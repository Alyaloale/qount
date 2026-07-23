"""Frozen-trial and independence-unit research governance."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence


FORMAL_TRIAL_REVIEW_MILESTONE = 3
# Compatibility alias.  This is an observation target, not a registration cap.
MAX_FORMAL_TRIALS_PER_FAMILY = FORMAL_TRIAL_REVIEW_MILESTONE


@dataclass(frozen=True)
class FormalTrial:
    trial_id: str
    hypothesis_family: str
    preregistered_primary_metric: str
    preregistered_failure_condition: str
    allowed_sensitivity_range: str
    number_of_prior_trials: int


def register_formal_trial(
    existing: Sequence[FormalTrial], proposed: FormalTrial
) -> tuple[FormalTrial, ...]:
    if not proposed.trial_id:
        raise ValueError("trial_id_empty")
    if not proposed.hypothesis_family:
        raise ValueError("hypothesis_family_empty")
    if proposed.trial_id in {trial.trial_id for trial in existing}:
        raise ValueError("trial_id_duplicate")
    required = {
        "preregistered_primary_metric": proposed.preregistered_primary_metric,
        "preregistered_failure_condition": proposed.preregistered_failure_condition,
        "allowed_sensitivity_range": proposed.allowed_sensitivity_range,
    }
    for name, value in required.items():
        if not value.strip():
            raise ValueError(f"{name}_empty")
    family_trials = sum(
        trial.hypothesis_family == proposed.hypothesis_family for trial in existing
    )
    if proposed.number_of_prior_trials != family_trials:
        raise ValueError("number_of_prior_trials_mismatch")
    return (*existing, proposed)


def formal_trial_observation(
    existing: Sequence[FormalTrial], hypothesis_family: str
) -> dict[str, Any]:
    """Report family trial maturity without blocking further research."""

    count = sum(
        trial.hypothesis_family == hypothesis_family for trial in existing
    )
    return {
        "policy_mode": "non_blocking_observation",
        "hypothesis_family": hypothesis_family,
        "formal_trial_count": count,
        "review_milestone": FORMAL_TRIAL_REVIEW_MILESTONE,
        "review_milestone_reached": count >= FORMAL_TRIAL_REVIEW_MILESTONE,
        "blocks_additional_trials": False,
    }


@dataclass(frozen=True)
class ForwardPeriod:
    period_id: str
    pool_role: str = "promotion_pool"
    result_reviewed: bool = False
    rules_changed_after_review: bool = False
    next_unseen_period_required: bool = False


def record_forward_review(
    period: ForwardPeriod, *, rules_changed_after_review: bool
) -> ForwardPeriod:
    if period.pool_role not in {"promotion_pool", "consumed_pool"}:
        raise ValueError("forward_pool_role_invalid")
    if not period.period_id:
        raise ValueError("forward_period_id_empty")
    if period.pool_role == "consumed_pool":
        return replace(period, result_reviewed=True)
    if rules_changed_after_review:
        return replace(
            period,
            pool_role="consumed_pool",
            result_reviewed=True,
            rules_changed_after_review=True,
            next_unseen_period_required=True,
        )
    return replace(period, result_reviewed=True)


def _iso_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def base_operational_evidence(completed_bar_dates: Sequence[Any]) -> dict[str, Any]:
    dates = {_iso_date(value) for value in completed_bar_dates}
    return {
        "operational_completed_daily_bars": len(dates),
        "statistical_alpha_units": 0,
        "evidence_role": "operational_only",
    }


def equity_mapping_independence(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    dates = {_iso_date(record["cash_trading_date"]) for record in records}
    weeks = {(date.isocalendar().year, date.isocalendar().week) for date in dates}
    return {
        "asset_event_count": len(records),
        "independent_cash_trading_dates": len(dates),
        "independent_iso_weeks": len(weeks),
        "earnings_event_count": sum(bool(row.get("is_earnings")) for row in records),
        "ordinary_weekend_event_count": sum(
            bool(row.get("is_ordinary_weekend")) for row in records
        ),
        "holiday_event_count": sum(bool(row.get("is_holiday")) for row in records),
        "independence_unit": "cash_trading_date",
    }


def funding_episode_independence(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    episode_ids = {str(record["episode_id"]) for record in records}
    if "" in episode_ids:
        raise ValueError("funding_episode_id_empty")
    return {
        "observation_count": len(records),
        "independent_episode_count": len(episode_ids),
        "independence_unit": "extreme_funding_episode",
    }


def liquid_trend_independence(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rebalance_dates = {_iso_date(record["rebalance_date"]) for record in records}
    regimes = {str(record["market_regime"]) for record in records}
    return {
        "observation_count": len(records),
        "independent_rebalance_dates": len(rebalance_dates),
        "observed_market_regime_count": len(regimes - {""}),
        "independence_unit": "rebalance_date_and_market_regime",
    }
