from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qount.mini_trend.live_lessons import LIVE_LESSONS_VERSION
from qount.mini_trend.live_lessons import build_live_lessons_report


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class MiniTrendLiveLessonsTest(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        orders = [
            {
                "ts": "2026-06-18T12:00:00+00:00",
                "bar": "2026-06-17",
                "mode": "live",
                "armed": True,
                "n_placed": 1,
                "orders": [{"symbol": "BTC/USDT:USDT", "side": "sell", "base": 0.01, "est_usdt": 10}],
                "capital_blocked": [{"symbol": "ETHUSDT"}],
                "stopped": [],
            },
            {
                "ts": "2026-06-18T12:00:01+00:00",
                "bar": "2026-06-17",
                "mode": "live",
                "armed": True,
                "n_placed": 1,
                "orders": [{"symbol": "BTC/USDT:USDT", "side": "sell", "base": 0.01, "est_usdt": 10}],
                "capital_blocked": [],
                "stopped": [],
            },
            {
                "ts": "2026-06-18T12:01:00+00:00",
                "bar": "2026-06-17",
                "mode": "live",
                "armed": True,
                "n_placed": 1,
                "orders": [{"symbol": "BTC/USDT:USDT", "side": "buy", "base": 0.01, "est_usdt": 10}],
                "capital_blocked": [],
                "stopped": ["BTCUSDT"],
            },
        ]
        snapshots = [
            {
                "ts": "2026-06-18T12:00:00+00:00",
                "state": "short",
                "n_holdings": 2,
                "holdings": [{"s": "BTCUSDT", "value": -30}, {"s": "BNBUSDT", "value": -10}],
            }
        ]
        _write_jsonl(root / "orders.jsonl", orders)
        _write_jsonl(root / "snapshots.jsonl", snapshots)
        _write_json(
            root / "equity_daily.json",
            [
                {"day": "2026-06-18", "equity": 100},
                {"day": "2026-06-30", "equity": 110},
                {"day": "2026-07-11", "equity": 90},
            ],
        )
        _write_json(root / "inception.json", {"equity": 100, "ts": "2026-06-18T10:00:00+00:00"})
        _write_json(root / "stops.json", {"BTCUSDT": {"latched": True}})
        _write_json(
            root / "latest.json",
            {"equity": 50, "inception_equity": 100, "total_pnl_pct": -0.5},
        )
        (root / "cxd_live.log").write_text(
            "[X4-LIVE live]\n"
            "[ALERT] auto-capital missing -> SKIP trading this run\n"
            "wallet read failed, using fallback: $500\n"
            "skip BTCUSDT: below min_order (+0.00 USDT)\n"
            "[STOP-SYNC] BTCUSDT\n",
            encoding="utf-8",
        )

    def test_report_separates_withdrawal_from_strategy_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root)
            report = build_live_lessons_report(root)
        self.assertEqual(report["schema_version"], LIVE_LESSONS_VERSION)
        self.assertEqual(report["equity"]["inception_to_pre_withdrawal_return_pct"], -10.0)
        self.assertTrue(report["equity"]["latest_total_pnl_contaminated_by_external_flow"])
        self.assertEqual(report["equity"]["external_flow_gap_usdt"], 40.0)
        self.assertFalse(report["candidate_constraints"]["carry_allowed"])

    def test_report_detects_duplicate_flip_latch_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root)
            report = build_live_lessons_report(root)
            serialized = json.dumps(report)
        self.assertEqual(report["orders"]["post_inception_placed_order_count"], 3)
        self.assertEqual(report["orders"]["exact_duplicate_order_count"], 1)
        self.assertEqual(report["orders"]["same_bar_repeated_same_side_order_count"], 1)
        self.assertEqual(report["orders"]["same_bar_direction_flip_group_count"], 1)
        self.assertEqual(report["stops"]["final_latched_symbols"], ["BTCUSDT"])
        self.assertEqual(report["operations"]["fail_closed_unknown_capital_count"], 1)
        self.assertNotIn("auto-capital missing", serialized)

    def test_missing_input_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "missing files"):
                build_live_lessons_report(tmp)


if __name__ == "__main__":
    unittest.main()
