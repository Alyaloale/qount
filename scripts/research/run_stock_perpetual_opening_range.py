"""Evaluate the standalone 60-minute opening-range candidate on cached perp weeks."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import statistics
from pathlib import Path

from qount.research.small_account_breakout import Signal, aggregate, atr, load_data, session, simulate
from qount.research.small_account_breakout_data import sha, timestamp, write_json

UTC=dt.timezone.utc


def build_signals(data, config, symbol: str, start: int, end: int):
    bars=aggregate(sorted(data.minutes[symbol].values(),key=lambda b:b.t),900,60)
    values=atr(bars)
    updates={symbol:{b.t+900:(b,values[i]) for i,b in enumerate(bars) if values[i] is not None}}
    sessions={}
    for b in bars:
        info=session(b.t)
        if info is None: continue
        day,minute,_=info
        sessions.setdefault(day,[]).append((minute,b))
    signals=[]; diagnostics=[]
    for day,rows in sorted(sessions.items()):
        opening=[b for minute,b in rows if 570<=minute<630]
        if len(opening)!=4 or [b.t for b in opening]!=list(range(opening[0].t,opening[0].t+3600,900)):
            continue
        range_high=max(b.h for b in opening);range_low=min(b.l for b in opening)
        width=range_high-range_low
        if width<=0: continue
        chosen=None
        for minute,b in rows:
            close=b.t+900
            if minute<630 or not start<=close<end: continue
            side=1 if b.c>range_high else (-1 if b.c<range_low else 0)
            if not side: continue
            vol=updates[symbol][close][1]
            if not vol: continue
            stop=range_low if side==1 else range_high
            sig=Signal(symbol,"stock",side,close,b.c,vol,event_id=f"{symbol}:{day}",structural_stop=stop)
            chosen=sig
            diagnostics.append({"symbol":symbol,"session":day,"range_high":range_high,"range_low":range_low,
                "range_width_fraction":width/b.c,"signal_time":dt.datetime.fromtimestamp(close,UTC).isoformat(),
                "side":"long" if side==1 else "short","signal_close":b.c,"structural_stop":stop})
            break
        if chosen: signals.append(chosen)
    return signals,updates,diagnostics


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path,default=Path("config/stock-perpetual-opening-range-v01.json"))
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists(): raise FileExistsError("refuse_overwrite_research_bundle")
    plan=json.loads(args.config.read_text());base=json.loads(Path(plan["base_config"]).read_text())
    cfg=copy.deepcopy(base);cfg.update({"initial_equity_usdt":plan["initial_equity_usdt_per_symbol_week"],
        "stock_symbols":plan["symbols"],"crypto_symbols":base["crypto_symbols"],
        "stock_fee_per_side":plan["fee_per_side"],"stock_slippage_per_side":plan["slippage_per_side"],
        "funding_interval_mode":"known_or_observed","funding_interval_fallback_hours":8.0,"size_to_liquidity":True})
    cache=Path(plan["cache"])
    args.output.mkdir(parents=True)
    write_json(args.output/"contract.json",plan)
    all_results={};all_signals=[]
    for symbol in plan["symbols"]:
        for week in base["draw_order"]:
            start,end=timestamp(week),timestamp(week)+7*86400
            data=load_data(cache,cfg,week)
            signals,updates,diag=build_signals(data,cfg,symbol,start,end)
            for row in diag: row["week"]=week
            all_signals.extend(diag)
            bundle=simulate(data,cfg,week,signals,updates,variant="combined",risk=plan["risk_fraction"],end_time=end)
            for t in bundle["trades"]:
                side=1 if t["side"]=="long" else -1
                pnl=side*t["quantity"]*(t["exit_price"]-t["entry_price"])-t["fees_usdt"]+t["funding_net_usdt"]
                if not math.isclose(pnl,t["net_pnl_usdt"],abs_tol=1e-8): raise AssertionError("trade_ledger")
                tick=float(next(f["tickSize"] for f in data.rules[symbol]["filters"] if f["filterType"]=="PRICE_FILTER"))
                boundary=t["signal"]["structural_stop"]
                if (t["side"]=="long" and not boundary-1e-8<=t["initial_stop"]<=boundary+tick+1e-8) or (
                        t["side"]=="short" and not boundary-tick-1e-8<=t["initial_stop"]<=boundary+1e-8):
                    raise AssertionError("structural_stop_rounding")
            name=f"{symbol}_{week}"
            write_json(args.output/f"{name}.json",bundle)
            all_results[name]=bundle["summary"]
    write_json(args.output/"signals.json",{"candidate_signals":all_signals,"signal_count":len(all_signals)})
    rows=["# Stock perpetual 60-minute opening-range candidate","",
        "Five disjoint cached 2026 development weeks. Each symbol-week starts a separate 10 USDT account; results are not compounded or combined.",
        "The 09:30–10:30 New York range uses four complete 15-minute bars. The first complete 15-minute close after 10:30 outside the range sets direction; the opposite range edge is the structural stop; exit is at 15:45 (or 15 minutes before an early close).",
        "","|Symbol|Week|Side|Signals|Trades|Net return|MDD|Net PnL USDT|","|---|---|---|---:|---:|---:|---:|---:|"]
    for name,s in all_results.items():
        sym,week=name.rsplit("_",1)
        trades=s["trade_count"]
        side_counts={}
        for row in all_signals:
            if row["symbol"]==sym and row["week"]==week:
                side_counts[row["side"]]=side_counts.get(row["side"],0)+1
        rows.append(f"|{sym}|{week}|L{side_counts.get('long',0)}/S{side_counts.get('short',0)}|{sum(side_counts.values())}|{trades}|{s['net_return']:.2%}|{s['max_drawdown']:.2%}|{s['final_equity_usdt']-s['initial_equity_usdt']:+.4f}|")
    rows += ["","Research-only candidate, not a combined portfolio. Costs use the existing 5bp fee/10bp slippage assumptions; historical fees, order books, and contract filters are not independently authenticated.",
        "The five weeks are discovery history already consumed by the earlier stock-perpetual diagnostics. No independent validation or live execution evidence is claimed.",""]
    (args.output/"report.md").write_text("\n".join(rows))
    summary={"runs":all_results,"signal_count":len(all_signals),"by_symbol":{
        s:{"signals":sum(x["symbol"]==s for x in all_signals),"trades":sum(v["stock_trades"] for k,v in all_results.items() if k.startswith(s+"_")),
           "net_pnl_usdt_sum_across_separate_weeks":sum(v["final_equity_usdt"]-v["initial_equity_usdt"] for k,v in all_results.items() if k.startswith(s+"_"))}
        for s in plan["symbols"]},"sample_role":"discovery_consumed","research_only":True,"orders_authorized":False}
    write_json(args.output/"summary.json",summary)
    sources=[args.config,Path(plan["base_config"]),Path(__file__),Path("src/qount/research/small_account_breakout.py"),Path("src/qount/research/small_account_breakout_data.py")]
    manifest={"created_at":dt.datetime.now(UTC).isoformat(),"source_hashes":{str(x):sha(x) for x in sources},
        "pilot_input_manifest_sha256":sha(cache/"manifest.json"),"files":{x.name:sha(x) for x in sorted(args.output.iterdir()) if x.is_file()},
        "sample_role":"discovery_consumed","research_only":True,"orders_authorized":False}
    write_json(args.output/"manifest.json",manifest);(args.output/"_COMPLETE").write_text(sha(args.output/"manifest.json")+"\n")
    return 0


if __name__=="__main__": raise SystemExit(main())
