"""Pure pre-event range fade signal rules for the small-account contract."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from numbers import Real
from typing import Literal, Sequence

from qount.small_account.event_signal import CompletedCandle


RANGE_CONTRACT_VERSION = "SmallAccount-PreEvent-Range-v0.1"
_EPSILON = 1e-12
_SIDES = frozenset({"long", "short"})


def _finite(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(float(value))
    )


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


@dataclass(frozen=True)
class RangeFadePolicy:
    minimum_range_atr_multiple: float = 3.0
    entry_zone_atr: float = 0.25
    break_buffer_atr: float = 0.25
    stop_buffer_atr: float = 0.35
    minimum_trigger_volume_fraction: float = 1.0
    minimum_long_close_location: float = 0.60
    maximum_short_close_location: float = 0.40
    maximum_entry_distance_atr: float = 0.10
    cash_buffer_minutes: int = 30

    def validate(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for field_name in (
            "minimum_range_atr_multiple",
            "entry_zone_atr",
            "break_buffer_atr",
            "stop_buffer_atr",
            "minimum_trigger_volume_fraction",
            "minimum_long_close_location",
            "maximum_short_close_location",
            "maximum_entry_distance_atr",
        ):
            if not _finite(getattr(self, field_name)):
                reasons.append(f"policy_{field_name}_invalid")
        if reasons:
            return tuple(reasons)
        if self.minimum_range_atr_multiple <= 0.0:
            reasons.append("policy_minimum_range_atr_multiple_invalid")
        for field_name in (
            "entry_zone_atr",
            "break_buffer_atr",
            "stop_buffer_atr",
            "maximum_entry_distance_atr",
        ):
            if getattr(self, field_name) < 0.0:
                reasons.append(f"policy_{field_name}_invalid")
        if self.stop_buffer_atr <= self.break_buffer_atr:
            reasons.append("policy_stop_buffer_not_beyond_break_buffer")
        if self.minimum_trigger_volume_fraction <= 0.0:
            reasons.append("policy_minimum_trigger_volume_fraction_invalid")
        if not 0.0 <= self.minimum_long_close_location <= 1.0:
            reasons.append("policy_minimum_long_close_location_invalid")
        if not 0.0 <= self.maximum_short_close_location <= 1.0:
            reasons.append("policy_maximum_short_close_location_invalid")
        if self.minimum_long_close_location <= self.maximum_short_close_location:
            reasons.append("policy_close_location_thresholds_overlap")
        if (
            not isinstance(self.cash_buffer_minutes, int)
            or isinstance(self.cash_buffer_minutes, bool)
            or self.cash_buffer_minutes < 0
        ):
            reasons.append("policy_cash_buffer_minutes_invalid")
        return tuple(reasons)


DEFAULT_RANGE_FADE_POLICY = RangeFadePolicy()


@dataclass(frozen=True)
class RangeFadeDecision:
    contract_version: str
    state: Literal["OBSERVE", "ARMED", "NO_TRADE"]
    side: str
    reasons: tuple[str, ...]
    entry_zone_line: float | None
    break_line: float | None
    target_price: float | None
    structural_stop_price: float | None

    @property
    def armed(self) -> bool:
        return self.state == "ARMED"


def _blocked_decision(
    *,
    side: str,
    reasons: Sequence[str],
    no_trade: bool = False,
    entry_zone_line: float | None = None,
    break_line: float | None = None,
    target_price: float | None = None,
    structural_stop_price: float | None = None,
) -> RangeFadeDecision:
    return RangeFadeDecision(
        contract_version=RANGE_CONTRACT_VERSION,
        state="NO_TRADE" if no_trade else "OBSERVE",
        side=side,
        reasons=tuple(dict.fromkeys(reasons)),
        entry_zone_line=entry_zone_line,
        break_line=break_line,
        target_price=target_price,
        structural_stop_price=structural_stop_price,
    )


def _validate_inputs(
    *,
    side: str,
    h0: float,
    l0: float,
    atr0: float,
    v20_15m: float,
    recent_15m: Sequence[CompletedCandle],
    planned_entry_price: float,
    cash_cutoff_at: datetime,
    evaluated_at: datetime,
    policy: RangeFadePolicy,
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
        ("cash_cutoff_at", cash_cutoff_at),
        ("evaluated_at", evaluated_at),
    ):
        if not _aware(value):
            reasons.append(f"{field_name}_not_timezone_aware")
    if not isinstance(recent_15m, Sequence) or isinstance(recent_15m, (str, bytes)):
        reasons.append("recent_sequence_invalid")
    elif not recent_15m:
        reasons.append("recent_sequence_empty")
    else:
        for index, candle in enumerate(recent_15m):
            if not isinstance(candle, CompletedCandle):
                _add_reason(reasons, f"recent_{index}_candle_invalid")
                continue
            for reason in candle.validate():
                _add_reason(reasons, f"recent_{index}_{reason}")
    if reasons:
        return reasons
    if any(candle.interval_minutes != 15 for candle in recent_15m):
        reasons.append("recent_interval_not_15m")
    candle_times = [candle.closed_at for candle in recent_15m]
    if any(later <= earlier for earlier, later in zip(candle_times, candle_times[1:])):
        reasons.append("recent_candles_not_strictly_ordered")
    if any(closed_at > evaluated_at for closed_at in candle_times):
        reasons.append("signal_uses_uncompleted_candle")
    return reasons


def evaluate_range_fade_signal(
    *,
    side: str,
    h0: float,
    l0: float,
    atr0: float,
    v20_15m: float,
    recent_15m: Sequence[CompletedCandle],
    planned_entry_price: float,
    cash_cutoff_at: datetime,
    evaluated_at: datetime,
    policy: RangeFadePolicy = DEFAULT_RANGE_FADE_POLICY,
) -> RangeFadeDecision:
    """Evaluate one completed 15m fade trigger inside a frozen pre-event range.

    The last candle of ``recent_15m`` is the trigger candle. This function
    cannot authorize or place an order. An ``ARMED`` result must still pass
    all-in sizing, net 2R room, account, freshness, and protection gates
    before any separately authorized execution path may act.
    """

    if not isinstance(policy, RangeFadePolicy):
        return _blocked_decision(side=side, reasons=("policy_invalid",))

    reasons = _validate_inputs(
        side=side,
        h0=h0,
        l0=l0,
        atr0=atr0,
        v20_15m=v20_15m,
        recent_15m=recent_15m,
        planned_entry_price=planned_entry_price,
        cash_cutoff_at=cash_cutoff_at,
        evaluated_at=evaluated_at,
        policy=policy,
    )
    if reasons:
        return _blocked_decision(side=side, reasons=reasons)

    mid_price = (h0 + l0) / 2.0
    if side == "long":
        entry_zone_line = l0 + policy.entry_zone_atr * atr0
        break_line = l0 - policy.break_buffer_atr * atr0
        structural_stop = l0 - policy.stop_buffer_atr * atr0
    else:
        entry_zone_line = h0 - policy.entry_zone_atr * atr0
        break_line = h0 + policy.break_buffer_atr * atr0
        structural_stop = h0 + policy.stop_buffer_atr * atr0
    if structural_stop <= 0.0 or break_line <= 0.0:
        return _blocked_decision(
            side=side,
            reasons=("frozen_levels_not_positive",),
            entry_zone_line=entry_zone_line,
            break_line=break_line,
        )

    if evaluated_at >= cash_cutoff_at - timedelta(minutes=policy.cash_buffer_minutes):
        return _blocked_decision(
            side=side,
            reasons=("cash_deadline_reached",),
            no_trade=True,
            entry_zone_line=entry_zone_line,
            break_line=break_line,
        )
    if h0 - l0 + _EPSILON < policy.minimum_range_atr_multiple * atr0:
        return _blocked_decision(
            side=side,
            reasons=("range_too_narrow",),
            no_trade=True,
            entry_zone_line=entry_zone_line,
            break_line=break_line,
        )
    lower_break = l0 - policy.break_buffer_atr * atr0
    upper_break = h0 + policy.break_buffer_atr * atr0
    if any(
        candle.close < lower_break - _EPSILON or candle.close > upper_break + _EPSILON
        for candle in recent_15m
    ):
        return _blocked_decision(
            side=side,
            reasons=("range_broken",),
            no_trade=True,
            entry_zone_line=entry_zone_line,
            break_line=break_line,
        )

    trigger = recent_15m[-1]
    if side == "long":
        if trigger.low > entry_zone_line + _EPSILON:
            _add_reason(reasons, "trigger_did_not_touch_entry_zone")
        if trigger.close <= entry_zone_line + _EPSILON:
            _add_reason(reasons, "trigger_close_not_back_outside_zone")
        if trigger.close_location + _EPSILON < policy.minimum_long_close_location:
            _add_reason(reasons, "trigger_close_location_weak")
        target_price = mid_price
        entry_inside = l0 + _EPSILON < planned_entry_price < mid_price - _EPSILON
    else:
        if trigger.high < entry_zone_line - _EPSILON:
            _add_reason(reasons, "trigger_did_not_touch_entry_zone")
        if trigger.close >= entry_zone_line - _EPSILON:
            _add_reason(reasons, "trigger_close_not_back_outside_zone")
        if trigger.close_location - _EPSILON > policy.maximum_short_close_location:
            _add_reason(reasons, "trigger_close_location_weak")
        target_price = mid_price
        entry_inside = mid_price + _EPSILON < planned_entry_price < h0 - _EPSILON
    if (
        trigger.volume + _EPSILON
        < policy.minimum_trigger_volume_fraction * v20_15m
    ):
        _add_reason(reasons, "trigger_volume_not_confirmed")
    if not entry_inside:
        _add_reason(reasons, "planned_entry_outside_fade_zone")
    if (
        abs(planned_entry_price - trigger.close)
        > policy.maximum_entry_distance_atr * atr0 + _EPSILON
    ):
        _add_reason(reasons, "planned_entry_too_far_from_trigger_close")
    if reasons:
        return _blocked_decision(
            side=side,
            reasons=reasons,
            entry_zone_line=entry_zone_line,
            break_line=break_line,
            target_price=target_price,
            structural_stop_price=structural_stop,
        )
    return RangeFadeDecision(
        contract_version=RANGE_CONTRACT_VERSION,
        state="ARMED",
        side=side,
        reasons=(),
        entry_zone_line=entry_zone_line,
        break_line=break_line,
        target_price=target_price,
        structural_stop_price=structural_stop,
    )


__all__ = (
    "DEFAULT_RANGE_FADE_POLICY",
    "RANGE_CONTRACT_VERSION",
    "RangeFadeDecision",
    "RangeFadePolicy",
    "evaluate_range_fade_signal",
)
