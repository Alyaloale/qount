"""Shared research statistics: Sharpe, DSR and PBO/CSCV (pure, no IO).

S3 of ``docs/archive/legacy/x4-rv/rv-c-plan.md``: the breadth panel tried 10 COIN-M symbols and 4 passed the L=3
gate. Is "4 of 10 pass" consistent with luck (杀手3, multiple testing)? Two standard tools
(Bailey & López de Prado):

* **DSR — Deflated Sharpe Ratio** (:func:`deflated_sharpe_ratio`): deflates an observed Sharpe
  by the *expected maximum* Sharpe one would see from ``N`` independent trials under the null of
  zero true skill, using the cross-trial Sharpe variance. ``DSR`` is the probability the true
  (annual-frequency-agnostic, per-observation) Sharpe exceeds that deflated benchmark. ``DSR >
  0.95`` ⇒ the edge survives the multiple-testing correction at 5%.

* **PBO — Probability of Backtest Overfitting** (:func:`pbo_cscv`) via Combinatorially Symmetric
  Cross-Validation: treat the ``N`` symbols as configs, split time into ``S`` blocks, and over all
  C(S, S/2) train/test partitions check whether the in-sample-best config stays above the
  out-of-sample median. ``PBO`` = fraction of partitions where it does NOT. High PBO ⇒ "pick the
  best symbol" is overfit/luck; low PBO ⇒ the selection generalizes.

Everything is per-observation (daily) and pure-Python (no numpy) so it is offline-testable.
The DSR formula uses the *non-annualized* Sharpe and the return skew/kurtosis (normal kurt = 3).
"""

from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist
from typing import Sequence

_N01 = NormalDist(0.0, 1.0)
_EULER = 0.5772156649015329  # Euler–Mascheroni γ


def _moments(xs: Sequence[float]) -> tuple[float, float, float, float]:
    """Return (mean, std_ddof1, skew γ3, kurtosis γ4 with normal=3) of ``xs``."""

    n = len(xs)
    if n < 2:
        raise ValueError("need >= 2 observations")
    mean = sum(xs) / n
    m2 = sum((x - mean) ** 2 for x in xs) / n
    if m2 <= 0.0:
        return mean, 0.0, 0.0, 3.0
    m3 = sum((x - mean) ** 3 for x in xs) / n
    m4 = sum((x - mean) ** 4 for x in xs) / n
    std = math.sqrt(m2 * n / (n - 1))      # sample std (ddof=1)
    skew = m3 / m2 ** 1.5
    kurt = m4 / m2 ** 2                     # non-excess (normal = 3)
    return mean, std, skew, kurt


def sharpe(returns: Sequence[float], *, periods_per_year: float | None = None) -> float:
    """Per-observation Sharpe ``mean/std`` (ddof=1); annualized by ``√periods_per_year`` if given."""

    mean, std, _, _ = _moments(returns)
    if std == 0.0:
        return 0.0
    sr = mean / std
    return sr * math.sqrt(periods_per_year) if periods_per_year else sr


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """Expected maximum per-observation Sharpe under the null (Bailey–LdP), ``SR0``.

    ``SR0 = √V · [(1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e))]`` with ``V`` the cross-trial Sharpe
    variance and ``N`` the number of trials. This is the benchmark a real edge must clear.
    """

    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if var_sr <= 0.0 or n_trials == 1:
        return 0.0
    z1 = _N01.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _N01.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sr) * ((1.0 - _EULER) * z1 + _EULER * z2)


def deflated_sharpe_ratio(
    sr_observed: float,
    *,
    n_obs: int,
    sr_benchmark: float,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """Deflated Sharpe Ratio = P(true SR > benchmark), per-observation units (Bailey–LdP).

    ``DSR = Φ[ (SR̂ − SR0)·√(n−1) / √(1 − γ3·SR̂ + ((γ4−1)/4)·SR̂²) ]``. With ``SR0`` the
    deflated benchmark from :func:`expected_max_sharpe`, ``n_obs`` the sample length, and the
    return ``skew``/``kurt`` (normal kurt = 3). ``DSR > 0.95`` ⇒ edge survives deflation at 5%.
    """

    if n_obs < 2:
        raise ValueError("n_obs must be >= 2")
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr_observed + (kurt - 1.0) / 4.0 * sr_observed ** 2))
    z = (sr_observed - sr_benchmark) * math.sqrt(n_obs - 1) / denom
    return _N01.cdf(z)


def _block_moments(series: Sequence[float], n_splits: int) -> list[tuple[int, float, float]]:
    """Per-block (n, sum, sumsq) of one config's returns, split into ``n_splits`` contiguous blocks."""

    n = len(series)
    out = []
    for b in range(n_splits):
        lo = b * n // n_splits
        hi = (b + 1) * n // n_splits
        seg = series[lo:hi]
        s = sum(seg)
        out.append((len(seg), s, sum(x * x for x in seg)))
    return out


def _agg_sharpe(blocks: Sequence[tuple[int, float, float]], idxs: Sequence[int]) -> float:
    n = sum(blocks[i][0] for i in idxs)
    if n < 2:
        return 0.0
    s = sum(blocks[i][1] for i in idxs)
    ss = sum(blocks[i][2] for i in idxs)
    mean = s / n
    var = ss / n - mean * mean
    if var <= 0.0:
        return 0.0
    return mean / math.sqrt(var)


def pbo_cscv(columns: Sequence[Sequence[float]], *, n_splits: int = 10) -> float:
    """Probability of Backtest Overfitting via CSCV over ``columns`` (one aligned series per config).

    Splits the common timeline into ``n_splits`` (even) contiguous blocks; over every way to pick
    ``n_splits/2`` blocks as in-sample, picks the config with the best IS Sharpe and measures its
    out-of-sample rank. ``PBO`` = fraction of partitions where the IS-best lands below the OOS
    median (logit < 0). Returns ``PBO ∈ [0, 1]``; lower = the selection generalizes.
    """

    ncfg = len(columns)
    if ncfg < 2:
        raise ValueError("need >= 2 configs")
    if n_splits % 2 != 0:
        raise ValueError("n_splits must be even")
    T = len(columns[0])
    if any(len(c) != T for c in columns):
        raise ValueError("all config series must be the same length (aligned)")

    blocks = [_block_moments(c, n_splits) for c in columns]
    all_b = range(n_splits)
    overfit = 0
    total = 0
    for is_set in combinations(all_b, n_splits // 2):
        oos_set = [b for b in all_b if b not in is_set]
        is_sr = [_agg_sharpe(blocks[c], is_set) for c in range(ncfg)]
        best = max(range(ncfg), key=lambda c: is_sr[c])
        oos_sr = [_agg_sharpe(blocks[c], oos_set) for c in range(ncfg)]
        # OOS rank of the IS-best (1 = worst .. ncfg = best); relative rank omega in (0,1)
        rank = 1 + sum(1 for c in range(ncfg) if oos_sr[c] < oos_sr[best])
        omega = rank / (ncfg + 1)
        logit = math.log(omega / (1.0 - omega))
        if logit <= 0.0:
            overfit += 1
        total += 1
    return overfit / total if total else 0.0


def returns_from_curve(curve: Sequence[float]) -> list[float]:
    """Per-bar simple returns from an equity curve (drops bars at/under zero equity)."""

    out = []
    for prev, cur in zip(curve, curve[1:]):
        if prev > 0.0:
            out.append(cur / prev - 1.0)
    return out
