from __future__ import annotations

from dataclasses import dataclass

from .models import SymbolSnapshot

LATE_ENTRY_MIN_DIRECTIONAL_24BAR_PCT = 0.0025
LATE_ENTRY_MIN_DIRECTIONAL_1BAR_PCT = 0.0008
LATE_ENTRY_MAX_CONFIRMING_VOLUME_RATIO = 1.10
LATE_ENTRY_MIN_BODY_TO_RANGE_RATIO = 0.55
LATE_ENTRY_MAX_CLOSE_FROM_EXTREME_RATIO = 0.20
LATE_ENTRY_SHORT_MAX_RSI = 38.0
LATE_ENTRY_LONG_MIN_RSI = 58.0

CLIMACTIC_EXTENSION_MIN_DIRECTIONAL_24BAR_PCT = 0.0045
CLIMACTIC_EXTENSION_MIN_DIRECTIONAL_1BAR_PCT = 0.0020
CLIMACTIC_EXTENSION_MIN_VOLUME_RATIO = 1.75
CLIMACTIC_EXTENSION_MIN_BODY_TO_RANGE_RATIO = 0.70
CLIMACTIC_EXTENSION_MAX_CLOSE_FROM_EXTREME_RATIO = 0.15
OVEREXTENDED_LONG_CHASE_MIN_DIRECTIONAL_24BAR_PCT = 0.0060
OVEREXTENDED_LONG_CHASE_MIN_DIRECTIONAL_1BAR_PCT = 0.0015
OVEREXTENDED_LONG_CHASE_MIN_VOLUME_RATIO = 1.50
OVEREXTENDED_LONG_CHASE_MIN_RSI = 68.0
OVEREXTENDED_LONG_CHASE_MIN_BODY_TO_RANGE_RATIO = 0.50
HIGH_RSI_LONG_CHASE_MIN_DIRECTIONAL_24BAR_PCT = 0.0100
HIGH_RSI_LONG_CHASE_MIN_DIRECTIONAL_1BAR_PCT = 0.0010
HIGH_RSI_LONG_CHASE_MIN_VOLUME_RATIO = 0.75
HIGH_RSI_LONG_CHASE_MIN_RSI = 74.0
HIGH_RSI_LONG_CHASE_MIN_BODY_TO_RANGE_RATIO = 0.35

PRE_BREAK_CONTINUATION_MIN_DIRECTIONAL_24BAR_PCT = 0.0012
PRE_BREAK_CONTINUATION_MAX_DIRECTIONAL_1BAR_PCT = 0.0008
PRE_BREAK_CONTINUATION_MIN_VOLUME_RATIO = 0.60
PRE_BREAK_CONTINUATION_MAX_VOLUME_RATIO = 1.05
PRE_BREAK_CONTINUATION_MAX_BODY_TO_RANGE_RATIO = 0.55
PRE_BREAK_CONTINUATION_MIN_CLOSE_FROM_EXTREME_RATIO = 0.25
PRE_BREAK_CONTINUATION_SHORT_RSI_MIN = 40.0
PRE_BREAK_CONTINUATION_SHORT_RSI_MAX = 52.0
PRE_BREAK_CONTINUATION_LONG_RSI_MIN = 48.0
PRE_BREAK_CONTINUATION_LONG_RSI_MAX = 60.0


@dataclass(frozen=True)
class FreshEntryAssessment:
    action: str | None
    bias: str | None
    continuation_watch: bool
    terminal_extension: bool
    candidate_reasons: tuple[str, ...]
    risk_reasons: tuple[str, ...]


def _higher_timeframe_bias(symbol: SymbolSnapshot) -> str | None:
    context = symbol.higher_timeframe or {}
    bias = context.get("trend_bias")
    return str(bias) if bias is not None else None


def _resolve_action(symbol: SymbolSnapshot, action: str | None) -> tuple[str | None, str | None]:
    bias = _higher_timeframe_bias(symbol)
    if action in {"buy", "sell"}:
        return action, bias
    if bias == "long":
        return "buy", bias
    if bias == "short":
        return "sell", bias
    return None, bias


