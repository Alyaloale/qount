from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.research.governance.build_r0_records import _verify_bundle
from scripts.research.governance.build_r0_records import build_bundle
from scripts.research.governance.run_multi_sleeve_virtual_runtime import run_fixture


class R0ArtifactsTest(unittest.TestCase):
    def test_runtime_and_r0_bundle_are_verified_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = run_fixture(root / "runtime")
            repeated_runtime = run_fixture(root / "runtime")
            self.assertEqual(
                repeated_runtime.result["result_hash"],
                runtime.result["result_hash"],
            )

            bundle = build_bundle(root / "r0", runtime.directory)
            manifest = _verify_bundle(bundle)
            repeated_bundle = build_bundle(root / "r0", runtime.directory)
            self.assertEqual(repeated_bundle, bundle)
            self.assertEqual(manifest["evidence_record_count"], 8)
            self.assertEqual(manifest["candidate_record_count"], 2)
            self.assertFalse(manifest["candidate_pnl_ready"])
            self.assertFalse(manifest["orders_authorized"])
            self.assertEqual(bundle.stat().st_mode & 0o777, 0o700)
            for path in bundle.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

            combined = "\n".join(
                path.read_text(encoding="ascii")
                for path in bundle.iterdir()
                if path.is_file()
            )
            self.assertNotIn("pending_revalidation", combined)
            self.assertNotIn("to_be_frozen_before_pnl", combined)
            candidates = [
                json.loads(path.read_text(encoding="ascii"))
                for path in bundle.glob("candidate-*.json")
            ]
            self.assertEqual(len(candidates), 2)
            self.assertTrue(
                all(candidate["candidate_id"].endswith("v4") for candidate in candidates)
            )
            self.assertTrue(
                all(
                    candidate["execution_contract"]["candidate_pnl_ready"] is False
                    for candidate in candidates
                )
            )

    def test_r0_bundle_tamper_and_missing_manifest_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = run_fixture(root / "runtime")
            bundle = build_bundle(root / "r0", runtime.directory)
            target = next(bundle.glob("candidate-*.json"))
            target.write_text("{}\n", encoding="ascii")
            os.chmod(target, 0o600)
            with self.assertRaisesRegex(
                RuntimeError,
                "r0_bundle_member_hash_or_set_mismatch",
            ):
                _verify_bundle(bundle)

        with tempfile.TemporaryDirectory() as tmp:
            incomplete = Path(tmp) / ("a" * 64)
            incomplete.mkdir(mode=0o700)
            with self.assertRaisesRegex(RuntimeError, "r0_bundle_manifest_missing"):
                _verify_bundle(incomplete)


if __name__ == "__main__":
    unittest.main()
