"""Deterministic alert producers over verified authority surfaces."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts import validate_decision_batch
from qount.contracts.trace import aware_datetime
from qount.ledger import RuntimeLedgerSnapshot
from qount.notifications.contracts import ALERT_SOURCE_TYPES
from qount.notifications.contracts import AlertEvent
from qount.notifications.store import NotificationStore
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import artifact_envelope


SYSTEM_HEALTH_SCHEMA_VERSION = 1
PRODUCER_INCIDENT_SYNC_SCHEMA_VERSION = 1
SYSTEM_HEALTH_STATUSES = ("healthy", "degraded", "unavailable")
_COMPONENT_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_DETAIL_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/=-]{0,127}$")


class AlertProducerError(ValueError):
    """Raised when a producer source is invalid or has been tampered with."""


def _utc_time(value: str, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise AlertProducerError(f"{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _codes_text(codes: Sequence[str]) -> str:
    normalized = tuple(str(code) for code in codes)
    joined = ", ".join(normalized)
    if len(joined) <= 600:
        return joined
    return (
        f"{joined[:440]}...; code_count={len(normalized)}; "
        f"codes_hash={canonical_hash({'codes': normalized})}"
    )


@dataclass(frozen=True)
class SystemHealthObservation:
    """Explicit, immutable input for a system-health alert producer."""

    schema_version: int
    observation_id: str
    component: str
    status: str
    observed_at: str
    detail_codes: tuple[str, ...]
    source_id: str
    source_hash: str
    trace_id: str | None
    observation_hash: str

    @classmethod
    def create(
        cls,
        *,
        component: str,
        status: str,
        observed_at: str,
        detail_codes: Sequence[str],
        source_id: str,
        source_hash: str,
        trace_id_value: str | None = None,
    ) -> SystemHealthObservation:
        observed_at = _utc_time(observed_at, name="system_health_observed_at")
        normalized_codes = tuple(sorted(str(code) for code in detail_codes))
        core = {
            "schema_version": SYSTEM_HEALTH_SCHEMA_VERSION,
            "component": component,
            "status": status,
            "observed_at": observed_at,
            "detail_codes": normalized_codes,
            "source_id": source_id,
            "source_hash": source_hash,
            "trace_id": trace_id_value,
        }
        observation_hash = canonical_hash(core)
        observation = cls(
            **core,
            observation_id=trace_id(
                "system_health_observation",
                {
                    "component": component,
                    "observed_at": observed_at,
                    "observation_hash": observation_hash,
                },
            ),
            observation_hash=observation_hash,
        )
        observation.validate()
        return observation

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "component": self.component,
            "status": self.status,
            "observed_at": self.observed_at,
            "detail_codes": self.detail_codes,
            "source_id": self.source_id,
            "source_hash": self.source_hash,
            "trace_id": self.trace_id,
        }

    def validate(self) -> None:
        if self.schema_version != SYSTEM_HEALTH_SCHEMA_VERSION:
            raise AlertProducerError("system_health_schema_invalid")
        if not isinstance(self.component, str) or not _COMPONENT_RE.fullmatch(
            self.component
        ):
            raise AlertProducerError("system_health_component_invalid")
        if self.status not in SYSTEM_HEALTH_STATUSES:
            raise AlertProducerError("system_health_status_invalid")
        _utc_time(self.observed_at, name="system_health_observed_at")
        if (
            not isinstance(self.detail_codes, tuple)
            or len(self.detail_codes) > 32
            or tuple(sorted(self.detail_codes)) != self.detail_codes
            or len(self.detail_codes) != len(set(self.detail_codes))
            or any(
                not isinstance(code, str) or not _DETAIL_CODE_RE.fullmatch(code)
                for code in self.detail_codes
            )
        ):
            raise AlertProducerError("system_health_detail_codes_invalid")
        if (self.status == "healthy") is not (not self.detail_codes):
            raise AlertProducerError("system_health_status_detail_mismatch")
        for name in ("observation_id", "observation_hash", "source_id", "source_hash"):
            if not is_sha256(getattr(self, name)):
                raise AlertProducerError(f"system_health_{name}_invalid")
        if self.trace_id is not None and not is_sha256(self.trace_id):
            raise AlertProducerError("system_health_trace_id_invalid")
        expected_hash = canonical_hash(self._core())
        if self.observation_hash != expected_hash:
            raise AlertProducerError("system_health_observation_hash_invalid")
        expected_id = trace_id(
            "system_health_observation",
            {
                "component": self.component,
                "observed_at": self.observed_at,
                "observation_hash": expected_hash,
            },
        )
        if self.observation_id != expected_id:
            raise AlertProducerError("system_health_observation_id_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "observation_id": self.observation_id,
            "observation_hash": self.observation_hash,
        }


@dataclass(frozen=True)
class ProducerIncidentSync:
    """Immutable result of one scoped producer-to-store synchronization."""

    schema_version: int
    sync_id: str
    source_type: str
    categories: tuple[str, ...]
    observed_at: str
    active_alert_ids: tuple[str, ...]
    resolved_alert_ids: tuple[str, ...]
    sync_hash: str

    @classmethod
    def create(
        cls,
        *,
        source_type: str,
        categories: Sequence[str],
        observed_at: str,
        active_alert_ids: Sequence[str],
        resolved_alert_ids: Sequence[str],
    ) -> ProducerIncidentSync:
        normalized_categories = tuple(sorted(str(value) for value in categories))
        normalized_active = tuple(sorted(str(value) for value in active_alert_ids))
        normalized_resolved = tuple(
            sorted(str(value) for value in resolved_alert_ids)
        )
        core = {
            "schema_version": PRODUCER_INCIDENT_SYNC_SCHEMA_VERSION,
            "source_type": source_type,
            "categories": normalized_categories,
            "observed_at": _utc_time(
                observed_at, name="producer_incident_sync_observed_at"
            ),
            "active_alert_ids": normalized_active,
            "resolved_alert_ids": normalized_resolved,
        }
        sync_hash = canonical_hash(core)
        result = cls(
            **core,
            sync_id=trace_id(
                "producer_incident_sync",
                {
                    "source_type": source_type,
                    "categories": normalized_categories,
                    "observed_at": core["observed_at"],
                    "sync_hash": sync_hash,
                },
            ),
            sync_hash=sync_hash,
        )
        result.validate()
        return result

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_type": self.source_type,
            "categories": self.categories,
            "observed_at": self.observed_at,
            "active_alert_ids": self.active_alert_ids,
            "resolved_alert_ids": self.resolved_alert_ids,
        }

    def validate(self) -> None:
        if self.schema_version != PRODUCER_INCIDENT_SYNC_SCHEMA_VERSION:
            raise AlertProducerError("producer_incident_sync_schema_invalid")
        if self.source_type not in ALERT_SOURCE_TYPES:
            raise AlertProducerError("producer_incident_sync_source_type_invalid")
        if (
            not isinstance(self.categories, tuple)
            or not self.categories
            or self.categories != tuple(sorted(self.categories))
            or len(self.categories) != len(set(self.categories))
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value)
                for value in self.categories
            )
        ):
            raise AlertProducerError("producer_incident_sync_categories_invalid")
        _utc_time(self.observed_at, name="producer_incident_sync_observed_at")
        for name, values in (
            ("active", self.active_alert_ids),
            ("resolved", self.resolved_alert_ids),
        ):
            if (
                not isinstance(values, tuple)
                or values != tuple(sorted(values))
                or len(values) != len(set(values))
                or any(not is_sha256(value) for value in values)
            ):
                raise AlertProducerError(f"producer_incident_sync_{name}_invalid")
        if set(self.active_alert_ids) & set(self.resolved_alert_ids):
            raise AlertProducerError("producer_incident_sync_sets_overlap")
        expected_hash = canonical_hash(self._core())
        if self.sync_hash != expected_hash:
            raise AlertProducerError("producer_incident_sync_hash_invalid")
        expected_id = trace_id(
            "producer_incident_sync",
            {
                "source_type": self.source_type,
                "categories": self.categories,
                "observed_at": self.observed_at,
                "sync_hash": expected_hash,
            },
        )
        if self.sync_id != expected_id:
            raise AlertProducerError("producer_incident_sync_id_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "sync_id": self.sync_id,
            "sync_hash": self.sync_hash,
        }


def synchronize_producer_incidents(
    store: NotificationStore,
    alerts: Sequence[AlertEvent],
    *,
    source_type: str,
    categories: Sequence[str],
    observed_at: str,
    channels: Sequence[str] = ("dashboard",),
    max_attempts: int = 3,
) -> ProducerIncidentSync:
    """Durably enqueue active incidents, then resolve older incidents in scope."""

    if not isinstance(store, NotificationStore):
        raise TypeError("producer_incident_sync_store_required")
    observed_at = _utc_time(
        observed_at, name="producer_incident_sync_observed_at"
    )
    normalized_categories = tuple(sorted(str(value) for value in categories))
    current = tuple(sorted(alerts, key=lambda event: event.alert_id))
    for event in current:
        if not isinstance(event, AlertEvent):
            raise TypeError("producer_incident_sync_alert_required")
        event.validate()
        if (
            event.source_type != source_type
            or event.category not in normalized_categories
        ):
            raise AlertProducerError("producer_incident_sync_scope_mismatch")
        if aware_datetime(event.occurred_at) > aware_datetime(observed_at):
            raise AlertProducerError("producer_incident_sync_alert_after_observation")
    if len({event.alert_id for event in current}) != len(current):
        raise AlertProducerError("producer_incident_sync_alert_duplicate")
    for event in current:
        store.enqueue(
            event,
            channels=channels,
            recorded_at=observed_at,
            max_attempts=max_attempts,
        )
    active_ids = tuple(event.alert_id for event in current)
    resolved_ids = store.resolve_superseded_alerts(
        active_alert_ids=active_ids,
        source_type=source_type,
        categories=normalized_categories,
        resolved_at=observed_at,
    )
    return ProducerIncidentSync.create(
        source_type=source_type,
        categories=normalized_categories,
        observed_at=observed_at,
        active_alert_ids=active_ids,
        resolved_alert_ids=resolved_ids,
    )


def _verified_batch_errors(batch: VerifiedDecisionBatch) -> tuple[str, ...]:
    errors = list(batch.manifest.validate())
    errors.extend(
        validate_decision_batch(
            batch.snapshot,
            batch.intents,
            batch.target,
            batch.risk,
            batch.plan,
        )
    )
    if batch.manifest.batch_id != batch.risk.batch_id:
        errors.append("alert_producer_manifest_batch_id_mismatch")
    values = (
        batch.snapshot,
        *sorted(batch.intents, key=lambda intent: intent.decision_id),
        batch.target,
        batch.risk,
        batch.plan,
    )
    references = batch.manifest.artifact_references()
    if len(values) != len(references):
        errors.append("alert_producer_manifest_reference_count_mismatch")
    else:
        for reference, value in zip(references, values, strict=True):
            try:
                envelope = artifact_envelope(value)
            except (TypeError, ValueError) as exc:
                errors.append(
                    "alert_producer_manifest_reference_object_invalid:"
                    f"{reference.file_name}:{type(exc).__name__}"
                )
                continue
            if any(
                getattr(reference, name) != envelope[name]
                for name in ("artifact_type", "object_id", "payload_hash", "artifact_hash")
            ):
                errors.append(
                    f"alert_producer_manifest_reference_mismatch:{reference.file_name}"
                )
    return tuple(dict.fromkeys(errors))


def _alert(
    *,
    severity: str,
    category: str,
    title: str,
    summary: str,
    occurred_at: str,
    source_type: str,
    source_id: str,
    source_hash: str,
    trace_id_value: str | None,
) -> AlertEvent:
    return AlertEvent.create(
        severity=severity,
        category=category,
        title=title,
        summary=summary,
        occurred_at=occurred_at,
        source_type=source_type,
        source_id=source_id,
        source_hash=source_hash,
        dedupe_key=f"{source_type}:{category}:{source_id}",
        trace_id_value=trace_id_value,
    )


def alerts_from_verified_decision_batch(
    batch: VerifiedDecisionBatch,
) -> tuple[AlertEvent, ...]:
    """Map a complete decision batch to fail-closed decision alerts."""

    if not isinstance(batch, VerifiedDecisionBatch):
        raise TypeError("alert_producer_verified_decision_batch_required")
    errors = _verified_batch_errors(batch)
    if errors:
        raise AlertProducerError(
            f"alert_producer_decision_batch_invalid:{','.join(errors)}"
        )
    alerts: list[AlertEvent] = []
    quality = batch.snapshot.data_quality
    quality_blockers = tuple(quality["blockers"])
    if quality["complete"] is not True:
        alerts.append(
            _alert(
                severity="CRITICAL",
                category="data_quality",
                title="Decision snapshot data is incomplete",
                summary=f"Data-quality blockers: {_codes_text(quality_blockers)}.",
                occurred_at=batch.snapshot.decision_time,
                source_type="decision_batch",
                source_id=batch.snapshot.snapshot_id,
                source_hash=batch.snapshot.snapshot_hash,
                trace_id_value=batch.manifest.batch_id,
            )
        )
    if not batch.target.allocatable or batch.target.blockers:
        target_codes = batch.target.blockers or ("PORTFOLIO_TARGET_NOT_ALLOCATABLE",)
        alerts.append(
            _alert(
                severity="WARNING",
                category="portfolio_allocation",
                title="Portfolio target was blocked",
                summary=f"Allocation blockers: {_codes_text(target_codes)}.",
                occurred_at=batch.target.decision_time,
                source_type="decision_batch",
                source_id=batch.target.portfolio_target_id,
                source_hash=batch.target.target_hash,
                trace_id_value=batch.manifest.batch_id,
            )
        )
    if not batch.risk.approved or batch.risk.violations:
        risk_codes = batch.risk.violations or ("RISK_DECISION_NOT_APPROVED",)
        alerts.append(
            _alert(
                severity="CRITICAL",
                category="risk_decision",
                title="Risk decision blocked execution",
                summary=f"Risk violations: {_codes_text(risk_codes)}.",
                occurred_at=batch.risk.decision_time,
                source_type="decision_batch",
                source_id=batch.risk.risk_decision_id,
                source_hash=batch.risk.decision_hash,
                trace_id_value=batch.manifest.batch_id,
            )
        )
    if not batch.plan.executable or batch.plan.blockers:
        plan_codes = batch.plan.blockers or ("ORDER_PLAN_NOT_EXECUTABLE",)
        alerts.append(
            _alert(
                severity="WARNING",
                category="execution_plan",
                title="Order plan is not executable",
                summary=f"Execution blockers: {_codes_text(plan_codes)}.",
                occurred_at=batch.plan.created_at,
                source_type="decision_batch",
                source_id=batch.plan.order_plan_id,
                source_hash=batch.plan.plan_hash,
                trace_id_value=batch.manifest.batch_id,
            )
        )
    return tuple(alerts)


def alerts_from_runtime_ledger_snapshot(
    snapshot: RuntimeLedgerSnapshot,
) -> tuple[AlertEvent, ...]:
    """Map a frozen ledger snapshot to recovery, accounting, and recon alerts."""

    if not isinstance(snapshot, RuntimeLedgerSnapshot):
        raise TypeError("alert_producer_runtime_ledger_snapshot_required")
    try:
        snapshot.validate()
    except ValueError as exc:
        raise AlertProducerError(
            f"alert_producer_runtime_snapshot_invalid:{exc}"
        ) from exc
    alerts: list[AlertEvent] = []
    if snapshot.unresolved_order_ids:
        alerts.append(
            _alert(
                severity="HALT",
                category="order_recovery",
                title="Recoverable order states require resolution",
                summary=(
                    f"{len(snapshot.unresolved_order_ids)} order state(s) require "
                    "deterministic client-ID recovery before risk can increase."
                ),
                occurred_at=snapshot.source_updated_at,
                source_type="runtime_ledger",
                source_id=snapshot.audit_last_hash,
                source_hash=snapshot.audit_last_hash,
                trace_id_value=snapshot.batch_id,
            )
        )
    reconciliation = snapshot.reconciliation
    if not reconciliation["passed"]:
        alerts.append(
            _alert(
                severity="HALT" if reconciliation["halt_required"] else "CRITICAL",
                category="reconciliation",
                title="Three-way reconciliation failed",
                summary=(
                    "Reconciliation blockers: "
                    f"{_codes_text(reconciliation['blockers'])}."
                ),
                occurred_at=str(reconciliation["reconciled_at"]),
                source_type="reconciliation",
                source_id=str(reconciliation["reconciliation_id"]),
                source_hash=str(reconciliation["report_hash"]),
                trace_id_value=snapshot.batch_id,
            )
        )
    nav = snapshot.nav
    if not nav["passed"]:
        alerts.append(
            _alert(
                severity="CRITICAL",
                category="accounting_residual",
                title="NAV accounting residual exceeded tolerance",
                summary=(
                    f"Residual {float(nav['residual']):.12g} exceeded tolerance "
                    f"{float(nav['residual_tolerance']):.12g}."
                ),
                occurred_at=str(nav["marked_at"]),
                source_type="runtime_ledger",
                source_id=str(nav["nav_mark_id"]),
                source_hash=str(nav["mark_hash"]),
                trace_id_value=snapshot.batch_id,
            )
        )
    return tuple(alerts)


def alerts_from_system_health(
    observation: SystemHealthObservation,
) -> tuple[AlertEvent, ...]:
    """Map an explicit health observation without probing any service."""

    if not isinstance(observation, SystemHealthObservation):
        raise TypeError("alert_producer_system_health_observation_required")
    observation.validate()
    if observation.status == "healthy":
        return ()
    return (
        _alert(
            severity="WARNING" if observation.status == "degraded" else "CRITICAL",
            category="system_health",
            title=f"{observation.component} is {observation.status}",
            summary=f"Health detail codes: {_codes_text(observation.detail_codes)}.",
            occurred_at=observation.observed_at,
            source_type="system",
            source_id=observation.observation_id,
            source_hash=observation.observation_hash,
            trace_id_value=observation.trace_id,
        ),
    )
