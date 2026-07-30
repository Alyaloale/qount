#!/usr/bin/env python3
"""X4 轻量 ADX 趋势强度门 — walk-forward 验证(线 D §12 候选上线前的稳健性关).

§12 面板发现 adx_min 12-16 是平台:总收益持平、Sharpe +0.03、maxDD −26→−21.5~22.7%、train/test 双段不劣,
修正了旧「ADX≥20 非 alpha」。但它翻转了既有结论 → 上 live 前必须 walk-forward 验稳:
  (A) 逐 fold 一致性:固定 adx14 vs 基线(adx0),看 maxDD/Sharpe 改善是否跨 OOS 折稳定(不是单一 regime).
  (B) 真 walk-forward:每折在 train 窗用 Sharpe 选 adx_min,应用到紧随其后的 test 窗(OOS),看 ① 选出的
      adx 是否稳定落在 ~12-16 ② OOS 是否打过基线 adx0.

LONG 组合 = live 全配置(slow60/vt3%/lev2/band.25/chand8 + breadth-OR + corr,funding-adjusted).滚动窗
train=504 bar(~2y)/ test=126 bar(~6mo)/ step=126.全程跑满 curve 再按日期切折(SMA200 暖机不破).
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

CANDS = [0, 10, 12, 14, 16, 18, 20]
FIXED = 14
TRAIN, TEST, STEP, WARM = 504, 126, 126, 260
BASE = dict(fast=20, slow=60, regime_sma=200, weighting="inverse_vol_corr", vol_lookback=30,
            master_gate_sym="BTCUSDT", master_gate_sma=200, breadth_gate=0.5, breadth_combine="or",
            vol_target=0.03, max_leverage=2.0, rebalance_band=0.25, chandelier_mult=8.0,
            chandelier_lookback=22, periods_per_year=365.0)


def _slice_stats(curve, a, b):
    sub = curve[a:b + 1]
    if len(sub) < 3:
        return 0.0, 0.0, 0.0
    return sub[-1] / sub[0] - 1.0, sharpe_of(sub, periods_per_year=365.0), _maxdd(sub)


def main() -> int:
    aligned = _load(); fmap = _funding_by_sym(); dates = [b.date for b in aligned["BTCUSDT"]]
    n = len(dates)
    print(f"X4 ADX 门 walk-forward  {dates[0]}..{dates[-1]}  ({n} bars)  "
          f"train {TRAIN}/test {TEST}/step {STEP}\n")

    curves = {a: run_trend_portfolio(aligned, funding_by_sym=fmap, **{**BASE, "adx_min": float(a)}).equity_curve
              for a in CANDS}

    folds = []
    t0 = WARM
    while t0 + TRAIN + TEST <= n:
        folds.append((t0, t0 + TRAIN, t0 + TRAIN + TEST))
        t0 += STEP

    print(f"  {'OOS 折':<20} {'选 adx':>6} {'WF test SR':>11} {'base SR':>8} {'adx14 SR':>9} "
          f"{'base DD':>8} {'adx14 DD':>9}")
    agg = {"wf": [], "base": [], "f14": [], "wf_win": 0, "dd_base": [], "dd_14": [], "sel": []}
    for (a, b, c) in folds:
        # (B) pick adx on TRAIN sharpe
        tr_sr = {k: _slice_stats(curves[k], a, b)[1] for k in CANDS}
        sel = max(CANDS, key=lambda k: tr_sr[k])
        wf_ret, wf_sr, wf_dd = _slice_stats(curves[sel], b, c)
        b_ret, b_sr, b_dd = _slice_stats(curves[0], b, c)
        f_ret, f_sr, f_dd = _slice_stats(curves[FIXED], b, c)
        agg["wf"].append(wf_sr); agg["base"].append(b_sr); agg["f14"].append(f_sr)
        agg["dd_base"].append(b_dd); agg["dd_14"].append(f_dd); agg["sel"].append(sel)
        agg["wf_win"] += 1 if wf_sr >= b_sr else 0
        lbl = f"{dates[b][:7]}..{dates[c-1][:7]}"
        print(f"  {lbl:<20} {sel:>6} {wf_sr:>11.2f} {b_sr:>8.2f} {f_sr:>9.2f} {b_dd:>+8.1%} {f_dd:>+9.1%}")

    k = len(folds)
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    print(f"\n  折数 {k}")
    print(f"  平均 OOS Sharpe   WF-selected {mean(agg['wf']):.2f}  | 基线(adx0) {mean(agg['base']):.2f}  "
          f"| 固定 adx14 {mean(agg['f14']):.2f}")
    print(f"  平均 OOS maxDD    基线 {mean(agg['dd_base']):+.1%}  | 固定 adx14 {mean(agg['dd_14']):+.1%}")
    print(f"  WF-selected ≥ 基线 的折: {agg['wf_win']}/{k}")
    f14_win = sum(1 for f, b in zip(agg['f14'], agg['base']) if f >= b)
    dd_win = sum(1 for d14, db in zip(agg['dd_14'], agg['dd_base']) if d14 >= db)  # >= 即 DD 更浅(负值更大)
    print(f"  固定 adx14 Sharpe ≥ 基线 的折: {f14_win}/{k};  maxDD 不更深 的折: {dd_win}/{k}")
    from collections import Counter
    print(f"  WF 选出的 adx 分布: {dict(sorted(Counter(agg['sel']).items()))}")
    print("\n  判据:① 固定 adx14 跨折 maxDD 多数不更深且 Sharpe 不劣 = 风险质量稳健;② WF-selected 多数选 ~10-16")
    print("        且 OOS≥基线 = ADX 可 OOS 选择.两者都过 → 上 live(默认关 env arm).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
