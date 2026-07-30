"""Standard registry adapter for the frozen L1-S2 personal-carrier research sleeve."""

from __future__ import annotations

from typing import Any, Mapping

from qount.governance.registry import StrategyRegistration
from qount.l1_personal_carrier_recertification import L1_PERSONAL_CARRIER_STRATEGY_ID
from qount.l1_personal_carrier_recertification import assert_personal_carrier_source_parity
from qount.l1_personal_carrier_recertification import personal_carrier_strategy_version
from qount.l1_personal_carrier_recertification import validate_personal_carrier_preregistration


def personal_carrier_strategy_registration(
    *,
    preregistration: Mapping[str, Any],
    code_hash: str,
    config_hash: str,
    registered_at: str,
) -> StrategyRegistration:
    """Register the L1 sleeve as a standard research-only strategy.

    Promotion evidence, owner authorization, paper, and live permission are
    deliberately absent.  The full-loss stress bound preserves the evaluator's
    fail-closed position until a carrier-specific risk model is independently
    certified.
    """

    validate_personal_carrier_preregistration(preregistration)
    assert_personal_carrier_source_parity(preregistration)
    return StrategyRegistration.create(
        strategy_id=L1_PERSONAL_CARRIER_STRATEGY_ID,
        strategy_version=personal_carrier_strategy_version(preregistration),
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
