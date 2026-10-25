#!/usr/bin/env python3
"""Daily order-free ETF timing and frozen regime paper accounts.

Each account starts at its actual first observation. Older downloaded bars are
warmup only. Missed subsequent sessions are explicitly reconstructed, never
backdated as observed forward decisions. No exchange client or credentials.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import fcntl
import json
import math
from pathlib import Path

from qount.contracts import canonical_hash
from qount.research_data.macro_live import write_json
from qount.research_data.paper_daily import yahoo_rows, tencent_etf_rows

# Explicit pre-v1.4 switches: later green/decay/cash-yield optimizations are off.
REGIME = dict(mode="1X_SPOT", causality_mode="RIGOROUS", max_positions=2,
    min_atr_pct=.0085, strict_golden_cross=True, breakout_quality_filter=True,
    dynamic_max_pos=True, orthogonal_tier_limit=True, gap_stress_pct=.015, er_min=.28,
    mr_require_green=False, mr_max_hold_days=15, mr_edge_decay=False,
    stagnant_exit_days=None, min_rs60=None, edge_decay_exit=False, enable_cash_overlay=False)


def etf_step(state, rows, *, genesis, decision_available_at=None, rules=None):
    from qount.research.personal_trading_assistant import StateMachineState, TrendTimingStateMachine
    sm=TrendTimingStateMachine()
    if genesis:
        machine=StateMachineState()
        for i,r in enumerate(rows):
            ma=sum(x["adjClose"] for x in rows[i-119:i+1])/120 if i>=119 else None
            machine=sm.update_at_close(machine,r["adjClose"],ma)
        return dict(cash=100000.,quantity=0.,machine=dataclasses.asdict(machine),
                    factor=rows[-1]["adjClose"]/rows[-1]["close"]),100000.,[],[]
    old=rows[-2];bar=rows[-1]
    factor=bar["adjClose"]/bar["close"]
    if not math.isclose(factor,old["adjClose"]/old["close"],rel_tol=2e-4):
        raise ValueError("etf_corporate_action_requires_reconciliation")
    machine=StateMachineState(**state["machine"])
    cash,qty=state["cash"],state["quantity"]
    rules=rules or {}
    commission=rules.get("commission_bps",6)/10000
    slippage=rules.get("slippage_bps",5)/10000
    lot=rules.get("lot_size",100)
    if qty==0 and cash>0:
        cash*=(1+rules.get("cash_apr",0))**(1/252)
    trades=[]
    from qount.research_data.paper_daily import SH
    opening=dt.datetime.combine(dt.date.fromisoformat(bar["date"]),dt.time(9,30),SH)
    can_fill=decision_available_at is None or dt.datetime.fromisoformat(decision_available_at)<=opening
    if can_fill and machine.current_target==1 and qty==0:
        px=bar["open"]*(1+slippage)
        amount=cash/(px*(1+commission))
        if lot:amount=math.floor(amount/lot)*lot
        if amount:
            fee=amount*px*commission;cash-=amount*px+fee;qty=amount
            trades.append(dict(date=bar["date"],symbol="513100.SH",side="BUY",quantity=qty,price=px,cost=fee))
    elif can_fill and machine.current_target==0 and qty:
        px=bar["open"]*(1-slippage);fee=qty*px*commission;cash+=qty*px-fee
        trades.append(dict(date=bar["date"],symbol="513100.SH",side="SELL",quantity=qty,price=px,cost=fee));qty=0.
    machine.executed_state=float(qty>0)
    machine=sm.update_at_close(machine,bar["adjClose"],sum(r["adjClose"] for r in rows[-120:])/120)
    equity=cash+qty*bar["close"]
    positions=[dict(symbol="513100.SH",quantity=qty,price=bar["close"],market_value=qty*bar["close"],
                    weight=qty*bar["close"]/equity)] if qty else []
    return dict(cash=cash,quantity=qty,machine=dataclasses.asdict(machine),factor=factor),equity,positions,trades


def regime_step(state, panel, root, *, genesis, decision_available_at=None):
    from qount.legacy.universal_regime.engine import run_regime_backtest
    daily=root/"daily"
    daily.mkdir(parents=True,exist_ok=True)
    for symbol,rows in panel.items():
        with (daily/(symbol+"_daily.csv")).open("w") as f:
            out=csv.writer(f);out.writerow(["Date","Open","High","Low","Close","Volume"])
            out.writerows([r["date"],r["open"],r["high"],r["low"],r["close"],r["volume"]] for r in rows)
    day=panel["SPY"][-1]["date"]
    if state and decision_available_at:
        from qount.research_data.paper_daily import NY
        opening=dt.datetime.combine(dt.date.fromisoformat(day),dt.time(9,30),NY)
        if dt.datetime.fromisoformat(decision_available_at)>opening:
            import copy
            state=copy.deepcopy(state);state["pending_orders"]=[]
    result=run_regime_backtest(start_date=day,end_date=day,data_dir=str(daily),
        opening_state=None if genesis else state,return_state=True,**REGIME)
    new=result["paper_state"];equity=result["final_equity"]
    positions=[];trades=[]
    for symbol,pos in new["active_positions"].items():
        close=panel[symbol][-1]["close"]
        positions.append(dict(symbol=symbol,quantity=pos["qty"],price=close,entry_date=pos["entry_date"],
                              market_value=pos["qty"]*close,weight=pos["qty"]*close/equity))
    old_positions=(state or {}).get("active_positions",{})
    for symbol in set(old_positions)|set(new["active_positions"]):
        old=old_positions.get(symbol,{});cur=new["active_positions"].get(symbol,{})
        change=cur.get("qty",0)-old.get("qty",0)
        if abs(change)<1e-10:continue
        closed=[t for t in result["trades"] if t["symbol"]==symbol]
        px=cur.get("entry_price") if change>0 else (closed[-1].get("exit_price") if closed else None)
        trades.append(dict(date=day,symbol=symbol,side="BUY" if change>0 else "SELL",
                           quantity=abs(change),price=px,cost=abs(change)*px*.0003 if px else None))
    return new,equity,positions,trades


def run_account(kind,root,observed):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    path=root/"forward.json"
    with (root/"paper.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        data=json.loads(path.read_text()) if path.exists() else None
        try:
            if kind=="etf":
                rows,digest=tencent_etf_rows(observed,root/"cache")
                panel={"513100.SH":rows};source="tencent_public_raw_and_qfq";initial=100000.
            else:
                from qount.legacy.universal_regime.engine import ALL_10_MACRO_SYMBOLS
                panel={};hashes={}
                for symbol in ALL_10_MACRO_SYMBOLS:
                    panel[symbol],hashes[symbol]=yahoo_rows(symbol,observed,root/"cache",
                        start=dt.datetime(2024,1,1,tzinfo=dt.timezone.utc))
                digest=canonical_hash(hashes);source="yahoo_public";initial=1000.
                common=set.intersection(*(set(r["date"] for r in rs) for rs in panel.values()))
                if not common:raise ValueError("regime_common_daily_input_missing")
                last=max(common)
                panel={s:[r for r in rs if r["date"]<=last] for s,rs in panel.items()}
            calendar=[r["date"] for r in next(iter(panel.values()))]
            if min(len(rs) for rs in panel.values())<250:raise ValueError("paper_warmup_short")
            genesis=data is None
            if genesis:
                data=dict(schema_version=1,kind=kind,created_at=observed.isoformat(),initial_equity=initial,
                    state=None,observations=[],trades=[],research_only=True,orders_authorized=False,
                    rules=REGIME if kind=="regime" else dict(ma=120,band=.015,confirmation=2,lot_size=100,
                        commission_bps=6,slippage_bps=5,cash_apr=0),source=source)
                pending=[calendar[-1]]
            else:
                if data["source"]!=source or data["orders_authorized"] is not False:
                    raise ValueError("paper_identity_changed")
                pending=[d for d in calendar if d>data["observations"][-1]["date"]]
            initial=data["initial_equity"]
            for n,day in enumerate(pending):
                subset={s:[r for r in rs if r["date"]<=day] for s,rs in panel.items()}
                # A missing market session cannot be replaced by another asset's bar.
                if any(rs[-1]["date"]!=day for rs in subset.values()):raise ValueError("paper_session_incomplete")
                if kind=="etf":
                    state,equity,positions,trades=etf_step(data["state"],subset["513100.SH"],genesis=genesis,
                        decision_available_at=(data["observations"][-1]["recorded_at"] if data["observations"] else None)
                            if not data.get("continuous") else None,rules=data["rules"])
                else:
                    state,equity,positions,trades=regime_step(data["state"],subset,root,genesis=genesis,
                        decision_available_at=data["observations"][-1]["recorded_at"] if data["observations"] else None)
                record_kind="genesis" if genesis else "reconstructed" if len(pending)>1 else "forward"
                if data.get("continuous"):
                    from qount.research_data.paper_daily import SH
                    opening=dt.datetime.combine(dt.date.fromisoformat(day),dt.time(9,30),SH)
                    if dt.datetime.fromisoformat(data["observations"][-1]["recorded_at"])>opening:
                        record_kind="reconstructed"
                data["state"]=state
                data["observations"].append(dict(date=day,equity=equity,positions=positions,
                    recorded_at=observed.isoformat(),sample_kind=record_kind,source_hash=digest))
                if data.get("benchmark_quantity") is not None:
                    data["observations"][-1]["benchmark_nav"]=data["benchmark_quantity"]*subset["513100.SH"][-1]["close"]/initial
                data["trades"].extend(dict(t,sample_kind=record_kind,recorded_at=observed.isoformat()) for t in trades)
                genesis=False
            data.update(observed_at=observed.isoformat(),source_hash=digest,last_error=None)
            write_json(path,data)
            return dict(kind=kind,status="READY",as_of=calendar[-1],observations=len(data["observations"]),
                        appended=len(pending),research_only=True,orders_authorized=False)
        except Exception as exc:
            if data is not None and data.get("observations"):
                data.update(observed_at=observed.isoformat(),last_error=type(exc).__name__+":"+str(exc)[:100])
                write_json(path,data)
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root",type=Path,required=True)
    parser.add_argument("--kind",choices=("etf","regime","all"),default="all")
    parser.add_argument("--registry",type=Path)
    parser.add_argument("--db",type=Path)
    args=parser.parse_args();now=dt.datetime.now(dt.timezone.utc);failed=False
    for kind in (("etf","regime") if args.kind=="all" else (args.kind,)):
        try:result=run_account(kind,args.state_root/kind,now)
        except Exception as exc:result=dict(kind=kind,status="ERROR",error=type(exc).__name__+":"+str(exc)[:100]);failed=True
        print(json.dumps(result))
    if args.registry and args.db:
        from qount.api.ingest import run_ingest
        result=run_ingest(str(args.registry),str(args.db))
        print(json.dumps(dict(ingest_status=result['status'],processed=result['processed'],failed_lines=result['failed_lines'])))
        failed |= bool(result['failed_lines'])
    return int(failed)


if __name__=="__main__":
    raise SystemExit(main())
