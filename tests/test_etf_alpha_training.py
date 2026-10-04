from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from qount.research.etf_alpha.diagnostics import (bridge_targets, huber, ic_series, retention,
                                                 select_candidate, block_interval)
from qount.research.etf_alpha.execution import execution_inputs
from qount.research.etf_alpha.ridge import fit_ridge, block_permutation
from qount.research.etf_alpha.training_data import TrainingData, fit_target_scales, prepare_partition
from qount.research.etf_trader.costs import cost_params_for
from qount.research.etf_trader.universe import US_ACCOUNT
from test_etf_alpha_m1 import fixture

try:
    import torch
except ImportError:
    torch = None


def data_fixture(T=400):
    rng = np.random.default_rng(31)
    dates = tuple(np.busday_offset("2015-01-01", np.arange(T), roll="forward").astype(str))
    mu = {f"mu{h}": rng.normal(.01, .1, (T, 9)) for h in (5, 20, 60)}
    targets = mu | {"sigma20": rng.uniform(.1, .2, (T, 9)), "p_up": (mu["mu20"] > 0).astype(float),
                    "q10": mu["mu20"].copy()}
    masks = {k: np.ones((T, 9), bool) for k in targets}
    starts = np.arange(T) + 1
    starts[starts >= T] = -1
    ends = {}
    for h in (5, 20, 60):
        ends[h] = np.arange(T) + h + 1
        ends[h][ends[h] >= T] = -1
        masks[f"mu{h}"][ends[h] < 0] = False
    for k in ("sigma20", "p_up", "q10"):
        masks[k] &= masks["mu20"]
    return TrainingData(dates, US_ACCOUNT.symbols, tuple(f"f{i}" for i in range(35)) + ("M", "Trend_orth_M", "Risk"),
        rng.normal(0, 1, (T, 9, 38)), np.ones((T, 9, 38), bool), rng.normal(0, 1, (T, 17)),
        np.ones((T, 17), bool), targets, masks, starts, ends)


def record(seed=1000, *, rank=.1, loss=.4, cagr=.06, sharpe=.4, mdd=.15, params=5921):
    return {"seed": seed, "parameters": params, "prediction": {"rank_ic": rank, "mu20_huber": loss},
            "bridge": {"2x": {"cagr": cagr, "sharpe_excess_cash": sharpe, "max_drawdown": mdd,
                "forced_breaches": 0, "minimum_cash": 0, "max_rolling_voluntary": 1}}}


