"""Small-account ETF perpetual leverage experiment; public data, never orders.

Fixed hypothesis: a simple 120-session equity trend/momentum signal can retain
net value after perpetual funding and discrete sizing. Gross caps and pressure
risk budgets are separate experimental factors. This is consumed-history research.
"""
from __future__ import annotations

from qount.strategies.macro_funding import feature_at, funding_reserve
from qount.research_data.binance_history import public_get, load_inputs
import bisect
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qount.research.engine.perpetual import grid, size
from qount.research.binance_macro_funding_lease import resize_lease, review_lease
from qount.research_data.bars import Bar, aggregate, atr, funding_budget, iso, session, NY
from qount.research_data.archives import archive_rows

SYMBOLS = ("SPYUSDT", "QQQUSDT")
BASE = "https://fapi.binance.com"






def equity_features(root: Path):
    """ETF closes become available after the actual New York session close."""
    result, inputs = {}, []
    for symbol in SYMBOLS:
        path = root / (symbol.removesuffix("USDT") + "_daily.csv")
        raw = path.read_bytes()
        inputs.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        rows = list(csv.DictReader(raw.decode().splitlines()))
        dates = [r["Date"] for r in rows]
        if dates != sorted(set(dates)):
            raise ValueError("equity_date_order")
        closes = [float(r["Adj Close"]) for r in rows]
        values = []
        for i in range(120, len(rows)):
            date = dt.date.fromisoformat(dates[i])
            local = dt.datetime.combine(date, dt.time(16), NY)
            # Only 2026 rows are consumed by this experiment; known early closes
            # are conservatively available at 16:00 as well.
            ma = statistics.mean(closes[i-119:i+1])
            mom = closes[i]/closes[i-120]-1
            values.append({"available": int(local.timestamp()), "date": dates[i],
                           "close": closes[i], "ma120": ma, "momentum120": mom,
                           "eligible": closes[i] > ma and mom > 0})
        result[symbol] = values
    return result, inputs




FUNDING_POLICIES = ("absolute_peak", "debit_peak", "debit_stress")




