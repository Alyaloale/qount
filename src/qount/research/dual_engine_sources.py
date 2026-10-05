"""Eleventh-round external information interventions and source qualification."""
from __future__ import annotations
import json
import statistics as stats
import sys
from pathlib import Path
from qount.research import dual_engine_optimization as old
from qount.research import dual_engine_structural as base
from qount.research import dual_engine_expansion as ex
from qount.research import dual_engine_reform as ninth
from qount.research import dual_engine_renewal as tenth
from qount.research.dual_engine_information_data import funding_feature, flow_feature, macro_features
from qount.research.dual_engine_capital import capital_contributions
from qount.research.dual_engine_registry import POLICY
from qount.research.dual_engine_holdings import analyze_units
from qount.research.dual_engine_expansion_data import load_macro, load_rates
from qount.research.dual_engine_execution_study import load_cache, read_opens, verify_manifest, paired_year_exclusion
from qount.research.dual_engine_nextgen_data import load_tail
from qount.research.dual_engine_regimes_data import load_inverse

G20_CONTROLS = ('aware_gold_rotate', 'capital_reset_sector')
G20_CANDIDATES = ('nfci_cash', 'credit_cash', 'credit_gold', 'curve_credit')
C60_CONTROLS = ('staged_risk4', 'dual_sat4_risk', 'fresh_units_risk4')
C60_CANDIDATES = ('funding_core', 'funding_all', 'flow_entry', 'funding_flow')
G20_SOURCES = {r: 'aware_gold_rotate' for r in G20_CANDIDATES}
C60_SOURCES = {r: 'staged_risk4' for r in C60_CANDIDATES}
PAIRS = (('g20', 'credit_gold', 'credit_cash'), ('g20', 'curve_credit', 'credit_cash'),
         ('c60', 'funding_all', 'funding_core'), ('c60', 'funding_flow', 'funding_all'), ('c60', 'funding_flow', 'flow_entry'))
MECHANISMS = {'c60': {'funding_core': 'half BTC/ETH original core targets individually when own positive 7-day mean daily settled rate ranks at or above75th percentile of preceding180 seven-day means; satellites unchanged', 'funding_all': 'half all original spot risk targets if either BTC or ETH is crowded by the same funding rule', 'flow_entry': 'original BTC/ETH targets require own prior20-day quote-weighted taker imbalance>0; satellites require BTC imbalance>0; missing feature is neutral and explicitly counted', 'funding_flow': 'funding_all times flow_entry, fixed factorial interaction', 'execution': 'same tenth-round staged recovery and owned vintage reductions; modified nominal targets may create information-driven recovery/exit; original universe and selection unchanged', 'available': 'funding and closed spot flow through prior UTC day only; no received funding PnL, derivative positions or fabricated stablecoin yield'}, 'g20': {'nfci_cash': 'latest NFCI>0 halves original selected equity instruments; released budget to BIL', 'credit_cash': 'latest NFCI Credit contribution>0 halves original selected equity instruments; released budget to BIL', 'credit_gold': 'same credit rule but released equity capital buys actual GLD units', 'curve_credit': 'credit contribution>0 OR lagged10y-3m slope<0 halves selected equity instruments; released budget to BIL', 'timing': 'NFCI reference Friday+7 calendar days, stale after21 days; slope2 equity-session lag, stale after7 days; changed targets trade at original T+1/T+2', 'missing': 'missing source feature is neutral; no backward fill or fabricated zero values', 'qualification': 'latest macro snapshots have revision exposure; all four G20 information candidates are diagnostic-only and excluded from current leader selection'}}

SOURCE_CONTRACT = {'funding_months': ['2020-06', '2026-08'],
    'flow_months': ['2020-12', '2026-08'], 'symbols': ['BTCUSDT', 'ETHUSDT'],
    'funding_features': [7, 180, .75], 'flow_days': 20,
    'information_lag_calendar_days': 1, 'macro_vintage_certified': False,
    'crypto_vintage_certified': False}
SELECTION_EXCLUSIONS = [f'dual_engine_sources_20261005/g20/{r}' for r in G20_CANDIDATES]


