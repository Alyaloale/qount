import unittest
import warnings
from dataclasses import replace

import numpy as np

from qount.research.etf_trader import baselines as B
from qount.research.etf_trader import constraints as C
from qount.research.etf_trader.costs import cost_params_for, effective_half_spread
from qount.research.etf_trader.env import simulate, summarize
from qount.research.etf_trader.generator import plausibility as PL
from qount.research.etf_trader.generator.calibration import calibration_report
from qount.research.etf_trader.generator import stylized as SF
from qount.research.etf_trader.generator.params import FactorParams, sample_world
from qount.research.etf_trader.generator.specs import CN_SPEC, US_SPEC, transition_matrix, ten_year_weight
from qount.research.etf_trader.generator.structural import simulate_world
from qount.research.etf_trader.universe import CN_ACCOUNT, US_ACCOUNT

_CACHE = {}


def _world(account="us", seed=3, years=6.0, warmup=4.0, factors=None):
    key = (account, seed, years, warmup, factors)
    if key not in _CACHE:
        p = sample_world(account, np.random.default_rng(seed))
        if factors is not None:
            p = p.with_factors(factors)
        spec = US_SPEC if account == "us" else CN_SPEC
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            _CACHE[key] = simulate_world(spec, p, years=years, warmup_years=warmup)
    return _CACHE[key]


class SpecTest(unittest.TestCase):
    def test_transition_matrix_rows_sum_to_one(self):
        P = transition_matrix(1.3)
        np.testing.assert_allclose(P.sum(axis=1), 1.0)
        self.assertTrue(np.all(P >= 0))

    def test_ten_year_weight_monotone(self):
        self.assertEqual(ten_year_weight(0.0), 0.0)
        self.assertLess(ten_year_weight(2.0), ten_year_weight(10.0))
        self.assertLess(ten_year_weight(30.0), 1.0)

    def test_specs_match_universe(self):
        self.assertEqual(US_SPEC.n, US_ACCOUNT.n_assets)
        self.assertEqual(CN_SPEC.n, CN_ACCOUNT.n_assets)
        self.assertEqual(CN_SPEC.tick, CN_ACCOUNT.tick)


