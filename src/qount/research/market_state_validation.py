"""Outcome-based validation of descriptive states, with causal probabilities.

There is no observed ten-state ground truth. The tasks here have separately
defined, later observable targets. No trading returns or position sizes enter.
"""
from __future__ import annotations

from collections import defaultdict
import math

import numpy as np


def state_key(row):
    key = row["action_state"]
    if key in ("up_breakout", "down_breakout"):
        key += ":"+row["event"]["status"]
    return key


def future_direction(bars, states, *, horizon=5):
    """Future close displacement relative to known vol20, not future indicators.

    Up/down means log(close[t+h]/close[t]) outside +/- .5*sigma20*sqrt(h).
    The middle class is a small terminal displacement, NOT proof of a range
    path. Regular nonoverlapping origins are fixed by index before any labels.
    """
    if horizon < 1:
        raise ValueError("positive_validation_horizon_required")
    samples = []
    for i in range(200, len(bars)-horizon, horizon):
        bar, row, end = bars[i], states[bars[i].t], bars[i+horizon]
        if row["action_state"] == "unknown":
            continue
        boundary = .5*row["volatility20"]*math.sqrt(horizon)
        displacement = math.log(end.c/bar.c)
        label = 2 if displacement > boundary else 0 if displacement < -boundary else 1
        side = (1 if row["action_state"] in ("up_trend", "up_breakout", "failed_down_breakout") else
                -1 if row["action_state"] in ("down_trend", "down_breakout", "failed_up_breakout") else 0)
        pending = row.get("event") is not None and row["event"]["status"] == "pending"
        fixed = (side+1) if side and not pending else 1 if row["action_state"] in (
            "compression", "range", "wide_range") else None
        samples.append(dict(known_at=bar.t, mature_at=end.t, key=state_key(row),
            outcome=label, fixed_prediction=fixed, actionable=bool(row["route_side"]),
            route_class=row["route_side"]+1 if row["route_side"] else None,
            displacement=displacement, known_direction_threshold=boundary))
    return samples


def range_containment(bars, states, *, horizon=5):
    """Will ALL next h closes stay within the fixed prior twenty-bar bounds?

    A small final displacement can hide a large excursion. This separate task
    measures path containment and reports compression/range/wide-range apart.
    """
    samples = []
    for i in range(200, len(bars)-horizon, horizon):
        row = states[bars[i].t]
        if row["action_state"] not in ("compression", "range", "wide_range"):
            continue
        future = bars[i+1:i+horizon+1]
        inside = all(row["previous_low20"] <= b.c <= row["previous_high20"] for b in future)
        samples.append(dict(known_at=bars[i].t, mature_at=bars[i+horizon].t, key=state_key(row),
            outcome=int(inside), fixed_prediction=1, actionable=False, route_class=None))
    return samples


def breakout_survival(bars, states, *, horizon=3):
    """At the FIRST pending/confirmed close, predict the NEXT three closes.

    Both origins get an equal future horizon. Confirmation has already observed
    more of the event and is NOT compared to initial failure over a shorter
    residual window. It may still fail after the original three-bar monitor.
    Initial and confirmed records can overlap; clustered inference is required.
    """
    samples, observed = [], set()
    for i in range(200, len(bars)-horizon):
        row = states[bars[i].t]
        event = row.get("event")
        if event is None or event["status"] not in ("pending", "confirmed"):
            continue
        identity = (event["started_at"], event["status"])
        if identity in observed:
            continue
        observed.add(identity)
        inside = all(event["side"]*(b.c-event["boundary"]) > 0 for b in bars[i+1:i+horizon+1])
        key = ("up" if event["side"] == 1 else "down")+":"+event["status"]
        samples.append(dict(known_at=bars[i].t, mature_at=bars[i+horizon].t, key=key,
            outcome=int(inside), fixed_prediction=1, actionable=event["status"] == "confirmed",
            route_class=None, event_started_at=event["started_at"]))
    return samples


def causal_probabilities(samples, classes, *, prior_strength=50.):
    """Expanding chronological estimate, only outcomes mature STRICTLY before t.

    One fixed shrinkage estimate: pooled state counts + 50 asset-prior pseudo
    observations. The baseline is the SAME causal asset class-frequency prior.
    Initial Laplace smoothing avoids zero probabilities. No threshold tuning.
    """
    if any(not 0<=s["outcome"]<classes or s["mature_at"]<=s["known_at"] for s in samples):
        raise ValueError("invalid_or_censored_training_target")
    ordered = sorted(samples, key=lambda s: (s["known_at"], s["asset"], s["key"]))
    mature = sorted(ordered, key=lambda s: s["mature_at"])
    by_asset = defaultdict(lambda: np.zeros(classes))
    by_state = defaultdict(lambda: np.zeros(classes))
    pooled = np.zeros(classes)
    position, latest = 0, None
    result = []
    for sample in ordered:
        while position < len(mature) and mature[position]["mature_at"] < sample["known_at"]:
            old = mature[position]
            by_asset[old["asset"]][old["outcome"]] += 1
            by_state[old["key"]][old["outcome"]] += 1
            pooled[old["outcome"]] += 1
            latest = old["mature_at"]
            position += 1
        asset_counts = by_asset[sample["asset"]]
        prior = (asset_counts+1)/(asset_counts.sum()+classes) if asset_counts.sum() else (pooled+1)/(pooled.sum()+classes)
        counts = by_state[sample["key"]]
        probability = (counts+prior_strength*prior)/(counts.sum()+prior_strength)
        result.append(dict(sample, probabilities=probability.tolist(), baseline=prior.tolist(),
            state_training_count=int(counts.sum()), asset_training_count=int(asset_counts.sum()),
            last_training_maturity=latest))
    return result


def scores(records, field="probabilities"):
    if not records:
        return None
    probabilities = np.array([r[field] for r in records])
    truth = np.array([r["outcome"] for r in records], int)
    classes = probabilities.shape[1]
    prediction = probabilities.argmax(axis=1)
    observed = np.eye(classes)[truth]
    matrix = np.zeros((classes, classes), int)
    for actual, guess in zip(truth, prediction):
        matrix[actual, guess] += 1
    recall, f1 = [], []
    for k in range(classes):
        tp = matrix[k,k]
        actual, guessed = matrix[k].sum(), matrix[:,k].sum()
        if actual:
            recall.append(tp/actual)
        f1.append(2*tp/(actual+guessed) if actual+guessed else 0.)
    confidence = probabilities.max(axis=1)
    bins = []
    for left, right in zip((0., .45, .55, .65, .75, .85), (.45, .55, .65, .75, .85, 1.000001)):
        mask = (confidence >= left) & (confidence < right)
        if mask.any():
            bins.append(dict(left=left, right=min(right,1.), count=int(mask.sum()),
                mean_confidence=float(confidence[mask].mean()), accuracy=float((prediction[mask]==truth[mask]).mean())))
    return dict(count=len(records), accuracy=float((prediction==truth).mean()),
        balanced_accuracy=float(np.mean(recall)), macro_f1=float(np.mean(f1)), confusion=matrix.tolist(),
        brier=float(np.mean(np.sum((probabilities-observed)**2, axis=1))),
        log_loss=float(-np.log(np.maximum(probabilities[np.arange(len(truth)),truth],1e-12)).mean()),
        calibration=bins, expected_calibration_error=sum(b["count"]*abs(b["mean_confidence"]-b["accuracy"]) for b in bins)/len(records))
