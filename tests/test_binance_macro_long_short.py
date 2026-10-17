"""Direction signs, adverse fills, funding and shared-capital regressions."""
import copy
import unittest

from qount.research.binance_etf_leverage import funding_reserve, replay
from qount.research.binance_macro_attack import directional_book
from qount.research.binance_macro_opportunities import fixed_fill_metrics
from qount.research.small_account_breakout import Bar
from test_binance_macro_attack import macro_fixture


def short_fixture():
    data, features = macro_fixture()
    for rows in features.values():
        for row in rows:
            row.update(entry_short=True, hold_short=True, rank_short=10,
                       state_short="TREND_UP", gross_short=3)
    return directional_book(data, features, "short")


class TestMacroLongShort(unittest.TestCase):
    def isolated(self, data, features, **kwargs):
        first = replay(data, features, strategy="macro_tactical", risk_fraction=.2,
                       gross_cap=3, account_controls=False)["trades"][0]
        return replay(data, features, strategy="macro_tactical", risk_fraction=.2,
                      gross_cap=3, account_controls=False,
                      forced_entry={"time": first["entry_time"], "symbol": first["symbol"], "engine": "tactical"}, **kwargs)

    def test_short_falling_price_profits_with_adverse_fill_and_reconciles(self):
        data, features = short_fixture()
        first = self.isolated(data, features)["trades"][0]
        for d in data.values():
            for kind in ("trade", "mark"):
                d[kind] = [Bar(b.t, 90, 91, 89, 90, b.v, b.q) if b.t > first["entry_time"] else b
                           for b in d[kind]]
        result = self.isolated(data, features)
        t = result["trades"][0]
        self.assertEqual(t["side"], -1)
        self.assertLess(t["entry_price"], 100)
        self.assertGreater(t["exit_price"], 90)
        expected = t["quantity"]*(t["entry_price"]-t["exit_price"])-t["entry_fee"]-t["quantity"]*t["exit_price"]*.0005+t["funding"]
        self.assertGreater(t["net_pnl"], 0)
        self.assertAlmostEqual(expected, t["net_pnl"])
        self.assertAlmostEqual(10+t["net_pnl"], result["summary"]["final_equity"])

    def test_short_stops_on_high_and_gap_fill_is_adverse(self):
        data, features = short_fixture()
        first = self.isolated(data, features)["trades"][0]
        d = data[first["symbol"]]
        i = next(i for i, b in enumerate(d["trade"]) if b.t == first["entry_time"])
        b = d["trade"][i]
        d["trade"][i] = d["mark"][i] = Bar(b.t, 100, 106, 99, 100, b.v, b.q)
        t = self.isolated(data, features, stop_gap=.02)["trades"][0]
        self.assertEqual(t["exit_reason"], "stop")
        self.assertEqual(t["exit_time"], t["entry_time"]+3600)
        self.assertAlmostEqual(t["exit_price"], t["initial_stop"]*1.02*1.0005)
        self.assertLess(t["net_pnl"], 0)

    def test_short_dividend_funding_is_debit_and_not_used_in_regular_forecast(self):
        data, features = short_fixture()
        base = self.isolated(data, features)["trades"][0]
        data[base["symbol"]]["funding"] = sorted(data[base["symbol"]]["funding"]+[
            {"fundingTime": base["entry_time"]*1000+1, "fundingRate": "-0.01",
             "markPrice": "100", "rateType": "Special"}], key=lambda r: int(r["fundingTime"]))
        changed = self.isolated(data, features)["trades"][0]
        self.assertAlmostEqual(changed["quantity"], base["quantity"])
        self.assertAlmostEqual(changed["net_pnl"]-base["net_pnl"], -base["quantity"])
        rows = [{"fundingTime": t*3600000, "fundingRate": "-0.0001"} for t in range(28, 100, 8)]
        self.assertEqual(funding_reserve(rows, 100*3600, 168, "debit_peak", 1), 0)
        self.assertAlmostEqual(funding_reserve(rows, 100*3600, 168, "debit_peak", -1), .0021)

    def test_short_liquidation_uses_mark_high(self):
        data, features = short_fixture()
        first = self.isolated(data, features)["trades"][0]
        d = data[first["symbol"]]
        i = next(i for i, b in enumerate(d["mark"]) if b.t == first["entry_time"])
        b = d["mark"][i]
        d["mark"][i] = Bar(b.t, 100, 150, 99, 100, b.v, b.q)
        result = self.isolated(data, features)
        self.assertEqual(result["summary"]["halt"], "liquidation_proxy")
        self.assertEqual(result["trades"][0]["exit_reason"], "liquidation_proxy")

    def test_short_fixed_cost_stress_charges_negative_regular_not_dividend_twice(self):
        trade = dict(side=-1, quantity=1, entry_price=100, exit_price=90,
                     entry_time=10, exit_time=20, net_pnl=8.81,
                     funding=-1, exit_reason="time_exit", stress_risk_usdt=5)
        funding = [dict(fundingTime=12000, markPrice="100", fundingRate="-0.002", rateType="Regular"),
                   dict(fundingTime=13000, markPrice="100", fundingRate="-0.008", rateType="Special")]
        result = fixed_fill_metrics(trade, trade, funding, fee=.001, slip=0)
        self.assertAlmostEqual(result["fixed_path_double_cost_pnl"], 10-.38-1-.2)

    def test_both_directions_share_capital_and_do_not_mutate_inputs(self):
        data, features = macro_fixture()
        for rows in features.values():
            for row in rows:
                row.update(entry_short=True, hold_short=True, rank_short=10,
                           state_short="TREND_UP", gross_short=3)
        original = copy.deepcopy(features)
        book, signals = directional_book(data, features)
        result = replay(book, signals, strategy="macro_tactical", risk_fraction=.2,
                        gross_cap=3, account_controls=False)
        self.assertEqual(features, original)
        self.assertEqual(result["trades"][0]["side"], -1)
        for a, b in zip(result["trades"], result["trades"][1:]):
            self.assertLessEqual(a["exit_time"], b["entry_time"])
        self.assertAlmostEqual(10+sum(t["net_pnl"] for t in result["trades"]), result["summary"]["final_equity"])


if __name__ == "__main__":
    unittest.main()
