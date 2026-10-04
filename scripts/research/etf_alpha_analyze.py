#!/usr/bin/env python3
"""Analyze frozen ETF P3 predictions without training or changing the source run."""
import argparse
from pathlib import Path

from qount.research.etf_alpha.postmortem import analyze_run, probe_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-run", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--samples", default=400, type=int)
    parser.add_argument("--identity-probe", action="store_true", help="CPU intervention on frozen embedding inputs")
    args = parser.parse_args()
    if args.samples < 100:
        parser.error("at least 100 synchronous bootstrap samples required")
    if args.identity_probe:
        report = probe_identity(args.input_run, args.out)
        name = "identity-probe.json"
    else:
        report = analyze_run(args.input_run, args.out, samples=args.samples)
        name = "analysis.json"
    print(f"Analysis: {args.out / name}; source: {report['source_run']}")


if __name__ == "__main__":
    main()
