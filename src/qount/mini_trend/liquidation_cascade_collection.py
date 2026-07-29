"""Append-only public collection for the liquidation-cascade forward study.

The ``forceOrder`` stream is the directional source of forced flow.  Open
interest, shallow depth, and mark/index snapshots are only contemporaneous
context.  This module deliberately contains no signal, return calculation,
private API client, or order path.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import asdict
from dataclasses import dataclass
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any
from typing import Callable
from typing import Mapping
from urllib.parse import urlencode
from urllib.parse import urlsplit
import urllib.request
import uuid
import zlib

from qount.contracts import canonical_hash
from qount.mini_trend.forward_collection_schema import LIQUIDATION_CASCADE_FORWARD


LIQUIDATION_CASCADE_COLLECTION_VERSION = "liquidation_cascade_forward_collection_v1"
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
DEFAULT_WS_BASE_URL = "wss://fstream.binance.com"
DEFAULT_REST_BASE_URL = "https://fapi.binance.com"
CONFIGURATION_EXIT_STATUS = 64
DISK_GUARD_EXIT_STATUS = 75

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,96}$")
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SNAPSHOT_SOURCES = ("open_interest", "depth", "premium_index")


class CollectorConfigurationError(ValueError):
    """A collection definition cannot safely be started or resumed."""


class DiskSpaceExhausted(RuntimeError):
    """The configured free-space floor was crossed."""


@dataclass(frozen=True)
class LiquidationCascadeCollectorConfig:
    """Immutable runtime settings for one append-only collection root."""

    state_root: Path
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    snapshot_interval_seconds: int = 300
    event_snapshot_min_interval_seconds: int = 15
    depth_limit: int = 20
    segment_rotation_seconds: int = 60 * 60
    receive_timeout_seconds: float = 30.0
    reconnect_delay_seconds: float = 5.0
    snapshot_timeout_seconds: float = 15.0
    min_free_disk_bytes: int = 8 * 1024**3
    disk_check_interval_seconds: float = 60.0
    ws_base_url: str = DEFAULT_WS_BASE_URL
    rest_base_url: str = DEFAULT_REST_BASE_URL
    use_proxy_env: bool = False
    max_recent_event_ids: int = 4096

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_root", Path(self.state_root))
        object.__setattr__(self, "symbols", tuple(str(symbol).upper() for symbol in self.symbols))

    def validate(self) -> None:
        root = self.state_root.expanduser()
        if not root.is_absolute() or root.resolve() == Path("/"):
            raise CollectorConfigurationError("collection_state_root_must_be_a_non_root_absolute_path")
        if not self.symbols:
            raise CollectorConfigurationError("collection_symbols_required")
        normalized_symbols = tuple(symbol.upper() for symbol in self.symbols)
        if len(set(normalized_symbols)) != len(normalized_symbols):
            raise CollectorConfigurationError("collection_symbols_must_be_unique")
        if any(not _SYMBOL_RE.fullmatch(symbol) for symbol in normalized_symbols):
            raise CollectorConfigurationError("collection_symbol_invalid")
        if self.snapshot_interval_seconds <= 0:
            raise CollectorConfigurationError("collection_snapshot_interval_invalid")
        if self.event_snapshot_min_interval_seconds <= 0:
            raise CollectorConfigurationError("collection_event_snapshot_interval_invalid")
        if self.depth_limit not in {5, 10, 20, 50, 100, 500, 1000}:
            raise CollectorConfigurationError("collection_depth_limit_invalid")
        if self.segment_rotation_seconds <= 0 or 86_400 % self.segment_rotation_seconds != 0:
            raise CollectorConfigurationError("collection_segment_rotation_must_divide_utc_day")
        if self.receive_timeout_seconds <= 0 or self.reconnect_delay_seconds <= 0:
            raise CollectorConfigurationError("collection_websocket_timing_invalid")
        if self.snapshot_timeout_seconds <= 0:
            raise CollectorConfigurationError("collection_snapshot_timeout_invalid")
        if self.min_free_disk_bytes < 0 or self.disk_check_interval_seconds <= 0:
            raise CollectorConfigurationError("collection_disk_guard_invalid")
        if self.max_recent_event_ids <= 0:
            raise CollectorConfigurationError("collection_dedup_window_invalid")
        _validate_base_url(self.ws_base_url, allowed_scheme="wss")
        _validate_base_url(self.rest_base_url, allowed_scheme="https")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state_root"] = str(self.state_root)
        payload["symbols"] = list(self.symbols)
        return payload


@dataclass(frozen=True)
class SegmentPaths:
    """Paths and UTC bounds for one compressed raw segment."""

    partial_path: Path
    completed_path: Path
    relative_completed_path: str
    bucket_started_at_ms: int
    bucket_ends_at_ms: int


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _iso_utc(timestamp_ms: int) -> str:
    return dt.datetime.fromtimestamp(timestamp_ms / 1000, tz=dt.UTC).isoformat().replace("+00:00", "Z")


def _as_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _validate_base_url(value: str, *, allowed_scheme: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != allowed_scheme
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CollectorConfigurationError("collection_endpoint_url_invalid")


def _relative_to_root(path: Path, state_root: Path) -> str:
    root = state_root.expanduser().resolve()
    resolved = path.resolve(strict=False)
    try:
        return str(resolved.relative_to(root))
    except ValueError as exc:
        raise CollectorConfigurationError("collection_path_outside_state_root") from exc


def build_force_order_stream_url(config: LiquidationCascadeCollectorConfig) -> str:
    """Return Binance's public combined-stream URL for directional liquidations."""

    config.validate()
    streams = "/".join(f"{symbol.lower()}@forceOrder" for symbol in config.symbols)
    return f"{config.ws_base_url.rstrip('/')}/stream?streams={streams}"


