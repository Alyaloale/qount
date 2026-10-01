"""Torch env / policy parity with the numpy reference (design §10). Skipped without torch."""

import unittest
import warnings
from dataclasses import replace

import numpy as np

try:
    import torch
except ImportError:  # torch lives on the research GPU host only
    torch = None

from qount.research.etf_trader import constraints as C
from qount.research.etf_trader import scorer as S
from qount.research.etf_trader.costs import cost_params_for
from qount.research.etf_trader.env import Decision, simulate
from qount.research.etf_trader.generator.params import sample_world
from qount.research.etf_trader.generator.specs import ACCOUNT_SPECS
from qount.research.etf_trader.generator.structural import simulate_world
from qount.research.etf_trader.universe import ACCOUNTS, US_ACCOUNT

_W = {}


def _world(acct, seed, warmup=1.5):
    if (acct, seed, warmup) not in _W:
        p = sample_world(acct, np.random.default_rng(seed))
        _W[(acct, seed, warmup)] = simulate_world(ACCOUNT_SPECS[acct], p, years=3.0, warmup_years=warmup)
    return _W[(acct, seed, warmup)]


def _random_targets(T, n, account, seed, every=5):
    rng = np.random.default_rng(seed)
    tg = np.full((T, n), np.nan)
    for t in range(0, T, every):
        w = rng.dirichlet(np.ones(n)) * rng.uniform(0.3, 1.0)
        tg[t] = S.construct_weights(np.log(w + 1e-9), np.ones(n), 1.0, float(w.sum()), account)
    return tg


@unittest.skipIf(torch is None, "torch not installed")
class TorchEnvParityTest(unittest.TestCase):
    def _run(self, acct_name, seed, *, band=0.0, kappa=1.0, budget=None, derisk=None, mult=1.0):
        from qount.research.etf_trader.torch_env import Batch, TorchEnv

        account = ACCOUNTS[acct_name]
        if acct_name == "us":
            account = replace(account, fractional_shares=True)
        w = _world(acct_name, seed)
        d = w.data
        T, n = d.T, d.n
        costs = cost_params_for(account)
        tg = _random_targets(T, n, account, seed)
        reduce_only = C.reduce_only_mask(d.adv, d.spread)

        def policy(o):
            if not np.all(np.isfinite(tg[o.t])):
                return Decision(target=None)
            return Decision(target=tg[o.t], band=band, kappa=kappa)

        mk = (lambda: replace(derisk)) if derisk else (lambda: C.DeRisk())
        ref = simulate(d, account, policy, costs, cost_multiplier=mult, derisk=mk(),
                       budget=C.TurnoverBudget(budget or account.turnover_budget))
        batch = Batch.from_market([d], [reduce_only], dtype=torch.float64)
        env = TorchEnv(batch, account, costs, exact=True, cost_multiplier=mult, derisk=mk(), budget=budget)
        eq = [float(env.equity[0])]
        for t in range(T - 1):
            obs = env.observe()
            np.testing.assert_allclose(obs.weights[0].numpy(), ref.weights[t], rtol=1e-9, atol=1e-12)
            self.assertAlmostEqual(float(obs.gross_cap[0]), ref.gross_cap[t])
            hold = not np.all(np.isfinite(tg[t]))
            target = torch.as_tensor(np.nan_to_num(tg[t]), dtype=torch.float64)[None]
            out = env.step(target, band, kappa, hold=torch.tensor([hold]))
            eq.append(float(out["equity"][0]))
            self.assertAlmostEqual(float(out["cost"][0]), ref.costs[t + 1], delta=1e-9 * max(1.0, ref.costs[t + 1]))
            self.assertAlmostEqual(float(out["voluntary_turnover"][0]), ref.voluntary_turnover[t + 1], places=10)
            self.assertAlmostEqual(float(out["forced_turnover"][0]), ref.forced_turnover[t + 1], places=10)
            np.testing.assert_array_equal(out["voided"][0].numpy(), ref.voided[t + 1])
        np.testing.assert_allclose(eq, ref.equity, rtol=1e-10)
        return ref

    def test_us_fractional(self):
        self._run("us", 1)

    def test_cn_lots_limits_quota(self):
        ref = self._run("cn", 2)
        self.assertGreater(np.abs(ref.voluntary_turnover).sum(), 0)

    def test_band_kappa_and_budget_bind(self):
        ref = self._run("us", 3, band=0.02, kappa=0.4, budget=0.6)
        self.assertLessEqual(max(np.convolve(ref.voluntary_turnover, np.ones(252), "valid")), 0.6 + 1e-9)

    def test_derisk_engages_and_recovers(self):
        ref = self._run("cn", 4, derisk=C.DeRisk(d1=0.02, d2=0.04, min_days=10, lookback=20))
        self.assertTrue((ref.gross_cap < 1).any() and (ref.gross_cap[ref.start:] == 1).any())

    def test_cost_multiplier(self):
        self._run("cn", 5, mult=3.0)

    def test_batch_equals_single_worlds(self):
        from qount.research.etf_trader.torch_env import Batch, TorchEnv

        acct = replace(US_ACCOUNT, fractional_shares=True)
        ws = [_world("us", s) for s in (1, 3)]
        ro = [C.reduce_only_mask(w.data.adv, w.data.spread) for w in ws]
        tgs = [_random_targets(w.data.T, w.data.n, acct, s) for w, s in zip(ws, (1, 3))]
        costs = cost_params_for(acct)
        both = TorchEnv(Batch.from_market([w.data for w in ws], ro), acct, costs, exact=True)
        singles = [TorchEnv(Batch.from_market([w.data], [r]), acct, costs, exact=True) for w, r in zip(ws, ro)]
        for t in range(ws[0].data.T - 1):
            hold = torch.tensor([not np.isfinite(tg[t]).all() for tg in tgs])
            tg = torch.as_tensor(np.stack([np.nan_to_num(g[t]) for g in tgs]))
            both.observe()
            ob = both.step(tg, 0.01, 0.7, hold=hold)
            for i, e in enumerate(singles):
                e.observe()
                os_ = e.step(tg[i:i + 1], 0.01, 0.7, hold=hold[i:i + 1])
                self.assertAlmostEqual(float(ob["equity"][i]), float(os_["equity"][0]), delta=1e-6)


