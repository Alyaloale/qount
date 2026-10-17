"""Unchanged causal minute-volume capacity rule."""
import math

def capacity_snapshot(bars, now, participation=.10):
    """Use15 completed minutes ending one minute before the decision only."""
    if not math.isfinite(participation) or not 0 < participation <= 1:
        raise ValueError("invalid_participation")
    end = now-60
    known = sorted((b for b in bars if end-15*60 <= b.t and b.t+60 <= end), key=lambda b: b.t)
    if [b.t for b in known] != list(range(end-15*60, end, 60)):
        return None
    if any(not math.isfinite(b.v) or b.v < 0 for b in known):
        raise ValueError("invalid_historical_volume")
    mean5 = sum(b.v for b in known[-5:])/5
    mean15 = sum(b.v for b in known)/15
    return dict(asof=end, lookback_start=known[0].t, quantity_cap=participation*min(mean5, mean15),
                mean_volume_5m=mean5, mean_volume_15m=mean15, participation=participation)
