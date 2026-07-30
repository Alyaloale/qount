"""Shared Binance public market-data parsing and download helpers.

S1 needs multi-year BTC OHLCV across regimes (2021 bull / 2022 bear / 2023-24 chop /
2025-26 recent). We use the public dump at ``data.binance.vision`` rather than the ccxt
REST API: it needs no key or ccxt. Binance can revise archived files after discovered
issues, so reproducibility comes from retaining the exact ZIP plus its verified official
``.CHECKSUM`` and project manifest, not from assuming the remote archive is immutable.

Pure parsing (``parse_kline_csv``) is split from IO (``download_month`` / ``load_klines``)
so the parser is unit-tested offline and the IO layer takes an injectable fetcher (tests
never touch the network). Cached zips live under ``state/grid_b/`` (line B caches locally
on Mac; the cross-host sync deliberately does not carry ``state/``).
"""

from __future__ import annotations

import calendar as _cal
import datetime as _dt
import hashlib
import io
import os
import re
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable
from typing import Iterable
from typing import Iterator

DEFAULT_CACHE_DIR = os.path.join("state", "research", "market_data")
_BASE = "https://data.binance.vision/data"
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _normalize_ts(ts: int) -> int:
    """Binance switched kline/funding times to microseconds in 2025; older dumps are ms.

    A ms epoch for this era is ~1.6e12; microseconds ~1.6e15. Normalize to ms.
    """

    return ts // 1000 if ts >= 1_000_000_000_000_000 else ts


def checksum_url(archive_url: str) -> str:
    """Return Binance Public Data's colocated SHA-256 sidecar URL."""

    if not archive_url.endswith(".zip"):
        raise ValueError("Binance archive URL must end with .zip")
    return f"{archive_url}.CHECKSUM"


def parse_checksum_sidecar(sidecar: bytes, expected_filename: str) -> str:
    """Parse ``<sha256>  <filename>`` and bind it to the requested archive."""

    if len(sidecar) > 4096:
        raise ValueError("Binance checksum sidecar is unexpectedly large")
    try:
        text = sidecar.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("Binance checksum sidecar is not ASCII") from exc
    parts = text.split()
    if len(parts) < 2 or not _SHA256_PATTERN.fullmatch(parts[0]):
        raise ValueError("Binance checksum sidecar format is invalid")
    sidecar_filename = parts[-1].lstrip("*")
    if os.path.basename(sidecar_filename) != expected_filename:
        raise ValueError("Binance checksum filename does not match archive URL")
    return parts[0].lower()


def validate_archive_checksum(
    archive: bytes,
    sidecar: bytes,
    *,
    expected_filename: str,
) -> str:
    """Validate archive bytes against the official sidecar and return the hash."""

    expected = parse_checksum_sidecar(sidecar, expected_filename)
    actual = hashlib.sha256(archive).hexdigest()
    if actual != expected:
        raise ValueError("Binance archive SHA-256 mismatch")
    return actual


def verified_archive_fetch(
    archive_url: str,
    *,
    fetch: Callable[[str], bytes],
) -> bytes:
    """Fetch one archive and sidecar, rejecting unverified or renamed bytes.

    Pass this as the injectable ``fetch`` used by ``load_klines``/``load_funding``
    for new strict ingestion. Existing caches are not silently relabeled as verified.
    """

    archive = fetch(archive_url)
    sidecar = fetch(checksum_url(archive_url))
    filename = os.path.basename(urllib.parse.urlparse(archive_url).path)
    validate_archive_checksum(archive, sidecar, expected_filename=filename)
    return archive


def _market_path(market: str) -> str:
    """URL segment for a market: spot dumps vs USD-margined (UM) perpetual futures."""

    if market == "spot":
        return "spot"
    if market == "um":
        return "futures/um"
    raise ValueError(f"unknown market {market!r} (expected 'spot' or 'um')")


@dataclass(frozen=True)
class Bar:
    """One Binance kline bar. ``ts_ms`` is the open time in epoch milliseconds (UTC)."""

    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None
    trade_count: int | None = None
    taker_buy_base_volume: float | None = None
    taker_buy_quote_volume: float | None = None

    @property
    def date(self) -> str:
        return _dt.datetime.fromtimestamp(self.ts_ms / 1000, _dt.UTC).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class Funding:
    """One UM funding settlement: ``rate`` paid at ``ts_ms`` (positive = longs pay shorts)."""

    ts_ms: int
    rate: float


# --------------------------------------------------------------------------------------
# Pure parsing (no IO)
# --------------------------------------------------------------------------------------


def _optional_float(cols: list[str], index: int) -> float | None:
    try:
        return float(cols[index])
    except (IndexError, TypeError, ValueError):
        return None


def _optional_int(cols: list[str], index: int) -> int | None:
    try:
        return int(cols[index])
    except (IndexError, TypeError, ValueError):
        return None


