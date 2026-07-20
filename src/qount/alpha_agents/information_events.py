"""Point-in-time information event contracts for LLM-assisted research."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from qount.alpha_agents.llm import find_forbidden_output


INFORMATION_EVENT_VERSION = "alpha_information_event_v0.1"
DEFAULT_ALLOWED_SOURCE_DOMAINS = (
    "binance.com",
    "bybit.com",
    "sec.gov",
    "federalreserve.gov",
    "investor.gov",
    "github.com",
)
ALLOWED_EVENT_TYPES = (
    "company_action",
    "earnings",
    "exchange_maintenance",
    "governance",
    "listing",
    "macro_release",
    "protocol_release",
    "regulatory_filing",
    "risk_parameter_change",
    "security_incident",
)
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class InformationEvent:
    event_id: str
    source_url: str
    published_at: str
    observed_at: str
    available_at: str
    entities: tuple[str, ...]
    event_type: str
    numeric_fields: Mapping[str, float] = field(default_factory=dict)
    source_excerpt: str = ""
    llm_summary: str = ""
    llm_confidence: float = 0.0
    source_hash: str = ""
    extractor_version: str = ""
    schema_version: str = INFORMATION_EVENT_VERSION

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["entities"] = list(self.entities)
        result["numeric_fields"] = dict(self.numeric_fields)
        return result


def _timestamp(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(dt.UTC)


def _domain_allowed(domain: str, allowed: Sequence[str]) -> bool:
    host = domain.lower().rstrip(".")
    return any(host == item or host.endswith(f".{item}") for item in allowed)


def information_event_id(
    *, source_hash: str, published_at: str, event_type: str, entities: Sequence[str]
) -> str:
    payload = {
        "source_hash": source_hash,
        "published_at": published_at,
        "event_type": event_type,
        "entities": sorted(set(str(entity).upper() for entity in entities)),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_information_event(
    *,
    source_url: str,
    source_bytes: bytes,
    published_at: str,
    observed_at: str,
    available_at: str,
    entities: Sequence[str],
    event_type: str,
    numeric_fields: Mapping[str, float] | None = None,
    source_excerpt: str,
    llm_summary: str,
    llm_confidence: float,
    extractor_version: str,
) -> InformationEvent:
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    normalized_entities = tuple(sorted(set(str(entity).upper() for entity in entities)))
    return InformationEvent(
        event_id=information_event_id(
            source_hash=source_hash,
            published_at=published_at,
            event_type=event_type,
            entities=normalized_entities,
        ),
        source_url=source_url,
        published_at=published_at,
        observed_at=observed_at,
        available_at=available_at,
        entities=normalized_entities,
        event_type=event_type,
        numeric_fields=dict(numeric_fields or {}),
        source_excerpt=source_excerpt,
        llm_summary=llm_summary,
        llm_confidence=llm_confidence,
        source_hash=source_hash,
        extractor_version=extractor_version,
    )


def validate_information_event(
    event: InformationEvent,
    *,
    allowed_source_domains: Sequence[str] = DEFAULT_ALLOWED_SOURCE_DOMAINS,
) -> list[str]:
    errors = []
    parsed_url = urllib.parse.urlparse(event.source_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        errors.append("source_url_not_https")
    elif not _domain_allowed(parsed_url.hostname, allowed_source_domains):
        errors.append("source_domain_not_allowed")

    published = _timestamp(event.published_at)
    available = _timestamp(event.available_at)
    observed = _timestamp(event.observed_at)
    if published is None:
        errors.append("published_at_invalid_or_naive")
    if available is None:
        errors.append("available_at_invalid_or_naive")
    if observed is None:
        errors.append("observed_at_invalid_or_naive")
    if published is not None and available is not None and available < published:
        errors.append("available_before_published")
    if available is not None and observed is not None and observed < available:
        errors.append("observed_before_available")

    if event.schema_version != INFORMATION_EVENT_VERSION:
        errors.append("schema_version_mismatch")
    if event.event_type not in ALLOWED_EVENT_TYPES:
        errors.append("event_type_not_allowed")
    if not event.entities:
        errors.append("entities_empty")
    elif any(entity != entity.upper() or not entity.strip() for entity in event.entities):
        errors.append("entities_not_normalized")
    if len(event.entities) != len(set(event.entities)):
        errors.append("entities_not_unique")
    if not _HASH_PATTERN.fullmatch(event.source_hash):
        errors.append("source_hash_invalid")
    expected_id = information_event_id(
        source_hash=event.source_hash,
        published_at=event.published_at,
        event_type=event.event_type,
        entities=event.entities,
    )
    if event.event_id != expected_id:
        errors.append("event_id_mismatch")
    if not event.extractor_version.strip():
        errors.append("extractor_version_empty")
    if not event.source_excerpt.strip():
        errors.append("source_excerpt_empty")
    if not 0.0 <= float(event.llm_confidence) <= 1.0:
        errors.append("llm_confidence_out_of_range")
    for name, value in event.numeric_fields.items():
        if not name or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            errors.append(f"numeric_field_invalid:{name}")
    for hit in find_forbidden_output(event.llm_summary):
        errors.append(f"forbidden_llm_output:{hit}")
    return errors


def information_event_feature_row(event: InformationEvent) -> dict[str, Any]:
    errors = validate_information_event(event)
    if errors:
        raise ValueError(f"invalid information event: {','.join(errors)}")
    return {
        "event_id": event.event_id,
        "available_at": event.available_at,
        "entities": list(event.entities),
        "event_type": event.event_type,
        "event_type_flags": {
            name: float(name == event.event_type) for name in ALLOWED_EVENT_TYPES
        },
        "numeric_fields": {
            name: float(value) for name, value in sorted(event.numeric_fields.items())
        },
        "source_hash": event.source_hash,
        "extractor_version": event.extractor_version,
        "llm_text_used_as_numeric_feature": False,
    }


def audit_information_events(events: Sequence[InformationEvent]) -> dict[str, Any]:
    validation = [
        {"event_id": event.event_id, "errors": validate_information_event(event)}
        for event in events
    ]
    event_ids = [event.event_id for event in events]
    source_hashes = [event.source_hash for event in events]
    duplicate_event_ids = sorted(
        {value for value in event_ids if event_ids.count(value) > 1}
    )
    duplicate_source_hashes = sorted(
        {value for value in source_hashes if source_hashes.count(value) > 1}
    )
    return {
        "schema_version": INFORMATION_EVENT_VERSION,
        "event_count": len(events),
        "valid_event_count": sum(not row["errors"] for row in validation),
        "invalid_event_count": sum(bool(row["errors"]) for row in validation),
        "duplicate_event_ids": duplicate_event_ids,
        "duplicate_source_hashes": duplicate_source_hashes,
        "validation": validation,
        "research_feature_rows_allowed": (
            bool(events)
            and all(not row["errors"] for row in validation)
            and not duplicate_event_ids
            and not duplicate_source_hashes
        ),
        "orders_allowed": False,
        "paper_or_live_allowed": False,
    }
