#!/usr/bin/env python3
"""Preregister or run the stablecoin marginal-flow no-PnL G0 audit."""

from __future__ import annotations

import argparse
import errno
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.mini_trend.stablecoin_impulse_g0 import (  # noqa: E402
    SOURCE_CAPACITY_ARTIFACT_SHA256,
    SOURCE_CAPACITY_CONTRACT_HASH,
    STABLECOIN_IMPULSE_G0_PROTOCOL,
    build_stablecoin_impulse_g0_report,
    build_stablecoin_impulse_preregistration,
    validate_stablecoin_impulse_preregistration,
)


DEFAULT_SOURCE_CAPACITY_PATH = (
    ROOT
    / "state"
    / "research_runs"
    / "20260724T174222-stablecoin-source-capacity"
    / "stablecoin_source_capacity.json"
)
DEFAULT_OUTPUT_ROOT = (
    ROOT / "state" / "research_governance" / "stablecoin_impulse_g0"
)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        + b"\n"
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EPERM}:
                raise
    finally:
        os.close(descriptor)


def _write_once(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    raw = _canonical_bytes(value)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)
    if path.read_bytes() != raw:
        raise RuntimeError(f"stablecoin_g0_readback_mismatch:{path}")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _artifact_path(source_path: Path, reference: Mapping[str, Any]) -> Path:
    relative = Path(str(reference.get("path", "")))
    if not relative.name or relative.is_absolute() or relative.parent != Path("."):
        raise ValueError("stablecoin_event_artifact_path_invalid")
    path = (source_path.parent / relative).resolve()
    if path.parent != source_path.parent.resolve():
        raise ValueError("stablecoin_event_artifact_path_escape")
    if not path.is_file():
        raise ValueError(f"stablecoin_event_artifact_missing:{relative.name}")
    if (
        path.stat().st_size != reference.get("size_bytes")
        or _file_sha256(path) != reference.get("sha256")
    ):
        raise ValueError(f"stablecoin_event_artifact_hash_mismatch:{relative.name}")
    return path


def _iter_gzip_ndjson(
    path: Path,
    reference: Mapping[str, Any],
):
    expected_count = int(reference.get("record_count", -1))
    expected_hash = str(reference.get("uncompressed_sha256", ""))
    digest = hashlib.sha256()
    count = 0
    with gzip.open(path, "rb") as handle:
        for line in handle:
            digest.update(line)
            row = json.loads(line)
            if not isinstance(row, Mapping):
                raise ValueError("stablecoin_event_artifact_row_not_object")
            count += 1
            yield row
    if count != expected_count or digest.hexdigest() != expected_hash:
        raise ValueError(f"stablecoin_event_artifact_content_mismatch:{path.name}")


def _evidence_artifact_inventory(
    source_path: Path,
    collection: Mapping[str, Any],
) -> list[dict[str, Any]]:
    references = collection.get("evidence_artifacts")
    if not isinstance(references, list) or not references:
        raise ValueError("stablecoin_source_evidence_artifacts_missing")
    inventory: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, reference in enumerate(references):
        if not isinstance(reference, Mapping):
            raise ValueError(f"stablecoin_source_evidence_reference_invalid:{index}")
        evidence_path = _artifact_path(source_path, reference)
        if evidence_path.name in seen_paths:
            raise ValueError(
                f"stablecoin_source_evidence_path_duplicate:{evidence_path.name}"
            )
        seen_paths.add(evidence_path.name)
        role = str(reference.get("role", "")).strip()
        if not role:
            raise ValueError(f"stablecoin_source_evidence_role_missing:{index}")
        inventory.append(
            {
                "role": "source_evidence",
                "evidence_role": role,
                "source_id": str(collection.get("source_id", "")),
                "path": str(evidence_path),
                "size_bytes": evidence_path.stat().st_size,
                "sha256": _file_sha256(evidence_path),
            }
        )
    return inventory


