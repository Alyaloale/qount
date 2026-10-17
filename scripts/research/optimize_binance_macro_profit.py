"""Profit-oriented factorial: risk, liquidation cushion, admission and direction.

Fixed12 parameter cells x2 directions x2 scales x2 costs. No ticker/threshold
search; actual costs, causal capacity and shared capital remain unchanged.
"""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

from qount.research.binance_etf_leverage import load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_liquidity import candidate_clocks, load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, fixed_fill_metrics
from qount.research.binance_macro_signals import exit_features
from qount.research.binance_macro_validation import available_atr, frozen_trade, minute_windows
from qount.research_data.archives import timestamp


PROFILES = {
    f"risk{round(risk*100)}_gate{round(gate*100)}_cushion{cushion:g}":
    dict(risk_fraction=risk, friction_limit_fraction_of_stop=gate, liquidation_stop_multiple=cushion)
    for risk, gate, cushion in itertools.product((.20, .50, .80), (.20, 1.0), (3.0, 1.25))
}
EXIT_PROFILES = {name: dict(risk_fraction=.50, friction_limit_fraction_of_stop=.20,
                          liquidation_stop_multiple=1.25, tactical_max_hold_hours=hours, hold_policy=policy)
                 for name, hours, policy in (
                     ("attack7", 168, "hold_tactical"), ("price7", 168, "hold_price_trend"),
                     ("price21", 504, "hold_price_trend"), ("structural21", 504, "hold_structural"))}


