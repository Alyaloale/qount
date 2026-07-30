#!/usr/bin/env python3
"""GRID-B S1 / S1c kill-test runner: grid vs buy-and-hold-above-SMA200 on real data.

线 B (GRID-B), isolated from line A. Downloads Binance public kline dumps
(data.binance.vision -- no key, reproducible), builds a daily SMA200 trend gate, and
replays hourly bars through the baseline grid vs the hold-above-MA baseline. Prints the
verdict + per-year attribution and writes a JSON artifact under state/grid_b/.

Run on Mac (line B iterates locally):
    .venv/bin/python scripts/research/grid_b_s1.py
    .venv/bin/python scripts/research/grid_b_s1.py --step 0.015 --symbol ETHUSDT
    .venv/bin/python scripts/research/grid_b_s1.py --panel   # S1c: USDT trend re-tests + ETHBTC

S1c panel (v0.3 §2): same harness, same generous settings (full-window lookahead range,
maker fees, unleveraged) across a small symbol panel. ``ETHBTC`` is the H2 candidate --
quote is BTC, so ``grid_total_return``/``hold_total_return`` are *already* BTC-numeraire
("hold-ETH-above-200MA, BTC-denominated" is exactly the S1 ``hold`` baseline); the
"hold BTC and do nothing" baseline is simply 0.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.legacy.grid_b.backtest import S1Result, active_fraction, run_s1  # noqa: E402
from qount.research_data.market_data import load_klines  # noqa: E402

ARTIFACT_DIR = REPO / "state" / "grid_b" / "research_runs"

# S1c panel (v0.3 §2): USDT trend-asset re-tests (expected to fail like BTC, verifying
# generality) + ETHBTC, the H2 candidate (structural pair, no long-run fiat drift).
PANEL = ["ETHUSDT", "SOLUSDT", "BNBUSDT", "ETHBTC"]


def run_one(symbol: str, *, step: float, start: str, end: str, confirm_bars: int) -> S1Result:
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    # daily needs ~200 bars of SMA200 warm-up before the hourly window opens.
    dsy, dsm = (sy - 1, sm) if sm <= 6 else (sy, 1)

    print(f"[grid-b S1] {symbol} hourly {start}..{end}, step={step:.3%}")
    print("  downloading daily (SMA200 warm-up) ...", flush=True)
    daily = load_klines(symbol, "1d", start=(dsy, dsm), end=(ey, em), skip_missing=True)
    print(f"    daily bars: {len(daily)} ({daily[0].date}..{daily[-1].date})", flush=True)
    print("  downloading hourly (grid fills) ...", flush=True)
    hourly = load_klines(symbol, "1h", start=(sy, sm), end=(ey, em), skip_missing=True)
    print(f"    hourly bars: {len(hourly)} ({hourly[0].date}..{hourly[-1].date})", flush=True)

    res = run_s1(hourly, daily, step=step, confirm_bars=confirm_bars)

    print("\n=== S1 VERDICT (kill-test: can the grid beat hold-above-200MA?) ===")
    print(f"  range [L,U] = [{res.spec.lower:g}, {res.spec.upper:g}]  "
          f"n={res.spec.n} grids  realized_step={res.spec.step:.3%}  "
          f"net/grid={res.spec.net_per_grid:.3%}  lookahead_range={res.lookahead_range}")
    print(f"  grid total   {res.grid_total_return:+8.1%}   maxDD {res.grid_max_drawdown:+.1%}")
    print(f"  hold total   {res.hold_total_return:+8.1%}   maxDD {res.hold_max_drawdown:+.1%}")
    print(f"  Δ grid-hold  {res.grid_minus_hold:+8.1%}")
    print(f"  decomposition: harvest {res.grid_realized_harvest:+.1%}  "
          f"inventory {res.grid_inventory_pnl:+.1%}")
    print(f"  fills: {res.buy_fills} buys / {res.sell_fills} sells  "
          f"({res.total_crossings} crossings)")
    print("\n  per-year:")
    print("    year   grid      hold      Δ        crossings")
    for y in res.per_year:
        flag = "WIN " if y.grid_minus_hold > 0 else "lose"
        print(f"    {y.year}  {y.grid_return:+7.1%}  {y.hold_return:+7.1%}  "
              f"{y.grid_minus_hold:+7.1%}  {y.crossings:>7}  {flag}")
    print(f"\n  >>> {res.verdict}")

    if symbol == "ETHBTC":
        frac = active_fraction(hourly, daily, confirm_bars=confirm_bars)
        print(f"\n  [O-B5 diag] SMA200 ACTIVE fraction of window = {frac:.1%}")

        n_pos_years = sum(1 for y in res.per_year if y.grid_return > 0)
        passes = (
            res.grid_total_return > 0
            and n_pos_years >= 4
            and abs(res.grid_max_drawdown) < res.grid_realized_harvest
        )
        print("\n=== H2 verdict (v0.3 §2 pre-registered, ETHBTC) ===")
        print(f"  BTC本位总收益 {res.grid_total_return:+.2%} "
              f"({'>' if res.grid_total_return > 0 else '<='}0)")
        print(f"  正收益年数 {n_pos_years}/{len(res.per_year)} (need >=4)")
        print(f"  maxDD {res.grid_max_drawdown:+.2%} vs harvest {res.grid_realized_harvest:+.2%} "
              f"({'<' if abs(res.grid_max_drawdown) < res.grid_realized_harvest else '>='})")
        print(f"  >>> {'H2 活' if passes else 'H2 死'}")

    write_artifact(symbol, res, step=step, start=start, end=end, confirm_bars=confirm_bars)
    return res


def write_artifact(symbol: str, res: S1Result, *, step: float, start: str, end: str,
                    confirm_bars: int) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARTIFACT_DIR / f"s1_{symbol}_{start}_{end}_step{step}_{stamp}.json"
    payload = dataclasses.asdict(res)
    payload["spec"] = {k: v for k, v in payload["spec"].items() if k != "prices"}
    payload.pop("grid_curve", None)
    payload.pop("hold_curve", None)
    payload["args"] = {"symbol": symbol, "step": step, "start": start, "end": end,
                        "confirm_bars": confirm_bars}
    out.write_text(json.dumps(payload, indent=2, default=float))
    print(f"\n  artifact: {out.relative_to(REPO)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--step", type=float, default=0.01)
    ap.add_argument("--start", default="2021-01", help="hourly window start YYYY-MM")
    ap.add_argument("--end", default="2026-05", help="hourly window end YYYY-MM (inclusive)")
    ap.add_argument("--confirm-bars", type=int, default=2)
    ap.add_argument("--panel", action="store_true",
                    help="S1c: run the USDT-pair + ETHBTC panel instead of --symbol")
    args = ap.parse_args()

    symbols = PANEL if args.panel else [args.symbol]
    for symbol in symbols:
        run_one(symbol, step=args.step, start=args.start, end=args.end,
                confirm_bars=args.confirm_bars)
        print("\n" + "=" * 78 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
