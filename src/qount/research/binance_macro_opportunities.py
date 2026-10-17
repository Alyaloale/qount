"""Fixed causal opportunity attribution; overlapping events are not a portfolio."""
from __future__ import annotations

import bisect
import copy
import datetime as dt
import math
import statistics
from collections import Counter, defaultdict

from qount.research.binance_etf_leverage import feature_at, funding_reserve, replay
from qount.research.engine.perpetual import size
from qount.research_data.bars import aggregate, atr, iso, session, NY


def fractional_rules(data, *, relax_grid=True, relax_minimum=True):
    """Untradable diagnostic: relax only quantity grid/minimum quantity/notional."""
    result = {}
    for symbol, d in data.items():
        rule = copy.deepcopy(d["rule"])
        for f in rule["filters"]:
            if relax_grid and f["filterType"] in ("LOT_SIZE", "MARKET_LOT_SIZE"):
                f["stepSize"] = f["minQty"] = "0.0000000001"
            if relax_minimum and f["filterType"] == "MIN_NOTIONAL":
                f["notional"] = "0"
        result[symbol] = {**d, "rule": rule}
    return result


def cost_case(data, scenario, sides=None):
    if scenario != "double_cost":
        return data
    return {s: {**d, "funding": [{**r, "fundingRate": str(float(r["fundingRate"])*2)
            if r.get("rateType", "Regular") == "Regular" and (sides or {}).get(s, 1)*float(r["fundingRate"]) > 0
            else r["fundingRate"]} for r in d["funding"]]} for s, d in data.items()}


def fixed_fill_metrics(trade, order, funding, fee=0.0005, slip=0.0005):
    """Linear unit economics on a frozen entry/exit path and chosen quantity."""
    if trade.get("partial_exits"):
        raise ValueError("fixed_fill_metrics_requires_constant_quantity")
    q = order["quantity"]
    side = trade.get("side", 1)
    ratio = q/trade["quantity"]
    pnl = trade["net_pnl"]*ratio
    entry, exit_ = trade["entry_price"], trade["exit_price"]
    adverse_regular = sum(side*q*float(r["markPrice"])*float(r["fundingRate"])
                          for r in funding if trade["entry_time"]*1000 <= int(r["fundingTime"]) < trade["exit_time"]*1000
                          and r.get("rateType", "Regular") == "Regular" and side*float(r["fundingRate"]) > 0)
    raw_entry, raw_exit = entry/(1+side*slip), exit_/(1-side*slip)
    e2, x2 = raw_entry*(1+2*side*slip), raw_exit*(1-2*side*slip)
    doubled = side*q*(x2-e2)-2*fee*q*(e2+x2)+trade["funding"]*ratio-adverse_regular
    risk = order["stress_risk_usdt"]
    return {"quantity": q, "notional": q*entry, "net_pnl": pnl,
            "net_stress_r": pnl/risk, "fixed_path_double_cost_pnl": doubled,
            "fixed_path_double_cost_r": doubled/risk,
            "exit_time": trade["exit_time"], "exit_reason": trade["exit_reason"],
            "right_censored": trade["exit_reason"] == "end_of_sample"}