def read_contract(path):
    c = json.loads(path.read_text())
    expected = {"study_id": "dual_engine_sources_20261005", "research_only": True,
        "orders_authorized": False, "promotion_evidence": False, "new_candidate_trials": 8,
        "planned_curves": 52, "data_role": "consumed_historical_discovery_pool"}
    if any(c.get(k) != v for k, v in expected.items()):
        raise ValueError("sources_contract_invalid")
    for line, controls, candidates, dates, costs, delays in (
        ("g20", G20_CONTROLS, G20_CANDIDATES, ("2018-04-02", "2026-07-30"), [20, 40], [1, 2]),
        ("c60", C60_CONTROLS, C60_CANDIDATES, ("2021-01-01", "2026-08-31"), [25, 50], [0, 1])):
        if (tuple(c[line]["controls"]) != controls or tuple(c[line]["candidates"]) != candidates
                or (c[line]["start"], c[line]["end"]) != dates or c[line]["cost_bps"] != costs or c[line]["delays"] != delays):
            raise ValueError("sources_comparison_protocol_changed")
    if (c["c60"]["horizons"] != [20, 60, 90] or c["c60"]["risk_window"] != 60
            or c["c60"]["annual_volatility_cap"] != .6 or c["c60"]["core_weight"] != .7
            or c["c60"]["satellite_weight"] != .3):
        raise ValueError("sources_core_settings_changed")
    if (c['selection_policy'] != POLICY
            or c['target_sources'] != {'g20': G20_SOURCES, 'c60': C60_SOURCES}):
        raise ValueError('sources_target_or_selection_policy_changed')
    if c['mechanisms'] != MECHANISMS: raise ValueError('sources_mechanisms_changed')
    if c['source_contract'] != SOURCE_CONTRACT or c['selection_exclusions'] != SELECTION_EXCLUSIONS:
        raise ValueError('sources_information_qualification_changed')
    return c


def equity_targets(panel, settings, rule, rates, information):
    if rule in G20_CONTROLS:
        return tenth.equity_targets(panel, settings, rule, rates)
    if rule not in G20_CANDIDATES: raise ValueError('unknown_information_equity_rule')
    original, selection = tenth.equity_targets(panel, settings, 'aware_gold_rotate', rates)
    features = macro_features(information, panel.dates)
    from qount.dual_engine.contracts import G20_EXECUTION_TO_PROXY
    targets, observations, current, last = {}, [], None, None
    monthly = set(old.g20_signals(panel))
    for t in range(len(panel.dates) - 1):
        if t in original: current = original[t]
        if current is None: continue
        feature = features[t]; nfci = feature['nfci']; slope = feature['curve']
        tight = bool(nfci and nfci['NFCI'] > 0) if rule == 'nfci_cash' else bool(nfci and nfci['Credit'] > 0)
        if rule == 'curve_credit': tight = tight or (slope is not None and slope < 0)
        target = dict(current); released = 0.
        if tight:
            for k in G20_EXECUTION_TO_PROXY:
                if k in target: released += target[k] * .5; target[k] *= .5
        if rule == 'credit_gold': target['GLD'] = target.get('GLD', 0.) + released
        else: target['BIL'] = target.get('BIL', 0.) + released
        if target != last or t in monthly:
            targets[t] = target; last = target
        observations.append({'date': panel.dates[t], 'feature': feature, 'tight': tight,
                             'released_budget': released, 'original_target': current, 'target': target})
    return targets, {'original_selection': selection, 'information_decisions': observations}


