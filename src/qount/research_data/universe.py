"""R0-DATA point-in-time universe revision builder.

Takes a collection of :class:`PointInTimeSymbolLifecycle` records and produces
frozen :class:`PointInTimeUniverseRevision` snapshots at specified dates.
Each revision captures exactly which symbols were active and tradeable at
``as_of``, with explicit exclusion reasons for symbols that were not yet
listed, already delisted, suspended, or lacking data.

This is the contract that downstream research backtests must respect:
``build_point_in_time_universe`` selects membership using only
``valid_from <= as_of < valid_to`` -- never back-filling future listings
or post-delisting survival.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any
from typing import Mapping
from typing import Sequence

from qount.governance.research_records import PointInTimeSymbolLifecycle
from qount.governance.research_records import PointInTimeUniverseRevision
from qount.governance.research_records import build_point_in_time_universe


# --- Revision schedule ------------------------------------------------------


def quarterly_schedule(
    start: str,
    end: str,
) -> list[str]:
    """Generate quarterly ``as_of`` ISO datetimes in ``[start, end]``.

    Each snapshot is taken at the first day of each quarter
    (Jan/Apr/Jul/Oct 1st, 00:00 UTC).
    """

    start_dt = _dt.datetime.fromisoformat(start)
    end_dt = _dt.datetime.fromisoformat(end)
    if end_dt < start_dt:
        return []
    # Align start to the first day of its quarter.
    q_month = ((start_dt.month - 1) // 3) * 3 + 1
    cursor = _dt.datetime(start_dt.year, q_month, 1, tzinfo=_dt.UTC)
    if cursor.tzinfo is None:
        cursor = cursor.replace(tzinfo=_dt.UTC)
    dates: list[str] = []
    while cursor <= end_dt:
        dates.append(cursor.isoformat())
        month = cursor.month + 3
        year = cursor.year
        if month > 12:
            month, year = 1, year + 1
        cursor = _dt.datetime(year, month, 1, tzinfo=_dt.UTC)
    return dates


def monthly_schedule(
    start: str,
    end: str,
) -> list[str]:
    """Generate monthly ``as_of`` ISO datetimes in ``[start, end]``."""

    start_dt = _dt.datetime.fromisoformat(start)
    end_dt = _dt.datetime.fromisoformat(end)
    if end_dt < start_dt:
        return []
    cursor = _dt.datetime(start_dt.year, start_dt.month, 1, tzinfo=_dt.UTC)
    if cursor.tzinfo is None:
        cursor = cursor.replace(tzinfo=_dt.UTC)
    dates: list[str] = []
    while cursor <= end_dt:
        dates.append(cursor.isoformat())
        month = cursor.month + 1
        year = cursor.year
        if month > 12:
            month, year = 1, year + 1
        cursor = _dt.datetime(year, month, 1, tzinfo=_dt.UTC)
    return dates


# --- Exclusion reason builder -----------------------------------------------


def _exclusion_reason(
    lifecycle: PointInTimeSymbolLifecycle,
    as_of: str,
) -> str | None:
    """Return the reason a lifecycle is excluded at *as_of*, or ``None`` if included."""

    from qount.contracts.trace import aware_datetime

    cutoff = aware_datetime(as_of)
    start = aware_datetime(lifecycle.valid_from)
    if start > cutoff:
        return "not_yet_listed"
    if lifecycle.valid_to is not None:
        end = aware_datetime(lifecycle.valid_to)
        if cutoff >= end:
            return "delisted_or_expired"
    if lifecycle.state != "active":
        return f"state_{lifecycle.state}"
    return None


def build_exclusion_reasons(
    lifecycles: Sequence[PointInTimeSymbolLifecycle],
    *,
    as_of: str,
    venue: str,
) -> dict[str, str]:
    """Build exclusion reasons for all symbols not included at *as_of*."""

    from qount.contracts.trace import aware_datetime

    cutoff = aware_datetime(as_of)
    reasons: dict[str, str] = {}
    for lc in lifecycles:
        if lc.venue != venue:
            continue
        start = aware_datetime(lc.valid_from)
        if start > cutoff:
            reasons[lc.symbol] = "not_yet_listed"
            continue
        if lc.valid_to is not None:
            end = aware_datetime(lc.valid_to)
            if cutoff >= end:
                reasons[lc.symbol] = "delisted_or_expired"
                continue
        if lc.state != "active":
            reasons[lc.symbol] = f"state_{lc.state}"
    return reasons


# --- Revision builder -------------------------------------------------------


def build_revision(
    lifecycles: Sequence[PointInTimeSymbolLifecycle],
    *,
    as_of: str,
    venue: str,
    source_hashes: Mapping[str, str],
    dataset_role: str = "point_in_time_collection",
    extra_exclusions: Mapping[str, str] | None = None,
) -> PointInTimeUniverseRevision:
    """Build one frozen universe revision at *as_of*.

    ``extra_exclusions`` can add data-driven exclusions (e.g. a symbol that
    is listed and active but has no kline data at ``as_of``).  Symbols in
    ``extra_exclusions`` are removed from ``included_symbols`` and their
    reason is recorded in ``exclusion_reasons``.
    """

    base = build_point_in_time_universe(
        lifecycles,
        as_of=as_of,
        venue=venue,
        source_hashes=source_hashes,
        exclusion_reasons=build_exclusion_reasons(lifecycles, as_of=as_of, venue=venue),
        dataset_role=dataset_role,
    )

    if not extra_exclusions:
        return base

    included = tuple(s for s in base.included_symbols if s not in extra_exclusions)
    exclusion_reasons = dict(base.exclusion_reasons)
    for symbol, reason in extra_exclusions.items():
        if symbol in base.included_symbols:
            exclusion_reasons[symbol] = reason

    return PointInTimeUniverseRevision.create(
        as_of=as_of,
        venue=venue,
        included_symbols=included,
        exclusion_reasons=exclusion_reasons,
        lifecycle_hashes=base.lifecycle_hashes,
        source_hashes=source_hashes,
        dataset_role=dataset_role,
    )


def build_revision_series(
    lifecycles: Sequence[PointInTimeSymbolLifecycle],
    *,
    as_of_dates: Sequence[str],
    venue: str,
    source_hashes: Mapping[str, str],
    dataset_role: str = "point_in_time_collection",
) -> list[PointInTimeUniverseRevision]:
    """Build a series of frozen revisions at each date in *as_of_dates*."""

    revisions: list[PointInTimeUniverseRevision] = []
    for as_of in as_of_dates:
        revision = build_revision(
            lifecycles,
            as_of=as_of,
            venue=venue,
            source_hashes=source_hashes,
            dataset_role=dataset_role,
        )
        revisions.append(revision)
    return revisions


# --- Summary ----------------------------------------------------------------


def summarize_revisions(
    revisions: list[PointInTimeUniverseRevision],
    *,
    venue: str,
) -> list[dict[str, Any]]:
    """Build a compact summary list of universe sizes over time."""

    summaries: list[dict[str, Any]] = []
    for rev in revisions:
        summaries.append({
            "as_of": rev.as_of,
            "venue": rev.venue,
            "included_count": len(rev.included_symbols),
            "excluded_count": len(rev.exclusion_reasons),
            "revision_id": rev.revision_id,
        })
    return summaries
