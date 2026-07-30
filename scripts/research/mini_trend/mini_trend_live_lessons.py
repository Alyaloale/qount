#!/usr/bin/env python3
"""Audit the retired X4 live records without touching exchange or VPS state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.mini_trend.live_lessons import build_live_lessons_report  # noqa: E402
from qount.mini_trend.live_lessons import write_live_lessons_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


DEFAULT_INPUT = REPO / "state/research_inputs/20260717-x4-live-audit"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-path")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payload = build_live_lessons_report(args.input_dir)
    artifact = write_live_lessons_artifact(
        Settings.from_env(), payload, explicit_path=args.output_path
    )
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={artifact['verdict']}")
        print(
            "strategy_return_pre_withdrawal_pct="
            f"{artifact['equity']['inception_to_pre_withdrawal_return_pct']}"
        )
        print(f"placed_orders={artifact['orders']['post_inception_placed_order_count']}")
        print(f"duplicate_orders={artifact['orders']['exact_duplicate_order_count']}")
        print(
            "fail_closed_unknown_capital="
            f"{artifact['operations']['fail_closed_unknown_capital_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
