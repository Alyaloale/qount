"""Unit tests for RV-C de-multiple-testing stats: DSR + PBO/CSCV (线 C). Plan §3 (杀手3)."""

from __future__ import annotations

import unittest

from qount.research_data.metrics import deflated_sharpe_ratio
from qount.research_data.metrics import expected_max_sharpe
from qount.research_data.metrics import pbo_cscv
from qount.research_data.metrics import returns_from_curve
from qount.research_data.metrics import sharpe


class TestSharpe(unittest.TestCase):
    def test_known_sharpe(self) -> None:
        # returns with mean 1, sample std 1 (values 0,1,2 -> mean 1, ddof1 std 1) -> SR 1.0
        self.assertAlmostEqual(sharpe([0.0, 1.0, 2.0]), 1.0)

    def test_annualized(self) -> None:
        sr = sharpe([0.0, 1.0, 2.0])
        self.assertAlmostEqual(sharpe([0.0, 1.0, 2.0], periods_per_year=365.0), sr * 365.0 ** 0.5)

    def test_zero_variance(self) -> None:
        self.assertEqual(sharpe([0.5, 0.5, 0.5]), 0.0)


class TestExpectedMaxSharpe(unittest.TestCase):
    def test_one_trial_or_zero_var_is_zero(self) -> None:
        self.assertEqual(expected_max_sharpe(1, 0.04), 0.0)
        self.assertEqual(expected_max_sharpe(10, 0.0), 0.0)

    def test_increases_with_trials_and_var(self) -> None:
        self.assertGreater(expected_max_sharpe(50, 0.04), expected_max_sharpe(5, 0.04))
        self.assertGreater(expected_max_sharpe(10, 0.09), expected_max_sharpe(10, 0.01))


class TestDeflatedSharpe(unittest.TestCase):
    def test_observed_equals_benchmark_is_half(self) -> None:
        dsr = deflated_sharpe_ratio(0.10, n_obs=500, sr_benchmark=0.10)
        self.assertAlmostEqual(dsr, 0.5, places=6)

    def test_strong_edge_near_one(self) -> None:
        # observed SR well above benchmark over a long sample -> DSR -> ~1
        dsr = deflated_sharpe_ratio(0.20, n_obs=1000, sr_benchmark=0.05)
        self.assertGreater(dsr, 0.99)

    def test_below_benchmark_is_small(self) -> None:
        dsr = deflated_sharpe_ratio(0.02, n_obs=1000, sr_benchmark=0.10)
        self.assertLess(dsr, 0.05)

    def test_fat_tails_lower_dsr(self) -> None:
        base = deflated_sharpe_ratio(0.15, n_obs=800, sr_benchmark=0.05, skew=0.0, kurt=3.0)
        fat = deflated_sharpe_ratio(0.15, n_obs=800, sr_benchmark=0.05, skew=-1.0, kurt=8.0)
        self.assertLess(fat, base)  # negative skew + fat kurt deflate the confidence


class TestPBO(unittest.TestCase):
    def test_robust_selection_low_pbo(self) -> None:
        # config 0 dominates every block; others are ~0 noise -> IS-best == OOS-best -> PBO ~0
        cfg0 = [0.02 + (0.001 if i % 2 else -0.001) for i in range(40)]
        noise = [[(0.001 if (i + c) % 2 else -0.001) for i in range(40)] for c in range(3)]
        cols = [cfg0, *noise]
        self.assertLess(pbo_cscv(cols, n_splits=4), 0.1)

    def test_overfit_selection_high_pbo(self) -> None:
        # each config is best in one half and worst in the other -> IS-best -> OOS-worst -> PBO high
        cols = []
        for c in range(4):
            block0 = [c + (0.1 if i % 2 else -0.1) for i in range(4)]    # mean c
            block1 = [-c + (0.1 if i % 2 else -0.1) for i in range(4)]   # mean -c
            cols.append(block0 + block1)
        self.assertGreater(pbo_cscv(cols, n_splits=2), 0.5)

    def test_validates_inputs(self) -> None:
        with self.assertRaises(ValueError):
            pbo_cscv([[1.0, 2.0]], n_splits=2)          # < 2 configs
        with self.assertRaises(ValueError):
            pbo_cscv([[1.0, 2.0], [3.0, 4.0]], n_splits=3)  # odd splits


class TestReturnsFromCurve(unittest.TestCase):
    def test_simple_returns(self) -> None:
        r = returns_from_curve([100.0, 110.0, 99.0])
        self.assertAlmostEqual(r[0], 0.10)
        self.assertAlmostEqual(r[1], -0.10)

    def test_drops_nonpositive_equity(self) -> None:
        r = returns_from_curve([100.0, 0.0, -5.0, 10.0])
        self.assertEqual(len(r), 1)  # only the 100->0 step has prev>0


if __name__ == "__main__":
    unittest.main()
