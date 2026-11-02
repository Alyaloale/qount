import unittest

import numpy as np

from qount.research.crypto_g20_hourly_portfolio import (
    PortfolioRule, _eligible, _ranked_candidates, replay,
)
from qount.research.crypto_g20_hourly_swing import features


class PortfolioSelectionTests(unittest.TestCase):
    def setUp(self):
        self.panel = {
            "symbols": ("ETHUSDT", "SOLUSDT", "SPYUSDT"),
            "close": np.ones((1, 3)),
        }
        self.rule = PortfolioRule(max_positions=2, core_mode="dual")

    def features(self, crypto=True, etf=True):
        rank = np.array([[.3, .2, .1]])
        trend = np.array([[.3, .2, .1 if etf else -.1]])
        mean = np.array([[0., 0., 0.]])
        close = np.array([[1., 1., 1.]])
        return {"rank_return": rank, "trend_return": trend, "trend_mean": mean}

    def test_missing_etf_does_not_replace_crypto_with_crypto(self):
        f = self.features(etf=False)
        self.assertEqual(_ranked_candidates(self.panel, f, 0, self.rule, {0}), [])

    def test_missing_core_is_filled_before_extra_slot(self):
        f = self.features()
        self.assertEqual(_ranked_candidates(self.panel, f, 0, self.rule, {0}), [2])

    def test_relaxed_core_tops_up_when_missing_group_unavailable(self):
        f = self.features(etf=False)
        relaxed = PortfolioRule(max_positions=2, core_mode="dual_relaxed")
        self.assertEqual(_ranked_candidates(self.panel, f, 0, relaxed, {0}), [1])

    def test_relaxed_core_still_prefers_missing_group(self):
        f = self.features()
        relaxed = PortfolioRule(max_positions=2, core_mode="dual_relaxed")
        self.assertEqual(_ranked_candidates(self.panel, f, 0, relaxed, {0}), [2])

    def test_rank_score_overrides_rank_return_ordering(self):
        f = self.features()
        f["rank_score"] = np.array([[.1, .2, .3]])
        pool = PortfolioRule(max_positions=2, core_mode="pool")
        self.assertEqual(_ranked_candidates(self.panel, f, 0, pool, {0}), [2])

    def test_max_crypto_caps_crypto_slots(self):
        f = self.features()
        capped = PortfolioRule(max_positions=3, core_mode="pool", max_crypto=1)
        self.assertEqual(_ranked_candidates(self.panel, f, 0, capped, set()), [0, 2])
        capped2 = PortfolioRule(max_positions=3, core_mode="pool", max_crypto=1)
        self.assertEqual(_ranked_candidates(self.panel, f, 0, capped2, {0}), [2])

    def test_min_trend_age_blocks_young_trends(self):
        f = self.features()
        f["trend_age"] = np.array([[5, 30, 40]])
        aged = PortfolioRule(max_positions=3, core_mode="pool", min_trend_age=20)
        self.assertEqual(_ranked_candidates(self.panel, f, 0, aged, set()), [1, 2])


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.panel = {"close": np.array([[1.0]])}
        self.f = {"rank_return": np.array([[-0.05]]),
                  "trend_return": np.array([[0.10]]),
                  "trend_mean": np.array([[0.50]])}

    def test_negative_rank_momentum_is_rejected_by_default(self):
        self.assertFalse(_eligible(self.panel, self.f, 0, 0,
                                   PortfolioRule(require_rank_positive=True)))

    def test_negative_rank_momentum_is_allowed_when_disabled(self):
        self.assertTrue(_eligible(self.panel, self.f, 0, 0,
                                  PortfolioRule(require_rank_positive=False)))


def _rising_panel(n=30, symbols=("ETHUSDT", "SPYUSDT")):
    close = 100.0 + np.arange(n, dtype=float)[:, None]
    close = np.repeat(close, len(symbols), axis=1)
    return dict(
        symbols=tuple(symbols),
        times=1_700_000_000 + np.arange(n, dtype=np.int64) * 3600,
        open=close.copy(), high=close + 1.0, low=close - 1.0,
        close=close, mark_low=close - 1.0,
        funding_value=np.zeros((n - 1, len(symbols))),
        funding_debit=np.zeros((n - 1, len(symbols))),
    )


