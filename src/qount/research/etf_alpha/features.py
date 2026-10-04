"""38 causal asset features, explicit masks and trailing-only normalization."""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from qount.research.etf_trader import scorer as S
from qount.research.etf_trader.universe import US_ACCOUNT

from .data import Panel, total_return_index

NORMALIZATION_WINDOW = 252
NORMALIZATION_CLIP = 5.0


@dataclass(frozen=True)
class Features:
    names: tuple[str, ...]
    raw: np.ndarray
    normalized: np.ndarray
    available: np.ndarray
    market_names: tuple[str, ...]
    market_raw: np.ndarray
    market_normalized: np.ndarray
    market_available: np.ndarray
    covariance_annual: np.ndarray
    schema: dict


def trailing_normalize(x: np.ndarray, window: int = NORMALIZATION_WINDOW) -> tuple[np.ndarray, np.ndarray]:
    """Current close included; constant complete windows map to known zero."""
    mean, sd = S.rolling_mean(x, window), S.rolling_std(x, window)
    ready = np.isfinite(x) & np.isfinite(mean) & np.isfinite(sd)
    z = np.divide(x - mean, sd, out=np.zeros_like(x), where=sd > 1e-14)
    z = np.where(ready, np.clip(z, -NORMALIZATION_CLIP, NORMALIZATION_CLIP), np.nan)
    return z, ready


def _window_stat(x: np.ndarray, window: int, function) -> np.ndarray:
    out = np.full_like(x, np.nan)
    if len(x) >= window:
        w = sliding_window_view(x, window, axis=0)
        valid = np.isfinite(w).all(axis=-1)
        value = function(np.where(valid[..., None], w, 0.0))
        out[window - 1:] = np.where(valid, value, np.nan)
    return out


def trailing_covariance(returns: np.ndarray, window: int = 60, shrinkage: float = 0.2) -> np.ndarray:
    cov = _sample_covariance(returns, window)
    diagonal = np.eye(returns.shape[1])[None] * cov
    return ((1 - shrinkage) * cov + shrinkage * diagonal) * 252


def _sample_covariance(returns: np.ndarray, window: int) -> np.ndarray:
    """Trailing second moments in one batch; incomplete windows remain missing."""
    if window < 2:
        raise ValueError("sample covariance requires at least two sessions")
    r = np.asarray(returns, dtype=float)
    mean = S.rolling_mean(r, window)
    products = S.rolling_mean(r[:, :, None] * r[:, None, :], window)
    cov = (products - mean[:, :, None] * mean[:, None, :]) * window / (window - 1)
    complete = np.isfinite(mean).all(axis=1)
    return np.where(complete[:, None, None], cov, np.nan)


def market_features(returns: np.ndarray, close_tr: np.ndarray, symbols: tuple[str, ...]):
    columns, names = [], []
    pairs = (("SPY", "TLT"), ("SPY", "GLD"), ("QQQ", "IWM"))
    n = len(symbols)
    for window in (20, 60, 120):
        vals = np.full((len(returns), 5), np.nan)
        cov = _sample_covariance(returns, window)
        sd = np.sqrt(np.maximum(np.diagonal(cov, axis1=1, axis2=2), 0))
        # Cumulative second moments can leave roundoff variance for constant nonzero returns.
        varying = S.rolling_max(returns, window) + S.rolling_max(-returns, window) > 0
        ready = np.isfinite(cov).all(axis=(1, 2)) & (sd > 1e-14).all(axis=1) & varying.all(axis=1)
        corr = cov[ready] / (sd[ready, :, None] * sd[ready, None, :])
        corr = np.clip(corr, -1, 1)
        upper = np.triu_indices(n, 1)
        vals[ready, 0] = corr[:, upper[0], upper[1]].mean(axis=1)
        for k, (a, b) in enumerate(pairs, 1):
            if a in symbols and b in symbols:
                vals[ready, k] = corr[:, symbols.index(a), symbols.index(b)]
        vals[ready, 4] = np.linalg.eigvalsh(corr)[:, -1] / n
        for k, name in enumerate(("mean_correlation", "SPY_TLT", "SPY_GLD", "QQQ_IWM", "pc1_correlation_share")):
            columns.append(vals[:, k])
            names.append(f"{name}{window}")
    dispersion = np.std(returns, axis=1, ddof=1)
    ma = S.rolling_mean(close_tr, 200)
    breadth = np.where(np.isfinite(ma).all(axis=1), np.mean(close_tr > ma, axis=1), np.nan)
    return tuple(names + ["return_dispersion", "trend_breadth200"]), np.column_stack(columns + [dispersion, breadth])


