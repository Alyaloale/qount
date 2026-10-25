#!/usr/bin/env python3
"""Compare a smaller risk budget with a notional cap, retaining live volume sizing."""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from unittest.mock import patch

from compare_macro_depth_execution import ROOT, RUNS
from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import cost_case
from qount.research.lines.macro_1atr import inputs
from qount.research.macro_depth_execution import DepthExitStress
from qount.strategies import macro_1atr as live_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; old research is retained")
    old_path = RUNS/"macro_small_capital_review_20261019/comparison.json"
    old = json.loads(old_path.read_text())["results"]
    venue_path = RUNS/"macro_leverage_cash_review_20261019/venue_snapshot.json"
    venue = json.loads(venue_path.read_text())
    book, signals, gates, caps, _ = inputs(ROOT/"binance_macro_attack_20261015",
        [ROOT/n for n in ("binance_macro_prefix_20260407_20260611", "binance_macro_earlier_20260611_20260730",
                         "binance_macro_attack_20261015")],
        ROOT/"binance_macro_liquidity_20261015", "2026-04-07", "2026-10-15")
    for symbol, data in book.items():
        data["rule"] = dict(data["rule"], leverage_brackets=venue["symbols"][symbol]["brackets"])
    base = copy.deepcopy(old["current_base_capital15.2711"]["parameters"])
    base.pop("capacity_multiplier")
    cases = [("base", "base", 0.), ("double_cost", "double_cost", 0.),
             ("extra_exit50bp", "base", .005), ("extra_exit200bp", "base", .02)]
    policies = [("current", .5, 20), ("risk25", .25, 20),
                ("gross2", .5, 2), ("risk25_gross2", .25, 2)]
    # These are fixed robustness perturbations, not implementable trading vetoes.
    baseline_trades = old["current_base_capital15.2711"]["trades"]
    iwms = [t for t in baseline_trades if t["symbol"] == "IWMUSDT"]
    last = max(baseline_trades, key=lambda t:t["entry_time"])
    omitted = [("all", []), ("missing_iwm", iwms), ("missing_iwm_and_last", iwms+[last])]
    results, checks = {}, []
    count = 0
    for label, risk, gross in policies+[("neighbor20", .2, 20), ("neighbor30", .3, 20)]:
        for omission, missing in (omitted if label in {p[0] for p in policies} else omitted[:1]):
            for case, costs, shock in (cases if omission == "all" else cases[2:]):
                parameters = dict(base, risk_fraction=risk, gross_cap=gross,
                    fee=.001 if costs == "double_cost" else .0005,
                    slip=.005 if costs == "double_cost" else .0025)
                episodes = {(t["symbol"], gates[t["symbol"],t["entry_time"]]["anchor_time"])
                            for t in missing}
                confirmations = {key: dict(g, eligible=False, reason="missing_opportunity_sensitivity")
                    if (key[0],g["anchor_time"]) in episodes else g for key,g in gates.items()}
                # This isolates unexpected adverse exits from admission costs.
                # No depth sizing or hypothetical extra IOC capacity is enabled.
                exit_model = DepthExitStress({}, use_depth=False, all_extra_slip=shock) if shock else None
                data = cost_case(book, costs)
                result = replay(data, signals, entry_confirmations=confirmations,
                                entry_liquidity_caps=caps, exit_execution_model=exit_model, **parameters)
                key = f"{label}_{omission}_{case}"
                count += 1
                if omission == "all" and not shock and label in ("current", "risk25"):
                    previous = old[f"{label}_{costs}_capital15.2711"]
                    clean = [{k:v for k,v in t.items() if k not in ("sizing_diagnostic", "pnl_components")}
                             for t in previous["trades"]]
                    assert result["trades"] == clean and result["curve"] == previous["curve"]
                    checks.append(key+": exact retained trades and curve")
                assert all((t["symbol"],gates[t["symbol"],t["entry_time"]]["anchor_time"]) not in episodes
                           for t in result["trades"])
                for trade in result["trades"]:
                    assert trade["feature_available"] < trade["entry_time"]
                    assert trade["stress_risk_usdt"] <= risk*trade["equity_before_entry"]+1e-8
                    assert trade["notional_usdt"] <= gross*trade["equity_before_entry"]+1e-8
                    filled_out = trade.get("exit_fill_time",trade["exit_time"])*1000
                    delayed = trade.get("exit_fill_time",trade["exit_time"]) > trade["exit_time"]
                    funding = 0.
                    for row in data[trade["symbol"]]["funding"]:
                        stamp = int(row["fundingTime"])
                        if stamp < trade["entry_time"]*1000 or (stamp > filled_out if delayed else stamp >= filled_out):
                            continue
                        payment = -trade["quantity"]*float(row["markPrice"])*float(row["fundingRate"])
                        if (trade["exit_reason"] in ("stop", "liquidation_proxy")
                                and stamp >= (trade["exit_time"]-3600)*1000 and payment > 0):
                            continue
                        funding += payment
                    assert math.isclose(funding,trade["funding"],abs_tol=1e-9)
                    pnl = trade["quantity"]*(trade["exit_price"]-trade["entry_price"])+funding-parameters["fee"]*(
                        trade["quantity"]*trade["entry_price"]+trade["quantity"]*trade["exit_price"])
                    assert math.isclose(pnl,trade["net_pnl"],abs_tol=1e-9)
                assert math.isclose(parameters["capital"]+sum(t["net_pnl"] for t in result["trades"]),
                                    result["summary"]["final_equity"],abs_tol=1e-9)
                result["parameters"] = dict(parameters, omission=omission, extra_exit_slip=shock)
                result["summary"].update(
                    closed_net_pnl=sum(t["net_pnl"] for t in result["trades"] if t["exit_reason"] != "end_of_sample"),
                    censored_net_pnl=sum(t["net_pnl"] for t in result["trades"] if t["exit_reason"] == "end_of_sample"))
                results[key] = result
                print(key,json.dumps({k:result["summary"][k] for k in (
                    "net_return","max_drawdown","trade_count","closed_net_pnl","censored_net_pnl")}),flush=True)
    # Exercise the actual pure entry policy with a process-local constant patch.
    # No production file, service, account or persistent setting is modified.
    policy_checks = []
    geometry = ("quantity", "entry_price", "initial_stop", "leverage", "risk_budget_usdt",
                "stress_risk_usdt", "margin_usdt", "structural_r", "funding_cost_cap_usdt")
    configured_risk = live_policy.RISK_FRACTION
    for label,risk in (("current",.5),("risk25",.25)):
        with patch.object(live_policy,"RISK_FRACTION",risk):
            for costs in ("base","double_cost"):
                result = results[f"{label}_all_{costs}"]
                parameters = result["parameters"]
                data = cost_case(book,costs)
                for trade in result["trades"]:
                    candidates,_ = live_policy.entry_candidates(data,signals,caps,trade["entry_time"],
                        trade["equity_before_entry"],fee=parameters["fee"],slip=parameters["slip"])
                    assert candidates and candidates[0]["symbol"] == trade["symbol"]
                    for field in geometry:
                        assert candidates[0].get(field) == trade.get(field), (label,costs,field)
                    policy_checks.append(dict(policy=label,scenario=costs,symbol=trade["symbol"],
                                              time=trade["entry_time"]))
    assert live_policy.RISK_FRACTION == configured_risk
    output = dict(research_only=True,orders_authorized=False,
        hypothesis="A smaller asset-neutral stress budget improves capital efficiency without relying on larger fills; "
                   "compare a separate gross cap, adjacent budgets and common missing-opportunity scenarios.",
        sample_start="2026-04-07",sample_end_exclusive="2026-10-15",initial_capital=base["capital"],
        symbols=list(book),benchmark="cash 0%",control_file=str(old_path),venue_snapshot=str(venue_path),
        replay_count=count,control_checks=checks,pure_entry_policy_checks=policy_checks,
        candidate_delta=dict(risk_fraction=dict(previous=.5,candidate=.25)),
        limitations=[
            "Consumed historical exploration with only seven original trades; no independent OOS or future-profit guarantee.",
            "Existing hourly entry/stop/mark and volume-cap model retained, no new IOC or displayed-depth fill assumption.",
            "Extra adverse exit shocks retain original ex-ante admission costs, affect subsequent cash and sizing; "
            "assumed full liquidation at the stressed price is not proven executable or a maximum loss.",
            "Current tiers applied historically, native protection assumed successful; stress budgets are not loss limits.",
            "Missing opportunities are hindsight robustness diagnostics, not signal filters; identical episodes omitted across policies.",
            "Terminal valuation is censored and reported separately; adjacent budgets are sensitivity checks, not optimal-parameter claims.",
        ],results=results)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as file: file.write(json.dumps(output,allow_nan=False)+"\n")
    print("saved",args.output,"replays",count,flush=True)


if __name__ == "__main__":
    main()
