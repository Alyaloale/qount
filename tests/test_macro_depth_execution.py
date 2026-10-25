"""Causality, partial-fill accounting and bounded historical execution checks."""
import copy
import math
import unittest

from qount.research.binance_etf_leverage import replay
from qount.research.macro_depth_execution import DepthExecution, DepthExitStress, limit_depth_lower_bound
import test_binance_macro_funding_lease as lease_fixtures


def levels(quantity=100., ask=100.01, bid=99.99):
    return {side*band: (quantity, quantity*(ask if side == 1 else bid))
            for side in (-1, 1) for band in (.2, 1., 2., 3., 4., 5.)}


class TestDepthBounds(unittest.TestCase):
    def setUp(self):
        self.rule = lease_fixtures.TestFundingLease().fixture()[0]["QQQUSDT"]["rule"]

    def test_bound_never_exceeds_exact_inside_limit_volume(self):
        asks = [(100.01, 4), (100.08, 6), (100.19, 2)]
        book = levels()
        for band in (.2, 1., 2., 3., 4., 5.):
            book[band] = (sum(q for p, q in asks), sum(p*q for p, q in asks))
        for limit in (99.9, 100, 100.02, 100.079, 100.08, 100.15, 100.2, 100.5):
            bound = limit_depth_lower_bound(book, limit)["quantity"]
            self.assertGreaterEqual(bound, 0)
            self.assertLessEqual(bound, sum(q for p, q in asks if p <= limit)+1e-8)
        self.assertEqual(limit_depth_lower_bound(book, 100.5)["quantity"], 12)

    def test_malformed_and_nonmonotonic_depth_fail(self):
        for book in ({}, levels(ask=99, bid=101), levels(quantity=math.nan)):
            with self.assertRaises(ValueError):
                limit_depth_lower_bound(book, 100.25)
        book = levels()
        book[1.] = (1, 100)
        with self.assertRaisesRegex(ValueError, "nonmonotonic"):
            limit_depth_lower_bound(book, 100.25)

    def test_sell_bound_never_exceeds_exact_inside_limit_volume(self):
        bids = [(99.99, 4), (99.92, 6), (99.81, 2)]
        book = levels()
        for band in (.2, 1., 2., 3., 4., 5.):
            book[-band] = (sum(q for p, q in bids), sum(p*q for p, q in bids))
        for limit in (99.5, 99.8, 99.81, 99.85, 99.92, 99.95, 99.99, 100.1):
            bound = limit_depth_lower_bound(book, limit, side=-1)["quantity"]
            self.assertGreaterEqual(bound, 0)
            self.assertLessEqual(bound, sum(q for p, q in bids if p >= limit)+1e-8)
        self.assertEqual(limit_depth_lower_bound(book, 99.5, side=-1)["quantity"], 12)

    def test_arrival_book_does_not_change_quote_or_submitted_quantity(self):
        key = ("QQQUSDT", 1000)
        rows = [dict(time=t, levels=levels(q)) for t, q in ((1005, 10), (1035, 1), (1065, 1000))]
        model = DepthExecution({key: rows})
        quote = model.quote(*key, 100.25, self.rule)
        changed = copy.deepcopy(rows)
        changed[1]["levels"] = levels(.04)
        other = DepthExecution({key: changed})
        self.assertEqual(quote, other.quote(*key, 100.25, self.rule))
        order = dict(quantity=1)
        receipt = model.fill(order, quote, self.rule)
        failed = other.fill(order, quote, self.rule)
        self.assertEqual(receipt["requested_quantity"], failed["requested_quantity"])
        self.assertGreater(receipt["filled_quantity"], failed["filled_quantity"])
        self.assertLess(receipt["filled_quantity"], order["quantity"])

    def test_minimum_notional_does_not_discard_a_valid_partial_fill(self):
        key = ("QQQUSDT", 1000)
        rows = [dict(time=1005, levels=levels(10)), dict(time=1035, levels=levels(.08))]
        model = DepthExecution({key: rows})
        quote = model.quote(*key, 100.25, self.rule)
        receipt = model.fill(dict(quantity=1), quote, self.rule)
        self.assertEqual(receipt["status"], "partial_fill")
        self.assertGreater(receipt["filled_quantity"], 0)
        self.assertLess(receipt["filled_quantity"]*receipt["fill_price"], 5)

    def test_no_snapshot_summing_and_no_fill_after_deadline(self):
        key = ("QQQUSDT", 1000)
        rows = [dict(time=t, levels=levels(.4)) for t in (1005, 1035, 1065, 1095)]
        model = DepthExecution({key: rows})
        quote = model.quote(*key, 100.25, self.rule)
        receipt = model.fill(dict(quantity=.1), quote, self.rule)
        self.assertLessEqual(receipt["filled_quantity"], .1)
        delayed = DepthExecution({key: rows}, latency_seconds=90).fill(dict(quantity=.1), quote, self.rule)
        self.assertEqual(delayed["status"], "arrival_after_deadline")
        self.assertEqual(delayed["filled_quantity"], 0)

    def test_future_only_quote_and_invalid_parameters(self):
        key = ("QQQUSDT", 1000)
        model = DepthExecution({key: [dict(time=1091, levels=levels())]})
        self.assertEqual(model.quote(*key, 100.25, self.rule)["status"], "quote_unavailable_before_deadline")
        for kwargs in (dict(fill_fraction=.5), dict(fill_fraction=-1), dict(latency_seconds=0),
                       dict(quote_fraction=math.nan)):
            with self.assertRaises(ValueError):
                DepthExecution({}, **kwargs)


