"""Verify economic labels and actual open timestamps of the market study."""
import datetime as dt
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts/research"))
import study_binance_market_states as study
sys.path.pop(0)

from qount.research_data.bars import Bar, NY


class MarketStateStudyTest(unittest.TestCase):
    def test_crypto_full_extra_day_and_signed_short_funding(self):
        bars = [Bar((i+1)*86400-1, 100 if i < 4 else 90, 101, 89, 100) for i in range(8)]
        rows = {b.t: dict(route_side=-1 if i == 0 else 0, action_state="down_breakout")
                for i, b in enumerate(bars)}
        panel = dict(funding_value=np.zeros((8,7)))
        panel["funding_value"][2:4,0] = [1., 2.]
        records, censored = study.opportunity_labels("crypto", "BTCUSDT", bars, rows, panel,
            horizon=2, cost_bp=10, start="1970-01-01")
        self.assertEqual(len(records), 1)
        trade = records[0]
        self.assertEqual(trade["entry_time"], 2*86400)
        self.assertEqual(trade["exit_time"], 4*86400)
        self.assertAlmostEqual(trade["funding_on_notional"], .03)
        self.assertAlmostEqual(trade["net_label"], .1+.03-.0019)
        self.assertEqual(censored, 0)

    def test_etf_signal_close_executes_next_session_open_and_costs_both_legs(self):
        days = [dt.date(2026,10,22), dt.date(2026,10,23), dt.date(2026,10,26), dt.date(2026,10,27)]
        bars = [Bar(int(dt.datetime.combine(day, dt.time(16), NY).timestamp()),
                    100+i, 105, 99, 102) for i, day in enumerate(days)]
        rows = {b.t: dict(route_side=1 if i == 0 else 0, action_state="up_breakout")
                for i, b in enumerate(bars)}
        records, _ = study.opportunity_labels("etf_proxy", "SPYUSDT", bars, rows, {},
            horizon=2, cost_bp=30, start="2026-01-01")
        trade = records[0]
        self.assertEqual(trade["entry_time"], int(dt.datetime(2026,10,23,9,30,tzinfo=NY).timestamp()))
        self.assertEqual(trade["exit_time"], int(dt.datetime(2026,10,27,9,30,tzinfo=NY).timestamp()))
        self.assertAlmostEqual(trade["net_label"], 103/101-1-.003*(1+103/101))


if __name__ == "__main__":
    unittest.main()
