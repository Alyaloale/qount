from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qount.operations.backups import BackupError
from qount.operations.backups import read_latest_dashboard_backup
from qount.operations.backups import verify_dashboard_restore_drill
from qount.operations.dashboard_publisher import DashboardPublisherBusyError
from qount.operations.dashboard_publisher import PublisherConfig
from qount.operations.dashboard_publisher import run_dashboard_publisher
from qount.operations.dashboard_publisher import single_writer_lock
from qount.operations.health_probes import CommandResult
from qount.operations.health_probes import HealthProbeConfig
from qount.operations.health_probes import HealthProbeDependencies
from qount.operations.health_probes import collect_os_system_health
from qount.reporting import read_dashboard_v1
from tests.test_authority_importer import _publish_authority_bundle


ROOT = Path(__file__).resolve().parents[1]


def _runner(argv: tuple[str, ...]) -> CommandResult:
    if argv[:2] == ("timedatectl", "show"):
        return CommandResult(0, "yes\n")
    if argv[:2] == ("timedatectl", "show-timesync"):
        return CommandResult(0, "15000\n")
    if argv[0] == "systemctl":
        return CommandResult(0, "active\n")
    raise AssertionError(f"unexpected command: {argv}")


def _dependencies() -> HealthProbeDependencies:
    return HealthProbeDependencies(
        command_runner=_runner,
        disk_usage=lambda _: SimpleNamespace(
            total=100_000_000_000,
            used=40_000_000_000,
            free=60_000_000_000,
        ),
    )


def _config(root: Path) -> PublisherConfig:
    root = root.resolve()
    return PublisherConfig(
        authority_root=root / "authority",
        dashboard_root=root / "dashboard",
        backup_root=root / "backups",
        lock_path=root / "locks" / "publisher.lock",
        disk_path=root / "dashboard",
        retain_previous_releases=2,
    )


class OperationsHealthProbeTest(unittest.TestCase):
    def test_real_probe_adapter_binds_raw_sources_and_missing_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup = root / "backups"
            backup.mkdir(mode=0o700)
            os.chmod(backup, 0o700)
            snapshot = collect_os_system_health(
                HealthProbeConfig(
                    disk_path=root,
                    service_name="qount-dashboard-publisher.timer",
                    allowed_service_names=("qount-dashboard-publisher.timer",),
                    backup_root=backup,
                ),
                observed_at="2026-07-20T00:09:00+00:00",
                captured_at="2026-07-20T00:09:00+00:00",
                dependencies=_dependencies(),
            )

        observations = {row["component"]: row for row in snapshot.observations}
        self.assertEqual(snapshot.status, "unavailable")
        self.assertEqual(observations["clock"]["metrics"]["drift_seconds"], 0.015)
        self.assertEqual(observations["disk"]["status"], "healthy")
        self.assertEqual(observations["service"]["status"], "healthy")
        self.assertIsNone(observations["backup"]["metrics"]["last_success_at"])

    def test_command_failures_publish_explicit_unavailable_nulls(self) -> None:
        def failed(_: tuple[str, ...]) -> CommandResult:
            return CommandResult(1, "", "not available")

        def disk_failed(_: str | Path):
            raise OSError("disk unavailable")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup = root / "backups"
            backup.mkdir(mode=0o700)
            os.chmod(backup, 0o700)
            snapshot = collect_os_system_health(
                HealthProbeConfig(
                    disk_path=root,
                    service_name="qount-dashboard-publisher.timer",
                    allowed_service_names=("qount-dashboard-publisher.timer",),
                    backup_root=backup,
                ),
                observed_at="2026-07-20T00:09:00+00:00",
                captured_at="2026-07-20T00:09:00+00:00",
                dependencies=HealthProbeDependencies(failed, disk_failed),
            )

        observations = {row["component"]: row for row in snapshot.observations}
        self.assertIsNone(observations["clock"]["metrics"]["drift_seconds"])
        self.assertEqual(
            observations["disk"]["metrics"],
            {"free_bytes": None, "total_bytes": None},
        )
        self.assertEqual(observations["service"]["metrics"]["active_state"], "unknown")


