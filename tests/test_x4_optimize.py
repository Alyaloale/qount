"""Unit tests for the X4 B3 optimization levers (线 D). Plan §9/§10 optimization round.

Root cause of the B1-b losses: 1h whipsaw + shorting a long-uptrending asset (S3/S4) and a soft
pair that runs away (S2). The fixes pinned here: long-bias (``allow_short=False``) on directional
strategies, the Turtle asymmetric exit channel on S4, and the ``stop_z`` cointegration-break cut on
S2. (Timeframe = daily is a script/run choice, validated separately.)
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import run_pair
from qount.x4.strategies import MomentumBreakout, PairStrategy, TrendFollow

_T0 = 1_609_459_200_000
_H = 3_600_000
_CAP = 100_000.0


def _bar(i: int, close: float, *, high: float | None = None, low: float | None = None,
         vol: float = 1.0) -> Bar:
    h = close if high is None else high
    lo = close if low is None else low
    return Bar(ts_ms=_T0 + i * _H, open=close, high=max(h, close), low=min(lo, close),
               close=close, volume=vol)


class TestLongBias(unittest.TestCase):
    def test_trend_long_only_flat_in_downtrend(self) -> None:
        s = TrendFollow(fast=2, slow=4, allow_short=False)
        w = 0.0
        for i, c in enumerate([100, 99, 98, 97, 96, 95]):
            w = s.on_bar(_bar(i, float(c)))
        self.assertEqual(w, 0.0)  # would be -1.0 if short allowed
        # control: short allowed -> -1.0
        s2 = TrendFollow(fast=2, slow=4, allow_short=True)
        for i, c in enumerate([100, 99, 98, 97, 96, 95]):
            w = s2.on_bar(_bar(i, float(c)))
        self.assertEqual(w, -1.0)

    def test_momentum_long_only_never_shorts(self) -> None:
        s = MomentumBreakout(lookback=3, vol_mult=1.0, allow_short=False)
        for i in range(3):
            s.on_bar(_bar(i, 100.0, high=100.0, low=100.0))
        w = s.on_bar(_bar(3, 95.0, low=95.0, vol=2.0))  # downside break
        self.assertEqual(w, 0.0)  # flat, not short

    def test_momentum_long_only_exits_on_channel_break(self) -> None:
        s = MomentumBreakout(lookback=3, vol_mult=1.0, exit_lookback=2, allow_short=False)
        for i in range(3):
            s.on_bar(_bar(i, 100.0, high=100.0, low=100.0))
        self.assertEqual(s.on_bar(_bar(3, 110.0, high=110.0, vol=2.0)), 1.0)  # enter long
        self.assertEqual(s.on_bar(_bar(4, 108.0, high=110.0, low=108.0)), 1.0)  # hold
        # break below the 2-bar exit-channel low -> flatten
        self.assertEqual(s.on_bar(_bar(5, 100.0, high=108.0, low=100.0)), 0.0)


class TestRegimeGate(unittest.TestCase):
    def test_trend_regime_gate_blocks_long_below_sma200(self) -> None:
        # fast>slow (a long signal) but price below the long-term regime SMA => stay flat
        s = TrendFollow(fast=2, slow=4, allow_short=False, regime_sma=6)
        # closes drop then bounce: a short-term up-cross while still under the 6-SMA
        closes = [120, 110, 100, 90, 80, 70, 75, 82]
        w = 0.0
        for i, c in enumerate(closes):
            w = s.on_bar(_bar(i, float(c)))
        self.assertEqual(w, 0.0)  # bounce is below SMA6 -> regime gate keeps it flat

    def test_trend_regime_gate_allows_long_above_sma200(self) -> None:
        s = TrendFollow(fast=2, slow=4, allow_short=False, regime_sma=6)
        closes = [70, 72, 74, 80, 90, 100, 115, 130]  # rising, last close above SMA6
        w = 0.0
        for i, c in enumerate(closes):
            w = s.on_bar(_bar(i, float(c)))
        self.assertEqual(w, 1.0)

    def test_momentum_regime_gate_blocks_breakout_below_sma(self) -> None:
        # deep drop then a small bounce: it breaks the 3-bar high (100) but is still below SMA6(~136)
        s = MomentumBreakout(lookback=3, vol_mult=1.0, allow_short=False, regime_sma=6)
        closes = [200, 200, 200, 100, 100, 100]  # SMA6 stays high from the old highs
        for i, c in enumerate(closes):
            s.on_bar(_bar(i, float(c), high=c, low=c))
        w = s.on_bar(_bar(6, 115.0, high=115.0, vol=2.0))  # break above 100 but below SMA6
        self.assertEqual(w, 0.0)


class TestPairStopZ(unittest.TestCase):
    def _series(self, prices: list[float]) -> list[Bar]:
        return [_bar(i, p) for i, p in enumerate(prices)]

    def test_stop_z_cuts_runaway_and_latches(self) -> None:
        # ratio enters on a jump, then jumps further (cointegration break) -> stop fires, stays flat.
        # (window>=5 so the trailing z can actually exceed stop_z; with window=3 it is bounded ~1.15.)
        cfg = PairStrategy(window=5, entry_z=1.0, exit_z=0.3, stop_z=1.5)
        btc = self._series([100.0] * 7)
        eth = self._series([100.0, 100.0, 100.0, 100.0, 100.0, 130.0, 200.0])
        r = run_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        self.assertEqual(r.extra["final_pos"], 0)  # stopped out, not riding the divergence

    def test_no_stop_when_disabled(self) -> None:
        cfg = PairStrategy(window=5, entry_z=1.0, exit_z=0.3, stop_z=0.0)
        btc = self._series([100.0] * 7)
        eth = self._series([100.0, 100.0, 100.0, 100.0, 100.0, 130.0, 200.0])
        r = run_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        self.assertEqual(r.extra["final_pos"], 1)  # still holding the losing spread


if __name__ == "__main__":
    unittest.main()
