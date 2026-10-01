import unittest
from dataclasses import replace

import numpy as np

from qount.research import cta_r_paper
from qount.research.etf_trader import baselines as B
from qount.research.etf_trader import constraints as C
from qount.research.etf_trader.costs import cost_params_for
from qount.research.etf_trader.env import Decision, MarketData, max_rolling_turnover, simulate, summarize
from qount.research.etf_trader.universe import CN_ACCOUNT, US_ACCOUNT

US_FRAC = replace(US_ACCOUNT, fractional_shares=True)


def _market(T=600, n=9, seed=0, drift=2e-4, vol=0.01, div=0.0, cash=0.0):
    rng = np.random.default_rng(seed)
    r = drift + vol * rng.standard_normal((T, n))
    close = 50.0 * np.exp(np.cumsum(r, axis=0))
    close_adj = close * (1.0 + div) ** np.arange(T)[:, None]
    return MarketData(
        close_adj=close_adj,
        close=close,
        open=close * np.exp(0.002 * rng.standard_normal((T, n))),
        adv=np.full((T, n), 1e10),
        sigma=np.full((T, n), vol),
        cash_return=np.full(T, cash),
    )


def _zero_costs(account):
    p = cost_params_for(account)
    return replace(p, sec_fee_rate=0.0, taf_per_share=0.0, commission_rate=0.0, min_fee=0.0,
                   half_spread=(0.0,) * account.n_assets, tick=1e-12, k_impact=0.0)


class EnvAccountingTest(unittest.TestCase):
    def test_cash_only_compounds_cash_rate(self):
        data = _market(T=253, cash=1e-4)
        res = simulate(data, US_FRAC, lambda o: Decision(target=np.zeros(9)), cost_params_for(US_FRAC))
        self.assertAlmostEqual(res.equity[-1] / res.equity[0], (1 + 1e-4) ** 252, places=10)
        self.assertEqual(res.costs.sum(), 0.0)

    def test_hold_earns_adjusted_return_including_distributions(self):
        data = _market(T=300, div=1e-4)
        w = np.zeros(9); w[0] = 0.15; w[5] = 0.15  # far from the 35% cap, so no trims
        pol = B.scheduled_policy(np.tile(w, (300, 1)), first=0, every=10_000)
        # De-risk off: the two runs must keep identical shares.
        off = lambda: C.DeRisk(d1=0.98, d2=0.99)
        res = simulate(data, US_FRAC, pol, _zero_costs(US_FRAC), derisk=off())
        base = simulate(replace(data, close_adj=data.close), US_FRAC, pol, _zero_costs(US_FRAC), derisk=off())
        # Same shares in both runs; distributions are paid into (zero-yield) cash.
        self.assertEqual(res.voluntary_turnover[2:].sum() + base.voluntary_turnover[2:].sum(), 0.0)
        sh = res.weights[1] * res.equity[1] / data.close[1]
        # Day t pays shares × close[t] × 1e-4 (adjusted grows 1e-4/day faster), from the first fill day.
        paid = sum(sh @ (data.close[t] * 1e-4) for t in range(1, 300))
        self.assertAlmostEqual(res.equity[-1] - base.equity[-1], paid, places=6)
        # Each day's return on the invested part equals the adjusted return.
        t = 150
        pnl = res.equity[t] - res.equity[t - 1]
        self.assertAlmostEqual(pnl, sh @ (data.close[t - 1] * (data.close_adj[t] / data.close_adj[t - 1] - 1)), places=6)

    def test_costs_only_reduce_equity(self):
        data = _market(T=400, seed=1)
        pol = B.scheduled_policy(B.equal_weight(data.close) * 0.9, first=0, every=5)
        free = simulate(data, US_FRAC, pol, _zero_costs(US_FRAC))
        paid = simulate(data, US_FRAC, pol, cost_params_for(US_FRAC), cost_multiplier=3.0)
        self.assertLess(paid.equity[-1], free.equity[-1])
        self.assertGreater(paid.costs.sum(), 0.0)

    def test_turnover_budget_holds_under_churn(self):
        data = _market(T=700, seed=2)
        rng = np.random.default_rng(9)

        def churn(obs):
            w = rng.dirichlet(np.ones(9)) * 0.9
            return Decision(target=np.minimum(w, 0.35))

        res = simulate(data, US_FRAC, churn, cost_params_for(US_FRAC))
        self.assertLessEqual(max_rolling_turnover(res.voluntary_turnover), US_FRAC.turnover_budget + 1e-6)
        self.assertGreater(max_rolling_turnover(res.voluntary_turnover), 3.5)
        self.assertEqual(int(res.forced_breach.sum()), 0)

    def test_derisk_engages_in_crash(self):
        data = _market(T=400, seed=3, drift=-4e-3, vol=0.005)
        pol = lambda o: Decision(target=np.full(9, 0.1))
        res = simulate(data, US_FRAC, pol, cost_params_for(US_FRAC))
        s = summarize(res)
        self.assertGreater(s["days_derisked"], 0)
        self.assertGreater(s["turnover_forced_per_year"], 0.0)
        # The cap decided at close t binds the fill at the open of t+1.
        rows = np.flatnonzero(res.gross_cap[:-1] < 0.3) + 1
        self.assertGreater(rows.size, 0)
        self.assertLessEqual(np.max(res.weights[rows].sum(axis=1)), 0.2 + 0.02)

    def test_cn_lots_and_limit_up_block(self):
        T, n = 60, 8
        data = _market(T=T, n=n, seed=4)
        opn = data.open.copy()
        opn[1, 0] = data.close[0, 0] * 1.10  # limit-up open on the first fill day
        data = replace(data, open=opn, close=np.round(data.close, 3), close_adj=np.round(data.close, 3))
        w = np.full(n, 0.1)
        res = simulate(data, CN_ACCOUNT, lambda o: Decision(target=w), cost_params_for(CN_ACCOUNT))
        self.assertTrue(res.voided[1, 0])
        self.assertEqual(res.weights[1, 0], 0.0)
        self.assertGreater(res.weights[2, 0], 0.0)

    def test_summary_keys(self):
        data = _market(T=300)
        res = simulate(data, US_FRAC, lambda o: Decision(target=np.full(9, 0.1)), cost_params_for(US_FRAC))
        s = summarize(res)
        for key in ("cagr", "sharpe", "max_drawdown", "turnover_voluntary_per_year", "cost_drag_per_year"):
            self.assertIn(key, s)


