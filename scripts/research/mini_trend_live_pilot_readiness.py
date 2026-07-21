#!/usr/bin/env python3
"""Build a fail-closed readiness artifact for the requested one-month UM pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.live_pilot import LivePilotEvidence  # noqa: E402
from qount.mini_trend.live_pilot import LivePilotRequest  # noqa: E402
from qount.mini_trend.live_pilot import build_live_pilot_readiness  # noqa: E402
from qount.mini_trend.live_pilot import write_live_pilot_readiness_artifact  # noqa: E402
from qount.contracts import canonical_hash  # noqa: E402
from qount.mini_trend.pilot_readiness_evidence import (  # noqa: E402
    runtime_evidence_from_artifacts,
)
from qount.mini_trend.pilot_dispatcher import dry_dispatch_evidence  # noqa: E402
from qount.mini_trend.pilot_runtime import validate_pilot_runtime_proof  # noqa: E402
from qount.reporting import read_vps_authority_bundle  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-requested", action="store_true")
    parser.add_argument("--capital-usdt", type=float)
    parser.add_argument("--start-date")
    parser.add_argument("--duration-days", type=int, default=30)
    parser.add_argument("--forward-pairs", type=int, default=0)
    parser.add_argument("--forward-active-bars", type=int, default=0)
    parser.add_argument("--paper-days", type=int, default=0)
    parser.add_argument("--paper-schema-errors", type=int, default=0)
    parser.add_argument("--dry-run-days", type=int, default=0)
    parser.add_argument("--dry-run-schema-errors", type=int, default=0)
    parser.add_argument("--dry-journal-path")
    parser.add_argument("--independent-runtime-verified", action="store_true")
    parser.add_argument("--runtime-proof-path")
    parser.add_argument("--complete-funding-journal", action="store_true")
    parser.add_argument("--configured-exchange-route-ok", action="store_true")
    parser.add_argument("--public-api-ok", action="store_true")
    parser.add_argument("--credentials-ok", action="store_true")
    parser.add_argument("--api-key-withdrawal-disabled", action="store_true")
    parser.add_argument("--api-key-futures-enabled", action="store_true")
    parser.add_argument("--api-key-ip-restricted", action="store_true")
    parser.add_argument("--account-balance-audit-complete", action="store_true")
    parser.add_argument("--available-balance-usdt", type=float)
    parser.add_argument("--position-mode-oneway", action="store_true")
    parser.add_argument("--position-audit-complete", action="store_true")
    parser.add_argument("--unmanaged-position-count", type=int)
    parser.add_argument("--account-flat", action="store_true")
    parser.add_argument("--open-order-audit-complete", action="store_true")
    parser.add_argument("--open-order-count", type=int)
    parser.add_argument("--isolated-one-x-verified", action="store_true")
    parser.add_argument("--legacy-production-cron-disabled", action="store_true")
    parser.add_argument("--legacy-live-guard-disarmed", action="store_true")
    parser.add_argument("--rollback-documented", action="store_true")
    parser.add_argument("--preflight-path")
    parser.add_argument("--paper-path")
    parser.add_argument("--shadow-input-path")
    parser.add_argument("--release-provenance-path")
    parser.add_argument("--authority-root")
    parser.add_argument("--authority-result-path")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    request = LivePilotRequest(
        owner_requested_one_month_live=args.owner_requested,
        capital_usdt=args.capital_usdt,
        start_date=args.start_date,
        duration_days=args.duration_days,
    )
    runtime_paths = (
        args.preflight_path,
        args.paper_path,
        args.shadow_input_path,
        args.release_provenance_path,
    )
    if any(runtime_paths) and not all(runtime_paths):
        raise ValueError(
            "--preflight-path, --paper-path, --shadow-input-path and "
            "--release-provenance-path are required together"
        )
    runtime_sources = None
    runtime_proof = None
    runtime_proof_valid = args.independent_runtime_verified
    if args.runtime_proof_path:
        proof_path = Path(args.runtime_proof_path).expanduser()
        raw = proof_path.read_bytes()
        runtime_proof = json.loads(raw)
        if not isinstance(runtime_proof, dict):
            raise ValueError("runtime proof must be a JSON object")
        runtime_proof_valid = validate_pilot_runtime_proof(runtime_proof)
        runtime_proof_source = {
            "path": str(proof_path.resolve()),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "valid": runtime_proof_valid,
        }
    dry_evidence = (
        dry_dispatch_evidence(args.dry_journal_path)
        if args.dry_journal_path
        else {
            "dry_run_days": args.dry_run_days,
            "dry_run_schema_error_count": args.dry_run_schema_errors,
        }
    )
    if all(runtime_paths):
        runtime = runtime_evidence_from_artifacts(
            preflight_path=args.preflight_path,
            paper_path=args.paper_path,
            shadow_input_path=args.shadow_input_path,
            release_provenance_path=args.release_provenance_path,
            dry_run_days=dry_evidence["dry_run_days"],
            dry_run_schema_error_count=dry_evidence[
                "dry_run_schema_error_count"
            ],
            independent_runtime_verified=runtime_proof_valid,
            legacy_production_cron_disabled=args.legacy_production_cron_disabled,
            legacy_live_guard_disarmed=args.legacy_live_guard_disarmed,
            rollback_documented=args.rollback_documented,
        )
        evidence = runtime.evidence
        runtime_sources = runtime.sources
    else:
        evidence = LivePilotEvidence(
            forward_pairs=args.forward_pairs,
            forward_active_bars=args.forward_active_bars,
            paper_days=args.paper_days,
            paper_schema_error_count=args.paper_schema_errors,
            dry_run_days=dry_evidence["dry_run_days"],
            dry_run_schema_error_count=dry_evidence[
                "dry_run_schema_error_count"
            ],
            independent_runtime_verified=runtime_proof_valid,
            complete_funding_journal=args.complete_funding_journal,
            configured_exchange_route_ok=args.configured_exchange_route_ok,
            public_api_ok=args.public_api_ok,
            credentials_ok=args.credentials_ok,
            api_key_withdrawal_disabled=args.api_key_withdrawal_disabled,
            api_key_futures_enabled=args.api_key_futures_enabled,
            api_key_ip_restricted=args.api_key_ip_restricted,
            account_balance_audit_complete=args.account_balance_audit_complete,
            available_balance_usdt=args.available_balance_usdt,
            position_mode_oneway=args.position_mode_oneway,
            position_audit_complete=args.position_audit_complete,
            unmanaged_position_count=args.unmanaged_position_count,
            account_flat=args.account_flat,
            open_order_audit_complete=args.open_order_audit_complete,
            open_order_count=args.open_order_count,
            isolated_one_x_verified=args.isolated_one_x_verified,
            legacy_production_cron_disabled=args.legacy_production_cron_disabled,
            legacy_live_guard_disarmed=args.legacy_live_guard_disarmed,
            rollback_documented=args.rollback_documented,
        )
    if args.authority_root:
        authority_root = Path(args.authority_root).expanduser().resolve()
        bundle = read_vps_authority_bundle(authority_root)
        reconciliation = bundle.ledger_snapshot.reconciliation
        authority_result = None
        authority_result_valid = False
        if args.authority_result_path:
            authority_result_path = Path(args.authority_result_path).expanduser()
            authority_result = json.loads(authority_result_path.read_text(encoding="ascii"))
            result_core = (
                {
                    key: value
                    for key, value in authority_result.items()
                    if key != "result_hash"
                }
                if isinstance(authority_result, dict)
                else {}
            )
            authority_result_valid = bool(
                isinstance(authority_result, dict)
                and authority_result.get("status") == "written"
                and authority_result.get("batch_id") == bundle.batch.manifest.batch_id
                and authority_result.get("result_hash") == canonical_hash(result_core)
                and Path(str(authority_result.get("run_dir") or "")).resolve()
                == authority_result_path.resolve().parent
            )
        authority_ready = bool(
            authority_result_valid
            and
            reconciliation.get("phase") == "pre_dispatch"
            and reconciliation.get("passed")
            and not reconciliation.get("halt_required")
            and bundle.ledger_snapshot.nav.get("passed")
            and not bundle.ledger_snapshot.unresolved_order_ids
        )
        evidence = LivePilotEvidence(
            **{
                **evidence.__dict__,
                "standard_authority_verified": authority_ready,
                "authority_batch_id": bundle.batch.manifest.batch_id,
                "runtime_ledger_snapshot_hash": bundle.ledger_snapshot.snapshot_hash,
                "pre_dispatch_reconciliation_hash": reconciliation.get("report_hash"),
                "pre_dispatch_reconciliation_passed": authority_ready,
                "notification_snapshot_hash": bundle.notification_snapshot.snapshot_hash,
                "daily_brief_hash": bundle.daily_brief.brief_hash,
                "system_health_snapshot_hash": bundle.system_health.snapshot_hash,
                "system_health_ready": bundle.system_health.status == "healthy",
            }
        )
        if runtime_sources is None:
            runtime_sources = {}
        runtime_sources["standard_authority"] = {
            "path": str(authority_root),
            "batch_id": bundle.batch.manifest.batch_id,
            "ledger_snapshot_hash": bundle.ledger_snapshot.snapshot_hash,
            "reconciliation_hash": reconciliation.get("report_hash"),
            "notification_snapshot_hash": bundle.notification_snapshot.snapshot_hash,
            "daily_brief_hash": bundle.daily_brief.brief_hash,
            "system_health_snapshot_hash": bundle.system_health.snapshot_hash,
            "valid": authority_ready,
            "writer_result_valid": authority_result_valid,
            "writer_result_hash": (
                authority_result.get("result_hash")
                if isinstance(authority_result, dict)
                else None
            ),
            "run_dir": (
                authority_result.get("run_dir")
                if isinstance(authority_result, dict)
                else None
            ),
        }
    payload = build_live_pilot_readiness(request, evidence)
    if runtime_sources is not None:
        payload["runtime_sources"] = runtime_sources
    if args.dry_journal_path:
        payload.setdefault("runtime_sources", {})["dry_dispatch_journal"] = {
            "path": str(Path(args.dry_journal_path).expanduser().resolve()),
            **dry_evidence,
        }
    if args.runtime_proof_path:
        payload.setdefault("runtime_sources", {})["independent_runtime"] = (
            runtime_proof_source
        )
    artifact = write_live_pilot_readiness_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"blockers={len(artifact['diagnostics']['blockers'])}")
    print(f"readiness_hash={artifact['readiness_hash']}")
    print(f"live_orders_allowed={artifact['meta']['live_orders_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
