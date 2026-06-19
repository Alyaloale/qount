#!/usr/bin/env python3
"""X4 出场/锁利优化面板 — 现状宽 8× vs 浮盈条件收紧 vs 分批止盈 (线 D, docs/x4-live-position-management.md §8).

挂载点 (owner 痛点): 多头出场是二元的 (信号掉→全平 / chandelier→全平+latch), 且 chandelier 宽 8×ATR
(≈峰值回撤 28% 才走) -> 一笔趋势可 +100% 回吐 28% 才出场 = "利润到手了又没了". 没有分批止盈/浮盈锁利.
本面板回测两条对症候选, 与现状宽 8× 同口径对照:

  ① 浮盈条件化收紧: 入场仍宽 8× (不丢 whipsaw 保护), 浮盈≥阈值后切紧 Y×ATR 锁利
     (run_directional(profit_lock_threshold=, profit_lock_mult=)).
  ② 分批止盈: 浮盈每 +step 永久减 frac, 留 residual 残仓继续 trail (scale_out_step/frac/residual).

基线 = 多头书 (= live 全配置: breadth-OR 闸 + 相关性惩罚 + chandelier 8×, vt3%/2x, funding-adjusted),
闸 SHUT→现金. 复用 x4_short_gate.py 的载入/闸/拼接原语 -> 基线由构造对齐 §24 的 +142.0%/0.91/−28.2%.
唯一变量 = 多头 sleeve 的出场参数. taker+滑点+funding 已扣. train(≤2023)/test(≥2024) 双段防过拟合.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.x4.backtest import run_directional  # noqa: E402
from qount.x4.portfolio import combine, sharpe_of  # noqa: E402

from x4_short_gate import (  # noqa: E402
    CAPITAL, F, S, S3, LONG_SIZE, TrendFollow,
    _load, _funding_by_sym, _master_mask, _splice, _maxdd, _yearly,
)

SPLIT = "2024"
BASE_CH = 8.0   # 现状多头宽 chandelier


def _long_port(aligned, fmap, *, chandelier_mult=BASE_CH, **exit_kw):
    """多头书 (per-coin run_directional + inverse_vol_corr combine). exit_kw = 出场优化参数."""
    sleeves, trades, exits, scouts = {}, 0, 0, 0
    for s in aligned:
        res = run_directional(
            aligned[s], TrendFollow(allow_short=False, **S3), initial_capital=CAPITAL, taker_fee=F,
            slippage=S, rebalance_band=0.25, chandelier_mult=chandelier_mult, chandelier_lookback=22,
            funding=fmap.get(s), periods_per_year=365.0, **LONG_SIZE, **exit_kw)
        sleeves[s] = res.equity_curve
        trades += res.trade_count
        exits += res.extra.get("chandelier_exits", 0)
        scouts += res.extra.get("scale_outs", 0)
    port = combine(sleeves, scheme="inverse_vol_corr", vol_lookback=30, initial_capital=CAPITAL)
    return port, trades, exits, scouts


def _stats(dates, curve):
    tot = curve[-1] / curve[0] - 1.0
    idx = next((i for i, d in enumerate(dates) if d[:4] >= SPLIT), len(curve))
    tr = sharpe_of(curve[:idx], periods_per_year=365.0) if idx >= 2 else 0.0
    te = sharpe_of(curve[idx:], periods_per_year=365.0) if len(curve) - idx >= 2 else 0.0
    return tot, sharpe_of(curve, periods_per_year=365.0), _maxdd(curve), tr, te


def main() -> int:
    aligned = _load()
    fmap = _funding_by_sym()
    dates = [b.date for b in aligned["BTCUSDT"]]
    n = len(dates)
    mask = _master_mask(aligned)
    print(f"X4 出场/锁利面板 (funding-adjusted)  {dates[0]}..{dates[-1]}  ({n} bars, {len(aligned)} coins)\n")

    # 配置面板: (label, chandelier_mult, exit_kw)
    configs = [
        ("现状 宽8× (基线)", BASE_CH, {}),
    ]
    # ① 浮盈条件化收紧: 入场宽8×, 浮盈≥阈值切紧 Y×
    for thr in (0.15, 0.25, 0.40):
        for ym in (3.0, 4.0, 5.0):
            configs.append((f"①锁利 +{thr:.0%}→{ym:.0f}×", BASE_CH,
                            dict(profit_lock_threshold=thr, profit_lock_mult=ym)))
    # ② 分批止盈: 每 +step 减 frac, 留 residual (1/3), 残仓仍 8× trail
    for step in (0.20, 0.30):
        for frac in (0.33, 0.50):
            configs.append((f"②分批 每+{step:.0%}减{frac:.0%}", BASE_CH,
                            dict(scale_out_step=step, scale_out_frac=frac, scale_out_residual=0.34)))

    print(f"  {'配置':<22} {'total':>9} {'Sharpe':>7} {'maxDD':>8} {'train':>7} {'test':>7} "
          f"{'笔数':>6} {'止损/分批':>9}")
    base_row = None
    for label, chm, kw in configs:
        lp, trades, exits, scouts = _long_port(aligned, fmap, chandelier_mult=chm, **kw)
        spliced = _splice(lp, lp, mask, short_on=False)   # 闸SHUT→现金 (= 多头书全账)
        st = _stats(dates, spliced)
        if base_row is None:
            base_row = st
        diag = f"{exits}/{scouts}"
        print(f"  {label:<22} {st[0]:>+8.1%} {st[1]:>7.2f} {st[2]:>+8.1%} {st[3]:>7.2f} {st[4]:>7.2f} "
              f"{trades:>6} {diag:>9}")

    bt, bs, bd, btr, bte = base_row
    print(f"\n  基线 = {bt:+.1%}/{bs:.2f}/maxDD {bd:+.1%} (train {btr:.2f}/test {bte:.2f}); "
          f"对账 §24 现状 +142.0%/0.91/−28.2%.")
    print("  判据: 出场优化要 ① 改善 maxDD/给回吐 ② Sharpe 不劣 ③ train且test双段不劣 才算增量;")
    print("        趋势策略先验=分批止盈砍肥尾→总收益降, 多半是风控旋钮非 alpha. 笔数/分批列看换手代价.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
