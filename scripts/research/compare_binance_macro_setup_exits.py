"""Fixed setup-specific exits in consumed and newly fetched earlier histories."""
import argparse
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from qount.research.binance_etf_leverage import feature_at, load_inputs, replay
from qount.research.binance_etf_leverage import funding_reserve
from qount.research.binance_macro_funding_lease import review_lease
from qount.research.binance_macro_attack import CONTRACT_SIGNALS, directional_book, macro_features
from qount.research.binance_macro_liquidity import candidate_clocks, load_capacity_contexts
from qount.research.binance_macro_opportunities import cost_case, fixed_fill_metrics
from qount.research.binance_macro_setup import ARMS, setup_policies
from qount.research.binance_macro_validation import available_atr, frozen_trade, minute_windows
from qount.research_data.bars import session
from qount.research_data.archives import timestamp


WINDOWS = {"consumed": ("2026-07-30", "2026-10-15"), "earlier": ("2026-06-11", "2026-07-30")}
FOLLOWUP_END = {"consumed": "2026-10-15", "earlier": "2026-08-21"}
BASE_CACHE = Path("state/research_cache/binance_macro_attack_20261015")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--download", action="store_true")
    p.add_argument("--study", choices=("setups", "leases", "continuous"), default="setups")
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("refuse_overwrite_setup_comparison")
    features, equity_sources = macro_features(BASE_CACHE, "2026-10-15")
    arms = ARMS if args.study == "setups" else {"full21": (7, 21), "rolling7_cost": (7, 21), "rolling7_risk": (7, 21)}
    if args.study == "continuous":
        arms = {"full21": (7, 21), "rolling7_risk": (7, 21)}
    windows = WINDOWS if args.study != "continuous" else {"continuous": ("2026-06-11", "2026-10-15")}
    followups = FOLLOWUP_END if args.study != "continuous" else {"continuous": "2026-10-15"}
    bundles, events, quality, sources, universes = {}, [], [], list(equity_sources), {}
    total_checks = legacy_controls = lease_reviews_verified = 0
    first_contract_bars = {}
    for window, (start, end) in windows.items():
        cache = BASE_CACHE if window == "consumed" else Path("state/research_cache/binance_macro_earlier_20260611_20260730")
        symbols = tuple(s for s in CONTRACT_SIGNALS if window != "earlier" or s != "SMHUSDT")
        if window == "earlier":
            cache.mkdir(parents=True, exist_ok=True)
            target = cache/"exchange-info.json"
            if not target.exists():
                # Public cached filters only; no secrets or account configuration.
                with target.open("xb") as f:
                    f.write((BASE_CACHE/"exchange-info.json").read_bytes())
            rules = {r["symbol"]: r for r in json.loads(target.read_text())["symbols"]}
            assert all(int(rules[s]["onboardDate"]) < timestamp(start)*1000 for s in symbols)
        if window == "continuous":
            later_data, later_sources = load_inputs(BASE_CACHE, timestamp("2026-07-30"), timestamp(end), symbols=symbols)
            earlier_data, earlier_sources = load_inputs(Path("state/research_cache/binance_macro_earlier_20260611_20260730"),
                timestamp(start), timestamp("2026-07-30"), symbols=tuple(s for s in symbols if s != "SMHUSDT"))
            data = {s: {**d, **{kind: earlier_data[s][kind]+d[kind] for kind in ("trade", "mark", "funding")}}
                    if s in earlier_data else d for s, d in later_data.items()}
            inputs = earlier_sources+later_sources
            for d in data.values():
                keys = [(int(r["fundingTime"]), r.get("rateType", "Regular")) for r in d["funding"]]
                assert keys == sorted(set(keys))
        else:
            data, inputs = load_inputs(cache, timestamp(start), timestamp(end), download=args.download, symbols=symbols)
        sources.extend(inputs)
        followup_end = timestamp(followups[window])
        if window == "consumed":
            continuation_data = data
        elif window == "earlier":
            # Earlier entry cohort matures using already cached later prices;
            # no new entry is permitted on/after July30. No synthetic padding.
            data = {s: {**d,
                "trade": d["trade"]+[b for b in continuation_data[s]["trade"] if b.t < followup_end],
                "mark": d["mark"]+[b for b in continuation_data[s]["mark"] if b.t < followup_end],
                "funding": d["funding"]+[r for r in continuation_data[s]["funding"] if int(r["fundingTime"]) < followup_end*1000]}
                for s, d in data.items()}
            for d in data.values():
                assert [b.t for b in d["trade"]] == [b.t for b in d["mark"]] == list(range(timestamp(start), followup_end, 3600))
                keys = [(int(r["fundingTime"]), r.get("rateType", "Regular")) for r in d["funding"]]
                assert keys == sorted(set(keys))
        universes[window] = list(symbols)
        first_contract_bars[window] = {s: d["trade"][0].t for s, d in data.items()}
        fs = {s: [r for r in features[s] if r["available"] < followup_end] for s in symbols}
        book, signals = directional_book(data, fs, "long", 20/3)
        available = {s: {b.t for b in d["trade"]} for s, d in data.items()}
        clocks = [(s, t) for s, t in candidate_clocks(book, signals) if t < timestamp(end) and t in available[s]]
        caps, cap_sources, _ = load_capacity_contexts(clocks, Path("state/research_cache/binance_macro_liquidity_20261015"), args.download)
        sources.extend(cap_sources)
        params = dict(strategy="macro_tactical", gross_cap=20, risk_fraction=.5, exchange_leverage=50,
                      liquidation_stop_multiple=1.25, account_controls=False, funding_policy="debit_stress", sizing_gap_reserve=.03,
                      entry_end_exclusive=timestamp(end), allow_partial_histories=window == "continuous")
        if window == "continuous":
            control_book, control_signals = directional_book(later_data, fs, "long", 20/3)
            for arm, capital, scenario in itertools.product(arms, (10, 100), ("base", "double_cost")):
                control = replay(cost_case(control_book, scenario), control_signals,
                    **{**params, "allow_partial_histories": False}, capital=capital, entry_liquidity_caps=caps,
                    tactical_setup_policies=setup_policies(7, 21), funding_lease_hours=168 if arm == "rolling7_risk" else None,
                    funding_lease_budget="risk" if arm == "rolling7_risk" else "cost",
                    fee=.001 if scenario == "double_cost" else .0005, slip=.005 if scenario == "double_cost" else .0025)
                old = json.loads(Path(f"state/research_runs/binance_macro_funding_leases_20261015_final/consumed_{arm}_capital{capital}_{scenario}.json").read_text())
                assert control["trades"] == old["trades"] and control["curve"] == old["curve"]
                legacy_controls += 1
        for arm, capital, scenario in itertools.product(arms, (10, 100), ("base", "double_cost")):
            trend, mr = arms[arm]
            b = replay(cost_case(book, scenario), signals, **params, capital=capital, entry_liquidity_caps=caps,
                       tactical_setup_policies=setup_policies(trend, mr),
                       funding_lease_hours=168 if arm.startswith("rolling7_") else None,
                       funding_lease_budget="risk" if arm == "rolling7_risk" else "cost",
                       fee=.001 if scenario == "double_cost" else .0005, slip=.005 if scenario == "double_cost" else .0025)
            r = b["summary"]
            closed = [t for t in b["trades"] if t["exit_reason"] != "end_of_sample"]
            censored = [t for t in b["trades"] if t["exit_reason"] == "end_of_sample"]
            r.update(window=window, arm=arm, capital=capital, scenario=scenario,
                     closed_trades=len(closed), censored_trades=len(censored),
                     closed_pnl=sum(t["net_pnl"] for t in closed), censored_pnl=sum(t["net_pnl"] for t in censored))
            r["lease_reviews"] = sum(len(t.get("funding_lease_reviews", [])) for t in b["trades"])
            r["lease_renewals"] = sum(review["allowed"] for t in b["trades"] for review in t.get("funding_lease_reviews", []))
            if scenario == "base":
                r["fixed_orders_double_cost_return"] = sum(fixed_fill_metrics(t, t, data[t["symbol"]]["funding"], fee=.0005, slip=.0025)["fixed_path_double_cost_pnl"] for t in b["trades"])/capital
            bundles[window, arm, capital, scenario] = b
            if window == "consumed" and arm in ("attack7", "structural21"):
                old = json.loads(Path(f"state/research_runs/binance_macro_profit_exits_20261015/{arm}_long_capital{capital}_{scenario}.json").read_text())
                clean = [{k: v for k, v in t.items() if k not in ("hold_feature", "tactical_setup")} for t in b["trades"]]
                assert clean == old["trades"] and b["curve"] == old["curve"]
                legacy_controls += 1
            if arm == "full21" and window != "continuous":
                old = json.loads(Path(f"state/research_runs/binance_macro_setup_exits_20261015_final/{window}_trend7_mr21_capital{capital}_{scenario}.json").read_text())
                assert b["trades"] == old["trades"] and b["curve"] == old["curve"]
                legacy_controls += 1
        print(json.dumps(dict(phase="accounts", window=window, raw_candidates=len(clocks))), flush=True)
        # Fixed raw first episodes, independently of account occupancy/admission.
        times = [b.t for b in next(iter(data.values()))["trade"] if session(b.t) is not None and session(b.t)[1] == 600]
        ordinals, previous, episode_counts = {t: i for i, t in enumerate(times)}, {}, Counter()
        for s, now in (sorted(clocks, key=lambda x: (x[1], x[0])) if args.study == "setups" else []):
            first = previous.get(s) != ordinals[now]-1
            if first:
                episode_counts[s] += 1
            previous[s] = ordinals[now]
            if not first:
                continue
            f = feature_at(signals[s], now)
            e = dict(window=window, symbol=s, time=now, setup=f["tactical_setup"], episode=episode_counts[s], outcomes={})
            for days in (7, 21):
                out = replay(book, signals, **{**params, "gross_cap": 1}, capital=100, fee=.0005, slip=.0025,
                             tactical_setup_policies=setup_policies(days, days),
                             forced_entry=dict(symbol=s, time=now, engine="tactical", ignore_friction_gate=True))
                if out["trades"]:
                    t = out["trades"][0]
                    e["outcomes"][str(days)] = dict(net_on_notional=t["net_pnl"]/t["notional_usdt"],
                        censored=t["exit_reason"] == "end_of_sample", exit_reason=t["exit_reason"], exit_time=t["exit_time"])
            events.append(e)
        for setup, days in (itertools.product(("all", "breakout", "pullback", "mean_reversion"), (7, 21)) if args.study == "setups" else []):
            selected = [e for e in events if e["window"] == window and (setup == "all" or setup == e["setup"]) and str(days) in e["outcomes"]]
            closed = [e["outcomes"][str(days)]["net_on_notional"] for e in selected if not e["outcomes"][str(days)]["censored"]]
            quality.append(dict(window=window, setup=setup, days=days, accepted=len(selected), closed=len(closed),
                                censored=len(selected)-len(closed), mean_closed_net_on_notional=statistics.mean(closed) if closed else None))
        longest = {}
        for (w, _, _, _), b in bundles.items():
            if w != window:
                continue
            for t in b["trades"]:
                key = t["symbol"], t["entry_time"]
                if key not in longest or t["exit_time"] > longest[key]["exit_time"]:
                    longest[key] = t
        minutes, minute_sources = minute_windows(list(longest.values()), Path("state/research_cache/binance_macro_minutes_20261015"), followup_end, args.download)
        sources.extend(minute_sources)
        atrs = {s: available_atr(d["trade"]) for s, d in data.items()}
        for (w, arm, capital, scenario), b in bundles.items():
            if w != window:
                continue
            equity = peak = capital
            mdd = 0
            checks = []
            cb = cost_case(data, scenario)
            for t in b["trades"]:
                s = t["symbol"]
                for recorded in t.get("funding_lease_reviews", []):
                    now = recorded["time"]
                    rows = [r for r in cb[s]["funding"] if t["entry_time"]*1000 <= int(r["fundingTime"]) < now*1000]
                    paid = sum(max(0, t["quantity"]*float(r["markPrice"])*float(r["fundingRate"])) for r in rows)
                    cash = t["equity_before_entry"]-t["entry_fee"]-sum(t["quantity"]*float(r["markPrice"])*float(r["fundingRate"]) for r in rows)
                    mark = next(b.o for b in cb[s]["mark"] if b.t == now)
                    price = next(b.o for b in cb[s]["trade"] if b.t == now)
                    fee, slip = (.001, .005) if scenario == "double_cost" else (.0005, .0025)
                    nav = cash+t["quantity"]*(mark-t["entry_price"])-t["quantity"]*mark*fee
                    assert math.isclose(paid, recorded["adverse_paid"], abs_tol=1e-8)
                    assert math.isclose(cash, recorded["cash"], abs_tol=1e-8)
                    assert math.isclose(nav, recorded["equity"], abs_tol=1e-8)
                    forecast = funding_reserve(cb[s]["funding"], now, recorded["forecast_hours"], "debit_stress")
                    f = feature_at(signals[s], now)
                    eligible = f is not None and 0 < now-f["available"] <= 4*86400 and f[t["hold_feature"]]
                    calculated = review_lease({**t, "stop": recorded["stop"], "funding_adverse_paid": paid}, now=now,
                        price=price, equity=nav, cash=cash, reserve=forecast, hours=recorded["forecast_hours"], eligible=eligible,
                        fee=fee, slip=slip, risk_fraction=.5, gap=.03)
                    assert calculated["allowed"] == recorded["allowed"] and calculated["reason"] == recorded["reason"]
                    lease_reviews_verified += 1
                m = minutes[t["symbol"], t["entry_time"]]
                result = frozen_trade({**t, "equity_before_entry": equity}, m["trade"], m["mark"], cb[t["symbol"]]["funding"], atrs[t["symbol"]], data[t["symbol"]]["rule"],
                                      fee=.001 if scenario == "double_cost" else .0005, slip=.005 if scenario == "double_cost" else .0025)
                if result["status"] != "executed":
                    raise AssertionError(result)
                for row in result.pop("curve"):
                    mdd = max(mdd, 1-row["equity"]/peak)
                    peak = max(peak, row["equity"])
                result.update(hourly_pnl_difference=result["net_pnl"]-t["net_pnl"],
                    changed_exit=result["exit_time"] != t["exit_time"] or result["exit_reason"] != t["exit_reason"],
                    risk_budget_breach=result["entry_stress_risk_usdt"] > .5*equity+1e-9,
                    margin_budget_breach=result["entry_margin_fraction"] > .8+1e-9)
                equity += result["net_pnl"]
                checks.append(result)
                total_checks += 1
            assert math.isclose(equity, capital+sum(t["net_pnl"] for t in checks), abs_tol=1e-8)
            b["minute_checks"] = checks
            b["summary"].update(minute_schedule_return=equity/capital-1, minute_close_mdd=mdd,
                minute_pnl_difference=equity-b["summary"]["final_equity"], minute_exit_changes=sum(t["changed_exit"] for t in checks),
                minute_risk_breaches=sum(t["risk_budget_breach"] for t in checks), minute_margin_breaches=sum(t["margin_budget_breach"] for t in checks))
        print(json.dumps(dict(phase="window_complete", window=window)), flush=True)
    unique_sources = {r["path"]: r for r in sources}
    for r in unique_sources.values():
        assert hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"]
    args.output.mkdir(parents=True)
    for (window, arm, capital, scenario), b in bundles.items():
        (args.output/f"{window}_{arm}_capital{capital}_{scenario}.json").write_text(json.dumps(b, allow_nan=False)+"\n")
    summary = dict(study=args.study, windows=windows, followup_end_exclusive=followups, universes=universes,
                   first_contract_bars=first_contract_bars, arms=arms, runs=[b["summary"] for b in bundles.values()],
                   lease_reviews_verified=lease_reviews_verified,
                   fixed_episode_quality=quality, minute_checks=total_checks, legacy_controls=legacy_controls,
                   sources=list(unique_sources.values()), code_sources=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in
                       (Path(__file__), Path("src/qount/research/binance_etf_leverage.py"), Path("src/qount/research_data/binance_history.py"), Path("src/qount/research_data/archives.py"), Path("src/qount/research_data/bars.py"), Path("src/qount/research/engine/perpetual.py"), Path("src/qount/research/binance_macro_setup.py"),
                        Path("src/qount/research/binance_macro_funding_lease.py"), Path("src/qount/research/binance_macro_validation.py"))],
                   research_only=True, orders_authorized=False, independent_oos=False,
                   assumptions=[("Four fixed setup policies before earlier-contract download; no payoff-directed threshold search or ticker removal." if args.study == "setups" else
                        "Full21 and rolling7-cost were compared first; rolling7-risk was added after observing cost-cap rejection despite available cash/risk headroom. This is adaptive consumed-history research, not independent confirmation."),
                       ("Continuous universe has seven histories fromJune11 and actual SMH history fromJuly30. Current filters/adjusted ETF proxies remain historical approximations; no forward or independent OOS claim." if args.study == "continuous" else
                        "Earlier seven-contract universe excludes not-yet-listed SMH; current filters and adjusted ETF proxies are still historical approximations. Earlier-history audit is not forward or independent OOS."),
                       ("Continuous entries remain eligible throughOctober15 exclusive; no July30 entry cutoff or account reset is applied." if args.study == "continuous" else
                        "Earlier entries stop before July30; holdings/labels follow through August21 using cached real prices, so all possible21-day horizons mature. No post-cutoff entries or synthetic padding."),
                       ("Continuous mode uses ONE carried cash book/ATR history fromJune11; SMH joins only when actual hourly history exists, then needs its own14 complete-day ATR. No padding, July30 reset, deposits or cohort-return multiplication." if args.study == "continuous" else
                        "Earlier and consumed windows are separate starting-capital experiments; their returns must not be added or compounded."),
                       "Entry setup and exit eligibility feature stay frozen. Full policy reserves the entire horizon; rolling policy reserves7d and renews only within lifetime adverse-cost, free-cash and original/current risk budgets, with21d hard cap.",
                       "Rolling renewal never adds quantity, margin or deposits. Actual signed ordinary/special funding is always paid. A debit exceeding lifetime allowance schedules next-hour exit and may overshoot the allowance before execution.",
                       "Cost lease allowance uses original20%-of-stop friction geometry; risk lease allowance is original entry risk budget minus stop/gap/ordinary-cost stress. Both lifetime allowances are frozen at entry, with current/original risk and free-cash renewal checks retained.",
                       "All accounts50% stress risk/1.25x liquidation cushion/3% gap reserve/10% causal minute volume cap; no drawdown downshift or HALT, liquidation HALT retained.",
                       "Base5bp fees/25bp slip each side; stress10bp/50bp and doubled adverse ordinary funding. No cost assumptions were reduced.",
                       ("Isolated fixed episodes bypass friction admission and minute capacity but still pay fees/slip/funding; their normalized means are not executable portfolios. Censored results are excluded from closed means and counted separately." if args.study == "setups" else
                        "Lease/continuous comparisons retain ordinary admission and actual quantity limits; no forced-event admission bypass is used."),
                       "Minute checks freeze hourly orders; disagreements and actual-equity risk/margin checks are retained, not a fully resized minute strategy."])
    (args.output/"summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    if events:
        (args.output/"events.json").write_text(json.dumps(events, indent=2, allow_nan=False)+"\n")
    lines = ["# Setup-specific exits and funding leases", "", "|Window|Arm|Capital|Cost|Hourly return|Minute fixed-order return|Minute MDD|Closed|Censored|Closed PnL|Censored PnL|", "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in summary["runs"]:
        lines.append(f"|{r['window']}|{r['arm']}|{r['capital']}|{r['scenario']}|{r['net_return']:.2%}|{r['minute_schedule_return']:.2%}|{r['minute_close_mdd']:.2%}|{r['closed_trades']}|{r['censored_trades']}|{r['closed_pnl']:.5f}|{r['censored_pnl']:.5f}|")
    if quality:
        lines += ["", "## Fixed first-episode diagnosis, not executable NAV", "", "|Window|Setup|Days|Closed|Censored|Mean closed net/notional|", "|---|---|---:|---:|---:|---:|"]
    for r in quality:
        mean = f"{r['mean_closed_net_on_notional']:.2%}" if r["mean_closed_net_on_notional"] is not None else "n/a"
        lines.append(f"|{r['window']}|{r['setup']}|{r['days']}|{r['closed']}|{r['censored']}|{mean}|")
    if args.study != "setups":
        lines += ["", "## Fixed original orders at double cost; no admission/resizing changes", "", "|Window|Arm|Capital|Net return|", "|---|---|---:|---:|"]
        for r in summary["runs"]:
            if r["scenario"] == "base":
                lines.append(f"|{r['window']}|{r['arm']}|{r['capital']}|{r['fixed_orders_double_cost_return']:.2%}|")
    lines += ["", "## Assumptions", ""]+["- "+s for s in summary["assumptions"]]
    (args.output/"report.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(dict(output=str(args.output), accounts=len(bundles), minute_checks=total_checks, legacy_controls=legacy_controls)), flush=True)


if __name__ == "__main__":
    main()
