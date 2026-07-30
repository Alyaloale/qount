"""Standard registry adapter for the result-independent L1 passive sleeve."""

from __future__ import annotations

from typing import Any, Mapping

from qount.governance.registry import StrategyRegistration
from qount.research.sleeves.l1_passive_allocation import L1_PASSIVE_ALLOCATION_STRATEGY_ID
from qount.research.sleeves.l1_passive_allocation import L1_PASSIVE_ALLOCATION_STRATEGY_VERSION
from qount.research.sleeves.l1_passive_allocation import validate_l1_passive_allocation_preregistration


def passive_allocation_strategy_registration(
    *,
    preregistration: Mapping[str, Any],
    code_hash: str,
    config_hash: str,
    registered_at: str,
) -> StrategyRegistration:
    """Register the passive policy as research-only; it cannot create intents or orders."""

    validate_l1_passive_allocation_preregistration(preregistration)
    return StrategyRegistration.create(
        strategy_id=L1_PASSIVE_ALLOCATION_STRATEGY_ID,
        strategy_version=L1_PASSIVE_ALLOCATION_STRATEGY_VERSION,
        strategy_kind="continuous",
        promotion_status="research",
        strategy_contract_hash=str(preregistration["contract_hash"]),
        code_hash=code_hash,
        config_hash=config_hash,
        promotion_artifact_hash=None,
        owner_authorization_hash=None,
        maximum_stress_loss_fraction=1.0,
        maximum_gross=1.0,
        registered_at=registered_at,
    )
