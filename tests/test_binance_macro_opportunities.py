"""Checks for isolated-path attribution and executable tactical preemption."""
import copy
import unittest

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_opportunities import fractional_rules, fixed_fill_metrics, summarize_events
from qount.research.small_account_breakout import Bar
from test_binance_macro_attack import macro_fixture


class TestMacroOpportunities(unittest.TestCase):
    def test_fractional_control_preserves_unrelated_rules(self):
        data, _ = macro_fixture()
        old = copy.deepcopy(data["SPYUSDT"]["rule"])
        result = fractional_rules(data, relax_grid=False)
        fs = {f["filterType"]: f for f in result["SPYUSDT"]["rule"]["filters"]}
        before = {f["filterType"]: f for f in old["filters"]}
        self.assertEqual(data["SPYUSDT"]["rule"], old)
        self.assertEqual(fs["LOT_SIZE"], before["LOT_SIZE"])
        self.assertEqual(fs["PRICE_FILTER"], before["PRICE_FILTER"])
        self.assertEqual(fs["MIN_NOTIONAL"]["notional"], "0")

    def test_fixed_cost_counterfactual_does_not_double_dividend_credit(self):
        trade = {"quantity": 2, "entry_price": 100, "exit_price": 110,
                 "entry_time": 10, "exit_time": 20, "funding": 1,
                 "net_pnl": 20-0.42+1, "exit_reason": "trend_off"}
        funding = [{"fundingTime": 12000, "markPrice": "100", "fundingRate": "0.001", "rateType": "Regular"},
                   {"fundingTime": 13000, "markPrice": "100", "fundingRate": "-0.006", "rateType": "Special"}]
        result = fixed_fill_metrics(trade, {"quantity": 1, "stress_risk_usdt": 5}, funding, fee=0.001, slip=0)
        self.assertAlmostEqual(result["net_pnl"], 10-0.21+0.5)
        self.assertAlmostEqual(result["fixed_path_double_cost_pnl"], 10-0.42+0.5-0.1)

    def test_censored_events_do_not_enter_closed_expectancy(self):
        events = [{"episode": "a", "outcomes": {"exact10": {"right_censored": False, "net_pnl": -1,
                   "net_stress_r": -0.5, "fixed_path_double_cost_r": -0.6}}},
                  {"episode": "b", "outcomes": {"exact10": {"right_censored": True, "net_pnl": 100,
                   "net_stress_r": 50, "fixed_path_double_cost_r": 49}}}]
        summary = summarize_events(events)
        self.assertEqual(summary["closed"], 1)
        self.assertEqual(summary["censored"], 1)
        self.assertEqual(summary["mean_net_stress_r"], -0.5)

    def test_forced_signal_path_has_exactly_one_entry_and_retains_exit_rules(self):
        data, features = macro_fixture()
        baseline = replay(data, features, strategy="macro_tactical", gross_cap=3, risk_fraction=0.08)
        t = baseline["trades"][0]
        isolated = replay(data, features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08,
                          account_controls=False, forced_entry={"time": t["entry_time"], "symbol": t["symbol"], "engine": "tactical"})
        self.assertEqual(len(isolated["trades"]), 1)
        self.assertEqual(isolated["trades"][0], t)

    def test_quantity_counterfactual_matches_direct_exact_replay(self):
        data, features = macro_fixture()
        baseline = replay(data, features, strategy="macro_tactical", gross_cap=3, risk_fraction=0.08)
        t = baseline["trades"][0]
        forced = {"time": t["entry_time"], "symbol": t["symbol"], "engine": "tactical"}
        exact = replay(data, features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08,
                       forced_entry=forced, account_controls=False)["trades"][0]
        frac = replay(fractional_rules(data), features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08,
                      forced_entry=forced, account_controls=False)["trades"][0]
        self.assertNotEqual(exact["quantity"], frac["quantity"])
        self.assertEqual(exact["exit_time"], frac["exit_time"])
        self.assertEqual(exact["exit_price"], frac["exit_price"])
        scaled = fixed_fill_metrics(frac, exact, data[t["symbol"]]["funding"])
        self.assertAlmostEqual(scaled["net_pnl"], exact["net_pnl"])

    def test_unexecutable_tactical_signal_does_not_liquidate_core(self):
        data, features = macro_fixture()
        for d in data.values():
            for row in d["funding"]:
                row["fundingRate"] = "0"
        for rows in features.values():
            for row in rows:
                row["entry_tactical"] = False
        first = replay(data, features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08)["trades"][0]
        for row in features["SPYUSDT"]:
            if row["available"] > first["entry_time"]:
                row["entry_tactical"] = True
        for kind in ("trade", "mark"):
            data["SPYUSDT"][kind] = [Bar(b.t, 10000, 10100, 9900, 10000, b.v, b.q) for b in data["SPYUSDT"][kind]]
        result = replay(data, features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08,
                        routing="tactical_preempt")
        self.assertTrue(all(t["exit_reason"] != "tactical_preempt" for t in result["trades"]))
        self.assertEqual(result["trades"][0]["symbol"], first["symbol"])

    def test_natural_handover_uses_exit_clock_without_preempting(self):
        data, features = macro_fixture()
        for rows in features.values():
            for row in rows:
                row["entry_core"] = False
        baseline = replay(data, features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08)
        handover = replay(data, features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08,
                          routing="exit_handover")
        self.assertEqual(baseline["trades"][0], handover["trades"][0])
        self.assertEqual(handover["trades"][0]["exit_time"], handover["trades"][1]["entry_time"])
        self.assertNotEqual(handover["trades"][0]["symbol"], handover["trades"][1]["symbol"])
        self.assertTrue(all(t["exit_reason"] != "tactical_preempt" for t in handover["trades"]))


if __name__ == "__main__":
    unittest.main()
