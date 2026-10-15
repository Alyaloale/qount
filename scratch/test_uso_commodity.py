from qount.research.universal_regime_expectancy import run_regime_backtest, ALL_10_MACRO_SYMBOLS
import qount.research.universal_regime_expectancy as ure

# Replace UUP with USO
syms = [s if s != "UUP" else "USO" for s in ALL_10_MACRO_SYMBOLS]
orig_non_eq = ure.NON_EQUITY_SYMBOLS
ure.NON_EQUITY_SYMBOLS = ["GLD", "CPER", "TLT", "USO"]

res = ure.run_regime_backtest(symbols=syms, orthogonal_tier_limit=True)
print(f"USO in Non-Equity: Ret={res['return_pct']:+.2f}%, MDD={res['mdd_pct']:.2f}%, Calmar={res['calmar']:.2f}")

c_22 = [p[1] for p in res["curve"] if p[0].startswith("2022")]
r_22 = ((c_22[-1] - c_22[0]) / c_22[0] * 100) if c_22 else 0.0
print(f"2022 Return: {r_22:+.2f}%")

trades_22 = [t for t in res["trades"] if t["entry_date"].startswith("2022")]
print(f"2022 Trades count: {len(trades_22)}")
for t in trades_22:
    print(f"  {t['entry_date']} | {t['symbol']} | ${t['net_pnl_usd']:+.2f} | {t['exit_reason']}")

