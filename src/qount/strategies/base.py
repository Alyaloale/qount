"""Base strategy adapters for the shared portfolio contract."""

from __future__ import annotations

import re
from typing import Any, Mapping

from qount.contracts import MarketSnapshot
from qount.contracts import StrategyIntent
from qount.governance.registry import StrategyRegistration
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.pilot_projection import PILOT_PROJECTION_VERSION


BASE_STRATEGY_VERSION = "0.2.0"


def base_strategy_registration(
    *,
    promotion_status: str,
    code_hash: str,
    config_hash: str,
    promotion_artifact_hash: str | None,
    owner_authorization_hash: str | None,
    maximum_stress_loss_fraction: float,
    maximum_gross: float,
    registered_at: str,
    supersedes_entry_id: str | None = None,
    halted_from_status: str | None = None,
    recovery_evidence_hash: str | None = None,
) -> StrategyRegistration:
    """Bind Base identity and its frozen live contract into the registry."""

    return StrategyRegistration.create(
        strategy_id=LIVE_PILOT_CONTRACT.strategy,
        strategy_version=BASE_STRATEGY_VERSION,
        strategy_kind="continuous",
        promotion_status=promotion_status,
        strategy_contract_hash=LIVE_PILOT_CONTRACT.contract_hash,
        code_hash=code_hash,
        config_hash=config_hash,
        promotion_artifact_hash=promotion_artifact_hash,
        owner_authorization_hash=owner_authorization_hash,
        maximum_stress_loss_fraction=maximum_stress_loss_fraction,
        maximum_gross=maximum_gross,
        registered_at=registered_at,
        supersedes_entry_id=supersedes_entry_id,
        halted_from_status=halted_from_status,
        recovery_evidence_hash=recovery_evidence_hash,
    )


def _validated_projection_decision(
    projection: Mapping[str, Any],
) -> Mapping[str, Any]:
    if projection.get("schema_version") != PILOT_PROJECTION_VERSION:
        raise ValueError("portfolio intent projection schema mismatch")
    if projection.get("artifact_type") != "mini_trend_um_pilot_latest_projection":
        raise ValueError("portfolio intent projection artifact mismatch")
    if projection.get("contract", {}).get("strategy") != LIVE_PILOT_CONTRACT.strategy:
        raise ValueError("portfolio intent projection strategy mismatch")
    if projection.get("contract", {}).get("live_pilot_contract_hash") != (
        LIVE_PILOT_CONTRACT.contract_hash
    ):
        raise ValueError("portfolio intent live contract hash mismatch")
    diagnostics = projection.get("diagnostics", {})
    if diagnostics.get("projection_ready") is not True:
        raise ValueError("portfolio intent projection is not ready")
    decision = projection.get("decision")
    if not isinstance(decision, Mapping):
        raise ValueError("portfolio intent decision missing")
    if decision.get("strategy") != LIVE_PILOT_CONTRACT.strategy:
        raise ValueError("portfolio intent decision strategy mismatch")
    return decision


def base_snapshot_from_projection(
    projection: Mapping[str, Any],
    *,
    projection_evidence_hash: str,
) -> MarketSnapshot:
    """Create the immutable standard snapshot reference used by Base."""

    decision = _validated_projection_decision(projection)
    available_after = str(decision.get("decision_available_after") or "")
    return MarketSnapshot.create(
        decision_time=available_after,
        data_cutoff=available_after,
        prices={
            str(symbol): float(price)
            for symbol, price in (decision.get("prices") or {}).items()
        },
        funding={},
        features={},
        exchange_rules_hash=str(decision.get("exchange_rules_hash") or ""),
        account_snapshot_hash=None,
        data_quality={
            "complete": True,
            "blockers": (),
            "account_snapshot_linked": False,
            "funding_values_embedded": False,
            "funding_lineage_bound_by_data_hash": True,
        },
        source_hashes={
            "projection_evidence": projection_evidence_hash,
            "market_data": str(decision.get("data_hash") or ""),
            "exchange_rules": str(decision.get("exchange_rules_hash") or ""),
            "strategy_contract": LIVE_PILOT_CONTRACT.contract_hash,
        },
    )


def _base_reason_codes(decision: Mapping[str, Any]) -> tuple[str, ...]:
    weights = {
        str(symbol): float(weight)
        for symbol, weight in (decision.get("desired_weights") or {}).items()
    }
    risk_stage = re.sub(
        r"[^A-Z0-9]+",
        "_",
        str(decision.get("risk_stage") or "UNKNOWN").upper(),
    ).strip("_")
    codes = [
        "BASE_MASTER_GATE_ACTIVE"
        if any(weight > 0.0 for weight in weights.values())
        else "BASE_MASTER_GATE_CASH",
        f"RISK_STAGE_{risk_stage or 'UNKNOWN'}",
    ]
    codes.extend(
        f"{symbol}_{'TARGET_LONG' if weight > 0.0 else 'TARGET_CASH'}"
        for symbol, weight in sorted(weights.items())
    )
    return tuple(codes)


def base_intent_from_projection(
    projection: Mapping[str, Any],
    *,
    projection_evidence_hash: str,
    target_stress_loss_fraction: float,
) -> StrategyIntent:
    """Convert one verified causal Base projection into an order-free intent."""

    decision = _validated_projection_decision(projection)
    snapshot = base_snapshot_from_projection(
        projection,
        projection_evidence_hash=projection_evidence_hash,
    )
    available_after = str(decision.get("decision_available_after") or "")
    intent = StrategyIntent.create(
        strategy_id=LIVE_PILOT_CONTRACT.strategy,
        strategy_version=BASE_STRATEGY_VERSION,
        snapshot_id=snapshot.snapshot_id,
        decision_id=str(decision.get("decision_id") or ""),
        decision_time=available_after,
        data_cutoff=available_after,
        target_weights={
            str(symbol): float(weight)
            for symbol, weight in decision.get("desired_weights", {}).items()
        },
        expected_holding_bars=1,
        target_stress_loss_fraction=target_stress_loss_fraction,
        reason_codes=_base_reason_codes(decision),
        evidence_hash=projection_evidence_hash,
        state_hash=str(decision.get("execution_state_hash") or ""),
    )
    return intent
