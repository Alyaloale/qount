"""Analytic subfamily with an exact Bayes-optimal filtering benchmark (design §8.1).

Two small worlds in which the posterior over tomorrow's moments is available in closed form:

- ``ar1``: per-asset excess drift ``m_t = m̄ + x_t``, ``x_t = a·x_{t-1} + η``, return
  ``r_t = m̄ + x_{t-1} + ε`` (linear Gaussian) → scalar Kalman filter is exact.
- ``hmm``: a regime chain with known transition matrix; ``r_t | s_t ~ N(μ_s, σ²_s)``
  independently across assets → the forward (Wonham/Hamilton) filter is exact.

Loss.  The oracle knows the latent state and takes the myopic mean–variance action on its
own one-step moments ``(m_o, v_o)``; every policy is scored by the oracle criterion
``CE(w) = w·m_o − ½γ Σ w²·v_o`` (daily, excess of cash).  CE is linear in ``(m_o, v_o)``,
so the action that maximizes ``E[CE | F_t]`` uses the posterior means of the oracle
moments; :func:`ar1_filter` / :func:`hmm_filter` return exactly those.  Because
:func:`mv_weights` solves the constrained diagonal QP exactly, no ``F_t``-measurable policy
can beat the Bayes action in expected CE: Bayes regret is the information cost, not a
decision-rule artifact.  This holds for this subfamily only; full structural worlds report
regret against the oracle alone (§8.1).

Prices are frictionless and open = previous close, so a decision at close t earns exactly
the simulated return of t+1.  Generated data never touches real history and uses no trial.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..env import MarketData
from ..universe import Account
from .params import YEAR

MV_RISK_AVERSION = 2.0
_BISECT_ITERS = 80


# ---------------------------------------------------------------------------
# Parameters


@dataclass(frozen=True)
class AR1Params:
    m_bar: np.ndarray  # (n,) daily excess drift mean
    a: np.ndarray  # (n,) AR coefficient of the drift deviation
    q: np.ndarray  # (n,) innovation variance of the drift deviation
    r: np.ndarray  # (n,) return noise variance
    rf: float  # daily cash return
    seed: int

    @property
    def n(self) -> int:
        return int(np.size(self.m_bar))

    @property
    def p0(self) -> np.ndarray:
        """Stationary variance of the drift deviation."""
        return self.q / (1.0 - self.a**2)


@dataclass(frozen=True)
class HMMParams:
    P: np.ndarray  # (K, K) daily transition matrix, rows sum to 1
    mean: np.ndarray  # (K, n) daily excess mean per regime
    var: np.ndarray  # (K, n) daily variance per regime
    rf: float
    seed: int

    @property
    def K(self) -> int:
        return int(self.P.shape[0])

    @property
    def n(self) -> int:
        return int(self.mean.shape[1])

    @property
    def stationary(self) -> np.ndarray:
        vals, vecs = np.linalg.eig(self.P.T)
        v = np.real(vecs[:, np.argmin(np.abs(vals - 1.0))])
        return v / v.sum()

    def oracle_moments(self) -> tuple[np.ndarray, np.ndarray]:
        """Per current regime s: (m_o(s), v_o(s)) of tomorrow's excess return, each (K, n)."""
        m = self.P @ self.mean
        v = self.P @ (self.var + self.mean**2) - m**2
        return m, v


