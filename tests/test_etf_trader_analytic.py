import itertools
import unittest
from dataclasses import replace

import numpy as np
from scipy.optimize import minimize

from qount.research.etf_trader import constraints as C
from qount.research.etf_trader.costs import cost_params_for
from qount.research.etf_trader.env import Decision, simulate
from qount.research.etf_trader.generator import analytic as A
from qount.research.etf_trader.universe import US_ACCOUNT

US_FRAC = replace(US_ACCOUNT, fractional_shares=True)


def _ar1(n=1, seed=0, **kw):
    p = A.sample_ar1(n, np.random.default_rng(seed))
    return replace(p, **kw) if kw else p


class KalmanExactTest(unittest.TestCase):
    def test_matches_brute_force_gaussian_conditioning(self):
        p = _ar1(seed=4)
        T = 12
        w = A.simulate_ar1(p, T + 1)
        post = A.ar1_filter(w.excess, p)
        a, P0, R = p.a[0], p.p0[0], p.r[0]
        idx = np.arange(T + 1)
        Cx = P0 * a ** np.abs(idx[:, None] - idx[None, :])  # Cov(x_s, x_u), s,u = 0..T
        Crr = Cx[:T, :T] + R * np.eye(T)  # r_t (t=1..T) observes x_{t-1}
        Cxr = Cx[T, :T]  # Cov(x_T, r_1..r_T)
        y = w.excess[1:, 0] - p.m_bar[0]
        mean = Cxr @ np.linalg.solve(Crr, y)
        var = P0 - Cxr @ np.linalg.solve(Crr, Cxr)
        self.assertAlmostEqual(post.m[T, 0] - p.m_bar[0], mean, places=12)
        self.assertAlmostEqual(post.state_var[T, 0], var, places=14)

    def test_calibrated_across_independent_worlds(self):
        # The state error is strongly autocorrelated within a world, so test on the last row
        # of many independent worlds (iid draws of the filtering error).
        p = _ar1(n=3, seed=7)
        z = []
        for s in range(400):
            w = A.simulate_ar1(replace(p, seed=s), 300)
            post = A.ar1_filter(w.excess, p)
            z.append((w.oracle_m[-1] - post.m[-1]) / np.sqrt(post.state_var[-1]))
        z = np.array(z)
        np.testing.assert_allclose(z.mean(axis=0), 0.0, atol=0.2)  # 4 SE
        np.testing.assert_allclose(z.std(axis=0), 1.0, atol=0.12)
        # one-step predictive innovations are white, so a single long world suffices
        w = A.simulate_ar1(p, 252 * 40)
        post = A.ar1_filter(w.excess, p)
        u = (w.excess[1:] - post.m[:-1])[252:] / np.sqrt(post.pred_var[:-1][252:])
        np.testing.assert_allclose(u.std(axis=0), 1.0, atol=0.03)

    def test_no_drift_variation_collapses_to_prior(self):
        p = _ar1(n=2, seed=1, q=np.full(2, 1e-30))
        w = A.simulate_ar1(p, 600)
        post = A.ar1_filter(w.excess, p)
        np.testing.assert_allclose(post.m, np.tile(p.m_bar, (600, 1)), atol=1e-12)


class HMMExactTest(unittest.TestCase):
    def test_matches_path_enumeration(self):
        p = A.sample_hmm(3, np.random.default_rng(11), K=2)
        p = replace(p, P=np.array([[0.9, 0.1], [0.2, 0.8]]))  # fast switching makes the test informative
        T = 8
        w = A.simulate_hmm(p, T + 1)
        post = A.hmm_filter(w.excess, p)
        pi0 = p.stationary

        def lik(t, s):
            r = w.excess[t]
            return np.prod(np.exp(-0.5 * (r - p.mean[s]) ** 2 / p.var[s]) / np.sqrt(2 * np.pi * p.var[s]))

        joint = np.zeros(2)
        for path in itertools.product(range(2), repeat=T + 1):
            pr = pi0[path[0]]
            for t in range(1, T + 1):
                pr *= p.P[path[t - 1], path[t]] * lik(t, path[t])
            joint[path[-1]] += pr
        np.testing.assert_allclose(post.probs[T], joint / joint.sum(), rtol=1e-10)

    def test_probabilities_and_calibration(self):
        p = A.sample_hmm(9, np.random.default_rng(3), K=3)
        w = A.simulate_hmm(p, 252 * 40)
        post = A.hmm_filter(w.excess, p)
        np.testing.assert_allclose(post.probs.sum(axis=1), 1.0)
        # reliability: among rows with P(s=k) in a bin, the frequency of s=k matches
        pk = post.probs[252:, 0]
        hit = (w.state[252:] == 0).astype(float)
        for lo, hi in ((0.0, 0.2), (0.8, 1.0)):
            sel = (pk >= lo) & (pk < hi)
            if sel.sum() > 200:
                self.assertAlmostEqual(hit[sel].mean(), pk[sel].mean(), delta=0.05)
        u = (w.excess[1:] - post.m[:-1])[252:] / np.sqrt(post.pred_var[:-1][252:])
        np.testing.assert_allclose(u.std(axis=0), 1.0, atol=0.05)

    def test_oracle_moments_are_mixtures(self):
        p = A.sample_hmm(4, np.random.default_rng(5), K=2)
        m, v = p.oracle_moments()
        k = 0
        draws_s = np.random.default_rng(0).random(200_000) < p.P[k, 1]
        z = np.random.default_rng(1).standard_normal((200_000, 4))
        r = np.where(draws_s[:, None], p.mean[1] + np.sqrt(p.var[1]) * z, p.mean[0] + np.sqrt(p.var[0]) * z)
        np.testing.assert_allclose(r.mean(axis=0), m[k], atol=4 * np.sqrt(v[k] / 200_000).max())
        np.testing.assert_allclose(r.var(axis=0), v[k], rtol=0.02)


