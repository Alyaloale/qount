"""Deterministic trading-history summary for LLM review."""

from __future__ import annotations

import datetime as dt
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

_RUNTIME_BOUNDARY_CURRENT = {
    "ledger_current",
    "ledger_current_after_blocked_observation",
}
RUNTIME_LEDGER_CURRENT_MAX_AGE_SECONDS = 900


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


def _readonly_account_observation(
    value: object,
    *,
    expected_observed_at: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    fields = {
        "source",
        "observed_at",
        "quote_asset",
        "wallet_balance",
        "available_balance",
        "margin_balance",
        "margin_used",
        "actual_gross_notional",
        "actual_gross_fraction",
        "margin_fraction",
        "open_order_count",
        "positions",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("runtime_fact_account_observation_invalid")
    if (
        value["source"] != "private_account_preflight"
        or value["observed_at"] != expected_observed_at
        or not isinstance(value["quote_asset"], str)
        or not value["quote_asset"]
        or len(value["quote_asset"]) > 20
    ):
        raise ValueError("runtime_fact_account_observation_invalid")
    try:
        aware_datetime(str(value["observed_at"]))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("runtime_fact_account_observation_time_invalid") from exc
    numeric = {
        name: _finite_number(value[name], name=f"runtime_fact_{name}", minimum=0.0)
        for name in (
            "wallet_balance",
            "available_balance",
            "margin_balance",
            "margin_used",
            "actual_gross_notional",
            "actual_gross_fraction",
            "margin_fraction",
        )
    }
    if numeric["available_balance"] > numeric["wallet_balance"] + 1e-12:
        raise ValueError("runtime_fact_account_balance_invalid")
    open_order_count = value["open_order_count"]
    if (
        not isinstance(open_order_count, int)
        or isinstance(open_order_count, bool)
        or open_order_count < 0
    ):
        raise ValueError("runtime_fact_open_order_count_invalid")
    raw_positions = value["positions"]
    if not isinstance(raw_positions, list) or len(raw_positions) > 100:
        raise ValueError("runtime_fact_positions_invalid")
    positions: list[dict[str, Any]] = []
    symbols: set[str] = set()
    for row in raw_positions:
        if not isinstance(row, Mapping) or set(row) != {
            "symbol",
            "side",
            "quantity",
            "notional",
        }:
            raise ValueError("runtime_fact_position_invalid")
        symbol = row["symbol"]
        side = row["side"]
        if (
            not isinstance(symbol, str)
            or not symbol
            or len(symbol) > 80
            or symbol in symbols
            or side not in {"long", "short"}
        ):
            raise ValueError("runtime_fact_position_invalid")
        symbols.add(symbol)
        positions.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": _finite_number(
                    row["quantity"],
                    name="runtime_fact_position_quantity",
                    minimum=0.0,
                ),
                "notional": _finite_number(
                    row["notional"],
                    name="runtime_fact_position_notional",
                    minimum=0.0,
                ),
            }
        )
    positions.sort(key=lambda row: row["symbol"])
    return {
        "status": "available_readonly",
        "source": value["source"],
        "observed_at": value["observed_at"],
        "quote_asset": value["quote_asset"],
        **numeric,
        "open_order_count": open_order_count,
        "positions": positions,
        "ledger_authority": False,
        "cost_basis_available": False,
        "fee_history_available": False,
        "order_lineage_available": False,
        "nav_available": False,
    }


