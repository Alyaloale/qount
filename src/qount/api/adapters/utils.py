"""Utility functions for adapters."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Optional


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


def compute_freshness(as_of: Optional[str], reference_date: Optional[str] = "2026-10-12") -> str:
    """Compute FRESH | STALE | MISSING based on as_of and reference date."""
    if not as_of:
        return "MISSING"
    norm_as_of = format_date_str(as_of)
    try:
        dt_as_of = datetime.strptime(norm_as_of, "%Y-%m-%d").date()
        ref_dt = datetime.strptime(reference_date or "2026-10-12", "%Y-%m-%d").date()
        days_diff = (ref_dt - dt_as_of).days
        # Fresh if within 4 calendar days (e.g. Friday 10-09 to Monday 10-12 is 3 days)
        if 0 <= days_diff <= 4:
            return "FRESH"
        return "STALE"
    except Exception:
        return "STALE"
