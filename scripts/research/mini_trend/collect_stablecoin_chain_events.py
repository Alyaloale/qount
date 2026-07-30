#!/usr/bin/env python3
"""Collect frozen native stablecoin supply events from public chain endpoints."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.mini_trend.stablecoin_chain_events import (  # noqa: E402
    DEFAULT_ETHEREUM_RPC_URL,
    DEFAULT_TRONGRID_URL,
    collect_ethereum_native_supply_source,
    collect_tron_native_supply_source,
)


DEFAULT_OUTPUT_ROOT = ROOT / "state" / "research_data" / "stablecoin_chain_events"


_JSON_ENCODER = json.JSONEncoder(
    ensure_ascii=True,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
)


def _json_line(value: object) -> bytes:
    return _JSON_ENCODER.encode(value).encode("ascii") + b"\n"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_new(path: Path, value: object) -> None:
    digest = hashlib.sha256()
    with path.open("xb") as handle:
        for chunk in _JSON_ENCODER.iterencode(value):
            raw = chunk.encode("ascii")
            handle.write(raw)
            digest.update(raw)
        handle.write(b"\n")
        digest.update(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    if _file_sha256(path) != digest.hexdigest():
        raise RuntimeError(f"stablecoin_collection_readback_mismatch:{path}")


def _verify_gzip_ndjson(
    path: Path,
    *,
    expected_count: int,
    expected_uncompressed_sha256: str,
) -> None:
    digest = hashlib.sha256()
    count = 0
    with gzip.open(path, "rb") as handle:
        for line in handle:
            json.loads(line)
            digest.update(line)
            count += 1
    if count != expected_count or digest.hexdigest() != expected_uncompressed_sha256:
        raise RuntimeError(f"stablecoin_ndjson_readback_mismatch:{path}")


def _event_artifact_reference(
    path: Path,
    *,
    record_count: int,
    uncompressed_sha256: str,
) -> dict[str, Any]:
    return {
        "path": path.name,
        "format": "canonical_ndjson",
        "compression": "gzip_mtime_zero",
        "record_count": record_count,
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
        "uncompressed_sha256": uncompressed_sha256,
    }


def _externalize_events(
    output_directory: Path,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    source_id = str(payload["source_id"])
    normalized_path = output_directory / f"{source_id}.events.ndjson.gz"
    raw_path = output_directory / f"{source_id}.raw.ndjson.gz"
    normalized_digest = hashlib.sha256()
    raw_digest = hashlib.sha256()
    count = 0
    with normalized_path.open("xb") as normalized_file, raw_path.open("xb") as raw_file:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=normalized_file,
            mtime=0,
        ) as normalized_gzip, gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_file,
            mtime=0,
        ) as raw_gzip:
            for event in payload.get("events", []):
                normalized = dict(event)
                raw_event = normalized.pop("raw", None)
                if not isinstance(raw_event, dict):
                    raise RuntimeError(
                        f"stablecoin_raw_event_missing:{source_id}:{count}"
                    )
                normalized_line = _json_line(normalized)
                raw_line = _json_line(raw_event)
                normalized_gzip.write(normalized_line)
                raw_gzip.write(raw_line)
                normalized_digest.update(normalized_line)
                raw_digest.update(raw_line)
                count += 1
        normalized_file.flush()
        raw_file.flush()
        os.fsync(normalized_file.fileno())
        os.fsync(raw_file.fileno())

    normalized_hash = normalized_digest.hexdigest()
    raw_hash = raw_digest.hexdigest()
    _verify_gzip_ndjson(
        normalized_path,
        expected_count=count,
        expected_uncompressed_sha256=normalized_hash,
    )
    _verify_gzip_ndjson(
        raw_path,
        expected_count=count,
        expected_uncompressed_sha256=raw_hash,
    )
    normalized_reference = _event_artifact_reference(
        normalized_path,
        record_count=count,
        uncompressed_sha256=normalized_hash,
    )
    raw_reference = _event_artifact_reference(
        raw_path,
        record_count=count,
        uncompressed_sha256=raw_hash,
    )
    collection = payload["collection"]
    collection["embedded_raw_events"] = False
    collection["raw_event_count"] = count
    collection["normalized_event_artifact"] = normalized_reference
    collection["raw_event_artifact"] = raw_reference
    collection["raw_events_hash"] = raw_hash
    collection["raw_events_hash_contract"] = (
        "sha256_of_uncompressed_canonical_ndjson_bytes"
    )
    payload.pop("events", None)
    return [
        {"role": "normalized_chain_events", "source_id": source_id, **normalized_reference},
        {"role": "raw_provider_events", "source_id": source_id, **raw_reference},
    ]


def _source_reference(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": payload["source_id"],
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _file_sha256(path),
        "event_count": payload["collection"]["raw_event_count"],
        "first_usable_at": payload["coverage"]["first_usable_at"],
        "semantic_verification_complete": payload["semantics"]["verified"],
        "exact_availability": payload["finality"]["exact_availability"],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-at", default="2017-01-01T00:00:00Z")
    parser.add_argument("--end-exclusive", default="2026-07-01T00:00:00Z")
    parser.add_argument("--ethereum-rpc-url", default=DEFAULT_ETHEREUM_RPC_URL)
    parser.add_argument("--trongrid-url", default=DEFAULT_TRONGRID_URL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    observed_at = datetime.now(timezone.utc).isoformat()
    run_id = observed_at.replace(":", "").replace("-", "").split(".")[0]
    output_directory = args.output_root.expanduser().resolve() / run_id
    output_directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    collectors = (
        lambda: collect_ethereum_native_supply_source(
            "usdt_ethereum",
            start_at=args.start_at,
            end_exclusive=args.end_exclusive,
            rpc_url=args.ethereum_rpc_url,
        ),
        lambda: collect_tron_native_supply_source(
            start_at=args.start_at,
            end_exclusive=args.end_exclusive,
            base_url=args.trongrid_url,
        ),
        lambda: collect_ethereum_native_supply_source(
            "usdc_ethereum",
            start_at=args.start_at,
            end_exclusive=args.end_exclusive,
            rpc_url=args.ethereum_rpc_url,
        ),
    )
    references: list[dict[str, Any]] = []
    event_artifacts: list[dict[str, Any]] = []
    for collect_source in collectors:
        source = collect_source()
        event_artifacts.extend(_externalize_events(output_directory, source))
        path = output_directory / f"{source['source_id']}.json"
        _write_new(path, source)
        references.append(_source_reference(path, source))
    code_paths = (
        ROOT / "src" / "qount" / "mini_trend" / "stablecoin_chain_events.py",
        ROOT / "src" / "qount" / "mini_trend" / "stablecoin_impulse_g0.py",
        ROOT / "scripts" / "research" / "collect_stablecoin_chain_events.py",
    )
    manifest_core = {
        "schema_version": 1,
        "artifact_type": "stablecoin_native_supply_event_collection",
        "observed_at": observed_at,
        "query_start_at": args.start_at,
        "query_end_exclusive": args.end_exclusive,
        "source_files": references,
        "event_artifacts": event_artifacts,
        "code_source_hashes": {
            str(path.relative_to(ROOT)): _file_sha256(path) for path in code_paths
        },
        "scope": "native_supply_events_only",
        "known_incompleteness": [
            "zero_address_transfer_overlap_not_collected",
            "treasury_transfer_history_not_collected",
            "exact_historical_finality_available_at_not_reconstructed",
        ],
        "market_data_read": False,
        "strategy_results_read": False,
        "orders_authorized": False,
    }
    manifest = {
        **manifest_core,
        "manifest_hash": canonical_hash(manifest_core),
    }
    manifest_path = output_directory / "manifest.json"
    _write_new(manifest_path, manifest)
    print(
        json.dumps(
            {
                "output_directory": str(output_directory),
                "manifest_path": str(manifest_path),
                "manifest_hash": manifest["manifest_hash"],
                "sources": references,
                "market_data_read": False,
                "strategy_results_read": False,
                "orders_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
