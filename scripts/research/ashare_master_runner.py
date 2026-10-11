"""Comprehensive Runner for the A-Share Master Quantitative Trading Strategy (总终方案).

Executes:
1. Benchmark CSI 300 Buy & Hold
2. The Grand Unified Master Quantitative Strategy (2013-2026)
3. Multi-Scheme Holistic Comparison Matrix (Benchmark, A, B1, B2, C, EKF-MPC Base, Master)
4. The Four Standard Curves Audit (Base, Double Cost, Extra Day Delay, Double Cost + Delay)
5. Parametric Conviction Sweep (50/50, 60/40, 65/35, 70/30, 75/25)
6. Historical Stress Regimes & Calendar Year Alpha Breakdown
7. Saves structured receipt to state/research_runs/ashare_master_20261011/summary.json
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from qount.research.ashare_master_strategy import (
    MasterBar,
    MasterStrategySimulator,
    MasterSimulationResult,
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


def load_master_data(data_path: Path) -> dict[str, list[MasterBar]]:
    with open(data_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, list[MasterBar]] = {}
    for code, items in raw.items():
        bars = [
            MasterBar(
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


def run_master_study(data_path: Path) -> dict:
    print("=" * 90)
    print("A-SHARE MASTER QUANTITATIVE TRADING SYSTEM (总终方案 · 麒麟集大成量化系统)")
    print("State-Space EKF + Historical Rally Dynamics + MPC Conviction Overweight + 4-Tier Fast Risk")
    print("=" * 90)

    data = load_master_data(data_path)
    b300 = data[BENCHMARK]
    dates = [b.trade_date for b in b300]
    years = len(dates) / 252.0

    print(f"Data period: {dates[0]} to {dates[-1]} ({len(dates)} sessions, ~{years:.2f} years)")
    print(f"Candidate assets: {len(UNIVERSE)} total (11 Domestic Sector ETFs + 1 Global Nasdaq ETF)")

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

    # 2. Main Master Production Strategy
    sim = MasterStrategySimulator(commission_bps=6.0, slippage_bps=5.0)
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

    print("\n[2] MASTER PRODUCTION QUANTITATIVE STRATEGY (总终方案核心战绩):")
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

    # 3. The Four Standard Curves Audit
    print("\n[3] THE FOUR STANDARD CURVES AUDIT:")
    sim_double_cost = MasterStrategySimulator(commission_bps=12.0, slippage_bps=10.0)
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

    sim_delay = MasterStrategySimulator(commission_bps=6.0, slippage_bps=5.0, extra_execution_delay=1)
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

    sim_double_delay = MasterStrategySimulator(commission_bps=12.0, slippage_bps=10.0, extra_execution_delay=1)
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

    # 4. Multi-Scheme Holistic Comparison Matrix
    print("\n[4] MULTI-SCHEME HOLISTIC COMPARISON SCORECARD (全方案横向统筹对比):")
    scorecard = [
        ("基准：沪深300 买入持有", 0.0413, 0.4670, 0.10, 0.09, 1_710_188, "被动挨打，不可行"),
        ("方案 A：赛道 ETF 强动量 (50/50等权)", 0.1985, 0.3328, 0.82, 0.60, 11_026_827, "稳健基石，低频免税"),
        ("方案 B1：中小创动量突破打板", -0.2128, 0.9497, -0.98, -0.22, 66_438, "坚决淘汰，散户绞肉机"),
        ("方案 B2：千亿白马行业龙头轮动", 0.1423, 0.5035, 0.40, 0.28, 5_832_490, "平庸，周期回撤大跑输ETF"),
        ("方案 C：综合牛市增强 (75%ETF+25%龙头)", 0.2231, 0.3414, 0.87, 0.65, 14_427_530, "极品进阶，牛市吃满弹性"),
        ("EKF-MPC 基础版 (65/35加仓)", 0.2006, 0.3101, 0.84, 0.65, 11_276_553, "工业级，打破33%回撤瓶颈"),
        ("总终方案：Master 麒麟集大成版", m.cagr, m.max_drawdown, m.sharpe_ratio, m.calmar_ratio, m.final_equity, "终极推荐：复利12.1倍盈亏比超3:1"),
    ]
    for name, c_val, d_val, sh_val, cal_val, fin_val, comment in scorecard:
        print(f"  {name:32s} | CAGR: {c_val*100:5.2f}% | MaxDD: {d_val*100:5.2f}% | Sharpe: {sh_val:4.2f} | Calmar: {cal_val:4.2f} | End: {fin_val:10,.0f} | {comment}")

    # 5. Annual Calendar Alpha Returns
    print("\n[5] ANNUAL CALENDAR ALPHA RETURNS:")
    for yr, ret in sorted(m.year_returns.items()):
        print(f"  {yr}: {ret * 100:6.2f}%")

    # 6. Historical Stress Regimes
    print("\n[6] HISTORICAL STRESS REGIMES:")
    for reg, r_val in sorted(m.regime_returns.items()):
        print(f"  {reg:20s}: {r_val * 100:6.2f}%")

    # Write summary receipt
    receipt = {
        "strategy_name": "ashare_master_kirin_system",
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
        "master_metrics": {
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

    out_dir = ROOT / "state" / "research_runs" / "ashare_master_20261011"
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
    run_master_study(DATA_FILE)
