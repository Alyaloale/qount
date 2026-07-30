"""CTA-R Phase 1 gate: turn a real-data run into a verdict, not just an equity number.

Runs the trend sim over a small parameter grid, then applies the project's anti-overfit
harness so the output answers "is this a real edge or a search artifact?":

  - Deflated Sharpe Ratio (López de Prado): deflate the grid's best per-period Sharpe by
    the expected maximum under N independent trials. DSR is a probability; low = the best
    cell is indistinguishable from picking the max of N noise draws.
  - PBO via CSCV (Bailey & López de Prado): does the in-sample winner stay above the OOS
    median across all combinatorial IS/OOS splits? High PBO = overfit.
  - Time-fold robustness: contiguous out-of-sample folds of the best config.

The DSR and PBO math here is a **faithful pure-stdlib port** of
``strategy_selection.compute_directional_deflated_sharpe`` / ``compute_directional_pbo``
(which can't be imported here without pulling ccxt). Consolidating both into a shared
``research_stats`` module is a follow-up best done where the full test suite runs (WSL).

Gate thresholds mirror the L1 cross-asset kill-test: annualized Sharpe >= 0.5,
DSR >= 0.95, PBO < 0.5, and a majority of OOS folds positive.
"""

from __future__ import annotations

import itertools
import math
import statistics
from typing import Any

from .cta_sim import SimConfig
from .cta_sim import TRADING_DAYS_PER_YEAR
from .cta_sim import _max_drawdown
from .cta_sim import run_paper_sim


_EULER_MASCHERONI = 0.5772156649015329

