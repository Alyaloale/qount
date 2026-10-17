"""Accounting and non-invasive observation for the selected cost diagnosis."""
import unittest
from unittest.mock import patch

import qount.research.binance_etf_leverage as model
from scripts.research.diagnose_macro_1atr_costs import frozen_trade, recorded_replay
from test_binance_macro_attack import macro_fixture


class TestMacroCostAttribution(unittest.TestCase):
    def trade(self, side):
        funding = [dict(fundingTime=t, markPrice="100", fundingRate=str(side*rate), rateType=kind)
                   for t, rate, kind in ((9999, .5, "Regular"), (10000, .001, "Regular"),
                       (12000, -.004, "Regular"), (13000, .01, "Special"), (20000, .5, "Regular"))]
        paid = -side*2*sum(float(r["markPrice"])*float(r["fundingRate"])
                          for r in funding if 10000 <= r["fundingTime"] < 20000)
        entry, exit_ = 100*(1+side*.01), 110*(1-side*.01)
        trade = dict(symbol="TESTUSDT", side=side, quantity=2, entry_price=entry, exit_price=exit_,
                     entry_time=10, exit_time=20, funding=paid, exit_reason="trend_off", stress_risk_usdt=5,
                     net_pnl=side*2*(exit_-entry)-.001*2*(entry+exit_)+paid)
        return trade, funding

    def test_fixed_costs_include_entry_exclude_exit_and_do_not_double_special_or_credits(self):
        for side in (1, -1):
            with self.subTest(side=side):
                trade, funding = self.trade(side)
                result = frozen_trade(trade, funding, fee=.001, slip=.01)
                target_entry, target_exit = 100*(1+side*.02), 110*(1-side*.02)
                expected = side*2*(target_exit-target_entry)-.002*2*(target_entry+target_exit)+trade["funding"]-.2
                self.assertAlmostEqual(result["extra_adverse_regular_funding"], .2)
                self.assertAlmostEqual(result["fixed_double_net_pnl"], expected)
                self.assertAlmostEqual(result["base_net_pnl"]-result["fixed_double_net_pnl"],
                    result["extra_slippage"]+result["extra_fees"]+result["extra_adverse_regular_funding"])

    def test_censored_trade_remains_identified_and_partial_positions_are_rejected(self):
        trade, funding = self.trade(1)
        trade["exit_reason"] = "end_of_sample"
        self.assertTrue(frozen_trade(trade, funding, fee=.001, slip=.01)["right_censored"])
        trade["partial_exits"] = [dict(quantity=1, price=trade["exit_price"])]
        with self.assertRaisesRegex(ValueError, "constant_quantity"):
            frozen_trade(trade, funding, fee=.001, slip=.01)

    def test_recording_reproduces_replay_and_restores_original_functions(self):
        data, features = macro_fixture()
        controls = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.08)
        original_feature, original_size = model.feature_at, model.size
        expected = model.replay(data, features, capital=10, fee=.0005, slip=.0005, trace=True, **controls)
        result, attempts = recorded_replay(data, features, None, None,
            capital=10, controls=controls, fee=.0005, slip=.0005)
        self.assertEqual(result, expected)
        self.assertGreater(len(attempts), 0)
        self.assertIs(model.feature_at, original_feature)
        self.assertIs(model.size, original_size)
        accepted = {(a["time"], a["symbol"]) for a in attempts if a["reason"] == "accepted"}
        self.assertEqual(accepted, {(t["entry_time"], t["symbol"]) for t in result["trades"]})

    def test_observers_restore_even_when_replay_fails(self):
        data, features = macro_fixture()
        original_feature, original_size = model.feature_at, model.size
        with patch.object(model, "replay", side_effect=ValueError("fixture_failure")):
            with self.assertRaisesRegex(ValueError, "fixture_failure"):
                recorded_replay(data, features, None, None, capital=10,
                    controls=dict(strategy="macro_tactical"), fee=.0005, slip=.0005)
        self.assertIs(model.feature_at, original_feature)
        self.assertIs(model.size, original_size)


if __name__ == "__main__":
    unittest.main()
