"""Unit tests for X4 directional strategies S3-CTA / S4-MOM (线 D). Plan: §2.

Both return a per-bar signed target weight in [-1, 1] (equity-normalized; the driver sizes
it). Tests pin determinism, warm-up flatness (no look-ahead), and the core signal logic so
the bake-off compares strategy *logic*, not accidental sizing differences.
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.strategies import MomentumBreakout
from qount.x4.strategies import TrendFollow

_T0 = 1_609_459_200_000
_H = 3_600_000


def _bar(i: int, close: float, *, high: float | None = None, low: float | None = None,
         vol: float = 1.0) -> Bar:
    h = close if high is None else high
    lo = close if low is None else low
    return Bar(ts_ms=_T0 + i * _H, open=close, high=max(h, close), low=min(lo, close),
               close=close, volume=vol)


class TestTrendFollow(unittest.TestCase):
    def test_warmup_is_flat(self) -> None:
        s = TrendFollow(fast=2, slow=4)
        # first slow-1 bars: no slow SMA yet -> flat (0.0), never None-crashes
        for i in range(3):
            self.assertEqual(s.on_bar(_bar(i, 100.0)), 0.0)

    def test_goes_long_in_uptrend_short_in_downtrend(self) -> None:
        s = TrendFollow(fast=2, slow=4)
        up = [100, 101, 102, 103, 104, 105]
        w = 0.0
        for i, c in enumerate(up):
            w = s.on_bar(_bar(i, float(c)))
        self.assertEqual(w, 1.0)  # fast SMA above slow SMA -> long
        s2 = TrendFollow(fast=2, slow=4)
        down = [100, 99, 98, 97, 96, 95]
        for i, c in enumerate(down):
            w = s2.on_bar(_bar(i, float(c)))
        self.assertEqual(w, -1.0)

    def test_deterministic(self) -> None:
        seq = [100, 102, 101, 105, 103, 108, 99, 95]
        runs = []
        for _ in range(2):
            s = TrendFollow(fast=2, slow=4)
            runs.append([s.on_bar(_bar(i, float(c))) for i, c in enumerate(seq)])
        self.assertEqual(runs[0], runs[1])


class TestMomentumBreakout(unittest.TestCase):
    def test_warmup_is_flat(self) -> None:
        s = MomentumBreakout(lookback=3, vol_mult=1.0)
        for i in range(3):
            self.assertEqual(s.on_bar(_bar(i, 100.0)), 0.0)

    def test_long_on_upside_breakout_with_volume(self) -> None:
        s = MomentumBreakout(lookback=3, vol_mult=1.5)
        for i in range(3):
            s.on_bar(_bar(i, 100.0, high=100.0, low=100.0, vol=1.0))
        # breakout above prior high 100 with 2x volume -> long
        w = s.on_bar(_bar(3, 105.0, high=105.0, vol=2.0))
        self.assertEqual(w, 1.0)

    def test_no_breakout_without_volume(self) -> None:
        s = MomentumBreakout(lookback=3, vol_mult=1.5)
        for i in range(3):
            s.on_bar(_bar(i, 100.0, high=100.0, low=100.0, vol=1.0))
        w = s.on_bar(_bar(3, 105.0, high=105.0, vol=1.0))  # price breaks, volume flat
        self.assertEqual(w, 0.0)

    def test_short_on_downside_breakout(self) -> None:
        s = MomentumBreakout(lookback=3, vol_mult=1.5)
        for i in range(3):
            s.on_bar(_bar(i, 100.0, high=100.0, low=100.0, vol=1.0))
        w = s.on_bar(_bar(3, 95.0, low=95.0, vol=2.0))
        self.assertEqual(w, -1.0)

    def test_position_persists_until_opposite_breakout(self) -> None:
        s = MomentumBreakout(lookback=3, vol_mult=1.5)
        for i in range(3):
            s.on_bar(_bar(i, 100.0, high=100.0, low=100.0, vol=1.0))
        self.assertEqual(s.on_bar(_bar(3, 105.0, high=105.0, vol=2.0)), 1.0)
        # quiet bar inside range -> still long (no exit signal)
        self.assertEqual(s.on_bar(_bar(4, 104.0, high=105.0, low=104.0, vol=1.0)), 1.0)


if __name__ == "__main__":
    unittest.main()
