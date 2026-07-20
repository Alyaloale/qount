from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.grid.data import _cached_download
from qount.settings import Settings


HISTORICAL_DERIVATIVES_VERSION = "alpha_agent_historical_derivatives_v0.1"
METRICS_BASE_URL = "https://data.binance.vision/data/futures/um/daily/metrics"
FIVE_MINUTES_MS = 5 * 60_000
EXPECTED_ROWS_PER_DAY = 24 * 60 // 5
FetchBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class HistoricalDerivativesConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    start_date: str = "2024-01-01"
    end_date: str = "2024-01-31"
    cache_dir: str = "state/alpha_agents/binance_historical_metrics"
    max_workers: int = 8
    request_retries: int = 3
    request_timeout_seconds: float = 30.0
    min_coverage_ratio: float = 0.98

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoricalMetricsRow:
    symbol: str
    ts_ms: int
    sum_open_interest: float
    sum_open_interest_value: float
    count_toptrader_long_short_ratio: float
    sum_toptrader_long_short_ratio: float
    count_long_short_ratio: float
    sum_taker_long_short_vol_ratio: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_timestamp(raw: str) -> int:
    value = raw.strip()
    try:
        numeric = int(value)
    except ValueError:
        parsed = dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
        return int(parsed.timestamp() * 1000)
    return numeric // 1000 if numeric >= 1_000_000_000_000_000 else numeric


