"""HaltEvent contract for the three-tier HALT model.

Implements Workstream C of the trading-system-evolution-plan sections 5.1-5.3.

Phase A: HaltEvent is a bypass observer.  It classifies the current
single-global-HALT reason into Operational / Strategy / Portfolio tiers
and emits structured recommendations, but does NOT change the existing
disposition.  The global state/mini_trend/HALT file remains the hard gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.contracts.trace import trace_id


HALT_SCHEMA_VERSION = 1

HALT_TYPES = ("operational", "strategy", "portfolio")

HALT_SCOPES = (
    "venue",
    "execution_plane",
    "single_strategy_version",
    "full_account",
)

HALT_SEVERITIES = ("WARNING", "CRITICAL", "HALT")

HALT_ACTIONS = (
    "freeze_risk",
    "flatten_then_halt",
    "halt_after_protected_fill",
    "block_sleeve",
    "block_account",
)

RECOVERY_STATES = (
    "halt_detected",
    "risk_frozen",
    "evidence_gaps_closing",
    "dual_accounting_diff_pending",
    "recovery_report_written",
    "owner_authorization_pending",
    "resumed",
)

_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


@dataclass(frozen=True)
class HaltEvent:
    """One classified halt event with tier, scope, and recovery requirements.

    In Phase A (bypass_mode=True) this event is observational only:
    it does not modify the global HALT file or change risk disposition.
    The three invariants (section 5.2) are encoded as flags:

    * unknown_unresolved -- UNKNOWN orders not yet closed -> no replacement orders
    * risk_increase_frozen -- no new risk may be added
    * recovery_requires_owner_auth -- resume needs explicit owner authorization
    * recovery_requires_dual_diff -- resume needs primary + shadow diff pass
    """

    schema_version: int
    event_id: str
    halt_type: str
    scope: str
    reason: str
    severity: str
    evidence_hash: str
    recommended_action: str
    recommended_scope: str
    bypass_mode: bool
    source_halt_reason: str | None
    unknown_unresolved: bool
    risk_increase_frozen: bool
    recovery_requires_owner_auth: bool
    recovery_requires_dual_diff: bool
    created_at: str
    event_hash: str

    @classmethod
    def create(
        cls,
        *,
        halt_type: str,
        scope: str,
        reason: str,
        severity: str,
        evidence_hash: str,
        recommended_action: str,
        recommended_scope: str,
        created_at: str,
        source_halt_reason: str | None = None,
        unknown_unresolved: bool = False,
        bypass_mode: bool = True,
    ) -> HaltEvent:
        risk_increase_frozen = True
        recovery_requires_owner_auth = True
        recovery_requires_dual_diff = True
        core = {
            "schema_version": HALT_SCHEMA_VERSION,
            "halt_type": halt_type,
            "scope": scope,
            "reason": reason,
            "severity": severity,
            "evidence_hash": evidence_hash,
            "recommended_action": recommended_action,
            "recommended_scope": recommended_scope,
            "bypass_mode": bypass_mode,
            "source_halt_reason": source_halt_reason,
            "unknown_unresolved": unknown_unresolved,
            "risk_increase_frozen": risk_increase_frozen,
            "recovery_requires_owner_auth": recovery_requires_owner_auth,
            "recovery_requires_dual_diff": recovery_requires_dual_diff,
            "created_at": created_at,
        }
        event_hash = canonical_hash(core)
        event = cls(
            schema_version=HALT_SCHEMA_VERSION,
            event_id=trace_id("halt_event", {"event_hash": event_hash}),
            halt_type=halt_type,
            scope=scope,
            reason=reason,
            severity=severity,
            evidence_hash=evidence_hash,
            recommended_action=recommended_action,
            recommended_scope=recommended_scope,
            bypass_mode=bypass_mode,
            source_halt_reason=source_halt_reason,
            unknown_unresolved=unknown_unresolved,
            risk_increase_frozen=risk_increase_frozen,
            recovery_requires_owner_auth=recovery_requires_owner_auth,
            recovery_requires_dual_diff=recovery_requires_dual_diff,
            created_at=created_at,
            event_hash=event_hash,
        )
        errors = event.validate()
        if errors:
            raise ValueError(f"halt_event_invalid:{','.join(errors)}")
        return event

    def _core(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "halt_type": self.halt_type,
            "scope": self.scope,
            "reason": self.reason,
            "severity": self.severity,
            "evidence_hash": self.evidence_hash,
            "recommended_action": self.recommended_action,
            "recommended_scope": self.recommended_scope,
            "bypass_mode": self.bypass_mode,
            "source_halt_reason": self.source_halt_reason,
            "unknown_unresolved": self.unknown_unresolved,
            "risk_increase_frozen": self.risk_increase_frozen,
            "recovery_requires_owner_auth": self.recovery_requires_owner_auth,
            "recovery_requires_dual_diff": self.recovery_requires_dual_diff,
            "created_at": self.created_at,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != HALT_SCHEMA_VERSION:
            errors.append("halt_event_schema_version_invalid")
        if self.halt_type not in HALT_TYPES:
            errors.append("halt_event_type_invalid")
        if self.scope not in HALT_SCOPES:
            errors.append("halt_event_scope_invalid")
        if not _REASON_RE.fullmatch(self.reason):
            errors.append("halt_event_reason_invalid")
        if self.severity not in HALT_SEVERITIES:
            errors.append("halt_event_severity_invalid")
        if not is_sha256(self.evidence_hash):
            errors.append("halt_event_evidence_hash_invalid")
        if self.recommended_action not in HALT_ACTIONS:
            errors.append("halt_event_recommended_action_invalid")
        if self.recommended_scope not in HALT_SCOPES:
            errors.append("halt_event_recommended_scope_invalid")
        if not isinstance(self.bypass_mode, bool):
            errors.append("halt_event_bypass_mode_invalid")
        if self.source_halt_reason is not None and not _REASON_RE.fullmatch(
            self.source_halt_reason
        ):
            errors.append("halt_event_source_halt_reason_invalid")
        if not isinstance(self.unknown_unresolved, bool):
            errors.append("halt_event_unknown_unresolved_invalid")
        if not isinstance(self.risk_increase_frozen, bool):
            errors.append("halt_event_risk_increase_frozen_invalid")
        if not isinstance(self.recovery_requires_owner_auth, bool):
            errors.append("halt_event_recovery_requires_owner_auth_invalid")
        if not isinstance(self.recovery_requires_dual_diff, bool):
            errors.append("halt_event_recovery_requires_dual_diff_invalid")
        try:
            aware_datetime(self.created_at)
        except (AttributeError, TypeError, ValueError):
            errors.append("halt_event_created_at_invalid")
        if self.risk_increase_frozen is not True:
            errors.append("halt_event_risk_increase_must_be_frozen")
        if self.recovery_requires_owner_auth is not True:
            errors.append("halt_event_recovery_must_require_owner_auth")
        if self.recovery_requires_dual_diff is not True:
            errors.append("halt_event_recovery_must_require_dual_diff")
        expected_hash = canonical_hash(self._core())
        if self.event_hash != expected_hash:
            errors.append("halt_event_hash_invalid")
        expected_id = trace_id(
            "halt_event", {"event_hash": expected_hash}
        )
        if self.event_id != expected_id:
            errors.append("halt_event_id_invalid")
        return tuple(errors)
