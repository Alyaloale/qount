"""Immutable notification contracts with deterministic identities."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime


ALERT_EVENT_SCHEMA_VERSION = 1
ALERT_SEVERITIES = ("INFO", "WARNING", "CRITICAL", "HALT")
ALERT_SOURCE_TYPES = (
    "decision_batch",
    "event_strategy",
    "intelligence",
    "runtime_ledger",
    "reconciliation",
    "system",
)
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class NotificationContractError(ValueError):
    """Raised when a notification contract is malformed or tampered."""


def _utc_time(value: str, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise NotificationContractError(f"{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _text(value: object, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise NotificationContractError(f"{name}_invalid")
    if len(value) > maximum or any(ord(char) < 32 for char in value):
        raise NotificationContractError(f"{name}_invalid")
    return value


@dataclass(frozen=True)
class AlertEvent:
    schema_version: int
    alert_id: str
    severity: str
    category: str
    title: str
    summary: str
    occurred_at: str
    source_type: str
    source_id: str
    source_hash: str
    dedupe_key: str
    trace_id: str | None
    event_hash: str

    @classmethod
    def create(
        cls,
        *,
        severity: str,
        category: str,
        title: str,
        summary: str,
        occurred_at: str,
        source_type: str,
        source_id: str,
        source_hash: str,
        dedupe_key: str,
        trace_id_value: str | None = None,
    ) -> AlertEvent:
        occurred_at = _utc_time(occurred_at, name="alert_occurred_at")
        identity = {
            "source_type": source_type,
            "source_id": source_id,
            "dedupe_key": dedupe_key,
        }
        core = {
            "schema_version": ALERT_EVENT_SCHEMA_VERSION,
            "severity": severity,
            "category": category,
            "title": title,
            "summary": summary,
            "occurred_at": occurred_at,
            "source_type": source_type,
            "source_id": source_id,
            "source_hash": source_hash,
            "dedupe_key": dedupe_key,
            "trace_id": trace_id_value,
        }
        event = cls(
            **core,
            alert_id=trace_id("alert_event", identity),
            event_hash=canonical_hash(core),
        )
        event.validate()
        return event

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "summary": self.summary,
            "occurred_at": self.occurred_at,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_hash": self.source_hash,
            "dedupe_key": self.dedupe_key,
            "trace_id": self.trace_id,
        }

    def validate(self) -> None:
        if self.schema_version != ALERT_EVENT_SCHEMA_VERSION:
            raise NotificationContractError("alert_schema_version_invalid")
        if self.severity not in ALERT_SEVERITIES:
            raise NotificationContractError("alert_severity_invalid")
        if not isinstance(self.category, str) or not _CATEGORY_RE.fullmatch(
            self.category
        ):
            raise NotificationContractError("alert_category_invalid")
        _text(self.title, name="alert_title", maximum=160)
        _text(self.summary, name="alert_summary", maximum=1_000)
        _utc_time(self.occurred_at, name="alert_occurred_at")
        if self.source_type not in ALERT_SOURCE_TYPES:
            raise NotificationContractError("alert_source_type_invalid")
        for name in ("source_id", "source_hash", "event_hash", "alert_id"):
            if not is_sha256(getattr(self, name)):
                raise NotificationContractError(f"alert_{name}_invalid")
        _text(self.dedupe_key, name="alert_dedupe_key", maximum=240)
        if self.trace_id is not None and not is_sha256(self.trace_id):
            raise NotificationContractError("alert_trace_id_invalid")
        expected_hash = canonical_hash(self._core())
        if self.event_hash != expected_hash:
            raise NotificationContractError("alert_event_hash_invalid")
        expected_id = trace_id(
            "alert_event",
            {
                "source_type": self.source_type,
                "source_id": self.source_id,
                "dedupe_key": self.dedupe_key,
            },
        )
        if self.alert_id != expected_id:
            raise NotificationContractError("alert_id_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "alert_id": self.alert_id,
            "event_hash": self.event_hash,
        }
