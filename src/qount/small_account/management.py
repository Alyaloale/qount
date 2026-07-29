"""Pure post-entry management rules for the small-account event strategy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real


_SIDES = frozenset({"long", "short"})


def _finite(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(float(value))
    )


@dataclass(frozen=True)
class TailStopPolicy:
    trailing_atr_multiple: float = 1.0

    def validate(self) -> tuple[str, ...]:
        if (
            not _finite(self.trailing_atr_multiple)
            or self.trailing_atr_multiple <= 0.0
        ):
            return ("policy_trailing_atr_multiple_invalid",)
        return ()


DEFAULT_TAIL_STOP_POLICY = TailStopPolicy()


@dataclass(frozen=True)
class TailStopDecision:
    allowed: bool
    side: str
    reasons: tuple[str, ...]
    previous_stop_price: float
    one_r_floor_price: float
    atr_trailing_candidate_price: float | None
    next_stop_price: float | None


@dataclass(frozen=True)
class ProfitThresholdDecision:
    """Cost-aware post-entry price thresholds for one frozen full-risk unit."""

    allowed: bool
    side: str
    reasons: tuple[str, ...]
    entry_price: float
    initial_quantity: float
    full_risk_usdt: float
    net_break_even_price: float | None
    net_one_r_price: float | None
    net_two_r_price: float | None


@dataclass(frozen=True)
class PartialExitQuantityDecision:
    """The exchange-representable one-third reduction, or a blocking reason."""

    allowed: bool
    reasons: tuple[str, ...]
    initial_quantity: float
    quantity_step: float
    partial_quantity: float | None
    remaining_quantity: float | None


def calculate_profit_thresholds(
    *,
    side: str,
    entry_price: float,
    initial_quantity: float,
    full_risk_usdt: float,
    entry_fee_usdt: float,
    adverse_funding_usdt: float,
    exit_fee_rate: float,
    exit_slippage_rate: float,
) -> ProfitThresholdDecision:
    """Solve net break-even, +1R, and +2R exit prices from actual entry facts.

    The entry VWAP already contains incurred entry slippage.  The thresholds retain
    the actual entry fee and a conservative exit fee/slippage plus funding reserve.
    """

    reasons: list[str] = []
    if side not in _SIDES:
        reasons.append("side_invalid")
    for name, value, minimum, strict in (
        ("entry_price", entry_price, 0.0, True),
        ("initial_quantity", initial_quantity, 0.0, True),
        ("full_risk_usdt", full_risk_usdt, 0.0, True),
        ("entry_fee_usdt", entry_fee_usdt, 0.0, False),
        ("adverse_funding_usdt", adverse_funding_usdt, 0.0, False),
        ("exit_fee_rate", exit_fee_rate, 0.0, False),
        ("exit_slippage_rate", exit_slippage_rate, 0.0, False),
    ):
        if not _finite(value) or value < minimum or (strict and value <= minimum):
            reasons.append(f"{name}_invalid")
    if _finite(exit_fee_rate) and _finite(exit_slippage_rate):
        exit_cost_rate = float(exit_fee_rate) + float(exit_slippage_rate)
        if exit_cost_rate >= 1.0:
            reasons.append("exit_cost_rate_invalid")
    else:
        exit_cost_rate = math.nan
    if reasons:
        return ProfitThresholdDecision(
            allowed=False,
            side=side,
            reasons=tuple(dict.fromkeys(reasons)),
            entry_price=float(entry_price) if _finite(entry_price) else 0.0,
            initial_quantity=(
                float(initial_quantity) if _finite(initial_quantity) else 0.0
            ),
            full_risk_usdt=(
                float(full_risk_usdt) if _finite(full_risk_usdt) else 0.0
            ),
            net_break_even_price=None,
            net_one_r_price=None,
            net_two_r_price=None,
        )

    entry = float(entry_price)
    quantity = float(initial_quantity)
    fixed_costs = float(entry_fee_usdt) + float(adverse_funding_usdt)
    if side == "long":
        denominator = quantity * (1.0 - exit_cost_rate)
        numerator = entry * quantity + fixed_costs
        price_for_r = lambda multiple: (
            numerator + multiple * float(full_risk_usdt)
        ) / denominator
    else:
        denominator = quantity * (1.0 + exit_cost_rate)
        numerator = entry * quantity - fixed_costs
        price_for_r = lambda multiple: (
            numerator - multiple * float(full_risk_usdt)
        ) / denominator
    prices = tuple(price_for_r(multiple) for multiple in (0.0, 1.0, 2.0))
    if (
        denominator <= 0.0
        or any(not math.isfinite(price) or price <= 0.0 for price in prices)
        or (side == "long" and not prices[0] > 0.0)
    ):
        return ProfitThresholdDecision(
            allowed=False,
            side=side,
            reasons=("calculated_profit_threshold_invalid",),
            entry_price=entry,
            initial_quantity=quantity,
            full_risk_usdt=float(full_risk_usdt),
            net_break_even_price=None,
            net_one_r_price=None,
            net_two_r_price=None,
        )
    if (side == "long" and not prices[0] >= entry) or (
        side == "short" and not prices[0] <= entry
    ):
        return ProfitThresholdDecision(
            allowed=False,
            side=side,
            reasons=("net_break_even_direction_invalid",),
            entry_price=entry,
            initial_quantity=quantity,
            full_risk_usdt=float(full_risk_usdt),
            net_break_even_price=None,
            net_one_r_price=None,
            net_two_r_price=None,
        )
    return ProfitThresholdDecision(
        allowed=True,
        side=side,
        reasons=(),
        entry_price=entry,
        initial_quantity=quantity,
        full_risk_usdt=float(full_risk_usdt),
        net_break_even_price=prices[0],
        net_one_r_price=prices[1],
        net_two_r_price=prices[2],
    )


def calculate_one_third_exit_quantity(
    *,
    initial_quantity: float,
    quantity_step: float,
    minimum_quantity: float,
) -> PartialExitQuantityDecision:
    """Floor a one-third reduce-only order without consuming the entire position."""

    reasons: list[str] = []
    for name, value in (
        ("initial_quantity", initial_quantity),
        ("quantity_step", quantity_step),
        ("minimum_quantity", minimum_quantity),
    ):
        if not _finite(value) or value <= 0.0:
            reasons.append(f"{name}_invalid")
    if reasons:
        return PartialExitQuantityDecision(
            allowed=False,
            reasons=tuple(dict.fromkeys(reasons)),
            initial_quantity=(
                float(initial_quantity) if _finite(initial_quantity) else 0.0
            ),
            quantity_step=float(quantity_step) if _finite(quantity_step) else 0.0,
            partial_quantity=None,
            remaining_quantity=None,
        )

    quantity = float(initial_quantity)
    step = float(quantity_step)
    minimum = float(minimum_quantity)
    partial = math.floor((quantity / 3.0) / step + 1e-12) * step
    partial = round(partial, max(0, int(-math.floor(math.log10(step))) + 2))
    remaining = quantity - partial
    if partial + 1e-12 < minimum:
        reasons.append("one_third_partial_below_minimum_quantity")
    if remaining + 1e-12 < minimum:
        reasons.append("one_third_residual_below_minimum_quantity")
    if partial <= 0.0 or remaining <= 0.0:
        reasons.append("one_third_partial_not_representable")
    if reasons:
        return PartialExitQuantityDecision(
            allowed=False,
            reasons=tuple(dict.fromkeys(reasons)),
            initial_quantity=quantity,
            quantity_step=step,
            partial_quantity=None,
            remaining_quantity=None,
        )
    return PartialExitQuantityDecision(
        allowed=True,
        reasons=(),
        initial_quantity=quantity,
        quantity_step=step,
        partial_quantity=partial,
        remaining_quantity=remaining,
    )


def calculate_post_2r_tail_stop(
    *,
    side: str,
    previous_stop_price: float,
    net_one_r_floor_price: float,
    favorable_completed_1h_close_price: float,
    atr14_1h: float,
    partial_exit_confirmed: bool,
    policy: TailStopPolicy = DEFAULT_TAIL_STOP_POLICY,
) -> TailStopDecision:
    """Ratchet the remaining position only after the +2R partial fill is known."""

    reasons = (
        list(policy.validate())
        if isinstance(policy, TailStopPolicy)
        else ["policy_invalid"]
    )
    if side not in _SIDES:
        reasons.append("side_invalid")
    for field_name, value in (
        ("previous_stop_price", previous_stop_price),
        ("net_one_r_floor_price", net_one_r_floor_price),
        (
            "favorable_completed_1h_close_price",
            favorable_completed_1h_close_price,
        ),
        ("atr14_1h", atr14_1h),
    ):
        if not _finite(value) or value <= 0.0:
            reasons.append(f"{field_name}_invalid")
    if not isinstance(partial_exit_confirmed, bool):
        reasons.append("partial_exit_confirmed_invalid")
    elif not partial_exit_confirmed:
        reasons.append("partial_exit_not_confirmed")
    if not reasons:
        if (
            side == "long"
            and favorable_completed_1h_close_price <= net_one_r_floor_price
        ) or (
            side == "short"
            and favorable_completed_1h_close_price >= net_one_r_floor_price
        ):
            reasons.append("favorable_close_not_beyond_one_r_floor")
        if (
            side == "long"
            and previous_stop_price >= favorable_completed_1h_close_price
        ) or (
            side == "short"
            and previous_stop_price <= favorable_completed_1h_close_price
        ):
            reasons.append("previous_stop_already_through_favorable_close")
    if reasons:
        return TailStopDecision(
            allowed=False,
            side=side,
            reasons=tuple(dict.fromkeys(reasons)),
            previous_stop_price=(
                float(previous_stop_price) if _finite(previous_stop_price) else 0.0
            ),
            one_r_floor_price=(
                float(net_one_r_floor_price)
                if _finite(net_one_r_floor_price)
                else 0.0
            ),
            atr_trailing_candidate_price=None,
            next_stop_price=None,
        )

    if side == "long":
        atr_candidate = (
            favorable_completed_1h_close_price
            - policy.trailing_atr_multiple * atr14_1h
        )
        next_stop = max(
            previous_stop_price,
            net_one_r_floor_price,
            atr_candidate,
        )
    else:
        atr_candidate = (
            favorable_completed_1h_close_price
            + policy.trailing_atr_multiple * atr14_1h
        )
        next_stop = min(
            previous_stop_price,
            net_one_r_floor_price,
            atr_candidate,
        )
    if atr_candidate <= 0.0 or next_stop <= 0.0:
        return TailStopDecision(
            allowed=False,
            side=side,
            reasons=("calculated_stop_price_invalid",),
            previous_stop_price=float(previous_stop_price),
            one_r_floor_price=float(net_one_r_floor_price),
            atr_trailing_candidate_price=float(atr_candidate),
            next_stop_price=None,
        )
    return TailStopDecision(
        allowed=True,
        side=side,
        reasons=(),
        previous_stop_price=float(previous_stop_price),
        one_r_floor_price=float(net_one_r_floor_price),
        atr_trailing_candidate_price=float(atr_candidate),
        next_stop_price=float(next_stop),
    )


__all__ = (
    "DEFAULT_TAIL_STOP_POLICY",
    "PartialExitQuantityDecision",
    "ProfitThresholdDecision",
    "TailStopDecision",
    "TailStopPolicy",
    "calculate_one_third_exit_quantity",
    "calculate_post_2r_tail_stop",
    "calculate_profit_thresholds",
)
