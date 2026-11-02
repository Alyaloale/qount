#!/usr/bin/env python3
"""Fixed-rule distinct-address consensus pilot, with sample-size diagnostics."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from qount.research.wallet_follow import reconstruct,simulate_direction,summarize_portfolio
from qount.research.wallet_consensus import consensus,position_votes,snapshot_anchored_states,target_signals,vote_policies

HOUR=3_600_000


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("state/research_runs/wallet_consensus_20261027"))
    parser.add_argument("--cohort",type=Path,default=Path("state/research_cache/wallet_consensus_20261027/consensus_cohort.json"))
    parser.add_argument("--coins",nargs="+",help="Fixed cash sleeves, including assets without eligible votes")
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    cache=Path("state/research_cache/wallet_consensus_20261027")
    old=Path("state/research_cache/slow_wallets_20261027")
    selected=json.loads(args.cohort.read_text())
    assert len({w["address"] for w in selected["cohort"]})==len(selected["cohort"]),"duplicate_address_vote"
    split,end=selected["split_ms"],selected["end_ms"]
    times=np.arange(split,end,HOUR,dtype=np.int64)
    members=Counter(c for w in selected["cohort"] for c in w["assets"])
    coins=sorted(args.coins) if args.coins else sorted(c for c,n in members.items() if n>=2)
    reconstructed={w["address"]:reconstruct(json.loads((Path(w["cache"])/(w["address"]+"-userFillsByTime.json")).read_text())) for w in selected["cohort"]}
    coverage={}
    for w in selected["cohort"]:
        if "snapshot_positions" in w:
            r=reconstructed[w['address']]
            r['states'],coverage[w['address']]=snapshot_anchored_states(r,w['snapshot_positions'],selected['snapshot_ms'])
    policies={k:{} for k in ("newrisk_min2","position_min2","any_newrisk","addition_supported_by_holdings",
                             "initial_position_consensus","reverse_newrisk","buyhold")}
    diagnostics={};event_records=[];vote_data={}
    for coin in coins:
        votes=[];holdings=[];addresses=[]
        for w in selected["cohort"]:
            if coin not in w["assets"]:continue
            r=reconstructed[w["address"]]
            if "snapshot_positions" not in w:
                assert not r["errors"] and not r["stats"].get("cross_timestamp_gaps",0)
            v,h,_=position_votes([s for s in r["states"] if s["coin"]==coin],times)
            votes.append(v);holdings.append(h);addresses.append(w["address"])
        votes=np.asarray(votes).reshape(-1,len(times));holdings=np.asarray(holdings).reshape(-1,len(times))
        vote_data[coin]=(addresses,votes,holdings)
        new,pos,neg=consensus(votes)
        targets=vote_policies(votes,holdings)
        diagnostics[coin]=dict(addresses=addresses,policies={})
        for name,target in targets.items():
            entries=(target!=0)&np.r_[True,target[1:]!=target[:-1]]
            diagnostics[coin]["policies"][name]=dict(active_hours=int(np.sum(target!=0)),entry_events=int(entries.sum()))
            policies[name][coin]=target_signals(times,target)
            if name in ("newrisk_min2","addition_supported_by_holdings"):
                for i in np.flatnonzero(entries):
                    event_records.append(dict(policy=name,coin=coin,decision_ms=int(times[i]),side=int(target[i]),
                                               positive_newrisk_addresses=int(pos[i]),negative_newrisk_addresses=int(neg[i])))
    original=json.loads(Path("state/research_cache/position_flow_20261027/hourly.json").read_text())["data"]
    closing=json.loads((old/"closing_bars.json").read_text())["data"]
    extra=json.loads((old/"additional_market_data.json").read_text())["data"]
    extra_funding=json.loads((old/"closing_funding.json").read_text())["data"]
    original_funding=json.loads(Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json").read_text())["data"]
    today_funding=json.loads(Path("state/research_cache/wallet_follow_20261027/funding_today.json").read_text())["data"]
    filters={s["symbol"]:s for s in json.loads((old/"exchange_filters.json").read_text())["symbols"]}
    markets={};rates={}
    for coin in coins:
        symbol=coin+"USDT"
        if symbol+"_futures" in original:
            bars=original[symbol+"_futures"]+closing[symbol]
            payments=original_funding[symbol+"_funding"]+today_funding[symbol]
        else:
            bars=extra[symbol+"_klines"]
            payments=extra[symbol+"_funding"]+extra_funding[symbol]
        markets[coin]=np.asarray(bars,float)
        assert np.all(np.diff(markets[coin][:,0])==HOUR)
        rates[coin]=sorted({p["fundingTime"]:p for p in payments}.values(),key=lambda p:p["fundingTime"])
    accounts={};curves={};any_runs={}
    for name,signals_by_coin in policies.items():
        accounts[name]={}
        for delay,cost in ((3600,10),(3600,30),(21600,10)):
            runs=[];by_coin={}
            for coin,sig in signals_by_coin.items():
                step=float(next(f["stepSize"] for f in filters[coin+"USDT"]["filters"] if f["filterType"]=="LOT_SIZE"))
                run=simulate_direction(sig,markets[coin],rates[coin],start_ms=split,end_ms=end,delay_seconds=delay,
                                       cost_bp=cost,initial=10000/len(coins),quantity_step=step,bar_ms=HOUR)
                by_coin[coin]={k:v for k,v in run.items() if k not in ("points","trades")}
                if name=="any_newrisk" and delay==3600 and cost==10:any_runs[coin]=run
                runs.append(run)
            summary,t,eq=summarize_portfolio(runs,10000)
            key=f"delay{delay}s_cost{cost}bp"
            accounts[name][key]=dict(summary=summary,by_coin=by_coin)
            curves[name+"_"+key]=dict(times=t,equity=eq)
    leave_one_out={}
    for wallet in selected["cohort"]:
        omitted=wallet["address"];runs=[]
        for coin in coins:
            addresses,votes,holdings=vote_data[coin]
            mask=np.asarray([a!=omitted for a in addresses])
            target=vote_policies(votes[mask],holdings[mask])["any_newrisk"]
            step=float(next(f["stepSize"] for f in filters[coin+"USDT"]["filters"] if f["filterType"]=="LOT_SIZE"))
            runs.append(simulate_direction(target_signals(times,target),markets[coin],rates[coin],start_ms=split,end_ms=end,
                        delay_seconds=3600,cost_bp=10,initial=10000/len(coins),quantity_step=step,bar_ms=HOUR))
        leave_one_out[omitted]=summarize_portfolio(runs,10000)[0]
    matched_runs=[];mean_weights={};removed_assets={}
    base=accounts["any_newrisk"]["delay3600s_cost10bp"]["summary"]
    for coin in coins:
        run=any_runs[coin];trades=run["trades"];quantity=0.;cursor=0;fractions=[]
        bars=markets[coin];ids=np.searchsorted(bars[:,0],times)
        for stamp,i in zip(times,ids):
            while cursor<len(trades) and trades[cursor]["time_ms"]<=stamp:
                quantity=trades[cursor]["quantity"];cursor+=1
            fractions.append(quantity*bars[i,1]/(10000/len(coins)))
        fraction=float(np.mean(fractions));mean_weights[coin]=fraction
        assert abs(fraction)<=1,"diagnostic_requires_unlevered_static_allocation"
        step=float(next(f["stepSize"] for f in filters[coin+"USDT"]["filters"] if f["filterType"]=="LOT_SIZE"))
        allocation=10000/len(coins);invested=abs(fraction)*allocation
        if invested>0:
            static=simulate_direction([dict(time_ms=split,target=int(np.sign(fraction)))],markets[coin],rates[coin],
                         start_ms=split,end_ms=end,delay_seconds=3600,cost_bp=10,initial=invested,quantity_step=step,bar_ms=HOUR)
            cash=allocation-invested
            static["initial"]=allocation;static["final_equity"]+=cash
            static["points"]=[dict(p,equity=p["equity"]+cash) for p in static["points"]]
        else:
            static=simulate_direction([],markets[coin],rates[coin],start_ms=split,end_ms=end,
                         delay_seconds=3600,cost_bp=10,initial=allocation,quantity_step=step,bar_ms=HOUR)
        matched_runs.append(static)
        removed_assets[coin]=base["return_pct"]-(run["final_equity"]-allocation)/10000*100
    matched_summary,_,matched_equity=summarize_portfolio(matched_runs,10000)
    curves["any_newrisk_expost_static_matching"]=dict(times=times.tolist(),equity=matched_equity)
    payload=dict(research_only=True,orders_authorized=False,independent_oos=False,
                 rule="One address one vote per asset; compare current signed position with24h earlier known position; reductions never count as new opposite risk;at least2 same-side votes and strict majority",
                 sample=selected.get("sample","Original12 plus24 deterministic non-ROI current-prefix samples; persistent per-asset discovery profile allows censored runs"),
                 causal_coverage_withdrawals=coverage,
                 cohort=selected,split_ms=split,end_ms=end,diagnostics=diagnostics,event_records=event_records,accounts=accounts,
                 any_newrisk_leave_one_address_out=leave_one_out,
                 any_newrisk_expost_static_matching=dict(mean_signed_initial_notional_by_sleeve=mean_weights,summary=matched_summary,
                      limitation="Mean exposures estimated from the evaluation itself; attribution diagnostic, not executable ex-ante allocation"),
                 any_newrisk_remove_asset_keep_cash_return_pct=removed_assets,
                 limits=selected.get("limits",["Only a few shared events; returns cannot establish alpha or failure","Distinct addresses are not verified independent beneficial owners",
                         "Current roster, turnover/equity and full-window coverage exclusions are retrospective","24h votes and revised censored profile are exploratory on consumed history",
                         "One-hour clock plus1h assumed observation latency;hourly curves miss intrahour drawdowns","10000USDT fixed initial allocation across four assets;not15U execution certification"]))
    (args.output/"results.json").write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n")
    (args.output/"curves.json").write_text(json.dumps(curves,separators=(",",":"),allow_nan=False)+"\n")
    print("assets",coins,"addresses",len(selected["cohort"]))
    print("diagnostics",{c:d["policies"]["newrisk_min2"] for c,d in diagnostics.items()})
    for name,r in accounts.items():
        print(name,{k:(round(v["summary"]["return_pct"],4),round(v["summary"]["hourly_open_mdd_pct"],4),v["summary"]["orders"]) for k,v in r.items()})


if __name__=="__main__":main()
