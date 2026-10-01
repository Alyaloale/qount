"""ctypes loader for the native structural-generator kernel (``structural_kernel.cpp``).

The shared library is compiled on first use into a per-host cache keyed by the source hash
and compiler flags (``$QOUNT_NATIVE_CACHE`` or ``~/.cache/qount/native``), so the Mac and WSL
each build their own.  No ``-ffast-math`` and ``-ffp-contract=off``: the kernel must agree
with the numpy reference loop to rounding (tests compare them).  ``available()`` is False
when no C++ compiler exists; ``simulate_world(backend="auto")`` then falls back to numpy.

Research-only build artifact; nothing here is installed, deployed or imported by
production packages.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

SOURCE = Path(__file__).with_name("structural_kernel.cpp")

ECON_FIELDS = (
    "R_STAR", "PI_STAR", "I_FLOOR", "PHI_PI", "PHI_X", "A_RATE", "A_GAP", "A_PI", "A_TP", "A_ERP",
    "GAP_SD", "PI_SD", "S_GAP", "S_PI", "S_TP", "TP_MEAN", "ERP_BAR", "ERP_GAP", "ERP_PI", "ERP_CRISIS",
    "DUR_EQ", "DY_BAR", "LOG_INV_DY", "DIV_LOAD", "W10", "EQ_VAR_D", "G_A", "G_G", "G_B", "PERSIST", "H_CAP", "THETA",
)
ASSET_FIELDS = ("BETA", "IDIO_D", "DUR", "CVX", "WM", "MAT_SCALE", "LEV", "STALE")
SCALAR_FIELDS = (
    "F_NOW", "A_MOM", "KAPPA", "PSI", "Q_CF", "A_OBS", "S_OBS", "JUMP_RATE_D", "JUMP_MEAN", "JUMP_SD",
    "REBOUND_SHARE", "FTQ", "JUMP_COMP", "AU_VAR", "GOLD_RR", "GOLD_RB", "GOLD_JS", "CM_VAR", "CM_ROLL",
    "CM_IB", "CM_GB", "A_PR", "QUOTA_PREM", "PREM_SIGMA", "QUOTA_DAYS", "QUOTA_RATE", "DROUGHT_DAYS",
    "DROUGHT_RATE", "CONTAGION", "PAYOUT", "FX_SCALE", "FX_VAR", "REBOUND_DAYS", "STALE_SHARE", "STALE_DECAY",
)
ABI = len(ECON_FIELDS) * 10000 + len(ASSET_FIELDS) * 100 + len(SCALAR_FIELDS)
MAX_ASSETS = 64

_lib: ctypes.CDLL | None = None
_error: str | None = None


class NativeUnavailable(RuntimeError):
    pass


def _compiler() -> list[str] | None:
    """``$CXX`` (may carry arguments), else c++/g++/clang++, else the venv's ``ziglang``."""
    env = shlex.split(os.environ.get("CXX", ""))
    if env and shutil.which(env[0]):
        return env
    for name in ("c++", "g++", "clang++"):
        if shutil.which(name):
            return [name]
    # No system compiler (e.g. WSL without build-essential): the pinned ``ziglang`` wheel in
    # the research venv ships a clang-based C++ toolchain and needs no root.
    import importlib.util
    import sys

    if importlib.util.find_spec("ziglang") is not None:
        return [sys.executable, "-m", "ziglang", "c++"]
    return None


def _flags() -> list[str]:
    arch = ["-mcpu=native"] if platform.machine() in ("arm64", "aarch64") else ["-march=native"]
    return ["-O3", *arch, "-ffp-contract=off", "-fno-fast-math", "-std=c++17", "-shared", "-fPIC"]


def _cache_dir() -> Path:
    root = os.environ.get("QOUNT_NATIVE_CACHE")
    return Path(root) if root else Path.home() / ".cache" / "qount" / "native"


def build(force: bool = False) -> Path:
    cxx = _compiler()
    if cxx is None:
        raise NativeUnavailable("no C++ compiler on PATH")
    flags = _flags()
    key = hashlib.sha256(SOURCE.read_bytes() + " ".join([*cxx, *flags, platform.platform()]).encode()).hexdigest()[:16]
    ext = ".dylib" if platform.system() == "Darwin" else ".so"
    out = _cache_dir() / f"structural_kernel-{key}{ext}"
    if out.exists() and not force:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=out.parent, suffix=ext, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        res = subprocess.run([*cxx, *flags, str(SOURCE), "-o", str(tmp_path)], capture_output=True, text=True)
        if res.returncode != 0:
            raise NativeUnavailable(f"compile failed: {res.stderr.strip()[:2000]}")
        os.replace(tmp_path, out)  # atomic: concurrent workers may race to build
    finally:
        tmp_path.unlink(missing_ok=True)
    return out


