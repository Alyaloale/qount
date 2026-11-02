#!/usr/bin/env python3
"""Behavior-selected slow-account cases; current-roster bias remains explicit."""
import argparse
from decimal import Decimal
import json
from pathlib import Path

import numpy as np

from qount.research.wallet_follow import behavior_screen, reconstruct, sign, simulate_direction, summarize_portfolio

DAY = 86_400_000
HOUR = 3_600_000


def initialized_signals(reconstructed, coin, split):
    previous = [s for s in reconstructed["states"] if s["coin"] == coin and s["time_ms"] < split]
    direction = sign(Decimal(previous[-1]["after"])) if previous else 0
    initial = dict(time_ms=split, target=direction, reason="known_training_end_position")
    later = [s for s in reconstructed["signals"] if s["coin"] == coin and s["time_ms"] >= split]
    static = [initial]
    if not previous:
        first = next((s for s in reconstructed["states"] if s["coin"] == coin and s["time_ms"] >= split),None)
        if first:
            observation = dict(time_ms=first["time_ms"],target=sign(Decimal(first["after"])),reason="first_observed_position")
            later = [observation]+later
            static.append(observation)
    return [initial] + sorted(later,key=lambda s:s["time_ms"]), static


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("state/research_runs/slow_wallets_20261027"))
    args = parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    cache = Path("state/research_cache/slow_wallets_20261027")
    roster = json.loads((cache/"selection.json").read_text())
    fetch = json.loads((cache/"fetch_summary.json").read_text())
    selection = json.loads((cache/"behavior_selection.json").read_text())
    filters = {s["symbol"]:s for s in json.loads((cache/"exchange_filters.json").read_text())["symbols"]}
    original = json.loads(Path("state/research_cache/position_flow_20261027/hourly.json").read_text())["data"]
    closing = json.loads((cache/"closing_bars.json").read_text())["data"]
    extra = json.loads((cache/"additional_market_data.json").read_text())["data"]
    extra_funding = json.loads((cache/"closing_funding.json").read_text())["data"]
    original_funding = json.loads(Path("state/research_cache/independent_crypto_factors_20261027/panel_seven.json").read_text())["data"]
    today_funding = json.loads(Path("state/research_cache/wallet_follow_20261027/funding_today.json").read_text())["data"]
    start,split,end = selection["training_start_ms"],selection["split_ms"],selection["evaluation_end_ms"]
    audit, eligible = [], []
    for row in fetch["results"]:
        address = row["address"]
        fills = json.loads((cache/(address+"-userFillsByTime.json")).read_text())
        s = behavior_screen(fills,start=start,split=split,saturated=row.get("saturated",True),universe=selection["universe"])
        s["address"]=address
        audit.append(s)
        if s["eligible"]:
            assert address in {s["address"] for s in selection["selected"]}
            eligible.append((address,s,reconstruct(fills)))
    assert {a for a,_,_ in eligible} == {s["address"] for s in selection["selected"]}
    markets,rates = {},{}
    for _,s,_ in eligible:
        for coin in s["mapped_training_assets"]:
            symbol = coin+"USDT"
            if symbol in markets: continue
            if symbol+"_futures" in original:
                bars = original[symbol+"_futures"]+closing[symbol]
                payments = original_funding[symbol+"_funding"]+today_funding[symbol]
            else:
                bars = extra[symbol+"_klines"]
                payments = extra[symbol+"_funding"]+extra_funding[symbol]
            bars = np.asarray(bars,float)
            assert np.all(np.diff(bars[:,0])==HOUR) and np.all(np.isfinite(bars))
            assert bars[0,0] <= split and bars[-1,0]>=end
            payments = sorted({p["fundingTime"]:p for p in payments}.values(),key=lambda p:p["fundingTime"])
            assert all(p.get("markPrice") for p in payments if split<=p["fundingTime"]<=end)
            relevant = [p["fundingTime"] for p in payments if split<=p["fundingTime"]<=end]
            assert relevant and max(np.diff(relevant))<=8.01*HOUR
            markets[symbol],rates[symbol] = bars,payments
    result,curves = {},{}
    for i,(address,s,r) in enumerate(eligible,1):
        name=f"W{i}";coins=s["mapped_training_assets"];initial=10000;allocation=initial/len(coins)
        policies={"follow_1h_10bp":("follow",3600,10),"follow_1h_30bp":("follow",3600,30),
                  "follow_6h_10bp":("follow",21600,10),"initial_static_1h_10bp":("static",3600,10),
                  "buyhold_1h_10bp":("buyhold",3600,10),"reverse_1h_10bp":("reverse",3600,10)}
        wallet = dict(address=address,behavior=s,full_chain_stats=r["stats"],full_chain_errors=r["errors"],accounts={})
        training={}
        for kind in ("follow","static"):
            runs=[]
            for coin in coins:
                symbol=coin+"USDT"
                follow,static=initialized_signals(r,coin,start)
                sig=[v for v in (follow if kind=="follow" else static) if v["time_ms"]<split]
                step=float(next(f["stepSize"] for f in filters[symbol]["filters"] if f["filterType"]=="LOT_SIZE"))
                runs.append(simulate_direction(sig,markets[symbol],rates[symbol],start_ms=start,end_ms=split,
                            delay_seconds=3600,cost_bp=10,initial=allocation,quantity_step=step,bar_ms=HOUR))
            training[kind]=summarize_portfolio(runs,initial)[0]
        wallet["discovery_copy_performance"]=training
        wallet["positive_copy_gate"]=(training["follow"]["return_pct"]>0 and
                                      training["follow"]["return_pct"]>training["static"]["return_pct"])
        for policy,(kind,delay,cost) in policies.items():
            runs=[];by_coin={}
            for coin in coins:
                symbol=coin+"USDT";follow,static=initialized_signals(r,coin,split)
                if kind=="follow": sig=follow
                elif kind=="static": sig=static
                elif kind=="buyhold": sig=[dict(time_ms=split,target=1)]
                else: sig=[dict(s,target=-s["target"]) for s in follow]
                step=float(next(f["stepSize"] for f in filters[symbol]["filters"] if f["filterType"]=="LOT_SIZE"))
                run=simulate_direction(sig,markets[symbol],rates[symbol],start_ms=split,end_ms=end,
                                       delay_seconds=delay,cost_bp=cost,initial=allocation,quantity_step=step,bar_ms=HOUR)
                by_coin[coin]={k:v for k,v in run.items() if k not in ("points","trades")}
                runs.append(run)
            summary,times,equities=summarize_portfolio(runs,initial)
            wallet["accounts"][policy]=dict(summary=summary,by_coin=by_coin)
            curves[name+"_"+policy]=dict(times=times,equity=equities)
        result[name]=wallet
    # Equal initial allocation to the three independently modeled 10k accounts:
    # this is a 30k account with no transfers/rebalancing between source sleeves.
    combined={}
    for policy in next(iter(result.values()))["accounts"]:
        eq=np.sum([curves[n+"_"+policy]["equity"] for n in result],axis=0)
        total=10000*len(result);nav=np.r_[total,eq]
        combined[policy]=dict(initial=total,return_pct=float((eq[-1]/total-1)*100),
                              hourly_open_mdd_pct=float(np.max(1-nav/np.maximum.accumulate(nav))*100),
                              costs=sum(w["accounts"][policy]["summary"]["costs"] for w in result.values()),
                              orders=sum(w["accounts"][policy]["summary"]["orders"] for w in result.values()))
    payload=dict(research_only=True,orders_authorized=False,independent_oos=False,
                 selection="Current prefix roster and current low-turnover prefilter; PnL/ROI never used; retrospective coverage exclusions",
                 roster_scan=dict(scanned=roster["scanned_rows"],eligible=roster["eligible"],sampled=fetch["sampled"]),
                 training_start_ms=start,split_ms=split,evaluation_end_ms=end,screen=audit,wallets=result,combined=combined,
                 limits=["Current roster and volume/equity selection expose future relative to September","Unsaturated API response does not certify lifetime coverage",
                         "Only mapped assets already seen in training; other positions excluded","Hourly execution means1h to2h latency; intrahour drawdown and fill capacity unqualified",
                         "Current quantity steps back-applied; no cross-venue USD/USDC/USDT conversion cost","Minimum2 completed intervals is exploratory, not stable style certification"])
    selected_by_gate=[n for n,w in result.items() if w["positive_copy_gate"]]
    gated_equity=np.sum([curves[n+"_follow_1h_10bp"]["equity"] if n in selected_by_gate else
                         np.full(len(next(iter(curves.values()))["times"]),10000.) for n in result],axis=0)
    total=10000*len(result);nav=np.r_[total,gated_equity]
    payload["positive_copy_gate"]=dict(rule="discovery net following return>0 and>same discovery initial static direction; unselected allocations stay cash; no ROI/PnL leaderboard fields",
                        selected=selected_by_gate,initial=total,return_pct=float((gated_equity[-1]/total-1)*100),
                        hourly_open_mdd_pct=float(np.max(1-nav/np.maximum.accumulate(nav))*100),
                        limitation="Exploratory gate added after baseline evaluation; does not create an untouched test")
    (args.output/"results.json").write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n")
    (args.output/"curves.json").write_text(json.dumps(curves,separators=(",",":"),allow_nan=False)+"\n")
    for name,w in result.items():
        print(name,w["address"][:10],w["behavior"]["mapped_training_assets"])
        print("discovery",{k:round(v["return_pct"],3) for k,v in w["discovery_copy_performance"].items()},"gate",w["positive_copy_gate"])
        print({p:(round(v["summary"]["return_pct"],3),round(v["summary"]["hourly_open_mdd_pct"],3)) for p,v in w["accounts"].items()})
    print("combined",combined)
    print("copy_gate",payload["positive_copy_gate"])


if __name__=="__main__":
    main()
