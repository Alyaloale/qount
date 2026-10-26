"""Integer-share/cash-payable validation of the G20 semiconductor SMH candidate."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime,time
from functools import partial
import hashlib
import json
import math
from pathlib import Path
from statistics import stdev

import analyze_g20_risk_budget as prior
from compare_g20_fixed_budget import ROOT,CASH_INPUT,schedule
from qount.dual_engine import g20_cash as ledger
from qount.research.g20_carriers import proxy_schedule
from qount.research.g20_cash_execution import CashFriction,rebalance_cash

SYMBOLS=(*ledger.SYMBOLS,"SMH")
CASES={"integer20":(CashFriction(),1),"fractional20":(CashFriction(lot=0),1),
       "integer20_floor035":(CashFriction(minimum_commission=.35),1),
       "integer20_floor1":(CashFriction(minimum_commission=1.),1),
       "integer40":(CashFriction(cost_bps=40,commission_bps=10),1),
       "integer20_delay2":(CashFriction(),2),
       "integer40_delay2":(CashFriction(cost_bps=40,commission_bps=10),2),
       "integer40_floor1_delay2":(CashFriction(cost_bps=40,commission_bps=10,minimum_commission=1.),2)}


def simulate(panel,panels,actions,targets,*,capital,friction,delay):
    first=next(i for i,d in enumerate(panel.dates) if d>="2026-01-02")
    data=ledger.new_account("2026-10-26T00:00:00+00:00")
    data["initial_equity"]=capital;data["layer"]["sleeves"]["g20"]["cash"]=capital
    def plan(j):
        return dict(target=targets[j],decision_date=panel.dates[j],
            available_at=datetime.combine(datetime.fromisoformat(panel.dates[j]),time(16),ledger.NY).isoformat())
    # A delayed new account stays in cash until its eligible scheduled signal;
    # do not manufacture an initial trade from a stale previous-month winner.
    data["pending"]=plan(first-delay) if first-delay in targets else None
    rebalance=partial(rebalance_cash,friction=friction)
    for i in range(first,len(panel.dates)):
        day=panel.dates[i]
        if i>first and i-delay in targets:
            j=i-delay
            data["pending"]=plan(j)
        data=ledger.step(data,day=day,bar={s:panels[s][day] for s in SYMBOLS},
            actions=actions.get(day,[]),decision=None,
            opening=datetime.combine(datetime.fromisoformat(day),time(9,30),ledger.NY),
            observed_at="2026-10-26T00:00:00+00:00",reconstructed=True,historical_replay=True,
            execution_symbols=SYMBOLS,rebalance=rebalance)
    rows=data["observations"];peak=capital;dd=0.;weights=[];returns=[];previous=capital
    for row in rows:
        returns.append(row["equity"]/previous-1);previous=row["equity"]
        peak=max(peak,row["equity"]);dd=max(dd,1-row["equity"]/peak)
        weights.append(sum(p["weight"] for p in row["positions"] if p["symbol"] not in ("BIL","DIVIDEND_RECEIVABLE")))
    # Independent cash-flow and final share-count reconciliation.
    cash=capital;held={}
    for t in data["trades"]:
        assert t["side"] in ("BUY","SELL") and t["decision_date"]<t["date"]
        sign=1 if t["side"]=="BUY" else -1
        assert math.isclose(t["cost"],friction.fee(t["quantity"]*t["price"]),abs_tol=1e-9)
        t["commission"]=max(t["quantity"]*t["price"]*friction.commission_bps/10000,friction.minimum_commission)
        t["slippage_charge"]=t["quantity"]*t["price"]*(friction.cost_bps-friction.commission_bps)/10000
        assert math.isclose(t["commission"]+t["slippage_charge"],t["cost"],abs_tol=1e-9)
        if friction.lot:assert math.isclose(t["quantity"]/friction.lot,round(t["quantity"]/friction.lot),abs_tol=1e-8)
        held[t["symbol"]]=held.get(t["symbol"],0)+sign*t["quantity"]
        cash-=sign*t["quantity"]*t["price"]+t["cost"]
        t["note"]=f"历史模型：收盘信号后延迟{delay}个交易日开盘；非真实成交"
    paid=sum(e["value"] for e in data["income"] if e["side"]=="DIVIDEND_PAYMENT")
    assert math.isclose(cash+paid,rows[-1]["cash"],abs_tol=1e-7)
    assert math.isclose(paid,data["distributions_received"],abs_tol=1e-8)
    for s,q in data["layer"]["sleeves"]["g20"]["positions"].items():assert math.isclose(held.get(s,0),q,abs_tol=1e-8)
    metrics=dict(capital=capital,start=rows[0]["date"],end=rows[-1]["date"],total_return=rows[-1]["equity"]/capital-1,
        max_drawdown=dd,final_equity=rows[-1]["equity"],trade_count=len(data["trades"]),
        cost=data["layer"]["cumulative_cost"],paid=paid,receivable=rows[-1]["receivable"],
        commission=sum(t["commission"] for t in data["trades"]),slippage_charge=sum(t["slippage_charge"] for t in data["trades"]),
        average_risk_weight=sum(weights)/len(weights),final_cash=rows[-1]["cash"],positions=rows[-1]["positions"])
    metrics.update(volatility_estimate_annualized=stdev(returns)*math.sqrt(252),
                   zero_risk_session_fraction=sum(w<1e-12 for w in weights)/len(weights))
    return dict(metrics=metrics,records=rows,trades=data["trades"],income=data["income"])


def run(output):
    if output.exists():raise FileExistsError("preserve_old_results")
    panel=prior.recent_panel(CASH_INPUT/"market-cache/yahoo-public",end="2026-10-23")
    cache={s:json.loads((CASH_INPUT/"market-cache/yahoo-public"/(s+"-1d.json")).read_text()) for s in {*SYMBOLS,*ledger.G20_PROXY_SYMBOLS}}
    policy=json.loads((ROOT/"config/g20-cash-distributions.json").read_text())
    policy["sources"]["vaneck"]="https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/"
    policy["pay_dates"]["vaneck"]={"2025-12-22":"2025-12-26"}
    panels,actions,_=ledger.normalize_cache(cache,policy,execution_symbols=SYMBOLS,issuer_groups={"SMH":"vaneck"})
    # The observed period contains no SMH distributions; never invent pay dates.
    assert not any(a["symbol"]=="SMH" for day,v in actions.items() if "2026-01-02"<=day<="2026-10-23" for a in v if a["kind"]=="dividend")
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        scope="2026 cash model only; no evidence of long-window cash executability or live fills",
        dividend_policy=policy,cases={k:dict(friction=asdict(f),delay=d) for k,(f,d) in CASES.items()},
        caveats=["Base friction is 5bp commission plus 15bp slippage cash charge; stress is 10+30bp. Commission floors are scenario assumptions, not an exact broker tariff.",
            "Fractional account is a model control, not proof of brokerage eligibility.",
            "No personal withholding tax, exchange/FX fees, auction depth or partial fills.",
            "Matched risk targets do not guarantee equal realized risk after integer rounding."],
        checks=dict(cash_books=0,paper_control_points=0,previous_cash_controls=0),runs={})
    previous=json.loads((ROOT/"state/research_runs/g20_fixed_budget_20261025_final/results.json").read_text())["cash"]
    for anchor in ("monthly20","monthly15","weekly_cap15"):
        original=schedule(panel,anchor);proxy,_=proxy_schedule(panel.dates,panel.total_closes,original)
        hybrid={i:(proxy[i] if t.get("SOXL",0)>0 else t) for i,t in original.items()}
        for capital in (1000.,10000.):
            for label,(friction,delay) in CASES.items():
                for name,targets in (("original",original),("SMH",hybrid)):
                    r=simulate(panel,panels,actions,targets,capital=capital,friction=friction,delay=delay)
                    if label=="integer20" and name=="original":
                        old=next(x for x in previous if x["rule"]==anchor and x["capital"]==capital)
                        assert [(x["date"],x["equity"]) for x in r["records"]]==[(x["date"],x["equity"]) for x in old["records"]]
                        result["checks"]["previous_cash_controls"]+=1
                    if anchor=="monthly20" and capital==10000 and label=="integer20" and name=="original":
                        old=json.loads((CASH_INPUT/"g20-cash/forward.json").read_text())["observations"]
                        assert [(x["date"],x["equity"]) for x in r["records"]]==[(x["date"],x["equity"]) for x in old]
                        result["checks"]["paper_control_points"]=len(old)
                    key=f"{anchor}-{name}-{int(capital)}-{label}"
                    result["runs"][key]=r;result["checks"]["cash_books"]+=1
            print(anchor,capital,"done",flush=True)
    paths=[Path(__file__),ROOT/"src/qount/research/g20_cash_execution.py",ROOT/"src/qount/dual_engine/g20_cash.py",ROOT/"src/qount/research/g20_carriers.py",ROOT/"config/g20-cash-distributions.json"]
    paths+=list((CASH_INPUT/"market-cache/yahoo-public").glob("*.json"))
    result["source_hashes"]={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    output.mkdir(parents=True)
    (output/"results.json").write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
    brief={**result,"runs":{k:v["metrics"] for k,v in result["runs"].items()}}
    (output/"summary.json").write_text(json.dumps(brief,ensure_ascii=False,indent=2))
    print(json.dumps(result["checks"]))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",type=Path,required=True)
    run(p.parse_args().output)
