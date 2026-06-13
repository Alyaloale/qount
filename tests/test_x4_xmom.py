"""Unit tests for X4 S6-XMOM cross-sectional momentum (线 D §16).

Pure ranking (vol-adjusted momentum + per-symbol SMA gate, no look-ahead) + the rotation driver.
"""

from __future__ import annotations

import unittest

from qount.grid.data import Bar
from qount.x4.backtest import run_cross_sectional
from qount.x4.strategies import cross_sectional_rank

_T0 = 1_609_459_200_000
_D = 86_400_000


def _bars(closes: list[float]) -> list[Bar]:
    return [Bar(ts_ms=_T0 + i * _D, open=c, high=c, low=c, close=c, volume=1.0)
            for i, c in enumerate(closes)]


def _from_rets(rets: list[float], base: float = 100.0) -> list[float]:
    """Closes from a return sequence (gives a well-defined non-zero vol unlike a smooth geom)."""

    c = [base]
    for r in rets:
        c.append(c[-1] * (1.0 + r))
    return c


class TestRank(unittest.TestCase):
    def test_picks_strongest_vol_adj_momentum(self) -> None:
        # all uptrend above SMA, with real (non-zero) vol; STRONG has the best momentum/vol
        strong = _from_rets([0.04, 0.02] * 6)   # mean ~3%, modest vol
        weak = _from_rets([0.008, 0.002] * 6)   # mild drift
        choppy = _from_rets([0.06, -0.045] * 6)  # near-flat drift, big vol -> penalized
        top = cross_sectional_rank({"STRONG": strong, "WEAK": weak, "CHOP": choppy},
                                   12, lookback=5, regime_sma=3, top_k=1)
        self.assertEqual(top, ["STRONG"])

    def test_regime_gate_excludes_below_sma(self) -> None:
        up = _from_rets([0.025, 0.015] * 6)
        down = _from_rets([-0.03, -0.02] * 6)  # below its own SMA
        top = cross_sectional_rank({"UP": up, "DOWN": down}, 12, lookback=5, regime_sma=3, top_k=2)
        self.assertEqual(top, ["UP"])  # DOWN gated out despite being in the universe

    def test_empty_when_nothing_qualifies(self) -> None:
        down = _from_rets([-0.03, -0.02] * 6)
        top = cross_sectional_rank({"A": down, "B": down}, 12, lookback=5, regime_sma=3, top_k=2)
        self.assertEqual(top, [])

    def test_no_lookahead(self) -> None:
        # rank at t uses only closes <= t: appending future bars must not change a past rank
        a = _from_rets([0.025, 0.015] * 12)
        b = _from_rets([0.012, 0.008] * 12)
        r1 = cross_sectional_rank({"A": a, "B": b}, 10, lookback=5, regime_sma=3, top_k=2)
        r2 = cross_sectional_rank({"A": a + [999.0], "B": b + [0.1]}, 10, lookback=5, regime_sma=3, top_k=2)
        self.assertEqual(r1, r2)


class TestRotation(unittest.TestCase):
    def test_rides_the_strong_symbol(self) -> None:
        n = 60
        strong = _bars([100.0 * (1.02 ** i) for i in range(n)])
        flat = _bars([100.0] * n)
        r = run_cross_sectional({"STRONG": strong, "FLAT": flat}, lookback=10, top_k=1,
                                regime_sma=5, rebalance_days=5, initial_capital=100_000.0,
                                taker_fee=0.0, slippage=0.0)
        self.assertGreater(r.equity_curve[-1], 100_000.0)  # rotated into and held STRONG
        self.assertGreaterEqual(r.extra["rebalances"], 1)

    def test_all_cash_when_universe_below_sma(self) -> None:
        n = 60
        down = _bars([100.0 * (0.99 ** i) for i in range(n)])
        r = run_cross_sectional({"A": down, "B": down}, lookback=10, top_k=1, regime_sma=5,
                                rebalance_days=5, initial_capital=100_000.0, taker_fee=0.0005,
                                slippage=0.0002)
        # never holds anything (all gated out) -> equity stays at capital, no losses
        self.assertAlmostEqual(r.equity_curve[-1], 100_000.0, places=2)

    def test_turnover_charges_fees(self) -> None:
        n = 60
        # two symbols alternate leadership so the basket rotates and pays turnover
        a = _bars([100.0 * (1.03 ** i) if i < 30 else 100.0 * (1.03 ** 30) * (0.99 ** (i - 30)) for i in range(n)])
        b = _bars([100.0 * (1.001 ** i) if i < 30 else 100.0 * (1.001 ** 30) * (1.05 ** (i - 30)) for i in range(n)])
        r = run_cross_sectional({"A": a, "B": b}, lookback=10, top_k=1, regime_sma=5,
                                rebalance_days=5, initial_capital=100_000.0, taker_fee=0.0005,
                                slippage=0.0002)
        self.assertGreater(r.fees_paid, 0.0)

    def test_mismatched_lengths_raise(self) -> None:
        with self.assertRaises(ValueError):
            run_cross_sectional({"A": _bars([1, 2, 3]), "B": _bars([1, 2])})


if __name__ == "__main__":
    unittest.main()
