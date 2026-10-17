"""Three missed-entry controls with unchanged rolling exits/costs/capacity."""
import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

from qount.research.binance_etf_leverage import load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_entry_episodes import episode_confirmations
from qount.research.binance_macro_liquidity import candidate_clocks, load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, fixed_fill_metrics
from qount.research.binance_macro_setup import setup_policies
from qount.research.binance_macro_validation import available_atr, frozen_trade, minute_windows
from qount.research_data.archives import timestamp


ARMS = ("baseline", "first_only", "no_chase")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--start", choices=("2026-06-11", "2026-04-07"), default="2026-06-11")
    p.add_argument("--download", action="store_true", help="Missing public hourly/funding/capacity/minute inputs")
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_entry_discipline")
    cache = Path("state/research_cache/binance_macro_attack_20261015")
    features, sources = macro_features(cache, "2026-10-15")
    symbols = tuple(CONTRACT_SIGNALS)
    later, inputs = load_inputs(cache, timestamp("2026-07-30"), timestamp("2026-10-15"), symbols=symbols)
    sources += inputs
    early, inputs = load_inputs(Path("state/research_cache/binance_macro_earlier_20260611_20260730"),
        timestamp("2026-06-11"), timestamp("2026-07-30"), symbols=tuple(s for s in symbols if s != "SMHUSDT"))
    sources += inputs
    data = {s: {**d, **{kind: early[s][kind]+d[kind] for kind in ("trade", "mark", "funding")}}
            if s in early else d for s, d in later.items()}
    june_data = data
    if args.start == "2026-04-07":
        prefix_cache = Path("state/research_cache/binance_macro_prefix_20260407_20260611")
        prefix_cache.mkdir(parents=True, exist_ok=True)
        target = prefix_cache/"exchange-info.json"
        if not target.exists():
            with target.open("xb") as f:
                f.write((cache/"exchange-info.json").read_bytes())
        prefix_symbols = ("SPYUSDT", "QQQUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT")
        rules = {r["symbol"]: r for r in json.loads(target.read_text())["symbols"]}
        assert all(int(rules[s]["onboardDate"]) < timestamp(args.start)*1000 for s in prefix_symbols)
        prefix, inputs = load_inputs(prefix_cache, timestamp(args.start), timestamp("2026-06-11"),
            symbols=prefix_symbols, download=args.download)
        sources += inputs
        data = {s: {**d, **{kind: prefix[s][kind]+d[kind] for kind in ("trade", "mark", "funding")}}
                if s in prefix else d for s, d in data.items()}
        for d in data.values():
            keys = [(int(r["fundingTime"]), r.get("rateType", "Regular")) for r in d["funding"]]
            assert keys == sorted(set(keys))
    book, signals = directional_book(data, features, "long", 20/3)
    known = {s: {b.t for b in d["trade"]} for s, d in data.items()}
    clocks = [(s, t) for s, t in candidate_clocks(book, signals) if t in known[s]]
    caps, cap_sources, _ = load_capacity_contexts(clocks, Path("state/research_cache/binance_macro_liquidity_20261015"), args.download)
    sources += cap_sources
    gates = {arm: episode_confirmations(book, signals, arm) for arm in ARMS if arm != "baseline"}
    assert all(set(g) == set(clocks) for g in gates.values())
    params = dict(strategy="macro_tactical", gross_cap=20, risk_fraction=.5, exchange_leverage=50,
        liquidation_stop_multiple=1.25, account_controls=False, funding_policy="debit_stress", sizing_gap_reserve=.03,
        allow_partial_histories=True, tactical_setup_policies=setup_policies(7, 21), funding_lease_hours=168, funding_lease_budget="risk")
    if args.start == "2026-04-07":
        control_book, control_signals = directional_book(june_data, features, "long", 20/3)
        for capital, scenario in itertools.product((10, 100), ("base", "double_cost")):
            control = replay(cost_case(control_book, scenario), control_signals, **params, capital=capital,
                entry_liquidity_caps=caps, fee=.001 if scenario == "double_cost" else .0005,
                slip=.005 if scenario == "double_cost" else .0025)
            old = json.loads(Path(f"state/research_runs/binance_macro_continuous_20261015/continuous_rolling7_risk_capital{capital}_{scenario}.json").read_text())
            assert control["trades"] == old["trades"] and control["curve"] == old["curve"]
    bundles = {}
    for arm, capital, scenario in itertools.product(ARMS, (10, 100), ("base", "double_cost")):
        b = replay(cost_case(book, scenario), signals, **params, capital=capital,
            entry_liquidity_caps=caps, entry_confirmations=gates.get(arm),
            fee=.001 if scenario == "double_cost" else .0005, slip=.005 if scenario == "double_cost" else .0025)
        r = b["summary"]
        closed = [t for t in b["trades"] if t["exit_reason"] != "end_of_sample"]
        r.update(arm=arm, capital=capital, scenario=scenario, closed_trades=len(closed), censored_trades=len(b["trades"])-len(closed),
                 closed_pnl=sum(t["net_pnl"] for t in closed), censored_pnl=sum(t["net_pnl"] for t in b["trades"] if t["exit_reason"] == "end_of_sample"))
        if scenario == "base":
            r["fixed_orders_double_cost_return"] = sum(fixed_fill_metrics(t, t, data[t["symbol"]]["funding"], fee=.0005, slip=.0025)["fixed_path_double_cost_pnl"] for t in b["trades"])/capital
        if arm == "baseline" and args.start == "2026-06-11":
            old = json.loads(Path(f"state/research_runs/binance_macro_continuous_20261015/continuous_rolling7_risk_capital{capital}_{scenario}.json").read_text())
            assert b["trades"] == old["trades"] and b["curve"] == old["curve"]
        bundles[arm, capital, scenario] = b
    print(json.dumps(dict(phase="accounts", start=args.start, accounts=len(bundles), raw_candidates=len(clocks))), flush=True)
    # Retain the isolated outcomes of ALL filtered continuations and anchors,
    # including profitable misses. No friction bypass or future-payoff ranking.
    relevant = set()
    for g in gates.values():
        for key, context in g.items():
            if not context["eligible"]:
                relevant.add(key)
                relevant.add((key[0], context["anchor_time"]))
    events = []
    for s, now in sorted(relevant, key=lambda key: (key[1], key[0])):
        e = dict(symbol=s, time=now, confirmations={arm: g[s, now] for arm, g in gates.items()}, outcomes={})
        for scenario in ("base", "double_cost"):
            b = replay(cost_case(book, scenario), signals, **{**params, "gross_cap": 1}, capital=100,
                forced_entry=dict(symbol=s, time=now, engine="tactical"),
                fee=.001 if scenario == "double_cost" else .0005, slip=.005 if scenario == "double_cost" else .0025)
            e["outcomes"][scenario] = (dict(accepted=True, net_on_notional=b["trades"][0]["net_pnl"]/b["trades"][0]["notional_usdt"],
                censored=b["trades"][0]["exit_reason"] == "end_of_sample", exit_reason=b["trades"][0]["exit_reason"])
                if b["trades"] else dict(accepted=False, rejections=b["summary"]["rejections"]))
        events.append(e)
    longest = {}
    for b in bundles.values():
        for t in b["trades"]:
            key = t["symbol"], t["entry_time"]
            if key not in longest or t["exit_time"] > longest[key]["exit_time"]:
                longest[key] = t
    minutes, minute_sources = minute_windows(list(longest.values()), Path("state/research_cache/binance_macro_minutes_20261015"), timestamp("2026-10-15"), args.download)
    sources += minute_sources
    atrs = {s: available_atr(d["trade"]) for s, d in data.items()}
    checks = 0
    for (arm, capital, scenario), b in bundles.items():
        equity = peak = capital
        mdd = 0
        checked = []
        cb = cost_case(data, scenario)
        for t in b["trades"]:
            s = t["symbol"]
            m = minutes[s, t["entry_time"]]
            result = frozen_trade({**t, "equity_before_entry": equity}, m["trade"], m["mark"], cb[s]["funding"], atrs[s], data[s]["rule"],
                fee=.001 if scenario == "double_cost" else .0005, slip=.005 if scenario == "double_cost" else .0025)
            assert result["status"] == "executed"
            for row in result.pop("curve"):
                mdd = max(mdd, 1-row["equity"]/peak)
                peak = max(peak, row["equity"])
            result.update(pnl_difference=result["net_pnl"]-t["net_pnl"],
                changed_exit=result["exit_time"] != t["exit_time"] or result["exit_reason"] != t["exit_reason"],
                risk_budget_breach=result["entry_stress_risk_usdt"] > .5*equity+1e-9,
                margin_budget_breach=result["entry_margin_fraction"] > .8+1e-9)
            equity += result["net_pnl"]
            checked.append(result)
            checks += 1
            if arm != "baseline":
                context = gates[arm][s, t["entry_time"]]
                assert context["eligible"] and context["anchor_time"] <= t["entry_time"]
        assert math.isclose(equity, capital+sum(t["net_pnl"] for t in checked), abs_tol=1e-8)
        b["minute_checks"] = checked
        b["summary"].update(minute_schedule_return=equity/capital-1, minute_close_mdd=mdd,
            minute_pnl_difference=equity-b["summary"]["final_equity"], minute_exit_changes=sum(t["changed_exit"] for t in checked),
            minute_risk_breaches=sum(t["risk_budget_breach"] for t in checked), minute_margin_breaches=sum(t["margin_budget_breach"] for t in checked))
    unique_sources = {s["path"]: s for s in sources}
    for source in unique_sources.values():
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    args.output.mkdir(parents=True)
    for (arm, capital, scenario), b in bundles.items():
        (args.output/f"{arm}_capital{capital}_{scenario}.json").write_text(json.dumps(b, allow_nan=False)+"\n")
    result = dict(start=args.start, end_exclusive="2026-10-15", arms=ARMS, runs=[b["summary"] for b in bundles.values()],
        first_contract_bars={s: d["trade"][0].t for s, d in data.items()},
        raw_candidates=len(clocks), gates={arm: [dict(symbol=s, time=t, **c) for (s, t), c in sorted(g.items())] for arm, g in gates.items()},
        diagnostic_events=events, minute_trade_checks=checks, legacy_controls=4, sources=list(unique_sources.values()),
        code_sources=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in
            (Path(__file__), Path("src/qount/research/binance_macro_entry_episodes.py"), Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"))],
        research_only=True, orders_authorized=False, independent_oos=False,
        assumptions=["Hypothesis follows observed cost-admission path failure. All histories/thresholds are consumed; no independent validation or asset-selected exclusion.",
            "April prefix audit keeps all three policies fixed before prefix download; it is an earlier-history extension, not independent OOS. SPY/QQQ/gold/copper/oil have actual history fromApril7; IWM/XLE fromJune11; SMH fromJuly30, each with14 complete-day ATR warmup. No synthetic prelisting bars.",
            "Three entry controls: unchanged, first setup opportunity only, or later opportunities only at a raw contract open no higher than the immutable first open. No tuned price tolerance.",
            "Episodes use consecutive regular-session10AM opportunities by contract and entry setup; signal gaps/setup changes reset anchors. Actual history availability is required; current close/future prices are not read.",
            "Signal scores/holding rules/risk budgets/leverage/ordinary costs/funding forecasts/capacity unchanged. One continuous account and causal per-contract ATR.",
            "Base5bp fees/25bp slip; stress10bp/50bp and doubled adverse ordinary funding. Fixed-order stress and resimulated admission are separate.",
            "All filtered events and their anchors are retained as isolated diagnostics with actual admission/costs,1x cap/100 USDT, without shared-book occupancy/minute capacity; not executable NAV.",
            "Minute checks freeze quantities/schedules and report discrepancies. Exit liquidity and current historical filters remain approximations."])
    (args.output/"summary.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    lines = ["# Missed-entry discipline under unchanged costs", "", "|Arm|Capital|Costs|Minute fixed-order return|Minute MDD|Closed|Censored|Closed PnL|", "|---|---:|---|---:|---:|---:|---:|---:|"]
    for r in result["runs"]:
        lines.append(f"|{r['arm']}|{r['capital']}|{r['scenario']}|{r['minute_schedule_return']:.2%}|{r['minute_close_mdd']:.2%}|{r['closed_trades']}|{r['censored_trades']}|{r['closed_pnl']:.5f}|")
    lines += ["", "## Assumptions", ""]+["- "+a for a in result["assumptions"]]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output), accounts=len(bundles), raw_candidates=len(clocks), diagnostic_events=len(events), minute_checks=checks)))


if __name__ == "__main__":
    main()
