"""Descriptive turnover attribution for C60 (not a trial).

Preregistration: docs/c60-turnover-attribution-diagnostic-2026-09.md
research_only=true / orders_authorized=false. Targets come from ``c60_cost_study.target_path`` unchanged;
this module only re-derives each day's candidate set and splits turnover by cause.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from qount.research.c60_cost_study import (
    WARMUP_BARS,
    C60CostStudyError,
    Panel,
    _is_month_end,
    _rank_candidates,
    simulate,
    target_path,
)

COST_BPS = 25.0
SMALL_TRADE = 0.01
CAUSES = ("candidate", "gate", "vol_scalar")
GUARDS = {"research_only": True, "orders_authorized": False, "trial": False, "global_trial_count": 150}


def _l1(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    return sum(abs(a.get(s, 0.0) - b.get(s, 0.0)) for s in set(a) | set(b))


def candidate_path(panel: Panel, *, mode: str) -> list[tuple[str, ...]]:
    """Same candidate selection as ``target_path`` (index < WARMUP_BARS-1 stays empty)."""

    out: list[tuple[str, ...]] = [() for _ in panel.dates]
    held: tuple[str, ...] = ()
    for index in range(WARMUP_BARS - 1, len(panel.dates)):
        window = {s: v[index - WARMUP_BARS + 1:index + 1] for s, v in panel.closes.items()}
        if mode == "frozen_daily":
            out[index] = _rank_candidates(window)
        elif mode == "research_monthly":
            if _is_month_end(panel.dates, index):
                held = _rank_candidates(window)
            out[index] = held
        else:
            raise C60CostStudyError("target_mode_invalid")
    return out


def _cause(prev_c, cur_c, prev_t, cur_t) -> str:
    if set(prev_c) != set(cur_c):
        return "candidate"
    if set(prev_t) != set(cur_t):
        return "gate"
    return "vol_scalar"


def attribute(panel: Panel, *, mode: str, start_date: str | None = None) -> dict[str, object]:
    targets = target_path(panel, mode=mode)
    candidates = candidate_path(panel, mode=mode)
    for index, target in enumerate(targets):
        if not set(target) <= set(candidates[index]):
            raise C60CostStudyError("attribution_candidate_mismatch")
    first = WARMUP_BARS - 1
    if start_date is not None:
        later = [i for i, day in enumerate(panel.dates) if day >= start_date]
        if not later:
            raise C60CostStudyError("simulation_start_after_panel")
        first = max(first, later[0])

    sums = {"total": 0.0, "drift": 0.0, "netting": 0.0} | {c: 0.0 for c in CAUSES}
    days = {c: 0 for c in CAUSES} | {"drift_only": 0, "traded": 0, "small": 0}
    small_turnover = 0.0
    weights: dict[str, float] = {}
    prev_target: dict[str, float] = {}
    prev_cand: tuple[str, ...] = ()
    for index in range(first, len(panel.dates) - 1):
        target = targets[index]
        total = _l1(target, weights)
        drift = _l1(prev_target, weights)
        change = _l1(target, prev_target)
        sums["total"] += total
        sums["drift"] += drift
        sums["netting"] += drift + change - total
        if change > 1e-12:
            cause = _cause(prev_cand, candidates[index], prev_target, target)
            sums[cause] += change
            days[cause] += 1
        elif total > 1e-12:
            days["drift_only"] += 1
        if total > 1e-12:
            days["traded"] += 1
            if total < SMALL_TRADE:
                days["small"] += 1
                small_turnover += total
        # Mirror of c60_cost_study.simulate drift (T+0, cost deducted pro rata).
        cost = total * COST_BPS / 10_000.0
        asset = {s: panel.closes[s][index + 1] / panel.closes[s][index] - 1.0 for s in target}
        grown = {s: w * (1.0 + asset[s]) for s, w in target.items()}
        nav = (1.0 - cost) * (1.0 + sum(w * asset[s] for s, w in target.items()))
        weights = {s: v * (1.0 - cost) / nav for s, v in grown.items()} if nav > 0.0 else {}
        prev_target, prev_cand = dict(target), candidates[index]

    reference = simulate(panel, targets, cost_bps=COST_BPS, start_date=start_date)
    if abs(reference.turnover - sums["total"]) > 1e-9:
        raise C60CostStudyError("attribution_turnover_mismatch")
    years = len(reference.returns) / 365.0
    total = sums["total"] or 1.0
    return {
        "mode": mode,
        "start_date": start_date or panel.dates[first],
        "bars": len(reference.returns),
        "turnover_total": round(sums["total"], 6),
        "turnover_per_year": round(sums["total"] / years, 4),
        "cost_bps_per_year": round(sums["total"] / years * COST_BPS, 2),
        "components": {k: round(sums[k], 6) for k in ("drift", *CAUSES, "netting")},
        "share_of_total": {k: round(sums[k] / total, 4) for k in ("drift", *CAUSES)},
        "days": days,
        "small_trade_turnover_share": round(small_turnover / total, 4),
        "small_trade_threshold": SMALL_TRADE,
    }


def run(panel: Panel, *, windows: Sequence[str | None] = (None, "2026-01-01")) -> dict[str, object]:
    return {
        "guards": GUARDS,
        "cost_bps": COST_BPS,
        "results": [attribute(panel, mode=m, start_date=w)
                    for m in ("frozen_daily", "research_monthly") for w in windows],
    }
