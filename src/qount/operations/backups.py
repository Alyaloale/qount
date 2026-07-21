"""Verified dashboard release backups and non-destructive restore drills."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime
from qount.reporting import read_dashboard_v1


BACKUP_SCHEMA_VERSION = 1
_MANIFEST_FILE = "manifest.json"
_LATEST_FILE = "latest-success.json"
_PUBLICATION_FILE = "publication.json"
_EXPECTED_RELEASE_FILES = {
    _PUBLICATION_FILE,
    "overview.json",
    "positions.json",
    "orders.json",
    "strategies.json",
    "decisions.json",
    "risk.json",
    "readiness.json",
    "system.json",
    "alerts.json",
    "reports.json",
    "intelligence.json",
}


class BackupError(ValueError):
    """Raised when a dashboard backup is incomplete, unsafe, or tampered."""


@dataclass(frozen=True)
class BackupRecord:
    backup_id: str
    completed_at: str
    publication_id: str
    publication_hash: str
    manifest_hash: str
    marker_hash: str
    file_count: int
    total_bytes: int
    source_id: str
    source_hash: str


@dataclass(frozen=True)
class BackupRetentionResult:
    latest_backup_id: str
    retained_backup_ids: tuple[str, ...]
    pruned_backup_ids: tuple[str, ...]
    skipped_backup_names: tuple[str, ...]


@dataclass(frozen=True)
class RestoreDrillResult:
    backup_id: str
    publication_id: str
    publication_hash: str
    file_count: int
    total_bytes: int
    verified: bool


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
        raise BackupError("backup_json_not_canonical") from exc


def _parse_json(raw: bytes, *, name: str) -> Mapping[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BackupError(f"{name}_duplicate_key:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate)
    except BackupError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError(f"{name}_json_invalid") from exc
    if not isinstance(value, Mapping):
        raise BackupError(f"{name}_must_be_object")
    if _canonical_bytes(value) != raw:
        raise BackupError(f"{name}_not_canonical")
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_directory(path: Path, *, name: str, mode: int) -> None:
    if path.is_symlink() or not path.is_dir():
        raise BackupError(f"{name}_directory_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != mode:
        raise BackupError(f"{name}_directory_mode_invalid")


def _require_file(path: Path, *, name: str, mode: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise BackupError(f"{name}_file_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != mode:
        raise BackupError(f"{name}_file_mode_invalid")
    return path.read_bytes()


def _write_file(path: Path, raw: bytes, *, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
        if path.read_bytes() != raw:
            raise BackupError("backup_write_readback_mismatch")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _file_rows(raw_files: Mapping[str, bytes]) -> list[dict[str, Any]]:
    return [
        {
            "file_name": name,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        for name, raw in sorted(raw_files.items())
    ]


def _manifest_core(
    *,
    completed_at: str,
    publication_id: str,
    publication_hash: str,
    raw_files: Mapping[str, bytes],
) -> dict[str, Any]:
    rows = _file_rows(raw_files)
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "completed_at": aware_datetime(completed_at).isoformat(),
        "publication_id": publication_id,
        "publication_hash": publication_hash,
        "file_count": len(rows),
        "total_bytes": sum(row["size_bytes"] for row in rows),
        "files": rows,
    }


def _validate_manifest(value: Mapping[str, Any]) -> tuple[str, str]:
    expected = {
        "schema_version",
        "backup_id",
        "completed_at",
        "publication_id",
        "publication_hash",
        "file_count",
        "total_bytes",
        "files",
        "manifest_hash",
    }
    if set(value) != expected or value["schema_version"] != BACKUP_SCHEMA_VERSION:
        raise BackupError("backup_manifest_fields_invalid")
    try:
        completed_at = aware_datetime(value["completed_at"]).isoformat()
    except (AttributeError, TypeError, ValueError) as exc:
        raise BackupError("backup_manifest_time_invalid") from exc
    if completed_at != value["completed_at"]:
        raise BackupError("backup_manifest_time_not_normalized")
    for name in ("backup_id", "publication_id", "publication_hash", "manifest_hash"):
        if not is_sha256(value[name]):
            raise BackupError(f"backup_manifest_{name}_invalid")
    rows = value["files"]
    if not isinstance(rows, list) or not rows:
        raise BackupError("backup_manifest_files_invalid")
    names: list[str] = []
    observed_bytes = 0
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "file_name",
            "size_bytes",
            "sha256",
        }:
            raise BackupError("backup_manifest_file_invalid")
        name = row["file_name"]
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name == _MANIFEST_FILE
        ):
            raise BackupError("backup_manifest_file_name_invalid")
        if (
            not isinstance(row["size_bytes"], int)
            or isinstance(row["size_bytes"], bool)
            or row["size_bytes"] < 1
            or not is_sha256(row["sha256"])
        ):
            raise BackupError("backup_manifest_file_value_invalid")
        names.append(name)
        observed_bytes += row["size_bytes"]
    if names != sorted(names) or len(names) != len(set(names)):
        raise BackupError("backup_manifest_file_order_invalid")
    if set(names) != _EXPECTED_RELEASE_FILES:
        raise BackupError("backup_manifest_release_files_invalid")
    if value["file_count"] != len(rows) or value["total_bytes"] != observed_bytes:
        raise BackupError("backup_manifest_totals_invalid")
    core = {name: value[name] for name in value if name not in {"backup_id", "manifest_hash"}}
    expected_hash = canonical_hash(core)
    if value["manifest_hash"] != expected_hash:
        raise BackupError("backup_manifest_hash_invalid")
    expected_id = trace_id("dashboard_release_backup", {"manifest_hash": expected_hash})
    if value["backup_id"] != expected_id:
        raise BackupError("backup_manifest_id_invalid")
    return expected_id, expected_hash


def _validate_marker(value: Mapping[str, Any]) -> tuple[str, str]:
    expected = {
        "schema_version",
        "backup_id",
        "completed_at",
        "publication_id",
        "manifest_hash",
        "marker_hash",
    }
    if set(value) != expected or value["schema_version"] != BACKUP_SCHEMA_VERSION:
        raise BackupError("backup_marker_fields_invalid")
    try:
        completed_at = aware_datetime(value["completed_at"]).isoformat()
    except (AttributeError, TypeError, ValueError) as exc:
        raise BackupError("backup_marker_time_invalid") from exc
    if completed_at != value["completed_at"]:
        raise BackupError("backup_marker_time_not_normalized")
    for name in ("backup_id", "publication_id", "manifest_hash", "marker_hash"):
        if not is_sha256(value[name]):
            raise BackupError(f"backup_marker_{name}_invalid")
    core = {name: value[name] for name in value if name != "marker_hash"}
    expected_hash = canonical_hash(core)
    if value["marker_hash"] != expected_hash:
        raise BackupError("backup_marker_hash_invalid")
    return value["backup_id"], expected_hash


def _read_backup(
    backup_root: Path,
    backup_id: str,
) -> tuple[Mapping[str, Any], dict[str, bytes]]:
    if not is_sha256(backup_id):
        raise BackupError("backup_id_invalid")
    snapshots = backup_root / "snapshots"
    _require_directory(snapshots, name="backup_snapshots", mode=0o700)
    directory = snapshots / backup_id
    _require_directory(directory, name="backup_snapshot", mode=0o700)
    manifest = _parse_json(
        _require_file(directory / _MANIFEST_FILE, name="backup_manifest", mode=0o600),
        name="backup_manifest",
    )
    manifest_id, _ = _validate_manifest(manifest)
    if manifest_id != backup_id:
        raise BackupError("backup_directory_id_mismatch")
    expected_files = {_MANIFEST_FILE, *(row["file_name"] for row in manifest["files"])}
    if {path.name for path in directory.iterdir()} != expected_files:
        raise BackupError("backup_snapshot_files_mismatch")
    raw_files: dict[str, bytes] = {}
    for row in manifest["files"]:
        raw = _require_file(
            directory / row["file_name"],
            name="backup_payload",
            mode=0o600,
        )
        if len(raw) != row["size_bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise BackupError("backup_payload_hash_mismatch")
        raw_files[row["file_name"]] = raw
    return manifest, raw_files


def read_latest_dashboard_backup(backup_root: str | Path) -> BackupRecord:
    """Verify and return the last successful dashboard backup marker."""

    root = Path(backup_root)
    _require_directory(root, name="backup_root", mode=0o700)
    marker_raw = _require_file(root / _LATEST_FILE, name="backup_marker", mode=0o600)
    marker = _parse_json(marker_raw, name="backup_marker")
    backup_id, marker_hash = _validate_marker(marker)
    manifest, _ = _read_backup(root, backup_id)
    if (
        marker["manifest_hash"] != manifest["manifest_hash"]
        or marker["publication_id"] != manifest["publication_id"]
        or marker["completed_at"] != manifest["completed_at"]
    ):
        raise BackupError("backup_marker_manifest_mismatch")
    source_id = trace_id("dashboard_backup_source", {"backup_id": backup_id})
    source_hash = canonical_hash(
        {
            "marker_sha256": hashlib.sha256(marker_raw).hexdigest(),
            "manifest_hash": manifest["manifest_hash"],
        }
    )
    return BackupRecord(
        backup_id=backup_id,
        completed_at=manifest["completed_at"],
        publication_id=manifest["publication_id"],
        publication_hash=manifest["publication_hash"],
        manifest_hash=manifest["manifest_hash"],
        marker_hash=marker_hash,
        file_count=manifest["file_count"],
        total_bytes=manifest["total_bytes"],
        source_id=source_id,
        source_hash=source_hash,
    )


def create_dashboard_backup(
    dashboard_root: str | Path,
    backup_root: str | Path,
    *,
    completed_at: str,
) -> BackupRecord:
    """Copy and hash the selected complete release before marking success."""

    dashboard = Path(dashboard_root)
    root = Path(backup_root)
    _require_directory(root, name="backup_root", mode=0o700)
    snapshots = root / "snapshots"
    if not snapshots.exists():
        snapshots.mkdir(mode=0o700)
        _fsync_directory(root)
    _require_directory(snapshots, name="backup_snapshots", mode=0o700)
    _, publication = read_dashboard_v1(dashboard)
    if aware_datetime(completed_at) < aware_datetime(publication.generated_at):
        raise BackupError("backup_completed_before_publication")
    expected_names = {
        _PUBLICATION_FILE,
        *(row["file_name"] for row in publication.read_models.values()),
    }
    if expected_names != _EXPECTED_RELEASE_FILES:
        raise BackupError("backup_release_files_invalid")
    target = Path(os.readlink(dashboard / "v1"))
    release = dashboard / target
    raw_files = {
        name: _require_file(release / name, name="dashboard_release", mode=0o644)
        for name in sorted(expected_names)
    }
    core = _manifest_core(
        completed_at=completed_at,
        publication_id=publication.publication_id,
        publication_hash=publication.publication_hash,
        raw_files=raw_files,
    )
    manifest_hash = canonical_hash(core)
    backup_id = trace_id("dashboard_release_backup", {"manifest_hash": manifest_hash})
    manifest = core | {"backup_id": backup_id, "manifest_hash": manifest_hash}
    destination = snapshots / backup_id
    if destination.exists():
        existing, existing_files = _read_backup(root, backup_id)
        if existing != manifest or existing_files != raw_files:
            raise BackupError("backup_id_collision")
    else:
        temporary = Path(tempfile.mkdtemp(dir=snapshots, prefix=".backup-", suffix=".tmp"))
        try:
            os.chmod(temporary, 0o700)
            for name, raw in raw_files.items():
                _write_file(temporary / name, raw, mode=0o600)
            _write_file(temporary / _MANIFEST_FILE, _canonical_bytes(manifest), mode=0o600)
            _fsync_directory(temporary)
            os.rename(temporary, destination)
            _fsync_directory(snapshots)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    marker_core = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "backup_id": backup_id,
        "completed_at": core["completed_at"],
        "publication_id": publication.publication_id,
        "manifest_hash": manifest_hash,
    }
    marker = marker_core | {"marker_hash": canonical_hash(marker_core)}
    _write_file(root / _LATEST_FILE, _canonical_bytes(marker), mode=0o600)
    _fsync_directory(root)
    record = read_latest_dashboard_backup(root)
    if record.backup_id != backup_id:
        raise BackupError("backup_final_readback_mismatch")
    return record


def verify_dashboard_restore_drill(
    backup_root: str | Path,
    backup_id: str,
) -> RestoreDrillResult:
    """Restore into a temporary tree and verify every byte and read-model hash."""

    root = Path(backup_root)
    _require_directory(root, name="backup_root", mode=0o700)
    manifest, raw_files = _read_backup(root, backup_id)
    with tempfile.TemporaryDirectory(dir=root, prefix=".restore-drill-") as temporary:
        dashboard = Path(temporary) / "data"
        release = dashboard / "releases" / manifest["publication_id"]
        release.mkdir(parents=True, mode=0o755)
        os.chmod(dashboard, 0o755)
        os.chmod(dashboard / "releases", 0o755)
        os.chmod(release, 0o755)
        for name, raw in raw_files.items():
            _write_file(release / name, raw, mode=0o644)
        _fsync_directory(release)
        os.symlink(Path("releases") / manifest["publication_id"], dashboard / "v1")
        _fsync_directory(dashboard)
        _, publication = read_dashboard_v1(dashboard)
        restored = {
            name: _require_file(release / name, name="restored_release", mode=0o644)
            for name in raw_files
        }
        if restored != raw_files or publication.publication_hash != manifest["publication_hash"]:
            raise BackupError("backup_restore_readback_mismatch")
    return RestoreDrillResult(
        backup_id=backup_id,
        publication_id=manifest["publication_id"],
        publication_hash=manifest["publication_hash"],
        file_count=manifest["file_count"],
        total_bytes=manifest["total_bytes"],
        verified=True,
    )


def prune_dashboard_backups(
    backup_root: str | Path,
    *,
    retain_previous_backups: int,
) -> BackupRetentionResult:
    """Delete only verified snapshots outside the latest-backed retention set."""

    if (
        not isinstance(retain_previous_backups, int)
        or isinstance(retain_previous_backups, bool)
        or retain_previous_backups < 1
    ):
        raise BackupError("backup_retention_invalid")
    root = Path(backup_root)
    latest = read_latest_dashboard_backup(root).backup_id
    snapshots = root / "snapshots"
    _require_directory(snapshots, name="backup_snapshots", mode=0o700)
    verified: list[tuple[dt.datetime, str]] = []
    skipped: list[str] = []
    for path in snapshots.iterdir():
        if path.name.startswith("."):
            skipped.append(path.name)
            continue
        if path.is_symlink() or not path.is_dir() or not is_sha256(path.name):
            skipped.append(path.name)
            continue
        try:
            manifest, _ = _read_backup(root, path.name)
            completed_at = aware_datetime(manifest["completed_at"])
        except (OSError, TypeError, ValueError):
            skipped.append(path.name)
            continue
        verified.append((completed_at, path.name))
    if latest not in {name for _, name in verified}:
        raise BackupError("backup_latest_not_verified_for_retention")
    verified.sort(key=lambda row: (row[0], row[1]), reverse=True)
    previous = [name for _, name in verified if name != latest]
    keep = {latest, *previous[:retain_previous_backups]}
    prune = sorted(name for _, name in verified if name not in keep)
    for backup_id in prune:
        if read_latest_dashboard_backup(root).backup_id != latest:
            raise BackupError("backup_latest_changed_during_prune")
        target = snapshots / backup_id
        if target.is_symlink() or not target.is_dir():
            raise BackupError("backup_prune_target_invalid")
        _read_backup(root, backup_id)
        shutil.rmtree(target)
    if prune:
        _fsync_directory(snapshots)
    return BackupRetentionResult(
        latest_backup_id=latest,
        retained_backup_ids=tuple(sorted(keep)),
        pruned_backup_ids=tuple(prune),
        skipped_backup_names=tuple(sorted(skipped)),
    )


__all__ = [
    "BACKUP_SCHEMA_VERSION",
    "BackupError",
    "BackupRecord",
    "BackupRetentionResult",
    "RestoreDrillResult",
    "create_dashboard_backup",
    "prune_dashboard_backups",
    "read_latest_dashboard_backup",
    "verify_dashboard_restore_drill",
]
