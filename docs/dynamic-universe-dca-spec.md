# High-Breadth Cross-Asset Dynamic DCA Strategy Specification

## 1. Core Philosophy
The Strategy aims to capture volatility premiums across highly uncorrelated asset classes (Crypto, Equities, Fixed Income, Commodities) while minimizing cash drag and survivorship bias. It uses a **Point-in-Time Universe Selection** to dynamically route capital to the most volatile assets, and a **Unified Reserve Pool (Z-Score DCA)** to manage exposure.

## 2. Architecture & Tool Division
- **Data Collection (L1 Passive)**: Daily close prices of a cross-asset universe (Crypto Proxies/Spot, Mega-Cap Tech, Core ETFs).
- **Universe Selection (Cross-Sectional Ranker)**: Monthly re-evaluation. Ranks all assets by trailing 90-day realized volatility. Selects the top N assets to maximize breadth and volatility capture.
- **Execution (Z-Score DCA)**: Calculates 200-day Z-Score for selected assets. Adjusts target weights to build a cash reserve during overheated periods (Z > 1.0) and aggressively deploy cash during crashes (Z < -1.0).

## 3. Rules & Parameters
- **Initial Capital**: $1,000 (Base Scenario)
- **Continuous Injection**: $10 / week added to the `Reserve Pool`.
- **Target Cross-Asset Universe**: 
  - **Crypto**: `GBTC` (Bitcoin Proxy), `ETHE` (Ethereum Proxy)
  - **Mega-Cap Stocks**: `TSLA`, `NVDA`, `AAPL`
  - **ETFs (Broad & Thematic)**: `ARKK` (Innovation), `SPY` (US Equity), `TLT` (20+ Yr Treasury), `GLD` (Gold)
- **Active Assets**: Top 3 by 90-day Realized Volatility, evaluated on the 1st of every month.
- **Z-Score Mapping**:
  - $Z \ge 1.0 \rightarrow Target = 0.5$ (Take profits to Reserve Pool)
  - $Z \le -1.0 \rightarrow Target = 1.0$ (Deploy Reserve Pool)
  - In-between: Linear interpolation.
- **Inactive Asset Handling**: If an asset drops out of the Top 3, new capital is no longer allocated to it. Existing shares are held, but if its $Z \ge 1.0$, it is liquidated to the Reserve Pool to lock in profits.
