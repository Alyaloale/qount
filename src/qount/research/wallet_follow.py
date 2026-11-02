"""Offline reconstruction of public fills and delayed cross-venue direction copying."""
from collections import Counter, defaultdict
from decimal import Decimal
import math

import numpy as np

MINUTE = 60_000


def position_edge(fill):
    before = Decimal(fill["startPosition"])
    size = Decimal(fill["sz"])
    if fill["side"] not in ("A", "B") or size <= 0:
        raise ValueError("invalid_fill_side_or_size")
    after = before + size * (1 if fill["side"] == "B" else -1)
    return before, after


def connect_group(fills, previous=None):
    """Euler path validates a same-millisecond position graph.

    Internal execution order may not be unique. Only group endpoints are used
    for signals, so alternate valid internal paths cannot change the signal.
    A closed cycle without a known incoming position has ambiguous endpoints.
    """
    adjacency, degree = defaultdict(list), Counter()
    edges = []
    for i, fill in enumerate(fills):
        a, b = position_edge(fill)
        edges.append((a, b))
        adjacency[a].append((b, i))
        degree[a] += 1
        degree[b] -= 1
    starts = [v for v, d in degree.items() if d == 1]
    ends = [v for v, d in degree.items() if d == -1]
    if any(abs(d) > 1 for d in degree.values()) or len(starts) != len(ends) or len(starts) > 1:
        raise ValueError("invalid_position_graph_degrees")
    if starts:
        start = starts[0]
    elif previous is not None and previous in adjacency:
        start = previous
    else:
        raise ValueError("ambiguous_cycle_without_anchor")
    vertices, used, path = [start], [], []
    while vertices:
        v = vertices[-1]
        if adjacency[v]:
            b, i = adjacency[v].pop()
            vertices.append(b)
            used.append(i)
        else:
            vertices.pop()
            if used:
                path.append(used.pop())
    path.reverse()
    if len(path) != len(fills):
        raise ValueError("disconnected_position_graph")
    cursor = start
    for i in path:
        if edges[i][0] != cursor:
            raise ValueError("invalid_position_path")
        cursor = edges[i][1]
    return start, cursor, path


def sign(value):
    return int(value > 0) - int(value < 0)


def reconstruct(fills):
    groups, seen = defaultdict(list), set()
    duplicate = spot = 0
    for fill in fills:
        key = (fill["coin"], fill["tid"], fill["hash"])
        if key in seen:
            duplicate += 1
            continue
        seen.add(key)
        if fill["dir"] in ("Buy", "Sell") or fill["coin"].startswith("@"):
            spot += 1
            continue
        groups[(fill["time"], fill["coin"])].append(fill)
    previous, opened = {}, {}
    signals, states, episodes, errors = [], [], [], []
    stats = Counter(duplicate_fills=duplicate, excluded_spot_fills=spot)
    for (stamp, coin), group in sorted(groups.items()):
        try:
            before, after, path = connect_group(group, previous.get(coin))
        except ValueError as exc:
            errors.append(dict(time_ms=stamp, coin=coin, reason=str(exc), fills=len(group)))
            previous.pop(coin, None)
            opened.pop(coin, None)
            signals.append(dict(time_ms=stamp, coin=coin, target=0, reason="unreconstructed_group"))
            continue
        if coin in previous and previous[coin] != before:
            stats["cross_timestamp_gaps"] += 1
            opened.pop(coin, None)
            signals.append(dict(time_ms=stamp, coin=coin, target=0, reason="position_gap"))
        stats["connected_groups"] += 1
        stats["connected_fills"] += len(group)
        stats["multi_fill_groups"] += len(group) > 1
        a, b = sign(before), sign(after)
        states.append(dict(time_ms=stamp, coin=coin, before=str(before), after=str(after)))
        if a != b:
            if coin in opened:
                entry, side = opened.pop(coin)
                episodes.append(dict(coin=coin, entry_ms=entry, exit_ms=stamp, side=side,
                                     duration_seconds=(stamp-entry)/1000))
            if b:
                opened[coin] = (stamp, b)
            signals.append(dict(time_ms=stamp, coin=coin, target=b, reason="net_direction_change"))
            stats["direction_changes"] += 1
        previous[coin] = after
    stats["right_censored_directions"] = len(opened)
    return dict(stats=dict(stats), errors=errors, states=states, signals=signals, episodes=episodes)


