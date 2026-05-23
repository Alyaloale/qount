from __future__ import annotations

from decimal import Decimal
from decimal import ROUND_CEILING
import time
from typing import Any

import ccxt

from .models import PositionSnapshot
from .settings import Settings


def sync_exchange_clock(exchange: Any) -> None:
    sync_clock = getattr(exchange, "load_time_difference", None)
    if callable(sync_clock):
        sync_clock()


def is_timestamp_ahead_error(exc: Exception) -> bool:
    message = str(exc)
    return "-1021" in message or "Timestamp for this request was" in message


def is_transient_network_error(exc: Exception) -> bool:
    network_error_type = getattr(ccxt, "NetworkError", None)
    if network_error_type is not None and isinstance(exc, network_error_type):
        return True
    message = str(exc)
    return any(
        token in message
        for token in (
            "SSLError",
            "SSL:",
            "UNEXPECTED_EOF_WHILE_READING",
            "EOF occurred in violation of protocol",
            "Max retries exceeded",
            "ProxyError",
            "Connection reset by peer",
            "timed out",
            "Temporary failure in name resolution",
            "RemoteDisconnected",
            "NetworkError",
        )
    )


def call_with_time_sync_retry(
    exchange: Any,
    operation,
    *args: Any,
    sync_before: bool = False,
    retry_attempts: int = 4,
    retry_delay_seconds: float = 1.0,
    **kwargs: Any,
):
    if sync_before:
        sync_exchange_clock(exchange)
    attempts_remaining = max(int(retry_attempts), 1)
    attempt = 0
    while True:
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            attempt += 1
            timestamp_retry = is_timestamp_ahead_error(exc)
            network_retry = is_transient_network_error(exc)
            if not timestamp_retry and not network_retry:
                raise
            if attempt >= attempts_remaining:
                raise
            if timestamp_retry:
                sync_exchange_clock(exchange)
            delay_seconds = max(float(retry_delay_seconds), 0.0) * (2 ** (attempt - 1))
            if delay_seconds > 0.0:
                time.sleep(delay_seconds)


def build_exchange(settings: Settings, private: bool = False):
    exchange_class = getattr(ccxt, settings.exchange_id)
    exchange_options: dict[str, Any] = {
        "defaultType": settings.ccxt_default_type,
        "adjustForTimeDifference": True,
        "fetchMarkets": {
            "types": ["linear"] if settings.contract_market else ["spot"],
        },
    }
    if settings.contract_market:
        exchange_options["defaultSubType"] = "linear"
        exchange_options["fetchBalance"] = {
            "defaultType": settings.ccxt_default_type,
            "subType": "linear",
        }
        exchange_options["fetchPositions"] = {
            "subType": "linear",
        }
        exchange_options["fetchPositionMode"] = {
            "subType": "linear",
        }
        exchange_options["fetchTime"] = {
            "defaultType": settings.ccxt_default_type,
            "subType": "linear",
        }
    else:
        exchange_options["fetchTime"] = {
            "defaultType": settings.ccxt_default_type,
        }
    options: dict[str, Any] = {
        "enableRateLimit": True,
        "options": exchange_options,
    }
    if settings.https_proxy:
        options["httpsProxy"] = settings.https_proxy
    elif settings.http_proxy:
        options["httpProxy"] = settings.http_proxy
    if private:
        options["apiKey"] = settings.binance_api_key
        options["secret"] = settings.binance_api_secret
    return exchange_class(options)


class ExchangePool:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, Any] = {}

    def get(self, *, private: bool) -> Any:
        key = "private" if private else "public"
        exchange = self._cache.get(key)
        if exchange is None:
            exchange = build_exchange(self.settings, private=private)
            self._cache[key] = exchange
        return exchange

    def public(self) -> Any:
        return self.get(private=False)

    def private(self) -> Any:
        return self.get(private=True)


def market_matches_settings(market: dict[str, Any], settings: Settings) -> bool:
    if settings.contract_market:
        return bool(market.get("contract")) and bool(market.get("linear")) and market.get("settle") == settings.quote_currency
    return bool(market.get("spot"))


