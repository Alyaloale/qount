"""Binance USD-M testnet venue client for certification.

Implements the VenueAdapter Protocol using real ccxt calls against
the Binance USD-M testnet (testnet.binancefuture.com).

orders_authorized is always False.  Testnet orders are operational
certification cost, never strategy PnL.

This module imports ccxt and is intentionally NOT in the
CERTIFICATION_GATEWAY_MODULES boundary group (which forbids ccxt).
The pure core (runner.py, contracts.py) never imports this module;
it is injected at runtime via the VenueAdapter Protocol.
"""

from __future__ import annotations

from typing import Any


class TestnetVenueClient:
    """Binance USD-M testnet venue client implementing VenueAdapter."""

    def __init__(self, exchange: Any) -> None:
        self._exchange = exchange
        self._orders_authorized: bool = False
        self._position_cache: dict[str, float] = {}
        self._order_meta: dict[str, dict[str, str]] = {}
        self._order_count: int = 0
        self._crashed: bool = False

    @property
    def orders_authorized(self) -> bool:
        return self._orders_authorized

    @property
    def position_count(self) -> int:
        return sum(
            1 for v in self._position_cache.values() if abs(v) > 1e-12
        )

    @property
    def order_count(self) -> int:
        return self._order_count

    @staticmethod
    def _to_ccxt_symbol(symbol: str) -> str:
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USDT:USDT"
        return symbol

    @staticmethod
    def _from_ccxt_status(
        status: str,
        filled: float,
        amount: float,
    ) -> str:
        if status == "closed" and filled >= amount - 1e-12:
            return "FILLED"
        if status == "closed" and filled > 1e-12:
            return "PARTIALLY_FILLED"
        if status in ("canceled", "expired", "rejected"):
            if filled > 1e-12:
                return "PARTIALLY_FILLED"
            return "CANCELLED"
        if status == "open" and filled > 1e-12:
            return "PARTIALLY_FILLED"
        return "NEW"

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
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        ccxt_side = side.lower()
        ccxt_type = order_type.lower()
        params: dict[str, Any] = {
            "newClientOrderId": client_order_id,
        }
        if reduce_only:
            params["reduceOnly"] = True
        if stop_price is not None:
            params["stopPrice"] = stop_price
        if order_type == "STOP_MARKET":
            params["closePosition"] = False
        response = self._exchange.create_order(
            symbol=ccxt_symbol,
            type=ccxt_type,
            side=ccxt_side,
            amount=qty,
            params=params,
        )
        self._order_count += 1
        info = response.get("info") if isinstance(response, dict) else None
        info = info if isinstance(info, dict) else {}
        algo_id = str(
            info.get("algoId") or response.get("algoId") or ""
        )
        is_algo = bool(algo_id)
        exchange_id = algo_id if is_algo else str(response.get("id", ""))
        meta: dict[str, str] = {
            "symbol": symbol,
            "exchange_order_id": exchange_id,
            "order_type": order_type,
        }
        if is_algo:
            client_algo_id = str(
                info.get("clientAlgoId")
                or response.get("clientAlgoId")
                or client_order_id
            )
            meta["is_algo"] = "true"
            meta["algo_id"] = algo_id
            meta["client_algo_id"] = client_algo_id
        self._order_meta[client_order_id] = meta
        filled = float(response.get("filled", 0.0) or 0.0)
        if filled > 0:
            if ccxt_side == "buy":
                self._position_cache[symbol] = (
                    self._position_cache.get(symbol, 0.0) + filled
                )
            else:
                self._position_cache[symbol] = (
                    self._position_cache.get(symbol, 0.0) - filled
                )
        status = self._from_ccxt_status(
            str(response.get("status", "open")),
            filled,
            qty,
        )
        result: dict[str, Any] = {
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "origQty": str(qty),
            "type": order_type,
            "status": status,
            "exchange_order_id": exchange_id,
            "reduce_only": reduce_only,
            # Preserve the venue response alongside the normalized contract.
            "raw_response": dict(response),
        }
        if filled > 0:
            result["executedQty"] = str(filled)
        if stop_price is not None:
            result["stopPrice"] = str(stop_price)
        result["closePosition"] = False
        return result

    def cancel(self, *, client_order_id: str) -> dict[str, Any]:
        meta = self._order_meta.get(client_order_id)
        if meta is None:
            raise ValueError(
                f"order_not_found_no_metadata:{client_order_id}"
            )
        if meta.get("is_algo") == "true":
            raw_response = self._exchange.fapiPrivateDeleteAlgoOrder(
                params={"algoId": meta["algo_id"]}
            )
            return {
                "client_order_id": client_order_id,
                "symbol": meta["symbol"],
                "status": "CANCELLED",
                "exchange_order_id": meta["exchange_order_id"],
                "raw_response": (
                    dict(raw_response)
                    if isinstance(raw_response, dict)
                    else raw_response
                ),
            }
        ccxt_symbol = self._to_ccxt_symbol(meta["symbol"])
        response = self._exchange.cancel_order(
            id=meta["exchange_order_id"],
            symbol=ccxt_symbol,
            params={"origClientOrderId": client_order_id},
        )
        return {
            "client_order_id": client_order_id,
            "symbol": meta["symbol"],
            "status": "CANCELLED",
            "exchange_order_id": meta["exchange_order_id"],
            "raw_response": (
                dict(response) if isinstance(response, dict) else response
            ),
        }

    def query(self, *, client_order_id: str) -> dict[str, Any]:
        meta = self._order_meta.get(client_order_id)
        if meta is None:
            raise ValueError(
                f"order_not_found_no_metadata:{client_order_id}"
            )
        if meta.get("is_algo") == "true":
            response = self._exchange.fapiPrivateGetAlgoOrder(
                params={"clientAlgoId": meta["client_algo_id"]}
            )
            info = response if isinstance(response, dict) else {}
            algo_status = str(
                info.get("algoStatus") or info.get("status") or "NEW"
            )
            status = "NEW"
            if algo_status in (
                "CANCELLED", "canceled", "expired", "EXPIRED"
            ):
                status = "CANCELLED"
            elif algo_status in (
                "FILLED", "filled", "TRIGGERED", "triggered"
            ):
                status = "FILLED"
            return {
                "client_order_id": client_order_id,
                "symbol": meta["symbol"],
                "status": status,
                "exchange_order_id": meta["exchange_order_id"],
                "raw_response": dict(response),
            }
        ccxt_symbol = self._to_ccxt_symbol(meta["symbol"])
        response = self._exchange.fetch_order(
            id=meta["exchange_order_id"],
            symbol=ccxt_symbol,
            params={"origClientOrderId": client_order_id},
        )
        filled = float(response.get("filled", 0.0) or 0.0)
        amount = float(response.get("amount", 0.0) or 0.0)
        status = self._from_ccxt_status(
            str(response.get("status", "open")),
            filled,
            amount if amount > 0 else filled,
        )
        result: dict[str, Any] = {
            "client_order_id": client_order_id,
            "symbol": meta["symbol"],
            "status": status,
            "exchange_order_id": meta["exchange_order_id"],
            "raw_response": dict(response),
        }
        if filled > 0:
            result["executedQty"] = str(filled)
        return result

    def snapshot(self) -> dict[str, Any]:
        orders: list[dict[str, Any]] = []
        try:
            raw_orders = self._exchange.fetch_open_orders(
                symbol=None,
            )
            for o in raw_orders:
                orders.append(dict(o))
        except Exception:
            pass
        positions: dict[str, float] = {}
        try:
            raw_positions = self._exchange.fetch_positions()
            for p in raw_positions:
                symbol = str(p.get("symbol", ""))
                contracts = float(p.get("contracts", 0.0) or 0.0)
                if abs(contracts) > 1e-12:
                    positions[symbol] = contracts
                    self._position_cache[symbol] = contracts
        except Exception:
            pass
        trades: list[dict[str, Any]] = []
        try:
            raw_trades = self._exchange.fetch_my_trades(
                symbol=None,
                limit=100,
            )
            for t in raw_trades:
                trades.append(dict(t))
        except Exception:
            pass
        return {
            "orders": orders,
            "positions": positions,
            "trades": trades,
            "funding_payments": [],
        }

    def recover_from_crash(self) -> None:
        self._refresh_positions()

    def _refresh_positions(self) -> None:
        try:
            raw_positions = self._exchange.fetch_positions()
            for p in raw_positions:
                symbol = str(p.get("symbol", ""))
                contracts = float(p.get("contracts", 0.0) or 0.0)
                self._position_cache[symbol] = contracts
        except Exception:
            pass
