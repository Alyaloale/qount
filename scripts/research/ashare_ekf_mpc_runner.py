"""Comprehensive Runner for A-Share EKF-MPC Dynamic Allocation & Fast-Escape Strategy.

Evaluates:
1. CSI 300 Buy & Hold Benchmark
2. EKF-MPC Dynamic Allocation (Asymmetric 65/35 High-Conviction Overweighting)
3. Three-Tier Fast-Escape Risk Control (Fast Hard-Stop -6.5%, Break-Even Lock +12%)
4. The Four Standard Curves (Base, Double Friction, +1 Day Delay, Double Friction + Delay)
5. Parametric Sensitivity Matrix (Allocation weights, Fast Stop vs No Stop)
6. Historical Stress Regimes & Annual Alpha Breakdown (2013-2026)
7. Outputs structured receipt to state/research_runs/ashare_ekf_mpc_20261011/summary.json
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

# Ensure src is on sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from qount.research.ashare_ekf_mpc import (
    AssetBar,
    EKFMPCSimulator,
    EKFMPCSimulationResult,
)

UNIVERSE = [
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
    "513100.SH",  # 纳指 100 ETF (Nasdaq ETF)
]
BENCHMARK = "000300.SH"


def load_asset_data(data_path: Path) -> dict[str, list[AssetBar]]:
    with open(data_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, list[AssetBar]] = {}
    for code, items in raw.items():
        bars = [
            AssetBar(
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


def run_ekf_mpc_study(data_path: Path) -> dict:
    print("=" * 85)
    print("A-SHARE EKF-MPC DYNAMIC ALLOCATION & FAST-ESCAPE STRATEGY (2013 - 2026)")
    print("State Space Dynamic Filtering + Non-Fixed Conviction Allocation + Fast-Escape Stop")
    print("=" * 85)

    data = load_asset_data(data_path)
    b300 = data[BENCHMARK]
    dates = [b.trade_date for b in b300]
    years = len(dates) / 252.0

    print(f"Data period: {dates[0]} to {dates[-1]} ({len(dates)} sessions, ~{years:.2f} years)")
    print(f"Candidate assets: {len(UNIVERSE)} total (11 Domestic + 1 Global Nasdaq)")

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
    print(f"  Final Return: {(b300_final / b300_initial - 1.0) * 100:6.2f}%")
    print(f"  CAGR:         {b300_cagr * 100:6.2f}%")
    print(f"  Max Drawdown: {b300_max_dd * 100:6.2f}%")

    # 2. Base EKF-MPC Strategy (Base scoring, 65/35)
    sim = EKFMPCSimulator(commission_bps=6.0, slippage_bps=5.0)
    base_res = sim.run(
        bars_dict=data,
        universe=UNIVERSE,
        benchmark_symbol=BENCHMARK,
        top_n=2,
        top1_weight=0.65,
        top2_weight=0.35,
        fast_hard_stop=0.065,
        breakeven_trigger=0.12,
        trailing_stop_pct=0.10,
        macro_filter=True,
        scoring_mode="base",
    )
    m_base = base_res.metrics

    print("\n[2] BASE EKF-MPC STRATEGY (65/35 Asymmetric Allocation):")
    print(f"  Final Equity:  {m_base.final_equity:12,.2f} CNY (Initial: 1,000,000)")
    print(f"  CAGR:          {m_base.cagr * 100:6.2f}%")
    print(f"  Max Drawdown:  {m_base.max_drawdown * 100:6.2f}%")
    print(f"  Calmar Ratio:  {m_base.calmar_ratio:6.2f}")
    print(f"  Sharpe Ratio:  {m_base.sharpe_ratio:6.2f}")

    # 3. Composite Master Strategy (Optimized based on historical rally dynamics)
    master_res = sim.run(
        bars_dict=data,
        universe=UNIVERSE,
        benchmark_symbol=BENCHMARK,
        top_n=2,
        top1_weight=0.65,
        top2_weight=0.35,
        fast_hard_stop=0.065,
        breakeven_trigger=0.12,
        trailing_stop_pct=0.10,
        macro_filter=True,
        scoring_mode="composite_master",
    )
    m = master_res.metrics

    print("\n[3] COMPOSITE MASTER EKF-MPC (Historical Rally Optimized: Accel + Vol + Breakout Gap):")
    print(f"  Final Equity:  {m.final_equity:12,.2f} CNY (Initial: 1,000,000)")
    print(f"  Total Return:  {m.total_return * 100:6.2f}% ({m.final_equity / m.initial_capital:.2f}x multi-bagger)")
    print(f"  CAGR:          {m.cagr * 100:6.2f}%")
    print(f"  Max Drawdown:  {m.max_drawdown * 100:6.2f}%")
    print(f"  Sharpe Ratio:  {m.sharpe_ratio:6.2f}")
    print(f"  Calmar Ratio:  {m.calmar_ratio:6.2f}")
    print(f"  Ann Volatility:{m.annualized_volatility * 100:6.2f}%")
    print(f"  Ann Turnover:  {m.annual_turnover:6.2f}x")
    print(f"  Total Trades:  {m.total_trades}")
    print(f"  Win Rate:      {m.win_rate * 100:6.2f}%")
    print(f"  P/L Ratio:     {m.profit_loss_ratio:6.2f}")
    print(f"  Exit Breakdown:{m.exit_attribution}")

    # 4. Scoring Formulation Comparisons
    print("\n[4] TREND SCORING FORMULATION COMPARISONS:")
    scoring_modes = [
        ("Base Forecast & KSNR", "base"),
        ("With Acceleration Bonus", "with_accel"),
        ("Composite Master (Accel + Vol + Gap)", "composite_master"),
    ]
    for label, sm in scoring_modes:
        r_sm = sim.run(
            bars_dict=data,
            universe=UNIVERSE,
            benchmark_symbol=BENCHMARK,
            top_n=2,
            top1_weight=0.65,
            top2_weight=0.35,
            fast_hard_stop=0.065,
            breakeven_trigger=0.12,
            trailing_stop_pct=0.10,
            macro_filter=True,
            scoring_mode=sm,
        )
        print(f"  {label:38s} | CAGR: {r_sm.metrics.cagr * 100:5.2f}% | MaxDD: {r_sm.metrics.max_drawdown * 100:5.2f}% | Calmar: {r_sm.metrics.calmar_ratio:4.2f} | Final: {r_sm.metrics.final_equity:12,.0f}")

    # 5. The Four Standard Curves on Composite Master
    print("\n[5] THE FOUR STANDARD CURVES AUDIT (Composite Master):")
    sim_double_cost = EKFMPCSimulator(commission_bps=12.0, slippage_bps=10.0)
    res_double_cost = sim_double_cost.run(
        bars_dict=data,
        universe=UNIVERSE,
        benchmark_symbol=BENCHMARK,
        top_n=2,
        top1_weight=0.65,
        top2_weight=0.35,
        fast_hard_stop=0.065,
        breakeven_trigger=0.12,
        trailing_stop_pct=0.10,
        macro_filter=True,
        scoring_mode="composite_master",
    )

    sim_delay = EKFMPCSimulator(commission_bps=6.0, slippage_bps=5.0, extra_execution_delay=1)
    res_delay = sim_delay.run(
        bars_dict=data,
        universe=UNIVERSE,
        benchmark_symbol=BENCHMARK,
        top_n=2,
        top1_weight=0.65,
        top2_weight=0.35,
        fast_hard_stop=0.065,
        breakeven_trigger=0.12,
        trailing_stop_pct=0.10,
        macro_filter=True,
        scoring_mode="composite_master",
    )

    sim_double_delay = EKFMPCSimulator(commission_bps=12.0, slippage_bps=10.0, extra_execution_delay=1)
    res_double_delay = sim_double_delay.run(
        bars_dict=data,
        universe=UNIVERSE,
        benchmark_symbol=BENCHMARK,
        top_n=2,
        top1_weight=0.65,
        top2_weight=0.35,
        fast_hard_stop=0.065,
        breakeven_trigger=0.12,
        trailing_stop_pct=0.10,
        macro_filter=True,
        scoring_mode="composite_master",
    )

    curves = [
        ("Base (6bps fee, 5bps slip, T+1 open)", master_res.metrics),
        ("Double Cost (12bps fee, 10bps slip)", res_double_cost.metrics),
        ("Extra Day Delay (T+2 open fill)", res_delay.metrics),
        ("Double Cost + Extra Day Delay", res_double_delay.metrics),
    ]

    for label, cm in curves:
        print(f"  {label:38s} | CAGR: {cm.cagr * 100:5.2f}% | MaxDD: {cm.max_drawdown * 100:5.2f}% | Sharpe: {cm.sharpe_ratio:4.2f} | Calmar: {cm.calmar_ratio:4.2f}")

    # 6. Parametric Conviction Weighting Comparisons
    print("\n[6] PARAMETRIC ALLOCATION WEIGHTING COMPARISONS (Composite Master):")
    alloc_configs = [
        ("Equal 50/50 Mechanical Split", 0.50, 0.50),
        ("Dynamic 60/40 Asymmetric Conviction", 0.60, 0.40),
        ("Dynamic 65/35 High-Conviction Overweight", 0.65, 0.35),
        ("Dynamic 70/30 Aggressive Conviction", 0.70, 0.30),
        ("Dynamic 75/25 Super Conviction", 0.75, 0.25),
    ]

    for label, w1, w2 in alloc_configs:
        r = sim.run(
            bars_dict=data,
            universe=UNIVERSE,
            benchmark_symbol=BENCHMARK,
            top_n=2,
            top1_weight=w1,
            top2_weight=w2,
            fast_hard_stop=0.065,
            breakeven_trigger=0.12,
            trailing_stop_pct=0.10,
            macro_filter=True,
            scoring_mode="composite_master",
        )
        print(f"  {label:42s} | CAGR: {r.metrics.cagr * 100:5.2f}% | MaxDD: {r.metrics.max_drawdown * 100:5.2f}% | Calmar: {r.metrics.calmar_ratio:4.2f} | Final: {r.metrics.final_equity:12,.0f}")

    # 5. Risk Control Breakdown: Fast Stop vs No Stop
    print("\n[5] RISK CONTROL ABLATION STUDY:")
    ablation_configs = [
        ("Standard Trailing 10% Only (No Fast Stop)", None, None),
        ("Add Fast Hard Stop -6.5% Only", 0.065, None),
        ("Add Fast Hard Stop -6.5% + Break-Even Lock +12%", 0.065, 0.12),
    ]
    for label, fhs, be in ablation_configs:
        r = sim.run(
            bars_dict=data,
            universe=UNIVERSE,
            benchmark_symbol=BENCHMARK,
            top_n=2,
            top1_weight=0.65,
            top2_weight=0.35,
            fast_hard_stop=fhs,
            breakeven_trigger=be,
            trailing_stop_pct=0.10,
            macro_filter=True,
        )
        print(f"  {label:50s} | CAGR: {r.metrics.cagr * 100:5.2f}% | MaxDD: {r.metrics.max_drawdown * 100:5.2f}% | Trades: {r.metrics.total_trades} | Exits: {r.metrics.exit_attribution}")

    # 6. Calendar Year Alpha Attribution
    print("\n[6] ANNUAL CALENDAR ALPHA RETURNS:")
    for yr, ret in sorted(m.year_returns.items()):
        print(f"  {yr}: {ret * 100:6.2f}%")

    # 7. Historical Stress Regimes
    print("\n[7] HISTORICAL STRESS REGIMES:")
    for reg, r_val in sorted(m.regime_returns.items()):
        print(f"  {reg:20s}: {r_val * 100:6.2f}%")

    # Prepare receipt dictionary
    receipt = {
        "strategy_name": "ashare_ekf_mpc_momentum",
        "benchmark": "000300.SH",
        "start_date": dates[0],
        "end_date": dates[-1],
        "total_sessions": len(dates),
        "total_years": round(years, 2),
        "benchmark_metrics": {
            "cagr": round(b300_cagr, 4),
            "max_drawdown": round(b300_max_dd, 4),
            "final_return": round(b300_final / b300_initial - 1.0, 4),
        },
        "base_metrics": {
            "initial_capital": m.initial_capital,
            "final_equity": round(m.final_equity, 2),
            "cagr": round(m.cagr, 4),
            "max_drawdown": round(m.max_drawdown, 4),
            "sharpe_ratio": round(m.sharpe_ratio, 2),
            "calmar_ratio": round(m.calmar_ratio, 2),
            "annualized_volatility": round(m.annualized_volatility, 4),
            "annual_turnover": round(m.annual_turnover, 2),
            "total_trades": m.total_trades,
            "win_rate": round(m.win_rate, 4),
            "profit_loss_ratio": round(m.profit_loss_ratio, 2),
            "exit_attribution": m.exit_attribution,
        },
        "four_standard_curves": {
            "base": {
                "cagr": round(master_res.metrics.cagr, 4),
                "max_drawdown": round(master_res.metrics.max_drawdown, 4),
                "sharpe": round(master_res.metrics.sharpe_ratio, 2),
                "calmar": round(master_res.metrics.calmar_ratio, 2),
            },
            "double_cost": {
                "cagr": round(res_double_cost.metrics.cagr, 4),
                "max_drawdown": round(res_double_cost.metrics.max_drawdown, 4),
                "sharpe": round(res_double_cost.metrics.sharpe_ratio, 2),
                "calmar": round(res_double_cost.metrics.calmar_ratio, 2),
            },
            "extra_day_delay": {
                "cagr": round(res_delay.metrics.cagr, 4),
                "max_drawdown": round(res_delay.metrics.max_drawdown, 4),
                "sharpe": round(res_delay.metrics.sharpe_ratio, 2),
                "calmar": round(res_delay.metrics.calmar_ratio, 2),
            },
            "double_cost_extra_day": {
                "cagr": round(res_double_delay.metrics.cagr, 4),
                "max_drawdown": round(res_double_delay.metrics.max_drawdown, 4),
                "sharpe": round(res_double_delay.metrics.sharpe_ratio, 2),
                "calmar": round(res_double_delay.metrics.calmar_ratio, 2),
            },
        },
        "year_returns": {k: round(v, 4) for k, v in m.year_returns.items()},
        "regime_returns": {k: round(v, 4) for k, v in m.regime_returns.items()},
        "research_only": True,
        "orders_authorized": False,
    }

    # Write receipt
    out_dir = ROOT / "state" / "research_runs" / "ashare_ekf_mpc_20261011"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)
    print(f"\n[RECEIPT SAVED]: {summary_path}")

    return receipt


if __name__ == "__main__":
    DATA_FILE = ROOT / "data" / "processed" / "clean_sectors_daily_2013_2026.json"
    if not DATA_FILE.exists():
        print(f"Error: {DATA_FILE} does not exist.")
        sys.exit(1)
    run_ekf_mpc_study(DATA_FILE)
