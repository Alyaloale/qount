"""Deterministic remediation helpers for stablecoin chain-event G0 sources.

The module is research-only. It reads public chain and verified-contract data,
never market prices, account state, positions, strategy results, or orders.
Large active checkpoints belong on WSL ext4; immutable completed artifacts are
published to the external evidence store by the CLI.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any

from qount.contracts import canonical_hash
from qount.mini_trend.stablecoin_chain_events import (
    DEFAULT_ETHEREUM_RPC_URL,
    DEFAULT_TRONGRID_URL,
    EthereumRpc,
    PublicChainCollectionError,
)
from qount.mini_trend.stablecoin_impulse_g0 import (
    SOURCE_SPECS,
    STABLECOIN_CHAIN_SOURCE_VERSION,
)


STABLECOIN_REMEDIATION_VERSION = "stablecoin_chain_event_remediation_v0.2"
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
USDC_UPGRADED_TOPIC = (
    "0xbc7cd75a20ee27fd9adebab32041f755214dbc6bffa90cc0225b39da2e5c2d3b"
)
ETHEREUM_AVAILABILITY_POLICY = "ethereum_event_block_plus_64"
TRON_AVAILABILITY_POLICY = "tron_event_producer_plus_18_distinct_srs"
TRONSCAN_BLOCK_API = "https://apilist.tronscanapi.com/api/block"
TRON_USDT_BASE58 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRON_ZERO_BASE58 = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"
TRON_INITIAL_OWNER = "THPvaUhoh2Qn2y9THCZML3H815hhFhn5YC"
TRON_SECOND_OWNER = "TBPxhVAsuzoFnKyXtc1o2UySEydPHgATto"
USDC_IMPLEMENTATION_SLOT = (
    "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3"
)
USDT_ETHEREUM_INITIAL_OWNER = "0x36928500bc1dcd7af6a2b4008875cc336b927d57"
USDT_ETHEREUM_MULTISIG_OWNER = "0xc6cde7c39eb2f0f0095f41570af89efc2c1ea828"
TRANSFER_OWNERSHIP_SELECTOR = "0xf2fde38b"
MULTISIG_TRANSACTION_COUNT_SELECTOR = "0xb77bf600"
MULTISIG_TRANSACTIONS_SELECTOR = "0x9ace38c2"

_ALLOWED_EVIDENCE_HOSTS = frozenset(
    {
        "api.trongrid.io",
        "apilist.tronscanapi.com",
        "developers.circle.com",
        "developers.tron.network",
        "ethereum.org",
        "rpc.mevblocker.io",
        "sourcify.dev",
        "tether.to",
    }
)
_HEX = frozenset("0123456789abcdef")
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_JSON_ENCODER = json.JSONEncoder(
    ensure_ascii=True,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
)


class StablecoinRemediationError(RuntimeError):
    """Raised when source remediation cannot make an exact evidence claim."""


def canonical_json_bytes(value: object, *, newline: bool = False) -> bytes:
    raw = _JSON_ENCODER.encode(value).encode("ascii")
    return raw + (b"\n" if newline else b"")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in _HEX for char in value.lower())
    )


def utc_text(timestamp: int | float) -> str:
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_utc_ms(value: str) -> int:
    rendered = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(rendered)
    if parsed.tzinfo is None:
        raise ValueError("timestamp_timezone_missing")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _validate_https_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _ALLOWED_EVIDENCE_HOSTS:
        raise ValueError(f"stablecoin_evidence_url_not_allowed:{host}")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("stablecoin_evidence_url_credentials_or_fragment")
    return host


class PublicEvidenceClient:
    """Bounded allowlisted fetcher with optional repo-external proxy routing."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        attempts: int = 6,
        minimum_interval_seconds: float = 0.0,
        proxy_url: str | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts
        self.minimum_interval_seconds = minimum_interval_seconds
        self.last_request_at = 0.0
        proxy_config: dict[str, str] = {}
        if proxy_url:
            parsed = urllib.parse.urlparse(proxy_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("stablecoin_proxy_url_invalid")
            proxy_config = {"http": proxy_url, "https": proxy_url}
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(proxy_config)
        )

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: object | None = None,
    ) -> bytes:
        _validate_https_url(url)
        body = None if payload is None else canonical_json_bytes(payload)
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "Content-Type": "application/json",
                "User-Agent": "qount-stablecoin-remediation/0.1",
            },
        )
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            wait_for = self.minimum_interval_seconds - (
                time.monotonic() - self.last_request_at
            )
            if wait_for > 0:
                time.sleep(wait_for)
            try:
                self.last_request_at = time.monotonic()
                with self.opener.open(
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    raw = response.read()
                if not raw:
                    raise StablecoinRemediationError("empty_public_evidence_response")
                return raw
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read(512).decode("utf-8", errors="replace")
                except OSError:
                    detail = ""
                last_error = StablecoinRemediationError(
                    f"http_{exc.code}:{detail[:256]}"
                )
            except OSError as exc:
                last_error = exc
            if attempt + 1 < self.attempts:
                time.sleep(min(2**attempt, 30))
        raise StablecoinRemediationError(
            f"public_evidence_fetch_failed:{type(last_error).__name__}:{last_error}"
        )

    def json(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: object | None = None,
    ) -> Any:
        last_error: str | None = None
        for attempt in range(self.attempts):
            raw = self.fetch(url, method=method, payload=payload)
            try:
                result = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise StablecoinRemediationError(
                    "public_evidence_response_not_json"
                ) from exc
            if isinstance(result, Mapping):
                api_error = result.get("Error")
                message_error = (
                    result.get("message")
                    if not any(
                        key in result
                        for key in ("data", "token_transfers", "success", "status")
                    )
                    else None
                )
                if api_error or message_error:
                    last_error = str(api_error or message_error)
                    if attempt + 1 < self.attempts:
                        time.sleep(min(5 * (attempt + 1), 60))
                        continue
                    break
            return result
        raise StablecoinRemediationError(
            f"public_evidence_api_error:{last_error}"
        )


def write_immutable_bytes(path: Path, raw: bytes) -> bool:
    """Write bytes once; return True when an identical file already existed."""

    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise StablecoinRemediationError(
                f"immutable_evidence_mismatch:{path.name}"
            )
        return True
    partial = path.with_name(f".{path.name}.partial")
    if partial.exists():
        partial.unlink()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)
    if path.read_bytes() != raw:
        raise StablecoinRemediationError(f"evidence_readback_mismatch:{path.name}")
    return False


def evidence_reference(path: Path, *, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "path": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


@dataclass(frozen=True)
class NdjsonReference:
    path: str
    record_count: int
    size_bytes: int
    sha256: str
    uncompressed_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "format": "canonical_ndjson",
            "compression": "gzip_mtime_zero",
            "record_count": self.record_count,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "uncompressed_sha256": self.uncompressed_sha256,
        }


class DeterministicGzipNdjsonWriter(AbstractContextManager[Any]):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.partial = path.with_name(f".{path.name}.partial")
        self.raw_handle: Any = None
        self.gzip_handle: Any = None
        self.digest = hashlib.sha256()
        self.record_count = 0

    def __enter__(self) -> "DeterministicGzipNdjsonWriter":
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.path.exists() or self.partial.exists():
            raise FileExistsError(self.path)
        self.raw_handle = self.partial.open("xb")
        self.gzip_handle = gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=self.raw_handle,
            mtime=0,
        )
        return self

    def write(self, value: Mapping[str, Any]) -> None:
        if self.gzip_handle is None:
            raise RuntimeError("ndjson_writer_not_open")
        line = canonical_json_bytes(value, newline=True)
        self.gzip_handle.write(line)
        self.digest.update(line)
        self.record_count += 1

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if self.gzip_handle is not None:
            self.gzip_handle.close()
        if self.raw_handle is not None:
            self.raw_handle.flush()
            os.fsync(self.raw_handle.fileno())
            self.raw_handle.close()
        if exc_type is not None:
            return False
        os.replace(self.partial, self.path)
        return False

    def reference(self) -> NdjsonReference:
        if not self.path.is_file():
            raise RuntimeError("ndjson_writer_not_finalized")
        return NdjsonReference(
            path=self.path.name,
            record_count=self.record_count,
            size_bytes=self.path.stat().st_size,
            sha256=file_sha256(self.path),
            uncompressed_sha256=self.digest.hexdigest(),
        )


def iter_verified_gzip_ndjson(
    path: Path,
    reference: Mapping[str, Any],
) -> Iterator[Mapping[str, Any]]:
    if (
        not path.is_file()
        or path.stat().st_size != reference.get("size_bytes")
        or file_sha256(path) != reference.get("sha256")
    ):
        raise StablecoinRemediationError(f"input_sidecar_hash_mismatch:{path.name}")
    digest = hashlib.sha256()
    count = 0
    with gzip.open(path, "rb") as handle:
        for line in handle:
            digest.update(line)
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StablecoinRemediationError(
                    f"input_sidecar_json_invalid:{path.name}:{count}"
                ) from exc
            if not isinstance(row, Mapping):
                raise StablecoinRemediationError(
                    f"input_sidecar_row_not_object:{path.name}:{count}"
                )
            count += 1
            yield row
    if (
        count != reference.get("record_count")
        or digest.hexdigest() != reference.get("uncompressed_sha256")
    ):
        raise StablecoinRemediationError(
            f"input_sidecar_content_mismatch:{path.name}"
        )


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise StablecoinRemediationError(f"json_artifact_invalid:{path.name}") from exc
    if not isinstance(payload, dict):
        raise StablecoinRemediationError(f"json_artifact_not_object:{path.name}")
    return payload


