from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from qount.research.etf_alpha.augmentation import _initialize, generate_shard
from qount.research.etf_alpha.diagnostics import retention
from qount.research.etf_alpha.expanded_data import BootstrapSpec, block_indices, bootstrap_panel, label_continuity, representation
from qount.research.etf_alpha.expanded_selection import BASELINES, NEGATIVE, hard_constraints, select_v2
from qount.research.etf_alpha.features import build_features, market_features, trailing_covariance
from qount.research.etf_alpha.training_data import TargetScales
from qount.research.etf_trader.scorer import daily_returns
from test_etf_alpha_m1 import fixture

try:
    import torch
except ImportError:
    torch = None


def record(seed=1000, rank=.1, huber=.4, sharpe=.4, drawdown=.1, turnover=3.):
    return {"seed": seed, "parameters": 100, "prediction": {"rank_ic": rank, "mu20_huber": huber},
            "bridge": {"2x": {"sharpe_excess_cash": sharpe, "cagr": .05, "max_drawdown": drawdown,
                              "forced_breaches": 0, "minimum_cash": .1, "max_rolling_voluntary": turnover}}}


class ExpandedDataTests(unittest.TestCase):
    def test_batched_covariance_and_market_match_window_oracle(self):
        panel = fixture(170)
        r = daily_returns(panel.close)
        r[65, 2] = np.nan
        for window in (20, 60):
            expected = np.full((len(r), 9, 9), np.nan)
            for t in range(window - 1, len(r)):
                sample = r[t - window + 1:t + 1]
                if np.isfinite(sample).all():
                    cov = np.cov(sample, rowvar=False)
                    expected[t] = (.8 * cov + .2 * np.diag(np.diag(cov))) * 252
            np.testing.assert_allclose(trailing_covariance(r, window), expected, atol=2e-15, rtol=1e-10)
        names, market = market_features(r, panel.close, panel.symbols)
        for window in (20, 60, 120):
            for t in range(window - 1, len(r)):
                sample = r[t - window + 1:t + 1]
                if np.isfinite(sample).all():
                    corr = np.corrcoef(sample, rowvar=False)
                    self.assertAlmostEqual(market[t, names.index(f"mean_correlation{window}")], corr[np.triu_indices(9, 1)].mean(), places=12)
                    self.assertAlmostEqual(market[t, names.index(f"pc1_correlation_share{window}")], np.linalg.eigvalsh(corr)[-1] / 9, places=12)

    def test_representation_keeps_levels_and_current_asset_differences(self):
        names = tuple(["return5", "return20", "return60", "rv20", "rv60", "ma_distance200", "drawdown252", "M"] + [f"field{k}" for k in range(30)])
        raw = np.broadcast_to(np.arange(9)[None, :, None] / 10, (3, 9, 38)).copy()
        result = representation(raw, np.zeros_like(raw), names)
        self.assertEqual(result.shape, (3, 9, 84))
        np.testing.assert_array_equal(result[..., :38], 0)
        np.testing.assert_allclose(result[0, :, 38], np.linspace(-1, 1, 9))
        self.assertEqual(result[0, -1, 76], 8)  # Fixed-unit return clipping, no fitted scale.
        order = np.arange(9)[::-1]
        np.testing.assert_array_equal(representation(raw[:, order], np.zeros_like(raw), names), result[:, order])

    def test_joint_blocks_are_reproducible_bounded_and_label_joins_masked(self):
        index = block_indices(90, 30, 180, 22, 7)
        np.testing.assert_array_equal(index, block_indices(90, 30, 180, 22, 7))
        self.assertTrue(((index >= 30) & (index < 180)).all())
        rows = np.arange(90)
        mask = label_continuity(index, rows)
        for row in rows:
            expected = row + 21 < len(index) and np.all(np.diff(index[row + 1:row + 22]) == 1)
            self.assertEqual(mask[row], expected)
        with self.assertRaises(ValueError):
            block_indices(10, 1, 10, 22, 7)

    def test_bootstrap_uses_only_selected_past_returns_and_dollar_liquidity(self):
        panel = fixture(300)
        indices = block_indices(90, 30, 180, 22, 7)
        boot = bootstrap_panel(panel, indices)
        np.testing.assert_allclose(daily_returns(boot.close)[1:], daily_returns(panel.close)[indices][1:], atol=3e-16)
        np.testing.assert_allclose(boot.close * boot.volume, panel.close[indices] * panel.volume[indices])
        changed_close = panel.close.copy(); changed_close[180:] *= 5
        after = bootstrap_panel(replace(panel, close=changed_close), indices)
        np.testing.assert_array_equal(boot.close, after.close)
        self.assertFalse(boot.dividends.any())
        self.assertTrue((boot.splits == 1).all())

    def test_shard_generation_is_finite_past_only_and_reproducible(self):
        panel = fixture(1500)
        spec = BootstrapSpec(worlds_per_fold=1, worlds_per_shard=1, training_sessions=24)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            np.savez(root / "panel.npz", dates=panel.dates, symbols=panel.symbols,
                     **{k: getattr(panel, k) for k in ("open", "high", "low", "close", "volume", "dividends", "splits", "cash_open", "cash_close")})
            _initialize(root)
            first = generate_shard((spec, 0, 1, 1000, 0, 1, root / "a"))
            second = generate_shard((spec, 0, 1, 1000, 0, 1, root / "b"))
            self.assertEqual(first["files"], second["files"])
            self.assertFalse(first["validation_or_test_sampled"])
            values = np.load(root / "a/assets.npy")
            self.assertEqual(values.shape, (1, 24, 9, 84))
            self.assertTrue(np.isfinite(values).all())
            source = np.load(root / "a/source_indices.npy")
            self.assertLess(source.max(), 1000)
            mask = np.load(root / "a/mask.npy")
            np.testing.assert_array_equal(mask[0, :, 0], label_continuity(source[0], np.arange(1280, 1304)))

    def test_expanded_features_are_causal_across_prefix(self):
        panel = fixture(1420)
        full, prefix = build_features(panel), build_features(panel.prefix(1390))
        before = representation(full.raw[:1390], full.normalized[:1390], full.names)
        after = representation(prefix.raw, prefix.normalized, prefix.names)
        np.testing.assert_allclose(before, after, atol=1e-6)


