from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from qount.research.etf_alpha import cloud, cloud_bundle
from qount.research.etf_alpha.artifacts import finish_manifest, read_json, sha256, write_json
from qount.research.etf_alpha.augmentation import bootstrap_identity, verify_bootstrap
from qount.research.etf_alpha.cloud_benchmark import amortized_choice
from qount.research.etf_alpha.compute import GIB, cpu_capacity, memory_capacity, profile, storage_preflight
from qount.research.etf_alpha.expanded_data import BootstrapSpec, bootstrap_panel
from qount.research.etf_alpha.data import total_return_index
from qount.research.etf_trader.scorer import daily_returns
from test_etf_alpha_m1 import fixture

REPOSITORY = Path(__file__).resolve().parents[1]


def config():
    return read_json(REPOSITORY / "config/etf-alpha-cloud-3080ti-20261003.json")


class ComputeProfileTests(unittest.TestCase):
    def test_visible_80_cpus_are_bounded_by_20_cpu_container_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cpu.max").write_text("2000000 100000\n")
            with patch("os.sched_getaffinity", return_value=set(range(80)), create=True):
                self.assertEqual(cpu_capacity(root), 20)
                (root / "cpu.max").write_text("max 100000\n")
                self.assertEqual(cpu_capacity(root), 80)

    def test_memory_uses_container_limit_instead_of_host_128_gib(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "memory.max").write_text(str(30 * GIB))
            (root / "meminfo").write_text(f"MemTotal: {128 * GIB // 1024} kB\n")
            self.assertEqual(memory_capacity(root, root / "meminfo"), 30 * GIB)

    def test_profile_preserves_wsl_and_rejects_unregistered_cloud_or_root(self):
        self.assertEqual(profile({})["kind"], "wsl_4060")
        good = config()
        self.assertEqual(profile(good)["cpu_limit"], 20)
        for key, value in (("machine_id", "old_3090"), ("storage_root", "/root/qount"),
                           ("cpu_limit", 80), ("disk_reserve_bytes", GIB)):
            changed = deepcopy(good)
            changed["compute_profile"][key] = value
            with self.assertRaises(ValueError):
                profile(changed)

    def test_reuse_capacity_does_not_reserve_space_for_a_second_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mounts = root / "mounts"
            mounts.write_text(f"data {root} ext4 rw 0 0\n")
            fake = {"storage_root": str(root), "mount": str(root), "disk_reserve_bytes": 8 * GIB,
                    "cpu_limit": 20}
            with patch("qount.research.etf_alpha.compute.profile", return_value=fake), \
                 patch("qount.research.etf_alpha.compute.cpu_capacity", return_value=20), \
                 patch("qount.research.etf_alpha.compute.memory_capacity", return_value=30 * GIB), \
                 patch("shutil.disk_usage", return_value=SimpleNamespace(free=12 * GIB)):
                result = storage_preflight({}, BootstrapSpec(), reuse_bootstrap=True, mounts=mounts)
                self.assertEqual(result["required_free_bytes"], 8 * GIB)
                with self.assertRaises(ValueError):
                    storage_preflight({}, BootstrapSpec(), mounts=mounts)
                mounts.write_text("")
                with self.assertRaises(ValueError):
                    storage_preflight({}, BootstrapSpec(), reuse_bootstrap=True, mounts=mounts)

    def test_owner_stop_blocks_generation_calibration_and_execution_before_gpu(self):
        stopped = dict(config(), training_start_authorized=False)
        with patch("qount.research.etf_alpha.cloud.gpu_preflight") as gpu:
            with self.assertRaises(ValueError):
                cloud.prepare(stopped, Path("/uncreated"))
            with self.assertRaises(ValueError):
                cloud.calibrate(stopped, Path("/uncreated"), REPOSITORY)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "contract.json"
                write_json(path, stopped)
                with self.assertRaises(ValueError):
                    cloud.execute(path, repository=REPOSITORY, calibration=Path("/missing"))
            gpu.assert_not_called()


