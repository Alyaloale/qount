#!/usr/bin/env python3
"""X4 dynamic-universe walk-forward vs fixed TOP7 (docs/crypto-x4-plan.md §22 Phase 2).

The research question (owner, as strategy lead): under STRICT no-look-ahead + ragged-listing +
survivorship defense, can a monthly-rebalanced dynamic TOP-K (ranked by trailing liquidity from a
broad pool incl. declined/late coins) hold ~TOP5-like efficiency long-term, NET of rotation cost?

Compares fixed TOP7 (the §21 deployable) to dynamic TOP5/7/10. Metrics on full + train(21-23)/
test(24-26) slices off each equity curve (walk-forward-honest), plus a SURVIVORSHIP diagnostic:
how often the dynamic book actually held non-survivor names (else it just re-picks the same winners).

Pre-registered verdict: dynamic is a REAL improvement only if it beats fixed TOP7 Sharpe in BOTH
train AND test, net of turnover, without materially worse maxDD. Else it's selection theatre
(§16.1 lesson: cross-sectional selection has repeatedly been neutral-to-negative in this project).

Run on Mac (needs network: um 1d klines; first run slow, then cached):
    .venv/bin/python scripts/research/x4_dynuniverse.py 2021-01 2026-05
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.research_data.market_data import Bar, load_klines  # noqa: E402
from qount.legacy.x4.backtest import max_drawdown, run_trend_portfolio  # noqa: E402
from qount.legacy.x4.dynuniverse import run_dynamic_trend_portfolio  # noqa: E402
from qount.legacy.x4.portfolio import sharpe_of  # noqa: E402

CAP = 100_000.0
F, S = 0.0005, 0.0002
TEST_FROM = "2024-01"

SURVIVORS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
             "LINKUSDT", "LTCUSDT", "BCHUSDT", "AVAXUSDT", "ATOMUSDT", "ETCUSDT", "TRXUSDT"]
DECLINED = ["DOGEUSDT", "MATICUSDT", "NEARUSDT", "FILUSDT", "SANDUSDT", "MANAUSDT", "AAVEUSDT",
            "UNIUSDT", "FTMUSDT", "ICPUSDT", "APEUSDT", "GALAUSDT", "ALGOUSDT", "EOSUSDT",
            "XLMUSDT", "VETUSDT", "THETAUSDT", "LUNAUSDT", "1000LUNCUSDT", "FTTUSDT"]
LATE = ["SUIUSDT", "APTUSDT", "TIAUSDT", "SEIUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TONUSDT",
        "WLDUSDT", "1000PEPEUSDT", "ORDIUSDT", "WIFUSDT", "JUPUSDT", "RUNEUSDT"]
NON_SURVIVOR = set(DECLINED) | set(LATE)
TOP7_FIXED = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]

# §21 spot deployable trend params (shared by both engines for a fair race).
TREND = dict(fast=20, slow=100, regime_sma=200, vol_target=0.02, max_leverage=1.0,
             rebalance_band=0.25, vol_lookback=30, master_gate_sym="BTCUSDT", master_gate_sma=200)


def _load_pool(syms, span):
    (sy, sm), (ey, em) = span
    pool: dict[str, list[Bar]] = {}
    for s in syms:
        try:
            b = load_klines(s, "1d", start=(sy, sm), end=(ey, em), market="um", skip_missing=True)
        except Exception:
            continue
        if len(b) >= 60:                       # a real candidate (eligibility handled by the engine)
            pool[s] = b
    return pool


def _aligned(pool, syms):
    by = {s: {b.ts_ms: b for b in pool[s]} for s in syms if s in pool}
    common = sorted(set.intersection(*(set(d) for d in by.values())))
    return {s: [by[s][t] for t in common] for s in by}


def _split_idx(dates, ym):
    for i, d in enumerate(dates):
        if d >= f"{ym}-01":
            return i
    return len(dates)


def _metrics(curve, split):
    def m(c):
        return sharpe_of(c, periods_per_year=365.0), max_drawdown(c)
    return m(curve), m(curve[:split + 1]), m(curve[split:])


def _row(label, curve, dates, base=None):
    split = _split_idx(dates, TEST_FROM)
    (fs, fd), (rs, rd), (ts, td) = _metrics(curve, split)
    tot = curve[-1] / CAP - 1.0
    verdict = ""
    if base is not None:
        bf, bt, bv = base
        eps = 1e-9
        if rs > bt + eps and ts > bv + eps:
            verdict = "  REAL (both regimes)"
        elif rs > bt + eps and ts > bv - 0.02:
            verdict = "  weak-regime+ (neutral bull)"
        elif fs > bf + eps and rs <= bt + eps:
            verdict = "  curve-fit (only bull headline)"
        else:
            verdict = "  worse / neutral"
    print(f"  {label:24} {tot:>8.1%} | full {fs:>5.2f}/{fd:>6.1%} | train {rs:>5.2f}/{rd:>6.1%} "
          f"| test {ts:>5.2f}/{td:>6.1%}{verdict}")
    return (fs, rs, ts)


def _survivorship_diag(res):
    log = res["extra"]["membership_log"]
    used = set()
    months_with_nonsurv = 0
    for _date, members in log:
        ns = [m for m in members if m in NON_SURVIVOR]
        used.update(ns)
        if ns:
            months_with_nonsurv += 1
    frac = months_with_nonsurv / max(1, len(log))
    return used, frac, len(log)


def main(argv):
    start = argv[1] if len(argv) > 1 else "2021-01"
    end = argv[2] if len(argv) > 2 else "2026-05"
    span = (tuple(int(x) for x in start.split("-")), tuple(int(x) for x in end.split("-")))

    all_syms = SURVIVORS + DECLINED + LATE
    pool = _load_pool(all_syms, span)
    have_ns = sorted(s for s in pool if s in NON_SURVIVOR)
    print(f"[X4-DYNUNIVERSE] {start}..{end}; candidate pool {len(pool)}/{len(all_syms)} have data "
          f"({len(have_ns)} non-survivors: {', '.join(have_ns) if have_ns else 'NONE'})")
    if "BTCUSDT" not in pool:
        raise SystemExit("no BTC data")
    print(f"  {'engine':24} {'total':>8} | {'full S/DD':>13} | {'train S/DD':>14} | {'test S/DD':>14}")

    # fixed TOP7 baseline (intersection-aligned)
    fixed = _aligned(pool, TOP7_FIXED)
    fres = run_trend_portfolio(fixed, weighting="inverse_vol", initial_capital=CAP, taker_fee=F,
                               slippage=S, periods_per_year=365.0, **TREND)
    fdates = [b.date for b in fixed["BTCUSDT"]]
    base = _row("FIXED TOP7 (baseline)", fres.equity_curve, fdates)

    # dynamic TOP-K over the full pool
    for k in (5, 7, 10):
        res = run_dynamic_trend_portfolio(pool, k=k, vol_window=30, min_history=200,
                                          initial_capital=CAP, taker_fee=F, slippage=S,
                                          periods_per_year=365.0, **TREND)
        _row(f"DYNAMIC TOP{k}", res["equity_curve"], res["dates"], base=base)
        used, frac, n = _survivorship_diag(res)
        print(f"      survivorship: held >=1 non-survivor in {frac:.0%} of {n} months; "
              f"names ever used: {', '.join(sorted(used)) if used else 'NONE (re-picked survivors only)'}")

    print(f"\n  RULE: dynamic is REAL only if it beats fixed TOP7 Sharpe in BOTH train AND test, "
          f"net of turnover. If non-survivors are ~never held, the 'dynamic' pool collapses to the "
          f"survivor set and the test is survivorship-limited (data ceiling, stated honestly).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
