import unittest

import numpy as np

from qount.research.etf_trader import constraints as C
from qount.research.etf_trader import costs as K
from qount.research.etf_trader import scorer as S
from qount.research.etf_trader.universe import CN_ACCOUNT, US_ACCOUNT, Account, EQUITY


def _prices(T=900, n=9, seed=0, drift=None):
    rng = np.random.default_rng(seed)
    mu = np.zeros(n) if drift is None else np.asarray(drift)
    r = mu + 0.01 * rng.standard_normal((T, n))
    return 100.0 * np.exp(np.cumsum(r, axis=0))


class UniverseTest(unittest.TestCase):
    def test_cash_excluded_and_groups_valid(self):
        for acct in (US_ACCOUNT, CN_ACCOUNT):
            self.assertNotIn(acct.cash_symbol, acct.symbols)
            for g in acct.group_indices():
                self.assertTrue(all(0 <= i < acct.n_assets for i in g))
        self.assertEqual(US_ACCOUNT.n_assets, 9)
        self.assertEqual(CN_ACCOUNT.n_assets, 8)
        self.assertEqual(CN_ACCOUNT.lot_size, 100)

    def test_rejects_cash_in_ranking(self):
        with self.assertRaises(ValueError):
            Account("x", "USD", ("A", "BIL"), "BIL", {"A": EQUITY, "BIL": EQUITY}, (), 4.0)


class CostTest(unittest.TestCase):
    def test_us_sell_pays_sec_and_taf_buy_does_not(self):
        p = K.cost_params_for(US_ACCOUNT)
        n = US_ACCOUNT.n_assets
        price = np.full(n, 100.0)
        adv = np.full(n, 1e9)
        sigma = np.zeros(n)  # isolate fees/spread
        buy = np.zeros(n); buy[0] = 1e6
        sell = -buy
        cb = K.trade_cost(buy, price, adv, sigma, p)[0]
        cs = K.trade_cost(sell, price, adv, sigma, p)[0]
        spread = 0.5e-4 * 1e6
        self.assertAlmostEqual(cb, spread)
        taf = min(K.FINRA_TAF_PER_SHARE * 1e4, K.FINRA_TAF_MAX)
        self.assertAlmostEqual(cs, spread + 20.60 + taf)

    def test_cn_min_fee_and_tick_floor(self):
        p = K.cost_params_for(CN_ACCOUNT)
        n = CN_ACCOUNT.n_assets
        price = np.full(n, 2.0)
        adv = np.full(n, 1e9)
        trade = np.zeros(n); trade[0] = 1000.0
        c = K.trade_cost(trade, price, adv, np.zeros(n), p)[0]
        # 0.85‰ × 1000 = 0.85 < 5 min fee; half tick 0.0005/2 = 2.5 bp
        self.assertAlmostEqual(c, 5.0 + 2.5e-4 * 1000)

    def test_sqrt_impact_and_multiplier(self):
        p = K.cost_params_for(US_ACCOUNT)
        n = US_ACCOUNT.n_assets
        # At 500 the half-tick floor (0.1 bp) is below the 0.5 bp base spread.
        price, adv, sigma = np.full(n, 500.0), np.full(n, 1e6), np.full(n, 0.01)
        t = np.zeros(n); t[1] = 1e4
        base = K.trade_cost(t, price, adv, sigma, p)[1]
        expected = 0.5e-4 * 1e4 + 0.1 * 0.01 * np.sqrt(0.01) * 1e4
        self.assertAlmostEqual(base, expected)
        self.assertAlmostEqual(K.trade_cost(t, price, adv, sigma, p, multiplier=2.0)[1], 2 * expected)

    def test_adv_cap_defers(self):
        ex, de = K.cap_by_adv(np.array([100.0, -100.0, 1.0]), np.array([1000.0, 1000.0, 1000.0]))
        np.testing.assert_allclose(ex, [50.0, -50.0, 1.0])
        np.testing.assert_allclose(de, [50.0, -50.0, 0.0])

    def test_randomize_only_spread_and_impact(self):
        p = K.cost_params_for(US_ACCOUNT)
        q = K.randomize(p, np.random.default_rng(1))
        self.assertEqual(q.sec_fee_rate, p.sec_fee_rate)
        ratio = q.k_impact / p.k_impact
        self.assertTrue(0.5 <= ratio <= 2.0)

    def test_zero_adv_trade_rejected(self):
        p = K.cost_params_for(US_ACCOUNT)
        n = US_ACCOUNT.n_assets
        t = np.zeros(n); t[0] = 1.0
        with self.assertRaises(K.CostModelError):
            K.trade_cost(t, np.ones(n), np.zeros(n), np.zeros(n), p)


