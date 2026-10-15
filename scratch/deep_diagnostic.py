from qount.research.universal_regime_expectancy import load_etf_bars, run_regime_backtest, ALL_10_MACRO_SYMBOLS

# 1. Check what XLE did in 2022
try:
    xle_bars = load_etf_bars("XLE")
    xle_2022 = [b for b in xle_bars if b.d.startswith("2022")]
    if xle_2022:
        xle_ret = (xle_2022[-1].c - xle_2022[0].o) / xle_2022[0].o * 100.0
        print(f"XLE 2022 Return: {xle_ret:+.2f}%")
except Exception as e:
    print(f"XLE error: {e}")

# 2. Check trades that blocked SMH in 2021
res = run_regime_backtest(orthogonal_tier_limit=True)
trades_2021 = [t for t in res["trades"] if t["entry_date"].startswith("2021")]
print(f"\nTotal trades in 2021: {len(trades_2021)}")
for t in trades_2021:
    print(f"{t['entry_date']} -> {t['exit_date']} | {t['symbol']:<5} | PnL: ${t['net_pnl_usd']:+7.2f} | Reason: {t['exit_reason']}")

