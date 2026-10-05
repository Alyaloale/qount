"""Self-financing proportional fees for offline, normalized research accounts."""

from __future__ import annotations

import math
from collections.abc import Mapping


def trade_to_target(pre_weights: Mapping[str, float], target: Mapping[str, float],
                    cost_bps: float, *, exact: bool = True) -> tuple[float, float]:
    """Return remaining NAV ratio and traded notional / pretrade NAV.

    Cash is implicit and does not itself incur fees. In the exact model the
    target applies to NAV after fees: z = 1 - k * sum(abs(z*t - w)).
    This is unit accounting, not a broker execution or cash-dividend model.
    """
    rate = cost_bps / 10_000.0
    if (not math.isfinite(rate) or not 0.0 <= rate < 0.5
            or any(not math.isfinite(w) or w < 0.0 for w in (*pre_weights.values(), *target.values()))
            or sum(pre_weights.values()) > 1.0 + 1e-10
            or sum(target.values()) > 1.0 + 1e-10):
        raise ValueError("invalid_long_only_fee_inputs")
    names = sorted(set(pre_weights) | set(target))

    def notional(ratio: float) -> float:
        return sum(abs(ratio * target.get(s, 0.0) - pre_weights.get(s, 0.0)) for s in names)

    if not exact or rate == 0.0:
        turnover = notional(1.0)
        return 1.0 - rate * turnover, turnover
    lo, hi = 0.0, 1.0
    for _ in range(64):
        mid = (lo + hi) / 2.0
        if mid + rate * notional(mid) > 1.0:
            hi = mid
        else:
            lo = mid
    ratio = (lo + hi) / 2.0
    return ratio, notional(ratio)
