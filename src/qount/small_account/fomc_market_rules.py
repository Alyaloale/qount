"""Pure Binance USD-M market-rule normalization for the FOMC boundary."""

from __future__ import annotations

import math
from typing import Any, Mapping

from qount.contracts import canonical_hash


class FomcLiveError(ValueError):
    """Raised when the FOMC live boundary cannot prove a safe state."""


def number(value: object, *fallbacks: object) -> float:
    """Return the first finite number from exchange-specific value variants."""
    for candidate in (value, *fallbacks):
        try:
            parsed = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    return math.nan


def market_rules(market: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the exact Binance contract fields used by the public watcher."""
    info = market.get("info") if isinstance(market.get("info"), Mapping) else {}
    filters = info.get("filters") if isinstance(info, Mapping) else ()
    by_type = {
        str(row.get("filterType")): row
        for row in filters or ()
        if isinstance(row, Mapping)
    }
    lot = by_type.get("LOT_SIZE", {})
    price_filter = by_type.get("PRICE_FILTER", {})
    notional = by_type.get("MIN_NOTIONAL", by_type.get("NOTIONAL", {}))
    limits = market.get("limits") if isinstance(market.get("limits"), Mapping) else {}
    amount_limits = (
        limits.get("amount") if isinstance(limits.get("amount"), Mapping) else {}
    )
    cost_limits = (
        limits.get("cost") if isinstance(limits.get("cost"), Mapping) else {}
    )
    precision = (
        market.get("precision")
        if isinstance(market.get("precision"), Mapping)
        else {}
    )
    price_tick = number(price_filter.get("tickSize"), precision.get("price"))
    quantity_step = number(lot.get("stepSize"), precision.get("amount"))
    minimum_quantity = number(lot.get("minQty"), amount_limits.get("min"))
    minimum_notional = number(
        notional.get("notional"),
        notional.get("minNotional"),
        cost_limits.get("min"),
        0.0,
    )
    contract_size = number(market.get("contractSize"), 1.0)
    rule_core = {
        "symbol": str(market.get("id") or ""),
        "step_size": quantity_step,
        "price_tick": price_tick,
        "minimum_quantity": minimum_quantity,
        "minimum_notional": minimum_notional,
        "contract_size": contract_size,
        "linear": bool(market.get("linear")),
        "swap": bool(market.get("swap")),
        "active": market.get("active"),
    }
    if not all(
        math.isfinite(value) and value > 0.0
        for value in (price_tick, quantity_step, minimum_quantity)
    ):
        raise FomcLiveError("fomc_live_market_rules_invalid")
    if not math.isfinite(minimum_notional) or minimum_notional < 0.0:
        raise FomcLiveError("fomc_live_market_rules_invalid")
    if not math.isclose(contract_size, 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise FomcLiveError("fomc_live_market_contract_size_invalid")
    return {
        "symbol": str(market.get("id") or "").upper(),
        "settle": str(market.get("settle") or "").upper(),
        "linear": bool(market.get("linear")),
        "swap": bool(market.get("swap")),
        "active": market.get("active"),
        "price_tick": price_tick,
        "quantity_step": quantity_step,
        "minimum_quantity": minimum_quantity,
        "minimum_notional_usdt": minimum_notional,
        "contract_size": contract_size,
        "exchange_rules_hash": canonical_hash(rule_core),
    }
