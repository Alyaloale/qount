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
from typing import BinaryIO
from typing import Callable
from typing import Iterator
from typing import TextIO

from qount.artifacts import write_research_json_artifact
from qount.settings import Settings


HISTORICAL_TRADEFLOW_VERSION = "alpha_agent_historical_tradeflow_v0.1"
PUBLIC_ARCHIVE_BASE_URL = "https://data.binance.vision/data/futures/um"
FIVE_MINUTES_MS = 5 * 60_000
EXPECTED_BUCKETS_PER_DAY = 24 * 60 // 5
SUPPORTED_DATASETS = ("aggTrades", "bookTicker")
FetchBytes = Callable[[str], bytes]

AGG_TRADE_COLUMNS = (
    "agg_trade_id",
    "price",
    "quantity",
    "first_trade_id",
    "last_trade_id",
    "transact_time",
    "is_buyer_maker",
)
BOOK_TICKER_COLUMNS = (
    "update_id",
    "best_bid_price",
    "best_bid_qty",
    "best_ask_price",
    "best_ask_qty",
    "transaction_time",
    "event_time",
)


@dataclass(frozen=True)
class HistoricalTradeFlowConfig:
    symbols: tuple[str, ...] = ("ETHUSDT",)
    start_date: str = "2024-01-01"
    end_date: str = "2024-01-31"
    datasets: tuple[str, ...] = ("aggTrades",)
    cadence: str = "monthly"
    cache_dir: str = "state/alpha_agents/binance_historical_tradeflow"
    max_workers: int = 2
    request_retries: int = 3
    request_timeout_seconds: float = 60.0
    min_coverage_ratio: float = 0.98

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AggTradeEvent:
    agg_trade_id: int
    price: float
    quantity: float
    first_trade_id: int
    last_trade_id: int
    transact_time_ms: int
    is_buyer_maker: bool


@dataclass(frozen=True)
class BookTickerEvent:
    update_id: int
    best_bid_price: float
    best_bid_qty: float
    best_ask_price: float
    best_ask_qty: float
    transaction_time_ms: int
    event_time_ms: int


def _normalize_timestamp(raw: str) -> int:
    value = int(raw.strip())
    return value // 1000 if value >= 1_000_000_000_000_000 else value


def _parse_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"invalid boolean value: {raw!r}")


def _dict_reader(stream: TextIO, expected_columns: tuple[str, ...]) -> csv.DictReader:
    reader = csv.DictReader(stream)
    actual = tuple(reader.fieldnames or ())
    if actual != expected_columns:
        raise ValueError(f"unexpected CSV schema: expected={expected_columns!r} actual={actual!r}")
    return reader


def iter_agg_trades_csv(stream: TextIO) -> Iterator[AggTradeEvent]:
    for item in _dict_reader(stream, AGG_TRADE_COLUMNS):
        yield AggTradeEvent(
            agg_trade_id=int(item["agg_trade_id"]),
            price=float(item["price"]),
            quantity=float(item["quantity"]),
            first_trade_id=int(item["first_trade_id"]),
            last_trade_id=int(item["last_trade_id"]),
            transact_time_ms=_normalize_timestamp(item["transact_time"]),
            is_buyer_maker=_parse_bool(item["is_buyer_maker"]),
        )


def iter_book_ticker_csv(stream: TextIO) -> Iterator[BookTickerEvent]:
    for item in _dict_reader(stream, BOOK_TICKER_COLUMNS):
        yield BookTickerEvent(
            update_id=int(item["update_id"]),
            best_bid_price=float(item["best_bid_price"]),
            best_bid_qty=float(item["best_bid_qty"]),
            best_ask_price=float(item["best_ask_price"]),
            best_ask_qty=float(item["best_ask_qty"]),
            transaction_time_ms=_normalize_timestamp(item["transaction_time"]),
            event_time_ms=_normalize_timestamp(item["event_time"]),
        )


