"""Frozen major redesigns: source-aware crises, recovery, insurance and supply.

Historical discovery only; does not import runtime control or submit orders.
"""
from __future__ import annotations
import datetime as dt
import json
import statistics as stats
import sys
from pathlib import Path
from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
from qount.research import dual_engine_optimization as old
from qount.research import dual_engine_structural as base
from qount.research import dual_engine_expansion as ex
from qount.research.dual_engine_execution_study import load_cache, read_opens, verify_manifest, paired_year_exclusion
from qount.research.dual_engine_expansion_data import load_macro, load_rates
from qount.research.dual_engine_nextgen_data import supply_features, load_tail
from qount.research.c60_execution_control import acquire_opens

G20_CONTROLS = ("g20", "gold20", "macro_trend", "macro_fund", "crisis_rotation")
G20_CANDIDATES = ("aware_gold_cash", "aware_gold_rotate", "aware_macro_cash", "aware_macro_rotate",
                  "source_selective_macro", "gold_recovery", "gold_tail5", "gold_tail_static5")
C60_CONTROLS = ("residual2", "btc_continuous", "core_only", "supply_covered2", "fee_covered2")
C60_CANDIDATES = ("crisis_core_cash", "crisis_satellite_cash", "recovery_core", "recovery_source",
                  "supply_gate2", "supply_rank2", "supply_recovery", "fee_density2")


def read_contract(path):
    c = json.loads(path.read_text())
    if (c.get("study_id") != "dual_engine_nextgen_20261004" or c.get("research_only") is not True
            or c.get("orders_authorized") is not False or c.get("promotion_evidence") is not False
            or c.get("new_candidate_trials") != 16 or c.get("planned_curves") != 104
            or tuple(c["g20"]["candidates"]) != G20_CANDIDATES or tuple(c["g20"]["controls"]) != G20_CONTROLS
            or tuple(c["c60"]["candidates"]) != C60_CANDIDATES or tuple(c["c60"]["controls"]) != C60_CONTROLS):
        raise ValueError("nextgen_contract_invalid")
    return c


def panic(prices, t, *, crypto=False):
    draw = prices[t] / max(prices[t - 63:t + 1]) - 1
    r5 = prices[t] / prices[t - 5] - 1
    return (draw < (-.15 if crypto else -.08) and r5 < (-.10 if crypto else -.04)) or r5 < (-.15 if crypto else -.08)


def recovered(prices, t, *, fast=False):
    n, h = (10, 5) if fast else (20, 21)
    return prices[t] > stats.fmean(prices[t - n + 1:t + 1]) and prices[t] / prices[t - h] > 1


def inflation_class(panel, t, rates):
    real, inflation = ex.rate_change(rates, "DFII10", t), ex.rate_change(rates, "T10YIE", t)
    return "inflation" if panel.total_closes["IEF"][t] / panel.total_closes["IEF"][t - 63] < 1 and (
        (real is not None and real > 0) or (inflation is not None and inflation > 0)) else "deflation"


def equity_targets(panel, settings, rule, rates):
    if rule in G20_CONTROLS:
        return ex.equity_targets(panel, settings, rule, rates)
    if rule not in G20_CANDIDATES:
        raise ValueError("unknown_nextgen_equity_rule")
    monthly = old.g20_signals(panel)
    targets, events, selected, macro = {}, [], None, {}
    state, regime = "normal", None
    for t in range(126, len(panel.dates) - 1):
        changed_selection = False
        if t in monthly:
            new = monthly[t]["selected"]
            changed_selection = selected != new
            selected = new
            if changed_selection:
                state, regime = "normal", None
            macro = ex.macro_allocation(ex.macro_scores(panel, t)) if "macro" in rule else {"GLD": .2}
        if selected is None:
            continue
        prices = panel.total_closes[G20_EXECUTION_TO_PROXY[selected]]
        entered = panic(prices, t)
        if rule == "gold_tail_static5":
            entered = False
        if rule == "source_selective_macro":
            entered = panic(panel.total_closes["SPY"], t) and prices[t] / prices[t - 21] < 1 and prices[t] < stats.fmean(prices[t - 19:t + 1])
        next_state = state
        if state == "normal" and entered:
            next_state, regime = "defensive", inflation_class(panel, t, rates)
        elif state != "normal" and recovered(prices, t, fast=rule == "gold_recovery"):
            next_state = "normal"
        transition = next_state != state or changed_selection
        state = next_state
        if not (t in monthly or transition):
            continue
        tail = rule in ("gold_tail5", "gold_tail_static5")
        equity_budget = .2 if tail or state == "normal" else .05
        target = {selected: equity_budget, **macro}
        if rule.endswith("_rotate") and state != "normal":
            scores = ex.macro_scores(panel, t)
            names = ("GLD", "DBC", "UUP") if regime == "inflation" else ("IEF", "TLT")
            eligible = [s for s in names if scores[s] > 0]
            for s in eligible:
                target[s] = target.get(s, 0) + .15 / len(eligible)
        if rule == "gold_tail_static5" or (rule == "gold_tail5" and state != "normal"):
            target["VIXY"] = .05
        target["BIL"] = 1 - sum(target.values())
        targets[t] = target
        events.append({"date": panel.dates[t], "selected": selected, "state": state, "regime": regime,
                       "transition": transition, "target": target, "monthly_macro_shape": dict(macro)})
    return targets, events


