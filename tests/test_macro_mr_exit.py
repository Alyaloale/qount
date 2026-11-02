import unittest
import test_binance_macro_funding_lease as lease_fixture

from qount.research.macro_mr_exit import RejectionLowHolding, holding_profiles
from qount.research_data.bars import Bar


class MacroMRExitTest(unittest.TestCase):
    def fixture(self):
        prices = {s: [Bar(t, c, c, c, c) for t, c in enumerate(values)] for s, values in {
            "SPYUSDT": [100, 101, 99, 100, 101],
            "IWMUSDT": [100, 103, 101, 102, 103],
            "CLUSDT": [100, 103, 101, 102, 103]}.items()}
        features = {s: [dict(available=t, date=str(t), hold_structural=flag,
            entry_tactical=True, hold_tactical=False, marker=s) for t, flag in enumerate(
            [True, True, False, False, False])] for s in prices}
        return prices, features

    def test_only_two_distinct_closes_confirm_failure(self):
        prices, features = self.fixture()
        result, _ = holding_profiles(prices, features)
        self.assertEqual([f["hold_structural"] for f in result["two_closes"]["IWMUSDT"]],
                         [True, True, True, False, False])
        self.assertEqual(result["control"], features)

    def test_equities_retain_spy_price_veto_commodities_use_own_price(self):
        prices, features = self.fixture()
        result, _ = holding_profiles(prices, features)
        self.assertFalse(result["price200"]["IWMUSDT"][2]["hold_structural"])
        self.assertTrue(result["price200"]["CLUSDT"][2]["hold_structural"])

    def test_future_prices_and_features_do_not_change_prefix(self):
        prices, features = self.fixture()
        result, diagnostics = holding_profiles(prices, features)
        before, prefix_diagnostics = holding_profiles({s: b[:3] for s, b in prices.items()},
                                                      {s: f[:3] for s, f in features.items()})
        for mode in result:
            for symbol in features:
                self.assertEqual(before[mode][symbol], result[mode][symbol][:3])
        self.assertEqual(prefix_diagnostics, [r for r in diagnostics if r["available"] < 3])

    def test_rejection_low_uses_frozen_entry_candle_and_completed_close(self):
        bars = {s: [Bar(0, 100, 103, 98, 101), Bar(1, 101, 110, 90, 102),
                    Bar(2, 102, 103, 94, 97)] for s in ("SPYUSDT", "IWMUSDT")}
        rule = RejectionLowHolding(bars)
        pos = dict(symbol="IWMUSDT", feature_available=0, entry_time=.5)
        self.assertTrue(rule(pos, dict(available=1), 1.5, False))
        self.assertFalse(rule(pos, dict(available=2), 2.5, True))
        with self.assertRaisesRegex(ValueError, "noncausal"):
            rule(pos, dict(available=2), 2, True)

    def test_rejection_market_failure_applies_only_to_equities(self):
        bars, _ = self.fixture()
        rule = RejectionLowHolding(bars, systemic=True)
        for s, expected in (("IWMUSDT", False), ("CLUSDT", True)):
            self.assertEqual(rule(dict(symbol=s, feature_available=0, entry_time=.5),
                                  dict(available=2), 2.5, True), expected)

    def test_identity_holding_rule_preserves_full_native_lease_result(self):
        fixture = lease_fixture.TestFundingLease()
        data, features = fixture.fixture(extend=True)
        baseline = fixture.run_lease(data, features, funding_lease_budget="risk")
        calls = []
        def identity(position, feature, now, original):
            calls.append(now)
            return original
        actual = fixture.run_lease(data, features, funding_lease_budget="risk", mr_holding_rule=identity)
        self.assertEqual(actual, baseline)
        self.assertTrue(all(r["time"] in calls for t in actual["trades"] for r in t["funding_lease_reviews"]))

    def test_invalid_holding_result_fails_instead_of_allowing_risk(self):
        fixture = lease_fixture.TestFundingLease()
        data, features = fixture.fixture(extend=True)
        with self.assertRaisesRegex(ValueError, "invalid_mr_holding_result"):
            fixture.run_lease(data, features, mr_holding_rule=lambda *args: 1)


if __name__ == "__main__":
    unittest.main()
