"""Economic, timing and path checks for offline full-account rotation."""
import unittest

import numpy as np

from qount.research.crypto_g20_rotation import (
    Rule, decision, features, qualifying_trend_breadth, replay, rounded_quantity,
)


def panel(days=145, assets=2):
    price = np.full((days, assets), 100.)
    return dict(symbols=tuple(f"COIN{j}" for j in range(assets)),
                dates=(np.datetime64("2021-01-01") + np.arange(days)).astype(str),
                open=price.copy(), close=price.copy(), high=price+1, low=price-1,
                mark_low=price-1, mark_high=price+1, funding_value=np.zeros_like(price),
                funding_debit=np.zeros_like(price), funding_credit=np.zeros_like(price))


class RotationTest(unittest.TestCase):
    def test_entry_exit_and_funding_self_finance(self):
        p = panel()
        p["funding_value"][130, 0] = .5
        r = replay(p, features(p), Rule(gross=3, trend=False), start=p["dates"][130],
                   end=p["dates"][131], cost_bp=10)
        q = 3000 / (1.003 * 100)
        self.assertAlmostEqual(r["summary"]["final_usdt"], 1000 - q * .5 - q * 100 * .002)
        self.assertAlmostEqual(r["summary"]["funding_pnl"], -q * .5)

    def test_signal_observation_waits_full_extra_day(self):
        p = panel()
        p["close"][128, 1] = 120
        a = replay(p, features(p), Rule(gross=1, trend=False), start=p["dates"][130], end=p["dates"][131])
        p["close"][129:, 0] = 10000
        b = replay(p, features(p), Rule(gross=1, trend=False), start=p["dates"][130], end=p["dates"][131])
        self.assertEqual(a["trades"], b["trades"])
        self.assertEqual(a["trades"][0]["symbol"], "COIN1")

    def test_real_mark_low_can_liquidate_without_trade_low(self):
        p = panel()
        p["mark_low"][130] = 60
        r = replay(p, features(p), Rule(gross=3, trend=False), start=p["dates"][130], end=p["dates"][131], cost_bp=0)
        self.assertEqual(r["summary"]["final_usdt"], 0)
        self.assertEqual(r["summary"]["counts"]["liquidations"], 1)
        self.assertEqual(r["summary"]["mdd_pct"], 100)

    def test_stop_and_liquidation_order_bounds_are_explicit(self):
        p = panel()
        p["mark_low"][130] = p["low"][130] = 60
        f = features(p)
        rule = Rule(gross=3, trend=False, stop_atr=3)
        kwargs = dict(start=p["dates"][130], end=p["dates"][131], cost_bp=0)
        pessimistic = replay(p, f, rule, **kwargs)
        optimistic = replay(p, f, rule, ambiguous_path="stop_first", **kwargs)
        self.assertEqual(pessimistic["summary"]["final_usdt"], 0)
        self.assertAlmostEqual(optimistic["summary"]["final_usdt"], 820)
        self.assertEqual(optimistic["summary"]["counts"]["ambiguous_stop_liquidation_days"], 1)

    def test_stop_never_claims_unknown_intraday_funding_credit(self):
        p = panel()
        p["low"][130] = 90
        p["funding_value"][130] = -10
        p["funding_debit"][130] = .2
        r = replay(p, features(p), Rule(gross=1, trend=False, stop_atr=3),
                   start=p["dates"][130], end=p["dates"][131], cost_bp=0)
        self.assertAlmostEqual(r["summary"]["funding_pnl"], -2)
        self.assertAlmostEqual(r["summary"]["final_usdt"], 938)

    def test_features_and_winner_ignore_future_suffix(self):
        rng = np.random.default_rng(12)
        p = panel()
        p["close"] *= np.exp(np.cumsum(rng.normal(0, .01, p["close"].shape), axis=0))
        a = features(p)
        prefix = {k: v[:132] if isinstance(v, np.ndarray) else v for k, v in p.items()}
        b = features(prefix)
        for name in a:
            np.testing.assert_allclose(a[name][:132], b[name], equal_nan=True)
        self.assertEqual(decision(p, a, 130, Rule()), decision(prefix, b, 130, Rule()))

    def test_minimum_order_skips_winner_without_cheaper_fallback(self):
        p = panel()
        filters = {s: dict(filters=[dict(filterType="MARKET_LOT_SIZE", stepSize=".1", minQty=".1", maxQty="1000"),
                                   dict(filterType="MIN_NOTIONAL", notional=str(n))])
                   for s,n in zip(p["symbols"], (50, 5))}
        self.assertEqual(rounded_quantity(45, 100, "COIN0", filters), 0)
        self.assertAlmostEqual(rounded_quantity(45, 100, "COIN1", filters), .4)
        r = replay(p, features(p), Rule(gross=3, trend=False), capital=15.27, filters=filters,
                   start=p["dates"][130], end=p["dates"][131])
        self.assertEqual(r["summary"]["final_usdt"], 15.27)
        self.assertEqual(r["trades"], [])
        self.assertEqual(r["summary"]["counts"]["minimum_order_skip"], 1)

    def test_short_profit_and_positive_funding_are_signed(self):
        p = panel()
        p["close"][128, 0] = 80
        p["open"][131, 0] = 90
        p["funding_value"][130, 0] = 1
        r = replay(p, features(p), Rule(gross=3, direction="both", trend=False),
                   start=p["dates"][130], end=p["dates"][131], cost_bp=0)
        self.assertEqual(r["trades"][0]["side"], "SELL")
        self.assertAlmostEqual(r["summary"]["final_usdt"], 1330)
        self.assertAlmostEqual(r["summary"]["funding_pnl"], 30)
        p["mark_high"][130, 0] = 140
        wiped = replay(p, features(p), Rule(gross=3, direction="both", trend=False),
                       start=p["dates"][130], end=p["dates"][131], cost_bp=0)
        self.assertEqual(wiped["summary"]["final_usdt"], 0)

    def test_hourly_clock_does_not_annualize_as_daily(self):
        p = panel()
        p["dates"] = (np.datetime64("2025-01-01T00", "h") + np.arange(145)).astype(str)
        p["periods_per_year"] = 8766.
        r = replay(p, features(p), Rule(cadence="6h", gross=1, trend=False),
                   start=p["dates"][130], end=p["dates"][131], cost_bp=0)
        self.assertEqual(r["summary"]["bar_hours"], 1.)
        self.assertEqual(r["summary"]["cagr_pct"], 0.)

    def test_resize_order_minimum_applies_to_delta(self):
        p = panel(assets=1)
        filters = {"COIN0": dict(filters=[dict(filterType="MARKET_LOT_SIZE", stepSize=".001", minQty=".001", maxQty="1000"),
                                         dict(filterType="MIN_NOTIONAL", notional="20")])}
        # May11 is Tuesday and May18 is the next Tuesday execution of Sunday
        # close. The small funding debit creates a sub-minimum rebalance.
        p["funding_value"][130, 0] = .1
        r = replay(p, features(p), Rule(gross=1, trend=False), capital=100,
                   start=p["dates"][130], end=p["dates"][138], filters=filters, cost_bp=0)
        self.assertGreater(r["summary"]["counts"].get("minimum_resize_skip", 0), 0)
        self.assertEqual(len(r["trades"]), 1)

    def test_inverse_keeps_exit_trigger_and_pays_costs_again(self):
        p = panel()
        p["low"][130] = 90
        rule = Rule(gross=1, trend=False, stop_atr=3)
        kwargs = dict(start=p["dates"][130], end=p["dates"][131], cost_bp=10)
        original = replay(p, features(p), rule, **kwargs)
        inverse = replay(p, features(p), rule, reverse_execution=True, **kwargs)
        self.assertEqual(original["summary"]["counts"]["stop_exit"], 1)
        self.assertEqual(inverse["summary"]["counts"]["stop_exit"], 1)
        self.assertEqual(original["trades"][0]["side"], "BUY")
        self.assertEqual(inverse["trades"][0]["side"], "SELL")
        self.assertEqual(original["trades"][1]["price"], inverse["trades"][1]["price"])
        self.assertAlmostEqual(original["summary"]["final_usdt"] + inverse["summary"]["final_usdt"],
                               2000 - original["summary"]["costs"] - inverse["summary"]["costs"])

    def test_inverse_uses_its_own_adverse_mark_and_funding_side(self):
        p = panel()
        p["funding_value"][130, 0] = 1.
        kwargs = dict(start=p["dates"][130], end=p["dates"][131], cost_bp=0)
        inverse = replay(p, features(p), Rule(gross=3, trend=False), reverse_execution=True, **kwargs)
        self.assertAlmostEqual(inverse["summary"]["funding_pnl"], 30.)
        self.assertAlmostEqual(inverse["summary"]["final_usdt"], 1030.)
        p["mark_high"][130, 0] = 140
        inverse = replay(p, features(p), Rule(gross=3, trend=False), reverse_execution=True, **kwargs)
        self.assertEqual(inverse["summary"]["final_usdt"], 0.)