class StructuralWorldTest(unittest.TestCase):
    def test_deterministic_from_seed(self):
        a = _world(seed=5)
        p = sample_world("us", np.random.default_rng(5))
        b = simulate_world(US_SPEC, p, years=6.0, warmup_years=4.0)
        np.testing.assert_array_equal(a.data.close_adj, b.data.close_adj)
        np.testing.assert_array_equal(a.truth.regime, b.truth.regime)

    def test_shapes_and_finite(self):
        for acct in ("us", "cn"):
            w = _world(acct)
            d = w.data
            self.assertEqual(d.close.shape, (d.T, w.spec.n))
            self.assertEqual(w.start, int(4.0 * 252))
            for name in ("close_adj", "close", "open", "adv", "sigma", "spread"):
                arr = getattr(d, name)
                self.assertTrue(np.isfinite(arr).all(), (acct, name))
                self.assertTrue(np.all(arr > 0), (acct, name))
            self.assertTrue(np.isfinite(d.cash_return).all())

    def test_adjusted_equals_price_plus_distribution(self):
        w = _world("us")
        d = w.data
        # close_adj[t]/close_adj[t-1] = close[t]/close[t-1] × (1 + dist_t), dist_t ≥ 0
        dist = (d.close_adj[1:] / d.close_adj[:-1]) / (d.close[1:] / d.close[:-1]) - 1.0
        self.assertTrue(np.all(dist > -1e-12))
        kinds = [a.kind for a in US_SPEC.assets]
        gold, cmdty = kinds.index("gold"), kinds.index("commodity")
        np.testing.assert_allclose(dist[:, [gold, cmdty]], 0.0, atol=1e-12)
        bond = kinds.index("bond")
        self.assertGreater(dist[:, bond].mean() * 252, 0.0)

    def test_cn_tick_grid_and_limits(self):
        w = _world("cn")
        d = w.data
        tick = CN_SPEC.tick
        np.testing.assert_allclose(np.round(d.close / tick) * tick, d.close, atol=1e-9)
        np.testing.assert_allclose(np.round(d.open / tick) * tick, d.open, atol=1e-9)
        up = np.maximum(np.round(d.close[:-1] * 1.1 / tick) * tick, d.close[:-1] + tick)
        dn = np.round(d.close[:-1] * 0.9 / tick) * tick
        self.assertTrue(np.all(d.close[1:] <= up + 1e-9))
        self.assertTrue(np.all(d.close[1:] >= dn - 1e-9))

    def test_cn_buy_block_only_on_qdii_and_during_quota(self):
        w = _world("cn", seed=21, years=12.0)
        qdii = np.array([a.qdii for a in CN_SPEC.assets])
        self.assertFalse(w.data.buy_blocked[:, ~qdii].any())
        np.testing.assert_array_equal(w.data.buy_blocked[:, qdii], np.repeat(w.truth.quota[:, None], qdii.sum(), 1))

    def test_first_trading_row_near_price0(self):
        w = _world("cn")
        p0 = np.array([a.price0 for a in CN_SPEC.assets])
        ratio = w.data.close[w.start] / p0
        self.assertTrue(np.all((ratio > 0.8) & (ratio < 1.25)), ratio)

    def test_null_factors_expected_return_is_beta_erp(self):
        w = _world("us", factors=FactorParams.null())
        eq = [i for i, a in enumerate(US_SPEC.assets) if a.kind == "equity" and not a.fx]
        beta = np.array([US_SPEC.assets[i].beta for i in eq])
        rf = w.truth.rate[:, 0] / 252
        expect = rf[:, None] + beta[None, :] * w.truth.erp[:, [0]] / 252
        np.testing.assert_allclose(w.truth.mu[:, eq], expect, atol=1e-12)

    def test_valuation_panel_kinds(self):
        w = _world("us")
        kinds = np.array([a.kind for a in US_SPEC.assets])
        self.assertTrue(np.isfinite(w.valuation[:, kinds == "equity"]).all())
        self.assertTrue(np.isfinite(w.valuation[:, kinds == "bond"]).all())
        self.assertTrue(np.isnan(w.valuation[:, (kinds == "gold") | (kinds == "commodity")]).all())

    def test_stylized_sample_runs(self):
        checks = SF.world_checks(_world("us").sample())
        for key in ("return_autocorr_max", "kurtosis_daily", "volume_abs_return_corr", "dy_r2_1m"):
            self.assertIn(key, checks)
        self.assertTrue(checks["volume_abs_return_corr"][1])

    def test_liquidity_shock_clipping_prevents_overflow(self):
        """Verify shock term is clipped to prevent exp overflow in log_tv calculation."""
        for acct in ("us", "cn"):
            w = _world(acct, years=10.0)
            d = w.data
            self.assertTrue(np.isfinite(d.adv).all(), f"{acct}: adv contains NaN/Inf")
            self.assertTrue(np.isfinite(d.spread).all(), f"{acct}: spread contains NaN/Inf")
            self.assertTrue(np.all(d.adv > 0), f"{acct}: adv must be positive")
            self.assertTrue(np.all(d.spread > 0), f"{acct}: spread must be positive")


class GeneratedWorldEnvTest(unittest.TestCase):
    def test_baselines_run_on_generated_worlds(self):
        for acct, account in (("us", replace(US_ACCOUNT, fractional_shares=True)), ("cn", CN_ACCOUNT)):
            w = _world(acct)
            close = w.data.close_adj
            for name, (targets, every) in B.all_baselines(close, account, w.valuation).items():
                if not np.isfinite(targets[w.start :]).all(axis=1).any():
                    continue
                first = max(B.first_ready(targets), w.start)
                res = simulate(w.data, account, B.scheduled_policy(targets, first, every),
                               cost_params_for(account), start=w.start)
                s = summarize(res)
                self.assertTrue(np.isfinite(s["sharpe"]), (acct, name))
                self.assertLessEqual(s["turnover_voluntary_per_year"], account.turnover_budget + 1e-6)

    def test_quota_blocks_buys_in_env(self):
        w = _world("cn", seed=21, years=12.0)
        qdii = [i for i, a in enumerate(CN_SPEC.assets) if a.qdii]
        target = np.zeros(CN_SPEC.n)
        target[qdii] = 0.3
        from qount.research.etf_trader.env import Decision

        res = simulate(w.data, CN_ACCOUNT, lambda o: Decision(target=target), cost_params_for(CN_ACCOUNT), start=w.start)
        blocked_rows = np.flatnonzero(w.data.buy_blocked[:, qdii[0]])
        blocked_rows = blocked_rows[blocked_rows > w.start + 1]
        self.assertGreater(blocked_rows.size, 0)
        bought = res.weights[blocked_rows, qdii[0]] > res.weights[blocked_rows - 1, qdii[0]] * (1 + 0.11) + 1e-9
        self.assertFalse(bought.any())


