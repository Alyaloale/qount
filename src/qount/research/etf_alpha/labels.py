"""Executable next-open cumulative total-return labels and their exact intervals."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qount.research.etf_trader.scorer import daily_returns, rolling_mean

from .data import Panel, total_return_index

HORIZONS = (5, 20, 60)


@dataclass(frozen=True)
class Labels:
    values: dict[str, np.ndarray]
    available: dict[str, np.ndarray]
    start_rows: np.ndarray
    end_rows: dict[int, np.ndarray]


def build_labels(panel: Panel, horizons: tuple[int, ...] = HORIZONS) -> Labels:
    if not horizons or any(h <= 0 for h in horizons):
        raise ValueError("positive horizons required")
    T, n = panel.open.shape
    opened = total_return_index(panel.open, panel.dividends, panel.splits)
    close_tr = total_return_index(panel.close, panel.dividends, panel.splits)
    valid = np.isfinite(panel.open) & (panel.open > 0)
    bad_prefix = np.vstack([np.zeros((1, n), int), np.cumsum(~valid, axis=0)])
    future_daily = daily_returns(opened)
    r = daily_returns(close_tr)
    cash_daily = daily_returns(panel.cash_close[:, None])
    excess = r - cash_daily
    spy = excess[:, panel.symbols.index("SPY")][:, None]
    covariance = rolling_mean(excess * spy, 252) - rolling_mean(excess, 252) * rolling_mean(spy, 252)
    variance = rolling_mean(spy * spy, 252) - rolling_mean(spy, 252) ** 2
    beta = np.divide(covariance, variance, out=np.full_like(covariance, np.nan), where=variance > 1e-16)
    values, masks, ends = {}, {}, {}
    if 20 in horizons:
        values["sigma20"] = np.full((T, n), np.nan)
    starts = np.arange(T) + 1
    starts[starts >= T] = -1
    for h in horizons:
        end = np.arange(T) + h + 1
        end[end >= T] = -1
        ends[h] = end
        y, cash_y = np.full((T, n), np.nan), np.full(T, np.nan)
        for t in range(max(0, T - h - 1)):
            a, b = t + 1, t + h + 1
            continuous = (bad_prefix[b + 1] - bad_prefix[a]) == 0
            y[t] = np.where(continuous, opened[b] / opened[a] - 1.0, np.nan)
            if np.isfinite(panel.cash_open[a:b + 1]).all():
                cash_y[t] = panel.cash_open[b] / panel.cash_open[a] - 1.0
            if h == 20:
                vol = np.std(future_daily[a + 1:b + 1], axis=0, ddof=1) * np.sqrt(252)
                values.setdefault("sigma20", np.full((T, n), np.nan))[t] = np.where(continuous, vol, np.nan)
        values[f"mu{h}"] = y
        values[f"cash{h}"] = np.broadcast_to(cash_y[:, None], y.shape).copy()
        values[f"excess{h}"] = y - cash_y[:, None]
        benchmark = values[f"excess{h}"][:, panel.symbols.index("SPY")][:, None]
        values[f"residual{h}"] = values[f"excess{h}"] - beta * benchmark
    if "mu20" in values:
        values["p_up"] = np.where(np.isfinite(values["mu20"]), (values["mu20"] > 0).astype(float), np.nan)
        values["q10"] = values["mu20"].copy()  # pinball target; not a realised sample quantile
    masks = {k: np.isfinite(v) for k, v in values.items()}
    return Labels(values, masks, starts, ends)


def opening_label_oracle(panel: Panel, asset: int, start: int, end: int) -> float:
    """Independent share/cash reconciliation: reinvest ex-date cash at each open.

    Zero cost and fractional shares define a total-return label, not the later
    constrained strategy. Entry at an ex-date open has no prior entitlement.
    """
    if not 0 <= start < end < len(panel.dates):
        raise ValueError("invalid oracle interval")
    shares = 1.0 / panel.open[start, asset]
    for u in range(start + 1, end + 1):
        shares *= panel.splits[u, asset]
        cash = shares * panel.dividends[u, asset]
        shares += cash / panel.open[u, asset]
    return float(shares * panel.open[end, asset] - 1.0)
