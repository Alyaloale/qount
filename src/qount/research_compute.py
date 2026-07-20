"""Reproducibility manifest for disposable research compute nodes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from qount.models import utc_now


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _command_output(command: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(
            list(command),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip()


def _os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def _memory_total_bytes(path: Path = Path("/proc/meminfo")) -> int | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    return None


def _torch_environment() -> dict[str, Any] | None:
    if importlib.util.find_spec("torch") is None:
        return None
    import torch

    cuda_available = bool(torch.cuda.is_available())
    return {
        "version": torch.__version__,
        "cuda_runtime_version": torch.version.cuda,
        "cuda_available": cuda_available,
        "cudnn_version": torch.backends.cudnn.version(),
        "device_count": torch.cuda.device_count() if cuda_available else 0,
        "device_names": [
            torch.cuda.get_device_name(index)
            for index in range(torch.cuda.device_count() if cuda_available else 0)
        ],
    }


def build_research_compute_manifest(
    project_root: Path,
    *,
    dataset_path: Path | None,
    code_paths: Sequence[Path],
) -> dict[str, Any]:
    root = project_root.expanduser().resolve()
    resolved_code_paths = [
        path if path.is_absolute() else root / path
        for path in code_paths
    ]
    code_hashes = {
        str(path.resolve().relative_to(root)): _sha256_file(path.resolve())
        for path in resolved_code_paths
    }
    disk = shutil.disk_usage(root)
    pip_freeze = _command_output([sys.executable, "-m", "pip", "freeze", "--all"])
    environment = {
        "os_release": _os_release(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "cpu_count": os.cpu_count(),
        "memory_total_bytes": _memory_total_bytes(),
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
        "nvidia_smi": _command_output(["nvidia-smi"]),
        "torch": _torch_environment(),
        "pip_freeze": pip_freeze.splitlines() if pip_freeze else [],
    }
    evidence: dict[str, Any] = {
        "code_file_sha256": code_hashes,
        "code_bundle_hash": _canonical_hash(code_hashes),
    }
    if dataset_path is not None:
        dataset_target = dataset_path.expanduser().resolve()
        source = json.loads(dataset_target.read_text(encoding="utf-8"))
        dataset = source.get("dataset", source)
        evidence.update(
            {
                "dataset_path": str(dataset_target.relative_to(root)),
                "dataset_file_sha256": _sha256_file(dataset_target),
                "dataset_contract_hash": dataset["contract"]["contract_hash"],
                "dataset_data_hash": dataset["data_hash"],
            }
        )
    return {
        "schema_version": "qount_research_compute_manifest_v0.1",
        "artifact_type": "research_compute_environment_manifest",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "contains_production_credentials": False,
            "paper_or_live_allowed": False,
        },
        "environment": environment,
        "evidence": evidence,
        "manifest_hash": _canonical_hash(
            {"environment": environment, "evidence": evidence}
        ),
    }
