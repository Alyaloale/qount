from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
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
from typing import Iterator

from qount.artifacts import write_research_json_artifact
from qount.settings import Settings


HISTORICAL_DEPTH_VERSION = "alpha_agent_historical_depth_v0.1"
PUBLIC_ARCHIVE_BASE_URL = "https://data.binance.vision/data/futures/um/daily/bookDepth"
FIVE_MINUTES_MS = 5 * 60_000
EXPECTED_BUCKETS_PER_DAY = 24 * 60 // 5
EXPECTED_PERCENTAGES = (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5)
DEPTH_COLUMNS = ("timestamp", "percentage", "depth", "notional")
FetchBytes = Callable[[str], bytes]


@dataclass(frozen=True)
class HistoricalDepthConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    start_date: str = "2024-01-01"
    end_date: str = "2024-03-31"
    cache_dir: str = "state/alpha_agents/binance_historical_depth"
    max_workers: int = 8
    request_retries: int = 3
    request_timeout_seconds: float = 60.0
    min_coverage_ratio: float = 0.98

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DepthSnapshot:
    ts_ms: int
    depth_by_percentage: dict[int, float]
    notional_by_percentage: dict[int, float]

    def imbalance(self, percentage: int) -> float:
        bid = self.notional_by_percentage[-percentage]
        ask = self.notional_by_percentage[percentage]
        total = bid + ask
        return (bid - ask) / total if total > 0 else 0.0

    @property
    def near_depth_share(self) -> float:
        near = self.notional_by_percentage[-1] + self.notional_by_percentage[1]
        broad = self.notional_by_percentage[-5] + self.notional_by_percentage[5]
        return near / broad if broad > 0 else 0.0


def archive_url(*, symbol: str, date: str) -> str:
    filename = f"{symbol}-bookDepth-{date}.zip"
    return f"{PUBLIC_ARCHIVE_BASE_URL}/{symbol}/{filename}"


def _parse_timestamp(raw: str) -> int:
    parsed = dt.datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.UTC)
    return int(parsed.timestamp() * 1000)


def iter_depth_snapshots(stream: io.TextIOBase) -> Iterator[DepthSnapshot]:
    reader = csv.reader(stream)
    header = tuple(next(reader, ()))
    if header != DEPTH_COLUMNS:
        raise ValueError(f"unexpected bookDepth schema: {header!r}")
    current_ts: int | None = None
    depth: dict[int, float] = {}
    notional: dict[int, float] = {}

    def snapshot() -> DepthSnapshot:
        if current_ts is None or tuple(sorted(depth)) != EXPECTED_PERCENTAGES:
            raise ValueError("bookDepth snapshot does not contain exact +/-1..5 percentage levels")
        return DepthSnapshot(
            ts_ms=current_ts,
            depth_by_percentage=dict(depth),
            notional_by_percentage=dict(notional),
        )

    for line_number, columns in enumerate(reader, start=2):
        if not columns:
            continue
        if len(columns) != len(DEPTH_COLUMNS):
            raise ValueError(f"unexpected bookDepth column count at line {line_number}")
        try:
            ts_ms = _parse_timestamp(columns[0])
            percentage_value = float(columns[1])
            percentage = int(percentage_value)
            depth_value = float(columns[2])
            notional_value = float(columns[3])
        except ValueError as exc:
            raise ValueError(f"invalid bookDepth value at line {line_number}") from exc
        if percentage_value != percentage or percentage not in EXPECTED_PERCENTAGES:
            raise ValueError(f"unexpected bookDepth percentage at line {line_number}")
        if depth_value < 0 or notional_value < 0 or not math.isfinite(depth_value + notional_value):
            raise ValueError(f"invalid bookDepth depth/notional at line {line_number}")
        if current_ts is not None and ts_ms < current_ts:
            raise ValueError("bookDepth timestamp regression")
        if current_ts is not None and ts_ms != current_ts:
            yield snapshot()
            depth.clear()
            notional.clear()
        current_ts = ts_ms
        if percentage in depth:
            raise ValueError(f"duplicate bookDepth percentage at line {line_number}")
        depth[percentage] = depth_value
        notional[percentage] = notional_value
    if current_ts is not None:
        yield snapshot()


def parse_depth_csv(text: str) -> list[DepthSnapshot]:
    return list(iter_depth_snapshots(io.StringIO(text)))


