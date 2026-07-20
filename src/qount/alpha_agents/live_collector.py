from __future__ import annotations

from concurrent.futures import Future
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from decimal import Decimal
from decimal import InvalidOperation
import gzip
import hashlib
import heapq
import json
import multiprocessing
import os
import shutil
import time
from pathlib import Path
from threading import Event
from threading import Lock
from typing import Any
from typing import Callable
import urllib.parse
import urllib.request

from qount.artifacts import persistent_research_dir
from qount.settings import Settings


LIVE_COLLECTOR_VERSION = "alpha_agent_live_collector_v0.1"
DEFAULT_WS_BASE_URL = "wss://fstream.binance.com"
DEFAULT_WS_API_URL = "wss://ws-fapi.binance.com/ws-fapi/v1"
DEFAULT_DEPTH_URL = "https://fapi.binance.com/fapi/v1/depth"

SUPPORTED_STREAMS = ("bookTicker", "trade", "aggTrade", "depth", "forceOrder")
STREAM_ROUTES = {
    "bookTicker": "public",
    "depth": "public",
    "trade": "market",
    "aggTrade": "market",
    "forceOrder": "market",
}


@dataclass(frozen=True)
class LiveCollectorConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    streams: tuple[str, ...] = ("bookTicker", "aggTrade", "depth", "forceOrder")
    duration_seconds: int = 60
    snapshot_interval_seconds: int = 30
    depth_speed_ms: int = 100
    depth_limit: int = 1000
    receive_timeout_seconds: float = 1.0
    reconnect_delay_seconds: float = 1.0
    max_events: int = 0
    max_depth_buffer_events: int = 50_000
    future_tolerance_ms: int = 1_000
    stale_event_ms: int = 5_000
    max_stale_event_rate: float = 0.01
    max_trade_gap_rate: float = 0.0001
    max_depth_sequence_breaks: int = 0
    max_connection_errors: int = 3
    max_snapshot_error_rate: float = 0.01
    snapshot_max_retries: int = 2
    snapshot_retry_delay_seconds: float = 0.5
    ws_base_url: str = DEFAULT_WS_BASE_URL
    ws_api_url: str = DEFAULT_WS_API_URL
    depth_url: str = DEFAULT_DEPTH_URL
    snapshot_transport: str = "websocket_api"
    use_proxy_env: bool = True
    min_free_disk_bytes: int = 0
    disk_check_interval_seconds: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        if any(not symbol or not symbol.isalnum() for symbol in self.symbols):
            raise ValueError("symbols must be non-empty alphanumeric Binance ids")
        unknown = sorted(set(self.streams) - set(SUPPORTED_STREAMS))
        if unknown:
            raise ValueError(f"unsupported streams: {','.join(unknown)}")
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.snapshot_interval_seconds <= 0:
            raise ValueError("snapshot_interval_seconds must be positive")
        if self.depth_speed_ms not in {100, 250, 500}:
            raise ValueError("depth_speed_ms must be one of 100,250,500")
        if self.depth_limit not in {5, 10, 20, 50, 100, 500, 1000}:
            raise ValueError("unsupported Binance depth snapshot limit")
        if self.snapshot_transport not in {"websocket_api", "rest"}:
            raise ValueError("snapshot_transport must be websocket_api or rest")
        for name, value in (
            ("max_stale_event_rate", self.max_stale_event_rate),
            ("max_trade_gap_rate", self.max_trade_gap_rate),
            ("max_snapshot_error_rate", self.max_snapshot_error_rate),
        ):
            if value < 0 or value > 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.max_connection_errors < 0 or self.max_depth_sequence_breaks < 0:
            raise ValueError("error thresholds must be non-negative")
        if self.snapshot_max_retries < 0:
            raise ValueError("snapshot_max_retries must be non-negative")
        if self.snapshot_retry_delay_seconds < 0:
            raise ValueError("snapshot_retry_delay_seconds must be non-negative")
        if self.min_free_disk_bytes < 0:
            raise ValueError("min_free_disk_bytes must be non-negative")
        if self.disk_check_interval_seconds <= 0:
            raise ValueError("disk_check_interval_seconds must be positive")


def stream_names(config: LiveCollectorConfig, *, route: str | None = None) -> tuple[str, ...]:
    names: list[str] = []
    for symbol in config.symbols:
        prefix = symbol.lower()
        for stream in config.streams:
            if route is not None and STREAM_ROUTES[stream] != route:
                continue
            if stream == "depth":
                names.append(f"{prefix}@depth@{config.depth_speed_ms}ms")
            else:
                names.append(f"{prefix}@{stream}")
    return tuple(names)


def _route_stream_url(config: LiveCollectorConfig, route: str, names: tuple[str, ...]) -> str:
    streams = "/".join(names)
    return f"{config.ws_base_url.rstrip('/')}/{route}/stream?streams={streams}"


def combined_stream_urls(config: LiveCollectorConfig) -> tuple[tuple[str, str], ...]:
    urls: list[tuple[str, str]] = []
    for route in ("public", "market"):
        names = stream_names(config, route=route)
        if names:
            urls.append((route, _route_stream_url(config, route, names)))
    return tuple(urls)


def combined_stream_url(config: LiveCollectorConfig) -> str:
    urls = combined_stream_urls(config)
    if len(urls) != 1:
        raise ValueError("configured streams span multiple Binance routes; use combined_stream_urls")
    return urls[0][1]


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_stream_message(message: str | bytes, *, received_at_ms: int | None = None) -> dict[str, Any]:
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    envelope = json.loads(message)
    if not isinstance(envelope, dict):
        raise ValueError("combined stream message must be an object")
    data = envelope.get("data", envelope)
    if not isinstance(data, dict):
        raise ValueError("combined stream data must be an object")
    stream = str(envelope.get("stream") or "")
    order = data.get("o") if isinstance(data.get("o"), dict) else {}
    event_type = str(data.get("e") or "unknown")
    symbol = str(data.get("s") or order.get("s") or stream.partition("@")[0]).upper()
    event_time_ms = _as_int(data.get("E"))
    transaction_time_ms = _as_int(data.get("T"))
    if transaction_time_ms is None:
        transaction_time_ms = _as_int(order.get("T"))
    return {
        "record_type": "market_event",
        "received_at_ms": int(received_at_ms if received_at_ms is not None else _now_ms()),
        "stream": stream,
        "event_type": event_type,
        "symbol": symbol,
        "event_time_ms": event_time_ms,
        "transaction_time_ms": transaction_time_ms,
        "payload": data,
    }


