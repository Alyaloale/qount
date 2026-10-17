"""Run the predeclared A/L/LT/LG breakout comparisons on cached data."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import statistics
from pathlib import Path

from qount.research.small_account_breakout import generate_signals, simulate
from qount.research.small_account_breakout_data import sha, timestamp, write_json
from qount.research.small_account_breakout_study import group_events, load_continuous


UTC = dt.timezone.utc


def price_risk(trade: dict) -> float:
    return trade["quantity"]*abs(trade["entry_price"]-trade["initial_stop"])


def drawdown(values: list[float]) -> float:
    peak, worst = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        worst = max(worst, 1-value/peak)
    return worst


def daily_nav(curve: list[dict], initial: float) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in curve:
        day = dt.datetime.fromtimestamp(timestamp(row["time"])-60, UTC).date().isoformat()
        result[day] = row["equity_usdt"]
    return {"start": initial, **result}


def benchmark(data, start: int, end: int, fee: float, slip: float,
              strategy_daily_returns: list[float]) -> dict:
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    daily = []
    asset_results = {}
    for symbol in symbols:
        rows = data.minutes[symbol]
        p0, p1 = rows[start].o, rows[end-60].c
        net = (p1*(1-slip)*(1-fee))/(p0*(1+slip)*(1+fee))-1
        closes = {}
        for t in range(start, end, 60):
            if t % 86400 == 0:
                closes[dt.datetime.fromtimestamp(t, UTC).date().isoformat()] = rows[t].o
        closes[dt.datetime.fromtimestamp(end-60, UTC).date().isoformat()] = p1
        asset_results[symbol] = {"net_buy_hold_return": net,
            "price_return_before_costs":p1/p0-1,
            "daily_closes":closes,"normalized_daily_prices":{d:p/p0 for d,p in closes.items()}}
    dates = sorted(set.intersection(*(set(v["daily_closes"]) for v in asset_results.values())))
    basket_nav = [sum(asset_results[s]["normalized_daily_prices"][day] for s in symbols)/3 for day in dates]
    basket_returns = [basket_nav[i]/basket_nav[i-1]-1 for i in range(1,len(basket_nav))]
    strategy_vol = statistics.stdev(strategy_daily_returns) if len(strategy_daily_returns)>1 else 0.0
    basket_vol = statistics.stdev(basket_returns) if len(basket_returns)>1 else 0.0
    scale = strategy_vol/basket_vol if basket_vol>0 else 0.0
    scaled_nav=[1.0]
    for r in basket_returns:
        scaled_nav.append(scaled_nav[-1]*(1+scale*r))
    scaled_net=scaled_nav[-1]*(1-2*(fee+slip)*scale)-1
    return {"cash_return":0.0,"execution_cost_assumption_per_side":{"fee":fee,"slippage":slip},
        "single_asset_buy_hold":{s:{k:v for k,v in row.items() if k not in {"daily_closes","normalized_daily_prices"}}
                                 for s,row in asset_results.items()},
        "equal_weight_unlevered_buy_hold":{
            "gross_return":basket_nav[-1]-1,
            "net_return_approx":basket_nav[-1]*(1-2*(fee+slip))-1,
            "max_drawdown":drawdown(basket_nav),"daily_volatility":basket_vol},
        "equal_weight_ex_post_volatility_matched":{
            "scale_to_strategy_daily_volatility":scale,
            "strategy_daily_volatility":strategy_vol,"basket_daily_volatility":basket_vol,
            "net_return_approx":scaled_net,"max_drawdown_before_entry_exit_costs":drawdown(scaled_nav),
            "interpretation":"ex-post descriptive risk match, not a deployable or independent benchmark"}}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,default=Path("config/small-account-breakout-v03-next.json"))
    parser.add_argument("--cache",type=Path,default=Path("state/research_cache/small_account_breakout_v02_20261013"))
    parser.add_argument("--study-config",type=Path,default=Path("config/small-account-breakout-v02.json"))
    parser.add_argument("--pilot",type=Path,default=Path("state/research_runs/small_account_breakout_v01_20261013_verified"))
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): raise FileExistsError("refuse_overwrite_research_bundle")
    plan=json.loads(args.config.read_text())
    study=json.loads(args.study_config.read_text())
    base=json.loads(Path(study["base_config"]).read_text())
    if plan["research_only"] is not True or plan["orders_authorized"] is not False:
        raise ValueError("research_only_contract_required")
    cfg=copy.deepcopy(base)
    cfg.update({"stock_symbols":[],"funding_interval_mode":study["funding_interval_mode"],
        "funding_interval_fallback_hours":study["funding_interval_fallback_hours"],"size_to_liquidity":True})
    data=load_continuous(args.cache,cfg,study)
    start,end=timestamp(plan["development_start"]),timestamp(plan["development_end_exclusive"])
    # The signal generator returns the completed-hour update cache used by exits.
    signals,updates=generate_signals(data,cfg,start,end,simple=True)
    signals=group_events([s for s in signals if s.market=="crypto"],study["event_window_hours"])
    longs=[s for s in signals if s.side==1]
    runs={}
    def execute(name, selected, settings, risk=.02, scenario="base"):
        current=copy.deepcopy(settings)
        bundle=simulate(data,current,plan["development_start"],selected,updates,variant="crypto",
                        risk=risk,scenario=scenario,end_time=end)
        s=bundle["summary"]
        for t in bundle["trades"]:
            side=1 if t["side"]=="long" else -1
            pnl=side*t["quantity"]*(t["exit_price"]-t["entry_price"])-t["fees_usdt"]+t["funding_net_usdt"]
            if not math.isclose(pnl,t["net_pnl_usdt"],abs_tol=1e-8): raise AssertionError("trade_ledger")
        mdd=drawdown([current["initial_equity_usdt"],*[r["equity_usdt"] for r in bundle["curve"]]])
        if not math.isclose(mdd,s["max_drawdown"],abs_tol=1e-10): raise AssertionError("nav_mdd")
        s["name"]=name
        write_json(args.output/f"{name}.json",bundle)
        nav=daily_nav(bundle["curve"],current["initial_equity_usdt"])
        runs[name]={"bundle":bundle,"config":current,"daily_nav":nav}
        print(json.dumps({k:s[k] for k in ("name","final_equity_usdt","net_return","max_drawdown","trade_count")}),flush=True)
        return bundle

    args.output.mkdir(parents=True)
    write_json(args.output/"plan.json",plan)
    write_json(args.output/"data-quality.json",data.quality)
    execute("A_simple",signals,cfg)
    execute("L_long_only",longs,cfg)
    lt={**cfg,"trailing_activation_r":2.0,"trailing_atr":1.0}
    execute("LT_long_only_trailing_1atr",longs,lt)
    lg={**cfg,"stress_slippage_budget_fraction":plan["extra_stress_slippage_fraction"]}
    execute("LG_long_only_stress_budget",longs,lg)
    execute("L_long_only_risk_1_3pct",longs,cfg,risk=plan["ordinary_downsize_comparison_risk_fraction"])
    execute("L_long_only_double_cost",longs,cfg,scenario="double_cost")
    execute("LT_long_only_trailing_1atr_double_cost",longs,lt,scenario="double_cost")
    execute("LG_long_only_stress_budget_double_cost",longs,lg,scenario="double_cost")
    execute("L_long_only_stop_gap_1pct",longs,cfg,scenario="stop_gap_1pct")
    execute("LG_long_only_stress_budget_stop_gap_1pct",longs,lg,scenario="stop_gap_1pct")
    for name in ("L_long_only","LT_long_only_trailing_1atr","LG_long_only_stress_budget"):
        rows=[]
        for trade in runs[name]["bundle"]["trades"]:
            adjusted=trade["net_pnl_usdt"]-trade["fees_usdt"]-trade["slippage_usdt"]
            rows.append({"entry_time":trade["entry_time"],"symbol":trade["symbol"],
                "original_net_pnl_usdt":trade["net_pnl_usdt"],"double_cost_net_pnl_usdt":adjusted,
                "double_cost_net_r":adjusted/price_risk(trade)})
        write_json(args.output/f"{name}_fixed_double_cost.json",{"mode":"fixed_fills_quantities_extra_cash_cost_no_resizing",
            "cost_multiplier":2,"trade_count":len(rows),"net_pnl_usdt":sum(r["double_cost_net_pnl_usdt"] for r in rows),
            "mean_net_r":statistics.mean(r["double_cost_net_r"] for r in rows) if rows else None,"trades":rows})

    # Fixed-entry/quantity pairing isolates only the post-entry trailing-distance change.
    fixed=[]
    for trade in runs["L_long_only"]["bundle"]["trades"]:
        sig=next(s for s in longs if s.symbol==trade["symbol"] and s.decision_time==timestamp(trade["decision_time"]))
        one_cfg={**lt,"initial_equity_usdt":trade["equity_before"]}
        end_trade=min(end,timestamp(trade["entry_time"])+cfg["crypto_max_hold_hours"]*3600+60)
        one=simulate(data,one_cfg,dt.datetime.fromtimestamp(sig.decision_time,UTC).date().isoformat(),
            [sig],updates,variant="crypto",risk=.02,end_time=end_trade)
        if len(one["trades"])!=1: raise AssertionError("fixed_trade_not_reproduced")
        other=one["trades"][0]
        if (other["entry_time"]!=trade["entry_time"] or other["entry_price"]!=trade["entry_price"]
                or other["quantity"]!=trade["quantity"]): raise AssertionError("fixed_trade_entry_changed")
        fixed.append({"symbol":trade["symbol"],"side":trade["side"],"event_id":trade["signal"]["event_id"],
            "entry_time":trade["entry_time"],"original_exit":trade["exit_reason"],"candidate_exit":other["exit_reason"],
            "original_net_pnl_usdt":trade["net_pnl_usdt"],"candidate_net_pnl_usdt":other["net_pnl_usdt"],
            "delta_net_pnl_usdt":other["net_pnl_usdt"]-trade["net_pnl_usdt"],
            "original_net_r":trade["net_pnl_usdt"]/price_risk(trade),
            "candidate_net_r":other["net_pnl_usdt"]/price_risk(other)})
    write_json(args.output/"LT_fixed_entries.json",{"diagnostic_only":True,"trade_count":len(fixed),
        "delta_net_pnl_usdt":sum(x["delta_net_pnl_usdt"] for x in fixed),"improved":sum(x["delta_net_pnl_usdt"]>0 for x in fixed),
        "worsened":sum(x["delta_net_pnl_usdt"]<0 for x in fixed),"records":fixed})

    l_curve=runs["L_long_only"]["bundle"]["curve"]
    daily_returns=[]
    prior=cfg["initial_equity_usdt"]
    seen=set()
    for row in l_curve:
        day=dt.datetime.fromtimestamp(timestamp(row["time"])-60,UTC).date().isoformat()
        if day not in seen:
            daily_returns.append(row["equity_usdt"]/prior-1)
            seen.add(day)
        elif row["time"].endswith("T23:59:00+00:00"):
            daily_returns[-1]=row["equity_usdt"]/prior-1
            prior=row["equity_usdt"]
    benchmark_result=benchmark(data,start,end,cfg["crypto_fee_per_side"],cfg["crypto_slippage_per_side"],daily_returns)
    write_json(args.output/"benchmark-controls.json",benchmark_result)

    # Event weighted net outcomes and monthly path dispersion are included for the primary L/LT/LG arms.
    report=["# Breakout next-step experiment", "",f"Discovery interval {plan['development_start']} to {plan['development_end_exclusive']} (end exclusive). Not independent OOS.",
        "","|Variant|Return|MDD|Trades|Mean net R|Events|Worst month|Best month|","|---|---:|---:|---:|---:|---:|---:|---:|"]
    summaries={}
    for name,row in runs.items():
        bundle=row["bundle"]; s=bundle["summary"]
        months={}
        points=bundle["curve"]
        previous=cfg["initial_equity_usdt"]
        for point in points:
            month=dt.datetime.fromtimestamp(timestamp(point["time"])-60,UTC).strftime("%Y-%m")
            months.setdefault(month,{"start":previous})["end"]=point["equity_usdt"]
            previous=point["equity_usdt"]
        month_returns={m:v["end"]/v["start"]-1 for m,v in months.items()}
        events={}
        for t in bundle["trades"]:
            events[t["signal"].get("event_id") or t["decision_time"]]=events.get(t["signal"].get("event_id") or t["decision_time"],0)+t["net_pnl_usdt"]
        net_rs=[t["net_pnl_usdt"]/price_risk(t) for t in bundle["trades"]]
        event_r={}
        for t in bundle["trades"]:
            eid=t["signal"].get("event_id") or t["decision_time"]
            event_r.setdefault(eid,[]).append(t["net_pnl_usdt"]/price_risk(t))
        summary={**s,"mean_trade_net_usdt":statistics.mean([t["net_pnl_usdt"] for t in bundle["trades"]]) if bundle["trades"] else None,
            "mean_net_r":statistics.mean(net_rs) if net_rs else None,"sum_net_r":sum(net_rs),
            "event_count":len(events),"event_equal_weight_mean_net_usdt":statistics.mean(events.values()) if events else None,
            "event_equal_weight_mean_net_r":statistics.mean(statistics.mean(v) for v in event_r.values()) if event_r else None,
            "monthly_returns":month_returns,"worst_month_return":min(month_returns.values()),"best_month_return":max(month_returns.values()),
            "positive_events":sum(v>0 for v in events.values()),"top_event_share_of_positive_pnl":max([v for v in events.values() if v>0],default=0)/sum(v for v in events.values() if v>0) if any(v>0 for v in events.values()) else None}
        summaries[name]=summary
        mean_r=f"{summary['mean_net_r']:.3f}" if summary["mean_net_r"] is not None else "—"
        report.append(f"|{name}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['trade_count']}|{mean_r}|{len(events)}|{summary['worst_month_return']:.2%}|{summary['best_month_return']:.2%}|")
    write_json(args.output/"summary.json",{"runs":summaries,"benchmarks":benchmark_result,
        "long_signal_count":len(longs),"all_signal_count":len(signals),"research_only":True,"orders_authorized":False,
        "independent_oos":False,"stock_perpetuals_included":False,"volatility_contraction_included":False,
        "tail_budget_definition":"N <= rE/(d+c+0.01); structural stop unchanged"})
    report += ["","Controls: cash 0%; equal-weight unlevered BTC/ETH/SOL buy-and-hold net return {:.2%}, MDD {:.2%}; ex-post volatility-matched basket net return {:.2%}, MDD {:.2%}. Single-asset buy-and-hold net returns: BTC {:.2%}, ETH {:.2%}, SOL {:.2%}.".format(
        benchmark_result["equal_weight_unlevered_buy_hold"]["net_return_approx"],benchmark_result["equal_weight_unlevered_buy_hold"]["max_drawdown"],
        benchmark_result["equal_weight_ex_post_volatility_matched"]["net_return_approx"],benchmark_result["equal_weight_ex_post_volatility_matched"]["max_drawdown_before_entry_exit_costs"],
        benchmark_result["single_asset_buy_hold"]["BTCUSDT"]["net_buy_hold_return"],benchmark_result["single_asset_buy_hold"]["ETHUSDT"]["net_buy_hold_return"],benchmark_result["single_asset_buy_hold"]["SOLUSDT"]["net_buy_hold_return"]),
        "","LT keeps 2R activation and changes only the trailing distance to 1.0 ATR. Fixed-entry/quantity results are diagnostics; the full continuous account rerun includes re-entry and opportunity changes.",
        "LG retains the structural stop and includes an extra 1% adverse-slippage reserve in the sizing denominator. The 1.3% L arm is a constant ordinary-downsize comparison; actual planned risk distributions remain in trade ledgers.",
        "Double-cost fixed-fills/quantities and full-account reruns are both stored for L/LT/LG; 1% stop-gap arms are full continuous account stress reruns. The volatility-matched basket is ex-post descriptive only. All history here is consumed development data.",""]
    (args.output/"report.md").write_text("\n".join(report))
    manifest={"created_at":dt.datetime.now(UTC).isoformat(),"source_hashes":{
        str(p):sha(p) for p in [args.config,args.study_config,Path(study["base_config"]),Path(__file__),
        Path("src/qount/research/small_account_breakout.py"),Path("src/qount/research/small_account_breakout_data.py"),
        Path("src/qount/research/small_account_breakout_study.py")]},
        "cache_manifest_sha256":sha(args.cache/"continuous-manifest.json"),"pilot_manifest_sha256":sha(args.pilot/"manifest.json"),
        "research_only":True,"orders_authorized":False,"files":{p.name:sha(p) for p in sorted(args.output.iterdir()) if p.is_file()}}
    write_json(args.output/"manifest.json",manifest)
    (args.output/"_COMPLETE").write_text(sha(args.output/"manifest.json")+"\n")
    return 0


if __name__=="__main__": raise SystemExit(main())
