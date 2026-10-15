from qount.research.universal_regime_expectancy import run_regime_backtest

res_base = run_regime_backtest(orthogonal_tier_limit=True)
res_no_tier = run_regime_backtest(orthogonal_tier_limit=False)

years = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
print(f"{'Year':<6} | {'With Tier Limit (Max 1 Eq)':<28} | {'No Tier Limit (Max 2 Eq)':<28}")
print("-" * 65)

for y in years:
    c_b = [p[1] for p in res_base["curve"] if p[0].startswith(y)]
    r_b = ((c_b[-1] - c_b[0]) / c_b[0] * 100) if c_b else 0.0

    c_nt = [p[1] for p in res_no_tier["curve"] if p[0].startswith(y)]
    r_nt = ((c_nt[-1] - c_nt[0]) / c_nt[0] * 100) if c_nt else 0.0

    print(f"{y:<6} | {r_b:+6.2f}%                       | {r_nt:+6.2f}%")

print("-" * 65)
print(f"Total  | {res_base['return_pct']:+6.2f}%, MDD={res_base['mdd_pct']:5.2f}%         | {res_no_tier['return_pct']:+6.2f}%, MDD={res_no_tier['mdd_pct']:5.2f}%")
