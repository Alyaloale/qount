#!/usr/bin/env python3
"""Write an immutable readable review after a frozen overnight run finishes."""
from __future__ import annotations

import argparse
from pathlib import Path

from qount.research.etf_alpha.reporting import write_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    review = write_review(args.input_run, args.out)
    print(f"Report: {args.out / 'REPORT.md'}; source status: {review['source_status']}")


if __name__ == "__main__":
    main()