class DailyEntryDesignTest(unittest.TestCase):
    def test_funding_filter_is_prefix_causal_and_excludes_current_reference(self):
        p = panel()
        p["daily_rate"] = np.arange(145.)[:, None] * np.ones((1, 2))
        full = features(p)
        prefix = {k: v[:132] if isinstance(v, np.ndarray) else v for k, v in p.items()}
        partial = features(prefix)
        for name in full:
            np.testing.assert_allclose(full[name][:132], partial[name], equal_nan=True)
        self.assertFalse(full["funding_cool"][130, 0])
        p["daily_rate"][124:131] = -1000.
        self.assertTrue(features(p)["funding_cool"][130, 0])

    def test_entry_filter_does_not_fall_back_to_another_coin(self):
        p = panel()
        p["close"][:, 0] = np.linspace(100, 200, 145)
        p["close"][:, 1] = np.linspace(100, 150, 145)
        p["close"][125, 1] = 180.
        f = features(p)
        self.assertEqual(decision(p, f, 128, Rule(gross=1))[0], 0)
        self.assertEqual(decision(p, f, 128, Rule(gross=1, entry_filter="pullback")), (None, 0.))

    def test_fixed_horizon_keeps_original_entry_despite_later_trend_failure(self):
        p = panel()
        p["close"][:] = np.linspace(100, 200, 145)[:, None]
        p["close"][129:] = 80.
        f = features(p)
        kwargs = dict(start=p["dates"][130], end=p["dates"][139], cost_bp=0)
        regular = replay(p, f, Rule(gross=1), **kwargs)
        fixed = replay(p, f, Rule(gross=1, trend_exit=False, max_hold_bars=7), **kwargs)
        self.assertEqual(regular["summary"]["counts"]["trend_exit"], 1)
        exits = [r for r in fixed["trades"] if r["reason"] == "time_exit"]
        self.assertEqual(exits[0]["holding_bars"], 7)
        self.assertEqual(exits[0]["date"], p["dates"][137])

    def test_btc_gate_exits_weekly_book_on_daily_clock_after_delay(self):
        p = panel()
        p["symbols"] = ("BTCUSDT", "ALTUSDT")
        p["close"][:, 0] = np.linspace(100, 140, 145)
        p["close"][:, 1] = np.linspace(100, 200, 145)
        p["close"][129:, 0] = 50.
        r = replay(p, features(p), Rule(gross=1, market_trend=True),
                   start=p["dates"][130], end=p["dates"][133], cost_bp=0)
        self.assertEqual(r["trades"][0]["symbol"], "ALTUSDT")
        exits = [t for t in r["trades"] if t["reason"] == "market_exit"]
        self.assertEqual(exits[0]["date"], p["dates"][131])
        self.assertEqual(exits[0]["signal_date"], p["dates"][129])
        self.assertEqual(r["summary"]["active_days"], 1)

    def test_volatility_sizes_actual_exposure_below_cap_and_accounts_for_fees(self):
        p = panel()
        f = features(p)
        f["sigma"][128] = .4
        rule = Rule(cadence="daily", gross=2, volatility_target=.6, trend=False)
        r = replay(p, f, rule, start=p["dates"][130], end=p["dates"][131], cost_bp=10)
        q = 1500 / (100 * 1.0015)
        self.assertAlmostEqual(r["trades"][0]["quantity"], q)
        self.assertAlmostEqual(r["curve"][0]["gross"], 1.5)
        self.assertAlmostEqual(r["summary"]["final_usdt"], 1000 - .2 * q)
        f["sigma"][128] = .1
        self.assertEqual(decision(p, f, 128, rule)[1], 2.)

    def test_breadth_overlay_raises_risk_only_after_cross_section_confirms(self):
        p = panel(assets=2)
        p["symbols"] = ("BTCUSDT", "ALTUSDT")
        p["close"][:, 0] = np.linspace(100, 200, len(p["dates"]))
        p["close"][:, 1] = np.linspace(100, 180, len(p["dates"]))
        f = features(p)
        f["sigma"][130] = .4
        rule = Rule(cadence="daily", gross=2, volatility_target=.6, trend=False,
                    risk_on_breadth=1., risk_on_gross=3., risk_on_volatility_target=1.5)
        self.assertEqual(qualifying_trend_breadth(p, f, 130, 63), 1.)
        self.assertEqual(decision(p, f, 130, rule)[1], 3.)

        p["close"][:, 1] = 100.
        f = features(p)
        f["sigma"][130] = .4
        self.assertEqual(qualifying_trend_breadth(p, f, 130, 63), .5)
        self.assertAlmostEqual(decision(p, f, 130, rule)[1], 1.5)
        cash_rule = Rule(cadence="daily", gross=3, volatility_target=1.5, trend=False,
                         market_trend=False, risk_off_breadth=1.)
        self.assertEqual(decision(p, f, 130, cash_rule), (None, 0.))

    def test_breadth_overlay_uses_only_the_signal_prefix(self):
        p = panel(assets=2)
        p["symbols"] = ("BTCUSDT", "ALTUSDT")
        p["close"][:, 0] = np.linspace(100, 200, len(p["dates"]))
        p["close"][:, 1] = np.linspace(100, 180, len(p["dates"]))
        original = {**p, "close": p["close"].copy()}
        original_features = features(original)
        p["close"][131:, :] = 1.
        changed = features(p)
        self.assertEqual(qualifying_trend_breadth(p, changed, 130, 63),
                         qualifying_trend_breadth(original, original_features, 130, 63))
        rule = Rule(
            cadence="daily", gross=2, volatility_target=.6, trend=False,
            risk_on_breadth=1., risk_on_gross=3., risk_on_volatility_target=1.5)
        self.assertEqual(decision(p, changed, 130, rule),
                         decision(original, original_features, 130, rule))

    def test_breadth_overlay_requires_complete_valid_configuration(self):
        with self.assertRaises(ValueError):
            Rule(risk_on_breadth=.7)
        with self.assertRaises(ValueError):
            Rule(risk_off_breadth=1.1)

    def test_long_entry_filter_rejects_undefined_short_semantics(self):
        with self.assertRaises(ValueError):
            Rule(direction="both", entry_filter="pullback")


if __name__ == "__main__":
    unittest.main()
