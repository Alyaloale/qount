"""Pure sizing and account guards for a tightly bounded small account."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from numbers import Real
from typing import Iterable


_EPSILON = 1e-12
_BETA_DIRECTIONS = frozenset({"long", "short"})


def _finite(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(float(value))
    )


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _floor_to_step(value: float, step: float) -> float:
    if not _finite(value) or not _finite(step) or value <= 0.0 or step <= 0.0:
        return 0.0
    value_decimal = Decimal(str(value))
    step_decimal = Decimal(str(step))
    steps = value_decimal // step_decimal
    return float(steps * step_decimal)


@dataclass(frozen=True)
class SmallAccountRiskPolicy:
    initial_equity_usdt: float = 200.0
    first_live_risk_cap_usdt: float = 5.0
    per_trade_risk_cap_usdt: float = 10.0
    concurrent_stress_risk_cap_usdt: float = 10.0
    rolling_24h_loss_limit_usdt: float = 10.0
    strategy_drawdown_limit_usdt: float = 20.0
    emergency_drawdown_limit_usdt: float = 32.0
    disaster_drawdown_limit_usdt: float = 40.0
    maximum_crypto_beta_exposures: int = 1
    default_futures_leverage: float = 5.0
    maximum_futures_leverage: float = 5.0
    maximum_isolated_margin_usdt: float = 40.0
    maximum_futures_notional_usdt: float = 200.0
    maximum_spot_notional_usdt: float = 40.0
    minimum_reward_risk_ratio: float = 2.0

    def validate(self) -> tuple[str, ...]:
        reasons: list[str] = []
        positive_fields = (
            "initial_equity_usdt",
            "first_live_risk_cap_usdt",
            "per_trade_risk_cap_usdt",
            "concurrent_stress_risk_cap_usdt",
            "rolling_24h_loss_limit_usdt",
            "strategy_drawdown_limit_usdt",
            "emergency_drawdown_limit_usdt",
            "disaster_drawdown_limit_usdt",
            "default_futures_leverage",
            "maximum_futures_leverage",
            "maximum_isolated_margin_usdt",
            "maximum_futures_notional_usdt",
            "maximum_spot_notional_usdt",
            "minimum_reward_risk_ratio",
        )
        for field_name in positive_fields:
            raw_value = getattr(self, field_name)
            if not _finite(raw_value) or float(raw_value) <= 0.0:
                reasons.append(f"policy_{field_name}_invalid")
        if reasons:
            return tuple(reasons)
        if self.first_live_risk_cap_usdt > self.per_trade_risk_cap_usdt:
            reasons.append("policy_first_live_cap_above_trade_cap")
        if self.per_trade_risk_cap_usdt > self.concurrent_stress_risk_cap_usdt:
            reasons.append("policy_trade_cap_above_concurrent_cap")
        if not (
            self.rolling_24h_loss_limit_usdt
            <= self.strategy_drawdown_limit_usdt
            < self.emergency_drawdown_limit_usdt
            < self.disaster_drawdown_limit_usdt
            <= self.initial_equity_usdt
        ):
            reasons.append("policy_drawdown_limits_invalid")
        if self.default_futures_leverage > self.maximum_futures_leverage:
            reasons.append("policy_default_leverage_above_maximum")
        if (
            not isinstance(self.maximum_crypto_beta_exposures, int)
            or isinstance(self.maximum_crypto_beta_exposures, bool)
            or self.maximum_crypto_beta_exposures < 1
        ):
            reasons.append("policy_crypto_beta_exposure_limit_invalid")
        if self.minimum_reward_risk_ratio < 1.0:
            reasons.append("policy_reward_risk_ratio_invalid")
        return tuple(reasons)

    def active_trade_risk_cap(self, protective_cycle_verified: bool) -> float:
        if self.validate():
            return 0.0
        if protective_cycle_verified:
            return self.per_trade_risk_cap_usdt
        return self.first_live_risk_cap_usdt


DEFAULT_SMALL_ACCOUNT_POLICY = SmallAccountRiskPolicy()


@dataclass(frozen=True)
class ExecutionCostRates:
    entry_fee_rate: float
    exit_fee_rate: float
    entry_slippage_rate: float
    exit_slippage_rate: float
    adverse_funding_rate: float = 0.0

    def validate(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for field_name in (
            "entry_fee_rate",
            "exit_fee_rate",
            "entry_slippage_rate",
            "exit_slippage_rate",
            "adverse_funding_rate",
        ):
            raw_value = getattr(self, field_name)
            if not _finite(raw_value) or not 0.0 <= float(raw_value) < 1.0:
                reasons.append(f"{field_name}_invalid")
        return tuple(reasons)


@dataclass(frozen=True)
class PositionSizeDecision:
    instrument: str
    side: str
    allowed: bool
    reasons: tuple[str, ...]
    requested_risk_budget_usdt: float
    effective_risk_cap_usdt: float
    quantity: float
    notional_usdt: float
    leverage: float
    isolated_margin_usdt: float
    worst_stop_fill_price: float | None
    risk_per_unit_usdt: float | None
    reward_per_unit_usdt: float | None
    reward_risk_ratio: float | None
    estimated_stress_loss_usdt: float
    estimated_net_reward_usdt: float


def _blocked_size_decision(
    *,
    instrument: str,
    side: str,
    reasons: Iterable[str],
    requested_risk_budget_usdt: float,
    effective_risk_cap_usdt: float,
    leverage: float,
    worst_stop_fill_price: float | None = None,
    risk_per_unit_usdt: float | None = None,
    reward_per_unit_usdt: float | None = None,
    reward_risk_ratio: float | None = None,
) -> PositionSizeDecision:
    return PositionSizeDecision(
        instrument=instrument,
        side=side,
        allowed=False,
        reasons=tuple(dict.fromkeys(reasons)),
        requested_risk_budget_usdt=requested_risk_budget_usdt,
        effective_risk_cap_usdt=effective_risk_cap_usdt,
        quantity=0.0,
        notional_usdt=0.0,
        leverage=leverage,
        isolated_margin_usdt=0.0,
        worst_stop_fill_price=worst_stop_fill_price,
        risk_per_unit_usdt=risk_per_unit_usdt,
        reward_per_unit_usdt=reward_per_unit_usdt,
        reward_risk_ratio=reward_risk_ratio,
        estimated_stress_loss_usdt=0.0,
        estimated_net_reward_usdt=0.0,
    )


def _validate_sizing_inputs(
    *,
    side: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    stop_gap_rate: float,
    quantity_step: float,
    minimum_notional_usdt: float,
    requested_risk_budget_usdt: float,
    effective_risk_cap_usdt: float,
    costs: ExecutionCostRates,
    policy: SmallAccountRiskPolicy,
) -> list[str]:
    reasons = list(policy.validate())
    reasons.extend(costs.validate())
    for field_name, value in (
        ("entry_price", entry_price),
        ("stop_price", stop_price),
        ("target_price", target_price),
        ("quantity_step", quantity_step),
    ):
        if not _finite(value) or value <= 0.0:
            _add_reason(reasons, f"{field_name}_invalid")
    if not _finite(stop_gap_rate) or not 0.0 <= stop_gap_rate < 1.0:
        _add_reason(reasons, "stop_gap_rate_invalid")
    if not _finite(minimum_notional_usdt) or minimum_notional_usdt < 0.0:
        _add_reason(reasons, "minimum_notional_usdt_invalid")
    if (
        not _finite(requested_risk_budget_usdt)
        or requested_risk_budget_usdt <= 0.0
    ):
        _add_reason(reasons, "requested_risk_budget_usdt_invalid")
    elif requested_risk_budget_usdt > effective_risk_cap_usdt + _EPSILON:
        if effective_risk_cap_usdt == policy.first_live_risk_cap_usdt:
            _add_reason(reasons, "first_live_risk_cap_exceeded")
        else:
            _add_reason(reasons, "per_trade_risk_cap_exceeded")
    prices_valid = all(_finite(value) for value in (entry_price, stop_price, target_price))
    if side == "long" and prices_valid:
        if not stop_price < entry_price:
            _add_reason(reasons, "long_stop_not_below_entry")
        if not target_price > entry_price:
            _add_reason(reasons, "long_target_not_above_entry")
    elif side == "short" and prices_valid:
        if not stop_price > entry_price:
            _add_reason(reasons, "short_stop_not_above_entry")
        if not target_price < entry_price:
            _add_reason(reasons, "short_target_not_below_entry")
    elif side not in _BETA_DIRECTIONS:
        _add_reason(reasons, "side_invalid")
    return reasons


def _per_unit_economics(
    *,
    side: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    stop_gap_rate: float,
    costs: ExecutionCostRates,
) -> tuple[float, float, float]:
    if side == "long":
        worst_stop_fill = stop_price * (1.0 - stop_gap_rate)
        adverse_price_loss = entry_price - worst_stop_fill
        gross_reward = target_price - entry_price
    else:
        worst_stop_fill = stop_price * (1.0 + stop_gap_rate)
        adverse_price_loss = worst_stop_fill - entry_price
        gross_reward = entry_price - target_price

    entry_cost = entry_price * (
        costs.entry_fee_rate + costs.entry_slippage_rate
    )
    stop_exit_cost = worst_stop_fill * (
        costs.exit_fee_rate + costs.exit_slippage_rate
    )
    target_exit_cost = target_price * (
        costs.exit_fee_rate + costs.exit_slippage_rate
    )
    funding_cost = entry_price * costs.adverse_funding_rate
    risk_per_unit = adverse_price_loss + entry_cost + stop_exit_cost + funding_cost
    reward_per_unit = gross_reward - entry_cost - target_exit_cost - funding_cost
    return worst_stop_fill, risk_per_unit, reward_per_unit


def size_linear_usdt_futures(
    *,
    side: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    stop_gap_rate: float,
    quantity_step: float,
    costs: ExecutionCostRates,
    risk_budget_usdt: float | None = None,
    leverage: float | None = None,
    margin_mode: str = "isolated",
    minimum_notional_usdt: float = 0.0,
    protective_cycle_verified: bool = False,
    policy: SmallAccountRiskPolicy = DEFAULT_SMALL_ACCOUNT_POLICY,
) -> PositionSizeDecision:
    """Size one linear USDT contract from its all-in stress loss."""

    effective_cap = policy.active_trade_risk_cap(protective_cycle_verified)
    raw_requested_budget = (
        effective_cap if risk_budget_usdt is None else risk_budget_usdt
    )
    requested_budget = (
        float(raw_requested_budget) if _finite(raw_requested_budget) else math.nan
    )
    raw_selected_leverage = (
        policy.default_futures_leverage if leverage is None else leverage
    )
    selected_leverage = (
        float(raw_selected_leverage) if _finite(raw_selected_leverage) else math.nan
    )
    reasons = _validate_sizing_inputs(
        side=side,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        stop_gap_rate=stop_gap_rate,
        quantity_step=quantity_step,
        minimum_notional_usdt=minimum_notional_usdt,
        requested_risk_budget_usdt=requested_budget,
        effective_risk_cap_usdt=effective_cap,
        costs=costs,
        policy=policy,
    )
    if not _finite(selected_leverage) or selected_leverage <= 0.0:
        _add_reason(reasons, "leverage_invalid")
    elif selected_leverage > policy.maximum_futures_leverage + _EPSILON:
        _add_reason(reasons, "maximum_futures_leverage_exceeded")
    if margin_mode != "isolated":
        _add_reason(reasons, "isolated_margin_required")
    if reasons:
        return _blocked_size_decision(
            instrument="linear_usdt_futures",
            side=side,
            reasons=reasons,
            requested_risk_budget_usdt=requested_budget,
            effective_risk_cap_usdt=effective_cap,
            leverage=selected_leverage if _finite(selected_leverage) else 0.0,
        )

    worst_stop_fill, risk_per_unit, reward_per_unit = _per_unit_economics(
        side=side,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        stop_gap_rate=stop_gap_rate,
        costs=costs,
    )
    if worst_stop_fill <= 0.0 or risk_per_unit <= 0.0:
        _add_reason(reasons, "stress_loss_not_positive")
    reward_risk_ratio = (
        reward_per_unit / risk_per_unit if risk_per_unit > 0.0 else None
    )
    if reward_risk_ratio is None or not _finite(reward_risk_ratio):
        _add_reason(reasons, "reward_risk_ratio_invalid")
    elif reward_risk_ratio + _EPSILON < policy.minimum_reward_risk_ratio:
        _add_reason(reasons, "minimum_reward_risk_ratio_not_met")
    if reasons:
        return _blocked_size_decision(
            instrument="linear_usdt_futures",
            side=side,
            reasons=reasons,
            requested_risk_budget_usdt=requested_budget,
            effective_risk_cap_usdt=effective_cap,
            leverage=selected_leverage,
            worst_stop_fill_price=worst_stop_fill,
            risk_per_unit_usdt=risk_per_unit,
            reward_per_unit_usdt=reward_per_unit,
            reward_risk_ratio=reward_risk_ratio,
        )

    risk_quantity = requested_budget / risk_per_unit
    notional_quantity = policy.maximum_futures_notional_usdt / entry_price
    margin_quantity = (
        policy.maximum_isolated_margin_usdt
        * selected_leverage
        / entry_price
    )
    quantity = _floor_to_step(
        min(risk_quantity, notional_quantity, margin_quantity), quantity_step
    )
    notional = quantity * entry_price
    margin = notional / selected_leverage
    stress_loss = quantity * risk_per_unit
    net_reward = quantity * reward_per_unit
    if quantity <= 0.0:
        _add_reason(reasons, "quantity_below_step")
    if notional + _EPSILON < minimum_notional_usdt:
        _add_reason(reasons, "notional_below_exchange_minimum")
    if notional > policy.maximum_futures_notional_usdt + _EPSILON:
        _add_reason(reasons, "maximum_futures_notional_exceeded")
    if margin > policy.maximum_isolated_margin_usdt + _EPSILON:
        _add_reason(reasons, "maximum_isolated_margin_exceeded")
    if stress_loss > requested_budget + _EPSILON:
        _add_reason(reasons, "risk_budget_exceeded_after_rounding")
    if reasons:
        return _blocked_size_decision(
            instrument="linear_usdt_futures",
            side=side,
            reasons=reasons,
            requested_risk_budget_usdt=requested_budget,
            effective_risk_cap_usdt=effective_cap,
            leverage=selected_leverage,
            worst_stop_fill_price=worst_stop_fill,
            risk_per_unit_usdt=risk_per_unit,
            reward_per_unit_usdt=reward_per_unit,
            reward_risk_ratio=reward_risk_ratio,
        )
    return PositionSizeDecision(
        instrument="linear_usdt_futures",
        side=side,
        allowed=True,
        reasons=(),
        requested_risk_budget_usdt=requested_budget,
        effective_risk_cap_usdt=effective_cap,
        quantity=quantity,
        notional_usdt=notional,
        leverage=selected_leverage,
        isolated_margin_usdt=margin,
        worst_stop_fill_price=worst_stop_fill,
        risk_per_unit_usdt=risk_per_unit,
        reward_per_unit_usdt=reward_per_unit,
        reward_risk_ratio=reward_risk_ratio,
        estimated_stress_loss_usdt=stress_loss,
        estimated_net_reward_usdt=net_reward,
    )


def size_spot_long(
    *,
    entry_price: float,
    stop_price: float,
    target_price: float,
    stop_gap_rate: float,
    quantity_step: float,
    costs: ExecutionCostRates,
    risk_budget_usdt: float | None = None,
    minimum_notional_usdt: float = 0.0,
    protective_cycle_verified: bool = False,
    policy: SmallAccountRiskPolicy = DEFAULT_SMALL_ACCOUNT_POLICY,
) -> PositionSizeDecision:
    """Size a spot long under both all-in loss and hard tail-notional caps."""

    effective_cap = policy.active_trade_risk_cap(protective_cycle_verified)
    raw_requested_budget = (
        effective_cap if risk_budget_usdt is None else risk_budget_usdt
    )
    requested_budget = (
        float(raw_requested_budget) if _finite(raw_requested_budget) else math.nan
    )
    reasons = _validate_sizing_inputs(
        side="long",
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        stop_gap_rate=stop_gap_rate,
        quantity_step=quantity_step,
        minimum_notional_usdt=minimum_notional_usdt,
        requested_risk_budget_usdt=requested_budget,
        effective_risk_cap_usdt=effective_cap,
        costs=costs,
        policy=policy,
    )
    if costs.adverse_funding_rate != 0.0:
        _add_reason(reasons, "spot_funding_rate_must_be_zero")
    if reasons:
        return _blocked_size_decision(
            instrument="spot",
            side="long",
            reasons=reasons,
            requested_risk_budget_usdt=requested_budget,
            effective_risk_cap_usdt=effective_cap,
            leverage=1.0,
        )

    worst_stop_fill, risk_per_unit, reward_per_unit = _per_unit_economics(
        side="long",
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        stop_gap_rate=stop_gap_rate,
        costs=costs,
    )
    if worst_stop_fill <= 0.0 or risk_per_unit <= 0.0:
        _add_reason(reasons, "stress_loss_not_positive")
    reward_risk_ratio = (
        reward_per_unit / risk_per_unit if risk_per_unit > 0.0 else None
    )
    if reward_risk_ratio is None or not _finite(reward_risk_ratio):
        _add_reason(reasons, "reward_risk_ratio_invalid")
    elif reward_risk_ratio + _EPSILON < policy.minimum_reward_risk_ratio:
        _add_reason(reasons, "minimum_reward_risk_ratio_not_met")
    if reasons:
        return _blocked_size_decision(
            instrument="spot",
            side="long",
            reasons=reasons,
            requested_risk_budget_usdt=requested_budget,
            effective_risk_cap_usdt=effective_cap,
            leverage=1.0,
            worst_stop_fill_price=worst_stop_fill,
            risk_per_unit_usdt=risk_per_unit,
            reward_per_unit_usdt=reward_per_unit,
            reward_risk_ratio=reward_risk_ratio,
        )

    risk_quantity = requested_budget / risk_per_unit
    notional_quantity = policy.maximum_spot_notional_usdt / entry_price
    quantity = _floor_to_step(min(risk_quantity, notional_quantity), quantity_step)
    notional = quantity * entry_price
    stress_loss = quantity * risk_per_unit
    net_reward = quantity * reward_per_unit
    if quantity <= 0.0:
        _add_reason(reasons, "quantity_below_step")
    if notional + _EPSILON < minimum_notional_usdt:
        _add_reason(reasons, "notional_below_exchange_minimum")
    if notional > policy.maximum_spot_notional_usdt + _EPSILON:
        _add_reason(reasons, "maximum_spot_notional_exceeded")
    if stress_loss > requested_budget + _EPSILON:
        _add_reason(reasons, "risk_budget_exceeded_after_rounding")
    if reasons:
        return _blocked_size_decision(
            instrument="spot",
            side="long",
            reasons=reasons,
            requested_risk_budget_usdt=requested_budget,
            effective_risk_cap_usdt=effective_cap,
            leverage=1.0,
            worst_stop_fill_price=worst_stop_fill,
            risk_per_unit_usdt=risk_per_unit,
            reward_per_unit_usdt=reward_per_unit,
            reward_risk_ratio=reward_risk_ratio,
        )
    return PositionSizeDecision(
        instrument="spot",
        side="long",
        allowed=True,
        reasons=(),
        requested_risk_budget_usdt=requested_budget,
        effective_risk_cap_usdt=effective_cap,
        quantity=quantity,
        notional_usdt=notional,
        leverage=1.0,
        isolated_margin_usdt=notional,
        worst_stop_fill_price=worst_stop_fill,
        risk_per_unit_usdt=risk_per_unit,
        reward_per_unit_usdt=reward_per_unit,
        reward_risk_ratio=reward_risk_ratio,
        estimated_stress_loss_usdt=stress_loss,
        estimated_net_reward_usdt=net_reward,
    )


@dataclass(frozen=True)
class AccountRiskSnapshot:
    net_liquidation_equity_usdt: float
    high_water_equity_usdt: float
    day_start_equity_usdt: float
    rolling_24h_start_equity_usdt: float
    open_stress_risk_usdt: float = 0.0
    pending_stress_risk_usdt: float = 0.0
    crypto_beta_directions: tuple[str, ...] = ()
    unprotected_position_count: int = 0
    has_unknown_state: bool = False
    state_is_stale: bool = False
    protective_cycle_verified: bool = False


@dataclass(frozen=True)
class AccountGuardDecision:
    allow_new_risk: bool
    flatten_required: bool
    risk_reduction_required: bool
    halt_required: bool
    reconciliation_required: bool
    disaster_limit_breached: bool
    active_risk_cap_usdt: float
    total_stress_risk_after_request_usdt: float
    remaining_stress_risk_capacity_usdt: float
    high_water_drawdown_usdt: float
    day_loss_usdt: float
    rolling_24h_loss_usdt: float
    reasons: tuple[str, ...]


def _snapshot_validation_reasons(
    snapshot: AccountRiskSnapshot,
    policy: SmallAccountRiskPolicy,
) -> list[str]:
    reasons = list(policy.validate())
    for field_name in (
        "net_liquidation_equity_usdt",
        "high_water_equity_usdt",
        "day_start_equity_usdt",
        "rolling_24h_start_equity_usdt",
        "open_stress_risk_usdt",
        "pending_stress_risk_usdt",
    ):
        raw_value = getattr(snapshot, field_name)
        if not _finite(raw_value):
            _add_reason(reasons, f"{field_name}_invalid")
    if reasons:
        return reasons
    if snapshot.net_liquidation_equity_usdt < 0.0:
        reasons.append("net_liquidation_equity_usdt_invalid")
    for field_name in (
        "high_water_equity_usdt",
        "day_start_equity_usdt",
        "rolling_24h_start_equity_usdt",
    ):
        if float(getattr(snapshot, field_name)) <= 0.0:
            _add_reason(reasons, f"{field_name}_invalid")
    for field_name in ("open_stress_risk_usdt", "pending_stress_risk_usdt"):
        if float(getattr(snapshot, field_name)) < 0.0:
            _add_reason(reasons, f"{field_name}_invalid")
    if (
        snapshot.high_water_equity_usdt + _EPSILON
        < snapshot.net_liquidation_equity_usdt
    ):
        reasons.append("high_water_below_current_equity")
    if snapshot.high_water_equity_usdt + _EPSILON < policy.initial_equity_usdt:
        reasons.append("high_water_below_initial_equity")
    if (
        not isinstance(snapshot.unprotected_position_count, int)
        or isinstance(snapshot.unprotected_position_count, bool)
        or snapshot.unprotected_position_count < 0
    ):
        reasons.append("unprotected_position_count_invalid")
    for field_name in (
        "has_unknown_state",
        "state_is_stale",
        "protective_cycle_verified",
    ):
        if not isinstance(getattr(snapshot, field_name), bool):
            _add_reason(reasons, f"{field_name}_invalid")
    if not isinstance(snapshot.crypto_beta_directions, tuple):
        reasons.append("crypto_beta_directions_invalid")
    else:
        for direction in snapshot.crypto_beta_directions:
            if direction not in _BETA_DIRECTIONS:
                _add_reason(reasons, f"crypto_beta_direction_invalid:{direction}")
        if (
            len(snapshot.crypto_beta_directions)
            > policy.maximum_crypto_beta_exposures
        ):
            reasons.append("crypto_beta_exposure_limit_exceeded")
        if (
            snapshot.open_stress_risk_usdt + snapshot.pending_stress_risk_usdt
            > _EPSILON
            and not snapshot.crypto_beta_directions
        ):
            reasons.append("crypto_beta_direction_missing_for_existing_risk")
    return reasons


def evaluate_account_guard(
    snapshot: AccountRiskSnapshot,
    *,
    requested_new_risk_usdt: float = 0.0,
    requested_crypto_beta_direction: str | None = None,
    policy: SmallAccountRiskPolicy = DEFAULT_SMALL_ACCOUNT_POLICY,
) -> AccountGuardDecision:
    """Evaluate account risk without mutating positions, orders, or state."""

    reasons = _snapshot_validation_reasons(snapshot, policy)
    invalid_snapshot = bool(reasons)
    if not _finite(requested_new_risk_usdt) or requested_new_risk_usdt < 0.0:
        _add_reason(reasons, "requested_new_risk_usdt_invalid")
        invalid_snapshot = True
    if (
        requested_crypto_beta_direction is not None
        and requested_crypto_beta_direction not in _BETA_DIRECTIONS
    ):
        _add_reason(
            reasons,
            f"requested_crypto_beta_direction_invalid:{requested_crypto_beta_direction}",
        )
        invalid_snapshot = True

    active_cap = policy.active_trade_risk_cap(snapshot.protective_cycle_verified)
    values_valid = not invalid_snapshot
    if values_valid:
        high_water_drawdown = max(
            0.0,
            snapshot.high_water_equity_usdt
            - snapshot.net_liquidation_equity_usdt,
        )
        day_loss = max(
            0.0,
            snapshot.day_start_equity_usdt
            - snapshot.net_liquidation_equity_usdt,
        )
        rolling_loss = max(
            0.0,
            snapshot.rolling_24h_start_equity_usdt
            - snapshot.net_liquidation_equity_usdt,
        )
        total_risk = (
            snapshot.open_stress_risk_usdt
            + snapshot.pending_stress_risk_usdt
            + requested_new_risk_usdt
        )
    else:
        high_water_drawdown = math.inf
        day_loss = math.inf
        rolling_loss = math.inf
        total_risk = math.inf

    flatten_required = False
    risk_reduction_required = False
    halt_required = invalid_snapshot
    reconciliation_required = invalid_snapshot
    disaster_breached = False

    if snapshot.has_unknown_state:
        _add_reason(reasons, "account_or_order_state_unknown")
        halt_required = True
        reconciliation_required = True
    if snapshot.state_is_stale:
        _add_reason(reasons, "account_or_market_state_stale")
        halt_required = True
        reconciliation_required = True
    if (
        isinstance(snapshot.unprotected_position_count, int)
        and not isinstance(snapshot.unprotected_position_count, bool)
        and snapshot.unprotected_position_count > 0
    ):
        _add_reason(reasons, "unprotected_position")
        flatten_required = True
        risk_reduction_required = True
        halt_required = True
        reconciliation_required = True
    if (
        isinstance(snapshot.crypto_beta_directions, tuple)
        and isinstance(policy.maximum_crypto_beta_exposures, int)
        and not isinstance(policy.maximum_crypto_beta_exposures, bool)
        and len(snapshot.crypto_beta_directions)
        > policy.maximum_crypto_beta_exposures
    ):
        flatten_required = True
        risk_reduction_required = True
        halt_required = True
        reconciliation_required = True

    if values_valid:
        if requested_new_risk_usdt > policy.per_trade_risk_cap_usdt + _EPSILON:
            _add_reason(reasons, "per_trade_risk_cap_exceeded")
        if requested_new_risk_usdt > active_cap + _EPSILON:
            if snapshot.protective_cycle_verified:
                _add_reason(reasons, "active_trade_risk_cap_exceeded")
            else:
                _add_reason(reasons, "first_live_risk_cap_exceeded")
        active_concurrent_cap = (
            policy.concurrent_stress_risk_cap_usdt
            if snapshot.protective_cycle_verified
            else min(policy.concurrent_stress_risk_cap_usdt, active_cap)
        )
        existing_risk = (
            snapshot.open_stress_risk_usdt + snapshot.pending_stress_risk_usdt
        )
        if total_risk > active_concurrent_cap + _EPSILON:
            _add_reason(reasons, "concurrent_stress_risk_cap_exceeded")
            if existing_risk > active_concurrent_cap + _EPSILON:
                risk_reduction_required = True
                flatten_required = True

        existing_exposure_count = len(snapshot.crypto_beta_directions)
        if requested_new_risk_usdt > _EPSILON and requested_crypto_beta_direction is None:
            _add_reason(reasons, "requested_crypto_beta_direction_required")
        if (
            requested_new_risk_usdt > _EPSILON
            and existing_exposure_count + 1 > policy.maximum_crypto_beta_exposures
        ):
            _add_reason(reasons, "crypto_beta_exposure_limit_exceeded")
        directions = set(snapshot.crypto_beta_directions)
        if requested_crypto_beta_direction is not None:
            directions.add(requested_crypto_beta_direction)
        if len(directions) > 1:
            _add_reason(reasons, "crypto_beta_direction_limit_exceeded")
        if existing_exposure_count > policy.maximum_crypto_beta_exposures:
            risk_reduction_required = True
            flatten_required = True
            halt_required = True

        if day_loss + total_risk > policy.rolling_24h_loss_limit_usdt + _EPSILON:
            _add_reason(reasons, "day_loss_budget_exceeded")
            if day_loss + existing_risk > policy.rolling_24h_loss_limit_usdt + _EPSILON:
                risk_reduction_required = True
                flatten_required = True
        if rolling_loss + total_risk > policy.rolling_24h_loss_limit_usdt + _EPSILON:
            _add_reason(reasons, "rolling_24h_loss_budget_exceeded")
            if rolling_loss + existing_risk > policy.rolling_24h_loss_limit_usdt + _EPSILON:
                risk_reduction_required = True
                flatten_required = True
        if high_water_drawdown + total_risk > policy.strategy_drawdown_limit_usdt + _EPSILON:
            _add_reason(reasons, "strategy_drawdown_budget_exceeded")
            if high_water_drawdown + existing_risk > policy.strategy_drawdown_limit_usdt + _EPSILON:
                risk_reduction_required = True
                flatten_required = True

        if (
            day_loss + _EPSILON >= policy.rolling_24h_loss_limit_usdt
            or rolling_loss + _EPSILON >= policy.rolling_24h_loss_limit_usdt
        ):
            if day_loss + _EPSILON >= policy.rolling_24h_loss_limit_usdt:
                _add_reason(reasons, "day_loss_limit_reached")
            if rolling_loss + _EPSILON >= policy.rolling_24h_loss_limit_usdt:
                _add_reason(reasons, "rolling_24h_loss_limit_reached")
            flatten_required = True
            risk_reduction_required = True
            halt_required = True
        if high_water_drawdown + _EPSILON >= policy.strategy_drawdown_limit_usdt:
            _add_reason(reasons, "strategy_drawdown_limit_reached")
            flatten_required = True
            risk_reduction_required = True
        if high_water_drawdown + _EPSILON >= policy.emergency_drawdown_limit_usdt:
            _add_reason(reasons, "emergency_drawdown_limit_reached")
            flatten_required = True
            risk_reduction_required = True
            halt_required = True
        if high_water_drawdown + _EPSILON >= policy.disaster_drawdown_limit_usdt:
            _add_reason(reasons, "disaster_drawdown_limit_reached")
            flatten_required = True
            risk_reduction_required = True
            halt_required = True
            disaster_breached = True

    if values_valid:
        active_concurrent_cap = (
            policy.concurrent_stress_risk_cap_usdt
            if snapshot.protective_cycle_verified
            else min(policy.concurrent_stress_risk_cap_usdt, active_cap)
        )
        existing_risk = (
            snapshot.open_stress_risk_usdt + snapshot.pending_stress_risk_usdt
        )
        remaining_capacity = max(
            0.0,
            min(
                active_concurrent_cap - existing_risk,
                policy.rolling_24h_loss_limit_usdt - day_loss - existing_risk,
                policy.rolling_24h_loss_limit_usdt - rolling_loss - existing_risk,
                policy.strategy_drawdown_limit_usdt
                - high_water_drawdown
                - existing_risk,
            ),
        )
    else:
        remaining_capacity = 0.0
    allow_new_risk = not reasons
    return AccountGuardDecision(
        allow_new_risk=allow_new_risk,
        flatten_required=flatten_required,
        risk_reduction_required=risk_reduction_required,
        halt_required=halt_required,
        reconciliation_required=reconciliation_required,
        disaster_limit_breached=disaster_breached,
        active_risk_cap_usdt=active_cap,
        total_stress_risk_after_request_usdt=total_risk,
        remaining_stress_risk_capacity_usdt=remaining_capacity,
        high_water_drawdown_usdt=high_water_drawdown,
        day_loss_usdt=day_loss,
        rolling_24h_loss_usdt=rolling_loss,
        reasons=tuple(reasons),
    )
