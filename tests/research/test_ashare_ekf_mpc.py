"""Unit tests for A-share EKF-MPC Dynamic Allocation & Fast-Escape Strategy."""
from __future__ import annotations

import math
import unittest

from qount.research.ashare_ekf_mpc import (
    AssetBar,
    DampedKalmanTracker,
    EKFMPCSimulator,
    evaluate_ekf_mpc_performance,
)


class TestDampedKalmanTracker(unittest.TestCase):
    """Test state space dynamics, velocity, acceleration, and forecast."""

    def test_initialization(self):
        tracker = DampedKalmanTracker()
        self.assertIsNone(tracker.x)
        self.assertEqual(tracker.level, 0.0)
        self.assertEqual(tracker.velocity, 0.0)
        self.assertEqual(tracker.ksnr, 0.0)

    def test_upward_drift_detection(self):
        tracker = DampedKalmanTracker()
        # Feed an exponentially growing price series
        prices = [10.0 * (1.02 ** i) for i in range(30)]
        for p in prices:
            s, v, a, ksnr = tracker.update(p)
        
        self.assertGreater(v, 0.005, "Drift velocity should be clearly positive")
        self.assertGreater(ksnr, 1.0, "Kalman SNR should reflect high significance")
        self.assertAlmostEqual(tracker.level, math.log(prices[-1]), delta=0.05)

    def test_downward_drift_detection(self):
        tracker = DampedKalmanTracker()
        # Feed a decaying price series
        prices = [100.0 * (0.98 ** i) for i in range(30)]
        for p in prices:
            s, v, a, ksnr = tracker.update(p)
            
        self.assertLess(v, -0.005, "Drift velocity should be clearly negative")
        self.assertLess(ksnr, -1.0, "Kalman SNR should be negative")

    def test_horizon_forecasting(self):
        tracker = DampedKalmanTracker()
        prices = [10.0 * (1.01 ** i) for i in range(25)]
        for p in prices:
            tracker.update(p)
            
        fwd_5 = tracker.forecast_return(horizon=5)
        fwd_15 = tracker.forecast_return(horizon=15)
        self.assertGreater(fwd_5, 0.0)
        self.assertGreater(fwd_15, fwd_5, "Longer horizon projection should be larger on uptrend")


class TestFastEscapeRiskModel(unittest.TestCase):
    """Test fast hard-stop, break-even profit lock, and trailing exits."""

    def _make_dummy_bars(self, prices: list[float], dates: list[str]) -> list[AssetBar]:
        return [
            AssetBar(trade_date=d, open=p, high=p * 1.01, low=p * 0.99, close=p)
            for d, p in zip(dates, prices)
        ]

    def test_fast_hard_stop_execution(self):
        dates = [f"202301{i+1:02d}" for i in range(31)] + [f"202302{i+1:02d}" for i in range(10)]
        bench_prices = [100.0] * len(dates)
        
        # Asset stays around 10.0, breaks out to 12.0 on day 32, fills buy on day 33 at 12.0,
        # then plunges to 11.0 on day 33 close (-8.33% loss from 12.0 entry), triggering hard stop on day 34
        asset_prices = [10.0] * 32 + [12.0, 12.0, 11.0, 11.0, 11.0, 11.0, 11.0, 11.0, 11.0]
        
        bars = {
            "000300.SH": self._make_dummy_bars(bench_prices, dates),
            "TEST_ASSET": self._make_dummy_bars(asset_prices, dates),
        }
        
        sim = EKFMPCSimulator(commission_bps=0.0, slippage_bps=0.0)
        res = sim.run(
            bars_dict=bars,
            universe=["TEST_ASSET"],
            top_n=1,
            fast_hard_stop=0.065,
            macro_filter=False,
        )
        
        sell_trades = [t for t in res.trades if t.action == "SELL"]
        self.assertGreaterEqual(len(sell_trades), 1)
        self.assertEqual(sell_trades[0].reason, "FAST_HARD_STOP")

    def test_breakeven_lock_execution(self):
        dates = [f"202301{i+1:02d}" for i in range(31)] + [f"202302{i+1:02d}" for i in range(15)]
        bench_prices = [100.0] * len(dates)
        
        # Asset: 10.0 baseline -> breaks out to 11.0 on day 32 -> buys on day 33 at 11.0
        # surges to 12.5 (+13.6% >= 12% trigger) on day 34 -> retreats to 11.1 on day 35 (<= 11.0 * 1.015 = 11.165)
        asset_prices = [10.0] * 32 + [11.0, 11.0, 12.5, 11.1, 11.1, 11.1, 11.1, 11.1, 11.1, 11.1, 11.1]
        
        bars = {
            "000300.SH": self._make_dummy_bars(bench_prices, dates),
            "TEST_ASSET": self._make_dummy_bars(asset_prices, dates),
        }
        
        sim = EKFMPCSimulator(commission_bps=0.0, slippage_bps=0.0)
        res = sim.run(
            bars_dict=bars,
            universe=["TEST_ASSET"],
            top_n=1,
            fast_hard_stop=0.065,
            breakeven_trigger=0.12,
            trailing_stop_pct=0.25, # High trailing stop so breakeven lock triggers first
            macro_filter=False,
        )
        
        sell_trades = [t for t in res.trades if t.action == "SELL"]
        self.assertGreaterEqual(len(sell_trades), 1)
        self.assertEqual(sell_trades[0].reason, "BREAK_EVEN_LOCK")
        self.assertGreater(sell_trades[0].pnl, 0.0, "Break-even lock must guarantee positive PnL")