def _annual_to_daily(mu: np.ndarray, vol: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(mu) / YEAR, np.asarray(vol) ** 2 / YEAR


def sample_ar1(n: int, rng: np.random.Generator, *, rf_annual: float = 0.02, seed: int | None = None) -> AR1Params:
    """Prior: drift mean U(0, 6%), drift sd U(2%, 10%), half-life U(21, 252)d, vol U(5%, 30%) (annual)."""
    m_bar, r = _annual_to_daily(rng.uniform(0.0, 0.06, n), rng.uniform(0.05, 0.30, n))
    a = 0.5 ** (1.0 / rng.uniform(21.0, 252.0, n))
    sd = rng.uniform(0.02, 0.10, n) / YEAR
    return AR1Params(m_bar=m_bar, a=a, q=sd**2 * (1.0 - a**2), r=r, rf=rf_annual / YEAR,
                     seed=int(rng.integers(2**31)) if seed is None else seed)


def sample_hmm(n: int, rng: np.random.Generator, *, K: int = 2, rf_annual: float = 0.02,
               seed: int | None = None) -> HMMParams:
    """Prior: regime means N(4%, 10%), vols U(8%, 30%) (annual), mean durations U(3, 24) months."""
    mean, var = _annual_to_daily(rng.normal(0.04, 0.10, (K, n)), rng.uniform(0.08, 0.30, (K, n)))
    exit_p = 1.0 / (rng.uniform(3.0, 24.0, K) * 21.0)
    P = np.empty((K, K))
    for k in range(K):
        P[k] = exit_p[k] / max(K - 1, 1)
        P[k, k] = 1.0 - exit_p[k] if K > 1 else 1.0
    return HMMParams(P=P, mean=mean, var=var, rf=rf_annual / YEAR,
                     seed=int(rng.integers(2**31)) if seed is None else seed)


# ---------------------------------------------------------------------------
# Worlds


@dataclass(frozen=True)
class AnalyticWorld:
    kind: str  # "ar1" | "hmm"
    params: AR1Params | HMMParams
    excess: np.ndarray  # (T, n) excess return realized over day t (row 0 is 0)
    oracle_m: np.ndarray  # (T, n) oracle mean of r_{t+1} at close t
    oracle_v: np.ndarray  # (T, n) oracle variance of r_{t+1} at close t
    state: np.ndarray  # ar1: (T, n) drift deviation x_t; hmm: (T,) regime s_t
    data: MarketData

    @property
    def T(self) -> int:
        return self.excess.shape[0]


def _market(excess: np.ndarray, rf: float, vol: np.ndarray, price0: float = 100.0) -> MarketData:
    T, n = excess.shape
    gross = np.maximum(1.0 + rf + excess, 1e-3)  # guard only; never binds under the priors
    gross[0] = 1.0
    close = price0 * np.cumprod(gross, axis=0)
    opn = np.vstack([close[:1], close[:-1]])  # open = previous close: fills earn r_{t+1} exactly
    return MarketData(
        close_adj=close,
        close=close,
        open=opn,
        adv=np.full((T, n), 1e15),
        sigma=np.tile(np.sqrt(vol), (T, 1)),
        cash_return=np.r_[0.0, np.full(T - 1, rf)],
    )


def simulate_ar1(p: AR1Params, T: int) -> AnalyticWorld:
    rng = np.random.default_rng(p.seed)
    n = p.n
    x = np.empty((T, n))
    excess = np.zeros((T, n))
    x[0] = np.sqrt(p.p0) * rng.standard_normal(n)
    z_r, z_x = rng.standard_normal((T, n)), rng.standard_normal((T, n))
    for t in range(1, T):
        excess[t] = p.m_bar + x[t - 1] + np.sqrt(p.r) * z_r[t]
        x[t] = p.a * x[t - 1] + np.sqrt(p.q) * z_x[t]
    return AnalyticWorld("ar1", p, excess, p.m_bar + x, np.tile(p.r, (T, 1)), x, _market(excess, p.rf, p.r))


def simulate_hmm(p: HMMParams, T: int) -> AnalyticWorld:
    rng = np.random.default_rng(p.seed)
    P_cum = np.cumsum(p.P, axis=1)
    u = rng.random(T)
    z = rng.standard_normal((T, p.n))
    s = np.empty(T, dtype=int)
    s[0] = int(np.searchsorted(np.cumsum(p.stationary), u[0], side="right"))
    excess = np.zeros((T, p.n))
    for t in range(1, T):
        s[t] = min(int(np.searchsorted(P_cum[s[t - 1]], u[t], side="right")), p.K - 1)
        excess[t] = p.mean[s[t]] + np.sqrt(p.var[s[t]]) * z[t]
    m_o, v_o = p.oracle_moments()
    vol = p.stationary @ p.var
    return AnalyticWorld("hmm", p, excess, m_o[s], v_o[s], s, _market(excess, p.rf, vol))


def simulate_analytic(p: AR1Params | HMMParams, T: int) -> AnalyticWorld:
    return simulate_ar1(p, T) if isinstance(p, AR1Params) else simulate_hmm(p, T)


# ---------------------------------------------------------------------------
# Exact filters (use only excess[1..t] at close t)


@dataclass(frozen=True)
class Posterior:
    m: np.ndarray  # (T, n) E[m_o | F_t]  (= predictive mean of r_{t+1})
    v: np.ndarray  # (T, n) E[v_o | F_t]  (the variance the CE loss charges)
    pred_var: np.ndarray  # (T, n) Var[r_{t+1} | F_t]  (for calibration checks)
    state_var: np.ndarray | None = None  # ar1: Var[x_t | F_t]
    probs: np.ndarray | None = None  # hmm: (T, K) P(s_t | F_t)


def ar1_filter(excess: np.ndarray, p: AR1Params) -> Posterior:
    T, n = excess.shape
    m = np.empty((T, n))
    sv = np.empty((T, n))
    xp, Pp = np.zeros(n), p.p0.copy()  # predictive x_t | F_t, starting from the stationary prior
    m[0], sv[0] = p.m_bar + xp, Pp
    for t in range(1, T):
        # Pp is Var[x_{t-1} | F_{t-1}]; r_t observes x_{t-1}
        k = Pp / (Pp + p.r)
        xf = xp + k * (excess[t] - p.m_bar - xp)
        Pf = (1.0 - k) * Pp
        xp, Pp = p.a * xf, p.a**2 * Pf + p.q
        m[t], sv[t] = p.m_bar + xp, Pp
    v = np.tile(p.r, (T, 1))
    return Posterior(m=m, v=v, pred_var=sv + p.r, state_var=sv)


def hmm_filter(excess: np.ndarray, p: HMMParams) -> Posterior:
    T, n = excess.shape
    m_o, v_o = p.oracle_moments()
    probs = np.empty((T, p.K))
    pi = p.stationary.copy()
    probs[0] = pi
    log_norm = -0.5 * np.log(2 * np.pi * p.var).sum(axis=1)  # (K,)
    for t in range(1, T):
        prior = pi @ p.P
        ll = log_norm - 0.5 * (((excess[t] - p.mean) ** 2) / p.var).sum(axis=1)
        w = np.log(np.maximum(prior, 1e-300)) + ll
        w = np.exp(w - w.max())
        pi = w / w.sum()
        probs[t] = pi
    m = probs @ m_o
    v = probs @ v_o
    nxt = probs @ p.P
    pred_var = nxt @ (p.var + p.mean**2) - (nxt @ p.mean) ** 2
    return Posterior(m=m, v=v, pred_var=pred_var, probs=probs)


def bayes_posterior(world: AnalyticWorld) -> Posterior:
    f = ar1_filter if world.kind == "ar1" else hmm_filter
    return f(world.excess, world.params)


def prior_moments(world: AnalyticWorld) -> tuple[np.ndarray, np.ndarray]:
    """No-learning reference: unconditional moments, constant over time."""
    p = world.params
    if world.kind == "ar1":
        m, v = p.m_bar, p.r
    else:
        m_o, v_o = p.oracle_moments()
        m, v = p.stationary @ m_o, p.stationary @ v_o
    return np.tile(m, (world.T, 1)), np.tile(v, (world.T, 1))


def ewma_moments(excess: np.ndarray, halflife: float = 63.0) -> tuple[np.ndarray, np.ndarray]:
    """Naive plug-in learner: PIT EWMA mean and variance of past excess returns."""
    lam = 0.5 ** (1.0 / halflife)
    T, n = excess.shape
    m, s2 = np.zeros((T, n)), np.zeros((T, n))
    mean, sq = np.zeros(n), np.zeros(n)
    wsum = 0.0
    for t in range(1, T):
        wsum = lam * wsum + 1.0
        mean = lam * mean + excess[t]
        sq = lam * sq + excess[t] ** 2
        m[t] = mean / wsum
        s2[t] = np.maximum(sq / wsum - m[t] ** 2, 1e-10)
    s2[0] = np.maximum(s2[1:].mean(axis=0) if T > 1 else 1e-4, 1e-10)  # row 0 is never scored
    return m, s2


# ---------------------------------------------------------------------------
# Exact constrained diagonal mean–variance


def _bisect_shift(e: np.ndarray, v: np.ndarray, cap: float, limit: float, gamma: float) -> np.ndarray:
    """Smallest η ≥ 0 per row with Σ clip((e − η)/(γv), 0, cap) ≤ limit."""
    def total(eta):
        return np.clip((e - eta[:, None]) / (gamma * v), 0.0, cap).sum(axis=1)

    rows = e.shape[0]
    zero = np.zeros(rows)
    need = total(zero) > limit
    lo, hi = zero.copy(), np.maximum(e.max(axis=1), 0.0)
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        over = total(mid) > limit
        lo, hi = np.where(over, mid, lo), np.where(over, hi, mid)
    return np.where(need, hi, 0.0)


def mv_weights(
    m: np.ndarray,
    v: np.ndarray,
    account: Account,
    *,
    gamma: float = MV_RISK_AVERSION,
    gross: float = 1.0,
) -> np.ndarray:
    """Exact argmax of ``w·m − ½γ Σ w²v`` s.t. 0 ≤ w ≤ single cap, group sums ≤ group cap, Σw ≤ gross.

    KKT: ``w_i = clip((m_i − ν − η_g(i)) / (γ v_i), 0, cap)``.  Groups are disjoint, so for a
    given total multiplier ν each group's η is a 1-D monotone root; ν is then a monotone
    root of the total.  Both are found by vectorized bisection.  ``m`` is excess of cash.
    """
    m = np.atleast_2d(np.asarray(m, dtype=float))
    v = np.maximum(np.atleast_2d(np.asarray(v, dtype=float)), 1e-14)
    rows, n = m.shape
    cap = account.single_cap
    groups = [list(g) for g in account.group_indices()]

    def weights(nu: np.ndarray) -> np.ndarray:
        e = m - nu[:, None]
        w = np.clip(e / (gamma * v), 0.0, cap)
        for g in groups:
            eta = _bisect_shift(e[:, g], v[:, g], cap, account.group_cap, gamma)
            w[:, g] = np.clip((e[:, g] - eta[:, None]) / (gamma * v[:, g]), 0.0, cap)
        return w

    zero = np.zeros(rows)
    need = weights(zero).sum(axis=1) > gross
    lo, hi = zero.copy(), np.maximum(m.max(axis=1), 0.0)
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        over = weights(mid).sum(axis=1) > gross
        lo, hi = np.where(over, mid, lo), np.where(over, hi, mid)
    return weights(np.where(need, hi, 0.0))


def certainty_equivalent(w: np.ndarray, m_o: np.ndarray, v_o: np.ndarray, gamma: float = MV_RISK_AVERSION) -> np.ndarray:
    """Daily oracle-criterion CE per row: ``w·m_o − ½γ Σ w²·v_o``."""
    return np.sum(w * m_o, axis=1) - 0.5 * gamma * np.sum(w**2 * v_o, axis=1)


@dataclass(frozen=True)
class Regret:
    name: str
    ce_annual: float  # mean CE × 252
    regret_annual: float  # (oracle CE − CE) × 252, ≥ 0 in expectation
    regret_se: float  # standard error of regret_annual (iid approximation)
    share_of_oracle: float  # CE / oracle CE


def regret_table(world: AnalyticWorld, weights: dict[str, np.ndarray], *, burn_in: int = 252,
                 gamma: float = MV_RISK_AVERSION) -> list[Regret]:
    """Frictionless regret of each weight panel vs the oracle on rows ``burn_in .. T-2``."""
    sl = slice(burn_in, world.T - 1)
    m_o, v_o = world.oracle_m[sl], world.oracle_v[sl]
    ce = {k: certainty_equivalent(w[sl], m_o, v_o, gamma) for k, w in weights.items()}
    base = ce["oracle"]
    out = []
    for k, c in ce.items():
        gap = base - c
        out.append(Regret(
            name=k,
            ce_annual=float(c.mean() * YEAR),
            regret_annual=float(gap.mean() * YEAR),
            regret_se=float(gap.std(ddof=1) / np.sqrt(gap.size) * YEAR),
            share_of_oracle=float(c.mean() / base.mean()) if base.mean() > 0 else float("nan"),
        ))
    return out


def benchmark_weights(world: AnalyticWorld, account: Account, *, gamma: float = MV_RISK_AVERSION) -> dict[str, np.ndarray]:
    """Oracle, exact Bayes, no-learning prior and EWMA plug-in weights on the same QP."""
    post = bayes_posterior(world)
    pm, pv = prior_moments(world)
    em, ev = ewma_moments(world.excess)
    return {
        "oracle": mv_weights(world.oracle_m, world.oracle_v, account, gamma=gamma),
        "bayes": mv_weights(post.m, post.v, account, gamma=gamma),
        "prior": mv_weights(pm, pv, account, gamma=gamma),
        "ewma": mv_weights(em, ev, account, gamma=gamma),
    }
