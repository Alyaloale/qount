from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qount.operations.backups import BackupError
from qount.operations.backups import read_latest_dashboard_backup
from qount.operations.backups import verify_dashboard_restore_drill
from qount.operations.dashboard_publisher import DashboardPublisherBusyError
from qount.operations.dashboard_publisher import DEFAULT_SYSTEM_STALE_AFTER_SECONDS
from qount.operations.dashboard_publisher import PublisherConfig
from qount.operations.dashboard_publisher import _parser
from qount.operations.dashboard_publisher import run_dashboard_publisher
from qount.operations.dashboard_publisher import single_writer_lock
from qount.operations.health_probes import CommandResult
from qount.operations.health_probes import HealthProbeConfig
from qount.operations.health_probes import HealthProbeDependencies
from qount.operations.health_probes import collect_os_system_health
from qount.operations.health_probes import probe_clock
from qount.operations.health_probes import probe_operations
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
        repo_root=ROOT,
        authority_root=root / "authority",
        dashboard_root=root / "dashboard",
        backup_root=root / "backups",
        lock_path=root / "locks" / "publisher.lock",
        disk_path=root / "dashboard",
        operations_enabled=False,
        retain_previous_releases=2,
        retain_previous_backups=2,
    )


class OperationsHealthProbeTest(unittest.TestCase):
    def test_live_oneshot_activating_is_a_valid_execution_state(self) -> None:
        def operations_runner(argv: tuple[str, ...]) -> CommandResult:
            unit = argv[2]
            states = {
                "qount-mini-trend-forward.timer": "inactive",
                "qount-mini-trend-live.timer": "inactive",
                "qount-mini-trend-live.service": "activating",
            }
            return CommandResult(0, states.get(unit, "active") + "\n")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_root = root / "state"
            state_root.mkdir()
            (root / ".qount-release-provenance.json").write_text(
                "{}\n", encoding="ascii"
            )
            with patch(
                "qount.operations.health_probes.verify_release_provenance",
                return_value={"provenance_hash": "a" * 64},
            ):
                measurement = probe_operations(
                    HealthProbeConfig(
                        disk_path=root,
                        service_name="qount-dashboard-publisher.timer",
                        allowed_service_names=(
                            "qount-dashboard-publisher.timer",
                        ),
                        backup_root=root,
                        repo_root=root,
                        state_root=state_root,
                        operations_enabled=True,
                    ),
                    operations_runner,
                )

        checks = {
            row["check_id"]: row for row in measurement["metrics"]["checks"]
        }
        live_service = checks["service:mini_trend_live_service"]
        self.assertEqual(measurement["status"], "healthy")
        self.assertEqual(measurement["metrics"]["scope_status"]["execution"], "pass")
        self.assertEqual(live_service["status"], "pass")
        self.assertEqual(live_service["observed_value"], "activating")

    def test_forward_timer_activating_remains_an_execution_blocker(self) -> None:
        def operations_runner(argv: tuple[str, ...]) -> CommandResult:
            unit = argv[2]
            states = {
                "qount-mini-trend-forward.timer": "activating",
                "qount-mini-trend-live.timer": "inactive",
                "qount-mini-trend-live.service": "inactive",
            }
            return CommandResult(0, states.get(unit, "active") + "\n")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_root = root / "state"
            state_root.mkdir()
            (root / ".qount-release-provenance.json").write_text(
                "{}\n", encoding="ascii"
            )
            with patch(
                "qount.operations.health_probes.verify_release_provenance",
                return_value={"provenance_hash": "a" * 64},
            ):
                measurement = probe_operations(
                    HealthProbeConfig(
                        disk_path=root,
                        service_name="qount-dashboard-publisher.timer",
                        allowed_service_names=(
                            "qount-dashboard-publisher.timer",
                        ),
                        backup_root=root,
                        repo_root=root,
                        state_root=state_root,
                        operations_enabled=True,
                    ),
                    operations_runner,
                )

        checks = {
            row["check_id"]: row for row in measurement["metrics"]["checks"]
        }
        forward_timer = checks["service:mini_trend_forward"]
        self.assertEqual(measurement["status"], "unavailable")
        self.assertEqual(
            measurement["metrics"]["scope_status"]["execution"],
            "unavailable",
        )
        self.assertEqual(forward_timer["status"], "block")
        self.assertEqual(forward_timer["observed_value"], "activating")

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

    def test_clock_probe_falls_back_to_synchronized_chrony(self) -> None:
        def chrony_runner(argv: tuple[str, ...]) -> CommandResult:
            if argv[:2] == ("timedatectl", "show"):
                return CommandResult(0, "yes\n")
            if argv[:2] == ("timedatectl", "show-timesync"):
                return CommandResult(1, "", "timesync1 unavailable")
            if argv == ("chronyc", "-c", "tracking"):
                return CommandResult(
                    0,
                    "64643D58,100.100.61.88,3,1784542050.380453474,"
                    "-0.000585097,0.000499939,0.000189562,1.037,0.002,"
                    "0.030,0.019752068,0.011192053,1034.7,Normal\n",
                )
            raise AssertionError(f"unexpected command: {argv}")

        measurement = probe_clock(
            HealthProbeConfig(
                disk_path=Path("/tmp"),
                service_name="qount-dashboard-publisher.timer",
                allowed_service_names=("qount-dashboard-publisher.timer",),
                backup_root=Path("/tmp"),
            ),
            chrony_runner,
        )

        self.assertEqual(measurement["status"], "healthy")
        self.assertEqual(measurement["detail_codes"], ())
        self.assertAlmostEqual(
            measurement["metrics"]["drift_seconds"], -0.000585097
        )

    def test_clock_probe_rejects_unsynchronized_chrony(self) -> None:
        def chrony_runner(argv: tuple[str, ...]) -> CommandResult:
            if argv[:2] == ("timedatectl", "show"):
                return CommandResult(0, "yes\n")
            if argv[:2] == ("timedatectl", "show-timesync"):
                return CommandResult(1, "", "timesync1 unavailable")
            if argv == ("chronyc", "-c", "tracking"):
                return CommandResult(
                    0,
                    "00000000,0.0.0.0,0,0.0,0.0,0.0,0.0,0.0,0.0,"
                    "0.0,0.0,0.0,0.0,Not synchronised\n",
                )
            raise AssertionError(f"unexpected command: {argv}")

        measurement = probe_clock(
            HealthProbeConfig(
                disk_path=Path("/tmp"),
                service_name="qount-dashboard-publisher.timer",
                allowed_service_names=("qount-dashboard-publisher.timer",),
                backup_root=Path("/tmp"),
            ),
            chrony_runner,
        )

        self.assertEqual(measurement["status"], "unavailable")
        self.assertEqual(measurement["detail_codes"], ("clock_not_synchronized",))