class TestDepthReplay(unittest.TestCase):
    def fixture(self, arrival_quantity=1000):
        data, features = lease_fixtures.TestFundingLease().fixture(extend=True)
        contexts = {(s, b.t): [
            dict(time=b.t+5, levels=levels(1000)),
            dict(time=b.t+35, levels=levels(arrival_quantity)),
            dict(time=b.t+65, levels=levels(arrival_quantity))]
            for s, d in data.items() for b in d["trade"]}
        parameters = dict(strategy="macro_tactical", gross_cap=3, risk_fraction=.2,
            account_controls=False, funding_policy="debit_stress", sizing_gap_reserve=.03,
            tactical_setup_policies={setup: dict(max_hold_hours=hours, hold_feature=hold)
                for setup, hours, hold in (("breakout", 168, "hold_tactical"),
                    ("pullback", 168, "hold_tactical"), ("mean_reversion", 504, "hold_structural"))},
            funding_lease_hours=168, funding_lease_budget="risk")
        return data, features, contexts, parameters

    def test_partial_fill_scales_original_funding_cap_and_reconciles(self):
        data, features, contexts, params = self.fixture()
        full = replay(data, features, entry_execution_model=DepthExecution(contexts), **params)
        data, features, contexts, params = self.fixture(.08)
        partial = replay(data, features, entry_execution_model=DepthExecution(contexts), **params)
        a, b = full["trades"][0], partial["trades"][0]
        ratio = b["quantity"]/a["quantity"]
        self.assertLess(ratio, 1)
        self.assertAlmostEqual(b["funding_cost_cap_usdt"], a["funding_cost_cap_usdt"]*ratio)
        self.assertEqual(b["risk_budget_usdt"], a["risk_budget_usdt"])
        self.assertAlmostEqual(10+sum(t["net_pnl"] for t in partial["trades"]),
                               partial["summary"]["final_equity"])
        self.assertEqual(b["entry_fill_time"], b["entry_time"]+35)
        self.assertLess(b["quantity"]*b["entry_price"], 5)

    def test_no_fill_consumes_candidate_without_same_clock_fallback(self):
        data, features, contexts, params = self.fixture()
        result = replay(data, features, entry_execution_model=DepthExecution(contexts, fill_fraction=0), **params)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["summary"]["final_equity"], 10)
        clocks = [r["decision_time"] for r in result["execution_attempts"]]
        self.assertTrue(clocks)
        self.assertEqual(clocks, sorted(set(clocks)))

    def test_pre_fill_funding_not_charged_and_later_funding_is_charged(self):
        data, features, contexts, params = self.fixture()
        first = replay(data, features, entry_execution_model=DepthExecution(contexts), **params)["trades"][0]
        s, now = first["symbol"], first["entry_time"]
        data[s]["funding"].extend([
            dict(fundingTime=(now+10)*1000, fundingRate=".001", markPrice="100", rateType="Regular"),
            dict(fundingTime=(now+40)*1000, fundingRate=".001", markPrice="100", rateType="Regular")])
        data[s]["funding"].sort(key=lambda r: int(r["fundingTime"]))
        result = replay(data, features, entry_execution_model=DepthExecution(contexts), **params)["trades"][0]
        self.assertAlmostEqual(result["funding"], -.001*100*result["quantity"])

    def test_depth_sizing_can_replace_zero_volume_proxy_without_relaxing_risk(self):
        data, features, contexts, params = self.fixture()
        caps = {key: dict(asof=key[1]-60, quantity_cap=0) for key in contexts}
        original = replay(data, features, entry_liquidity_caps=caps,
                          entry_execution_model=DepthExecution(contexts), **params)
        self.assertEqual(original["trades"], [])
        changed = replay(data, features, entry_liquidity_caps=caps,
                         entry_execution_model=DepthExecution(contexts, use_depth_sizing=True), **params)
        self.assertTrue(changed["trades"])
        self.assertTrue(all(t["stress_risk_usdt"] <= t["risk_budget_usdt"] for t in changed["trades"]))


