"""CPU-only synthetic worlds and immutable, resumable NPY datasets.

Generation never imports torch. Workers write their own shards, returning only receipts;
the completed manifest is the publication barrier used by training. Research only, no orders.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import platform
import shutil
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .costs import RANDOMIZATION_RANGE
from .features import ASSET_STATIC_DIM, MARKET_DIM, WorldFeatures, world_features
from .generator import native
from .generator.params import YEAR, sample_world
from .generator.plausibility import check
from .generator.specs import ACCOUNT_SPECS
from .generator.structural import simulate_world
from .universe import ACCOUNTS

SPLITS = {"train": 0, "val": 1, "test": 2}
SCHEMA = "qount.synthetic-worlds.v1"


@dataclass
class WorldArrays:
    close_adj: np.ndarray
    close: np.ndarray
    open: np.ndarray
    adv: np.ndarray
    sigma: np.ndarray
    cash_return: np.ndarray
    spread: np.ndarray
    buy_blocked: np.ndarray
    features: WorldFeatures
    spread_mult: float
    impact_mult: float
    params_seed: int


def world_seed(root: int, split: str, index: int) -> np.random.SeedSequence:
    return np.random.SeedSequence((root, SPLITS[split], index))


def generate_world(account: str, root: int, split: str, index: int, years: float, warmup_years: float,
                   plausibility_years: float = 100.0, max_draws: int = 50, backend: str = "auto") -> WorldArrays:
    rng = np.random.default_rng(world_seed(root, split, index))
    spec, acct = ACCOUNT_SPECS[account], ACCOUNTS[account]
    for _ in range(max_draws):
        params = sample_world(account, rng)
        if plausibility_years <= 0 or not check(
            simulate_world(spec, params, years=plausibility_years, backend=backend)
        )[1]:
            break
    else:
        raise RuntimeError(f"no plausible world in {max_draws} draws ({split}/{index})")
    w = simulate_world(spec, params, years=years, warmup_years=warmup_years, backend=backend)
    d = w.data
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        f = world_features(d.close_adj, acct, w.valuation, d.adv, d.spread)
    s = w.start
    lo, hi = RANDOMIZATION_RANGE
    return WorldArrays(
        close_adj=d.close_adj[s:], close=d.close[s:], open=d.open[s:], adv=d.adv[s:], sigma=d.sigma[s:],
        cash_return=d.cash_return[s:], spread=d.spread[s:], buy_blocked=d.buy_blocked[s:], features=f.sliced(s),
        spread_mult=float(rng.uniform(lo, hi)), impact_mult=float(rng.uniform(lo, hi)), params_seed=params.seed,
    )


def _gen(args):
    return generate_world(*args)


@dataclass(frozen=True)
class WorldDatasetConfig:
    account: str = "us"
    seed: int = 20260930
    split: str = "train"
    worlds: int = 256
    start_index: int = 0
    years: float = 8.0
    warmup_years: float = 10.0
    plausibility_years: float = 100.0
    max_draws: int = 50
    shard_worlds: int = 64
    dtype: str = "float32"  # exactly the values consumed by float32 training
    backend: str = "native"

    def validate(self) -> None:
        if self.account not in ACCOUNTS or self.split not in SPLITS:
            raise ValueError("unknown account or split")
        for name in ("worlds", "shard_worlds", "max_draws"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.seed) is not int or self.seed < 0 or type(self.start_index) is not int or self.start_index < 0:
            raise ValueError("seed/start_index must be nonnegative integers")
        if not all(np.isfinite(x) for x in (self.years, self.warmup_years, self.plausibility_years)):
            raise ValueError("world durations must be finite")
        if self.years <= 0 or self.warmup_years < 0 or self.plausibility_years < 0 or self.rows < 2:
            raise ValueError("invalid world durations")
        if self.dtype not in ("float32", "float64") or self.backend not in ("native", "numpy", "auto"):
            raise ValueError("unsupported dtype or backend")

    @property
    def rows(self) -> int:
        return round((self.warmup_years + self.years) * YEAR) + 1 - round(self.warmup_years * YEAR)


def _layout(cfg: WorldDatasetConfig, count: int) -> dict[str, tuple[tuple[int, ...], str]]:
    B, T, n, dt = count, cfg.rows, ACCOUNTS[cfg.account].n_assets, cfg.dtype
    out = {k: ((B, T, n), dt) for k in ("close_adj", "close", "open", "adv", "sigma", "spread",
                                        "features_sigma", "tradable")}
    out.update({k: ((B, T, n), "bool") for k in ("buy_blocked", "eligible", "reduce_only")})
    out.update({"cash_return": ((B, T), dt), "asset": ((B, T, n, ASSET_STATIC_DIM), dt),
                "market": ((B, T, MARKET_DIM), dt), "spread_mult": ((B,), dt), "impact_mult": ((B,), dt),
                "params_seed": ((B,), "uint64"), "value_enabled": ((B,), "bool")})
    return out


def estimated_bytes(cfg: WorldDatasetConfig) -> int:
    cfg.validate()
    return sum(int(np.prod(shape)) * np.dtype(dt).itemsize for shape, dt in _layout(cfg, cfg.worlds).values())


def _arrays(w: WorldArrays) -> dict:
    return {**{k: getattr(w, k) for k in ("close_adj", "close", "open", "adv", "sigma", "cash_return",
                                         "spread", "buy_blocked", "spread_mult", "impact_mult", "params_seed")},
            **{k: getattr(w.features, k) for k in ("asset", "eligible", "market", "tradable", "reduce_only",
                                                  "value_enabled")}, "features_sigma": w.features.sigma}


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _write_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as f:
        f.write(_json_bytes(value))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _source_hashes() -> dict:
    root = Path(__file__).parent
    paths = [root / k for k in ("worlds.py", "features.py", "scorer.py", "costs.py", "constraints.py",
                                "universe.py", "env.py")]
    paths += sorted((root / "generator").rglob("*.py"))
    paths.append(native.SOURCE)
    return {p.relative_to(root).as_posix(): _hash(p) for p in paths}


def cpu_workers(requested: int) -> int:
    if requested < 0:
        raise ValueError("workers must be nonnegative (0 uses available CPUs)")
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    return min(requested or available, available)


_thread_limit = None


def init_cpu_worker() -> None:
    # Avoid workers × BLAS threads. No CUDA initialization or environment/secret loading.
    global _thread_limit
    try:
        from threadpoolctl import threadpool_limits
        _thread_limit = threadpool_limits(limits=1)
    except ImportError:
        pass  # NumPy-only installations may have no threaded BLAS controller.


def _write_shard(job) -> dict:
    cfg, backend, root_str, contract_hash, offset, count = job
    root = Path(root_str)
    shard = root / "shards" / f"{offset:09d}"
    shard.mkdir(parents=True, exist_ok=True)
    layout = _layout(cfg, count)
    maps = {k: np.lib.format.open_memmap(shard / f"{k}.npy", mode="w+", dtype=dt, shape=shape)
            for k, (shape, dt) in layout.items()}
    try:
        for i in range(count):
            w = generate_world(cfg.account, cfg.seed, cfg.split, cfg.start_index + offset + i,
                               cfg.years, cfg.warmup_years, cfg.plausibility_years, cfg.max_draws, backend)
            for key, value in _arrays(w).items():
                maps[key][i] = value
        for a in maps.values():
            a.flush()
    finally:
        maps.clear()
    files = {k: {"sha256": _hash(shard / f"{k}.npy"), "shape": list(shape), "dtype": dt}
             for k, (shape, dt) in layout.items()}
    rec = {"offset": offset, "count": count, "contract_sha256": contract_hash, "files": files}
    _write_json(shard / "receipt.json", rec)
    return rec


def _check_shard(root: Path, cfg: WorldDatasetConfig, rec: dict, contract_hash: str, *, hashes: bool) -> None:
    offset, count = rec["offset"], rec["count"]
    if type(offset) is not int or type(count) is not int or not 0 <= offset < cfg.worlds or count < 1:
        raise ValueError("invalid shard range")
    if rec["contract_sha256"] != contract_hash or count != min(cfg.shard_worlds, cfg.worlds - offset):
        raise ValueError("shard contract/count mismatch")
    layout = _layout(cfg, count)
    if set(rec["files"]) != set(layout):
        raise ValueError("shard fields mismatch")
    for key, (shape, dt) in layout.items():
        p = root / "shards" / f"{offset:09d}" / f"{key}.npy"
        if not p.resolve().is_relative_to(root.resolve()) or p.is_symlink():
            raise ValueError("dataset file escapes its root")
        entry = rec["files"][key]
        if entry["shape"] != list(shape) or entry["dtype"] != dt:
            raise ValueError(f"{key}: invalid declared layout")
        if hashes and _hash(p) != entry["sha256"]:
            raise ValueError(f"{key}: hash mismatch")
        a = np.load(p, mmap_mode="r", allow_pickle=False)
        if a.shape != shape or a.dtype != np.dtype(dt):
            raise ValueError(f"{key}: invalid array layout")


def generate_dataset(cfg: WorldDatasetConfig, out: Path, *, workers: int = 0, resume: bool = False) -> dict:
    """Generate every world on CPUs, then atomically publish a training-readable manifest."""
    cfg.validate()
    n_workers = cpu_workers(workers)
    out = Path(out).resolve()
    if not resume and out.exists():
        raise FileExistsError(f"dataset output already exists: {out}")
    if resume and not (out / "contract.json").is_file():
        raise ValueError("resume requires an existing dataset contract")
    backend = cfg.backend
    if backend == "auto":
        backend = "native" if native.available() else "numpy"
    if backend == "native":
        native.load()  # compile once before spawning any workers
    contract = {"schema": SCHEMA, "config": asdict(cfg), "resolved_backend": backend,
                "sources": _source_hashes(), "numpy_version": np.__version__,
                "host": {"system": platform.system(), "machine": platform.machine()},
                "native_build": native.build_metadata() if backend == "native" else None,
                "research_only": True, "orders_authorized": False}
    contract_hash = hashlib.sha256(_json_bytes(contract)).hexdigest()
    if resume:
        if (out / "contract.json").read_bytes() != _json_bytes(contract):
            raise ValueError("resume contract differs: config/source/backend/NumPy changed")
        if (out / "manifest.json").is_file():
            return WorldDataset(out).manifest
    else:
        out.mkdir(parents=True, exist_ok=False)
        _write_json(out / "contract.json", contract)
    # A per-dataset lock also prevents simultaneous resume writers on Mac/WSL.
    import fcntl
    with (out / ".generation.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("dataset generation already running") from exc
        receipts, jobs = [], []
        for offset in range(0, cfg.worlds, cfg.shard_worlds):
            count = min(cfg.shard_worlds, cfg.worlds - offset)
            receipt = out / "shards" / f"{offset:09d}" / "receipt.json"
            if resume and receipt.exists():
                rec = json.loads(receipt.read_text())
                if rec["offset"] != offset:
                    raise ValueError("receipt offset mismatch")
                _check_shard(out, cfg, rec, contract_hash, hashes=True)
                receipts.append(rec)
            else:
                jobs.append((cfg, backend, str(out), contract_hash, offset, count))
        remaining = sum(estimated_bytes(WorldDatasetConfig(**{**asdict(cfg), "worlds": j[-1]})) for j in jobs)
        if shutil.disk_usage(out).free < remaining * 1.05 + 1024 * 1024:
            raise OSError("insufficient free space for the remaining world shards")
        if jobs:
            with ProcessPoolExecutor(max_workers=min(n_workers, len(jobs)), mp_context=mp.get_context("spawn"),
                                     initializer=init_cpu_worker) as pool:
                receipts.extend(pool.map(_write_shard, jobs, chunksize=1))
        manifest = {"schema": SCHEMA, "contract_sha256": contract_hash,
                    "shards": sorted(receipts, key=lambda r: r["offset"]),
                    "estimated_array_bytes": estimated_bytes(cfg), "workers": min(n_workers, max(1, len(jobs))),
                    "python_version": platform.python_version(), "status": "complete",
                    "research_only": True, "orders_authorized": False}
        for rec in manifest["shards"]:
            _check_shard(out, cfg, rec, contract_hash, hashes=True)
        _write_json(out / "manifest.json", manifest)
    return manifest


class WorldDataset:
    """Read-only lazy mmap reader. A missing/incomplete/corrupt dataset is never regenerated."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        contract_bytes = (self.root / "contract.json").read_bytes()
        self.contract = json.loads(contract_bytes)
        self.manifest = json.loads((self.root / "manifest.json").read_text())
        self.manifest_sha256 = _hash(self.root / "manifest.json")
        self.cfg = WorldDatasetConfig(**self.contract["config"])
        self.cfg.validate()
        digest = hashlib.sha256(contract_bytes).hexdigest()
        for doc in (self.contract, self.manifest):
            if doc["schema"] != SCHEMA or doc.get("research_only") is not True or doc.get("orders_authorized") is not False:
                raise ValueError("invalid research dataset contract")
        if self.manifest["status"] != "complete" or digest != self.manifest["contract_sha256"]:
            raise ValueError("dataset incomplete or contract hash mismatch")
        expected = list(range(0, self.cfg.worlds, self.cfg.shard_worlds))
        if [r["offset"] for r in self.manifest["shards"]] != expected:
            raise ValueError("dataset coverage mismatch")
        for rec in self.manifest["shards"]:
            _check_shard(self.root, self.cfg, rec, digest, hashes=True)

    def batch(self, start: int, count: int) -> list[WorldArrays]:
        if start < 0 or count < 1 or start + count > self.cfg.worlds:
            raise ValueError("batch outside dataset coverage")
        worlds, maps, previous = [], {}, None
        for row in range(start, start + count):
            offset = (row // self.cfg.shard_worlds) * self.cfg.shard_worlds
            if offset != previous:
                shard = self.root / "shards" / f"{offset:09d}"
                maps = {k: np.load(shard / f"{k}.npy", mmap_mode="r", allow_pickle=False)
                        for k in _layout(self.cfg, min(self.cfg.shard_worlds, self.cfg.worlds - offset))}
                previous = offset
            i = row - offset
            f = WorldFeatures(*(maps[k][i] for k in ("asset", "eligible", "market", "features_sigma",
                                                    "tradable", "reduce_only")), bool(maps["value_enabled"][i]))
            worlds.append(WorldArrays(*(maps[k][i] for k in ("close_adj", "close", "open", "adv", "sigma",
                                                             "cash_return", "spread", "buy_blocked")),
                                      f, float(maps["spread_mult"][i]), float(maps["impact_mult"][i]),
                                      int(maps["params_seed"][i])))
        return worlds


def require_external_dataset_path(path: Path) -> Path:
    root = Path("/mnt/e/qount_data/qount")
    if not root.is_dir() or not root.is_mount() and not Path("/mnt/e").is_mount():
        raise ValueError("the Windows external disk must be mounted at /mnt/e")
    target = Path(path).resolve()
    if not target.is_relative_to(root / "datasets" / "etf_trader") or target == root / "datasets" / "etf_trader":
        raise ValueError("world datasets belong below /mnt/e/qount_data/qount/datasets/etf_trader/")
    return target
