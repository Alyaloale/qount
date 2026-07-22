"""Pure functions for building venue capability snapshots.

build_venue_capability_snapshot hashes the exchange_info schema,
extracts symbol rules, and validates position/margin mode and leverage.
No network calls in Phase A; callers pass fixture data.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from qount.contracts.hashing import canonical_hash
from qount.venue.contracts import VenueCapabilitySnapshot


def _hash_json(value: Any) -> str:
    return canonical_hash(
        json.loads(
            json.dumps(value, ensure_ascii=True, sort_keys=True)
        )
    )


def build_venue_capability_snapshot(
    *,
    venue: str,
    observed_at: str,
    exchange_info: Mapping[str, Any],
    symbol_rules: Mapping[str, Any],
    position_mode: str,
    margin_mode: str,
    leverage: int,
    server_time_offset_ms: int = 0,
    order_endpoint_contract_hashes: Mapping[str, str] | None = None,
    algo_endpoint_contract_hashes: Mapping[str, str] | None = None,
    order_capabilities: Mapping[str, Any] | None = None,
    conditional_algo_capabilities: Mapping[str, Any] | None = None,
    query_retention_assumptions: Mapping[str, Any] | None = None,
    websocket_assumptions: Mapping[str, Any] | None = None,
    rest_recovery_assumptions: Mapping[str, Any] | None = None,
    changelog_last_reviewed_at: str,
    changelog_source_hash: str,
    previous_snapshot: VenueCapabilitySnapshot | None = None,
) -> VenueCapabilitySnapshot:
    """Build a snapshot from exchange_info and symbol rules.

    Compatibility is determined by comparing against the previous
    snapshot (if any).  Without a previous snapshot, compatibility
    defaults to 'pass' if position_mode/margin_mode/leverage are valid.

    * precision/filter/endpoint change -> review_required
    * changelog text change -> review_required (caller provides hash)
    * invalid position_mode/margin_mode -> blocked
    """
    exchange_info_schema_hash = _hash_json(dict(exchange_info))
    symbol_rules_hash = _hash_json(dict(symbol_rules))

    blockers: list[str] = []
    if position_mode != "one_way":
        blockers.append("position_mode_not_one_way")
    if margin_mode != "isolated":
        blockers.append("margin_mode_not_isolated")
    if leverage < 1:
        blockers.append("leverage_invalid")

    compatibility = "pass"
    if blockers:
        compatibility = "blocked"
    elif previous_snapshot is not None:
        if (
            previous_snapshot.exchange_info_schema_hash
            != exchange_info_schema_hash
        ):
            compatibility = "review_required"
            blockers.append("exchange_info_schema_changed")
        elif (
            previous_snapshot.symbol_rules_hash != symbol_rules_hash
        ):
            compatibility = "review_required"
            blockers.append("symbol_rules_changed")
        elif (
            previous_snapshot.changelog_source_hash
            != changelog_source_hash
        ):
            compatibility = "review_required"
            blockers.append("changelog_text_changed")

    if compatibility == "pass":
        blockers = []

    return VenueCapabilitySnapshot.create(
        venue=venue,
        observed_at=observed_at,
        server_time_offset_ms=server_time_offset_ms,
        exchange_info_schema_hash=exchange_info_schema_hash,
        symbol_rules_hash=symbol_rules_hash,
        position_mode=position_mode,
        margin_mode=margin_mode,
        leverage=leverage,
        order_endpoint_contract_hashes=order_endpoint_contract_hashes or {},
        algo_endpoint_contract_hashes=algo_endpoint_contract_hashes or {},
        order_capabilities=order_capabilities or {},
        conditional_algo_capabilities=conditional_algo_capabilities or {},
        query_retention_assumptions=query_retention_assumptions or {},
        websocket_assumptions=websocket_assumptions or {},
        rest_recovery_assumptions=rest_recovery_assumptions or {},
        changelog_last_reviewed_at=changelog_last_reviewed_at,
        changelog_source_hash=changelog_source_hash,
        compatibility=compatibility,
        blockers=tuple(blockers),
    )
