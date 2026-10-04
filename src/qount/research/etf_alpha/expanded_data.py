"""Causal representation and joint past-only block augmentation for P3 v2.

Bootstrap paths are augmentation, not new independent market observations.
Neither source indices nor any outer/validation labels enter model inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from qount.research.etf_trader.scorer import daily_returns, percentile_rank

from .data import Panel, total_return_index

LEVELS = (("return5", .05), ("return20", .1), ("return60", .2),
          ("rv20", .2), ("rv60", .2), ("ma_distance200", .2),
          ("drawdown252", .2), ("M", .5))
ASSET_DIM = 84


def representation(raw, normalized, names):
    """38 trailing z scores + 38 current cross-sectional ranks + 8 fixed units."""
    if raw.shape != normalized.shape or raw.shape[-1] != 38 or len(names) != 38:
        raise ValueError("frozen 38-feature schema required")
    ranked = np.moveaxis(percentile_rank(np.moveaxis(raw, -1, -2)), -2, -1) * 2 - 1
    levels = []
    for name, unit in LEVELS:
        value = raw[..., names.index(name)]
        levels.append((value - .5) / unit if name == "M" else value / unit)
    values = np.concatenate((normalized, ranked, np.clip(np.stack(levels, -1), -8, 8)), -1)
    return values.astype(np.float32)


def load_panel(root: Path) -> Panel:
    with np.load(root / "panel.npz", allow_pickle=False) as p:
        return Panel(tuple(p["dates"].tolist()), tuple(p["symbols"].tolist()),
                     **{k: p[k].copy() for k in ("open", "high", "low", "close", "volume",
                                                "dividends", "splits", "cash_open", "cash_close")}, audit={})


@dataclass(frozen=True)
class BootstrapSpec:
    worlds_per_fold: int = 1024
    worlds_per_shard: int = 8
    warmup_sessions: int = 1280
    training_sessions: int = 1260
    block_sessions: int = 252
    seed: int = 20261003

    def __post_init__(self):
        if self.worlds_per_fold < 1 or self.worlds_per_shard < 1:
            raise ValueError("positive world/shard counts required")
        if self.warmup_sessions < 1280 or self.training_sessions < 1 or self.block_sessions < 22:
            raise ValueError("full causal warmup and blocks exceeding the label interval required")

    @property
    def sessions(self):
        return self.warmup_sessions + self.training_sessions + 22

    @property
    def estimated_bytes_per_fold(self):
        # Assets, current market, mu20, mask and source indices; exclude small receipts.
        return self.worlds_per_fold * (self.training_sessions * (9 * ASSET_DIM * 4 + 17 * 4 + 9 * 5)
                                       + self.sessions * 4)


def block_indices(length, lower, upper, block, seed):
    """Half-open source range. All assets/cash use the exact same sampled dates."""
    if not 1 <= lower < upper or upper - lower < block or length < 1:
        raise ValueError("a complete past-only source block is required")
    rng = np.random.default_rng(seed)
    starts = rng.integers(lower, upper - block + 1, int(np.ceil(length / block)))
    return (starts[:, None] + np.arange(block)).ravel()[:length].astype(np.int32)


def label_continuity(indices, rows, horizon=20):
    """Exclude a next-open interval crossing a sampled block join or path tail."""
    rows = np.asarray(rows)
    valid = rows + horizon + 1 < len(indices)
    safe = rows[valid]
    if len(safe):
        steps = safe[:, None] + np.arange(1, horizon + 2)
        valid[valid] = (np.diff(indices[steps], axis=1) == 1).all(axis=1)
    return valid


def bootstrap_panel(panel: Panel, indices: np.ndarray, *, source_returns=None) -> Panel:
    """Joint TR returns + sampled intraday ratios/dollar liquidity.

    Events are embedded in TR returns; synthetic distributions=0 and splits=1.
    This approximation is restricted to supervised pretraining, never execution.
    """
    if source_returns is None:
        tr = total_return_index(panel.close, panel.dividends, panel.splits)
        source_returns = daily_returns(tr), daily_returns(panel.cash_close[:, None])[:, 0]
    r = source_returns[0][indices]
    cash_r = source_returns[1][indices]
    close = 100 * np.cumprod(1 + r, axis=0)
    cash = 100 * np.cumprod(1 + cash_r)
    opn = close * (panel.open[indices] / panel.close[indices])
    high = close * (panel.high[indices] / panel.close[indices])
    low = close * (panel.low[indices] / panel.close[indices])
    volume = panel.volume[indices] * panel.close[indices] / close
    days = tuple(np.busday_offset("2000-01-03", np.arange(len(indices))).astype(str))
    return Panel(days, panel.symbols, opn, high, low, close, volume, np.zeros_like(close),
                 np.ones_like(close), cash * panel.cash_open[indices] / panel.cash_close[indices], cash,
                 {"type": "past_only_joint_block_bootstrap", "independent_observations": False,
                  "corporate_actions": "embedded_TR_approximation_pretraining_only"})
