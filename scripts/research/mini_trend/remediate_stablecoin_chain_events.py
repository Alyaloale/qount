#!/usr/bin/env python3
"""Remediate frozen stablecoin chain-event sources without market or PnL data."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.mini_trend.stablecoin_chain_events import (  # noqa: E402
    DEFAULT_ETHEREUM_RPC_URL,
    DEFAULT_TRONGRID_URL,
    EthereumRpc,
    PublicChainCollectionError,
)
from qount.mini_trend.stablecoin_chain_events_remediation import (  # noqa: E402
    ETHEREUM_AVAILABILITY_POLICY,
    STABLECOIN_REMEDIATION_VERSION,
    TRANSFER_TOPIC,
    TRON_AVAILABILITY_POLICY,
    TRON_INITIAL_OWNER,
    TRON_SECOND_OWNER,
    TRON_USDT_BASE58,
    TRON_ZERO_BASE58,
    USDT_ETHEREUM_INITIAL_OWNER,
    USDT_ETHEREUM_MULTISIG_OWNER,
    ChainHeader,
    DeterministicGzipNdjsonWriter,
    EventStore,
    HeaderStore,
    PublicEvidenceClient,
    StablecoinRemediationError,
    abi_sha256,
    address_topic,
    build_nonproxy_implementation_history,
    build_tron_implementation_history,
    build_usdt_ethereum_owner_call_proof,
    build_usdc_implementation_history,
    bytes_sha256,
    canonical_json_bytes,
    discover_usdt_ethereum_owner_history,
    decode_multisig_transaction_result,
    ethereum_owner_at,
    ethereum_confirmation_fields,
    evidence_reference,
    fetch_ethereum_headers,
    fetch_ethereum_logs,
    fetch_immutable_evidence,
    fetch_tron_transaction_transfer_events,
    fetch_trongrid_contract_events,
    fetch_tronscan_transfer_rows,
    file_sha256,
    ingest_v01_collection,
    implementation_timeline_hash,
    iter_verified_gzip_ndjson,
    multisig_transaction_call,
    normalize_evm_transfer_log,
    normalize_tron_transfer,
    owner_address_history,
    parse_utc_ms,
    parse_ethereum_header,
    parse_tron_header,
    parse_tronscan_verified_contract,
    parse_verified_contract,
    read_json_object,
    sourcify_contract_url,
    source_spec,
    supply_overlap_audit,
    tron_confirmation_fields,
    tron_confirmation_headers,
    utc_text,
    verified_multisig_execution_semantic_proof,
    write_immutable_bytes,
)
from qount.mini_trend.stablecoin_impulse_g0 import (  # noqa: E402
    STABLECOIN_CHAIN_SOURCE_VERSION,
)


DEFAULT_INPUT_DIRECTORY = Path(
    "/mnt/e/qount_data/qount/datasets/stablecoin_chain_events/"
    "v0.1/20260725T133234"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/e/qount_data/qount/datasets/stablecoin_chain_events/v0.3"
)
DEFAULT_SCRATCH_ROOT = Path(
    "/home/alyaloale/.cache/qount-compute/stablecoin-chain-remediation-v03"
)
USDT_ETHEREUM = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC_ETHEREUM = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDC_IMPLEMENTATIONS = (
    "0x0882477e7895bdc5cea7cb1552ed914ab157fe56",
    "0xb7277a6e95992041568d9391d09d0122023778a2",
    "0xa2327a938febf5fec13bacfb16ae10ecbc4cbdcf",
    "0x43506849d7c04f9138d1a2050bbf3a0c054402dd",
)
ZERO_EVM = "0x0000000000000000000000000000000000000000"

EVIDENCE_URLS = {
    "usdt_ethereum.sourcify.json": sourcify_contract_url(1, USDT_ETHEREUM),
    "usdt_ethereum.owner-multisig.sourcify.json": sourcify_contract_url(
        1, USDT_ETHEREUM_MULTISIG_OWNER
    ),
    "usdc_ethereum.proxy.sourcify.json": sourcify_contract_url(1, USDC_ETHEREUM),
    **{
        f"usdc_ethereum.impl.{address[2:10]}.sourcify.json": sourcify_contract_url(
            1, address
        )
        for address in USDC_IMPLEMENTATIONS
    },
    "usdt_tron.contract.tronscan.json": (
        "https://apilist.tronscanapi.com/api/contract?contract="
        f"{TRON_USDT_BASE58}"
    ),
    "usdt_tron.code.tronscan.json": (
        "https://apilist.tronscanapi.com/api/contracts/code?contract="
        f"{TRON_USDT_BASE58}"
    ),
    "ethereum.finality-policy.html": (
        "https://ethereum.org/developers/docs/consensus-mechanisms/pos/gasper/"
    ),
    "tron.finality-policy.html": (
        "https://developers.tron.network/docs/tron-protocol-transaction"
    ),
    "circle.usdc-contract-addresses.html": (
        "https://developers.circle.com/stablecoins/usdc-contract-addresses"
    ),
    "tether.supported-protocols.html": "https://tether.to/en/supported-protocols/",
}

PUBLISH_CODE_RELATIVE_PATHS = (
    "src/qount/mini_trend/stablecoin_impulse_g0.py",
    "src/qount/mini_trend/stablecoin_chain_events.py",
    "src/qount/mini_trend/stablecoin_chain_events_remediation.py",
    "scripts/research/mini_trend/remediate_stablecoin_chain_events.py",
)


class _ResilientEthereumRpc(EthereumRpc):
    """Apply the remediation CLI's retry and pacing policy to JSON-RPC calls."""

    def __init__(
        self,
        url: str,
        *,
        attempts: int,
        minimum_interval_seconds: float,
    ) -> None:
        super().__init__(url)
        self.attempts = attempts
        self.minimum_interval_seconds = minimum_interval_seconds
        self._last_request_at: float | None = None

    def _invoke(self, operation: Any, *args: Any) -> Any:
        last_error: PublicChainCollectionError | None = None
        for attempt in range(self.attempts):
            now = time.monotonic()
            if self._last_request_at is not None:
                delay = self.minimum_interval_seconds - (
                    now - self._last_request_at
                )
                if delay > 0:
                    time.sleep(delay)
            self._last_request_at = time.monotonic()
            try:
                return operation(*args)
            except PublicChainCollectionError as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    time.sleep(max(self.minimum_interval_seconds, min(2**attempt, 8)))
        assert last_error is not None
        raise last_error

    def call(self, method: str, params: list[Any]) -> Any:
        return self._invoke(super().call, method, params)

    def batch(self, requests: list[tuple[str, list[Any]]]) -> list[Any]:
        return self._invoke(super().batch, requests)


def _json_bytes(value: object) -> bytes:
    return canonical_json_bytes(value, newline=True)


def _write_json(path: Path, value: object) -> None:
    write_immutable_bytes(path, _json_bytes(value))


