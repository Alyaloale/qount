#!/usr/bin/env python3
"""X4 刷新频率分析(线 D)— owner 点名「目前一日才刷新」.

现状:信号(SMA200 闸 / SMA20·60 趋势 / ATR vol-parity / 逆波动率)在**日线收盘**算,cron 每 2 分钟跑但
当天信号不变 → regime flip(BTC 收上/跌破 200 线、币趋势翻转)最多滞后 ~24h 才动手.问题:把**同一套经济
信号**(还是 200-DAY/20-DAY/60-DAY)改成**每 4h 评估一次**(滞后 24h→4h),是帮忙(早进早出)还是只是
加 whipsaw(线 D §11「日内是噪声」的元结论)?

测法 = apples-to-apples:同一套 run_directional + combine + 大盘闸,唯一差别 = bar 粒度 + lookback 同比放大
(日→4h ×6:regime 200→1200、fast 20→120、slow 60→360、ATR 14→84、chandelier 22→132、combine vol 30→180),
Sharpe 各自年化(日 365 / 4h 2190).两边都**不计 funding**(隔离刷新效应;funding ≈ −2pp/yr 是两边共同的常数拖累).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "research"))

from qount.research_data.market_data import load_klines  # noqa: E402
from qount.legacy.x4.backtest import run_directional  # noqa: E402
from qount.legacy.x4.portfolio import combine, sharpe_of  # noqa: E402
from qount.legacy.x4.strategies import TrendFollow, sma_regime_mask  # noqa: E402

UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
F, S = 0.0005, 0.0002
CAP = 100_000.0


def _load(interval):
    by = {}
    for s in UNIVERSE:
        b = load_klines(s, interval, start=(2021, 1), end=(2026, 6), market="um", skip_missing=True)
        if len(b) > 400:
            by[s] = {x.ts_ms: x for x in b}
    common = sorted(set.intersection(*(set(d) for d in by.values())))
    return {s: [by[s][t] for t in common] for s in by}


def _maxdd(c):
    peak, w = c[0], 0.0
    for x in c:
        peak = max(peak, x)
        if peak > 0:
            w = min(w, x / peak - 1.0)
    return w


def _portfolio(aligned, *, fast, slow, regime, atr_lb, chand_lb, combine_vol, ppy):
    """LONG book: per-coin TrendFollow vol-parity sleeve + inverse_vol_corr combine + breadth-OR 大盘闸."""
    sleeves = {}
    for s in aligned:
        r = run_directional(aligned[s], TrendFollow(fast=fast, slow=slow, allow_short=False,
                            regime_sma=regime), initial_capital=CAP, taker_fee=F, slippage=S,
                            rebalance_band=0.25, vol_target=0.03, max_leverage=2.0, vol_lookback=atr_lb,
                            chandelier_mult=8.0, chandelier_lookback=chand_lb, periods_per_year=ppy)
        sleeves[s] = r.equity_curve
    port = combine(sleeves, scheme="inverse_vol_corr", vol_lookback=combine_vol, initial_capital=CAP)
    # breadth-OR 大盘闸 (BTC>SMA regime OR ≥50% coins>own SMA regime)
    n = len(port)
    btc = sma_regime_mask([b.close for b in aligned["BTCUSDT"]], regime)
    per = [sma_regime_mask([b.close for b in aligned[s]], regime) for s in aligned]
    mask = [btc[t] or (sum(1 for m in per if m[t]) / len(per) >= 0.5) for t in range(n)]
    gated = [CAP]
    for t in range(len(port) - 1):
        r = (port[t + 1] / port[t] - 1.0) if (mask[t] and port[t] > 0) else 0.0
        gated.append(gated[-1] * (1.0 + r))
    return gated


def _stats(dates, c, ppy):
    i = next((k for k, d in enumerate(dates) if d[:4] >= "2024"), len(c))
    tr = sharpe_of(c[:i], periods_per_year=ppy) if i >= 2 else 0.0
    te = sharpe_of(c[i:], periods_per_year=ppy) if len(c) - i >= 2 else 0.0
    return c[-1] / c[0] - 1.0, sharpe_of(c, periods_per_year=ppy), _maxdd(c), tr, te


def main() -> int:
    print("X4 刷新频率: 日线信号 vs 4h 信号(同一套 200/20/60-DAY 经济信号,无 funding)\n")
    d1 = _load("1d")
    d4 = _load("4h")
    dates1 = [b.date for b in d1["BTCUSDT"]]
    dates4 = [b.date for b in d4["BTCUSDT"]]
    print(f"  1d: {len(dates1)} bars   4h: {len(dates4)} bars   ({len(d1)} coins)\n")

    daily = _portfolio(d1, fast=20, slow=60, regime=200, atr_lb=14, chand_lb=22, combine_vol=30, ppy=365.0)
    h4 = _portfolio(d4, fast=120, slow=360, regime=1200, atr_lb=84, chand_lb=132, combine_vol=180, ppy=2190.0)

    print(f"  {'刷新粒度':<22} {'total':>9} {'Sharpe':>7} {'maxDD':>8} {'train':>7} {'test':>7}")
    for label, c, dts, ppy in (("日线(现状,~24h 滞后)", daily, dates1, 365.0),
                               ("4h(~4h 滞后)", h4, dates4, 2190.0)):
        s = _stats(dts, c, ppy)
        print(f"  {label:<22} {s[0]:>+8.1%} {s[1]:>7.2f} {s[2]:>+8.1%} {s[3]:>7.2f} {s[4]:>7.2f}")
    print("\n  解读:total/maxDD 可直接比;Sharpe 已各自年化可比.4h≈日线 → 刷新滞后不是约束(信号本就日线级,")
    print("  早动 ~20h 的收益被多出的近-crossing whipsaw 抵消);4h 明显更优 → 值得上 intraday 刷新.")
    print("  注:两边均未计 funding(≈ −2pp/yr 共同拖累);4h taker 触发次数更多,已扣 5bp+2bp/笔.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
