"""HALT bypass observer orchestration layer.

Runs after each live cycle to classify the current halt state into
structured HaltEvents for observability.  In Phase B, this is purely
bypass: it does NOT modify the global HALT file or change risk
disposition (section 5.2).

The caller provides runtime state (unknown_order_count, reconciliation
status) from an independent source (e.g. primary_snapshot.extract_runtime_state).
This module does NOT import qount.ledger or qount.execution.

Import boundary: this module must NOT import qount.execution,
qount.executor, qount.settings, or ccxt.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.halt.contracts import HaltEvent
from qount.halt.router import classify_halt


_FILENAME_RE = re.compile(r"^\d{8}T\d{6}Z$")


def observe_halt_state(
    *,
    halt_path: str | os.PathLike[str] | None = None,
    unknown_order_count: int = 0,
    reconciliation_halt_required: bool = False,
    reconciliation_passed: bool | None = None,
    data_quality_blockers: int = 0,
    observed_at: str | None = None,
    archive_dir: str | os.PathLike[str] | None = None,
) -> list[HaltEvent]:
    """Observe and classify the current halt state.

    Reads the HALT file (read-only) and accepts runtime state from
    the caller, then classifies into HaltEvents.  Does NOT modify
    the HALT file or change risk disposition (bypass mode).

    If *archive_dir* is provided, archives the observations as a
    timestamped JSON file.
    """
    if observed_at is None:
        observed_at = dt.datetime.now(dt.timezone.utc).isoformat()

    events = classify_halt(
        halt_path=halt_path,
        created_at=observed_at,
        unknown_order_count=unknown_order_count,
        reconciliation_halt_required=reconciliation_halt_required,
        reconciliation_passed=reconciliation_passed,
        data_quality_blockers=data_quality_blockers,
    )

    if archive_dir is not None and events:
        archive_halt_observations(
            events,
            archive_dir=archive_dir,
            observed_at=observed_at,
        )

    return events


def archive_halt_observations(
    events: Sequence[HaltEvent],
    *,
    archive_dir: str | os.PathLike[str],
    observed_at: str,
) -> str:
    """Archive HaltEvents as a timestamped JSON file.

    Returns the SHA-256 of the written file.
    """
    dir_path = Path(archive_dir)
    dir_path.mkdir(parents=True, exist_ok=True)

    timestamp = dt.datetime.fromisoformat(observed_at)
    filename = timestamp.strftime("%Y%m%dT%H%M%SZ")
    file_path = dir_path / f"{filename}.json"

    payload: dict[str, Any] = {
        "observed_at": observed_at,
        "bypass_mode": True,
        "event_count": len(events),
        "events": [_halt_event_to_dict(e) for e in events],
    }

    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    )
    with open(file_path, "w", encoding="ascii") as f:
        f.write(canonical)

    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _halt_event_to_dict(event: HaltEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "halt_type": event.halt_type,
        "scope": event.scope,
        "reason": event.reason,
        "severity": event.severity,
        "evidence_hash": event.evidence_hash,
        "recommended_action": event.recommended_action,
        "recommended_scope": event.recommended_scope,
        "bypass_mode": event.bypass_mode,
        "source_halt_reason": event.source_halt_reason,
        "unknown_unresolved": event.unknown_unresolved,
        "risk_increase_frozen": event.risk_increase_frozen,
        "recovery_requires_owner_auth": event.recovery_requires_owner_auth,
        "recovery_requires_dual_diff": event.recovery_requires_dual_diff,
        "created_at": event.created_at,
        "event_hash": event.event_hash,
    }
