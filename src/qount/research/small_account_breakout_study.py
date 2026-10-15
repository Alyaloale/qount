"""Continuous development and event-grouped mechanism diagnostics, never orders."""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from pathlib import Path

from qount.research.small_account_breakout import (
    MarketData, Signal, aggregate, generate_signals, iso, load_data, session, parse_bars, simulate, NY,
)
from qount.research.small_account_breakout_data import timestamp, sha


def seconds(value: str) -> int:
    return int(dt.datetime.fromisoformat(value).timestamp())


def load_continuous(cache: Path, config: dict, study: dict, *, allow_hourly_mismatch: bool = False) -> MarketData:
    start,end = timestamp(study["development_start"]),timestamp(study["development_end_exclusive"])
    manifest = json.loads((cache/"continuous-manifest.json").read_text())
    for row in manifest["files"]:
        if sha(cache/row["file"]) != row["sha256"]:
            raise ValueError(f"input_hash_mismatch:{row['file']}")
    minutes,marks,hours,funding,quality = {},{},{},{},{}
    exchange = json.loads((cache/"exchange-info.json").read_text())
    rules = {r["symbol"]:r for r in exchange["symbols"] if r["symbol"] in config["crypto_symbols"]}
    for symbol in config["crypto_symbols"]:
        consistency_mismatches = []
        for kind,destination in (("klines",minutes),("markPriceKlines",marks)):
            rows = {}
            for t in range(start,end,86400):
                day = iso(t)[:10]
                for bar in parse_bars(cache/f"{kind}-{symbol}-1m-{day}.zip"):
                    if bar.t in rows or not 0 < bar.l <= min(bar.o,bar.c) <= max(bar.o,bar.c) <= bar.h:
                        raise ValueError(f"duplicate_or_invalid_bar:{symbol}:{bar.t}")
                    rows[bar.t] = bar
            if sorted(rows) != list(range(start,end,60)):
                raise ValueError(f"continuous_minute_gap:{symbol}:{kind}")
            destination[symbol] = rows
        known_hours = {}
        for record in manifest["files"]:
            if not record["file"].startswith(f"klines-{symbol}-1h-"):
                continue
            for bar in parse_bars(cache/record["file"]):
                if start-35*86400 <= bar.t < end:
                    if bar.t in known_hours and known_hours[bar.t] != bar:
                        raise ValueError("conflicting_hour_sources")
                    known_hours[bar.t] = bar
        if sorted(known_hours) != list(range(start-35*86400,end,3600)):
            raise ValueError("hourly_warmup_gap")
        hours[symbol] = [known_hours[t] for t in sorted(known_hours)]
        for bar in aggregate(list(minutes[symbol].values()),3600,60):
            fields = [k for k in ("o","h","l","c","v","q")
                      if not math.isclose(getattr(bar,k),getattr(known_hours[bar.t],k),rel_tol=1e-7,abs_tol=1e-5)]
            if fields:
                consistency_mismatches.append({"time":iso(bar.t),"fields":fields})
                if not allow_hourly_mismatch:
                    raise ValueError(f"minute_hour_mismatch:{symbol}:{bar.t}")
        settlements = {}
        for t in range(start,end,7*86400):
            for row in json.loads((cache/f"funding-{symbol}-{iso(t)[:10]}.json").read_text()):
                key = (int(row["fundingTime"]),row.get("rateType","Regular"))
                if key in settlements and settlements[key] != row:
                    raise ValueError("conflicting_funding_sources")
                settlements[key] = row
        funding[symbol] = [settlements[k] for k in sorted(settlements)]
        quality[symbol] = {"trade_minutes":len(minutes[symbol]),"mark_minutes":len(marks[symbol]),
                           "hours":len(hours[symbol]),"funding_records":len(funding[symbol]),
                           "minute_hour_consistent":not consistency_mismatches,
                           "minute_hour_mismatch_count":len(consistency_mismatches),
                           "minute_hour_mismatches":consistency_mismatches,
                           "historical_funding_interval_snapshots":0}
    return MarketData(minutes,marks,hours,funding,rules,quality)