def summarize_runtime_fact_boundary(
    snapshot: RuntimeLedgerSnapshot | None,
    blocked_runtime_observation: Mapping[str, Any] | None,
    *,
    evaluated_at: str | None = None,
    stale_after_seconds: int = RUNTIME_LEDGER_CURRENT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Separate historical ledger facts from newer read-only account facts."""

    if (
        not isinstance(stale_after_seconds, int)
        or isinstance(stale_after_seconds, bool)
        or stale_after_seconds < 1
    ):
        raise ValueError("runtime_fact_ledger_freshness_invalid")
    if evaluated_at is None:
        evaluated_time = None
        normalized_evaluated_at = None
    else:
        try:
            evaluated_time = aware_datetime(evaluated_at)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("runtime_fact_evaluation_time_invalid") from exc
        normalized_evaluated_at = evaluated_time.astimezone(dt.timezone.utc).isoformat()

    if snapshot is not None:
        snapshot.validate()
        ledger_updated_at = snapshot.source_updated_at
        try:
            ledger_time = aware_datetime(ledger_updated_at)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("runtime_fact_ledger_time_invalid") from exc
        ledger = {
            "status": "available",
            "source": "runtime_ledger",
            "source_updated_at": ledger_updated_at,
            "position_count": sum(
                float(row["quantity"]) != 0.0 for row in snapshot.position_details
            ),
            "reconciliation_passed": snapshot.reconciliation["passed"],
            "halt_required": snapshot.reconciliation["halt_required"],
            "scope": "source_updated_at_only",
        }
    else:
        ledger_time = None
        ledger = {
            "status": "unavailable",
            "source": "runtime_ledger",
            "source_updated_at": None,
            "position_count": None,
            "reconciliation_passed": None,
            "halt_required": None,
            "scope": "unavailable",
        }

    if ledger_time is None:
        ledger_freshness = "unavailable"
    elif evaluated_time is None:
        ledger_freshness = "unverified"
    elif ledger_time > evaluated_time:
        ledger_freshness = "future_dated"
    elif evaluated_time >= ledger_time + dt.timedelta(seconds=stale_after_seconds):
        ledger_freshness = "stale"
    else:
        ledger_freshness = "fresh"
    ledger["freshness_status"] = ledger_freshness
    ledger["evaluated_at"] = normalized_evaluated_at
    ledger["stale_after_seconds"] = stale_after_seconds

    if blocked_runtime_observation is None:
        if ledger_freshness == "fresh":
            status = "ledger_current"
        elif ledger_freshness == "stale":
            status = "ledger_stale"
        elif ledger_freshness == "future_dated":
            status = "ledger_future_dated"
        elif ledger_freshness == "unverified":
            status = "ledger_freshness_unverified"
        else:
            status = "ledger_unavailable"
        return {
            "status": status,
            "ledger": ledger,
            "blocked_runtime_observation": None,
            "account_observation": None,
            "evaluated_at": normalized_evaluated_at,
            "stale_after_seconds": stale_after_seconds,
            "current_ledger_reconciliation": (
                "available" if status in _RUNTIME_BOUNDARY_CURRENT else "unavailable"
            ),
        }

    observation = blocked_runtime_observation
    core = {
        key: item for key, item in observation.items() if key != "observation_hash"
    }
    observation_hash = observation.get("observation_hash")
    blockers = observation.get("blockers")
    if (
        observation.get("artifact_type") != "qount_blocked_runtime_observation"
        or observation.get("status") != "blocked"
        or observation.get("live_orders_allowed") is not False
        or observation.get("runtime_ledger_created") is not False
        or not isinstance(observation.get("strategy_id"), str)
        or not observation["strategy_id"]
        or not isinstance(blockers, list)
        or not blockers
        or any(not isinstance(item, str) or not item for item in blockers)
        or not is_sha256(observation_hash)
        or observation_hash != canonical_hash(core)
    ):
        raise ValueError("runtime_fact_blocked_observation_invalid")
    try:
        observed_at = str(observation["observed_at"])
        observation_time = aware_datetime(observed_at)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("runtime_fact_blocked_observation_time_invalid") from exc
    account = _readonly_account_observation(
        observation.get("account_observation"),
        expected_observed_at=observed_at,
    )
    blocked = {
        "status": "blocked",
        "observed_at": observed_at,
        "strategy_id": observation["strategy_id"],
        "blockers": list(blockers),
        "live_orders_allowed": False,
        "runtime_ledger_created": False,
        "observation_hash": observation_hash,
    }
    if ledger_time is None:
        status = "ledger_unavailable_with_blocked_observation"
    elif observation_time >= ledger_time:
        status = "ledger_superseded_by_blocked_observation"
    elif ledger_freshness == "fresh":
        status = "ledger_current_after_blocked_observation"
    elif ledger_freshness == "stale":
        status = "ledger_stale_after_blocked_observation"
    elif ledger_freshness == "future_dated":
        status = "ledger_future_dated_after_blocked_observation"
    else:
        status = "ledger_freshness_unverified_after_blocked_observation"
    return {
        "status": status,
        "ledger": ledger,
        "blocked_runtime_observation": blocked,
        "account_observation": account,
        "evaluated_at": normalized_evaluated_at,
        "stale_after_seconds": stale_after_seconds,
        "current_ledger_reconciliation": (
            "available" if status in _RUNTIME_BOUNDARY_CURRENT else "unavailable"
        ),
    }


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


__all__ = [
    "RUNTIME_LEDGER_CURRENT_MAX_AGE_SECONDS",
    "summarize_runtime_fact_boundary",
    "summarize_trading_history",
    "validate_trading_history",
]
