"""Read-only OS probes for the explicit four-component health contract."""

from __future__ import annotations

import csv
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from qount.contracts import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.notifications import SystemHealthSnapshot
from qount.notifications import collect_system_health
from qount.operations.backups import BackupError
from qount.operations.backups import read_latest_dashboard_backup


_SERVICE_STATES = {"active", "inactive", "failed"}
_OFFSET_RE = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(us|ms|s)?$")
_OFFSET_SCALE = {None: 0.000001, "us": 0.000001, "ms": 0.001, "s": 1.0}
DEFAULT_ALLOWED_SERVICE_NAMES = (
    "qount-dashboard-publisher.timer",
    "caddy.service",
)


class HealthProbeError(ValueError):
    """Raised when probe configuration is unsafe or internally inconsistent."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[tuple[str, ...]], CommandResult]


class DiskUsage(Protocol):
    total: int
    used: int
    free: int


DiskUsageReader = Callable[[str | Path], DiskUsage]


@dataclass(frozen=True)
class HealthProbeDependencies:
    command_runner: CommandRunner
    disk_usage: DiskUsageReader = shutil.disk_usage

    @classmethod
    def system(cls) -> HealthProbeDependencies:
        return cls(command_runner=_run_command)


@dataclass(frozen=True)
class HealthProbeConfig:
    disk_path: Path
    service_name: str
    allowed_service_names: tuple[str, ...]
    backup_root: Path
    clock_warning_seconds: float = 0.5
    clock_unavailable_seconds: float = 5.0
    disk_warning_fraction: float = 0.10
    disk_unavailable_fraction: float = 0.02
    disk_warning_free_bytes: int = 1_073_741_824
    disk_unavailable_free_bytes: int = 268_435_456
    backup_warning_seconds: int = 90_000
    backup_unavailable_seconds: int = 180_000

    def validate(self) -> None:
        if (
            not isinstance(self.disk_path, Path)
            or not isinstance(self.backup_root, Path)
            or not self.service_name
            or self.service_name not in self.allowed_service_names
            or len(set(self.allowed_service_names)) != len(self.allowed_service_names)
        ):
            raise HealthProbeError("health_probe_configuration_invalid")
        if (
            not math.isfinite(self.clock_warning_seconds)
            or not math.isfinite(self.clock_unavailable_seconds)
            or not math.isfinite(self.disk_warning_fraction)
            or not math.isfinite(self.disk_unavailable_fraction)
            or self.clock_warning_seconds < 0
            or self.clock_unavailable_seconds <= self.clock_warning_seconds
            or not 0 < self.disk_unavailable_fraction < self.disk_warning_fraction < 1
            or self.disk_unavailable_free_bytes < 0
            or self.disk_warning_free_bytes <= self.disk_unavailable_free_bytes
            or self.backup_warning_seconds < 1
            or self.backup_unavailable_seconds <= self.backup_warning_seconds
        ):
            raise HealthProbeError("health_probe_thresholds_invalid")


def _run_command(argv: tuple[str, ...]) -> CommandResult:
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _source_id(component: str, source: Mapping[str, object]) -> str:
    return canonical_hash({"health_probe": component, "source": dict(source)})


def _failure_evidence(component: str, exc: BaseException) -> dict[str, object]:
    return {"probe": component, "error_type": type(exc).__name__}


def _command_evidence(argv: tuple[str, ...], result: CommandResult) -> dict[str, object]:
    return {
        "argv": list(argv),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _measurement(
    *,
    status: str,
    detail_codes: tuple[str, ...],
    metrics: Mapping[str, object],
    source_id: str,
    source_hash: str,
) -> dict[str, object]:
    return {
        "status": status,
        "detail_codes": detail_codes,
        "metrics": dict(metrics),
        "source_id": source_id,
        "source_hash": source_hash,
    }


def _parse_offset_seconds(raw: str) -> float:
    match = _OFFSET_RE.fullmatch(raw.strip())
    if match is None:
        raise ValueError("clock_offset_invalid")
    value = float(match.group(1))
    return value * _OFFSET_SCALE[match.group(2)]


def _parse_chrony_tracking(raw: str) -> tuple[float, bool]:
    lines = raw.strip().splitlines()
    if len(lines) != 1:
        raise ValueError("chrony_tracking_invalid")
    fields = next(csv.reader(lines))
    if len(fields) != 14:
        raise ValueError("chrony_tracking_invalid")
    drift_seconds = float(fields[4])
    if not math.isfinite(drift_seconds):
        raise ValueError("chrony_tracking_invalid")
    leap_status = fields[13].strip().lower()
    if leap_status not in {
        "normal",
        "insert second",
        "delete second",
        "not synchronised",
    }:
        raise ValueError("chrony_tracking_invalid")
    return drift_seconds, leap_status != "not synchronised"


def probe_clock(
    config: HealthProbeConfig,
    runner: CommandRunner,
) -> dict[str, object]:
    sync_argv = (
        "timedatectl",
        "show",
        "--property=NTPSynchronized",
        "--value",
    )
    offset_argv = (
        "timedatectl",
        "show-timesync",
        "--property=OffsetUSec",
        "--value",
    )
    chrony_argv = ("chronyc", "-c", "tracking")
    source_id = _source_id(
        "clock",
        {
            "commands": [
                list(sync_argv),
                list(offset_argv),
                list(chrony_argv),
            ]
        },
    )
    evidence: dict[str, object] = {}
    try:
        sync = runner(sync_argv)
        offset = runner(offset_argv)
        evidence = {
            "synchronization": _command_evidence(sync_argv, sync),
            "offset": _command_evidence(offset_argv, offset),
        }
        synchronized: str | None = None
        if sync.returncode == 0:
            synchronized = sync.stdout.strip().lower()
            if synchronized not in {"yes", "no", "true", "false", "1", "0"}:
                raise ValueError("clock_sync_state_invalid")
        if sync.returncode == 0 and offset.returncode == 0:
            drift_seconds = _parse_offset_seconds(offset.stdout)
            synchronized_value = synchronized in {"yes", "true", "1"}
        else:
            chrony = runner(chrony_argv)
            evidence["chrony_tracking"] = _command_evidence(chrony_argv, chrony)
            if chrony.returncode != 0:
                return _measurement(
                    status="unavailable",
                    detail_codes=("clock_probe_failed",),
                    metrics={"drift_seconds": None},
                    source_id=source_id,
                    source_hash=canonical_hash(evidence),
                )
            drift_seconds, chrony_synchronized = _parse_chrony_tracking(
                chrony.stdout
            )
            synchronized_value = chrony_synchronized and (
                synchronized is None
                or synchronized in {"yes", "true", "1"}
            )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence = dict(evidence) | {
            "parse_error": _failure_evidence("clock", exc)
        }
        return _measurement(
            status="unavailable",
            detail_codes=("clock_observation_invalid",),
            metrics={"drift_seconds": None},
            source_id=source_id,
            source_hash=canonical_hash(evidence),
        )
    absolute_drift = abs(drift_seconds)
    if not synchronized_value:
        status = "unavailable"
        codes = ("clock_not_synchronized",)
    elif absolute_drift > config.clock_unavailable_seconds:
        status = "unavailable"
        codes = ("clock_drift_unavailable",)
    elif absolute_drift > config.clock_warning_seconds:
        status = "degraded"
        codes = ("clock_drift_warning",)
    else:
        status = "healthy"
        codes = ()
    return _measurement(
        status=status,
        detail_codes=codes,
        metrics={"drift_seconds": drift_seconds},
        source_id=source_id,
        source_hash=canonical_hash(evidence),
    )


def probe_disk(
    config: HealthProbeConfig,
    disk_usage: DiskUsageReader,
) -> dict[str, object]:
    source_id = _source_id("disk", {"path": str(config.disk_path)})
    try:
        usage = disk_usage(config.disk_path)
        free_bytes = int(usage.free)
        total_bytes = int(usage.total)
        if total_bytes < 1 or free_bytes < 0 or free_bytes > total_bytes:
            raise ValueError("disk_usage_invalid")
        evidence: dict[str, object] = {
            "path": str(config.disk_path),
            "free_bytes": free_bytes,
            "total_bytes": total_bytes,
        }
    except (OSError, ValueError, TypeError) as exc:
        evidence = _failure_evidence("disk", exc)
        return _measurement(
            status="unavailable",
            detail_codes=("disk_probe_failed",),
            metrics={"free_bytes": None, "total_bytes": None},
            source_id=source_id,
            source_hash=canonical_hash(evidence),
        )
    free_fraction = free_bytes / total_bytes
    if (
        free_fraction <= config.disk_unavailable_fraction
        or free_bytes <= config.disk_unavailable_free_bytes
    ):
        status = "unavailable"
        codes = ("disk_space_unavailable",)
    elif (
        free_fraction <= config.disk_warning_fraction
        or free_bytes <= config.disk_warning_free_bytes
    ):
        status = "degraded"
        codes = ("disk_space_warning",)
    else:
        status = "healthy"
        codes = ()
    return _measurement(
        status=status,
        detail_codes=codes,
        metrics={"free_bytes": free_bytes, "total_bytes": total_bytes},
        source_id=source_id,
        source_hash=canonical_hash(evidence),
    )


def probe_service(
    config: HealthProbeConfig,
    runner: CommandRunner,
) -> dict[str, object]:
    argv = (
        "systemctl",
        "show",
        config.service_name,
        "--property=ActiveState",
        "--value",
        "--no-pager",
    )
    source_id = _source_id(
        "service",
        {"service_name": config.service_name, "command": list(argv)},
    )
    try:
        result = runner(argv)
        evidence = _command_evidence(argv, result)
        raw_state = result.stdout.strip().lower()
        if result.returncode != 0:
            state = "unknown"
            status = "unavailable"
            codes = ("service_probe_failed",)
        elif raw_state not in _SERVICE_STATES:
            state = "unknown"
            status = "unavailable"
            codes = ("service_state_unknown",)
        elif raw_state == "active":
            state = raw_state
            status = "healthy"
            codes = ()
        elif raw_state == "inactive":
            state = raw_state
            status = "degraded"
            codes = ("service_inactive",)
        else:
            state = raw_state
            status = "unavailable"
            codes = ("service_failed",)
    except (OSError, subprocess.SubprocessError) as exc:
        evidence = _failure_evidence("service", exc)
        state = "unknown"
        status = "unavailable"
        codes = ("service_probe_failed",)
    return _measurement(
        status=status,
        detail_codes=codes,
        metrics={"service_name": config.service_name, "active_state": state},
        source_id=source_id,
        source_hash=canonical_hash(evidence),
    )


def probe_backup(
    config: HealthProbeConfig,
    *,
    observed_at: str,
) -> dict[str, object]:
    fallback_source_id = _source_id(
        "backup",
        {"marker": "latest-success.json", "root": str(config.backup_root)},
    )
    try:
        record = read_latest_dashboard_backup(config.backup_root)
        age_seconds = int(
            (
                aware_datetime(observed_at)
                - aware_datetime(record.completed_at)
            ).total_seconds()
        )
        if age_seconds < 0:
            raise ValueError("backup_marker_from_future")
    except (BackupError, OSError, ValueError, TypeError) as exc:
        return _measurement(
            status="unavailable",
            detail_codes=("backup_observation_unavailable",),
            metrics={"last_success_at": None, "age_seconds": None},
            source_id=fallback_source_id,
            source_hash=canonical_hash(_failure_evidence("backup", exc)),
        )
    if age_seconds > config.backup_unavailable_seconds:
        status = "unavailable"
        codes = ("backup_too_old",)
    elif age_seconds > config.backup_warning_seconds:
        status = "degraded"
        codes = ("backup_stale",)
    else:
        status = "healthy"
        codes = ()
    return _measurement(
        status=status,
        detail_codes=codes,
        metrics={
            "last_success_at": record.completed_at,
            "age_seconds": age_seconds,
        },
        source_id=record.source_id,
        source_hash=record.source_hash,
    )


def collect_os_system_health(
    config: HealthProbeConfig,
    *,
    observed_at: str,
    captured_at: str,
    dependencies: HealthProbeDependencies | None = None,
) -> SystemHealthSnapshot:
    """Run the fixed read-only probes and build one verified health snapshot."""

    config.validate()
    actual = dependencies or HealthProbeDependencies.system()
    measurements = {
        "clock": probe_clock(config, actual.command_runner),
        "disk": probe_disk(config, actual.disk_usage),
        "service": probe_service(config, actual.command_runner),
        "backup": probe_backup(config, observed_at=observed_at),
    }
    return collect_system_health(
        measurements,
        observed_at=observed_at,
        captured_at=captured_at,
    )


__all__ = [
    "CommandResult",
    "DEFAULT_ALLOWED_SERVICE_NAMES",
    "HealthProbeConfig",
    "HealthProbeDependencies",
    "HealthProbeError",
    "collect_os_system_health",
    "probe_backup",
    "probe_clock",
    "probe_disk",
    "probe_service",
]
