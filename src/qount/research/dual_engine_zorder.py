"""Thirteenth-round atomic source/risk budgets and family trading clocks."""
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
from qount.research import dual_engine_zonal as twelfth
from qount.research.dual_engine_family_clock import replay_family_clock
from qount.research.dual_engine_coordinator import replay_coordinator
from qount.research.dual_engine_capital import capital_contributions
from qount.research.dual_engine_registry import POLICY
from qount.research.dual_engine_holdings import analyze_units
from qount.research.dual_engine_expansion_data import load_macro, load_rates
from qount.research.dual_engine_execution_study import load_cache, read_opens, verify_manifest, paired_year_exclusion
from qount.research.dual_engine_nextgen_data import load_tail
from qount.research.dual_engine_regimes_data import load_inverse

G20_CONTROLS = ('aware_gold_rotate','daily20_rotate','daily40_rotate','daily20_sector','daily40_sector','cap40_rotate','capital_reset_sector')
G20_CANDIDATES = ('joint20_rotate','joint40_rotate','joint20_sector','joint40_sector')
C60_CONTROLS = ('satellite_staged','staged_risk4','dual_sat4_risk','family_staged')
C60_CANDIDATES = ('core_week','sat_week','split_week','split_local')
G20_SOURCES = {'joint20_rotate':'aware_gold_rotate','joint40_rotate':'aware_gold_rotate','joint20_sector':'sector3_guard','joint40_sector':'sector3_guard'}
C60_SOURCES = {k:'staged_risk4' for k in C60_CANDIDATES}
PAIRS = tuple(('g20',n,n.replace('joint','daily')) for n in G20_CANDIDATES) + tuple(('c60',n,'satellite_staged') for n in C60_CANDIDATES) + (('c60','split_week','core_week'),('c60','split_week','sat_week'),('c60','split_local','split_week'))
MECHANISMS = {'g20': {'decision': 'same closed source targets/scopes and monthly sweep20/cap40 shares; after each close merge feasible source changes with held complementary non-BIL weights; cap projected investment dollars per book/global NAV at20%/40%', 'settlement': 'one dated target and scope per book; binding budget expands to full-book target with funded BIL remainder; original T+1/T+2; no separate cap order/epoch cancellation or round-trip fee paths', 'qualification': 'binding daily targets are full source-book rebalances and may buy risk units at fill; same-book cash funding and actual gross fees; no continuous hard exposure or derivative look-through claim; monthly capital transfers remain zero-sum'}, 'c60': {'core_week': 'Sunday refresh acquires core only; satellite transitions/refills acquire satellites; any core transition/refill retains coupled full fill', 'sat_week': 'Sunday refresh acquires satellites only; satellite transitions/refills acquire satellites; any core transition/refill retains coupled full fill', 'split_week': 'Sunday core and Wednesday satellite refresh; satellite transitions/refills scoped; any core transition/refill retains coupled full fill', 'split_local': 'Sunday core and Wednesday satellite refresh; all recovery/refill triggers acquire their own family, simultaneous triggers union both; no coupled core override', 'common': 'original zero/absent nominal to positive, half recovered targets outside Sunday and next-close refill; scheduled acquisitions union scoped recovery; complement uses owned-vintage reductions and nominal-zero exits; latest-closed-zero acquisition cancellation; 60-day60% covariance cap over combined planned weights and shared cash, not actual hard volatility ceiling'}}


def read_contract(path):
    c = json.loads(path.read_text())
    expected = {"study_id": "dual_engine_zorder_20261005", "research_only": True,
        "orders_authorized": False, "promotion_evidence": False, "new_candidate_trials": 8,
        "planned_curves": 76, "data_role": "consumed_historical_discovery_pool"}
    if any(c.get(k) != v for k, v in expected.items()):
        raise ValueError("zorder_contract_invalid")
    for line, controls, candidates, dates, costs, delays in (
        ("g20", G20_CONTROLS, G20_CANDIDATES, ("2018-04-02", "2026-07-30"), [20, 40], [1, 2]),
        ("c60", C60_CONTROLS, C60_CANDIDATES, ("2021-01-01", "2026-08-31"), [25, 50], [0, 1])):
        if (tuple(c[line]["controls"]) != controls or tuple(c[line]["candidates"]) != candidates
                or (c[line]["start"], c[line]["end"]) != dates or c[line]["cost_bps"] != costs or c[line]["delays"] != delays):
            raise ValueError("zorder_comparison_protocol_changed")
    if (c["c60"]["horizons"] != [20, 60, 90] or c["c60"]["risk_window"] != 60
            or c["c60"]["annual_volatility_cap"] != .6 or c["c60"]["core_weight"] != .7
            or c["c60"]["satellite_weight"] != .3):
        raise ValueError("zorder_core_settings_changed")
    if (c['selection_policy'] != POLICY or c['target_sources'] != {'g20': G20_SOURCES, 'c60': C60_SOURCES}
            or c['g20']['capital_policy']['initial_shares'] != {'equity_crisis': .2, 'gold': .2, 'reserve': .6}):
        raise ValueError('zorder_capital_or_selection_policy_changed')
    if c['mechanisms'] != MECHANISMS: raise ValueError('zorder_mechanisms_changed')
    if c['selection_exclusions'] != []: raise ValueError('zorder_selection_exclusions_changed')
    return c


def equity_targets(panel, settings, rule, rates):
    if rule not in G20_CONTROLS + G20_CANDIDATES:raise ValueError("unknown_zonal_equity_rule")
    source = G20_SOURCES.get(rule, rule)
    if rule in twelfth.G20_CANDIDATES: return twelfth.equity_targets(panel,settings,rule,rates)
    if source == 'sector3_guard': return ninth.equity_targets(panel, settings, source, rates)
    return tenth.equity_targets(panel, settings, source, rates)


