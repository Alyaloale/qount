"""Pure validation for the legacy MiniTrend dry-dispatch artifact."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from qount.contracts import PortfolioTarget
from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts import trace_id


LEGACY_PLAN_HASH_FIELDS = (
    "contract_hash",
    "readiness_hash",
    "source_hashes",
    "standard_authority",
    "standard_execution",
    "snapshot_hash",
    "decision",
    "capital_usdt",
    "desired_weights",
    "execution_reference_prices",
    "market_orders",
    "stop_cancels",
    "stop_orders",
    "risk_flags",
    "source_freshness",
    "halt_after_dispatch",
    "halt_reason",
    "expected_positions_base",
    "reconciliation_tolerance_base",
)


@dataclass(frozen=True)
class LegacyDispatchVerification:
    legacy_plan_hash: str
    batch_id: str
    decision_id: str
    errors: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return not self.errors


def legacy_dispatch_plan_hash(plan: Mapping[str, Any]) -> str:
    """Recompute the exact hash core used by the current dispatcher."""

    return canonical_hash({field: plan.get(field) for field in LEGACY_PLAN_HASH_FIELDS})


def _normalized_weights(value: object) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return {str(symbol): float(weight) for symbol, weight in value.items()}
    except (TypeError, ValueError):
        return None


def verify_legacy_dry_dispatch_plan(
    plan: Mapping[str, Any],
    target: PortfolioTarget,
) -> LegacyDispatchVerification:
    """Bind a dry legacy artifact to one immutable portfolio target."""

    errors: list[str] = []
    recomputed_hash = legacy_dispatch_plan_hash(plan)
    if str(plan.get("plan_hash") or "") != recomputed_hash:
        errors.append("legacy_plan_hash_invalid")
    if (plan.get("meta") or {}).get("mode") != "dry":
        errors.append("legacy_plan_not_dry")

    target_errors = target.validate()
    errors.extend(f"portfolio_target_invalid:{error}" for error in target_errors)

    decision = plan.get("decision")
    if not isinstance(decision, Mapping):
        decision = {}
        errors.append("legacy_decision_missing")
    decision_id = str(decision.get("decision_id") or "")
    if not is_sha256(decision_id):
        errors.append("legacy_decision_id_invalid")
    elif decision_id not in target.decision_ids:
        errors.append("legacy_decision_portfolio_target_mismatch")

    decision_time = str(decision.get("decision_available_after") or "")
    if decision_time and decision_time != target.decision_time:
        errors.append("legacy_decision_time_portfolio_target_mismatch")

    legacy_weights = _normalized_weights(decision.get("desired_weights"))
    target_weights = _normalized_weights(target.target_weights)
    if legacy_weights is None:
        errors.append("legacy_decision_weights_invalid")
    elif target_weights is None or legacy_weights != target_weights:
        errors.append("legacy_decision_weights_portfolio_target_mismatch")

    batch_id = trace_id(
        "legacy_dispatch_batch",
        {
            "legacy_plan_hash": recomputed_hash,
            "portfolio_target_id": target.portfolio_target_id,
        },
    )
    return LegacyDispatchVerification(
        legacy_plan_hash=recomputed_hash,
        batch_id=batch_id,
        decision_id=decision_id,
        errors=tuple(dict.fromkeys(errors)),
    )