def assess_fresh_entry(symbol: SymbolSnapshot, *, action: str | None = None) -> FreshEntryAssessment:
    resolved_action, bias = _resolve_action(symbol, action)
    if resolved_action not in {"buy", "sell"} or not symbol.recent_candles:
        return FreshEntryAssessment(
            action=resolved_action,
            bias=bias,
            continuation_watch=False,
            terminal_extension=False,
            candidate_reasons=(),
            risk_reasons=(),
        )

    indicators = symbol.indicators
    return_1bar = float(indicators.get("return_1bar") or 0.0)
    return_24bars = float(indicators.get("return_24bars") or 0.0)
    rsi_14 = float(indicators.get("rsi_14") or 50.0)
    volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
    sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
    sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)

    last_candle = symbol.recent_candles[-1]
    bar_range = max(last_candle.high - last_candle.low, 0.0)
    if last_candle.close <= 0.0 or bar_range <= 0.0:
        return FreshEntryAssessment(
            action=resolved_action,
            bias=bias,
            continuation_watch=False,
            terminal_extension=False,
            candidate_reasons=(),
            risk_reasons=(),
        )

    body_to_range_ratio = abs(last_candle.close - last_candle.open) / bar_range
    if resolved_action == "sell":
        directional_1bar = max(-return_1bar, 0.0)
        directional_24bars = max(-return_24bars, 0.0)
        close_from_extreme_ratio = (last_candle.close - last_candle.low) / bar_range
        rsi_ok_for_terminal = rsi_14 <= LATE_ENTRY_SHORT_MAX_RSI
        rsi_ok_for_continuation = (
            PRE_BREAK_CONTINUATION_SHORT_RSI_MIN
            <= rsi_14
            <= PRE_BREAK_CONTINUATION_SHORT_RSI_MAX
        )
        sma_direction_ok = sma_fast_ratio < 0.0 and sma_slow_ratio < 0.0
        continuation_reason = "short_setup_pre_breakdown_watch"
        terminal_candidate_reason = "short_setup_late_breakdown_soft_penalty"
        terminal_risk_reason = "fresh_entry_late_breakdown"
    else:
        directional_1bar = max(return_1bar, 0.0)
        directional_24bars = max(return_24bars, 0.0)
        close_from_extreme_ratio = (last_candle.high - last_candle.close) / bar_range
        rsi_ok_for_terminal = rsi_14 >= LATE_ENTRY_LONG_MIN_RSI
        rsi_ok_for_continuation = (
            PRE_BREAK_CONTINUATION_LONG_RSI_MIN
            <= rsi_14
            <= PRE_BREAK_CONTINUATION_LONG_RSI_MAX
        )
        sma_direction_ok = sma_fast_ratio > 0.0 and sma_slow_ratio > 0.0
        continuation_reason = "long_setup_pre_breakout_watch"
        terminal_candidate_reason = "long_setup_late_breakout_soft_penalty"
        terminal_risk_reason = "fresh_entry_late_breakout"

    low_participation_terminal = (
        directional_24bars >= LATE_ENTRY_MIN_DIRECTIONAL_24BAR_PCT
        and directional_1bar >= LATE_ENTRY_MIN_DIRECTIONAL_1BAR_PCT
        and rsi_ok_for_terminal
        and volume_ratio <= LATE_ENTRY_MAX_CONFIRMING_VOLUME_RATIO
        and body_to_range_ratio >= LATE_ENTRY_MIN_BODY_TO_RANGE_RATIO
        and close_from_extreme_ratio <= LATE_ENTRY_MAX_CLOSE_FROM_EXTREME_RATIO
    )
    climactic_terminal = (
        directional_24bars >= CLIMACTIC_EXTENSION_MIN_DIRECTIONAL_24BAR_PCT
        and directional_1bar >= CLIMACTIC_EXTENSION_MIN_DIRECTIONAL_1BAR_PCT
        and volume_ratio >= CLIMACTIC_EXTENSION_MIN_VOLUME_RATIO
        and body_to_range_ratio >= CLIMACTIC_EXTENSION_MIN_BODY_TO_RANGE_RATIO
        and close_from_extreme_ratio <= CLIMACTIC_EXTENSION_MAX_CLOSE_FROM_EXTREME_RATIO
    )
    overextended_long_chase = (
        resolved_action == "buy"
        and directional_24bars >= OVEREXTENDED_LONG_CHASE_MIN_DIRECTIONAL_24BAR_PCT
        and directional_1bar >= OVEREXTENDED_LONG_CHASE_MIN_DIRECTIONAL_1BAR_PCT
        and volume_ratio >= OVEREXTENDED_LONG_CHASE_MIN_VOLUME_RATIO
        and rsi_14 >= OVEREXTENDED_LONG_CHASE_MIN_RSI
        and body_to_range_ratio >= OVEREXTENDED_LONG_CHASE_MIN_BODY_TO_RANGE_RATIO
        and sma_direction_ok
    )
    high_rsi_long_chase = (
        resolved_action == "buy"
        and directional_24bars >= HIGH_RSI_LONG_CHASE_MIN_DIRECTIONAL_24BAR_PCT
        and directional_1bar >= HIGH_RSI_LONG_CHASE_MIN_DIRECTIONAL_1BAR_PCT
        and volume_ratio >= HIGH_RSI_LONG_CHASE_MIN_VOLUME_RATIO
        and rsi_14 >= HIGH_RSI_LONG_CHASE_MIN_RSI
        and body_to_range_ratio >= HIGH_RSI_LONG_CHASE_MIN_BODY_TO_RANGE_RATIO
        and sma_direction_ok
    )
    if low_participation_terminal or climactic_terminal or overextended_long_chase or high_rsi_long_chase:
        return FreshEntryAssessment(
            action=resolved_action,
            bias=bias,
            continuation_watch=False,
            terminal_extension=True,
            candidate_reasons=(terminal_candidate_reason,),
            risk_reasons=(terminal_risk_reason,),
        )

    continuation_watch = (
        directional_24bars >= PRE_BREAK_CONTINUATION_MIN_DIRECTIONAL_24BAR_PCT
        and directional_1bar <= PRE_BREAK_CONTINUATION_MAX_DIRECTIONAL_1BAR_PCT
        and volume_ratio >= PRE_BREAK_CONTINUATION_MIN_VOLUME_RATIO
        and volume_ratio <= PRE_BREAK_CONTINUATION_MAX_VOLUME_RATIO
        and body_to_range_ratio <= PRE_BREAK_CONTINUATION_MAX_BODY_TO_RANGE_RATIO
        and close_from_extreme_ratio >= PRE_BREAK_CONTINUATION_MIN_CLOSE_FROM_EXTREME_RATIO
        and rsi_ok_for_continuation
        and sma_direction_ok
    )
    return FreshEntryAssessment(
        action=resolved_action,
        bias=bias,
        continuation_watch=continuation_watch,
        terminal_extension=False,
        candidate_reasons=((continuation_reason,) if continuation_watch else ()),
        risk_reasons=(),
    )