def resolve_market_symbol(markets: dict[str, dict[str, Any]], configured_symbol: str, settings: Settings) -> str:
    direct = markets.get(configured_symbol)
    if direct and market_matches_settings(direct, settings):
        return str(direct["symbol"])

    if "/" not in configured_symbol:
        raise KeyError(f"unsupported_symbol_format:{configured_symbol}")

    base, quote_part = configured_symbol.split("/", 1)
    quote = quote_part.split(":", 1)[0]
    candidates = [
        market
        for market in markets.values()
        if market.get("base") == base and market.get("quote") == quote and market_matches_settings(market, settings)
    ]
    if settings.contract_market:
        candidates = [market for market in candidates if market.get("swap")] or candidates
        settle_symbol = f"{base}/{quote}:{settings.quote_currency}"
        candidates = [market for market in candidates if market.get("symbol") == settle_symbol] or candidates

    if len(candidates) == 1:
        return str(candidates[0]["symbol"])
    if not candidates:
        raise KeyError(f"missing_market_symbol:{configured_symbol}:{settings.market_type}")

    names = ",".join(sorted(str(item["symbol"]) for item in candidates[:6]))
    raise KeyError(f"ambiguous_market_symbol:{configured_symbol}:{names}")


def resolve_market_symbols(markets: dict[str, dict[str, Any]], configured_symbols: tuple[str, ...], settings: Settings) -> tuple[str, ...]:
    return tuple(resolve_market_symbol(markets, symbol, settings) for symbol in configured_symbols)


def round_up_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    value_dec = Decimal(str(value))
    step_dec = Decimal(str(step))
    units = (value_dec / step_dec).to_integral_value(rounding=ROUND_CEILING)
    return float(units * step_dec)


def market_amount_step(market: dict[str, Any]) -> float | None:
    info = market.get("info") or {}
    for filter_entry in info.get("filters") or []:
        if filter_entry.get("filterType") not in {"LOT_SIZE", "MARKET_LOT_SIZE"}:
            continue
        try:
            step = float(filter_entry.get("stepSize") or 0.0)
        except (TypeError, ValueError):
            continue
        if step > 0:
            return step

    raw_precision = (market.get("precision") or {}).get("amount")
    try:
        precision_value = float(raw_precision)
    except (TypeError, ValueError):
        return None
    if precision_value <= 0:
        return None
    if precision_value < 1:
        return precision_value
    if precision_value.is_integer():
        return 10 ** (-int(precision_value))
    return precision_value


def minimum_executable_quantity(
    *,
    price: float,
    min_cost: float,
    min_amount: float,
    amount_step: float | None,
) -> float:
    if price <= 0:
        return max(min_amount, 0.0)
    min_quantity = max(min_amount, min_cost / price)
    if amount_step:
        return round_up_to_step(min_quantity, amount_step)
    return min_quantity


def minimum_executable_notional(
    *,
    price: float,
    min_cost: float,
    min_amount: float,
    amount_step: float | None,
) -> float:
    return minimum_executable_quantity(
        price=price,
        min_cost=min_cost,
        min_amount=min_amount,
        amount_step=amount_step,
    ) * price


