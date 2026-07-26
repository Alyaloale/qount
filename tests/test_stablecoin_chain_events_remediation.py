from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from scripts.research.remediate_stablecoin_chain_events import (
    PUBLISH_CODE_RELATIVE_PATHS,
    _ResilientEthereumRpc,
    _build_or_resume_usdt_owner_call_proof,
)
from qount.contracts import canonical_hash
from qount.mini_trend.stablecoin_chain_events import (
    EthereumRpc,
    PublicChainCollectionError,
)
from qount.mini_trend.stablecoin_chain_events_remediation import (
    ChainHeader,
    DeterministicGzipNdjsonWriter,
    EventStore,
    HeaderStore,
    StablecoinRemediationError,
    USDT_ETHEREUM_INITIAL_OWNER,
    USDT_ETHEREUM_MULTISIG_OWNER,
    address_topic,
    build_usdt_ethereum_owner_call_proof,
    decode_multisig_transaction_result,
    ethereum_confirmation_fields,
    fetch_ethereum_headers,
    fetch_ethereum_logs,
    fetch_immutable_evidence,
    fetch_tron_transaction_transfer_events,
    fetch_tronscan_transfer_rows,
    file_sha256,
    ingest_v01_collection,
    supply_overlap_audit,
    topic_address,
    tron_base58_to_hex,
    tron_confirmation_fields,
    tron_confirmation_headers,
    tron_hex_to_base58,
    normalize_evm_transfer_log,
    normalize_tron_transfer,
    parse_tronscan_verified_contract,
    verified_source_semantic_proof,
    verified_multisig_execution_semantic_proof,
)


class _TronHeaderClient:
    def __init__(self, producers: list[str]) -> None:
        self.producers = producers
        self.calls: list[int] = []

    def json(
        self,
        url: str,
        *,
        method: str,
        payload: object,
    ) -> dict[str, Any]:
        del url, method
        assert isinstance(payload, dict)
        number = int(payload["num"])
        self.calls.append(number)
        producer = self.producers[number]
        return {
            "blockID": f"{number:064x}",
            "block_header": {
                "raw_data": {
                    "number": number,
                    "timestamp": number * 3_000,
                    "witness_address": producer,
                }
            },
        }


class _TronscanHeaderClient:
    def __init__(
        self,
        producers: list[str],
        *,
        omit_number: int | None = None,
    ) -> None:
        self.producers = producers
        self.omit_number = omit_number
        self.calls: list[tuple[int, int]] = []

    def json(self, url: str) -> dict[str, Any]:
        query = parse_qs(urlparse(url).query)
        start_timestamp_ms = int(query["start_timestamp"][0])
        offset = int(query["start"][0])
        limit = int(query["limit"][0])
        self.calls.append((offset, limit))
        first_number = start_timestamp_ms // 3_000 + offset
        rows = []
        for number in range(first_number, first_number + limit):
            if number == self.omit_number:
                continue
            rows.append(
                {
                    "number": number,
                    "hash": f"{number:064x}",
                    "timestamp": number * 3_000,
                    "witnessAddress": self.producers[number],
                    "confirmed": True,
                }
            )
        return {"data": rows, "rangeTotal": 10_000, "total": 10_000}


class _EthereumLogRpc:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    def call(self, method: str, params: list[Any]) -> list[dict[str, Any]]:
        self.assert_method = method
        query = params[0]
        self.calls.append(query)
        start = int(query["fromBlock"], 16)
        end = int(query["toBlock"], 16)
        return [
            row
            for row in self.rows
            if start <= int(row["blockNumber"], 16) <= end
        ]


class _EthereumHeaderRpc:
    calls: list[list[int]] = []

    def __init__(self, url: str = "https://rpc.example") -> None:
        self.url = url

    def batch(
        self,
        requests: list[tuple[str, list[Any]]],
    ) -> list[dict[str, Any]]:
        numbers = [int(params[0], 16) for _, params in requests]
        self.calls.append(numbers)
        return [
            {
                "number": hex(number),
                "timestamp": hex(number * 12),
                "hash": "0x" + f"{number:064x}",
            }
            for number in numbers
        ]


class _TronscanClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.urls: list[str] = []

    def json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        from urllib.parse import parse_qs, urlparse

        self.urls.append(url)
        query = parse_qs(urlparse(url).query)
        start_ms = int(query["start_timestamp"][0])
        end_ms = int(query["end_timestamp"][0])
        offset = int(query["start"][0])
        limit = int(query["limit"][0])
        selected = [
            row for row in self.rows if start_ms <= row["block_ts"] < end_ms
        ]
        return {
            "total": 10_000,
            "rangeTotal": 10_000,
            "token_transfers": selected[offset : offset + limit],
        }