def trade_pnl_components(trade, *, fee, slip):
    """Reconcile a model fill into direction, execution costs and signed funding.

    Recovered raw prices are the model's fill references, not observed market
    quotes. This is attribution of a frozen trade, not a frictionless rerun.
    """
    side, q = trade.get("side", 1), trade["quantity"]
    if side not in (-1, 1) or not 0 <= slip < 1 or not 0 <= fee < 1 or q <= 0:
        raise ValueError("invalid_pnl_component_assumptions")
    entry, exit_ = trade["entry_price"], trade["exit_price"]
    raw_entry = entry/(1+side*slip)
    exits = [(r["quantity"], r["price"]) for r in trade.get("partial_exits", [])]
    remaining = q-sum(x[0] for x in exits)
    if remaining <= 0 or any(qty <= 0 for qty, _ in exits):
        raise ValueError("invalid_partial_exit_quantities")
    exits.append((remaining, exit_))
    direction = sum(side*qty*(price/(1-side*slip)-raw_entry) for qty, price in exits)
    execution = side*q*(entry-raw_entry)+sum(side*qty*(price/(1-side*slip)-price) for qty, price in exits)
    fees = (q*entry+sum(qty*price for qty, price in exits))*fee
    funding = trade["funding"]
    net = direction-execution-fees+funding
    if not math.isclose(net, trade["net_pnl"], rel_tol=1e-9, abs_tol=1e-8):
        raise ValueError("pnl_components_do_not_reconcile")
    return dict(raw_price_pnl=direction, slippage_cost=execution, fees=fees,
                net_funding=funding, net_pnl=net)


def native_horizon_components(order, data, days, *, fee, slip):
    """Paid native-contract labels from the SAME entry, without an exit rule.

    This is an unrealizable diagnostic when a stop/liquidation barrier is hit;
    its future endpoint/funding never enters sizing or admission. No maturity
    means no return label, even when an earlier strategy exit is already known.
    """
    if days not in (7, 21) or order.get("partial_exits"):
        raise ValueError("fixed_native_horizon_only")
    side, q, start = order.get("side", 1), order["quantity"], order["entry_time"]
    end = start+days*86400
    prices = {b.t:b for b in data["trade"]}
    marks = {b.t:b for b in data["mark"]}
    if start not in prices or start not in marks:
        raise ValueError("native_entry_missing")
    if end > max(prices):
        return dict(censored=True, planned_exit=end)
    times = list(range(start,end,3600))
    if end not in prices or any(t not in prices or t not in marks for t in times):
        raise ValueError("native_horizon_gap")
    entry = prices[start].o*(1+side*slip)
    if not math.isclose(entry, order["entry_price"], rel_tol=1e-12, abs_tol=1e-8):
        raise ValueError("native_entry_changed")
    paid, received = 0.0, 0.0
    regular, special = 0.0, 0.0
    for r in data["funding"]:
        if start*1000 <= int(r["fundingTime"]) < end*1000:
            payment = -side*q*float(r["markPrice"])*float(r["fundingRate"])
            paid += max(0,-payment)
            received += max(0,payment)
            if r.get("rateType","Regular")=="Regular":
                regular += payment
            else:
                special += payment
    exit_price = prices[end].o*(1-side*slip)
    funding = received-paid
    frozen = {**order, "exit_time":end, "exit_price":exit_price, "funding":funding,
              "net_pnl":side*q*(exit_price-entry)-q*(entry+exit_price)*fee+funding}
    components = trade_pnl_components(frozen,fee=fee,slip=slip)
    notional = q*entry
    # Static barriers only: this deliberately does NOT certify a full margin
    # path, funding collateral, dynamic trailing stop or actual liquidation.
    liq = entry*(1-side/order["leverage"])/(1-side*.01)
    stop_hits = [t for t in times if side*((prices[t].l if side==1 else prices[t].h)-order["initial_stop"]) <= 0]
    liq_hits = [t for t in times if side*((marks[t].l if side==1 else marks[t].h)-liq) <= 0]
    return dict(censored=False,entry_time=start,exit_time=end,quantity=q,notional=notional,
                components=components, on_notional={k:v/notional for k,v in components.items()},
                adverse_funding=paid,favorable_funding=received,
                regular_net_funding=regular,special_net_funding=special,
                initial_stop_first_touch=stop_hits[0] if stop_hits else None,
                static_liquidation_first_touch=liq_hits[0] if liq_hits else None,
                executable_constraint_set=False)


