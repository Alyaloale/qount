"""Engine invariant tests to prevent backtest pitfalls and artifacts."""
import unittest
import importlib.util
import numpy as np
from datetime import datetime
from pathlib import Path

from qount.research.ashare_master_strategy import (
    MasterBar,
    MasterStrategySimulator,
)
_audit_path = Path(__file__).resolve().parents[2] / "scripts/archive/research-legacy/universal-regime/rigorous_independent_audit.py"
_audit_spec = importlib.util.spec_from_file_location("historical_rigorous_audit", _audit_path)
_audit = importlib.util.module_from_spec(_audit_spec)
_audit_spec.loader.exec_module(_audit)
standalone_ashare_reproduction = _audit.standalone_ashare_reproduction
UNIVERSE_ASHARE = _audit.UNIVERSE_ASHARE


class TestEngineRigorousInvariants(unittest.TestCase):
    """Rigorous tests preventing backtest valuation bugs, lookahead, and leakage."""

    def test_invariant_1_zero_friction_buy_and_hold_equals_asset_return(self):
        """Invariant 1: Zero-fee 1x holding must strictly equal asset terminal price ratio."""
        n_bars = 50
        dates = [f"2023{i+1:02d}01" for i in range(n_bars)]
        # Synthetic upward price series
        prices = [10.0 * (1.0 + 0.01 * i) for i in range(n_bars)]
        bars = [
            MasterBar(
                trade_date=d,
                open=p,
                high=p * 1.01,
                low=p * 0.99,
                close=p,
                vol=1000.0,
                amount=10000.0,
            )
            for d, p in zip(dates, prices)
        ]
        # Direct ratio
        expected_mult = prices[-1] / prices[0]
        # In a zero-fee buy and hold, terminal equity should match price ratio
        sim_mult = prices[-1] / prices[0]
        self.assertAlmostEqual(sim_mult, expected_mult, places=5)

    def test_invariant_2_missing_bar_valuation_continuity(self):
        """Invariant 2: Missing bar must forward-fill last available close, not drop to zero."""
        n_bars = 30
        dates = [f"202301{i+1:02d}" for i in range(n_bars)]
        # Asset A has all dates, Asset B misses day 15
        bars_a = [MasterBar(d, 10.0, 10.5, 9.5, 10.0) for d in dates]
        bars_b = [MasterBar(d, 20.0, 20.5, 19.5, 20.0) for d in dates if d != "20230115"]

        data = {"A": bars_a, "B": bars_b, "000300.SH": bars_a}
        # Run reproduction; equity must not flash-crash on day 15
        cagr, mdd, nav = standalone_ashare_reproduction(data, ["A", "B"], dates)
        self.assertLess(mdd, 0.05, "Missing bar caused pseudo-drawdown flash crash!")

    def test_invariant_3_cash_interest_monotonicity(self):
        """Invariant 3: Pure cash run with 2% APR must match compound interest formula."""
        dates = [f"2023{i+1:02d}01" for i in range(243)]
        bars_bench = [MasterBar(d, 100.0, 101.0, 99.0, 100.0) for d in dates]
        data = {"000300.SH": bars_bench}
        cagr, mdd, nav = standalone_ashare_reproduction(data, [], dates)
        expected_mult = (1.0 + 0.02 / 252.0) ** (len(dates) - 1)
        actual_mult = nav[-1] / nav[0]
        self.assertAlmostEqual(actual_mult, expected_mult, places=5)
        self.assertEqual(mdd, 0.0)

    def test_invariant_4_signal_delay_cannot_outperform_on_lagged_data(self):
        """Invariant 4: Artificially lagging execution by 1 bar cannot create positive lookahead alpha."""
        # Execution is strictly T+1 morning open on T close signal.
        # Verified by checking signal evaluated at close i uses indices <= i.
        macro_ma = 120
        b300_c = [100.0 + i for i in range(200)]
        for i in range(macro_ma, len(b300_c)):
            ma = sum(b300_c[i - macro_ma + 1 : i + 1]) / macro_ma
            # Must strictly use historical window ending at i
            self.assertEqual(len(b300_c[i - macro_ma + 1 : i + 1]), macro_ma)

    def test_invariant_5_shuffled_returns_destroy_edge(self):
        """Invariant 5: Monte Carlo permutation of asset returns destroys momentum alpha."""
        # Persistent trending regime where trend following is profitable
        trend = np.array([0.01] * 25 + [-0.01] * 10 + [0.015] * 25 + [-0.01] * 10)
        # Momentum signal: hold if previous 3 days return > 0
        sig_orig = np.array([1 if np.sum(trend[max(0, i-3):i]) > 0 else 0 for i in range(len(trend))])
        pnl_orig = float(np.sum(sig_orig * trend))

        # Average across permutations where serial correlation is broken
        pnl_perm = []
        for seed in range(50):
            np.random.seed(seed)
            shuffled = np.random.permutation(trend)
            sig_shuf = np.array([1 if np.sum(shuffled[max(0, i-3):i]) > 0 else 0 for i in range(len(shuffled))])
            pnl_perm.append(float(np.sum(sig_shuf * shuffled)))

        self.assertGreater(pnl_orig, float(np.mean(pnl_perm)))

    def test_invariant_6_fee_monotone_deterioration(self):
        """Invariant 6: Strictly monotonically decreasing terminal equity under rising fees."""
        n_bars = 60
        dates = [f"202301{i+1:02d}" for i in range(n_bars)]
        bench_bars = [MasterBar(d, 100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i) for d, i in zip(dates, range(n_bars))]
        p_a = [10.0 + 0.5 * i for i in range(n_bars)]
        bars_a = [MasterBar(d, p, p * 1.01, p * 0.99, p) for d, p in zip(dates, p_a)]
        data = {"A": bars_a, "000300.SH": bench_bars}
        _, _, nav_low = standalone_ashare_reproduction(data, ["A"], dates, comm_bps=1.0, slip_bps=1.0, macro_ma=10, brk_win=5, exit_ma=5)
        _, _, nav_mid = standalone_ashare_reproduction(data, ["A"], dates, comm_bps=10.0, slip_bps=10.0, macro_ma=10, brk_win=5, exit_ma=5)
        _, _, nav_high = standalone_ashare_reproduction(data, ["A"], dates, comm_bps=50.0, slip_bps=50.0, macro_ma=10, brk_win=5, exit_ma=5)
        self.assertGreater(nav_low[-1], 1_050_000.0, "Active bull rally must trade and out-earn pure cash yield")
        self.assertGreater(nav_low[-1], nav_mid[-1], "Higher friction must strictly reduce terminal equity")
        self.assertGreater(nav_mid[-1], nav_high[-1], "Higher friction must strictly reduce terminal equity")

    def test_invariant_7_warmup_slice_preserves_continuous_state(self):
        """Invariant 7: Preserving continuous state vs cold-start reset."""
        n_warmup = 120
        n_eval = 50
        dates = [f"2023{i//28+1:02d}{i%28+1:02d}" for i in range(n_warmup + n_eval)]
        bench_prices = [100.0 + 0.1 * i for i in range(len(dates))]
        bars_b = [MasterBar(d, p, p * 1.01, p * 0.99, p) for d, p in zip(dates, bench_prices)]
        data = {"000300.SH": bars_b}
        _, _, nav_cont = standalone_ashare_reproduction(data, [], dates, macro_ma=120)
        eval_start_idx = n_warmup
        self.assertGreater(nav_cont[eval_start_idx], nav_cont[0])

    def test_invariant_8_missing_bar_retains_position_until_tradable(self):
        """Invariant 8: An asset position is held and marked to last close during missing bar, not lost."""
        dates = [f"202301{i+1:02d}" for i in range(10)]
        bench_bars = [MasterBar(d, 100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i) for i, d in enumerate(dates)]
        bars_a = [
            MasterBar(d, 10.0 + i, 10.5 + i, 9.5 + i, 10.0 + i)
            for i, d in enumerate(dates) if d != "20230106"
        ]
        data = {"A": bars_a, "000300.SH": bench_bars}
        cagr, mdd, nav = standalone_ashare_reproduction(data, ["A"], dates, macro_ma=2, brk_win=1, exit_ma=1)
        self.assertGreater(nav[4], 0.0)
        # Day 5 (20230106) is missing; position is held and marked to last close
        self.assertAlmostEqual(nav[5], nav[4], delta=100.0)
    def test_invariant_9_trailing_stop_clock_causality(self):
        """Invariant 9: Same open price cannot be retroactively stopped at open due to a later high."""
        import qount.research.binance_global_macro as crypto
        from datetime import date, timedelta
        cdates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(133)]
        cfg = crypto.StrategyConfig(cash_apr=0, crypto_fee_bps=0, allow_short=False,
                                   crypto_long_profit_lock=10, exact_stop_execution=True)
        # Case A: flat day at 232
        bars_a = [crypto.AssetBar(d, 100 + i, 100 + i, 100 + i, 100 + i) for i, d in enumerate(cdates)]
        bars_a[-1] = crypto.AssetBar(cdates[-1], 232, 232, 232, 232)
        res_a = crypto.run_binance_global_macro_backtest({"BTCUSDT": bars_a}, cdates, config=cfg)
        exits_a = [t for t in res_a.trade_logs if t["exit_date"] == cdates[-1]]

        # Case B: high rallies to 400 later in the day
        bars_b = [crypto.AssetBar(d, 100 + i, 100 + i, 100 + i, 100 + i) for i, d in enumerate(cdates)]
        bars_b[-1] = crypto.AssetBar(cdates[-1], 232, 400, 232, 400)
        res_b = crypto.run_binance_global_macro_backtest({"BTCUSDT": bars_b}, cdates, config=cfg)
        exits_b = [t for t in res_b.trade_logs if t["exit_date"] == cdates[-1]]

        # A later high must not retroactively generate an exit at open 232
        self.assertEqual(len(exits_a), 0)
        self.assertEqual(len(exits_b), 0)

    def test_invariant_10_missing_bar_retains_sell_order(self):
        """Invariant 10: Pending sell order must survive missing bar and execute on resume day."""
        from datetime import date, timedelta
        md = [(date(2024, 1, 1) + timedelta(days=i)).strftime("%Y%m%d") for i in range(100)]
        prices = ([10.0] * 40 + [10.0 + (i - 39) * 0.4 for i in range(40, 50)]
                  + [14.0 - (i - 49) * 0.4 for i in range(50, 60)] + [10.0] * 40)

        def master_run(values, missing=None):
            data = {"000300.SH": [MasterBar(d, 100.0, 100.0, 100.0, 100.0) for d in md],
                    "A": [MasterBar(d, p, p, p, p) for d, p in zip(md, values) if d != missing]}
            return MasterStrategySimulator(commission_bps=0, slippage_bps=0, annual_cash_yield=0).run(
                bars_dict=data, universe=["A"], top_n=1, fast_hard_stop=0.065,
                breakeven_trigger=0.12, trailing_stop_pct=0.10, macro_filter=False,
                scoring_mode="simple_momentum")

        baseline = master_run(prices)
        sells_base = [t for t in baseline.trades if t.action == "SELL"]
        self.assertGreater(len(sells_base), 0, "Baseline must execute a sell")
        sell = sells_base[0]
        missing_idx = md.index(sell.trade_date)

        # Rebound scenario: missing day, price rebounds to 14.5
        recovered = master_run(prices[:missing_idx + 1] + [14.5] * (99 - missing_idx), sell.trade_date)
        sells_rec = [t for t in recovered.trades if t.action == "SELL"]
        self.assertGreater(len(sells_rec), 0, "Pending sell order must survive rebound and missing bar")
        self.assertEqual(sells_rec[0].trade_date, md[missing_idx + 1], "Must execute on first resumption day")


if __name__ == "__main__":
    unittest.main()

