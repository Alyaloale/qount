"""Causal research risk reductions retain cost gates and lifetime lease caps."""
import unittest

import test_binance_macro_attack as attack_fixture
import test_binance_macro_funding_lease as lease_fixture
from qount.research.binance_etf_leverage import replay


class TestMacroEntryRisk(unittest.TestCase):
    def params(self):
        return dict(strategy="macro_tactical", gross_cap=20, risk_fraction=.2,
                    account_controls=False, exchange_leverage=50,
                    liquidation_stop_multiple=1.25, sizing_gap_reserve=.03)

    def contexts(self, data, multiplier):
        return {(s, b.t): dict(asof=b.t, multiplier=multiplier) for s, d in data.items() for b in d["trade"]}

    def test_unit_controls_reproduce_default_and_half_reduces_risk(self):
        data, features = attack_fixture.macro_fixture()
        baseline = replay(data, features, **self.params())
        self.assertEqual(baseline, replay(data, features, entry_risk_controls=self.contexts(data, 1), **self.params()))
        reduced = replay(data, features, entry_risk_controls=self.contexts(data, .5), **self.params())
        self.assertTrue(reduced["trades"])
        self.assertLess(reduced["trades"][0]["quantity"], baseline["trades"][0]["quantity"])
        for t in reduced["trades"]:
            self.assertAlmostEqual(t["risk_budget_usdt"], .1*t["equity_before_entry"])
            self.assertLessEqual(t["stress_risk_usdt"], t["risk_budget_usdt"]+1e-9)

    def test_capacity_bound_order_is_not_forced_to_half_quantity(self):
        data, features = attack_fixture.macro_fixture()
        caps = {(s, b.t): dict(asof=b.t-60, quantity_cap=.06) for s, d in data.items() for b in d["trade"]}
        args = dict(self.params(), entry_liquidity_caps=caps)
        a = replay(data, features, **args)
        b = replay(data, features, entry_risk_controls=self.contexts(data, .5), **args)
        self.assertTrue(a["trades"] and b["trades"])
        self.assertEqual(a["trades"][0]["quantity"], b["trades"][0]["quantity"])
        costly = dict(args, fee=.002, slip=.004)
        self.assertFalse(replay(data, features, entry_risk_controls=self.contexts(data, .5), **costly)["trades"])

    def test_missing_stale_future_and_invalid_controls(self):
        data, features = attack_fixture.macro_fixture()
        self.assertFalse(replay(data, features, entry_risk_controls={}, **self.params())["trades"])
        contexts = self.contexts(data, .5)
        for key, context in contexts.items():
            context["asof"] = key[1]-3601
        self.assertFalse(replay(data, features, entry_risk_controls=contexts, **self.params())["trades"])
        for key, context in contexts.items():
            context["asof"] = key[1]+1
        with self.assertRaisesRegex(ValueError, "future_entry_risk"):
            replay(data, features, entry_risk_controls=contexts, **self.params())
        for multiplier in (0, -.5, 1.01, True, None, float("nan")):
            with self.subTest(multiplier=multiplier), self.assertRaisesRegex(ValueError, "invalid_entry_risk"):
                replay(data, features, entry_risk_controls=self.contexts(data, multiplier), **self.params())
        with self.assertRaisesRegex(ValueError, "require_tactical"):
            replay(data, features, strategy="macro_hybrid", entry_risk_controls={})

    def test_lease_renewals_never_restore_original_full_budget(self):
        fixture = lease_fixture.TestFundingLease()
        data, features = fixture.fixture(extend=True)
        result = fixture.run_lease(data, features, funding_lease_budget="risk",
                                   entry_risk_controls=self.contexts(data, .5))
        self.assertTrue(result["trades"])
        t = result["trades"][0]
        self.assertTrue(t["funding_lease_reviews"])
        self.assertAlmostEqual(t["risk_budget_usdt"], .1*t["equity_before_entry"])
        for r in t["funding_lease_reviews"]:
            self.assertLessEqual(r["risk_budget"], t["risk_budget_usdt"]+1e-9)
            self.assertEqual(r["funding_cost_cap"], t["funding_cost_cap_usdt"])
        self.assertAlmostEqual(10+sum(t["net_pnl"] for t in result["trades"]), result["summary"]["final_equity"])


if __name__ == "__main__":
    unittest.main()
