#!/usr/bin/env python3
"""Run the hash-bound MiniTrend UM dispatcher; defaults to order-free dry mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.pilot_dispatcher import (  # noqa: E402
    build_pilot_dispatch_plan,
    fetch_pilot_dispatch_snapshot,
    run_pilot_dispatch,
    verify_dispatch_journal,
    write_pilot_dispatch_artifact,
)
from qount.settings import Settings  # noqa: E402


def _object(path: str | Path) -> tuple[dict, str]:
    target = Path(path).expanduser()
    raw = target.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {target}")
    return payload, hashlib.sha256(raw).hexdigest()


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dry", "live"), default="dry")
    parser.add_argument("--preflight-path", required=True)
    parser.add_argument("--projection-path", required=True)
    parser.add_argument("--readiness-path", required=True)
    parser.add_argument("--exchange-rules-path", required=True)
    parser.add_argument("--journal-path", required=True)
    parser.add_argument("--arm-path")
    parser.add_argument("--arm-token-env", default="QOUNT_MINI_TREND_ARM_TOKEN")
    parser.add_argument("--halt-path")
    parser.add_argument("--output-path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    preflight, preflight_hash = _object(args.preflight_path)
    projection, projection_hash = _object(args.projection_path)
    readiness, readiness_hash = _object(args.readiness_path)
    rules, rules_hash = _object(args.exchange_rules_path)
    arm = None
    arm_hash = None
    if args.arm_path:
        arm, arm_hash = _object(args.arm_path)

    settings = Settings.from_env()
    snapshot = fetch_pilot_dispatch_snapshot(settings)
    journal_summary = verify_dispatch_journal(args.journal_path)
    source_hashes = {
        "preflight": preflight_hash,
        "projection": projection_hash,
        "readiness": readiness_hash,
        "exchange_rules": rules_hash,
    }
    if arm_hash:
        source_hashes["arm"] = arm_hash
    plan = build_pilot_dispatch_plan(
        preflight,
        projection,
        readiness,
        rules,
        snapshot,
        mode=args.mode,
        source_hashes=source_hashes,
        arm=arm,
        arm_token=os.getenv(args.arm_token_env),
        live_switch_enabled=_enabled("QOUNT_MINI_TREND_LIVE_ENABLE"),
        live_confirmation=os.getenv("QOUNT_MINI_TREND_LIVE_CONFIRMATION"),
        journal_summary=journal_summary,
    )
    dispatch = run_pilot_dispatch(
        settings,
        plan,
        args.journal_path,
        halt_path=args.halt_path,
    )
    payload = dict(plan)
    payload["account_snapshot"] = snapshot
    payload["dispatch_result"] = dispatch
    payload["journal"] = verify_dispatch_journal(args.journal_path)
    artifact = write_pilot_dispatch_artifact(
        settings, payload, explicit_path=args.output_path
    )
    print(f"artifact={artifact['artifact_path']}")
    print(f"verdict={artifact['diagnostics']['verdict']}")
    print(f"dispatch_status={artifact['dispatch_result']['status']}")
    print(f"market_orders={len(artifact['market_orders'])}")
    print(f"stop_orders={len(artifact['stop_orders'])}")
    print(f"exchange_mutation_attempted={artifact['dispatch_result']['exchange_mutation_attempted']}")
    print(f"live_orders_allowed={artifact['meta']['live_orders_allowed']}")
    return 0 if args.mode == "dry" or dispatch["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
