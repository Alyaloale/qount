#!/usr/bin/env python3
"""Build a CTA-R AkShare ETF seed archive for research-only forward collection."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.legacy.line_a.cta_data import fetch_etf_online_akshare  # noqa: E402
from qount.legacy.line_a.cta_data import read_etf_adjusted_close_from_zip  # noqa: E402
from qount.research.cta_r_inputs import CTA_R_ETF_SYMBOLS  # noqa: E402
from qount.research.cta_r_inputs import write_seed_zip  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=dt.date.today().isoformat())
    parser.add_argument("--from-zip", type=Path, help="Convert an existing legacy archive without network access")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.from_zip:
        series = {
            symbol: sorted(
                read_etf_adjusted_close_from_zip(str(args.from_zip), f"{symbol}.SH" if symbol != "159915" else "159915.SZ").items()
            )
            for symbol in CTA_R_ETF_SYMBOLS
        }
    else:
        series = {
            symbol: sorted(fetch_etf_online_akshare(symbol, start_date=args.start).items())
            for symbol in CTA_R_ETF_SYMBOLS
        }
    write_seed_zip(args.out, series, start_date=args.start, end_date=args.end)
    print(f"seed_path={args.out.resolve()}")
    print(f"symbols={len(series)}")
    print("research_only=true")
    print("orders_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