@unittest.skipIf(torch is None, "torch not installed")
class TrainingModeTest(unittest.TestCase):
    def test_gradients_finite_through_a_segment(self):
        from qount.research.etf_trader.features import world_features
        from qount.research.etf_trader.policy import PolicyConfig, Trader
        from qount.research.etf_trader.train import WorldArrays, run_segment, to_tensors
        from qount.research.etf_trader.torch_env import TorchEnv

        worlds = []
        for acct_name, seed in (("cn", 1), ("cn", 2)):
            w = _world(acct_name, seed, warmup=5.0)  # factors need ~4 years of history
            d = w.data
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                f = world_features(d.close_adj, ACCOUNTS["cn"], w.valuation, d.adv, d.spread)
            s = w.start
            worlds.append(WorldArrays(d.close_adj[s:], d.close[s:], d.open[s:], d.adv[s:], d.sigma[s:],
                                      d.cash_return[s:], d.spread[s:], d.buy_blocked[s:], f.sliced(s), 1.3, 0.7, 0))
        et = to_tensors(worlds, "cpu")
        acct = ACCOUNTS["cn"]
        model = Trader(PolicyConfig(d_phi=16, hidden=16))
        env = TorchEnv(et.batch, acct, cost_params_for(acct), exact=False, spread_mult=et.spread_mult,
                       impact_mult=et.impact_mult)
        self.assertTrue(et.eligible[:, 0].any())
        out, _ = run_segment(env, model, et, model.initial_state(2), 120, acct)
        loss = -torch.log1p(out["ret"]).sum(dim=1).mean()
        loss.backward()
        grads = [p.grad for p in model.parameters()]
        self.assertTrue(all(g is not None and torch.isfinite(g).all() for g in grads))
        self.assertGreater(sum(float(g.abs().sum()) for g in grads), 0.0)

    def test_construct_matches_numpy(self):
        from qount.research.etf_trader.policy import Action, construct

        rng = np.random.default_rng(0)
        for account in (US_ACCOUNT, ACCOUNTS["cn"]):
            n = account.n_assets
            ranks = rng.random((6, n, 4))
            sigma = rng.uniform(0.005, 0.02, (6, n))
            elig = rng.random((6, n)) > 0.15
            alpha = rng.dirichlet(np.ones(4), 6)
            tau, g = rng.uniform(0.03, 1.0, 6), rng.uniform(0.2, 1.0, 6)
            act = Action(alpha=torch.as_tensor(alpha), gross=torch.as_tensor(g), tau=torch.as_tensor(tau),
                         band=torch.zeros(6, dtype=torch.float64), kappa=torch.ones(6, dtype=torch.float64))
            got = construct(torch.as_tensor(ranks), torch.as_tensor(sigma), torch.as_tensor(elig), act, account).numpy()
            for i in range(6):
                score = S.composite_score(np.moveaxis(ranks[i], -1, 0), alpha[i])
                want = S.construct_weights(score, sigma[i], tau[i], g[i], account, eligible=elig[i])
                np.testing.assert_allclose(got[i], want, rtol=1e-10, atol=1e-14)


if __name__ == "__main__":
    unittest.main()