def opportunity_status(event, decision):
    if decision is None:
        return "halt_or_missing_decision"
    if decision["just_closed"]:
        return "exit_cooldown"
    held = decision["held_after_exits"]
    if held:
        return "occupied_"+held["engine"]
    opened = decision["opened"]
    if opened == {"symbol": event["symbol"], "engine": event["engine"]}:
        return "executed"
    if opened:
        return "same_time_core_priority" if event["engine"] == "tactical" and opened["engine"] == "core" else "another_candidate_selected"
    month = dt.datetime.fromtimestamp(event["time"], NY).strftime("%Y-%m")
    if event["engine"] == "core" and decision["core_month_before"] == month:
        return "monthly_core_quota"
    return "account_path_or_entry_filter"


def summarize_events(events, field="exact10"):
    accepted = [e for e in events if e["outcomes"].get(field)]
    closed = [e for e in accepted if not e["outcomes"][field]["right_censored"]]
    vals = [e["outcomes"][field]["net_stress_r"] for e in closed]
    doubles = [e["outcomes"][field]["fixed_path_double_cost_r"] for e in closed]
    return {"signals": len(events), "accepted": len(accepted), "closed": len(closed),
            "censored": len(accepted)-len(closed), "mean_net_stress_r": statistics.mean(vals) if vals else None,
            "median_net_stress_r": statistics.median(vals) if vals else None,
            "win_fraction": sum(x > 0 for x in vals)/len(vals) if vals else None,
            "mean_fixed_path_double_cost_r": statistics.mean(doubles) if doubles else None,
            "total_event_pnl_not_portfolio": sum(e["outcomes"][field]["net_pnl"] for e in closed),
            "distinct_signal_episodes": len({e["episode"] for e in accepted})}


