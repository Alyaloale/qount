"""Read-only resolver orchestration for in-flight and UNKNOWN orders."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.execution.state_machine import ExchangeOrderObservation
from qount.execution.state_machine import OrderRecoveryQuery
from qount.execution.state_machine import OrderRecoveryReport

if TYPE_CHECKING:
    from qount.ledger.store import RuntimeLedger


OrderResolver = Callable[[OrderRecoveryQuery], ExchangeOrderObservation | None]


def _mark_unknown(
    ledger: RuntimeLedger,
    query: OrderRecoveryQuery,
    *,
    completed_at: str,
    reason: str,
) -> None:
    current = ledger.get_order(query.client_order_id)
    if current["status"] == "UNKNOWN":
        return
    event_at = completed_at
    if aware_datetime(event_at) < aware_datetime(str(current["last_transition_at"])):
        event_at = str(current["last_transition_at"])
    ledger.transition_order(
        query.client_order_id,
        "UNKNOWN",
        event_at=event_at,
        source_hash=canonical_hash(
            {
                "kind": "order_recovery_unresolved",
                "client_order_id": query.client_order_id,
                "completed_at": completed_at,
                "reason": reason,
            }
        ),
        exchange_order_id=(
            str(current["exchange_order_id"])
            if current["exchange_order_id"] is not None
            else None
        ),
        executed_quantity=float(current["executed_quantity"]),
        average_price=(
            float(current["average_price"])
            if current["average_price"] is not None
            else None
        ),
        reason=reason,
    )


def recover_unknown_orders(
    ledger: RuntimeLedger,
    resolver: OrderResolver,
    *,
    started_at: str,
    completed_at: str,
) -> OrderRecoveryReport:
    """Resolve persisted in-flight orders by deterministic client ID only.

    A missing or failing query is ambiguity, not rejection. The order is left in
    ``UNKNOWN`` and the returned report requires HALT; this function never creates
    a replacement order and has no order-placement interface.
    """

    started = aware_datetime(started_at)
    completed = aware_datetime(completed_at)
    if completed < started:
        raise ValueError("order_recovery_time_order_invalid")
    queries = ledger.recovery_queries()
    attempted = tuple(query.client_order_id for query in queries)
    resolved: list[str] = []
    unresolved: list[str] = []
    errors: dict[str, str] = {}
    for query in queries:
        try:
            observation = resolver(query)
        except Exception as exc:
            reason = f"resolver_error:{type(exc).__name__}"
            _mark_unknown(
                ledger,
                query,
                completed_at=completed_at,
                reason=reason,
            )
            unresolved.append(query.client_order_id)
            errors[query.client_order_id] = reason
            continue
        if observation is None:
            reason = "client_order_id_not_found_unresolved"
            _mark_unknown(
                ledger,
                query,
                completed_at=completed_at,
                reason=reason,
            )
            unresolved.append(query.client_order_id)
            errors[query.client_order_id] = reason
            continue
        if not isinstance(observation, ExchangeOrderObservation):
            reason = "resolver_observation_type_invalid"
            _mark_unknown(
                ledger,
                query,
                completed_at=completed_at,
                reason=reason,
            )
            unresolved.append(query.client_order_id)
            errors[query.client_order_id] = reason
            continue
        if observation.client_order_id != query.client_order_id:
            reason = "resolver_client_order_id_mismatch"
            _mark_unknown(
                ledger,
                query,
                completed_at=completed_at,
                reason=reason,
            )
            unresolved.append(query.client_order_id)
            errors[query.client_order_id] = reason
            continue
        try:
            ledger.apply_order_observation(observation)
        except Exception as exc:
            reason = f"resolver_observation_rejected:{type(exc).__name__}"
            _mark_unknown(
                ledger,
                query,
                completed_at=completed_at,
                reason=reason,
            )
            unresolved.append(query.client_order_id)
            errors[query.client_order_id] = reason
            continue
        if observation.status == "UNKNOWN":
            unresolved.append(query.client_order_id)
            errors[query.client_order_id] = "exchange_status_unknown"
        else:
            resolved.append(query.client_order_id)
    report = OrderRecoveryReport.create(
        started_at=started_at,
        completed_at=completed_at,
        attempted_client_order_ids=attempted,
        resolved_client_order_ids=tuple(resolved),
        unresolved_client_order_ids=tuple(unresolved),
        errors=errors,
    )
    ledger.record_order_recovery(report)
    return report
