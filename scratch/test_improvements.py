"""
Test systematic improvements to universal_regime_expectancy:
1. Macro/Trend filter on MEAN_REVERSION:
   - Does allowing MR only when c_now >= ema50 eliminate the 2022 SMH dump?
   - What is the impact across the full 2020-2026 dataset?
2. Stricter Breakout / Pullback filters:
   - Can we improve Breakout PF?
3. Cash Yield Accrual (Real-world idle cash management: SOFR / Fed Funds / SGOV):
   - What happens to CAGR, 2022 PnL, MDD, and Calmar?
"""

from collections import defaultdict
import datetime as dt
from qount.research.universal_regime_expectancy import run_regime_backtest, load_etf_bars, compute_ema, ALL_10_MACRO_SYMBOLS

# Base run
res_base = run_regime_backtest()
print(f"Base: Return={res_base['return_pct']:.2f}%, MDD={res_base['mdd_pct']:.2f}%, Calmar={res_base['calmar']:.2f}, Trades={res_base['trade_count']}, WinRate={res_base['win_rate']:.1f}%")

# Let's inspect 2022 trades in base
trades_2022 = [t for t in res_base['trades'] if t['entry_date'].startswith('2022')]
pnl_2022 = sum(t['net_pnl_usd'] for t in trades_2022)
print(f"2022 Base: {len(trades_2022)} trades, PnL = ${pnl_2022:.2f}")
for t in trades_2022:
    print(f"   {t['entry_date']} | {t['symbol']} | {t['type']} | ${t['net_pnl_usd']:+.2f} | {t['exit_reason']}")