GATE_IR_THRESHOLD = 0.5
GATE_DSR_THRESHOLD = 0.95
GATE_PBO_THRESHOLD = 0.5
GATE_FOLD_POSITIVE_FRACTION = 0.6


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std_sample(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def per_period_sharpe(net_daily: list[float]) -> float | None:
    """Un-annualized Sharpe (mean/std) of a daily return series."""

    std = _std_sample(net_daily)
    if std <= 0.0:
        return None
    return _mean(net_daily) / std


def annualized_sharpe(net_daily: list[float]) -> float | None:
    pp = per_period_sharpe(net_daily)
    return pp * math.sqrt(TRADING_DAYS_PER_YEAR) if pp is not None else None


# --------------------------------------------------------------------------------------
# Deflated Sharpe Ratio
# --------------------------------------------------------------------------------------


def deflated_sharpe(per_period_sharpes: list[float], best_period_count: int) -> dict[str, Any] | None:
    """Port of compute_directional_deflated_sharpe over a list of per-period Sharpes."""

    sharpes = [s for s in per_period_sharpes if isinstance(s, (int, float))]
    if len(sharpes) < 2:
        return None
    trial_count = len(sharpes)
    variance = statistics.pvariance(sharpes)
    best_sr = max(sharpes)
    normal = statistics.NormalDist()
    if variance <= 0.0:
        expected_max = 0.0
    else:
        expected_max = math.sqrt(variance) * (
            (1.0 - _EULER_MASCHERONI) * normal.inv_cdf(1.0 - 1.0 / trial_count)
            + _EULER_MASCHERONI * normal.inv_cdf(1.0 - 1.0 / (trial_count * math.e))
        )
    deflated = None
    if best_period_count > 1:
        deflated = normal.cdf((best_sr - expected_max) * math.sqrt(best_period_count - 1))
    return {
        "trial_count": trial_count,
        "best_per_period_sharpe": best_sr,
        "best_period_count": best_period_count,
        "trial_per_period_sharpe_variance": variance,
        "expected_max_per_period_sharpe": expected_max,
        "deflated_sharpe_ratio": deflated,
        "assumes_normal_returns": True,
    }


# --------------------------------------------------------------------------------------
# PBO via CSCV (single common time axis -- all cta configs share the daily index)
# --------------------------------------------------------------------------------------


def _block_sharpe(stats: list[tuple[float, float, int]], block_indices: tuple[int, ...]) -> float | None:
    total_sum = 0.0
    total_sq = 0.0
    total_n = 0
    for index in block_indices:
        block_sum, block_sq, block_n = stats[index]
        total_sum += block_sum
        total_sq += block_sq
        total_n += block_n
    if total_n < 2:
        return None
    mean = total_sum / total_n
    variance = (total_sq - total_n * mean * mean) / (total_n - 1)
    if variance <= 0.0:
        return None
    return mean / math.sqrt(variance)


def pbo_cscv(returns_by_config: list[dict[int, float]], block_count: int = 10) -> dict[str, Any] | None:
    """Port of _pbo_for_group: CSCV PBO over configs sharing one integer time axis."""

    group = [series for series in returns_by_config if series]
    if len(group) < 2:
        return None
    block_count = block_count if block_count % 2 == 0 else block_count - 1
    if block_count < 2:
        return None
    timestamps = sorted({int(ts) for series in group for ts in series})
    if len(timestamps) < block_count:
        return None
    bounds = [int(len(timestamps) * index / block_count) for index in range(block_count + 1)]
    blocks = [set(timestamps[bounds[index] : bounds[index + 1]]) for index in range(block_count)]

    config_stats: list[list[tuple[float, float, int]]] = []
    for series in group:
        row: list[tuple[float, float, int]] = []
        for block in blocks:
            values = [series[ts] for ts in block if ts in series]
            row.append((sum(values), sum(v * v for v in values), len(values)))
        config_stats.append(row)

    half = block_count // 2
    logits: list[float] = []
    overfit = 0
    for is_blocks in itertools.combinations(range(block_count), half):
        oos_blocks = tuple(i for i in range(block_count) if i not in is_blocks)
        is_scores = [(ci, _block_sharpe(config_stats[ci], is_blocks)) for ci in range(len(group))]
        is_scores = [(ci, s) for ci, s in is_scores if s is not None]
        if not is_scores:
            continue
        best_ci = max(is_scores, key=lambda item: item[1])[0]
        oos_scores = [(ci, _block_sharpe(config_stats[ci], oos_blocks)) for ci in range(len(group))]
        oos_scores = [(ci, s) for ci, s in oos_scores if s is not None]
        best_oos = dict(oos_scores).get(best_ci)
        if best_oos is None or len(oos_scores) < 2:
            continue
        worse = sum(1 for _ci, s in oos_scores if s < best_oos)
        omega = (worse + 0.5) / len(oos_scores)
        omega = min(max(omega, 1e-9), 1.0 - 1e-9)
        logit = math.log(omega / (1.0 - omega))
        logits.append(logit)
        if logit <= 0.0:
            overfit += 1
    if not logits:
        return None
    return {
        "config_count": len(group),
        "block_count": block_count,
        "combination_count": len(logits),
        "pbo": overfit / len(logits),
        "median_logit": statistics.median(logits),
        "mean_logit": _mean(logits),
        "method": "cscv_sharpe",
    }


# --------------------------------------------------------------------------------------
# Time-fold robustness
# --------------------------------------------------------------------------------------


def time_fold_sharpes(net_daily: list[float], n_folds: int) -> list[float | None]:
    """Annualized Sharpe within each contiguous (out-of-sample) fold."""

    if n_folds < 1 or len(net_daily) < n_folds:
        return []
    bounds = [int(len(net_daily) * i / n_folds) for i in range(n_folds + 1)]
    folds: list[float | None] = []
    for i in range(n_folds):
        folds.append(annualized_sharpe(net_daily[bounds[i] : bounds[i + 1]]))
    return folds


# --------------------------------------------------------------------------------------
# Grid + verdict
# --------------------------------------------------------------------------------------


def default_grid(
    *,
    long_only: bool = False,
    max_leverage: float = 3.0,
    max_weight: float = 1.0,
    cost_per_side_pct: float = 0.0002,
) -> list[SimConfig]:
    """A small, deliberately coarse grid -- DSR penalizes every extra trial.

    ``long_only`` / ``max_leverage`` / ``max_weight`` are *modes* applied uniformly to every
    cell (not searched dimensions), so they don't inflate the trial count the DSR deflates
    against.
    """

    grid: list[SimConfig] = []
    for lookbacks in ((21, 63, 126), (63, 126, 252), (126, 252, 504)):
        for vol_lb in (42, 63):
            for rebalance in (5, 21):
                grid.append(
                    SimConfig(
                        lookback_days=lookbacks,
                        vol_lookback_days=vol_lb,
                        rebalance_days=rebalance,
                        max_leverage=max_leverage,
                        long_only=long_only,
                        max_weight=max_weight,
                        cost_per_side_pct=cost_per_side_pct,
                    )
                )
    return grid


def default_carry_grid(
    *,
    long_only: bool = False,
    max_leverage: float = 3.0,
    max_weight: float = 1.0,
    cost_per_side_pct: float = 0.0002,
) -> list[SimConfig]:
    """Coarse carry-sleeve grid (carry smoothing x vol x rebalance), mirroring ``default_grid``.

    The carry signal does not use price lookbacks, so the searched dimension is the carry
    smoothing window instead. ``lookback_days=(1,)`` keeps ``run_paper_sim``'s history guard
    happy while the trend lookbacks stay unused. 12 cells, same as the trend grid, so DSR
    deflates against a comparable trial count.
    """

    grid: list[SimConfig] = []
    for smooth in (1, 5, 10):
        for vol_lb in (42, 63):
            for rebalance in (5, 21):
                grid.append(
                    SimConfig(
                        signal="carry",
                        carry_smooth_days=smooth,
                        lookback_days=(1,),
                        vol_lookback_days=vol_lb,
                        rebalance_days=rebalance,
                        max_leverage=max_leverage,
                        long_only=long_only,
                        max_weight=max_weight,
                        cost_per_side_pct=cost_per_side_pct,
                    )
                )
    return grid


def run_gate_scan(
    prices: dict[str, list[float]],
    grid: list[SimConfig] | None = None,
    *,
    n_folds: int = 5,
    pbo_blocks: int = 10,
    long_only: bool = False,
    max_leverage: float = 3.0,
    max_weight: float = 1.0,
    cost_per_side_pct: float = 0.0002,
    carry: dict[str, list[float | None]] | None = None,
) -> dict[str, Any]:
    """Run the grid, apply DSR/PBO/folds, and return a pass/fail verdict.

    When ``carry`` is given (and no explicit ``grid``), the carry-sleeve grid is used and the
    carry panel is threaded into every cell -- so the same DSR/PBO/fold harness judges the
    carry edge exactly as it judges trend.
    """

    if grid is None:
        grid = (
            default_carry_grid(
                long_only=long_only,
                max_leverage=max_leverage,
                max_weight=max_weight,
                cost_per_side_pct=cost_per_side_pct,
            )
            if carry is not None
            else default_grid(
                long_only=long_only,
                max_leverage=max_leverage,
                max_weight=max_weight,
                cost_per_side_pct=cost_per_side_pct,
            )
        )
    cells: list[dict[str, Any]] = []
    returns_by_config: list[dict[int, float]] = []
    breadth: dict[str, Any] | None = None
    skipped = 0
    for config in grid:
        try:
            res = run_paper_sim(prices, config, carry)
        except ValueError:
            skipped += 1  # not enough history for this config on this panel
            continue
        net = res["net_daily_returns"]
        breadth = breadth or res["effective_breadth"]
        pp = per_period_sharpe(net)
        if pp is None:
            continue
        returns_by_config.append({i: r for i, r in enumerate(net)})
        cells.append(
            {
                "signal": config.signal,
                "carry_smooth_days": config.carry_smooth_days,
                "lookback_days": list(config.lookback_days),
                "vol_lookback_days": config.vol_lookback_days,
                "rebalance_days": config.rebalance_days,
                "annualized_sharpe": res["sharpe"],
                "per_period_sharpe": pp,
                "period_count": len(net),
                "total_return_pct": res["total_return_pct"],
                "max_drawdown": res["max_drawdown"],
            }
        )

    if len(cells) < 2:
        return {
            "version": "cta_eval_v1",
            "decision": "insufficient_configs",
            "evaluated_configs": len(cells),
            "skipped_configs": skipped,
        }

    best = max(cells, key=lambda c: c["per_period_sharpe"])
    dsr = deflated_sharpe([c["per_period_sharpe"] for c in cells], best["period_count"])
    pbo = pbo_cscv(returns_by_config, block_count=pbo_blocks)
    best_idx = cells.index(best)
    folds = time_fold_sharpes(list(returns_by_config[best_idx].values()), n_folds)
    fold_values = [f for f in folds if isinstance(f, (int, float))]
    fold_positive_fraction = (
        sum(1 for f in fold_values if f > 0) / len(fold_values) if fold_values else 0.0
    )

    best_annualized = best["annualized_sharpe"]
    dsr_value = dsr.get("deflated_sharpe_ratio") if dsr else None
    pbo_value = pbo.get("pbo") if pbo else None

    ir_pass = isinstance(best_annualized, (int, float)) and best_annualized >= GATE_IR_THRESHOLD
    net_pass = best["total_return_pct"] > 0.0
    dsr_pass = isinstance(dsr_value, (int, float)) and dsr_value >= GATE_DSR_THRESHOLD
    pbo_pass = isinstance(pbo_value, (int, float)) and pbo_value < GATE_PBO_THRESHOLD
    folds_pass = fold_positive_fraction >= GATE_FOLD_POSITIVE_FRACTION
    passes_gate = bool(ir_pass and net_pass and dsr_pass and pbo_pass and folds_pass)

    return {
        "version": "cta_eval_v1",
        "decision": "passes_gate" if passes_gate else "below_gate",
        "mode": {
            "long_only": long_only,
            "max_leverage": max_leverage,
            "max_weight": max_weight,
            "cost_per_side_pct": cost_per_side_pct,
        },
        "evaluated_configs": len(cells),
        "skipped_configs": skipped,
        "effective_breadth": breadth,
        "best_cell": best,
        "best_annualized_sharpe": best_annualized,
        "deflated_sharpe": dsr,
        "pbo": pbo,
        "time_folds": folds,
        "fold_positive_fraction": fold_positive_fraction,
        "gate": {
            "ir_pass": ir_pass,
            "net_pass": net_pass,
            "dsr_pass": dsr_pass,
            "pbo_pass": pbo_pass,
            "folds_pass": folds_pass,
            "passes_gate": passes_gate,
            "thresholds": {
                "ir": GATE_IR_THRESHOLD,
                "dsr": GATE_DSR_THRESHOLD,
                "pbo": GATE_PBO_THRESHOLD,
                "fold_positive_fraction": GATE_FOLD_POSITIVE_FRACTION,
            },
        },
        "cells": cells,
    }


def render_gate_summary(result: dict[str, Any]) -> str:
    def num(x: Any, d: int = 3) -> str:
        return f"{x:.{d}f}" if isinstance(x, (int, float)) else "n/a"

    if result.get("decision") == "insufficient_configs":
        return (
            f"CTA-R gate scan: insufficient configs "
            f"(evaluated={result.get('evaluated_configs')}, skipped={result.get('skipped_configs')})"
        )
    gate = result["gate"]
    best = result["best_cell"]
    breadth = result.get("effective_breadth") or {}
    checks = " ".join(
        f"{name}={'✓' if gate[name] else '✗'}"
        for name in ("ir_pass", "net_pass", "dsr_pass", "pbo_pass", "folds_pass")
    )
    verdict = "PASS ✅" if gate["passes_gate"] else "BELOW GATE ❌"
    return "\n".join(
        [
            f"CTA-R gate scan (cta_eval_v1) -> {verdict}",
            f"  configs         : {result['evaluated_configs']} evaluated, {result['skipped_configs']} skipped",
            f"  effective breadth: {num(breadth.get('effective_breadth'), 2)}",
            f"  best cell       : lb={best['lookback_days']} vol={best['vol_lookback_days']} reb={best['rebalance_days']}",
            f"  best ann Sharpe : {num(result['best_annualized_sharpe'], 2)}  (gate >= {GATE_IR_THRESHOLD})",
            f"  DSR             : {num((result.get('deflated_sharpe') or {}).get('deflated_sharpe_ratio'))}  (gate >= {GATE_DSR_THRESHOLD})",
            f"  PBO             : {num((result.get('pbo') or {}).get('pbo'))}  (gate < {GATE_PBO_THRESHOLD})",
            f"  fold +frac      : {num(result['fold_positive_fraction'], 2)}  (gate >= {GATE_FOLD_POSITIVE_FRACTION})",
            f"  checks          : {checks}",
        ]
    )


# --------------------------------------------------------------------------------------
# Walk-forward / ensemble evaluation (no parameter selection -> PBO does not apply)
# --------------------------------------------------------------------------------------
#
# The gate's PBO asks "does the IN-SAMPLE best cell stay best out-of-sample?". When every
# cell is good and tightly clustered, that ranking is noise and PBO is pessimistic by
# construction. The honest answer is to NOT pick the best cell. Two selection-free reads:
#   - ensemble: equal-weight the daily returns of ALL cells (no pick at all);
#   - walk-forward: at each split pick the best-on-PAST-data cell and measure it FORWARD
#     (genuine out-of-sample selection, the thing PBO worries about, done honestly).
# The sim is strictly causal, so slicing each config's full-run net returns into
# past/future windows is a valid walk-forward. We also report a fixed, a-priori config.


def _return_stats(returns: list[float], *, n_folds: int = 5) -> dict[str, Any] | None:
    if not returns:
        return None
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1.0 + r))
    pp = per_period_sharpe(returns)
    folds = time_fold_sharpes(returns, n_folds)
    fold_values = [f for f in folds if isinstance(f, (int, float))]
    final = equity[-1]
    years = len(returns) / TRADING_DAYS_PER_YEAR
    return {
        "ann_sharpe": pp * math.sqrt(TRADING_DAYS_PER_YEAR) if pp is not None else None,
        "cagr": (final ** (1.0 / years) - 1.0) if years > 0 and final > 0 else None,
        "total_return_pct": final - 1.0,
        "max_drawdown": _max_drawdown(equity),
        "n_days": len(returns),
        "time_folds": folds,
        "fold_positive_fraction": (
            sum(1 for f in fold_values if f > 0) / len(fold_values) if fold_values else 0.0
        ),
    }


