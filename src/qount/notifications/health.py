"""Immutable, structured observations for operational system health."""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime


SYSTEM_COMPONENT_OBSERVATION_SCHEMA_VERSION = 1
SYSTEM_HEALTH_SNAPSHOT_SCHEMA_VERSION = 1
SYSTEM_COMPONENTS = ("clock", "disk", "service", "backup", "operations")
SYSTEM_HEALTH_STATUSES = ("healthy", "degraded", "unavailable")
IMPACT_SCOPES = ("delivery", "execution", "intelligence", "observation")
_DETAIL_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/=-]{0,127}$")
_SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,127}$")


class SystemHealthContractError(ValueError):
    """Raised when a system health observation cannot be trusted."""


def _utc_time(value: str, *, name: str) -> str:
    try:
        parsed = aware_datetime(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise SystemHealthContractError(f"{name}_invalid") from exc
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _finite(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SystemHealthContractError(f"{name}_invalid") from exc
    if not math.isfinite(number):
        raise SystemHealthContractError(f"{name}_invalid")
    return number


def _optional_finite(value: object, *, name: str) -> float | None:
    if value is None:
        return None
    return _finite(value, name=name)


def _integer(value: object, *, name: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SystemHealthContractError(f"{name}_invalid")
    return value


def _normalize_metrics(component: str, metrics: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(metrics, Mapping):
        raise SystemHealthContractError("system_component_metrics_invalid")
    value = dict(metrics)
    if component == "clock":
        if set(value) != {"drift_seconds"}:
            raise SystemHealthContractError("system_clock_metrics_invalid")
        return {
            "drift_seconds": _optional_finite(
                value["drift_seconds"], name="system_clock_drift_seconds"
            )
        }
    if component == "disk":
        if set(value) != {"free_bytes", "total_bytes"}:
            raise SystemHealthContractError("system_disk_metrics_invalid")
        if (value["free_bytes"] is None) is not (value["total_bytes"] is None):
            raise SystemHealthContractError("system_disk_metrics_incomplete")
        if value["free_bytes"] is None:
            return {"free_bytes": None, "total_bytes": None}
        free_bytes = _integer(
            value["free_bytes"], name="system_disk_free_bytes"
        )
        total_bytes = _integer(
            value["total_bytes"], name="system_disk_total_bytes", minimum=1
        )
        if free_bytes > total_bytes:
            raise SystemHealthContractError("system_disk_capacity_invalid")
        return {"free_bytes": free_bytes, "total_bytes": total_bytes}
    if component == "service":
        if set(value) != {"service_name", "active_state"}:
            raise SystemHealthContractError("system_service_metrics_invalid")
        service_name = value["service_name"]
        if not isinstance(service_name, str) or not _SERVICE_NAME_RE.fullmatch(
            service_name
        ):
            raise SystemHealthContractError("system_service_name_invalid")
        active_state = value["active_state"]
        if active_state not in {"active", "inactive", "failed", "unknown"}:
            raise SystemHealthContractError("system_service_active_state_invalid")
        return {"service_name": service_name, "active_state": active_state}
    if component == "backup":
        if set(value) != {"last_success_at", "age_seconds"}:
            raise SystemHealthContractError("system_backup_metrics_invalid")
        last_success_at = value["last_success_at"]
        age_seconds = value["age_seconds"]
        if (last_success_at is None) is not (age_seconds is None):
            raise SystemHealthContractError("system_backup_metrics_incomplete")
        if last_success_at is not None:
            last_success_at = _utc_time(
                last_success_at, name="system_backup_last_success_at"
            )
            age_seconds = _integer(
                age_seconds, name="system_backup_age_seconds"
            )
        return {"last_success_at": last_success_at, "age_seconds": age_seconds}
    if component == "operations":
        if set(value) != {"checks", "scope_status"}:
            raise SystemHealthContractError("system_operations_metrics_invalid")
        checks = value["checks"]
        if not isinstance(checks, (list, tuple)) or not checks:
            raise SystemHealthContractError("system_operations_checks_invalid")
        normalized_checks: list[dict[str, Any]] = []
        check_ids: list[str] = []
        for raw in checks:
            if not isinstance(raw, Mapping) or set(raw) != {
                "check_id",
                "status",
                "detail",
                "impact_scopes",
                "blocks_execution",
                "observed_value",
            }:
                raise SystemHealthContractError(
                    "system_operations_check_invalid"
                )
            check_id = raw["check_id"]
            scopes = tuple(raw["impact_scopes"])
            if (
                not isinstance(check_id, str)
                or not _DETAIL_CODE_RE.fullmatch(check_id)
                or raw["status"] not in {"pass", "warn", "block", "unavailable"}
                or not isinstance(raw["detail"], str)
                or not raw["detail"]
                or tuple(sorted(scopes)) != scopes
                or not scopes
                or len(scopes) != len(set(scopes))
                or any(scope not in IMPACT_SCOPES for scope in scopes)
                or not isinstance(raw["blocks_execution"], bool)
                or not isinstance(
                    raw["observed_value"], (str, int, float, bool, type(None))
                )
            ):
                raise SystemHealthContractError(
                    "system_operations_check_invalid"
                )
            check_ids.append(check_id)
            normalized_checks.append(
                {
                    "check_id": check_id,
                    "status": raw["status"],
                    "detail": raw["detail"],
                    "impact_scopes": list(scopes),
                    "blocks_execution": raw["blocks_execution"],
                    "observed_value": raw["observed_value"],
                }
            )
        if check_ids != sorted(check_ids) or len(check_ids) != len(set(check_ids)):
            raise SystemHealthContractError("system_operations_check_order_invalid")
        scope_status = value["scope_status"]
        if (
            not isinstance(scope_status, Mapping)
            or set(scope_status) != set(IMPACT_SCOPES)
            or any(
                status not in {"pass", "degraded", "unavailable"}
                for status in scope_status.values()
            )
        ):
            raise SystemHealthContractError(
                "system_operations_scope_status_invalid"
            )
        return {
            "checks": normalized_checks,
            "scope_status": {
                scope: scope_status[scope] for scope in IMPACT_SCOPES
            },
        }
    raise SystemHealthContractError("system_component_invalid")


@dataclass(frozen=True)
class SystemComponentObservation:
    schema_version: int
    observation_id: str
    component: str
    status: str
    observed_at: str
    detail_codes: tuple[str, ...]
    metrics: Mapping[str, Any]
    source_id: str
    source_hash: str
    observation_hash: str

    @classmethod
    def create(
        cls,
        *,
        component: str,
        status: str,
        observed_at: str,
        detail_codes: Sequence[str],
        metrics: Mapping[str, Any],
        source_id: str,
        source_hash: str,
    ) -> SystemComponentObservation:
        normalized_time = _utc_time(
            observed_at, name="system_component_observed_at"
        )
        normalized_codes = tuple(sorted(str(code) for code in detail_codes))
        normalized_metrics = _normalize_metrics(component, metrics)
        core = {
            "schema_version": SYSTEM_COMPONENT_OBSERVATION_SCHEMA_VERSION,
            "component": component,
            "status": status,
            "observed_at": normalized_time,
            "detail_codes": normalized_codes,
            "metrics": normalized_metrics,
            "source_id": source_id,
            "source_hash": source_hash,
        }
        observation_hash = canonical_hash(core)
        observation = cls(
            **core,
            observation_id=trace_id(
                "system_component_observation",
                {
                    "component": component,
                    "observed_at": normalized_time,
                    "observation_hash": observation_hash,
                },
            ),
            observation_hash=observation_hash,
        )
        observation.validate()
        return observation

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SystemComponentObservation:
        if set(value) != set(cls.__dataclass_fields__):
            raise SystemHealthContractError("system_component_fields_invalid")
        observation = cls(
            schema_version=value["schema_version"],
            observation_id=value["observation_id"],
            component=value["component"],
            status=value["status"],
            observed_at=value["observed_at"],
            detail_codes=tuple(value["detail_codes"]),
            metrics=_normalize_metrics(value["component"], value["metrics"]),
            source_id=value["source_id"],
            source_hash=value["source_hash"],
            observation_hash=value["observation_hash"],
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
            "metrics": dict(self.metrics),
            "source_id": self.source_id,
            "source_hash": self.source_hash,
        }

    def validate(self) -> None:
        if self.schema_version != SYSTEM_COMPONENT_OBSERVATION_SCHEMA_VERSION:
            raise SystemHealthContractError("system_component_schema_invalid")
        if self.component not in SYSTEM_COMPONENTS:
            raise SystemHealthContractError("system_component_invalid")
        if self.status not in SYSTEM_HEALTH_STATUSES:
            raise SystemHealthContractError("system_component_status_invalid")
        _utc_time(self.observed_at, name="system_component_observed_at")
        if (
            not isinstance(self.detail_codes, tuple)
            or len(self.detail_codes) > 32
            or self.detail_codes != tuple(sorted(self.detail_codes))
            or len(self.detail_codes) != len(set(self.detail_codes))
            or any(
                not isinstance(code, str) or not _DETAIL_CODE_RE.fullmatch(code)
                for code in self.detail_codes
            )
        ):
            raise SystemHealthContractError("system_component_detail_codes_invalid")
        if (self.status == "healthy") is not (not self.detail_codes):
            raise SystemHealthContractError(
                "system_component_status_detail_mismatch"
            )
        normalized_metrics = _normalize_metrics(self.component, self.metrics)
        if dict(self.metrics) != normalized_metrics:
            raise SystemHealthContractError("system_component_metrics_not_normalized")
        if self.component == "clock" and (
            self.metrics["drift_seconds"] is None
            and self.status != "unavailable"
        ):
            raise SystemHealthContractError("system_clock_availability_mismatch")
        if self.component == "disk" and (
            self.metrics["free_bytes"] is None
            and self.status != "unavailable"
        ):
            raise SystemHealthContractError("system_disk_availability_mismatch")
        if self.component == "backup" and self.metrics["last_success_at"] is not None:
            observed = aware_datetime(self.observed_at)
            last_success = aware_datetime(self.metrics["last_success_at"])
            expected_age = int((observed - last_success).total_seconds())
            if expected_age < 0 or self.metrics["age_seconds"] != expected_age:
                raise SystemHealthContractError("system_backup_age_mismatch")
        if self.component == "service" and (
            (self.status == "healthy") is not (
                self.metrics["active_state"] == "active"
            )
        ):
            raise SystemHealthContractError("system_service_status_mismatch")
        if self.component == "operations":
            checks = self.metrics["checks"]
            expected_status = (
                "unavailable"
                if any(
                    row["blocks_execution"]
                    and row["status"] in {"block", "unavailable"}
                    for row in checks
                )
                else "degraded"
                if any(row["status"] != "pass" for row in checks)
                else "healthy"
            )
            if self.status != expected_status:
                raise SystemHealthContractError(
                    "system_operations_status_mismatch"
                )
        for name in (
            "observation_id",
            "source_id",
            "source_hash",
            "observation_hash",
        ):
            if not is_sha256(getattr(self, name)):
                raise SystemHealthContractError(f"system_component_{name}_invalid")
        expected_hash = canonical_hash(self._core())
        if self.observation_hash != expected_hash:
            raise SystemHealthContractError("system_component_hash_invalid")
        if self.observation_id != trace_id(
            "system_component_observation",
            {
                "component": self.component,
                "observed_at": self.observed_at,
                "observation_hash": expected_hash,
            },
        ):
            raise SystemHealthContractError("system_component_id_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "detail_codes": list(self.detail_codes),
            "observation_id": self.observation_id,
            "observation_hash": self.observation_hash,
        }


@dataclass(frozen=True)
class SystemHealthSnapshot:
    schema_version: int
    snapshot_id: str
    captured_at: str
    source_updated_at: str
    status: str
    observations: tuple[Mapping[str, Any], ...]
    snapshot_hash: str

    @classmethod
    def create(
        cls,
        observations: Sequence[SystemComponentObservation],
        *,
        captured_at: str,
    ) -> SystemHealthSnapshot:
        normalized: dict[str, SystemComponentObservation] = {}
        for observation in observations:
            if not isinstance(observation, SystemComponentObservation):
                raise TypeError("system_health_component_observation_required")
            observation.validate()
            if observation.component in normalized:
                raise SystemHealthContractError("system_health_component_duplicate")
            normalized[observation.component] = observation
        if set(normalized) != set(SYSTEM_COMPONENTS):
            raise SystemHealthContractError("system_health_components_incomplete")
        captured_at = _utc_time(captured_at, name="system_health_captured_at")
        ordered = tuple(normalized[name].as_dict() for name in SYSTEM_COMPONENTS)
        source_updated_at = max(
            str(row["observed_at"]) for row in ordered
        )
        if aware_datetime(source_updated_at) > aware_datetime(captured_at):
            raise SystemHealthContractError("system_health_capture_before_source")
        statuses = {str(row["status"]) for row in ordered}
        status = (
            "unavailable"
            if "unavailable" in statuses
            else "degraded"
            if "degraded" in statuses
            else "healthy"
        )
        core = {
            "schema_version": SYSTEM_HEALTH_SNAPSHOT_SCHEMA_VERSION,
            "captured_at": captured_at,
            "source_updated_at": source_updated_at,
            "status": status,
            "observations": ordered,
        }
        snapshot_hash = canonical_hash(core)
        snapshot = cls(
            **core,
            snapshot_id=trace_id(
                "system_health_snapshot", {"snapshot_hash": snapshot_hash}
            ),
            snapshot_hash=snapshot_hash,
        )
        snapshot.validate()
        return snapshot

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SystemHealthSnapshot:
        if set(value) != set(cls.__dataclass_fields__):
            raise SystemHealthContractError("system_health_snapshot_fields_invalid")
        normalized_observations = tuple(
            SystemComponentObservation.from_dict(row).as_dict()
            for row in value["observations"]
        )
        snapshot = cls(
            schema_version=value["schema_version"],
            snapshot_id=value["snapshot_id"],
            captured_at=value["captured_at"],
            source_updated_at=value["source_updated_at"],
            status=value["status"],
            observations=normalized_observations,
            snapshot_hash=value["snapshot_hash"],
        )
        snapshot.validate()
        return snapshot

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "captured_at": self.captured_at,
            "source_updated_at": self.source_updated_at,
            "status": self.status,
            "observations": tuple(dict(row) for row in self.observations),
        }

    def validate(self) -> None:
        if self.schema_version != SYSTEM_HEALTH_SNAPSHOT_SCHEMA_VERSION:
            raise SystemHealthContractError("system_health_snapshot_schema_invalid")
        captured_at = _utc_time(
            self.captured_at, name="system_health_captured_at"
        )
        source_updated_at = _utc_time(
            self.source_updated_at, name="system_health_source_updated_at"
        )
        if aware_datetime(source_updated_at) > aware_datetime(captured_at):
            raise SystemHealthContractError("system_health_capture_before_source")
        if not isinstance(self.observations, tuple):
            raise SystemHealthContractError("system_health_observations_invalid")
        observations = tuple(
            SystemComponentObservation.from_dict(row) for row in self.observations
        )
        if tuple(row.component for row in observations) != SYSTEM_COMPONENTS:
            raise SystemHealthContractError("system_health_components_invalid")
        if source_updated_at != max(row.observed_at for row in observations):
            raise SystemHealthContractError("system_health_source_time_mismatch")
        statuses = {row.status for row in observations}
        expected_status = (
            "unavailable"
            if "unavailable" in statuses
            else "degraded"
            if "degraded" in statuses
            else "healthy"
        )
        if self.status != expected_status:
            raise SystemHealthContractError("system_health_status_mismatch")
        for name in ("snapshot_id", "snapshot_hash"):
            if not is_sha256(getattr(self, name)):
                raise SystemHealthContractError(f"system_health_{name}_invalid")
        expected_hash = canonical_hash(self._core())
        if self.snapshot_hash != expected_hash:
            raise SystemHealthContractError("system_health_snapshot_hash_invalid")
        if self.snapshot_id != trace_id(
            "system_health_snapshot", {"snapshot_hash": expected_hash}
        ):
            raise SystemHealthContractError("system_health_snapshot_id_invalid")

    def as_dict(self) -> dict[str, Any]:
        return self._core() | {
            "observations": [dict(row) for row in self.observations],
            "snapshot_id": self.snapshot_id,
            "snapshot_hash": self.snapshot_hash,
        }
