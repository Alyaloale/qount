"""Offline G20 volatility timing versus fixed capital budgets and account size."""
from __future__ import annotations

import argparse
from datetime import datetime, time
import hashlib
import json
import math
from pathlib import Path

import analyze_g20_risk_budget as prior
from qount.dual_engine import g20_cash as cash_book
from qount.research.dual_engine_execution_verify import verify_ledger

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT/"state/research_runs/g20_risk_synthesis_20261025"
CASH_INPUT = ROOT/"state/research_runs/g20_cash_repair_20261025/paper"
RULES = ("monthly20", "monthly18", "monthly15", "monthly10", "weekly18", "weekly_cap15")


def schedule(panel, rule):
    if rule in ("monthly20", "weekly_cap15"):
        return prior.targets(panel, rule)
    if rule not in RULES:
        raise ValueError("unknown_rule")
    weight = int(rule[-2:])/100
    source = prior.targets(panel, "weekly20" if rule.startswith("weekly") else "monthly20")
    return {i:{next(s for s in target if s != "BIL"):weight, "BIL":1-weight}
            for i,target in source.items()}


def cash_replay(panel, panels, actions, *, rule, capital):
    """Same cash/dividend/integer-share implementation as the revised paper book."""
    targets=schedule(panel,rule)
    first=next(i for i,d in enumerate(panel.dates) if d >= "2026-01-02")
    data=cash_book.new_account("2026-10-25T00:00:00+00:00")
    data["initial_equity"]=capital
    data["layer"]["sleeves"]["g20"]["cash"]=capital
    known=max(i for i in targets if i < first)
    data["pending"]=dict(target=targets[known],decision_date=panel.dates[known],
        available_at=datetime.combine(datetime.fromisoformat(panel.dates[known]),time(16),cash_book.NY).isoformat())
    for i in range(first,len(panel.dates)):
        day=panel.dates[i]
        data=cash_book.step(data,day=day,bar={s:panels[s][day] for s in cash_book.SYMBOLS},
            actions=actions.get(day,[]),decision=targets.get(i),
            opening=datetime.combine(datetime.fromisoformat(day),time(9,30),cash_book.NY),
            observed_at="2026-10-25T00:00:00+00:00",reconstructed=True,historical_replay=True)
    rows=data["observations"];peak=capital;dd=0
    risk=[];active=0;deviations=[]
    current_target=targets[known]
    for i,r in enumerate(rows,first):
        if i-1 in targets:current_target=targets[i-1]
        w=sum(p["weight"] for p in r["positions"] if p["symbol"] not in ("BIL","DIVIDEND_RECEIVABLE"))
        risk.append(w);active+=w>1e-12
        deviations.append(abs(w-sum(v for s,v in current_target.items() if s!="BIL")))
        peak=max(peak,r["equity"]);dd=max(dd,1-r["equity"]/peak)
    return dict(capital=capital,rule=rule,first=rows[0]["date"],last=rows[-1]["date"],
        total_return=rows[-1]["equity"]/capital-1,max_drawdown=dd,
        final_equity=rows[-1]["equity"],cost=data["layer"]["cumulative_cost"],
        distributions_received=data["distributions_received"],
        trade_count=len(data["trades"]),average_risk_weight=sum(risk)/len(risk),
        active_session_fraction=active/len(rows),mean_target_deviation=sum(deviations)/len(rows),
        final=rows[-1],records=rows,trades=data["trades"])


