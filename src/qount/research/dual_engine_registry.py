"""Immutable strategy versions and deterministic discovery leader maintenance.

Historical leaders are conditional on the declared comparison protocol.  Neither
backtest ranking nor a short later-period check certifies a global/live optimum.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

from qount.research import dual_engine_optimization as old
from qount.research.dual_engine_execution_study import verify_manifest

POLICY = {
    "id": "worst_cell_cash_sharpe_v1",
    "primary": "maximize minimum cash_excess_sharpe across all four cost/delay cells",
    "ties": "minimum CAGR, worst drawdown, lower maximum turnover, stable version ID",
    "pareto": ["minimum cash_excess_sharpe", "minimum CAGR", "worst max_drawdown"],
    "data_role": "consumed_historical_discovery_pool",
    "global_optimum_confirmed": False,
}
CELLS = {"g20": {"c20-d1", "c20-d2", "c40-d1", "c40-d2"},
         "c60": {"c25-d0", "c25-d1", "c50-d0", "c50-d1"}}
DATES = {"g20": ("2018-04-02", "2026-07-30"), "c60": ("2021-01-01", "2026-08-31")}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def robust_metrics(cells, line):
    if line not in CELLS:
        return None
    if set(cells) != CELLS.get(line, set()):
        return None
    if any((r.get("first"), r.get("last")) != DATES[line] for r in cells.values()):
        return None
    names = ("cash_excess_sharpe", "cagr", "max_drawdown", "annual_turnover")
    if any(not math.isfinite(r[n]) for r in cells.values() for n in names):
        raise ValueError("registry_nonfinite_metric")
    return {"minimum_sharpe": min(r["cash_excess_sharpe"] for r in cells.values()),
            "minimum_cagr": min(r["cagr"] for r in cells.values()),
            "worst_drawdown": min(r["max_drawdown"] for r in cells.values()),
            "maximum_turnover": max(r["annual_turnover"] for r in cells.values())}


def select_leaders(versions):
    output = {}
    for line in CELLS:
        eligible = [r for r in versions if r["line"] == line and r.get("selection_eligible")]
        if not eligible:
            output[line] = {"leader": None, "pareto": [], "confirmation_status": "no_comparable_versions"}
            continue
        def score(row):
            m = row["robust_metrics"]
            return (-m["minimum_sharpe"], -m["minimum_cagr"], -m["worst_drawdown"], m["maximum_turnover"], row["version_id"])
        def vector(row):
            return tuple(row["robust_metrics"][n] for n in ("minimum_sharpe", "minimum_cagr", "worst_drawdown"))
        frontier = [r for r in eligible if not any(all(x >= y for x, y in zip(vector(o), vector(r), strict=True))
                    and any(x > y for x, y in zip(vector(o), vector(r), strict=True)) for o in eligible)]
        output[line] = {"leader": sorted(eligible, key=score)[0]["version_id"],
                        "pareto": sorted(r["version_id"] for r in frontier),
                        "eligible_versions": len(eligible), "confirmation_status": "historical_leader_verified_pending_prospective"}
    return output


def build_registry(studies, out, *, selection_exclusions=(), parent_registry_root=None):
    """Preserve EVERY version/curve; older protocols remain archived and visible."""
    if out.exists():
        raise ValueError("immutable_registry_snapshot_exists")
    versions, receipts, exposures, trials = [], [], [], 0
    excluded = set(selection_exclusions)
    for root, expected_hash in studies:
        files = verify_manifest(root, expected_hash=expected_hash)
        actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p != root / "manifest.json"}
        if actual != set(files):
            raise ValueError("registry_artifact_inventory_changed")
        result = json.loads((root / "results.json").read_text())
        if result.get("research_only") is not True or result.get("orders_authorized") is not False:
            raise ValueError("research_only_result_required")
        study = result["study_id"]
        contract_name = next((name for name in ("contract.json", "preregistration.json") if name in files), None)
        if contract_name is None:
            raise ValueError("registry_manifest_bound_contract_required")
        snapshot = json.loads((root / contract_name).read_text())
        if snapshot.get("study_id") != study or snapshot.get("research_only") is not True or snapshot.get("orders_authorized") is not False:
            raise ValueError("registry_contract_identity_invalid")
        curves = result["curve_exposures"]
        verification_path = root.parent / "_verification" / "result-verification.json"
        verification = json.loads(verification_path.read_text())
        verified = verification.get("verified") is True or (
            bool(verification.get("curves_verified")) and all(r["verified"] is True for r in verification["curves_verified"]))
        verification_manifest = verification.get("manifest_sha256", verification.get("result_manifest_sha256",
            verification.get("output_integrity", {}).get("manifest_sha256")))
        verification_count = verification.get("curve_count", verification.get("curves", len(verification.get("curves_verified", []))))
        if not verified or verification_manifest != expected_hash or verification_count != len(curves):
            raise ValueError("registry_independent_verification_required")
        exposures += [{"study_id": study, **r} for r in curves]
        trials += result.get("candidate_trials", result.get("new_candidate_trials", result.get("local_candidate_trials", 0)))
        receipt = {"study_id": study, "root": str(root), "manifest_sha256": old.file_hash(root / "manifest.json"),
                   "result_sha256": files["results.json"], "source_sha256": result["source_sha256"], "curve_count": len(curves),
                   "independent_verification_path": str(verification_path),
                   "independent_verification_sha256": old.file_hash(verification_path)}
        receipts.append(receipt)
        summaries = result.get("summaries", result.get("results", {}))
        for line, rules in summaries.items():
            for rule, cells in rules.items():
                version = f"{study}/{line}/{rule}"
                metrics = robust_metrics(cells, line)
                # No-order reference strategies may compete; diagnostic-only lines cannot.
                eligible = metrics is not None and version not in excluded
                row = {"version_id": version, "study_id": study, "line": line, "rule": rule,
                       "summary_path": f"{'summaries' if 'summaries' in result else 'results'}.{line}.{rule}",
                       "artifact_root": str(root), "artifact_manifest_sha256": receipt["manifest_sha256"],
                       "strategy_contract_path": str(root / contract_name),
                       "strategy_contract_sha256": files[contract_name],
                       "source_sha256": result["source_sha256"], "cells": cells,
                       "robust_metrics": metrics, "selection_eligible": eligible,
                       "selection_note": "registered diagnostic exclusion" if version in excluded else
                                         ("comparable protocol" if metrics else "preserved older or diagnostic protocol; not current ranking"),
                       "research_only": True, "orders_authorized": False, "promotion_evidence": False}
                row["version_fingerprint"] = fingerprint(row)
                versions.append(row)
    ids = [v["version_id"] for v in versions]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate_strategy_version")
    leaders = select_leaders(versions)
    revision = {}
    if parent_registry_root is not None:
        verify_manifest(parent_registry_root)
        parent = json.loads((parent_registry_root / "registry.json").read_text())
        fields = ("version_id", "cells", "source_sha256", "robust_metrics", "selection_eligible", "artifact_manifest_sha256")
        def unchanged(rows):
            return {r["version_id"]: {k: r[k] for k in fields} for r in rows}
        if (parent["policy"] != POLICY or parent["leaders"] != leaders or parent["candidate_trials"] != trials
                or parent["curve_exposures"] != exposures or unchanged(parent["versions"]) != unchanged(versions)):
            raise ValueError("metadata_revision_cannot_change_strategy_or_ranking")
        revision = {"revision_role": "contract_binding_metadata_correction_only",
                    "parent_registry_root": str(parent_registry_root),
                    "parent_registry_manifest_sha256": old.file_hash(parent_registry_root / "manifest.json"),
                    "selection_frozen_at": parent.get("selection_frozen_at", parent["created_at"]),
                    "selection_receipt_root": parent.get("selection_receipt_root", str(parent_registry_root)),
                    "ranking_and_return_summaries_unchanged": True}
    out.mkdir(parents=True)
    for row in versions:
        path = out / "strategies" / (row["version_id"] + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        old.write_json(path, row)
    builder = out / "source" / "dual_engine_registry.py"
    builder.parent.mkdir(parents=True, exist_ok=True)
    builder.write_bytes(Path(__file__).read_bytes())
    registry = {"schema_version": 1, "research_only": True, "orders_authorized": False,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "policy": POLICY,
                "studies": receipts, "versions": versions, "curve_exposures": exposures,
                "candidate_trials": trials, "global_trial_count": None,
                "leaders": leaders, "global_optimum_confirmed": False,
                "prospective_start": "2026-10-05", "scheduler_created": False,
                "registry_builder_path": str(builder), "registry_builder_sha256": old.file_hash(builder), **revision}
    old.write_json(out / "registry.json", registry)
    old.write_json(out / "manifest.json", {"research_only": True, "orders_authorized": False,
        "files": {str(p.relative_to(out)): old.file_hash(p) for p in sorted(out.rglob("*")) if p.is_file()}})
    return registry
