"""Calendar-preserving statistical primitives for the fixed A-share protocol.

This module has no market-data loader, ranking runner or portfolio interface.
"""
from __future__ import annotations

import math
import random
import statistics


def decision_mask(session_count, boundaries=(), *, latest_exit=22, embargo=22):
    """Use common maturity and exact purge/embargo on the original session grid."""
    if session_count < 1 or latest_exit < 1 or embargo < 0:
        raise ValueError('ashare_invalid_mask_shape')
    if len(set(boundaries)) != len(boundaries) or any(not 0 < b < session_count for b in boundaries):
        raise ValueError('ashare_invalid_segment_boundary')
    result = [j + latest_exit < session_count for j in range(session_count)]
    for boundary in boundaries:
        for j in range(max(0, boundary-latest_exit), min(session_count, boundary+embargo)):
            result[j] = False
    return result


def calendar_block_mean_interval(values, *, block_sessions=60, samples=2000, seed=20261009):
    """Noncircular moving blocks, preserving unknown positions and calendar gaps.

    Means/intervals describe observed values only. Any unknown date prevents
    this interval from certifying the complete information plan by itself.
    Quantiles use sorted empirical order statistics floor(p * (B - 1)).
    """
    if not values or block_sessions < 1 or samples < 1:
        raise ValueError('ashare_invalid_block_shape')
    observed = [float(v) if v is not None and math.isfinite(v) else None for v in values]
    sums, counts = [0.0], [0]
    for v in observed:
        sums.append(sums[-1] + (v if v is not None else 0.0))
        counts.append(counts[-1] + (v is not None))
    n, width = len(observed), min(block_sessions, len(observed))
    rng = random.Random(seed)
    means, draw_counts = [], []
    for _ in range(samples):
        total, count, filled = 0.0, 0, 0
        while filled < n:
            start = rng.randrange(n-width+1)
            take = min(width, n-filled)
            total += sums[start+take] - sums[start]
            count += counts[start+take] - counts[start]
            filled += take
        draw_counts.append(count)
        if count:
            means.append(total/count)
    means.sort()
    interval = [means[math.floor(p*(len(means)-1))] for p in (.025,.975)] if means else None
    return {'mean_observed': statistics.fmean(v for v in observed if v is not None) if counts[-1] else None,
            'mean_95pct_interval_conditional': interval, 'calendar_positions': n,
            'observed_positions': counts[-1], 'unknown_positions': n-counts[-1],
            'requested_draws': samples, 'nonempty_draws': len(means),
            'minimum_observations_per_draw': min(draw_counts), 'maximum_observations_per_draw': max(draw_counts),
            'block_sessions': block_sessions, 'effective_block_sessions': width, 'seed': seed,
            'method': 'noncircular_moving_session_blocks_tail_truncated_empirical_floor_quantiles',
            'unknown_gate_resolved_by_interval': False,
            'complete_plan_can_be_certified_from_interval_alone': False}
