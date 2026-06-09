from __future__ import annotations

import random
import sys
import types
import unittest

if "ccxt" not in sys.modules:
    class _StubExchange:
        def __init__(self, options=None) -> None:
            self.options = options or {}

    sys.modules["ccxt"] = types.SimpleNamespace(binance=_StubExchange, binanceus=_StubExchange)

from qount.cta_eval import annualized_sharpe
from qount.cta_eval import deflated_sharpe
from qount.cta_eval import default_carry_grid
from qount.cta_eval import default_grid
from qount.cta_eval import pbo_cscv
from qount.cta_eval import per_period_sharpe
from qount.cta_eval import run_gate_scan
from qount.cta_eval import run_walkforward_eval
from qount.cta_eval import time_fold_sharpes
from qount.cta_sim import DEFAULT_UNIVERSE
from qount.cta_sim import generate_synthetic_carry_market
from qount.cta_sim import generate_synthetic_panel


def _noise_panel(n_assets: int, n_days: int, seed: int) -> dict[str, list[float]]:
    rng = random.Random(seed)
    names = [f"A{i}" for i in range(n_assets)]
    px = {n: 100.0 for n in names}
    series: dict[str, list[float]] = {n: [100.0] for n in names}
    for _ in range(n_days - 1):
        for n in names:
            px[n] *= 1.0 + rng.gauss(0.0, 0.01)  # zero drift, no trend regime
            series[n].append(px[n])
    return series


class SharpeHelpersTest(unittest.TestCase):
    def test_per_period_and_annualized(self) -> None:
        rets = [0.001, 0.002, -0.001, 0.0015, 0.0]
        pp = per_period_sharpe(rets)
        self.assertIsNotNone(pp)
        ann = annualized_sharpe(rets)
        self.assertAlmostEqual(ann, pp * (252 ** 0.5), places=9)

    def test_zero_vol_returns_none(self) -> None:
        self.assertIsNone(per_period_sharpe([0.0, 0.0, 0.0]))
        self.assertIsNone(per_period_sharpe([0.5]))


class DeflatedSharpeTest(unittest.TestCase):
    def test_probability_in_unit_interval(self) -> None:
        result = deflated_sharpe([0.02, 0.05, 0.08, 0.03, 0.06], best_period_count=1000)
        self.assertIsNotNone(result)
        dsr = result["deflated_sharpe_ratio"]
        self.assertGreaterEqual(dsr, 0.0)
        self.assertLessEqual(dsr, 1.0)

    def test_zero_variance_expected_max_zero(self) -> None:
        result = deflated_sharpe([0.04, 0.04, 0.04], best_period_count=500)
        self.assertEqual(result["expected_max_per_period_sharpe"], 0.0)

    def test_needs_two_trials(self) -> None:
        self.assertIsNone(deflated_sharpe([0.05], best_period_count=100))

    def test_strong_signal_beats_weak_signal(self) -> None:
        # A best far above the trial dispersion should deflate less than one buried in it.
        strong = deflated_sharpe([0.0, 0.0, 0.0, 0.30], best_period_count=2000)
        buried = deflated_sharpe([0.10, 0.11, 0.12, 0.13], best_period_count=2000)
        self.assertGreater(strong["deflated_sharpe_ratio"], buried["deflated_sharpe_ratio"])


class PboTest(unittest.TestCase):
    def test_structural_guards(self) -> None:
        self.assertIsNone(pbo_cscv([], block_count=10))
        self.assertIsNone(pbo_cscv([{0: 0.1}], block_count=10))  # <2 configs

    def test_pbo_in_unit_interval(self) -> None:
        rng = random.Random(1)
        configs = [{i: rng.gauss(0.0, 0.01) for i in range(120)} for _ in range(6)]
        result = pbo_cscv(configs, block_count=10)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["pbo"], 0.0)
        self.assertLessEqual(result["pbo"], 1.0)

    def test_robust_winner_has_low_pbo(self) -> None:
        # One config has a genuinely higher mean (same noise) in every block; it should
        # stay the winner OOS, so PBO is low.
        rng = random.Random(7)
        n = 200
        noise = [rng.gauss(0.0, 0.01) for _ in range(n)]
        dominant = {i: 0.004 + noise[i] for i in range(n)}
        others = [{i: -0.002 * (k + 1) + noise[i] for i in range(n)} for k in range(5)]
        result = pbo_cscv([dominant, *others], block_count=10)
        self.assertLess(result["pbo"], 0.5)


