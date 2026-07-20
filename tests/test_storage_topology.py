from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qount.artifacts import persistent_research_dir
from qount.settings import Settings
from qount.storage_topology import build_tree_manifest, write_tree_manifest


class StorageTopologyTest(unittest.TestCase):
    def test_manifest_hash_is_independent_of_root_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            left, right = base / "left", base / "right"
            for root in (left, right):
                (root / "nested").mkdir(parents=True)
                (root / "nested" / "data.bin").write_bytes(b"qount-data")

            left_manifest = build_tree_manifest(left, source_node="mac")
            right_manifest = build_tree_manifest(right, source_node="wsl")
            self.assertEqual(left_manifest["content_hash"], right_manifest["content_hash"])
            self.assertEqual(left_manifest["total_bytes"], len(b"qount-data"))

            (right / "nested" / "data.bin").write_bytes(b"changed")
            changed = build_tree_manifest(right, source_node="wsl")
            self.assertNotEqual(left_manifest["content_hash"], changed["content_hash"])

    def test_manifest_writer_and_state_dir_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = build_tree_manifest(root, source_node="fixture")
            output = write_tree_manifest(payload, root.parent / "manifest.json")
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["content_hash"], payload["content_hash"])

            external_state = root / "external-state"
            with patch.dict(
                "os.environ",
                {
                    "QOUNT_PROJECT_ROOT": str(root),
                    "QOUNT_STATE_DIR": str(external_state),
                },
                clear=False,
            ):
                settings = Settings.from_env()
            self.assertEqual(settings.project_root, root)
            self.assertEqual(settings.state_dir, external_state)
            self.assertEqual(settings.db_path, external_state / "qount.db")
            artifact_dir = persistent_research_dir(settings, "storage-test")
            self.assertEqual(artifact_dir.parent, external_state / "research_runs")


if __name__ == "__main__":
    unittest.main()
