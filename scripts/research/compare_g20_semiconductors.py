"""Keep G20 selection fixed; replace only its semiconductor carrier with SMH/SOXX."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import analyze_g20_risk_budget as prior
from compare_g20_fixed_budget import schedule,ROOT,INPUT,CASH_INPUT
from compare_g20_carriers import ANCHORS,attribution
from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.research.dual_engine_execution_verify import verify_ledger
from qount.research.g20_carriers import proxy_schedule


def append_soxx(panel,path):
    payload=json.loads(Path(path).read_text());node=payload["chart"]["result"][0]
    if node["meta"]["symbol"]!="SOXX":raise ValueError("SOXX_identity_invalid")
    q=node["indicators"]["quote"][0];adj=node["indicators"]["adjclose"][0]["adjclose"]
    rows={}
    for i,t in enumerate(node["timestamp"]):
        day=datetime.fromtimestamp(t,ZoneInfo("America/New_York")).date().isoformat()
        if day in rows:raise ValueError("SOXX_duplicate_date")
        o,h,l,c,a=tuple(q[k][i] for k in ("open","high","low","close"))+(adj[i],)
        if any(x is None or not math.isfinite(x) or x<=0 for x in (o,h,l,c,a)) or not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError("SOXX_invalid_price:"+day)
        rows[day]=(c,a,o*a/c)
    if not set(panel.dates)<=set(rows):raise ValueError("SOXX_common_calendar_incomplete")
    return replace(panel,**{field:{**getattr(panel,field),"SOXX":tuple(rows[d][j] for d in panel.dates)}
                            for j,field in enumerate(("closes","total_closes","total_opens"))})


def segment(records,start,end):
    rows=[r for r in records if start<=r["date"]<=end]
    if not rows:return None
    m=prior.slice_metrics(records,start,end)
    years=(datetime.fromisoformat(rows[-1]["date"])-datetime.fromisoformat(rows[0]["date"])).days/365.25
    m.pop("cagr",None)
    if years>=1:m["cagr_calendar"]=(1+m["total_return"])**(1/years)-1
    m.update(first=rows[0]["date"],last=rows[-1]["date"])
    return m


def run(output,soxx):
    if output.exists():raise FileExistsError("preserve_previous_results")
    c=json.loads((ROOT/"config/dual-engine-optimization-20261004.json").read_text())
    long,_=prior.load_equity(INPUT/"inputs/long-equity",c)
    recent=prior.recent_panel(CASH_INPUT/"market-cache/yahoo-public",end="2026-10-23")
    old=json.loads((ROOT/"state/research_runs/g20_carrier_comparison_20261025_final/results.json").read_text())
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,
        hypothesis="Is the prior SMH advantage semiconductor benchmark selection rather than a universal unlevered carrier effect? Only replace SOXL; leave all other carriers and original SMH-based ranking unchanged.",
        assumptions=dict(risk_window=20,cost_delay_pairs=[[20,1],[40,2]],proxy_max_weight=1.,cash_asset="BIL",
            units="fractional total-return units, not shares",initial_nav=1.),
        benchmark_scope="SOXX/SOXL both PHLX before June 2021; SOXX changed around June 21 and SOXL around August 25. 2021 transition remains in full-window results and is not claimed same-benchmark. Post-2022 is a continuous-account diagnostic, not OOS.",
        sources=dict(SOXX="https://www.ishares.com/us/products/239705/ishares-phlx-semiconductor-etf",
            SOXL_change="https://www.direxion.com/uploads/Direxion-Changes-Index-for-Semiconductor-ETFs.pdf",
            SOXX_change="https://www.nasdaq.com/press-release/blackrock-announces-product-updates-to-two-ishares-etfs-2021-04-22"),
        checks=dict(unit_ledgers=0,attributions=0,retained_controls=0),panels={})
    for name,panel,start in (("long",long,"2018-04-02"),("recent",recent,"2026-01-02")):
        panel=append_soxx(panel,soxx);closes,opens=prior.prices(panel);runs={};risk={}
        first=next(i for i,d in enumerate(panel.dates) if d>=start)
        for anchor in ANCHORS:
            lev=schedule(panel,anchor);variants={"SOXL":lev}
            for ticker in ("SMH","SOXX"):
                mapping=dict(G20_EXECUTION_TO_PROXY,SOXL=ticker)
                alternative,diag=proxy_schedule(panel.dates,panel.total_closes,lev,proxy_mapping=mapping)
                variants[ticker]={i:(alternative[i] if target.get("SOXL",0)>0 else target) for i,target in lev.items()}
                risk[anchor+"-"+ticker]=[r for r in diag if r["selected"]=="SOXL" and first-2<=r["index"]<len(panel.dates)-1]
            for cost,delay in ((20,1),(40,2)):
                for carrier,targets in variants.items():
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
                    if carrier=="SOXL":
                        control=old["panels"][name]["runs"][f"{anchor}-leveraged-c{cost}-d{delay}"]["metrics"]
                        assert all(math.isclose(m[k],v,abs_tol=1e-12) if isinstance(v,(int,float)) else m[k]==v for k,v in control.items())
                        result["checks"]["retained_controls"]+=1
                    parts=attribution(book,panel.dates,closes,opens);result["checks"]["attributions"]+=1
                    runs[f"{anchor}-{carrier}-c{cost}-d{delay}"]=dict(metrics=m,attribution=parts,
                        annual={y:prior.slice_metrics(book["records"],y+"-01-01",y+"-12-31") for y in sorted({r["date"][:4] for r in book["records"]})},
                        periods={label:segment(book["records"],a,b) for label,a,b in (
                            ("pre_transition","2018-04-02","2021-05-31"),("transition_2021","2021-06-01","2021-12-31"),
                            ("post_2022","2022-01-03","2026-07-30"))} if name=="long" else {},
                        records=[{k:r[k] for k in ("date","nav","return","cash_return","risk_gross","turnover","cost_fraction")} for r in book["records"]])
            print(name,anchor,"SOXL/SMH/SOXX done",flush=True)
        result["panels"][name]=dict(runs=runs,risk_matching=risk)
    paths=[Path(__file__),ROOT/"src/qount/research/g20_carriers.py",soxx]
    result["source_hashes"]={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):
        hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result["prior_study_source_hashes"]=old["source_hashes"]
    output.mkdir(parents=True)
    (output/"results.json").write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))
    brief={**result,"panels":{name:{**p,"runs":{key:{k:v for k,v in r.items() if k!="records"} for key,r in p["runs"].items()}} for name,p in result["panels"].items()}}
    (output/"summary.json").write_text(json.dumps(brief,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps(result["checks"]))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--soxx",type=Path,default=ROOT/"state/research_cache/g20_carriers_20261025/SOXX.source.json")
    args=p.parse_args();run(args.output,args.soxx.resolve())
