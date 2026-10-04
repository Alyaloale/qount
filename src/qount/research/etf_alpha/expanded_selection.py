"""Validation-only v2 selection with hard constraints and signal/control gates."""
from __future__ import annotations

import numpy as np

BASELINES = ("E3-ridge-raw", "train-asset-mean", "momentum120", "cash")
NEGATIVE = "v2-rank-shuffle"


def hard_constraints(records):
    return bool(records) and all(r["bridge"]["2x"]["forced_breaches"] == 0
        and r["bridge"]["2x"]["minimum_cash"] >= -1e-7
        and r["bridge"]["2x"]["max_rolling_voluntary"] <= 4 + 1e-7 for r in records)


def utility(records):
    """Frozen units: cash-excess Sharpe - 2*MDD - .025*used annual turnover/4."""
    values = []
    for r in records:
        b = r["bridge"]["2x"]
        values.append((b["sharpe_excess_cash"] or 0) - 2 * b["max_drawdown"] - .025 * b["max_rolling_voluntary"] / 4)
    return float(np.mean(values))


def select_v2(records):
    if any(not records.get(k) for k in (*BASELINES, NEGATIVE)):
        raise ValueError("complete past-validation controls required")
    # Use the average negative control, not its luckiest seed, as the paired family reference.
    reference = max(0., records["train-asset-mean"][0]["prediction"]["rank_ic"] or 0.,
                    float(np.mean([r["prediction"]["rank_ic"] or 0. for r in records[NEGATIVE]])))
    loss_reference = min(records[k][0]["prediction"]["mu20_huber"] for k in ("E3-ridge-raw", "train-asset-mean"))
    eligible = {k: v for k, v in records.items() if k in BASELINES and hard_constraints(v)}
    decisions = {}
    for name, values in records.items():
        if name in (*BASELINES, "negative-ridge-shuffle", NEGATIVE):
            continue
        ranks = [r["prediction"]["rank_ic"] for r in values]
        complete = len(values) == 5
        positive = complete and all(v is not None for v in ranks) and sum(v > reference + .01 for v in ranks) >= 3
        loss_ok = bool(values) and np.mean([r["prediction"]["mu20_huber"] for r in values]) <= 1.05 * loss_reference
        risk_ok = hard_constraints(values)
        qualified = bool(complete and positive and loss_ok and risk_ok)
        decisions[name] = {"eligible": qualified, "complete_five_seeds": complete, "rank_increment_and_consensus": bool(positive),
                           "huber_within_five_percent_of_baseline": bool(loss_ok), "hard_constraints": risk_ok,
                           "mean_rank_ic": float(np.mean(ranks)) if ranks and all(v is not None for v in ranks) else None,
                           "validation_utility": utility(values) if values else None}
        if qualified:
            eligible[name] = values
    if not eligible:
        raise ValueError("no completed constrained baseline/candidate")
    selected = min(eligible, key=lambda k: (-utility(eligible[k]), eligible[k][0]["parameters"], k))
    return {"selected": selected, "eligible": list(eligible), "decisions": decisions,
            "rank_reference": reference, "huber_reference": float(loss_reference),
            "utility": "mean_seed(Sharpe_cash_2x - 2*MDD_2x - .025*rolling_voluntary/4)",
            "test_used_for_selection": False, "new_trials_after_test": False}
