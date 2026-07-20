from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from qount.operations import PUBLISHER_AUTHORIZATION_GRANTED
from qount.operations import PUBLISHER_AUTHORIZATION_PENDING
from qount.operations import audit_publisher_paths
from tests.test_authority_importer import _publish_authority_bundle


AUDITED_AT = "2026-07-20T01:00:00+00:00"


class PublisherPathAuditTest(unittest.TestCase):
    def test_complete_authority_and_empty_private_backup_are_ready_for_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _publish_authority_bundle(root)
            backup = root / "backups"
            backup.mkdir(mode=0o700)
            os.chmod(backup, 0o700)

            result = audit_publisher_paths(
                root / "authority",
                backup,
                audited_at=AUDITED_AT,
            )

        self.assertEqual(result.status, "ready_for_authorization")
        self.assertTrue(result.authority_bundle_verified)
        self.assertEqual(result.backup_state, "prepared_empty")
        self.assertEqual(result.authorization_status, PUBLISHER_AUTHORIZATION_PENDING)
        self.assertFalse(result.install_authorized)
        self.assertFalse(result.enable_authorized)
        self.assertTrue(all(check["ok"] for check in result.checks))

    def test_wide_authority_file_and_backup_symlink_block_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            _publish_authority_bundle(root)
            registry = root / "authority" / "strategy_registry.json"
            os.chmod(registry, 0o644)
            backup = root / "backups"
            backup.mkdir(mode=0o700)
            os.chmod(backup, 0o700)
            target = root / "outside"
            target.write_text("not a backup", encoding="ascii")
            (backup / "unexpected").symlink_to(target)

            result = audit_publisher_paths(
                root / "authority",
                backup,
                audited_at=AUDITED_AT,
            )

        self.assertEqual(result.status, "blocked")
        self.assertFalse(result.authority_bundle_verified)
        self.assertFalse(result.install_authorized)
        self.assertFalse(result.enable_authorized)
        failed = {row["name"] for row in result.checks if not row["ok"]}
        self.assertIn("authority_bundle", failed)
        self.assertIn("backup_root_entries", failed)
        self.assertIn("backup_tree_symlinks", failed)

    def test_relative_paths_fail_closed_without_creating_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = tuple(root.iterdir())
            result = audit_publisher_paths(
                Path("authority"),
                Path("backups"),
                audited_at=AUDITED_AT,
            )
            after = tuple(root.iterdir())

        self.assertEqual(result.status, "blocked")
        self.assertEqual(before, after)

    def test_owner_authorization_allows_install_but_not_incomplete_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            authority = root / "authority"
            backup = root / "backups"
            authority.mkdir(mode=0o700)
            backup.mkdir(mode=0o700)
            os.chmod(authority, 0o700)
            os.chmod(backup, 0o700)

            blocked = audit_publisher_paths(
                authority,
                backup,
                audited_at=AUDITED_AT,
                owner_authorized=True,
            )
            self.assertEqual(blocked.status, "blocked")
            self.assertEqual(
                blocked.authorization_status,
                PUBLISHER_AUTHORIZATION_GRANTED,
            )
            self.assertTrue(blocked.install_authorized)
            self.assertFalse(blocked.enable_authorized)

            authority.rmdir()
            _publish_authority_bundle(root)
            ready = audit_publisher_paths(
                root / "authority",
                backup,
                audited_at=AUDITED_AT,
                owner_authorized=True,
            )
            self.assertEqual(ready.status, "ready_for_authorization")
            self.assertTrue(ready.install_authorized)
            self.assertTrue(ready.enable_authorized)


if __name__ == "__main__":
    unittest.main()
