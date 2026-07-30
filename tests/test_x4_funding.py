from __future__ import annotations

import unittest

from qount.research_data.market_data import Bar, Funding
from qount.legacy.x4.funding import holding_period_funding


_T0 = 1_609_459_200_000
_HOUR = 3_600_000
_DAY = 86_400_000


def _bar(ts_ms: int) -> Bar:
    return Bar(ts_ms, 100.0, 101.0, 99.0, 100.0, 1000.0)


class X4FundingAlignmentTest(unittest.TestCase):
    def test_daily_bar_gets_all_three_next_day_settlements(self) -> None:
        bars = [_bar(_T0), _bar(_T0 + _DAY)]
        rows = [Funding(_T0 + _DAY + hour * _HOUR, 0.001) for hour in (0, 8, 16)]
        result = holding_period_funding(rows, bars, "1d")
        self.assertAlmostEqual(result[bars[0].ts_ms], 0.003)
        self.assertEqual(result[bars[1].ts_ms], 0.0)

    def test_hourly_bar_aligns_boundary_settlement_to_prior_signal(self) -> None:
        bars = [_bar(_T0 + 7 * _HOUR), _bar(_T0 + 8 * _HOUR)]
        rows = [Funding(_T0 + 8 * _HOUR, 0.001)]
        result = holding_period_funding(rows, bars, "1h")
        self.assertEqual(result[bars[0].ts_ms], 0.001)
        self.assertEqual(result[bars[1].ts_ms], 0.0)

    def test_unknown_interval_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            holding_period_funding([], [_bar(_T0)], "2h")


if __name__ == "__main__":
    unittest.main()
