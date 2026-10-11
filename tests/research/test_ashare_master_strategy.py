"""Unit tests for A-Share Master Quantitative Trading Strategy (总终方案)."""
from __future__ import annotations

import math
import unittest

from qount.research.ashare_master_strategy import (
    MasterBar,
    DampedStateSpaceTracker,
    MasterStrategySimulator,
    evaluate_master_performance,
)


class TestMasterStrategyModule(unittest.TestCase):
    """Test state space filtering, multi-factor scoring, fast escape risk, and execution."""

    def _make_dummy_bars(self, prices: list[float], dates: list[str], vols: list[float] = None) -> list[MasterBar]:
        if vols is None:
            vols = [1000.0] * len(prices)
        return [
            MasterBar(trade_date=d, open=p, high=p * 1.01, low=p * 0.99, close=p, vol=v)
            for d, p, v in zip(dates, prices, vols)
        ]

    def test_state_space_convergence(self):
        tracker = DampedStateSpaceTracker()
        prices = [10.0 * (1.02 ** i) for i in range(30)]
        for p in prices:
            s, v, a, ksnr = tracker.update(p)
            
        self.assertGreater(v, 0.005, "Drift velocity must be positive on persistent trend")
        self.assertGreater(ksnr, 1.0, "Kalman SNR must reflect statistical significance")
        self.assertGreater(tracker.forecast_return(horizon=10), 0.0)

    def test_fast_hard_stop_and_breakeven_lock(self):
        # 1. Test fast hard stop execution
        dates = [f"202301{i+1:02d}" for i in range(31)] + [f"202302{i+1:02d}" for i in range(10)]
        bench_prices = [100.0] * len(dates)
        asset_prices = [10.0] * 32 + [12.0, 12.0, 11.0, 11.0, 11.0, 11.0, 11.0, 11.0, 11.0]

        bars = {
            "000300.SH": self._make_dummy_bars(bench_prices, dates),
            "TEST_ASSET": self._make_dummy_bars(asset_prices, dates),
        }

        sim = MasterStrategySimulator(commission_bps=0.0, slippage_bps=0.0)
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

    def test_master_asymmetric_allocation(self):
        dates = [f"202301{i+1:02d}" for i in range(31)] + [f"202302{i+1:02d}" for i in range(10)]
        bench_prices = [100.0] * len(dates)
        prices_1 = [10.0] * 32 + [11.0, 12.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 13.0]
        prices_2 = [10.0] * 32 + [10.5, 10.8, 11.0, 11.0, 11.0, 11.0, 11.0, 11.0, 11.0]

        bars = {
            "000300.SH": self._make_dummy_bars(bench_prices, dates),
            "SYM_1": self._make_dummy_bars(prices_1, dates, vols=[5000.0] * len(dates)),
            "SYM_2": self._make_dummy_bars(prices_2, dates, vols=[1000.0] * len(dates)),
        }

        sim = MasterStrategySimulator(commission_bps=0.0, slippage_bps=0.0)
        res = sim.run(
            bars_dict=bars,
            universe=["SYM_1", "SYM_2"],
            top_n=2,
            top1_weight=0.65,
            top2_weight=0.35,
            scoring_mode="composite_master",
            macro_filter=False,
        )

        buy_trades = [t for t in res.trades if t.action == "BUY"]
        self.assertEqual(len(buy_trades), 2)
        cost_1 = abs(buy_trades[0].cash_flow)
        cost_2 = abs(buy_trades[1].cash_flow)
        self.assertGreater(cost_1, cost_2 * 1.5, "Top 1 should receive ~65% while Top 2 receives ~35%")


if __name__ == "__main__":
    unittest.main()
