from __future__ import annotations

import copy
import gzip
import hashlib
import json
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.research.run_stablecoin_impulse_g0 import _hydrate_source_events
from qount.contracts import canonical_hash
from qount.mini_trend.stablecoin_chain_events import (
    LEGACY_STABLECOIN_CHAIN_SOURCE_VERSION,
    _JsonClient,
    _ethereum_block_context,
)
from qount.mini_trend.stablecoin_impulse_g0 import (
    SOURCE_SPECS,
    STABLECOIN_CHAIN_SOURCE_VERSION,
    STABLECOIN_IMPULSE_G0_PROTOCOL,
    build_stablecoin_impulse_g0_report,
    build_stablecoin_impulse_preregistration,
    frozen_weekly_anchors,
    validate_stablecoin_impulse_preregistration,
)


UTC = timezone.utc
EVIDENCE_HASH = "a" * 64
QUERY_EVIDENCE_HASH = "b" * 64
FINALITY_EVIDENCE_HASH = "c" * 64
TREASURY = "0x5754284f345afc66a98fbb0a0afe71e0f007b949"
TRON_ZERO_ADDRESS = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"


class _GzipResponse:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.headers = {"Content-Encoding": "gzip"}

    def __enter__(self) -> "_GzipResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return self.raw


class _GzipOpener:
    def __init__(self, payload: object) -> None:
        self.raw = gzip.compress(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        )
        self.accept_encoding: str | None = None

    def open(self, request: Any, *, timeout: float) -> _GzipResponse:
        del timeout
        self.accept_encoding = request.get_header("Accept-encoding")
        return _GzipResponse(self.raw)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _event(
    *,
    transaction_hash: str,
    event_index: int,
    event_name: str,
    amount: int,
    event_at: datetime,
    from_address: str | None = None,
    to_address: str | None = None,
) -> dict[str, Any]:
    available_at = event_at + timedelta(minutes=2)
    return {
        "transaction_hash": transaction_hash,
        "event_index": event_index,
        "block_number": 1_000_000 + event_index,
        "block_hash": f"0x{event_index + 1:064x}",
        "block_timestamp": _iso(event_at),
        "available_at": _iso(available_at),
        "availability_policy": "ethereum_event_block_plus_64",
        "confirmation_block_number": 1_000_000 + event_index + 64,
        "confirmation_block_hash": f"0x{event_index + 10_000:064x}",
        "confirmation_block_timestamp": _iso(available_at),
        "confirmation_evidence_sha256": FINALITY_EVIDENCE_HASH,
        "canonical_block_rechecked": True,
        "event_name": event_name,
        "amount": str(amount),
        "from_address": from_address,
        "to_address": to_address,
        "removed": False,
    }


