"""Sixth-round structural discovery: autonomous sleeves and crisis payoff sources.

Uses frozen public history and cash/units. No execution or service interfaces.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import statistics as stats
import sys
from pathlib import Path
from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.research import dual_engine_optimization as old
from qount.research import dual_engine_structural as base
from qount.research import dual_engine_expansion as ex
from qount.research import dual_engine_nextgen as previous
from qount.research.dual_engine_expansion_data import load_macro, load_rates
from qount.research.dual_engine_execution_study import load_cache, read_opens, verify_manifest, paired_year_exclusion
from qount.research.dual_engine_nextgen_data import load_tail
from qount.research.dual_engine_regimes_data import load_inverse
from qount.research.c60_execution_control import acquire_opens

G20_CONTROLS = ("g20", "gold20", "aware_gold_cash", "aware_gold_rotate", "macro_fund")
G20_CANDIDATES = ("gold_short_crisis", "macro_long_book", "macro_directional_book", "macro_directional_crisis",
                  "macro_two_speed", "gold_trend_budget", "macro_risk_book", "macro_joint_defense")
C60_CONTROLS = ("residual2", "btc_continuous", "core_only", "recovery_core", "recovery_source")
C60_CANDIDATES = ("handoff_core", "handoff_source", "continuous_two_speed", "autonomous_satellites",
                  "dual_core", "dual_autonomous", "gold_crisis_reserve", "gold_autonomous")
PAIRS = (
    ("g20", "gold_short_crisis", "aware_gold_cash"),
    ("g20", "gold_short_crisis", "aware_gold_rotate"),
    ("g20", "macro_long_book", "macro_fund"),
    ("g20", "macro_directional_book", "macro_long_book"),
    ("g20", "macro_directional_crisis", "macro_directional_book"),
    ("g20", "macro_two_speed", "macro_directional_crisis"),
    ("g20", "gold_trend_budget", "aware_gold_cash"),
    ("g20", "macro_risk_book", "macro_directional_book"),
    ("g20", "macro_joint_defense", "macro_directional_book"),
    ("c60", "handoff_core", "recovery_core"),
    ("c60", "handoff_source", "recovery_source"),
    ("c60", "continuous_two_speed", "residual2"),
    ("c60", "autonomous_satellites", "residual2"),
    ("c60", "dual_core", "residual2"),
    ("c60", "dual_autonomous", "dual_core"),
    ("c60", "gold_crisis_reserve", "residual2"),
    ("c60", "gold_autonomous", "dual_autonomous"),
)


def read_contract(path):
    c = json.loads(path.read_text())
    expected = {"study_id": "dual_engine_regimes_20261004", "research_only": True,
        "orders_authorized": False, "promotion_evidence": False, "new_candidate_trials": 16,
        "planned_curves": 104, "data_role": "consumed_historical_discovery_pool"}
    if any(c.get(k) != v for k, v in expected.items()):
        raise ValueError("regimes_contract_invalid")
    for line, controls, candidates, dates, costs, delays in (
        ("g20", G20_CONTROLS, G20_CANDIDATES, ("2018-04-02", "2026-07-30"), [20, 40], [1, 2]),
        ("c60", C60_CONTROLS, C60_CANDIDATES, ("2021-01-01", "2026-08-31"), [25, 50], [0, 1])):
        if (tuple(c[line]["controls"]) != controls or tuple(c[line]["candidates"]) != candidates
                or (c[line]["start"], c[line]["end"]) != dates or c[line]["cost_bps"] != costs or c[line]["delays"] != delays):
            raise ValueError("regimes_comparison_protocol_changed")
    if (c["c60"]["horizons"] != [20, 60, 90] or c["c60"]["risk_window"] != 60
            or c["c60"]["annual_volatility_cap"] != .6 or c["c60"]["core_weight"] != .7
            or c["c60"]["satellite_weight"] != .3):
        raise ValueError("regimes_core_settings_changed")
    return c


def signed_signal(panel, symbol, t):
    """Three fixed total-return horizons relative to cash; ties are zero."""
    prices, cash = panel.total_closes[symbol], panel.total_closes["BIL"]
    moves = [math.log(prices[t] / prices[t - h]) - math.log(cash[t] / cash[t - h]) for h in (21, 63, 126)]
    return stats.fmean((x > 0) - (x < 0) for x in moves)


def macro_book(panel, t, *, directional=True, risk_weighted=False):
    families = ("GLD", "DBC", "UUP", "TLT")
    signals = {s: signed_signal(panel, s, t) for s in families}
    instruments = {s: "TBF" if s == "TLT" and directional and signals[s] < 0 else s for s in families}
    raw = {s: 1 / max(stats.stdev(base.daily_returns(panel.total_closes[instruments[s]][t - 60:t + 1])), 1e-6)
           if risk_weighted else 1. for s in families}
    denominator = sum(raw.values())
    return {instruments[s]: .45 * raw[s] / denominator * (abs(signals[s]) if s == "TLT" and directional else max(0., signals[s]))
            for s in families if signals[s] > 0 or (s == "TLT" and directional and signals[s] < 0)}


def crisis_hedge(panel, t):
    """At most two sources: one equity inverse and one duration inverse."""
    scores = {s: signed_signal(panel, s, t) for s in ("SPY", "QQQ", "TLT")}
    equity = min(("SPY", "QQQ"), key=lambda s: (scores[s], s))
    names = (["SH" if equity == "SPY" else "PSQ"] if scores[equity] < 0 else [])
    if scores["TLT"] < 0:
        names.append("TBF")
    return {s: .15 / len(names) for s in names}


def equity_targets(panel, settings, rule, rates):
    if rule in G20_CONTROLS:
        return previous.equity_targets(panel, settings, rule, rates)
    if rule not in G20_CANDIDATES:
        raise ValueError("unknown_regimes_equity_rule")
    monthly = old.g20_signals(panel)
    selected, state, book = None, "normal", {}
    targets, events = {}, []
    for t in range(126, len(panel.dates) - 1):
        selection_changed = False
        if t in monthly:
            new = monthly[t]["selected"]
            selection_changed = selected != new
            selected = new
            if selection_changed:
                state = "normal"
            if rule in ("gold_short_crisis", "gold_trend_budget"):
                book = {"GLD": .2 * max(0., signed_signal(panel, "GLD", t))} if rule == "gold_trend_budget" else {"GLD": .2}
            else:
                book = macro_book(panel, t, directional=rule != "macro_long_book", risk_weighted=rule == "macro_risk_book")
        if selected is None:
            continue
        prices = panel.total_closes[G20_EXECUTION_TO_PROXY[selected]]
        next_state = state
        if rule in ("macro_long_book", "macro_directional_book", "macro_risk_book"):
            next_state = "normal"
        elif rule == "macro_joint_defense":
            joint = all(panel.total_closes[s][t] < stats.fmean(panel.total_closes[s][t - 62:t + 1])
                        and panel.total_closes[s][t] / panel.total_closes[s][t - 63] < 1 for s in ("SPY", "TLT"))
            next_state = "defensive" if joint else "normal"
        elif rule == "macro_two_speed":
            if previous.panic(prices, t):
                next_state = "defensive"
            elif previous.recovered(prices, t):
                next_state = "normal"
            elif state != "normal":
                next_state = "recovery" if previous.recovered(prices, t, fast=True) else "defensive"
        elif state == "normal" and previous.panic(prices, t):
            next_state = "defensive"
        elif state != "normal" and previous.recovered(prices, t):
            next_state = "normal"
        transition = next_state != state or selection_changed
        state = next_state
        if t not in monthly and not transition:
            continue
        budget = .2 if state == "normal" else .10 if state == "recovery" else .05
        target = {selected: budget, **book}
        hedge = crisis_hedge(panel, t) if state == "defensive" and rule in (
            "gold_short_crisis", "macro_directional_crisis", "macro_two_speed") else {}
        for s, w in hedge.items():
            target[s] = target.get(s, 0.) + w
        target["BIL"] = 1 - sum(target.values())
        targets[t] = target
        events.append({"date": panel.dates[t], "selected": selected, "state": state,
                       "transition": transition, "macro_monthly_shape": dict(book), "hedge": hedge, "target": target})
    return targets, events


def handoff_step(state, probe, *, panic, slow_recovered, fast_recovered, long_strength, fast_strength):
    """A state exit cannot cancel an unabsorbed, still-valid recovery probe."""
    if panic:
        state, probe = "defensive", False
    elif slow_recovered:
        state = "normal"
    elif state != "normal":
        state = "recovery" if fast_recovered else "defensive"
    if state == "recovery":
        probe = True
    if not fast_recovered:
        probe = False
    long_core, floor = .7 * long_strength, .3 * fast_strength if probe else 0.
    if long_core >= floor:
        probe = False
    core = .25 * long_strength if state == "defensive" else max(long_core, floor)
    return state, probe, core


def asset_at(assets, symbol, t):
    matches = [a for a in assets.values() if a.symbol == symbol and a.window(t) is not None]
    if len(matches) > 1:
        raise ValueError("overlapping_asset_segments")
    return matches[0] if matches else None


def crypto_targets(axis, assets, settings, rule):
    if rule in C60_CONTROLS:
        return previous.crypto_targets(axis, assets, settings, rule, {})
    if rule not in C60_CANDIDATES:
        raise ValueError("unknown_regimes_crypto_rule")
    btc = next(a for a in assets.values() if a.symbol == "BTCUSDT")
    first = next(t for t in range(len(axis.dates)) if btc.window(t) is not None)
    selected, targets, events, state, probe = (), {}, {}, "normal", False
    dual = rule in ("dual_core", "dual_autonomous", "gold_autonomous")
    autonomous = rule in ("autonomous_satellites", "dual_autonomous", "gold_autonomous")
    for t in range(first, len(axis.dates)):
        market, local = btc.window(t), t - btc.start
        day = dt.date.fromisoformat(axis.dates[t])
        monthly = (day + dt.timedelta(days=1)).day == 1
        detail = None
        if monthly:
            # Excluding ETH before PIT selection gives dual-core rules an explicit
            # alternative universe; it is recorded, not an unnoticed duplicate.
            pool = {k: a for k, a in assets.items() if not (dual and a.symbol == "ETHUSDT")}
            selected, detail = previous.select_satellites(pool, t, market, axis.dates[t], "residual2", {})
        long_strength = base.trend_score(market, settings["horizons"])
        fast_strength = base.trend_score(market, (5, 10, 20))
        panic = previous.panic(btc.closes, local, crypto=True)
        slow = previous.recovered(btc.closes, local)
        fast = previous.recovered(btc.closes, local, fast=True)
        old_state, old_probe = state, probe
        if rule in ("handoff_core", "handoff_source"):
            state, probe, core = handoff_step(state, probe, panic=panic, slow_recovered=slow,
                fast_recovered=fast, long_strength=long_strength, fast_strength=fast_strength)
        else:
            state = "defensive" if panic else "normal" if slow else ("recovery" if fast else "defensive") if state != "normal" else state
            core = .7 * long_strength
        if rule == "continuous_two_speed":
            core = .7 * (.5 * long_strength + .5 * fast_strength)
        if dual:
            core = .5 * long_strength
        if rule == "gold_crisis_reserve" and state != "normal":
            core = .25 * long_strength
        pre = {btc.asset_id: core}
        if dual:
            eth = asset_at(assets, "ETHUSDT", t)
            if eth is not None:
                pre[eth.asset_id] = .2 * base.trend_score(eth.window(t), settings["horizons"])
        cut_satellite = (rule == "handoff_source" or rule == "gold_crisis_reserve") and state != "normal"
        if not cut_satellite:
            satellite_budget = .2 if rule == "gold_autonomous" else .3
            for k in selected:
                window = assets[k].window(t)
                if window is not None:
                    pre[k] = satellite_budget / 2 * (1. if autonomous else long_strength) * base.trend_score(window, settings["horizons"])
        gold_budget = .1 if rule == "gold_autonomous" else .2 if rule == "gold_crisis_reserve" and state != "normal" else 0.
        gold = asset_at(assets, "PAXGUSDT", t) if gold_budget else None
        if gold is not None:
            pre[gold.asset_id] = gold_budget * base.trend_score(gold.window(t), settings["horizons"])
        pre = {k: w for k, w in pre.items() if w > 0}
        returns = {k: base.daily_returns(assets[k].window(t, settings["risk_window"] + 1)) for k in pre}
        scale = min(1., settings["annual_volatility_cap"] / max(base.portfolio_sigma(returns, pre, 365), 1e-6))
        targets[t] = {k: w * scale for k, w in pre.items()}
        # Daily state/core traces are evidence for handoff continuity and sleeve
        # decomposition; monthly selections remain fixed between month ends.
        events[t] = {"date": axis.dates[t], "state": state, "probe_active": probe,
            "transition": state != old_state, "probe_changed": probe != old_probe,
            "long_strength": long_strength, "fast_strength": fast_strength,
            "core_before_risk_cap": core, "pre_risk_target": pre, "risk_scale": scale,
            "selection": detail, "selected": selected, "target": targets[t]}
    return targets, events


def prepare_opens(*, contract_path, pit_cache, prior_open_roots, out):
    ex.require_storage(out)
    c = read_contract(contract_path)
    raw, _ = load_cache(pit_cache)
    axis, assets = old.build_crypto_assets(raw)
    priors = [(root, verify_manifest(root)) for root in prior_open_roots]
    needed = {}
    for rule in C60_CONTROLS + C60_CANDIDATES:
        targets, _ = crypto_targets(axis, assets, c["c60"], rule)
        for t, weights in targets.items():
            for delay in c["c60"]["delays"]:
                for i in (t + 1 + delay, t + 2 + delay):
                    if i < len(axis.dates) and axis.dates[i] >= c["c60"]["start"]:
                        for k in weights:
                            if assets[k].has(i):
                                needed.setdefault(assets[k].symbol, set()).add(axis.dates[i][:7])
        print(json.dumps({"open_coverage_rule": rule, "symbols": len(needed)}), flush=True)
    out.mkdir(parents=True, exist_ok=False)
    (out / "archives").mkdir()
    for symbol, months in needed.items():
        for month in months:
            name = f"archives/{symbol}-1d-{month}.zip"
            for root, files in priors:
                if name in files:
                    (out / name).write_bytes((root / name).read_bytes())
                    break
    return acquire_opens(pit_cache, out, symbols=sorted(needed), months_by_symbol=needed, workers=16)


def run_study(*, contract_path, prior_contract, equity_root, pit_cache, expansion_root, rates_root,
              inverse_root, tail_root, open_root, prior_results, out, repo):
    ex.require_storage(out)
    c = read_contract(contract_path)
    if out.exists():
        raise ValueError("immutable_result_exists")
    panel, equity_audit = old.load_equity(equity_root, old.read_contract(prior_contract))
    raw, hashes = load_cache(pit_cache)
    verify_manifest(prior_results)
    prior_audit = json.loads((prior_results / "input-audit.json").read_text())
    if hashes != prior_audit["cache_sha256"] or equity_audit["files"] != prior_audit["equity"]["files"]:
        raise ValueError("prior_input_identity_changed")
    panel = load_inverse(load_tail(load_macro(panel, expansion_root), tail_root), inverse_root)
    rates = load_rates(rates_root, panel.dates)
    axis, assets = old.build_crypto_assets(raw)
    opens, open_files = read_opens(open_root)
    eq_close = {s: dict(zip(panel.dates, p, strict=True)) for s, p in panel.total_closes.items()}
    eq_open = {s: dict(zip(panel.dates, p, strict=True)) for s, p in panel.total_opens.items()}
    cr_close, cr_open = base.crypto_prices(axis, assets, opens)
    btc = next(k for k, a in assets.items() if a.symbol == "BTCUSDT")
    out.mkdir(parents=True)
    old.write_json(out / "contract.json", c)
    audit = {"equity": equity_audit, "cache_sha256": hashes, "open_files": open_files,
        "input_files": {name: verify_manifest(root) for name, root in (
            ("expansion", expansion_root), ("rates", rates_root), ("inverse", inverse_root), ("tail", tail_root))},
        "paths": {k: str(v) for k, v in {"equity_root": equity_root, "pit_cache": pit_cache,
            "expansion_root": expansion_root, "rates_root": rates_root, "inverse_root": inverse_root,
            "tail_root": tail_root, "open_root": open_root}.items()},
        "prior_result_manifest_sha256": old.file_hash(prior_results / "manifest.json"),
        "contract_sha256": old.file_hash(contract_path)}
    old.write_json(out / "input-audit.json", audit)
    runs, summaries, exposures, checks, attribution = {}, {"g20": {}, "c60": {}}, [], {}, {}
    for line, rules, dates, closes, opns, annual in (
        ("g20", G20_CONTROLS + G20_CANDIDATES, panel.dates, eq_close, eq_open, 252),
        ("c60", C60_CONTROLS + C60_CANDIDATES, axis.dates, cr_close, cr_open, 365)):
        for rule in rules:
            targets, members = (equity_targets(panel, c[line], rule, rates) if line == "g20" else
                                crypto_targets(axis, assets, c[line], rule))
            old.write_json(out / f"{line}-{rule}-targets.json", targets)
            old.write_json(out / f"{line}-{rule}-selection.json", members)
            for cost in c[line]["cost_bps"]:
                for delay in c[line]["delays"]:
                    cell = f"c{cost}-d{delay}"
                    aims = dict(targets)
                    if line == "g20":
                        first = next(i for i, d in enumerate(dates) if d >= c[line]["start"])
                        aims.setdefault(first - delay, {"BIL": 1.0})
                    run = base.replay_units(dates, closes, opns, aims, start=c[line]["start"],
                        lag=delay if line == "g20" else 1 + delay, cost_bps=cost, cash_asset="BIL" if line == "g20" else None)
                    key = f"{line}-{rule}-{cell}"
                    runs[key] = run
                    old.write_json(out / f"{key}-ledger.json", run)
                    result = old.summarize(run, annual)
                    result["mean_risk_gross"] = stats.fmean(r["risk_gross"] for r in run["records"])
                    result["max_risk_gross"] = max(r["risk_gross"] for r in run["records"])
                    summaries[line].setdefault(rule, {})[cell] = result
                    exposures.append({"curve": key, "role": "candidate" if rule in G20_CANDIDATES + C60_CANDIDATES else "control"})
                    if cell in (("c20-d1", "c40-d2") if line == "g20" else ("c25-d0", "c50-d1")):
                        attribution[key] = ex.contributions(run, dates, closes, opns, annual=annual, market="SPY" if line == "g20" else btc)
                    if rule in (G20_CONTROLS if line == "g20" else C60_CONTROLS):
                        prior = json.loads((prior_results / f"{key}-ledger.json").read_text())
                        if [r["date"] for r in run["records"]] != [r["date"] for r in prior["records"]]:
                            raise ValueError("baseline_dates_changed")
                        error = max(abs(r["return"] - s["return"]) for r, s in zip(run["records"], prior["records"], strict=True))
                        if error > 1e-12:
                            raise ValueError(f"baseline_reproduction_failed:{key}:{error}")
                        checks[key] = error
            print(json.dumps({"replayed": line + "-" + rule}), flush=True)
    pairs = list(dict.fromkeys(PAIRS + tuple(
        (line, r, "aware_gold_rotate" if line == "g20" else "residual2")
        for line, rules in (("g20", G20_CANDIDATES), ("c60", C60_CANDIDATES)) for r in rules)))
    contrasts = {}
    for line, rule, reference in pairs:
        for cell in (("c20-d1", "c40-d2") if line == "g20" else ("c25-d0", "c50-d1")):
            a, b = runs[f"{line}-{rule}-{cell}"], runs[f"{line}-{reference}-{cell}"]
            contrasts[f"{line}-{rule}-vs-{reference}-{cell}"] = {
                "paired": ex.paired_fast(a, b, annual=252 if line == "g20" else 365, settings=c["paired_bootstrap"]),
                "same_baseline_best_year_exclusion": paired_year_exclusion(a, b, annual=252 if line == "g20" else 365)}
    crises = {key: {name: ex.window_summary(run, first, last, 252 if key.startswith("g20-") else 365)
              for name, (first, last) in c["crisis_windows"][key.split("-")[0]].items()} for key, run in runs.items()}
    sources = {repo / "scripts/research/dual_engine_regimes.py", repo / "config/dual-engine-regimes-20261004.json"}
    for name, module in tuple(sys.modules.items()):
        path = Path(module.__file__).resolve() if getattr(module, "__file__", None) else None
        if name.startswith("qount") and path and path.suffix == ".py":
            if not path.is_relative_to(repo.resolve() / "src"):
                raise ValueError("source_outside_public_delivery")
            sources.add(path)
    source_hashes = {}
    for path in sorted(sources):
        relative = path.relative_to(repo)
        saved = out / "source" / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(path.read_bytes())
        source_hashes[str(relative)] = old.file_hash(path)
    result = {"study_id": c["study_id"], "research_only": True, "orders_authorized": False,
        "promotion_evidence": False, "data_role": c["data_role"], "summaries": summaries, "contrasts": contrasts,
        "baseline_reproduction": checks, "attribution": attribution, "crisis_windows": crises,
        "source_sha256": source_hashes, "curve_exposures": exposures, "candidate_trials": c["new_candidate_trials"],
        "global_trial_count": None, "dsr_pbo": c["dsr_pbo"]}
    if len(exposures) != c["planned_curves"]:
        raise ValueError("curve_inventory_mismatch")
    old.write_json(out / "results.json", result)
    old.write_json(out / "manifest.json", {"research_only": True, "orders_authorized": False,
        "files": {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}})
    return result