def run_walkforward_eval(
    prices: dict[str, list[float]],
    *,
    n_splits: int = 5,
    n_folds: int = 5,
    long_only: bool = False,
    max_leverage: float = 3.0,
    max_weight: float = 1.0,
    cost_per_side_pct: float = 0.0002,
    fixed_config: SimConfig | None = None,
    carry: dict[str, list[float | None]] | None = None,
) -> dict[str, Any]:
    """Selection-free robustness: equal-weight ensemble + past-only walk-forward + fixed cfg.

    Pass ``carry`` to evaluate the carry sleeve (carry grid + carry fixed config) instead of
    trend; the selection-free reads are identical in spirit.
    """

    grid = (
        default_carry_grid(
            long_only=long_only,
            max_leverage=max_leverage,
            max_weight=max_weight,
            cost_per_side_pct=cost_per_side_pct,
        )
        if carry is not None
        else default_grid(
            long_only=long_only,
            max_leverage=max_leverage,
            max_weight=max_weight,
            cost_per_side_pct=cost_per_side_pct,
        )
    )
    nets: list[list[float]] = []
    warmups: list[int] = []
    for config in grid:
        try:
            res = run_paper_sim(prices, config, carry)
        except ValueError:
            continue
        nets.append(res["net_daily_returns"])
        warmups.append(max(max(config.lookback_days), config.vol_lookback_days) + 1)
    if len(nets) < 2:
        return {"version": "cta_walkforward_v1", "decision": "insufficient_configs"}

    length = min(len(n) for n in nets)
    nets = [n[:length] for n in nets]
    start = min(max(warmups), length - 1)  # first day all configs are live

    # Ensemble: equal-weight the daily returns of every cell (no selection at all).
    ensemble = [
        _mean([nets[c][t] for c in range(len(nets))]) for t in range(start, length)
    ]

    # Walk-forward: contiguous OOS segments; pick the best-on-past cell, score it forward.
    span = length - start
    seg = span // n_splits
    walk_forward: list[float] = []
    choices: list[dict[str, Any]] = []
    if seg >= n_folds:
        for s in range(1, n_splits):
            past_hi = start + s * seg
            oos_hi = length if s == n_splits - 1 else start + (s + 1) * seg
            best_c = max(
                range(len(nets)),
                key=lambda c: (per_period_sharpe(nets[c][start:past_hi]) or -9.9),
            )
            walk_forward.extend(nets[best_c][past_hi:oos_hi])
            choices.append(
                {
                    "split": s,
                    "lookback_days": list(grid[best_c].lookback_days),
                    "vol_lookback_days": grid[best_c].vol_lookback_days,
                    "rebalance_days": grid[best_c].rebalance_days,
                }
            )

    # Fixed a-priori config (NOT the in-sample winner): a standard medium-term ensemble,
    # or a standard carry config when evaluating the carry sleeve.
    if fixed_config is not None:
        fixed = fixed_config
    elif carry is not None:
        fixed = SimConfig(
            signal="carry",
            carry_smooth_days=5,
            lookback_days=(1,),
            vol_lookback_days=63,
            rebalance_days=21,
            long_only=long_only,
            max_leverage=max_leverage,
            max_weight=max_weight,
            cost_per_side_pct=cost_per_side_pct,
        )
    else:
        fixed = SimConfig(
            lookback_days=(63, 126, 252),
            vol_lookback_days=63,
            rebalance_days=21,
            long_only=long_only,
            max_leverage=max_leverage,
            max_weight=max_weight,
            cost_per_side_pct=cost_per_side_pct,
        )
    fixed_net = run_paper_sim(prices, fixed, carry)["net_daily_returns"][:length][start:]

    ens_stats = _return_stats(ensemble, n_folds=n_folds)
    wf_stats = _return_stats(walk_forward, n_folds=n_folds)
    fixed_stats = _return_stats(fixed_net, n_folds=n_folds)

    def _robust(stats: dict[str, Any] | None) -> bool:
        return bool(
            stats
            and isinstance(stats.get("ann_sharpe"), (int, float))
            and stats["ann_sharpe"] >= GATE_IR_THRESHOLD
            and stats["fold_positive_fraction"] >= GATE_FOLD_POSITIVE_FRACTION
        )

    # No-selection robustness: ensemble AND true-OOS walk-forward both clear IR + folds.
    robust = _robust(ens_stats) and _robust(wf_stats)

    return {
        "version": "cta_walkforward_v1",
        "mode": {
            "long_only": long_only,
            "max_leverage": max_leverage,
            "max_weight": max_weight,
            "cost_per_side_pct": cost_per_side_pct,
        },
        "configs": len(nets),
        "eval_days": span,
        "n_splits": n_splits,
        "selection_free_robust": robust,
        "ensemble": ens_stats,
        "walk_forward": wf_stats,
        "walk_forward_choices": choices,
        "fixed_config": {
            "lookback_days": list(fixed.lookback_days),
            "vol_lookback_days": fixed.vol_lookback_days,
            "rebalance_days": fixed.rebalance_days,
        },
        "fixed": fixed_stats,
    }