def load() -> ctypes.CDLL:
    global _lib, _error
    if _lib is not None:
        return _lib
    if _error is not None:
        raise NativeUnavailable(_error)
    try:
        lib = ctypes.CDLL(str(build()))
    except (NativeUnavailable, OSError) as exc:
        _error = str(exc)
        raise NativeUnavailable(_error) from exc
    lib.qount_kernel_abi.restype = ctypes.c_int
    if lib.qount_kernel_abi() != ABI:
        _error = f"kernel ABI {lib.qount_kernel_abi()} != loader {ABI}"
        raise NativeUnavailable(_error)
    for fn in ("qount_structural_loop", "qount_price_paths", "qount_ewma_sigma", "qount_ar1"):
        getattr(lib, fn).restype = ctypes.c_int
    _lib = lib
    return lib


def available() -> bool:
    try:
        load()
        return True
    except NativeUnavailable:
        return False


def _p(a: np.ndarray):
    if not a.flags.c_contiguous:
        raise ValueError("arrays passed to the kernel must be C-contiguous")
    return a.ctypes.data_as(ctypes.c_void_p)


def _f64(a) -> np.ndarray:
    return np.ascontiguousarray(a, dtype=np.float64)


def _check(code: int, name: str) -> None:
    if code != 0:
        raise RuntimeError(f"{name} returned {code}")


def structural_loop(T: int, n: int, econ: dict, asset: dict, aint: np.ndarray, scal: dict, rtab: np.ndarray,
                    pcum: np.ndarray, init: np.ndarray, draws: dict) -> dict:
    if n > MAX_ASSETS:
        raise ValueError(f"at most {MAX_ASSETS} assets")
    lib = load()
    ec = _f64(np.stack([np.broadcast_to(econ[k], (2,)) for k in ECON_FIELDS]))
    asr = _f64(np.stack([np.broadcast_to(asset[k], (n,)) for k in ASSET_FIELDS]))
    sc = _f64([scal[k] for k in SCALAR_FIELDS])
    ai = np.ascontiguousarray(aint, dtype=np.int32)
    rt, pc, ini = _f64(rtab), _f64(pcum), _f64(init)
    d = {k: _f64(v) for k, v in draws.items()}
    out = {
        "logret": np.zeros((T, n)), "dist": np.zeros((T, n)), "pe": np.empty((T, n)), "pe_obs": np.empty((T, n)),
        "bond_y": np.empty((T, n)), "mu": np.empty((T, n)), "var": np.empty((T, n)),
        "quota": np.zeros(T, dtype=np.uint8), "drought": np.zeros((T, n), dtype=np.uint8),
        "fx_ret": np.empty(T), "reg": np.empty((T, 2), dtype=np.int32), "econ": np.empty((5, T, 2)),
    }
    order = ("u_reg", "u_cont", "zg", "zi", "z_tp", "z_eq", "z_id", "z_fx", "z_au", "z_cm", "z_pr", "z_obs",
             "u_jump", "z_jump", "u_quota", "u_drought")
    code = lib.qount_structural_loop(
        ctypes.c_int(T), ctypes.c_int(n), _p(ec), _p(asr), _p(ai), _p(sc), _p(rt), _p(pc), _p(ini),
        *[_p(d[k]) for k in order],
        *[_p(out[k]) for k in ("logret", "dist", "pe", "pe_obs", "bond_y", "mu", "var", "quota", "drought",
                               "fx_ret", "reg", "econ")],
    )
    _check(code, "qount_structural_loop")
    return out


def price_paths(logret: np.ndarray, dist: np.ndarray, close0: np.ndarray, tick: float, lim: float | None):
    lib = load()
    T, n = logret.shape
    close = np.zeros((T, n))
    close[0] = close0
    close_adj = close.copy()
    lr, ds = _f64(logret), _f64(dist)
    code = lib.qount_price_paths(ctypes.c_int(T), ctypes.c_int(n), _p(lr), _p(ds), ctypes.c_double(tick),
                                 ctypes.c_double(0.0 if lim is None else lim), ctypes.c_int(lim is not None),
                                 _p(close), _p(close_adj))
    _check(code, "qount_price_paths")
    return close, close_adj


def ewma_sigma(r: np.ndarray, sigma0: np.ndarray, lam: float) -> np.ndarray:
    lib = load()
    r = _f64(r)
    out = np.empty_like(r)
    s0 = _f64(np.broadcast_to(sigma0, (r.shape[1],)))
    _check(lib.qount_ewma_sigma(ctypes.c_int(r.shape[0]), ctypes.c_int(r.shape[1]), _p(r), _p(s0),
                                ctypes.c_double(lam), _p(out)), "qount_ewma_sigma")
    return out


def ar1(z: np.ndarray, a: float, s: float) -> np.ndarray:
    lib = load()
    z = _f64(z)
    out = np.empty_like(z)
    _check(lib.qount_ar1(ctypes.c_int(z.shape[0]), ctypes.c_int(z.shape[1]), _p(z), ctypes.c_double(a),
                         ctypes.c_double(s), _p(out)), "qount_ar1")
    return out
