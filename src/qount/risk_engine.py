from __future__ import annotations

from .entry_quality import assess_fresh_entry
from .entry_quality import build_entry_thesis_candidate
from .entry_quality import build_traditional_signal_context
from .exchange_utils import minimum_executable_notional
from .journal import Journal
from .models import AIDecision, MarketSnapshotBundle, RiskVerdict, ValidatedDecision, utc_now
from .settings import Settings
from .trade_policy import action_direction
from .trade_policy import estimated_action_cost_pct
from .trade_policy import is_open_action
from .trade_policy import timeframe_to_ms

MIN_OPEN_SIGNAL_TREND_RETURN_PCT = 0.0005
MIN_OPEN_SIGNAL_VOLUME_RATIO = 0.55
COUNTERTREND_BREAKOUT_SHORT_MIN_VOLUME_RATIO = 1.25
COUNTERTREND_BREAKOUT_SHORT_MIN_VOLATILITY_PCT = 0.002
COUNTERTREND_BREAKOUT_SHORT_MAX_24BAR_RETURN_PCT = 0.006
COUNTERTREND_BREAKOUT_SHORT_MAX_SLOW_SMA_RATIO = 0.0015
COUNTERTREND_BREAKOUT_SHORT_EDGE_BONUS_CAP = 0.00125
PRE_BREAK_CONTINUATION_EDGE_BONUS_PCT = 0.0010
PRE_BREAK_CONTINUATION_MIN_HIGHER_RETURN_12BAR_PCT = 0.0080
PRE_BREAK_CONTINUATION_MIN_HIGHER_SLOW_SMA_RATIO = 0.0050
PRE_BREAK_CONTINUATION_MIN_VOLUME_RATIO = 0.70
PRE_BREAK_CONTINUATION_SHORT_STRONG_MIN_VOLUME_RATIO = 0.85
PRE_BREAK_CONTINUATION_SHORT_MAX_LOCAL_RSI = 46.0
SHORT_EXHAUSTION_FLUSH_MIN_DIRECTIONAL_24BAR_PCT = 0.0080
SHORT_EXHAUSTION_FLUSH_MIN_VOLUME_RATIO = 4.0
SHORT_EXHAUSTION_FLUSH_MAX_LOCAL_RSI = 18.0
SHORT_EXHAUSTION_FLUSH_MIN_HIGHER_RETURN_12BAR_PCT = -0.0030
EDGE_ATR_WEIGHT = 0.65
EDGE_RANGE_WEIGHT = 0.35
EDGE_DIRECTIONAL_WEIGHT = 0.5
EDGE_TREND_RETURN_SCALE = 0.25
PLAIN_OPEN_VOLATILITY_CAP_MULTIPLIER = 1.40
FLAT_BIAS_SHORT_VOLATILITY_CAP_MULTIPLIER = 3.00
OPEN_SIGNAL_WEAK_TREND_EDGE_PENALTY_PCT = 0.00035
OPEN_SIGNAL_FAST_SMA_EDGE_PENALTY_PCT = 0.00030
WEAK_PLAIN_OPEN_DIRECTIONAL_SHARE_THRESHOLD = 0.25
WEAK_FLAT_BIAS_SHORT_DIRECTIONAL_SHARE_THRESHOLD = 0.25
FLAT_BIAS_FRESH_ENTRY_EDGE_PENALTY_PCT = 0.0010
HIGHER_TIMEFRAME_LONG_RECLAIM_EDGE_BONUS_PCT = 0.0004
HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_HIGHER_RETURN_12BAR_PCT = 0.020
HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_HIGHER_SLOW_SMA_RATIO = 0.015
HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_HIGHER_RSI = 60.0
HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_1BAR_PCT = 0.0003
HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_24BAR_PCT = -0.0045
HIGHER_TIMEFRAME_LONG_RECLAIM_MAX_24BAR_PCT = 0.0015
HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_VOLUME_RATIO = 0.90
HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_VOLATILITY_PCT = 0.0022
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_EDGE_BONUS_PCT = 0.00030
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_HIGHER_RETURN_12BAR_PCT = 0.012
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_HIGHER_SLOW_SMA_RATIO = 0.013
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_HIGHER_RSI = 60.0
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_BONUS_MIN_1BAR_PCT = -0.0005
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_24BAR_PCT = -0.0065
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MAX_24BAR_PCT = -0.0010
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_VOLUME_RATIO = 0.50
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_VOLATILITY_PCT = 0.0015
HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MAX_LOCAL_RSI = 56.0
HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_HIGHER_RETURN_12BAR_PCT = 0.030
HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_HIGHER_SLOW_SMA_RATIO = 0.015
HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_HIGHER_RSI = 60.0
HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_1BAR_PCT = 0.0010
HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_24BAR_PCT = -0.0100
HIGHER_TIMEFRAME_LONG_REVERSAL_MAX_24BAR_PCT = -0.0045
HIGHER_TIMEFRAME_LONG_REVERSAL_MAX_LOCAL_RSI = 35.0
HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_VOLUME_RATIO = 1.0
HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_HIGHER_RETURN_12BAR_PCT = 0.030
HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_HIGHER_SLOW_SMA_RATIO = 0.020
HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_24BAR_PCT = 0.0035
HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_VOLUME_RATIO = 1.50
HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_VOLATILITY_PCT = 0.0035
HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MAX_NEGATIVE_1BAR_PCT = 0.0025
HIGHER_TIMEFRAME_SHORT_RECLAIM_EDGE_BONUS_PCT = 0.00035
HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_HIGHER_RETURN_12BAR_PCT = -0.0035
HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_HIGHER_SLOW_SMA_RATIO = -0.0010
HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_HIGHER_RSI = 48.0
HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_24BAR_PCT = 0.0020
HIGHER_TIMEFRAME_SHORT_RECLAIM_MIN_24BAR_PCT = -0.0005
HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_1BAR_PCT = 0.0
HIGHER_TIMEFRAME_SHORT_RECLAIM_MIN_VOLUME_RATIO = 1.0
HIGHER_TIMEFRAME_SHORT_RECLAIM_MIN_VOLATILITY_PCT = 0.0025
HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_LOCAL_RSI = 45.0
ALIGNED_SHORT_CONTINUATION_EDGE_BONUS_PCT = 0.00030
ALIGNED_SHORT_CONTINUATION_MIN_HIGHER_RETURN_12BAR_PCT = -0.0090
ALIGNED_SHORT_CONTINUATION_MAX_HIGHER_SLOW_SMA_RATIO = -0.0075
ALIGNED_SHORT_CONTINUATION_MAX_HIGHER_RSI = 40.0
ALIGNED_SHORT_CONTINUATION_MIN_1BAR_PCT = 0.0004
ALIGNED_SHORT_CONTINUATION_MAX_24BAR_PCT = 0.0010
ALIGNED_SHORT_CONTINUATION_MIN_VOLUME_RATIO = 1.50
ALIGNED_SHORT_CONTINUATION_MIN_VOLATILITY_PCT = 0.0016
ALIGNED_SHORT_CONTINUATION_MAX_LOCAL_RSI = 38.0
WEAK_PLAIN_OPEN_SHORT_EDGE_PENALTY_PCT = 0.00020
WEAK_FLAT_BIAS_SHORT_EDGE_PENALTY_PCT = 0.00025
WEAK_PRE_BREAK_CONTINUATION_SHORT_EDGE_PENALTY_PCT = 0.00020
WEAK_SAME_DIRECTION_SHORT_EDGE_BUFFER_PCT = 0.00050
FLAT_BIAS_SHORT_FLUSH_MIN_DIRECTIONAL_24BAR_PCT = 0.0100
FLAT_BIAS_SHORT_FLUSH_MIN_DIRECTIONAL_1BAR_PCT = 0.0020
FLAT_BIAS_SHORT_FLUSH_MIN_VOLUME_RATIO = 3.0
FLAT_BIAS_SHORT_FLUSH_MAX_LOCAL_RSI = 18.0
MANAGEMENT_ADVERSE_MIN_1BAR_PCT = 0.0015
MANAGEMENT_ADVERSE_MIN_24BAR_PCT = 0.0025
MANAGEMENT_SUPPORT_MIN_24BAR_PCT = 0.001
MANAGEMENT_ADVERSE_LOSS_CUT_MIN_POSITION_RETURN_PCT = 0.0025
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MIN_POSITION_RETURN_PCT = 0.005
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MIN_24BAR_RETURN_PCT = 0.005
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MAX_LOCAL_RSI = 55.0
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MAX_1BAR_RETURN_PCT = 0.003
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MIN_HIGHER_RSI = 60.0
ETH_RECLAIM_SHORT_REENTRY_COOLDOWN_BARS = 6
ETH_SHORT_CLOSE_REJECT_MIN_POSITION_RETURN_PCT = 0.0025
ETH_SHORT_CLOSE_REJECT_MIN_VOLUME_RATIO = 1.0
ETH_SHORT_AI_CLOSE_REJECT_MAX_POSITION_LOSS_PCT = 0.003
ETH_SHORT_AI_CLOSE_STRONG_REBOUND_MIN_1BAR_PCT = 0.003
ETH_SHORT_AI_CLOSE_STRONG_REBOUND_MIN_VOLUME_RATIO = 1.5
ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MIN_1BAR_PCT = 0.006
ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MIN_VOLUME_RATIO = 3.0
ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MIN_RANGE_PCT = 0.006
ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MAX_LOCAL_RSI = 35.0
ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MAX_EXTREME_DISTANCE_PCT = 0.0025
ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MIN_DIRECTIONAL_24BAR_PCT = 0.0040
ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MAX_REBOUND_1BAR_PCT = 0.0020
ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MAX_FAST_SMA_RATIO = 0.0010
ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MAX_LOCAL_RSI = 45.0
ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MAX_EXTREME_DISTANCE_PCT = 0.0060
ETH_RECLAIM_SHORT_HOLD_MAX_FAST_SMA_RATIO = 0.0005
ETH_RECLAIM_SHORT_HOLD_MAX_RETURN_1BAR_PCT = 0.0030
ETH_RECLAIM_SHORT_HOLD_MAX_LOCAL_RSI = 45.0
ETH_RECLAIM_SHORT_HOLD_MIN_VOLUME_RATIO = 1.0
ETH_RECLAIM_SHORT_HOLD_MIN_CONVICTION_SCORE = 0.58
ETH_RECLAIM_SHORT_HOLD_MIN_REBOUND_FAILURE_PCT = 0.0025
ETH_RECLAIM_SHORT_HOLD_MIN_SUPPORT_BREAK_PCT = 0.0008
ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_1BAR_PCT = 0.0015
ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_VOLUME_RATIO = 1.4
ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_RSI = 52.0
ETH_CONTINUATION_SHORT_WEAK_REBOUND_MAX_24BAR_RETURN_PCT = 0.0025
ETH_CONTINUATION_SHORT_WEAK_REBOUND_MAX_FAST_SMA_RATIO = 0.0010
ETH_CONTINUATION_SHORT_WEAK_REBOUND_MAX_LOCAL_RSI = 50.0
CORRELATED_DIRECTIONAL_GROUPS: dict[str, frozenset[str]] = {
    "crypto_beta": frozenset({"BTC", "ETH", "SOL", "XRP"}),
}
ALT_SHORT_TIGHTEN_BASES = frozenset({"SOL", "XRP"})


def build_day_start_equity_key(mode: str, exchange_id: str, market_type: str, quote_currency: str, date_key: str) -> str:
    return f"day_start_equity:{mode}:{exchange_id}:{market_type}:{quote_currency}:{date_key}"


