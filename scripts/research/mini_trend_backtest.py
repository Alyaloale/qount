#!/usr/bin/env python3
"""MiniTrend research-only backtest entry.

Loads Binance-vision spot daily bars, runs the deterministic MiniTrend core, and writes a replayable
artifact directory. This is not a paper/live runner.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_klines  # noqa: E402
from qount.mini_trend.backtest import research_filters, run_backtest, write_backtest_artifact  # noqa: E402
from qount.mini_trend.config import DEFAULT_UNIVERSE, MiniTrendConfig  # noqa: E402


def _month(value: str) -> tuple[int, int]:
    try:
        y, m = value.split("-", 1)
        year, month = int(y), int(m)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM") from exc
    if month < 1 or month > 12:
        raise argparse.ArgumentTypeError("month must be 1..12")
    return year, month


def _default_output() -> Path:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("state") / "mini_trend" / "research_runs" / f"{stamp}-mini-trend-backtest"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MiniTrend research-only spot backtest")
    p.add_argument("--start", type=_month, default=(2024, 1), help="start month, YYYY-MM")
    p.add_argument("--end", type=_month, default=(2026, 6), help="end month, YYYY-MM")
    p.add_argument("--symbols", default=",".join(DEFAULT_UNIVERSE), help="comma-separated symbols")
    p.add_argument("--cache-dir", default="state/grid_b/klines")
    p.add_argument("--output-dir", type=Path, default=None)
    p.add_argument("--capital", type=float, default=400.0)
    p.add_argument("--vol-target", type=float, default=0.015)
    p.add_argument("--rebalance-band", type=float, default=0.35)
    p.add_argument("--min-notional", type=float, default=10.0)
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slippage-bps", type=float, default=2.0)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
    cfg = MiniTrendConfig(
        universe=symbols,
        gate_symbol=symbols[0],
        capital_cap_usdt=args.capital,
        vol_target=args.vol_target,
        rebalance_band=args.rebalance_band,
    )
    bars_by_symbol = {
        s: load_klines(
            s,
            "1d",
            start=args.start,
            end=args.end,
            market="spot",
            cache_dir=args.cache_dir,
            skip_missing=True,
        )
        for s in symbols
    }
    result = run_backtest(
        bars_by_symbol,
        cfg,
        filters=research_filters(symbols, min_notional=args.min_notional),
        taker_fee=args.fee_bps / 10_000.0,
        slippage=args.slippage_bps / 10_000.0,
    )
    out = write_backtest_artifact(result, args.output_dir or _default_output())
    print(f"artifact={out}")
    print(
        "summary "
        f"{result.summary['start']}..{result.summary['end']} "
        f"return={result.summary['total_return_pct']:.4f}% "
        f"maxDD={result.summary['max_drawdown_pct']:.4f}% "
        f"orders={result.summary['order_count']} "
        f"verdict={result.summary['scorecard_verdict']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