def replay(data, features, *, gross_cap=1.0, risk_fraction=0.03,
           fee=0.0005, slip=0.0005, stop_gap=0.0, capital=10.0,
           strategy="momentum120", hold_symbol=None, max_hold_hours=168,
           forced_entry=None, account_controls=True, routing="core_first", trace=False,
           funding_policy="absolute_peak", exchange_leverage=5, liquidation_stop_multiple=3.0,
           entry_liquidity_caps=None, sizing_gap_reserve=0.01,
           entry_confirmations=None, tactical_max_hold_hours=168,
           friction_limit_fraction_of_stop=0.2, tactical_setup_policies=None,
           entry_end_exclusive=None, funding_lease_hours=None, funding_lease_budget="cost",
           allow_partial_histories=False, funding_lease_resize=False, lease_exit_liquidity_caps=None,
           capital_flows=None):
    """Hourly pessimistic stop fills, signed funding, isolated margin proxy.

    No intrabar trailing updates. A decision at 10:00 ET uses only prior completed
    ETF sessions and the prior UTC day's contract ATR14. Native stop reliability,
    historical filters/brackets and historical order books remain unverified.
    """
    if funding_policy not in FUNDING_POLICIES:
        raise ValueError("unknown_funding_policy")
    if not isinstance(exchange_leverage, int) or not 1 <= exchange_leverage <= 100:
        raise ValueError("invalid_exchange_leverage")
    if not math.isfinite(sizing_gap_reserve) or not 0 <= sizing_gap_reserve < 1:
        raise ValueError("invalid_sizing_gap_reserve")
    if entry_liquidity_caps is not None and strategy != "macro_tactical":
        raise ValueError("liquidity_caps_require_tactical_only")
    if entry_confirmations is not None and strategy != "macro_tactical":
        raise ValueError("confirmations_require_tactical_only")
    if not isinstance(tactical_max_hold_hours, int) or not 1 <= tactical_max_hold_hours <= 720:
        raise ValueError("invalid_tactical_horizon")
    if tactical_max_hold_hours != 168 and strategy != "macro_tactical":
        raise ValueError("custom_horizon_requires_tactical_only")
    if not math.isfinite(friction_limit_fraction_of_stop) or not 0 < friction_limit_fraction_of_stop <= 1:
        raise ValueError("invalid_friction_limit")
    if friction_limit_fraction_of_stop != .2 and strategy != "macro_tactical":
        raise ValueError("custom_friction_limit_requires_tactical_only")
    if tactical_setup_policies is not None:
        if strategy != "macro_tactical" or set(tactical_setup_policies) != {"breakout", "pullback", "mean_reversion"}:
            raise ValueError("setup_policies_require_all_tactical_setups")
        for policy in tactical_setup_policies.values():
            if (policy.get("hold_feature") not in ("hold_tactical", "hold_structural")
                    or not isinstance(policy.get("max_hold_hours"), int)
                    or not 1 <= policy["max_hold_hours"] <= 720):
                raise ValueError("invalid_setup_policy")
    if entry_end_exclusive is not None and (strategy != "macro_tactical" or not isinstance(entry_end_exclusive, int)):
        raise ValueError("entry_cutoff_requires_tactical_timestamp")
    if funding_lease_hours is not None and (strategy != "macro_tactical" or tactical_setup_policies is None
            or not isinstance(funding_lease_hours, int) or not 1 <= funding_lease_hours <= 720):
        raise ValueError("funding_lease_requires_tactical_setup_policy")
    if funding_lease_budget not in ("cost", "risk") or (funding_lease_budget != "cost" and funding_lease_hours is None):
        raise ValueError("invalid_funding_lease_budget")
    if allow_partial_histories and strategy != "macro_tactical":
        raise ValueError("partial_histories_require_tactical_only")
    if funding_lease_resize and (funding_lease_hours is None or funding_lease_budget != "risk" or lease_exit_liquidity_caps is None):
        raise ValueError("lease_resize_requires_risk_lease_and_exit_capacity")
    if lease_exit_liquidity_caps is not None and not funding_lease_resize:
        raise ValueError("lease_exit_capacity_requires_resize")
    config = {"signal": {"initial_stop_atr": 2},
              "cost_model": {"ordinary_friction_limit_fraction_of_stop": friction_limit_fraction_of_stop,
                             "stop_gap_reserve": sizing_gap_reserve},
              "sizing": {"exchange_leverage": {"maximum": exchange_leverage},
                         "notional_caps": {"effective_gross": gross_cap,
                                           "maximum_isolated_margin_fraction": 0.8}}}
    if forced_entry and forced_entry.get("ignore_friction_gate"):
        if account_controls:
            raise ValueError("signal_quality_only_requires_isolated_event_mode")
        config["cost_model"]["ordinary_friction_limit_fraction_of_stop"] = math.inf
    symbols = tuple(data)
    macro = strategy.startswith("macro_")
    timeline = [b.t for b in data[symbols[0]]["trade"]]
    hour_indices = {}
    for s, d in data.items():
        times = [b.t for b in d["trade"]]
        if (times != sorted(set(times)) or times != [b.t for b in d["mark"]]
                or any(b-a != 3600 for a, b in zip(times, times[1:]))):
            raise ValueError("contract_bar_clock_mismatch")
        if not allow_partial_histories and times != timeline:
            raise ValueError("partial_histories_require_opt_in")
        hour_indices[s] = {t: j for j, t in enumerate(times)}
    if allow_partial_histories:
        timeline = sorted({t for rows in hour_indices.values() for t in rows})
    start, end = timeline[0], timeline[-1]+3600
    flows_by_time = {}
    if capital_flows:
        if strategy != "macro_tactical":
            raise ValueError("capital_flows_require_tactical_replay")
        for flow in capital_flows:
            when, amount = flow["time"], flow["amount"]
            if (isinstance(when, bool) or not isinstance(when, int) or when not in timeline
                    or when in flows_by_time or isinstance(amount, bool)
                    or not math.isfinite(amount) or amount == 0):
                raise ValueError("invalid_replay_capital_flow")
            flows_by_time[when] = amount
    units = capital
    applied_flows = []
    daily_vol, funding_hours = {}, {}
    for s, d in data.items():
        daily = aggregate(d["trade"], 86400, 3600)
        vs = atr(daily)
        daily_vol[s] = [(b.t+86400, vs[i]) for i, b in enumerate(daily) if vs[i] is not None]
        grouped = {}
        for row in d["funding"]:
            grouped.setdefault(int(row["fundingTime"])//3600000*3600, []).append(row)
        funding_hours[s] = grouped
    equity = peak = capital
    pos = None
    halted = None
    trades, curve, rejected = [], [], Counter()
    total_fee = total_funding = total_slip = 0.0
    max_dd = intrabar_dd = max_gross = 0.0
    invested = 0
    last_core_month = None
    decisions = []
    if routing not in ("core_first", "tactical_first", "tactical_preempt", "exit_handover"):
        raise ValueError("unknown_entry_routing")

    def nav(price):
        return equity if pos is None else equity+pos.get("side", 1)*pos["quantity"]*(price-pos["entry_price"])-pos["quantity"]*price*fee

    def close(now, raw_price, reason):
        nonlocal equity, pos, total_fee, total_slip
        side = pos.get("side", 1)
        price = raw_price*(1-side*slip)
        exit_fee = pos["quantity"]*price*fee
        equity += side*pos["quantity"]*(price-pos["entry_price"])-exit_fee
        total_fee += exit_fee
        total_slip += side*pos["quantity"]*(raw_price-price)
        trade = {**pos, "exit_time": now, "exit_price": price, "exit_reason": reason,
                 "net_pnl": side*pos["quantity"]*(price-pos["entry_price"])-pos["entry_fee"]-exit_fee+pos["funding"]}
        if pos.get("partial_exits"):
            trade.update(quantity=pos["initial_quantity"], remaining_quantity=pos["quantity"],
                         net_pnl=trade["net_pnl"]+pos["partial_realized_pnl"])
        trades.append(trade)
        pos = None

    for i, now in enumerate(timeline):
        ix = {s: hour_indices[s].get(now) for s in symbols} if allow_partial_histories else dict.fromkeys(symbols, i)
        if pos is not None and ix[pos["symbol"]] is None:
            raise ValueError("held_contract_bar_missing")
        if now in flows_by_time:
            # Explicit reconciled simulation inputs, never exchange transfers.
            # A held-position cashflow requires separate margin/ownership
            # reconciliation; do not silently treat marked profit as cash.
            if pos is not None:
                raise ValueError("capital_flow_requires_flat_reconciled_state")
            amount = flows_by_time[now]
            if equity <= 0 or equity+amount <= 0:
                raise ValueError("capital_flow_exhausts_equity")
            unit_nav = equity/units
            previous_units = units
            units += amount/unit_nav
            equity += amount
            peak *= units/previous_units
            applied_flows.append(dict(time=now,amount=amount,equity=equity,units=units,unit_nav=unit_nav))
        just_closed = False
        preempted_target = None
        before = {"symbol": pos["symbol"], "engine": pos.get("engine")} if pos else None
        core_month_before = last_core_month
        if pos is not None and now >= pos.get("funding_exit_due", math.inf):
            close(now, data[pos["symbol"]]["trade"][ix[pos["symbol"]]].o, "funding_cost_exit")
            just_closed = True
        # The funding reserve covers the chosen holding horizon. Expiry must not wait
        # through a holiday/weekend for another regular-session decision.
        if pos is not None and strategy != "hold" and now-pos["entry_time"] >= pos.get("max_hold_hours", max_hold_hours)*3600:
            close(now, data[pos["symbol"]]["trade"][ix[pos["symbol"]]].o, "seven_day_exit" if not macro else "time_exit")
            just_closed = True
        if pos is not None and now >= pos.get("funding_lease_deadline", math.inf):
            s = pos["symbol"]
            current = feature_at(features[s], now)
            eligible = (current is not None and 0 < now-current["available"] <= 4*86400
                        and current[pos["hold_feature"]])
            remaining = (pos["entry_time"]+pos["max_hold_hours"]*3600-now)//3600
            hours = min(pos["funding_lease_hours"], remaining)
            reserve = funding_reserve(data[s]["funding"], now, hours, funding_policy, pos.get("side", 1))
            review = review_lease(pos, now=now, price=data[s]["trade"][ix[s]].o,
                                  equity=nav(data[s]["mark"][ix[s]].o), cash=equity,
                                  reserve=reserve, hours=hours, eligible=eligible,
                                  fee=fee, slip=slip, risk_fraction=risk_fraction, gap=sizing_gap_reserve)
            pos["funding_lease_reviews"].append(review)
            if not review["allowed"] and funding_lease_resize:
                context = lease_exit_liquidity_caps.get((s, now))
                if context is not None and context["asof"] > now-60:
                    raise ValueError("future_lease_exit_capacity")
                if context is None or context["asof"] < now-120:
                    plan = dict(allowed=False, reason="resize_liquidity_unknown")
                else:
                    cap = context["quantity_cap"]
                    if not math.isfinite(cap) or cap < 0:
                        raise ValueError("invalid_lease_exit_capacity")
                    plan = resize_lease(pos, data[s]["rule"], now=now, price=data[s]["trade"][ix[s]].o,
                        mark_price=data[s]["mark"][ix[s]].o, cash=equity, reserve=reserve, hours=hours,
                        eligible=eligible, fee=fee, slip=slip, risk_fraction=risk_fraction, gap=sizing_gap_reserve,
                        liquidity=min(cap, data[s]["trade"][ix[s]-1].v*.01))
                review["resize_attempt"] = plan
                if plan["allowed"]:
                    pos.setdefault("initial_quantity", pos["quantity"])
                    pos.setdefault("initial_margin_usdt", pos["margin_usdt"])
                    raw = data[s]["trade"][ix[s]].o
                    pos.setdefault("partial_exits", []).append(dict(time=now, quantity=plan["removed_quantity"],
                        raw_price=raw, price=plan["exit_price"], fee=plan["exit_fee"],
                        remaining_quantity=plan["quantity"], realized_pnl=plan["realized_pnl"],
                        liquidity=dict(context), partial_risk_spent_usdt=plan["partial_risk_spent_usdt"]))
                    pos["partial_realized_pnl"] = pos.get("partial_realized_pnl", 0)+plan["realized_pnl"]
                    pos["quantity"], pos["margin_usdt"] = plan["quantity"], plan["margin_after"]
                    pos["partial_risk_spent_usdt"] = plan["partial_risk_spent_usdt"]
                    equity = plan["cash_after"]
                    total_fee += plan["exit_fee"]
                    total_slip += pos.get("side", 1)*plan["removed_quantity"]*(raw-plan["exit_price"])
                    review = {**plan["review"], "phase": "after_reduction"}
                    pos["funding_lease_reviews"].append(review)
            if review["allowed"]:
                pos["funding_lease_deadline"] = now+hours*3600
            else:
                close(now, data[s]["trade"][ix[s]].o, review["reason"])
                just_closed = True
        # Decisions use no prices or volumes from the hour being entered.
        info = session(now)
        decision = info is not None and info[1] == 600
        if decision and not halted:
            fs = {s: feature_at(features[s], now) for s in symbols}
            fresh = all(f is not None and 0 < now-f["available"] <= 4*86400 for f in fs.values())
            if not fresh:
                rejected["stale_equity_features"] += 1
            if pos is not None:
                s = pos["symbol"]
                # Buy/hold controls have no signal exits or stop; account HALT
                # and liquidation handling remain identical to the candidate.
                off = strategy != "hold" and (not fresh or (
                    not fs[s][pos.get("hold_feature", "hold_"+pos["engine"])] if macro else
                    not fs["SPYUSDT"]["eligible"] or not fs[s]["eligible"]))
                if off:
                    close(now, data[s]["trade"][ix[s]].o, "trend_off")
                    just_closed = True
            if macro and fresh and pos is not None and pos["engine"] == "core" and routing == "tactical_preempt":
                old_price = data[pos["symbol"]]["trade"][ix[pos["symbol"]]].o*(1-slip)
                flat_equity = equity+pos["quantity"]*(old_price-pos["entry_price"])-pos["quantity"]*old_price*fee
                downshift = 0.5 if flat_equity <= 0.9*peak else 1.0
                budget = min(risk_fraction*flat_equity*downshift, max(0, flat_equity-0.8*peak))
                candidates = sorted((s for s in symbols if s != pos["symbol"] and fs[s]["entry_tactical"]),
                                    key=lambda s: (-fs[s]["rank_tactical"], s))
                # Confirm a replacement can execute BEFORE paying to leave core.
                # No future payoff enters this decision; both fills pay costs.
                for s in candidates:
                    volrows = daily_vol[s]
                    vi = bisect.bisect_right([v[0] for v in volrows], now)-1
                    reserve = funding_reserve(data[s]["funding"], now, 168, funding_policy)
                    if vi < 0 or now-volrows[vi][0] > 86400 or reserve is None:
                        continue
                    config["sizing"]["notional_caps"]["effective_gross"] = min(gross_cap, fs[s]["gross_target"])*downshift
                    order, _ = size(config, data[s]["rule"], data[s]["trade"][ix[s]].o,
                                    data[s]["trade"][ix[s]].o*(1+slip), volrows[vi][1], flat_equity,
                                    budget, reserve, fee, slip, data[s]["trade"][ix[s]-1].v*0.01)
                    if order is not None:
                        close(now, data[pos["symbol"]]["trade"][ix[pos["symbol"]]].o, "tactical_preempt")
                        preempted_target = (s, "tactical")
                        break
            held_after_exits = {"symbol": pos["symbol"], "engine": pos.get("engine")} if pos else None
            entry_clock = ((forced_entry is None or now == forced_entry["time"])
                           and (entry_end_exclusive is None or now < entry_end_exclusive))
            handover = just_closed and routing == "exit_handover"
            if pos is None and (not just_closed or handover) and fresh and entry_clock:
                if macro:
                    month = dt.datetime.fromtimestamp(now, NY).strftime("%Y-%m")
                    core = (strategy in ("macro_core", "macro_hybrid") and month != last_core_month and not handover)
                    tactical = strategy in ("macro_tactical", "macro_hybrid")
                    proposals = []
                    for s in symbols:
                        if core and fs[s]["entry_core"]:
                            proposals.append((s, "core"))
                        if tactical and fs[s]["entry_tactical"] and not (handover and before and s == before["symbol"]):
                            proposals.append((s, "tactical"))
                    preferred = "core" if routing == "core_first" else "tactical"
                    proposals.sort(key=lambda x: (x[1] != preferred, -fs[x[0]]["rank_"+x[1]], x[0]))
                    if preempted_target is not None:
                        proposals = [preempted_target]
                    if forced_entry is not None:
                        target, engine = forced_entry["symbol"], forced_entry["engine"]
                        if target not in fs or engine not in ("core", "tactical") or not fs[target]["entry_"+engine]:
                            raise ValueError("forced_entry_must_be_an_existing_causal_signal")
                        proposals = [(target, engine)]
                else:
                    eligible = ([hold_symbol] if strategy == "hold" else
                                sorted((s for s in symbols if fs[s]["eligible"] and fs["SPYUSDT"]["eligible"]),
                                       key=lambda s: (-fs[s]["momentum120"], s)))
                    proposals = [(s, None) for s in eligible]
                if not proposals:
                    rejected["regime_off"] += 1
                for s, engine in proposals:
                    if ix[s] is None:
                        rejected["contract_unavailable"] += 1
                        continue
                    if entry_confirmations is not None:
                        confirmation = entry_confirmations.get((s, now))
                        if confirmation is None or confirmation["asof"] < now-3600:
                            rejected["native_confirmation_unknown"] += 1
                            continue
                        if confirmation["asof"] > now:
                            raise ValueError("future_native_confirmation")
                        if confirmation["eligible"] is not True:
                            rejected[confirmation.get("reason", "native_confirmation_off")] += 1
                            continue
                    volrows = daily_vol[s]
                    vi = bisect.bisect_right([v[0] for v in volrows], now)-1
                    if vi < 0 or now-volrows[vi][0] > 86400:
                        rejected["atr_warmup"] += 1
                        continue
                    setup_policy = None
                    if tactical_setup_policies is not None:
                        setup_policy = tactical_setup_policies[fs[s]["tactical_setup"]]
                    horizon = (setup_policy["max_hold_hours"] if setup_policy is not None else
                               (720 if engine == "core" else tactical_max_hold_hours) if macro else max_hold_hours)
                    side = fs[s].get("side", 1)
                    lease = (funding_lease_hours if funding_lease_hours is not None
                             and fs[s]["tactical_setup"] == "mean_reversion" and horizon > funding_lease_hours else None)
                    reserve_hours = min(horizon, lease) if lease is not None else horizon
                    reserve = funding_reserve(data[s]["funding"], now, reserve_hours, funding_policy, side)
                    if reserve is None:
                        rejected["funding_unknown"] += 1
                        continue
                    b = data[s]["trade"][ix[s]]
                    liquidity = data[s]["trade"][ix[s]-1].v*0.01
                    liquidity_context = None
                    if entry_liquidity_caps is not None:
                        liquidity_context = entry_liquidity_caps.get((s, now))
                        if liquidity_context is None:
                            rejected["liquidity_unknown"] += 1
                            continue
                        if liquidity_context["asof"] > now-60:
                            raise ValueError("future_liquidity_context")
                        if liquidity_context["asof"] < now-120:
                            rejected["liquidity_stale"] += 1
                            continue
                        cap = liquidity_context["quantity_cap"]
                        if not math.isfinite(cap) or cap < 0:
                            raise ValueError("invalid_liquidity_cap")
                        if cap == 0:
                            rejected["liquidity_zero"] += 1
                            continue
                        liquidity = min(liquidity, cap)
                    price = b.o*(1+side*slip)
                    current_equity = equity
                    downshift = 0.5 if account_controls and macro and current_equity <= 0.9*peak else 1.0
                    available = risk_fraction*equity*downshift
                    if account_controls:
                        available = min(available, max(0, equity-0.8*peak))
                    if macro:
                        config["sizing"]["notional_caps"]["effective_gross"] = min(gross_cap, fs[s]["gross_target"])*downshift
                    if strategy == "hold":
                        filters = {f["filterType"]: f for f in data[s]["rule"]["filters"]}
                        q = grid(min(gross_cap*equity/price, equity/(price*(0.2+fee)),
                                     data[s]["trade"][ix[s]-1].v*0.01), filters["LOT_SIZE"]["stepSize"])
                        if q < float(filters["LOT_SIZE"]["minQty"]) or q*price < float(filters["MIN_NOTIONAL"]["notional"]):
                            rejected["minimum_order"] += 1
                            continue
                        order = {"quantity": q, "entry_price": price, "initial_stop": 0.0,
                                 "stop": 0.0, "notional_usdt": q*price, "leverage": 5,
                                 "stress_risk_usdt": None, "risk_budget_usdt": None}
                    else:
                        order, reason = size(config, data[s]["rule"], b.o, price,
                                             volrows[vi][1], equity, available, reserve,
                                             fee, slip, liquidity,
                                             side=side, liquidation_stop_multiple=liquidation_stop_multiple)
                        if order is None:
                            rejected[reason] += 1
                            continue
                    q = order["quantity"]
                    entry_fee = q*price*fee
                    equity -= entry_fee
                    total_fee += entry_fee
                    total_slip += side*q*(price-b.o)
                    pos = {**order, "symbol": s, "entry_time": now, "feature_available": fs[s]["available"],
                           "feature_date": fs[s]["date"], "equity_before_entry": equity+entry_fee,
                           "entry_fee": entry_fee, "funding": 0.0,
                           "structural_r": side*(price-order["initial_stop"]), "highest_close": price}
                    if side == -1:
                        pos["side"] = -1
                    if liquidity_context is not None:
                        pos["entry_liquidity"] = dict(liquidity_context)
                    if sizing_gap_reserve != .01:
                        pos["sizing_gap_reserve"] = sizing_gap_reserve
                    if setup_policy is not None:
                        pos.update(tactical_setup=fs[s]["tactical_setup"], hold_feature=setup_policy["hold_feature"])
                    if lease is not None:
                        distance = side*(price-order["initial_stop"])/price
                        cost_cap = q*price*max(0, friction_limit_fraction_of_stop*distance-2*(fee+slip))
                        if funding_lease_budget == "risk":
                            base_risk = order["stress_risk_usdt"]-q*price*reserve
                            cost_cap = max(0, order["risk_budget_usdt"]-base_risk)
                        pos.update(funding_reserve_hours=reserve_hours, funding_lease_hours=lease,
                                   funding_reserve_fraction=reserve, funding_lease_budget=funding_lease_budget,
                                   funding_lease_deadline=now+lease*3600,
                                   funding_cost_cap_usdt=cost_cap,
                                   funding_adverse_paid=0.0, funding_lease_reviews=[])
                    if macro:
                        pos.update(engine=engine, state=fs[s]["state"], max_hold_hours=horizon,
                                   gross_target=config["sizing"]["notional_caps"]["effective_gross"])
                        if engine == "core":
                            last_core_month = month
                    break
            if trace:
                decisions.append({"time": now, "position_before": before,
                                  "held_after_exits": held_after_exits,
                                  "just_closed": just_closed, "fresh": fresh,
                                  "core_month_before": core_month_before,
                                  "opened": {"symbol": pos["symbol"], "engine": pos.get("engine")}
                                  if pos is not None and pos["entry_time"] == now else None})
        if pos is not None:
            s, q = pos["symbol"], pos["quantity"]
            side = pos.get("side", 1)
            b, m = data[s]["trade"][ix[s]], data[s]["mark"][ix[s]]
            invested += 1
            max_gross = max(max_gross, q*m.o/max(nav(m.o), 1e-12))
            # Account-bracket proxy: 1% maintenance, 5x isolated setting.
            liquidation = pos["entry_price"]*(1-side/pos["leverage"])/(1-side*0.01)
            stopped = (b.l <= pos["stop"] if side == 1 else b.h >= pos["stop"]) if strategy != "hold" else False
            liquidated = m.l <= liquidation if side == 1 else m.h >= liquidation
            for row in funding_hours[s].get(now, []):
                ftime = int(row["fundingTime"])
                if ftime < pos["entry_time"]*1000:
                    continue
                payment = -side*q*float(row["markPrice"])*float(row["fundingRate"])
                # Stop/funding ordering inside an hourly bar is unknown: charge
                # adverse funding, omit favorable credit in a touched-stop hour.
                if (stopped or liquidated) and payment > 0:
                    continue
                equity += payment
                pos["funding"] += payment
                total_funding += payment
                if "funding_adverse_paid" in pos:
                    pos["funding_adverse_paid"] += max(0, -payment)
            if ("funding_adverse_paid" in pos
                    and pos["funding_adverse_paid"] > pos["funding_cost_cap_usdt"]+1e-9):
                # The current hour's settlement is only known after it occurs.
                # Schedule the next hourly open; do not fill retrospectively.
                pos["funding_exit_due"] = now+3600
            adverse_mark = m.l if side == 1 else m.h
            worst_price = ((max(m.l, pos["stop"]*(1-stop_gap)) if side == 1 else
                            min(m.h, pos["stop"]*(1+stop_gap))) if stopped and not liquidated else adverse_mark)
            intrabar_dd = max(intrabar_dd, 1-nav(worst_price)/peak)
            if liquidated:
                close(now+3600, min(b.o, liquidation) if side == 1 else max(b.o, liquidation), "liquidation_proxy")
                halted = "liquidation_proxy"
            elif stopped:
                close(now+3600, (min(b.o, pos["stop"]) if side == 1 else max(b.o, pos["stop"]))*(1-side*stop_gap), "stop")
            elif account_controls and nav(adverse_mark) <= 0.8*peak:
                close(now+3600, b.l if side == 1 else b.h, "drawdown_halt")
                halted = "drawdown_halt"
            elif strategy != "hold":
                from qount.strategies.macro_1atr import trailing_update
                volrows = daily_vol[s]
                vi = bisect.bisect_right([v[0] for v in volrows], now+3600)-1
                tick = next(f["tickSize"] for f in data[s]["rule"]["filters"] if f["filterType"] == "PRICE_FILTER")
                pos, trailing_exit = trailing_update(pos, b.c, volrows[vi][1] if vi >= 0 else None, tick)
                if trailing_exit:
                    close(now+3600, b.c, trailing_exit)

        value = equity if pos is None else nav(data[pos["symbol"]]["mark"][ix[pos["symbol"]]].c)
        peak = max(peak, value)
        max_dd = max(max_dd, 1-value/peak)
        if account_controls and value <= 0.8*peak:
            halted = halted or "drawdown_halt"
        curve.append({"time": now+3600, "equity": value})
        if flows_by_time:
            curve[-1]["unit_nav"] = value/units
    if pos is not None:
        close(end, data[pos["symbol"]]["trade"][-1].c, "end_of_sample")
        curve[-1]["equity"] = equity
        if flows_by_time:
            curve[-1]["unit_nav"] = equity/units
        max_dd = max(max_dd, 1-equity/peak)
    net_flows = sum(f["amount"] for f in applied_flows)
    if not math.isclose(capital+net_flows+sum(t["net_pnl"] for t in trades), equity, abs_tol=1e-8):
        raise AssertionError("cash_trade_reconciliation")
    if any(t["feature_available"] >= t["entry_time"] for t in trades):
        raise AssertionError("feature_time_leakage")
    months = {}
    prev = 1.0 if flows_by_time else capital
    for row in curve:
        month = iso(row["time"]-1)[:7]
        performance_value = row["unit_nav"] if flows_by_time else row["equity"]
        months.setdefault(month, {"start": prev})["end"] = performance_value
        prev = performance_value
    wins = sorted((t["net_pnl"] for t in trades if t["net_pnl"] > 0), reverse=True)
    summary = {"strategy": strategy if strategy != "hold" else "hold_"+hold_symbol,
               "gross_cap": gross_cap, "risk_fraction": risk_fraction if strategy != "hold" else None,
               "initial_equity": capital, "final_equity": equity, "net_return": equity/units-1 if flows_by_time else equity/capital-1,
               "max_drawdown": max_dd, "intrahour_drawdown_bound": max(intrabar_dd, max_dd),
               "trade_count": len(trades), "fees": total_fee, "funding": total_funding,
               "slippage_estimate": total_slip, "maximum_observed_gross": max_gross,
               "cash_fraction": 1-invested/len(timeline), "halt": halted,
               "rejections": dict(rejected), "top_two_winner_pnl": sum(wins[:2]),
               "monthly_returns": {m: v["end"]/v["start"]-1 for m, v in months.items()}}
    result = {"summary": summary, "trades": trades, "curve": curve}
    if flows_by_time:
        summary.update(return_basis="unit_nav",net_external_flows=net_flows,
                       deposits=sum(max(0,f["amount"]) for f in applied_flows),
                       withdrawals=sum(max(0,-f["amount"]) for f in applied_flows),
                       strategy_pnl=equity-capital-net_flows,final_units=units)
        result["capital_flows"] = applied_flows
    if trace:
        result["decisions"] = decisions
    return result
