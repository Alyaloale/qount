"""Bypass router for the three-tier HALT model.

Phase A: the router observes and classifies but does not change
the existing global HALT disposition.  It reads the HALT file reason
(if present) and runtime state, then emits structured HaltEvents
for observability without modifying any files or risk state.
"""

from __future__ import annotations

import os
from pathlib import Path

from qount.halt.classifier import classify_from_halt_reason
from qount.halt.classifier import classify_from_runtime_state
from qount.halt.classifier import escalate_scope
from qount.halt.classifier import validate_recovery_flow
from qount.halt.contracts import HaltEvent


def read_halt_reason(halt_path: str | os.PathLike[str] | None) -> str | None:
    """Read the reason from an existing global HALT file.

    Returns None if the file does not exist.  This is a read-only
    operation; the HALT file is never modified by the bypass router.
    """
    if halt_path is None:
        return None
    path = Path(halt_path)
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return content if content else None


def classify_halt(
    *,
    halt_path: str | os.PathLike[str] | None = None,
    created_at: str,
    unknown_order_count: int = 0,
    reconciliation_halt_required: bool = False,
    reconciliation_passed: bool | None = None,
    data_quality_blockers: int = 0,
) -> list[HaltEvent]:
    """Classify the current halt state into structured HaltEvents.

    This is the main bypass-observer entry point.  It:
    1. Reads the existing HALT file reason (if any) -- read-only.
    2. Classifies it into three-tier HaltEvent.
    3. Also classifies runtime conditions (UNKNOWN, reconciliation, etc.).
    4. Returns all events without changing disposition.

    The existing global HALT file remains the hard gate.
    """
    events: list[HaltEvent] = []
    reason = read_halt_reason(halt_path)
    if reason is not None:
        events.append(
            classify_from_halt_reason(
                reason,
                created_at=created_at,
                unknown_unresolved=unknown_order_count > 0,
            )
        )
    events.extend(
        classify_from_runtime_state(
            unknown_order_count=unknown_order_count,
            reconciliation_halt_required=reconciliation_halt_required,
            reconciliation_passed=reconciliation_passed,
            data_quality_blockers=data_quality_blockers,
            created_at=created_at,
        )
    )
    return events


def should_escalate_to_account_level(events: list[HaltEvent]) -> bool:
    """Check whether any event recommends full-account scope.

    In Phase A this is observational: it reports whether escalation
    is recommended, but does not perform the escalation.
    """
    if not events:
        return False
    return escalate_scope(events) == "full_account"


__all__ = [
    "classify_halt",
    "read_halt_reason",
    "should_escalate_to_account_level",
    "validate_recovery_flow",
]
