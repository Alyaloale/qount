"""Run frozen A-share technical-leader/trend research backtest on WSL/E."""
import argparse
import json
from pathlib import Path
from qount.research.ashare_leader import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.contract, args.out), ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
