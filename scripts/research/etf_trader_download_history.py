"""Download credential-free public US ETF data for exploratory evaluation."""
from __future__ import annotations

import argparse
from pathlib import Path

from qount.research.etf_trader.historical_data import download_public_panel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--start", default="2009-01-01")
    parser.add_argument("--end", required=True)
    args = parser.parse_args()
    download_public_panel(args.out, args.start, args.end)


if __name__ == "__main__":
    main()