class RiskEngine:
    def __init__(self, settings: Settings, journal: Journal) -> None:
        self.settings = settings
        self.journal = journal

    def _symbol_snapshot(self, bundle: MarketSnapshotBundle, symbol: str):
        return next((item for item in bundle.symbols if item.symbol == symbol), None)

    def _bars_since(self, current_ts: int, previous_ts: int | None) -> int | None:
        if previous_ts is None or current_ts <= previous_ts:
            return None
        return max(0, (current_ts - previous_ts) // timeframe_to_ms(self.settings.timeframe))

    def _same_symbol_reentry_cooldown_bars(
        self,
        *,
        symbol: str,
        last_close: dict | None,
        desired_direction: int | None,
    ) -> int:
        base_cooldown = self.settings.same_symbol_reentry_cooldown_bars
        if (
            last_close is None
            or desired_direction != -1
            or symbol != "ETH/USDT:USDT"
            or str(last_close.get("final_action") or "") != "close"
        ):
            return base_cooldown
        if str(last_close.get("entry_setup_phase") or "") != "short_rebound_fail_confirmed":
            return base_cooldown
        if str(last_close.get("entry_higher_timeframe_phase") or "") != "reclaim":
            return base_cooldown
        return max(base_cooldown, ETH_RECLAIM_SHORT_REENTRY_COOLDOWN_BARS)

    def _open_entry_cooldown_reasons(
        self,
        *,
        current_entry_ts: int | None,
        last_close: dict | None,
        last_action: dict | None,
        desired_direction: int | None,
    ) -> list[str]:
        if current_entry_ts is None:
            return []
        reasons: list[str] = []
        if last_close is not None:
            bars_since_close = self._bars_since(current_entry_ts, last_close.get("bar_timestamp_ms"))
            reentry_cooldown_bars = self._same_symbol_reentry_cooldown_bars(
                symbol=str(last_close.get("symbol") or ""),
                last_close=last_close,
                desired_direction=desired_direction,
            )
            if (
                bars_since_close is not None
                and bars_since_close < reentry_cooldown_bars
            ):
                reasons.append(
                    f"same_symbol_reentry_cooldown_active:{bars_since_close}<{reentry_cooldown_bars}"
                )
            elif (
                bars_since_close is not None
                and bars_since_close < self._loss_reentry_cooldown_bars()
                and self._is_forced_loss_close(last_close, desired_direction)
            ):
                reasons.append(
                    f"loss_reentry_cooldown_active:{bars_since_close}<{self._loss_reentry_cooldown_bars()}"
                )

        if last_action is None:
            return reasons

        last_direction = action_direction(
            str(last_action.get("final_action") or "hold"),
            contract_market=self.settings.contract_market,
            position_side=last_action.get("position_side_before_action"),
        )
        bars_since_action = self._bars_since(current_entry_ts, last_action.get("bar_timestamp_ms"))
        if (
            last_direction is not None
            and desired_direction is not None
            and last_direction != desired_direction
            and bars_since_action is not None
            and bars_since_action < self.settings.flip_cooldown_bars
        ):
            reasons.append(f"flip_cooldown_active:{bars_since_action}<{self.settings.flip_cooldown_bars}")
        return reasons

    def _recent_symbol_history(self, symbol: str) -> list[dict]:
        # Positions can stay open for many hours on the 5m workflow, so
        # management logic needs enough history to recover the original
        # open-plan take-profit / stop-loss thresholds.
        return self.journal.get_recent_signal_actions(limit=400, symbol=symbol)

    def _last_matching_action(self, history: list[dict], predicate) -> dict | None:
        return next((item for item in history if predicate(item)), None)

    def _trailing_profit_peak_key(self, symbol: str, open_run_id: int) -> str:
        return f"trailing_profit_peak:{self.settings.mode}:{self.settings.exchange_id}:{self.settings.market_type}:{symbol}:{open_run_id}"

    def _partial_take_profit_done_key(self, symbol: str, open_run_id: int) -> str:
        return f"partial_tp_done:{self.settings.mode}:{self.settings.exchange_id}:{self.settings.market_type}:{symbol}:{open_run_id}"

    def _breakeven_stop_armed_key(self, symbol: str, open_run_id: int) -> str:
        return f"breakeven_stop_armed:{self.settings.mode}:{self.settings.exchange_id}:{self.settings.market_type}:{symbol}:{open_run_id}"

    def _partial_take_profit_count(self, symbol: str, open_run_id: int) -> int:
        state = self.journal.get_runtime_state(self._partial_take_profit_done_key(symbol, open_run_id), 0)
        if isinstance(state, bool):
            return 1 if state else 0
        if isinstance(state, dict):
            return int(state.get("count") or 0)
        return int(state or 0)

    def _next_partial_take_profit_trigger_pct(self, partial_take_profit_count: int) -> float:
        base_trigger_pct = max(float(self.settings.partial_take_profit_trigger_pct), 0.0)
        step_trigger_pct = max(float(self.settings.partial_take_profit_step_pct), 0.0)
        return base_trigger_pct + (partial_take_profit_count * step_trigger_pct)

    def _remaining_protective_prices(
        self,
        *,
        position_side: str | None,
        entry_price: float,
        take_profit_pct: float,
        take_profit_enabled: bool = True,
    ) -> tuple[float | None, float | None]:
        if position_side not in {"long", "short"} or entry_price <= 0.0:
            return None, None
        stop_buffer_pct = max(float(self.settings.breakeven_stop_buffer_pct), 0.0)
        if position_side == "long":
            take_profit_price = entry_price * (1.0 + take_profit_pct) if take_profit_enabled and take_profit_pct > 0.0 else None
            stop_price = entry_price * (1.0 + stop_buffer_pct)
        else:
            take_profit_price = entry_price * (1.0 - take_profit_pct) if take_profit_enabled and take_profit_pct > 0.0 else None
            stop_price = entry_price * (1.0 - stop_buffer_pct)
        return take_profit_price, stop_price

    def _planned_take_profit_price(
        self,
        *,
        position_side: str | None,
        entry_price: float,
        take_profit_pct: float,
    ) -> float | None:
        if position_side not in {"long", "short"} or entry_price <= 0.0 or take_profit_pct <= 0.0:
            return None
        if position_side == "long":
            return entry_price * (1.0 + take_profit_pct)
        return entry_price * (1.0 - take_profit_pct)

    def _trailing_stop_price(
        self,
        *,
        position_side: str | None,
        entry_price: float,
        peak_return_pct: float,
    ) -> float | None:
        if position_side not in {"long", "short"} or entry_price <= 0.0:
            return None
        if peak_return_pct < self.settings.trailing_profit_arm_pct:
            return None
        protected_return_pct = peak_return_pct - self.settings.trailing_profit_retrace_pct
        if protected_return_pct <= 0.0:
            return None
        if position_side == "long":
            return entry_price * (1.0 + protected_return_pct)
        return entry_price * (1.0 - protected_return_pct)

    def _managed_protective_refresh_plan(
        self,
        *,
        symbol: str,
        current_position,
        last_open: dict | None,
        current_position_return_pct: float | None,
    ) -> tuple[int | None, float | None, float | None, str | None]:
        if not self.settings.dynamic_protective_refresh_enable:
            return None, None, None, None
        if current_position is None or last_open is None or current_position_return_pct is None:
            return None, None, None, None
        open_run_id = int(last_open.get("run_id") or 0)
        if open_run_id <= 0:
            return None, None, None, None

        entry_price = float(current_position.average_entry_price or 0.0)
        if entry_price <= 0.0:
            return None, None, None, None

        position_side = current_position.side
        partial_take_profit_count = self._partial_take_profit_count(symbol, open_run_id)
        take_profit_pct = max(float(last_open.get("take_profit_pct") or 0.0), 0.0)
        take_profit_price = None
        if partial_take_profit_count == 0:
            take_profit_price = self._planned_take_profit_price(
                position_side=position_side,
                entry_price=entry_price,
                take_profit_pct=take_profit_pct,
            )

        desired_stop_price: float | None = None
        refresh_reason: str | None = None
        breakeven_state = self.journal.get_runtime_state(
            self._breakeven_stop_armed_key(symbol, open_run_id),
            {},
        )
        breakeven_armed = partial_take_profit_count > 0 or bool((breakeven_state or {}).get("armed"))
        if breakeven_armed:
            _, breakeven_stop_price = self._remaining_protective_prices(
                position_side=position_side,
                entry_price=entry_price,
                take_profit_pct=take_profit_pct,
            )
            desired_stop_price = breakeven_stop_price
            refresh_reason = "breakeven_stop_refresh"

        peak_key = self._trailing_profit_peak_key(symbol, open_run_id)
        peak_return_pct = float(
            self.journal.get_runtime_state(peak_key, current_position_return_pct) or current_position_return_pct
        )
        trailing_stop_price = self._trailing_stop_price(
            position_side=position_side,
            entry_price=entry_price,
            peak_return_pct=peak_return_pct,
        )
        if trailing_stop_price is not None:
            if position_side == "long":
                if desired_stop_price is None or trailing_stop_price > desired_stop_price:
                    desired_stop_price = trailing_stop_price
                    refresh_reason = "trailing_stop_refresh"
            else:
                if desired_stop_price is None or trailing_stop_price < desired_stop_price:
                    desired_stop_price = trailing_stop_price
                    refresh_reason = "trailing_stop_refresh"

        if desired_stop_price is None:
            return None, None, None, None

        if take_profit_price is not None:
            if position_side == "long" and take_profit_price <= desired_stop_price:
                take_profit_price = None
            if position_side == "short" and take_profit_price >= desired_stop_price:
                take_profit_price = None
        return open_run_id, take_profit_price, desired_stop_price, refresh_reason

    def _should_partial_take_profit(
        self,
        *,
        symbol: str,
        last_open: dict | None,
        current_position_return_pct: float | None,
        management_signal: str | None,
    ) -> tuple[bool, int | None, float | None, int]:
        if not self.settings.contract_market or not self.settings.partial_take_profit_enable:
            return False, None, None, 0
        if self.settings.partial_take_profit_max_times <= 0:
            return False, None, None, 0
        if last_open is None or current_position_return_pct is None:
            return False, None, None, 0
        open_run_id = int(last_open.get("run_id") or 0)
        if open_run_id <= 0:
            return False, None, None, 0
        partial_take_profit_count = self._partial_take_profit_count(symbol, open_run_id)
        next_trigger_pct = self._next_partial_take_profit_trigger_pct(partial_take_profit_count)
        if current_position_return_pct < next_trigger_pct:
            return False, open_run_id, next_trigger_pct, partial_take_profit_count
        if management_signal == "adverse":
            return False, open_run_id, next_trigger_pct, partial_take_profit_count
        if partial_take_profit_count >= self.settings.partial_take_profit_max_times:
            return False, open_run_id, next_trigger_pct, partial_take_profit_count
        return True, open_run_id, next_trigger_pct, partial_take_profit_count

    def _countertrend_breakout_short_bonus_pct(self, action: str, symbol_snapshot) -> float:
        if action != "sell" or symbol_snapshot is None:
            return 0.0
        if (symbol_snapshot.higher_timeframe or {}).get("trend_bias") != "short":
            return 0.0

        indicators = symbol_snapshot.indicators
        return_1bar = float(indicators.get("return_1bar") or 0.0)
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
        sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
        volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
        volatility_pct = max(
            float(indicators.get("atr_14_pct") or 0.0),
            float(indicators.get("range_pct") or 0.0),
        )

        if return_1bar >= 0.0:
            return 0.0
        if return_24bars < 0.0 or return_24bars > COUNTERTREND_BREAKOUT_SHORT_MAX_24BAR_RETURN_PCT:
            return 0.0
        if sma_fast_ratio >= 0.0:
            return 0.0
        if sma_slow_ratio < 0.0 or sma_slow_ratio > COUNTERTREND_BREAKOUT_SHORT_MAX_SLOW_SMA_RATIO:
            return 0.0
        if volume_ratio < COUNTERTREND_BREAKOUT_SHORT_MIN_VOLUME_RATIO:
            return 0.0
        if volatility_pct < COUNTERTREND_BREAKOUT_SHORT_MIN_VOLATILITY_PCT:
            return 0.0

        return min(volatility_pct * 0.5, COUNTERTREND_BREAKOUT_SHORT_EDGE_BONUS_CAP)

    def _directional_return_pct(self, action: str, *, return_1bar: float, return_24bars: float) -> tuple[float, float]:
        if action == "buy":
            return max(return_1bar, 0.0), max(return_24bars, 0.0)
        if action == "sell":
            return max(-return_1bar, 0.0), max(-return_24bars, 0.0)
        return 0.0, 0.0

    def _open_signal_context(self, action: str, symbol_snapshot) -> dict[str, object]:
        if symbol_snapshot is None:
            return {
                "return_24bars": 0.0,
                "sma_fast_ratio": 0.0,
                "sma_slow_ratio": 0.0,
                "volume_ratio": 0.0,
                "countertrend_breakout_short": False,
                "higher_timeframe_short_reclaim": False,
                "higher_timeframe_long_reclaim": False,
                "higher_timeframe_long_early_reclaim": False,
                "higher_timeframe_long_reversal": False,
                "long_sma_fast_exception": False,
            }

        indicators = symbol_snapshot.indicators
        return {
            "return_24bars": float(indicators.get("return_24bars") or 0.0),
            "sma_fast_ratio": float(indicators.get("sma_fast_ratio") or 0.0),
            "sma_slow_ratio": float(indicators.get("sma_slow_ratio") or 0.0),
            "volume_ratio": float(indicators.get("volume_ratio_20") or 0.0),
            "countertrend_breakout_short": self._countertrend_breakout_short_bonus_pct(action, symbol_snapshot) > 0.0,
            "higher_timeframe_short_reclaim": self._higher_timeframe_short_reclaim_bonus_pct(action, symbol_snapshot) > 0.0,
            "higher_timeframe_long_reclaim": self._higher_timeframe_long_reclaim_bonus_pct(action, symbol_snapshot) > 0.0,
            "higher_timeframe_long_early_reclaim": self._higher_timeframe_long_early_reclaim_bonus_pct(action, symbol_snapshot) > 0.0,
            "higher_timeframe_long_reversal": self._higher_timeframe_long_reversal_ready(action, symbol_snapshot),
            "long_sma_fast_exception": self._allow_long_side_sma_fast_exception(action, symbol_snapshot),
        }

    def _open_signal_hard_reasons(self, action: str, symbol_snapshot) -> list[str]:
        if symbol_snapshot is None:
            return ["missing_symbol_snapshot"]
        context = self._open_signal_context(action, symbol_snapshot)
        reasons: list[str] = []
        if action == "buy":
            if (
                float(context["sma_slow_ratio"]) <= 0.0
                and not (
                    bool(context["higher_timeframe_long_reversal"])
                    or bool(context["higher_timeframe_long_reclaim"])
                    or bool(context["higher_timeframe_long_early_reclaim"])
                )
            ):
                reasons.append("open_signal_sma_slow_conflict")
        elif action == "sell":
            if (
                float(context["sma_slow_ratio"]) >= 0.0
                and not (
                    bool(context["countertrend_breakout_short"])
                    or bool(context["higher_timeframe_short_reclaim"])
                )
            ):
                reasons.append("open_signal_sma_slow_conflict")
        if float(context["volume_ratio"]) < MIN_OPEN_SIGNAL_VOLUME_RATIO:
            reasons.append("open_signal_low_volume")
        return reasons

    def _open_signal_soft_edge_adjustments(self, action: str, symbol_snapshot) -> dict[str, float]:
        if symbol_snapshot is None:
            return {}
        context = self._open_signal_context(action, symbol_snapshot)
        adjustments: dict[str, float] = {}
        if action == "buy":
            if (
                float(context["return_24bars"]) <= MIN_OPEN_SIGNAL_TREND_RETURN_PCT
                and not (
                    bool(context["higher_timeframe_long_reversal"])
                    or bool(context["higher_timeframe_long_reclaim"])
                    or bool(context["higher_timeframe_long_early_reclaim"])
                )
            ):
                adjustments["open_signal_return_24bars_too_weak_penalty_pct"] = -OPEN_SIGNAL_WEAK_TREND_EDGE_PENALTY_PCT
            if float(context["sma_fast_ratio"]) <= 0.0 and not bool(context["long_sma_fast_exception"]):
                adjustments["open_signal_sma_fast_conflict_penalty_pct"] = -OPEN_SIGNAL_FAST_SMA_EDGE_PENALTY_PCT
        elif action == "sell":
            if (
                float(context["return_24bars"]) >= -MIN_OPEN_SIGNAL_TREND_RETURN_PCT
                and not (
                    bool(context["countertrend_breakout_short"])
                    or bool(context["higher_timeframe_short_reclaim"])
                )
            ):
                adjustments["open_signal_return_24bars_too_weak_penalty_pct"] = -OPEN_SIGNAL_WEAK_TREND_EDGE_PENALTY_PCT
            if float(context["sma_fast_ratio"]) >= 0.0:
                adjustments["open_signal_sma_fast_conflict_penalty_pct"] = -OPEN_SIGNAL_FAST_SMA_EDGE_PENALTY_PCT
        return adjustments

    def _volatility_cap_multiplier(self, entry_archetype: str | None) -> float | None:
        if entry_archetype == "plain_open":
            return PLAIN_OPEN_VOLATILITY_CAP_MULTIPLIER
        if entry_archetype == "flat_bias_short":
            return FLAT_BIAS_SHORT_VOLATILITY_CAP_MULTIPLIER
        return None

    def _directional_signal_share(self, action: str, symbol_snapshot) -> float:
        if symbol_snapshot is None:
            return 0.0
        indicators = symbol_snapshot.indicators
        directional_1bar_pct, directional_24bars_pct = self._directional_return_pct(
            action,
            return_1bar=float(indicators.get("return_1bar") or 0.0),
            return_24bars=float(indicators.get("return_24bars") or 0.0),
        )
        directional_signal_pct = max(
            directional_1bar_pct,
            directional_24bars_pct * EDGE_TREND_RETURN_SCALE,
        )
        volatility_component_pct = (
            (float(indicators.get("atr_14_pct") or 0.0) * EDGE_ATR_WEIGHT)
            + (float(indicators.get("range_pct") or 0.0) * EDGE_RANGE_WEIGHT)
        )
        if volatility_component_pct <= 0.0:
            return 0.0
        return directional_signal_pct / volatility_component_pct

    def _pre_break_continuation_bonus_pct(self, action: str, symbol_snapshot) -> float:
        if action not in {"buy", "sell"} or symbol_snapshot is None:
            return 0.0
        assessment = assess_fresh_entry(symbol_snapshot, action=action)
        if not assessment.continuation_watch or assessment.terminal_extension:
            return 0.0
        indicators = symbol_snapshot.indicators
        higher = symbol_snapshot.higher_timeframe or {}
        volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
        if volume_ratio < PRE_BREAK_CONTINUATION_MIN_VOLUME_RATIO:
            return 0.0
        if action == "sell":
            if higher.get("trend_bias") != "short":
                return 0.0
            if (
                symbol_snapshot.symbol == "ETH/USDT:USDT"
                and volume_ratio < PRE_BREAK_CONTINUATION_SHORT_STRONG_MIN_VOLUME_RATIO
            ):
                return 0.0
            if (
                symbol_snapshot.symbol == "ETH/USDT:USDT"
                and float(indicators.get("rsi_14") or 50.0) > PRE_BREAK_CONTINUATION_SHORT_MAX_LOCAL_RSI
            ):
                return 0.0
            if float(higher.get("return_12bars") or 0.0) > -PRE_BREAK_CONTINUATION_MIN_HIGHER_RETURN_12BAR_PCT:
                return 0.0
            if float(higher.get("sma_slow_ratio") or 0.0) > -PRE_BREAK_CONTINUATION_MIN_HIGHER_SLOW_SMA_RATIO:
                return 0.0
            if float(indicators.get("return_1bar") or 0.0) > 0.0:
                return 0.0
        else:
            if higher.get("trend_bias") != "long":
                return 0.0
            if float(higher.get("return_12bars") or 0.0) < PRE_BREAK_CONTINUATION_MIN_HIGHER_RETURN_12BAR_PCT:
                return 0.0
            if float(higher.get("sma_slow_ratio") or 0.0) < PRE_BREAK_CONTINUATION_MIN_HIGHER_SLOW_SMA_RATIO:
                return 0.0
            if float(indicators.get("return_1bar") or 0.0) < 0.0:
                return 0.0
        return PRE_BREAK_CONTINUATION_EDGE_BONUS_PCT

    def _higher_timeframe_long_reclaim_bonus_pct(self, action: str, symbol_snapshot) -> float:
        if action != "buy" or symbol_snapshot is None:
            return 0.0

        indicators = symbol_snapshot.indicators
        higher = symbol_snapshot.higher_timeframe or {}
        volatility_pct = max(
            float(indicators.get("atr_14_pct") or 0.0),
            float(indicators.get("range_pct") or 0.0),
        )
        if higher.get("trend_bias") != "long":
            return 0.0
        if float(higher.get("return_12bars") or 0.0) < HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_HIGHER_RETURN_12BAR_PCT:
            return 0.0
        if float(higher.get("sma_slow_ratio") or 0.0) < HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_HIGHER_SLOW_SMA_RATIO:
            return 0.0
        if float(higher.get("rsi_14") or 0.0) < HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_HIGHER_RSI:
            return 0.0
        if float(indicators.get("return_1bar") or 0.0) < HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_1BAR_PCT:
            return 0.0
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        if return_24bars < HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_24BAR_PCT:
            return 0.0
        if return_24bars > HIGHER_TIMEFRAME_LONG_RECLAIM_MAX_24BAR_PCT:
            return 0.0
        if float(indicators.get("volume_ratio_20") or 0.0) < HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_VOLUME_RATIO:
            return 0.0
        if volatility_pct < HIGHER_TIMEFRAME_LONG_RECLAIM_MIN_VOLATILITY_PCT:
            return 0.0
        if float(indicators.get("sma_fast_ratio") or 0.0) <= 0.0:
            return 0.0
        if float(indicators.get("sma_slow_ratio") or 0.0) >= 0.0:
            return 0.0
        return HIGHER_TIMEFRAME_LONG_RECLAIM_EDGE_BONUS_PCT

    def _higher_timeframe_long_early_reclaim_bonus_pct(self, action: str, symbol_snapshot) -> float:
        if action != "buy" or symbol_snapshot is None:
            return 0.0

        indicators = symbol_snapshot.indicators
        higher = symbol_snapshot.higher_timeframe or {}
        volatility_pct = max(
            float(indicators.get("atr_14_pct") or 0.0),
            float(indicators.get("range_pct") or 0.0),
        )
        if higher.get("trend_bias") != "long":
            return 0.0
        if float(higher.get("return_12bars") or 0.0) < HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_HIGHER_RETURN_12BAR_PCT:
            return 0.0
        if float(higher.get("sma_slow_ratio") or 0.0) < HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_HIGHER_SLOW_SMA_RATIO:
            return 0.0
        if float(higher.get("rsi_14") or 0.0) < HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_HIGHER_RSI:
            return 0.0
        if float(indicators.get("return_1bar") or 0.0) < HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_BONUS_MIN_1BAR_PCT:
            return 0.0
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        if return_24bars < HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_24BAR_PCT:
            return 0.0
        if return_24bars > HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MAX_24BAR_PCT:
            return 0.0
        if float(indicators.get("volume_ratio_20") or 0.0) < HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_VOLUME_RATIO:
            return 0.0
        if volatility_pct < HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MIN_VOLATILITY_PCT:
            return 0.0
        if float(indicators.get("sma_fast_ratio") or 0.0) <= 0.0:
            return 0.0
        if float(indicators.get("sma_slow_ratio") or 0.0) >= 0.0:
            return 0.0
        if float(indicators.get("rsi_14") or 50.0) > HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_MAX_LOCAL_RSI:
            return 0.0
        return HIGHER_TIMEFRAME_LONG_EARLY_RECLAIM_EDGE_BONUS_PCT

    def _higher_timeframe_long_reversal_ready(self, action: str, symbol_snapshot) -> bool:
        if action != "buy" or symbol_snapshot is None:
            return False

        indicators = symbol_snapshot.indicators
        higher = symbol_snapshot.higher_timeframe or {}
        if higher.get("trend_bias") != "long":
            return False
        if float(higher.get("return_12bars") or 0.0) < HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_HIGHER_RETURN_12BAR_PCT:
            return False
        if float(higher.get("sma_slow_ratio") or 0.0) < HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_HIGHER_SLOW_SMA_RATIO:
            return False
        if float(higher.get("rsi_14") or 0.0) < HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_HIGHER_RSI:
            return False

        return_1bar = float(indicators.get("return_1bar") or 0.0)
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        if return_1bar < HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_1BAR_PCT:
            return False
        if return_24bars < HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_24BAR_PCT:
            return False
        if return_24bars > HIGHER_TIMEFRAME_LONG_REVERSAL_MAX_24BAR_PCT:
            return False
        if float(indicators.get("rsi_14") or 50.0) > HIGHER_TIMEFRAME_LONG_REVERSAL_MAX_LOCAL_RSI:
            return False
        if float(indicators.get("volume_ratio_20") or 0.0) < HIGHER_TIMEFRAME_LONG_REVERSAL_MIN_VOLUME_RATIO:
            return False
        if float(indicators.get("sma_fast_ratio") or 0.0) >= 0.0:
            return False
        if float(indicators.get("sma_slow_ratio") or 0.0) >= 0.0:
            return False
        return True

    def _higher_timeframe_long_fast_pullback_ready(self, action: str, symbol_snapshot) -> bool:
        if action != "buy" or symbol_snapshot is None:
            return False

        indicators = symbol_snapshot.indicators
        higher = symbol_snapshot.higher_timeframe or {}
        volatility_pct = max(
            float(indicators.get("atr_14_pct") or 0.0),
            float(indicators.get("range_pct") or 0.0),
        )
        if higher.get("trend_bias") != "long":
            return False
        if float(higher.get("return_12bars") or 0.0) < HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_HIGHER_RETURN_12BAR_PCT:
            return False
        if float(higher.get("sma_slow_ratio") or 0.0) < HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_HIGHER_SLOW_SMA_RATIO:
            return False
        if float(indicators.get("return_24bars") or 0.0) < HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_24BAR_PCT:
            return False
        if float(indicators.get("volume_ratio_20") or 0.0) < HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_VOLUME_RATIO:
            return False
        if volatility_pct < HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MIN_VOLATILITY_PCT:
            return False
        return_1bar = float(indicators.get("return_1bar") or 0.0)
        if return_1bar > 0.0:
            return False
        if abs(return_1bar) > HIGHER_TIMEFRAME_LONG_FAST_PULLBACK_MAX_NEGATIVE_1BAR_PCT:
            return False
        if float(indicators.get("sma_fast_ratio") or 0.0) >= 0.0:
            return False
        if float(indicators.get("sma_slow_ratio") or 0.0) <= 0.0:
            return False
        return True

    def _allow_long_side_sma_fast_exception(self, action: str, symbol_snapshot) -> bool:
        if action != "buy" or symbol_snapshot is None:
            return False
        # Only the narrow long reversal / fast-pullback lanes can bypass
        # local fast-SMA lag. This does not relax slow-SMA or 24-bar checks.
        return (
            self._higher_timeframe_long_reversal_ready(action, symbol_snapshot)
            or self._higher_timeframe_long_fast_pullback_ready(action, symbol_snapshot)
        )

    def _higher_timeframe_short_reclaim_bonus_pct(self, action: str, symbol_snapshot) -> float:
        if action != "sell" or symbol_snapshot is None:
            return 0.0

        indicators = symbol_snapshot.indicators
        higher = symbol_snapshot.higher_timeframe or {}
        volatility_pct = max(
            float(indicators.get("atr_14_pct") or 0.0),
            float(indicators.get("range_pct") or 0.0),
        )
        if higher.get("trend_bias") != "short":
            return 0.0
        if float(higher.get("return_12bars") or 0.0) > HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_HIGHER_RETURN_12BAR_PCT:
            return 0.0
        if float(higher.get("sma_slow_ratio") or 0.0) > HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_HIGHER_SLOW_SMA_RATIO:
            return 0.0
        if float(higher.get("rsi_14") or 50.0) > HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_HIGHER_RSI:
            return 0.0
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        if return_24bars < HIGHER_TIMEFRAME_SHORT_RECLAIM_MIN_24BAR_PCT:
            return 0.0
        if return_24bars > HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_24BAR_PCT:
            return 0.0
        if float(indicators.get("return_1bar") or 0.0) > HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_1BAR_PCT:
            return 0.0
        if float(indicators.get("volume_ratio_20") or 0.0) < HIGHER_TIMEFRAME_SHORT_RECLAIM_MIN_VOLUME_RATIO:
            return 0.0
        if volatility_pct < HIGHER_TIMEFRAME_SHORT_RECLAIM_MIN_VOLATILITY_PCT:
            return 0.0
        if float(indicators.get("sma_fast_ratio") or 0.0) >= 0.0:
            return 0.0
        if float(indicators.get("sma_slow_ratio") or 0.0) >= 0.0:
            return 0.0
        if float(indicators.get("rsi_14") or 50.0) > HIGHER_TIMEFRAME_SHORT_RECLAIM_MAX_LOCAL_RSI:
            return 0.0
        return HIGHER_TIMEFRAME_SHORT_RECLAIM_EDGE_BONUS_PCT

    def _aligned_short_continuation_bonus_pct(self, action: str, symbol_snapshot) -> float:
        if action != "sell" or symbol_snapshot is None:
            return 0.0

        indicators = symbol_snapshot.indicators
        higher = symbol_snapshot.higher_timeframe or {}
        volatility_pct = max(
            float(indicators.get("atr_14_pct") or 0.0),
            float(indicators.get("range_pct") or 0.0),
        )
        if higher.get("trend_bias") != "short":
            return 0.0
        if float(higher.get("return_12bars") or 0.0) > ALIGNED_SHORT_CONTINUATION_MIN_HIGHER_RETURN_12BAR_PCT:
            return 0.0
        if float(higher.get("sma_slow_ratio") or 0.0) > ALIGNED_SHORT_CONTINUATION_MAX_HIGHER_SLOW_SMA_RATIO:
            return 0.0
        if float(higher.get("rsi_14") or 50.0) > ALIGNED_SHORT_CONTINUATION_MAX_HIGHER_RSI:
            return 0.0
        if float(indicators.get("return_1bar") or 0.0) > -ALIGNED_SHORT_CONTINUATION_MIN_1BAR_PCT:
            return 0.0
        if float(indicators.get("return_24bars") or 0.0) > ALIGNED_SHORT_CONTINUATION_MAX_24BAR_PCT:
            return 0.0
        if float(indicators.get("volume_ratio_20") or 0.0) < ALIGNED_SHORT_CONTINUATION_MIN_VOLUME_RATIO:
            return 0.0
        if volatility_pct < ALIGNED_SHORT_CONTINUATION_MIN_VOLATILITY_PCT:
            return 0.0
        if float(indicators.get("sma_fast_ratio") or 0.0) >= 0.0:
            return 0.0
        if float(indicators.get("sma_slow_ratio") or 0.0) >= 0.0:
            return 0.0
        if float(indicators.get("rsi_14") or 50.0) > ALIGNED_SHORT_CONTINUATION_MAX_LOCAL_RSI:
            return 0.0
        assessment = assess_fresh_entry(symbol_snapshot, action=action)
        if assessment.terminal_extension:
            return 0.0
        return ALIGNED_SHORT_CONTINUATION_EDGE_BONUS_PCT

    def _fresh_entry_bias_edge_adjustment_pct(self, action: str, symbol_snapshot) -> float:
        return sum(self._fresh_entry_bias_adjustments(action, symbol_snapshot).values())

    def _fresh_entry_bias_adjustments(self, action: str, symbol_snapshot) -> dict[str, float]:
        if action not in {"buy", "sell"} or symbol_snapshot is None:
            return {}
        adjustments: dict[str, float] = {}
        trend_bias = (symbol_snapshot.higher_timeframe or {}).get("trend_bias")
        if trend_bias == "flat":
            # Flat higher-timeframe entries should clear a larger edge cushion than aligned-trend entries.
            adjustments["flat_bias_penalty_pct"] = -FLAT_BIAS_FRESH_ENTRY_EDGE_PENALTY_PCT
        if action != "sell":
            return adjustments

        fresh_entry_assessment = assess_fresh_entry(symbol_snapshot, action=action)
        entry_archetype = self._entry_archetype(
            action,
            symbol_snapshot,
            has_position=False,
            fresh_entry_assessment=fresh_entry_assessment,
        )
        if self._open_signal_hard_reasons(action, symbol_snapshot):
            return adjustments
        directional_signal_share = self._directional_signal_share(action, symbol_snapshot)
        weak_plain_open = (
            entry_archetype == "plain_open"
            and directional_signal_share < WEAK_PLAIN_OPEN_DIRECTIONAL_SHARE_THRESHOLD
        )
        weak_flat_bias_short = (
            entry_archetype == "flat_bias_short"
            and directional_signal_share < WEAK_FLAT_BIAS_SHORT_DIRECTIONAL_SHARE_THRESHOLD
        )
        weak_pre_break_continuation_short = (
            fresh_entry_assessment.continuation_watch
            and symbol_snapshot.symbol == "ETH/USDT:USDT"
            and (
                float(symbol_snapshot.indicators.get("volume_ratio_20") or 0.0) < PRE_BREAK_CONTINUATION_SHORT_STRONG_MIN_VOLUME_RATIO
                or float(symbol_snapshot.indicators.get("rsi_14") or 50.0) > PRE_BREAK_CONTINUATION_SHORT_MAX_LOCAL_RSI
            )
        )
        if weak_plain_open:
            adjustments["weak_plain_open_short_penalty_pct"] = -WEAK_PLAIN_OPEN_SHORT_EDGE_PENALTY_PCT
        elif weak_flat_bias_short:
            adjustments["weak_flat_bias_short_penalty_pct"] = -WEAK_FLAT_BIAS_SHORT_EDGE_PENALTY_PCT
        elif weak_pre_break_continuation_short:
            adjustments["weak_pre_break_continuation_short_penalty_pct"] = -WEAK_PRE_BREAK_CONTINUATION_SHORT_EDGE_PENALTY_PCT
        if self._is_alt_short_tighten_symbol(symbol_snapshot.symbol):
            if weak_flat_bias_short:
                adjustments["alt_short_penalty_pct"] = -self.settings.alt_short_edge_penalty_pct
            elif weak_plain_open:
                adjustments["alt_short_penalty_pct"] = -(self.settings.alt_short_edge_penalty_pct * 0.5)
        return adjustments

    def _weak_same_direction_short_edge_buffer_pct(
        self,
        *,
        action: str,
        symbol_snapshot,
        has_position: bool,
        fresh_entry_assessment,
        portfolio_context: dict[str, object] | None,
    ) -> float:
        if action != "sell" or has_position or symbol_snapshot is None or not portfolio_context:
            return 0.0
        entry_archetype = self._entry_archetype(
            action,
            symbol_snapshot,
            has_position=has_position,
            fresh_entry_assessment=fresh_entry_assessment,
        )
        if entry_archetype not in {"plain_open", "flat_bias_short"}:
            return 0.0
        current_same_direction_positions = int(portfolio_context.get("current_same_direction_positions") or 0)
        if current_same_direction_positions < 1:
            return 0.0
        return WEAK_SAME_DIRECTION_SHORT_EDGE_BUFFER_PCT

    def _flat_bias_short_flush_blocked(self, action: str, symbol_snapshot) -> bool:
        if action != "sell" or symbol_snapshot is None:
            return False
        trend_bias = (symbol_snapshot.higher_timeframe or {}).get("trend_bias")
        if trend_bias != "flat":
            return False
        indicators = symbol_snapshot.indicators
        directional_1bar = max(-float(indicators.get("return_1bar") or 0.0), 0.0)
        directional_24bars = max(-float(indicators.get("return_24bars") or 0.0), 0.0)
        volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
        rsi_14 = float(indicators.get("rsi_14") or 50.0)
        sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
        sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
        return (
            directional_24bars >= FLAT_BIAS_SHORT_FLUSH_MIN_DIRECTIONAL_24BAR_PCT
            and directional_1bar >= FLAT_BIAS_SHORT_FLUSH_MIN_DIRECTIONAL_1BAR_PCT
            and volume_ratio >= FLAT_BIAS_SHORT_FLUSH_MIN_VOLUME_RATIO
            and rsi_14 <= FLAT_BIAS_SHORT_FLUSH_MAX_LOCAL_RSI
            and sma_fast_ratio < 0.0
            and sma_slow_ratio < 0.0
        )

    def _short_exhaustion_flush_blocked(self, action: str, symbol_snapshot) -> bool:
        if action != "sell" or symbol_snapshot is None:
            return False
        higher = symbol_snapshot.higher_timeframe or {}
        if higher.get("trend_bias") != "short":
            return False
        if float(higher.get("return_12bars") or 0.0) < SHORT_EXHAUSTION_FLUSH_MIN_HIGHER_RETURN_12BAR_PCT:
            return False
        indicators = symbol_snapshot.indicators
        directional_24bars = max(-float(indicators.get("return_24bars") or 0.0), 0.0)
        volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
        rsi_14 = float(indicators.get("rsi_14") or 50.0)
        sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
        sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
        return (
            directional_24bars >= SHORT_EXHAUSTION_FLUSH_MIN_DIRECTIONAL_24BAR_PCT
            and volume_ratio >= SHORT_EXHAUSTION_FLUSH_MIN_VOLUME_RATIO
            and rsi_14 <= SHORT_EXHAUSTION_FLUSH_MAX_LOCAL_RSI
            and sma_fast_ratio < 0.0
            and sma_slow_ratio < 0.0
        )

    def _entry_archetype(
        self,
        action: str,
        symbol_snapshot,
        *,
        has_position: bool,
        fresh_entry_assessment,
    ) -> str | None:
        if action not in {"buy", "sell"} or symbol_snapshot is None:
            return None
        if not has_position and self._flat_bias_short_flush_blocked(action, symbol_snapshot):
            return "flat_bias_short_flush"
        if not has_position and self._short_exhaustion_flush_blocked(action, symbol_snapshot):
            return "short_exhaustion_flush"
        if fresh_entry_assessment is not None and fresh_entry_assessment.terminal_extension:
            return "terminal_extension"
        if self._countertrend_breakout_short_bonus_pct(action, symbol_snapshot) > 0.0:
            return "countertrend_breakout_short"
        if self._aligned_short_continuation_bonus_pct(action, symbol_snapshot) > 0.0:
            return "aligned_short_continuation_short"
        if self._higher_timeframe_short_reclaim_bonus_pct(action, symbol_snapshot) > 0.0:
            return "higher_timeframe_short_reclaim_short"
        if self._pre_break_continuation_bonus_pct(action, symbol_snapshot) > 0.0:
            return "pre_break_continuation"
        if self._higher_timeframe_long_reclaim_bonus_pct(action, symbol_snapshot) > 0.0:
            return "higher_timeframe_long_reclaim_long"
        if self._higher_timeframe_long_early_reclaim_bonus_pct(action, symbol_snapshot) > 0.0:
            return "higher_timeframe_long_early_reclaim_long"
        if self._higher_timeframe_long_reversal_ready(action, symbol_snapshot):
            return "higher_timeframe_long_reversal_long"
        if self._higher_timeframe_long_fast_pullback_ready(action, symbol_snapshot):
            return "higher_timeframe_long_fast_pullback_long"
        trend_bias = (symbol_snapshot.higher_timeframe or {}).get("trend_bias")
        if not has_position and action == "sell" and trend_bias == "flat":
            return "flat_bias_short"
        if has_position:
            return "position_add_or_reverse"
        return "plain_open"

    def _expected_edge_breakdown(
        self,
        decision: ValidatedDecision,
        symbol_snapshot,
        *,
        include_fresh_entry_bias: bool,
    ) -> dict[str, object]:
        indicators = symbol_snapshot.indicators if symbol_snapshot is not None else {}
        atr_pct = float(indicators.get("atr_14_pct") or 0.0)
        range_pct = float(indicators.get("range_pct") or 0.0)
        return_1bar = float(indicators.get("return_1bar") or 0.0)
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        fresh_entry_assessment = (
            assess_fresh_entry(symbol_snapshot, action=decision.decision.action)
            if symbol_snapshot is not None and decision.decision.action in {"buy", "sell"}
            else None
        )
        entry_archetype = self._entry_archetype(
            decision.decision.action,
            symbol_snapshot,
            has_position=False,
            fresh_entry_assessment=fresh_entry_assessment,
        )
        directional_1bar_pct, directional_24bars_pct = self._directional_return_pct(
            decision.decision.action,
            return_1bar=return_1bar,
            return_24bars=return_24bars,
        )
        volatility_component_pct = (
            (atr_pct * EDGE_ATR_WEIGHT)
            + (range_pct * EDGE_RANGE_WEIGHT)
        )
        directional_signal_pct = max(
            directional_1bar_pct,
            directional_24bars_pct * EDGE_TREND_RETURN_SCALE,
        )
        volatility_cap_multiplier = self._volatility_cap_multiplier(entry_archetype)
        effective_volatility_component_pct = volatility_component_pct
        if volatility_cap_multiplier is not None:
            effective_volatility_component_pct = min(
                volatility_component_pct,
                directional_signal_pct * volatility_cap_multiplier,
            )
        directional_component_pct = min(directional_signal_pct, effective_volatility_component_pct) * EDGE_DIRECTIONAL_WEIGHT
        projected_move_pct = effective_volatility_component_pct + directional_component_pct
        estimated_cost_pct = estimated_action_cost_pct(
            decision.decision.action,
            contract_market=self.settings.contract_market,
            fee_pct=self.settings.estimated_fee_pct,
            slippage_pct=self.settings.estimated_slippage_pct,
        )
        soft_signal_edge_adjustments = self._open_signal_soft_edge_adjustments(decision.decision.action, symbol_snapshot)
        bonuses = {
            "countertrend_breakout_short_bonus_pct": self._countertrend_breakout_short_bonus_pct(decision.decision.action, symbol_snapshot),
            "aligned_short_continuation_bonus_pct": self._aligned_short_continuation_bonus_pct(decision.decision.action, symbol_snapshot),
            "higher_timeframe_short_reclaim_bonus_pct": self._higher_timeframe_short_reclaim_bonus_pct(decision.decision.action, symbol_snapshot),
            "pre_break_continuation_bonus_pct": self._pre_break_continuation_bonus_pct(decision.decision.action, symbol_snapshot),
            "higher_timeframe_long_reclaim_bonus_pct": self._higher_timeframe_long_reclaim_bonus_pct(decision.decision.action, symbol_snapshot),
            "higher_timeframe_long_early_reclaim_bonus_pct": self._higher_timeframe_long_early_reclaim_bonus_pct(decision.decision.action, symbol_snapshot),
        }
        base_expected_edge_pct = projected_move_pct - estimated_cost_pct + sum(bonuses.values()) + sum(soft_signal_edge_adjustments.values())
        fresh_entry_bias_adjustments = (
            self._fresh_entry_bias_adjustments(decision.decision.action, symbol_snapshot)
            if include_fresh_entry_bias
            else {}
        )
        fresh_entry_bias_adjustment_pct = sum(fresh_entry_bias_adjustments.values())
        final_expected_edge_pct = base_expected_edge_pct + fresh_entry_bias_adjustment_pct
        return {
            "directional_1bar_pct": directional_1bar_pct,
            "directional_24bars_pct": directional_24bars_pct,
            "volatility_component_pct": volatility_component_pct,
            "effective_volatility_component_pct": effective_volatility_component_pct,
            "volatility_cap_multiplier": volatility_cap_multiplier,
            "directional_signal_pct": directional_signal_pct,
            "directional_component_pct": directional_component_pct,
            "projected_move_pct": projected_move_pct,
            "estimated_cost_pct": estimated_cost_pct,
            "bonuses": bonuses,
            "soft_signal_edge_adjustments": soft_signal_edge_adjustments,
            "entry_archetype": entry_archetype,
            "base_expected_edge_pct": base_expected_edge_pct,
            "fresh_entry_bias_adjustments": fresh_entry_bias_adjustments,
            "fresh_entry_bias_adjustment_pct": fresh_entry_bias_adjustment_pct,
            "final_expected_edge_pct": final_expected_edge_pct,
            "threshold_pct": self.settings.min_expected_edge_pct,
            "threshold_gap_pct": self.settings.min_expected_edge_pct - final_expected_edge_pct,
        }

    def _expected_edge_pct(self, decision: ValidatedDecision, symbol_snapshot) -> float:
        return float(
            self._expected_edge_breakdown(
                decision,
                symbol_snapshot,
                include_fresh_entry_bias=False,
            )["base_expected_edge_pct"]
        )

    def _risk_size_cap_pct(self, action: str, stop_loss_pct: float) -> tuple[float | None, float, float]:
        if not self.settings.risk_sizing_enable or not self.settings.contract_market:
            return None, stop_loss_pct, 0.0
        leverage = max(float(self.settings.contract_leverage), 1.0)
        min_stop = max(float(self.settings.min_effective_stop_loss_pct), 0.0)
        max_stop = max(float(self.settings.max_effective_stop_loss_pct), min_stop)
        effective_stop_loss_pct = min(max(stop_loss_pct, min_stop), max_stop)
        cost_pct = (
            estimated_action_cost_pct(
                action,
                contract_market=self.settings.contract_market,
                fee_pct=self.settings.estimated_fee_pct,
                slippage_pct=self.settings.estimated_slippage_pct,
            )
            if self.settings.risk_sizing_include_cost
            else 0.0
        )
        risk_distance_pct = effective_stop_loss_pct + cost_pct
        if risk_distance_pct <= 0.0:
            return None, effective_stop_loss_pct, cost_pct
        return self.settings.max_risk_per_trade_pct / (leverage * risk_distance_pct), effective_stop_loss_pct, cost_pct

    def _open_signal_reasons(self, action: str, symbol_snapshot) -> list[str]:
        hard_reasons = self._open_signal_hard_reasons(action, symbol_snapshot)
        soft_reasons: list[str] = []
        for key in self._open_signal_soft_edge_adjustments(action, symbol_snapshot):
            if key.startswith("open_signal_return_24bars_too_weak"):
                soft_reasons.append("open_signal_return_24bars_too_weak")
            elif key.startswith("open_signal_sma_fast_conflict"):
                soft_reasons.append("open_signal_sma_fast_conflict")
        combined: list[str] = []
        seen: set[str] = set()
        for reason in [*soft_reasons, *hard_reasons]:
            if reason in seen:
                continue
            seen.add(reason)
            combined.append(reason)
        return combined

    def _management_signal(self, position_side: str | None, symbol_snapshot) -> str | None:
        if position_side not in {"long", "short"} or symbol_snapshot is None:
            return None
        indicators = symbol_snapshot.indicators
        return_1bar = float(indicators.get("return_1bar") or 0.0)
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
        sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
        trend_bias = (symbol_snapshot.higher_timeframe or {}).get("trend_bias")

        if position_side == "long":
            adverse = (
                return_1bar <= -MANAGEMENT_ADVERSE_MIN_1BAR_PCT
                and sma_fast_ratio < 0.0
                and (
                    trend_bias == "short"
                    or sma_slow_ratio < 0.0
                    or return_24bars <= -MANAGEMENT_ADVERSE_MIN_24BAR_PCT
                )
            )
            supportive = (
                return_1bar >= 0.0
                and sma_fast_ratio >= 0.0
                and trend_bias != "short"
                and (
                    sma_slow_ratio >= 0.0
                    or return_24bars >= MANAGEMENT_SUPPORT_MIN_24BAR_PCT
                )
            )
        else:
            adverse = (
                return_1bar >= MANAGEMENT_ADVERSE_MIN_1BAR_PCT
                and sma_fast_ratio > 0.0
                and (
                    trend_bias == "long"
                    or sma_slow_ratio > 0.0
                    or return_24bars >= MANAGEMENT_ADVERSE_MIN_24BAR_PCT
                )
            )
            supportive = (
                return_1bar <= 0.0
                and sma_fast_ratio <= 0.0
                and trend_bias != "long"
                and (
                    sma_slow_ratio <= 0.0
                    or return_24bars <= -MANAGEMENT_SUPPORT_MIN_24BAR_PCT
                )
            )

        if adverse:
            return "adverse"
        if supportive:
            return "supportive"
        return None

    def _higher_timeframe_supports_position(self, position_side: str | None, symbol_snapshot) -> bool:
        if position_side not in {"long", "short"} or symbol_snapshot is None:
            return False
        trend_bias = (symbol_snapshot.higher_timeframe or {}).get("trend_bias")
        if position_side == "long":
            return trend_bias == "long"
        return trend_bias == "short"

    def _candidate_filter_symbol_summary(
        self,
        validated: ValidatedDecision,
        symbol: str,
    ) -> dict[str, object] | None:
        raw_payload = validated.raw_payload or {}
        candidate_filter = raw_payload.get("candidate_filter")
        if not isinstance(candidate_filter, dict):
            return None
        symbols = candidate_filter.get("symbols")
        if not isinstance(symbols, list):
            return None
        match = next(
            (
                item
                for item in symbols
                if isinstance(item, dict) and str(item.get("symbol") or "") == symbol
            ),
            None,
        )
        return match if isinstance(match, dict) else None

    def _setup_phase_from_candidate_summary(self, candidate_summary_for_symbol: dict[str, object] | None) -> str | None:
        if not isinstance(candidate_summary_for_symbol, dict):
            return None
        setup_phase = candidate_summary_for_symbol.get("setup_phase")
        if isinstance(setup_phase, str) and setup_phase:
            return setup_phase
        reasons = candidate_summary_for_symbol.get("reasons")
        if not isinstance(reasons, list) or not reasons:
            return None
        primary_reason = str(reasons[0] or "")
        if primary_reason == "short_setup_pre_breakdown_watch":
            return "short_continuation_confirmed"
        if primary_reason == "long_setup_pre_breakout_watch":
            return "long_continuation_confirmed"
        if primary_reason == "long_setup_pullback_reclaim_confirmed":
            return "long_pullback_reclaim_confirmed"
        if primary_reason == "long_setup_pullback_reclaim_unconfirmed":
            return "long_pullback_reclaim_unconfirmed"
        if primary_reason == "short_setup_rebound_fail_confirmed":
            return "short_rebound_fail_confirmed"
        if primary_reason == "short_setup_late_breakdown_soft_penalty":
            return "short_breakdown_chase"
        if primary_reason == "long_setup_late_breakout_soft_penalty":
            return "long_late_breakout_chase"
        return None

    def _entry_thesis(
        self,
        *,
        validated: ValidatedDecision,
        action: str,
        symbol_snapshot,
        fresh_entry_assessment,
    ) -> dict[str, object] | None:
        candidate_summary_for_symbol = self._candidate_filter_symbol_summary(validated, validated.decision.symbol)
        thesis = None
        if isinstance(candidate_summary_for_symbol, dict):
            candidate_thesis = candidate_summary_for_symbol.get("entry_thesis_candidate")
            if isinstance(candidate_thesis, dict) and candidate_thesis:
                thesis = dict(candidate_thesis)
            elif action in {"buy", "sell"}:
                higher = symbol_snapshot.higher_timeframe or {} if symbol_snapshot is not None else {}
                setup_phase = str(self._setup_phase_from_candidate_summary(candidate_summary_for_symbol) or "")
                if setup_phase and setup_phase != "range_noise":
                    if setup_phase in {"short_continuation_confirmed", "long_continuation_confirmed"}:
                        invalidation_type = "continuation_follow_through_failed"
                        follow_through_bars = 2
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
                    thesis = {
                        "version": 1,
                        "direction": "long" if action == "buy" else "short",
                        "higher_timeframe_direction": higher.get("trend_direction") or higher.get("trend_bias"),
                        "higher_timeframe_phase": candidate_summary_for_symbol.get("higher_timeframe_phase") or higher.get("trend_phase"),
                        "setup_phase": setup_phase,
                        "setup_confirmed": bool(candidate_summary_for_symbol.get("setup_confirmed")),
                        "invalidation_type": invalidation_type,
                        "follow_through_bars": follow_through_bars,
                    }
        if thesis is None:
            thesis = build_entry_thesis_candidate(symbol_snapshot, fresh_entry_assessment)
        if thesis is None:
            return None
        return {
            **thesis,
            "trigger_bar_timestamp_ms": (
                None
                if not symbol_snapshot.recent_candles
                else int(symbol_snapshot.recent_candles[-1].timestamp_ms)
            ),
            "entry_price": float(symbol_snapshot.last_price or 0.0),
            "entry_sma_fast_ratio": float(symbol_snapshot.indicators.get("sma_fast_ratio") or 0.0),
            "entry_sma_slow_ratio": float(symbol_snapshot.indicators.get("sma_slow_ratio") or 0.0),
            "entry_return_24bars": float(symbol_snapshot.indicators.get("return_24bars") or 0.0),
            "entry_rsi_14": float(symbol_snapshot.indicators.get("rsi_14") or 50.0),
        }

    def _entry_thesis_state(
        self,
        *,
        current_position,
        symbol_snapshot,
        last_open: dict | None,
        bars_since_open: int | None,
        current_position_return_pct: float | None,
    ) -> dict[str, object] | None:
        if current_position is None or symbol_snapshot is None or last_open is None:
            return None

        entry_thesis = last_open.get("entry_thesis")
        if not isinstance(entry_thesis, dict) or not entry_thesis:
            return None

        direction = str(entry_thesis.get("direction") or "")
        setup_phase = str(entry_thesis.get("setup_phase") or "")
        follow_through_bars = max(int(entry_thesis.get("follow_through_bars") or 1), 1)
        indicators = symbol_snapshot.indicators
        higher = symbol_snapshot.higher_timeframe or {}
        trend_bias = str(higher.get("trend_bias") or "")
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
        sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
        rsi_14 = float(indicators.get("rsi_14") or 50.0)
        weak_pnl = current_position_return_pct is None or current_position_return_pct <= 0.0
        preserve_profitable_eth_reclaim_short = self._should_preserve_profitable_eth_reclaim_short(
            entry_thesis=entry_thesis,
            symbol_snapshot=symbol_snapshot,
            current_position_return_pct=current_position_return_pct,
        )

        still_supported = False
        invalidation_reason: str | None = None

        if current_position.side == "short" and direction == "short":
            if trend_bias != "short":
                invalidation_reason = "higher_timeframe_short_bias_lost"
            elif sma_slow_ratio >= 0.0:
                invalidation_reason = "slow_sma_reclaimed"
            elif setup_phase == "short_breakdown_confirmed":
                if rsi_14 >= 45.0 and sma_fast_ratio > 0.0:
                    invalidation_reason = "breakdown_reclaimed"
                elif return_24bars > -0.0010 and sma_fast_ratio > 0.0:
                    invalidation_reason = "momentum_breakdown_failed"
                elif (
                    bars_since_open is not None
                    and bars_since_open >= follow_through_bars
                    and weak_pnl
                    and sma_fast_ratio > 0.0
                ):
                    invalidation_reason = "no_follow_through_after_short_breakdown"
                else:
                    still_supported = True
            elif setup_phase == "short_continuation_confirmed":
                if rsi_14 >= 55.0 and sma_fast_ratio > 0.0:
                    invalidation_reason = "rebound_strength_reclaimed_fast_sma"
                elif preserve_profitable_eth_reclaim_short:
                    still_supported = True
                elif self._should_preserve_profitable_eth_continuation_short_weak_rebound(
                    entry_thesis=entry_thesis,
                    symbol_snapshot=symbol_snapshot,
                    current_position_return_pct=current_position_return_pct,
                ):
                    still_supported = True
                elif return_24bars > 0.0015 and sma_fast_ratio > 0.0:
                    invalidation_reason = "directional_follow_through_lost"
                elif (
                    bars_since_open is not None
                    and bars_since_open >= follow_through_bars
                    and weak_pnl
                    and sma_fast_ratio > 0.0
                ):
                    invalidation_reason = "no_follow_through_after_short_continuation"
                else:
                    still_supported = True
            elif setup_phase == "short_rebound_fail_confirmed":
                current_short_assessment = assess_fresh_entry(symbol_snapshot, action="sell")
                current_traditional_context = build_traditional_signal_context(
                    symbol_snapshot,
                    current_short_assessment,
                )
                setup_degraded = current_short_assessment.setup_phase not in {
                    "short_rebound_fail_confirmed",
                    "short_breakdown_confirmed",
                    "short_continuation_confirmed",
                }
                downside_follow_through_intact = (
                    float(indicators.get("return_1bar") or 0.0) <= 0.0
                    and sma_fast_ratio < 0.0
                    and trend_bias == "short"
                )
                short_reclaim_warning = (
                    sma_fast_ratio >= 0.0
                    or rsi_14 >= 40.0
                    or float(indicators.get("return_1bar") or 0.0) >= MANAGEMENT_ADVERSE_MIN_1BAR_PCT
                )
                profitable = (
                    current_position_return_pct is not None
                    and current_position_return_pct >= self.settings.trailing_profit_arm_pct
                )
                if preserve_profitable_eth_reclaim_short:
                    still_supported = True
                elif (
                    profitable
                    and bars_since_open is not None
                    and bars_since_open >= follow_through_bars
                    and setup_degraded
                    and not downside_follow_through_intact
                    and short_reclaim_warning
                ):
                    invalidation_reason = "rebound_fail_profit_protection_exit"
                elif (
                    profitable
                    and isinstance(current_traditional_context, dict)
                    and bool(current_traditional_context.get("terminal_risk"))
                    and not downside_follow_through_intact
                    and short_reclaim_warning
                ):
                    invalidation_reason = "rebound_fail_terminal_extension_after_profit"
                elif (
                    bars_since_open is not None
                    and bars_since_open >= follow_through_bars
                    and weak_pnl
                    and sma_fast_ratio > 0.0
                ):
                    invalidation_reason = "rebound_fail_setup_lost"
                elif rsi_14 >= 50.0 and sma_fast_ratio > 0.0:
                    invalidation_reason = "short_rebound_fail_reclaimed"
                else:
                    still_supported = True
            else:
                still_supported = self._higher_timeframe_supports_position(current_position.side, symbol_snapshot)

        elif current_position.side == "long" and direction == "long":
            if trend_bias != "long":
                invalidation_reason = "higher_timeframe_long_bias_lost"
            elif sma_slow_ratio <= 0.0:
                invalidation_reason = "slow_sma_lost"
            elif setup_phase in {"long_continuation_confirmed", "long_pullback_reclaim_confirmed"}:
                if rsi_14 <= 45.0 and sma_fast_ratio < 0.0:
                    invalidation_reason = "reclaim_strength_lost"
                elif (
                    bars_since_open is not None
                    and bars_since_open >= follow_through_bars
                    and weak_pnl
                    and sma_fast_ratio < 0.0
                ):
                    invalidation_reason = "no_follow_through_after_long_entry"
                else:
                    still_supported = True
            elif setup_phase == "long_pullback_reclaim_unconfirmed":
                if sma_fast_ratio < 0.0 and weak_pnl:
                    invalidation_reason = "early_reclaim_failed"
                else:
                    still_supported = True
            else:
                still_supported = self._higher_timeframe_supports_position(current_position.side, symbol_snapshot)

        return {
            "entry_thesis": entry_thesis,
            "still_supported": still_supported,
            "invalidated": invalidation_reason is not None,
            "invalidation_reason": invalidation_reason,
        }

    def _base_asset(self, symbol: str) -> str:
        return symbol.split("/", 1)[0].split(":", 1)[0].strip().upper()

    def _correlated_directional_group(self, symbol: str) -> str | None:
        base_asset = self._base_asset(symbol)
        for group_name, members in CORRELATED_DIRECTIONAL_GROUPS.items():
            if base_asset in members:
                return group_name
        return None

    def _is_alt_short_tighten_symbol(self, symbol: str) -> bool:
        return self._base_asset(symbol) in ALT_SHORT_TIGHTEN_BASES

    def _closed_position_direction(self, position_side_before_action: str | None) -> int | None:
        if position_side_before_action == "long":
            return 1
        if position_side_before_action == "short":
            return -1
        return None

    def _position_notional_quote(self, position) -> float:
        return abs(float(position.notional_quote or position.market_value_quote or 0.0))

    def _directional_exposure_denominator(self, bundle: MarketSnapshotBundle) -> float:
        leverage = float(self.settings.contract_leverage) if self.settings.contract_market else 1.0
        return max(float(bundle.account.equity_quote) * leverage, 1e-9)

    def _portfolio_open_context(
        self,
        *,
        symbol: str,
        action: str,
        bundle: MarketSnapshotBundle,
        current_position,
        final_size_pct: float,
        desired_direction: int | None,
    ) -> dict[str, object] | None:
        if action not in {"buy", "sell"} or desired_direction not in {-1, 1}:
            return None

        target_side = "long" if desired_direction > 0 else "short"
        target_group = self._correlated_directional_group(symbol)
        denominator = self._directional_exposure_denominator(bundle)
        leverage = float(self.settings.contract_leverage) if self.settings.contract_market else 1.0
        projected_open_notional_quote = max(float(bundle.account.equity_quote) * max(final_size_pct, 0.0) * leverage, 0.0)

        same_direction_positions = [
            position
            for position in bundle.account.open_positions
            if position.side == target_side
        ]
        same_direction_symbols = [position.symbol for position in same_direction_positions]
        same_direction_notional_quote = sum(self._position_notional_quote(position) for position in same_direction_positions)
        projected_same_direction_positions = len(same_direction_positions)
        if current_position is None or current_position.side != target_side:
            projected_same_direction_positions += 1

        correlated_positions = [
            position
            for position in same_direction_positions
            if target_group is not None and self._correlated_directional_group(position.symbol) == target_group
        ]
        correlated_symbols = [position.symbol for position in correlated_positions]
        correlated_notional_quote = sum(self._position_notional_quote(position) for position in correlated_positions)
        projected_correlated_positions = len(correlated_positions)
        if target_group is not None and (current_position is None or current_position.side != target_side):
            projected_correlated_positions += 1

        return {
            "target_side": target_side,
            "target_group": target_group,
            "current_same_direction_positions": len(same_direction_positions),
            "projected_same_direction_positions": projected_same_direction_positions,
            "current_same_direction_symbols": same_direction_symbols,
            "projected_same_direction_exposure_pct": (same_direction_notional_quote + projected_open_notional_quote) / denominator,
            "current_same_direction_exposure_pct": same_direction_notional_quote / denominator,
            "current_same_direction_notional_quote": same_direction_notional_quote,
            "projected_open_notional_quote": projected_open_notional_quote,
            "current_correlated_positions": len(correlated_positions),
            "projected_correlated_positions": projected_correlated_positions,
            "current_correlated_symbols": correlated_symbols,
            "current_correlated_exposure_pct": correlated_notional_quote / denominator,
            "projected_correlated_exposure_pct": (
                None
                if target_group is None
                else (correlated_notional_quote + projected_open_notional_quote) / denominator
            ),
            "current_correlated_notional_quote": correlated_notional_quote,
            "third_same_direction_edge_buffer_pct": (
                self.settings.third_same_direction_edge_buffer_pct
                if current_position is None and projected_same_direction_positions >= 3
                else 0.0
            ),
        }

    def _portfolio_exposure_reasons(self, portfolio_context: dict[str, object] | None) -> list[str]:
        if not portfolio_context:
            return []

        reasons: list[str] = []
        projected_same_direction_exposure_pct = float(portfolio_context.get("projected_same_direction_exposure_pct") or 0.0)
        if projected_same_direction_exposure_pct > self.settings.max_net_directional_exposure_pct:
            reasons.append(
                "portfolio_net_directional_exposure_limit:"
                f"{portfolio_context.get('target_side')}:{projected_same_direction_exposure_pct:.6f}"
                f">{self.settings.max_net_directional_exposure_pct:.6f}"
            )

        projected_correlated_exposure_pct = portfolio_context.get("projected_correlated_exposure_pct")
        if (
            projected_correlated_exposure_pct is not None
            and float(projected_correlated_exposure_pct) > self.settings.max_correlated_directional_exposure_pct
        ):
            reasons.append(
                "portfolio_correlated_directional_exposure_limit:"
                f"{portfolio_context.get('target_group')}:{portfolio_context.get('target_side')}:"
                f"{float(projected_correlated_exposure_pct):.6f}"
                f">{self.settings.max_correlated_directional_exposure_pct:.6f}"
            )

        return reasons

    def _is_forced_loss_close(self, action_item: dict | None, desired_direction: int | None) -> bool:
        if action_item is None or desired_direction is None:
            return False
        previous_direction = self._closed_position_direction(action_item.get("position_side_before_action"))
        if previous_direction is None or previous_direction != desired_direction:
            return False
        risk_reasons = [str(reason) for reason in (action_item.get("risk_reasons") or [])]
        return any(
            reason == "management_adverse_hold_to_close" or reason.startswith("management_stop_loss_hit:")
            for reason in risk_reasons
        )

    def _loss_reentry_cooldown_bars(self) -> int:
        return max(
            self.settings.same_symbol_reentry_cooldown_bars,
            self.settings.same_symbol_reentry_cooldown_bars + self.settings.cooldown_bars_after_losses,
        )

    def _position_return_pct(self, position, symbol_snapshot) -> float | None:
        if position is None or symbol_snapshot is None:
            return None
        entry_price = float(position.average_entry_price or 0.0)
        last_price = float(symbol_snapshot.last_price or 0.0)
        if entry_price <= 0.0 or last_price <= 0.0:
            return None
        raw_return_pct = (last_price / entry_price) - 1.0
        if position.side == "long":
            return raw_return_pct
        if position.side == "short":
            return -raw_return_pct
        return None

    def _preview_action_from_candidate_context(self, candidate_context: dict[str, object] | None, symbol_snapshot) -> str | None:
        if not isinstance(candidate_context, dict) or symbol_snapshot is None:
            return None
        if bool(candidate_context.get("manage_only")):
            return None
        entry_thesis_candidate = candidate_context.get("entry_thesis_candidate")
        if isinstance(entry_thesis_candidate, dict):
            direction = str(entry_thesis_candidate.get("direction") or "")
            if direction == "long":
                return "buy"
            if direction == "short":
                return "sell"
        setup_phase = str(candidate_context.get("setup_phase") or "")
        if setup_phase.startswith("long_"):
            return "buy"
        if setup_phase.startswith("short_"):
            return "sell"
        higher = symbol_snapshot.higher_timeframe or {}
        trend_direction = higher.get("trend_direction")
        if trend_direction is None:
            trend_direction = higher.get("trend_bias")
        if trend_direction == "long":
            return "buy"
        if trend_direction == "short":
            return "sell"
        return None

    def _preview_entry_size_pct(self) -> float:
        target_size_pct = max(float(self.settings.min_open_size_pct), 0.10)
        return min(target_size_pct, float(self.settings.max_entry_size_pct))

    def entry_viability_preview(
        self,
        *,
        bundle: MarketSnapshotBundle,
        symbol_snapshot,
        candidate_context: dict[str, object] | None,
    ) -> dict[str, object] | None:
        action = self._preview_action_from_candidate_context(candidate_context, symbol_snapshot)
        if action not in {"buy", "sell"} or symbol_snapshot is None:
            return None

        preview_size_pct = self._preview_entry_size_pct()
        if preview_size_pct <= 0.0:
            return None
        preview_validated = ValidatedDecision(
            decision=AIDecision(
                timestamp=utc_now().isoformat(),
                symbol=symbol_snapshot.symbol,
                action=action,
                size_pct=preview_size_pct,
                take_profit_pct=max(float(self.settings.min_take_profit_pct), 0.02),
                stop_loss_pct=max(float(self.settings.min_effective_stop_loss_pct), 0.01),
                ttl_minutes=30,
                confidence=0.0,
                reason="candidate_entry_viability_preview",
                prompt_version="preview",
            ),
            valid=True,
            errors=[],
            raw_payload=None,
        )
        fresh_entry_assessment = assess_fresh_entry(symbol_snapshot, action=action)
        expected_edge_components = self._expected_edge_breakdown(
            preview_validated,
            symbol_snapshot,
            include_fresh_entry_bias=True,
        )
        current_position = next(
            (position for position in bundle.account.open_positions if position.symbol == symbol_snapshot.symbol),
            None,
        )
        desired_direction = action_direction(
            action,
            contract_market=self.settings.contract_market,
            position_side=None if current_position is None else current_position.side,
        )
        portfolio_context = self._portfolio_open_context(
            symbol=symbol_snapshot.symbol,
            action=action,
            bundle=bundle,
            current_position=current_position,
            final_size_pct=preview_size_pct,
            desired_direction=desired_direction,
        )
        threshold_buffer_pct = 0.0 if portfolio_context is None else float(
            portfolio_context.get("third_same_direction_edge_buffer_pct") or 0.0
        )
        weak_same_direction_buffer_pct = self._weak_same_direction_short_edge_buffer_pct(
            action=action,
            symbol_snapshot=symbol_snapshot,
            has_position=current_position is not None,
            fresh_entry_assessment=fresh_entry_assessment,
            portfolio_context=portfolio_context,
        )
        required_expected_edge_pct = (
            self.settings.min_expected_edge_pct
            + threshold_buffer_pct
            + weak_same_direction_buffer_pct
        )
        final_expected_edge_pct = float(expected_edge_components["final_expected_edge_pct"])
        edge_surplus_pct = final_expected_edge_pct - required_expected_edge_pct
        portfolio_pressure = None
        if portfolio_context is not None:
            portfolio_pressure = {
                "current_same_direction_positions": int(portfolio_context.get("current_same_direction_positions") or 0),
                "projected_same_direction_positions": int(portfolio_context.get("projected_same_direction_positions") or 0),
                "projected_same_direction_exposure_pct": float(
                    portfolio_context.get("projected_same_direction_exposure_pct") or 0.0
                ),
                "current_correlated_positions": int(portfolio_context.get("current_correlated_positions") or 0),
                "projected_correlated_positions": int(portfolio_context.get("projected_correlated_positions") or 0),
                "projected_correlated_exposure_pct": (
                    None
                    if portfolio_context.get("projected_correlated_exposure_pct") is None
                    else float(portfolio_context.get("projected_correlated_exposure_pct") or 0.0)
                ),
            }
        return {
            "preview_action": action,
            "assumed_size_pct": preview_size_pct,
            "entry_archetype": self._entry_archetype(
                action,
                symbol_snapshot,
                has_position=current_position is not None,
                fresh_entry_assessment=fresh_entry_assessment,
            ),
            "shadow_open_signal_reasons": self._open_signal_reasons(action, symbol_snapshot),
            "expected_edge": {
                "projected_move_pct": float(expected_edge_components["projected_move_pct"]),
                "estimated_cost_pct": float(expected_edge_components["estimated_cost_pct"]),
                "final_expected_edge_pct": final_expected_edge_pct,
                "base_threshold_pct": float(self.settings.min_expected_edge_pct),
                "required_threshold_pct": required_expected_edge_pct,
                "required_threshold_gap_pct": required_expected_edge_pct - final_expected_edge_pct,
                "edge_surplus_pct": edge_surplus_pct,
            },
            "portfolio_pressure": portfolio_pressure,
        }

    def _should_force_trailing_profit_close(
        self,
        *,
        symbol: str,
        last_open: dict | None,
        current_position_return_pct: float | None,
    ) -> tuple[bool, float | None, float | None]:
        if last_open is None or current_position_return_pct is None:
            return False, None, None
        open_run_id = int(last_open.get("run_id") or 0)
        if open_run_id <= 0:
            return False, None, None
        peak_key = self._trailing_profit_peak_key(symbol, open_run_id)
        previous_peak = float(self.journal.get_runtime_state(peak_key, current_position_return_pct) or current_position_return_pct)
        peak_return_pct = max(previous_peak, current_position_return_pct)
        if peak_return_pct != previous_peak:
            self.journal.set_runtime_state(peak_key, peak_return_pct)
        if peak_return_pct < self.settings.trailing_profit_arm_pct:
            return False, peak_return_pct, None
        retrace_pct = peak_return_pct - current_position_return_pct
        if retrace_pct < self.settings.trailing_profit_retrace_pct:
            return False, peak_return_pct, retrace_pct
        return True, peak_return_pct, retrace_pct

    def _should_close_profitable_long_on_cooling_momentum(
        self,
        *,
        current_position,
        symbol_snapshot,
        current_position_return_pct: float | None,
    ) -> bool:
        if current_position is None or symbol_snapshot is None or current_position.side != "long":
            return False
        if current_position_return_pct is None:
            return False
        if current_position_return_pct < MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MIN_POSITION_RETURN_PCT:
            return False

        indicators = symbol_snapshot.indicators
        higher = symbol_snapshot.higher_timeframe or {}
        if higher.get("trend_bias") != "long":
            return False
        if float(higher.get("rsi_14") or 0.0) < MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MIN_HIGHER_RSI:
            return False
        if float(indicators.get("return_24bars") or 0.0) < MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MIN_24BAR_RETURN_PCT:
            return False
        if float(indicators.get("rsi_14") or 50.0) > MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MAX_LOCAL_RSI:
            return False
        if float(indicators.get("return_1bar") or 0.0) > MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MAX_1BAR_RETURN_PCT:
            return False
        return True

    def _eth_short_management_setup_phase(self, symbol_snapshot) -> str | None:
        if symbol_snapshot is None:
            return None
        setup_phase = str(assess_fresh_entry(symbol_snapshot, action="sell").setup_phase or "")
        return setup_phase or None

    def _should_preserve_profitable_eth_reclaim_short(
        self,
        *,
        entry_thesis: dict[str, object],
        symbol_snapshot,
        current_position_return_pct: float | None,
    ) -> bool:
        if symbol_snapshot is None or symbol_snapshot.symbol != "ETH/USDT:USDT":
            return False
        if current_position_return_pct is None or current_position_return_pct <= 0.0:
            return False
        if str(entry_thesis.get("direction") or "") != "short":
            return False
        if str(entry_thesis.get("higher_timeframe_phase") or "") not in {"reclaim", "trend"}:
            return False
        if str(entry_thesis.get("setup_phase") or "") not in {
            "short_rebound_fail_confirmed",
            "short_continuation_confirmed",
        }:
            return False

        higher = symbol_snapshot.higher_timeframe or {}
        if str(higher.get("trend_bias") or "") != "short":
            return False
        if str(higher.get("trend_phase") or "") not in {"reclaim", "trend", "exhaustion"}:
            return False

        indicators = symbol_snapshot.indicators
        return_1bar = float(indicators.get("return_1bar") or 0.0)
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
        sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
        rsi_14 = float(indicators.get("rsi_14") or 50.0)
        volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
        if sma_slow_ratio >= 0.0:
            return False

        strong_reversal = (
            (
                sma_fast_ratio >= 0.0
                and rsi_14 >= ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_RSI
                and return_1bar >= ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_1BAR_PCT
            )
            or (
                return_1bar >= ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_1BAR_PCT
                and volume_ratio >= ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_VOLUME_RATIO
                and rsi_14 >= 48.0
            )
        )
        if strong_reversal:
            return False

        current_short_assessment = assess_fresh_entry(symbol_snapshot, action="sell")
        if current_short_assessment.setup_phase in {
            "short_rebound_fail_confirmed",
            "short_breakdown_confirmed",
            "short_continuation_confirmed",
        } and not current_short_assessment.terminal_extension:
            return True

        current_traditional_context = build_traditional_signal_context(
            symbol_snapshot,
            current_short_assessment,
        )
        if isinstance(current_traditional_context, dict) and not bool(current_traditional_context.get("terminal_risk")):
            pattern_label = str(current_traditional_context.get("pattern_label") or "")
            conviction_score = float(current_traditional_context.get("conviction_score") or 0.0)
            rebound_failure_pct = float(current_traditional_context.get("rebound_failure_pct") or 0.0)
            support_break_pct = float(current_traditional_context.get("support_break_pct") or 0.0)
            if (
                pattern_label in {"failed_rebound_breakdown", "fresh_support_break"}
                and conviction_score >= ETH_RECLAIM_SHORT_HOLD_MIN_CONVICTION_SCORE
                and (
                    rebound_failure_pct >= ETH_RECLAIM_SHORT_HOLD_MIN_REBOUND_FAILURE_PCT
                    or support_break_pct >= ETH_RECLAIM_SHORT_HOLD_MIN_SUPPORT_BREAK_PCT
                )
            ):
                return True

        return (
            return_24bars <= 0.0
            and volume_ratio >= ETH_RECLAIM_SHORT_HOLD_MIN_VOLUME_RATIO
            and rsi_14 <= ETH_RECLAIM_SHORT_HOLD_MAX_LOCAL_RSI
            and sma_fast_ratio <= ETH_RECLAIM_SHORT_HOLD_MAX_FAST_SMA_RATIO
            and return_1bar <= ETH_RECLAIM_SHORT_HOLD_MAX_RETURN_1BAR_PCT
        )

    def _should_preserve_profitable_eth_continuation_short_weak_rebound(
        self,
        *,
        entry_thesis: dict[str, object],
        symbol_snapshot,
        current_position_return_pct: float | None,
    ) -> bool:
        if symbol_snapshot is None or symbol_snapshot.symbol != "ETH/USDT:USDT":
            return False
        if current_position_return_pct is None or current_position_return_pct < self.settings.trailing_profit_arm_pct:
            return False
        if str(entry_thesis.get("direction") or "") != "short":
            return False
        if str(entry_thesis.get("setup_phase") or "") != "short_continuation_confirmed":
            return False
        if str(entry_thesis.get("higher_timeframe_phase") or "") not in {"reclaim", "trend"}:
            return False

        higher = symbol_snapshot.higher_timeframe or {}
        if str(higher.get("trend_bias") or "") != "short":
            return False
        if str(higher.get("trend_phase") or "") not in {"reclaim", "trend", "exhaustion"}:
            return False

        indicators = symbol_snapshot.indicators
        return_1bar = float(indicators.get("return_1bar") or 0.0)
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
        sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
        rsi_14 = float(indicators.get("rsi_14") or 50.0)
        volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)

        strong_reversal = (
            sma_slow_ratio >= 0.0
            or (
                sma_fast_ratio > ETH_CONTINUATION_SHORT_WEAK_REBOUND_MAX_FAST_SMA_RATIO
                and rsi_14 >= ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_RSI
            )
            or (
                return_1bar >= ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_1BAR_PCT
                and volume_ratio >= ETH_RECLAIM_SHORT_STRONG_REVERSAL_MIN_VOLUME_RATIO
                and rsi_14 >= 48.0
            )
        )
        if strong_reversal:
            return False

        return (
            return_24bars <= ETH_CONTINUATION_SHORT_WEAK_REBOUND_MAX_24BAR_RETURN_PCT
            and sma_fast_ratio <= ETH_CONTINUATION_SHORT_WEAK_REBOUND_MAX_FAST_SMA_RATIO
            and rsi_14 <= ETH_CONTINUATION_SHORT_WEAK_REBOUND_MAX_LOCAL_RSI
        )

    def _should_reject_eth_short_ai_close_for_exhaustion_breakdown_flush(
        self,
        *,
        symbol: str,
        decision_action: str,
        current_position,
        symbol_snapshot,
        current_position_return_pct: float | None,
        management_signal: str | None,
    ) -> bool:
        if decision_action != "close" or symbol != "ETH/USDT:USDT":
            return False
        if current_position is None or current_position.side != "short" or symbol_snapshot is None:
            return False
        if current_position_return_pct is None or current_position_return_pct < ETH_SHORT_CLOSE_REJECT_MIN_POSITION_RETURN_PCT:
            return False
        if management_signal == "adverse":
            return False
        higher = symbol_snapshot.higher_timeframe or {}
        if str(higher.get("trend_phase") or "") != "exhaustion":
            return False
        setup_phase = self._eth_short_management_setup_phase(symbol_snapshot)
        if setup_phase != "short_breakdown_chase":
            return False
        indicators = symbol_snapshot.indicators
        if float(indicators.get("sma_fast_ratio") or 0.0) >= 0.0:
            return False
        if float(indicators.get("volume_ratio_20") or 0.0) < ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MIN_VOLUME_RATIO:
            return False
        if float(indicators.get("range_pct") or 0.0) < ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MIN_RANGE_PCT:
            return False
        extreme_distance = abs(float(higher.get("distance_from_12bar_extreme") or 0.0))
        if extreme_distance > ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MAX_EXTREME_DISTANCE_PCT:
            return False
        if float(indicators.get("return_1bar") or 0.0) > -ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MIN_1BAR_PCT:
            return False
        if float(indicators.get("rsi_14") or 50.0) > ETH_SHORT_AI_CLOSE_EXHAUSTION_FLUSH_MAX_LOCAL_RSI:
            return False
        return True

    def _should_reject_eth_short_ai_close_for_exhaustion_range_noise(
        self,
        *,
        symbol: str,
        decision_action: str,
        current_position,
        symbol_snapshot,
        current_position_return_pct: float | None,
        management_signal: str | None,
    ) -> bool:
        if decision_action != "close" or symbol != "ETH/USDT:USDT":
            return False
        if current_position is None or current_position.side != "short" or symbol_snapshot is None:
            return False
        if current_position_return_pct is None or current_position_return_pct < ETH_SHORT_CLOSE_REJECT_MIN_POSITION_RETURN_PCT:
            return False
        if management_signal == "adverse":
            return False
        higher = symbol_snapshot.higher_timeframe or {}
        if str(higher.get("trend_bias") or "") != "short":
            return False
        if str(higher.get("trend_phase") or "") != "exhaustion":
            return False
        if self._eth_short_management_setup_phase(symbol_snapshot) != "range_noise":
            return False

        indicators = symbol_snapshot.indicators
        return_1bar = float(indicators.get("return_1bar") or 0.0)
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
        sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
        rsi_14 = float(indicators.get("rsi_14") or 50.0)
        if sma_slow_ratio >= 0.0:
            return False
        if return_24bars > -ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MIN_DIRECTIONAL_24BAR_PCT:
            return False
        if return_1bar >= ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MAX_REBOUND_1BAR_PCT:
            return False
        if sma_fast_ratio > ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MAX_FAST_SMA_RATIO:
            return False
        if rsi_14 > ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MAX_LOCAL_RSI:
            return False
        extreme_distance = higher.get("distance_from_12bar_extreme")
        if extreme_distance is not None and abs(float(extreme_distance)) > ETH_SHORT_AI_CLOSE_EXHAUSTION_RANGE_NOISE_MAX_EXTREME_DISTANCE_PCT:
            return False
        return True

    def _should_reject_eth_short_ai_close_for_trend_range_noise(
        self,
        *,
        symbol: str,
        decision_action: str,
        current_position,
        symbol_snapshot,
        current_position_return_pct: float | None,
        management_signal: str | None,
    ) -> bool:
        if decision_action != "close" or symbol != "ETH/USDT:USDT":
            return False
        if current_position is None or current_position.side != "short" or symbol_snapshot is None:
            return False
        if management_signal == "adverse":
            return False
        if current_position_return_pct is None or current_position_return_pct < -ETH_SHORT_AI_CLOSE_REJECT_MAX_POSITION_LOSS_PCT:
            return False
        higher = symbol_snapshot.higher_timeframe or {}
        if str(higher.get("trend_bias") or "") != "short":
            return False
        if str(higher.get("trend_phase") or "") != "trend":
            return False
        if self._eth_short_management_setup_phase(symbol_snapshot) != "range_noise":
            return False
        if current_position_return_pct > ETH_SHORT_CLOSE_REJECT_MIN_POSITION_RETURN_PCT:
            return False
        indicators = symbol_snapshot.indicators
        strong_rebound_bar = (
            float(indicators.get("return_1bar") or 0.0) >= ETH_SHORT_AI_CLOSE_STRONG_REBOUND_MIN_1BAR_PCT
            and float(indicators.get("volume_ratio_20") or 0.0) >= ETH_SHORT_AI_CLOSE_STRONG_REBOUND_MIN_VOLUME_RATIO
        )
        strong_reversal = (
            float(indicators.get("sma_slow_ratio") or 0.0) >= 0.0
            or strong_rebound_bar
            or (
                float(indicators.get("sma_fast_ratio") or 0.0) >= 0.0
                and (
                    float(indicators.get("rsi_14") or 50.0) >= 55.0
                    or (
                        float(indicators.get("volume_ratio_20") or 0.0) >= 1.0
                        and float(indicators.get("return_1bar") or 0.0) >= MANAGEMENT_ADVERSE_MIN_1BAR_PCT
                    )
                )
            )
        )
        return not strong_reversal

    def evaluate(self, validated: ValidatedDecision, bundle: MarketSnapshotBundle) -> RiskVerdict:
        decision = validated.decision
        reasons: list[str] = []
        approved = True
        final_action = decision.action
        bottom_line_rules = self.settings.bottom_line_rules
        final_size_pct = min(max(decision.size_pct, 0.0), self.settings.max_entry_size_pct)
        leverage = float(self.settings.contract_leverage)
        if is_open_action(decision.action, self.settings.contract_market):
            min_take_profit_pct = 0.0 if bottom_line_rules else self.settings.min_take_profit_pct
            stop_loss_floor_pct = max(float(self.settings.min_effective_stop_loss_pct), 0.0)
            stop_loss_cap_pct = max(float(self.settings.max_effective_stop_loss_pct), stop_loss_floor_pct)
            take_profit_pct = min(max(decision.take_profit_pct, min_take_profit_pct), 0.05)
            stop_loss_pct = min(max(decision.stop_loss_pct, stop_loss_floor_pct), stop_loss_cap_pct)
        else:
            take_profit_pct = max(decision.take_profit_pct, 0.0)
            stop_loss_pct = max(decision.stop_loss_pct, 0.0)

        if not validated.valid:
            reasons.extend(validated.errors)
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        date_key = utc_now().date().isoformat()
        # Keep paper/live day baselines isolated so a paper bankroll cannot halt live trading.
        day_start_key = build_day_start_equity_key(
            self.settings.mode,
            self.settings.exchange_id,
            self.settings.market_type,
            self.settings.quote_currency,
            date_key,
        )
        day_start_equity = self.journal.get_runtime_state(day_start_key, None)
        if day_start_equity is None:
            self.journal.set_runtime_state(day_start_key, bundle.account.equity_quote)
            day_start_equity = bundle.account.equity_quote
        if day_start_equity > 0:
            drawdown_pct = (bundle.account.equity_quote - float(day_start_equity)) / float(day_start_equity)
            if drawdown_pct <= -self.settings.daily_loss_limit_pct:
                reasons.append("daily_loss_limit_reached")
                approved = False
                final_action = "hold"
                final_size_pct = 0.0

        if self.journal.get_runtime_state("halted", False):
            reasons.append("system_halted")
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        positions = {position.symbol: position for position in bundle.account.open_positions}
        current_position = positions.get(decision.symbol)
        has_position = current_position is not None
        position_count = len(positions)
        symbol_snapshot = self._symbol_snapshot(bundle, decision.symbol)
        exchange_min_cost_quote = float(symbol_snapshot.exchange_min_cost_quote or 0.0) if symbol_snapshot is not None else 0.0
        configured_min_entry_quote = self.settings.min_notional_quote * leverage if self.settings.contract_market else self.settings.min_notional_quote
        exchange_min_notional = max(
            configured_min_entry_quote,
            exchange_min_cost_quote,
        )
        if symbol_snapshot is not None:
            exchange_min_notional = max(
                exchange_min_notional,
                minimum_executable_notional(
                    price=symbol_snapshot.last_price,
                    min_cost=exchange_min_cost_quote,
                    min_amount=float(symbol_snapshot.exchange_min_amount or 0.0),
                    amount_step=symbol_snapshot.exchange_amount_step,
                ),
            )

        if self.journal.get_consecutive_losses(decision.symbol, limit=2) >= 2 and not bottom_line_rules:
            reasons.append("recent_loss_streak")
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        current_entry_ts = None if symbol_snapshot is None else symbol_snapshot.recent_candles[-1].timestamp_ms
        history = self._recent_symbol_history(decision.symbol)
        last_action = self._last_matching_action(history, lambda item: item.get("final_action") != "hold")
        last_open = self._last_matching_action(history, lambda item: is_open_action(str(item.get("final_action") or "hold"), self.settings.contract_market))
        last_close = self._last_matching_action(history, lambda item: str(item.get("final_action") or "hold") == "close")
        bars_since_open = None
        if current_entry_ts is not None and last_open is not None:
            bars_since_open = self._bars_since(current_entry_ts, last_open.get("bar_timestamp_ms"))
        management_signal = self._management_signal(None if current_position is None else current_position.side, symbol_snapshot)
        current_position_return_pct = self._position_return_pct(current_position, symbol_snapshot)
        forced_management_exit = False
        close_fraction = 1.0
        management_open_run_id: int | None = None
        remaining_take_profit_price: float | None = None
        remaining_stop_price: float | None = None
        protective_refresh_only = False
        protective_refresh_reason: str | None = None
        risk_debug: dict[str, object] | None = None
        fresh_entry_assessment = None
        entry_thesis: dict[str, object] | None = None
        if is_open_action(final_action, self.settings.contract_market) and not has_position:
            fresh_entry_assessment = assess_fresh_entry(symbol_snapshot, action=final_action) if symbol_snapshot is not None else None
            entry_thesis = self._entry_thesis(
                validated=validated,
                action=final_action,
                symbol_snapshot=symbol_snapshot,
                fresh_entry_assessment=fresh_entry_assessment,
            )
        if is_open_action(final_action, self.settings.contract_market):
            expected_edge_breakdown = self._expected_edge_breakdown(
                validated,
                symbol_snapshot,
                include_fresh_entry_bias=not has_position,
            )
            risk_debug = {
                "entry_archetype": self._entry_archetype(
                    final_action,
                    symbol_snapshot,
                    has_position=has_position,
                    fresh_entry_assessment=fresh_entry_assessment,
                ),
                "expected_edge_components": expected_edge_breakdown,
                "shadow_open_signal_reasons": self._open_signal_reasons(final_action, symbol_snapshot),
                "fresh_entry_context": (
                    None
                    if fresh_entry_assessment is None
                    else {
                        "continuation_watch": fresh_entry_assessment.continuation_watch,
                        "terminal_extension": fresh_entry_assessment.terminal_extension,
                        "setup_phase": fresh_entry_assessment.setup_phase,
                        "setup_confirmed": fresh_entry_assessment.setup_confirmed,
                        "higher_timeframe_phase": (
                            None
                            if symbol_snapshot is None
                            else (symbol_snapshot.higher_timeframe or {}).get("trend_phase")
                        ),
                        "candidate_reasons": list(fresh_entry_assessment.candidate_reasons),
                        "risk_reasons": list(fresh_entry_assessment.risk_reasons),
                    }
                ),
                "entry_thesis": entry_thesis,
                "portfolio_context": None,
            }

        desired_direction = action_direction(
            final_action,
            contract_market=self.settings.contract_market,
            position_side=None if current_position is None else current_position.side,
        )
        required_expected_edge_pct = self.settings.min_expected_edge_pct
        if is_open_action(final_action, self.settings.contract_market):
            portfolio_context = self._portfolio_open_context(
                symbol=decision.symbol,
                action=final_action,
                bundle=bundle,
                current_position=current_position,
                final_size_pct=final_size_pct,
                desired_direction=desired_direction,
            )
            threshold_buffer_pct = 0.0 if portfolio_context is None else float(
                portfolio_context.get("third_same_direction_edge_buffer_pct") or 0.0
            )
            weak_same_direction_buffer_pct = self._weak_same_direction_short_edge_buffer_pct(
                action=final_action,
                symbol_snapshot=symbol_snapshot,
                has_position=has_position,
                fresh_entry_assessment=fresh_entry_assessment,
                portfolio_context=portfolio_context,
            )
            required_expected_edge_pct = (
                self.settings.min_expected_edge_pct
                + threshold_buffer_pct
                + weak_same_direction_buffer_pct
            )
            if risk_debug is not None:
                risk_debug["portfolio_context"] = portfolio_context
                if isinstance(risk_debug.get("expected_edge_components"), dict):
                    expected_edge_components = dict(risk_debug["expected_edge_components"])
                    expected_edge_components["base_threshold_pct"] = self.settings.min_expected_edge_pct
                    expected_edge_components["portfolio_threshold_buffer_pct"] = threshold_buffer_pct
                    expected_edge_components["weak_same_direction_edge_buffer_pct"] = weak_same_direction_buffer_pct
                    expected_edge_components["required_threshold_pct"] = required_expected_edge_pct
                    expected_edge_components["required_threshold_gap_pct"] = (
                        required_expected_edge_pct - float(expected_edge_components["final_expected_edge_pct"])
                    )
                    risk_debug["expected_edge_components"] = expected_edge_components

        if (
            approved
            and has_position
            and current_position_return_pct is not None
            and last_open is not None
            and final_action != "close"
        ):
            take_profit_threshold = max(float(last_open.get("take_profit_pct") or 0.0), 0.0)
            stop_loss_threshold = max(float(last_open.get("stop_loss_pct") or 0.0), 0.0)
            if stop_loss_threshold > 0.0 and current_position_return_pct <= -stop_loss_threshold:
                reasons.append(
                    f"management_stop_loss_hit:{current_position_return_pct:.6f}<=-{stop_loss_threshold:.6f}"
                )
                final_action = "close"
                final_size_pct = 0.0
                forced_management_exit = True
            else:
                partial_take_profit_applied = False
                partial_take_profit_count = 0
                (
                    should_partial_take_profit,
                    partial_open_run_id,
                    next_partial_take_profit_trigger_pct,
                    partial_take_profit_count,
                ) = self._should_partial_take_profit(
                    symbol=decision.symbol,
                    last_open=last_open,
                    current_position_return_pct=current_position_return_pct,
                    management_signal=management_signal,
                )
                if should_partial_take_profit and current_position is not None:
                    close_fraction = min(max(self.settings.partial_take_profit_fraction, 0.0), 1.0)
                    if 0.0 < close_fraction < 1.0:
                        min_amount = float(symbol_snapshot.exchange_min_amount or 0.0) if symbol_snapshot is not None else 0.0
                        close_quantity = float(current_position.quantity) * close_fraction
                        remaining_quantity = float(current_position.quantity) - close_quantity
                        if min_amount > 0.0 and (close_quantity < min_amount or remaining_quantity < min_amount):
                            reasons.append("partial_take_profit_skipped_below_min_amount")
                            close_fraction = 1.0
                        else:
                            average_entry_price = float(current_position.average_entry_price or 0.0)
                            peak_key = self._trailing_profit_peak_key(decision.symbol, int(partial_open_run_id or 0))
                            previous_peak = float(
                                self.journal.get_runtime_state(peak_key, current_position_return_pct) or current_position_return_pct
                            )
                            peak_return_pct = max(previous_peak, current_position_return_pct)
                            if partial_open_run_id:
                                self.journal.set_runtime_state(peak_key, peak_return_pct)
                            next_partial_count = partial_take_profit_count + 1
                            trailing_stop_price = self._trailing_stop_price(
                                position_side=current_position.side,
                                entry_price=average_entry_price,
                                peak_return_pct=peak_return_pct,
                            )
                            remaining_take_profit_price, remaining_stop_price = self._remaining_protective_prices(
                                position_side=current_position.side,
                                entry_price=average_entry_price,
                                take_profit_pct=take_profit_threshold,
                                take_profit_enabled=False,
                            )
                            if trailing_stop_price is not None:
                                if current_position.side == "long":
                                    remaining_stop_price = max(float(remaining_stop_price or 0.0), trailing_stop_price)
                                else:
                                    if remaining_stop_price is None or trailing_stop_price < remaining_stop_price:
                                        remaining_stop_price = trailing_stop_price
                            management_open_run_id = partial_open_run_id
                            reasons.append(
                                f"partial_take_profit:{current_position_return_pct:.6f}>={float(next_partial_take_profit_trigger_pct or 0.0):.6f}|fraction={close_fraction:.4f}|count={next_partial_count}"
                            )
                            final_action = "close"
                            final_size_pct = 0.0
                            forced_management_exit = True
                            partial_take_profit_applied = True
                if (
                    not partial_take_profit_applied
                    and partial_take_profit_count == 0
                    and take_profit_threshold > 0.0
                    and current_position_return_pct >= take_profit_threshold
                ):
                    reasons.append(
                        f"management_take_profit_hit:{current_position_return_pct:.6f}>={take_profit_threshold:.6f}"
                    )
                    final_action = "close"
                    final_size_pct = 0.0
                    forced_management_exit = True

        if (
            approved
            and has_position
            and final_action == "hold"
            and management_signal == "adverse"
            and current_position_return_pct is not None
            and current_position_return_pct <= -MANAGEMENT_ADVERSE_LOSS_CUT_MIN_POSITION_RETURN_PCT
            and (bars_since_open is None or bars_since_open >= 1)
        ):
            reasons.append(
                "management_adverse_loss_cut:"
                f"{current_position_return_pct:.6f}<=-{MANAGEMENT_ADVERSE_LOSS_CUT_MIN_POSITION_RETURN_PCT:.6f}"
            )
            final_action = "close"
            final_size_pct = 0.0
            forced_management_exit = True

        if approved and has_position and final_action != "close":
            should_close_for_trail, peak_return_pct, retrace_pct = self._should_force_trailing_profit_close(
                symbol=decision.symbol,
                last_open=last_open,
                current_position_return_pct=current_position_return_pct,
            )
            if should_close_for_trail:
                reasons.append(
                    f"management_trailing_profit_retrace:{current_position_return_pct:.6f}|peak={peak_return_pct:.6f}|retrace={retrace_pct:.6f}"
                )
                final_action = "close"
                final_size_pct = 0.0
                forced_management_exit = True

        if (
            approved
            and has_position
            and final_action == "hold"
            and self._should_close_profitable_long_on_cooling_momentum(
                current_position=current_position,
                symbol_snapshot=symbol_snapshot,
                current_position_return_pct=current_position_return_pct,
            )
        ):
            reasons.append("management_profitable_long_momentum_cooldown_close")
            final_action = "close"
            final_size_pct = 0.0
            forced_management_exit = True

        if (
            approved
            and has_position
            and final_action == "hold"
            and management_signal == "adverse"
            and not self._higher_timeframe_supports_position(current_position.side, symbol_snapshot)
        ):
            reasons.append("management_adverse_hold_to_close")
            final_action = "close"
            final_size_pct = 0.0

        if approved and has_position and final_action == "hold":
            (
                refresh_open_run_id,
                refresh_take_profit_price,
                refresh_stop_price,
                refresh_reason,
            ) = self._managed_protective_refresh_plan(
                symbol=decision.symbol,
                current_position=current_position,
                last_open=last_open,
                current_position_return_pct=current_position_return_pct,
            )
            if refresh_reason is not None:
                protective_refresh_only = True
                protective_refresh_reason = refresh_reason
                management_open_run_id = refresh_open_run_id
                remaining_take_profit_price = refresh_take_profit_price
                remaining_stop_price = refresh_stop_price
                reasons.append(refresh_reason)

        if approved and is_open_action(final_action, self.settings.contract_market) and not has_position and not bottom_line_rules:
            if fresh_entry_assessment and fresh_entry_assessment.terminal_extension:
                reasons.extend(fresh_entry_assessment.risk_reasons)
                approved = False
                final_action = "hold"
                final_size_pct = 0.0
            elif self._flat_bias_short_flush_blocked(final_action, symbol_snapshot):
                reasons.append("fresh_entry_flat_bias_short_flush")
                approved = False
                final_action = "hold"
                final_size_pct = 0.0
            elif self._short_exhaustion_flush_blocked(final_action, symbol_snapshot):
                reasons.append("fresh_entry_short_exhaustion_flush")
                approved = False
                final_action = "hold"
                final_size_pct = 0.0

        if approved and is_open_action(final_action, self.settings.contract_market) and not bottom_line_rules:
            cooldown_reasons = self._open_entry_cooldown_reasons(
                current_entry_ts=current_entry_ts,
                last_close=last_close,
                last_action=last_action,
                desired_direction=desired_direction,
            )
            if cooldown_reasons:
                reasons.extend(cooldown_reasons)
                approved = False
                final_action = "hold"
                final_size_pct = 0.0

        if approved and is_open_action(final_action, self.settings.contract_market) and not bottom_line_rules:
            if risk_debug and isinstance(risk_debug.get("expected_edge_components"), dict):
                expected_edge_pct = float(risk_debug["expected_edge_components"]["final_expected_edge_pct"])
            else:
                expected_edge_pct = self._expected_edge_pct(validated, symbol_snapshot)
                if not has_position:
                    expected_edge_pct += self._fresh_entry_bias_edge_adjustment_pct(final_action, symbol_snapshot)
            if expected_edge_pct < required_expected_edge_pct:
                reasons.append(
                    f"expected_edge_below_minimum:{expected_edge_pct:.6f}<{required_expected_edge_pct:.6f}"
                )
                for reason in self._open_signal_reasons(final_action, symbol_snapshot):
                    if reason not in reasons:
                        reasons.append(reason)
                approved = False
                final_action = "hold"
                final_size_pct = 0.0
            else:
                hard_signal_reasons = self._open_signal_hard_reasons(final_action, symbol_snapshot)
                if hard_signal_reasons:
                    reasons.extend(self._open_signal_reasons(final_action, symbol_snapshot))
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0

        if approved and is_open_action(final_action, self.settings.contract_market) and symbol_snapshot is not None and not bottom_line_rules:
            trend_bias = (symbol_snapshot.higher_timeframe or {}).get("trend_bias")
            if trend_bias == "long" and desired_direction == -1:
                reasons.append("higher_timeframe_trend_conflict")
                approved = False
                final_action = "hold"
                final_size_pct = 0.0
            if trend_bias == "short" and desired_direction == 1:
                reasons.append("higher_timeframe_trend_conflict")
                approved = False
                final_action = "hold"
                final_size_pct = 0.0

        if approved and final_action == "close" and not forced_management_exit and current_entry_ts is not None and last_open is not None and not bottom_line_rules:
            bars_since_open = self._bars_since(current_entry_ts, last_open.get("bar_timestamp_ms"))
            if bars_since_open is not None and bars_since_open < self.settings.min_hold_bars:
                reasons.append(f"min_hold_bars_active:{bars_since_open}<{self.settings.min_hold_bars}")
                approved = False
                final_action = "hold"
                final_size_pct = 0.0

        entry_thesis_state = (
            self._entry_thesis_state(
                current_position=current_position,
                symbol_snapshot=symbol_snapshot,
                last_open=last_open,
                bars_since_open=bars_since_open,
                current_position_return_pct=current_position_return_pct,
            )
            if has_position
            else None
        )

        if (
            approved
            and has_position
            and final_action == "hold"
            and not forced_management_exit
            and isinstance(entry_thesis_state, dict)
            and bool(entry_thesis_state.get("invalidated"))
        ):
            reasons.append(
                "management_entry_thesis_invalidated:"
                f"{entry_thesis_state.get('invalidation_reason') or 'unknown'}"
            )
            final_action = "close"
            final_size_pct = 0.0
            forced_management_exit = True

        if (
            approved
            and has_position
            and final_action == "close"
            and not forced_management_exit
            and isinstance(entry_thesis_state, dict)
            and bool(entry_thesis_state.get("still_supported"))
        ):
            reasons.append("management_close_rejected_entry_thesis_still_supported")
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        if (
            approved
            and has_position
            and final_action == "close"
            and not forced_management_exit
            and self._should_reject_eth_short_ai_close_for_trend_range_noise(
                symbol=decision.symbol,
                decision_action=decision.action,
                current_position=current_position,
                symbol_snapshot=symbol_snapshot,
                current_position_return_pct=current_position_return_pct,
                management_signal=management_signal,
            )
        ):
            reasons.append("management_close_rejected_eth_short_trend_range_noise_reversal_not_confirmed")
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        if (
            approved
            and has_position
            and final_action == "close"
            and not forced_management_exit
            and self._should_reject_eth_short_ai_close_for_exhaustion_breakdown_flush(
                symbol=decision.symbol,
                decision_action=decision.action,
                current_position=current_position,
                symbol_snapshot=symbol_snapshot,
                current_position_return_pct=current_position_return_pct,
                management_signal=management_signal,
            )
        ):
            reasons.append("management_close_rejected_eth_short_exhaustion_breakdown_flush_still_expanding")
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        if (
            approved
            and has_position
            and final_action == "close"
            and not forced_management_exit
            and self._should_reject_eth_short_ai_close_for_exhaustion_range_noise(
                symbol=decision.symbol,
                decision_action=decision.action,
                current_position=current_position,
                symbol_snapshot=symbol_snapshot,
                current_position_return_pct=current_position_return_pct,
                management_signal=management_signal,
            )
        ):
            reasons.append("management_close_rejected_eth_short_exhaustion_range_noise_reversal_not_confirmed")
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        if approved and has_position and final_action == "close" and not forced_management_exit and management_signal == "supportive" and not bottom_line_rules:
            reasons.append("management_close_rejected_position_still_supported")
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        risk_size_cap_pct: float | None = None
        if approved and is_open_action(final_action, self.settings.contract_market):
            final_size_pct = min(max(final_size_pct, 0.0), self.settings.max_entry_size_pct)
            min_open_size_pct = min(max(self.settings.min_open_size_pct, 0.0), self.settings.max_entry_size_pct)
            if final_size_pct < min_open_size_pct and not bottom_line_rules:
                final_size_pct = min_open_size_pct
                reasons.append("raised_to_min_open_size")

            risk_size_cap_pct, effective_stop_loss_pct, sizing_cost_pct = self._risk_size_cap_pct(
                final_action,
                stop_loss_pct,
            )
            if risk_size_cap_pct is not None and final_size_pct > risk_size_cap_pct:
                previous_size_pct = final_size_pct
                final_size_pct = max(risk_size_cap_pct, 0.0)
                reasons.append(
                    "risk_sized_down:"
                    f"{previous_size_pct:.6f}>{final_size_pct:.6f}"
                    f"|sl={effective_stop_loss_pct:.6f}|cost={sizing_cost_pct:.6f}"
                )
            portfolio_context = self._portfolio_open_context(
                symbol=decision.symbol,
                action=final_action,
                bundle=bundle,
                current_position=current_position,
                final_size_pct=final_size_pct,
                desired_direction=desired_direction,
            )
            if risk_debug is not None:
                risk_debug["portfolio_context"] = portfolio_context

        if self.settings.contract_market:
            if final_action in {"buy", "sell"}:
                target_side = "long" if final_action == "buy" else "short"
                if position_count >= self.settings.max_open_positions and (not has_position):
                    reasons.append("max_open_positions_reached")
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0
                elif current_position and current_position.side not in {None, target_side}:
                    reasons.append("opposite_position_open_requires_close")
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0
                available_open_notional = bundle.account.free_quote * leverage
                if available_open_notional < exchange_min_notional:
                    reasons.append("insufficient_free_quote")
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0
                if approved and bundle.account.equity_quote > 0:
                    required_size_pct = exchange_min_notional / (bundle.account.equity_quote * leverage)
                    if bundle.account.equity_quote * final_size_pct * leverage < exchange_min_notional:
                        if risk_size_cap_pct is not None and required_size_pct > risk_size_cap_pct:
                            reasons.append("risk_budget_below_exchange_minimum")
                            approved = False
                            final_action = "hold"
                            final_size_pct = 0.0
                        else:
                            final_size_pct = max(final_size_pct, required_size_pct)
                            reasons.append("raised_to_exchange_min_notional")
                if approved and bundle.account.equity_quote * final_size_pct * leverage < exchange_min_notional:
                    reasons.append("notional_below_minimum")
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0
                if approved:
                    portfolio_context = self._portfolio_open_context(
                        symbol=decision.symbol,
                        action=final_action,
                        bundle=bundle,
                        current_position=current_position,
                        final_size_pct=final_size_pct,
                        desired_direction=desired_direction,
                    )
                    if risk_debug is not None:
                        risk_debug["portfolio_context"] = portfolio_context
                    exposure_reasons = self._portfolio_exposure_reasons(portfolio_context)
                    if exposure_reasons:
                        reasons.extend(exposure_reasons)
                        approved = False
                        final_action = "hold"
                        final_size_pct = 0.0
            elif final_action == "close":
                if not has_position:
                    reasons.append("no_position_to_close")
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0
                else:
                    final_size_pct = 0.0
        else:
            if final_action == "buy":
                if position_count >= self.settings.max_open_positions and not has_position:
                    reasons.append("max_open_positions_reached")
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0
                if bundle.account.free_quote < exchange_min_notional:
                    reasons.append("insufficient_free_quote")
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0
                if approved and bundle.account.equity_quote > 0:
                    required_size_pct = exchange_min_notional / bundle.account.equity_quote
                    if bundle.account.equity_quote * final_size_pct < exchange_min_notional:
                        final_size_pct = max(final_size_pct, required_size_pct)
                        reasons.append("raised_to_exchange_min_notional")
                if bundle.account.equity_quote * final_size_pct < exchange_min_notional:
                    reasons.append("notional_below_minimum")
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0

            if final_action in {"sell", "close"}:
                if not has_position:
                    reasons.append("no_position_to_close")
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0
                else:
                    final_action = "close"
                    final_size_pct = 0.0

        status = "approved"
        if not approved:
            status = "rejected"
        elif (
            final_action != decision.action
            or abs(final_size_pct - decision.size_pct) > 1e-9
            or abs(take_profit_pct - decision.take_profit_pct) > 1e-9
            or abs(stop_loss_pct - decision.stop_loss_pct) > 1e-9
            or abs(close_fraction - 1.0) > 1e-9
            or protective_refresh_only
        ):
            status = "modified"

        if not approved or final_action == "hold":
            close_fraction = 1.0
            if not protective_refresh_only:
                management_open_run_id = None
                remaining_take_profit_price = None
                remaining_stop_price = None
                protective_refresh_reason = None
        if not approved:
            protective_refresh_only = False

        return RiskVerdict(
            status=status,
            final_action=final_action,
            symbol=decision.symbol,
            final_size_pct=final_size_pct,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            ttl_minutes=decision.ttl_minutes,
            reasons=reasons or ["ok"],
            confidence=decision.confidence,
            approved=approved,
            close_fraction=close_fraction,
            management_open_run_id=management_open_run_id,
            remaining_take_profit_price=remaining_take_profit_price,
            remaining_stop_price=remaining_stop_price,
            protective_refresh_only=protective_refresh_only,
            protective_refresh_reason=protective_refresh_reason,
            risk_debug=risk_debug,
        )
