"""Build a dated no-order industry/company research queue on WSL/E."""
import argparse
import json
from pathlib import Path

from qount.research.ashare_sector_screen import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(run(contract_path=args.contract, out=args.out), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