class DashboardPublisherOperationsTest(unittest.TestCase):
    def test_cli_uses_the_same_system_freshness_default_as_config(self) -> None:
        args = _parser().parse_args(
            [
                "--repo-root",
                "/tmp/repo",
                "--authority-root",
                "/tmp/authority",
                "--dashboard-root",
                "/tmp/dashboard",
                "--backup-root",
                "/tmp/backups",
                "--lock-path",
                "/tmp/publisher.lock",
                "--disk-path",
                "/tmp/dashboard",
            ]
        )

        self.assertEqual(DEFAULT_SYSTEM_STALE_AFTER_SECONDS, 180)
        self.assertEqual(
            args.system_stale_after_seconds,
            PublisherConfig(
                repo_root=args.repo_root,
                authority_root=args.authority_root,
                dashboard_root=args.dashboard_root,
                backup_root=args.backup_root,
                lock_path=args.lock_path,
                disk_path=args.disk_path,
            ).system_stale_after_seconds,
        )

    def test_module_cli_loads_without_runpy_warning(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-W",
                "error",
                "-m",
                "qount.operations.dashboard_publisher",
                "--help",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("RuntimeWarning", completed.stderr)

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
            backup_names = {
                path.name
                for path in (config.backup_root / "snapshots").iterdir()
                if path.is_dir()
            }

        self.assertEqual(results[0].system_health_status, "unavailable")
        self.assertEqual(results[1].system_health_status, "healthy")
        self.assertEqual(publication.publication_id, results[-1].publication_id)
        self.assertEqual(models.system.payload["health"]["values"]["status"], "healthy")
        self.assertEqual(backup.publication_id, publication.publication_id)
        self.assertTrue(drill.verified)
        self.assertEqual(drill.file_count, 12)
        self.assertEqual(len(release_names), 3)
        self.assertEqual(release_names, set(results[-1].retained_release_ids))
        self.assertTrue(results[-1].pruned_release_ids)
        self.assertEqual(len(backup_names), 3)
        self.assertEqual(backup_names, set(results[-1].retained_backup_ids))
        self.assertIn(results[-1].backup_id, backup_names)
        self.assertTrue(results[-1].pruned_backup_ids)

    def test_empty_intelligence_archive_publishes_explicit_unavailable_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _publish_authority_bundle(root)
            intelligence_root = root / "intelligence"
            intelligence_root.mkdir(mode=0o700)
            config = replace(_config(root), intelligence_root=intelligence_root)
            result = run_dashboard_publisher(
                config,
                observed_at="2026-07-20T00:09:00+00:00",
                dependencies=_dependencies(),
            )
            models, publication = read_dashboard_v1(config.dashboard_root)

        self.assertEqual(publication.publication_id, result.publication_id)
        self.assertEqual(
            models.intelligence.payload["authority"]["intelligence"],
            "unavailable_until_daily_intelligence",
        )

    def test_invalid_latest_intelligence_is_scoped_to_unavailable_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _publish_authority_bundle(root)
            intelligence_root = root / "intelligence"
            report_id = "a" * 64
            report_root = intelligence_root / "reports" / report_id
            report_root.mkdir(parents=True, mode=0o700)
            (report_root / "report.json").write_text("{}\n", encoding="ascii")
            (report_root / "manifest.json").write_text("{}\n", encoding="ascii")
            os.symlink(f"reports/{report_id}", intelligence_root / "latest")
            config = replace(_config(root), intelligence_root=intelligence_root)

            result = run_dashboard_publisher(
                config,
                observed_at="2026-07-20T00:09:00+00:00",
                dependencies=_dependencies(),
            )
            models, publication = read_dashboard_v1(config.dashboard_root)

        self.assertEqual(publication.publication_id, result.publication_id)
        self.assertEqual(
            models.intelligence.payload["authority"]["intelligence"],
            "unavailable_until_daily_intelligence",
        )

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

    def test_invalid_backup_snapshot_is_preserved_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _publish_authority_bundle(root)
            config = _config(root)
            run_dashboard_publisher(
                config,
                observed_at="2026-07-20T00:09:00+00:00",
                dependencies=_dependencies(),
            )
            invalid = config.backup_root / "snapshots" / ("f" * 64)
            invalid.mkdir(mode=0o700)
            result = run_dashboard_publisher(
                config,
                observed_at="2026-07-20T00:10:00+00:00",
                dependencies=_dependencies(),
            )
            invalid_preserved = invalid.exists()

        self.assertTrue(invalid_preserved)
        self.assertIn("f" * 64, result.skipped_backup_names)

    def test_systemd_template_is_hardened_and_not_enabled_by_repo_change(self) -> None:
        service = (ROOT / "deploy/systemd/qount-dashboard-publisher.service").read_text()
        timer = (ROOT / "deploy/systemd/qount-dashboard-publisher.timer").read_text()
        self.assertIn("Type=oneshot", service)
        self.assertIn("UMask=0077", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("PrivateNetwork=true", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("ReadWritePaths=/var/lib/qount/notifications", service)
        self.assertIn(
            "ReadOnlyPaths=/var/lib/qount/notifications/store.sqlite3", service
        )
        self.assertIn("ReadWritePaths=/var/www/qount/data", service)
        self.assertIn("ReadWritePaths=-/run/chrony", service)
        self.assertIn("CapabilityBoundingSet=CAP_DAC_OVERRIDE", service)
        self.assertNotIn("CAP_NET_", service)
        self.assertIn("QOUNT_LIVE_ENABLE=false", service)
        self.assertNotIn("EnvironmentFile=", service)
        self.assertIn("qount.operations.dashboard_publisher", service)
        self.assertIn("--retain-previous-backups 60", service)
        self.assertIn("mode=ro plus PRAGMA query_only", service)
        self.assertIn("Unit=qount-dashboard-publisher.service", timer)


if __name__ == "__main__":
    unittest.main()
