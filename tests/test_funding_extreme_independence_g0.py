from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path
import unittest

from qount.research_data.market_data import Funding


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "research"
    / "mini_trend"
    / "run_funding_extreme_independence_g0.py"
)
SPEC = importlib.util.spec_from_file_location("funding_extreme_g0", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FundingExtremeIndependenceG0Test(unittest.TestCase):
    def test_requires_two_consecutive_extreme_settlements(self) -> None:
        start = int(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        extreme = MODULE.EXTREME_ANNUALIZED_ABS_FUNDING / MODULE.ANNUALIZATION_FACTOR
        rows = [
            Funding(start, extreme),
            Funding(start + MODULE.SETTLEMENT_MS, extreme),
            Funding(start + 3 * MODULE.SETTLEMENT_MS, extreme),
        ]
        episodes = MODULE._episodes(MODULE._extreme_rows(rows))
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["settlement_count"], 2)

    def test_overlap_uses_preceding_calendar_day(self) -> None:
        clusters = [
            {
                "start_utc": "2026-01-09T16:00:00Z",
                "end_utc": "2026-01-09T16:00:00Z",
                "symbols": ["BTCUSDT"],
            },
            {
                "start_utc": "2026-01-07T16:00:00Z",
                "end_utc": "2026-01-07T16:00:00Z",
                "symbols": ["ETHUSDT"],
            },
        ]
        result = MODULE._overlap((dt.date(2026, 1, 10),), clusters)
        self.assertEqual(result["matched_trial_signal_count"], 1)
        self.assertEqual(result["overlap_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
