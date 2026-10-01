"""Calibrated stylized-fact targets from out-of-test history (design §7.3, owner decision 2026-09-30).

A-share daily return autocorrelation: the fixed ``|ρ| < 0.05`` gate is replaced, for the four
domestic equity ETFs, by the real 2005–2014 autocorrelation of their underlying CSI/SZSE
index plus a sampling-error band.  For each (asset, lag) cell:

    target ρ̂, band half-width = z · sqrt(se_real² + se_world²)

``se_real`` is a stationary-bootstrap standard error of the real statistic (keeps GARCH
dependence, which inflates the iid ``1/√T``), and ``se_world`` the same estimator applied to
the generated sample, so a correct generator falls inside with probability ≈ Φ(z)·2−1.
Generated worlds are scored on the *same number of days* as the real series of that asset.
A cell passes when ≥ 80% of worlds fall in its band; the fact passes when every cell passes.

Caveats recorded with the targets: indices are not ETFs (no fund-level limit carry, and
constituent-level limits act differently), and 2005–2014 is the only out-of-test window,
so these are weak targets.  Non-domestic CN assets and the US account keep ``|ρ| < 0.05``.

The 5-year dividend-yield R² target is deliberately *absent* until P0 delivers the Shiller
series; the gate reports ``needs_calibration`` instead of a pass/fail.

Network access lives in :func:`fetch_tencent_index` behind an injectable getter; everything
else is pure.  research_only=true / orders_authorized=false / trial=false.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Callable, Mapping, Sequence

import numpy as np

from .stylized import autocorr

TENCENT_INDEX_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,{start},{end},2000,"
CALIBRATION_START = dt.date(2005, 1, 1)
CALIBRATION_END = dt.date(2014, 12, 31)
LAGS = (1, 2, 3, 4, 5)
BAND_Z = 2.0
BOOTSTRAP_DRAWS = 1000
BOOTSTRAP_BLOCK = 21.0  # mean block length (days) of the stationary bootstrap
TARGETS_VERSION = 1

# CN_SPEC column -> underlying index (Tencent code).  QDII / gold / bond keep the fixed gate.
CN_INDEX_FOR_COLUMN = {
    0: ("510300", "sh000300"),  # CSI 300
    1: ("510500", "sh000905"),  # CSI 500
    2: ("159915", "sz399006"),  # ChiNext
    3: ("510050", "sh000016"),  # SSE 50
}

Getter = Callable[[str], bytes]


class TargetError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Data


def fetch_tencent_index(getter: Getter, code: str, start: dt.date, end: dt.date) -> list[tuple[str, float]]:
    """Daily (date, close) for a Tencent index code, paged by ≤ 2000 rows per request."""
    rows: dict[str, float] = {}
    cursor = start
    while cursor <= end:
        stop = min(end, cursor + dt.timedelta(days=4 * 365))
        url = TENCENT_INDEX_URL.format(code=code, start=cursor.isoformat(), end=stop.isoformat())
        node = (json.loads(getter(url).decode("utf-8")).get("data") or {}).get(code) or {}
        for k in node.get("day") or node.get("qfqday") or []:
            day = str(k[0])
            if start.isoformat() <= day <= end.isoformat():
                rows[day] = float(k[2])  # [date, open, close, high, low, volume]
        cursor = stop + dt.timedelta(days=1)
    out = sorted(rows.items())
    if len(out) < 300:
        raise TargetError(f"{code}: only {len(out)} rows in {start}..{end}")
    return out


def series_hash(series: Mapping[str, Sequence[tuple[str, float]]]) -> str:
    h = hashlib.sha256()
    for code in sorted(series):
        for day, close in series[code]:
            h.update(f"{code},{day},{close:.6f}\n".encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Statistics


def autocorr_lags(r: np.ndarray, lags: Sequence[int] = LAGS) -> np.ndarray:
    return np.array([autocorr(r, lag) for lag in lags])


def stationary_bootstrap_se(
    r: np.ndarray, lags: Sequence[int] = LAGS, *, draws: int = BOOTSTRAP_DRAWS,
    block: float = BOOTSTRAP_BLOCK, seed: int = 0,
) -> np.ndarray:
    """Politis–Romano stationary bootstrap SE of the lag autocorrelations (circular wrap)."""
    r = np.asarray(r, dtype=float)
    T = r.size
    rng = np.random.default_rng(seed)
    stats = np.empty((draws, len(lags)))
    p = 1.0 / block
    for b in range(draws):
        new = rng.random(T) < p
        new[0] = True
        starts = rng.integers(0, T, T)
        # index = start of current block + offset within the block
        block_id = np.cumsum(new) - 1
        first = np.flatnonzero(new)
        offset = np.arange(T) - first[block_id]
        idx = (starts[first][block_id] + offset) % T
        stats[b] = autocorr_lags(r[idx], lags)
    return stats.std(axis=0, ddof=1)


def iid_autocorr_se(T: int) -> float:
    return 1.0 / np.sqrt(max(T, 1))


@dataclass(frozen=True)
class AutocorrTarget:
    column: int
    etf: str
    index: str
    first_day: str
    last_day: str
    n_returns: int
    rho: tuple[float, ...]  # per lag
    se: tuple[float, ...]  # stationary bootstrap SE per lag


@dataclass(frozen=True)
class CalibrationTargets:
    version: int
    account: str
    window: tuple[str, str]
    lags: tuple[int, ...]
    band_z: float
    autocorr: tuple[AutocorrTarget, ...]
    source: str
    source_hash: str
    dy_r2_5y: tuple[float, float] | None = None  # pending Shiller P0 data
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def from_json(text: str) -> "CalibrationTargets":
        d = json.loads(text)
        d["autocorr"] = tuple(AutocorrTarget(**{**a, "rho": tuple(a["rho"]), "se": tuple(a["se"])})
                              for a in d["autocorr"])
        d["window"] = tuple(d["window"])
        d["lags"] = tuple(d["lags"])
        d["notes"] = tuple(d.get("notes", ()))
        if d.get("dy_r2_5y") is not None:
            d["dy_r2_5y"] = tuple(d["dy_r2_5y"])
        if d["version"] != TARGETS_VERSION:
            raise TargetError(f"unsupported targets version {d['version']}")
        return CalibrationTargets(**d)


def build_cn_targets(
    series: Mapping[str, Sequence[tuple[str, float]]], *, draws: int = BOOTSTRAP_DRAWS, seed: int = 20260930,
) -> CalibrationTargets:
    """Targets for the CN domestic equity columns from index closes keyed by Tencent code."""
    out = []
    for col, (etf, code) in sorted(CN_INDEX_FOR_COLUMN.items()):
        rows = series.get(code)
        if not rows:
            raise TargetError(f"missing series {code}")
        close = np.array([c for _, c in rows], dtype=float)
        if np.any(close <= 0):
            raise TargetError(f"{code}: non-positive close")
        r = np.diff(np.log(close))
        out.append(AutocorrTarget(
            column=col, etf=etf, index=code, first_day=rows[0][0], last_day=rows[-1][0], n_returns=int(r.size),
            rho=tuple(float(x) for x in autocorr_lags(r)),
            se=tuple(float(x) for x in stationary_bootstrap_se(r, draws=draws, seed=seed + col)),
        ))
    return CalibrationTargets(
        version=TARGETS_VERSION,
        account="cn",
        window=(CALIBRATION_START.isoformat(), CALIBRATION_END.isoformat()),
        lags=LAGS,
        band_z=BAND_Z,
        autocorr=tuple(out),
        source="Tencent fqkline daily index close (public, no credentials)",
        source_hash=series_hash(series),
        notes=(
            "Index, not ETF: no fund-level limit carry; constituent limits act differently.",
            "2005-2014 is the only out-of-test CN window (§7.3/§9); weak target.",
            "dy_r2_5y pending P0 Shiller data; gate reports needs_calibration.",
        ),
    )


# ---------------------------------------------------------------------------
# Gate


def autocorr_cells(log_r: np.ndarray, targets: CalibrationTargets) -> dict[str, tuple[float, bool]]:
    """Per (asset, lag) cell for one generated world: (ρ_world, in band).

    The world is scored on its first ``n_returns`` days so the sampling error matches.
    """
    r = np.asarray(log_r, dtype=float)
    out: dict[str, tuple[float, bool]] = {}
    for a in targets.autocorr:
        T = min(a.n_returns, r.shape[0])
        x = r[:T, a.column]
        rho = autocorr_lags(x, targets.lags)
        se_w = np.array(a.se) * np.sqrt(a.n_returns / max(T, 1))  # same estimator, same length
        half = targets.band_z * np.sqrt(np.square(a.se) + se_w**2)
        for k, lag in enumerate(targets.lags):
            ok = bool(abs(rho[k] - a.rho[k]) <= half[k])
            out[f"autocorr:{a.etf}:lag{lag}"] = (float(rho[k]), ok)
    return out
