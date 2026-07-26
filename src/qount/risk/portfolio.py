"""Deterministic portfolio risk decisions for standard runtime contracts."""

from __future__ import annotations

import math
from typing import Any, Mapping

from qount.contracts import MarketSnapshot
from qount.contracts import InstrumentId
from qount.contracts import PortfolioTarget
from qount.contracts import ProductCapability
from qount.contracts import RiskDecision
from qount.contracts import canonical_hash
from qount.contracts import trace_id


def build_portfolio_risk_decision(
    snapshot: MarketSnapshot,
    target: PortfolioTarget,
    *,
    current_positions: Mapping[str, float],
    account_equity_usdt: float,
    maximum_portfolio_gross: float = 1.0,
    maximum_weight_by_symbol: Mapping[str, float] | None = None,
    risk_source_hashes: Mapping[str, str] | None = None,
    instruments: Mapping[str, InstrumentId] | None = None,
    product_capabilities: Mapping[str, ProductCapability] | None = None,
) -> RiskDecision:
    """Validate one allocated target without granting any order authority."""

    violations: list[str] = []
    adjustments: list[str] = []
    violations.extend(f"snapshot:{error}" for error in snapshot.validate())
    violations.extend(f"target:{error}" for error in target.validate())
    if target.snapshot_id != snapshot.snapshot_id:
        violations.append("portfolio_risk_snapshot_target_mismatch")
    if not target.allocatable or target.blockers:
        violations.extend(
            f"portfolio_target_blocked:{blocker}"
            for blocker in target.blockers or ("not_allocatable",)
        )
    if snapshot.data_quality.get("complete") is not True:
        violations.append("market_snapshot_incomplete")

    try:
        equity = float(account_equity_usdt)
    except (TypeError, ValueError):
        equity = math.nan
    if not math.isfinite(equity) or equity <= 0.0:
        violations.append("account_equity_invalid")

    try:
        maximum_gross = float(maximum_portfolio_gross)
    except (TypeError, ValueError):
        maximum_gross = math.nan
    if not math.isfinite(maximum_gross) or not 0.0 < maximum_gross <= 1.0:
        violations.append("maximum_portfolio_gross_invalid")

    normalized_instruments: dict[str, InstrumentId] = {}
    for raw_key, instrument in sorted(
        (instruments or {}).items(), key=lambda item: str(item[0])
    ):
        key = str(raw_key)
        if not isinstance(instrument, InstrumentId):
            violations.append(f"portfolio_risk_instrument_invalid:{key}")
            continue
        errors = instrument.validate()
        if errors or key != instrument.instrument_key:
            violations.append(f"portfolio_risk_instrument_invalid:{key}")
            continue
        normalized_instruments[key] = instrument

    normalized_capabilities: dict[str, ProductCapability] = {}
    for raw_key, capability in sorted(
        (product_capabilities or {}).items(), key=lambda item: str(item[0])
    ):
        key = str(raw_key)
        if not isinstance(capability, ProductCapability):
            violations.append(f"portfolio_risk_product_capability_invalid:{key}")
            continue
        errors = capability.validate()
        if errors or key != capability.instrument_key:
            violations.append(f"portfolio_risk_product_capability_invalid:{key}")
            continue
        normalized_capabilities[key] = capability

    positions: dict[str, float] = {}
    current_gross_notional = 0.0
    for symbol, raw_quantity in current_positions.items():
        try:
            quantity = float(raw_quantity)
            price = float(snapshot.prices[symbol])
        except (KeyError, TypeError, ValueError):
            violations.append(f"current_position_unpriced:{symbol}")
            continue
        if (
            not symbol
            or not math.isfinite(quantity)
            or not math.isfinite(price)
            or price <= 0.0
        ):
            violations.append(f"current_position_invalid:{symbol}")
            continue
        positions[str(symbol)] = quantity
        multiplier = normalized_instruments.get(str(symbol))
        current_gross_notional += abs(
            quantity * price * (1.0 if multiplier is None else multiplier.multiplier)
        )

    target_gross = sum(abs(float(weight)) for weight in target.target_weights.values())
    if math.isfinite(maximum_gross) and target_gross > maximum_gross + 1e-12:
        violations.append("portfolio_risk_gross_limit_exceeded")
    symbol_caps = dict(maximum_weight_by_symbol or {})
    normalized_symbol_caps: dict[str, float | None] = {}
    for raw_symbol, raw_cap in sorted(symbol_caps.items(), key=lambda item: str(item[0])):
        symbol = str(raw_symbol)
        try:
            cap = float(raw_cap)
        except (TypeError, ValueError):
            cap = math.nan
        normalized_symbol_caps[symbol] = cap if math.isfinite(cap) else None
        if (
            not symbol
            or not math.isfinite(maximum_gross)
            or not math.isfinite(cap)
            or not 0.0 <= cap <= maximum_gross
        ):
            violations.append(f"portfolio_risk_symbol_cap_invalid:{symbol}")
    for symbol, raw_weight in target.target_weights.items():
        if symbol not in snapshot.prices:
            violations.append(f"portfolio_risk_target_unpriced:{symbol}")
            continue
        if symbol not in normalized_symbol_caps:
            normalized_symbol_caps[symbol] = (
                maximum_gross if math.isfinite(maximum_gross) else None
            )
        cap = normalized_symbol_caps.get(symbol, maximum_gross)
        if cap is None or not math.isfinite(maximum_gross):
            violations.append(f"portfolio_risk_symbol_cap_invalid:{symbol}")
        elif abs(float(raw_weight)) > cap + 1e-12:
            violations.append(f"portfolio_risk_symbol_cap_exceeded:{symbol}")

    explicit_product_contracts = instruments is not None or product_capabilities is not None
    if math.isfinite(equity) and equity > 0.0:
        for symbol, raw_target_weight in target.target_weights.items():
            try:
                target_weight = float(raw_target_weight)
                price = float(snapshot.prices[symbol])
            except (KeyError, TypeError, ValueError):
                continue
            instrument = normalized_instruments.get(symbol)
            multiplier = 1.0 if instrument is None else instrument.multiplier
            current_weight = positions.get(symbol, 0.0) * price * multiplier / equity
            long_increase = max(target_weight, 0.0) > max(current_weight, 0.0) + 1e-12
            short_increase = max(-target_weight, 0.0) > max(-current_weight, 0.0) + 1e-12
            if not long_increase and not short_increase:
                continue
            requires_contract = explicit_product_contracts or short_increase
            capability = normalized_capabilities.get(symbol)
            if requires_contract and instrument is None:
                violations.append(f"portfolio_risk_instrument_missing:{symbol}")
            if requires_contract and capability is None:
                violations.append(f"portfolio_risk_product_capability_missing:{symbol}")
                continue
            if capability is None:
                continue
            if long_increase and (
                not capability.long_allowed or not capability.buy_allowed
            ):
                violations.append(f"portfolio_risk_long_not_allowed:{symbol}")
            if short_increase and (
                not capability.short_allowed
                or not capability.sell_allowed
                or capability.sell_close_only
            ):
                violations.append(f"portfolio_risk_short_not_allowed:{symbol}")

    current_gross_fraction = (
        current_gross_notional / equity
        if math.isfinite(equity) and equity > 0.0
        else math.inf
    )
    increase_risk_allowed = True
    if (
        math.isfinite(maximum_gross)
        and current_gross_fraction > maximum_gross + 1e-12
    ):
        adjustments.append("CURRENT_GROSS_ABOVE_LIMIT_REDUCTIONS_ONLY")
        increase_risk_allowed = False

    normalized_violations = tuple(sorted(set(violations)))
    normalized_adjustments = tuple(sorted(set(adjustments)))
    approved = not normalized_violations
    symbols = sorted(set(target.target_weights) | set(positions))
    approved_target = (
        dict(target.target_weights)
        if approved
        else {symbol: 0.0 for symbol in symbols}
    )
    policy = {
        "maximum_portfolio_gross": (
            maximum_gross if math.isfinite(maximum_gross) else None
        ),
        "maximum_weight_by_symbol": dict(sorted(normalized_symbol_caps.items())),
    }
    state = {
        "snapshot_hash": snapshot.snapshot_hash,
        "portfolio_target_hash": target.target_hash,
        "current_positions": dict(sorted(positions.items())),
        "account_equity_usdt": equity,
        "current_gross_fraction": current_gross_fraction,
        "policy": policy,
        "risk_source_hashes": dict(sorted((risk_source_hashes or {}).items())),
        "instruments": {
            key: value.instrument_hash
            for key, value in sorted(normalized_instruments.items())
        },
        "product_capabilities": {
            key: value.capability_hash
            for key, value in sorted(normalized_capabilities.items())
        },
    }
    risk_state_hash = canonical_hash(state)
    batch_id = trace_id(
        "decision_batch",
        {
            "snapshot_id": snapshot.snapshot_id,
            "portfolio_target_id": target.portfolio_target_id,
            "risk_state_hash": risk_state_hash,
        },
    )
    return RiskDecision.create(
        batch_id=batch_id,
        portfolio_target_id=target.portfolio_target_id,
        decision_time=target.decision_time,
        approved=approved,
        input_target=target.target_weights,
        approved_target=approved_target,
        adjustments=normalized_adjustments,
        violations=normalized_violations,
        risk_state_hash=risk_state_hash,
        increase_risk_allowed=approved and increase_risk_allowed,
        reduce_risk_allowed=True,
    )
