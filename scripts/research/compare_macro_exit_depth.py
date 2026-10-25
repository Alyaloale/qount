#!/usr/bin/env python3
"""Replay complete exits with discounted bid depth and explicit unknown-book costs."""
from __future__ import annotations

import argparse
import copy
import json
import math
from collections import Counter
from pathlib import Path

from compare_macro_depth_execution import ROOT, RUNS, depth_context
from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import cost_case
from qount.research.lines.macro_1atr import inputs
from qount.research.macro_depth_execution import DepthExecution, DepthExitStress


class ExitContexts(dict):
    """Load only exits actually reached, never use exit books to select entries."""
    def __init__(self, download, sources):
        super().__init__()
        self.download, self.sources = download, sources

    def get(self, key, default=None):
        if key not in self:
            rows, source = depth_context(key, self.download)
            self[key] = rows
            self.sources.append(source)
        return self[key]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; old experiments are retained")
    previous = json.loads((RUNS/"macro_depth_execution_20261020/with_exit_depth.json").read_text())
    old = json.loads((RUNS/"macro_small_capital_review_20261019/comparison.json").read_text())["results"]
    venue = json.loads((RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json").read_text())
    book, signals, gates, caps, _ = inputs(ROOT/"binance_macro_attack_20261015",
        [ROOT/n for n in ("binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730",
                         "binance_macro_attack_20261015")],
        ROOT/"binance_macro_liquidity_20261015", "2026-04-07", "2026-10-15")
    for symbol, data in book.items():
        data["rule"] = dict(data["rule"], leverage_brackets=venue["symbols"][symbol]["brackets"])
    entries, sources = {}, []
    for key, gate in gates.items():
        if gate["eligible"]:
            entries[key], source = depth_context(key, args.download)
            sources.append(source)
    exits = ExitContexts(args.download, sources)
    # Fix entry assumptions while varying exit capacity. These fractions and
    # unknown-book loss scenarios are sensitivity inputs, not fitted estimates.
    scenarios = [
        ("volume_control", "volume", .25, None, 0, "base", True),
        ("depth_control", "depth", .25, None, 0, "base", True),
        ("delay_funding_only", "depth", .25, .25, 0, "base", False),
    ]
    for fraction in (.25, .05, .01):
        for unknown in (.005, .02, .05):
            scenarios.append((f"entry25_exit{fraction:g}_unknown{unknown:g}",
                              "depth", .25, fraction, unknown, "base", True))
    scenarios += [
        ("joint5_unknown200bp", "depth", .05, .05, .02, "base", True),
        ("joint1_unknown200bp", "depth", .01, .01, .02, "base", True),
        ("volume_exit5_unknown200bp", "volume", .25, .05, .02, "base", True),
        ("double_cost_exit5_unknown200bp", "depth", .25, .05, .02, "double_cost", True),
    ]
    scenarios = [(*row, .5) for row in scenarios]
    scenarios += [
        ("risk25_exit5_unknown200bp", "depth", .25, .05, .02, "base", True, .25),
        ("risk25_exit5_unknown500bp", "depth", .25, .05, .05, "base", True, .25),
        ("risk25_exit1_unknown200bp", "depth", .25, .01, .02, "base", True, .25),
        ("risk25_volume_exit5_unknown200bp", "volume", .25, .05, .02, "base", True, .25),
        ("risk25_double_cost_exit5_unknown200bp", "depth", .25, .05, .02, "double_cost", True, .25),
    ]
    scenarios = [(*row, 0.) for row in scenarios]
    for risk in (.5, .25):
        for sizing in ("volume", "depth"):
            for shock in (.005, .02):
                scenarios.append((f"risk{risk:g}_{sizing}_all_exit{shock:g}",
                    sizing, .25, .05, 0., "base", True, risk, shock))
    results, checks = {}, []
    for name, sizing, entry_fraction, exit_fraction, unknown, costs, use_depth, risk, all_shock in scenarios:
        parameters = copy.deepcopy(old[f"current_{costs}_capital15.2711"]["parameters"])
        parameters.pop("capacity_multiplier")
        parameters["risk_fraction"] = risk
        data = cost_case(book, costs)
        entry = DepthExecution(entries, use_depth_sizing=sizing == "depth", fill_fraction=entry_fraction)
        exit_model = None if exit_fraction is None else DepthExitStress(
            exits, fraction=exit_fraction, unknown_extra_slip=unknown, use_depth=use_depth,
            all_extra_slip=all_shock)
        result = replay(data, signals, entry_confirmations=gates, entry_liquidity_caps=caps,
                        entry_execution_model=entry, exit_execution_model=exit_model, **parameters)
        if exit_fraction is None:
            expected = previous["results"][f"{sizing}_survival25_base"]
            assert result["curve"] == expected["curve"] and result["trades"] == expected["trades"]
            checks.append(name+": exact retained curve and trades")
        summary = result["summary"]
        for trade in result["trades"]:
            # Independent signed settlement reconciliation. All current sample
            # exits are scheduled/terminal, so no unknown stop-credit ordering.
            assert trade["exit_reason"] not in ("stop", "liquidation_proxy", "drawdown_halt")
            filled_in = trade["entry_fill_time"]*1000
            filled_out = trade.get("exit_fill_time", trade["exit_time"])*1000
            delayed = filled_out > trade["exit_time"]*1000
            funding = sum(-trade.get("side", 1)*trade["quantity"]*float(r["markPrice"])*float(r["fundingRate"])
                for r in data[trade["symbol"]]["funding"] if filled_in <= int(r["fundingTime"])
                and (int(r["fundingTime"]) <= filled_out if delayed else int(r["fundingTime"]) < filled_out))
            assert math.isclose(funding, trade["funding"], abs_tol=1e-9)
            pnl = trade["quantity"]*(trade["exit_price"]-trade["entry_price"])+funding-parameters["fee"]*(
                trade["quantity"]*trade["exit_price"]+trade["quantity"]*trade["entry_price"])
            assert math.isclose(pnl, trade["net_pnl"], abs_tol=1e-9)
        assert math.isclose(parameters["capital"]+sum(t["net_pnl"] for t in result["trades"]),
                            summary["final_equity"], abs_tol=1e-9)
        summary.update(
            closed_net_pnl=sum(t["net_pnl"] for t in result["trades"] if t["exit_reason"] != "end_of_sample"),
            censored_net_pnl=sum(t["net_pnl"] for t in result["trades"] if t["exit_reason"] == "end_of_sample"),
            delayed_exit_funding=sum(t.get("exit_execution", {}).get("delayed_funding", 0) for t in result["trades"]),
            exit_status_counts=dict(Counter(t.get("exit_execution", {}).get("status", "original_proxy")
                                           for t in result["trades"])))
        result["parameters"] = dict(parameters, entry_sizing=sizing, entry_depth_fraction=entry_fraction,
            exit_depth_fraction=exit_fraction, unknown_book_extra_slip=unknown, exit_uses_depth=use_depth,
            exit_delay_seconds=30 if exit_model else 0, all_exit_extra_slip=all_shock)
        results[name] = result
        print(name, json.dumps({k: summary[k] for k in ("net_return", "max_drawdown", "trade_count",
            "closed_net_pnl", "censored_net_pnl", "delayed_exit_funding", "exit_status_counts")}), flush=True)
    output = dict(research_only=True, orders_authorized=False,
        hypothesis="Does discounted-depth entry retain its conditional historical benefit after "
                   "full-position exit capacity, delayed settlements and unknown-book price shocks?",
        sample_start="2026-04-07", sample_end_exclusive="2026-10-15", initial_capital=15.27112826,
        symbols=list(book), benchmark="cash 0%", sources=sources, baseline_checks=checks,
        limitations=[
            "Consumed historical sample; scenario analysis, not independent OOS or realized trading.",
            "Existing entry risk/admission and fee assumptions unchanged; exit losses affect future account sizing.",
            "Entry quote 25% static bound, fixed limit; arrival depth fraction 25/5/1%, first quote+30s, deadline90s.",
            "Scheduled exit first snapshot >=decision+30s and <=decision+90s; no earlier/later cherry-picking.",
            "Known exit price uses original 25bp/50bp floor if quantity covered; else lower cumulative bid-band boundary.",
            "Band boundary is a conservative conditional price floor, not reconstructed VWAP or market-order receipt.",
            "Missing, inconsistent or insufficient books assume full exit at additional 50/200/500bp loss.",
            "Unknown-book shocks are NOT maximum losses or evidence liquidation is available; no exit is silently discarded.",
            "Uniform extra exit-price shocks apply to every exit and terminal valuation, independent of archive availability; "
            "in those arms unknown-book-only extra loss is zero to avoid double counting.",
            "All delayed-exit settlements through fill timestamp included; exact timestamp settlement precedes exit by convention.",
            "Native protection still assumed successful. Intra-hour trigger times remain unknown, no synthetic L2 proof.",
            "Current tiers applied historically, no calibrated cancellation/impact or real execution latency.",
            "Full exits may occur seconds after nominal holding deadline; original decision clocks remain fixed.",
        ], results=results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as file:
        file.write(json.dumps(output, allow_nan=False)+"\n")
    print("saved", args.output, flush=True)


if __name__ == "__main__":
    main()
