"""Unit tests for the X4 parameter-ensemble wrapper (线 D §14).

Averaging N sub-strategies' target weights -> consensus sizing (full when aligned, small when they
disagree), still in [-1, 1] so it feeds run_directional directly.
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import run_directional
from qount.x4.strategies import EnsembleStrategy, TrendFollow

_T0 = 1_609_459_200_000
_D = 86_400_000


def _bar(i: int, close: float) -> Bar:
    return Bar(ts_ms=_T0 + i * _D, open=close, high=close, low=close, close=close, volume=1.0)


class _Fixed:
    """A stub member returning a fixed weight (to test averaging deterministically)."""

    def __init__(self, w: float) -> None:
        self.name = f"fixed{w}"
        self.w = w
        self.calls = 0

    def on_bar(self, bar: Bar) -> float:
        self.calls += 1
        return self.w


class TestEnsemble(unittest.TestCase):
    def test_mean_of_member_weights(self) -> None:
        ens = EnsembleStrategy([_Fixed(1.0), _Fixed(1.0), _Fixed(0.0)])
        self.assertAlmostEqual(ens.on_bar(_bar(0, 100.0)), 2.0 / 3.0)

    def test_disagreement_nets_to_small_position(self) -> None:
        ens = EnsembleStrategy([_Fixed(1.0), _Fixed(-1.0)])
        self.assertAlmostEqual(ens.on_bar(_bar(0, 100.0)), 0.0)  # opposing votes cancel

    def test_every_member_fed_each_bar(self) -> None:
        members = [_Fixed(1.0), _Fixed(0.0)]
        ens = EnsembleStrategy(members)
        for i in range(5):
            ens.on_bar(_bar(i, 100.0))
        self.assertEqual([m.calls for m in members], [5, 5])

    def test_single_member_equals_that_member(self) -> None:
        # an ensemble of one TrendFollow == the bare TrendFollow on the same path
        seq = [100, 102, 101, 105, 103, 108, 99, 95, 97, 110]
        solo = TrendFollow(fast=2, slow=4)
        ens = EnsembleStrategy([TrendFollow(fast=2, slow=4)])
        for i, c in enumerate(seq):
            self.assertEqual(solo.on_bar(_bar(i, float(c))), ens.on_bar(_bar(i, float(c))))

    def test_fractional_weight_sizes_fractional_position(self) -> None:
        # ensemble weight 0.5 (one long member, one flat) -> ~half the position of a full long
        bars = [_bar(0, 100.0), _bar(1, 110.0)]
        half = EnsembleStrategy([_Fixed(1.0), _Fixed(0.0)])
        full = EnsembleStrategy([_Fixed(1.0)])
        r_half = run_directional(bars, half, initial_capital=100_000.0, taker_fee=0.0, slippage=0.0)
        r_full = run_directional(bars, full, initial_capital=100_000.0, taker_fee=0.0, slippage=0.0)
        gain_half = r_half.equity_curve[-1] - 100_000.0
        gain_full = r_full.equity_curve[-1] - 100_000.0
        self.assertAlmostEqual(gain_half, gain_full * 0.5, places=2)


if __name__ == "__main__":
    unittest.main()
