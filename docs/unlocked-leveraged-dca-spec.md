# Unlocked Sector Dual-Momentum 3x Leveraged DCA (Max Yield Build)

> [!WARNING]
> **HIGH RISK PROFILE (MAX CAGR)**
> This strategy specification has been stripped of the SMA200 structural safeguards to maximize Compound Annual Growth Rate (CAGR). It is designed to aggressively "catch falling knives" during market crashes to maximize rebound profits. Expect drawdowns exceeding -60%. Only deploy capital that you are prepared to lose in extreme Black Swan liquidation events.

## 1. Core Philosophy
This is the "Ultra-Aggressive" expression of the Qount personal quantitative engine. It abandons safety nets to maximize the geometric compounding of 3x leveraged ETFs. By eliminating the moving-average filter, it stays fully invested during sharp V-shaped market crashes (e.g., March 2020), ensuring it never misses a deep-bottom DCA entry.

## 2. The Universal Sector Pool (3x Leveraged)
The system surveys the 7 core pillars of the US economy using their 3x leveraged ETF proxies:
1. `TQQQ`: Tech / Nasdaq
2. `SOXL`: Semiconductors
3. `FAS`: Financials
4. `CURE`: Healthcare
5. `URTY`: Small Caps / Russell 2000
6. `DRN`: Real Estate
7. `ERX`: Traditional Energy

## 3. The Three-Pillar Engine (Unlocked)

### A. The Radar: Absolute Momentum Rotation (No SMA Filter)
- **Schedule**: Evaluated on the 1st trading day of every month.
- **Metric**: 90-day return (Time-Series Momentum).
- **Rule**: Rank all 7 ETFs. Select the Top 2. 
- **Absolute Filter**: If an ETF's 90-day momentum is $< 0$, it is disqualified. If all sectors are negative, park in cash.
- **Unlocked Rule**: *Unlike the Safeguarded version, there is NO SMA200 trend filter.* The system will aggressively buy assets that have crashed below their 200-day moving average, provided their 90-day momentum is still mathematically positive.

### B. The Ammo: Unified Reserve Pool
- **Capital**: $1,000 initial + $10/week constant injection.
- **Storage**: Unused capital sits in a cash pool, ready to deploy.
- **Unlocked Rule**: *No stepped cash limits.* The system is authorized to deploy all available cash if the Z-Score drops low enough.

### C. The Trigger: Z-Score Position Sizing
- **Metric**: 200-day Z-Score for the chosen active ETFs.
- **Mapping (Target Equity Exposure)**:
  - $Z \ge 1.0$: Target = 0.5 (Sell 50% of the target equity exposure to lock in profits and reload the Reserve Pool).
  - $Z \le -1.0$: Target = 1.0 (Deploy maximum cash to aggressively buy the blood).
  - $-1.0 < Z < 1.0$: Linear scaling between 1.0 and 0.5.
- **Asymmetric Profit Holding**: Never liquidate fully (Target never goes below 0.5). This ensures we remain heavily invested during parabolic 3x ETF blow-off tops.

## 4. Performance Expectations (10-Year Backtest)
Based on 10-year historical simulations (2016-2026):
- **Annualized Return (CAGR)**: ~24.36%
- **Max Drawdown**: ~63.44%
- **Trade-off Achieved**: Trades away the -51% drawdown limit of the Safeguarded version in exchange for a massive ~5% permanent boost in annualized yield.
