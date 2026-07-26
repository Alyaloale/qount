"""Pure contracts for the Binance Stocks Trading SAPI module.

``BUY_SELL`` describes accepted transaction sides. It does not grant short
selling: stock ``SELL`` remains sell-to-close unless a separate borrow or
margin contract is observed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from qount.contracts import InstrumentId
from qount.contracts import ProductCapability
from qount.contracts import canonical_hash


BINANCE_STOCKS_API_PREFIX = "/sapi/v1/equity"
BINANCE_STOCKS_DISCLAIMER_PATH = f"{BINANCE_STOCKS_API_PREFIX}/account/disclaimer"
BINANCE_STOCKS_DISCLAIMER_REQUIRED_CODE = 486410

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,31}$")
_QUOTE_ASSET_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
_CLIENT_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32,36}$")
_TRADABILITY = {"BUY_SELL", "BUY", "SELL", "NONE"}
_SIDES = {"BUY", "SELL"}
_ORDER_TYPES = {"MARKET", "LIMIT"}
_TIME_IN_FORCE = {"DAY", "GTC"}
_TRADING_SESSIONS = {"RTH", "EXTENDED", "24H"}
_WALLET_TYPES = {"CARD", "MAIN"}


class BinanceStocksContractError(ValueError):
    """Raised when an official Binance Stocks payload violates its contract."""


def _decimal(value: object, *, name: str, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise BinanceStocksContractError(f"{name}_invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BinanceStocksContractError(f"{name}_invalid") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise BinanceStocksContractError(f"{name}_invalid")
    return result


def _decimal_text(value: object, *, name: str, positive: bool = False) -> str:
    result = _decimal(value, name=name, positive=positive)
    return format(result, "f")


def _integer(value: object, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise BinanceStocksContractError(f"{name}_invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise BinanceStocksContractError(f"{name}_invalid") from exc
    if result < minimum or result != value:
        raise BinanceStocksContractError(f"{name}_invalid")
    return result


def _boolean(value: object, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise BinanceStocksContractError(f"{name}_invalid")
    return value


@dataclass(frozen=True)
class BinanceStockSymbolRule:
    symbol: str
    tradability: str
    tradability_update_time: int
    overnight_supported: bool
    fractionable: bool
    fractionable_extended_hours: bool
    extended_session: bool
    max_num_orders: int
    step_size: str
    multiplier_up: str
    multiplier_down: str
    minimum_quantity: str
    maximum_quantity: str
    minimum_notional: str
    maximum_notional: str
    listing_time: int
    delisting_time: int | None
    rule_hash: str

    @classmethod
    def from_exchange_info_row(
        cls, value: Mapping[str, Any]
    ) -> BinanceStockSymbolRule:
        if not isinstance(value, Mapping):
            raise BinanceStocksContractError("stock_symbol_rule_not_object")
        required = {
            "symbol",
            "tradability",
            "tradabilityUpdateTime",
            "overnightSupported",
            "fractionable",
            "fractionableEh",
            "extendedSession",
            "maxNumOrders",
            "stepSize",
            "multiplierUp",
            "multiplierDown",
            "minQty",
            "maxQty",
            "minNotional",
            "maxNotional",
            "listingTime",
            "delistingTime",
        }
        if set(value) != required:
            raise BinanceStocksContractError("stock_symbol_rule_fields_invalid")
        core = {
            "symbol": str(value["symbol"]),
            "tradability": str(value["tradability"]),
            "tradability_update_time": _integer(
                value["tradabilityUpdateTime"],
                name="stock_tradability_update_time",
            ),
            "overnight_supported": _boolean(
                value["overnightSupported"], name="stock_overnight_supported"
            ),
            "fractionable": _boolean(
                value["fractionable"], name="stock_fractionable"
            ),
            "fractionable_extended_hours": _boolean(
                value["fractionableEh"],
                name="stock_fractionable_extended_hours",
            ),
            "extended_session": _boolean(
                value["extendedSession"], name="stock_extended_session"
            ),
            "max_num_orders": _integer(
                value["maxNumOrders"], name="stock_max_num_orders", minimum=1
            ),
            "step_size": _decimal_text(
                value["stepSize"], name="stock_step_size", positive=True
            ),
            "multiplier_up": _decimal_text(
                value["multiplierUp"], name="stock_multiplier_up", positive=True
            ),
            "multiplier_down": _decimal_text(
                value["multiplierDown"],
                name="stock_multiplier_down",
                positive=True,
            ),
            "minimum_quantity": _decimal_text(
                value["minQty"], name="stock_minimum_quantity", positive=True
            ),
            "maximum_quantity": _decimal_text(
                value["maxQty"], name="stock_maximum_quantity", positive=True
            ),
            "minimum_notional": _decimal_text(
                value["minNotional"],
                name="stock_minimum_notional",
                positive=True,
            ),
            "maximum_notional": _decimal_text(
                value["maxNotional"],
                name="stock_maximum_notional",
                positive=True,
            ),
            "listing_time": _integer(
                value["listingTime"], name="stock_listing_time"
            ),
            "delisting_time": (
                None
                if value["delistingTime"] is None
                else _integer(
                    value["delistingTime"], name="stock_delisting_time"
                )
            ),
        }
        rule = cls(**core, rule_hash=canonical_hash(core))
        errors = rule.validate()
        if errors:
            raise BinanceStocksContractError(
                "stock_symbol_rule_invalid:" + ",".join(errors)
            )
        return rule

    def _core(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "rule_hash"
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not _TICKER_RE.fullmatch(self.symbol):
            errors.append("symbol_invalid")
        if self.tradability not in _TRADABILITY:
            errors.append("tradability_invalid")
        for name in (
            "tradability_update_time",
            "max_num_orders",
            "listing_time",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"{name}_invalid")
        if self.max_num_orders < 1:
            errors.append("max_num_orders_invalid")
        if self.delisting_time is not None and (
            not isinstance(self.delisting_time, int)
            or isinstance(self.delisting_time, bool)
            or self.delisting_time < self.listing_time
        ):
            errors.append("delisting_time_invalid")
        for name in (
            "overnight_supported",
            "fractionable",
            "fractionable_extended_hours",
            "extended_session",
        ):
            if not isinstance(getattr(self, name), bool):
                errors.append(f"{name}_invalid")
        try:
            step = _decimal(self.step_size, name="step_size", positive=True)
            multiplier_up = _decimal(
                self.multiplier_up, name="multiplier_up", positive=True
            )
            multiplier_down = _decimal(
                self.multiplier_down, name="multiplier_down", positive=True
            )
            minimum_quantity = _decimal(
                self.minimum_quantity, name="minimum_quantity", positive=True
            )
            maximum_quantity = _decimal(
                self.maximum_quantity, name="maximum_quantity", positive=True
            )
            minimum_notional = _decimal(
                self.minimum_notional, name="minimum_notional", positive=True
            )
            maximum_notional = _decimal(
                self.maximum_notional, name="maximum_notional", positive=True
            )
        except BinanceStocksContractError as exc:
            errors.append(str(exc))
        else:
            if step > minimum_quantity:
                errors.append("step_size_above_minimum_quantity")
            if maximum_quantity < minimum_quantity:
                errors.append("quantity_range_invalid")
            if maximum_notional < minimum_notional:
                errors.append("notional_range_invalid")
            if multiplier_down > multiplier_up:
                errors.append("price_multiplier_range_invalid")
        if self.rule_hash != canonical_hash(self._core()):
            errors.append("rule_hash_invalid")
        return tuple(errors)

    def planner_rule(self) -> dict[str, float]:
        errors = self.validate()
        if errors:
            raise BinanceStocksContractError(
                "stock_symbol_rule_invalid:" + ",".join(errors)
            )
        return {
            "step_size": float(self.step_size),
            "minimum_quantity": float(self.minimum_quantity),
            "minimum_notional": float(self.minimum_notional),
        }


def parse_binance_stock_exchange_info(
    value: Mapping[str, Any],
) -> tuple[BinanceStockSymbolRule, ...]:
    if not isinstance(value, Mapping) or set(value) != {"timezone", "symbols"}:
        raise BinanceStocksContractError("stock_exchange_info_fields_invalid")
    if value["timezone"] != "UTC":
        raise BinanceStocksContractError("stock_exchange_info_timezone_invalid")
    rows = value["symbols"]
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise BinanceStocksContractError("stock_exchange_info_symbols_invalid")
    rules = tuple(BinanceStockSymbolRule.from_exchange_info_row(row) for row in rows)
    symbols = [rule.symbol for rule in rules]
    if len(symbols) != len(set(symbols)):
        raise BinanceStocksContractError("stock_exchange_info_symbol_duplicate")
    return rules


def build_binance_stock_instrument(
    rule: BinanceStockSymbolRule,
    *,
    asset_class: str,
    tokenize: bool,
) -> InstrumentId:
    if rule.validate():
        raise BinanceStocksContractError("stock_symbol_rule_invalid")
    if asset_class not in {"equity", "etf"}:
        raise BinanceStocksContractError("stock_asset_class_invalid")
    return InstrumentId.create(
        venue="binance",
        symbol=rule.symbol,
        asset_class=asset_class,
        product_kind="tokenized_equity" if tokenize else "cash_equity",
        underlying=rule.symbol,
        price_currency="USD",
        settlement_asset="USDC",
        multiplier=1.0,
        session_calendar="us_equities_24h"
        if rule.overnight_supported
        else "us_equities",
    )


def build_binance_stock_capability(
    rule: BinanceStockSymbolRule,
    instrument: InstrumentId,
    *,
    observed_at: str,
    source_hash: str,
) -> ProductCapability:
    if rule.validate():
        raise BinanceStocksContractError("stock_symbol_rule_invalid")
    if (
        instrument.validate()
        or instrument.venue != "binance"
        or instrument.symbol != rule.symbol
        or instrument.product_kind not in {"cash_equity", "tokenized_equity"}
    ):
        raise BinanceStocksContractError("stock_instrument_mismatch")
    buy_allowed = rule.tradability in {"BUY_SELL", "BUY"}
    sell_allowed = rule.tradability in {"BUY_SELL", "SELL"}
    sessions = ["RTH"]
    if rule.extended_session:
        sessions.append("EXTENDED")
    if rule.overnight_supported:
        sessions.append("24H")
    return ProductCapability.create(
        instrument_key=instrument.instrument_key,
        observed_at=observed_at,
        source_hash=source_hash,
        long_allowed=buy_allowed,
        short_allowed=False,
        buy_allowed=buy_allowed,
        sell_allowed=sell_allowed,
        sell_close_only=sell_allowed,
        reduce_only_supported=False,
        fractional_supported=(
            rule.fractionable or rule.fractionable_extended_hours
        ),
        funding_applicable=False,
        order_types=("MARKET", "LIMIT"),
        trading_sessions=tuple(sessions),
    )


@dataclass(frozen=True)
class BinanceStockOrderRequest:
    symbol: str
    side: str
    order_type: str
    quote_asset: str = "USDC"
    price: str | None = None
    quantity: str | None = None
    notional: str | None = None
    time_in_force: str = "DAY"
    trading_session: str | None = None
    wallet_type: str | None = None
    client_order_id: str | None = None
    tokenize: bool = True

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quote_asset: str = "USDC",
        price: object | None = None,
        quantity: object | None = None,
        notional: object | None = None,
        time_in_force: str = "DAY",
        trading_session: str | None = None,
        wallet_type: str | None = None,
        client_order_id: str | None = None,
        tokenize: bool = True,
    ) -> BinanceStockOrderRequest:
        request = cls(
            symbol=str(symbol),
            side=str(side),
            order_type=str(order_type),
            quote_asset=str(quote_asset),
            price=(
                None
                if price is None
                else _decimal_text(price, name="stock_order_price", positive=True)
            ),
            quantity=(
                None
                if quantity is None
                else _decimal_text(
                    quantity, name="stock_order_quantity", positive=True
                )
            ),
            notional=(
                None
                if notional is None
                else _decimal_text(
                    notional, name="stock_order_notional", positive=True
                )
            ),
            time_in_force=str(time_in_force),
            trading_session=(
                None if trading_session is None else str(trading_session)
            ),
            wallet_type=None if wallet_type is None else str(wallet_type),
            client_order_id=(
                None if client_order_id is None else str(client_order_id)
            ),
            tokenize=tokenize,
        )
        errors = request.validate()
        if errors:
            raise BinanceStocksContractError(
                "stock_order_request_invalid:" + ",".join(errors)
            )
        return request

    def validate(
        self,
        *,
        rule: BinanceStockSymbolRule | None = None,
        available_to_sell: object | None = None,
        require_sell_inventory: bool = False,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        if not _TICKER_RE.fullmatch(self.symbol):
            errors.append("symbol_invalid")
        if self.side not in _SIDES:
            errors.append("side_invalid")
        if self.order_type not in _ORDER_TYPES:
            errors.append("order_type_invalid")
        if not _QUOTE_ASSET_RE.fullmatch(self.quote_asset):
            errors.append("quote_asset_invalid")
        if self.time_in_force not in _TIME_IN_FORCE:
            errors.append("time_in_force_invalid")
        if self.trading_session is not None and self.trading_session not in _TRADING_SESSIONS:
            errors.append("trading_session_invalid")
        if self.wallet_type is not None and self.wallet_type not in _WALLET_TYPES:
            errors.append("wallet_type_invalid")
        if self.client_order_id is not None and not _CLIENT_ORDER_ID_RE.fullmatch(
            self.client_order_id
        ):
            errors.append("client_order_id_invalid")
        if not isinstance(self.tokenize, bool):
            errors.append("tokenize_invalid")

        if self.order_type == "LIMIT":
            if self.price is None:
                errors.append("limit_price_required")
            if self.quantity is None:
                errors.append("limit_quantity_required")
            if self.trading_session is None:
                errors.append("limit_trading_session_required")
            if self.notional is not None:
                errors.append("limit_notional_forbidden")
        elif self.side == "BUY":
            if self.notional is None:
                errors.append("market_buy_notional_required")
            if self.price is not None:
                errors.append("market_buy_price_forbidden")
            if self.quantity is not None:
                errors.append("market_buy_quantity_forbidden")
            if self.trading_session is not None:
                errors.append("market_buy_trading_session_forbidden")
        elif self.side == "SELL":
            if self.quantity is None:
                errors.append("market_sell_quantity_required")
            if self.price is not None:
                errors.append("market_sell_price_forbidden")
            if self.notional is not None:
                errors.append("market_sell_notional_forbidden")
            if self.trading_session is not None:
                errors.append("market_sell_trading_session_forbidden")

        if self.time_in_force == "GTC" and self.order_type != "LIMIT":
            errors.append("gtc_requires_limit")
        price: Decimal | None = None
        quantity: Decimal | None = None
        notional: Decimal | None = None
        for name in ("price", "quantity", "notional"):
            raw = getattr(self, name)
            if raw is None:
                continue
            try:
                value = _decimal(raw, name=f"stock_order_{name}", positive=True)
            except BinanceStocksContractError as exc:
                errors.append(str(exc))
                continue
            if name == "price":
                price = value
            elif name == "quantity":
                quantity = value
            else:
                notional = value
        if price is not None and max(0, -price.as_tuple().exponent) > 2:
            errors.append("price_precision_exceeds_two")

        fractional = notional is not None or (
            quantity is not None and quantity != quantity.to_integral_value()
        )
        if (
            fractional
            and self.time_in_force == "GTC"
            and self.trading_session not in {"EXTENDED", "24H"}
        ):
            errors.append("fractional_gtc_session_invalid")

        if rule is not None:
            if rule.validate() or rule.symbol != self.symbol:
                errors.append("symbol_rule_invalid")
            else:
                side_allowed = (
                    self.side == "BUY"
                    and rule.tradability in {"BUY_SELL", "BUY"}
                ) or (
                    self.side == "SELL"
                    and rule.tradability in {"BUY_SELL", "SELL"}
                )
                if not side_allowed:
                    errors.append("side_not_tradable")
                if self.trading_session == "EXTENDED" and not rule.extended_session:
                    errors.append("extended_session_not_supported")
                if self.trading_session == "24H" and not rule.overnight_supported:
                    errors.append("overnight_session_not_supported")
                if fractional:
                    fractional_supported = (
                        rule.fractionable
                        if self.trading_session in {None, "RTH"}
                        else rule.fractionable_extended_hours
                    )
                    if not fractional_supported:
                        errors.append("fractional_order_not_supported")
                if quantity is not None:
                    step = Decimal(rule.step_size)
                    if quantity % step != 0:
                        errors.append("quantity_step_mismatch")
                    if quantity < Decimal(rule.minimum_quantity):
                        errors.append("quantity_below_minimum")
                    if quantity > Decimal(rule.maximum_quantity):
                        errors.append("quantity_above_maximum")
                order_notional = notional
                if order_notional is None and price is not None and quantity is not None:
                    order_notional = price * quantity
                if order_notional is not None:
                    if order_notional < Decimal(rule.minimum_notional):
                        errors.append("notional_below_minimum")
                    if order_notional > Decimal(rule.maximum_notional):
                        errors.append("notional_above_maximum")

        if self.side == "SELL":
            if available_to_sell is None:
                if require_sell_inventory:
                    errors.append("sell_inventory_unavailable")
            else:
                try:
                    available = _decimal(
                        available_to_sell,
                        name="stock_available_to_sell",
                    )
                except BinanceStocksContractError as exc:
                    errors.append(str(exc))
                else:
                    if available < 0:
                        errors.append("stock_available_to_sell_invalid")
                    elif quantity is not None and quantity > available:
                        errors.append("sell_quantity_exceeds_inventory")
        return tuple(dict.fromkeys(errors))

    def as_sapi_params(self) -> dict[str, object]:
        errors = self.validate()
        if errors:
            raise BinanceStocksContractError(
                "stock_order_request_invalid:" + ",".join(errors)
            )
        values = {
            "symbol": self.symbol,
            "quoteAsset": self.quote_asset,
            "side": self.side,
            "orderType": self.order_type,
            "price": self.price,
            "quantity": self.quantity,
            "notional": self.notional,
            "timeInForce": self.time_in_force,
            "tradingSession": self.trading_session,
            "walletType": self.wallet_type,
            "clientOrderId": self.client_order_id,
            "tokenize": self.tokenize,
        }
        return {key: value for key, value in values.items() if value is not None}


def validate_binance_stock_order_for_execution(
    request: BinanceStockOrderRequest,
    *,
    rule: BinanceStockSymbolRule,
    instrument: InstrumentId,
    disclaimer_accepted: bool,
    available_to_sell: object | None,
) -> tuple[str, ...]:
    if not isinstance(request, BinanceStockOrderRequest):
        return ("stock_order_request_type_invalid",)
    errors = list(
        request.validate(
        rule=rule,
        available_to_sell=available_to_sell,
        require_sell_inventory=True,
        )
    )
    expected_product_kind = "tokenized_equity" if request.tokenize else "cash_equity"
    if (
        not isinstance(instrument, InstrumentId)
        or instrument.validate()
        or instrument.venue != "binance"
        or instrument.symbol != request.symbol
        or instrument.product_kind != expected_product_kind
    ):
        errors.append("stock_order_instrument_mismatch")
    if disclaimer_accepted is not True:
        errors.append("stock_disclaimer_not_accepted")
    return tuple(dict.fromkeys(errors))
