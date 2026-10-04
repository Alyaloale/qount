from __future__ import annotations

from dataclasses import replace
import unittest

import numpy as np

from qount.research.etf_alpha.execution import simulate
from qount.research.etf_alpha.postmortem import guard_output_location, ledger_components, prediction_components, selector_sensitivity
from qount.research.etf_trader.env import Decision
from test_etf_alpha_m1 import flat_fixture, prepared, ZERO_COSTS, NATURAL, SPY


class AttributionTests(unittest.TestCase):
    def test_prediction_components_separate_fixed_asset_and_date_effects(self):
        interaction = np.array([[1., -1.], [-1., 1.]])
        mu = 10 + np.array([-2., 2.])[None] + np.array([-3., 3.])[:, None] + interaction
        report = prediction_components(mu)
        self.assertEqual(report["asset_means"], [8., 12.])
        self.assertAlmostEqual(report["variance"], 14)
        for key, expected in (("asset", 4/14), ("date", 9/14), ("interaction", 1/14)):
            self.assertAlmostEqual(report["variance_fractions"][key], expected)
        self.assertLess(report["reconstruction_error"], 1e-12)

    def test_constant_panel_and_nonfinite_rejection(self):
        self.assertEqual(sum(prediction_components(np.ones((5, 9)))["variance_fractions"].values()), 0)
        with self.assertRaises(ValueError):
            prediction_components([[np.nan]])
        for output in ("/tmp/frozen-run", "/tmp/frozen-run/new-report"):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, "immutable source"):
                guard_output_location("/tmp/frozen-run", output)
        guard_output_location("/tmp/frozen-run", "/tmp/separate-report")

    def test_split_dividend_and_next_open_sale_reconcile(self):
        panel = flat_fixture(5)
        opn, close, splits, dividends = [getattr(panel, k).copy() for k in ("open", "close", "splits", "dividends")]
        # Buy at 125, mark at 100, then split 2:1 and sell at 55 with a
        # $1 ex-date entitlement on all 16,000 post-split shares.
        opn[1, 0] = 125
        splits[2, 0] = 2
        opn[2:, 0], close[2:, 0] = 55, 50
        dividends[2, 0] = 1
        panel = replace(panel, open=opn, close=close, splits=splits, dividends=dividends)
        result = simulate(panel, lambda o: Decision(SPY if o.t == 0 else np.zeros(9)), start=0,
                          stop=3, account=NATURAL, costs=ZERO_COSTS, inputs=prepared(panel))
        parts = ledger_components(panel, result, 3)
        self.assertAlmostEqual(parts["fill"][0, 0], -200_000)
        self.assertAlmostEqual(parts["dividend"][1, 0], 16_000)
        self.assertAlmostEqual(parts["fill"][1, 0], 80_000)
        self.assertAlmostEqual(result.equity[3], 896_000)
        self.assertLess(parts["maximum_identity_error"], 1e-6)

    def test_cost_and_cash_carry_are_counted_separately(self):
        panel = flat_fixture(5)
        cash = np.cumprod(np.full(5, 1.001))
        panel = replace(panel, cash_open=cash, cash_close=cash)
        costs = replace(ZERO_COSTS, commission_rate=0.0005)
        result = simulate(panel, lambda o: Decision(SPY*.5 if o.t == 0 else None), start=0,
                          stop=3, account=NATURAL, costs=costs, inputs=prepared(panel))
        parts = ledger_components(panel, result, 3)
        self.assertGreater(parts["cash_carry"].sum(), 0)
        self.assertLess(parts["costs"].sum(), 0)
        self.assertLess(parts["maximum_identity_error"], 1e-6)

    def test_corrupted_equity_cannot_get_a_valid_attribution(self):
        panel = flat_fixture(5)
        result = simulate(panel, lambda o: Decision(None), start=0, stop=3,
                          costs=ZERO_COSTS, inputs=prepared(panel))
        result.equity[2] += 1
        with self.assertRaises(ValueError):
            ledger_components(panel, result, 3)


class SelectorSensitivityTests(unittest.TestCase):
    def records(self):
        length = 120
        rng = np.random.default_rng(4)
        cash = np.full(length, .0001)
        underlying = rng.normal(.0007, .003, length)
        records, series = {}, {}
        for name, increment, params in (("E3-ridge-raw", .0002, 39), ("train-asset-mean", 0., 9),
                                         ("momentum120", -.0002, 0), ("cash", 0., 0),
                                         ("v2-rank-shuffle", -.0004, 31561)):
            r = cash if name == "cash" else underlying+increment
            excess = r-cash
            sd = excess.std(ddof=1)
            eq = np.r_[1., np.cumprod(1+r)]
            bridge = {"sharpe_excess_cash": float(excess.mean()*np.sqrt(252)/sd) if sd > 1e-14 else 0.,
                      "max_drawdown": float(np.max(1-eq/np.maximum.accumulate(eq))),
                      "max_rolling_voluntary": 0., "minimum_cash": 1., "forced_breaches": 0}
            count = 5 if name == "v2-rank-shuffle" else 1
            records[name] = [{"seed": 1000+i, "parameters": params, "bridge": {"2x": bridge.copy()},
                              "prediction": {"rank_ic": .1, "mu20_huber": .1}} for i in range(count)]
            series[name] = [{"returns": r.copy(), "cash": cash.copy(), "rank": np.full(length,.1),
                             "huber": np.full(length,.1)} for _ in range(count)]
        return records, series

    def test_shared_draws_preserve_dominant_winner_and_reproducibility(self):
        records, series = self.records()
        a = selector_sensitivity(records, series, samples=100, blocks=(20,40,60))
        b = selector_sensitivity(records, series, samples=100, blocks=(20,40,60))
        self.assertEqual(a, b)
        self.assertEqual(a["original_selected"], "E3-ridge-raw")
        for value in a["bootstrap"].values():
            self.assertEqual(value["original_winner_retained_fixed"], 1.)
            self.assertEqual(sum(value["recomputed_signal_gates_win_frequency"].values()), 1.)

    def test_utility_corruption_is_rejected_before_sensitivity(self):
        records, series = self.records()
        records["E3-ridge-raw"][0]["bridge"]["2x"]["max_drawdown"] += .01
        with self.assertRaisesRegex(ValueError, "utility mismatch"):
            selector_sensitivity(records, series, samples=10)


if __name__ == "__main__":
    unittest.main()
