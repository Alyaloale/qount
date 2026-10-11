#!/usr/bin/env python3
"""Thin CLI for immutable source-evidence forensics, without return labels."""
import argparse
import json
from pathlib import Path
from qount.research.ashare_evidence import audit_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--calendar-sources', required=True, type=Path)
    parser.add_argument('--public-examples', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_evidence(contract_path=args.contract, calendar_path=args.calendar_sources,
                                  examples_path=args.public_examples, out=args.out), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
