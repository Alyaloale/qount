from qount.research.universal_regime_expectancy import load_etf_bars, ALL_10_MACRO_SYMBOLS

print(f"{'Symbol':<6} | {'2021 Open':<10} | {'2021 Close':<10} | {'2021 Return':<12}")
print("-" * 45)
for s in ALL_10_MACRO_SYMBOLS:
    bars = load_etf_bars(s)
    y_bars = [b for b in bars if b.d.startswith("2021")]
    if y_bars:
        ret = (y_bars[-1].c - y_bars[0].o) / y_bars[0].o * 100.0
        print(f"{s:<6} | {y_bars[0].o:10.2f} | {y_bars[-1].c:10.2f} | {ret:+8.2f}%")
