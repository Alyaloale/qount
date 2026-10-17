"""Six fixed confirmation/exit arms on the existing consumed-history window."""
import argparse
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from qount.research.binance_etf_leverage import feature_at, load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_liquidity import candidate_clocks, load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, fixed_fill_metrics
from qount.research.binance_macro_signals import contract_confirmations
from qount.research.binance_macro_validation import available_atr, frozen_trade, minute_windows
from qount.research_data.bars import session
from qount.research_data.archives import timestamp


ARMS = {f"{mode}_{hours}h": dict(confirmation=mode, hours=hours)
        for mode, hours in itertools.product(("none", "above20", "aligned20_50"), (168, 72))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=Path("state/research_cache/binance_macro_attack_20261015"))
    p.add_argument("--capacity-cache", type=Path, default=Path("state/research_cache/binance_macro_liquidity_20261015"))
    p.add_argument("--minute-cache", type=Path, default=Path("state/research_cache/binance_macro_minutes_20261015"))
    p.add_argument("--download", action="store_true", help="Fetch missing public minute windows only")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_signal_study")
    features, sources = macro_features(args.cache, "2026-10-15")
    data, contract_sources = load_inputs(args.cache, timestamp("2026-07-30"), timestamp("2026-10-15"), symbols=tuple(CONTRACT_SIGNALS))
    clocks = candidate_clocks(data, features)
    capacity, capacity_sources, _ = load_capacity_contexts(clocks, args.capacity_cache)
    native = {mode: contract_confirmations(data, clocks, mode) for mode in ("above20", "aligned20_50")}
    book, signals = directional_book(data, features, "long", 20/3)
    bundles = {}
    common = dict(strategy="macro_tactical", gross_cap=20, risk_fraction=.20,
                  exchange_leverage=50, liquidation_stop_multiple=3,
                  account_controls=False, funding_policy="debit_stress", sizing_gap_reserve=.03)
    for arm, capital, scenario in itertools.product(ARMS, (10, 100), ("base", "double_cost")):
        spec = ARMS[arm]
        bundle = replay(cost_case(book, scenario), signals, capital=capital, **common,
                        entry_liquidity_caps=capacity, entry_confirmations=native.get(spec["confirmation"]),
                        tactical_max_hold_hours=spec["hours"], fee=.001 if scenario == "double_cost" else .0005,
                        slip=.005 if scenario == "double_cost" else .0025)
        bundle["summary"].update(arm=arm, capital=capital, scenario=scenario)
        bundle["summary"]["pnl_by_symbol"] = {s: sum(t["net_pnl"] for t in bundle["trades"] if t["symbol"] == s)
                                               for s in sorted({t["symbol"] for t in bundle["trades"]})}
        if scenario == "base":
            doubled_pnl = sum(fixed_fill_metrics(t, t, data[t["symbol"]]["funding"], fee=.0005, slip=.0025)
                              ["fixed_path_double_cost_pnl"] for t in bundle["trades"])
            bundle["summary"]["fixed_orders_double_cost_return"] = doubled_pnl/capital
        bundles[arm, capital, scenario] = bundle
    # Exact frozen control reproduction, including all costs and entry paths.
    for capital, scenario in itertools.product((10, 100), ("base", "double_cost")):
        old = json.loads(Path(f"state/research_runs/binance_macro_execution_optimization_20261015_final/volume25_gap3_capital{capital}_{scenario}.json").read_text())
        assert old["trades"] == bundles["none_168h", capital, scenario]["trades"]
        assert old["curve"] == bundles["none_168h", capital, scenario]["curve"]

    # Fixed raw opportunities, detached from shared-book occupancy and friction
    # admission. Real fees/funding/slip are still paid. These are not portfolios
    # or executable recommendations; this isolates signal/exit quality only.
    decision_times = [b.t for b in next(iter(data.values()))["trade"] if session(b.t) is not None and session(b.t)[1] == 600]
    ordinal = {t: i for i, t in enumerate(decision_times)}
    previous, episodes = {}, Counter()
    events = []
    for s, now in sorted(clocks, key=lambda x: (x[1], x[0])):
        first = previous.get(s) != ordinal[now]-1
        if first:
            episodes[s] += 1
        previous[s] = ordinal[now]
        f = feature_at(features[s], now)
        event = dict(symbol=s, time=now, setup=f["tactical_setup"], first_episode=first,
                     episode=f"{s}:{episodes[s]}", state=f["state"], feature_available=f["available"],
                     confirmation={mode: native[mode].get((s, now)) for mode in native}, outcomes={})
        for hours in (168, 72):
            result = replay(book, signals, capital=100, **{**common, "gross_cap": 1},
                            tactical_max_hold_hours=hours, fee=.0005, slip=.0025,
                            forced_entry=dict(symbol=s, time=now, engine="tactical", ignore_friction_gate=True))
            if result["trades"]:
                t = result["trades"][0]
                assert t["entry_time"] == now and t["symbol"] == s
                event["outcomes"][str(hours)] = dict(net_return_on_entry_notional=t["net_pnl"]/t["notional_usdt"],
                    exit_reason=t["exit_reason"], exit_time=t["exit_time"], censored=t["exit_reason"] == "end_of_sample")
            else:
                event["outcomes"][str(hours)] = dict(rejections=result["summary"]["rejections"])
        events.append(event)
    quality = []
    for setup, mode, hours in itertools.product(("all", "breakout", "pullback", "mean_reversion"), ("none", "above20", "aligned20_50"), (168, 72)):
        selected = [e for e in events if e["first_episode"] and (setup == "all" or e["setup"] == setup)
                    and (mode == "none" or (e["confirmation"][mode] or {}).get("eligible") is True)]
        closed = [e["outcomes"][str(hours)]["net_return_on_entry_notional"] for e in selected
                  if "censored" in e["outcomes"][str(hours)] and not e["outcomes"][str(hours)]["censored"]]
        quality.append(dict(setup=setup, confirmation=mode, hours=hours, episodes=len(selected), closed=len(closed),
                            censored=sum(e["outcomes"][str(hours)].get("censored", False) for e in selected),
                            mean_net_return_on_notional=statistics.mean(closed) if closed else None,
                            median_net_return_on_notional=statistics.median(closed) if closed else None,
                            positive=sum(v > 0 for v in closed)))

    longest = {}
    for b in bundles.values():
        for t in b["trades"]:
            key = t["symbol"], t["entry_time"]
            if key not in longest or t["exit_time"] > longest[key]["exit_time"]:
                longest[key] = t
    windows, minute_sources = minute_windows(list(longest.values()), args.minute_cache, timestamp("2026-10-15"), args.download)
    atrs = {s: available_atr(d["trade"]) for s, d in data.items()}
    checked = 0
    for (arm, capital, scenario), b in bundles.items():
        equity = peak = capital
        mdd = 0
        checks = []
        actual_data = cost_case(data, scenario)
        risk_breaches = margin_breaches = 0
        for t in b["trades"]:
            w = windows[t["symbol"], t["entry_time"]]
            result = frozen_trade({**t, "equity_before_entry": equity}, w["trade"], w["mark"],
                                  actual_data[t["symbol"]]["funding"], atrs[t["symbol"]], actual_data[t["symbol"]]["rule"],
                                  fee=.001 if scenario == "double_cost" else .0005,
                                  slip=.005 if scenario == "double_cost" else .0025)
            for row in result.pop("curve"):
                mdd = max(mdd, 1-row["equity"]/peak)
                peak = max(peak, row["equity"])
            result["hourly_pnl_difference"] = result["net_pnl"]-t["net_pnl"]
            result["hourly_exit_changed"] = result["exit_time"] != t["exit_time"] or result["exit_reason"] != t["exit_reason"]
            assert t["exit_time"]-t["entry_time"] <= ARMS[arm]["hours"]*3600
            risk_breaches += result["entry_stress_risk_usdt"] > equity*.20+1e-9
            margin_breaches += result["entry_margin_fraction"] > .8+1e-9
            equity += result["net_pnl"]
            checks.append(result)
            checked += 1
        b["minute_checks"] = checks
        b["summary"].update(minute_close_mdd=mdd, minute_schedule_return=equity/capital-1,
                            minute_pnl_difference=equity-b["summary"]["final_equity"],
                            minute_pnl_reproduced=all(abs(t["hourly_pnl_difference"]) < 1e-8 for t in checks),
                            minute_exit_changes=sum(t["hourly_exit_changed"] for t in checks),
                            minute_risk_budget_breaches=risk_breaches, minute_margin_budget_breaches=margin_breaches)
        assert math.isclose(equity, capital+sum(t["net_pnl"] for t in checks), abs_tol=1e-8)
    # Immutable public sources are checked again after all experiments.
    for record in sources+contract_sources+capacity_sources+minute_sources:
        assert hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest() == record["sha256"]
    args.output.mkdir(parents=True)
    for (arm, capital, scenario), b in bundles.items():
        (args.output/f"{arm}_capital{capital}_{scenario}.json").write_text(json.dumps(b, allow_nan=False)+"\n")
    (args.output/"events.json").write_text(json.dumps(events, indent=2, allow_nan=False)+"\n")
    summary = dict(start="2026-07-30", end_exclusive="2026-10-15", arms=ARMS,
                   runs=[b["summary"] for b in bundles.values()], episode_quality=quality,
                   raw_candidates=len(events), minute_trade_checks=checked, exact_legacy_controls=4,
                   sources=sources+contract_sources, capacity_sources=capacity_sources, minute_sources=minute_sources,
                   code_sources=[dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                       for path in (Path(__file__), Path("src/qount/research/binance_macro_signals.py"),
                                    Path("src/qount/research/binance_macro_attack.py"), Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"),
                                    Path("src/qount/research/binance_macro_validation.py"))],
                   research_only=True, orders_authorized=False, independent_oos=False,
                   assumptions=["Six fixed arms; all use the same repeatedly consumed history. No threshold or ticker selection.",
                       "Native confirmation uses completed hourly contract closes; ETF state and exits remain unchanged.",
                       "72h vs168h changes BOTH time exit and causal full-horizon funding reserve, never realized-duration hindsight.",
                       "Executable accounts retain20% risk,3% stop overshoot reserve, causal10% volume cap,3x liquidation cushion.",
                       "Base:5bp fees and25bp slippage per side. Stress:10bp/50bp and double adverse ordinary funding.",
                       "Fixed opportunity quality ignores occupancy and friction ADMISSION, pays actual costs, uses1x cap/100 USDT and no minute capacity. It is a diagnosis, not executable NAV.",
                       "Episode means exclude ATR-warmup rejects and censored trades; overlapping correlated outcomes are not independent.",
                       "Minute revaluation freezes quantities/order schedules: hourly-vs-minute open discrepancies are retained and actual-equity risk/margin budgets checked. It is not a fully resized minute strategy replay.",
                       "Historical books, exit liquidity, account brackets and native stops remain approximations."])
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    lines = ["# Native contract confirmation and holding horizon", "", "|Arm|Capital|Costs|Hourly return|Minute frozen-order return|Minute MDD|Trades|", "|---|---:|---|---:|---:|---:|---:|"]
    for r in summary["runs"]:
        lines.append(f"|{r['arm']}|{r['capital']}|{r['scenario']}|{r['net_return']:.2%}|{r['minute_schedule_return']:.2%}|{r['minute_close_mdd']:.2%}|{r['trade_count']}|")
    lines += ["", "## Fixed hourly orders at double cost (no resizing or admission changes)", "", "|Arm|Capital|Net return|", "|---|---:|---:|"]
    for r in summary["runs"]:
        if r["scenario"] == "base":
            lines.append(f"|{r['arm']}|{r['capital']}|{r['fixed_orders_double_cost_return']:.2%}|")
    lines += ["", "## Fixed first-episode signal diagnosis (not executable NAV)", "", "|Setup|Confirmation|Hours|Closed|Censored|Mean net/notional|Positive|", "|---|---|---:|---:|---:|---:|---:|"]
    for r in quality:
        mean = f"{r['mean_net_return_on_notional']:.2%}" if r["mean_net_return_on_notional"] is not None else "n/a"
        lines.append(f"|{r['setup']}|{r['confirmation']}|{r['hours']}|{r['closed']}|{r['censored']}|{mean}|{r['positive']}|")
    lines += ["", "## Assumptions", ""]+["- "+s for s in summary["assumptions"]]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output), accounts=len(bundles), raw_candidates=len(events), minute_trade_checks=checked)))


if __name__ == "__main__":
    main()
