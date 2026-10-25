"""Known-cost protection must be causal, monotone and quantity-aware."""
import copy
import unittest

from qount.research.macro_profit_protection import protect_profit
from qount.strategies.macro_1atr import trailing_update


class TestMacroProfitProtection(unittest.TestCase):
    def position(self, **extra):
        return dict(dict(entry_price=100., entry_fee=.1, funding=-.2, quantity=2.,
                         structural_r=5., highest_close=100., stop=95.), **extra)

    def update(self, p, close, **extra):
        return protect_profit(p, close, 3., .01, fee=.0005, slip=.0025, **extra)

    def test_original_trigger_and_trail_are_exact_when_both_options_off(self):
        p = self.position()
        for close in (103., 106., 110., 109., 113.):
            expected = trailing_update(p, close, 3., .01)
            actual = self.update(p, close)
            self.assertEqual(actual, expected)
            p = actual[0]

    def test_floor_arms_at_completed_one_r_and_covers_known_costs(self):
        p = self.position()
        before, _ = self.update(p, 104.99, cost_floor=True)
        self.assertEqual(before["stop"], 95.)
        after, reason = self.update(p, 105., cost_floor=True)
        self.assertIsNone(reason)
        self.assertTrue(after["cost_floor_armed"])
        q = p["quantity"]
        exit_price = after["stop"]*(1-.0025)
        net = q*(exit_price-p["entry_price"])-p["entry_fee"]-q*exit_price*.0005+p["funding"]
        self.assertGreaterEqual(net, 0)
        self.assertLess(net, q*.011)
        self.assertEqual(p, self.position())

    def test_funding_debits_raise_floor_and_credits_never_lower_it(self):
        p, _ = self.update(self.position(), 106., cost_floor=True)
        old = copy.deepcopy(p)
        p["funding"] = -1.
        higher, _ = self.update(p, 106., cost_floor=True)
        self.assertGreater(higher["stop"], old["stop"])
        higher["funding"] = 1.
        credited, _ = self.update(higher, 106., cost_floor=True)
        self.assertEqual(credited["stop"], higher["stop"])

    def test_armed_floor_survives_price_falling_below_one_r(self):
        p, _ = self.update(self.position(), 105., cost_floor=True)
        held, reason = self.update(p, 103., cost_floor=True)
        self.assertIsNone(reason)
        self.assertTrue(held["cost_floor_armed"])
        self.assertGreaterEqual(held["stop"], p["stop"])

    def test_earlier_trail_does_not_require_two_r_or_loosen_stop(self):
        p = self.position()
        ordinary, _ = self.update(p, 105.)
        early, _ = self.update(p, 105., early_trail=True)
        self.assertEqual(ordinary["stop"], 95.)
        self.assertEqual(early["stop"], 99.)
        later, _ = self.update(early, 104., early_trail=True)
        self.assertGreaterEqual(later["stop"], early["stop"])

    def test_price_already_below_new_floor_requests_exit_instead_of_retroactive_fill(self):
        p = self.position(cost_floor_armed=True, funding=-10.)
        _, reason = self.update(p, 103., cost_floor=True)
        self.assertEqual(reason, "cost_floor_crossed_at_update")


if __name__ == "__main__":
    unittest.main()
