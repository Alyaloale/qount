"""Exact date-balanced Ridge by SVD; no iterative neural optimizer."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RidgeModel:
    coefficients: np.ndarray
    intercept: float

    def predict(self, x):
        return np.asarray(x) @ self.coefficients + self.intercept


def fit_ridge(x: np.ndarray, y: np.ndarray, mask: np.ndarray, penalty=0.01) -> RidgeModel:
    """Minimize mean_date(mean_available_asset(error**2)) + penalty*||beta||²."""
    if x.ndim != 3 or y.shape != x.shape[:2] or mask.shape != y.shape or mask.dtype != np.bool_:
        raise ValueError("date/asset Ridge inputs disagree")
    if not np.isfinite(penalty) or penalty <= 0 or not mask.any(axis=1).all():
        raise ValueError("positive penalty and at least one target per date required")
    if not np.isfinite(x[mask]).all() or not np.isfinite(y[mask]).all():
        raise ValueError("Ridge observations must be finite")
    weights = (mask / mask.sum(axis=1, keepdims=True) / len(x))[mask]
    xx, yy = np.asarray(x[mask], dtype=np.float64), np.asarray(y[mask], dtype=np.float64)
    xm, ym = weights @ xx, float(weights @ yy)
    a = (xx - xm) * np.sqrt(weights[:, None])
    b = (yy - ym) * np.sqrt(weights)
    u, singular, vt = np.linalg.svd(a, full_matrices=False)
    coefficients = vt.T @ ((singular / (singular ** 2 + penalty)) * (u.T @ b))
    return RidgeModel(coefficients, float(ym - xm @ coefficients))


def block_permutation(length: int, *, block=60, seed=1000) -> np.ndarray:
    if length < 2 * block or block < 1:
        raise ValueError("at least two train-only blocks required")
    blocks = [np.arange(i, min(length, i + block)) for i in range(0, length, block)]
    return np.concatenate([blocks[i] for i in np.random.default_rng(seed).permutation(len(blocks))])
