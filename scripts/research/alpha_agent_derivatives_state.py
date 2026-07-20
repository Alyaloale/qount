#!/usr/bin/env python3
"""Fetch Binance USD-M derivatives-state research inputs for Alpha Agents.

This is research-only. It uses public Binance market-data endpoints for recent
open-interest and taker buy/sell ratio data, writes an artifact, and never reads
private Binance keys or places orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.derivatives_state import DerivativesStateConfig  # noqa: E402
from qount.alpha_agents.derivatives_state import build_derivatives_state_dataset  # noqa: E402
from qount.alpha_agents.derivatives_state import write_derivatives_state_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--period", default="5m", choices=("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"))
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--no-current-open-interest", action="store_true")
    parser.add_argument("--cache-dir", default="state/alpha_agents/binance_derivatives_state")
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = DerivativesStateConfig(
        symbols=tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip()),
        period=args.period,
        days=args.days,
        limit=args.limit,
        include_current_open_interest=not args.no_current_open_interest,
        cache_dir=args.cache_dir,
    )
    payload = build_derivatives_state_dataset(config)
    artifact = write_derivatives_state_artifact(Settings.from_env(), payload, explicit_path=args.output_path)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        diag = artifact["diagnostics"]
        print(f"artifact={artifact['artifact_path']}")
        print(f"open_interest_hist_count={diag['open_interest_hist_count']}")
        print(f"taker_long_short_count={diag['taker_long_short_count']}")
        print(f"current_open_interest_count={diag['current_open_interest_count']}")
        print(f"error_count={len(diag['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
