from qount.research.universal_regime_expectancy import load_etf_bars, compute_ema

spy_bars = load_etf_bars("SPY")
closes = [b.c for b in spy_bars]
ema50 = compute_ema(closes, 50)
ema200 = compute_ema(closes, 200)

for i, b in enumerate(spy_bars):
    if b.d.startswith("2020"):
        c = b.c
        e50 = ema50[i]
        e200 = ema200[i]
        # check death cross and golden cross
        if i > 0:
            prev_e50 = ema50[i-1]
            prev_e200 = ema200[i-1]
            if prev_e50 >= prev_e200 and e50 < e200:
                print(f"DEATH CROSS on {b.d}: Close={c:.2f}, EMA50={e50:.2f}, EMA200={e200:.2f}")
            if prev_e50 <= prev_e200 and e50 > e200:
                print(f"GOLDEN CROSS on {b.d}: Close={c:.2f}, EMA50={e50:.2f}, EMA200={e200:.2f}")