def crypto_targets(axis, assets, settings, rule):
    if rule not in C60_CONTROLS + C60_CANDIDATES:raise ValueError("unknown_zonal_crypto_rule")
    return twelfth.crypto_targets(axis,assets,settings,rule) if rule in twelfth.C60_CANDIDATES else tenth.crypto_targets(axis, assets, settings, C60_SOURCES.get(rule,rule))


def candidate_replay(line,rule,dates,closes,opens,targets,*,settings,delay,cost,assets=None,panel=None):
    if line == "g20":
        return replay_coordinator(dates, closes, opens, targets, start=settings['start'], lag=delay, cost_bps=cost,
                                  full_refresh=set(old.g20_signals(panel)), limit=.2 if rule.startswith('joint20') else .4)
    def risk_scale(t, weights):
        returns = {k:base.daily_returns(assets[k].window(t, settings['risk_window']+1)) for k in weights}
        return min(1., settings['annual_volatility_cap'] / max(base.portfolio_sigma(returns, weights, 365), 1e-6))
    cores = tuple(k for k, a in assets.items() if a.symbol in ('BTCUSDT','ETHUSDT'))
    policy = rule
    return replay_family_clock(dates, closes, opens, targets, start=settings['start'], lag=1+delay, cost_bps=cost,
                           clock_mode=policy, core_assets=cores, risk_scale=risk_scale)


def diagnostics(run, assets):
    rows = run['records']
    return {'recovery_decisions': sum(bool(p.get('recovered_assets')) for p in run.get('decisions', [])),
        'scoped_acquisition_fills': sum(r.get('trade_clock') == 'recover' for r in rows),
        'cancelled_stale_assets': sum(len(r.get('cancelled_stale', [])) for r in rows),
        'vintage_relative_error': max(r.get('vintage_units_relative_error', 0.) for r in rows),
        'joint_binding_decisions': sum(p['binding'] for plans in run.get('joint_decisions',{}).values() for p in plans['books'].values()),
        'joint_binding_fills': sum(p['binding'] for row in rows for p in (row.get('joint_plan') or {}).get('books',{}).values()),
        'family_refresh_decisions': sum(bool(p.get('refresh_assets')) for p in run.get('decisions',[])),
        'cap_decisions': sum(len(v) for v in run.get('containment_decisions', {}).values()),
        'cap_fills': sum(bool(a.get('sales')) for r in rows for a in r.get('cap_actions', {}).values()),
        'cancelled_cap_epoch': sum(a.get('cancelled_epoch', False) for r in rows for a in r.get('cap_actions', {}).values()),
        'max_equity_risk_weight': max((r.get('book_risk_weights', {}).get('equity_crisis', 0.) for r in rows), default=0.),
        'max_gold_risk_weight': max((r.get('book_risk_weights', {}).get('gold', 0.) for r in rows), default=0.),
        'max_equity_capital_share': max((r['books']['equity_crisis']['nav']/r['nav'] for r in rows if 'books' in r), default=None),
        'cap_breach_days': sum(any(w > run.get('risk_limit', 1.) + 1e-12 for w in r.get('book_risk_weights', {}).values()) for r in rows),
        'daily_cap_actual_fees': sum(a.get('fee', 0.) for r in rows for a in r.get('cap_actions', {}).values()),
        'daily_cap_transfers': 0.,
        'reduce_buy_notional': sum(r.get('risk_buy_notional', 0.) for r in rows if r.get('trade_clock') == 'reduce')}


def run_study(*, contract_path, prior_contract, equity_root, pit_cache, expansion_root, rates_root,
              inverse_root, tail_root, open_root, prior_results, out, repo):
    ex.require_storage(out)
    c = read_contract(contract_path)
    if out.exists():
        raise ValueError("immutable_result_exists")
    panel, equity_audit = old.load_equity(equity_root, old.read_contract(prior_contract))
    raw, hashes = load_cache(pit_cache)
    if str(prior_results) != c['prior_result']['root']:
        raise ValueError('zorder_prior_root_changed')
    verify_manifest(prior_results, expected_hash=c['prior_result']['manifest_sha256'])
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
                    if rule in G20_CANDIDATES + C60_CANDIDATES:
                        run = candidate_replay(line,rule,dates,closes,opns,aims,settings=c[line],delay=delay,cost=cost,assets=assets,panel=panel)
                    elif rule in twelfth.G20_CANDIDATES + twelfth.C60_CANDIDATES:
                        run = twelfth.candidate_replay(line,rule,dates,closes,opns,aims,settings=c[line],delay=delay,cost=cost,assets=assets,panel=panel)
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
        (line, r, "aware_gold_rotate" if line == "g20" else "dual_sat4_risk")
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
            holding = (capital_contributions(run, panel.dates, eq_close, eq_open) if "books" in run["records"][0] else
                analyze_units(run, panel.dates if line=="g20" else axis.dates,
                    eq_close if line=="g20" else cr_close, eq_open if line=="g20" else cr_open, market="SPY" if line=="g20" else btc))
            old.write_json(out/(key+"-holdings.json"), holding)
    sources = {repo / "scripts/research/dual_engine_zorder.py", repo / "config/dual-engine-zorder-20261005.json"}
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
        "account_diagnostics": {key: diagnostics(run, assets if key.startswith('c60-') else None) for key, run in runs.items()},
        "global_trial_count": None, "dsr_pbo": c["dsr_pbo"]}
    if len(exposures) != c["planned_curves"]:
        raise ValueError("curve_inventory_mismatch")
    old.write_json(out / "results.json", result)
    old.write_json(out / "manifest.json", {"research_only": True, "orders_authorized": False,
        "files": {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}})
    return result
