"""Four-factor expert scorer and weight construction (design §3–§4).

All panels are ``(T, n)`` arrays of *adjusted* closes (or derived series) with NaN where an
asset has no data yet.  Every statistic at row ``t`` only uses rows ``<= t`` (point-in-time).
Factors are converted to cross-sectional percentile ranks before being mixed, so the prior
``α`` is a statement about ranks, not raw magnitudes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .universe import Account

FACTORS = ("momentum", "trend_orth", "value", "risk")
PRIOR_ALPHA = np.array([6.0, 4.0, 4.0, 3.0]) / 17.0
EFFECTIVE_WEIGHT_FLAG = 1.5
TRADING_DAYS = 252
ZSCORE_CLIP = 5.0


class ScorerError(ValueError):
    pass


@dataclass(frozen=True)
class ScorerConfig:
    momentum_skip: int = 5
    momentum_horizons: tuple[int, ...] = (21, 63, 126, 252)
    vol_window: int = 63
    sma_fast: int = 50
    sma_slow: int = 200
    slope_lag: int = 20
    above_window: int = 252
    orth_window: int = 252
    value_window: int = 2520
    value_min_periods: int | None = None  # None -> full window
    risk_window: int = 756
    risk_min_periods: int | None = None
    drawdown_window: int = 252


@dataclass(frozen=True)
class Factors:
    raw: dict[str, np.ndarray]  # un-ranked factor values, for the network's z-scored inputs
    ranks: np.ndarray  # (4, T, n) cross-sectional percentile ranks in FACTORS order
    value_enabled: bool

    def score(self, alpha: np.ndarray = PRIOR_ALPHA) -> np.ndarray:
        return composite_score(self.ranks, alpha)


# ---------------------------------------------------------------------------
# PIT rolling primitives


def shift(x: np.ndarray, k: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full_like(x, np.nan)
    if k < x.shape[0]:
        out[k:] = x[: x.shape[0] - k]
    return out


def daily_returns(close: np.ndarray) -> np.ndarray:
    close = np.asarray(close, dtype=float)
    return close / shift(close, 1) - 1.0


def _rolling_sum(x: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    valid = np.isfinite(x)
    pad = np.zeros((1,) + x.shape[1:])
    cs = np.concatenate([pad, np.cumsum(np.where(valid, x, 0.0), axis=0)])
    cc = np.concatenate([pad, np.cumsum(valid, axis=0)])
    total = np.full(x.shape, np.nan)
    count = np.zeros(x.shape)
    if window <= x.shape[0]:
        total[window - 1 :] = cs[window:] - cs[:-window]
        count[window - 1 :] = cc[window:] - cc[:-window]
    return total, count


def rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    """Mean over the trailing ``window`` rows; NaN unless the full window is finite."""
    total, count = _rolling_sum(x, window)
    return np.where(count == window, total / window, np.nan)


def rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    mean = rolling_mean(x, window)
    mean_sq = rolling_mean(x * x, window)
    var = np.maximum(mean_sq - mean * mean, 0.0) * window / (window - 1)
    return np.sqrt(var)


def rolling_max(x: np.ndarray, window: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    out = np.full_like(x, np.nan)
    if window <= x.shape[0]:
        out[window - 1 :] = sliding_window_view(x, window, axis=0).max(axis=-1)
    return out


def rolling_percentile(
    x: np.ndarray, window: int, min_periods: int | None = None, chunk: int = 1024
) -> np.ndarray:
    """Mid-rank percentile of ``x[t]`` within each asset's own trailing ``window`` values."""
    x = np.asarray(x, dtype=float)
    min_periods = window if min_periods is None else min_periods
    T = x.shape[0]
    out = np.full_like(x, np.nan)
    for j in range(x.shape[1]):
        col = x[:, j]
        windows = sliding_window_view(np.concatenate([np.full(window - 1, np.nan), col]), window)
        for start in range(0, T, chunk):
            stop = min(start + chunk, T)
            cur = col[start:stop, None]
            win = windows[start:stop]
            count = np.isfinite(win).sum(axis=1)
            pct = ((win < cur).sum(axis=1) + 0.5 * (win == cur).sum(axis=1)) / np.maximum(count, 1)
            ok = np.isfinite(col[start:stop]) & (count >= min_periods)
            out[start:stop, j] = np.where(ok, pct, np.nan)
    return out


