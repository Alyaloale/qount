#!/usr/bin/env python3
"""X4 universe 多样化 — walk-forward 验证(线 D).

live 跑固定 TOP7,但 bake-off 的 S7 命题是「分散 > 选择」(§19,14 币 Sharpe 0.88 打过更少币).缺口:把
LONG 书的 universe 从 TOP7 扩到更宽(加有完整 2021 历史的流动山寨),OOS 是否真改善 Sharpe/maxDD?吸取
ADX 教训——**这次 walk-forward 内建**:全样本 + 9 滚动 OOS 折逐折比,broader vs TOP7,看改善是否跨折稳定.

LONG 组合 = live 配置(slow60/vt3%/lev2/band.25/chand8 + breadth-OR + corr,funding-adjusted),唯一变量
= universe 成分.每个 universe 各自跑满 curve 再按日期切折(BTC 闸/暖机不破).⚠️ 这是「universe 够本金时
值不值得扩」的研究,不是说 $491 现在就能持 14 币(小本金多数山寨够不到最小下单额=另一层约束).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "research"))

from qount.grid.data import load_klines, load_funding  # noqa: E402
from qount.x4.backtest import run_trend_portfolio  # noqa: E402
from qount.x4.portfolio import sharpe_of  # noqa: E402
from x4_short_gate import _maxdd  # noqa: E402

TOP7 = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT"]
# broader candidates filled in from the availability check (full 2021 history only)
ADD = ["DOGEUSDT", "LTCUSDT", "BCHUSDT", "ETCUSDT", "DOTUSDT", "AVAXUSDT", "UNIUSDT",
       "ATOMUSDT", "FILUSDT", "TRXUSDT", "EOSUSDT", "XLMUSDT"]
TRAIN, TEST, STEP, WARM = 504, 126, 126, 260
BASE = dict(fast=20, slow=60, regime_sma=200, weighting="inverse_vol_corr", vol_lookback=30,
            master_gate_sym="BTCUSDT", master_gate_sma=200, breadth_gate=0.5, breadth_combine="or",
            vol_target=0.03, max_leverage=2.0, rebalance_band=0.25, chandelier_mult=8.0,
            chandelier_lookback=22, periods_per_year=365.0)


def _load_many(syms):
    raw = {}
    for s in syms:
        b = load_klines(s, "1d", start=(2021, 1), end=(2026, 6), market="um", skip_missing=True)
        if len(b) > 1800 and b[0].date <= "2021-02-01":
            raw[s] = {x.ts_ms: x for x in b}
    common = sorted(set.intersection(*(set(d) for d in raw.values())))
    return {s: [raw[s][t] for t in common] for s in raw}, common


def _funding(syms, common_ts):
    out = {}
    for s in syms:
        d = {}
        for fr in load_funding(s, start=(2021, 1), end=(2026, 6), skip_missing=True):
            k = fr.ts_ms // 86_400_000
            d[k] = d.get(k, 0.0) + fr.rate
        out[s] = (lambda dd: (lambda bar: dd.get(bar.ts_ms // 86_400_000, 0.0)))(d)
    return out


def _slice(curve, a, b):
    sub = curve[a:b + 1]
    if len(sub) < 3:
        return 0.0, 0.0, 0.0
    return sub[-1] / sub[0] - 1.0, sharpe_of(sub, periods_per_year=365.0), _maxdd(sub)


def main() -> int:
    full, common = _load_many(TOP7 + ADD)
    avail = list(full)
    # build aligned dicts on the SHARED timeline so folds line up across universes
    dates = [full[avail[0]][i].date for i in range(len(common))]
    n = len(dates)
    fmap = _funding(avail, common)
    print(f"X4 universe walk-forward  {dates[0]}..{dates[-1]}  ({n} bars)  可用 {len(avail)} 币\n")

    universes = {
        "TOP7 (现状)": TOP7,
        "TOP10": TOP7 + ["DOGEUSDT", "LTCUSDT", "DOTUSDT"],
        f"ALL{len(avail)}": avail,
    }
    curves = {}
    print(f"  {'universe':<14} {'#币':>3} {'total':>9} {'Sharpe':>7} {'maxDD':>8} {'train':>7} {'test':>7}")
    for name, u in universes.items():
        u = [s for s in u if s in full]
        sub = {s: full[s] for s in u}
        r = run_trend_portfolio(sub, funding_by_sym={s: fmap[s] for s in u}, **BASE)
        c = r.equity_curve; curves[name] = c
        i = next((k for k, d in enumerate(dates) if d[:4] >= "2024"), len(c))
        tr = sharpe_of(c[:i], periods_per_year=365.0); te = sharpe_of(c[i:], periods_per_year=365.0)
        print(f"  {name:<14} {len(u):>3} {c[-1]/c[0]-1:>+8.1%} {r.sharpe:>7.2f} {_maxdd(c):>+8.1%} "
              f"{tr:>7.2f} {te:>7.2f}")

    # walk-forward: per OOS fold, broader vs TOP7
    folds = []
    t0 = WARM
    while t0 + TRAIN + TEST <= n:
        folds.append((t0 + TRAIN, t0 + TRAIN + TEST)); t0 += STEP
    base_name = "TOP7 (现状)"; broad = f"ALL{len(avail)}"
    print(f"\n  walk-forward OOS 折 ({len(folds)} 折): {broad} vs {base_name}")
    print(f"  {'OOS 折':<20} {'b SR':>6} {'7 SR':>6} {'b DD':>8} {'7 DD':>8}")
    sr_b, sr_7, dd_b, dd_7, sw, dw = [], [], [], [], 0, 0
    for (a, b) in folds:
        _, s_b, d_b = _slice(curves[broad], a, b)
        _, s_7, d_7 = _slice(curves[base_name], a, b)
        sr_b.append(s_b); sr_7.append(s_7); dd_b.append(d_b); dd_7.append(d_7)
        sw += 1 if s_b >= s_7 else 0; dw += 1 if d_b >= d_7 else 0
        print(f"  {dates[a][:7]}..{dates[b-1][:7]:<8} {s_b:>6.2f} {s_7:>6.2f} {d_b:>+8.1%} {d_7:>+8.1%}")
    m = lambda x: sum(x) / len(x)
    print(f"\n  平均 OOS Sharpe  broader {m(sr_b):.2f}  vs TOP7 {m(sr_7):.2f}")
    print(f"  平均 OOS maxDD   broader {m(dd_b):+.1%}  vs TOP7 {m(dd_7):+.1%}")
    print(f"  broader Sharpe ≥ TOP7 的折: {sw}/{len(folds)};  maxDD 不更深的折: {dw}/{len(folds)}")
    print("\n  判据:broader 多数折 OOS Sharpe≥ 且 maxDD 不更深 = 分散稳健可推(够本金时扩 universe).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