class OracleTest(unittest.TestCase):
    def test_oracle_weights_bounds(self):
        rng = np.random.default_rng(0)
        mu = rng.normal(1e-4, 3e-4, size=(50, 9))
        var = np.full((50, 9), 1e-4)
        w = B.oracle_weights(mu, var, np.full(50, 5e-5), US_ACCOUNT)
        self.assertTrue(np.all(w >= 0))
        self.assertTrue(np.all(w <= 0.35 + 1e-12))
        self.assertTrue(np.all(w.sum(axis=1) <= 1 + 1e-12))
        self.assertTrue(np.all(w[:, :3].sum(axis=1) <= 0.5 + 1e-12))
        self.assertTrue(np.all(w[mu <= 5e-5] == 0))


class PlausibilityTest(unittest.TestCase):
    def test_check_reports_all_rules(self):
        stats, fails = PL.check(_world("us", years=10.0))
        for key in ("erp", "term_premium", "real_cash", "gold_real", "oracle_sharpe", "pe_min", "sb_corr_max"):
            self.assertIn(key, stats)
        self.assertIsInstance(fails, list)

    def test_implausible_world_rejected(self):
        p = sample_world("us", np.random.default_rng(3))
        bad = replace(p, home=replace(p.home, erp=0.25))
        _, fails = PL.check(simulate_world(US_SPEC, bad, years=10.0, warmup_years=4.0))
        self.assertIn("erp", fails)

    def test_sampling_report(self):
        rep = PL.sample_plausible("us", n_worlds=1, rng=np.random.default_rng(1), years=5.0, max_draws=2)
        self.assertLessEqual(rep.draws, 2)
        self.assertTrue(0.0 <= rep.rejection_rate <= 1.0)
        self.assertEqual(rep.summary()["draws"], rep.draws)


class CalibrationTest(unittest.TestCase):
    def test_report_shape_and_flags(self):
        r = calibration_report("us", 1, 99, plausibility_years=8.0, stylized_years=8.0)
        self.assertFalse(r["acceptance_run"])
        self.assertEqual(r["plausibility"]["draws"], r["draw_budget"])
        self.assertIn("stylized", r)
        if r["n_worlds_stylized"]:
            self.assertEqual(r["stylized_undecided"], ["equity_drawdown_ge_30_share"])
        self.assertFalse(r["stylized_passed"] and not r["n_worlds_stylized"])
        self.assertFalse(r["orders_authorized"])
        self.assertTrue(r["research_only"])

    def test_workers_do_not_change_the_result(self):
        kw = dict(plausibility_years=8.0, stylized_years=8.0)
        one = calibration_report("cn", 2, 7, **kw)
        many = calibration_report("cn", 2, 7, workers=4, **kw)
        self.assertEqual(one["plausibility"], many["plausibility"])
        self.assertEqual(one["stylized"], many["stylized"])

    def test_unknown_account(self):
        with self.assertRaises(ValueError):
            calibration_report("jp", 1, 1)


class CostSeriesTest(unittest.TestCase):
    def test_spread_series_scaled_and_floored(self):
        p = cost_params_for(CN_ACCOUNT).scaled(spread_mult=2.0)
        price = np.full(8, 2.0)
        series = np.full(8, 1e-3)
        np.testing.assert_allclose(effective_half_spread(p, price, series), 2e-3)
        np.testing.assert_allclose(effective_half_spread(p, price, np.zeros(8)), 0.5 * 0.001 / 2.0)

    def test_buy_blocked_voids_buys_only(self):
        n = CN_ACCOUNT.n_assets
        blocked = np.zeros(n, bool)
        blocked[6] = True
        cur = np.zeros(n)
        cur[7] = 0.2
        target = np.zeros(n)
        target[6] = 0.2
        inp = C.StepInputs(target=target, current=cur, holdings=cur * 1e6 / 2.0, equity=1e6,
                           open_price=np.full(n, 2.0), prev_close_unadj=np.full(n, 2.0), adv=np.full(n, 1e9),
                           reduce_only=np.zeros(n, bool), suspended=np.zeros(n, bool), gross_cap=1.0,
                           buy_blocked=blocked)
        res = C.constrain_step(inp, CN_ACCOUNT, C.TurnoverBudget(3.0))
        self.assertTrue(res.voided[6])
        self.assertEqual(res.shares[6], 0.0)
        self.assertLess(res.shares[7], 0.0)


if __name__ == "__main__":
    unittest.main()
