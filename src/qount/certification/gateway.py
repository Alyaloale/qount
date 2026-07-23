"""Local venue gateway for certification fault injection testing.

Simulates a Binance USD-M-like exchange in memory.  Supports:
- submit / cancel / query by client_order_id
- MARKET and STOP_MARKET order types
- Fault injection (ACK loss, timeout, partial fill, crash)
- Crash recovery via REST snapshot
- Symbol rules (minQty, minNotional, stepSize, tickSize) for §3.4 rounding/filter
- Funding/income fixture for §3.4 funding/income

orders_authorized is always False; no real network is used.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from qount.certification.fault_injection import FaultInjector
from qount.certification.fault_injection import FaultScenario

_FILL_PRICE = 100000.0


@dataclass(frozen=True)
class SymbolRules:
    """Exchange filter rules for one symbol (§3.4 rounding/filter)."""

    min_qty: float
    min_notional: float
    step_size: float
    tick_size: float

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.min_qty < 0.0:
            errors.append("symbol_rules_min_qty_negative")
        if self.min_notional < 0.0:
            errors.append("symbol_rules_min_notional_negative")
        if self.step_size <= 0.0:
            errors.append("symbol_rules_step_size_invalid")
        if self.tick_size <= 0.0:
            errors.append("symbol_rules_tick_size_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class SymbolRulesSet:
    """A set of symbol rules for multiple symbols."""

    rules: dict[str, SymbolRules] = field(default_factory=dict)

    def get(self, symbol: str) -> SymbolRules | None:
        return self.rules.get(symbol)

    def add(self, symbol: str, rules: SymbolRules) -> None:
        errors = rules.validate()
        if errors:
            raise ValueError(f"symbol_rules_invalid:{','.join(errors)}")
        self.rules[symbol] = rules


class GatewayError(Exception):
    """Raised when the gateway rejects an operation."""


class GatewayFilterError(GatewayError):
    """Raised when an order violates symbol filter rules (§3.4)."""


class GatewayTimeout(GatewayError):
    """Raised when a fault injects a REST timeout."""


class GatewayAckLoss(GatewayError):
    """Raised when a fault injects an ACK loss."""


class GatewayCrash(GatewayError):
    """Raised when a fault injects a crash at a specific state."""


def _round_to_step(qty: float, step_size: float) -> float:
    if step_size <= 0.0:
        return qty
    steps = math.floor(qty / step_size + 1e-12)
    return round(steps * step_size, 10)


def _round_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0.0:
        return price
    ticks = round(price / tick_size)
    return round(ticks * tick_size, 10)


class LocalVenueGateway:
    """In-memory simulated exchange for certification testing."""

    def __init__(self) -> None:
        self._orders: dict[str, dict[str, Any]] = {}
        self._positions: dict[str, float] = {}
        self._trades: list[dict[str, Any]] = []
        self._funding_payments: list[dict[str, Any]] = []
        self._fault_injector: FaultInjector | None = None
        self._crashed: bool = False
        self._orders_authorized: bool = False
        self._symbol_rules: dict[str, SymbolRules] = {}

    @property
    def orders_authorized(self) -> bool:
        return self._orders_authorized

    def set_fault_injector(self, injector: FaultInjector) -> None:
        self._fault_injector = injector

    def set_symbol_rules(self, rules: dict[str, SymbolRules]) -> None:
        for symbol, rule in rules.items():
            errors = rule.validate()
            if errors:
                raise ValueError(f"symbol_rules_invalid:{','.join(errors)}")
        self._symbol_rules = dict(rules)

    def simulate_funding(
        self, symbol: str, rate: float
    ) -> dict[str, Any]:
        """Apply funding to a position (§3.4 fixture).

        Positive rate: longs pay shorts.
        Returns the funding payment record.
        """
        position = self._positions.get(symbol, 0.0)
        notional = abs(position) * _FILL_PRICE
        payment = -position * _FILL_PRICE * rate
        record = {
            "symbol": symbol,
            "rate": rate,
            "position": position,
            "notional": notional,
            "funding_payment": payment,
            "time": int(time.time() * 1000),
        }
        self._funding_payments.append(record)
        return dict(record)

    @property
    def funding_payments(self) -> list[dict[str, Any]]:
        return [dict(fp) for fp in self._funding_payments]

    def _check_fault(
        self,
        client_order_id: str,
        operation: str,
    ) -> FaultScenario | None:
        if self._fault_injector is None:
            return None
        return self._fault_injector.check(client_order_id, operation)

    def submit(
        self,
        *,
        client_order_id: str,
        symbol: str,
        side: str,
        qty: float,
        order_type: str = "MARKET",
        stop_price: float | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """Submit an order. Returns the exchange response dict.

        Raises GatewayAckLoss, GatewayTimeout, or GatewayCrash on fault.
        """
        if self._crashed:
            raise GatewayCrash("gateway_crashed_must_recover_first")
        if client_order_id in self._orders:
            existing = self._orders[client_order_id]
            return dict(existing)

        rules = self._symbol_rules.get(symbol)
        if rules is not None:
            qty = _round_to_step(qty, rules.step_size)
            if qty < rules.min_qty:
                raise GatewayFilterError(
                    f"min_qty_violation:{symbol}:qty={qty}:min={rules.min_qty}"
                )
            if order_type == "STOP_MARKET" and stop_price is not None:
                stop_price = _round_to_tick(stop_price, rules.tick_size)
                ref_price = stop_price
            else:
                ref_price = _FILL_PRICE
            notional = qty * ref_price
            if notional < rules.min_notional:
                raise GatewayFilterError(
                    f"min_notional_violation:{symbol}:notional={notional}:min={rules.min_notional}"
                )

        scenario = self._check_fault(client_order_id, "submit")
        if scenario is not None:
            if scenario.fault_type == "ack_loss":
                order = {
                    "client_order_id": client_order_id,
                    "symbol": symbol,
                    "side": side,
                    "origQty": str(qty),
                    "type": order_type,
                    "status": "UNKNOWN",
                    "exchange_order_id": None,
                    "reduce_only": reduce_only,
                }
                self._orders[client_order_id] = order
                raise GatewayAckLoss("ack_lost")
            if scenario.fault_type == "rest_timeout":
                raise GatewayTimeout("rest_timeout")
            if scenario.fault_type == "crash_at_submitting":
                order = {
                    "client_order_id": client_order_id,
                    "symbol": symbol,
                    "side": side,
                    "origQty": str(qty),
                    "type": order_type,
                    "status": "UNKNOWN",
                    "exchange_order_id": None,
                    "reduce_only": reduce_only,
                }
                self._orders[client_order_id] = order
                self._crashed = True
                raise GatewayCrash("crash_at_submitting")
            if scenario.fault_type == "partial_fill":
                fill_qty = scenario.parameters.get(
                    "fill_qty", qty / 2
                )
                exchange_id = str(uuid.uuid4())
                order = {
                    "client_order_id": client_order_id,
                    "symbol": symbol,
                    "side": side,
                    "origQty": str(qty),
                    "executedQty": str(fill_qty),
                    "type": order_type,
                    "status": "PARTIALLY_FILLED",
                    "exchange_order_id": exchange_id,
                    "reduce_only": reduce_only,
                }
                self._orders[client_order_id] = order
                self._apply_fill(symbol, side, fill_qty)
                self._trades.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "qty": str(fill_qty),
                        "price": "100000.0",
                        "client_order_id": client_order_id,
                        "time": int(time.time() * 1000),
                    }
                )
                if scenario.fault_type == "crash_at_partial":
                    self._crashed = True
                    raise GatewayCrash("crash_at_partial")
                return dict(order)
            if scenario.fault_type == "crash_at_acknowledged":
                exchange_id = str(uuid.uuid4())
                order = {
                    "client_order_id": client_order_id,
                    "symbol": symbol,
                    "side": side,
                    "origQty": str(qty),
                    "type": order_type,
                    "status": "UNKNOWN",
                    "exchange_order_id": exchange_id,
                    "reduce_only": reduce_only,
                }
                self._orders[client_order_id] = order
                self._crashed = True
                raise GatewayCrash("crash_at_acknowledged")

        exchange_id = str(uuid.uuid4())
        if order_type == "STOP_MARKET":
            order = {
                "client_order_id": client_order_id,
                "symbol": symbol,
                "side": side,
                "origQty": str(qty),
                "type": order_type,
                "stopPrice": str(stop_price) if stop_price else "0",
                "status": "NEW",
                "exchange_order_id": exchange_id,
                "reduce_only": reduce_only,
                "closePosition": False,
            }
        else:
            order = {
                "client_order_id": client_order_id,
                "symbol": symbol,
                "side": side,
                "origQty": str(qty),
                "executedQty": str(qty),
                "type": order_type,
                "status": "FILLED",
                "exchange_order_id": exchange_id,
                "reduce_only": reduce_only,
            }
            self._apply_fill(symbol, side, qty)
            self._trades.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "qty": str(qty),
                    "price": "100000.0",
                    "client_order_id": client_order_id,
                    "time": int(time.time() * 1000),
                }
            )
        self._orders[client_order_id] = order
        return dict(order)

    def cancel(
        self,
        *,
        client_order_id: str,
    ) -> dict[str, Any]:
        """Cancel an order by client_order_id."""
        if self._crashed:
            raise GatewayCrash("gateway_crashed_must_recover_first")
        if client_order_id not in self._orders:
            raise GatewayError("order_not_found")
        order = self._orders[client_order_id]
        if order["status"] in ("FILLED", "CANCELLED"):
            return dict(order)
        order["status"] = "CANCELLED"
        return dict(order)

    def query(
        self,
        *,
        client_order_id: str,
    ) -> dict[str, Any]:
        """Query an order's current state by client_order_id."""
        if client_order_id not in self._orders:
            raise GatewayError("order_not_found")
        return dict(self._orders[client_order_id])

    def snapshot(self) -> dict[str, Any]:
        """Return a REST full snapshot of all orders and positions.

        Used for crash recovery: covers WS gaps with a full state dump.
        """
        return {
            "orders": [dict(o) for o in self._orders.values()],
            "positions": dict(self._positions),
            "trades": list(self._trades),
            "funding_payments": [dict(fp) for fp in self._funding_payments],
        }

    def recover_from_crash(self) -> None:
        """Clear the crashed flag so queries can resume.

        UNKNOWN orders remain UNKNOWN until resolved by query.
        No replacement orders are created.
        """
        self._crashed = False

    def _apply_fill(self, symbol: str, side: str, qty: float) -> None:
        if side == "BUY":
            self._positions[symbol] = (
                self._positions.get(symbol, 0.0) + qty
            )
        elif side == "SELL":
            self._positions[symbol] = (
                self._positions.get(symbol, 0.0) - qty
            )
            if self._positions[symbol] < 0:
                self._positions[symbol] = 0.0

    @property
    def position_count(self) -> int:
        return sum(1 for v in self._positions.values() if abs(v) > 1e-12)

    @property
    def order_count(self) -> int:
        return len(self._orders)
