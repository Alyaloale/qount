"""Small, deterministic 1ATR signal core for Binance USD-M.

This module only computes a current signal and an order plan. It does not call a
venue, read credentials, or submit orders. The live runner owns the execution
authorization and persists the resulting plan separately from research NAVs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence
from decimal import Decimal, ROUND_DOWN


def allocation_quantity(available: float, price: float, *, fraction: float,
                        step: float, minimum: float, maximum: float, min_notional: float) -> float:
    """Current live nominal allocation, also used by its offline replay."""
    if not 0 < fraction <= 1:
        raise ValueError("auto_alloc_fraction_invalid")
    for value, name in ((available,"available"),(price,"price"),(step,"step"),(maximum,"maximum")):
        _finite(value, name)
    raw = Decimal(str(available*fraction/price))
    quantum = Decimal(str(step))
    quantity = float((raw/quantum).to_integral_value(rounding=ROUND_DOWN)*quantum)
    if quantity < minimum or quantity > maximum or quantity*price < min_notional:
        raise ValueError("auto_quantity_below_exchange_minimum")
    return quantity


@dataclass(frozen=True)
class DailyBar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class AtrSignal:
    symbol: str
    as_of: str
    side: str
    close: float
    atr: float
    stop_price: float
    sma120: float
    momentum20: float
    eligible: bool
    reason: str


def _finite(value: float, name: str) -> float:
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")) or value <= 0:
        raise ValueError(f"{name}_invalid")
    return value


def true_range(previous: DailyBar, current: DailyBar) -> float:
    return max(current.high - current.low,
               abs(current.high - previous.close),
               abs(current.low - previous.close))


def wilder_atr(bars: Sequence[DailyBar], period: int = 14) -> float:
    if period < 2 or len(bars) < period + 1:
        raise ValueError("atr_history_insufficient")
    values = [true_range(bars[i - 1], bars[i]) for i in range(1, len(bars))]
    atr = sum(values[:period]) / period
    for value in values[period:]:
        atr = ((period - 1) * atr + value) / period
    return _finite(atr, "atr")


def build_signal(symbol: str, bars: Sequence[DailyBar], *, now: datetime | None = None) -> AtrSignal:
    if len(bars) < 121:
        raise ValueError("signal_history_insufficient")
    if any(bars[i].timestamp >= bars[i + 1].timestamp for i in range(len(bars) - 1)):
        raise ValueError("bars_not_strictly_ordered")
    latest = bars[-1]
    close = _finite(latest.close, "close")
    atr = wilder_atr(bars, 14)
    sma120 = sum(_finite(row.close, "close") for row in bars[-120:]) / 120
    prior = _finite(bars[-2].close, "prior_close")
    momentum20 = close / _finite(bars[-21].close, "momentum_reference") - 1.0
    # 1ATR gate: a long trend entry is allowed only when the current daily
    # move is no more than one ATR and the close remains above the 120-day mean.
    move = close - prior
    eligible = close > sma120 and momentum20 > 0 and move <= atr
    reason = "eligible_1atr_long" if eligible else "trend_or_1atr_gate_failed"
    stamp = now or datetime.fromtimestamp(latest.timestamp, timezone.utc)
    return AtrSignal(
        symbol=symbol,
        as_of=stamp.astimezone(timezone.utc).isoformat(),
        side="buy" if eligible else "flat",
        close=close,
        atr=atr,
        stop_price=max(0.0, close - 2.0 * atr),
        sma120=sma120,
        momentum20=momentum20,
        eligible=eligible,
        reason=reason,
    )


def select_signal(signals: Iterable[AtrSignal]) -> AtrSignal | None:
    eligible = [signal for signal in signals if signal.eligible]
    return max(eligible, key=lambda signal: (signal.momentum20, signal.symbol), default=None)
