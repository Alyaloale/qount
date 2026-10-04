"""Explicit research compute profiles; no service, credential or account access."""
from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import subprocess

from .artifacts import EXTERNAL_ROOT

GIB = 1024 ** 3


def cpu_capacity(cgroup=Path("/sys/fs/cgroup")):
    """Containers often expose host affinity despite a smaller CPU quota."""
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    quota = cgroup / "cpu.max"
    if quota.exists():
        amount, period = quota.read_text().split()
        if amount != "max":
            affinity = min(affinity, max(1, int(amount) // int(period)))
    else:
        quota, period = cgroup / "cpu/cpu.cfs_quota_us", cgroup / "cpu/cpu.cfs_period_us"
        if quota.exists() and period.exists() and int(quota.read_text()) > 0:
            affinity = min(affinity, max(1, int(quota.read_text()) // int(period.read_text())))
    return affinity


def memory_capacity(cgroup=Path("/sys/fs/cgroup"), meminfo=Path("/proc/meminfo")):
    fields = {line.split(":")[0]: int(line.split()[1]) * 1024 for line in meminfo.read_text().splitlines()}
    total = fields["MemTotal"]
    for name in ("memory.max", "memory/memory.limit_in_bytes"):
        path = cgroup / name
        if path.exists() and path.read_text().strip() != "max":
            total = min(total, int(path.read_text()))
    return total


def profile(config):
    value = config.get("compute_profile")
    if value is None:
        return {"kind": "wsl_4060", "storage_root": str(EXTERNAL_ROOT), "mount": "/mnt/e",
                "gpu_name": "4060", "cpu_limit": 24, "disk_reserve_bytes": 10 * GIB,
                "diagnostic_workers": 2, "compile_real": True, "compile_bootstrap": True,
                "price_per_hour_cny": 0.0}
    required = {"kind", "storage_root", "mount", "gpu_name", "cpu_limit", "disk_reserve_bytes",
                "diagnostic_workers", "compile_real", "compile_bootstrap", "price_per_hour_cny", "machine_id"}
    if not required.issubset(value) or value["kind"] != "cloud_3080ti" or value["machine_id"] != "jn1f8a7n6z":
        raise ValueError("explicit new 3080 Ti research compute profile required")
    if value["gpu_name"] != "RTX 3080 Ti" or value["mount"] != "/root/autodl-tmp":
        raise ValueError("undeclared cloud GPU/data mount")
    root = Path(value["storage_root"])
    relative = root.resolve().relative_to(Path(value["mount"]).resolve())
    if not relative.parts or not root.is_absolute():
        raise ValueError("a dedicated absolute cloud scratch root is required")
    if not 1 <= value["cpu_limit"] <= 20 or not 1 <= value["diagnostic_workers"] <= 4:
        raise ValueError("cloud CPU allocation exceeded")
    if value["disk_reserve_bytes"] < 8 * GIB:
        raise ValueError("eight GiB result/compiler/disk safety reserve required")
    for key in ("compile_real", "compile_bootstrap"):
        if type(value[key]) is not bool:
            raise ValueError("explicit compilation booleans required")
    price = value["price_per_hour_cny"]
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValueError("a finite positive declared instance price required")
    return value


def storage_preflight(config, spec, *, reuse_bootstrap=False, mounts=Path("/proc/mounts")):
    value = profile(config)
    mount, root = Path(value["mount"]), Path(value["storage_root"])
    mounted = {line.split()[1] for line in mounts.read_text().splitlines()}
    if str(mount) not in mounted:
        raise ValueError(f"declared compute data disk is not mounted: {mount}")
    if not root.is_dir():
        raise ValueError("declared compute storage root missing; refusing fallback")
    needed = value["disk_reserve_bytes"] + (0 if reuse_bootstrap else spec.estimated_bytes_per_fold * 7)
    usage = shutil.disk_usage(root)
    if usage.free < needed:
        raise ValueError(f"insufficient data disk: need {needed}, free {usage.free} bytes")
    return {"profile": value, "free_bytes": usage.free, "required_free_bytes": needed,
            "effective_cpus": min(cpu_capacity(), value["cpu_limit"]),
            "memory_limit_bytes": memory_capacity()}


def gpu_preflight(config):
    import torch
    value = profile(config)
    if not torch.cuda.is_available() or value["gpu_name"] not in torch.cuda.get_device_name(0):
        raise RuntimeError(f"declared {value['gpu_name']} compute GPU is unavailable")
    if value["kind"] == "cloud_3080ti":
        import numpy as np
        if torch.__version__.split("+")[0] != "2.13.0" or torch.version.cuda != "13.0" or np.__version__ != "2.5.1":
            raise ValueError("isolated pinned Torch2.13/cu130/NumPy2.5.1 environment required")
        if torch.cuda.device_count() != 1:
            raise ValueError("expose only the single allocated GPU with CUDA_VISIBLE_DEVICES")
        if torch.cuda.get_device_capability(0) != (8, 6):
            raise ValueError("3080 Ti compute capability mismatch")
        free, total = torch.cuda.mem_get_info()
        if total < 11 * GIB or free < 9 * GIB:
            raise ValueError("12 GB GPU allocation is missing or occupied")
    return {"gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda,
            "torch": torch.__version__, "visible_devices": torch.cuda.device_count()}


def runtime_environment(config):
    """Own cache paths and bounded compiler parallelism; no private environment file."""
    value = profile(config)
    if value["kind"] != "cloud_3080ti":
        return
    cache = Path(value["storage_root"]) / "cache"
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = str(cache / "inductor")
    os.environ["TRITON_CACHE_DIR"] = str(cache / "triton")
    os.environ["TORCHINDUCTOR_COMPILE_THREADS"] = "4"
    os.environ["MAX_JOBS"] = "8"


def monitor_compute(log, stopped, value):
    smi = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
    while not stopped.wait(15):
        try:
            gpu = subprocess.run([smi, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
            log.emit("resources", gpu_csv=gpu.stdout.strip(), gpu_probe_returncode=gpu.returncode,
                     load_average=list(os.getloadavg()), effective_cpus=cpu_capacity(),
                     data_disk_free_bytes=shutil.disk_usage(value["storage_root"]).free,
                     declared_price_per_hour_cny=value["price_per_hour_cny"])
        except Exception as exc:
            log.emit("resource_probe_failed", error=str(exc))
