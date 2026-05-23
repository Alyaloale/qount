from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .entry_quality import assess_fresh_entry
from .entry_quality import build_entry_thesis_candidate
from .entry_quality import build_traditional_signal_context
from .journal import Journal
from .models import MarketSnapshotBundle, SymbolSnapshot
from .setup_model import load_setup_model_bundle
from .setup_model import score_setup_edge_model_signal
from .settings import Settings
from .trade_policy import is_open_action
from .trade_policy import timeframe_to_ms


MIN_CANDIDATE_VOLATILITY_PCT = 0.0020
MIN_CANDIDATE_VOLUME_RATIO = 0.60
HARD_MIN_CANDIDATE_VOLATILITY_PCT = 0.0015
HARD_MIN_CANDIDATE_VOLUME_RATIO = 0.45
MAX_CANDIDATE_SYMBOLS = 2
BOTTOM_LINE_MAX_CANDIDATE_SYMBOLS = 3
FLAT_TREND_SCORE_PENALTY = 0.75
FRESH_ENTRY_EXHAUSTION_SCORE_PENALTY = 1.25
PRE_BREAK_CONTINUATION_SCORE_BONUS = 0.75
WEAK_LOW_VOLATILITY_FRESH_ENTRY_SCORE_PENALTY = 0.60
# Only veto clearly countertrend short candidates. A tiny green 5m bar inside a
# still-bearish 1h structure should be allowed through to AI/risk review.
SHORT_REBOUND_1BAR_PCT = 0.0015
SHORT_COUNTERTREND_24BAR_PCT = 0.0025
CONFIRMED_PULLBACK_RECLAIM_SCORE_BONUS = 0.65
UNCONFIRMED_PULLBACK_RECLAIM_SCORE_PENALTY = 0.55
RANGE_NOISE_SCORE_PENALTY = 0.15
EXHAUSTION_PHASE_CHASE_SCORE_PENALTY = 0.40
PULLBACK_PHASE_CONTINUATION_SCORE_PENALTY = 0.10
TRADITIONAL_SIGNAL_SCORE_MULTIPLIER = 0.45
TRADITIONAL_SIGNAL_TERMINAL_RISK_PENALTY = 0.20
HOURLY_MODEL_ALIGN_SCORE_MULTIPLIER = 0.20
HOURLY_MODEL_CONFLICT_SCORE_MULTIPLIER = 0.25
SETUP_MODEL_EDGE_SCALE_PCT = 0.0012
SETUP_MODEL_FAVORABLE_SCORE_MULTIPLIER = 0.55
SETUP_MODEL_UNFAVORABLE_SCORE_MULTIPLIER = 0.70
ETH_RECLAIM_SHORT_REENTRY_COOLDOWN_BARS = 6
ETH_RANGE_NOISE_SHORT_MIN_CONVICTION_SCORE = 0.60
ETH_RANGE_NOISE_SHORT_MIN_REBOUND_FAILURE_PCT = 0.0075
ETH_RANGE_NOISE_SHORT_MIN_SUPPORT_BREAK_PCT = 0.0018
ETH_RANGE_NOISE_SHORT_MIN_RANGE_EXPANSION_RATIO = 0.90
HARD_BOTTOM_LINE_REASONS = (
    "low_volatility",
    "low_volume",
    "higher_timeframe_unavailable",
    "same_symbol_reentry_cooldown_active",
    "loss_reentry_cooldown_active",
    "recent_action_cooldown_active",
    "short_setup_countertrend_drift",
    "short_setup_latest_bar_rebound",
    "setup_model_unfavorable_short_rebound_fail",
    "setup_model_weak_pullback_short_rebound_fail",
    "eth_short_range_noise_requires_breakdown_structure",
    "max_open_positions_reached",
)


@dataclass
class CandidateFilterResult:
    status: str
    filtered_bundle: MarketSnapshotBundle | None
    summary: dict[str, Any]


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