def persistence_signals(signals, confirmation_seconds, *, last_observed_ms):
    """Confirm a direction using elapsed observations; cancel on earlier change.

    All times here are source times; the simulator adds the same observation
    latency to entries and exits. Changes at the exact deadline cancel first.
    """
    confirmed, pending, out = 0, None, []
    for signal in sorted(signals, key=lambda s:s["time_ms"]):
        t, target = signal["time_ms"], signal["target"]
        if pending and pending[0] < t:
            due, direction = pending
            out.append(dict(time_ms=due, target=direction, reason="direction_persisted"))
            confirmed, pending = direction, None
        if confirmed and confirmed != target:
            out.append(dict(time_ms=t, target=0, reason="source_direction_changed"))
            confirmed = 0
        pending = (t + confirmation_seconds*1000, target) if target and target != confirmed else None
    if pending and pending[0] <= last_observed_ms:
        out.append(dict(time_ms=pending[0], target=pending[1], reason="direction_persisted"))
    return out


def hourly_inventory_signals(states, *, last_observed_ms):
    """Hourly decisions from the preceding full hour's time-weighted inventory.

    No backfill before the first observed state. Position units are used only
    for direction; this is not a reconstruction of account risk percentages.
    """
    if not states:
        return []
    states = sorted(states, key=lambda s:s["time_ms"])
    stamps = np.asarray([s["time_ms"] for s in states], dtype=np.int64)
    values = np.asarray([float(s["after"]) for s in states])
    hour = 60*MINUTE
    first = math.ceil((stamps[0]+hour)/hour)*hour
    out = []
    for t in range(first, last_observed_ms+1, hour):
        left = t-hour
        idx = int(np.searchsorted(stamps,left,side="right")-1)
        if idx < 0:
            continue
        cursor, area = left, 0.
        while idx+1 < len(stamps) and stamps[idx+1] < t:
            boundary = int(stamps[idx+1])
            area += values[idx]*(boundary-cursor)
            cursor,idx = boundary,idx+1
        area += values[idx]*(t-cursor)
        out.append(dict(time_ms=t,target=sign(area),reason="past_hour_inventory",
                        mean_inventory=area/hour))
    return out