class TimeFoldTest(unittest.TestCase):
    def test_fold_count_and_short_series(self) -> None:
        folds = time_fold_sharpes([0.001] * 100 + [0.002] * 100, n_folds=4)
        self.assertEqual(len(folds), 4)
        self.assertEqual(time_fold_sharpes([0.1, 0.2], n_folds=5), [])


class RunGateScanTest(unittest.TestCase):
    def test_trending_panel_passes(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=2200, seed=7)
        result = run_gate_scan(prices)
        self.assertEqual(result["decision"], "passes_gate")
        self.assertTrue(result["gate"]["passes_gate"])
        self.assertEqual(result["evaluated_configs"], 12)

    def test_noise_panel_below_gate(self) -> None:
        prices = _noise_panel(12, 2200, seed=99)
        result = run_gate_scan(prices)
        self.assertEqual(result["decision"], "below_gate")
        self.assertFalse(result["gate"]["passes_gate"])
        # Noise must fail the overfitting checks specifically.
        self.assertFalse(result["gate"]["dsr_pass"])
        self.assertFalse(result["gate"]["pbo_pass"])

    def test_short_panel_insufficient_configs(self) -> None:
        # Shorter than the smallest config's lookback (126) + warmup, so every grid
        # config is skipped for want of history.
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=130, seed=1)
        result = run_gate_scan(prices)
        self.assertEqual(result["decision"], "insufficient_configs")
        self.assertGreater(result["skipped_configs"], 0)

    def test_default_grid_size(self) -> None:
        self.assertEqual(len(default_grid()), 12)


class WalkForwardEvalTest(unittest.TestCase):
    def test_structure_and_choices_on_trending_panel(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=2200, seed=7)
        result = run_walkforward_eval(prices, n_splits=5)
        self.assertEqual(result["version"], "cta_walkforward_v1")
        for key in ("ensemble", "walk_forward", "fixed"):
            self.assertIsNotNone(result[key])
            self.assertIn("ann_sharpe", result[key])
            self.assertIn("fold_positive_fraction", result[key])
        # Past-only walk-forward made one pick per split after the first.
        self.assertEqual(len(result["walk_forward_choices"]), result["n_splits"] - 1)
        self.assertIn("selection_free_robust", result)

    def test_trending_panel_is_robust_noise_is_not(self) -> None:
        trend = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=2200, seed=3)
        self.assertTrue(run_walkforward_eval(trend, n_splits=5)["selection_free_robust"])
        noise = _noise_panel(8, 2200, seed=11)
        self.assertFalse(run_walkforward_eval(noise, n_splits=5)["selection_free_robust"])

    def test_insufficient_history_reports_cleanly(self) -> None:
        prices = generate_synthetic_panel(DEFAULT_UNIVERSE, n_days=130, seed=1)
        result = run_walkforward_eval(prices)
        self.assertEqual(result["decision"], "insufficient_configs")


class CarryGateTest(unittest.TestCase):
    def test_carry_grid_is_carry_signal(self) -> None:
        grid = default_carry_grid()
        self.assertEqual(len(grid), 12)
        self.assertTrue(all(c.signal == "carry" for c in grid))

    def test_gate_scan_uses_carry_panel(self) -> None:
        prices, carry = generate_synthetic_carry_market(DEFAULT_UNIVERSE, n_days=1500, seed=5)
        res = run_gate_scan(prices, long_only=False, max_leverage=3.0, carry=carry)
        self.assertIn(res["decision"], ("passes_gate", "below_gate"))
        self.assertGreater(res["evaluated_configs"], 0)
        self.assertEqual(res["best_cell"]["signal"], "carry")
        # carry-rich synthetic: the best cell must at least be profitable.
        self.assertGreater(res["best_cell"]["total_return_pct"], 0.0)

    def test_walkforward_uses_carry_panel(self) -> None:
        prices, carry = generate_synthetic_carry_market(DEFAULT_UNIVERSE, n_days=1500, seed=7)
        res = run_walkforward_eval(prices, long_only=False, max_leverage=3.0, carry=carry)
        self.assertIsNotNone(res["ensemble"])
        self.assertGreater(res["ensemble"]["ann_sharpe"], 0.0)


if __name__ == "__main__":
    unittest.main()
