"""Published cash-equity dates, causal live inputs and year-boundary display."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.research_data.bars import CalendarUnavailable, NY, session
from qount.research_data.macro_live import expected_feature_date
from qount.strategies.macro_1atr import STRATEGY_ID, is_decision


def stamp(date, hour=10, minute=0):
    return int(dt.datetime.fromisoformat(f"{date}T{hour:02}:{minute:02}:00").replace(tzinfo=NY).timestamp())


class NyseCalendarTest(unittest.TestCase):
    def test_every_2026_date_preserves_the_original_calendar(self):
        holidays = {"01-01", "01-19", "02-16", "04-03", "05-25", "06-19", "07-03", "09-07", "11-26", "12-25"}
        early = {"11-27", "12-24"}
        for offset in range(365):
            date = dt.date(2026, 1, 1)+dt.timedelta(days=offset)
            for minute in (0, 570, 600, 780, 960, 1439):
                expected = (None if date.weekday() >= 5 or date.strftime("%m-%d") in holidays else
                            (date.isoformat(), minute, 780 if date.strftime("%m-%d") in early else 960))
                self.assertEqual(session(stamp(date.isoformat(), minute//60, minute%60)), expected)

    def test_published_2027_and_2028_full_closures_reject_entry(self):
        closed = {
            2027: ("01-01", "01-18", "02-15", "03-26", "05-31", "06-18", "07-05", "09-06", "11-25", "12-24"),
            2028: ("01-17", "02-21", "04-14", "05-29", "06-19", "07-04", "09-04", "11-23", "12-25"),
        }
        for year, days in closed.items():
            for day in days:
                with self.subTest(year=year, day=day):
                    now = stamp(f"{year}-{day}")
                    self.assertIsNone(session(now))
                    self.assertFalse(is_decision(now))
        for date in ("2027-01-02", "2028-01-01", "2028-12-31"):
            self.assertIsNone(session(stamp(date)))

    def test_early_closes_and_saturday_new_year_exception(self):
        for date in ("2027-11-26", "2028-07-03", "2028-11-24"):
            self.assertEqual(session(stamp(date))[2], 780)
            self.assertTrue(is_decision(stamp(date)))
        # NYSE explicitly observes no New Year's holiday for Saturday 2028-01-01.
        for date in ("2027-07-02", "2027-11-24", "2027-12-23", "2027-12-31", "2028-12-22"):
            self.assertEqual(session(stamp(date))[2], 960)
            self.assertTrue(is_decision(stamp(date)))

    def test_new_york_dst_keeps_ten_am_decisions_at_correct_utc_hour(self):
        for date, hour in (("2026-10-30", 14), ("2026-11-02", 15),
                           ("2027-03-12", 15), ("2027-03-15", 14), ("2027-11-05", 14), ("2027-11-08", 15),
                           ("2028-03-10", 15), ("2028-03-13", 14), ("2028-11-03", 14), ("2028-11-06", 15)):
            now = stamp(date)
            self.assertEqual(dt.datetime.fromtimestamp(now, dt.timezone.utc).hour, hour)
            self.assertTrue(is_decision(now))
            self.assertFalse(is_decision(now-3600))
            self.assertFalse(is_decision(now+60))

    def test_completed_feature_day_crosses_years_and_holidays_without_future_data(self):
        for date, previous in (("2027-01-01", "2026-12-31"), ("2027-01-04", "2026-12-31"),
                               ("2027-03-29", "2027-03-25"), ("2027-12-27", "2027-12-23"),
                               ("2028-01-03", "2027-12-31"), ("2028-07-05", "2028-07-03")):
            self.assertEqual(expected_feature_date(stamp(date)).isoformat(), previous)
        # Preserve conservative 16:00 publication, including a 13:00 early close.
        for hour, expected in ((13, "2028-06-30"), (15, "2028-06-30"), (16, "2028-07-03")):
            self.assertEqual(expected_feature_date(stamp("2028-07-03", hour)).isoformat(), expected)

    def test_unpublished_years_remain_unknown(self):
        for date in ("2025-12-31", "2029-01-02"):
            with self.assertRaises(CalendarUnavailable):
                session(stamp(date))
            with self.assertRaises(CalendarUnavailable):
                is_decision(stamp(date))

    def test_api_next_entry_crosses_year_and_dst_but_never_guesses_unknown_year(self):
        from qount.api.routes.account import get_one_atr_status
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = root/"result.json"
            env = {"QOUNT_1ATR_RESULT_PATH": str(result), "QOUNT_1ATR_EXECUTION_STORE": str(root/"execution.db"),
                   "QOUNT_1ATR_ARM_PATH": str(root/"arm.json"), "QOUNT_1ATR_HALT_PATH": str(root/"HALT"),
                   "QOUNT_ACCOUNT_ASSETS_PATH": str(root/"assets.json"), "QOUNT_ACCOUNT_TRADES_PATH": str(root/"trades.db")}
            for date, expected in (("2026-12-31", "2027-01-04T15:00:00+00:00"),
                                   ("2027-12-31", "2028-01-03T15:00:00+00:00"),
                                   ("2027-03-12", "2027-03-15T14:00:00+00:00"),
                                   ("2028-12-29", None)):
                now = dt.datetime.fromtimestamp(stamp(date, 17), dt.timezone.utc)
                result.write_text(json.dumps(dict(strategy_id=STRATEGY_ID, execution_mode="auto_live", created_at=now.isoformat())))
                with patch.dict(os.environ, env), patch("qount.api.routes.account.datetime") as clock:
                    clock.now.return_value = now
                    clock.side_effect = dt.datetime
                    clock.fromisoformat = dt.datetime.fromisoformat
                    actual = get_one_atr_status()
                self.assertEqual(actual["next_entry_at"], expected)

