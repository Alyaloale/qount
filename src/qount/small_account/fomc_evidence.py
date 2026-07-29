"""Immutable FOMC replay manifests and credential-free local evidence backups."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.ledger import verify_audit_journal
from qount.persistence import read_decision_batch
from qount.small_account.fomc_live import FomcLiveStore
from qount.small_account.fomc_runtime import FomcEventDefinition
from qount.small_account.fomc_watcher import FomcStateStore


FOMC_EVENT_SCORECARD_SCHEMA_VERSION = 1
FOMC_EVENT_BUNDLE_SCHEMA_VERSION = 1
FOMC_EVIDENCE_BACKUP_SCHEMA_VERSION = 1
_SENSITIVE_LIVE_PATHS = frozenset({"auto-arm-secret.json"})
_LIVE_POINTER_PATHS = frozenset(
    {
        "arm-latest.json",
        "execution-latest.json",
        "management-latest.json",
        "readiness-latest.json",
    }
)


class FomcEvidenceError(ValueError):
    """Raised when FOMC replay evidence cannot be proved or safely copied."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(value),
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _utc(value: str | dt.datetime) -> dt.datetime:
    parsed = (
        value
        if isinstance(value, dt.datetime)
        else dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FomcEvidenceError("fomc_evidence_time_invalid")
    return parsed.astimezone(dt.timezone.utc)


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise FomcEvidenceError("fomc_evidence_directory_invalid")
    os.chmod(path, 0o700)
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o700:
        raise FomcEvidenceError("fomc_evidence_directory_mode_invalid")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    raw = _canonical_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if path.read_bytes() != raw:
        raise FomcEvidenceError("fomc_evidence_write_readback_mismatch")
    _fsync_directory(path.parent)


def _write_latest(path: Path, value: Mapping[str, Any]) -> None:
    raw = _canonical_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _read_json(path: Path, *, name: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FomcEvidenceError(f"fomc_evidence_{name}_invalid")
    if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
        raise FomcEvidenceError(f"fomc_evidence_{name}_mode_invalid")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise FomcEvidenceError(f"fomc_evidence_{name}_duplicate_key")
            result[key] = value
        return result

    raw = path.read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate)
    except FomcEvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FomcEvidenceError(f"fomc_evidence_{name}_json_invalid") from exc
    if not isinstance(value, dict) or _canonical_bytes(value) != raw:
        raise FomcEvidenceError(f"fomc_evidence_{name}_not_canonical")
    return value


def _file_reference(path: Path, *, relative_to: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _market_capture_references(store: FomcStateStore) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for path in sorted(store.captures_root.glob("*.json")):
        payload = _read_json(path, name="market_capture")
        core = {
            key: value
            for key, value in payload.items()
            if key not in {"capture_id", "capture_hash"}
        }
        capture_hash = canonical_hash(core)
        if (
            payload.get("capture_id") != capture_hash
            or payload.get("capture_hash") != capture_hash
            or path.stem != capture_hash
        ):
            raise FomcEvidenceError("fomc_evidence_market_capture_hash_invalid")
        references.append(
            {
                "capture_id": capture_hash,
                "capture_hash": capture_hash,
                "observed_at": payload.get("observed_at"),
            }
        )
    return references


def _run_references(store: FomcStateStore) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for path in sorted(store.runs_root.glob("*.json")):
        payload = _read_json(path, name="run")
        expected = canonical_hash(
            {key: value for key, value in payload.items() if key != "result_hash"}
        )
        if payload.get("result_hash") != expected:
            raise FomcEvidenceError("fomc_evidence_run_hash_invalid")
        capture = payload.get("market_capture")
        capture_id = capture.get("capture_id") if isinstance(capture, Mapping) else None
        references.append(
            {
                "result_hash": expected,
                "observed_at": payload.get("observed_at"),
                "stage": payload.get("stage"),
                "market_capture_id": capture_id,
            }
        )
    return references


def _batch_references(store: FomcStateStore) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for path in sorted(store.batches_root.iterdir()):
        if path.name.startswith("."):
            continue
        batch = read_decision_batch(path)
        references.append(
            {
                "batch_id": batch.manifest.batch_id,
                "manifest_hash": batch.manifest.manifest_hash,
            }
        )
    return references


def _live_artifact_references(live_store: FomcLiveStore) -> tuple[list[dict[str, Any]], list[str]]:
    references: list[dict[str, Any]] = []
    excluded: list[str] = []
    for path in sorted(live_store.root.rglob("*")):
        if path.is_symlink():
            raise FomcEvidenceError("fomc_evidence_live_symlink_forbidden")
        if not path.is_file():
            continue
        relative = path.relative_to(live_store.root).as_posix()
        if relative in _SENSITIVE_LIVE_PATHS:
            excluded.append(relative)
            continue
        if relative in _LIVE_POINTER_PATHS or relative in {"cycle.lock", "runtime.sqlite3", "runtime.audit.jsonl"}:
            continue
        if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o600:
            raise FomcEvidenceError("fomc_evidence_live_artifact_mode_invalid")
        references.append(_file_reference(path, relative_to=live_store.root))
    return references, excluded


def _ledger_reference(live_store: FomcLiveStore) -> dict[str, Any]:
    database = live_store.ledger_path
    audit = database.with_suffix(".audit.jsonl")
    reference: dict[str, Any] = {
        "database": None,
        "audit": {"row_count": 0, "last_hash": "0" * 64},
    }
    if database.exists():
        if stat.S_IMODE(os.stat(database, follow_symlinks=False).st_mode) != 0o600:
            raise FomcEvidenceError("fomc_evidence_ledger_mode_invalid")
        reference["database"] = _file_reference(database, relative_to=live_store.root)
    if audit.exists():
        journal = verify_audit_journal(audit)
        reference["audit"] = {
            **_file_reference(audit, relative_to=live_store.root),
            "row_count": journal.row_count,
            "last_hash": journal.last_hash,
        }
    return reference


def _release_reference(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"status": "unavailable"}
    if path.is_symlink() or not path.is_file():
        raise FomcEvidenceError("fomc_evidence_release_provenance_invalid")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FomcEvidenceError("fomc_evidence_release_provenance_json_invalid") from exc
    if not isinstance(payload, Mapping) or not is_sha256(payload.get("provenance_hash")):
        raise FomcEvidenceError("fomc_evidence_release_provenance_hash_invalid")
    return {
        "status": "available",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "provenance_hash": payload["provenance_hash"],
        "git_commit": payload.get("git_commit"),
        "version": payload.get("version"),
    }


def _event_config_reference(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FomcEvidenceError("fomc_evidence_event_config_invalid")
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def build_fomc_event_scorecard(
    event: FomcEventDefinition,
    state_store: FomcStateStore,
    live_store: FomcLiveStore,
    *,
    finalized_at: str | dt.datetime,
) -> dict[str, Any]:
    """Summarize the actual event evidence without inventing unrealized PnL."""

    freeze = state_store.read_freeze()
    runs = _run_references(state_store)
    batches = _batch_references(state_store)
    execution = live_store.read_execution()
    attempt = live_store.read_attempt()
    management = live_store.read_management_state()
    core = {
        "schema_version": FOMC_EVENT_SCORECARD_SCHEMA_VERSION,
        "artifact_type": "fomc_event_scorecard",
        "event_id": event.event_id,
        "finalized_at": _utc(finalized_at).isoformat(),
        "freeze_hash": freeze.freeze_hash if freeze is not None else None,
        "market_capture_count": len(_market_capture_references(state_store)),
        "shadow_run_count": len(runs),
        "stages": [str(row["stage"]) for row in runs],
        "decision_batch_count": len(batches),
        "execution_status": execution.get("status") if execution is not None else "no_execution_artifact",
        "attempt_present": attempt is not None,
        "management_status": management.get("status") if management is not None else None,
        "ledger": _ledger_reference(live_store),
        "limitations": [
            "public_market_captures_are_candle_and_quote_snapshots_not_order_book_replay",
            "no_real_fill_metrics_are_available_when_no_execution_artifact_exists",
        ],
    }
    return core | {"scorecard_hash": canonical_hash(core)}


def finalize_fomc_event_bundle(
    event: FomcEventDefinition,
    state_store: FomcStateStore,
    live_store: FomcLiveStore,
    *,
    event_config_path: str | os.PathLike[str],
    release_provenance_path: str | os.PathLike[str] | None = None,
    finalized_at: str | dt.datetime,
) -> dict[str, Any] | None:
    """Freeze one event-wide manifest only after the configured force-exit time."""

    finalized = _utc(finalized_at)
    if finalized < event.force_exit_time:
        return None
    existing = state_store.read_final_bundle()
    if existing is not None:
        return existing
    scorecard = build_fomc_event_scorecard(
        event,
        state_store,
        live_store,
        finalized_at=finalized,
    )
    state_store.write_scorecard(scorecard)
    scorecard_hash = str(scorecard["scorecard_hash"])
    freeze = state_store.read_freeze()
    live_artifacts, excluded = _live_artifact_references(live_store)
    core = {
        "schema_version": FOMC_EVENT_BUNDLE_SCHEMA_VERSION,
        "artifact_type": "fomc_event_replay_bundle",
        "event": event.as_dict(),
        "finalized_at": finalized.isoformat(),
        "event_config": _event_config_reference(Path(event_config_path).expanduser()),
        "release_provenance": _release_reference(
            Path(release_provenance_path).expanduser()
            if release_provenance_path is not None
            else None
        ),
        "freeze": (
            {"freeze_id": freeze.freeze_id, "freeze_hash": freeze.freeze_hash}
            if freeze is not None
            else None
        ),
        "market_captures": _market_capture_references(state_store),
        "shadow_runs": _run_references(state_store),
        "decision_batches": _batch_references(state_store),
        "live_artifacts": live_artifacts,
        "sensitive_paths_excluded": excluded,
        "runtime_ledger": _ledger_reference(live_store),
        "scorecard": {"scorecard_hash": scorecard_hash},
    }
    bundle_id = canonical_hash(core)
    payload = core | {
        "bundle_id": bundle_id,
        "bundle_hash": canonical_hash(core | {"bundle_id": bundle_id}),
    }
    state_store.write_final_bundle(payload)
    return payload


def _copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise FomcEvidenceError("fomc_evidence_backup_source_file_invalid")
    if stat.S_IMODE(os.stat(source, follow_symlinks=False).st_mode) != 0o600:
        raise FomcEvidenceError("fomc_evidence_backup_source_file_mode_invalid")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    raw = source.read_bytes()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _copy_tree(
    source: Path,
    destination: Path,
    *,
    excluded: Iterable[str] = (),
) -> list[Path]:
    excluded_paths = frozenset(excluded)
    copied: list[Path] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise FomcEvidenceError("fomc_evidence_backup_source_symlink_forbidden")
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        if relative in excluded_paths:
            continue
        target = destination / relative
        _copy_file(path, target)
        copied.append(target)
    return copied


def _copy_sqlite_snapshot(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise FomcEvidenceError("fomc_evidence_backup_sqlite_source_invalid")
    if stat.S_IMODE(os.stat(source, follow_symlinks=False).st_mode) != 0o600:
        raise FomcEvidenceError("fomc_evidence_backup_sqlite_source_mode_invalid")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    source_connection = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(target_connection)
        quick_check = target_connection.execute("PRAGMA quick_check").fetchone()
        if quick_check != ("ok",):
            raise FomcEvidenceError("fomc_evidence_backup_sqlite_integrity_invalid")
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()
    os.chmod(destination, 0o600)
    with destination.open("rb") as handle:
        os.fsync(handle.fileno())


def create_fomc_evidence_backup(
    event: FomcEventDefinition,
    *,
    state_root: str | os.PathLike[str],
    backup_root: str | os.PathLike[str],
    completed_at: str | dt.datetime,
) -> dict[str, Any]:
    """Copy replay evidence under the FOMC cycle lock without loading credentials."""

    state_store = FomcStateStore(state_root, event.event_id)
    live_store = FomcLiveStore(state_root, event.event_id)
    root = Path(backup_root).expanduser().resolve()
    snapshots = root / "snapshots"
    _secure_directory(root)
    _secure_directory(snapshots)
    completed = _utc(completed_at)
    with live_store.cycle_lock():
        temporary = Path(tempfile.mkdtemp(dir=snapshots, prefix=".backup-", suffix=".tmp"))
        os.chmod(temporary, 0o700)
        try:
            event_destination = temporary / "event"
            # The live subtree is handled below so runtime.sqlite3 can be copied
            # through SQLite's consistent backup API and no arm secret is copied.
            copied = _copy_tree(
                state_store.event_root,
                event_destination,
                excluded=(
                    "live/auto-arm-secret.json",
                    "live/cycle.lock",
                    "live/runtime.sqlite3",
                    "live/runtime.sqlite3-wal",
                    "live/runtime.sqlite3-shm",
                ),
            )
            database = live_store.ledger_path
            if database.exists():
                target = event_destination / "live" / "runtime.sqlite3"
                _copy_sqlite_snapshot(database, target)
                copied.append(target)
            files = [
                _file_reference(path, relative_to=temporary)
                for path in sorted(copied)
            ]
            final_bundle = state_store.read_final_bundle()
            core = {
                "schema_version": FOMC_EVIDENCE_BACKUP_SCHEMA_VERSION,
                "artifact_type": "fomc_evidence_backup",
                "event_id": event.event_id,
                "completed_at": completed.isoformat(),
                "event_bundle_id": (
                    final_bundle.get("bundle_id") if final_bundle is not None else None
                ),
                "sensitive_paths_excluded": ["live/auto-arm-secret.json"],
                "file_count": len(files),
                "total_bytes": sum(row["size_bytes"] for row in files),
                "files": files,
            }
            backup_hash = canonical_hash(core)
            payload = core | {"backup_id": backup_hash, "backup_hash": backup_hash}
            _write_exclusive(temporary / "manifest.json", payload)
            destination = snapshots / backup_hash
            if destination.exists():
                raise FomcEvidenceError("fomc_evidence_backup_id_collision")
            os.replace(temporary, destination)
            _fsync_directory(snapshots)
            marker_core = {
                "schema_version": FOMC_EVIDENCE_BACKUP_SCHEMA_VERSION,
                "backup_id": backup_hash,
                "completed_at": completed.isoformat(),
                "backup_hash": backup_hash,
            }
            _write_latest(root / "latest-success.json", marker_core | {"marker_hash": canonical_hash(marker_core)})
            return payload
        except Exception:
            if temporary.exists():
                for path in sorted(temporary.rglob("*"), reverse=True):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                temporary.rmdir()
            raise


__all__ = (
    "FOMC_EVENT_BUNDLE_SCHEMA_VERSION",
    "FOMC_EVENT_SCORECARD_SCHEMA_VERSION",
    "FOMC_EVIDENCE_BACKUP_SCHEMA_VERSION",
    "FomcEvidenceError",
    "build_fomc_event_scorecard",
    "create_fomc_evidence_backup",
    "finalize_fomc_event_bundle",
)
