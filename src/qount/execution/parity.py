"""Economic-action parity checks for the legacy dispatcher migration."""

from __future__ import annotations

from typing import Any, Mapping

from qount.contracts import OrderPlan


def _action_symbol(order: Mapping[str, Any]) -> str:
    return str(order.get("data_symbol") or order.get("symbol") or "")


def _managed_order_id(order: Mapping[str, Any]) -> str:
    return str(order.get("id") or order.get("client_order_id") or "")


def _legacy_actions(plan: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    market_rows = sorted(
        plan.get("market_orders") or (),
        key=lambda row: 0 if str(row.get("side") or "").lower() == "sell" else 1,
    )
    actions = [
        {
            "symbol": str(row.get("symbol") or ""),
            "side": str(row.get("side") or "").lower(),
            "phase": (
                "reduce"
                if str(row.get("side") or "").lower() == "sell"
                else "increase"
            ),
            "order_type": str(row.get("type") or "market").lower(),
            "quantity": float(row.get("quantity")),
            "reduce_only": bool(row.get("reduce_only")),
            "close_position": False,
            "stop_price": None,
        }
        for row in market_rows
    ]
    actions.extend(
        {
            "symbol": str(row.get("symbol") or ""),
            "side": str(row.get("side") or "").lower(),
            "phase": "protective",
            "order_type": str(row.get("type") or "stop_market").lower(),
            "quantity": None,
            "reduce_only": bool(row.get("reduce_only")),
            "close_position": bool(row.get("close_position")),
            "stop_price": float(row.get("stop_price")),
        }
        for row in (plan.get("stop_orders") or ())
    )
    return tuple(actions)


def _standard_actions(plan: OrderPlan) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "symbol": order.symbol,
            "side": order.side,
            "phase": order.phase,
            "order_type": order.order_type,
            "quantity": order.quantity,
            "reduce_only": order.reduce_only,
            "close_position": order.close_position,
            "stop_price": order.stop_price,
        }
        for order in sorted(plan.orders, key=lambda value: value.sequence)
    )


def _legacy_cancellations(plan: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "symbol": _action_symbol(row),
            "target_exchange_order_id": str(row.get("id")) if row.get("id") else None,
            "target_client_order_id": (
                str(row.get("client_order_id"))
                if row.get("client_order_id")
                else None
            ),
        }
        for row in (plan.get("stop_cancels") or ())
    )


def _standard_cancellations(plan: OrderPlan) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "symbol": cancellation.symbol,
            "target_exchange_order_id": cancellation.target_exchange_order_id,
            "target_client_order_id": cancellation.target_client_order_id,
        }
        for cancellation in sorted(plan.cancellations, key=lambda value: value.sequence)
    )


def _numeric_mapping(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    return {str(symbol): float(number) for symbol, number in value.items()}


def compare_legacy_dispatch_plan(
    legacy_plan: Mapping[str, Any],
    standard_plan: OrderPlan,
) -> dict[str, Any]:
    """Report migration differences while intentionally ignoring client IDs."""

    comparisons = {
        "orders": (_legacy_actions(legacy_plan), _standard_actions(standard_plan)),
        "cancellations": (
            _legacy_cancellations(legacy_plan),
            _standard_cancellations(standard_plan),
        ),
        "retained_order_ids": (
            tuple(
                _managed_order_id(row)
                for row in (legacy_plan.get("retained_stops") or ())
            ),
            tuple(standard_plan.retained_order_ids),
        ),
        "expected_positions": (
            _numeric_mapping(legacy_plan.get("expected_positions_base")),
            _numeric_mapping(standard_plan.expected_positions),
        ),
        "reconciliation_tolerance": (
            _numeric_mapping(legacy_plan.get("reconciliation_tolerance_base")),
            _numeric_mapping(standard_plan.reconciliation_tolerance),
        ),
    }
    differences = tuple(
        name for name, (legacy, standard) in comparisons.items() if legacy != standard
    )
    return {
        "matches": not differences,
        "differences": differences,
        "legacy": {name: legacy for name, (legacy, _) in comparisons.items()},
        "standard": {name: standard for name, (_, standard) in comparisons.items()},
    }
