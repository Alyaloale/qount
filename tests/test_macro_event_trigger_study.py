from __future__ import annotations

import datetime as dt
import hashlib
import json
import unittest

from qount.small_account.macro_event_trigger_study import HourlyCandle
from qount.small_account.macro_event_trigger_study import MacroEvent
from qount.small_account.macro_event_trigger_study import TriggerStudyConfig
from qount.small_account.macro_event_trigger_study import analyze_event
from qount.small_account.macro_event_trigger_study import build_study_report
from qount.small_account.macro_event_trigger_study import scheduled_events


UTC = dt.timezone.utc


def _candle(hour: int, high: float, low: float, close: float) -> HourlyCandle:
    return HourlyCandle(dt.datetime(2024, 1, 1, hour, tzinfo=UTC), 100.0, high, low, close)


class MacroEventTriggerStudyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = TriggerStudyConfig(freeze_hour_count=72)
        self.event = MacroEvent("cpi", "2024-01-04", dt.datetime(2024, 1, 4, 0, 30, tzinfo=UTC))
        self.candles = []
        start = dt.datetime(2023, 12, 31, 23, tzinfo=UTC)
        for index in range(73 + 72):
            opened = start + dt.timedelta(hours=index)
            self.candles.append(HourlyCandle(opened, 100.0, 102.0, 98.0, 100.0))

    def test_scheduled_calendar_has_30_dates_and_dst_utc_conversion(self) -> None:
        events = scheduled_events("cpi")
        self.assertEqual(len(events), 30)
        self.assertEqual(events[0].released_at.isoformat(), "2024-01-11T13:30:00+00:00")
        self.assertEqual(events[2].released_at.isoformat(), "2024-03-12T12:30:00+00:00")

    def test_fomc_calendar_uses_1400_new_york_release_time(self) -> None:
        events = scheduled_events("fomc")
        self.assertEqual(len(events), 20)
        self.assertEqual(events[0].released_at.isoformat(), "2024-01-31T19:00:00+00:00")
        self.assertEqual(events[0].as_dict()["scheduled_local_time"], "14:00 America/New_York")

    def test_uses_only_completed_pre_event_candles_for_freeze(self) -> None:
        self.candles[73] = HourlyCandle(self.candles[73].opened_at, 100.0, 200.0, 1.0, 150.0)
        result = analyze_event(self.event, self.candles, self.config)
        self.assertEqual(result["freeze"]["h0"], 102.0)
        self.assertEqual(result["freeze"]["l0"], 98.0)

    def test_first_breakout_is_anchor_and_measures_d0(self) -> None:
        self.candles[73] = HourlyCandle(self.candles[73].opened_at, 100.0, 112.0, 99.0, 104.0)
        result = analyze_event(self.event, self.candles, self.config)
        self.assertTrue(result["anchor_triggered"])
        self.assertEqual(result["direction"], "long")
        self.assertEqual(result["anchor"]["closed_at_utc"], "2024-01-04T01:00:00+00:00")
        self.assertTrue(result["strong_d0"])

    def test_report_requires_both_frozen_candidate_gates(self) -> None:
        weak = analyze_event(self.event, self.candles, self.config)
        self.assertFalse(weak["anchor_triggered"])
        report = build_study_report((self.event,), self.candles, self.config)
        self.assertEqual(report["verdict"], "not_execution_basket_candidate")
        self.assertFalse(any(report["gates"].values()))

    def test_report_hash_binds_market_provenance(self) -> None:
        report = build_study_report((self.event,), self.candles, self.config, {"response_sha256": ["abc"]})
        digest = report.pop("report_sha256")
        self.assertEqual(
            digest,
            hashlib.sha256(
                json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(report["market_data"]["provenance"]["response_sha256"], ["abc"])

    def test_report_excludes_incomplete_d3_events_from_denominator(self) -> None:
        report = build_study_report((self.event,), self.candles[:85], self.config)
        self.assertEqual(report["summary"]["scheduled_event_count"], 1)
        self.assertEqual(report["summary"]["complete_d3_event_count"], 0)
        self.assertEqual(report["summary"]["incomplete_d3_event_count"], 1)
        self.assertEqual(report["summary"]["event_count"], 0)


if __name__ == "__main__":
    unittest.main()
