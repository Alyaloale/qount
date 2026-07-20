"""Frozen notification snapshots for reporting and static publication."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts.trace import aware_datetime
from qount.notifications.contracts import ALERT_SEVERITIES
from qount.notifications.store import DELIVERY_STATES
from qount.notifications.store import NotificationStore
from qount.notifications.store import NotificationStoreError


NOTIFICATION_SNAPSHOT_SCHEMA_VERSION = 1


def _utc_time(value: str, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise NotificationStoreError(f"{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


@dataclass(frozen=True)
class NotificationSnapshot:
    schema_version: int
    captured_at: str
    source_updated_at: str
    open_alert_count: int
    severity_counts: Mapping[str, int]
    delivery_state_counts: Mapping[str, int]
    alerts: tuple[Mapping[str, Any], ...]
    audit_last_hash: str
    audit_row_count: int
    snapshot_hash: str

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "captured_at": self.captured_at,
            "source_updated_at": self.source_updated_at,
            "open_alert_count": self.open_alert_count,
            "severity_counts": dict(self.severity_counts),
            "delivery_state_counts": dict(self.delivery_state_counts),
            "alerts": [dict(row) for row in self.alerts],
            "audit_last_hash": self.audit_last_hash,
            "audit_row_count": self.audit_row_count,
        }

    def validate(self) -> None:
        if self.schema_version != NOTIFICATION_SNAPSHOT_SCHEMA_VERSION:
            raise NotificationStoreError("notification_snapshot_schema_invalid")
        captured = aware_datetime(
            _utc_time(self.captured_at, name="notification_snapshot_captured_at")
        )
        source_updated = aware_datetime(
            _utc_time(
                self.source_updated_at,
                name="notification_snapshot_source_updated_at",
            )
        )
        if source_updated > captured:
            raise NotificationStoreError(
                "notification_snapshot_source_after_capture"
            )
        if not is_sha256(self.audit_last_hash) or not is_sha256(self.snapshot_hash):
            raise NotificationStoreError("notification_snapshot_hash_invalid")
        if (
            not isinstance(self.audit_row_count, int)
            or isinstance(self.audit_row_count, bool)
            or self.audit_row_count < 1
        ):
            raise NotificationStoreError("notification_snapshot_audit_count_invalid")
        if set(self.severity_counts) != set(ALERT_SEVERITIES) or set(
            self.delivery_state_counts
        ) != set(DELIVERY_STATES):
            raise NotificationStoreError("notification_snapshot_counts_invalid")
        for counts in (self.severity_counts, self.delivery_state_counts):
            if any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                for value in counts.values()
            ):
                raise NotificationStoreError("notification_snapshot_counts_invalid")
        if self.open_alert_count != sum(
            1 for row in self.alerts if row.get("status") == "OPEN"
        ):
            raise NotificationStoreError(
                "notification_snapshot_open_count_invalid"
            )
        if sum(self.severity_counts.values()) != len(self.alerts):
            raise NotificationStoreError(
                "notification_snapshot_severity_count_invalid"
            )
        if self.snapshot_hash != canonical_hash(self._core()):
            raise NotificationStoreError("notification_snapshot_hash_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {"snapshot_hash": self.snapshot_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NotificationSnapshot:
        """Rehydrate a published snapshot and replay its audit/hash checks."""

        expected = set(cls.__dataclass_fields__)
        if not isinstance(value, Mapping) or set(value) != expected:
            raise NotificationStoreError("notification_snapshot_fields_invalid")
        try:
            snapshot = cls(
                schema_version=value["schema_version"],
                captured_at=value["captured_at"],
                source_updated_at=value["source_updated_at"],
                open_alert_count=value["open_alert_count"],
                severity_counts=dict(value["severity_counts"]),
                delivery_state_counts=dict(value["delivery_state_counts"]),
                alerts=tuple(dict(row) for row in value["alerts"]),
                audit_last_hash=value["audit_last_hash"],
                audit_row_count=value["audit_row_count"],
                snapshot_hash=value["snapshot_hash"],
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise NotificationStoreError(
                "notification_snapshot_fields_invalid"
            ) from exc
        snapshot.validate()
        return snapshot


def build_notification_snapshot(
    store: NotificationStore,
    *,
    captured_at: str,
) -> NotificationSnapshot:
    if not isinstance(store, NotificationStore):
        raise TypeError("notification_store_required")
    captured_at = _utc_time(
        captured_at, name="notification_snapshot_captured_at"
    )
    rows = store.verified_rows()
    audit = rows["audit"]
    if not audit:
        raise NotificationStoreError("notification_snapshot_empty_store")
    source_updated_at = max(row["occurred_at"] for row in audit)
    if aware_datetime(source_updated_at) > aware_datetime(captured_at):
        raise NotificationStoreError("notification_snapshot_source_after_capture")
    jobs_by_alert: dict[str, list[dict[str, Any]]] = {}
    for job in rows["jobs"]:
        jobs_by_alert.setdefault(job["alert_id"], []).append(job)
    alerts: list[Mapping[str, Any]] = []
    for alert_id, event in rows["events"].items():
        state = rows["states"][alert_id]
        deliveries = [
            {
                name: job[name]
                for name in (
                    "job_id",
                    "channel",
                    "delivery_key",
                    "status",
                    "attempt_count",
                    "max_attempts",
                    "next_attempt_at",
                    "last_attempt_at",
                    "delivered_at",
                    "last_error",
                    "job_hash",
                )
            }
            for job in jobs_by_alert.get(alert_id, [])
        ]
        alerts.append(
            {
                **event,
                "status": state["status"],
                "resolved_at": state["resolved_at"],
                "state_hash": state["state_hash"],
                "deliveries": deliveries,
            }
        )
    alerts.sort(key=lambda row: (row["occurred_at"], row["alert_id"]), reverse=True)
    severity_counts = {
        severity: sum(1 for row in alerts if row["severity"] == severity)
        for severity in ALERT_SEVERITIES
    }
    delivery_state_counts = {
        status: sum(
            1
            for alert in alerts
            for delivery in alert["deliveries"]
            if delivery["status"] == status
        )
        for status in DELIVERY_STATES
    }
    core = {
        "schema_version": NOTIFICATION_SNAPSHOT_SCHEMA_VERSION,
        "captured_at": captured_at,
        "source_updated_at": source_updated_at,
        "open_alert_count": sum(1 for row in alerts if row["status"] == "OPEN"),
        "severity_counts": severity_counts,
        "delivery_state_counts": delivery_state_counts,
        "alerts": alerts,
        "audit_last_hash": audit[-1]["row_hash"],
        "audit_row_count": len(audit),
    }
    snapshot = NotificationSnapshot(**core, snapshot_hash=canonical_hash(core))
    snapshot.validate()
    return snapshot
