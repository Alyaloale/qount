from __future__ import annotations

import unittest

from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.high_return_attribution import _all_next_holding_day_funding
from qount.mini_trend.high_return_attribution import _daily_funding


_T0 = 1_609_459_200_000
_HOUR = 3_600_000
_DAY = 86_400_000


class MiniTrendHighReturnAttributionTest(unittest.TestCase):
    def test_daily_funding_sums_all_three_settlements(self) -> None:
        rows = [
            Funding(_T0 + offset * _HOUR, 0.001)
            for offset in (0, 8, 16)
        ]
        self.assertAlmostEqual(_daily_funding(rows)[_T0 // _DAY], 0.003)

    def test_holding_day_alignment_excludes_final_bar(self) -> None:
        bars = [
            Bar(_T0 + index * _DAY, 100.0, 101.0, 99.0, 100.0, 1000.0)
            for index in range(2)
        ]
        rows = [
            Funding(_T0 + _DAY + offset * _HOUR, 0.001)
            for offset in (0, 8, 16)
        ]
        funding = _all_next_holding_day_funding(rows, bars)
        self.assertAlmostEqual(funding(bars[0]), 0.003)
        self.assertEqual(funding(bars[1]), 0.0)


if __name__ == "__main__":
    unittest.main()
