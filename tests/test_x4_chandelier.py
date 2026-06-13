"""Unit tests for the X4 asymmetric Chandelier exit in run_directional (线 D §15).

Long-only trailing stop at highest_high_since_entry − mult×ATR: ratchets up, flattens + latches when
a bar's low pierces it, re-arms only after the underlying signal resets. Slow entry, fast exit.
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import run_directional

_T0 = 1_609_459_200_000
_D = 86_400_000


def _bar(i: int, close: float, *, high: float | None = None, low: float | None = None) -> Bar:
    h = close if high is None else high
    lo = close if low is None else low
    return Bar(ts_ms=_T0 + i * _D, open=close, high=max(h, close), low=min(lo, close),
               close=close, volume=1.0)


class _AlwaysLong:
    name = "always-long"

    def on_bar(self, bar: Bar) -> float:
        return 1.0


class _LongThenFlat:
    """Long for the first ``n`` bars, then flat — to test re-arm after a chandelier latch."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.i = -1

    def on_bar(self, bar: Bar) -> float:
        self.i += 1
        return 1.0 if self.i < self.n else 0.0


class TestChandelier(unittest.TestCase):
    def test_trailing_stop_flattens_before_the_decline(self) -> None:
        # rally to ~129, then a multi-bar decline to 78: chandelier exits early and sits flat through
        # the rest of the fall, while the no-stop long rides all the way down.
        bars = [_bar(i, 100.0 + i, high=100.0 + i + 1, low=100.0 + i - 1) for i in range(30)]  # ~129
        for j, c in enumerate([124.0, 118.0, 110.0, 100.0, 90.0, 82.0, 78.0]):
            bars.append(_bar(30 + j, c, high=c + 1, low=c - 1))
        flat = run_directional(bars, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                               slippage=0.0, chandelier_mult=3.0, chandelier_lookback=5)
        no_ch = run_directional(bars, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                                slippage=0.0, chandelier_mult=0.0)
        self.assertGreaterEqual(flat.extra["chandelier_exits"], 1)
        self.assertGreater(flat.equity_curve[-1], no_ch.equity_curve[-1])  # flat avoided the fall

    def test_off_by_default_matches_plain_run(self) -> None:
        bars = [_bar(0, 100.0), _bar(1, 110.0)]
        a = run_directional(bars, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                            slippage=0.0, chandelier_mult=0.0)
        self.assertAlmostEqual(a.equity_curve[-1], 110_000.0, places=2)
        self.assertEqual(a.extra.get("chandelier_exits", 0), 0)

    def test_latch_blocks_reentry_until_signal_resets(self) -> None:
        # after a chandelier exit while the signal is still "long", it must NOT re-enter next bar
        bars = [_bar(i, 100.0 + i, high=100.0 + i + 1, low=100.0 + i - 1) for i in range(20)]
        bars.append(_bar(20, 90.0, high=119.0, low=90.0))   # deep pullback -> chandelier exit
        bars.append(_bar(21, 92.0, high=93.0, low=91.0))    # signal still long, but latched -> flat
        r = run_directional(bars, _AlwaysLong(), initial_capital=100_000.0, taker_fee=0.0,
                            slippage=0.0, chandelier_mult=3.0, chandelier_lookback=5)
        # after the latch fires, the final position is flat (no re-entry while signal stays long)
        self.assertGreaterEqual(r.extra["chandelier_exits"], 1)
        # equity flat across the last bar (no position) -> last two equity points ~equal
        self.assertAlmostEqual(r.equity_curve[-1], r.equity_curve[-2], places=2)


if __name__ == "__main__":
    unittest.main()
