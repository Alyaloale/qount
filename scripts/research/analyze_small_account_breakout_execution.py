"""Isolate lot/minimum effects at fixed capital; no executable portfolio returns."""
from __future__ import annotations

import argparse
import copy
import json
import statistics
from collections import Counter
from dataclasses import replace
from pathlib import Path

from qount.research.small_account_breakout import funding_budget, generate_signals, size_contract
from qount.research.small_account_breakout_data import sha, timestamp, write_json
from qount.research.small_account_breakout_study import load_continuous


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle",type=Path,required=True)
    p.add_argument("--cache",type=Path,default=Path("state/research_cache/small_account_breakout_v02_20261013"))
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists(): raise FileExistsError("refuse_overwrite_diagnostic")
    cfg=json.loads((args.bundle/"effective-config.json").read_text())
    study=json.loads((args.bundle/"study-config.json").read_text())
    data=load_continuous(args.cache,cfg,study)
    start,end=timestamp(study["development_start"]),timestamp(study["development_end_exclusive"])
    signals,_=generate_signals(data,cfg,start,end)
    records=[]
    for sig in signals:
        t=sig.decision_time+cfg["entry_delay_minutes"]*60
        if t>=end: continue
        price=data.minutes[sig.symbol][t].o*(1+sig.side*cfg["crypto_slippage_per_side"])
        if abs(price-sig.close)>cfg["max_entry_drift_atr"]*sig.atr: continue
        forecast=funding_budget(data.funding[sig.symbol],data.funding_intervals.get(sig.symbol,[]),
                                sig.decision_time,cfg["crypto_max_hold_hours"],cfg)["fraction"]
        friction=2*(cfg["crypto_fee_per_side"]+cfg["crypto_slippage_per_side"])+forecast
        liquidity=data.minutes[sig.symbol][t-60].v*cfg["max_minute_volume_participation"]
        actual_rule=data.rules[sig.symbol]
        ideal_rule=copy.deepcopy(actual_rule)
        for f in ideal_rule["filters"]:
            if f["filterType"] in {"LOT_SIZE","MARKET_LOT_SIZE"}:
                f.update({"stepSize":"0.000000000001","minQty":"0"})
            elif f["filterType"]=="MIN_NOTIONAL": f["notional"]="0"
        # A diagnostic symbol bypasses the historical BTC minimum only in the
        # fractional counterfactual. It is never fed to simulate or an order path.
        ideal_signal=replace(sig,symbol="FRACTIONAL_DIAGNOSTIC")
        for capital in (10.0,50.0,100.0):
            actual,reason=size_contract(sig,price,capital,0.02,friction,actual_rule,cfg,liquidity_quantity=liquidity)
            ideal,ideal_reason=size_contract(ideal_signal,price,capital,0.02,friction,ideal_rule,cfg,liquidity_quantity=liquidity)
            if not ideal: continue  # Isolate quantities after the identical non-quantity gates.
            records.append({"decision_time":sig.decision_time,"symbol":sig.symbol,"capital_usdt":capital,
                            "actual_reason":reason,"actual_quantity":actual.quantity if actual else None,
                            "fractional_quantity":ideal.quantity,
                            "fractional_quantity_lost":1-actual.quantity/ideal.quantity if actual else 1.0})
    comparisons=[]
    for capital in (10.0,50.0,100.0):
        rows=[r for r in records if r["capital_usdt"]==capital]
        feasible=[r for r in rows if r["actual_quantity"] is not None]
        comparisons.append({"capital_usdt":capital,"pre_quantity_eligible_signals":len(rows),
            "actual_quantity_feasible_signals":len(feasible),"blocked_by_minimum":sum(r["actual_reason"]=="minimum_order" for r in rows),
            "feasible_by_symbol":dict(Counter(r["symbol"] for r in feasible)),
            "median_quantity_lost_on_feasible_signals":statistics.median(r["fractional_quantity_lost"] for r in feasible) if feasible else None,
            "mean_quantity_lost_including_blocked_signals":statistics.mean(r["fractional_quantity_lost"] for r in rows) if rows else None})
    result={"diagnostic_only":True,"account_executable_return":False,"research_only":True,"orders_authorized":False,
            "definition":"Fixed equity for each D signal, fixed 2% risk and all non-quantity gates; remove only minimum quantity/notional and lot discretization for fractional counterfactual. Overlapping signals are not independent trades.",
            "bundle_manifest_sha256":sha(args.bundle/"manifest.json"),"script_sha256":sha(Path(__file__)),
            "comparisons":comparisons,"records":records}
    write_json(args.output,result)
    print(json.dumps(comparisons))
    return 0


if __name__=="__main__": raise SystemExit(main())
