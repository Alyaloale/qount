from qount.research.universal_regime_expectancy import load_etf_bars, run_regime_backtest, ALL_10_MACRO_SYMBOLS

uso_bars = load_etf_bars("USO")
u_22 = [b for b in uso_bars if b.d.startswith("2022")]
if u_22:
    print(f"USO 2022 Return: {(u_22[-1].c - u_22[0].o) / u_22[0].o * 100:+.2f}%")

