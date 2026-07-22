"""Venue capability snapshot and changelog diff contracts.

Implements Workstream D of the trading-system-evolution-plan section 6.
The snapshot captures exchange_info schema hash, symbol rules hash,
position/margin mode, leverage, endpoint contract hashes, and
changelog provenance.  Compatibility is pass / review_required / blocked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.contracts.trace import trace_id


VENUE_SCHEMA_VERSION = 1

COMPATIBILITY_LEVELS = ("pass", "review_required", "blocked")

_VENUE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(frozen=True)
class VenueCapabilitySnapshot:
    """A frozen snapshot of one venue's runtime capabilities.

    Git/source provenance is separate; this captures the dynamic
    exchange_info, symbol rules, position/margin mode, leverage,
    endpoint contracts, and changelog state at a point in time.
    """

    schema_version: int
    snapshot_id: str
    venue: str
    observed_at: str
    server_time_offset_ms: int
    exchange_info_schema_hash: str
    symbol_rules_hash: str
    position_mode: str
    margin_mode: str
    leverage: int
    order_endpoint_contract_hashes: Mapping[str, str]
    algo_endpoint_contract_hashes: Mapping[str, str]
    order_capabilities: Mapping[str, Any]
    conditional_algo_capabilities: Mapping[str, Any]
    query_retention_assumptions: Mapping[str, Any]
    websocket_assumptions: Mapping[str, Any]
    rest_recovery_assumptions: Mapping[str, Any]
    changelog_last_reviewed_at: str
    changelog_source_hash: str
    compatibility: str
    blockers: tuple[str, ...]
    snapshot_hash: str

    @classmethod
    def create(
        cls,
        *,
        venue: str,
        observed_at: str,
        server_time_offset_ms: int,
        exchange_info_schema_hash: str,
        symbol_rules_hash: str,
        position_mode: str,
        margin_mode: str,
        leverage: int,
        order_endpoint_contract_hashes: Mapping[str, str],
        algo_endpoint_contract_hashes: Mapping[str, str],
        order_capabilities: Mapping[str, Any],
        conditional_algo_capabilities: Mapping[str, Any],
        query_retention_assumptions: Mapping[str, Any],
        websocket_assumptions: Mapping[str, Any],
        rest_recovery_assumptions: Mapping[str, Any],
        changelog_last_reviewed_at: str,
        changelog_source_hash: str,
        compatibility: str,
        blockers: tuple[str, ...] = (),
    ) -> VenueCapabilitySnapshot:
        core = {
            "schema_version": VENUE_SCHEMA_VERSION,
            "venue": venue,
            "observed_at": observed_at,
            "server_time_offset_ms": int(server_time_offset_ms),
            "exchange_info_schema_hash": exchange_info_schema_hash,
            "symbol_rules_hash": symbol_rules_hash,
            "position_mode": position_mode,
            "margin_mode": margin_mode,
            "leverage": int(leverage),
            "order_endpoint_contract_hashes": dict(
                order_endpoint_contract_hashes
            ),
            "algo_endpoint_contract_hashes": dict(
                algo_endpoint_contract_hashes
            ),
            "order_capabilities": dict(order_capabilities),
            "conditional_algo_capabilities": dict(
                conditional_algo_capabilities
            ),
            "query_retention_assumptions": dict(
                query_retention_assumptions
            ),
            "websocket_assumptions": dict(websocket_assumptions),
            "rest_recovery_assumptions": dict(rest_recovery_assumptions),
            "changelog_last_reviewed_at": changelog_last_reviewed_at,
            "changelog_source_hash": changelog_source_hash,
            "compatibility": compatibility,
            "blockers": list(blockers),
        }
        snapshot_hash = canonical_hash(core)
        snapshot = cls(
            schema_version=VENUE_SCHEMA_VERSION,
            snapshot_id=trace_id(
                "venue_capability_snapshot",
                {"snapshot_hash": snapshot_hash},
            ),
            venue=venue,
            observed_at=observed_at,
            server_time_offset_ms=int(server_time_offset_ms),
            exchange_info_schema_hash=exchange_info_schema_hash,
            symbol_rules_hash=symbol_rules_hash,
            position_mode=position_mode,
            margin_mode=margin_mode,
            leverage=int(leverage),
            order_endpoint_contract_hashes=dict(
                order_endpoint_contract_hashes
            ),
            algo_endpoint_contract_hashes=dict(
                algo_endpoint_contract_hashes
            ),
            order_capabilities=dict(order_capabilities),
            conditional_algo_capabilities=dict(
                conditional_algo_capabilities
            ),
            query_retention_assumptions=dict(query_retention_assumptions),
            websocket_assumptions=dict(websocket_assumptions),
            rest_recovery_assumptions=dict(rest_recovery_assumptions),
            changelog_last_reviewed_at=changelog_last_reviewed_at,
            changelog_source_hash=changelog_source_hash,
            compatibility=compatibility,
            blockers=tuple(blockers),
            snapshot_hash=snapshot_hash,
        )
        errors = snapshot.validate()
        if errors:
            raise ValueError(
                f"venue_capability_snapshot_invalid:{','.join(errors)}"
            )
        return snapshot

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "venue": self.venue,
            "observed_at": self.observed_at,
            "server_time_offset_ms": self.server_time_offset_ms,
            "exchange_info_schema_hash": self.exchange_info_schema_hash,
            "symbol_rules_hash": self.symbol_rules_hash,
            "position_mode": self.position_mode,
            "margin_mode": self.margin_mode,
            "leverage": self.leverage,
            "order_endpoint_contract_hashes": dict(
                self.order_endpoint_contract_hashes
            ),
            "algo_endpoint_contract_hashes": dict(
                self.algo_endpoint_contract_hashes
            ),
            "order_capabilities": dict(self.order_capabilities),
            "conditional_algo_capabilities": dict(
                self.conditional_algo_capabilities
            ),
            "query_retention_assumptions": dict(
                self.query_retention_assumptions
            ),
            "websocket_assumptions": dict(self.websocket_assumptions),
            "rest_recovery_assumptions": dict(
                self.rest_recovery_assumptions
            ),
            "changelog_last_reviewed_at": self.changelog_last_reviewed_at,
            "changelog_source_hash": self.changelog_source_hash,
            "compatibility": self.compatibility,
            "blockers": list(self.blockers),
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != VENUE_SCHEMA_VERSION:
            errors.append("venue_snapshot_schema_version_invalid")
        if not _VENUE_RE.fullmatch(self.venue):
            errors.append("venue_snapshot_venue_invalid")
        try:
            aware_datetime(self.observed_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("venue_snapshot_observed_at_invalid")
        if not isinstance(self.server_time_offset_ms, int):
            errors.append("venue_snapshot_server_time_offset_invalid")
        for name in (
            "exchange_info_schema_hash",
            "symbol_rules_hash",
            "changelog_source_hash",
        ):
            if not is_sha256(getattr(self, name)):
                errors.append(f"venue_snapshot_{name}_invalid")
        if not self.position_mode:
            errors.append("venue_snapshot_position_mode_empty")
        if not self.margin_mode:
            errors.append("venue_snapshot_margin_mode_empty")
        if not isinstance(self.leverage, int) or self.leverage < 1:
            errors.append("venue_snapshot_leverage_invalid")
        try:
            aware_datetime(self.changelog_last_reviewed_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("venue_snapshot_changelog_last_reviewed_at_invalid")
        if self.compatibility not in COMPATIBILITY_LEVELS:
            errors.append("venue_snapshot_compatibility_invalid")
        if self.compatibility == "blocked" and not self.blockers:
            errors.append("venue_snapshot_blocked_without_blockers")
        if self.compatibility == "pass" and self.blockers:
            errors.append("venue_snapshot_pass_with_blockers")
        expected_hash = canonical_hash(self._core())
        if self.snapshot_hash != expected_hash:
            errors.append("venue_snapshot_hash_invalid")
        expected_id = trace_id(
            "venue_capability_snapshot",
            {"snapshot_hash": expected_hash},
        )
        if self.snapshot_id != expected_id:
            errors.append("venue_snapshot_id_invalid")
        return tuple(errors)


@dataclass(frozen=True)
class ChangelogDiff:
    """A diff between two changelog observations.

    text_changed=True means the changelog body hash differs, which
    triggers review_required.  The diff itself is an immutable artifact.
    """

    schema_version: int
    diff_id: str
    venue: str
    previous_source_hash: str
    current_source_hash: str
    previous_observed_at: str
    current_observed_at: str
    text_changed: bool
    review_required: bool
    diff_hash: str

    @classmethod
    def create(
        cls,
        *,
        venue: str,
        previous_source_hash: str,
        current_source_hash: str,
        previous_observed_at: str,
        current_observed_at: str,
    ) -> ChangelogDiff:
        text_changed = previous_source_hash != current_source_hash
        review_required = text_changed
        core = {
            "schema_version": VENUE_SCHEMA_VERSION,
            "venue": venue,
            "previous_source_hash": previous_source_hash,
            "current_source_hash": current_source_hash,
            "previous_observed_at": previous_observed_at,
            "current_observed_at": current_observed_at,
            "text_changed": text_changed,
            "review_required": review_required,
        }
        diff_hash = canonical_hash(core)
        diff = cls(
            schema_version=VENUE_SCHEMA_VERSION,
            diff_id=trace_id(
                "venue_changelog_diff", {"diff_hash": diff_hash}
            ),
            venue=venue,
            previous_source_hash=previous_source_hash,
            current_source_hash=current_source_hash,
            previous_observed_at=previous_observed_at,
            current_observed_at=current_observed_at,
            text_changed=text_changed,
            review_required=review_required,
            diff_hash=diff_hash,
        )
        errors = diff.validate()
        if errors:
            raise ValueError(
                f"venue_changelog_diff_invalid:{','.join(errors)}"
            )
        return diff

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "venue": self.venue,
            "previous_source_hash": self.previous_source_hash,
            "current_source_hash": self.current_source_hash,
            "previous_observed_at": self.previous_observed_at,
            "current_observed_at": self.current_observed_at,
            "text_changed": self.text_changed,
            "review_required": self.review_required,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != VENUE_SCHEMA_VERSION:
            errors.append("changelog_diff_schema_version_invalid")
        if not _VENUE_RE.fullmatch(self.venue):
            errors.append("changelog_diff_venue_invalid")
        for name in (
            "previous_source_hash",
            "current_source_hash",
        ):
            if not is_sha256(getattr(self, name)):
                errors.append(f"changelog_diff_{name}_invalid")
        for name in (
            "previous_observed_at",
            "current_observed_at",
        ):
            try:
                aware_datetime(getattr(self, name))
            except (AttributeError, TypeError, ValueError):
                errors.append(f"changelog_diff_{name}_invalid")
        if not isinstance(self.text_changed, bool):
            errors.append("changelog_diff_text_changed_invalid")
        if not isinstance(self.review_required, bool):
            errors.append("changelog_diff_review_required_invalid")
        if self.text_changed and not self.review_required:
            errors.append("changelog_diff_text_changed_without_review")
        expected_hash = canonical_hash(self._core())
        if self.diff_hash != expected_hash:
            errors.append("changelog_diff_hash_invalid")
        expected_id = trace_id(
            "venue_changelog_diff", {"diff_hash": expected_hash}
        )
        if self.diff_id != expected_id:
            errors.append("changelog_diff_id_invalid")
        return tuple(errors)
