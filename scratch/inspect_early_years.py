import sys
from collections import defaultdict
from qount.research.universal_regime_expectancy import run_regime_backtest, ALL_10_MACRO_SYMBOLS

res = run_regime_backtest(
    symbols=ALL_10_MACRO_SYMBOLS,
    mode="1X_SPOT",
    causality_mode="RIGOROUS",
    start_date="2020-01-01",
    end_date="2026-07-30",
    orthogonal_tier_limit=True,
)

trades = res["trades"]

for target_year in ["2020", "2021", "2022"]:
    print(f"\n{'='*30} TRADES IN {target_year} {'='*30}")
    y_trades = [t for t in trades if t["entry_date"].startswith(target_year)]
    print(f"{'Entry Date':<11} | {'Exit Date':<11} | {'Symbol':<5} | {'Type':<15} | {'Net PnL ($)':<12} | {'Net R':<6} | {'Exit Reason':<16}")
    print("-" * 85)
    for t in y_trades:
        print(f"{t['entry_date']:<11} | {t['exit_date']:<11} | {t['symbol']:<5} | {t['type']:<15} | ${t['net_pnl_usd']:+9.2f}  | {t['net_R']:+5.2f} | {t['exit_reason']:<16}")

