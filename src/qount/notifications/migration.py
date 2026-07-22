"""Verified, idempotent replay into the canonical notification store."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.notifications.contracts import AlertEvent
from qount.notifications.read_model import build_notification_snapshot
from qount.notifications.store import NotificationStore


NOTIFICATION_MIGRATION_SCHEMA_VERSION = 1
_LEGACY_SYNTHETIC_TITLE = "Order-free authority bundle assembled"


def _utc_time(value: str) -> str:
    return aware_datetime(value).astimezone(dt.timezone.utc).isoformat()


def replay_verified_notification_store(
    source_path: str | Path,
    target_path: str | Path,
    *,
    imported_at: str,
    resolve_open_info: bool = True,
) -> dict[str, Any]:
    """Replay verified incidents without claiming historical delivery parity."""

    imported_at = _utc_time(imported_at)
    source = NotificationStore(source_path, read_only=True)
    target = NotificationStore(target_path)
    source_rows = source.verified_rows()
    source_jobs: dict[str, list[dict[str, Any]]] = {}
    for job in source_rows["jobs"]:
        source_jobs.setdefault(str(job["alert_id"]), []).append(job)

    replayed: list[str] = []
    skipped_synthetic: list[str] = []
    for alert_id, payload in sorted(source_rows["events"].items()):
        alert = AlertEvent(**payload)
        alert.validate()
        if (
            alert.category == "system_health"
            and alert.title == _LEGACY_SYNTHETIC_TITLE
        ):
            skipped_synthetic.append(alert_id)
            continue
        channels = tuple(
            sorted(
                {
                    str(job["channel"])
                    for job in source_jobs.get(alert_id, ())
                }
                or {"dashboard"}
            )
        )
        max_attempts = max(
            (
                int(job["max_attempts"])
                for job in source_jobs.get(alert_id, ())
            ),
            default=3,
        )
        target.enqueue(
            alert,
            channels=channels,
            recorded_at=max(imported_at, alert.occurred_at),
            max_attempts=max_attempts,
        )
        source_state = source_rows["states"][alert_id]
        target_state = target.verified_rows()["states"][alert_id]
        should_resolve = source_state["status"] == "RESOLVED" or (
            resolve_open_info and alert.severity == "INFO"
        )
        if should_resolve and target_state["status"] == "OPEN":
            resolved_at = (
                str(source_state["resolved_at"])
                if source_state["resolved_at"] is not None
                else imported_at
            )
            target.resolve_alert(alert_id, resolved_at=resolved_at)
        replayed.append(alert_id)

    resolved_target_info: list[str] = []
    if resolve_open_info:
        target_rows = target.verified_rows()
        for alert_id, payload in sorted(target_rows["events"].items()):
            if (
                payload["severity"] == "INFO"
                and target_rows["states"][alert_id]["status"] == "OPEN"
            ):
                target.resolve_alert(alert_id, resolved_at=imported_at)
                resolved_target_info.append(alert_id)

    target_snapshot = build_notification_snapshot(
        target, captured_at=imported_at
    )
    source_audit_hash = (
        source_rows["audit"][-1]["row_hash"]
        if source_rows["audit"]
        else canonical_hash({"notification_audit": "empty"})
    )
    core = {
        "schema_version": NOTIFICATION_MIGRATION_SCHEMA_VERSION,
        "imported_at": imported_at,
        "source_path": str(Path(source_path).resolve()),
        "target_path": str(Path(target_path).resolve()),
        "source_audit_hash": source_audit_hash,
        "source_audit_row_count": len(source_rows["audit"]),
        "replayed_alert_ids": replayed,
        "skipped_synthetic_alert_ids": skipped_synthetic,
        "resolved_target_info_alert_ids": resolved_target_info,
        "delivery_history_replayed": False,
        "target_snapshot_hash": target_snapshot.snapshot_hash,
    }
    return core | {"migration_hash": canonical_hash(core)}


__all__ = [
    "NOTIFICATION_MIGRATION_SCHEMA_VERSION",
    "replay_verified_notification_store",
]
