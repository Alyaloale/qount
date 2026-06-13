"""X4 top-level portfolio combiner: allocate across strategy equity curves (线 D §13).

The bake-off runs each strategy on its own $100k. A *portfolio* allocates one capital base across
them and rebalances — equal-weight or inverse-volatility (a simple risk-parity), using only trailing
data (no look-ahead). Combining low-correlation sleeves is the textbook way to lift portfolio Sharpe
and crush max-drawdown below any single sleeve's. Pure (no IO), reusing ``rv.stats`` for returns.
"""

from __future__ import annotations

import math
from collections import deque

from qount.rv.stats import returns_from_curve


def correlation(a: list[float], b: list[float]) -> float:
    """Pearson correlation of two equal-length return series (0 if undefined)."""

    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return cov / (va ** 0.5 * vb ** 0.5)


def _std(xs) -> float:
    xs = list(xs)
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def combine(
    curves: dict[str, list[float]],
    *,
    scheme: str = "equal",
    vol_lookback: int = 30,
    initial_capital: float = 100_000.0,
) -> list[float]:
    """Combine aligned strategy equity ``curves`` into one portfolio equity curve.

    ``scheme='equal'`` rebalances to equal weights each bar; ``scheme='inverse_vol'`` weights each
    sleeve by the inverse of its trailing ``vol_lookback``-bar return volatility (simple risk parity),
    falling back to equal weights during warm-up. Weights at bar ``t`` use only returns *before* ``t``
    (no look-ahead). All input curves must be the same length.
    """

    names = list(curves)
    if not names:
        raise ValueError("need at least one curve")
    length = len(curves[names[0]])
    if any(len(curves[n]) != length for n in names):
        raise ValueError("all curves must be the same length")

    rets = {n: returns_from_curve(curves[n]) for n in names}
    t_steps = length - 1
    windows = {n: deque(maxlen=vol_lookback) for n in names}
    port = [initial_capital]

    for t in range(t_steps):
        if scheme == "inverse_vol" and all(len(windows[n]) >= 2 for n in names):
            invs = {n: (1.0 / _std(windows[n]) if _std(windows[n]) > 0 else 0.0) for n in names}
            s = sum(invs.values())
            w = {n: (invs[n] / s if s > 0 else 1.0 / len(names)) for n in names}
        else:
            w = {n: 1.0 / len(names) for n in names}
        r_p = sum(w[n] * rets[n][t] for n in names)
        port.append(port[-1] * (1.0 + r_p))
        for n in names:
            windows[n].append(rets[n][t])
    return port


def sharpe_of(curve: list[float], *, periods_per_year: float = 365.0) -> float:
    """Annualized Sharpe of an equity curve (reuses ``rv.stats``)."""

    from qount.rv.stats import sharpe as _sharpe
    r = returns_from_curve(curve)
    return _sharpe(r, periods_per_year=periods_per_year) if len(r) >= 2 else 0.0
