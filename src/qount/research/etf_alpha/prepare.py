"""M1 workflow: freeze contracts, audit causal data/labels and run fixed baselines."""
from __future__ import annotations

import csv
import platform
import sys
from pathlib import Path

import numpy as np

from .artifacts import (EXTERNAL_ROOT, GUARDS, finish_manifest, new_directory,
                        read_json, sha256, utc_now, verify_files, write_json)
from .baselines import declared_baselines, run_baselines
from .contracts import cost_contract, label_contract, metric_contract, protocol_contract, regime_contract
from .data import load_public_panel, total_return_index
from .features import build_features
from .labels import build_labels, opening_label_oracle
from .splits import expanding_folds


def _source_hashes(repo: Path) -> dict:
    roots = [repo / "src/qount/research/etf_alpha", repo / "src/qount/research/etf_trader"]
    paths = [p for root in roots for p in root.rglob("*.py") if "__pycache__" not in p.parts]
    paths += list((repo / "scripts/research").glob("etf_alpha_*.py"))
    paths += list((repo / "tests").glob("test_etf_alpha_*.py"))
    paths += [repo / "pyproject.toml"]
    return {str(p.relative_to(repo)): sha256(p) for p in sorted(paths) if p.is_file()}


def _causal_checks(panel, features, labels) -> dict:
    stop = int(np.searchsorted(panel.dates, "2020-01-01"))
    prefix = build_features(panel.prefix(stop))
    for name in ("raw", "normalized", "market_raw", "market_normalized", "covariance_annual"):
        np.testing.assert_allclose(getattr(prefix, name), getattr(features, name)[:stop], atol=1e-10, equal_nan=True)
    order = tuple(reversed(panel.symbols))
    reversed_features = build_features(panel.reordered(order))
    np.testing.assert_allclose(reversed_features.normalized, features.normalized[:, ::-1], atol=1e-8, equal_nan=True)
    np.testing.assert_allclose(reversed_features.market_raw, features.market_raw, atol=1e-10, equal_nan=True)
    np.testing.assert_allclose(reversed_features.covariance_annual,
                               features.covariance_annual[:, ::-1, ::-1], atol=1e-12, equal_nan=True)
    checks, maximum = 0, 0.0
    # Reconcile all assets across deterministic, evenly spaced, complete label intervals.
    for h in (5, 20, 60):
        eligible = np.flatnonzero(labels.available[f"mu{h}"].all(axis=1))
        selected = eligible[np.linspace(0, len(eligible) - 1, min(100, len(eligible)), dtype=int)]
        for t in selected:
            for i in range(len(panel.symbols)):
                oracle = opening_label_oracle(panel, i, int(t + 1), int(t + h + 1))
                error = abs(oracle - labels.values[f"mu{h}"][t, i])
                maximum = max(maximum, float(error))
                checks += 1
    if maximum > 1e-9:
        raise ValueError("next-open total-return labels fail raw share/cash reconciliation")
    cov = features.covariance_annual
    available = np.isfinite(cov).all(axis=(1, 2))
    minimum_eigenvalue = float(np.min(np.linalg.eigvalsh(cov[available])))
    if minimum_eigenvalue < -1e-10:
        raise ValueError("risk covariance is not PSD")
    return {"prefix_invariance": "pass", "prefix_cutoff": panel.dates[stop - 1],
            "asset_permutation": "pass", "label_cash_share_oracle": "pass",
            "label_oracle_intervals": checks, "maximum_label_error": maximum,
            "covariance_psd": "pass", "minimum_covariance_eigenvalue": minimum_eigenvalue,
            "input_uses_vendor_adjusted_close": False}