def simulate_direction(signals, bars, funding, *, start_ms, end_ms, delay_seconds=60,
                       cost_bp=10, initial=10000, quantity_step=.001, bar_ms=MINUTE):
    """One-asset paper account. Delayed latest target wins at each bar open.

    Fixed quantity while its sign is unchanged. Initial inherited positions
    are not copied. At the sample right boundary, liquidate and charge costs.
    Current quantity step is an explicit approximation to historical rules.
    """
    bars = np.asarray(bars, float)
    times = bars[:, 0].astype(np.int64)
    assert bar_ms > 0 and np.all(np.diff(times) == bar_ms)
    assert np.all(np.isfinite(bars)) and np.all(bars[:, 1] > 0)
    left = int(np.searchsorted(times, start_ms // bar_ms * bar_ms))
    right_time = int(math.ceil(end_ms / bar_ms) * bar_ms)
    right = int(np.searchsorted(times, right_time))
    if left >= len(times) or right >= len(times) or right <= left or times[right] != right_time:
        raise ValueError("minute_prices_do_not_cover_sample")
    scheduled = {}
    dropped = 0
    for s in sorted(signals, key=lambda s:s["time_ms"]):
        execution = math.ceil((s["time_ms"] + delay_seconds * 1000) / bar_ms) * bar_ms
        if times[left] <= execution < times[right]:
            scheduled[execution] = s["target"]
        else:
            dropped += 1
    rate_marks = np.zeros(len(times))
    for payment in funding:
        stamp = int(payment["fundingTime"])
        j = np.searchsorted(times, stamp, side="left") - 1
        if 0 <= j < len(times)-1:
            rate_marks[j] += float(payment["fundingRate"]) * float(payment["markPrice"])
    equity, quantity, peak = float(initial), 0., float(initial)
    fees = funding_pnl = price_pnl = turnover = drawdown = 0.
    trades, points, active = [], [], 0
    c = cost_bp / 10000
    for t in range(left, right):
        price = bars[t, 1]
        target = scheduled.get(int(times[t]))
        if target is not None and target != sign(quantity):
            exit_notional = abs(quantity) * price
            notional = max(0., (equity - exit_notional*c) / (1+c)) if target else 0.
            units = math.floor(notional / price / quantity_step) * quantity_step
            new_quantity = target * units
            changed_notional = abs(new_quantity-quantity) * price
            cost = changed_notional*c
            equity -= cost
            fees += cost
            turnover += changed_notional
            trades.append(dict(time_ms=int(times[t]), old_quantity=quantity, quantity=new_quantity,
                               cost=cost, price=price, terminal=False))
            quantity = new_quantity
        peak = max(peak, equity)
        drawdown = max(drawdown, 1-equity/peak)
        active += quantity != 0
        pnl = quantity * (bars[t+1, 1] - price)
        carry = -quantity * rate_marks[t]
        equity += pnl + carry
        price_pnl += pnl
        funding_pnl += carry
        if t == right-1 and quantity:
            notional = abs(quantity) * bars[t+1, 1]
            cost = notional*c
            equity -= cost
            fees += cost
            turnover += notional
            trades.append(dict(time_ms=int(times[t+1]), old_quantity=quantity, quantity=0.,
                               cost=cost, price=bars[t+1, 1], terminal=True))
        peak = max(peak, equity)
        drawdown = max(drawdown, 1-equity/peak)
        if equity <= 0:
            raise ValueError("bankrupt_research_account")
        points.append(dict(time_ms=int(times[t+1]), equity=equity))
    assert math.isclose(equity-initial, price_pnl+funding_pnl-fees, abs_tol=1e-6)
    return dict(start_ms=int(times[left]), end_ms=int(times[right]), initial=initial,
                final_equity=equity, return_pct=(equity/initial-1)*100, mdd_pct=drawdown*100,
                price_pnl=price_pnl, funding_pnl=funding_pnl, costs=fees, turnover=turnover,
                order_count=len(trades), active_minutes=active*bar_ms/MINUTE, minutes=(right-left)*bar_ms/MINUTE,
                bar_duration_ms=bar_ms,
                delayed_signals_outside_sample=dropped, trades=trades, points=points)


def behavior_screen(fills, *, start, split, saturated, universe):
    train = [f for f in fills if start <= f["time"] < split]
    reconstructed = reconstruct(train)
    d = [e["duration_seconds"]/3600 for e in reconstructed["episodes"]]
    span = (max((f["time"] for f in train), default=0)-min((f["time"] for f in train), default=0))/86_400_000
    median = float(np.median(d)) if d else None
    changes = reconstructed["stats"].get("direction_changes",0)/((split-start)/86_400_000)
    coins = sorted({s["coin"] for s in reconstructed["states"]} & set(universe))
    reasons = []
    if saturated: reasons.append("response_saturated")
    if span < 14: reasons.append("training_span_under14d")
    if len(d) < 2: reasons.append("under2_completed_direction_intervals")
    if median is None or median < 6: reasons.append("median_direction_under6h")
    if changes > 1: reasons.append("over1_direction_change_per_day")
    if reconstructed["errors"] or reconstructed["stats"].get("cross_timestamp_gaps",0):
        reasons.append("training_position_chain_error")
    if not coins: reasons.append("no_training_mapped_asset")
    return dict(training_count=len(train),training_span_days=span,closed_direction_intervals=len(d),
                median_direction_hours=median,direction_changes_per_day=changes,
                mapped_training_assets=coins,reasons=reasons,eligible=not reasons)


def summarize_portfolio(runs, initial):
    times = np.array([p["time_ms"] for p in runs[0]["points"]])
    equities = np.zeros(len(times))
    for r in runs:
        assert np.array_equal(times,[p["time_ms"] for p in r["points"]])
        equities += np.asarray([p["equity"] for p in r["points"]])
    nav = np.r_[initial,equities]
    result = dict(initial=initial,final_equity=float(equities[-1]),return_pct=float((equities[-1]/initial-1)*100),
                  hourly_open_mdd_pct=float(np.max(1-nav/np.maximum.accumulate(nav))*100),
                  price_pnl=sum(r["price_pnl"] for r in runs),funding_pnl=sum(r["funding_pnl"] for r in runs),
                  costs=sum(r["costs"] for r in runs),orders=sum(r["order_count"] for r in runs),
                  turnover=sum(r["turnover"] for r in runs))
    assert abs(result["final_equity"]-initial-result["price_pnl"]-result["funding_pnl"]+result["costs"]) < 1e-5
    return result, times.tolist(), equities.tolist()


