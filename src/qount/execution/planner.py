"""Pure current-position to target-position planning."""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping

from qount.contracts import MarketSnapshot
from qount.contracts import InstrumentId
from qount.contracts import OrderPlan
from qount.contracts import PlannedOrder
from qount.contracts import PortfolioTarget
from qount.contracts import ProductCapability
from qount.contracts import RiskDecision
from qount.contracts import canonical_hash


def _floor_to_step(value: float, step: float) -> float:
    units = (Decimal(str(value)) / Decimal(str(step))).to_integral_value(
        rounding=ROUND_DOWN
    )
    return float(units * Decimal(str(step)))


def _validated_rule(
    symbol: str,
    rules: Mapping[str, Mapping[str, float]],
) -> tuple[dict[str, float] | None, tuple[str, ...]]:
    raw = rules.get(symbol)
    if not isinstance(raw, Mapping):
        return None, (f"symbol_rule_missing:{symbol}",)
    values: dict[str, float] = {}
    errors: list[str] = []
    for name in ("step_size", "minimum_quantity", "minimum_notional"):
        try:
            value = float(raw.get(name, 0.0))
        except (TypeError, ValueError):
            value = math.nan
        minimum = 0.0 if name == "minimum_notional" else 1e-18
        if not math.isfinite(value) or value < minimum:
            errors.append(f"symbol_rule_{name}_invalid:{symbol}")
        values[name] = value
    return (values if not errors else None), tuple(errors)


