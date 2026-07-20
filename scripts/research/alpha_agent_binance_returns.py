#!/usr/bin/env python3
"""Build aligned Binance public-dump returns for Alpha Agents.

This is research-only. It downloads public data.binance.vision klines via the
existing qount.grid.data loader and writes an aligned returns artifact. It does
not use Binance private keys, write paper/live state, change VPS config, or
place orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.alpha_agents.binance_returns import BinanceReturnsConfig  # noqa: E402
from qount.alpha_agents.binance_returns import build_binance_returns_dataset  # noqa: E402
from qount.alpha_agents.binance_returns import write_binance_returns_artifact  # noqa: E402
from qount.alpha_agents.exchange_rules import fetch_exchange_info  # noqa: E402
from qount.alpha_agents.exchange_rules import load_symbol_rules  # noqa: E402
from qount.settings import Settings  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT")
    parser.add_argument("--strategy-symbol", default="ETHUSDT")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month", required=True)
    parser.add_argument("--market", default="um", choices=("spot", "um"))
    parser.add_argument("--strategy", default="sma_long_cash", choices=("sma_long_cash", "sma_long_short"))
    parser.add_argument("--fast-window", type=int, default=20)
    parser.add_argument("--slow-window", type=int, default=60)
    parser.add_argument("--fee-pct", type=float, default=0.0005)
    parser.add_argument("--slippage-pct", type=float, default=0.0002)
    parser.add_argument("--account-equity-usdt", type=float, default=400.0)
    parser.add_argument("--target-notional-fraction", type=float, default=1.0)
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument("--include-funding", action="store_true")
    parser.add_argument("--cache-dir", default="state/alpha_agents/binance_klines")
    parser.add_argument("--funding-cache-dir", default="state/alpha_agents/binance_funding")
    parser.add_argument("--exchange-rules-path", default=None, help="alpha_agent_exchange_rules.json or raw exchangeInfo JSON.")
    parser.add_argument("--fetch-exchange-info", action="store_true", help="Fetch public exchangeInfo for filter checks.")
    parser.add_argument("--output-path", default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = BinanceReturnsConfig(
        symbols=tuple(item.strip() for item in args.symbols.split(",") if item.strip()),
        strategy_symbol=args.strategy_symbol,
        interval=args.interval,
        start_month=args.start_month,
        end_month=args.end_month,
        market=args.market,
        strategy=args.strategy,
        fast_window=args.fast_window,
        slow_window=args.slow_window,
        fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
        account_equity_usdt=args.account_equity_usdt,
        target_notional_fraction=args.target_notional_fraction,
        leverage=args.leverage,
        include_funding=args.include_funding,
        cache_dir=args.cache_dir,
        funding_cache_dir=args.funding_cache_dir,
    )
    symbol_rules = None
    exchange_info = None
    if args.exchange_rules_path:
        symbol_rules = load_symbol_rules(args.exchange_rules_path, market=args.market)
    elif args.fetch_exchange_info:
        exchange_info = fetch_exchange_info(market=args.market)
    payload = build_binance_returns_dataset(config, exchange_info=exchange_info, symbol_rules=symbol_rules)
    artifact = write_binance_returns_artifact(Settings.from_env(), payload, explicit_path=args.output_path)
    if args.print_json:
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
    else:
        print(f"artifact={artifact['artifact_path']}")
        print(f"period_count={artifact['diagnostics']['period_count']}")
        print(f"total_turnover={artifact['diagnostics']['total_turnover']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
