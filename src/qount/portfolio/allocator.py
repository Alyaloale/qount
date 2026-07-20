"""Deterministic, fail-closed aggregation of strategy intents."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from qount.contracts import StrategyIntent
from qount.contracts import canonical_hash
from qount.contracts import PortfolioTarget
from qount.portfolio.models import SleeveRiskBudget
from qount.portfolio.models import scale_standalone_weights


def allocate_strategy_intents(
    intents: Sequence[StrategyIntent],
    budgets: Sequence[SleeveRiskBudget],
    *,
    account_equity_usdt: float,
    allowed_strategy_ids: Sequence[str],
    minimum_notional_by_symbol: Mapping[str, float] | None = None,
    maximum_weight_by_symbol: Mapping[str, float] | None = None,
    correlation_cluster_by_symbol: Mapping[str, str] | None = None,
    maximum_positions_per_cluster: int = 2,
    maximum_portfolio_gross: float = 1.0,
) -> dict[str, Any]:
    """Scale and aggregate intents, failing the entire batch closed on any error."""

    blockers: list[str] = []
    if not math.isfinite(account_equity_usdt) or account_equity_usdt <= 0.0:
        blockers.append("account_equity_invalid")
    if not 0.0 < maximum_portfolio_gross <= 1.0:
        blockers.append("maximum_portfolio_gross_invalid")
    if maximum_positions_per_cluster < 1:
        blockers.append("maximum_positions_per_cluster_invalid")

    allowed = set(allowed_strategy_ids)
    intent_ids = [intent.strategy_id for intent in intents]
    budget_ids = [budget.strategy_id for budget in budgets]
    if not intents:
        blockers.append("strategy_intents_empty")
    if len(intent_ids) != len(set(intent_ids)):
        blockers.append("duplicate_strategy_intent")
    if len(budget_ids) != len(set(budget_ids)):
        blockers.append("duplicate_strategy_risk_budget")
    if set(intent_ids) != set(budget_ids):
        blockers.append("strategy_intent_budget_mismatch")
    for strategy_id in intent_ids:
        if strategy_id not in allowed:
            blockers.append(f"strategy_not_allowlisted:{strategy_id}")

    decision_times = {intent.decision_time for intent in intents}
    if len(decision_times) > 1:
        blockers.append("mixed_decision_times_in_batch")

    budget_by_id = {budget.strategy_id: budget for budget in budgets}
    maximum_weights = dict(maximum_weight_by_symbol or {})
    minimum_notionals = dict(minimum_notional_by_symbol or {})
    clusters = dict(correlation_cluster_by_symbol or {})
    sleeve_rows: list[dict[str, Any]] = []
    proposed: dict[str, float] = {}
    for intent in intents:
        for error in intent.validate():
            blockers.append(f"intent:{intent.strategy_id}:{error}")
        try:
            budget = budget_by_id[intent.strategy_id]
            scalar = budget.risk_scalar()
            scaled = scale_standalone_weights(intent.target_weights, budget)
        except (KeyError, TypeError, ValueError) as exc:
            blockers.append(f"risk_budget:{intent.strategy_id}:{exc}")
            scalar = 0.0
            scaled = {symbol: 0.0 for symbol in intent.target_weights}
        for symbol, weight in scaled.items():
            proposed[symbol] = proposed.get(symbol, 0.0) + float(weight)
            minimum = float(minimum_notionals.get(symbol, 0.0))
            if weight > 0.0 and account_equity_usdt * weight < minimum:
                blockers.append(
                    f"sleeve_target_below_minimum_notional:{intent.strategy_id}:{symbol}"
                )
        sleeve_rows.append(
            {
                "strategy_id": intent.strategy_id,
                "risk_scalar": scalar,
                "standalone_target_weights": dict(intent.target_weights),
                "scaled_target_weights": scaled,
                "evidence_hash": intent.evidence_hash,
                "state_hash": intent.state_hash,
            }
        )

    gross = sum(abs(weight) for weight in proposed.values())
    if gross > maximum_portfolio_gross + 1e-12:
        blockers.append("portfolio_gross_limit_exceeded")

    cluster_symbols: dict[str, list[str]] = {}
    for symbol, weight in proposed.items():
        maximum = float(maximum_weights.get(symbol, maximum_portfolio_gross))
        minimum = float(minimum_notionals.get(symbol, 0.0))
        if not math.isfinite(maximum) or not 0.0 <= maximum <= maximum_portfolio_gross:
            blockers.append(f"symbol_weight_cap_invalid:{symbol}")
        elif weight > maximum + 1e-12:
            blockers.append(f"symbol_weight_cap_exceeded:{symbol}")
        if not math.isfinite(minimum) or minimum < 0.0:
            blockers.append(f"minimum_notional_invalid:{symbol}")
        elif weight > 0.0 and account_equity_usdt * weight < minimum:
            blockers.append(f"target_below_minimum_notional:{symbol}")
        cluster = clusters.get(symbol)
        if weight > 0.0 and cluster:
            cluster_symbols.setdefault(cluster, []).append(symbol)
    for cluster, symbols in cluster_symbols.items():
        if len(symbols) > maximum_positions_per_cluster:
            blockers.append(f"correlation_cluster_position_limit:{cluster}")

    blockers = sorted(set(blockers))
    executable = (
        dict(sorted(proposed.items()))
        if not blockers
        else {symbol: 0.0 for symbol in sorted(proposed)}
    )
    audit_core = {
        "account_equity_usdt": account_equity_usdt,
        "maximum_portfolio_gross": maximum_portfolio_gross,
        "maximum_positions_per_cluster": maximum_positions_per_cluster,
        "allowed_strategy_ids": sorted(allowed),
        "sleeves": sleeve_rows,
        "proposed_target_weights": dict(sorted(proposed.items())),
        "portfolio_target_weights": executable,
        "proposed_gross": gross,
        "blockers": blockers,
        "allocatable": not blockers,
    }
    return audit_core | {"allocation_hash": canonical_hash(audit_core)}


def portfolio_target_from_allocation(
    intents: Sequence[StrategyIntent],
    allocation: Mapping[str, Any],
) -> PortfolioTarget:
    """Bind one deterministic allocator result to its traced strategy decisions."""

    if not intents:
        raise ValueError("portfolio_target_strategy_intents_empty")
    validation_errors: dict[str, tuple[str, ...]] = {}
    for intent in intents:
        errors = intent.validate()
        if errors:
            validation_errors[intent.strategy_id] = errors
    if validation_errors:
        raise ValueError(f"portfolio_target_intent_invalid:{validation_errors}")
    if any(not intent.traced for intent in intents):
        raise ValueError("portfolio_target_requires_traced_intents")
    snapshot_ids = {intent.snapshot_id for intent in intents}
    if len(snapshot_ids) != 1:
        raise ValueError("portfolio_target_mixed_snapshot_ids")
    decision_times = {intent.decision_time for intent in intents}
    if len(decision_times) != 1:
        raise ValueError("portfolio_target_mixed_decision_times")

    sleeve_contributions: dict[str, dict[str, float]] = {}
    for sleeve in allocation.get("sleeves") or ():
        strategy_id = str(sleeve.get("strategy_id") or "")
        if not strategy_id or strategy_id in sleeve_contributions:
            raise ValueError("portfolio_target_sleeve_identity_invalid")
        sleeve_contributions[strategy_id] = {
            str(symbol): float(weight)
            for symbol, weight in (sleeve.get("scaled_target_weights") or {}).items()
        }
    if set(sleeve_contributions) != {intent.strategy_id for intent in intents}:
        raise ValueError("portfolio_target_sleeve_intent_mismatch")

    blockers = tuple(str(value) for value in (allocation.get("blockers") or ()))
    return PortfolioTarget.create(
        snapshot_id=next(iter(snapshot_ids)),
        decision_ids=tuple(intent.decision_id for intent in intents),
        decision_time=next(iter(decision_times)),
        proposed_target_weights=allocation.get("proposed_target_weights") or {},
        target_weights=allocation.get("portfolio_target_weights") or {},
        sleeve_contributions=sleeve_contributions,
        blockers=blockers,
        allocatable=bool(allocation.get("allocatable")),
        allocation_hash=str(allocation.get("allocation_hash") or ""),
    )
