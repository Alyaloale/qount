#!/usr/bin/env python3
"""Build an offline Equity Mapping G0 contract artifact without PnL or orders."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.equity_mapping import build_equity_mapping_g0_dataset  # noqa: E402
from qount.mini_trend.equity_mapping import write_equity_mapping_g0_artifact  # noqa: E402
from qount.mini_trend.equity_mapping_collection import (  # noqa: E402
    load_verified_equity_mapping_collection_manifest,
)
from qount.settings import Settings  # noqa: E402


MAX_INPUT_BYTES = 2 * 1024 * 1024


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--raw-manifest", action="append", default=[])
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    input_path = Path(args.input).expanduser().resolve()
    raw = input_path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("equity_mapping_g0_input_too_large")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("equity_mapping_g0_input_not_object")
    raw_manifests = [
        load_verified_equity_mapping_collection_manifest(Path(path))
        for path in args.raw_manifest
    ]
    report = build_equity_mapping_g0_dataset(
        payload,
        verified_raw_collection_manifests=raw_manifests,
    )
    report["input_manifest"] = {
        "path": str(input_path),
        "byte_count": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    artifact = write_equity_mapping_g0_artifact(
        Settings.from_env(), report, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={report['verdict']}")
    print(f"dataset_role={report['input']['dataset_role']}")
    print(f"event_count={report['event_count']}")
    print(
        "independent_cash_trading_dates="
        f"{report['independence']['independent_cash_trading_dates']}"
    )
    print("pnl_evaluated=False")
    print("orders_allowed=False")
    print("paper_or_live_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