class FractionSizingTests(unittest.TestCase):
    def setUp(self):
        self.panel = _rising_panel()
        self.rule = PortfolioRule(
            rank_hours=2, trend_hours=3, mean_hours=5, decision_hours=1,
            max_positions=2, position_gross=1.0, core_mode="pool",
            exit_mode="dual")

    def run_mode(self, position_mode):
        rule = PortfolioRule(**{**vars(self.rule),
                                "position_mode": position_mode})
        f = features(self.panel, rule)
        return replay(self.panel, f, rule, start=self.panel["times"][6],
                      end=self.panel["times"][-1], capital=100.0, cost_bp=0.0,
                      variable_clock=True)

    def test_fraction_mode_keeps_gross_at_target(self):
        run = self.run_mode("fraction")
        s = run["summary"]
        self.assertEqual(s["trades"], 2)
        gross = [row["gross"] for row in run["curve"] if row["gross"] > 0]
        self.assertTrue(gross)
        self.assertLess(max(abs(g - 2.0) for g in gross), 0.05)
        self.assertTrue(s["path_evidence"])

    def test_fixed_mode_dilutes_gross_when_equity_grows(self):
        run = self.run_mode("fixed")
        s = run["summary"]
        self.assertEqual(s["trades"], 2)
        gross = [row["gross"] for row in run["curve"] if row["gross"] > 0]
        self.assertLess(gross[-1], gross[0])
        self.assertLess(gross[-1], 1.9)

    def test_statistics_fields_are_reported(self):
        s = self.run_mode("fixed")["summary"]
        self.assertEqual(s["symbols_traded"], 2)
        self.assertEqual(s["symbol_trades"], {"ETHUSDT": 1, "SPYUSDT": 1})
        self.assertTrue(s["path_evidence"])
        self.assertIsNotNone(s["top1_positive_pnl_share"])


class RiskParityTests(unittest.TestCase):
    def setUp(self):
        self.panel = _rising_panel()
        self.rule = PortfolioRule(
            rank_hours=2, trend_hours=3, mean_hours=5, decision_hours=1,
            max_positions=2, position_gross=2.0, core_mode="pool",
            exit_mode="dual", position_mode="risk_parity")

    def test_inverse_vol_gives_smaller_notional_to_higher_vol(self):
        f = features(self.panel, self.rule)
        n = len(self.panel["times"])
        # ETH at 2x SPY vol must receive half the notional of SPY.
        vol = np.zeros((n, 2))
        vol[:, 0] = 0.40
        vol[:, 1] = 0.20
        run = replay(self.panel, f, self.rule, start=self.panel["times"][6],
                     end=self.panel["times"][-1], capital=100.0, cost_bp=0.0,
                     variable_clock=True, vol=vol)
        buys = [fl for fl in run["fills"] if fl["side"] == "BUY"]
        self.assertEqual(len(buys), 2)
        q = {fl["symbol"]: fl["quantity"] * fl["price"] for fl in buys}
        self.assertAlmostEqual(q["ETHUSDT"] / q["SPYUSDT"], 0.5, places=6)
        # Total book gross equals position_gross (2.0) at entry.
        self.assertAlmostEqual(q["ETHUSDT"] + q["SPYUSDT"], 200.0, places=6)

    def test_min_notional_slot_stays_empty(self):
        f = features(self.panel, self.rule)
        n = len(self.panel["times"])
        vol = np.zeros((n, 2))
        vol[:, 0] = 0.40
        vol[:, 1] = 0.20
        filters = {"ETHUSDT": {"filters": [
            {"filterType": "MARKET_LOT_SIZE", "minQty": 0.001, "stepSize": 0.001, "maxQty": 1000},
            {"filterType": "MIN_NOTIONAL", "notional": 1000}]},
            "SPYUSDT": {"filters": [
                {"filterType": "MARKET_LOT_SIZE", "minQty": 0.001, "stepSize": 0.001, "maxQty": 1000},
                {"filterType": "MIN_NOTIONAL", "notional": 5}]}}
        run = replay(self.panel, f, self.rule, start=self.panel["times"][6],
                     end=self.panel["times"][-1], capital=100.0, cost_bp=0.0,
                     filters=filters, variable_clock=True, vol=vol)
        buys = [fl for fl in run["fills"] if fl["side"] == "BUY"]
        self.assertEqual([fl["symbol"] for fl in buys], ["SPYUSDT"])
        self.assertGreaterEqual(run["summary"]["counts"].get("minimum_notional_skip", 0), 1)

    def test_held_slot_below_min_notional_is_closed_to_cash(self):
        # Contract: a below-minimum slot is cash, not a frozen stale lot.
        # ETH enters at 50/50 risk (target 100 >= 50), then its vol explodes
        # so the resize target collapses below MIN_NOTIONAL and the slot must
        # be closed instead of keeping the old quantity.
        f = features(self.panel, self.rule)
        n = len(self.panel["times"])
        vol = np.zeros((n, 2))
        vol[:, :] = 0.20
        vol[7:, 0] = 10.0
        filters = {"ETHUSDT": {"filters": [
            {"filterType": "MARKET_LOT_SIZE", "minQty": 0.001, "stepSize": 0.001, "maxQty": 1000},
            {"filterType": "MIN_NOTIONAL", "notional": 50}]},
            "SPYUSDT": {"filters": [
                {"filterType": "MARKET_LOT_SIZE", "minQty": 0.001, "stepSize": 0.001, "maxQty": 1000},
                {"filterType": "MIN_NOTIONAL", "notional": 50}]}}
        run = replay(self.panel, f, self.rule, start=self.panel["times"][6],
                     end=self.panel["times"][-1], capital=100.0, cost_bp=0.0,
                     filters=filters, variable_clock=True, vol=vol)
        eth = [fl for fl in run["fills"] if fl["symbol"] == "ETHUSDT"]
        self.assertEqual([fl["side"] for fl in eth], ["BUY", "SELL"])
        self.assertEqual(eth[1]["reason"], "min_notional_exit")
        self.assertEqual(run["summary"]["counts"].get("min_notional_exit"), 1)
        spy = [fl for fl in run["fills"] if fl["symbol"] == "SPYUSDT"]
        self.assertEqual([fl["side"] for fl in spy], ["BUY", "SELL"])
        self.assertEqual(spy[1]["reason"], "terminal_exit")
        # Realized gross never exceeds the 2.0 target by more than rounding.
        self.assertLessEqual(run["summary"]["max_actual_gross"], 2.05)


