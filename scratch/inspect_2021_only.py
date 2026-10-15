import sys
from qount.research.universal_regime_expectancy import (
    run_regime_backtest,
    ALL_10_MACRO_SYMBOLS,
)

res = run_regime_backtest(
    symbols=ALL_10_MACRO_SYMBOLS,
    mode='1X_SPOT',
    causality_mode='RIGOROUS',
    start_date='2021-01-01',
    end_date='2021-12-31',
    orthogonal_tier_limit=True,
    mr_require_green=True,
)

print(f"2021 Trades: {len(res['trades'])}, PnL: {res['return_pct']:+.2f}%")
print(f"{'Entry Date':<11} | {'Exit Date':<11} | {'Sym':<5} | {'Type':<22} | {'PnL ($)':<8} | {'Exit Reason':<15}")
print("-" * 80)
for t in res['trades']:
    print(f"{t['entry_date']:<11} | {t['exit_date']:<11} | {t['symbol']:<5} | {t['type']:<22} | ${t['net_pnl_usd']:>7.2f} | {t['exit_reason']:<15}")
