"""Adapt a verified legacy dry-dispatch artifact to a standard risk decision."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from qount.contracts import PortfolioTarget
from qount.contracts import RiskDecision
from qount.contracts import canonical_hash
from qount.risk.validation import verify_legacy_dry_dispatch_plan


def _unique_strings(values: Sequence[object]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _weights(value: object) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return {str(symbol): float(weight) for symbol, weight in value.items()}
    except (TypeError, ValueError):
        return None


def _approved_target_errors(weights: Mapping[str, float]) -> tuple[str, ...]:
    errors: list[str] = []
    gross = 0.0
    for symbol, weight in weights.items():
        if not symbol or not math.isfinite(weight) or weight < 0.0:
            errors.append(f"legacy_approved_target_weight_invalid:{symbol}")
        else:
            gross += weight
    if gross > 1.0 + 1e-12:
        errors.append("legacy_approved_target_gross_exceeds_limit")
    return tuple(errors)


def risk_decision_from_legacy_dry_plan(
    plan: Mapping[str, Any],
    target: PortfolioTarget,
) -> RiskDecision:
    """Translate legacy risk output without granting it execution authority."""

    verification = verify_legacy_dry_dispatch_plan(plan, target)
    diagnostics = plan.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        diagnostics = {}

    raw_blockers = diagnostics.get("blockers")
    if not isinstance(raw_blockers, (list, tuple)):
        raw_blockers = ("legacy_diagnostics_blockers_invalid",)
    diagnostic_violations = tuple(
        f"legacy_dispatch_blocker:{value}" for value in raw_blockers if str(value)
    )
    readiness_violations: list[str] = []
    if diagnostics.get("verdict") != "dry_dispatch_ready":
        readiness_violations.append("legacy_dispatch_not_ready")
    if diagnostics.get("dry_evidence_valid") is not True:
        readiness_violations.append("legacy_dry_evidence_invalid")

    violations = _unique_strings(
        (*verification.errors, *diagnostic_violations, *readiness_violations)
    )
    approved_target = _weights(plan.get("desired_weights"))
    if approved_target is None:
        violations = _unique_strings((*violations, "legacy_approved_target_invalid"))
        approved_target = {}
    else:
        violations = _unique_strings(
            (*violations, *_approved_target_errors(approved_target))
        )

    symbols = set(target.target_weights) | set(approved_target)
    if violations:
        approved_target = {symbol: 0.0 for symbol in sorted(symbols)}

    risk_flags = plan.get("risk_flags")
    if not isinstance(risk_flags, (list, tuple)):
        risk_flags = ("legacy_risk_flags_invalid",)
        violations = _unique_strings((*violations, "legacy_risk_flags_invalid"))
    halt_after_dispatch = bool(plan.get("halt_after_dispatch"))
    adjustments = _unique_strings(risk_flags)
    if halt_after_dispatch and "pilot_drawdown_flatten_then_halt" not in adjustments:
        adjustments = (*adjustments, "halt_after_dispatch")

    risk_state_hash = canonical_hash(
        {
            "legacy_plan_hash": verification.legacy_plan_hash,
            "account_equity": plan.get("account_equity"),
            "actual_weights": plan.get("actual_weights"),
            "risk_flags": tuple(risk_flags),
            "halt_after_dispatch": halt_after_dispatch,
            "approved_target": approved_target,
        }
    )
    approved = not violations
    return RiskDecision.create(
        batch_id=verification.batch_id,
        portfolio_target_id=target.portfolio_target_id,
        decision_time=target.decision_time,
        approved=approved,
        input_target=target.target_weights,
        approved_target=approved_target,
        adjustments=adjustments,
        violations=violations,
        risk_state_hash=risk_state_hash,
        increase_risk_allowed=approved and not halt_after_dispatch,
        reduce_risk_allowed=True,
    )
