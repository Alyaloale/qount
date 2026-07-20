from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from decimal import ROUND_DOWN
from pathlib import Path
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings


BINANCE_EXCHANGE_RULES_VERSION = "alpha_agent_binance_exchange_rules_v0.1"

UM_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
SPOT_EXCHANGE_INFO_URL = "https://data-api.binance.vision/api/v3/exchangeInfo"


def _as_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _market_url(market: str) -> str:
    if market == "um":
        return UM_EXCHANGE_INFO_URL
    if market == "spot":
        return SPOT_EXCHANGE_INFO_URL
    raise ValueError(f"unknown market {market!r} (expected 'um' or 'spot')")


def _default_fetch(url: str) -> bytes:  # pragma: no cover - network
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read()


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    status: str
    base_asset: str
    quote_asset: str
    tick_size: Decimal
    min_price: Decimal
    max_price: Decimal
    step_size: Decimal
    market_step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal
    source_market: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "tick_size": _decimal_text(self.tick_size),
            "min_price": _decimal_text(self.min_price),
            "max_price": _decimal_text(self.max_price),
            "step_size": _decimal_text(self.step_size),
            "market_step_size": _decimal_text(self.market_step_size),
            "min_qty": _decimal_text(self.min_qty),
            "max_qty": _decimal_text(self.max_qty),
            "min_notional": _decimal_text(self.min_notional),
            "source_market": self.source_market,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SymbolRules":
        return cls(
            symbol=str(payload.get("symbol", "")).upper(),
            status=str(payload.get("status", "")),
            base_asset=str(payload.get("base_asset", "")),
            quote_asset=str(payload.get("quote_asset", "")),
            tick_size=_as_decimal(payload.get("tick_size")),
            min_price=_as_decimal(payload.get("min_price")),
            max_price=_as_decimal(payload.get("max_price")),
            step_size=_as_decimal(payload.get("step_size")),
            market_step_size=_as_decimal(payload.get("market_step_size")),
            min_qty=_as_decimal(payload.get("min_qty")),
            max_qty=_as_decimal(payload.get("max_qty")),
            min_notional=_as_decimal(payload.get("min_notional")),
            source_market=str(payload.get("source_market", "unknown")),
        )


@dataclass(frozen=True)
class OrderFilterCheck:
    symbol: str
    ok: bool
    reasons: tuple[str, ...]
    price: str
    requested_notional: str
    rounded_quantity: str
    rounded_notional: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ok": self.ok,
            "reasons": list(self.reasons),
            "price": self.price,
            "requested_notional": self.requested_notional,
            "rounded_quantity": self.rounded_quantity,
            "rounded_notional": self.rounded_notional,
        }


