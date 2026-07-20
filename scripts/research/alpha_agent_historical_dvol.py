#!/usr/bin/env python3
"""Build the preregistered public Deribit DVOL discovery dataset."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.historical_dvol import HistoricalDvolConfig  # noqa: E402
from qount.alpha_agents.historical_dvol import build_historical_dvol_dataset  # noqa: E402
from qount.alpha_agents.historical_dvol import write_historical_dvol_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2021-04-01")
    parser.add_argument("--end-date", default="2024-12-31")
    parser.add_argument("--cache-dir", default="state/alpha_agents/deribit_historical_dvol")
    parser.add_argument("--request-retries", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.999)
    parser.add_argument("--output-path")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_historical_dvol_dataset(
        HistoricalDvolConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            cache_dir=args.cache_dir,
            request_retries=args.request_retries,
            request_timeout_seconds=args.request_timeout_seconds,
            min_coverage_ratio=args.min_coverage_ratio,
        )
    )
    artifact = write_historical_dvol_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        print(f"aligned_complete_hour_count={diagnostics['aligned_complete_hour_count']}")
        print(f"aligned_coverage_ratio={diagnostics['aligned_coverage_ratio']:.6f}")
        print(f"request_count={diagnostics['request_count']}")
        print(f"response_bytes={diagnostics['response_bytes']}")
        print(f"data_hash={artifact['meta']['data_hash']}")
    return 0 if diagnostics["verdict"] == "pass_dataset" else 1


if __name__ == "__main__":
    raise SystemExit(main())