def rolling_zscore(x: np.ndarray, window: int = 756, clip: float = ZSCORE_CLIP) -> np.ndarray:
    """Per-asset PIT z-score for the network's raw-value inputs, clipped to ±clip."""
    mean = rolling_mean(x, window)
    std = rolling_std(x, window)
    z = np.divide(np.asarray(x, dtype=float) - mean, std, out=np.full_like(mean, np.nan), where=std > 0)
    return np.clip(z, -clip, clip)


def percentile_rank(x: np.ndarray) -> np.ndarray:
    """Cross-sectional percentile per row with average ties: ``(rank-1)/(m-1)`` in [0, 1].

    NaN stays NaN; a row with a single finite value gets 0.5.
    """
    x = np.asarray(x, dtype=float)
    valid = np.isfinite(x)
    a, b = x[..., :, None], x[..., None, :]
    both = valid[..., :, None] & valid[..., None, :]
    less = ((b < a) & both).sum(axis=-1)
    equal = ((b == a) & both).sum(axis=-1)
    m = valid.sum(axis=-1, keepdims=True)
    pct = np.divide(less + 0.5 * (equal - 1), m - 1, out=np.full(x.shape, 0.5), where=m > 1)
    return np.where(valid, pct, np.nan)


# ---------------------------------------------------------------------------
# Factors


def momentum(close: np.ndarray, cfg: ScorerConfig = ScorerConfig()) -> np.ndarray:
    """Mean of skip-5 horizon returns, each divided by annualized 63-day vol."""
    close = np.asarray(close, dtype=float)
    vol = rolling_std(daily_returns(close), cfg.vol_window) * np.sqrt(TRADING_DAYS)
    base = shift(close, cfg.momentum_skip)
    rets = [base / shift(close, cfg.momentum_skip + h) - 1.0 for h in cfg.momentum_horizons]
    return np.divide(np.mean(rets, axis=0), vol, out=np.full(close.shape, np.nan), where=vol > 0)


def trend_components(close: np.ndarray, cfg: ScorerConfig = ScorerConfig()) -> dict[str, np.ndarray]:
    close = np.asarray(close, dtype=float)
    fast = rolling_mean(close, cfg.sma_fast)
    slow = rolling_mean(close, cfg.sma_slow)
    above = np.where(np.isfinite(slow) & np.isfinite(close), (close > slow).astype(float), np.nan)
    return {
        "distance": close / slow - 1.0,
        "slope_fast": np.sign(fast - shift(fast, cfg.slope_lag)),
        "slope_slow": np.sign(slow - shift(slow, cfg.slope_lag)),
        "frac_above": rolling_mean(above, cfg.above_window),
    }


def trend_composite(close: np.ndarray, cfg: ScorerConfig = ScorerConfig()) -> np.ndarray:
    """Equal mix of the cross-sectional ranks of the four trend components."""
    parts = [percentile_rank(v) for v in trend_components(close, cfg).values()]
    return np.mean(parts, axis=0)  # NaN if any component is missing


