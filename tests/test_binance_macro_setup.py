"""Entry setup is frozen; funding reserves match its chosen full horizon."""
import copy
import unittest
from unittest.mock import patch

from qount.research.binance_etf_leverage import funding_reserve, replay
from qount.research.binance_macro_setup import setup_policies
from test_binance_macro_attack import macro_fixture


class TestMacroSetup(unittest.TestCase):
    def test_entry_cutoff_does_not_truncate_holding_or_allow_later_entries(self):
        data, features = macro_fixture()
        args = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.2, account_controls=False)
        first = replay(data, features, **args)["trades"][0]
        result = replay(data, features, **args, entry_end_exclusive=first["entry_time"]+1)
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"][0], first)
        self.assertGreater(first["exit_time"], first["entry_time"]+1)
        self.assertEqual(replay(data, features, **args, entry_end_exclusive=first["entry_time"])["trades"], [])

    def test_frozen_mr_holding_survives_later_trend_labels_and_state_exit(self):
        data, features = macro_fixture()
        for d in data.values():
            for row in d["funding"]:
                row["fundingRate"] = "0"
        args = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.2, account_controls=False)
        first = replay(data, features, **args)["trades"][0]
        for rows in features.values():
            for f in rows:
                earlier = f["available"] < first["entry_time"]
                f.update(tactical_setup="mean_reversion" if earlier else "breakout",
                         hold_tactical=earlier, hold_structural=True)
        original = copy.deepcopy(features)
        with patch("qount.research.binance_etf_leverage.funding_reserve", wraps=funding_reserve) as reserve:
            result = replay(data, features, **args, tactical_setup_policies=setup_policies(7, 21),
                            forced_entry=dict(symbol=first["symbol"], time=first["entry_time"], engine="tactical"))
        t = result["trades"][0]
        self.assertEqual(t["tactical_setup"], "mean_reversion")
        self.assertEqual(t["hold_feature"], "hold_structural")
        self.assertEqual(t["max_hold_hours"], 504)
        self.assertGreater(t["exit_time"]-t["entry_time"], 168*3600)
        self.assertTrue(all(c.args[2] == 504 for c in reserve.call_args_list))
        self.assertEqual(features, original)

    def test_trend_entry_uses_short_horizon_even_if_later_label_is_mr(self):
        data, features = macro_fixture()
        args = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.2, account_controls=False)
        first = replay(data, features, **args)["trades"][0]
        for rows in features.values():
            for f in rows:
                earlier = f["available"] < first["entry_time"]
                f.update(tactical_setup="pullback" if earlier else "mean_reversion", hold_structural=True)
        result = replay(data, features, **args, tactical_setup_policies=setup_policies(7, 21),
                        forced_entry=dict(symbol=first["symbol"], time=first["entry_time"], engine="tactical"))
        t = result["trades"][0]
        self.assertEqual(t["tactical_setup"], "pullback")
        self.assertEqual(t["max_hold_hours"], 168)
        self.assertLessEqual(t["exit_time"]-t["entry_time"], 168*3600)

    def test_same_seven_day_policy_preserves_legacy_prices_quantity_and_cash(self):
        data, features = macro_fixture()
        for rows in features.values():
            for f in rows:
                f.update(tactical_setup="breakout", hold_structural=True)
        args = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.2, account_controls=False)
        old = replay(data, features, **args)
        new = replay(data, features, **args, tactical_setup_policies=setup_policies(7, 7))
        self.assertEqual(old["summary"], new["summary"])
        self.assertEqual(old["curve"], new["curve"])
        self.assertEqual(old["trades"], [{k: v for k, v in t.items() if k not in ("hold_feature", "tactical_setup")} for t in new["trades"]])


if __name__ == "__main__":
    unittest.main()
