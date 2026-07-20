#!/usr/bin/env python3
"""Audit whether official Deribit history can reconstruct a point-in-time option skew."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.option_surface_capacity import OptionSurfaceCapacityConfig  # noqa: E402
from qount.alpha_agents.option_surface_capacity import build_option_surface_capacity  # noqa: E402
from qount.alpha_agents.option_surface_capacity import write_option_surface_capacity_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-retries", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output-path")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_option_surface_capacity(
        OptionSurfaceCapacityConfig(
            request_retries=args.request_retries,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    )
    artifact = write_option_surface_capacity_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    diagnostics = artifact["diagnostics"]
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={diagnostics['verdict']}")
        print(f"historical_chain_enumerable={diagnostics['historical_chain_enumerable']}")
        print(f"historical_trade_iv_available={diagnostics['historical_trade_iv_available']}")
        print(f"historical_price_charts_complete={diagnostics['historical_price_charts_complete']}")
        print(f"current_surface_available={diagnostics['current_surface_available']}")
        print(f"data_hash={artifact['meta']['data_hash']}")
    return 0 if diagnostics["verdict"] == "eligible_g0" else 2


if __name__ == "__main__":
    raise SystemExit(main())