def verify_v01_collection(
    directory: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest_path = directory / "manifest.json"
    manifest = read_json_object(manifest_path)
    manifest_core = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if manifest.get("manifest_hash") != canonical_hash(manifest_core):
        raise StablecoinRemediationError("v01_manifest_hash_invalid")
    if (
        manifest.get("artifact_type")
        != "stablecoin_native_supply_event_collection"
        or manifest.get("scope") != "native_supply_events_only"
        or manifest.get("market_data_read") is not False
        or manifest.get("strategy_results_read") is not False
        or manifest.get("orders_authorized") is not False
    ):
        raise StablecoinRemediationError("v01_manifest_contract_invalid")
    source_payloads: dict[str, dict[str, Any]] = {}
    for reference in manifest.get("source_files", []):
        if not isinstance(reference, Mapping):
            raise StablecoinRemediationError("v01_source_reference_invalid")
        source_id = str(reference.get("source_id", ""))
        if source_id in source_payloads:
            raise StablecoinRemediationError("v01_source_reference_duplicate")
        path = directory / Path(str(reference.get("path", ""))).name
        if (
            not path.is_file()
            or path.stat().st_size != reference.get("size_bytes")
            or file_sha256(path) != reference.get("sha256")
        ):
            raise StablecoinRemediationError(f"v01_source_hash_invalid:{source_id}")
        payload = read_json_object(path)
        if (
            payload.get("schema_version")
            != "stablecoin_chain_event_source_v0.1"
            or payload.get("source_id") != source_id
        ):
            raise StablecoinRemediationError(f"v01_source_schema_invalid:{source_id}")
        source_payloads[source_id] = payload
    expected_ids = {spec.source_id for spec in SOURCE_SPECS}
    if set(source_payloads) != expected_ids:
        raise StablecoinRemediationError("v01_source_set_invalid")
    artifact_references = manifest.get("event_artifacts", [])
    if not isinstance(artifact_references, list) or len(artifact_references) != 6:
        raise StablecoinRemediationError("v01_event_artifact_set_invalid")
    manifest_artifacts = {
        (str(row.get("source_id")), str(row.get("role"))): row
        for row in artifact_references
        if isinstance(row, Mapping)
    }
    for source_id, payload in source_payloads.items():
        collection = payload.get("collection", {})
        if not isinstance(collection, Mapping):
            raise StablecoinRemediationError(
                f"v01_collection_not_object:{source_id}"
            )
        for role, key in (
            ("normalized_chain_events", "normalized_event_artifact"),
            ("raw_provider_events", "raw_event_artifact"),
        ):
            source_reference = collection.get(key)
            manifest_reference = manifest_artifacts.get((source_id, role))
            if (
                not isinstance(source_reference, Mapping)
                or not isinstance(manifest_reference, Mapping)
                or any(
                    source_reference.get(field) != manifest_reference.get(field)
                    for field in (
                        "path",
                        "record_count",
                        "size_bytes",
                        "sha256",
                        "uncompressed_sha256",
                    )
                )
            ):
                raise StablecoinRemediationError(
                    f"v01_event_reference_mismatch:{source_id}:{role}"
                )
    return manifest, source_payloads


class EventStore(AbstractContextManager[Any]):
    """Resume-safe normalized/raw event checkpoint bound to one v0.1 manifest."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> "EventStore":
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                source_id TEXT NOT NULL,
                chain TEXT NOT NULL,
                block_number INTEGER NOT NULL,
                transaction_hash TEXT NOT NULL,
                event_index INTEGER NOT NULL,
                event_name TEXT NOT NULL,
                event_family TEXT NOT NULL,
                normalized_json TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                row_hash TEXT NOT NULL,
                origin TEXT NOT NULL,
                PRIMARY KEY (source_id, transaction_hash, event_index)
            )
            """
        )
        self.connection.execute(
            """
            CREATE INDEX IF NOT EXISTS events_source_block
            ON events(source_id, block_number, transaction_hash, event_index)
            """
        )
        self.connection.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS pending_event_hashes (
                source_id TEXT NOT NULL,
                transaction_hash TEXT NOT NULL,
                event_index INTEGER NOT NULL,
                row_hash TEXT NOT NULL,
                PRIMARY KEY (source_id, transaction_hash, event_index)
            ) WITHOUT ROWID
            """
        )
        self.connection.commit()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if self.connection is not None:
            self.connection.close()
        return False

    @property
    def db(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("event_store_not_open")
        return self.connection

    def bind_manifest(self, manifest_hash: str) -> None:
        row = self.db.execute(
            "SELECT value FROM metadata WHERE key='v01_manifest_hash'"
        ).fetchone()
        if row is not None and row[0] != manifest_hash:
            raise StablecoinRemediationError("event_store_manifest_conflict")
        self.db.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)",
            ("v01_manifest_hash", manifest_hash),
        )
        self.db.commit()

    @staticmethod
    def _record(
        source_id: str,
        chain: str,
        normalized: Mapping[str, Any],
        raw: Mapping[str, Any],
        origin: str,
    ) -> tuple[Any, ...]:
        transaction_hash = str(normalized.get("transaction_hash", "")).lower()
        event_name = str(normalized.get("event_name", "")).lower()
        block_number = int(normalized["block_number"])
        event_index = int(normalized["event_index"])
        if not transaction_hash or not event_name or block_number < 0 or event_index < 0:
            raise StablecoinRemediationError("event_store_row_identity_invalid")
        if event_name in {"issue", "redeem", "mint", "burn"}:
            family = "native_supply"
        elif event_name == "transfer":
            from_address = str(normalized.get("from_address", "")).lower()
            to_address = str(normalized.get("to_address", "")).lower()
            zero_addresses = {
                "0x0000000000000000000000000000000000000000",
                TRON_ZERO_BASE58.lower(),
            }
            family = (
                "zero_transfer"
                if from_address in zero_addresses or to_address in zero_addresses
                else "treasury_transfer"
            )
        else:
            raise StablecoinRemediationError("event_store_event_name_invalid")
        normalized_json = canonical_json_bytes(normalized).decode("ascii")
        raw_json = canonical_json_bytes(raw).decode("ascii")
        row_hash = canonical_hash(
            {"normalized": normalized, "raw": raw, "origin": origin}
        )
        return (
            source_id,
            chain,
            block_number,
            transaction_hash,
            event_index,
            event_name,
            family,
            normalized_json,
            raw_json,
            row_hash,
            origin,
        )

    def add_many(
        self,
        source_id: str,
        chain: str,
        rows: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
        *,
        origin: str,
        batch_size: int = 5_000,
    ) -> int:
        pending: list[tuple[Any, ...]] = []
        inserted = 0

        def flush() -> None:
            nonlocal inserted
            if not pending:
                return
            self.db.execute("DELETE FROM pending_event_hashes")
            try:
                self.db.executemany(
                    """
                    INSERT INTO pending_event_hashes(
                        source_id, transaction_hash, event_index, row_hash
                    ) VALUES (?, ?, ?, ?)
                    """,
                    ((row[0], row[3], row[4], row[9]) for row in pending),
                )
            except sqlite3.IntegrityError as exc:
                raise StablecoinRemediationError(
                    "event_store_pending_identity_duplicate"
                ) from exc
            before = self.db.total_changes
            self.db.executemany(
                """
                INSERT OR IGNORE INTO events(
                    source_id, chain, block_number, transaction_hash,
                    event_index, event_name, event_family, normalized_json,
                    raw_json, row_hash, origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                pending,
            )
            inserted += self.db.total_changes - before
            conflict = self.db.execute(
                """
                SELECT 1
                FROM pending_event_hashes AS pending
                LEFT JOIN events AS existing
                  ON existing.source_id=pending.source_id
                 AND existing.transaction_hash=pending.transaction_hash
                 AND existing.event_index=pending.event_index
                WHERE existing.row_hash IS NULL
                   OR existing.row_hash<>pending.row_hash
                LIMIT 1
                """
            ).fetchone()
            if conflict is not None:
                raise StablecoinRemediationError("event_store_identity_conflict")
            self.db.commit()
            pending.clear()

        for normalized, raw in rows:
            pending.append(self._record(source_id, chain, normalized, raw, origin))
            if len(pending) >= batch_size:
                flush()
        flush()
        return inserted

    def count(self, source_id: str, *, event_family: str | None = None) -> int:
        if event_family is None:
            row = self.db.execute(
                "SELECT COUNT(*) FROM events WHERE source_id=?", (source_id,)
            ).fetchone()
        else:
            row = self.db.execute(
                """
                SELECT COUNT(*) FROM events
                WHERE source_id=? AND event_family=?
                """,
                (source_id, event_family),
            ).fetchone()
        return int(row[0])

    def amount_accounting(
        self,
        source_id: str,
        *,
        event_family: str | None = None,
    ) -> dict[str, int]:
        parameters: list[Any] = [source_id]
        clause = ""
        if event_family is not None:
            clause = " AND event_family=?"
            parameters.append(event_family)
        row = self.db.execute(
            f"""
            SELECT
                COUNT(*),
                COALESCE(SUM(
                    CASE WHEN COALESCE(
                        json_extract(normalized_json, '$.raw_amount'),
                        json_extract(normalized_json, '$.amount')
                    ) IN ('0', 0, 0.0) THEN 1 ELSE 0 END
                ), 0)
            FROM events
            WHERE source_id=?{clause}
            """,
            parameters,
        ).fetchone()
        lineage = int(row[0])
        zero_amount = int(row[1])
        return {
            "lineage_event_count": lineage,
            "economic_event_count": lineage - zero_amount,
            "zero_amount_event_count_excluded": zero_amount,
        }

    def iter_events(
        self,
        source_id: str,
        *,
        event_family: str | None = None,
    ) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
        parameters: list[Any] = [source_id]
        clause = ""
        if event_family is not None:
            clause = " AND event_family=?"
            parameters.append(event_family)
        cursor = self.db.execute(
            f"""
            SELECT normalized_json, raw_json FROM events
            WHERE source_id=?{clause}
            ORDER BY block_number, transaction_hash, event_index
            """,
            parameters,
        )
        for normalized_json, raw_json in cursor:
            yield json.loads(normalized_json), json.loads(raw_json)

    def block_numbers(self, source_id: str) -> Iterator[int]:
        cursor = self.db.execute(
            """
            SELECT DISTINCT block_number FROM events
            WHERE source_id=? ORDER BY block_number
            """,
            (source_id,),
        )
        for (block_number,) in cursor:
            yield int(block_number)


