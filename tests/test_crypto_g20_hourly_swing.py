import unittest

import numpy as np

from qount.research.crypto_g20_hourly_swing import (
    SwingRule, _winner, features, replay, trend_failure,
)


def panel(hours=40):
    base = np.linspace(100., 140., hours)
    prices = np.column_stack((base, base * .8))
    return dict(
        symbols=("BTCUSDT", "ETHUSDT"),
        times=np.arange(hours, dtype=np.int64) * 3600,
        open=prices.copy(), close=prices.copy(),
        mark_low=prices - 1., funding_value=np.zeros_like(prices),
        funding_debit=np.zeros_like(prices),
    )


class HourlySwingTest(unittest.TestCase):
    def test_hourly_features_do_not_read_future_suffix(self):
        p = panel()
        rule = SwingRule(rank_hours=2, trend_hours=4, mean_hours=6)
        expected = features(p, rule)
        p["close"][21:] = 1.
        changed = features(p, rule)
        for key in expected:
            np.testing.assert_allclose(changed[key][:21], expected[key][:21], equal_nan=True)

    def test_dual_failure_keeps_position_after_one_trend_leg_fails(self):
        p = panel()
        rule = SwingRule(rank_hours=2, trend_hours=4, mean_hours=6, exit_mode="dual")
        f = features(p, rule)
        f["trend_mean"][10, 0] = p["close"][10, 0] + 1.
        self.assertFalse(trend_failure(p, f, 10, 0, rule))
        self.assertTrue(trend_failure(p, f, 10, 0,
                                      SwingRule(rank_hours=2, trend_hours=4,
                                                mean_hours=6, exit_mode="either")))

    def test_untradeable_top_rank_does_not_fall_back(self):
        p = panel()
        rule = SwingRule(rank_hours=2, trend_hours=4, mean_hours=6, gross=1.)
        f = features(p, rule)
        # Make ETH the highest-ranked qualified contract, while its min notional
        # exceeds the complete wallet.
        f["rank_return"][10] = np.array([.1, .2])
        f["trend_return"][10] = np.array([.1, .1])
        f["trend_mean"][10] = np.array([90., 70.])
        filters = {
            "BTCUSDT": {"filters": [
                {"filterType": "MARKET_LOT_SIZE", "stepSize": ".001", "minQty": ".001", "maxQty": "1000"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ]},
            "ETHUSDT": {"filters": [
                {"filterType": "MARKET_LOT_SIZE", "stepSize": ".001", "minQty": ".001", "maxQty": "1000"},
                {"filterType": "MIN_NOTIONAL", "notional": "100"},
            ]},
        }
        self.assertEqual(_winner(p, f, 10, 11, 20., rule, 10., filters), (None, 0.0))

    def test_hourly_account_costs_funding_and_equity_reconcile(self):
        p = panel()
        p["funding_value"][11:15, 0] = .01
        p["funding_debit"][11:15, 0] = .01
        rule = SwingRule(rank_hours=2, trend_hours=4, mean_hours=6, gross=1.)
        f = features(p, rule)
        run = replay(p, f, rule, start=8 * 3600, end=16 * 3600,
                     capital=1000., cost_bp=10.)
        summary = run["summary"]
        self.assertEqual(summary["counts"]["entry"], 1)
        self.assertEqual(summary["counts"]["terminal_exit"], 1)
        self.assertAlmostEqual(summary["costs"], sum(row["costs"] for row in run["curve"]))
        self.assertAlmostEqual(summary["final_usdt"] - summary["initial_usdt"],
            summary["price_pnl"] + summary["funding_pnl"] - summary["costs"], places=7)

    def test_rule_rejects_noncausal_or_short_duration_configuration(self):
        with self.assertRaises(ValueError):
            SwingRule(rank_hours=100, trend_hours=50, mean_hours=60)
        with self.assertRaises(ValueError):
            SwingRule(exit_mode="rank")


if __name__ == "__main__":
    unittest.main()