def render_walkforward_summary(result: dict[str, Any]) -> str:
    def num(x: Any, d: int = 2) -> str:
        return f"{x:.{d}f}" if isinstance(x, (int, float)) else "n/a"

    if result.get("decision") == "insufficient_configs":
        return "CTA-R walk-forward: insufficient configs"

    def line(tag: str, stats: dict[str, Any] | None) -> str:
        if not stats:
            return f"  {tag:16}: n/a"
        return (
            f"  {tag:16}: Sharpe {num(stats['ann_sharpe'])}  CAGR {num((stats['cagr'] or 0) * 100, 1)}%"
            f"  maxDD {num(stats['max_drawdown'] * 100, 1)}%  fold+ {num(stats['fold_positive_fraction'])}"
            f"  (n={stats['n_days']})"
        )

    mode = result["mode"]
    verdict = "ROBUST ✅" if result["selection_free_robust"] else "NOT ROBUST ❌"
    return "\n".join(
        [
            f"CTA-R walk-forward (cta_walkforward_v1) -> selection-free {verdict}",
            f"  mode            : long_only={mode['long_only']} max_leverage={mode['max_leverage']}"
            f"  configs={result['configs']} eval_days={result['eval_days']}",
            line("ensemble", result["ensemble"]),
            line("walk-forward OOS", result["walk_forward"]),
            line("fixed a-priori", result["fixed"]),
        ]
    )