class BaselineTest(unittest.TestCase):
    def test_cta_r_matches_frozen_rule(self):
        data = _market(T=400, seed=5, drift=3e-4, vol=0.012)
        w = B.cta_r(data.close)
        syms = US_ACCOUNT.symbols
        prices = {s: list(data.close[:, j]) for j, s in enumerate(syms)}
        rets = {s: [0.0] + [p[i] / p[i - 1] - 1 for i in range(1, len(p))] for s, p in prices.items()}
        for t in (260, 333, 399):
            ref = cta_r_paper._weights(prices, rets, t)
            expect = np.array([ref.get(s, 0.0) for s in syms])
            np.testing.assert_allclose(w[t], expect, atol=1e-12)
        self.assertTrue(np.isnan(w[100]).all())

    def test_sixty_forty(self):
        w = B.sixty_forty(np.ones((3, 8)), CN_ACCOUNT)
        self.assertAlmostEqual(w[0, CN_ACCOUNT.index("510300")], 0.6)
        self.assertAlmostEqual(w[0, CN_ACCOUNT.index("511010")], 0.4)

    def test_all_baselines_run_through_env(self):
        data = _market(T=1100, seed=6)
        out = {}
        for name, (targets, every) in B.all_baselines(data.close, US_FRAC).items():
            pol = B.scheduled_policy(targets, B.first_ready(targets), every)
            res = simulate(data, US_FRAC, pol, cost_params_for(US_FRAC))
            out[name] = summarize(res)
        self.assertEqual(set(out), {"fixed_scorer", "cta_r", "equal_weight", "sixty_forty", "buy_and_hold"})
        for s in out.values():
            self.assertLessEqual(s["turnover_voluntary_per_year"], 4.0 + 1e-6)


if __name__ == "__main__":
    unittest.main()
