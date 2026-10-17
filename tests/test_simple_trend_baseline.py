"""Timing and native availability for the fixed simple trend comparison."""
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from qount.research.lines.simple_trend import candidate_clocks, simple_features, trend_rows
from qount.research_data.bars import Bar, NY


class TestSimpleTrendBaseline(unittest.TestCase):
    def daily(self, length=160):
        first = dt.datetime(2026, 1, 1, 16, tzinfo=NY)
        return [dict(available=int((first+dt.timedelta(days=i)).timestamp()),
                     date=(first+dt.timedelta(days=i)).date().isoformat(), close=100+i)
                for i in range(length)]

    def test_warmup_and_flat_market_do_not_create_trades(self):
        daily = self.daily(120)
        for row in daily:
            row["close"] = 100
        rows = trend_rows(daily)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["available"], daily[-1]["available"])
        self.assertFalse(rows[0]["entry_tactical"])
        with self.assertRaisesRegex(ValueError, "120_daily"):
            trend_rows(daily[:-1])

    def test_later_prices_do_not_change_earlier_signals_or_rank(self):
        daily = self.daily()
        original = trend_rows(daily)
        changed = copy.deepcopy(daily)
        for row in changed[140:]:
            row["close"] *= .01
        self.assertEqual(original[:21], trend_rows(changed)[:21])
        self.assertTrue(all(r["entry_tactical"] for r in original))
        self.assertNotEqual(original[-1]["entry_tactical"], trend_rows(changed)[-1]["entry_tactical"])

    def test_unordered_or_invalid_prices_fail(self):
        daily = self.daily()
        daily[120]["available"] = daily[119]["available"]
        with self.assertRaisesRegex(ValueError, "ordered"):
            trend_rows(daily)
        daily = self.daily()
        daily[100]["close"] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid_daily_close"):
            trend_rows(daily)

    def test_raw_daily_timestamp_is_published_at_close_and_future_dates_are_excluded(self):
        daily = self.daily()
        data = dict(chart=dict(result=[dict(timestamp=[r["available"]-int(6.5*3600) for r in daily],
                     indicators=dict(adjclose=[dict(adjclose=[r["close"] for r in daily])]))]))
        end = "2026-05-15"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/f"yahoo-TEST-20250101-{end}.json"
            path.write_text(json.dumps(data))
            features, sources = simple_features(Path(directory), {"TESTUSDT": "TEST"}, end)
        self.assertEqual(len(sources), 1)
        first, last = features["TESTUSDT"][0], features["TESTUSDT"][-1]
        self.assertEqual(first["available"], daily[119]["available"])
        self.assertEqual(last["date"], "2026-05-14")
        self.assertEqual(dt.datetime.fromtimestamp(last["available"], NY).hour, 16)

    def test_union_of_histories_excludes_prelisting_and_future_features(self):
        now = int(dt.datetime(2026, 6, 16, 10, tzinfo=NY).timestamp())
        previous = now-86400
        bar = lambda t: Bar(t, 100, 101, 99, 100, 10)
        book = {"LATE": dict(trade=[bar(now)]), "EARLY": dict(trade=[bar(previous), bar(now)])}
        rows = [dict(available=previous-18*3600, entry_tactical=True),
                dict(available=now-18*3600, entry_tactical=True),
                dict(available=now+1, entry_tactical=False)]
        clocks = set(candidate_clocks(book, {"LATE": rows, "EARLY": rows}))
        self.assertEqual(clocks, {("EARLY", previous), ("EARLY", now), ("LATE", now)})


if __name__ == "__main__":
    unittest.main()
