"""Single-writer production-shaped Dashboard v1 publisher.

This module is intentionally host-facing.  It reads only the complete verified
authority bundle plus four read-only OS probes; it never queries an exchange,
opens the runtime SQLite ledger, or grants execution authority.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import shutil
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from qount.contracts import canonical_hash
from qount.contracts import is_sha256
from qount.contracts.trace import aware_datetime
from qount.intelligence import read_latest_daily_intelligence
from qount.notifications import NotificationStore
from qount.notifications import build_notification_snapshot
from qount.operations.backups import BackupRecord
from qount.operations.backups import BackupRetentionResult
from qount.operations.backups import RestoreDrillResult
from qount.operations.backups import create_dashboard_backup
from qount.operations.backups import prune_dashboard_backups
from qount.operations.backups import verify_dashboard_restore_drill
from qount.operations.health_probes import HealthProbeConfig
from qount.operations.health_probes import HealthProbeDependencies
from qount.operations.health_probes import DEFAULT_ALLOWED_SERVICE_NAMES
from qount.operations.health_probes import collect_os_system_health
from qount.reporting import DashboardPublication
from qount.reporting import build_dashboard_v1
from qount.reporting import publish_dashboard_v1
from qount.reporting import read_dashboard_release_v1
from qount.reporting import read_dashboard_v1
from qount.reporting import read_vps_authority_bundle


class DashboardPublisherError(ValueError):
    """Raised when publishing cannot preserve the operational contract."""


class DashboardPublisherBusyError(DashboardPublisherError):
    """Raised when another publisher owns the non-blocking writer lock."""


@dataclass(frozen=True)
class PublisherConfig:
    repo_root: Path
    authority_root: Path
    dashboard_root: Path
    backup_root: Path
    lock_path: Path
    disk_path: Path
    intelligence_root: Path | None = None
    notification_store_path: Path | None = None
    operations_enabled: bool = True
    service_name: str = "qount-dashboard-publisher.timer"
    allowed_service_names: tuple[str, ...] = DEFAULT_ALLOWED_SERVICE_NAMES
    retain_previous_releases: int = 4
    retain_previous_backups: int = 60
    stale_after_seconds: int = 900
    alert_stale_after_seconds: int = 300
    report_stale_after_seconds: int = 90_000
    system_stale_after_seconds: int = 120

    def validate(self) -> None:
        paths = (
            self.repo_root,
            self.authority_root,
            self.dashboard_root,
            self.backup_root,
            self.lock_path,
            self.disk_path,
        )
        if any(not isinstance(path, Path) or not path.is_absolute() for path in paths):
            raise DashboardPublisherError("publisher_absolute_paths_required")
        if self.intelligence_root is not None and not self.intelligence_root.is_absolute():
            raise DashboardPublisherError("publisher_absolute_paths_required")
        if (
            self.notification_store_path is not None
            and not self.notification_store_path.is_absolute()
        ):
            raise DashboardPublisherError("publisher_absolute_paths_required")
        if (
            self.service_name not in self.allowed_service_names
            or len(set(self.allowed_service_names)) != len(self.allowed_service_names)
            or not isinstance(self.retain_previous_releases, int)
            or isinstance(self.retain_previous_releases, bool)
            or self.retain_previous_releases < 1
            or not isinstance(self.retain_previous_backups, int)
            or isinstance(self.retain_previous_backups, bool)
            or self.retain_previous_backups < 1
            or not isinstance(self.operations_enabled, bool)
        ):
            raise DashboardPublisherError("publisher_configuration_invalid")
        for value in (
            self.stale_after_seconds,
            self.alert_stale_after_seconds,
            self.report_stale_after_seconds,
            self.system_stale_after_seconds,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise DashboardPublisherError("publisher_staleness_invalid")


@dataclass(frozen=True)
class ReleaseRetentionResult:
    current_publication_id: str
    retained_release_ids: tuple[str, ...]
    pruned_release_ids: tuple[str, ...]
    skipped_release_names: tuple[str, ...]


@dataclass(frozen=True)
class PublisherResult:
    completed_at: str
    publication_id: str
    publication_hash: str
    system_health_status: str
    system_health_hash: str
    backup_id: str
    backup_manifest_hash: str
    backup_file_count: int
    backup_total_bytes: int
    restore_drill_verified: bool
    retained_release_ids: tuple[str, ...]
    pruned_release_ids: tuple[str, ...]
    skipped_release_names: tuple[str, ...]
    retained_backup_ids: tuple[str, ...]
    pruned_backup_ids: tuple[str, ...]
    skipped_backup_names: tuple[str, ...]
    result_hash: str

    @classmethod
    def create(
        cls,
        *,
        completed_at: str,
        publication: DashboardPublication,
        system_health_status: str,
        system_health_hash: str,
        backup: BackupRecord,
        restore: RestoreDrillResult,
        release_retention: ReleaseRetentionResult,
        backup_retention: BackupRetentionResult,
    ) -> PublisherResult:
        core = {
            "completed_at": aware_datetime(completed_at).isoformat(),
            "publication_id": publication.publication_id,
            "publication_hash": publication.publication_hash,
            "system_health_status": system_health_status,
            "system_health_hash": system_health_hash,
            "backup_id": backup.backup_id,
            "backup_manifest_hash": backup.manifest_hash,
            "backup_file_count": backup.file_count,
            "backup_total_bytes": backup.total_bytes,
            "restore_drill_verified": restore.verified,
            "retained_release_ids": release_retention.retained_release_ids,
            "pruned_release_ids": release_retention.pruned_release_ids,
            "skipped_release_names": release_retention.skipped_release_names,
            "retained_backup_ids": backup_retention.retained_backup_ids,
            "pruned_backup_ids": backup_retention.pruned_backup_ids,
            "skipped_backup_names": backup_retention.skipped_backup_names,
        }
        result = cls(**core, result_hash=canonical_hash(core))
        result.validate()
        return result

    def validate(self) -> None:
        for name in (
            "publication_id",
            "publication_hash",
            "system_health_hash",
            "backup_id",
            "backup_manifest_hash",
            "result_hash",
        ):
            if not is_sha256(getattr(self, name)):
                raise DashboardPublisherError(f"publisher_result_{name}_invalid")
        if self.system_health_status not in {"healthy", "degraded", "unavailable"}:
            raise DashboardPublisherError("publisher_result_health_invalid")
        if not self.restore_drill_verified or self.backup_file_count < 1 or self.backup_total_bytes < 1:
            raise DashboardPublisherError("publisher_result_backup_invalid")
        for values in (
            self.retained_release_ids,
            self.pruned_release_ids,
            self.retained_backup_ids,
            self.pruned_backup_ids,
        ):
            if (
                not isinstance(values, tuple)
                or tuple(sorted(values)) != values
                or len(values) != len(set(values))
                or any(not is_sha256(value) for value in values)
            ):
                raise DashboardPublisherError("publisher_result_releases_invalid")
        if set(self.retained_release_ids) & set(self.pruned_release_ids):
            raise DashboardPublisherError("publisher_result_release_overlap")
        if set(self.retained_backup_ids) & set(self.pruned_backup_ids):
            raise DashboardPublisherError("publisher_result_backup_overlap")
        if self.publication_id not in self.retained_release_ids:
            raise DashboardPublisherError("publisher_result_current_not_retained")
        if self.backup_id not in self.retained_backup_ids:
            raise DashboardPublisherError("publisher_result_latest_backup_not_retained")
        for values in (self.skipped_release_names, self.skipped_backup_names):
            if tuple(sorted(values)) != values or len(values) != len(set(values)):
                raise DashboardPublisherError("publisher_result_skipped_invalid")
        core = self.as_dict()
        core.pop("result_hash")
        if self.result_hash != canonical_hash(core):
            raise DashboardPublisherError("publisher_result_hash_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "completed_at": self.completed_at,
            "publication_id": self.publication_id,
            "publication_hash": self.publication_hash,
            "system_health_status": self.system_health_status,
            "system_health_hash": self.system_health_hash,
            "backup_id": self.backup_id,
            "backup_manifest_hash": self.backup_manifest_hash,
            "backup_file_count": self.backup_file_count,
            "backup_total_bytes": self.backup_total_bytes,
            "restore_drill_verified": self.restore_drill_verified,
            "retained_release_ids": list(self.retained_release_ids),
            "pruned_release_ids": list(self.pruned_release_ids),
            "skipped_release_names": list(self.skipped_release_names),
            "retained_backup_ids": list(self.retained_backup_ids),
            "pruned_backup_ids": list(self.pruned_backup_ids),
            "skipped_backup_names": list(self.skipped_backup_names),
            "result_hash": self.result_hash,
        }


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise DashboardPublisherError("publisher_path_symlink_rejected")


def _ensure_directory(path: Path, *, mode: int, name: str) -> None:
    _reject_symlink_components(path)
    if not path.exists():
        path.mkdir(parents=True, mode=mode)
    if path.is_symlink() or not path.is_dir():
        raise DashboardPublisherError(f"{name}_directory_invalid")
    actual_mode = stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode)
    if actual_mode != mode:
        raise DashboardPublisherError(f"{name}_directory_mode_invalid")


def _prepare_lock_parent(path: Path) -> None:
    _ensure_directory(path.parent, mode=0o700, name="publisher_lock_parent")
    if path.is_symlink():
        raise DashboardPublisherError("publisher_lock_symlink_rejected")


@contextmanager
def single_writer_lock(path: Path) -> Iterator[None]:
    """Acquire the publisher lock without waiting for another writer."""

    _prepare_lock_parent(path)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise DashboardPublisherError("publisher_lock_file_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DashboardPublisherBusyError("publisher_lock_busy") from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _current_publication_id(root: Path) -> str:
    _, publication = read_dashboard_v1(root)
    return publication.publication_id


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prune_dashboard_releases(
    root: str | Path,
    *,
    retain_previous_releases: int,
) -> ReleaseRetentionResult:
    """Delete only verified, unreferenced releases outside the retention set."""

    if (
        not isinstance(retain_previous_releases, int)
        or isinstance(retain_previous_releases, bool)
        or retain_previous_releases < 1
    ):
        raise DashboardPublisherError("publisher_retention_invalid")
    dashboard = Path(root)
    current = _current_publication_id(dashboard)
    releases = dashboard / "releases"
    verified: list[tuple[dt.datetime, str]] = []
    skipped: list[str] = []
    for path in releases.iterdir():
        if path.name.startswith("."):
            skipped.append(path.name)
            continue
        if path.is_symlink() or not path.is_dir() or not is_sha256(path.name):
            skipped.append(path.name)
            continue
        try:
            _, publication = read_dashboard_release_v1(dashboard, path.name)
        except (OSError, ValueError):
            skipped.append(path.name)
            continue
        verified.append((aware_datetime(publication.generated_at), path.name))
    verified.sort(key=lambda row: (row[0], row[1]), reverse=True)
    previous = [name for _, name in verified if name != current]
    keep = {current, *previous[:retain_previous_releases]}
    prune = sorted(name for _, name in verified if name not in keep)
    for publication_id in prune:
        if _current_publication_id(dashboard) != current:
            raise DashboardPublisherError("publisher_current_changed_during_prune")
        target = releases / publication_id
        if target.is_symlink() or not target.is_dir():
            raise DashboardPublisherError("publisher_prune_target_invalid")
        shutil.rmtree(target)
    if prune:
        _fsync_directory(releases)
    return ReleaseRetentionResult(
        current_publication_id=current,
        retained_release_ids=tuple(sorted(keep)),
        pruned_release_ids=tuple(prune),
        skipped_release_names=tuple(sorted(skipped)),
    )


def _prepare_output_paths(config: PublisherConfig) -> None:
    _ensure_directory(config.dashboard_root, mode=0o755, name="dashboard_root")
    _ensure_directory(config.backup_root, mode=0o700, name="backup_root")
    dashboard_device = os.stat(config.dashboard_root, follow_symlinks=False).st_dev
    backup_device = os.stat(config.backup_root, follow_symlinks=False).st_dev
    if dashboard_device != backup_device:
        raise DashboardPublisherError("publisher_cross_device_output_rejected")


def run_dashboard_publisher(
    config: PublisherConfig,
    *,
    observed_at: str,
    dependencies: HealthProbeDependencies | None = None,
) -> PublisherResult:
    """Run one complete locked publish, backup, restore drill, and prune cycle."""

    config.validate()
    completed_at = aware_datetime(observed_at).isoformat()
    with single_writer_lock(config.lock_path):
        _prepare_output_paths(config)
        bundle = read_vps_authority_bundle(config.authority_root)
        notification_snapshot = (
            build_notification_snapshot(
                NotificationStore(
                    config.notification_store_path,
                    read_only=True,
                ),
                captured_at=completed_at,
            )
            if config.notification_store_path is not None
            else bundle.notification_snapshot
        )
        intelligence = (
            read_latest_daily_intelligence(config.intelligence_root)
            if config.intelligence_root is not None
            and (config.intelligence_root / "latest").exists()
            else None
        )
        health = collect_os_system_health(
            HealthProbeConfig(
                disk_path=config.disk_path,
                service_name=config.service_name,
                allowed_service_names=config.allowed_service_names,
                backup_root=config.backup_root,
                repo_root=config.repo_root,
                state_root=config.repo_root / "state" / "mini_trend",
                operations_enabled=config.operations_enabled,
            ),
            observed_at=completed_at,
            captured_at=completed_at,
            dependencies=dependencies,
        )
        models = build_dashboard_v1(
            bundle.batch,
            bundle.registry,
            generated_at=completed_at,
            evaluated_at=completed_at,
            stale_after_seconds=config.stale_after_seconds,
            ledger_snapshot=bundle.ledger_snapshot,
            notification_snapshot=notification_snapshot,
            daily_brief_notification_snapshot=bundle.notification_snapshot,
            alert_stale_after_seconds=config.alert_stale_after_seconds,
            daily_brief=bundle.daily_brief,
            report_stale_after_seconds=config.report_stale_after_seconds,
            daily_intelligence=intelligence,
            system_health=health,
            system_stale_after_seconds=config.system_stale_after_seconds,
        )
        publication = publish_dashboard_v1(config.dashboard_root, models)
        read_models, read_publication = read_dashboard_v1(config.dashboard_root)
        if read_models != models or read_publication != publication:
            raise DashboardPublisherError("publisher_release_readback_mismatch")
        backup = create_dashboard_backup(
            config.dashboard_root,
            config.backup_root,
            completed_at=completed_at,
        )
        restore = verify_dashboard_restore_drill(config.backup_root, backup.backup_id)
        if (
            restore.publication_id != publication.publication_id
            or restore.publication_hash != publication.publication_hash
        ):
            raise DashboardPublisherError("publisher_restore_publication_mismatch")
        backup_retention = prune_dashboard_backups(
            config.backup_root,
            retain_previous_backups=config.retain_previous_backups,
        )
        release_retention = prune_dashboard_releases(
            config.dashboard_root,
            retain_previous_releases=config.retain_previous_releases,
        )
        return PublisherResult.create(
            completed_at=completed_at,
            publication=publication,
            system_health_status=health.status,
            system_health_hash=health.snapshot_hash,
            backup=backup,
            restore=restore,
            release_retention=release_retention,
            backup_retention=backup_retention,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish verified Dashboard v1 read models without execution authority."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--authority-root", type=Path, required=True)
    parser.add_argument("--dashboard-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--lock-path", type=Path, required=True)
    parser.add_argument("--disk-path", type=Path, required=True)
    parser.add_argument("--intelligence-root", type=Path)
    parser.add_argument("--notification-store", type=Path)
    parser.add_argument(
        "--service-name",
        choices=DEFAULT_ALLOWED_SERVICE_NAMES,
        default="qount-dashboard-publisher.timer",
    )
    parser.add_argument("--retain-previous-releases", type=int, default=4)
    parser.add_argument("--retain-previous-backups", type=int, default=60)
    parser.add_argument("--stale-after-seconds", type=int, default=900)
    parser.add_argument("--alert-stale-after-seconds", type=int, default=300)
    parser.add_argument("--report-stale-after-seconds", type=int, default=90_000)
    parser.add_argument("--system-stale-after-seconds", type=int, default=120)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = PublisherConfig(
        repo_root=args.repo_root,
        authority_root=args.authority_root,
        dashboard_root=args.dashboard_root,
        backup_root=args.backup_root,
        lock_path=args.lock_path,
        disk_path=args.disk_path,
        intelligence_root=args.intelligence_root,
        notification_store_path=args.notification_store,
        service_name=args.service_name,
        retain_previous_releases=args.retain_previous_releases,
        retain_previous_backups=args.retain_previous_backups,
        stale_after_seconds=args.stale_after_seconds,
        alert_stale_after_seconds=args.alert_stale_after_seconds,
        report_stale_after_seconds=args.report_stale_after_seconds,
        system_stale_after_seconds=args.system_stale_after_seconds,
    )
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        result = run_dashboard_publisher(config, observed_at=now)
    except DashboardPublisherBusyError as exc:
        print(json.dumps({"status": "busy", "error": str(exc)}, sort_keys=True))
        return 75
    except (OSError, TypeError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc), "error_type": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps({"status": "published", **result.as_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_ALLOWED_SERVICE_NAMES",
    "DashboardPublisherBusyError",
    "DashboardPublisherError",
    "PublisherConfig",
    "PublisherResult",
    "ReleaseRetentionResult",
    "main",
    "prune_dashboard_releases",
    "run_dashboard_publisher",
    "single_writer_lock",
]
