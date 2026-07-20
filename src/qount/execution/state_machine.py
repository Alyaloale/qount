"""Pure order-state contracts for deterministic submission and recovery."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from qount.contracts import canonical_hash
from qount.contracts import trace_id
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256


ORDER_STATUSES = (
    "PLANNED",
    "SUBMITTING",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "REJECTED",
    "CANCELED",
    "EXPIRED",
    "UNKNOWN",
)
TERMINAL_ORDER_STATUSES = frozenset(
    {"FILLED", "REJECTED", "CANCELED", "EXPIRED"}
)
RECOVERABLE_ORDER_STATUSES = frozenset(
    {"SUBMITTING", "ACKNOWLEDGED", "PARTIALLY_FILLED", "UNKNOWN"}
)
_TRANSITIONS = {
    "PLANNED": {"SUBMITTING", "CANCELED"},
    "SUBMITTING": {
        "ACKNOWLEDGED",
        "PARTIALLY_FILLED",
        "FILLED",
        "REJECTED",
        "CANCELED",
        "EXPIRED",
        "UNKNOWN",
    },
    "ACKNOWLEDGED": {
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELED",
        "EXPIRED",
        "UNKNOWN",
    },
    "PARTIALLY_FILLED": {
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELED",
        "EXPIRED",
        "UNKNOWN",
    },
    "UNKNOWN": {
        "UNKNOWN",
        "ACKNOWLEDGED",
        "PARTIALLY_FILLED",
        "FILLED",
        "REJECTED",
        "CANCELED",
        "EXPIRED",
    },
    "FILLED": set(),
    "REJECTED": set(),
    "CANCELED": set(),
    "EXPIRED": set(),
}


def validate_order_transition(current_status: str, next_status: str) -> None:
    if current_status not in ORDER_STATUSES or next_status not in ORDER_STATUSES:
        raise ValueError("order_status_invalid")
    if next_status not in _TRANSITIONS[current_status]:
        raise ValueError(
            f"order_transition_forbidden:{current_status}->{next_status}"
        )


@dataclass(frozen=True)
class ExchangeOrderObservation:
    client_order_id: str
    status: str
    observed_at: str
    exchange_order_id: str | None
    executed_quantity: float
    average_price: float | None
    source_hash: str
    reason: str | None = None

    @classmethod
    def create(
        cls,
        *,
        client_order_id: str,
        status: str,
        observed_at: str,
        exchange_order_id: str | None,
        executed_quantity: float,
        average_price: float | None,
        source_hash: str,
        reason: str | None = None,
    ) -> ExchangeOrderObservation:
        observation = cls(
            client_order_id=client_order_id,
            status=status,
            observed_at=observed_at,
            exchange_order_id=exchange_order_id,
            executed_quantity=executed_quantity,
            average_price=average_price,
            source_hash=source_hash,
            reason=reason,
        )
        errors = observation.validate()
        if errors:
            raise ValueError(f"exchange_order_observation_invalid:{','.join(errors)}")
        return observation

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.client_order_id:
            errors.append("client_order_id_empty")
        if self.status not in ORDER_STATUSES or self.status == "PLANNED":
            errors.append("status_invalid")
        try:
            aware_datetime(self.observed_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("observed_at_invalid")
        if self.exchange_order_id is not None and not str(self.exchange_order_id):
            errors.append("exchange_order_id_invalid")
        try:
            executed = float(self.executed_quantity)
        except (TypeError, ValueError):
            executed = math.nan
        if not math.isfinite(executed) or executed < 0.0:
            errors.append("executed_quantity_invalid")
        if self.average_price is not None:
            try:
                average_price = float(self.average_price)
            except (TypeError, ValueError):
                average_price = math.nan
            if not math.isfinite(average_price) or average_price <= 0.0:
                errors.append("average_price_invalid")
        if executed > 0.0 and self.average_price is None:
            errors.append("average_price_missing_for_fill")
        if self.status in {"ACKNOWLEDGED", "REJECTED"} and executed > 0.0:
            errors.append("executed_quantity_unexpected")
        if self.status in {"PARTIALLY_FILLED", "FILLED"} and executed <= 0.0:
            errors.append("executed_quantity_missing")
        if not is_sha256(self.source_hash):
            errors.append("source_hash_invalid")
        return tuple(errors)

    def as_dict(self) -> dict[str, object]:
        return {
            "client_order_id": self.client_order_id,
            "status": self.status,
            "observed_at": self.observed_at,
            "exchange_order_id": self.exchange_order_id,
            "executed_quantity": self.executed_quantity,
            "average_price": self.average_price,
            "source_hash": self.source_hash,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class OrderRecoveryQuery:
    client_order_id: str
    exchange_order_id: str | None
    symbol: str
    current_status: str
    last_transition_at: str

    def validate(self) -> None:
        if not self.client_order_id or not self.symbol:
            raise ValueError("order_recovery_query_identity_invalid")
        if self.current_status not in RECOVERABLE_ORDER_STATUSES:
            raise ValueError("order_recovery_query_status_invalid")
        try:
            aware_datetime(self.last_transition_at)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("order_recovery_query_time_invalid") from exc


@dataclass(frozen=True)
class OrderRecoveryReport:
    recovery_id: str
    started_at: str
    completed_at: str
    attempted_client_order_ids: tuple[str, ...]
    resolved_client_order_ids: tuple[str, ...]
    unresolved_client_order_ids: tuple[str, ...]
    errors: Mapping[str, str]
    risk_increase_allowed: bool
    halt_required: bool
    report_hash: str

    @classmethod
    def create(
        cls,
        *,
        started_at: str,
        completed_at: str,
        attempted_client_order_ids: tuple[str, ...],
        resolved_client_order_ids: tuple[str, ...],
        unresolved_client_order_ids: tuple[str, ...],
        errors: Mapping[str, str],
    ) -> OrderRecoveryReport:
        attempted_client_order_ids = tuple(sorted(attempted_client_order_ids))
        resolved_client_order_ids = tuple(sorted(resolved_client_order_ids))
        unresolved_client_order_ids = tuple(sorted(unresolved_client_order_ids))
        core = {
            "started_at": started_at,
            "completed_at": completed_at,
            "attempted_client_order_ids": attempted_client_order_ids,
            "resolved_client_order_ids": resolved_client_order_ids,
            "unresolved_client_order_ids": unresolved_client_order_ids,
            "errors": dict(errors),
            "risk_increase_allowed": not unresolved_client_order_ids,
            "halt_required": bool(unresolved_client_order_ids),
        }
        report_hash = canonical_hash(core)
        report = cls(
            **core,
            recovery_id=trace_id(
                "order_recovery",
                {"started_at": started_at, "report_hash": report_hash},
            ),
            report_hash=report_hash,
        )
        report.validate()
        return report

    def validate(self) -> None:
        try:
            started = aware_datetime(self.started_at)
            completed = aware_datetime(self.completed_at)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("order_recovery_time_invalid") from exc
        if completed < started:
            raise ValueError("order_recovery_time_order_invalid")
        attempted = set(self.attempted_client_order_ids)
        resolved = set(self.resolved_client_order_ids)
        unresolved = set(self.unresolved_client_order_ids)
        if (
            len(attempted) != len(self.attempted_client_order_ids)
            or len(resolved) != len(self.resolved_client_order_ids)
            or len(unresolved) != len(self.unresolved_client_order_ids)
            or resolved & unresolved
            or resolved | unresolved != attempted
        ):
            raise ValueError("order_recovery_sets_invalid")
        if set(self.errors) - unresolved:
            raise ValueError("order_recovery_errors_invalid")
        if self.risk_increase_allowed is not (not unresolved):
            raise ValueError("order_recovery_risk_flag_invalid")
        if self.halt_required is not bool(unresolved):
            raise ValueError("order_recovery_halt_flag_invalid")
        expected_hash = canonical_hash(
            {
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "attempted_client_order_ids": self.attempted_client_order_ids,
                "resolved_client_order_ids": self.resolved_client_order_ids,
                "unresolved_client_order_ids": self.unresolved_client_order_ids,
                "errors": dict(self.errors),
                "risk_increase_allowed": self.risk_increase_allowed,
                "halt_required": self.halt_required,
            }
        )
        if self.report_hash != expected_hash:
            raise ValueError("order_recovery_hash_invalid")
        expected_id = trace_id(
            "order_recovery",
            {"started_at": self.started_at, "report_hash": expected_hash},
        )
        if self.recovery_id != expected_id:
            raise ValueError("order_recovery_id_invalid")
