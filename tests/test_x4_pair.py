"""Unit tests for the X4 S2-PAIR two-leg z-score driver (线 D). Plan: §2 S2, §3.

Long one leg / short the other on ETH/BTC ratio z-score extremes, dollar-neutral. Tests pin
warm-up flatness (no look-ahead), entry sign, dollar-neutral sizing, and mean-reversion profit.
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import run_pair
from qount.x4.strategies import PairStrategy

_T0 = 1_609_459_200_000
_H = 3_600_000
_CAP = 100_000.0


def _bar(i: int, close: float) -> Bar:
    return Bar(ts_ms=_T0 + i * _H, open=close, high=close, low=close, close=close, volume=1.0)


def _series(prices: list[float]) -> list[Bar]:
    return [_bar(i, p) for i, p in enumerate(prices)]


class TestPairWarmup(unittest.TestCase):
    def test_below_window_is_flat(self) -> None:
        cfg = PairStrategy(window=5, entry_z=1.0)
        btc = _series([100.0] * 3)
        eth = _series([100.0] * 3)
        r = run_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        self.assertEqual(r.trade_count, 0)
        self.assertEqual(r.equity_curve[-1], _CAP)


class TestPairEntry(unittest.TestCase):
    def test_high_ratio_shorts_eth_longs_btc(self) -> None:
        cfg = PairStrategy(window=5, entry_z=1.0, exit_z=0.3)
        btc = _series([100.0] * 6)
        eth = _series([100.0, 100.0, 100.0, 100.0, 100.0, 140.0])  # spike => ratio high
        r = run_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        self.assertGreater(r.extra["btc_base"], 0.0)   # long BTC
        self.assertLess(r.extra["eth_base"], 0.0)      # short ETH

    def test_entry_is_dollar_neutral(self) -> None:
        cfg = PairStrategy(window=5, entry_z=1.0, exit_z=0.3, leg_leverage=1.0)
        btc = _series([100.0] * 6)
        eth = _series([100.0, 100.0, 100.0, 100.0, 100.0, 140.0])
        r = run_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        btc_notional = abs(r.extra["btc_base"]) * 100.0
        eth_notional = abs(r.extra["eth_base"]) * 140.0
        self.assertAlmostEqual(btc_notional, eth_notional, delta=1.0)


class TestPairMeanReversion(unittest.TestCase):
    def test_reversion_after_entry_books_profit(self) -> None:
        # ratio spikes (enter short-ETH/long-BTC), then ETH falls back to par => short profits
        cfg = PairStrategy(window=5, entry_z=1.0, exit_z=0.3)
        btc = _series([100.0] * 9)
        eth = _series([100.0, 100.0, 100.0, 100.0, 100.0, 140.0, 120.0, 105.0, 100.0])
        r = run_pair(btc, eth, cfg, initial_capital=_CAP, taker_fee=0.0, slippage=0.0)
        self.assertGreater(r.equity_curve[-1], _CAP)


if __name__ == "__main__":
    unittest.main()
