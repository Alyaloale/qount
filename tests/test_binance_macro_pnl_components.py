import unittest

from qount.research.binance_macro_opportunities import native_horizon_components, trade_pnl_components
from qount.research.small_account_breakout import Bar


class TestTradePnlComponents(unittest.TestCase):
    def test_long_price_profit_costs_and_funding_are_counted_once(self):
        trade = dict(quantity=2, entry_price=101, exit_price=108.9,
                     funding=-.5, net_pnl=14.8802)
        c = trade_pnl_components(trade, fee=.001, slip=.01)
        self.assertAlmostEqual(c["raw_price_pnl"], 20)
        self.assertAlmostEqual(c["slippage_cost"], 4.2)
        self.assertAlmostEqual(c["fees"], .4198)
        self.assertEqual(c["net_funding"], -.5)

    def test_short_favorable_funding_and_price_profit(self):
        trade = dict(side=-1, quantity=2, entry_price=99, exit_price=90.9,
                     funding=.5, net_pnl=16.3202)
        c = trade_pnl_components(trade, fee=.001, slip=.01)
        self.assertAlmostEqual(c["raw_price_pnl"], 20)
        self.assertAlmostEqual(c["slippage_cost"], 3.8)
        self.assertAlmostEqual(c["fees"], .3798)

    def test_wrong_cost_assumptions_fail_reconciliation(self):
        trade = dict(quantity=2, entry_price=101, exit_price=108.9,
                     funding=-.5, net_pnl=14.8802)
        with self.assertRaisesRegex(ValueError, "do_not_reconcile"):
            trade_pnl_components(trade, fee=.002, slip=.01)


class TestNativeHorizonComponents(unittest.TestCase):
    def fixture(self):
        bars = [Bar(t,100,101,99,100,1000) for t in range(0,7*86400+3600,3600)]
        order = dict(quantity=2,entry_time=0,entry_price=100.25,initial_stop=95,leverage=5)
        return order,dict(trade=bars,mark=list(bars),funding=[])

    def test_exact_endpoint_open_and_funding_interval(self):
        order,data = self.fixture()
        end = 7*86400
        data["trade"][-1] = Bar(end,110,121,109,120,1000)
        data["funding"] = [dict(fundingTime=t,markPrice="100",fundingRate=r,rateType=kind)
                           for t,r,kind in ((0,".001","Regular"),
                                            (end*1000-1,"-.002","Special"),
                                            (end*1000,".5","Regular"))]
        label = native_horizon_components(order,data,7,fee=.0005,slip=.0025)
        c = label["components"]
        self.assertAlmostEqual(c["raw_price_pnl"],20)
        self.assertAlmostEqual(c["net_funding"],.2)
        self.assertAlmostEqual(label["adverse_funding"],.2)
        self.assertAlmostEqual(label["favorable_funding"],.4)
        self.assertAlmostEqual(label["regular_net_funding"],-.2)
        self.assertAlmostEqual(label["special_net_funding"],.4)
        self.assertAlmostEqual(c["net_pnl"],c["raw_price_pnl"]-c["slippage_cost"]-c["fees"]+c["net_funding"])

    def test_unmatured_label_does_not_use_last_close(self):
        order,data = self.fixture()
        label = native_horizon_components(order,data,21,fee=.0005,slip=.0025)
        self.assertEqual(label,dict(censored=True,planned_exit=21*86400))
        data["trade"][-1] = Bar(7*86400,500,501,499,500,1000)
        self.assertEqual(label,native_horizon_components(order,data,21,fee=.0005,slip=.0025))

    def test_missing_interior_bar_fails_even_with_endpoint(self):
        order,data = self.fixture()
        data["mark"].pop(1)
        with self.assertRaisesRegex(ValueError,"native_horizon_gap"):
            native_horizon_components(order,data,7,fee=.0005,slip=.0025)

    def test_stopped_or_liquidated_label_remains_unexecutable(self):
        order,data = self.fixture()
        data["trade"][1] = Bar(3600,100,101,90,100,1000)
        data["mark"][2] = Bar(7200,100,101,70,100,1000)
        label = native_horizon_components(order,data,7,fee=.0005,slip=.0025)
        self.assertEqual(label["initial_stop_first_touch"],3600)
        self.assertEqual(label["static_liquidation_first_touch"],7200)
        self.assertFalse(label["executable_constraint_set"])

    def test_changed_entry_or_cost_case_fails(self):
        order,data = self.fixture()
        with self.assertRaisesRegex(ValueError,"native_entry_changed"):
            native_horizon_components(order,data,7,fee=.001,slip=.005)