def parse_kline_csv(text: str) -> list[Bar]:
    """Parse a Binance-vision kline CSV into bars.

    Column layout: open_time_ms, open, high, low, close, volume, close_time, quote_volume,
    trade_count, taker_buy_base_volume, taker_buy_quote_volume, ignore. Older
    dumps have no header; newer ones (2025+) sometimes prepend a header row -- a non-numeric
    first field is treated as a header and skipped.
    """

    bars: list[Bar] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        cols = line.split(",")
        if len(cols) < 6:
            continue
        try:
            ts = int(cols[0])
        except ValueError:
            continue  # header row
        # Binance switched kline open_time to microseconds in 2025; older dumps are ms.
        # A ms epoch for this era is ~1.6e12; microseconds ~1.6e15. Normalize to ms.
        if ts >= 1_000_000_000_000_000:  # >= 1e15 -> microseconds
            ts //= 1000
        try:
            bars.append(
                Bar(
                    ts_ms=ts,
                    open=float(cols[1]),
                    high=float(cols[2]),
                    low=float(cols[3]),
                    close=float(cols[4]),
                    volume=float(cols[5]),
                    quote_volume=_optional_float(cols, 7),
                    trade_count=_optional_int(cols, 8),
                    taker_buy_base_volume=_optional_float(cols, 9),
                    taker_buy_quote_volume=_optional_float(cols, 10),
                )
            )
        except (ValueError, IndexError):
            continue
    return bars


def parse_zip_bytes(blob: bytes) -> list[Bar]:
    """Parse the single CSV inside a Binance-vision monthly kline zip."""

    return _parse_zip(blob, parse_kline_csv)


def parse_funding_csv(text: str) -> list[Funding]:
    """Parse a Binance-vision UM fundingRate CSV.

    Column layout: ``calc_time_ms, funding_interval_hours, last_funding_rate`` (newer) or
    ``calc_time_ms, last_funding_rate`` (older). The timestamp is the first column, the
    rate is always the *last* column; a non-numeric first field is a header and skipped.
    """

    rows: list[Funding] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        cols = line.split(",")
        if len(cols) < 2:
            continue
        try:
            ts = int(cols[0])
        except ValueError:
            continue  # header row
        try:
            rate = float(cols[-1])
        except ValueError:
            continue
        rows.append(Funding(ts_ms=_normalize_ts(ts), rate=rate))
    return rows


def parse_funding_zip_bytes(blob: bytes) -> list[Funding]:
    """Parse the single CSV inside a Binance-vision monthly fundingRate zip."""

    return _parse_zip(blob, parse_funding_csv)


def _parse_zip(blob: bytes, parser):
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not names:
            raise ValueError("zip contains no CSV")
        return parser(zf.read(names[0]).decode("utf-8"))


# --------------------------------------------------------------------------------------
# IO: download + cache + load (injectable fetcher; tests never hit the network)
# --------------------------------------------------------------------------------------


def month_url(symbol: str, interval: str, year: int, month: int, *,
              market: str = "spot") -> str:
    name = f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
    return f"{_BASE}/{_market_path(market)}/monthly/klines/{symbol}/{interval}/{name}"


def day_url(symbol: str, interval: str, year: int, month: int, day: int, *,
            market: str = "spot") -> str:
    name = f"{symbol}-{interval}-{year:04d}-{month:02d}-{day:02d}.zip"
    return f"{_BASE}/{_market_path(market)}/daily/klines/{symbol}/{interval}/{name}"


def funding_url(symbol: str, year: int, month: int) -> str:
    name = f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
    return f"{_BASE}/futures/um/monthly/fundingRate/{symbol}/{name}"


def _default_fetch(url: str) -> bytes:  # pragma: no cover - network
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def _cached_download(url: str, cache_name: str, cache_dir: str,
                     fetch: Callable[[str], bytes] | None) -> bytes:
    """Return ``url``'s bytes, caching under ``cache_dir/cache_name`` (reuses if present)."""

    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, cache_name)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "rb") as fh:
            return fh.read()
    blob = (fetch or _default_fetch)(url)
    with open(path, "wb") as fh:
        fh.write(blob)
    return blob


def download_month(
    symbol: str,
    interval: str,
    year: int,
    month: int,
    *,
    market: str = "spot",
    cache_dir: str = DEFAULT_CACHE_DIR,
    fetch: Callable[[str], bytes] | None = None,
) -> bytes:
    """Return the monthly kline zip bytes, caching to ``cache_dir`` (reuses if present).

    ``market`` 'um' (perp) is namespaced in the cache filename so it never collides with
    the same-named spot dump.
    """

    prefix = "" if market == "spot" else f"{market}-"
    name = f"{prefix}{symbol}-{interval}-{year:04d}-{month:02d}.zip"
    return _cached_download(
        month_url(symbol, interval, year, month, market=market),
        name, cache_dir, fetch,
    )


