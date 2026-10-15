import sys
from qount.research.universal_regime_expectancy import (
    load_etf_bars,
    compute_ema,
    run_regime_backtest,
    ALL_10_MACRO_SYMBOLS,
)
import datetime as dt

spy_bars = load_etf_bars("SPY", data_dir="data/raw")
spy_closes = [b.c for b in spy_bars]
spy_ema50 = compute_ema(spy_closes, 50)
spy_ema200 = compute_ema(spy_closes, 200)

print(f"{'Year':<6} | {'Total Bars':<10} | {'Close < EMA200':<15} | {'EMA50 < EMA200':<15} | {'Macro Bear Lockout':<20}")
print("-" * 75)

for y in ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]:
    total = 0
    c_below = 0
    cross_below = 0
    bear_lockout = 0
    for i, b in enumerate(spy_bars):
        if b.d.startswith(y):
            total += 1
            if b.c < spy_ema200[i]:
                c_below += 1
            if spy_ema50[i] < spy_ema200[i]:
                cross_below += 1
            if b.c < spy_ema200[i] or spy_ema50[i] < spy_ema200[i]:
                bear_lockout += 1
    pct = bear_lockout / total * 100 if total else 0
    print(f"{y:<6} | {total:<10} | {c_below:<15} | {cross_below:<15} | {bear_lockout} ({pct:.1f}%)")