def _crash_panel(n=40):
    """ETH trends up then crashes; SPY trends up steadily."""
    i = np.arange(n, dtype=float)
    eth = np.where(i < 14, 100.0 + i, 55.0)
    spy = 100.0 + 0.5 * i
    close = np.stack([eth, spy], axis=1)
    return dict(
        symbols=("ETHUSDT", "SPYUSDT"),
        times=1_700_000_000 + np.arange(n, dtype=np.int64) * 3600,
        open=close.copy(), high=close + 1.0, low=close - 1.0,
        close=close, mark_low=close - 1.0,
        funding_value=np.zeros((n - 1, 2)),
        funding_debit=np.zeros((n - 1, 2)),
    )


class DrawdownDeleverageTests(unittest.TestCase):
    def setUp(self):
        self.panel = _crash_panel()
        self.base = PortfolioRule(
            rank_hours=2, trend_hours=3, mean_hours=5, decision_hours=1,
            max_positions=2, position_gross=2.0, core_mode="pool",
            exit_mode="dual", position_mode="risk_parity")

    def run_rule(self, rule):
        f = features(self.panel, rule)
        n = len(self.panel["times"])
        vol = np.full((n, 2), 0.2)
        return replay(self.panel, f, rule, start=self.panel["times"][6],
                      end=self.panel["times"][-1], capital=100.0, cost_bp=0.0,
                      variable_clock=True, vol=vol)

    def test_invalid_dd_rule_rejected(self):
        with self.assertRaises(ValueError):
            PortfolioRule(**{**vars(self.base), "dd_deleverage_threshold": 1.5})
        with self.assertRaises(ValueError):
            PortfolioRule(**{**vars(self.base), "dd_deleverage_factor": 0.0})

    def test_drawdown_rule_halves_gross_after_loss(self):
        plain = self.run_rule(self.base)
        dd_rule = PortfolioRule(**{**vars(self.base),
                                   "dd_deleverage_threshold": 0.10,
                                   "dd_deleverage_factor": 0.5})
        scaled = self.run_rule(dd_rule)
        g_plain = [r["gross"] for r in plain["curve"] if r["gross"] > 0]
        g_scaled = [r["gross"] for r in scaled["curve"] if r["gross"] > 0]
        # After the ETH crash keeps equity far below highwater, the rule book
        # must sit at half the gross of the plain book.  The crash drawdown
        # itself is not prevented — the rule reacts at the next decision.
        self.assertGreater(len(g_scaled), 10)
        self.assertAlmostEqual(g_scaled[-1] / g_plain[-1], 0.5, places=2)


class CryptoCostStressTests(unittest.TestCase):
    def test_crypto_surcharge_raises_book_costs(self):
        panel = _rising_panel()
        rule = PortfolioRule(
            rank_hours=2, trend_hours=3, mean_hours=5, decision_hours=1,
            max_positions=2, position_gross=1.0, core_mode="pool",
            exit_mode="dual", position_mode="risk_parity")
        f = features(panel, rule)
        n = len(panel["times"])
        vol = np.full((n, 2), 0.2)

        def run(crypto_cost_bp):
            return replay(panel, f, rule, start=panel["times"][6],
                          end=panel["times"][-1], capital=100.0, cost_bp=0.0,
                          variable_clock=True, vol=vol, crypto_cost_bp=crypto_cost_bp)

        plain = run(None)
        stressed = run(10.0)
        # Zero base cost: only the crypto leg pays, ETF leg stays free.
        self.assertEqual(plain["summary"]["costs"], 0.0)
        self.assertGreater(stressed["summary"]["costs"], 0.0)
        self.assertGreater(stressed["summary"]["attribution"]["ETHUSDT"]["costs"], 0.0)
        self.assertEqual(stressed["summary"]["attribution"]["SPYUSDT"]["costs"], 0.0)


if __name__ == "__main__":
    unittest.main()
