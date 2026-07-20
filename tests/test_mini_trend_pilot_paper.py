from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from qount.grid.data import Bar, Funding
from qount.mini_trend.forward import TOP3
from qount.mini_trend.pilot_paper import PILOT_PAPER_PROTOCOL
from qount.mini_trend.pilot_paper import build_pilot_paper_replay
from qount.mini_trend.pilot_paper import reconcile_pilot_paper_journal
from qount.mini_trend.live_pilot import verify_live_pilot_journal


_DAY_MS = 86_400_000
_START = dt.datetime(2026, 7, 19, tzinfo=dt.UTC)
_T0 = int((_START - dt.timedelta(days=200)).timestamp() * 1000)


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


def _bars(count: int, *, crash_outcome: bool = False) -> dict[str, list[Bar]]:
    rows = []
    for index in range(count):
        close = 100.0 * (1.002**index)
        if crash_outcome and index == 201:
            close *= 0.1
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


def _funding(count: int, *, omit_last_day: bool = False) -> dict[str, list[Funding]]:
    rows = []
    upper = count - 1 if omit_last_day else count
    for index in range(upper):
        day = _T0 + index * _DAY_MS
        rows.extend(
            [
                Funding(day + 8 * 3_600_000, 0.0),
                Funding(day + 16 * 3_600_000, 0.0),
                Funding(day + _DAY_MS, 0.0),
            ]
        )
    return {symbol: list(rows) for symbol in TOP3}


class MiniTrendPilotPaperTest(unittest.TestCase):
    def test_no_completed_pair_is_an_explicit_wait_state(self) -> None:
        replay = build_pilot_paper_replay(_bars(201), _funding(201), _rules())
        self.assertEqual(replay.report["diagnostics"]["verdict"], "await_paper_inputs")
        self.assertEqual(replay.report["evaluation"]["paper_days"], 0)
        self.assertFalse(replay.report["meta"]["live_orders_allowed"])
        self.assertEqual(
            set(replay.report["evaluation"]["shadow_paths"]),
            {
                "MiniTrend-UM-RiskTier-v0.2",
                "MiniTrend-UM-FundingVeto-v0.1",
            },
        )
        self.assertTrue(
            all(
                row["end_equity_usdt"] == 300.0
                and not row["controls_live_orders"]
                for row in replay.report["evaluation"]["shadow_paths"].values()
            )
        )
        self.assertEqual(replay.journal_rows, ())

    def test_complete_pairs_start_from_three_hundred_usdt_cash(self) -> None:
        replay = build_pilot_paper_replay(_bars(203), _funding(203), _rules())
        self.assertEqual(replay.report["evaluation"]["paper_days"], 2)
        self.assertEqual(replay.report["evaluation"]["start_equity_usdt"], 300.0)
        self.assertEqual(
            replay.journal_rows[0]["decision_date"],
            PILOT_PAPER_PROTOCOL.paper_start_date,
        )
        self.assertFalse(replay.report["meta"]["private_api_order_attempted"])
        self.assertEqual(
            set(replay.report["evaluation"]["shadow_paths"]),
            {
                "MiniTrend-UM-RiskTier-v0.2",
                "MiniTrend-UM-FundingVeto-v0.1",
            },
        )
        self.assertTrue(
            all(
                not row["controls_live_orders"]
                for row in replay.report["evaluation"]["shadow_paths"].values()
            )
        )
        self.assertEqual(
            set(replay.journal_rows[0]["shadow_paths"]),
            set(replay.report["evaluation"]["shadow_paths"]),
        )
        self.assertEqual(
            replay.report["diagnostics"]["verdict"], "collect_paper_evidence"
        )

    def test_incomplete_funding_cannot_create_paper_rows(self) -> None:
        replay = build_pilot_paper_replay(
            _bars(203),
            _funding(203, omit_last_day=True),
            _rules(),
        )
        self.assertLess(len(replay.journal_rows), 2)
        self.assertIsNotNone(replay.report["data"]["first_incomplete_pair"])

    def test_journal_reconcile_is_append_only_and_idempotent(self) -> None:
        replay = build_pilot_paper_replay(_bars(203), _funding(203), _rules())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.jsonl"
            first = reconcile_pilot_paper_journal(path, replay.journal_rows)
            second = reconcile_pilot_paper_journal(path, replay.journal_rows)
            verified = verify_live_pilot_journal(path)
            persisted = path.read_text(encoding="utf-8")
        self.assertEqual(first["appended_rows"], 2)
        self.assertEqual(second["appended_rows"], 0)
        self.assertEqual(verified["row_count"], 2)
        self.assertIn('"shadow_paths"', persisted)

    def test_pilot_drawdown_breach_halts_without_a_daily_loss_gate(self) -> None:
        replay = build_pilot_paper_replay(
            _bars(203, crash_outcome=True),
            _funding(203),
            _rules(),
        )
        self.assertEqual(replay.report["diagnostics"]["verdict"], "paper_risk_halted")
        self.assertTrue(replay.report["evaluation"]["halted"])
        self.assertNotIn("daily_loss_halt", replay.report["evaluation"]["risk_flags"])
        self.assertIn("pilot_drawdown_halt", replay.report["evaluation"]["risk_flags"])
        self.assertEqual(len(replay.journal_rows), 1)


if __name__ == "__main__":
    unittest.main()
