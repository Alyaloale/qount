from qount.research.universal_regime_expectancy import run_regime_backtest, ALL_10_MACRO_SYMBOLS

# Baseline
res_base = run_regime_backtest(orthogonal_tier_limit=True)

# 1. Macro Quadrant Repair: Replace XLB (materials) with XLE (energy)
# XLE provides true stagflation/inflation coverage
syms_with_xle = [s if s != "XLB" else "XLE" for s in ALL_10_MACRO_SYMBOLS]
res_xle = run_regime_backtest(symbols=syms_with_xle, orthogonal_tier_limit=True)

print(">>> 1. Macro Quadrant Coverage: Replace XLB with XLE (Energy):")
print(f"Base (with XLB): Ret={res_base['return_pct']:+.2f}%, MDD={res_base['mdd_pct']:.2f}%, Calmar={res_base['calmar']:.2f}")
print(f"XLE (with Energy): Ret={res_xle['return_pct']:+.2f}%, MDD={res_xle['mdd_pct']:.2f}%, Calmar={res_xle['calmar']:.2f}")

# Check 2022 performance comparison
c_base_2022 = [p[1] for p in res_base["curve"] if p[0].startswith("2022")]
r_b22 = ((c_base_2022[-1] - c_base_2022[0]) / c_base_2022[0] * 100) if c_base_2022 else 0.0

c_xle_2022 = [p[1] for p in res_xle["curve"] if p[0].startswith("2022")]
r_x22 = ((c_xle_2022[-1] - c_xle_2022[0]) / c_xle_2022[0] * 100) if c_xle_2022 else 0.0

print(f"2022 Return with Base: {r_b22:+.2f}%")
print(f"2022 Return with XLE:  {r_x22:+.2f}%")

