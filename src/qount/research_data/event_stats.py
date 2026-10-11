"""Calendar-block diagnostics for sparse, correlated research event labels."""
from __future__ import annotations

import random
import statistics


def sparse_block_intervals(events, *, first_ms, last_ms, samples=1000, seed=20261009):
    """Resample complete seven-day calendar buckets, retaining empty buckets.

    Events contain ``entry_ms`` and conservative per-notional ``net_lower``.
    These descriptive intervals do not certify independent or fresh evidence.
    """
    if not events:
        return {"mean": None, "win_rate": None, "occupied_blocks": 0}
    width = 7 * 86400000
    blocks = [[0, 0.0, 0] for _ in range((last_ms - first_ms) // width + 1)]
    for event in events:
        index = (event['entry_ms'] - first_ms) // width
        if not 0 <= index < len(blocks):
            raise ValueError('event_outside_calendar')
        b = blocks[index]
        b[0] += 1
        b[1] += event['net_lower']
        b[2] += event['net_lower'] > 0
    rng = random.Random(seed)
    means, wins = [], []
    for _ in range(samples):
        chosen = rng.choices(blocks, k=len(blocks))
        count = sum(b[0] for b in chosen)
        if count:
            means.append(sum(b[1] for b in chosen) / count)
            wins.append(sum(b[2] for b in chosen) / count)
    def interval(values):
        values.sort()
        return [values[int(.025 * (len(values) - 1))], values[int(.975 * (len(values) - 1))]] if values else None
    return {"mean": interval(means), "win_rate": interval(wins),
            "occupied_blocks": sum(b[0] > 0 for b in blocks), "calendar_blocks": len(blocks),
            "bootstrap_nonempty_draws": len(means), "method": "seven_day_calendar_cluster_percentile_descriptive"}


def event_summary(events, *, first_ms, last_ms, gate):
    intervals = sparse_block_intervals(events, first_ms=first_ms, last_ms=last_ms,
                                     samples=gate['bootstrap_samples'], seed=gate['bootstrap_seed'])
    if not events:
        return {"events": 0, "mean_net_lower": None, "net_lower_win_rate": None,
                "intervals": intervals, "diagnostic_gate_passed": False}
    values = [e['net_lower'] for e in events]
    years = {}
    for e in events:
        years.setdefault(e['entry_utc'][:4], []).append(e['net_lower'])
    best_year = max(years, key=lambda year: (sum(years[year]), year))
    without_year = [v for year, group in years.items() if year != best_year for v in group]
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    mean, rate = statistics.fmean(values), len(wins) / len(values)
    passed = (len(values) >= gate['min_events'] and intervals['occupied_blocks'] >= gate['min_seven_day_blocks']
              and mean > 0 and intervals['mean'] is not None and intervals['mean'][0] > 0
              and rate >= gate['min_net_win_rate'] and intervals['win_rate'][0] > gate['win_interval_lower_min']
              and sum(values) - max(values) > 0 and bool(without_year) and sum(without_year) > 0)
    return {"events": len(values), "wins_lower": len(wins), "mean_net_lower": mean,
            "mean_net_proxy": statistics.fmean(e['net_proxy'] for e in events),
            "net_lower_win_rate": rate, "average_win": statistics.fmean(wins) if wins else None,
            "average_loss": statistics.fmean(losses) if losses else None,
            "profit_factor": sum(wins) / -sum(losses) if losses else None,
            "worst_net_lower": min(values), "sum_net_lower_ex_best_event": sum(values) - max(values),
            "excluded_best_year": best_year, "mean_ex_best_year": statistics.fmean(without_year) if without_year else None,
            "by_year": {y: {"events": len(v), "mean_net_lower": statistics.fmean(v),
                            "net_win_rate": sum(x > 0 for x in v) / len(v)} for y, v in sorted(years.items())},
            "intervals": intervals, "diagnostic_gate_passed": passed}