def diagnose(data, features, baseline):
    timeline = [b.t for b in next(iter(data.values()))["trade"]]
    end = timeline[-1]+3600
    fractional = fractional_rules(data)
    vols = {}
    for s, d in data.items():
        daily = aggregate(d["trade"], 86400, 3600)
        values = atr(daily)
        vols[s] = [(b.t+86400, values[i]) for i, b in enumerate(daily) if values[i] is not None]
    trace = {row["time"]: row for row in baseline["decisions"]}
    events, previous, episode_count = [], {}, Counter()
    ordinal = -1
    for i, now in enumerate(timeline):
        info = session(now)
        if info is None or info[1] != 600:
            continue
        ordinal += 1
        fs = {s: feature_at(features[s], now) for s in data}
        if not all(f is not None and 0 < now-f["available"] <= 4*86400 for f in fs.values()):
            continue
        for s in data:
            f = fs[s]
            for engine in ("core", "tactical"):
                if not f["entry_"+engine]:
                    continue
                key = (s, engine)
                if previous.get(key) != ordinal-1:
                    episode_count[key] += 1
                previous[key] = ordinal
                event = {"id": f"{now}:{s}:{engine}", "time": now, "symbol": s, "engine": engine,
                         "rank": f["rank_"+engine], "state": f["state"],
                         "feature_available": f["available"],
                         "episode": f"{s}:{engine}:{episode_count[key]}", "outcomes": {}, "sizing": {}}
                event["baseline_status"] = opportunity_status(event, trace.get(now))
                vr = vols[s]
                vi = bisect.bisect_right([v[0] for v in vr], now)-1
                if vi < 0 or now-vr[vi][0] > 86400:
                    event["path_status"] = "atr_warmup"
                    events.append(event)
                    continue
                horizon = 720 if engine == "core" else 168
                reserve = funding_reserve(data[s]["funding"], now, horizon)
                if reserve is None:
                    event["path_status"] = "funding_unknown"
                    events.append(event)
                    continue
                reference = data[s]["trade"][i].o
                config = {"signal": {"initial_stop_atr": 2},
                          "cost_model": {"ordinary_friction_limit_fraction_of_stop": 0.2, "stop_gap_reserve": 0.01},
                          "sizing": {"exchange_leverage": {"maximum": 5},
                                     "notional_caps": {"effective_gross": min(3.0, f["gross_target"]),
                                                       "maximum_isolated_margin_fraction": 0.8}}}
                plans = {}
                for label, capital, d in (("exact10", 10, data), ("fractional10", 10, fractional), ("exact100", 100, data)):
                    order, reason = size(config, d[s]["rule"], reference, reference*1.0005, vr[vi][1],
                                         capital, 0.08*capital, reserve, 0.0005, 0.0005,
                                         data[s]["trade"][i-1].v*0.01)
                    event["sizing"][label] = {"status": reason, "order": order}
                    if order is not None:
                        plans[label] = order
                # Signal-quality path bypasses ONLY the forecast friction gate
                # and untradable quantity minima. Actual realized costs remain.
                cropped = {**fractional[s], "trade": [b for b in data[s]["trade"] if b.t < min(end, now+(horizon+1)*3600)],
                           "mark": [b for b in data[s]["mark"] if b.t < min(end, now+(horizon+1)*3600)]}
                bundle = replay({s: cropped}, {s: features[s]}, strategy="macro_hybrid", gross_cap=3,
                                risk_fraction=0.08, capital=10, account_controls=False,
                                forced_entry={"time": now, "symbol": s, "engine": engine, "ignore_friction_gate": True})
                if not bundle["trades"]:
                    event["path_status"] = "no_path:"+str(bundle["summary"]["rejections"])
                    events.append(event)
                    continue
                if len(bundle["trades"]) != 1:
                    raise AssertionError("isolated_opportunity_must_have_one_trade")
                t = bundle["trades"][0]
                event.update(path_status="available", exit_time=t["exit_time"], exit_reason=t["exit_reason"],
                             right_censored=t["exit_reason"] == "end_of_sample")
                # Same linear-perpetual path is valid across quantity-only sizing
                # controls: stop, trailing and isolated liquidation price do not
                # depend on q; account HALT/compounding deliberately excluded.
                for label, order in plans.items():
                    if not math.isclose(t["initial_stop"], order["initial_stop"], abs_tol=1e-8) or t["leverage"] != order["leverage"]:
                        raise AssertionError("quantity_counterfactual_changed_exit_mechanism")
                    event["outcomes"][label] = fixed_fill_metrics(t, order, data[s]["funding"])
                quality = dict(t, stress_risk_usdt=t["stress_risk_usdt"])
                event["outcomes"]["signal_only"] = fixed_fill_metrics(t, quality, data[s]["funding"])
                events.append(event)
    summary = {engine: {label: summarize_events([e for e in events if e["engine"] == engine], label)
                        for label in ("signal_only", "exact10", "fractional10", "exact100")}
               for engine in ("core", "tactical")}
    first_episode = {}
    for event in events:
        if event["outcomes"].get("signal_only"):
            first_episode.setdefault(event["episode"], event)
    summary["first_observable_per_episode"] = {
        engine: summarize_events([e for e in first_episode.values() if e["engine"] == engine], "signal_only")
        for engine in ("core", "tactical")}
    ranked = {}
    for e in events:
        if e["engine"] == "tactical" and e["outcomes"].get("exact10"):
            old = ranked.get(e["time"])
            if old is None or (-e["rank"], e["symbol"]) < (-old["rank"], old["symbol"]):
                ranked[e["time"]] = e
    grouped = defaultdict(list)
    for e in ranked.values():
        grouped[e["baseline_status"]].append(e)
    summary["ranked_tactical_occupancy"] = {k: summarize_events(v) for k, v in grouped.items()}
    summary["minimum_order_only"] = {
        engine: summarize_events([e for e in events if e["engine"] == engine and
                                 e["sizing"].get("exact10", {}).get("status") == "minimum_order" and
                                 e["outcomes"].get("fractional10")], "fractional10")
        for engine in ("core", "tactical")}
    return events, summary