def residualize_pooled(y: np.ndarray, x: np.ndarray, window: int = 252) -> np.ndarray:
    """Residual of ``y`` on ``x`` from a pooled (all assets) trailing-``window`` OLS.

    The fit at row ``t`` uses every finite (x, y) pair in rows ``t-window+1..t``.
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    xv, yv = np.where(valid, x, 0.0), np.where(valid, y, 0.0)
    daily = np.stack(
        [valid.sum(axis=1), xv.sum(axis=1), yv.sum(axis=1), (xv * xv).sum(axis=1), (xv * yv).sum(axis=1)],
        axis=1,
    ).astype(float)
    sums, _ = _rolling_sum(daily, window)
    n, sx, sy, sxx, sxy = sums.T
    denom = n * sxx - sx * sx
    ok = np.isfinite(denom) & (denom > 1e-12) & (n >= 3)
    beta = np.divide(n * sxy - sx * sy, denom, out=np.full(n.shape, np.nan), where=ok)
    alpha = np.divide(sy - beta * sx, n, out=np.full(n.shape, np.nan), where=ok)
    return y - alpha[:, None] - beta[:, None] * x


def value(
    valuation: np.ndarray | None,
    kinds: tuple[str, ...],
    cfg: ScorerConfig = ScorerConfig(),
) -> tuple[np.ndarray, bool]:
    """Own-history cheapness in [0, 1]; returns ``(panel, enabled)``.

    ``valuation`` holds PE/PB for ``"valuation"`` assets and yield for ``"yield"`` assets.
    Gold/commodity (``"neutral"``) and any missing entry get 0.5.  ``enabled`` is False when
    no valuation data is usable, and reports must then say "Value 未启用".
    """
    if valuation is None:
        return np.full((0, len(kinds)), 0.5), False
    valuation = np.asarray(valuation, dtype=float)
    if valuation.shape[1] != len(kinds):
        raise ScorerError("valuation columns must match the account's assets")
    pct = rolling_percentile(valuation, cfg.value_window, cfg.value_min_periods)
    kinds_arr = np.asarray(kinds)
    cheap = np.where(kinds_arr == "valuation", 1.0 - pct, np.where(kinds_arr == "yield", pct, np.nan))
    enabled = bool(np.isfinite(cheap).any())
    return np.where(np.isfinite(cheap), cheap, 0.5), enabled


def risk(close: np.ndarray, cfg: ScorerConfig = ScorerConfig()) -> np.ndarray:
    """1 - mean own-history percentile of (63d vol, current drawdown, 63d downside vol)."""
    close = np.asarray(close, dtype=float)
    r = daily_returns(close)
    vol = rolling_std(r, cfg.vol_window)
    drawdown = 1.0 - close / rolling_max(close, cfg.drawdown_window)
    downside = np.sqrt(rolling_mean(np.minimum(r, 0.0) ** 2, cfg.vol_window))
    pcts = [rolling_percentile(v, cfg.risk_window, cfg.risk_min_periods) for v in (vol, drawdown, downside)]
    return 1.0 - np.mean(pcts, axis=0)


def compute_factors(
    close: np.ndarray,
    account: Account,
    valuation: np.ndarray | None = None,
    cfg: ScorerConfig = ScorerConfig(),
) -> Factors:
    close = np.asarray(close, dtype=float)
    if close.ndim != 2 or close.shape[1] != account.n_assets:
        raise ScorerError(f"close must be (T, {account.n_assets})")
    mom = momentum(close, cfg)
    rank_m = percentile_rank(mom)
    trend = trend_composite(close, cfg)
    trend_orth = residualize_pooled(trend, rank_m, cfg.orth_window)
    val, enabled = value(valuation, account.value_kinds(), cfg)
    if not enabled:
        val = np.full(close.shape, 0.5)
    rsk = risk(close, cfg)
    raw = {"momentum": mom, "trend_orth": trend_orth, "value": val, "risk": rsk}
    ranks = np.stack([rank_m, percentile_rank(trend_orth), percentile_rank(val), percentile_rank(rsk)])
    return Factors(raw=raw, ranks=ranks, value_enabled=enabled)


# ---------------------------------------------------------------------------
# Score, effective weights, construction


def composite_score(ranks: np.ndarray, alpha: np.ndarray = PRIOR_ALPHA) -> np.ndarray:
    """``S = Σ α_k · rank_k``; NaN (ineligible) when any factor rank is missing."""
    alpha = np.asarray(alpha, dtype=float)
    if ranks.shape[0] != alpha.shape[0] or not np.isclose(alpha.sum(), 1.0) or np.any(alpha < 0):
        raise ScorerError("alpha must be a non-negative simplex vector matching the factors")
    return np.tensordot(alpha, ranks, axes=1)


@dataclass(frozen=True)
class EffectiveWeights:
    nominal: np.ndarray
    effective: np.ndarray
    flagged: np.ndarray  # effective > 1.5 × nominal


def effective_weights(ranks: np.ndarray, alpha: np.ndarray = PRIOR_ALPHA) -> EffectiveWeights:
    """``α_eff,k = α_k · Cov(rank_k, S) / Var(S)``, pooled over all eligible (t, i); sums to 1."""
    alpha = np.asarray(alpha, dtype=float)
    s = composite_score(ranks, alpha)
    mask = np.isfinite(s)
    if mask.sum() < 2:
        raise ScorerError("not enough eligible observations")
    sv = s[mask] - s[mask].mean()
    rv = ranks[:, mask] - ranks[:, mask].mean(axis=1, keepdims=True)
    var = float(np.mean(sv * sv))
    if var <= 0:
        raise ScorerError("score has zero variance")
    eff = alpha * np.mean(rv * sv, axis=1) / var
    return EffectiveWeights(nominal=alpha, effective=eff, flagged=eff > EFFECTIVE_WEIGHT_FLAG * alpha)


def construct_weights(
    score: np.ndarray,
    sigma: np.ndarray,
    tau: float,
    gross: float,
    account: Account,
    eligible: np.ndarray | None = None,
    single_cap: float | np.ndarray | None = None,
) -> np.ndarray:
    """One row of target weights: ``w ∝ exp(S/τ)/σ``, × g, then single and group caps.

    Weight removed by a cap is left in cash, not redistributed.  ``single_cap`` may be a
    per-asset array (e.g. the liquidity capacity cap) and defaults to the account's 35%.
    """
    if tau <= 0 or not 0.0 <= gross <= 1.0:
        raise ScorerError("tau must be positive and gross in [0, 1]")
    score = np.asarray(score, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    ok = np.isfinite(score) & np.isfinite(sigma) & (sigma > 0)
    if eligible is not None:
        ok &= np.asarray(eligible, dtype=bool)
    w = np.zeros(account.n_assets)
    if not ok.any():
        return w
    z = score[ok] / tau
    raw = np.exp(z - z.max()) / sigma[ok]
    w[ok] = gross * raw / raw.sum()
    w = np.minimum(w, account.single_cap if single_cap is None else single_cap)
    for group in account.group_indices():
        idx = list(group)  # a tuple would index dimensions, not positions
        total = w[idx].sum()
        if total > account.group_cap:
            w[idx] *= account.group_cap / total
    return w


def absolute_trend_filter(close: np.ndarray, horizons: tuple[int, ...] = (63, 126, 252)) -> np.ndarray:
    """True where the mean sign of the horizon returns is positive (missing -> False)."""
    close = np.asarray(close, dtype=float)
    signs = np.mean([np.sign(close / shift(close, h) - 1.0) for h in horizons], axis=0)
    return np.nan_to_num(signs, nan=0.0) > 0


# Fixed-scorer baseline knobs. τ and g are not pinned by the design doc; these are defaults.
DEFAULT_TAU = 0.2
DEFAULT_GROSS = 1.0
REBALANCE_EVERY = 21


def fixed_scorer_targets(
    close: np.ndarray,
    account: Account,
    valuation: np.ndarray | None = None,
    tau: float = DEFAULT_TAU,
    gross: float = DEFAULT_GROSS,
    rebalance_every: int = REBALANCE_EVERY,
    cfg: ScorerConfig = ScorerConfig(),
) -> tuple[np.ndarray, Factors]:
    """Prior-α targets refreshed every ``rebalance_every`` rows and held in between.

    Rows before the first eligible score are NaN; filtered-out assets hold cash.
    """
    close = np.asarray(close, dtype=float)
    factors = compute_factors(close, account, valuation, cfg)
    score = factors.score()
    sigma = rolling_std(daily_returns(close), cfg.vol_window)
    trend_ok = absolute_trend_filter(close)
    targets = np.full(close.shape, np.nan)
    ready = np.flatnonzero(np.isfinite(score).any(axis=1))
    if ready.size == 0:
        return targets, factors
    current = None
    for t in range(ready[0], close.shape[0]):
        if (t - ready[0]) % rebalance_every == 0:
            current = construct_weights(score[t], sigma[t], tau, gross, account) * trend_ok[t]
        targets[t] = current
    return targets, factors