def group_events(signals: list[Signal], hours: int) -> list[Signal]:
    """Fixed, non-chaining windows across symbols and sides; no return-based grouping."""
    result,anchor,event = [],None,None
    for sig in signals:
        if anchor is None or sig.decision_time >= anchor+hours*3600:
            anchor = sig.decision_time
            event = iso(anchor)
        result.append(replace(sig,event_id=event))
    return result


def confirm_entries(signals: list[Signal], updates: dict, end: int) -> list[Signal]:
    result = []
    for sig in signals:
        t = sig.decision_time+3600
        row = updates[sig.symbol].get(t)
        boundary = sig.breakout_high if sig.side == 1 else sig.breakout_low
        if row and t < end and boundary is not None and sig.side*(row[0].c-boundary)>0:
            result.append(replace(sig,decision_time=t,close=row[0].c,original_decision_time=sig.decision_time))
    return result


def path_diagnostic(trade: dict, data: MarketData, config: dict, post_hours: int) -> dict:
    """Exit-bar extrema are bounds, not a claim about unknowable within-minute order."""
    sym,side = trade["symbol"],1 if trade["side"]=="long" else -1
    entered,exited = seconds(trade["entry_time"]),seconds(trade["exit_time"])
    entry,risk = trade["entry_price"],abs(trade["entry_price"]-trade["initial_stop"])
    price_risk = risk*trade["quantity"]
    prices = data.minutes[sym]
    full = [prices[t] for t in range(entered,exited,60) if t in prices]
    favorable = [0.0,side*(trade["exit_price"]-entry)/risk]
    adverse = favorable.copy()
    for b in full:
        favorable.append(side*((b.h if side==1 else b.l)-entry)/risk)
        adverse.append(side*((b.l if side==1 else b.h)-entry)/risk)
    last = prices.get(exited)
    if last:
        favorable.append(side*(last.o-entry)/risk)
        adverse.append(side*(last.o-entry)/risk)
    mfe,mae = max(favorable),-min(adverse)
    uncertain = trade.get("exit_timing","intraminute_unknown") == "intraminute_unknown"
    mfe_upper = max(mfe,side*((last.h if side==1 else last.l)-entry)/risk) if last and uncertain else mfe
    mae_upper = max(mae,-side*((last.l if side==1 else last.h)-entry)/risk) if last and uncertain else mae
    sig = trade.get("signal",{})
    boundary = sig.get("breakout_high" if side==1 else "breakout_low")
    failed = None
    if boundary is not None:
        for b in data.hours[sym]:
            decision = b.t+3600
            if entered < decision <= entered+config["crypto_max_hold_hours"]*3600 and side*(b.c-boundary)<=0:
                execution = decision+config["entry_delay_minutes"]*60
                if execution in prices:
                    px = prices[execution].o*(1-side*config["crypto_slippage_per_side"])
                    funding = sum(-side*float(f["markPrice"])*float(f["fundingRate"])
                                  for f in data.funding[sym]
                                  if entered < int(f["fundingTime"])//60000*60 <= execution)
                    net_r = (side*(px-entry)-config["crypto_fee_per_side"]*(entry+px)+funding)/risk
                    failed = {"decision_time":iso(decision),"execution_time":iso(execution),
                              "hours_after_entry":(decision-entered)/3600,"hypothetical_net_r":net_r,
                              "strictly_before_actual_exit":execution<exited,
                              "status":"opportunity_before_exit" if execution<exited else "after_or_at_exit_not_executable_for_trade"}
                break
    # Start after the exit minute to avoid accidentally treating pre-stop prices as recovery.
    post_start = exited+60 if uncertain else exited
    post = [prices[t] for t in range(post_start,exited+post_hours*3600,60) if t in prices]
    complete = all(t in prices for t in range(post_start,exited+post_hours*3600,60))
    post_result = {"window_hours":post_hours,"complete":complete,"observed_minutes":len(post)}
    if post:
        fav = max(side*((b.h if side==1 else b.l)-entry)/risk for b in post)
        adv = min(side*((b.l if side==1 else b.h)-entry)/risk for b in post)
        post_result.update({"max_original_direction_r":fav,"min_original_direction_r":adv,
                            "terminal_original_direction_r":side*(post[-1].c-entry)/risk,
                            "recovered_entry":fav>=0,"reached_plus_1r":fav>=1,
                            "recovered_boundary":any(side*((b.h if side==1 else b.l)-boundary)>=0 for b in post)
                            if boundary is not None else None})
    net_r = trade["net_pnl_usdt"]/price_risk
    return {"price_risk_usdt":price_risk,"initial_price_r":risk,"net_r":net_r,
            "mfe_r_confirmed":mfe,"mfe_r_upper_bound":mfe_upper,"mae_r_confirmed":mae,
            "mae_r_upper_bound":mae_upper,"giveback_from_confirmed_mfe_r":mfe-net_r,
            "holding_hours":(exited-entered)/3600,"failure_path":failed,"post_exit":post_result,
            "actual_loss_to_planned_risk":max(-trade["net_pnl_usdt"],0)/trade["planned_risk_usdt"]}


def enrich_bundle(bundle: dict, data: MarketData, config: dict, study: dict) -> None:
    trades = bundle["trades"]
    events = defaultdict(float)
    for trade in trades:
        trade["diagnostic"] = path_diagnostic(trade,data,config,study["post_exit_window_hours"])
        events[trade["signal"]["event_id"]] += trade["net_pnl_usdt"]
    s = bundle["summary"]
    net_rs = [r["diagnostic"]["net_r"] for r in trades]
    occupied = sum(r["diagnostic"]["holding_hours"] for r in trades)
    total_hours = (seconds(s["end_exclusive"])-timestamp(s["week_start"]))/3600
    profits = sorted((p for p in events.values() if p>0),reverse=True)
    s.update({"mean_net_r":statistics.mean(net_rs) if net_rs else None,"sum_net_r":sum(net_rs),
              "worst_net_r":min(net_rs) if net_rs else None,"holding_hours":occupied,
              "occupancy_fraction":occupied/total_hours,
              "mean_margin_fraction_time_weighted":sum(r["margin_usdt"]/r["equity_before"]*
                    r["diagnostic"]["holding_hours"] for r in trades)/total_hours,
              "worst_loss_to_planned_risk":max((r["diagnostic"]["actual_loss_to_planned_risk"] for r in trades),default=0),
              "event_count_traded":len(events),"event_pnl_usdt":dict(events),
              "top_event_share_positive_event_pnl":profits[0]/sum(profits) if profits else None,
              "top3_events_share_positive_event_pnl":sum(profits[:3])/sum(profits) if profits else None,
              "exit_counts":dict(Counter(r["exit_reason"] for r in trades)),
              "funding_interval_sources":dict(Counter(r["funding_budget"]["interval_source"] for r in bundle["decisions"]))})


def fixed_cost_revaluation(trades: list[dict], multiplier: float) -> dict:
    """Frozen fills and quantities; charge extra execution friction as cash costs."""
    rows = [{"entry_time":t["entry_time"],"symbol":t["symbol"],
             "original_net_pnl_usdt":t["net_pnl_usdt"],
             "net_pnl_usdt":t["net_pnl_usdt"]-(multiplier-1)*(t["fees_usdt"]+t["slippage_usdt"]),
             "net_r":(t["net_pnl_usdt"]-(multiplier-1)*(t["fees_usdt"]+t["slippage_usdt"]))/t["diagnostic"]["price_risk_usdt"]}
            for t in trades]
    return {"mode":"fixed_fills_quantities_extra_cash_cost_no_resizing", "cost_multiplier":multiplier,
            "trade_count":len(rows),"net_pnl_usdt":sum(t["net_pnl_usdt"] for t in rows),
            "mean_net_r":statistics.mean(t["net_r"] for t in rows) if rows else None,"trades":rows}


def matched_exit_comparison(trades: list[dict], data: MarketData, config: dict, updates: dict, end: int) -> dict:
    """Freeze each original entry/quantity; freed capital cannot create extra trades."""
    records=[]
    for trade in trades:
        sig=Signal(**trade["signal"])
        cfg={**config,"initial_equity_usdt":trade["equity_before"],"breakout_failure_exit":True}
        stop=min(end,seconds(trade["entry_time"])+cfg["crypto_max_hold_hours"]*3600+60)
        result=simulate(data,cfg,iso(sig.decision_time),[sig],updates,variant="crypto",risk=0.02,end_time=stop)
        if len(result["trades"])!=1: raise AssertionError("matched_entry_missing")
        other=result["trades"][0]
        if (other["entry_time"]!=trade["entry_time"] or other["entry_price"]!=trade["entry_price"]
                or other["quantity"]!=trade["quantity"]): raise AssertionError("matched_entry_changed")
        records.append({"symbol":trade["symbol"],"entry_time":trade["entry_time"],
            "event_id":sig.event_id,"original_exit":trade["exit_reason"],"alternative_exit":other["exit_reason"],
            "original_exit_time":trade["exit_time"],"alternative_exit_time":other["exit_time"],
            "original_net_r":trade["diagnostic"]["net_r"],
            "alternative_net_r":other["net_pnl_usdt"]/trade["diagnostic"]["price_risk_usdt"],
            "delta_net_r":(other["net_pnl_usdt"]-trade["net_pnl_usdt"])/trade["diagnostic"]["price_risk_usdt"],
            "delta_usdt":other["net_pnl_usdt"]-trade["net_pnl_usdt"]})
    changed=[r for r in records if abs(r["delta_net_r"])>1e-9]
    return {"diagnostic_only":True,"continuous_account_return":False,"fixed_original_entries_and_quantities":True,
            "trade_count":len(records),"changed_exits":len(changed),
            "improved":sum(r["delta_net_r"]>1e-9 for r in records),
            "worsened":sum(r["delta_net_r"] < -1e-9 for r in records),
            "original_winners_turned_negative":sum(r["original_net_r"]>0>r["alternative_net_r"] for r in records),
            "delta_net_r_sum":sum(r["delta_net_r"] for r in records),
            "delta_usdt_sum":sum(r["delta_usdt"] for r in records),"records":records}


def signal_paths(signals: list[Signal], data: MarketData, config: dict, study: dict) -> dict:
    """24h diagnostic horizons in uniform price R, no account or cost gates."""
    records = []
    horizon = study["signal_path_hours"]*3600
    for sig in signals:
        prices = data.minutes[sig.symbol]
        t = sig.decision_time+config["entry_delay_minutes"]*60
        if t not in prices or t+horizon not in prices:
            continue
        side = sig.side
        price = prices[t].o*(1+side*config["crypto_slippage_per_side"])
        risk = config["initial_stop_atr"]*sig.atr
        future = [prices[x] for x in range(t,t+horizon,60)]
        exit_price = prices[t+horizon].o*(1-side*config["crypto_slippage_per_side"])
        funding = sum(-side*float(f["markPrice"])*float(f["fundingRate"]) for f in data.funding[sig.symbol]
                      if t < int(f["fundingTime"])//60000*60 <= t+horizon)
        records.append({**asdict(sig),"entry_time":iso(t),"horizon_hours":study["signal_path_hours"],
            "mfe_r":max(0,max(side*((b.h if side==1 else b.l)-price)/risk for b in future)),
            "mae_r":max(0,max(-side*((b.l if side==1 else b.h)-price)/risk for b in future)),
            "net_r":(side*(exit_price-price)-config["crypto_fee_per_side"]*(price+exit_price)+funding)/risk})
    summaries = {}
    filters = {"A_simple":lambda r:True,"B_direction":lambda r:r["direction_pass"],
               "C_volume":lambda r:r["volume_pass"],"D_original":lambda r:r["direction_pass"] and r["volume_pass"],
               "rejected_direction":lambda r:not r["direction_pass"],"rejected_volume":lambda r:not r["volume_pass"]}
    for name,accept in filters.items():
        selected = [r for r in records if accept(r)]
        grouped = defaultdict(list)
        for r in selected:
            grouped[r["event_id"]].append(r["net_r"])
        summaries[name] = {"signal_count":len(selected),"event_count":len(grouped),
                           "mean_net_r":statistics.mean(r["net_r"] for r in selected) if selected else None,
                           "equal_event_mean_net_r":statistics.mean(statistics.mean(v) for v in grouped.values()) if grouped else None}
    return {"diagnostic_only":True,"account_executable_return":False,"independent_observations":False,
            "definition":"fixed 24h horizon without protective exits, cost/risk gates, or sizing; descriptive signal paths",
            "boundary_censored_signals":len(signals)-len(records),"summaries":summaries,"records":records}


def stock_diagnostics(cache: Path, config: dict) -> dict:
    records = []
    volatility_records=[]
    for week in sorted(config["draw_order"]):
        data = load_data(cache,config,week)
        start,end = timestamp(week),timestamp(week)+7*86400
        signals,_ = generate_signals(data,config,start,end)
        rth_atrs,opening_ranges = {},{}
        for sym in config["stock_symbols"]:
            quarters = aggregate(list(data.minutes[sym].values()),900,60)
            rth = [b for b in quarters if session(b.t) and 570<=session(b.t)[1]<session(b.t)[2]]
            ranges,known,previous_day,previous_close = [],{},None,None
            daily = defaultdict(list)
            for b in rth:
                day = session(b.t)[0]
                reference = previous_close if day==previous_day else b.o
                tr = max(b.h-b.l,abs(b.h-reference),abs(b.l-reference))
                ranges.append(tr)
                if len(ranges)==14: value = statistics.mean(ranges)
                elif len(ranges)>14: value = (value*13+tr)/14
                if len(ranges)>=14: known[b.t+900] = value
                previous_day,previous_close = day,b.c
                if session(b.t)[1]<600: daily[day].append(b)
            rth_atrs[sym] = known
            opening_ranges[sym] = {day:max(b.h for b in bs)-min(b.l for b in bs) for day,bs in daily.items() if len(bs)==2}
            for b in quarters:
                if start<=b.t<end:
                    hours=session(b.t)
                    regular=bool(hours and 570<=hours[1]<hours[2])
                    volatility_records.append({"symbol":sym,"regular":regular,"range_fraction":(b.h-b.l)/b.o})
        for sig in signals:
            if sig.market!="stock": continue
            entry_t = sig.decision_time+config["entry_delay_minutes"]*60
            prices = data.minutes[sig.symbol]
            raw = prices[entry_t].o
            local = dt.datetime.fromtimestamp(entry_t,NY)
            deadline = int(local.replace(hour=session(entry_t)[2]//60-1,minute=45,second=0).timestamp())
            path = [prices[t] for t in range(entry_t,deadline,60)]
            move = max(sig.side*((b.h if sig.side==1 else b.l)/raw-1) for b in path)
            terminal = sig.side*(prices[deadline].o/raw-1)
            rth = rth_atrs[sig.symbol].get(sig.decision_time)
            records.append({"week":week,"symbol":sig.symbol,"decision_time":iso(sig.decision_time),
                            "session_event":f"{sig.symbol}:{local.date()}","side":sig.side,
                            "continuous_atr_stop_fraction":1.5*sig.atr/raw,
                            "rth_atr_stop_fraction":1.5*rth/raw if rth else None,
                            "opening_range_fraction":opening_ranges[sig.symbol].get(str(local.date()),0)/raw,
                            "mfe_fraction_upper_bound":move,"terminal_gross_fraction":terminal,
                            "mfe_after_30bp_upper_bound":move-0.003,"terminal_after_30bp_before_funding":terminal-0.003})
    def median(key):
        values = [r[key] for r in records if r[key] is not None]
        return statistics.median(values) if values else None
    events = defaultdict(list)
    for r in records: events[r["session_event"]].append(r)
    return {"diagnostic_only":True,"stock_account_trades":0,"signal_count":len(records),"symbol_session_events":len(events),
            "mfe_covers_30bp_count":sum(r["mfe_fraction_upper_bound"]>0.003 for r in records),
            "mfe_covers_60bp_count":sum(r["mfe_fraction_upper_bound"]>0.006 for r in records),
            "median_continuous_atr_stop":median("continuous_atr_stop_fraction"),
            "median_rth_atr_stop":median("rth_atr_stop_fraction"),"median_opening_range":median("opening_range_fraction"),
            "median_15m_rth_range":statistics.median(r["range_fraction"] for r in volatility_records if r["regular"]),
            "median_15m_outside_rth_range":statistics.median(r["range_fraction"] for r in volatility_records if not r["regular"]),
            "median_terminal_after_30bp_before_funding":median("terminal_after_30bp_before_funding"),
            "equal_event_mean_terminal_after_30bp_before_funding":statistics.mean(
                statistics.mean(r["terminal_after_30bp_before_funding"] for r in rows) for rows in events.values()),
            "limitation":"MFE is a hindsight upper bound, not an exit rule; 30bp cost excludes funding. No stock strategy selected.",
            "records":records}