def crypto_targets(axis, assets, settings, rule, information):
    if rule in C60_CONTROLS: return tenth.crypto_targets(axis, assets, settings, rule)
    if rule not in C60_CANDIDATES: raise ValueError('unknown_information_crypto_rule')
    original, selection = tenth.crypto_targets(axis, assets, settings, 'staged_risk4')
    targets, decisions = {}, {}
    for t, nominal in original.items():
        day = axis.dates[t]
        funding = {s: funding_feature(information['funding'][s], day) for s in ('BTCUSDT', 'ETHUSDT')}
        flow = {s: flow_feature(information['flow'][s], day) for s in ('BTCUSDT', 'ETHUSDT')}
        crowded = any(f and f['crowded'] for f in funding.values())
        target = {}
        for k, w in nominal.items():
            symbol = assets[k].symbol; factor = 1.
            if rule == 'funding_core' and symbol in funding and funding[symbol] and funding[symbol]['crowded']: factor *= .5
            if rule in ('funding_all', 'funding_flow') and crowded: factor *= .5
            if rule in ('flow_entry', 'funding_flow'):
                reference = symbol if symbol in flow else 'BTCUSDT'
                if flow[reference] and flow[reference]['imbalance20'] <= 0: factor = 0.
            if factor > 0: target[k] = w * factor
        targets[t] = target
        decisions[t] = {'date': day, 'funding': funding, 'flow': flow, 'crowded': crowded,
                        'original_target': nominal, 'target': target}
    return targets, {'original_selection': selection, 'information_decisions': decisions}


def candidate_replay(line, rule, dates, closes, opens, targets, *, settings, delay, cost, assets=None, panel=None):
    if line == 'g20':
        return base.replay_units(dates, closes, opens, targets, start=settings['start'], lag=delay, cost_bps=cost, cash_asset='BIL')
    return tenth.candidate_replay('c60', 'staged_risk4', dates, closes, opens, targets,
                                 settings=settings, delay=delay, cost=cost, assets=assets, panel=panel)


