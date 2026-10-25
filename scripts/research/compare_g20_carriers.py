"""Compare actual G20 leveraged ETFs with causal risk-matched 1x proxy ETFs."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import hashlib
import json
import math
from pathlib import Path

import analyze_g20_risk_budget as prior
from compare_g20_fixed_budget import schedule,INPUT,CASH_INPUT,ROOT
from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.research.dual_engine_execution_verify import verify_ledger
from qount.research.g20_carriers import proxy_schedule

ANCHORS=("monthly20","monthly15","weekly_cap15")


def attribution(run,dates,closes,opens):
    """Initial-capital P&L from prior units overnight and new units intraday."""
    by_symbol=defaultdict(float);costs=0.;units={};cash=1.;index={d:i for i,d in enumerate(dates)}
    for row in run["records"]:
        day=row["date"];previous=dates[index[day]-1]
        open_equity=cash+sum(q*opens[s][day] for s,q in units.items())
        for symbol in set(units)|set(row["units"]):
            by_symbol[symbol]+=units.get(symbol,0.)*(opens[symbol][day]-closes[symbol][previous])
            by_symbol[symbol]+=row["units"].get(symbol,0.)*(closes[symbol][day]-opens[symbol][day])
        costs+=open_equity*row["cost_fraction"]
        units,cash=row["units"],row["cash"]
    assert math.isclose(sum(by_symbol.values())-costs,run["records"][-1]["nav"]-1,abs_tol=1e-9)
    return dict(price_pnl_by_asset=dict(by_symbol),trading_cost_per_initial_capital=costs)


def pair_difference(leveraged,proxy):
    a,b=leveraged["attribution"],proxy["attribution"]
    ga,gb=defaultdict(float),defaultdict(float)
    for symbol,value in a["price_pnl_by_asset"].items():ga[G20_EXECUTION_TO_PROXY.get(symbol,symbol)]+=value
    for symbol,value in b["price_pnl_by_asset"].items():gb[symbol]+=value
    delta={s:gb[s]-ga[s] for s in set(ga)|set(gb)}
    cost=a["trading_cost_per_initial_capital"]-b["trading_cost_per_initial_capital"]
    return dict(proxy_minus_leveraged_terminal_nav=sum(delta.values())+cost,
        price_pnl_difference_by_proxy=delta,trading_cost_difference=cost)


def run(output):
    if output.exists():raise FileExistsError("preserve_previous_results")
    contract=json.loads((ROOT/"config/dual-engine-optimization-20261004.json").read_text())
    long_panel,_=prior.load_equity(INPUT/"inputs/long-equity",contract)
    recent=prior.recent_panel(CASH_INPUT/"market-cache/yahoo-public",end="2026-10-23")
    retained=json.loads((ROOT/"state/research_runs/g20_fixed_budget_20261025_final/results.json").read_text())
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        hypothesis="Same G20 sector and decision clock, actual leveraged carrier versus an unlevered proxy matched to prior 20-session full portfolio variance including BIL covariance.",
        assumptions=dict(cost_bps=[20,40],execution_delay_sessions=[1,2],risk_window=20,
            proxy_max_weight=1.,cash_asset="BIL",units="fractional total-return units; not broker shares",
            initial_nav=1.,taxes="before_personal_tax",signal_basis="adjusted_close"),
        caveats=["The 1x signal proxies need not share the leveraged ETF's exact benchmark; carrier/benchmark effects are confounded.",
            "Matching uses actual completed returns, not today's leveraged multiple; embedded fund expenses are not charged twice.",
            "Equal risk is an estimate at decision close only; realized risk, monthly drift and delay differ.",
            "No full-history cash-dividend pay dates, lot/minimum-fee/auction-depth or independent OOS certification."],
        posthoc_diagnostic="After the first carrier results concentrated gains in SOXL-to-SMH, retain SOXL on its selected dates and replace only the other carriers. Diagnostic only, not a preselected strategy or new OOS evidence.",
        panels={},checks=dict(unit_ledgers=0,attributions=0,retained_controls=0))
    for name,panel,start in (("long",long_panel,"2018-04-02"),("recent",recent,"2026-01-02")):
        closes,opens=prior.prices(panel);runs={};risk={};paired={}
        for anchor in ANCHORS:
            lev=schedule(panel,anchor)
            unlev,diagnostics=proxy_schedule(panel.dates,panel.total_closes,lev)
            first=next(i for i,d in enumerate(panel.dates) if d>=start)
            used=[r for r in diagnostics if r["index"]>=first-2 and r["index"]<len(panel.dates)-1]
            risk[anchor]=dict(decisions=used,status_counts=dict(Counter(r["status"] for r in used)),
                mean_proxy_target=sum(r["weight"] for r in used)/len(used),
                max_abs_risk_gap=max(abs(r["risk_gap"]) for r in used),
                mean_risk_gap=sum(r["risk_gap"] for r in used)/len(used))
            for cost in (20,40):
                for delay in (1,2):
                    keys=[]
                    variants=[("leveraged",lev),("proxy",unlev)]
                    if (cost,delay) in ((20,1),(40,2)):
                        hybrid={i:(lev[i] if lev[i].get("SOXL",0)>0 else target) for i,target in unlev.items()}
                        variants.append(("proxy_except_SOXL",hybrid))
                    for carrier,targets in variants:
                        targets=dict(targets);targets.setdefault(first-delay,{"BIL":1.})
                        book=prior.replay_units(panel.dates,closes,opens,targets,start=start,lag=delay,cost_bps=cost,cash_asset="BIL")
                        for row in book["records"]:
                            row["post_open_weights"]=row["target_weights"] if row["target_weights"] is not None else row["pretrade_weights"]
                            assert row["signal_date"] is None or row["signal_date"]<row["date"]
                        verify_ledger(book,dict(dates=panel.dates,opens=opens,closes=closes,cash_asset="BIL"),252,cost_bps=cost)
                        result["checks"]["unit_ledgers"]+=1
                        m=prior.metrics(book)
                        if name=="recent":
                            for k in ("cagr","cagr_calendar","calmar_calendar"):m.pop(k,None)
                        if carrier=="leveraged":
                            old=retained["panels"][name][f"{anchor}-c{cost}-d{delay}"]["metrics"]
                            assert all(math.isclose(m[k],v,abs_tol=1e-12) if isinstance(v,(int,float)) else m[k]==v for k,v in old.items())
                            result["checks"]["retained_controls"]+=1
                        contribution=attribution(book,panel.dates,closes,opens)
                        result["checks"]["attributions"]+=1
                        key=f"{anchor}-{carrier}-c{cost}-d{delay}";keys.append(key)
                        runs[key]=dict(metrics=m,attribution=contribution,
                            annual={y:prior.slice_metrics(book["records"],y+"-01-01",y+"-12-31") for y in sorted({r["date"][:4] for r in book["records"]})},
                            records=[{k:r[k] for k in ("date","nav","return","cash_return","risk_gross","turnover","cost_fraction")} for r in book["records"]])
                    paired[f"{anchor}-c{cost}-d{delay}"]=pair_difference(runs[keys[0]],runs[keys[1]])
                    assert math.isclose(paired[f"{anchor}-c{cost}-d{delay}"]["proxy_minus_leveraged_terminal_nav"],
                        runs[keys[1]]["records"][-1]["nav"]-runs[keys[0]]["records"][-1]["nav"],abs_tol=1e-9)
            print(name,anchor,"completed; risk",risk[anchor]["status_counts"],flush=True)
        result["panels"][name]=dict(runs=runs,risk_matching=risk,paired=paired)
    paths=list((INPUT/"inputs/long-equity").glob("*"))+list((CASH_INPUT/"market-cache/yahoo-public").glob("*.json"))
    paths+=[Path(__file__),ROOT/"src/qount/research/g20_carriers.py",ROOT/"scripts/research/compare_g20_fixed_budget.py",
            ROOT/"scripts/research/analyze_g20_risk_budget.py",ROOT/"src/qount/research/dual_engine_structural.py"]
    result["source_hashes"]={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    output.mkdir(parents=True)
    (output/"results.json").write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
    brief={**result,"panels":{n:{**v,"runs":{k:{a:b for a,b in r.items() if a!="records"} for k,r in v["runs"].items()},
        "risk_matching":{k:{a:b for a,b in r.items() if a!="decisions"} for k,r in v["risk_matching"].items()}} for n,v in result["panels"].items()}}
    (output/"summary.json").write_text(json.dumps(brief,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps(dict(output=str(output),checks=result["checks"])))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    run(parser.parse_args().output)
