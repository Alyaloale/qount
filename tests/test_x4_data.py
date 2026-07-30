"""Unit tests for X4 data layer: open-interest metrics parsing + bar alignment (线 D). Plan §2 S4/§5.

Klines reuse ``grid.data`` (spot/um) directly; the new pure pieces here are the binance.vision
``futures/um/.../metrics`` open-interest parser and the forward-fill alignment of OI onto a bar
timeline (no look-ahead). Both are tested offline with no network.
"""

from __future__ import annotations

import unittest

from qount.research_data.market_data import Bar
from qount.legacy.x4.data import OpenInterest
from qount.legacy.x4.data import align_oi_to_bars
from qount.legacy.x4.data import parse_metrics_csv

_T0 = 1_609_459_200_000  # 2021-01-01 00:00:00 UTC
_H = 3_600_000

_HEADER = ("create_time,symbol,sum_open_interest,sum_open_interest_value,"
           "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
           "count_long_short_ratio,sum_taker_long_short_vol_ratio")


class TestParseMetrics(unittest.TestCase):
    def test_parses_datetime_rows_and_skips_header(self) -> None:
        text = "\n".join([
            _HEADER,
            "2021-01-01 00:00:00,BTCUSDT,1000.5,50000000,1.2,1.3,1.1,0.9",
            "2021-01-01 01:00:00,BTCUSDT,1010.0,50500000,1.2,1.3,1.1,0.9",
        ])
        rows = parse_metrics_csv(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], OpenInterest(ts_ms=_T0, oi=1000.5, oi_value=50000000.0))
        self.assertEqual(rows[1].ts_ms, _T0 + _H)

    def test_parses_numeric_epoch_create_time(self) -> None:
        # some dumps store create_time as epoch ms (or microseconds, normalized to ms)
        text = f"{_T0},BTCUSDT,1000.0,5e7,1,1,1,1\n{_T0 * 1000},BTCUSDT,2000.0,1e8,1,1,1,1"
        rows = parse_metrics_csv(text)
        self.assertEqual(rows[0].ts_ms, _T0)
        self.assertEqual(rows[1].ts_ms, _T0)  # microseconds normalized

    def test_skips_malformed_rows(self) -> None:
        text = "\n".join([_HEADER, "2021-01-01 00:00:00,BTCUSDT,notanumber,5e7,1,1,1,1",
                          "2021-01-01 01:00:00,BTCUSDT,1010.0,5e7,1,1,1,1"])
        rows = parse_metrics_csv(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ts_ms, _T0 + _H)


class TestAlignOI(unittest.TestCase):
    def _bars(self, n: int) -> list[Bar]:
        return [Bar(ts_ms=_T0 + i * _H, open=1, high=1, low=1, close=1, volume=1) for i in range(n)]

    def test_forward_fill_last_known(self) -> None:
        oi = [OpenInterest(_T0, 100.0, 0.0), OpenInterest(_T0 + 2 * _H, 200.0, 0.0)]
        aligned = align_oi_to_bars(oi, self._bars(4))
        # bar0 -> 100; bar1 -> still 100 (no new OI yet); bar2 -> 200; bar3 -> 200
        self.assertEqual(aligned, [100.0, 100.0, 200.0, 200.0])

    def test_no_lookahead_before_first_oi_is_none(self) -> None:
        oi = [OpenInterest(_T0 + 2 * _H, 200.0, 0.0)]
        aligned = align_oi_to_bars(oi, self._bars(4))
        self.assertEqual(aligned[0], None)
        self.assertEqual(aligned[1], None)
        self.assertEqual(aligned[2], 200.0)

    def test_empty_oi_all_none(self) -> None:
        self.assertEqual(align_oi_to_bars([], self._bars(3)), [None, None, None])


if __name__ == "__main__":
    unittest.main()
