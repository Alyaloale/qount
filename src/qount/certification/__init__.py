"""Venue certification lane: independent execution certification contracts.

This package implements Workstream A of the trading-system-evolution-plan.
Phase A delivers schema/hash contracts only; orders_authorized is always
False and no real exchange mutation is possible.
"""

from qount.certification.attribution import ATTRIBUTION_SCHEMA_VERSION
from qount.certification.attribution import ATTRIBUTION_SCHEMA_VERSIONS
from qount.certification.attribution import ATTRIBUTION_SOURCES
from qount.certification.attribution import FIELD_AVAILABILITY
from qount.certification.attribution import UNAVAILABLE
from qount.certification.attribution import ExecutionAttributionReport
from qount.certification.attribution_recovery import build_recovered_attribution
from qount.certification.attribution_capture import build_event_time_attribution
from qount.certification.attribution_capture import capture_arrival_quote
from qount.certification.attribution_capture import exchange_evidence_envelope
from qount.certification.attribution_capture import sanitize_exchange_evidence
from qount.certification.contracts import CERTIFICATION_EVENT_SOURCES
from qount.certification.contracts import CERTIFICATION_EVENT_TYPES
from qount.certification.contracts import CERTIFICATION_SCHEMA_VERSION
from qount.certification.contracts import CERTIFICATION_STATUSES
from qount.certification.contracts import CERTIFICATION_TYPES
from qount.certification.contracts import OBSERVED_ORDER_STATES
from qount.certification.contracts import REQUIRED_RESULT_MEMBERS
from qount.certification.contracts import RUN_STATUSES
from qount.certification.contracts import VENUE_SEMANTICS
from qount.certification.contracts import CertificationEvent
from qount.certification.contracts import CertificationPlan
from qount.certification.contracts import CertificationResult
from qount.certification.contracts import CertificationRun
from qount.certification.runner import CertificationRunner
from qount.certification.runner import VenueAdapter

__all__ = [
    "ATTRIBUTION_SCHEMA_VERSION",
    "ATTRIBUTION_SCHEMA_VERSIONS",
    "ATTRIBUTION_SOURCES",
    "CERTIFICATION_EVENT_SOURCES",
    "CERTIFICATION_EVENT_TYPES",
    "CERTIFICATION_SCHEMA_VERSION",
    "CERTIFICATION_STATUSES",
    "CERTIFICATION_TYPES",
    "FIELD_AVAILABILITY",
    "OBSERVED_ORDER_STATES",
    "REQUIRED_RESULT_MEMBERS",
    "RUN_STATUSES",
    "UNAVAILABLE",
    "VENUE_SEMANTICS",
    "CertificationEvent",
    "CertificationArtifactIncompleteError",
    "CertificationArtifactStoreError",
    "CertificationPlan",
    "CertificationResult",
    "CertificationRun",
    "CertificationRunner",
    "ExecutionAttributionReport",
    "VerifiedCertificationBundle",
    "VenueAdapter",
    "build_recovered_attribution",
    "build_event_time_attribution",
    "capture_arrival_quote",
    "exchange_evidence_envelope",
    "publish_certification_bundle",
    "read_certification_bundle",
    "sanitize_exchange_evidence",
]


_ARTIFACT_STORE_EXPORTS = {
    "CertificationArtifactIncompleteError",
    "CertificationArtifactStoreError",
    "VerifiedCertificationBundle",
    "publish_certification_bundle",
    "read_certification_bundle",
}


def __getattr__(name: str) -> object:
    """Load the artifact store lazily to preserve persistence boundaries."""

    if name in _ARTIFACT_STORE_EXPORTS:
        from qount.certification import artifact_store

        return getattr(artifact_store, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
