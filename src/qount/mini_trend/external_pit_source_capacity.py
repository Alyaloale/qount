"""Source-capacity audit for Wave 4 external PIT families.

Assesses PIT vintage availability for stablecoin, token supply, network
adoption and venue-rule families. Selection priority (frozen): PIT vintage
availability > event density > novelty versus local negative evidence. Only one
family that passes source-capacity may enter the first formal external trial.

This module produces only a capacity assessment -- no PnL, no direction, no
strategy signal. It reports what official sources exist, whether historical
vintage is reconstructable, and what the PIT revision policy would require.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from qount.contracts import canonical_hash


EXTERNAL_PIT_VERSION = "external_pit_source_capacity_v0.1"


@dataclass(frozen=True)
class ExternalPitFamilyContract:
    family: str
    candidate_id: str
    trial_number_within_family: int
    family_trial_budget: int
    economic_mechanism: str
    official_sources: tuple[str, ...]
    required_clocks: tuple[str, ...]
    vintage_assessment: str
    pit_revision_policy: str
    local_negative_evidence: str
    selection_priority: str

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "candidate_id": self.candidate_id,
            "trial_number_within_family": self.trial_number_within_family,
            "family_trial_budget": self.family_trial_budget,
            "economic_mechanism": self.economic_mechanism,
            "official_sources": list(self.official_sources),
            "required_clocks": list(self.required_clocks),
            "vintage_assessment": self.vintage_assessment,
            "pit_revision_policy": self.pit_revision_policy,
            "local_negative_evidence": self.local_negative_evidence,
            "selection_priority": self.selection_priority,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)


STABLECOIN_FAMILY = ExternalPitFamilyContract(
    family="stablecoin_liquidity_impulse_v1",
    candidate_id="stablecoin_impulse_capacity_v0",
    trial_number_within_family=0,
    family_trial_budget=2,
    economic_mechanism="mint/redeem and exchange net flow as marginal crypto funding supply",
    official_sources=(
        "tether_usdt_transparency_page",
        "circle_usdc_attestations",
        "chain_supply_contract_events",
        "exchange_proof_of_reserves",
    ),
    required_clocks=("published_at", "chain_block_timestamp", "observed_at"),
    vintage_assessment="issuer_attestations_are_periodic_not_continuous; chain_events_are_pit_but_exchange_inventory_is_not",
    pit_revision_policy="chain_events_immutable; attestation_vintage_must_track_revision; exchange_inventory_is_latest_only",
    local_negative_evidence="aggregate_stablecoin_supply_growth_already_rejected",
    selection_priority="pit_vintage_availability_first",
)

TOKEN_SUPPLY_FAMILY = ExternalPitFamilyContract(
    family="token_supply_event_v1",
    candidate_id="token_supply_capacity_v0",
    trial_number_within_family=0,
    family_trial_budget=2,
    economic_mechanism="unlock/vesting/emission/burn changes tradeable supply and sell pressure",
    official_sources=(
        "project_official_schedule_or_transparency_page",
        "chain_vesting_and_token_contract_events",
        "exchange_listing_and_withdrawal_status",
    ),
    required_clocks=("announced_at", "chain_execution_timestamp", "available_at", "observed_at"),
    vintage_assessment="project_schedules_are_revisable; chain_execution_is_pit; exchange_availability_is_runtime_only",
    pit_revision_policy="schedule_revisions_must_be_tracked; chain_execution_is_immutable; exchange_status_needs_snapshot_revision",
    local_negative_evidence="none_direct; but_supply_growth_as_direction_already_weak",
    selection_priority="pit_vintage_availability_first",
)

NETWORK_FAMILY = ExternalPitFamilyContract(
    family="network_adoption_quality_v1",
    candidate_id="network_adoption_capacity_v0",
    trial_number_within_family=0,
    family_trial_budget=2,
    economic_mechanism="active entities, fees and settlement value reflect network demand",
    official_sources=(
        "chain_analytics_active_entities",
        "chain_analytics_fees_and_transfer_value",
        "realized_cap_and_settlement_data",
    ),
    required_clocks=("chain_block_timestamp", "data_provider_published_at", "observed_at"),
    vintage_assessment="on_chain_data_is_pit_but_provider_revisions_and_entity_definitions_change",
    pit_revision_policy="block_data_immutable; entity_count_and_realized_cap_revisions_must_be_tracked_per_provider_vintage",
    local_negative_evidence="hashrate_factor_already_rejected; production_cost_does_not_predict_returns",
    selection_priority="pit_vintage_availability_first",
)

VENUE_RULE_FAMILY = ExternalPitFamilyContract(
    family="venue_rule_event_v1",
    candidate_id="venue_rule_capacity_v0",
    trial_number_within_family=0,
    family_trial_budget=2,
    economic_mechanism="listing/delisting/filter/funding interval changes alter liquidity and capacity",
    official_sources=(
        "binance_announcements_published_time",
        "binance_exchangeInfo_snapshot_revision",
        "binance_funding_interval_history",
    ),
    required_clocks=("published_at", "available_at", "snapshot_timestamp", "observed_at"),
    vintage_assessment="exchangeInfo_is_current_only; announcements_have_published_time; snapshot_revision_chain_must_be_built_from_now",
    pit_revision_policy="current_snapshot_cannot_reconstruct_past; announcements_are_pit; revision_chain_append_only_from_collection_start",
    local_negative_evidence="none_direct; but_runtime_rules_coverage_already_0_of_10",
    selection_priority="pit_vintage_availability_first",
)

ALL_EXTERNAL_PIT_FAMILIES = (
    STABLECOIN_FAMILY,
    TOKEN_SUPPLY_FAMILY,
    NETWORK_FAMILY,
    VENUE_RULE_FAMILY,
)


def _assess_vintage_availability(contract: ExternalPitFamilyContract) -> dict[str, Any]:
    """Assess whether PIT vintage is reconstructable for this family.

    Chain-level events (mint/redeem/unlock/burn) are immutable and PIT. Provider
    metrics (entity counts, realized cap) suffer from definition revisions and
    latest-vintage backfill. Runtime snapshots (exchangeInfo, exchange inventory)
    are current-only and cannot reconstruct historical rules.
    """

    chain_pit = any("chain" in clock or "block" in clock for clock in contract.required_clocks)
    announcement_pit = any("published" in clock or "announced" in clock for clock in contract.required_clocks)
    has_provider_vintage_issue = "provider" in contract.vintage_assessment or "revisions" in contract.vintage_assessment
    has_runtime_only_core = "current_only" in contract.vintage_assessment or "latest_only" in contract.vintage_assessment

    if has_runtime_only_core:
        reconstructable = False
    elif has_provider_vintage_issue:
        reconstructable = False
    else:
        reconstructable = chain_pit or announcement_pit

    return {
        "chain_pit_available": chain_pit,
        "announcement_pit_available": announcement_pit,
        "provider_vintage_issue": has_provider_vintage_issue,
        "runtime_only_core_data": has_runtime_only_core,
        "historical_vintage_reconstructable": reconstructable,
        "requires_forward_collection": has_runtime_only_core or has_provider_vintage_issue,
        "vintage_assessment": contract.vintage_assessment,
    }


def build_external_pit_source_capacity_report(observed_at: str) -> dict[str, Any]:
    families = []
    for contract in ALL_EXTERNAL_PIT_FAMILIES:
        vintage = _assess_vintage_availability(contract)
        entry = {**contract.contract_basis, "contract_hash": contract.contract_hash}
        entry["vintage_assessment_detail"] = vintage
        entry["kill_tests"] = {
            "vintage_not_available": not vintage["historical_vintage_reconstructable"],
            "equivalent_to_local_negative_evidence": False,
            "pit_revision_not_trackable": "must_be_tracked" in contract.pit_revision_policy and "immutable" not in contract.pit_revision_policy,
        }
        blocked = any(entry["kill_tests"].values())
        entry["verdict"] = "block_capacity" if blocked else "pass_to_g0"
        entry["remaining_blockers"] = (
            [
                "historical_vintage_not_reconstructable",
                "requires_forward_collection_from_now",
            ]
            if blocked
            else []
        )
        families.append(entry)

    families_with_pass = [f for f in families if f["verdict"] == "pass_to_g0"]
    selected = families_with_pass[0]["family"] if families_with_pass else None
    for family in families:
        if family["verdict"] == "pass_to_g0" and family["family"] != selected:
            family["verdict"] = "block_capacity"
            family["remaining_blockers"] = ["only_one_family_selected_for_formal_trial"]

    return {
        "schema_version": EXTERNAL_PIT_VERSION,
        "artifact_type": "external_pit_source_capacity",
        "observed_at": observed_at,
        "meta": {
            "research_only": True,
            "direction_produced": False,
            "pnl_evaluated": False,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        },
        "selection_priority": "pit_vintage_availability_first",
        "selection_rule": "only_one_family_passing_source_capacity_enters_formal_trial",
        "families": families,
        "selected_for_g0": selected,
        "hard_constraints": [
            "latest_web_page_or_http_receipt_time_cannot_backfill_historical_visibility",
            "project_latest_schedule_or_aggregator_current_view_is_not_pit",
            "only_one_family_enters_formal_trial_others_block_capacity",
            "local_negative_evidence_aggregate_supply_and_hashrate_must_not_be_repackaged",
        ],
    }
