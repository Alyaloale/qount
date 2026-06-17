#!/usr/bin/env python3
"""Real backtest of the CURRENT live config (vol-parity + breadth-OR + corr-penalty + chandelier)
on the fixed TOP7 universe, with ablations to find weaknesses. Read-only; writes no state.

The live `x4/live.py` exits/sizing map onto `run_trend_portfolio` switches:
  vol-parity      -> vol_target/max_leverage   (faithful)
  breadth-OR gate -> breadth_gate/breadth_combine
  corr penalty    -> weighting='inverse_vol_corr'
  chandelier stop -> chandelier_mult/lookback  (engine = DAILY chandelier; live = intraday proxy)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import load_funding, load_klines  # noqa: E402
from qount.x4.backtest import run_trend_portfolio  # noqa: E402

START = (2021, 1)
UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]  # live TOP7

# current live config (x4/live.py defaults)
LIVE = dict(fast=20, slow=100, regime_sma=200, master_gate_sym="BTCUSDT", master_gate_sma=200,
            vol_target=0.03, max_leverage=2.0, vol_lookback=30, rebalance_band=0.25,
            taker_fee=0.0005, slippage=0.0002, periods_per_year=365.0,
            weighting="inverse_vol_corr", breadth_gate=0.5, breadth_combine="or",
            chandelier_mult=8.0, chandelier_lookback=22)   # 8× = disaster-only (see live.py)

VARIANTS = {
    "LIVE 全配置": {},
    "− chandelier": dict(chandelier_mult=0.0),
    "− corr惩罚": dict(weighting="inverse_vol"),
    "− breadth闸": dict(breadth_gate=None),
    "验证基线(都关)": dict(weighting="inverse_vol", breadth_gate=None, chandelier_mult=0.0),
    # T3-4: MA200 斜率确认 — 总闸额外要求 SMA200 上行(slope lookback 天). reviewer 头号增量,
    # 预注册判据(§21.4)= train(≤23) 且 test(≥24) 都打过 LIVE 全配置 Sharpe 且 DD 不显著恶化.
    "+斜率5d": dict(master_gate_slope=5),
    "+斜率20d": dict(master_gate_slope=20),
    # T3-8: 动态 vol_target — 组合回撤超阈值时把敞口按 derisk_vt/vt 缩(风控杠杆,reviewer 建议 DD>15%→2%).
    "+动态vt DD15→2%": dict(dd_derisk_threshold=0.15, dd_derisk_vol_target=0.02),
    "+动态vt DD20→2%": dict(dd_derisk_threshold=0.20, dd_derisk_vol_target=0.02),
    "+动态vt DD15→1.5%": dict(dd_derisk_threshold=0.15, dd_derisk_vol_target=0.015),
}


def _load():
    now_y, now_m = 2026, 6
    by = {}
    for s in UNIVERSE:
        bars = load_klines(s, "1d", start=START, end=(now_y, now_m), market="um", skip_missing=True)
        if len(bars) > 300:
            by[s] = {b.ts_ms: b for b in bars}
    common = sorted(set.intersection(*(set(d) for d in by.values())))
    return {s: [by[s][t] for t in common] for s in by}


def _maxdd(curve):
    peak, worst = curve[0], 0.0
    for x in curve:
        peak = max(peak, x)
        if peak > 0:
            worst = min(worst, x / peak - 1.0)
    return worst


def _yearly(dates, curve):
    """Calendar-year returns from the equity curve."""
    out, prev_end = {}, curve[0]
    by_year = {}
    for d, e in zip(dates, curve):
        by_year[d[:4]] = e  # last equity seen in each year
    start = curve[0]
    for y in sorted(by_year):
        end = by_year[y]
        out[y] = end / prev_end - 1.0
        prev_end = end
    return out


def _funding_by_sym():
    """Per-coin daily funding callable (8h rates summed per day) — perp longs PAY positive funding,
    so this is a real cost the naive backtest ignores. ~+11%/yr on BTC/ETH, worst in bulls."""
    out = {}
    for s in UNIVERSE:
        d = {}
        for fr in load_funding(s, start=START, end=(2026, 6), skip_missing=True):
            k = fr.ts_ms // 86_400_000
            d[k] = d.get(k, 0.0) + fr.rate
        out[s] = (lambda dd: (lambda bar: dd.get(bar.ts_ms // 86_400_000, 0.0)))(d)
    return out


def _run(aligned, fmap, **over):
    cfg = {**LIVE, **over}
    return run_trend_portfolio(aligned, initial_capital=100_000.0, funding_by_sym=fmap, **cfg)


def main() -> int:
    aligned = _load()
    fmap = _funding_by_sym()
    dates = [b.date for b in aligned["BTCUSDT"]]
    n = len(dates)
    print(f"TOP7 live-strategy backtest (funding-adjusted/诚实)  {dates[0]}..{dates[-1]}  ({n} bars, {len(aligned)} coins)\n")

    print(f"  {'变体':<16} | {'total':>9} | {'Sharpe':>6} | {'maxDD':>7} | {'gate%':>5} | {'ch_exits':>8}")
    print("  " + "-" * 70)
    results = {}
    for name, over in VARIANTS.items():
        r = _run(aligned, fmap, **over)
        results[name] = r
        ch = r.extra.get("chandelier_exits", "—")
        print(f"  {name:<16} | {r.total_return:>+8.1%} | {r.sharpe:>6.2f} | {r.max_drawdown:>+7.1%} | "
              f"{r.extra.get('gate_active_frac', 0):>4.0%} | {str(ch):>8}")

    # per-year for the LIVE full config (find regime weaknesses)
    print("\n  LIVE 全配置 · 逐年:")
    yr = _yearly(dates, results["LIVE 全配置"].equity_curve)
    print("   " + "  ".join(f"{y}:{v:+.0%}" for y, v in yr.items()))

    # train(21-23)/test(24-26) overfit check: LIVE vs validated baseline
    print("\n  train(≤2023-12-31) / test(≥2024-01-01) Sharpe (过拟合检验):")
    split = next((i for i, d in enumerate(dates) if d >= "2024-01-01"), n)
    from qount.x4.portfolio import sharpe_of
    for name in ("LIVE 全配置", "验证基线(都关)", "+斜率20d",
                 "+动态vt DD15→2%", "+动态vt DD20→2%", "+动态vt DD15→1.5%"):
        c = results[name].equity_curve
        tr = sharpe_of(c[:split], periods_per_year=365.0)
        te = sharpe_of(c[split:], periods_per_year=365.0)
        print(f"    {name:<16} train {tr:+.2f}  test {te:+.2f}")
    print("\n  注:chandelier 为引擎日线版(live 是盘中实时版的代理);taker 费+滑点已扣;TOP7 现货等价。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
