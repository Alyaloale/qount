"""Frozen, order-free macro-event anchor-trigger study utilities.

The discovery study uses completed hourly OKX BTC-USDT candles and keeps the
measurement anchor-only; it does not alter the live FOMC execution contract.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass
from zoneinfo import ZoneInfo
from typing import Any, Iterable, Mapping, Sequence

from qount.models import utc_now


UTC = dt.timezone.utc
NEW_YORK = ZoneInfo("America/New_York")
STUDY_VERSION = "macro_event_anchor_trigger_study_v0.1"
EVENT_SOURCES = {
    "cpi": "https://www.bls.gov/schedule/news_release/cpi.htm",
    "nfp": "https://www.bls.gov/schedule/news_release/empsit.htm",
    "fomc": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
}

_EVENT_LOCAL_TIMES = {
    "cpi": (8, 30),
    "nfp": (8, 30),
    "fomc": (14, 0),
}

# These scheduled publication dates cover 2024-01 through 2026-06 inclusive.
# CPI/NFP use 08:30 and FOMC uses 14:00 America/New_York; ZoneInfo freezes the
# corresponding UTC timestamp including daylight-saving changes.
_RELEASE_DATES = {
    "cpi": (
        "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15", "2024-06-12",
        "2024-07-11", "2024-08-14", "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
        "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13", "2025-06-11",
        "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-24", "2025-11-13", "2025-12-10",
        "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-10", "2026-05-12", "2026-06-10",
    ),
    "nfp": (
        "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03", "2024-06-07",
        "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04", "2024-11-01", "2024-12-06",
        "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-02", "2025-06-06",
        "2025-07-03", "2025-08-01", "2025-09-05", "2025-10-03", "2025-11-07", "2025-12-05",
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05",
    ),
    "fomc": (
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18",
        "2024-11-07", "2024-12-18",
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17",
        "2025-10-29", "2025-12-10",
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    ),
}


@dataclass(frozen=True)
class MacroEvent:
    event_type: str
    event_date: str
    released_at: dt.datetime

    @property
    def event_id(self) -> str:
        return f"{self.event_type}-{self.event_date}"

    def as_dict(self) -> dict[str, str]:
        hour, minute = _EVENT_LOCAL_TIMES[self.event_type]
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_date": self.event_date,
            "scheduled_local_time": f"{hour:02d}:{minute:02d} America/New_York",
            "released_at_utc": self.released_at.isoformat(),
            "source_url": EVENT_SOURCES[self.event_type],
        }


@dataclass(frozen=True)
class HourlyCandle:
    opened_at: dt.datetime
    open: float
    high: float
    low: float
    close: float

    @property
    def closed_at(self) -> dt.datetime:
        return self.opened_at + dt.timedelta(hours=1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "opened_at_utc": self.opened_at.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
        }


@dataclass(frozen=True)
class TriggerStudyConfig:
    freeze_hour_count: int = 72
    atr_period: int = 14
    breakout_atr_multiple: float = 0.25
    anchor_window_hours: int = 10
    d0_window_hours: int = 10
    d1_window_hours: int = 34
    d3_window_hours: int = 72
    strong_d0_atr: float = 2.0
    weak_d0_atr: float = 1.5
    weak_reversal_d3_atr: float = 2.0
    minimum_anchor_rate: float = 0.40
    fomc_anchor_count: int = 11
    fomc_event_count: int = 20
    fomc_strong_anchor_count: int = 7
    fomc_strong_proportion_multiple: float = 0.70

    @property
    def fomc_anchor_rate(self) -> float:
        return self.fomc_anchor_count / self.fomc_event_count

    @property
    def fomc_strong_given_anchor_rate(self) -> float:
        return self.fomc_strong_anchor_count / self.fomc_anchor_count

    @property
    def minimum_strong_given_anchor_rate(self) -> float:
        return self.fomc_strong_given_anchor_rate * self.fomc_strong_proportion_multiple


def scheduled_events(event_type: str) -> tuple[MacroEvent, ...]:
    if event_type not in _RELEASE_DATES:
        raise ValueError(f"unsupported event type: {event_type}")
    events = []
    hour, minute = _EVENT_LOCAL_TIMES[event_type]
    for event_date in _RELEASE_DATES[event_type]:
        local = dt.datetime.fromisoformat(
            f"{event_date}T{hour:02d}:{minute:02d}:00"
        ).replace(tzinfo=NEW_YORK)
        events.append(MacroEvent(event_type, event_date, local.astimezone(UTC)))
    return tuple(events)


def all_scheduled_events() -> tuple[MacroEvent, ...]:
    return tuple(event for name in sorted(_RELEASE_DATES) for event in scheduled_events(name))


def _canonical_json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_candles(candles: Sequence[HourlyCandle]) -> tuple[HourlyCandle, ...]:
    normalized = tuple(sorted(candles, key=lambda row: row.opened_at))
    if not normalized:
        raise ValueError("hourly candles are empty")
    if any(row.opened_at.tzinfo is None for row in normalized):
        raise ValueError("hourly candle timestamps must be timezone-aware")
    if len({row.opened_at for row in normalized}) != len(normalized):
        raise ValueError("hourly candle timestamps must be unique")
    if any(row.high < max(row.open, row.close) or row.low > min(row.open, row.close) for row in normalized):
        raise ValueError("hourly candle OHLC is invalid")
    return normalized


def _atr(candles: Sequence[HourlyCandle], period: int) -> float:
    if len(candles) < period + 1:
        raise ValueError("insufficient completed candles for ATR")
    rows = candles[-(period + 1):]
    true_ranges = [
        max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close))
        for previous, current in zip(rows, rows[1:])
    ]
    value = sum(true_ranges) / period
    if value <= 0.0:
        raise ValueError("ATR must be positive")
    return value


def _window(candles: Iterable[HourlyCandle], event: MacroEvent, hours: int) -> tuple[HourlyCandle, ...]:
    end = event.released_at + dt.timedelta(hours=hours)
    return tuple(row for row in candles if row.closed_at > event.released_at and row.closed_at <= end)


def _complete_hourly_window(window: Sequence[HourlyCandle], hours: int) -> bool:
    if len(window) < hours:
        return False
    recent = window[-hours:]
    return all(
        right.opened_at - left.opened_at == dt.timedelta(hours=1)
        for left, right in zip(recent, recent[1:])
    )


def _excursions(
    candles: Sequence[HourlyCandle], *, direction: str, breakout_line: float, atr: float
) -> dict[str, float]:
    if not candles:
        raise ValueError("event window is empty")
    if direction == "long":
        favorable = (max(row.high for row in candles) - breakout_line) / atr
        adverse = (breakout_line - min(row.low for row in candles)) / atr
    else:
        favorable = (breakout_line - min(row.low for row in candles)) / atr
        adverse = (max(row.high for row in candles) - breakout_line) / atr
    return {"favorable_atr": favorable, "adverse_atr": adverse}


def analyze_event(
    event: MacroEvent,
    candles: Sequence[HourlyCandle],
    config: TriggerStudyConfig | None = None,
) -> dict[str, Any]:
    config = config or TriggerStudyConfig()
    rows = _validate_candles(candles)
    completed = tuple(row for row in rows if row.closed_at <= event.released_at)
    if len(completed) < config.freeze_hour_count:
        raise ValueError(f"{event.event_id}: insufficient pre-event completed candles")
    frozen = completed[-config.freeze_hour_count:]
    atr = _atr(frozen, config.atr_period)
    upper = max(row.high for row in frozen) + config.breakout_atr_multiple * atr
    lower = min(row.low for row in frozen) - config.breakout_atr_multiple * atr
    anchors = _window(rows, event, config.anchor_window_hours)
    anchor: HourlyCandle | None = None
    direction: str | None = None
    for row in anchors:
        if row.close > upper:
            anchor, direction = row, "long"
            break
        if row.close < lower:
            anchor, direction = row, "short"
            break
    result: dict[str, Any] = {
        **event.as_dict(),
        "freeze": {
            "freeze_hour_count": config.freeze_hour_count,
            "frozen_through_utc": frozen[-1].closed_at.isoformat(),
            "h0": max(row.high for row in frozen),
            "l0": min(row.low for row in frozen),
            "atr14": atr,
            "upper_breakout_line": upper,
            "lower_breakout_line": lower,
        },
        "anchor_triggered": anchor is not None,
        "direction": direction,
    }
    windows = {
        label: _window(rows, event, hours)
        for label, hours in (
            ("d0", config.d0_window_hours),
            ("d1", config.d1_window_hours),
            ("d3", config.d3_window_hours),
        )
    }
    result["d0_complete"] = _complete_hourly_window(windows["d0"], config.d0_window_hours)
    result["d1_complete"] = _complete_hourly_window(windows["d1"], config.d1_window_hours)
    result["d3_complete"] = _complete_hourly_window(windows["d3"], config.d3_window_hours)
    if anchor is None or direction is None:
        return result
    breakout_line = upper if direction == "long" else lower
    result["anchor"] = {
        "closed_at_utc": anchor.closed_at.isoformat(),
        "close": anchor.close,
        "breakout_line": breakout_line,
        "distance_atr": abs(anchor.close - breakout_line) / atr,
    }
    for label in ("d0", "d1", "d3"):
        if windows[label]:
            result[label] = _excursions(
                windows[label], direction=direction, breakout_line=breakout_line, atr=atr
            )
    result["strong_d0"] = result.get("d0_complete", False) and result["d0"]["favorable_atr"] >= config.strong_d0_atr
    result["weak_d0"] = result.get("d0_complete", False) and result["d0"]["favorable_atr"] < config.weak_d0_atr
    result["weak_reversal_d3"] = (
        result["weak_d0"]
        and result.get("d3_complete", False)
        and result["d3"]["adverse_atr"] >= config.weak_reversal_d3_atr
    )
    return result


def build_study_report(
    events: Sequence[MacroEvent],
    candles: Sequence[HourlyCandle],
    config: TriggerStudyConfig | None = None,
    market_data_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or TriggerStudyConfig()
    rows = _validate_candles(candles)
    event_rows = [analyze_event(event, rows, config) for event in events]
    complete_event_rows = [row for row in event_rows if row["d3_complete"]]
    triggered = [row for row in complete_event_rows if row["anchor_triggered"]]
    strong = [row for row in triggered if row["strong_d0"]]
    weak = [row for row in triggered if row["weak_d0"]]
    weak_reversals = [row for row in weak if row["weak_reversal_d3"]]
    anchor_rate = len(triggered) / len(complete_event_rows) if complete_event_rows else 0.0
    strong_rate = len(strong) / len(triggered) if triggered else 0.0
    gates = {
        "anchor_trigger_rate_at_least_40pct": anchor_rate >= config.minimum_anchor_rate,
        "strong_d0_given_anchor_at_least_70pct_of_fomc": strong_rate >= config.minimum_strong_given_anchor_rate,
    }
    event_type = events[0].event_type if events else "unknown"
    report = {
        "schema_version": STUDY_VERSION,
        "artifact_type": "macro_event_anchor_trigger_study",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
            "market_source": "OKX BTC-USDT public 1H candles",
            "measurement_scope": "anchor-only; excludes v0.2 15m confirmation and all PnL",
        },
        "event_type": event_type,
        "calendar": {
            "count": len(events),
            "source_url": EVENT_SOURCES.get(event_type),
            "events": [event.as_dict() for event in events],
        },
        "contract": {
            **asdict(config),
            "fomc_anchor_rate": config.fomc_anchor_rate,
            "fomc_strong_given_anchor_rate": config.fomc_strong_given_anchor_rate,
            "minimum_strong_given_anchor_rate": config.minimum_strong_given_anchor_rate,
            "fomc_reference_note": "docs/fomc-trigger-study-and-v03-extension.md",
        },
        "market_data": {
            "candle_count": len(rows),
            "first_opened_at_utc": rows[0].opened_at.isoformat(),
            "last_opened_at_utc": rows[-1].opened_at.isoformat(),
            "canonical_sha256": _canonical_json_hash({"candles": [row.as_dict() for row in rows]}),
            "provenance": dict(market_data_provenance or {}),
        },
        "summary": {
            "scheduled_event_count": len(event_rows),
            "complete_d3_event_count": len(complete_event_rows),
            "incomplete_d3_event_count": len(event_rows) - len(complete_event_rows),
            "event_count": len(complete_event_rows),
            "anchor_trigger_count": len(triggered),
            "anchor_trigger_rate": anchor_rate,
            "strong_d0_count": len(strong),
            "strong_d0_given_anchor_rate": strong_rate,
            "weak_d0_count": len(weak),
            "weak_reversal_d3_count": len(weak_reversals),
            "weak_reversal_d3_given_weak_rate": len(weak_reversals) / len(weak) if weak else None,
        },
        "gates": gates,
        "verdict": "execution_basket_candidate" if all(gates.values()) else "not_execution_basket_candidate",
        "events": event_rows,
    }
    report["report_sha256"] = _canonical_json_hash(report)
    return report
