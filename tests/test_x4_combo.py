"""Tests for the C×D combined-book kill-test (src/qount/legacy/x4/combo.py)."""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qount.legacy.x4.combo import align_curves, combine_fixed, kill_verdict


class TestAlignCurves(unittest.TestCase):
    def test_intersects_timestamps_and_rebases(self):
        # trend covers ts 1..4, carry covers ts 2..5 -> common = 2,3,4
        trend = ([1, 2, 3, 4], [100.0, 110.0, 121.0, 133.0])
        carry = ([2, 3, 4, 5], [50.0, 55.0, 60.0, 66.0])
        common, out = align_curves({"T": trend, "C": carry}, initial_capital=1000.0)
        self.assertEqual(common, [2, 3, 4])
        # both rebased to 1000 at first common bar (ts=2)
        self.assertAlmostEqual(out["T"][0], 1000.0)
        self.assertAlmostEqual(out["C"][0], 1000.0)
        # trend: 110 -> 121 -> 133 rebased
        self.assertAlmostEqual(out["T"][1], 1000.0 * 121.0 / 110.0)
        self.assertAlmostEqual(out["T"][2], 1000.0 * 133.0 / 110.0)
        # carry at common ts 2,3,4 = 50,55,60 (ts=5 dropped); base 50
        self.assertAlmostEqual(out["C"][1], 1000.0 * 55.0 / 50.0)
        self.assertAlmostEqual(out["C"][2], 1000.0 * 60.0 / 50.0)

    def test_raises_on_no_common_span(self):
        with self.assertRaises(ValueError):
            align_curves({"A": ([1, 2], [1.0, 1.0]), "B": ([5, 6], [1.0, 1.0])})

    def test_raises_on_length_mismatch(self):
        with self.assertRaises(ValueError):
            align_curves({"A": ([1, 2, 3], [1.0, 1.0])})


class TestCombineFixed(unittest.TestCase):
    def test_full_weight_one_sleeve_reproduces_it(self):
        trend = [100.0, 110.0, 99.0, 108.9]
        carry = [100.0, 101.0, 100.0, 100.0]
        port = combine_fixed({"T": trend, "C": carry}, {"T": 1.0, "C": 0.0},
                             initial_capital=100.0)
        # 100% trend -> same returns as trend
        for a, b in zip(port, trend):
            self.assertAlmostEqual(a, b)

    def test_known_two_asset_blend(self):
        # T: +10% then -10%; C: 0% flat. 50/50 -> +5% then -5%.
        trend = [100.0, 110.0, 99.0]
        carry = [100.0, 100.0, 100.0]
        port = combine_fixed({"T": trend, "C": carry}, {"T": 0.5, "C": 0.5},
                             initial_capital=100.0)
        self.assertAlmostEqual(port[1], 105.0)
        self.assertAlmostEqual(port[2], 105.0 * 0.95)

    def test_anticorrelated_sleeves_cut_volatility(self):
        # perfectly anti-correlated sleeves -> blended path is far smoother (the ballast thesis)
        trend = [100.0]
        carry = [100.0]
        for r in (0.1, -0.1, 0.1, -0.1, 0.1, -0.1):
            trend.append(trend[-1] * (1 + r))
            carry.append(carry[-1] * (1 - r))
        port = combine_fixed({"T": trend, "C": carry}, {"T": 0.5, "C": 0.5},
                             initial_capital=100.0)
        # blended return each bar ~ 0 -> std of port returns < std of trend returns
        def _std(c):
            rs = [c[i + 1] / c[i] - 1 for i in range(len(c) - 1)]
            m = sum(rs) / len(rs)
            return math.sqrt(sum((x - m) ** 2 for x in rs) / len(rs))
        self.assertLess(_std(port), _std(trend))

    def test_missing_weight_raises(self):
        with self.assertRaises(ValueError):
            combine_fixed({"T": [1.0, 1.0], "C": [1.0, 1.0]}, {"T": 1.0})


class TestKillVerdict(unittest.TestCase):
    def test_ballast_sleeve_passes(self):
        # trend: volatile up-down; carry: steady low-vol up -> combo smoother & higher Sharpe
        trend = [100.0]
        carry = [100.0]
        for i in range(40):
            trend.append(trend[-1] * (1 + (0.05 if i % 2 == 0 else -0.03)))
            carry.append(carry[-1] * 1.002)
        aligned_combo = combine_fixed({"T": trend, "C": carry}, {"T": 0.6, "C": 0.4},
                                      initial_capital=100.0)
        v = kill_verdict(aligned_combo, trend)
        self.assertTrue(v["sharpe_ok"])
        self.assertTrue(v["dd_ok"])
        self.assertEqual(v["verdict"], "PASS")

    def test_pure_dilution_without_improvement_fails(self):
        # carry identical to trend (corr=1) -> no diversification, combo == trend -> not strictly better
        trend = [100.0, 110.0, 99.0, 108.9, 120.0]
        v = kill_verdict(trend, trend)
        self.assertFalse(v["sharpe_ok"])  # equal, not greater
        self.assertEqual(v["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
