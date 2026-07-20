"""Append-only hash-chain journal used as the SQLite audit outbox sink."""

from __future__ import annotations

import fcntl
import json
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256


AUDIT_SCHEMA_VERSION = 1
ZERO_HASH = "0" * 64


class AuditJournalError(ValueError):
    """Raised when the append-only audit journal cannot be trusted."""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _parse_line(raw: bytes, *, line_number: int) -> Mapping[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuditJournalError(
                    f"audit_journal_duplicate_key:{line_number}:{key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate)
    except AuditJournalError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditJournalError(
            f"audit_journal_json_invalid:{line_number}"
        ) from exc
    if not isinstance(value, dict):
        raise AuditJournalError(f"audit_journal_row_invalid:{line_number}")
    if canonical_json_bytes(value) != raw:
        raise AuditJournalError(f"audit_journal_not_canonical:{line_number}")
    return value


def build_audit_row(
    *,
    sequence: int,
    event_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    occurred_at: str,
    payload: Mapping[str, Any],
    previous_hash: str,
) -> dict[str, Any]:
    core = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "sequence": sequence,
        "event_id": event_id,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "occurred_at": occurred_at,
        "payload": dict(payload),
        "previous_hash": previous_hash,
    }
    row = core | {"row_hash": canonical_hash(core)}
    _validate_audit_row(row)
    return row


def _validate_audit_row(row: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "sequence",
        "event_id",
        "event_type",
        "entity_type",
        "entity_id",
        "occurred_at",
        "payload",
        "previous_hash",
        "row_hash",
    }
    if set(row) != expected:
        raise AuditJournalError("audit_journal_row_fields_invalid")
    if row["schema_version"] != AUDIT_SCHEMA_VERSION:
        raise AuditJournalError("audit_journal_schema_invalid")
    if (
        not isinstance(row["sequence"], int)
        or isinstance(row["sequence"], bool)
        or row["sequence"] < 1
    ):
        raise AuditJournalError("audit_journal_sequence_invalid")
    for name in ("event_id", "previous_hash", "row_hash"):
        if not is_sha256(row[name]):
            raise AuditJournalError(f"audit_journal_{name}_invalid")
    for name in ("event_type", "entity_type", "entity_id"):
        if not isinstance(row[name], str) or not row[name]:
            raise AuditJournalError(f"audit_journal_{name}_invalid")
    try:
        aware_datetime(str(row["occurred_at"]))
    except (AttributeError, TypeError, ValueError) as exc:
        raise AuditJournalError("audit_journal_occurred_at_invalid") from exc
    if not isinstance(row["payload"], dict):
        raise AuditJournalError("audit_journal_payload_invalid")
    core = {name: row[name] for name in expected if name != "row_hash"}
    if row["row_hash"] != canonical_hash(core):
        raise AuditJournalError("audit_journal_row_hash_invalid")


@dataclass(frozen=True)
class AuditJournalState:
    row_count: int
    last_sequence: int
    last_hash: str
    rows_by_sequence: Mapping[int, Mapping[str, Any]]


def verify_audit_journal(path: str | Path) -> AuditJournalState:
    source = Path(path)
    if source.is_symlink():
        raise AuditJournalError("audit_journal_symlink_forbidden")
    if not source.exists():
        return AuditJournalState(0, 0, ZERO_HASH, {})
    if not source.is_file():
        raise AuditJournalError("audit_journal_file_invalid")
    if stat.S_IMODE(os.stat(source, follow_symlinks=False).st_mode) != 0o600:
        raise AuditJournalError("audit_journal_mode_invalid")
    rows_by_sequence: dict[int, Mapping[str, Any]] = {}
    previous_hash = ZERO_HASH
    previous_time = None
    for line_number, raw in enumerate(source.read_bytes().splitlines(keepends=True), 1):
        row = _parse_line(raw, line_number=line_number)
        _validate_audit_row(row)
        if row["sequence"] != line_number:
            raise AuditJournalError(
                f"audit_journal_sequence_gap:{line_number}"
            )
        if row["previous_hash"] != previous_hash:
            raise AuditJournalError(
                f"audit_journal_chain_hash_invalid:{line_number}"
            )
        occurred_at = aware_datetime(str(row["occurred_at"]))
        if previous_time is not None and occurred_at < previous_time:
            raise AuditJournalError(
                f"audit_journal_time_regression:{line_number}"
            )
        if any(
            existing["event_id"] == row["event_id"]
            for existing in rows_by_sequence.values()
        ):
            raise AuditJournalError(
                f"audit_journal_event_duplicate:{line_number}"
            )
        rows_by_sequence[row["sequence"]] = row
        previous_hash = str(row["row_hash"])
        previous_time = occurred_at
    return AuditJournalState(
        row_count=len(rows_by_sequence),
        last_sequence=len(rows_by_sequence),
        last_hash=previous_hash,
        rows_by_sequence=rows_by_sequence,
    )


@contextmanager
def audit_journal_lock(path: str | Path) -> Iterator[None]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(f".{target.name}.lock")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _append_audit_row_locked(path: str | Path, row: Mapping[str, Any]) -> None:
    """Append while the caller holds ``audit_journal_lock(path)``."""

    target = Path(path)
    _validate_audit_row(row)
    state = verify_audit_journal(target)
    if row["sequence"] != state.last_sequence + 1:
        raise AuditJournalError("audit_journal_append_sequence_invalid")
    if row["previous_hash"] != state.last_hash:
        raise AuditJournalError("audit_journal_append_previous_hash_invalid")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    os.fchmod(descriptor, 0o600)
    try:
        raw = canonical_json_bytes(row)
        written = os.write(descriptor, raw)
        if written != len(raw):
            raise AuditJournalError("audit_journal_short_write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    readback = verify_audit_journal(target)
    if readback.rows_by_sequence[row["sequence"]] != row:
        raise AuditJournalError("audit_journal_append_readback_mismatch")


def append_audit_row(path: str | Path, row: Mapping[str, Any]) -> None:
    """Verify and append one row under an exclusive journal lock."""

    with audit_journal_lock(path):
        _append_audit_row_locked(path, row)