def parse_agg_trades_csv(text: str) -> list[AggTradeEvent]:
    return list(iter_agg_trades_csv(io.StringIO(text)))


def parse_book_ticker_csv(text: str) -> list[BookTickerEvent]:
    return list(iter_book_ticker_csv(io.StringIO(text)))


def archive_url(*, dataset: str, symbol: str, cadence: str, period: str) -> str:
    if dataset not in SUPPORTED_DATASETS:
        raise ValueError(f"unsupported trade-flow dataset: {dataset}")
    if cadence not in {"daily", "monthly"}:
        raise ValueError(f"unsupported archive cadence: {cadence}")
    filename = f"{symbol}-{dataset}-{period}.zip"
    return f"{PUBLIC_ARCHIVE_BASE_URL}/{cadence}/{dataset}/{symbol}/{filename}"


def _parse_checksum(payload: bytes, filename: str) -> str:
    parts = payload.decode("utf-8").strip().split()
    if len(parts) < 2 or parts[-1].lstrip("*") != filename:
        raise ValueError("invalid checksum sidecar filename")
    digest = parts[0].lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("invalid checksum digest")
    return digest


def _network_to_file(
    url: str,
    destination: Path,
    *,
    timeout_seconds: float,
    retries: int,
) -> None:  # pragma: no cover - network
    request = urllib.request.Request(url, headers={"User-Agent": "qount-historical-tradeflow/0.1"})
    part = destination.with_name(f"{destination.name}.part")
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response, part.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            os.replace(part, destination)
            return
        except urllib.error.HTTPError:
            part.unlink(missing_ok=True)
            raise
        except (OSError, TimeoutError, urllib.error.URLError):
            part.unlink(missing_ok=True)
            if attempt >= retries:
                raise
            time.sleep(0.25 * (2**attempt))


def _ensure_cached_file(
    url: str,
    *,
    cache_dir: str,
    fetch: FetchBytes | None,
    timeout_seconds: float,
    retries: int,
) -> Path:
    destination = Path(cache_dir).expanduser() / url.rsplit("/", 1)[-1]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    if fetch is None:
        _network_to_file(
            url,
            destination,
            timeout_seconds=timeout_seconds,
            retries=retries,
        )
        return destination
    blob = fetch(url)
    part = destination.with_name(f"{destination.name}.part")
    part.write_bytes(blob)
    os.replace(part, destination)
    return destination


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _single_csv_stream(archive: zipfile.ZipFile) -> tuple[str, BinaryIO]:
    names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if len(names) != 1:
        raise ValueError("trade-flow archive must contain exactly one CSV")
    return names[0], archive.open(names[0])


def _new_agg_bucket(symbol: str, ts_ms: int) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "ts_ms": ts_ms,
        "agg_trade_count": 0,
        "aggressive_buy_trade_count": 0,
        "aggressive_sell_trade_count": 0,
        "agg_trade_base_volume": 0.0,
        "agg_trade_quote_volume": 0.0,
        "aggressive_buy_base_volume": 0.0,
        "aggressive_sell_base_volume": 0.0,
        "aggressive_buy_quote_volume": 0.0,
        "aggressive_sell_quote_volume": 0.0,
    }


