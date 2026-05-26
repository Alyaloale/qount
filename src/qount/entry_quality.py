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
OVEREXTENDED_SHORT_CHASE_MIN_DIRECTIONAL_24BAR_PCT = 0.0035
OVEREXTENDED_SHORT_CHASE_MIN_DIRECTIONAL_1BAR_PCT = 0.0012
OVEREXTENDED_SHORT_CHASE_MIN_VOLUME_RATIO = 3.0
OVEREXTENDED_SHORT_CHASE_MAX_RSI = 35.0
OVEREXTENDED_SHORT_CHASE_MIN_BODY_TO_RANGE_RATIO = 0.45
OVEREXTENDED_SHORT_CHASE_MAX_CLOSE_FROM_EXTREME_RATIO = 0.30
SHORT_BREAKDOWN_CONFIRMED_MIN_DIRECTIONAL_24BAR_PCT = 0.0032
SHORT_BREAKDOWN_CONFIRMED_MAX_DIRECTIONAL_24BAR_PCT = 0.0095
SHORT_BREAKDOWN_CONFIRMED_MIN_DIRECTIONAL_1BAR_PCT = 0.0014
SHORT_BREAKDOWN_CONFIRMED_MIN_VOLUME_RATIO = 1.00
SHORT_BREAKDOWN_CONFIRMED_MIN_RSI = 24.0
SHORT_BREAKDOWN_CONFIRMED_MAX_RSI = 34.0
SHORT_BREAKDOWN_CONFIRMED_MIN_BODY_TO_RANGE_RATIO = 0.50
SHORT_BREAKDOWN_CONFIRMED_MIN_CLOSE_FROM_EXTREME_RATIO = 0.18
SHORT_BREAKDOWN_CONFIRMED_MAX_CLOSE_FROM_EXTREME_RATIO = 0.38
SHORT_BREAKDOWN_CONFIRMED_MIN_FAST_SMA_RATIO = -0.0035
SHORT_BREAKDOWN_CONFIRMED_MIN_SLOW_SMA_RATIO = -0.0060
HIGH_RSI_LONG_CHASE_MIN_DIRECTIONAL_24BAR_PCT = 0.0100
HIGH_RSI_LONG_CHASE_MIN_DIRECTIONAL_1BAR_PCT = 0.0010
HIGH_RSI_LONG_CHASE_MIN_VOLUME_RATIO = 0.75
HIGH_RSI_LONG_CHASE_MIN_RSI = 74.0
HIGH_RSI_LONG_CHASE_MIN_BODY_TO_RANGE_RATIO = 0.35
WEAK_LONG_RECLAIM_MIN_DIRECTIONAL_24BAR_PCT = 0.0020
WEAK_LONG_RECLAIM_MAX_DIRECTIONAL_24BAR_PCT = 0.0050
WEAK_LONG_RECLAIM_MIN_DIRECTIONAL_1BAR_PCT = 0.0018
WEAK_LONG_RECLAIM_MIN_VOLUME_RATIO = 1.40
WEAK_LONG_RECLAIM_MIN_RSI = 64.0
WEAK_LONG_RECLAIM_MIN_BODY_TO_RANGE_RATIO = 0.45
WEAK_LONG_RECLAIM_MAX_CLOSE_FROM_EXTREME_RATIO = 0.35
WEAK_LONG_RECLAIM_MIN_FAST_SMA_RATIO = 0.0015
WEAK_LONG_RECLAIM_MIN_SLOW_SMA_RATIO = 0.0015
TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_24BAR_PCT = 0.0035
TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_FAST_SMA_RATIO = 0.0015
TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_SLOW_SMA_RATIO = 0.0020
TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_RSI = 60.0
TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_VOLUME_RATIO = 0.90

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
TRADITIONAL_SIGNAL_LOOKBACK_BARS = 4
TRADITIONAL_SIGNAL_TERMINAL_VOLUME_RATIO = 1.75
TRADITIONAL_SIGNAL_TERMINAL_EXPANSION_RATIO = 1.35
STRUCTURAL_RANGE_NOISE_SHORT_MIN_CONVICTION_SCORE = 0.60
STRUCTURAL_RANGE_NOISE_SHORT_MIN_REBOUND_FAILURE_PCT = 0.0075
STRUCTURAL_RANGE_NOISE_SHORT_MIN_SUPPORT_BREAK_PCT = 0.0018
STRUCTURAL_RANGE_NOISE_SHORT_MIN_RANGE_EXPANSION_RATIO = 0.90


