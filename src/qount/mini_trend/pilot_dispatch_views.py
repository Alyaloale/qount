"""Pure exchange-value normalization for the MiniTrend pilot dispatcher.

The dispatcher owns exchange calls, safety gates, and journal writes.  This
module contains only deterministic adapters for heterogeneous CCXT payloads,
which keeps those rules directly testable without an exchange client.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping


_MANAGED_PROTECTIVE_PREFIXES = ("qmt-s-", "q-p-")


def managed_protective_client_id(value: object) -> bool:
    """Return whether an order ID belongs to a dispatcher-managed stop."""
    return str(value or "").startswith(_MANAGED_PROTECTIVE_PREFIXES)


def float_or_zero(value: Any) -> float:
    """Coerce an exchange number, treating missing or malformed values as zero."""
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def utc_timestamp(value: object) -> dt.datetime | None:
    """Parse an offset-aware timestamp and normalize it to UTC."""
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def source_age_seconds(
    payload: Mapping[str, Any], *, observed_at: dt.datetime
) -> float | None:
    """Return a non-negative source age or reject materially future timestamps."""
    created_at = utc_timestamp(payload.get("created_at"))
    if created_at is None:
        return None
    age = (observed_at - created_at).total_seconds()
    if age < -60.0:
        return None
    return max(age, 0.0)


def round_down(value: float, step: float) -> float:
    """Round a positive quantity or price down to its exchange increment."""
    if step <= 0.0:
        return value
    value_dec = Decimal(str(value))
    step_dec = Decimal(str(step))
    units = (value_dec / step_dec).to_integral_value(rounding=ROUND_DOWN)
    return float(units * step_dec)


def position_symbol(position: Mapping[str, Any]) -> str:
    """Read a position symbol from either normalized or raw CCXT fields."""
    info = position.get("info") or {}
    return str(position.get("symbol") or info.get("symbol") or "")


def position_contracts(position: Mapping[str, Any]) -> float:
    """Return the absolute contract count from normalized or raw CCXT fields."""
    info = position.get("info") or {}
    value = position.get("contracts")
    if value is None:
        value = info.get("positionAmt")
    return abs(float_or_zero(value))


def position_side(position: Mapping[str, Any]) -> str:
    """Return an explicit position side, deriving it from signed contracts if needed."""
    side = str(position.get("side") or "").lower()
    if side in {"long", "short"}:
        return side
    signed = float_or_zero((position.get("info") or {}).get("positionAmt"))
    return "short" if signed < 0.0 else "long"


def position_average_cost(position: Mapping[str, Any]) -> float:
    """Return the best available entry-price field from a CCXT position payload."""
    info = position.get("info") or {}
    return float_or_zero(
        position.get("entryPrice")
        or position.get("average")
        or info.get("entryPrice")
        or info.get("breakEvenPrice")
    )


def order_view(order: Mapping[str, Any], *, ccxt_symbol: str) -> dict[str, Any]:
    """Normalize a regular or conditional CCXT order into the dispatcher view."""
    info = order.get("info") or {}
    trigger = (
        order.get("stopPrice")
        or order.get("triggerPrice")
        or info.get("stopPrice")
    )
    client_id = (
        order.get("clientOrderId")
        or info.get("clientOrderId")
        or info.get("clientAlgoId")
        or ""
    )
    return {
        "id": str(
            order.get("id") or info.get("orderId") or info.get("algoId") or ""
        ),
        "client_order_id": str(client_id),
        "symbol": ccxt_symbol,
        "type": str(
            order.get("type")
            or info.get("origType")
            or info.get("type")
            or ""
        ),
        "side": str(order.get("side") or info.get("side") or "").lower(),
        "trigger_price": float_or_zero(trigger)
        if trigger not in (None, "")
        else None,
        "reduce_only": bool(
            order.get("reduceOnly")
            or str(info.get("reduceOnly")).lower() == "true"
        ),
        "close_position": bool(
            order.get("closePosition")
            or str(info.get("closePosition")).lower() == "true"
        ),
        "status": str(order.get("status") or info.get("status") or ""),
    }
