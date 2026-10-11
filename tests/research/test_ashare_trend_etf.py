"""Unit tests for A-share ETF trend timing research module."""
import unittest
from qount.research.ashare_trend_etf import (
    DailyBar,
    MovingAverageEngine,
    TrendETFAssistantSimulator,
    compute_drawdowns,
)


class TestAshareTrendETF(unittest.TestCase):
    def test_moving_average_engine_sma(self):
        closes = [10.0, 11.0, 12.0, 13.0, 14.0]
        sma3 = MovingAverageEngine.sma(closes, 3)
        self.assertIsNone(sma3[0])
        self.assertIsNone(sma3[1])
        self.assertAlmostEqual(sma3[2], 11.0)
        self.assertAlmostEqual(sma3[3], 12.0)
        self.assertAlmostEqual(sma3[4], 13.0)

    def test_moving_average_engine_ema(self):
        closes = [10.0, 10.0, 10.0, 10.0]
        ema2 = MovingAverageEngine.ema(closes, 2)
        self.assertIsNone(ema2[0])
        self.assertAlmostEqual(ema2[1], 10.0)
        self.assertAlmostEqual(ema2[2], 10.0)
        self.assertAlmostEqual(ema2[3], 10.0)

    def test_compute_drawdowns(self):
        navs = [100.0, 120.0, 90.0, 110.0, 60.0]
        dds, max_dd = compute_drawdowns(navs)
        self.assertEqual(len(dds), 5)
        self.assertAlmostEqual(dds[0], 0.0)
        self.assertAlmostEqual(dds[1], 0.0)
        self.assertAlmostEqual(dds[2], (120.0 - 90.0) / 120.0)  # 25%
        self.assertAlmostEqual(max_dd, 0.5)  # (120 - 60) / 120 = 50%

    def test_causal_signal_execution(self):
        # 10 bars: first 5 flat at 10.0, day 6 breaks out to 15.0, day 7 stays 15.0
        bars = [
            DailyBar("20240101", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240102", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240103", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240104", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240105", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240108", 12.0, 15.0, 12.0, 15.0), # Breakout on close!
            DailyBar("20240109", 15.0, 16.0, 15.0, 15.0),
            DailyBar("20240110", 15.0, 15.0, 15.0, 15.0),
        ]
        sim = TrendETFAssistantSimulator(
            commission_bps=0.0,
            slippage_bps=0.0,
            annual_cash_yield=0.0,
            initial_capital=100_000.0,
        )
        # Period 3 SMA, confirm_days=1, band_pct=0.0
        res = sim.simulate_single_asset_trend(bars, ma_period=3, band_pct=0.0, confirm_days=1)
        self.assertTrue(len(res.trades) > 0)
        first_trade = res.trades[0]
        # Signal on 20240108 close -> execution MUST be on 20240109 open!
        self.assertEqual(first_trade.trade_date, "20240109")
        self.assertEqual(first_trade.action, "BUY")
        self.assertEqual(first_trade.price, 15.0)

    def test_dual_asset_rotation_logic(self):
        bars_a = [
            DailyBar("20240101", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240102", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240103", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240104", 12.0, 15.0, 12.0, 15.0),
            DailyBar("20240105", 15.0, 16.0, 15.0, 16.0),
        ]
        bars_b = [
            DailyBar("20240101", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240102", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240103", 9.0, 9.0, 8.0, 8.0),
            DailyBar("20240104", 8.0, 8.0, 7.0, 7.0),
            DailyBar("20240105", 7.0, 7.0, 6.0, 6.0),
        ]
        sim = TrendETFAssistantSimulator(
            commission_bps=5.0,
            slippage_bps=5.0,
            annual_cash_yield=0.02,
            initial_capital=100_000.0,
        )
        res = sim.simulate_dual_asset_rotation(
            bars_a, bars_b,
            symbol_a="CSI300",
            symbol_b="CSI500",
            ma_period=2,
            momentum_window=1,
            band_pct=0.0,
            confirm_days=1,
        )
        self.assertIsNotNone(res.metrics)
        self.assertTrue(len(res.snapshots) == 5)

    def test_trend_dividend_shield_logic(self):
        bars_t = [
            DailyBar("20240101", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240102", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240103", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240104", 12.0, 15.0, 12.0, 15.0), # Bull breakout
            DailyBar("20240105", 15.0, 16.0, 15.0, 16.0),
        ]
        bars_s = [
            DailyBar("20240101", 5.0, 5.0, 5.0, 5.0),
            DailyBar("20240102", 5.0, 5.0, 5.0, 5.0),
            DailyBar("20240103", 5.0, 5.0, 5.0, 5.0),
            DailyBar("20240104", 5.0, 5.0, 5.0, 5.0),
            DailyBar("20240105", 5.0, 5.0, 5.0, 5.0),
        ]
        sim = TrendETFAssistantSimulator(
            commission_bps=5.0,
            slippage_bps=5.0,
            annual_cash_yield=0.02,
            initial_capital=100_000.0,
        )
        res = sim.simulate_trend_dividend_shield(
            bars_t, bars_s,
            symbol_trend="CSI300",
            symbol_shield="DIV",
            ma_period=2,
            band_pct=0.0,
            confirm_days=1,
            shield_mode="DIV_50_CASH_50",
        )
        self.assertIsNotNone(res.metrics)
        self.assertEqual(len(res.snapshots), 5)
        # Should have executed trades
        self.assertTrue(len(res.trades) > 0)

    def test_donchian_high_and_atr(self):
        highs = [10.0, 12.0, 11.0, 15.0, 14.0]
        lows = [9.0, 10.0, 10.0, 12.0, 12.0]
        closes = [9.5, 11.0, 10.5, 14.0, 13.0]
        d_high = MovingAverageEngine.donchian_high(highs, 2)
        self.assertIsNone(d_high[0])
        self.assertIsNone(d_high[1])
        self.assertEqual(d_high[2], 12.0)
        self.assertEqual(d_high[3], 12.0)
        self.assertEqual(d_high[4], 15.0)

        atr = MovingAverageEngine.atr(highs, lows, closes, 2)
        self.assertIsNone(atr[0])
        self.assertIsNotNone(atr[1])
        self.assertTrue(atr[1] > 0)

    def test_asymmetric_trend_simulation(self):
        bars_t = [
            DailyBar("20240101", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240102", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240103", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240104", 12.0, 15.0, 12.0, 15.0),
            DailyBar("20240105", 15.0, 16.0, 15.0, 16.0),
        ]
        sim = TrendETFAssistantSimulator()
        res = sim.simulate_asymmetric_trend(
            bars_t,
            entry_donchian_window=2,
            exit_ma_period=2,
            band_pct=0.0,
            trailing_stop_pct=0.10,
            shield_mode="CASH_100",
        )
        self.assertIsNotNone(res.metrics)
        self.assertEqual(len(res.snapshots), 5)

    def test_atr_dynamic_band_simulation(self):
        bars_t = [
            DailyBar("20240101", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240102", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240103", 10.0, 10.0, 10.0, 10.0),
            DailyBar("20240104", 12.0, 15.0, 12.0, 15.0),
            DailyBar("20240105", 15.0, 16.0, 15.0, 16.0),
        ]
        sim = TrendETFAssistantSimulator()
        res = sim.simulate_atr_dynamic_band_trend(
            bars_t,
            ma_period=2,
            atr_period=2,
            atr_multiplier=1.0,
            confirm_days=1,
            shield_mode="CASH_100",
        )
        self.assertIsNotNone(res.metrics)
        self.assertEqual(len(res.snapshots), 5)

    def test_core_satellite_simulation(self):
        bars_a = [DailyBar(f"2024010{i}", 10.0, 10.0, 10.0, 10.0) for i in range(1, 6)]
        bars_b = [DailyBar(f"2024010{i}", 5.0, 5.0, 5.0, 5.0) for i in range(1, 6)]
        bars_c = [DailyBar(f"2024010{i}", 20.0, 20.0, 20.0, 20.0) for i in range(1, 6)]
        sim = TrendETFAssistantSimulator()
        res = sim.simulate_core_satellite_portfolio(
            bars_a, bars_b, bars_c,
            core_weight=0.8,
            satellite_weight=0.2,
            core_ma_period=2,
            satellite_ma_period=2,
        )
        self.assertIsNotNone(res.metrics)
        self.assertEqual(len(res.snapshots), 5)


if __name__ == "__main__":
    unittest.main()
