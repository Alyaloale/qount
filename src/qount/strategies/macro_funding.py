"""Causal feature lookup and funding reserve, shared by replay and live."""
from __future__ import annotations
import bisect
import math
from qount.research_data.bars import funding_budget
FUNDING_POLICIES = ("absolute_peak", "debit_peak", "debit_stress")

def feature_at(features, now):
    idx = bisect.bisect_right([x["available"] for x in features], now) - 1
    return features[idx] if idx >= 0 else None


def funding_reserve(rows, now, hours=168, policy="absolute_peak", side=1):
    """Causal long-side reserve, never offset adverse costs with future credits.

    debit_stress keeps the full holding horizon: twice the past72h debit
    intensity, a24h peak-rate shock allowance, and a1bp/day minimum buffer.
    These are exploratory fixed assumptions, not calibrated coverage claims.
    """
    if side not in (-1, 1):
        raise ValueError("invalid_side")
    if policy not in FUNDING_POLICIES:
        raise ValueError("unknown_funding_policy")
    if not math.isfinite(hours) or hours < 0:
        raise ValueError("invalid_funding_horizon")
    known = [r for r in rows if now*1000-72*3600000 <= int(r["fundingTime"]) < now*1000
             and r.get("rateType", "Regular") == "Regular"]
    if not known:
        return None
    if hours == 0:
        return 0.0
    settings = {"funding_interval_mode": "known_or_observed",
                "funding_interval_fallback_hours": 8}
    if policy == "absolute_peak":
        return funding_budget(known, [], now, hours, settings)["fraction"]
    debits = [{**r, "fundingRate": str(max(0.0, side*float(r["fundingRate"])))} for r in known]
    if policy == "debit_peak":
        return funding_budget(debits, [], now, hours, settings)["fraction"]
    # Reject incomplete72h history rather than treating missing observations as
    # zero debits. The original loader checks the regular settlement cadence.
    times = sorted({int(r["fundingTime"]) for r in known})
    observed = funding_budget(debits, [], now, hours, settings)
    interval = observed["interval_hours"]
    if times[0] > (now-72*3600+interval*3600)*1000+10000:
        return None
    baseline = 2*sum(float(r["fundingRate"]) for r in debits)*hours/72
    shock = funding_budget(debits, [], now, min(hours, 24), settings)["fraction"]
    return max(baseline, shock, 0.0001*hours/24)
