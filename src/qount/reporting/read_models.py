"""Verified Dashboard v1 read models and atomic static publication."""

from __future__ import annotations

import json
import math
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.contracts import trace_id
from qount.contracts import validate_decision_batch
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.governance import StrategyRegistry
from qount.governance import validate_registered_intents
from qount.intelligence import DailyIntelligenceReport
from qount.intelligence import IntelligenceContractError
from qount.intelligence import daily_intelligence_from_dict
from qount.ledger import RuntimeLedgerSnapshot
from qount.notifications import ALERT_SEVERITIES
from qount.notifications import DELIVERY_STATES
from qount.notifications import AlertEvent
from qount.notifications import NotificationSnapshot
from qount.notifications import SystemHealthContractError
from qount.notifications import SystemHealthSnapshot
from qount.persistence import VerifiedDecisionBatch
from qount.persistence import artifact_envelope
from qount.reporting.daily_brief import DailyBrief
from qount.reporting.daily_brief import DailyBriefError
from qount.reporting.daily_brief import daily_brief_from_dict
from qount.reporting.daily_brief import validate_daily_brief_sources


DASHBOARD_SCHEMA_VERSION = 1
READ_MODEL_TYPES = (
    "overview",
    "positions",
    "orders",
    "strategies",
    "decisions",
    "risk",
    "readiness",
    "system",
    "alerts",
    "reports",
    "intelligence",
)
_READ_MODEL_FILES = {
    "overview": "overview.json",
    "positions": "positions.json",
    "orders": "orders.json",
    "strategies": "strategies.json",
    "decisions": "decisions.json",
    "risk": "risk.json",
    "readiness": "readiness.json",
    "system": "system.json",
    "alerts": "alerts.json",
    "reports": "reports.json",
    "intelligence": "intelligence.json",
}
_PUBLICATION_FILE = "publication.json"
_BASE_SOURCE_KEYS = {"decision_batch_manifest", "strategy_registry"}
_RUNTIME_SOURCE_KEYS = _BASE_SOURCE_KEYS | {"runtime_ledger"}
_BLOCKED_RUNTIME_SOURCE_KEYS = _BASE_SOURCE_KEYS | {"blocked_runtime_observation"}
_NOTIFICATION_SOURCE_KEYS = {"notification_store"}
_REPORT_SOURCE_KEYS = {"daily_brief"}
_INTELLIGENCE_SOURCE_KEYS = {"daily_intelligence"}
_SYSTEM_HEALTH_SOURCE_KEYS = _BASE_SOURCE_KEYS | {"system_health"}
_SYSTEM_RUNTIME_SOURCE_KEYS = _RUNTIME_SOURCE_KEYS | {"system_health"}
_SYSTEM_BLOCKED_RUNTIME_SOURCE_KEYS = _BLOCKED_RUNTIME_SOURCE_KEYS | {"system_health"}
_HEX_ID_LENGTH = 64