class TestExitDepthStress(unittest.TestCase):
    def test_full_quantity_requires_wider_bid_band(self):
        book = levels(100)
        for side in (-1, 1):
            for band in (1., 2., 3., 4., 5.):
                book[side*band] = (300, 300*(100.01 if side == 1 else 99.99))
        model = DepthExitStress({("QQQUSDT", 1000): [dict(time=1030, levels=book)]}, fraction=.01)
        small = model.execute(dict(symbol="QQQUSDT", quantity=.5), 1000, 100, "time_exit", .0025)
        large = model.execute(dict(symbol="QQQUSDT", quantity=1.5), 1000, 100, "time_exit", .0025)
        self.assertEqual(small["status"], "conditional_base_price")
        self.assertEqual(large["status"], "conditional_wider_band")
        self.assertEqual(large["band_percent"], 1.)
        self.assertLess(large["fill_price"], small["fill_price"])
        self.assertEqual(large["quantity"], 1.5)
        self.assertEqual(large["fill_time"], 1030)

    def test_missing_inconsistent_or_insufficient_depth_is_explicit_assumption(self):
        for rows, error in (([], "missing_exit_snapshot"),
                ([dict(time=1030, levels=levels(ask=99, bid=101))], "inconsistent_depth_midpoint"),
                ([dict(time=1030, levels=levels(.01))], "insufficient_discounted_depth")):
            model = DepthExitStress({("QQQUSDT", 1000): rows}, unknown_extra_slip=.02)
            r = model.execute(dict(symbol="QQQUSDT", quantity=1), 1000, 100, "time_exit", .0025)
            self.assertEqual(r["status"], "assumed_unknown_book_price")
            self.assertEqual(r["unknown_reason"], error)
            self.assertAlmostEqual(r["fill_price"], 100*.9975*.98)
            self.assertEqual(r["quantity"], 1)

    def test_delayed_exit_settlements_included_once_and_later_settlements_excluded(self):
        data, features, _, params = TestDepthReplay().fixture()
        baseline = replay(data, features, **params)["trades"][0]
        now, symbol = baseline["exit_time"], baseline["symbol"]
        data[symbol]["funding"].extend([
            dict(fundingTime=(now-1)*1000, fundingRate=".001", markPrice="100"),
            dict(fundingTime=(now+1)*1000, fundingRate=".002", markPrice="100"),
            dict(fundingTime=(now+31)*1000, fundingRate=".004", markPrice="100")])
        data[symbol]["funding"].sort(key=lambda r: int(r["fundingTime"]))
        immediate = replay(data, features, **params)
        delayed = replay(data, features, exit_execution_model=DepthExitStress({}, use_depth=False), **params)
        a, b = immediate["trades"][0], delayed["trades"][0]
        self.assertEqual(a["quantity"], b["quantity"])
        self.assertEqual(b["exit_fill_time"], now+30)
        self.assertAlmostEqual(b["funding"], -.003*100*b["quantity"])
        self.assertAlmostEqual(b["exit_execution"]["delayed_funding"], -.002*100*b["quantity"])
        self.assertAlmostEqual(b["net_pnl"]-a["net_pnl"], -.002*100*b["quantity"])
        self.assertAlmostEqual(10+sum(t["net_pnl"] for t in delayed["trades"]),
                               delayed["summary"]["final_equity"])
        self.assertEqual(immediate, replay(data, features, exit_execution_model=None, **params))

    def test_intrabar_clock_and_terminal_are_not_claimed_as_observed_exits(self):
        model = DepthExitStress({})
        p = dict(symbol="QQQUSDT", quantity=1)
        stop = model.execute(p, 1000, 100, "stop", .0025)
        terminal = model.execute(p, 1000, 100, "end_of_sample", .0025)
        self.assertEqual(stop["status"], "intrabar_clock_unknown")
        self.assertEqual(stop["fill_time"], 1000)
        self.assertEqual(terminal["status"], "terminal_valuation_not_execution")
        self.assertAlmostEqual(terminal["fill_price"], 99.75)

    def test_uniform_shock_covers_known_unknown_and_terminal_without_double_counting(self):
        context = {("QQQUSDT", 1000): [dict(time=1030, levels=levels(1000))]}
        model = DepthExitStress(context, unknown_extra_slip=0, all_extra_slip=.02)
        p = dict(symbol="QQQUSDT", quantity=1)
        known = model.execute(p, 1000, 100, "time_exit", .0025)
        unknown = DepthExitStress({("QQQUSDT", 1000): []}, unknown_extra_slip=0,
            all_extra_slip=.02).execute(p, 1000, 100, "time_exit", .0025)
        terminal = model.execute(p, 1000, 100, "end_of_sample", .0025)
        for receipt in (known, unknown, terminal):
            self.assertAlmostEqual(receipt["fill_price"], 99.75*.98)


if __name__ == "__main__":
    unittest.main()
