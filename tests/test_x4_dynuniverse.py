"""Unit tests for the dynamic-universe trend portfolio (线 D §22 Phase 2).

The bias defenses are the risk surface, so they get the coverage: point-in-time ranking (no
look-ahead), ragged-listing eligibility (a late coin can't be picked before it lists), delisting
drop-out (a stale coin falls out), and the monthly-rebalanced book mechanics (BTC gate, turnover).
"""
import unittest

from qount.research_data.market_data import Bar
from qount.legacy.x4.dynuniverse import (
    run_dynamic_trend_portfolio,
    select_universe,
    trailing_dollar_volume,
)

DAY = 86_400_000


def _series(n, *, start_day=0, base=100.0, step=1.0, vol=1000.0):
    return [Bar(ts_ms=(start_day + i) * DAY, open=base + step * i, high=base + step * i,
                low=base + step * i, close=base + step * i, volume=vol) for i in range(n)]


class TestTrailingVolume(unittest.TestCase):
    def test_window_and_asof(self):
        bars = _series(10, base=10.0, step=0.0, vol=2.0)  # close=10, vol=2 -> $20/bar
        # last 3 bars up to ts of bar index 5 -> bars 3,4,5 -> 3*$20 = $60
        self.assertAlmostEqual(trailing_dollar_volume(bars, asof_ts=5 * DAY, window=3), 60.0)

    def test_empty_before_listing(self):
        bars = _series(5, start_day=100)
        self.assertEqual(trailing_dollar_volume(bars, asof_ts=10 * DAY, window=30), 0.0)


class TestSelectUniverse(unittest.TestCase):
    def _pool(self):
        # three coins, all listed from day 0 with 300 bars; volumes A>B>C
        return {
            "AUSDT": _series(300, vol=3000.0),
            "BUSDT": _series(300, vol=2000.0),
            "CUSDT": _series(300, vol=1000.0),
        }

    def test_ranks_by_dollar_volume(self):
        pool = self._pool()
        sel = select_universe(pool, asof_ts=299 * DAY, k=2, vol_window=30, min_history=200)
        self.assertEqual(sel, ["AUSDT", "BUSDT"])   # top-2 by $vol

    def test_excludes_insufficient_history(self):
        pool = self._pool()
        pool["DUSDT"] = _series(50, vol=9999.0)   # huge volume but only 50 bars < min_history
        sel = select_universe(pool, asof_ts=299 * DAY, k=3, vol_window=30, min_history=200)
        self.assertNotIn("DUSDT", sel)

    def test_late_listed_not_eligible_early(self):
        # a coin listing at day 250 has < min_history at day 299 -> not selectable yet (no look-ahead)
        pool = self._pool()
        pool["LATEUSDT"] = _series(300, start_day=250, vol=9999.0)
        early = select_universe(pool, asof_ts=299 * DAY, k=4, vol_window=30, min_history=200)
        self.assertNotIn("LATEUSDT", early)
        # much later, once it has history, it qualifies
        late = select_universe(pool, asof_ts=520 * DAY, k=1, vol_window=30, min_history=200)
        self.assertEqual(late, ["LATEUSDT"])

    def test_stale_coin_drops_out(self):
        # a coin whose data ends long ago (delisted) is excluded despite past history
        pool = self._pool()
        pool["DEADUSDT"] = _series(300, vol=9999.0)   # ends at day 299
        sel = select_universe(pool, asof_ts=400 * DAY, k=4, vol_window=30, min_history=200,
                              max_stale_ms=7 * DAY)
        self.assertNotIn("DEADUSDT", sel)


class TestRunDynamic(unittest.TestCase):
    def _pool(self):
        return {
            "BTCUSDT": _series(400, base=100.0, step=1.0, vol=5000.0),
            "AUSDT": _series(400, base=50.0, step=0.8, vol=4000.0),
            "BUSDT": _series(400, base=50.0, step=0.5, vol=3000.0),
            "CUSDT": _series(400, base=50.0, step=0.3, vol=1000.0),
        }

    def test_runs_and_shapes(self):
        res = run_dynamic_trend_portfolio(self._pool(), k=2, min_history=200, fast=5, slow=20,
                                          regime_sma=50, master_gate_sma=50, vol_lookback=10)
        self.assertEqual(len(res["equity_curve"]), len(res["dates"]))
        self.assertEqual(res["equity_curve"][0], 100_000.0)
        self.assertGreater(res["extra"]["candidate_pool_size"], 1)

    def test_missing_master_gate_raises(self):
        with self.assertRaises(ValueError):
            run_dynamic_trend_portfolio({"AUSDT": _series(300)}, master_gate_sym="BTCUSDT")

    def test_btc_gate_flattens_in_downtrend(self):
        # BTC falling the whole way -> gate shut -> book sits in cash -> equity flat at capital
        pool = {
            "BTCUSDT": _series(400, base=500.0, step=-1.0, vol=5000.0),
            "AUSDT": _series(400, base=50.0, step=0.8, vol=4000.0),
            "BUSDT": _series(400, base=50.0, step=0.5, vol=3000.0),
        }
        res = run_dynamic_trend_portfolio(pool, k=2, min_history=200, fast=5, slow=20,
                                          regime_sma=50, master_gate_sma=50, vol_lookback=10)
        self.assertTrue(all(abs(e - 100_000.0) < 1e-6 for e in res["equity_curve"]))

    def test_membership_logged(self):
        res = run_dynamic_trend_portfolio(self._pool(), k=2, min_history=200, fast=5, slow=20,
                                          regime_sma=50, master_gate_sma=50, vol_lookback=10)
        self.assertGreaterEqual(res["extra"]["n_rebalances"], 1)
        self.assertTrue(res["extra"]["membership_log"])


if __name__ == "__main__":
    unittest.main()
