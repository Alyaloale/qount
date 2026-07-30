#!/usr/bin/env python3
"""Build deterministic DSR/PBO/purged-CV validation for an Alpha feature experiment."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.validation import ValidationConfig  # noqa: E402
from qount.alpha_agents.validation import build_validation_from_feature_experiment  # noqa: E402
from qount.alpha_agents.validation import write_validation_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-experiment-path", required=True)
    parser.add_argument("--fold-count", type=int, default=5)
    parser.add_argument("--embargo-periods", type=int, default=1)
    parser.add_argument("--pbo-splits", type=int, default=10)
    parser.add_argument("--min-positive-fold-fraction", type=float, default=0.60)
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = ValidationConfig(
        fold_count=args.fold_count,
        embargo_periods=args.embargo_periods,
        pbo_splits=args.pbo_splits,
        min_positive_fold_fraction=args.min_positive_fold_fraction,
    )
    payload = build_validation_from_feature_experiment(args.feature_experiment_path, config)
    artifact = write_validation_artifact(Settings.from_env(), payload, explicit_path=args.output_path)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        validation = artifact["validation"]
        print(f"artifact={artifact['artifact_path']}")
        print(f"deflated_sharpe_ratio={validation['deflated_sharpe_ratio']:.6f}")
        print(f"pbo={validation['pbo']:.6f}")
        print(f"purged_cv_pass={str(validation['purged_cv_pass']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