class DataAndSelectionTests(unittest.TestCase):
    def test_scales_ignore_validation_targets_and_biases_are_train_only(self):
        data = data_fixture()
        data.validate()
        rows = np.arange(60, 200)
        heads = tuple(data.targets)
        scales = fit_target_scales(data, rows, heads)
        for values in data.targets.values():
            values[200:] *= 100
        after = fit_target_scales(data, rows, heads)
        self.assertEqual(scales, after)
        self.assertEqual(scales.transform("q10", np.array([.1])).item(), scales.transform("mu20", np.array([.1])).item())

    def test_market_windows_end_at_decision_and_missing_context_is_rejected(self):
        data = data_fixture()
        scales = fit_target_scales(data, np.arange(60, 200), ("mu20",))
        part = prepare_partition(data, np.array([200, 201]), scales, ("mu20",), (35, 36, 37), market=True)
        np.testing.assert_array_equal(part.market[0], data.market[141:201].astype(np.float32))
        data.market_available[199, 0] = False
        with self.assertRaises(ValueError):
            prepare_partition(data, np.array([200]), scales, ("mu20",), (35, 36, 37), market=True)

    def test_ridge_matches_weighted_normal_equations_without_intercept_penalty(self):
        rng = np.random.default_rng(4)
        x, y = rng.normal(size=(8, 3, 2)), rng.normal(size=(8, 3))
        mask = np.ones_like(y, dtype=bool); mask[:4, 1:] = False
        model = fit_ridge(x, y, mask, .01)
        w = (mask / mask.sum(1, keepdims=True) / len(x))[mask]
        design = np.c_[np.ones(mask.sum()), x[mask]]
        expected = np.linalg.solve(design.T @ (w[:, None] * design) + np.diag([0, .01, .01]), design.T @ (w * y[mask]))
        np.testing.assert_allclose(np.r_[model.intercept, model.coefficients], expected, atol=1e-12)

    def test_shuffle_preserves_joint_date_blocks(self):
        p = block_permutation(180)
        np.testing.assert_array_equal(np.sort(p), np.arange(180))
        for start in range(0, 180, 60):
            np.testing.assert_array_equal(np.diff(p[start:start + 60]), np.ones(59))
        np.testing.assert_array_equal(p, block_permutation(180))

    def test_masked_nan_is_excluded_and_dates_are_equally_weighted(self):
        pred = np.array([[1., 1., 1.], [1., 9., 9.]])
        truth = np.array([[0., 0., 0.], [0., np.nan, np.nan]])
        mask = np.isfinite(truth)
        self.assertEqual(huber(pred, truth, mask, 1), .5)

    def test_rank_ic_uses_average_ties_and_omits_constant_predictions(self):
        p = np.array([[1., 1., 3., 4.], [1., 1., 1., 1.]])
        ic, rank = ic_series(p, p.copy(), np.ones_like(p, bool))
        self.assertAlmostEqual(rank[0], 1)
        self.assertTrue(np.isnan(ic[1]))

    def test_retention_requires_paired_seeds_quality_and_consensus(self):
        parent = [record(s) for s in range(1000, 1005)]
        better = [record(s, cagr=.07, sharpe=.5, loss=.39) for s in range(1000, 1005)]
        self.assertTrue(retention(better, parent)["retained"])
        better[0]["prediction"]["mu20_huber"] = 1
        self.assertFalse(retention(better, parent)["retained"])
        self.assertFalse(retention(better[:4], parent)["retained"])
        better[0]["seed"] = 999
        with self.assertRaises(ValueError):
            retention(better, parent)

    def test_selection_ties_use_simpler_model(self):
        self.assertEqual(select_candidate({"simple": [record(loss=.40005, params=39)],
                                           "complex": [record(loss=.4, params=10000)]}), "simple")

    def test_bridge_is_causal_and_keeps_no_signal_cash(self):
        panel = fixture(400)
        rows = np.arange(300, 310)
        prepared = execution_inputs(panel, cost_params_for(US_ACCOUNT))
        mu = np.full((10, 9), .03)
        target = bridge_targets(panel, rows, mu, prepared)[rows]
        altered = replace(panel, cash_close=panel.cash_close.copy(), close=panel.close.copy())
        altered.cash_close[310:] *= 100
        altered.close[310:] *= 100
        after = bridge_targets(altered, rows, mu, execution_inputs(altered, cost_params_for(US_ACCOUNT)))[rows]
        np.testing.assert_array_equal(target, after)
        zero = bridge_targets(panel, rows, np.full((10, 9), -1.), prepared)[rows]
        self.assertFalse(zero.any())
        self.assertTrue((target <= .35).all())
        self.assertTrue((target.sum(1) <= 1 + 1e-12).all())

    def test_block_interval_constant_and_short_samples(self):
        interval = block_interval(np.ones(180))
        self.assertEqual(interval["lower"], 1)
        self.assertEqual(interval["upper"], 1)
        self.assertEqual(block_interval(np.ones(20))["status"], "insufficient")


