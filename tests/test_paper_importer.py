from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from qount.dual_engine import run_paper_cycle
from qount.reporting import PaperProgramImportError
from qount.reporting import read_paper_program_snapshot
from tests.test_dual_engine import _cycle


class PaperProgramImporterTest(unittest.TestCase):
    def test_reads_only_verified_private_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "paper"
            snapshot = run_paper_cycle(
                root,
                _cycle(3, signal=True, rebalance=True),
            )

            self.assertEqual(read_paper_program_snapshot(root), snapshot)

    def test_rejects_relaxed_snapshot_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "paper"
            run_paper_cycle(root, _cycle(3, signal=True, rebalance=True))
            path = root / "current" / "paper_program_snapshot.json"
            os.chmod(path, 0o644)

            with self.assertRaises(PaperProgramImportError):
                read_paper_program_snapshot(root)


if __name__ == "__main__":
    unittest.main()