def _default_fetch(url: str, *, timeout_seconds: float, retries: int) -> bytes:  # pragma: no cover - network
    request = urllib.request.Request(url, headers={"User-Agent": "qount-historical-depth/0.1"})
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _download_archive(url: str, destination: Path, *, config: HistoricalDepthConfig, fetch: FetchBytes | None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(f"{destination.name}.part")
    if fetch is not None:
        part.write_bytes(fetch(url))
        os.replace(part, destination)
        return
    request = urllib.request.Request(url, headers={"User-Agent": "qount-historical-depth/0.1"})
    for attempt in range(config.request_retries + 1):  # pragma: no cover - network
        try:
            with urllib.request.urlopen(request, timeout=config.request_timeout_seconds) as response, part.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            os.replace(part, destination)
            return
        except urllib.error.HTTPError:
            part.unlink(missing_ok=True)
            raise
        except (OSError, TimeoutError, urllib.error.URLError):
            part.unlink(missing_ok=True)
            if attempt >= config.request_retries:
                raise
            time.sleep(0.25 * (2**attempt))


def _aggregate_snapshots(snapshots: Iterator[DepthSnapshot]) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    snapshot_count = 0
    first_ts: int | None = None
    last_ts: int | None = None
    max_gap_ms = 0
    previous_ts: int | None = None
    for row in snapshots:
        snapshot_count += 1
        first_ts = row.ts_ms if first_ts is None else first_ts
        last_ts = row.ts_ms
        if previous_ts is not None:
            max_gap_ms = max(max_gap_ms, row.ts_ms - previous_ts)
        previous_ts = row.ts_ms
        bucket_ts = row.ts_ms // FIVE_MINUTES_MS * FIVE_MINUTES_MS
        bucket = buckets.setdefault(
            bucket_ts,
            {
                "ts_ms": bucket_ts,
                "snapshot_count": 0,
                "imbalance_1_sum": 0.0,
                "imbalance_1_sumsq": 0.0,
                "imbalance_5_sum": 0.0,
                "imbalance_5_sumsq": 0.0,
                "near_depth_share_sum": 0.0,
            },
        )
        imbalance_1 = row.imbalance(1)
        imbalance_5 = row.imbalance(5)
        bucket["snapshot_count"] += 1
        bucket["imbalance_1_sum"] += imbalance_1
        bucket["imbalance_1_sumsq"] += imbalance_1 * imbalance_1
        bucket["imbalance_5_sum"] += imbalance_5
        bucket["imbalance_5_sumsq"] += imbalance_5 * imbalance_5
        bucket["near_depth_share_sum"] += row.near_depth_share
    return buckets, {
        "snapshot_count": snapshot_count,
        "first_ts_ms": first_ts,
        "last_ts_ms": last_ts,
        "max_snapshot_gap_ms": max_gap_ms,
    }


def _finalize_bucket(symbol: str, bucket: dict[str, Any]) -> dict[str, Any]:
    count = int(bucket["snapshot_count"])
    mean_1 = float(bucket["imbalance_1_sum"]) / count
    mean_5 = float(bucket["imbalance_5_sum"]) / count
    var_1 = max(0.0, float(bucket["imbalance_1_sumsq"]) / count - mean_1 * mean_1)
    var_5 = max(0.0, float(bucket["imbalance_5_sumsq"]) / count - mean_5 * mean_5)
    return {
        "symbol": symbol,
        "ts_ms": int(bucket["ts_ms"]),
        "snapshot_count": count,
        "depth_imbalance_1pct_mean": mean_1,
        "depth_imbalance_1pct_std": math.sqrt(var_1),
        "depth_imbalance_5pct_mean": mean_5,
        "depth_imbalance_5pct_std": math.sqrt(var_5),
        "near_depth_share_mean": float(bucket["near_depth_share_sum"]) / count,
        "complete": count > 0,
    }


def _load_archive(
    *,
    symbol: str,
    date: str,
    config: HistoricalDepthConfig,
    fetch: FetchBytes | None,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    url = archive_url(symbol=symbol, date=date)
    filename = url.rsplit("/", 1)[-1]
    actual_fetch = fetch or (
        lambda target: _default_fetch(
            target,
            timeout_seconds=config.request_timeout_seconds,
            retries=config.request_retries,
        )
    )
    expected_digest = _parse_checksum(actual_fetch(f"{url}.CHECKSUM"), filename)
    archive_path = Path(config.cache_dir).expanduser() / filename
    if not archive_path.exists():
        _download_archive(url, archive_path, config=config, fetch=fetch)
    actual_digest = _sha256_file(archive_path)
    if actual_digest != expected_digest:
        raise ValueError(f"checksum mismatch for {symbol}/{date}")
    with zipfile.ZipFile(archive_path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("bookDepth archive must contain exactly one CSV")
        with archive.open(members[0]) as raw:
            stream = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            buckets, audit = _aggregate_snapshots(iter_depth_snapshots(stream))
    return buckets, {
        "symbol": symbol,
        "date": date,
        "archive_filename": filename,
        "archive_size_bytes": archive_path.stat().st_size,
        "checksum_sha256": actual_digest,
        "checksum_verified": True,
        "bucket_count": len(buckets),
        **audit,
    }


def _dates(start: dt.date, end: dt.date) -> list[str]:
    return [str(start + dt.timedelta(days=offset)) for offset in range((end - start).days + 1)]


def _segment_rows(rows: list[dict[str, Any]]) -> None:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)
    for selected in by_symbol.values():
        segment_id = 0
        previous_ts: int | None = None
        for row in sorted(selected, key=lambda item: int(item["ts_ms"])):
            ts_ms = int(row["ts_ms"])
            if previous_ts is not None and ts_ms - previous_ts != FIVE_MINUTES_MS:
                segment_id += 1
            row["segment_id"] = segment_id
            previous_ts = ts_ms


def build_historical_depth_dataset(
    config: HistoricalDepthConfig,
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    if not config.symbols:
        raise ValueError("at least one symbol is required")
    if config.max_workers <= 0 or config.request_retries < 0:
        raise ValueError("invalid worker/retry configuration")
    if not 0 < config.min_coverage_ratio <= 1:
        raise ValueError("min_coverage_ratio must be in (0,1]")
    start = dt.date.fromisoformat(config.start_date)
    end = dt.date.fromisoformat(config.end_date)
    if end < start:
        raise ValueError("end_date must not precede start_date")
    symbols = tuple(symbol.upper() for symbol in config.symbols)
    dates = _dates(start, end)
    tasks = [(symbol, date) for symbol in symbols for date in dates]
    archives: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    merged: dict[tuple[str, int], dict[str, Any]] = {}

    def load(task: tuple[str, str]):
        symbol, date = task
        try:
            return _load_archive(symbol=symbol, date=date, config=config, fetch=fetch), None
        except Exception as exc:
            return None, {
                "symbol": symbol,
                "date": date,
                "error": type(exc).__name__,
                "message": str(exc)[:240],
            }

    with ThreadPoolExecutor(max_workers=min(config.max_workers, len(tasks))) as pool:
        for result, error in pool.map(load, tasks):
            if error is not None:
                errors.append(error)
                continue
            buckets, audit = result
            archives.append(audit)
            symbol = str(audit["symbol"])
            for ts_ms, bucket in buckets.items():
                key = (symbol, ts_ms)
                if key in merged:
                    raise ValueError(f"duplicate bookDepth bucket for {symbol}/{ts_ms}")
                merged[key] = _finalize_bucket(symbol, bucket)
    rows = [merged[key] for key in sorted(merged)]
    _segment_rows(rows)
    expected_count = len(dates) * EXPECTED_BUCKETS_PER_DAY
    by_symbol: dict[str, Any] = {}
    for symbol in symbols:
        selected = [row for row in rows if row["symbol"] == symbol and row["complete"]]
        by_symbol[symbol] = {
            "expected_bucket_count": expected_count,
            "complete_bucket_count": len(selected),
            "complete_coverage_ratio": min(1.0, len(selected) / expected_count) if expected_count else 0.0,
            "segment_count": len({row["segment_id"] for row in selected}),
            "snapshot_count": sum(int(row["snapshot_count"]) for row in selected),
        }
    blockers: list[str] = []
    if errors:
        blockers.append("archive_fetch_or_parse_errors")
    if any(row["complete_coverage_ratio"] < config.min_coverage_ratio for row in by_symbol.values()):
        blockers.append("coverage_below_threshold")
    basis = {
        "config": config.to_dict(),
        "archives": sorted(archives, key=lambda item: (item["symbol"], item["date"])),
        "rows": rows,
    }
    data_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema_version": HISTORICAL_DEPTH_VERSION,
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "point_in_time": True,
            "checksum_verified": bool(archives) and all(row["checksum_verified"] for row in archives),
            "replayable": not blockers,
            "replayable_l2": False,
            "source": "binance_usdm_public_bookDepth_percentage_aggregates",
            "data_hash": data_hash,
            "aggregation_period_ms": FIVE_MINUTES_MS,
        },
        "config": config.to_dict(),
        "schema_audit": {
            "columns": list(DEPTH_COLUMNS),
            "required_percentages": list(EXPECTED_PERCENTAGES),
            "semantic_boundary": "percentage-bucket cumulative depth/notional; not price-level diff-depth",
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
            "promotion_note": "Aggregate depth integrity is data evidence, not replayable L2 or alpha evidence.",
        },
        "five_minute_features": rows,
    }


def write_historical_depth_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-historical-depth",
        path_key="artifact_path",
        default_filename="alpha_agent_historical_depth.json",
        explicit_path=explicit_path,
    )
