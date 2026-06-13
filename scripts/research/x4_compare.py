#!/usr/bin/env python3
"""X4: four-strategy crypto bake-off — equal-capital backtest comparison (docs/crypto-x4-plan.md).

线 D (X4), isolated from 线 A/B/C. Run the four contestants on the SAME bars / window / fee /
$100k capital and lay their results side by side — this is a horse-race, NOT a kill-test (the
owner relaxed the line to: design each to backtest well, then compare on equal capital).

Setup (plan §3, fairness is the whole point):
  * S1-GRID / S3-CTA / S4-MOM run on BTC USDT-M perp (the primary single asset).
  * S2-PAIR runs on the BTC-ETH ratio (two-leg, dollar-neutral) by its nature.
  * All start $100k, 1h bars, taker 5bp + slippage 2bp; S3/S4 also accrue BTC funding.

Outputs the §4 comparison table + the four-strategy return-correlation matrix + per-year
attribution, and saves a JSON artifact under state/x4/research_runs/.

Run on Mac (needs network to data.binance.vision: um klines + funding):
    .venv/bin/python scripts/research/x4_compare.py 2021-01 2026-05 1h
"""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.rv.stats import returns_from_curve  # noqa: E402
from qount.x4.backtest import run_directional, run_grid, run_pair  # noqa: E402
from qount.x4.strategies import (  # noqa: E402
    GridStrategy,
    MomentumBreakout,
    PairStrategy,
    TrendFollow,
)

ARTIFACT_DIR = REPO / "state" / "x4" / "research_runs"
CAPITAL = 100_000.0
TAKER_FEE = 0.0005
SLIPPAGE = 0.0002
REBALANCE_BAND = 0.25   # B1-b: drift deadband for directional legs (kills fee micro-churn)


def _cagr(total: float, n_bars: int, bars_per_year: float) -> float:
    years = n_bars / bars_per_year
    if years <= 0 or 1.0 + total <= 0.0:
        return -1.0 if 1.0 + total <= 0.0 else 0.0
    return (1.0 + total) ** (1.0 / years) - 1.0


