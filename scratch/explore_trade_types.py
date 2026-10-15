import sys
from collections import defaultdict
from qount.research.universal_regime_expectancy import (
    load_etf_bars, compute_ema, compute_atr, compute_kaufman_er,
    compute_profile_state, ALL_10_MACRO_SYMBOLS, NON_EQUITY_SYMBOLS,
    run_regime_backtest
)

res = run_regime_backtest(
    symbols=ALL_10_MACRO_SYMBOLS,
    mode='1X_SPOT',
    causality_mode='RIGOROUS',
    start_date='2020-01-01',
    end_date='2026-07-30',
    min_atr_pct=0.0085,
    orthogonal_tier_limit=True,
)

type_stats = defaultdict(lambda: {'count': 0, 'pnl': 0.0, 'wins': 0})
for t in res['trades']:
    tt = t['type']
    type_stats[tt]['count'] += 1
    type_stats[tt]['pnl'] += t['net_pnl_usd']
    if t['net_pnl_usd'] > 0:
        type_stats[tt]['wins'] += 1

print("Baseline trade type breakdown:")
for tt, st in sorted(type_stats.items(), key=lambda x: x[1]['pnl'], reverse=True):
    wr = st['wins']/st['count']*100 if st['count']>0 else 0
    print(f"  {tt:<25}: count={st['count']:>3}, PnL=${st['pnl']:>+7.2f}, WinRate={wr:>5.1f}%")
