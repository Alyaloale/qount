"""Thin adapter for no-order dated Q-DIV dividend diagnostics."""
import argparse
import json
from pathlib import Path

from qount.research.q_div_review import run_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_review(args.contract, args.out), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
