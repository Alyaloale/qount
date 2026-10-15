from qount.research.universal_regime_expectancy import run_regime_backtest

res = run_regime_backtest(min_atr_pct=0.0095, orthogonal_tier_limit=True)
t_2022 = [t for t in res["trades"] if t["entry_date"].startswith("2022")]
for t in t_2022:
    print(f"{t['entry_date']} | {t['symbol']} | {t['type']} | ${t['net_pnl_usd']:+.2f} | {t['exit_reason']}")
