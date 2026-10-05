"""Frozen execution-mechanism study; public inputs, offline WSL accounts only."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import platform
import random
import statistics
import sys
from pathlib import Path
from collections.abc import Mapping

from qount.research import dual_engine_optimization as old
from qount.research.c60_execution_control import acquire_opens, replay_crypto_open, warm_targets
from qount.research.g20_drift_control import replay_equity_control


def read_contract(path: Path) -> dict:
    c = json.loads(path.read_text())
    required = {"study_id": "dual_engine_execution_20261004", "research_only": True,
                "orders_authorized": False, "holdout_role": "discovery", "promotion_evidence": False,
                "new_candidate_trials": 2, "cumulative_local_candidate_trials": 4,
                "planned_curve_exposures": 64, "discovery_slices": 5}
    if any(c.get(k) != v for k, v in required.items()):
        raise old.OptimizationStudyError("execution_contract_invalid")
    if (c["g20"]["candidate"] != "reduce_only_drift_20pct" or c["g20"]["risk_weight"] != 0.2
            or c["g20"]["cost_bps"] != [20, 40] or c["g20"]["delays"] != [1, 2]
            or c["g20"]["primary_cells"] != [[20, 1], [40, 2]]
            or c["c60"]["candidate"] != "cancel_stale_buys"
            or c["c60"]["start"] != "2021-01-01" or c["c60"]["end"] != "2026-08-31"
            or c["c60"]["cost_bps"] != [25, 50] or c["c60"]["delays"] != [0, 1]
            or c["c60"]["primary_cells"] != [[25, 1], [50, 1]]):
        raise old.OptimizationStudyError("fixed_execution_settings_changed")
    return c


def verify_manifest(root: Path, *, expected_hash: str | None = None) -> dict:
    manifest = root / "manifest.json"
    if expected_hash and old.file_hash(manifest) != expected_hash:
        raise old.OptimizationStudyError("original_manifest_changed")
    files = json.loads(manifest.read_text())["files"]
    for relative, digest in files.items():
        p = root / relative
        if not p.resolve().is_relative_to(root.resolve()) or old.file_hash(p) != digest:
            raise old.OptimizationStudyError(f"manifest_hash_mismatch:{relative}")
    return files


def load_cache(pit_cache: Path) -> tuple[dict, dict]:
    raw, hashes = {}, {}
    for path in sorted(pit_cache.glob("*.json")):
        hashes[path.name] = old.file_hash(path)
        rows = json.loads(path.read_text())["rows"]
        if rows:
            raw[path.stem] = rows
    if not raw:
        raise old.OptimizationStudyError("pit_cache_empty")
    return raw, hashes


def read_opens(root: Path) -> tuple[dict, dict]:
    files = verify_manifest(root)
    if "opens.json" not in files:
        raise old.OptimizationStudyError("open_snapshot_not_hash_bound")
    opens = json.loads((root / "opens.json").read_text())
    if not opens:
        raise old.OptimizationStudyError("open_inputs_empty")
    return opens, files


def acquire(*, pit_cache: Path, out: Path) -> dict:
    if sys.platform != "linux" or not os.path.ismount("/mnt/e"):
        raise old.OptimizationStudyError("public_acquisition_requires_wsl_e")
    if not out.resolve().is_relative_to(Path("/mnt/e/qount_data/qount/artifacts/dual_engine")):
        raise old.OptimizationStudyError("open_output_outside_declared_storage")
    raw, _ = load_cache(pit_cache)
    axis, assets = old.build_crypto_assets(raw)
    needed: dict[str, set[str]] = {"BTCUSDT": {d[:7] for d in axis.dates if "2021-01-01" <= d <= "2026-08-31"}}
    for universe, confirmation in (("pit", 1), ("pit", 2), ("btc", 1), ("btc_monthly", 1)):
        targets, _ = warm_targets(axis, assets, universe=universe, confirmation=confirmation)
        for signal, weights in targets.items():
            for delay in (0, 1):
                execution = signal + 1 + delay
                if execution >= len(axis.dates) or axis.dates[execution] < "2021-01-01":
                    continue
                for k in weights:
                    # Cover the opening fill and next-day marking/exit of its
                    # holdings, even when the next requested target is zero.
                    for t in (execution, execution + 1):
                        if t < len(axis.dates):
                            needed.setdefault(assets[k].symbol, set()).add(axis.dates[t][:7])
    available = {p.stem: set(json.loads(p.read_text())["files"]) for p in pit_cache.glob("*.json")}
    months = {s: sorted(v & available[s]) for s, v in needed.items()}
    return acquire_opens(pit_cache, out, symbols=sorted(months), months_by_symbol=months, workers=16)


def paired_diagnostics(candidate: Mapping, baseline: Mapping, *, annual: int, settings: Mapping) -> dict:
    a, b = candidate["records"], baseline["records"]
    if [r["date"] for r in a] != [r["date"] for r in b] or not a:
        raise old.OptimizationStudyError("paired_dates_mismatch")
    ar, br = [r["return"] for r in a], [r["return"] for r in b]
    ax = [r["return"] - r["cash_return"] for r in a]
    bx = [r["return"] - r["cash_return"] for r in b]
    logs = [math.log1p(x) - math.log1p(y) for x, y in zip(ar, br, strict=True)]

    def sharpe(v):
        sigma = statistics.stdev(v) if len(v) > 1 else 0.0
        return statistics.fmean(v) / sigma * math.sqrt(annual) if sigma else 0.0

    def interval(values):
        values.sort()
        return [values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]]

    out = {}
    n = len(a)
    for block in settings["block_lengths"]:
        rng = random.Random(settings["seed"] + block)
        growth, sharpes = [], []
        for _ in range(settings["draws"]):
            indices = []
            while len(indices) < n:
                start = rng.randrange(n)
                indices.extend((start + j) % n for j in range(block))
            indices = indices[:n]
            growth.append(statistics.fmean(logs[i] for i in indices) * annual)
            sharpes.append(sharpe([ax[i] for i in indices]) - sharpe([bx[i] for i in indices]))
        out[str(block)] = {"annual_log_growth_difference": statistics.fmean(logs) * annual,
                           "log_growth_ci95": interval(growth),
                           "cash_excess_sharpe_difference": sharpe(ax) - sharpe(bx),
                           "sharpe_ci95": interval(sharpes), "draws": settings["draws"],
                           "role": "consumed discovery diagnostic; no post-selection significance"}
    return out


def paired_year_exclusion(candidate: Mapping, baseline: Mapping, *, annual: int) -> dict:
    best = old.summarize(baseline, annual)["excluded_best_complete_year"]
    def keep(run):
        return {"records": [r for r in run["records"] if r["date"][:4] != best]}
    return {"excluded_year": best, "candidate": old.summarize(keep(candidate), annual),
            "baseline": old.summarize(keep(baseline), annual), "role": "same-year paired discovery diagnostic"}


def summary(run: Mapping, annual: int) -> dict:
    result = old.summarize(run, annual)
    for name in ("risk_exposure_pre_trade", "risk_exposure_post_open", "risk_exposure_close"):
        values = [r[name] for r in run["records"] if name in r]
        if values:
            result[name] = {"mean": statistics.fmean(values), "maximum": max(values)}
    if run["records"] and "pretrade_weights" in run["records"][0]:
        for key, field in (("risk_exposure_pre_trade", "pretrade_weights"),
                           ("risk_exposure_post_open", "weights"), ("risk_exposure_close", "close_weights")):
            values = [sum(r[field].values()) for r in run["records"]]
            result[key] = {"mean": statistics.fmean(values), "maximum": max(values)}
    return result


def decide(results: Mapping, paired_years: Mapping, contract: Mapping, noop: bool) -> dict:
    decisions = {}
    for line in ("g20", "c60"):
        cells = [f"c{cost}-d{delay}" for cost, delay in contract[line]["primary_cells"]]
        base_name = "g20" if line == "g20" else "pit"
        candidate = results[line]["candidate"]
        baseline = results[line][base_name]
        metric = "cash_excess_sharpe" if line == "g20" else "sharpe"
        slices = sum(a[metric] > b[metric] for a, b in zip(candidate[cells[0]]["discovery_slices"],
                                                          baseline[cells[0]]["discovery_slices"], strict=True))
        gates = {"drawdown_not_worse": all(candidate[c]["max_drawdown"] + 1e-12 >= baseline[c]["max_drawdown"] for c in cells),
                 "slice_stability": slices >= contract[line]["gates"]["minimum_positive_slices"],
                 "same_year_exclusion_positive": all(paired_years[line][c]["candidate"]["cagr"] > 0.0 for c in cells)}
        if line == "g20":
            gates["cash_excess_sharpe_improves"] = all(candidate[c][metric] > baseline[c][metric] for c in cells)
            gates["base_cagr_budget"] = candidate[cells[0]]["cagr"] >= baseline[cells[0]]["cagr"] - contract[line]["gates"]["maximum_primary_cagr_sacrifice"]
        else:
            gates["sharpe_increment"] = all(candidate[c][metric] >= baseline[c][metric] + contract[line]["gates"]["minimum_primary_sharpe_improvement"] for c in cells)
            gates["cagr_not_lower"] = all(candidate[c]["cagr"] >= baseline[c]["cagr"] for c in cells)
            gates["ex_2021_above_both_btc"] = all(candidate[c]["excluding_2021"][metric] > results[line][btc][c]["excluding_2021"][metric]
                                                  for c in cells for btc in ("btc_daily", "btc_monthly"))
            gates["delay0_exact_noop"] = noop
        decisions[line] = {"gates": gates, "positive_discovery_slices": slices, "slice_cell": cells[0],
                           "verdict": "retain_for_new_forward_design" if all(gates.values()) else "reject_discovery_candidate"}
    return decisions


def orthogonal_contrasts(group: Mapping, *, low: int, high: int, early: int, late: int) -> dict:
    out = {}
    for rule, cells in group.items():
        def difference(a, b):
            return {metric: cells[a][metric] - cells[b][metric] for metric in ("cagr", "sharpe", "cash_excess_sharpe", "max_drawdown")}
        out[rule] = {"cost_only_early": difference(f"c{high}-d{early}", f"c{low}-d{early}"),
                     "cost_only_late": difference(f"c{high}-d{late}", f"c{low}-d{late}"),
                     "delay_only_low_cost": difference(f"c{low}-d{late}", f"c{low}-d{early}"),
                     "delay_only_high_cost": difference(f"c{high}-d{late}", f"c{high}-d{early}")}
    return out


def run_study(*, original_root: Path, equity_root: Path, pit_cache: Path, open_root: Path,
              contract_path: Path, original_contract_path: Path, out: Path, repo: Path) -> dict:
    contract = read_contract(contract_path)
    prior_contract = old.read_contract(original_contract_path)
    storage = Path("/mnt/e/qount_data/qount/artifacts/dual_engine")
    if sys.platform != "linux" or not os.path.ismount("/mnt/e") or not out.resolve().is_relative_to(storage):
        raise old.OptimizationStudyError("wsl_e_execution_required")
    if out.exists():
        raise old.OptimizationStudyError("output_exists; preserve immutable runs")
    prior_files = verify_manifest(original_root, expected_hash=contract["original_manifest_sha256"])
    panel, equity_audit = old.load_equity(equity_root, prior_contract)
    raw, cache_hashes = load_cache(pit_cache)
    original_audit = json.loads((original_root / "input-audit.json").read_text())
    if cache_hashes != original_audit["pit_cache_sha256"]:
        raise old.OptimizationStudyError("pit_cache_identity_changed")
    if equity_audit["files"] != original_audit["g20"]["files"]:
        raise old.OptimizationStudyError("equity_inputs_changed")
    axis, assets = old.build_crypto_assets(raw)
    opens, open_files = read_opens(open_root)
    signals = old.g20_signals(panel)
    source_files = {repo / "scripts/research/dual_engine_execution_study.py"}
    for name, module in tuple(sys.modules.items()):
        p = Path(module.__file__).resolve() if getattr(module, "__file__", None) else None
        if (name == "qount" or name.startswith("qount.")) and p and p.suffix == ".py":
            if not p.is_relative_to(repo.resolve() / "src"):
                raise old.OptimizationStudyError("imported_source_outside_declared_repo")
            source_files.add(p)
    out.mkdir(parents=True)
    old.write_json(out / "preregistration.json", contract)
    source_hashes = {}
    for path in sorted(source_files):
        relative = path.relative_to(repo)
        saved = out / "source" / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(path.read_bytes())
        source_hashes[str(relative)] = old.file_hash(path)
    old.write_json(out / "input-audit.json", {"original_result_manifest_sha256": old.file_hash(original_root / "manifest.json"),
                                              "original_output_files": len(prior_files), "g20": equity_audit,
                                              "pit_cache_sha256": cache_hashes, "open_files_sha256": open_files,
                                              "open_manifest_sha256": old.file_hash(open_root / "manifest.json"),
                                              "paths": {"original_root": str(original_root), "equity_root": str(equity_root),
                                                        "pit_cache": str(pit_cache), "open_root": str(open_root)},
                                              "source_sha256": source_hashes, "contract_sha256": old.file_hash(contract_path)})
    results = {"g20": {}, "c60": {}, "old_g20": {}, "old_c60": {}}
    runs, exposures, reproduced = {}, [], {}

    def save(group, rule, cell, run, annual, *, trial=None, role="discovery"):
        key = f"{group}-{rule}-{cell}"
        old.write_json(out / f"{key}-ledger.json", run)
        results[group].setdefault(rule, {})[cell] = summary(run, annual)
        runs[key] = run
        exposures.append({"curve": key, "candidate_trial": trial, "role": role})

    # Original startup, fee model and clocks are preserved in orthogonal diagnoses.
    for rule, absolute, benchmark in (("baseline", False, False), ("absolute", True, False), ("benchmark", False, True)):
        prior_signals = old.g20_signals(panel, absolute_momentum=absolute)
        for cost in (20, 40):
            for delay in (1, 2):
                cell = f"c{cost}-d{delay}"
                run = old.replay_equity(panel, prior_signals, start="2018-01-01", cost_bps=cost, delay=delay, benchmark=benchmark)
                save("old_g20", rule, cell, run, 252, role="original-rule orthogonal diagnosis")
                if (cost, delay) in ((20, 1), (40, 2)):
                    name = "candidate" if absolute else rule
                    scenario = "base" if cost == 20 else "stress"
                    original = json.loads((original_root / f"g20-{name}-{scenario}-ledger.json").read_text())
                    if [r["date"] for r in run["records"]] != [r["date"] for r in original["records"]]:
                        raise old.OptimizationStudyError("original_equity_dates_mismatch")
                    error = max(abs(a["return"] - b["return"]) for a, b in zip(run["records"], original["records"], strict=True))
                    if error > 1e-12:
                        raise old.OptimizationStudyError("original_equity_reproduction_failed")
                    reproduced[f"g20-{name}-{scenario}"] = error
    for rule, universe, confirmation in (("baseline", "pit", 1), ("confirmation", "pit", 2), ("btc", "btc", 1)):
        targets, _ = old.c60_targets(axis, assets, universe=universe, confirmation=confirmation)
        for cost in (25, 50):
            for delay in (0, 1):
                cell = f"c{cost}-d{delay}"
                run = old.replay_crypto(axis, assets, targets, cost_bps=cost, delay=delay)
                save("old_c60", rule, cell, run, 365, role="original-rule orthogonal diagnosis")
                if (cost, delay) in ((25, 0), (50, 1)):
                    prefix = "c60-btc" if rule == "btc" else "c60-pit-" + ("candidate" if confirmation == 2 else "baseline")
                    scenario = "base" if cost == 25 else "stress"
                    original = json.loads((original_root / f"{prefix}-{scenario}-ledger.json").read_text())
                    if [r["date"] for r in run["records"]] != [r["date"] for r in original["records"]]:
                        raise old.OptimizationStudyError("original_crypto_dates_mismatch")
                    error = max(abs(a["return"] - b["return"]) for a, b in zip(run["records"], original["records"], strict=True))
                    if error > 1e-12:
                        raise old.OptimizationStudyError("original_crypto_reproduction_failed")
                    reproduced[f"{prefix}-{scenario}"] = error

    # Fresh-account causal open replay, exact self-financing fees.
    for rule, risk, reduce, benchmark in (("g20", 0.2, False, False), ("g10", 0.1, False, False),
                                           ("candidate", 0.2, True, False), ("benchmark", 0.2, False, True)):
        for cost in (20, 40):
            for delay in (1, 2):
                run = replay_equity_control(panel, signals, start="2018-01-01", cost_bps=cost, delay=delay,
                                            reduce_only=reduce, risk_weight=risk, benchmark=benchmark)
                save("g20", rule, f"c{cost}-d{delay}", run, 252, trial="g20-drift-1" if reduce else None)
    targets_by_rule = {}
    for rule, universe, confirmation in (("pit", "pit", 1), ("candidate", "pit", 1),
                                          ("confirmation", "pit", 2), ("btc_daily", "btc", 1), ("btc_monthly", "btc_monthly", 1)):
        targets, members = warm_targets(axis, assets, universe=universe, confirmation=confirmation)
        targets_by_rule[rule] = targets
        if rule != "candidate":
            old.write_json(out / f"c60-{rule}-warm-targets.json", targets)
            old.write_json(out / f"c60-{rule}-warm-members.json", members)
        for signal, weights in targets.items():
            for delay in (0, 1):
                execution = signal + 1 + delay
                if execution >= len(axis.dates) or axis.dates[execution] < "2021-01-01":
                    continue
                for k in weights:
                    for t in (execution, execution + 1):
                        if t < len(axis.dates) and assets[k].has(t) and axis.dates[t] not in opens.get(assets[k].symbol, {}):
                            raise old.OptimizationStudyError(f"open_date_coverage_missing:{assets[k].symbol}:{axis.dates[t]}")
        for cost in (25, 50):
            for delay in (0, 1):
                run = replay_crypto_open(axis, assets, opens, targets, start="2021-01-01", cost_bps=cost,
                                         delay=delay, cancel_stale=rule == "candidate")
                save("c60", rule, f"c{cost}-d{delay}", run, 365, trial="c60-cancel-1" if rule == "candidate" else None)
    fee_errors = {}
    for line, cells in (("g20", ((20, 1), (40, 2))), ("c60", ((25, 0), (50, 1)))):
        for cost, delay in cells:
            cell = f"c{cost}-d{delay}"
            if line == "g20":
                approx = replay_equity_control(panel, signals, start="2018-01-01", cost_bps=cost, delay=delay, exact_fees=False)
                exact = runs[f"g20-g20-{cell}"]
            else:
                approx = replay_crypto_open(axis, assets, opens, targets_by_rule["pit"], start="2021-01-01", cost_bps=cost,
                                           delay=delay, exact_fees=False)
                exact = runs[f"c60-pit-{cell}"]
            key = f"{line}-fee-approx-{cell}"
            old.write_json(out / f"{key}-ledger.json", approx)
            exposures.append({"curve": key, "candidate_trial": None, "role": "prespecified fee approximation diagnosis"})
            fee_errors[key] = {"max_daily_return_difference": max(abs(a["return"] - b["return"]) for a, b in zip(approx["records"], exact["records"], strict=True)),
                               "approximate": summary(approx, 252 if line == "g20" else 365),
                               "exact": summary(exact, 252 if line == "g20" else 365)}
    noop = all(runs[f"c60-candidate-c{cost}-d0"] == runs[f"c60-pit-c{cost}-d0"] for cost in (25, 50))
    if not noop:
        raise old.OptimizationStudyError("delay0_candidate_not_identical")
    years, intervals = {}, {}
    for line, annual in (("g20", 252), ("c60", 365)):
        years[line], intervals[line] = {}, {}
        base_name = "g20" if line == "g20" else "pit"
        for cost, delay in contract[line]["primary_cells"]:
            cell = f"c{cost}-d{delay}"
            a, b = runs[f"{line}-candidate-{cell}"], runs[f"{line}-{base_name}-{cell}"]
            years[line][cell] = paired_year_exclusion(a, b, annual=annual)
            intervals[line][cell] = paired_diagnostics(a, b, annual=annual, settings=contract["paired_bootstrap"])
    startup = {}
    for rule, cells in results["old_c60"].items():
        for cell in ("c25-d0", "c50-d1"):
            run = runs[f"old_c60-{rule}-{cell}"]
            cropped = {"records": [r for r in run["records"] if r["date"] >= "2021-01-01"]}
            tail = [r["return"] for r in run["records"] if r["date"] < "2021-01-01"]
            startup[f"{rule}-{cell}"] = {"old_2020_tail_return": math.prod(1 + r for r in tail) - 1,
                                          "continuous_common_start": summary(cropped, 365)}
    if len(exposures) != contract["planned_curve_exposures"]:
        raise old.OptimizationStudyError("unregistered_curve_count")
    events = {}
    for line in ("g20", "c60"):
        for cost, delay in contract[line]["primary_cells"]:
            cell = f"c{cost}-d{delay}"
            run = runs[f"{line}-candidate-{cell}"]
            if line == "g20":
                events[f"{line}-{cell}"] = {"reductions_executed": sum(e["status"] == "executed" for e in run["reduce_events"]),
                                             "reductions_skipped_below_cap": sum(e["status"] == "skipped_below_cap" for e in run["reduce_events"]),
                                             "cancelled_by_monthly_fill": sum(e["status"] == "monthly_cancelled" for e in run["reduce_events"]),
                                             "close_risk_above_20pct_days": sum(r["risk_exposure_close"] > 0.2 + 1e-12 for r in run["records"])}
            else:
                events[f"{line}-{cell}"] = {"cancelled_buy_dates": sum(bool(r["canceled_buys"]) for r in run["records"]),
                                             "cancelled_buy_asset_days": sum(len(r["canceled_buys"]) for r in run["records"]),
                                             "missing_mark_events": sum(len(r["missing_marks"]) for r in run["records"]),
                                             "no_fill_events": sum(len(r["no_fills"]) for r in run["records"])}
    result = {"study_id": contract["study_id"], "research_only": True, "orders_authorized": False,
              "holdout_role": "discovery", "promotion_evidence": False, "new_candidate_trials": 2,
              "cumulative_local_candidate_trials": 4, "global_trial_count": None,
              "results": results, "decisions": decide(results, years, contract, noop),
              "paired_intervals": intervals, "paired_year_exclusion": years,
              "initialization_diagnostic": startup, "fee_approximation_diagnostic": fee_errors,
              "orthogonal_contrasts": {g: orthogonal_contrasts(results[g], low=low, high=high, early=early, late=late)
                                       for g, low, high, early, late in (("g20", 20, 40, 1, 2), ("old_g20", 20, 40, 1, 2),
                                                                       ("c60", 25, 50, 0, 1), ("old_c60", 25, 50, 0, 1))},
              "original_return_reproduction": reproduced, "delay0_noop": noop, "curve_exposures": exposures,
              "execution_events": events,
              "source_sha256": source_hashes, "contract_sha256": old.file_hash(contract_path),
              "dsr_pbo": contract["dsr_pbo"], "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "environment": {"python": sys.version, "platform": platform.platform()}}
    old.write_json(out / "results.json", result)
    old.write_json(out / "manifest.json", {"files": {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()},
                                          "research_only": True, "orders_authorized": False})
    return result
