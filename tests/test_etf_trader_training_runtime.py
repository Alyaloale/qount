"""Runtime fixtures only: disk inputs, gradients, checkpoint schema and compiler fallback."""

import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "torch not installed")
class TrainingRuntimeTest(unittest.TestCase):
    def setUp(self):
        from qount.research.etf_trader.policy import PolicyConfig
        from qount.research.etf_trader.train import TrainConfig
        from qount.research.etf_trader.worlds import WorldDatasetConfig, generate_dataset

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "worlds"
        self.cfg = replace(TrainConfig(), episodes=2, batch_worlds=2, years=0.025, warmup_years=4.0,
                           plausibility_years=0, segment=3, device="cpu", policy=PolicyConfig(d_phi=8, hidden=8))
        generate_dataset(WorldDatasetConfig(worlds=4, years=self.cfg.years, warmup_years=self.cfg.warmup_years,
                                            plausibility_years=0, shard_worlds=2), self.dataset, workers=1)

    def test_training_uses_only_saved_worlds_and_checkpoint_remains_loadable(self):
        from qount.research.etf_trader.policy import Trader
        from qount.research.etf_trader.train import train

        out = self.root / "model"
        with patch("qount.research.etf_trader.training_runtime.ProcessPoolExecutor", side_effect=AssertionError), \
                patch("qount.research.etf_trader.worlds.generate_world", side_effect=AssertionError), \
                contextlib.redirect_stdout(io.StringIO()):
            result = train(self.cfg, out, world_dataset=self.dataset, use_compile=False, checkpoint_every=1)
        self.assertEqual(len(result["history"]), 2)
        self.assertTrue(all(r["time_gen"] == 0 for r in result["history"]))
        self.assertEqual(result["meta"]["world_source"], "saved_dataset")
        checkpoint = torch.load(out / "model.pt", map_location="cpu", weights_only=True)
        model = Trader(self.cfg.policy)
        model.load_state_dict(checkpoint["model"], strict=True)
        self.assertTrue(all(torch.isfinite(t).all() for t in checkpoint["model"].values()))
        self.assertFalse(any("_orig_mod" in key for key in checkpoint["model"]))
        self.assertTrue((out / "checkpoint_ep1.pt").is_file())

    def test_contract_mismatch_and_insufficient_worlds_rejected_before_model_creation(self):
        from qount.research.etf_trader.train import train
        for cfg in (replace(self.cfg, account="cn"), replace(self.cfg, years=1), replace(self.cfg, episodes=3)):
            with self.assertRaises(ValueError):
                train(cfg, self.root / "invalid", world_dataset=self.dataset)
            self.assertFalse((self.root / "invalid").exists())

    def test_cpu_transfer_does_not_use_cuda_and_pipeline_returns_canonical_schema(self):
        from qount.research.etf_trader.train import to_tensors
        from qount.research.etf_trader.train_pipeline import _transfer_to_device, train_pipelined
        from qount.research.etf_trader.worlds import WorldDataset

        ep = to_tensors(WorldDataset(self.dataset).batch(0, 2), "cpu")
        with patch("torch.cuda.stream", side_effect=AssertionError):
            transferred = _transfer_to_device(ep, torch.device("cpu"))
        torch.testing.assert_close(transferred.static, ep.static)
        with contextlib.redirect_stdout(io.StringIO()):
            result = train_pipelined(replace(self.cfg, episodes=1), self.root / "pipeline",
                                     world_dataset=self.dataset, use_compile=False)
        self.assertTrue(result["pipelined"])
        self.assertIn("lambda", result)
        self.assertIn("meta", result)

    def test_prefetch_failure_propagates_and_loader_stops(self):
        from qount.research.etf_trader.train import to_tensors
        from qount.research.etf_trader.training_runtime import episode_tensors
        from qount.research.etf_trader.worlds import WorldDataset

        dataset = WorldDataset(self.dataset)
        with patch.object(dataset, "batch", side_effect=RuntimeError("broken read")):
            with contextlib.closing(episode_tensors(self.cfg, "cpu", to_tensors, dataset)) as loader:
                with self.assertRaisesRegex(RuntimeError, "broken read"):
                    next(loader)

    def test_lazy_compiler_failure_falls_back_without_checkpoint_key_changes(self):
        from torch._dynamo.exc import Unsupported
        from qount.research.etf_trader.policy import Trader
        from qount.research.etf_trader.training_runtime import PolicyRunner

        model = Trader(self.cfg.policy)
        keys = tuple(model.state_dict())
        args = (torch.randn(2, 9, 12), torch.randn(2, 6), torch.randn(2, 6), model.initial_state(2))
        with patch("torch.compile", return_value=lambda *a: (_ for _ in ()).throw(Unsupported("fixture"))):
            runner = PolicyRunner(model, enabled=True, mode="reduce-overhead")
            self.assertEqual(runner.status["state"], "pending")
            with self.assertWarns(RuntimeWarning):
                act, h = runner(*args)
        self.assertEqual(runner.status["state"], "fallback")
        self.assertEqual(runner.status["effective_mode"], "default")
        self.assertEqual(keys, tuple(model.state_dict()))
        self.assertTrue(torch.isfinite(h).all())
        act.alpha.sum().backward()
        self.assertTrue(all(p.grad is not None for p in model.parameters()))

    @unittest.skipUnless(torch is not None and torch.cuda.is_available(), "CUDA device unavailable")
    def test_cuda_compile_recurrent_gradients_and_transfer(self):
        from qount.research.etf_trader.costs import cost_params_for
        from qount.research.etf_trader.policy import Trader
        from qount.research.etf_trader.train import run_segment, to_tensors
        from qount.research.etf_trader.training_runtime import PolicyRunner, pin_tensors, transfer_tensors
        from qount.research.etf_trader.torch_env import TorchEnv
        from qount.research.etf_trader.universe import ACCOUNTS
        from qount.research.etf_trader.worlds import WorldDataset

        torch.manual_seed(4)
        device = torch.device("cuda:0")
        cpu = pin_tensors(to_tensors(WorldDataset(self.dataset).batch(0, 2), "cpu"))
        ep = transfer_tensors(cpu, device, torch.cuda.Stream(device=device))
        model = Trader(self.cfg.policy).to(device)
        ref = Trader(self.cfg.policy).to(device)
        ref.load_state_dict(model.state_dict())
        runner = PolicyRunner(model, enabled=True, mode="default")
        account = ACCOUNTS["us"]
        for m in (runner, ref):
            env = TorchEnv(ep.batch, account, cost_params_for(account), exact=False,
                           spread_mult=ep.spread_mult, impact_mult=ep.impact_mult)
            if m is runner:
                env.cost_fn = runner.cost
            out, _ = run_segment(env, m, ep, model.initial_state(2, device=device), 4, account)
            (-torch.log1p(out["ret"]).sum()).backward()
        self.assertEqual(runner.status["state"], "active", runner.status)
        self.assertEqual(runner.status["construction"]["state"], "active", runner.status)
        self.assertEqual(runner.status["cost"]["state"], "active", runner.status)
        for a, b in zip(model.parameters(), ref.parameters()):
            self.assertTrue(torch.isfinite(a.grad).all())
            torch.testing.assert_close(a.grad, b.grad, rtol=2e-4, atol=2e-5)


if __name__ == "__main__":
    unittest.main()