def build_segment_paths(
    state_root: Path,
    *,
    recorded_at_ms: int,
    rotation_seconds: int,
    session_id: str,
    sequence: int,
) -> SegmentPaths:
    """Build a contained, unique UTC segment path without touching the filesystem."""

    if rotation_seconds <= 0 or 86_400 % rotation_seconds != 0:
        raise CollectorConfigurationError("collection_segment_rotation_must_divide_utc_day")
    if not _SAFE_LABEL_RE.fullmatch(session_id):
        raise CollectorConfigurationError("collection_session_id_invalid")
    if sequence < 0:
        raise CollectorConfigurationError("collection_segment_sequence_invalid")
    bucket_started_at_ms = (recorded_at_ms // (rotation_seconds * 1000)) * rotation_seconds * 1000
    bucket_ends_at_ms = bucket_started_at_ms + rotation_seconds * 1000
    bucket_start = dt.datetime.fromtimestamp(bucket_started_at_ms / 1000, tz=dt.UTC)
    directory = state_root.expanduser().resolve() / "raw" / bucket_start.strftime("%Y/%m/%d")
    filename = (
        "liquidation-cascade-"
        f"{bucket_start.strftime('%Y%m%dT%H%M%SZ')}-{session_id}-{sequence:06d}.jsonl.gz"
    )
    completed_path = directory / filename
    partial_path = completed_path.with_name(f"{filename}.partial")
    relative_completed_path = _relative_to_root(completed_path, state_root)
    _relative_to_root(partial_path, state_root)
    return SegmentPaths(
        partial_path=partial_path,
        completed_path=completed_path,
        relative_completed_path=relative_completed_path,
        bucket_started_at_ms=bucket_started_at_ms,
        bucket_ends_at_ms=bucket_ends_at_ms,
    )


def _module_source_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def build_collection_contract(config: LiquidationCascadeCollectorConfig) -> dict[str, Any]:
    """Freeze collection semantics before the first public record is written."""

    config.validate()
    semantic_core = {
        "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
        "artifact_type": "liquidation_cascade_forward_collection_contract",
        "forward_contract_hash": LIQUIDATION_CASCADE_FORWARD.contract_hash,
        "family": LIQUIDATION_CASCADE_FORWARD.family,
        "candidate_id": LIQUIDATION_CASCADE_FORWARD.candidate_id,
        "symbols": list(config.symbols),
        "sources": {
            "directional_liquidations": "binance_usdm_forceOrder_combined_stream",
            "open_interest": "binance_usdm_fapi_v1_openInterest",
            "shallow_depth": "binance_usdm_fapi_v1_depth",
            "mark_index_context": "binance_usdm_fapi_v1_premiumIndex",
        },
        "endpoints": {
            "websocket_base_url": config.ws_base_url,
            "rest_base_url": config.rest_base_url,
        },
        "snapshot_interval_seconds": config.snapshot_interval_seconds,
        "event_snapshot_min_interval_seconds": config.event_snapshot_min_interval_seconds,
        "depth_limit": config.depth_limit,
        "utc_segment_rotation_seconds": config.segment_rotation_seconds,
        "deduplication": {
            "stream_message_fingerprint": "sha256_of_source_envelope",
            "persisted_recent_event_window": config.max_recent_event_ids,
            "cross_reconnect_gap_marked": True,
        },
        "research_guards": {
            "independent_window_days": LIQUIDATION_CASCADE_FORWARD.independent_window_days,
            "read_results_before_window": False,
            "orders_authorized": False,
            "private_api_used": False,
            "pnl_evaluated": False,
            "signal_generated": False,
        },
    }
    return semantic_core | {
        "source_provenance": {
            "collector_module_sha256": _module_source_hash(),
            "frozen_forward_schema_hash": LIQUIDATION_CASCADE_FORWARD.contract_hash,
        },
        "collection_contract_hash": canonical_hash(semantic_core),
    }


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Replace mutable status metadata only after it is durable and complete."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path.exists():
            temporary_path.unlink()


def _write_json_once(path: Path, payload: Mapping[str, Any]) -> bool:
    """Publish immutable metadata without replacing an existing target."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = -1
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return False
        _fsync_directory(path.parent)
        return True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path.exists():
            temporary_path.unlink()


def collection_contract_path(state_root: Path) -> Path:
    return state_root.expanduser().resolve() / "metadata" / "collection-contract.json"


def write_or_verify_collection_contract(
    state_root: Path,
    config: LiquidationCascadeCollectorConfig,
) -> dict[str, Any]:
    """Create a collection contract once, or reject a semantic configuration drift."""

    desired = build_collection_contract(config)
    target = collection_contract_path(state_root)
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="ascii"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CollectorConfigurationError("collection_contract_unreadable") from exc
        if not isinstance(existing, dict) or existing.get("collection_contract_hash") != desired[
            "collection_contract_hash"
        ]:
            raise CollectorConfigurationError("collection_contract_mismatch")
        return existing
    _write_json_once(target, desired)
    try:
        existing = json.loads(target.read_text(encoding="ascii"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorConfigurationError("collection_contract_write_failed") from exc
    if existing != desired:
        raise CollectorConfigurationError("collection_contract_race_or_mismatch")
    return existing


def _status_path(state_root: Path) -> Path:
    return state_root.expanduser().resolve() / "metadata" / "current.json"


def read_collection_status(state_root: Path) -> dict[str, Any]:
    path = _status_path(state_root)
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorConfigurationError("collection_status_unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != LIQUIDATION_CASCADE_COLLECTION_VERSION:
        raise CollectorConfigurationError("collection_status_invalid")
    return payload


def normalize_force_order_message(
    message: str | bytes | Mapping[str, Any],
    *,
    received_at_ms: int | None = None,
) -> dict[str, Any]:
    """Normalize one public ``forceOrder`` envelope while retaining source fields.

    Binance publishes the liquidation *order* side.  A filled ``SELL`` order
    closes a long position and a filled ``BUY`` order closes a short position;
    both the raw side and this explicit interpretation are retained.
    """

    if isinstance(message, bytes):
        message = message.decode("utf-8")
    if isinstance(message, str):
        envelope = json.loads(message)
    else:
        envelope = dict(message)
    if not isinstance(envelope, dict):
        raise ValueError("force_order_envelope_invalid")
    data = envelope.get("data", envelope)
    if not isinstance(data, dict) or data.get("e") != "forceOrder":
        raise ValueError("force_order_event_invalid")
    order = data.get("o")
    if not isinstance(order, dict):
        raise ValueError("force_order_payload_missing")
    symbol = str(order.get("s") or data.get("s") or "").upper()
    order_side = str(order.get("S") or "").upper()
    if not _SYMBOL_RE.fullmatch(symbol) or order_side not in {"BUY", "SELL"}:
        raise ValueError("force_order_identity_invalid")
    event_time_ms = _as_int(data.get("E"))
    transaction_time_ms = _as_int(order.get("T")) or _as_int(data.get("T"))
    source_order_id = str(order.get("i") or order.get("I") or "").strip() or None
    source_envelope = {
        "stream": str(envelope.get("stream") or f"{symbol.lower()}@forceOrder"),
        "data": data,
    }
    event_id = canonical_hash({"force_order": source_envelope})
    return {
        "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
        "record_type": "liquidation_event",
        "recorded_at_ms": int(received_at_ms if received_at_ms is not None else _now_ms()),
        "event_time_ms": event_time_ms,
        "transaction_time_ms": transaction_time_ms,
        "event_id": event_id,
        "source_order_id": source_order_id,
        "symbol": symbol,
        "liquidation_order_side": order_side,
        "liquidated_position_side": "long" if order_side == "SELL" else "short",
        "order_type": order.get("o"),
        "time_in_force": order.get("f"),
        "original_quantity": order.get("q"),
        "price": order.get("p"),
        "average_price": order.get("ap"),
        "last_filled_quantity": order.get("l"),
        "cumulative_filled_quantity": order.get("z"),
        "order_status": order.get("X"),
        "source_envelope": source_envelope,
    }


def build_gap_record(
    *,
    started_at_ms: int,
    ended_at_ms: int,
    reason: str,
    detail: str | None = None,
) -> dict[str, Any]:
    if started_at_ms < 0 or ended_at_ms < started_at_ms or not reason:
        raise ValueError("collection_gap_invalid")
    return {
        "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
        "record_type": "collection_gap",
        "recorded_at_ms": ended_at_ms,
        "gap_started_at_ms": started_at_ms,
        "gap_ended_at_ms": ended_at_ms,
        "gap_duration_ms": ended_at_ms - started_at_ms,
        "reason": reason,
        "detail": detail,
    }


def build_snapshot_records(
    *,
    kind: str,
    symbol: str,
    snapshot_started_at_ms: int,
    recorded_at_ms: int,
    source_payloads: Mapping[str, Any],
    source_errors: Mapping[str, str],
    trigger_event_ids: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Build raw context plus explicit error records for one snapshot attempt."""

    if kind not in {"periodic_snapshot", "event_snapshot"}:
        raise ValueError("collection_snapshot_kind_invalid")
    normalized_symbol = symbol.upper()
    if not _SYMBOL_RE.fullmatch(normalized_symbol):
        raise ValueError("collection_snapshot_symbol_invalid")
    unknown_sources = (set(source_payloads) | set(source_errors)) - set(_SNAPSHOT_SOURCES)
    if unknown_sources:
        raise ValueError("collection_snapshot_source_invalid")
    snapshot = {
        "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
        "record_type": kind,
        "recorded_at_ms": recorded_at_ms,
        "snapshot_started_at_ms": snapshot_started_at_ms,
        "symbol": normalized_symbol,
        "trigger_event_ids": list(trigger_event_ids),
        "source_payloads": dict(source_payloads),
        "complete": not source_errors and set(source_payloads) == set(_SNAPSHOT_SOURCES),
    }
    records = [snapshot]
    for source in _SNAPSHOT_SOURCES:
        error = source_errors.get(source)
        if error:
            records.append(
                {
                    "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
                    "record_type": "snapshot_error",
                    "recorded_at_ms": recorded_at_ms,
                    "snapshot_started_at_ms": snapshot_started_at_ms,
                    "snapshot_kind": kind,
                    "symbol": normalized_symbol,
                    "source": source,
                    "error": error,
                }
            )
    return records


class DiskGuard:
    """Rate-limited free-space guard shared by raw writes and the health loop."""

    def __init__(
        self,
        root: Path,
        *,
        min_free_bytes: int,
        interval_seconds: float,
        disk_usage: Callable[[str | Path], Any] | None = None,
    ) -> None:
        self.root = root
        self.min_free_bytes = min_free_bytes
        self.interval_seconds = interval_seconds
        self._disk_usage = disk_usage
        self._last_checked_at = 0.0

    def check(self, *, force: bool = False) -> None:
        if not self.min_free_bytes:
            return
        now = time.monotonic()
        if not force and now - self._last_checked_at < self.interval_seconds:
            return
        disk_usage = self._disk_usage or shutil.disk_usage
        free_bytes = disk_usage(self.root).free
        self._last_checked_at = now
        if free_bytes < self.min_free_bytes:
            raise DiskSpaceExhausted(
                "liquidation_cascade_disk_guard_tripped:"
                f"free_bytes={free_bytes}:minimum={self.min_free_bytes}:path={self.root}"
            )


class RecentEventDeduper:
    """Bounded event-fingerprint set persisted through current status metadata."""

    def __init__(self, *, max_items: int, initial_ids: tuple[str, ...] = ()) -> None:
        self.max_items = max_items
        self._items: OrderedDict[str, None] = OrderedDict()
        for event_id in initial_ids:
            if isinstance(event_id, str) and len(event_id) == 64:
                self._items[event_id] = None
        self._trim()

    def add_if_new(self, event_id: str) -> bool:
        if event_id in self._items:
            self._items.move_to_end(event_id)
            return False
        self._items[event_id] = None
        self._trim()
        return True

    def snapshot(self) -> list[str]:
        return list(self._items)

    def _trim(self) -> None:
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)