@unittest.skipIf(torch is None, "optional research Torch is not installed")
class TrainingTests(unittest.TestCase):
    def test_parameter_counts_and_shared_market_embedding(self):
        from qount.research.etf_alpha.models import ModelSpec, SharedPredictor, HEADS
        for spec, expected in ((ModelSpec(3), 3681), (ModelSpec(), 5921), (ModelSpec(heads=HEADS), 6086),
                               (ModelSpec(market="mlp"), 12433), (ModelSpec(market="gru"), 12401),
                               (ModelSpec(heads=HEADS, market="mlp"), 12598), (ModelSpec(heads=HEADS, market="gru"), 12566)):
            model = SharedPredictor(spec).eval()
            self.assertEqual(sum(p.numel() for p in model.parameters()), expected)
            assets = torch.zeros(2, 9, spec.asset_dim)
            result = model(assets, torch.randn(2, 60, 17) if spec.market != "none" else None)
            torch.testing.assert_close(result["mu20"][:, 0], result["mu20"][:, -1])

    def test_loss_weights_and_masked_gradient(self):
        from qount.research.etf_alpha.training import objective
        from qount.research.etf_alpha.training_data import TargetScales
        scales = TargetScales({"mu20": {"mean": 0, "std": 1}, "sigma20": {"mean": 0, "std": 1}}, {})
        pred = {k: torch.zeros(2, 3, requires_grad=True) for k in ("mu5", "mu20", "mu60", "sigma20", "p_up", "q10")}
        targets = {k: torch.ones(2, 3) for k in pred}
        masks = {k: torch.tensor([[True, True, True], [True, False, False]]) for k in pred}
        targets["sigma20"].fill_(float(torch.log(torch.nn.functional.softplus(torch.tensor(0.)) + 1e-6)))
        loss = objective(pred, targets, masks, scales)
        self.assertAlmostEqual(float(loss.detach()), .5 + .2 * np.log(2) + .5 * .1, places=6)
        loss.backward()
        self.assertEqual(float(pred["mu20"].grad[1, 1]), 0)
        self.assertAlmostEqual(float(pred["mu20"].grad[1, 0]), 3 * float(pred["mu20"].grad[0, 0]), places=6)

    def run_fit(self, device="cpu", expired=lambda: False, market="none"):
        from qount.research.etf_alpha.models import ModelSpec, HEADS
        from qount.research.etf_alpha.training import TensorPartition, fit
        data = data_fixture()
        spec = ModelSpec(heads=HEADS, market=market)
        scales = fit_target_scales(data, np.arange(60, 92), HEADS)
        train = prepare_partition(data, np.arange(60, 92), scales, HEADS, tuple(range(38)), market=market != "none")
        val = prepare_partition(data, np.arange(100, 111), scales, HEADS, tuple(range(38)), market=market != "none")
        options = json.loads((Path(__file__).parents[1] / "config/etf-alpha-stage1-proposal-20261002.json").read_text())["training"]
        options.update(max_epochs=2, batch_dates=13)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fit"
            result = fit(spec, TensorPartition.from_partition(train, device), TensorPartition.from_partition(val, device),
                         scales, 1000, out, options, expired=expired, emit=lambda *_args, **_kw: None)
            if result["status"] == "complete":
                saved = torch.load(out / "best.pt", weights_only=True)
                self.assertTrue(all(torch.isfinite(v).all() for v in saved["model"].values()))
                self.assertTrue((out / "validation.npz").exists())
                self.assertEqual(result["epochs"], 2)
            else:
                self.assertFalse((out / "validation.npz").exists())
            self.assertTrue((out / "last.pt").exists())
            return result

    def test_cpu_fit_saves_original_state_and_validation_predictions(self):
        torch.set_num_threads(2)
        self.assertEqual(self.run_fit()["status"], "complete")

    def test_deadline_partial_is_not_eligible(self):
        self.assertEqual(self.run_fit(expired=lambda: True)["status"], "budget_stopped")

    @unittest.skipUnless(torch is not None and torch.cuda.is_available(), "CUDA host required")
    def test_cuda_compiled_fit_with_partial_batches_and_gru(self):
        for market in ("none", "mlp", "gru"):
            result = self.run_fit(device="cuda", market=market)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["compilation"]["state"], "active")

    def test_run_contract_rejects_undeclared_scope(self):
        from qount.research.etf_alpha.overnight import validate_run
        root = Path(__file__).parents[1]
        config = json.loads((root / "config/etf-alpha-overnight-20261003.json").read_text())
        proposal = json.loads((root / config["proposal"]).read_text())
        validate_run(config, proposal)
        for key, value in (("max_hours", 9), ("seeds", [1000]), ("amp", True),
                           ("outer_test_after_selection_freeze", False), ("training_start_authorized", False)):
            altered = deepcopy(config); altered[key] = value
            with self.assertRaises(ValueError):
                validate_run(altered, proposal)


if __name__ == "__main__":
    unittest.main()