def select_satellites(assets, t, market, day, rule, supply):
    universe = [k for k in base.pit.pit_universe(assets, t) if assets[k].symbol not in ("BTCUSDT", "PAXGUSDT")]
    scores = {k: base.relative_strength(assets[k].window(t), market)["score"] for k in universe}
    positive = [k for k in universe if scores[k] > 0]
    features = {k: supply_features(supply.get(assets[k].symbol, {}), day) for k in positive}
    covered = [k for k in positive if features[k] is not None]
    eligible = positive
    if rule.startswith("supply_") or rule == "fee_covered2" or rule == "fee_density2":
        eligible = covered
    if rule in ("fee_covered2", "fee_density2"):
        eligible = [k for k in covered if features[k]["fee_density_growth"] is not None]
    if rule in ("supply_gate2", "supply_recovery"):
        btc = supply_features(supply.get("BTCUSDT", {}), day)
        eligible = [k for k in covered if btc is not None and features[k]["issued_growth30"] <= btc["issued_growth30"]]
    if rule in ("supply_rank2", "fee_density2"):
        residual = ex.percentile({k: scores[k] for k in eligible})
        dilution = ex.percentile({k: -features[k]["issued_growth30"] for k in eligible})
        density = ex.percentile({k: features[k]["fee_density_growth"] for k in eligible}) if rule == "fee_density2" else {}
        scores = {k: residual[k] + .5 * dilution[k] + (.5 * density[k] if density else 0) for k in eligible}
    selected = tuple(sorted(eligible, key=lambda k: (-scores[k], k))[:2])
    return selected, {"universe": universe, "positive_relative": positive, "covered": covered,
                       "eligible": eligible, "selected": selected, "supply_features": features}


def crypto_targets(axis, assets, settings, rule, supply):
    if rule in ("residual2", "btc_continuous", "core_only"):
        return ex.crypto_targets(axis, assets, settings, rule, {})
    if rule not in C60_CONTROLS + C60_CANDIDATES:
        raise ValueError("unknown_nextgen_crypto_rule")
    btc = next(a for a in assets.values() if a.symbol == "BTCUSDT")
    first = next(t for t in range(len(axis.dates)) if btc.window(t) is not None)
    selected, targets, events, state = (), {}, {}, "normal"
    for t in range(first, len(axis.dates)):
        market = btc.window(t)
        prices = btc.closes
        local = t - btc.start
        day = dt.date.fromisoformat(axis.dates[t])
        monthly = (day + dt.timedelta(days=1)).day == 1
        if monthly:
            selected, detail = select_satellites(assets, t, market, axis.dates[t], rule, supply)
        next_state = state
        if panic(prices, local, crypto=True):
            next_state = "defensive"
        elif recovered(prices, local):
            next_state = "normal"
        elif state != "normal":
            next_state = "recovery" if recovered(prices, local, fast=True) else "defensive"
        transition = next_state != state
        state = next_state
        strength = base.trend_score(market, settings["horizons"])
        core = settings["core_weight"] * strength
        if rule == "crisis_core_cash" and state != "normal":
            core = .25 * strength
        fast_core = rule in ("recovery_core", "recovery_source", "supply_recovery")
        if fast_core and state == "defensive":
            core = .25 * strength
        if fast_core and state == "recovery":
            core = max(core, .30 * base.trend_score(market, (5, 10, 20)))
        pre = {btc.asset_id: core}
        cut_satellite = (rule == "crisis_satellite_cash" and state != "normal") or (
            rule in ("recovery_source", "supply_recovery") and state != "normal")
        if not cut_satellite:
            for k in selected:
                window = assets[k].window(t)
                if window is not None:
                    pre[k] = settings["satellite_weight"] / 2 * strength * base.trend_score(window, settings["horizons"])
        pre = {k: w for k, w in pre.items() if w > 0}
        returns = {k: base.daily_returns(assets[k].window(t, settings["risk_window"] + 1)) for k in pre}
        scale = min(1.0, settings["annual_volatility_cap"] / max(base.portfolio_sigma(returns, pre, 365), 1e-6))
        targets[t] = {k: w * scale for k, w in pre.items()}
        if monthly or transition:
            events[t] = {"date": axis.dates[t], "state": state, "transition": transition,
                         "target": targets[t], "selection": detail if monthly else None}
    return targets, events