def build_portfolio_order_plan(
    snapshot: MarketSnapshot,
    target: PortfolioTarget,
    risk: RiskDecision,
    *,
    current_positions: Mapping[str, float],
    account_equity_usdt: float,
    symbol_rules: Mapping[str, Mapping[str, float]],
    instruments: Mapping[str, InstrumentId] | None = None,
    product_capabilities: Mapping[str, ProductCapability] | None = None,
) -> OrderPlan:
    """Build deterministic reduce-before-increase market orders.

    This function only creates an ``OrderPlan``. It has no exchange adapter and
    cannot route the plan.
    """

    blockers: list[str] = []
    blockers.extend(f"snapshot:{error}" for error in snapshot.validate())
    blockers.extend(f"target:{error}" for error in target.validate())
    blockers.extend(f"risk:{error}" for error in risk.validate())
    if target.snapshot_id != snapshot.snapshot_id:
        blockers.append("order_planner_snapshot_target_mismatch")
    if risk.portfolio_target_id != target.portfolio_target_id:
        blockers.append("order_planner_risk_target_mismatch")
    if not risk.approved or risk.violations:
        blockers.extend(risk.violations or ("risk_decision_not_approved",))
    try:
        equity = float(account_equity_usdt)
    except (TypeError, ValueError):
        equity = math.nan
    if not math.isfinite(equity) or equity <= 0.0:
        blockers.append("order_planner_account_equity_invalid")

    normalized_instruments: dict[str, InstrumentId] = {}
    for raw_key, instrument in sorted(
        (instruments or {}).items(), key=lambda item: str(item[0])
    ):
        key = str(raw_key)
        if (
            not isinstance(instrument, InstrumentId)
            or instrument.validate()
            or key != instrument.instrument_key
        ):
            blockers.append(f"order_planner_instrument_invalid:{key}")
            continue
        normalized_instruments[key] = instrument

    normalized_capabilities: dict[str, ProductCapability] = {}
    for raw_key, capability in sorted(
        (product_capabilities or {}).items(), key=lambda item: str(item[0])
    ):
        key = str(raw_key)
        if (
            not isinstance(capability, ProductCapability)
            or capability.validate()
            or key != capability.instrument_key
        ):
            blockers.append(f"order_planner_product_capability_invalid:{key}")
            continue
        normalized_capabilities[key] = capability

    explicit_product_contracts = instruments is not None or product_capabilities is not None
    current: dict[str, float] = {}
    for symbol, raw_quantity in current_positions.items():
        try:
            quantity = float(raw_quantity)
        except (TypeError, ValueError):
            quantity = math.nan
        if not symbol or not math.isfinite(quantity):
            blockers.append(f"order_planner_current_position_invalid:{symbol}")
        else:
            current[str(symbol)] = quantity

    symbols = sorted(set(current) | set(risk.approved_target))
    rows: list[dict[str, Any]] = []
    tolerances: dict[str, float] = {}
    expected = dict(current)
    for symbol in symbols:
        rule, rule_errors = _validated_rule(symbol, symbol_rules)
        blockers.extend(rule_errors)
        try:
            price = float(snapshot.prices[symbol])
            weight = float(risk.approved_target.get(symbol, 0.0))
        except (KeyError, TypeError, ValueError):
            blockers.append(f"order_planner_target_input_invalid:{symbol}")
            continue
        if not math.isfinite(price) or price <= 0.0 or not math.isfinite(weight):
            blockers.append(f"order_planner_target_input_invalid:{symbol}")
            continue
        if rule is None:
            continue
        step = rule["step_size"]
        instrument = normalized_instruments.get(symbol)
        multiplier = 1.0 if instrument is None else instrument.multiplier
        target_quantity = math.copysign(
            _floor_to_step(equity * abs(weight) / (price * multiplier), step),
            weight,
        )
        if abs(target_quantity) <= 1e-15:
            target_quantity = 0.0
        projected_quantity = current.get(symbol, 0.0)
        tolerances[symbol] = step

        def append_delta(
            raw_delta: float,
            *,
            phase: str,
            exposure_side: str | None = None,
        ) -> None:
            nonlocal projected_quantity
            quantity = _floor_to_step(abs(raw_delta), step)
            if quantity <= 1e-15:
                return
            side = "buy" if raw_delta > 0.0 else "sell"
            if quantity + 1e-12 < rule["minimum_quantity"]:
                blockers.append(f"order_quantity_below_minimum:{symbol}")
            if quantity * price * multiplier + 1e-12 < rule["minimum_notional"]:
                blockers.append(f"order_notional_below_minimum:{symbol}")
            capability = normalized_capabilities.get(symbol)
            if capability is not None:
                if "MARKET" not in capability.order_types:
                    blockers.append(f"market_order_not_supported:{symbol}")
                if side == "buy" and not capability.buy_allowed:
                    blockers.append(f"product_buy_not_allowed:{symbol}")
                if side == "sell" and not capability.sell_allowed:
                    blockers.append(f"product_sell_not_allowed:{symbol}")
            if phase == "increase":
                if not risk.increase_risk_allowed:
                    blockers.append(f"risk_increase_not_allowed:{symbol}")
                requires_contract = explicit_product_contracts or exposure_side == "short"
                if requires_contract and instrument is None:
                    blockers.append(f"product_instrument_missing:{symbol}")
                if requires_contract and capability is None:
                    blockers.append(f"product_capability_missing:{symbol}")
                elif capability is not None and exposure_side == "long" and (
                    not capability.long_allowed or not capability.buy_allowed
                ):
                    blockers.append(f"product_long_not_allowed:{symbol}")
                elif capability is not None and exposure_side == "short" and (
                    not capability.short_allowed
                    or not capability.sell_allowed
                    or capability.sell_close_only
                ):
                    blockers.append(f"product_short_not_allowed:{symbol}")
            elif not risk.reduce_risk_allowed:
                blockers.append(f"risk_reduction_not_allowed:{symbol}")
            rows.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "phase": phase,
                }
            )
            projected_quantity += quantity if side == "buy" else -quantity
            if abs(projected_quantity) <= 1e-15:
                projected_quantity = 0.0

        current_quantity = current.get(symbol, 0.0)
        if current_quantity * target_quantity < -1e-15:
            append_delta(-current_quantity, phase="reduce")
            append_delta(
                target_quantity - projected_quantity,
                phase="increase",
                exposure_side="long" if target_quantity > 0.0 else "short",
            )
        else:
            delta = target_quantity - current_quantity
            phase = (
                "increase"
                if abs(target_quantity) > abs(current_quantity) + 1e-15
                else "reduce"
            )
            append_delta(
                delta,
                phase=phase,
                exposure_side=(
                    "long"
                    if phase == "increase" and target_quantity > 0.0
                    else "short"
                    if phase == "increase" and target_quantity < 0.0
                    else None
                ),
            )
        expected[symbol] = projected_quantity

    normalized_blockers = tuple(sorted(set(blockers)))
    current_position_hash = canonical_hash(
        {
            "current_positions": dict(sorted(current.items())),
            "account_equity_usdt": equity,
            "snapshot_hash": snapshot.snapshot_hash,
            "symbol_rules": {
                symbol: dict(sorted(rule.items()))
                for symbol, rule in sorted(symbol_rules.items())
            },
            "instruments": {
                key: value.instrument_hash
                for key, value in sorted(normalized_instruments.items())
            },
            "product_capabilities": {
                key: value.capability_hash
                for key, value in sorted(normalized_capabilities.items())
            },
        }
    )
    if normalized_blockers:
        return OrderPlan.create(
            batch_id=risk.batch_id,
            risk_decision_id=risk.risk_decision_id,
            portfolio_target_id=target.portfolio_target_id,
            snapshot_id=snapshot.snapshot_id,
            decision_ids=target.decision_ids,
            created_at=target.decision_time,
            current_position_hash=current_position_hash,
            approved_target=risk.approved_target,
            orders=(),
            expected_positions=dict(sorted(current.items())),
            reconciliation_tolerance={
                symbol: tolerances.get(symbol, 0.0) for symbol in sorted(current)
            },
            blockers=normalized_blockers,
            executable=False,
        )

    ordered_rows = sorted(
        rows,
        key=lambda row: (0 if row["phase"] == "reduce" else 1, row["symbol"]),
    )
    orders = tuple(
        PlannedOrder.create(
            batch_id=risk.batch_id,
            decision_ids=target.decision_ids,
            symbol=str(row["symbol"]),
            side=str(row["side"]),
            quantity=float(row["quantity"]),
            reduce_only=row["phase"] == "reduce",
            phase=str(row["phase"]),
            sequence=index,
        )
        for index, row in enumerate(ordered_rows, start=1)
    )
    return OrderPlan.create(
        batch_id=risk.batch_id,
        risk_decision_id=risk.risk_decision_id,
        portfolio_target_id=target.portfolio_target_id,
        snapshot_id=snapshot.snapshot_id,
        decision_ids=target.decision_ids,
        created_at=target.decision_time,
        current_position_hash=current_position_hash,
        approved_target=risk.approved_target,
        orders=orders,
        expected_positions={symbol: expected.get(symbol, 0.0) for symbol in symbols},
        reconciliation_tolerance={symbol: tolerances[symbol] for symbol in symbols},
        blockers=(),
        executable=True,
    )
