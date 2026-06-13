"""Unit tests for the X4 B1-b rebalance deadband / pos-change gating (线 D). Plan §9 B1-b.

B1 headline showed S2-PAIR churning ~1 trade/bar from resizing both legs every bar at a constant
position — a rebalancing-tax artifact. And directional runs micro-churn from fee-induced equity
drift. These tests pin the fixes: ``run_pair`` trades only on position change; ``run_directional``
honors a drift deadband (still trades on a genuine signal flip).
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import run_directional, run_pair
from qount.x4.strategies import PairStrategy

_T0 = 1_609_459_200_000
_H = 3_600_000
_CAP = 100_000.0


def _bar(i: int, close: float) -> Bar:
    return Bar(ts_ms=_T0 + i * _H, open=close, high=close, low=close, close=close, volume=1.0)


def _series(prices: list[float]) -> list[Bar]:
    return [_bar(i, p) for i, p in enumerate(prices)]


class _ConstLong:
    name = "const-long"

    def on_bar(self, bar: Bar) -> float:
        return 1.0


class _Flipper:
    """Long for the first half of bars, short for the second — one genuine signal flip."""

    name = "flipper"

    def __init__(self, flip_at: int) -> None:
        self.flip_at = flip_at
        self.i = -1

    def on_bar(self, bar: Bar) -> float:
        self.i += 1
        return 1.0 if self.i < self.flip_at else -1.0


class TestDirectionalDeadband(unittest.TestCase):
    def test_band_suppresses_fee_microchurn(self) -> None:
        # constant long, constant price, nonzero fee: only the open should trade under a band
        bars = _series([100.0] * 10)
        banded = run_directional(bars, _ConstLong(), initial_capital=_CAP, taker_fee=0.0005,
                                 slippage=0.0, rebalance_band=0.25)
        churn = run_directional(bars, _ConstLong(), initial_capital=_CAP, taker_fee=0.0005,
                                slippage=0.0, rebalance_band=0.0)
        self.assertEqual(banded.trade_count, 1)          # just the open
        self.assertGreater(churn.trade_count, banded.trade_count)  # band=0 micro-churns

    def test_band_still_trades_on_signal_flip(self) -> None:
        bars = _series([100.0] * 6)
        r = run_directional(bars, _Flipper(flip_at=3), initial_capital=_CAP, taker_fee=0.0005,
                            slippage=0.0, rebalance_band=0.25)
        self.assertGreaterEqual(r.trade_count, 2)  # open long + flip to short


class TestPairPosChangeGating(unittest.TestCase):
    def test_held_position_does_not_rechurn_each_bar(self) -> None:
        # ratio jumps and stays elevated => pos enters +1 once and holds for many bars
        cfg = PairStrategy(window=3, entry_z=1.0, exit_z=0.3)
        btc = _series([100.0] * 8)
        eth = _series([100.0, 100.0, 100.0, 140.0, 141.0, 142.0, 143.0, 144.0])
        r = run_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0005, slippage=0.0)
        self.assertEqual(r.extra["final_pos"], 1)
        self.assertEqual(r.trade_count, 2)  # one entry per leg, NOT 2 * held-bars

    def test_exit_trades_back_to_flat(self) -> None:
        cfg = PairStrategy(window=3, entry_z=1.0, exit_z=0.3)
        btc = _series([100.0] * 9)
        # spike (enter), then sit flat at par long enough for the trailing window to converge => exit
        eth = _series([100.0, 100.0, 100.0, 140.0, 141.0, 100.0, 100.0, 100.0, 100.0])
        r = run_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0005, slippage=0.0)
        self.assertEqual(r.extra["final_pos"], 0)   # reverted => exited
        self.assertEqual(r.trade_count, 4)          # 2 legs in, 2 legs out


if __name__ == "__main__":
    unittest.main()
