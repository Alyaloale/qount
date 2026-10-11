"""Unit tests for A-share Sector and Track ETF Momentum Breakout Module."""
import unittest

from qount.research.ashare_sector_momentum import (
    SectorBar,
    TradeRecord,
    SectorMomentumSimulator,
    compute_drawdowns,
    evaluate_sector_performance,
)


class TestAshareSectorMomentum(unittest.TestCase):
    def test_compute_drawdowns(self):
        navs = [100.0, 150.0, 120.0, 160.0, 80.0]
        dds, max_dd = compute_drawdowns(navs)
        self.assertEqual(len(dds), 5)
        self.assertAlmostEqual(dds[0], 0.0)
        self.assertAlmostEqual(dds[1], 0.0)
        self.assertAlmostEqual(dds[2], (150.0 - 120.0) / 150.0)  # 20%
        self.assertAlmostEqual(dds[3], 0.0)
        self.assertAlmostEqual(dds[4], (160.0 - 80.0) / 160.0)  # 50%
        self.assertAlmostEqual(max_dd, 0.50)

    def test_evaluate_sector_performance_empty(self):
        metrics = evaluate_sector_performance([], [], [], 0.0)
        self.assertEqual(metrics.cagr, 0.0)
        self.assertEqual(metrics.total_trades, 0)

    def test_causal_breakout_execution(self):
        # 10 bars: flat at 10.0, day 6 breaks out to 15.0 on close
        dates = [f"2024010{i+1}" for i in range(9)]
        bars_bench = [SectorBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates]
        
        bars_sector = [
            SectorBar("20240101", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240102", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240103", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240104", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240105", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240106", 12.0, 15.0, 12.0, 15.0),  # Breakout on close!
            SectorBar("20240107", 16.0, 17.0, 15.0, 16.0),  # Execution happens on OPEN!
            SectorBar("20240108", 16.0, 16.0, 16.0, 16.0),
            SectorBar("20240109", 16.0, 16.0, 16.0, 16.0),
        ]

        sim = SectorMomentumSimulator(
            commission_bps=0.0,
            slippage_bps=0.0,
            annual_cash_yield=0.0,
            initial_capital=100_000.0,
        )
        res = sim.run(
            bars_dict={"000300.SH": bars_bench, "SECTOR_A": bars_sector},
            universe=["SECTOR_A"],
            benchmark_symbol="000300.SH",
            top_n=1,
            ma_period=3,
            breakout_window=3,
            trailing_stop_pct=0.10,
            momentum_window=3,
            macro_filter=False,
        )
        self.assertTrue(len(res.trades) > 0)
        buy_trade = res.trades[0]
        # Breakout at 20240106 close -> MUST fill at 20240107 open!
        self.assertEqual(buy_trade.trade_date, "20240107")
        self.assertEqual(buy_trade.action, "BUY")
        self.assertEqual(buy_trade.price, 16.0)

    def test_trailing_stop_causal_execution(self):
        dates = [f"202401{i+1:02d}" for i in range(12)]
        bars_bench = [SectorBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates]
        
        # Sector rises to 20.0, then drops to 16.0 (>15% drop from peak of 20)
        closes = [10.0, 10.0, 10.0, 12.0, 15.0, 20.0, 17.0, 15.0, 12.0, 10.0, 10.0, 10.0]
        opens  = [10.0, 10.0, 10.0, 11.0, 13.0, 16.0, 18.0, 16.0, 13.0, 11.0, 10.0, 10.0]
        bars_sector = [
            SectorBar(dates[i], opens[i], max(opens[i], closes[i]), min(opens[i], closes[i]), closes[i])
            for i in range(len(dates))
        ]

        sim = SectorMomentumSimulator(
            commission_bps=0.0,
            slippage_bps=0.0,
            annual_cash_yield=0.0,
            initial_capital=100_000.0,
        )
        res = sim.run(
            bars_dict={"000300.SH": bars_bench, "SECTOR_A": bars_sector},
            universe=["SECTOR_A"],
            benchmark_symbol="000300.SH",
            top_n=1,
            ma_period=3,
            breakout_window=3,
            trailing_stop_pct=0.15,
            momentum_window=3,
            macro_filter=False,
        )
        # Should have 1 BUY and 1 SELL
        actions = [t.action for t in res.trades]
        self.assertIn("BUY", actions)
        self.assertIn("SELL", actions)
        sell_trade = [t for t in res.trades if t.action == "SELL"][0]
        self.assertTrue(sell_trade.reason in ("TRAILING_STOP", "MA_BREAKDOWN"))
        self.assertIsNotNone(sell_trade.pnl)

    def test_friction_and_delay_impact(self):
        dates = [f"202401{i+1:02d}" for i in range(10)]
        bars_bench = [SectorBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates]
        bars_sector = [
            SectorBar("20240101", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240102", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240103", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240104", 12.0, 15.0, 12.0, 15.0),
            SectorBar("20240105", 15.0, 16.0, 15.0, 16.0),
            SectorBar("20240106", 16.0, 17.0, 16.0, 17.0),
            SectorBar("20240107", 17.0, 18.0, 17.0, 18.0),
            SectorBar("20240108", 18.0, 19.0, 18.0, 19.0),
            SectorBar("20240109", 19.0, 20.0, 19.0, 20.0),
            SectorBar("20240110", 20.0, 20.0, 20.0, 20.0),
        ]
        sim_base = SectorMomentumSimulator(commission_bps=0.0, slippage_bps=0.0)
        sim_cost = SectorMomentumSimulator(commission_bps=20.0, slippage_bps=10.0)

        res_base = sim_base.run(
            bars_dict={"000300.SH": bars_bench, "SECTOR_A": bars_sector},
            universe=["SECTOR_A"],
            ma_period=2,
            breakout_window=2,
            momentum_window=2,
            trailing_stop_pct=0.20,
            macro_filter=False,
        )
        res_cost = sim_cost.run(
            bars_dict={"000300.SH": bars_bench, "SECTOR_A": bars_sector},
            universe=["SECTOR_A"],
            ma_period=2,
            breakout_window=2,
            momentum_window=2,
            trailing_stop_pct=0.20,
            macro_filter=False,
        )
        self.assertGreater(res_base.metrics.final_equity, res_cost.metrics.final_equity)

    def test_multisector_slot_allocation(self):
        dates = [f"202401{i+1:02d}" for i in range(8)]
        bars_bench = [SectorBar(d, 10.0, 10.0, 10.0, 10.0) for d in dates]
        # Two sectors both break out on day 3
        bars_a = [
            SectorBar("20240101", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240102", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240103", 10.0, 12.0, 10.0, 12.0),
            SectorBar("20240104", 12.0, 13.0, 12.0, 13.0),
            SectorBar("20240105", 13.0, 13.0, 13.0, 13.0),
            SectorBar("20240106", 13.0, 13.0, 13.0, 13.0),
            SectorBar("20240107", 13.0, 13.0, 13.0, 13.0),
            SectorBar("20240108", 13.0, 13.0, 13.0, 13.0),
        ]
        bars_b = [
            SectorBar("20240101", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240102", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240103", 10.0, 15.0, 10.0, 15.0),
            SectorBar("20240104", 15.0, 16.0, 15.0, 16.0),
            SectorBar("20240105", 16.0, 16.0, 16.0, 16.0),
            SectorBar("20240106", 16.0, 16.0, 16.0, 16.0),
            SectorBar("20240107", 16.0, 16.0, 16.0, 16.0),
            SectorBar("20240108", 16.0, 16.0, 16.0, 16.0),
        ]
        sim = SectorMomentumSimulator(
            commission_bps=0.0,
            slippage_bps=0.0,
            initial_capital=100_000.0,
        )
        res = sim.run(
            bars_dict={"000300.SH": bars_bench, "A": bars_a, "B": bars_b},
            universe=["A", "B"],
            top_n=2,
            ma_period=2,
            breakout_window=2,
            momentum_window=2,
            macro_filter=False,
        )
        # Should have bought both A and B
        bought_syms = {t.symbol for t in res.trades if t.action == "BUY"}
        self.assertEqual(bought_syms, {"A", "B"})

    def test_macro_bear_regime_tightening(self):
        dates = [f"202401{i+1:02d}" for i in range(10)]
        # Benchmark crashing: 100 -> 50
        bars_bench = [
            SectorBar(dates[i], 100.0 - i * 5.0, 100.0 - i * 5.0, 100.0 - i * 5.0, 100.0 - i * 5.0)
            for i in range(10)
        ]
        bars_sector = [
            SectorBar("20240101", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240102", 10.0, 10.0, 10.0, 10.0),
            SectorBar("20240103", 10.0, 12.0, 10.0, 12.0),
            SectorBar("20240104", 12.0, 14.0, 12.0, 14.0),
            SectorBar("20240105", 14.0, 13.0, 12.5, 12.5),  # drops from 14 to 12.5 (~10.7% drop)
            SectorBar("20240106", 12.0, 12.0, 12.0, 12.0),
            SectorBar("20240107", 12.0, 12.0, 12.0, 12.0),
            SectorBar("20240108", 12.0, 12.0, 12.0, 12.0),
            SectorBar("20240109", 12.0, 12.0, 12.0, 12.0),
            SectorBar("20240110", 12.0, 12.0, 12.0, 12.0),
        ]
        # With normal stop 12%, 10.7% wouldn't trigger.
        # But in bear mode, stop tightened to 12% * 0.8 = 9.6%, so 10.7% triggers!
        sim = SectorMomentumSimulator(commission_bps=0.0, slippage_bps=0.0)
        res = sim.run(
            bars_dict={"000300.SH": bars_bench, "SECTOR": bars_sector},
            universe=["SECTOR"],
            top_n=2,
            ma_period=2,
            breakout_window=2,
            momentum_window=2,
            trailing_stop_pct=0.12,
            macro_filter=True,
            macro_ma_period=3,
            macro_tighten_factor=0.80,
        )
        sells = [t for t in res.trades if t.action == "SELL"]
        self.assertTrue(len(sells) > 0)


if __name__ == "__main__":
    unittest.main()
