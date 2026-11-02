import unittest
import test_binance_macro_funding_lease as lease_fixture

from qount.research.macro_topup import topup_quote, verify_topup_replay, review_topup_lease
from qount.strategies.macro_funding import funding_reserve


class MacroTopupTest(unittest.TestCase):
    def quote(self, *, position=None, **extra):
        pos = dict(quantity=1., entry_price=100., stop=90., margin_usdt=20., leverage=5,
            risk_budget_usdt=50., funding_adverse_paid=0., funding_cost_cap_usdt=10.)
        pos.update(position or {})
        rule = dict(filters=[dict(filterType="PRICE_FILTER", tickSize="0.01"),
            dict(filterType="LOT_SIZE", stepSize="0.01", minQty="0.01", maxQty="1000"),
            dict(filterType="MIN_NOTIONAL", notional="5")],
            leverage_brackets=[dict(notionalFloor=0, notionalCap=10000, initialLeverage=50, maintMarginRatio=.01)])
        params = dict(now=1000, reserve_hours=168, reference=100., equity=100., cash=100., reserve=.001,
            gate_reserve=.001, liquidity=10., risk_fraction=.25)
        params.update(extra)
        return topup_quote(pos, rule, **params)

    def test_feasible_quote_respects_original_budget_cash_and_funding(self):
        r = self.quote()
        self.assertTrue(r["allowed"])
        self.assertLessEqual(r["joint_stress_risk"], r["effective_risk_budget"]+1e-8)
        self.assertLessEqual(r["effective_risk_budget"], r["original_risk_budget"])
        self.assertLessEqual(r["joint_margin"]+r["future_funding_reserve"]+r["incremental_entry_fee"], 100+1e-8)
        self.assertGreaterEqual(r["additional_notional"], 5)

    def test_insufficient_headroom_cannot_ignore_increment_order_minimum(self):
        r = self.quote(position=dict(risk_budget_usdt=13.5))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "risk_headroom_below_minimum_increment")
        self.assertGreater(r["minimum_increment_stress"], r["risk_headroom"])

    def test_old_stop_profit_cannot_offset_new_lot_loss(self):
        r = self.quote(position=dict(entry_price=80., margin_usdt=16., risk_budget_usdt=1.))
        self.assertFalse(r["allowed"])
        self.assertGreater(r["increment_stress_per_unit"], 10.)

    def test_unrealized_profit_is_not_cash_for_additional_margin(self):
        r = self.quote(equity=10000., cash=20.11)
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "cash_margin_funding")

    def test_original_funding_cost_cap_is_never_refreshed(self):
        r = self.quote(position=dict(funding_cost_cap_usdt=.11))
        self.assertTrue(r["allowed"])
        self.assertLessEqual(r["future_funding_reserve"], .11+1e-9)
        self.assertLessEqual(r["quantity"], .1+1e-9)

    def test_liquidity_is_incremental_order_capacity(self):
        r = self.quote(liquidity=.1)
        self.assertTrue(r["allowed"])
        self.assertAlmostEqual(r["quantity"], .1)
        self.assertAlmostEqual(r["total_quantity"], 1.1)

    def test_post_fill_risk_budget_includes_mark_loss_and_both_fees(self):
        r = self.quote(mark_price=95.)
        self.assertTrue(r["allowed"])
        q = r["quantity"]
        after = 100+q*(95-r["entry_price"])-r["incremental_entry_fee"]-q*95*.0005
        self.assertAlmostEqual(r["effective_risk_budget"], .25*after)

    def simulate(self, data=None, features=None, policy_enabled=True):
        fixture = lease_fixture.TestFundingLease()
        if data is None:
            data, features = fixture.fixture(extend=True)
        def policy(pos, f, now, equity, cash, reference):
            if f["available"] <= pos["feature_available"]:
                return None
            hours = (pos["funding_lease_deadline"]-now)/3600
            return topup_quote(pos, data[pos["symbol"]]["rule"], now=now, reserve_hours=hours,
                reference=reference, equity=equity, cash=cash,
                reserve=funding_reserve(data[pos["symbol"]]["funding"], now, hours, "debit_stress"),
                gate_reserve=funding_reserve(data[pos["symbol"]]["funding"], now, 168, "debit_stress"),
                liquidity=.1, fee=.0005, slip=.0005, risk_fraction=.2, liquidation_multiple=3.)
        r = fixture.run_lease(data, features, capital=100., funding_lease_budget="risk",
            funding_lease_entry_utilization=.5, mr_topup_policy=policy if policy_enabled else None)
        verify_topup_replay(r, data, dict(capital=100., fee=.0005))
        return r, data, features

    def test_full_replay_keeps_original_deadlines_and_budget_after_addition(self):
        r, _, _ = self.simulate()
        t = next(t for t in r["trades"] if t.get("topups"))
        self.assertEqual(len(t["topups"]), 1)
        self.assertEqual(t["exit_reason"], "time_exit")
        self.assertEqual(t["exit_time"]-t["entry_time"], 504*3600)
        self.assertEqual([v["time"]-t["entry_time"] for v in t["funding_lease_reviews"]], [168*3600,336*3600])
        self.assertAlmostEqual(sum(l["quantity"]*l["entry_price"] for l in t["entry_lots"]), t["quantity"]*t["entry_price"])
        self.assertEqual(t["topups"][0]["stop"], t["initial_stop"])

    def test_added_lot_is_not_charged_funding_before_its_entry(self):
        original, data, features = self.simulate()
        t = next(t for t in original["trades"] if t.get("topups"))
        before = next(row for row in data[t["symbol"]]["funding"] if
            t["entry_time"]*1000 < int(row["fundingTime"]) < t["topups"][0]["time"]*1000)
        before["fundingRate"] = "0.0001"
        r, _, _ = self.simulate(data, features)
        actual = next(t for t in r["trades"] if t.get("topups"))
        self.assertAlmostEqual(actual["funding"], -actual["entry_lots"][0]["quantity"]*.01)

    def test_per_lot_financial_review_rejects_unrealized_profit_offset(self):
        position = dict(quantity=2., entry_price=100., margin_usdt=40., leverage=5,
            stop=100., risk_budget_usdt=2., funding_adverse_paid=0., funding_cost_cap_usdt=10.,
            entry_lots=[dict(quantity=1., entry_price=90.), dict(quantity=1., entry_price=110.)])
        r = review_topup_lease(position, now=1000, price=110., equity=100., cash=100., reserve=.001,
            hours=168, eligible=True, fee=.0005, slip=.0025, risk_fraction=.25, gap=0.)
        self.assertFalse(r["allowed"])
        self.assertGreater(r["stress_risk"], 10.)


if __name__ == "__main__":
    unittest.main()
