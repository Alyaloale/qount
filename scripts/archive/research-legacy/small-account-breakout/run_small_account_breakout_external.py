"""One-shot frozen 2025 historical validation for A versus Long-Only."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from qount.research.small_account_breakout import generate_signals, simulate
from qount.research.small_account_breakout_data import acquire_continuous, sha, timestamp, write_json
from qount.research.small_account_breakout_study import group_events, load_continuous

UTC=dt.timezone.utc


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path,default=Path("config/small-account-breakout-v03-external-2025.json"))
    p.add_argument("--cache",type=Path,default=Path("state/research_cache/small_account_breakout_v03_external_2025"))
    p.add_argument("--reuse",type=Path,default=Path("state/research_cache/small_account_breakout_v01_20261013"))
    p.add_argument("--study-config",type=Path,default=Path("config/small-account-breakout-v02.json"))
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--resume",action="store_true",help="resume the isolated public-data cache after a transient fetch failure")
    args=p.parse_args()
    if args.output.exists() or (args.cache.exists() and not args.resume): raise FileExistsError("refuse_overwrite_validation_artifacts")
    plan=json.loads(args.config.read_text())
    study=json.loads(args.study_config.read_text())
    base=json.loads(Path(plan["base_config"]).read_text())
    study["development_start"]=plan["validation_start"]
    study["development_end_exclusive"]=plan["validation_end_exclusive"]
    cfg=copy.deepcopy(base)
    cfg.update({"stock_symbols":[],"initial_equity_usdt":plan["initial_equity_usdt"],
        "funding_interval_mode":study["funding_interval_mode"],
        "funding_interval_fallback_hours":study["funding_interval_fallback_hours"],"size_to_liquidity":True})
    acquire_continuous(cfg,study,args.cache,args.reuse)
    data=load_continuous(args.cache,cfg,study,allow_hourly_mismatch=True)
    start,end=timestamp(plan["validation_start"]),timestamp(plan["validation_end_exclusive"])
    signals,updates=generate_signals(data,cfg,start,end,simple=True)
    signals=group_events([s for s in signals if s.market=="crypto"],study["event_window_hours"])
    longs=[s for s in signals if s.side==1]
    args.output.mkdir(parents=True)
    write_json(args.output/"frozen-contract.json",plan)
    write_json(args.output/"data-quality.json",data.quality)
    results={}
    variants=[("A_simple",signals,"base"),("L_long_only",longs,"base"),
        ("L_long_only_double_cost",longs,"double_cost"),("L_long_only_stop_gap_1pct",longs,"stop_gap_1pct")]
    for name,selected,scenario in variants:
        bundle=simulate(data,cfg,plan["validation_start"],selected,updates,variant="crypto",
            risk=plan["risk_fraction"],scenario=scenario,end_time=end)
        trades=bundle["trades"]
        for t in trades:
            side=1 if t["side"]=="long" else -1
            pnl=side*t["quantity"]*(t["exit_price"]-t["entry_price"])-t["fees_usdt"]+t["funding_net_usdt"]
            if not math.isclose(pnl,t["net_pnl_usdt"],abs_tol=1e-8): raise AssertionError("trade_ledger")
        peak=plan["initial_equity_usdt"]; mdd=0.0
        for row in bundle["curve"]:
            peak=max(peak,row["equity_usdt"]); mdd=max(mdd,1-row["equity_usdt"]/peak)
        if not math.isclose(mdd,bundle["summary"]["max_drawdown"],abs_tol=1e-10): raise AssertionError("nav_mdd")
        events={}
        for t in trades:
            event=t["signal"].get("event_id") or t["decision_time"]
            events[event]=events.get(event,0)+t["net_pnl_usdt"]
        net_r=[t["net_pnl_usdt"]/(t["quantity"]*abs(t["entry_price"]-t["initial_stop"])) for t in trades]
        monthly={}
        previous=plan["initial_equity_usdt"]
        for row in bundle["curve"]:
            month=dt.datetime.fromtimestamp(timestamp(row["time"])-60,UTC).strftime("%Y-%m")
            monthly.setdefault(month,{"start":previous})["end"]=row["equity_usdt"]
            previous=row["equity_usdt"]
        months={k:v["end"]/v["start"]-1 for k,v in monthly.items()}
        bundle["summary"].update({"mean_net_r":statistics.mean(net_r) if net_r else None,
            "sum_net_r":sum(net_r),"event_count":len(events),
            "event_equal_weight_mean_net_usdt":statistics.mean(events.values()) if events else None,
            "monthly_returns":months,"worst_month_return":min(months.values()),
            "best_month_return":max(months.values()),"symbol_trade_counts":dict(Counter(t["symbol"] for t in trades))})
        write_json(args.output/f"{name}.json",bundle)
        results[name]=bundle["summary"]
        print(json.dumps({k:bundle["summary"][k] for k in ("net_return","max_drawdown","trade_count","mean_net_r")},
                         sort_keys=True),flush=True)
    summary={"holdout_role":"validation_v1","interval_start":plan["validation_start"],
        "interval_end_exclusive":plan["validation_end_exclusive"],"runs":results,
        "signal_count":len(signals),"long_signal_count":len(longs),"quality":data.quality,
        "no_rule_selection":True,"research_only":True,"orders_authorized":False,
        "historical_validation_not_forward_evidence":True}
    write_json(args.output/"summary.json",summary)
    rows=["# Frozen Long-Only historical validation","",f"validation_v1: {plan['validation_start']} to {plan['validation_end_exclusive']} (end exclusive). Rules frozen before this interval was read.",
        "","|Variant|Return|MDD|Trades|Mean net R|Worst month|Best month|","|---|---:|---:|---:|---:|---:|---:|"]
    for name,s in results.items():
        r=f"{s['mean_net_r']:.3f}" if s["mean_net_r"] is not None else "—"
        rows.append(f"|{name}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['trade_count']}|{r}|{s['worst_month_return']:.2%}|{s['best_month_return']:.2%}|")
    rows += ["","The interval is historical, not forward evidence. Current exchange filters approximate historical rules; no historical order book or executable fills are available.",
        "Double-cost reruns change the friction gate and transaction set. No tuning or candidate selection was performed on this interval.",""]
    (args.output/"report.md").write_text("\n".join(rows))
    sources=[args.config,args.study_config,Path(plan["base_config"]),Path(__file__),
        Path("src/qount/research/small_account_breakout.py"),Path("src/qount/research/small_account_breakout_data.py"),
        Path("src/qount/research/small_account_breakout_study.py")]
    manifest={"created_at":dt.datetime.now(UTC).isoformat(),"source_hashes":{str(x):sha(x) for x in sources},
        "input_manifest_sha256":sha(args.cache/"continuous-manifest.json"),"reused_pilot_manifest_sha256":sha(args.reuse/"manifest.json"),
        "files":{x.name:sha(x) for x in sorted(args.output.iterdir()) if x.is_file()},
        "holdout_role":"validation_v1","research_only":True,"orders_authorized":False}
    write_json(args.output/"manifest.json",manifest)
    (args.output/"_COMPLETE").write_text(sha(args.output/"manifest.json")+"\n")
    return 0


if __name__=="__main__": raise SystemExit(main())