class MVWeightsTest(unittest.TestCase):
    def _scipy(self, m, v, acct, gamma):
        n = m.size
        cons = [{"type": "ineq", "fun": lambda w: 1.0 - w.sum()}]
        for g in acct.group_indices():
            cons.append({"type": "ineq", "fun": lambda w, g=list(g): acct.group_cap - w[g].sum()})
        res = minimize(lambda w: -(w @ m - 0.5 * gamma * (w**2 * v).sum()), np.full(n, 0.01),
                       jac=lambda w: -(m - gamma * w * v), bounds=[(0, acct.single_cap)] * n,
                       constraints=cons, method="SLSQP", options={"ftol": 1e-15, "maxiter": 500})
        return res.x

    def test_matches_scipy_and_feasible(self):
        rng = np.random.default_rng(0)
        for gamma in (1.0, 2.0, 8.0):
            m = rng.normal(2e-4, 4e-4, (40, 9))
            v = rng.uniform(0.05, 0.3, (40, 9)) ** 2 / 252
            w = A.mv_weights(m, v, US_ACCOUNT, gamma=gamma)
            self.assertTrue(np.all(w >= -1e-12) and np.all(w <= US_ACCOUNT.single_cap + 1e-12))
            self.assertTrue(np.all(w.sum(axis=1) <= 1.0 + 1e-9))
            for g in US_ACCOUNT.group_indices():
                self.assertTrue(np.all(w[:, list(g)].sum(axis=1) <= US_ACCOUNT.group_cap + 1e-9))
            for i in range(m.shape[0]):
                ref = self._scipy(m[i], v[i], US_ACCOUNT, gamma)
                ce = A.certainty_equivalent(np.vstack([w[i], ref]), m[i][None], v[i][None], gamma)
                self.assertGreaterEqual(ce[0], ce[1] - 1e-12)
                np.testing.assert_allclose(w[i], ref, atol=2e-4)

    def test_all_negative_excess_holds_cash(self):
        w = A.mv_weights(np.full((3, 9), -1e-4), np.full((3, 9), 1e-4), US_ACCOUNT)
        np.testing.assert_array_equal(w, 0.0)


class RegretTest(unittest.TestCase):
    def test_oracle_dominates_pointwise_and_bayes_beats_alternatives(self):
        for kind, seeds in (("ar1", range(4)), ("hmm", range(4))):
            reg = {"bayes": [], "prior": [], "ewma": []}
            for s in seeds:
                rng = np.random.default_rng(50 + s)
                p = A.sample_ar1(9, rng) if kind == "ar1" else A.sample_hmm(9, rng)
                w = A.simulate_analytic(p, 252 * 12)
                W = A.benchmark_weights(w, US_ACCOUNT)
                ce = {k: A.certainty_equivalent(x, w.oracle_m, w.oracle_v) for k, x in W.items()}
                for k in reg:
                    self.assertTrue(np.all(ce["oracle"] >= ce[k] - 1e-14), (kind, s, k))
                rows = {r.name: r.regret_annual for r in A.regret_table(w, W)}
                for k in reg:
                    reg[k].append(rows[k])
            mean = {k: float(np.mean(v)) for k, v in reg.items()}
            self.assertLess(mean["bayes"], mean["prior"], kind)
            self.assertLess(mean["bayes"], mean["ewma"], kind)

    def test_reproducible(self):
        p = A.sample_hmm(9, np.random.default_rng(2))
        a, b = A.simulate_hmm(p, 500), A.simulate_hmm(p, 500)
        np.testing.assert_array_equal(a.excess, b.excess)
        np.testing.assert_array_equal(a.state, b.state)


class EnvIntegrationTest(unittest.TestCase):
    def test_frictionless_env_earns_weighted_return(self):
        p = A.sample_ar1(9, np.random.default_rng(9))
        w = A.simulate_ar1(p, 400)
        W = A.benchmark_weights(w, US_FRAC)["bayes"]
        costs = replace(cost_params_for(US_FRAC), sec_fee_rate=0.0, taf_per_share=0.0, commission_rate=0.0,
                        min_fee=0.0, half_spread=(0.0,) * 9, tick=1e-12, k_impact=0.0)
        res = simulate(w.data, US_FRAC, lambda o: Decision(target=W[o.t]), costs, start=0,
                       derisk=C.DeRisk(d1=0.98, d2=0.99), budget=C.TurnoverBudget(1e9))
        # equity return over t→t+1 = rf + Σ w_t (excess_{t+1}) up to drift between close t and fill
        exp = p.rf + np.sum(W[:-1] * w.excess[1:], axis=1)
        np.testing.assert_allclose(res.returns[1:], exp, atol=1e-10)


if __name__ == "__main__":
    unittest.main()