def extract_quote_balance(balance: dict[str, Any], settings: Settings) -> dict[str, float]:
    free = float((balance.get("free") or {}).get(settings.quote_currency) or 0.0)
    total = float((balance.get("total") or {}).get(settings.quote_currency) or 0.0)
    used = float((balance.get("used") or {}).get(settings.quote_currency) or 0.0)
    if not settings.contract_market:
        return {
            "quote_total": total,
            "quote_free": free,
            "quote_used": used,
            "wallet_balance": total,
            "margin_balance": total,
        }

    assets = (balance.get("info") or {}).get("assets") or []
    asset = next((item for item in assets if item.get("asset") == settings.quote_currency), None)
    if asset is None:
        return {
            "quote_total": total,
            "quote_free": free,
            "quote_used": used,
            "wallet_balance": total,
            "margin_balance": total,
        }

    margin_balance = float(asset.get("marginBalance") or total or 0.0)
    available_balance = float(asset.get("availableBalance") or free or 0.0)
    wallet_balance = float(asset.get("walletBalance") or total or 0.0)
    used_balance = max(margin_balance - available_balance, 0.0)
    return {
        "quote_total": margin_balance,
        "quote_free": available_balance,
        "quote_used": used_balance,
        "wallet_balance": wallet_balance,
        "margin_balance": margin_balance,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None


def _position_value(position: dict[str, Any], *keys: str) -> Any:
    info = position.get("info") or {}
    for key in keys:
        if position.get(key) is not None:
            return position.get(key)
        if isinstance(info, dict) and info.get(key) is not None:
            return info.get(key)
    return None


def _position_market_symbol(
    position: dict[str, Any],
    *,
    markets: dict[str, dict[str, Any]],
    market_by_id: dict[str, dict[str, Any]],
) -> str:
    raw_symbol = str(_position_value(position, "symbol") or "")
    if raw_symbol in markets:
        return raw_symbol
    market = market_by_id.get(raw_symbol)
    if market is not None:
        return str(market.get("symbol"))
    return raw_symbol


def normalize_futures_position_snapshots(
    raw_positions: list[dict[str, Any]],
    *,
    markets: dict[str, dict[str, Any]],
    resolved_symbols: tuple[str, ...],
    latest_prices: dict[str, float] | None = None,
    min_notional_quote: float = 0.0,
) -> list[PositionSnapshot]:
    latest_prices = latest_prices or {}
    resolved_symbol_set = set(resolved_symbols)
    market_by_id = {str(market.get("id")): market for market in markets.values() if market.get("id") is not None}
    snapshots: list[PositionSnapshot] = []

    for position in raw_positions:
        if not isinstance(position, dict):
            continue
        symbol = _position_market_symbol(position, markets=markets, market_by_id=market_by_id)
        if symbol not in resolved_symbol_set:
            continue

        signed_quantity = _float_or_none(
            _position_value(position, "positionAmt", "positionAmount", "contracts")
        )
        raw_side = str(_position_value(position, "side") or "").strip().lower()
        if signed_quantity is None:
            signed_quantity = _float_or_none(_position_value(position, "contractSize"))
        if signed_quantity is None:
            signed_quantity = 0.0
        if raw_side == "short" and signed_quantity > 0:
            signed_quantity = -signed_quantity

        quantity = abs(signed_quantity)
        if quantity == 0.0:
            quantity = abs(_float_or_none(_position_value(position, "contracts")) or 0.0)
        if quantity == 0.0:
            continue

        if raw_side in {"long", "short"}:
            side = raw_side
        else:
            side = "long" if signed_quantity > 0 else "short"

        average_entry_price = _float_or_none(_position_value(position, "entryPrice", "average", "avgPrice"))
        mark_price = (
            _float_or_none(_position_value(position, "markPrice", "lastPrice"))
            or latest_prices.get(symbol)
            or average_entry_price
            or 0.0
        )
        notional_quote = abs(
            _float_or_none(_position_value(position, "notional", "notionalValue"))
            or (quantity * mark_price)
        )
        if notional_quote < min_notional_quote:
            continue

        unrealized_pnl_quote = _float_or_none(
            _position_value(position, "unrealizedPnl", "unrealizedProfit", "unRealizedProfit")
        )
        leverage = _float_or_none(_position_value(position, "leverage"))
        margin_mode = _position_value(position, "marginMode", "marginType")
        if margin_mode is None:
            isolated = _bool_or_none(_position_value(position, "isolated"))
            if isolated is not None:
                margin_mode = "isolated" if isolated else "cross"
        liquidation_price = _float_or_none(_position_value(position, "liquidationPrice"))

        snapshots.append(
            PositionSnapshot(
                symbol=symbol,
                quantity=quantity,
                mark_price=mark_price,
                market_value_quote=notional_quote,
                side=side,
                average_entry_price=average_entry_price,
                notional_quote=notional_quote,
                unrealized_pnl_quote=unrealized_pnl_quote,
                leverage=leverage,
                margin_mode=str(margin_mode) if margin_mode is not None else None,
                liquidation_price=liquidation_price,
            )
        )

    return snapshots


def fetch_futures_position_snapshots(
    exchange: Any,
    *,
    balance: dict[str, Any],
    markets: dict[str, dict[str, Any]],
    resolved_symbols: tuple[str, ...],
    latest_prices: dict[str, float] | None = None,
    min_notional_quote: float = 0.0,
) -> list[PositionSnapshot]:
    raw_positions: list[dict[str, Any]] | None = None
    fetch_positions = getattr(exchange, "fetch_positions", None)
    if callable(fetch_positions):
        try:
            fetched = call_with_time_sync_retry(exchange, fetch_positions, list(resolved_symbols))
            if isinstance(fetched, list):
                raw_positions = fetched
        except Exception:
            raw_positions = None

    if raw_positions is None:
        raw_positions = ((balance.get("info") or {}).get("positions") or [])

    return normalize_futures_position_snapshots(
        raw_positions,
        markets=markets,
        resolved_symbols=resolved_symbols,
        latest_prices=latest_prices,
        min_notional_quote=min_notional_quote,
    )