class ScorerPrimitivesTest(unittest.TestCase):
    def test_percentile_rank_ties_and_nan(self):
        r = S.percentile_rank(np.array([[1.0, 2.0, 2.0, np.nan, 3.0]]))
        np.testing.assert_allclose(r[0, [0, 1, 2, 4]], [0.0, 0.5, 0.5, 1.0])
        self.assertTrue(np.isnan(r[0, 3]))
        self.assertEqual(S.percentile_rank(np.array([[np.nan, 7.0]]))[0, 1], 0.5)

    def test_rolling_stats_match_naive(self):
        x = np.random.default_rng(2).standard_normal((50, 3))
        m = S.rolling_mean(x, 10)
        sd = S.rolling_std(x, 10)
        self.assertTrue(np.isnan(m[8]).all())
        np.testing.assert_allclose(m[20], x[11:21].mean(axis=0))
        np.testing.assert_allclose(sd[20], x[11:21].std(axis=0, ddof=1))
        pct = S.rolling_percentile(x, 10)
        naive = ((x[11:21] < x[20]).sum(0) + 0.5 * (x[11:21] == x[20]).sum(0)) / 10
        np.testing.assert_allclose(pct[20], naive)

    def test_pit_no_lookahead(self):
        close = _prices(T=900)
        f_full = S.compute_factors(close, US_ACCOUNT)
        f_cut = S.compute_factors(close[:700], US_ACCOUNT)
        np.testing.assert_allclose(f_full.ranks[:, :700], f_cut.ranks, equal_nan=True)
        for k in S.FACTORS:
            np.testing.assert_allclose(f_full.raw[k][:700], f_cut.raw[k], equal_nan=True)

    def test_residualized_trend_uncorrelated_with_momentum(self):
        close = _prices(T=1200, seed=3, drift=np.linspace(-5e-4, 5e-4, 9))
        f = S.compute_factors(close, US_ACCOUNT)
        m, tr = f.ranks[0], f.raw["trend_orth"]
        # In-window pooled OLS residuals are orthogonal to the regressor.
        t = 1100
        rows = slice(t - 251, t + 1)
        y = S.trend_composite(close)[rows]
        x = m[rows]
        ok = np.isfinite(x) & np.isfinite(y)
        beta, a = np.polyfit(x[ok], y[ok], 1)
        np.testing.assert_allclose(tr[t], y[-1] - a - beta * x[-1], atol=1e-9)

    def test_value_disabled_is_neutral(self):
        f = S.compute_factors(_prices(T=400), US_ACCOUNT)
        self.assertFalse(f.value_enabled)
        self.assertTrue(np.all(f.raw["value"] == 0.5))

    def test_value_direction(self):
        kinds = ("valuation", "yield", "neutral")
        v = np.column_stack([np.arange(30.0), np.arange(30.0), np.arange(30.0)])
        cfg = S.ScorerConfig(value_window=20)
        out, enabled = S.value(v, kinds, cfg)
        self.assertTrue(enabled)
        # Rising PE -> expensive (low); rising yield -> cheap bond (high); neutral 0.5.
        self.assertLess(out[-1, 0], 0.1)
        self.assertGreater(out[-1, 1], 0.9)
        self.assertEqual(out[-1, 2], 0.5)