class TestEKFMPCSimulator(unittest.TestCase):
    """Test dynamic allocation, top_n weighting, and four standard curves."""

    def _make_dummy_bars(self, prices: list[float], dates: list[str]) -> list[AssetBar]:
        return [
            AssetBar(trade_date=d, open=p, high=p * 1.01, low=p * 0.99, close=p)
            for d, p in zip(dates, prices)
        ]

    def test_asymmetric_weighting(self):
        # Create 2 candidate assets breaking out simultaneously with different momentum
        dates = [f"202301{i+1:02d}" for i in range(31)] + [f"202302{i+1:02d}" for i in range(10)]
        bench_prices = [100.0] * len(dates)
        
        # Asset 1 surges +30%
        prices_1 = [10.0] * 32 + [11.0, 12.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0]
        # Asset 2 surges +15%
        prices_2 = [10.0] * 32 + [10.5, 10.8, 11.0, 11.0, 11.0, 11.0, 11.0, 11.0, 11.0]
        
        bars = {
            "000300.SH": self._make_dummy_bars(bench_prices, dates),
            "SYM_1": self._make_dummy_bars(prices_1, dates),
            "SYM_2": self._make_dummy_bars(prices_2, dates),
        }
        
        sim = EKFMPCSimulator(commission_bps=0.0, slippage_bps=0.0)
        res = sim.run(
            bars_dict=bars,
            universe=["SYM_1", "SYM_2"],
            top_n=2,
            top1_weight=0.65,
            top2_weight=0.35,
            macro_filter=False,
        )
        
        buy_trades = [t for t in res.trades if t.action == "BUY"]
        self.assertEqual(len(buy_trades), 2)
        # Verify that Top 1 has roughly 65% cash flow and Top 2 has 35%
        cost_1 = abs(buy_trades[0].cash_flow)
        cost_2 = abs(buy_trades[1].cash_flow)
        self.assertGreater(cost_1, cost_2 * 1.5, "Top 1 should receive ~65% while Top 2 receives ~35%")

    def test_scoring_mode_options(self):
        dates = [f"202301{i+1:02d}" for i in range(31)] + [f"202302{i+1:02d}" for i in range(10)]
        bench_prices = [100.0] * len(dates)
        prices = [10.0] * 32 + [11.0, 12.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0]
        bars = {
            "000300.SH": self._make_dummy_bars(bench_prices, dates),
            "SYM_1": self._make_dummy_bars(prices, dates),
        }
        sim = EKFMPCSimulator(commission_bps=0.0, slippage_bps=0.0)
        for mode in ["base", "with_accel", "composite_master"]:
            res = sim.run(
                bars_dict=bars,
                universe=["SYM_1"],
                scoring_mode=mode,
                macro_filter=False,
            )
            self.assertGreater(len(res.trades), 0)


if __name__ == "__main__":
    unittest.main()
