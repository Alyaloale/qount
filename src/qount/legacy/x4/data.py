"""X4 market data: klines (reused) + UM open-interest metrics dump (线 D). Plan §2 S4/§5.

Price/volume klines reuse ``grid.data`` directly (``load_klines`` for spot/um) -- no need to
re-implement. The genuinely new piece is the **open-interest** series for S4-MOM, from Binance's
public metrics dump:

    data/futures/um/monthly/metrics/{SYMBOL}/{SYMBOL}-metrics-{YYYY}-{MM}.zip

whose CSV columns are ``create_time, symbol, sum_open_interest, sum_open_interest_value, ...``.
``create_time`` is a UTC ``YYYY-MM-DD HH:MM:SS`` string (older dumps) or an epoch (ms/µs). Pure
parsing (:func:`parse_metrics_csv`) is split from IO (:func:`load_open_interest`, reusing
``grid.data``'s cached injectable fetcher), and :func:`align_oi_to_bars` maps OI onto a bar
timeline by last-known forward fill (no look-ahead). Caches live under ``state/x4/`` so neither
line B's ``state/grid_b/`` nor line C's ``state/rv_c/`` glob is ever touched.
"""

from __future__ import annotations

import datetime as _dt
import io
import zipfile
from dataclasses import dataclass
from typing import Callable

from qount.research_data.market_data import Bar
from qount.research_data.market_data import _cached_download

DEFAULT_CACHE_DIR = "state/x4/metrics"
_BASE = "https://data.binance.vision/data"


@dataclass(frozen=True)
class OpenInterest:
    """One open-interest sample: ``oi`` base units and ``oi_value`` quote, at ``ts_ms`` (UTC)."""

    ts_ms: int
    oi: float
    oi_value: float


def _normalize_ts(ts: int) -> int:
    """Normalize a possibly-microsecond epoch to milliseconds (mirrors ``grid.data``)."""

    return ts // 1000 if ts >= 1_000_000_000_000_000 else ts


def _parse_create_time(field: str) -> int:
    """Parse a metrics ``create_time`` (epoch number or ``YYYY-MM-DD HH:MM:SS`` UTC) to ms."""

    try:
        return _normalize_ts(int(field))
    except ValueError:
        dt = _dt.datetime.strptime(field, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt.UTC)
        return int(dt.timestamp() * 1000)


def parse_metrics_csv(text: str) -> list[OpenInterest]:
    """Parse a Binance-vision UM metrics CSV into open-interest samples.

    Column layout: ``create_time, symbol, sum_open_interest, sum_open_interest_value, ...``. The
    header row (non-parseable ``create_time``) and any malformed row are skipped.
    """

    rows: list[OpenInterest] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        cols = line.split(",")
        if len(cols) < 4:
            continue
        try:
            ts = _parse_create_time(cols[0])
            oi = float(cols[2])
            oi_value = float(cols[3])
        except (ValueError, IndexError):
            continue  # header or malformed row
        rows.append(OpenInterest(ts_ms=ts, oi=oi, oi_value=oi_value))
    return rows


def parse_metrics_zip_bytes(blob: bytes) -> list[OpenInterest]:
    """Parse the single CSV inside a Binance-vision monthly metrics zip."""

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            raise ValueError("zip contains no CSV")
        return parse_metrics_csv(zf.read(names[0]).decode("utf-8"))


def metrics_month_url(symbol: str, year: int, month: int) -> str:
    name = f"{symbol}-metrics-{year:04d}-{month:02d}.zip"
    return f"{_BASE}/futures/um/monthly/metrics/{symbol}/{name}"


def _iter_months(start: tuple[int, int], end: tuple[int, int]):
    y, m = start
    ey, em = end
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def load_open_interest(
    symbol: str,
    *,
    start: tuple[int, int],
    end: tuple[int, int],
    cache_dir: str = DEFAULT_CACHE_DIR,
    fetch: Callable[[str], bytes] | None = None,
    skip_missing: bool = True,
) -> list[OpenInterest]:
    """Load an ascending, de-duplicated UM open-interest series for ``[start, end]`` months.

    The metrics dump only began partway through 2021 for some symbols, so ``skip_missing``
    defaults ``True`` (a missing month is tolerated rather than raising).
    """

    seen: dict[int, OpenInterest] = {}
    for year, month in _iter_months(start, end):
        name = f"{symbol}-metrics-{year:04d}-{month:02d}.zip"
        try:
            blob = _cached_download(metrics_month_url(symbol, year, month), name, cache_dir, fetch)
        except Exception:
            if skip_missing:
                continue
            raise
        for row in parse_metrics_zip_bytes(blob):
            seen[row.ts_ms] = row
    return [seen[ts] for ts in sorted(seen)]


def align_oi_to_bars(oi: list[OpenInterest], bars: list[Bar]) -> list[float | None]:
    """Map an OI series onto ``bars`` by last-known forward fill (no look-ahead).

    For each bar, returns the most recent ``oi`` sample whose ``ts_ms <= bar.ts_ms``; ``None`` for
    bars before the first OI sample. Both inputs must be ascending by ``ts_ms``.
    """

    out: list[float | None] = []
    j = 0
    last: float | None = None
    for bar in bars:
        while j < len(oi) and oi[j].ts_ms <= bar.ts_ms:
            last = oi[j].oi
            j += 1
        out.append(last)
    return out