def prepare_m1(data_root: Path, baseline_manifest: Path, dataset_out: Path, out: Path, repo: Path,
               end: str = "2026-10-01", *, external_root: Path = EXTERNAL_ROOT,
               fixture_validation: Path | None = None, progress=None) -> dict:
    preservation = read_json(baseline_manifest)
    verify_files(baseline_manifest.parent, read_json(baseline_manifest.parent / "manifest.json")["files"])
    if preservation["m0_status"] != "completed":
        raise ValueError("completed M0 registration required")
    panel = load_public_panel(data_root, end)
    if panel.audit["source_manifest_sha256"] != preservation["inputs"]["dataset"]["manifest_sha256"]:
        raise ValueError("M1 source must match the registered dataset version")
    new_directory(out, external_root=external_root)
    new_directory(dataset_out, kind="datasets", external_root=external_root)
    # Freeze all rules before baseline returns are calculated. No data-dependent thresholds.
    frozen_at = utc_now()
    protocol = protocol_contract() | {"protocol_frozen_at": frozen_at,
        "baseline_manifest_sha256": sha256(baseline_manifest), "source_hashes": _source_hashes(repo),
        "environment": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform()},
        "consumed_through": panel.dates[-1], "fresh_window_start": None,
        "fresh_window_status": "not_designated; must follow actual final-model freeze and consumed cutoff"}
    contracts = {"protocol-contract.json": protocol, "label-contract.json": label_contract(),
                 "metric-contract.json": metric_contract(), "regime-contract.json": regime_contract(),
                 "cost-contract.json": cost_contract(), "seed-contract.json": GUARDS | protocol["seed_contract"],
                 "selection-contract.json": GUARDS | protocol["selection_contract"]}
    for name, contract in contracts.items():
        write_json(out / name, contract)
    if fixture_validation is not None:
        verification = read_json(fixture_validation)
        if verification.get("status") != "pass":
            raise ValueError("failed fixture validation cannot qualify M1")
        write_json(out / "fixture-validation.json", verification)
    if progress:
        progress("contracts frozen; constructing features and labels")
    features = build_features(panel)
    labels = build_labels(panel)
    ready = features.available.all(axis=(1, 2))
    folds = expanding_folds(panel.dates, labels, ready)
    write_json(out / "feature-schema.json", GUARDS | features.schema)
    write_json(out / "fold-contract.json", GUARDS | {"schema": "etf-p3-folds-v1",
        "purge": "label_end_row < next_partition_first_row - embargo_sessions", "embargo_sessions": 5,
        "normalizer": "trailing PIT input scale; future output/target scales fit each train only",
        "execution_continuity": "one continuous ledger; switch models without resetting positions, DD or budgets",
        "folds": [fold.contract() for fold in folds]})
    write_json(out / "calendar-contract.json", GUARDS | {"sessions": len(panel.dates),
        "first": panel.dates[0], "last": panel.dates[-1], "calendar_file": str(dataset_out / "calendar.csv"),
        "source": "ten-source exact session agreement", "independent_exchange_calendar_verified": False,
        "removed_sessions": []})
    write_json(out / "execution-contract.json", GUARDS | {
        "schema": "etf-p3-event-accounting-v1", "p2_engine_modified": False,
        "decision": "close t; fill open t+1; ADV/sigma/spread known at close t",
        "splits": "adjust prior holdings before open",
        "distributions": "prior holdings entitlement; new ex-open buyers excluded, sellers retain cash",
        "cash_proxy": "daily BIL close carry on previous cash, before next-open fills",
        "payment_timing": "ex-date entitlement treated as immediately spendable cash; actual payment dates unavailable",
        "affordability": "sells retained; whole-share buys scaled to fund fees; no negative cash borrowing",
        "controller": "existing 10%/15% DD state machine applied once; existing recovery semantics",
        "continuity": "shares, cash, DD history/peak and rolling voluntary/forced budgets carried across boundaries",
        "total_return_label": "zero-cost fractional reinvestment; different from constrained strategy cash policy"})
    baseline = declared_baselines(panel, features)
    write_json(out / "baseline-contract.json", GUARDS | {"schema": "etf-p3-baselines-v1",
        "frozen_at": frozen_at, "start": "2015-01-01", "cost_multipliers": [1, 2, 3],
        "baselines": [{"baseline_id": b.baseline_id, "baseline_variant": b.variant,
                       "rule": b.rule, "rebalance_sessions": b.every} for b in baseline],
        "checkpoint_inference": False, "parameter_selection": False,
        "fixed_factor_note": "new P3 execution diagnostic; does not replace or rewrite original P2 result"})
    checks = _causal_checks(panel, features, labels)
    np.savez_compressed(dataset_out / "panel.npz", dates=np.asarray(panel.dates), symbols=np.asarray(panel.symbols),
        **{k: getattr(panel, k) for k in ("open", "high", "low", "close", "volume", "dividends", "splits", "cash_open", "cash_close")})
    np.savez_compressed(dataset_out / "features.npz", names=np.asarray(features.names), raw=features.raw,
        normalized=features.normalized, available=features.available, market_names=np.asarray(features.market_names),
        market_raw=features.market_raw, market_normalized=features.market_normalized,
        market_available=features.market_available, covariance_annual=features.covariance_annual)
    np.savez_compressed(dataset_out / "labels.npz", **labels.values,
        **{f"available_{k}": v for k, v in labels.available.items()}, start_rows=labels.start_rows,
        **{f"end_rows_{h}": r for h, r in labels.end_rows.items()})
    with (dataset_out / "calendar.csv").open("x", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(["row", "date"])
        writer.writerows(enumerate(panel.dates))
    write_json(dataset_out / "source-manifest.json", GUARDS | panel.audit)
    dataset = GUARDS | {"dataset_id": dataset_out.name, "source": panel.audit,
        "parent_baseline_manifest_sha256": sha256(baseline_manifest),
        "contracts": {name: sha256(out / name) for name in (*contracts, "feature-schema.json", "fold-contract.json")},
        "rows": len(panel.dates), "risk_assets": list(panel.symbols), "feature_count": 38,
        "ready_decision_dates": int(ready.sum()), "first_all_features_ready": panel.dates[np.flatnonzero(ready)[0]],
        "derived_data_path": str(dataset_out), "retention": "immutable public research input and contracts"}
    write_json(out / "dataset-contract.json", dataset)
    write_json(dataset_out / "dataset-contract.json", dataset)
    finish_manifest(dataset_out, dataset_id=dataset_out.name)
    if progress:
        progress("causal/label checks passed; running declared baseline diagnostics")
    reports = run_baselines(panel, baseline, out, progress=progress)
    write_json(out / "baseline-results.json", GUARDS | {
        "result_status": "descriptive_baseline_diagnostics", "qualification": "not_Alpha_or_promotion",
        "baselines": reports, "independent_fresh_evidence": False})
    # Source limits are hard qualification gaps, not a waiver based on good returns.
    blockers = ["retrospective Yahoo snapshot has no historical as-of revision/availability provenance",
                "independent exchange session calendar has not been supplied",
                "distribution payment dates missing; immediate ex-date cash remains an approximation",
                "historical fee/spread schedule not audited; frozen static estimates only"]
    report = GUARDS | {"schema": "etf-p3-m1-audit-v1", "m1_engineering_status": "completed",
        "m1_status": "qualification_blocked", "D_gate": {"status": "insufficient", "blockers": blockers},
        "dataset_id": dataset_out.name, "dataset_path": str(dataset_out), "checks": checks,
        "sessions": len(panel.dates), "feature_count": 38, "fold_count": len(folds),
        "ready_decision_dates": int(ready.sum()), "first_all_features_ready": dataset["first_all_features_ready"],
        "fold_counts": {f.fold_id: {"train": len(f.train_rows), "validation": len(f.validation_rows),
                                    "test_execution": len(f.test_rows)} for f in folds},
        "baseline_count": len(baseline), "cost_scenarios": 3,
        "new_alpha_trials": 0, "prediction_training_status": "not_run", "M2_authorized_by_D_gate": False,
        "exposure_ledger": {"role": "already_consumed_discovery", "consumed_through": panel.dates[-1],
                            "descriptive_baseline_evaluations": len(baseline) * 3,
                            "global_trial_reconciliation": "pending", "checkpoint_inference": False},
        "source_audit": panel.audit, "protocol_frozen_at": frozen_at,
        "immutable_originals": "checked against M0 before and after; no original path rewritten"}
    verify_files(data_root, panel.audit["files"])
    for source in preservation["inputs"].values():
        verify_files(Path(source["root"]), source["files"])
        if sha256(Path(source["root"]) / source["manifest"]) != source["manifest_sha256"]:
            raise ValueError("preserved M0 input changed during M1")
    write_json(out / "m1-audit.json", report)
    (out / "summary.md").write_text(
        "# ETF P3 M1 audit\n\nresearch_only=true / orders_authorized=false\n\n"
        f"Engineering checks complete: {len(panel.dates)} sessions, 38 features, {len(folds)} folds.\n"
        f"Baseline diagnostics: {len(baseline)} rules/variants × 3 cost scenarios.\n\n"
        "D gate: insufficient. M2 prediction training has not started.\n\n"
        + "\n".join(f"- {reason}" for reason in blockers) + "\n", encoding="utf-8")
    finish_manifest(out, milestone="M1", dataset_id=dataset_out.name, D_gate="insufficient")
    return report
