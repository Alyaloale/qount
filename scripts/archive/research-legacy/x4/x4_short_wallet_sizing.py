#!/usr/bin/env python3
"""X4 做空侧本金口径回测 — marginBalance vs walletBalance (线 D, docs/x4-live-position-management.md §8.3①).

挂载点 (问题): live 的 auto 本金 = marginBalance (含未实现盈亏). 在**做空书**上这是"逆向顺周期":
空头赚钱(价跌) -> equity 涨 -> 目标名义涨 -> 对赢钱的空头加仓, 而那往往接近底部/均值回归区 (逆风的
金字塔); 被逼空时反而自动减仓. 候选修复 = 做空侧 sizing 改用 walletBalance (已实现口径, 不含浮盈) ->
开仓浮盈不再喂回仓位 -> 不在探底区加仓. 但它对称: 也拿掉了浮亏时的保护性减仓 (逼空里不再自动降险).

唯一变量 = 做空书 sleeve 的 sizing 本金口径 (run_directional(wallet_sizing=)). 多头书在两臂里完全
一致 (始终 margin sizing) -> 差异纯粹来自空头侧. 复用 x4_short_gate.py 的载入/闸/拼接原语, 不动引擎逻辑.

配置 = §24 可部署中心 / live LiveConfig 做空默认: ShortTrend(fast20/slow100/regime100) + 止损 3×ATR
+ size 2%/1.5x. 长书 = x4_short_gate 同口径 (slow100, 止损 8×) 以便基线与 §24 已发表数对账
(caveat: live 多头 slow 已 60, 但多头书是两臂共模, 不影响本对比).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.legacy.x4.backtest import run_directional  # noqa: E402
from qount.legacy.x4.portfolio import combine, sharpe_of  # noqa: E402

# 复用 x4_short_gate 的全部 fixture (载入/funding/闸/拼接/指标) + ShortTrend + 常量
from x4_short_gate import (  # noqa: E402
    CAPITAL, F, S, S3, SHORT_CONSERV, LONG_SIZE, TrendFollow, ShortTrend,
    _load, _funding_by_sym, _master_mask, _splice, _shut_compound, _maxdd, _yearly,
)

# §24 可部署中心 / live 做空默认
SHORT_CFG = dict(fast=20, slow=100, regime_sma=100, slope_lookback=0)
SHORT_CHANDELIER = 3.0
SPLIT = "2024"   # train ≤2023-12-31 / test ≥2024-01-01


def _short_sleeves(aligned, fmap, *, wallet_sizing):
    """空头 sleeve (每币 run_directional) — 返回 (combine 后的组合净值, 总成交笔数)."""
    sleeves, trades = {}, 0
    for s in aligned:
        res = run_directional(
            aligned[s], ShortTrend(**SHORT_CFG), initial_capital=CAPITAL, taker_fee=F, slippage=S,
            rebalance_band=0.25, chandelier_mult=SHORT_CHANDELIER, chandelier_lookback=22,
            funding=fmap.get(s), periods_per_year=365.0, wallet_sizing=wallet_sizing, **SHORT_CONSERV)
        sleeves[s] = res.equity_curve
        trades += res.trade_count
    port = combine(sleeves, scheme="inverse_vol_corr", vol_lookback=30, initial_capital=CAPITAL)
    return port, trades


def _train_test_sharpe(dates, curve):
    idx = next((i for i, d in enumerate(dates) if d[:4] >= SPLIT), len(curve))
    tr = sharpe_of(curve[:idx], periods_per_year=365.0) if idx >= 2 else 0.0
    te = sharpe_of(curve[idx:], periods_per_year=365.0) if len(curve) - idx >= 2 else 0.0
    return tr, te


def _stats(dates, curve):
    tot = curve[-1] / curve[0] - 1.0
    return tot, sharpe_of(curve, periods_per_year=365.0), _maxdd(curve), *_train_test_sharpe(dates, curve)


def main() -> int:
    aligned = _load()
    fmap = _funding_by_sym()
    dates = [b.date for b in aligned["BTCUSDT"]]
    n = len(dates)
    mask = _master_mask(aligned)
    shut_frac = 1.0 - sum(mask[:-1]) / (n - 1)
    print(f"X4 做空侧本金口径: marginBalance vs walletBalance  {dates[0]}..{dates[-1]}  "
          f"({n} bars, {len(aligned)} coins)  闸 SHUT 占比 {shut_frac:.0%}")
    print(f"  做空配置 = {SHORT_CFG} + 止损{SHORT_CHANDELIER:.0f}×ATR + size {SHORT_CONSERV}\n")

    # --- 多头书 (两臂共模, 始终 margin sizing = 现状) ---
    long_sleeves = {}
    for s in aligned:
        long_sleeves[s] = run_directional(
            aligned[s], TrendFollow(allow_short=False, **S3), initial_capital=CAPITAL, taker_fee=F,
            slippage=S, rebalance_band=0.25, chandelier_mult=8.0, chandelier_lookback=22,
            funding=fmap.get(s), periods_per_year=365.0, **LONG_SIZE).equity_curve
    long_port = combine(long_sleeves, scheme="inverse_vol_corr", vol_lookback=30, initial_capital=CAPITAL)

    # --- 两臂: 空头书 margin vs wallet ---
    arms = {}
    for label, wallet in (("margin (现状/含浮盈)", False), ("wallet (已实现/不含浮盈)", True)):
        sp, trades = _short_sleeves(aligned, fmap, wallet_sizing=wallet)
        spliced = _splice(long_port, sp, mask, short_on=True)            # 拼进总账 (闸SHUT→空头)
        shut_ret, shut_bars = _shut_compound(sp, mask, 0, n)            # 空头在 SHUT 段的净贡献
        arms[label] = dict(spliced=spliced, short_port=sp, trades=trades,
                           shut_ret=shut_ret, shut_bars=shut_bars)

    # 现状基线 (闸SHUT→现金, 无空头) 作参照
    base_cash = _splice(long_port, long_port, mask, short_on=False)

    print("  ===== 拼进总账 (多头书 + 闸SHUT时空头书) =====")
    print(f"  {'本金口径':<24} {'total':>9} {'Sharpe':>7} {'maxDD':>8} {'train':>7} {'test':>7} {'空头笔数':>8}")
    bt = _stats(dates, base_cash)
    print(f"  {'现状(闸SHUT→现金,无空头)':<24} {bt[0]:>+8.1%} {bt[1]:>7.2f} {bt[2]:>+8.1%} {bt[3]:>7.2f} {bt[4]:>7.2f} {'—':>8}")
    for label, a in arms.items():
        st = _stats(dates, a["spliced"])
        print(f"  {label:<24} {st[0]:>+8.1%} {st[1]:>7.2f} {st[2]:>+8.1%} {st[3]:>7.2f} {st[4]:>7.2f} {a['trades']:>8}")

    print("\n  ===== 空头书本体 (combine, 独立看不拼多头) =====")
    print(f"  {'本金口径':<24} {'total':>9} {'Sharpe':>7} {'maxDD':>8} {'SHUT段净贡献':>12} {'空头笔数':>8}")
    for label, a in arms.items():
        sp = a["short_port"]
        tot, sh, dd = sp[-1] / sp[0] - 1.0, sharpe_of(sp, periods_per_year=365.0), _maxdd(sp)
        print(f"  {label:<24} {tot:>+8.1%} {sh:>7.2f} {dd:>+8.1%} {a['shut_ret']:>+11.1%} {a['trades']:>8}  ({a['shut_bars']} SHUT bars)")

    print("\n  逐年 (总账, 空头侧 margin vs wallet):")
    ym = _yearly(dates, arms["margin (现状/含浮盈)"]["spliced"])
    yw = _yearly(dates, arms["wallet (已实现/不含浮盈)"]["spliced"])
    for y in sorted(ym):
        print(f"    {y}  margin {ym[y]:>+7.1%}   wallet {yw[y]:>+7.1%}")

    print("\n  判据 = wallet 是否在 ① SHUT 段净贡献/Sharpe ② maxDD ③ train且test双段 上不劣于 margin.")
    print("  注: 多头书两臂共模; 唯一变量=空头 sleeve 本金口径. wallet 同时去掉浮盈加仓与浮亏减仓 (对称).")
    print("      换手用空头总笔数代理 (wallet<margin = 少了浮盈触发的加仓). taker+滑点+funding 已扣.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
