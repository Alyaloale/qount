"""Causal episode anchors shared by research and live startup reconstruction."""
from qount.strategies.macro_funding import feature_at
from qount.research_data.bars import session

def episode_confirmations(data, features, policy):
    """Observe current open and prior opportunities, never the current close.

    Episode identity is symbol plus setup on consecutive regular-session10AM
    decisions. The first observed contract open is immutable. Before an actual
    contract history exists there is no anchor or synthetic price.
    """
    if policy not in ("first_only", "no_chase"):
        raise ValueError("unknown_episode_policy")
    prices = {s: {b.t: b.o for b in d["trade"]} for s, d in data.items()}
    timeline = sorted({t for rows in prices.values() for t in rows})
    previous, result = {}, {}
    ordinal = -1
    for now in timeline:
        clock = session(now)
        if clock is None or clock[1] != 600:
            continue
        ordinal += 1
        fs = {s: feature_at(rows, now) for s, rows in features.items()}
        fresh = all(f is not None and 0 < now-f["available"] <= 4*86400 for f in fs.values())
        if not fresh:
            continue
        for s, f in fs.items():
            if not f["entry_tactical"] or now not in prices[s]:
                continue
            setup = f["tactical_setup"]
            last = previous.get(s)
            first = last is None or last["ordinal"] != ordinal-1 or last["setup"] != setup
            anchor_time = now if first else last["anchor_time"]
            anchor_price = prices[s][now] if first else last["anchor_price"]
            eligible = first if policy == "first_only" else prices[s][now] <= anchor_price+1e-12
            result[s, now] = dict(asof=now, eligible=eligible, setup=setup, first=first,
                anchor_time=anchor_time, anchor_price=anchor_price, current_price=prices[s][now],
                reason="episode_not_first" if policy == "first_only" else "episode_price_chase")
            previous[s] = dict(ordinal=ordinal, setup=setup, anchor_time=anchor_time, anchor_price=anchor_price)
    return result
