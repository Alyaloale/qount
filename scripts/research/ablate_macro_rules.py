"""Fixed rule ablations on retained ETFs and native contracts; offline only."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import statistics
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np

from continue_macro_fixed_candidates import append_inputs
from study_macro_admission_and_simplicity import headline, verify
from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, macro_features
from qount.research.binance_macro_history import adjusted_bars
from qount.research.binance_macro_opportunities import cost_case
from qount.research.macro_depth_execution import DepthExitStress
from qount.research.macro_mechanism_value import daily_replay, mechanism_rows
from qount.research_data.regime import compute_ema
from qount.strategies.macro_episodes import episode_confirmations
from qount.strategies.macro_gates import mean_reversion_gap_confirmations
from qount.strategies.perpetual import size as original_size


RUNS = Path("state/research_runs")
LONG_SOURCE = RUNS / "macro_mechanism_value_20261026_reviewed/comparison.json"
NATIVE_SOURCE = RUNS / "macro_fixed_candidates_20261026_final/comparison.json"
LONG_PROFILES = (
    "control", "no_price_ema200", "no_ema50_200", "no_ret63", "no_own_structure",
    "no_spy_entry", "no_spy_hold", "no_spy_both", "no_trend_state", "no_mr_state",
    "no_all_state", "no_er", "no_alignment", "no_mr_green", "no_pullback_green",
    "no_mr_lower_touch", "no_mr_reclaim", "no_breakout", "no_pullback", "no_mr",
    "mr_only", "no_rank_momentum", "momentum_rank", "constant_rank",
    "no_trend_regime_exit", "no_mr_regime_exit", "no_all_regime_exit",
    "no_trend_state_exit", "trend21", "mr7", "no_stop_or_trailing",
    "no_structure_or_state",
)
NATIVE_PROFILES = (
    "control", "no_chase", "no_gap", "no_chase_or_gap", "no_friction",
    "no_breakout", "no_pullback", "no_mr", "mr_only", "momentum_rank",
    "constant_rank", "no_rank_momentum", "no_trend_state_exit", "no_spy_hold",
    "no_trend_regime_exit", "no_mr_regime_exit", "no_all_regime_exit",
    "no_trailing", "trend21", "mr7", "upfront21_funding", "risk12_5", "risk50",
    "gross1", "gross2", "no_vol_cap", "same_gross_all", "stop1atr", "stop3atr",
    "no_gap_reserve", "funding_debit_peak", "no_minute_capacity",
)


def long_context():
    saved = json.loads(LONG_SOURCE.read_text())
    cache = Path("state/research_cache/binance_macro_etf_history_20261015")
    features, _ = macro_features(cache, "2026-01-01", start_date="2016-01-01")
    book = {s: adjusted_bars(json.loads((cache / f"yahoo-{ticker}-20160101-2026-01-01.json").read_text()))
            for s, ticker in CONTRACT_SIGNALS.items()}
    original = {s: mechanism_rows(book[s], features[s]) for s in book}
    primitives = {}
    for s, bars in book.items():
        closes = [b.c for b in bars]
        ema20, ema50, ema200 = [compute_ema(closes, n) for n in (20, 50, 200)]
        values = {}
        for i in range(200, len(bars)):
            b = bars[i]
            lower = statistics.mean(closes[i-19:i+1]) - 2 * statistics.pstdev(closes[i-19:i+1])
            values[b.t] = dict(price200=b.c > ema200[i], ma50_200=ema50[i] > ema200[i],
                ret63=b.c / closes[i-63] - 1, aligned=b.c > ema20[i] > ema50[i],
                green=b.c > b.o, breakout=b.c > max(x.h for x in bars[i-20:i]),
                pullback_touch=b.l <= 1.02 * ema20[i], above20=b.c > ema20[i],
                lower_touch=b.l < lower, reclaim=b.c > lower)
        primitives[s] = values
    return saved, book, original, primitives


def long_rows(original, primitives, profile):
    own = {}
    for s, rows in primitives.items():
        own[s] = {t: ((p["price200"] or profile == "no_price_ema200")
                      and (p["ma50_200"] or profile == "no_ema50_200")
                      and (p["ret63"] > 0 or profile == "no_ret63"))
                  or profile in ("no_own_structure", "no_structure_or_state")
                  for t, p in rows.items()}
    result = {}
    for s, rows in original.items():
        selected = {}
        for t, f in rows.items():
            p = primitives[s][t]
            stock = s not in ("XAUUSDT", "COPPERUSDT", "CLUSDT")
            system = not stock or own["SPYUSDT"][t]
            no_state = profile in ("no_all_state", "no_structure_or_state")
            trend_state = f["state"] in ("ACCUMULATION", "TREND_UP") or no_state or profile == "no_trend_state"
            pullback_state = f["state"] == "TREND_UP" or no_state or profile == "no_trend_state"
            er = f["er20"] >= .28 or profile == "no_er"
            aligned = p["aligned"] or profile == "no_alignment"
            breakout = p["breakout"] and profile != "no_breakout"
            pullback = (pullback_state and p["pullback_touch"] and p["above20"]
                        and (p["green"] or profile == "no_pullback_green") and profile != "no_pullback")
            trend = trend_state and er and aligned and (breakout or pullback)
            mr = ((f["state"] == "CHOP" or no_state or profile == "no_mr_state")
                  and (p["lower_touch"] or profile == "no_mr_lower_touch")
                  and (p["reclaim"] or profile == "no_mr_reclaim")
                  and (p["green"] or profile == "no_mr_green"))
            if profile == "mr_only":
                trend = False
            if profile == "no_mr":
                mr = False
            setup = "breakout" if trend and breakout else "pullback" if trend else "mean_reversion" if mr else None
            entry = own[s][t] and (system or profile in ("no_spy_entry", "no_spy_both")) and (trend or mr)
            hold_structure = own[s][t] and (system or profile in ("no_spy_hold", "no_spy_both"))
            hold_tactical = hold_structure and f["state"] != "EXHAUSTION"
            if profile in ("no_trend_regime_exit", "no_all_regime_exit"):
                hold_tactical = True
            if profile in ("no_mr_regime_exit", "no_all_regime_exit"):
                hold_structure = True
            if profile == "no_trend_state_exit":
                hold_tactical = hold_structure
            rank = (2.5 + 3 * max(f["er20"] - .28, 0) if trend else 2.2 if mr else 0) + max(0, p["ret63"] * 4)
            if profile == "no_rank_momentum":
                rank -= max(0, p["ret63"] * 4)
            elif profile == "momentum_rank":
                rank = p["ret63"]
            elif profile == "constant_rank":
                rank = 0.
            row = dict(f, structural=own[s][t], entry_tactical=bool(entry), tactical_setup=setup,
                       hold_structural=bool(hold_structure), hold_tactical=bool(hold_tactical), rank_tactical=rank)
            if profile == "control":
                for key in ("structural", "entry_tactical", "tactical_setup", "hold_structural", "hold_tactical", "rank_tactical"):
                    assert row[key] == f[key], (s, t, key)
            selected[t] = row
        result[s] = selected
    return result


def long_run(book, rows, profile, fee, slip):
    """Change horizons only inside the existing pure eligibility call."""
    from qount.research import macro_mechanism_value as engine
    ordinary = engine.eligibility

    def horizon(f, method):
        allowed, days, setup = ordinary(f, method)
        if profile == "trend21" and setup in ("breakout", "pullback"):
            days = 21
        if profile == "mr7" and setup == "mean_reversion":
            days = 7
        return allowed, days, setup

    with patch.object(engine, "eligibility", horizon):
        return daily_replay(book, rows, "original_all", fee=fee, slip=slip,
                            stops=profile != "no_stop_or_trailing")


def verify_long_treatment(original, rows, profile):
    relaxing = {"no_price_ema200", "no_ema50_200", "no_ret63", "no_own_structure",
                "no_spy_entry", "no_spy_both", "no_trend_state", "no_mr_state",
                "no_all_state", "no_er", "no_alignment", "no_mr_green",
                "no_pullback_green", "no_mr_lower_touch", "no_mr_reclaim", "no_structure_or_state"}
    restricted = {"no_breakout", "no_pullback", "no_mr", "mr_only"}
    rankings = {"no_rank_momentum", "momentum_rank", "constant_rank"}
    unchanged_signals = rankings | {"no_spy_hold", "no_trend_regime_exit", "no_mr_regime_exit",
        "no_all_regime_exit", "no_trend_state_exit", "trend21", "mr7", "no_stop_or_trailing"}
    for s, source in original.items():
        for t, before in source.items():
            after = rows[s][t]
            assert after["available"] == before["available"] == t
            if profile in relaxing:
                assert not before["entry_tactical"] or after["entry_tactical"]
            if profile in restricted:
                assert not after["entry_tactical"] or before["entry_tactical"]
            if profile in unchanged_signals:
                assert all(before[k] == after[k] for k in ("entry_tactical", "tactical_setup"))
            if profile in rankings:
                assert all(before[k] == after[k] for k in ("hold_structural", "hold_tactical"))


def entry_path_difference(control, candidate):
    key = lambda t: (t["symbol"], t["entry_time"], t["tactical_setup"])
    a, b = ({key(t): t for t in r["trades"]} for r in (control, candidate))
    exit_delta = sum((b[k]["net_pnl"] / b[k]["quantity"] - a[k]["net_pnl"] / a[k]["quantity"])
                     * a[k]["quantity"] for k in a.keys() & b.keys())
    quantity_delta = sum(b[k]["net_pnl"] - a[k]["net_pnl"] for k in a.keys() & b.keys()) - exit_delta
    removed = sum(a[k]["net_pnl"] for k in a.keys() - b.keys())
    added = sum(b[k]["net_pnl"] for k in b.keys() - a.keys())
    total = candidate["summary"]["final_equity"] - control["summary"]["final_equity"]
    assert math.isclose(exit_delta + quantity_delta + added - removed, total, abs_tol=1e-8)
    return dict(common_entries=len(a.keys() & b.keys()), control_only=len(a.keys() - b.keys()),
                candidate_only=len(b.keys() - a.keys()), same_quantity_exit_delta=exit_delta,
                quantity_delta=quantity_delta, added_entry_pnl=added, removed_entry_pnl=removed,
                total_equity_delta=total)


def native_run(book, features, gates, anchors, gaps, capacities, parameters, profile, scenario):
    fs = copy.deepcopy(features)
    p = copy.deepcopy(parameters)
    gs, caps = gates, capacities
    for rows in fs.values():
        for f in rows:
            setup = f["tactical_setup"]
            if profile == "mr_only" and setup != "mean_reversion" or profile == "no_mr" and setup == "mean_reversion" or profile == "no_breakout" and setup == "breakout" or profile == "no_pullback" and setup == "pullback":
                f["entry_tactical"] = False
            if profile == "momentum_rank":
                f["rank_tactical"] = f["rank_core"]
            elif profile == "constant_rank":
                f["rank_tactical"] = 0.
            elif profile == "no_rank_momentum":
                f["rank_tactical"] -= max(0, f["rank_core"] * 4)
            if profile in ("no_trend_regime_exit", "no_all_regime_exit"):
                f["hold_tactical"] = True
            if profile in ("no_mr_regime_exit", "no_all_regime_exit"):
                f["hold_structural"] = True
            if profile == "no_trend_state_exit":
                f["hold_tactical"] = f["hold_structural"]
            if profile == "no_spy_hold":
                f["hold_structural"] = f["structural"]
                f["hold_tactical"] = f["structural"] and f["state"] != "EXHAUSTION"
            if profile == "no_vol_cap":
                f["gross_target"] = 20 / 3 if setup == "mean_reversion" else 20.
            elif profile == "same_gross_all":
                f["gross_target"] = 20.
    if profile in ("no_chase", "no_gap", "no_chase_or_gap"):
        gs = {k: dict(g, eligible=gaps[k]["eligible"] if profile == "no_chase" else
                    anchors[k]["eligible"] if profile == "no_gap" else True,
                    reason="ablation_gate") for k, g in gates.items()}
        if profile == "no_chase":
            assert all(g["eligible"] == gaps[k]["eligible"] for k, g in gs.items())
        if profile == "no_gap":
            assert all(g["eligible"] == anchors[k]["eligible"] for k, g in gs.items())
        if profile == "no_chase_or_gap":
            assert all(g["eligible"] for g in gs.values())
    if profile == "trend21":
        for setup in ("breakout", "pullback"):
            p["tactical_setup_policies"][setup]["max_hold_hours"] = 504
    if profile == "mr7":
        p["tactical_setup_policies"]["mean_reversion"]["max_hold_hours"] = 168
    if profile == "upfront21_funding":
        p.update(funding_lease_hours=None, funding_lease_budget="cost")
    if profile in ("risk12_5", "risk50"):
        p["risk_fraction"] = .125 if profile == "risk12_5" else .5
    if profile in ("gross1", "gross2"):
        p["gross_cap"] = 1 if profile == "gross1" else 2
    if profile == "no_gap_reserve":
        p["sizing_gap_reserve"] = 0.
    if profile == "funding_debit_peak":
        p["funding_policy"] = "debit_peak"
    if profile == "no_minute_capacity":
        caps = None  # Still retain the prior-hour 1% volume cap; optimistic fill diagnostic.
    data = cost_case(book, scenario)
    p.update(fee=.001 if scenario == "double_cost" else .0005,
             slip=.005 if scenario == "double_cost" else .0025)

    def modified_size(config, *args, **kwargs):
        config = copy.deepcopy(config)
        if profile == "no_friction":
            config["cost_model"]["ordinary_friction_limit_fraction_of_stop"] = math.inf
        if profile in ("stop1atr", "stop3atr"):
            config["signal"]["initial_stop_atr"] = 1 if profile == "stop1atr" else 3
        return original_size(config, *args, **kwargs)

    with ExitStack() as stack:
        if profile in ("no_friction", "stop1atr", "stop3atr"):
            stack.enter_context(patch("qount.research.binance_etf_leverage.size", modified_size))
        if profile == "no_trailing":
            stack.enter_context(patch("qount.strategies.macro_1atr.trailing_update", lambda position, *args: (copy.deepcopy(position), None)))
        result = replay(data, fs, entry_confirmations=gs, entry_liquidity_caps=caps,
                        exit_execution_model=DepthExitStress({}, use_depth=False, all_extra_slip=.005)
                        if scenario == "exit50bp" else None, **p)
    verify(result, data, p)
    return result


def native_activity(book, features, gates, capacities, parameters, expected):
    """Count actual baseline rule activations without changing any decision."""
    from qount.strategies.macro_1atr import entry_candidates, trailing_update
    counter = dict(completed_hour_updates=0, reached_2r=0, stop_tightened=0)
    sizes = []

    def trailing(position, close, volatility, tick):
        counter["completed_hour_updates"] += 1
        counter["reached_2r"] += close - position["entry_price"] >= 2 * position["structural_r"]
        result, reason = trailing_update(position, close, volatility, tick)
        counter["stop_tightened"] += result["stop"] > position["stop"]
        return result, reason

    def sizing(config, rule, reference, price, volatility, equity, budget, reserve, fee, slip, liquidity, **kwargs):
        order, reason = original_size(config, rule, reference, price, volatility, equity,
                                      budget, reserve, fee, slip, liquidity, **kwargs)
        if order is not None:
            limits = dict(risk=budget * order["quantity"] / order["stress_risk_usdt"],
                gross=config["sizing"]["notional_caps"]["effective_gross"] * equity / price,
                margin=.8 * equity * order["leverage"] / price,
                cash=equity / (price * (1 / order["leverage"] + fee + reserve)), liquidity=liquidity)
            sizes.append(dict(symbol=rule["symbol"], price=price, equity=equity,
                              quantity=order["quantity"], limits=limits, binding=min(limits, key=limits.get)))
        return order, reason

    with patch("qount.strategies.macro_1atr.trailing_update", trailing), patch("qount.research.binance_etf_leverage.size", sizing):
        result = replay(book, features, entry_confirmations=gates, entry_liquidity_caps=capacities,
                        trace=True, **parameters)
    assert result["curve"] == expected["curve"] and result["trades"] == expected["trades"]
    admitted, selected = [], []
    for trade in result["trades"]:
        candidates, _ = entry_candidates(book, features, capacities, trade["entry_time"], trade["equity_before_entry"])
        assert candidates and candidates[0]["symbol"] == trade["symbol"]
        admitted.append(dict(time=trade["entry_time"], symbol=trade["symbol"],
                             count=len(candidates), symbols=[c["symbol"] for c in candidates]))
        matching = [s for s in sizes if s["symbol"] == trade["symbol"] and s["price"] == trade["entry_price"]
                    and s["equity"] == trade["equity_before_entry"] and s["quantity"] == trade["quantity"]]
        assert len(matching) == 1
        selected.append(dict(time=trade["entry_time"], **matching[0]))
    return dict(trailing=counter, selected_entry_candidate_counts=admitted, binding_sizing=selected,
                exact_instrumented_control=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a new output; retain previous results")
    saved, long_book, original, primitives = long_context()
    long_results, curves, long_returns, controls = [], {}, {}, {}
    for scenario, fee, slip in (("base", .0005, .0025), ("double_cost", .001, .005)):
        for profile in LONG_PROFILES:
            rows = long_rows(original, primitives, profile)
            verify_long_treatment(original, rows, profile)
            result = long_run(long_book, rows, profile, fee, slip)
            if profile == "control":
                controls[scenario] = result
                if scenario == "base":
                    previous = next(r for r in saved["portfolios"] if r["profile"] == "original_all" and r["vol_target"] is None)
                    assert result["curve"] == previous["curve"] and result["trades"] == previous["trades"]
            control = controls[scenario]
            assert [p["t"] for p in result["curve"]] == [p["t"] for p in control["curve"]]
            nav = np.array([p["nav"] for p in result["curve"]])
            control_nav = np.array([p["nav"] for p in control["curve"]])
            log_delta = np.diff(np.log(nav)) - np.diff(np.log(control_nav))
            key = scenario + "__" + profile
            curves["long__" + key] = nav
            long_returns[key] = log_delta
            changed = {field: sum(row[field] != original[s][t][field] for s, rs in rows.items() for t, row in rs.items())
                       for field in ("entry_tactical", "tactical_setup", "hold_structural", "hold_tactical", "rank_tactical")}
            long_results.append(dict(profile=profile, scenario=scenario, summary=result["summary"], changed_fields=changed,
                annual_log_delta=float(log_delta.mean() * 252),
                positive_delta_years=sum(result["summary"]["years"][y] > control["summary"]["years"][y] for y in result["summary"]["years"])))
            print("long", scenario, profile, result["summary"]["cagr_pct"], result["summary"]["max_drawdown_pct"], flush=True)
    # Identical moving-block draws for all comparisons; intervals are not search-adjusted.
    n = len(next(iter(long_returns.values())))
    rng = np.random.default_rng(20261102)
    draws = np.zeros((n, 2000))
    for i in range(draws.shape[1]):
        starts = rng.integers(0, n, size=(n + 62) // 63)
        indices = ((starts[:, None] + np.arange(63)) % n).ravel()[:n]
        draws[:, i] = np.bincount(indices, minlength=n) / n * 252
    for r in long_results:
        values = long_returns[r["scenario"] + "__" + r["profile"]] @ draws
        r["annual_log_delta_interval95"] = np.quantile(values, [.025, .975]).tolist()

    native_saved = json.loads(NATIVE_SOURCE.read_text())
    (book, features, gates, capacities), _, _ = append_inputs("2026-10-26", False)
    anchors = episode_confirmations(book, features, "no_chase")
    gaps = mean_reversion_gap_confirmations(book, features, list(anchors))
    assert set(gates) == set(anchors) == set(gaps)
    assert all(g["eligible"] == (anchors[k]["eligible"] and gaps[k]["eligible"]) for k, g in gates.items())
    native_results, native_controls = [], {}
    for scenario in ("base", "double_cost", "exit50bp"):
        for profile in NATIVE_PROFILES:
            result = native_run(book, features, gates, anchors, gaps, capacities,
                                native_saved["parameters"], profile, scenario)
            if profile == "control":
                previous = next(r for r in native_saved["portfolios"] if r["profile"] == "control" and r["scenario"] == scenario
                                and r["capital"] == native_saved["parameters"]["capital"])
                assert result["curve"] == previous["curve"] and result["trades"] == previous["trades"]
                native_controls[scenario] = result
            h = headline(result)
            curves["native__" + scenario + "__" + profile] = np.array([p["equity"] for p in result["curve"]])
            native_results.append(dict(profile=profile, scenario=scenario, capital=native_saved["parameters"]["capital"],
                headline=h, trades=result["trades"],
                exact_control_curve=result["curve"] == native_controls[scenario]["curve"],
                path_attribution=entry_path_difference(native_controls[scenario], result)))
            print("native", scenario, profile, h["net_return"], h["max_drawdown"], h["trade_count"], flush=True)
    activity = native_activity(book, features, gates, capacities, native_saved["parameters"], native_controls["base"])
    out = dict(research_only=True, orders_authorized=False, independent_oos=False,
        long_sample=["2017-01-01", "2026-01-01"], native_sample=["2026-04-07", "2026-10-26"],
        long_source=str(LONG_SOURCE), native_source=str(NATIVE_SOURCE), native_parameters=native_saved["parameters"],
        long_results=long_results, native_results=native_results,
        long_profiles=list(LONG_PROFILES), native_profiles=list(NATIVE_PROFILES),
        long_control_exact=True, native_control_exact_scenarios=list(native_controls), native_activity=activity,
        methodology="Fixed leave-one-rule-out and named interactions, not parameter optimization. "
                     "ETF next-open 1x account and native hourly account evaluated separately. "
                     "2000 paired circular 63-session block draws for long log-return differences.",
        limitations=[
            "All history consumed; no independent holdout. Bootstrap intervals not corrected for the many tested hypotheses.",
            "Removing a gate changes other rule effectiveness and future occupancy; individual deltas cannot be summed.",
            "Long ETF proxies omit native funding, gap/no-chase, capacity, exchange filters and liquidation; adjusted snapshots not certified historical PIT.",
            "Native opening-signal expansions omitted where new minute capacity is unavailable; short window only seven baseline trades.",
            "Native no_minute_capacity is an optimistic fill-model diagnostic, retaining only prior-hour volume cap, never an executable candidate.",
            "Cost removal disables the admission ratio only; actual fees/slippage/funding, sizing budget, minimum orders and liquidation cushion remain.",
            "no_stop_or_trailing on ETFs removes both protections together, not an isolated initial-stop effect.",
            "Horizon changes alter ex-ante funding reserves and possible renewals; these are total policy effects, not pure exit-price effects.",
            "Time correctness, actual cost accounting, native protection reliability and production authority are constraints, not alpha filters to optimize away.",
        ])
    args.output.mkdir(parents=True)
    (args.output / "comparison.json").write_text(json.dumps(out, ensure_ascii=False, allow_nan=False) + "\n")
    np.savez_compressed(args.output / "curves.npz", **curves)
    print("saved", args.output, flush=True)


if __name__ == "__main__":
    main()
