#!/usr/bin/env python3
"""Audit structural-source capacity and freeze the single selected G0 protocol."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.source_capacity import SourceCapacityConfig  # noqa: E402
from qount.alpha_agents.source_capacity import build_options_dvol_preregistration  # noqa: E402
from qount.alpha_agents.source_capacity import build_source_capacity_matrix  # noqa: E402
from qount.alpha_agents.source_capacity import write_source_capacity_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("matrix", "preregister"), required=True)
    parser.add_argument("--capacity-path")
    parser.add_argument("--request-retries", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--output-path")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.mode == "matrix":
        payload = build_source_capacity_matrix(
            SourceCapacityConfig(
                request_retries=args.request_retries,
                request_timeout_seconds=args.request_timeout_seconds,
            )
        )
    else:
        if not args.capacity_path:
            raise ValueError("--capacity-path is required for preregister mode")
        payload = build_options_dvol_preregistration(args.capacity_path)
    artifact = write_source_capacity_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        if args.mode == "matrix":
            print(f"selected_candidate_id={diagnostics['selected_candidate_id']}")
            print(f"data_hash={artifact['meta']['data_hash']}")
        else:
            print(f"contract_hash={artifact['contract']['contract_hash']}")
            print(f"protocol_hash={artifact['protocol']['protocol_hash']}")
    return 0 if diagnostics["verdict"] != "capacity_incomplete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
