#!/usr/bin/env python3
"""X4 paper-sim ops runner: replay (engine validation) + forward (daily live paper). §18 / B2.

Deploys the §17-validated 3-sleeve portfolio (S1-GRID + S3-CTA + S4-MOM; S2 excluded). No real orders.

  replay [months] : run the engine over recent data and print the daily snapshot trail + final
                    metrics. Fidelity to the backtest is by construction (papersim re-runs the exact
                    drivers) -- eyeball the final sleeve totals against §15 (S1 +5.4 / S3 +115 / S4 +98).
  forward         : pull the latest 1d bars, run the engine, append one snapshot line to
                    state/x4/paper/snapshots.jsonl (+ latest.json), and print today's snapshot.
                    Run this daily (after the 00:00 UTC bar closes), e.g. from cron.

Run on Mac (needs network: um 1d klines + funding):
    .venv/bin/python scripts/research/x4_paper.py replay 12
    .venv/bin/python scripts/research/x4_paper.py forward
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.x4.backtest import run_trend_portfolio  # noqa: E402
from qount.x4.papersim import PaperConfig, run_paper  # noqa: E402

PAPER_DIR = REPO / "state" / "x4" / "paper"
START = (2021, 1)  # full history for indicator warm-up (SMA200 etc.)

# S7-TREND-PORT (§19) deployable config + universe. Same 14-coin survivor set as §16.1/§19.6.
# vol_target=2% is the §19.7 deployable SIZE: it dials the in-sample maxDD to ~-21% (clears the
# pre-registered -25% bar with margin); Sharpe (~0.88) is invariant to this sizing -- it is a
# risk-budget choice, NOT an alpha tweak. Honest forward expectation is lower (§17: ~0.70).
S7_UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
               "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT", "ATOMUSDT", "ETCUSDT", "TRXUSDT"]
S7_CONFIG = dict(weighting="inverse_vol", master_gate_sym="BTCUSDT", master_gate_sma=200,
                 fast=20, slow=100, regime_sma=200, vol_target=0.02, max_leverage=2.0,
                 rebalance_band=0.25, taker_fee=0.0005, slippage=0.0002, periods_per_year=365.0)


def _load(end_y: int, end_m: int):
    btc = load_klines("BTCUSDT", "1d", start=START, end=(end_y, end_m), market="um", skip_missing=True)
    fmap = {f.ts_ms: f.rate for f in load_funding("BTCUSDT", start=START, end=(end_y, end_m), skip_missing=True)}
    return btc, (lambda b: fmap.get(b.ts_ms, 0.0))


def _load_universe(end_y: int, end_m: int):
    """Load + intersection-align the S7 universe up to ``(end_y, end_m)`` (daily-dump fallback fills
    the in-progress month). Returns ``{sym: [Bar]}`` aligned to common timestamps, or ``None``."""

    by_sym: dict[str, dict] = {}
    for sym in S7_UNIVERSE:
        bars = load_klines(sym, "1d", start=START, end=(end_y, end_m), market="um", skip_missing=True)
        if len(bars) > 300:
            by_sym[sym] = {b.ts_ms: b for b in bars}
    if "BTCUSDT" not in by_sym:
        return None
    common = sorted(set.intersection(*(set(d) for d in by_sym.values())))
    return {s: [by_sym[s][t] for t in common] for s in by_sym}


def _print_snapshot(snap: dict) -> None:
    p = snap["portfolio"]
    print(f"  [{snap['date']}] portfolio: equity ${p['equity']:,.0f}  total {p['total_return']:+.1%}  "
          f"Sharpe {p['sharpe']:.2f}  maxDD {p['max_drawdown']:.1%}  (fees ${snap['fees_to_date']:,.0f})")
    for nm, m in snap["sleeves"].items():
        pos = snap["positions"][nm]
        tag = (f"w={pos['weight']:+.2f}" if "weight" in pos else f"inv={pos['inventory_base']:.3f}")
        print(f"      {nm:8} total {m['total_return']:+7.1%}  Sharpe {m['sharpe']:5.2f}  "
              f"maxDD {m['max_drawdown']:6.1%}  [{tag}]")


def replay(months: int) -> int:
    now = dt.datetime.now(dt.UTC)
    btc, fund = _load(now.year, now.month)
    if len(btc) < 300:
        print("  too few bars"); return 2
    cfg = PaperConfig()
    res = run_paper(btc, config=cfg, funding=fund)
    print(f"[X4-PAPER replay] {btc[0].date}..{btc[-1].date}  ({len(btc)} bars); deployed = "
          f"S1+S3+S4 equal-weight (S2 excluded, §17)")
    # daily snapshot trail over the last `months`
    n_tail = min(len(btc), months * 30)
    print(f"\n  --- last ~{months}mo portfolio equity trail ---")
    pc = res.portfolio_curve
    step = max(1, n_tail // 12)
    for i in range(len(btc) - n_tail, len(btc), step):
        print(f"    {btc[i].date}  ${pc[i]:,.0f}  ({pc[i]/cfg.initial_capital-1:+.1%})")
    print("\n  --- final snapshot (eyeball sleeve totals vs §15: S1 +5.4 / S3 +115 / S4 +98) ---")
    _print_snapshot(res.snapshot)
    print("\n  fidelity: papersim re-runs the exact backtest drivers -> sleeve curves are bit-for-bit"
          " the §15 results (pinned by tests/test_x4_papersim.py). Engine validated.")
    return 0


def forward() -> int:
    now = dt.datetime.now(dt.UTC)
    btc, fund = _load(now.year, now.month)
    if len(btc) < 300:
        print("  too few bars"); return 2
    res = run_paper(btc, config=PaperConfig(), funding=fund)
    snap = res.snapshot
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    # append one line per run (idempotent-ish: dedup by date on read if needed)
    with (PAPER_DIR / "snapshots.jsonl").open("a") as fh:
        fh.write(json.dumps({"run_at": now.isoformat(), **snap}, default=float) + "\n")
    (PAPER_DIR / "latest.json").write_text(json.dumps(snap, indent=2, default=float))
    print(f"[X4-PAPER forward] {now.isoformat()}  bar {snap['date']}")
    _print_snapshot(snap)
    print(f"\n  snapshot appended -> {(PAPER_DIR / 'snapshots.jsonl').relative_to(REPO)}")
    print("  PRE-REGISTERED expectation (§17): forward Sharpe ~0.4-0.7 (not in-sample 0.88), portfolio"
          " maxDD ~-17%; SMA200 gate should keep S3/S4 flat in a bear (portfolio shouldn't deep-bleed).")
    return 0


def forward_s7() -> int:
    """Daily forward paper for S7-TREND-PORT (§19.7): multi-coin trend portfolio, deployable size.

    Loads the aligned universe up to today, runs the deployable config, and appends a snapshot to
    a SEPARATE log (``s7_snapshots.jsonl`` / ``s7_latest.json``) so it never collides with the 3-leg
    §18 paper. No real orders -- pure simulation."""

    now = dt.datetime.now(dt.UTC)
    aligned = _load_universe(now.year, now.month)
    if aligned is None or len(aligned["BTCUSDT"]) < 300:
        print("  too few bars"); return 2
    res = run_trend_portfolio(aligned, initial_capital=100_000.0, **S7_CONFIG)
    btc = aligned["BTCUSDT"]
    snap = {
        "date": btc[-1].date,
        "n_bars": len(btc),
        "n_syms": res.extra["n_syms"],
        "gate_active_frac": round(res.extra["gate_active_frac"], 4),
        "portfolio": {
            "equity": round(res.equity_curve[-1], 2),
            "total_return": res.total_return,
            "sharpe": res.sharpe,
            "max_drawdown": res.max_drawdown,
        },
        "fees_to_date": round(res.fees_paid, 2),
    }
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    with (PAPER_DIR / "s7_snapshots.jsonl").open("a") as fh:
        fh.write(json.dumps({"run_at": now.isoformat(), **snap}, default=float) + "\n")
    (PAPER_DIR / "s7_latest.json").write_text(json.dumps(snap, indent=2, default=float))
    p = snap["portfolio"]
    print(f"[X4-PAPER forward-s7] {now.isoformat()}  bar {snap['date']}  ({snap['n_syms']} syms)")
    print(f"  S7-TREND-PORT: equity ${p['equity']:,.0f}  total {p['total_return']:+.1%}  "
          f"Sharpe {p['sharpe']:.2f}  maxDD {p['max_drawdown']:.1%}  "
          f"(BTC-gate active {snap['gate_active_frac']:.0%}, fees ${snap['fees_to_date']:,.0f})")
    print(f"\n  snapshot appended -> {(PAPER_DIR / 's7_snapshots.jsonl').relative_to(REPO)}")
    print("  PRE-REGISTERED (§19.7): deployable size vol_target=2% -> in-sample ~+80%/0.87/-21%;"
          " honest forward Sharpe anchored ~0.70 (§17, not in-sample 0.88); BTC gate flattens in a bear.")
    return 0


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "replay"
    if mode == "replay":
        return replay(int(argv[2]) if len(argv) > 2 else 12)
    if mode == "forward":
        return forward()
    if mode == "forward-s7":
        return forward_s7()
    print(f"unknown mode {mode!r} (expected 'replay', 'forward', or 'forward-s7')")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
