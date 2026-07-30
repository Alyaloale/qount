"""Unit tests for the X4 top-level portfolio combiner (线 D §13).

Equal-weight and inverse-vol (risk-parity) allocation over strategy equity curves, no look-ahead.
"""

from __future__ import annotations

import unittest

from qount.legacy.x4.portfolio import combine, correlation, sharpe_of


def _curve_from_rets(rets, initial=100_000.0):
    c = [initial]
    for r in rets:
        c.append(c[-1] * (1.0 + r))
    return c


class TestCorrelation(unittest.TestCase):
    def test_identical_is_one(self) -> None:
        a = [0.01, -0.02, 0.03, -0.01]
        self.assertAlmostEqual(correlation(a, a), 1.0, places=6)

    def test_opposite_is_minus_one(self) -> None:
        a = [0.01, -0.02, 0.03, -0.01]
        b = [-x for x in a]
        self.assertAlmostEqual(correlation(a, b), -1.0, places=6)


class TestCombine(unittest.TestCase):
    def test_equal_weight_of_identical_curves_matches(self) -> None:
        c = _curve_from_rets([0.01, 0.02, -0.01, 0.03])
        port = combine({"a": c, "b": c}, scheme="equal")
        for x, y in zip(port, c):
            self.assertAlmostEqual(x, y, places=6)

    def test_equal_weight_diversifies(self) -> None:
        # two anti-correlated sleeves -> the equal-weight blend is far smoother than either
        up_down = _curve_from_rets([0.05, -0.04, 0.05, -0.04, 0.05])
        down_up = _curve_from_rets([-0.04, 0.05, -0.04, 0.05, -0.04])
        port = combine({"a": up_down, "b": down_up}, scheme="equal")
        # portfolio per-bar swings are smaller than the components'
        self.assertLess(max(port) - min(port), max(up_down) - min(up_down))

    def test_inverse_vol_underweights_the_noisy_sleeve(self) -> None:
        # calm sleeve (tiny steady gains) + wild sleeve (big swings): inverse-vol leans calm, so its
        # blended curve is SMOOTHER (smaller peak-to-trough) than the equal-weight blend.
        calm = _curve_from_rets([0.001] * 60)
        wild = _curve_from_rets([0.10, -0.09] * 30)
        eq = combine({"calm": calm, "wild": wild}, scheme="equal", vol_lookback=10)
        iv = combine({"calm": calm, "wild": wild}, scheme="inverse_vol", vol_lookback=10)
        self.assertLess(max(iv) - min(iv), max(eq) - min(eq))  # inverse-vol = smoother

    def test_length_and_initial(self) -> None:
        c = _curve_from_rets([0.01, 0.02, 0.03])
        port = combine({"a": c}, initial_capital=50_000.0)
        self.assertEqual(len(port), len(c))
        self.assertEqual(port[0], 50_000.0)

    def test_mismatched_lengths_raise(self) -> None:
        with self.assertRaises(ValueError):
            combine({"a": [1, 2, 3], "b": [1, 2]})


class TestSharpeHelper(unittest.TestCase):
    def test_sharpe_positive_for_steady_gains(self) -> None:
        # positive mean with some variation (constant returns have zero vol -> undefined Sharpe)
        c = _curve_from_rets([0.01, 0.005, 0.012, 0.003, 0.009] * 10)
        self.assertGreater(sharpe_of(c, periods_per_year=365.0), 0.0)


if __name__ == "__main__":
    unittest.main()
