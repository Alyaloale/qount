from __future__ import annotations

import unittest
from dataclasses import replace

from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.pilot_300_research import PILOT_300_PROTOCOL
from qount.mini_trend.pilot_300_research import build_pilot_300_research_report


_T0 = 1_609_459_200_000
_DAY_MS = 86_400_000


def _bars(count: int = 235) -> dict[str, list[Bar]]:
    rows = []
    for index in range(count):
        close = 100.0 * (1.001**index)
        rows.append(
            Bar(
                _T0 + index * _DAY_MS,
                close,
                close * 1.01,
                close * 0.99,
                close,
                1_000.0,
            )
        )
    return {symbol: list(rows) for symbol in TOP3}


def _funding(count: int = 235) -> dict[str, list[Funding]]:
    rows = [Funding(_T0 + index * _DAY_MS, 0.0) for index in range(count)]
    return {symbol: list(rows) for symbol in TOP3}


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {
                "symbol": symbol,
                "status": "TRADING",
                "min_qty": "0.000001",
                "min_notional": "5",
            }
            for symbol in TOP3
        ],
    }


class MiniTrendPilot300ResearchTest(unittest.TestCase):
    def test_fixed_candidate_comparison_is_research_only(self) -> None:
        inputs = {
            "2021-2026-full": {
                "bars": _bars(),
                "funding": _funding(),
            }
        }
        report = build_pilot_300_research_report(inputs, _rules())
        candidates = report["windows"]["2021-2026-full"]["candidates"]
        self.assertEqual(
            set(candidates),
            {"base_v0.2", "global_risk_2pct", "stop_latch", "funding_veto"},
        )
        self.assertEqual(report["contract"]["capital_usdt"], 300.0)
        self.assertIsNone(report["contract"]["daily_account_loss_halt_pct"])
        self.assertEqual(report["contract"]["pilot_drawdown_halt_pct"], 10.0)
        self.assertFalse(report["meta"]["paper_or_live_allowed"])
        self.assertFalse(report["diagnostics"]["candidate_promotion_allowed"])
        for summary in report["rolling_30_day_pilots"]["summaries"].values():
            self.assertEqual(summary["episode_count"], 1)

    def test_consumed_historical_research_capital_remains_frozen(self) -> None:
        with self.assertRaisesRegex(ValueError, "capital"):
            build_pilot_300_research_report(
                {
                    "2021-2026-full": {
                        "bars": _bars(),
                        "funding": _funding(),
                    }
                },
                _rules(),
                protocol=replace(PILOT_300_PROTOCOL, capital_usdt=299.0),
            )


if __name__ == "__main__":
    unittest.main()
