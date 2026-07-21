"""Fail-closed extraction of MiniTrend readiness evidence from runtime artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from qount.mini_trend.live_pilot import LivePilotEvidence


@dataclass(frozen=True)
class RuntimeEvidence:
    evidence: LivePilotEvidence
    sources: dict[str, Any]


def _load_object(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path).expanduser()
    raw = target.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {target}")
    return payload, {
        "path": str(target.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_is_order_free(payload: Mapping[str, Any]) -> bool:
    meta = _mapping(payload.get("meta"))
    return not any(
        bool(meta.get(name))
        for name in (
            "orders_allowed",
            "live_orders_allowed",
            "private_api_order_attempted",
            "mutating_account_method_attempted",
        )
    )


def runtime_evidence_from_artifacts(
    *,
    preflight_path: str | Path,
    paper_path: str | Path,
    shadow_input_path: str | Path,
    release_provenance_path: str | Path,
    dry_run_days: int = 0,
    dry_run_schema_error_count: int = 0,
    independent_runtime_verified: bool = False,
    legacy_production_cron_disabled: bool = False,
    legacy_live_guard_disarmed: bool = False,
    rollback_documented: bool = False,
) -> RuntimeEvidence:
    preflight, preflight_source = _load_object(preflight_path)
    paper, paper_source = _load_object(paper_path)
    shadow_input, shadow_input_source = _load_object(shadow_input_path)
    release_provenance, release_provenance_source = _load_object(
        release_provenance_path
    )

    preflight_valid = (
        preflight.get("artifact_type") == "mini_trend_um_pilot_account_preflight"
        and bool(_mapping(preflight.get("meta")).get("read_only"))
        and _artifact_is_order_free(preflight)
    )
    paper_valid = (
        paper.get("artifact_type") == "mini_trend_um_pilot_paper_runtime"
        and bool(_mapping(paper.get("meta")).get("paper_only"))
        and _artifact_is_order_free(paper)
    )
    shadow_input_valid = (
        shadow_input.get("artifact_type") == "mini_trend_um_shadow_input_refresh"
        and bool(_mapping(shadow_input.get("meta")).get("public_data_only"))
        and _artifact_is_order_free(shadow_input)
    )
    release_meta = _mapping(release_provenance.get("meta"))
    release_evidence = _mapping(release_provenance.get("evidence"))
    release_details = _mapping(release_provenance.get("provenance"))
    release_verification_core = {
        key: value
        for key, value in release_provenance.items()
        if key != "verification_hash"
    }
    release_provenance_valid = (
        release_provenance.get("artifact_type")
        == "qount_release_provenance_verification"
        and bool(release_meta.get("read_only"))
        and not bool(release_meta.get("orders_allowed"))
        and release_evidence.get("verified") is True
        and bool(release_details.get("git_commit"))
        and bool(release_details.get("version"))
        and bool(release_details.get("source_tree_hash"))
        and bool(release_details.get("provenance_hash"))
        and release_provenance.get("verification_hash")
        == _canonical_hash(release_verification_core)
    )

    preflight_evidence = (
        _mapping(preflight.get("evidence")) if preflight_valid else {}
    )
    paper_data = _mapping(paper.get("data")) if paper_valid else {}
    paper_evaluation = _mapping(paper.get("evaluation")) if paper_valid else {}
    paper_journal = _mapping(paper.get("journal")) if paper_valid else {}
    shadow_diagnostics = (
        _mapping(shadow_input.get("diagnostics")) if shadow_input_valid else {}
    )

    paper_days = _integer(paper_evaluation.get("paper_days"))
    journal_rows = _integer(paper_journal.get("row_count"))
    paper_schema_errors = 0
    if not paper_valid:
        paper_schema_errors += 1
    if journal_rows != paper_days:
        paper_schema_errors += 1
    if paper_days and not paper_journal.get("final_chain_hash"):
        paper_schema_errors += 1

    funding_journal_complete = (
        paper_valid
        and shadow_input_valid
        and journal_rows == paper_days
        and bool(shadow_diagnostics.get("current_month_funding_complete"))
    )

    evidence = LivePilotEvidence(
        forward_pairs=_integer(paper_data.get("complete_prefix_pair_count")),
        forward_active_bars=_integer(paper_evaluation.get("active_bars")),
        paper_days=paper_days,
        paper_schema_error_count=paper_schema_errors,
        dry_run_days=max(int(dry_run_days), 0),
        dry_run_schema_error_count=max(int(dry_run_schema_error_count), 0),
        independent_runtime_verified=independent_runtime_verified,
        complete_funding_journal=funding_journal_complete,
        configured_exchange_route_ok=bool(
            preflight_evidence.get("configured_exchange_route_ok")
        ),
        public_api_ok=bool(preflight_evidence.get("public_api_ok")),
        credentials_ok=bool(preflight_evidence.get("credentials_ok")),
        api_key_reading_enabled=bool(
            preflight_evidence.get("api_key_reading_enabled")
        ),
        api_key_spot_margin_disabled=bool(
            preflight_evidence.get("api_key_spot_margin_disabled")
        ),
        api_key_withdrawal_disabled=bool(
            preflight_evidence.get("api_key_withdrawal_disabled")
        ),
        api_key_futures_enabled=bool(
            preflight_evidence.get("api_key_futures_enabled")
        ),
        api_key_ip_restricted=bool(preflight_evidence.get("api_key_ip_restricted")),
        account_balance_audit_complete=bool(
            preflight_evidence.get("account_balance_audit_complete")
        ),
        available_balance_usdt=_optional_float(
            preflight_evidence.get("available_balance_usdt")
        ),
        position_mode_oneway=bool(preflight_evidence.get("position_mode_oneway")),
        position_audit_complete=bool(
            preflight_evidence.get("position_audit_complete")
        ),
        unmanaged_position_count=(
            _integer(preflight_evidence.get("unmanaged_position_count"))
            if preflight_evidence.get("unmanaged_position_count") is not None
            else None
        ),
        account_flat=bool(preflight_evidence.get("account_flat")),
        open_order_audit_complete=bool(
            preflight_evidence.get("open_order_audit_complete")
        ),
        open_order_count=(
            _integer(preflight_evidence.get("open_order_count"))
            if preflight_evidence.get("open_order_count") is not None
            else None
        ),
        isolated_one_x_verified=bool(
            preflight_evidence.get("isolated_one_x_verified")
        ),
        legacy_production_cron_disabled=legacy_production_cron_disabled,
        legacy_live_guard_disarmed=legacy_live_guard_disarmed,
        rollback_documented=rollback_documented,
        release_provenance_verified=release_provenance_valid,
        release_git_commit=(
            str(release_details.get("git_commit"))
            if release_provenance_valid
            else None
        ),
        release_version=(
            str(release_details.get("version"))
            if release_provenance_valid
            else None
        ),
        release_source_tree_hash=(
            str(release_details.get("source_tree_hash"))
            if release_provenance_valid
            else None
        ),
        release_provenance_hash=(
            str(release_details.get("provenance_hash"))
            if release_provenance_valid
            else None
        ),
    )
    sources = {
        "preflight": preflight_source | {"valid": preflight_valid},
        "paper": paper_source
        | {"valid": paper_valid, "schema_error_count": paper_schema_errors},
        "shadow_input": shadow_input_source | {"valid": shadow_input_valid},
        "release_provenance": release_provenance_source
        | {"valid": release_provenance_valid},
    }
    return RuntimeEvidence(evidence=evidence, sources=sources)
