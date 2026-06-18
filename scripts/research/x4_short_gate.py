#!/usr/bin/env python3
"""X4 做空闸 (short gate) 验证 — 大盘反转闸 (语义 A, docs/crypto-x4-plan.md §22 预注册).

现状: live 是 long-only + 大盘闸. 总闸 SHUT (BTC<200SMA 且 breadth 窄 = 真熊) 时全仓现金
(run_trend_portfolio lines 595-605: 闸 SHUT 那步收益置 0). S7 砍不掉的 −30% 尾 = "crypto-beta
一起跌" — 单向策略熊市只能躲现金. 做空闸 = 把那段"死现金"换成镜像空头组合, 直接对冲 beta 尾.

杀线 (kill question): 在闸 SHUT 的 risk-off bar 上, 用空头组合的收益替换现金(0), 是否
  ① 真把 maxDD/−30% 尾砍下来 (空头价值在尾对冲, 非 alpha);
  ② 整轮 Sharpe 不被空头负 carry / 逼空右尾拖垮 (中性偏正即可接受).
若两条都不过 = 做空闸证伪, 维持熊市走现金.

诚实口径 (三个结构性逆风, 必须计入):
  * funding: 永续空头 RECEIVES 正 funding (longs pay shorts) — engine accrue_funding 已带符号,
    短腿 funding 是收入侧, 这里如实喂真实 funding 序列 (非 0).
  * 逼空右尾: 熊市反弹又快又猛, 2x 空头 +50% 爆. ⚠️ engine 的 chandelier 只保护多头
    (backtest.py:131-147 仅 was_long), 所以短腿这里 chandelier=OFF = 无保护 = 最保守/最坏 squeeze
    情形. 若无保护仍能砍尾, 加对称止损只会更好; 若 squeeze 尾吃光, 那才是真发现.
  * 长期上漂: crypto 正 drift, 空头平均负 carry — 体现在 short_port 自身曲线.

不动引擎 (owner: 先验证后实现): 全部用 run_directional / combine 原语在脚本内组装, 并把 long 基线
精确钉死到 run_trend_portfolio (断言一致), 确保唯一变量 = "闸 SHUT 那步: 现金 vs 空头".

Read-only; writes no state.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.grid.data import Bar, load_funding, load_klines  # noqa: E402
from qount.x4.backtest import run_directional, run_trend_portfolio  # noqa: E402
from qount.x4.portfolio import combine, sharpe_of  # noqa: E402
from qount.x4.strategies import TrendFollow, sma_regime_mask  # noqa: E402

START = (2021, 1)
END = (2026, 6)
CAPITAL = 100_000.0
UNIVERSE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]  # live TOP7
F, S = 0.0005, 0.0002          # taker fee + slippage (= live)
GATE_SMA = 200
BREADTH = 0.5                  # breadth-OR 闸 (= live default)
S3 = dict(fast=20, slow=100, regime_sma=200)
LONG_SIZE = dict(vol_target=0.03, max_leverage=2.0)       # = live 博收益档 (vt3)
# 短腿尺寸: headline = 与多头对称(3%/2x); 保守变体 = 更小(逼空尾更脆)
SHORT_SYMMETRIC = dict(vol_target=0.03, max_leverage=2.0)
SHORT_CONSERV = dict(vol_target=0.02, max_leverage=1.5)


class ShortTrend:
    """大盘反转闸的镜像空头 sleeve: 只在熊市 regime 做空, 永不做多.

    INVERTED regime 门 vs :class:`TrendFollow` (后者 close<=SMA200 时多空全禁, strategies.py:101).
    这里: 暖机/close>=SMA_regime -> flat (不在上升趋势里做空); 否则 fast<slow -> -1 (空), 不然 0.
    """

    name = "S3-SHORT"

    def __init__(self, *, fast: int = 20, slow: int = 100, regime_sma: int = 200,
                 slope_lookback: int = 0) -> None:
        if fast < 1 or slow <= fast:
            raise ValueError(f"need 1 <= fast < slow, got fast={fast}, slow={slow}")
        self.fast, self.slow, self.regime_sma = fast, slow, regime_sma
        # slope_lookback>0: 额外要求 regime SMA 本身在下行 (今天 < lookback 天前) — 镜像 long 侧
        # 的 sma_slope_up_mask, 专杀 bear->bull "假反弹" (价格还在 SMA200 下但已掉头向上) 的被逼空.
        self.slope_lookback = slope_lookback
        from collections import deque
        self._closes: deque[float] = deque(maxlen=max(slow, regime_sma + slope_lookback))

    def on_bar(self, bar: Bar) -> float:
        self._closes.append(bar.close)
        need = max(self.slow, self.regime_sma + self.slope_lookback)
        if len(self._closes) < need:
            return 0.0
        closes = list(self._closes)
        sma_r = sum(closes[-self.regime_sma:]) / self.regime_sma
        if bar.close >= sma_r:
            return 0.0  # 上升/盘整 regime: 不做空
        if self.slope_lookback:
            sma_prev = sum(closes[-self.regime_sma - self.slope_lookback:-self.slope_lookback]) / self.regime_sma
            if sma_r >= sma_prev:
                return 0.0  # SMA200 未下行 (假反弹): 不做空
        fast_ma = sum(closes[-self.fast:]) / self.fast
        slow_ma = sum(closes[-self.slow:]) / self.slow
        return -1.0 if fast_ma < slow_ma else 0.0  # 熊 regime 且下穿 -> 空


def _load():
    by = {}
    for s in UNIVERSE:
        bars = load_klines(s, "1d", start=START, end=END, market="um", skip_missing=True)
        if len(bars) > 300:
            by[s] = {b.ts_ms: b for b in bars}
    common = sorted(set.intersection(*(set(d) for d in by.values())))
    return {s: [by[s][t] for t in common] for s in by}


def _funding_by_sym():
    """逐币日 funding callable (8h 费率按日加总). 多头 PAY 正费率, 空头 RECEIVE."""
    out = {}
    for s in UNIVERSE:
        d: dict[int, float] = {}
        for fr in load_funding(s, start=START, end=END, skip_missing=True):
            k = fr.ts_ms // 86_400_000
            d[k] = d.get(k, 0.0) + fr.rate
        out[s] = (lambda dd: (lambda bar: dd.get(bar.ts_ms // 86_400_000, 0.0)))(d)
    return out


def _sleeves(aligned, fmap, strat_factory, size, chandelier_mult):
    sleeves = {}
    for s in aligned:
        res = run_directional(
            aligned[s], strat_factory(), initial_capital=CAPITAL, taker_fee=F, slippage=S,
            rebalance_band=0.25, chandelier_mult=chandelier_mult, chandelier_lookback=22,
            funding=fmap.get(s), periods_per_year=365.0, **size)
        sleeves[s] = res.equity_curve
    return sleeves


def _master_mask(aligned):
    """大盘闸 mask (= run_trend_portfolio 的 breadth-OR): BTC>200SMA OR breadth>=0.5."""
    n = len(aligned["BTCUSDT"])
    btc_mask = sma_regime_mask([b.close for b in aligned["BTCUSDT"]], GATE_SMA)
    per_coin = [sma_regime_mask([b.close for b in aligned[s]], S3["regime_sma"]) for s in aligned]
    out = []
    for t in range(n):
        frac = sum(1 for m in per_coin if m[t]) / len(per_coin)
        out.append(btc_mask[t] or (frac >= BREADTH))
    return out


def _splice(long_port, short_port, mask, *, short_on):
    """逐步拼: mask[t] True (risk-on) -> long step ret; False (risk-off) -> short step (若 short_on) 否则 0(现金)."""
    curve = [CAPITAL]
    for t in range(len(long_port) - 1):
        if mask[t]:
            r = long_port[t + 1] / long_port[t] - 1.0 if long_port[t] > 0 else 0.0
        elif short_on:
            r = short_port[t + 1] / short_port[t] - 1.0 if short_port[t] > 0 else 0.0
        else:
            r = 0.0  # 现金
        curve.append(curve[-1] * (1.0 + r))
    return curve


def _shut_compound(short_port, mask, lo, hi):
    """空头组合在 [lo,hi) 区间内、仅 SHUT bars 上的复利收益 (= 它替换现金那部分的净贡献)."""
    mult, bars = 1.0, 0
    for t in range(lo, min(hi, len(short_port) - 1)):
        if not mask[t]:
            bars += 1
            mult *= short_port[t + 1] / short_port[t] if short_port[t] > 0 else 1.0
    return mult - 1.0, bars


def _short_port(aligned, fmap, *, fast, slow, regime, slope, chmult, size):
    sleeves = _sleeves(
        aligned, fmap,
        lambda: ShortTrend(fast=fast, slow=slow, regime_sma=regime, slope_lookback=slope),
        size, chandelier_mult=chmult)
    return combine(sleeves, scheme="inverse_vol_corr", vol_lookback=30, initial_capital=CAPITAL)


def _maxdd(curve):
    peak, worst = curve[0], 0.0
    for x in curve:
        peak = max(peak, x)
        if peak > 0:
            worst = min(worst, x / peak - 1.0)
    return worst


def _row(curve):
    tot = curve[-1] / curve[0] - 1.0
    return tot, sharpe_of(curve, periods_per_year=365.0), _maxdd(curve)


def _yearly(dates, curve):
    by_year = {}
    for d, e in zip(dates, curve):
        by_year[d[:4]] = e
    out, prev = {}, curve[0]
    for y in sorted(by_year):
        out[y] = by_year[y] / prev - 1.0
        prev = by_year[y]
    return out


def main() -> int:
    aligned = _load()
    fmap = _funding_by_sym()
    dates = [b.date for b in aligned["BTCUSDT"]]
    n = len(dates)
    mask = _master_mask(aligned)
    shut_frac = 1.0 - sum(mask[:-1]) / (n - 1)
    print(f"X4 做空闸验证 (funding-adjusted/诚实)  {dates[0]}..{dates[-1]}  "
          f"({n} bars, {len(aligned)} coins)  闸 SHUT 占比 {shut_frac:.0%}\n")

    # --- LONG book (= live 全配置) + 钉死到 run_trend_portfolio ---
    long_sleeves = _sleeves(aligned, fmap, lambda: TrendFollow(allow_short=False, **S3),
                            LONG_SIZE, chandelier_mult=8.0)
    long_port = combine(long_sleeves, scheme="inverse_vol_corr", vol_lookback=30,
                        initial_capital=CAPITAL)
    base_manual = _splice(long_port, long_port, mask, short_on=False)  # 闸 SHUT -> 现金 = 现状

    canon = run_trend_portfolio(
        aligned, fast=S3["fast"], slow=S3["slow"], regime_sma=S3["regime_sma"],
        weighting="inverse_vol_corr", vol_lookback=30, master_gate_sym="BTCUSDT",
        master_gate_sma=GATE_SMA, breadth_gate=BREADTH, breadth_combine="or",
        initial_capital=CAPITAL, taker_fee=F, slippage=S, rebalance_band=0.25,
        chandelier_mult=8.0, chandelier_lookback=22, funding_by_sym=fmap,
        periods_per_year=365.0, **LONG_SIZE).equity_curve
    rel = max(abs(a / b - 1.0) for a, b in zip(base_manual, canon) if b > 0)
    print(f"  [pin] 手工 long 基线 vs run_trend_portfolio 最大相对偏差 = {rel:.2e} "
          f"({'OK ✓ 钉死' if rel < 1e-6 else '⚠️ 偏离, 拼装与引擎不一致!'})\n")

    # --- SHORT book (闸 SHUT 时启用; chandelier OFF = 无逼空保护 = 最保守) ---
    results = {"现状 (闸SHUT→现金)": base_manual}
    # (label, short size, SMA下行确认 lookback, 短腿对称 chandelier mult — 0=无逼空保护)
    SHORT_VARIANTS = (
        ("做空闸·对称3%/2x·无止损", SHORT_SYMMETRIC, 0, 0.0),
        ("做空闸·保守2%/1.5x·无止损", SHORT_CONSERV, 0, 0.0),
        ("做空闸·保守+SMA下行确认", SHORT_CONSERV, 30, 0.0),   # 零成本杠杆: 杀假反弹被逼空
        ("做空闸·对称+对称止损8x", SHORT_SYMMETRIC, 0, 8.0),   # 对称空头侧 chandelier (灾难/逼空兜底)
        ("做空闸·对称+对称止损3x", SHORT_SYMMETRIC, 0, 3.0),   # 紧止损 (squeeze 早出, 但 whipsaw 趋势)
        ("做空闸·全料(保守+下行+止损3x)", SHORT_CONSERV, 30, 3.0),  # 三杠杆叠加: 最佳可能空头
    )
    for label, size, slope, chmult in SHORT_VARIANTS:
        short_sleeves = _sleeves(aligned, fmap, lambda s=slope: ShortTrend(slope_lookback=s, **S3),
                                 size, chandelier_mult=chmult)
        short_port = combine(short_sleeves, scheme="inverse_vol_corr", vol_lookback=30,
                             initial_capital=CAPITAL)
        results[label] = _splice(long_port, short_port, mask, short_on=True)

    print(f"  {'变体':<22} | {'total':>9} | {'Sharpe':>6} | {'maxDD':>7}")
    print("  " + "-" * 56)
    for name, curve in results.items():
        tot, sh, dd = _row(curve)
        print(f"  {name:<22} | {tot:>+8.1%} | {sh:>6.2f} | {dd:>+7.1%}")

    # risk-off 子区间归因: 闸 SHUT 的 bar 上, 现金(0) vs 空头各贡献多少 (复利乘子)
    print("\n  risk-off (闸SHUT) 子区间 — 只看 SHUT bars 的复利收益:")
    for label, size, slope, chmult in SHORT_VARIANTS:
        short_sleeves = _sleeves(aligned, fmap, lambda s=slope: ShortTrend(slope_lookback=s, **S3),
                                 size, chandelier_mult=chmult)
        sp = combine(short_sleeves, scheme="inverse_vol_corr", vol_lookback=30, initial_capital=CAPITAL)
        mult, bars_off = 1.0, 0
        for t in range(n - 1):
            if not mask[t]:
                bars_off += 1
                mult *= sp[t + 1] / sp[t] if sp[t] > 0 else 1.0
        print(f"    {label:<18} {bars_off} SHUT bars -> 空头复利 {mult - 1.0:+.1%}  (现金=0.0%)")

    # 逐年 + train/test 过拟合检验
    best = max((k for k in results if k != "现状 (闸SHUT→现金)"),
               key=lambda k: sharpe_of(results[k], periods_per_year=365.0))
    print(f"\n  逐年 (现状 vs 最佳空头变体 = {best}):")
    yb, yg = _yearly(dates, results["现状 (闸SHUT→现金)"]), _yearly(dates, results[best])
    print("   现状   " + "  ".join(f"{y}:{v:+.0%}" for y, v in yb.items()))
    print("   做空闸 " + "  ".join(f"{y}:{v:+.0%}" for y, v in yg.items()))

    print("\n  train(≤2023-12-31)/test(≥2024-01-01) Sharpe (过拟合检验):")
    split = next((i for i, d in enumerate(dates) if d >= "2024-01-01"), n)
    for name, curve in results.items():
        tr = sharpe_of(curve[:split], periods_per_year=365.0)
        te = sharpe_of(curve[split:], periods_per_year=365.0)
        print(f"    {name:<22} train {tr:+.2f}  test {te:+.2f}")

    # ---------- 因子参数扫描: 找"空头 SHUT 段不亏"的区域, 但用 train/test 双段防过拟合 ----------
    # owner 命题: 闸 SHUT 时多头在现金(=0), 只要空头那段净≥0 就是白捡 -> 总收益只升.
    # 命题在"收益流"上对; 致命问题="全样本调到≥0" ≠ "前向≥0". 故判据 = train SHUT≥0 AND test SHUT≥0
    # (两段都不亏才是真白捡); 同时看叠上去后 maxDD 是否真没恶化(尾才是 owner 真正在意的).
    print("\n  ===== 因子参数扫描 (目标: 空头 SHUT 段不亏, train/test 双段防过拟合) =====")
    print("  判据: train SHUT≥0 且 test SHUT≥0 = 真白捡; 只 train≥0/test<0 = 过拟合幻觉")
    print(f"  {'fast/slow':>9} {'reg':>3} {'slope':>5} {'stop':>4} {'size':>8} | "
          f"{'train SHUT':>10} {'test SHUT':>9} | {'全段total':>8} {'maxDD':>7} {'判据':>4}")
    print("  " + "-" * 88)
    grids = []
    for (fast, slow) in [(20, 100), (10, 50), (50, 200), (10, 100)]:
        for regime in (200, 100):
            for slope in (0, 30):
                for chmult in (0.0, 3.0, 5.0):
                    for sname, size in (("3%/2x", SHORT_SYMMETRIC), ("2%/1.5x", SHORT_CONSERV)):
                        grids.append((fast, slow, regime, slope, chmult, sname, size))
    rows = []
    for (fast, slow, regime, slope, chmult, sname, size) in grids:
        sp = _short_port(aligned, fmap, fast=fast, slow=slow, regime=regime, slope=slope,
                         chmult=chmult, size=size)
        tr_shut, _ = _shut_compound(sp, mask, 0, split)
        te_shut, _ = _shut_compound(sp, mask, split, n)
        spliced = _splice(long_port, sp, mask, short_on=True)
        tot, _, dd = _row(spliced)
        ok = tr_shut >= 0 and te_shut >= 0
        rows.append((ok, min(tr_shut, te_shut), tr_shut, te_shut, tot, dd,
                     fast, slow, regime, slope, chmult, sname))
    # 先列通过双段判据的(按两段较差者降序=最稳健白捡在前), 再列若干未通过的代表
    passed = sorted([r for r in rows if r[0]], key=lambda r: -r[1])
    failed = sorted([r for r in rows if not r[0]], key=lambda r: -r[1])
    for r in passed + failed[:4]:
        ok, _, tr, te, tot, dd, fast, slow, regime, slope, chmult, sname = r
        flag = "✓白捡" if ok else ("✗过拟" if tr >= 0 > te else "✗双亏")
        print(f"  {f'{fast}/{slow}':>9} {regime:>3} {slope:>5} {chmult:>4.0f} {sname:>8} | "
              f"{tr:>+9.1%} {te:>+8.1%} | {tot:>+7.1%} {dd:>+7.1%} {flag:>4}")
    npass = len(passed)
    print(f"\n  {npass}/{len(grids)} 组通过「train且test双段 SHUT≥0」。现状(熊→现金) maxDD = {_maxdd(base_manual):+.1%}.")
    if npass:
        best = passed[0]
        worse_dd = best[5] < _maxdd(base_manual)
        print(f"  最稳健白捡组两段较差者 {best[1]:+.1%} ≥0 → 收益流确实白捡; 但其 maxDD {best[5]:+.1%}"
              f" {'仍比现状深(尾恶化, 白捡是以更深回撤换的)' if worse_dd else '未超现状(真白捡)'}.")
    else:
        print("  无一组双段不亏 → 「调到不亏」全是 in-sample 幻觉, 前向必亏一段. 命题在 OOS 下不成立.")

    print("\n  注: 对称空头侧 chandelier 已实现 (backtest.py: 多头 trail high-stop / 空头 trail low+squeeze-stop);"
          "\n      funding 已计入(空头收正费率); long→short 书本切换的换手成本未单独建模 (regime flip 罕见, 二阶). taker+滑点已扣.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
