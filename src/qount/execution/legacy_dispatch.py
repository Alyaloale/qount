"""Convert verified legacy dry plans into standard, non-routing order plans."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from qount.contracts import OrderPlan
from qount.contracts import PlannedCancellation
from qount.contracts import PlannedOrder
from qount.contracts import PortfolioTarget
from qount.contracts import RiskDecision
from qount.contracts import canonical_hash
from qount.risk.legacy_dispatch import risk_decision_from_legacy_dry_plan
from qount.risk.validation import LegacyDispatchVerification
from qount.risk.validation import verify_legacy_dry_dispatch_plan


def _unique_strings(values: Sequence[object]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _position_hash(plan: Mapping[str, Any]) -> str:
    return canonical_hash(
        {
            "legacy_snapshot_hash": plan.get("snapshot_hash"),
            "account_equity": plan.get("account_equity"),
            "actual_weights": plan.get("actual_weights"),
        }
    )


def _empty_plan(
    plan: Mapping[str, Any],
    target: PortfolioTarget,
    risk: RiskDecision,
    verification: LegacyDispatchVerification,
    blockers: Sequence[object],
) -> OrderPlan:
    return OrderPlan.create(
        batch_id=verification.batch_id,
        risk_decision_id=risk.risk_decision_id,
        portfolio_target_id=target.portfolio_target_id,
        snapshot_id=target.snapshot_id,
        decision_ids=target.decision_ids,
        created_at=target.decision_time,
        current_position_hash=_position_hash(plan),
        approved_target=risk.approved_target,
        orders=(),
        cancellations=(),
        retained_order_ids=(),
        expected_positions={},
        reconciliation_tolerance={},
        blockers=_unique_strings(blockers) or ("legacy_order_plan_conversion_blocked",),
        executable=False,
    )


def _numeric_mapping(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError("mapping_missing")
    return {str(symbol): float(number) for symbol, number in value.items()}


def _managed_order_id(order: Mapping[str, Any]) -> str:
    value = order.get("id") or order.get("client_order_id")
    if not value:
        raise ValueError("managed_order_id_missing")
    return str(value)


def _action_symbol(order: Mapping[str, Any]) -> str:
    return str(order.get("data_symbol") or order.get("symbol") or "")


def order_plan_from_legacy_dry_plan(
    plan: Mapping[str, Any],
    target: PortfolioTarget,
    risk: RiskDecision,
) -> OrderPlan:
    """Build a deterministic standard plan; never route or mutate an exchange."""

    verification = verify_legacy_dry_dispatch_plan(plan, target)
    expected_risk = risk_decision_from_legacy_dry_plan(plan, target)
    linkage_errors = list(verification.errors)
    linkage_errors.extend(risk.validate())
    if risk.batch_id != verification.batch_id:
        linkage_errors.append("risk_batch_legacy_plan_mismatch")
    if risk.portfolio_target_id != target.portfolio_target_id:
        linkage_errors.append("risk_portfolio_target_mismatch")
    if risk.decision_hash != expected_risk.decision_hash:
        linkage_errors.append("risk_decision_legacy_plan_mismatch")
    if not risk.approved or risk.violations:
        linkage_errors.extend(risk.violations or ("risk_decision_not_approved",))
    if linkage_errors:
        return _empty_plan(plan, target, risk, verification, linkage_errors)

    try:
        market_rows = plan.get("market_orders") or ()
        stop_cancel_rows = plan.get("stop_cancels") or ()
        stop_rows = plan.get("stop_orders") or ()
        retained_rows = plan.get("retained_stops") or ()
        if not all(
            isinstance(rows, (list, tuple))
            for rows in (market_rows, stop_cancel_rows, stop_rows, retained_rows)
        ):
            raise ValueError("legacy_order_collections_invalid")

        market_rows = sorted(
            market_rows,
            key=lambda row: 0 if str(row.get("side") or "").lower() == "sell" else 1,
        )
        orders: list[PlannedOrder] = []
        sequence = 1
        for row in market_rows:
            side = str(row.get("side") or "").lower()
            orders.append(
                PlannedOrder.create(
                    batch_id=verification.batch_id,
                    decision_ids=target.decision_ids,
                    symbol=str(row.get("symbol") or ""),
                    side=side,
                    quantity=float(row.get("quantity")),
                    reduce_only=bool(row.get("reduce_only")),
                    phase="reduce" if side == "sell" else "increase",
                    sequence=sequence,
                    order_type=str(row.get("type") or "market").lower(),
                )
            )
            sequence += 1

        stop_symbols = {_action_symbol(row) for row in stop_rows}
        cancellations: list[PlannedCancellation] = []
        for row in stop_cancel_rows:
            symbol = _action_symbol(row)
            cancellations.append(
                PlannedCancellation.create(
                    batch_id=verification.batch_id,
                    decision_ids=target.decision_ids,
                    symbol=symbol,
                    target_exchange_order_id=(
                        str(row.get("id")) if row.get("id") else None
                    ),
                    target_client_order_id=(
                        str(row.get("client_order_id"))
                        if row.get("client_order_id")
                        else None
                    ),
                    sequence=sequence,
                    reason=(
                        "replace_protective_stop"
                        if symbol in stop_symbols
                        else "remove_protective_stop"
                    ),
                )
            )
            sequence += 1

        for row in stop_rows:
            orders.append(
                PlannedOrder.create(
                    batch_id=verification.batch_id,
                    decision_ids=target.decision_ids,
                    symbol=str(row.get("symbol") or ""),
                    side=str(row.get("side") or "").lower(),
                    quantity=None,
                    reduce_only=bool(row.get("reduce_only")),
                    phase="protective",
                    sequence=sequence,
                    order_type=str(row.get("type") or "stop_market").lower(),
                    close_position=bool(row.get("close_position")),
                    stop_price=float(row.get("stop_price")),
                )
            )
            sequence += 1

        if not risk.increase_risk_allowed and any(
            order.phase == "increase" for order in orders
        ):
            raise ValueError("increase_order_when_risk_increase_blocked")
        retained_order_ids = tuple(_managed_order_id(row) for row in retained_rows)
        expected_positions = _numeric_mapping(plan.get("expected_positions_base"))
        tolerance = _numeric_mapping(plan.get("reconciliation_tolerance_base"))
        return OrderPlan.create(
            batch_id=verification.batch_id,
            risk_decision_id=risk.risk_decision_id,
            portfolio_target_id=target.portfolio_target_id,
            snapshot_id=target.snapshot_id,
            decision_ids=target.decision_ids,
            created_at=target.decision_time,
            current_position_hash=_position_hash(plan),
            approved_target=risk.approved_target,
            orders=orders,
            cancellations=cancellations,
            retained_order_ids=retained_order_ids,
            expected_positions=expected_positions,
            reconciliation_tolerance=tolerance,
            blockers=(),
            executable=True,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        return _empty_plan(
            plan,
            target,
            risk,
            verification,
            (f"legacy_order_plan_conversion_error:{exc}",),
        )
