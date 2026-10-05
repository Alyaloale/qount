"""Independent cash/units identities for the offline fee model."""

import unittest

from qount.research_data.replay_fees import trade_to_target


class ReplayFeeTests(unittest.TestCase):
    def test_cash_purchase_closed_form(self):
        ratio, turnover = trade_to_target({}, {"A": 0.6}, 50)
        self.assertAlmostEqual(ratio, 1 / (1 + 0.005 * 0.6))
        self.assertAlmostEqual(turnover, ratio * 0.6)
        self.assertAlmostEqual(1 - ratio * 0.6 - 0.005 * turnover, ratio * 0.4)

    def test_full_rotation_cash_and_units(self):
        ratio, turnover = trade_to_target({"A": 0.2, "B": 0.8}, {"C": 0.2, "B": 0.8}, 40)
        buys = ratio * 0.2
        sells = 0.2 + 0.8 - ratio * 0.8
        self.assertAlmostEqual(turnover, buys + sells)
        self.assertAlmostEqual(sells - buys, 0.004 * turnover)
        self.assertAlmostEqual(ratio, 1 - 0.004 * turnover)

    def test_partial_sale_conserves_cash(self):
        old = {"A": 0.7}
        ratio, turnover = trade_to_target(old, {"A": 0.4}, 50)
        actual_sale = 0.7 - ratio * 0.4
        cash_after = 0.3 + actual_sale - actual_sale * 0.005
        self.assertAlmostEqual(turnover, actual_sale)
        self.assertAlmostEqual(cash_after, ratio * 0.6)

    def test_approximation_is_explicit(self):
        self.assertEqual(trade_to_target({}, {"A": 1.0}, 50, exact=False), (0.995, 1.0))
        self.assertAlmostEqual(trade_to_target({}, {"A": 1.0}, 50)[0], 1 / 1.005)

    def test_rejects_invalid_financing(self):
        for pre, target, cost in (({}, {"A": 1.1}, 50), ({"A": -0.1}, {}, 50), ({}, {}, float("nan"))):
            with self.assertRaises(ValueError):
                trade_to_target(pre, target, cost)
