from __future__ import annotations

from .entry_quality import assess_fresh_entry
from .exchange_utils import minimum_executable_notional
from .journal import Journal
from .models import MarketSnapshotBundle, RiskVerdict, ValidatedDecision, utc_now
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
EDGE_ATR_WEIGHT = 0.65
EDGE_RANGE_WEIGHT = 0.35
EDGE_DIRECTIONAL_WEIGHT = 0.5
EDGE_TREND_RETURN_SCALE = 0.25
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
WEAK_SAME_DIRECTION_SHORT_EDGE_BUFFER_PCT = 0.00050
FLAT_BIAS_SHORT_FLUSH_MIN_DIRECTIONAL_24BAR_PCT = 0.0100
FLAT_BIAS_SHORT_FLUSH_MIN_DIRECTIONAL_1BAR_PCT = 0.0020
FLAT_BIAS_SHORT_FLUSH_MIN_VOLUME_RATIO = 3.0
FLAT_BIAS_SHORT_FLUSH_MAX_LOCAL_RSI = 18.0
MANAGEMENT_ADVERSE_MIN_1BAR_PCT = 0.0015
MANAGEMENT_ADVERSE_MIN_24BAR_PCT = 0.0025
MANAGEMENT_SUPPORT_MIN_24BAR_PCT = 0.001
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MIN_POSITION_RETURN_PCT = 0.005
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MIN_24BAR_RETURN_PCT = 0.005
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MAX_LOCAL_RSI = 55.0
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MAX_1BAR_RETURN_PCT = 0.003
MANAGEMENT_PROFITABLE_LONG_COOLDOWN_MIN_HIGHER_RSI = 60.0
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

    def _pre_break_continuation_bonus_pct(self, action: str, symbol_snapshot) -> float:
        if action not in {"buy", "sell"} or symbol_snapshot is None:
            return 0.0
        assessment = assess_fresh_entry(symbol_snapshot, action=action)
        if not assessment.continuation_watch or assessment.terminal_extension:
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
        if self._open_signal_reasons(action, symbol_snapshot):
            return adjustments
        if entry_archetype == "plain_open":
            adjustments["weak_plain_open_short_penalty_pct"] = -WEAK_PLAIN_OPEN_SHORT_EDGE_PENALTY_PCT
        elif entry_archetype == "flat_bias_short":
            adjustments["weak_flat_bias_short_penalty_pct"] = -WEAK_FLAT_BIAS_SHORT_EDGE_PENALTY_PCT
        if self._is_alt_short_tighten_symbol(symbol_snapshot.symbol):
            if entry_archetype == "flat_bias_short":
                adjustments["alt_short_penalty_pct"] = -self.settings.alt_short_edge_penalty_pct
            elif entry_archetype == "plain_open":
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
        directional_component_pct = min(directional_signal_pct, volatility_component_pct) * EDGE_DIRECTIONAL_WEIGHT
        projected_move_pct = volatility_component_pct + directional_component_pct
        estimated_cost_pct = estimated_action_cost_pct(
            decision.decision.action,
            contract_market=self.settings.contract_market,
            fee_pct=self.settings.estimated_fee_pct,
            slippage_pct=self.settings.estimated_slippage_pct,
        )
        bonuses = {
            "countertrend_breakout_short_bonus_pct": self._countertrend_breakout_short_bonus_pct(decision.decision.action, symbol_snapshot),
            "aligned_short_continuation_bonus_pct": self._aligned_short_continuation_bonus_pct(decision.decision.action, symbol_snapshot),
            "higher_timeframe_short_reclaim_bonus_pct": self._higher_timeframe_short_reclaim_bonus_pct(decision.decision.action, symbol_snapshot),
            "pre_break_continuation_bonus_pct": self._pre_break_continuation_bonus_pct(decision.decision.action, symbol_snapshot),
            "higher_timeframe_long_reclaim_bonus_pct": self._higher_timeframe_long_reclaim_bonus_pct(decision.decision.action, symbol_snapshot),
            "higher_timeframe_long_early_reclaim_bonus_pct": self._higher_timeframe_long_early_reclaim_bonus_pct(decision.decision.action, symbol_snapshot),
        }
        base_expected_edge_pct = projected_move_pct - estimated_cost_pct + sum(bonuses.values())
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
            "directional_signal_pct": directional_signal_pct,
            "directional_component_pct": directional_component_pct,
            "projected_move_pct": projected_move_pct,
            "estimated_cost_pct": estimated_cost_pct,
            "bonuses": bonuses,
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
        if symbol_snapshot is None:
            return ["missing_symbol_snapshot"]
        indicators = symbol_snapshot.indicators
        return_24bars = float(indicators.get("return_24bars") or 0.0)
        sma_fast_ratio = float(indicators.get("sma_fast_ratio") or 0.0)
        sma_slow_ratio = float(indicators.get("sma_slow_ratio") or 0.0)
        volume_ratio = float(indicators.get("volume_ratio_20") or 0.0)
        countertrend_breakout_short = self._countertrend_breakout_short_bonus_pct(action, symbol_snapshot) > 0.0
        higher_timeframe_short_reclaim = self._higher_timeframe_short_reclaim_bonus_pct(action, symbol_snapshot) > 0.0
        higher_timeframe_long_reclaim = self._higher_timeframe_long_reclaim_bonus_pct(action, symbol_snapshot) > 0.0
        higher_timeframe_long_early_reclaim = self._higher_timeframe_long_early_reclaim_bonus_pct(action, symbol_snapshot) > 0.0
        higher_timeframe_long_reversal = self._higher_timeframe_long_reversal_ready(action, symbol_snapshot)
        higher_timeframe_long_fast_pullback = self._higher_timeframe_long_fast_pullback_ready(action, symbol_snapshot)
        long_sma_fast_exception = self._allow_long_side_sma_fast_exception(action, symbol_snapshot)
        reasons: list[str] = []

        if action == "buy":
            if return_24bars <= MIN_OPEN_SIGNAL_TREND_RETURN_PCT and not (higher_timeframe_long_reversal or higher_timeframe_long_reclaim or higher_timeframe_long_early_reclaim):
                reasons.append("open_signal_return_24bars_too_weak")
            if sma_fast_ratio <= 0.0 and not long_sma_fast_exception:
                reasons.append("open_signal_sma_fast_conflict")
            if sma_slow_ratio <= 0.0 and not (higher_timeframe_long_reversal or higher_timeframe_long_reclaim or higher_timeframe_long_early_reclaim):
                reasons.append("open_signal_sma_slow_conflict")
        elif action == "sell":
            if return_24bars >= -MIN_OPEN_SIGNAL_TREND_RETURN_PCT and not (countertrend_breakout_short or higher_timeframe_short_reclaim):
                reasons.append("open_signal_return_24bars_too_weak")
            if sma_fast_ratio >= 0.0:
                reasons.append("open_signal_sma_fast_conflict")
            if sma_slow_ratio >= 0.0 and not (countertrend_breakout_short or higher_timeframe_short_reclaim):
                reasons.append("open_signal_sma_slow_conflict")

        if volume_ratio < MIN_OPEN_SIGNAL_VOLUME_RATIO:
            reasons.append("open_signal_low_volume")
        return reasons

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

    def evaluate(self, validated: ValidatedDecision, bundle: MarketSnapshotBundle) -> RiskVerdict:
        decision = validated.decision
        reasons: list[str] = []
        approved = True
        final_action = decision.action
        final_size_pct = min(max(decision.size_pct, 0.0), self.settings.max_entry_size_pct)
        leverage = float(self.settings.contract_leverage)
        if is_open_action(decision.action, self.settings.contract_market):
            take_profit_pct = min(max(decision.take_profit_pct, self.settings.min_take_profit_pct), 0.05)
            stop_loss_pct = min(max(decision.stop_loss_pct, 0.005), 0.03)
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

        if self.journal.get_consecutive_losses(decision.symbol, limit=2) >= 2:
            reasons.append("recent_loss_streak")
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        current_entry_ts = None if symbol_snapshot is None else symbol_snapshot.recent_candles[-1].timestamp_ms
        history = self._recent_symbol_history(decision.symbol)
        last_action = self._last_matching_action(history, lambda item: item.get("final_action") != "hold")
        last_open = self._last_matching_action(history, lambda item: is_open_action(str(item.get("final_action") or "hold"), self.settings.contract_market))
        last_close = self._last_matching_action(history, lambda item: str(item.get("final_action") or "hold") == "close")
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
        if is_open_action(final_action, self.settings.contract_market) and not has_position:
            fresh_entry_assessment = assess_fresh_entry(symbol_snapshot, action=final_action) if symbol_snapshot is not None else None
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
                        "candidate_reasons": list(fresh_entry_assessment.candidate_reasons),
                        "risk_reasons": list(fresh_entry_assessment.risk_reasons),
                    }
                ),
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
                partial_take_profit_applied = False
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

        if approved and is_open_action(final_action, self.settings.contract_market) and not has_position:
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

        if approved and is_open_action(final_action, self.settings.contract_market):
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
                approved = False
                final_action = "hold"
                final_size_pct = 0.0
            else:
                signal_reasons = self._open_signal_reasons(final_action, symbol_snapshot)
                if signal_reasons:
                    reasons.extend(signal_reasons)
                    approved = False
                    final_action = "hold"
                    final_size_pct = 0.0

        if approved and is_open_action(final_action, self.settings.contract_market) and symbol_snapshot is not None:
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

        if approved and final_action == "close" and not forced_management_exit and current_entry_ts is not None and last_open is not None:
            bars_since_open = self._bars_since(current_entry_ts, last_open.get("bar_timestamp_ms"))
            if bars_since_open is not None and bars_since_open < self.settings.min_hold_bars:
                reasons.append(f"min_hold_bars_active:{bars_since_open}<{self.settings.min_hold_bars}")
                approved = False
                final_action = "hold"
                final_size_pct = 0.0

        if approved and has_position and final_action == "close" and not forced_management_exit and management_signal == "supportive":
            reasons.append("management_close_rejected_position_still_supported")
            approved = False
            final_action = "hold"
            final_size_pct = 0.0

        if approved and is_open_action(final_action, self.settings.contract_market) and current_entry_ts is not None and last_close is not None:
            bars_since_close = self._bars_since(current_entry_ts, last_close.get("bar_timestamp_ms"))
            if (
                bars_since_close is not None
                and bars_since_close < self.settings.same_symbol_reentry_cooldown_bars
            ):
                reasons.append(
                    f"same_symbol_reentry_cooldown_active:{bars_since_close}<{self.settings.same_symbol_reentry_cooldown_bars}"
                )
                approved = False
                final_action = "hold"
                final_size_pct = 0.0
            elif (
                bars_since_close is not None
                and bars_since_close < self._loss_reentry_cooldown_bars()
                and self._is_forced_loss_close(last_close, desired_direction)
            ):
                reasons.append(
                    f"loss_reentry_cooldown_active:{bars_since_close}<{self._loss_reentry_cooldown_bars()}"
                )
                approved = False
                final_action = "hold"
                final_size_pct = 0.0

        if approved and is_open_action(final_action, self.settings.contract_market) and current_entry_ts is not None and last_action is not None:
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
                approved = False
                final_action = "hold"
                final_size_pct = 0.0

        risk_size_cap_pct: float | None = None
        if approved and is_open_action(final_action, self.settings.contract_market):
            final_size_pct = min(max(final_size_pct, 0.0), self.settings.max_entry_size_pct)
            min_open_size_pct = min(max(self.settings.min_open_size_pct, 0.0), self.settings.max_entry_size_pct)
            if final_size_pct < min_open_size_pct:
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
