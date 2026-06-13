"""Unit tests for GRID-B H3 point-in-time universe selection (洞2)."""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.grid.universe import select_universe
from qount.grid.universe import trailing_adv

_DAY_MS = 86_400_000
_T0 = 1_609_459_200_000  # 2021-01-01


def _daily(prices_vols: list[tuple[float, float]], *, start_day: int = 0) -> list[Bar]:
    out = []
    for i, (p, v) in enumerate(prices_vols):
        ts = _T0 + (start_day + i) * _DAY_MS
        out.append(Bar(ts_ms=ts, open=p, high=p, low=p, close=p, volume=v))
    return out


class TestTrailingADV(unittest.TestCase):
    def test_window_sums_dollar_volume(self) -> None:
        bars = _daily([(100.0, 10.0)] * 30)  # 30 days, $1000/day
        adv = trailing_adv(bars, at_ts=_T0 + 30 * _DAY_MS, window_days=30)
        self.assertAlmostEqual(adv, 1000.0)

    def test_zero_before_listing(self) -> None:
        bars = _daily([(100.0, 10.0)] * 5, start_day=100)  # listed at day 100
        self.assertEqual(trailing_adv(bars, at_ts=_T0 + 10 * _DAY_MS, window_days=30), 0.0)

    def test_only_counts_trailing_window(self) -> None:
        # 60 days; the trailing 30 ending at day 60 excludes the first 30
        bars = _daily([(100.0, 1.0)] * 30 + [(100.0, 5.0)] * 30)
        adv = trailing_adv(bars, at_ts=_T0 + 60 * _DAY_MS, window_days=30)
        self.assertAlmostEqual(adv, 100.0 * 5.0)  # only the high-volume half


class TestSelectUniverse(unittest.TestCase):
    def setUp(self) -> None:
        # three symbols, descending liquidity; one not-yet-listed at the query time
        self.cands = {
            "AAA": _daily([(100.0, 100.0)] * 40),  # ADV ~10000
            "BBB": _daily([(100.0, 50.0)] * 40),   # ADV ~5000
            "CCC": _daily([(100.0, 1.0)] * 40),    # ADV ~100
            "LATE": _daily([(100.0, 999.0)] * 5, start_day=100),  # lists later
        }
        self.at = _T0 + 40 * _DAY_MS

    def test_ranks_by_adv_desc(self) -> None:
        self.assertEqual(select_universe(self.cands, self.at, top_n=2), ["AAA", "BBB"])

    def test_excludes_not_yet_listed(self) -> None:
        sel = select_universe(self.cands, self.at, top_n=10)
        self.assertNotIn("LATE", sel)         # no bars in the trailing window yet
        self.assertEqual(set(sel), {"AAA", "BBB", "CCC"})

    def test_min_adv_floor_drops_thin(self) -> None:
        sel = select_universe(self.cands, self.at, top_n=10, min_adv=1000.0)
        self.assertEqual(set(sel), {"AAA", "BBB"})  # CCC (~100) dropped

    def test_top_n_caps_count(self) -> None:
        self.assertEqual(len(select_universe(self.cands, self.at, top_n=1)), 1)


if __name__ == "__main__":
    unittest.main()
