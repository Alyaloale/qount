"""Pure validation helpers shared by Dashboard read-model builders.

This module deliberately owns only deterministic schema, numeric, and
freshness checks.  It neither reads files nor imports the reporting builders,
so the rules can be tested independently from static publication.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Mapping

from qount.contracts.trace import aware_datetime


class DashboardReadModelError(ValueError):
    """Raised when a read model source, payload, or publication is invalid."""


def mapping(value: object, *, name: str) -> Mapping[str, Any]:
    """Return a mapping or raise the dashboard's stable schema error."""
    if not isinstance(value, Mapping):
        raise DashboardReadModelError(f"{name}_must_be_object")
    return value


def exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    name: str,
) -> None:
    """Require a mapping to have precisely the documented field set."""
    actual = set(value)
    if actual != expected:
        missing = ",".join(sorted(expected - actual)) or "none"
        unexpected = ",".join(sorted(actual - expected)) or "none"
        raise DashboardReadModelError(
            f"{name}_fields_mismatch:missing={missing}:unexpected={unexpected}"
        )


def finite_nonnegative(value: object, *, name: str) -> float:
    """Coerce a finite, non-negative number while preserving error wording."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DashboardReadModelError(f"{name}_invalid") from exc
    if not math.isfinite(number) or number < 0.0:
        raise DashboardReadModelError(f"{name}_invalid")
    return number


def finite(value: object, *, name: str) -> float:
    """Coerce a finite signed number while preserving error wording."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DashboardReadModelError(f"{name}_invalid") from exc
    if not math.isfinite(number):
        raise DashboardReadModelError(f"{name}_invalid")
    return number


def gross(weights: Mapping[str, float]) -> float:
    """Calculate rounded gross exposure after validating each weight."""
    return round(
        sum(
            finite_nonnegative(value, name=f"weight:{symbol}")
            for symbol, value in weights.items()
        ),
        12,
    )


def iso_after(value: str, seconds: int) -> str:
    """Return an ISO timestamp offset from an ISO-aware input timestamp."""
    return (aware_datetime(value) + timedelta(seconds=seconds)).isoformat()


def freshness(
    *,
    source_updated_at: str,
    evaluated_at: str,
    stale_after_seconds: int,
    observed_at: str | None = None,
    content_updated_at: str | None = None,
    sources: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Build deterministic per-source and aggregate freshness metadata."""
    observed_at = observed_at or source_updated_at
    content_updated_at = content_updated_at or source_updated_at
    source_times = dict(sources or {"primary": source_updated_at})
    source_states = {
        name: {
            "updated_at": updated_at,
            "stale_at": iso_after(updated_at, stale_after_seconds),
            "status": (
                "stale"
                if aware_datetime(evaluated_at)
                >= aware_datetime(iso_after(updated_at, stale_after_seconds))
                else "fresh"
            ),
        }
        for name, updated_at in sorted(source_times.items())
    }
    stale_at = min(str(value["stale_at"]) for value in source_states.values())
    status = (
        "stale"
        if any(value["status"] == "stale" for value in source_states.values())
        else "fresh"
    )
    return {
        "status": status,
        "source_updated_at": source_updated_at,
        "observed_at": observed_at,
        "content_updated_at": content_updated_at,
        "evaluated_at": evaluated_at,
        "stale_at": stale_at,
        "sources": source_states,
    }


def count(value: object, *, name: str) -> int:
    """Validate a non-boolean, non-negative integer count."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DashboardReadModelError(f"{name}_invalid")
    return value


def string_list(value: object, *, name: str) -> list[str]:
    """Validate a non-empty, duplicate-free string list."""
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(value) != len(set(value))
    ):
        raise DashboardReadModelError(f"{name}_invalid")
    return value


def trace_href(identifier: str) -> str:
    """Return the dashboard route for a traceable decision identifier."""
    return f"#/decisions?trace={identifier}"
