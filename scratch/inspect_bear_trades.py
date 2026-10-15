import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from qount.research.universal_regime_expectancy import (
    load_etf_bars, compute_ema, compute_atr, compute_kaufman_er,
    compute_profile_state, ALL_10_MACRO_SYMBOLS, NON_EQUITY_SYMBOLS,
    run_regime_backtest
)
from scratch.test_causal_architecture import run_audited_strategy

res = run_audited_strategy(start_date='2020-01-01', end_date='2022-12-31')
print(f"2020-2022 Loss Trades Count: {len(res['trades'])}")
print(f"Net Return: {res['return_pct']:.2f}%, MDD: {res['mdd_pct']:.2f}%")

print("\nAll trades in 2020-2022 sorted by PnL:")
for t in sorted(res['trades'], key=lambda x: x['net_pnl_usd']):
    print(f"  {t['date']} | {t['symbol']:<5} | {t['type']:<22} | Entry: {t['entry_date']} | Exit: {t['exit_reason']:<13} | PnL: ${t['net_pnl_usd']:>+6.2f} | R: {t['net_R']:>+5.2f}")
