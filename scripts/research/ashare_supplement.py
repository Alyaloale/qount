#!/usr/bin/env python3
"""Thin adapter for single-connection research-only equity source supplements."""
import argparse
import json
from pathlib import Path
from qount.research.ashare_supplement import acquire

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sdk-root', type=Path, required=True)
    args = parser.parse_args()
    result = acquire(contract_path=args.contract, out=args.out, sdk_root=args.sdk_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'completed' else 1

if __name__ == '__main__':
    raise SystemExit(main())
