#!/usr/bin/env python3
"""Run authorized P3 v2 offline augmentation, ablations and outer diagnostics."""
from __future__ import annotations

import argparse
from pathlib import Path


def main():
    # Keep CUDA imports out of multiprocessing's main-module preparation.
    from qount.research.etf_alpha.expanded_run import run
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dataset-out", type=Path, required=True)
    parser.add_argument("--reuse-bootstrap", action="store_true", help="Verify and reuse a complete, source-bound CPU dataset")
    args = parser.parse_args()
    summary = run(args.contract.resolve(), args.out, args.dataset_out, repository=Path(__file__).resolve().parents[2],
                  reuse_bootstrap=args.reuse_bootstrap)
    return 0 if summary["status"] in {"complete", "budget_stopped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