class DashboardReadModelError(ValueError):
    """Raised when a read model source, payload, or publication is invalid."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _mapping(value: object, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DashboardReadModelError(f"{name}_must_be_object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    name: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = ",".join(sorted(expected - actual)) or "none"
        unexpected = ",".join(sorted(actual - expected)) or "none"
        raise DashboardReadModelError(
            f"{name}_fields_mismatch:missing={missing}:unexpected={unexpected}"
        )


def _finite_nonnegative(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DashboardReadModelError(f"{name}_invalid") from exc
    if not math.isfinite(number) or number < 0.0:
        raise DashboardReadModelError(f"{name}_invalid")
    return number


def _finite(value: object, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DashboardReadModelError(f"{name}_invalid") from exc
    if not math.isfinite(number):
        raise DashboardReadModelError(f"{name}_invalid")
    return number


def _gross(weights: Mapping[str, float]) -> float:
    return round(
        sum(
            _finite_nonnegative(value, name=f"weight:{symbol}")
            for symbol, value in weights.items()
        ),
        12,
    )


def _valid_source_hashes(
    source_hashes: Mapping[str, str],
    *,
    read_model_type: str | None = None,
) -> bool:
    keys = set(source_hashes)
    return (
        keys == _BASE_SOURCE_KEYS
        or keys == _RUNTIME_SOURCE_KEYS
        or keys == _BLOCKED_RUNTIME_SOURCE_KEYS
        or (
            read_model_type == "alerts"
            and keys == _NOTIFICATION_SOURCE_KEYS
        )
        or (
            read_model_type == "reports"
            and keys == _REPORT_SOURCE_KEYS
        )
        or (
            read_model_type == "intelligence"
            and keys == _INTELLIGENCE_SOURCE_KEYS
        )
        or (
            read_model_type == "system"
            and (
                keys == _SYSTEM_HEALTH_SOURCE_KEYS
                or keys == _SYSTEM_RUNTIME_SOURCE_KEYS
                or keys == _SYSTEM_BLOCKED_RUNTIME_SOURCE_KEYS
            )
        )
    ) and all(is_sha256(value) for value in source_hashes.values())


def _iso_after(value: str, seconds: int) -> str:
    return (aware_datetime(value) + timedelta(seconds=seconds)).isoformat()


def _freshness(
    *,
    source_updated_at: str,
    evaluated_at: str,
    stale_after_seconds: int,
    observed_at: str | None = None,
    content_updated_at: str | None = None,
    sources: Mapping[str, str] | None = None,
) -> dict[str, object]:
    observed_at = observed_at or source_updated_at
    content_updated_at = content_updated_at or source_updated_at
    source_times = dict(sources or {"primary": source_updated_at})
    source_states = {
        name: {
            "updated_at": updated_at,
            "stale_at": _iso_after(updated_at, stale_after_seconds),
            "status": (
                "stale"
                if aware_datetime(evaluated_at)
                >= aware_datetime(_iso_after(updated_at, stale_after_seconds))
                else "fresh"
            ),
        }
        for name, updated_at in sorted(source_times.items())
    }
    stale_at = min(
        str(value["stale_at"]) for value in source_states.values()
    )
    status = (
        "stale"
        if any(value["status"] == "stale" for value in source_states.values())
        else "fresh"
    )
    return {
        "status": status,
        "source_updated_at": source_updated_at,
        "observed_at": observed_at,
        "content_updated_at": content_updated_at,
        "evaluated_at": evaluated_at,
        "stale_at": stale_at,
        "sources": source_states,
    }


def _source_errors(
    batch: VerifiedDecisionBatch,
    registry: StrategyRegistry,
) -> tuple[str, ...]:
    errors: list[str] = []
    if not isinstance(batch, VerifiedDecisionBatch):
        return ("dashboard_source_verified_decision_batch_required",)
    if not isinstance(registry, StrategyRegistry):
        return ("dashboard_source_strategy_registry_required",)
    errors.extend(f"manifest:{error}" for error in batch.manifest.validate())
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
        errors.append("dashboard_source_manifest_batch_id_mismatch")
    references = (
        (batch.manifest.market_snapshot, batch.snapshot),
        *zip(batch.manifest.strategy_intents, batch.intents, strict=False),
        (batch.manifest.portfolio_target, batch.target),
        (batch.manifest.risk_decision, batch.risk),
        (batch.manifest.order_plan, batch.plan),
    )
    if len(batch.manifest.strategy_intents) != len(batch.intents):
        errors.append("dashboard_source_intent_reference_count_mismatch")
    for reference, value in references:
        try:
            envelope = artifact_envelope(value)
        except (TypeError, ValueError) as exc:
            errors.append(f"dashboard_source_artifact_invalid:{type(exc).__name__}")
            continue
        for name in ("artifact_type", "object_id", "payload_hash", "artifact_hash"):
            if getattr(reference, name) != envelope[name]:
                errors.append(
                    f"dashboard_source_artifact_reference_mismatch:{reference.file_name}:{name}"
                )
    errors.extend(
        f"registry:{error}" for error in registry.validate()
    )
    errors.extend(
        validate_registered_intents(
            registry,
            batch.intents,
            environment="research",
        )
    )
    return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class DashboardReadModel:
    schema_version: int
    read_model_type: str
    read_model_id: str
    generated_at: str
    data_cutoff: str
    source_hashes: Mapping[str, str]
    stale_after_seconds: int
    freshness: Mapping[str, object]
    payload: Mapping[str, object]
    read_model_hash: str

    @classmethod
    def create(
        cls,
        *,
        read_model_type: str,
        generated_at: str,
        data_cutoff: str,
        source_hashes: Mapping[str, str],
        stale_after_seconds: int,
        freshness: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> DashboardReadModel:
        core = {
            "schema_version": DASHBOARD_SCHEMA_VERSION,
            "read_model_type": read_model_type,
            "generated_at": generated_at,
            "data_cutoff": data_cutoff,
            "source_hashes": dict(source_hashes),
            "stale_after_seconds": stale_after_seconds,
            "freshness": dict(freshness),
            "payload": dict(payload),
        }
        read_model_hash = canonical_hash(core)
        model = cls(
            **core,
            read_model_id=trace_id(
                "dashboard_read_model",
                {
                    "read_model_type": read_model_type,
                    "read_model_hash": read_model_hash,
                },
            ),
            read_model_hash=read_model_hash,
        )
        model.validate()
        return model

    def _core(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "read_model_type": self.read_model_type,
            "generated_at": self.generated_at,
            "data_cutoff": self.data_cutoff,
            "source_hashes": dict(self.source_hashes),
            "stale_after_seconds": self.stale_after_seconds,
            "freshness": dict(self.freshness),
            "payload": dict(self.payload),
        }

    def validate(self) -> None:
        if self.schema_version != DASHBOARD_SCHEMA_VERSION:
            raise DashboardReadModelError("dashboard_schema_version_invalid")
        if self.read_model_type not in READ_MODEL_TYPES:
            raise DashboardReadModelError("dashboard_read_model_type_invalid")
        try:
            generated = aware_datetime(self.generated_at)
            cutoff = aware_datetime(self.data_cutoff)
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError("dashboard_read_model_time_invalid") from exc
        if cutoff > generated:
            raise DashboardReadModelError("dashboard_data_cutoff_after_generation")
        if (
            not isinstance(self.stale_after_seconds, int)
            or isinstance(self.stale_after_seconds, bool)
            or self.stale_after_seconds < 1
        ):
            raise DashboardReadModelError("dashboard_stale_after_invalid")
        if not _valid_source_hashes(
            self.source_hashes, read_model_type=self.read_model_type
        ):
            raise DashboardReadModelError("dashboard_source_hashes_invalid")
        freshness = _mapping(self.freshness, name="dashboard_freshness")
        _exact_keys(
            freshness,
            {
                "status",
                "source_updated_at",
                "observed_at",
                "content_updated_at",
                "evaluated_at",
                "stale_at",
                "sources",
            },
            name="dashboard_freshness",
        )
        if freshness["status"] not in {"fresh", "stale"}:
            raise DashboardReadModelError("dashboard_freshness_status_invalid")
        try:
            source_updated = aware_datetime(str(freshness["source_updated_at"]))
            observed = aware_datetime(str(freshness["observed_at"]))
            content_updated = aware_datetime(
                str(freshness["content_updated_at"])
            )
            evaluated = aware_datetime(str(freshness["evaluated_at"]))
            stale_at = aware_datetime(str(freshness["stale_at"]))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError("dashboard_freshness_time_invalid") from exc
        if (
            generated > evaluated
            or observed > generated
            or source_updated > observed
            or content_updated > observed
        ):
            raise DashboardReadModelError("dashboard_freshness_time_order_invalid")
        source_rows = _mapping(
            freshness["sources"], name="dashboard_freshness_sources"
        )
        if not source_rows:
            raise DashboardReadModelError("dashboard_freshness_sources_invalid")
        normalized_rows: dict[str, Mapping[str, object]] = {}
        for name, raw in source_rows.items():
            if not isinstance(name, str) or not name:
                raise DashboardReadModelError(
                    "dashboard_freshness_source_name_invalid"
                )
            row = _mapping(raw, name="dashboard_freshness_source")
            _exact_keys(
                row,
                {"updated_at", "stale_at", "status"},
                name="dashboard_freshness_source",
            )
            try:
                updated = aware_datetime(str(row["updated_at"]))
                row_stale_at = aware_datetime(str(row["stale_at"]))
            except (AttributeError, TypeError, ValueError) as exc:
                raise DashboardReadModelError(
                    "dashboard_freshness_source_time_invalid"
                ) from exc
            if updated > observed or row_stale_at != updated + timedelta(
                seconds=self.stale_after_seconds
            ):
                raise DashboardReadModelError(
                    "dashboard_freshness_source_time_invalid"
                )
            expected_row_status = (
                "stale" if evaluated >= row_stale_at else "fresh"
            )
            if row["status"] != expected_row_status:
                raise DashboardReadModelError(
                    "dashboard_freshness_source_status_invalid"
                )
            normalized_rows[name] = row
        expected_stale_at = min(
            aware_datetime(str(row["stale_at"]))
            for row in normalized_rows.values()
        )
        if stale_at != expected_stale_at:
            raise DashboardReadModelError("dashboard_stale_at_invalid")
        expected_status = (
            "stale"
            if any(row["status"] == "stale" for row in normalized_rows.values())
            else "fresh"
        )
        if freshness["status"] != expected_status:
            raise DashboardReadModelError("dashboard_freshness_status_mismatch")
        _validate_payload(self.read_model_type, self.payload)
        authority = _mapping(self.payload["authority"], name="dashboard_authority")
        if self.read_model_type == "alerts":
            notification_authoritative = (
                authority["notifications"] == "notification_store"
            )
            if notification_authoritative is not (
                "notification_store" in self.source_hashes
            ):
                raise DashboardReadModelError(
                    "dashboard_notification_authority_source_mismatch"
                )
        elif self.read_model_type == "reports":
            report_authoritative = authority["reports"] == "deterministic_daily_brief"
            if report_authoritative is not ("daily_brief" in self.source_hashes):
                raise DashboardReadModelError(
                    "dashboard_report_authority_source_mismatch"
                )
        elif self.read_model_type == "intelligence":
            intelligence_authoritative = (
                authority["intelligence"] == "daily_intelligence"
            )
            if intelligence_authoritative is not (
                "daily_intelligence" in self.source_hashes
            ):
                raise DashboardReadModelError(
                    "dashboard_intelligence_authority_source_mismatch"
                )
        else:
            runtime_authoritative = authority["account_and_pnl"] == "runtime_ledger"
            if runtime_authoritative is not (
                "runtime_ledger" in self.source_hashes
            ):
                raise DashboardReadModelError(
                    "dashboard_runtime_authority_source_mismatch"
                )
            if self.read_model_type == "system":
                health = _mapping(
                    self.payload["health"], name="dashboard_system_health"
                )
                health_authoritative = health["status"] == "available"
                if health_authoritative is not (
                    "system_health" in self.source_hashes
                ):
                    raise DashboardReadModelError(
                        "dashboard_system_health_source_mismatch"
                    )
        if self.read_model_type == "overview":
            latest_batch = _mapping(
                self.payload["latest_batch"], name="dashboard_latest_batch"
            )
            if latest_batch["data_cutoff"] != self.data_cutoff:
                raise DashboardReadModelError(
                    "dashboard_latest_batch_data_cutoff_mismatch"
                )
        if self.read_model_type == "readiness":
            blocked_observation = "blocked_runtime_observation" in self.source_hashes
            if self.freshness["status"] == "stale":
                expected_readiness = "stale"
            elif blocked_observation:
                expected_readiness = "read_only_observation_ready"
            elif not runtime_authoritative:
                expected_readiness = "blocked_phase_b_required"
            else:
                gates = {
                    gate["gate"]: gate["status"]
                    for gate in self.payload["gates"]
                }
                expected_readiness = (
                    "read_model_ready"
                    if gates["runtime_ledger"] == "pass"
                    and gates["order_state_recovery"] == "pass"
                    and gates["three_way_reconciliation"] == "pass"
                    else "blocked_runtime_state"
                )
            if self.payload["status"] != expected_readiness:
                raise DashboardReadModelError(
                    "dashboard_readiness_freshness_mismatch"
                )
        expected_hash = canonical_hash(self._core())
        if self.read_model_hash != expected_hash:
            raise DashboardReadModelError("dashboard_read_model_hash_invalid")
        expected_id = trace_id(
            "dashboard_read_model",
            {
                "read_model_type": self.read_model_type,
                "read_model_hash": expected_hash,
            },
        )
        if self.read_model_id != expected_id:
            raise DashboardReadModelError("dashboard_read_model_id_invalid")

    def as_dict(self) -> dict[str, object]:
        return self._core() | {
            "read_model_id": self.read_model_id,
            "read_model_hash": self.read_model_hash,
        }


def _validate_payload(read_model_type: str, payload: Mapping[str, object]) -> None:
    value = _mapping(payload, name=f"dashboard_{read_model_type}_payload")
    expected = {
        "overview": {
            "authority",
            "latest_batch",
            "account",
            "portfolio",
            "risk",
            "pnl",
        },
        "positions": {"authority", "summary", "positions"},
        "orders": {"authority", "summary", "orders", "fills"},
        "strategies": {"authority", "strategies"},
        "decisions": {
            "authority",
            "batch",
            "strategies",
            "portfolio",
            "risk",
            "order_plan",
            "trace",
        },
        "risk": {"authority", "decision", "runtime"},
        "readiness": {"authority", "status", "axes", "gates", "strategies"},
        "system": {"authority", "summary", "ledger", "health"},
        "alerts": {"authority", "summary", "alerts"},
        "reports": {"authority", "summary", "brief"},
        "intelligence": {"authority", "summary", "report"},
    }[read_model_type]
    _exact_keys(value, expected, name=f"dashboard_{read_model_type}_payload")
    if read_model_type == "alerts":
        _validate_alerts_payload(value)
        return
    if read_model_type == "reports":
        _validate_reports_payload(value)
        return
    if read_model_type == "intelligence":
        _validate_intelligence_payload(value)
        return
    authority = _mapping(value["authority"], name="dashboard_authority")
    _exact_keys(
        authority,
        {"decision", "governance", "account_and_pnl"},
        name="dashboard_authority",
    )
    if authority.get("decision") != "verified_decision_batch" or authority.get(
        "governance"
    ) != "strategy_registry" or authority.get("account_and_pnl") not in {
        "unavailable_until_phase_b_ledger",
        "runtime_ledger",
        "private_account_preflight",
    }:
        raise DashboardReadModelError("dashboard_authority_invalid")
    if read_model_type == "orders":
        _validate_orders_payload(value)
    elif read_model_type == "positions":
        _validate_positions_payload(value)
    elif read_model_type == "decisions":
        _validate_decisions_payload(value)
    elif read_model_type == "risk":
        _validate_risk_payload(value)
    elif read_model_type == "system":
        _validate_system_payload(value)
    elif read_model_type == "overview":
        latest_batch = _mapping(
            value["latest_batch"], name="dashboard_latest_batch"
        )
        _exact_keys(
            latest_batch,
            {
                "batch_id",
                "manifest_id",
                "manifest_hash",
                "snapshot_id",
                "decision_time",
                "data_cutoff",
                "complete",
                "decision_count",
            },
            name="dashboard_latest_batch",
        )
        for name in ("batch_id", "manifest_id", "manifest_hash", "snapshot_id"):
            if not is_sha256(latest_batch[name]):
                raise DashboardReadModelError(
                    f"dashboard_latest_batch_{name}_invalid"
                )
        try:
            aware_datetime(str(latest_batch["decision_time"]))
            aware_datetime(str(latest_batch["data_cutoff"]))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError(
                "dashboard_latest_batch_time_invalid"
            ) from exc
        if latest_batch["complete"] is not True:
            raise DashboardReadModelError("dashboard_latest_batch_not_complete")
        if (
            not isinstance(latest_batch["decision_count"], int)
            or isinstance(latest_batch["decision_count"], bool)
            or latest_batch["decision_count"] < 1
        ):
            raise DashboardReadModelError(
                "dashboard_latest_batch_decision_count_invalid"
            )

        portfolio = _mapping(value["portfolio"], name="dashboard_portfolio")
        _exact_keys(
            portfolio,
            {
                "portfolio_target_id",
                "approved_target",
                "approved_target_gross",
                "actual_positions",
                "planned_order_count",
                "planned_cancellation_count",
                "plan_executable",
            },
            name="dashboard_portfolio",
        )
        if not is_sha256(portfolio["portfolio_target_id"]):
            raise DashboardReadModelError("dashboard_portfolio_target_id_invalid")
        approved_target = _mapping(
            portfolio["approved_target"], name="dashboard_approved_target"
        )
        approved_gross = _gross(approved_target)
        if not math.isclose(
            _finite_nonnegative(
                portfolio["approved_target_gross"],
                name="dashboard_approved_target_gross",
            ),
            approved_gross,
            abs_tol=1e-12,
            rel_tol=0.0,
        ):
            raise DashboardReadModelError(
                "dashboard_approved_target_gross_mismatch"
            )
        if approved_gross > 1.0 + 1e-12:
            raise DashboardReadModelError("dashboard_approved_target_gross_invalid")
        if authority["account_and_pnl"] == "private_account_preflight":
            actual_positions = _validate_readonly_account_value(
                portfolio["actual_positions"],
                name="dashboard_actual_positions",
                value_kind="positions",
            )
        else:
            actual_positions = _validate_ledger_value(
                portfolio["actual_positions"],
                name="dashboard_actual_positions",
                value_kind="positions",
            )
        for name in ("planned_order_count", "planned_cancellation_count"):
            if (
                not isinstance(portfolio[name], int)
                or isinstance(portfolio[name], bool)
                or portfolio[name] < 0
            ):
                raise DashboardReadModelError(f"dashboard_{name}_invalid")
        if not isinstance(portfolio["plan_executable"], bool):
            raise DashboardReadModelError("dashboard_plan_executable_invalid")

        risk = _mapping(value["risk"], name="dashboard_risk")
        _exact_keys(
            risk,
            {
                "risk_decision_id",
                "approved",
                "increase_risk_allowed",
                "reduce_risk_allowed",
                "adjustments",
                "violations",
                "blockers",
            },
            name="dashboard_risk",
        )
        if not is_sha256(risk["risk_decision_id"]):
            raise DashboardReadModelError("dashboard_risk_decision_id_invalid")
        for name in ("approved", "increase_risk_allowed", "reduce_risk_allowed"):
            if not isinstance(risk[name], bool):
                raise DashboardReadModelError(f"dashboard_risk_{name}_invalid")
        for name in ("adjustments", "violations", "blockers"):
            rows = risk[name]
            if (
                not isinstance(rows, list)
                or any(not isinstance(row, str) or not row for row in rows)
                or len(rows) != len(set(rows))
            ):
                raise DashboardReadModelError(f"dashboard_risk_{name}_invalid")

        pnl = _validate_ledger_value(
            value["pnl"], name="dashboard_overview_pnl", value_kind="pnl"
        )
        if authority["account_and_pnl"] == "private_account_preflight":
            account = _validate_readonly_account_value(
                value["account"],
                name="dashboard_overview_account",
                value_kind="account",
            )
        else:
            account = _validate_ledger_value(
                value["account"],
                name="dashboard_overview_account",
                value_kind="account",
            )
        runtime_authoritative = authority["account_and_pnl"] == "runtime_ledger"
        readonly_authoritative = authority["account_and_pnl"] == "private_account_preflight"
        if runtime_authoritative is not (
            actual_positions["status"] == "available"
            and pnl["status"] == "available"
            and account["status"] == "available"
        ):
            raise DashboardReadModelError(
                "dashboard_overview_ledger_availability_mismatch"
            )
        if readonly_authoritative is not (
            actual_positions["status"] == "available_readonly"
            and pnl["status"] == "unavailable_until_phase_b_ledger"
            and account["status"] == "available_readonly"
        ):
            raise DashboardReadModelError(
                "dashboard_overview_readonly_account_availability_mismatch"
            )
    elif read_model_type == "strategies":
        rows = value["strategies"]
        if not isinstance(rows, list):
            raise DashboardReadModelError("dashboard_strategies_invalid")
        strategy_ids: list[str] = []
        for index, row_value in enumerate(rows):
            row = _mapping(
                row_value, name=f"dashboard_strategy:{index}"
            )
            _exact_keys(
                row,
                {
                    "strategy_id",
                    "strategy_version",
                    "strategy_kind",
                    "promotion_status",
                    "registry_entry_id",
                    "strategy_contract_hash",
                    "maximum_gross",
                    "maximum_stress_loss_fraction",
                    "promotion_evidence_present",
                    "owner_authorization_present",
                    "latest_decision",
                    "nav",
                },
                name=f"dashboard_strategy:{index}",
            )
            if not isinstance(row["strategy_id"], str) or not row["strategy_id"]:
                raise DashboardReadModelError("dashboard_strategy_id_invalid")
            strategy_ids.append(row["strategy_id"])
            if not isinstance(row["strategy_version"], str) or not row[
                "strategy_version"
            ]:
                raise DashboardReadModelError("dashboard_strategy_version_invalid")
            if row["strategy_kind"] not in {"continuous", "event", "filter"}:
                raise DashboardReadModelError("dashboard_strategy_kind_invalid")
            if row["promotion_status"] not in {
                "draft",
                "research",
                "frozen_candidate",
                "shadow",
                "paper",
                "minimal_live",
                "scaled_live",
                "halted",
            }:
                raise DashboardReadModelError("dashboard_strategy_status_invalid")
            for name in ("registry_entry_id", "strategy_contract_hash"):
                if not is_sha256(row[name]):
                    raise DashboardReadModelError(f"dashboard_strategy_{name}_invalid")
            for name in ("maximum_gross", "maximum_stress_loss_fraction"):
                number = _finite_nonnegative(
                    row[name], name=f"dashboard_strategy_{name}"
                )
                if number > 1.0 + 1e-12:
                    raise DashboardReadModelError(
                        f"dashboard_strategy_{name}_invalid"
                    )
            for name in (
                "promotion_evidence_present",
                "owner_authorization_present",
            ):
                if not isinstance(row[name], bool):
                    raise DashboardReadModelError(
                        f"dashboard_strategy_{name}_invalid"
                    )
            nav = _validate_ledger_value(
                row["nav"],
                name=f"dashboard_strategy_nav:{index}",
                value_kind="strategy_nav",
            )
            if (authority["account_and_pnl"] == "runtime_ledger") is not (
                nav["status"] == "available"
            ):
                raise DashboardReadModelError(
                    "dashboard_strategy_nav_availability_mismatch"
                )
            decision = row["latest_decision"]
            if decision is not None:
                _validate_strategy_decision(decision, index=index)
        if strategy_ids != sorted(strategy_ids) or len(strategy_ids) != len(
            set(strategy_ids)
        ):
            raise DashboardReadModelError(
                "dashboard_strategies_order_or_identity_invalid"
            )
    elif read_model_type == "readiness":
        if value["status"] not in {
            "blocked_phase_b_required",
            "blocked_runtime_state",
            "read_only_observation_ready",
            "read_model_ready",
            "stale",
        }:
            raise DashboardReadModelError("dashboard_readiness_status_invalid")
        gates = value["gates"]
        strategies = value["strategies"]
        axes = _mapping(value["axes"], name="dashboard_readiness_axes")
        expected_axes = {
            "publication_integrity",
            "observation_state",
            "operational_state",
            "trading_authority",
            "evidence_state",
        }
        if set(axes) != expected_axes:
            raise DashboardReadModelError("dashboard_readiness_axes_invalid")
        allowed_axis_statuses = {
            "pass",
            "fresh",
            "stale",
            "healthy",
            "degraded",
            "unavailable",
            "registry_authorized",
            "disarmed",
            "blocked",
            "complete",
            "incomplete",
        }
        for name, axis_value in axes.items():
            axis = _mapping(axis_value, name=f"dashboard_readiness_axis:{name}")
            _exact_keys(
                axis,
                {"status", "detail", "impact_scopes"},
                name=f"dashboard_readiness_axis:{name}",
            )
            if (
                axis["status"] not in allowed_axis_statuses
                or not isinstance(axis["detail"], str)
                or not axis["detail"]
                or not isinstance(axis["impact_scopes"], list)
                or not axis["impact_scopes"]
                or any(
                    scope
                    not in {"execution", "observation", "intelligence", "delivery"}
                    for scope in axis["impact_scopes"]
                )
            ):
                raise DashboardReadModelError(
                    "dashboard_readiness_axis_invalid"
                )
        if not isinstance(gates, list) or not isinstance(strategies, list):
            raise DashboardReadModelError("dashboard_readiness_rows_invalid")
        expected_gates = {
            "verified_decision_batch",
            "strategy_registry",
            "runtime_ledger",
            "order_state_recovery",
            "three_way_reconciliation",
            "live_orders_allowed",
        }
        gate_names: list[str] = []
        for index, gate_value in enumerate(gates):
            gate = _mapping(gate_value, name=f"dashboard_gate:{index}")
            _exact_keys(
                gate,
                {"gate", "status", "detail"},
                name=f"dashboard_gate:{index}",
            )
            if (
                not isinstance(gate["gate"], str)
                or not isinstance(gate["detail"], str)
                or not gate["detail"]
                or gate["status"] not in {"pass", "block", "unavailable"}
            ):
                raise DashboardReadModelError("dashboard_gate_invalid")
            gate_names.append(gate["gate"])
        if set(gate_names) != expected_gates or len(gate_names) != len(
            set(gate_names)
        ):
            raise DashboardReadModelError("dashboard_gate_set_invalid")
        gates_by_name = {gate["gate"]: gate for gate in gates}
        if gates_by_name["verified_decision_batch"]["status"] != "pass" or gates_by_name[
            "strategy_registry"
        ]["status"] != "pass" or gates_by_name["live_orders_allowed"][
            "status"
        ] != "block":
            raise DashboardReadModelError("dashboard_gate_fixed_status_invalid")
        if authority["account_and_pnl"] == "runtime_ledger":
            if gates_by_name["runtime_ledger"]["status"] != "pass" or any(
                gates_by_name[name]["status"] not in {"pass", "block"}
                for name in ("order_state_recovery", "three_way_reconciliation")
            ):
                raise DashboardReadModelError("dashboard_runtime_gate_status_invalid")
        elif any(
            gates_by_name[name]["status"] != "unavailable"
            for name in (
                "runtime_ledger",
                "order_state_recovery",
                "three_way_reconciliation",
            )
        ):
            raise DashboardReadModelError("dashboard_unavailable_gate_status_invalid")
        for index, row_value in enumerate(strategies):
            row = _mapping(
                row_value, name=f"dashboard_readiness_strategy:{index}"
            )
            _exact_keys(
                row,
                {
                    "strategy_id",
                    "strategy_version",
                    "promotion_status",
                    "current_batch_decision_present",
                    "promotion_evidence_present",
                    "owner_authorization_present",
                    "live_orders_allowed",
                    "execution_blockers",
                },
                name=f"dashboard_readiness_strategy:{index}",
            )
            if row["live_orders_allowed"] is not False:
                raise DashboardReadModelError(
                    "dashboard_readiness_cannot_authorize_orders"
                )
            if (
                not isinstance(row["execution_blockers"], list)
                or any(
                    not isinstance(value, str) or not value
                    for value in row["execution_blockers"]
                )
                or len(row["execution_blockers"])
                != len(set(row["execution_blockers"]))
            ):
                raise DashboardReadModelError(
                    "dashboard_readiness_execution_blockers_invalid"
                )
            for name in (
                "current_batch_decision_present",
                "promotion_evidence_present",
                "owner_authorization_present",
            ):
                if not isinstance(row[name], bool):
                    raise DashboardReadModelError(
                        f"dashboard_readiness_{name}_invalid"
                    )


def _validate_runtime_wrapper(value: object, *, name: str) -> Mapping[str, Any]:
    row = _mapping(value, name=name)
    _exact_keys(row, {"status", "source", "values"}, name=name)
    if row["source"] != "runtime_ledger":
        raise DashboardReadModelError(f"{name}_source_invalid")
    if row["status"] == "unavailable_until_phase_b_ledger":
        if row["values"] is not None:
            raise DashboardReadModelError(f"{name}_unavailable_values_present")
        return row
    if row["status"] != "available" or not isinstance(row["values"], Mapping):
        raise DashboardReadModelError(f"{name}_invalid")
    return row


def _count(value: object, *, name: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise DashboardReadModelError(f"{name}_invalid")
    return value


def _string_list(value: object, *, name: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise DashboardReadModelError(f"{name}_invalid")
    return value


def _trace_href(identifier: str) -> str:
    return f"#/decisions?trace={identifier}"


def _validate_positions_payload(value: Mapping[str, object]) -> None:
    summary = _mapping(value["summary"], name="dashboard_positions_summary")
    _exact_keys(
        summary,
        {
            "status",
            "position_count",
            "nonzero_position_count",
            "reconciliation_id",
            "reconciled",
        },
        name="dashboard_positions_summary",
    )
    rows = value["positions"]
    if not isinstance(rows, list):
        raise DashboardReadModelError("dashboard_positions_invalid")
    runtime = value["authority"]["account_and_pnl"] == "runtime_ledger"
    if not runtime:
        if summary != {
            "status": "unavailable_until_phase_b_ledger",
            "position_count": 0,
            "nonzero_position_count": 0,
            "reconciliation_id": None,
            "reconciled": False,
        } or rows:
            raise DashboardReadModelError("dashboard_positions_unavailable_invalid")
        return
    if summary["status"] != "available":
        raise DashboardReadModelError("dashboard_positions_status_invalid")
    for field in ("position_count", "nonzero_position_count"):
        _count(summary[field], name=f"dashboard_positions_{field}")
    if not is_sha256(summary["reconciliation_id"]) or not isinstance(
        summary["reconciled"], bool
    ):
        raise DashboardReadModelError("dashboard_positions_reconciliation_invalid")
    symbols: list[str] = []
    nonzero = 0
    for index, row_value in enumerate(rows):
        row = _mapping(row_value, name=f"dashboard_position:{index}")
        _exact_keys(
            row,
            {
                "symbol",
                "actual_quantity",
                "average_cost",
                "realized_trading_pnl",
                "expected_quantity",
                "quantity_difference",
                "approved_target_weight",
                "updated_at",
                "source_hash",
                "position_hash",
                "trace",
            },
            name=f"dashboard_position:{index}",
        )
        symbol = row["symbol"]
        if not isinstance(symbol, str) or not symbol:
            raise DashboardReadModelError("dashboard_position_symbol_invalid")
        symbols.append(symbol)
        actual = _finite_nonnegative(
            row["actual_quantity"], name=f"dashboard_position_actual:{symbol}"
        )
        expected = _finite_nonnegative(
            row["expected_quantity"], name=f"dashboard_position_expected:{symbol}"
        )
        _finite_nonnegative(
            row["approved_target_weight"],
            name=f"dashboard_position_target_weight:{symbol}",
        )
        _finite(row["realized_trading_pnl"], name=f"dashboard_position_pnl:{symbol}")
        _finite_nonnegative(row["average_cost"], name=f"dashboard_position_cost:{symbol}")
        if not math.isclose(
            _finite(row["quantity_difference"], name=f"dashboard_position_difference:{symbol}"),
            actual - expected,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise DashboardReadModelError("dashboard_position_difference_mismatch")
        if actual > 0.0:
            nonzero += 1
        fact_fields = ("updated_at", "source_hash", "position_hash")
        if any(row[field] is None for field in fact_fields):
            if not all(row[field] is None for field in fact_fields) or actual != 0.0:
                raise DashboardReadModelError("dashboard_position_fact_invalid")
        else:
            try:
                aware_datetime(str(row["updated_at"]))
            except (AttributeError, TypeError, ValueError) as exc:
                raise DashboardReadModelError("dashboard_position_time_invalid") from exc
            if not is_sha256(row["source_hash"]) or not is_sha256(row["position_hash"]):
                raise DashboardReadModelError("dashboard_position_hash_invalid")
        trace = _mapping(row["trace"], name=f"dashboard_position_trace:{symbol}")
        _exact_keys(
            trace,
            {
                "batch_id",
                "manifest_hash",
                "snapshot_id",
                "decision_ids",
                "portfolio_target_id",
                "risk_decision_id",
                "order_plan_id",
                "href",
            },
            name=f"dashboard_position_trace:{symbol}",
        )
        for field in (
            "batch_id",
            "manifest_hash",
            "snapshot_id",
            "portfolio_target_id",
            "risk_decision_id",
            "order_plan_id",
        ):
            if not is_sha256(trace[field]):
                raise DashboardReadModelError("dashboard_position_trace_invalid")
        decisions = _string_list(
            trace["decision_ids"], name="dashboard_position_trace_decisions"
        )
        if any(not is_sha256(identifier) for identifier in decisions):
            raise DashboardReadModelError("dashboard_position_trace_decision_invalid")
        selected = decisions[0] if decisions else trace["batch_id"]
        if trace["href"] != _trace_href(selected):
            raise DashboardReadModelError("dashboard_position_trace_href_invalid")
    if symbols != sorted(symbols) or len(symbols) != len(set(symbols)):
        raise DashboardReadModelError("dashboard_positions_order_invalid")
    if summary["position_count"] != len(rows) or summary[
        "nonzero_position_count"
    ] != nonzero:
        raise DashboardReadModelError("dashboard_positions_summary_mismatch")


def _validate_decisions_payload(value: Mapping[str, object]) -> None:
    batch = _mapping(value["batch"], name="dashboard_decisions_batch")
    _exact_keys(
        batch,
        {
            "batch_id",
            "manifest_id",
            "manifest_hash",
            "snapshot_id",
            "created_at",
            "orders_authorized",
            "href",
        },
        name="dashboard_decisions_batch",
    )
    for field in ("batch_id", "manifest_id", "manifest_hash", "snapshot_id"):
        if not is_sha256(batch[field]):
            raise DashboardReadModelError("dashboard_decisions_batch_hash_invalid")
    try:
        aware_datetime(str(batch["created_at"]))
    except (AttributeError, TypeError, ValueError) as exc:
        raise DashboardReadModelError("dashboard_decisions_batch_time_invalid") from exc
    if batch["orders_authorized"] is not False or batch["href"] != _trace_href(
        batch["batch_id"]
    ):
        raise DashboardReadModelError("dashboard_decisions_batch_invalid")
    strategies = value["strategies"]
    if not isinstance(strategies, list) or not strategies:
        raise DashboardReadModelError("dashboard_decisions_strategies_invalid")
    strategy_keys: list[tuple[str, str]] = []
    decision_ids: list[str] = []
    for index, row_value in enumerate(strategies):
        row = _mapping(row_value, name=f"dashboard_decision_strategy:{index}")
        _exact_keys(
            row,
            {
                "strategy_id",
                "strategy_version",
                "decision_id",
                "intent_hash",
                "decision_time",
                "reason_codes",
                "target_weights",
                "target_stress_loss_fraction",
                "href",
            },
            name=f"dashboard_decision_strategy:{index}",
        )
        if not all(
            isinstance(row[field], str) and row[field]
            for field in ("strategy_id", "strategy_version")
        ) or not is_sha256(row["decision_id"]) or not is_sha256(row["intent_hash"]):
            raise DashboardReadModelError("dashboard_decision_strategy_invalid")
        try:
            aware_datetime(str(row["decision_time"]))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError("dashboard_decision_strategy_time_invalid") from exc
        _string_list(row["reason_codes"], name="dashboard_decision_reason_codes")
        _mapping(row["target_weights"], name="dashboard_decision_target_weights")
        _gross(row["target_weights"])
        _finite_nonnegative(
            row["target_stress_loss_fraction"],
            name="dashboard_decision_stress_loss",
        )
        if row["href"] != _trace_href(row["decision_id"]):
            raise DashboardReadModelError("dashboard_decision_strategy_href_invalid")
        strategy_keys.append((row["strategy_id"], row["decision_id"]))
        decision_ids.append(row["decision_id"])
    if strategy_keys != sorted(strategy_keys) or len(decision_ids) != len(set(decision_ids)):
        raise DashboardReadModelError("dashboard_decision_strategy_order_invalid")

    portfolio = _mapping(value["portfolio"], name="dashboard_decisions_portfolio")
    _exact_keys(
        portfolio,
        {
            "portfolio_target_id",
            "target_hash",
            "decision_ids",
            "target_weights",
            "approved_target",
            "sleeve_contributions",
            "href",
        },
        name="dashboard_decisions_portfolio",
    )
    risk = _mapping(value["risk"], name="dashboard_decisions_risk")
    _exact_keys(
        risk,
        {
            "risk_decision_id",
            "decision_hash",
            "portfolio_target_id",
            "approved",
            "increase_risk_allowed",
            "reduce_risk_allowed",
            "adjustments",
            "violations",
            "href",
        },
        name="dashboard_decisions_risk",
    )
    plan = _mapping(value["order_plan"], name="dashboard_decisions_order_plan")
    _exact_keys(
        plan,
        {
            "order_plan_id",
            "plan_hash",
            "risk_decision_id",
            "executable",
            "blockers",
            "order_ids",
            "cancellation_ids",
            "href",
        },
        name="dashboard_decisions_order_plan",
    )
    for field, row in (
        ("portfolio_target_id", portfolio),
        ("target_hash", portfolio),
        ("risk_decision_id", risk),
        ("decision_hash", risk),
        ("portfolio_target_id", risk),
        ("order_plan_id", plan),
        ("plan_hash", plan),
        ("risk_decision_id", plan),
    ):
        if not is_sha256(row[field]):
            raise DashboardReadModelError("dashboard_decisions_artifact_hash_invalid")
    if portfolio["decision_ids"] != decision_ids:
        raise DashboardReadModelError("dashboard_decisions_portfolio_decisions_mismatch")
    _gross(_mapping(portfolio["target_weights"], name="dashboard_decisions_target"))
    _gross(_mapping(portfolio["approved_target"], name="dashboard_decisions_approved"))
    _mapping(portfolio["sleeve_contributions"], name="dashboard_decisions_sleeves")
    if portfolio["href"] != _trace_href(portfolio["portfolio_target_id"]):
        raise DashboardReadModelError("dashboard_decisions_portfolio_href_invalid")
    if risk["portfolio_target_id"] != portfolio["portfolio_target_id"]:
        raise DashboardReadModelError("dashboard_decisions_risk_target_mismatch")
    for field in ("approved", "increase_risk_allowed", "reduce_risk_allowed"):
        if not isinstance(risk[field], bool):
            raise DashboardReadModelError("dashboard_decisions_risk_invalid")
    _string_list(risk["adjustments"], name="dashboard_decisions_adjustments")
    _string_list(risk["violations"], name="dashboard_decisions_violations")
    if risk["href"] != _trace_href(risk["risk_decision_id"]):
        raise DashboardReadModelError("dashboard_decisions_risk_href_invalid")
    if plan["risk_decision_id"] != risk["risk_decision_id"] or not isinstance(
        plan["executable"], bool
    ):
        raise DashboardReadModelError("dashboard_decisions_plan_invalid")
    _string_list(plan["blockers"], name="dashboard_decisions_plan_blockers")
    for field in ("order_ids", "cancellation_ids"):
        identifiers = _string_list(plan[field], name=f"dashboard_decisions_{field}")
        if identifiers != sorted(identifiers):
            raise DashboardReadModelError("dashboard_decisions_plan_order_invalid")
    if plan["href"] != _trace_href(plan["order_plan_id"]):
        raise DashboardReadModelError("dashboard_decisions_plan_href_invalid")

    trace = _mapping(value["trace"], name="dashboard_decisions_trace")
    _exact_keys(trace, {"nodes", "edges"}, name="dashboard_decisions_trace")
    if not isinstance(trace["nodes"], list) or not isinstance(trace["edges"], list):
        raise DashboardReadModelError("dashboard_decisions_trace_invalid")
    node_ids: list[str] = []
    for node_value in trace["nodes"]:
        node = _mapping(node_value, name="dashboard_decisions_trace_node")
        _exact_keys(
            node,
            {"id", "type", "label", "integrity_hash", "href"},
            name="dashboard_decisions_trace_node",
        )
        if (
            not is_sha256(node["id"])
            or not is_sha256(node["integrity_hash"])
            or not isinstance(node["type"], str)
            or not node["type"]
            or not isinstance(node["label"], str)
            or not node["label"]
            or node["href"] != _trace_href(node["id"])
        ):
            raise DashboardReadModelError("dashboard_decisions_trace_node_invalid")
        node_ids.append(node["id"])
    if len(node_ids) != len(set(node_ids)):
        raise DashboardReadModelError("dashboard_decisions_trace_node_duplicate")
    edge_keys: list[tuple[str, str, str]] = []
    for edge_value in trace["edges"]:
        edge = _mapping(edge_value, name="dashboard_decisions_trace_edge")
        _exact_keys(
            edge, {"from", "to", "relation"}, name="dashboard_decisions_trace_edge"
        )
        if (
            edge["from"] not in node_ids
            or edge["to"] not in node_ids
            or not isinstance(edge["relation"], str)
            or not edge["relation"]
        ):
            raise DashboardReadModelError("dashboard_decisions_trace_edge_invalid")
        edge_keys.append((edge["from"], edge["to"], edge["relation"]))
    if len(edge_keys) != len(set(edge_keys)):
        raise DashboardReadModelError("dashboard_decisions_trace_edge_duplicate")
    required_nodes = {
        batch["batch_id"],
        batch["snapshot_id"],
        *decision_ids,
        portfolio["portfolio_target_id"],
        risk["risk_decision_id"],
        plan["order_plan_id"],
    }
    if not required_nodes.issubset(node_ids):
        raise DashboardReadModelError("dashboard_decisions_trace_incomplete")


def _validate_orders_payload(value: Mapping[str, object]) -> None:
    summary = _mapping(value["summary"], name="dashboard_orders_summary")
    summary_fields = {
        "status",
        "total_order_count",
        "open_order_count",
        "unresolved_order_count",
        "partial_fill_count",
        "rejected_count",
        "protective_order_count",
        "fill_count",
        "fill_quantity",
        "fill_notional",
        "fill_fees_by_asset",
        "latest_recovery_status",
        "unavailable_fields",
    }
    _exact_keys(summary, summary_fields, name="dashboard_orders_summary")
    rows = value["orders"]
    fills = value["fills"]
    if not isinstance(rows, list) or not isinstance(fills, list):
        raise DashboardReadModelError("dashboard_orders_rows_invalid")
    runtime = value["authority"]["account_and_pnl"] == "runtime_ledger"
    if not runtime:
        expected = {field: None for field in summary_fields}
        expected["status"] = "unavailable_until_phase_b_ledger"
        expected["unavailable_fields"] = ["order_latency", "slippage"]
        if summary != expected or rows or fills:
            raise DashboardReadModelError("dashboard_orders_unavailable_invalid")
        return
    if summary["status"] != "available":
        raise DashboardReadModelError("dashboard_orders_status_invalid")
    for field in (
        "total_order_count",
        "open_order_count",
        "unresolved_order_count",
        "partial_fill_count",
        "rejected_count",
        "protective_order_count",
        "fill_count",
    ):
        _count(summary[field], name=f"dashboard_orders_{field}")
    _finite_nonnegative(summary["fill_quantity"], name="dashboard_orders_fill_quantity")
    _finite_nonnegative(summary["fill_notional"], name="dashboard_orders_fill_notional")
    fees = _mapping(summary["fill_fees_by_asset"], name="dashboard_orders_fees")
    for asset, amount in fees.items():
        if not isinstance(asset, str) or not asset:
            raise DashboardReadModelError("dashboard_orders_fee_asset_invalid")
        _finite_nonnegative(amount, name=f"dashboard_orders_fee:{asset}")
    if summary["latest_recovery_status"] not in {"none", "passed", "blocked"}:
        raise DashboardReadModelError("dashboard_orders_recovery_status_invalid")
    if _string_list(
        summary["unavailable_fields"], name="dashboard_orders_unavailable_fields"
    ) != ["order_latency", "slippage"]:
        raise DashboardReadModelError("dashboard_orders_unavailable_fields_invalid")
    expected_fields = {
        "client_order_id",
        "batch_id",
        "symbol",
        "side",
        "phase",
        "order_type",
        "status",
        "planned_quantity",
        "executed_quantity",
        "remaining_quantity",
        "fill_count",
        "fill_quantity",
        "fill_notional",
        "fill_fees_by_asset",
        "exchange_order_id",
        "average_price",
        "reduce_only",
        "close_position",
        "limit_price",
        "stop_price",
        "last_transition_at",
        "latest_reason",
        "plan_spec_hash",
        "last_observation_hash",
    }
    ids: list[str] = []
    observed_fill_count = 0
    observed_fill_quantity = 0.0
    observed_fill_notional = 0.0
    observed_fees: dict[str, float] = {}
    for index, row_value in enumerate(rows):
        row = _mapping(row_value, name=f"dashboard_order:{index}")
        _exact_keys(row, expected_fields, name=f"dashboard_order:{index}")
        for field in ("client_order_id", "symbol", "order_type"):
            if not isinstance(row[field], str) or not row[field]:
                raise DashboardReadModelError(f"dashboard_order_{field}_invalid")
        ids.append(str(row["client_order_id"]))
        for field in ("batch_id", "plan_spec_hash", "last_observation_hash"):
            if not is_sha256(row[field]):
                raise DashboardReadModelError(f"dashboard_order_{field}_invalid")
        if row["side"] not in {"buy", "sell"} or row["phase"] not in {
            "reduce",
            "increase",
            "protective",
        } or row["status"] not in {
            "PLANNED",
            "SUBMITTING",
            "ACKNOWLEDGED",
            "PARTIALLY_FILLED",
            "FILLED",
            "REJECTED",
            "CANCELED",
            "EXPIRED",
            "UNKNOWN",
        }:
            raise DashboardReadModelError("dashboard_order_state_invalid")
        for field in ("reduce_only", "close_position"):
            if not isinstance(row[field], bool):
                raise DashboardReadModelError(f"dashboard_order_{field}_invalid")
        planned = row["planned_quantity"]
        if planned is not None:
            planned = _finite_nonnegative(planned, name="dashboard_order_planned")
        executed = _finite_nonnegative(row["executed_quantity"], name="dashboard_order_executed")
        remaining = row["remaining_quantity"]
        if planned is None:
            if remaining is not None:
                raise DashboardReadModelError("dashboard_order_remaining_invalid")
        elif not math.isclose(
            _finite_nonnegative(remaining, name="dashboard_order_remaining"),
            max(0.0, planned - executed),
            abs_tol=1e-12,
            rel_tol=0.0,
        ):
            raise DashboardReadModelError("dashboard_order_remaining_invalid")
        for field in ("average_price", "limit_price", "stop_price"):
            if row[field] is not None:
                _finite_nonnegative(row[field], name=f"dashboard_order_{field}")
        for field in ("exchange_order_id", "latest_reason"):
            if row[field] is not None and (
                not isinstance(row[field], str) or not row[field]
            ):
                raise DashboardReadModelError(f"dashboard_order_{field}_invalid")
        try:
            aware_datetime(str(row["last_transition_at"]))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError("dashboard_order_time_invalid") from exc
        count = _count(row["fill_count"], name="dashboard_order_fill_count")
        quantity = _finite_nonnegative(row["fill_quantity"], name="dashboard_order_fill_quantity")
        notional = _finite_nonnegative(row["fill_notional"], name="dashboard_order_fill_notional")
        row_fees = _mapping(row["fill_fees_by_asset"], name="dashboard_order_fill_fees")
        observed_fill_count += count
        observed_fill_quantity += quantity
        observed_fill_notional += notional
        for asset, amount in row_fees.items():
            if not isinstance(asset, str) or not asset:
                raise DashboardReadModelError("dashboard_order_fee_asset_invalid")
            observed_fees[asset] = observed_fees.get(asset, 0.0) + _finite_nonnegative(
                amount, name=f"dashboard_order_fee:{asset}"
            )
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise DashboardReadModelError("dashboard_order_identity_or_order_invalid")
    expected_counts = {
        "total_order_count": len(rows),
        "open_order_count": sum(
            row["status"] in {"SUBMITTING", "ACKNOWLEDGED", "PARTIALLY_FILLED", "UNKNOWN"}
            for row in rows
        ),
        "unresolved_order_count": sum(
            row["status"] in {"SUBMITTING", "PARTIALLY_FILLED", "UNKNOWN"}
            for row in rows
        ),
        "partial_fill_count": sum(row["status"] == "PARTIALLY_FILLED" for row in rows),
        "rejected_count": sum(row["status"] == "REJECTED" for row in rows),
        "protective_order_count": sum(row["phase"] == "protective" for row in rows),
        "fill_count": observed_fill_count,
    }
    if any(summary[field] != count for field, count in expected_counts.items()) or not math.isclose(
        float(summary["fill_quantity"]), observed_fill_quantity, abs_tol=1e-12, rel_tol=0.0
    ) or not math.isclose(
        float(summary["fill_notional"]), observed_fill_notional, abs_tol=1e-9, rel_tol=0.0
    ) or dict(fees) != observed_fees:
        raise DashboardReadModelError("dashboard_orders_summary_mismatch")
    fill_ids: list[tuple[str, str]] = []
    observed_order_ids = set(ids)
    for index, fill_value in enumerate(fills):
        fill = _mapping(fill_value, name=f"dashboard_fill:{index}")
        _exact_keys(
            fill,
            {
                "fill_id",
                "client_order_id",
                "exchange_trade_id",
                "quantity",
                "price",
                "fee",
                "fee_asset",
                "occurred_at",
                "source_hash",
                "fill_hash",
            },
            name=f"dashboard_fill:{index}",
        )
        for field in ("fill_id", "source_hash", "fill_hash"):
            if not is_sha256(fill[field]):
                raise DashboardReadModelError(f"dashboard_fill_{field}_invalid")
        for field in ("client_order_id", "exchange_trade_id", "fee_asset"):
            if not isinstance(fill[field], str) or not fill[field]:
                raise DashboardReadModelError(f"dashboard_fill_{field}_invalid")
        if fill["client_order_id"] not in observed_order_ids:
            raise DashboardReadModelError("dashboard_fill_order_missing")
        for field in ("quantity", "price"):
            if _finite_nonnegative(fill[field], name=f"dashboard_fill_{field}") <= 0.0:
                raise DashboardReadModelError(f"dashboard_fill_{field}_invalid")
        _finite_nonnegative(fill["fee"], name="dashboard_fill_fee")
        try:
            aware_datetime(str(fill["occurred_at"]))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError("dashboard_fill_time_invalid") from exc
        fill_ids.append((str(fill["occurred_at"]), str(fill["fill_id"])))
    if fill_ids != sorted(fill_ids) or len(fill_ids) != len(set(fill_ids)):
        raise DashboardReadModelError("dashboard_fill_order_invalid")
    if len(fills) != summary["fill_count"]:
        raise DashboardReadModelError("dashboard_fill_count_mismatch")


def _validate_risk_payload(value: Mapping[str, object]) -> None:
    decision = _mapping(value["decision"], name="dashboard_risk_decision")
    _exact_keys(
        decision,
        {
            "risk_decision_id",
            "approved",
            "increase_risk_allowed",
            "reduce_risk_allowed",
            "adjustments",
            "violations",
            "blockers",
        },
        name="dashboard_risk_decision",
    )
    if not is_sha256(decision["risk_decision_id"]):
        raise DashboardReadModelError("dashboard_risk_decision_id_invalid")
    for field in ("approved", "increase_risk_allowed", "reduce_risk_allowed"):
        if not isinstance(decision[field], bool):
            raise DashboardReadModelError(f"dashboard_risk_decision_{field}_invalid")
    for field in ("adjustments", "violations", "blockers"):
        _string_list(decision[field], name=f"dashboard_risk_decision_{field}")
    runtime = _validate_runtime_wrapper(value["runtime"], name="dashboard_risk_runtime")
    if (value["authority"]["account_and_pnl"] == "runtime_ledger") is not (
        runtime["status"] == "available"
    ):
        raise DashboardReadModelError("dashboard_risk_runtime_availability_mismatch")
    if runtime["status"] != "available":
        return
    values = _mapping(runtime["values"], name="dashboard_risk_runtime_values")
    _exact_keys(
        values,
        {
            "gate_status",
            "reason_codes",
            "reconciliation",
            "accounting",
            "protective_order_status_counts",
            "cash_event_counts",
            "cash_event_amounts",
        },
        name="dashboard_risk_runtime_values",
    )
    if values["gate_status"] not in {"pass", "block"}:
        raise DashboardReadModelError("dashboard_risk_gate_status_invalid")
    reasons = _string_list(values["reason_codes"], name="dashboard_risk_reasons")
    reconciliation = _mapping(values["reconciliation"], name="dashboard_risk_reconciliation")
    _exact_keys(
        reconciliation,
        {
            "reconciliation_id",
            "passed",
            "risk_increase_allowed",
            "halt_required",
            "blockers",
            "position_differences",
            "equity_residual",
            "equity_residual_tolerance",
        },
        name="dashboard_risk_reconciliation",
    )
    if not is_sha256(reconciliation["reconciliation_id"]):
        raise DashboardReadModelError("dashboard_risk_reconciliation_id_invalid")
    for field in ("passed", "risk_increase_allowed", "halt_required"):
        if not isinstance(reconciliation[field], bool):
            raise DashboardReadModelError(f"dashboard_risk_reconciliation_{field}_invalid")
    _string_list(reconciliation["blockers"], name="dashboard_risk_reconciliation_blockers")
    _mapping(reconciliation["position_differences"], name="dashboard_risk_position_differences")
    _finite(reconciliation["equity_residual"], name="dashboard_risk_equity_residual")
    _finite_nonnegative(
        reconciliation["equity_residual_tolerance"],
        name="dashboard_risk_equity_residual_tolerance",
    )
    accounting = _mapping(values["accounting"], name="dashboard_risk_accounting")
    _exact_keys(
        accounting,
        {
            "nav_mark_id",
            "mark_hash",
            "passed",
            "residual",
            "residual_tolerance",
            "funding",
            "fees",
            "transfers",
        },
        name="dashboard_risk_accounting",
    )
    for field in ("nav_mark_id", "mark_hash"):
        if not is_sha256(accounting[field]):
            raise DashboardReadModelError(f"dashboard_risk_accounting_{field}_invalid")
    if not isinstance(accounting["passed"], bool):
        raise DashboardReadModelError("dashboard_risk_accounting_passed_invalid")
    for field in ("residual", "funding", "transfers"):
        _finite(accounting[field], name=f"dashboard_risk_accounting_{field}")
    for field in ("residual_tolerance", "fees"):
        _finite_nonnegative(accounting[field], name=f"dashboard_risk_accounting_{field}")
    for name in (
        "protective_order_status_counts",
        "cash_event_counts",
    ):
        counts = _mapping(values[name], name=f"dashboard_risk_{name}")
        for key, count in counts.items():
            if not isinstance(key, str) or not key:
                raise DashboardReadModelError(f"dashboard_risk_{name}_key_invalid")
            _count(count, name=f"dashboard_risk_{name}:{key}")
    amounts = _mapping(values["cash_event_amounts"], name="dashboard_risk_cash_amounts")
    for key, amount in amounts.items():
        if not isinstance(key, str) or not key:
            raise DashboardReadModelError("dashboard_risk_cash_amount_key_invalid")
        _finite(amount, name=f"dashboard_risk_cash_amount:{key}")
    expected_reasons = []
    if not decision["increase_risk_allowed"]:
        expected_reasons.append("decision_risk_increase_blocked")
    if not reconciliation["risk_increase_allowed"]:
        expected_reasons.append("reconciliation_risk_increase_blocked")
    if reconciliation["halt_required"]:
        expected_reasons.append("reconciliation_halt_required")
    if not accounting["passed"]:
        expected_reasons.append("accounting_identity_failed")
    if values["gate_status"] == "pass" and (expected_reasons or reasons):
        raise DashboardReadModelError("dashboard_risk_gate_reason_mismatch")


def _validate_system_payload(value: Mapping[str, object]) -> None:
    summary = _mapping(value["summary"], name="dashboard_system_summary")
    _exact_keys(
        summary,
        {"status", "reason_codes", "unavailable_fields"},
        name="dashboard_system_summary",
    )
    if summary["status"] not in {
        "unavailable_until_phase_b_ledger",
        "healthy",
        "attention_required",
        "halt_required",
    }:
        raise DashboardReadModelError("dashboard_system_status_invalid")
    reasons = _string_list(summary["reason_codes"], name="dashboard_system_reasons")
    unavailable_fields = _string_list(
        summary["unavailable_fields"], name="dashboard_system_unavailable_fields"
    )
    health = _mapping(value["health"], name="dashboard_system_health")
    _exact_keys(health, {"status", "source", "values"}, name="dashboard_system_health")
    if health["source"] != "system_health":
        raise DashboardReadModelError("dashboard_system_health_source_invalid")
    if health["status"] == "unavailable_until_health_observation":
        if health["values"] is not None:
            raise DashboardReadModelError("dashboard_system_health_unavailable_invalid")
        health_snapshot = None
    elif health["status"] == "available":
        try:
            health_snapshot = SystemHealthSnapshot.from_dict(
                _mapping(health["values"], name="dashboard_system_health_values")
            )
        except SystemHealthContractError as exc:
            raise DashboardReadModelError(
                f"dashboard_system_health_invalid:{exc}"
            ) from exc
    else:
        raise DashboardReadModelError("dashboard_system_health_status_invalid")
    expected_unavailable = (
        ["backup", "clock", "disk", "operations", "service"]
        if health_snapshot is None
        else []
    )
    if unavailable_fields != expected_unavailable:
        raise DashboardReadModelError("dashboard_system_unavailable_fields_mismatch")
    ledger = _validate_runtime_wrapper(value["ledger"], name="dashboard_system_ledger")
    runtime = value["authority"]["account_and_pnl"] == "runtime_ledger"
    if runtime is not (ledger["status"] == "available"):
        raise DashboardReadModelError("dashboard_system_ledger_availability_mismatch")
    if not runtime:
        if summary["status"] != "unavailable_until_phase_b_ledger":
            raise DashboardReadModelError("dashboard_system_unavailable_invalid")
        return
    values = _mapping(ledger["values"], name="dashboard_system_ledger_values")
    _exact_keys(
        values,
        {
            "schema_version",
            "snapshot_hash",
            "captured_at",
            "source_updated_at",
            "integrity_status",
            "audit_chain_status",
            "audit_last_hash",
            "audit_row_count",
            "reconciliation_id",
            "reconciliation_passed",
            "halt_required",
            "recoverable_order_count",
            "recovery_report_count",
            "latest_recovery_status",
            "nav_accounting_passed",
        },
        name="dashboard_system_ledger_values",
    )
    if values["schema_version"] != 3:
        raise DashboardReadModelError("dashboard_system_ledger_schema_invalid")
    for field in ("snapshot_hash", "audit_last_hash", "reconciliation_id"):
        if not is_sha256(values[field]):
            raise DashboardReadModelError(f"dashboard_system_{field}_invalid")
    for field in ("captured_at", "source_updated_at"):
        try:
            aware_datetime(str(values[field]))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError(f"dashboard_system_{field}_invalid") from exc
    if values["integrity_status"] != "verified" or values["audit_chain_status"] != "verified":
        raise DashboardReadModelError("dashboard_system_integrity_invalid")
    for field in ("reconciliation_passed", "halt_required", "nav_accounting_passed"):
        if not isinstance(values[field], bool):
            raise DashboardReadModelError(f"dashboard_system_{field}_invalid")
    for field in ("audit_row_count", "recoverable_order_count", "recovery_report_count"):
        _count(values[field], name=f"dashboard_system_{field}")
    if values["audit_row_count"] < 1 or values["latest_recovery_status"] not in {
        "none",
        "passed",
        "blocked",
    }:
        raise DashboardReadModelError("dashboard_system_runtime_state_invalid")
    expected_status = (
        "halt_required"
        if values["halt_required"]
        or values["recoverable_order_count"]
        or (health_snapshot is not None and health_snapshot.status == "unavailable")
        else "attention_required"
        if not values["reconciliation_passed"]
        or not values["nav_accounting_passed"]
        or health_snapshot is None
        or health_snapshot.status == "degraded"
        else "healthy"
    )
    if summary["status"] != expected_status:
        raise DashboardReadModelError("dashboard_system_status_mismatch")


def _validate_alerts_payload(value: Mapping[str, object]) -> None:
    authority = _mapping(value["authority"], name="dashboard_alerts_authority")
    _exact_keys(
        authority,
        {"notifications"},
        name="dashboard_alerts_authority",
    )
    if authority["notifications"] not in {
        "notification_store",
        "unavailable_until_phase_c_notification_store",
    }:
        raise DashboardReadModelError("dashboard_alerts_authority_invalid")
    summary = _mapping(value["summary"], name="dashboard_alerts_summary")
    _exact_keys(
        summary,
        {
            "status",
            "open_alert_count",
            "resolved_alert_count",
            "severity_counts",
            "historical_severity_counts",
            "delivery_state_counts",
            "monitoring_observed_at",
            "content_updated_at",
            "audit_last_hash",
            "audit_row_count",
        },
        name="dashboard_alerts_summary",
    )
    alerts = value["alerts"]
    if not isinstance(alerts, list):
        raise DashboardReadModelError("dashboard_alerts_rows_invalid")
    available = authority["notifications"] == "notification_store"
    if not available:
        if summary != {
            "status": "unavailable_until_phase_c_notification_store",
            "open_alert_count": None,
            "resolved_alert_count": None,
            "severity_counts": None,
            "historical_severity_counts": None,
            "delivery_state_counts": None,
            "monitoring_observed_at": None,
            "content_updated_at": None,
            "audit_last_hash": None,
            "audit_row_count": None,
        } or alerts:
            raise DashboardReadModelError(
                "dashboard_alerts_unavailable_payload_invalid"
            )
        return
    if summary["status"] != "available":
        raise DashboardReadModelError("dashboard_alerts_status_invalid")
    if (
        set(
            _mapping(
                summary["severity_counts"],
                name="dashboard_alert_severity_counts",
            )
        )
        != set(ALERT_SEVERITIES)
        or set(
            _mapping(
                summary["historical_severity_counts"],
                name="dashboard_alert_historical_severity_counts",
            )
        )
        != set(ALERT_SEVERITIES)
        or set(
            _mapping(
                summary["delivery_state_counts"],
                name="dashboard_alert_delivery_counts",
            )
        )
        != set(DELIVERY_STATES)
    ):
        raise DashboardReadModelError("dashboard_alert_counts_invalid")
    severity_counts = dict(summary["severity_counts"])
    historical_severity_counts = dict(summary["historical_severity_counts"])
    delivery_counts = dict(summary["delivery_state_counts"])
    for counts in (
        severity_counts,
        historical_severity_counts,
        delivery_counts,
    ):
        if any(
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            for count in counts.values()
        ):
            raise DashboardReadModelError("dashboard_alert_counts_invalid")
    if (
        not isinstance(summary["open_alert_count"], int)
        or isinstance(summary["open_alert_count"], bool)
        or summary["open_alert_count"] < 0
        or not isinstance(summary["resolved_alert_count"], int)
        or isinstance(summary["resolved_alert_count"], bool)
        or summary["resolved_alert_count"] < 0
        or not isinstance(summary["audit_row_count"], int)
        or isinstance(summary["audit_row_count"], bool)
        or summary["audit_row_count"] < 0
        or not is_sha256(summary["audit_last_hash"])
    ):
        raise DashboardReadModelError("dashboard_alert_summary_invalid")
    try:
        aware_datetime(str(summary["monitoring_observed_at"]))
        if summary["content_updated_at"] is not None:
            aware_datetime(str(summary["content_updated_at"]))
    except (AttributeError, TypeError, ValueError) as exc:
        raise DashboardReadModelError(
            "dashboard_alert_observation_time_invalid"
        ) from exc
    observed_severity = {severity: 0 for severity in ALERT_SEVERITIES}
    observed_historical_severity = {
        severity: 0 for severity in ALERT_SEVERITIES
    }
    observed_delivery = {status: 0 for status in DELIVERY_STATES}
    open_count = 0
    alert_order: list[tuple[str, str]] = []
    alert_ids: set[str] = set()
    event_fields = set(AlertEvent.__dataclass_fields__)
    for index, row_value in enumerate(alerts):
        row = _mapping(row_value, name=f"dashboard_alert:{index}")
        _exact_keys(
            row,
            event_fields
            | {"status", "resolved_at", "state_hash", "deliveries"},
            name=f"dashboard_alert:{index}",
        )
        try:
            event = AlertEvent(**{name: row[name] for name in event_fields})
            event.validate()
        except (TypeError, ValueError) as exc:
            raise DashboardReadModelError("dashboard_alert_event_invalid") from exc
        if event.alert_id in alert_ids:
            raise DashboardReadModelError("dashboard_alert_identity_duplicate")
        alert_ids.add(event.alert_id)
        alert_order.append((event.occurred_at, event.alert_id))
        if row["status"] not in {"OPEN", "RESOLVED"}:
            raise DashboardReadModelError("dashboard_alert_state_invalid")
        if (row["status"] == "OPEN") is not (row["resolved_at"] is None):
            raise DashboardReadModelError("dashboard_alert_state_invalid")
        if row["resolved_at"] is not None:
            try:
                if aware_datetime(str(row["resolved_at"])) < aware_datetime(
                    event.occurred_at
                ):
                    raise ValueError("resolved_before_alert")
            except (AttributeError, TypeError, ValueError) as exc:
                raise DashboardReadModelError(
                    "dashboard_alert_resolution_invalid"
                ) from exc
        expected_state_hash = canonical_hash(
            {
                "alert_id": event.alert_id,
                "status": row["status"],
                "resolved_at": row["resolved_at"],
            }
        )
        if row["state_hash"] != expected_state_hash:
            raise DashboardReadModelError("dashboard_alert_state_hash_invalid")
        if row["status"] == "OPEN":
            open_count += 1
            observed_severity[event.severity] += 1
        observed_historical_severity[event.severity] += 1
        deliveries = row["deliveries"]
        if not isinstance(deliveries, list):
            raise DashboardReadModelError("dashboard_alert_deliveries_invalid")
        channels: list[str] = []
        for delivery_value in deliveries:
            delivery = _mapping(
                delivery_value, name="dashboard_alert_delivery"
            )
            _exact_keys(
                delivery,
                {
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
                },
                name="dashboard_alert_delivery",
            )
            if (
                not isinstance(delivery["channel"], str)
                or not delivery["channel"]
                or delivery["status"] not in DELIVERY_STATES
                or not isinstance(delivery["attempt_count"], int)
                or isinstance(delivery["attempt_count"], bool)
                or delivery["attempt_count"] < 0
                or not isinstance(delivery["max_attempts"], int)
                or isinstance(delivery["max_attempts"], bool)
                or delivery["max_attempts"] < 1
                or delivery["attempt_count"] > delivery["max_attempts"]
            ):
                raise DashboardReadModelError("dashboard_alert_delivery_invalid")
            expected_job_id = trace_id(
                "notification_job",
                {
                    "alert_id": event.alert_id,
                    "channel": delivery["channel"],
                },
            )
            expected_delivery_key = trace_id(
                "notification_delivery",
                {
                    "job_id": expected_job_id,
                    "event_hash": event.event_hash,
                },
            )
            job_core = {
                name: delivery[name]
                for name in (
                    "job_id",
                    "alert_id",
                    "channel",
                    "delivery_key",
                    "status",
                    "attempt_count",
                    "max_attempts",
                    "next_attempt_at",
                    "last_attempt_at",
                    "delivered_at",
                    "last_error",
                )
                if name in delivery
            }
            job_core["alert_id"] = event.alert_id
            job_core = {
                name: job_core[name]
                for name in (
                    "job_id",
                    "alert_id",
                    "channel",
                    "delivery_key",
                    "status",
                    "attempt_count",
                    "max_attempts",
                    "next_attempt_at",
                    "last_attempt_at",
                    "delivered_at",
                    "last_error",
                )
            }
            if (
                delivery["job_id"] != expected_job_id
                or delivery["delivery_key"] != expected_delivery_key
                or delivery["job_hash"] != canonical_hash(job_core)
            ):
                raise DashboardReadModelError(
                    "dashboard_alert_delivery_hash_invalid"
                )
            channels.append(delivery["channel"])
            observed_delivery[delivery["status"]] += 1
        if channels != sorted(channels) or len(channels) != len(set(channels)):
            raise DashboardReadModelError(
                "dashboard_alert_delivery_order_invalid"
            )
    if alert_order != sorted(alert_order, reverse=True):
        raise DashboardReadModelError("dashboard_alert_order_invalid")
    if (
        open_count != summary["open_alert_count"]
        or len(alerts) - open_count != summary["resolved_alert_count"]
        or observed_severity != severity_counts
        or observed_historical_severity != historical_severity_counts
        or observed_delivery != delivery_counts
    ):
        raise DashboardReadModelError("dashboard_alert_counts_mismatch")


def _validate_readonly_account_value(
    value: object,
    *,
    name: str,
    value_kind: str,
) -> Mapping[str, Any]:
    row = _mapping(value, name=name)
    _exact_keys(row, {"status", "source", "values"}, name=name)
    if row["status"] != "available_readonly" or row["source"] != "private_account_preflight":
        raise DashboardReadModelError(f"{name}_not_private_readonly_authoritative")
    values = _mapping(row["values"], name=f"{name}_values")
    if value_kind == "account":
        expected = {
            "source", "observed_at", "quote_asset", "wallet_balance",
            "available_balance", "margin_balance", "margin_used",
            "actual_gross_notional", "actual_gross_fraction", "margin_fraction",
            "open_order_count", "positions",
        }
        _exact_keys(values, expected, name=f"{name}_values")
        if values["source"] != "private_account_preflight":
            raise DashboardReadModelError(f"{name}_source_invalid")
        try:
            aware_datetime(str(values["observed_at"]))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError(f"{name}_observed_at_invalid") from exc
        if not isinstance(values["quote_asset"], str) or not values["quote_asset"]:
            raise DashboardReadModelError(f"{name}_quote_asset_invalid")
        for field in expected - {"source", "observed_at", "quote_asset", "positions"}:
            if field == "open_order_count":
                if not isinstance(values[field], int) or isinstance(values[field], bool) or values[field] < 0:
                    raise DashboardReadModelError(f"{name}_{field}_invalid")
            else:
                _finite_nonnegative(values[field], name=f"{name}_{field}")
        positions = values["positions"]
        if not isinstance(positions, list):
            raise DashboardReadModelError(f"{name}_positions_invalid")
        symbols = []
        for position in positions:
            item = _mapping(position, name=f"{name}_position")
            _exact_keys(item, {"symbol", "side", "quantity", "notional"}, name=f"{name}_position")
            if not isinstance(item["symbol"], str) or not item["symbol"] or item["side"] not in {"long", "short"}:
                raise DashboardReadModelError(f"{name}_position_identity_invalid")
            _finite_nonnegative(item["quantity"], name=f"{name}_position_quantity")
            _finite_nonnegative(item["notional"], name=f"{name}_position_notional")
            symbols.append(item["symbol"])
        if symbols != sorted(symbols) or len(symbols) != len(set(symbols)):
            raise DashboardReadModelError(f"{name}_positions_order_invalid")
    elif value_kind == "positions":
        _exact_keys(values, {"positions", "open_order_count"}, name=f"{name}_values")
        positions = _mapping(values["positions"], name=f"{name}_positions")
        if list(positions) != sorted(positions):
            raise DashboardReadModelError(f"{name}_positions_order_invalid")
        for symbol, quantity in positions.items():
            if not isinstance(symbol, str) or not symbol:
                raise DashboardReadModelError(f"{name}_position_symbol_invalid")
            _finite_nonnegative(quantity, name=f"{name}_position:{symbol}")
        if not isinstance(values["open_order_count"], int) or isinstance(values["open_order_count"], bool) or values["open_order_count"] < 0:
            raise DashboardReadModelError(f"{name}_open_order_count_invalid")
    else:
        raise DashboardReadModelError(f"{name}_kind_invalid")
    return row


def _validate_ledger_value(
    value: object,
    *,
    name: str,
    value_kind: str,
) -> Mapping[str, Any]:
    row = _mapping(value, name=name)
    _exact_keys(row, {"status", "source", "values"}, name=name)
    if row["source"] != "runtime_ledger":
        raise DashboardReadModelError(f"{name}_not_ledger_authoritative")
    if row["status"] == "unavailable_until_phase_b_ledger":
        if row["values"] is not None:
            raise DashboardReadModelError(f"{name}_unavailable_values_present")
        return row
    if row["status"] != "available":
        raise DashboardReadModelError(f"{name}_status_invalid")
    values = _mapping(row["values"], name=f"{name}_values")
    if value_kind == "positions":
        _exact_keys(
            values,
            {"positions", "open_order_ids", "unresolved_order_ids"},
            name=f"{name}_values",
        )
        positions = _mapping(values["positions"], name=f"{name}_positions")
        if list(positions) != sorted(positions):
            raise DashboardReadModelError(f"{name}_positions_order_invalid")
        for symbol, quantity in positions.items():
            if not isinstance(symbol, str) or not symbol:
                raise DashboardReadModelError(f"{name}_position_symbol_invalid")
            _finite_nonnegative(quantity, name=f"{name}_position:{symbol}")
        for field in ("open_order_ids", "unresolved_order_ids"):
            identifiers = values[field]
            if (
                not isinstance(identifiers, list)
                or any(not isinstance(item, str) or not item for item in identifiers)
                or identifiers != sorted(identifiers)
                or len(identifiers) != len(set(identifiers))
            ):
                raise DashboardReadModelError(f"{name}_{field}_invalid")
        if not set(values["unresolved_order_ids"]).issubset(
            values["open_order_ids"]
        ):
            raise DashboardReadModelError(f"{name}_unresolved_orders_not_open")
    elif value_kind == "pnl":
        expected = {
            "nav_mark_id",
            "mark_hash",
            "marked_at",
            "previous_equity",
            "equity",
            "equity_change",
            "trading_pnl",
            "funding",
            "fees",
            "transfers",
            "residual",
            "residual_tolerance",
            "passed",
            "trading_pnl_cumulative",
            "funding_cumulative",
            "fees_cumulative",
            "transfers_cumulative",
            "peak_equity",
            "current_drawdown_fraction",
            "peak_drawdown_fraction",
            "peak_drawdown_at",
        }
        _exact_keys(values, expected, name=f"{name}_values")
        for field in ("nav_mark_id", "mark_hash"):
            if not is_sha256(values[field]):
                raise DashboardReadModelError(f"{name}_{field}_invalid")
        try:
            aware_datetime(str(values["marked_at"]))
            aware_datetime(str(values["peak_drawdown_at"]))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError(f"{name}_marked_at_invalid") from exc
        for field in expected - {
            "nav_mark_id",
            "mark_hash",
            "marked_at",
            "passed",
            "peak_drawdown_at",
        }:
            number = _finite_nonnegative(values[field], name=f"{name}_{field}") if field in {
                "previous_equity",
                "equity",
                "fees",
                "residual_tolerance",
                "fees_cumulative",
                "peak_equity",
                "current_drawdown_fraction",
                "peak_drawdown_fraction",
            } else _finite(values[field], name=f"{name}_{field}")
            if not math.isfinite(number):
                raise DashboardReadModelError(f"{name}_{field}_invalid")
        if not isinstance(values["passed"], bool):
            raise DashboardReadModelError(f"{name}_passed_invalid")
    elif value_kind == "account":
        expected = {
            "account_observation_id",
            "batch_id",
            "observed_at",
            "quote_asset",
            "wallet_balance",
            "available_balance",
            "actual_gross_notional",
            "actual_gross_fraction",
            "margin_used",
            "margin_fraction",
            "source_id",
            "source_hash",
            "observation_hash",
            "peak_equity",
            "current_drawdown_fraction",
            "peak_drawdown_fraction",
            "peak_drawdown_at",
        }
        _exact_keys(values, expected, name=f"{name}_values")
        for field in (
            "account_observation_id",
            "batch_id",
            "source_id",
            "source_hash",
            "observation_hash",
        ):
            if not is_sha256(values[field]):
                raise DashboardReadModelError(f"{name}_{field}_invalid")
        for field in ("observed_at", "peak_drawdown_at"):
            try:
                aware_datetime(str(values[field]))
            except (AttributeError, TypeError, ValueError) as exc:
                raise DashboardReadModelError(f"{name}_{field}_invalid") from exc
        if (
            not isinstance(values["quote_asset"], str)
            or not values["quote_asset"]
        ):
            raise DashboardReadModelError(f"{name}_quote_asset_invalid")
        for field in expected - {
            "account_observation_id",
            "batch_id",
            "observed_at",
            "quote_asset",
            "source_id",
            "source_hash",
            "observation_hash",
            "peak_drawdown_at",
        }:
            _finite_nonnegative(values[field], name=f"{name}_{field}")
        if float(values["available_balance"]) > float(values["wallet_balance"]) + 1e-12:
            raise DashboardReadModelError(f"{name}_balance_invalid")
    elif value_kind == "strategy_nav":
        _exact_keys(
            values,
            {
                "scope",
                "nav_mark_id",
                "mark_hash",
                "marked_at",
                "signal_nav",
                "standalone_executable_nav",
            },
            name=f"{name}_values",
        )
        if values["scope"] != "portfolio":
            raise DashboardReadModelError(f"{name}_scope_invalid")
        for field in ("nav_mark_id", "mark_hash"):
            if not is_sha256(values[field]):
                raise DashboardReadModelError(f"{name}_{field}_invalid")
        try:
            aware_datetime(str(values["marked_at"]))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DashboardReadModelError(f"{name}_marked_at_invalid") from exc
        for field in ("signal_nav", "standalone_executable_nav"):
            if values[field] is not None and _finite_nonnegative(
                values[field], name=f"{name}_{field}"
            ) <= 0.0:
                raise DashboardReadModelError(f"{name}_{field}_invalid")
    else:
        raise DashboardReadModelError(f"{name}_kind_invalid")
    return row


def _validate_strategy_decision(value: object, *, index: int) -> None:
    decision = _mapping(value, name=f"dashboard_strategy_decision:{index}")
    _exact_keys(
        decision,
        {
            "decision_id",
            "intent_hash",
            "decision_time",
            "reason_codes",
            "standalone_target",
            "standalone_target_gross",
            "portfolio_sleeve",
            "target_stress_loss_fraction",
        },
        name=f"dashboard_strategy_decision:{index}",
    )
    for name in ("decision_id", "intent_hash"):
        if not is_sha256(decision[name]):
            raise DashboardReadModelError(
                f"dashboard_strategy_decision_{name}_invalid"
            )
    try:
        aware_datetime(str(decision["decision_time"]))
    except (AttributeError, TypeError, ValueError) as exc:
        raise DashboardReadModelError(
            "dashboard_strategy_decision_time_invalid"
        ) from exc
    reason_codes = decision["reason_codes"]
    if (
        not isinstance(reason_codes, list)
        or not reason_codes
        or any(not isinstance(value, str) or not value for value in reason_codes)
        or len(reason_codes) != len(set(reason_codes))
    ):
        raise DashboardReadModelError(
            "dashboard_strategy_decision_reason_codes_invalid"
        )
    standalone = _mapping(
        decision["standalone_target"], name="dashboard_strategy_standalone_target"
    )
    sleeve = _mapping(
        decision["portfolio_sleeve"], name="dashboard_strategy_portfolio_sleeve"
    )
    if not math.isclose(
        _gross(standalone),
        _finite_nonnegative(
            decision["standalone_target_gross"],
            name="dashboard_strategy_standalone_target_gross",
        ),
        abs_tol=1e-12,
        rel_tol=0.0,
    ):
        raise DashboardReadModelError(
            "dashboard_strategy_standalone_target_gross_mismatch"
        )
    if _gross(standalone) > 1.0 + 1e-12 or _gross(sleeve) > 1.0 + 1e-12:
        raise DashboardReadModelError("dashboard_strategy_target_gross_invalid")
    stress = _finite_nonnegative(
        decision["target_stress_loss_fraction"],
        name="dashboard_strategy_target_stress_loss_fraction",
    )
    if stress > 1.0 + 1e-12:
        raise DashboardReadModelError(
            "dashboard_strategy_target_stress_loss_fraction_invalid"
        )


def _authority(
    ledger_snapshot: RuntimeLedgerSnapshot | None,
    *,
    readonly_account: bool = False,
) -> dict[str, str]:
    return {
        "decision": "verified_decision_batch",
        "governance": "strategy_registry",
        "account_and_pnl": (
            "runtime_ledger"
            if ledger_snapshot is not None
            else "private_account_preflight"
            if readonly_account
            else "unavailable_until_phase_b_ledger"
        ),
    }


def _ledger_unavailable() -> dict[str, object]:
    return {
        "status": "unavailable_until_phase_b_ledger",
        "source": "runtime_ledger",
        "values": None,
    }


def _pnl_values(ledger_snapshot: RuntimeLedgerSnapshot) -> dict[str, object]:
    nav = ledger_snapshot.nav
    fields = (
        "nav_mark_id",
        "mark_hash",
        "marked_at",
        "previous_equity",
        "equity",
        "equity_change",
        "trading_pnl",
        "funding",
        "fees",
        "transfers",
        "residual",
        "residual_tolerance",
        "passed",
        "trading_pnl_cumulative",
        "funding_cumulative",
        "fees_cumulative",
        "transfers_cumulative",
    )
    return {field: nav[field] for field in fields} | {
        field: ledger_snapshot.account[field]
        for field in (
            "peak_equity",
            "current_drawdown_fraction",
            "peak_drawdown_fraction",
            "peak_drawdown_at",
        )
    }


def _account_values(ledger_snapshot: RuntimeLedgerSnapshot) -> dict[str, object]:
    return dict(ledger_snapshot.account)


def _readonly_account_values(observation: Mapping[str, Any]) -> dict[str, object]:
    values = _mapping(
        observation["account_observation"], name="blocked_runtime_account_observation"
    )
    return dict(values)


def _overview_payload(
    batch: VerifiedDecisionBatch,
    ledger_snapshot: RuntimeLedgerSnapshot | None,
    blocked_runtime_observation: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    target = batch.target
    risk = batch.risk
    plan = batch.plan
    return {
        "authority": _authority(
            ledger_snapshot,
            readonly_account=blocked_runtime_observation is not None
            and "account_observation" in blocked_runtime_observation,
        ),
        "latest_batch": {
            "batch_id": batch.manifest.batch_id,
            "manifest_id": batch.manifest.decision_batch_manifest_id,
            "manifest_hash": batch.manifest.manifest_hash,
            "snapshot_id": batch.snapshot.snapshot_id,
            "decision_time": batch.snapshot.decision_time,
            "data_cutoff": batch.snapshot.data_cutoff,
            "complete": True,
            "decision_count": len(batch.intents),
        },
        "account": (
            _ledger_unavailable()
            if ledger_snapshot is None
            and (blocked_runtime_observation is None or "account_observation" not in blocked_runtime_observation)
            else {
                "status": "available_readonly",
                "source": "private_account_preflight",
                "values": _readonly_account_values(blocked_runtime_observation),
            }
            if blocked_runtime_observation is not None and "account_observation" in blocked_runtime_observation
            else {
                "status": "available",
                "source": "runtime_ledger",
                "values": _account_values(ledger_snapshot),
            }
        ),
        "portfolio": {
            "portfolio_target_id": target.portfolio_target_id,
            "approved_target": dict(risk.approved_target),
            "approved_target_gross": _gross(risk.approved_target),
            "actual_positions": (
                _ledger_unavailable()
                if ledger_snapshot is None
                and (blocked_runtime_observation is None or "account_observation" not in blocked_runtime_observation)
                else {
                    "status": "available_readonly",
                    "source": "private_account_preflight",
                    "values": {
                        "positions": {
                            row["symbol"]: row["quantity"]
                            for row in _readonly_account_values(
                                blocked_runtime_observation
                            )["positions"]
                        },
                        "open_order_count": _readonly_account_values(
                            blocked_runtime_observation
                        )["open_order_count"],
                    },
                }
                if blocked_runtime_observation is not None and "account_observation" in blocked_runtime_observation
                else {
                    "status": "available",
                    "source": "runtime_ledger",
                    "values": {
                        "positions": dict(ledger_snapshot.positions),
                        "open_order_ids": list(ledger_snapshot.open_order_ids),
                        "unresolved_order_ids": list(
                            ledger_snapshot.unresolved_order_ids
                        ),
                    },
                }
            ),
            "planned_order_count": len(plan.orders),
            "planned_cancellation_count": len(plan.cancellations),
            "plan_executable": plan.executable,
        },
        "risk": {
            "risk_decision_id": risk.risk_decision_id,
            "approved": risk.approved,
            "increase_risk_allowed": risk.increase_risk_allowed,
            "reduce_risk_allowed": risk.reduce_risk_allowed,
            "adjustments": list(risk.adjustments),
            "violations": list(risk.violations),
            "blockers": list(plan.blockers),
        },
        "pnl": (
            _ledger_unavailable()
            if ledger_snapshot is None
            else {
                "status": "available",
                "source": "runtime_ledger",
                "values": _pnl_values(ledger_snapshot),
            }
        ),
    }


def _positions_payload(
    batch: VerifiedDecisionBatch,
    ledger_snapshot: RuntimeLedgerSnapshot | None,
) -> dict[str, object]:
    if ledger_snapshot is None:
        return {
            "authority": _authority(None),
            "summary": {
                "status": "unavailable_until_phase_b_ledger",
                "position_count": 0,
                "nonzero_position_count": 0,
                "reconciliation_id": None,
                "reconciled": False,
            },
            "positions": [],
        }
    details = {
        str(row["symbol"]): row for row in ledger_snapshot.position_details
    }
    symbols = sorted(
        set(batch.risk.approved_target)
        | set(batch.plan.expected_positions)
        | set(ledger_snapshot.positions)
    )
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        fact = details.get(symbol)
        actual = float(ledger_snapshot.positions.get(symbol, 0.0))
        expected = float(batch.plan.expected_positions.get(symbol, 0.0))
        decision_ids = sorted(
            intent.decision_id
            for intent in batch.intents
            if symbol in intent.target_weights
            or any(
                order.symbol == symbol and intent.decision_id in order.decision_ids
                for order in batch.plan.orders
            )
        )
        trace_target = decision_ids[0] if decision_ids else batch.manifest.batch_id
        rows.append(
            {
                "symbol": symbol,
                "actual_quantity": actual,
                "average_cost": 0.0 if fact is None else fact["average_cost"],
                "realized_trading_pnl": (
                    0.0 if fact is None else fact["realized_trading_pnl"]
                ),
                "expected_quantity": expected,
                "quantity_difference": actual - expected,
                "approved_target_weight": float(
                    batch.risk.approved_target.get(symbol, 0.0)
                ),
                "updated_at": None if fact is None else fact["updated_at"],
                "source_hash": None if fact is None else fact["source_hash"],
                "position_hash": None if fact is None else fact["position_hash"],
                "trace": {
                    "batch_id": batch.manifest.batch_id,
                    "manifest_hash": batch.manifest.manifest_hash,
                    "snapshot_id": batch.snapshot.snapshot_id,
                    "decision_ids": decision_ids,
                    "portfolio_target_id": batch.target.portfolio_target_id,
                    "risk_decision_id": batch.risk.risk_decision_id,
                    "order_plan_id": batch.plan.order_plan_id,
                    "href": _trace_href(trace_target),
                },
            }
        )
    reconciliation = ledger_snapshot.reconciliation
    return {
        "authority": _authority(ledger_snapshot),
        "summary": {
            "status": "available",
            "position_count": len(rows),
            "nonzero_position_count": sum(
                float(row["actual_quantity"]) > 0.0 for row in rows
            ),
            "reconciliation_id": reconciliation["reconciliation_id"],
            "reconciled": bool(reconciliation["passed"]),
        },
        "positions": rows,
    }


def _trace_node(
    identifier: str, node_type: str, label: str, integrity_hash: str
) -> dict[str, str]:
    return {
        "id": identifier,
        "type": node_type,
        "label": label,
        "integrity_hash": integrity_hash,
        "href": _trace_href(identifier),
    }


def _decisions_payload(
    batch: VerifiedDecisionBatch,
    ledger_snapshot: RuntimeLedgerSnapshot | None,
) -> dict[str, object]:
    strategies = [
        {
            "strategy_id": intent.strategy_id,
            "strategy_version": intent.strategy_version,
            "decision_id": intent.decision_id,
            "intent_hash": intent.intent_hash,
            "decision_time": intent.decision_time,
            "reason_codes": list(intent.reason_codes),
            "target_weights": dict(intent.target_weights),
            "target_stress_loss_fraction": intent.target_stress_loss_fraction,
            "href": _trace_href(intent.decision_id),
        }
        for intent in sorted(
            batch.intents, key=lambda row: (row.strategy_id, row.decision_id)
        )
    ]
    decision_ids = [str(row["decision_id"]) for row in strategies]
    nodes = [
        _trace_node(
            batch.manifest.batch_id,
            "decision_batch",
            "Verified decision batch",
            batch.manifest.manifest_hash,
        ),
        _trace_node(
            batch.snapshot.snapshot_id,
            "market_snapshot",
            "Market snapshot",
            batch.snapshot.snapshot_hash,
        ),
        *(
            _trace_node(
                intent.decision_id,
                "strategy_decision",
                f"{intent.strategy_id} v{intent.strategy_version}",
                intent.intent_hash,
            )
            for intent in sorted(
                batch.intents, key=lambda row: (row.strategy_id, row.decision_id)
            )
        ),
        _trace_node(
            batch.target.portfolio_target_id,
            "portfolio_target",
            "Portfolio target",
            batch.target.target_hash,
        ),
        _trace_node(
            batch.risk.risk_decision_id,
            "risk_decision",
            "Risk decision",
            batch.risk.decision_hash,
        ),
        _trace_node(
            batch.plan.order_plan_id,
            "order_plan",
            "Order plan",
            batch.plan.plan_hash,
        ),
    ]
    edges = [
        {
            "from": batch.manifest.batch_id,
            "to": batch.snapshot.snapshot_id,
            "relation": "contains",
        },
        *(
            {
                "from": batch.snapshot.snapshot_id,
                "to": intent.decision_id,
                "relation": "informs",
            }
            for intent in sorted(
                batch.intents, key=lambda row: (row.strategy_id, row.decision_id)
            )
        ),
        *(
            {
                "from": intent.decision_id,
                "to": batch.target.portfolio_target_id,
                "relation": "contributes_to",
            }
            for intent in sorted(
                batch.intents, key=lambda row: (row.strategy_id, row.decision_id)
            )
        ),
        {
            "from": batch.target.portfolio_target_id,
            "to": batch.risk.risk_decision_id,
            "relation": "evaluated_by",
        },
        {
            "from": batch.risk.risk_decision_id,
            "to": batch.plan.order_plan_id,
            "relation": "authorizes",
        },
    ]
    if ledger_snapshot is not None:
        nodes.extend(
            (
                _trace_node(
                    ledger_snapshot.snapshot_hash,
                    "runtime_ledger",
                    "Runtime ledger snapshot",
                    ledger_snapshot.snapshot_hash,
                ),
                _trace_node(
                    str(ledger_snapshot.reconciliation["reconciliation_id"]),
                    "reconciliation",
                    "Three-way reconciliation",
                    str(ledger_snapshot.reconciliation["report_hash"]),
                ),
            )
        )
        edges.extend(
            (
                {
                    "from": batch.plan.order_plan_id,
                    "to": ledger_snapshot.snapshot_hash,
                    "relation": "recorded_in",
                },
                {
                    "from": ledger_snapshot.snapshot_hash,
                    "to": ledger_snapshot.reconciliation["reconciliation_id"],
                    "relation": "verified_by",
                },
            )
        )
    return {
        "authority": _authority(ledger_snapshot),
        "batch": {
            "batch_id": batch.manifest.batch_id,
            "manifest_id": batch.manifest.decision_batch_manifest_id,
            "manifest_hash": batch.manifest.manifest_hash,
            "snapshot_id": batch.snapshot.snapshot_id,
            "created_at": batch.manifest.created_at,
            "orders_authorized": False,
            "href": _trace_href(batch.manifest.batch_id),
        },
        "strategies": strategies,
        "portfolio": {
            "portfolio_target_id": batch.target.portfolio_target_id,
            "target_hash": batch.target.target_hash,
            "decision_ids": decision_ids,
            "target_weights": dict(batch.target.target_weights),
            "approved_target": dict(batch.risk.approved_target),
            "sleeve_contributions": {
                strategy_id: dict(weights)
                for strategy_id, weights in batch.target.sleeve_contributions.items()
            },
            "href": _trace_href(batch.target.portfolio_target_id),
        },
        "risk": {
            "risk_decision_id": batch.risk.risk_decision_id,
            "decision_hash": batch.risk.decision_hash,
            "portfolio_target_id": batch.risk.portfolio_target_id,
            "approved": batch.risk.approved,
            "increase_risk_allowed": batch.risk.increase_risk_allowed,
            "reduce_risk_allowed": batch.risk.reduce_risk_allowed,
            "adjustments": list(batch.risk.adjustments),
            "violations": list(batch.risk.violations),
            "href": _trace_href(batch.risk.risk_decision_id),
        },
        "order_plan": {
            "order_plan_id": batch.plan.order_plan_id,
            "plan_hash": batch.plan.plan_hash,
            "risk_decision_id": batch.plan.risk_decision_id,
            "executable": batch.plan.executable,
            "blockers": list(batch.plan.blockers),
            "order_ids": sorted(order.client_order_id for order in batch.plan.orders),
            "cancellation_ids": sorted(
                cancellation.cancellation_id
                for cancellation in batch.plan.cancellations
            ),
            "href": _trace_href(batch.plan.order_plan_id),
        },
        "trace": {"nodes": nodes, "edges": edges},
    }


def _latest_recovery_status(
    ledger_snapshot: RuntimeLedgerSnapshot,
) -> str:
    if not ledger_snapshot.recoveries:
        return "none"
    return (
        "passed"
        if ledger_snapshot.recoveries[-1]["risk_increase_allowed"]
        else "blocked"
    )


def _orders_payload(
    ledger_snapshot: RuntimeLedgerSnapshot | None,
) -> dict[str, object]:
    if ledger_snapshot is None:
        return {
            "authority": _authority(None),
            "summary": {
                "status": "unavailable_until_phase_b_ledger",
                "total_order_count": None,
                "open_order_count": None,
                "unresolved_order_count": None,
                "partial_fill_count": None,
                "rejected_count": None,
                "protective_order_count": None,
                "fill_count": None,
                "fill_quantity": None,
                "fill_notional": None,
                "fill_fees_by_asset": None,
                "latest_recovery_status": None,
                "unavailable_fields": ["order_latency", "slippage"],
            },
            "orders": [],
            "fills": [],
        }
    fills_by_order: dict[str, list[Mapping[str, Any]]] = {}
    for fill in ledger_snapshot.fills:
        fills_by_order.setdefault(str(fill["client_order_id"]), []).append(fill)
    rows: list[dict[str, object]] = []
    for order in ledger_snapshot.orders:
        order_fills = fills_by_order.get(str(order["client_order_id"]), [])
        fees: dict[str, float] = {}
        for fill in order_fills:
            asset = str(fill["fee_asset"])
            fees[asset] = fees.get(asset, 0.0) + float(fill["fee"])
        planned = order["planned_quantity"]
        executed = float(order["executed_quantity"])
        rows.append(
            {
                "client_order_id": order["client_order_id"],
                "batch_id": order["batch_id"],
                "symbol": order["symbol"],
                "side": order["side"],
                "phase": order["phase"],
                "order_type": order["order_type"],
                "status": order["status"],
                "planned_quantity": planned,
                "executed_quantity": executed,
                "remaining_quantity": (
                    None
                    if planned is None
                    else max(0.0, float(planned) - executed)
                ),
                "fill_count": len(order_fills),
                "fill_quantity": sum(float(fill["quantity"]) for fill in order_fills),
                "fill_notional": sum(
                    float(fill["quantity"]) * float(fill["price"])
                    for fill in order_fills
                ),
                "fill_fees_by_asset": dict(sorted(fees.items())),
                "exchange_order_id": order["exchange_order_id"],
                "average_price": order["average_price"],
                "reduce_only": order["reduce_only"],
                "close_position": order["close_position"],
                "limit_price": order["limit_price"],
                "stop_price": order["stop_price"],
                "last_transition_at": order["last_transition_at"],
                "latest_reason": order["latest_reason"],
                "plan_spec_hash": order["plan_spec_hash"],
                "last_observation_hash": order["last_observation_hash"],
            }
        )
    total_fees: dict[str, float] = {}
    for row in rows:
        for asset, amount in row["fill_fees_by_asset"].items():
            total_fees[asset] = total_fees.get(asset, 0.0) + float(amount)
    open_statuses = {"SUBMITTING", "ACKNOWLEDGED", "PARTIALLY_FILLED", "UNKNOWN"}
    return {
        "authority": _authority(ledger_snapshot),
        "summary": {
            "status": "available",
            "total_order_count": len(rows),
            "open_order_count": sum(row["status"] in open_statuses for row in rows),
            "unresolved_order_count": len(ledger_snapshot.unresolved_order_ids),
            "partial_fill_count": sum(
                row["status"] == "PARTIALLY_FILLED" for row in rows
            ),
            "rejected_count": sum(row["status"] == "REJECTED" for row in rows),
            "protective_order_count": sum(
                row["phase"] == "protective" for row in rows
            ),
            "fill_count": sum(int(row["fill_count"]) for row in rows),
            "fill_quantity": sum(float(row["fill_quantity"]) for row in rows),
            "fill_notional": sum(float(row["fill_notional"]) for row in rows),
            "fill_fees_by_asset": dict(sorted(total_fees.items())),
            "latest_recovery_status": _latest_recovery_status(ledger_snapshot),
            "unavailable_fields": ["order_latency", "slippage"],
        },
        "orders": rows,
        "fills": [dict(fill) for fill in ledger_snapshot.fills],
    }


def _risk_payload(
    batch: VerifiedDecisionBatch,
    ledger_snapshot: RuntimeLedgerSnapshot | None,
) -> dict[str, object]:
    decision = {
        "risk_decision_id": batch.risk.risk_decision_id,
        "approved": batch.risk.approved,
        "increase_risk_allowed": batch.risk.increase_risk_allowed,
        "reduce_risk_allowed": batch.risk.reduce_risk_allowed,
        "adjustments": list(batch.risk.adjustments),
        "violations": list(batch.risk.violations),
        "blockers": list(batch.plan.blockers),
    }
    if ledger_snapshot is None:
        return {
            "authority": _authority(None),
            "decision": decision,
            "runtime": _ledger_unavailable(),
        }
    reconciliation = ledger_snapshot.reconciliation
    nav = ledger_snapshot.nav
    reasons: list[str] = []
    if not batch.risk.increase_risk_allowed:
        reasons.append("decision_risk_increase_blocked")
    if ledger_snapshot.unresolved_order_ids:
        reasons.append("unresolved_order_states")
    if not reconciliation["risk_increase_allowed"]:
        reasons.append("reconciliation_risk_increase_blocked")
    if reconciliation["halt_required"]:
        reasons.append("reconciliation_halt_required")
    if not nav["passed"]:
        reasons.append("accounting_identity_failed")
    protective_counts: dict[str, int] = {}
    for order in ledger_snapshot.orders:
        if order["phase"] == "protective":
            status = str(order["status"])
            protective_counts[status] = protective_counts.get(status, 0) + 1
    cash_counts: dict[str, int] = {}
    cash_amounts: dict[str, float] = {}
    for event in ledger_snapshot.cash_events:
        event_type = str(event["event_type"])
        cash_counts[event_type] = cash_counts.get(event_type, 0) + 1
        cash_amounts[event_type] = cash_amounts.get(event_type, 0.0) + float(
            event["amount"]
        )
    return {
        "authority": _authority(ledger_snapshot),
        "decision": decision,
        "runtime": {
            "status": "available",
            "source": "runtime_ledger",
            "values": {
                "gate_status": "block" if reasons else "pass",
                "reason_codes": reasons,
                "reconciliation": {
                    "reconciliation_id": reconciliation["reconciliation_id"],
                    "passed": reconciliation["passed"],
                    "risk_increase_allowed": reconciliation[
                        "risk_increase_allowed"
                    ],
                    "halt_required": reconciliation["halt_required"],
                    "blockers": list(reconciliation["blockers"]),
                    "position_differences": dict(
                        reconciliation["position_differences"]
                    ),
                    "equity_residual": reconciliation["equity_residual"],
                    "equity_residual_tolerance": reconciliation[
                        "equity_residual_tolerance"
                    ],
                },
                "accounting": {
                    "nav_mark_id": nav["nav_mark_id"],
                    "mark_hash": nav["mark_hash"],
                    "passed": nav["passed"],
                    "residual": nav["residual"],
                    "residual_tolerance": nav["residual_tolerance"],
                    "funding": nav["funding"],
                    "fees": nav["fees"],
                    "transfers": nav["transfers"],
                },
                "protective_order_status_counts": dict(
                    sorted(protective_counts.items())
                ),
                "cash_event_counts": dict(sorted(cash_counts.items())),
                "cash_event_amounts": dict(sorted(cash_amounts.items())),
            },
        },
    }


def _system_payload(
    ledger_snapshot: RuntimeLedgerSnapshot | None,
    system_health: SystemHealthSnapshot | None,
) -> dict[str, object]:
    unavailable_fields = (
        ["backup", "clock", "disk", "operations", "service"]
        if system_health is None
        else []
    )
    health_value = (
        {
            "status": "unavailable_until_health_observation",
            "source": "system_health",
            "values": None,
        }
        if system_health is None
        else {
            "status": "available",
            "source": "system_health",
            "values": system_health.as_dict(),
        }
    )
    health_reasons = (
        ["system_health_observation_missing"]
        if system_health is None
        else [
            f"health_{row['component']}_{row['status']}"
            for row in system_health.observations
            if row["status"] != "healthy"
        ]
    )
    if ledger_snapshot is None:
        return {
            "authority": _authority(None),
            "summary": {
                "status": "unavailable_until_phase_b_ledger",
                "reason_codes": health_reasons,
                "unavailable_fields": unavailable_fields,
            },
            "ledger": _ledger_unavailable(),
            "health": health_value,
        }
    reconciliation = ledger_snapshot.reconciliation
    reasons: list[str] = []
    if ledger_snapshot.unresolved_order_ids:
        reasons.append("recoverable_order_states_present")
    if not reconciliation["passed"]:
        reasons.append("reconciliation_failed")
    if reconciliation["halt_required"]:
        reasons.append("reconciliation_halt_required")
    if not ledger_snapshot.nav["passed"]:
        reasons.append("nav_accounting_identity_failed")
    reasons.extend(health_reasons)
    status = (
        "halt_required"
        if reconciliation["halt_required"]
        or ledger_snapshot.unresolved_order_ids
        or (system_health is not None and system_health.status == "unavailable")
        else "attention_required"
        if not reconciliation["passed"]
        or not ledger_snapshot.nav["passed"]
        or system_health is None
        or system_health.status == "degraded"
        else "healthy"
    )
    return {
        "authority": _authority(ledger_snapshot),
        "summary": {
            "status": status,
            "reason_codes": reasons,
            "unavailable_fields": unavailable_fields,
        },
        "ledger": {
            "status": "available",
            "source": "runtime_ledger",
            "values": {
                "schema_version": ledger_snapshot.schema_version,
                "snapshot_hash": ledger_snapshot.snapshot_hash,
                "captured_at": ledger_snapshot.captured_at,
                "source_updated_at": ledger_snapshot.source_updated_at,
                "integrity_status": "verified",
                "audit_chain_status": "verified",
                "audit_last_hash": ledger_snapshot.audit_last_hash,
                "audit_row_count": ledger_snapshot.audit_row_count,
                "reconciliation_id": reconciliation["reconciliation_id"],
                "reconciliation_passed": reconciliation["passed"],
                "halt_required": reconciliation["halt_required"],
                "recoverable_order_count": len(
                    ledger_snapshot.unresolved_order_ids
                ),
                "recovery_report_count": len(ledger_snapshot.recoveries),
                "latest_recovery_status": _latest_recovery_status(
                    ledger_snapshot
                ),
                "nav_accounting_passed": ledger_snapshot.nav["passed"],
            },
        },
        "health": health_value,
    }


def _strategy_payload(
    batch: VerifiedDecisionBatch,
    registry: StrategyRegistry,
    ledger_snapshot: RuntimeLedgerSnapshot | None,
) -> dict[str, object]:
    intents = {intent.strategy_id: intent for intent in batch.intents}
    sleeves = batch.target.sleeve_contributions
    rows: list[dict[str, object]] = []
    for entry in registry.entries:
        intent = intents.get(entry.strategy_id)
        rows.append(
            {
                "strategy_id": entry.strategy_id,
                "strategy_version": entry.strategy_version,
                "strategy_kind": entry.strategy_kind,
                "promotion_status": entry.promotion_status,
                "registry_entry_id": entry.registry_entry_id,
                "strategy_contract_hash": entry.strategy_contract_hash,
                "maximum_gross": entry.maximum_gross,
                "maximum_stress_loss_fraction": entry.maximum_stress_loss_fraction,
                "promotion_evidence_present": entry.promotion_artifact_hash is not None,
                "owner_authorization_present": entry.owner_authorization_hash is not None,
                "latest_decision": None
                if intent is None
                else {
                    "decision_id": intent.decision_id,
                    "intent_hash": intent.intent_hash,
                    "decision_time": intent.decision_time,
                    "reason_codes": list(intent.reason_codes),
                    "standalone_target": dict(intent.target_weights),
                    "standalone_target_gross": _gross(intent.target_weights),
                    "portfolio_sleeve": dict(sleeves[entry.strategy_id]),
                    "target_stress_loss_fraction": intent.target_stress_loss_fraction,
                },
                "nav": (
                    _ledger_unavailable()
                    if ledger_snapshot is None
                    else {
                        "status": "available",
                        "source": "runtime_ledger",
                        "values": {
                            "scope": "portfolio",
                            "nav_mark_id": ledger_snapshot.nav["nav_mark_id"],
                            "mark_hash": ledger_snapshot.nav["mark_hash"],
                            "marked_at": ledger_snapshot.nav["marked_at"],
                            "signal_nav": ledger_snapshot.nav["signal_nav"],
                            "standalone_executable_nav": ledger_snapshot.nav[
                                "standalone_executable_nav"
                            ],
                        },
                    }
                ),
            }
        )
    return {"authority": _authority(ledger_snapshot), "strategies": rows}


def _readiness_payload(
    batch: VerifiedDecisionBatch,
    registry: StrategyRegistry,
    *,
    stale: bool,
    ledger_snapshot: RuntimeLedgerSnapshot | None,
    system_health: SystemHealthSnapshot | None,
    blocked_runtime_observation: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    intent_ids = {intent.strategy_id for intent in batch.intents}
    gates = [
        {
            "gate": "verified_decision_batch",
            "status": "pass",
            "detail": "complete_manifest_and_lineage_verified",
        },
        {
            "gate": "strategy_registry",
            "status": "pass",
            "detail": "registry_and_current_intents_verified",
        },
        *(
            [
                {
                    "gate": "runtime_ledger",
                    "status": "unavailable",
                    "detail": "runtime_ledger_snapshot_not_supplied",
                },
                {
                    "gate": "order_state_recovery",
                    "status": "unavailable",
                    "detail": "runtime_ledger_snapshot_not_supplied",
                },
                {
                    "gate": "three_way_reconciliation",
                    "status": "unavailable",
                    "detail": "runtime_ledger_snapshot_not_supplied",
                },
            ]
            if ledger_snapshot is None
            else [
                {
                    "gate": "runtime_ledger",
                    "status": "pass",
                    "detail": "snapshot_and_audit_chain_verified",
                },
                {
                    "gate": "order_state_recovery",
                    "status": (
                        "block"
                        if ledger_snapshot.unresolved_order_ids
                        else "pass"
                    ),
                    "detail": (
                        "unresolved_order_states:"
                        + ",".join(ledger_snapshot.unresolved_order_ids)
                        if ledger_snapshot.unresolved_order_ids
                        else "no_recoverable_order_states"
                    ),
                },
                {
                    "gate": "three_way_reconciliation",
                    "status": (
                        "pass"
                        if ledger_snapshot.reconciliation["passed"]
                        and not ledger_snapshot.reconciliation["halt_required"]
                        and ledger_snapshot.nav["passed"]
                        else "block"
                    ),
                    "detail": (
                        "latest_three_way_reconciliation_passed"
                        if ledger_snapshot.reconciliation["passed"]
                        and not ledger_snapshot.reconciliation["halt_required"]
                        and ledger_snapshot.nav["passed"]
                        else "latest_three_way_reconciliation_failed:"
                        + (
                            ",".join(ledger_snapshot.reconciliation["blockers"])
                            or "nav_accounting_identity_failed"
                        )
                    ),
                },
            ]
        ),
        {
            "gate": "live_orders_allowed",
            "status": "block",
            "detail": "dashboard_read_models_never_authorize_orders",
        },
    ]
    strategies = [
        {
            "strategy_id": entry.strategy_id,
            "strategy_version": entry.strategy_version,
            "promotion_status": entry.promotion_status,
            "current_batch_decision_present": entry.strategy_id in intent_ids,
            "promotion_evidence_present": entry.promotion_artifact_hash is not None,
            "owner_authorization_present": entry.owner_authorization_hash is not None,
            "live_orders_allowed": False,
            "execution_blockers": (
                list(blocked_runtime_observation["blockers"])
                if blocked_runtime_observation is not None
                and blocked_runtime_observation.get("strategy_id")
                == entry.strategy_id
                else []
            ),
        }
        for entry in registry.entries
    ]
    runtime_blocked = bool(
        ledger_snapshot is not None
        and (
            ledger_snapshot.unresolved_order_ids
            or not ledger_snapshot.reconciliation["passed"]
            or ledger_snapshot.reconciliation["halt_required"]
            or not ledger_snapshot.nav["passed"]
        )
    )
    registry_authorized = any(
        entry.promotion_status in {"minimal_live", "scaled_live"}
        and entry.owner_authorization_hash is not None
        for entry in registry.entries
    )
    if ledger_snapshot is None:
        evidence_status = "unavailable"
        evidence_detail = "runtime_ledger_snapshot_not_supplied"
    elif ledger_snapshot.fills:
        evidence_status = "complete"
        evidence_detail = "fills_verified"
    elif not batch.plan.orders and not ledger_snapshot.orders:
        evidence_status = "complete"
        evidence_detail = "no_order_expected"
    else:
        evidence_status = "incomplete"
        evidence_detail = "orders_expected_but_missing"
    operational_status = (
        "unavailable"
        if system_health is None or system_health.status == "unavailable"
        else "degraded"
        if system_health.status == "degraded"
        else "healthy"
    )
    operations_row = (
        next(
            (
                row
                for row in system_health.observations
                if row["component"] == "operations"
            ),
            None,
        )
        if system_health is not None
        else None
    )
    execution_operations_blocked = bool(
        operations_row is not None
        and operations_row["metrics"]["scope_status"]["execution"]
        == "unavailable"
    )
    trading_status = (
        "blocked"
        if stale or runtime_blocked or execution_operations_blocked
        else "registry_authorized"
        if registry_authorized
        else "disarmed"
    )
    if blocked_runtime_observation is not None:
        for gate in gates:
            if gate["gate"] == "runtime_ledger":
                gate["detail"] = "not_created_for_manual_account_observation"
        trading_status = "disarmed"
        evidence_status = "complete"
        evidence_detail = "read_only_account_observation_verified"
    return {
        "authority": _authority(ledger_snapshot),
        "status": (
            "stale"
            if stale
            else "read_only_observation_ready"
            if blocked_runtime_observation is not None
            else "blocked_phase_b_required" if ledger_snapshot is None
            else "blocked_runtime_state"
            if ledger_snapshot.unresolved_order_ids
            or not ledger_snapshot.reconciliation["passed"]
            or ledger_snapshot.reconciliation["halt_required"]
            or not ledger_snapshot.nav["passed"]
            else "read_model_ready"
        ),
        "axes": {
            "publication_integrity": {
                "status": "pass",
                "detail": "verified_sources_and_read_model_hashes",
                "impact_scopes": ["observation"],
            },
            "observation_state": {
                "status": "stale" if stale else "fresh",
                "detail": (
                    "one_or_more_required_sources_stale"
                    if stale
                    else "required_sources_within_freshness_windows"
                ),
                "impact_scopes": ["observation", "execution"],
            },
            "operational_state": {
                "status": operational_status,
                "detail": (
                    "ops_observer_not_available"
                    if system_health is None
                    else f"ops_observer_{system_health.status}"
                ),
                "impact_scopes": [
                    "execution",
                    "observation",
                    "intelligence",
                    "delivery",
                ],
            },
            "trading_authority": {
                "status": trading_status,
                "detail": (
                    "runtime_or_freshness_gate_blocked"
                    if trading_status == "blocked"
                    else "registry_owner_authorization_present_dashboard_read_only"
                    if trading_status == "registry_authorized"
                    else "no_live_registry_authority_dashboard_read_only"
                ),
                "impact_scopes": ["execution"],
            },
            "evidence_state": {
                "status": evidence_status,
                "detail": evidence_detail,
                "impact_scopes": ["execution", "observation"],
            },
        },
        "gates": gates,
        "strategies": strategies,
    }


def _alerts_payload(
    snapshot: NotificationSnapshot | None,
) -> dict[str, object]:
    if snapshot is None:
        return {
            "authority": {
                "notifications": "unavailable_until_phase_c_notification_store"
            },
            "summary": {
                "status": "unavailable_until_phase_c_notification_store",
                "open_alert_count": None,
                "resolved_alert_count": None,
                "severity_counts": None,
                "historical_severity_counts": None,
                "delivery_state_counts": None,
                "monitoring_observed_at": None,
                "content_updated_at": None,
                "audit_last_hash": None,
                "audit_row_count": None,
            },
            "alerts": [],
        }
    return {
        "authority": {"notifications": "notification_store"},
        "summary": {
            "status": "available",
            "open_alert_count": snapshot.open_alert_count,
            "resolved_alert_count": snapshot.resolved_alert_count,
            "severity_counts": dict(snapshot.severity_counts),
            "historical_severity_counts": dict(
                snapshot.historical_severity_counts
            ),
            "delivery_state_counts": dict(snapshot.delivery_state_counts),
            "monitoring_observed_at": snapshot.observed_at,
            "content_updated_at": snapshot.content_updated_at,
            "audit_last_hash": snapshot.audit_last_hash,
            "audit_row_count": snapshot.audit_row_count,
        },
        "alerts": [dict(row) for row in snapshot.alerts],
    }


def _validate_reports_payload(value: Mapping[str, object]) -> None:
    authority = _mapping(value["authority"], name="dashboard_reports_authority")
    _exact_keys(authority, {"reports"}, name="dashboard_reports_authority")
    summary = _mapping(value["summary"], name="dashboard_reports_summary")
    _exact_keys(
        summary,
        {"status", "brief_id", "brief_hash", "report_date", "brief_status"},
        name="dashboard_reports_summary",
    )
    if authority["reports"] == "unavailable_until_phase_c_daily_brief":
        if summary != {
            "status": "unavailable_until_phase_c_daily_brief",
            "brief_id": None,
            "brief_hash": None,
            "report_date": None,
            "brief_status": None,
        } or value["brief"] is not None:
            raise DashboardReadModelError("dashboard_reports_unavailable_invalid")
        return
    if authority["reports"] != "deterministic_daily_brief":
        raise DashboardReadModelError("dashboard_reports_authority_invalid")
    if summary["status"] != "available":
        raise DashboardReadModelError("dashboard_reports_status_invalid")
    brief_value = _mapping(value["brief"], name="dashboard_reports_brief")
    try:
        brief = daily_brief_from_dict(brief_value)
    except DailyBriefError as exc:
        raise DashboardReadModelError(f"dashboard_daily_brief_invalid:{exc}") from exc
    if (
        summary["brief_id"] != brief.brief_id
        or summary["brief_hash"] != brief.brief_hash
        or summary["report_date"] != brief.report_date
        or summary["brief_status"] != brief.status
    ):
        raise DashboardReadModelError("dashboard_reports_summary_mismatch")


def _reports_payload(brief: DailyBrief | None) -> dict[str, object]:
    if brief is None:
        return {
            "authority": {
                "reports": "unavailable_until_phase_c_daily_brief",
            },
            "summary": {
                "status": "unavailable_until_phase_c_daily_brief",
                "brief_id": None,
                "brief_hash": None,
                "report_date": None,
                "brief_status": None,
            },
            "brief": None,
        }
    return {
        "authority": {"reports": "deterministic_daily_brief"},
        "summary": {
            "status": "available",
            "brief_id": brief.brief_id,
            "brief_hash": brief.brief_hash,
            "report_date": brief.report_date,
            "brief_status": brief.status,
        },
        "brief": brief.as_dict(),
    }


def _validate_intelligence_payload(value: Mapping[str, object]) -> None:
    authority = _mapping(
        value["authority"], name="dashboard_intelligence_authority"
    )
    _exact_keys(
        authority,
        {"intelligence"},
        name="dashboard_intelligence_authority",
    )
    summary = _mapping(value["summary"], name="dashboard_intelligence_summary")
    _exact_keys(
        summary,
        {
            "status",
            "report_id",
            "report_hash",
            "report_date",
            "report_status",
            "source_count",
            "proposal_count",
        },
        name="dashboard_intelligence_summary",
    )
    if authority["intelligence"] == "unavailable_until_daily_intelligence":
        if dict(summary) != {
            "status": "unavailable_until_daily_intelligence",
            "report_id": None,
            "report_hash": None,
            "report_date": None,
            "report_status": None,
            "source_count": 0,
            "proposal_count": 0,
        } or value["report"] is not None:
            raise DashboardReadModelError(
                "dashboard_intelligence_unavailable_invalid"
            )
        return
    if authority["intelligence"] != "daily_intelligence":
        raise DashboardReadModelError("dashboard_intelligence_authority_invalid")
    report_value = _mapping(value["report"], name="dashboard_intelligence_report")
    try:
        report = daily_intelligence_from_dict(report_value)
    except IntelligenceContractError as exc:
        raise DashboardReadModelError(
            f"dashboard_intelligence_report_invalid:{exc}"
        ) from exc
    expected = {
        "status": "available",
        "report_id": report.report_id,
        "report_hash": report.report_hash,
        "report_date": report.report_date,
        "report_status": report.status,
        "source_count": len(report.sources),
        "proposal_count": len(report.research_proposals),
    }
    if dict(summary) != expected:
        raise DashboardReadModelError("dashboard_intelligence_summary_mismatch")


def _intelligence_payload(
    report: DailyIntelligenceReport | None,
) -> dict[str, object]:
    if report is None:
        return {
            "authority": {
                "intelligence": "unavailable_until_daily_intelligence"
            },
            "summary": {
                "status": "unavailable_until_daily_intelligence",
                "report_id": None,
                "report_hash": None,
                "report_date": None,
                "report_status": None,
                "source_count": 0,
                "proposal_count": 0,
            },
            "report": None,
        }
    report.validate()
    return {
        "authority": {"intelligence": "daily_intelligence"},
        "summary": {
            "status": "available",
            "report_id": report.report_id,
            "report_hash": report.report_hash,
            "report_date": report.report_date,
            "report_status": report.status,
            "source_count": len(report.sources),
            "proposal_count": len(report.research_proposals),
        },
        "report": report.as_dict(),
    }


@dataclass(frozen=True)
class DashboardReadModelSet:
    overview: DashboardReadModel
    positions: DashboardReadModel
    orders: DashboardReadModel
    strategies: DashboardReadModel
    decisions: DashboardReadModel
    risk: DashboardReadModel
    readiness: DashboardReadModel
    system: DashboardReadModel
    alerts: DashboardReadModel
    reports: DashboardReadModel
    intelligence: DashboardReadModel

    def models(self) -> tuple[DashboardReadModel, ...]:
        return (
            self.overview,
            self.positions,
            self.orders,
            self.strategies,
            self.decisions,
            self.risk,
            self.readiness,
            self.system,
            self.alerts,
            self.reports,
            self.intelligence,
        )

    def validate(self) -> None:
        models = self.models()
        if tuple(model.read_model_type for model in models) != READ_MODEL_TYPES:
            raise DashboardReadModelError("dashboard_read_model_set_types_invalid")
        for model in models:
            model.validate()
        if any(model.generated_at != models[0].generated_at for model in models[1:]):
            raise DashboardReadModelError(
                "dashboard_read_model_set_generated_at_mismatch"
            )
        if self.system.generated_at != self.overview.generated_at:
            raise DashboardReadModelError(
                "dashboard_read_model_set_generation_mismatch"
            )
        if self.alerts.generated_at != self.overview.generated_at:
            raise DashboardReadModelError(
                "dashboard_read_model_set_generation_mismatch"
            )
        if self.reports.generated_at != self.overview.generated_at:
            raise DashboardReadModelError(
                "dashboard_read_model_set_generation_mismatch"
            )
        if self.intelligence.generated_at != self.overview.generated_at:
            raise DashboardReadModelError(
                "dashboard_read_model_set_generation_mismatch"
            )


def build_dashboard_v1(
    batch: VerifiedDecisionBatch,
    registry: StrategyRegistry,
    *,
    generated_at: str,
    evaluated_at: str | None = None,
    stale_after_seconds: int = 900,
    ledger_snapshot: RuntimeLedgerSnapshot | None = None,
    notification_snapshot: NotificationSnapshot | None = None,
    daily_brief_notification_snapshot: NotificationSnapshot | None = None,
    alert_stale_after_seconds: int | None = None,
    daily_brief: DailyBrief | None = None,
    report_stale_after_seconds: int | None = None,
    daily_intelligence: DailyIntelligenceReport | None = None,
    intelligence_stale_after_seconds: int | None = None,
    system_health: SystemHealthSnapshot | None = None,
    system_stale_after_seconds: int | None = None,
    blocked_runtime_observation: Mapping[str, Any] | None = None,
) -> DashboardReadModelSet:
    """Build read models from verified decision, governance, and frozen ledger state."""

    source_errors = _source_errors(batch, registry)
    if source_errors:
        raise DashboardReadModelError(
            f"dashboard_sources_invalid:{','.join(source_errors)}"
        )
    if ledger_snapshot is not None:
        if not isinstance(ledger_snapshot, RuntimeLedgerSnapshot):
            raise DashboardReadModelError(
                "dashboard_runtime_ledger_snapshot_required"
            )
        try:
            ledger_snapshot.validate()
        except ValueError as exc:
            raise DashboardReadModelError(
                f"dashboard_runtime_ledger_snapshot_invalid:{exc}"
            ) from exc
        if (
            ledger_snapshot.batch_id != batch.manifest.batch_id
            or ledger_snapshot.manifest_hash != batch.manifest.manifest_hash
            or ledger_snapshot.order_plan_id != batch.plan.order_plan_id
            or ledger_snapshot.plan_hash != batch.plan.plan_hash
        ):
            raise DashboardReadModelError(
                "dashboard_runtime_ledger_snapshot_batch_mismatch"
            )
    if blocked_runtime_observation is not None:
        if (
            blocked_runtime_observation.get("status") != "blocked"
            or blocked_runtime_observation.get("live_orders_allowed") is not False
            or blocked_runtime_observation.get("runtime_ledger_created") is not False
            or not isinstance(blocked_runtime_observation.get("strategy_id"), str)
            or not blocked_runtime_observation["strategy_id"]
            or not is_sha256(blocked_runtime_observation.get("observation_hash"))
        ):
            raise DashboardReadModelError(
                "dashboard_blocked_runtime_observation_invalid"
            )
    if notification_snapshot is not None:
        if not isinstance(notification_snapshot, NotificationSnapshot):
            raise DashboardReadModelError(
                "dashboard_notification_snapshot_required"
            )
        try:
            notification_snapshot.validate()
        except ValueError as exc:
            raise DashboardReadModelError(
                f"dashboard_notification_snapshot_invalid:{exc}"
            ) from exc
    if system_health is not None:
        if not isinstance(system_health, SystemHealthSnapshot):
            raise DashboardReadModelError(
                "dashboard_system_health_snapshot_required"
            )
        try:
            system_health.validate()
        except SystemHealthContractError as exc:
            raise DashboardReadModelError(
                f"dashboard_system_health_snapshot_invalid:{exc}"
            ) from exc
    if daily_brief is not None:
        if ledger_snapshot is None or notification_snapshot is None:
            raise DashboardReadModelError(
                "dashboard_daily_brief_sources_required"
            )
        try:
            validate_daily_brief_sources(
                daily_brief,
                batch,
                registry,
                ledger_snapshot,
                daily_brief_notification_snapshot or notification_snapshot,
            )
        except DailyBriefError as exc:
            raise DashboardReadModelError(
                f"dashboard_daily_brief_invalid:{exc}"
            ) from exc
    if daily_intelligence is not None:
        if not isinstance(daily_intelligence, DailyIntelligenceReport):
            raise DashboardReadModelError(
                "dashboard_daily_intelligence_required"
            )
        try:
            daily_intelligence.validate()
        except IntelligenceContractError as exc:
            raise DashboardReadModelError(
                f"dashboard_daily_intelligence_invalid:{exc}"
            ) from exc
    if (
        not isinstance(stale_after_seconds, int)
        or isinstance(stale_after_seconds, bool)
        or stale_after_seconds < 1
    ):
        raise DashboardReadModelError("dashboard_stale_after_invalid")
    alert_stale_after_seconds = (
        stale_after_seconds
        if alert_stale_after_seconds is None
        else alert_stale_after_seconds
    )
    if (
        not isinstance(alert_stale_after_seconds, int)
        or isinstance(alert_stale_after_seconds, bool)
        or alert_stale_after_seconds < 1
    ):
        raise DashboardReadModelError("dashboard_alert_stale_after_invalid")
    report_stale_after_seconds = (
        stale_after_seconds
        if report_stale_after_seconds is None
        else report_stale_after_seconds
    )
    if (
        not isinstance(report_stale_after_seconds, int)
        or isinstance(report_stale_after_seconds, bool)
        or report_stale_after_seconds < 1
    ):
        raise DashboardReadModelError("dashboard_report_stale_after_invalid")
    intelligence_stale_after_seconds = (
        129_600
        if intelligence_stale_after_seconds is None
        else intelligence_stale_after_seconds
    )
    if (
        not isinstance(intelligence_stale_after_seconds, int)
        or isinstance(intelligence_stale_after_seconds, bool)
        or intelligence_stale_after_seconds < 1
    ):
        raise DashboardReadModelError(
            "dashboard_intelligence_stale_after_invalid"
        )
    system_stale_after_seconds = (
        stale_after_seconds
        if system_stale_after_seconds is None
        else system_stale_after_seconds
    )
    if (
        not isinstance(system_stale_after_seconds, int)
        or isinstance(system_stale_after_seconds, bool)
        or system_stale_after_seconds < 1
    ):
        raise DashboardReadModelError("dashboard_system_stale_after_invalid")
    evaluated_at = evaluated_at or generated_at
    try:
        generated = aware_datetime(generated_at)
        evaluated = aware_datetime(evaluated_at)
        source_times_by_name = (
            {"blocked_runtime_observation": aware_datetime(
                str(blocked_runtime_observation["observed_at"])
            )}
            if blocked_runtime_observation is not None
            else
            {
                "runtime_ledger": aware_datetime(
                    ledger_snapshot.source_updated_at
                )
            }
            if ledger_snapshot is not None
            else {"decision_batch": aware_datetime(batch.manifest.created_at)}
        )
        source_times = tuple(source_times_by_name.values())
        notification_source_time = (
            aware_datetime(notification_snapshot.source_updated_at)
            if notification_snapshot is not None
            else None
        )
        report_source_time = (
            aware_datetime(daily_brief.source_updated_at)
            if daily_brief is not None
            else None
        )
        intelligence_source_time = (
            aware_datetime(daily_intelligence.created_at)
            if daily_intelligence is not None
            else None
        )
        system_source_time = (
            aware_datetime(system_health.source_updated_at)
            if system_health is not None
            else None
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise DashboardReadModelError("dashboard_generation_time_invalid") from exc
    source_updated_at = max(source_times).isoformat()
    if (
        generated < max(source_times)
        or evaluated < generated
        or (
            ledger_snapshot is not None
            and generated < aware_datetime(ledger_snapshot.captured_at)
        )
        or (
            notification_snapshot is not None
            and (
                generated < aware_datetime(notification_snapshot.captured_at)
                or generated < notification_source_time
            )
        )
        or (
            daily_brief is not None
            and (
                generated < aware_datetime(daily_brief.generated_at)
                or generated < report_source_time
            )
        )
        or (
            daily_intelligence is not None
            and generated < intelligence_source_time
        )
        or (
            system_health is not None
            and (
                generated < aware_datetime(system_health.captured_at)
                or generated < system_source_time
            )
        )
    ):
        raise DashboardReadModelError("dashboard_generation_time_order_invalid")
    freshness = _freshness(
        source_updated_at=source_updated_at,
        evaluated_at=evaluated_at,
        stale_after_seconds=stale_after_seconds,
        observed_at=generated_at,
        content_updated_at=source_updated_at,
        sources={
            name: value.isoformat()
            for name, value in source_times_by_name.items()
        },
    )
    source_hashes = {
        "decision_batch_manifest": batch.manifest.manifest_hash,
        "strategy_registry": registry.registry_hash,
        **(
            {"blocked_runtime_observation": blocked_runtime_observation["observation_hash"]}
            if blocked_runtime_observation is not None
            else
            {"runtime_ledger": ledger_snapshot.snapshot_hash}
            if ledger_snapshot is not None
            else {}
        ),
    }
    common = {
        "generated_at": generated_at,
        "data_cutoff": batch.snapshot.data_cutoff,
        "source_hashes": source_hashes,
        "stale_after_seconds": stale_after_seconds,
        "freshness": freshness,
    }
    effective_ledger_snapshot = (
        None if blocked_runtime_observation is not None else ledger_snapshot
    )
    decision_source_updated_at = aware_datetime(
        batch.manifest.created_at
    ).isoformat()
    decision_common = {
        **common,
        "source_hashes": (
            source_hashes
            if blocked_runtime_observation is None
            else {
                "decision_batch_manifest": batch.manifest.manifest_hash,
                "strategy_registry": registry.registry_hash,
            }
        ),
        "freshness": _freshness(
            source_updated_at=decision_source_updated_at,
            evaluated_at=evaluated_at,
            stale_after_seconds=stale_after_seconds,
            observed_at=generated_at,
            content_updated_at=decision_source_updated_at,
            sources={"decision_batch": decision_source_updated_at},
        ),
    }
    if notification_snapshot is None:
        alerts_common = common
    else:
        alerts_common = {
            "generated_at": generated_at,
            "data_cutoff": notification_snapshot.source_updated_at,
            "source_hashes": {
                "notification_store": notification_snapshot.snapshot_hash
            },
            "stale_after_seconds": alert_stale_after_seconds,
            "freshness": _freshness(
                source_updated_at=notification_snapshot.source_updated_at,
                evaluated_at=evaluated_at,
                stale_after_seconds=alert_stale_after_seconds,
                observed_at=notification_snapshot.observed_at,
                content_updated_at=(
                    notification_snapshot.content_updated_at
                    or notification_snapshot.observed_at
                ),
                sources={
                    "notification_monitor": notification_snapshot.observed_at
                },
            ),
        }
    if daily_brief is None:
        reports_common = common
    else:
        reports_common = {
            "generated_at": generated_at,
            "data_cutoff": daily_brief.source_updated_at,
            "source_hashes": {"daily_brief": daily_brief.brief_hash},
            "stale_after_seconds": report_stale_after_seconds,
            "freshness": _freshness(
                source_updated_at=daily_brief.source_updated_at,
                evaluated_at=evaluated_at,
                stale_after_seconds=report_stale_after_seconds,
                observed_at=generated_at,
                content_updated_at=daily_brief.source_updated_at,
                sources={"daily_brief": daily_brief.source_updated_at},
            ),
        }
    if daily_intelligence is None:
        intelligence_common = common
    else:
        intelligence_common = {
            "generated_at": generated_at,
            "data_cutoff": daily_intelligence.created_at,
            "source_hashes": {
                "daily_intelligence": daily_intelligence.report_hash
            },
            "stale_after_seconds": intelligence_stale_after_seconds,
            "freshness": _freshness(
                source_updated_at=daily_intelligence.created_at,
                evaluated_at=evaluated_at,
                stale_after_seconds=intelligence_stale_after_seconds,
                observed_at=generated_at,
                content_updated_at=daily_intelligence.created_at,
                sources={"daily_intelligence": daily_intelligence.created_at},
            ),
        }
    if system_health is None:
        system_common = common
    else:
        system_source_hashes = dict(source_hashes) | {
            "system_health": system_health.snapshot_hash
        }
        system_common = {
            "generated_at": generated_at,
            "data_cutoff": system_health.source_updated_at,
            "source_hashes": system_source_hashes,
            "stale_after_seconds": system_stale_after_seconds,
            "freshness": _freshness(
                source_updated_at=system_health.source_updated_at,
                evaluated_at=evaluated_at,
                stale_after_seconds=system_stale_after_seconds,
                observed_at=system_health.captured_at,
                content_updated_at=system_health.source_updated_at,
                sources={"ops_observer": system_health.source_updated_at},
            ),
        }
    models = DashboardReadModelSet(
        overview=DashboardReadModel.create(
            read_model_type="overview",
            payload=_overview_payload(
                batch,
                effective_ledger_snapshot,
                blocked_runtime_observation,
            ),
            **common,
        ),
        positions=DashboardReadModel.create(
            read_model_type="positions",
            payload=_positions_payload(batch, effective_ledger_snapshot),
            **common,
        ),
        orders=DashboardReadModel.create(
            read_model_type="orders",
            payload=_orders_payload(effective_ledger_snapshot),
            **common,
        ),
        strategies=DashboardReadModel.create(
            read_model_type="strategies",
            payload=_strategy_payload(batch, registry, effective_ledger_snapshot),
            **decision_common,
        ),
        decisions=DashboardReadModel.create(
            read_model_type="decisions",
            payload=_decisions_payload(batch, effective_ledger_snapshot),
            **decision_common,
        ),
        risk=DashboardReadModel.create(
            read_model_type="risk",
            payload=_risk_payload(batch, effective_ledger_snapshot),
            **common,
        ),
        readiness=DashboardReadModel.create(
            read_model_type="readiness",
            payload=_readiness_payload(
                batch,
                registry,
                stale=freshness["status"] == "stale",
                ledger_snapshot=effective_ledger_snapshot,
                system_health=system_health,
                blocked_runtime_observation=blocked_runtime_observation,
            ),
            **common,
        ),
        system=DashboardReadModel.create(
            read_model_type="system",
            payload=_system_payload(effective_ledger_snapshot, system_health),
            **system_common,
        ),
        alerts=DashboardReadModel.create(
            read_model_type="alerts",
            payload=_alerts_payload(notification_snapshot),
            **alerts_common,
        ),
        reports=DashboardReadModel.create(
            read_model_type="reports",
            payload=_reports_payload(daily_brief),
            **reports_common,
        ),
        intelligence=DashboardReadModel.create(
            read_model_type="intelligence",
            payload=_intelligence_payload(daily_intelligence),
            **intelligence_common,
        ),
    )
    models.validate()
    return models


@dataclass(frozen=True)
class DashboardPublication:
    schema_version: int
    publication_id: str
    generated_at: str
    data_cutoff: str
    source_hashes: Mapping[str, str]
    read_models: Mapping[str, Mapping[str, str]]
    publication_hash: str

    @classmethod
    def create(cls, models: DashboardReadModelSet) -> DashboardPublication:
        models.validate()
        core = {
            "schema_version": DASHBOARD_SCHEMA_VERSION,
            "generated_at": models.overview.generated_at,
            "data_cutoff": models.overview.data_cutoff,
            "source_hashes": dict(models.overview.source_hashes),
            "read_models": {
                model.read_model_type: {
                    "file_name": _READ_MODEL_FILES[model.read_model_type],
                    "read_model_id": model.read_model_id,
                    "read_model_hash": model.read_model_hash,
                }
                for model in models.models()
            },
        }
        publication_hash = canonical_hash(core)
        publication = cls(
            **core,
            publication_id=trace_id(
                "dashboard_publication",
                {"publication_hash": publication_hash},
            ),
            publication_hash=publication_hash,
        )
        publication.validate(models=models)
        return publication

    def _core(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "data_cutoff": self.data_cutoff,
            "source_hashes": dict(self.source_hashes),
            "read_models": {
                key: dict(value) for key, value in self.read_models.items()
            },
        }

    def validate(self, *, models: DashboardReadModelSet | None = None) -> None:
        if self.schema_version != DASHBOARD_SCHEMA_VERSION:
            raise DashboardReadModelError("dashboard_publication_schema_invalid")
        if not _valid_source_hashes(self.source_hashes):
            raise DashboardReadModelError("dashboard_publication_sources_invalid")
        if set(self.read_models) != set(READ_MODEL_TYPES):
            raise DashboardReadModelError("dashboard_publication_models_invalid")
        for read_model_type, row_value in self.read_models.items():
            row = _mapping(row_value, name="dashboard_publication_model")
            _exact_keys(
                row,
                {"file_name", "read_model_id", "read_model_hash"},
                name="dashboard_publication_model",
            )
            if row["file_name"] != _READ_MODEL_FILES[read_model_type] or not all(
                is_sha256(row[name]) for name in ("read_model_id", "read_model_hash")
            ):
                raise DashboardReadModelError("dashboard_publication_model_invalid")
        expected_hash = canonical_hash(self._core())
        if self.publication_hash != expected_hash:
            raise DashboardReadModelError("dashboard_publication_hash_invalid")
        expected_id = trace_id(
            "dashboard_publication",
            {"publication_hash": expected_hash},
        )
        if self.publication_id != expected_id:
            raise DashboardReadModelError("dashboard_publication_id_invalid")
        if models is not None:
            models.validate()
            if self.generated_at != models.overview.generated_at:
                raise DashboardReadModelError("dashboard_publication_time_mismatch")
            if self.data_cutoff != models.overview.data_cutoff:
                raise DashboardReadModelError("dashboard_publication_cutoff_mismatch")
            if dict(self.source_hashes) != dict(models.overview.source_hashes):
                raise DashboardReadModelError("dashboard_publication_source_mismatch")
            for model in models.models():
                row = self.read_models[model.read_model_type]
                if row["read_model_id"] != model.read_model_id or row[
                    "read_model_hash"
                ] != model.read_model_hash:
                    raise DashboardReadModelError(
                        "dashboard_publication_read_model_mismatch"
                    )

    def as_dict(self) -> dict[str, object]:
        return self._core() | {
            "publication_id": self.publication_id,
            "publication_hash": self.publication_hash,
        }


def _write_release_file(path: Path, value: Mapping[str, Any]) -> None:
    raw = _canonical_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary, path)
        if path.read_bytes() != raw:
            raise DashboardReadModelError("dashboard_publish_readback_mismatch")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_json(raw: bytes, *, name: str) -> Mapping[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DashboardReadModelError(f"{name}_duplicate_key:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicate)
    except DashboardReadModelError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DashboardReadModelError(f"{name}_json_invalid") from exc
    mapping = _mapping(value, name=name)
    if _canonical_bytes(mapping) != raw:
        raise DashboardReadModelError(f"{name}_not_canonical")
    return mapping


def _read_model_from_dict(value: Mapping[str, Any]) -> DashboardReadModel:
    _exact_keys(
        value,
        {
            "schema_version",
            "read_model_type",
            "read_model_id",
            "generated_at",
            "data_cutoff",
            "source_hashes",
            "stale_after_seconds",
            "freshness",
            "payload",
            "read_model_hash",
        },
        name="dashboard_read_model",
    )
    model = DashboardReadModel(
        schema_version=value["schema_version"],
        read_model_type=value["read_model_type"],
        read_model_id=value["read_model_id"],
        generated_at=value["generated_at"],
        data_cutoff=value["data_cutoff"],
        source_hashes=_mapping(value["source_hashes"], name="dashboard_source_hashes"),
        stale_after_seconds=value["stale_after_seconds"],
        freshness=_mapping(value["freshness"], name="dashboard_freshness"),
        payload=_mapping(value["payload"], name="dashboard_payload"),
        read_model_hash=value["read_model_hash"],
    )
    model.validate()
    return model


def _publication_from_dict(value: Mapping[str, Any]) -> DashboardPublication:
    _exact_keys(
        value,
        {
            "schema_version",
            "publication_id",
            "generated_at",
            "data_cutoff",
            "source_hashes",
            "read_models",
            "publication_hash",
        },
        name="dashboard_publication",
    )
    publication = DashboardPublication(
        schema_version=value["schema_version"],
        publication_id=value["publication_id"],
        generated_at=value["generated_at"],
        data_cutoff=value["data_cutoff"],
        source_hashes=_mapping(value["source_hashes"], name="dashboard_publication_sources"),
        read_models=_mapping(value["read_models"], name="dashboard_publication_models"),
        publication_hash=value["publication_hash"],
    )
    publication.validate()
    return publication


def _read_release(directory: Path) -> tuple[DashboardReadModelSet, DashboardPublication]:
    if directory.is_symlink() or not directory.is_dir():
        raise DashboardReadModelError("dashboard_release_directory_invalid")
    if stat.S_IMODE(os.stat(directory, follow_symlinks=False).st_mode) != 0o755:
        raise DashboardReadModelError("dashboard_release_directory_mode_invalid")
    expected_files = {*_READ_MODEL_FILES.values(), _PUBLICATION_FILE}
    actual_files = {path.name for path in directory.iterdir()}
    if actual_files != expected_files:
        raise DashboardReadModelError("dashboard_release_files_mismatch")
    loaded: dict[str, DashboardReadModel] = {}
    for read_model_type, file_name in _READ_MODEL_FILES.items():
        path = directory / file_name
        if path.is_symlink() or not path.is_file():
            raise DashboardReadModelError("dashboard_release_file_invalid")
        if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) != 0o644:
            raise DashboardReadModelError("dashboard_release_file_mode_invalid")
        model = _read_model_from_dict(
            _parse_json(path.read_bytes(), name=f"dashboard_{read_model_type}")
        )
        if model.read_model_type != read_model_type:
            raise DashboardReadModelError("dashboard_release_type_mismatch")
        loaded[read_model_type] = model
    publication_path = directory / _PUBLICATION_FILE
    if publication_path.is_symlink() or not publication_path.is_file():
        raise DashboardReadModelError("dashboard_publication_file_invalid")
    if stat.S_IMODE(os.stat(publication_path, follow_symlinks=False).st_mode) != 0o644:
        raise DashboardReadModelError("dashboard_publication_file_mode_invalid")
    publication = _publication_from_dict(
        _parse_json(publication_path.read_bytes(), name="dashboard_publication")
    )
    models = DashboardReadModelSet(
        overview=loaded["overview"],
        positions=loaded["positions"],
        orders=loaded["orders"],
        strategies=loaded["strategies"],
        decisions=loaded["decisions"],
        risk=loaded["risk"],
        readiness=loaded["readiness"],
        system=loaded["system"],
        alerts=loaded["alerts"],
        reports=loaded["reports"],
        intelligence=loaded["intelligence"],
    )
    publication.validate(models=models)
    if directory.name != publication.publication_id:
        raise DashboardReadModelError("dashboard_release_directory_id_mismatch")
    return models, publication


def publish_dashboard_v1(
    root: str | Path,
    models: DashboardReadModelSet,
) -> DashboardPublication:
    """Publish one immutable release and atomically switch the public ``v1`` link."""

    publication = DashboardPublication.create(models)
    root_path = Path(root)
    releases = root_path / "releases"
    root_path.mkdir(parents=True, exist_ok=True)
    releases.mkdir(mode=0o755, exist_ok=True)
    os.chmod(releases, 0o755)
    release = releases / publication.publication_id
    if release.exists():
        existing_models, existing_publication = _read_release(release)
        if existing_models != models or existing_publication != publication:
            raise DashboardReadModelError("dashboard_release_id_collision")
    else:
        temporary = Path(
            tempfile.mkdtemp(dir=releases, prefix=".dashboard-", suffix=".tmp")
        )
        try:
            os.chmod(temporary, 0o755)
            for model in models.models():
                _write_release_file(
                    temporary / _READ_MODEL_FILES[model.read_model_type],
                    model.as_dict(),
                )
            _write_release_file(
                temporary / _PUBLICATION_FILE,
                publication.as_dict(),
            )
            _fsync_directory(temporary)
            os.rename(temporary, release)
            _fsync_directory(releases)
            _read_release(release)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=root_path,
        prefix=".v1.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_link = Path(temporary_name)
    temporary_link.unlink()
    try:
        os.symlink(Path("releases") / publication.publication_id, temporary_link)
        os.replace(temporary_link, root_path / "v1")
        _fsync_directory(root_path)
    finally:
        if temporary_link.exists() or temporary_link.is_symlink():
            temporary_link.unlink()
    read_models, read_publication = read_dashboard_v1(root_path)
    if read_models != models or read_publication != publication:
        raise DashboardReadModelError("dashboard_publish_final_readback_mismatch")
    return publication


def read_dashboard_v1(
    root: str | Path,
) -> tuple[DashboardReadModelSet, DashboardPublication]:
    """Verify the atomically selected v1 release and every embedded hash."""

    root_path = Path(root)
    current = root_path / "v1"
    if not current.is_symlink():
        raise DashboardReadModelError("dashboard_current_link_missing")
    target_text = os.readlink(current)
    target = Path(target_text)
    if target.is_absolute() or len(target.parts) != 2 or target.parts[0] != "releases":
        raise DashboardReadModelError("dashboard_current_link_target_invalid")
    if len(target.parts[1]) != _HEX_ID_LENGTH or not is_sha256(target.parts[1]):
        raise DashboardReadModelError("dashboard_current_release_id_invalid")
    release = root_path / target
    return _read_release(release)


def read_dashboard_release_v1(
    root: str | Path,
    publication_id: str,
) -> tuple[DashboardReadModelSet, DashboardPublication]:
    """Verify one immutable release without changing or following ``v1``."""

    if not isinstance(publication_id, str) or not is_sha256(publication_id):
        raise DashboardReadModelError("dashboard_release_id_invalid")
    return _read_release(Path(root) / "releases" / publication_id)