def macro_scale():
    """Keep current gates/capacity; do not multiply the 15-dollar NAV curve."""
    from compare_macro_trend_continuation import extended_inputs
    from qount.research.binance_macro_opportunities import cost_case
    from qount.research.binance_etf_leverage import replay
    from study_macro_admission_and_simplicity import headline, verify
    import copy
    previous=json.loads((ROOT/"state/research_runs/macro_trend_continuation_20261022/comparison.json").read_text())
    _,(book,signals,gates,caps),sources,_=extended_inputs(False)
    venue_path=ROOT/"state/research_runs/macro_leverage_cash_review_20261019/venue_snapshot.json"
    venue=json.loads(venue_path.read_text())
    for symbol,data in book.items():data["rule"]=dict(data["rule"],leverage_brackets=venue["symbols"][symbol]["brackets"])
    runs=[]
    for capital in (15.27112826,100.,1000.,10000.):
        for scenario in ("base","double_cost"):
            control=next(x for x in previous["portfolios"] if x["window"]=="extended" and
                         x["profile"]=="control" and x["scenario"]==scenario)
            parameters=copy.deepcopy(control["parameters"]);parameters["capital"]=capital
            data=cost_case(book,scenario)
            result=replay(data,signals,entry_confirmations=gates,entry_liquidity_caps=caps,**parameters)
            verify(result,data,parameters)
            reproduced=None
            if capital==15.27112826:
                assert result["trades"]==control["trades"] and result["curve"]==control["curve"]
                reproduced=True
            runs.append(dict(capital=capital,scenario=scenario,parameters=parameters,headline=headline(result),
                             trades=result["trades"],control_reproduced=reproduced))
            print("macro",capital,scenario,json.dumps(runs[-1]["headline"]),flush=True)
    for p in (venue_path,ROOT/"state/research_runs/macro_trend_continuation_20261022/comparison.json"):
        sources.append(dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    sources={s["path"]:s for s in sources}
    for source in sources.values():
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()==source["sha256"]
    return runs,list(sources.values())


def run(output, include_macro=False):
    if output.exists():raise FileExistsError("preserve_prior_results")
    contract=json.loads((ROOT/"config/dual-engine-optimization-20261004.json").read_text())
    long_panel,_=prior.load_equity(INPUT/"inputs/long-equity",contract)
    recent=prior.recent_panel(CASH_INPUT/"market-cache/yahoo-public",end="2026-10-23")
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        hypothesis="Does causal volatility scaling beat simpler fixed lower budgets after activity and cost controls?",
        fixed18_note="18% is a rounded exposure-matching diagnostic chosen after observing the prior dynamic average 18.317%; not an independently selected production weight.",
        panels={},cash=[],macro=[],checks=dict(unit_ledgers=0,cash_ledgers=0,retained_controls=0))
    retained=json.loads((INPUT/"final-results/results.json").read_text())
    for name,panel,start in (("long",long_panel,"2018-04-02"),("recent",recent,"2026-01-02")):
        closes,opens=prior.prices(panel);runs={}
        for rule in RULES:
            for cost in (20,40):
                for delay in (1,2):
                    targets=schedule(panel,rule)
                    first=next(i for i,d in enumerate(panel.dates) if d>=start)
                    targets.setdefault(first-delay,{"BIL":1.})
                    replay=prior.replay_units(panel.dates,closes,opens,targets,start=start,lag=delay,cost_bps=cost,cash_asset="BIL")
                    for row in replay["records"]:
                        row["post_open_weights"]=row["target_weights"] if row["target_weights"] is not None else row["pretrade_weights"]
                        assert row["signal_date"] is None or row["signal_date"] < row["date"]
                    verify_ledger(replay,dict(dates=panel.dates,opens=opens,closes=closes,cash_asset="BIL"),252,cost_bps=cost)
                    result["checks"]["unit_ledgers"]+=1
                    metrics=prior.metrics(replay);key=f"{rule}-c{cost}-d{delay}"
                    if name=="long" and rule in ("monthly20","weekly_cap15"):
                        old=retained["panels"][name][key]["metrics"]
                        assert all(math.isclose(metrics[k],v,abs_tol=1e-12) if isinstance(v,(int,float))
                                   else metrics[k]==v for k,v in old.items())
                        result["checks"]["retained_controls"]+=1
                    if name=="recent":
                        for k in ("cagr","cagr_calendar","calmar_calendar"):
                            metrics.pop(k,None)
                    runs[key]=dict(metrics=metrics,annual={y:prior.slice_metrics(replay["records"],y+"-01-01",y+"-12-31")
                        for y in sorted({r["date"][:4] for r in replay["records"]})},records=replay["records"])
        result["panels"][name]=runs
        print(name,"scenarios",len(runs),flush=True)
    cache={s:json.loads((CASH_INPUT/"market-cache/yahoo-public"/(s+"-1d.json")).read_text())
           for s in (*cash_book.SYMBOLS,*cash_book.G20_PROXY_SYMBOLS)}
    policy=json.loads((ROOT/"config/g20-cash-distributions.json").read_text())
    panels,actions,_=cash_book.normalize_cache(cache,policy)
    for capital in (100.,1000.,10000.):
        for rule in ("monthly20","monthly15","monthly10","weekly_cap15"):
            r=cash_replay(recent,panels,actions,rule=rule,capital=capital)
            if capital==10000 and rule=="monthly20":
                paper=json.loads((CASH_INPUT/"g20-cash/forward.json").read_text())
                assert [(x["date"],x["equity"]) for x in r["records"]]==[(x["date"],x["equity"]) for x in paper["observations"]]
            terminal_cash=capital+r["distributions_received"]
            for trade in r["trades"]:
                assert trade["side"] in ("BUY","SELL") and trade["decision_date"]<trade["date"]
                signed=-1 if trade["side"]=="BUY" else 1
                terminal_cash+=signed*trade["quantity"]*trade["price"]-trade["cost"]
            assert math.isclose(terminal_cash,r["final"]["cash"],abs_tol=1e-8)
            result["checks"]["cash_ledgers"]+=1
            result["cash"].append(r)
            print("cash",capital,rule,r["total_return"],r["max_drawdown"],r["trade_count"],flush=True)
    if include_macro:result["macro"],result["macro_sources"]=macro_scale()
    paths=list((INPUT/"inputs/long-equity").glob("*"))+list((CASH_INPUT/"market-cache/yahoo-public").glob("*.json"))
    paths += [Path(__file__),ROOT/"config/g20-cash-distributions.json",ROOT/"src/qount/dual_engine/g20_cash.py"]
    result["input_hashes"]={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}
    output.mkdir(parents=True)
    (output/"results.json").write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
    brief={**result,"panels":{name:{k:{a:b for a,b in v.items() if a!="records"} for k,v in runs.items()}
           for name,runs in result["panels"].items()},"cash":[{k:v for k,v in r.items() if k not in ("records","trades")} for r in result["cash"]]}
    (output/"summary.json").write_text(json.dumps(brief,ensure_ascii=False,indent=2,allow_nan=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--include-macro",action="store_true")
    args=parser.parse_args();run(args.output,args.include_macro)
