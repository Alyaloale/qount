"""Reference strategies run through the same engine, costs and turnover budget (design §8).

Each baseline is a ``(T, n)`` target panel plus a rebalance schedule; :func:`scheduled_policy`
turns it into an env policy that trades only on rebalance rows (band 0, κ 1) and otherwise
lets weights drift.  The oracle and analytic-subfamily Bayes baselines need generator
internals and live next to the generator.
"""

from __future__ import annotations

import numpy as np

from . import scorer as S
from .env import Decision, Observation, Policy
from .universe import SIXTY_FORTY, Account

REBALANCE_EVERY = 21
CTA_R_LOOKBACKS = (63, 126, 252)
CTA_R_VOL = 63
CTA_R_CAP = 0.35


def scheduled_policy(targets: np.ndarray, first: int, every: int = REBALANCE_EVERY) -> Policy:
    """Trade to ``targets[t]`` on rows ``first, first+every, …``; NaN rows are skipped."""
    targets = np.asarray(targets, dtype=float)

    def policy(obs: Observation) -> Decision:
        t = obs.t
        if t < first or (t - first) % every or not np.all(np.isfinite(targets[t])):
            return Decision(target=None)
        return Decision(target=targets[t])

    return policy


def first_ready(targets: np.ndarray) -> int:
    ready = np.flatnonzero(np.isfinite(targets).all(axis=1))
    if ready.size == 0:
        raise ValueError("baseline never becomes ready")
    return int(ready[0])


def fixed_scorer(close: np.ndarray, account: Account, valuation: np.ndarray | None = None, **kw) -> np.ndarray:
    """§2.4: prior α, fixed τ/g, monthly, absolute-trend filtered."""
    targets, _ = S.fixed_scorer_targets(close, account, valuation, **kw)
    return targets


def cta_r(close: np.ndarray) -> np.ndarray:
    """Frozen CTA-R rule (``cta_r_paper._weights``) vectorized over rows.

    signal = mean sign of 63/126/252 returns; long-only if > 0, weight ∝ signal / σ63,
    normalized to 1, then each capped at 35% with the excess left in cash.
    """
    close = np.asarray(close, dtype=float)
    r = S.daily_returns(close)
    vol = S.rolling_std(r, CTA_R_VOL)
    signs = np.mean([np.sign(close - S.shift(close, h)) for h in CTA_R_LOOKBACKS], axis=0)
    raw = np.where((signs > 0) & (vol > 0), signs / vol, 0.0)
    gross = raw.sum(axis=1, keepdims=True)
    w = np.divide(raw, gross, out=np.zeros_like(raw), where=gross > 0)
    w = np.minimum(w, CTA_R_CAP)
    ready = np.isfinite(signs).all(axis=1) & np.isfinite(vol).all(axis=1)
    return np.where(ready[:, None], w, np.nan)


def equal_weight(close: np.ndarray) -> np.ndarray:
    close = np.asarray(close, dtype=float)
    n = close.shape[1]
    return np.where(np.isfinite(close).all(axis=1, keepdims=True), 1.0 / n, np.nan) * np.ones_like(close)


def sixty_forty(close: np.ndarray, account: Account) -> np.ndarray:
    w = np.zeros(account.n_assets)
    for symbol, weight in SIXTY_FORTY[account.name].items():
        w[account.index(symbol)] = weight
    return np.tile(w, (np.shape(close)[0], 1))


def buy_and_hold(close: np.ndarray) -> np.ndarray:
    """Equal-weight entry once; use with ``every`` larger than the sample."""
    return equal_weight(close)


ORACLE_RISK_AVERSION = 2.0


def oracle_weights(
    mu: np.ndarray,
    var: np.ndarray,
    cash_return: np.ndarray,
    account: Account,
    risk_aversion: float = ORACLE_RISK_AVERSION,
) -> np.ndarray:
    """Diagonal mean-variance on the *true* next-day moments (§8 upper bound).

    ``w_i = max(0, μ_i − r_f) / (γ σ²_i)``, then single cap, group caps and gross ≤ 1.
    It ignores correlations and costs, so it is a reference, not an optimum.
    """
    mu = np.asarray(mu, dtype=float)
    var = np.asarray(var, dtype=float)
    rf = np.asarray(cash_return, dtype=float).reshape(-1, 1)
    excess = mu - rf
    w = np.divide(np.maximum(excess, 0.0), risk_aversion * var, out=np.zeros_like(mu), where=var > 0)
    w = np.minimum(w, account.single_cap)
    for group in account.group_indices():
        idx = list(group)
        total = w[:, idx].sum(axis=1, keepdims=True)
        w[:, idx] *= np.where(total > account.group_cap, account.group_cap / np.maximum(total, 1e-12), 1.0)
    gross = w.sum(axis=1, keepdims=True)
    return w / np.maximum(gross, 1.0)


def all_baselines(close: np.ndarray, account: Account, valuation: np.ndarray | None = None, **scorer_kw) -> dict[str, tuple[np.ndarray, int]]:
    """``name -> (targets, rebalance_every)`` for the §8 comparison set."""
    T = np.shape(close)[0]
    return {
        "fixed_scorer": (fixed_scorer(close, account, valuation, **scorer_kw), REBALANCE_EVERY),
        "cta_r": (cta_r(close), REBALANCE_EVERY),
        "equal_weight": (equal_weight(close), REBALANCE_EVERY),
        "sixty_forty": (sixty_forty(close, account), REBALANCE_EVERY),
        "buy_and_hold": (buy_and_hold(close), T + 1),
    }
