from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from qount.research.etf_alpha.preservation import inspect_checkpoint, source_inventory


class SourceIdentityTests(unittest.TestCase):
    def test_dirty_public_source_changes_identity_without_reading_private_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "src/qount/research/etf_trader/scorer.py"
            public.parent.mkdir(parents=True)
            public.write_text("ORIGINAL = 1\n")
            (root / ".env").write_text("private fixture must not be inventoried\n")
            before = source_inventory(root)
            public.write_text("ORIGINAL = 2\n")
            after = source_inventory(root)
            self.assertEqual(before["git_commit"], after["git_commit"])
            self.assertNotEqual(before["files"], after["files"])
            self.assertNotIn(".env", after["files"])


@unittest.skipUnless(importlib.util.find_spec("torch"), "torch tensor validation runs on WSL")
class CheckpointTests(unittest.TestCase):
    def checkpoint(self, root, episode=60):
        import torch
        from qount.research.etf_trader.policy import PolicyConfig, Trader
        torch.set_num_threads(1)
        model = Trader(PolicyConfig(16, 16, 1))
        path = root / "checkpoint.pt"
        body = {"model": {"_orig_mod." + k: v for k, v in model.state_dict().items()},
                "config": {"policy": {"d_phi": 16, "hidden": 16, "layers": 1},
                           "seed": 1000, "episodes": 100}, "episode": episode}
        torch.save(body, path)
        return path, body

    def test_saved_episode_and_partial_resume_are_not_confused_with_planned_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self.checkpoint(Path(directory))
            report = inspect_checkpoint(path)
            self.assertEqual(report["saved_episode_index"], 60)
            self.assertEqual(report["config"]["episodes"], 100)
            self.assertFalse(report["exact_resume_available"])
            self.assertTrue(report["finite_tensors"])

    def test_nonfinite_tensors_are_rejected(self):
        import torch
        with tempfile.TemporaryDirectory() as directory:
            path, body = self.checkpoint(Path(directory))
            next(iter(body["model"].values())).flatten()[0] = float("nan")
            torch.save(body, path)
            with self.assertRaises(ValueError): inspect_checkpoint(path)

    def test_wrong_network_schema_is_rejected_before_any_inference(self):
        import torch
        with tempfile.TemporaryDirectory() as directory:
            path, body = self.checkpoint(Path(directory))
            body["config"]["policy"]["hidden"] = 32
            torch.save(body, path)
            with self.assertRaises(RuntimeError): inspect_checkpoint(path)


if __name__ == "__main__":
    unittest.main()
