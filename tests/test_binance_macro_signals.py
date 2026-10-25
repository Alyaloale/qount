"""Causal native confirmation, holding/funding horizon and legacy equivalence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_signals import contract_confirmations, exit_features
from qount.research.binance_macro_validation import minute_windows
from qount.research.small_account_breakout import Bar
from test_binance_macro_attack import macro_fixture


class TestMacroSignals(unittest.TestCase):
    def test_state_exit_confirmation_preserves_entries_and_structural_veto(self):
        rows = [dict(available=i, entry_tactical=True, rank_tactical=3,
                     hold_tactical=tactical, hold_price_trend=price, hold_structural=structural)
                for i, (tactical, price, structural) in enumerate(
                    ((False, True, True), (False, False, True), (False, False, False), (True, False, True)))]
        features = {"A": rows}
        original = copy.deepcopy(features)
        result = exit_features(features, "state_exit_price_confirm")
        self.assertEqual([r["hold_tactical"] for r in result["A"]], [True, False, False, True])
        for old, new in zip(rows, result["A"]):
            self.assertEqual({k: v for k, v in old.items() if k != "hold_tactical"},
                             {k: v for k, v in new.items() if k != "hold_tactical"})
        self.assertEqual(features, original)
        changed = copy.deepcopy(features)
        changed["A"][-1]["hold_price_trend"] = True
        self.assertEqual(exit_features(changed, "state_exit_price_confirm")["A"][:-1], result["A"][:-1])

    def test_exit_policy_preserves_entries_ranks_and_information_times(self):
        features = {"A": [dict(available=100, entry_tactical=True, rank_tactical=3,
                               hold_tactical=False, hold_price_trend=True, hold_structural=True)]}
        original = copy.deepcopy(features)
        result = exit_features(features, "hold_price_trend")
        self.assertTrue(result["A"][0]["hold_tactical"])
        for key in ("available", "entry_tactical", "rank_tactical"):
            self.assertEqual(result["A"][0][key], original["A"][0][key])
        self.assertEqual(features, original)
        self.assertEqual(exit_features(features, "hold_tactical"), original)

    def test_relaxed_admission_still_charges_costs_and_keeps_risk_budget(self):
        data, features = macro_fixture()
        args = dict(strategy="macro_tactical", gross_cap=20, risk_fraction=.5, account_controls=False,
                    exchange_leverage=50, sizing_gap_reserve=.03, fee=.002, slip=.004)
        strict = replay(data, features, **args)
        relaxed = replay(data, features, friction_limit_fraction_of_stop=1, **args)
        self.assertEqual(strict["trades"], [])
        self.assertGreater(len(relaxed["trades"]), 0)
        for t in relaxed["trades"]:
            self.assertAlmostEqual(t["entry_fee"], t["notional_usdt"]*.002)
            self.assertLessEqual(t["stress_risk_usdt"], t["risk_budget_usdt"]+1e-9)
            self.assertLessEqual(t["margin_usdt"], t["equity_before_entry"]*.8+1e-9)

    def test_eighty_percent_risk_never_overrides_capacity_or_default_admission(self):
        data, features = macro_fixture()
        caps = {(s, b.t): dict(asof=b.t-60, quantity_cap=.06) for s, d in data.items() for b in d["trade"]}
        result = replay(data, features, strategy="macro_tactical", gross_cap=20, risk_fraction=.8,
                        account_controls=False, entry_liquidity_caps=caps, friction_limit_fraction_of_stop=1)
        self.assertGreater(len(result["trades"]), 0)
        self.assertTrue(all(t["quantity"] <= .06 for t in result["trades"]))
        args = dict(strategy="macro_tactical", account_controls=False)
        self.assertEqual(replay(data, features, **args), replay(data, features, friction_limit_fraction_of_stop=.2, **args))

    def test_entry_hour_and_future_prices_do_not_change_confirmation(self):
        bars = [Bar(i*3600, 100+i, 101+i, 99+i, 100+i, 10) for i in range(80)]
        data = {"A": dict(trade=bars)}
        for mode in ("above20", "aligned20_50"):
            result = contract_confirmations(data, [("A", 60*3600)], mode)
            changed = {"A": dict(trade=[b if i < 60 else Bar(b.t, 1, 1, 1, 1, 0) for i, b in enumerate(bars)])}
            self.assertEqual(result, contract_confirmations(changed, [("A", 60*3600)], mode))
            self.assertTrue(result["A", 60*3600]["eligible"])
            self.assertEqual(result["A", 60*3600]["asof"], 60*3600)

    def test_missing_history_and_falling_trend_fail_closed(self):
        bars = [Bar(i*3600, 200-i, 201-i, 199-i, 200-i, 10) for i in range(70)]
        result = contract_confirmations({"A": dict(trade=bars)}, [("A", 49*3600), ("A", 60*3600)], "above20")
        self.assertNotIn(("A", 49*3600), result)
        self.assertFalse(result["A", 60*3600]["eligible"])
        missing = bars[:55]+bars[56:]
        self.assertEqual(contract_confirmations({"A": dict(trade=missing)}, [("A", 60*3600)], "above20"), {})

    def test_default_options_reproduce_legacy_and_pass_all_confirmation(self):
        data, features = macro_fixture()
        original = copy.deepcopy(features)
        args = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.2, account_controls=False)
        baseline = replay(data, features, **args)
        contexts = {(s, b.t): dict(asof=b.t, eligible=True) for s, d in data.items() for b in d["trade"]}
        self.assertEqual(baseline, replay(data, features, entry_confirmations=contexts, tactical_max_hold_hours=168, **args))
        self.assertEqual(features, original)

    def test_confirmation_missing_off_stale_and_future(self):
        data, features = macro_fixture()
        args = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.2, account_controls=False)
        for contexts in ({}, {(s, b.t): dict(asof=b.t, eligible=False) for s, d in data.items() for b in d["trade"]},
                         {(s, b.t): dict(asof=b.t-7200, eligible=True) for s, d in data.items() for b in d["trade"]}):
            self.assertEqual(replay(data, features, entry_confirmations=contexts, **args)["trades"], [])
        future = {(s, b.t): dict(asof=b.t+1, eligible=True) for s, d in data.items() for b in d["trade"]}
        with self.assertRaisesRegex(ValueError, "future_native_confirmation"):
            replay(data, features, entry_confirmations=future, **args)

    def test_shorter_horizon_exits_on_clock_and_reserves_only_chosen_horizon(self):
        from unittest.mock import patch
        from qount.research.binance_etf_leverage import funding_reserve
        data, features = macro_fixture()
        with patch("qount.research.binance_etf_leverage.funding_reserve", wraps=funding_reserve) as reserve:
            result = replay(data, features, strategy="macro_tactical", gross_cap=3, risk_fraction=.2,
                            account_controls=False, tactical_max_hold_hours=72)
        self.assertGreater(len(result["trades"]), 0)
        self.assertTrue(all(c.args[2] == 72 for c in reserve.call_args_list))
        self.assertTrue(all(t["max_hold_hours"] == 72 and t["exit_time"]-t["entry_time"] <= 72*3600 for t in result["trades"]))
        self.assertTrue(any(t["exit_reason"] == "time_exit" for t in result["trades"]))
        with self.assertRaisesRegex(ValueError, "custom_horizon_requires_tactical_only"):
            replay(data, features, strategy="macro_hybrid", tactical_max_hold_hours=72)

    def test_short_exit_reuses_immutable_long_minute_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            rows = [[t*1000, "100", "101", "99", "100", "10", 0, "1000"] for t in range(0, 1200, 60)]
            paths = [cache/f"A-{k}-1m-0-1200.json" for k in ("trade", "mark")]
            for path in paths:
                path.write_text(json.dumps(rows))
            before = [p.read_bytes() for p in paths]
            windows, sources = minute_windows([dict(symbol="A", entry_time=0, exit_time=600)], cache, 2000)
            self.assertEqual([b.t for b in windows["A", 0]["trade"]], list(range(0, 960, 60)))
            self.assertEqual(len(sources), 2)
            self.assertEqual([p.read_bytes() for p in paths], before)
            self.assertEqual(len(list(cache.iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
