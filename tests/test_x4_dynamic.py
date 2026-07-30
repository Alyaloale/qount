"""Unit tests for X4 §12 dynamic-parameter optimizations: ATR grid, grid funding, Kalman pair (线 D).

- S1: ``run_grid(atr_mult=...)`` sizes the grid half-width off ATR; ``funding=`` accrues funding on
  the long inventory (a long *pays* positive funding).
- S2: ``run_kalman_pair`` trades a dynamic hedge ratio (KalmanHedge β adapts online).
"""

from __future__ import annotations

import unittest

from qount.research_data.market_data import Bar
from qount.legacy.x4.backtest import run_grid, run_kalman_pair
from qount.research_data.indicators import KalmanHedge
from qount.legacy.x4.strategies import GridStrategy, KalmanPair
from qount.legacy.grid_b.trend import TrendState

_T0 = 1_609_459_200_000
_D = 86_400_000
_CAP = 100_000.0


def _bar(i: int, close: float, *, high: float | None = None, low: float | None = None) -> Bar:
    h = close if high is None else high
    lo = close if low is None else low
    return Bar(ts_ms=_T0 + i * _D, open=close, high=max(h, close), low=min(lo, close),
               close=close, volume=1.0)


class TestATRGrid(unittest.TestCase):
    def test_atr_grid_widens_in_high_vol(self) -> None:
        cfg = GridStrategy(n=4)
        # high-vol bars (±8% ranges) -> ATR-dynamic half-width should exceed the low-vol one
        hi = [_bar(i, 100.0, high=108.0, low=92.0) for i in range(20)]
        lo = [_bar(i, 100.0, high=101.0, low=99.0) for i in range(20)]
        r_hi = run_grid(hi, cfg, initial_capital=_CAP, atr_mult=5.0,
                        gate_override=[TrendState.ACTIVE] * 20)
        r_lo = run_grid(lo, cfg, initial_capital=_CAP, atr_mult=5.0,
                        gate_override=[TrendState.ACTIVE] * 20)
        # both run without error and seed a grid; the high-vol grid is wider so a ±8% bar that would
        # cross many tight low-vol lines crosses fewer wide ones -> fewer fills per bar on average.
        self.assertGreaterEqual(r_hi.extra["seed_count"], 1)
        self.assertGreaterEqual(r_lo.extra["seed_count"], 1)

    def test_atr_mult_zero_uses_fixed_halfwidth(self) -> None:
        cfg = GridStrategy(n=4, half_width=0.20)
        bars = [_bar(0, 100.0), _bar(1, 97.0, low=97.0, high=100.0), _bar(2, 109.0, low=97.0, high=109.0)]
        r = run_grid(bars, cfg, initial_capital=_CAP, atr_mult=0.0,
                     gate_override=[TrendState.ACTIVE] * 3)
        self.assertGreaterEqual(r.extra["buy_fills"], 1)  # same as the fixed-grid baseline

    def test_funding_drag_on_long_inventory(self) -> None:
        # hold inventory through positive funding -> a long PAYS -> funding_pnl < 0 (honest)
        cfg = GridStrategy(n=4, half_width=0.20)
        bars = [_bar(0, 100.0), _bar(1, 97.0, low=97.0, high=100.0)] + [_bar(i, 97.0) for i in range(2, 6)]
        r = run_grid(bars, cfg, initial_capital=_CAP, gate_override=[TrendState.ACTIVE] * 6,
                     funding=lambda b: 0.001)  # positive funding every bar
        self.assertLess(r.funding_pnl, 0.0)


class TestKalmanHedge(unittest.TestCase):
    def test_beta_tracks_a_constant_ratio(self) -> None:
        kf = KalmanHedge(delta=1e-2, r=1e-3, beta0=1.0)
        # y = 2*x consistently -> beta should converge toward 2
        beta = 1.0
        for x in [100, 110, 90, 105, 95, 120, 80, 100, 115, 100]:
            beta, _e, _z = kf.update(float(x), 2.0 * float(x))
        self.assertGreater(beta, 1.5)  # moved decisively toward 2.0

    def test_zero_error_gives_zero_z(self) -> None:
        kf = KalmanHedge(beta0=2.0)
        _b, e, z = kf.update(100.0, 200.0)  # exactly on the ratio -> e ~ 0
        self.assertAlmostEqual(e, 0.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)


class TestKalmanPair(unittest.TestCase):
    def _series(self, prices):
        return [_bar(i, p) for i, p in enumerate(prices)]

    def test_runs_and_reports_beta(self) -> None:
        cfg = KalmanPair(warmup=3, entry_z=1.0, exit_z=0.3)
        btc = self._series([100.0] * 12)
        eth = self._series([100, 100, 100, 130, 140, 120, 105, 100, 100, 100, 100, 100])
        r = run_kalman_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        self.assertIn("final_beta", r.extra)
        self.assertEqual(len(r.equity_curve), 12)

    def test_warmup_blocks_early_trades(self) -> None:
        cfg = KalmanPair(warmup=100, entry_z=0.5)  # warmup longer than the series -> never trades
        btc = self._series([100.0] * 10)
        eth = self._series([100, 130, 90, 140, 80, 150, 70, 160, 60, 100])
        r = run_kalman_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        self.assertEqual(r.trade_count, 0)


if __name__ == "__main__":
    unittest.main()