class DeliveryTests(unittest.TestCase):
    def test_code_package_is_deterministic_excludes_private_state_and_imports_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = cloud_bundle.pack(REPOSITORY, root / "a.tar.gz")
            second = cloud_bundle.pack(REPOSITORY, root / "b.tar.gz")
            self.assertEqual(first["sha256"], second["sha256"])
            manifest = cloud_bundle.verify_archive(root / "a.tar.gz")
            self.assertFalse(manifest["dataset_included"])
            self.assertTrue(all(Path(name).parts[0] in {"src", "tests", "scripts", "config", "deploy"}
                                for name in manifest["files"]))
            self.assertFalse(any(".env" in Path(name).parts or "state" in Path(name).parts
                                 for name in manifest["files"]))
            unpacked = root / "release"
            unpacked.mkdir()
            with tarfile.open(root / "a.tar.gz") as archive:
                archive.extractall(unpacked, filter="data")
            result = subprocess.run([sys.executable, "-c",
                "import qount.research.etf_alpha.cloud; import qount.research.etf_alpha.diagnostics; "
                "import qount.research.etf_alpha.cloud_bundle; import importlib.util; "
                "exec('import qount.research.etf_alpha.expanded_run' if importlib.util.find_spec('torch') else '')"], cwd=unpacked,
                env={"PYTHONPATH": str(unpacked / "src")}, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_archive_rejects_symlinks_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source.py"; source.write_text("public\n")
            (root / "link.py").symlink_to(source)
            with self.assertRaises(ValueError):
                cloud_bundle._archive(root / "link.tar.gz", {"src/link.py": root / "link.py"}, {})
            with self.assertRaises(ValueError):
                cloud_bundle._archive(root / "escape.tar.gz", {"../escape": source}, {})

    def test_archive_verification_detects_replaced_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source.py"; source.write_text("public\n")
            cloud_bundle._archive(root / "good.tar.gz", {"src/a.py": source}, {})
            with tarfile.open(root / "good.tar.gz") as original, tarfile.open(root / "tampered.tar.gz", "w:gz") as changed:
                for member in original:
                    content = original.extractfile(member).read()
                    if member.name == "src/a.py":
                        content = b"changed\n"; member.size = len(content)
                    changed.addfile(member, io.BytesIO(content))
            with self.assertRaises(ValueError):
                cloud_bundle.verify_archive(root / "tampered.tar.gz")

    def test_input_export_preserves_registered_bytes_and_rejects_fold_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / "data"; data.mkdir()
            fold = root / "fold.json"; fold.write_text('{"embargo_sessions":5}\n')
            for name in cloud_bundle.INPUT_NAMES:
                (data / name).write_bytes(b"frozen fixture\n")
            (data / "dataset-contract.json").unlink()
            write_json(data / "dataset-contract.json", {"contracts": {"fold-contract.json": sha256(fold)}})
            write_json(data / "manifest.json", {"files": {name: sha256(data / name) for name in cloud_bundle.INPUT_NAMES}})
            with patch.object(cloud_bundle, "DATASET_SHA256", sha256(data / "manifest.json")):
                delivery = cloud_bundle.export_inputs(data, fold, root / "inputs.tar.gz")
                self.assertEqual(delivery["file_count"], 8)
                fold.write_text("changed")
                with self.assertRaises(ValueError):
                    cloud_bundle.export_inputs(data, fold, root / "invalid.tar.gz")


class BootstrapReuseTests(unittest.TestCase):
    def test_cached_source_returns_match_uncached_paths_exactly(self):
        panel = fixture(300)
        indices = np.arange(30, 120, dtype=np.int32)
        cached = daily_returns(total_return_index(panel.close, panel.dividends, panel.splits)), daily_returns(panel.cash_close[:, None])[:, 0]
        first, second = bootstrap_panel(panel, indices), bootstrap_panel(panel, indices, source_returns=cached)
        for name in ("open", "high", "low", "close", "volume", "cash_open", "cash_close"):
            np.testing.assert_array_equal(getattr(first, name), getattr(second, name))

    def test_reuse_rejects_changed_generator_input_and_incomplete_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / "input"; data.mkdir(); (data / "manifest.json").write_text("frozen\n")
            spec = BootstrapSpec(worlds_per_fold=1, worlds_per_shard=1, training_sessions=2)
            folds = [SimpleNamespace(fold_id="WF2020", validation_start="2019-01-01", embargo_sessions=5)]
            dates = np.busday_offset("2015-01-01", np.arange(1500)).astype(str)
            out = root / "bootstrap"; shard = out / "WF2020/shard_000000"; shard.mkdir(parents=True)
            identity = bootstrap_identity(spec, data, folds, dates)
            from qount.research.etf_alpha.artifacts import GUARDS
            write_json(out / "contract.json", GUARDS | identity)
            for name, array in (("assets", np.zeros((1, 2, 9, 84), np.float32)),
                    ("market", np.zeros((1, 2, 17), np.float32)), ("mu20", np.zeros((1, 2, 9), np.float32)),
                    ("mask", np.zeros((1, 2, 9), bool)), ("source_indices", np.zeros((1, spec.sessions), np.int32))):
                np.save(shard / f"{name}.npy", array, allow_pickle=False)
            interval = identity["fold_intervals"][0]
            write_json(shard / "receipt.json", {"first_world": 0, "worlds": 1, "source_lower": interval["lower"],
                "source_upper_exclusive": interval["upper_exclusive"], "validation_or_test_sampled": False,
                "torch_imported": False})
            finish_manifest(out, phase="cpu_bootstrap_complete", completed_shards=1)
            verify_bootstrap(spec, data, folds, dates, out)
            (data / "manifest.json").write_text("changed\n")
            with self.assertRaises(ValueError):
                verify_bootstrap(spec, data, folds, dates, out)
            (data / "manifest.json").write_text("frozen\n")
            (out / "manifest.json").unlink()
            finish_manifest(out, phase="cpu_preparation_incomplete", completed_shards=0)
            with self.assertRaises(ValueError):
                verify_bootstrap(spec, data, folds, dates, out)

    def test_calibration_chooses_amortized_speed_and_rejects_bad_numerics(self):
        records = [{"status": "complete", "parity_passed": True, "compiled": False,
                    "startup_seconds": 0, "seconds_per_step": .02},
                   {"status": "complete", "parity_passed": True, "compiled": True,
                    "startup_seconds": 30, "seconds_per_step": .005}]
        self.assertFalse(amortized_choice(records, 400))
        self.assertTrue(amortized_choice(records, 80640))
        records[1]["parity_passed"] = False
        self.assertFalse(amortized_choice(records, 80640))
        with self.assertRaises(ValueError):
            amortized_choice([], 400)


if __name__ == "__main__":
    unittest.main()
