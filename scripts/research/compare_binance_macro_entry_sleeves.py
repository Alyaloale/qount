"""Fixed trend/MR entry ablation; capacity removal is diagnostic only."""
import argparse
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from qount.research.binance_etf_leverage import load_inputs, replay
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_entry_episodes import episode_confirmations
from qount.research.binance_macro_liquidity import load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, trade_pnl_components
from qount.research.binance_macro_setup import setup_policies
from qount.research.binance_macro_validation import available_atr, frozen_trade, minute_windows
from qount.research_data.archives import timestamp


def friction_shadow(book, signals, params, gates, caps, sources, output):
    """Ignore the friction ratio ONLY in isolated counterfactual diagnostics."""
    reference_path = Path("state/research_runs/binance_macro_entry_sleeves_20261015/summary.json")
    reference = json.loads(reference_path.read_text())
    for source in reference["sources"]:
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    events, controls = [], 0
    for old in reference["isolated_events"]:
        if not old["first"]:
            continue
        key = old["symbol"], old["time"]
        assert gates[key]["first"] and gates[key]["setup"] == old["setup"]
        e = {k: old[k] for k in ("symbol", "time", "setup", "first")}
        e["outcomes"] = {}
        for scenario in ("base", "double_cost"):
            fee, slip = (.001, .005) if scenario == "double_cost" else (.0005, .0025)
            b = replay(cost_case(book, scenario), signals, **params, capital=10, fee=fee, slip=slip,
                forced_entry=dict(symbol=key[0], time=key[1], engine="tactical", ignore_friction_gate=True),
                entry_liquidity_caps=caps)
            normal = old["outcomes"][scenario]
            o = dict(normal_accepted=normal["accepted"], accepted=bool(b["trades"]))
            if normal["accepted"]:
                assert b["trades"] == [normal["trade"]]
                controls += 1
            if b["trades"]:
                assert len(b["trades"]) == 1
                t = b["trades"][0]
                o.update(trade=t, components=trade_pnl_components(t, fee=fee, slip=slip),
                    censored=t["exit_reason"] == "end_of_sample", net_on_notional=t["net_pnl"]/t["notional_usdt"])
            else:
                o["rejections"] = b["summary"]["rejections"]
            e["outcomes"][scenario] = o
        events.append(e)
    groups = []
    for scenario, admission, sleeve in itertools.product(("base", "double_cost"), (True, False), ("trend", "mean_reversion")):
        rows = [e["outcomes"][scenario] for e in events
                if (e["setup"] == "mean_reversion") == (sleeve == "mean_reversion")
                and e["outcomes"][scenario]["normal_accepted"] == admission]
        accepted = [o for o in rows if o["accepted"]]
        closed = [o for o in accepted if not o["censored"]]
        groups.append(dict(scenario=scenario, normal_accepted=admission, sleeve=sleeve,
            first_opportunities=len(rows), shadow_accepted=len(accepted), closed=len(closed),
            censored=len(accepted)-len(closed),
            mean_closed_net_on_notional=statistics.mean(o["net_on_notional"] for o in closed) if closed else None,
            closed_win_fraction=sum(o["net_on_notional"] > 0 for o in closed)/len(closed) if closed else None))
    for source in sources:
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    result = dict(events=events, groups=groups, admitted_event_controls=controls, sources=sources,
        reference=dict(path=str(reference_path), sha256=hashlib.sha256(reference_path.read_bytes()).hexdigest()),
        code_sources=[dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in
            (Path(__file__), Path("src/qount/research/binance_macro_opportunities.py"), Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"))],
        research_only=True, orders_authorized=False, independent_oos=False, executable_constraint_set=False,
        assumptions=["Isolated21 first opportunities, fixed10USDT, all normal sizing/risk/capacity/holding/costs retained except entry friction-ratio rejection.",
            "Costs are paid, no free execution. Admission removal is a shadow diagnostic, not executable strategy NAV or promotion.",
            "Closed/censored outcomes kept separate; overlapping and highly correlated events cannot be added as portfolio PnL.",
            "Hourly replay only for new shadow trades, no new minute execution certification; normal admitted events must reproduce exactly."])
    output.mkdir(parents=True)
    (output/"summary.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    lines = ["# Friction-ratio admission shadow diagnostics", "",
        "|Costs|Normal admission|Sleeve|First opportunities|Shadow accepted|Closed|Censored|Closed mean net/notional|",
        "|---|---|---|---:|---:|---:|---:|---:|"]
    for g in groups:
        value = f"{g['mean_closed_net_on_notional']:.2%}" if g['closed'] else "n/a"
        lines.append(f"|{g['scenario']}|{g['normal_accepted']}|{g['sleeve']}|{g['first_opportunities']}|{g['shadow_accepted']}|{g['closed']}|{g['censored']}|{value}|")
    lines += ["", "## Assumptions", ""]+["- "+a for a in result["assumptions"]]
    (output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(output), first_opportunities=len(events), admitted_controls=controls)), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--download", action="store_true", help="Only missing public minute windows")
    p.add_argument("--mode", choices=("sleeves", "friction-shadow"), default="sleeves")
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_entry_sleeves")
    cache = Path("state/research_cache/binance_macro_attack_20261015")
    features, sources = macro_features(cache, "2026-10-15")
    symbols = tuple(CONTRACT_SIGNALS)
    data, inputs = load_inputs(cache, timestamp("2026-07-30"), timestamp("2026-10-15"), symbols=symbols)
    sources += inputs
    for folder, start, end, subset in (
        ("binance_macro_earlier_20260611_20260730", "2026-06-11", "2026-07-30", tuple(s for s in symbols if s != "SMHUSDT")),
        ("binance_macro_prefix_20260407_20260611", "2026-04-07", "2026-06-11", ("SPYUSDT", "QQQUSDT", "XAUUSDT", "COPPERUSDT", "CLUSDT")),
    ):
        prefix, inputs = load_inputs(Path("state/research_cache")/folder, timestamp(start), timestamp(end), symbols=subset)
        sources += inputs
        data = {s: {**d, **{k: prefix[s][k]+d[k] for k in ("trade", "mark", "funding")}}
                if s in prefix else d for s, d in data.items()}
    book, signals = directional_book(data, features, "long", 20/3)
    no_chase = episode_confirmations(book, signals, "no_chase")
    clocks = sorted(no_chase, key=lambda k: (k[1], k[0]))
    caps, cap_sources, _ = load_capacity_contexts(clocks, Path("state/research_cache/binance_macro_liquidity_20261015"))
    sources += cap_sources
    params = dict(strategy="macro_tactical", gross_cap=20, risk_fraction=.5, exchange_leverage=50,
        liquidation_stop_multiple=1.25, account_controls=False, funding_policy="debit_stress", sizing_gap_reserve=.03,
        allow_partial_histories=True, tactical_setup_policies=setup_policies(7, 21), funding_lease_hours=168, funding_lease_budget="risk")
    if args.mode == "friction-shadow":
        friction_shadow(book, signals, params, no_chase, caps, sources, args.output)
        return
    gates = {}
    for sleeve in ("shared", "trend_only", "mr_only"):
        gates[sleeve] = {}
        for key, context in no_chase.items():
            selected = (sleeve == "shared" or (context["setup"] == "mean_reversion") == (sleeve == "mr_only"))
            gates[sleeve][key] = {**context, "eligible": context["eligible"] and selected,
                "reason": context["reason"] if selected else "other_entry_sleeve"}
    bundles = {}
    legacy_controls = 0
    for sleeve, capital, scenario, capacity in itertools.product(
            gates, (10, 100), ("base", "double_cost"), ("causal", "without_short_volume_cap")):
        fee, slip = (.001, .005) if scenario == "double_cost" else (.0005, .0025)
        b = replay(cost_case(book, scenario), signals, **params, capital=capital, fee=fee, slip=slip,
            entry_confirmations=gates[sleeve], entry_liquidity_caps=caps if capacity == "causal" else None, trace=True)
        if sleeve == "shared" and capacity == "causal":
            old = json.loads(Path(f"state/research_runs/binance_macro_entry_extended_20261015/no_chase_capital{capital}_{scenario}.json").read_text())
            assert b["trades"] == old["trades"] and b["curve"] == old["curve"]
            legacy_controls += 1
        r = b["summary"]
        r.update(sleeve=sleeve, capital=capital, scenario=scenario, capacity=capacity,
                 executable_constraint_set=capacity == "causal")
        for category in ("closed", "censored"):
            trades = [t for t in b["trades"] if (t["exit_reason"] == "end_of_sample") == (category == "censored")]
            r[category+"_trades"] = len(trades)
            r[category+"_pnl"] = sum(t["net_pnl"] for t in trades)
            r[category+"_components"] = {k: sum(c[k] for c in
                [trade_pnl_components(t, fee=fee, slip=slip) for t in trades]) for k in
                ("raw_price_pnl", "slippage_cost", "fees", "net_funding", "net_pnl")}
        assert math.isclose(r["final_equity"], capital+r["closed_pnl"]+r["censored_pnl"], abs_tol=1e-8)
        for t in b["trades"]:
            assert gates[sleeve][t["symbol"], t["entry_time"]]["eligible"]
        bundles[sleeve, capital, scenario, capacity] = b
    print(json.dumps(dict(phase="accounts", accounts=len(bundles), legacy_controls=legacy_controls)), flush=True)

    # Frozen-capital isolated opportunities retain misses and losing events.
    # They include admission and capacity, but have no competing holdings.
    events = []
    for s, now in clocks:
        context = no_chase[s, now]
        e = dict(symbol=s, time=now, setup=context["setup"], first=context["first"],
                 no_chase_eligible=context["eligible"], anchor_time=context["anchor_time"], outcomes={})
        for scenario in ("base", "double_cost"):
            fee, slip = (.001, .005) if scenario == "double_cost" else (.0005, .0025)
            b = replay(cost_case(book, scenario), signals, **params, capital=10, fee=fee, slip=slip,
                forced_entry=dict(symbol=s, time=now, engine="tactical"), entry_liquidity_caps=caps)
            if b["trades"]:
                assert len(b["trades"]) == 1
                t = b["trades"][0]
                c = trade_pnl_components(t, fee=fee, slip=slip)
                e["outcomes"][scenario] = dict(accepted=True, trade=t, components=c,
                    net_on_notional=t["net_pnl"]/t["notional_usdt"], net_stress_r=t["net_pnl"]/t["stress_risk_usdt"],
                    censored=t["exit_reason"] == "end_of_sample")
            else:
                e["outcomes"][scenario] = dict(accepted=False, rejections=b["summary"]["rejections"])
        events.append(e)
    groups = []
    for setup, scenario in itertools.product(("breakout", "pullback", "mean_reversion"), ("base", "double_cost")):
        # First observed opportunity only; continuation days aren't independent.
        candidates = [e for e in events if e["setup"] == setup and e["first"]]
        accepted = [e["outcomes"][scenario] for e in candidates if e["outcomes"][scenario]["accepted"]]
        closed = [e for e in accepted if not e["censored"]]
        values = [e["net_on_notional"] for e in closed]
        groups.append(dict(setup=setup, scenario=scenario, first_opportunities=len(candidates), accepted=len(accepted),
            closed=len(closed), censored=len(accepted)-len(closed),
            mean_closed_net_on_notional=statistics.mean(values) if values else None,
            mean_closed_stress_r=statistics.mean(e["net_stress_r"] for e in closed) if closed else None,
            closed_win_fraction=sum(v > 0 for v in values)/len(values) if values else None))
    occupancy = []
    for scenario in ("base", "double_cost"):
        b = bundles["shared", 10, scenario, "causal"]
        trace = {row["time"]: row for row in b["decisions"]}
        setups = {(t["symbol"], t["entry_time"]): t["tactical_setup"] for t in b["trades"]}
        for e in events:
            row = trace[e["time"]]
            if not e["no_chase_eligible"]:
                status = "no_chase_filtered"
            elif row["opened"] and row["opened"]["symbol"] == e["symbol"]:
                status = "executed"
            elif row["held_after_exits"]:
                held = row["held_after_exits"]["symbol"]
                prior = [(t, setup) for (s, t), setup in setups.items() if s == held and t < e["time"]]
                status = "occupied_"+max(prior)[1]
            elif row["just_closed"]:
                status = "exit_cooldown"
            elif row["opened"]:
                status = "another_candidate_selected"
            else:
                status = "account_path_or_entry_filter"
            occupancy.append(dict(symbol=e["symbol"], time=e["time"], setup=e["setup"], scenario=scenario,
                first=e["first"], status=status, fixed10_isolated_accepted=e["outcomes"][scenario]["accepted"]))
    print(json.dumps(dict(phase="opportunities", raw=len(events), first=sum(e["first"] for e in events))), flush=True)

    longest = {}
    for b in bundles.values():
        for t in b["trades"]:
            key = t["symbol"], t["entry_time"]
            if key not in longest or t["exit_time"] > longest[key]["exit_time"]:
                longest[key] = t
    minutes, minute_sources = minute_windows(list(longest.values()), Path("state/research_cache/binance_macro_minutes_20261015"),
        timestamp("2026-10-15"), args.download)
    sources += minute_sources
    atrs = {s: available_atr(d["trade"]) for s, d in data.items()}
    count = 0
    for (sleeve, capital, scenario, capacity), b in bundles.items():
        equity = peak = capital
        mdd, checked = 0, []
        fee, slip = (.001, .005) if scenario == "double_cost" else (.0005, .0025)
        cb = cost_case(data, scenario)
        for t in b["trades"]:
            s = t["symbol"]
            m = minutes[s, t["entry_time"]]
            result = frozen_trade({**t, "equity_before_entry": equity}, m["trade"], m["mark"], cb[s]["funding"],
                atrs[s], data[s]["rule"], fee=fee, slip=slip)
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
            count += 1
        b["minute_checks"] = checked
        b["summary"].update(minute_schedule_return=equity/capital-1, minute_close_mdd=mdd,
            minute_pnl_difference=equity-b["summary"]["final_equity"], minute_exit_changes=sum(t["changed_exit"] for t in checked),
            minute_risk_breaches=sum(t["risk_budget_breach"] for t in checked), minute_margin_breaches=sum(t["margin_budget_breach"] for t in checked))
    unique = {s["path"]: s for s in sources}
    for s in unique.values():
        assert hashlib.sha256(Path(s["path"]).read_bytes()).hexdigest() == s["sha256"]
    args.output.mkdir(parents=True)
    for key, b in bundles.items():
        (args.output/("_".join(map(str, key))+".json")).write_text(json.dumps(b, allow_nan=False)+"\n")
    result = dict(start="2026-04-07", end_exclusive="2026-10-15", runs=[b["summary"] for b in bundles.values()],
        isolated_events=events, first_opportunity_groups=groups, occupancy=occupancy,
        occupancy_counts=dict(Counter(r["status"] for r in occupancy)), minute_trade_checks=count,
        legacy_controls=legacy_controls, sources=list(unique.values()),
        code_sources=[dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in
            (Path(__file__), Path("src/qount/research/binance_macro_opportunities.py"),
             Path("src/qount/research/binance_macro_entry_episodes.py"), Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"))],
        research_only=True, orders_authorized=False, independent_oos=False,
        assumptions=["Fixed setups/ranks/stops/holding policies/risk/leverage/funding and no-chase rule. Only entry sleeve and short-window capacity toggled.",
            "Base fee5bp/slip25bp per side; stress fee10bp/slip50bp plus doubled adverse ordinary funding. Actual signed special funding unchanged.",
            "Removing short-volume capacity is unexecutable attribution; previous-hour1% cap and all filters still apply. No new real trading claim.",
            "Isolated events use fixed10USDT with normal admission and causal capacity, no competing holdings. Different cash histories can change quantity and funding lease paths; not additive portfolio PnL.",
            "Group statistics use first opportunity per consecutive same-setup episode, keep rejects and censored events. Overlapping different setups are still correlated; no significance/OOS claim.",
            "Minute checks freeze account quantities/exit schedules, do not rerun complete minute-level decisions. Exit liquidity, current filters/MMR and adjusted proxy ETF signals remain approximations.",
            "Actual contract histories start April7 for five symbols, June11 for IWM/XLE, July30 for SMH; independent14complete-day ATR warmup, no synthetic history."])
    (args.output/"summary.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    lines = ["# Fixed trend / mean-reversion entry and capacity ablation", "",
        "|Entry sleeve|Capital|Costs|Capacity|Minute return|Minute MDD|Closed PnL|Censored PnL|",
        "|---|---:|---|---|---:|---:|---:|---:|"]
    for r in result["runs"]:
        lines.append(f"|{r['sleeve']}|{r['capital']}|{r['scenario']}|{r['capacity']}|{r['minute_schedule_return']:.2%}|{r['minute_close_mdd']:.2%}|{r['closed_pnl']:.5f}|{r['censored_pnl']:.5f}|")
    lines += ["", "## First-opportunity diagnostics", "", json.dumps(groups, ensure_ascii=False, indent=2),
              "", "## Assumptions", ""]+["- "+a for a in result["assumptions"]]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output), accounts=len(bundles), minute_checks=count, controls=legacy_controls)), flush=True)


if __name__ == "__main__":
    main()
