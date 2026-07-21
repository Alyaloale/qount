from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qount.operations.release_provenance import ReleaseProvenanceError
from qount.operations.release_provenance import build_release_provenance
from qount.operations.release_provenance import build_release_provenance_verification
from qount.operations.release_provenance import verify_release_provenance
from qount.operations.release_provenance import write_release_provenance


def _release_root(root: Path) -> Path:
    (root / "README.md").write_text("# qount\n", encoding="ascii")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'qount'\nversion = '0.2.1'\n", encoding="ascii"
    )
    for directory in ("deploy", "docs", "prompts", "scripts", "src/qount", "tests", "web"):
        target = root / directory / "release.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(directory, encoding="ascii")
    return root


class ReleaseProvenanceTest(unittest.TestCase):
    def test_verifies_the_exact_release_file_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _release_root(Path(tmp))
            provenance = build_release_provenance(root, git_commit="a" * 40)
            path = write_release_provenance(root / "manifest.json", provenance)
            verification = build_release_provenance_verification(root, provenance)

        self.assertEqual(path.name, "manifest.json")
        self.assertEqual(verification["provenance"]["git_commit"], "a" * 40)
        self.assertTrue(verification["evidence"]["verified"])

    def test_rejects_a_deployed_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _release_root(Path(tmp))
            provenance = build_release_provenance(root, git_commit="b" * 40)
            (root / "src/qount/release.txt").write_text("changed", encoding="ascii")
            with self.assertRaisesRegex(ReleaseProvenanceError, "source_tree_mismatch"):
                verify_release_provenance(root, provenance)


if __name__ == "__main__":
    unittest.main()