def _write_checkpoint_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    raw = _json_bytes(value)
    partial = path.with_name(f".{path.name}.partial")
    with partial.open("wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


def _read_json_any(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise StablecoinRemediationError(f"json_artifact_invalid:{path.name}") from exc


def _load_json_bytes(raw: bytes, *, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StablecoinRemediationError(f"evidence_json_invalid:{name}") from exc
    if not isinstance(payload, dict):
        raise StablecoinRemediationError(f"evidence_json_not_object:{name}")
    return payload


def _read_existing_json_group(
    directory: Path,
    names: Iterable[str],
) -> dict[str, Any] | None:
    materialized = tuple(names)
    existing = {name for name in materialized if (directory / name).is_file()}
    if not existing:
        return None
    if existing != set(materialized):
        missing = sorted(set(materialized) - existing)
        raise StablecoinRemediationError(
            f"resumable_evidence_group_incomplete:{','.join(missing)}"
        )
    return {name: _read_json_any(directory / name) for name in materialized}


def _validate_resumed_implementation_history(
    history: Mapping[str, Any],
    *,
    observed_through_block: int,
    is_proxy: bool,
) -> None:
    if (
        int(history.get("observed_through_block", -1)) != observed_through_block
        or history.get("is_proxy") is not is_proxy
        or history.get("complete") is not True
        or history.get("timeline_hash") != implementation_timeline_hash(history)
    ):
        raise StablecoinRemediationError(
            "resumed_implementation_history_invalid"
        )


def _proxy_from_env(name: str | None) -> str | None:
    if not name:
        return None
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"proxy environment variable is not set: {name}")
    return value


def _header_payload(header: ChainHeader) -> dict[str, Any]:
    return {
        "chain": header.chain,
        "block_number": header.block_number,
        "block_hash": header.block_hash,
        "block_timestamp": utc_text(header.timestamp),
        "producer": header.producer,
    }


def _write_ethereum_cutoff_boundary(
    args: argparse.Namespace,
    rpc: EthereumRpc,
) -> int:
    path = args.output_directory / "ethereum.cutoff-boundary-rpc.json"
    if path.exists():
        payload = read_json_object(path)
        if (
            payload.get("query_end_exclusive") != args.query_end_exclusive
            or payload.get("observed_through_block")
            != args.ethereum_observed_through_block
        ):
            raise StablecoinRemediationError("ethereum_cutoff_artifact_mismatch")
        return int(payload["observed_through_block"])
    cutoff_ms = parse_utc_ms(args.query_end_exclusive)
    if cutoff_ms % 1000:
        raise ValueError("query_end_exclusive_requires_whole_second")
    before_raw, after_raw = rpc.batch(
        [
            (
                "eth_getBlockByNumber",
                [hex(args.ethereum_observed_through_block), False],
            ),
            (
                "eth_getBlockByNumber",
                [hex(args.ethereum_observed_through_block + 1), False],
            ),
        ]
    )
    if not isinstance(before_raw, Mapping) or not isinstance(after_raw, Mapping):
        raise StablecoinRemediationError("ethereum_cutoff_header_missing")
    before = parse_ethereum_header(before_raw)
    after = parse_ethereum_header(after_raw)
    cutoff_seconds = cutoff_ms // 1000
    if (
        before.block_number + 1 != after.block_number
        or before.timestamp >= cutoff_seconds
        or after.timestamp < cutoff_seconds
    ):
        raise StablecoinRemediationError("ethereum_cutoff_boundary_invalid")
    payload = {
        "proof_kind": "adjacent_canonical_block_timestamp_boundary",
        "query_end_exclusive": args.query_end_exclusive,
        "observed_through_block": before.block_number,
        "last_block_before_cutoff": _header_payload(before),
        "first_block_at_or_after_cutoff": _header_payload(after),
        "raw_rpc_headers": [dict(before_raw), dict(after_raw)],
    }
    _write_json(path, payload)
    return before.block_number


def _write_tron_cutoff_boundary(
    args: argparse.Namespace,
    client: PublicEvidenceClient,
) -> int:
    path = args.output_directory / "tron.cutoff-boundary-rpc.json"
    if path.exists():
        payload = read_json_object(path)
        if payload.get("query_end_exclusive") != args.query_end_exclusive:
            raise StablecoinRemediationError("tron_cutoff_artifact_mismatch")
        return int(payload["observed_through_block"])

    cutoff_ms = parse_utc_ms(args.query_end_exclusive)
    if cutoff_ms % 1000:
        raise ValueError("query_end_exclusive_requires_whole_second")
    endpoint = DEFAULT_TRONGRID_URL.rstrip("/")

    def fetch(number: int) -> tuple[ChainHeader, dict[str, Any]]:
        raw = client.json(
            f"{endpoint}/wallet/getblockbynum",
            method="POST",
            payload={"num": number},
        )
        if not isinstance(raw, Mapping):
            raise StablecoinRemediationError("tron_cutoff_header_missing")
        header = parse_tron_header(raw)
        if header.block_number != number:
            raise StablecoinRemediationError("tron_cutoff_header_number_mismatch")
        return header, dict(raw)

    latest_raw = client.json(f"{endpoint}/wallet/getnowblock")
    if not isinstance(latest_raw, Mapping):
        raise StablecoinRemediationError("tron_latest_header_missing")
    latest = parse_tron_header(latest_raw)
    earliest_regular, _ = fetch(1)
    cutoff_seconds = cutoff_ms // 1000
    if (
        earliest_regular.timestamp >= cutoff_seconds
        or latest.timestamp < cutoff_seconds
    ):
        raise StablecoinRemediationError("tron_cutoff_outside_chain_range")

    low = earliest_regular.block_number
    high = latest.block_number
    while low + 1 < high:
        middle = (low + high) // 2
        header, _ = fetch(middle)
        if header.timestamp < cutoff_seconds:
            low = middle
        else:
            high = middle
    before, before_raw = fetch(low)
    after, after_raw = fetch(high)
    if (
        before.block_number + 1 != after.block_number
        or before.timestamp >= cutoff_seconds
        or after.timestamp < cutoff_seconds
    ):
        raise StablecoinRemediationError("tron_cutoff_boundary_invalid")
    payload = {
        "proof_kind": "adjacent_confirmed_block_timestamp_boundary",
        "query_end_exclusive": args.query_end_exclusive,
        "observed_through_block": before.block_number,
        "last_block_before_cutoff": _header_payload(before),
        "first_block_at_or_after_cutoff": _header_payload(after),
        "raw_confirmed_headers": [before_raw, after_raw],
        "binary_search_latest_block": latest.block_number,
    }
    _write_json(path, payload)
    return before.block_number


def _open_stores(args: argparse.Namespace):
    args.scratch_directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    return (
        EventStore(args.scratch_directory / "events.sqlite"),
        HeaderStore(args.scratch_directory / "headers.sqlite"),
    )


def _ingest(args: argparse.Namespace, events: EventStore) -> dict[str, Any]:
    manifest, sources = ingest_v01_collection(args.input_directory, events)
    if (
        manifest.get("query_start_at") != args.query_start_at
        or manifest.get("query_end_exclusive") != args.query_end_exclusive
    ):
        raise StablecoinRemediationError("v01_query_window_mismatch")
    summary = {
        "stage": "ingest",
        "v01_manifest_hash": manifest["manifest_hash"],
        "source_native_counts": {
            source_id: events.count(source_id, event_family="native_supply")
            for source_id in sorted(sources)
        },
        "market_data_read": False,
        "strategy_results_read": False,
        "orders_authorized": False,
    }
    _write_checkpoint_json(args.scratch_directory / "ingest-summary.json", summary)
    return summary


def _fetch_static_evidence(
    args: argparse.Namespace,
    client: PublicEvidenceClient,
) -> dict[str, bytes]:
    args.output_directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    raw_by_name: dict[str, bytes] = {}
    for name, url in EVIDENCE_URLS.items():
        raw_by_name[name] = fetch_immutable_evidence(
            client, url, args.output_directory / name
        )
    return raw_by_name


_OWNER_BLOCKS_NAME = "usdt_ethereum.owner-initial-eoa-blocks.ndjson.gz"
_OWNER_RECEIPTS_NAME = "usdt_ethereum.owner-initial-eoa-receipts.ndjson.gz"
_OWNER_MULTISIG_TRANSACTIONS_NAME = (
    "usdt_ethereum.owner-multisig-transactions.ndjson.gz"
)
_OWNER_CALL_PROOF_NAME = "usdt_ethereum.owner-call-proof.json"


def _owner_proof_rows(
    output_directory: Path,
    reference: Mapping[str, Any],
    *,
    expected_name: str,
) -> list[Mapping[str, Any]]:
    if reference.get("path") != expected_name:
        raise StablecoinRemediationError(
            f"owner_proof_sidecar_path_invalid:{expected_name}"
        )
    return list(
        iter_verified_gzip_ndjson(output_directory / expected_name, reference)
    )


def _completed_owner_sidecar(
    path: Path,
) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    digest = hashlib.sha256()
    rows: list[Mapping[str, Any]] = []
    try:
        with gzip.open(path, "rb") as handle:
            for index, line in enumerate(handle):
                digest.update(line)
                row = json.loads(line)
                if (
                    not isinstance(row, Mapping)
                    or canonical_json_bytes(row, newline=True) != line
                ):
                    raise StablecoinRemediationError(
                        f"owner_completed_sidecar_noncanonical:{path.name}:{index}"
                    )
                rows.append(row)
    except (OSError, EOFError, json.JSONDecodeError) as exc:
        raise StablecoinRemediationError(
            f"owner_completed_sidecar_invalid:{path.name}"
        ) from exc
    reference = {
        "path": path.name,
        "format": "canonical_ndjson",
        "compression": "gzip_mtime_zero",
        "record_count": len(rows),
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "uncompressed_sha256": digest.hexdigest(),
    }
    return rows, reference


def _build_or_resume_usdt_owner_call_proof(
    args: argparse.Namespace,
    rpc: EthereumRpc,
    *,
    owner_audit: Mapping[str, Any],
    multisig_payload: Mapping[str, Any],
    multisig_source_sha256: str,
) -> dict[str, Any]:
    paths = {
        "initial_owner_blocks": args.output_directory / _OWNER_BLOCKS_NAME,
        "initial_owner_receipts": args.output_directory / _OWNER_RECEIPTS_NAME,
        "multisig_transactions": (
            args.output_directory / _OWNER_MULTISIG_TRANSACTIONS_NAME
        ),
        "proof": args.output_directory / _OWNER_CALL_PROOF_NAME,
    }
    existing = {role for role, path in paths.items() if path.is_file()}
    completed_sidecars = set(paths) - {"proof"}
    if (
        existing
        and existing != completed_sidecars
        and existing != set(paths)
    ):
        raise StablecoinRemediationError(
            "resumable_owner_call_proof_group_incomplete:"
            + ",".join(sorted(set(paths) - existing))
        )
    source_proof = verified_multisig_execution_semantic_proof(
        multisig_payload,
        source_artifact_sha256=multisig_source_sha256,
    )
    owner_audit_path = args.output_directory / "usdt_ethereum.owner-history-audit.json"
    owner_audit_hash = file_sha256(owner_audit_path)

    if existing == set(paths):
        proof = read_json_object(paths["proof"])
        references = proof.get("evidence_references", {})
        state = proof.get("state_observations", {})
        if not isinstance(references, Mapping) or not isinstance(state, Mapping):
            raise StablecoinRemediationError("resumed_owner_call_proof_invalid")
        block_rows = _owner_proof_rows(
            args.output_directory,
            references.get("initial_owner_blocks", {}),
            expected_name=_OWNER_BLOCKS_NAME,
        )
        receipt_rows = _owner_proof_rows(
            args.output_directory,
            references.get("initial_owner_receipts", {}),
            expected_name=_OWNER_RECEIPTS_NAME,
        )
        multisig_rows = _owner_proof_rows(
            args.output_directory,
            references.get("multisig_transactions", {}),
            expected_name=_OWNER_MULTISIG_TRANSACTIONS_NAME,
        )
        rebuilt = build_usdt_ethereum_owner_call_proof(
            contract=USDT_ETHEREUM,
            owner_audit=owner_audit,
            owner_audit_sha256=owner_audit_hash,
            multisig_semantic_proof=source_proof,
            initial_block_rows=block_rows,
            initial_receipt_rows=receipt_rows,
            multisig_transaction_rows=multisig_rows,
            state_observations=state,
            evidence_references=references,
        )
        if canonical_hash(rebuilt) != canonical_hash(proof):
            raise StablecoinRemediationError("resumed_owner_call_proof_mismatch")
        return proof

    transitions = owner_audit.get("transitions", [])
    if not isinstance(transitions, list) or len(transitions) != 1:
        raise StablecoinRemediationError("usdt_owner_transition_count_invalid")
    activation_block = int(transitions[0]["activation_block"])
    deployment_block = int(owner_audit["deployment_block"])
    observed_through_block = int(owner_audit["observed_through_block"])

    if existing == completed_sidecars:
        block_rows, block_reference = _completed_owner_sidecar(
            paths["initial_owner_blocks"]
        )
        receipt_rows, receipt_reference = _completed_owner_sidecar(
            paths["initial_owner_receipts"]
        )
        multisig_rows, multisig_reference = _completed_owner_sidecar(
            paths["multisig_transactions"]
        )
    else:
        _remove_partial(paths["initial_owner_blocks"])
        block_rows = []
        with DeterministicGzipNdjsonWriter(paths["initial_owner_blocks"]) as writer:
            for offset in range(
                deployment_block,
                activation_block + 1,
                args.owner_block_scan_batch_size,
            ):
                numbers = list(
                    range(
                        offset,
                        min(
                            activation_block + 1,
                            offset + args.owner_block_scan_batch_size,
                        ),
                    )
                )
                requests: list[tuple[str, list[Any]]] = []
                for number in numbers:
                    requests.extend(
                        (
                            ("eth_getBlockByNumber", [hex(number), True]),
                            (
                                "eth_getCode",
                                [USDT_ETHEREUM_INITIAL_OWNER, hex(number)],
                            ),
                            (
                                "eth_getTransactionCount",
                                [USDT_ETHEREUM_INITIAL_OWNER, hex(number)],
                            ),
                        )
                    )
                results = rpc.batch(requests)
                for index, number in enumerate(numbers):
                    raw_block, owner_code, owner_nonce = results[
                        index * 3 : index * 3 + 3
                    ]
                    if not isinstance(raw_block, Mapping):
                        raise StablecoinRemediationError(
                            "owner_initial_block_rpc_result_invalid"
                        )
                    row = {
                        "block_number": number,
                        "raw_block": dict(raw_block),
                        "initial_owner_code": owner_code,
                        "initial_owner_nonce": owner_nonce,
                    }
                    writer.write(row)
                    block_rows.append(row)
        block_reference = writer.reference().as_dict()

        owner_call_hashes = [
            str(transaction["hash"]).lower()
            for row in block_rows
            for transaction in row["raw_block"]["transactions"]
            if str(transaction.get("from", "")).lower()
            == USDT_ETHEREUM_INITIAL_OWNER
            and str(transaction.get("to", "")).lower() == USDT_ETHEREUM
        ]
        receipts = rpc.batch(
            [
                ("eth_getTransactionReceipt", [transaction_hash])
                for transaction_hash in owner_call_hashes
            ]
        )
        _remove_partial(paths["initial_owner_receipts"])
        receipt_rows = []
        with DeterministicGzipNdjsonWriter(paths["initial_owner_receipts"]) as writer:
            for transaction_hash, receipt in zip(owner_call_hashes, receipts):
                if not isinstance(receipt, Mapping):
                    raise StablecoinRemediationError(
                        "owner_initial_receipt_rpc_invalid"
                    )
                row = {
                    "transaction_hash": transaction_hash,
                    "raw_receipt": dict(receipt),
                }
                writer.write(row)
                receipt_rows.append(row)
        receipt_reference = writer.reference().as_dict()

    state_results = rpc.batch(
        [
            (
                "eth_call",
                [
                    {
                        "to": USDT_ETHEREUM_MULTISIG_OWNER,
                        "data": "0xb77bf600",
                    },
                    hex(observed_through_block),
                ],
            ),
            (
                "eth_getCode",
                [USDT_ETHEREUM_MULTISIG_OWNER, hex(activation_block)],
            ),
            (
                "eth_getCode",
                [USDT_ETHEREUM_MULTISIG_OWNER, hex(observed_through_block)],
            ),
        ]
    )
    transaction_count_raw, transition_code, observed_code = state_results
    transaction_count = int(str(transaction_count_raw), 16)
    state_observations = {
        "token_owner_at_deployment": ethereum_owner_at(
            rpc, USDT_ETHEREUM, deployment_block
        ),
        "token_owner_before_transition": ethereum_owner_at(
            rpc, USDT_ETHEREUM, activation_block - 1
        ),
        "token_owner_at_transition": ethereum_owner_at(
            rpc, USDT_ETHEREUM, activation_block
        ),
        "token_owner_at_observed": ethereum_owner_at(
            rpc, USDT_ETHEREUM, observed_through_block
        ),
        "multisig_runtime_code_at_transition": transition_code,
        "multisig_runtime_code_at_observed": observed_code,
        "multisig_transaction_count_raw": transaction_count_raw,
    }

    if existing != completed_sidecars:
        _remove_partial(paths["multisig_transactions"])
        multisig_rows = []
        with DeterministicGzipNdjsonWriter(paths["multisig_transactions"]) as writer:
            for offset in range(0, transaction_count, args.owner_multisig_batch_size):
                transaction_ids = list(
                    range(
                        offset,
                        min(transaction_count, offset + args.owner_multisig_batch_size),
                    )
                )
                results = rpc.batch(
                    [
                        (
                            "eth_call",
                            [
                                {
                                    "to": USDT_ETHEREUM_MULTISIG_OWNER,
                                    "data": multisig_transaction_call(transaction_id),
                                },
                                hex(observed_through_block),
                            ],
                        )
                        for transaction_id in transaction_ids
                    ]
                )
                for transaction_id, result in zip(transaction_ids, results):
                    row = {
                        "transaction_id": transaction_id,
                        "raw_call_result": result,
                        "decoded": decode_multisig_transaction_result(result),
                    }
                    writer.write(row)
                    multisig_rows.append(row)
        multisig_reference = writer.reference().as_dict()

    references = {
        "initial_owner_blocks": block_reference,
        "initial_owner_receipts": receipt_reference,
        "multisig_transactions": multisig_reference,
        "multisig_verified_source": evidence_reference(
            args.output_directory / "usdt_ethereum.owner-multisig.sourcify.json",
            role="verified_multisig_source",
        ),
    }
    proof = build_usdt_ethereum_owner_call_proof(
        contract=USDT_ETHEREUM,
        owner_audit=owner_audit,
        owner_audit_sha256=owner_audit_hash,
        multisig_semantic_proof=source_proof,
        initial_block_rows=block_rows,
        initial_receipt_rows=receipt_rows,
        multisig_transaction_rows=multisig_rows,
        state_observations=state_observations,
        evidence_references=references,
    )
    _write_json(paths["proof"], proof)
    return proof


def _evidence(
    args: argparse.Namespace,
    events: EventStore,
    rpc: EthereumRpc,
    client: PublicEvidenceClient,
) -> dict[str, Any]:
    _write_ethereum_cutoff_boundary(args, rpc)
    args.tron_observed_through_block = _write_tron_cutoff_boundary(args, client)
    raw = _fetch_static_evidence(args, client)
    usdt_payload = parse_verified_contract(
        raw["usdt_ethereum.sourcify.json"],
        expected_address=USDT_ETHEREUM,
    )
    owner_multisig_payload = parse_verified_contract(
        raw["usdt_ethereum.owner-multisig.sourcify.json"],
        expected_address=USDT_ETHEREUM_MULTISIG_OWNER,
    )
    proxy_payload = parse_verified_contract(
        raw["usdc_ethereum.proxy.sourcify.json"],
        expected_address=USDC_ETHEREUM,
    )
    implementation_payloads: dict[str, dict[str, Any]] = {}
    implementation_hashes: dict[str, str] = {}
    for address in USDC_IMPLEMENTATIONS:
        name = f"usdc_ethereum.impl.{address[2:10]}.sourcify.json"
        payload = parse_verified_contract(raw[name], expected_address=address)
        implementation_payloads[address] = payload
        implementation_hashes[address] = bytes_sha256(raw[name])

    usdc_group = _read_existing_json_group(
        args.output_directory,
        (
            "usdc_ethereum.proxy-timeline-rpc.json",
            "usdc_ethereum.implementation-history.json",
        ),
    )
    if usdc_group is None:
        usdc_history, usdc_rpc_evidence = build_usdc_implementation_history(
            rpc,
            proxy_payload=proxy_payload,
            proxy_evidence_sha256=bytes_sha256(
                raw["usdc_ethereum.proxy.sourcify.json"]
            ),
            implementation_payloads=implementation_payloads,
            implementation_evidence_sha256=implementation_hashes,
            observed_through_block=args.ethereum_observed_through_block,
        )
        _write_json(
            args.output_directory / "usdc_ethereum.proxy-timeline-rpc.json",
            usdc_rpc_evidence,
        )
        _write_json(
            args.output_directory / "usdc_ethereum.implementation-history.json",
            usdc_history,
        )
    else:
        usdc_rpc_evidence = usdc_group["usdc_ethereum.proxy-timeline-rpc.json"]
        usdc_history = usdc_group["usdc_ethereum.implementation-history.json"]
        if not isinstance(usdc_history, Mapping) or not isinstance(
            usdc_rpc_evidence, Mapping
        ):
            raise StablecoinRemediationError("resumed_usdc_evidence_invalid")
        _validate_resumed_implementation_history(
            usdc_history,
            observed_through_block=args.ethereum_observed_through_block,
            is_proxy=True,
        )

    usdt_group = _read_existing_json_group(
        args.output_directory,
        (
            "usdt_ethereum.runtime-code.json",
            "usdt_ethereum.implementation-history.json",
        ),
    )
    if usdt_group is None:
        usdt_history, usdt_runtime_evidence = (
            build_nonproxy_implementation_history(
                rpc,
                contract_payload=usdt_payload,
                source_artifact_sha256=bytes_sha256(
                    raw["usdt_ethereum.sourcify.json"]
                ),
                observed_through_block=args.ethereum_observed_through_block,
                native_mint_events=["issue"],
                native_burn_events=["redeem"],
                zero_transfer_emission="absent",
            )
        )
        _write_json(
            args.output_directory / "usdt_ethereum.runtime-code.json",
            usdt_runtime_evidence,
        )
        _write_json(
            args.output_directory / "usdt_ethereum.implementation-history.json",
            usdt_history,
        )
    else:
        usdt_runtime_evidence = usdt_group["usdt_ethereum.runtime-code.json"]
        usdt_history = usdt_group["usdt_ethereum.implementation-history.json"]
        if not isinstance(usdt_history, Mapping) or not isinstance(
            usdt_runtime_evidence, Mapping
        ):
            raise StablecoinRemediationError("resumed_usdt_evidence_invalid")
        _validate_resumed_implementation_history(
            usdt_history,
            observed_through_block=args.ethereum_observed_through_block,
            is_proxy=False,
        )

    owner_group = _read_existing_json_group(
        args.output_directory,
        ("usdt_ethereum.owner-history-audit.json",),
    )
    if owner_group is None:
        owner_audit = discover_usdt_ethereum_owner_history(
            rpc,
            contract=USDT_ETHEREUM,
            deployment_block=usdt_history["deployment_block"],
            observed_through_block=args.ethereum_observed_through_block,
            native_event_blocks=events.block_numbers("usdt_ethereum"),
            checkpoint_step_blocks=args.owner_checkpoint_step_blocks,
        )
        _write_json(
            args.output_directory / "usdt_ethereum.owner-history-audit.json",
            owner_audit,
        )
    else:
        owner_audit = owner_group["usdt_ethereum.owner-history-audit.json"]
        if (
            not isinstance(owner_audit, Mapping)
            or int(owner_audit.get("observed_through_block", -1))
            != args.ethereum_observed_through_block
            or int(owner_audit.get("deployment_block", -1))
            != int(usdt_history["deployment_block"])
        ):
            raise StablecoinRemediationError("resumed_usdt_owner_audit_invalid")
    owner_call_proof = _build_or_resume_usdt_owner_call_proof(
        args,
        rpc,
        owner_audit=owner_audit,
        multisig_payload=owner_multisig_payload,
        multisig_source_sha256=bytes_sha256(
            raw["usdt_ethereum.owner-multisig.sourcify.json"]
        ),
    )
    deprecate_topic = next(
        row["signatureHash32"]
        for row in usdt_payload["signatures"]["event"]
        if row["signature"] == "Deprecate(address)"
    )
    deprecate_group = _read_existing_json_group(
        args.output_directory,
        ("usdt_ethereum.deprecate-query.json",),
    )
    if deprecate_group is None:
        deprecate_logs, deprecate_segments = fetch_ethereum_logs(
            rpc,
            address=USDT_ETHEREUM,
            topics=[deprecate_topic],
            start_block=usdt_history["deployment_block"],
            end_block_exclusive=args.ethereum_observed_through_block + 1,
        )
        if deprecate_logs:
            raise StablecoinRemediationError("usdt_ethereum_deprecation_detected")
        _write_json(
            args.output_directory / "usdt_ethereum.deprecate-query.json",
            {"logs": deprecate_logs, "segments": deprecate_segments},
        )
    else:
        deprecate_query = deprecate_group["usdt_ethereum.deprecate-query.json"]
        if not isinstance(deprecate_query, Mapping) or deprecate_query.get("logs"):
            raise StablecoinRemediationError("resumed_usdt_deprecation_invalid")

    tron_event_group = _read_existing_json_group(
        args.output_directory,
        (
            "usdt_tron.ownership-events.json",
            "usdt_tron.deprecate-events.json",
        ),
    )
    if tron_event_group is None:
        ownership_payload = fetch_trongrid_contract_events(
            client, event_name="OwnershipTransferred"
        )
        deprecate_payload = fetch_trongrid_contract_events(
            client, event_name="Deprecate"
        )
        _write_json(
            args.output_directory / "usdt_tron.ownership-events.json",
            ownership_payload,
        )
        _write_json(
            args.output_directory / "usdt_tron.deprecate-events.json",
            deprecate_payload,
        )
    else:
        ownership_payload = tron_event_group["usdt_tron.ownership-events.json"]
        deprecate_payload = tron_event_group["usdt_tron.deprecate-events.json"]
        if not isinstance(ownership_payload, Mapping) or not isinstance(
            deprecate_payload, Mapping
        ):
            raise StablecoinRemediationError("resumed_tron_event_history_invalid")
    tron_contract_payload = _load_json_bytes(
        raw["usdt_tron.contract.tronscan.json"],
        name="usdt_tron.contract.tronscan.json",
    )
    tron_code_payload = _load_json_bytes(
        raw["usdt_tron.code.tronscan.json"],
        name="usdt_tron.code.tronscan.json",
    )
    tron_contract, _, _, _ = parse_tronscan_verified_contract(
        tron_contract_payload,
        tron_code_payload,
    )
    creator_tx = str(tron_contract["creator"]["txHash"])
    deployment_raw = fetch_immutable_evidence(
        client,
        f"{DEFAULT_TRONGRID_URL.rstrip('/')}/wallet/gettransactioninfobyid",
        args.output_directory / "usdt_tron.deployment-transaction-info.json",
        method="POST",
        payload={"value": creator_tx},
    )
    deployment_info = _load_json_bytes(
        deployment_raw,
        name="usdt_tron.deployment-transaction-info.json",
    )
    tron_implementation_group = _read_existing_json_group(
        args.output_directory,
        (
            "usdt_tron.implementation-history.json",
            "usdt_tron.owner-history.json",
            "usdt_tron.runtime-verification.json",
        ),
    )
    if tron_implementation_group is None:
        tron_history, tron_owner_history, tron_runtime_evidence = (
            build_tron_implementation_history(
                contract_payload=tron_contract_payload,
                code_payload=tron_code_payload,
                deployment_info=deployment_info,
                code_artifact_sha256=bytes_sha256(
                    raw["usdt_tron.code.tronscan.json"]
                ),
                observed_through_block=args.tron_observed_through_block,
                ownership_payload=ownership_payload,
                ownership_evidence_sha256=file_sha256(
                    args.output_directory / "usdt_tron.ownership-events.json"
                ),
                deprecate_payload=deprecate_payload,
            )
        )
        _write_json(
            args.output_directory / "usdt_tron.implementation-history.json",
            tron_history,
        )
        _write_json(
            args.output_directory / "usdt_tron.owner-history.json",
            tron_owner_history,
        )
        _write_json(
            args.output_directory / "usdt_tron.runtime-verification.json",
            tron_runtime_evidence,
        )
    else:
        tron_history = tron_implementation_group[
            "usdt_tron.implementation-history.json"
        ]
        tron_owner_history = tron_implementation_group[
            "usdt_tron.owner-history.json"
        ]
        tron_runtime_evidence = tron_implementation_group[
            "usdt_tron.runtime-verification.json"
        ]
        if (
            not isinstance(tron_history, Mapping)
            or not isinstance(tron_owner_history, list)
            or not isinstance(tron_runtime_evidence, Mapping)
        ):
            raise StablecoinRemediationError(
                "resumed_tron_implementation_evidence_invalid"
            )
        _validate_resumed_implementation_history(
            tron_history,
            observed_through_block=args.tron_observed_through_block,
            is_proxy=False,
        )
    summary = {
        "stage": "evidence",
        "usdc_implementation_count": len(usdc_history["entries"]),
        "usdc_upgrade_event_count": usdc_history["upgrade_event_count"],
        "usdt_ethereum_owner_count": len(owner_audit["owner_addresses"]),
        "usdt_ethereum_owner_history_complete": owner_call_proof[
            "complete_owner_history_claimed"
        ],
        "usdt_tron_owner_count": len(tron_owner_history),
        "market_data_read": False,
        "strategy_results_read": False,
        "orders_authorized": False,
    }
    _write_checkpoint_json(args.scratch_directory / "evidence-summary.json", summary)
    return summary


def _owner_active(
    history: Iterable[Mapping[str, Any]],
    address: str,
    block_number: int,
) -> bool:
    rendered = address.lower()
    for row in history:
        start = int(row["valid_from_block"])
        end = row.get("valid_to_block_exclusive")
        if (
            str(row["address"]).lower() == rendered
            and block_number >= start
            and (end is None or block_number < int(end))
        ):
            return True
    return False


def _ethereum_transfer_evidence(
    args: argparse.Namespace,
    rpc: EthereumRpc,
) -> dict[str, Any]:
    path = args.output_directory / "usdt_ethereum.transfer-query.json"
    if path.exists():
        return read_json_object(path)
    owner_audit = read_json_object(
        args.output_directory / "usdt_ethereum.owner-history-audit.json"
    )
    owner_audit_hash = file_sha256(
        args.output_directory / "usdt_ethereum.owner-history-audit.json"
    )
    history = owner_address_history(
        owner_audit,
        activation_evidence_sha256=owner_audit_hash,
    )
    filters: list[tuple[str, list[Any]]] = [
        ("zero_from", [TRANSFER_TOPIC, address_topic(ZERO_EVM)]),
        ("zero_to", [TRANSFER_TOPIC, None, address_topic(ZERO_EVM)]),
    ]
    for row in history:
        filters.extend(
            (
                (
                    f"treasury_from:{row['address']}",
                    [TRANSFER_TOPIC, address_topic(str(row["address"]))],
                ),
                (
                    f"treasury_to:{row['address']}",
                    [TRANSFER_TOPIC, None, address_topic(str(row["address"]))],
                ),
            )
        )
    logs_by_identity: dict[tuple[str, int], dict[str, Any]] = {}
    zero_amount_logs_by_identity: dict[tuple[str, int], dict[str, Any]] = {}
    segments: list[dict[str, Any]] = []
    inactive_owner_log_count = 0
    for label, topics in filters:
        logs, query_segments = fetch_ethereum_logs(
            rpc,
            address=USDT_ETHEREUM,
            topics=topics,
            start_block=int(owner_audit["deployment_block"]),
            end_block_exclusive=args.ethereum_observed_through_block + 1,
        )
        segments.extend({"filter": label, **row} for row in query_segments)
        for log in logs:
            normalized = normalize_evm_transfer_log(
                log,
                contract=USDT_ETHEREUM,
                allow_zero_amount=True,
            )
            identity = (
                str(normalized["transaction_hash"]),
                int(normalized["event_index"]),
            )
            if normalized["raw_amount"] == "0":
                existing = zero_amount_logs_by_identity.get(identity)
                if existing is not None and canonical_hash(existing) != canonical_hash(
                    log
                ):
                    raise StablecoinRemediationError(
                        "usdt_ethereum_zero_amount_log_identity_conflict"
                    )
                zero_amount_logs_by_identity[identity] = log
                continue
            is_zero = normalized["from_address"] == ZERO_EVM or normalized[
                "to_address"
            ] == ZERO_EVM
            is_active_owner = _owner_active(
                history,
                str(normalized["from_address"]),
                int(normalized["block_number"]),
            ) or _owner_active(
                history,
                str(normalized["to_address"]),
                int(normalized["block_number"]),
            )
            if not is_zero and not is_active_owner:
                inactive_owner_log_count += 1
                continue
            existing = logs_by_identity.get(identity)
            if existing is not None and canonical_hash(existing) != canonical_hash(log):
                raise StablecoinRemediationError(
                    "usdt_ethereum_transfer_log_identity_conflict"
                )
            logs_by_identity[identity] = log
    evidence = {
        "contract": USDT_ETHEREUM,
        "query_start_block": int(owner_audit["deployment_block"]),
        "query_end_block_inclusive": args.ethereum_observed_through_block,
        "owner_history_audit_sha256": owner_audit_hash,
        "owner_history_complete": owner_audit["complete_owner_history_claimed"],
        "segments": segments,
        "zero_amount_logs_excluded": sorted(
            zero_amount_logs_by_identity.values(),
            key=lambda row: (
                int(str(row["blockNumber"]), 16),
                int(str(row["transactionIndex"]), 16),
                int(str(row["logIndex"]), 16),
            ),
        ),
        "inactive_owner_log_count_excluded": inactive_owner_log_count,
        "logs": sorted(
            logs_by_identity.values(),
            key=lambda row: (
                int(str(row["blockNumber"]), 16),
                int(str(row["transactionIndex"]), 16),
                int(str(row["logIndex"]), 16),
            ),
        ),
    }
    _write_json(path, evidence)
    return evidence


def _ingest_ethereum_transfers(
    args: argparse.Namespace,
    events: EventStore,
    rpc: EthereumRpc,
) -> dict[str, Any]:
    evidence = _ethereum_transfer_evidence(args, rpc)
    rows = (
        (normalize_evm_transfer_log(log, contract=USDT_ETHEREUM), log)
        for log in evidence["logs"]
    )
    events.add_many(
        "usdt_ethereum",
        "ethereum",
        rows,
        origin="remediation_zero_or_treasury_transfer",
    )
    return {
        "query_log_count": len(evidence["logs"]),
        "zero_transfer_count": events.count(
            "usdt_ethereum", event_family="zero_transfer"
        ),
        "treasury_transfer_count": events.count(
            "usdt_ethereum", event_family="treasury_transfer"
        ),
        "owner_history_complete": evidence["owner_history_complete"],
    }


def _tron_transfer_evidence(
    args: argparse.Namespace,
    client: PublicEvidenceClient,
) -> dict[str, Any]:
    path = args.output_directory / "usdt_tron.transfer-query.json"
    if path.exists():
        return read_json_object(path)
    owner_history = _read_json_any(
        args.output_directory / "usdt_tron.owner-history.json"
    )
    if not isinstance(owner_history, list):
        raise StablecoinRemediationError("tron_owner_history_not_list")
    deployment_info = read_json_object(
        args.output_directory / "usdt_tron.deployment-transaction-info.json"
    )
    deployment_timestamp_ms = deployment_info.get("blockTimeStamp")
    if (
        not isinstance(deployment_timestamp_ms, int)
        or deployment_timestamp_ms <= 0
    ):
        raise StablecoinRemediationError("tron_deployment_timestamp_invalid")
    requested_start_ms = parse_utc_ms(args.query_start_at)
    effective_start_ms = max(requested_start_ms, deployment_timestamp_ms)
    end_ms = parse_utc_ms(args.query_end_exclusive)
    if effective_start_ms >= end_ms:
        raise StablecoinRemediationError("tron_transfer_window_after_deployment_empty")
    query_addresses = (TRON_ZERO_BASE58, TRON_INITIAL_OWNER, TRON_SECOND_OWNER)
    row_variants_by_identity: dict[
        tuple[Any, ...], dict[str, dict[str, Any]]
    ] = {}
    segments: list[dict[str, Any]] = []
    excluded_inactive_identities: set[tuple[Any, ...]] = set()
    for address in query_addresses:
        checkpoint_path = (
            args.scratch_directory
            / f"usdt-tron-transfer-rows-{address.lower()}.json"
        )
        if checkpoint_path.is_file():
            checkpoint = read_json_object(checkpoint_path)
            rows = checkpoint.get("rows")
            query_segments = checkpoint.get("segments")
            if (
                checkpoint.get("related_address") != address
                or checkpoint.get("start_ms") != effective_start_ms
                or checkpoint.get("end_ms") != end_ms
                or not isinstance(rows, list)
                or not isinstance(query_segments, list)
                or any(not isinstance(row, Mapping) for row in rows)
                or any(not isinstance(row, Mapping) for row in query_segments)
            ):
                raise StablecoinRemediationError(
                    "tron_transfer_row_checkpoint_invalid"
                )
        else:
            rows, query_segments = fetch_tronscan_transfer_rows(
                client,
                related_address=address,
                start_ms=effective_start_ms,
                end_ms=end_ms,
            )
            _write_checkpoint_json(
                checkpoint_path,
                {
                    "related_address": address,
                    "start_ms": effective_start_ms,
                    "end_ms": end_ms,
                    "rows": rows,
                    "segments": query_segments,
                },
            )
        segments.extend(query_segments)
        for row in rows:
            is_zero = (
                row["from_address"] == TRON_ZERO_BASE58
                or row["to_address"] == TRON_ZERO_BASE58
            )
            is_active_owner = _owner_active(
                owner_history,
                str(row["from_address"]),
                int(row["block"]),
            ) or _owner_active(
                owner_history,
                str(row["to_address"]),
                int(row["block"]),
            )
            if not is_zero and not is_active_owner:
                excluded_inactive_identities.add(
                    (
                        str(row["transaction_id"]).lower(),
                        int(row["block"]),
                        str(row["from_address"]),
                        str(row["to_address"]),
                        str(row["quant"]),
                    )
                )
                continue
            identity = (
                str(row["transaction_id"]).lower(),
                int(row["block"]),
                str(row["from_address"]),
                str(row["to_address"]),
                str(row["quant"]),
            )
            materialized = dict(row)
            row_variants_by_identity.setdefault(identity, {})[
                canonical_hash(materialized)
            ] = materialized
    records_by_identity: dict[tuple[str, int], dict[str, Any]] = {}
    match_checkpoint_directory = (
        args.scratch_directory / "usdt-tron-transfer-event-matches"
    )
    for identity, variants in sorted(row_variants_by_identity.items()):
        transfer_rows = [variants[key] for key in sorted(variants)]
        representative = transfer_rows[0]
        identity_hash = canonical_hash({"coarse_transfer_identity": identity})
        match_path = match_checkpoint_directory / f"{identity_hash}.json"
        if match_path.is_file():
            match_payload = read_json_object(match_path)
            transaction_events = match_payload.get("transaction_events")
            if (
                match_payload.get("coarse_transfer_identity") != list(identity)
                or not isinstance(transaction_events, list)
                or any(
                    not isinstance(event, Mapping) for event in transaction_events
                )
            ):
                raise StablecoinRemediationError(
                    "tron_transfer_event_checkpoint_invalid"
                )
        else:
            transaction_events = fetch_tron_transaction_transfer_events(
                client, representative
            )
            _write_checkpoint_json(
                match_path,
                {
                    "coarse_transfer_identity": list(identity),
                    "transaction_events": transaction_events,
                },
            )
        for transaction_event in transaction_events:
            exact_identity = (
                str(transaction_event["transaction_id"]).lower(),
                int(transaction_event["event_index"]),
            )
            record = {
                "transfer_rows": transfer_rows,
                "transaction_event": dict(transaction_event),
            }
            existing = records_by_identity.get(exact_identity)
            if existing is not None and canonical_hash(existing) != canonical_hash(
                record
            ):
                raise StablecoinRemediationError(
                    "tron_exact_transfer_identity_conflict"
                )
            records_by_identity[exact_identity] = record
    records = [
        records_by_identity[key]
        for key in sorted(
            records_by_identity,
            key=lambda value: (
                int(records_by_identity[value]["transaction_event"]["block_number"]),
                value[0],
                value[1],
            ),
        )
    ]
    evidence = {
        "contract": TRON_USDT_BASE58,
        "query_start_at": args.query_start_at,
        "effective_query_start_at": utc_text(effective_start_ms / 1000),
        "deployment_block": deployment_info["blockNumber"],
        "deployment_timestamp_ms": deployment_timestamp_ms,
        "query_end_exclusive": args.query_end_exclusive,
        "query_addresses": list(query_addresses),
        "reported_total_fields_trusted": False,
        "pagination_completion": "monthly_partition_short_page_limit_50",
        "segments": segments,
        "excluded_inactive_owner_count": len(excluded_inactive_identities),
        "records": records,
    }
    _write_json(path, evidence)
    return evidence


def _ingest_tron_transfers(
    args: argparse.Namespace,
    events: EventStore,
    client: PublicEvidenceClient,
) -> dict[str, Any]:
    evidence = _tron_transfer_evidence(args, client)
    def rows() -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
        for record in evidence["records"]:
            transfer_rows = record["transfer_rows"]
            if not isinstance(transfer_rows, list) or not transfer_rows:
                raise StablecoinRemediationError(
                    "tron_transfer_candidate_rows_invalid"
                )
            normalized, _ = normalize_tron_transfer(
                transfer_rows[0], record["transaction_event"]
            )
            yield normalized, {
                "tronscan_transfer_candidates": transfer_rows,
                "trongrid_transaction_event": record["transaction_event"],
            }

    events.add_many(
        "usdt_tron",
        "tron",
        rows(),
        origin="remediation_zero_or_treasury_transfer",
    )
    return {
        "query_record_count": len(evidence["records"]),
        "zero_transfer_count": events.count(
            "usdt_tron", event_family="zero_transfer"
        ),
        "treasury_transfer_count": events.count(
            "usdt_tron", event_family="treasury_transfer"
        ),
    }


def _transfers(
    args: argparse.Namespace,
    events: EventStore,
    rpc: EthereumRpc,
    client: PublicEvidenceClient,
) -> dict[str, Any]:
    summary = {
        "stage": "transfers",
        "usdt_ethereum": _ingest_ethereum_transfers(args, events, rpc),
        "usdt_tron": _ingest_tron_transfers(args, events, client),
        "market_data_read": False,
        "strategy_results_read": False,
        "orders_authorized": False,
    }
    _write_checkpoint_json(args.scratch_directory / "transfer-summary.json", summary)
    return summary


def _headers(
    args: argparse.Namespace,
    events: EventStore,
    headers: HeaderStore,
    rpc: EthereumRpc,
    client: PublicEvidenceClient,
) -> dict[str, Any]:
    ethereum_blocks = set(events.block_numbers("usdt_ethereum"))
    ethereum_blocks.update(events.block_numbers("usdc_ethereum"))
    required_ethereum_blocks = ethereum_blocks | {
        number + 64 for number in ethereum_blocks
    }
    fetched_ethereum = fetch_ethereum_headers(
        rpc,
        headers,
        required_ethereum_blocks,
        batch_size=args.ethereum_header_batch_size,
        parallel_requests=args.ethereum_header_workers,
    )
    tron_blocks: dict[int, int] = {}
    for event, _ in events.iter_events("usdt_tron"):
        block_number = int(event["block_number"])
        timestamp_ms = parse_utc_ms(str(event["block_timestamp"]))
        existing = tron_blocks.get(block_number)
        if existing is not None and existing != timestamp_ms:
            raise StablecoinRemediationError("tron_event_block_timestamp_conflict")
        tron_blocks[block_number] = timestamp_ms
    for block_number, timestamp_ms in sorted(tron_blocks.items()):
        tron_confirmation_headers(
            client,
            headers,
            block_number,
            event_timestamp_ms=timestamp_ms,
        )
    summary = {
        "stage": "headers",
        "ethereum_event_block_count": len(ethereum_blocks),
        "ethereum_required_header_count": len(required_ethereum_blocks),
        "ethereum_fetched_this_run": fetched_ethereum,
        "ethereum_header_batch_size": args.ethereum_header_batch_size,
        "ethereum_header_workers": args.ethereum_header_workers,
        "tron_event_block_count": len(tron_blocks),
        "market_data_read": False,
        "strategy_results_read": False,
        "orders_authorized": False,
    }
    _write_checkpoint_json(args.scratch_directory / "header-summary.json", summary)
    return summary


def _remove_partial(path: Path) -> None:
    partial = path.with_name(f".{path.name}.partial")
    if partial.exists() and not path.exists():
        partial.unlink()


def _scan_sidecar(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    with gzip.open(path, "rb") as handle:
        for line in handle:
            json.loads(line)
            digest.update(line)
            count += 1
    return {
        "path": path.name,
        "format": "canonical_ndjson",
        "compression": "gzip_mtime_zero",
        "record_count": count,
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "uncompressed_sha256": digest.hexdigest(),
    }


def _finality_record(
    source_id: str,
    event: Mapping[str, Any],
    headers: HeaderStore,
    client: PublicEvidenceClient,
    header_map: Mapping[int, ChainHeader] | None = None,
) -> dict[str, Any]:
    block_number = int(event["block_number"])
    if source_spec(source_id).chain == "ethereum":
        event_header = (
            header_map.get(block_number)
            if header_map is not None
            else headers.get("ethereum", block_number)
        )
        confirmation = (
            header_map.get(block_number + 64)
            if header_map is not None
            else headers.get("ethereum", block_number + 64)
        )
        if event_header is None or confirmation is None:
            raise StablecoinRemediationError("ethereum_finality_record_header_missing")
        declared_hash = str(event["block_hash"]).lower()
        if declared_hash != event_header.block_hash:
            raise StablecoinRemediationError(
                f"ethereum_event_block_hash_mismatch:{source_id}:{block_number}"
            )
        return {
            "source_id": source_id,
            "transaction_hash": str(event["transaction_hash"]).lower(),
            "event_index": int(event["event_index"]),
            "availability_policy": ETHEREUM_AVAILABILITY_POLICY,
            "event_header": {
                "block_number": event_header.block_number,
                "block_hash": event_header.block_hash,
                "block_timestamp": utc_text(event_header.timestamp),
            },
            "confirmation_header": {
                "block_number": confirmation.block_number,
                "block_hash": confirmation.block_hash,
                "block_timestamp": utc_text(confirmation.timestamp),
            },
            "native_consensus_finality_claimed": False,
        }
    event_header, subsequent = tron_confirmation_headers(
        client,
        headers,
        block_number,
        event_timestamp_ms=parse_utc_ms(str(event["block_timestamp"])),
    )
    return {
        "source_id": source_id,
        "transaction_hash": str(event["transaction_hash"]).lower(),
        "event_index": int(event["event_index"]),
        "availability_policy": TRON_AVAILABILITY_POLICY,
        "event_header": {
            "block_number": event_header.block_number,
            "block_hash": event_header.block_hash,
            "block_timestamp": utc_text(event_header.timestamp),
            "producer": event_header.producer,
        },
        "subsequent_distinct_sr_headers": [
            {
                "block_number": row.block_number,
                "block_hash": row.block_hash,
                "block_timestamp": utc_text(row.timestamp),
                "producer": row.producer,
            }
            for row in subsequent
        ],
        "acknowledgement_count": 19,
    }


def _write_finality_evidence(
    args: argparse.Namespace,
    source_id: str,
    events: EventStore,
    headers: HeaderStore,
    client: PublicEvidenceClient,
) -> dict[str, Any]:
    path = args.output_directory / f"{source_id}.exact-confirmation.ndjson.gz"
    if path.exists():
        return _scan_sidecar(path)
    _remove_partial(path)
    with DeterministicGzipNdjsonWriter(path) as writer:
        iterator = events.iter_events(source_id)
        while batch := list(islice(iterator, 5_000)):
            header_map = None
            if source_spec(source_id).chain == "ethereum":
                required = {
                    number
                    for event, _ in batch
                    for number in (
                        int(event["block_number"]),
                        int(event["block_number"]) + 64,
                    )
                }
                header_map = headers.get_many("ethereum", required)
                if len(header_map) != len(required):
                    raise StablecoinRemediationError(
                        f"ethereum_finality_batch_header_missing:{source_id}"
                    )
            for event, _ in batch:
                writer.write(
                    _finality_record(
                        source_id,
                        event,
                        headers,
                        client,
                        header_map=header_map,
                    )
                )
    return writer.reference().as_dict()


def _write_event_sidecars(
    args: argparse.Namespace,
    source_id: str,
    events: EventStore,
    headers: HeaderStore,
    client: PublicEvidenceClient,
    *,
    finality_evidence_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_path = args.output_directory / f"{source_id}.events.ndjson.gz"
    raw_path = args.output_directory / f"{source_id}.raw.ndjson.gz"
    if normalized_path.exists() != raw_path.exists():
        raise StablecoinRemediationError(
            f"output_event_sidecar_pair_incomplete:{source_id}"
        )
    if normalized_path.exists():
        return _scan_sidecar(normalized_path), _scan_sidecar(raw_path)
    _remove_partial(normalized_path)
    _remove_partial(raw_path)
    with DeterministicGzipNdjsonWriter(normalized_path) as normalized_writer:
        with DeterministicGzipNdjsonWriter(raw_path) as raw_writer:
            iterator = events.iter_events(source_id)
            while batch := list(islice(iterator, 5_000)):
                header_map = None
                if source_spec(source_id).chain == "ethereum":
                    required = {
                        number
                        for event, _ in batch
                        for number in (
                            int(event["block_number"]),
                            int(event["block_number"]) + 64,
                        )
                    }
                    header_map = headers.get_many("ethereum", required)
                    if len(header_map) != len(required):
                        raise StablecoinRemediationError(
                            f"ethereum_event_batch_header_missing:{source_id}"
                        )
                for event, raw in batch:
                    if header_map is not None:
                        finality = _finality_record(
                            source_id,
                            event,
                            headers,
                            client,
                            header_map=header_map,
                        )
                        event_header = finality["event_header"]
                        confirmation = finality["confirmation_header"]
                        normalized = {
                            **event,
                            "block_hash": event_header["block_hash"],
                            "block_timestamp": event_header["block_timestamp"],
                            "available_at": confirmation["block_timestamp"],
                            "availability_policy": ETHEREUM_AVAILABILITY_POLICY,
                            "confirmation_block_number": confirmation[
                                "block_number"
                            ],
                            "confirmation_block_hash": confirmation["block_hash"],
                            "confirmation_block_timestamp": confirmation[
                                "block_timestamp"
                            ],
                            "confirmation_evidence_sha256": (
                                finality_evidence_sha256
                            ),
                            "canonical_block_rechecked": True,
                            "removed": False,
                        }
                    else:
                        event_header, subsequent = tron_confirmation_headers(
                            client,
                            headers,
                            int(event["block_number"]),
                            event_timestamp_ms=parse_utc_ms(
                                str(event["block_timestamp"])
                            ),
                        )
                        normalized = tron_confirmation_fields(
                            event,
                            event_header,
                            subsequent,
                            evidence_sha256=finality_evidence_sha256,
                        )
                    normalized_writer.write(normalized)
                    raw_writer.write(raw)
    return (
        normalized_writer.reference().as_dict(),
        raw_writer.reference().as_dict(),
    )


def _artifact_refs(
    output_directory: Path,
    names_and_roles: Iterable[tuple[str, str]],
) -> list[dict[str, Any]]:
    references = []
    for name, role in names_and_roles:
        path = output_directory / name
        if not path.is_file():
            raise StablecoinRemediationError(f"required_evidence_missing:{name}")
        references.append(evidence_reference(path, role=role))
    return references


def _zero_audit_usdc(
    events: EventStore,
    implementation_history: Mapping[str, Any],
    evidence_hashes: Iterable[str],
) -> dict[str, Any]:
    native_count = events.count("usdc_ethereum", event_family="native_supply")
    audit = {
        "complete": True,
        "method": "implementation_complete_control_flow_proof",
        "pair_identity": "implementation_control_flow_native_event_implies_zero_transfer",
        "native_event_count": native_count,
        "zero_transfer_event_count": native_count,
        "paired_native_event_count": native_count,
        "unmatched_native_event_count": 0,
        "unmatched_zero_transfer_event_count": 0,
        "ambiguous_pair_count": 0,
        "duplicate_suppression_policy": "native_supply_event_precedence",
        "suppressed_duplicate_count": native_count,
        "materialized_lineage_event_count": 0,
        "materialized_economic_event_count": 0,
        "materialized_zero_amount_event_count_excluded": 0,
        "evidence_artifact_sha256": sorted(set(evidence_hashes)),
        "implementation_addresses_proven": [
            row["implementation_address"]
            for row in implementation_history["entries"]
        ],
        "zero_transfer_logs_materialized": False,
    }
    audit["audit_hash"] = canonical_hash(audit)
    return audit


def _treasury_audit(
    *,
    required: bool,
    complete: bool,
    history: list[dict[str, Any]],
    included_event_count: int,
    evidence_hashes: Iterable[str],
    completeness_method: str,
    lineage_event_count: int | None = None,
    zero_amount_event_count_excluded: int = 0,
    owner_history_proof_kind: str | None = None,
    owner_history_proof_sha256: str | None = None,
) -> dict[str, Any]:
    if lineage_event_count is None:
        lineage_event_count = included_event_count + zero_amount_event_count_excluded
    audit: dict[str, Any] = {
        "required": required,
        "complete": complete,
        "address_history": history,
        "included_event_count": included_event_count,
        "lineage_event_count": lineage_event_count,
        "economic_event_count": included_event_count,
        "zero_amount_event_count_excluded": zero_amount_event_count_excluded,
        "unmatched_event_count": 0,
        "evidence_artifact_sha256": sorted(set(evidence_hashes)),
        "completeness_method": completeness_method,
    }
    if required:
        audit["derivation"] = "issue_redeem_owner_balance"
        audit["owner_history_round_trip_absence_proven"] = True
        audit["owner_history_proof_kind"] = owner_history_proof_kind
        audit["owner_history_proof_sha256"] = owner_history_proof_sha256
    audit["audit_hash"] = canonical_hash(audit)
    return audit


def _source_evidence_specs(source_id: str) -> list[tuple[str, str]]:
    if source_id == "usdt_ethereum":
        return [
            ("usdt_ethereum.sourcify.json", "verified_contract_source"),
            ("usdt_ethereum.runtime-code.json", "runtime_code"),
            (
                "usdt_ethereum.implementation-history.json",
                "implementation_history",
            ),
            (
                "usdt_ethereum.owner-history-audit.json",
                "owner_state_checkpoint_history",
            ),
            (
                "usdt_ethereum.owner-multisig.sourcify.json",
                "verified_owner_multisig_source",
            ),
            (
                _OWNER_BLOCKS_NAME,
                "initial_owner_complete_block_scan",
            ),
            (
                _OWNER_RECEIPTS_NAME,
                "initial_owner_call_receipts",
            ),
            (
                _OWNER_MULTISIG_TRANSACTIONS_NAME,
                "owner_multisig_complete_state_enumeration",
            ),
            (_OWNER_CALL_PROOF_NAME, "complete_treasury_owner_history"),
            ("usdt_ethereum.deprecate-query.json", "deprecation_history"),
            ("usdt_ethereum.transfer-query.json", "zero_treasury_transfer_query"),
            (
                "usdt_ethereum.exact-confirmation.ndjson.gz",
                "exact_confirmation_evidence",
            ),
            ("ethereum.finality-policy.html", "confirmation_policy_source"),
            ("ethereum.cutoff-boundary-rpc.json", "query_cutoff_boundary"),
            ("tether.supported-protocols.html", "issuer_contract_reference"),
        ]
    if source_id == "usdc_ethereum":
        return [
            ("usdc_ethereum.proxy.sourcify.json", "verified_proxy_source"),
            *[
                (
                    f"usdc_ethereum.impl.{address[2:10]}.sourcify.json",
                    "verified_implementation_source",
                )
                for address in USDC_IMPLEMENTATIONS
            ],
            ("usdc_ethereum.proxy-timeline-rpc.json", "proxy_upgrade_history"),
            (
                "usdc_ethereum.implementation-history.json",
                "implementation_history",
            ),
            (
                "usdc_ethereum.exact-confirmation.ndjson.gz",
                "exact_confirmation_evidence",
            ),
            ("ethereum.finality-policy.html", "confirmation_policy_source"),
            ("ethereum.cutoff-boundary-rpc.json", "query_cutoff_boundary"),
            ("circle.usdc-contract-addresses.html", "issuer_contract_reference"),
        ]
    return [
        ("usdt_tron.contract.tronscan.json", "verified_contract_metadata"),
        ("usdt_tron.code.tronscan.json", "verified_abi_runtime_code"),
        (
            "usdt_tron.deployment-transaction-info.json",
            "deployment_transaction_evidence",
        ),
        ("usdt_tron.ownership-events.json", "ownership_history"),
        ("usdt_tron.deprecate-events.json", "deprecation_history"),
        ("usdt_tron.implementation-history.json", "implementation_history"),
        ("usdt_tron.owner-history.json", "treasury_owner_history"),
        ("usdt_tron.runtime-verification.json", "runtime_verification"),
        ("usdt_tron.transfer-query.json", "zero_treasury_transfer_query"),
        (
            "usdt_tron.exact-confirmation.ndjson.gz",
            "exact_confirmation_evidence",
        ),
        ("tron.finality-policy.html", "confirmation_policy_source"),
        ("tron.cutoff-boundary-rpc.json", "query_cutoff_boundary"),
        ("tether.supported-protocols.html", "issuer_contract_reference"),
    ]


def _frozen_observed_at(output_directory: Path) -> str:
    path = output_directory / "collection-observation.json"
    if path.exists():
        payload = read_json_object(path)
        return str(payload["observed_at"])
    observed_at = datetime.now(timezone.utc).isoformat()
    _write_json(
        path,
        {
            "observed_at": observed_at,
            "market_data_read": False,
            "strategy_results_read": False,
            "orders_authorized": False,
        },
    )
    return observed_at


def _source_payload(
    args: argparse.Namespace,
    source_id: str,
    events: EventStore,
    headers: HeaderStore,
    *,
    observed_at: str,
    normalized_reference: Mapping[str, Any],
    raw_reference: Mapping[str, Any],
) -> dict[str, Any]:
    spec = source_spec(source_id)
    evidence_refs = _artifact_refs(
        args.output_directory, _source_evidence_specs(source_id)
    )
    evidence_hashes = {row["sha256"] for row in evidence_refs}
    implementation_history = read_json_object(
        args.output_directory / f"{source_id}.implementation-history.json"
    )
    if source_id == "usdc_ethereum":
        implementation_source_hashes = {
            row["verified_source_artifact_sha256"]
            for row in implementation_history["entries"]
        }
        zero_audit = _zero_audit_usdc(
            events,
            implementation_history,
            implementation_source_hashes,
        )
        treasury_audit = _treasury_audit(
            required=False,
            complete=True,
            history=[],
            included_event_count=0,
            evidence_hashes=[],
            completeness_method="not_required_by_frozen_source_contract",
        )
        treasury_complete = True
    elif source_id == "usdt_ethereum":
        native_events = [
            event
            for event, _ in events.iter_events(
                source_id, event_family="native_supply"
            )
        ]
        zero_events = [
            event
            for event, _ in events.iter_events(
                source_id, event_family="zero_transfer"
            )
        ]
        transfer_hash = file_sha256(
            args.output_directory / "usdt_ethereum.transfer-query.json"
        )
        zero_audit = supply_overlap_audit(
            native_events,
            zero_events,
            method="complete_chain_log_query",
            implementation_addresses=[USDT_ETHEREUM],
            evidence_hashes=[transfer_hash],
        )
        owner_path = args.output_directory / "usdt_ethereum.owner-history-audit.json"
        owner_audit = read_json_object(owner_path)
        owner_hash = file_sha256(owner_path)
        owner_proof_path = args.output_directory / _OWNER_CALL_PROOF_NAME
        owner_proof = read_json_object(owner_proof_path)
        owner_proof_hash = file_sha256(owner_proof_path)
        if (
            owner_proof.get("complete_owner_history_claimed") is not True
            or owner_proof.get(
                "absence_of_round_trip_change_between_equal_checkpoints_proven"
            )
            is not True
        ):
            raise StablecoinRemediationError("usdt_owner_call_proof_incomplete")
        history = owner_address_history(
            owner_audit,
            activation_evidence_sha256=owner_proof_hash,
        )
        treasury_accounting = events.amount_accounting(
            source_id, event_family="treasury_transfer"
        )
        treasury_complete = True
        treasury_audit = _treasury_audit(
            required=True,
            complete=True,
            history=history,
            included_event_count=treasury_accounting["economic_event_count"],
            lineage_event_count=treasury_accounting["lineage_event_count"],
            zero_amount_event_count_excluded=treasury_accounting[
                "zero_amount_event_count_excluded"
            ],
            evidence_hashes=[owner_hash, owner_proof_hash, transfer_hash],
            completeness_method=(
                "complete_initial_eoa_block_scan_and_verified_multisig_state_enumeration"
            ),
            owner_history_proof_kind=owner_proof["proof_kind"],
            owner_history_proof_sha256=owner_proof_hash,
        )
    else:
        native_events = [
            event
            for event, _ in events.iter_events(
                source_id, event_family="native_supply"
            )
        ]
        zero_events = [
            event
            for event, _ in events.iter_events(
                source_id, event_family="zero_transfer"
            )
        ]
        transfer_hash = file_sha256(
            args.output_directory / "usdt_tron.transfer-query.json"
        )
        zero_audit = supply_overlap_audit(
            native_events,
            zero_events,
            method="complete_chain_log_query",
            implementation_addresses=[TRON_USDT_BASE58],
            evidence_hashes=[transfer_hash],
        )
        history_payload = _read_json_any(
            args.output_directory / "usdt_tron.owner-history.json"
        )
        if not isinstance(history_payload, list):
            raise StablecoinRemediationError("tron_owner_history_not_list")
        owner_hash = file_sha256(
            args.output_directory / "usdt_tron.ownership-events.json"
        )
        treasury_accounting = events.amount_accounting(
            source_id, event_family="treasury_transfer"
        )
        treasury_complete = True
        treasury_audit = _treasury_audit(
            required=True,
            complete=True,
            history=history_payload,
            included_event_count=treasury_accounting["economic_event_count"],
            lineage_event_count=treasury_accounting["lineage_event_count"],
            zero_amount_event_count_excluded=treasury_accounting[
                "zero_amount_event_count_excluded"
            ],
            evidence_hashes=[owner_hash, transfer_hash],
            completeness_method="complete_confirmed_ownership_event_history",
            owner_history_proof_kind="complete_confirmed_ownership_event_history",
            owner_history_proof_sha256=owner_hash,
        )

    first_event, _ = next(events.iter_events(source_id))
    first_header = headers.get(spec.chain, int(first_event["block_number"]))
    if first_header is None:
        raise StablecoinRemediationError(f"first_event_header_missing:{source_id}")
    finality_name = f"{source_id}.exact-confirmation.ndjson.gz"
    finality_hash = file_sha256(args.output_directory / finality_name)
    policy_name = (
        "ethereum.finality-policy.html"
        if spec.chain == "ethereum"
        else "tron.finality-policy.html"
    )
    policy_hash = file_sha256(args.output_directory / policy_name)
    complete_families = list(spec.required_event_families)
    if not treasury_complete and "treasury_transfer" in complete_families:
        complete_families.remove("treasury_transfer")
    semantics_complete = zero_audit["complete"] is True and treasury_complete
    event_accounting = events.amount_accounting(source_id)
    finality: dict[str, Any] = {
        "policy": (
            ETHEREUM_AVAILABILITY_POLICY
            if spec.chain == "ethereum"
            else TRON_AVAILABILITY_POLICY
        ),
        "exact_availability": True,
        "canonical_recheck_complete": True,
        "reorg_detected_count": 0,
        "event_count": events.count(source_id),
        "lineage_event_count": event_accounting["lineage_event_count"],
        "economic_event_count": event_accounting["economic_event_count"],
        "zero_amount_event_count_excluded": event_accounting[
            "zero_amount_event_count_excluded"
        ],
        "evidence_artifact_sha256": finality_hash,
        "policy_source_artifact_sha256": policy_hash,
    }
    if spec.chain == "ethereum":
        finality.update(
            {"confirmation_blocks": 64, "native_consensus_finality_claimed": False}
        )
    else:
        finality.update(
            {"acknowledgement_count": 19, "subsequent_distinct_sr_count": 18}
        )
    return {
        "schema_version": STABLECOIN_CHAIN_SOURCE_VERSION,
        "source_id": source_id,
        "chain": spec.chain,
        "asset": spec.asset,
        "contract": spec.contract,
        "decimals": spec.decimals,
        "retrieved_at": observed_at,
        "event_accounting": {
            "zero_amount_policy": (
                "retain_raw_and_finality_lineage_exclude_economic_flow_and_count"
            ),
            **event_accounting,
        },
        "coverage": {
            "query_start_at": args.query_start_at,
            "query_end_exclusive": args.query_end_exclusive,
            "first_usable_at": utc_text(first_header.timestamp),
            "complete": True,
            "gap_count": 0,
            "event_families_requested": list(spec.required_event_families),
            "event_families_complete": complete_families,
        },
        "semantics": {
            "verified": semantics_complete,
            "evidence_hashes": sorted(evidence_hashes),
            "supports": ["mint", "burn"]
            + (["treasury_transfer"] if "treasury_transfer" in spec.required_event_families else []),
            "implementation_history": implementation_history,
            "zero_transfer_overlap_audit": zero_audit,
            "treasury_transfer_audit": treasury_audit,
            "blockers": (
                []
                if semantics_complete
                else ["ethereum_owner_history_round_trip_absence_not_proven"]
            ),
        },
        "finality": finality,
        "collection": {
            "embedded_raw_events": False,
            "raw_event_count": events.count(source_id),
            "normalized_event_artifact": dict(normalized_reference),
            "raw_event_artifact": dict(raw_reference),
            "evidence_artifacts": evidence_refs,
            "remediation_version": STABLECOIN_REMEDIATION_VERSION,
            "market_data_read": False,
            "strategy_results_read": False,
            "orders_authorized": False,
        },
    }


def _verify_completed_collection(output_directory: Path) -> dict[str, Any]:
    manifest = read_json_object(output_directory / "manifest.json")
    core = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    if manifest.get("manifest_hash") != canonical_hash(core):
        raise StablecoinRemediationError("v03_manifest_hash_invalid")
    for member in manifest.get("member_files", []):
        path = output_directory / member["path"]
        if (
            not path.is_file()
            or path.stat().st_size != member["size_bytes"]
            or file_sha256(path) != member["sha256"]
        ):
            raise StablecoinRemediationError(
                f"v03_manifest_member_invalid:{member['path']}"
            )
    return manifest


def _publish(
    args: argparse.Namespace,
    events: EventStore,
    headers: HeaderStore,
    client: PublicEvidenceClient,
) -> dict[str, Any]:
    manifest_path = args.output_directory / "manifest.json"
    if manifest_path.exists():
        manifest = _verify_completed_collection(args.output_directory)
        return {
            "stage": "publish",
            "manifest_hash": manifest["manifest_hash"],
            "source_files": manifest["source_files"],
            "resumed_existing_manifest": True,
            "orders_authorized": False,
        }
    observed_at = _frozen_observed_at(args.output_directory)
    source_files = []
    event_artifacts = []
    for source_id in ("usdt_ethereum", "usdt_tron", "usdc_ethereum"):
        finality_reference = _write_finality_evidence(
            args, source_id, events, headers, client
        )
        normalized_reference, raw_reference = _write_event_sidecars(
            args,
            source_id,
            events,
            headers,
            client,
            finality_evidence_sha256=finality_reference["sha256"],
        )
        source = _source_payload(
            args,
            source_id,
            events,
            headers,
            observed_at=observed_at,
            normalized_reference=normalized_reference,
            raw_reference=raw_reference,
        )
        source_path = args.output_directory / f"{source_id}.json"
        _write_json(source_path, source)
        source_files.append(
            {
                "source_id": source_id,
                "path": str(source_path),
                "size_bytes": source_path.stat().st_size,
                "sha256": file_sha256(source_path),
                "event_count": events.count(source_id),
                "lineage_event_count": source["event_accounting"][
                    "lineage_event_count"
                ],
                "economic_event_count": source["event_accounting"][
                    "economic_event_count"
                ],
                "zero_amount_event_count_excluded": source[
                    "event_accounting"
                ]["zero_amount_event_count_excluded"],
                "first_usable_at": source["coverage"]["first_usable_at"],
                "semantic_verification_complete": source["semantics"]["verified"],
                "exact_availability": source["finality"]["exact_availability"],
            }
        )
        event_artifacts.extend(
            (
                {
                    "source_id": source_id,
                    "role": "normalized_chain_events",
                    **normalized_reference,
                },
                {
                    "source_id": source_id,
                    "role": "raw_provider_events",
                    **raw_reference,
                },
                {
                    "source_id": source_id,
                    "role": "exact_confirmation_evidence",
                    **finality_reference,
                },
            )
        )
    code_paths = tuple(ROOT / path for path in PUBLISH_CODE_RELATIVE_PATHS)
    member_files = []
    for path in sorted(args.output_directory.iterdir()):
        if path.is_file() and path.name != "manifest.json":
            member_files.append(
                {
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
    incomplete_sources = [
        row["source_id"]
        for row in source_files
        if row["semantic_verification_complete"] is not True
    ]
    core = {
        "schema_version": 3,
        "artifact_type": "stablecoin_chain_event_remediated_collection",
        "remediation_version": STABLECOIN_REMEDIATION_VERSION,
        "observed_at": observed_at,
        "query_start_at": args.query_start_at,
        "query_end_exclusive": args.query_end_exclusive,
        "input_v01_manifest_hash": read_json_object(
            args.scratch_directory / "ingest-summary.json"
        )["v01_manifest_hash"],
        "source_files": source_files,
        "event_artifacts": event_artifacts,
        "member_files": member_files,
        "code_source_hashes": {
            str(path.relative_to(ROOT)): file_sha256(path) for path in code_paths
        },
        "known_incomplete_semantic_sources": incomplete_sources,
        "market_data_read": False,
        "strategy_results_read": False,
        "pnl_evaluated": False,
        "orders_authorized": False,
    }
    manifest = {**core, "manifest_hash": canonical_hash(core)}
    _write_json(manifest_path, manifest)
    _verify_completed_collection(args.output_directory)
    return {
        "stage": "publish",
        "manifest_hash": manifest["manifest_hash"],
        "source_files": source_files,
        "known_incomplete_semantic_sources": incomplete_sources,
        "resumed_existing_manifest": False,
        "market_data_read": False,
        "strategy_results_read": False,
        "orders_authorized": False,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("all", "ingest", "evidence", "transfers", "headers", "publish"),
        default="all",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--input-directory",
        type=Path,
        default=DEFAULT_INPUT_DIRECTORY,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--scratch-root", type=Path, default=DEFAULT_SCRATCH_ROOT)
    parser.add_argument(
        "--scratch-run-id",
        help="Reuse an existing mutable WSL scratch checkpoint under --scratch-root.",
    )
    parser.add_argument("--query-start-at", default="2017-01-01T00:00:00Z")
    parser.add_argument(
        "--query-end-exclusive",
        default="2026-07-01T00:00:00Z",
    )
    parser.add_argument("--ethereum-rpc-url", default=DEFAULT_ETHEREUM_RPC_URL)
    parser.add_argument(
        "--ethereum-observed-through-block",
        type=int,
        default=25_433_938,
    )
    parser.add_argument("--ethereum-header-batch-size", type=int, default=1000)
    parser.add_argument("--ethereum-header-workers", type=int, default=4)
    parser.add_argument("--owner-checkpoint-step-blocks", type=int, default=100_000)
    parser.add_argument("--owner-block-scan-batch-size", type=int, default=20)
    parser.add_argument("--owner-multisig-batch-size", type=int, default=100)
    parser.add_argument("--request-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--request-attempts", type=int, default=6)
    parser.add_argument("--minimum-request-interval-seconds", type=float, default=0.0)
    parser.add_argument(
        "--proxy-url-env",
        help="Optional repo-external environment variable containing an HTTP(S) proxy URL.",
    )
    return parser.parse_args(argv)


def _prepare_args(args: argparse.Namespace) -> argparse.Namespace:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.run_id):
        raise ValueError("stablecoin_remediation_run_id_invalid")
    if args.request_timeout_seconds <= 0 or args.request_attempts < 1:
        raise ValueError("stablecoin_remediation_request_policy_invalid")
    if args.scratch_run_id and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.scratch_run_id
    ):
        raise ValueError("stablecoin_remediation_scratch_run_id_invalid")
    if not 1 <= args.owner_block_scan_batch_size <= 50:
        raise ValueError("stablecoin_remediation_owner_block_batch_invalid")
    if not 1 <= args.owner_multisig_batch_size <= 250:
        raise ValueError("stablecoin_remediation_owner_multisig_batch_invalid")
    if args.ethereum_header_workers < 1 or args.ethereum_header_workers > 8:
        raise ValueError("stablecoin_remediation_header_workers_invalid")
    if args.minimum_request_interval_seconds < 0:
        raise ValueError("stablecoin_remediation_request_interval_invalid")
    start_ms = parse_utc_ms(args.query_start_at)
    end_ms = parse_utc_ms(args.query_end_exclusive)
    if start_ms >= end_ms:
        raise ValueError("stablecoin_remediation_query_window_invalid")
    args.input_directory = args.input_directory.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    scratch_root = args.scratch_root.expanduser().resolve()
    args.output_directory = output_root / args.run_id
    args.scratch_directory = scratch_root / (args.scratch_run_id or args.run_id)
    if str(args.scratch_directory).startswith("/mnt/"):
        raise ValueError("stablecoin_remediation_scratch_must_be_ext4")
    if args.output_directory == args.scratch_directory:
        raise ValueError("stablecoin_remediation_output_scratch_collision")
    args.output_directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    args.scratch_directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    args.tron_observed_through_block = None
    return args


def _require_checkpoint(args: argparse.Namespace, name: str) -> dict[str, Any]:
    path = args.scratch_directory / name
    if not path.is_file():
        raise StablecoinRemediationError(f"required_checkpoint_missing:{name}")
    return read_json_object(path)


def _require_ingested_events(
    args: argparse.Namespace,
    events: EventStore,
) -> None:
    summary = _require_checkpoint(args, "ingest-summary.json")
    counts = summary.get("source_native_counts")
    if not isinstance(counts, Mapping):
        raise StablecoinRemediationError("ingest_checkpoint_counts_invalid")
    for source_id in ("usdt_ethereum", "usdt_tron", "usdc_ethereum"):
        if events.count(source_id, event_family="native_supply") != int(
            counts.get(source_id, -1)
        ):
            raise StablecoinRemediationError(
                f"ingest_checkpoint_event_count_mismatch:{source_id}"
            )


def _run_phase(
    args: argparse.Namespace,
    phase: str,
    events: EventStore,
    headers: HeaderStore,
    rpc: EthereumRpc,
    client: PublicEvidenceClient,
) -> dict[str, Any]:
    if phase == "ingest":
        return _ingest(args, events)
    _require_ingested_events(args, events)
    if phase == "evidence":
        return _evidence(args, events, rpc, client)
    _require_checkpoint(args, "evidence-summary.json")
    if phase == "transfers":
        return _transfers(args, events, rpc, client)
    _require_checkpoint(args, "transfer-summary.json")
    if phase == "headers":
        return _headers(args, events, headers, rpc, client)
    _require_checkpoint(args, "header-summary.json")
    if phase == "publish":
        return _publish(args, events, headers, client)
    raise ValueError(f"stablecoin_remediation_phase_invalid:{phase}")


def main(argv: list[str] | None = None) -> int:
    args = _prepare_args(parse_args(sys.argv[1:] if argv is None else argv))
    proxy_url = _proxy_from_env(args.proxy_url_env)
    client = PublicEvidenceClient(
        timeout_seconds=args.request_timeout_seconds,
        attempts=args.request_attempts,
        minimum_interval_seconds=args.minimum_request_interval_seconds,
        proxy_url=proxy_url,
    )
    rpc = _ResilientEthereumRpc(
        args.ethereum_rpc_url,
        attempts=args.request_attempts,
        minimum_interval_seconds=args.minimum_request_interval_seconds,
    )
    phases = (
        ("ingest", "evidence", "transfers", "headers", "publish")
        if args.phase == "all"
        else (args.phase,)
    )
    summaries = []
    with EventStore(args.scratch_directory / "events.sqlite") as events:
        with HeaderStore(args.scratch_directory / "headers.sqlite") as headers:
            for phase in phases:
                summaries.append(
                    _run_phase(args, phase, events, headers, rpc, client)
                )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "phase": args.phase,
                "output_directory": str(args.output_directory),
                "scratch_directory": str(args.scratch_directory),
                "scratch_run_id": args.scratch_run_id or args.run_id,
                "transport": (
                    "owner_configured_proxy" if proxy_url else "direct_wsl"
                ),
                "summaries": summaries,
                "market_data_read": False,
                "strategy_results_read": False,
                "pnl_evaluated": False,
                "orders_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
