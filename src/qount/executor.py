from __future__ import annotations

from typing import Any

import ccxt

from .exchange_utils import ExchangePool
from .exchange_utils import build_exchange
from .exchange_utils import extract_quote_balance
from .exchange_utils import market_amount_step
from .exchange_utils import minimum_executable_quantity
from .journal import Journal
from .models import ExecutionResult, MarketSnapshotBundle, RiskVerdict, utc_now
from .settings import Settings

PROTECTIVE_TAKE_PROFIT_PREFIX = "qount-tp-"
PROTECTIVE_STOP_LOSS_PREFIX = "qount-sl-"


class Executor:
    def __init__(self, settings: Settings, journal: Journal, exchange_pool: ExchangePool | None = None) -> None:
        self.settings = settings
        self.journal = journal
        self.exchange_pool = exchange_pool or ExchangePool(settings)

    def execute(self, verdict: RiskVerdict, bundle: MarketSnapshotBundle) -> ExecutionResult:
        if verdict.final_action == "hold":
            if self.settings.live_mode and verdict.protective_refresh_only:
                return self._refresh_live_protection(verdict, bundle)
            return ExecutionResult(
                status="noop",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action=verdict.final_action,
                side=None,
                quantity=None,
                notional_quote=None,
                pnl_quote=None,
                external_order_id=None,
                raw={"reasons": verdict.reasons},
            )

        if self.settings.paper_mode:
            return self._execute_paper(verdict, bundle)
        return self._execute_live(verdict, bundle)

    def cleanup_orphan_managed_orders(self, bundle: MarketSnapshotBundle) -> dict[str, Any]:
        if not self.settings.live_mode or not self.settings.contract_market:
            return {"canceled": [], "errors": []}
        exchange = self._exchange()
        sync_clock = getattr(exchange, "load_time_difference", None)
        if callable(sync_clock):
            sync_clock()
        open_position_symbols = {position.symbol for position in bundle.account.open_positions}
        canceled: list[dict[str, Any]] = []
        errors: list[str] = []
        for snapshot in bundle.symbols:
            symbol = snapshot.symbol
            if symbol in open_position_symbols:
                continue
            try:
                result = self._cancel_managed_protective_orders(exchange, symbol, ignore_errors=True)
                for item in result.get("canceled") or []:
                    canceled.append({"symbol": symbol, **item})
                for item in result.get("errors") or []:
                    errors.append(f"{symbol}:{item}")
            except Exception as exc:
                errors.append(f"{symbol}:cleanup_failed:{exc}")
        return {"canceled": canceled, "errors": errors}

    def _load_paper_portfolio(self) -> dict[str, Any]:
        return self.journal.get_runtime_state(
            "paper_portfolio",
            {
                "free_quote": self.settings.paper_starting_quote,
                "positions": {},
            },
        )

    def _save_paper_portfolio(self, portfolio: dict[str, Any]) -> None:
        self.journal.set_runtime_state("paper_portfolio", portfolio)

    def _find_price(self, bundle: MarketSnapshotBundle, symbol: str) -> float:
        for snapshot in bundle.symbols:
            if snapshot.symbol == symbol:
                return snapshot.last_price
        raise KeyError(f"missing price for {symbol}")

    def _execute_paper(self, verdict: RiskVerdict, bundle: MarketSnapshotBundle) -> ExecutionResult:
        portfolio = self._load_paper_portfolio()
        price = self._find_price(bundle, verdict.symbol)

        if self.settings.contract_market and verdict.final_action in {"buy", "sell"}:
            desired_side = "long" if verdict.final_action == "buy" else "short"
            current_position = portfolio["positions"].get(verdict.symbol)
            reversed_from: str | None = None
            if current_position and str(current_position.get("side") or "long") != desired_side:
                reversed_from = str(current_position.get("side") or "long")
                existing_quantity = float(current_position["quantity"])
                existing_entry_price = float(current_position["average_entry_price"])
                existing_margin_quote = float(current_position.get("margin_quote") or 0.0)
                realized_pnl_quote = (
                    (price - existing_entry_price) * existing_quantity
                    if reversed_from == "long"
                    else (existing_entry_price - price) * existing_quantity
                )
                portfolio["free_quote"] = float(portfolio["free_quote"]) + existing_margin_quote + realized_pnl_quote
                portfolio["positions"].pop(verdict.symbol, None)
                current_position = None

            margin_quote = min(bundle.account.equity_quote * verdict.final_size_pct, float(portfolio["free_quote"]))
            if margin_quote <= 0.0:
                return ExecutionResult(
                    status="paper_rejected",
                    mode=self.settings.mode,
                    symbol=verdict.symbol,
                    action=verdict.final_action,
                    side=verdict.final_action,
                    quantity=None,
                    notional_quote=None,
                    pnl_quote=None,
                    external_order_id=None,
                    raw={"reason": "insufficient_paper_free_quote"},
                )
            quantity = (margin_quote * float(self.settings.contract_leverage)) / price
            portfolio["free_quote"] = float(portfolio["free_quote"]) - margin_quote
            if current_position:
                old_qty = float(current_position["quantity"])
                old_entry = float(current_position["average_entry_price"])
                old_margin_quote = float(current_position.get("margin_quote") or 0.0)
                new_qty = old_qty + quantity
                avg_entry = ((old_qty * old_entry) + (quantity * price)) / new_qty
                new_margin_quote = old_margin_quote + margin_quote
            else:
                new_qty = quantity
                avg_entry = price
                new_margin_quote = margin_quote
            portfolio["positions"][verdict.symbol] = {
                "quantity": new_qty,
                "average_entry_price": avg_entry,
                "side": desired_side,
                "margin_quote": new_margin_quote,
            }
            self._save_paper_portfolio(portfolio)
            return ExecutionResult(
                status="paper_filled",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action=verdict.final_action,
                side=verdict.final_action,
                quantity=quantity,
                notional_quote=quantity * price,
                pnl_quote=None,
                external_order_id=None,
                raw={
                    "paper_portfolio": portfolio,
                    "margin_quote": margin_quote,
                    "position_side": desired_side,
                    "reversed_from": reversed_from,
                },
            )

        if verdict.final_action == "buy":
            spend = min(bundle.account.equity_quote * verdict.final_size_pct, float(portfolio["free_quote"]))
            quantity = spend / price
            portfolio["free_quote"] = float(portfolio["free_quote"]) - spend
            current_position = portfolio["positions"].get(verdict.symbol)
            if current_position:
                old_qty = float(current_position["quantity"])
                old_entry = float(current_position["average_entry_price"])
                new_qty = old_qty + quantity
                avg_entry = ((old_qty * old_entry) + spend) / new_qty
            else:
                new_qty = quantity
                avg_entry = price
            portfolio["positions"][verdict.symbol] = {
                "quantity": new_qty,
                "average_entry_price": avg_entry,
            }
            self._save_paper_portfolio(portfolio)
            return ExecutionResult(
                status="paper_filled",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="buy",
                side="buy",
                quantity=quantity,
                notional_quote=spend,
                pnl_quote=None,
                external_order_id=None,
                raw={"paper_portfolio": portfolio},
            )

        current_position = portfolio["positions"].get(verdict.symbol)
        if current_position is None:
            return ExecutionResult(
                status="paper_rejected",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action=verdict.final_action,
                side="sell",
                quantity=None,
                notional_quote=None,
                pnl_quote=None,
                external_order_id=None,
                raw={"reason": "missing_paper_position"},
            )
        close_fraction = min(max(float(verdict.close_fraction), 0.0), 1.0)
        if close_fraction <= 0.0:
            return ExecutionResult(
                status="paper_rejected",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action=verdict.final_action,
                side="sell",
                quantity=None,
                notional_quote=None,
                pnl_quote=None,
                external_order_id=None,
                raw={"reason": "invalid_close_fraction", "close_fraction": verdict.close_fraction},
            )
        position_quantity = float(current_position["quantity"])
        quantity = position_quantity * close_fraction
        entry_price = float(current_position["average_entry_price"])
        position_side = str(current_position.get("side") or "long")
        proceeds = quantity * price
        if self.settings.contract_market:
            margin_quote = float(current_position.get("margin_quote") or 0.0)
            released_margin_quote = margin_quote * close_fraction
            pnl_quote = (
                (price - entry_price) * quantity
                if position_side == "long"
                else (entry_price - price) * quantity
            )
            portfolio["free_quote"] = float(portfolio["free_quote"]) + released_margin_quote + pnl_quote
        else:
            released_margin_quote = None
            pnl_quote = proceeds - (quantity * entry_price)
            portfolio["free_quote"] = float(portfolio["free_quote"]) + proceeds
        remaining_quantity = max(position_quantity - quantity, 0.0)
        if remaining_quantity > 1e-12:
            current_position["quantity"] = remaining_quantity
            if self.settings.contract_market:
                current_position["margin_quote"] = max(float(current_position.get("margin_quote") or 0.0) - float(released_margin_quote or 0.0), 0.0)
            portfolio["positions"][verdict.symbol] = current_position
        else:
            portfolio["positions"].pop(verdict.symbol, None)
        self._save_paper_portfolio(portfolio)
        return ExecutionResult(
            status="paper_closed",
            mode=self.settings.mode,
            symbol=verdict.symbol,
            action="close",
            side="buy" if self.settings.contract_market and position_side == "short" else "sell",
            quantity=quantity,
            notional_quote=proceeds,
            pnl_quote=pnl_quote,
            external_order_id=None,
            raw={
                "paper_portfolio": portfolio,
                "close_fraction": close_fraction,
                "partial_close": remaining_quantity > 1e-12,
                "remaining_quantity": remaining_quantity,
                "released_margin_quote": released_margin_quote,
                "position_side": position_side,
            },
        )

    def _exchange(self) -> ccxt.binance:
        return self.exchange_pool.private()

    def _protective_order_client_id(self, kind: str) -> str:
        millis = int(utc_now().timestamp() * 1000)
        prefix = PROTECTIVE_TAKE_PROFIT_PREFIX if kind == "take_profit" else PROTECTIVE_STOP_LOSS_PREFIX
        return f"{prefix}{millis}"

    def _order_client_id(self, order: dict[str, Any]) -> str | None:
        info = order.get("info") or {}
        return (
            order.get("clientOrderId")
            or info.get("clientOrderId")
            or info.get("clientAlgoId")
            or info.get("origClientOrderId")
        )

    def _is_managed_protective_order(self, order: dict[str, Any], symbol: str) -> bool:
        if str(order.get("symbol") or "") != symbol:
            return False
        client_id = self._order_client_id(order)
        if not isinstance(client_id, str):
            return False
        return client_id.startswith(PROTECTIVE_TAKE_PROFIT_PREFIX) or client_id.startswith(PROTECTIVE_STOP_LOSS_PREFIX)

    def _managed_protective_order_kind(self, order: dict[str, Any]) -> str | None:
        client_id = self._order_client_id(order)
        if not isinstance(client_id, str):
            return None
        if client_id.startswith(PROTECTIVE_TAKE_PROFIT_PREFIX):
            return "take_profit"
        if client_id.startswith(PROTECTIVE_STOP_LOSS_PREFIX):
            return "stop_loss"
        return None

    def _managed_order_trigger_price(self, order: dict[str, Any]) -> float | None:
        info = order.get("info") or {}
        for key in ("stopPrice", "stop_price", "triggerPrice", "trigger_price"):
            value = order.get(key)
            if value is None and isinstance(info, dict):
                value = info.get(key)
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _fetch_open_orders(
        self,
        exchange: ccxt.binance,
        symbol: str,
        *,
        conditional: bool = False,
    ) -> list[dict[str, Any]]:
        params = {"trigger": True} if conditional else {}
        try:
            if params:
                return exchange.fetch_open_orders(symbol, params=params)
            return exchange.fetch_open_orders(symbol)
        except TypeError:
            # Test doubles may not expose the ccxt params surface.
            return exchange.fetch_open_orders(symbol)

    def _is_conditional_managed_order(self, order: dict[str, Any]) -> bool:
        info = order.get("info") or {}
        if any(key in info for key in ("algoId", "clientAlgoId", "algoType", "triggerPrice")):
            return True
        order_type = str(order.get("type") or info.get("type") or info.get("orderType") or "").upper()
        return order_type in {"TAKE_PROFIT_MARKET", "STOP_MARKET", "TAKE_PROFIT", "STOP"}

    def _list_managed_protective_orders(
        self,
        exchange: ccxt.binance,
        symbol: str,
        *,
        ignore_errors: bool = True,
    ) -> list[dict[str, Any]]:
        include_conditional = self.settings.contract_market
        queries = [False, True] if include_conditional else [False]
        seen: set[tuple[str, str | None, str]] = set()
        managed: list[dict[str, Any]] = []
        for conditional in queries:
            try:
                open_orders = self._fetch_open_orders(exchange, symbol, conditional=conditional)
            except Exception:
                if not ignore_errors:
                    raise
                continue
            for order in open_orders:
                key = (
                    str(order.get("id") or ""),
                    self._order_client_id(order),
                    str(order.get("symbol") or symbol),
                )
                if key in seen:
                    continue
                seen.add(key)
                if self._is_managed_protective_order(order, symbol):
                    managed.append(order)
        return managed

    def _cancel_order(
        self,
        exchange: ccxt.binance,
        order: dict[str, Any],
        symbol: str,
    ) -> None:
        order_id = str(order.get("id"))
        params: dict[str, Any] = {}
        client_id = self._order_client_id(order)
        if self.settings.contract_market and self._is_conditional_managed_order(order):
            params["trigger"] = True
            if isinstance(client_id, str) and client_id:
                params["clientAlgoId"] = client_id
        exchange.cancel_order(order_id, symbol, params=params or None)

    def _managed_protective_orders(self, exchange: ccxt.binance, symbol: str) -> list[dict[str, Any]]:
        try:
            open_orders = self._list_managed_protective_orders(exchange, symbol, ignore_errors=True)
        except Exception:
            return []
        return open_orders

    def _protective_orders_match_targets(
        self,
        exchange: ccxt.binance,
        symbol: str,
        *,
        position_side: str | None,
        quantity: float,
        take_profit_price: float | None,
        stop_price: float | None,
    ) -> bool:
        if position_side not in {"long", "short"}:
            return False
        desired_side = "sell" if position_side == "long" else "buy"
        managed_orders = self._managed_protective_orders(exchange, symbol)
        desired: dict[str, float | None] = {
            "take_profit": take_profit_price,
            "stop_loss": stop_price,
        }
        desired_count = sum(1 for value in desired.values() if value is not None and value > 0.0)
        if len(managed_orders) != desired_count:
            return False

        quantity_tol = 1e-9
        for kind, desired_trigger in desired.items():
            order = next((item for item in managed_orders if self._managed_protective_order_kind(item) == kind), None)
            if desired_trigger is None or desired_trigger <= 0.0:
                if order is not None:
                    return False
                continue
            if order is None:
                return False
            if str(order.get("side") or "").lower() != desired_side:
                return False
            try:
                order_amount = float(order.get("amount") or 0.0)
            except (TypeError, ValueError):
                return False
            if abs(order_amount - quantity) > quantity_tol:
                return False
            current_trigger = self._managed_order_trigger_price(order)
            if current_trigger is None:
                return False
            trigger_tol = max(abs(desired_trigger) * 1e-8, 1e-8)
            if abs(current_trigger - desired_trigger) > trigger_tol:
                return False
        return True

    def _cancel_managed_protective_orders(
        self,
        exchange: ccxt.binance,
        symbol: str,
        *,
        ignore_errors: bool,
    ) -> dict[str, Any]:
        canceled: list[dict[str, Any]] = []
        errors: list[str] = []
        try:
            open_orders = self._list_managed_protective_orders(exchange, symbol, ignore_errors=ignore_errors)
        except Exception as exc:
            if not ignore_errors:
                raise
            return {"canceled": canceled, "errors": [f"fetch_managed_protective_orders_failed:{exc}"]}

        for order in open_orders:
            order_id = str(order.get("id"))
            try:
                self._cancel_order(exchange, order, symbol)
                canceled.append(
                    {
                        "id": order_id,
                        "client_order_id": self._order_client_id(order),
                        "type": order.get("type"),
                    }
                )
            except Exception as exc:
                if not ignore_errors:
                    raise
                errors.append(f"cancel_failed:{order_id}:{exc}")
        return {"canceled": canceled, "errors": errors}

    def _market_order_average_price(self, order: dict[str, Any], fallback_price: float) -> float:
        average = order.get("average")
        try:
            average_value = float(average) if average is not None else 0.0
        except (TypeError, ValueError):
            average_value = 0.0
        if average_value > 0.0:
            return average_value

        cost = order.get("cost")
        filled = order.get("filled")
        try:
            cost_value = float(cost) if cost is not None else 0.0
            filled_value = float(filled) if filled is not None else 0.0
        except (TypeError, ValueError):
            cost_value = 0.0
            filled_value = 0.0
        if cost_value > 0.0 and filled_value > 0.0:
            return cost_value / filled_value
        return fallback_price

    def _market_order_quantity(self, order: dict[str, Any], fallback_quantity: float) -> float:
        filled = order.get("filled")
        try:
            filled_value = float(filled) if filled is not None else 0.0
        except (TypeError, ValueError):
            filled_value = 0.0
        return filled_value if filled_value > 0.0 else fallback_quantity

    def _protective_orders_for_open(
        self,
        verdict: RiskVerdict,
        *,
        entry_price: float,
        quantity: float,
    ) -> list[dict[str, Any]]:
        if not self.settings.contract_market or quantity <= 0.0:
            return []
        if verdict.final_action not in {"buy", "sell"}:
            return []

        exit_side = "sell" if verdict.final_action == "buy" else "buy"
        orders: list[dict[str, Any]] = []
        if verdict.take_profit_pct > 0.0:
            trigger_price = (
                entry_price * (1.0 + verdict.take_profit_pct)
                if verdict.final_action == "buy"
                else entry_price * (1.0 - verdict.take_profit_pct)
            )
            orders.append(
                {
                    "kind": "take_profit",
                    "type": "TAKE_PROFIT_MARKET",
                    "side": exit_side,
                    "quantity": quantity,
                    "trigger_price": trigger_price,
                    "client_order_id": self._protective_order_client_id("take_profit"),
                }
            )
        if verdict.stop_loss_pct > 0.0:
            trigger_price = (
                entry_price * (1.0 - verdict.stop_loss_pct)
                if verdict.final_action == "buy"
                else entry_price * (1.0 + verdict.stop_loss_pct)
            )
            orders.append(
                {
                    "kind": "stop_loss",
                    "type": "STOP_MARKET",
                    "side": exit_side,
                    "quantity": quantity,
                    "trigger_price": trigger_price,
                    "client_order_id": self._protective_order_client_id("stop_loss"),
                }
            )
        return orders

    def _place_protective_orders(
        self,
        exchange: ccxt.binance,
        verdict: RiskVerdict,
        *,
        entry_price: float,
        quantity: float,
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        for spec in self._protective_orders_for_open(verdict, entry_price=entry_price, quantity=quantity):
            order = exchange.create_order(
                verdict.symbol,
                spec["type"],
                spec["side"],
                spec["quantity"],
                None,
                {
                    "stopPrice": spec["trigger_price"],
                    "reduceOnly": True,
                    "positionSide": "BOTH",
                    "workingType": "CONTRACT_PRICE",
                    "newClientOrderId": spec["client_order_id"],
                },
            )
            created.append(
                {
                    "kind": spec["kind"],
                    "type": spec["type"],
                    "side": spec["side"],
                    "quantity": spec["quantity"],
                    "trigger_price": spec["trigger_price"],
                    "client_order_id": spec["client_order_id"],
                    "id": str(order.get("id")),
                    "raw": order,
                }
            )
        return created

    def _place_remaining_protective_orders(
        self,
        exchange: ccxt.binance,
        *,
        symbol: str,
        position_side: str | None,
        quantity: float,
        take_profit_price: float | None,
        stop_price: float | None,
    ) -> list[dict[str, Any]]:
        if not self.settings.contract_market or quantity <= 0.0:
            return []
        if position_side not in {"long", "short"}:
            return []
        exit_side = "sell" if position_side == "long" else "buy"
        specs: list[dict[str, Any]] = []
        if take_profit_price is not None and take_profit_price > 0.0:
            specs.append(
                {
                    "kind": "take_profit",
                    "type": "TAKE_PROFIT_MARKET",
                    "trigger_price": take_profit_price,
                    "client_order_id": self._protective_order_client_id("take_profit"),
                }
            )
        if stop_price is not None and stop_price > 0.0:
            specs.append(
                {
                    "kind": "stop_loss",
                    "type": "STOP_MARKET",
                    "trigger_price": stop_price,
                    "client_order_id": self._protective_order_client_id("stop_loss"),
                }
            )

        created: list[dict[str, Any]] = []
        for spec in specs:
            order = exchange.create_order(
                symbol,
                spec["type"],
                exit_side,
                quantity,
                None,
                {
                    "stopPrice": spec["trigger_price"],
                    "reduceOnly": True,
                    "positionSide": "BOTH",
                    "workingType": "CONTRACT_PRICE",
                    "newClientOrderId": spec["client_order_id"],
                },
            )
            created.append(
                {
                    "kind": spec["kind"],
                    "type": spec["type"],
                    "side": exit_side,
                    "quantity": quantity,
                    "trigger_price": spec["trigger_price"],
                    "client_order_id": spec["client_order_id"],
                    "id": str(order.get("id")),
                    "raw": order,
                }
            )
        return created

    def _emergency_flatten_after_protective_failure(
        self,
        exchange: ccxt.binance,
        verdict: RiskVerdict,
        *,
        quantity: float,
    ) -> dict[str, Any]:
        if quantity <= 0.0:
            return {"status": "skipped", "reason": "missing_quantity"}
        close_side = "sell" if verdict.final_action == "buy" else "buy"
        order = exchange.create_order(
            verdict.symbol,
            "market",
            close_side,
            quantity,
            None,
            {"reduceOnly": True, "positionSide": "BOTH"},
        )
        return {
            "status": str(order.get("status", "submitted")),
            "side": close_side,
            "quantity": quantity,
            "id": str(order.get("id")),
            "raw": order,
        }

    def _emergency_flatten_position(
        self,
        exchange: ccxt.binance,
        *,
        symbol: str,
        position_side: str | None,
        quantity: float,
    ) -> dict[str, Any]:
        if quantity <= 0.0:
            return {"status": "skipped", "reason": "missing_quantity"}
        close_side = "buy" if position_side == "short" else "sell"
        order = exchange.create_order(
            symbol,
            "market",
            close_side,
            quantity,
            None,
            {"reduceOnly": True, "positionSide": "BOTH"},
        )
        return {
            "status": str(order.get("status", "submitted")),
            "side": close_side,
            "quantity": quantity,
            "id": str(order.get("id")),
            "raw": order,
        }

    def _configure_contract_market(self, exchange: ccxt.binance, symbol: str) -> None:
        exchange.set_margin_mode(self.settings.contract_margin_mode, symbol)
        exchange.set_leverage(self.settings.contract_leverage, symbol)

    def _normalized_open_quantity(
        self,
        exchange: ccxt.binance,
        symbol: str,
        market: dict[str, Any],
        *,
        requested_notional: float,
        price: float,
        min_cost: float,
        min_amount: float,
    ) -> dict[str, float | None]:
        if price <= 0:
            return {
                "quantity": 0.0,
                "rounded_notional": 0.0,
                "amount_step": market_amount_step(market),
                "minimum_quantity": float(min_amount),
                "minimum_notional": 0.0,
            }
        amount_step = market_amount_step(market)
        minimum_quantity = minimum_executable_quantity(
            price=price,
            min_cost=min_cost,
            min_amount=min_amount,
            amount_step=amount_step,
        )
        requested_quantity = requested_notional / price
        raw_quantity = max(requested_quantity, minimum_quantity)
        quantity = float(exchange.amount_to_precision(symbol, raw_quantity))
        rounded_notional = quantity * price
        return {
            "quantity": quantity,
            "rounded_notional": rounded_notional,
            "amount_step": amount_step,
            "minimum_quantity": minimum_quantity,
            "minimum_notional": minimum_quantity * price,
        }

    def _execute_live(self, verdict: RiskVerdict, bundle: MarketSnapshotBundle) -> ExecutionResult:
        exchange = self._exchange()
        sync_clock = getattr(exchange, "load_time_difference", None)
        if callable(sync_clock):
            sync_clock()
        markets = exchange.load_markets()
        market = markets[verdict.symbol]
        price = self._find_price(bundle, verdict.symbol)
        min_cost = ((market.get("limits") or {}).get("cost") or {}).get("min") or self.settings.min_notional_quote
        min_amount = ((market.get("limits") or {}).get("amount") or {}).get("min") or 0.0

        if self.settings.contract_market:
            if verdict.final_action in {"buy", "sell"}:
                cleanup = self._cancel_managed_protective_orders(exchange, verdict.symbol, ignore_errors=False)
                self._configure_contract_market(exchange, verdict.symbol)
                live_balance = exchange.fetch_balance()
                quote_balance = extract_quote_balance(live_balance, self.settings)
                leverage = float(self.settings.contract_leverage)
                available_notional = quote_balance["quote_free"] * leverage
                effective_min_notional = max(float(min_cost), self.settings.min_notional_quote * leverage)
                target_margin_quote = min(
                    bundle.account.equity_quote * verdict.final_size_pct,
                    bundle.account.free_quote,
                    quote_balance["quote_free"],
                )
                target_notional = min(target_margin_quote * leverage, available_notional)
                if target_notional < effective_min_notional:
                    return ExecutionResult(
                        status="live_rejected",
                        mode=self.settings.mode,
                        symbol=verdict.symbol,
                        action=verdict.final_action,
                        side=verdict.final_action,
                        quantity=None,
                        notional_quote=target_notional,
                        pnl_quote=None,
                        external_order_id=None,
                        raw={
                            "reason": "below_market_min_cost",
                            "min_cost": min_cost,
                            "effective_min_notional_quote": effective_min_notional,
                            "available_notional_quote": available_notional,
                            "target_margin_quote": target_margin_quote,
                        },
                    )
                normalized = self._normalized_open_quantity(
                    exchange,
                    verdict.symbol,
                    market,
                    requested_notional=target_notional,
                    price=price,
                    min_cost=effective_min_notional,
                    min_amount=float(min_amount),
                )
                quantity = float(normalized["quantity"] or 0.0)
                rounded_notional = float(normalized["rounded_notional"] or 0.0)
                if quantity < float(min_amount):
                    return ExecutionResult(
                        status="live_rejected",
                        mode=self.settings.mode,
                        symbol=verdict.symbol,
                        action=verdict.final_action,
                        side=verdict.final_action,
                        quantity=quantity,
                        notional_quote=target_notional,
                        pnl_quote=None,
                        external_order_id=None,
                        raw={
                            "reason": "below_market_min_amount",
                            "min_amount": min_amount,
                            "amount_step": normalized["amount_step"],
                            "minimum_executable_quantity": normalized["minimum_quantity"],
                        },
                    )
                if rounded_notional < effective_min_notional:
                    return ExecutionResult(
                        status="live_rejected",
                        mode=self.settings.mode,
                        symbol=verdict.symbol,
                        action=verdict.final_action,
                        side=verdict.final_action,
                        quantity=quantity,
                        notional_quote=rounded_notional,
                        pnl_quote=None,
                        external_order_id=None,
                        raw={
                            "reason": "below_market_min_cost_after_rounding",
                            "min_cost": min_cost,
                            "effective_min_notional_quote": effective_min_notional,
                            "requested_notional_quote": target_notional,
                            "target_margin_quote": target_margin_quote,
                            "rounded_notional_quote": rounded_notional,
                            "amount_step": normalized["amount_step"],
                            "minimum_executable_quantity": normalized["minimum_quantity"],
                            "minimum_executable_notional_quote": normalized["minimum_notional"],
                        },
                    )
                if rounded_notional > available_notional + 1e-9:
                    return ExecutionResult(
                        status="live_rejected",
                        mode=self.settings.mode,
                        symbol=verdict.symbol,
                        action=verdict.final_action,
                        side=verdict.final_action,
                        quantity=quantity,
                        notional_quote=rounded_notional,
                        pnl_quote=None,
                        external_order_id=None,
                        raw={
                            "reason": "insufficient_free_quote_for_min_executable_size",
                            "requested_notional_quote": target_notional,
                            "target_margin_quote": target_margin_quote,
                            "rounded_notional_quote": rounded_notional,
                            "available_notional_quote": available_notional,
                            "amount_step": normalized["amount_step"],
                            "minimum_executable_quantity": normalized["minimum_quantity"],
                            "minimum_executable_notional_quote": normalized["minimum_notional"],
                        },
                    )
                side = "buy" if verdict.final_action == "buy" else "sell"
                order = exchange.create_order(
                    verdict.symbol,
                    "market",
                    side,
                    quantity,
                    None,
                    {"positionSide": "BOTH"},
                )
                filled_quantity = self._market_order_quantity(order, quantity)
                entry_price = self._market_order_average_price(order, price)
                try:
                    protective_orders = self._place_protective_orders(
                        exchange,
                        verdict,
                        entry_price=entry_price,
                        quantity=filled_quantity,
                    )
                except Exception as exc:
                    protective_cleanup = self._cancel_managed_protective_orders(exchange, verdict.symbol, ignore_errors=True)
                    emergency_close = self._emergency_flatten_after_protective_failure(
                        exchange,
                        verdict,
                        quantity=filled_quantity,
                    )
                    raise RuntimeError(
                        f"protective_order_placement_failed:{exc}; emergency_close={emergency_close.get('status')}; cleanup_errors={protective_cleanup.get('errors')}"
                    ) from exc
                return ExecutionResult(
                    status=str(order.get("status", "submitted")),
                    mode=self.settings.mode,
                    symbol=verdict.symbol,
                    action=verdict.final_action,
                    side=side,
                    quantity=filled_quantity,
                    notional_quote=filled_quantity * entry_price,
                    pnl_quote=None,
                    external_order_id=str(order.get("id")),
                    raw={
                        "entry_order": order,
                        "entry_cleanup": cleanup,
                        "entry_price": entry_price,
                        "protective_orders": protective_orders,
                    },
                )

            position = next((item for item in bundle.account.open_positions if item.symbol == verdict.symbol), None)
            if position is None:
                return ExecutionResult(
                    status="live_rejected",
                    mode=self.settings.mode,
                    symbol=verdict.symbol,
                    action="close",
                    side=None,
                    quantity=None,
                    notional_quote=None,
                    pnl_quote=None,
                    external_order_id=None,
                    raw={"reason": "missing_live_position"},
                )
            close_fraction = min(max(float(verdict.close_fraction), 0.0), 1.0)
            if close_fraction <= 0.0:
                return ExecutionResult(
                    status="live_rejected",
                    mode=self.settings.mode,
                    symbol=verdict.symbol,
                    action="close",
                    side=None,
                    quantity=None,
                    notional_quote=None,
                    pnl_quote=None,
                    external_order_id=None,
                    raw={"reason": "invalid_close_fraction", "close_fraction": verdict.close_fraction},
                )
            requested_close_quantity = float(position.quantity) * close_fraction
            quantity = float(exchange.amount_to_precision(verdict.symbol, requested_close_quantity))
            partial_close = close_fraction < 1.0
            remaining_quantity = 0.0
            if partial_close:
                remaining_quantity = max(float(position.quantity) - quantity, 0.0)
                remaining_quantity = float(exchange.amount_to_precision(verdict.symbol, remaining_quantity)) if remaining_quantity > 0.0 else 0.0
                if remaining_quantity < float(min_amount):
                    return ExecutionResult(
                        status="live_rejected",
                        mode=self.settings.mode,
                        symbol=verdict.symbol,
                        action="close",
                        side=None,
                        quantity=quantity,
                        notional_quote=quantity * price,
                        pnl_quote=None,
                        external_order_id=None,
                        raw={
                            "reason": "partial_remaining_below_market_min_amount",
                            "close_fraction": close_fraction,
                            "remaining_quantity": remaining_quantity,
                            "min_amount": min_amount,
                        },
                    )
                if verdict.remaining_stop_price is None or verdict.remaining_stop_price <= 0.0:
                    return ExecutionResult(
                        status="live_rejected",
                        mode=self.settings.mode,
                        symbol=verdict.symbol,
                        action="close",
                        side=None,
                        quantity=quantity,
                        notional_quote=quantity * price,
                        pnl_quote=None,
                        external_order_id=None,
                        raw={
                            "reason": "partial_missing_remaining_stop_price",
                            "close_fraction": close_fraction,
                            "remaining_quantity": remaining_quantity,
                        },
                    )
            if quantity < float(min_amount):
                return ExecutionResult(
                    status="live_rejected",
                    mode=self.settings.mode,
                    symbol=verdict.symbol,
                    action="close",
                    side=None,
                    quantity=quantity,
                    notional_quote=quantity * price,
                    pnl_quote=None,
                    external_order_id=None,
                    raw={"reason": "below_market_min_amount", "min_amount": min_amount},
                )
            cleanup = self._cancel_managed_protective_orders(exchange, verdict.symbol, ignore_errors=False)
            close_side = "sell" if position.side != "short" else "buy"
            order = exchange.create_order(
                verdict.symbol,
                "market",
                close_side,
                quantity,
                None,
                {"reduceOnly": True, "positionSide": "BOTH"},
            )
            filled_quantity = self._market_order_quantity(order, quantity)
            remaining_quantity = max(float(position.quantity) - filled_quantity, 0.0) if partial_close else 0.0
            remaining_quantity = float(exchange.amount_to_precision(verdict.symbol, remaining_quantity)) if remaining_quantity > 0.0 else 0.0
            remaining_protective_orders: list[dict[str, Any]] = []
            emergency_flatten: dict[str, Any] | None = None
            protective_replacement_error = None
            if partial_close and remaining_quantity >= float(min_amount):
                try:
                    remaining_protective_orders = self._place_remaining_protective_orders(
                        exchange,
                        symbol=verdict.symbol,
                        position_side=position.side,
                        quantity=remaining_quantity,
                        take_profit_price=verdict.remaining_take_profit_price,
                        stop_price=verdict.remaining_stop_price,
                    )
                except Exception as exc:
                    protective_replacement_error = str(exc)
                    self._cancel_managed_protective_orders(exchange, verdict.symbol, ignore_errors=True)
                    emergency_flatten = self._emergency_flatten_position(
                        exchange,
                        symbol=verdict.symbol,
                        position_side=position.side,
                        quantity=remaining_quantity,
                    )
                    remaining_quantity = 0.0
            post_cleanup = self._cancel_managed_protective_orders(exchange, verdict.symbol, ignore_errors=True) if not partial_close else {"canceled": [], "errors": []}
            result_status = str(order.get("status", "submitted"))
            if emergency_flatten is not None:
                result_status = "emergency_flattened_after_partial_protection_failure"
            return ExecutionResult(
                status=result_status,
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="close",
                side=close_side,
                quantity=filled_quantity,
                notional_quote=filled_quantity * price,
                pnl_quote=None,
                external_order_id=str(order.get("id")),
                raw={
                    "close_order": order,
                    "close_fraction": close_fraction,
                    "partial_close": partial_close,
                    "pre_close_cleanup": cleanup,
                    "post_close_cleanup": post_cleanup,
                    "remaining_quantity": remaining_quantity,
                    "remaining_take_profit_price": verdict.remaining_take_profit_price,
                    "remaining_stop_price": verdict.remaining_stop_price,
                    "remaining_protective_orders": remaining_protective_orders,
                    "protective_replacement_error": protective_replacement_error,
                    "emergency_flatten": emergency_flatten,
                },
            )

        if verdict.final_action == "buy":
            live_balance = exchange.fetch_balance()
            free_quote_live = float(live_balance["free"].get(self.settings.quote_currency, 0.0))
            spend = min(bundle.account.equity_quote * verdict.final_size_pct, bundle.account.free_quote, free_quote_live)
            if spend < float(min_cost):
                return ExecutionResult(
                    status="live_rejected",
                    mode=self.settings.mode,
                    symbol=verdict.symbol,
                    action="buy",
                    side="buy",
                    quantity=None,
                    notional_quote=spend,
                    pnl_quote=None,
                    external_order_id=None,
                    raw={"reason": "below_market_min_cost", "min_cost": min_cost, "free_quote_live": free_quote_live},
                )
            normalized = self._normalized_open_quantity(
                exchange,
                verdict.symbol,
                market,
                requested_notional=spend,
                price=price,
                min_cost=float(min_cost),
                min_amount=float(min_amount),
            )
            quantity = float(normalized["quantity"] or 0.0)
            rounded_notional = float(normalized["rounded_notional"] or 0.0)
            if quantity < float(min_amount):
                return ExecutionResult(
                    status="live_rejected",
                    mode=self.settings.mode,
                    symbol=verdict.symbol,
                    action="buy",
                    side="buy",
                    quantity=quantity,
                    notional_quote=spend,
                    pnl_quote=None,
                    external_order_id=None,
                    raw={
                        "reason": "below_market_min_amount",
                        "min_amount": min_amount,
                        "amount_step": normalized["amount_step"],
                        "minimum_executable_quantity": normalized["minimum_quantity"],
                    },
                )
            if rounded_notional < float(min_cost):
                return ExecutionResult(
                    status="live_rejected",
                    mode=self.settings.mode,
                    symbol=verdict.symbol,
                    action="buy",
                    side="buy",
                    quantity=quantity,
                    notional_quote=rounded_notional,
                    pnl_quote=None,
                    external_order_id=None,
                    raw={
                        "reason": "below_market_min_cost_after_rounding",
                        "min_cost": min_cost,
                        "requested_notional_quote": spend,
                        "rounded_notional_quote": rounded_notional,
                        "amount_step": normalized["amount_step"],
                        "minimum_executable_quantity": normalized["minimum_quantity"],
                        "minimum_executable_notional_quote": normalized["minimum_notional"],
                    },
                )
            if rounded_notional > free_quote_live + 1e-9:
                return ExecutionResult(
                    status="live_rejected",
                    mode=self.settings.mode,
                    symbol=verdict.symbol,
                    action="buy",
                    side="buy",
                    quantity=quantity,
                    notional_quote=rounded_notional,
                    pnl_quote=None,
                    external_order_id=None,
                    raw={
                        "reason": "insufficient_free_quote_for_min_executable_size",
                        "requested_notional_quote": spend,
                        "rounded_notional_quote": rounded_notional,
                        "free_quote_live": free_quote_live,
                        "amount_step": normalized["amount_step"],
                        "minimum_executable_quantity": normalized["minimum_quantity"],
                        "minimum_executable_notional_quote": normalized["minimum_notional"],
                    },
                )
            order = exchange.create_order(verdict.symbol, "market", "buy", quantity)
            return ExecutionResult(
                status=str(order.get("status", "submitted")),
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="buy",
                side="buy",
                quantity=quantity,
                notional_quote=quantity * price,
                pnl_quote=None,
                external_order_id=str(order.get("id")),
                raw=order,
            )

        position = next((item for item in bundle.account.open_positions if item.symbol == verdict.symbol), None)
        if position is None:
            return ExecutionResult(
                status="live_rejected",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="close",
                side="sell",
                quantity=None,
                notional_quote=None,
                pnl_quote=None,
                external_order_id=None,
                raw={"reason": "missing_live_position"},
            )
        quantity = float(exchange.amount_to_precision(verdict.symbol, position.quantity))
        if quantity < float(min_amount):
            return ExecutionResult(
                status="live_rejected",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="close",
                side="sell",
                quantity=quantity,
                notional_quote=quantity * price,
                pnl_quote=None,
                external_order_id=None,
                raw={"reason": "below_market_min_amount", "min_amount": min_amount},
            )
        order = exchange.create_order(verdict.symbol, "market", "sell", quantity)
        return ExecutionResult(
            status=str(order.get("status", "submitted")),
            mode=self.settings.mode,
            symbol=verdict.symbol,
            action="close",
            side="sell",
            quantity=quantity,
            notional_quote=quantity * price,
            pnl_quote=None,
            external_order_id=str(order.get("id")),
            raw=order,
        )

    def _refresh_live_protection(self, verdict: RiskVerdict, bundle: MarketSnapshotBundle) -> ExecutionResult:
        if not self.settings.contract_market:
            return ExecutionResult(
                status="noop",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="hold",
                side=None,
                quantity=None,
                notional_quote=None,
                pnl_quote=None,
                external_order_id=None,
                raw={"reason": "protective_refresh_non_contract_market"},
            )

        position = next((item for item in bundle.account.open_positions if item.symbol == verdict.symbol), None)
        if position is None:
            return ExecutionResult(
                status="noop",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="hold",
                side=None,
                quantity=None,
                notional_quote=None,
                pnl_quote=None,
                external_order_id=None,
                raw={"reason": "protective_refresh_missing_position"},
            )

        exchange = self._exchange()
        sync_clock = getattr(exchange, "load_time_difference", None)
        if callable(sync_clock):
            sync_clock()
        markets = exchange.load_markets()
        market = markets[verdict.symbol]
        min_amount = ((market.get("limits") or {}).get("amount") or {}).get("min") or 0.0
        quantity = float(exchange.amount_to_precision(verdict.symbol, position.quantity))
        if quantity < float(min_amount):
            return ExecutionResult(
                status="protective_refresh_skipped",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="hold",
                side=None,
                quantity=quantity,
                notional_quote=quantity * position.mark_price,
                pnl_quote=None,
                external_order_id=None,
                raw={
                    "reason": "protective_refresh_below_market_min_amount",
                    "min_amount": min_amount,
                },
            )

        take_profit_price = verdict.remaining_take_profit_price
        stop_price = verdict.remaining_stop_price
        if (take_profit_price is None or take_profit_price <= 0.0) and (stop_price is None or stop_price <= 0.0):
            return ExecutionResult(
                status="noop",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="hold",
                side=None,
                quantity=None,
                notional_quote=None,
                pnl_quote=None,
                external_order_id=None,
                raw={"reason": "protective_refresh_missing_targets"},
            )

        if self._protective_orders_match_targets(
            exchange,
            verdict.symbol,
            position_side=position.side,
            quantity=quantity,
            take_profit_price=take_profit_price,
            stop_price=stop_price,
        ):
            return ExecutionResult(
                status="noop",
                mode=self.settings.mode,
                symbol=verdict.symbol,
                action="hold",
                side=None,
                quantity=None,
                notional_quote=None,
                pnl_quote=None,
                external_order_id=None,
                raw={
                    "reason": "protective_refresh_already_current",
                    "protective_refresh_reason": verdict.protective_refresh_reason,
                    "take_profit_price": take_profit_price,
                    "stop_price": stop_price,
                },
            )

        cleanup = self._cancel_managed_protective_orders(exchange, verdict.symbol, ignore_errors=False)
        replacement_orders: list[dict[str, Any]] = []
        emergency_flatten: dict[str, Any] | None = None
        replacement_error = None
        try:
            replacement_orders = self._place_remaining_protective_orders(
                exchange,
                symbol=verdict.symbol,
                position_side=position.side,
                quantity=quantity,
                take_profit_price=take_profit_price,
                stop_price=stop_price,
            )
        except Exception as exc:
            replacement_error = str(exc)
            self._cancel_managed_protective_orders(exchange, verdict.symbol, ignore_errors=True)
            emergency_flatten = self._emergency_flatten_position(
                exchange,
                symbol=verdict.symbol,
                position_side=position.side,
                quantity=quantity,
            )

        status = "protective_refreshed" if emergency_flatten is None else "emergency_flattened_after_protective_refresh_failure"
        return ExecutionResult(
            status=status,
            mode=self.settings.mode,
            symbol=verdict.symbol,
            action="hold",
            side=None,
            quantity=None,
            notional_quote=None,
            pnl_quote=None,
            external_order_id=None,
            raw={
                "reason": "protective_refresh",
                "protective_refresh_reason": verdict.protective_refresh_reason,
                "pre_refresh_cleanup": cleanup,
                "replacement_orders": replacement_orders,
                "replacement_error": replacement_error,
                "emergency_flatten": emergency_flatten,
                "take_profit_price": take_profit_price,
                "stop_price": stop_price,
                "quantity": quantity,
            },
        )
