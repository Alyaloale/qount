#!/usr/bin/env python3
"""Fetch Binance public exchangeInfo filters for Alpha Agents.

This is research-only. It uses public Binance metadata, writes a reduced rules
artifact, and never reads private Binance keys or places orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.exchange_rules import build_exchange_rules_report  # noqa: E402
from qount.alpha_agents.exchange_rules import fetch_exchange_info  # noqa: E402
from qount.alpha_agents.exchange_rules import write_exchange_rules_artifact  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default="um", choices=("um", "spot"))
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT")
    parser.add_argument("--input-path", default=None, help="Optional raw exchangeInfo JSON path for offline use.")
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.input_path:
        exchange_info = json.loads(Path(args.input_path).expanduser().read_text(encoding="utf-8"))
    else:
        exchange_info = fetch_exchange_info(market=args.market)
    symbols = tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip())
    payload = build_exchange_rules_report(exchange_info, market=args.market, symbols=symbols)
    artifact = write_exchange_rules_artifact(Settings.from_env(), payload, explicit_path=args.output_path)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"returned_symbol_count={artifact['returned_symbol_count']}")
        print(f"trading_symbol_count={artifact['trading_symbol_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
