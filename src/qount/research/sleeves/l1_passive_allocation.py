"""Result-independent preregistration for the L1 passive Sleeve 1 allocation."""

from __future__ import annotations

from typing import Any, Mapping

from qount.contracts import canonical_hash
from qount.models import utc_now


L1_PASSIVE_ALLOCATION_PREREGISTRATION_VERSION = "l1_passive_allocation_preregistration_v0.1"
L1_PASSIVE_ALLOCATION_STRATEGY_ID = "l1_passive_sixty_forty"
L1_PASSIVE_ALLOCATION_STRATEGY_VERSION = "0.1.0"
_REFERENCE_PREREGISTRATION_CONTRACT_HASH = (
    "05d46a2378d2adec4a96d9e8961a909941c45021f3a84f6de77bb54cae643a38"
)


def passive_allocation_contract() -> dict[str, Any]:
    """Return the exact, non-tactical passive policy that is being registered."""

    return {
        "strategy_identity": {
            "strategy_id": L1_PASSIVE_ALLOCATION_STRATEGY_ID,
            "strategy_version": L1_PASSIVE_ALLOCATION_STRATEGY_VERSION,
            "sleeve": "sleeve_1_core_passive",
            "style": "long_only_strategic_allocation",
        },
        "selection_provenance": {
            "selection_method": "owner_directed_separate_passive_allocation",
            "pre_result_reference": {
                "artifact_type": "l1_personal_carrier_recertification_preregistration",
                "contract_hash": _REFERENCE_PREREGISTRATION_CONTRACT_HASH,
                "role": "pre_result_sixty_forty_benchmark_only",
            },
            "forbidden_selection_inputs": [
                "terminal_trend_evaluation_metrics",
                "post_registration_historical_performance",
                "parameter_or_asset_search",
            ],
        },
        "strategic_allocation": {
            "assets": [
                {
                    "ticker": "SPY",
                    "asset_class": "US_large_cap_equity_ETF",
                    "target_weight": 0.60,
                },
                {
                    "ticker": "TLT",
                    "asset_class": "US_long_duration_treasury_ETF",
                    "target_weight": 0.40,
                },
            ],
            "target_weight_total": 1.0,
            "long_only": True,
            "leverage_allowed": False,
            "shorting_allowed": False,
            "asset_substitution_allowed": False,
            "corporate_action_rule": (
                "apply issuer-provided split or distribution mechanics; a delisting, merger, "
                "or permanently untradeable asset requires a successor preregistration"
            ),
        },
        "cash_rule": {
            "currency": "USD",
            "strategic_target_weight": 0.0,
            "cash_instrument": "uninvested_USD_cash_only",
            "yield_assumption": "none",
            "permitted_residual_cash": "rounding_fees_and_unsettled_distributions_only",
            "dividend_coupon_and_external_cash_flow_treatment": (
                "hold as USD cash until the next scheduled rebalance"
            ),
            "scheduled_deployment": (
                "at the next eligible rebalance, include available USD cash in total portfolio "
                "value and restore the fixed SPY/TLT target weights"
            ),
            "intra_period_cash_deployment_allowed": False,
            "signal_dependent_cash_allocation_allowed": False,
            "external_cash_flows_excluded_from_strategy_return": True,
        },
        "rebalance_calendar": {
            "calendar": "NYSE_regular_US_equity_sessions",
            "frequency": "annual",
            "anchor": "first_eligible_full_NYSE_regular_session_on_or_after_January_1",
            "decision_data": "official_regular_session_close_after_anchor_completion",
            "target_effective": "next_eligible_regular_session_after_decision",
            "early_close_holiday_or_unscheduled_closure": (
                "skip_the_ineligible_session_and_use_the_next_eligible_full_NYSE_regular_session"
            ),
            "intra_year_drift_band_rebalance_allowed": False,
            "missed_rebalance_rule": "defer_to_next_eligible_full_NYSE_regular_session_without_target_change",
        },
        "operating_boundaries": {
            "tax_and_account_wrapper": "not_modeled; no tax-location or tax-loss-harvesting rule",
            "fx_treatment": "USD_base_currency_only",
            "historical_evaluation": "not_authorized_by_this_allocation_preregistration",
            "strategy_intent_authorized": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "scheduler_or_cron_allowed": False,
            "changes_require": "new_separate_preregistration_and_owner_authorization",
        },
    }


def build_l1_passive_allocation_preregistration() -> dict[str, Any]:
    """Build the sealed research-only passive-allocation contract."""

    contract = passive_allocation_contract()
    return {
        "schema_version": L1_PASSIVE_ALLOCATION_PREREGISTRATION_VERSION,
        "artifact_type": "l1_passive_allocation_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "strategy_intent_authorized": False,
            "orders_authorized": False,
            "paper_or_live_allowed": False,
            "scheduler_or_cron_allowed": False,
        },
        "contract": contract,
        "contract_hash": canonical_hash(contract),
    }


def validate_l1_passive_allocation_preregistration(payload: Mapping[str, Any]) -> None:
    """Fail closed unless the policy and authority boundaries are exact."""

    if payload.get("schema_version") != L1_PASSIVE_ALLOCATION_PREREGISTRATION_VERSION:
        raise ValueError("l1_passive_allocation_preregistration_version_invalid")
    if payload.get("artifact_type") != "l1_passive_allocation_preregistration":
        raise ValueError("l1_passive_allocation_preregistration_type_invalid")
    meta = payload.get("meta")
    expected_meta = {
        "research_only": True,
        "strategy_results_evaluated": False,
        "strategy_intent_authorized": False,
        "orders_authorized": False,
        "paper_or_live_allowed": False,
        "scheduler_or_cron_allowed": False,
    }
    if meta != expected_meta:
        raise ValueError("l1_passive_allocation_preregistration_authority_invalid")
    contract = payload.get("contract")
    if contract != passive_allocation_contract():
        raise ValueError("l1_passive_allocation_preregistration_contract_invalid")
    if payload.get("contract_hash") != canonical_hash(contract):
        raise ValueError("l1_passive_allocation_preregistration_hash_invalid")
