import sys
from qount.research.universal_regime_expectancy import run_regime_backtest, ALL_10_MACRO_SYMBOLS

# Test 1: Baseline 10 symbols
res_base = run_regime_backtest(orthogonal_tier_limit=True)

# Test 2: Drop UUP (since UUP is FX and caused $53 loss in 2022)
syms_no_uup = [s for s in ALL_10_MACRO_SYMBOLS if s != "UUP"]
res_no_uup = run_regime_backtest(symbols=syms_no_uup, orthogonal_tier_limit=True)

# Test 3: Allow Max 2 Equities in strong bull market (dynamic equity quota)
# Let's inspect the returns by year for base vs no_uup
years = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]

print(f"{'Year':<6} | {'Base Return':<13} | {'No-UUP Return':<14} | {'Base 2022 Trades'}")
print("-" * 65)

for y in years:
    c_b = [p[1] for p in res_base["curve"] if p[0].startswith(y)]
    r_b = ((c_b[-1] - c_b[0]) / c_b[0] * 100) if c_b else 0.0

    c_no = [p[1] for p in res_no_uup["curve"] if p[0].startswith(y)]
    r_no = ((c_no[-1] - c_no[0]) / c_no[0] * 100) if c_no else 0.0

    print(f"{y:<6} | {r_b:+6.2f}%       | {r_no:+6.2f}%        |")

print("\n" + "=" * 65)
print(f"Base Total Ret: {res_base['return_pct']:+.2f}%, MDD: {res_base['mdd_pct']:.2f}%, Calmar: {res_base['calmar']:.2f}")
print(f"No-UUP Total Ret: {res_no_uup['return_pct']:+.2f}%, MDD: {res_no_uup['mdd_pct']:.2f}%, Calmar: {res_no_uup['calmar']:.2f}")

