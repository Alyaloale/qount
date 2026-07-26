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
    "TailStopDecision",
    "TailStopPolicy",
    "calculate_post_2r_tail_stop",
)
