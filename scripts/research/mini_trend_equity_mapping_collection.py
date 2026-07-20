#!/usr/bin/env python3
"""Plan or seal research-only Equity Mapping raw collection batches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.artifacts import write_research_json_artifact  # noqa: E402
from qount.mini_trend.equity_mapping_collection import (  # noqa: E402
    build_equity_mapping_collection_readiness,
)
from qount.mini_trend.equity_mapping_collection import (  # noqa: E402
    seal_equity_mapping_collection_batch,
)
from qount.settings import Settings  # noqa: E402


MAX_INPUT_BYTES = 2 * 1024 * 1024


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan-cash-date")
    modes.add_argument("--input")
    parser.add_argument("--raw-root")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = Settings.from_env()
    if args.plan_cash_date:
        readiness = build_equity_mapping_collection_readiness(args.plan_cash_date)
        artifact = write_research_json_artifact(
            settings,
            readiness,
            kind="equity-mapping-collection-readiness",
            path_key="artifact_path",
            default_filename="equity_mapping_collection_readiness.json",
            explicit_path=args.output_path,
        )
        print(f"artifact={artifact['artifact_path']}")
        print(f"cash_trading_date={readiness['cash_trading_date']}")
        print(f"reference_window_start={readiness['reference_window_start']}")
        print(f"decision_time={readiness['decision_time']}")
        print(f"status={readiness['status']}")
        print("market_evidence_present=False")
        print("orders_allowed=False")
        return 0

    if not args.raw_root:
        raise ValueError("equity_mapping_collection_raw_root_required")
    input_path = Path(args.input).expanduser().resolve()
    raw = input_path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("equity_mapping_collection_input_too_large")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("equity_mapping_collection_input_not_object")
    result = seal_equity_mapping_collection_batch(
        payload,
        input_base_dir=input_path.parent,
        raw_root=Path(args.raw_root),
    )
    print(f"bundle={result['bundle_path']}")
    print(f"batch_hash={result['batch_hash']}")
    print(f"manifest_sha256={result['manifest_sha256']}")
    print(f"capture_count={result['capture_count']}")
    print(f"asset_count={result['asset_count']}")
    print(f"idempotent_existing_bundle={result['idempotent_existing_bundle']}")
    print("future_return_evaluated=False")
    print("pnl_evaluated=False")
    print("orders_allowed=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
