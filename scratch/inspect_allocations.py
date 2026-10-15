import sys
from qount.research.universal_regime_expectancy import (
    run_regime_backtest,
    ALL_10_MACRO_SYMBOLS,
)

res = run_regime_backtest(
    symbols=ALL_10_MACRO_SYMBOLS,
    mode='1X_SPOT',
    causality_mode='RIGOROUS',
    start_date='2020-01-01',
    end_date='2026-07-30',
    orthogonal_tier_limit=True,
    mr_require_green=True,
)

trades = res['trades']
print(f"Total trades: {len(trades)}")
# Let's inspect entry prices, quantities, and notional
allocations = []
for t in trades:
    notional = t['quantity'] * t['entry_price']
    # equity_after is recorded on exit. Let's inspect notional range
    allocations.append(notional)

print(f"Average Notional per trade: ${sum(allocations)/len(allocations):.2f}")
print(f"Min Notional: ${min(allocations):.2f}, Max Notional: ${max(allocations):.2f}")
