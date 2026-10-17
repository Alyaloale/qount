"""Paid reductions must not reset original budgets or historical cash flows."""
import copy
import unittest

import test_binance_macro_funding_lease as lease_fixtures
import test_binance_macro_validation as minute_fixtures
from qount.research.binance_macro_funding_lease import resize_lease
from qount.research.binance_macro_opportunities import fixed_fill_metrics, trade_pnl_components
from qount.research.binance_macro_validation import frozen_trade
from qount.research.small_account_breakout import Bar


class TestLeaseResize(unittest.TestCase):
    def plan(self, **kwargs):
        order = dict(quantity=1, entry_price=100, stop=95, margin_usdt=20,
                     risk_budget_usdt=15, funding_adverse_paid=0, funding_cost_cap_usdt=.5)
        order.update(kwargs.pop("order", {}))
        rule = dict(filters=[dict(filterType="LOT_SIZE", stepSize=".1", minQty=".1", maxQty="100"),
                             dict(filterType="MIN_NOTIONAL", notional="5")])
        args = dict(now=1000, price=105, mark_price=105, cash=100, reserve=.02,
                    hours=168, eligible=True, fee=.0005, slip=.0025,
                    risk_fraction=.5, gap=.03, liquidity=10)
        return resize_lease(order, rule, **{**args, **kwargs})

    def test_maximum_grid_residual_pays_exit_cost_and_passes_frozen_cap(self):
        r = self.plan()
        self.assertTrue(r["allowed"])
        self.assertEqual(r["quantity"], .2)
        self.assertEqual(r["removed_quantity"], .8)
        self.assertAlmostEqual(r["exit_price"], 104.7375)
        self.assertAlmostEqual(r["cash_after"], 100+.8*(104.7375-100)-.8*104.7375*.0005)
        self.assertAlmostEqual(r["review"]["forecast_cost"], .42)
        self.assertGreater(.3*105*.02, .5)
        self.assertEqual(r["review"]["funding_cost_cap"], .5)

    def test_historical_debits_and_sunk_risk_cannot_be_reset(self):
        self.assertEqual(self.plan(order=dict(funding_adverse_paid=.6))["reason"], "resize_stop_or_spent_cap")
        self.assertFalse(self.plan(order=dict(partial_risk_spent_usdt=15))["allowed"])
        r = self.plan(order=dict(funding_adverse_paid=.2, partial_risk_spent_usdt=1))
        self.assertTrue(r["allowed"])
        self.assertEqual(r["quantity"], .1)
        self.assertEqual(r["review"]["adverse_paid"], .2)
        self.assertGreater(r["partial_risk_spent_usdt"], 1)

    def test_insufficient_exit_capacity_or_lot_size_keeps_full_exit(self):
        self.assertFalse(self.plan(liquidity=.1)["allowed"])
        self.assertFalse(self.plan(reserve=.06)["allowed"])

    def test_missing_forecast_or_broken_state_never_rescued(self):
        self.assertFalse(self.plan(eligible=False)["allowed"])
        self.assertFalse(self.plan(reserve=None)["allowed"])
        self.assertFalse(self.plan(price=94)["allowed"])

    def test_a_liquidated_mark_open_cannot_be_rescued_with_a_trim(self):
        self.assertEqual(self.plan(mark_price=80)["reason"], "resize_already_liquidated")

    def integration(self):
        helper = lease_fixtures.TestFundingLease()
        data, features = helper.fixture(extend=True)
        original = helper.run_lease(data, features, funding_lease_budget="risk")["trades"][0]
        now = original["entry_time"]+168*3600
        data[original["symbol"]]["funding"].append(dict(fundingTime=(now-3600)*1000+1,
            fundingRate=".001", markPrice="100", rateType="Regular"))
        data[original["symbol"]]["funding"].sort(key=lambda r: int(r["fundingTime"]))
        caps = {(s, b.t): dict(asof=b.t-60, quantity_cap=1000) for s,d in data.items() for b in d["trade"]}
        return helper, data, features, caps, now

    def test_replay_reconciles_partial_funding_fees_and_unchanged_lifetime_budget(self):
        h, data, fs, caps, now = self.integration()
        baseline = h.run_lease(data, fs, funding_lease_budget="risk")
        b = h.run_lease(data, fs, funding_lease_budget="risk", funding_lease_resize=True, lease_exit_liquidity_caps=caps)
        t = b["trades"][0]
        self.assertEqual(baseline["trades"][0]["exit_time"], now)
        self.assertEqual(t["partial_exits"][0]["time"], now)
        self.assertGreater(t["exit_time"], now)
        self.assertEqual(t["quantity"], t["initial_quantity"])
        self.assertAlmostEqual(t["remaining_quantity"]+sum(r["quantity"] for r in t["partial_exits"]), t["quantity"])
        self.assertTrue(all(r["funding_cost_cap"] == t["funding_cost_cap_usdt"] for r in t["funding_lease_reviews"]))
        self.assertAlmostEqual(10+sum(x["net_pnl"] for x in b["trades"]), b["summary"]["final_equity"])
        trade_pnl_components(t, fee=.0005, slip=.0005)
        with self.assertRaisesRegex(ValueError, "constant_quantity"):
            fixed_fill_metrics(t, t, data[t["symbol"]]["funding"])

    def test_future_settlement_cannot_change_first_reduction(self):
        h, data, fs, caps, now = self.integration()
        original = h.run_lease(data, fs, funding_lease_budget="risk", funding_lease_resize=True, lease_exit_liquidity_caps=caps)["trades"][0]
        changed = copy.deepcopy(data)
        changed[original["symbol"]]["funding"].append(dict(fundingTime=(now+3600)*1000+1,
            fundingRate=".02", markPrice="100", rateType="Regular"))
        changed[original["symbol"]]["funding"].sort(key=lambda r:int(r["fundingTime"]))
        t = h.run_lease(changed, fs, funding_lease_budget="risk", funding_lease_resize=True, lease_exit_liquidity_caps=caps)["trades"][0]
        self.assertEqual(t["partial_exits"][0], original["partial_exits"][0])
        self.assertEqual(t["funding_lease_reviews"][:2], original["funding_lease_reviews"][:2])

    def test_future_exit_volume_is_rejected_before_reduction(self):
        h, data, fs, caps, now = self.integration()
        for s in data:
            caps[s,now]["asof"] = now
        with self.assertRaisesRegex(ValueError, "future_lease_exit_capacity"):
            h.run_lease(data, fs, funding_lease_budget="risk", funding_lease_resize=True, lease_exit_liquidity_caps=caps)

    def test_minute_ledger_charges_funding_on_live_quantity_and_each_exit_once(self):
        args = list(minute_fixtures.fixture())
        args[0]["partial_exits"] = [dict(time=60, quantity=.1)]
        args[1][1] = args[2][1] = Bar(60,102,103,101,102,100)
        args[1][3] = args[2][3] = Bar(180,104,105,103,104,100)
        args[3] = [dict(fundingTime=30001,fundingRate=".001",markPrice="100"),
                   dict(fundingTime=60001,fundingRate=".001",markPrice="102")]
        r = frozen_trade(*args)
        self.assertAlmostEqual(r["funding"], -.0302)
        self.assertAlmostEqual(r["net_pnl"], .52920015)
        self.assertAlmostEqual(r["remaining_quantity"], .1)
        self.assertEqual(len(r["partial_exits"]), 1)
        trade_pnl_components(r, fee=.0005, slip=.0005)