def _aggregate_agg_trades(
    stream: TextIO,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    row_count = 0
    filtered_row_count = 0
    first_ts: int | None = None
    last_ts: int | None = None
    first_id: int | None = None
    last_id: int | None = None
    id_gap_count = 0
    id_gap_size = 0
    id_regression_count = 0
    timestamp_regression_count = 0
    max_event_gap_ms = 0
    previous_id: int | None = None
    previous_ts: int | None = None
    for event in iter_agg_trades_csv(stream):
        row_count += 1
        if previous_id is not None:
            delta = event.agg_trade_id - previous_id
            if delta > 1:
                id_gap_count += 1
                id_gap_size += delta - 1
            elif delta <= 0:
                id_regression_count += 1
        if previous_ts is not None:
            if event.transact_time_ms < previous_ts:
                timestamp_regression_count += 1
            else:
                max_event_gap_ms = max(max_event_gap_ms, event.transact_time_ms - previous_ts)
        first_ts = event.transact_time_ms if first_ts is None else first_ts
        first_id = event.agg_trade_id if first_id is None else first_id
        last_ts = event.transact_time_ms
        last_id = event.agg_trade_id
        previous_id = event.agg_trade_id
        previous_ts = event.transact_time_ms
        if event.transact_time_ms < start_ms or event.transact_time_ms > end_ms:
            filtered_row_count += 1
            continue
        bucket_ts = event.transact_time_ms // FIVE_MINUTES_MS * FIVE_MINUTES_MS
        bucket = buckets.setdefault(bucket_ts, _new_agg_bucket(symbol, bucket_ts))
        quote_volume = event.price * event.quantity
        bucket["agg_trade_count"] += 1
        bucket["agg_trade_base_volume"] += event.quantity
        bucket["agg_trade_quote_volume"] += quote_volume
        side = "sell" if event.is_buyer_maker else "buy"
        bucket[f"aggressive_{side}_trade_count"] += 1
        bucket[f"aggressive_{side}_base_volume"] += event.quantity
        bucket[f"aggressive_{side}_quote_volume"] += quote_volume
    return buckets, {
        "row_count": row_count,
        "filtered_row_count": filtered_row_count,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "first_id": first_id,
        "last_id": last_id,
        "id_gap_count": id_gap_count,
        "id_gap_size": id_gap_size,
        "id_regression_count": id_regression_count,
        "timestamp_regression_count": timestamp_regression_count,
        "max_event_gap_ms": max_event_gap_ms,
    }


def _new_book_bucket(symbol: str, ts_ms: int) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "ts_ms": ts_ms,
        "book_ticker_event_count": 0,
        "book_spread_bps_sum": 0.0,
        "book_top_imbalance_sum": 0.0,
        "book_last_update_id": None,
        "book_last_bid_price": None,
        "book_last_bid_qty": None,
        "book_last_ask_price": None,
        "book_last_ask_qty": None,
        "book_last_spread_bps": None,
        "book_last_top_imbalance": None,
        "book_event_transaction_lag_ms_sum": 0.0,
        "book_event_transaction_lag_ms_max": 0,
    }