def _bars_since(current_ts: int, previous_ts: int | None, timeframe_ms: int) -> int | None:
    if previous_ts is None or current_ts <= previous_ts:
        return None
    return max(0, (current_ts - previous_ts) // timeframe_ms)


def _candidate_target_direction(symbol: SymbolSnapshot) -> int | None:
    bias = _higher_timeframe_bias(symbol)
    if bias == "long":
        return 1
    if bias == "short":
        return -1
    return None


def _closed_position_direction(position_side_before_action: str | None) -> int | None:
    if position_side_before_action == "long":
        return 1
    if position_side_before_action == "short":
        return -1
    return None


def _is_forced_loss_close(action_item: dict[str, Any] | None, desired_direction: int | None) -> bool:
    if action_item is None or desired_direction is None:
        return False
    previous_direction = _closed_position_direction(
        None if action_item.get("position_side_before_action") is None else str(action_item.get("position_side_before_action"))
    )
    if previous_direction is None or previous_direction != desired_direction:
        return False
    risk_reasons = [str(reason) for reason in (action_item.get("risk_reasons") or [])]
    return any(
        reason == "management_adverse_hold_to_close"
        or reason.startswith("management_stop_loss_hit:")
        or reason.startswith("management_adverse_loss_cut:")
        for reason in risk_reasons
    )


def _loss_reentry_cooldown_bars(settings: Settings) -> int:
    return max(
        settings.same_symbol_reentry_cooldown_bars,
        settings.same_symbol_reentry_cooldown_bars + settings.cooldown_bars_after_losses,
    )


def _short_candidate_precheck(symbol: SymbolSnapshot) -> list[str]:
    trend_bias = _higher_timeframe_bias(symbol)
    if trend_bias != "short":
        return []

    indicators = symbol.indicators
    return_1bar = float(indicators.get("return_1bar") or 0.0)
    return_24bars = float(indicators.get("return_24bars") or 0.0)
    sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
    sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
    reasons: list[str] = []

    # Avoid sending obvious rebound / countertrend short candidates to the model.
    if return_24bars > SHORT_COUNTERTREND_24BAR_PCT and sma_slow_ratio >= 0.0:
        reasons.append("short_setup_countertrend_drift")
    if return_1bar > SHORT_REBOUND_1BAR_PCT and sma_fast_ratio >= 0.0:
        reasons.append("short_setup_latest_bar_rebound")
    return reasons


def _candidate_quality_gate(
    *,
    volatility_pct: float,
    volume_ratio: float,
    trend_bias: str | None,
) -> tuple[bool, list[str]]:
    directional_bias = trend_bias in {"long", "short"}
    eligible = True
    reasons: list[str] = []

    if volatility_pct < HARD_MIN_CANDIDATE_VOLATILITY_PCT:
        eligible = False
        reasons.append("low_volatility")
    elif volatility_pct < MIN_CANDIDATE_VOLATILITY_PCT:
        if directional_bias:
            reasons.append("low_volatility_soft_penalty")
        else:
            eligible = False
            reasons.append("low_volatility")

    if volume_ratio < HARD_MIN_CANDIDATE_VOLUME_RATIO:
        eligible = False
        reasons.append("low_volume")
    elif volume_ratio < MIN_CANDIDATE_VOLUME_RATIO:
        if directional_bias:
            reasons.append("low_volume_soft_penalty")
        else:
            eligible = False
            reasons.append("low_volume")

    return eligible, reasons


def _should_penalize_soft_low_volatility_fresh_entry(
    *,
    reasons: list[str],
    fresh_entry_assessment,
    manage_only: bool,
) -> bool:
    if manage_only or fresh_entry_assessment is None:
        return False
    if fresh_entry_assessment.continuation_watch:
        return False
    return "low_volatility_soft_penalty" in reasons


def _phase_match_score(
    *,
    fresh_entry_assessment,
    higher_timeframe_phase: str | None,
    manage_only: bool,
) -> float:
    if manage_only or fresh_entry_assessment is None:
        return 0.0

    setup_phase = fresh_entry_assessment.setup_phase
    score = 0.0
    if setup_phase in {"long_pullback_reclaim_confirmed", "short_rebound_fail_confirmed", "short_breakdown_confirmed"}:
        score += CONFIRMED_PULLBACK_RECLAIM_SCORE_BONUS
    elif setup_phase == "long_pullback_reclaim_unconfirmed":
        score -= UNCONFIRMED_PULLBACK_RECLAIM_SCORE_PENALTY
    elif setup_phase == "range_noise":
        score -= RANGE_NOISE_SCORE_PENALTY

    if higher_timeframe_phase == "exhaustion" and (
        setup_phase.endswith("_chase") or setup_phase.endswith("_unconfirmed")
    ):
        score -= EXHAUSTION_PHASE_CHASE_SCORE_PENALTY
    elif higher_timeframe_phase == "pullback" and setup_phase.endswith("continuation_confirmed"):
        score -= PULLBACK_PHASE_CONTINUATION_SCORE_PENALTY
    return score


def _bottom_line_candidate_allowed(reasons: list[str]) -> bool:
    return not any(
        any(reason == hard_reason or reason.startswith(f"{hard_reason}:") for hard_reason in HARD_BOTTOM_LINE_REASONS)
        for reason in reasons
    )


def _same_symbol_reentry_cooldown_bars(
    settings: Settings,
    *,
    symbol_name: str,
    latest_close: dict[str, Any] | None,
    desired_direction: int | None,
) -> int:
    base_cooldown = settings.same_symbol_reentry_cooldown_bars
    if (
        latest_close is None
        or desired_direction != -1
        or symbol_name != "ETH/USDT:USDT"
        or str(latest_close.get("final_action") or "") != "close"
    ):
        return base_cooldown
    if str(latest_close.get("entry_setup_phase") or "") != "short_rebound_fail_confirmed":
        return base_cooldown
    if str(latest_close.get("entry_higher_timeframe_phase") or "") != "reclaim":
        return base_cooldown
    return max(base_cooldown, ETH_RECLAIM_SHORT_REENTRY_COOLDOWN_BARS)


def _traditional_signal_score_delta(
    traditional_signal_context: dict[str, object] | None,
    *,
    manage_only: bool,
) -> float:
    if manage_only or not isinstance(traditional_signal_context, dict):
        return 0.0
    conviction_score = float(traditional_signal_context.get("conviction_score") or 0.0)
    delta = conviction_score * TRADITIONAL_SIGNAL_SCORE_MULTIPLIER
    if bool(traditional_signal_context.get("terminal_risk")):
        delta -= TRADITIONAL_SIGNAL_TERMINAL_RISK_PENALTY
    return delta


def _hourly_model_score_delta(
    symbol: SymbolSnapshot,
    *,
    manage_only: bool,
) -> float:
    if manage_only:
        return 0.0
    higher = symbol.higher_timeframe or {}
    model_signal = higher.get("model_signal")
    if not isinstance(model_signal, dict):
        return 0.0
    direction = str(model_signal.get("direction") or "flat")
    if direction == "flat":
        return 0.0
    bias = _higher_timeframe_bias(symbol)
    if bias not in {"long", "short"}:
        return 0.0
    strength = min(max(float(model_signal.get("prediction_strength") or 0.0), 0.0), 2.0)
    if direction == bias:
        return strength * HOURLY_MODEL_ALIGN_SCORE_MULTIPLIER
    return -(strength * HOURLY_MODEL_CONFLICT_SCORE_MULTIPLIER)


def _setup_model_score_delta(
    setup_model_signal: dict[str, object] | None,
    *,
    manage_only: bool,
) -> float:
    if manage_only or not isinstance(setup_model_signal, dict):
        return 0.0
    predicted_edge_pct = float(setup_model_signal.get("predicted_edge_pct") or 0.0)
    confidence_ratio = min(max(float(setup_model_signal.get("confidence_ratio") or 0.0), 0.0), 3.0)
    label = str(setup_model_signal.get("label") or "neutral")
    quality = str(setup_model_signal.get("quality") or "neutral")
    normalized_edge = min(abs(predicted_edge_pct) / SETUP_MODEL_EDGE_SCALE_PCT, 2.0)
    magnitude = normalized_edge * (0.5 + min(confidence_ratio, 2.0) * 0.25)
    if label == "favorable":
        if quality == "weak_favorable":
            return magnitude * 0.10
        return magnitude * SETUP_MODEL_FAVORABLE_SCORE_MULTIPLIER
    if label == "unfavorable":
        return -(magnitude * SETUP_MODEL_UNFAVORABLE_SCORE_MULTIPLIER)
    return 0.0


def _setup_model_entry_block_reason(
    symbol: SymbolSnapshot,
    setup_model_signal: dict[str, object] | None,
    *,
    fresh_entry_assessment,
    manage_only: bool,
) -> str | None:
    if manage_only or fresh_entry_assessment is None or not isinstance(setup_model_signal, dict):
        return None
    if fresh_entry_assessment.setup_phase != "short_rebound_fail_confirmed":
        return None
    sample_count = int(setup_model_signal.get("sample_count") or 0)
    if sample_count < 20:
        return None
    label = str(setup_model_signal.get("label") or "neutral")
    if label == "unfavorable":
        return "setup_model_unfavorable_short_rebound_fail"
    if (
        symbol.symbol == "ETH/USDT:USDT"
        and fresh_entry_assessment.action == "sell"
        and _higher_timeframe_phase(symbol) == "pullback"
        and label == "favorable"
        and str(setup_model_signal.get("quality") or "neutral") == "weak_favorable"
        and (
            float(setup_model_signal.get("positive_edge_rate") or 0.0) < 0.30
            or float(setup_model_signal.get("avg_target_edge_pct") or 0.0) <= 0.0
        )
    ):
        return "setup_model_weak_pullback_short_rebound_fail"
    return None


def _eth_structural_short_range_noise_allowed(
    symbol: SymbolSnapshot,
    *,
    fresh_entry_assessment,
    traditional_signal_context: dict[str, object] | None,
    manage_only: bool,
) -> bool:
    if manage_only or fresh_entry_assessment is None:
        return True
    if symbol.symbol != "ETH/USDT:USDT":
        return True
    if fresh_entry_assessment.action != "sell":
        return True
    if fresh_entry_assessment.setup_phase != "range_noise":
        return True
    if _higher_timeframe_bias(symbol) != "short":
        return True
    if _higher_timeframe_phase(symbol) not in {"trend", "reclaim"}:
        return True
    if not isinstance(traditional_signal_context, dict):
        return False
    if bool(traditional_signal_context.get("terminal_risk")):
        return False
    conviction_score = float(traditional_signal_context.get("conviction_score") or 0.0)
    rebound_failure_pct = float(traditional_signal_context.get("rebound_failure_pct") or 0.0)
    support_break_pct = float(traditional_signal_context.get("support_break_pct") or 0.0)
    range_expansion_ratio = float(traditional_signal_context.get("range_expansion_ratio") or 0.0)
    return (
        conviction_score >= ETH_RANGE_NOISE_SHORT_MIN_CONVICTION_SCORE
        and rebound_failure_pct >= ETH_RANGE_NOISE_SHORT_MIN_REBOUND_FAILURE_PCT
        and support_break_pct >= ETH_RANGE_NOISE_SHORT_MIN_SUPPORT_BREAK_PCT
        and range_expansion_ratio >= ETH_RANGE_NOISE_SHORT_MIN_RANGE_EXPANSION_RATIO
    )


class CandidateFilter:
    def __init__(self, settings: Settings, journal: Journal) -> None:
        self.settings = settings
        self.journal = journal
        self.setup_model_bundle = (
            load_setup_model_bundle(settings.setup_model_path)
            if settings.setup_model_enable
            else None
        )

    def apply(
        self,
        bundle: MarketSnapshotBundle,
        *,
        exclude_symbols: set[str] | None = None,
    ) -> CandidateFilterResult:
        bottom_line_rules = self.settings.bottom_line_rules
        timeframe_ms = timeframe_to_ms(self.settings.timeframe)
        excluded = exclude_symbols or set()
        recent_actions = self.journal.get_recent_signal_actions(limit=80)
        latest_action_by_symbol: dict[str, dict[str, Any]] = {}
        latest_close_by_symbol: dict[str, dict[str, Any]] = {}
        for item in recent_actions:
            symbol_name = str(item.get("symbol") or "")
            if not symbol_name or item.get("bar_timestamp_ms") is None or symbol_name in latest_action_by_symbol:
                if (
                    symbol_name
                    and item.get("bar_timestamp_ms") is not None
                    and symbol_name not in latest_close_by_symbol
                    and str(item.get("final_action") or "") == "close"
                ):
                    latest_close_by_symbol[symbol_name] = item
                continue
            latest_action_by_symbol[symbol_name] = item
            if str(item.get("final_action") or "") == "close" and symbol_name not in latest_close_by_symbol:
                latest_close_by_symbol[symbol_name] = item
        open_positions = {position.symbol: position for position in bundle.account.open_positions}
        contexts: dict[str, dict[str, Any]] = {}
        selected_symbols: list[str] = []
        open_position_slots_remaining = max(self.settings.max_open_positions - len(open_positions), 0)
        supplemental_candidates: list[tuple[str, float]] = []

        for symbol in bundle.symbols:
            if symbol.symbol in excluded:
                continue
            entry_ts = symbol.recent_candles[-1].timestamp_ms
            latest_action = latest_action_by_symbol.get(symbol.symbol)
            latest_close = latest_close_by_symbol.get(symbol.symbol)
            latest_action_ts = None if latest_action is None else int(latest_action["bar_timestamp_ms"])
            latest_final_action = "hold" if latest_action is None else str(latest_action.get("final_action") or "hold")
            bars_since_action = _bars_since(entry_ts, latest_action_ts, timeframe_ms)
            latest_close_ts = None if latest_close is None else int(latest_close["bar_timestamp_ms"])
            bars_since_close = _bars_since(entry_ts, latest_close_ts, timeframe_ms)
            trend_bias = _higher_timeframe_bias(symbol)
            higher_timeframe_phase = _higher_timeframe_phase(symbol)
            desired_direction = _candidate_target_direction(symbol)
            indicators = symbol.indicators
            volatility_pct = max(float(indicators.get("atr_14_pct") or 0.0), float(indicators.get("range_pct") or 0.0))
            volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
            fresh_entry_assessment = assess_fresh_entry(symbol) if self.settings.contract_market else None
            traditional_signal_context = (
                None
                if fresh_entry_assessment is None
                else build_traditional_signal_context(symbol, fresh_entry_assessment)
            )
            setup_model_signal = (
                None
                if fresh_entry_assessment is None
                else score_setup_edge_model_signal(
                    symbol=symbol,
                    assessment=fresh_entry_assessment,
                    traditional_signal_context=traditional_signal_context,
                    model_bundle=self.setup_model_bundle,
                )
            )
            score = (
                volatility_pct * 1000.0
                + min(volume_ratio, 3.0)
            )
            if trend_bias in {"long", "short"}:
                score += 1.0
            elif self.settings.contract_market and trend_bias == "flat":
                score -= FLAT_TREND_SCORE_PENALTY

            reasons: list[str] = []
            eligible = True
            manage_only = False

            if open_positions:
                if symbol.symbol in open_positions:
                    reasons.append("position_management")
                    manage_only = True
                    selected_symbols.append(symbol.symbol)
                else:
                    quality_ok, quality_reasons = _candidate_quality_gate(
                        volatility_pct=volatility_pct,
                        volume_ratio=volume_ratio,
                        trend_bias=trend_bias,
                    )
                    if not quality_ok:
                        eligible = False
                    reasons.extend(quality_reasons)
                    reentry_cooldown_bars = _same_symbol_reentry_cooldown_bars(
                        self.settings,
                        symbol_name=symbol.symbol,
                        latest_close=latest_close,
                        desired_direction=desired_direction,
                    )
                    if (
                        latest_close is not None
                        and bars_since_close is not None
                        and bars_since_close < reentry_cooldown_bars
                    ):
                        eligible = False
                        reasons.append(
                            f"same_symbol_reentry_cooldown_active:{bars_since_close}<{reentry_cooldown_bars}"
                        )
                    elif (
                        latest_close is not None
                        and bars_since_close is not None
                        and bars_since_close < _loss_reentry_cooldown_bars(self.settings)
                        and _is_forced_loss_close(latest_close, desired_direction)
                    ):
                        eligible = False
                        reasons.append(
                            f"loss_reentry_cooldown_active:{bars_since_close}<{_loss_reentry_cooldown_bars(self.settings)}"
                        )
                    if (
                        is_open_action(latest_final_action, self.settings.contract_market)
                        and bars_since_action is not None
                        and bars_since_action < self.settings.flip_cooldown_bars
                    ):
                        eligible = False
                        reasons.append(
                            f"recent_action_cooldown_active:{bars_since_action}<{self.settings.flip_cooldown_bars}"
                        )
                    if not self.settings.contract_market and trend_bias == "short":
                        eligible = False
                        reasons.append("higher_timeframe_short_bias")
                    if trend_bias is None and (self.settings.candidate_trend_timeframe or "").strip():
                        reasons.append("higher_timeframe_unavailable")
                    if self.settings.contract_market and trend_bias == "flat":
                        reasons.append("higher_timeframe_flat_bias_soft_penalty")
                    if fresh_entry_assessment is not None:
                        if fresh_entry_assessment.terminal_extension:
                            reasons.extend(fresh_entry_assessment.candidate_reasons)
                            score -= FRESH_ENTRY_EXHAUSTION_SCORE_PENALTY
                        elif fresh_entry_assessment.continuation_watch:
                            reasons.extend(fresh_entry_assessment.candidate_reasons)
                            score += PRE_BREAK_CONTINUATION_SCORE_BONUS
                        else:
                            if fresh_entry_assessment.candidate_reasons:
                                reasons.extend(fresh_entry_assessment.candidate_reasons)
                            if _should_penalize_soft_low_volatility_fresh_entry(
                                reasons=reasons,
                                fresh_entry_assessment=fresh_entry_assessment,
                                manage_only=manage_only,
                            ):
                                # Low-volatility fresh entries can still be reviewed,
                                # but they should rank below cleaner continuation setups.
                                score -= WEAK_LOW_VOLATILITY_FRESH_ENTRY_SCORE_PENALTY
                        score += _phase_match_score(
                            fresh_entry_assessment=fresh_entry_assessment,
                            higher_timeframe_phase=higher_timeframe_phase,
                            manage_only=manage_only,
                        )
                        score += _traditional_signal_score_delta(
                            traditional_signal_context,
                            manage_only=manage_only,
                        )
                        score += _hourly_model_score_delta(
                            symbol,
                            manage_only=manage_only,
                        )
                        score += _setup_model_score_delta(
                            setup_model_signal,
                            manage_only=manage_only,
                        )
                        setup_model_block_reason = _setup_model_entry_block_reason(
                            symbol,
                            setup_model_signal,
                            fresh_entry_assessment=fresh_entry_assessment,
                            manage_only=manage_only,
                        )
                        if setup_model_block_reason is not None:
                            eligible = False
                            reasons.append(setup_model_block_reason)
                        if not _eth_structural_short_range_noise_allowed(
                            symbol,
                            fresh_entry_assessment=fresh_entry_assessment,
                            traditional_signal_context=traditional_signal_context,
                            manage_only=manage_only,
                        ):
                            eligible = False
                            reasons.append("eth_short_range_noise_requires_breakdown_structure")
                        short_precheck_reasons = _short_candidate_precheck(symbol)
                        if short_precheck_reasons:
                            eligible = False
                            reasons.extend(short_precheck_reasons)
                    if open_position_slots_remaining <= 0:
                        eligible = False
                        reasons.append("max_open_positions_reached")
                    elif eligible or (bottom_line_rules and _bottom_line_candidate_allowed(reasons)):
                        supplemental_candidates.append((symbol.symbol, score))
            else:
                quality_ok, quality_reasons = _candidate_quality_gate(
                    volatility_pct=volatility_pct,
                    volume_ratio=volume_ratio,
                    trend_bias=trend_bias,
                )
                if not quality_ok:
                    eligible = False
                reasons.extend(quality_reasons)
                reentry_cooldown_bars = _same_symbol_reentry_cooldown_bars(
                    self.settings,
                    symbol_name=symbol.symbol,
                    latest_close=latest_close,
                    desired_direction=desired_direction,
                )
                if (
                    latest_close is not None
                    and bars_since_close is not None
                    and bars_since_close < reentry_cooldown_bars
                ):
                    eligible = False
                    reasons.append(
                        f"same_symbol_reentry_cooldown_active:{bars_since_close}<{reentry_cooldown_bars}"
                    )
                elif (
                    latest_close is not None
                    and bars_since_close is not None
                    and bars_since_close < _loss_reentry_cooldown_bars(self.settings)
                    and _is_forced_loss_close(latest_close, desired_direction)
                ):
                    eligible = False
                    reasons.append(
                        f"loss_reentry_cooldown_active:{bars_since_close}<{_loss_reentry_cooldown_bars(self.settings)}"
                    )
                if (
                    is_open_action(latest_final_action, self.settings.contract_market)
                    and bars_since_action is not None
                    and bars_since_action < self.settings.flip_cooldown_bars
                ):
                    eligible = False
                    reasons.append(
                        f"recent_action_cooldown_active:{bars_since_action}<{self.settings.flip_cooldown_bars}"
                    )
                if not self.settings.contract_market and trend_bias == "short":
                    eligible = False
                    reasons.append("higher_timeframe_short_bias")
                if trend_bias is None and (self.settings.candidate_trend_timeframe or "").strip():
                    reasons.append("higher_timeframe_unavailable")
                if self.settings.contract_market and trend_bias == "flat":
                    reasons.append("higher_timeframe_flat_bias_soft_penalty")
                if fresh_entry_assessment is not None:
                    if fresh_entry_assessment.terminal_extension:
                        reasons.extend(fresh_entry_assessment.candidate_reasons)
                        score -= FRESH_ENTRY_EXHAUSTION_SCORE_PENALTY
                    elif fresh_entry_assessment.continuation_watch:
                        reasons.extend(fresh_entry_assessment.candidate_reasons)
                        score += PRE_BREAK_CONTINUATION_SCORE_BONUS
                    else:
                        if fresh_entry_assessment.candidate_reasons:
                            reasons.extend(fresh_entry_assessment.candidate_reasons)
                        if _should_penalize_soft_low_volatility_fresh_entry(
                            reasons=reasons,
                            fresh_entry_assessment=fresh_entry_assessment,
                            manage_only=manage_only,
                        ):
                            # Keep weak low-volatility fresh entries available, but
                            # let cleaner setups win the candidate slots first.
                            score -= WEAK_LOW_VOLATILITY_FRESH_ENTRY_SCORE_PENALTY
                    score += _phase_match_score(
                        fresh_entry_assessment=fresh_entry_assessment,
                        higher_timeframe_phase=higher_timeframe_phase,
                        manage_only=manage_only,
                    )
                    score += _traditional_signal_score_delta(
                        traditional_signal_context,
                        manage_only=manage_only,
                    )
                    score += _hourly_model_score_delta(
                        symbol,
                        manage_only=manage_only,
                    )
                    score += _setup_model_score_delta(
                        setup_model_signal,
                        manage_only=manage_only,
                    )
                    setup_model_block_reason = _setup_model_entry_block_reason(
                        symbol,
                        setup_model_signal,
                        fresh_entry_assessment=fresh_entry_assessment,
                        manage_only=manage_only,
                    )
                    if setup_model_block_reason is not None:
                        eligible = False
                        reasons.append(setup_model_block_reason)
                    if not _eth_structural_short_range_noise_allowed(
                        symbol,
                        fresh_entry_assessment=fresh_entry_assessment,
                        traditional_signal_context=traditional_signal_context,
                        manage_only=manage_only,
                    ):
                        eligible = False
                        reasons.append("eth_short_range_noise_requires_breakdown_structure")
                    short_precheck_reasons = _short_candidate_precheck(symbol)
                    if short_precheck_reasons:
                        eligible = False
                        reasons.extend(short_precheck_reasons)
                if eligible or (bottom_line_rules and _bottom_line_candidate_allowed(reasons)):
                    selected_symbols.append(symbol.symbol)

            contexts[symbol.symbol] = {
                "eligible": eligible,
                "manage_only": manage_only,
                "score": round(score, 6),
                "higher_timeframe_bias": trend_bias,
                "higher_timeframe_phase": higher_timeframe_phase,
                "bars_since_last_action": bars_since_action,
                "setup_phase": None if fresh_entry_assessment is None else fresh_entry_assessment.setup_phase,
                "setup_confirmed": None if fresh_entry_assessment is None else fresh_entry_assessment.setup_confirmed,
                "entry_thesis_candidate": None if fresh_entry_assessment is None else build_entry_thesis_candidate(symbol, fresh_entry_assessment),
                "traditional_signal_context": traditional_signal_context,
                "hourly_model_signal": (
                    None
                    if not isinstance((symbol.higher_timeframe or {}).get("model_signal"), dict)
                    else (symbol.higher_timeframe or {}).get("model_signal")
                ),
                "setup_model_signal": setup_model_signal,
                "phase_match_score": round(
                    _phase_match_score(
                        fresh_entry_assessment=fresh_entry_assessment,
                        higher_timeframe_phase=higher_timeframe_phase,
                        manage_only=manage_only,
                    ),
                    6,
                ),
                "reasons": reasons or ["candidate_ok"],
            }

        if open_positions:
            supplemental_selected = sorted(
                {symbol: score for symbol, score in supplemental_candidates}.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:open_position_slots_remaining]
            selected_symbols.extend(symbol for symbol, _score in supplemental_selected)
        else:
            selected_limit = (
                BOTTOM_LINE_MAX_CANDIDATE_SYMBOLS
                if bottom_line_rules
                else MAX_CANDIDATE_SYMBOLS
            )
            selected_pool = (
                set(selected_symbols)
                if bottom_line_rules
                else {symbol for symbol in selected_symbols if contexts.get(symbol, {}).get("eligible")}
            )
            selected_symbols = sorted(
                selected_pool,
                key=lambda symbol: contexts[symbol]["score"],
                reverse=True,
            )[:selected_limit]

        summary = {
            "status": "selected" if selected_symbols else "filtered_hold",
            "selected_symbols": selected_symbols,
            "symbols": [
                contexts[symbol.symbol] | {"symbol": symbol.symbol}
                for symbol in bundle.symbols
                if symbol.symbol in contexts
            ],
        }
        if not selected_symbols:
            return CandidateFilterResult(status="filtered_hold", filtered_bundle=None, summary=summary)

        filtered_symbols_by_symbol = {
            symbol.symbol: replace(symbol, candidate_context=contexts[symbol.symbol])
            for symbol in bundle.symbols
            if symbol.symbol in selected_symbols
        }
        filtered_symbols = [
            filtered_symbols_by_symbol[symbol]
            for symbol in selected_symbols
            if symbol in filtered_symbols_by_symbol
        ]
        filtered_bundle = replace(bundle, symbols=filtered_symbols)
        return CandidateFilterResult(status="selected", filtered_bundle=filtered_bundle, summary=summary)
