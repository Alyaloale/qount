"""Classifier and bypass router for the three-tier HALT model.

Phase A: classify_from_halt_reason reads the existing global HALT file's
reason string and maps it to a structured HaltEvent.  classify_from_runtime
state generates events from observed operational conditions.  Neither function
modifies the HALT file or changes risk disposition.
"""

from __future__ import annotations

from typing import Mapping

from qount.contracts.trace import canonical_hash
from qount.contracts.trace import is_sha256
from qount.halt.contracts import HALT_SCHEMA_VERSION
from qount.halt.contracts import HaltEvent


_REASON_CLASSIFICATION: dict[str, dict[str, str]] = {
    "live_execution_error": {
        "halt_type": "operational",
        "scope": "execution_plane",
        "severity": "HALT",
        "recommended_action": "freeze_risk",
        "recommended_scope": "execution_plane",
    },
    "post_dispatch_accounting_error": {
        "halt_type": "operational",
        "scope": "execution_plane",
        "severity": "HALT",
        "recommended_action": "freeze_risk",
        "recommended_scope": "execution_plane",
    },
    "pilot_risk_halt": {
        "halt_type": "operational",
        "scope": "execution_plane",
        "severity": "HALT",
        "recommended_action": "freeze_risk",
        "recommended_scope": "execution_plane",
    },
    "pilot_slippage_halt": {
        "halt_type": "operational",
        "scope": "execution_plane",
        "severity": "HALT",
        "recommended_action": "halt_after_protected_fill",
        "recommended_scope": "execution_plane",
    },
    "pilot_drawdown_halt": {
        "halt_type": "portfolio",
        "scope": "full_account",
        "severity": "HALT",
        "recommended_action": "flatten_then_halt",
        "recommended_scope": "full_account",
    },
    "pilot_drawdown_flatten_then_halt": {
        "halt_type": "portfolio",
        "scope": "full_account",
        "severity": "HALT",
        "recommended_action": "flatten_then_halt",
        "recommended_scope": "full_account",
    },
    "pilot_daily_loss_halt": {
        "halt_type": "portfolio",
        "scope": "full_account",
        "severity": "HALT",
        "recommended_action": "flatten_then_halt",
        "recommended_scope": "full_account",
    },
    "pilot_daily_loss_flatten_then_halt": {
        "halt_type": "portfolio",
        "scope": "full_account",
        "severity": "HALT",
        "recommended_action": "flatten_then_halt",
        "recommended_scope": "full_account",
    },
}

_DEFAULT_CLASSIFICATION = {
    "halt_type": "operational",
    "scope": "execution_plane",
    "severity": "HALT",
    "recommended_action": "freeze_risk",
    "recommended_scope": "execution_plane",
}


def _evidence_hash(reason: str, created_at: str) -> str:
    return canonical_hash(
        {
            "source": "halt_classifier",
            "reason": reason,
            "created_at": created_at,
        }
    )


def classify_from_halt_reason(
    reason: str,
    *,
    created_at: str,
    unknown_unresolved: bool = False,
) -> HaltEvent:
    """Classify an existing HALT file reason into a three-tier HaltEvent.

    This is a bypass observer: it does NOT modify the HALT file.
    Unknown reason strings fall back to operational / freeze_risk.
    """
    classification = _REASON_CLASSIFICATION.get(
        reason, _DEFAULT_CLASSIFICATION
    )
    return HaltEvent.create(
        halt_type=classification["halt_type"],
        scope=classification["scope"],
        reason=reason,
        severity=classification["severity"],
        evidence_hash=_evidence_hash(reason, created_at),
        recommended_action=classification["recommended_action"],
        recommended_scope=classification["recommended_scope"],
        created_at=created_at,
        source_halt_reason=reason,
        unknown_unresolved=unknown_unresolved,
        bypass_mode=True,
    )


def classify_from_runtime_state(
    *,
    unknown_order_count: int = 0,
    reconciliation_halt_required: bool = False,
    reconciliation_passed: bool | None = None,
    data_quality_blockers: int = 0,
    created_at: str,
) -> list[HaltEvent]:
    """Generate HaltEvents from observed runtime conditions.

    Each condition that warrants a halt produces a separate event.
    Returns an empty list when no conditions are met.
    """
    events: list[HaltEvent] = []
    if unknown_order_count > 0:
        reason = "unknown_orders_unresolved"
        events.append(
            HaltEvent.create(
                halt_type="operational",
                scope="execution_plane",
                reason=reason,
                severity="HALT",
                evidence_hash=_evidence_hash(reason, created_at),
                recommended_action="freeze_risk",
                recommended_scope="execution_plane",
                created_at=created_at,
                unknown_unresolved=True,
                bypass_mode=True,
            )
        )
    if reconciliation_halt_required:
        reason = "reconciliation_halt_required"
        events.append(
            HaltEvent.create(
                halt_type="operational",
                scope="execution_plane",
                reason=reason,
                severity="HALT",
                evidence_hash=_evidence_hash(reason, created_at),
                recommended_action="freeze_risk",
                recommended_scope="execution_plane",
                created_at=created_at,
                bypass_mode=True,
            )
        )
    if reconciliation_passed is False and not reconciliation_halt_required:
        reason = "reconciliation_failed"
        events.append(
            HaltEvent.create(
                halt_type="operational",
                scope="execution_plane",
                reason=reason,
                severity="CRITICAL",
                evidence_hash=_evidence_hash(reason, created_at),
                recommended_action="freeze_risk",
                recommended_scope="execution_plane",
                created_at=created_at,
                bypass_mode=True,
            )
        )
    if data_quality_blockers > 0:
        reason = "data_quality_blockers"
        events.append(
            HaltEvent.create(
                halt_type="operational",
                scope="execution_plane",
                reason=reason,
                severity="CRITICAL",
                evidence_hash=_evidence_hash(reason, created_at),
                recommended_action="freeze_risk",
                recommended_scope="execution_plane",
                created_at=created_at,
                bypass_mode=True,
            )
        )
    return events


def escalate_scope(events: list[HaltEvent]) -> str:
    """Return the widest scope recommended across all events.

    full_account > execution_plane > single_strategy_version > venue.
    Used to determine whether a local event should escalate to account level.
    """
    priority = {
        "venue": 0,
        "single_strategy_version": 1,
        "execution_plane": 2,
        "full_account": 3,
    }
    if not events:
        return "venue"
    return max(
        events, key=lambda e: priority.get(e.recommended_scope, 0)
    ).recommended_scope


def validate_recovery_flow(
    *,
    halt_active: bool,
    unknown_unresolved: bool,
    dual_accounting_diff_passed: bool,
    recovery_report_written: bool,
    owner_authorized: bool,
) -> tuple[str, ...]:
    """Validate that the recovery flow (section 5.3) is correctly ordered.

    Returns a tuple of error strings; empty means the recovery is valid.
    """
    errors: list[str] = []
    if not halt_active:
        errors.append("recovery_no_active_halt")
        return tuple(errors)
    if unknown_unresolved:
        errors.append("recovery_unknown_orders_not_closed")
    if not dual_accounting_diff_passed:
        errors.append("recovery_dual_accounting_diff_not_passed")
    if not recovery_report_written:
        errors.append("recovery_report_not_written")
    if not owner_authorized:
        errors.append("recovery_owner_authorization_missing")
    return tuple(errors)
