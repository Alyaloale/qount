from __future__ import annotations

import unittest

from qount.mini_trend.scorecard import build_scorecard, max_drawdown_pct, scorecard_from_events


class TestMiniTrendScorecard(unittest.TestCase):
    def test_missing_fields_cannot_pass(self) -> None:
        sc = build_scorecard({"max_drawdown_pct": 0.0})
        self.assertEqual(sc.verdict, "block")
        self.assertIn("schema_error_count", sc.missing_fields)

    def test_passes_when_required_metrics_clean(self) -> None:
        sc = build_scorecard(
            {
                "max_drawdown_pct": 5.0,
                "fee_to_notional_pct": 0.08,
                "order_count": 10,
                "min_notional_coverage": 1.0,
                "stop_reentry_count": 0,
                "unmanaged_position_count": 0,
                "schema_error_count": 0,
            }
        )
        self.assertEqual(sc.verdict, "pass")

    def test_coverage_below_gate_blocks(self) -> None:
        sc = build_scorecard(
            {
                "max_drawdown_pct": 5.0,
                "fee_to_notional_pct": 0.08,
                "order_count": 10,
                "min_notional_coverage": 0.5,
                "stop_reentry_count": 0,
                "unmanaged_position_count": 0,
                "schema_error_count": 0,
            }
        )
        self.assertEqual(sc.verdict, "block")

    def test_scorecard_from_events_computes_core_metrics(self) -> None:
        orders = [
            {"est_usdt": 100.0, "fee_usdt": 0.08},
            {"est_usdt": 200.0, "fee_usdt": 0.16},
        ]
        sc = scorecard_from_events(
            equity_curve=[100.0, 110.0, 90.0, 120.0],
            orders=orders,
            min_notional_checks=[True, True],
            stop_reentry_count=0,
            unmanaged_position_count=0,
            schema_error_count=0,
        )
        self.assertEqual(sc.metrics["order_count"], 2)
        self.assertAlmostEqual(sc.metrics["fee_to_notional_pct"], 0.08)
        self.assertAlmostEqual(sc.metrics["max_drawdown_pct"], max_drawdown_pct([100.0, 110.0, 90.0, 120.0]))
        self.assertEqual(sc.verdict, "pass")


if __name__ == "__main__":
    unittest.main()
