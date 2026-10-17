"""The shared small-account book must preserve routing and risk boundaries."""
import datetime as dt
import unittest

from qount.research.binance_etf_leverage import replay
from qount.research.small_account_breakout import Bar, NY
from test_binance_etf_leverage import fixture


def macro_fixture():
    data, features = fixture()
    for rows in features.values():
        for row in rows:
            row.update(state="TREND_UP", entry_core=True, entry_tactical=True,
                       hold_core=True, hold_tactical=True, rank_core=row["momentum120"],
                       rank_tactical=3.0+row["momentum120"], gross_target=3.0)
    return data, features


class TestBinanceMacroAttack(unittest.TestCase):
    def test_infeasible_core_does_not_hide_tactical_opportunity(self):
        data, features = macro_fixture()
        core = replay(data, features, strategy="macro_core", gross_cap=3, risk_fraction=0.08)
        self.assertEqual(core["summary"]["trade_count"], 0)
        self.assertGreater(core["summary"]["rejections"]["friction_budget"], 0)
        hybrid = replay(data, features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08)
        self.assertGreater(hybrid["summary"]["trade_count"], 0)
        self.assertTrue(all(t["engine"] == "tactical" for t in hybrid["trades"]))

    def test_state_budget_limits_entry_even_with_three_times_cap(self):
        data, features = macro_fixture()
        for rows in features.values():
            for row in rows:
                row["gross_target"] = 1.0
        result = replay(data, features, strategy="macro_tactical", gross_cap=3, risk_fraction=0.08)
        self.assertGreater(result["summary"]["trade_count"], 0)
        for t in result["trades"]:
            self.assertLessEqual(t["notional_usdt"], t["equity_before_entry"]+1e-9)

    def test_core_stop_does_not_automatically_reenter_same_month(self):
        data, features = macro_fixture()
        for d in data.values():
            for row in d["funding"]:
                row["fundingRate"] = "0"
        first = replay(data, features, strategy="macro_core", gross_cap=3, risk_fraction=0.08)["trades"][0]
        s, entry = first["symbol"], first["entry_time"]
        i = next(i for i, b in enumerate(data[s]["trade"]) if b.t == entry)
        data[s]["trade"][i] = Bar(entry, 100, 101, 94, 99, 10000, 1000000)
        data[s]["mark"][i] = Bar(entry, 100, 101, 94, 99, 10000, 1000000)
        result = replay(data, features, strategy="macro_core", gross_cap=3, risk_fraction=0.08)
        months = [dt.datetime.fromtimestamp(t["entry_time"], NY).strftime("%Y-%m") for t in result["trades"]]
        self.assertEqual(len(months), len(set(months)))
        self.assertEqual(result["trades"][0]["exit_reason"], "stop")

    def test_engines_share_one_nonoverlapping_cash_book(self):
        data, features = macro_fixture()
        result = replay(data, features, strategy="macro_hybrid", gross_cap=3, risk_fraction=0.08)
        trades = result["trades"]
        self.assertGreater(len(trades), 1)
        for a, b in zip(trades, trades[1:]):
            self.assertLessEqual(a["exit_time"], b["entry_time"])
        self.assertAlmostEqual(10+sum(t["net_pnl"] for t in trades), result["summary"]["final_equity"])

    def test_full_loss_experiment_continues_after_drawdown_with_stops_and_full_budget(self):
        data, features = macro_fixture()
        for d in data.values():
            for row in d["funding"]:
                row["fundingRate"] = "0"
            for kind in ("trade", "mark"):
                d[kind] = [Bar(b.t, b.o, b.h, 92, b.c, b.v, b.q) if i >= 350 else b
                           for i, b in enumerate(d[kind])]
        common = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=0.20, stop_gap=0.05)
        original = replay(data, features, **common)
        aggressive = replay(data, features, account_controls=False, **common)
        self.assertEqual(original["summary"]["halt"], "drawdown_halt")
        self.assertIsNone(aggressive["summary"]["halt"])
        self.assertGreater(aggressive["summary"]["max_drawdown"], 0.20)
        self.assertGreater(len(aggressive["trades"]), len(original["trades"]))
        self.assertEqual(aggressive["trades"][0]["exit_reason"], "stop")
        for t in aggressive["trades"]:
            self.assertAlmostEqual(t["risk_budget_usdt"], 0.20*t["equity_before_entry"])
            self.assertLessEqual(t["stress_risk_usdt"], t["risk_budget_usdt"]+1e-9)

    def test_full_loss_experiment_keeps_liquidation_halt(self):
        data, features = macro_fixture()
        common = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=0.20, account_controls=False)
        first = replay(data, features, **common)["trades"][0]
        d = data[first["symbol"]]
        i = next(i for i, b in enumerate(d["mark"]) if b.t == first["entry_time"])
        b = d["mark"][i]
        d["mark"][i] = Bar(b.t, b.o, b.h, 70, b.c, b.v, b.q)
        result = replay(data, features, **common)
        self.assertEqual(result["summary"]["halt"], "liquidation_proxy")
        self.assertEqual(result["trades"][0]["exit_reason"], "liquidation_proxy")
        self.assertEqual(len(result["trades"]), 1)


if __name__ == "__main__":
    unittest.main()
