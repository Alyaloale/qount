from qount.research.universal_regime_expectancy import run_regime_backtest, ALL_10_MACRO_SYMBOLS

print(">>> Testing min_atr_pct=0.0085 (v1.5 Baseline) vs min_atr_pct=0.0095 (Clean Cash Defense):")
res_85 = run_regime_backtest(min_atr_pct=0.0085, orthogonal_tier_limit=True)
res_95 = run_regime_backtest(min_atr_pct=0.0095, orthogonal_tier_limit=True)

print(f"0.85%: Ret={res_85['return_pct']:+.2f}%, MDD={res_85['mdd_pct']:.2f}%, Calmar={res_85['calmar']:.2f}, Trades={res_85['trade_count']}, Win%={res_85['win_rate']:.1f}%")
print(f"0.95%: Ret={res_95['return_pct']:+.2f}%, MDD={res_95['mdd_pct']:.2f}%, Calmar={res_95['calmar']:.2f}, Trades={res_95['trade_count']}, Win%={res_95['win_rate']:.1f}%")

years = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
print("\nYearly Return & MDD comparison:")
print(f"{'Year':<6} | {'0.85% Ret':<10} | {'0.85% MDD':<10} | {'0.95% Ret':<10} | {'0.95% MDD':<10} | {'0.95% Trades'}")
print("-" * 65)

for y in years:
    c85 = [p[1] for p in res_85["curve"] if p[0].startswith(y)]
    r85 = ((c85[-1] - c85[0]) / c85[0] * 100) if c85 else 0.0
    pk85 = c85[0]
    mdd85 = 0.0
    for v in c85:
        if v > pk85: pk85 = v
        dd = (pk85 - v) / pk85
        if dd > mdd85: mdd85 = dd

    c95 = [p[1] for p in res_95["curve"] if p[0].startswith(y)]
    r95 = ((c95[-1] - c95[0]) / c95[0] * 100) if c95 else 0.0
    pk95 = c95[0]
    mdd95 = 0.0
    for v in c95:
        if v > pk95: pk95 = v
        dd = (pk95 - v) / pk95
        if dd > mdd95: mdd95 = dd

    y_trades = [t for t in res_95["trades"] if t["entry_date"].startswith(y)]
    print(f"{y:<6} | {r85:+6.2f}%    | {mdd85*100:5.2f}%     | {r95:+6.2f}%    | {mdd95*100:5.2f}%     | {len(y_trades)} trades")

# Check 2025-2026 Out-of-sample
res_95_oos = run_regime_backtest(min_atr_pct=0.0095, orthogonal_tier_limit=True, start_date="2025-01-01", end_date="2026-07-30")
print(f"\n2025-2026 OOS (0.95%): Ret={res_95_oos['return_pct']:+.2f}%, MDD={res_95_oos['mdd_pct']:.2f}%, Calmar={res_95_oos['calmar']:.2f}, Win%={res_95_oos['win_rate']:.1f}%, Trades={res_95_oos['trade_count']}")
