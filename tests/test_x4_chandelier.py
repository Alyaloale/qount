"""Unit tests for the X4 asymmetric Chandelier exit in run_directional (线 D §15).

Long-only trailing stop at highest_high_since_entry − mult×ATR: ratchets up, flattens + latches when
a bar's low pierces it, re-arms only after the underlying signal resets. Slow entry, fast exit.
"""

from __future__ import annotations

import unittest

from qount.research_data.market_data import Bar
from qount.legacy.x4.backtest import run_directional

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


class _AlwaysShort:
    name = "always-short"

    def on_bar(self, bar: Bar) -> float:
        return -1.0


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


    def test_short_squeeze_stop_flattens_before_the_rally(self) -> None:
        # mirror of the long test: decline to ~71 (a profitable short), then a violent squeeze back up
        # to 122. The symmetric chandelier covers the short early; the no-stop short rides the squeeze.
        bars = [_bar(i, 100.0 - i, high=100.0 - i + 1, low=100.0 - i - 1) for i in range(30)]  # ~71
        for j, c in enumerate([76.0, 82.0, 90.0, 100.0, 110.0, 118.0, 122.0]):
            bars.append(_bar(30 + j, c, high=c + 1, low=c - 1))
        stopped = run_directional(bars, _AlwaysShort(), initial_capital=100_000.0, taker_fee=0.0,
                                  slippage=0.0, chandelier_mult=3.0, chandelier_lookback=5)
        no_ch = run_directional(bars, _AlwaysShort(), initial_capital=100_000.0, taker_fee=0.0,
                                slippage=0.0, chandelier_mult=0.0)
        self.assertGreaterEqual(stopped.extra["chandelier_exits"], 1)
        self.assertGreater(stopped.equity_curve[-1], no_ch.equity_curve[-1])  # covered the squeeze

    def test_short_does_not_trigger_long_branch(self) -> None:
        # a pure downtrend short should never fire the (long) stop and never the short stop either
        bars = [_bar(i, 100.0 - i, high=100.0 - i + 1, low=100.0 - i - 1) for i in range(20)]
        r = run_directional(bars, _AlwaysShort(), initial_capital=100_000.0, taker_fee=0.0,
                            slippage=0.0, chandelier_mult=3.0, chandelier_lookback=5)
        self.assertEqual(r.extra["chandelier_exits"], 0)
        self.assertGreater(r.equity_curve[-1], r.equity_curve[0])  # short profited on the decline


class TestProfitTaking(unittest.TestCase):
    """§8 profit-taking / giveback control: profit-conditional tightening + partial scale-out."""

    def test_profit_lock_tightens_and_exits_where_wide_holds(self) -> None:
        # rally 100->140, then a pullback to ~133. A wide 20x stop rides through it; the same run with
        # profit-lock (tighten to 1x once +10% in profit) exits on the pullback.
        rise = [_bar(i, 100.0 + 2.0 * i, high=100.0 + 2.0 * i + 0.5, low=100.0 + 2.0 * i - 0.5)
                for i in range(21)]                         # 100 -> 140
        bars = rise + [_bar(21, 134.0, high=134.5, low=133.0)]
        common = dict(initial_capital=100_000.0, taker_fee=0.0, slippage=0.0, rebalance_band=5.0,
                      chandelier_mult=20.0, chandelier_lookback=10)
        plain = run_directional(bars, _AlwaysLong(), **common)
        lock = run_directional(bars, _AlwaysLong(), **common,
                               profit_lock_threshold=0.10, profit_lock_mult=1.0)
        self.assertEqual(plain.extra["chandelier_exits"], 0)       # wide stop never fired
        self.assertGreaterEqual(lock.extra["chandelier_exits"], 1)  # tightened stop locked the gain

    def test_profit_lock_off_by_default_matches_plain(self) -> None:
        bars = [_bar(i, 100.0 + i, high=100.0 + i + 1, low=100.0 + i - 1) for i in range(20)]
        common = dict(initial_capital=100_000.0, taker_fee=0.0, slippage=0.0,
                      chandelier_mult=8.0, chandelier_lookback=5)
        a = run_directional(bars, _AlwaysLong(), **common)
        b = run_directional(bars, _AlwaysLong(), **common, profit_lock_threshold=0.0,
                            profit_lock_mult=0.0)
        self.assertEqual(a.equity_curve, b.equity_curve)

    def test_scale_out_trims_at_thresholds_and_keeps_residual(self) -> None:
        # rally 100 -> 160 (+60%); scale out 1/3 every +20%, floor at ~1/3 residual.
        bars = [_bar(i, 100.0 + 4.0 * i, high=100.0 + 4.0 * i + 0.5, low=100.0 + 4.0 * i - 0.5)
                for i in range(16)]                          # 100 -> 160
        common = dict(initial_capital=100_000.0, taker_fee=0.0, slippage=0.0, rebalance_band=0.25)
        plain = run_directional(bars, _AlwaysLong(), **common)
        so = run_directional(bars, _AlwaysLong(), **common,
                             scale_out_step=0.20, scale_out_frac=0.34, scale_out_residual=0.32)
        self.assertGreaterEqual(so.extra["scale_outs"], 2)        # trimmed at +20% and +40%
        self.assertGreater(so.extra["final_position_base"], 0.0)  # residual still long (not flat)
        self.assertLess(so.extra["final_position_base"],
                        plain.extra["final_position_base"])       # but smaller than full size

    def test_scale_out_ratchet_does_not_re_add_on_retrace(self) -> None:
        # rally to +40% (two scale-outs -> residual), then retrace to +10%: must NOT rebuild the size.
        rise = [_bar(i, 100.0 + 4.0 * i, high=100.0 + 4.0 * i + 0.5, low=100.0 + 4.0 * i - 0.5)
                for i in range(11)]                          # 100 -> 140
        bars = rise + [_bar(11, 110.0, high=110.5, low=109.5)]
        common = dict(initial_capital=100_000.0, taker_fee=0.0, slippage=0.0, rebalance_band=0.25)
        plain = run_directional(bars, _AlwaysLong(), **common)
        so = run_directional(bars, _AlwaysLong(), **common,
                             scale_out_step=0.20, scale_out_frac=0.34, scale_out_residual=0.32)
        self.assertEqual(so.extra["scale_outs"], 2)               # no extra step on the way down
        self.assertLess(so.extra["final_position_base"], 0.5 * plain.extra["final_position_base"])


if __name__ == "__main__":
    unittest.main()
