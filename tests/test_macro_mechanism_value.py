"""Timing and accounting for the offline ETF mechanism experiment."""
import datetime as dt
import unittest

from qount.research.macro_mechanism_value import daily_replay
from qount.research_data.bars import Bar, NY


class MacroMechanismValueTest(unittest.TestCase):
    def fixture(self):
        times = [int(dt.datetime(2020, 1, day, 16, tzinfo=NY).timestamp()) for day in (6, 7, 8, 9)]
        bars = [Bar(t, 100, 101, 99, 100) for t in times]
        rows = {t: dict(available=t, date=dt.datetime.fromtimestamp(t, NY).date().isoformat(),
            hold_structural=True, hold_tactical=True, structural=True, rank_core=1., rank_tactical=1.,
            entry_tactical=True, tactical_setup="mean_reversion", atr=2., realized_vol20=.3)
            for t in times}
        return times, {"SPYUSDT": bars}, {"SPYUSDT": rows}

    def run_book(self, book, rows, **kwargs):
        return daily_replay(book, rows, "original_all", start="2020-01-07", end="2020-01-10",
                            fee=0, slip=0, **kwargs)

    def test_prior_signal_next_open_and_no_future_entry(self):
        times, book, rows = self.fixture()
        rows["SPYUSDT"][times[0]]["entry_tactical"] = False
        result = self.run_book(book, rows)
        self.assertEqual(len(result["trades"]), 1)
        trade = result["trades"][0]
        self.assertEqual(trade["signal_time"], times[1])
        self.assertEqual(dt.datetime.fromtimestamp(trade["entry_time"], NY).day, 8)

    def test_current_close_trailing_applies_only_to_next_session(self):
        times, book, rows = self.fixture()
        book["SPYUSDT"][1] = Bar(times[1], 100, 120, 97, 110)
        book["SPYUSDT"][2] = Bar(times[2], 105, 106, 100, 103)
        rows["SPYUSDT"][times[2]]["entry_tactical"] = False
        result = self.run_book(book, rows)
        self.assertEqual(len(result["trades"]), 1)
        trade = result["trades"][0]
        self.assertEqual(trade["exit_reason"], "stop_gap")
        self.assertEqual(trade["exit_price"], 105)
        self.assertEqual(dt.datetime.fromtimestamp(trade["exit_time"], NY).day, 8)

    def test_gap_through_stop_uses_open_and_no_same_session_reentry(self):
        times, book, rows = self.fixture()
        book["SPYUSDT"][2] = Bar(times[2], 90, 92, 88, 91)
        result = self.run_book(book, rows)
        self.assertEqual(result["trades"][0]["exit_price"], 90)
        self.assertEqual(dt.datetime.fromtimestamp(result["trades"][1]["entry_time"], NY).day, 9)

    def test_vol_budget_reads_previous_completed_session(self):
        times, book, rows = self.fixture()
        rows["SPYUSDT"][times[1]]["realized_vol20"] = .01
        result = self.run_book(book, rows, vol_target=.15)
        self.assertEqual(result["trades"][0]["quantity"], 50)
        self.assertEqual(result["trades"][0]["weight"], .5)

    def test_end_window_liquidation_and_friction_reconcile(self):
        _, book, rows = self.fixture()
        result = daily_replay(book, rows, "original_all", start="2020-01-07", end="2020-01-09")
        trade = result["trades"][0]
        self.assertEqual(trade["exit_reason"], "end_of_sample")
        self.assertLess(result["curve"][-1]["equity"], 10000)
        self.assertAlmostEqual(result["curve"][-1]["equity"], 10000+trade["net_pnl"])

    def test_fixed_fifteen_sessions_ignores_regime_exit_and_keeps_exact_horizon(self):
        times, book, rows = self.fixture()
        sample = dict(rows["SPYUSDT"][times[0]])
        dates = [dt.date(2020, 1, 6)+dt.timedelta(days=i) for i in range(40)]
        times = [int(dt.datetime.combine(day, dt.time(16), NY).timestamp()) for day in dates if day.weekday() < 5]
        book = {"SPYUSDT": [Bar(t, 100, 101, 99, 100) for t in times]}
        rows = {"SPYUSDT": {t: dict(sample, available=t, hold_structural=False) for t in times}}
        opening = times[1]-int(6.5*3600)
        result = daily_replay(book, rows, "original_mr", start="2020-01-07", end="2020-02-10",
            holding="fixed15", stops=False, entry_times={opening})
        self.assertEqual(len(result["trades"]), 1)
        t = result["trades"][0]
        self.assertEqual(t["exit_reason"], "fixed15_close")
        self.assertEqual(t["exit_time"], times[15])

    def test_signal_source_can_differ_from_execution_asset(self):
        times, book, rows = self.fixture()
        book["QQQUSDT"] = [Bar(t, 200, 202, 198, 200) for t in times]
        rows["QQQUSDT"] = {t: dict(f, rank_tactical=2.) for t, f in rows["SPYUSDT"].items()}
        result = daily_replay(book, rows, "original_all", start="2020-01-07", end="2020-01-10",
            execution_symbol="SPYUSDT", holding="fixed15", stops=False, fee=0, slip=0)
        t = result["trades"][0]
        self.assertEqual(t["source_symbol"], "QQQUSDT")
        self.assertEqual(t["symbol"], "SPYUSDT")
        self.assertEqual(t["entry_price"], 100)


if __name__ == "__main__":
    unittest.main()