def parse_historical_metrics_csv(text: str) -> list[HistoricalMetricsRow]:
    rows: list[HistoricalMetricsRow] = []
    for item in csv.DictReader(io.StringIO(text)):
        try:
            rows.append(
                HistoricalMetricsRow(
                    symbol=str(item["symbol"]).upper(),
                    ts_ms=_normalize_timestamp(str(item["create_time"])),
                    sum_open_interest=float(item["sum_open_interest"]),
                    sum_open_interest_value=float(item["sum_open_interest_value"]),
                    count_toptrader_long_short_ratio=float(item["count_toptrader_long_short_ratio"]),
                    sum_toptrader_long_short_ratio=float(item["sum_toptrader_long_short_ratio"]),
                    count_long_short_ratio=float(item["count_long_short_ratio"]),
                    sum_taker_long_short_vol_ratio=float(item["sum_taker_long_short_vol_ratio"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def parse_historical_metrics_zip(blob: bytes) -> list[HistoricalMetricsRow]:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("metrics archive must contain exactly one CSV")
        return parse_historical_metrics_csv(archive.read(names[0]).decode("utf-8"))


def metrics_daily_url(symbol: str, date: dt.date) -> str:
    day = date.isoformat()
    filename = f"{symbol}-metrics-{day}.zip"
    return f"{METRICS_BASE_URL}/{symbol}/{filename}"


def _date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=offset) for offset in range((end - start).days + 1)]


def _default_fetch(url: str, *, timeout_seconds: float, retries: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qount-historical-metrics/0.1"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError):
            if attempt >= retries:
                raise
            time.sleep(0.25 * (2**attempt))
    raise AssertionError("unreachable")


def _parse_checksum(payload: bytes, filename: str) -> str:
    parts = payload.decode("utf-8").strip().split()
    if len(parts) < 2 or parts[-1].lstrip("*") != filename:
        raise ValueError("invalid checksum sidecar filename")
    digest = parts[0].lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("invalid checksum digest")
    return digest


def _archive_diagnostics(rows: list[HistoricalMetricsRow], *, expected_symbol: str) -> dict[str, Any]:
    timestamps = sorted({row.ts_ms for row in rows if row.symbol == expected_symbol})
    gaps = [right - left for left, right in zip(timestamps, timestamps[1:]) if right - left > FIVE_MINUTES_MS]
    return {
        "row_count": len(timestamps),
        "first_ts": timestamps[0] if timestamps else None,
        "last_ts": timestamps[-1] if timestamps else None,
        "gap_count": len(gaps),
        "max_gap_ms": max(gaps) if gaps else 0,
    }


def _load_archive(
    symbol: str,
    date: dt.date,
    *,
    config: HistoricalDerivativesConfig,
    fetch: FetchBytes,
) -> tuple[list[HistoricalMetricsRow], dict[str, Any]]:
    url = metrics_daily_url(symbol, date)
    filename = url.rsplit("/", 1)[-1]
    archive_blob = _cached_download(url, filename, config.cache_dir, fetch)
    checksum_blob = _cached_download(f"{url}.CHECKSUM", f"{filename}.CHECKSUM", config.cache_dir, fetch)
    expected_digest = _parse_checksum(checksum_blob, filename)
    actual_digest = hashlib.sha256(archive_blob).hexdigest()
    if actual_digest != expected_digest:
        raise ValueError("archive checksum mismatch")
    rows = parse_historical_metrics_zip(archive_blob)
    if any(row.symbol != symbol for row in rows):
        raise ValueError("archive contains unexpected symbol")
    diagnostics = {
        "symbol": symbol,
        "date": date.isoformat(),
        "archive_url": url,
        "archive_bytes": len(archive_blob),
        "sha256": actual_digest,
        "checksum_verified": True,
        **_archive_diagnostics(rows, expected_symbol=symbol),
    }
    return rows, diagnostics


def _coverage(rows: list[HistoricalMetricsRow], *, expected_rows: int) -> dict[str, Any]:
    timestamps = sorted({row.ts_ms for row in rows})
    gaps = [right - left for left, right in zip(timestamps, timestamps[1:]) if right - left > FIVE_MINUTES_MS]
    return {
        "row_count": len(timestamps),
        "expected_row_count": expected_rows,
        "coverage_ratio": min(1.0, len(timestamps) / expected_rows) if expected_rows else 0.0,
        "first_ts": timestamps[0] if timestamps else None,
        "last_ts": timestamps[-1] if timestamps else None,
        "gap_count": len(gaps),
        "max_gap_ms": max(gaps) if gaps else 0,
        "segment_count": 1 + len(gaps) if timestamps else 0,
    }


def _segment_ids(rows: list[HistoricalMetricsRow]) -> dict[tuple[str, int], int]:
    result: dict[tuple[str, int], int] = {}
    by_symbol: dict[str, list[HistoricalMetricsRow]] = {}
    for row in rows:
        by_symbol.setdefault(row.symbol, []).append(row)
    for symbol, symbol_rows in by_symbol.items():
        segment_id = 0
        previous_ts: int | None = None
        for row in sorted(symbol_rows, key=lambda item: item.ts_ms):
            if previous_ts is not None and row.ts_ms - previous_ts > FIVE_MINUTES_MS:
                segment_id += 1
            result[(symbol, row.ts_ms)] = segment_id
            previous_ts = row.ts_ms
    return result


def build_historical_derivatives_dataset(
    config: HistoricalDerivativesConfig,
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    if not config.symbols:
        raise ValueError("at least one symbol is required")
    start = dt.date.fromisoformat(config.start_date)
    end = dt.date.fromisoformat(config.end_date)
    if end < start:
        raise ValueError("end_date must not precede start_date")
    if config.max_workers <= 0:
        raise ValueError("max_workers must be positive")
    if not 0 < config.min_coverage_ratio <= 1:
        raise ValueError("min_coverage_ratio must be in (0,1]")

    symbols = tuple(symbol.upper() for symbol in config.symbols)
    dates = _date_range(start, end)
    actual_fetch = fetch or (
        lambda url: _default_fetch(
            url,
            timeout_seconds=config.request_timeout_seconds,
            retries=config.request_retries,
        )
    )
    tasks = [(symbol, date) for symbol in symbols for date in dates]
    rows: list[HistoricalMetricsRow] = []
    archives: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    def load(task: tuple[str, dt.date]):
        symbol, date = task
        try:
            return _load_archive(symbol, date, config=config, fetch=actual_fetch), None
        except Exception as exc:
            return None, {
                "symbol": symbol,
                "date": date.isoformat(),
                "error": type(exc).__name__,
                "message": str(exc)[:200],
            }

    with ThreadPoolExecutor(max_workers=min(config.max_workers, len(tasks))) as pool:
        for result, error in pool.map(load, tasks):
            if error is not None:
                errors.append(error)
                continue
            loaded_rows, diagnostics = result
            rows.extend(loaded_rows)
            archives.append(diagnostics)

    deduped = {(row.symbol, row.ts_ms): row for row in rows}
    rows = [deduped[key] for key in sorted(deduped)]
    by_symbol: dict[str, dict[str, Any]] = {}
    expected_rows = len(dates) * EXPECTED_ROWS_PER_DAY
    for symbol in symbols:
        symbol_rows = [row for row in rows if row.symbol == symbol]
        by_symbol[symbol] = _coverage(symbol_rows, expected_rows=expected_rows)

    blockers: list[str] = []
    if errors:
        blockers.append("archive_fetch_or_parse_errors")
    if any(summary["coverage_ratio"] < config.min_coverage_ratio for summary in by_symbol.values()):
        blockers.append("coverage_below_threshold")
    basis = {
        "config": config.to_dict(),
        "archives": [{key: value for key, value in item.items() if key != "archive_url"} for item in archives],
        "rows": [row.to_dict() for row in rows],
    }
    data_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    segment_ids = _segment_ids(rows)
    open_interest_hist = [
        {
            "symbol": row.symbol,
            "ts_ms": row.ts_ms,
            "segment_id": segment_ids[(row.symbol, row.ts_ms)],
            "sum_open_interest": row.sum_open_interest,
            "sum_open_interest_value": row.sum_open_interest_value,
            "cmc_circulating_supply": None,
        }
        for row in rows
    ]
    taker_long_short = [
        {
            "symbol": row.symbol,
            "ts_ms": row.ts_ms,
            "segment_id": segment_ids[(row.symbol, row.ts_ms)],
            "buy_sell_ratio": row.sum_taker_long_short_vol_ratio,
            "buy_vol": None,
            "sell_vol": None,
            "source_field": "sum_taker_long_short_vol_ratio",
        }
        for row in rows
    ]
    return {
        "schema_version": HISTORICAL_DERIVATIVES_VERSION,
        "meta": {
            "point_in_time": True,
            "as_of_join_required": True,
            "replayable": not blockers,
            "official_source": "binance_usdm_public_metrics_daily",
            "history_limit": "public_archive_availability",
            "checksum_verified": all(item["checksum_verified"] for item in archives) and bool(archives),
            "supported_feature_families": ["oi_delta", "oi_value_delta", "taker_ratio"],
            "unsupported_feature_families": ["taker_imbalance"],
            "data_hash": data_hash,
            "source_url": METRICS_BASE_URL,
        },
        "config": config.to_dict(),
        "window": {
            "start_ms": int(dt.datetime.combine(start, dt.time.min, tzinfo=dt.UTC).timestamp() * 1000),
            "end_ms": int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC).timestamp() * 1000) - 1,
            "start_utc": dt.datetime.combine(start, dt.time.min, tzinfo=dt.UTC).isoformat(),
            "end_utc": dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC).isoformat(),
            "period_ms": FIVE_MINUTES_MS,
        },
        "diagnostics": {
            "verdict": "pass_data_smoke" if not blockers else "block_data",
            "blockers": blockers,
            "symbols": list(symbols),
            "requested_archive_count": len(tasks),
            "loaded_archive_count": len(archives),
            "row_count": len(rows),
            "errors": errors,
            "by_symbol": by_symbol,
            "archives": archives,
            "promotion_note": "Historical metrics coverage is a dataset input, not alpha or paper/live evidence.",
        },
        "open_interest_hist": open_interest_hist,
        "taker_long_short": taker_long_short,
        "current_open_interest": [],
        "historical_metrics": [
            {**row.to_dict(), "segment_id": segment_ids[(row.symbol, row.ts_ms)]}
            for row in rows
        ],
    }


def write_historical_derivatives_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-historical-derivatives",
        path_key="artifact_path",
        default_filename="alpha_agent_historical_derivatives.json",
        explicit_path=explicit_path,
    )
