import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scratch.validate_strategy_proposal import run_causal_regime_backtest, ALL_10_MACRO_SYMBOLS

res_28 = run_causal_regime_backtest(
    symbols=ALL_10_MACRO_SYMBOLS,
    mode='1X_SPOT',
    start_date='2020-01-01',
    end_date='2026-07-30',
    min_atr_pct=0.0085,
    orthogonal_tier_limit=True,
    spy_lookahead_fixed=True,
    er_min=0.28,
)

print(f"Causal with Spec ER=0.28:")
print(f"  Return: {res_28['return_pct']:.2f}%")
print(f"  MDD: {res_28['mdd_pct']:.2f}%")
print(f"  Win Rate: {res_28['win_rate']:.1f}%")
print(f"  Trades: {res_28['trade_count']}")
print(f"  Calmar: {res_28['calmar']:.2f}")
print(f"  Profit Factor: {res_28['profit_factor']:.2f}")

# Recent window 2025-2026
res_28_recent = run_causal_regime_backtest(
    symbols=ALL_10_MACRO_SYMBOLS,
    mode='1X_SPOT',
    start_date='2025-01-01',
    end_date='2026-07-30',
    min_atr_pct=0.0085,
    orthogonal_tier_limit=True,
    spy_lookahead_fixed=True,
    er_min=0.28,
)
print(f"\n2025-2026 Sample:")
print(f"  Return: {res_28_recent['return_pct']:.2f}%")
print(f"  MDD: {res_28_recent['mdd_pct']:.2f}%")
print(f"  Win Rate: {res_28_recent['win_rate']:.1f}%")
print(f"  Calmar: {res_28_recent['calmar']:.2f}")