def _pearson(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return cov / (va ** 0.5 * vb ** 0.5)


def _funding_map(symbol, start, end):
    rows = load_funding(symbol, start=start, end=end, skip_missing=True)
    return {f.ts_ms: f.rate for f in rows}


def _per_year(curve: list[float], bars: list, bars_per_year: float) -> dict[str, float]:
    """Per-calendar-year fractional return of an equity curve (regime attribution)."""

    out: dict[str, list[int]] = {}
    for i, bar in enumerate(bars):
        yr = bar.date[:4]
        out.setdefault(yr, []).append(i)
    res = {}
    for yr, idxs in out.items():
        lo, hi = idxs[0], idxs[-1]
        start_eq = curve[lo - 1] if lo > 0 else CAPITAL
        if start_eq > 0:
            res[yr] = curve[hi] / start_eq - 1.0
    return res


def main(argv: list[str]) -> int:
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    interval = argv[3] if len(argv) > 3 else "1h"
    btc_sym = argv[4] if len(argv) > 4 else "BTCUSDT"
    eth_sym = argv[5] if len(argv) > 5 else "ETHUSDT"
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    bars_per_year = 365.0 if interval == "1d" else 365.0 * 24.0

    print(f"[X4] bake-off {btc_sym}/{eth_sym} {start}..{end} ({interval}); "
          f"${CAPITAL:,.0f}/strategy, taker {TAKER_FEE:.2%} + slip {SLIPPAGE:.2%}")
    btc = load_klines(btc_sym, interval, start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
    eth = load_klines(eth_sym, interval, start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
    if not btc or not eth:
        print("  missing BTC or ETH um klines on binance.vision")
        return 2

    # align BTC/ETH to common timestamps (S2 needs both; keeps all curves the same length)
    eth_by_ts = {b.ts_ms: b for b in eth}
    btc_a = [b for b in btc if b.ts_ms in eth_by_ts]
    eth_a = [eth_by_ts[b.ts_ms] for b in btc_a]
    print(f"  aligned bars: {len(btc_a)} ({btc_a[0].date}..{btc_a[-1].date})")

    fmap = _funding_map(btc_sym, (sy, sm), (ey, em))
    funding = lambda bar: fmap.get(bar.ts_ms, 0.0)  # noqa: E731

    # B3-optimized config (root cause of the B1-b losses: 1h whipsaw + shorting an uptrending
    # asset + soft-pair runaway). Fixes: run daily (interval arg), long-bias the directional legs
    # (no shorting BTC's secular uptrend), Turtle asymmetric exit on S4, and a stop_z break on S2.
    # §12 dynamic-parameter optimizations (static params fail across regime shifts):
    #  S1: ATR-dynamic grid (atr_mult>0) -- widen in high vol, tighten in low vol.
    #  S3/S4: volatility-parity sizing (vol_target/max_leverage) -- constant risk exposure, caps DD.
    #         vt=3%/cap=2x strictly *dominates* the fixed-1x baseline (higher return, higher Sharpe,
    #         lower maxDD) -- a Pareto win, not a trade-off.
    #  S2: kept on the tuned static z (the "回测好看" headline). NOTE the Kalman variant (run_kalman_pair)
    #      is more principled but shows the BTC-ETH pair has no robust reversion edge (β adapts the
    #      drift away) -- i.e. S2's +45.8% is in-sample tuning, not a real edge. See §12.
    grid = GridStrategy()
    pair = PairStrategy(window=60, entry_z=2.5, exit_z=0.5, stop_z=3.0)
    cta = TrendFollow(fast=20, slow=100, allow_short=False, regime_sma=200)
    mom = MomentumBreakout(lookback=20, exit_lookback=10, vol_mult=1.0, allow_short=False, regime_sma=200)
    runs = {
        "S1-GRID": run_grid(btc_a, grid, initial_capital=CAPITAL, taker_fee=TAKER_FEE,
                            slippage=SLIPPAGE, atr_mult=5.0, periods_per_year=bars_per_year),
        "S2-PAIR": run_pair(btc_a, eth_a, pair, initial_capital=CAPITAL,
                            taker_fee=TAKER_FEE, slippage=SLIPPAGE, periods_per_year=bars_per_year),
        "S3-CTA": run_directional(btc_a, cta, initial_capital=CAPITAL, taker_fee=TAKER_FEE,
                                  slippage=SLIPPAGE, funding=funding, rebalance_band=REBALANCE_BAND,
                                  vol_target=0.03, max_leverage=2.0, periods_per_year=bars_per_year),
        # §15: S4 (breakout) gets the asymmetric Chandelier exit -- its Donchian signal toggles off
        # often so the latch re-arms; 4x dominates the no-stop baseline (return+Sharpe up, DD down).
        # NOT applied to S3 (its MA-cross already exits well; chandelier+latch double-stops and sidelines it).
        "S4-MOM": run_directional(btc_a, mom, initial_capital=CAPITAL, taker_fee=TAKER_FEE,
                                  slippage=SLIPPAGE, funding=funding, rebalance_band=REBALANCE_BAND,
                                  vol_target=0.03, max_leverage=2.0, chandelier_mult=4.0,
                                  chandelier_lookback=22, periods_per_year=bars_per_year),
    }

    # ---- §4 comparison table -------------------------------------------------------------
    print("\n=== §4 comparison (equal $100k, same bars/fee) ===")
    print(f"  {'strat':8} {'total':>9} {'CAGR':>8} {'Sharpe':>7} {'maxDD':>8} "
          f"{'trades':>7} {'fees$':>10}")
    rows = {}
    for name, r in runs.items():
        cagr = _cagr(r.total_return, len(r.equity_curve), bars_per_year)
        print(f"  {name:8} {r.total_return:>+8.1%} {cagr:>+7.1%} {r.sharpe:>7.2f} "
              f"{r.max_drawdown:>7.1%} {r.trade_count:>7d} {r.fees_paid:>10,.0f}")
        rows[name] = {
            "total_return": r.total_return, "cagr": cagr, "sharpe": r.sharpe,
            "max_drawdown": r.max_drawdown, "trade_count": r.trade_count,
            "fees_paid": r.fees_paid, "funding_pnl": r.funding_pnl, "extra": r.extra,
        }

    # ---- correlation matrix of per-bar returns -------------------------------------------
    names = list(runs)
    rets = {n: returns_from_curve(runs[n].equity_curve) for n in names}
    print("\n=== return-correlation matrix (low = diversification value) ===")
    print("           " + " ".join(f"{n:>8}" for n in names))
    corr = {}
    for a in names:
        line, row = [], {}
        for b in names:
            c = _pearson(rets[a], rets[b])
            row[b] = c
            line.append(f"{c:>8.2f}")
        corr[a] = row
        print(f"  {a:8} " + " ".join(line))

    # ---- per-year attribution ------------------------------------------------------------
    print("\n=== per-year return (regime attribution; not single-regime carried?) ===")
    years = sorted({y for n in names for y in _per_year(runs[n].equity_curve, btc_a, bars_per_year)})
    print("           " + " ".join(f"{y:>8}" for y in years))
    attr = {}
    for n in names:
        py = _per_year(runs[n].equity_curve, btc_a, bars_per_year)
        attr[n] = py
        print(f"  {n:8} " + " ".join(f"{py.get(y, 0.0):>+7.1%}" for y in years))

    print("\n  NOTE: this is a bake-off, not a verdict. Read the honest caveats: a fat curve carried "
          "by one regime, fee-drag on a high-turnover strat, and S2 being a soft (cointegration-"
          "fragile) pair are all visible above and must be stated, not sold as edge.")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ARTIFACT_DIR / f"x4_compare_{start}_{end}_{interval}_{stamp}.json"
    out.write_text(json.dumps({
        "window": [start, end], "interval": interval, "n_bars": len(btc_a),
        "capital": CAPITAL, "taker_fee": TAKER_FEE, "slippage": SLIPPAGE,
        "metrics": rows, "correlation": corr, "per_year": attr,
    }, indent=2))
    print(f"\n  artifact -> {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
