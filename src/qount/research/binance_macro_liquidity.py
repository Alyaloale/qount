"""Causal short-window capacity proxy; volume is not historical order-book depth."""
from qount.strategies.macro_liquidity import capacity_snapshot
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qount.research.binance_etf_leverage import feature_at, public_get
from qount.research.engine.perpetual import grid, size
from qount.research_data.bars import Bar, session




def candidate_clocks(data, features):
    clocks = []
    timeline = next(iter(data.values()))["trade"]
    for b in timeline:
        s = session(b.t)
        if s is None or s[1] != 600:
            continue
        fs = {symbol: feature_at(rows, b.t) for symbol, rows in features.items()}
        if not all(f is not None and 0 < b.t-f["available"] <= 4*86400 for f in fs.values()):
            continue
        clocks.extend((symbol, b.t) for symbol, f in fs.items() if f["entry_tactical"])
    return clocks


def load_capacity_contexts(clocks, cache: Path, download=False):
    """Fetch15 causal minutes, one publication-buffer minute and entry minute.

    The entry minute is retained for ex-post capacity diagnosis only. Snapshot
    construction excludes both it and the publication-buffer minute.
    """
    cache.mkdir(parents=True, exist_ok=True)

    def fetch(key):
        symbol, now = key
        path = cache/f"{symbol}-trade-1m-{now-16*60}-{now+60}.json"
        if not path.exists():
            if not download:
                raise FileNotFoundError(path)
            rows = public_get("/fapi/v1/klines", dict(symbol=symbol, interval="1m",
                              startTime=(now-16*60)*1000, endTime=(now+60)*1000-1, limit=1000))
            if not isinstance(rows, list):
                raise ValueError("invalid_public_capacity_response")
            with path.open("x") as f:
                f.write(json.dumps(rows, separators=(",", ":"))+"\n")
        raw = path.read_bytes()
        bars = [Bar(int(r[0])//1000, *(float(r[i]) for i in (1, 2, 3, 4)), float(r[5]), float(r[7]))
                for r in json.loads(raw)]
        if [b.t for b in bars] != list(range(now-16*60, now+60, 60)):
            raise ValueError("capacity_minute_grid_missing")
        snapshot = capacity_snapshot(bars, now)
        return key, snapshot, dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()), bars[-1].v

    contexts, sources, observed_entry_volume = {}, [], {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for key, snapshot, source, volume in pool.map(fetch, sorted(set(clocks))):
            if snapshot is not None:
                contexts[key] = snapshot
            sources.append(source)
            observed_entry_volume[key] = volume
    return contexts, sources, observed_entry_volume


def guarded_long_quote(rule, depth, now_ms, volatility, reserve, *, capital=10, risk_fraction=.20,
                       max_price_distance=.0025, depth_fraction=.25, gap_reserve=.03):
    """Risk geometry for a bounded IOC limit; never places an order.

    Displayed depth can disappear and IOC can fill partially or not at all.
    Signal eligibility, actual account leverage, native protection and exit
    execution are deliberately not certified by this read-only calculation.
    """
    base = dict(research_only=True, orders_authorized=False, signal_evaluated=False)
    if (not math.isfinite(capital) or capital <= 0 or not math.isfinite(risk_fraction)
            or not 0 < risk_fraction <= 1 or not math.isfinite(gap_reserve) or not 0 <= gap_reserve < 1):
        raise ValueError("invalid_quote_risk_budget")
    timestamp = depth.get("E", depth.get("T"))
    if timestamp is None or not -1000 <= now_ms-int(timestamp) <= 2000:
        return dict(base, status="stale_or_unknown_quote")
    if not 0 < depth_fraction <= 1 or not 0 < max_price_distance < 1:
        raise ValueError("invalid_quote_limits")
    if reserve is None or not math.isfinite(reserve) or reserve < 0 or not math.isfinite(volatility) or volatility <= 0:
        return dict(base, status="unknown_risk_inputs")
    asks = [(float(p), float(q)) for p, q in depth.get("asks", [])]
    bids = [(float(p), float(q)) for p, q in depth.get("bids", [])]
    if (not asks or not bids or asks != sorted(asks) or bids != sorted(bids, reverse=True)
            or any(not math.isfinite(p) or not math.isfinite(q) or p <= 0 or q < 0 for p, q in asks+bids)):
        return dict(base, status="invalid_book")
    ask, bid = asks[0][0], bids[0][0]
    if ask < bid:
        return dict(base, status="crossed_book")
    mid = (ask+bid)/2
    filters = {f["filterType"]: f for f in rule["filters"]}
    limit = grid(mid*(1+max_price_distance), filters["PRICE_FILTER"]["tickSize"])
    depth_cap = depth_fraction*sum(q for p, q in asks if p <= limit)
    info = dict(mid=mid, best_ask=ask, best_bid=bid, spread_bps=(ask-bid)/mid*10000,
                price_limit=limit, visible_depth_quantity_cap=depth_cap,
                quote_time=timestamp, maximum_price_distance=max_price_distance)
    if ask > limit or depth_cap <= 0:
        return dict(base, **info, status="insufficient_depth_within_price_limit")
    config = {"signal": {"initial_stop_atr": 2},
              "cost_model": {"ordinary_friction_limit_fraction_of_stop": .2, "stop_gap_reserve": gap_reserve},
              "sizing": {"exchange_leverage": {"maximum": 50},
                         "notional_caps": {"effective_gross": 20, "maximum_isolated_margin_fraction": .8}}}
    order, reason = size(config, rule, mid, limit, volatility, capital, capital*risk_fraction,
                         reserve, .0005, max_price_distance, depth_cap)
    if order is None:
        return dict(base, **info, status=reason)
    return dict(base, **info, status="research_quote_only", quantity=order["quantity"],
                order_type="LIMIT", time_in_force="IOC", worst_price_stress_risk=order["stress_risk_usdt"],
                risk_budget=capital*risk_fraction, leverage_assumption=order["leverage"],
                notional_at_limit=order["notional_usdt"], isolated_margin_assumption=order["margin_usdt"])
