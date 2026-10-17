#!/usr/bin/env python3
"""Preview the independent historical simplified 1ATR rule; live entry is retired."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from qount.binance_assets import load_binance_assets
from qount.strategies.one_atr import DailyBar, build_signal, select_signal


def _exchange() -> ccxt.Exchange:
    return ccxt.binance({
        "enableRateLimit": True,
        "timeout": 10000,
        "options": {"defaultType": "future", "fetchCurrencies": False},
        "apiKey": os.environ.get("QOUNT_BINANCE_API_KEY", ""),
        "secret": os.environ.get("QOUNT_BINANCE_API_SECRET", ""),
    })


def _bars(exchange: ccxt.Exchange, symbol: str, limit: int, *, now: datetime | None = None) -> list[DailyBar]:
    rows = exchange.fetch_ohlcv(symbol, timeframe="1d", limit=limit)
    current = now or datetime.now(timezone.utc)
    day_start = datetime(current.year, current.month, current.day, tzinfo=timezone.utc).timestamp()
    # Binance includes the still-forming UTC daily candle. A daily-close rule
    # must never use that row as a decision input.
    bars = [DailyBar(int(row[0] // 1000), *map(float, row[1:6]))
            for row in rows if int(row[0] // 1000) < day_start]
    if len(bars) < 121:
        raise RuntimeError(f"daily_history_short:{symbol}")
    return bars


def build_plan(exchange: ccxt.Exchange, *, limit: int = 160) -> dict[str, object]:
    assets = [asset for asset in load_binance_assets() if asset.status == "active"]
    signals = []
    errors = {}
    try:
        markets = exchange.load_markets()
    except Exception as exc:
        return {
            "strategy_id": "one_atr_macro_v0_1",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "research_only": True,
            "orders_authorized": False,
            "execution_mode": "plan_only",
            "selected": None,
            "signals": [],
            "errors": {"markets": type(exc).__name__},
            "execution_blocker": "binance_market_data_unavailable",
        }
    live_symbols = set()
    for symbol, market in markets.items():
        info = market.get("info") or {}
        if (market.get("linear") is True and market.get("swap") is True
                and market.get("quote") == "USDT"
                and info.get("status") == "TRADING"):
            live_symbols.add(str(info.get("symbol") or symbol.replace("/", "").replace(":USDT", "")).upper())
    for asset in assets:
        if asset.execution_symbol not in live_symbols:
            errors[asset.execution_symbol] = "exchange_symbol_not_trading"
            continue
        try:
            signals.append(build_signal(asset.execution_symbol, _bars(exchange, asset.execution_symbol, limit)))
        except Exception as exc:
            errors[asset.execution_symbol] = type(exc).__name__
    selected = select_signal(signals)
    return {
        "strategy_id": "one_atr_macro_v0_1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "research_only": True,
        "orders_authorized": False,
        "execution_mode": "plan_only",
        "selected": selected.__dict__ if selected else None,
        "signals": [signal.__dict__ for signal in signals],
        "errors": errors,
        "execution_blocker": "one_shot_arm_required_for_live_entry",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Historical simplified 1ATR preview; live execution retired")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=160)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    if args.execute or args.recover:
        raise SystemExit("simplified_1atr_live_retired: use run_macro_1atr; preserve legacy protection until flat")
    result = build_plan(_exchange(), limit=args.limit)
    result["execution_blocker"] = "historical_simplified_strategy_live_retired"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, args.output)
    print(json.dumps({"output": str(args.output), "selected": result["selected"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