def _hydrate_source_events(
    source_path: Path,
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    hydrated = dict(payload)
    collection = payload.get("collection", {})
    if not isinstance(collection, Mapping):
        raise ValueError("stablecoin_source_collection_not_object")
    evidence_inventory = _evidence_artifact_inventory(source_path, collection)
    source_id = str(payload.get("source_id", ""))
    for row in evidence_inventory:
        row["source_id"] = source_id
    event_reference = collection.get("normalized_event_artifact")
    raw_reference = collection.get("raw_event_artifact")
    if event_reference is None and isinstance(payload.get("events"), list):
        return hydrated, evidence_inventory
    if not isinstance(event_reference, Mapping) or not isinstance(
        raw_reference, Mapping
    ):
        raise ValueError("stablecoin_source_event_artifact_reference_missing")
    event_path = _artifact_path(source_path, event_reference)
    raw_path = _artifact_path(source_path, raw_reference)
    hydrated["events"] = _iter_gzip_ndjson(event_path, event_reference)
    # Raw provider rows are evidence, not model inputs, but still require a full
    # decompression/count/content-hash pass before the normalized stream is read.
    for _ in _iter_gzip_ndjson(raw_path, raw_reference):
        pass
    inventory = [
        {
            "role": "normalized_chain_events",
            "source_id": source_id,
            "path": str(event_path),
            "size_bytes": event_path.stat().st_size,
            "sha256": _file_sha256(event_path),
            "record_count": event_reference.get("record_count"),
            "uncompressed_sha256": event_reference.get("uncompressed_sha256"),
        },
        {
            "role": "raw_provider_events",
            "source_id": source_id,
            "path": str(raw_path),
            "size_bytes": raw_path.stat().st_size,
            "sha256": _file_sha256(raw_path),
            "record_count": raw_reference.get("record_count"),
            "uncompressed_sha256": raw_reference.get("uncompressed_sha256"),
        },
    ]
    inventory.extend(evidence_inventory)
    return hydrated, inventory


def _validate_source_capacity(path: Path) -> Mapping[str, Any]:
    if _file_sha256(path) != SOURCE_CAPACITY_ARTIFACT_SHA256:
        raise ValueError("stablecoin_source_capacity_artifact_hash_mismatch")
    payload = _read_json(path)
    if not isinstance(payload, Mapping):
        raise ValueError("stablecoin_source_capacity_not_object")
    if payload.get("contract_hash") != SOURCE_CAPACITY_CONTRACT_HASH:
        raise ValueError("stablecoin_source_capacity_contract_hash_mismatch")
    if payload.get("verdict") != "pass_to_g0":
        raise ValueError("stablecoin_source_capacity_did_not_pass")
    return payload


def _member_refs(directory: Path) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        references.append(
            {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    return references


def _verify_bundle(bundle_directory: Path) -> dict[str, Any]:
    manifest_path = bundle_directory / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest_core = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if manifest.get("manifest_hash") != canonical_hash(manifest_core):
        raise RuntimeError("stablecoin_g0_manifest_hash_invalid")
    for member in manifest.get("member_files", []):
        path = bundle_directory / member["path"]
        if (
            not path.is_file()
            or path.stat().st_size != member["size_bytes"]
            or _file_sha256(path) != member["sha256"]
        ):
            raise RuntimeError(f"stablecoin_g0_member_hash_invalid:{path.name}")
        _read_json(path)
    return manifest


def _preregister(output_root: Path, source_capacity_path: Path) -> Path:
    _validate_source_capacity(source_capacity_path)
    protocol = STABLECOIN_IMPULSE_G0_PROTOCOL
    path = (
        output_root
        / "preregistrations"
        / protocol.protocol_hash
        / "preregistration.json"
    )
    if path.exists():
        existing = _read_json(path)
        validate_stablecoin_impulse_preregistration(existing)
        return path
    payload = build_stablecoin_impulse_preregistration(
        datetime.now(timezone.utc).isoformat()
    )
    _write_once(path, payload)
    validate_stablecoin_impulse_preregistration(_read_json(path))
    return path


def _run(args: argparse.Namespace) -> dict[str, Any]:
    source_capacity_path = args.source_capacity_path.expanduser().resolve()
    _validate_source_capacity(source_capacity_path)
    preregistration_path = args.preregistration_path.expanduser().resolve()
    preregistration = _read_json(preregistration_path)
    validate_stablecoin_impulse_preregistration(preregistration)

    source_paths = [path.expanduser().resolve() for path in args.source_input]
    if len(source_paths) != 3:
        raise ValueError("--run requires exactly three --source-input files")
    source_metadata = [_read_json(path) for path in source_paths]
    if not all(isinstance(payload, Mapping) for payload in source_metadata):
        raise ValueError("stablecoin source inputs must be JSON objects")
    source_payloads: list[dict[str, Any]] = []
    event_inventory: list[dict[str, Any]] = []
    for path, payload in zip(source_paths, source_metadata):
        hydrated, artifacts = _hydrate_source_events(path, payload)
        source_payloads.append(hydrated)
        event_inventory.extend(artifacts)
    aggregate_supply_path = args.aggregate_supply_path.expanduser().resolve()
    aggregate_supply_rows = _read_json(aggregate_supply_path)
    observed_at = datetime.now(timezone.utc).isoformat()
    report, weekly_rows = build_stablecoin_impulse_g0_report(
        source_payloads,
        aggregate_supply_rows,
        preregistration,
        observed_at=observed_at,
    )

    input_inventory = [
        {
            "role": "chain_event_source",
            "source_id": str(payload.get("source_id", "")),
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": _file_sha256(path),
        }
        for path, payload in zip(source_paths, source_metadata)
    ]
    input_inventory.extend(event_inventory)
    for manifest_path in sorted({path.parent / "manifest.json" for path in source_paths}):
        if manifest_path.is_file():
            input_inventory.append(
                {
                    "role": "chain_event_collection_manifest",
                    "path": str(manifest_path),
                    "size_bytes": manifest_path.stat().st_size,
                    "sha256": _file_sha256(manifest_path),
                }
            )
    input_inventory.extend(
        (
            {
                "role": "aggregate_supply_baseline",
                "path": str(aggregate_supply_path),
                "size_bytes": aggregate_supply_path.stat().st_size,
                "sha256": _file_sha256(aggregate_supply_path),
            },
            {
                "role": "source_capacity_gate",
                "path": str(source_capacity_path),
                "size_bytes": source_capacity_path.stat().st_size,
                "sha256": _file_sha256(source_capacity_path),
            },
            {
                "role": "preregistration",
                "path": str(preregistration_path),
                "size_bytes": preregistration_path.stat().st_size,
                "sha256": _file_sha256(preregistration_path),
            },
        )
    )
    code_paths = (
        Path("src/qount/mini_trend/stablecoin_impulse_g0.py"),
        Path("src/qount/legacy/l3/l3_information_edge.py"),
        Path("scripts/research/mini_trend/run_stablecoin_impulse_g0.py"),
    )
    code_source_hashes = {
        str(path): _file_sha256(ROOT / path) for path in code_paths
    }
    source_inventory_hash = canonical_hash({"inputs": input_inventory})
    code_hash = canonical_hash(code_source_hashes)
    result_hash = canonical_hash(report)
    weekly_hash = canonical_hash({"weekly_rows": weekly_rows})
    bundle_core = {
        "schema_version": 1,
        "artifact_type": "stablecoin_liquidity_impulse_g0_bundle",
        "observed_at": observed_at,
        "hypothesis_family": STABLECOIN_IMPULSE_G0_PROTOCOL.hypothesis_family,
        "family_trial_number": 0,
        "formal_strategy_trial_count_before": 148,
        "formal_strategy_trial_count_after": 148,
        "contract_hash": STABLECOIN_IMPULSE_G0_PROTOCOL.contract_hash,
        "protocol_hash": STABLECOIN_IMPULSE_G0_PROTOCOL.protocol_hash,
        "source_inventory_hash": source_inventory_hash,
        "code_hash": code_hash,
        "result_hash": result_hash,
        "weekly_hash": weekly_hash,
        "verdict": report["verdict"],
        "market_data_read": False,
        "strategy_results_read": False,
        "pnl_evaluated": False,
        "formal_strategy_trial_created": False,
        "promotion_evidence": False,
        "orders_authorized": False,
    }
    bundle_id = canonical_hash(bundle_core)
    bundle_directory = (
        args.output_root.expanduser().resolve() / "bundles" / bundle_id
    )
    bundle_directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    _write_once(bundle_directory / "preregistration.json", preregistration)
    _write_once(
        bundle_directory / "data_audit.json",
        {
            "data_role": "consumed_historical_discovery_pool",
            "source_inventory_hash": source_inventory_hash,
            "inputs": input_inventory,
            "code_source_hashes": code_source_hashes,
            "market_data_read": False,
            "strategy_results_read": False,
            "orders_authorized": False,
        },
    )
    _write_once(bundle_directory / "results.json", report)
    _write_once(bundle_directory / "weekly_features.json", weekly_rows)
    manifest_core = {
        **bundle_core,
        "bundle_id": bundle_id,
        "input_inventory": input_inventory,
        "code_source_hashes": code_source_hashes,
        "member_files": _member_refs(bundle_directory),
    }
    manifest = {
        **manifest_core,
        "manifest_hash": canonical_hash(manifest_core),
    }
    _write_once(bundle_directory / "manifest.json", manifest)
    verified_manifest = _verify_bundle(bundle_directory)
    return {
        "bundle_id": bundle_id,
        "bundle_path": str(bundle_directory),
        "manifest_hash": verified_manifest["manifest_hash"],
        "verdict": report["verdict"],
        "kill_tests": report["kill_tests"],
        "classification_coverage": report["events"]["classification_coverage"],
        "primary_complete_anchor_count": report["independent_samples"][
            "primary_complete_anchor_count"
        ],
        "aggregate_comparable_anchor_count": report[
            "aggregate_supply_comparison"
        ]["comparable_anchor_count"],
        "formal_strategy_trial_count": 148,
        "formal_strategy_trial_created": False,
        "market_data_read": False,
        "strategy_results_read": False,
        "orders_authorized": False,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preregister", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument(
        "--source-capacity-path",
        type=Path,
        default=DEFAULT_SOURCE_CAPACITY_PATH,
    )
    parser.add_argument("--preregistration-path", type=Path)
    parser.add_argument("--source-input", type=Path, action="append", default=[])
    parser.add_argument("--aggregate-supply-path", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.preregister:
        path = _preregister(
            args.output_root.expanduser().resolve(),
            args.source_capacity_path.expanduser().resolve(),
        )
        print(
            json.dumps(
                {
                    "preregistration_path": str(path),
                    "contract_hash": STABLECOIN_IMPULSE_G0_PROTOCOL.contract_hash,
                    "protocol_hash": STABLECOIN_IMPULSE_G0_PROTOCOL.protocol_hash,
                    "family_trial_number": 0,
                    "formal_strategy_trial_count": 148,
                    "chain_event_results_read": False,
                    "market_data_read": False,
                    "strategy_results_read": False,
                    "orders_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.preregistration_path is None:
        raise ValueError("--run requires --preregistration-path")
    if args.aggregate_supply_path is None:
        raise ValueError("--run requires --aggregate-supply-path")
    print(json.dumps(_run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
