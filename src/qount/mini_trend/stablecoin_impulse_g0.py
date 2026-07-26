"""No-PnL G0 audit for ``stablecoin_liquidity_impulse_v1``.

The audit answers a deliberately narrow question: can three frozen chain-event
sources be reconstructed, classified and aggregated at weekly UTC decision
cutoffs without transaction or cross-chain double counting, and do those
event-level states contain information that is not merely the old aggregate
stablecoin-supply series under another name?

This module never reads market prices, returns, positions or orders.  Its
statistical unit is a weekly decision anchor, never an event count.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.l3_information_edge import (
    DEFAULT_STABLECOIN_SUPPLY_FIELD,
    asof_supply_at,
    normalize_stablecoin_supply_series,
)


STABLECOIN_IMPULSE_G0_VERSION = "stablecoin_liquidity_impulse_g0_v0.2"
STABLECOIN_IMPULSE_PREREG_VERSION = (
    "stablecoin_liquidity_impulse_g0_preregistration_v0.2"
)
STABLECOIN_CHAIN_SOURCE_VERSION = "stablecoin_chain_event_source_v0.3"
STABLECOIN_FAMILY = "stablecoin_liquidity_impulse_v1"

SOURCE_CAPACITY_CONTRACT_HASH = (
    "0d545b77a27e3758897b4f4a6f5866c51651b3dff70f9e9d289dbe09b48d12c9"
)
SOURCE_CAPACITY_ARTIFACT_SHA256 = (
    "69463c848bc14832313efcc319d3cc49ffa83d02ff1db493512025754f53dbea"
)

_WEEK = timedelta(days=7)
_ZERO_EVM = "0x0000000000000000000000000000000000000000"
_ZERO_TRON = "t9yd14nj9j7xab4dbgeix9h8unkkhxuwwb"
_HEX = frozenset("0123456789abcdef")
_ETHEREUM_CONFIRMATION_POLICY = "ethereum_event_block_plus_64"
_TRON_CONFIRMATION_POLICY = "tron_event_producer_plus_18_distinct_srs"


@dataclass(frozen=True)
class StablecoinChainSourceSpec:
    source_id: str
    chain: str
    asset: str
    contract: str
    decimals: int
    native_mint_events: tuple[str, ...]
    native_burn_events: tuple[str, ...]
    required_event_families: tuple[str, ...]


SOURCE_SPECS: tuple[StablecoinChainSourceSpec, ...] = (
    StablecoinChainSourceSpec(
        source_id="usdt_ethereum",
        chain="ethereum",
        asset="USDT",
        contract="0xdac17f958d2ee523a2206206994597c13d831ec7",
        decimals=6,
        native_mint_events=("issue",),
        native_burn_events=("redeem",),
        required_event_families=(
            "native_supply",
            "zero_transfer",
            "treasury_transfer",
        ),
    ),
    StablecoinChainSourceSpec(
        source_id="usdt_tron",
        chain="tron",
        asset="USDT",
        contract="tr7nhqjekqxgtci8q8zy4pl8otszgjlj6t",
        decimals=6,
        native_mint_events=("issue",),
        native_burn_events=("redeem",),
        required_event_families=(
            "native_supply",
            "zero_transfer",
            "treasury_transfer",
        ),
    ),
    StablecoinChainSourceSpec(
        source_id="usdc_ethereum",
        chain="ethereum",
        asset="USDC",
        contract="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        decimals=6,
        native_mint_events=("mint",),
        native_burn_events=("burn",),
        required_event_families=("native_supply", "zero_transfer"),
    ),
)
_SOURCE_BY_ID = {source.source_id: source for source in SOURCE_SPECS}


@dataclass(slots=True)
class _NormalizedEvent:
    source_id: str
    chain: str
    asset: str
    contract: str
    transaction_hash: str
    block_number: int
    block_hash: str
    event_index: int
    event_name: str
    event_at: datetime
    available_at: datetime
    amount: Decimal
    from_address: str | None
    to_address: str | None
    supply_classification: str
    classification: str
    event_family: str
    economic_cluster_id: str | None = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


@dataclass(frozen=True)
class StablecoinImpulseG0Protocol:
    hypothesis_family: str = STABLECOIN_FAMILY
    candidate_id: str = "stablecoin_marginal_flow_state_v0"
    trial_number_within_family: int = 0
    family_trial_budget: int = 2
    formal_strategy_trial_count_before_and_after: int = 148
    anchor_epoch_utc: str = "2022-06-01T00:00:00Z"
    cutoff_exclusive_utc: str = "2026-07-01T00:00:00Z"
    aggregate_comparison_start_utc: str = "2022-06-01T00:00:00Z"
    aggregate_comparison_end_inclusive_utc: str = "2026-06-01T00:00:00Z"
    expected_aggregate_comparison_anchors: int = 209
    cross_chain_match_window_hours: int = 48
    cross_chain_max_relative_amount_difference: float = 0.0001
    cross_chain_minimum_amount_usd: int = 1_000_000
    maximum_finality_delay_seconds: int = 21_600
    minimum_classification_coverage: float = 1.0
    aggregate_equivalence_abs_spearman: float = 0.90
    aggregate_equivalence_r_squared: float = 0.80
    minimum_offsetting_flow_anchor_ratio: float = 0.10

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "hypothesis_family": self.hypothesis_family,
            "candidate_id": self.candidate_id,
            "trial_number_within_family": self.trial_number_within_family,
            "family_trial_budget": self.family_trial_budget,
            "formal_strategy_trial_count_before_and_after": (
                self.formal_strategy_trial_count_before_and_after
            ),
            "source_capacity": {
                "contract_hash": SOURCE_CAPACITY_CONTRACT_HASH,
                "artifact_sha256": SOURCE_CAPACITY_ARTIFACT_SHA256,
                "required_verdict": "pass_to_g0",
            },
            "sources": [
                {
                    "source_id": source.source_id,
                    "chain": source.chain,
                    "asset": source.asset,
                    "contract": source.contract,
                    "decimals": source.decimals,
                    "native_mint_events": list(source.native_mint_events),
                    "native_burn_events": list(source.native_burn_events),
                    "required_event_families": list(source.required_event_families),
                }
                for source in SOURCE_SPECS
            ],
            "data_role": "consumed_historical_discovery_pool",
            "coverage_only_history_allowed": True,
            "cross_source_sample_window": (
                "first_frozen_anchor_on_or_after_max_verified_first_usable_timestamp"
            ),
            "statistical_independence_unit": "one_weekly_utc_decision_anchor",
            "raw_event_independence_claimed": False,
            "result_permissions": {
                "market_prices_read": False,
                "strategy_results_read": False,
                "direction_allowed": False,
                "paper_or_live_allowed": False,
                "orders_allowed": False,
            },
        }

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "anchor_grid": {
                "epoch_utc": self.anchor_epoch_utc,
                "cadence_days": 7,
                "grid_definition": "epoch_plus_integer_multiples_of_7d",
                "cutoff_exclusive_utc": self.cutoff_exclusive_utc,
                "event_window": "previous_anchor_exclusive_to_anchor_inclusive_by_available_at",
            },
            "aggregate_supply_comparison": {
                "source": "defillama_aggregate_stablecoin_supply_existing_cache",
                "field_path": list(DEFAULT_STABLECOIN_SUPPLY_FIELD),
                "start_utc": self.aggregate_comparison_start_utc,
                "end_inclusive_utc": self.aggregate_comparison_end_inclusive_utc,
                "expected_anchor_count": self.expected_aggregate_comparison_anchors,
                "weekly_value": "asof(anchor)-asof(anchor-7d)",
                "equivalent_when": {
                    "absolute_spearman_at_least": self.aggregate_equivalence_abs_spearman,
                    "linear_r_squared_at_least": self.aggregate_equivalence_r_squared,
                    "offsetting_flow_anchor_ratio_at_most": (
                        self.minimum_offsetting_flow_anchor_ratio
                    ),
                },
            },
            "classification": {
                "vocabulary": [
                    "mint",
                    "burn",
                    "treasury_transfer",
                    "cross_chain_migration",
                    "unknown",
                ],
                "minimum_coverage": self.minimum_classification_coverage,
                "native_events_take_precedence_over_zero_address_transfer_duplicates": True,
                "unknown_events_fail_closed": True,
            },
            "event_accounting": {
                "lineage_includes_zero_amount_events": True,
                "economic_features_require_strictly_positive_amount": True,
                "zero_amount_policy": (
                    "retain_raw_and_finality_lineage_exclude_economic_flow_and_count"
                ),
                "source_declared_and_observed_counts_must_reconcile": True,
            },
            "deduplication": {
                "raw_identity": "chain+transaction_hash+event_index",
                "transaction_semantic_identity": (
                    "chain+asset+transaction_hash+amount+supply_classification"
                ),
                "cross_chain_cluster": {
                    "same_asset": True,
                    "opposite_supply_classification": True,
                    "different_chain": True,
                    "maximum_hours": self.cross_chain_match_window_hours,
                    "maximum_relative_amount_difference": (
                        self.cross_chain_max_relative_amount_difference
                    ),
                    "minimum_amount_usd": self.cross_chain_minimum_amount_usd,
                    "matching": "deterministic_greedy_min_amount_then_time_distance",
                },
            },
            "revision_finality_availability": {
                "exact_available_at_required": True,
                "canonical_block_recheck_required": True,
                "removed_or_reorged_event_fails_closed": True,
                "maximum_finality_delay_seconds": self.maximum_finality_delay_seconds,
            },
            "kill_tests": [
                "source_coverage_incomplete",
                "classification_coverage_below_one",
                "event_family_or_treasury_semantics_incomplete",
                "transaction_double_count_audit_incomplete",
                "cross_chain_cluster_audit_incomplete",
                "revision_or_finality_clock_incomplete",
                "weekly_independent_sample_or_baseline_incomplete",
                "equivalent_to_aggregate_supply",
            ],
            "result_read_order": (
                "preregister_then_read_chain_events_then_build_no_market_result"
            ),
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


STABLECOIN_IMPULSE_G0_PROTOCOL = StablecoinImpulseG0Protocol()


def _parse_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_missing")
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field}_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field}_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _HEX for char in value.lower())
    )


def _block_hash_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    rendered = value.lower().removeprefix("0x")
    return len(rendered) == 64 and all(char in _HEX for char in rendered)


def _evidence_artifact_hashes(payload: Mapping[str, Any]) -> frozenset[str]:
    collection = payload.get("collection", {})
    if not isinstance(collection, Mapping):
        return frozenset()
    references = collection.get("evidence_artifacts", [])
    if not isinstance(references, list):
        return frozenset()
    hashes: set[str] = set()
    for reference in references:
        if not isinstance(reference, Mapping):
            continue
        path = str(reference.get("path", ""))
        digest = reference.get("sha256")
        size = reference.get("size_bytes")
        if (
            path
            and "/" not in path
            and "\\" not in path
            and _sha256_text(digest)
            and isinstance(size, int)
            and size >= 0
        ):
            hashes.add(str(digest).lower())
    return frozenset(hashes)


def _canonical_embedded_hash(
    payload: Mapping[str, Any],
    *,
    hash_field: str,
) -> bool:
    declared = payload.get(hash_field)
    if not _sha256_text(declared):
        return False
    basis = {key: value for key, value in payload.items() if key != hash_field}
    return canonical_hash(basis) == str(declared).lower()


def _semantic_proof_complete(
    entry: Mapping[str, Any],
    spec: StablecoinChainSourceSpec,
    evidence_hashes: frozenset[str],
) -> bool:
    source_hash = str(entry.get("verified_source_artifact_sha256", "")).lower()
    proof = entry.get("semantic_proof", {})
    if (
        source_hash not in evidence_hashes
        or not _sha256_text(entry.get("abi_sha256"))
        or not _sha256_text(entry.get("runtime_code_sha256"))
        or entry.get("verification_match") not in {"match", "exact_match"}
        or not isinstance(proof, Mapping)
        or not _canonical_embedded_hash(proof, hash_field="proof_hash")
        or str(proof.get("source_artifact_sha256", "")).lower() != source_hash
        or proof.get("proof_kind")
        not in {
            "verified_source_ast",
            "verified_source_control_flow",
            "verified_bytecode_and_complete_event_overlap",
        }
    ):
        return False
    mint_calls = {str(value).lower() for value in proof.get("native_mint_event_calls", [])}
    burn_calls = {str(value).lower() for value in proof.get("native_burn_event_calls", [])}
    storage_writes = proof.get("supply_storage_writes", [])
    zero_behavior = proof.get("zero_transfer_emission")
    return (
        set(spec.native_mint_events).issubset(mint_calls)
        and set(spec.native_burn_events).issubset(burn_calls)
        and isinstance(storage_writes, list)
        and len(storage_writes) >= 2
        and zero_behavior in {"absent", "paired"}
    )


def _implementation_history_complete(
    semantics: Mapping[str, Any],
    spec: StablecoinChainSourceSpec,
    evidence_hashes: frozenset[str],
) -> tuple[bool, list[Mapping[str, Any]]]:
    history = semantics.get("implementation_history", {})
    if not isinstance(history, Mapping):
        return False, []
    entries = history.get("entries", [])
    if not isinstance(entries, list) or not entries:
        return False, []
    proxy_expected = spec.source_id == "usdc_ethereum"
    if (
        history.get("complete") is not True
        or history.get("is_proxy") is not proxy_expected
        or not isinstance(history.get("deployment_block"), int)
        or int(history.get("deployment_block", -1)) < 0
        or not isinstance(history.get("observed_through_block"), int)
        or int(history.get("observed_through_block", -1))
        < int(history.get("deployment_block", 0))
        or history.get("upgrade_event_count") != len(entries) - 1
        or not _sha256_text(history.get("timeline_hash"))
    ):
        return False, []
    if proxy_expected:
        if len(entries) < 2 or not str(history.get("proxy_type", "")).strip():
            return False, []
    elif len(entries) != 1 or history.get("proxy_type") != "none":
        return False, []

    previous_activation: tuple[int, int, int] | None = None
    normalized_entries: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            return False, []
        address = _address(entry.get("implementation_address"))
        activation = entry.get("activated_at", {})
        if (
            not address
            or not isinstance(activation, Mapping)
            or not isinstance(activation.get("block_number"), int)
            or not isinstance(activation.get("transaction_index"), int)
            or not isinstance(activation.get("event_index"), int)
            or not _semantic_proof_complete(entry, spec, evidence_hashes)
        ):
            return False, []
        position = (
            int(activation["block_number"]),
            int(activation["transaction_index"]),
            int(activation["event_index"]),
        )
        if previous_activation is not None and position <= previous_activation:
            return False, []
        previous_activation = position
        normalized_entries.append(entry)
    timeline_basis = {
        "deployment_block": history["deployment_block"],
        "observed_through_block": history["observed_through_block"],
        "is_proxy": history["is_proxy"],
        "proxy_type": history["proxy_type"],
        "entries": entries,
    }
    if canonical_hash(timeline_basis) != str(history["timeline_hash"]).lower():
        return False, []
    return True, normalized_entries


def _zero_transfer_audit_complete(
    semantics: Mapping[str, Any],
    implementation_entries: Sequence[Mapping[str, Any]],
    evidence_hashes: frozenset[str],
) -> bool:
    audit = semantics.get("zero_transfer_overlap_audit", {})
    if not isinstance(audit, Mapping):
        return False
    method = audit.get("method")
    if (
        audit.get("complete") is not True
        or method
        not in {"complete_chain_log_query", "implementation_complete_control_flow_proof"}
        or not isinstance(audit.get("native_event_count"), int)
        or int(audit.get("native_event_count", -1)) < 0
        or not isinstance(audit.get("zero_transfer_event_count"), int)
        or int(audit.get("zero_transfer_event_count", -1)) < 0
        or not isinstance(audit.get("paired_native_event_count"), int)
        or not isinstance(audit.get("unmatched_native_event_count"), int)
        or not isinstance(audit.get("unmatched_zero_transfer_event_count"), int)
        or audit.get("ambiguous_pair_count") != 0
        or audit.get("duplicate_suppression_policy")
        != "native_supply_event_precedence"
        or audit.get("suppressed_duplicate_count")
        != audit.get("paired_native_event_count")
        or not isinstance(audit.get("materialized_lineage_event_count"), int)
        or int(audit.get("materialized_lineage_event_count", -1)) < 0
        or not isinstance(audit.get("materialized_economic_event_count"), int)
        or int(audit.get("materialized_economic_event_count", -1)) < 0
        or not isinstance(
            audit.get("materialized_zero_amount_event_count_excluded"), int
        )
        or int(audit.get("materialized_zero_amount_event_count_excluded", -1)) < 0
        or not _canonical_embedded_hash(audit, hash_field="audit_hash")
    ):
        return False
    proof_hashes = {
        str(value).lower() for value in audit.get("evidence_artifact_sha256", [])
    }
    if not proof_hashes or not proof_hashes.issubset(evidence_hashes):
        return False
    implementation_addresses = {
        _address(entry.get("implementation_address")) for entry in implementation_entries
    }
    proof_addresses = {
        _address(value) for value in audit.get("implementation_addresses_proven", [])
    }
    if implementation_addresses != proof_addresses:
        return False
    native_count = int(audit["native_event_count"])
    zero_count = int(audit["zero_transfer_event_count"])
    paired_count = int(audit["paired_native_event_count"])
    unmatched_native = int(audit["unmatched_native_event_count"])
    unmatched_zero = int(audit["unmatched_zero_transfer_event_count"])
    materialized_lineage = int(audit["materialized_lineage_event_count"])
    materialized_economic = int(audit["materialized_economic_event_count"])
    materialized_zero = int(
        audit["materialized_zero_amount_event_count_excluded"]
    )
    counts_reconcile = (
        0 <= paired_count <= native_count
        and 0 <= paired_count <= zero_count
        and unmatched_native == native_count - paired_count
        and unmatched_zero == zero_count - paired_count
        and materialized_lineage == materialized_economic + materialized_zero
    )
    if not counts_reconcile:
        return False
    if method == "implementation_complete_control_flow_proof":
        return (
            zero_count == native_count == paired_count
            and unmatched_native == 0
            and unmatched_zero == 0
            and materialized_lineage in {0, zero_count}
        )
    return zero_count == materialized_lineage


def _treasury_history(
    semantics: Mapping[str, Any],
    spec: StablecoinChainSourceSpec,
    evidence_hashes: frozenset[str],
) -> tuple[bool, tuple[Mapping[str, Any], ...]]:
    audit = semantics.get("treasury_transfer_audit", {})
    if not isinstance(audit, Mapping):
        return False, ()
    required = "treasury_transfer" in spec.required_event_families
    history = audit.get("address_history", [])
    if not isinstance(history, list):
        return False, ()
    if not required:
        complete = (
            audit.get("required") is False
            and audit.get("complete") is True
            and history == []
            and audit.get("included_event_count") == 0
            and audit.get("lineage_event_count") == 0
            and audit.get("economic_event_count") == 0
            and audit.get("zero_amount_event_count_excluded") == 0
            and _canonical_embedded_hash(audit, hash_field="audit_hash")
        )
        return complete, ()
    if (
        audit.get("required") is not True
        or audit.get("complete") is not True
        or audit.get("derivation") != "issue_redeem_owner_balance"
        or not history
        or not isinstance(audit.get("included_event_count"), int)
        or int(audit.get("included_event_count", -1)) < 0
        or audit.get("unmatched_event_count") != 0
        or not isinstance(audit.get("lineage_event_count"), int)
        or not isinstance(audit.get("economic_event_count"), int)
        or not isinstance(audit.get("zero_amount_event_count_excluded"), int)
        or audit.get("included_event_count") != audit.get("economic_event_count")
        or audit.get("lineage_event_count")
        != audit.get("economic_event_count")
        + audit.get("zero_amount_event_count_excluded")
        or audit.get("owner_history_round_trip_absence_proven") is not True
        or audit.get("owner_history_proof_kind")
        not in {
            "initial_eoa_complete_block_scan_plus_verified_multisig_complete_state_enumeration",
            "complete_confirmed_ownership_event_history",
        }
        or str(audit.get("owner_history_proof_sha256", "")).lower()
        not in evidence_hashes
        or not _canonical_embedded_hash(audit, hash_field="audit_hash")
    ):
        return False, ()
    query_hashes = {
        str(value).lower() for value in audit.get("evidence_artifact_sha256", [])
    }
    if not query_hashes or not query_hashes.issubset(evidence_hashes):
        return False, ()
    previous_end: int | None = None
    normalized: list[Mapping[str, Any]] = []
    for row in history:
        if not isinstance(row, Mapping):
            return False, ()
        address = _address(row.get("address"))
        start = row.get("valid_from_block")
        end = row.get("valid_to_block_exclusive")
        activation_hash = str(row.get("activation_evidence_sha256", "")).lower()
        if (
            not address
            or not isinstance(start, int)
            or start < 0
            or (end is not None and (not isinstance(end, int) or end <= start))
            or activation_hash not in evidence_hashes
            or (previous_end is not None and start != previous_end)
        ):
            return False, ()
        previous_end = end
        normalized.append(row)
    if normalized[-1].get("valid_to_block_exclusive") is not None:
        return False, ()
    return True, tuple(normalized)


def _treasury_address_matches(
    address_history: Sequence[Mapping[str, Any]],
    address: str | None,
    block_number: int,
) -> bool:
    if address is None:
        return False
    for row in address_history:
        if _address(row.get("address")) != address:
            continue
        start = int(row["valid_from_block"])
        end = row.get("valid_to_block_exclusive")
        if block_number >= start and (end is None or block_number < int(end)):
            return True
    return False


def _event_exact_confirmation_complete(
    event: Mapping[str, Any],
    *,
    spec: StablecoinChainSourceSpec,
    event_at: datetime,
    available_at: datetime,
    block_number: int,
    evidence_hashes: frozenset[str],
) -> bool:
    confirmation_timestamp = event.get("confirmation_block_timestamp")
    try:
        confirmation_at = _parse_utc(
            confirmation_timestamp,
            field="confirmation_block_timestamp",
        )
    except ValueError:
        return False
    if confirmation_at != available_at or available_at < event_at:
        return False
    if (
        event.get("canonical_block_rechecked") is not True
        or not _block_hash_text(event.get("block_hash"))
        or not _block_hash_text(event.get("confirmation_block_hash"))
        or not isinstance(event.get("confirmation_block_number"), int)
        or str(event.get("confirmation_evidence_sha256", "")).lower()
        not in evidence_hashes
    ):
        return False
    confirmation_block = int(event["confirmation_block_number"])
    if spec.chain == "ethereum":
        return (
            event.get("availability_policy") == _ETHEREUM_CONFIRMATION_POLICY
            and confirmation_block == block_number + 64
        )
    event_producer = _address(event.get("event_block_producer"))
    subsequent = [
        _address(value)
        for value in event.get("confirmation_subsequent_sr_addresses", [])
    ]
    return (
        event.get("availability_policy") == _TRON_CONFIRMATION_POLICY
        and confirmation_block > block_number
        and event.get("confirmation_acknowledgement_count") == 19
        and event.get("confirmation_subsequent_distinct_sr_count") == 18
        and event_producer is not None
        and len(subsequent) == 18
        and None not in subsequent
        and len(set(subsequent)) == 18
        and event_producer not in subsequent
        and _address(event.get("confirmation_block_producer")) == subsequent[-1]
    )


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _event_amount(event: Mapping[str, Any], decimals: int) -> Decimal:
    if event.get("raw_amount") is not None:
        try:
            raw = Decimal(str(event["raw_amount"]))
        except InvalidOperation as exc:
            raise ValueError("raw_amount_invalid") from exc
        amount = raw / (Decimal(10) ** decimals)
    else:
        try:
            amount = Decimal(str(event.get("amount")))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("amount_invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("amount_negative_or_non_finite")
    return amount


def _address(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip().lower()
    return rendered or None


def _is_zero_address(value: str | None) -> bool:
    return value in {_ZERO_EVM, _ZERO_TRON, "0x0", "0", ""}


def _event_family(event_name: str, classification: str) -> str:
    if event_name == "transfer" and classification in {"mint", "burn"}:
        return "zero_transfer"
    if event_name == "transfer" and classification == "treasury_transfer":
        return "treasury_transfer"
    if classification in {"mint", "burn"}:
        return "native_supply"
    return "unknown"


def _classify_event(
    event: Mapping[str, Any],
    spec: StablecoinChainSourceSpec,
    treasury_address_history: Sequence[Mapping[str, Any]],
    block_number: int,
) -> tuple[str, str]:
    event_name = str(event.get("event_name", "")).strip().lower()
    from_address = _address(event.get("from_address"))
    to_address = _address(event.get("to_address"))
    if event_name in spec.native_mint_events:
        return "mint", "native_supply"
    if event_name in spec.native_burn_events:
        return "burn", "native_supply"
    if event_name != "transfer":
        return "unknown", "unknown"
    if _is_zero_address(from_address) and not _is_zero_address(to_address):
        return "mint", "zero_transfer"
    if _is_zero_address(to_address) and not _is_zero_address(from_address):
        return "burn", "zero_transfer"
    if _treasury_address_matches(
        treasury_address_history, from_address, block_number
    ) or _treasury_address_matches(
        treasury_address_history, to_address, block_number
    ):
        return "treasury_transfer", "treasury_transfer"
    return "unknown", "unknown"


def build_stablecoin_impulse_preregistration(created_at: str) -> dict[str, Any]:
    _parse_utc(created_at, field="created_at")
    protocol = STABLECOIN_IMPULSE_G0_PROTOCOL
    return {
        "schema_version": STABLECOIN_IMPULSE_PREREG_VERSION,
        "artifact_type": "stablecoin_liquidity_impulse_g0_preregistration",
        "created_at": created_at,
        "meta": {
            "research_only": True,
            "data_role": "consumed_historical_discovery_pool",
            "chain_event_results_read": False,
            "market_data_read": False,
            "strategy_results_read": False,
            "formal_strategy_trial_created": False,
            "paper_or_live_allowed": False,
            "orders_allowed": False,
        },
        "decision_contract": {
            **protocol.contract_basis,
            "contract_hash": protocol.contract_hash,
        },
        "audit_protocol": {
            **protocol.protocol_basis,
            "protocol_hash": protocol.protocol_hash,
        },
    }


def validate_stablecoin_impulse_preregistration(payload: Mapping[str, Any]) -> None:
    protocol = STABLECOIN_IMPULSE_G0_PROTOCOL
    if payload.get("schema_version") != STABLECOIN_IMPULSE_PREREG_VERSION:
        raise ValueError("unexpected_stablecoin_impulse_preregistration_schema")
    _parse_utc(payload.get("created_at"), field="created_at")
    contract = dict(payload.get("decision_contract", {}))
    declared_contract_hash = contract.pop("contract_hash", None)
    if (
        declared_contract_hash != protocol.contract_hash
        or canonical_hash(contract) != protocol.contract_hash
    ):
        raise ValueError("stablecoin_impulse_contract_hash_mismatch")
    audit_protocol = dict(payload.get("audit_protocol", {}))
    declared_protocol_hash = audit_protocol.pop("protocol_hash", None)
    if (
        declared_protocol_hash != protocol.protocol_hash
        or canonical_hash(audit_protocol) != protocol.protocol_hash
    ):
        raise ValueError("stablecoin_impulse_protocol_hash_mismatch")
    meta = payload.get("meta", {})
    for key in ("chain_event_results_read", "market_data_read", "strategy_results_read"):
        if meta.get(key) is not False:
            raise ValueError(f"stablecoin_impulse_preregistration_result_leak:{key}")
    if meta.get("formal_strategy_trial_created") is not False:
        raise ValueError("stablecoin_impulse_preregistration_trial_leak")


def frozen_weekly_anchors(
    start: datetime,
    end: datetime,
    *,
    end_inclusive: bool,
) -> list[datetime]:
    """Return anchors on the frozen epoch phase, including negative multiples."""

    protocol = STABLECOIN_IMPULSE_G0_PROTOCOL
    epoch = _parse_utc(protocol.anchor_epoch_utc, field="anchor_epoch_utc")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    periods = math.ceil((start - epoch).total_seconds() / _WEEK.total_seconds())
    cursor = epoch + periods * _WEEK
    anchors: list[datetime] = []
    while cursor < end or (end_inclusive and cursor <= end):
        anchors.append(cursor)
        cursor += _WEEK
    return anchors


def _normalize_source(
    payload: Mapping[str, Any],
    *,
    cutoff: datetime,
) -> tuple[dict[str, Any], list[_NormalizedEvent]]:
    source_id = str(payload.get("source_id", ""))
    spec = _SOURCE_BY_ID.get(source_id)
    errors: list[str] = []
    if spec is None:
        return {
            "source_id": source_id,
            "valid": False,
            "errors": ["source_id_not_frozen"],
        }, []
    if payload.get("schema_version") != STABLECOIN_CHAIN_SOURCE_VERSION:
        errors.append("source_schema_invalid")
    if str(payload.get("chain", "")).lower() != spec.chain:
        errors.append("chain_mismatch")
    if str(payload.get("asset", "")).upper() != spec.asset:
        errors.append("asset_mismatch")
    if str(payload.get("contract", "")).lower() != spec.contract:
        errors.append("contract_mismatch")
    if payload.get("decimals") != spec.decimals:
        errors.append("decimals_mismatch")

    coverage = payload.get("coverage", {})
    try:
        query_start = _parse_utc(coverage.get("query_start_at"), field="query_start_at")
        query_end = _parse_utc(
            coverage.get("query_end_exclusive"), field="query_end_exclusive"
        )
        first_usable = _parse_utc(
            coverage.get("first_usable_at"), field="first_usable_at"
        )
    except ValueError as exc:
        errors.append(str(exc))
        query_start = cutoff
        query_end = cutoff
        first_usable = cutoff
    coverage_complete = (
        coverage.get("complete") is True
        and coverage.get("gap_count") == 0
        and query_start < cutoff
        and query_end >= cutoff
        and query_start <= first_usable < cutoff
    )
    if not coverage_complete:
        errors.append("coverage_incomplete")
    requested_families = {
        str(value) for value in coverage.get("event_families_requested", [])
    }
    complete_families = {
        str(value) for value in coverage.get("event_families_complete", [])
    }
    required_families = set(spec.required_event_families)
    event_family_audit_complete = required_families.issubset(
        requested_families & complete_families
    )
    if not event_family_audit_complete:
        errors.append("required_event_family_incomplete")

    raw_semantics = payload.get("semantics", {})
    semantics = raw_semantics if isinstance(raw_semantics, Mapping) else {}
    declared_evidence_hashes = semantics.get("evidence_hashes", [])
    evidence_artifact_hashes = _evidence_artifact_hashes(payload)
    normalized_declared_hashes = {
        str(value).lower()
        for value in declared_evidence_hashes
        if _sha256_text(value)
    }
    semantic_capabilities = {str(value) for value in semantics.get("supports", [])}
    required_capabilities = {"mint", "burn"}
    if "treasury_transfer" in required_families:
        required_capabilities.add("treasury_transfer")
    implementation_complete, implementation_entries = (
        _implementation_history_complete(
            semantics,
            spec,
            evidence_artifact_hashes,
        )
    )
    zero_transfer_complete = _zero_transfer_audit_complete(
        semantics,
        implementation_entries,
        evidence_artifact_hashes,
    )
    treasury_complete, treasury_address_history = _treasury_history(
        semantics,
        spec,
        evidence_artifact_hashes,
    )
    semantic_audit_complete = (
        semantics.get("verified") is True
        and isinstance(declared_evidence_hashes, list)
        and len(declared_evidence_hashes) > 0
        and len(normalized_declared_hashes) == len(declared_evidence_hashes)
        and normalized_declared_hashes == evidence_artifact_hashes
        and required_capabilities.issubset(semantic_capabilities)
        and implementation_complete
        and zero_transfer_complete
        and treasury_complete
    )
    if not semantic_audit_complete:
        errors.append("classification_semantics_incomplete")

    raw_finality = payload.get("finality", {})
    finality = raw_finality if isinstance(raw_finality, Mapping) else {}
    raw_accounting = payload.get("event_accounting", {})
    event_accounting = (
        raw_accounting if isinstance(raw_accounting, Mapping) else {}
    )
    raw_collection = payload.get("collection", {})
    collection = raw_collection if isinstance(raw_collection, Mapping) else {}
    expected_policy = (
        _ETHEREUM_CONFIRMATION_POLICY
        if spec.chain == "ethereum"
        else _TRON_CONFIRMATION_POLICY
    )
    finality_audit_complete = (
        finality.get("exact_availability") is True
        and finality.get("canonical_recheck_complete") is True
        and finality.get("reorg_detected_count") == 0
        and finality.get("policy") == expected_policy
        and str(finality.get("evidence_artifact_sha256", "")).lower()
        in evidence_artifact_hashes
        and str(finality.get("policy_source_artifact_sha256", "")).lower()
        in evidence_artifact_hashes
        and (
            spec.chain != "ethereum"
            or (
                finality.get("confirmation_blocks") == 64
                and finality.get("native_consensus_finality_claimed") is False
            )
        )
        and (
            spec.chain != "tron"
            or (
                finality.get("acknowledgement_count") == 19
                and finality.get("subsequent_distinct_sr_count") == 18
            )
        )
    )
    if not finality_audit_complete:
        errors.append("revision_finality_audit_incomplete")

    normalized_events: list[_NormalizedEvent] = []
    event_errors: list[str] = []
    lineage_family_counts: Counter[str] = Counter()
    economic_family_counts: Counter[str] = Counter()
    zero_amount_family_counts: Counter[str] = Counter()
    raw_events = payload.get("events", [])
    if (
        not isinstance(raw_events, Iterable)
        or isinstance(raw_events, (str, bytes, bytearray, Mapping))
    ):
        raw_events = []
        event_errors.append("events_not_iterable")
    raw_event_count = 0
    for row_number, raw_event in enumerate(raw_events):
        raw_event_count += 1
        if not isinstance(raw_event, Mapping):
            event_errors.append(f"event_{row_number}_not_object")
            continue
        try:
            event_at = _parse_utc(
                raw_event.get("block_timestamp"), field="block_timestamp"
            )
            available_at = _parse_utc(
                raw_event.get("available_at"), field="available_at"
            )
            if available_at < event_at:
                raise ValueError("available_at_before_event")
            amount = _event_amount(raw_event, spec.decimals)
            transaction_hash = str(raw_event.get("transaction_hash", "")).strip().lower()
            block_hash = str(raw_event.get("block_hash", "")).strip().lower()
            event_index = int(raw_event.get("event_index"))
            block_number = int(raw_event.get("block_number"))
            if not transaction_hash:
                raise ValueError("transaction_hash_missing")
            if not block_hash:
                raise ValueError("block_hash_missing")
            if event_index < 0 or block_number < 0:
                raise ValueError("event_position_negative")
            if raw_event.get("removed") is not False:
                raise ValueError("event_removed_or_revision_unknown")
            if not _event_exact_confirmation_complete(
                raw_event,
                spec=spec,
                event_at=event_at,
                available_at=available_at,
                block_number=block_number,
                evidence_hashes=evidence_artifact_hashes,
            ):
                raise ValueError("exact_confirmation_evidence_invalid")
            classification, family = _classify_event(
                raw_event,
                spec,
                treasury_address_history,
                block_number,
            )
            event_name = str(raw_event.get("event_name", "")).strip().lower()
            lineage_family_counts[family] += 1
            if amount == 0:
                if event_name != "transfer" or family not in {
                    "zero_transfer",
                    "treasury_transfer",
                }:
                    raise ValueError("zero_amount_event_not_frozen_transfer_family")
                zero_amount_family_counts[family] += 1
                continue
            economic_family_counts[family] += 1
            normalized_events.append(
                _NormalizedEvent(
                    source_id=source_id,
                    chain=spec.chain,
                    asset=spec.asset,
                    contract=spec.contract,
                    transaction_hash=transaction_hash,
                    block_number=block_number,
                    block_hash=block_hash,
                    event_index=event_index,
                    event_name=event_name,
                    event_at=event_at,
                    available_at=available_at,
                    amount=amount,
                    from_address=_address(raw_event.get("from_address")),
                    to_address=_address(raw_event.get("to_address")),
                    supply_classification=classification,
                    classification=classification,
                    event_family=family,
                )
            )
        except (ValueError, TypeError) as exc:
            event_errors.append(f"event_{row_number}_{exc}")
    if event_errors:
        errors.append("event_validation_failed")

    economic_event_count = len(normalized_events)
    zero_amount_event_count = sum(zero_amount_family_counts.values())
    event_accounting_complete = (
        event_accounting.get("zero_amount_policy")
        == "retain_raw_and_finality_lineage_exclude_economic_flow_and_count"
        and event_accounting.get("lineage_event_count") == raw_event_count
        and event_accounting.get("economic_event_count") == economic_event_count
        and event_accounting.get("zero_amount_event_count_excluded")
        == zero_amount_event_count
        and raw_event_count == economic_event_count + zero_amount_event_count
        and collection.get("raw_event_count") == raw_event_count
    )
    if not event_accounting_complete:
        errors.append("event_accounting_count_mismatch")

    native_event_count = sum(
        event.event_family == "native_supply" for event in normalized_events
    )
    treasury_event_count = sum(
        event.event_family == "treasury_transfer" for event in normalized_events
    )
    zero_audit = semantics.get("zero_transfer_overlap_audit", {})
    treasury_audit = semantics.get("treasury_transfer_audit", {})
    if (
        not isinstance(zero_audit, Mapping)
        or zero_audit.get("native_event_count") != native_event_count
        or zero_audit.get("materialized_lineage_event_count")
        != lineage_family_counts["zero_transfer"]
        or zero_audit.get("materialized_economic_event_count")
        != economic_family_counts["zero_transfer"]
        or zero_audit.get("materialized_zero_amount_event_count_excluded")
        != zero_amount_family_counts["zero_transfer"]
    ):
        semantic_audit_complete = False
        errors.append("zero_transfer_native_count_mismatch")
    if (
        not isinstance(treasury_audit, Mapping)
        or treasury_audit.get("included_event_count") != treasury_event_count
        or treasury_audit.get("lineage_event_count")
        != lineage_family_counts["treasury_transfer"]
        or treasury_audit.get("economic_event_count")
        != economic_family_counts["treasury_transfer"]
        or treasury_audit.get("zero_amount_event_count_excluded")
        != zero_amount_family_counts["treasury_transfer"]
    ):
        semantic_audit_complete = False
        errors.append("treasury_transfer_count_mismatch")
    if (
        finality.get("event_count") != raw_event_count
        or finality.get("lineage_event_count") != raw_event_count
        or finality.get("economic_event_count") != economic_event_count
        or finality.get("zero_amount_event_count_excluded")
        != zero_amount_event_count
    ):
        finality_audit_complete = False
        errors.append("finality_event_count_mismatch")

    source_audit = {
        "source_id": source_id,
        "chain": spec.chain,
        "asset": spec.asset,
        "contract": spec.contract,
        "valid": len(errors) == 0,
        "errors": sorted(set(errors)),
        "query_start_at": _utc_text(query_start),
        "query_end_exclusive": _utc_text(query_end),
        "first_usable_at": _utc_text(first_usable),
        "coverage_complete": coverage_complete,
        "required_event_families": sorted(required_families),
        "requested_event_families": sorted(requested_families),
        "complete_event_families": sorted(complete_families),
        "event_family_audit_complete": event_family_audit_complete,
        "semantic_audit_complete": semantic_audit_complete,
        "semantic_evidence_hash_count": len(normalized_declared_hashes),
        "implementation_count": len(implementation_entries),
        "zero_transfer_overlap_audit_complete": zero_transfer_complete,
        "treasury_transfer_audit_complete": treasury_complete,
        "treasury_address_count": len(treasury_address_history),
        "finality_audit_complete": finality_audit_complete,
        "event_accounting_complete": event_accounting_complete,
        "raw_event_count": raw_event_count,
        "lineage_event_count": raw_event_count,
        "economic_event_count": economic_event_count,
        "zero_amount_event_count_excluded": zero_amount_event_count,
        "lineage_event_family_counts": dict(sorted(lineage_family_counts.items())),
        "economic_event_family_counts": dict(sorted(economic_family_counts.items())),
        "zero_amount_event_family_counts": dict(
            sorted(zero_amount_family_counts.items())
        ),
        "normalized_event_count": economic_event_count,
        "invalid_event_count": len(event_errors),
        "event_validation_errors": event_errors,
    }
    return source_audit, normalized_events


def _raw_deduplicate(
    events: Sequence[Any],
) -> tuple[list[Any], int]:
    seen: set[tuple[str, str, int]] = set()
    retained: list[Any] = []
    duplicate_count = 0
    for event in events:
        identity = (
            event["chain"],
            event["transaction_hash"],
            event["event_index"],
        )
        if identity in seen:
            duplicate_count += 1
            continue
        seen.add(identity)
        retained.append(event)
    return retained, duplicate_count


def _transaction_semantic_deduplicate(
    events: Sequence[Any],
) -> tuple[list[Any], int]:
    if not any(event["event_family"] == "zero_transfer" for event in events):
        return sorted(
            events,
            key=lambda row: (
                row["available_at"],
                row["chain"],
                row["event_index"],
            ),
        ), 0

    by_identity: dict[tuple[str, str, str, str, str], list[Any]] = {}
    for event in events:
        identity = (
            event["chain"],
            event["asset"],
            event["transaction_hash"],
            _decimal_text(event["amount"]),
            event["supply_classification"],
        )
        by_identity.setdefault(identity, []).append(event)
    retained: list[Any] = []
    duplicate_count = 0
    for group in by_identity.values():
        families = {event["event_family"] for event in group}
        if (
            len(group) > 1
            and "native_supply" in families
            and "zero_transfer" in families
        ):
            native = sorted(
                (event for event in group if event["event_family"] == "native_supply"),
                key=lambda row: row["event_index"],
            )
            retained.extend(native)
            retained.extend(
                event
                for event in group
                if event["event_family"] not in {"native_supply", "zero_transfer"}
            )
            duplicate_count += sum(
                1 for event in group if event["event_family"] == "zero_transfer"
            )
        else:
            retained.extend(group)
    retained.sort(key=lambda row: (row["available_at"], row["chain"], row["event_index"]))
    return retained, duplicate_count


def _cross_chain_cluster(
    events: Sequence[Any],
) -> tuple[list[Any], list[dict[str, Any]]]:
    protocol = STABLECOIN_IMPULSE_G0_PROTOCOL
    minimum = Decimal(protocol.cross_chain_minimum_amount_usd)
    maximum_relative = Decimal(
        str(protocol.cross_chain_max_relative_amount_difference)
    )
    maximum_seconds = protocol.cross_chain_match_window_hours * 3600
    candidate_chains: dict[str, set[str]] = {}
    for event in events:
        if (
            event["supply_classification"] in {"mint", "burn"}
            and event["amount"] >= minimum
        ):
            candidate_chains.setdefault(event["asset"], set()).add(event["chain"])
    multi_chain_assets = {
        asset for asset, chains in candidate_chains.items() if len(chains) > 1
    }
    candidates = sorted(
        [
        event
        for event in events
        if event["supply_classification"] in {"mint", "burn"}
        and event["amount"] >= minimum
        and event["asset"] in multi_chain_assets
        ],
        key=lambda event: event["event_at"],
    )
    possible: list[tuple[Decimal, float, int, int]] = []
    for left_index, left in enumerate(candidates):
        for right_index in range(left_index + 1, len(candidates)):
            right = candidates[right_index]
            seconds = (right["event_at"] - left["event_at"]).total_seconds()
            if seconds > maximum_seconds:
                break
            if left["asset"] != right["asset"] or left["chain"] == right["chain"]:
                continue
            if left["supply_classification"] == right["supply_classification"]:
                continue
            amount_difference = abs(left["amount"] - right["amount"])
            relative = amount_difference / max(left["amount"], right["amount"])
            if relative <= maximum_relative:
                possible.append((relative, seconds, left_index, right_index))
    used: set[int] = set()
    clusters: list[dict[str, Any]] = []
    event_cluster: dict[tuple[str, str, int], str] = {}
    for relative, seconds, left_index, right_index in sorted(possible):
        if left_index in used or right_index in used:
            continue
        used.update({left_index, right_index})
        left = candidates[left_index]
        right = candidates[right_index]
        core = {
            "asset": left["asset"],
            "left": [left["chain"], left["transaction_hash"], left["event_index"]],
            "right": [right["chain"], right["transaction_hash"], right["event_index"]],
            "amount_relative_difference": float(relative),
            "time_difference_seconds": seconds,
        }
        cluster_id = canonical_hash(core)
        for event in (left, right):
            event_cluster[
                (event["chain"], event["transaction_hash"], event["event_index"])
            ] = cluster_id
        clusters.append({**core, "cluster_id": cluster_id})
    clustered: list[Any] = []
    for event in events:
        identity = (event["chain"], event["transaction_hash"], event["event_index"])
        cluster_id = event_cluster.get(identity)
        if cluster_id is None:
            clustered.append(event)
        elif isinstance(event, _NormalizedEvent):
            event.classification = "cross_chain_migration"
            event.economic_cluster_id = cluster_id
            clustered.append(event)
        else:
            clustered.append(
                {
                    **event,
                    "classification": "cross_chain_migration",
                    "economic_cluster_id": cluster_id,
                }
            )
    return clustered, clusters


def _rank(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and indexed[end][1] == indexed[cursor][1]:
            end += 1
        rank = (cursor + end - 1) / 2.0 + 1.0
        for position in range(cursor, end):
            ranks[indexed[position][0]] = rank
        cursor = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    numerator = sum(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right)
    )
    left_scale = sum((value - left_mean) ** 2 for value in left)
    right_scale = sum((value - right_mean) ** 2 for value in right)
    if left_scale <= 0.0 or right_scale <= 0.0:
        return None
    return numerator / math.sqrt(left_scale * right_scale)


def _linear_r_squared(left: Sequence[float], right: Sequence[float]) -> float | None:
    correlation = _pearson(left, right)
    return None if correlation is None else correlation * correlation


def _delay_summary(events: Sequence[Any]) -> dict[str, Any]:
    delays = Counter(
        (event["available_at"] - event["event_at"]).total_seconds()
        for event in events
    )
    count = sum(delays.values())
    if not count:
        return {"count": 0, "median_seconds": None, "p99_seconds": None, "max_seconds": None}

    def value_at(position: int) -> float:
        seen = 0
        for value, frequency in sorted(delays.items()):
            seen += frequency
            if position < seen:
                return value
        raise RuntimeError("stablecoin_delay_position_out_of_range")

    middle = count // 2
    median = (
        value_at(middle)
        if count % 2
        else (value_at(middle - 1) + value_at(middle)) / 2.0
    )
    p99_index = min(count - 1, math.ceil(0.99 * count) - 1)
    return {
        "count": count,
        "median_seconds": median,
        "p99_seconds": value_at(p99_index),
        "max_seconds": max(delays),
    }


def _weekly_rows(
    anchors: Sequence[datetime],
    events: Sequence[Any],
    source_audits: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    def source_covers(audit: Mapping[str, Any], previous: datetime, anchor: datetime) -> bool:
        if audit.get("coverage_complete") is not True:
            return False
        try:
            query_start = _parse_utc(
                audit.get("query_start_at"), field="query_start_at"
            )
            query_end = _parse_utc(
                audit.get("query_end_exclusive"), field="query_end_exclusive"
            )
        except ValueError:
            return False
        return query_start <= previous and query_end >= anchor

    ordered_events = sorted(events, key=lambda event: event["available_at"])
    event_cursor = 0
    rows: list[dict[str, Any]] = []
    for anchor in anchors:
        previous = anchor - _WEEK
        while (
            event_cursor < len(ordered_events)
            and ordered_events[event_cursor]["available_at"] <= previous
        ):
            event_cursor += 1
        selected_end = event_cursor
        while (
            selected_end < len(ordered_events)
            and ordered_events[selected_end]["available_at"] <= anchor
        ):
            selected_end += 1
        selected = ordered_events[event_cursor:selected_end]
        event_cursor = selected_end
        mint = sum(
            (event["amount"] for event in selected if event["classification"] == "mint"),
            Decimal(0),
        )
        burn = sum(
            (event["amount"] for event in selected if event["classification"] == "burn"),
            Decimal(0),
        )
        complete = len(source_audits) == len(SOURCE_SPECS) and all(
            source_covers(audit, previous, anchor) for audit in source_audits
        )
        counts = {
            classification: sum(
                event["classification"] == classification for event in selected
            )
            for classification in (
                "mint",
                "burn",
                "treasury_transfer",
                "cross_chain_migration",
                "unknown",
            )
        }
        active_sources = len({event["source_id"] for event in selected})
        gross = mint + burn
        net = mint - burn
        offsetting = gross - abs(net)
        offsetting_material = (
            gross > 0
            and offsetting >= Decimal(1_000_000)
            and offsetting / gross >= Decimal("0.10")
        )
        rows.append(
            {
                "anchor_utc": _utc_text(anchor),
                "complete": complete,
                "independence_unit": "weekly_anchor",
                "mint_amount_usd": _decimal_text(mint),
                "burn_amount_usd": _decimal_text(burn),
                "gross_supply_event_amount_usd": _decimal_text(gross),
                "economic_net_flow_usd": _decimal_text(net),
                "offsetting_flow_amount_usd": _decimal_text(offsetting),
                "offsetting_flow_material": offsetting_material,
                "active_source_count": active_sources,
                "event_counts": counts,
            }
        )
    return rows


def _aggregate_comparison(
    weekly_rows: Sequence[Mapping[str, Any]],
    aggregate_supply_rows: Any,
) -> dict[str, Any]:
    protocol = STABLECOIN_IMPULSE_G0_PROTOCOL
    comparison_start = _parse_utc(
        protocol.aggregate_comparison_start_utc,
        field="aggregate_comparison_start_utc",
    )
    comparison_end = _parse_utc(
        protocol.aggregate_comparison_end_inclusive_utc,
        field="aggregate_comparison_end_inclusive_utc",
    )
    expected = frozen_weekly_anchors(
        comparison_start, comparison_end, end_inclusive=True
    )
    indexed = {row["anchor_utc"]: row for row in weekly_rows}
    supply = normalize_stablecoin_supply_series(
        aggregate_supply_rows,
        field_path=DEFAULT_STABLECOIN_SUPPLY_FIELD,
    )
    event_values: list[float] = []
    aggregate_values: list[float] = []
    comparable_rows = 0
    missing_anchors: list[str] = []
    offsetting_count = 0
    for anchor in expected:
        anchor_text = _utc_text(anchor)
        weekly = indexed.get(anchor_text)
        current = asof_supply_at(supply, int(anchor.timestamp() * 1000))
        previous = asof_supply_at(supply, int((anchor - _WEEK).timestamp() * 1000))
        if (
            weekly is None
            or weekly.get("complete") is not True
            or current is None
            or previous is None
        ):
            missing_anchors.append(anchor_text)
            continue
        event_values.append(float(weekly["economic_net_flow_usd"]))
        aggregate_values.append(current - previous)
        offsetting_count += bool(weekly["offsetting_flow_material"])
        comparable_rows += 1
    pearson = _pearson(event_values, aggregate_values)
    spearman = _pearson(_rank(event_values), _rank(aggregate_values))
    r_squared = _linear_r_squared(event_values, aggregate_values)
    offsetting_ratio = offsetting_count / comparable_rows if comparable_rows else 0.0
    comparison_complete = (
        len(expected) == protocol.expected_aggregate_comparison_anchors
        and comparable_rows == len(expected)
        and len(missing_anchors) == 0
    )
    equivalent = (
        comparison_complete
        and spearman is not None
        and r_squared is not None
        and abs(spearman) >= protocol.aggregate_equivalence_abs_spearman
        and r_squared >= protocol.aggregate_equivalence_r_squared
        and offsetting_ratio <= protocol.minimum_offsetting_flow_anchor_ratio
    )
    return {
        "anchor_start_utc": _utc_text(expected[0]) if expected else None,
        "anchor_end_utc": _utc_text(expected[-1]) if expected else None,
        "expected_anchor_count": protocol.expected_aggregate_comparison_anchors,
        "frozen_anchor_count": len(expected),
        "comparable_anchor_count": comparable_rows,
        "missing_anchor_count": len(missing_anchors),
        "missing_anchors": missing_anchors,
        "comparison_complete": comparison_complete,
        "pearson_correlation": pearson,
        "spearman_correlation": spearman,
        "linear_r_squared": r_squared,
        "material_offsetting_flow_anchor_count": offsetting_count,
        "material_offsetting_flow_anchor_ratio": offsetting_ratio,
        "equivalent_to_aggregate_supply": equivalent,
        "thresholds": {
            "absolute_spearman_at_least": protocol.aggregate_equivalence_abs_spearman,
            "linear_r_squared_at_least": protocol.aggregate_equivalence_r_squared,
            "offsetting_flow_anchor_ratio_at_most": (
                protocol.minimum_offsetting_flow_anchor_ratio
            ),
        },
    }


def build_stablecoin_impulse_g0_report(
    source_payloads: Sequence[Mapping[str, Any]],
    aggregate_supply_rows: Any,
    preregistration: Mapping[str, Any],
    *,
    observed_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build the deterministic capacity report and weekly no-market feature rows."""

    validate_stablecoin_impulse_preregistration(preregistration)
    _parse_utc(observed_at, field="observed_at")
    protocol = STABLECOIN_IMPULSE_G0_PROTOCOL
    cutoff = _parse_utc(protocol.cutoff_exclusive_utc, field="cutoff_exclusive_utc")

    payload_by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_source_inputs: list[str] = []
    for payload in source_payloads:
        source_id = str(payload.get("source_id", ""))
        if source_id in payload_by_id:
            duplicate_source_inputs.append(source_id)
        else:
            payload_by_id[source_id] = payload
    source_audits: list[dict[str, Any]] = []
    normalized_events: list[_NormalizedEvent] = []
    for spec in SOURCE_SPECS:
        payload = payload_by_id.get(spec.source_id)
        if payload is None:
            source_audits.append(
                {
                    "source_id": spec.source_id,
                    "chain": spec.chain,
                    "asset": spec.asset,
                    "contract": spec.contract,
                    "valid": False,
                    "errors": ["source_input_missing"],
                    "coverage_complete": False,
                    "event_family_audit_complete": False,
                    "semantic_audit_complete": False,
                    "finality_audit_complete": False,
                    "raw_event_count": 0,
                    "normalized_event_count": 0,
                    "invalid_event_count": 0,
                }
            )
            continue
        audit, events = _normalize_source(payload, cutoff=cutoff)
        source_audits.append(audit)
        normalized_events.extend(event for event in events if event["event_at"] < cutoff)

    raw_unique_events, raw_duplicate_count = _raw_deduplicate(normalized_events)
    transaction_unique_events, semantic_duplicate_count = (
        _transaction_semantic_deduplicate(raw_unique_events)
    )
    clustered_events, economic_clusters = _cross_chain_cluster(transaction_unique_events)

    first_usable_values = []
    for audit in source_audits:
        if audit.get("first_usable_at"):
            first_usable_values.append(
                _parse_utc(audit["first_usable_at"], field="first_usable_at")
            )
    if len(first_usable_values) == len(SOURCE_SPECS):
        common_start_raw = max(first_usable_values)
        primary_anchors = frozen_weekly_anchors(
            common_start_raw, cutoff, end_inclusive=False
        )
    else:
        common_start_raw = None
        primary_anchors = []
    comparison_start = _parse_utc(
        protocol.aggregate_comparison_start_utc,
        field="aggregate_comparison_start_utc",
    )
    all_anchor_start = min(
        [anchor for anchor in (common_start_raw, comparison_start) if anchor is not None],
        default=comparison_start,
    )
    all_anchors = frozen_weekly_anchors(all_anchor_start, cutoff, end_inclusive=False)
    weekly_rows = _weekly_rows(all_anchors, clustered_events, source_audits)
    primary_anchor_set = {_utc_text(anchor) for anchor in primary_anchors}
    primary_rows = [row for row in weekly_rows if row["anchor_utc"] in primary_anchor_set]
    primary_complete_count = sum(row["complete"] for row in primary_rows)

    classification_counter = Counter(
        event["classification"] for event in clustered_events
    )
    classifications = {
        classification: classification_counter[classification]
        for classification in (
            "mint",
            "burn",
            "treasury_transfer",
            "cross_chain_migration",
            "unknown",
        )
    }
    known_count = len(clustered_events) - classifications["unknown"]
    classification_coverage = (
        known_count / len(clustered_events) if clustered_events else 0.0
    )
    delay = _delay_summary(clustered_events)
    aggregate = _aggregate_comparison(weekly_rows, aggregate_supply_rows)

    source_coverage_incomplete = (
        len(source_audits) != len(SOURCE_SPECS)
        or any(audit.get("coverage_complete") is not True for audit in source_audits)
        or bool(duplicate_source_inputs)
    )
    semantic_incomplete = any(
        audit.get("semantic_audit_complete") is not True
        or audit.get("event_family_audit_complete") is not True
        for audit in source_audits
    )
    revision_incomplete = (
        any(audit.get("finality_audit_complete") is not True for audit in source_audits)
        or delay["count"] != len(clustered_events)
        or (
            delay["max_seconds"] is not None
            and delay["max_seconds"] > protocol.maximum_finality_delay_seconds
        )
    )
    cross_chain_audit_complete = all(
        next(
            (
                audit.get("coverage_complete") is True
                and audit.get("semantic_audit_complete") is True
                for audit in source_audits
                if audit.get("source_id") == source_id
            ),
            False,
        )
        for source_id in ("usdt_ethereum", "usdt_tron")
    )
    weekly_incomplete = (
        not primary_rows
        or primary_complete_count != len(primary_rows)
        or aggregate["comparison_complete"] is not True
    )
    kill_tests = {
        "source_coverage_incomplete": source_coverage_incomplete,
        "classification_coverage_below_one": (
            classification_coverage < protocol.minimum_classification_coverage
        ),
        "event_family_or_treasury_semantics_incomplete": semantic_incomplete,
        "transaction_double_count_audit_incomplete": semantic_incomplete,
        "cross_chain_cluster_audit_incomplete": not cross_chain_audit_complete,
        "revision_or_finality_clock_incomplete": revision_incomplete,
        "weekly_independent_sample_or_baseline_incomplete": weekly_incomplete,
        "equivalent_to_aggregate_supply": aggregate[
            "equivalent_to_aggregate_supply"
        ],
    }
    capacity_blockers = {
        key: value
        for key, value in kill_tests.items()
        if key != "equivalent_to_aggregate_supply" and value
    }
    if capacity_blockers:
        verdict = "block_capacity"
    elif kill_tests["equivalent_to_aggregate_supply"]:
        verdict = "reject_as_aggregate_supply_repackaging"
    else:
        verdict = "pass_to_market_state_design"

    report = {
        "schema_version": STABLECOIN_IMPULSE_G0_VERSION,
        "artifact_type": "stablecoin_liquidity_impulse_g0",
        "observed_at": observed_at,
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "source_capacity_contract_hash": SOURCE_CAPACITY_CONTRACT_HASH,
        "source_capacity_artifact_sha256": SOURCE_CAPACITY_ARTIFACT_SHA256,
        "meta": {
            "research_only": True,
            "data_role": "consumed_historical_discovery_pool",
            "output_role": "coverage_classification_dedup_revision_samples_delay_no_market",
            "market_data_read": False,
            "strategy_results_read": False,
            "pnl_evaluated": False,
            "direction_produced": False,
            "formal_strategy_trial_created": False,
            "formal_strategy_trial_count_before": (
                protocol.formal_strategy_trial_count_before_and_after
            ),
            "formal_strategy_trial_count_after": (
                protocol.formal_strategy_trial_count_before_and_after
            ),
            "family_trial_number": protocol.trial_number_within_family,
            "candidate_pnl_ready": False,
            "promotion_evidence": False,
            "paper_or_live_allowed": False,
            "orders_authorized": False,
        },
        "window": {
            "anchor_epoch_utc": protocol.anchor_epoch_utc,
            "cutoff_exclusive_utc": protocol.cutoff_exclusive_utc,
            "common_start_policy": (
                "first_frozen_anchor_on_or_after_max_verified_first_usable_timestamp"
            ),
            "max_verified_first_usable_at": (
                _utc_text(common_start_raw) if common_start_raw else None
            ),
            "first_common_anchor_utc": (
                _utc_text(primary_anchors[0]) if primary_anchors else None
            ),
            "last_common_anchor_utc": (
                _utc_text(primary_anchors[-1]) if primary_anchors else None
            ),
        },
        "sources": source_audits,
        "events": {
            "lineage_before_economic_filter_count": sum(
                int(audit.get("lineage_event_count", 0)) for audit in source_audits
            ),
            "zero_amount_lineage_excluded_count": sum(
                int(audit.get("zero_amount_event_count_excluded", 0))
                for audit in source_audits
            ),
            "normalized_before_dedup_count": len(normalized_events),
            "raw_identity_duplicate_count": raw_duplicate_count,
            "transaction_semantic_duplicate_count": semantic_duplicate_count,
            "post_transaction_dedup_count": len(transaction_unique_events),
            "economic_cluster_count": len(economic_clusters),
            "economic_cluster_event_count": sum(
                event["classification"] == "cross_chain_migration"
                for event in clustered_events
            ),
            "post_cluster_event_count": len(clustered_events),
            "classification_counts": classifications,
            "classification_coverage": classification_coverage,
        },
        "revision_finality_availability": {
            "exact_available_at_required": True,
            "maximum_allowed_delay_seconds": protocol.maximum_finality_delay_seconds,
            "delay": delay,
            "audit_complete": not revision_incomplete,
        },
        "independent_samples": {
            "unit": "weekly_anchor",
            "raw_event_count_is_independent_sample_count": False,
            "primary_anchor_count": len(primary_rows),
            "primary_complete_anchor_count": primary_complete_count,
            "primary_missing_anchor_count": len(primary_rows) - primary_complete_count,
            "coverage_only_history_excluded_from_cross_source_count": True,
        },
        "aggregate_supply_comparison": aggregate,
        "kill_tests": kill_tests,
        "verdict": verdict,
        "remaining_blockers": sorted(capacity_blockers),
    }
    return report, weekly_rows
