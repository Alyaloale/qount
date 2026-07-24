"""Source-capacity audit for ``stablecoin_liquidity_impulse_v1``.

Assesses whether official stablecoin issuer data (Tether USDT, Circle USDC),
chain-level mint/redeem events and exchange inventory can be reconstructed
point-in-time. The family was selected from the Wave 4 external PIT audit
because chain events are immutable and PIT; exchange inventory is latest-only.

This module produces only a capacity assessment -- no PnL, no direction, no
strategy signal. It reports what official sources exist, whether historical
vintage is reconstructable, and what the PIT revision policy requires.

Key distinction from local negative evidence: aggregate stablecoin supply
growth was already rejected. This family targets marginal funding impulse
(mint/redeem flows + exchange net flow), not total supply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qount.contracts import canonical_hash


STABLECOIN_CAPACITY_VERSION = "stablecoin_source_capacity_v0.1"
STABLECOIN_FAMILY = "stablecoin_liquidity_impulse_v1"


@dataclass(frozen=True)
class StablecoinSource:
    name: str
    issuer: str
    source_type: str  # "attestation" | "chain_event" | "exchange_inventory"
    url: str
    clock: str  # primary clock field
    historical_vintage: str  # "available" | "partial" | "latest_only" | "unknown"
    pit_revisable: bool  # can the source revise past data?
    revision_policy: str
    api_or_scrape: str  # "official_api" | "public_page" | "chain_rpc"
    notes: str = ""


@dataclass(frozen=True)
class StablecoinCapacityProtocol:
    hypothesis_family: str = STABLECOIN_FAMILY
    candidate_id: str = "stablecoin_impulse_source_capacity_v0"
    trial_number_within_family: int = 0
    family_trial_budget: int = 2
    target_stablecoins: tuple[str, ...] = ("USDT", "USDC")
    chains_of_interest: tuple[str, ...] = ("ethereum", "tron", "solana", "bsc")
    output_role: str = "source_capacity_no_direction_no_pnl"
    local_negative_evidence: str = "aggregate_stablecoin_supply_growth_already_rejected"

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "hypothesis_family": self.hypothesis_family,
            "candidate_id": self.candidate_id,
            "trial_number_within_family": self.trial_number_within_family,
            "family_trial_budget": self.family_trial_budget,
            "target_stablecoins": list(self.target_stablecoins),
            "chains_of_interest": list(self.chains_of_interest),
            "output_role": self.output_role,
            "local_negative_evidence": self.local_negative_evidence,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)


STABLECOIN_CAPACITY_PROTOCOL = StablecoinCapacityProtocol()


SOURCES: tuple[StablecoinSource, ...] = (
    StablecoinSource(
        name="tether_usdt_transparency",
        issuer="Tether",
        source_type="attestation",
        url="https://tether.to/en/transparency/",
        clock="published_at",
        historical_vintage="partial",
        pit_revisable=True,
        revision_policy="attestations_are_periodic_snapshots; past attestations may be revised or removed; must archive each snapshot with retrieved_at",
        api_or_scrape="public_page",
        notes="Tether publishes periodic reserve attestations but does not guarantee historical availability; chain events are more reliable",
    ),
    StablecoinSource(
        name="tether_usdt_eth_contract",
        issuer="Tether",
        source_type="chain_event",
        url="ethereum:0xdAC17F958D2ee523a2206206994597C13D831ec7",
        clock="chain_block_timestamp",
        historical_vintage="available",
        pit_revisable=False,
        revision_policy="chain events are immutable; block timestamp is PIT; no revision possible",
        api_or_scrape="chain_rpc",
        notes="USDT contract on Ethereum: mint=transferFrom(treasury), burn=burn(); full history from contract deployment 2017-11",
    ),
    StablecoinSource(
        name="tether_usdt_tron_contract",
        issuer="Tether",
        source_type="chain_event",
        url="tron:TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        clock="chain_block_timestamp",
        historical_vintage="available",
        pit_revisable=False,
        revision_policy="chain events are immutable; block timestamp is PIT",
        api_or_scrape="chain_rpc",
        notes="USDT on Tron is a major supply chain; full history from 2021-04",
    ),
    StablecoinSource(
        name="circle_usdc_attestations",
        issuer="Circle",
        source_type="attestation",
        url="https://www.circle.com/en/transparency",
        clock="published_at",
        historical_vintage="partial",
        pit_revisable=True,
        revision_policy="Circle publishes monthly attestations; past reports may be revised; must archive each with retrieved_at",
        api_or_scrape="public_page",
        notes="Circle attestations are monthly; historical PDFs may be removed from website",
    ),
    StablecoinSource(
        name="circle_usdc_eth_contract",
        issuer="Circle",
        source_type="chain_event",
        url="ethereum:0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        clock="chain_block_timestamp",
        historical_vintage="available",
        pit_revisable=False,
        revision_policy="chain events are immutable; block timestamp is PIT",
        api_or_scrape="chain_rpc",
        notes="USDC contract on Ethereum: mint/burn events are fully reconstructable from chain",
    ),
    StablecoinSource(
        name="exchange_proof_of_reserves",
        issuer="Binance/OKX/Bybit",
        source_type="exchange_inventory",
        url="various exchange PoR pages",
        clock="observed_at",
        historical_vintage="latest_only",
        pit_revisable=True,
        revision_policy="exchange PoR is a current snapshot; no historical revision chain; cannot reconstruct past inventory",
        api_or_scrape="public_page",
        notes="Exchange stablecoin inventory is latest-only; requires append-only collection from now",
    ),
)


def build_stablecoin_source_capacity_report(observed_at: str) -> dict[str, Any]:
    protocol = STABLECOIN_CAPACITY_PROTOCOL
    source_assessments = []
    chain_pit_count = 0
    attestation_count = 0
    exchange_inventory_count = 0
    reconstructable_count = 0

    for src in SOURCES:
        is_chain = src.source_type == "chain_event"
        is_attestation = src.source_type == "attestation"
        is_exchange = src.source_type == "exchange_inventory"
        reconstructable = src.historical_vintage == "available"

        if is_chain:
            chain_pit_count += 1
        if is_attestation:
            attestation_count += 1
        if is_exchange:
            exchange_inventory_count += 1
        if reconstructable:
            reconstructable_count += 1

        source_assessments.append({
            "name": src.name,
            "issuer": src.issuer,
            "source_type": src.source_type,
            "url": src.url,
            "clock": src.clock,
            "historical_vintage": src.historical_vintage,
            "pit_revisable": src.pit_revisable,
            "revision_policy": src.revision_policy,
            "api_or_scrape": src.api_or_scrape,
            "historical_vintage_reconstructable": reconstructable,
            "notes": src.notes,
        })

    kill_tests = {
        "no_chain_pit_sources": chain_pit_count == 0,
        "all_sources_latest_only": reconstructable_count == 0,
        "equivalent_to_aggregate_supply": False,
        "exchange_inventory_not_pit": exchange_inventory_count > 0 and all(
            s["historical_vintage"] == "latest_only"
            for s in source_assessments
            if s["source_type"] == "exchange_inventory"
        ),
    }
    blocked = kill_tests["no_chain_pit_sources"] or kill_tests["all_sources_latest_only"]

    return {
        "schema_version": STABLECOIN_CAPACITY_VERSION,
        "artifact_type": "stablecoin_source_capacity",
        "observed_at": observed_at,
        "contract_hash": protocol.contract_hash,
        "meta": {
            "research_only": True,
            "output_role": protocol.output_role,
            "direction_produced": False,
            "pnl_evaluated": False,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "orders_authorized": False,
        },
        "target_stablecoins": list(protocol.target_stablecoins),
        "chains_of_interest": list(protocol.chains_of_interest),
        "local_negative_evidence": protocol.local_negative_evidence,
        "source_count": len(SOURCES),
        "chain_pit_sources": chain_pit_count,
        "attestation_sources": attestation_count,
        "exchange_inventory_sources": exchange_inventory_count,
        "reconstructable_sources": reconstructable_count,
        "sources": source_assessments,
        "kill_tests": kill_tests,
        "verdict": "block_capacity" if blocked else "pass_to_g0",
        "remaining_blockers": (
            [
                "no_chain_pit_sources_available",
                "requires_forward_collection_for_exchange_inventory",
            ]
            if blocked
            else [
                "exchange_inventory_is_latest_only_requires_append_only_collection",
                "attestations_must_be_archived_with_retrieved_at",
                "must_distinguish_marginal_flow_from_aggregate_supply",
            ]
        ),
        "hard_constraints": [
            "aggregate_stablecoin_supply_is_local_negative_evidence_not_repackaged",
            "exchange_inventory_cannot_backfill_historical_visibility",
            "attestation_vintage_must_track_revision_not_latest_only",
            "chain_events_are_pit_immutable_but_must_bind_to_decision_clock",
        ],
    }
