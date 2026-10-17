"""Independently replay saved continuous cash/mark NAV and funding accounting."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from qount.research.small_account_breakout import MarketData, generate_signals
from qount.research.small_account_breakout_data import sha, timestamp, write_json
from qount.research.small_account_breakout_study import load_continuous


def near(a,b):
    if not math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8): raise AssertionError(f"mismatch:{a}:{b}")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle",type=Path,required=True)
    p.add_argument("--cache",type=Path,default=Path("state/research_cache/small_account_breakout_v02_20261013"))
    p.add_argument("--receipt",type=Path,required=True)
    args=p.parse_args()
    if args.receipt.exists(): raise FileExistsError("refuse_overwrite_receipt")
    root=args.bundle
    manifest=json.loads((root/"manifest.json").read_text())
    if (root/"_COMPLETE").read_text().strip()!=sha(root/"manifest.json"): raise AssertionError("complete_hash")
    for name,expected in manifest["files"].items():
        if sha(root/name)!=expected: raise AssertionError(f"artifact_hash:{name}")
    for name,expected in manifest["source_hashes"].items():
        if sha(Path(name))!=expected: raise AssertionError(f"source_hash:{name}")
    study=json.loads((root/"study-config.json").read_text())
    cfg=json.loads((root/"effective-config.json").read_text())
    summary=json.loads((root/"summary.json").read_text())
    data=load_continuous(args.cache,cfg,study)
    start,end=timestamp(study["development_start"]),timestamp(study["development_end_exclusive"])
    checks=[]
    for saved in summary["runs"]:
        name=saved["name"]
        bundle=json.loads((root/f"{name}.json").read_text())
        if saved!=bundle["summary"]: raise AssertionError("summary_disagreement")
        trades=bundle["trades"]
        events=defaultdict(float)
        last_exit=None
        for trade in trades:
            entry,exit=timestamp(trade["entry_time"]),timestamp(trade["exit_time"])
            if last_exit is not None and entry<=last_exit: raise AssertionError("overlapping_positions")
            if not start<=timestamp(trade["decision_time"])<entry<=exit<=end: raise AssertionError("trade_time")
            last_exit=exit
            side=1 if trade["side"]=="long" else -1
            q=trade["quantity"]
            funding=0.0
            for f in data.funding[trade["symbol"]]:
                settled=int(f["fundingTime"])//60000*60
                if entry<settled<=exit and settled<end:
                    payment=-side*q*float(f["markPrice"])*float(f["fundingRate"])
                    events[settled]+=payment
                    funding+=payment
            near(funding,trade["funding_net_usdt"])
            fee_rate=cfg["crypto_fee_per_side"]*(2 if saved["scenario"]=="double_cost" else 1)
            entry_fee=trade["entry_price"]*q*fee_rate
            events[entry]-=entry_fee
            gross=side*q*(trade["exit_price"]-trade["entry_price"])
            events[min(exit,end-60)]+=gross-(trade["fees_usdt"]-entry_fee)
            near(gross-trade["fees_usdt"]+funding,trade["net_pnl_usdt"])
            near(trade["net_pnl_usdt"]/(q*abs(trade["entry_price"]-trade["initial_stop"])),trade["diagnostic"]["net_r"])
            if trade["planned_risk_usdt"]>trade["risk_budget_usdt"]+1e-8: raise AssertionError("risk_budget")
            if trade["exit_reason"]=="breakout_failure":
                decision=exit-cfg["entry_delay_minutes"]*60
                completed=next(b for b in data.hours[trade["symbol"]] if b.t+3600==decision)
                boundary=trade["signal"]["breakout_high" if side==1 else "breakout_low"]
                if decision<=entry or side*(completed.c-boundary)>0: raise AssertionError("failure_exit_clock")
        cash=peak=saved["initial_equity_usdt"]
        mdd=0.0
        index=0
        points=0
        with (root/f"{name}_equity.csv").open() as stream:
            for row in csv.DictReader(stream):
                t=timestamp(row["time"])-60
                if t!=start+points*60: raise AssertionError("continuous_nav_time")
                points+=1
                cash+=events.get(t,0)
                while index<len(trades) and timestamp(trades[index]["exit_time"])<=t:
                    index+=1
                active=trades[index] if index<len(trades) and timestamp(trades[index]["entry_time"])<=t else None
                if active and active["exit_reason"]=="sample_end" and t==end-60: active=None
                nav=cash
                if active:
                    side=1 if active["side"]=="long" else -1
                    nav+=side*active["quantity"]*(data.marks[active["symbol"]][t].c-active["entry_price"])
                near(nav,float(row["equity_usdt"]))
                if (row["position"] or None)!=(active["symbol"] if active else None): raise AssertionError("position_state")
                peak=max(peak,nav); mdd=max(mdd,1-nav/peak)
        near(cash,saved["final_equity_usdt"])
        near(mdd,saved["max_drawdown"])
        if points!=(end-start)//60: raise AssertionError("nav_length")
        checks.append({"name":name,"trades":len(trades),"nav_points":points,"status":"passed"})
    cut=start+98*86400
    full,_=generate_signals(data,cfg,start,end,simple=True)
    prefix_data=MarketData({}, {},{s:[b for b in rows if b.t+3600<=cut] for s,rows in data.hours.items()}, {}, {}, {})
    prefix,_=generate_signals(prefix_data,cfg,start,cut,simple=True)
    if prefix!=[s for s in full if s.decision_time<cut]: raise AssertionError("future_signal_leak")
    receipt={"status":"passed","bundle_manifest_sha256":sha(root/"manifest.json"),"verifier_sha256":sha(Path(__file__)),
        "runs":checks,"ledger_trades":sum(r["trades"] for r in checks),"nav_points":sum(r["nav_points"] for r in checks),
        "causal_raw_signal_prefix_count":len(prefix),"research_only":True,"orders_authorized":False,
        "scope":"Independent saved cash, actual funding, minute mark NAV, drawdown, R and clock checks; not orderbook certification"}
    write_json(args.receipt,receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k!="runs"}))
    return 0


if __name__=="__main__": raise SystemExit(main())
