#!/usr/bin/env python3
"""Build a MiniTrend UM would-place order plan from audited, read-only inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.pilot_dry import build_pilot_dry_plan  # noqa: E402
from qount.mini_trend.pilot_dry import write_pilot_dry_plan_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def _object(path: str) -> dict:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-path", required=True)
    parser.add_argument("--desired-weights-path", required=True)
    parser.add_argument("--prices-path", required=True)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_pilot_dry_plan(
        _object(args.preflight_path),
        _object(args.desired_weights_path),
        _object(args.prices_path),
        _object(args.exchange_rules_path),
    )
    artifact = write_pilot_dry_plan_artifact(
        Settings.from_env(),
        payload,
        explicit_path=args.output_path,
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"would_place_orders={len(artifact['would_place_orders'])}")
    print(f"blocked_orders={len(artifact['blocked_orders'])}")
    print(f"live_orders_allowed={artifact['meta']['live_orders_allowed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