@dataclass(frozen=True)
class FreshEntryAssessment:
    action: str | None
    bias: str | None
    continuation_watch: bool
    terminal_extension: bool
    setup_phase: str
    setup_confirmed: bool
    candidate_reasons: tuple[str, ...]
    risk_reasons: tuple[str, ...]


def build_entry_thesis_candidate(
    symbol: SymbolSnapshot,
    assessment: FreshEntryAssessment | None,
) -> dict[str, object] | None:
    if assessment is None or assessment.action not in {"buy", "sell"}:
        return None
    if assessment.setup_phase == "range_noise":
        return _build_structural_range_noise_short_thesis(symbol, assessment)
    if assessment.terminal_extension:
        return None

    higher = symbol.higher_timeframe or {}
    setup_phase = str(assessment.setup_phase or "range_noise")
    if setup_phase in {"short_continuation_confirmed", "long_continuation_confirmed"}:
        invalidation_type = "continuation_follow_through_failed"
        follow_through_bars = 2
    elif setup_phase == "short_breakdown_confirmed":
        invalidation_type = "breakdown_reclaimed"
        follow_through_bars = 1
    elif setup_phase == "short_rebound_fail_confirmed":
        invalidation_type = "rebound_fail_reclaimed"
        follow_through_bars = 2
    elif setup_phase == "long_pullback_reclaim_confirmed":
        invalidation_type = "reclaim_failed"
        follow_through_bars = 2
    elif setup_phase == "long_pullback_reclaim_unconfirmed":
        invalidation_type = "early_reclaim_failed"
        follow_through_bars = 1
    else:
        invalidation_type = "generic_structure_lost"
        follow_through_bars = 1

    return {
        "version": 1,
        "direction": "long" if assessment.action == "buy" else "short",
        "higher_timeframe_direction": higher.get("trend_direction") or higher.get("trend_bias"),
        "higher_timeframe_phase": higher.get("trend_phase"),
        "setup_phase": setup_phase,
        "setup_confirmed": bool(assessment.setup_confirmed),
        "invalidation_type": invalidation_type,
        "follow_through_bars": follow_through_bars,
    }


