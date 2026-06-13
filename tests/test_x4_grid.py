"""Unit tests for the X4 S1-GRID ladder driver (线 D). Plan: §2 S1, §3.

Reuses ``grid.engine.GridLadder`` + ``grid.trend`` SMA200 gate. Mechanics (buy on dip / sell on
rise / DERISK sell-only / PAUSED liquidate) are tested with an explicit ``gate_override`` so the
fill logic is decoupled from the trend filter; a separate test checks the real SMA gate wiring.
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.grid.trend import TrendState
from qount.x4.backtest import run_grid
from qount.x4.strategies import GridStrategy

_T0 = 1_609_459_200_000
_H = 3_600_000
_CAP = 100_000.0


def _bar(i: int, close: float, *, high: float | None = None, low: float | None = None) -> Bar:
    h = close if high is None else high
    lo = close if low is None else low
    return Bar(ts_ms=_T0 + i * _H, open=close, high=max(h, close), low=min(lo, close),
               close=close, volume=1.0)


# coarse 4-grid over +-20% => buy lines below 100 fill on dips, sells above on rallies
_CFG = GridStrategy(n=4, half_width=0.20)


class TestGridMechanics(unittest.TestCase):
    def test_seed_then_round_trip_books_profit(self) -> None:
        # seed @100; dip to 97 fills a buy ~98; rally to 109 fills its sell ~108.4 => grid profit
        bars = [_bar(0, 100.0), _bar(1, 97.0, low=97.0, high=100.0), _bar(2, 109.0, low=97.0, high=109.0)]
        r = run_grid(bars, _CFG, initial_capital=_CAP, gate_override=[TrendState.ACTIVE] * 3)
        self.assertGreaterEqual(r.extra["buy_fills"], 1)
        self.assertGreaterEqual(r.extra["sell_fills"], 1)
        self.assertGreater(r.equity_curve[-1], _CAP)  # realized grid spread net of fees

    def test_monotonic_rise_buys_nothing(self) -> None:
        # price only ever rises from the seed: resting buys (below seed) never fill
        bars = [_bar(i, 100.0 + i) for i in range(6)]
        r = run_grid(bars, _CFG, initial_capital=_CAP, gate_override=[TrendState.ACTIVE] * 6)
        self.assertEqual(r.extra["buy_fills"], 0)


class TestGridGate(unittest.TestCase):
    def test_derisk_blocks_new_buys(self) -> None:
        bars = [_bar(0, 100.0), _bar(1, 97.0, low=97.0, high=100.0)]
        active = run_grid(bars, _CFG, initial_capital=_CAP,
                          gate_override=[TrendState.ACTIVE, TrendState.ACTIVE])
        derisk = run_grid(bars, _CFG, initial_capital=_CAP,
                          gate_override=[TrendState.ACTIVE, TrendState.DERISK])
        self.assertGreaterEqual(active.extra["buy_fills"], 1)
        self.assertEqual(derisk.extra["buy_fills"], 0)  # DERISK = sell-only, no new buys

    def test_paused_liquidates_inventory_to_cash(self) -> None:
        # seed, buy on dip (inventory > 0), then PAUSED => liquidate at close, flat thereafter
        bars = [_bar(0, 100.0), _bar(1, 97.0, low=97.0, high=100.0), _bar(2, 90.0)]
        r = run_grid(bars, _CFG, initial_capital=_CAP,
                     gate_override=[TrendState.ACTIVE, TrendState.ACTIVE, TrendState.PAUSED])
        self.assertGreaterEqual(r.extra["liquidations"], 1)
        self.assertAlmostEqual(r.extra["final_inventory_base"], 0.0)

    def test_real_sma_gate_seeds_on_uptrend(self) -> None:
        # rising closes confirm ACTIVE under a short SMA, so the grid actually arms
        cfg = GridStrategy(n=4, half_width=0.20, sma_window=3, confirm_bars=1)
        bars = [_bar(i, 100.0 + 2 * i) for i in range(8)]
        r = run_grid(bars, cfg, initial_capital=_CAP)
        self.assertGreaterEqual(r.extra["seed_count"], 1)


if __name__ == "__main__":
    unittest.main()
