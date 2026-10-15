import sys
from collections import defaultdict
from qount.research.universal_regime_expectancy import run_regime_backtest, ALL_10_MACRO_SYMBOLS, load_etf_bars

# Lets inspect what happens if we simulate a short component or if shorting is viable
print("Analyzing the behavior of shorting in ETF markets...")
# We will inspect the downside trends of SPY, SMH, TLT, GLD in 2020, 2021, 2022
for s in ["SPY", "SMH", "TLT", "GLD", "IWM"]:
    bars = load_etf_bars(s)
    b_dict = {b.d: b for b in bars}
    
    # Check 2022 performance
    b_2022 = [b for b in bars if b.d.startswith("2022")]
    if b_2022:
        open_2022 = b_2022[0].o
        close_2022 = b_2022[-1].c
        min_2022 = min(b.l for b in b_2022)
        print(f"{s} 2022: Open={open_2022:.2f}, Close={close_2022:.2f}, Ret={(close_2022-open_2022)/open_2022*100:+.2f}%, Max Down={(min_2022-open_2022)/open_2022*100:+.2f}%")

