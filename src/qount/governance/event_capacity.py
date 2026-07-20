"""Execution-capacity governance for the Equity Mapping event sleeve."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EquityMappingExecutionContract:
    timezone: str = "America/New_York"
    decision_time: str = "09:25:00"
    entry_quote_window: str = "09:24:30-09:25:30"
    earliest_order_time: str = "09:25:00"
    cash_open_reference: str = "09:30:00"
    direction: str = "long_only_negative_true_gap"
    maximum_event_stress_loss_fraction: float = 0.0025

    def __post_init__(self) -> None:
        if self.timezone != "America/New_York":
            raise ValueError("equity_mapping_timezone_changed")
        if self.decision_time != "09:25:00":
            raise ValueError("equity_mapping_decision_time_changed")
        if self.entry_quote_window != "09:24:30-09:25:30":
            raise ValueError("equity_mapping_quote_window_changed")
        if self.earliest_order_time != self.decision_time:
            raise ValueError("equity_mapping_order_cannot_precede_decision")
        if self.direction != "long_only_negative_true_gap":
            raise ValueError("equity_mapping_must_remain_long_only")
        if self.maximum_event_stress_loss_fraction != 0.0025:
            raise ValueError("equity_mapping_event_risk_budget_changed")


def equity_mapping_event_capacity(
    *,
    account_equity_usdt: float,
    true_gap: float,
    stress_loss_fraction: float,
    minimum_notional_usdt: float,
    corporate_action_status: str,
    contract: EquityMappingExecutionContract | None = None,
) -> dict[str, Any]:
    """Size a negative-gap long event by stress loss or block it to shadow."""

    contract = contract or EquityMappingExecutionContract()
    values = (
        account_equity_usdt,
        true_gap,
        stress_loss_fraction,
        minimum_notional_usdt,
    )
    if any(not math.isfinite(float(value)) for value in values):
        raise ValueError("equity_mapping_event_input_non_finite")
    if account_equity_usdt <= 0.0:
        raise ValueError("equity_mapping_account_equity_invalid")
    if not 0.0 < stress_loss_fraction <= 1.0:
        raise ValueError("equity_mapping_stress_loss_invalid")
    if minimum_notional_usdt < 0.0:
        raise ValueError("equity_mapping_minimum_notional_invalid")
    if corporate_action_status not in {"none", "point_in_time_adjusted", "unknown"}:
        raise ValueError("equity_mapping_corporate_action_status_invalid")

    reasons: list[str] = []
    if corporate_action_status == "unknown":
        reasons.append("corporate_action_not_point_in_time_reconstructable")
    if true_gap >= 0.0:
        reasons.append("not_a_negative_gap_long_event")
    notional = (
        account_equity_usdt
        * contract.maximum_event_stress_loss_fraction
        / stress_loss_fraction
    )
    if notional < minimum_notional_usdt:
        reasons.append("stress_sized_notional_below_exchange_minimum")
    return {
        "notional_usdt": notional,
        "maximum_account_stress_loss_usdt": (
            account_equity_usdt * contract.maximum_event_stress_loss_fraction
        ),
        "live_trial_eligible": not reasons,
        "shadow_only": bool(reasons),
        "reasons": reasons,
        "direction": contract.direction,
    }
