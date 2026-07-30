#!/usr/bin/env python3
"""Build the immutable local R0 research-readiness evidence bundle.

The bundle maps historical families and records honest lifecycle, cost, and
Standalone NAV readiness. It does not fetch data, run candidate PnL, promote a
candidate, modify production authority, or authorize orders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash
from qount.governance import GlobalExperimentRecord
from qount.governance import HistoricalFamilyMapping
from qount.governance import ResearchEvidenceReadinessRecord
from qount.governance import build_r0_candidate_records
from qount.portfolio import read_multi_sleeve_virtual_artifact


R0_BUNDLE_SCHEMA_VERSION = 1


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _file_hash(relative_path: str) -> str:
    return hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()


def _source_hashes(*relative_paths: str) -> dict[str, str]:
    return {path: _file_hash(path) for path in relative_paths}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path: Path, value: object) -> None:
    raw = _canonical_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.link(temporary, path)
        _fsync_directory(path.parent)
        if path.read_bytes() != raw:
            raise RuntimeError(f"r0_record_readback_mismatch:{path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"r0_record_mode_invalid:{path}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _member_references(directory: Path) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        raw = path.read_bytes()
        references.append(
            {
                "path": path.name,
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return references


def _verify_bundle(directory: Path) -> Mapping[str, Any]:
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("r0_bundle_directory_invalid")
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise RuntimeError("r0_bundle_directory_mode_invalid")
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("r0_bundle_manifest_missing")
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest_core = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if manifest.get("manifest_hash") != canonical_hash(manifest_core):
        raise RuntimeError("r0_bundle_manifest_hash_invalid")
    if manifest.get("bundle_id") != directory.name:
        raise RuntimeError("r0_bundle_identity_invalid")
    if manifest.get("member_files") != _member_references(directory):
        raise RuntimeError("r0_bundle_member_hash_or_set_mismatch")
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("r0_bundle_member_invalid")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"r0_bundle_member_mode_invalid:{path.name}")
    return manifest


def _family_records() -> dict[str, ResearchEvidenceReadinessRecord]:
    cxd_mapping = HistoricalFamilyMapping.create(
        current_family="cxd_trend_carry",
        historical_family_ids=(
            "x4_s7_trend_portfolio",
            "rv_c_basis_carry",
            "x4_cxd_combo_v1_9",
        ),
        mapping_reason=(
            "The current CxD revalidation family inherits only the S7 trend, "
            "RV-C carry, and fixed-weight combo mechanism labels; it does not "
            "inherit historical promotion or live status."
        ),
        mapping_status="confirmed",
    )
    cta_mapping = HistoricalFamilyMapping.create(
        current_family="cta_r_cross_asset",
        historical_family_ids=(
            "l1_cross_asset_v1",
            "cta_r_selection_free_a_share_etf",
        ),
        mapping_reason=(
            "The current CTA-R revalidation family maps the selection-free "
            "cross-asset trend mechanism while requiring new point-in-time, "
            "cost, and venue evidence."
        ),
        mapping_status="confirmed",
    )
    cxd_sources = _source_hashes(
        "docs/archive/legacy/x4-rv/crypto-x4-plan.md",
        "docs/archive/legacy/x4-rv/rv-c-plan.md",
        "src/qount/legacy/x4/combo.py",
        "scripts/archive/research-legacy/x4/x4_combo.py",
    )
    cta_sources = _source_hashes(
        "docs/archive/legacy/line-a/rebuild-plan.md",
        "src/qount/legacy/l1/l1_cross_asset.py",
        "src/qount/legacy/line_a/cta_sim.py",
    )
    return {
        "cxd_family": ResearchEvidenceReadinessRecord.create(
            evidence_type="historical_family_mapping",
            scope="cxd_trend_carry",
            status="available",
            available_evidence={"mapping": asdict(cxd_mapping)},
            missing_evidence={},
            source_hashes=cxd_sources,
            supports_research=True,
            supports_candidate_pnl=False,
        ),
        "cta_r_family": ResearchEvidenceReadinessRecord.create(
            evidence_type="historical_family_mapping",
            scope="cta_r_cross_asset",
            status="available",
            available_evidence={"mapping": asdict(cta_mapping)},
            missing_evidence={},
            source_hashes=cta_sources,
            supports_research=True,
            supports_candidate_pnl=False,
        ),
    }


def _lifecycle_records() -> dict[str, ResearchEvidenceReadinessRecord]:
    contract_sources = _source_hashes(
        "src/qount/governance/research_records.py",
    )
    return {
        "cxd_lifecycle": ResearchEvidenceReadinessRecord.create(
            evidence_type="point_in_time_lifecycle",
            scope="binance_spot_um_coinm_cxd",
            status="partial",
            available_evidence={
                "contract": "PointInTimeSymbolLifecycle/PointInTimeUniverseRevision",
                "selection_semantics": "valid_from <= as_of < valid_to",
                "future_membership_backfill_forbidden": True,
            },
            missing_evidence={
                "historical_listing_intervals": "not_present_in_local_repository",
                "historical_delisting_intervals": "not_present_in_local_repository",
                "historical_rule_revisions": "not_present_in_local_repository",
                "current_dataset_id": "requires_point_in_time_venue_collection",
            },
            source_hashes=contract_sources,
            supports_research=True,
            supports_candidate_pnl=False,
        ),
        "cta_r_lifecycle": ResearchEvidenceReadinessRecord.create(
            evidence_type="point_in_time_lifecycle",
            scope="cta_r_cross_asset_etf_futures",
            status="partial",
            available_evidence={
                "static_research_universe_source": "src/qount/legacy/l1/l1_cross_asset.py",
                "future_membership_backfill_forbidden": True,
            },
            missing_evidence={
                "historical_listing_delisting_intervals": "not_present_in_local_repository",
                "tracking_instrument_revisions": "not_captured_point_in_time",
                "venue_tradability_intervals": "requires_account_and_venue_specific_collection",
                "current_dataset_id": "requires_point_in_time_cross_asset_collection",
            },
            source_hashes={
                **contract_sources,
                **_source_hashes("src/qount/legacy/l1/l1_cross_asset.py"),
            },
            supports_research=True,
            supports_candidate_pnl=False,
        ),
    }


def _cost_records() -> dict[str, ResearchEvidenceReadinessRecord]:
    return {
        "cxd_cost": ResearchEvidenceReadinessRecord.create(
            evidence_type="cost_model",
            scope="cxd_trend_carry_revalidation_v4",
            status="partial",
            available_evidence={
                "frozen_assumptions": {
                    "trend_taker_fee_rate": 0.0005,
                    "trend_adverse_slippage_rate": 0.0002,
                    "carry_spot_maker_fee_rate": 0.00075,
                    "carry_dated_maker_fee_rate": 0.0002,
                    "carry_maker_fill_assumption": "upper_bound_only",
                },
                "cost_doubling_required": True,
            },
            missing_evidence={
                "point_in_time_fee_tiers": "account_tier_history_not_captured",
                "maker_fill_probability": "requires_shadow_execution_evidence",
                "adverse_selection": "requires_order_level_evidence",
                "funding_and_basis_history": "requires_complete_current_dataset",
                "legging_and_roll_slippage": "requires_multi_leg_execution_evidence",
            },
            source_hashes=_source_hashes(
                "scripts/archive/research-legacy/x4/x4_combo.py",
                "src/qount/legacy/x4/backtest.py",
                "src/qount/legacy/rv_c/backtest.py",
            ),
            supports_research=True,
            supports_candidate_pnl=False,
        ),
        "cta_r_cost": ResearchEvidenceReadinessRecord.create(
            evidence_type="cost_model",
            scope="cta_r_cross_asset_revalidation_v4",
            status="partial",
            available_evidence={
                "historical_simulation_cost_per_side_rate": 0.0002,
                "documented_real_etf_cost_range_bps": [5.0, 10.0],
                "cost_doubling_required": True,
            },
            missing_evidence={
                "broker_commission_schedule": "account_specific_schedule_not_captured",
                "tax_and_exchange_fees": "venue_specific_inputs_not_frozen",
                "tracking_error": "point_in_time_instrument_series_not_collected",
                "market_impact_and_slippage": "requires_current_capacity_evidence",
                "futures_roll_cost_if_used": "venue_contract_not_selected",
            },
            source_hashes=_source_hashes(
                "docs/archive/legacy/line-a/rebuild-plan.md",
                "src/qount/legacy/line_a/cta_sim.py",
            ),
            supports_research=True,
            supports_candidate_pnl=False,
        ),
    }


def _nav_records(runtime) -> dict[str, ResearchEvidenceReadinessRecord]:
    runtime_sources = {
        "virtual_runtime_result": str(runtime.result["result_hash"]),
        "virtual_runtime_snapshot": runtime.ledger_snapshot.snapshot_hash,
        "virtual_runtime_manifest": str(runtime.manifest["manifest_hash"]),
        **_source_hashes("src/qount/portfolio/virtual_runtime.py"),
    }
    fixture = {
        "integration_fixture": {
            "status": "available",
            "evidence_class": runtime.result["evidence_class"],
            "result_hash": runtime.result["result_hash"],
            "runtime_snapshot_hash": runtime.ledger_snapshot.snapshot_hash,
            "accounting_passed": runtime.result["accounting_passed"],
            "reconciliation_passed": runtime.result["reconciliation_passed"],
            "candidate_performance_evidence": False,
        },
        "nav_contract": (
            "Signal NAV / Standalone Executable NAV / Portfolio Realized NAV"
        ),
    }
    return {
        "cxd_nav": ResearchEvidenceReadinessRecord.create(
            evidence_type="standalone_nav_readiness",
            scope="cxd_trend_carry_revalidation_v4",
            status="partial",
            available_evidence=fixture,
            missing_evidence={
                "trend_signal_nav": "current_point_in_time_dataset_not_available",
                "trend_standalone_executable_nav": "current_cost_and_data_inputs_incomplete",
                "carry_signal_nav": "current_basis_dataset_not_available",
                "carry_standalone_executable_nav": "current_cost_and_leg_evidence_incomplete",
                "beta_residual_return": "candidate_return_series_not_computed",
                "portfolio_realized_nav": "not_applicable_before_virtual_candidate_run",
            },
            source_hashes=runtime_sources,
            supports_research=True,
            supports_candidate_pnl=False,
        ),
        "cta_r_nav": ResearchEvidenceReadinessRecord.create(
            evidence_type="standalone_nav_readiness",
            scope="cta_r_cross_asset_revalidation_v4",
            status="partial",
            available_evidence=fixture,
            missing_evidence={
                "signal_nav": "current_point_in_time_dataset_not_available",
                "standalone_executable_nav": "current_cost_and_lifecycle_inputs_incomplete",
                "beta_residual_return": "candidate_return_series_not_computed",
                "portfolio_realized_nav": "not_applicable_before_virtual_candidate_run",
            },
            source_hashes=runtime_sources,
            supports_research=True,
            supports_candidate_pnl=False,
        ),
    }


def build_bundle(output_root: Path, runtime_directory: Path) -> Path:
    runtime = read_multi_sleeve_virtual_artifact(runtime_directory)
    evidence = {
        **_family_records(),
        **_lifecycle_records(),
        **_cost_records(),
        **_nav_records(runtime),
    }
    candidates = build_r0_candidate_records(evidence)
    experiment = GlobalExperimentRecord.create(
        hypothesis_family="architecture_multi_sleeve_runtime",
        trial_number_within_family=1,
        research_question=(
            "Can the standard multi-sleeve contracts complete deterministic virtual "
            "execution, accounting, reconciliation, and immutable replay?"
        ),
        economic_mechanism="architecture contract integration fixture; no alpha claim",
        baseline_ids=("standard_contracts_v1",),
        preregistered_primary_metric="accounting_and_reconciliation_both_pass",
        preregistered_failure_conditions=(
            "runtime_chain_incomplete",
            "accounting_residual_nonzero",
            "reconciliation_failed",
            "artifact_replay_or_hash_failed",
        ),
        allowed_sensitivity_range={
            "sleeve_count": [0, 1, 2],
            "cost_model": "frozen_fixture",
        },
        dataset_ids=("deterministic_multi_sleeve_contract_fixture_v1",),
        data_role="discovery_pool",
        code_hash=_file_hash("src/qount/portfolio/virtual_runtime.py"),
        config_hash=canonical_hash(
            {
                "snapshot_id": runtime.batch.snapshot.snapshot_id,
                "strategy_ids": runtime.result["strategy_ids"],
                "cost_model_hash": runtime.result["cost_model_hash"],
            }
        ),
        source_hashes={
            "runtime_manifest": str(runtime.manifest["manifest_hash"]),
            "runtime_snapshot": runtime.ledger_snapshot.snapshot_hash,
        },
        first_result_observed_at=str(runtime.result["completed_at"]),
        result_artifact_hash=str(runtime.result["result_hash"]),
        decision="retain",
        contamination_notes=(
            "synthetic contract fixture; not candidate performance evidence",
            "orders_authorized=false and promotion_evidence=false",
        ),
    )
    errors = experiment.validate()
    if errors:
        raise RuntimeError("r0_global_experiment_invalid:" + ",".join(errors))

    records: dict[str, object] = {
        **{f"evidence-{name}.json": asdict(record) for name, record in evidence.items()},
        "global-experiment-multi-sleeve-runtime.json": asdict(experiment),
        **{
            f"candidate-{record.candidate_id}.json": asdict(record)
            for record in candidates
        },
    }
    bundle_id = canonical_hash(
        {
            "schema_version": R0_BUNDLE_SCHEMA_VERSION,
            "record_hashes": {
                name: canonical_hash(value) for name, value in sorted(records.items())
            },
            "runtime_result_hash": runtime.result["result_hash"],
        }
    )
    directory = output_root / bundle_id
    if directory.exists():
        _verify_bundle(directory)
        return directory

    output_root.mkdir(parents=True, exist_ok=True)
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    _fsync_directory(output_root)
    for file_name, value in sorted(records.items()):
        _write_once(directory / file_name, value)
    manifest_core = {
        "schema_version": R0_BUNDLE_SCHEMA_VERSION,
        "artifact_type": "r0_research_readiness_bundle",
        "bundle_id": bundle_id,
        "runtime_result_hash": runtime.result["result_hash"],
        "runtime_manifest_hash": runtime.manifest["manifest_hash"],
        "evidence_record_count": len(evidence),
        "candidate_record_count": len(candidates),
        "global_experiment_count": 1,
        "candidate_pnl_ready": False,
        "orders_authorized": False,
        "promotion_evidence": False,
        "member_files": _member_references(directory),
    }
    manifest = manifest_core | {"manifest_hash": canonical_hash(manifest_core)}
    _write_once(directory / "manifest.json", manifest)
    _fsync_directory(directory)
    _verify_bundle(directory)
    return directory


def _default_runtime_directory() -> Path:
    root = ROOT / "state" / "research_governance" / "runtime"
    from scripts.research.run_multi_sleeve_virtual_runtime import run_fixture

    return run_fixture(root).directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "state" / "research_governance" / "r0"),
    )
    parser.add_argument("--virtual-runtime-artifact")
    args = parser.parse_args()
    runtime_directory = (
        Path(args.virtual_runtime_artifact)
        if args.virtual_runtime_artifact
        else _default_runtime_directory()
    )
    directory = build_bundle(Path(args.output_dir), runtime_directory)
    manifest = _verify_bundle(directory)
    print(f"artifact_directory={directory}")
    print(f"bundle_id={manifest['bundle_id']}")
    print(f"manifest_hash={manifest['manifest_hash']}")
    print("family_mapping=available")
    print("lifecycle=partial")
    print("cost_model=partial")
    print("candidate_standalone_nav=unavailable_with_reasons")
    print("research_execution_allowed=true")
    print("candidate_pnl_ready=false")
    print("orders_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
