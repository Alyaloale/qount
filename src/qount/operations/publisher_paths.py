"""Read-only production publisher path and permission audit."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.operations.backups import read_latest_dashboard_backup
from qount.reporting import read_vps_authority_bundle


PUBLISHER_PATH_AUDIT_SCHEMA_VERSION = 1
PUBLISHER_AUTHORIZATION_PENDING = "pending_explicit_owner_authorization"


class PublisherPathAuditError(ValueError):
    """Raised when a path audit request itself is malformed."""


@dataclass(frozen=True)
class PublisherPathAudit:
    schema_version: int
    audited_at: str
    authority_root: str
    backup_root: str
    status: str
    checks: tuple[dict[str, Any], ...]
    authority_bundle_verified: bool
    backup_state: str
    backup_id: str | None
    authorization_status: str
    install_authorized: bool
    enable_authorized: bool
    audit_hash: str

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audited_at": self.audited_at,
            "authority_root": self.authority_root,
            "backup_root": self.backup_root,
            "status": self.status,
            "checks": [dict(row) for row in self.checks],
            "authority_bundle_verified": self.authority_bundle_verified,
            "backup_state": self.backup_state,
            "backup_id": self.backup_id,
            "authorization_status": self.authorization_status,
            "install_authorized": self.install_authorized,
            "enable_authorized": self.enable_authorized,
        }

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {"audit_hash": self.audit_hash}


def _check(
    rows: list[dict[str, Any]],
    *,
    name: str,
    ok: bool,
    detail: str,
) -> None:
    rows.append({"name": name, "ok": bool(ok), "detail": detail})


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode)


def _symlink_component(path: Path) -> Path | None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            return current
        if not current.exists():
            break
    return None


def _audit_root(
    path: Path,
    *,
    name: str,
    rows: list[dict[str, Any]],
) -> bool:
    absolute = path.is_absolute()
    _check(
        rows,
        name=f"{name}_absolute",
        ok=absolute,
        detail="absolute" if absolute else "relative_path_rejected",
    )
    if not absolute:
        return False
    symlink = _symlink_component(path)
    _check(
        rows,
        name=f"{name}_symlink_components",
        ok=symlink is None,
        detail="none" if symlink is None else "symlink_component_rejected",
    )
    exists = path.exists() and path.is_dir() and not path.is_symlink()
    _check(
        rows,
        name=f"{name}_directory",
        ok=exists,
        detail="directory" if exists else "missing_or_invalid",
    )
    if not exists:
        return False
    actual_mode = _mode(path)
    _check(
        rows,
        name=f"{name}_mode",
        ok=actual_mode == 0o700,
        detail=f"{actual_mode:04o}",
    )
    return symlink is None and actual_mode == 0o700


def _audit_backup_tree(path: Path, rows: list[dict[str, Any]]) -> bool:
    valid = True
    unexpected_types = 0
    invalid_modes = 0
    symlinks = 0
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            symlinks += 1
            valid = False
            continue
        if child.is_dir():
            expected_mode = 0o700
        elif child.is_file():
            expected_mode = 0o600
        else:
            unexpected_types += 1
            valid = False
            continue
        if _mode(child) != expected_mode:
            invalid_modes += 1
            valid = False
    _check(
        rows,
        name="backup_tree_symlinks",
        ok=symlinks == 0,
        detail=f"count={symlinks}",
    )
    _check(
        rows,
        name="backup_tree_modes",
        ok=invalid_modes == 0,
        detail=f"invalid_count={invalid_modes}",
    )
    _check(
        rows,
        name="backup_tree_types",
        ok=unexpected_types == 0,
        detail=f"invalid_count={unexpected_types}",
    )
    return valid


def audit_publisher_paths(
    authority_root: str | Path,
    backup_root: str | Path,
    *,
    audited_at: str,
) -> PublisherPathAudit:
    """Verify actual host paths without writing files or changing services."""

    try:
        normalized_time = aware_datetime(audited_at).isoformat()
    except (AttributeError, TypeError, ValueError) as exc:
        raise PublisherPathAuditError("publisher_path_audit_time_invalid") from exc
    authority = Path(authority_root)
    backup = Path(backup_root)
    checks: list[dict[str, Any]] = []
    authority_root_ok = _audit_root(
        authority,
        name="authority_root",
        rows=checks,
    )
    backup_root_ok = _audit_root(
        backup,
        name="backup_root",
        rows=checks,
    )

    authority_verified = False
    if authority_root_ok:
        try:
            read_vps_authority_bundle(authority)
        except (OSError, TypeError, ValueError) as exc:
            _check(
                checks,
                name="authority_bundle",
                ok=False,
                detail=f"invalid:{type(exc).__name__}:{exc}",
            )
        else:
            authority_verified = True
            _check(
                checks,
                name="authority_bundle",
                ok=True,
                detail="complete_and_cross_verified",
            )
    else:
        _check(
            checks,
            name="authority_bundle",
            ok=False,
            detail="root_precheck_failed",
        )

    backup_state = "invalid"
    backup_id: str | None = None
    backup_tree_ok = False
    if backup_root_ok:
        backup_tree_ok = _audit_backup_tree(backup, checks)
        root_entries = {child.name for child in backup.iterdir()}
        expected_entries = {"latest-success.json", "snapshots"}
        entries_ok = root_entries in (set(), expected_entries)
        _check(
            checks,
            name="backup_root_entries",
            ok=entries_ok,
            detail=(
                "empty"
                if not root_entries
                else "complete"
                if root_entries == expected_entries
                else "unexpected_or_incomplete"
            ),
        )
        if not root_entries:
            backup_state = "prepared_empty"
            _check(
                checks,
                name="backup_readback",
                ok=True,
                detail="prepared_empty",
            )
        elif entries_ok:
            try:
                record = read_latest_dashboard_backup(backup)
            except (OSError, TypeError, ValueError) as exc:
                _check(
                    checks,
                    name="backup_readback",
                    ok=False,
                    detail=f"invalid:{type(exc).__name__}:{exc}",
                )
            else:
                backup_state = "verified_snapshot"
                backup_id = record.backup_id
                _check(
                    checks,
                    name="backup_readback",
                    ok=True,
                    detail="latest_snapshot_verified",
                )
        else:
            _check(
                checks,
                name="backup_readback",
                ok=False,
                detail="root_entries_invalid",
            )
    else:
        _check(
            checks,
            name="backup_readback",
            ok=False,
            detail="root_precheck_failed",
        )

    ready = (
        authority_verified
        and backup_root_ok
        and backup_tree_ok
        and backup_state in {"prepared_empty", "verified_snapshot"}
        and all(bool(row["ok"]) for row in checks)
    )
    core = {
        "schema_version": PUBLISHER_PATH_AUDIT_SCHEMA_VERSION,
        "audited_at": normalized_time,
        "authority_root": str(authority),
        "backup_root": str(backup),
        "status": "ready_for_authorization" if ready else "blocked",
        "checks": checks,
        "authority_bundle_verified": authority_verified,
        "backup_state": backup_state,
        "backup_id": backup_id,
        "authorization_status": PUBLISHER_AUTHORIZATION_PENDING,
        "install_authorized": False,
        "enable_authorized": False,
    }
    return PublisherPathAudit(**core, audit_hash=canonical_hash(core))


__all__ = [
    "PUBLISHER_AUTHORIZATION_PENDING",
    "PUBLISHER_PATH_AUDIT_SCHEMA_VERSION",
    "PublisherPathAudit",
    "PublisherPathAuditError",
    "audit_publisher_paths",
]