class ScoreAndConstructionTest(unittest.TestCase):
    def test_prior_alpha(self):
        np.testing.assert_allclose(S.PRIOR_ALPHA, [6 / 17, 4 / 17, 4 / 17, 3 / 17])

    def test_effective_weights_sum_to_one(self):
        rng = np.random.default_rng(4)
        ranks = rng.uniform(size=(4, 200, 9))
        ranks[1] = 0.8 * ranks[0] + 0.2 * ranks[1]  # correlated factor
        ew = S.effective_weights(ranks)
        self.assertAlmostEqual(ew.effective.sum(), 1.0)
        self.assertGreater(ew.effective[0], ew.nominal[0])

    def test_construct_weights_caps_leave_cash(self):
        score = np.array([1.0, 0.9, 0.8, 0, 0, 0, 0, 0, 0])
        sigma = np.full(9, 0.01)
        w = S.construct_weights(score, sigma, tau=0.03, gross=1.0, account=US_ACCOUNT)
        self.assertLessEqual(w.max(), 0.35 + 1e-12)
        self.assertLessEqual(w[[0, 1, 2]].sum(), 0.5 + 1e-12)
        self.assertLess(w.sum(), 1.0)

    def test_construct_inverse_vol(self):
        score = np.zeros(9)
        sigma = np.array([0.01, 0.02] + [0.01] * 7)
        w = S.construct_weights(score, sigma, tau=1.0, gross=0.5, account=US_ACCOUNT)
        self.assertAlmostEqual(w[0] / w[1], 2.0)

    def test_fixed_baseline_flat_in_bear(self):
        close = _prices(T=900, seed=5, drift=np.full(9, -2e-3))
        targets, _ = S.fixed_scorer_targets(close, US_ACCOUNT, cfg=S.ScorerConfig(risk_window=252))
        ready = np.flatnonzero(np.isfinite(targets).all(axis=1))
        ok = S.absolute_trend_filter(close)
        for t in ready[::21]:  # rebalance rows
            self.assertTrue(np.all(targets[t][~ok[t]] == 0.0))
        self.assertLess(np.nanmean(targets[ready].sum(axis=1)), 0.2)


class LiquidityConstraintTest(unittest.TestCase):
    def test_reduce_only_on_deterioration(self):
        adv = np.full((300, 2), 1e7)
        adv[-1, 0] = 2e6  # < 30% of median
        m = C.reduce_only_mask(adv, min_adv=1e6, window=252)
        self.assertTrue(m[-1, 0])
        self.assertFalse(m[-1, 1])
        self.assertTrue(C.reduce_only_mask(np.full((5, 1), 5e5), min_adv=1e6).all())

    def test_capacity_and_apply(self):
        cap = C.capacity_cap(np.array([1e6, 1e9]), equity=1e6, single_cap=0.35)
        np.testing.assert_allclose(cap, [0.15, 0.35])
        out = C.apply_liquidity(np.array([0.3, 0.3]), np.array([0.1, 0.1]), np.array([True, False]), cap)
        np.testing.assert_allclose(out, [0.1, 0.3])


class DeRiskTest(unittest.TestCase):
    def test_engage_and_recover_by_drawdown(self):
        d = C.DeRisk()
        self.assertEqual(d.update(100.0), 1.0)
        self.assertEqual(d.update(89.0), 0.5)
        self.assertEqual(d.update(84.0), 0.2)
        self.assertEqual(d.update(90.0), 0.2)  # still 10% dd, cap does not loosen
        self.assertEqual(d.update(96.0), 1.0)  # within D1/2

    def test_time_based_recovery_requires_positive_lookback(self):
        d = C.DeRisk(min_days=5, lookback=10)
        for e in [100.0] * 11 + [88.0]:
            cap = d.update(e)
        self.assertEqual(cap, 0.5)
        # Slow grind up, still >5% below the peak: only the time rule can release.
        path = [88.0 + 0.1 * k for k in range(1, 13)]
        caps = [d.update(e) for e in path]
        self.assertIn(1.0, caps)
        first = caps.index(1.0)
        # Needs ≥5 capped days and the 100s out of the 10-day lookback.
        self.assertGreaterEqual(first + 1, 10)
        # HWM reset: the same level does not re-trigger.
        self.assertEqual(d.update(path[first]), 1.0)


class BandAndBudgetTest(unittest.TestCase):
    def test_soft_band(self):
        dw = C.soft_band(np.array([0.3, 0.1, 0.2]), np.array([0.1, 0.1, 0.25]), band=0.05, kappa=0.5)
        np.testing.assert_allclose(dw, [0.075, 0.0, 0.0])

    def test_budget_scales_voluntary_only(self):
        b = C.TurnoverBudget(budget=1.0, window=5)
        for _ in range(4):
            b.record(0.2, 0.0)  # 0.8 used
        v, breach = b.project(np.array([0.4, -0.4]), np.zeros(2))  # needs 0.4
        self.assertAlmostEqual(C.one_way_turnover(v), 0.2)
        self.assertFalse(breach)

    def test_forced_breach_reported(self):
        b = C.TurnoverBudget(budget=1.0, window=3)
        b.record(1.0, 0.0)
        b.record(0.0, 0.4)
        v, breach = b.project(np.array([0.1, -0.1]), np.array([-0.4, 0.0]))
        self.assertEqual(C.one_way_turnover(v), 0.0)
        self.assertTrue(breach)

    def test_window_rolls(self):
        b = C.TurnoverBudget(budget=1.0, window=3)
        b.record(1.0, 0.0)
        b.record(0.0, 0.0)
        b.record(0.0, 0.0)  # first entry leaves the window-1 history
        self.assertEqual(b.used_voluntary, 0.0)


