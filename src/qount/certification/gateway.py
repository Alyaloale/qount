"""Local venue gateway for certification fault injection testing.

Simulates a Binance USD-M-like exchange in memory.  Supports:
- submit / cancel / query by client_order_id
- MARKET and STOP_MARKET order types
- Fault injection (ACK loss, timeout, partial fill, crash)
- Crash recovery via REST snapshot

orders_authorized is always False; no real network is used.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from qount.certification.fault_injection import FaultInjector
from qount.certification.fault_injection import FaultScenario


class GatewayError(Exception):
    """Raised when the gateway rejects an operation."""


class GatewayTimeout(GatewayError):
    """Raised when a fault injects a REST timeout."""


class GatewayAckLoss(GatewayError):
    """Raised when a fault injects an ACK loss."""


class GatewayCrash(GatewayError):
    """Raised when a fault injects a crash at a specific state."""


class LocalVenueGateway:
    """In-memory simulated exchange for certification testing."""

    def __init__(self) -> None:
        self._orders: dict[str, dict[str, Any]] = {}
        self._positions: dict[str, float] = {}
        self._trades: list[dict[str, Any]] = []
        self._fault_injector: FaultInjector | None = None
        self._crashed: bool = False
        self._orders_authorized: bool = False

    @property
    def orders_authorized(self) -> bool:
        return self._orders_authorized

    def set_fault_injector(self, injector: FaultInjector) -> None:
        self._fault_injector = injector

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
