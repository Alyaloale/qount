#!/usr/bin/env python3
"""CTA-R operational target-weights tool (research-only).

Loads the latest akshare ETF cache, runs the EXACT validated engine
(`_target_weights` + MODE_PRESETS, fixed lookbacks) up to the last available
date, and prints the CURRENT target book for a given capital: per-ETF weight,
trend signal (long/flat), price, target lots (100-share), ¥ amount, and the
cash residual. This is the "given latest prices -> hold this" monthly rebalance
sheet. No network, no orders; refresh the cache (akshare online) before acting.

Run on WSL:  .venv/bin/python scripts/research/cta_target_weights.py [--mode balanced] [--capital 1000000]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from qount.cta_data import ETF_ASSET_CLASS, exclude_asset_classes, load_etf_cache  # noqa: E402
from qount.cta_sim import MODE_PRESETS, SimConfig, _target_weights  # noqa: E402

CACHE = REPO / "state" / "etf_cache"
FIXED_LB = (63, 126, 252)
FIXED_VOL_LB, FIXED_REB = 63, 21

NAMES = {
    "510300.SH": "沪深300ETF", "510500.SH": "中证500ETF", "159915.SZ": "创业板ETF",
    "510050.SH": "上证50ETF", "518880.SH": "黄金ETF", "511010.SH": "国债ETF(5年)",
    "513100.SH": "纳指ETF", "513500.SH": "标普500ETF",
}
QDII = {"513100.SH", "513500.SH"}


def _load_aligned():
    symbols = sorted(p.stem for p in CACHE.glob("*.csv"))
    by = {s: load_etf_cache(str(CACHE), s) for s in symbols}
    common = None
    for s in symbols:
        d = set(by[s])
        common = d if common is None else (common & d)
    dates = sorted(common or [])
    prices = {s: [by[s][dt] for dt in dates] for s in symbols}
    return dates, prices


def _final_weights(prices, config):
    """Replicate the engine loop; return the weights in effect at the last rebalance."""
    names = list(prices)
    length = len(prices[names[0]])
    rets = {}
    for n in names:
        s = [None]
        for t in range(1, length):
            prev = prices[n][t - 1]
            s.append(prices[n][t] / prev - 1.0 if prev > 0 else None)
        rets[n] = s
    warmup = max(max(config.lookback_days), config.vol_lookback_days) + 1
    equity, peak, weights = 1.0, 1.0, {}
    for t in range(1, length):
        port = sum(w * rets[n][t] for n, w in weights.items() if rets[n][t] is not None)
        equity *= 1.0 + port
        peak = max(peak, equity)
        if t >= warmup and t % config.rebalance_days == 0:
            weights = _target_weights(prices, rets, t, config, equity, peak)
            peak = max(peak, equity)
    return weights


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=list(MODE_PRESETS), default="balanced")
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    args = ap.parse_args()

    dates, prices = _load_aligned()
    preset = MODE_PRESETS[args.mode]
    if preset["exclude_classes"]:
        prices = exclude_asset_classes(prices, preset["exclude_classes"])
    config = SimConfig(
        lookback_days=FIXED_LB, vol_lookback_days=FIXED_VOL_LB, rebalance_days=FIXED_REB,
        target_vol=preset["target_vol"], max_leverage=preset["max_leverage"],
        long_only=preset["long_only"], max_weight=preset["max_weight"],
    )
    weights = _final_weights(prices, config)
    last_px = {s: prices[s][-1] for s in prices}

    print(f"CTA-R 目标权重  mode={args.mode}  本金=¥{args.capital:,.0f}  数据截至 {dates[-1]}")
    print(f"(fixed lb={FIXED_LB} reb={FIXED_REB}天 cash long-only cap={preset['max_weight']} "
          f"target_vol={preset['target_vol']}{' 剔除国债' if preset['exclude_classes'] else ''})\n")
    print(f"{'ETF':<11}{'名称':<13}{'QDII':<5}{'类别':<15}{'权重':>7}{'信号':>5}{'现价':>9}{'手数':>7}{'金额¥':>12}")
    invested = 0.0
    for s in sorted(prices, key=lambda x: -weights.get(x, 0.0)):
        w = weights.get(s, 0.0)
        px = last_px[s]
        tgt = args.capital * w
        lots = int(tgt / px / 100) if px > 0 else 0        # 1 手 = 100 份;向下取整(现金账户不超配)
        amt = lots * 100 * px
        invested += amt
        sig = "多" if w > 0 else "空仓"
        tag = "QDII" if s in QDII else ""
        nm = NAMES.get(s, "?")
        print(f"{s:<11}{nm:<12}{tag:<5}{ETF_ASSET_CLASS.get(s,'?'):<15}{w*100:>6.1f}%{sig:>5}{px:>9.3f}{lots:>7}{amt:>12,.0f}")
    cash = args.capital - invested
    print(f"\n{'现金(未投)':<25}{(cash/args.capital)*100:>6.1f}%{'':>14}{cash:>12,.0f}")
    print(f"{'合计投入':<25}{(invested/args.capital)*100:>6.1f}%{'':>14}{invested:>12,.0f}")
    print("\n* QDII(513100/513500)有溢价/限购,二级市场买卖不受限但注意溢价;每月调仓日按最新价重算本表。")


if __name__ == "__main__":
    main()
