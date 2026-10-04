"""Frozen exploratory P2 historical evaluation (no orders)."""
from __future__ import annotations

import argparse
from pathlib import Path

from qount.research.etf_trader.historical_backtest import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path, action="append")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new immutable artifact directory")
    parser.add_argument("--start", default="2015-01-01", help="first decision date; earlier data retained for warmup")
    parser.add_argument("--end", required=True)
    parser.add_argument("--initial-equity", type=float, default=1_000_000.0)
    args = parser.parse_args()
    evaluate(args.checkpoint, args.data_root, args.out, args.start, args.end, args.initial_equity)


if __name__ == "__main__":
    main()
