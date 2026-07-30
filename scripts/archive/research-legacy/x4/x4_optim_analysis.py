#!/usr/bin/env python3
"""X4 实盘策略深度优化分析(线 D)— owner 点名四方向:动态杠杆 / 仓位管理 / 趋势判断 / 刷新频率.

复用 x4_short_gate.py 的载入/funding/闸 原语,以 run_trend_portfolio 跑 LONG 组合(= live 全配置:
breadth-OR 闸 + 相关性惩罚 + chandelier 8×,vt3%/2x,slow60,funding-adjusted).基线对账 §24.1 slow=60
档(+173%/1.07/−26%).每个方向用同口径回测,train(≤2023)/test(≥2024) 双段防过拟合.taker+滑点+funding 已扣.

注:已测过(不重复,见 crypto-x4-plan §24 / x4-live-position-management §9-11):chandelier sweep(8× 最优)、
浮盈条件收紧(无 edge)、分批止盈(Sharpe+DD 改善,已上)、T3-8 动态降杠杆(降 DD 非 alpha)、MA200 斜率
(证伪)、ADX(非 alpha)、做空闸(已上)、walletBalance sizing(≈无差).本文只跑「尚未系统扫过」的杠杆/band/
趋势核心参数,给 owner 决策面板.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "research"))

from qount.legacy.x4.backtest import run_trend_portfolio  # noqa: E402
from qount.legacy.x4.portfolio import sharpe_of  # noqa: E402
from x4_short_gate import _load, _funding_by_sym, _maxdd  # noqa: E402

SPLIT = "2024"
# live LONG-side config (= 部署值)
BASE = dict(fast=20, slow=60, regime_sma=200, weighting="inverse_vol_corr", vol_lookback=30,
            master_gate_sym="BTCUSDT", master_gate_sma=200, breadth_gate=0.5, breadth_combine="or",
            vol_target=0.03, max_leverage=2.0, rebalance_band=0.25, chandelier_mult=8.0,
            chandelier_lookback=22, periods_per_year=365.0)


def _run(aligned, fmap, dates, **over):
    cfg = dict(BASE); cfg.update(over)
    r = run_trend_portfolio(aligned, funding_by_sym=fmap, **cfg)
    c = r.equity_curve
    i = next((k for k, d in enumerate(dates) if d[:4] >= SPLIT), len(c))
    tr = sharpe_of(c[:i], periods_per_year=365.0) if i >= 2 else 0.0
    te = sharpe_of(c[i:], periods_per_year=365.0) if len(c) - i >= 2 else 0.0
    return (c[-1] / c[0] - 1.0, r.sharpe, _maxdd(c), tr, te,
            r.extra.get("gate_active_frac", 0.0))


def _row(label, s):
    print(f"  {label:<26} {s[0]:>+8.1%} {s[1]:>7.2f} {s[2]:>+8.1%} {s[3]:>7.2f} {s[4]:>7.2f}")


def main() -> int:
    aligned = _load(); fmap = _funding_by_sym(); dates = [b.date for b in aligned["BTCUSDT"]]
    print(f"X4 优化分析 (funding-adjusted)  {dates[0]}..{dates[-1]}  ({len(dates)} bars, {len(aligned)} coins)\n")
    base = _run(aligned, fmap, dates)
    hdr = f"  {'配置':<26} {'total':>8} {'Sharpe':>7} {'maxDD':>8} {'train':>7} {'test':>7}"

    print("══ 基线 (= live LONG 配置 slow60/vt3%/lev2/band.25/chand8) ══")
    print(hdr); _row("BASELINE", base)
    print(f"  (对账 §24.1 slow=60 ≈ +173%/1.07/−26%; gate_active {base[5]:.0%})\n")

    print("══ ① 动态杠杆 — vol_target 前沿 (杠杆真旋钮) + max_leverage cap (验惰性) ══")
    print(hdr)
    for vt in (0.02, 0.025, 0.03, 0.035, 0.04):
        _row(f"vol_target {vt}", _run(aligned, fmap, dates, vol_target=vt))
    for lev in (1.5, 2.0, 3.0):
        _row(f"max_leverage {lev} (vt3%)", _run(aligned, fmap, dates, max_leverage=lev))
    print()

    print("══ ① 动态杠杆 — 组合回撤降杠杆 T3-8 (已知:降 DD 非 alpha,复核) ══")
    print(hdr)
    for thr, dvt in ((0.15, 0.02), (0.20, 0.02), (0.15, 0.015)):
        _row(f"dd>{thr:.0%}→vt{dvt}", _run(aligned, fmap, dates,
                                          dd_derisk_threshold=thr, dd_derisk_vol_target=dvt))
    print()

    print("══ ② 仓位管理 — rebalance_band 扫描 (换手 vs 跟踪,未系统扫过) ══")
    print(hdr)
    for band in (0.0, 0.1, 0.25, 0.4, 0.6):
        _row(f"band {band}", _run(aligned, fmap, dates, rebalance_band=band))
    print()

    print("══ ③ 趋势判断 — slow MA 扫描 (复核 60) + regime_sma 扫描 ══")
    print(hdr)
    for slow in (40, 50, 60, 80, 100):
        _row(f"slow {slow}", _run(aligned, fmap, dates, slow=slow))
    for reg in (150, 200, 250):
        _row(f"regime_sma {reg}", _run(aligned, fmap, dates, regime_sma=reg))
    print()

    print("══ ③ 趋势判断 — ADX 趋势强度过滤 (已知非 alpha,复核) ══")
    print(hdr)
    for adx in (15.0, 20.0, 25.0):
        _row(f"adx_min {adx}", _run(aligned, fmap, dates, adx_min=adx))
    print()

    print("══ ③ 趋势判断 — breadth 闸阈值 (gate 松紧) ══")
    print(hdr)
    for bg in (0.3, 0.4, 0.5, 0.6):
        _row(f"breadth_gate {bg}", _run(aligned, fmap, dates, breadth_gate=bg))
    print()

    print("判据:增量须 ① Sharpe 不劣 ② train且test双段不劣 ③ maxDD 不恶化 (2x 永续尾敏感).")
    print("已测过的方向(分批止盈/斜率/做空闸/walletBalance)见文档,不在此重复.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
