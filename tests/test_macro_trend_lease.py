"""Continuation must preserve lifetime risk, causal prices and the hard deadline."""
import copy
import unittest

from qount.research.binance_etf_leverage import replay
from qount.research.macro_trend_lease import review_profitable_trend
import test_binance_macro_funding_lease as lease_fixture


class TestMacroTrendLease(unittest.TestCase):
    def review(self, *, price=101, **updates):
        order = dict(quantity=1, entry_price=100, entry_fee=.05, funding=-.1,
                     stop=95, margin_usdt=20, risk_budget_usdt=15,
                     funding_adverse_paid=.1, funding_cost_cap_usdt=1,
                     tactical_setup="breakout")
        order.update(updates)
        return review_profitable_trend(order, now=1000, price=price, equity=100, cash=100,
            reserve=.001, hours=168, eligible=True, fee=.0005, slip=.0025,
            risk_fraction=.25, gap=.03)

    def test_small_gross_gain_is_not_enough_to_cover_paid_and_exit_costs(self):
        result = self.review(price=100.1)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "lease_trend_profit_not_covered")
        self.assertLess(result["known_net_exit_estimate"], 0)
        self.assertTrue(self.review(price=101)["allowed"])

    def test_profit_cannot_bypass_lifetime_funding_or_risk_limits(self):
        result = self.review(price=110, funding_adverse_paid=.99)
        self.assertEqual(result["reason"], "lease_cost_budget")
        self.assertFalse(result["allowed"])
        self.assertEqual(self.review(price=101, risk_budget_usdt=1)["reason"], "lease_risk_budget")

    def test_mean_reversion_policy_and_inputs_are_unchanged(self):
        result = self.review(price=100, tactical_setup="mean_reversion")
        self.assertTrue(result["allowed"])
        self.assertNotIn("known_net_exit_estimate", result)

    def test_optional_trend_lease_preserves_default_and_hard_twenty_one_day_cap(self):
        data, features = lease_fixture.TestFundingLease().fixture(extend=True)
        for rows in features.values():
            for row in rows:
                row["tactical_setup"] = "breakout"
        before = copy.deepcopy((data, features))
        parameters = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.2,
            account_controls=False, funding_policy="debit_stress", sizing_gap_reserve=.03,
            tactical_setup_policies={s: dict(max_hold_hours=504, hold_feature="hold_tactical")
                for s in ("breakout", "pullback", "mean_reversion")},
            funding_lease_hours=168, funding_lease_budget="risk")
        default = replay(data, features, **parameters)
        explicit = replay(data, features, funding_lease_setups=("mean_reversion",), **parameters)
        self.assertEqual(default, explicit)
        trend = replay(data, features, funding_lease_setups=("breakout", "pullback", "mean_reversion"), **parameters)
        first = trend["trades"][0]
        self.assertEqual(first["funding_reserve_hours"], 168)
        self.assertEqual(first["exit_time"]-first["entry_time"], 504*3600)
        self.assertEqual([r["time"]-first["entry_time"] for r in first["funding_lease_reviews"]], [168*3600, 336*3600])
        self.assertEqual((data, features), before)

    def test_invalid_scope_is_rejected(self):
        data, features = lease_fixture.TestFundingLease().fixture()
        for setups in ((), ("unknown",), ("breakout", "breakout"), "breakout"):
            with self.assertRaisesRegex(ValueError, "invalid_funding_lease_setups"):
                replay(data, features, funding_lease_setups=setups)


if __name__ == "__main__":
    unittest.main()
