"""Causal lease reviews, lifetime debit budgets and a hard holding deadline."""
import copy
import datetime as dt
import unittest

from qount.research.binance_etf_leverage import replay
from qount.research.binance_macro_funding_lease import review_lease
from qount.research.binance_macro_setup import setup_policies
from qount.research.small_account_breakout import Bar, NY
from test_binance_macro_attack import macro_fixture


class TestFundingLease(unittest.TestCase):
    def review(self, **kwargs):
        order = dict(quantity=1, entry_price=100, stop=95, margin_usdt=20,
                     risk_budget_usdt=15, funding_adverse_paid=0, funding_cost_cap_usdt=1)
        order.update(kwargs.pop("order", {}))
        args = dict(now=1000, price=100, equity=100, cash=100, reserve=.001,
                    hours=168, eligible=True, fee=.0005, slip=.0025, risk_fraction=.5, gap=.03)
        return review_lease(order, **{**args, **kwargs})

    def test_sufficient_cash_and_lifetime_cost_risk_budgets_allow_renewal(self):
        r = self.review()
        self.assertTrue(r["allowed"])
        self.assertAlmostEqual(r["forecast_cost"], .1)
        self.assertLessEqual(r["stress_risk"], r["risk_budget"])

    def test_paid_adverse_funding_consumes_lifetime_allowance(self):
        r = self.review(order=dict(funding_adverse_paid=.95))
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "lease_cost_budget")

    def test_original_risk_headroom_can_fund_costs_without_expanding_total_budget(self):
        self.assertEqual(self.review(reserve=.02)["reason"], "lease_cost_budget")
        headroom = 15-self.review(reserve=0)["stress_risk"]
        r = self.review(order=dict(funding_cost_cap_usdt=headroom), reserve=.02)
        self.assertTrue(r["allowed"])
        self.assertLessEqual(r["stress_risk"], 15)

    def test_marked_profit_does_not_substitute_for_free_cash(self):
        r = self.review(equity=1000, cash=20.05)
        self.assertFalse(r["allowed"])
        self.assertEqual(r["reason"], "lease_cash_budget")

    def test_unknown_state_forecast_and_reduced_risk_budget_fail_closed(self):
        self.assertEqual(self.review(eligible=False)["reason"], "lease_regime_off")
        self.assertEqual(self.review(reserve=None)["reason"], "lease_funding_unknown")
        self.assertEqual(self.review(order=dict(risk_budget_usdt=5))["reason"], "lease_risk_budget")

    def fixture(self, extend=False):
        data, features = macro_fixture()
        for rows in features.values():
            for r in rows:
                r.update(tactical_setup="mean_reversion", hold_structural=True)
        for d in data.values():
            for r in d["funding"]:
                r["fundingRate"] = "0"
        if extend:
            for s, d in data.items():
                start = d["trade"][-1].t+3600
                extra = [Bar(t, 100, 101, 99, 100, 10000, 1000000) for t in range(start, start+21*86400, 3600)]
                d["trade"] = d["trade"]+extra
                d["mark"] = d["mark"]+extra
                d["funding"] += [dict(fundingTime=b.t*1000+1, fundingRate="0", markPrice="100", rateType="Regular")
                                 for b in extra if b.t % (8*3600) == 0]
                template = features[s][-1]
                later = {}
                for b in extra:
                    date = dt.datetime.fromtimestamp(b.t, NY).date()
                    available = int(dt.datetime.combine(date, dt.time(16), NY).timestamp())
                    if date.weekday() < 5 and available > template["available"]:
                        later[available] = {**template, "available": available, "date": date.isoformat()}
                features[s] += [later[k] for k in sorted(later)]
        return data, features

    def run_lease(self, data, features, **extra):
        return replay(data, features, strategy="macro_tactical", gross_cap=3, risk_fraction=.2,
                      account_controls=False, funding_policy="debit_stress", sizing_gap_reserve=.03,
                      tactical_setup_policies=setup_policies(7, 21), funding_lease_hours=168, **extra)

    def test_entry_and_renewal_use_seven_days_and_never_extend_beyond_twenty_one(self):
        data, features = self.fixture(extend=True)
        first = self.run_lease(data, features)["trades"][0]
        self.assertEqual(first["funding_reserve_hours"], 168)
        self.assertEqual(first["max_hold_hours"], 504)
        self.assertEqual(first["exit_reason"], "time_exit")
        self.assertEqual(first["exit_time"]-first["entry_time"], 504*3600)
        self.assertEqual([r["time"]-first["entry_time"] for r in first["funding_lease_reviews"]], [168*3600, 336*3600])
        self.assertTrue(all(r["allowed"] and r["forecast_hours"] == 168 for r in first["funding_lease_reviews"]))

    def test_risk_headroom_allowance_is_derived_at_entry_and_never_reset(self):
        data, features = self.fixture(extend=True)
        t = self.run_lease(data, features, funding_lease_budget="risk")["trades"][0]
        base = t["stress_risk_usdt"]-t["notional_usdt"]*t["funding_reserve_fraction"]
        self.assertAlmostEqual(t["funding_cost_cap_usdt"], t["risk_budget_usdt"]-base)
        self.assertTrue(all(r["funding_cost_cap"] == t["funding_cost_cap_usdt"] for r in t["funding_lease_reviews"]))

    def test_partial_listing_history_never_backfills_prices_or_bypasses_atr_warmup(self):
        data, features = self.fixture(extend=True)
        listing = data["QQQUSDT"]["trade"][24*21].t
        for kind in ("trade", "mark"):
            data["QQQUSDT"][kind] = [b for b in data["QQQUSDT"][kind] if b.t >= listing]
        before = copy.deepcopy(data)
        with self.assertRaisesRegex(ValueError, "partial_histories_require_opt_in"):
            self.run_lease(data, features)
        out = self.run_lease(data, features, allow_partial_histories=True)
        self.assertGreater(len(out["trades"]), 0)
        self.assertTrue(any(t["symbol"] == "QQQUSDT" for t in out["trades"]))
        for t in out["trades"]:
            if t["symbol"] == "QQQUSDT":
                self.assertGreaterEqual(t["entry_time"], listing+14*86400)
        self.assertEqual(data, before)

    def test_mark_trade_clock_mismatch_fails_before_replay(self):
        data, features = self.fixture()
        data["QQQUSDT"]["mark"] = data["QQQUSDT"]["mark"][1:]
        with self.assertRaisesRegex(ValueError, "contract_bar_clock_mismatch"):
            self.run_lease(data, features, allow_partial_histories=True)

    def test_future_settlement_cannot_change_prior_review_and_overspend_exits_next_hour(self):
        data, features = self.fixture()
        baseline = self.run_lease(data, features)["trades"][0]
        now = baseline["funding_lease_reviews"][0]["time"]
        changed = copy.deepcopy(data)
        d = changed[baseline["symbol"]]
        d["funding"].append(dict(fundingTime=now*1000+1, fundingRate=".02", markPrice="100", rateType="Regular"))
        d["funding"].sort(key=lambda r: int(r["fundingTime"]))
        out = self.run_lease(changed, features)["trades"][0]
        self.assertEqual(out["funding_lease_reviews"][0], baseline["funding_lease_reviews"][0])
        self.assertEqual(out["exit_reason"], "funding_cost_exit")
        self.assertEqual(out["exit_time"], now+3600)
        self.assertGreater(out["funding_adverse_paid"], out["funding_cost_cap_usdt"])


if __name__ == "__main__":
    unittest.main()