def build_features(panel: Panel) -> Features:
    close = total_return_index(panel.close, panel.dividends, panel.splits)
    r = S.daily_returns(close)
    raw_fields, specifications = {}, []

    def add(name: str, value: np.ndarray, formula: str, window: int, unit: str) -> None:
        raw_fields[name] = value
        specifications.append({"name": name, "formula": formula, "lookback_sessions": window,
                               "unit": unit, "availability": "after close t, observations <= t",
                               "missing": "NaN with available=false; no implicit neutral imputation"})

    valid = np.isfinite(panel.close).astype(float)
    for h in (1, 5, 10, 20, 60, 120, 252):
        value = close / S.shift(close, h) - 1
        value = np.where(S.rolling_mean(valid, h + 1) == 1, value, np.nan)
        add(f"return{h}", value, "TR_close[t]/TR_close[t-h]-1", h + 1, "cumulative fraction")
    for h in (20, 60, 120):
        sd = S.rolling_std(r, h) * np.sqrt(h)
        value = np.divide(raw_fields[f"return{h}"], sd, out=np.full_like(close, np.nan), where=sd > 1e-14)
        add(f"vol_adjusted_momentum{h}", value, "cumulative return_h/(daily_sd_h*sqrt(h))", h + 1, "ratio")
    vol20 = S.rolling_std(r, 20)
    for h in (20, 60, 120, 200):
        ma = S.rolling_mean(close, h)
        add(f"ma_distance{h}", close / ma - 1, "TR_close/mean_h(TR_close)-1", h, "fraction")
        base = S.shift(ma, 20)
        denominator = base * vol20 * np.sqrt(20)
        slope = np.divide(ma - base, denominator, out=np.full_like(close, np.nan), where=denominator > 1e-14)
        add(f"ma_slope{h}", slope, "(MA_h[t]-MA_h[t-20])/(MA_h[t-20]*sd20*sqrt(20))", h + 20, "ratio")
    for h in (60, 252):
        lo = _window_stat(close, h, lambda w: np.min(w, axis=-1))
        hi = _window_stat(close, h, lambda w: np.max(w, axis=-1))
        value = np.divide(close - lo, hi - lo, out=np.full_like(close, 0.5), where=hi > lo)
        add(f"range_percentile{h}", np.where(np.isfinite(lo), value, np.nan),
            "(TR_close-min_h)/(max_h-min_h); constant range=0.5", h, "fraction")
    for h in (10, 20, 60):
        add(f"rv{h}", S.rolling_std(r, h) * np.sqrt(252), "sample daily sd_h*sqrt(252)", h + 1, "annual volatility")
    for h in (20, 60):
        add(f"downside_vol{h}", np.sqrt(S.rolling_mean(np.minimum(r, 0) ** 2, h) * 252),
            "sqrt(mean_h(min(r,0)^2)*252)", h + 1, "annual volatility")
    add("drawdown252", 1 - close / S.rolling_max(close, 252), "1-TR_close/max_252(TR_close)", 252, "positive loss fraction")
    for h in (60, 252):
        value = _window_stat(close, h, lambda w: np.max(1 - np.divide(w, np.maximum.accumulate(w, axis=-1),
                             out=np.ones_like(w), where=np.maximum.accumulate(w, axis=-1) > 0), axis=-1))
        add(f"max_drawdown{h}", value, "max within-window drawdown from that window's running peak", h, "positive loss fraction")

    def moment(w, power):
        centered = w - w.mean(axis=-1, keepdims=True)
        sd = np.sqrt(np.mean(centered ** 2, axis=-1))
        value = np.divide(np.mean(centered ** power, axis=-1), sd ** power,
                          out=np.full(sd.shape, np.nan), where=sd > 1e-14)
        return value - (3 if power == 4 else 0)

    add("skew60", _window_stat(r, 60, lambda w: moment(w, 3)), "population standardized third moment", 61, "ratio")
    add("kurtosis60", _window_stat(r, 60, lambda w: moment(w, 4)), "population fourth moment minus 3", 61, "excess kurtosis")
    add("var95_120", _window_stat(r, 120, lambda w: np.maximum(0, -np.quantile(w, 0.05, axis=-1))),
        "max(0,-5% daily quantile), linear interpolation", 121, "daily positive loss fraction")

    def cvar(w):
        tail = w <= np.quantile(w, 0.05, axis=-1)[..., None]
        return np.maximum(0, -np.sum(np.where(tail, w, 0), axis=-1) / np.maximum(tail.sum(axis=-1), 1))

    add("cvar95_120", _window_stat(r, 120, cvar), "max(0,-mean daily returns <= VaR quantile)", 121, "daily positive loss fraction")
    vm, vs = S.rolling_mean(panel.volume, 20), S.rolling_std(panel.volume, 20)
    vz = np.divide(panel.volume - vm, vs, out=np.zeros_like(panel.volume), where=vs > 1e-14)
    add("volume_z20", np.where(np.isfinite(vm), vz, np.nan), "(volume-mean20)/sd20; known constant=0", 20, "ratio")
    dollar_volume = panel.volume * panel.close
    add("log_dollar_adv20", np.log(S.rolling_mean(dollar_volume, 20)), "log(mean20(raw_close*volume))", 20, "log USD")
    add("amihud20", S.rolling_mean(np.abs(r) / dollar_volume, 20), "mean20(abs(total_return_daily)/(raw_close*volume))", 21, "1/USD")
    account = replace(US_ACCOUNT, symbols=panel.symbols)
    factors = S.compute_factors(close, account)
    for index, name in ((0, "M"), (1, "Trend_orth_M"), (3, "Risk")):
        add(name, factors.ranks[index], f"existing scorer {name} cross-sectional score; Value excluded", 1008, "rank fraction")
    names = tuple(raw_fields)
    raw = np.stack(list(raw_fields.values()), axis=-1)
    if len(names) != 38:
        raise AssertionError("feature schema must have exactly 38 numeric fields")
    normalized, available = trailing_normalize(raw)
    market_names, market = market_features(r, close, panel.symbols)
    market_z, market_available = trailing_normalize(market)
    schema = {"schema": "etf-p3-features-v1", "fields": specifications, "count": len(names),
              "market_fields": list(market_names), "value_enabled": False,
              "normalization": {"method": "trailing per-asset sample z-score", "window": NORMALIZATION_WINDOW,
                                "clip": NORMALIZATION_CLIP, "full_history_fit": False,
                                "constant_window": "known zero", "missing_mask_is_separate": True},
              "raw_price_basis": "event-based causal TR_close; nominal prices only for dollar volume",
              "tail_sample_warning": "VaR/CVaR120 typically use only six lower-tail daily observations"}
    return Features(names, raw, normalized, available, market_names, market, market_z, market_available,
                    trailing_covariance(r), schema)
