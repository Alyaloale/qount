"""Runner for A-share ETF Trend Timing and Regime Rotation Research.

Executes systematic parameter sweeps, whipsaw filter tests, dual-asset regime rotation,
stress-period evaluations, and friction sensitivity on 2013-2026 data.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

# Ensure src is on sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from qount.research.ashare_trend_etf import (
    DailyBar,
    TrendETFAssistantSimulator,
    evaluate_performance,
)


def load_clean_data(data_path: Path) -> dict[str, list[DailyBar]]:
    with open(data_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for code, items in raw.items():
        bars = [
            DailyBar(
                trade_date=it["trade_date"],
                open=float(it["open"]),
                high=float(it["high"]),
                low=float(it["low"]),
                close=float(it["close"]),
                vol=float(it.get("vol", 0.0)),
                amount=float(it.get("amount", 0.0)),
            )
            for it in items
        ]
        out[code] = bars
    return out


def run_comprehensive_study(data_path: Path):
    print("=" * 80)
    print("A-SHARE PERSONAL ETF QUANTITATIVE STRATEGY RESEARCH (2013 - 2026)")
    print("=" * 80)

    data = load_clean_data(data_path)
    b300 = data["000300.SH"]
    h300 = data.get("H00300.CSI", b300)
    b500 = data["000905.SH"]

    start_date = b300[0].trade_date
    end_date = b300[-1].trade_date
    total_days = len(b300)
    years = total_days / 252.0
    print(f"Data range: {start_date} to {end_date} ({total_days} sessions, ~{years:.2f} years)")

    # 1. Benchmarks
    sim_base = TrendETFAssistantSimulator(commission_bps=6.0, slippage_bps=5.0, annual_cash_yield=0.02)
    # Buy & Hold CSI 300
    b300_ret = (b300[-1].close / b300[0].close) - 1.0
    b300_cagr = (1.0 + b300_ret) ** (1.0 / years) - 1.0
    # Peak to trough for CSI 300 close
    peak = b300[0].close
    mdd_300 = 0.0
    for b in b300:
        if b.close > peak:
            peak = b.close
        dd = (peak - b.close) / peak
        if dd > mdd_300:
            mdd_300 = dd

    h300_ret = (h300[-1].close / h300[0].close) - 1.0
    h300_cagr = (1.0 + h300_ret) ** (1.0 / years) - 1.0
    peak_h = h300[0].close
    mdd_h300 = 0.0
    for b in h300:
        if b.close > peak_h:
            peak_h = b.close
        dd = (peak_h - b.close) / peak_h
        if dd > mdd_h300:
            mdd_h300 = dd

    print("\n[1] BUY & HOLD BENCHMARKS:")
    print(f"  * CSI 300 Price (000300.SH):  Total Ret: {b300_ret*100:6.2f}%, CAGR: {b300_cagr*100:5.2f}%, MaxDD: {mdd_300*100:5.2f}%")
    print(f"  * CSI 300 TR   (H00300.CSI): Total Ret: {h300_ret*100:6.2f}%, CAGR: {h300_cagr*100:5.2f}%, MaxDD: {mdd_h300*100:5.2f}%")

    # 2. Experiment A: Single-Asset MA Period Sweep on CSI 300
    print("\n[2] EXPERIMENT A: MA PERIOD SWEEP ON CSI 300 (band=1.5%, confirm=2, cash_yield=2.0%):")
    print(f"{'MA Period':<10} | {'CAGR (%)':<10} | {'MaxDD (%)':<10} | {'Sharpe':<8} | {'Calmar':<8} | {'Turnover':<10} | {'Trades':<8} | {'WinRate':<8}")
    print("-" * 88)
    ma_results = {}
    for ma in [60, 100, 120, 150, 200, 250]:
        res = sim_base.simulate_single_asset_trend(b300, ma_period=ma, band_pct=0.015, confirm_days=2)
        m = res.metrics
        ma_results[ma] = res
        print(f"MA {ma:<7} | {m.cagr*100:9.2f}% | {m.max_drawdown*100:9.2f}% | {m.sharpe_ratio:8.2f} | {m.calmar_ratio:8.2f} | {m.annual_turnover:9.2f}x | {m.trade_count:<8} | {m.win_rate*100:6.1f}%")

    # 3. Experiment B: Whipsaw Buffer Filter Sweep (MA 120)
    print("\n[3] EXPERIMENT B: WHIPSAW BUFFER FILTER SWEEP ON MA 120 (confirm=2):")
    print(f"{'Band Pct':<10} | {'CAGR (%)':<10} | {'MaxDD (%)':<10} | {'Sharpe':<8} | {'Calmar':<8} | {'Turnover':<10} | {'Trades':<8}")
    print("-" * 78)
    for band in [0.000, 0.005, 0.010, 0.015, 0.020, 0.025]:
        res = sim_base.simulate_single_asset_trend(b300, ma_period=120, band_pct=band, confirm_days=2)
        m = res.metrics
        print(f"{band*100:5.1f}%     | {m.cagr*100:9.2f}% | {m.max_drawdown*100:9.2f}% | {m.sharpe_ratio:8.2f} | {m.calmar_ratio:8.2f} | {m.annual_turnover:9.2f}x | {m.trade_count:<8}")

    # 4. Experiment C: Dual-Asset Regime Rotation (CSI 300 vs CSI 500 vs Cash)
    print("\n[4] EXPERIMENT C: DUAL-ASSET REGIME ROTATION (CSI 300 vs CSI 500 vs Cash, MA 120):")
    print(f"{'Momentum Win':<12} | {'CAGR (%)':<10} | {'MaxDD (%)':<10} | {'Sharpe':<8} | {'Calmar':<8} | {'Turnover':<10} | {'Trades':<8}")
    print("-" * 80)
    rot_results = {}
    for mom in [10, 20, 40, 60]:
        res_rot = sim_base.simulate_dual_asset_rotation(
            b300, b500, symbol_a="000300.SH", symbol_b="000905.SH",
            ma_period=120, momentum_window=mom, band_pct=0.015, confirm_days=2
        )
        m = res_rot.metrics
        rot_results[mom] = res_rot
        print(f"MOM {mom:<8} | {m.cagr*100:9.2f}% | {m.max_drawdown*100:9.2f}% | {m.sharpe_ratio:8.2f} | {m.calmar_ratio:8.2f} | {m.annual_turnover:9.2f}x | {m.trade_count:<8}")

    # 5. Experiment D: 300 Trend Timing + Dividend Shield (H00922 Total Return)
    print("\n[5] EXPERIMENT D: CSI 300 TREND + DIVIDEND SHIELD ROTATION (H00922 TR Shield):")
    print(f"{'Model Configuration':<30} | {'CAGR (%)':<10} | {'MaxDD (%)':<10} | {'Sharpe':<8} | {'Calmar':<8} | {'Turnover':<10} | {'Trades':<8}")
    print("-" * 98)
    shield_results = {}
    b_div = data.get("H00922.CSI", b300)
    for ma in [120, 200]:
        for s_mode in ["DIV_100", "DIV_50_CASH_50", "CASH_100"]:
            res_sh = sim_base.simulate_trend_dividend_shield(
                b300, b_div, symbol_trend="000300.SH", symbol_shield="H00922.CSI",
                ma_period=ma, band_pct=0.015, confirm_days=2, shield_mode=s_mode
            )
            m = res_sh.metrics
            cfg_name = f"MA{ma} + {s_mode}"
            shield_results[cfg_name] = res_sh
            print(f"{cfg_name:<30} | {m.cagr*100:9.2f}% | {m.max_drawdown*100:9.2f}% | {m.sharpe_ratio:8.2f} | {m.calmar_ratio:8.2f} | {m.annual_turnover:9.2f}x | {m.trade_count:<8}")

    # 6. Stress Period Regimes Breakdown (Comparing Benchmark vs MA200 vs Shield)
    best_single = ma_results[200]
    best_rot = rot_results[20]
    best_shield = shield_results["MA200 + DIV_50_CASH_50"]

    print("\n[5] STRESS PERIOD BREAKDOWN:")
    regimes = [
        ("2015_crash", "2015 杠杆牛崩盘 (2015.06-08)"),
        ("2016_circuit", "2016 熔断股灾 (2016.01)"),
        ("2018_bear", "2018 单边大熊市 (2018 全年)"),
        ("2019_2020_bull", "2019-20 核心资产牛市 (2019-20)"),
        ("2021_2023_bear", "2021-23 漫长阴跌熊市 (2021-23)"),
        ("2024_09_surge", "2024.09 超级暴涨反弹 (2024.09-10)"),
    ]
    print(f"{'Regime Period':<26} | {'CSI 300':<12} | {'MA200 Trend':<12} | {'Div Shield (50/50)':<18}")
    print("-" * 75)
    # Compute benchmark regime return
    snap_dates = {b.trade_date: b.close for b in b300}
    regime_bounds = {
        "2015_crash": ("20150615", "20150826"),
        "2016_circuit": ("20160101", "20160129"),
        "2018_bear": ("20180129", "20181228"),
        "2019_2020_bull": ("20190102", "20201231"),
        "2021_2023_bear": ("20210218", "20231229"),
        "2024_09_surge": ("20240918", "20241008"),
    }
    for r_key, r_name in regimes:
        d0, d1 = regime_bounds[r_key]
        sub_dates = [d for d in sorted(snap_dates.keys()) if d0 <= d <= d1]
        bench_ret = (snap_dates[sub_dates[-1]] / snap_dates[sub_dates[0]]) - 1.0 if sub_dates else 0.0
        s_ret = best_single.metrics.regime_returns.get(r_key, 0.0)
        sh_ret = best_shield.metrics.regime_returns.get(r_key, 0.0)
        print(f"{r_name:<26} | {bench_ret*100:10.2f}% | {s_ret*100:10.2f}% | {sh_ret*100:16.2f}%")

    # 6. Robustness / Friction Sensitivity Test
    print("\n[6] ROBUSTNESS & FRICTION SENSITIVITY TEST (MA 120 Trend):")
    # Base (6bp comm, 5bp slip, 0 delay)
    res_base = best_single
    # Double cost (12bp comm, 10bp slip, 0 delay)
    sim_double = TrendETFAssistantSimulator(commission_bps=12.0, slippage_bps=10.0, annual_cash_yield=0.02, extra_execution_delay=0)
    res_double = sim_double.simulate_single_asset_trend(b300, ma_period=120, band_pct=0.015, confirm_days=2)
    # Extra day delay (6bp comm, 5bp slip, 1 delay -> T+2 open execution)
    sim_delay = TrendETFAssistantSimulator(commission_bps=6.0, slippage_bps=5.0, annual_cash_yield=0.02, extra_execution_delay=1)
    res_delay = sim_delay.simulate_single_asset_trend(b300, ma_period=120, band_pct=0.015, confirm_days=2)
    # Double cost + Extra delay
    sim_both = TrendETFAssistantSimulator(commission_bps=12.0, slippage_bps=10.0, annual_cash_yield=0.02, extra_execution_delay=1)
    res_both = sim_both.simulate_single_asset_trend(b300, ma_period=120, band_pct=0.015, confirm_days=2)

    print(f"{'Condition':<25} | {'CAGR (%)':<10} | {'MaxDD (%)':<10} | {'Sharpe':<8} | {'Calmar':<8} | {'Turnover':<10}")
    print("-" * 75)
    for c_name, r in [
        ("Base (0 delay, 11bp)", res_base),
        ("Double Cost (22bp)", res_double),
        ("Extra Day (T+2 fill)", res_delay),
        ("Double Cost + Extra Day", res_both),
    ]:
        m = r.metrics
        print(f"{c_name:<25} | {m.cagr*100:9.2f}% | {m.max_drawdown*100:9.2f}% | {m.sharpe_ratio:8.2f} | {m.calmar_ratio:8.2f} | {m.annual_turnover:9.2f}x")

    # 7. Annual Returns Table
    print("\n[7] ANNUAL CALENDAR RETURNS (MA 120 Trend vs Buy & Hold CSI 300):")
    print(f"{'Year':<6} | {'CSI 300':<10} | {'MA 120 Trend':<12} | {'Dual-Rotation':<12} | {'Alpha vs 300':<12}")
    print("-" * 62)
    all_years = sorted(best_single.metrics.year_returns.keys())
    # Bench annual return
    by_yr_bench: dict[str, list[DailyBar]] = {}
    for b in b300:
        by_yr_bench.setdefault(b.trade_date[:4], []).append(b)
    bench_yr_ret = {}
    prev_c = b300[0].close
    for y, y_bars in sorted(by_yr_bench.items()):
        bench_yr_ret[y] = (y_bars[-1].close / prev_c) - 1.0
        prev_c = y_bars[-1].close

    print(f"{'Year':<6} | {'CSI 300':<10} | {'MA 200 Trend':<12} | {'Div Shield (50/50)':<18} | {'Shield Alpha':<12}")
    print("-" * 70)
    for y in all_years:
        b_r = bench_yr_ret.get(y, 0.0)
        s_r = best_single.metrics.year_returns.get(y, 0.0)
        sh_r = best_shield.metrics.year_returns.get(y, 0.0)
        alpha = sh_r - b_r
        print(f"{y:<6} | {b_r*100:9.2f}% | {s_r*100:11.2f}% | {sh_r*100:17.2f}% | {alpha*100:+11.2f}%")


if __name__ == "__main__":
    data_file = ROOT / "data/processed/clean_indices_daily_2013_2026.json"
    run_comprehensive_study(data_file)
