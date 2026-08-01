from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "maintenance" / "repository_hygiene.py"
SPEC = importlib.util.spec_from_file_location("repository_hygiene", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
repository_hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository_hygiene)


class RepositoryHygieneTests(unittest.TestCase):
    def test_inventory_records_worktree_without_mutating_it(self) -> None:
        result = repository_hygiene.inventory()
        self.assertIn("git_status", result)
        self.assertIn("file_categories", result)
        self.assertIn("runtime_data", result["file_categories"])
        self.assertIn("environment_reference_count", result)

    def test_contract_covers_scanned_environment_references(self) -> None:
        missing = repository_hygiene.scan_environment_references().difference(
            repository_hygiene._contract_names()
        )
        self.assertEqual(missing, set())

    def test_current_governance_checks_pass(self) -> None:
        result = repository_hygiene.check()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["markdown_link_errors"], [])
        self.assertEqual(result["deployment_reference_errors"], [])
        self.assertEqual(result["production_import_boundary_errors"], [])


if __name__ == "__main__":
    unittest.main()
