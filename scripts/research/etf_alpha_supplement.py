#!/usr/bin/env python3
"""Thin WSL entry point for immutable public ETF research source supplementation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from qount.research.etf_alpha.data_supplement import supplement_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--end", default="2026-10-01")
    parser.add_argument("--source-cache", type=Path, help="Optional immutable source vintage; original acquisition times are preserved")
    args = parser.parse_args()
    report = supplement_data(args.data_root, args.out, args.repo, args.end,
                             source_cache=args.source_cache,
                             progress=lambda value: print(json.dumps(value), flush=True))
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
