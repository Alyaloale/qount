#!/usr/bin/env python3
"""Run the authorized bounded Stage 1 workflow; artifacts stay on mounted E."""
from __future__ import annotations

import argparse
from pathlib import Path

from qount.research.etf_alpha.overnight import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary = run(args.contract.resolve(), args.out, repository=Path(__file__).resolve().parents[2])
    return 0 if summary["status"] in {"complete", "budget_stopped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
