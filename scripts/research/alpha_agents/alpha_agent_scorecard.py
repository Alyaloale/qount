#!/usr/bin/env python3
"""Evaluate a deterministic Alpha Agents promotion scorecard.

Input is a metrics JSON produced by research/backtest/model-training code. This
script does not call LLMs, fetch private exchange data, write paper/live state,
change VPS config, or place orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.promotion import evaluate_promotion_scorecard  # noqa: E402
from qount.alpha_agents.promotion import load_metrics  # noqa: E402
from qount.alpha_agents.promotion import write_promotion_scorecard_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics-path", required=True, help="Input metrics JSON.")
    parser.add_argument("--target", choices=("proposal", "paper", "live_pilot"), default="paper")
    parser.add_argument("--output-path", default=None, help="Optional scorecard artifact path.")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = Settings.from_env()
    metrics = load_metrics(args.metrics_path)
    payload = evaluate_promotion_scorecard(metrics, target=args.target)
    artifact = write_promotion_scorecard_artifact(settings, payload, explicit_path=args.output_path)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"verdict={artifact['verdict']}")
    return 0 if artifact["verdict"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
