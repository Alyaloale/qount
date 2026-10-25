#!/usr/bin/env python3
"""Return concentration, full-account episode omissions and all-signal shadows."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from compare_macro_depth_execution import ROOT, RUNS, depth_context
from compare_macro_exit_depth import ExitContexts
from qount.research.binance_etf_leverage import replay
from qount.research.lines.macro_1atr import inputs
from qount.research.macro_depth_execution import DepthExecution, DepthExitStress


def components(trade, fee):
    notional = trade["quantity"]*trade["entry_price"]
    price_pnl = trade["quantity"]*(trade["exit_price"]-trade["entry_price"])
    fees = trade["entry_fee"]+trade["quantity"]*trade["exit_price"]*fee
    assert math.isclose(price_pnl+trade["funding"]-fees, trade["net_pnl"], abs_tol=1e-9)
    return dict(entry_notional=notional, price_pnl=price_pnl, funding=trade["funding"],
                fees=fees, return_on_entry_notional=trade["net_pnl"]/notional,
                original_account_budget_R=trade["net_pnl"]/trade["risk_budget_usdt"],
                closed=trade["exit_reason"] != "end_of_sample")


def check(result, book, parameters):
    assert math.isclose(parameters["capital"]+sum(t["net_pnl"] for t in result["trades"]),
                        result["summary"]["final_equity"], abs_tol=1e-9)
    for trade in result["trades"]:
        assert trade["feature_available"] < trade["entry_time"] < trade["entry_fill_time"]
        paid = 0.
        exit_stamp = trade["exit_fill_time"]*1000
        delayed = trade["exit_fill_time"] > trade["exit_time"]
        touched = trade["exit_reason"] in ("stop", "liquidation_proxy")
        for row in book[trade["symbol"]]["funding"]:
            stamp = int(row["fundingTime"])
            if stamp < trade["entry_fill_time"]*1000 or (stamp > exit_stamp if delayed else stamp >= exit_stamp):
                continue
            payment = -trade["quantity"]*float(row["markPrice"])*float(row["fundingRate"])
            if touched and stamp >= (trade["exit_time"]-3600)*1000 and payment > 0:
                continue
            paid += payment
        assert math.isclose(paid, trade["funding"], abs_tol=1e-9)
        trade["attribution"] = components(trade, parameters["fee"])


def metrics(result):
    trades, summary = result["trades"], result["summary"]
    closed = [t for t in trades if t["exit_reason"] != "end_of_sample"]
    profits = sorted((t["net_pnl"] for t in trades if t["net_pnl"] > 0), reverse=True)
    total = sum(t["net_pnl"] for t in trades)
    return dict(net_return=summary["net_return"], max_drawdown=summary["max_drawdown"],
        trade_count=len(trades), closed_net_pnl=sum(t["net_pnl"] for t in closed),
        censored_net_pnl=sum(t["net_pnl"] for t in trades if t not in closed),
        top_two_share_of_net=sum(profits[:2])/total if total > 0 else None,
        fixed_ledger_pnl_without_top_two=total-sum(profits[:2]),
        average_closed_notional_return=statistics.mean(t["attribution"]["return_on_entry_notional"] for t in closed)
            if closed else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; previous results are retained")
    previous = json.loads((RUNS/"macro_exit_depth_20261020/uniform_stress_comparison.json").read_text())
    controls = json.loads((RUNS/"macro_small_capital_review_20261019/comparison.json").read_text())
    parameters = copy.deepcopy(controls["results"]["current_base_capital15.2711"]["parameters"])
    parameters.pop("capacity_multiplier")
    venue = json.loads((RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json").read_text())
    book, signals, gates, caps, _ = inputs(ROOT/"binance_macro_attack_20261015",
        [ROOT/n for n in ("binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730",
                         "binance_macro_attack_20261015")],
        ROOT/"binance_macro_liquidity_20261015", "2026-04-07", "2026-10-15")
    for symbol, data in book.items():
        data["rule"] = dict(data["rule"], leverage_brackets=venue["symbols"][symbol]["brackets"])
    entries, sources = {}, []
    eligible = sorted((key for key, g in gates.items() if g["eligible"]), key=lambda k: (k[1], k[0]))
    for key in eligible:
        entries[key], source = depth_context(key, args.download)
        sources.append(source)
    exits = ExitContexts(args.download, sources)
    exit_model = DepthExitStress(exits, fraction=.05, unknown_extra_slip=0, all_extra_slip=.005)
    results, shadows, checks = {}, [], []
    n_replays = 0

    def run(sizing, confirmations, **extra):
        nonlocal n_replays
        result = replay(book, signals, entry_confirmations=confirmations, entry_liquidity_caps=caps,
            entry_execution_model=DepthExecution(entries, use_depth_sizing=sizing == "depth"),
            exit_execution_model=exit_model, **parameters, **extra)
        n_replays += 1
        check(result, book, parameters)
        result["diagnostic"] = metrics(result)
        return result

    for sizing in ("volume", "depth"):
        baseline = run(sizing, gates)
        expected = previous["results"][f"risk0.5_{sizing}_all_exit0.005"]
        clean = [{k:v for k,v in t.items() if k != "attribution"} for t in baseline["trades"]]
        assert clean == expected["trades"] and baseline["curve"] == expected["curve"]
        checks.append(sizing+": exact retained trades and curve")
        results[sizing+"_control"] = baseline
        ranked = sorted(baseline["trades"], key=lambda t: -t["net_pnl"])
        omissions = [("omit_"+t["symbol"]+"_"+str(t["entry_time"]), [t]) for t in baseline["trades"]]
        omissions += [("omit_top_two", ranked[:2])]
        for label, omitted in omissions:
            episodes = {(t["symbol"], gates[t["symbol"], t["entry_time"]]["anchor_time"]) for t in omitted}
            adjusted = {key: dict(g, eligible=False, reason="retrospective_episode_omission")
                        if (key[0], g["anchor_time"]) in episodes else g for key,g in gates.items()}
            result = run(sizing, adjusted)
            result["omitted_episodes"] = sorted(episodes)
            assert all((t["symbol"], gates[t["symbol"],t["entry_time"]]["anchor_time"]) not in episodes
                       for t in result["trades"])
            results[sizing+"_"+label] = result
            print(sizing, label, json.dumps(result["diagnostic"]), flush=True)
        for symbol in sorted({t["symbol"] for t in baseline["trades"]}):
            adjusted = {key: dict(g, eligible=False, reason="retrospective_symbol_omission")
                        if key[0] == symbol else g for key,g in gates.items()}
            result = run(sizing, adjusted)
            assert all(t["symbol"] != symbol for t in result["trades"])
            results[f"{sizing}_omit_asset_{symbol}"] = result
            print(sizing, "omit_asset", symbol, json.dumps(result["diagnostic"]), flush=True)
        # Every eligible signal is kept, including rejected and censored ones.
        # Equal initial cash and no competing position isolate missed episodes.
        for symbol, now in eligible:
            result = run(sizing, gates, forced_entry=dict(symbol=symbol,time=now,engine="tactical"),
                         entry_end_exclusive=now+1)
            assert len(result["trades"]) <= 1
            trade = result["trades"][0] if result["trades"] else None
            shadows.append(dict(sizing=sizing, symbol=symbol, time=now,
                setup=gates[symbol,now]["setup"], anchor_time=gates[symbol,now]["anchor_time"],
                trade=trade, rejections=result["summary"]["rejections"]))
            print("shadow", sizing, symbol, dt.datetime.fromtimestamp(now,dt.timezone.utc).isoformat(),
                  None if trade is None else round(trade["net_pnl"],6), flush=True)
    grouped = defaultdict(list)
    for row in shadows:
        for dimension, key in (("all", "all"), ("asset", row["symbol"]), ("setup", row["setup"])):
            grouped[row["sizing"],dimension,key].append(row)
    shadow_summary = []
    for (sizing,dimension,key), rows in sorted(grouped.items()):
        executed = [r["trade"] for r in rows if r["trade"] is not None]
        closed = [t for t in executed if t["attribution"]["closed"]]
        values = [t["attribution"]["return_on_entry_notional"] for t in closed]
        shadow_summary.append(dict(sizing=sizing,dimension=dimension,key=key,eligible=len(rows),
            executed=len(executed),closed=len(closed),censored=len(executed)-len(closed),
            mean_closed_notional_return=statistics.mean(values) if values else None,
            median_closed_notional_return=statistics.median(values) if values else None,
            positive_closed=sum(x > 0 for x in values)))
    output = dict(research_only=True,orders_authorized=False,
        hypothesis="Determine concentration, opportunity substitution and per-notional signal outcomes before increasing exposure.",
        sample_start="2026-04-07",sample_end_exclusive="2026-10-15",initial_capital=parameters["capital"],
        symbols=list(book),benchmark="cash 0%",parameters=parameters,
        execution=dict(entry_depth_fraction=.25,exit_depth_fraction=.05,latency_seconds=30,
                       all_exit_extra_slip=.005,unknown_book_extra_slip=0),
        control_checks=checks,replay_count=n_replays,sources=sources,
        limitations=[
            "Consumed history. Exclusions selected using realized outcomes are hindsight fragility diagnostics, never tradable rules.",
            "Omissions rerun full account, quantities, signal competition and future opportunities; not static PnL subtraction.",
            "All eligible shadows use identical initial cash and current tiers; overlap and cannot be summed as portfolio returns.",
            "Per-entry-notional normalization is descriptive; does not prove equal-sized orders could fill or keep identical exits.",
            "Unknown books assume full exit at original proxy plus common 50bp shock; no proof of liquidation capacity.",
            "Censored trades excluded from closed shadow averages; rejected signals remain visible, no cost-gate bypass.",
            "20 eligible timestamps are not independent events; same-asset time windows can overlap despite separate anchors.",
            "Base per-side fee/slip5/25bp plus50bp exit shock and actual funding; next-time fills and native protection assumptions retained.",
        ],results=results,shadows=shadows,shadow_summary=shadow_summary)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as file:
        file.write(json.dumps(output,allow_nan=False)+"\n")
    print("saved",args.output,"replays",n_replays,flush=True)


if __name__ == "__main__":
    main()