class DashboardPublisherOperationsTest(unittest.TestCase):
    def test_end_to_end_publish_backup_restore_and_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _publish_authority_bundle(root)
            config = _config(root)
            results = []
            for minute in range(9, 14):
                results.append(
                    run_dashboard_publisher(
                        config,
                        observed_at=f"2026-07-20T00:{minute:02d}:00+00:00",
                        dependencies=_dependencies(),
                    )
                )
            models, publication = read_dashboard_v1(config.dashboard_root)
            backup = read_latest_dashboard_backup(config.backup_root)
            drill = verify_dashboard_restore_drill(config.backup_root, backup.backup_id)
            release_names = {
                path.name
                for path in (config.dashboard_root / "releases").iterdir()
                if path.is_dir()
            }

        self.assertEqual(results[0].system_health_status, "unavailable")
        self.assertEqual(results[1].system_health_status, "healthy")
        self.assertEqual(publication.publication_id, results[-1].publication_id)
        self.assertEqual(models.system.payload["health"]["values"]["status"], "healthy")
        self.assertEqual(backup.publication_id, publication.publication_id)
        self.assertTrue(drill.verified)
        self.assertEqual(drill.file_count, 11)
        self.assertEqual(len(release_names), 3)
        self.assertEqual(release_names, set(results[-1].retained_release_ids))
        self.assertTrue(results[-1].pruned_release_ids)

    def test_lock_busy_fails_without_changing_current_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _publish_authority_bundle(root)
            config = _config(root)
            first = run_dashboard_publisher(
                config,
                observed_at="2026-07-20T00:09:00+00:00",
                dependencies=_dependencies(),
            )
            with single_writer_lock(config.lock_path):
                with self.assertRaisesRegex(DashboardPublisherBusyError, "lock_busy"):
                    run_dashboard_publisher(
                        config,
                        observed_at="2026-07-20T00:10:00+00:00",
                        dependencies=_dependencies(),
                    )
            _, publication = read_dashboard_v1(config.dashboard_root)

        self.assertEqual(publication.publication_id, first.publication_id)

    def test_publish_failure_keeps_atomic_pointer_and_invalid_release_is_not_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _publish_authority_bundle(root)
            config = _config(root)
            first = run_dashboard_publisher(
                config,
                observed_at="2026-07-20T00:09:00+00:00",
                dependencies=_dependencies(),
            )
            invalid = config.dashboard_root / "releases" / ("f" * 64)
            invalid.mkdir(mode=0o755)
            with patch(
                "qount.operations.dashboard_publisher.publish_dashboard_v1",
                side_effect=RuntimeError("injected publish failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected publish failure"):
                    run_dashboard_publisher(
                        config,
                        observed_at="2026-07-20T00:10:00+00:00",
                        dependencies=_dependencies(),
                    )
            _, publication = read_dashboard_v1(config.dashboard_root)
            second = run_dashboard_publisher(
                config,
                observed_at="2026-07-20T00:10:00+00:00",
                dependencies=_dependencies(),
            )
            invalid_preserved = invalid.exists()

        self.assertEqual(publication.publication_id, first.publication_id)
        self.assertTrue(invalid_preserved)
        self.assertIn("f" * 64, second.skipped_release_names)

    def test_backup_payload_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _publish_authority_bundle(root)
            config = _config(root)
            result = run_dashboard_publisher(
                config,
                observed_at="2026-07-20T00:09:00+00:00",
                dependencies=_dependencies(),
            )
            payload = (
                config.backup_root
                / "snapshots"
                / result.backup_id
                / "overview.json"
            )
            value = json.loads(payload.read_text(encoding="ascii"))
            value["read_model_hash"] = "0" * 64
            payload.write_text(
                json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="ascii",
            )
            os.chmod(payload, 0o600)
            with self.assertRaisesRegex(BackupError, "payload_hash_mismatch"):
                read_latest_dashboard_backup(config.backup_root)

    def test_systemd_template_is_hardened_and_not_enabled_by_repo_change(self) -> None:
        service = (ROOT / "deploy/systemd/qount-dashboard-publisher.service").read_text()
        timer = (ROOT / "deploy/systemd/qount-dashboard-publisher.timer").read_text()
        self.assertIn("Type=oneshot", service)
        self.assertIn("UMask=0077", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("PrivateNetwork=true", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ReadWritePaths=/var/www/qount/data", service)
        self.assertIn("QOUNT_LIVE_ENABLE=false", service)
        self.assertNotIn("EnvironmentFile=", service)
        self.assertIn("qount.operations.dashboard_publisher", service)
        self.assertIn("Unit=qount-dashboard-publisher.service", timer)


if __name__ == "__main__":
    unittest.main()