class MarketRuleTest(unittest.TestCase):
    def test_cn_limits_use_unadjusted_prev_close(self):
        prev = np.array([2.000, 2.000, 2.000])
        opn = np.array([2.200, 1.800, 2.100])
        buy, sell = C.tradable_sides(opn, prev, np.zeros(3, bool), 0.10, 0.001)
        np.testing.assert_array_equal(buy, [False, True, True])
        np.testing.assert_array_equal(sell, [True, False, True])

    def test_lot_rounding_and_full_exit(self):
        s = C.round_shares(np.array([250.0, -130.0, -1000.0]), np.array([0, 130, 400]), np.zeros(3), 100)
        np.testing.assert_allclose(s, [200.0, -130.0, -400.0])

    def test_t_plus_one_lock(self):
        s = C.round_shares(np.array([-500.0]), np.array([500.0]), np.array([300.0]), 100)
        np.testing.assert_allclose(s, [-200.0])


class ConstrainStepTest(unittest.TestCase):
    def _inputs(self, **kw):
        n = CN_ACCOUNT.n_assets
        base = dict(
            target=np.array([0.3, 0.2, 0.0, 0.0, 0.2, 0.2, 0.0, 0.0]),
            current=np.zeros(n),
            holdings=np.zeros(n),
            equity=1e6,
            open_price=np.full(n, 2.0),
            prev_close_unadj=np.full(n, 2.0),
            adv=np.full(n, 1e9),
            reduce_only=np.zeros(n, bool),
            suspended=np.zeros(n, bool),
            gross_cap=1.0,
        )
        base.update(kw)
        return C.StepInputs(**base)

    def test_basic_fill_is_lot_rounded(self):
        b = C.TurnoverBudget(budget=3.0)
        res = C.constrain_step(self._inputs(), CN_ACCOUNT, b)
        self.assertTrue(np.all(res.shares % 100 == 0))
        np.testing.assert_allclose(res.delta_weight, [0.3, 0.2, 0, 0, 0.2, 0.2, 0, 0], atol=1e-3)
        self.assertAlmostEqual(res.forced_turnover, 0.0)
        self.assertAlmostEqual(b.used_voluntary, res.voluntary_turnover)

    def test_forced_derisk_not_blocked_by_budget(self):
        n = CN_ACCOUNT.n_assets
        cur = np.array([0.35, 0.3, 0, 0, 0.3, 0, 0, 0])
        hold = cur * 1e6 / 2.0
        b = C.TurnoverBudget(budget=0.01)
        b.record(0.01, 0.0)  # voluntary budget exhausted
        res = C.constrain_step(
            self._inputs(target=cur, current=cur, holdings=hold, gross_cap=0.5), CN_ACCOUNT, b
        )
        self.assertAlmostEqual((cur + res.delta_weight).sum(), 0.5, places=3)
        self.assertGreater(res.forced_turnover, 0.0)
        self.assertAlmostEqual(res.voluntary_turnover, 0.0, places=6)

    def test_limit_up_voids_buy_without_budget(self):
        n = CN_ACCOUNT.n_assets
        opn = np.full(n, 2.0); opn[0] = 2.2
        b = C.TurnoverBudget(budget=3.0)
        res = C.constrain_step(self._inputs(open_price=opn), CN_ACCOUNT, b)
        self.assertTrue(res.voided[0])
        self.assertEqual(res.shares[0], 0.0)
        self.assertAlmostEqual(res.voluntary_turnover, 0.5 * 0.6, places=3)

    def test_adv_cap_defers(self):
        n = CN_ACCOUNT.n_assets
        adv = np.full(n, 1e9); adv[0] = 1e6  # 5% = 50k < 300k wanted, capacity 15%
        res = C.constrain_step(self._inputs(adv=adv), CN_ACCOUNT, C.TurnoverBudget(budget=3.0))
        self.assertAlmostEqual(res.delta_weight[0], 0.05, places=3)
        self.assertGreater(res.deferred_notional[0], 0.0)


if __name__ == "__main__":
    unittest.main()