class ExpandedSelectionTests(unittest.TestCase):
    def test_turnover_uses_hard_budget_instead_of_parent_activity(self):
        parents = [record(s, turnover=2) for s in range(1000, 1005)]
        better = [record(s, rank=.2, sharpe=.6, huber=.39, turnover=3.99999) for s in range(1000, 1005)]
        self.assertTrue(retention(better, parents)["retained"])
        self.assertFalse(retention(better, parents, turnover_rule="parent_nonincrease_v1")["retained"])
        better[0]["bridge"]["2x"]["max_rolling_voluntary"] = 4.001
        self.assertFalse(hard_constraints(better))

    def test_validation_selector_requires_signal_consensus_and_risk(self):
        controls = {k: [record(rank=.02, sharpe=.1)] for k in BASELINES}
        controls[NEGATIVE] = [record(s, rank=-.01) for s in range(1000, 1005)]
        controls["good"] = [record(s, rank=.08, sharpe=.8) for s in range(1000, 1005)]
        controls["no_rank"] = [record(s, rank=-.05, huber=.2, sharpe=2) for s in range(1000, 1005)]
        controls["one_lucky_seed"] = [record(s, rank=.9 if s == 1000 else -.1, sharpe=2) for s in range(1000, 1005)]
        result = select_v2(controls)
        self.assertEqual(result["selected"], "good")
        self.assertFalse(result["decisions"]["no_rank"]["eligible"])
        self.assertFalse(result["decisions"]["one_lucky_seed"]["eligible"])
        self.assertFalse(result["test_used_for_selection"])
        controls["good"][0]["bridge"]["2x"]["forced_breaches"] = 1
        self.assertNotEqual(select_v2(controls)["selected"], "good")


