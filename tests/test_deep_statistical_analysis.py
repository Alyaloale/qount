"""
Tests for Deep Institutional Statistical Analysis Suite
"""

import unittest
from scripts.research.deep_statistical_analysis_universal_regime import (
    compute_underwater_stats,
    compute_advanced_time_series_stats,
    compute_trade_microstructure,
    perform_hypothesis_testing,
    perform_monte_carlo_permutation,
)


class TestDeepStatisticalAnalysis(unittest.TestCase):

    def test_underwater_stats(self):
        curve = [
            ("2025-01-01", 100.0),
            ("2025-01-02", 105.0),
            ("2025-01-03", 95.0),
            ("2025-01-04", 100.0),
            ("2025-01-05", 110.0),
        ]
        stats = compute_underwater_stats(curve)
        self.assertAlmostEqual(stats["max_drawdown_pct"], (105.0 - 95.0) / 105.0 * 100.0, places=2)
        self.assertGreater(stats["ulcer_index"], 0.0)
        self.assertGreater(stats["pain_index"], 0.0)
        self.assertEqual(len(stats["top_episodes"]), 1)
        self.assertEqual(stats["top_episodes"][0]["recovery_date"], "2025-01-05")

    def test_advanced_time_series_stats(self):
        curve = [
            ("2025-01-01", 100.0),
            ("2025-01-02", 101.0),
            ("2025-01-03", 102.0),
            ("2025-01-04", 101.5),
            ("2025-01-05", 103.0),
        ]
        stats = compute_advanced_time_series_stats(curve, annual_rf=0.035)
        self.assertIn("ann_cagr", stats)
        self.assertIn("ann_volatility", stats)
        self.assertIn("sharpe_ratio", stats)
        self.assertIn("sortino_ratio", stats)
        self.assertIn("skewness", stats)
        self.assertIn("excess_kurtosis", stats)
        self.assertIn("jarque_bera_p", stats)

    def test_trade_microstructure_and_hypothesis(self):
        trades = [
            {"net_pnl_usd": 10.0, "net_R": 1.0, "holding_days": 10, "type": "TREND_BREAKOUT", "exit_reason": "trailing_stop"},
            {"net_pnl_usd": -5.0, "net_R": -0.5, "holding_days": 3, "type": "TREND_BREAKOUT", "exit_reason": "initial_stop"},
            {"net_pnl_usd": 20.0, "net_R": 2.0, "holding_days": 15, "type": "MEAN_REVERSION", "exit_reason": "mr_tp"},
        ]
        m = compute_trade_microstructure(trades)
        self.assertEqual(m["trade_count"], 3)
        self.assertAlmostEqual(m["win_rate"], 66.67, places=1)
        self.assertAlmostEqual(m["profit_factor"], 30.0 / 5.0)
        self.assertGreater(m["avg_win_hold_days"], m["avg_loss_hold_days"])

        ht = perform_hypothesis_testing(m["r_multiples"], m["pnls"], n_bootstrap=100)
        self.assertIn("t_statistic", ht)
        self.assertIn("r_ci_95", ht)
        self.assertIn("bootstrap_p_value", ht)

    def test_monte_carlo_permutation(self):
        trades = [
            {"net_pnl_usd": 10.0},
            {"net_pnl_usd": -5.0},
            {"net_pnl_usd": 15.0},
            {"net_pnl_usd": -8.0},
        ]
        mc = perform_monte_carlo_permutation(trades, initial_capital=100.0, n_sims=100)
        self.assertIn("mdd_50th_median", mc)
        self.assertIn("mdd_95th_tail", mc)
        self.assertGreater(mc["mdd_95th_tail"], 0.0)


if __name__ == "__main__":
    unittest.main()
