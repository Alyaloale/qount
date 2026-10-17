"""Causality and account checks for the isolated ETF perpetual experiment."""
import datetime as dt
import unittest
from unittest.mock import patch

from qount.research.binance_etf_leverage import feature_at, funding_reserve, replay
from qount.research.small_account_breakout import Bar, NY, session


def fixture():
    start = int(dt.datetime(2026, 4, 7, tzinfo=dt.timezone.utc).timestamp())
    times = list(range(start, start+28*86400, 3600))
    features, data = {}, {}
    for s in ("SPYUSDT", "QQQUSDT"):
        bars = [Bar(t, 100, 101, 99, 100, 10000, 1000000) for t in times]
        data[s] = {"trade": bars, "mark": bars,
                   "funding": [{"fundingTime": t*1000+1, "fundingRate": "0.0001",
                                "markPrice": "100", "rateType": "Regular"}
                               for t in times if t % (8*3600) == 0],
                   "rule": {"liquidationFee": "0.01", "filters": [
                       {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                       {"filterType": "LOT_SIZE", "minQty": "0.01", "maxQty": "1000", "stepSize": "0.01"},
                       {"filterType": "MARKET_LOT_SIZE", "minQty": "0.01", "maxQty": "1000", "stepSize": "0.01"},
                       {"filterType": "MIN_NOTIONAL", "notional": "5"}]}}
        features[s] = []
        for d in range(-5, 29):
            date = dt.datetime.fromtimestamp(start+d*86400, NY).date()
            if date.weekday() >= 5:
                continue
            available = int(dt.datetime.combine(date, dt.time(16), NY).timestamp())
            features[s].append({"available": available, "date": date.isoformat(),
                                "eligible": True, "momentum120": 0.2 if s == "QQQUSDT" else 0.1})
    return data, features


class TestBinanceETFLeverage(unittest.TestCase):
    def test_future_equity_feature_is_not_read(self):
        rows = [{"available": 100, "eligible": False}, {"available": 200, "eligible": True}]
        self.assertFalse(feature_at(rows, 199)["eligible"])
        self.assertIsNone(feature_at(rows, 99))

    def test_funding_reserve_uses_only_prior_regular_settlements(self):
        rows = [{"fundingTime": 1000, "fundingRate": "0.001"},
                {"fundingTime": 2000, "fundingRate": "0.9"},
                {"fundingTime": 1001, "fundingRate": "-0.5", "rateType": "Special"}]
        self.assertAlmostEqual(funding_reserve(rows, 2, hours=16), 0.002)

    def test_observed_hourly_funding_interval_changes_reserve(self):
        now = 4*3600
        rows = [{"fundingTime": t*1000, "fundingRate": "0.001"} for t in (3600, 7200, 10800)]
        self.assertAlmostEqual(funding_reserve(rows, now, hours=16), 0.016)

    def test_long_debit_reserve_does_not_treat_credits_as_costs(self):
        now = 100*3600
        rows = [{"fundingTime": t*3600000, "fundingRate": "-0.001"}
                for t in range(28, 100, 8)]
        self.assertAlmostEqual(funding_reserve(rows, now, 168), 0.021)
        self.assertEqual(funding_reserve(rows, now, 168, "debit_peak"), 0)
        self.assertAlmostEqual(funding_reserve(rows, now, 168, "debit_stress"), 0.0007)

    def test_debit_stress_reserves_full_horizon_and_one_day_peak(self):
        now = 100*3600
        rows = [{"fundingTime": t*3600000, "fundingRate": "0.0001"}
                for t in range(28, 100, 8)]
        self.assertAlmostEqual(funding_reserve(rows, now, 168, "debit_stress"), 0.0042)
        for row in rows[:-1]:
            row["fundingRate"] = "0"
        self.assertAlmostEqual(funding_reserve(rows, now, 24, "debit_stress"), 0.0003)

    def test_debit_stress_is_causal_excludes_special_and_requires_history(self):
        now = 100*3600
        rows = [{"fundingTime": t*3600000, "fundingRate": "0.0001"}
                for t in range(28, 100, 8)]
        original = funding_reserve(rows, now, 168, "debit_stress")
        rows.extend([{"fundingTime": now*1000, "fundingRate": "1"},
                     {"fundingTime": (now-1)*1000, "fundingRate": "1", "rateType": "Special"}])
        self.assertEqual(funding_reserve(rows, now, 168, "debit_stress"), original)
        self.assertIsNone(funding_reserve(rows[-3:-2], now, 168, "debit_stress"))

    def test_funding_policy_validation_and_zero_horizon(self):
        with self.assertRaises(ValueError):
            funding_reserve([], 100, policy="unknown")
        with self.assertRaises(ValueError):
            funding_reserve([], 100, hours=-1)
        rows = [{"fundingTime": 0, "fundingRate": "0.1"}]
        self.assertEqual(funding_reserve(rows, 1, 0, "debit_stress"), 0)

    def test_costed_flat_market_loses_and_cash_reconciles(self):
        data, features = fixture()
        result = replay(data, features, gross_cap=2, risk_fraction=0.06)
        self.assertGreater(result["summary"]["trade_count"], 0)
        self.assertLess(result["summary"]["net_return"], 0)
        self.assertAlmostEqual(10+sum(t["net_pnl"] for t in result["trades"]), result["summary"]["final_equity"])
        for t in result["trades"]:
            self.assertLess(t["feature_available"], t["entry_time"])
            self.assertLessEqual(t["stress_risk_usdt"], t["risk_budget_usdt"]+1e-9)

    def test_future_price_changes_do_not_change_earlier_trades(self):
        data, features = fixture()
        original = replay(data, features, risk_fraction=0.06)
        first = original["trades"][0]
        for d in data.values():
            for kind in ("trade", "mark"):
                d[kind] = [b if b.t <= first["exit_time"] else Bar(b.t, 120, 121, 119, 120, b.v, b.q)
                           for b in d[kind]]
        changed = replay(data, features, risk_fraction=0.06)
        self.assertEqual(original["trades"][0], changed["trades"][0])

    def test_entry_hour_stop_is_active(self):
        data, features = fixture()
        initial = replay(data, features, risk_fraction=0.06)
        entry = initial["trades"][0]["entry_time"]
        s = initial["trades"][0]["symbol"]
        idx = next(i for i, b in enumerate(data[s]["trade"]) if b.t == entry)
        data[s]["trade"][idx] = Bar(entry, 100, 101, 94, 99, 10000, 1000000)
        data[s]["mark"][idx] = Bar(entry, 100, 101, 94, 99, 10000, 1000000)
        changed = replay(data, features, risk_fraction=0.06)
        self.assertEqual(changed["trades"][0]["exit_reason"], "stop")
        self.assertEqual(changed["trades"][0]["exit_time"], entry+3600)

    def test_expiry_does_not_wait_for_next_equity_session(self):
        data, features = fixture()
        original = replay(data, features, risk_fraction=0.06)
        expiry = original["trades"][0]["entry_time"]+7*86400
        with patch("qount.research.binance_etf_leverage.session",
                   side_effect=lambda t: None if t == expiry else session(t)):
            changed = replay(data, features, risk_fraction=0.06)
        self.assertEqual(changed["trades"][0]["exit_time"], expiry)
        self.assertEqual(changed["trades"][0]["exit_reason"], "seven_day_exit")

    def test_gross_cap_cannot_override_fixed_risk_budget(self):
        data, features = fixture()
        low = replay(data, features, gross_cap=2, risk_fraction=0.03)
        high = replay(data, features, gross_cap=3, risk_fraction=0.03)
        self.assertEqual(low["trades"], high["trades"])


if __name__ == "__main__":
    unittest.main()
