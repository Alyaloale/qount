"""Unit tests for the X4 S5-VEL minute scalper: velocity/acceleration signal + TP/SL driver (线 D).

Plan §11 (ultra-short impulse hypothesis). Pins: the signal fires only on accelerating up-moves
past threshold (no look-ahead), and the driver fills take-profit / stop **intrabar** from OHLC and
charges a full round-trip fee.
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import run_scalper
from qount.x4.strategies import EfficiencyRegime, GatedVelocityScalper, VelocityScalper

_T0 = 1_609_459_200_000
_M = 60_000  # 1-minute bars


def _bar(i: int, close: float, *, high: float | None = None, low: float | None = None) -> Bar:
    h = close if high is None else high
    lo = close if low is None else low
    return Bar(ts_ms=_T0 + i * _M, open=close, high=max(h, close), low=min(lo, close),
               close=close, volume=1.0)


class TestVelocitySignal(unittest.TestCase):
    def test_warmup_no_signal(self) -> None:
        s = VelocityScalper(vel_window=2, accel_lag=2, vel_threshold=0.0)
        for i in range(4):  # need vel_window+accel_lag+1 = 5 bars
            self.assertEqual(s.on_bar(_bar(i, 100.0)), 0.0)

    def test_fires_on_accelerating_up(self) -> None:
        # convex/accelerating ramp: each step bigger than the last => velocity rising
        s = VelocityScalper(vel_window=2, accel_lag=2, vel_threshold=0.001)
        prices = [100.0, 100.5, 101.5, 103.5, 107.5, 115.5]  # gaps 0.5,1,2,4,8 (accelerating)
        sig = 0.0
        for i, p in enumerate(prices):
            sig = s.on_bar(_bar(i, p))
        self.assertEqual(sig, 1.0)

    def test_no_signal_when_decelerating(self) -> None:
        # rising but decelerating (gaps shrink) => acceleration < 0 => no entry
        s = VelocityScalper(vel_window=2, accel_lag=2, vel_threshold=0.0)
        prices = [100.0, 108.0, 115.0, 119.0, 121.0, 122.0]  # gaps 8,7,4,2,1 (decelerating)
        sig = 0.0
        for i, p in enumerate(prices):
            sig = s.on_bar(_bar(i, p))
        self.assertEqual(sig, 0.0)

    def test_no_signal_in_downtrend(self) -> None:
        s = VelocityScalper(vel_window=2, accel_lag=2, vel_threshold=0.0)
        sig = 0.0
        for i, p in enumerate([100, 99, 97, 94, 90, 85]):
            sig = s.on_bar(_bar(i, float(p)))
        self.assertEqual(sig, 0.0)


class _AlwaysEnter:
    name = "always-enter"

    def on_bar(self, bar: Bar) -> float:
        return 1.0


class _EnterOnce:
    name = "enter-once"

    def __init__(self) -> None:
        self.i = -1

    def on_bar(self, bar: Bar) -> float:
        self.i += 1
        return 1.0 if self.i == 0 else 0.0


class TestScalperTPSL(unittest.TestCase):
    def test_take_profit_exit_books_gain(self) -> None:
        s = _EnterOnce()
        # enter @100; next bar's high reaches the +1% TP => exit at 101
        bars = [_bar(0, 100.0), _bar(1, 100.5, high=101.5)]
        r = run_scalper(bars, s, initial_capital=100_000.0, taker_fee=0.0, slippage=0.0,
                        tp=0.01, sl=0.01)
        self.assertEqual(r.extra["round_trips"], 1)
        self.assertEqual(r.extra["wins"], 1)
        self.assertGreater(r.equity_curve[-1], 100_000.0)

    def test_stop_loss_exit_books_loss(self) -> None:
        s = _EnterOnce()
        bars = [_bar(0, 100.0), _bar(1, 99.5, low=98.5)]  # low pierces the -1% stop => exit 99
        r = run_scalper(bars, s, initial_capital=100_000.0, taker_fee=0.0, slippage=0.0,
                        tp=0.01, sl=0.01)
        self.assertEqual(r.extra["wins"], 0)
        self.assertLess(r.equity_curve[-1], 100_000.0)

    def test_stop_checked_before_tp_when_bar_spans_both(self) -> None:
        s = _EnterOnce()
        bars = [_bar(0, 100.0), _bar(1, 100.0, high=102.0, low=98.0)]  # spans both -> stop wins
        r = run_scalper(bars, s, initial_capital=100_000.0, taker_fee=0.0, slippage=0.0,
                        tp=0.01, sl=0.01)
        self.assertEqual(r.extra["wins"], 0)

    def test_round_trip_pays_two_legs_of_fees(self) -> None:
        s = _EnterOnce()
        bars = [_bar(0, 100.0), _bar(1, 100.5, high=101.5)]
        r = run_scalper(bars, s, initial_capital=100_000.0, taker_fee=0.0005, slippage=0.0,
                        tp=0.01, sl=0.01)
        self.assertGreater(r.fees_paid, 0.0)
        self.assertEqual(r.trade_count, 2)  # entry + exit

    def test_max_hold_timeout_exits_at_close(self) -> None:
        s = _EnterOnce()
        # never hits TP/SL; max_hold=2 forces a close-out
        bars = [_bar(0, 100.0)] + [_bar(i, 100.1) for i in range(1, 5)]
        r = run_scalper(bars, s, initial_capital=100_000.0, taker_fee=0.0, slippage=0.0,
                        tp=0.5, sl=0.5, max_hold=2)
        self.assertEqual(r.extra["round_trips"], 1)


class TestEfficiencyRegime(unittest.TestCase):
    def test_warmup_is_chop(self) -> None:
        r = EfficiencyRegime(window=4, er_threshold=0.35)
        for i in range(4):  # need window+1 = 5 closes
            self.assertEqual(r.on_bar(_bar(i, 100.0)), 0)

    def test_clean_uptrend_is_up(self) -> None:
        # monotone ramp: net == path => ER == 1.0 => +1
        r = EfficiencyRegime(window=4, er_threshold=0.35)
        state = 0
        for i, p in enumerate([100.0, 101.0, 102.0, 103.0, 104.0]):
            state = r.on_bar(_bar(i, p))
        self.assertEqual(state, 1)

    def test_clean_downtrend_is_down(self) -> None:
        r = EfficiencyRegime(window=4, er_threshold=0.35)
        state = 0
        for i, p in enumerate([104.0, 103.0, 102.0, 101.0, 100.0]):
            state = r.on_bar(_bar(i, p))
        self.assertEqual(state, -1)

    def test_chop_is_zero(self) -> None:
        # oscillation with zero net displacement => ER == 0 => chop
        r = EfficiencyRegime(window=4, er_threshold=0.35)
        state = 99
        for i, p in enumerate([100.0, 101.0, 100.0, 101.0, 100.0]):
            state = r.on_bar(_bar(i, p))
        self.assertEqual(state, 0)

    def test_validates_params(self) -> None:
        with self.assertRaises(ValueError):
            EfficiencyRegime(window=1)
        with self.assertRaises(ValueError):
            EfficiencyRegime(er_threshold=1.5)


# Chop-then-burst: the short scalper fires on the final accelerating leg, but over the longer
# regime window the net displacement is small vs the path (ER ≈ 0.43) — so the gate's threshold
# is what decides whether the trade is allowed. Hand-traced in the plan §11 re-test.
_CHOP_BURST = [100.0, 102.0, 100.0, 102.0, 100.0, 102.0, 104.0, 108.0]


class TestGatedVelocityScalper(unittest.TestCase):
    def test_bare_scalper_would_fire_on_burst(self) -> None:
        s = VelocityScalper(vel_window=2, accel_lag=2, vel_threshold=0.001)
        sig = 0.0
        for i, p in enumerate(_CHOP_BURST):
            sig = s.on_bar(_bar(i, p))
        self.assertEqual(sig, 1.0)  # the impulse signal is real

    def test_gate_blocks_when_regime_is_chop(self) -> None:
        # high threshold (> 0.43) => regime reads chop => the firing scalper is gated to flat
        g = GatedVelocityScalper(vel_window=2, accel_lag=2, vel_threshold=0.001,
                                 er_window=6, er_threshold=0.5)
        sig = 1.0
        for i, p in enumerate(_CHOP_BURST):
            sig = g.on_bar(_bar(i, p))
        self.assertEqual(sig, 0.0)

    def test_gate_opens_when_regime_is_up(self) -> None:
        # low threshold (< 0.43) => regime reads up => the same firing scalper passes through
        g = GatedVelocityScalper(vel_window=2, accel_lag=2, vel_threshold=0.001,
                                 er_window=6, er_threshold=0.3)
        sig = 0.0
        for i, p in enumerate(_CHOP_BURST):
            sig = g.on_bar(_bar(i, p))
        self.assertEqual(sig, 1.0)


if __name__ == "__main__":
    unittest.main()