def ingest_v01_collection(
    directory: Path,
    store: EventStore,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest, source_payloads = verify_v01_collection(directory)
    store.bind_manifest(str(manifest["manifest_hash"]))
    for source_id, payload in source_payloads.items():
        spec = source_spec(source_id)
        collection = payload["collection"]
        normalized_reference = collection["normalized_event_artifact"]
        raw_reference = collection["raw_event_artifact"]
        normalized_rows = iter_verified_gzip_ndjson(
            directory / normalized_reference["path"], normalized_reference
        )
        raw_rows = iter_verified_gzip_ndjson(
            directory / raw_reference["path"], raw_reference
        )

        def paired_rows() -> Iterator[
            tuple[Mapping[str, Any], Mapping[str, Any]]
        ]:
            sentinel = object()
            for normalized, raw in zip_longest(
                normalized_rows,
                raw_rows,
                fillvalue=sentinel,
            ):
                if normalized is sentinel or raw is sentinel:
                    raise StablecoinRemediationError(
                        f"v01_normalized_raw_count_mismatch:{source_id}"
                    )
                assert isinstance(normalized, Mapping)
                assert isinstance(raw, Mapping)
                yield normalized, raw

        store.add_many(
            source_id,
            spec.chain,
            paired_rows(),
            origin="v01_native_supply",
        )
        expected_count = int(collection["raw_event_count"])
        if store.count(source_id, event_family="native_supply") != expected_count:
            raise StablecoinRemediationError(
                f"v01_ingested_count_mismatch:{source_id}"
            )
    return manifest, source_payloads


def address_topic(address: str) -> str:
    rendered = address.lower().removeprefix("0x")
    if len(rendered) != 40 or any(char not in _HEX for char in rendered):
        raise ValueError("evm_address_invalid")
    return "0x" + "0" * 24 + rendered


def topic_address(topic: str) -> str:
    rendered = topic.lower().removeprefix("0x")
    if len(rendered) != 64 or any(char not in _HEX for char in rendered):
        raise ValueError("evm_address_topic_invalid")
    if any(char != "0" for char in rendered[:24]):
        raise ValueError("evm_address_topic_padding_invalid")
    return "0x" + rendered[-40:]


def _base58_encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = _BASE58_ALPHABET[remainder] + encoded
    leading_zeroes = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * leading_zeroes + (encoded or "1")


def _base58_decode(value: str) -> bytes:
    number = 0
    for char in value:
        try:
            digit = _BASE58_ALPHABET.index(char)
        except ValueError as exc:
            raise ValueError("base58_character_invalid") from exc
        number = number * 58 + digit
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeroes + body


def tron_hex_to_base58(value: str) -> str:
    rendered = value.lower().removeprefix("0x")
    if len(rendered) == 40:
        payload = b"\x41" + bytes.fromhex(rendered)
    elif len(rendered) == 42 and rendered.startswith("41"):
        payload = bytes.fromhex(rendered)
    else:
        raise ValueError("tron_hex_address_invalid")
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _base58_encode(payload + checksum)


def tron_base58_to_hex(value: str) -> str:
    decoded = _base58_decode(value)
    if len(decoded) != 25:
        raise ValueError("tron_base58_address_length_invalid")
    payload, checksum = decoded[:-4], decoded[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected or payload[0] != 0x41:
        raise ValueError("tron_base58_address_checksum_invalid")
    return "0x" + payload[1:].hex()


def data_address(data: str) -> str:
    rendered = data.lower().removeprefix("0x")
    if len(rendered) < 64 or any(char not in _HEX for char in rendered[-64:]):
        raise ValueError("evm_data_address_invalid")
    return "0x" + rendered[-40:]


def _runtime_code_bytes(code: str) -> bytes:
    rendered = code.lower().removeprefix("0x")
    if not rendered or len(rendered) % 2 or any(char not in _HEX for char in rendered):
        raise ValueError("runtime_bytecode_invalid")
    return bytes.fromhex(rendered)


def runtime_code_sha256(code: str) -> str:
    return hashlib.sha256(_runtime_code_bytes(code)).hexdigest()


def runtime_executable_code_sha256(code: str) -> str:
    raw = _runtime_code_bytes(code)
    executable = raw
    if len(raw) >= 3:
        metadata_length = int.from_bytes(raw[-2:], "big")
        metadata_start = len(raw) - metadata_length - 2
        if metadata_length > 0 and metadata_start > 0:
            metadata = raw[metadata_start:-2]
            known_key = any(
                marker in metadata
                for marker in (b"bzzr0", b"bzzr1", b"ipfs", b"solc")
            )
            if metadata and metadata[0] & 0xE0 == 0xA0 and known_key:
                executable = raw[:metadata_start]
    return hashlib.sha256(executable).hexdigest()


def abi_sha256(abi: Any) -> str:
    if not isinstance(abi, list):
        raise ValueError("verified_abi_not_list")
    return bytes_sha256(canonical_json_bytes(abi))


def _walk_ast(node: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(node, Mapping):
        yield node
        for value in node.values():
            yield from _walk_ast(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_ast(value)


def _expression_name(node: Any) -> str | None:
    if not isinstance(node, Mapping):
        return None
    for field in ("name", "memberName"):
        value = node.get(field)
        if isinstance(value, str) and value:
            return value
    for field in ("baseExpression", "expression"):
        nested = _expression_name(node.get(field))
        if nested:
            return nested
    return None


def _strip_solidity_comments_and_strings(source: str) -> str:
    output: list[str] = []
    index = 0
    state = "normal"
    quote = ""
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "normal":
            if char == "/" and following == "/":
                output.extend("  ")
                index += 2
                state = "line_comment"
                continue
            if char == "/" and following == "*":
                output.extend("  ")
                index += 2
                state = "block_comment"
                continue
            if char in {"'", '"'}:
                quote = char
                output.append(" ")
                index += 1
                state = "string"
                continue
            output.append(char)
            index += 1
            continue
        if state == "line_comment":
            output.append("\n" if char == "\n" else " ")
            index += 1
            if char == "\n":
                state = "normal"
            continue
        if state == "block_comment":
            if char == "*" and following == "/":
                output.extend("  ")
                index += 2
                state = "normal"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if state == "string":
            if char == "\\":
                output.extend("  " if following else " ")
                index += 2 if following else 1
            elif char == quote:
                output.append(" ")
                index += 1
                state = "normal"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
    if state in {"block_comment", "string"}:
        raise StablecoinRemediationError("verified_source_lexically_unterminated")
    return "".join(output)


_SOLIDITY_TOKEN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*|\+=|-=|\+\+|--|=>|==|!=|<=|>=|[{}()\[\].,;=]"
)


def _solidity_function_bodies(sources: Mapping[str, Any]) -> dict[str, list[list[str]]]:
    functions: dict[str, list[list[str]]] = {}
    for source in sources.values():
        if not isinstance(source, Mapping) or not isinstance(source.get("content"), str):
            continue
        stripped = _strip_solidity_comments_and_strings(source["content"])
        tokens = _SOLIDITY_TOKEN.findall(stripped)
        index = 0
        while index < len(tokens):
            if tokens[index] != "function":
                index += 1
                continue
            if index + 1 >= len(tokens) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", tokens[index + 1]
            ):
                index += 1
                continue
            name = tokens[index + 1].lower()
            cursor = index + 2
            while cursor < len(tokens) and tokens[cursor] not in {"{", ";"}:
                cursor += 1
            if cursor >= len(tokens) or tokens[cursor] == ";":
                index = cursor + 1
                continue
            depth = 1
            end = cursor + 1
            while end < len(tokens) and depth:
                if tokens[end] == "{":
                    depth += 1
                elif tokens[end] == "}":
                    depth -= 1
                end += 1
            if depth:
                raise StablecoinRemediationError(
                    "verified_source_function_brace_unterminated"
                )
            functions.setdefault(name, []).append(tokens[cursor + 1 : end - 1])
            index = end
    return functions


def _lexical_function_summary(tokens: Sequence[str]) -> dict[str, set[str]]:
    calls = {
        tokens[index].lower()
        for index in range(len(tokens) - 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tokens[index])
        and tokens[index + 1] == "("
        and tokens[index].lower()
        not in {"if", "for", "while", "require", "assert", "return"}
    }
    writes: set[str] = set()
    statement_start = 0
    for index, token in enumerate(tokens):
        if token in {";", "{", "}"}:
            statement_start = index + 1
            continue
        if token not in {"=", "+=", "-=", "++", "--"}:
            continue
        for candidate in tokens[statement_start:index]:
            lowered = candidate.lower()
            if "supply" in lowered or "balance" in lowered:
                writes.add(lowered)
    return {"calls": calls, "writes": writes}


def _verified_source_lexical_summaries(
    payload: Mapping[str, Any],
    required: set[str],
) -> tuple[dict[str, dict[str, set[str]]], set[str]]:
    sources = payload.get("sources", {})
    if not isinstance(sources, Mapping) or not sources:
        raise StablecoinRemediationError("verified_source_content_missing")
    bodies = _solidity_function_bodies(sources)
    if not required.issubset(bodies):
        raise StablecoinRemediationError("verified_native_function_source_missing")
    direct = {
        name: _lexical_function_summary(body)
        for name, overloads in bodies.items()
        for body in overloads
    }
    reachable: set[str] = set()
    queue = list(required)
    while queue:
        name = queue.pop()
        if name in reachable:
            continue
        reachable.add(name)
        summary = direct.get(name)
        if summary is None:
            continue
        queue.extend(call for call in summary["calls"] if call in direct)
    summaries = {name: direct[name] for name in sorted(reachable) if name in direct}
    storage_writes = {
        value for summary in summaries.values() for value in summary["writes"]
    }
    return summaries, storage_writes


def verified_source_semantic_proof(
    payload: Mapping[str, Any],
    *,
    source_artifact_sha256: str,
    native_mint_events: Sequence[str],
    native_burn_events: Sequence[str],
    zero_transfer_emission: str,
) -> dict[str, Any]:
    std_output = payload.get("stdJsonOutput", {})
    source_outputs = (
        std_output.get("sources", {}) if isinstance(std_output, Mapping) else {}
    )
    function_summaries: dict[str, dict[str, set[str]]] = {}
    storage_writes: set[str] = set()
    required = {
        *[str(value).lower() for value in native_mint_events],
        *[str(value).lower() for value in native_burn_events],
    }
    ast_available = False
    if isinstance(source_outputs, Mapping):
        for source in source_outputs.values():
            if not isinstance(source, Mapping) or not isinstance(
                source.get("ast"), Mapping
            ):
                continue
            ast_available = True
            for node in _walk_ast(source["ast"]):
                if node.get("nodeType") != "FunctionDefinition":
                    continue
                function_name = str(node.get("name", "")).lower()
                if function_name not in required:
                    continue
                calls: set[str] = set()
                writes: set[str] = set()
                for child in _walk_ast(node.get("body", {})):
                    if child.get("nodeType") == "FunctionCall":
                        name = _expression_name(child.get("expression"))
                        if name:
                            calls.add(name.lower())
                    if child.get("nodeType") == "EmitStatement":
                        name = _expression_name(
                            child.get("eventCall", {}).get("expression")
                        )
                        if name:
                            calls.add(name.lower())
                    if child.get("nodeType") == "Assignment":
                        name = _expression_name(child.get("leftHandSide"))
                        if name:
                            writes.add(name.lower())
                    if child.get("nodeType") == "UnaryOperation" and child.get(
                        "operator"
                    ) in {"++", "--"}:
                        name = _expression_name(child.get("subExpression"))
                        if name:
                            writes.add(name.lower())
                function_summaries[function_name] = {
                    "calls": calls,
                    "writes": writes,
                }
                storage_writes.update(writes)
    proof_kind = "verified_source_ast"
    parser = "solidity_compiler_ast"
    if not ast_available:
        function_summaries, storage_writes = _verified_source_lexical_summaries(
            payload, required
        )
        proof_kind = "verified_source_control_flow"
        parser = "bounded_solidity_lexer_v0.1"
    if not required.issubset(function_summaries):
        raise StablecoinRemediationError("verified_native_function_proof_missing")
    event_calls = {
        name
        for summary in function_summaries.values()
        for name in summary["calls"]
    }
    if not required.issubset(event_calls):
        raise StablecoinRemediationError("verified_native_event_call_missing")
    has_supply_write = any("totalsupply" in value for value in storage_writes)
    has_balance_write = any("balance" in value for value in storage_writes)
    if not has_supply_write or not has_balance_write:
        raise StablecoinRemediationError("verified_supply_storage_write_missing")
    transfer_in_all = all(
        "transfer" in function_summaries[name]["calls"] for name in required
    )
    if zero_transfer_emission == "paired" and not transfer_in_all:
        raise StablecoinRemediationError("verified_zero_transfer_call_missing")
    if zero_transfer_emission == "absent" and "transfer" in event_calls:
        raise StablecoinRemediationError("unexpected_zero_transfer_call_present")
    proof = {
        "proof_kind": proof_kind,
        "parser": parser,
        "source_artifact_sha256": source_artifact_sha256,
        "native_mint_event_calls": sorted(
            str(value).lower() for value in native_mint_events
        ),
        "native_burn_event_calls": sorted(
            str(value).lower() for value in native_burn_events
        ),
        "supply_storage_writes": sorted(storage_writes),
        "zero_transfer_emission": zero_transfer_emission,
        "ast_function_summaries": {
            name: {
                "calls": sorted(summary["calls"]),
                "writes": sorted(summary["writes"]),
            }
            for name, summary in sorted(function_summaries.items())
        },
    }
    proof["proof_hash"] = canonical_hash(proof)
    return proof


def fetch_ethereum_logs(
    rpc: EthereumRpc,
    *,
    address: str,
    topics: Sequence[Any],
    start_block: int,
    end_block_exclusive: int,
    maximum_step: int = 100_000,
    minimum_step: int = 500,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not (0 <= start_block < end_block_exclusive):
        raise ValueError("ethereum_log_range_invalid")
    cursor = start_block
    step = maximum_step
    logs: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    while cursor < end_block_exclusive:
        end_block = min(end_block_exclusive - 1, cursor + step - 1)
        query = {
            "address": address,
            "fromBlock": hex(cursor),
            "toBlock": hex(end_block),
            "topics": list(topics),
        }
        try:
            rows = rpc.call("eth_getLogs", [query])
        except PublicChainCollectionError:
            if step <= minimum_step:
                raise
            step = max(minimum_step, step // 2)
            continue
        if not isinstance(rows, list) or any(
            not isinstance(row, Mapping) for row in rows
        ):
            raise StablecoinRemediationError("ethereum_log_result_invalid")
        materialized = [dict(row) for row in rows]
        for row in materialized:
            number = int(str(row.get("blockNumber", "")), 16)
            if number < cursor or number > end_block:
                raise StablecoinRemediationError("ethereum_log_outside_query_range")
            if row.get("removed") is True:
                raise StablecoinRemediationError("ethereum_removed_log_present")
        logs.extend(materialized)
        segments.append(
            {
                "from_block": cursor,
                "to_block": end_block,
                "topics": list(topics),
                "event_count": len(materialized),
            }
        )
        cursor = end_block + 1
        step = min(maximum_step, step * 2)
    logs.sort(
        key=lambda row: (
            int(str(row["blockNumber"]), 16),
            int(str(row["transactionIndex"]), 16),
            int(str(row["logIndex"]), 16),
        )
    )
    return logs, segments


def normalize_evm_transfer_log(
    row: Mapping[str, Any],
    *,
    contract: str,
    allow_zero_amount: bool = False,
) -> dict[str, Any]:
    topics = row.get("topics")
    if (
        str(row.get("address", "")).lower() != contract.lower()
        or not isinstance(topics, list)
        or len(topics) != 3
        or str(topics[0]).lower() != TRANSFER_TOPIC
    ):
        raise StablecoinRemediationError("evm_transfer_log_contract_or_topics_invalid")
    try:
        amount = int(str(row["data"]), 16)
        block_number = int(str(row["blockNumber"]), 16)
        event_index = int(str(row["logIndex"]), 16)
        transaction_hash = str(row["transactionHash"]).lower()
        block_hash = str(row["blockHash"]).lower()
        from_address = topic_address(str(topics[1]))
        to_address = topic_address(str(topics[2]))
    except (KeyError, TypeError, ValueError) as exc:
        raise StablecoinRemediationError("evm_transfer_log_fields_invalid") from exc
    if (
        amount < 0
        or (amount == 0 and not allow_zero_amount)
        or not transaction_hash
        or not block_hash
    ):
        raise StablecoinRemediationError("evm_transfer_log_identity_invalid")
    return {
        "transaction_hash": transaction_hash,
        "event_index": event_index,
        "block_number": block_number,
        "block_hash": block_hash,
        "block_timestamp": "1970-01-01T00:00:00Z",
        "available_at": "1970-01-01T00:00:00Z",
        "event_name": "Transfer",
        "raw_amount": str(amount),
        "from_address": from_address,
        "to_address": to_address,
        "removed": False,
    }


def _month_windows(start_ms: int, end_ms: int) -> Iterator[tuple[int, int]]:
    if end_ms <= start_ms:
        raise ValueError("month_window_invalid")
    cursor = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    cursor = cursor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while int(cursor.timestamp() * 1000) < end_ms:
        if cursor.month == 12:
            following = cursor.replace(year=cursor.year + 1, month=1)
        else:
            following = cursor.replace(month=cursor.month + 1)
        yield max(start_ms, int(cursor.timestamp() * 1000)), min(
            end_ms, int(following.timestamp() * 1000)
        )
        cursor = following


def fetch_tronscan_transfer_rows(
    client: PublicEvidenceClient,
    *,
    related_address: str,
    start_ms: int,
    end_ms: int,
    contract_address: str = TRON_USDT_BASE58,
    base_url: str = "https://apilist.tronscanapi.com",
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if page_size < 1 or page_size > 50:
        raise ValueError("tronscan_page_size_invalid")
    tron_base58_to_hex(related_address)
    rows_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    segments: list[dict[str, Any]] = []
    for window_start, window_end in _month_windows(start_ms, end_ms):
        offset = 0
        while True:
            query = urllib.parse.urlencode(
                {
                    "limit": page_size,
                    "start": offset,
                    "contract_address": contract_address,
                    "relatedAddress": related_address,
                    "start_timestamp": window_start,
                    "end_timestamp": window_end,
                }
            )
            payload = client.json(
                f"{base_url.rstrip('/')}/api/token_trc20/transfers?{query}"
            )
            if not isinstance(payload, Mapping):
                raise StablecoinRemediationError(
                    "tronscan_transfer_response_not_object"
                )
            page = payload.get("token_transfers", [])
            if not isinstance(page, list) or any(
                not isinstance(row, Mapping) for row in page
            ):
                raise StablecoinRemediationError("tronscan_transfer_page_invalid")
            segments.append(
                {
                    "related_address": related_address,
                    "start_timestamp": window_start,
                    "end_timestamp": window_end,
                    "offset": offset,
                    "page_size": page_size,
                    "returned_count": len(page),
                    "reported_total_ignored": payload.get("total"),
                    "reported_range_total_ignored": payload.get("rangeTotal"),
                }
            )
            for raw_row in page:
                row = dict(raw_row)
                try:
                    timestamp = int(row["block_ts"])
                    identity = (
                        str(row["transaction_id"]).lower(),
                        int(row["block"]),
                        str(row["from_address"]),
                        str(row["to_address"]),
                        str(row["quant"]),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise StablecoinRemediationError(
                        "tronscan_transfer_row_invalid"
                    ) from exc
                if not (window_start <= timestamp < window_end):
                    raise StablecoinRemediationError(
                        "tronscan_transfer_outside_partition"
                    )
                if (
                    row.get("confirmed") is not True
                    or row.get("contractRet") != "SUCCESS"
                    or str(row.get("contract_address", "")) != contract_address
                ):
                    raise StablecoinRemediationError(
                        "tronscan_transfer_not_confirmed_success"
                    )
                existing = rows_by_identity.get(identity)
                if existing is not None and canonical_hash(existing) != canonical_hash(row):
                    raise StablecoinRemediationError(
                        "tronscan_transfer_identity_conflict"
                    )
                rows_by_identity[identity] = row
            if len(page) < page_size:
                break
            offset += page_size
    rows = sorted(
        rows_by_identity.values(),
        key=lambda row: (
            int(row["block"]),
            str(row["transaction_id"]),
            str(row["from_address"]),
            str(row["to_address"]),
            str(row["quant"]),
        ),
    )
    return rows, segments


def fetch_tron_transaction_transfer_events(
    client: PublicEvidenceClient,
    transfer_row: Mapping[str, Any],
    *,
    contract_address: str = TRON_USDT_BASE58,
    base_url: str = DEFAULT_TRONGRID_URL,
) -> list[dict[str, Any]]:
    transaction_hash = str(transfer_row.get("transaction_id", "")).lower()
    payload = client.json(
        f"{base_url.rstrip('/')}/v1/transactions/{transaction_hash}/events"
        "?only_confirmed=true&limit=200"
    )
    if (
        not isinstance(payload, Mapping)
        or payload.get("success") is not True
        or not isinstance(payload.get("data"), list)
        or payload.get("meta", {}).get("fingerprint")
    ):
        raise StablecoinRemediationError("trongrid_transaction_events_incomplete")
    expected_from = str(transfer_row.get("from_address", ""))
    expected_to = str(transfer_row.get("to_address", ""))
    expected_value = str(transfer_row.get("quant", ""))
    matches: list[dict[str, Any]] = []
    for value in payload["data"]:
        if not isinstance(value, Mapping):
            continue
        result = value.get("result", {})
        if (
            value.get("event_name") != "Transfer"
            or value.get("contract_address") != contract_address
            or not isinstance(result, Mapping)
        ):
            continue
        try:
            from_address = tron_hex_to_base58(str(result["from"]))
            to_address = tron_hex_to_base58(str(result["to"]))
        except (KeyError, ValueError):
            continue
        if (
            from_address == expected_from
            and to_address == expected_to
            and str(result.get("value")) == expected_value
        ):
            matches.append(dict(value))
    if not matches:
        raise StablecoinRemediationError(
            "trongrid_transfer_event_match_count:0"
        )
    matches.sort(key=lambda row: int(row["event_index"]))
    identities = {
        (str(row.get("transaction_id", "")).lower(), int(row["event_index"]))
        for row in matches
    }
    if len(identities) != len(matches):
        raise StablecoinRemediationError(
            "trongrid_transfer_event_identity_duplicate"
        )
    return matches


def normalize_tron_transfer(
    transfer_row: Mapping[str, Any],
    transaction_event: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = transaction_event.get("result", {})
    if not isinstance(result, Mapping):
        raise StablecoinRemediationError("tron_transfer_result_invalid")
    normalized = {
        "transaction_hash": str(transaction_event["transaction_id"]).lower(),
        "event_index": int(transaction_event["event_index"]),
        "block_number": int(transaction_event["block_number"]),
        "block_hash": "0" * 64,
        "block_timestamp": utc_text(int(transaction_event["block_timestamp"]) / 1000),
        "available_at": utc_text(int(transaction_event["block_timestamp"]) / 1000),
        "event_name": "Transfer",
        "raw_amount": str(result["value"]),
        "from_address": tron_hex_to_base58(str(result["from"])),
        "to_address": tron_hex_to_base58(str(result["to"])),
        "removed": False,
    }
    raw = {
        "tronscan_transfer": transfer_row,
        "trongrid_transaction_event": transaction_event,
    }
    return normalized, raw


def sourcify_contract_url(chain_id: int, address: str) -> str:
    fields = (
        "abi,sources,deployment,compilation,proxyResolution,"
        "stdJsonOutput,signatures"
    )
    return (
        f"https://sourcify.dev/server/v2/contract/{chain_id}/{address}"
        f"?fields={fields}"
    )


def fetch_immutable_evidence(
    client: PublicEvidenceClient,
    url: str,
    path: Path,
    *,
    method: str = "GET",
    payload: object | None = None,
) -> bytes:
    if path.exists():
        raw = path.read_bytes()
        if not raw:
            raise StablecoinRemediationError(
                f"existing_evidence_empty:{path.name}"
            )
        return raw
    raw = client.fetch(url, method=method, payload=payload)
    write_immutable_bytes(path, raw)
    return raw


def parse_verified_contract(raw: bytes, *, expected_address: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StablecoinRemediationError("sourcify_response_invalid") from exc
    if (
        not isinstance(payload, dict)
        or str(payload.get("address", "")).lower() != expected_address.lower()
        or payload.get("match") not in {"match", "exact_match"}
        or not isinstance(payload.get("abi"), list)
        or not isinstance(payload.get("sources"), Mapping)
        or not payload.get("sources")
        or not isinstance(payload.get("deployment"), Mapping)
    ):
        raise StablecoinRemediationError("sourcify_contract_not_verified")
    return payload


def _decode_evm_call_address(value: Any) -> str:
    rendered = str(value).lower().removeprefix("0x")
    if len(rendered) != 64 or any(char not in _HEX for char in rendered):
        raise StablecoinRemediationError("evm_address_call_result_invalid")
    if any(char != "0" for char in rendered[:24]):
        raise StablecoinRemediationError("evm_address_call_padding_invalid")
    return "0x" + rendered[-40:]


def _owner_at(rpc: EthereumRpc, contract: str, block_number: int) -> str:
    result = rpc.call(
        "eth_call",
        [{"to": contract, "data": "0x8da5cb5b"}, hex(block_number)],
    )
    return _decode_evm_call_address(result)


def ethereum_owner_at(
    rpc: EthereumRpc, contract: str, block_number: int
) -> str:
    return _owner_at(rpc, contract, block_number)


def decode_evm_uint_result(value: Any) -> int:
    rendered = str(value).lower().removeprefix("0x")
    if len(rendered) != 64 or any(char not in _HEX for char in rendered):
        raise StablecoinRemediationError("evm_uint_call_result_invalid")
    return int(rendered, 16)


def multisig_transaction_call(transaction_id: int) -> str:
    if transaction_id < 0:
        raise ValueError("multisig_transaction_id_negative")
    return MULTISIG_TRANSACTIONS_SELECTOR + f"{transaction_id:064x}"


def decode_multisig_transaction_result(value: Any) -> dict[str, Any]:
    rendered = str(value).lower().removeprefix("0x")
    if (
        len(rendered) < 64 * 5
        or len(rendered) % 64
        or any(char not in _HEX for char in rendered)
    ):
        raise StablecoinRemediationError("multisig_transaction_result_invalid")

    words = [rendered[offset : offset + 64] for offset in range(0, 256, 64)]
    if any(char != "0" for char in words[0][:-40]):
        raise StablecoinRemediationError("multisig_destination_padding_invalid")
    destination = "0x" + words[0][-40:]
    amount = int(words[1], 16)
    data_offset = int(words[2], 16)
    executed_raw = int(words[3], 16)
    if data_offset < 128 or data_offset % 32 or executed_raw not in {0, 1}:
        raise StablecoinRemediationError("multisig_transaction_head_invalid")
    data_length_offset = data_offset * 2
    if data_length_offset + 64 > len(rendered):
        raise StablecoinRemediationError("multisig_transaction_data_offset_invalid")
    data_length = int(rendered[data_length_offset : data_length_offset + 64], 16)
    data_start = data_length_offset + 64
    data_end = data_start + data_length * 2
    padded_end = data_start + ((data_length + 31) // 32) * 64
    if data_end > len(rendered) or padded_end != len(rendered):
        raise StablecoinRemediationError("multisig_transaction_data_length_invalid")
    if any(char != "0" for char in rendered[data_end:padded_end]):
        raise StablecoinRemediationError("multisig_transaction_data_padding_invalid")
    return {
        "destination": destination,
        "value": str(amount),
        "data": "0x" + rendered[data_start:data_end],
        "executed": bool(executed_raw),
    }


def decode_transfer_ownership_target(data: Any) -> str | None:
    rendered = str(data).lower()
    if not rendered.startswith(TRANSFER_OWNERSHIP_SELECTOR):
        return None
    arguments = rendered[len(TRANSFER_OWNERSHIP_SELECTOR) :]
    if (
        len(arguments) != 64
        or any(char not in _HEX for char in arguments)
        or any(char != "0" for char in arguments[:-40])
    ):
        raise StablecoinRemediationError("transfer_ownership_calldata_invalid")
    return "0x" + arguments[-40:]


def _contains_token_sequence(tokens: Sequence[str], expected: Sequence[str]) -> bool:
    width = len(expected)
    return any(
        list(tokens[offset : offset + width]) == list(expected)
        for offset in range(len(tokens) - width + 1)
    )


def verified_multisig_execution_semantic_proof(
    payload: Mapping[str, Any],
    *,
    source_artifact_sha256: str,
    expected_address: str = USDT_ETHEREUM_MULTISIG_OWNER,
) -> dict[str, Any]:
    if (
        str(payload.get("address", "")).lower() != expected_address.lower()
        or payload.get("match") not in {"match", "exact_match"}
        or payload.get("runtimeMatch") not in {"match", "exact_match"}
        or payload.get("creationMatch") not in {"match", "exact_match"}
        or not _sha256_text(source_artifact_sha256)
    ):
        raise StablecoinRemediationError("multisig_verified_source_identity_invalid")
    proxy = payload.get("proxyResolution", {})
    deployment = payload.get("deployment", {})
    if (
        not isinstance(proxy, Mapping)
        or proxy.get("isProxy") is not False
        or not isinstance(deployment, Mapping)
        or int(deployment.get("blockNumber", -1)) < 0
    ):
        raise StablecoinRemediationError("multisig_deployment_or_proxy_invalid")

    expected_abi = {
        "transactionCount": ((), ("uint256",)),
        "transactions": (
            ("uint256",),
            ("address", "uint256", "bytes", "bool"),
        ),
    }
    abi = payload.get("abi")
    if not isinstance(abi, list):
        raise StablecoinRemediationError("multisig_abi_invalid")
    for name, (inputs, outputs) in expected_abi.items():
        matches = [
            entry
            for entry in abi
            if isinstance(entry, Mapping)
            and entry.get("type") == "function"
            and entry.get("name") == name
        ]
        if len(matches) != 1:
            raise StablecoinRemediationError(f"multisig_abi_function_invalid:{name}")
        entry = matches[0]
        actual_inputs = tuple(
            str(item.get("type", ""))
            for item in entry.get("inputs", [])
            if isinstance(item, Mapping)
        )
        actual_outputs = tuple(
            str(item.get("type", ""))
            for item in entry.get("outputs", [])
            if isinstance(item, Mapping)
        )
        if actual_inputs != inputs or actual_outputs != outputs:
            raise StablecoinRemediationError(
                f"multisig_abi_function_signature_invalid:{name}"
            )

    signatures = payload.get("signatures", {})
    function_signatures = (
        signatures.get("function", []) if isinstance(signatures, Mapping) else []
    )
    selector_by_signature = {
        str(entry.get("signature", "")): str(entry.get("signatureHash4", "")).lower()
        for entry in function_signatures
        if isinstance(entry, Mapping)
    }
    if (
        selector_by_signature.get("transactionCount()")
        != MULTISIG_TRANSACTION_COUNT_SELECTOR
        or selector_by_signature.get("transactions(uint256)")
        != MULTISIG_TRANSACTIONS_SELECTOR
    ):
        raise StablecoinRemediationError("multisig_function_selectors_invalid")

    sources = payload.get("sources", {})
    if not isinstance(sources, Mapping):
        raise StablecoinRemediationError("multisig_verified_source_missing")
    bodies = _solidity_function_bodies(sources)
    if len(bodies.get("addtransaction", [])) != 1 or len(
        bodies.get("executetransaction", [])
    ) != 1:
        raise StablecoinRemediationError("multisig_execution_functions_invalid")
    add_tokens = bodies["addtransaction"][0]
    execute_tokens = bodies["executetransaction"][0]
    required_add_sequences = (
        ("transactionId", "=", "transactionCount"),
        ("transactions", "[", "transactionId", "]", "=", "Transaction"),
        ("transactionCount", "+="),
    )
    required_execute_sequences = (
        ("Transaction", "tx", "=", "transactions", "[", "transactionId", "]"),
        ("tx", ".", "executed", "=", "true"),
        (
            "tx",
            ".",
            "destination",
            ".",
            "call",
            ".",
            "value",
            "(",
            "tx",
            ".",
            "value",
            ")",
            "(",
            "tx",
            ".",
            "data",
            ")",
        ),
        ("tx", ".", "executed", "=", "false"),
    )
    if not all(
        _contains_token_sequence(add_tokens, sequence)
        for sequence in required_add_sequences
    ) or not all(
        _contains_token_sequence(execute_tokens, sequence)
        for sequence in required_execute_sequences
    ):
        raise StablecoinRemediationError("multisig_execution_semantics_unproven")

    std_output = payload.get("stdJsonOutput", {})
    contracts = std_output.get("contracts", {}) if isinstance(std_output, Mapping) else {}
    compilation = payload.get("compilation", {})
    source_name = str(compilation.get("fullyQualifiedName", "")).split(":", 1)[0]
    contract_name = str(compilation.get("name", ""))
    compiled = (
        contracts.get(source_name, {}).get(contract_name, {})
        if isinstance(contracts, Mapping)
        else {}
    )
    bytecode = (
        compiled.get("evm", {}).get("deployedBytecode", {}).get("object")
        if isinstance(compiled, Mapping)
        else None
    )
    if not isinstance(bytecode, str):
        raise StablecoinRemediationError("multisig_compiled_runtime_missing")
    proof = {
        "proof_kind": "verified_multisig_complete_transaction_mapping_execution_path",
        "parser": "bounded_solidity_lexer_and_verified_abi_v0.1",
        "contract": expected_address.lower(),
        "deployment_block": int(deployment["blockNumber"]),
        "source_artifact_sha256": source_artifact_sha256.lower(),
        "abi_sha256": abi_sha256(abi),
        "runtime_match": str(payload["runtimeMatch"]),
        "compiled_runtime_code_sha256": runtime_code_sha256(bytecode),
        "compiled_runtime_executable_code_sha256": (
            runtime_executable_code_sha256(bytecode)
        ),
        "transaction_count_selector": MULTISIG_TRANSACTION_COUNT_SELECTOR,
        "transactions_selector": MULTISIG_TRANSACTIONS_SELECTOR,
        "state_enumeration": "transaction_ids_zero_through_transaction_count_minus_one",
        "successful_call_semantics": (
            "executed_true_implies_destination_call_returned_true_and_is_not_reset"
        ),
    }
    proof["proof_hash"] = canonical_hash(proof)
    return proof


def discover_usdt_ethereum_owner_history(
    rpc: EthereumRpc,
    *,
    contract: str,
    deployment_block: int,
    observed_through_block: int,
    native_event_blocks: Iterable[int],
    checkpoint_step_blocks: int = 100_000,
) -> dict[str, Any]:
    if checkpoint_step_blocks < 1:
        raise ValueError("owner_checkpoint_step_invalid")
    native_blocks = set(native_event_blocks)
    checkpoints = {
        deployment_block,
        observed_through_block,
        *range(
            deployment_block,
            observed_through_block + 1,
            checkpoint_step_blocks,
        ),
        *native_blocks,
    }
    ordered = sorted(checkpoints)
    observations: list[dict[str, Any]] = []
    for offset in range(0, len(ordered), 250):
        blocks = ordered[offset : offset + 250]
        results = rpc.batch(
            [
                (
                    "eth_call",
                    [{"to": contract, "data": "0x8da5cb5b"}, hex(number)],
                )
                for number in blocks
            ]
        )
        observations.extend(
            {
                "block_number": block_number,
                "owner": _decode_evm_call_address(result),
            }
            for block_number, result in zip(blocks, results)
        )
    transitions: list[dict[str, Any]] = []
    previous = observations[0]
    for observation in observations[1:]:
        if observation["owner"] == previous["owner"]:
            previous = observation
            continue
        low = int(previous["block_number"]) + 1
        high = int(observation["block_number"])
        target_owner = str(observation["owner"])
        while low < high:
            middle = (low + high) // 2
            if _owner_at(rpc, contract, middle) == target_owner:
                high = middle
            else:
                low = middle + 1
        before_owner = _owner_at(rpc, contract, low - 1)
        at_owner = _owner_at(rpc, contract, low)
        if at_owner != target_owner or before_owner == target_owner:
            raise StablecoinRemediationError("owner_transition_boundary_invalid")
        transitions.append(
            {
                "activation_block": low,
                "previous_owner": before_owner,
                "new_owner": at_owner,
                "left_checkpoint_block": previous["block_number"],
                "right_checkpoint_block": observation["block_number"],
            }
        )
        previous = observation
    owners = [observations[0]["owner"], *[row["new_owner"] for row in transitions]]
    if len(set(owners)) != len(owners):
        raise StablecoinRemediationError(
            "owner_address_reappeared_between_observed_transitions"
        )
    return {
        "contract": contract.lower(),
        "deployment_block": deployment_block,
        "observed_through_block": observed_through_block,
        "checkpoint_step_blocks": checkpoint_step_blocks,
        "native_event_block_count": len(native_blocks),
        "checkpoint_count": len(observations),
        "observations": observations,
        "transitions": transitions,
        "owner_addresses": owners,
        "exact_at_each_checkpoint": True,
        "exact_transition_boundary_when_checkpoint_value_changed": True,
        "absence_of_round_trip_change_between_equal_checkpoints_proven": False,
        "complete_owner_history_claimed": False,
    }


def _rpc_quantity(value: Any, *, field: str) -> int:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise StablecoinRemediationError(f"{field}_invalid")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise StablecoinRemediationError(f"{field}_invalid") from exc


def build_usdt_ethereum_owner_call_proof(
    *,
    contract: str,
    owner_audit: Mapping[str, Any],
    owner_audit_sha256: str,
    multisig_semantic_proof: Mapping[str, Any],
    initial_block_rows: Sequence[Mapping[str, Any]],
    initial_receipt_rows: Sequence[Mapping[str, Any]],
    multisig_transaction_rows: Sequence[Mapping[str, Any]],
    state_observations: Mapping[str, Any],
    evidence_references: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    contract = contract.lower()
    if contract != "0xdac17f958d2ee523a2206206994597c13d831ec7":
        raise StablecoinRemediationError("owner_call_proof_contract_invalid")
    if not _sha256_text(owner_audit_sha256):
        raise StablecoinRemediationError("owner_audit_sha256_invalid")
    transitions = owner_audit.get("transitions", [])
    owners = [str(value).lower() for value in owner_audit.get("owner_addresses", [])]
    if (
        not isinstance(transitions, list)
        or len(transitions) != 1
        or owners
        != [USDT_ETHEREUM_INITIAL_OWNER, USDT_ETHEREUM_MULTISIG_OWNER]
    ):
        raise StablecoinRemediationError("owner_audit_transition_shape_invalid")
    transition = transitions[0]
    if not isinstance(transition, Mapping):
        raise StablecoinRemediationError("owner_audit_transition_invalid")
    deployment_block = int(owner_audit["deployment_block"])
    observed_through_block = int(owner_audit["observed_through_block"])
    activation_block = int(transition["activation_block"])
    if (
        str(transition.get("previous_owner", "")).lower()
        != USDT_ETHEREUM_INITIAL_OWNER
        or str(transition.get("new_owner", "")).lower()
        != USDT_ETHEREUM_MULTISIG_OWNER
        or not deployment_block < activation_block <= observed_through_block
    ):
        raise StablecoinRemediationError("owner_audit_transition_values_invalid")

    source_proof = dict(multisig_semantic_proof)
    if (
        source_proof.get("proof_kind")
        != "verified_multisig_complete_transaction_mapping_execution_path"
        or source_proof.get("contract") != USDT_ETHEREUM_MULTISIG_OWNER
        or source_proof.get("proof_hash")
        != canonical_hash(
            {key: value for key, value in source_proof.items() if key != "proof_hash"}
        )
        or int(source_proof.get("deployment_block", -1)) > activation_block
    ):
        raise StablecoinRemediationError("owner_multisig_semantic_proof_invalid")

    expected_reference_counts = {
        "initial_owner_blocks": len(initial_block_rows),
        "initial_owner_receipts": len(initial_receipt_rows),
        "multisig_transactions": len(multisig_transaction_rows),
    }
    for role, expected_count in expected_reference_counts.items():
        reference = evidence_references.get(role, {})
        if (
            not isinstance(reference, Mapping)
            or not _sha256_text(reference.get("sha256"))
            or reference.get("record_count") != expected_count
        ):
            raise StablecoinRemediationError(
                f"owner_call_proof_evidence_reference_invalid:{role}"
            )
    source_reference = evidence_references.get("multisig_verified_source", {})
    if (
        not isinstance(source_reference, Mapping)
        or source_reference.get("sha256") != source_proof["source_artifact_sha256"]
    ):
        raise StablecoinRemediationError("owner_multisig_source_reference_invalid")

    expected_blocks = list(range(deployment_block, activation_block + 1))
    if len(initial_block_rows) != len(expected_blocks):
        raise StablecoinRemediationError("owner_initial_block_scan_count_invalid")
    owner_to_contract_calls: list[dict[str, Any]] = []
    total_transaction_count = 0
    previous_nonce: int | None = None
    for expected_number, row in zip(expected_blocks, initial_block_rows):
        raw_block = row.get("raw_block", {})
        if not isinstance(raw_block, Mapping):
            raise StablecoinRemediationError("owner_initial_block_payload_invalid")
        number = _rpc_quantity(raw_block.get("number"), field="owner_block_number")
        block_hash = str(raw_block.get("hash", "")).lower()
        transactions = raw_block.get("transactions", [])
        code = str(row.get("initial_owner_code", "")).lower()
        nonce = _rpc_quantity(
            row.get("initial_owner_nonce"), field="owner_account_nonce"
        )
        if (
            number != expected_number
            or row.get("block_number") != expected_number
            or not re.fullmatch(r"0x[0-9a-f]{64}", block_hash)
            or not isinstance(transactions, list)
            or any(not isinstance(transaction, Mapping) for transaction in transactions)
            or code != "0x"
            or nonce < 1
            or (previous_nonce is not None and nonce < previous_nonce)
        ):
            raise StablecoinRemediationError("owner_initial_block_scan_invalid")
        previous_nonce = nonce
        total_transaction_count += len(transactions)
        for transaction in transactions:
            if (
                str(transaction.get("from", "")).lower()
                != USDT_ETHEREUM_INITIAL_OWNER
                or str(transaction.get("to", "")).lower() != contract
            ):
                continue
            tx_hash = str(transaction.get("hash", "")).lower()
            if not re.fullmatch(r"0x[0-9a-f]{64}", tx_hash):
                raise StablecoinRemediationError("owner_initial_call_hash_invalid")
            owner_to_contract_calls.append(
                {
                    "block_number": number,
                    "block_hash": block_hash,
                    "transaction_hash": tx_hash,
                    "input": str(transaction.get("input", "")).lower(),
                }
            )

    receipts: dict[str, Mapping[str, Any]] = {}
    for row in initial_receipt_rows:
        transaction_hash = str(row.get("transaction_hash", "")).lower()
        receipt = row.get("raw_receipt", {})
        if (
            not re.fullmatch(r"0x[0-9a-f]{64}", transaction_hash)
            or not isinstance(receipt, Mapping)
            or str(receipt.get("transactionHash", "")).lower() != transaction_hash
            or transaction_hash in receipts
        ):
            raise StablecoinRemediationError("owner_initial_receipt_invalid")
        receipts[transaction_hash] = receipt
    if set(receipts) != {
        row["transaction_hash"] for row in owner_to_contract_calls
    }:
        raise StablecoinRemediationError("owner_initial_receipt_coverage_invalid")

    successful_owner_changes: list[dict[str, Any]] = []
    failed_owner_changes = 0
    for call in owner_to_contract_calls:
        target = decode_transfer_ownership_target(call["input"])
        receipt = receipts[call["transaction_hash"]]
        status = _rpc_quantity(receipt.get("status"), field="owner_call_status")
        receipt_block = _rpc_quantity(
            receipt.get("blockNumber"), field="owner_call_receipt_block"
        )
        if (
            str(receipt.get("blockHash", "")).lower() != call["block_hash"]
            or receipt_block != call["block_number"]
            or status not in {0, 1}
        ):
            raise StablecoinRemediationError("owner_initial_receipt_binding_invalid")
        if target is None:
            continue
        if status == 0:
            failed_owner_changes += 1
            continue
        successful_owner_changes.append({**call, "new_owner": target})
    if (
        len(successful_owner_changes) != 1
        or successful_owner_changes[0]["block_number"] != activation_block
        or successful_owner_changes[0]["new_owner"]
        != USDT_ETHEREUM_MULTISIG_OWNER
    ):
        raise StablecoinRemediationError("owner_initial_transition_calls_invalid")

    expected_owner_states = {
        "token_owner_at_deployment": USDT_ETHEREUM_INITIAL_OWNER,
        "token_owner_before_transition": USDT_ETHEREUM_INITIAL_OWNER,
        "token_owner_at_transition": USDT_ETHEREUM_MULTISIG_OWNER,
        "token_owner_at_observed": USDT_ETHEREUM_MULTISIG_OWNER,
    }
    if any(
        str(state_observations.get(key, "")).lower() != value
        for key, value in expected_owner_states.items()
    ):
        raise StablecoinRemediationError("owner_state_observations_invalid")
    transition_code = str(
        state_observations.get("multisig_runtime_code_at_transition", "")
    )
    observed_code = str(
        state_observations.get("multisig_runtime_code_at_observed", "")
    )
    compiled_runtime_hash = str(source_proof["compiled_runtime_code_sha256"])
    compiled_executable_hash = str(
        source_proof["compiled_runtime_executable_code_sha256"]
    )
    transition_runtime_hash = runtime_code_sha256(transition_code)
    observed_runtime_hash = runtime_code_sha256(observed_code)
    transition_executable_hash = runtime_executable_code_sha256(transition_code)
    observed_executable_hash = runtime_executable_code_sha256(observed_code)
    if (
        transition_runtime_hash != observed_runtime_hash
        or transition_executable_hash != compiled_executable_hash
        or observed_executable_hash != compiled_executable_hash
        or (
            source_proof.get("runtime_match") == "exact_match"
            and transition_runtime_hash != compiled_runtime_hash
        )
    ):
        raise StablecoinRemediationError("owner_multisig_runtime_code_mismatch")
    transaction_count = decode_evm_uint_result(
        state_observations.get("multisig_transaction_count_raw")
    )
    if transaction_count != len(multisig_transaction_rows):
        raise StablecoinRemediationError("owner_multisig_transaction_count_mismatch")

    decoded_rows: list[dict[str, Any]] = []
    for expected_id, row in enumerate(multisig_transaction_rows):
        decoded = decode_multisig_transaction_result(row.get("raw_call_result"))
        if row.get("transaction_id") != expected_id or row.get("decoded") != decoded:
            raise StablecoinRemediationError("owner_multisig_transaction_row_invalid")
        decoded_rows.append(decoded)
    executed_count = sum(row["executed"] for row in decoded_rows)
    destination_rows = [
        row for row in decoded_rows if row["destination"] == contract
    ]
    executed_destination_rows = [row for row in destination_rows if row["executed"]]
    ownership_rows = [
        row
        for row in destination_rows
        if decode_transfer_ownership_target(row["data"]) is not None
    ]
    executed_ownership_rows = [row for row in ownership_rows if row["executed"]]
    if executed_ownership_rows:
        raise StablecoinRemediationError(
            "owner_multisig_executed_transfer_ownership_detected"
        )

    proof = {
        "proof_kind": (
            "initial_eoa_complete_block_scan_plus_verified_multisig_complete_state_enumeration"
        ),
        "contract": contract,
        "deployment_block": deployment_block,
        "observed_through_block": observed_through_block,
        "owner_audit_sha256": owner_audit_sha256.lower(),
        "owner_addresses": owners,
        "transition": dict(transition),
        "initial_eoa": {
            "address": USDT_ETHEREUM_INITIAL_OWNER,
            "scan_start_block": deployment_block,
            "scan_end_block_inclusive": activation_block,
            "scanned_block_count": len(initial_block_rows),
            "scanned_transaction_count": total_transaction_count,
            "code_empty_at_every_scanned_block": True,
            "nonce_positive_and_nondecreasing_at_every_scanned_block": True,
            "owner_to_token_call_count": len(owner_to_contract_calls),
            "failed_transfer_ownership_call_count": failed_owner_changes,
            "successful_transfer_ownership_call_count": len(
                successful_owner_changes
            ),
            "successful_transfer_ownership_calls": successful_owner_changes,
        },
        "multisig": {
            "address": USDT_ETHEREUM_MULTISIG_OWNER,
            "semantic_proof": source_proof,
            "transaction_count": transaction_count,
            "enumerated_transaction_count": len(decoded_rows),
            "executed_transaction_count": executed_count,
            "token_destination_transaction_count": len(destination_rows),
            "executed_token_destination_transaction_count": len(
                executed_destination_rows
            ),
            "transfer_ownership_transaction_count": len(ownership_rows),
            "executed_transfer_ownership_transaction_count": 0,
            "runtime_verification": {
                "sourcify_runtime_match": source_proof["runtime_match"],
                "compiled_runtime_code_sha256": compiled_runtime_hash,
                "onchain_runtime_code_sha256": observed_runtime_hash,
                "runtime_executable_code_sha256": observed_executable_hash,
                "activation_and_observed_full_runtime_equal": True,
                "metadata_only_difference_from_compiled_runtime": (
                    observed_runtime_hash != compiled_runtime_hash
                ),
            },
        },
        "state_observations": dict(state_observations),
        "evidence_references": {
            role: dict(reference)
            for role, reference in sorted(evidence_references.items())
        },
        "absence_of_round_trip_change_between_equal_checkpoints_proven": True,
        "complete_owner_history_claimed": True,
    }
    proof["proof_hash"] = canonical_hash(proof)
    return proof


def owner_address_history(
    owner_audit: Mapping[str, Any],
    *,
    activation_evidence_sha256: str,
) -> list[dict[str, Any]]:
    deployment_block = int(owner_audit["deployment_block"])
    owners = list(owner_audit["owner_addresses"])
    transitions = list(owner_audit["transitions"])
    starts = [deployment_block, *[int(row["activation_block"]) for row in transitions]]
    history = []
    for index, (owner, start) in enumerate(zip(owners, starts)):
        history.append(
            {
                "address": str(owner).lower(),
                "valid_from_block": start,
                "valid_to_block_exclusive": (
                    starts[index + 1] if index + 1 < len(starts) else None
                ),
                "activation_evidence_sha256": activation_evidence_sha256,
            }
        )
    return history


def _rpc_contract_code(
    rpc: EthereumRpc,
    address: str,
    observed_through_block: int,
) -> tuple[str, str]:
    code = str(rpc.call("eth_getCode", [address, hex(observed_through_block)]))
    return code, runtime_code_sha256(code)


def build_usdc_implementation_history(
    rpc: EthereumRpc,
    *,
    proxy_payload: Mapping[str, Any],
    proxy_evidence_sha256: str,
    implementation_payloads: Mapping[str, Mapping[str, Any]],
    implementation_evidence_sha256: Mapping[str, str],
    observed_through_block: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    del proxy_evidence_sha256
    deployment = proxy_payload["deployment"]
    deployment_tx_hash = str(deployment["transactionHash"]).lower()
    deployment_tx = rpc.call("eth_getTransactionByHash", [deployment_tx_hash])
    if not isinstance(deployment_tx, Mapping):
        raise StablecoinRemediationError("usdc_proxy_deployment_tx_missing")
    tx_input = str(deployment_tx.get("input", "")).lower().removeprefix("0x")
    if len(tx_input) < 64:
        raise StablecoinRemediationError("usdc_proxy_constructor_input_invalid")
    initial_address = "0x" + tx_input[-40:]
    logs, segments = fetch_ethereum_logs(
        rpc,
        address=str(proxy_payload["address"]),
        topics=[USDC_UPGRADED_TOPIC],
        start_block=int(deployment["blockNumber"]),
        end_block_exclusive=observed_through_block + 1,
    )
    activation_rows = [
        {
            "implementation_address": initial_address,
            "block_number": int(deployment["blockNumber"]),
            "transaction_index": int(deployment["transactionIndex"]),
            "event_index": -1,
            "transaction_hash": deployment_tx_hash,
            "activation_kind": "proxy_constructor_argument",
        }
    ]
    for log in logs:
        activation_rows.append(
            {
                "implementation_address": data_address(str(log["data"])),
                "block_number": int(str(log["blockNumber"]), 16),
                "transaction_index": int(str(log["transactionIndex"]), 16),
                "event_index": int(str(log["logIndex"]), 16),
                "transaction_hash": str(log["transactionHash"]).lower(),
                "activation_kind": "Upgraded_event",
            }
        )
    entries = []
    runtime_codes: dict[str, str] = {}
    for activation in activation_rows:
        address = str(activation["implementation_address"]).lower()
        payload = implementation_payloads.get(address)
        source_hash = implementation_evidence_sha256.get(address)
        if payload is None or source_hash is None:
            raise StablecoinRemediationError(
                f"usdc_implementation_evidence_missing:{address}"
            )
        code, code_hash = _rpc_contract_code(rpc, address, observed_through_block)
        runtime_codes[address] = code
        proof = verified_source_semantic_proof(
            payload,
            source_artifact_sha256=source_hash,
            native_mint_events=["mint"],
            native_burn_events=["burn"],
            zero_transfer_emission="paired",
        )
        entries.append(
            {
                "implementation_address": address,
                "activated_at": {
                    "block_number": activation["block_number"],
                    "transaction_index": activation["transaction_index"],
                    "event_index": activation["event_index"],
                    "transaction_hash": activation["transaction_hash"],
                    "activation_kind": activation["activation_kind"],
                },
                "verified_source_artifact_sha256": source_hash,
                "abi_sha256": abi_sha256(payload["abi"]),
                "runtime_code_sha256": code_hash,
                "verification_match": payload["match"],
                "semantic_proof": proof,
            }
        )
    proxy_resolution = proxy_payload.get("proxyResolution", {})
    current = (
        proxy_resolution.get("implementations", [{}])[0].get("address")
        if isinstance(proxy_resolution, Mapping)
        else None
    )
    if not current or str(current).lower() != entries[-1]["implementation_address"]:
        raise StablecoinRemediationError("usdc_current_implementation_mismatch")
    history = {
        "complete": True,
        "deployment_block": int(deployment["blockNumber"]),
        "observed_through_block": observed_through_block,
        "is_proxy": True,
        "proxy_type": "ZeppelinOSProxy",
        "implementation_slot": USDC_IMPLEMENTATION_SLOT,
        "upgrade_event_count": len(entries) - 1,
        "entries": entries,
    }
    history["timeline_hash"] = implementation_timeline_hash(history)
    raw_evidence = {
        "proxy_deployment_transaction": deployment_tx,
        "upgraded_logs": logs,
        "query_segments": segments,
        "runtime_codes": runtime_codes,
        "observed_through_block": observed_through_block,
    }
    return history, raw_evidence


def build_nonproxy_implementation_history(
    rpc: EthereumRpc,
    *,
    contract_payload: Mapping[str, Any],
    source_artifact_sha256: str,
    observed_through_block: int,
    native_mint_events: Sequence[str],
    native_burn_events: Sequence[str],
    zero_transfer_emission: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    address = str(contract_payload["address"]).lower()
    deployment = contract_payload["deployment"]
    code, code_hash = _rpc_contract_code(rpc, address, observed_through_block)
    proof = verified_source_semantic_proof(
        contract_payload,
        source_artifact_sha256=source_artifact_sha256,
        native_mint_events=native_mint_events,
        native_burn_events=native_burn_events,
        zero_transfer_emission=zero_transfer_emission,
    )
    entries = [
        {
            "implementation_address": address,
            "activated_at": {
                "block_number": int(deployment["blockNumber"]),
                "transaction_index": int(deployment["transactionIndex"]),
                "event_index": -1,
                "transaction_hash": str(deployment["transactionHash"]).lower(),
                "activation_kind": "contract_deployment",
            },
            "verified_source_artifact_sha256": source_artifact_sha256,
            "abi_sha256": abi_sha256(contract_payload["abi"]),
            "runtime_code_sha256": code_hash,
            "verification_match": contract_payload["match"],
            "semantic_proof": proof,
        }
    ]
    history = {
        "complete": True,
        "deployment_block": int(deployment["blockNumber"]),
        "observed_through_block": observed_through_block,
        "is_proxy": False,
        "proxy_type": "none",
        "upgrade_event_count": 0,
        "entries": entries,
    }
    history["timeline_hash"] = implementation_timeline_hash(history)
    return history, {"runtime_code": code}


def fetch_trongrid_contract_events(
    client: PublicEvidenceClient,
    *,
    event_name: str,
    contract_address: str = TRON_USDT_BASE58,
    base_url: str = DEFAULT_TRONGRID_URL,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "event_name": event_name,
            "only_confirmed": "true",
            "limit": 200,
            "order_by": "block_timestamp,asc",
        }
    )
    payload = client.json(
        f"{base_url.rstrip('/')}/v1/contracts/{contract_address}/events?{query}"
    )
    if (
        not isinstance(payload, Mapping)
        or payload.get("success") is not True
        or not isinstance(payload.get("data"), list)
        or not isinstance(payload.get("meta"), Mapping)
        or payload["meta"].get("fingerprint")
    ):
        raise StablecoinRemediationError(
            f"trongrid_contract_event_query_incomplete:{event_name}"
        )
    return dict(payload)


def parse_tronscan_verified_contract(
    contract_payload: Mapping[str, Any],
    code_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[Any], str]:
    rows = contract_payload.get("data", [])
    code = code_payload.get("data", {})
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], Mapping)
        or not isinstance(code, Mapping)
    ):
        raise StablecoinRemediationError("tronscan_contract_payload_invalid")
    contract = dict(rows[0])
    code = dict(code)
    if (
        contract.get("address") != TRON_USDT_BASE58
        or contract.get("verify_status") != 2
        or contract.get("is_proxy") is not False
        or code.get("address") != TRON_USDT_BASE58
        or code.get("verify_status") != 2
    ):
        raise StablecoinRemediationError("tronscan_contract_not_verified_nonproxy")
    raw_abi = code.get("abi")
    if isinstance(raw_abi, str):
        try:
            abi = json.loads(raw_abi)
        except json.JSONDecodeError as exc:
            raise StablecoinRemediationError("tronscan_abi_invalid") from exc
    else:
        abi = raw_abi
    if isinstance(abi, Mapping) and isinstance(abi.get("entrys"), list):
        abi = abi["entrys"]
    if not isinstance(abi, list) or not abi:
        raise StablecoinRemediationError("tronscan_abi_not_list")
    bytecode = str(code.get("byteCode", ""))
    bytecode_hash = runtime_code_sha256(bytecode)
    creator = contract.get("creator", {})
    if (
        not isinstance(creator, Mapping)
        or creator.get("address") != TRON_INITIAL_OWNER
        or not str(creator.get("txHash", ""))
    ):
        raise StablecoinRemediationError("tronscan_contract_creator_invalid")
    return contract, code, abi, bytecode_hash


def build_tron_implementation_history(
    *,
    contract_payload: Mapping[str, Any],
    code_payload: Mapping[str, Any],
    deployment_info: Mapping[str, Any],
    code_artifact_sha256: str,
    observed_through_block: int,
    ownership_payload: Mapping[str, Any],
    ownership_evidence_sha256: str,
    deprecate_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    contract, code, abi, bytecode_hash = parse_tronscan_verified_contract(
        contract_payload, code_payload
    )
    creator_tx = str(contract["creator"]["txHash"])
    if (
        not isinstance(deployment_info.get("blockNumber"), int)
        or deployment_info.get("result") not in {None, "SUCCESS"}
        or str(deployment_info.get("id", "")).lower() != creator_tx.lower()
    ):
        raise StablecoinRemediationError("tron_deployment_transaction_info_invalid")
    deployment_block = int(deployment_info["blockNumber"])
    ownership_rows = ownership_payload.get("data", [])
    deprecate_rows = deprecate_payload.get("data", [])
    if (
        not isinstance(ownership_rows, list)
        or len(ownership_rows) != 1
        or not isinstance(ownership_rows[0], Mapping)
        or not isinstance(deprecate_rows, list)
        or deprecate_rows
    ):
        raise StablecoinRemediationError("tron_ownership_or_deprecation_history_invalid")
    ownership = ownership_rows[0]
    result = ownership.get("result", {})
    if not isinstance(result, Mapping):
        raise StablecoinRemediationError("tron_ownership_event_result_invalid")
    previous_owner = tron_hex_to_base58(str(result.get("previousOwner", "")))
    new_owner = tron_hex_to_base58(str(result.get("newOwner", "")))
    activation_block = int(ownership["block_number"])
    if previous_owner != TRON_INITIAL_OWNER or new_owner != TRON_SECOND_OWNER:
        raise StablecoinRemediationError("tron_owner_addresses_unexpected")
    address_history = [
        {
            "address": TRON_INITIAL_OWNER.lower(),
            "valid_from_block": deployment_block,
            "valid_to_block_exclusive": activation_block,
            "activation_evidence_sha256": ownership_evidence_sha256,
        },
        {
            "address": TRON_SECOND_OWNER.lower(),
            "valid_from_block": activation_block,
            "valid_to_block_exclusive": None,
            "activation_evidence_sha256": ownership_evidence_sha256,
        },
    ]
    proof = {
        "proof_kind": "verified_bytecode_and_complete_event_overlap",
        "parser": "tronscan_verified_abi_runtime_plus_complete_overlap_v0.1",
        "source_artifact_sha256": code_artifact_sha256,
        "native_mint_event_calls": ["issue"],
        "native_burn_event_calls": ["redeem"],
        "supply_storage_writes": [
            "supply_change_bound_to_issue_redeem_and_zero_transfer_overlap",
            "owner_balance_change_bound_to_issue_redeem_and_zero_transfer_overlap",
        ],
        "zero_transfer_emission": "paired",
        "limitations": [
            "no_solidity_ast_in_tronscan_response",
            "storage_semantics_require_complete_native_zero_event_overlap",
        ],
    }
    proof["proof_hash"] = canonical_hash(proof)
    entry = {
        "implementation_address": TRON_USDT_BASE58.lower(),
        "activated_at": {
            "block_number": deployment_block,
            "transaction_index": 0,
            "event_index": -1,
            "transaction_hash": creator_tx.lower(),
            "activation_kind": "contract_deployment",
        },
        "verified_source_artifact_sha256": code_artifact_sha256,
        "abi_sha256": abi_sha256(abi),
        "runtime_code_sha256": bytecode_hash,
        "verification_match": "match",
        "semantic_proof": proof,
    }
    history = {
        "complete": True,
        "deployment_block": deployment_block,
        "observed_through_block": observed_through_block,
        "is_proxy": False,
        "proxy_type": "none",
        "upgrade_event_count": 0,
        "entries": [entry],
    }
    history["timeline_hash"] = implementation_timeline_hash(history)
    raw_evidence = {
        "deployment_transaction_info": deployment_info,
        "ownership_event": ownership,
        "deprecate_event_count": 0,
        "tronscan_verify_status": contract["verify_status"],
        "tronscan_is_proxy": contract["is_proxy"],
        "runtime_bytecode_sha256": bytecode_hash,
        "abi_sha256": abi_sha256(abi),
        "observed_through_block": observed_through_block,
    }
    return history, address_history, raw_evidence


def supply_overlap_audit(
    native_events: Iterable[Mapping[str, Any]],
    zero_events: Iterable[Mapping[str, Any]],
    *,
    method: str,
    implementation_addresses: Sequence[str],
    evidence_hashes: Sequence[str],
) -> dict[str, Any]:
    """Pair native and zero-address supply logs without discarding zero-only flow."""

    def identity(event: Mapping[str, Any]) -> tuple[str, str, str]:
        name = str(event.get("event_name", "")).lower()
        if name in {"issue", "mint"}:
            direction = "mint"
        elif name in {"redeem", "burn"}:
            direction = "burn"
        elif name == "transfer":
            from_address = str(event.get("from_address", "")).lower()
            direction = "mint" if from_address in {
                "0x0000000000000000000000000000000000000000",
                TRON_ZERO_BASE58.lower(),
            } else "burn"
        else:
            raise ValueError("supply_overlap_event_name_invalid")
        amount = str(event.get("raw_amount", event.get("amount", "")))
        return str(event.get("transaction_hash", "")).lower(), amount, direction

    native_counts: dict[tuple[str, str, str], int] = {}
    zero_counts: dict[tuple[str, str, str], int] = {}
    native_count = 0
    zero_count = 0
    zero_amount_count = 0
    for event in native_events:
        key = identity(event)
        native_counts[key] = native_counts.get(key, 0) + 1
        native_count += 1
    for event in zero_events:
        key = identity(event)
        zero_counts[key] = zero_counts.get(key, 0) + 1
        zero_count += 1
        try:
            raw_amount = int(str(event.get("raw_amount", event.get("amount", ""))))
        except ValueError as exc:
            raise ValueError("supply_overlap_raw_amount_invalid") from exc
        if raw_amount < 0:
            raise ValueError("supply_overlap_raw_amount_negative")
        zero_amount_count += raw_amount == 0
    paired_count = sum(
        min(count, zero_counts.get(key, 0)) for key, count in native_counts.items()
    )
    ambiguous = sum(
        max(0, count - 1) + max(0, zero_counts.get(key, 0) - 1)
        for key, count in native_counts.items()
        if count > 1 or zero_counts.get(key, 0) > 1
    )
    audit = {
        "complete": ambiguous == 0,
        "method": method,
        "pair_identity": "transaction_hash+raw_amount+supply_direction",
        "native_event_count": native_count,
        "zero_transfer_event_count": zero_count,
        "paired_native_event_count": paired_count,
        "unmatched_native_event_count": native_count - paired_count,
        "unmatched_zero_transfer_event_count": zero_count - paired_count,
        "ambiguous_pair_count": ambiguous,
        "duplicate_suppression_policy": "native_supply_event_precedence",
        "suppressed_duplicate_count": paired_count,
        "materialized_lineage_event_count": zero_count,
        "materialized_economic_event_count": zero_count - zero_amount_count,
        "materialized_zero_amount_event_count_excluded": zero_amount_count,
        "evidence_artifact_sha256": sorted(set(evidence_hashes)),
        "implementation_addresses_proven": [
            str(value).lower() for value in implementation_addresses
        ],
    }
    audit["audit_hash"] = canonical_hash(audit)
    return audit


@dataclass(frozen=True)
class ChainHeader:
    chain: str
    block_number: int
    block_hash: str
    timestamp: int
    producer: str | None = None


class HeaderStore(AbstractContextManager[Any]):
    """Resume-safe header cache. The path must be on WSL ext4, not ExFAT."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> "HeaderStore":
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS headers (
                chain TEXT NOT NULL,
                block_number INTEGER NOT NULL,
                block_hash TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                producer TEXT,
                PRIMARY KEY (chain, block_number)
            )
            """
        )
        self.connection.commit()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if self.connection is not None:
            self.connection.close()
        return False

    @property
    def db(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("header_store_not_open")
        return self.connection

    def put_many(self, headers: Iterable[ChainHeader]) -> None:
        normalized: dict[tuple[str, int], ChainHeader] = {}
        for header in headers:
            expected = ChainHeader(
                header.chain,
                header.block_number,
                header.block_hash.lower(),
                header.timestamp,
                header.producer.lower() if header.producer else None,
            )
            key = (expected.chain, expected.block_number)
            prior = normalized.get(key)
            if prior is not None and prior != expected:
                raise StablecoinRemediationError("header_store_conflict")
            normalized[key] = expected
        if not normalized:
            return
        existing: dict[tuple[str, int], ChainHeader] = {}
        chains = {chain for chain, _ in normalized}
        for chain in chains:
            numbers = [number for row_chain, number in normalized if row_chain == chain]
            existing.update(
                {
                    (chain, number): header
                    for number, header in self.get_many(chain, numbers).items()
                }
            )
        for key, header in existing.items():
            if normalized[key] != header:
                raise StablecoinRemediationError("header_store_conflict")
        missing = [header for key, header in normalized.items() if key not in existing]
        self.db.executemany(
            """
            INSERT INTO headers(chain, block_number, block_hash, timestamp, producer)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    header.chain,
                    header.block_number,
                    header.block_hash,
                    header.timestamp,
                    header.producer,
                )
                for header in missing
            ),
        )
        self.db.commit()

    def get(self, chain: str, block_number: int) -> ChainHeader | None:
        row = self.db.execute(
            """
            SELECT chain, block_number, block_hash, timestamp, producer
            FROM headers WHERE chain=? AND block_number=?
            """,
            (chain, block_number),
        ).fetchone()
        return ChainHeader(*row) if row else None

    def get_many(
        self,
        chain: str,
        block_numbers: Iterable[int],
    ) -> dict[int, ChainHeader]:
        numbers = sorted(set(block_numbers))
        result: dict[int, ChainHeader] = {}
        for offset in range(0, len(numbers), 800):
            batch = numbers[offset : offset + 800]
            placeholders = ",".join("?" for _ in batch)
            cursor = self.db.execute(
                f"""
                SELECT chain, block_number, block_hash, timestamp, producer
                FROM headers
                WHERE chain=? AND block_number IN ({placeholders})
                """,
                [chain, *batch],
            )
            for row in cursor:
                header = ChainHeader(*row)
                result[header.block_number] = header
        return result

    def missing(self, chain: str, block_numbers: Iterable[int]) -> Iterator[int]:
        requested = sorted(set(block_numbers))
        for offset in range(0, len(requested), 50_000):
            batch = requested[offset : offset + 50_000]
            present = self.get_many(chain, batch)
            for block_number in batch:
                if block_number not in present:
                    yield block_number


def parse_ethereum_header(payload: Mapping[str, Any]) -> ChainHeader:
    try:
        number = int(str(payload["number"]), 16)
        timestamp = int(str(payload["timestamp"]), 16)
        block_hash = str(payload["hash"]).lower()
    except (KeyError, TypeError, ValueError) as exc:
        raise StablecoinRemediationError("ethereum_header_invalid") from exc
    rendered = block_hash.removeprefix("0x")
    if len(rendered) != 64 or any(char not in _HEX for char in rendered):
        raise StablecoinRemediationError("ethereum_header_hash_invalid")
    return ChainHeader("ethereum", number, block_hash, timestamp)


def fetch_ethereum_headers(
    rpc: EthereumRpc,
    store: HeaderStore,
    block_numbers: Iterable[int],
    *,
    batch_size: int = 250,
    parallel_requests: int = 1,
) -> int:
    if batch_size < 1 or batch_size > 1000:
        raise ValueError("ethereum_header_batch_size_invalid")
    if parallel_requests < 1 or parallel_requests > 8:
        raise ValueError("ethereum_header_parallel_requests_invalid")
    missing = list(store.missing("ethereum", block_numbers))
    fetched = 0

    def materialize(
        batch: Sequence[int],
        payloads: Sequence[Any],
    ) -> list[ChainHeader]:
        if len(payloads) != len(batch):
            raise StablecoinRemediationError("ethereum_header_batch_incomplete")
        headers = []
        for expected, payload in zip(batch, payloads):
            if not isinstance(payload, Mapping):
                raise StablecoinRemediationError("ethereum_header_missing")
            header = parse_ethereum_header(payload)
            if header.block_number != expected:
                raise StablecoinRemediationError(
                    "ethereum_header_number_mismatch"
                )
            headers.append(header)
        return headers

    def requests(batch: Sequence[int]) -> list[tuple[str, list[Any]]]:
        return [
            ("eth_getBlockByNumber", [hex(number), False])
            for number in batch
        ]

    if parallel_requests == 1:
        for offset in range(0, len(missing), batch_size):
            batch = missing[offset : offset + batch_size]
            headers = materialize(batch, rpc.batch(requests(batch)))
            store.put_many(headers)
            fetched += len(headers)
        return fetched

    if not isinstance(getattr(rpc, "url", None), str):
        raise ValueError("ethereum_header_parallel_rpc_url_missing")

    def fetch_batch(batch: Sequence[int]) -> list[Any]:
        worker = EthereumRpc(rpc.url)
        return worker.batch(requests(batch))

    batches = (
        missing[offset : offset + batch_size]
        for offset in range(0, len(missing), batch_size)
    )
    pending: deque[tuple[list[int], Future[list[Any]]]] = deque()
    with ThreadPoolExecutor(max_workers=parallel_requests) as executor:
        for _ in range(parallel_requests):
            batch = next(batches, None)
            if batch is None:
                break
            pending.append((batch, executor.submit(fetch_batch, batch)))
        while pending:
            batch, future = pending.popleft()
            headers = materialize(batch, future.result())
            store.put_many(headers)
            fetched += len(headers)
            following = next(batches, None)
            if following is not None:
                pending.append(
                    (following, executor.submit(fetch_batch, following))
                )
    return fetched


def parse_tron_header(payload: Mapping[str, Any]) -> ChainHeader:
    try:
        block_number = int(payload["block_header"]["raw_data"]["number"])
        timestamp_ms = int(payload["block_header"]["raw_data"]["timestamp"])
        producer = str(payload["block_header"]["raw_data"]["witness_address"])
        block_hash = str(payload["blockID"]).lower()
    except (KeyError, TypeError, ValueError) as exc:
        raise StablecoinRemediationError("tron_header_invalid") from exc
    if (
        len(block_hash) != 64
        or any(char not in _HEX for char in block_hash)
        or not producer
        or timestamp_ms % 1000 != 0
    ):
        raise StablecoinRemediationError("tron_header_fields_invalid")
    return ChainHeader(
        "tron",
        block_number,
        block_hash,
        timestamp_ms // 1000,
        producer,
    )


def parse_tronscan_header(payload: Mapping[str, Any]) -> ChainHeader:
    try:
        block_number = int(payload["number"])
        timestamp_ms = int(payload["timestamp"])
        block_hash = str(payload["hash"]).lower()
        producer = "41" + tron_base58_to_hex(
            str(payload["witnessAddress"])
        ).removeprefix("0x")
    except (KeyError, TypeError, ValueError) as exc:
        raise StablecoinRemediationError("tronscan_header_invalid") from exc
    if (
        payload.get("confirmed") is not True
        or len(block_hash) != 64
        or any(char not in _HEX for char in block_hash)
        or timestamp_ms % 1000 != 0
    ):
        raise StablecoinRemediationError("tronscan_header_fields_invalid")
    return ChainHeader(
        "tron",
        block_number,
        block_hash,
        timestamp_ms // 1000,
        producer,
    )


def fetch_tronscan_header_page(
    client: PublicEvidenceClient,
    store: HeaderStore,
    *,
    event_block_number: int,
    event_timestamp_ms: int,
    offset: int,
    page_size: int = 50,
    base_url: str = TRONSCAN_BLOCK_API,
) -> list[ChainHeader]:
    if (
        event_block_number < 0
        or event_timestamp_ms <= 0
        or event_timestamp_ms % 1000 != 0
        or offset < 0
        or page_size < 1
        or page_size > 50
    ):
        raise ValueError("tronscan_header_page_request_invalid")
    query = urllib.parse.urlencode(
        {
            "sort": "number",
            "limit": page_size,
            "start": offset,
            "start_timestamp": event_timestamp_ms,
        }
    )
    payload = client.json(f"{base_url}?{query}")
    if not isinstance(payload, Mapping):
        raise StablecoinRemediationError("tronscan_header_response_not_object")
    rows = payload.get("data")
    if (
        not isinstance(rows, list)
        or len(rows) != page_size
        or any(not isinstance(row, Mapping) for row in rows)
    ):
        raise StablecoinRemediationError("tronscan_header_page_incomplete")
    headers = [parse_tronscan_header(row) for row in rows]
    expected_start = event_block_number + offset
    for position, header in enumerate(headers):
        if header.block_number != expected_start + position:
            raise StablecoinRemediationError(
                "tronscan_header_page_not_contiguous"
            )
    if offset == 0 and headers[0].timestamp * 1000 != event_timestamp_ms:
        raise StablecoinRemediationError("tronscan_event_timestamp_mismatch")
    store.put_many(headers)
    return headers


def fetch_tron_header(
    client: PublicEvidenceClient,
    store: HeaderStore,
    block_number: int,
    *,
    base_url: str = DEFAULT_TRONGRID_URL,
) -> ChainHeader:
    cached = store.get("tron", block_number)
    if cached is not None:
        return cached
    payload = client.json(
        f"{base_url.rstrip('/')}/wallet/getblockbynum",
        method="POST",
        payload={"num": block_number},
    )
    if not isinstance(payload, Mapping):
        raise StablecoinRemediationError("tron_header_response_not_object")
    header = parse_tron_header(payload)
    if header.block_number != block_number:
        raise StablecoinRemediationError("tron_header_number_mismatch")
    store.put_many([header])
    return header


def tron_confirmation_headers(
    client: PublicEvidenceClient,
    store: HeaderStore,
    event_block_number: int,
    *,
    event_timestamp_ms: int | None = None,
    distinct_subsequent_producers: int = 18,
    maximum_scan_blocks: int = 256,
    tronscan_page_size: int = 50,
) -> tuple[ChainHeader, list[ChainHeader]]:
    if (
        distinct_subsequent_producers < 1
        or maximum_scan_blocks < 1
        or tronscan_page_size < 1
        or tronscan_page_size > 50
    ):
        raise ValueError("tron_confirmation_policy_invalid")
    if event_timestamp_ms is not None:
        event_header: ChainHeader | None = None
        selected: list[ChainHeader] = []
        seen: set[str] = set()
        total_header_count = maximum_scan_blocks + 1
        for offset in range(total_header_count):
            number = event_block_number + offset
            header = store.get("tron", number)
            if header is None:
                page_size = min(
                    tronscan_page_size,
                    total_header_count - offset,
                )
                fetch_tronscan_header_page(
                    client,
                    store,
                    event_block_number=event_block_number,
                    event_timestamp_ms=event_timestamp_ms,
                    offset=offset,
                    page_size=page_size,
                )
                header = store.get("tron", number)
            if header is None:
                raise StablecoinRemediationError(
                    "tronscan_header_page_cache_incomplete"
                )
            if event_header is None:
                event_header = header
                if header.block_number != event_block_number:
                    raise StablecoinRemediationError(
                        "tron_event_header_number_mismatch"
                    )
                if header.timestamp * 1000 != event_timestamp_ms:
                    raise StablecoinRemediationError(
                        "tronscan_event_timestamp_mismatch"
                    )
                if header.producer is None:
                    raise StablecoinRemediationError(
                        "tron_event_producer_missing"
                    )
                seen.add(header.producer)
                continue
            if header.producer is None or header.producer in seen:
                continue
            seen.add(header.producer)
            selected.append(header)
            if len(selected) == distinct_subsequent_producers:
                return event_header, selected
        raise StablecoinRemediationError("tron_distinct_sr_confirmation_not_found")

    event_header = fetch_tron_header(client, store, event_block_number)
    if event_header.producer is None:
        raise StablecoinRemediationError("tron_event_producer_missing")
    selected: list[ChainHeader] = []
    seen = {event_header.producer}
    for number in range(
        event_block_number + 1,
        event_block_number + maximum_scan_blocks + 1,
    ):
        header = fetch_tron_header(client, store, number)
        if header.producer is None or header.producer in seen:
            continue
        seen.add(header.producer)
        selected.append(header)
        if len(selected) == distinct_subsequent_producers:
            return event_header, selected
    raise StablecoinRemediationError("tron_distinct_sr_confirmation_not_found")


def ethereum_confirmation_fields(
    event: Mapping[str, Any],
    store: HeaderStore,
    *,
    evidence_sha256: str,
) -> dict[str, Any]:
    block_number = int(event["block_number"])
    event_header = store.get("ethereum", block_number)
    confirmation = store.get("ethereum", block_number + 64)
    if event_header is None or confirmation is None:
        raise StablecoinRemediationError("ethereum_confirmation_header_missing")
    declared_hash = str(event.get("block_hash", "")).lower()
    if declared_hash != event_header.block_hash:
        raise StablecoinRemediationError("ethereum_event_block_reorg_or_mismatch")
    return {
        **event,
        "block_hash": event_header.block_hash,
        "block_timestamp": utc_text(event_header.timestamp),
        "available_at": utc_text(confirmation.timestamp),
        "availability_policy": ETHEREUM_AVAILABILITY_POLICY,
        "confirmation_block_number": confirmation.block_number,
        "confirmation_block_hash": confirmation.block_hash,
        "confirmation_block_timestamp": utc_text(confirmation.timestamp),
        "confirmation_evidence_sha256": evidence_sha256,
        "canonical_block_rechecked": True,
        "removed": False,
    }


def tron_confirmation_fields(
    event: Mapping[str, Any],
    event_header: ChainHeader,
    subsequent: Sequence[ChainHeader],
    *,
    evidence_sha256: str,
) -> dict[str, Any]:
    if len(subsequent) != 18 or len({row.producer for row in subsequent}) != 18:
        raise StablecoinRemediationError("tron_confirmation_sr_set_invalid")
    if event_header.producer in {row.producer for row in subsequent}:
        raise StablecoinRemediationError("tron_event_producer_reused_in_confirmation")
    confirmation = subsequent[-1]
    return {
        **event,
        "block_hash": event_header.block_hash,
        "block_timestamp": utc_text(event_header.timestamp),
        "available_at": utc_text(confirmation.timestamp),
        "availability_policy": TRON_AVAILABILITY_POLICY,
        "confirmation_block_number": confirmation.block_number,
        "confirmation_block_hash": confirmation.block_hash,
        "confirmation_block_timestamp": utc_text(confirmation.timestamp),
        "confirmation_evidence_sha256": evidence_sha256,
        "canonical_block_rechecked": True,
        "event_block_producer": event_header.producer,
        "confirmation_acknowledgement_count": 19,
        "confirmation_subsequent_distinct_sr_count": 18,
        "confirmation_subsequent_sr_addresses": [
            str(row.producer) for row in subsequent
        ],
        "confirmation_block_producer": confirmation.producer,
        "removed": False,
    }


def implementation_timeline_hash(history: Mapping[str, Any]) -> str:
    basis = {
        "deployment_block": history["deployment_block"],
        "observed_through_block": history["observed_through_block"],
        "is_proxy": history["is_proxy"],
        "proxy_type": history["proxy_type"],
        "entries": history["entries"],
    }
    return canonical_hash(basis)


def source_spec(source_id: str) -> Any:
    return next(spec for spec in SOURCE_SPECS if spec.source_id == source_id)


def remediated_source_version() -> str:
    return STABLECOIN_CHAIN_SOURCE_VERSION