class AppendOnlyGzipSegment:
    """Write one new gzip segment, then atomically publish it without replacement."""

    def __init__(self, paths: SegmentPaths, disk_guard: DiskGuard) -> None:
        self.paths = paths
        self._disk_guard = disk_guard
        self.paths.partial_path.parent.mkdir(parents=True, exist_ok=True)
        if self.paths.partial_path.exists() or self.paths.completed_path.exists():
            raise FileExistsError("collection_segment_path_already_exists")
        self._disk_guard.check(force=True)
        self._raw_handle = self.paths.partial_path.open("xb")
        os.fchmod(self._raw_handle.fileno(), 0o600)
        self._gzip_handle = gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=self._raw_handle,
            compresslevel=6,
            mtime=0,
        )
        self._closed = False
        self.record_count = 0
        self.first_recorded_at_ms: int | None = None
        self.last_recorded_at_ms: int | None = None
        self._last_fsync_at = time.monotonic()

    def write(self, record: Mapping[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("collection_segment_closed")
        self._disk_guard.check()
        raw = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
        self._gzip_handle.write(raw)
        self._gzip_handle.flush(zlib.Z_SYNC_FLUSH)
        self._raw_handle.flush()
        now = time.monotonic()
        if now - self._last_fsync_at >= 5.0:
            os.fsync(self._raw_handle.fileno())
            self._last_fsync_at = now
        self.record_count += 1
        recorded_at_ms = _as_int(record.get("recorded_at_ms"))
        if recorded_at_ms is not None:
            self.first_recorded_at_ms = self.first_recorded_at_ms or recorded_at_ms
            self.last_recorded_at_ms = recorded_at_ms

    def close(self) -> Path:
        if self._closed:
            return self.paths.completed_path
        self._gzip_handle.close()
        self._raw_handle.flush()
        os.fsync(self._raw_handle.fileno())
        self._raw_handle.close()
        try:
            os.link(self.paths.partial_path, self.paths.completed_path)
        except FileExistsError as exc:
            raise FileExistsError("collection_segment_completed_path_already_exists") from exc
        _fsync_directory(self.paths.completed_path.parent)
        self.paths.partial_path.unlink()
        _fsync_directory(self.paths.completed_path.parent)
        self._closed = True
        return self.paths.completed_path

    def abandon(self) -> None:
        """Close descriptors but intentionally retain an unsealed partial segment."""

        if self._closed:
            return
        self._gzip_handle.close()
        self._raw_handle.close()
        self._closed = True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _segment_manifest_path(state_root: Path, completed_path: Path) -> Path:
    relative = Path(_relative_to_root(completed_path, state_root))
    return state_root.expanduser().resolve() / "metadata" / "segments" / relative.with_suffix(
        relative.suffix + ".json"
    )


def seal_closed_segment(state_root: Path, completed_path: Path) -> dict[str, Any]:
    """Verify a closed gzip stream and publish its immutable integrity manifest."""

    relative_path = _relative_to_root(completed_path, state_root)
    line_count = 0
    first_recorded_at_ms: int | None = None
    last_recorded_at_ms: int | None = None
    with gzip.open(completed_path, "rt", encoding="ascii") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("collection_segment_record_invalid")
            line_count += 1
            recorded_at_ms = _as_int(record.get("recorded_at_ms"))
            if recorded_at_ms is not None:
                first_recorded_at_ms = first_recorded_at_ms or recorded_at_ms
                last_recorded_at_ms = recorded_at_ms
    manifest_core = {
        "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
        "artifact_type": "liquidation_cascade_closed_segment",
        "relative_path": relative_path,
        "size_bytes": completed_path.stat().st_size,
        "sha256": _sha256_file(completed_path),
        "record_count": line_count,
        "first_recorded_at_ms": first_recorded_at_ms,
        "last_recorded_at_ms": last_recorded_at_ms,
        "compression": "gzip",
        "read_results_before_window": False,
        "orders_authorized": False,
    }
    manifest = manifest_core | {"manifest_hash": canonical_hash(manifest_core)}
    manifest_path = _segment_manifest_path(state_root, completed_path)
    if not _write_json_once(manifest_path, manifest):
        existing = json.loads(manifest_path.read_text(encoding="ascii"))
        if existing != manifest:
            raise CollectorConfigurationError("collection_segment_manifest_mismatch")
        return existing
    return manifest


class BinancePublicSnapshotClient:
    """Bounded public REST reader with an explicit no-proxy option."""

    def __init__(self, config: LiquidationCascadeCollectorConfig) -> None:
        self.config = config
        proxy_handler = urllib.request.ProxyHandler() if config.use_proxy_env else urllib.request.ProxyHandler({})
        self._opener = urllib.request.build_opener(proxy_handler)

    def _fetch_json(self, path: str, parameters: Mapping[str, str]) -> Any:
        url = f"{self.config.rest_base_url.rstrip('/')}{path}?{urlencode(parameters)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "qount-liquidation-cascade-forward/1"},
        )
        with self._opener.open(request, timeout=self.config.snapshot_timeout_seconds) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ValueError("snapshot_response_too_large")
        return json.loads(raw.decode("utf-8"))

    def capture(self, symbol: str) -> tuple[dict[str, Any], dict[str, str]]:
        """Fetch every source independently so an outage remains explicit per field."""

        requests = {
            "open_interest": ("/fapi/v1/openInterest", {"symbol": symbol}),
            "depth": ("/fapi/v1/depth", {"symbol": symbol, "limit": str(self.config.depth_limit)}),
            "premium_index": ("/fapi/v1/premiumIndex", {"symbol": symbol}),
        }
        payloads: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for source in _SNAPSHOT_SOURCES:
            path, parameters = requests[source]
            try:
                payload = self._fetch_json(path, parameters)
                if not isinstance(payload, dict):
                    raise ValueError("snapshot_response_not_object")
                payloads[source] = payload
            except Exception as exc:  # public network errors become append-only records
                errors[source] = f"{type(exc).__name__}:{exc}"
        return payloads, errors


class _EventSnapshotCoordinator:
    """Capture one immediate event snapshot per symbol, then coalesce bursts."""

    def __init__(
        self,
        *,
        min_interval_seconds: int,
        capture: Callable[[str, tuple[str, ...]], "asyncio.Future[None] | Any"],
    ) -> None:
        self._min_interval_seconds = min_interval_seconds
        self._capture = capture
        self._pending: dict[str, list[str]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._last_started_at: dict[str, float] = {}
        self._closed = False

    def schedule(self, symbol: str, event_id: str) -> None:
        if self._closed:
            return
        self._pending.setdefault(symbol, []).append(event_id)
        if symbol not in self._tasks:
            self._tasks[symbol] = asyncio.create_task(self._run(symbol), name=f"event-snapshot-{symbol}")

    async def _run(self, symbol: str) -> None:
        try:
            while self._pending.get(symbol):
                delay_seconds = max(
                    0.0,
                    self._min_interval_seconds - (time.monotonic() - self._last_started_at.get(symbol, -1e12)),
                )
                if delay_seconds:
                    await asyncio.sleep(delay_seconds)
                event_ids = tuple(self._pending.pop(symbol, []))
                if not event_ids:
                    continue
                self._last_started_at[symbol] = time.monotonic()
                await self._capture(symbol, event_ids)
        finally:
            self._tasks.pop(symbol, None)
            if not self._closed and self._pending.get(symbol):
                self._tasks[symbol] = asyncio.create_task(self._run(symbol), name=f"event-snapshot-{symbol}")

    async def close(self) -> None:
        self._closed = True
        self._pending.clear()
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


class _CollectionRootLock:
    """Reject a second collector before it can write competing forward records."""

    def __init__(self, state_root: Path) -> None:
        self.path = state_root / "metadata" / ".collector.lock"
        self._handle: Any | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="ascii")
        os.fchmod(handle.fileno(), 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise CollectorConfigurationError("collection_root_already_locked") from exc
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class LiquidationCascadeCollector:
    """Long-running, public-only collector for one fixed forward collection root."""

    def __init__(
        self,
        config: LiquidationCascadeCollectorConfig,
        *,
        snapshot_client: BinancePublicSnapshotClient | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.state_root = config.state_root.expanduser().resolve()
        self._snapshot_client = snapshot_client or BinancePublicSnapshotClient(config)
        self._disk_guard = DiskGuard(
            self.state_root,
            min_free_bytes=config.min_free_disk_bytes,
            interval_seconds=config.disk_check_interval_seconds,
        )
        self._session_id = f"{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}-p{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._segment_sequence = 0
        self._segment: AppendOnlyGzipSegment | None = None
        self._contract: dict[str, Any] | None = None
        self._deduper = RecentEventDeduper(max_items=config.max_recent_event_ids)
        self._started_at_ms: int | None = None
        self._last_recorded_at_ms: int | None = None
        self._last_stream_message_at_ms: int | None = None
        self._last_connection_opened_at_ms: int | None = None
        self._last_error: str | None = None
        self._terminal_error: Exception | None = None
        self._counters: dict[str, int] = {
            "liquidation_events": 0,
            "deduplicated_events": 0,
            "periodic_snapshots": 0,
            "event_snapshots": 0,
            "snapshot_errors": 0,
            "connection_opens": 0,
            "connection_errors": 0,
            "gap_records": 0,
        }
        self._event_snapshots = _EventSnapshotCoordinator(
            min_interval_seconds=config.event_snapshot_min_interval_seconds,
            capture=self._capture_event_snapshot,
        )
        self._root_lock = _CollectionRootLock(self.state_root)

    def _new_segment(self, recorded_at_ms: int) -> AppendOnlyGzipSegment:
        paths = build_segment_paths(
            self.state_root,
            recorded_at_ms=recorded_at_ms,
            rotation_seconds=self.config.segment_rotation_seconds,
            session_id=self._session_id,
            sequence=self._segment_sequence,
        )
        self._segment_sequence += 1
        return AppendOnlyGzipSegment(paths, self._disk_guard)

    def _close_segment(self) -> None:
        if self._segment is None:
            return
        completed_path = self._segment.close()
        seal_closed_segment(self.state_root, completed_path)
        self._segment = None

    def _ensure_segment(self, recorded_at_ms: int) -> AppendOnlyGzipSegment:
        if self._segment is not None and recorded_at_ms >= self._segment.paths.bucket_ends_at_ms:
            self._close_segment()
        if self._segment is None:
            self._segment = self._new_segment(recorded_at_ms)
        return self._segment

    def _record(self, record: Mapping[str, Any]) -> None:
        recorded_at_ms = _as_int(record.get("recorded_at_ms"))
        if recorded_at_ms is None:
            raise ValueError("collection_record_missing_timestamp")
        self._ensure_segment(recorded_at_ms).write(record)
        self._last_recorded_at_ms = recorded_at_ms
        record_type = str(record.get("record_type") or "")
        if record_type == "snapshot_error":
            self._counters["snapshot_errors"] += 1
        elif record_type == "collection_gap":
            self._counters["gap_records"] += 1

    def _current_status(self, status: str, *, stopped_at_ms: int | None = None) -> dict[str, Any]:
        active_segment = None
        if self._segment is not None:
            active_segment = _relative_to_root(self._segment.paths.partial_path, self.state_root)
        contract_hash = self._contract.get("collection_contract_hash") if self._contract else None
        return {
            "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
            "artifact_type": "liquidation_cascade_collector_status",
            "updated_at_ms": _now_ms(),
            "status": status,
            "session_id": self._session_id,
            "started_at_ms": self._started_at_ms,
            "stopped_at_ms": stopped_at_ms,
            "last_recorded_at_ms": self._last_recorded_at_ms,
            "last_stream_message_at_ms": self._last_stream_message_at_ms,
            "last_connection_opened_at_ms": self._last_connection_opened_at_ms,
            "last_error": self._last_error,
            "collection_contract_hash": contract_hash,
            "active_partial_segment": active_segment,
            "counters": dict(self._counters),
            "recent_event_ids": self._deduper.snapshot(),
            "research_guards": {
                "independent_window_days": LIQUIDATION_CASCADE_FORWARD.independent_window_days,
                "read_results_before_window": False,
                "orders_authorized": False,
                "private_api_used": False,
                "pnl_evaluated": False,
                "signal_generated": False,
            },
        }

    def _publish_status(self, status: str, *, stopped_at_ms: int | None = None) -> None:
        _atomic_write_json(_status_path(self.state_root), self._current_status(status, stopped_at_ms=stopped_at_ms))

    def _restore_previous_status(self) -> None:
        try:
            previous = read_collection_status(self.state_root)
        except FileNotFoundError:
            return
        previous_hash = previous.get("collection_contract_hash")
        if self._contract is None or previous_hash != self._contract.get("collection_contract_hash"):
            raise CollectorConfigurationError("collection_previous_status_contract_mismatch")
        prior_ids = previous.get("recent_event_ids", [])
        if isinstance(prior_ids, list):
            self._deduper = RecentEventDeduper(
                max_items=self.config.max_recent_event_ids,
                initial_ids=tuple(item for item in prior_ids if isinstance(item, str)),
            )
        previous_activity = _as_int(previous.get("stopped_at_ms")) or _as_int(previous.get("last_recorded_at_ms"))
        if previous_activity is not None and self._started_at_ms is not None and previous_activity < self._started_at_ms:
            self._record(
                build_gap_record(
                    started_at_ms=previous_activity,
                    ended_at_ms=self._started_at_ms,
                    reason="collector_restart",
                    detail=str(previous.get("status") or "unknown"),
                )
            )

    def _record_unsealed_partials(self) -> None:
        raw_root = self.state_root / "raw"
        if not raw_root.exists():
            return
        for partial_path in sorted(raw_root.rglob("*.partial")):
            self._record(
                {
                    "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
                    "record_type": "unsealed_partial_detected",
                    "recorded_at_ms": _now_ms(),
                    "relative_path": _relative_to_root(partial_path, self.state_root),
                    "size_bytes": partial_path.stat().st_size,
                    "action": "preserved_without_resume_or_overwrite",
                }
            )

    async def _capture_snapshot(
        self,
        symbol: str,
        *,
        kind: str,
        trigger_event_ids: tuple[str, ...] = (),
    ) -> None:
        started_at_ms = _now_ms()
        try:
            payloads, errors = await asyncio.to_thread(self._snapshot_client.capture, symbol)
        except Exception as exc:  # defensive boundary around custom or future clients
            payloads = {}
            errors = {"open_interest": f"{type(exc).__name__}:{exc}"}
        records = build_snapshot_records(
            kind=kind,
            symbol=symbol,
            snapshot_started_at_ms=started_at_ms,
            recorded_at_ms=_now_ms(),
            source_payloads=payloads,
            source_errors=errors,
            trigger_event_ids=trigger_event_ids,
        )
        for record in records:
            self._record(record)
        counter_key = "periodic_snapshots" if kind == "periodic_snapshot" else "event_snapshots"
        self._counters[counter_key] += 1

    async def _capture_event_snapshot(self, symbol: str, event_ids: tuple[str, ...]) -> None:
        await self._capture_snapshot(symbol, kind="event_snapshot", trigger_event_ids=event_ids)

    async def _periodic_snapshot_loop(self, stop_event: asyncio.Event) -> None:
        next_capture_at = time.monotonic()
        while not stop_event.is_set():
            await asyncio.gather(
                *(self._capture_snapshot(symbol, kind="periodic_snapshot") for symbol in self.config.symbols),
                return_exceptions=False,
            )
            next_capture_at += self.config.snapshot_interval_seconds
            delay_seconds = max(0.0, next_capture_at - time.monotonic())
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay_seconds)
            except TimeoutError:
                continue

    async def _health_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                self._disk_guard.check(force=True)
                self._publish_status("running")
            except DiskSpaceExhausted as exc:
                self._terminal_error = exc
                self._last_error = str(exc)
                stop_event.set()
                return
            except Exception as exc:
                self._last_error = f"status_publish:{type(exc).__name__}:{exc}"
                raise
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=min(self.config.disk_check_interval_seconds, 60.0))
            except TimeoutError:
                continue

    async def _stream_once(self, stop_event: asyncio.Event, gap_started_at_ms: int | None) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:  # pragma: no cover - optional runtime extra
            raise CollectorConfigurationError("collector_requires_websockets_optional_extra") from exc
        async with connect(
            build_force_order_stream_url(self.config),
            open_timeout=20,
            close_timeout=10,
            ping_interval=20,
            ping_timeout=20,
            max_size=2 * 1024 * 1024,
            proxy=True if self.config.use_proxy_env else None,
        ) as websocket:
            opened_at_ms = _now_ms()
            self._last_connection_opened_at_ms = opened_at_ms
            self._counters["connection_opens"] += 1
            self._record(
                {
                    "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
                    "record_type": "stream_connection_open",
                    "recorded_at_ms": opened_at_ms,
                    "stream_url": build_force_order_stream_url(self.config),
                }
            )
            if gap_started_at_ms is not None and gap_started_at_ms < opened_at_ms:
                self._record(
                    build_gap_record(
                        started_at_ms=gap_started_at_ms,
                        ended_at_ms=opened_at_ms,
                        reason="websocket_reconnect",
                    )
                )
            while not stop_event.is_set():
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=self.config.receive_timeout_seconds)
                except TimeoutError:
                    continue
                received_at_ms = _now_ms()
                self._last_stream_message_at_ms = received_at_ms
                try:
                    record = normalize_force_order_message(message, received_at_ms=received_at_ms)
                except Exception as exc:
                    self._record(
                        {
                            "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
                            "record_type": "stream_parse_error",
                            "recorded_at_ms": received_at_ms,
                            "error": f"{type(exc).__name__}:{exc}",
                        }
                    )
                    continue
                if not self._deduper.add_if_new(record["event_id"]):
                    self._counters["deduplicated_events"] += 1
                    continue
                self._record(record)
                self._counters["liquidation_events"] += 1
                self._event_snapshots.schedule(record["symbol"], record["event_id"])

    async def _stream_loop(self, stop_event: asyncio.Event) -> None:
        gap_started_at_ms: int | None = None
        while not stop_event.is_set():
            try:
                await self._stream_once(stop_event, gap_started_at_ms)
                if stop_event.is_set():
                    return
                gap_started_at_ms = _now_ms()
                raise RuntimeError("websocket_closed_without_stop")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                now_ms = _now_ms()
                gap_started_at_ms = gap_started_at_ms or now_ms
                self._counters["connection_errors"] += 1
                self._last_error = f"websocket:{type(exc).__name__}:{exc}"
                self._record(
                    {
                        "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
                        "record_type": "stream_connection_error",
                        "recorded_at_ms": now_ms,
                        "error": self._last_error,
                    }
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=self.config.reconnect_delay_seconds)
                except TimeoutError:
                    continue

    async def _wait_for_stop_or_task_failure(
        self,
        stop_event: asyncio.Event,
        tasks: list[asyncio.Task[None]],
    ) -> None:
        stop_wait = asyncio.create_task(stop_event.wait(), name="liquidation-stop-wait")
        try:
            done, _ = await asyncio.wait([stop_wait, *tasks], return_when=asyncio.FIRST_COMPLETED)
            if stop_wait in done:
                return
            for task in done:
                if task is stop_wait:
                    continue
                task.result()
        finally:
            if not stop_wait.done():
                stop_wait.cancel()
            await asyncio.gather(stop_wait, return_exceptions=True)

    async def run(self, *, run_seconds: float = 0.0) -> dict[str, Any]:
        """Run until a signal/timeout, preserving any terminal disk outcome."""

        if run_seconds < 0:
            raise CollectorConfigurationError("collection_run_seconds_invalid")
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._disk_guard.check(force=True)
        self._root_lock.acquire()
        try:
            self._contract = write_or_verify_collection_contract(self.state_root, self.config)
            self._started_at_ms = _now_ms()
            self._restore_previous_status()
            self._record_unsealed_partials()
            self._record(
                {
                    "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
                    "record_type": "collector_started",
                    "recorded_at_ms": self._started_at_ms,
                    "session_id": self._session_id,
                    "collection_contract_hash": self._contract["collection_contract_hash"],
                    "collector_module_sha256": _module_source_hash(),
                }
            )
            self._publish_status("starting")
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            signal_handlers_added = []
            for signal_name in ("SIGINT", "SIGTERM"):
                signal_value = getattr(__import__("signal"), signal_name)
                try:
                    loop.add_signal_handler(signal_value, stop_event.set)
                    signal_handlers_added.append(signal_value)
                except (NotImplementedError, RuntimeError):  # pragma: no cover - Windows / embedded loop
                    pass
            tasks = [
                asyncio.create_task(self._stream_loop(stop_event), name="liquidation-force-order-stream"),
                asyncio.create_task(self._periodic_snapshot_loop(stop_event), name="liquidation-periodic-snapshots"),
                asyncio.create_task(self._health_loop(stop_event), name="liquidation-collector-health"),
            ]
            timeout_task: asyncio.Task[None] | None = None
            if run_seconds:
                timeout_task = asyncio.create_task(
                    self._stop_after(stop_event, run_seconds), name="liquidation-run-timeout"
                )
            run_error: BaseException | None = None
            try:
                await self._wait_for_stop_or_task_failure(stop_event, tasks)
            except BaseException as exc:
                run_error = exc
                if isinstance(exc, DiskSpaceExhausted):
                    self._terminal_error = exc
                self._last_error = self._last_error or f"task_failure:{type(exc).__name__}:{exc}"
                stop_event.set()
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if timeout_task is not None:
                    timeout_task.cancel()
                    await asyncio.gather(timeout_task, return_exceptions=True)
                await self._event_snapshots.close()
                stopped_at_ms = _now_ms()
                status = "terminal_disk_low" if isinstance(self._terminal_error, DiskSpaceExhausted) else "stopped"
                try:
                    self._record(
                        {
                            "schema_version": LIQUIDATION_CASCADE_COLLECTION_VERSION,
                            "record_type": "collector_stopped",
                            "recorded_at_ms": stopped_at_ms,
                            "reason": status,
                        }
                    )
                finally:
                    try:
                        self._close_segment()
                    finally:
                        self._publish_status(status, stopped_at_ms=stopped_at_ms)
                for signal_value in signal_handlers_added:
                    loop.remove_signal_handler(signal_value)
            if self._terminal_error is not None:
                raise self._terminal_error
            if run_error is not None:
                raise run_error
            return self._current_status("stopped", stopped_at_ms=_now_ms())
        finally:
            self._root_lock.release()

    @staticmethod
    async def _stop_after(stop_event: asyncio.Event, seconds: float) -> None:
        await asyncio.sleep(seconds)
        stop_event.set()


async def run_liquidation_cascade_collector(
    config: LiquidationCascadeCollectorConfig,
    *,
    run_seconds: float = 0.0,
) -> dict[str, Any]:
    return await LiquidationCascadeCollector(config).run(run_seconds=run_seconds)