def download_day(
    symbol: str,
    interval: str,
    year: int,
    month: int,
    day: int,
    *,
    market: str = "spot",
    cache_dir: str = DEFAULT_CACHE_DIR,
    fetch: Callable[[str], bytes] | None = None,
) -> bytes:
    """Return the per-day kline zip bytes, caching to ``cache_dir`` (reuses if present).

    Used to fill the in-progress current month, whose monthly dump only publishes after the
    month ends. Retain and hash the exact bytes because Binance may revise archived files.
    """

    prefix = "" if market == "spot" else f"{market}-"
    name = f"{prefix}{symbol}-{interval}-{year:04d}-{month:02d}-{day:02d}.zip"
    return _cached_download(
        day_url(symbol, interval, year, month, day, market=market),
        name, cache_dir, fetch,
    )


def download_funding_month(
    symbol: str,
    year: int,
    month: int,
    *,
    cache_dir: str = DEFAULT_CACHE_DIR,
    fetch: Callable[[str], bytes] | None = None,
) -> bytes:
    """Return the monthly UM fundingRate zip bytes, caching to ``cache_dir``."""

    name = f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
    return _cached_download(funding_url(symbol, year, month), name, cache_dir, fetch)


def _download_month_daily(
    symbol: str,
    interval: str,
    year: int,
    month: int,
    *,
    market: str,
    cache_dir: str,
    fetch: Callable[[str], bytes] | None,
) -> list[Bar]:
    """Assemble a month's bars from per-day dumps (fallback when the monthly zip is absent).

    Iterates only days up to today (UTC) -- future days, and today before its dump publishes,
    simply 404 and are skipped. Each day is cached independently. Returns ``[]`` when no day in
    the month is available (e.g. an entirely future month), so the caller can fall back to its
    normal missing-month handling.
    """

    today = _dt.datetime.now(_dt.UTC).date()
    if (year, month) > (today.year, today.month):
        return []
    last_day = today.day if (year, month) == (today.year, today.month) else _cal.monthrange(year, month)[1]
    bars: list[Bar] = []
    for day in range(1, last_day + 1):
        try:
            blob = download_day(symbol, interval, year, month, day, market=market,
                                cache_dir=cache_dir, fetch=fetch)
        except Exception:
            continue  # this day's dump not published yet (or genuinely missing)
        bars.extend(parse_zip_bytes(blob))
    return bars


def _iter_months(start: tuple[int, int], end: tuple[int, int]) -> Iterator[tuple[int, int]]:
    y, m = start
    ey, em = end
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def load_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    *,
    start: tuple[int, int],
    end: tuple[int, int],
    market: str = "spot",
    cache_dir: str = DEFAULT_CACHE_DIR,
    fetch: Callable[[str], bytes] | None = None,
    skip_missing: bool = False,
) -> list[Bar]:
    """Load an ascending, de-duplicated bar series for ``[start, end]`` inclusive months.

    ``start`` / ``end`` are ``(year, month)``. ``market`` selects spot or 'um' perp dumps.
    When a month's monthly dump is absent -- typically the in-progress current month, whose
    monthly zip publishes only after the month ends -- this falls back to per-day dumps so a
    forward run advances daily instead of waiting for month-end. ``skip_missing=True`` then
    additionally tolerates a month with no data at all (not even daily) instead of raising.
    """

    seen: dict[int, Bar] = {}
    for year, month in _iter_months(start, end):
        try:
            blob = download_month(symbol, interval, year, month, market=market,
                                  cache_dir=cache_dir, fetch=fetch)
        except Exception:
            day_bars = _download_month_daily(symbol, interval, year, month, market=market,
                                             cache_dir=cache_dir, fetch=fetch)
            if not day_bars:
                if skip_missing:
                    continue
                raise
            for bar in day_bars:
                seen[bar.ts_ms] = bar
            continue
        for bar in parse_zip_bytes(blob):
            seen[bar.ts_ms] = bar  # last write wins; dedup on open time
    return [seen[ts] for ts in sorted(seen)]


def load_funding(
    symbol: str,
    *,
    start: tuple[int, int],
    end: tuple[int, int],
    cache_dir: str = DEFAULT_CACHE_DIR,
    fetch: Callable[[str], bytes] | None = None,
    skip_missing: bool = False,
) -> list[Funding]:
    """Load an ascending, de-duplicated UM funding series for ``[start, end]`` months."""

    seen: dict[int, Funding] = {}
    for year, month in _iter_months(start, end):
        try:
            blob = download_funding_month(symbol, year, month,
                                          cache_dir=cache_dir, fetch=fetch)
        except Exception:
            if skip_missing:
                continue
            raise
        for row in parse_funding_zip_bytes(blob):
            seen[row.ts_ms] = row
    return [seen[ts] for ts in sorted(seen)]


def closes(bars: Iterable[Bar]) -> list[float]:
    return [b.close for b in bars]
