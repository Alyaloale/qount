"""Small synthetic fixtures verify persisted worlds, parallelism and fail-closed resume."""

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from qount.research.etf_trader.worlds import (
    WorldDataset, WorldDatasetConfig, _arrays, estimated_bytes, generate_dataset, generate_world, world_seed,
)


class WorldDatasetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "worlds"
        self.cfg = WorldDatasetConfig(worlds=3, years=0.04, warmup_years=0.1, plausibility_years=0,
                                      shard_worlds=2, backend="native")

    def build(self, **kwargs):
        generate_dataset(self.cfg, self.root, workers=1, **kwargs)
        return WorldDataset(self.root)

    def test_generation_does_not_import_torch(self):
        result = subprocess.run([sys.executable, "-c", "import sys; from qount.research.etf_trader import worlds; "
                                 "assert 'torch' not in sys.modules"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_saved_values_equal_training_precision_and_cross_shard_read(self):
        dataset = self.build()
        got = dataset.batch(1, 2)
        self.assertEqual(len(got), 2)
        for index, w in enumerate(got, start=1):
            reference = generate_world("us", self.cfg.seed, "train", index, self.cfg.years,
                                       self.cfg.warmup_years, 0, backend="native")
            for key, a in _arrays(w).items():
                b = _arrays(reference)[key]
                if np.asarray(a).dtype.kind == "f":
                    b = np.asarray(b, dtype=np.float32)
                np.testing.assert_array_equal(a, b, err_msg=key)
        self.assertIsInstance(got[0].close, np.memmap)
        self.assertFalse(got[0].close.flags.writeable)
        with self.assertRaises(ValueError):
            dataset.batch(2, 2)

    def test_worker_count_does_not_change_worlds(self):
        a = self.build()
        root2 = Path(self.tmp.name) / "parallel"
        generate_dataset(self.cfg, root2, workers=2)
        b = WorldDataset(root2)
        self.assertEqual(a.manifest["contract_sha256"], b.manifest["contract_sha256"])
        self.assertEqual(a.manifest["shards"], b.manifest["shards"])

    def test_completed_dataset_is_immutable_and_resume_is_idempotent(self):
        self.build()
        before = (self.root / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.build()
        self.build(resume=True)
        self.assertEqual(before, (self.root / "manifest.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "resume contract differs"):
            generate_dataset(replace(self.cfg, seed=self.cfg.seed + 1), self.root, resume=True)

    def test_resume_retains_finished_shards_and_rebuilds_partial_shard(self):
        dataset = self.build()
        saved_receipt = (self.root / "shards/000000000/receipt.json").read_bytes()
        (self.root / "manifest.json").unlink()
        (self.root / "shards/000000002/receipt.json").unlink()
        (self.root / "shards/000000002/close.npy").write_bytes(b"interrupted")
        resumed = self.build(resume=True)
        self.assertEqual(saved_receipt, (self.root / "shards/000000000/receipt.json").read_bytes())
        self.assertEqual(dataset.manifest["shards"], resumed.manifest["shards"])

    def test_corrupt_data_is_rejected_by_reader_and_resume(self):
        self.build()
        p = self.root / "shards/000000000/close.npy"
        a = np.load(p, mmap_mode="r+")
        a[0, 0, 0] += 1
        a.flush()
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            WorldDataset(self.root)
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.build(resume=True)

    def test_missing_manifest_and_duplicate_coverage_are_rejected(self):
        self.build()
        p = self.root / "manifest.json"
        manifest = json.loads(p.read_text())
        manifest["shards"].append(manifest["shards"][0])
        p.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            WorldDataset(self.root)
        p.unlink()
        with self.assertRaises(FileNotFoundError):
            WorldDataset(self.root)

    def test_estimate_and_invalid_configuration(self):
        self.assertGreater(estimated_bytes(self.cfg), 0)
        for changes in ({"worlds": 0}, {"years": float("nan")}, {"warmup_years": -1}, {"split": "holdout"},
                        {"seed": -1}, {"dtype": "object"}):
            with self.assertRaises(ValueError):
                estimated_bytes(replace(self.cfg, **changes))

    def test_space_failure_leaves_no_manifest(self):
        with patch("qount.research.etf_trader.worlds.shutil.disk_usage") as disk:
            disk.return_value.free = 0
            with self.assertRaisesRegex(OSError, "insufficient free space"):
                self.build()
        self.assertTrue((self.root / "contract.json").exists())
        self.assertFalse((self.root / "manifest.json").exists())

    def test_split_seeds_are_disjoint_and_indexed(self):
        seeds = [tuple(world_seed(4, s, i).generate_state(4)) for s in ("train", "val", "test") for i in range(4)]
        self.assertEqual(len(set(seeds)), 12)


if __name__ == "__main__":
    unittest.main()
