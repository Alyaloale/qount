#!/usr/bin/env python3
"""R0-RECORD: backfill governance records with real R0-DATA and R0-RUNTIME evidence.

Reads the R0-DATA bundle (lifecycle, source hashes) and R0-RUNTIME bundle
(NAV artifacts, cost model hashes), then produces updated v5 evidence records
and candidate records with real dataset IDs, cost model hashes, and NAV
artifact references.

Writes a new R0 v5 bundle (0700/0600, write-once, manifest-verified).

Usage:
    python3 scripts/research/governance/update_r0_records_v5.py \
        --data-bundle state/research_governance/r0_data/<bundle_id> \
        --runtime-bundle state/research_governance/r0_runtime/<bundle_id> \
        --output-dir state/research_governance/r0
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
from typing import Any
from typing import Mapping

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash
from qount.governance import CandidateRevalidationRecord
from qount.governance import GlobalExperimentRecord
from qount.governance import HistoricalFamilyMapping
from qount.governance import ResearchEvidenceReadinessRecord
from qount.models import utc_now

R0_V5_SCHEMA_VERSION = 1


# --- Write-once helpers (same pattern as build_r0_records.py) ---------------


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        .encode("ascii") + b"\n"
    )


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hashes(*relative_paths: str) -> dict[str, str]:
    return {p: _file_hash(ROOT / p) for p in relative_paths}


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_once(path: Path, value: object) -> None:
    raw = _canonical_bytes(value)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as h:
            h.write(raw)
            h.flush()
            os.fsync(h.fileno())
        fd = -1
        os.link(tmp, path)
        _fsync_directory(path.parent)
        if path.read_bytes() != raw:
            raise RuntimeError(f"r0_v5_readback_mismatch:{path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"r0_v5_mode_invalid:{path}")
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp.exists():
            tmp.unlink()


def _member_refs(directory: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for p in sorted(directory.iterdir()):
        if not p.is_file() or p.name == "manifest.json":
            continue
        raw = p.read_bytes()
        refs.append({"path": p.name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return refs


def _verify_bundle(directory: Path) -> dict[str, Any]:
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("r0_v5_dir_invalid")
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise RuntimeError("r0_v5_dir_mode_invalid")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="ascii"))
    core = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    if manifest.get("manifest_hash") != canonical_hash(core):
        raise RuntimeError("r0_v5_manifest_hash_invalid")
    if manifest.get("bundle_id") != directory.name:
        raise RuntimeError("r0_v5_identity_invalid")
    if manifest.get("member_files") != _member_refs(directory):
        raise RuntimeError("r0_v5_member_mismatch")
    return manifest


def _read_manifest(bundle_dir: Path) -> dict[str, Any]:
    return json.loads((bundle_dir / "manifest.json").read_text(encoding="ascii"))


# --- Evidence record builders (v5 with real data) ---------------------------


def _v5_cxd_lifecycle(
    data_manifest: dict[str, Any],
    source_hashes: dict[str, str],
) -> ResearchEvidenceReadinessRecord:
    data_bundle_id = data_manifest.get("bundle_id", "")
    return ResearchEvidenceReadinessRecord.create(
        evidence_type="point_in_time_lifecycle",
        scope="cxd_trend_carry_v5",
        status="partial",
        available_evidence={
            "contract": "PointInTimeSymbolLifecycle/PointInTimeUniverseRevision",
            "future_membership_backfill_forbidden": True,
            "selection_semantics": "valid_from <= as_of < valid_to",
            "r0_data_bundle_id": data_bundle_id,
            "um_lifecycle_records": data_manifest.get("lifecycle_summaries", [{}])[0].get("total_symbols", 0)
                if data_manifest.get("lifecycle_summaries") else 0,
            "um_active_symbols": data_manifest.get("lifecycle_summaries", [{}])[0].get("active_symbols", 0)
                if data_manifest.get("lifecycle_summaries") else 0,
            "quarterly_revisions": data_manifest.get("revision_count", 0),
        },
        missing_evidence={
            "historical_delisted_symbols": "exchange_info_only_shows_current_symbols",
            "historical_rule_revisions": "changelog_history_not_captured",
            "spot_listing_dates": "onboard_date_absent_in_spot_exchange_info",
        },
        source_hashes=source_hashes,
        supports_research=True,
        supports_candidate_pnl=True,
    )


def _v5_cxd_cost(
    runtime_manifest: dict[str, Any],
    source_hashes: dict[str, str],
) -> ResearchEvidenceReadinessRecord:
    trend_cost = runtime_manifest.get("trend_cost_model", {})
    carry_cost = runtime_manifest.get("carry_cost_model", {})
    trend_cost_hash = trend_cost.get("model_hash", "")
    carry_cost_hash = carry_cost.get("model_hash", "") if carry_cost else ""
    trend_incomplete = runtime_manifest.get("trend_standalone_nav", {}).get("cost_incomplete", True)
    carry_incomplete = runtime_manifest.get("carry_standalone_nav", {}).get("cost_incomplete", True) if runtime_manifest.get("carry_standalone_nav") else True

    return ResearchEvidenceReadinessRecord.create(
        evidence_type="cost_model",
        scope="cxd_trend_carry_v5",
        status="partial",
        available_evidence={
            "frozen_cost_model": "FrozenCostModel_hash_bound",
            "trend_cost_model_hash": trend_cost_hash,
            "carry_cost_model_hash": carry_cost_hash,
            "trend_cost_components": [c["name"] for c in trend_cost.get("components", [])],
            "carry_cost_components": [c["name"] for c in carry_cost.get("components", [])] if carry_cost else [],
            "cost_doubling_required": True,
            "funding_and_basis_history": "available_from_r0_runtime",
        },
        missing_evidence={
            "adverse_selection": "requires_order_level_evidence",
            "maker_fill_probability": "requires_shadow_execution_evidence",
            "legging_and_roll_slippage": "requires_multi_leg_execution_evidence",
            "point_in_time_fee_tiers": "account_tier_history_not_captured",
        },
        source_hashes=source_hashes,
        supports_research=True,
        supports_candidate_pnl=not (trend_incomplete or carry_incomplete),
    )


def _v5_cxd_nav(
    runtime_manifest: dict[str, Any],
    source_hashes: dict[str, str],
) -> ResearchEvidenceReadinessRecord:
    trend_signal = runtime_manifest.get("trend_signal_nav", {})
    trend_standalone = runtime_manifest.get("trend_standalone_nav", {})
    carry_signal = runtime_manifest.get("carry_signal_nav")
    carry_standalone = runtime_manifest.get("carry_standalone_nav")
    runtime_bundle_id = runtime_manifest.get("bundle_id", "")

    available: dict[str, Any] = {
        "nav_contract": "Signal NAV / Standalone Executable NAV / Portfolio Realized NAV",
        "r0_runtime_bundle_id": runtime_bundle_id,
        "trend_signal_nav": trend_signal.get("final_nav", 0.0),
        "trend_signal_return": trend_signal.get("total_return", 0.0),
        "trend_standalone_nav": trend_standalone.get("final_nav", 0.0),
        "trend_standalone_return": trend_standalone.get("total_return", 0.0),
        "trend_total_cost": trend_standalone.get("total_cost", 0.0),
        "trend_cost_incomplete": trend_standalone.get("cost_incomplete", True),
    }
    missing: dict[str, str] = {}

    if carry_signal and carry_standalone:
        available["carry_signal_nav"] = carry_signal.get("final_nav", 0.0)
        available["carry_signal_return"] = carry_signal.get("total_return", 0.0)
        available["carry_standalone_nav"] = carry_standalone.get("final_nav", 0.0)
        available["carry_standalone_return"] = carry_standalone.get("total_return", 0.0)
        available["carry_total_cost"] = carry_standalone.get("total_cost", 0.0)
        available["carry_cost_incomplete"] = carry_standalone.get("cost_incomplete", True)
    else:
        missing["carry_signal_nav"] = "runtime_carry_leg_not_computed"

    missing["beta_residual_return"] = "candidate_return_series_not_computed"
    missing["portfolio_realized_nav"] = "not_applicable_before_virtual_candidate_run"

    cost_incomplete = trend_standalone.get("cost_incomplete", True)
    if carry_standalone:
        cost_incomplete = cost_incomplete or carry_standalone.get("cost_incomplete", True)

    return ResearchEvidenceReadinessRecord.create(
        evidence_type="standalone_nav_readiness",
        scope="cxd_trend_carry_v5",
        status="partial",
        available_evidence=available,
        missing_evidence=missing,
        source_hashes=source_hashes,
        supports_research=True,
        supports_candidate_pnl=not cost_incomplete,
    )


def _v5_cta_r_lifecycle(source_hashes: dict[str, str]) -> ResearchEvidenceReadinessRecord:
    return ResearchEvidenceReadinessRecord.create(
        evidence_type="point_in_time_lifecycle",
        scope="cta_r_cross_asset_v5",
        status="partial",
        available_evidence={
            "future_membership_backfill_forbidden": True,
            "static_research_universe_source": "src/qount/legacy/l1/l1_cross_asset.py",
        },
        missing_evidence={
            "current_dataset_id": "requires_point_in_time_cross_asset_collection",
            "historical_listing_delisting_intervals": "not_present_in_local_repository",
            "tracking_instrument_revisions": "not_captured_point_in_time",
            "venue_tradability_intervals": "requires_account_and_venue_specific_collection",
        },
        source_hashes=source_hashes,
        supports_research=True,
        supports_candidate_pnl=False,
    )


def _v5_cta_r_cost(source_hashes: dict[str, str]) -> ResearchEvidenceReadinessRecord:
    return ResearchEvidenceReadinessRecord.create(
        evidence_type="cost_model",
        scope="cta_r_cross_asset_v5",
        status="partial",
        available_evidence={
            "frozen_cost_model": "FrozenCostModel_hash_bound",
            "etf_cost_components": ["etf_fee", "spread", "slippage", "tax", "fx_cost"],
            "futures_cost_components": ["futures_fee", "spread", "slippage", "roll_cost"],
        },
        missing_evidence={
            "current_fee_tiers": "requires_brokerage_account_evidence",
            "tax_jurisdiction": "requires_account_specific_evidence",
            "roll_history": "requires_continuous_futures_data",
        },
        source_hashes=source_hashes,
        supports_research=True,
        supports_candidate_pnl=False,
    )


def _v5_cta_r_nav(source_hashes: dict[str, str]) -> ResearchEvidenceReadinessRecord:
    return ResearchEvidenceReadinessRecord.create(
        evidence_type="standalone_nav_readiness",
        scope="cta_r_cross_asset_v5",
        status="partial",
        available_evidence={
            "nav_contract": "Signal NAV / Standalone Executable NAV / Portfolio Realized NAV",
            "runtime_status": "not_yet_executed_for_cta_r",
        },
        missing_evidence={
            "trend_signal_nav": "current_cross_asset_dataset_not_available",
            "trend_standalone_executable_nav": "current_cost_and_data_inputs_incomplete",
            "beta_residual_return": "candidate_return_series_not_computed",
            "portfolio_realized_nav": "not_applicable_before_virtual_candidate_run",
        },
        source_hashes=source_hashes,
        supports_research=True,
        supports_candidate_pnl=False,
    )


# --- Main -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R0-RECORD v5 update")
    parser.add_argument("--data-bundle", required=True, help="Path to R0-DATA bundle directory")
    parser.add_argument("--runtime-bundle", required=True, help="Path to R0-RUNTIME bundle directory")
    parser.add_argument("--output-dir", default=str(ROOT / "state" / "research_governance" / "r0"))
    args = parser.parse_args(argv)

    data_dir = Path(args.data_bundle)
    runtime_dir = Path(args.runtime_bundle)

    if not data_dir.is_dir() or not (data_dir / "manifest.json").exists():
        print(f"ERROR: R0-DATA bundle not found: {data_dir}", file=sys.stderr)
        return 1
    if not runtime_dir.is_dir() or not (runtime_dir / "manifest.json").exists():
        print(f"ERROR: R0-RUNTIME bundle not found: {runtime_dir}", file=sys.stderr)
        return 1

    data_manifest = _read_manifest(data_dir)
    runtime_manifest = _read_manifest(runtime_dir)
    observed_at = utc_now().isoformat()

    print(f"R0-DATA bundle: {data_manifest.get('bundle_id', '?')[:16]}...")
    print(f"R0-RUNTIME bundle: {runtime_manifest.get('bundle_id', '?')[:16]}...")

    # --- Source hashes ---
    cxd_sources = _source_hashes(
        "docs/archive/legacy/x4-rv/crypto-x4-plan.md",
        "docs/archive/legacy/x4-rv/rv-c-plan.md",
        "src/qount/research_data/cost_model.py",
        "src/qount/research_data/nav.py",
        "scripts/research/governance/run_r0_runtime.py",
    )
    cta_sources = _source_hashes(
        "docs/archive/legacy/line-a/rebuild-plan.md",
        "src/qount/legacy/l1/l1_cross_asset.py",
        "src/qount/legacy/line_a/cta_sim.py",
        "src/qount/research_data/cost_model.py",
    )
    family_sources = _source_hashes(
        "docs/archive/legacy/x4-rv/crypto-x4-plan.md",
        "docs/archive/legacy/x4-rv/rv-c-plan.md",
        "docs/archive/legacy/line-a/rebuild-plan.md",
        "src/qount/legacy/x4/combo.py",
        "src/qount/legacy/l1/l1_cross_asset.py",
    )

    # --- Family mappings (same as v4) ---
    cxd_mapping = HistoricalFamilyMapping.create(
        current_family="cxd_trend_carry",
        historical_family_ids=("x4_s7_trend_portfolio", "rv_c_basis_carry", "x4_cxd_combo_v1_9"),
        mapping_reason="CxD revalidation family inherits mechanism labels only; no historical promotion.",
        mapping_status="confirmed",
    )
    cta_mapping = HistoricalFamilyMapping.create(
        current_family="cta_r_cross_asset",
        historical_family_ids=("l1_cross_asset_v1", "cta_r_selection_free_a_share_etf"),
        mapping_reason="CTA-R revalidation requires new point-in-time, cost, and venue evidence.",
        mapping_status="confirmed",
    )

    # --- Evidence records (v5) ---
    evidence: dict[str, ResearchEvidenceReadinessRecord] = {
        "cxd_family": ResearchEvidenceReadinessRecord.create(
            evidence_type="historical_family_mapping",
            scope="cxd_trend_carry_v5",
            status="available",
            available_evidence={"mapping": asdict(cxd_mapping)},
            missing_evidence={},
            source_hashes=family_sources,
            supports_research=True,
            supports_candidate_pnl=False,
        ),
        "cxd_lifecycle": _v5_cxd_lifecycle(data_manifest, cxd_sources),
        "cxd_cost": _v5_cxd_cost(runtime_manifest, cxd_sources),
        "cxd_nav": _v5_cxd_nav(runtime_manifest, cxd_sources),
        "cta_r_family": ResearchEvidenceReadinessRecord.create(
            evidence_type="historical_family_mapping",
            scope="cta_r_cross_asset_v5",
            status="available",
            available_evidence={"mapping": asdict(cta_mapping)},
            missing_evidence={},
            source_hashes=family_sources,
            supports_research=True,
            supports_candidate_pnl=False,
        ),
        "cta_r_lifecycle": _v5_cta_r_lifecycle(cta_sources),
        "cta_r_cost": _v5_cta_r_cost(cta_sources),
        "cta_r_nav": _v5_cta_r_nav(cta_sources),
    }

    for name, record in evidence.items():
        errors = record.validate()
        if errors:
            print(f"ERROR: evidence {name} invalid: {errors}", file=sys.stderr)
            return 1

    # --- Candidate records (v5) ---
    cxd_lifecycle = evidence["cxd_lifecycle"]
    cxd_cost = evidence["cxd_cost"]
    cxd_nav = evidence["cxd_nav"]
    cta_lifecycle = evidence["cta_r_lifecycle"]
    cta_cost = evidence["cta_r_cost"]
    cta_nav = evidence["cta_r_nav"]

    common = {
        "untouched_data_ids": (),
        "baseline_ids": ("base_v0.2_frozen_control",),
        "factor_and_beta_plan": {"market": "crypto_market", "momentum": "required", "carry": "required_if_applicable"},
        "tail_scenarios": ("basis_tail", "cost_shock", "gap_and_missing_data"),
        "primary_metric": "cost_adjusted_standalone_executable_nav",
        "kill_tests": ("standalone_nav_non_positive_after_tail", "independent_nav_reconciliation_failure", "point_in_time_data_gap"),
        "trial_budget": 3,
    }

    cxd_candidate = CandidateRevalidationRecord.create(
        candidate_id="cxd-trend-carry-revalidation-v5",
        hypothesis_family="cxd_trend_carry",
        historical_evidence_ids=(evidence["cxd_family"].record_id,),
        current_data_ids=(cxd_lifecycle.record_id, data_manifest.get("bundle_id", "")),
        frozen_cost_model={
            "status": cxd_cost.status,
            "evidence_id": cxd_cost.record_id,
            "evidence_hash": cxd_cost.record_hash,
            "trend_cost_model_hash": runtime_manifest.get("trend_cost_model", {}).get("model_hash", ""),
            "carry_cost_model_hash": runtime_manifest.get("carry_cost_model", {}).get("model_hash", "") if runtime_manifest.get("carry_cost_model") else "",
            "candidate_pnl_ready": cxd_cost.supports_candidate_pnl,
        },
        standalone_nav_artifacts=(cxd_nav.record_id, runtime_manifest.get("bundle_id", "")),
        venue_and_account_scope="historical_discovery_shadow_virtual; no carry order permission",
        execution_contract={
            "mode": "research_virtual",
            "carry": "observation_shadow_virtual",
            "research_execution_allowed": True,
            "orders_allowed": False,
            "blocks_local_progress": False,
            "trial_budget_blocks_research": False,
            "candidate_pnl_ready": all(r.supports_candidate_pnl for r in (cxd_lifecycle, cxd_cost, cxd_nav)),
        },
        owner_authorization_state="owner_authorized_research",
        decision="active_research",
        **common,
    )

    cta_candidate = CandidateRevalidationRecord.create(
        candidate_id="cta-r-cross-asset-revalidation-v5",
        hypothesis_family="cta_r_cross_asset",
        historical_evidence_ids=(evidence["cta_r_family"].record_id,),
        current_data_ids=(cta_lifecycle.record_id,),
        frozen_cost_model={
            "status": cta_cost.status,
            "evidence_id": cta_cost.record_id,
            "evidence_hash": cta_cost.record_hash,
            "candidate_pnl_ready": cta_cost.supports_candidate_pnl,
        },
        standalone_nav_artifacts=(cta_nav.record_id,),
        venue_and_account_scope="research_cross_asset_only; no Binance wallet order permission",
        execution_contract={
            "mode": "research_virtual",
            "research_execution_allowed": True,
            "orders_allowed": False,
            "blocks_local_progress": False,
            "trial_budget_blocks_research": False,
            "candidate_pnl_ready": all(r.supports_candidate_pnl for r in (cta_lifecycle, cta_cost, cta_nav)),
        },
        owner_authorization_state="owner_authorized_research",
        decision="active_research",
        **common,
    )

    for candidate in (cxd_candidate, cta_candidate):
        errors = candidate.validate()
        if errors:
            print(f"ERROR: candidate {candidate.candidate_id} invalid: {errors}", file=sys.stderr)
            return 1

    # --- GlobalExperimentRecord ---
    runtime_code_hash = _file_hash(ROOT / "scripts/research/governance/run_r0_runtime.py")
    config_hash = canonical_hash({
        "symbol": runtime_manifest.get("symbol", ""),
        "fast": runtime_manifest.get("trend_config", {}).get("fast", 0),
        "slow": runtime_manifest.get("trend_config", {}).get("slow", 0),
        "regime_sma": runtime_manifest.get("trend_config", {}).get("regime_sma", 0),
    })
    global_exp = GlobalExperimentRecord.create(
        hypothesis_family="cxd_trend_carry",
        trial_number_within_family=1,
        research_question="Does the CxD trend leg produce positive Standalone Executable NAV after frozen costs?",
        economic_mechanism="Trend following with SMA crossover, regime gate, frozen taker fee + slippage + funding",
        baseline_ids=("base_v0.2_frozen_control",),
        preregistered_primary_metric="cost_adjusted_standalone_executable_nav",
        preregistered_failure_conditions=("standalone_nav_non_positive_after_tail",),
        allowed_sensitivity_range={"cost_doubling": "2x", "delay": "1_bar"},
        dataset_ids=(data_manifest.get("bundle_id", ""),),
        data_role="consumed_historical_discovery_pool",
        untouched_data_ids=(),
        code_hash=runtime_code_hash,
        config_hash=config_hash,
        source_hashes={
            "r0_data_bundle": data_manifest.get("bundle_id", ""),
            "r0_runtime_bundle": runtime_manifest.get("bundle_id", ""),
            "um_closes_hash": runtime_manifest.get("um_closes_hash", ""),
        },
        first_result_observed_at=observed_at,
        reviewer_observations=({"role": "automated", "at": observed_at, "note": "R0-RUNTIME v1 NAV computed"},),
        result_artifact_hash=runtime_manifest.get("bundle_id", ""),
        decision="active_research",
        contamination_notes=("Historical discovery pool; results are consumed and not OOS.",),
    )
    errors = global_exp.validate()
    if errors:
        print(f"ERROR: global experiment invalid: {errors}", file=sys.stderr)
        return 1

    # --- Write bundle ---
    bundle_core: dict[str, Any] = {
        "schema_version": R0_V5_SCHEMA_VERSION,
        "artifact_type": "r0_research_readiness_bundle",
        "revision": "v5",
        "observed_at": observed_at,
        "candidate_pnl_ready": cxd_candidate.execution_contract.get("candidate_pnl_ready", False),
        "candidate_record_count": 2,
        "evidence_record_count": 8,
        "global_experiment_count": 1,
        "r0_data_bundle_id": data_manifest.get("bundle_id", ""),
        "r0_runtime_bundle_id": runtime_manifest.get("bundle_id", ""),
        "orders_authorized": False,
        "promotion_evidence": False,
    }

    output_base = Path(args.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)
    bundle_id = hashlib.sha256(canonical_hash(bundle_core).encode("ascii")).hexdigest()
    bundle_dir = output_base / bundle_id

    if bundle_dir.exists():
        print(f"ERROR: bundle already exists: {bundle_dir}", file=sys.stderr)
        return 1

    bundle_dir.mkdir(mode=0o700)

    # Write evidence records
    for name, record in sorted(evidence.items()):
        _write_once(bundle_dir / f"evidence-{name}.json", asdict(record))

    # Write candidate records
    _write_once(bundle_dir / "candidate-cxd-trend-carry-revalidation-v5.json", asdict(cxd_candidate))
    _write_once(bundle_dir / "candidate-cta-r-cross-asset-revalidation-v5.json", asdict(cta_candidate))

    # Write global experiment
    _write_once(bundle_dir / "global-experiment-cxd-trend-runtime.json", asdict(global_exp))

    # Write manifest
    manifest = dict(bundle_core)
    manifest["bundle_id"] = bundle_id
    manifest["member_files"] = _member_refs(bundle_dir)
    manifest["manifest_hash"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    _write_once(bundle_dir / "manifest.json", manifest)

    # Verify
    verified = _verify_bundle(bundle_dir)
    print(f"\nR0 v5 bundle written and verified: {bundle_dir}")
    print(f"  bundle_id: {bundle_id}")
    print(f"  members: {len(verified['member_files'])}")
    print(f"  candidate_pnl_ready: {verified['candidate_pnl_ready']}")
    print(f"  orders_authorized: {verified['orders_authorized']}")

    # Print key results
    cxd_nav_record = evidence["cxd_nav"]
    print(f"\n  C×D trend Signal NAV: {runtime_manifest.get('trend_signal_nav', {}).get('final_nav', 'N/A')}")
    print(f"  C×D trend Standalone NAV: {runtime_manifest.get('trend_standalone_nav', {}).get('final_nav', 'N/A')}")
    if runtime_manifest.get("carry_standalone_nav"):
        print(f"  C×D carry Signal NAV: {runtime_manifest.get('carry_signal_nav', {}).get('final_nav', 'N/A')}")
        print(f"  C×D carry Standalone NAV: {runtime_manifest.get('carry_standalone_nav', {}).get('final_nav', 'N/A')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
