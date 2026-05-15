from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .entry_quality import assess_fresh_entry
from .journal import Journal
from .models import MarketSnapshotBundle, SymbolSnapshot
from .settings import Settings
from .trade_policy import is_open_action
from .trade_policy import timeframe_to_ms


MIN_CANDIDATE_VOLATILITY_PCT = 0.0020
MIN_CANDIDATE_VOLUME_RATIO = 0.60
HARD_MIN_CANDIDATE_VOLATILITY_PCT = 0.0015
HARD_MIN_CANDIDATE_VOLUME_RATIO = 0.45
MAX_CANDIDATE_SYMBOLS = 2
FLAT_TREND_SCORE_PENALTY = 0.75
FRESH_ENTRY_EXHAUSTION_SCORE_PENALTY = 1.25
PRE_BREAK_CONTINUATION_SCORE_BONUS = 0.75
SHORT_REBOUND_1BAR_PCT = 0.0
SHORT_COUNTERTREND_24BAR_PCT = 0.0


@dataclass
class CandidateFilterResult:
    status: str
    filtered_bundle: MarketSnapshotBundle | None
    summary: dict[str, Any]


def _higher_timeframe_bias(symbol: SymbolSnapshot) -> str | None:
    context = symbol.higher_timeframe or {}
    bias = context.get("trend_bias")
    return str(bias) if bias is not None else None


def _bars_since(current_ts: int, previous_ts: int | None, timeframe_ms: int) -> int | None:
    if previous_ts is None or current_ts <= previous_ts:
        return None
    return max(0, (current_ts - previous_ts) // timeframe_ms)


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


class CandidateFilter:
    def __init__(self, settings: Settings, journal: Journal) -> None:
        self.settings = settings
        self.journal = journal

    def apply(self, bundle: MarketSnapshotBundle) -> CandidateFilterResult:
        timeframe_ms = timeframe_to_ms(self.settings.timeframe)
        recent_actions = self.journal.get_recent_signal_actions(limit=80)
        latest_action_by_symbol = {
            item["symbol"]: item
            for item in recent_actions
            if item.get("symbol") and item.get("bar_timestamp_ms") is not None
        }
        open_positions = {position.symbol: position for position in bundle.account.open_positions}
        contexts: dict[str, dict[str, Any]] = {}
        selected_symbols: list[str] = []
        open_position_slots_remaining = max(self.settings.max_open_positions - len(open_positions), 0)
        supplemental_candidates: list[tuple[str, float]] = []

        for symbol in bundle.symbols:
            entry_ts = symbol.recent_candles[-1].timestamp_ms
            latest_action = latest_action_by_symbol.get(symbol.symbol)
            latest_action_ts = None if latest_action is None else int(latest_action["bar_timestamp_ms"])
            latest_final_action = "hold" if latest_action is None else str(latest_action.get("final_action") or "hold")
            bars_since_action = _bars_since(entry_ts, latest_action_ts, timeframe_ms)
            trend_bias = _higher_timeframe_bias(symbol)
            indicators = symbol.indicators
            volatility_pct = max(float(indicators.get("atr_14_pct") or 0.0), float(indicators.get("range_pct") or 0.0))
            volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
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
                    if (
                        latest_final_action == "close"
                        and bars_since_action is not None
                        and bars_since_action < self.settings.same_symbol_reentry_cooldown_bars
                    ):
                        eligible = False
                        reasons.append(
                            f"same_symbol_reentry_cooldown_active:{bars_since_action}<{self.settings.same_symbol_reentry_cooldown_bars}"
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
                    if self.settings.contract_market:
                        fresh_entry_assessment = assess_fresh_entry(symbol)
                        if fresh_entry_assessment.terminal_extension:
                            reasons.extend(fresh_entry_assessment.candidate_reasons)
                            score -= FRESH_ENTRY_EXHAUSTION_SCORE_PENALTY
                        elif fresh_entry_assessment.continuation_watch:
                            reasons.extend(fresh_entry_assessment.candidate_reasons)
                            score += PRE_BREAK_CONTINUATION_SCORE_BONUS
                        short_precheck_reasons = _short_candidate_precheck(symbol)
                        if short_precheck_reasons:
                            eligible = False
                            reasons.extend(short_precheck_reasons)
                    if open_position_slots_remaining <= 0:
                        eligible = False
                        reasons.append("max_open_positions_reached")
                    elif eligible:
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
                if (
                    latest_final_action == "close"
                    and bars_since_action is not None
                    and bars_since_action < self.settings.same_symbol_reentry_cooldown_bars
                ):
                    eligible = False
                    reasons.append(
                        f"same_symbol_reentry_cooldown_active:{bars_since_action}<{self.settings.same_symbol_reentry_cooldown_bars}"
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
                if self.settings.contract_market:
                    fresh_entry_assessment = assess_fresh_entry(symbol)
                    if fresh_entry_assessment.terminal_extension:
                        reasons.extend(fresh_entry_assessment.candidate_reasons)
                        score -= FRESH_ENTRY_EXHAUSTION_SCORE_PENALTY
                    elif fresh_entry_assessment.continuation_watch:
                        reasons.extend(fresh_entry_assessment.candidate_reasons)
                        score += PRE_BREAK_CONTINUATION_SCORE_BONUS
                    short_precheck_reasons = _short_candidate_precheck(symbol)
                    if short_precheck_reasons:
                        eligible = False
                        reasons.extend(short_precheck_reasons)
                if eligible:
                    selected_symbols.append(symbol.symbol)

            contexts[symbol.symbol] = {
                "eligible": eligible,
                "manage_only": manage_only,
                "score": round(score, 6),
                "higher_timeframe_bias": trend_bias,
                "bars_since_last_action": bars_since_action,
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
            selected_symbols = sorted(
                {symbol for symbol in selected_symbols if contexts.get(symbol, {}).get("eligible")},
                key=lambda symbol: contexts[symbol]["score"],
                reverse=True,
            )[:MAX_CANDIDATE_SYMBOLS]

        summary = {
            "status": "selected" if selected_symbols else "filtered_hold",
            "selected_symbols": selected_symbols,
            "symbols": [contexts[symbol.symbol] | {"symbol": symbol.symbol} for symbol in bundle.symbols],
        }
        if not selected_symbols:
            return CandidateFilterResult(status="filtered_hold", filtered_bundle=None, summary=summary)

        filtered_symbols = [
            replace(symbol, candidate_context=contexts[symbol.symbol])
            for symbol in bundle.symbols
            if symbol.symbol in selected_symbols
        ]
        filtered_bundle = replace(bundle, symbols=filtered_symbols)
        return CandidateFilterResult(status="selected", filtered_bundle=filtered_bundle, summary=summary)
