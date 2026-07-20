"""Fail-closed strategy runtime eligibility checks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


SMALL_ACCOUNT_THRESHOLD_USDT = 3_000.0


@dataclass(frozen=True)
class SleeveRuntimeEligibility:
    strategy_id: str
    strategy_kind: str
    runtime_mode: str


def validate_runtime_eligibility(
    account_equity_usdt: float,
    sleeves: Sequence[SleeveRuntimeEligibility],
) -> tuple[str, ...]:
    """Enforce the small-account live eligibility contract."""

    errors: list[str] = []
    if not math.isfinite(account_equity_usdt) or account_equity_usdt <= 0.0:
        return ("account_equity_invalid",)
    allowed_kinds = {"continuous", "event", "filter"}
    allowed_modes = {"research", "virtual", "shadow", "minimal_live", "live"}
    ids = [sleeve.strategy_id for sleeve in sleeves]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_strategy_id")
    for sleeve in sleeves:
        if not sleeve.strategy_id:
            errors.append("strategy_id_empty")
        if sleeve.strategy_kind not in allowed_kinds:
            errors.append(f"strategy_kind_invalid:{sleeve.strategy_id}")
        if sleeve.runtime_mode not in allowed_modes:
            errors.append(f"runtime_mode_invalid:{sleeve.strategy_id}")
        if sleeve.strategy_kind == "filter" and sleeve.runtime_mode in {
            "minimal_live",
            "live",
        }:
            errors.append(f"filter_cannot_own_live_orders:{sleeve.strategy_id}")

    if account_equity_usdt < SMALL_ACCOUNT_THRESHOLD_USDT:
        continuous_live = [
            sleeve.strategy_id
            for sleeve in sleeves
            if sleeve.strategy_kind == "continuous"
            and sleeve.runtime_mode in {"minimal_live", "live"}
        ]
        event_minimal_live = [
            sleeve.strategy_id
            for sleeve in sleeves
            if sleeve.strategy_kind == "event"
            and sleeve.runtime_mode == "minimal_live"
        ]
        event_full_live = [
            sleeve.strategy_id
            for sleeve in sleeves
            if sleeve.strategy_kind == "event" and sleeve.runtime_mode == "live"
        ]
        if len(continuous_live) > 1:
            errors.append("small_account_multiple_continuous_live_sleeves")
        if len(event_minimal_live) > 1:
            errors.append("small_account_multiple_event_minimal_live_sleeves")
        if event_full_live:
            errors.append("small_account_event_sleeve_must_be_minimal_live")
    return tuple(errors)
