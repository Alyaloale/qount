"""Anchors survive misses, respect session breaks and never use future prices."""
import copy
import datetime as dt
import unittest

from qount.research.binance_macro_entry_episodes import episode_confirmations
from qount.research.small_account_breakout import Bar, NY


class TestEntryEpisodes(unittest.TestCase):
    def fixture(self):
        data, fs, times = {"A": dict(trade=[])}, {"A": []}, []
        for day, price in ((21, 100), (24, 105), (25, 99), (26, 104), (27, 110)):
            now = int(dt.datetime(2026, 8, day, 10, tzinfo=NY).timestamp())
            available = now-18*3600
            times.append(now)
            data["A"]["trade"].append(Bar(now, price, price+1, price-1, price, 1))
            fs["A"].append(dict(available=available, entry_tactical=True, tactical_setup="breakout"))
        return data, fs, times

    def test_weekend_continuation_keeps_first_anchor_and_allows_better_price(self):
        data, fs, t = self.fixture()
        gates = episode_confirmations(data, fs, "no_chase")
        self.assertTrue(gates["A", t[0]]["eligible"])
        self.assertFalse(gates["A", t[1]]["eligible"])
        self.assertTrue(gates["A", t[2]]["eligible"])
        self.assertFalse(gates["A", t[3]]["eligible"])
        self.assertTrue(all(g["anchor_price"] == 100 for g in gates.values()))
        first = episode_confirmations(data, fs, "first_only")
        self.assertEqual(sum(g["eligible"] for g in first.values()), 1)

    def test_signal_gap_and_setup_change_start_new_episode(self):
        data, fs, t = self.fixture()
        fs["A"][1]["entry_tactical"] = False
        fs["A"][3]["tactical_setup"] = "pullback"
        gates = episode_confirmations(data, fs, "first_only")
        self.assertTrue(gates["A", t[2]]["first"])
        self.assertTrue(gates["A", t[3]]["first"])
        self.assertTrue(gates["A", t[4]]["first"])

    def test_future_price_and_feature_changes_cannot_change_prior_gates(self):
        data, fs, t = self.fixture()
        baseline = episode_confirmations(data, fs, "no_chase")
        changed, signals = copy.deepcopy(data), copy.deepcopy(fs)
        changed["A"]["trade"][-1] = Bar(t[-1], 1, 1, 1, 1, 0)
        signals["A"][-1]["entry_tactical"] = False
        result = episode_confirmations(changed, signals, "no_chase")
        for key in baseline:
            if key[1] < t[-1]:
                self.assertEqual(baseline[key], result[key])

    def test_entry_hour_high_low_close_and_volume_are_not_used(self):
        data, fs, t = self.fixture()
        baseline = episode_confirmations(data, fs, "no_chase")
        data["A"]["trade"][1] = Bar(t[1], 105, 10000, .001, 9999, 1e9)
        self.assertEqual(episode_confirmations(data, fs, "no_chase"), baseline)

    def test_unlisted_history_has_no_anchor_or_fake_price(self):
        data, fs, t = self.fixture()
        data["A"]["trade"] = data["A"]["trade"][1:]
        result = episode_confirmations(data, fs, "no_chase")
        self.assertNotIn(("A", t[0]), result)
        self.assertEqual(result["A", t[1]]["anchor_price"], 105)
        self.assertTrue(result["A", t[1]]["first"])


if __name__ == "__main__":
    unittest.main()
