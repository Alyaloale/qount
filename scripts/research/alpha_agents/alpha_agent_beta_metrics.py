#!/usr/bin/env python3
"""Build deterministic beta-residual promotion metrics from aligned returns.

Input rows are period returns in percent points. JSON input can be either a list
of row objects or {"meta": {...}, "periods": [...]}. CSV and JSONL are also
accepted. This script does not call LLMs, fetch exchange data, write paper/live
state, change VPS config, or place orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.metrics import build_beta_residual_metrics  # noqa: E402
from qount.alpha_agents.metrics import load_return_rows  # noqa: E402
from qount.alpha_agents.metrics import write_beta_metrics_artifact  # noqa: E402
from qount.alpha_agents.tradeflow_replication import assert_replication_matches_anchor  # noqa: E402
from qount.alpha_agents.tradeflow_replication import load_tradeflow_replication_artifact  # noqa: E402
from qount.alpha_agents.tradeflow_replication import replication_meta  # noqa: E402
from qount.alpha_agents.validation import assert_validation_matches_feature  # noqa: E402
from qount.alpha_agents.validation import load_validation_artifact  # noqa: E402
from qount.alpha_agents.validation import validation_meta  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--returns-path", required=True, help="JSON/JSONL/CSV aligned return rows.")
    parser.add_argument("--source-label", default="alpha-beta-residual")
    parser.add_argument("--holdout-role", default="discovery", choices=("discovery", "validation_v1", "unknown"))
    parser.add_argument("--validation-path", default=None, help="Matching Alpha validation artifact.")
    parser.add_argument("--replication-path", default=None, help="Matching trade-flow replication report.")
    parser.add_argument("--output-path", default=None, help="Optional metrics artifact path.")
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = Settings.from_env()
    rows, meta, data_hash = load_return_rows(args.returns_path)
    if args.validation_path:
        validation = load_validation_artifact(args.validation_path)
        assert_validation_matches_feature(validation, args.returns_path)
        meta.update(validation_meta(validation))
    if args.replication_path:
        replication = load_tradeflow_replication_artifact(args.replication_path)
        assert_replication_matches_anchor(replication, args.returns_path)
        meta.update(replication_meta(replication))
    payload = build_beta_residual_metrics(
        rows,
        source_label=args.source_label,
        data_hash=data_hash,
        holdout_role=args.holdout_role,
        meta=meta,
    )
    artifact = write_beta_metrics_artifact(settings, payload, explicit_path=args.output_path)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"net_residual_return_pct={artifact['performance']['net_residual_return_pct']:.6f}")
        print(f"beta_to_btc={artifact['performance']['beta_to_btc']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
