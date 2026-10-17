"""Synchronize all eight mappings; compare one fixed MR signal-age price gate."""
import argparse
import bisect
import hashlib
import itertools
import json
import math
import statistics
from pathlib import Path

from qount.research.binance_etf_leverage import feature_at, load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_entry_episodes import episode_confirmations
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, fixed_fill_metrics
from qount.research.binance_macro_proxy_alignment import (
    causal_proxy_snapshot, etf_closes, mean_reversion_daily_confirmations,
    mean_reversion_gap_confirmations, paired_closes, pair_statistics,
)
from qount.research.binance_macro_setup import setup_policies
from qount.research.binance_macro_validation import available_atr, frozen_trade, minute_windows
from qount.research_data.archives import timestamp


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--download",action="store_true",help="Missing public minute windows only")
    p.add_argument("--study",choices=("proxy","daily-reversal"),default="proxy")
    args=p.parse_args()
    if args.output.exists():raise FileExistsError("refuse_overwrite_proxy_alignment")
    cache=Path("state/research_cache/binance_macro_attack_20261015")
    features,sources=macro_features(cache,"2026-10-15")
    symbols=tuple(CONTRACT_SIGNALS)
    data,inputs=load_inputs(cache,timestamp("2026-07-30"),timestamp("2026-10-15"),symbols=symbols)
    sources+=inputs
    for folder,start,end,subset in (
        ("binance_macro_earlier_20260611_20260730","2026-06-11","2026-07-30",tuple(s for s in symbols if s!="SMHUSDT")),
        ("binance_macro_prefix_20260407_20260611","2026-04-07","2026-06-11",("SPYUSDT","QQQUSDT","XAUUSDT","COPPERUSDT","CLUSDT")),
    ):
        prefix,inputs=load_inputs(Path("state/research_cache")/folder,timestamp(start),timestamp(end),symbols=subset)
        sources+=inputs
        data={s:{**d,**{k:prefix[s][k]+d[k] for k in ("trade","mark","funding")}} if s in prefix else d for s,d in data.items()}
    book,signals=directional_book(data,features,"long",20/3)
    no_chase=episode_confirmations(book,signals,"no_chase")
    clocks=sorted(no_chase,key=lambda x:(x[1],x[0]))
    caps,inputs,_=load_capacity_contexts(clocks,Path("state/research_cache/binance_macro_liquidity_20261015"))
    sources+=inputs
    gap=mean_reversion_gap_confirmations(book,signals,clocks)
    assert set(gap)==set(no_chase)
    combined={key:{**context,"eligible":context["eligible"] and gap[key]["eligible"],
                    "reason":gap[key]["reason"] if context["eligible"] else context["reason"]}
              for key,context in no_chase.items()}
    paired={};proxy_closes={}
    alignment=[]
    for s,ticker in CONTRACT_SIGNALS.items():
        proxy=etf_closes(json.loads((cache/f"yahoo-{ticker}-20250101-2026-10-15.json").read_text()))
        proxy_closes[s]=proxy
        paired[s]=paired_closes(proxy,data[s])
        alignment.append(dict(symbol=s,proxy=ticker,economic_proxy=s in ("CLUSDT","COPPERUSDT","XAUUSDT"),**pair_statistics(paired[s])))
    daily=mean_reversion_daily_confirmations(signals,proxy_closes,clocks) if args.study=="daily-reversal" else None
    arms={"baseline":no_chase,"mr_signal_gap_1atr":combined}
    if daily is not None:
        assert set(daily)==set(no_chase)
        for name,parent in (("mr_daily_reversal",no_chase),("mr_gap_and_daily_reversal",combined)):
            arms[name]={key:{**context,"eligible":context["eligible"] and daily[key]["eligible"],
                             "reason":daily[key]["reason"] if context["eligible"] else context["reason"]}
                        for key,context in parent.items()}
    # Label paths are kept separate and never read by the pure gap gate above.
    reference_path=Path("state/research_runs/binance_macro_entry_sleeves_20261015/summary.json")
    reference=json.loads(reference_path.read_text())
    for source in reference["sources"]:
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()==source["sha256"]
    old_events={(e["symbol"],e["time"]):e for e in reference["isolated_events"]}
    events=[]
    opens={s:{b.t:b.o for b in d["trade"]} for s,d in data.items()}
    for s,now in clocks:
        f=feature_at(signals[s],now)
        snapshot=causal_proxy_snapshot(paired[s],now)
        if snapshot is not None:
            assert snapshot["available"]==f["available"]
            snapshot.update(entry_open=opens[s][now],pre_entry_gap_return=opens[s][now]/snapshot["native_close"]-1)
        e=dict(symbol=s,proxy=CONTRACT_SIGNALS[s],time=now,setup=f["tactical_setup"],
            first=no_chase[s,now]["first"],known_at_entry=snapshot,gap_gate=gap[s,now],
            no_chase_eligible=no_chase[s,now]["eligible"],normal_isolated_outcomes=old_events[s,now]["outcomes"],
            synchronized_outcomes={})
        if daily is not None:e["daily_gate"]=daily[s,now]
        if snapshot is not None:
            rows=paired[s];i=bisect.bisect_left([r["available"] for r in rows],snapshot["available"])
            for n in (1,5,10):
                if i+n<len(rows) and rows[i+n]["session_index"]==rows[i]["session_index"]+n:
                    e["synchronized_outcomes"][str(n)]=dict(end_available=rows[i+n]["available"],
                        etf_return=rows[i+n]["etf_adjusted"]/rows[i]["etf_adjusted"]-1,
                        native_return=rows[i+n]["native_trade"]/rows[i]["native_trade"]-1)
            for scenario,o in e["normal_isolated_outcomes"].items():
                if not o["accepted"]:continue
                t=o["trade"];slip=.005 if scenario=="double_cost" else .0025
                raw_exit=t["exit_price"]/(1-slip)
                o["price_path_attribution"]=dict(pre_entry_gap_return=snapshot["pre_entry_gap_return"],
                    entry_to_exit_raw_return=raw_exit/opens[s][now]-1,
                    signal_close_to_exit_raw_return=raw_exit/snapshot["native_close"]-1)
        events.append(e)
    quality=[]
    for expired,scenario in itertools.product((False,True),("base","double_cost")):
        selected=[e for e in events if e["first"] and e["setup"]=="mean_reversion"
                  and e["known_at_entry"] is not None and (not e["gap_gate"]["eligible"])==expired]
        accepted=[e["normal_isolated_outcomes"][scenario] for e in selected if e["normal_isolated_outcomes"][scenario]["accepted"]]
        closed=[o for o in accepted if not o["censored"]]
        quality.append(dict(expired=expired,scenario=scenario,first_opportunities=len(selected),
            normal_accepted=len(accepted),closed=len(closed),censored=len(accepted)-len(closed),
            mean_closed_net_on_notional=statistics.mean(o["net_on_notional"] for o in closed) if closed else None))
    params=dict(strategy="macro_tactical",gross_cap=20,risk_fraction=.5,exchange_leverage=50,
        liquidation_stop_multiple=1.25,account_controls=False,funding_policy="debit_stress",sizing_gap_reserve=.03,
        allow_partial_histories=True,tactical_setup_policies=setup_policies(7,21),funding_lease_hours=168,funding_lease_budget="risk")
    bundles,controls={},0
    for arm,capital,scenario in itertools.product(arms,(10,100),("base","double_cost")):
        fee,slip=(.001,.005) if scenario=="double_cost" else (.0005,.0025)
        b=replay(cost_case(book,scenario),signals,**params,capital=capital,fee=fee,slip=slip,
            entry_liquidity_caps=caps,entry_confirmations=arms[arm])
        if arm=="baseline":
            old=json.loads(Path(f"state/research_runs/binance_macro_entry_extended_20261015/no_chase_capital{capital}_{scenario}.json").read_text())
            assert b["trades"]==old["trades"] and b["curve"]==old["curve"]
            controls+=1
        elif arm=="mr_signal_gap_1atr" and args.study=="daily-reversal":
            old=json.loads(Path(f"state/research_runs/binance_macro_proxy_alignment_20261015/{arm}_{capital}_{scenario}.json").read_text())
            assert b["trades"]==old["trades"] and b["curve"]==old["curve"]
            controls+=1
        closed=[t for t in b["trades"] if t["exit_reason"]!="end_of_sample"]
        censored=[t for t in b["trades"] if t["exit_reason"]=="end_of_sample"]
        b["summary"].update(arm=arm,capital=capital,scenario=scenario,closed_trades=len(closed),censored_trades=len(censored),
            closed_pnl=sum(t["net_pnl"] for t in closed),censored_pnl=sum(t["net_pnl"] for t in censored))
        if scenario=="base":
            b["summary"]["fixed_orders_double_cost_return"]=sum(fixed_fill_metrics(t,t,data[t["symbol"]]["funding"],fee=.0005,slip=.0025)["fixed_path_double_cost_pnl"] for t in b["trades"])/capital
        bundles[arm,capital,scenario]=b
    print(json.dumps(dict(phase="accounts",accounts=len(bundles),controls=controls,
        expired=[dict(symbol=s,time=t,gap_atr=c.get("gap_atr"),reason=c["reason"]) for (s,t),c in gap.items() if not c["eligible"]])),flush=True)
    longest={}
    for b in bundles.values():
        for t in b["trades"]:
            key=t["symbol"],t["entry_time"]
            if key not in longest or t["exit_time"]>longest[key]["exit_time"]:longest[key]=t
    minutes,inputs=minute_windows(list(longest.values()),Path("state/research_cache/binance_macro_minutes_20261015"),timestamp("2026-10-15"),args.download)
    sources+=inputs
    atrs={s:available_atr(d["trade"]) for s,d in data.items()}
    count=0
    for (arm,capital,scenario),b in bundles.items():
        fee,slip=(.001,.005) if scenario=="double_cost" else (.0005,.0025)
        equity=peak=capital;mdd=0;checked=[];cb=cost_case(data,scenario)
        for t in b["trades"]:
            s=t["symbol"];m=minutes[s,t["entry_time"]]
            r=frozen_trade({**t,"equity_before_entry":equity},m["trade"],m["mark"],cb[s]["funding"],atrs[s],data[s]["rule"],fee=fee,slip=slip)
            assert r["status"]=="executed"
            for row in r.pop("curve"):
                mdd=max(mdd,1-row["equity"]/peak);peak=max(peak,row["equity"])
            r.update(pnl_difference=r["net_pnl"]-t["net_pnl"],changed_exit=r["exit_time"]!=t["exit_time"] or r["exit_reason"]!=t["exit_reason"],
                entry_risk_breach=r["entry_stress_risk_usdt"]>.5*equity+1e-9,entry_margin_breach=r["entry_margin_fraction"]>.8+1e-9)
            assert arms[arm][s,t["entry_time"]]["eligible"]
            equity+=r["net_pnl"];checked.append(r);count+=1
        b["minute_checks"]=checked
        b["summary"].update(minute_schedule_return=equity/capital-1,minute_close_mdd=mdd,
            minute_pnl_difference=equity-b["summary"]["final_equity"],minute_exit_changes=sum(r["changed_exit"] for r in checked),
            minute_entry_risk_breaches=sum(r["entry_risk_breach"] for r in checked),minute_entry_margin_breaches=sum(r["entry_margin_breach"] for r in checked))
    unique={s["path"]:s for s in sources}
    for s in unique.values():assert hashlib.sha256(Path(s["path"]).read_bytes()).hexdigest()==s["sha256"]
    args.output.mkdir(parents=True)
    for key,b in bundles.items():(args.output/("_".join(map(str,key))+".json")).write_text(json.dumps(b,allow_nan=False)+"\n")
    result=dict(start="2026-04-07",end_exclusive="2026-10-15",runs=[b["summary"] for b in bundles.values()],
        study=args.study,
        alignment=alignment,paired_sessions=paired,events=events,quality_by_signal_gap=quality,
        minute_trade_checks=count,legacy_controls=controls,sources=list(unique.values()),
        reused_opportunity_reference=dict(path=str(reference_path),sha256=hashlib.sha256(reference_path.read_bytes()).hexdigest()),
        code_sources=[dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in
            (Path(__file__),Path("src/qount/research/binance_macro_proxy_alignment.py"),Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"))],
        research_only=True,orders_authorized=False,independent_oos=False,
        assumptions=["All eight mappings aligned to native1h close ending ETF16:00NY; window has no early closes. Adjclose and quoted close metrics separated, no synthetic prelisting bars or skipped-session daily returns.",
            "High contemporaneous return correlation is not forward alpha or instrument equivalence; CPER/USO futures baskets and GLD bullion are economic proxies.",
            "One new gate only: all MR entries require native positive signal-close to entry-open displacement <=1 native ATR14 available at signal timestamp. Trend bypasses it; no threshold sweep.",
            "Gap hypothesis is adaptive after observing CL loss paths; consumed-history exploration, not independent OOS. Normal costs/risk/capacity/holding and full-exit funding leases unchanged.",
            "Synchronized1/5/10session future returns are gross diagnostic labels from signal close, not tradable entries or net returns. Normal isolated paths retain rejects/censoring and are not additive portfolio PnL.",
            "Minute checks freeze quantities and exits; current historical filters/MMR, exit liquidity and dividend-adjustment availability remain approximations."])
    if daily is not None:
        result["assumptions"][2]="Four fixed arms: original intraday-green MR; positive-gap<=1ATR; exact-signal adjusted close above prior actual session; both. No changes to signal ranks/holding/risk, no threshold search."
        result["gate_equivalence_controls"]=0
        for capital,scenario in itertools.product((10,100),("base","double_cost")):
            a=bundles["mr_daily_reversal",capital,scenario]
            b=bundles["mr_gap_and_daily_reversal",capital,scenario]
            assert a["trades"]==b["trades"] and a["curve"]==b["curve"]
            result["gate_equivalence_controls"]+=1
        result["quality_by_daily_reversal"]=[]
        for reversal,scenario in itertools.product((False,True),("base","double_cost")):
            selected=[e for e in events if e["first"] and e["setup"]=="mean_reversion" and e["daily_gate"]["eligible"]==reversal]
            accepted=[e["normal_isolated_outcomes"][scenario] for e in selected if e["normal_isolated_outcomes"][scenario]["accepted"]]
            closed=[o for o in accepted if not o["censored"]]
            result["quality_by_daily_reversal"].append(dict(daily_reversal=reversal,scenario=scenario,
                first_opportunities=len(selected),accepted=len(accepted),closed=len(closed),censored=len(accepted)-len(closed),
                mean_closed_net_on_notional=statistics.mean(o["net_on_notional"] for o in closed) if closed else None))
        # Existing paid-cost shadow paths distinguish directional selection
        # from normal friction admission. Labels never feed back into gates.
        shadow_path=Path("state/research_runs/binance_macro_admission_shadow_20261015/summary.json")
        shadow=json.loads(shadow_path.read_text())
        for source in shadow["sources"]:
            assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()==source["sha256"]
        result["reused_admission_shadow_reference"]=dict(path=str(shadow_path),sha256=hashlib.sha256(shadow_path.read_bytes()).hexdigest())
        result["shadow_quality_by_daily_reversal"]=[]
        for reversal,scenario in itertools.product((False,True),("base","double_cost")):
            selected=[e for e in shadow["events"] if e["setup"]=="mean_reversion" and daily[e["symbol"],e["time"]]["eligible"]==reversal]
            accepted=[e["outcomes"][scenario] for e in selected if e["outcomes"][scenario]["accepted"]]
            closed=[o for o in accepted if not o["censored"]]
            result["shadow_quality_by_daily_reversal"].append(dict(daily_reversal=reversal,scenario=scenario,
                first_opportunities=len(selected),accepted=len(accepted),closed=len(closed),censored=len(accepted)-len(closed),
                mean_closed_net_on_notional=statistics.mean(o["net_on_notional"] for o in closed) if closed else None))
        result["assumptions"].append("Existing shadow paths bypass entry friction-ratio rejection while paying costs and retaining sizing/capacity/holding constraints; not executable accounts or new independent observations.")
    (args.output/"summary.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    lines=["# Proxy alignment and one fixed MR signal-gap gate","", "|Mapping|Paired closes|Adjusted daily correlation|Mean absolute daily log-return difference bp|",
        "|---|---:|---:|---:|"]
    for r in alignment:
        m=r['etf_adjusted'];lines.append(f"|{r['proxy']}→{r['symbol']}|{r['paired_closes']}|{m['correlation']:.4f}|{m['mean_abs_daily_log_return_difference_bps']:.2f}|")
    lines += ["", "|Arm|Capital|Costs|Minute return|Minute MDD|Closed PnL|Censored PnL|", "|---|---:|---|---:|---:|---:|---:|"]
    for r in result["runs"]:lines.append(f"|{r['arm']}|{r['capital']}|{r['scenario']}|{r['minute_schedule_return']:.2%}|{r['minute_close_mdd']:.2%}|{r['closed_pnl']:.5f}|{r['censored_pnl']:.5f}|")
    lines += ["", "## Assumptions", ""]+["- "+a for a in result['assumptions']]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output),accounts=len(bundles),minute_checks=count,controls=controls)),flush=True)


if __name__=="__main__":main()
