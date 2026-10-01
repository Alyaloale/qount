"""Regime-conditional stationary block bootstrap (design §7.4).

Blocks are drawn synchronously across all assets (keeping cross-sectional correlation) with
geometric lengths of mean ``mean_block`` (21–126 per the design).  With ``regimes`` given,
each new block starts at a source day whose regime equals the regime of the output path at
that position, so a regime path (e.g. from the structural HMM or a resampled calibration
path) conditions which history is replayed.  Output is a log-return panel; callers rebuild
prices, volume and spreads from the same drawn source indices.
"""

from __future__ import annotations

import numpy as np


class BootstrapError(ValueError):
    pass


def draw_indices(
    n_source: int,
    length: int,
    mean_block: float,
    rng: np.random.Generator,
    source_regimes: np.ndarray | None = None,
    target_regimes: np.ndarray | None = None,
) -> np.ndarray:
    """Source row index for each of ``length`` output rows."""
    if n_source < 2 or length < 1 or mean_block < 1:
        raise BootstrapError("need ≥2 source rows, length ≥1 and mean_block ≥1")
    p_new = 1.0 / mean_block
    pools = None
    if target_regimes is not None:
        if source_regimes is None or len(source_regimes) != n_source or len(target_regimes) != length:
            raise BootstrapError("regime arrays must match source and output lengths")
        src = np.asarray(source_regimes)
        pools = {r: np.flatnonzero(src[:-1] == r) for r in np.unique(target_regimes)}
        empty = [r for r, pool in pools.items() if pool.size == 0]
        if empty:
            raise BootstrapError(f"no source days for regimes {empty}")

    out = np.empty(length, dtype=int)
    cur = -1
    for k in range(length):
        want = None if target_regimes is None else target_regimes[k]
        restart = (
            cur < 0
            or cur + 1 >= n_source
            or rng.random() < p_new
            or (want is not None and source_regimes[cur + 1] != want)
        )
        if restart:
            cur = int(rng.choice(pools[want])) if pools is not None else int(rng.integers(n_source))
        else:
            cur += 1
        out[k] = cur
    return out


def bootstrap_paths(
    log_returns: np.ndarray,
    length: int,
    n_paths: int,
    mean_block: float,
    rng: np.random.Generator,
    source_regimes: np.ndarray | None = None,
    target_regimes: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(paths (n_paths, length, n), indices (n_paths, length))``.

    Rows with any NaN in the source are excluded (synchronous blocks need a full cross-section).
    """
    x = np.asarray(log_returns, dtype=float)
    keep = np.isfinite(x).all(axis=1)
    x = x[keep]
    regimes = None if source_regimes is None else np.asarray(source_regimes)[keep]
    idx = np.stack(
        [draw_indices(x.shape[0], length, mean_block, rng, regimes, target_regimes) for _ in range(n_paths)]
    )
    return x[idx], idx