def _build_structural_range_noise_short_thesis(
    symbol: SymbolSnapshot,
    assessment: FreshEntryAssessment,
) -> dict[str, object] | None:
    if symbol.symbol != "ETH/USDT:USDT" or assessment.action != "sell":
        return None
    if assessment.terminal_extension or assessment.setup_phase != "range_noise":
        return None
    higher = symbol.higher_timeframe or {}
    if str(higher.get("trend_bias") or "") != "short":
        return None
    higher_phase = str(higher.get("trend_phase") or "")
    if higher_phase not in {"trend", "reclaim", "exhaustion"}:
        return None
    traditional_context = build_traditional_signal_context(symbol, assessment)
    if not isinstance(traditional_context, dict):
        return None
    if bool(traditional_context.get("terminal_risk")):
        return None
    if str(traditional_context.get("pattern_family") or "") != "short":
        return None
    if float(traditional_context.get("conviction_score") or 0.0) < STRUCTURAL_RANGE_NOISE_SHORT_MIN_CONVICTION_SCORE:
        return None
    if float(traditional_context.get("rebound_failure_pct") or 0.0) < STRUCTURAL_RANGE_NOISE_SHORT_MIN_REBOUND_FAILURE_PCT:
        return None
    if float(traditional_context.get("support_break_pct") or 0.0) < STRUCTURAL_RANGE_NOISE_SHORT_MIN_SUPPORT_BREAK_PCT:
        return None
    if float(traditional_context.get("range_expansion_ratio") or 0.0) < STRUCTURAL_RANGE_NOISE_SHORT_MIN_RANGE_EXPANSION_RATIO:
        return None

    return {
        "version": 2,
        "direction": "short",
        "higher_timeframe_direction": higher.get("trend_direction") or higher.get("trend_bias"),
        "higher_timeframe_phase": higher_phase,
        "setup_phase": "eth_structural_range_noise_short",
        "setup_confirmed": True,
        "invalidation_type": "structural_breakdown_reclaimed",
        "follow_through_bars": 2,
        "traditional_pattern_label": traditional_context.get("pattern_label"),
        "traditional_conviction_score": traditional_context.get("conviction_score"),
        "rebound_failure_pct": traditional_context.get("rebound_failure_pct"),
        "support_break_pct": traditional_context.get("support_break_pct"),
        "range_expansion_ratio": traditional_context.get("range_expansion_ratio"),
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _range_pct(open_price: float, high_price: float, low_price: float, close_price: float) -> float:
    if close_price <= 0.0:
        return 0.0
    return max(high_price - low_price, 0.0) / close_price


def build_traditional_signal_context(
    symbol: SymbolSnapshot,
    assessment: FreshEntryAssessment | None,
) -> dict[str, object] | None:
    if assessment is None or assessment.action not in {"buy", "sell"}:
        return None
    if len(symbol.recent_candles) < (TRADITIONAL_SIGNAL_LOOKBACK_BARS + 1):
        return None

    candles = symbol.recent_candles[-(TRADITIONAL_SIGNAL_LOOKBACK_BARS + 1):]
    last_candle = candles[-1]
    prior_candles = candles[:-1]
    if last_candle.close <= 0.0:
        return None

    indicators = symbol.indicators
    higher = symbol.higher_timeframe or {}
    atr_pct = float(indicators.get("atr_14_pct") or 0.0)
    volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
    rsi_14 = float(indicators.get("rsi_14") or 50.0)
    trend_strength = max(float(higher.get("trend_strength") or 0.0), 0.0)
    last_range_pct = _range_pct(
        last_candle.open,
        last_candle.high,
        last_candle.low,
        last_candle.close,
    )
    prior_range_pcts = [
        _range_pct(candle.open, candle.high, candle.low, candle.close)
        for candle in prior_candles
        if candle.close > 0.0
    ]
    if not prior_range_pcts:
        return None
    avg_prior_range_pct = sum(prior_range_pcts) / len(prior_range_pcts)
    range_expansion_ratio = (
        last_range_pct / avg_prior_range_pct
        if avg_prior_range_pct > 0.0
        else 0.0
    )
    compression_score = (
        0.0
        if atr_pct <= 0.0
        else _clamp01((atr_pct - avg_prior_range_pct) / atr_pct)
    )
    trend_score = _clamp01(trend_strength / 3.0)
    expansion_score = _clamp01((range_expansion_ratio - 1.0) / 1.0)
    volume_score = _clamp01(volume_ratio / 1.5)

    if assessment.action == "sell":
        close_from_extreme_ratio = (
            0.0
            if last_candle.high <= last_candle.low
            else (last_candle.close - last_candle.low) / (last_candle.high - last_candle.low)
        )
        rebound_peak_pct = max(
            (max(candle.high for candle in prior_candles) - last_candle.close) / last_candle.close,
            0.0,
        )
        support_break_pct = max(
            (min(candle.close for candle in prior_candles) - last_candle.close) / last_candle.close,
            0.0,
        )
        lower_high_count = sum(
            1
            for previous, current in zip(prior_candles, prior_candles[1:])
            if current.high <= previous.high
        )
        rebound_score = _clamp01(rebound_peak_pct / 0.0040)
        support_break_score = _clamp01(support_break_pct / 0.0015)
        staircase_score = _clamp01(lower_high_count / 3.0)
        terminal_risk = bool(assessment.terminal_extension) or (
            close_from_extreme_ratio <= 0.10
            and volume_ratio >= TRADITIONAL_SIGNAL_TERMINAL_VOLUME_RATIO
            and range_expansion_ratio >= TRADITIONAL_SIGNAL_TERMINAL_EXPANSION_RATIO
            and rsi_14 <= 30.0
        )
        if assessment.setup_phase == "short_rebound_fail_confirmed":
            pattern_label = "failed_rebound_breakdown"
        elif assessment.setup_phase == "short_breakdown_confirmed":
            if rebound_peak_pct >= 0.0020 and not terminal_risk:
                pattern_label = "failed_rebound_breakdown"
            elif support_break_pct >= 0.0004 and compression_score >= 0.15 and not terminal_risk:
                pattern_label = "fresh_support_break"
            else:
                pattern_label = "trend_breakdown_pressure"
        elif assessment.setup_phase == "short_continuation_confirmed":
            pattern_label = "trend_continuation_pressure"
        else:
            pattern_label = "short_structure_mixed"
        conviction_score = (
            (0.24 * trend_score)
            + (0.22 * expansion_score)
            + (0.18 * volume_score)
            + (0.18 * max(rebound_score, support_break_score))
            + (0.10 * compression_score)
            + (0.08 * staircase_score)
        )
        if terminal_risk:
            conviction_score = max(conviction_score - 0.12, 0.0)
        notes = [
            pattern_label,
            "terminal_risk" if terminal_risk else "terminal_risk_low",
        ]
        return {
            "pattern_family": "short",
            "pattern_label": pattern_label,
            "conviction_score": round(conviction_score, 6),
            "terminal_risk": terminal_risk,
            "rebound_failure_pct": round(rebound_peak_pct, 6),
            "support_break_pct": round(support_break_pct, 6),
            "range_expansion_ratio": round(range_expansion_ratio, 6),
            "compression_score": round(compression_score, 6),
            "trend_strength": round(trend_strength, 6),
            "notes": notes,
        }

    close_from_extreme_ratio = (
        0.0
        if last_candle.high <= last_candle.low
        else (last_candle.high - last_candle.close) / (last_candle.high - last_candle.low)
    )
    reclaim_from_low_pct = max(
        (last_candle.close - min(candle.low for candle in prior_candles)) / last_candle.close,
        0.0,
    )
    resistance_reclaim_pct = max(
        (last_candle.close - max(candle.close for candle in prior_candles)) / last_candle.close,
        0.0,
    )
    higher_low_count = sum(
        1
        for previous, current in zip(prior_candles, prior_candles[1:])
        if current.low >= previous.low
    )
    reclaim_score = _clamp01(reclaim_from_low_pct / 0.0040)
    resistance_score = _clamp01(resistance_reclaim_pct / 0.0015)
    staircase_score = _clamp01(higher_low_count / 3.0)
    terminal_risk = bool(assessment.terminal_extension) or (
        close_from_extreme_ratio <= 0.10
        and volume_ratio >= TRADITIONAL_SIGNAL_TERMINAL_VOLUME_RATIO
        and range_expansion_ratio >= TRADITIONAL_SIGNAL_TERMINAL_EXPANSION_RATIO
        and rsi_14 >= 70.0
    )
    if assessment.setup_phase == "long_pullback_reclaim_confirmed":
        if reclaim_from_low_pct >= 0.0020 and not terminal_risk:
            pattern_label = "failed_breakdown_reclaim"
        elif resistance_reclaim_pct >= 0.0004 and compression_score >= 0.15 and not terminal_risk:
            pattern_label = "fresh_resistance_reclaim"
        else:
            pattern_label = "trend_reclaim_pressure"
    elif assessment.setup_phase == "long_pullback_reclaim_unconfirmed":
        pattern_label = "early_reclaim_pressure"
    elif assessment.setup_phase == "long_continuation_confirmed":
        pattern_label = "trend_continuation_push"
    else:
        pattern_label = "long_structure_mixed"
    conviction_score = (
        (0.24 * trend_score)
        + (0.22 * expansion_score)
        + (0.18 * volume_score)
        + (0.18 * max(reclaim_score, resistance_score))
        + (0.10 * compression_score)
        + (0.08 * staircase_score)
    )
    if terminal_risk:
        conviction_score = max(conviction_score - 0.12, 0.0)
    notes = [
        pattern_label,
        "terminal_risk" if terminal_risk else "terminal_risk_low",
    ]
    return {
        "pattern_family": "long",
        "pattern_label": pattern_label,
        "conviction_score": round(conviction_score, 6),
        "terminal_risk": terminal_risk,
        "reclaim_from_low_pct": round(reclaim_from_low_pct, 6),
        "resistance_reclaim_pct": round(resistance_reclaim_pct, 6),
        "range_expansion_ratio": round(range_expansion_ratio, 6),
        "compression_score": round(compression_score, 6),
        "trend_strength": round(trend_strength, 6),
        "notes": notes,
    }


def _higher_timeframe_bias(symbol: SymbolSnapshot) -> str | None:
    context = symbol.higher_timeframe or {}
    bias = context.get("trend_direction")
    if bias is None:
        bias = context.get("trend_bias")
    return str(bias) if bias is not None else None


def _higher_timeframe_phase(symbol: SymbolSnapshot) -> str | None:
    context = symbol.higher_timeframe or {}
    phase = context.get("trend_phase")
    return str(phase) if phase is not None else None


def _empty_assessment(action: str | None, bias: str | None) -> FreshEntryAssessment:
    return FreshEntryAssessment(
        action=action,
        bias=bias,
        continuation_watch=False,
        terminal_extension=False,
        setup_phase="range_noise",
        setup_confirmed=False,
        candidate_reasons=(),
        risk_reasons=(),
    )


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
        return _empty_assessment(resolved_action, bias)

    indicators = symbol.indicators
    return_1bar = float(indicators.get("return_1bar") or 0.0)
    return_24bars = float(indicators.get("return_24bars") or 0.0)
    rsi_14 = float(indicators.get("rsi_14") or 50.0)
    volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
    sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
    sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
    higher_phase = _higher_timeframe_phase(symbol)

    last_candle = symbol.recent_candles[-1]
    bar_range = max(last_candle.high - last_candle.low, 0.0)
    if last_candle.close <= 0.0 or bar_range <= 0.0:
        return _empty_assessment(resolved_action, bias)

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
        reclaim_confirmed_reason = "short_setup_rebound_fail_confirmed"
        breakdown_confirmed_reason = "short_setup_breakdown_confirmed"
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
        reclaim_confirmed_reason = "long_setup_pullback_reclaim_confirmed"
        reclaim_unconfirmed_reason = "long_setup_pullback_reclaim_unconfirmed"

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
    overextended_short_chase = (
        resolved_action == "sell"
        and directional_24bars >= OVEREXTENDED_SHORT_CHASE_MIN_DIRECTIONAL_24BAR_PCT
        and directional_1bar >= OVEREXTENDED_SHORT_CHASE_MIN_DIRECTIONAL_1BAR_PCT
        and volume_ratio >= OVEREXTENDED_SHORT_CHASE_MIN_VOLUME_RATIO
        and rsi_14 <= OVEREXTENDED_SHORT_CHASE_MAX_RSI
        and body_to_range_ratio >= OVEREXTENDED_SHORT_CHASE_MIN_BODY_TO_RANGE_RATIO
        and close_from_extreme_ratio <= OVEREXTENDED_SHORT_CHASE_MAX_CLOSE_FROM_EXTREME_RATIO
        and sma_direction_ok
    )
    short_breakdown_confirmed = (
        resolved_action == "sell"
        and bias == "short"
        and higher_phase in {"trend", "pullback", "reclaim"}
        and directional_24bars >= SHORT_BREAKDOWN_CONFIRMED_MIN_DIRECTIONAL_24BAR_PCT
        and directional_24bars <= SHORT_BREAKDOWN_CONFIRMED_MAX_DIRECTIONAL_24BAR_PCT
        and directional_1bar >= SHORT_BREAKDOWN_CONFIRMED_MIN_DIRECTIONAL_1BAR_PCT
        and volume_ratio >= SHORT_BREAKDOWN_CONFIRMED_MIN_VOLUME_RATIO
        and rsi_14 >= SHORT_BREAKDOWN_CONFIRMED_MIN_RSI
        and rsi_14 <= SHORT_BREAKDOWN_CONFIRMED_MAX_RSI
        and body_to_range_ratio >= SHORT_BREAKDOWN_CONFIRMED_MIN_BODY_TO_RANGE_RATIO
        and close_from_extreme_ratio >= SHORT_BREAKDOWN_CONFIRMED_MIN_CLOSE_FROM_EXTREME_RATIO
        and close_from_extreme_ratio <= SHORT_BREAKDOWN_CONFIRMED_MAX_CLOSE_FROM_EXTREME_RATIO
        and sma_fast_ratio >= SHORT_BREAKDOWN_CONFIRMED_MIN_FAST_SMA_RATIO
        and sma_slow_ratio >= SHORT_BREAKDOWN_CONFIRMED_MIN_SLOW_SMA_RATIO
        and sma_direction_ok
    )
    weak_long_reclaim_chase = (
        resolved_action == "buy"
        and bias == "long"
        and directional_24bars >= WEAK_LONG_RECLAIM_MIN_DIRECTIONAL_24BAR_PCT
        and directional_24bars <= WEAK_LONG_RECLAIM_MAX_DIRECTIONAL_24BAR_PCT
        and directional_1bar >= WEAK_LONG_RECLAIM_MIN_DIRECTIONAL_1BAR_PCT
        and volume_ratio >= WEAK_LONG_RECLAIM_MIN_VOLUME_RATIO
        and rsi_14 >= WEAK_LONG_RECLAIM_MIN_RSI
        and body_to_range_ratio >= WEAK_LONG_RECLAIM_MIN_BODY_TO_RANGE_RATIO
        and close_from_extreme_ratio <= WEAK_LONG_RECLAIM_MAX_CLOSE_FROM_EXTREME_RATIO
        and sma_fast_ratio >= WEAK_LONG_RECLAIM_MIN_FAST_SMA_RATIO
        and sma_slow_ratio >= WEAK_LONG_RECLAIM_MIN_SLOW_SMA_RATIO
    )
    trend_phase_long_reclaim_extension = (
        resolved_action == "buy"
        and bias == "long"
        and higher_phase == "trend"
        and directional_24bars >= TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_24BAR_PCT
        and directional_1bar >= 0.0004
        and volume_ratio >= TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_VOLUME_RATIO
        and rsi_14 >= TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_RSI
        and sma_fast_ratio >= TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_FAST_SMA_RATIO
        and sma_slow_ratio >= TREND_PHASE_LONG_RECLAIM_EXTENSION_MIN_SLOW_SMA_RATIO
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
    if continuation_watch:
        return FreshEntryAssessment(
            action=resolved_action,
            bias=bias,
            continuation_watch=True,
            terminal_extension=False,
            setup_phase=(
                "short_continuation_confirmed"
                if resolved_action == "sell"
                else "long_continuation_confirmed"
            ),
            setup_confirmed=True,
            candidate_reasons=(continuation_reason,),
            risk_reasons=(),
        )

    if short_breakdown_confirmed:
        return FreshEntryAssessment(
            action=resolved_action,
            bias=bias,
            continuation_watch=False,
            terminal_extension=False,
            setup_phase="short_breakdown_confirmed",
            setup_confirmed=True,
            candidate_reasons=(breakdown_confirmed_reason,),
            risk_reasons=(),
        )

    if (
        low_participation_terminal
        or climactic_terminal
        or overextended_long_chase
        or high_rsi_long_chase
        or overextended_short_chase
        or weak_long_reclaim_chase
        or trend_phase_long_reclaim_extension
    ):
        setup_phase = (
            "long_pullback_reclaim_unconfirmed"
            if weak_long_reclaim_chase
            else "short_breakdown_chase"
            if resolved_action == "sell"
            else "long_late_breakout_chase"
        )
        return FreshEntryAssessment(
            action=resolved_action,
            bias=bias,
            continuation_watch=False,
            terminal_extension=True,
            setup_phase=setup_phase,
            setup_confirmed=False,
            candidate_reasons=(terminal_candidate_reason,),
            risk_reasons=(terminal_risk_reason,),
        )

    long_pullback_reclaim_confirmed = (
        resolved_action == "buy"
        and bias == "long"
        and higher_phase in {"trend", "pullback", "reclaim"}
        and directional_24bars <= 0.0045
        and return_24bars >= -0.0060
        and directional_1bar >= 0.0002
        and volume_ratio >= 0.70
        and rsi_14 >= 50.0
        and sma_fast_ratio >= -0.0002
        and sma_slow_ratio >= -0.0015
        and close_from_extreme_ratio <= 0.55
    )
    if long_pullback_reclaim_confirmed:
        return FreshEntryAssessment(
            action=resolved_action,
            bias=bias,
            continuation_watch=False,
            terminal_extension=False,
            setup_phase="long_pullback_reclaim_confirmed",
            setup_confirmed=True,
            candidate_reasons=(reclaim_confirmed_reason,),
            risk_reasons=(),
        )

    long_pullback_reclaim_unconfirmed = (
        resolved_action == "buy"
        and bias == "long"
        and higher_phase in {"trend", "pullback", "reclaim"}
        and return_24bars >= -0.0075
        and return_24bars <= 0.0045
        and return_1bar >= -0.0003
        and volume_ratio >= 0.55
        and sma_slow_ratio >= -0.0015
    )
    if long_pullback_reclaim_unconfirmed:
        return FreshEntryAssessment(
            action=resolved_action,
            bias=bias,
            continuation_watch=False,
            terminal_extension=False,
            setup_phase="long_pullback_reclaim_unconfirmed",
            setup_confirmed=False,
            candidate_reasons=(reclaim_unconfirmed_reason,),
            risk_reasons=(),
        )

    short_rebound_fail_confirmed = (
        resolved_action == "sell"
        and bias == "short"
        and higher_phase in {"trend", "pullback", "reclaim"}
        and return_24bars <= 0.0020
        and return_24bars >= -0.0040
        and directional_1bar >= 0.0004
        and volume_ratio >= 0.90
        and rsi_14 <= 48.0
        and sma_fast_ratio < 0.0
        and sma_slow_ratio <= 0.0
        and close_from_extreme_ratio <= 0.55
    )
    if short_rebound_fail_confirmed:
        return FreshEntryAssessment(
            action=resolved_action,
            bias=bias,
            continuation_watch=False,
            terminal_extension=False,
            setup_phase="short_rebound_fail_confirmed",
            setup_confirmed=True,
            candidate_reasons=(reclaim_confirmed_reason,),
            risk_reasons=(),
        )

    return FreshEntryAssessment(
        action=resolved_action,
        bias=bias,
        continuation_watch=False,
        terminal_extension=False,
        setup_phase="range_noise",
        setup_confirmed=False,
        candidate_reasons=(),
        risk_reasons=(),
    )
