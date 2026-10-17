"""Test one predeclared pre-breakout volatility-compression filter."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from qount.research.small_account_breakout import atr, generate_signals, simulate
from qount.research.small_account_breakout_data import sha, timestamp, write_json
from qount.research.small_account_breakout_study import group_events, load_continuous

UTC=dt.timezone.utc


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path,default=Path("config/small-account-breakout-volatility-contraction-v01.json"))
    p.add_argument("--cache",type=Path,default=Path("state/research_cache/small_account_breakout_v02_20261013"))
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists(): raise FileExistsError("refuse_overwrite_research_bundle")
    plan=json.loads(args.config.read_text())
    study=json.loads(Path(plan["study_config"]).read_text())
    base=json.loads(Path(plan["base_config"]).read_text())
    cfg=copy.deepcopy(base)
    cfg.update({"stock_symbols":[],"initial_equity_usdt":plan["initial_equity_usdt"],
        "funding_interval_mode":study["funding_interval_mode"],
        "funding_interval_fallback_hours":study["funding_interval_fallback_hours"],"size_to_liquidity":True})
    data=load_continuous(args.cache,cfg,study)
    start,end=timestamp(plan["development_start"]),timestamp(plan["development_end_exclusive"])
    signals,updates=generate_signals(data,cfg,start,end,simple=True)
    signals=group_events([s for s in signals if s.market=="crypto"],study["event_window_hours"])
    longs=[s for s in signals if s.side==1]
    atr_close={}
    for symbol,bars in data.hours.items():
        values=atr(bars)
        atr_close[symbol]={bar.t+3600:values[i] for i,bar in enumerate(bars) if values[i] is not None}
    ratios={}; accepted=[]
    for sig in longs:
        previous_close=sig.decision_time-3600
        window=[atr_close[sig.symbol].get(previous_close-i*3600) for i in range(71,-1,-1)]
        if len(window)!=72 or any(x is None for x in window):
            continue
        ratio=window[-1]/statistics.mean(window)
        ratios[f"{sig.symbol}:{sig.decision_time}"]=ratio
        if ratio < plan["threshold"]: accepted.append(sig)
    args.output.mkdir(parents=True)
    write_json(args.output/"contract.json",plan)
    write_json(args.output/"compression-diagnostic.json",{"formula":plan["formula"],
        "threshold":plan["threshold"],"long_signal_count":len(longs),"eligible_complete_windows":len(ratios),
        "accepted_count":len(accepted),"accepted_fraction":len(accepted)/len(longs) if longs else None,
        "ratio_quantiles":{"p10":statistics.quantiles(ratios.values(),n=10)[0] if len(ratios)>=10 else None,
            "median":statistics.median(ratios.values()) if ratios else None,"p90":statistics.quantiles(ratios.values(),n=10)[8] if len(ratios)>=10 else None},
        "ratios":ratios})
    results={}
    for name,selected,scenario in (("L_long_only",longs,"base"),("LC_long_only_contraction_085",accepted,"base"),
        ("L_long_only_double_cost",longs,"double_cost"),("LC_long_only_contraction_085_double_cost",accepted,"double_cost"),
        ("L_long_only_stop_gap_1pct",longs,"stop_gap_1pct"),("LC_long_only_contraction_085_stop_gap_1pct",accepted,"stop_gap_1pct")):
        bundle=simulate(data,cfg,plan["development_start"],selected,updates,variant="crypto",
            risk=plan["risk_fraction"],scenario=scenario,end_time=end)
        trades=bundle["trades"]
        for t in trades:
            side=1 if t["side"]=="long" else -1
            pnl=side*t["quantity"]*(t["exit_price"]-t["entry_price"])-t["fees_usdt"]+t["funding_net_usdt"]
            if not math.isclose(pnl,t["net_pnl_usdt"],abs_tol=1e-8): raise AssertionError("trade_ledger")
        peak=plan["initial_equity_usdt"];mdd=0.0
        for row in bundle["curve"]:
            peak=max(peak,row["equity_usdt"]);mdd=max(mdd,1-row["equity_usdt"]/peak)
        if not math.isclose(mdd,bundle["summary"]["max_drawdown"],abs_tol=1e-10): raise AssertionError("nav_mdd")
        events={}
        event_rs=defaultdict(list)
        for t in trades:
            event=t["signal"].get("event_id") or t["decision_time"]
            events[event]=events.get(event,0)+t["net_pnl_usdt"]
        net_r=[t["net_pnl_usdt"]/(t["quantity"]*abs(t["entry_price"]-t["initial_stop"])) for t in trades]
        for t,r in zip(trades,net_r):
            event_rs[t["signal"].get("event_id") or t["decision_time"]].append(r)
        bundle["summary"].update({"mean_net_r":statistics.mean(net_r) if net_r else None,
            "event_count":len(events),"event_equal_weight_mean_net_usdt":statistics.mean(events.values()) if events else None,
            "event_equal_weight_mean_net_r":statistics.mean(statistics.mean(v) for v in event_rs.values()) if event_rs else None,
            "symbol_trade_counts":dict(Counter(t["symbol"] for t in trades))})
        write_json(args.output/f"{name}.json",bundle)
        results[name]=bundle["summary"]
    summary={"runs":results,"compression":json.loads((args.output/"compression-diagnostic.json").read_text()),
        "research_only":True,"orders_authorized":False,"independent_oos":False}
    write_json(args.output/"summary.json",summary)
    report=["# Volatility contraction discovery","",f"Discovery: {plan['development_start']} to {plan['development_end_exclusive']} (end exclusive); this interval is consumed.",
        "","|Variant|Return|MDD|Trades|Mean net R|Events|","|---|---:|---:|---:|---:|---:|"]
    for name,s in results.items():
        if name.endswith("double_cost") or name.endswith("stop_gap_1pct"): continue
        r=f"{s['mean_net_r']:.3f}" if s["mean_net_r"] is not None else "—"
        report.append(f"|{name}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['trade_count']}|{r}|{s.get('event_count',0)}|")
    report += ["",plan["formula"],f"Accepted {len(accepted)}/{len(longs)} long signals at the fixed threshold {plan['threshold']:.2f}.",
        "This is discovery evidence only. The 2025 validation interval has already been consumed by the frozen L/A comparison and is not reused for this filter.",
        "Double-cost and 1% stop-gap full-account stress arms are saved alongside base runs.",""]
    (args.output/"report.md").write_text("\n".join(report))
    sources=[args.config,Path(plan["study_config"]),Path(plan["base_config"]),Path(__file__),
        Path("src/qount/research/small_account_breakout.py"),Path("src/qount/research/small_account_breakout_data.py"),
        Path("src/qount/research/small_account_breakout_study.py")]
    manifest={"created_at":dt.datetime.now(UTC).isoformat(),"source_hashes":{str(x):sha(x) for x in sources},
        "input_manifest_sha256":sha(args.cache/"continuous-manifest.json"),
        "files":{x.name:sha(x) for x in sorted(args.output.iterdir()) if x.is_file()},
        "sample_role":"discovery_consumed","research_only":True,"orders_authorized":False}
    write_json(args.output/"manifest.json",manifest);(args.output/"_COMPLETE").write_text(sha(args.output/"manifest.json")+"\n")
    return 0


if __name__=="__main__": raise SystemExit(main())
