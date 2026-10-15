"""Utility functions for adapters."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

from qount.api.schemas import LineSafety, LineSource, PaperLine


def compute_sha256(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def format_date_str(val: str) -> str:
    """Normalize date strings like '20261009' to '2026-10-09'."""
    val = str(val).strip()
    if len(val) == 8 and val.isdigit():
        return f"{val[:4]}-{val[4:6]}-{val[6:]}"
    if "T" in val:
        return val.split("T")[0]
    return val


def _stale_after_calendar_days() -> int:
    config_path = os.environ.get("QOUNT_API_CONFIG", "config/api.json")
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            value = json.load(handle)["freshness"]["stale_after_calendar_days"]
        days = int(value)
        return days if days >= 0 else 4
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 4


def compute_freshness(
    as_of: Optional[str],
    reference_date: Optional[str] = None,
    stale_after_days: Optional[int] = None,
) -> str:
    """Compute FRESH | STALE | MISSING from current UTC date and configured age limit."""
    if not as_of:
        return "MISSING"
    norm_as_of = format_date_str(as_of)
    try:
        dt_as_of = datetime.strptime(norm_as_of, "%Y-%m-%d").date()
        ref_dt = (
            datetime.strptime(reference_date, "%Y-%m-%d").date()
            if reference_date
            else datetime.now(timezone.utc).date()
        )
        days_diff = (ref_dt - dt_as_of).days
        max_age = _stale_after_calendar_days() if stale_after_days is None else stale_after_days
        if 0 <= days_diff <= max_age:
            return "FRESH"
        return "STALE"
    except Exception:
        return "STALE"


def unavailable_line(
    line_id: str,
    name: str,
    category: str,
    source_path: str,
    error: str,
    adjudication: str = "",
    lifecycle_status: str = "ACTIVE_PAPER",
) -> PaperLine:
    """Create a missing-source row that contains no performance or position figures."""
    try:
        sha256_val = compute_sha256(source_path)
    except OSError:
        sha256_val = None
    return PaperLine(
        line_id=line_id,
        name=name,
        category=category,
        status=lifecycle_status,
        data_status="MISSING",
        adjudication=adjudication,
        as_of="unknown",
        freshness="MISSING",
        nav_series=[],
        metrics=None,
        positions=[],
        position_status="MISSING" if lifecycle_status == "ACTIVE_PAPER" else "NOT_APPLICABLE",
        source=LineSource(path=source_path, sha256=sha256_val, produced_at=None),
        safety=LineSafety(research_only=True, orders_authorized=False),
        error=error,
    )
