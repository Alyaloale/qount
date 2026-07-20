"""Read-only importer for a complete VPS authority bundle.

The importer is intentionally narrower than a publisher: it accepts only
verified batch, registry, ledger, notification, health and daily-brief
artifacts.  It never reads legacy state, invokes a network client, or writes a
release.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from qount.governance import StrategyRegistry
from qount.ledger import RuntimeLedgerSnapshot
from qount.notifications import NotificationSnapshot
from qount.notifications import SystemHealthSnapshot
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import read_decision_batch
from qount.persistence import read_immutable_artifact
from qount.reporting.daily_brief import DailyBrief
from qount.reporting.daily_brief import daily_brief_from_dict
from qount.reporting.daily_brief import validate_daily_brief_sources
from qount.reporting.read_models import build_dashboard_v1


class AuthorityArtifactImportError(ValueError):
    """Raised when a VPS authority bundle is incomplete or tampered."""


@dataclass(frozen=True)
class VpsAuthorityBundle:
    """All inputs required by a production publisher, after verification."""

    batch: VerifiedDecisionBatch
    registry: StrategyRegistry
    ledger_snapshot: RuntimeLedgerSnapshot
    notification_snapshot: NotificationSnapshot
    system_health: SystemHealthSnapshot
    daily_brief: DailyBrief


_ROOT_FILES = {
    "strategy_registry.json",
    "runtime_ledger_snapshot.json",
    "notification_snapshot.json",
    "system_health_snapshot.json",
    "daily_brief.json",
    "decision_batch",
}


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise AuthorityArtifactImportError("authority_json_not_canonical") from exc


def _parse_json(raw: bytes, *, name: str) -> Mapping[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuthorityArtifactImportError(f"{name}_duplicate_key:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate)
    except AuthorityArtifactImportError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityArtifactImportError(f"{name}_json_invalid") from exc
    if not isinstance(value, Mapping):
        raise AuthorityArtifactImportError(f"{name}_must_be_object")
    if _canonical_bytes(value) != raw:
        raise AuthorityArtifactImportError(f"{name}_not_canonical")
    return value


def _require_directory(path: Path, *, name: str, mode: int = 0o700) -> None:
    if path.is_symlink() or not path.is_dir():
        raise AuthorityArtifactImportError(f"{name}_directory_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != mode:
        raise AuthorityArtifactImportError(f"{name}_directory_mode_invalid")


def _read_json(path: Path, *, name: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AuthorityArtifactImportError(f"{name}_file_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise AuthorityArtifactImportError(f"{name}_file_mode_invalid")
    return _parse_json(path.read_bytes(), name=name)


def _read_batch(root: Path) -> VerifiedDecisionBatch:
    batch_parent = root / "decision_batch"
    _require_directory(batch_parent, name="decision_batch")
    children = tuple(batch_parent.iterdir())
    if len(children) != 1 or children[0].is_symlink() or not children[0].is_dir():
        raise AuthorityArtifactImportError("decision_batch_selection_invalid")
    try:
        return read_decision_batch(children[0])
    except (OSError, ValueError, TypeError) as exc:
        raise AuthorityArtifactImportError("decision_batch_invalid") from exc


def read_vps_authority_bundle(root: str | Path) -> VpsAuthorityBundle:
    """Read and cross-check one complete, immutable VPS artifact bundle."""

    source = Path(root)
    _require_directory(source, name="authority_root")
    actual = {path.name for path in source.iterdir()}
    if actual != _ROOT_FILES:
        missing = ",".join(sorted(_ROOT_FILES - actual)) or "none"
        unexpected = ",".join(sorted(actual - _ROOT_FILES)) or "none"
        raise AuthorityArtifactImportError(
            f"authority_root_files_mismatch:missing={missing}:unexpected={unexpected}"
        )

    batch = _read_batch(source)
    registry_path = source / "strategy_registry.json"
    if registry_path.is_symlink() or not registry_path.is_file():
        raise AuthorityArtifactImportError("strategy_registry_file_invalid")
    if stat.S_IMODE(os.stat(registry_path, follow_symlinks=False).st_mode) != 0o600:
        raise AuthorityArtifactImportError("strategy_registry_file_mode_invalid")
    try:
        registry = read_immutable_artifact(
            registry_path,
            expected_artifact_type="strategy_registry",
        )
    except (OSError, ValueError, TypeError) as exc:
        raise AuthorityArtifactImportError("strategy_registry_invalid") from exc
    if not isinstance(registry, StrategyRegistry):
        raise AuthorityArtifactImportError("strategy_registry_type_invalid")

    try:
        ledger_snapshot = RuntimeLedgerSnapshot.from_dict(
            _read_json(
                source / "runtime_ledger_snapshot.json",
                name="runtime_ledger_snapshot",
            )
        )
        notification_snapshot = NotificationSnapshot.from_dict(
            _read_json(
                source / "notification_snapshot.json",
                name="notification_snapshot",
            )
        )
        system_health = SystemHealthSnapshot.from_dict(
            _read_json(
                source / "system_health_snapshot.json",
                name="system_health_snapshot",
            )
        )
        daily_brief = daily_brief_from_dict(
            _read_json(source / "daily_brief.json", name="daily_brief")
        )
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, AuthorityArtifactImportError):
            raise
        raise AuthorityArtifactImportError("authority_source_invalid") from exc

    if ledger_snapshot.batch_id != batch.manifest.batch_id:
        raise AuthorityArtifactImportError("authority_ledger_batch_mismatch")
    if ledger_snapshot.manifest_hash != batch.manifest.manifest_hash:
        raise AuthorityArtifactImportError("authority_ledger_manifest_mismatch")
    if ledger_snapshot.order_plan_id != batch.plan.order_plan_id:
        raise AuthorityArtifactImportError("authority_ledger_plan_id_mismatch")
    if ledger_snapshot.plan_hash != batch.plan.plan_hash:
        raise AuthorityArtifactImportError("authority_ledger_plan_hash_mismatch")
    expected_brief_sources = {
        "decision_batch_manifest": batch.manifest.manifest_hash,
        "strategy_registry": registry.registry_hash,
        "runtime_ledger": ledger_snapshot.snapshot_hash,
        "notification_store": notification_snapshot.snapshot_hash,
    }
    if dict(daily_brief.source_hashes) != expected_brief_sources:
        raise AuthorityArtifactImportError("authority_brief_sources_mismatch")
    try:
        validate_daily_brief_sources(
            daily_brief,
            batch,
            registry,
            ledger_snapshot,
            notification_snapshot,
        )
        # Run the same complete source validation used by the publisher.  The
        # returned models are intentionally discarded; importing is read-only.
        build_dashboard_v1(
            batch,
            registry,
            generated_at=daily_brief.generated_at,
            evaluated_at=daily_brief.generated_at,
            ledger_snapshot=ledger_snapshot,
            notification_snapshot=notification_snapshot,
            system_health=system_health,
        )
    except (TypeError, ValueError) as exc:
        raise AuthorityArtifactImportError("authority_cross_check_failed") from exc

    return VpsAuthorityBundle(
        batch=batch,
        registry=registry,
        ledger_snapshot=ledger_snapshot,
        notification_snapshot=notification_snapshot,
        system_health=system_health,
        daily_brief=daily_brief,
    )


__all__ = [
    "AuthorityArtifactImportError",
    "VpsAuthorityBundle",
    "read_vps_authority_bundle",
]
