"""Stable identifiers and validation helpers for cross-domain trace objects."""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, Mapping

from qount.contracts.hashing import canonical_hash


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRACE_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def is_sha256(value: object) -> bool:
    return bool(_SHA256_RE.fullmatch(str(value)))


def aware_datetime(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime_must_be_timezone_aware")
    return parsed


def trace_id(kind: str, payload: Mapping[str, Any]) -> str:
    """Build a deterministic, secret-free ID from canonical inputs."""

    if not _TRACE_KIND_RE.fullmatch(kind):
        raise ValueError("trace_kind_invalid")
    return canonical_hash(
        {
            "trace_schema_version": 1,
            "kind": kind,
            "payload": payload,
        }
    )


def timestamp_errors(
    decision_time: str,
    data_cutoff: str,
    *,
    prefix: str,
) -> tuple[str, ...]:
    try:
        decision = aware_datetime(decision_time)
        cutoff = aware_datetime(data_cutoff)
    except (AttributeError, TypeError, ValueError):
        return (f"{prefix}_datetime_invalid",)
    if cutoff > decision:
        return (f"{prefix}_data_cutoff_after_decision_time",)
    return ()


def weight_errors(
    weights: Mapping[str, float],
    *,
    prefix: str,
    maximum_gross: float | None = 1.0,
) -> tuple[str, ...]:
    errors: list[str] = []
    gross = 0.0
    try:
        rows = weights.items()
    except AttributeError:
        return (f"{prefix}_weights_invalid",)
    for symbol, raw_weight in rows:
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            errors.append(f"{prefix}_weight_invalid:{symbol}")
            continue
        if not symbol or not math.isfinite(weight):
            errors.append(f"{prefix}_weight_invalid:{symbol}")
        elif weight < 0.0:
            errors.append(f"{prefix}_short_target_forbidden:{symbol}")
        else:
            gross += weight
    if maximum_gross is not None and gross > maximum_gross + 1e-12:
        errors.append(f"{prefix}_gross_exceeds_limit")
    return tuple(errors)