def _aggregate_book_ticker(
    stream: TextIO,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    row_count = 0
    filtered_row_count = 0
    crossed_book_count = 0
    invalid_quantity_count = 0
    update_id_regression_count = 0
    event_time_regression_count = 0
    transaction_time_regression_count = 0
    max_event_gap_ms = 0
    first_ts: int | None = None
    last_ts: int | None = None
    first_id: int | None = None
    last_id: int | None = None
    previous_id: int | None = None
    previous_event_ts: int | None = None
    previous_transaction_ts: int | None = None
    for event in iter_book_ticker_csv(stream):
        row_count += 1
        if previous_id is not None and event.update_id <= previous_id:
            update_id_regression_count += 1
        if previous_event_ts is not None:
            if event.event_time_ms < previous_event_ts:
                event_time_regression_count += 1
            else:
                max_event_gap_ms = max(max_event_gap_ms, event.event_time_ms - previous_event_ts)
        if previous_transaction_ts is not None and event.transaction_time_ms < previous_transaction_ts:
            transaction_time_regression_count += 1
        if event.best_bid_price > event.best_ask_price:
            crossed_book_count += 1
        if event.best_bid_qty < 0 or event.best_ask_qty < 0:
            invalid_quantity_count += 1
        first_ts = event.event_time_ms if first_ts is None else first_ts
        first_id = event.update_id if first_id is None else first_id
        last_ts = event.event_time_ms
        last_id = event.update_id
        previous_id = event.update_id
        previous_event_ts = event.event_time_ms
        previous_transaction_ts = event.transaction_time_ms
        if event.event_time_ms < start_ms or event.event_time_ms > end_ms:
            filtered_row_count += 1
            continue
        midpoint = (event.best_bid_price + event.best_ask_price) / 2.0
        spread_bps = (event.best_ask_price - event.best_bid_price) / midpoint * 10_000.0 if midpoint > 0 else 0.0
        quantity_sum = event.best_bid_qty + event.best_ask_qty
        imbalance = (event.best_bid_qty - event.best_ask_qty) / quantity_sum if quantity_sum > 0 else 0.0
        lag_ms = event.event_time_ms - event.transaction_time_ms
        bucket_ts = event.event_time_ms // FIVE_MINUTES_MS * FIVE_MINUTES_MS
        bucket = buckets.setdefault(bucket_ts, _new_book_bucket(symbol, bucket_ts))
        bucket["book_ticker_event_count"] += 1
        bucket["book_spread_bps_sum"] += spread_bps
        bucket["book_top_imbalance_sum"] += imbalance
        bucket["book_last_update_id"] = event.update_id
        bucket["book_last_bid_price"] = event.best_bid_price
        bucket["book_last_bid_qty"] = event.best_bid_qty
        bucket["book_last_ask_price"] = event.best_ask_price
        bucket["book_last_ask_qty"] = event.best_ask_qty
        bucket["book_last_spread_bps"] = spread_bps
        bucket["book_last_top_imbalance"] = imbalance
        bucket["book_event_transaction_lag_ms_sum"] += lag_ms
        bucket["book_event_transaction_lag_ms_max"] = max(bucket["book_event_transaction_lag_ms_max"], lag_ms)
    return buckets, {
        "row_count": row_count,
        "filtered_row_count": filtered_row_count,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "first_id": first_id,
        "last_id": last_id,
        "update_id_regression_count": update_id_regression_count,
        "event_time_regression_count": event_time_regression_count,
        "transaction_time_regression_count": transaction_time_regression_count,
        "crossed_book_count": crossed_book_count,
        "invalid_quantity_count": invalid_quantity_count,
        "max_event_gap_ms": max_event_gap_ms,
        "update_id_gap_semantics": "not_a_gap_signal; Binance bookTicker update IDs may skip",
    }


def _archive_periods(start: dt.date, end: dt.date, cadence: str) -> list[str]:
    if cadence == "daily":
        return [(start + dt.timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]
    periods: list[str] = []
    current = dt.date(start.year, start.month, 1)
    final = dt.date(end.year, end.month, 1)
    while current <= final:
        periods.append(current.strftime("%Y-%m"))
        current = dt.date(current.year + int(current.month == 12), current.month % 12 + 1, 1)
    return periods


def _load_archive(
    *,
    dataset: str,
    symbol: str,
    period: str,
    start_ms: int,
    end_ms: int,
    config: HistoricalTradeFlowConfig,
    fetch: FetchBytes | None,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    url = archive_url(dataset=dataset, symbol=symbol, cadence=config.cadence, period=period)
    filename = url.rsplit("/", 1)[-1]
    checksum_path = _ensure_cached_file(
        f"{url}.CHECKSUM",
        cache_dir=config.cache_dir,
        fetch=fetch,
        timeout_seconds=config.request_timeout_seconds,
        retries=config.request_retries,
    )
    archive_path = _ensure_cached_file(
        url,
        cache_dir=config.cache_dir,
        fetch=fetch,
        timeout_seconds=config.request_timeout_seconds,
        retries=config.request_retries,
    )
    expected_digest = _parse_checksum(checksum_path.read_bytes(), filename)
    actual_digest = _sha256_file(archive_path)
    if actual_digest != expected_digest:
        raise ValueError("archive checksum mismatch")
    with zipfile.ZipFile(archive_path) as archive:
        member_name, binary_stream = _single_csv_stream(archive)
        with binary_stream, io.TextIOWrapper(binary_stream, encoding="utf-8-sig", newline="") as text_stream:
            if dataset == "aggTrades":
                buckets, audit = _aggregate_agg_trades(
                    text_stream,
                    symbol=symbol,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            else:
                buckets, audit = _aggregate_book_ticker(
                    text_stream,
                    symbol=symbol,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
    return buckets, {
        "dataset": dataset,
        "symbol": symbol,
        "period": period,
        "cadence": config.cadence,
        "archive_url": url,
        "archive_filename": filename,
        "archive_size_bytes": archive_path.stat().st_size,
        "csv_member": member_name,
        "checksum_sha256": actual_digest,
        "checksum_verified": True,
        "bucket_count": len(buckets),
        **audit,
    }


def _finalize_row(row: dict[str, Any], *, datasets: tuple[str, ...]) -> dict[str, Any]:
    agg_count = int(row.get("agg_trade_count", 0))
    agg_quote = float(row.get("agg_trade_quote_volume", 0.0))
    buy_quote = float(row.get("aggressive_buy_quote_volume", 0.0))
    sell_quote = float(row.get("aggressive_sell_quote_volume", 0.0))
    book_count = int(row.get("book_ticker_event_count", 0))
    if "aggTrades" in datasets:
        row["agg_trade_imbalance"] = (buy_quote - sell_quote) / agg_quote if agg_quote > 0 else None
        row["agg_trade_count_imbalance"] = (
            (int(row.get("aggressive_buy_trade_count", 0)) - int(row.get("aggressive_sell_trade_count", 0)))
            / agg_count
            if agg_count > 0
            else None
        )
    if "bookTicker" in datasets:
        row["book_spread_bps_mean"] = row.pop("book_spread_bps_sum", 0.0) / book_count if book_count else None
        row["book_top_imbalance_mean"] = row.pop("book_top_imbalance_sum", 0.0) / book_count if book_count else None
        row["book_event_transaction_lag_ms_mean"] = (
            row.pop("book_event_transaction_lag_ms_sum", 0.0) / book_count if book_count else None
        )
    row["complete"] = all(
        (dataset == "aggTrades" and agg_count > 0) or (dataset == "bookTicker" and book_count > 0)
        for dataset in datasets
    )
    return row


def _segment_rows(rows: list[dict[str, Any]]) -> None:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)
    for symbol_rows in by_symbol.values():
        segment_id = 0
        previous_ts: int | None = None
        previous_complete = False
        for row in sorted(symbol_rows, key=lambda item: int(item["ts_ms"])):
            current_ts = int(row["ts_ms"])
            complete = bool(row["complete"])
            if previous_ts is not None and (
                current_ts - previous_ts != FIVE_MINUTES_MS or not previous_complete or not complete
            ):
                segment_id += 1
            row["segment_id"] = segment_id
            previous_ts = current_ts
            previous_complete = complete


def _symbol_coverage(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    datasets: tuple[str, ...],
    expected_buckets: int,
) -> dict[str, Any]:
    selected = [row for row in rows if row["symbol"] == symbol]
    by_dataset: dict[str, Any] = {}
    for dataset in datasets:
        count_key = "agg_trade_count" if dataset == "aggTrades" else "book_ticker_event_count"
        bucket_count = sum(int(row.get(count_key, 0)) > 0 for row in selected)
        by_dataset[dataset] = {
            "bucket_count": bucket_count,
            "coverage_ratio": min(1.0, bucket_count / expected_buckets) if expected_buckets else 0.0,
        }
    complete = [row for row in selected if row["complete"]]
    gaps = [
        int(right["ts_ms"]) - int(left["ts_ms"])
        for left, right in zip(complete, complete[1:])
        if int(right["ts_ms"]) - int(left["ts_ms"]) > FIVE_MINUTES_MS
    ]
    return {
        "expected_bucket_count": expected_buckets,
        "union_bucket_count": len(selected),
        "complete_bucket_count": len(complete),
        "complete_coverage_ratio": min(1.0, len(complete) / expected_buckets) if expected_buckets else 0.0,
        "segment_count": len({row["segment_id"] for row in complete}),
        "gap_count": len(gaps),
        "max_gap_ms": max(gaps) if gaps else 0,
        "by_dataset": by_dataset,
    }


def _cross_archive_audit(archives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for archive in archives:
        groups.setdefault((str(archive["dataset"]), str(archive["symbol"])), []).append(archive)
    for (dataset, symbol), group in sorted(groups.items()):
        id_gap_count = 0
        id_gap_size = 0
        id_regression_count = 0
        timestamp_regression_count = 0
        previous_last_id: int | None = None
        previous_last_ts: int | None = None
        for archive in sorted(group, key=lambda item: str(item["period"])):
            first_id = archive.get("first_id")
            first_ts = archive.get("first_ts")
            if previous_last_id is not None and first_id is not None:
                delta = int(first_id) - previous_last_id
                if dataset == "aggTrades" and delta > 1:
                    id_gap_count += 1
                    id_gap_size += delta - 1
                elif delta <= 0:
                    id_regression_count += 1
            if previous_last_ts is not None and first_ts is not None and int(first_ts) < previous_last_ts:
                timestamp_regression_count += 1
            if archive.get("last_id") is not None:
                previous_last_id = int(archive["last_id"])
            if archive.get("last_ts") is not None:
                previous_last_ts = int(archive["last_ts"])
        result.append(
            {
                "dataset": dataset,
                "symbol": symbol,
                "archive_count": len(group),
                "id_gap_count": id_gap_count,
                "id_gap_size": id_gap_size,
                "id_regression_count": id_regression_count,
                "timestamp_regression_count": timestamp_regression_count,
                "id_gap_semantics": (
                    "contiguous aggregate-trade IDs required"
                    if dataset == "aggTrades"
                    else "bookTicker skipped update IDs are ignored; regressions only"
                ),
            }
        )
    return result


def build_historical_tradeflow_dataset(
    config: HistoricalTradeFlowConfig,
    *,
    fetch: FetchBytes | None = None,
) -> dict[str, Any]:
    if not config.symbols:
        raise ValueError("at least one symbol is required")
    if not config.datasets:
        raise ValueError("at least one dataset is required")
    if unknown := sorted(set(config.datasets) - set(SUPPORTED_DATASETS)):
        raise ValueError(f"unsupported datasets: {','.join(unknown)}")
    if config.cadence not in {"daily", "monthly"}:
        raise ValueError("cadence must be 'daily' or 'monthly'")
    if config.max_workers <= 0:
        raise ValueError("max_workers must be positive")
    if not 0 < config.min_coverage_ratio <= 1:
        raise ValueError("min_coverage_ratio must be in (0,1]")
    start = dt.date.fromisoformat(config.start_date)
    end = dt.date.fromisoformat(config.end_date)
    if end < start:
        raise ValueError("end_date must not precede start_date")
    symbols = tuple(symbol.upper() for symbol in config.symbols)
    datasets = tuple(dict.fromkeys(config.datasets))
    periods = _archive_periods(start, end, config.cadence)
    start_ms = int(dt.datetime.combine(start, dt.time.min, tzinfo=dt.UTC).timestamp() * 1000)
    end_ms = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC).timestamp() * 1000) - 1
    tasks = [(dataset, symbol, period) for dataset in datasets for symbol in symbols for period in periods]
    archives: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    merged: dict[tuple[str, int], dict[str, Any]] = {}

    def load(task: tuple[str, str, str]):
        dataset, symbol, period = task
        try:
            result = _load_archive(
                dataset=dataset,
                symbol=symbol,
                period=period,
                start_ms=start_ms,
                end_ms=end_ms,
                config=config,
                fetch=fetch,
            )
            return result, None
        except Exception as exc:
            return None, {
                "dataset": dataset,
                "symbol": symbol,
                "period": period,
                "error": type(exc).__name__,
                "message": str(exc)[:200],
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
                target = merged.setdefault(key, {"symbol": symbol, "ts_ms": ts_ms})
                duplicate_keys = set(target) & set(bucket) - {"symbol", "ts_ms"}
                if duplicate_keys:
                    raise ValueError(f"overlapping archive buckets for {symbol} at {ts_ms}")
                target.update(bucket)

    rows = [_finalize_row(merged[key], datasets=datasets) for key in sorted(merged)]
    _segment_rows(rows)
    cross_archive = _cross_archive_audit(archives)
    expected_buckets = ((end - start).days + 1) * EXPECTED_BUCKETS_PER_DAY
    by_symbol = {
        symbol: _symbol_coverage(
            rows,
            symbol=symbol,
            datasets=datasets,
            expected_buckets=expected_buckets,
        )
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
    if any(
        audit.get("id_gap_count", 0)
        or audit.get("id_regression_count", 0)
        or audit.get("timestamp_regression_count", 0)
        for audit in archives
        if audit["dataset"] == "aggTrades"
    ):
        blockers.append("agg_trade_sequence_anomaly")
    if any(
        audit.get("update_id_regression_count", 0)
        or audit.get("event_time_regression_count", 0)
        or audit.get("transaction_time_regression_count", 0)
        or audit.get("crossed_book_count", 0)
        or audit.get("invalid_quantity_count", 0)
        for audit in archives
        if audit["dataset"] == "bookTicker"
    ):
        blockers.append("book_ticker_schema_or_ordering_anomaly")
    if any(
        audit["id_gap_count"] or audit["id_regression_count"] or audit["timestamp_regression_count"]
        for audit in cross_archive
    ):
        blockers.append("cross_archive_sequence_anomaly")
    basis = {
        "config": config.to_dict(),
        "archives": [
            {key: value for key, value in audit.items() if key != "archive_url"}
            for audit in sorted(archives, key=lambda item: (item["dataset"], item["symbol"], item["period"]))
        ],
        "rows": rows,
    }
    data_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "schema_version": HISTORICAL_TRADEFLOW_VERSION,
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "point_in_time": True,
            "checksum_verified": bool(archives) and all(audit["checksum_verified"] for audit in archives),
            "replayable": not blockers,
            "source": "binance_usdm_public_archive",
            "data_hash": data_hash,
            "aggregation_period_ms": FIVE_MINUTES_MS,
            "agg_trade_sign": "buyer_maker=false is aggressive buy; buyer_maker=true is aggressive sell",
            "book_update_id_semantics": "monotonicity audit only; skipped IDs are not treated as packet gaps",
            "receive_latency_available": False,
        },
        "config": config.to_dict(),
        "window": {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "start_utc": dt.datetime.fromtimestamp(start_ms / 1000, dt.UTC).isoformat(),
            "end_utc": dt.datetime.fromtimestamp((end_ms + 1) / 1000, dt.UTC).isoformat(),
            "period_ms": FIVE_MINUTES_MS,
        },
        "schema_audit": {
            "aggTrades": list(AGG_TRADE_COLUMNS),
            "bookTicker": list(BOOK_TICKER_COLUMNS),
        },
        "diagnostics": {
            "verdict": "pass_data_smoke" if not blockers else "block_data",
            "blockers": blockers,
            "requested_archive_count": len(tasks),
            "loaded_archive_count": len(archives),
            "error_count": len(errors),
            "errors": errors,
            "row_count": len(rows),
            "complete_row_count": sum(bool(row["complete"]) for row in rows),
            "by_symbol": by_symbol,
            "archives": sorted(archives, key=lambda item: (item["dataset"], item["symbol"], item["period"])),
            "cross_archive_sequence": cross_archive,
            "promotion_note": "Checksum and schema coverage are dataset evidence, not alpha or paper/live evidence.",
        },
        "five_minute_features": rows,
    }


def write_historical_tradeflow_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-historical-tradeflow",
        path_key="artifact_path",
        default_filename="alpha_agent_historical_tradeflow.json",
        explicit_path=explicit_path,
    )
