# Ultimate Sector Dual-Momentum 3x Leveraged DCA (Qount Final)

## 1. Core Philosophy
The ultimate expression of the Qount personal quantitative engine. It abandons sector bias (e.g., "AI will always win") in favor of mathematical trend-following across the entire US economy. By applying 3x leverage to the leading sector, it generates massive upside. By enforcing absolute momentum (cash-out on negative trends) and Z-Score DCA, it mathematically neuters the catastrophic drawdowns typical of leveraged ETFs.

## 2. The Universal Sector Pool (3x Leveraged)
The system surveys the 7 core pillars of the economy using their 3x leveraged ETF proxies:
1. `TQQQ`: Tech / Nasdaq
2. `SOXL`: Semiconductors
3. `FAS`: Financials
4. `CURE`: Healthcare
5. `URTY`: Small Caps / Russell 2000
6. `DRN`: Real Estate
7. `ERX`: Traditional Energy

## 3. The Three-Pillar Engine
### A. The Radar: Absolute Dual-Momentum
- **Schedule**: Evaluated on the 1st trading day of every month.
- **Metric**: 90-day return (Time-Series Momentum) + 200-day Simple Moving Average (SMA200).
- **Rule**: Rank all 7 ETFs by 90-day momentum. Select the Top 2. 
- **Absolute Filter**: If an ETF's 90-day momentum is $< 0$, OR its current price is below its SMA200 (bear market trend), it is instantly disqualified. 

### B. The Ammo: Stepped Reserve Pool
- **Capital**: $1,000 initial + $10/week constant injection.
- **Storage**: Unused capital sits in a cash pool, ready to deploy instantly when the Z-Score drops.
- **Cash Exhaustion Protection**: Cash deployment is strictly tiered to prevent running out of bullets prematurely.

### C. The Trigger: Z-Score Position Sizing
- **Metric**: 200-day Z-Score for the chosen active ETFs.
- **Mapping**:
  - $Z \ge 1.0$: Sell 50% of the target equity exposure to lock in profits.
  - $0 \le Z < 1.0$: Scale exposure between 50% and 75%.
  - $-1.0 \le Z < 0$: Deploy up to 30% of reserve cash.
  - $-2.0 \le Z < -1.0$: Deploy up to 60% of reserve cash.
  - $-3.0 \le Z < -2.0$: Deploy 100% of reserve cash (All-in panic buying).
- **Hard Stop**: If daily price falls below SMA200, all buying is strictly forbidden to prevent catching falling knives in structural bear markets.

## 4. Why This is the "Holy Grail" for Retail
- **No Overfitting**: It doesn't care if Semis fail and Healthcare cures cancer. It mathematically rotates to the winner.
- **Drawdown Protection**: It sidesteps the 80% drawdowns of 3x ETFs by automatically sitting in cash during macro bear markets.
- **Automated "Buy The Dip"**: When a leading sector experiences a severe but temporary pullback (Z-Score crashes to -1.5), the Reserve Pool automatically swoops in to buy cheap leveraged shares before the rebound.