def fetch_depth_snapshot(config: LiveCollectorConfig, symbol: str) -> dict[str, Any]:
    started_at_ms = _now_ms()
    query = urllib.parse.urlencode({"symbol": symbol.upper(), "limit": config.depth_limit})
    request = urllib.request.Request(
        f"{config.depth_url}?{query}",
        headers={"User-Agent": "qount-alpha-agent-live-collector/0.1"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # pragma: no cover - network
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or _as_int(payload.get("lastUpdateId")) is None:
        raise ValueError(f"invalid depth snapshot for {symbol}: {payload!r}")
    return {
        "record_type": "depth_snapshot",
        "symbol": symbol.upper(),
        "snapshot_started_at_ms": started_at_ms,
        "received_at_ms": _now_ms(),
        "payload": payload,
    }


def normalize_depth_snapshot_response(
    response: dict[str, Any],
    *,
    symbol: str,
    started_at_ms: int,
    received_at_ms: int | None = None,
) -> dict[str, Any]:
    status = _as_int(response.get("status"))
    payload = response.get("result")
    if status != 200 or not isinstance(payload, dict) or _as_int(payload.get("lastUpdateId")) is None:
        raise ValueError(f"invalid websocket depth snapshot for {symbol}: {response!r}")
    return {
        "record_type": "depth_snapshot",
        "symbol": symbol.upper(),
        "snapshot_started_at_ms": started_at_ms,
        "received_at_ms": int(received_at_ms if received_at_ms is not None else _now_ms()),
        "payload": payload,
    }


def _fetch_depth_snapshots_once(config: LiveCollectorConfig) -> list[dict[str, Any]]:
    if config.snapshot_transport == "rest":
        records: list[dict[str, Any]] = []
        for symbol in config.symbols:
            try:
                records.append(fetch_depth_snapshot(config, symbol))
            except Exception as exc:
                records.append(
                    {
                        "record_type": "snapshot_error",
                        "symbol": symbol,
                        "received_at_ms": _now_ms(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
        return records

    try:
        from websockets.sync.client import connect
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("live collector needs: pip install -e '.[collector]'") from exc

    started_by_id: dict[str, tuple[str, int]] = {}
    records = []
    try:
        with connect(
            config.ws_api_url,
            open_timeout=15,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=None,
            proxy=True if config.use_proxy_env else None,
        ) as websocket:
            for index, symbol in enumerate(config.symbols):
                request_id = f"depth-{index}-{symbol.lower()}"
                started_at_ms = _now_ms()
                started_by_id[request_id] = (symbol, started_at_ms)
                websocket.send(
                    json.dumps(
                        {
                            "id": request_id,
                            "method": "depth",
                            "params": {"symbol": symbol, "limit": config.depth_limit},
                        },
                        separators=(",", ":"),
                    )
                )
            pending = set(started_by_id)
            deadline = time.monotonic() + 15
            while pending and time.monotonic() < deadline:
                try:
                    message = websocket.recv(timeout=max(0.1, min(1.0, deadline - time.monotonic())))
                except TimeoutError:
                    continue
                response = json.loads(message)
                request_id = str(response.get("id") or "")
                if request_id not in pending:
                    continue
                symbol, started_at_ms = started_by_id[request_id]
                try:
                    records.append(
                        normalize_depth_snapshot_response(
                            response,
                            symbol=symbol,
                            started_at_ms=started_at_ms,
                        )
                    )
                except Exception as exc:
                    records.append(
                        {
                            "record_type": "snapshot_error",
                            "symbol": symbol,
                            "received_at_ms": _now_ms(),
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                pending.remove(request_id)
            for request_id in sorted(pending):
                symbol, _ = started_by_id[request_id]
                records.append(
                    {
                        "record_type": "snapshot_error",
                        "symbol": symbol,
                        "received_at_ms": _now_ms(),
                        "error_type": "TimeoutError",
                        "error": "websocket depth snapshot response timed out",
                    }
                )
    except Exception as exc:
        returned = {str(record.get("symbol") or "") for record in records}
        for symbol in config.symbols:
            if symbol in returned:
                continue
            records.append(
                {
                    "record_type": "snapshot_error",
                    "symbol": symbol,
                    "received_at_ms": _now_ms(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    return records


def fetch_depth_snapshots(config: LiveCollectorConfig) -> list[dict[str, Any]]:
    pending_symbols = config.symbols
    records: list[dict[str, Any]] = []
    for attempt in range(config.snapshot_max_retries + 1):
        attempt_config = replace(config, symbols=pending_symbols, snapshot_max_retries=0)
        attempt_records = _fetch_depth_snapshots_once(attempt_config)
        failed_symbols: list[str] = []
        for record in attempt_records:
            if record.get("record_type") != "snapshot_error":
                records.append(record)
                continue
            symbol = str(record.get("symbol") or "").upper()
            if attempt >= config.snapshot_max_retries:
                records.append(record)
                continue
            if symbol and symbol != "*":
                failed_symbols.append(symbol)
            else:
                failed_symbols.extend(pending_symbols)
            records.append(
                {
                    "record_type": "snapshot_retry",
                    "symbol": symbol or "*",
                    "received_at_ms": record.get("received_at_ms", _now_ms()),
                    "attempt": attempt + 1,
                    "error_type": record.get("error_type"),
                    "error": record.get("error"),
                }
            )
        if not failed_symbols:
            break
        pending_symbols = tuple(dict.fromkeys(failed_symbols))
        if config.snapshot_retry_delay_seconds:
            time.sleep(config.snapshot_retry_delay_seconds)
    return records


class GzipJsonlWriter:
    def __init__(
        self,
        path: Path,
        *,
        min_free_disk_bytes: int = 0,
        disk_check_interval_seconds: float = 30.0,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.min_free_disk_bytes = min_free_disk_bytes
        self.disk_check_interval_seconds = disk_check_interval_seconds
        self._last_disk_check_at = 0.0
        self._check_disk_space(force=True)
        self._fh = gzip.open(path, "wt", encoding="utf-8", compresslevel=6)
        self.line_count = 0

    def _check_disk_space(self, *, force: bool = False) -> None:
        if not self.min_free_disk_bytes:
            return
        now = time.monotonic()
        if not force and now - self._last_disk_check_at < self.disk_check_interval_seconds:
            return
        free_bytes = shutil.disk_usage(self.path.parent).free
        self._last_disk_check_at = now
        if free_bytes < self.min_free_disk_bytes:
            raise RuntimeError(
                "collector disk guard tripped: "
                f"free_bytes={free_bytes} minimum={self.min_free_disk_bytes} path={self.path.parent}"
            )

    def write(self, record: dict[str, Any]) -> None:
        self._check_disk_space()
        self._fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.line_count += 1
        if self.line_count % 1000 == 0:
            self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "GzipJsonlWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def iter_gzip_jsonl(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_hash(config: LiveCollectorConfig) -> str:
    raw = json.dumps(config.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _latency_bucket(latency_ms: int) -> str:
    for upper in (0, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10_000, 30_000):
        if latency_ms <= upper:
            return str(upper)
    return "inf"


def _histogram_percentile(histogram: dict[str, int], total: int, quantile: float) -> int | None:
    if total <= 0:
        return None
    threshold = max(1, int(total * quantile + 0.999999))
    cumulative = 0
    ordered = ("0", "10", "25", "50", "100", "250", "500", "1000", "2500", "5000", "10000", "30000", "inf")
    for label in ordered:
        cumulative += histogram.get(label, 0)
        if cumulative >= threshold:
            return None if label == "inf" else int(label)
    return None


def _new_depth_state() -> dict[str, Any]:
    return {
        "snapshot_id": None,
        "anchored": False,
        "prev_u": None,
        "buffer": [],
        "depth_events": 0,
        "awaiting_resync": False,
        "anchors": 0,
        "bids": {},
        "asks": {},
        "bid_heap": [],
        "ask_heap": [],
        "replay_updates": 0,
    }


def _parse_depth_level(level: Any) -> tuple[Decimal, Decimal] | None:
    if not isinstance(level, (list, tuple)) or len(level) < 2:
        return None
    try:
        price = Decimal(str(level[0]))
        quantity = Decimal(str(level[1]))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not price.is_finite() or not quantity.is_finite() or price <= 0 or quantity < 0:
        return None
    return price, quantity


def _replace_depth_book(state: dict[str, Any], payload: dict[str, Any]) -> int:
    bids: dict[Decimal, Decimal] = {}
    asks: dict[Decimal, Decimal] = {}
    invalid_levels = 0
    for key, book in (("bids", bids), ("asks", asks)):
        levels = payload.get(key)
        if not isinstance(levels, list):
            invalid_levels += 1
            continue
        for raw_level in levels:
            level = _parse_depth_level(raw_level)
            if level is None:
                invalid_levels += 1
                continue
            price, quantity = level
            if quantity:
                book[price] = quantity
    state["bids"] = bids
    state["asks"] = asks
    state["bid_heap"] = [-price for price in bids]
    state["ask_heap"] = list(asks)
    heapq.heapify(state["bid_heap"])
    heapq.heapify(state["ask_heap"])
    return invalid_levels


def _apply_depth_updates(state: dict[str, Any], payload: dict[str, Any]) -> int:
    invalid_levels = 0
    for key, book_key, heap_key, is_bid in (
        ("b", "bids", "bid_heap", True),
        ("a", "asks", "ask_heap", False),
    ):
        levels = payload.get(key)
        if not isinstance(levels, list):
            invalid_levels += 1
            continue
        book: dict[Decimal, Decimal] = state[book_key]
        heap: list[Decimal] = state[heap_key]
        for raw_level in levels:
            level = _parse_depth_level(raw_level)
            if level is None:
                invalid_levels += 1
                continue
            price, quantity = level
            if not quantity:
                book.pop(price, None)
                continue
            if price not in book:
                heapq.heappush(heap, -price if is_bid else price)
            book[price] = quantity
        if len(heap) > len(book) * 2 + 1_000:
            heap[:] = [(-price if is_bid else price) for price in book]
            heapq.heapify(heap)
    state["replay_updates"] += 1
    return invalid_levels


def _best_depth_level(state: dict[str, Any], *, is_bid: bool) -> tuple[Decimal, Decimal] | None:
    book_key = "bids" if is_bid else "asks"
    heap_key = "bid_heap" if is_bid else "ask_heap"
    book: dict[Decimal, Decimal] = state[book_key]
    heap: list[Decimal] = state[heap_key]
    while heap:
        price = -heap[0] if is_bid else heap[0]
        quantity = book.get(price)
        if quantity is not None:
            return price, quantity
        heapq.heappop(heap)
    return None


def audit_records(records, config: LiveCollectorConfig) -> dict[str, Any]:
    counts: dict[str, int] = {}
    by_symbol: dict[str, dict[str, int]] = {symbol: {} for symbol in config.symbols}
    connection_opens = 0
    connection_continuations = 0
    connection_errors = 0
    snapshot_retries = 0
    snapshot_errors = 0
    snapshot_counts = {symbol: 0 for symbol in config.symbols}
    last_trade: dict[tuple[str, str], int] = {}
    trade_observations = 0
    trade_missing_ids = 0
    trade_out_of_order = 0
    last_book: dict[str, int] = {}
    book_observations = 0
    book_out_of_order = 0
    latency_histogram: dict[str, int] = {}
    latency_count = 0
    latency_sum = 0
    latency_max: int | None = None
    event_time_missing = 0
    event_time_future = 0
    event_time_stale = 0
    depth_sequence_observations = 0
    depth_sequence_breaks = 0
    depth_snapshot_resyncs = 0
    depth_buffer_overflows = 0
    depth_invalid_levels = 0
    depth_empty_books = 0
    depth_crossed_books = 0

    depth_state: dict[str, dict[str, Any]] = {symbol: _new_depth_state() for symbol in config.symbols}

    def apply_and_check(state: dict[str, Any], payload: dict[str, Any]) -> None:
        nonlocal depth_invalid_levels, depth_empty_books, depth_crossed_books
        depth_invalid_levels += _apply_depth_updates(state, payload)
        best_bid = _best_depth_level(state, is_bid=True)
        best_ask = _best_depth_level(state, is_bid=False)
        if best_bid is None or best_ask is None:
            depth_empty_books += 1
        elif best_bid[0] >= best_ask[0]:
            depth_crossed_books += 1

    def process_depth(symbol: str, payload: dict[str, Any]) -> None:
        nonlocal depth_sequence_observations, depth_sequence_breaks, depth_snapshot_resyncs
        state = depth_state.setdefault(symbol, _new_depth_state())
        first_id = _as_int(payload.get("U"))
        final_id = _as_int(payload.get("u"))
        previous_final_id = _as_int(payload.get("pu"))
        if first_id is None or final_id is None:
            return
        if state["anchored"]:
            depth_sequence_observations += 1
            if previous_final_id != state["prev_u"]:
                depth_sequence_breaks += 1
                state["anchored"] = False
                state["snapshot_id"] = None
                state["prev_u"] = None
                state["awaiting_resync"] = True
                state["bids"] = {}
                state["asks"] = {}
                state["bid_heap"] = []
                state["ask_heap"] = []
                state["buffer"] = [payload]
                return
            state["prev_u"] = final_id
            apply_and_check(state, payload)
            return

        snapshot_id = state["snapshot_id"]
        if snapshot_id is None:
            state["buffer"].append(payload)
            if len(state["buffer"]) > config.max_depth_buffer_events:
                state["buffer"].pop(0)
                nonlocal_depth_overflow[0] += 1
            return
        if final_id < snapshot_id:
            return
        if (first_id <= snapshot_id <= final_id) or previous_final_id == snapshot_id:
            if state["awaiting_resync"]:
                depth_snapshot_resyncs += 1
                state["awaiting_resync"] = False
            state["anchored"] = True
            state["prev_u"] = final_id
            state["anchors"] += 1
            apply_and_check(state, payload)

    nonlocal_depth_overflow = [0]

    for record in records:
        record_type = str(record.get("record_type") or "unknown")
        counts[record_type] = counts.get(record_type, 0) + 1
        if record_type == "connection_open":
            connection_opens += 1
            continue
        if record_type == "connection_continuation":
            connection_continuations += 1
            continue
        if record_type == "connection_error":
            connection_errors += 1
            continue
        if record_type == "snapshot_retry":
            snapshot_retries += 1
            continue
        if record_type == "snapshot_error":
            snapshot_errors += 1
            continue
        if record_type == "depth_snapshot":
            symbol = str(record.get("symbol") or "").upper()
            snapshot_id = _as_int((record.get("payload") or {}).get("lastUpdateId"))
            if snapshot_id is None:
                snapshot_errors += 1
                continue
            snapshot_counts[symbol] = snapshot_counts.get(symbol, 0) + 1
            state = depth_state.setdefault(symbol, _new_depth_state())
            if state["anchored"]:
                continue
            state["snapshot_id"] = snapshot_id
            depth_invalid_levels += _replace_depth_book(state, record.get("payload") or {})
            buffered = list(state["buffer"])
            state["buffer"] = []
            for payload in buffered:
                process_depth(symbol, payload)
            continue
        if record_type != "market_event":
            continue

        event_type = str(record.get("event_type") or "unknown")
        symbol = str(record.get("symbol") or "").upper()
        counts[event_type] = counts.get(event_type, 0) + 1
        symbol_counts = by_symbol.setdefault(symbol, {})
        symbol_counts[event_type] = symbol_counts.get(event_type, 0) + 1
        payload = record.get("payload") or {}
        received_at_ms = _as_int(record.get("received_at_ms"))
        event_time_ms = _as_int(record.get("event_time_ms"))
        if received_at_ms is None or event_time_ms is None:
            event_time_missing += 1
        else:
            latency_ms = received_at_ms - event_time_ms
            latency_count += 1
            latency_sum += latency_ms
            latency_max = latency_ms if latency_max is None else max(latency_max, latency_ms)
            bucket = _latency_bucket(latency_ms)
            latency_histogram[bucket] = latency_histogram.get(bucket, 0) + 1
            if latency_ms < -config.future_tolerance_ms:
                event_time_future += 1
            if latency_ms > config.stale_event_ms:
                event_time_stale += 1

        if event_type in {"aggTrade", "trade"}:
            trade_id = _as_int(payload.get("a" if event_type == "aggTrade" else "t"))
            if trade_id is not None:
                key = (symbol, event_type)
                previous = last_trade.get(key)
                if previous is not None:
                    trade_observations += 1
                    if trade_id <= previous:
                        trade_out_of_order += 1
                    elif trade_id > previous + 1:
                        trade_missing_ids += trade_id - previous - 1
                last_trade[key] = max(previous or trade_id, trade_id)
        elif event_type == "bookTicker":
            update_id = _as_int(payload.get("u"))
            if update_id is not None:
                previous = last_book.get(symbol)
                if previous is not None:
                    book_observations += 1
                    if update_id <= previous:
                        book_out_of_order += 1
                last_book[symbol] = max(previous or update_id, update_id)
        elif event_type == "depthUpdate":
            first_id = _as_int(payload.get("U"))
            final_id = _as_int(payload.get("u"))
            previous_final_id = _as_int(payload.get("pu"))
            state = depth_state.setdefault(symbol, _new_depth_state())
            state["depth_events"] += 1
            if first_id is not None and final_id is not None:
                process_depth(symbol, payload)

    depth_buffer_overflows = nonlocal_depth_overflow[0]
    trade_denominator = trade_observations + trade_missing_ids
    trade_gap_rate = trade_missing_ids / trade_denominator if trade_denominator else 0.0
    stale_rate = event_time_stale / latency_count if latency_count else 0.0
    depth_unanchored = sorted(
        symbol for symbol, state in depth_state.items() if state["depth_events"] > 0 and not state["anchored"]
    )
    missing_required: list[str] = []
    if "bookTicker" in config.streams and counts.get("bookTicker", 0) == 0:
        missing_required.append("bookTicker")
    if "depth" in config.streams and counts.get("depthUpdate", 0) == 0:
        missing_required.append("depthUpdate")
    if ({"trade", "aggTrade"} & set(config.streams)) and not (counts.get("trade", 0) or counts.get("aggTrade", 0)):
        missing_required.append("trade_or_aggTrade")
    blockers: list[str] = []
    if connection_opens == 0 and connection_continuations == 0:
        blockers.append("no_websocket_connection")
    if connection_errors > config.max_connection_errors:
        blockers.append("connection_errors_above_threshold")
    if missing_required:
        blockers.append("required_stream_events_missing")
    snapshot_attempts = sum(snapshot_counts.values()) + snapshot_errors
    snapshot_error_rate = snapshot_errors / snapshot_attempts if snapshot_attempts else 0.0
    if snapshot_error_rate > config.max_snapshot_error_rate:
        blockers.append("depth_snapshot_error_rate_above_threshold")
    if "depth" in config.streams and any(snapshot_counts.get(symbol, 0) == 0 for symbol in config.symbols):
        blockers.append("depth_snapshot_missing")
    if depth_unanchored:
        blockers.append("depth_replay_unanchored")
    if depth_sequence_breaks > config.max_depth_sequence_breaks:
        blockers.append("depth_sequence_breaks_above_threshold")
    if depth_buffer_overflows:
        blockers.append("depth_buffer_overflow")
    if depth_invalid_levels:
        blockers.append("depth_replay_invalid_levels")
    if depth_empty_books:
        blockers.append("depth_replay_empty_book")
    if depth_crossed_books:
        blockers.append("depth_replay_crossed_book")
    if trade_gap_rate > config.max_trade_gap_rate:
        blockers.append("trade_gap_rate_above_threshold")
    if trade_out_of_order:
        blockers.append("trade_out_of_order")
    if book_out_of_order:
        blockers.append("book_ticker_out_of_order")
    if event_time_missing:
        blockers.append("event_time_missing")
    if event_time_future:
        blockers.append("event_time_future")
    if stale_rate > config.max_stale_event_rate:
        blockers.append("stale_event_rate_above_threshold")

    return {
        "verdict": "pass_data_smoke" if not blockers else "block_data",
        "blockers": blockers,
        "counts": counts,
        "by_symbol": by_symbol,
        "connections": {
            "opens": connection_opens,
            "continuations": connection_continuations,
            "errors": connection_errors,
        },
        "snapshots": {
            "by_symbol": snapshot_counts,
            "retries": snapshot_retries,
            "errors": snapshot_errors,
            "attempts": snapshot_attempts,
            "error_rate": snapshot_error_rate,
        },
        "trades": {
            "sequence_observations": trade_observations,
            "missing_ids": trade_missing_ids,
            "out_of_order": trade_out_of_order,
            "gap_rate": trade_gap_rate,
        },
        "book_ticker": {"sequence_observations": book_observations, "out_of_order": book_out_of_order},
        "depth": {
            "sequence_observations": depth_sequence_observations,
            "sequence_breaks": depth_sequence_breaks,
            "snapshot_resyncs": depth_snapshot_resyncs,
            "buffer_overflows": depth_buffer_overflows,
            "replay_updates": sum(int(state["replay_updates"]) for state in depth_state.values()),
            "invalid_levels": depth_invalid_levels,
            "empty_books": depth_empty_books,
            "crossed_books": depth_crossed_books,
            "unanchored_symbols": depth_unanchored,
            "anchors_by_symbol": {symbol: state["anchors"] for symbol, state in depth_state.items()},
            "final_top_by_symbol": {
                symbol: {
                    "bid": (
                        [str(level[0]), str(level[1])]
                        if (level := _best_depth_level(state, is_bid=True)) is not None
                        else None
                    ),
                    "ask": (
                        [str(level[0]), str(level[1])]
                        if (level := _best_depth_level(state, is_bid=False)) is not None
                        else None
                    ),
                }
                for symbol, state in depth_state.items()
            },
        },
        "event_time": {
            "count": latency_count,
            "missing": event_time_missing,
            "future": event_time_future,
            "stale": event_time_stale,
            "stale_rate": stale_rate,
            "latency_mean_ms": latency_sum / latency_count if latency_count else None,
            "latency_p95_bucket_ms": _histogram_percentile(latency_histogram, latency_count, 0.95),
            "latency_max_ms": latency_max,
            "latency_histogram": latency_histogram,
        },
        "notes": [
            "forceOrder can legitimately have zero events during a quiet collection window",
            "pass_data_smoke is a data-quality verdict only and is not strategy promotion",
        ],
    }


def audit_event_file(path: Path, config: LiveCollectorConfig) -> dict[str, Any]:
    return audit_records(iter_gzip_jsonl(path), config)


def _write_snapshot_result(writer: GzipJsonlWriter, future: Future) -> None:
    try:
        for record in future.result():
            writer.write(record)
    except Exception as exc:
        writer.write(
            {
                "record_type": "snapshot_error",
                "symbol": "*",
                "received_at_ms": _now_ms(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )


def capture_market_streams(config: LiveCollectorConfig, raw_path: Path) -> dict[str, Any]:
    config.validate()
    try:
        from websockets.sync.client import connect
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("live collector needs: pip install -e '.[collector]'") from exc

    started_at_ms = _now_ms()
    deadline = time.monotonic() + config.duration_seconds
    routes = combined_stream_urls(config)
    write_lock = Lock()

    def safe_write(writer: GzipJsonlWriter, record: dict[str, Any]) -> None:
        with write_lock:
            writer.write(record)

    def capture_route(writer: GzipJsonlWriter, route: str, uri: str) -> dict[str, Any]:
        route_streams = tuple(stream for stream in config.streams if STREAM_ROUTES[stream] == route)
        route_has_depth = "depth" in route_streams
        route_market_events = 0
        route_connection_attempts = 0
        route_first_event_at_ms: int | None = None
        route_last_event_at_ms: int | None = None
        with ThreadPoolExecutor(max_workers=min(8, len(config.symbols))) as pool:
            while time.monotonic() < deadline and (
                config.max_events <= 0 or route_market_events < config.max_events
            ):
                route_connection_attempts += 1
                connection_id = f"{route}-{route_connection_attempts}"
                try:
                    with connect(
                        uri,
                        open_timeout=15,
                        close_timeout=5,
                        ping_interval=20,
                        ping_timeout=20,
                        max_size=None,
                        max_queue=4096,
                        proxy=True if config.use_proxy_env else None,
                    ) as websocket:
                        safe_write(
                            writer,
                            {
                                "record_type": "connection_open",
                                "connection_id": connection_id,
                                "route": route,
                                "received_at_ms": _now_ms(),
                            },
                        )
                        pending_snapshot: Future | None = None
                        next_snapshot_at = 0.0
                        while time.monotonic() < deadline and (
                            config.max_events <= 0 or route_market_events < config.max_events
                        ):
                            now = time.monotonic()
                            if route_has_depth and now >= next_snapshot_at:
                                if pending_snapshot is None:
                                    pending_snapshot = pool.submit(fetch_depth_snapshots, config)
                                next_snapshot_at = now + config.snapshot_interval_seconds
                            if pending_snapshot is not None and pending_snapshot.done():
                                with write_lock:
                                    _write_snapshot_result(writer, pending_snapshot)
                                pending_snapshot = None
                            remaining = max(0.0, deadline - time.monotonic())
                            if remaining <= 0:
                                break
                            try:
                                message = websocket.recv(timeout=min(config.receive_timeout_seconds, remaining))
                            except TimeoutError:
                                continue
                            record = normalize_stream_message(message)
                            record["route"] = route
                            safe_write(writer, record)
                            received_at_ms = int(record["received_at_ms"])
                            if route_first_event_at_ms is None:
                                route_first_event_at_ms = received_at_ms
                            route_last_event_at_ms = received_at_ms
                            route_market_events += 1
                        if pending_snapshot is not None:
                            if pending_snapshot.done():
                                with write_lock:
                                    _write_snapshot_result(writer, pending_snapshot)
                            else:
                                pending_snapshot.cancel()
                        safe_write(
                            writer,
                            {
                                "record_type": "connection_close",
                                "connection_id": connection_id,
                                "route": route,
                                "received_at_ms": _now_ms(),
                                "reason": "collection_deadline" if time.monotonic() >= deadline else "max_events",
                            },
                        )
                except Exception as exc:  # pragma: no cover - network-dependent
                    safe_write(
                        writer,
                        {
                            "record_type": "connection_error",
                            "connection_id": connection_id,
                            "route": route,
                            "received_at_ms": _now_ms(),
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        time.sleep(min(config.reconnect_delay_seconds, remaining))
        return {
            "route": route,
            "stream_url": uri,
            "market_events": route_market_events,
            "connection_attempts": route_connection_attempts,
            "first_market_event_at_ms": route_first_event_at_ms,
            "last_market_event_at_ms": route_last_event_at_ms,
        }

    with GzipJsonlWriter(
        raw_path,
        min_free_disk_bytes=config.min_free_disk_bytes,
        disk_check_interval_seconds=config.disk_check_interval_seconds,
    ) as writer:
        writer.write(
            {
                "record_type": "collector_start",
                "received_at_ms": started_at_ms,
                "schema_version": LIVE_COLLECTOR_VERSION,
                "stream_urls": {route: uri for route, uri in routes},
                "config": config.to_dict(),
            }
        )
        with ThreadPoolExecutor(max_workers=len(routes)) as routes_pool:
            futures = [routes_pool.submit(capture_route, writer, route, uri) for route, uri in routes]
            route_stats = [future.result() for future in futures]
        market_events = sum(int(stat["market_events"]) for stat in route_stats)
        connection_attempts = sum(int(stat["connection_attempts"]) for stat in route_stats)
        writer.write(
            {
                "record_type": "collector_stop",
                "received_at_ms": _now_ms(),
                "market_events": market_events,
                "connection_attempts": connection_attempts,
                "routes": route_stats,
            }
        )
        line_count = writer.line_count
    return {
        "started_at_ms": started_at_ms,
        "ended_at_ms": _now_ms(),
        "market_events": market_events,
        "connection_attempts": connection_attempts,
        "routes": route_stats,
        "market_event_started_at_ms": min(
            (
                int(stat["first_market_event_at_ms"])
                for stat in route_stats
                if stat["first_market_event_at_ms"] is not None
            ),
            default=None,
        ),
        "market_event_ended_at_ms": max(
            (
                int(stat["last_market_event_at_ms"])
                for stat in route_stats
                if stat["last_market_event_at_ms"] is not None
            ),
            default=None,
        ),
        "line_count": line_count,
        "stream_urls": {route: uri for route, uri in routes},
    }


def capture_market_stream_segments(
    config: LiveCollectorConfig,
    segment_targets: list[dict[str, Any]],
    *,
    on_segment_closed: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Capture multiple raw segments without restarting the market connections."""

    config.validate()
    if not segment_targets:
        raise ValueError("at least one segment target is required")
    if config.max_events:
        raise ValueError("continuous segment capture does not support max_events")
    for target in segment_targets:
        if int(target.get("duration_seconds") or 0) <= 0:
            raise ValueError("segment duration_seconds must be positive")
        partial_path = Path(target["partial_raw_path"])
        raw_path = Path(target["raw_path"])
        if partial_path == raw_path:
            raise ValueError("continuous segment partial and final paths must differ")
        existing = [path for path in (partial_path, raw_path) if path.exists()]
        if existing:
            raise FileExistsError(f"collector output already exists: {existing[0]}")

    try:
        from websockets.sync.client import connect
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("live collector needs: pip install -e '.[collector]'") from exc

    routes = combined_stream_urls(config)
    write_lock = Lock()
    stop_event = Event()
    run_id = f"{_now_ms():x}-{os.getpid():x}"
    active_connections: dict[str, str] = {}
    generation = 0
    writer: GzipJsonlWriter | None = None
    current_target: dict[str, Any] | None = None
    current_started_at_ms = 0
    connection_ids_at_start: dict[str, str] = {}
    route_stats: dict[str, dict[str, Any]] = {}
    captures: list[dict[str, Any]] = []

    def new_sequence_boundaries() -> dict[str, dict[str, Any]]:
        return {"trades": {}, "book_ticker": {}, "depth": {}}

    def new_route_stats(route: str, uri: str) -> dict[str, Any]:
        return {
            "route": route,
            "stream_url": uri,
            "market_events": 0,
            "connection_attempts": 0,
            "first_market_event_at_ms": None,
            "last_market_event_at_ms": None,
            "sequence_boundaries": new_sequence_boundaries(),
        }

    def update_sequence_boundaries(stat: dict[str, Any], record: dict[str, Any]) -> None:
        event_type = str(record.get("event_type") or "")
        symbol = str(record.get("symbol") or "").upper()
        payload = record.get("payload") or {}
        boundaries = stat["sequence_boundaries"]
        if event_type in {"aggTrade", "trade"}:
            trade_id = _as_int(payload.get("a" if event_type == "aggTrade" else "t"))
            if trade_id is not None:
                key = f"{symbol}:{event_type}"
                value = boundaries["trades"].setdefault(key, {"first": trade_id, "last": trade_id})
                value["last"] = trade_id
        elif event_type == "bookTicker":
            update_id = _as_int(payload.get("u"))
            if update_id is not None:
                value = boundaries["book_ticker"].setdefault(
                    symbol,
                    {"first": update_id, "last": update_id},
                )
                value["last"] = update_id
        elif event_type == "depthUpdate":
            current = {
                "first_update_id": _as_int(payload.get("U")),
                "final_update_id": _as_int(payload.get("u")),
                "previous_final_update_id": _as_int(payload.get("pu")),
            }
            value = boundaries["depth"].setdefault(symbol, {"first": current, "last": current})
            value["last"] = current

    def start_segment_locked(target: dict[str, Any]) -> None:
        nonlocal writer, current_target, current_started_at_ms, connection_ids_at_start, route_stats, generation
        current_target = target
        partial_path = Path(target["partial_raw_path"])
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        writer = GzipJsonlWriter(
            partial_path,
            min_free_disk_bytes=config.min_free_disk_bytes,
            disk_check_interval_seconds=config.disk_check_interval_seconds,
        )
        current_started_at_ms = _now_ms()
        connection_ids_at_start = dict(active_connections)
        route_stats = {route: new_route_stats(route, uri) for route, uri in routes}
        generation += 1
        segment_config = replace(config, duration_seconds=int(target["duration_seconds"]))
        writer.write(
            {
                "record_type": "collector_start",
                "received_at_ms": current_started_at_ms,
                "schema_version": LIVE_COLLECTOR_VERSION,
                "segment_index": int(target["index"]),
                "segment_connection_mode": "continuous_in_stream_rotation",
                "stream_urls": {route: uri for route, uri in routes},
                "config": segment_config.to_dict(),
            }
        )
        for route, connection_id in sorted(active_connections.items()):
            writer.write(
                {
                    "record_type": "connection_continuation",
                    "connection_id": connection_id,
                    "route": route,
                    "received_at_ms": current_started_at_ms,
                }
            )

    def start_segment(target: dict[str, Any]) -> None:
        with write_lock:
            start_segment_locked(target)

    def write_record(record: dict[str, Any]) -> None:
        nonlocal writer
        with write_lock:
            if writer is None:
                return
            record_type = str(record.get("record_type") or "")
            route = str(record.get("route") or "")
            connection_id = str(record.get("connection_id") or "")
            if record_type == "connection_open" and route:
                active_connections[route] = connection_id
                route_stats[route]["connection_attempts"] += 1
            elif record_type == "connection_error" and route:
                if active_connections.get(route) == connection_id:
                    active_connections.pop(route, None)
                route_stats[route]["connection_attempts"] += 1
            elif record_type == "connection_close" and route:
                if active_connections.get(route) == connection_id:
                    active_connections.pop(route, None)
            elif record_type == "market_event" and route:
                stat = route_stats[route]
                received_at_ms = int(record["received_at_ms"])
                stat["market_events"] += 1
                if stat["first_market_event_at_ms"] is None:
                    stat["first_market_event_at_ms"] = received_at_ms
                stat["last_market_event_at_ms"] = received_at_ms
                update_sequence_boundaries(stat, record)
            writer.write(record)

    def close_segment_locked(reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
        nonlocal writer, current_target
        if writer is None or current_target is None:
            raise RuntimeError("collector segment writer is not active")
        ended_at_ms = _now_ms()
        active_at_end = dict(active_connections)
        market_events = sum(int(stat["market_events"]) for stat in route_stats.values())
        connection_attempts = sum(int(stat["connection_attempts"]) for stat in route_stats.values())
        writer.write(
            {
                "record_type": "collector_stop",
                "received_at_ms": ended_at_ms,
                "market_events": market_events,
                "connection_attempts": connection_attempts,
                "reason": reason,
                "routes": list(route_stats.values()),
            }
        )
        line_count = writer.line_count
        writer.close()
        writer = None
        partial_path = Path(current_target["partial_raw_path"])
        raw_path = Path(current_target["raw_path"])
        os.replace(partial_path, raw_path)
        stats = list(route_stats.values())
        capture = {
            "started_at_ms": current_started_at_ms,
            "ended_at_ms": ended_at_ms,
            "market_events": market_events,
            "connection_attempts": connection_attempts,
            "routes": stats,
            "market_event_started_at_ms": min(
                (
                    int(stat["first_market_event_at_ms"])
                    for stat in stats
                    if stat["first_market_event_at_ms"] is not None
                ),
                default=None,
            ),
            "market_event_ended_at_ms": max(
                (
                    int(stat["last_market_event_at_ms"])
                    for stat in stats
                    if stat["last_market_event_at_ms"] is not None
                ),
                default=None,
            ),
            "line_count": line_count,
            "stream_urls": {route: uri for route, uri in routes},
            "connection_ids_at_start": connection_ids_at_start,
            "connection_ids_at_end": active_at_end,
            "segment_connection_mode": "continuous_in_stream_rotation",
            "writer_generation": generation,
        }
        target = current_target
        current_target = None
        return target, capture

    def close_segment(reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
        with write_lock:
            return close_segment_locked(reason)

    def rotate_segment(target: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        with write_lock:
            closed = close_segment_locked("segment_rotation")
            start_segment_locked(target)
            return closed

    start_segment(segment_targets[0])
    total_duration = sum(int(target["duration_seconds"]) for target in segment_targets)
    deadline = time.monotonic() + total_duration

    def capture_route(route: str, uri: str) -> None:
        route_streams = tuple(stream for stream in config.streams if STREAM_ROUTES[stream] == route)
        route_has_depth = "depth" in route_streams
        attempts = 0
        observed_generation = 0
        with ThreadPoolExecutor(max_workers=min(8, len(config.symbols))) as pool:
            pending_snapshot: Future | None = None
            next_snapshot_at = 0.0
            while not stop_event.is_set() and time.monotonic() < deadline:
                attempts += 1
                connection_id = f"{run_id}-{route}-{attempts}"
                try:
                    with connect(
                        uri,
                        open_timeout=15,
                        close_timeout=5,
                        ping_interval=20,
                        ping_timeout=20,
                        max_size=None,
                        max_queue=4096,
                        proxy=True if config.use_proxy_env else None,
                    ) as websocket:
                        write_record(
                            {
                                "record_type": "connection_open",
                                "connection_id": connection_id,
                                "route": route,
                                "received_at_ms": _now_ms(),
                            }
                        )
                        while not stop_event.is_set() and time.monotonic() < deadline:
                            with write_lock:
                                current_generation = generation
                            if current_generation != observed_generation:
                                observed_generation = current_generation
                                next_snapshot_at = 0.0
                            now = time.monotonic()
                            if route_has_depth and now >= next_snapshot_at:
                                if pending_snapshot is None:
                                    pending_snapshot = pool.submit(fetch_depth_snapshots, config)
                                next_snapshot_at = now + config.snapshot_interval_seconds
                            if pending_snapshot is not None and pending_snapshot.done():
                                try:
                                    records = pending_snapshot.result()
                                except Exception as exc:
                                    records = [
                                        {
                                            "record_type": "snapshot_error",
                                            "symbol": "*",
                                            "received_at_ms": _now_ms(),
                                            "error_type": type(exc).__name__,
                                            "error": str(exc),
                                        }
                                    ]
                                for record in records:
                                    record["route"] = route
                                    write_record(record)
                                pending_snapshot = None
                            remaining = max(0.0, deadline - time.monotonic())
                            if remaining <= 0:
                                break
                            try:
                                message = websocket.recv(timeout=min(config.receive_timeout_seconds, remaining))
                            except TimeoutError:
                                continue
                            record = normalize_stream_message(message)
                            record["route"] = route
                            write_record(record)
                        if pending_snapshot is not None:
                            if pending_snapshot.done():
                                try:
                                    records = pending_snapshot.result()
                                except Exception as exc:
                                    records = [
                                        {
                                            "record_type": "snapshot_error",
                                            "symbol": "*",
                                            "received_at_ms": _now_ms(),
                                            "error_type": type(exc).__name__,
                                            "error": str(exc),
                                        }
                                    ]
                                for record in records:
                                    record["route"] = route
                                    write_record(record)
                            else:
                                pending_snapshot.cancel()
                            pending_snapshot = None
                        write_record(
                            {
                                "record_type": "connection_close",
                                "connection_id": connection_id,
                                "route": route,
                                "received_at_ms": _now_ms(),
                                "reason": "collection_deadline",
                            }
                        )
                except Exception as exc:  # pragma: no cover - network-dependent
                    write_record(
                        {
                            "record_type": "connection_error",
                            "connection_id": connection_id,
                            "route": route,
                            "received_at_ms": _now_ms(),
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                    remaining = deadline - time.monotonic()
                    if remaining > 0 and not stop_event.is_set():
                        stop_event.wait(min(config.reconnect_delay_seconds, remaining))

    try:
        with ThreadPoolExecutor(max_workers=len(routes)) as routes_pool:
            futures = [routes_pool.submit(capture_route, route, uri) for route, uri in routes]
            next_boundary = time.monotonic() + int(segment_targets[0]["duration_seconds"])
            for target in segment_targets[1:]:
                while not stop_event.is_set():
                    remaining = next_boundary - time.monotonic()
                    if remaining <= 0:
                        break
                    stop_event.wait(min(0.1, remaining))
                closed_target, capture = rotate_segment(target)
                captures.append(capture)
                if on_segment_closed is not None:
                    on_segment_closed(closed_target, capture)
                next_boundary += int(target["duration_seconds"])
            while not stop_event.is_set():
                remaining = next_boundary - time.monotonic()
                if remaining <= 0:
                    break
                stop_event.wait(min(0.1, remaining))
            stop_event.set()
            for future in futures:
                future.result()
        closed_target, capture = close_segment("collection_deadline")
        captures.append(capture)
        if on_segment_closed is not None:
            on_segment_closed(closed_target, capture)
        return captures
    except BaseException:
        stop_event.set()
        with write_lock:
            if writer is not None:
                writer.close()
        raise


def _live_collector_result(
    config: LiveCollectorConfig,
    run_dir: Path,
    raw_path: Path,
    capture: dict[str, Any],
) -> dict[str, Any]:
    artifact_path = run_dir / "alpha_agent_live_collector.json"
    audit = audit_event_file(raw_path, config)
    result = {
        "schema_version": LIVE_COLLECTOR_VERSION,
        "artifact_path": str(artifact_path),
        "persistent_artifact_path": str(artifact_path),
        "raw_event_path": str(raw_path),
        "artifact_relpath": artifact_path.name,
        "raw_event_relpath": raw_path.name,
        "meta": {
            "research_only": True,
            "private_exchange_data": False,
            "orders_allowed": False,
            "training_allowed": False,
            "holdout_role": "forward_research_data_only",
            "point_in_time": True,
            "event_time_audited": True,
            "replayable": audit["verdict"] == "pass_data_smoke",
            "path_contract": "segment_relative_v1",
            "source": "Binance USD-M public websocket + public WS-API/REST depth snapshot",
            "source_urls": [config.ws_base_url, config.ws_api_url, config.depth_url],
            "config_hash": _config_hash(config),
            "raw_sha256": _sha256_file(raw_path),
            "raw_bytes": raw_path.stat().st_size,
        },
        "config": config.to_dict(),
        "capture": capture,
        "audit": audit,
    }
    _atomic_write_json(artifact_path, result)
    return result


def run_live_collector_segments(
    settings: Settings,
    segments: list[tuple[LiveCollectorConfig, str]],
    *,
    on_segment_complete: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    if not segments:
        raise ValueError("at least one collector segment is required")
    base_config = segments[0][0]
    base_contract = base_config.to_dict()
    base_contract.pop("duration_seconds", None)
    targets: list[dict[str, Any]] = []
    configs: list[LiveCollectorConfig] = []
    for index, (segment_config, output_dir) in enumerate(segments):
        segment_config.validate()
        contract = segment_config.to_dict()
        contract.pop("duration_seconds", None)
        if contract != base_contract:
            raise ValueError("continuous collector segments must share one frozen config")
        run_dir = Path(output_dir).expanduser()
        if not run_dir.is_absolute():
            run_dir = settings.project_root / run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        raw_path = run_dir / "events.jsonl.gz"
        partial_path = run_dir / "events.jsonl.gz.partial"
        artifact_path = run_dir / "alpha_agent_live_collector.json"
        existing = [path for path in (raw_path, partial_path, artifact_path) if path.exists()]
        if existing:
            raise FileExistsError(f"collector output already exists: {existing[0]}")
        targets.append(
            {
                "index": index,
                "duration_seconds": segment_config.duration_seconds,
                "run_dir": run_dir,
                "raw_path": raw_path,
                "partial_raw_path": partial_path,
            }
        )
        configs.append(segment_config)

    results_by_index: dict[int, dict[str, Any]] = {}
    completion_futures: list[Future] = []
    process_context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=process_context) as audit_pool:
        with ThreadPoolExecutor(max_workers=1) as completion_pool:

            def schedule_finalize(target: dict[str, Any], capture: dict[str, Any]) -> None:
                index = int(target["index"])
                audit_future = audit_pool.submit(
                    _live_collector_result,
                    configs[index],
                    Path(target["run_dir"]),
                    Path(target["raw_path"]),
                    capture,
                )

                def complete() -> dict[str, Any]:
                    result = audit_future.result()
                    results_by_index[index] = result
                    if on_segment_complete is not None:
                        on_segment_complete(result)
                    return result

                completion_futures.append(completion_pool.submit(complete))

            capture_market_stream_segments(base_config, targets, on_segment_closed=schedule_finalize)
            for future in completion_futures:
                future.result()
    return [results_by_index[index] for index in range(len(segments))]


def run_live_collector(
    settings: Settings,
    config: LiveCollectorConfig,
    *,
    explicit_output_dir: str | None = None,
) -> dict[str, Any]:
    config.validate()
    if explicit_output_dir:
        run_dir = Path(explicit_output_dir).expanduser()
        if not run_dir.is_absolute():
            run_dir = settings.project_root / run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        run_dir = persistent_research_dir(settings, "alpha-agent-live-collector")
    raw_path = run_dir / "events.jsonl.gz"
    partial_raw_path = run_dir / "events.jsonl.gz.partial"
    artifact_path = run_dir / "alpha_agent_live_collector.json"
    existing = [path for path in (raw_path, partial_raw_path, artifact_path) if path.exists()]
    if existing:
        raise FileExistsError(f"collector output already exists: {existing[0]}")
    capture = capture_market_streams(config, partial_raw_path)
    os.replace(partial_raw_path, raw_path)
    return _live_collector_result(config, run_dir, raw_path, capture)
