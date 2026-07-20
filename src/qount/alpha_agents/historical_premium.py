from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar
from qount.settings import Settings


HISTORICAL_PREMIUM_VERSION = "alpha_agent_historical_premium_v0.1"
PUBLIC_ARCHIVE_BASE_URL = "https://data.binance.vision/data/futures/um/monthly"
FIVE_MINUTES_MS = 5 * 60_000
EXPECTED_BUCKETS_PER_DAY = 24 * 60 // 5
SUPPORTED_DATASETS = ("premiumIndexKlines", "markPriceKlines", "indexPriceKlines")
FetchBytes = Callable[[str], bytes]
KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
)


@dataclass(frozen=True)
class HistoricalPremiumConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    start_date: str = "2024-01-01"
    end_date: str = "2024-03-31"
    interval: str = "5m"
    datasets: tuple[str, ...] = SUPPORTED_DATASETS
    cache_dir: str = "state/alpha_agents/binance_historical_premium"
    max_workers: int = 4
    request_retries: int = 3
    request_timeout_seconds: float = 60.0
    min_coverage_ratio: float = 0.98

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def archive_url(*, dataset: str, symbol: str, interval: str, period: str) -> str:
    if dataset not in SUPPORTED_DATASETS:
        raise ValueError(f"unsupported premium dataset: {dataset}")
    filename = f"{symbol}-{interval}-{period}.zip"
    return f"{PUBLIC_ARCHIVE_BASE_URL}/{dataset}/{symbol}/{interval}/{filename}"


def _default_fetch(
    url: str,
    *,
    timeout_seconds: float,
    retries: int,
) -> bytes:  # pragma: no cover - network
    request = urllib.request.Request(url, headers={"User-Agent": "qount-historical-premium/0.1"})
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