def _source_payload(source_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    spec = next(source for source in SOURCE_SPECS if source.source_id == source_id)
    supports = ["mint", "burn"]
    treasury_addresses: list[str] = []
    if "treasury_transfer" in spec.required_event_families:
        supports.append("treasury_transfer")
        treasury_addresses.append(TREASURY)
    if spec.chain == "tron":
        for event in events:
            event["availability_policy"] = (
                "tron_event_producer_plus_18_distinct_srs"
            )
            event["confirmation_block_number"] = event["block_number"] + 18
            event["confirmation_acknowledgement_count"] = 19
            event["confirmation_subsequent_distinct_sr_count"] = 18
            event["event_block_producer"] = "tron-sr-00"
            event["confirmation_subsequent_sr_addresses"] = [
                f"tron-sr-{index:02d}" for index in range(1, 19)
            ]
            event["confirmation_block_producer"] = "tron-sr-18"
    first_usable = {
        "usdt_ethereum": "2017-11-28T00:00:00Z",
        "usdt_tron": "2021-04-01T00:00:00Z",
        "usdc_ethereum": "2018-09-10T00:00:00Z",
    }[source_id]
    native_event_count = sum(
        str(event.get("event_name", "")).lower()
        in {*spec.native_mint_events, *spec.native_burn_events}
        for event in events
    )
    treasury_lineage_count = sum(
        str(event.get("event_name", "")).lower() == "transfer"
        and str(event.get("from_address", "")).lower()
        not in {
            "0x0000000000000000000000000000000000000000",
            TRON_ZERO_ADDRESS.lower(),
        }
        and str(event.get("to_address", "")).lower()
        not in {
            "0x0000000000000000000000000000000000000000",
            TRON_ZERO_ADDRESS.lower(),
        }
        and (
            str(event.get("from_address", "")).lower() in treasury_addresses
            or str(event.get("to_address", "")).lower() in treasury_addresses
        )
        for event in events
    )
    treasury_zero_count = sum(
        str(event.get("event_name", "")).lower() == "transfer"
        and str(event.get("from_address", "")).lower()
        not in {
            "0x0000000000000000000000000000000000000000",
            TRON_ZERO_ADDRESS.lower(),
        }
        and str(event.get("to_address", "")).lower()
        not in {
            "0x0000000000000000000000000000000000000000",
            TRON_ZERO_ADDRESS.lower(),
        }
        and str(event.get("amount", event.get("raw_amount", ""))) == "0"
        and (
            str(event.get("from_address", "")).lower() in treasury_addresses
            or str(event.get("to_address", "")).lower() in treasury_addresses
        )
        for event in events
    )
    treasury_event_count = treasury_lineage_count - treasury_zero_count
    zero_addresses = {
        "0x0000000000000000000000000000000000000000",
        TRON_ZERO_ADDRESS.lower(),
    }
    materialized_zero_events = [
        event
        for event in events
        if str(event.get("event_name", "")).lower() == "transfer"
        and (
            str(event.get("from_address", "")).lower() in zero_addresses
            or str(event.get("to_address", "")).lower() in zero_addresses
        )
    ]
    materialized_zero_amount_count = sum(
        str(event.get("amount", event.get("raw_amount", ""))) == "0"
        for event in materialized_zero_events
    )
    implementation_addresses = (
        [spec.contract, "0x1111111111111111111111111111111111111111"]
        if source_id == "usdc_ethereum"
        else [spec.contract]
    )
    implementation_entries: list[dict[str, Any]] = []
    for index, address in enumerate(implementation_addresses):
        proof = {
            "proof_kind": (
                "verified_bytecode_and_complete_event_overlap"
                if spec.chain == "tron"
                else "verified_source_ast"
            ),
            "source_artifact_sha256": EVIDENCE_HASH,
            "native_mint_event_calls": list(spec.native_mint_events),
            "native_burn_event_calls": list(spec.native_burn_events),
            "supply_storage_writes": ["total_supply", "owner_or_recipient_balance"],
            "zero_transfer_emission": (
                "absent" if source_id == "usdt_ethereum" else "paired"
            ),
        }
        proof["proof_hash"] = canonical_hash(proof)
        implementation_entries.append(
            {
                "implementation_address": address,
                "activated_at": {
                    "block_number": 100 + index * 100,
                    "transaction_index": index,
                    "event_index": index,
                },
                "verified_source_artifact_sha256": EVIDENCE_HASH,
                "abi_sha256": "d" * 64,
                "runtime_code_sha256": "e" * 64,
                "verification_match": "match",
                "semantic_proof": proof,
            }
        )
    timeline_basis = {
        "deployment_block": 100,
        "observed_through_block": 2_000_000,
        "is_proxy": source_id == "usdc_ethereum",
        "proxy_type": (
            "zeppelinos_proxy" if source_id == "usdc_ethereum" else "none"
        ),
        "entries": implementation_entries,
    }
    implementation_history = {
        "complete": True,
        **timeline_basis,
        "upgrade_event_count": len(implementation_entries) - 1,
        "timeline_hash": canonical_hash(timeline_basis),
    }
    if source_id == "usdc_ethereum":
        zero_method = "implementation_complete_control_flow_proof"
        zero_count = native_event_count
        paired_count = native_event_count
    else:
        zero_method = "complete_chain_log_query"
        zero_count = len(materialized_zero_events)

        def identity(event: dict[str, Any]) -> tuple[str, str, str]:
            event_name = str(event.get("event_name", "")).lower()
            if event_name in {"issue", "mint"}:
                direction = "mint"
            elif event_name in {"redeem", "burn"}:
                direction = "burn"
            else:
                direction = (
                    "mint"
                    if str(event.get("from_address", "")).lower()
                    in zero_addresses
                    else "burn"
                )
            return (
                str(event.get("transaction_hash", "")).lower(),
                str(event.get("amount", event.get("raw_amount", ""))),
                direction,
            )

        native_counts = Counter(
            identity(event)
            for event in events
            if str(event.get("event_name", "")).lower()
            in {*spec.native_mint_events, *spec.native_burn_events}
        )
        zero_counts = Counter(identity(event) for event in materialized_zero_events)
        paired_count = sum(
            min(count, zero_counts.get(key, 0))
            for key, count in native_counts.items()
        )
    zero_audit = {
        "complete": True,
        "method": zero_method,
        "native_event_count": native_event_count,
        "zero_transfer_event_count": zero_count,
        "paired_native_event_count": paired_count,
        "unmatched_native_event_count": native_event_count - paired_count,
        "unmatched_zero_transfer_event_count": zero_count - paired_count,
        "ambiguous_pair_count": 0,
        "duplicate_suppression_policy": "native_supply_event_precedence",
        "suppressed_duplicate_count": paired_count,
        "materialized_lineage_event_count": len(materialized_zero_events),
        "materialized_economic_event_count": (
            len(materialized_zero_events) - materialized_zero_amount_count
        ),
        "materialized_zero_amount_event_count_excluded": (
            materialized_zero_amount_count
        ),
        "evidence_artifact_sha256": [QUERY_EVIDENCE_HASH],
        "implementation_addresses_proven": implementation_addresses,
    }
    zero_audit["audit_hash"] = canonical_hash(zero_audit)
    if treasury_addresses:
        treasury_audit = {
            "required": True,
            "complete": True,
            "derivation": "issue_redeem_owner_balance",
            "address_history": [
                {
                    "address": TREASURY,
                    "valid_from_block": 0,
                    "valid_to_block_exclusive": None,
                    "activation_evidence_sha256": QUERY_EVIDENCE_HASH,
                }
            ],
            "included_event_count": treasury_event_count,
            "lineage_event_count": treasury_lineage_count,
            "economic_event_count": treasury_event_count,
            "zero_amount_event_count_excluded": treasury_zero_count,
            "unmatched_event_count": 0,
            "evidence_artifact_sha256": [QUERY_EVIDENCE_HASH],
            "owner_history_round_trip_absence_proven": True,
            "owner_history_proof_kind": (
                "complete_confirmed_ownership_event_history"
                if spec.chain == "tron"
                else "initial_eoa_complete_block_scan_plus_verified_multisig_complete_state_enumeration"
            ),
            "owner_history_proof_sha256": QUERY_EVIDENCE_HASH,
        }
    else:
        treasury_audit = {
            "required": False,
            "complete": True,
            "address_history": [],
            "included_event_count": 0,
            "lineage_event_count": 0,
            "economic_event_count": 0,
            "zero_amount_event_count_excluded": 0,
            "unmatched_event_count": 0,
            "evidence_artifact_sha256": [QUERY_EVIDENCE_HASH],
        }
    treasury_audit["audit_hash"] = canonical_hash(treasury_audit)
    zero_amount_event_count = sum(
        str(event.get("amount", event.get("raw_amount", ""))) == "0"
        for event in events
    )
    economic_event_count = len(events) - zero_amount_event_count
    finality = {
        "policy": (
            "ethereum_event_block_plus_64"
            if spec.chain == "ethereum"
            else "tron_event_producer_plus_18_distinct_srs"
        ),
        "exact_availability": True,
        "canonical_recheck_complete": True,
        "reorg_detected_count": 0,
        "event_count": len(events),
        "lineage_event_count": len(events),
        "economic_event_count": economic_event_count,
        "zero_amount_event_count_excluded": zero_amount_event_count,
        "evidence_artifact_sha256": FINALITY_EVIDENCE_HASH,
        "policy_source_artifact_sha256": FINALITY_EVIDENCE_HASH,
    }
    if spec.chain == "ethereum":
        finality.update(
            {
                "confirmation_blocks": 64,
                "native_consensus_finality_claimed": False,
            }
        )
    else:
        finality.update(
            {
                "acknowledgement_count": 19,
                "subsequent_distinct_sr_count": 18,
            }
        )
    return {
        "schema_version": STABLECOIN_CHAIN_SOURCE_VERSION,
        "source_id": spec.source_id,
        "chain": spec.chain,
        "asset": spec.asset,
        "contract": spec.contract,
        "decimals": spec.decimals,
        "event_accounting": {
            "zero_amount_policy": (
                "retain_raw_and_finality_lineage_exclude_economic_flow_and_count"
            ),
            "lineage_event_count": len(events),
            "economic_event_count": economic_event_count,
            "zero_amount_event_count_excluded": zero_amount_event_count,
        },
        "coverage": {
            "query_start_at": "2017-01-01T00:00:00Z",
            "query_end_exclusive": "2026-07-01T00:00:00Z",
            "first_usable_at": first_usable,
            "complete": True,
            "gap_count": 0,
            "event_families_requested": list(spec.required_event_families),
            "event_families_complete": list(spec.required_event_families),
        },
        "semantics": {
            "verified": True,
            "evidence_hashes": [
                EVIDENCE_HASH,
                QUERY_EVIDENCE_HASH,
                FINALITY_EVIDENCE_HASH,
            ],
            "supports": supports,
            "implementation_history": implementation_history,
            "zero_transfer_overlap_audit": zero_audit,
            "treasury_transfer_audit": treasury_audit,
        },
        "finality": finality,
        "collection": {
            "raw_event_count": len(events),
            "evidence_artifacts": [
                {
                    "role": "verified_contract_source",
                    "path": "verified-source.json",
                    "size_bytes": 1,
                    "sha256": EVIDENCE_HASH,
                },
                {
                    "role": "chain_event_query_audit",
                    "path": "chain-query.json",
                    "size_bytes": 1,
                    "sha256": QUERY_EVIDENCE_HASH,
                },
                {
                    "role": "exact_confirmation_evidence",
                    "path": "confirmation.ndjson.gz",
                    "size_bytes": 1,
                    "sha256": FINALITY_EVIDENCE_HASH,
                },
            ]
        },
        "events": events,
    }


def _baseline_rows(*, varying: bool = False) -> list[dict[str, Any]]:
    cursor = datetime(2022, 5, 25, tzinfo=UTC)
    end = datetime(2026, 6, 1, tzinfo=UTC)
    supply = 100_000_000_000.0
    rows: list[dict[str, Any]] = []
    index = 0
    while cursor <= end:
        rows.append(
            {
                "date": int(cursor.timestamp()),
                "totalCirculatingUSD": {"peggedUSD": supply},
            }
        )
        increment = 1_000_000.0 + index * 10_000.0 if varying else 1_000_000.0
        supply += increment
        cursor += timedelta(days=7)
        index += 1
    return rows


def _valid_fixture() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    event_at = datetime(2022, 6, 6, 12, tzinfo=UTC)
    eth_issue = _event(
        transaction_hash="0xethmigration",
        event_index=1,
        event_name="Issue",
        amount=10_000_000,
        event_at=event_at,
    )
    eth_treasury = _event(
        transaction_hash="0xtreasury",
        event_index=2,
        event_name="Transfer",
        amount=2_000_000,
        event_at=event_at + timedelta(days=2),
        from_address=TREASURY,
        to_address="0x1111111111111111111111111111111111111111",
    )
    tron_redeem = _event(
        transaction_hash="tronmigration",
        event_index=3,
        event_name="Redeem",
        amount=10_000_000,
        event_at=event_at + timedelta(hours=1),
    )
    usdc_mint = _event(
        transaction_hash="0xusdc",
        event_index=4,
        event_name="Mint",
        amount=3_000_000,
        event_at=event_at + timedelta(days=8),
    )
    usdc_transfer = _event(
        transaction_hash="0xusdc",
        event_index=5,
        event_name="Transfer",
        amount=3_000_000,
        event_at=event_at + timedelta(days=8),
        from_address="0x0000000000000000000000000000000000000000",
        to_address="0x2222222222222222222222222222222222222222",
    )
    sources = [
        _source_payload("usdt_ethereum", [eth_issue, eth_treasury, copy.deepcopy(eth_issue)]),
        _source_payload("usdt_tron", [tron_redeem]),
        _source_payload("usdc_ethereum", [usdc_mint, usdc_transfer]),
    ]
    return sources, _baseline_rows()


class StablecoinImpulseG0Tests(unittest.TestCase):
    def test_public_json_client_decodes_gzip_response(self) -> None:
        opener = _GzipOpener({"result": [1, 2, 3]})
        client = _JsonClient(timeout_seconds=1, attempts=1)
        client.opener = opener  # type: ignore[assignment]
        result = client.request(
            "https://rpc.example",
            method="POST",
            payload={"request": 1},
        )
        self.assertEqual(result, {"result": [1, 2, 3]})
        self.assertEqual(opener.accept_encoding, "gzip")

    def setUp(self) -> None:
        self.preregistration = build_stablecoin_impulse_preregistration(
            "2026-07-25T00:00:00Z"
        )

    def test_preregistration_is_hash_bound_and_result_free(self) -> None:
        validate_stablecoin_impulse_preregistration(self.preregistration)
        self.assertFalse(self.preregistration["meta"]["chain_event_results_read"])
        self.assertEqual(
            self.preregistration["decision_contract"]["trial_number_within_family"],
            0,
        )
        tampered = copy.deepcopy(self.preregistration)
        tampered["audit_protocol"]["aggregate_supply_comparison"][
            "expected_anchor_count"
        ] = 208
        with self.assertRaisesRegex(ValueError, "protocol_hash_mismatch"):
            validate_stablecoin_impulse_preregistration(tampered)

    def test_frozen_anchor_phase_and_cutoffs(self) -> None:
        common = frozen_weekly_anchors(
            datetime(2021, 4, 1, tzinfo=UTC),
            datetime(2021, 4, 20, tzinfo=UTC),
            end_inclusive=False,
        )
        self.assertEqual(_iso(common[0]), "2021-04-07T00:00:00Z")
        comparison = frozen_weekly_anchors(
            datetime(2022, 6, 1, tzinfo=UTC),
            datetime(2026, 6, 1, tzinfo=UTC),
            end_inclusive=True,
        )
        self.assertEqual(len(comparison), 209)
        cutoffs = frozen_weekly_anchors(
            datetime(2022, 6, 1, tzinfo=UTC),
            datetime(2026, 7, 1, tzinfo=UTC),
            end_inclusive=False,
        )
        self.assertEqual(_iso(cutoffs[-1]), "2026-06-24T00:00:00Z")

    def test_classification_and_all_three_dedup_layers(self) -> None:
        sources, baseline = _valid_fixture()
        report, weekly = build_stablecoin_impulse_g0_report(
            sources,
            baseline,
            self.preregistration,
            observed_at="2026-07-25T01:00:00Z",
        )
        self.assertEqual(report["verdict"], "pass_to_market_state_design")
        self.assertEqual(report["events"]["raw_identity_duplicate_count"], 1)
        self.assertEqual(report["events"]["transaction_semantic_duplicate_count"], 1)
        self.assertEqual(report["events"]["economic_cluster_count"], 1)
        self.assertEqual(report["events"]["economic_cluster_event_count"], 2)
        self.assertEqual(report["events"]["classification_counts"]["unknown"], 0)
        self.assertEqual(report["events"]["classification_counts"]["treasury_transfer"], 1)
        self.assertEqual(report["events"]["classification_coverage"], 1.0)
        self.assertEqual(
            report["aggregate_supply_comparison"]["frozen_anchor_count"], 209
        )
        self.assertEqual(
            report["aggregate_supply_comparison"]["comparable_anchor_count"], 209
        )
        self.assertGreater(len(weekly), 209)
        self.assertFalse(any(report["kill_tests"].values()))

    def test_zero_amount_transfers_remain_lineage_but_not_economic_events(self) -> None:
        event_at = datetime(2022, 6, 6, 12, tzinfo=UTC)
        native_issue = _event(
            transaction_hash="tron-positive-pair",
            event_index=40,
            event_name="Issue",
            amount=5_000_000,
            event_at=event_at,
        )
        positive_zero_transfer = _event(
            transaction_hash="tron-positive-pair",
            event_index=41,
            event_name="Transfer",
            amount=5_000_000,
            event_at=event_at,
            from_address=TRON_ZERO_ADDRESS,
            to_address=TREASURY,
        )
        zero_supply_transfer = _event(
            transaction_hash="tron-zero-lineage",
            event_index=42,
            event_name="Transfer",
            amount=0,
            event_at=event_at,
            from_address=TRON_ZERO_ADDRESS,
            to_address=TREASURY,
        )
        zero_treasury_transfer = _event(
            transaction_hash="tron-zero-treasury",
            event_index=43,
            event_name="Transfer",
            amount=0,
            event_at=event_at,
            from_address=TREASURY,
            to_address="0x1111111111111111111111111111111111111111",
        )
        sources = [
            _source_payload("usdt_ethereum", []),
            _source_payload(
                "usdt_tron",
                [
                    native_issue,
                    positive_zero_transfer,
                    zero_supply_transfer,
                    zero_treasury_transfer,
                ],
            ),
            _source_payload("usdc_ethereum", []),
        ]

        report, _ = build_stablecoin_impulse_g0_report(
            sources,
            _baseline_rows(),
            self.preregistration,
            observed_at="2026-07-25T01:00:00Z",
        )

        tron = next(row for row in report["sources"] if row["source_id"] == "usdt_tron")
        self.assertTrue(tron["valid"])
        self.assertEqual(tron["lineage_event_count"], 4)
        self.assertEqual(tron["economic_event_count"], 2)
        self.assertEqual(tron["zero_amount_event_count_excluded"], 2)
        self.assertEqual(report["events"]["lineage_before_economic_filter_count"], 4)
        self.assertEqual(report["events"]["zero_amount_lineage_excluded_count"], 2)
        self.assertEqual(report["events"]["normalized_before_dedup_count"], 2)
        self.assertEqual(report["events"]["transaction_semantic_duplicate_count"], 1)
        self.assertEqual(report["events"]["classification_counts"]["treasury_transfer"], 0)
        self.assertEqual(report["events"]["classification_coverage"], 1.0)
        self.assertFalse(any(report["kill_tests"].values()))

    def test_tron_zero_address_transfer_is_semantically_deduplicated(self) -> None:
        event_at = datetime(2022, 6, 6, 12, tzinfo=UTC)
        native_issue = _event(
            transaction_hash="tron-zero-pair",
            event_index=30,
            event_name="Issue",
            amount=5_000_000,
            event_at=event_at,
        )
        zero_transfer = _event(
            transaction_hash="tron-zero-pair",
            event_index=31,
            event_name="Transfer",
            amount=5_000_000,
            event_at=event_at,
            from_address=TRON_ZERO_ADDRESS,
            to_address="TBPxhVAsuzoFnKyXtc1o2UySEydPHgATto",
        )
        sources = [
            _source_payload("usdt_ethereum", []),
            _source_payload("usdt_tron", [native_issue, zero_transfer]),
            _source_payload("usdc_ethereum", []),
        ]

        report, _ = build_stablecoin_impulse_g0_report(
            sources,
            _baseline_rows(),
            self.preregistration,
            observed_at="2026-07-25T01:00:00Z",
        )

        self.assertEqual(
            report["events"]["transaction_semantic_duplicate_count"], 1
        )
        self.assertEqual(report["events"]["classification_counts"]["mint"], 1)
        self.assertEqual(
            report["events"]["classification_counts"]["treasury_transfer"], 0
        )
        self.assertEqual(report["events"]["classification_counts"]["unknown"], 0)

    def test_weekly_cutoff_uses_exact_available_at(self) -> None:
        sources, baseline = _valid_fixture()
        report, weekly = build_stablecoin_impulse_g0_report(
            sources,
            baseline,
            self.preregistration,
            observed_at="2026-07-25T01:00:00Z",
        )
        del report
        indexed = {row["anchor_utc"]: row for row in weekly}
        self.assertEqual(
            indexed["2022-06-15T00:00:00Z"]["event_counts"][
                "treasury_transfer"
            ],
            1,
        )
        self.assertEqual(
            indexed["2022-06-08T00:00:00Z"]["event_counts"][
                "treasury_transfer"
            ],
            0,
        )

    def test_unknown_event_and_incomplete_semantics_fail_closed(self) -> None:
        sources, baseline = _valid_fixture()
        sources[0]["semantics"]["treasury_transfer_audit"]["complete"] = False
        sources[2]["events"].append(
            _event(
                transaction_hash="0xunknown",
                event_index=20,
                event_name="Paused",
                amount=1,
                event_at=datetime(2023, 1, 1, tzinfo=UTC),
            )
        )
        report, _ = build_stablecoin_impulse_g0_report(
            sources,
            baseline,
            self.preregistration,
            observed_at="2026-07-25T01:00:00Z",
        )
        self.assertEqual(report["verdict"], "block_capacity")
        self.assertTrue(report["kill_tests"]["classification_coverage_below_one"])
        self.assertTrue(
            report["kill_tests"]["event_family_or_treasury_semantics_incomplete"]
        )

    def test_exact_aggregate_repackaging_is_rejected(self) -> None:
        baseline = _baseline_rows(varying=True)
        anchors = frozen_weekly_anchors(
            datetime(2022, 6, 1, tzinfo=UTC),
            datetime(2026, 6, 1, tzinfo=UTC),
            end_inclusive=True,
        )
        events = []
        for index, anchor in enumerate(anchors):
            events.append(
                _event(
                    transaction_hash=f"0xrepackage{index:04d}",
                    event_index=index,
                    event_name="Mint",
                    amount=1_000_000 + index * 10_000,
                    event_at=anchor - timedelta(days=1),
                )
            )
        sources = [
            _source_payload("usdt_ethereum", []),
            _source_payload("usdt_tron", []),
            _source_payload("usdc_ethereum", events),
        ]
        report, _ = build_stablecoin_impulse_g0_report(
            sources,
            baseline,
            self.preregistration,
            observed_at="2026-07-25T01:00:00Z",
        )
        self.assertEqual(
            report["verdict"], "reject_as_aggregate_supply_repackaging"
        )
        self.assertTrue(
            report["aggregate_supply_comparison"]["equivalent_to_aggregate_supply"]
        )

    def test_report_contains_only_false_permission_guards_for_market_results(self) -> None:
        sources, baseline = _valid_fixture()
        report, _ = build_stablecoin_impulse_g0_report(
            sources,
            baseline,
            self.preregistration,
            observed_at="2026-07-25T01:00:00Z",
        )
        meta = report["meta"]
        for key in (
            "market_data_read",
            "strategy_results_read",
            "pnl_evaluated",
            "direction_produced",
            "candidate_pnl_ready",
            "promotion_evidence",
            "paper_or_live_allowed",
            "orders_authorized",
        ):
            self.assertIs(meta[key], False)
        self.assertEqual(meta["formal_strategy_trial_count_before"], 148)
        self.assertEqual(meta["formal_strategy_trial_count_after"], 148)

    def test_provider_log_timestamp_avoids_full_block_download(self) -> None:
        class NoHeaderRpc:
            def batch(self, requests: list[object]) -> list[object]:
                raise AssertionError(f"unexpected block-header request: {requests}")

        contexts = _ethereum_block_context(
            NoHeaderRpc(),  # type: ignore[arg-type]
            [
                {
                    "blockNumber": "0x64",
                    "blockHash": "0xabc",
                    "blockTimestamp": "0x3e8",
                }
            ],
        )
        self.assertEqual(contexts[100]["timestamp"], 1_000)
        self.assertEqual(
            contexts[100]["timestamp_source"], "eth_getLogs.blockTimestamp"
        )
        self.assertFalse(contexts[100]["canonical_rechecked"])

    def test_missing_log_timestamp_fetches_only_minimal_header_fields(self) -> None:
        class HeaderRpc:
            def batch(self, requests: list[object]) -> list[object]:
                self.requests = requests
                return [
                    {
                        "hash": "0xabc",
                        "timestamp": "0x3e8",
                        "transactions": ["must-not-be-retained"],
                    }
                ]

        rpc = HeaderRpc()
        contexts = _ethereum_block_context(  # type: ignore[arg-type]
            rpc,
            [{"blockNumber": "0x64", "blockHash": "0xabc"}],
        )
        self.assertEqual(len(rpc.requests), 1)
        self.assertEqual(
            contexts[100],
            {
                "timestamp": 1_000,
                "canonical_hash": "0xabc",
                "canonical_rechecked": True,
                "timestamp_source": "eth_getBlockByNumber",
            },
        )

    def test_gzip_sidecar_is_hash_count_and_path_bound(self) -> None:
        event = _event(
            transaction_hash="0xsidecar",
            event_index=1,
            event_name="Mint",
            amount=1_000_000,
            event_at=datetime(2022, 6, 1, tzinfo=UTC),
        )
        line = (
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode("ascii")
            + b"\n"
        )
        raw_line = b'{"provider":"fixture"}\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event_path = root / "events.ndjson.gz"
            raw_path = root / "raw.ndjson.gz"
            evidence_path = root / "verified-source.json"
            evidence_path.write_bytes(b'{"verified":true}\n')
            for path, content in ((event_path, line), (raw_path, raw_line)):
                with path.open("xb") as compressed:
                    with gzip.GzipFile(
                        filename="",
                        mode="wb",
                        fileobj=compressed,
                        mtime=0,
                    ) as handle:
                        handle.write(content)

            def reference(path: Path, content: bytes) -> dict[str, Any]:
                return {
                    "path": path.name,
                    "record_count": 1,
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "uncompressed_sha256": hashlib.sha256(content).hexdigest(),
                }

            payload = {
                "source_id": "usdc_ethereum",
                "collection": {
                    "normalized_event_artifact": reference(event_path, line),
                    "raw_event_artifact": reference(raw_path, raw_line),
                    "evidence_artifacts": [
                        {
                            "role": "verified_contract_source",
                            "path": evidence_path.name,
                            "size_bytes": evidence_path.stat().st_size,
                            "sha256": hashlib.sha256(
                                evidence_path.read_bytes()
                            ).hexdigest(),
                        }
                    ],
                },
            }
            hydrated, inventory = _hydrate_source_events(
                root / "usdc_ethereum.json",
                payload,
            )
            self.assertEqual(list(hydrated["events"]), [event])
            self.assertEqual(
                [row["role"] for row in inventory],
                [
                    "normalized_chain_events",
                    "raw_provider_events",
                    "source_evidence",
                ],
            )

            tampered = copy.deepcopy(payload)
            tampered["collection"]["normalized_event_artifact"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "artifact_hash_mismatch"):
                _hydrate_source_events(root / "usdc_ethereum.json", tampered)

            tampered_evidence = copy.deepcopy(payload)
            tampered_evidence["collection"]["evidence_artifacts"][0][
                "sha256"
            ] = "0" * 64
            with self.assertRaisesRegex(ValueError, "artifact_hash_mismatch"):
                _hydrate_source_events(
                    root / "usdc_ethereum.json", tampered_evidence
                )

    def test_native_only_collector_cannot_claim_remediated_schema(self) -> None:
        self.assertEqual(
            LEGACY_STABLECOIN_CHAIN_SOURCE_VERSION,
            "stablecoin_chain_event_source_v0.1",
        )
        self.assertNotEqual(
            LEGACY_STABLECOIN_CHAIN_SOURCE_VERSION,
            STABLECOIN_CHAIN_SOURCE_VERSION,
        )


if __name__ == "__main__":
    unittest.main()
