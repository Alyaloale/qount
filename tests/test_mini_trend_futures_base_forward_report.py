from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_base_forward import build_futures_base_forward_preregistration
from qount.mini_trend.futures_base_forward import FUTURES_BASE_FORWARD_PROTOCOL
from qount.mini_trend.futures_base_forward_report import build_base_forward_report


_T0 = 1_609_459_200_000
_DAY = 86_400_000


def _bars() -> list[Bar]:
    return [
        Bar(_T0 + i * _DAY, 100.0, 101.0, 99.0, 100.0, 1000.0)
        for i in range(220)
    ]


def _rules() -> dict:
    return {
        "market": "um",
        "source_type": "runtime_exchange_info",
        "rules": [
            {"symbol": symbol, "status": "TRADING", "min_qty": "0.001", "min_notional": "5"}
            for symbol in TOP3
        ],
    }


class MiniTrendFuturesBaseForwardReportTest(unittest.TestCase):
    def test_no_new_bars_is_explicit_wait_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lessons = root / "lessons.json"
            lessons.write_text(
                json.dumps(
                    {
                        "schema_version": "mini_trend_live_lessons_v0.1",
                        "verdict": "audit_complete_research_only",
                        "candidate_constraints": {"carry_allowed": False, "market": "um_futures"},
                        "equity": {"inception_to_pre_withdrawal_return_pct": -2.0, "july_rebound_giveback_usdt": -25},
                        "orders": {"post_inception_placed_order_count": 37, "exact_duplicate_order_count": 5, "same_bar_direction_flip_group_count": 8},
                        "operations": {"fail_closed_unknown_capital_count": 66},
                    }
                ),
                encoding="utf-8",
            )
            prereg = build_futures_base_forward_preregistration(_rules(), lessons)
            report = build_base_forward_report(
                {symbol: _bars() for symbol in TOP3},
                {symbol: [Funding(_T0, 0.0)] for symbol in TOP3},
                _rules(),
                prereg,
                str(lessons),
            )
        self.assertEqual(report["diagnostics"]["verdict"], "await_forward_data")
        self.assertEqual(
            prereg["decision_contract"]["stops"]["daily_chandelier_atr_multiple"],
            FUTURES_BASE_FORWARD_PROTOCOL.daily_chandelier_atr_multiple,
        )
        self.assertFalse(report["meta"]["strategy_results_evaluated"])
        self.assertEqual(report["data"]["evaluation_bar_count"], 0)
        self.assertIn(
            "no_completed_bars_on_or_after_forward_start",
            report["diagnostics"]["blockers"],
        )


if __name__ == "__main__":
    unittest.main()
