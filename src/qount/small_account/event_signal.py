"""Pure FOMC right-side signal rules for the small-account shadow contract."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from numbers import Real
from typing import Literal, Sequence


SIGNAL_CONTRACT_VERSION = "SmallAccount-FOMC-RightSide-v0.2"
_EPSILON = 1e-12
_SIDES = frozenset({"long", "short"})


def _finite(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(float(value))
    )


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


@dataclass(frozen=True)
class CompletedCandle:
    """One completed exchange candle with an explicit close timestamp."""

    interval_minutes: int
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def validate(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if (
            not isinstance(self.interval_minutes, int)
            or isinstance(self.interval_minutes, bool)
            or self.interval_minutes <= 0
        ):
            reasons.append("candle_interval_invalid")
        if not _aware(self.closed_at):
            reasons.append("candle_close_time_not_timezone_aware")
        for field_name in ("open", "high", "low", "close", "volume"):
            value = getattr(self, field_name)
            if not _finite(value):
                reasons.append(f"candle_{field_name}_invalid")
        if reasons:
            return tuple(reasons)
        if self.volume < 0.0:
            reasons.append("candle_volume_negative")
        if self.high + _EPSILON < self.low:
            reasons.append("candle_high_below_low")
        if not self.low - _EPSILON <= self.open <= self.high + _EPSILON:
            reasons.append("candle_open_outside_range")
        if not self.low - _EPSILON <= self.close <= self.high + _EPSILON:
            reasons.append("candle_close_outside_range")
        return tuple(reasons)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body_fraction(self) -> float:
        if self.range <= _EPSILON:
            return 0.0
        return abs(self.close - self.open) / self.range

    @property
    def close_location(self) -> float:
        if self.range <= _EPSILON:
            return 0.5
        return (self.close - self.low) / self.range


@dataclass(frozen=True)
class FomcSignalPolicy:
    breakout_atr_offset: float = 0.25
    retest_touch_tolerance_atr: float = 0.10
    maximum_entry_extension_atr: float = 0.25
    stop_buffer_atr: float = 0.50
    breakout_volume_multiple: float = 1.50
    reclaim_volume_fraction: float = 0.80
    minimum_breakout_body_fraction: float = 0.60
    minimum_long_close_location: float = 0.80
    maximum_short_close_location: float = 0.20
    maximum_retest_bars: int = 8

    def validate(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for field_name in (
            "breakout_atr_offset",
            "retest_touch_tolerance_atr",
            "maximum_entry_extension_atr",
            "stop_buffer_atr",
            "breakout_volume_multiple",
            "reclaim_volume_fraction",
            "minimum_breakout_body_fraction",
            "minimum_long_close_location",
            "maximum_short_close_location",
        ):
            value = getattr(self, field_name)
            if not _finite(value):
                reasons.append(f"policy_{field_name}_invalid")
        if reasons:
            return tuple(reasons)
        for field_name in (
            "breakout_atr_offset",
            "retest_touch_tolerance_atr",
            "maximum_entry_extension_atr",
            "stop_buffer_atr",
        ):
            if getattr(self, field_name) < 0.0:
                reasons.append(f"policy_{field_name}_invalid")
        if self.breakout_volume_multiple <= 0.0:
            reasons.append("policy_breakout_volume_multiple_invalid")
        if not 0.0 <= self.reclaim_volume_fraction <= 1.0:
            reasons.append("policy_reclaim_volume_fraction_invalid")
        if not 0.0 <= self.minimum_breakout_body_fraction <= 1.0:
            reasons.append("policy_minimum_breakout_body_fraction_invalid")
        if not 0.0 <= self.minimum_long_close_location <= 1.0:
            reasons.append("policy_minimum_long_close_location_invalid")
        if not 0.0 <= self.maximum_short_close_location <= 1.0:
            reasons.append("policy_maximum_short_close_location_invalid")
        if self.minimum_long_close_location <= self.maximum_short_close_location:
            reasons.append("policy_close_location_thresholds_overlap")
        if (
            not isinstance(self.maximum_retest_bars, int)
            or isinstance(self.maximum_retest_bars, bool)
            or self.maximum_retest_bars < 1
        ):
            reasons.append("policy_maximum_retest_bars_invalid")
        return tuple(reasons)


DEFAULT_FOMC_SIGNAL_POLICY = FomcSignalPolicy()


@dataclass(frozen=True)
class FomcSignalDecision:
    contract_version: str
    state: Literal["OBSERVE", "ARMED", "NO_TRADE"]
    side: str
    reasons: tuple[str, ...]
    breakout_line: float | None
    retest_extreme: float | None
    structural_stop_price: float | None

    @property
    def armed(self) -> bool:
        return self.state == "ARMED"


def _blocked_decision(
    *,
    side: str,
    reasons: Sequence[str],
    breakout_line: float | None,
    no_trade: bool = False,
    retest_extreme: float | None = None,
    structural_stop_price: float | None = None,
) -> FomcSignalDecision:
    return FomcSignalDecision(
        contract_version=SIGNAL_CONTRACT_VERSION,
        state="NO_TRADE" if no_trade else "OBSERVE",
        side=side,
        reasons=tuple(dict.fromkeys(reasons)),
        breakout_line=breakout_line,
        retest_extreme=retest_extreme,
        structural_stop_price=structural_stop_price,
    )


def _validate_inputs(
    *,
    side: str,
    h0: float,
    l0: float,
    atr0: float,
    v20_15m: float,
    anchor_1h: CompletedCandle,
    breakout_15m: CompletedCandle,
    retest_15m: Sequence[CompletedCandle],
    planned_entry_price: float,
    observation_started_at: datetime,
    entry_cutoff_at: datetime,
    evaluated_at: datetime,
    policy: FomcSignalPolicy,
) -> list[str]:
    reasons = list(policy.validate())
    if side not in _SIDES:
        _add_reason(reasons, "side_invalid")
    for field_name, value in (
        ("h0", h0),
        ("l0", l0),
        ("atr0", atr0),
        ("v20_15m", v20_15m),
        ("planned_entry_price", planned_entry_price),
    ):
        if not _finite(value):
            _add_reason(reasons, f"{field_name}_invalid")
    if reasons:
        return reasons
    if h0 <= l0:
        reasons.append("frozen_range_invalid")
    if h0 <= 0.0 or l0 <= 0.0:
        reasons.append("frozen_prices_invalid")
    if atr0 <= 0.0:
        reasons.append("atr0_invalid")
    if v20_15m <= 0.0:
        reasons.append("v20_15m_invalid")
    if planned_entry_price <= 0.0:
        reasons.append("planned_entry_price_invalid")
    for field_name, value in (
        ("observation_started_at", observation_started_at),
        ("entry_cutoff_at", entry_cutoff_at),
        ("evaluated_at", evaluated_at),
    ):
        if not _aware(value):
            reasons.append(f"{field_name}_not_timezone_aware")
    for prefix, candle in (("anchor", anchor_1h), ("breakout", breakout_15m)):
        if not isinstance(candle, CompletedCandle):
            _add_reason(reasons, f"{prefix}_candle_invalid")
            continue
        for reason in candle.validate():
            _add_reason(reasons, f"{prefix}_{reason}")
    if not isinstance(retest_15m, Sequence) or isinstance(
        retest_15m, (str, bytes)
    ):
        reasons.append("retest_sequence_invalid")
    else:
        for index, candle in enumerate(retest_15m):
            if not isinstance(candle, CompletedCandle):
                _add_reason(reasons, f"retest_{index}_candle_invalid")
                continue
            for reason in candle.validate():
                _add_reason(reasons, f"retest_{index}_{reason}")
    if reasons:
        return reasons
    if anchor_1h.interval_minutes != 60:
        reasons.append("anchor_interval_not_1h")
    if breakout_15m.interval_minutes != 15:
        reasons.append("breakout_interval_not_15m")
    if any(candle.interval_minutes != 15 for candle in retest_15m):
        reasons.append("retest_interval_not_15m")
    if observation_started_at > entry_cutoff_at:
        reasons.append("event_window_invalid")
    if evaluated_at < observation_started_at:
        reasons.append("observation_window_not_open")
    if anchor_1h.closed_at < observation_started_at:
        reasons.append("anchor_before_observation_window")
    if breakout_15m.closed_at < anchor_1h.closed_at:
        reasons.append("breakout_before_anchor")
    candle_times = [breakout_15m.closed_at]
    candle_times.extend(candle.closed_at for candle in retest_15m)
    if any(later <= earlier for earlier, later in zip(candle_times, candle_times[1:])):
        reasons.append("signal_candles_not_strictly_ordered")
    if any(closed_at > evaluated_at for closed_at in candle_times):
        reasons.append("signal_uses_uncompleted_candle")
    return reasons


def evaluate_fomc_hybrid_signal(
    *,
    side: str,
    h0: float,
    l0: float,
    atr0: float,
    v20_15m: float,
    anchor_1h: CompletedCandle,
    breakout_15m: CompletedCandle,
    retest_15m: Sequence[CompletedCandle],
    planned_entry_price: float,
    observation_started_at: datetime,
    entry_cutoff_at: datetime,
    evaluated_at: datetime,
    policy: FomcSignalPolicy = DEFAULT_FOMC_SIGNAL_POLICY,
) -> FomcSignalDecision:
    """Evaluate one completed 1h anchor plus a completed 15m retest sequence.

    This function cannot authorize or place an order. An ``ARMED`` result must
    still pass all-in sizing, net 2R room, account, freshness, and protection
    gates before any separately authorized execution path may act.
    """

    if not isinstance(policy, FomcSignalPolicy):
        return _blocked_decision(
            side=side,
            reasons=("policy_invalid",),
            breakout_line=None,
        )

    reasons = _validate_inputs(
        side=side,
        h0=h0,
        l0=l0,
        atr0=atr0,
        v20_15m=v20_15m,
        anchor_1h=anchor_1h,
        breakout_15m=breakout_15m,
        retest_15m=retest_15m,
        planned_entry_price=planned_entry_price,
        observation_started_at=observation_started_at,
        entry_cutoff_at=entry_cutoff_at,
        evaluated_at=evaluated_at,
        policy=policy,
    )
    breakout_line = None
    if side in _SIDES and _finite(h0) and _finite(l0) and _finite(atr0):
        breakout_line = (
            h0 + policy.breakout_atr_offset * atr0
            if side == "long"
            else l0 - policy.breakout_atr_offset * atr0
        )
    if reasons:
        no_trade = "entry_window_closed" in reasons
        return _blocked_decision(
            side=side,
            reasons=reasons,
            breakout_line=breakout_line,
            no_trade=no_trade,
        )
    assert breakout_line is not None
    if breakout_line <= 0.0:
        return _blocked_decision(
            side=side,
            reasons=("breakout_line_not_positive",),
            breakout_line=breakout_line,
        )

    if evaluated_at > entry_cutoff_at:
        return _blocked_decision(
            side=side,
            reasons=("entry_window_closed",),
            breakout_line=breakout_line,
            no_trade=True,
        )
    if len(retest_15m) > policy.maximum_retest_bars:
        return _blocked_decision(
            side=side,
            reasons=("retest_window_exceeded",),
            breakout_line=breakout_line,
            no_trade=True,
        )

    if side == "long":
        if anchor_1h.close <= breakout_line:
            _add_reason(reasons, "anchor_not_outside_breakout_line")
        if breakout_15m.close <= breakout_line:
            _add_reason(reasons, "breakout_not_outside_line")
        if breakout_15m.close_location + _EPSILON < policy.minimum_long_close_location:
            _add_reason(reasons, "breakout_close_location_weak")
    else:
        if anchor_1h.close >= breakout_line:
            _add_reason(reasons, "anchor_not_outside_breakout_line")
        if breakout_15m.close >= breakout_line:
            _add_reason(reasons, "breakout_not_outside_line")
        if breakout_15m.close_location - _EPSILON > policy.maximum_short_close_location:
            _add_reason(reasons, "breakout_close_location_weak")
    if (
        breakout_15m.volume + _EPSILON
        < policy.breakout_volume_multiple * v20_15m
    ):
        _add_reason(reasons, "breakout_volume_not_confirmed")
    if (
        breakout_15m.body_fraction + _EPSILON
        < policy.minimum_breakout_body_fraction
    ):
        _add_reason(reasons, "breakout_body_fraction_too_small")
    if reasons:
        return _blocked_decision(
            side=side,
            reasons=reasons,
            breakout_line=breakout_line,
        )
    if not retest_15m:
        return _blocked_decision(
            side=side,
            reasons=("retest_missing",),
            breakout_line=breakout_line,
        )

    reclaim = retest_15m[-1]
    if side == "long":
        retest_extreme = min(candle.low for candle in retest_15m)
        touch_ceiling = breakout_line + policy.retest_touch_tolerance_atr * atr0
        touched = any(candle.low <= touch_ceiling + _EPSILON for candle in retest_15m)
        returned_to_range = any(candle.low < h0 - _EPSILON for candle in retest_15m)
        reclaim_outside = reclaim.close > breakout_line
        entry_outside = planned_entry_price >= breakout_line - _EPSILON
        entry_extended = (
            planned_entry_price
            > breakout_line + policy.maximum_entry_extension_atr * atr0 + _EPSILON
        )
        structural_stop = retest_extreme - policy.stop_buffer_atr * atr0
    else:
        retest_extreme = max(candle.high for candle in retest_15m)
        touch_floor = breakout_line - policy.retest_touch_tolerance_atr * atr0
        touched = any(candle.high >= touch_floor - _EPSILON for candle in retest_15m)
        returned_to_range = any(candle.high > l0 + _EPSILON for candle in retest_15m)
        reclaim_outside = reclaim.close < breakout_line
        entry_outside = planned_entry_price <= breakout_line + _EPSILON
        entry_extended = (
            planned_entry_price
            < breakout_line - policy.maximum_entry_extension_atr * atr0 - _EPSILON
        )
        structural_stop = retest_extreme + policy.stop_buffer_atr * atr0

    if returned_to_range:
        return _blocked_decision(
            side=side,
            reasons=("retest_returned_to_original_range",),
            breakout_line=breakout_line,
            no_trade=True,
            retest_extreme=retest_extreme,
            structural_stop_price=structural_stop,
        )
    if not touched:
        _add_reason(reasons, "retest_not_deep_enough")
    if not reclaim_outside:
        _add_reason(reasons, "reclaim_not_outside_line")
    if reclaim.volume + _EPSILON < policy.reclaim_volume_fraction * breakout_15m.volume:
        _add_reason(reasons, "reclaim_volume_not_confirmed")
    if not entry_outside:
        _add_reason(reasons, "planned_entry_inside_breakout_line")
    if entry_extended:
        _add_reason(reasons, "planned_entry_too_extended")
    if reasons:
        return _blocked_decision(
            side=side,
            reasons=reasons,
            breakout_line=breakout_line,
            retest_extreme=retest_extreme,
            structural_stop_price=structural_stop,
        )
    return FomcSignalDecision(
        contract_version=SIGNAL_CONTRACT_VERSION,
        state="ARMED",
        side=side,
        reasons=(),
        breakout_line=breakout_line,
        retest_extreme=retest_extreme,
        structural_stop_price=structural_stop,
    )


__all__ = (
    "CompletedCandle",
    "DEFAULT_FOMC_SIGNAL_POLICY",
    "FomcSignalDecision",
    "FomcSignalPolicy",
    "SIGNAL_CONTRACT_VERSION",
    "evaluate_fomc_hybrid_signal",
)
