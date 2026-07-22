"""Deterministic trading-history summary for LLM review."""

from __future__ import annotations

import math
from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts.trace import aware_datetime
from qount.ledger import RuntimeLedgerSnapshot


_SUMMARY_FIELDS = {
    "status",
    "source",
    "batch_id",
    "source_updated_at",
    "position_count",
    "order_count",
    "fill_count",
    "cash_event_count",
    "recoverable_order_count",
    "unresolved_order_count",
    "execution_evidence_status",
    "execution_evidence_sufficient",
    "wallet_balance",
    "available_balance",
    "current_equity",
    "current_drawdown_fraction",
    "peak_drawdown_fraction",
    "trading_pnl",
    "trading_pnl_cumulative",
    "funding",
    "funding_cumulative",
    "fees",
    "fees_cumulative",
    "transfers",
    "transfers_cumulative",
    "residual",
    "reconciliation_passed",
    "halt_required",
    "recent_orders",
    "recent_fills",
    "summary_hash",
}


def _finite_number(value: object, *, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"trading_history_{name}_invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"trading_history_{name}_invalid") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise ValueError(f"trading_history_{name}_invalid")
    return number


def validate_trading_history(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or set(value) != _SUMMARY_FIELDS:
        raise ValueError("trading_history_fields_invalid")
    if value["source"] != "runtime_ledger" or value["status"] not in {
        "available",
        "unavailable",
    }:
        raise ValueError("trading_history_status_invalid")
    core = dict(value)
    summary_hash = core.pop("summary_hash")
    if not is_sha256(summary_hash) or summary_hash != canonical_hash(core):
        raise ValueError("trading_history_hash_invalid")
    if value["status"] == "unavailable":
        nullable = _SUMMARY_FIELDS - {
            "status",
            "source",
            "recent_orders",
            "recent_fills",
            "summary_hash",
        }
        if (
            any(value[name] is not None for name in nullable)
            or value["recent_orders"] != []
            or value["recent_fills"] != []
        ):
            raise ValueError("trading_history_unavailable_invalid")
        return
    if not is_sha256(value["batch_id"]):
        raise ValueError("trading_history_batch_id_invalid")
    try:
        aware_datetime(value["source_updated_at"])
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("trading_history_time_invalid") from exc
    for name in (
        "position_count",
        "order_count",
        "fill_count",
        "cash_event_count",
        "recoverable_order_count",
        "unresolved_order_count",
    ):
        if (
            not isinstance(value[name], int)
            or isinstance(value[name], bool)
            or value[name] < 0
        ):
            raise ValueError(f"trading_history_{name}_invalid")
    for name in (
        "wallet_balance",
        "available_balance",
        "current_equity",
        "current_drawdown_fraction",
        "peak_drawdown_fraction",
        "fees",
        "fees_cumulative",
    ):
        _finite_number(value[name], name=name, minimum=0.0)
    for name in (
        "trading_pnl",
        "trading_pnl_cumulative",
        "funding",
        "funding_cumulative",
        "transfers",
        "transfers_cumulative",
        "residual",
    ):
        _finite_number(value[name], name=name)
    if not isinstance(value["reconciliation_passed"], bool) or not isinstance(
        value["halt_required"], bool
    ):
        raise ValueError("trading_history_reconciliation_invalid")
    if value["execution_evidence_status"] not in {
        "no_order_expected",
        "orders_expected_but_missing",
        "fills_verified",
    } or not isinstance(value["execution_evidence_sufficient"], bool):
        raise ValueError("trading_history_execution_evidence_invalid")
    if value["execution_evidence_sufficient"] is not (
        value["execution_evidence_status"]
        in {"no_order_expected", "fills_verified"}
    ):
        raise ValueError("trading_history_execution_evidence_invalid")
    orders = value["recent_orders"]
    fills = value["recent_fills"]
    if not isinstance(orders, list) or len(orders) > 20:
        raise ValueError("trading_history_orders_invalid")
    if not isinstance(fills, list) or len(fills) > 20:
        raise ValueError("trading_history_fills_invalid")
    order_fields = {
        "client_order_id",
        "symbol",
        "side",
        "order_type",
        "status",
        "executed_quantity",
    }
    for row in orders:
        if not isinstance(row, Mapping) or set(row) != order_fields:
            raise ValueError("trading_history_order_fields_invalid")
        if any(
            not isinstance(row[name], str) or not row[name]
            for name in order_fields - {"executed_quantity"}
        ):
            raise ValueError("trading_history_order_text_invalid")
        _finite_number(
            row["executed_quantity"], name="order_executed_quantity", minimum=0.0
        )
    fill_fields = {
        "client_order_id",
        "exchange_trade_id",
        "quantity",
        "price",
        "fee",
        "fee_asset",
        "occurred_at",
    }
    for row in fills:
        if not isinstance(row, Mapping) or set(row) != fill_fields:
            raise ValueError("trading_history_fill_fields_invalid")
        for name in ("client_order_id", "exchange_trade_id", "fee_asset"):
            if not isinstance(row[name], str) or not row[name]:
                raise ValueError("trading_history_fill_text_invalid")
        if _finite_number(row["quantity"], name="fill_quantity", minimum=0.0) <= 0:
            raise ValueError("trading_history_fill_quantity_invalid")
        if _finite_number(row["price"], name="fill_price", minimum=0.0) <= 0:
            raise ValueError("trading_history_fill_price_invalid")
        _finite_number(row["fee"], name="fill_fee", minimum=0.0)
        try:
            aware_datetime(row["occurred_at"])
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("trading_history_fill_time_invalid") from exc


def summarize_trading_history(
    snapshot: RuntimeLedgerSnapshot | None,
) -> dict[str, Any]:
    if snapshot is None:
        core = {
            "status": "unavailable",
            "source": "runtime_ledger",
            "batch_id": None,
            "source_updated_at": None,
            "position_count": None,
            "order_count": None,
            "fill_count": None,
            "cash_event_count": None,
            "recoverable_order_count": None,
            "unresolved_order_count": None,
            "execution_evidence_status": None,
            "execution_evidence_sufficient": None,
            "wallet_balance": None,
            "available_balance": None,
            "current_equity": None,
            "current_drawdown_fraction": None,
            "peak_drawdown_fraction": None,
            "trading_pnl": None,
            "trading_pnl_cumulative": None,
            "funding": None,
            "funding_cumulative": None,
            "fees": None,
            "fees_cumulative": None,
            "transfers": None,
            "transfers_cumulative": None,
            "residual": None,
            "reconciliation_passed": None,
            "halt_required": None,
            "recent_orders": [],
            "recent_fills": [],
        }
        summary = core | {"summary_hash": canonical_hash(core)}
        validate_trading_history(summary)
        return summary

    snapshot.validate()
    nav = snapshot.nav
    account = snapshot.account
    reconciliation = snapshot.reconciliation
    recent_orders = [
        {
            "client_order_id": row["client_order_id"],
            "symbol": row["symbol"],
            "side": row["side"],
            "order_type": row["order_type"],
            "status": row["status"],
            "executed_quantity": row["executed_quantity"],
        }
        for row in snapshot.orders[-20:]
    ]
    recent_fills = [
        {
            "client_order_id": row["client_order_id"],
            "exchange_trade_id": row["exchange_trade_id"],
            "quantity": row["quantity"],
            "price": row["price"],
            "fee": row["fee"],
            "fee_asset": row["fee_asset"],
            "occurred_at": row["occurred_at"],
        }
        for row in snapshot.fills[-20:]
    ]
    if snapshot.fills:
        execution_evidence_status = "fills_verified"
    elif not snapshot.orders and reconciliation["passed"] and not reconciliation[
        "halt_required"
    ]:
        execution_evidence_status = "no_order_expected"
    else:
        execution_evidence_status = "orders_expected_but_missing"
    core = {
        "status": "available",
        "source": "runtime_ledger",
        "batch_id": snapshot.batch_id,
        "source_updated_at": snapshot.source_updated_at,
        # The ledger stores one position row per tracked symbol, including
        # zero-quantity rows. Report the number of active (non-zero) positions
        # so an all-cash cycle is not narrated as holding every symbol.
        "position_count": sum(
            float(row["quantity"]) != 0.0 for row in snapshot.position_details
        ),
        "order_count": len(snapshot.orders),
        "fill_count": len(snapshot.fills),
        "cash_event_count": len(snapshot.cash_events),
        "recoverable_order_count": len(snapshot.recoveries),
        "unresolved_order_count": len(snapshot.unresolved_order_ids),
        "execution_evidence_status": execution_evidence_status,
        "execution_evidence_sufficient": execution_evidence_status
        in {"no_order_expected", "fills_verified"},
        "wallet_balance": account["wallet_balance"],
        "available_balance": account["available_balance"],
        "current_equity": nav["equity"],
        "current_drawdown_fraction": account["current_drawdown_fraction"],
        "peak_drawdown_fraction": account["peak_drawdown_fraction"],
        "trading_pnl": nav["trading_pnl"],
        "trading_pnl_cumulative": nav["trading_pnl_cumulative"],
        "funding": nav["funding"],
        "funding_cumulative": nav["funding_cumulative"],
        "fees": nav["fees"],
        "fees_cumulative": nav["fees_cumulative"],
        "transfers": nav["transfers"],
        "transfers_cumulative": nav["transfers_cumulative"],
        "residual": nav["residual"],
        "reconciliation_passed": reconciliation["passed"],
        "halt_required": reconciliation["halt_required"],
        "recent_orders": recent_orders,
        "recent_fills": recent_fills,
    }
    summary = core | {"summary_hash": canonical_hash(core)}
    validate_trading_history(summary)
    return summary


__all__ = ["summarize_trading_history", "validate_trading_history"]
