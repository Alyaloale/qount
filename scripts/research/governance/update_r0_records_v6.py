#!/usr/bin/env python3
"""R0-RECORD v6: revision governance bundle binding corrected R0 artifacts.

Reads the corrected runtime (Round 2), decision (Round 3), and advancement
(Round 4) bundle manifests, plus the v5 governance bundle for unchanged
evidence records.  Produces a v6 governance bundle with:

- Updated GlobalExperimentRecord pointing to the corrected runtime bundle
- Updated CandidateRevalidationRecord with REVISE decision (kill test 3 FAIL)
- decision_bundle_id and advancement_bundle_id in the manifest
- candidate_pnl_ready=False (carry cost_incomplete=True)
- supersedes v5 bundle

Usage:
    python3 scripts/research/governance/update_r0_records_v6.py \
        --runtime-bundle state/research_governance/r0_runtime/<id> \
        --decision-bundle state/research_governance/r0_decision/<id> \
        --advancement-bundle state/research_governance/r0_advancement/<id> \
        --v5-bundle state/research_governance/r0/47aa0e88... \
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
from qount.models import utc_now

R0_V6_SCHEMA_VERSION = 1


# --- Write-once helpers (same pattern as v5) --------------------------------


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        .encode("ascii") + b"\n"
    )


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
            raise RuntimeError(f"r0_v6_readback_mismatch:{path}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RuntimeError(f"r0_v6_mode_invalid:{path}")
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


def _verify_bundle(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    core = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    if manifest.get("manifest_hash") != canonical_hash(core):
        raise RuntimeError("r0_v6_manifest_hash_invalid")
    return manifest


# --- Main -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R0-RECORD v6 revision bundle")
    parser.add_argument("--runtime-bundle", required=True)
    parser.add_argument("--decision-bundle", required=True)
    parser.add_argument("--advancement-bundle", required=True)
    parser.add_argument("--v5-bundle", required=True,
                        help="Path to the v5 governance bundle (for evidence records)")
    parser.add_argument("--output-dir", default=str(ROOT / "state" / "research_governance" / "r0"))
    args = parser.parse_args(argv)

    observed_at = utc_now().isoformat()

    # --- Read corrected bundle manifests ---
    rt_manifest = json.loads((Path(args.runtime_bundle) / "manifest.json").read_text(encoding="ascii"))
    dec_manifest = json.loads((Path(args.decision_bundle) / "manifest.json").read_text(encoding="ascii"))
    adv_manifest = json.loads((Path(args.advancement_bundle) / "manifest.json").read_text(encoding="ascii"))

    rt_bundle_id = rt_manifest.get("bundle_id", "")
    dec_bundle_id = dec_manifest.get("bundle_id", "")
    adv_bundle_id = adv_manifest.get("bundle_id", "")

    v5_manifest = json.loads((Path(args.v5_bundle) / "manifest.json").read_text(encoding="ascii"))
    v5_bundle_id = v5_manifest.get("bundle_id", "")

    print(f"Runtime bundle:     {rt_bundle_id[:16]}...")
    print(f"Decision bundle:    {dec_bundle_id[:16]}...")
    print(f"Advancement bundle: {adv_bundle_id[:16]}...")
    print(f"Supersedes v5:      {v5_bundle_id[:16]}...")

    # --- Read corrected results ---
    rt_trend_nav = rt_manifest.get("trend_standalone_nav", {})
    rt_carry_nav = rt_manifest.get("carry_standalone_nav", {})
    trend_final = rt_trend_nav.get("final_nav", 0.0)
    carry_final = rt_carry_nav.get("final_nav", 0.0)
    carry_incomplete = rt_carry_nav.get("cost_incomplete", True)
    candidate_pnl_ready = rt_manifest.get("candidate_pnl_ready", False)

    # Read candidate config from runtime
    rt_cfg = rt_manifest.get("trend_config", {})
    config_hash = rt_cfg.get("config_hash", "")

    # Read decision results
    trend_decision = dec_manifest.get("trend_decision", {})
    carry_decision = dec_manifest.get("carry_decision", {})
    trend_verdict = trend_decision.get("decision", "unknown")
    carry_verdict = carry_decision.get("decision", "unknown")

    print(f"\nCorrected results:")
    print(f"  Trend Standalone NAV: {trend_final:.4f}  decision={trend_verdict}")
    print(f"  Carry Standalone NAV: {carry_final:.4f}  decision={carry_verdict}")
    print(f"  candidate_pnl_ready: {candidate_pnl_ready}")

    # --- Build GlobalExperimentRecord ---
    runtime_code_hash = _file_hash(ROOT / "scripts" / "research" / "run_r0_runtime.py")
    global_exp = GlobalExperimentRecord.create(
        hypothesis_family="cxd_trend_carry",
        trial_number_within_family=1,
        research_question="Does the CxD trend leg produce positive Standalone Executable NAV after frozen costs?",
        economic_mechanism="Trend following with SMA crossover, regime gate, frozen taker fee + slippage + funding; carry leg with basis convergence, gross<=1, additive NAV",
        baseline_ids=("base_v0.2_frozen_control",),
        preregistered_primary_metric="cost_adjusted_standalone_executable_nav",
        preregistered_failure_conditions=("standalone_nav_non_positive_after_tail",),
        allowed_sensitivity_range={"cost_doubling": "2x", "delay": "1_bar"},
        dataset_ids=(),  # R0-DATA not available locally
        data_role="consumed_historical_discovery_pool",
        untouched_data_ids=(),
        code_hash=runtime_code_hash,
        config_hash=config_hash,
        source_hashes={
            "r0_runtime_bundle": rt_bundle_id,
            "r0_decision_bundle": dec_bundle_id,
            "r0_advancement_bundle": adv_bundle_id,
            "um_closes_hash": rt_manifest.get("um_closes_hash", ""),
            "candidate_config_hash": config_hash,
        },
        first_result_observed_at=observed_at,
        reviewer_observations=({
            "role": "automated",
            "at": observed_at,
            "note": f"R0 v6 revision: trend NAV {trend_final:.4f} ({trend_verdict}), carry NAV {carry_final:.4f} ({carry_verdict}), candidate_pnl_ready={candidate_pnl_ready}",
        },),
        result_artifact_hash=rt_bundle_id,
        decision="active_research",
        contamination_notes=(
            "Historical discovery pool; results are consumed and not OOS.",
            "Kill test 3 (PIT data gap) FAIL: R0-DATA bundle not available locally.",
            "Carry cost_incomplete=True: collateral/tail costs not yet estimated.",
        ),
    )
    errors = global_exp.validate()
    if errors:
        print(f"ERROR: global experiment invalid: {errors}", file=sys.stderr)
        return 1

    # --- Build CandidateRevalidationRecord (CxD) ---
    cxd_candidate = CandidateRevalidationRecord.create(
        candidate_id="cxd_trend_carry_v6",
        hypothesis_family="cxd_trend_carry",
        historical_evidence_ids=("cxd_family", "cxd_lifecycle"),
        current_data_ids=(rt_bundle_id,),
        untouched_data_ids=(),
        venue_and_account_scope="research_binance_um_spot_perp; no order permission",
        baseline_ids=("base_v0.2_frozen_control",),
        frozen_cost_model={
            "trend_cost_model_hash": rt_manifest.get("trend_cost_model", {}).get("model_hash", ""),
            "carry_cost_model_hash": rt_manifest.get("carry_cost_model", {}).get("model_hash", "") if rt_manifest.get("carry_cost_model") else "",
            "candidate_pnl_ready": candidate_pnl_ready,
        },
        execution_contract={
            "mode": "research_virtual",
            "research_execution_allowed": True,
            "orders_allowed": False,
            "candidate_pnl_ready": candidate_pnl_ready,
            "trend_decision": trend_verdict,
            "carry_decision": carry_verdict,
            "kill_test_3_pass": False,
            "kill_test_3_reason": "R0-DATA bundle not available locally",
        },
        standalone_nav_artifacts=(rt_bundle_id,),
        factor_and_beta_plan={
            "btc_beta_alpha_annualized": adv_manifest.get("results", {}).get("btc_beta_residual", {}).get("alpha_annualized", 0.0),
            "equal_weight_nav": adv_manifest.get("results", {}).get("equal_weight_portfolio", {}).get("final_nav", 0.0),
            "equal_weight_max_dd": adv_manifest.get("results", {}).get("equal_weight_portfolio", {}).get("max_drawdown", 0.0),
        },
        tail_scenarios=("cost_doubling", "delay_1_bar", "missed_fills_10pct", "worse_execution_5x"),
        primary_metric="cost_adjusted_standalone_executable_nav",
        kill_tests=(
            "standalone_nav_non_positive_after_tail",
            "independent_nav_reconciliation_failure",
            "point_in_time_data_gap",
        ),
        trial_budget=1,
        owner_authorization_state="owner_authorized_research",
        decision="active_research",
    )
    errors = cxd_candidate.validate()
    if errors:
        print(f"ERROR: candidate invalid: {errors}", file=sys.stderr)
        return 1

    # --- Write bundle ---
    bundle_core: dict[str, Any] = {
        "schema_version": R0_V6_SCHEMA_VERSION,
        "artifact_type": "r0_research_readiness_bundle",
        "revision": "v6",
        "supersedes": v5_bundle_id,
        "observed_at": observed_at,
        "candidate_pnl_ready": candidate_pnl_ready,
        "candidate_record_count": 1,
        "evidence_record_count": 0,
        "global_experiment_count": 1,
        "r0_runtime_bundle_id": rt_bundle_id,
        "r0_decision_bundle_id": dec_bundle_id,
        "r0_advancement_bundle_id": adv_bundle_id,
        "candidate_config_hash": config_hash,
        "trend_standalone_nav": trend_final,
        "carry_standalone_nav": carry_final,
        "carry_cost_incomplete": carry_incomplete,
        "trend_decision": trend_verdict,
        "carry_decision": carry_verdict,
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

    # Write candidate record
    _write_once(bundle_dir / "candidate-cxd-trend-carry-revalidation-v6.json", asdict(cxd_candidate))

    # Write global experiment
    _write_once(bundle_dir / "global-experiment-cxd-trend-runtime-v6.json", asdict(global_exp))

    # Write manifest
    manifest = dict(bundle_core)
    manifest["bundle_id"] = bundle_id
    manifest["member_files"] = _member_refs(bundle_dir)
    manifest["manifest_hash"] = canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})
    _write_once(bundle_dir / "manifest.json", manifest)

    # Verify
    verified = _verify_bundle(bundle_dir)
    print(f"\nR0 v6 bundle written and verified: {bundle_dir}")
    print(f"  bundle_id: {bundle_id}")
    print(f"  members: {len(verified['member_files'])}")
    print(f"  candidate_pnl_ready: {verified['candidate_pnl_ready']}")
    print(f"  orders_authorized: {verified['orders_authorized']}")
    print(f"  supersedes: {verified.get('supersedes', '')[:16]}...")
    print(f"  trend_decision: {verified.get('trend_decision')}")
    print(f"  carry_decision: {verified.get('carry_decision')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
