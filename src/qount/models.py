from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


@dataclass
class Candle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class PositionSnapshot:
    symbol: str
    quantity: float
    mark_price: float
    market_value_quote: float
    side: str | None = None
    average_entry_price: float | None = None
    notional_quote: float | None = None
    unrealized_pnl_quote: float | None = None
    leverage: float | None = None
    margin_mode: str | None = None
    liquidation_price: float | None = None


@dataclass
class SymbolSnapshot:
    symbol: str
    timeframe: str
    last_price: float
    indicators: dict[str, float]
    recent_candles: list[Candle]
    exchange_min_cost_quote: float | None = None
    exchange_min_amount: float | None = None
    exchange_amount_step: float | None = None
    higher_timeframe: dict[str, Any] | None = None
    candidate_context: dict[str, Any] | None = None


@dataclass
class AccountSnapshot:
    quote_currency: str
    equity_quote: float
    free_quote: float
    open_positions: list[PositionSnapshot]
    mode: str
    market_type: str


@dataclass
class MarketSnapshotBundle:
    generated_at: datetime
    timeframe: str
    symbols: list[SymbolSnapshot]
    account: AccountSnapshot

    def latest_closed_bar_fingerprint(self) -> str:
        parts: list[str] = []
        for symbol in self.symbols:
            if not symbol.recent_candles:
                continue
            parts.append(f"{symbol.symbol}:{symbol.recent_candles[-1].timestamp_ms}")
        return f"{self.timeframe}|{'|'.join(parts)}"

    def summary_for_prompt(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "timeframe": self.timeframe,
            "account": to_jsonable(self.account),
            "symbols": [
                {
                    "symbol": symbol.symbol,
                    "last_price": symbol.last_price,
                    "exchange_min_cost_quote": symbol.exchange_min_cost_quote,
                    "exchange_min_amount": symbol.exchange_min_amount,
                    "exchange_amount_step": symbol.exchange_amount_step,
                    "indicators": symbol.indicators,
                    "higher_timeframe": symbol.higher_timeframe,
                    "candidate_context": symbol.candidate_context,
                    "recent_candles": [
                        {
                            "timestamp_ms": candle.timestamp_ms,
                            "open": candle.open,
                            "high": candle.high,
                            "low": candle.low,
                            "close": candle.close,
                            "volume": candle.volume,
                        }
                        for candle in symbol.recent_candles[-8:]
                    ],
                }
                for symbol in self.symbols
            ],
        }


@dataclass
class AIDecision:
    timestamp: str
    symbol: str
    action: str
    size_pct: float
    take_profit_pct: float
    stop_loss_pct: float
    ttl_minutes: int
    confidence: float
    reason: str
    prompt_version: str


@dataclass
class ValidatedDecision:
    decision: AIDecision
    valid: bool
    errors: list[str]
    raw_payload: dict[str, Any] | None = None


@dataclass
class RiskVerdict:
    status: str
    final_action: str
    symbol: str
    final_size_pct: float
    take_profit_pct: float
    stop_loss_pct: float
    ttl_minutes: int
    reasons: list[str]
    confidence: float
    approved: bool
    close_fraction: float = 1.0
    management_open_run_id: int | None = None
    remaining_take_profit_price: float | None = None
    remaining_stop_price: float | None = None
    protective_refresh_only: bool = False
    protective_refresh_reason: str | None = None


@dataclass
class ExecutionResult:
    status: str
    mode: str
    symbol: str
    action: str
    side: str | None
    quantity: float | None
    notional_quote: float | None
    pnl_quote: float | None
    external_order_id: str | None
    raw: dict[str, Any]