def parse_premium_kline_csv(text: str) -> list[Bar]:
    rows = csv.reader(io.StringIO(text))
    result: list[Bar] = []
    for line_number, columns in enumerate(rows, start=1):
        if not columns:
            continue
        if line_number == 1 and tuple(columns) == KLINE_COLUMNS:
            continue
        if len(columns) != len(KLINE_COLUMNS):
            raise ValueError(f"unexpected premium kline column count at line {line_number}")
        try:
            ts_ms = int(columns[0])
            close_time = int(columns[6])
            trade_count = int(columns[8])
            numeric = [float(columns[index]) for index in (1, 2, 3, 4, 5, 7, 9, 10)]
        except ValueError as exc:
            raise ValueError(f"invalid premium kline value at line {line_number}") from exc
        if ts_ms >= 1_000_000_000_000_000:
            ts_ms //= 1000
        if close_time >= 1_000_000_000_000_000:
            close_time //= 1000
        if close_time < ts_ms:
            raise ValueError(f"premium kline close precedes open at line {line_number}")
        result.append(
            Bar(
                ts_ms=ts_ms,
                open=numeric[0],
                high=numeric[1],
                low=numeric[2],
                close=numeric[3],
                volume=numeric[4],
                quote_volume=numeric[5],
                trade_count=trade_count,
                taker_buy_base_volume=numeric[6],
                taker_buy_quote_volume=numeric[7],
            )
        )
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _download_archive(
    url: str,
    destination: Path,
    *,
    fetch: FetchBytes | None,
    timeout_seconds: float,
    retries: int,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(f"{destination.name}.part")
    if fetch is None:  # pragma: no cover - network
        request = urllib.request.Request(url, headers={"User-Agent": "qount-historical-premium/0.1"})
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response, part.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
                break
            except urllib.error.HTTPError:
                part.unlink(missing_ok=True)
                raise
            except (OSError, TimeoutError, urllib.error.URLError):
                part.unlink(missing_ok=True)
                if attempt >= retries:
                    raise
                time.sleep(0.25 * (2**attempt))
    else:
        part.write_bytes(fetch(url))
    os.replace(part, destination)


def _periods(start: dt.date, end: dt.date) -> list[str]:
    year, month = start.year, start.month
    result: list[str] = []
    while (year, month) <= (end.year, end.month):
        result.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year += 1
            month = 1
    return result


def _load_archive(
    *,
    dataset: str,
    symbol: str,
    period: str,
    config: HistoricalPremiumConfig,
    start_ms: int,
    end_ms: int,
    fetch: FetchBytes | None,
) -> tuple[list[Bar], dict[str, Any]]:
    url = archive_url(dataset=dataset, symbol=symbol, interval=config.interval, period=period)
    filename = url.rsplit("/", 1)[-1]
    actual_fetch = fetch or (
        lambda target: _default_fetch(
            target,
            timeout_seconds=config.request_timeout_seconds,
            retries=config.request_retries,
        )
    )
    expected_digest = _parse_checksum(actual_fetch(f"{url}.CHECKSUM"), filename)
    archive_path = Path(config.cache_dir).expanduser() / f"{dataset}-{filename}"
    if not archive_path.exists():
        _download_archive(
            url,
            archive_path,
            fetch=fetch,
            timeout_seconds=config.request_timeout_seconds,
            retries=config.request_retries,
        )
    actual_digest = _sha256_file(archive_path)
    if actual_digest != expected_digest:
        raise ValueError(f"checksum mismatch for {dataset}/{symbol}/{period}")
    with zipfile.ZipFile(archive_path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("premium archive must contain exactly one CSV")
        bars = parse_premium_kline_csv(archive.read(members[0]).decode("utf-8"))
    filtered = [bar for bar in bars if start_ms <= bar.ts_ms <= end_ms]
    return filtered, {
        "dataset": dataset,
        "symbol": symbol,
        "period": period,
        "interval": config.interval,
        "archive_filename": filename,
        "archive_size_bytes": archive_path.stat().st_size,
        "checksum_sha256": actual_digest,
        "checksum_verified": True,
        "row_count": len(bars),
        "filtered_row_count": len(filtered),
        "first_ts_ms": filtered[0].ts_ms if filtered else None,
        "last_ts_ms": filtered[-1].ts_ms if filtered else None,
    }


def _segment_rows(rows: list[dict[str, Any]]) -> None:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)
    for symbol_rows in by_symbol.values():
        segment_id = 0
        previous_ts: int | None = None
        previous_complete = False
        for row in sorted(symbol_rows, key=lambda item: int(item["ts_ms"])):
            ts_ms = int(row["ts_ms"])
            complete = bool(row["complete"])
            if previous_ts is not None and (
                ts_ms - previous_ts != FIVE_MINUTES_MS or not previous_complete or not complete
            ):
                segment_id += 1
            row["segment_id"] = segment_id
            previous_ts = ts_ms
            previous_complete = complete


def _coverage(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    expected_count: int,
) -> dict[str, Any]:
    selected = [row for row in rows if row["symbol"] == symbol]
    complete = [row for row in selected if row["complete"]]
    return {
        "expected_bucket_count": expected_count,
        "union_bucket_count": len(selected),
        "complete_bucket_count": len(complete),
        "complete_coverage_ratio": min(1.0, len(complete) / expected_count) if expected_count else 0.0,
        "segment_count": len({row["segment_id"] for row in complete}),
    }


def build_historical_premium_dataset(
    config: HistoricalPremiumConfig,
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    if not config.symbols:
        raise ValueError("at least one symbol is required")
    if config.interval != "5m":
        raise ValueError("historical premium v0 supports 5m only")
    if unknown := sorted(set(config.datasets) - set(SUPPORTED_DATASETS)):
        raise ValueError(f"unsupported datasets: {','.join(unknown)}")
    if set(config.datasets) != set(SUPPORTED_DATASETS):
        raise ValueError("historical premium v0 requires premium, mark, and index datasets")
    if config.max_workers <= 0:
        raise ValueError("max_workers must be positive")
    if config.request_retries < 0:
        raise ValueError("request_retries must be non-negative")
    if not 0 < config.min_coverage_ratio <= 1:
        raise ValueError("min_coverage_ratio must be in (0,1]")
    start = dt.date.fromisoformat(config.start_date)
    end = dt.date.fromisoformat(config.end_date)
    if end < start:
        raise ValueError("end_date must not precede start_date")
    start_ms = int(dt.datetime.combine(start, dt.time.min, tzinfo=dt.UTC).timestamp() * 1000)
    end_ms = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC).timestamp() * 1000) - 1
    symbols = tuple(symbol.upper() for symbol in config.symbols)
    periods = _periods(start, end)
    tasks = [
        (dataset, symbol, period)
        for dataset in config.datasets
        for symbol in symbols
        for period in periods
    ]
    archives: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    series: dict[tuple[str, str], dict[int, Bar]] = {}

    def load(task: tuple[str, str, str]):
        dataset, symbol, period = task
        try:
            return _load_archive(
                dataset=dataset,
                symbol=symbol,
                period=period,
                config=config,
                start_ms=start_ms,
                end_ms=end_ms,
                fetch=fetch,
            ), None
        except Exception as exc:
            return None, {
                "dataset": dataset,
                "symbol": symbol,
                "period": period,
                "error": type(exc).__name__,
                "message": str(exc)[:240],
            }

    with ThreadPoolExecutor(max_workers=min(config.max_workers, len(tasks))) as pool:
        for result, error in pool.map(load, tasks):
            if error is not None:
                errors.append(error)
                continue
            bars, audit = result
            archives.append(audit)
            key = (str(audit["dataset"]), str(audit["symbol"]))
            target = series.setdefault(key, {})
            for bar in bars:
                if bar.ts_ms in target:
                    raise ValueError(f"duplicate premium kline at {key}/{bar.ts_ms}")
                target[bar.ts_ms] = bar

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        timestamps: set[int] = set()
        for dataset in config.datasets:
            timestamps |= set(series.get((dataset, symbol), {}))
        for ts_ms in sorted(timestamps):
            premium = series.get(("premiumIndexKlines", symbol), {}).get(ts_ms)
            mark = series.get(("markPriceKlines", symbol), {}).get(ts_ms)
            index = series.get(("indexPriceKlines", symbol), {}).get(ts_ms)
            complete = premium is not None and mark is not None and index is not None and index.close > 0
            basis = (mark.close / index.close - 1.0) if complete else None
            rows.append(
                {
                    "symbol": symbol,
                    "ts_ms": ts_ms,
                    "premium_index_close": premium.close if premium is not None else None,
                    "mark_price_close": mark.close if mark is not None else None,
                    "index_price_close": index.close if index is not None else None,
                    "mark_index_basis": basis,
                    "premium_minus_mark_index_basis": (
                        premium.close - basis if premium is not None and basis is not None else None
                    ),
                    "complete": complete,
                }
            )
    _segment_rows(rows)
    expected_count = ((end - start).days + 1) * EXPECTED_BUCKETS_PER_DAY
    by_symbol = {
        symbol: _coverage(rows, symbol=symbol, expected_count=expected_count)
        for symbol in symbols
    }
    blockers: list[str] = []
    if errors:
        blockers.append("archive_fetch_or_parse_errors")
    if any(
        summary["complete_coverage_ratio"] < config.min_coverage_ratio
        for summary in by_symbol.values()
    ):
        blockers.append("coverage_below_threshold")
    basis = {
        "config": config.to_dict(),
        "archives": sorted(archives, key=lambda item: (item["dataset"], item["symbol"], item["period"])),
        "rows": rows,
    }
    data_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema_version": HISTORICAL_PREMIUM_VERSION,
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "point_in_time": True,
            "checksum_verified": bool(archives) and all(row["checksum_verified"] for row in archives),
            "replayable": not blockers,
            "source": "binance_usdm_public_archive",
            "data_hash": data_hash,
            "aggregation_period_ms": FIVE_MINUTES_MS,
        },
        "config": config.to_dict(),
        "window": {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "period_ms": FIVE_MINUTES_MS,
        },
        "schema_audit": {
            "kline_columns": list(KLINE_COLUMNS),
            "strict_column_count": True,
            "malformed_rows_allowed": False,
        },
        "diagnostics": {
            "verdict": "pass_data_smoke" if not blockers else "block_data",
            "blockers": blockers,
            "requested_archive_count": len(tasks),
            "loaded_archive_count": len(archives),
            "archive_bytes": sum(int(row["archive_size_bytes"]) for row in archives),
            "error_count": len(errors),
            "errors": errors,
            "row_count": len(rows),
            "complete_row_count": sum(bool(row["complete"]) for row in rows),
            "by_symbol": by_symbol,
            "archives": sorted(archives, key=lambda item: (item["dataset"], item["symbol"], item["period"])),
            "promotion_note": "Archive integrity is data evidence, not alpha or paper/live evidence.",
        },
        "five_minute_features": rows,
    }


def write_historical_premium_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-historical-premium",
        path_key="artifact_path",
        default_filename="alpha_agent_historical_premium.json",
        explicit_path=explicit_path,
    )