def run_study(*, contract_path, prior_contract, equity_root, pit_cache, expansion_root, rates_root,
              inverse_root, tail_root, open_root, prior_results, information_root, out, repo):
    ex.require_storage(out)
    c = read_contract(contract_path)
    if (not isinstance(c['information_manifest_sha256'], str)
            or len(c['information_manifest_sha256']) != 64
            or str(information_root) != c.get('information_root')):
        raise ValueError('information_inputs_not_frozen')
    if out.exists():
        raise ValueError("immutable_result_exists")
    panel, equity_audit = old.load_equity(equity_root, old.read_contract(prior_contract))
    raw, hashes = load_cache(pit_cache)
    if str(prior_results) != c['prior_result']['root']:
        raise ValueError('sources_prior_root_changed')
    verify_manifest(prior_results, expected_hash=c['prior_result']['manifest_sha256'])
    prior_audit = json.loads((prior_results / "input-audit.json").read_text())
    if hashes != prior_audit["cache_sha256"] or equity_audit["files"] != prior_audit["equity"]["files"]:
        raise ValueError("prior_input_identity_changed")
    panel = load_inverse(load_tail(load_macro(panel, expansion_root), tail_root), inverse_root)
    rates = load_rates(rates_root, panel.dates)
    verify_manifest(information_root, expected_hash=c['information_manifest_sha256'])
    information = json.loads((information_root / 'information.json').read_text())
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
            "tail_root": tail_root, "open_root": open_root, "information_root": information_root}.items()},
        "prior_result_manifest_sha256": old.file_hash(prior_results / "manifest.json"),
        "contract_sha256": old.file_hash(contract_path),
        "information_manifest_sha256": old.file_hash(information_root / 'manifest.json')}
    old.write_json(out / "input-audit.json", audit)
    runs, summaries, exposures, checks, attribution = {}, {"g20": {}, "c60": {}}, [], {}, {}
    for line, rules, dates, closes, opns, annual in (
        ("g20", G20_CONTROLS + G20_CANDIDATES, panel.dates, eq_close, eq_open, 252),
        ("c60", C60_CONTROLS + C60_CANDIDATES, axis.dates, cr_close, cr_open, 365)):
        for rule in rules:
            targets, members = (equity_targets(panel, c[line], rule, rates, information) if line == "g20" else
                                crypto_targets(axis, assets, c[line], rule, information))
            old.write_json(out / f"{line}-{rule}-targets.json", targets)
            old.write_json(out / f"{line}-{rule}-selection.json", members)
            for cost in c[line]["cost_bps"]:
                for delay in c[line]["delays"]:
                    cell = f"c{cost}-d{delay}"
                    aims = dict(targets)
                    if line == "g20":
                        first = next(i for i, d in enumerate(dates) if d >= c[line]["start"])
                        aims.setdefault(first - delay, {"BIL": 1.0})
                    if rule in G20_CANDIDATES + C60_CANDIDATES:
                        run = candidate_replay(line,rule,dates,closes,opns,aims,settings=c[line],delay=delay,cost=cost,assets=assets,panel=panel)
                    elif rule in tenth.G20_CANDIDATES + tenth.C60_CANDIDATES:
                        run = tenth.candidate_replay(line, rule, dates, closes, opns, aims,
                            settings=c[line], delay=delay, cost=cost, assets=assets, panel=panel)
                    elif rule in ninth.G20_CANDIDATES + ninth.C60_CANDIDATES:
                        run = ninth.candidate_replay(line, rule, dates, closes, opns, aims,
                            settings=c[line], delay=delay, cost=cost, assets=assets, panel=panel)
                    else:
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
        (line, r, "aware_gold_rotate" if line == "g20" else "staged_risk4")
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
    for key,run in runs.items():
        if key.endswith("c20-d1") or key.endswith("c40-d2") or key.endswith("c25-d0") or key.endswith("c50-d1"):
            line=key.split("-")[0]
            holding = (capital_contributions(run, panel.dates, eq_close, eq_open) if line == "g20" and key.split("-")[1] == "capital_reset_sector" else
                analyze_units(run, panel.dates if line=="g20" else axis.dates,
                    eq_close if line=="g20" else cr_close, eq_open if line=="g20" else cr_open, market="SPY" if line=="g20" else btc))
            old.write_json(out/(key+"-holdings.json"), holding)
    sources = {repo / "scripts/research/dual_engine_sources.py", repo / "config/dual-engine-sources-20261005.json"}
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
        "information_manifest_sha256": old.file_hash(information_root / "manifest.json"),
        "selection_exclusions": c["selection_exclusions"],
        "information_usage": "public information only; all cashflow remains actual long spot/fund price PnL and fees",
        "account_diagnostics": {key: {
            "recovery_decisions": sum(bool(p.get("recovered_assets")) for p in run.get("decisions", [])),
            "off_week_recovery_fills": sum(bool(r.get("intent") and r["intent"].get("recovered_assets") and not r["intent"].get("weekly")) for r in run["records"]),
            "version_mismatches": sum(r.get("version_mismatch", False) for r in run["records"]),
            "reduce_buy_notional": sum(r.get("risk_buy_notional", 0.) for r in run["records"] if r.get("trade_clock")=="reduce"),
            "daily_core_buy_notional": sum(r.get("core_buy_notional", 0.) for r in run["records"] if r.get("trade_clock")=="mixed"),
            "vintage_relative_error": max(r.get("vintage_units_relative_error", 0.) for r in run["records"]),
            "cancelled_stale_assets": sum(len(r.get("cancelled_stale", [])) for r in run["records"]),
            "capital_reset_days": sum(r.get("capital_reset", False) for r in run["records"]),
            "untouched_books_units_max_error": max(r.get("untouched_books_units_max_error", 0.) for r in run["records"]),
            "gross_internal_opposite_notional": sum(r.get("internal_opposite_traded_notional", 0.) for r in run["records"]),
            "gross_capital_transfers": sum(sum(abs(b["capital_transfer"]) for b in r.get("books", {}).values()) for r in run["records"]),
            "max_equity_crisis_capital_weight": max((r["books"]["equity_crisis"]["nav"]/r["nav"] for r in run["records"] if "books" in r), default=None)
        } for key, run in runs.items()},
        "global_trial_count": None, "dsr_pbo": c["dsr_pbo"]}
    if len(exposures) != c["planned_curves"]:
        raise ValueError("curve_inventory_mismatch")
    old.write_json(out / "results.json", result)
    old.write_json(out / "manifest.json", {"research_only": True, "orders_authorized": False,
        "files": {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}})
    return result
