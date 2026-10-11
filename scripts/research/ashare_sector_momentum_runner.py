"""Comprehensive Runner for A-Share Sector and Track ETF Momentum Breakout Strategy (2013-2026).

Executes:
1. Domestic vs Global-Macro Sector Universe Comparisons
2. Systematic Parameter Sweeps (Top N, MA trend filter, Trailing Stop)
3. The Four Standard Curves (Base, Double Cost, Extra Day Delay, Double Cost + Extra Day)
4. Historical Stress Regime & Annual Alpha Attributions
5. Outputs machine-readable summary receipt to state/research_runs/ashare_sector_momentum_20261011/summary.json
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

# Ensure src is on sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from qount.research.ashare_sector_momentum import (
    SectorBar,
    SectorMomentumSimulator,
    SectorSimulationResult,
)

DOMESTIC_UNIVERSE = [
    "399975.SZ",  # 券商 (Securities)
    "399997.SZ",  # 白酒 (Liquor)
    "000990.CSI",  # 半导体 (Semiconductor)
    "399976.SZ",  # 新能源车 (NEV)
    "399808.SZ",  # 光伏 (Solar)
    "399989.SZ",  # 医疗 (Healthcare)
    "399967.SZ",  # 军工 (Military/Defense)
    "399998.SZ",  # 煤炭 (Coal)
    "000991.SH",  # 计算机 (Computer/AI)
    "000922.CSI",  # 红利 (Dividend)
    "159915.SZ",  # 创业板 ETF (ChiNext Growth)
]

GLOBAL_MACRO_UNIVERSE = DOMESTIC_UNIVERSE + [
    "513100.SH",  # 纳指 100 ETF (Nasdaq ETF)
]


def load_sector_data(data_path: Path) -> dict[str, list[SectorBar]]:
    with open(data_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, list[SectorBar]] = {}
    for code, items in raw.items():
        bars = [
            SectorBar(
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


def run_comprehensive_study(data_path: Path) -> dict:
    print("=" * 85)
    print("A-SHARE SECTOR & TRACK ETF MOMENTUM BREAKOUT STRATEGY (2013 - 2026)")
    print("Target: High-Profit Breakthrough for Personal Quant Trading")
    print("=" * 85)

    data = load_sector_data(data_path)
    b300 = data["000300.SH"]
    dates = [b.trade_date for b in b300]
    years = len(dates) / 252.0

    print(f"Data period: {dates[0]} to {dates[-1]} ({len(dates)} sessions, ~{years:.2f} years)")
    print(f"Candidate assets: {len(GLOBAL_MACRO_UNIVERSE)} total ({len(DOMESTIC_UNIVERSE)} domestic, 1 cross-border)")

    # 1. Benchmark Buy & Hold CSI 300
    b300_initial = b300[0].close
    b300_final = b300[-1].close
    b300_cagr = (b300_final / b300_initial) ** (1.0 / years) - 1.0

    b300_peak = b300[0].close
    b300_max_dd = 0.0
    for b in b300:
        if b.close > b300_peak:
            b300_peak = b.close
        dd = (b300_peak - b.close) / b300_peak
        if dd > b300_max_dd:
            b300_max_dd = dd

    print("\n[1] BENCHMARK BASELINE (CSI 300 BUY & HOLD):")
    print(f"  Final Return: {(b300_final/b300_initial - 1.0)*100:6.2f}%")
    print(f"  CAGR:         {b300_cagr*100:6.2f}%")
    print(f"  Max Drawdown: {b300_max_dd*100:6.2f}%")

    # 2. Universe Comparison: Pure Domestic vs Global-Macro
    print("\n[2] UNIVERSE COMPARISON (Top 2, MA 30, Breakout 20, Trailing Stop 10%, Macro Overlay):")
    sim = SectorMomentumSimulator(commission_bps=6.0, slippage_bps=5.0, annual_cash_yield=0.02)
    
    res_dom = sim.run(
        bars_dict=data,
        universe=DOMESTIC_UNIVERSE,
        top_n=2,
        ma_period=30,
        breakout_window=20,
        trailing_stop_pct=0.10,
        macro_filter=True,
    )
    res_global = sim.run(
        bars_dict=data,
        universe=GLOBAL_MACRO_UNIVERSE,
        top_n=2,
        ma_period=30,
        breakout_window=20,
        trailing_stop_pct=0.10,
        macro_filter=True,
    )

    print(f"{'Universe':<25} | {'CAGR (%)':<10} | {'MaxDD (%)':<10} | {'Sharpe':<8} | {'Calmar':<8} | {'Turnover':<10} | {'Final Equity (¥)':<16}")
    print("-" * 96)
    for name, r in [("Domestic (11 assets)", res_dom), ("Global-Macro (12 assets)", res_global)]:
        m = r.metrics
        print(f"{name:<25} | {m.cagr*100:9.2f}% | {m.max_drawdown*100:9.2f}% | {m.sharpe_ratio:8.2f} | {m.calmar_ratio:8.2f} | {m.annual_turnover:9.2f}x | ¥{m.final_equity:15,.0f}")

    # 3. Systematic Parameter Sweep
    print("\n[3] PARAMETER SWEEP MATRIX (Global-Macro Universe):")
    print(f"{'Config':<35} | {'CAGR (%)':<10} | {'MaxDD (%)':<10} | {'Sharpe':<8} | {'Calmar':<8} | {'Turnover':<10} | {'WinRate':<8}")
    print("-" * 96)
    sweep_results = []
    for top_n in [2, 3]:
        for ma_w in [20, 30, 40]:
            for ts in [0.08, 0.10, 0.12]:
                r = sim.run(
                    bars_dict=data,
                    universe=GLOBAL_MACRO_UNIVERSE,
                    top_n=top_n,
                    ma_period=ma_w,
                    trailing_stop_pct=ts,
                    macro_filter=True,
                )
                m = r.metrics
                cfg_name = f"Top {top_n} | MA {ma_w} | TrailStop {int(ts*100)}%"
                sweep_results.append({
                    "config": cfg_name,
                    "top_n": top_n,
                    "ma_period": ma_w,
                    "trailing_stop_pct": ts,
                    "cagr": m.cagr,
                    "max_dd": m.max_drawdown,
                    "sharpe": m.sharpe_ratio,
                    "calmar": m.calmar_ratio,
                    "turnover": m.annual_turnover,
                    "final_equity": m.final_equity,
                })
                print(f"{cfg_name:<35} | {m.cagr*100:9.2f}% | {m.max_drawdown*100:9.2f}% | {m.sharpe_ratio:8.2f} | {m.calmar_ratio:8.2f} | {m.annual_turnover:9.2f}x | {m.win_rate*100:6.1f}%")

    # 4. The Four Standard Curves (Base, Double Cost, Extra Day Delay, Double Cost + Extra Day Delay)
    print("\n[4] THE FOUR STANDARD ROBUSTNESS CURVES (Top 2, MA 30, Trail 10%):")
    sim_base = SectorMomentumSimulator(commission_bps=6.0, slippage_bps=5.0, extra_execution_delay=0)
    sim_double = SectorMomentumSimulator(commission_bps=12.0, slippage_bps=10.0, extra_execution_delay=0)
    sim_delay = SectorMomentumSimulator(commission_bps=6.0, slippage_bps=5.0, extra_execution_delay=1)
    sim_both = SectorMomentumSimulator(commission_bps=12.0, slippage_bps=10.0, extra_execution_delay=1)

    curve_base = sim_base.run(bars_dict=data, universe=GLOBAL_MACRO_UNIVERSE, top_n=2, ma_period=30, trailing_stop_pct=0.10, macro_filter=True)
    curve_double = sim_double.run(bars_dict=data, universe=GLOBAL_MACRO_UNIVERSE, top_n=2, ma_period=30, trailing_stop_pct=0.10, macro_filter=True)
    curve_delay = sim_delay.run(bars_dict=data, universe=GLOBAL_MACRO_UNIVERSE, top_n=2, ma_period=30, trailing_stop_pct=0.10, macro_filter=True)
    curve_both = sim_both.run(bars_dict=data, universe=GLOBAL_MACRO_UNIVERSE, top_n=2, ma_period=30, trailing_stop_pct=0.10, macro_filter=True)

    four_curves_data = [
        ("Base (11bp, T+1 open fill)", curve_base),
        ("Double Cost (22bp, T+1 open fill)", curve_double),
        ("Extra Day Delay (11bp, T+2 open fill)", curve_delay),
        ("Double Cost + Delay (22bp, T+2 fill)", curve_both),
    ]

    print(f"{'Condition':<38} | {'CAGR (%)':<10} | {'MaxDD (%)':<10} | {'Sharpe':<8} | {'Calmar':<8} | {'Turnover':<10} | {'Final Equity (¥)':<16}")
    print("-" * 110)
    for c_name, r in four_curves_data:
        m = r.metrics
        print(f"{c_name:<38} | {m.cagr*100:9.2f}% | {m.max_drawdown*100:9.2f}% | {m.sharpe_ratio:8.2f} | {m.calmar_ratio:8.2f} | {m.annual_turnover:9.2f}x | ¥{m.final_equity:15,.0f}")

    # 5. Stress Regimes Evaluation
    print("\n[5] HISTORICAL STRESS PERIODS & REGIME ATTRIBUTIONS:")
    regime_labels = {
        "2015_crash": "2015-06 to 2015-08 (Leverage Crash)",
        "2016_circuit": "2016-01 (Circuit Breakers)",
        "2018_trade_war": "2018-01 to 2018-12 (Trade War Bear)",
        "2019_recovery": "2019-01 to 2019-04 (V-Shape Rebound)",
        "2020_covid_shock": "2020-01 to 2020-03 (COVID Liquidity Shock)",
        "2020_2021_bull": "2020-03 to 2021-02 (Structural Sector Bull)",
        "2022_downtrend": "2022-01 to 2022-10 (Global Rate Hikes Downtrend)",
        "2024_rebound": "2024-09 to 2024-10 (Policy Pivot Surge)",
    }
    regime_bounds = {
        "2015_crash": ("20150615", "20150826"),
        "2016_circuit": ("20160101", "20160129"),
        "2018_trade_war": ("20180129", "20181228"),
        "2019_recovery": ("20190102", "20190419"),
        "2020_covid_shock": ("20200120", "20200323"),
        "2020_2021_bull": ("20200324", "20210218"),
        "2022_downtrend": ("20220104", "20221031"),
        "2024_rebound": ("20240918", "20241009"),
    }
    date_to_b300 = {b.trade_date: b.close for b in b300}

    print(f"{'Regime Window':<42} | {'CSI 300':<10} | {'Base (Global)':<14} | {'Domestic Only':<14} | {'Alpha vs 300':<12}")
    print("-" * 100)
    for r_key, r_name in regime_labels.items():
        d0, d1 = regime_bounds[r_key]
        sub = [d for d in dates if d0 <= d <= d1]
        b_ret = (date_to_b300[sub[-1]] / date_to_b300[sub[0]]) - 1.0 if len(sub) >= 2 else 0.0
        g_ret = curve_base.metrics.regime_returns.get(r_key, 0.0)
        d_ret = res_dom.metrics.regime_returns.get(r_key, 0.0)
        alpha = g_ret - b_ret
        print(f"{r_name:<42} | {b_ret*100:9.2f}% | {g_ret*100:13.2f}% | {d_ret*100:13.2f}% | {alpha*100:+11.2f}%")

    # 6. Annual Calendar Returns
    print("\n[6] ANNUAL CALENDAR RETURNS (2013 - 2026):")
    b300_by_yr: dict[str, list[float]] = {}
    for b in b300:
        b300_by_yr.setdefault(b.trade_date[:4], []).append(b.close)
    b300_yr_rets: dict[str, float] = {}
    prev_c = b300[0].close
    for y, closes in sorted(b300_by_yr.items()):
        b300_yr_rets[y] = (closes[-1] / prev_c) - 1.0
        prev_c = closes[-1]

    print(f"{'Year':<6} | {'CSI 300':<10} | {'Sector Mom (Base)':<18} | {'Domestic Only':<16} | {'Excess Alpha':<12}")
    print("-" * 70)
    all_years = sorted(curve_base.metrics.year_returns.keys())
    for y in all_years:
        b_r = b300_yr_rets.get(y, 0.0)
        g_r = curve_base.metrics.year_returns.get(y, 0.0)
        d_r = res_dom.metrics.year_returns.get(y, 0.0)
        alpha = g_r - b_r
        print(f"{y:<6} | {b_r*100:9.2f}% | {g_r*100:17.2f}% | {d_r*100:15.2f}% | {alpha*100:+11.2f}%")

    # 7. Output Structured Receipt
    receipt_dir = ROOT / "state/research_runs/ashare_sector_momentum_20261011"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    summary_path = receipt_dir / "summary.json"

    receipt_data = {
        "timestamp": "2026-10-11T14:40:00Z",
        "research_topic": "ashare_sector_track_momentum_breakout",
        "universe_size": len(GLOBAL_MACRO_UNIVERSE),
        "data_range": f"{dates[0]} to {dates[-1]} ({len(dates)} days, {years:.2f} years)",
        "benchmark_csi300": {
            "cagr": b300_cagr,
            "max_drawdown": b300_max_dd,
            "total_return": (b300_final / b300_initial) - 1.0,
        },
        "four_standard_curves": {
            "base": {
                "cagr": curve_base.metrics.cagr,
                "max_drawdown": curve_base.metrics.max_drawdown,
                "sharpe": curve_base.metrics.sharpe_ratio,
                "calmar": curve_base.metrics.calmar_ratio,
                "annual_turnover": curve_base.metrics.annual_turnover,
                "final_equity": curve_base.metrics.final_equity,
            },
            "double_cost": {
                "cagr": curve_double.metrics.cagr,
                "max_drawdown": curve_double.metrics.max_drawdown,
                "sharpe": curve_double.metrics.sharpe_ratio,
                "calmar": curve_double.metrics.calmar_ratio,
                "annual_turnover": curve_double.metrics.annual_turnover,
                "final_equity": curve_double.metrics.final_equity,
            },
            "extra_day": {
                "cagr": curve_delay.metrics.cagr,
                "max_drawdown": curve_delay.metrics.max_drawdown,
                "sharpe": curve_delay.metrics.sharpe_ratio,
                "calmar": curve_delay.metrics.calmar_ratio,
                "annual_turnover": curve_delay.metrics.annual_turnover,
                "final_equity": curve_delay.metrics.final_equity,
            },
            "double_cost_extra_day": {
                "cagr": curve_both.metrics.cagr,
                "max_drawdown": curve_both.metrics.max_drawdown,
                "sharpe": curve_both.metrics.sharpe_ratio,
                "calmar": curve_both.metrics.calmar_ratio,
                "annual_turnover": curve_both.metrics.annual_turnover,
                "final_equity": curve_both.metrics.final_equity,
            },
        },
        "domestic_only": {
            "cagr": res_dom.metrics.cagr,
            "max_drawdown": res_dom.metrics.max_drawdown,
            "sharpe": res_dom.metrics.sharpe_ratio,
            "calmar": res_dom.metrics.calmar_ratio,
            "annual_turnover": res_dom.metrics.annual_turnover,
            "final_equity": res_dom.metrics.final_equity,
        },
        "annual_returns": {
            y: {
                "benchmark_csi300": b300_yr_rets.get(y, 0.0),
                "sector_momentum_base": curve_base.metrics.year_returns.get(y, 0.0),
                "domestic_only": res_dom.metrics.year_returns.get(y, 0.0),
                "alpha": curve_base.metrics.year_returns.get(y, 0.0) - b300_yr_rets.get(y, 0.0),
            }
            for y in all_years
        },
        "regime_stress": {
            r_key: {
                "label": regime_labels[r_key],
                "sector_momentum_return": curve_base.metrics.regime_returns.get(r_key, 0.0),
            }
            for r_key in regime_labels
        },
        "parameter_sweep": sweep_results,
        "research_only": True,
        "orders_authorized": False,
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(receipt_data, f, indent=2, ensure_ascii=False)

    print(f"\n[7] Summary receipt saved to: {summary_path}")
    print("=" * 85)
    return receipt_data


if __name__ == "__main__":
    data_file = ROOT / "data/processed/clean_sectors_daily_2013_2026.json"
    run_comprehensive_study(data_file)
