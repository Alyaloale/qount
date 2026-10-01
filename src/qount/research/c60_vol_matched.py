"""Descriptive: C60 v2 vs volatility-matched BTC and a BTC-only C60 gate ablation (not a trial).

Preregistration: docs/cta-r-us-replication-and-c60-vol-matched-2026-09.md (section B)
research_only=true / orders_authorized=false. Offline on the frozen cost-study panel.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from qount.dual_engine.contracts import DualEnginePaperContract
from qount.research.c60_cost_study import (
    WARMUP_BARS,
    Panel,
    SimResult,
    annual_sharpe,
    c60_target,
    cagr,
    max_drawdown,
    simulate,
    target_path,
    yearly_returns,
)
from qount.research_data.metrics import _moments

COST_BPS = 25.0
VOL_WINDOW = 60
EXCLUDED_YEAR = "2021"
GUARDS = {"research_only": True, "orders_authorized": False, "trial": False, "global_trial_count": 151}


def _gross_returns(panel: Panel, targets: Sequence[Mapping[str, float]]) -> list[float]:
    """r_p[t] = sum w_t * r[t+1] (0 bps); index t holds the return earned after close t."""

    out = [0.0] * len(panel.dates)
    for t in range(len(panel.dates) - 1):
        out[t] = sum(w * (panel.closes[s][t + 1] / panel.closes[s][t] - 1.0) for s, w in targets[t].items())
    return out


def _stdev(values: Sequence[float]) -> float:
    return _moments(list(values))[1]


def static_vol_matched(panel: Panel, c60: SimResult) -> tuple[list[dict[str, float]], float]:
    btc = panel.closes["BTCUSDT"]
    first = WARMUP_BARS - 1
    btc_returns = [btc[t + 1] / btc[t] - 1.0 for t in range(first, len(btc) - 1)]
    k = _stdev(c60.returns) / _stdev(btc_returns)
    targets = [{} for _ in panel.dates]
    for t in range(first, len(panel.dates)):
        targets[t] = {"BTCUSDT": k}
    return targets, k


def ex_ante_vol_matched(panel: Panel, c60_targets: Sequence[Mapping[str, float]]) -> list[dict[str, float]]:
    """Weight at close t uses only returns realised up to close t (past 60 days)."""

    c60_r = _gross_returns(panel, c60_targets)  # c60_r[i] realised at close i+1
    btc = panel.closes["BTCUSDT"]
    targets: list[dict[str, float]] = [{} for _ in panel.dates]
    for t in range(WARMUP_BARS - 1, len(panel.dates)):
        if t < VOL_WINDOW + 1:
            continue
        c_hist = c60_r[t - VOL_WINDOW:t]  # realised by close t
        b_hist = [btc[i] / btc[i - 1] - 1.0 for i in range(t - VOL_WINDOW + 1, t + 1)]
        sb = _stdev(b_hist)
        if sb > 0.0:
            w = min(1.0, _stdev(c_hist) / sb)
            if w > 0.0:
                targets[t] = {"BTCUSDT": w}
    return targets


def btc_only_gate(panel: Panel) -> list[dict[str, float]]:
    """Frozen C60 conditions on BTC alone: 90d momentum > 0, SMA20, SMA50, 20d vol cap 60%; daily."""

    contract = DualEnginePaperContract.frozen_v1()
    btc = panel.closes["BTCUSDT"]
    targets: list[dict[str, float]] = [{} for _ in panel.dates]
    for t in range(WARMUP_BARS - 1, len(panel.dates)):
        window = {"BTCUSDT": btc[t - WARMUP_BARS + 1:t + 1]}
        candidates = ("BTCUSDT",) if window["BTCUSDT"][-1] / window["BTCUSDT"][-91] - 1.0 > 0.0 else ()
        targets[t] = c60_target(window, candidates, contract)
    return targets


def _summary(result: SimResult) -> dict[str, object]:
    kept = [r for d, r in zip(result.dates, result.returns) if d[:4] != EXCLUDED_YEAR]
    std = _moments(list(result.returns))[1]
    return {
        "cagr": round(cagr(result.returns), 4), "sharpe": round(annual_sharpe(result.returns), 4),
        "max_drawdown": round(max_drawdown(result.returns), 4), "annual_vol": round(std * math.sqrt(365.0), 4),
        "average_gross": round(result.average_gross, 4),
        "annual_turnover": round(result.turnover / (len(result.returns) / 365.0), 3),
        "ex_2021_cagr": round(cagr(kept), 4), "ex_2021_sharpe": round(annual_sharpe(kept), 4),
        "yearly": {y: round(v, 4) for y, v in yearly_returns(result).items()},
    }


def run(panel: Panel) -> dict[str, object]:
    c60_targets = target_path(panel, mode="research_monthly")
    c60 = simulate(panel, c60_targets, cost_bps=COST_BPS)
    static_targets, k = static_vol_matched(panel, c60)
    variants = {
        "c60_v2": c60,
        "btc_static_vol_matched": simulate(panel, static_targets, cost_bps=COST_BPS),
        "btc_ex_ante_vol_matched": simulate(panel, ex_ante_vol_matched(panel, c60_targets), cost_bps=COST_BPS),
        "btc_only_c60_gate": simulate(panel, btc_only_gate(panel), cost_bps=COST_BPS),
    }
    for name, result in variants.items():
        if result.dates != c60.dates:
            raise ValueError(f"window_mismatch:{name}")
    return {"guards": GUARDS, "cost_bps": COST_BPS, "static_k": round(k, 6),
            "window": {"first": c60.dates[0], "last": c60.dates[-1], "bars": len(c60.dates)},
            "variants": {name: _summary(result) for name, result in variants.items()}}
