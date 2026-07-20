#!/usr/bin/env python3
"""Write order-free proof that MiniTrend ran as an independent systemd cycle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.pilot_runtime import (  # noqa: E402
    build_pilot_runtime_proof,
    write_pilot_runtime_proof_artifact,
)
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycle-path", required=True)
    parser.add_argument("--service-unit-path", required=True)
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_pilot_runtime_proof(
        cycle_path=args.cycle_path,
        service_unit_path=args.service_unit_path,
    )
    artifact = write_pilot_runtime_proof_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"blockers={len(artifact['diagnostics']['blockers'])}")
    print(f"live_orders_allowed={artifact['meta']['live_orders_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