def fetch_exchange_info(
    *,
    market: str = "um",
    fetch: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    url = _market_url(market)
    blob = (fetch or _default_fetch)(url)
    payload = json.loads(blob.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise ValueError("exchangeInfo payload must be an object with symbols list")
    return payload


def _filter_map(symbol_info: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in symbol_info.get("filters", []):
        if isinstance(item, dict) and item.get("filterType"):
            result[str(item["filterType"])] = item
    return result


def parse_symbol_rules(symbol_info: dict[str, Any], *, market: str) -> SymbolRules:
    filters = _filter_map(symbol_info)
    price = filters.get("PRICE_FILTER", {})
    lot = filters.get("LOT_SIZE", {})
    market_lot = filters.get("MARKET_LOT_SIZE", {})
    min_notional = filters.get("MIN_NOTIONAL", {})
    notional = filters.get("NOTIONAL", {})
    return SymbolRules(
        symbol=str(symbol_info.get("symbol", "")).upper(),
        status=str(symbol_info.get("status", "")),
        base_asset=str(symbol_info.get("baseAsset", symbol_info.get("base_asset", ""))),
        quote_asset=str(symbol_info.get("quoteAsset", symbol_info.get("quote_asset", ""))),
        tick_size=_as_decimal(price.get("tickSize")),
        min_price=_as_decimal(price.get("minPrice")),
        max_price=_as_decimal(price.get("maxPrice")),
        step_size=_as_decimal(lot.get("stepSize")),
        market_step_size=_as_decimal(market_lot.get("stepSize")),
        min_qty=_as_decimal(lot.get("minQty")),
        max_qty=_as_decimal(lot.get("maxQty")),
        min_notional=_as_decimal(
            min_notional.get("notional", min_notional.get("minNotional", notional.get("minNotional")))
        ),
        source_market=market,
    )


def rules_from_exchange_info(exchange_info: dict[str, Any], *, market: str = "um") -> dict[str, SymbolRules]:
    symbols = exchange_info.get("symbols")
    if not isinstance(symbols, list):
        raise ValueError("exchangeInfo payload must contain symbols list")
    result: dict[str, SymbolRules] = {}
    for item in symbols:
        if isinstance(item, dict):
            rules = parse_symbol_rules(item, market=market)
            if rules.symbol:
                result[rules.symbol] = rules
    return result


def load_symbol_rules(path: str | Path, *, market: str = "um") -> dict[str, SymbolRules]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, dict) and payload.get("schema_version") == BINANCE_EXCHANGE_RULES_VERSION:
        rules = payload.get("rules", [])
        if not isinstance(rules, list):
            raise ValueError("rules artifact must contain rules list")
        return {SymbolRules.from_dict(item).symbol: SymbolRules.from_dict(item) for item in rules if isinstance(item, dict)}
    if isinstance(payload, dict) and isinstance(payload.get("symbols"), list):
        return rules_from_exchange_info(payload, market=market)
    raise ValueError("exchange rules path must contain raw exchangeInfo or alpha exchange-rules artifact")


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def validate_market_notional(
    rules_by_symbol: dict[str, SymbolRules],
    *,
    symbol: str,
    price: float | Decimal,
    target_notional: float | Decimal,
) -> OrderFilterCheck:
    normalized = symbol.upper()
    reasons: list[str] = []
    rules = rules_by_symbol.get(normalized)
    price_dec = _as_decimal(price)
    requested = _as_decimal(target_notional)
    if rules is None:
        return OrderFilterCheck(
            symbol=normalized,
            ok=False,
            reasons=("unknown_symbol_rules",),
            price=_decimal_text(price_dec),
            requested_notional=_decimal_text(requested),
            rounded_quantity="0",
            rounded_notional="0",
        )
    if rules.status != "TRADING":
        reasons.append(f"symbol_status:{rules.status or 'unknown'}")
    if price_dec <= 0:
        reasons.append("price_not_positive")
    if requested <= 0:
        reasons.append("target_notional_not_positive")
    raw_qty = requested / price_dec if price_dec > 0 else Decimal("0")
    step = rules.market_step_size if rules.market_step_size > 0 else rules.step_size
    qty = _floor_to_step(raw_qty, step)
    rounded_notional = qty * price_dec
    if qty <= 0:
        reasons.append("quantity_rounds_to_zero")
    if rules.min_qty > 0 and qty < rules.min_qty:
        reasons.append("quantity_below_min_qty")
    if rules.max_qty > 0 and qty > rules.max_qty:
        reasons.append("quantity_above_max_qty")
    if rules.min_notional > 0 and rounded_notional < rules.min_notional:
        reasons.append("notional_below_min_notional")
    return OrderFilterCheck(
        symbol=normalized,
        ok=not reasons,
        reasons=tuple(reasons),
        price=_decimal_text(price_dec),
        requested_notional=_decimal_text(requested),
        rounded_quantity=_decimal_text(qty),
        rounded_notional=_decimal_text(rounded_notional),
    )


def evaluate_period_filter_coverage(
    periods: list[dict[str, Any]],
    rules_by_symbol: dict[str, SymbolRules],
    *,
    symbol: str,
    account_equity_usdt: float,
    target_notional_fraction: float,
    leverage: float,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    prev_position = 0.0
    for row in periods:
        try:
            position = float(row.get("strategy_position", 0.0))
            price = float(row.get("strategy_close", 0.0))
        except (TypeError, ValueError):
            position = 0.0
            price = 0.0
        legs: list[tuple[str, float]] = []
        if prev_position * position < 0:
            legs.append(("close", abs(prev_position)))
            legs.append(("open", abs(position)))
        elif prev_position == 0.0 and position != 0.0:
            legs.append(("open", abs(position)))
        elif prev_position != 0.0 and position == 0.0:
            legs.append(("close", abs(prev_position)))
        elif position != prev_position:
            legs.append(("rebalance", abs(position - prev_position)))

        for action, size_fraction in legs:
            notional = account_equity_usdt * target_notional_fraction * leverage * size_fraction
            check = validate_market_notional(
                rules_by_symbol,
                symbol=symbol,
                price=price,
                target_notional=notional,
            ).to_dict()
            check["ts"] = row.get("ts")
            check["action"] = action
            checks.append(check)
        prev_position = position

    order_count = len(checks)
    passed = sum(1 for item in checks if item["ok"])
    failed = order_count - passed
    coverage = passed / order_count if order_count else 1.0
    failure_reasons: dict[str, int] = {}
    for item in checks:
        for reason in item["reasons"]:
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
    return {
        "order_count": order_count,
        "passed_order_count": passed,
        "failed_order_count": failed,
        "filter_coverage": coverage,
        "min_notional_coverage": coverage,
        "failure_reasons": failure_reasons,
        "first_failures": [item for item in checks if not item["ok"]][:10],
        "account_equity_usdt": account_equity_usdt,
        "target_notional_fraction": target_notional_fraction,
        "leverage": leverage,
    }


def build_exchange_rules_report(
    exchange_info: dict[str, Any],
    *,
    market: str = "um",
    symbols: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    rules = rules_from_exchange_info(exchange_info, market=market)
    selected = {item.upper() for item in symbols} if symbols else set(rules)
    rows = [rules[symbol] for symbol in sorted(selected) if symbol in rules]
    raw_hash = hashlib.sha256(json.dumps(exchange_info, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema_version": BINANCE_EXCHANGE_RULES_VERSION,
        "created_at": utc_now().isoformat(),
        "market": market,
        "source_url": _market_url(market),
        "source_type": "runtime_exchange_info",
        "raw_exchange_info_hash": raw_hash,
        "requested_symbol_count": len(selected),
        "returned_symbol_count": len(rows),
        "trading_symbol_count": sum(1 for item in rows if item.status == "TRADING"),
        "rules": [item.to_dict() for item in rows],
        "policy": [
            "This artifact is public exchange metadata only; it contains no private Binance credentials.",
            "Filter coverage can satisfy the Alpha Agents data gate only when generated from runtime exchangeInfo.",
            "Order sizing still belongs to deterministic risk code, not LLM output.",
        ],
    }


def write_exchange_rules_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-exchange-rules",
        path_key="artifact_path",
        default_filename="alpha_agent_exchange_rules.json",
        explicit_path=explicit_path,
    )
