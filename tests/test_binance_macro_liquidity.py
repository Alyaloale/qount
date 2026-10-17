"""No future-volume filtering, quantity inflation or missing-context fallback."""
import copy
import unittest

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_liquidity import capacity_snapshot, guarded_long_quote
from qount.research.small_account_breakout import Bar
from test_binance_macro_attack import macro_fixture


class TestMacroLiquidity(unittest.TestCase):
    def test_future_and_unpublished_volume_do_not_change_capacity(self):
        now = 3600
        bars = [Bar(t, 100, 101, 99, 100, 100 if t < 3240 else 20) for t in range(2640, 3660, 60)]
        result = capacity_snapshot(bars, now)
        self.assertEqual(result["quantity_cap"], 2)
        self.assertEqual(result["asof"], now-60)
        changed = [b if b.t < 3540 else Bar(b.t, 100, 101, 99, 100, 1e9) for b in bars]
        self.assertEqual(capacity_snapshot(changed, now), result)

    def test_missing_or_duplicate_history_does_not_imply_zero_volume(self):
        rows = [Bar(t, 100, 101, 99, 100, 1) for t in range(2640, 3540, 60)]
        self.assertIsNone(capacity_snapshot(rows[:-1], 3600))
        self.assertIsNone(capacity_snapshot(rows+[rows[-1]], 3600))

    def test_quantity_cap_reduces_orders_without_changing_inputs(self):
        data, features = macro_fixture()
        original = copy.deepcopy(features)
        caps = {(s, b.t): dict(asof=b.t-60, quantity_cap=.06) for s, d in data.items() for b in d["trade"]}
        result = replay(data, features, strategy="macro_tactical", gross_cap=3, risk_fraction=.2,
                        account_controls=False, entry_liquidity_caps=caps)
        self.assertGreater(len(result["trades"]), 0)
        self.assertTrue(all(t["quantity"] <= .06 for t in result["trades"]))
        self.assertEqual(features, original)

    def test_minimum_order_is_never_rounded_up_to_override_capacity(self):
        data, features = macro_fixture()
        caps = {(s, b.t): dict(asof=b.t-60, quantity_cap=.02) for s, d in data.items() for b in d["trade"]}
        result = replay(data, features, strategy="macro_tactical", gross_cap=3, risk_fraction=.2,
                        account_controls=False, entry_liquidity_caps=caps)
        self.assertEqual(len(result["trades"]), 0)
        self.assertGreater(result["summary"]["rejections"]["minimum_order"], 0)

    def test_missing_context_fails_closed_and_future_context_raises(self):
        data, features = macro_fixture()
        args = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.2, account_controls=False)
        result = replay(data, features, entry_liquidity_caps={}, **args)
        self.assertEqual(len(result["trades"]), 0)
        self.assertGreater(result["summary"]["rejections"]["liquidity_unknown"], 0)
        caps = {(s, b.t): dict(asof=b.t, quantity_cap=1) for s, d in data.items() for b in d["trade"]}
        with self.assertRaisesRegex(ValueError, "future_liquidity_context"):
            replay(data, features, entry_liquidity_caps=caps, **args)

    def test_larger_gap_reserve_reduces_risk_allocation(self):
        data, features = macro_fixture()
        normal = replay(data, features, strategy="macro_tactical", gross_cap=20, risk_fraction=.2,
                        account_controls=False, exchange_leverage=50)
        buffered = replay(data, features, strategy="macro_tactical", gross_cap=20, risk_fraction=.2,
                          account_controls=False, exchange_leverage=50, sizing_gap_reserve=.03)
        a, b = normal["trades"][0], buffered["trades"][0]
        self.assertLess(b["quantity"], a["quantity"])
        self.assertEqual(b["sizing_gap_reserve"], .03)
        self.assertLessEqual(b["stress_risk_usdt"], b["risk_budget_usdt"]+1e-9)

    def test_quote_guard_prices_worst_fill_and_caps_depth(self):
        data, _ = macro_fixture()
        rule = data["SPYUSDT"]["rule"]
        depth = dict(E=1000, bids=[["99.99", "100"]], asks=[["100.01", "4"], ["101", "100"]])
        result = guarded_long_quote(rule, depth, 1001, 3, .0007)
        self.assertEqual(result["status"], "research_quote_only")
        self.assertLessEqual(result["quantity"], 1)
        self.assertLessEqual(result["price_limit"], result["mid"]*1.0025)
        self.assertLessEqual(result["worst_price_stress_risk"], 2)
        self.assertEqual(result["time_in_force"], "IOC")
        self.assertFalse(result["orders_authorized"])
        self.assertFalse(result["signal_evaluated"])

    def test_quote_guard_rejects_wide_spread_stale_and_small_depth(self):
        data, _ = macro_fixture()
        rule = data["SPYUSDT"]["rule"]
        wide = dict(E=1000, bids=[["99", "100"]], asks=[["101", "100"]])
        self.assertEqual(guarded_long_quote(rule, wide, 1001, 3, .0007)["status"], "insufficient_depth_within_price_limit")
        small = dict(E=1000, bids=[["99.99", "100"]], asks=[["100.01", ".01"]])
        self.assertEqual(guarded_long_quote(rule, small, 1001, 3, .0007)["status"], "minimum_order")
        self.assertEqual(guarded_long_quote(rule, small, 4000, 3, .0007)["status"], "stale_or_unknown_quote")


if __name__ == "__main__":
    unittest.main()