@unittest.skipIf(torch is None, "optional research Torch is not installed")
class ExpandedTrainingTests(unittest.TestCase):
    def test_model_counts_and_asset_identity_permutation(self):
        from qount.research.etf_alpha.expanded_models import ExpandedSpec, ExpandedPredictor
        for identity in (False, True):
            spec = ExpandedSpec(identity=identity)
            model = ExpandedPredictor(spec).eval()
            self.assertEqual(sum(p.numel() for p in model.parameters()), spec.parameters)
            assets, market = torch.randn(3, 9, 84), torch.randn(3, 17)
            order = torch.arange(9).flip(0)
            torch.testing.assert_close(model(assets[:, order], market, order)["mu20"], model(assets, market)["mu20"][:, order])

    def test_rank_loss_rewards_correct_order_and_masks_gradients(self):
        from qount.research.etf_alpha.expanded_training import rank_loss
        pred = torch.tensor([[1., 0., -1.]], requires_grad=True)
        target = torch.tensor([[1., 0., -1.]])
        mask = torch.tensor([[True, False, True]])
        correct, reverse = rank_loss(pred, target, mask), rank_loss(-pred, target, mask)
        self.assertLess(float(correct.detach()), float(reverse.detach()))
        correct.backward()
        self.assertEqual(float(pred.grad[0, 1]), 0)
        pred.grad.zero_()
        empty = rank_loss(pred, target, torch.zeros_like(mask))
        empty.backward()
        self.assertEqual(float(empty.detach()), 0)
        self.assertFalse(pred.grad.any())

    def run_small_fit(self, device="cpu", expired=lambda: False, identity=True):
        from qount.research.etf_alpha.expanded_models import ExpandedSpec
        from qount.research.etf_alpha.expanded_training import fit_expanded
        from qount.research.etf_alpha.training import TensorPartition
        torch.set_num_threads(2)
        rng = np.random.default_rng(8)
        def partition(n):
            x = torch.tensor(rng.normal(size=(n, 9, 84)), dtype=torch.float32, device=device)
            y = x[:, :, 0] * .2
            return TensorPartition(np.arange(n), x, torch.zeros(n, 17, device=device),
                                   {"mu20": y}, {"mu20": torch.ones(n, 9, dtype=torch.bool, device=device)})
        options = json.loads((Path(__file__).parents[1] / "config/etf-alpha-expanded-20261003.json").read_text())["training"]
        options.update(max_epochs=2, batch_dates=13, pretrain_max_epochs=1, pretrain_batch_dates=16)
        scales = TargetScales({"mu20": {"mean": .01, "std": .05}}, {})
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fit"
            receipt = fit_expanded(ExpandedSpec(identity=identity, rank_weight=.3), partition(32), partition(11),
                scales, 1000, out, options, expired=expired, emit=lambda *args, **kw: None,
                bootstrap=partition(37), inference={"validation_bridge": partition(17)})
            self.assertTrue((out / "last.pt").exists())
            if receipt["status"] == "complete":
                self.assertEqual(receipt["epochs"], 2)
                self.assertEqual(receipt["pretraining"]["steps"], 3)
                model = torch.load(out / "best.pt", weights_only=True)["model"]
                self.assertTrue(all(torch.isfinite(p).all() for p in model.values()))
                self.assertTrue((out / "validation_bridge.npz").exists())
            else:
                self.assertFalse((out / "validation.npz").exists())
            return receipt

    def test_bootstrap_then_real_fit_and_checkpoint(self):
        self.assertEqual(self.run_small_fit()["status"], "complete")

    def test_global_deadline_preserves_partial_not_validation(self):
        self.assertEqual(self.run_small_fit(expired=lambda: True)["status"], "budget_stopped")

    @unittest.skipUnless(torch is not None and torch.cuda.is_available(), "WSL CUDA compute verification")
    def test_cuda_compiled_bootstrap_finetuning_and_partial_batches(self):
        for identity in (False, True):
            self.assertEqual(self.run_small_fit(device="cuda", identity=identity)["compilation"]["state"], "active")

    def test_contract_rejects_undeclared_architecture_and_budget(self):
        from qount.research.etf_alpha.expanded_run import validate_contract
        config = json.loads((Path(__file__).parents[1] / "config/etf-alpha-expanded-20261003.json").read_text())
        with self.assertRaises(ValueError):
            validate_contract(dict(config, training_start_authorized=False))
        # Static fixture of a separately authorized future run, never invoke the scheduler here.
        config = dict(config, training_start_authorized=True)
        validate_contract(config)
        changed = dict(config, max_fits=1000)
        with self.assertRaises(ValueError):
            validate_contract(changed)
        changed = dict(config, model_schedule=config["model_schedule"] + ["extra"])
        with self.assertRaises(ValueError):
            validate_contract(changed)
        validate_contract(dict(config, max_hours=None))
        validate_contract(dict(config, max_hours=8.0))
        for hours in (0, -1, True, float("nan"), float("inf"), "unlimited"):
            with self.assertRaises(ValueError):
                validate_contract(dict(config, max_hours=hours))

    def test_unlimited_run_does_not_expire_and_still_honors_manual_stop(self):
        from qount.research.etf_alpha.expanded_run import expiry_checks
        from qount.research.etf_alpha.overnight import RunLog
        stopped = threading.Event()
        with patch("qount.research.etf_alpha.expanded_run.time.monotonic", return_value=1000):
            deadline, expired, final_expired = expiry_checks(None, 1000, stopped)
        self.assertIsNone(deadline)
        with patch("qount.research.etf_alpha.expanded_run.time.monotonic", return_value=1000 + 100 * 3600):
            self.assertFalse(expired())
            self.assertFalse(final_expired())
            with tempfile.TemporaryDirectory() as tmp:
                log = RunLog(Path(tmp), deadline)
                log.emit("fixture")
                log.close()
                event = json.loads((Path(tmp) / "events.jsonl").read_text())
                self.assertIsNone(event["remaining_seconds"])
        stopped.set()
        self.assertTrue(expired())
        self.assertTrue(final_expired())
        stopped.clear()
        deadline, expired, final_expired = expiry_checks(1, 1000, stopped)
        self.assertEqual(deadline, 4600)
        with patch("qount.research.etf_alpha.expanded_run.time.monotonic", return_value=4000):
            self.assertTrue(expired())
            self.assertFalse(final_expired())


if __name__ == "__main__":
    unittest.main()
