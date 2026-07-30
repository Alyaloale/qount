#!/usr/bin/env python3
"""Audit external Binance liquidation/L2 history without purchasing access."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.external_microstructure_capacity import ExternalMicrostructureCapacityConfig  # noqa: E402
from qount.alpha_agents.external_microstructure_capacity import build_external_microstructure_capacity  # noqa: E402
from qount.alpha_agents.external_microstructure_capacity import write_external_microstructure_capacity_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-retries", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--maximum-source-cache-gib", type=float, default=32.0)
    parser.add_argument("--output-path")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_external_microstructure_capacity(
        ExternalMicrostructureCapacityConfig(
            maximum_source_cache_budget_bytes=int(args.maximum_source_cache_gib * 1024**3),
            request_retries=args.request_retries,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    )
    artifact = write_external_microstructure_capacity_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        print(f"replayable_l2_sample_pass={diagnostics['replayable_l2_sample_pass']}")
        print(f"liquidation_sample_pass={diagnostics['liquidation_sample_pass']}")
        print(f"anonymous_full_horizon_access={diagnostics['anonymous_full_horizon_access']}")
        print(f"l2_raw_bytes_90d_estimate={diagnostics['l2_raw_bytes_90d_estimate']}")
        print(f"data_hash={artifact['meta']['data_hash']}")
    return 0 if diagnostics["verdict"] == "eligible_g0" else 2


if __name__ == "__main__":
    raise SystemExit(main())
