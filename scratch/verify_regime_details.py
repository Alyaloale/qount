import sys
from collections import defaultdict
from qount.research.universal_regime_expectancy import (
    run_regime_backtest,
    ALL_10_MACRO_SYMBOLS,
    NON_EQUITY_SYMBOLS,
)

res = run_regime_backtest(
    symbols=ALL_10_MACRO_SYMBOLS,
    mode="1X_SPOT",
    causality_mode="RIGOROUS",
    start_date="2020-01-01",
    end_date="2026-07-30",
    orthogonal_tier_limit=True,
)

trades = res["trades"]
print("Total trades:", len(trades))
print(f"Overall Return: {res['return_pct']:+.2f}%, MDD: {res['mdd_pct']:.2f}%, Win: {res['win_rate']:.1f}%, Calmar: {res['calmar']:.2f}")

# Check symbol PnL
sym_data = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0})
for t in trades:
    s = t["symbol"]
    sym_data[s]["count"] += 1
    sym_data[s]["pnl"] += t["net_pnl_usd"]
    if t["net_pnl_usd"] > 0:
        sym_data[s]["wins"] += 1

print("\n--- Symbol Attribution ---")
for s in sorted(sym_data.keys(), key=lambda x: sym_data[x]["pnl"], reverse=True):
    d = sym_data[s]
    wr = d["wins"] / d["count"] * 100 if d["count"] else 0
    print(f"{s:<6}: PnL = ${d['pnl']:>7.2f}, Trades = {d['count']:>2}, WinRate = {wr:>5.1f}%")

# Check Annual Returns & MDD
print("\n--- Annual Breakdown ---")
years = ["2020", "2021", "2022", "2023", "2024", "2025-2026"]
for yr in years:
    s_d = f"{yr}-01-01" if "-" not in yr else "2025-01-01"
    e_d = f"{yr}-12-31" if "-" not in yr else "2026-07-30"
    r_yr = run_regime_backtest(
        symbols=ALL_10_MACRO_SYMBOLS,
        mode="1X_SPOT",
        causality_mode="RIGOROUS",
        start_date=s_d,
        end_date=e_d,
        orthogonal_tier_limit=True,
    )
    print(f"{yr:<9}: Ret = {r_yr['return_pct']:>+6.2f}%, MDD = {r_yr['mdd_pct']:>5.2f}%, Win = {r_yr['win_rate']:>5.1f}%, Trades = {r_yr['trade_count']:>2}")

# Check Gap stress
print("\n--- Gap Stress Testing ---")
for gap in [0.0, 0.010, 0.015, 0.020, 0.030]:
    r = run_regime_backtest(
        symbols=ALL_10_MACRO_SYMBOLS,
        mode="1X_SPOT",
        causality_mode="RIGOROUS",
        start_date="2020-01-01",
        end_date="2026-07-30",
        orthogonal_tier_limit=True,
        gap_stress_pct=gap,
    )
    print(f"Gap {gap*100:4.1f}%: Ret = {r['return_pct']:>+6.2f}%, MDD = {r['mdd_pct']:>5.2f}%, Calmar = {r['calmar']:>5.2f}")

# Exit reason breakdown
print("\n--- Exit Reason Breakdown ---")
exit_reasons = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
for t in trades:
    r = t["exit_reason"]
    exit_reasons[r]["count"] += 1
    exit_reasons[r]["pnl"] += t["net_pnl_usd"]
    if t["net_pnl_usd"] > 0:
        exit_reasons[r]["wins"] += 1
for r in sorted(exit_reasons.keys(), key=lambda x: exit_reasons[x]["pnl"], reverse=True):
    d = exit_reasons[r]
    wr = d["wins"] / d["count"] * 100 if d["count"] else 0
    print(f"{r:<18}: PnL = ${d['pnl']:>7.2f}, Count = {d['count']:>2}, WinRate = {wr:>5.1f}%")
