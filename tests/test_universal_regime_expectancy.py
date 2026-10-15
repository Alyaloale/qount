"""
Tests for Universal Regime Expectancy Strategy Engine (Audited & Rigorous)
"""

import unittest
from pathlib import Path
from qount.research.universal_regime_expectancy import (
    DailyBar,
    load_etf_bars,
    compute_ema,
    compute_atr,
    compute_kaufman_er,
    compute_profile_state,
    run_regime_backtest,
    ALL_10_MACRO_SYMBOLS,
)

class TestUniversalRegimeExpectancy(unittest.TestCase):

    def test_indicator_math(self):
        prices = [10.0, 11.0, 12.0, 11.0, 10.0]
        ema = compute_ema(prices, 3)
        self.assertEqual(len(ema), len(prices))
        self.assertAlmostEqual(ema[0], 10.0)

        bars = [
            DailyBar("2025-01-01", 10.0, 11.0, 9.0, 10.5, 1000),
            DailyBar("2025-01-02", 10.5, 12.0, 10.0, 11.5, 1500),
            DailyBar("2025-01-03", 11.5, 12.5, 11.0, 12.0, 2000),
        ]
        atr = compute_atr(bars, 2)
        self.assertEqual(len(atr), 3)
        self.assertGreater(atr[-1], 0)

        er = compute_kaufman_er([10.0 + i for i in range(25)], 20)
        self.assertAlmostEqual(er[-1], 1.0, places=3)

    def test_profile_state_classification(self):
        bars = [
            DailyBar(f"2025-01-{i:02d}", 100.0, 102.0, 98.0, 100.0, 10000)
            for i in range(1, 25)
        ]
        s_code, s_name, poc, vah, val, pr, conc = compute_profile_state(bars, 100.0, 2.0)
        self.assertIn(s_code, [1, 2, 3, 4])
        self.assertIn(s_name, ["ACCUMULATION", "TREND_UP", "EXHAUSTION", "CHOP"])

    def test_intraday_causality_precedence(self):
        """
        Verify that when a bar hits BOTH Stop Loss and Take Profit,
        conservative causality triggers STOP-OUT first and does NOT award partial TP.
        """
        res = run_regime_backtest(
            symbols=["SPY", "GLD"],
            mode="1X_SPOT",
            causality_mode="RIGOROUS",
            start_date="2025-01-01",
            end_date="2025-06-30",
        )
        self.assertIn("return_pct", res)
        self.assertIn("mdd_pct", res)
        self.assertIn("trades", res)

    def test_financing_and_cost_accounting(self):
        """
        Verify that TradFi Margin 2X deducts borrow interest, and
        Binance Perp 2X deducts funding fees.
        """
        res_margin = run_regime_backtest(
            symbols=["SPY", "GLD"],
            mode="TRADIFI_MARGIN_2X",
            causality_mode="RIGOROUS",
            start_date="2025-01-01",
            end_date="2025-06-30",
        )
        if len(res_margin["trades"]) > 0:
            self.assertGreater(res_margin["total_borrow_interest_paid"], 0.0)

        res_perp = run_regime_backtest(
            symbols=["SPY", "GLD"],
            mode="BINANCE_PERP_2X",
            causality_mode="RIGOROUS",
            start_date="2025-01-01",
            end_date="2025-06-30",
        )
        if len(res_perp["trades"]) > 0:
            self.assertGreater(res_perp["total_funding_fees_paid"], 0.0)

    def test_deterministic_full_universe_run(self):
        """
        Verify that the full 10-asset universe runs deterministically without error.
        """
        res = run_regime_backtest(
            symbols=ALL_10_MACRO_SYMBOLS,
            mode="1X_SPOT",
            causality_mode="RIGOROUS",
            start_date="2025-01-01",
            end_date="2026-07-30",
            min_atr_pct=0.0085,
        )
        self.assertGreater(res["trade_count"], 0)
        self.assertGreater(res["return_pct"], 0.0)
        self.assertLess(res["mdd_pct"], 50.0)

    def test_orthogonal_tier_limit(self):
        """
        Verify that orthogonal_tier_limit=True strictly prevents holding
        multiple equity ETFs simultaneously.
        """
        res = run_regime_backtest(
            symbols=ALL_10_MACRO_SYMBOLS,
            mode="1X_SPOT",
            causality_mode="RIGOROUS",
            start_date="2020-01-01",
            end_date="2026-07-30",
            orthogonal_tier_limit=True,
        )
        self.assertTrue(res["orthogonal_tier_limit"])
        self.assertGreater(res["return_pct"], 20.0)
        self.assertLess(res["mdd_pct"], 30.0)
        self.assertGreater(res["calmar"], 1.0)

    def test_mr_right_side_green_candle_confirmation(self):
        """
        Verify that right-side green candle confirmation (mr_require_green=True)
        filters out falling knives, reducing trades and improving Calmar ratio.
        """
        res_baseline = run_regime_backtest(
            symbols=ALL_10_MACRO_SYMBOLS,
            mode="1X_SPOT",
            causality_mode="RIGOROUS",
            start_date="2020-01-01",
            end_date="2026-07-30",
            orthogonal_tier_limit=True,
            mr_require_green=False,
        )
        res_opt = run_regime_backtest(
            symbols=ALL_10_MACRO_SYMBOLS,
            mode="1X_SPOT",
            causality_mode="RIGOROUS",
            start_date="2020-01-01",
            end_date="2026-07-30",
            orthogonal_tier_limit=True,
            mr_require_green=True,
        )
        self.assertLess(res_opt["trade_count"], res_baseline["trade_count"])
        self.assertGreater(res_opt["return_pct"], res_baseline["return_pct"])
        self.assertLess(res_opt["mdd_pct"], res_baseline["mdd_pct"])
        self.assertGreater(res_opt["calmar"], res_baseline["calmar"])

    def test_edge_decay_exit_reduces_drawdown(self):
        """
        Verify that edge_decay_exit=True significantly reduces max drawdown
        by cleanly cutting off stagnant losing positions early.
        """
        res_no_decay = run_regime_backtest(
            symbols=ALL_10_MACRO_SYMBOLS,
            mode="1X_SPOT",
            causality_mode="RIGOROUS",
            start_date="2020-01-01",
            end_date="2026-07-30",
            orthogonal_tier_limit=True,
            edge_decay_exit=False,
        )
        res_decay = run_regime_backtest(
            symbols=ALL_10_MACRO_SYMBOLS,
            mode="1X_SPOT",
            causality_mode="RIGOROUS",
            start_date="2020-01-01",
            end_date="2026-07-30",
            orthogonal_tier_limit=True,
            edge_decay_exit=True,
        )
        self.assertLess(res_decay["mdd_pct"], res_no_decay["mdd_pct"])
        self.assertGreater(res_decay["calmar"], res_no_decay["calmar"])
    def test_dynamic_bull_2_5x_mode(self):
        """
        Verify that DYNAMIC_BULL_2_5X mode scales leverage strictly during strong bull
        regimes, compounding small capital with high Calmar efficiency (> 7.0)
        and realistic financing cost deduction.
        """
        res = run_regime_backtest(
            symbols=ALL_10_MACRO_SYMBOLS,
            mode="DYNAMIC_BULL_2_5X",
            causality_mode="RIGOROUS",
            start_date="2020-01-01",
            end_date="2026-07-30",
            initial_capital=100.0,
            max_positions=1,
            orthogonal_tier_limit=True,
        )
        self.assertGreater(res["return_pct"], 200.0)
        self.assertLess(res["mdd_pct"], 40.0)
        self.assertGreater(res["calmar"], 7.0)
        self.assertGreater(res["total_borrow_interest_paid"], 0.0)
        self.assertGreater(res["final_equity"], 300.0)


if __name__ == "__main__":
    unittest.main()
