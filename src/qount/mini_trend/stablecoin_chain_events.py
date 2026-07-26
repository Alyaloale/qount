"""Public-chain collector for the stablecoin marginal-flow G0.

The collector intentionally starts with native supply events only.  It embeds
the raw provider record beside every normalized event and marks zero-address,
treasury-transfer, proxy-history and exact-finality coverage incomplete unless
those claims are genuinely available.  The downstream G0 therefore fails
closed instead of treating transport success as semantic completeness.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from qount.contracts import canonical_hash
from qount.mini_trend.stablecoin_impulse_g0 import (
    SOURCE_SPECS,
)


DEFAULT_ETHEREUM_RPC_URL = "https://rpc.mevblocker.io"
DEFAULT_TRONGRID_URL = "https://api.trongrid.io"
TRON_USDT_BASE58_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRON_USDT_HEX_ADDRESS = "41a614f803b6fd780986a42c78ec9c7f77e6ded13c"
LEGACY_STABLECOIN_CHAIN_SOURCE_VERSION = "stablecoin_chain_event_source_v0.1"

_ETHEREUM_EVENT_SIGNATURES = {
    "usdt_ethereum": {
        "Issue(uint256)": (
            "Issue",
            "0xcb8241adb0c3fdb35b70c24ce35c5eb0c17af7431c99f827d44a445ca624176a",
        ),
        "Redeem(uint256)": (
            "Redeem",
            "0x702d5967f45f6513a38ffc42d6ba9bf230bd40e8f53b16363c7eb4fd2deb9a44",
        ),
    },
    "usdc_ethereum": {
        "Mint(address,address,uint256)": (
            "Mint",
            "0xab8530f87dc9b59234c4623bf917212bb2536d647574c8e7e5da92c2ede0c9f8",
        ),
        "Burn(address,uint256)": (
            "Burn",
            "0xcc16f5dbb4873280815c1ee09dbd06736cffcc184412cf7a71a0fdb75d397ca5",
        ),
    },
}


class PublicChainCollectionError(RuntimeError):
    """Raised when a bounded public-chain collection cannot be completed."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _parse_utc(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("collection timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hostname(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("public chain endpoint must be an HTTPS URL")
    return parsed.hostname.lower()


class _JsonClient:
    def __init__(self, *, timeout_seconds: float = 30.0, attempts: int = 4) -> None:
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: object | None = None,
    ) -> Any:
        body = None if payload is None else _canonical_bytes(payload)
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "Content-Type": "application/json",
                "User-Agent": "qount-stablecoin-g0-collector/0.1",
            },
        )
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                    content_encoding = str(
                        response.headers.get("Content-Encoding", "")
                    ).strip().lower()
                if content_encoding == "gzip":
                    raw = gzip.decompress(raw)
                elif content_encoding not in {"", "identity"}:
                    raise PublicChainCollectionError(
                        f"unsupported_content_encoding:{content_encoding}"
                    )
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read(512).decode("utf-8", errors="replace")
                except OSError:
                    detail = ""
                last_error = PublicChainCollectionError(
                    f"http_{exc.code}:{detail[:256]}"
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt + 1 < self.attempts:
                time.sleep(min(2**attempt, 8))
        raise PublicChainCollectionError(
            f"public_json_request_failed:{type(last_error).__name__}:{last_error}"
        )


class EthereumRpc:
    def __init__(self, url: str, *, client: _JsonClient | None = None) -> None:
        self.url = url
        self.host = _hostname(url)
        self.client = client or _JsonClient()
        self.request_id = 0

    def call(self, method: str, params: Sequence[Any]) -> Any:
        self.request_id += 1
        response = self.client.request(
            self.url,
            method="POST",
            payload={
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method,
                "params": list(params),
            },
        )
        if not isinstance(response, Mapping):
            raise PublicChainCollectionError("ethereum_rpc_response_not_object")
        if response.get("error") is not None:
            error = response["error"]
            message = error.get("message") if isinstance(error, Mapping) else str(error)
            raise PublicChainCollectionError(f"ethereum_rpc_error:{message}")
        return response.get("result")

    def batch(self, requests: Sequence[tuple[str, Sequence[Any]]]) -> list[Any]:
        payload = []
        order: list[int] = []
        for method, params in requests:
            self.request_id += 1
            order.append(self.request_id)
            payload.append(
                {
                    "jsonrpc": "2.0",
                    "id": self.request_id,
                    "method": method,
                    "params": list(params),
                }
            )
        response = self.client.request(self.url, method="POST", payload=payload)
        if not isinstance(response, list):
            raise PublicChainCollectionError("ethereum_rpc_batch_response_not_list")
        indexed = {int(row["id"]): row for row in response if isinstance(row, Mapping)}
        results: list[Any] = []
        for request_id in order:
            row = indexed.get(request_id)
            if row is None or row.get("error") is not None:
                raise PublicChainCollectionError("ethereum_rpc_batch_member_failed")
            results.append(row.get("result"))
        return results


def _ethereum_block_at_or_after(rpc: EthereumRpc, timestamp: int) -> int:
    latest = int(rpc.call("eth_blockNumber", []), 16)
    low = 0
    high = latest
    while low < high:
        middle = (low + high) // 2
        block = rpc.call("eth_getBlockByNumber", [hex(middle), False])
        if block is None:
            low = middle + 1
            continue
        if int(block["timestamp"], 16) < timestamp:
            low = middle + 1
        else:
            high = middle
    return low


def _ethereum_topics(rpc: EthereumRpc, source_id: str) -> tuple[dict[str, str], dict[str, str]]:
    del rpc
    signatures = _ETHEREUM_EVENT_SIGNATURES[source_id]
    topic_to_name: dict[str, str] = {}
    signature_to_topic: dict[str, str] = {}
    for signature, (event_name, topic) in signatures.items():
        topic_to_name[topic] = event_name
        signature_to_topic[signature] = topic
    return topic_to_name, signature_to_topic


def _ethereum_logs(
    rpc: EthereumRpc,
    *,
    address: str,
    topics: Sequence[str],
    start_block: int,
    end_block_exclusive: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cursor = start_block
    maximum_step = 100_000
    step = maximum_step
    logs: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    while cursor < end_block_exclusive:
        end_block = min(end_block_exclusive - 1, cursor + step - 1)
        try:
            rows = rpc.call(
                "eth_getLogs",
                [
                    {
                        "address": address,
                        "fromBlock": hex(cursor),
                        "toBlock": hex(end_block),
                        "topics": [list(topics)],
                    }
                ],
            )
        except PublicChainCollectionError:
            if step <= 1_000:
                raise
            step = max(1_000, step // 2)
            continue
        if not isinstance(rows, list):
            raise PublicChainCollectionError("ethereum_logs_result_not_list")
        logs.extend(row for row in rows if isinstance(row, Mapping))
        segments.append(
            {
                "from_block": cursor,
                "to_block": end_block,
                "event_count": len(rows),
            }
        )
        cursor = end_block + 1
        step = min(maximum_step, step * 2)
    return logs, segments


def _ethereum_block_metadata(
    rpc: EthereumRpc, block_numbers: Sequence[int]
) -> dict[int, Mapping[str, Any]]:
    metadata: dict[int, Mapping[str, Any]] = {}
    unique = sorted(set(block_numbers))
    for cursor in range(0, len(unique), 100):
        batch_numbers = unique[cursor : cursor + 100]
        results = rpc.batch(
            [("eth_getBlockByNumber", [hex(number), False]) for number in batch_numbers]
        )
        for number, result in zip(batch_numbers, results):
            if not isinstance(result, Mapping):
                raise PublicChainCollectionError("ethereum_block_metadata_missing")
            metadata[number] = {
                "hash": str(result.get("hash", "")).lower(),
                "timestamp": str(result.get("timestamp", "")),
            }
    return metadata


def _ethereum_block_context(
    rpc: EthereumRpc,
    raw_logs: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    timestamps: dict[int, int] = {}
    blocks_requiring_headers: set[int] = set()
    for raw in raw_logs:
        block_number = int(str(raw["blockNumber"]), 16)
        raw_timestamp = raw.get("blockTimestamp")
        try:
            if not isinstance(raw_timestamp, str) or not raw_timestamp.startswith("0x"):
                raise ValueError
            timestamp = int(raw_timestamp, 16)
        except (TypeError, ValueError):
            blocks_requiring_headers.add(block_number)
            continue
        previous = timestamps.setdefault(block_number, timestamp)
        if previous != timestamp:
            blocks_requiring_headers.add(block_number)

    headers = _ethereum_block_metadata(rpc, sorted(blocks_requiring_headers))
    contexts: dict[int, dict[str, Any]] = {}
    for block_number in sorted(
        {int(str(raw["blockNumber"]), 16) for raw in raw_logs}
    ):
        header = headers.get(block_number)
        if header is not None:
            try:
                timestamp = int(str(header["timestamp"]), 16)
            except (KeyError, TypeError, ValueError) as exc:
                raise PublicChainCollectionError(
                    "ethereum_block_timestamp_missing"
                ) from exc
            contexts[block_number] = {
                "timestamp": timestamp,
                "canonical_hash": str(header["hash"]).lower(),
                "canonical_rechecked": True,
                "timestamp_source": "eth_getBlockByNumber",
            }
            continue
        contexts[block_number] = {
            "timestamp": timestamps[block_number],
            "canonical_hash": None,
            "canonical_rechecked": False,
            "timestamp_source": "eth_getLogs.blockTimestamp",
        }
    return contexts


def collect_ethereum_native_supply_source(
    source_id: str,
    *,
    start_at: str,
    end_exclusive: str,
    rpc_url: str = DEFAULT_ETHEREUM_RPC_URL,
) -> dict[str, Any]:
    spec = next(source for source in SOURCE_SPECS if source.source_id == source_id)
    if spec.chain != "ethereum":
        raise ValueError("source is not Ethereum")
    start = _parse_utc(start_at)
    end = _parse_utc(end_exclusive)
    if end <= start:
        raise ValueError("collection end must be after start")
    rpc = EthereumRpc(rpc_url)
    client_version = str(rpc.call("web3_clientVersion", []))
    start_block = _ethereum_block_at_or_after(rpc, int(start.timestamp()))
    end_block = _ethereum_block_at_or_after(rpc, int(end.timestamp()))
    topic_to_name, signature_topics = _ethereum_topics(rpc, source_id)
    raw_logs, query_segments = _ethereum_logs(
        rpc,
        address=spec.contract,
        topics=tuple(topic_to_name),
        start_block=start_block,
        end_block_exclusive=end_block,
    )
    blocks = _ethereum_block_context(rpc, raw_logs)
    canonical_mismatch_blocks: set[int] = set()
    events: list[dict[str, Any]] = []
    for raw in raw_logs:
        block_number = int(str(raw["blockNumber"]), 16)
        event_index = int(str(raw["logIndex"]), 16)
        block = blocks[block_number]
        block_hash = str(raw.get("blockHash", "")).lower()
        if (
            block["canonical_rechecked"]
            and block_hash != block["canonical_hash"]
        ):
            canonical_mismatch_blocks.add(block_number)
        event_at = datetime.fromtimestamp(block["timestamp"], tz=timezone.utc)
        topic0 = str(raw.get("topics", [""])[0]).lower()
        data = str(raw.get("data", "0x0"))
        amount = int(data, 16)
        events.append(
            {
                "transaction_hash": str(raw["transactionHash"]).lower(),
                "event_index": event_index,
                "block_number": block_number,
                "block_hash": block_hash,
                "block_timestamp": _utc_text(event_at),
                "available_at": _utc_text(event_at + timedelta(seconds=64 * 12)),
                "event_name": topic_to_name.get(topic0, "Unknown"),
                "raw_amount": str(amount),
                "from_address": None,
                "to_address": None,
                "removed": raw.get("removed") is True,
                "raw": raw,
            }
        )
    first_usable = min(
        (_parse_utc(event["block_timestamp"]) for event in events),
        default=start,
    )
    code = str(rpc.call("eth_getCode", [spec.contract, hex(end_block - 1)]))
    evidence = {
        "endpoint_host": rpc.host,
        "client_version": client_version,
        "contract_code_sha256": hashlib.sha256(code.encode("ascii")).hexdigest(),
        "event_signature_topics": signature_topics,
        "start_block": start_block,
        "end_block_exclusive": end_block,
        "unique_event_block_count": len(blocks),
        "provider_log_timestamp_block_count": sum(
            block["timestamp_source"] == "eth_getLogs.blockTimestamp"
            for block in blocks.values()
        ),
        "header_timestamp_block_count": sum(
            block["timestamp_source"] == "eth_getBlockByNumber"
            for block in blocks.values()
        ),
    }
    return {
        "schema_version": LEGACY_STABLECOIN_CHAIN_SOURCE_VERSION,
        "source_id": spec.source_id,
        "chain": spec.chain,
        "asset": spec.asset,
        "contract": spec.contract,
        "decimals": spec.decimals,
        "retrieved_at": _utc_text(datetime.now(timezone.utc)),
        "coverage": {
            "query_start_at": _utc_text(start),
            "query_end_exclusive": _utc_text(end),
            "first_usable_at": _utc_text(first_usable),
            "complete": True,
            "gap_count": 0,
            "event_families_requested": ["native_supply"],
            "event_families_complete": ["native_supply"],
        },
        "semantics": {
            "verified": False,
            "evidence_hashes": [_sha256(evidence)],
            "supports": ["mint", "burn"],
            "proxy_implementation_history_complete": source_id == "usdt_ethereum",
            "treasury_addresses": [],
            "treasury_addresses_verified": False,
            "blockers": [
                "verified_abi_and_source_history_not_archived",
                "zero_address_transfer_overlap_not_collected",
                "treasury_transfer_history_not_collected",
            ],
        },
        "finality": {
            "policy": "event_block_plus_64_blocks_approximated_as_64x12_seconds",
            "exact_availability": False,
            "canonical_recheck_complete": all(
                block["canonical_rechecked"] for block in blocks.values()
            ),
            "reorg_detected_count": len(canonical_mismatch_blocks),
        },
        "collection": {
            **evidence,
            "evidence_hash": _sha256(evidence),
            "query_segment_count": len(query_segments),
            "query_segments_hash": canonical_hash({"segments": query_segments}),
            "embedded_raw_events": True,
            "raw_event_count": len(raw_logs),
        },
        "events": events,
    }


def _trongrid_pages(
    client: _JsonClient,
    *,
    base_url: str,
    event_name: str,
    start_ms: int,
    end_ms_inclusive: int,
) -> tuple[list[dict[str, Any]], int]:
    query = urllib.parse.urlencode(
        {
            "event_name": event_name,
            "only_confirmed": "true",
            "limit": 200,
            "order_by": "block_timestamp,asc",
            "min_block_timestamp": start_ms,
            "max_block_timestamp": end_ms_inclusive,
        }
    )
    url = (
        f"{base_url.rstrip('/')}/v1/contracts/"
        f"{TRON_USDT_BASE58_ADDRESS}/events?{query}"
    )
    rows: list[dict[str, Any]] = []
    pages = 0
    while url:
        if _hostname(url) != _hostname(base_url):
            raise PublicChainCollectionError("trongrid_pagination_host_changed")
        payload = client.request(url)
        if not isinstance(payload, Mapping) or payload.get("success") is not True:
            raise PublicChainCollectionError("trongrid_event_page_failed")
        page_rows = payload.get("data", [])
        if not isinstance(page_rows, list):
            raise PublicChainCollectionError("trongrid_event_data_not_list")
        rows.extend(row for row in page_rows if isinstance(row, Mapping))
        pages += 1
        if pages > 20_000:
            raise PublicChainCollectionError("trongrid_pagination_limit_exceeded")
        links = payload.get("meta", {}).get("links", {})
        next_url = links.get("next") if isinstance(links, Mapping) else None
        url = str(next_url) if next_url else ""
    return rows, pages


def collect_tron_native_supply_source(
    *,
    start_at: str,
    end_exclusive: str,
    base_url: str = DEFAULT_TRONGRID_URL,
) -> dict[str, Any]:
    spec = next(source for source in SOURCE_SPECS if source.source_id == "usdt_tron")
    start = _parse_utc(start_at)
    end = _parse_utc(end_exclusive)
    if end <= start:
        raise ValueError("collection end must be after start")
    client = _JsonClient()
    issue_rows, issue_pages = _trongrid_pages(
        client,
        base_url=base_url,
        event_name="Issue",
        start_ms=int(start.timestamp() * 1000),
        end_ms_inclusive=int(end.timestamp() * 1000) - 1,
    )
    redeem_rows, redeem_pages = _trongrid_pages(
        client,
        base_url=base_url,
        event_name="Redeem",
        start_ms=int(start.timestamp() * 1000),
        end_ms_inclusive=int(end.timestamp() * 1000) - 1,
    )
    contract_metadata = client.request(
        f"{base_url.rstrip('/')}/wallet/getcontract",
        method="POST",
        payload={"value": TRON_USDT_HEX_ADDRESS},
    )
    raw_events = sorted(
        [*issue_rows, *redeem_rows],
        key=lambda row: (
            int(row.get("block_timestamp", 0)),
            str(row.get("transaction_id", "")),
            int(row.get("event_index", 0)),
        ),
    )
    events: list[dict[str, Any]] = []
    for raw in raw_events:
        event_at = datetime.fromtimestamp(
            int(raw["block_timestamp"]) / 1000,
            tz=timezone.utc,
        )
        result = raw.get("result", {})
        amount = result.get("amount") if isinstance(result, Mapping) else None
        events.append(
            {
                "transaction_hash": str(raw["transaction_id"]).lower(),
                "event_index": int(raw["event_index"]),
                "block_number": int(raw["block_number"]),
                "block_hash": "confirmed_trongrid_event_block_hash_unavailable",
                "block_timestamp": _utc_text(event_at),
                "available_at": _utc_text(event_at + timedelta(seconds=57)),
                "event_name": str(raw["event_name"]),
                "raw_amount": str(amount),
                "from_address": None,
                "to_address": None,
                "removed": False,
                "raw": raw,
            }
        )
    first_usable = min(
        (_parse_utc(event["block_timestamp"]) for event in events),
        default=start,
    )
    abi_entries = contract_metadata.get("abi", {}).get("entrys", []) if isinstance(contract_metadata, Mapping) else []
    abi_event_names = sorted(
        {
            str(entry.get("name"))
            for entry in abi_entries
            if isinstance(entry, Mapping) and entry.get("type") == "Event"
        }
    )
    evidence = {
        "endpoint_host": _hostname(base_url),
        "contract_metadata_sha256": _sha256(contract_metadata),
        "abi_event_names": abi_event_names,
    }
    return {
        "schema_version": LEGACY_STABLECOIN_CHAIN_SOURCE_VERSION,
        "source_id": spec.source_id,
        "chain": spec.chain,
        "asset": spec.asset,
        "contract": spec.contract,
        "decimals": spec.decimals,
        "retrieved_at": _utc_text(datetime.now(timezone.utc)),
        "coverage": {
            "query_start_at": _utc_text(start),
            "query_end_exclusive": _utc_text(end),
            "first_usable_at": _utc_text(first_usable),
            "complete": True,
            "gap_count": 0,
            "event_families_requested": ["native_supply"],
            "event_families_complete": ["native_supply"],
        },
        "semantics": {
            "verified": False,
            "evidence_hashes": [_sha256(evidence)],
            "supports": ["mint", "burn"],
            "proxy_implementation_history_complete": False,
            "treasury_addresses": [],
            "treasury_addresses_verified": False,
            "blockers": [
                "contract_source_history_not_archived",
                "zero_address_transfer_overlap_not_collected",
                "treasury_transfer_history_not_collected",
            ],
        },
        "finality": {
            "policy": "only_confirmed_trongrid_event_plus_19x3_second_approximation",
            "exact_availability": False,
            "canonical_recheck_complete": False,
            "reorg_detected_count": 0,
        },
        "collection": {
            **evidence,
            "evidence_hash": _sha256(evidence),
            "issue_page_count": issue_pages,
            "redeem_page_count": redeem_pages,
            "embedded_raw_events": True,
            "raw_event_count": len(raw_events),
        },
        "events": events,
    }