class _RawEvidenceClient:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.calls: list[tuple[str, str, object | None]] = []

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: object | None = None,
    ) -> bytes:
        self.calls.append((url, method, payload))
        return self.raw


class _TronTransactionEventClient:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events

    def json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        del url, kwargs
        return {"success": True, "data": self.events, "meta": {}}


class StablecoinChainEventRemediationTests(unittest.TestCase):
    def test_owner_proof_resumes_three_completed_sidecars(self) -> None:
        class OwnerStateRpc:
            def batch(self, requests: list[tuple[str, list[Any]]]) -> list[str]:
                self.requests = requests
                return ["0x0", "0x6000", "0x6000"]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            names = (
                "usdt_ethereum.owner-initial-eoa-blocks.ndjson.gz",
                "usdt_ethereum.owner-initial-eoa-receipts.ndjson.gz",
                "usdt_ethereum.owner-multisig-transactions.ndjson.gz",
            )
            for name in names:
                with DeterministicGzipNdjsonWriter(root / name):
                    pass
            sidecar_hashes = {name: file_sha256(root / name) for name in names}
            multisig_source = root / "usdt_ethereum.owner-multisig.sourcify.json"
            multisig_source.write_text("{}", encoding="ascii")
            owner_audit = {
                "deployment_block": 100,
                "observed_through_block": 200,
                "owner_addresses": [
                    USDT_ETHEREUM_INITIAL_OWNER,
                    USDT_ETHEREUM_MULTISIG_OWNER,
                ],
                "transitions": [
                    {
                        "activation_block": 102,
                        "previous_owner": USDT_ETHEREUM_INITIAL_OWNER,
                        "new_owner": USDT_ETHEREUM_MULTISIG_OWNER,
                    }
                ],
            }
            (root / "usdt_ethereum.owner-history-audit.json").write_text(
                json.dumps(owner_audit, sort_keys=True, separators=(",", ":")),
                encoding="ascii",
            )
            proof = {"complete_owner_history_claimed": True}
            with (
                patch(
                    "scripts.research.remediate_stablecoin_chain_events."
                    "verified_multisig_execution_semantic_proof",
                    return_value={"source_artifact_sha256": "a" * 64},
                ),
                patch(
                    "scripts.research.remediate_stablecoin_chain_events."
                    "ethereum_owner_at",
                    side_effect=(
                        USDT_ETHEREUM_INITIAL_OWNER,
                        USDT_ETHEREUM_INITIAL_OWNER,
                        USDT_ETHEREUM_MULTISIG_OWNER,
                        USDT_ETHEREUM_MULTISIG_OWNER,
                    ),
                ),
                patch(
                    "scripts.research.remediate_stablecoin_chain_events."
                    "build_usdt_ethereum_owner_call_proof",
                    return_value=proof,
                ) as build,
            ):
                actual = _build_or_resume_usdt_owner_call_proof(
                    SimpleNamespace(
                        output_directory=root,
                        owner_block_scan_batch_size=1,
                        owner_multisig_batch_size=1,
                    ),
                    OwnerStateRpc(),  # type: ignore[arg-type]
                    owner_audit=owner_audit,
                    multisig_payload={},
                    multisig_source_sha256="a" * 64,
                )

            self.assertEqual(actual, proof)
            self.assertEqual(build.call_count, 1)
            self.assertTrue((root / "usdt_ethereum.owner-call-proof.json").is_file())
            self.assertEqual(
                sidecar_hashes,
                {name: file_sha256(root / name) for name in names},
            )

    def test_resilient_ethereum_rpc_retries_bounded_transport_failures(self) -> None:
        requests = [("eth_blockNumber", [])]
        rpc = _ResilientEthereumRpc(
            "https://rpc.example",
            attempts=3,
            minimum_interval_seconds=0.0,
        )
        error = PublicChainCollectionError("temporary")
        with (
            patch.object(
                EthereumRpc,
                "batch",
                side_effect=(error, error, ["0x1"]),
            ) as batch,
            patch(
                "scripts.research.remediate_stablecoin_chain_events.time.sleep"
            ) as sleep,
        ):
            self.assertEqual(rpc.batch(requests), ["0x1"])

        self.assertEqual(batch.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_resilient_ethereum_rpc_fails_closed_at_attempt_limit(self) -> None:
        rpc = _ResilientEthereumRpc(
            "https://rpc.example",
            attempts=2,
            minimum_interval_seconds=0.0,
        )
        error = PublicChainCollectionError("persistent")
        with (
            patch.object(EthereumRpc, "call", side_effect=error) as call,
            patch("scripts.research.remediate_stablecoin_chain_events.time.sleep"),
            self.assertRaisesRegex(PublicChainCollectionError, "persistent"),
        ):
            rpc.call("eth_blockNumber", [])

        self.assertEqual(call.call_count, 2)

    def test_publish_code_provenance_covers_transport_and_remediation(self) -> None:
        self.assertEqual(
            set(PUBLISH_CODE_RELATIVE_PATHS),
            {
                "src/qount/mini_trend/stablecoin_impulse_g0.py",
                "src/qount/mini_trend/stablecoin_chain_events.py",
                "src/qount/mini_trend/stablecoin_chain_events_remediation.py",
                "scripts/research/remediate_stablecoin_chain_events.py",
            },
        )

    def test_immutable_evidence_supports_post_and_resumes_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.json"
            client = _RawEvidenceClient(b'{"blockNumber":8418292}')
            payload = {"value": "creator-transaction"}

            first = fetch_immutable_evidence(
                client,
                "https://api.trongrid.io/wallet/gettransactioninfobyid",
                path,
                method="POST",
                payload=payload,
            )
            resumed = fetch_immutable_evidence(
                _RawEvidenceClient(b"different"),
                "https://api.trongrid.io/wallet/gettransactioninfobyid",
                path,
                method="POST",
                payload=payload,
            )

        self.assertEqual(first, b'{"blockNumber":8418292}')
        self.assertEqual(resumed, first)
        self.assertEqual(
            client.calls,
            [
                (
                    "https://api.trongrid.io/wallet/gettransactioninfobyid",
                    "POST",
                    payload,
                )
            ],
        )

    def test_address_topics_round_trip_and_reject_nonzero_padding(self) -> None:
        address = "0x1234567890abcdef1234567890abcdef12345678"
        self.assertEqual(topic_address(address_topic(address)), address)
        with self.assertRaisesRegex(ValueError, "padding"):
            topic_address("0x1" + "0" * 63)
        self.assertEqual(
            tron_hex_to_base58("0x0000000000000000000000000000000000000000"),
            "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
        )
        self.assertEqual(
            tron_base58_to_hex("TBPxhVAsuzoFnKyXtc1o2UySEydPHgATto"),
            "0x0fa695d6b065707cb4e0ef73b751c93347682bf2",
        )

    def test_verified_source_ast_proves_storage_and_zero_transfer_calls(self) -> None:
        def function(name: str) -> dict[str, Any]:
            event_name = name.title()
            operator = "+=" if name == "mint" else "-="
            return {
                "nodeType": "FunctionDefinition",
                "name": name,
                "body": {
                    "nodeType": "Block",
                    "statements": [
                        {
                            "nodeType": "Assignment",
                            "operator": operator,
                            "leftHandSide": {
                                "nodeType": "Identifier",
                                "name": "totalSupply_",
                            },
                        },
                        {
                            "nodeType": "Assignment",
                            "operator": operator,
                            "leftHandSide": {
                                "nodeType": "IndexAccess",
                                "baseExpression": {
                                    "nodeType": "Identifier",
                                    "name": "balances",
                                },
                            },
                        },
                        {
                            "nodeType": "EmitStatement",
                            "eventCall": {
                                "nodeType": "FunctionCall",
                                "expression": {
                                    "nodeType": "Identifier",
                                    "name": event_name,
                                },
                            },
                        },
                        {
                            "nodeType": "EmitStatement",
                            "eventCall": {
                                "nodeType": "FunctionCall",
                                "expression": {
                                    "nodeType": "Identifier",
                                    "name": "Transfer",
                                },
                            },
                        },
                    ],
                },
            }

        payload = {
            "stdJsonOutput": {
                "sources": {
                    "Token.sol": {
                        "ast": {
                            "nodeType": "SourceUnit",
                            "nodes": [function("mint"), function("burn")],
                        }
                    }
                }
            }
        }
        proof = verified_source_semantic_proof(
            payload,
            source_artifact_sha256="a" * 64,
            native_mint_events=["mint"],
            native_burn_events=["burn"],
            zero_transfer_emission="paired",
        )
        self.assertEqual(proof["zero_transfer_emission"], "paired")
        self.assertIn("totalsupply_", proof["supply_storage_writes"])
        self.assertIn("balances", proof["supply_storage_writes"])

    def test_verified_multisig_source_and_complete_owner_call_audit(self) -> None:
        multisig = USDT_ETHEREUM_MULTISIG_OWNER
        token = "0xdac17f958d2ee523a2206206994597c13d831ec7"
        source = """
        contract MultiSigWallet {
            uint public transactionCount;
            struct Transaction { address destination; uint value; bytes data; bool executed; }
            mapping (uint => Transaction) public transactions;
            function addTransaction(address destination, uint value, bytes data)
                internal returns (uint transactionId) {
                transactionId = transactionCount;
                transactions[transactionId] = Transaction(destination, value, data, false);
                transactionCount += 1;
            }
            function executeTransaction(uint transactionId) public {
                Transaction tx = transactions[transactionId];
                tx.executed = true;
                if (tx.destination.call.value(tx.value)(tx.data)) { }
                else { tx.executed = false; }
            }
        }
        """
        compiled_metadata = "a165627a7a72305820" + "11" * 32 + "0029"
        observed_metadata = "a165627a7a72305820" + "22" * 32 + "0029"
        payload = {
            "address": multisig,
            "match": "match",
            "runtimeMatch": "match",
            "creationMatch": "match",
            "proxyResolution": {"isProxy": False},
            "deployment": {"blockNumber": "90"},
            "abi": [
                {
                    "type": "function",
                    "name": "transactionCount",
                    "inputs": [],
                    "outputs": [{"type": "uint256"}],
                },
                {
                    "type": "function",
                    "name": "transactions",
                    "inputs": [{"type": "uint256"}],
                    "outputs": [
                        {"type": "address"},
                        {"type": "uint256"},
                        {"type": "bytes"},
                        {"type": "bool"},
                    ],
                },
            ],
            "signatures": {
                "function": [
                    {
                        "signature": "transactionCount()",
                        "signatureHash4": "0xb77bf600",
                    },
                    {
                        "signature": "transactions(uint256)",
                        "signatureHash4": "0x9ace38c2",
                    },
                ]
            },
            "sources": {"MultiSigWallet.sol": {"content": source}},
            "compilation": {
                "name": "MultiSigWallet",
                "fullyQualifiedName": "MultiSigWallet.sol:MultiSigWallet",
            },
            "stdJsonOutput": {
                "contracts": {
                    "MultiSigWallet.sol": {
                        "MultiSigWallet": {
                            "evm": {
                                "deployedBytecode": {
                                    "object": "6000" + compiled_metadata
                                }
                            }
                        }
                    }
                }
            },
        }
        source_hash = "a" * 64
        semantic_proof = verified_multisig_execution_semantic_proof(
            payload,
            source_artifact_sha256=source_hash,
        )

        def block(number: int, transactions: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "block_number": number,
                "raw_block": {
                    "number": hex(number),
                    "hash": "0x" + f"{number:064x}",
                    "transactions": transactions,
                },
                "initial_owner_code": "0x",
                "initial_owner_nonce": "0x1",
            }

        def ownership_input(target: str) -> str:
            return "0xf2fde38b" + "0" * 24 + target.removeprefix("0x")

        failed_hash = "0x" + "1" * 64
        success_hash = "0x" + "2" * 64
        initial_rows = [
            block(100, []),
            block(
                101,
                [
                    {
                        "from": USDT_ETHEREUM_INITIAL_OWNER,
                        "to": token,
                        "hash": failed_hash,
                        "input": ownership_input(multisig),
                    }
                ],
            ),
            block(
                102,
                [
                    {
                        "from": USDT_ETHEREUM_INITIAL_OWNER,
                        "to": token,
                        "hash": success_hash,
                        "input": ownership_input(multisig),
                    }
                ],
            ),
        ]
        receipts = [
            {
                "transaction_hash": failed_hash,
                "raw_receipt": {
                    "transactionHash": failed_hash,
                    "blockNumber": hex(101),
                    "blockHash": "0x" + f"{101:064x}",
                    "status": "0x0",
                },
            },
            {
                "transaction_hash": success_hash,
                "raw_receipt": {
                    "transactionHash": success_hash,
                    "blockNumber": hex(102),
                    "blockHash": "0x" + f"{102:064x}",
                    "status": "0x1",
                },
            },
        ]

        def encode_transaction(destination: str, data: str, executed: bool) -> str:
            raw_data = data.removeprefix("0x")
            padded = raw_data + "0" * ((64 - len(raw_data) % 64) % 64)
            return "0x" + "".join(
                (
                    "0" * 24 + destination.removeprefix("0x"),
                    f"{0:064x}",
                    f"{128:064x}",
                    f"{int(executed):064x}",
                    f"{len(raw_data) // 2:064x}",
                    padded,
                )
            )

        transfer_data = "0xa9059cbb" + "0" * 64
        pending_owner_data = ownership_input("0x" + "3" * 40)
        raw_results = [
            encode_transaction(token, transfer_data, True),
            encode_transaction(token, pending_owner_data, False),
        ]
        multisig_rows = [
            {
                "transaction_id": index,
                "raw_call_result": raw,
                "decoded": decode_multisig_transaction_result(raw),
            }
            for index, raw in enumerate(raw_results)
        ]
        owner_audit = {
            "deployment_block": 100,
            "observed_through_block": 200,
            "owner_addresses": [USDT_ETHEREUM_INITIAL_OWNER, multisig],
            "transitions": [
                {
                    "activation_block": 102,
                    "previous_owner": USDT_ETHEREUM_INITIAL_OWNER,
                    "new_owner": multisig,
                }
            ],
        }
        references = {
            "initial_owner_blocks": {
                "path": "blocks.gz",
                "record_count": 3,
                "sha256": "b" * 64,
            },
            "initial_owner_receipts": {
                "path": "receipts.gz",
                "record_count": 2,
                "sha256": "c" * 64,
            },
            "multisig_transactions": {
                "path": "transactions.gz",
                "record_count": 2,
                "sha256": "d" * 64,
            },
            "multisig_verified_source": {
                "path": "source.json",
                "sha256": source_hash,
            },
        }
        proof = build_usdt_ethereum_owner_call_proof(
            contract=token,
            owner_audit=owner_audit,
            owner_audit_sha256="e" * 64,
            multisig_semantic_proof=semantic_proof,
            initial_block_rows=initial_rows,
            initial_receipt_rows=receipts,
            multisig_transaction_rows=multisig_rows,
            state_observations={
                "token_owner_at_deployment": USDT_ETHEREUM_INITIAL_OWNER,
                "token_owner_before_transition": USDT_ETHEREUM_INITIAL_OWNER,
                "token_owner_at_transition": multisig,
                "token_owner_at_observed": multisig,
                "multisig_runtime_code_at_transition": (
                    "0x6000" + observed_metadata
                ),
                "multisig_runtime_code_at_observed": "0x6000" + observed_metadata,
                "multisig_transaction_count_raw": "0x" + f"{2:064x}",
            },
            evidence_references=references,
        )

        self.assertTrue(proof["complete_owner_history_claimed"])
        self.assertEqual(proof["initial_eoa"]["scanned_block_count"], 3)
        self.assertEqual(proof["initial_eoa"]["successful_transfer_ownership_call_count"], 1)
        self.assertEqual(proof["multisig"]["transaction_count"], 2)
        self.assertEqual(proof["multisig"]["executed_transfer_ownership_transaction_count"], 0)
        self.assertTrue(
            proof["multisig"]["runtime_verification"][
                "metadata_only_difference_from_compiled_runtime"
            ]
        )

    def test_evm_transfer_logs_are_range_queried_and_structurally_decoded(self) -> None:
        contract = "0x" + "c" * 40
        from_address = "0x" + "1" * 40
        to_address = "0x" + "2" * 40
        raw = {
            "address": contract,
            "blockNumber": "0x65",
            "transactionIndex": "0x2",
            "logIndex": "0x3",
            "transactionHash": "0x" + "4" * 64,
            "blockHash": "0x" + "5" * 64,
            "data": "0x64",
            "topics": [
                "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                address_topic(from_address),
                address_topic(to_address),
            ],
            "removed": False,
        }
        rpc = _EthereumLogRpc([raw])
        rows, segments = fetch_ethereum_logs(
            rpc,  # type: ignore[arg-type]
            address=contract,
            topics=[raw["topics"][0], address_topic(from_address)],
            start_block=100,
            end_block_exclusive=103,
        )
        self.assertEqual(rows, [raw])
        self.assertEqual(segments[0]["event_count"], 1)
        normalized = normalize_evm_transfer_log(raw, contract=contract)
        self.assertEqual(normalized["from_address"], from_address)
        self.assertEqual(normalized["to_address"], to_address)
        self.assertEqual(normalized["raw_amount"], "100")
        zero_amount = {**raw, "data": "0x0"}
        with self.assertRaisesRegex(
            StablecoinRemediationError, "evm_transfer_log_identity_invalid"
        ):
            normalize_evm_transfer_log(zero_amount, contract=contract)
        self.assertEqual(
            normalize_evm_transfer_log(
                zero_amount,
                contract=contract,
                allow_zero_amount=True,
            )["raw_amount"],
            "0",
        )

    def test_tronscan_pagination_ignores_capped_total_and_uses_exact_event(self) -> None:
        start_ms = 1_609_459_200_000
        end_ms = 1_612_137_600_000
        rows = []
        for index in range(51):
            rows.append(
                {
                    "transaction_id": f"{index:064x}",
                    "status": 0,
                    "block_ts": start_ms + index * 1_000,
                    "from_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
                    "to_address": "TBPxhVAsuzoFnKyXtc1o2UySEydPHgATto",
                    "block": 100 + index,
                    "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                    "quant": str(1_000 + index),
                    "confirmed": True,
                    "contractRet": "SUCCESS",
                }
            )
        client = _TronscanClient(rows)
        fetched, segments = fetch_tronscan_transfer_rows(
            client,  # type: ignore[arg-type]
            related_address="T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
            start_ms=start_ms,
            end_ms=end_ms,
        )
        self.assertEqual(len(fetched), 51)
        self.assertEqual([row["returned_count"] for row in segments], [50, 1])
        self.assertTrue(all(row["reported_total_ignored"] == 10_000 for row in segments))

        transaction_event = {
            "transaction_id": rows[0]["transaction_id"],
            "event_index": 2,
            "block_number": rows[0]["block"],
            "block_timestamp": rows[0]["block_ts"],
            "result": {
                "from": "0x0000000000000000000000000000000000000000",
                "to": "0x0fa695d6b065707cb4e0ef73b751c93347682bf2",
                "value": rows[0]["quant"],
            },
        }
        normalized, raw = normalize_tron_transfer(rows[0], transaction_event)
        self.assertEqual(normalized["event_index"], 2)
        self.assertEqual(
            normalized["from_address"],
            "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
        )
        self.assertIn("trongrid_transaction_event", raw)

    def test_trongrid_event_index_disambiguates_identical_transfer_rows(self) -> None:
        transfer_row = {
            "transaction_id": "a" * 64,
            "from_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
            "to_address": "TBPxhVAsuzoFnKyXtc1o2UySEydPHgATto",
            "quant": "1000000",
        }
        event_basis = {
            "transaction_id": transfer_row["transaction_id"],
            "block_number": 123,
            "block_timestamp": 1_609_459_200_000,
            "event_name": "Transfer",
            "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
            "result": {
                "from": "0x0000000000000000000000000000000000000000",
                "to": "0x0fa695d6b065707cb4e0ef73b751c93347682bf2",
                "value": transfer_row["quant"],
            },
        }
        client = _TronTransactionEventClient(
            [
                {**event_basis, "event_index": 7},
                {**event_basis, "event_index": 3},
            ]
        )

        matches = fetch_tron_transaction_transfer_events(
            client,  # type: ignore[arg-type]
            transfer_row,
        )

        self.assertEqual([row["event_index"] for row in matches], [3, 7])

    def test_tronscan_verified_abi_accepts_entrys_wrapper(self) -> None:
        contract = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        creator = "THPvaUhoh2Qn2y9THCZML3H815hhFhn5YC"
        _, _, abi, bytecode_hash = parse_tronscan_verified_contract(
            {
                "data": [
                    {
                        "address": contract,
                        "verify_status": 2,
                        "is_proxy": False,
                        "creator": {"address": creator, "txHash": "a" * 64},
                    }
                ]
            },
            {
                "data": {
                    "address": contract,
                    "verify_status": 2,
                    "abi": json.dumps(
                        {"entrys": [{"name": "issue", "type": "Function"}]}
                    ),
                    "byteCode": "00",
                }
            },
        )
        self.assertEqual(abi, [{"name": "issue", "type": "Function"}])
        self.assertEqual(len(bytecode_hash), 64)

    def test_overlap_audit_reconciles_paired_and_zero_only_events(self) -> None:
        native = [
            {
                "transaction_hash": "a",
                "event_name": "Issue",
                "raw_amount": "100",
            },
            {
                "transaction_hash": "b",
                "event_name": "Redeem",
                "raw_amount": "30",
            },
        ]
        zero = [
            {
                "transaction_hash": "a",
                "event_name": "Transfer",
                "raw_amount": "100",
                "from_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
            },
            {
                "transaction_hash": "c",
                "event_name": "Transfer",
                "raw_amount": "50",
                "from_address": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
            },
        ]
        audit = supply_overlap_audit(
            native,
            zero,
            method="complete_chain_log_query",
            implementation_addresses=["contract"],
            evidence_hashes=["a" * 64],
        )
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["paired_native_event_count"], 1)
        self.assertEqual(audit["unmatched_native_event_count"], 1)
        self.assertEqual(audit["unmatched_zero_transfer_event_count"], 1)
        self.assertEqual(audit["suppressed_duplicate_count"], 1)

    def test_deterministic_gzip_sidecar_has_stable_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / "one.ndjson.gz", root / "two.ndjson.gz"]
            references = []
            for path in paths:
                with DeterministicGzipNdjsonWriter(path) as writer:
                    writer.write({"b": 2, "a": 1})
                    writer.write({"row": 2})
                references.append(writer.reference())
            self.assertEqual(file_sha256(paths[0]), file_sha256(paths[1]))
            self.assertEqual(
                references[0].uncompressed_sha256,
                references[1].uncompressed_sha256,
            )
            with gzip.open(paths[0], "rt", encoding="ascii") as handle:
                self.assertEqual(
                    [json.loads(line) for line in handle],
                    [{"a": 1, "b": 2}, {"row": 2}],
                )

    def test_header_store_rejects_conflicting_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "headers.sqlite"
            with HeaderStore(path) as store:
                original = ChainHeader("ethereum", 1, "0x" + "a" * 64, 10)
                store.put_many([original])
                self.assertEqual(store.get("ethereum", 1), original)
                with self.assertRaisesRegex(
                    StablecoinRemediationError,
                    "header_store_conflict",
                ):
                    store.put_many(
                        [ChainHeader("ethereum", 1, "0x" + "b" * 64, 10)]
                    )

    def test_ethereum_header_parallel_fetch_commits_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _EthereumHeaderRpc.calls = []
            path = Path(temporary) / "headers.sqlite"
            with HeaderStore(path) as store:
                with patch(
                    "qount.mini_trend.stablecoin_chain_events_remediation.EthereumRpc",
                    _EthereumHeaderRpc,
                ):
                    fetched = fetch_ethereum_headers(
                        _EthereumHeaderRpc(),  # type: ignore[arg-type]
                        store,
                        [4, 3, 2, 1],
                        batch_size=2,
                        parallel_requests=2,
                    )
                    resumed = fetch_ethereum_headers(
                        _EthereumHeaderRpc(),  # type: ignore[arg-type]
                        store,
                        [1, 2, 3, 4],
                        batch_size=2,
                        parallel_requests=2,
                    )
                self.assertEqual(fetched, 4)
                self.assertEqual(resumed, 0)
                self.assertEqual(
                    store.get("ethereum", 4),
                    ChainHeader("ethereum", 4, "0x" + f"{4:064x}", 48),
                )
                self.assertEqual(
                    sorted(_EthereumHeaderRpc.calls),
                    [[1, 2], [3, 4]],
                )

    def test_v01_manifest_and_sidecars_are_bound_before_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_files = []
            artifact_rows = []
            for index, (source_id, chain, event_name) in enumerate(
                (
                    ("usdt_ethereum", "ethereum", "Issue"),
                    ("usdt_tron", "tron", "Issue"),
                    ("usdc_ethereum", "ethereum", "Mint"),
                )
            ):
                normalized_path = root / f"{source_id}.events.ndjson.gz"
                raw_path = root / f"{source_id}.raw.ndjson.gz"
                normalized = {
                    "transaction_hash": f"tx-{index}",
                    "event_index": index,
                    "block_number": 100 + index,
                    "event_name": event_name,
                    "raw_amount": "1",
                }
                with DeterministicGzipNdjsonWriter(normalized_path) as writer:
                    writer.write(normalized)
                normalized_reference = writer.reference().as_dict()
                with DeterministicGzipNdjsonWriter(raw_path) as raw_writer:
                    raw_writer.write({"provider": source_id})
                raw_reference = raw_writer.reference().as_dict()
                payload = {
                    "schema_version": "stablecoin_chain_event_source_v0.1",
                    "source_id": source_id,
                    "chain": chain,
                    "collection": {
                        "normalized_event_artifact": normalized_reference,
                        "raw_event_artifact": raw_reference,
                        "raw_event_count": 1,
                    },
                }
                source_path = root / f"{source_id}.json"
                source_path.write_text(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
                source_files.append(
                    {
                        "source_id": source_id,
                        "path": str(source_path),
                        "size_bytes": source_path.stat().st_size,
                        "sha256": file_sha256(source_path),
                    }
                )
                artifact_rows.extend(
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
                    )
                )
            core = {
                "artifact_type": "stablecoin_native_supply_event_collection",
                "scope": "native_supply_events_only",
                "market_data_read": False,
                "strategy_results_read": False,
                "orders_authorized": False,
                "source_files": source_files,
                "event_artifacts": artifact_rows,
            }
            (root / "manifest.json").write_text(
                json.dumps(
                    {**core, "manifest_hash": canonical_hash(core)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            with EventStore(root / "events.sqlite") as event_store:
                manifest, _ = ingest_v01_collection(root, event_store)
                self.assertEqual(manifest["manifest_hash"], canonical_hash(core))
                self.assertEqual(event_store.count("usdc_ethereum"), 1)
                ingest_v01_collection(root, event_store)
                self.assertEqual(event_store.count("usdc_ethereum"), 1)

            normalized_path = root / "usdc_ethereum.events.ndjson.gz"
            normalized_path.write_bytes(normalized_path.read_bytes() + b"tamper")
            with EventStore(root / "events-2.sqlite") as second_store:
                with self.assertRaisesRegex(
                    StablecoinRemediationError,
                    "sidecar_hash_mismatch",
                ):
                    ingest_v01_collection(root, second_store)

    def test_confirmation_fields_bind_exact_headers_and_sr_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "headers.sqlite"
            with HeaderStore(path) as store:
                store.put_many(
                    [
                        ChainHeader("ethereum", 100, "0x" + "a" * 64, 1_000),
                        ChainHeader("ethereum", 164, "0x" + "b" * 64, 1_800),
                    ]
                )
                event = {
                    "block_number": 100,
                    "block_hash": "0x" + "a" * 64,
                }
                remediated = ethereum_confirmation_fields(
                    event,
                    store,
                    evidence_sha256="c" * 64,
                )
                self.assertEqual(remediated["confirmation_block_number"], 164)
                self.assertEqual(remediated["available_at"], "1970-01-01T00:30:00Z")

                producers = [f"sr-{index % 20:02d}" for index in range(300)]
                client = _TronHeaderClient(producers)
                event_header, subsequent = tron_confirmation_headers(
                    client,  # type: ignore[arg-type]
                    store,
                    200,
                )
                tron = tron_confirmation_fields(
                    {"block_number": 200},
                    event_header,
                    subsequent,
                    evidence_sha256="d" * 64,
                )
                self.assertEqual(
                    len(tron["confirmation_subsequent_sr_addresses"]),
                    18,
                )
                self.assertNotIn(
                    tron["event_block_producer"],
                    tron["confirmation_subsequent_sr_addresses"],
                )

    def test_tronscan_confirmation_pages_are_contiguous_and_resume_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            addresses = [
                tron_hex_to_base58(f"{index % 20 + 1:040x}")
                for index in range(20)
            ]
            producers = [addresses[0]] * 300
            for number, address in enumerate(addresses[1:19], start=250):
                producers[number] = address
            client = _TronscanHeaderClient(producers)
            with HeaderStore(Path(temporary) / "headers.sqlite") as store:
                event_header, subsequent = tron_confirmation_headers(
                    client,  # type: ignore[arg-type]
                    store,
                    200,
                    event_timestamp_ms=600_000,
                )
                self.assertEqual(event_header.block_number, 200)
                self.assertEqual(len(subsequent), 18)
                self.assertEqual(client.calls, [(0, 50), (50, 50)])

                resumed = tron_confirmation_headers(
                    client,  # type: ignore[arg-type]
                    store,
                    200,
                    event_timestamp_ms=600_000,
                )
                self.assertEqual(resumed, (event_header, subsequent))
                self.assertEqual(client.calls, [(0, 50), (50, 50)])

    def test_tronscan_confirmation_rejects_incomplete_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            producers = [
                tron_hex_to_base58(f"{index % 20 + 1:040x}")
                for index in range(300)
            ]
            client = _TronscanHeaderClient(producers, omit_number=215)
            with HeaderStore(Path(temporary) / "headers.sqlite") as store:
                with self.assertRaisesRegex(
                    StablecoinRemediationError,
                    "tronscan_header_page_incomplete",
                ):
                    tron_confirmation_headers(
                        client,  # type: ignore[arg-type]
                        store,
                        200,
                        event_timestamp_ms=600_000,
                    )


if __name__ == "__main__":
    unittest.main()
