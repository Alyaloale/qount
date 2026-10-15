import sys
from qount.research.universal_regime_expectancy import (
    load_etf_bars,
    compute_ema,
    compute_atr,
    compute_kaufman_er,
    compute_profile_state,
)

bars = load_etf_bars("SMH", data_dir="data/raw")
closes = [b.c for b in bars]
atr14 = compute_atr(bars, 14)
ema20 = compute_ema(closes, 20)
ema50 = compute_ema(closes, 50)
ema200 = compute_ema(closes, 200)
ers = compute_kaufman_er(closes, 20)

print("Checking SMH in 2021...")
for i, b in enumerate(bars):
    if b.d.startswith("2021"):
        c_now = b.c
        cur_atr = atr14[i]
        er_val = ers[i]
        ema20_now = ema20[i]
        ema50_now = ema50[i]
        ema200_now = ema200[i]

        chan_high = max(x.h for x in bars[i - 20 : i])
        trend_aligned = (c_now > ema20_now) and (ema20_now > ema50_now)
        
        w_bars = bars[max(0, i - 30) : i + 1]
        s_code, s_name, poc_p, vah, val, pr, conc = compute_profile_state(w_bars, c_now, cur_atr)

        # Breakout check:
        # s_code in [1, 2] and c_now > chan_high and trend_aligned and er_val >= 0.28
        # breakout_quality_filter: (c_now - b.l) / (b.h - b.l) >= 0.65
        is_bo = (c_now > chan_high)
        if is_bo:
            reasons = []
            if s_code not in [1, 2]: reasons.append(f"s_code={s_code}({s_name})")
            if not trend_aligned: reasons.append("trend_not_aligned")
            if er_val < 0.28: reasons.append(f"er={er_val:.2f}<0.28")
            bar_rng = b.h - b.l
            if bar_rng > 0 and (b.c - b.l) / bar_rng < 0.65: reasons.append("wick_filter")
            
            # Print whenever breakout triggered or was blocked
            if not reasons:
                print(f"{b.d}: VALID BREAKOUT! s_code={s_code}, er={er_val:.2f}")
            else:
                if i % 10 == 0:
                    print(f"{b.d}: Blocked breakout: {', '.join(reasons)}")
