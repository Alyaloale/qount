"""Minute stops, collateral depletion, delays and bankruptcy bounds."""
import unittest

from qount.research.binance_macro_validation import frozen_trade
from qount.research.small_account_breakout import Bar


def fixture(end=180):
    order = dict(symbol="TEST", quantity=.2, entry_time=0, exit_time=end,
                 exit_reason="time_exit", initial_stop=95, entry_price=100.05,
                 leverage=5, equity_before_entry=10, stress_risk_usdt=1.5)
    bars = [Bar(t, 100, 101, 99, 100, 100, 10000) for t in range(0, end+420, 60)]
    rule = dict(liquidationFee=".015", filters=[dict(filterType="PRICE_FILTER", tickSize=".01")])
    return order, bars, bars.copy(), [], [(0, 2)], rule


class TestMacroValidation(unittest.TestCase):
    def test_frozen_quantity_pnl_and_exit_open(self):
        args = list(fixture())
        args[1][3] = Bar(180, 102, 103, 101, 102, 100)
        result = frozen_trade(*args)
        expected = .2*(102*.9995-100*1.0005)-.2*.0005*(102*.9995+100*1.0005)
        self.assertAlmostEqual(result["net_pnl"], expected)
        self.assertEqual(result["exit_time"], 180)
        self.assertEqual(result["quantity"], .2)

    def test_gap_through_stop_exceeds_budget_and_closes_next_minute(self):
        result = frozen_trade(*fixture(), stop_overshoot=.10)
        self.assertEqual(result["exit_reason"], "stop")
        self.assertEqual(result["exit_time"], 120)
        self.assertAlmostEqual(result["exit_price"], 95*.9*.9995)
        self.assertTrue(result["risk_budget_exceeded"])

    def test_exceeding_estimated_loss_is_distinct_from_exceeding_allocated_budget(self):
        args = list(fixture())
        args[0]["risk_budget_usdt"] = 2
        result = frozen_trade(*args, stop_overshoot=.03)
        self.assertTrue(result["stress_estimate_exceeded"])
        self.assertFalse(result["risk_budget_exceeded"])

    def test_liquidation_clearance_and_bankruptcy_do_not_consume_free_cash(self):
        result = frozen_trade(*fixture(), stop_overshoot=.30)
        self.assertEqual(result["exit_reason"], "liquidation_proxy")
        self.assertEqual(result["ambiguous_stop_liquidation_minutes"], 1)
        self.assertGreater(result["bankruptcy_adjustment"], 0)
        self.assertAlmostEqual(result["net_pnl"], -(.2*100.05/5+.2*100.05*.0005))
        self.assertGreater(10+result["net_pnl"], 0)

    def test_funding_from_isolated_changes_liquidation_before_exit(self):
        args = list(fixture())
        args[1][1] = Bar(60, 90, 91, 89, 90, 100)
        args[2][1] = Bar(60, 90, 91, 81.5, 90, 100)
        args[3] = [dict(fundingTime=60001, fundingRate=".01", markPrice="100")]
        wallet = frozen_trade(*args)
        isolated = frozen_trade(*args, funding_collateral="isolated_debit")
        self.assertEqual(wallet["exit_reason"], "stop")
        self.assertEqual(isolated["exit_reason"], "liquidation_proxy")
        self.assertAlmostEqual(wallet["funding"], -.2)
        self.assertAlmostEqual(isolated["funding"], -.2)
        self.assertGreater(isolated["liquidation_fee"], 0)

    def test_mark_stop_uses_contract_fill_not_trigger_price(self):
        args = list(fixture())
        args[2][1] = Bar(60, 100, 101, 94, 100, 100)
        normal = frozen_trade(*args)
        mark = frozen_trade(*args, trigger="mark")
        self.assertEqual(normal["exit_reason"], "time_exit")
        self.assertEqual(mark["exit_reason"], "stop")
        self.assertAlmostEqual(mark["exit_price"], args[1][1].l*.9995)

    def test_hour_close_trail_applies_only_next_minute(self):
        args = list(fixture(3660))
        args[1][59] = args[2][59] = Bar(3540, 100, 115, 100, 115, 100)
        args[1][60] = args[2][60] = Bar(3600, 110, 112, 109, 110, 100)
        result = frozen_trade(*args)
        self.assertEqual(result["exit_reason"], "stop")
        self.assertEqual(result["exit_time"], 3660)

    def test_delayed_entry_rejects_price_already_beyond_stop(self):
        args = list(fixture())
        args[1][1] = Bar(60, 94, 95, 93, 94, 100)
        result = frozen_trade(*args, entry_delay=1)
        self.assertEqual(result["status"], "cancelled_entry_beyond_stop")
        self.assertEqual(result["net_pnl"], 0)

    def test_sample_end_uses_last_close_without_future_bar(self):
        args = list(fixture())
        args[0]["exit_reason"] = "end_of_sample"
        args[1] = args[1][:3]
        args[2] = args[2][:3]
        args[1][-1] = Bar(120, 100, 104, 99, 103, 100)
        result = frozen_trade(*args, exit_delay=5)
        self.assertEqual(result["exit_time"], 180)
        self.assertAlmostEqual(result["exit_price"], 103*.9995)


if __name__ == "__main__":
    unittest.main()
