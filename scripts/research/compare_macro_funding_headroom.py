#!/usr/bin/env python3
"""Offline fixed 10% entry-headroom ablation; never accesses accounts or orders."""
from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import cost_case
from qount.research.lines.macro_1atr import inputs
from qount.strategies.macro_funding import feature_at


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("state/research_runs/macro_funding_headroom_20261020/comparison.json"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new --output to preserve retained results")
    old_path = Path("state/research_runs/macro_small_capital_review_20261019/comparison.json")
    venue_path = Path("state/research_runs/macro_leverage_cash_review_20261019/venue_snapshot.json")
    old = json.loads(old_path.read_text())["results"]
    venue = json.loads(venue_path.read_text())
    root = Path("state/research_cache")
    book, signals, gates, caps, _ = inputs(
        root/"binance_macro_attack_20261015",
        [root/name for name in ("binance_macro_prefix_20260407_20260611",
                               "binance_macro_earlier_20260611_20260730",
                               "binance_macro_attack_20261015")],
        root/"binance_macro_liquidity_20261015", "2026-04-07", "2026-10-15")
    for symbol, data in book.items():
        data["rule"] = dict(data["rule"], leverage_brackets=venue["symbols"][symbol]["brackets"])
    results, checks = {}, []
    # Original execution proxy plus the two previously observed budget failures.
    # These are fixed mechanism controls, not a capacity/threshold search.
    for context in ("current", "capacity25_risk25", "capacity50"):
        for scenario in ("base", "double_cost"):
            previous = old[f"{context}_{scenario}_capital15.2711"]
            parameters = copy.deepcopy(previous["parameters"])
            multiplier = parameters.pop("capacity_multiplier")
            capacity = {key: dict(row, quantity_cap=row["quantity_cap"]*multiplier,
                                  participation=row["participation"]*multiplier)
                        for key, row in caps.items()}
            for utilization in (1., .9):
                key = f"{context}_{scenario}_utilization{utilization:g}"
                result = replay(cost_case(book, scenario), signals,
                                entry_confirmations=gates, entry_liquidity_caps=capacity,
                                funding_lease_entry_utilization=utilization, **parameters)
                if utilization == 1:
                    expected = [{k: v for k, v in trade.items()
                                 if k not in ("sizing_diagnostic", "pnl_components")}
                                for trade in previous["trades"]]
                    assert result["trades"] == expected, f"{key}: control trades changed"
                    assert result["curve"] == previous["curve"], f"{key}: control NAV changed"
                    checks.append(key+": exact retained trades and curve")
                capital = parameters["capital"]
                assert math.isclose(capital+sum(t["net_pnl"] for t in result["trades"]),
                                    result["summary"]["final_equity"], abs_tol=1e-8)
                for trade in result["trades"]:
                    assert trade["feature_available"] < trade["entry_time"]
                    budget = trade.get("entry_sizing_budget_usdt", trade["risk_budget_usdt"])
                    assert trade["stress_risk_usdt"] <= budget+1e-9
                    assert budget <= trade["risk_budget_usdt"]+1e-9
                    for review in trade.get("funding_lease_reviews", []):
                        assert review["funding_cost_cap"] == trade["funding_cost_cap_usdt"]
                        if review["allowed"]:
                            assert review["stress_risk"] <= review["risk_budget"]+1e-9
                summary = result["summary"]
                summary.update(
                    closed_net_pnl=sum(t["net_pnl"] for t in result["trades"]
                                       if t["exit_reason"] != "end_of_sample"),
                    censored_net_pnl=sum(t["net_pnl"] for t in result["trades"]
                                         if t["exit_reason"] == "end_of_sample"))
                result["parameters"] = dict(parameters, capacity_multiplier=multiplier,
                                             funding_lease_entry_utilization=utilization)
                results[key] = result
                print(key, json.dumps({k: summary[k] for k in
                    ("net_return", "max_drawdown", "trade_count", "closed_net_pnl", "censored_net_pnl")}),
                    flush=True)
    # Paired single-event controls test whether the mechanism extends beyond
    # the portfolio's final censored trade. They never add up to portfolio PnL.
    shadows, episodes = [], {}
    previous_shadows = json.loads(Path(
        "state/research_runs/macro_execution_allocation_review_20261019/allocation.json").read_text())["shadows"]
    previous_shadows = {(r["symbol"], r["time"], r["scenario"]): r["trade"]
                        for r in previous_shadows}
    for (symbol, now), gate in sorted(gates.items(), key=lambda item: (item[0][1], item[0][0])):
        if not gate["eligible"]:
            continue
        feature = feature_at(signals[symbol], now)
        for scenario in ("base", "double_cost"):
            parameters = copy.deepcopy(old[f"current_{scenario}_capital15.2711"]["parameters"])
            parameters.pop("capacity_multiplier")
            paired = {}
            for utilization in (1., .9):
                result = replay(cost_case(book, scenario), signals,
                                entry_confirmations=gates, entry_liquidity_caps=caps,
                                forced_entry=dict(symbol=symbol, time=now, engine="tactical"),
                                entry_end_exclusive=now+1,
                                funding_lease_entry_utilization=utilization, **parameters)
                assert len(result["trades"]) <= 1
                trade = result["trades"][0] if result["trades"] else None
                if utilization == 1:
                    assert trade == previous_shadows[symbol, now, scenario]
                assert math.isclose(parameters["capital"]+(trade["net_pnl"] if trade else 0),
                                    result["summary"]["final_equity"], abs_tol=1e-8)
                paired[str(utilization)] = trade
            row = dict(symbol=symbol, time=now, anchor_time=gate["anchor_time"],
                       setup=feature["tactical_setup"], scenario=scenario, trades=paired)
            shadows.append(row)
            if paired["1.0"] is not None:
                episodes.setdefault((scenario, symbol, gate["anchor_time"]), row)
    closed_pairs = [r for r in episodes.values()
                    if r["trades"]["1.0"]["exit_reason"] != "end_of_sample"]
    episode_summary = {}
    for scenario in ("base", "double_cost"):
        rows = [r for r in closed_pairs if r["scenario"] == scenario]
        outcomes = []
        for row in rows:
            a, b = row["trades"]["1.0"], row["trades"]["0.9"]
            # Normalize by the SAME initial account budget, not each arm's
            # smaller utilized risk, to avoid a favorable denominator change.
            outcomes.append(dict(symbol=row["symbol"], time=row["time"],
                pnl_delta=(b["net_pnl"] if b else 0)-a["net_pnl"],
                original_budget_R_delta=((b["net_pnl"] if b else 0)-a["net_pnl"])/a["risk_budget_usdt"],
                quantity_changed=b is None or b["quantity"] != a["quantity"],
                exit_changed=b is None or b["exit_time"] != a["exit_time"] or b["exit_reason"] != a["exit_reason"],
                new_censored=b is not None and b["exit_reason"] == "end_of_sample"))
        episode_summary[scenario] = dict(
            closed_control_episodes=len(rows),
            quantity_changes=sum(r["quantity_changed"] for r in outcomes),
            exit_changes=sum(r["exit_changed"] for r in outcomes),
            new_censored=sum(r["new_censored"] for r in outcomes),
            mean_original_budget_R_delta=statistics.mean(r["original_budget_R_delta"] for r in outcomes)
                                        if outcomes else None,
            episodes=outcomes)
        print("paired_episodes", scenario, json.dumps(episode_summary[scenario]), flush=True)
    output = dict(
        research_only=True, orders_authorized=False,
        hypothesis="Leave 10% of the original stress budget unused at leased MR entry; "
                   "test whether smaller positions avoid budget-driven early exits.",
        sample_start="2026-04-07", sample_end_exclusive="2026-10-15",
        initial_capital=15.27112826, symbols=list(book), benchmark="cash, 0%",
        source_controls=str(old_path), venue_snapshot=str(venue_path),
        limitations=[
            "Consumed historical exploration; 90% was chosen after observing budget exits, not independent OOS.",
            "Capacity25 and capacity50 are unvalidated volume-proxy counterfactuals, not executable returns.",
            "Only initial MR sizing uses a smaller budget. Original lifetime risk/funding/cash checks and full exits remain.",
            "Hourly fill/stop model; present venue tiers applied historically; no new live settings.",
            "Terminal positions are marked and costed at sample end, not confirmed strategy exits.",
            "Base per-side fee/slippage 5/25 bp; double-cost 10/50 bp plus doubled adverse regular funding.",
            "Single-event shadows overlap; first executable baseline episode selected, censored controls excluded.",
        ], control_checks=checks, results=results, shadows=shadows,
        paired_episode_summary=episode_summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as file:
        file.write(json.dumps(output, allow_nan=False)+"\n")
    print("saved", args.output, flush=True)


if __name__ == "__main__":
    main()
