"""Unit tests for the X4 single-asset directional backtest driver (线 D). Plan: §3/§4.

The driver feeds one bar stream to a strategy, sizes its target weight equity-normalized,
trades the unified account, and reports the §4 metrics. These tests pin equity-normalized
sizing, no look-ahead, and metric correctness (reusing ``rv.stats``).
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import max_drawdown
from qount.x4.backtest import run_directional

_T0 = 1_609_459_200_000
_H = 3_600_000


def _bar(i: int, close: float) -> Bar:
    return Bar(ts_ms=_T0 + i * _H, open=close, high=close, low=close, close=close, volume=1.0)


class _AlwaysLong:
    name = "always-long"

    def on_bar(self, bar: Bar) -> float:
        return 1.0


class _AlwaysFlat:
    name = "flat"

    def on_bar(self, bar: Bar) -> float:
        return 0.0


class TestSizingAndPnL(unittest.TestCase):
    def test_always_long_tracks_price_1x(self) -> None:
        # equity-normalized 1x long: a +10% price move => ~+10% equity (frictionless)
        bars = [_bar(0, 100.0), _bar(1, 110.0)]
        r = run_directional(bars, _AlwaysLong(), initial_capital=100_000.0,
                            taker_fee=0.0, slippage=0.0)
        self.assertAlmostEqual(r.equity_curve[-1], 110_000.0, places=2)
        self.assertAlmostEqual(r.total_return, 0.10, places=4)

    def test_flat_strategy_is_constant_equity(self) -> None:
        bars = [_bar(i, 100.0 + i) for i in range(10)]
        r = run_directional(bars, _AlwaysFlat(), initial_capital=100_000.0,
                            taker_fee=0.0005, slippage=0.0)
        self.assertEqual(r.equity_curve[-1], 100_000.0)  # never trades, no fees
        self.assertEqual(r.fees_paid, 0.0)

    def test_no_lookahead_uses_close_of_same_bar(self) -> None:
        # strategy decides on bar t's close and fills at bar t's close; the first long is
        # established on bar 0 and only bar 1's move accrues -> result independent of any
        # future bar beyond the last.
        bars = [_bar(0, 100.0), _bar(1, 110.0), _bar(2, 110.0)]
        r = run_directional(bars, _AlwaysLong(), initial_capital=100_000.0,
                            taker_fee=0.0, slippage=0.0)
        self.assertAlmostEqual(r.equity_curve[1], 110_000.0, places=2)
        self.assertAlmostEqual(r.equity_curve[2], 110_000.0, places=2)


class TestMetrics(unittest.TestCase):
    def test_max_drawdown_basic(self) -> None:
        self.assertAlmostEqual(max_drawdown([100, 120, 60, 90]), 60 / 120 - 1)  # -0.5
        self.assertEqual(max_drawdown([100, 101, 102]), 0.0)

    def test_result_reports_trades_and_fees(self) -> None:
        bars = [_bar(0, 100.0), _bar(1, 110.0)]
        r = run_directional(bars, _AlwaysLong(), initial_capital=100_000.0,
                            taker_fee=0.0005, slippage=0.0)
        self.assertGreaterEqual(r.trade_count, 1)
        self.assertGreater(r.fees_paid, 0.0)
        self.assertTrue(hasattr(r, "sharpe"))
        self.assertTrue(hasattr(r, "max_drawdown"))


if __name__ == "__main__":
    unittest.main()
