#!/usr/bin/env python3
"""Freeze and audit M1 inputs and fixed baselines; no model training or orders."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from qount.research.etf_alpha.prepare import prepare_m1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-root", "baseline-manifest", "dataset-out", "out", "repo"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--end", default="2026-10-01")
    parser.add_argument("--fixture-validation", type=Path)
    args = parser.parse_args()
    report = prepare_m1(args.data_root, args.baseline_manifest, args.dataset_out, args.out,
                        args.repo, args.end, fixture_validation=args.fixture_validation,
                        progress=lambda value: print(value, flush=True))
    print(json.dumps({k: report[k] for k in ("m1_status", "D_gate", "sessions", "feature_count", "fold_count",
          "baseline_count", "prediction_training_status", "research_only", "orders_authorized")}))


if __name__ == "__main__":
    main()
