"""Per-world policy inputs that depend only on market data (design §3.1, §3.5).

Factor ranks, PIT z-scored raw factor values, construction σ and the market state are
computed once per world in numpy and never enter BPTT.  Holdings-dependent inputs (current
weight, distance to cap, ADV capacity, account state) are built by the env each day.

Missing values: ranks → 0.5 and z-scores → 0 with ``eligible=False`` (the construction
layer gives ineligible assets zero weight).  research_only=true / orders_authorized=false.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import constraints as C
from . import scorer as S
from .universe import Account

ZSCORE_WINDOW = 756
MARKET_DIM = 6
ASSET_STATIC_DIM = 8  # 4 ranks + 4 z-scored raw values
CORR_WINDOW = 63


@dataclass(frozen=True)
class WorldFeatures:
    asset: np.ndarray  # (T, n, 8) float
    eligible: np.ndarray  # (T, n) bool: every factor finite and σ > 0
    market: np.ndarray  # (T, 6) float, PIT z-scored
    sigma: np.ndarray  # (T, n) 63-day daily vol for w ∝ exp(S/τ)/σ (NaN → 1, ineligible)
    tradable: np.ndarray  # (T, n) float: 1 unless reduce-only at the decision close
    reduce_only: np.ndarray  # (T, n) bool, as the env's liquidity rule sees it
    value_enabled: bool

    def sliced(self, start: int, stop: int | None = None) -> "WorldFeatures":
        s = slice(start, stop)
        return WorldFeatures(self.asset[s], self.eligible[s], self.market[s], self.sigma[s], self.tradable[s],
                             self.reduce_only[s], self.value_enabled)


def _rolling_corr_pairs(r: np.ndarray, window: int) -> np.ndarray:
    """Mean pairwise trailing correlation across assets per row (NaN until full)."""
    T, n = r.shape
    m = S.rolling_mean(r, window)
    sd = S.rolling_std(r, window) * np.sqrt((window - 1) / window)  # population sd
    iu = np.triu_indices(n, 1)
    prod = (r[:, :, None] * r[:, None, :])[:, iu[0], iu[1]]
    cov = S.rolling_mean(prod, window) - m[:, iu[0]] * m[:, iu[1]]
    den = sd[:, iu[0]] * sd[:, iu[1]]
    corr = np.divide(cov, den, out=np.full_like(cov, np.nan), where=den > 0)
    return np.nanmean(np.where(np.isfinite(corr), corr, np.nan), axis=1) if n > 1 else np.full(T, np.nan)


def _pair_corr(x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    xy = np.stack([x, y], axis=1)
    return _rolling_corr_pairs(xy, window)


def market_state(close: np.ndarray, account: Account) -> np.ndarray:
    """§3.1: breadth, dispersion, mean pairwise corr, EW-portfolio vol, its 21d change, stock–bond corr."""
    close = np.asarray(close, dtype=float)
    r = S.daily_returns(close)
    slow = S.rolling_mean(close, 200)
    above = np.where(np.isfinite(slow), (close > slow).astype(float), np.nan)
    breadth = np.nanmean(above, axis=1) if np.isfinite(above).any() else np.full(close.shape[0], np.nan)
    ret63 = close / S.shift(close, 63) - 1.0
    dispersion = np.nanstd(ret63, axis=1)
    corr = _rolling_corr_pairs(r, CORR_WINDOW)
    ew = np.nanmean(r, axis=1)
    pvol = S.rolling_std(ew[:, None], CORR_WINDOW)[:, 0] * np.sqrt(S.TRADING_DAYS)
    dvol = pvol - S.shift(pvol[:, None], 21)[:, 0]
    kinds = [account.asset_class[s] for s in account.symbols]
    eq = kinds.index("equity")
    bd = kinds.index("bond")
    sb = _pair_corr(r[:, eq], r[:, bd], CORR_WINDOW)
    with np.errstate(all="ignore"):
        raw = np.stack([breadth, dispersion, corr, pvol, dvol, sb], axis=1)
    z = S.rolling_zscore(raw, ZSCORE_WINDOW)
    return np.nan_to_num(z, nan=0.0)


def world_features(
    close_adj: np.ndarray,
    account: Account,
    valuation: np.ndarray | None = None,
    adv: np.ndarray | None = None,
    spread: np.ndarray | None = None,
    min_adv: float = 0.0,
    cfg: S.ScorerConfig = S.ScorerConfig(),
) -> WorldFeatures:
    close_adj = np.asarray(close_adj, dtype=float)
    f = S.compute_factors(close_adj, account, valuation, cfg)
    ranks = np.moveaxis(f.ranks, 0, -1)  # (T, n, 4)
    raw = np.stack([f.raw[k] for k in S.FACTORS], axis=-1)  # (T, n, 4)
    T, n = close_adj.shape
    z = np.stack([S.rolling_zscore(raw[:, :, k], ZSCORE_WINDOW) for k in range(4)], axis=-1)
    sigma = S.rolling_std(S.daily_returns(close_adj), cfg.vol_window)
    eligible = np.isfinite(ranks).all(axis=-1) & np.isfinite(sigma) & (sigma > 0)
    asset = np.concatenate([np.nan_to_num(ranks, nan=0.5), np.nan_to_num(z, nan=0.0)], axis=-1)
    if adv is None:
        reduce_only = np.zeros((T, n), dtype=bool)
    else:
        reduce_only = C.reduce_only_mask(adv, spread, min_adv=min_adv)
    return WorldFeatures(
        asset=asset,
        eligible=eligible,
        market=market_state(close_adj, account),
        sigma=np.where(eligible, sigma, 1.0),
        tradable=(~reduce_only).astype(float),
        reduce_only=reduce_only,
        value_enabled=f.value_enabled,
    )