def physical(symbol):
    return symbol.removesuffix(":SHORT")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--study", choices=("risk", "exits"), default="risk")
    p.add_argument("--download", action="store_true", help="Missing public capacity/minute data only")
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_profit_study")
    cache = Path("state/research_cache/binance_macro_attack_20261015")
    features, sources = macro_features(cache, "2026-10-15")
    data, contract_sources = load_inputs(cache, timestamp("2026-07-30"), timestamp("2026-10-15"), symbols=tuple(CONTRACT_SIGNALS))
    profiles = PROFILES if args.study == "risk" else EXIT_PROFILES
    books = {direction: directional_book(data, features, direction, 20/3, "tactical")
             for direction in (("long", "long_short") if args.study == "risk" else ("long",))}
    raw_clocks = candidate_clocks(*books["long_short" if args.study == "risk" else "long"])
    physical_clocks = sorted({(physical(s), t) for s, t in raw_clocks})
    contexts, capacity_sources, _ = load_capacity_contexts(physical_clocks,
                      Path("state/research_cache/binance_macro_liquidity_20261015"), args.download)
    capacities = {(s, t): contexts[physical(s), t] for s, t in raw_clocks if (physical(s), t) in contexts}
    bundles = {}
    cost_books = {}
    for direction, (book, signals) in books.items():
        sides = {s: rows[0].get("side", 1) for s, rows in signals.items()}
        for scenario in ("base", "double_cost"):
            cost_books[direction, scenario] = cost_case(book, scenario, sides)
    for profile, direction, capital, scenario in itertools.product(profiles, books, (10, 100), ("base", "double_cost")):
        book, signals = books[direction]
        spec = {k: v for k, v in profiles[profile].items() if k != "hold_policy"}
        if "hold_policy" in profiles[profile]:
            signals = exit_features(signals, profiles[profile]["hold_policy"])
        b = replay(cost_books[direction, scenario], signals, capital=capital, strategy="macro_tactical",
                   gross_cap=20, exchange_leverage=50, account_controls=False, funding_policy="debit_stress",
                   sizing_gap_reserve=.03, entry_liquidity_caps=capacities,
                   fee=.001 if scenario == "double_cost" else .0005,
                   slip=.005 if scenario == "double_cost" else .0025, **spec)
        r = b["summary"]
        r.update(profile=profile, direction=direction, capital=capital, scenario=scenario,
                 short_trades=sum(t.get("side", 1) == -1 for t in b["trades"]),
                 long_pnl=sum(t["net_pnl"] for t in b["trades"] if t.get("side", 1) == 1),
                 short_pnl=sum(t["net_pnl"] for t in b["trades"] if t.get("side", 1) == -1),
                 maximum_entry_gross=max((t["notional_usdt"]/t["equity_before_entry"] for t in b["trades"]), default=0),
                 maximum_entry_leverage=max((t["leverage"] for t in b["trades"]), default=0))
        if scenario == "base":
            r["fixed_orders_double_cost_return"] = sum(fixed_fill_metrics(t, t, book[t["symbol"]]["funding"], fee=.0005, slip=.0025)
                                ["fixed_path_double_cost_pnl"] for t in b["trades"])/capital
        bundles[profile, direction, capital, scenario] = b
    for capital, scenario in itertools.product((10, 100), ("base", "double_cost")):
        if args.study == "risk":
            path = Path(f"state/research_runs/binance_macro_execution_optimization_20261015_final/volume25_gap3_capital{capital}_{scenario}.json")
            control = "risk20_gate20_cushion3"
        else:
            path = Path(f"state/research_runs/binance_macro_profit_optimization_20261015/risk50_gate20_cushion1.25_long_capital{capital}_{scenario}.json")
            control = "attack7"
        old = json.loads(path.read_text())
        b = bundles[control, "long", capital, scenario]
        assert b["trades"] == old["trades"] and b["curve"] == old["curve"]
    print(json.dumps(dict(phase="hourly_complete", accounts=len(bundles), raw_long_short_candidates=len(raw_clocks))), flush=True)
    longest = {}
    for b in bundles.values():
        for t in b["trades"]:
            actual = {**t, "symbol": physical(t["symbol"])}
            key = actual["symbol"], actual["entry_time"]
            if key not in longest or t["exit_time"] > longest[key]["exit_time"]:
                longest[key] = actual
    windows, minute_sources = minute_windows(list(longest.values()), Path("state/research_cache/binance_macro_minutes_20261015"), timestamp("2026-10-15"), args.download)
    atrs = {s: available_atr(d["trade"]) for s, d in data.items()}
    print(json.dumps(dict(phase="minute_data_ready", windows=len(windows))), flush=True)
    checked = 0
    shocks = []
    for (profile, direction, capital, scenario), b in bundles.items():
        equity = peak = capital
        mdd = 0
        checks = []
        cb = cost_books[direction, scenario]
        risk = profiles[profile]["risk_fraction"]
        for t in b["trades"]:
            s = physical(t["symbol"])
            w = windows[s, t["entry_time"]]
            result = frozen_trade({**t, "equity_before_entry": equity}, w["trade"], w["mark"], cb[t["symbol"]]["funding"], atrs[s], data[s]["rule"],
                                  fee=.001 if scenario == "double_cost" else .0005, slip=.005 if scenario == "double_cost" else .0025)
            if result["status"] != "executed":
                raise AssertionError((profile, direction, capital, scenario, "minute_order_unaffordable", result))
            for row in result.pop("curve"):
                mdd = max(mdd, 1-row["equity"]/peak)
                peak = max(peak, row["equity"])
            result.update(symbol=t["symbol"], hourly_pnl_difference=result["net_pnl"]-t["net_pnl"],
                          hourly_exit_changed=result["exit_time"] != t["exit_time"] or result["exit_reason"] != t["exit_reason"],
                          actual_equity_budget_breach=result["entry_stress_risk_usdt"] > risk*equity+1e-9,
                          actual_equity_margin_breach=result["entry_margin_fraction"] > .8+1e-9)
            equity += result["net_pnl"]
            checks.append(result)
            checked += 1
        assert math.isclose(equity, capital+sum(t["net_pnl"] for t in checks), abs_tol=1e-8)
        b["minute_checks"] = checks
        b["summary"].update(minute_schedule_return=equity/capital-1, minute_close_mdd=mdd,
            minute_exit_changes=sum(t["hourly_exit_changed"] for t in checks),
            minute_risk_budget_breaches=sum(t["actual_equity_budget_breach"] for t in checks),
            minute_margin_budget_breaches=sum(t["actual_equity_margin_breach"] for t in checks),
            minute_pnl_difference=equity-b["summary"]["final_equity"])
        # Independent jump scenarios on each original order; no deposit/reset
        # inside a strategy account and no occurrence-probability inference.
        if scenario == "base":
            for gap in (.03, .10):
                rows = []
                for t in b["trades"]:
                    s = physical(t["symbol"])
                    w = windows[s, t["entry_time"]]
                    result = frozen_trade(t, w["trade"], w["mark"], cb[t["symbol"]]["funding"], atrs[s], data[s]["rule"], slip=.0025, stop_overshoot=gap)
                    result.pop("curve")
                    rows.append(result)
                shocks.append(dict(profile=profile, direction=direction, capital=capital, stop_overshoot=gap,
                                   maximum_loss_fraction=max((t["risk_fraction_loss"] for t in rows), default=0),
                                   liquidations=sum(t["exit_reason"] == "liquidation_proxy" for t in rows), trades=rows))
    for source in sources+contract_sources+capacity_sources+minute_sources:
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    args.output.mkdir(parents=True)
    for (profile, direction, capital, scenario), b in bundles.items():
        (args.output/f"{profile}_{direction}_capital{capital}_{scenario}.json").write_text(json.dumps(b, allow_nan=False)+"\n")
    summary = dict(start="2026-07-30", end_exclusive="2026-10-15", study=args.study, profiles=profiles,
                   runs=[b["summary"] for b in bundles.values()], synthetic_shocks=shocks, minute_trade_checks=checked,
                   raw_long_short_candidates=len(raw_clocks), raw_short_candidates=sum(s.endswith(":SHORT") for s, _ in raw_clocks),
                   exact_legacy_controls=4, sources=sources+contract_sources, capacity_sources=capacity_sources, minute_sources=minute_sources,
                   code_sources=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in
                       (Path(__file__), Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"), Path("src/qount/research/binance_macro_attack.py"),
                        Path("src/qount/research/binance_macro_validation.py"), Path("src/qount/research/engine/perpetual.py"),
                        Path("src/qount/research/binance_macro_signals.py"))],
                   research_only=True, orders_authorized=False, independent_oos=False,
                   assumptions=["Same repeatedly consumed history, no ticker removal or payoff-selected threshold sweep. Exit-study hypotheses follow risk-study diagnosis and are not independent confirmation.",
                       ("Fixed full factorial:20/50/80% stress budgets,3/1.25x cushions,20/100% friction admission,long/long_short." if args.study == "risk" else
                        "Four fixed exit controls: original7d; structural+price>EMA20 with7/21d; structural-only21d. All50% stress risk/1.25x cushion/20% friction admission. Holding rules preserve equity systemic gates and entry signals. Funding reserve uses full chosen horizon."),
                       "Admission threshold is changed, not actual costs: base5bp fees/25bp slip, stress10bp/50bp and double adverse ordinary funding per side.",
                       "20x requested gross/50x requested setting are simulation caps, not actual account capability.80% margin cap/3% gap reserve remain.",
                       "10% past5/15-minute volume caps with1-minute publication buffer apply equally to both directions. Volume is not historical depth.",
                       "All directions share ONE non-overlapping book; no fresh deposits, account resets, forced orders or automatic production changes.",
                       "Minute revaluation freezes hourly orders; timing/PnL/budget discrepancies are reported. It is not a minute strategy with resized later orders.",
                       "Synthetic3/10% jumps beyond stop are independent per-order loss scenarios; they do not estimate liquidation probability.",
                       "Current filters, maintenance/isolated-funding/liquidation fees and exit liquidity remain assumptions, not exchange certification."])
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    lines = ["# Profit-oriented aggressive risk and admission experiment", "", "|Profile|Direction|Capital|Costs|Hourly return|Minute fixed-order return|Minute MDD|Trades|Shorts|Max entry gross|Max leverage|", "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in summary["runs"]:
        lines.append(f"|{r['profile']}|{r['direction']}|{r['capital']}|{r['scenario']}|{r['net_return']:.2%}|{r['minute_schedule_return']:.2%}|{r['minute_close_mdd']:.2%}|{r['trade_count']}|{r['short_trades']}|{r['maximum_entry_gross']:.2f}|{r['maximum_entry_leverage']}|")
    lines += ["", "## Fixed original orders at double cost (no admission/resizing)", "", "|Profile|Direction|Capital|Net return|", "|---|---|---:|---:|"]
    for r in summary["runs"]:
        if r["scenario"] == "base":
            lines.append(f"|{r['profile']}|{r['direction']}|{r['capital']}|{r['fixed_orders_double_cost_return']:.2%}|")
    lines += ["", "## Synthetic jumps beyond stop", "", "|Profile|Direction|Capital|Overshoot|Max loss|Liquidations|", "|---|---|---:|---:|---:|---:|"]
    for r in shocks:
        lines.append(f"|{r['profile']}|{r['direction']}|{r['capital']}|{r['stop_overshoot']:.0%}|{r['maximum_loss_fraction']:.2%}|{r['liquidations']}|")
    lines += ["", "## Assumptions", ""]+["- "+a for a in summary["assumptions"]]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output), accounts=len(bundles), minute_trade_checks=checked)), flush=True)


if __name__ == "__main__":
    main()
