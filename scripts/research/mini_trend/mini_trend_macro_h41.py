#!/usr/bin/env python3
"""Audit or build point-in-time Federal Reserve H.4.1 total-assets history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.macro_h41 import H41DatasetConfig  # noqa: E402
from qount.mini_trend.macro_h41 import build_h41_capacity_audit  # noqa: E402
from qount.mini_trend.macro_h41 import build_h41_dataset  # noqa: E402
from qount.mini_trend.macro_h41 import write_h41_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("capacity", "dataset"), required=True)
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--start-release-date", default="2021-01-07")
    parser.add_argument("--end-release-date", default="2026-07-16")
    parser.add_argument("--output-path", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.mode == "capacity":
        payload = build_h41_capacity_audit(args.cache_root)
    else:
        payload = build_h41_dataset(
            args.cache_root,
            H41DatasetConfig(
                start_release_date=args.start_release_date,
                end_release_date=args.end_release_date,
            ),
        )
    artifact = write_h41_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={diagnostics['verdict']}")
    if args.mode == "capacity":
        print(f"selected_candidate_id={diagnostics['selected_candidate_id']}")
        for row in artifact["probes"]:
            print(
                f"probe={row['release_date']} format={row['format']} "
                f"layout={row['source_layout']} "
                f"observation={row['observation_date']} "
                f"total_assets={row['total_assets_usd_millions']}"
            )
    else:
        print(f"release_count={diagnostics['parsed_release_count']}")
        print(f"coverage={diagnostics['release_coverage']:.8f}")
        print(f"feature_rows={diagnostics['feature_rows']}")
        print(f"source_bytes={diagnostics['source_bytes']}")
        print(f"data_hash={artifact['data_hash']}")
    return 0 if not diagnostics["verdict"].startswith("block_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
