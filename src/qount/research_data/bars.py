"""Shared seconds-based research bars and causal calculations.

session() preserves the explicitly limited 2026 US calendar used by old studies.
"""
from __future__ import annotations
import datetime as dt
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from zoneinfo import ZoneInfo
NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
HOLIDAYS_2026 = {"2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"}
EARLY_CLOSE_2026 = {"2026-11-27", "2026-12-24"}

@dataclass(frozen=True)
class Bar:
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0
    q: float = 0.0


def iso(t: int) -> str:
    return dt.datetime.fromtimestamp(t, UTC).isoformat()


def aggregate(bars: list[Bar], period: int, source_period: int) -> list[Bar]:
    groups: dict[int, list[Bar]] = defaultdict(list)
    for bar in bars:
        groups[bar.t // period * period].append(bar)
    result = []
    for t, rows in sorted(groups.items()):
        rows.sort(key=lambda row: row.t)
        if [row.t for row in rows] != list(range(t, t + period, source_period)):
            continue  # Incomplete feature bar is never used.
        result.append(Bar(t, rows[0].o, max(row.h for row in rows),
                          min(row.l for row in rows), rows[-1].c,
                          sum(row.v for row in rows), sum(row.q for row in rows)))
    return result


def atr(bars: list[Bar], span: int = 14) -> list[float | None]:
    ranges = [max(bar.h-bar.l, abs(bar.h-bars[i-1].c), abs(bar.l-bars[i-1].c))
              if i else bar.h-bar.l for i, bar in enumerate(bars)]
    result: list[float | None] = [None] * len(bars)
    if len(bars) >= span:
        result[span-1] = statistics.mean(ranges[:span])
        for i in range(span, len(bars)):
            result[i] = (result[i-1] * (span-1) + ranges[i]) / span
    return result


def session(t: int) -> tuple[str, int, int] | None:
    local = dt.datetime.fromtimestamp(t, NY)
    date = local.date().isoformat()
    if local.year != 2026:
        raise ValueError("calendar_only_certified_for_2026")
    if local.weekday() >= 5 or date in HOLIDAYS_2026:
        return None
    return date, local.hour*60+local.minute, 13*60 if date in EARLY_CLOSE_2026 else 16*60


def funding_budget(rows: list[dict], snapshots: list[dict], now: int,
                   remaining_hours: float, config: dict) -> dict:
    """Only information available strictly before decision/fill can set the budget."""
    known = [r for r in rows if (now-72*3600)*1000 <= int(r["fundingTime"]) < now*1000]
    if not known:
        raise ValueError("no_causal_funding_history")
    hours,source = 8.0,"v01_fixed_8h_assumption"
    if config.get("funding_interval_mode") == "known_or_observed":
        available = [r for r in snapshots if r["known_at"] <= now and r["effective_from"] <= now
                     and now < r.get("effective_until",float("inf"))]
        if available:
            record = max(available,key=lambda r:(r["known_at"],r["effective_from"]))
            hours,source = float(record["fundingIntervalHours"]),"point_in_time_snapshot"
        else:
            times = sorted({int(r["fundingTime"])//60000*60 for r in known
                            if r.get("rateType","Regular")=="Regular"})
            hours = (times[-1]-times[-2])/3600 if len(times)>=2 else config["funding_interval_fallback_hours"]
            source = "last_settlement_gap_assumption" if len(times)>=2 else "fallback_interval_assumption"
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError("invalid_funding_interval")
    count = math.ceil(max(remaining_hours,0)/hours)
    return {"fraction":max(abs(float(r["fundingRate"])) for r in known)*count,
            "interval_hours":hours,"interval_source":source,"settlement_count_budget":count}
