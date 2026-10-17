"""Read-only comparison of current positions and exchange protective orders."""
from __future__ import annotations

from datetime import datetime, timezone
import math


def position_amount(row):
    info = row.get("info") or {}
    amount = float(row.get("positionAmt", info.get("positionAmt", row.get("contracts", row.get("amount", 0)))) or 0)
    if not math.isfinite(amount):
        raise ValueError("position_amount_invalid")
    return -abs(amount) if row.get("side") == "short" or row.get("positionSide", info.get("positionSide")) == "SHORT" else amount


def native_symbol(value):
    return str(value or "").upper().replace("/", "").split(":")[0]


def inspect_protection(exchange, positions, store):
    result = dict(checked_at=datetime.now(timezone.utc).isoformat(), status="UNKNOWN", positions=[])
    try:
        for position in positions:
            quantity = position_amount(position)
            if quantity == 0:
                continue
            symbol = native_symbol(position.get("symbol") or (position.get("info") or {}).get("symbol"))
            if not symbol:
                raise ValueError("position_symbol_missing")
            # Current ordinary orders alone do not certify conditional-order protection.
            # fetch_open_orders must provide the actual protective order identity.
            orders = exchange.fetch_open_orders(position.get("symbol") or symbol)
            matched = False
            for row in orders:
                info = row.get("info") or {}
                client_id = row.get("clientOrderId", info.get("clientOrderId", info.get("clientAlgoId")))
                local = store.get_order(str(client_id)) if client_id else None
                kind = str(row.get("type", info.get("type", ""))).upper()
                reduce_only = row.get("reduceOnly", info.get("reduceOnly"))
                side = str(row.get("side", info.get("side", ""))).lower()
                status = str(row.get("status", info.get("status", ""))).lower()
                remaining = float(row.get("remaining") if row.get("remaining") is not None else info.get("origQty", row.get("amount", 0)))
                stop = float(row.get("stopPrice") or row.get("triggerPrice") or info.get("stopPrice") or info.get("triggerPrice") or 0)
                if (local and local.get("strategy_id") == "one_atr_macro_v0_1"
                        and kind.replace("_", "") == "STOPMARKET"
                        and status in {"", "open", "new", "partially_filled"}
                        and str(reduce_only).lower() == "true"
                        and side == ("sell" if quantity > 0 else "buy")
                        and native_symbol(row.get("symbol") or info.get("symbol")) == symbol
                        and math.isfinite(remaining) and remaining+1e-12 >= abs(quantity)
                        and math.isfinite(stop) and stop > 0):
                    matched = True
                    break
            result["positions"].append(dict(symbol=symbol, quantity=quantity, protected=matched))
        result["status"] = "FLAT" if not result["positions"] else "PROTECTED" if all(p["protected"] for p in result["positions"]) else "UNPROTECTED"
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result
