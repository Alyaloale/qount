from qount.research.universal_regime_expectancy import run_regime_backtest

res = run_regime_backtest()
mr_trades = [t for t in res["trades"] if "MEAN_REVERSION" in t["type"]]

print(f"Total MR Trades: {len(mr_trades)}")
for t in mr_trades:
    if t["entry_date"].startswith("2022"):
        print(f"2022 MR: {t['entry_date']} | {t['symbol']} | Net: ${t['net_pnl_usd']:+.2f} | Exit: {t['exit_reason']} | Exit Date: {t['exit_date']}")