def prepare_opens(*, contract_path, pit_cache, supply_root, prior_open_roots, out):
    ex.require_storage(out)
    c = read_contract(contract_path)
    verify_manifest(supply_root)
    supply = json.loads((supply_root / "supply.json").read_text())
    raw, _ = load_cache(pit_cache)
    axis, assets = old.build_crypto_assets(raw)
    priors = [(root, verify_manifest(root)) for root in prior_open_roots]
    needed = {}
    for rule in C60_CONTROLS + C60_CANDIDATES:
        targets, _ = crypto_targets(axis, assets, c["c60"], rule, supply)
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
              supply_root, tail_root, open_root, prior_results, out, repo):
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
    panel = load_tail(load_macro(panel, expansion_root), tail_root)
    rates = load_rates(rates_root, panel.dates)
    verify_manifest(supply_root)
    supply = json.loads((supply_root / "supply.json").read_text())
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
            ("expansion", expansion_root), ("rates", rates_root), ("supply", supply_root), ("tail", tail_root))},
        "paths": {k: str(v) for k, v in {"equity_root": equity_root, "pit_cache": pit_cache,
            "expansion_root": expansion_root, "rates_root": rates_root, "supply_root": supply_root,
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
                                crypto_targets(axis, assets, c[line], rule, supply))
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
                    if rule in G20_CONTROLS or rule in ("residual2", "btc_continuous", "core_only"):
                        prior = json.loads((prior_results / f"{key}-ledger.json").read_text())
                        if [r["date"] for r in run["records"]] != [r["date"] for r in prior["records"]]:
                            raise ValueError("baseline_dates_changed")
                        error = max(abs(r["return"] - s["return"]) for r, s in zip(run["records"], prior["records"], strict=True))
                        if error > 1e-12:
                            raise ValueError(f"baseline_reproduction_failed:{key}:{error}")
                        checks[key] = error
            print(json.dumps({"replayed": line + "-" + rule}), flush=True)
    comparisons = {"g20": {r: "macro_trend" if "macro" in r else "gold20" for r in G20_CANDIDATES},
        "c60": {r: ("supply_covered2" if r in ("supply_gate2", "supply_rank2") else
                    "fee_covered2" if r == "fee_density2" else "residual2") for r in C60_CANDIDATES}}
    # Matched interventions separate the supply/recovery interaction and cash/rotation.
    pairs = [(line, r, ref) for line, rules in comparisons.items() for r, ref in rules.items()] + [
        ("g20", "aware_gold_rotate", "aware_gold_cash"), ("g20", "aware_macro_rotate", "aware_macro_cash"),
        ("c60", "supply_recovery", "supply_gate2"), ("c60", "supply_recovery", "recovery_source")]
    contrasts = {}
    for line, rule, reference in pairs:
        for cell in (("c20-d1", "c40-d2") if line == "g20" else ("c25-d0", "c50-d1")):
            a, b = runs[f"{line}-{rule}-{cell}"], runs[f"{line}-{reference}-{cell}"]
            contrasts[f"{line}-{rule}-vs-{reference}-{cell}"] = {
                "paired": ex.paired_fast(a, b, annual=252 if line == "g20" else 365, settings=c["paired_bootstrap"]),
                "same_baseline_best_year_exclusion": paired_year_exclusion(a, b, annual=252 if line == "g20" else 365)}
    crises = {key: {name: ex.window_summary(run, first, last, 252 if key.startswith("g20-") else 365)
              for name, (first, last) in c["crisis_windows"][key.split("-")[0]].items()} for key, run in runs.items()}
    sources = {repo / "scripts/research/dual_engine_nextgen.py", repo / "config/dual-engine-nextgen-20261004.json"}
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
