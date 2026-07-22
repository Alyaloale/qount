"""Three-tier HALT model: contracts, classifier, and bypass router.

Implements Workstream C of the trading-system-evolution-plan.
Phase A: bypass observer only; the global HALT file remains the hard gate.
"""

from qount.halt.classifier import classify_from_halt_reason
from qount.halt.classifier import classify_from_runtime_state
from qount.halt.classifier import escalate_scope
from qount.halt.classifier import validate_recovery_flow
from qount.halt.contracts import HALT_ACTIONS
from qount.halt.contracts import HALT_SCHEMA_VERSION
from qount.halt.contracts import HALT_SCOPES
from qount.halt.contracts import HALT_SEVERITIES
from qount.halt.contracts import HALT_TYPES
from qount.halt.contracts import HaltEvent
from qount.halt.contracts import RECOVERY_STATES
from qount.halt.observer import archive_halt_observations
from qount.halt.observer import observe_halt_state
from qount.halt.router import classify_halt
from qount.halt.router import read_halt_reason
from qount.halt.router import should_escalate_to_account_level

__all__ = [
    "HALT_ACTIONS",
    "HALT_SCHEMA_VERSION",
    "HALT_SCOPES",
    "HALT_SEVERITIES",
    "HALT_TYPES",
    "HaltEvent",
    "RECOVERY_STATES",
    "archive_halt_observations",
    "classify_from_halt_reason",
    "classify_from_runtime_state",
    "classify_halt",
    "escalate_scope",
    "observe_halt_state",
    "read_halt_reason",
    "should_escalate_to_account_level",
    "validate_recovery_flow",
]
