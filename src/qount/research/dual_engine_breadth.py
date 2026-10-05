"""Seventh-round frozen research: causal core/pool ablations and risk families.

All positions use actual long instrument units; no orders or runtime interfaces.
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
from qount.research import dual_engine_regimes as sixth
from qount.research.dual_engine_expansion_data import load_macro, load_rates
from qount.research.dual_engine_execution_study import load_cache, read_opens, verify_manifest, paired_year_exclusion
from qount.research.dual_engine_nextgen_data import load_tail
from qount.research.dual_engine_regimes_data import load_inverse
from qount.research.c60_execution_control import acquire_opens

G20_CONTROLS = ("aware_gold_cash", "aware_gold_rotate", "macro_fund", "gold_short_crisis")
G20_CANDIDATES = ("gold_clock_inverse", "gold_clock_macro", "sector3_cash", "sector3_guard", "sector3_inverse", "sector3_macro")
C60_CONTROLS = ("residual2", "dual_core", "core_only")
C60_CANDIDATES = ("btc_pool_ex_eth", "dual_pool_all", "dual_sat4", "dual_sat4_risk", "dual_sat4_publicgate", "family_gold", "family_gold_publicgate", "crisis_gold_transfer")
PAIRS = (
    ("g20", "gold_clock_inverse", "gold_short_crisis"),
    ("g20", "gold_clock_macro", "aware_gold_rotate"),
    ("g20", "sector3_cash", "aware_gold_cash"),
    ("g20", "sector3_guard", "sector3_cash"),
    ("g20", "sector3_inverse", "sector3_guard"),
    ("g20", "sector3_macro", "sector3_guard"),
    ("c60", "btc_pool_ex_eth", "residual2"),
    ("c60", "dual_pool_all", "residual2"),
    ("c60", "dual_core", "btc_pool_ex_eth"),
    ("c60", "dual_core", "dual_pool_all"),
    ("c60", "dual_sat4", "dual_core"),
    ("c60", "dual_sat4_risk", "dual_sat4"),
    ("c60", "dual_sat4_publicgate", "dual_sat4"),
    ("c60", "family_gold", "dual_sat4"),
    ("c60", "family_gold_publicgate", "family_gold"),
    ("c60", "crisis_gold_transfer", "dual_sat4"),
)


def read_contract(path):
    c = json.loads(path.read_text())
    expected = {"study_id": "dual_engine_breadth_20261005", "research_only": True,
        "orders_authorized": False, "promotion_evidence": False, "new_candidate_trials": 14,
        "planned_curves": 84, "data_role": "consumed_historical_discovery_pool"}
    if any(c.get(k) != v for k, v in expected.items()):
        raise ValueError("breadth_contract_invalid")
    for line, controls, candidates, dates, costs, delays in (
        ("g20", G20_CONTROLS, G20_CANDIDATES, ("2018-04-02", "2026-07-30"), [20, 40], [1, 2]),
        ("c60", C60_CONTROLS, C60_CANDIDATES, ("2021-01-01", "2026-08-31"), [25, 50], [0, 1])):
        if (tuple(c[line]["controls"]) != controls or tuple(c[line]["candidates"]) != candidates
                or (c[line]["start"], c[line]["end"]) != dates or c[line]["cost_bps"] != costs or c[line]["delays"] != delays):
            raise ValueError("breadth_comparison_protocol_changed")
    if (c["c60"]["horizons"] != [20, 60, 90] or c["c60"]["risk_window"] != 60
            or c["c60"]["annual_volatility_cap"] != .6 or c["c60"]["core_weight"] != .7
            or c["c60"]["satellite_weight"] != .3):
        raise ValueError("breadth_core_settings_changed")
    return c


def fast_direction(prices, t, sign):
    return sign * (prices[t] / prices[t - 5] - 1) > 0 and sign * (prices[t] - stats.fmean(prices[t - 9:t + 1])) > 0


def protection_book(panel, t, budget, kind):
    """Daily source permission, independent of held-sector recovery state."""
    if budget <= 0:
        return {}
    if kind == "inverse":
        eligible = [s for s in ("SPY", "QQQ") if sixth.signed_signal(panel, s, t) < 0 and fast_direction(panel.total_closes[s], t, -1)]
        names = []
        if eligible:
            source = min(eligible, key=lambda s: (sixth.signed_signal(panel, s, t), s))
            names.append("SH" if source == "SPY" else "PSQ")
        if sixth.signed_signal(panel, "TLT", t) < 0 and fast_direction(panel.total_closes["TLT"], t, -1):
            names.append("TBF")
    elif kind == "macro":
        names = [s for s in ("GLD", "DBC", "UUP", "TLT")
                 if sixth.signed_signal(panel, s, t) > 0 and fast_direction(panel.total_closes[s], t, 1)]
        if sixth.signed_signal(panel, "TLT", t) < 0 and fast_direction(panel.total_closes["TLT"], t, -1):
            names.append("TBF")
    else:
        raise ValueError("unknown_protection_kind")
    return {s: budget / len(names) for s in names}


def equity_targets(panel, settings, rule, rates):
    if rule in G20_CONTROLS:
        return sixth.equity_targets(panel, settings, rule, rates)
    if rule not in G20_CANDIDATES:
        raise ValueError("unknown_breadth_equity_rule")
    monthly = old.g20_signals(panel)
    selected, states, targets, events, last_target = (), {}, {}, [], None
    broad = rule.startswith("sector3_")
    for t in range(126, len(panel.dates) - 1):
        if t in monthly:
            ranked = sorted(G20_EXECUTION_TO_PROXY, key=lambda s: (
                -(panel.closes[G20_EXECUTION_TO_PROXY[s]][t] / panel.closes[G20_EXECUTION_TO_PROXY[s]][t - 63] - 1), s))
            selected = tuple(ranked[:3]) if broad else (monthly[t]["selected"],)
            states = {s: states.get(s, "normal") for s in selected}
        if not selected:
            continue
        target, old_states = {"GLD": .2}, dict(states)
        for s in selected:
            prices = panel.total_closes[G20_EXECUTION_TO_PROXY[s]]
            if rule == "sector3_cash":
                states[s] = "normal"
            elif states[s] == "normal" and previous.panic(prices, t):
                states[s] = "defensive"
            elif states[s] != "normal" and previous.recovered(prices, t):
                states[s] = "normal"
            target[s] = (.2 if states[s] == "normal" else .05) / len(selected)
        released = .2 - sum(target[s] for s in selected)
        kind = "inverse" if rule.endswith("inverse") else "macro" if rule.endswith("macro") else None
        book = protection_book(panel, t, released, kind) if kind else {}
        for s, w in book.items():
            target[s] = target.get(s, 0.) + w
        target["BIL"] = 1 - sum(target.values())
        # Monthly refresh is retained. Between refreshes only a changed state or
        # discrete source membership changes the target; there is no drift reset.
        if t not in monthly and target == last_target:
            continue
        targets[t], last_target = target, target
        events.append({"date": panel.dates[t], "selected": selected, "states": dict(states),
            "state_changed": states != old_states, "released_equity_budget": released,
            "protection": book, "target": target})
    return targets, events


def satellite_selection(assets, t, market, *, exclude_eth, slots):
    pool = {k: a for k, a in assets.items() if not (exclude_eth and a.symbol == "ETHUSDT")}
    universe = [k for k in base.pit.pit_universe(pool, t) if assets[k].symbol not in ("BTCUSDT", "PAXGUSDT")]
    scores = {k: base.relative_strength(assets[k].window(t), market)["score"] for k in universe}
    selected = tuple(sorted((k for k in universe if scores[k] > 0), key=lambda k: (-scores[k], k))[:slots])
    return selected, {"universe": universe, "scores": scores, "selected": selected, "slots": slots, "exclude_eth": exclude_eth}


def crypto_targets(axis, assets, settings, rule):
    if rule in C60_CONTROLS:
        return sixth.crypto_targets(axis, assets, settings, rule)
    if rule not in C60_CANDIDATES:
        raise ValueError("unknown_breadth_crypto_rule")
    btc = next(a for a in assets.values() if a.symbol == "BTCUSDT")
    first = next(t for t in range(len(axis.dates)) if btc.window(t) is not None)
    selected, shares, targets, events = (), {}, {}, {}
    single = rule == "btc_pool_ex_eth"
    slots = 2 if rule in ("btc_pool_ex_eth", "dual_pool_all") else 4
    family = rule in ("family_gold", "family_gold_publicgate")
    for t in range(first, len(axis.dates)):
        market = btc.window(t)
        day = dt.date.fromisoformat(axis.dates[t])
        detail = None
        if (day + dt.timedelta(days=1)).day == 1:
            selected, detail = satellite_selection(assets, t, market, exclude_eth=rule != "dual_pool_all", slots=slots)
            raw = {k: 1 / max(stats.stdev(base.daily_returns(assets[k].window(t, 61))), 1e-6)
                   if rule == "dual_sat4_risk" else 1. for k in selected}
            denominator = sum(raw.values())
            shares = {k: .3 * len(selected) / slots * v / denominator for k, v in raw.items()}
        strength = base.trend_score(market, settings["horizons"])
        eth = sixth.asset_at(assets, "ETHUSDT", t)
        eth_strength = base.trend_score(eth.window(t), settings["horizons"]) if eth is not None else 0.
        gate = max(strength, eth_strength) if rule.endswith("publicgate") else strength
        core = (.7 if single else .35 if family else .5) * strength
        pre = {btc.asset_id: core}
        if not single and eth is not None:
            pre[eth.asset_id] = .2 * eth_strength
        for k in selected:
            window = assets[k].window(t)
            if window is not None:
                # Add, rather than overwrite: ETH may explicitly occupy both
                # core and satellite sleeves in the dual_pool_all factorial cell.
                pre[k] = pre.get(k, 0.) + shares[k] * gate * base.trend_score(window, settings["horizons"])
        gold_budget = .15 if family else .3 * (1 - strength) if rule == "crisis_gold_transfer" else 0.
        gold = sixth.asset_at(assets, "PAXGUSDT", t) if gold_budget else None
        if gold is not None:
            pre[gold.asset_id] = gold_budget * base.trend_score(gold.window(t), settings["horizons"])
        pre = {k: w for k, w in pre.items() if w > 0}
        returns = {k: base.daily_returns(assets[k].window(t, settings["risk_window"] + 1)) for k in pre}
        scale = min(1., settings["annual_volatility_cap"] / max(base.portfolio_sigma(returns, pre, 365), 1e-6))
        targets[t] = {k: w * scale for k, w in pre.items()}
        events[t] = {"date": axis.dates[t], "long_strength": strength, "eth_strength": eth_strength,
            "satellite_gate": gate, "satellite_shares": shares, "core_before_risk_cap": core,
            "gold_budget": gold_budget, "pre_risk_target": pre, "risk_scale": scale,
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
        (line, r, "aware_gold_rotate" if line == "g20" else "dual_core")
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
    sources = {repo / "scripts/research/dual_engine_breadth.py", repo / "config/dual-engine-breadth-20261005.json"}
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
