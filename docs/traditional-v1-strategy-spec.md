# Traditional V1 Strategy Specification (Clean Base)

## 1. Core Philosophy
A strict, rules-based dual-momentum sector rotation strategy. It enforces a fixed risk budget and separates the signal generation (1x underlying index) from the execution vehicle (3x leveraged ETF) to prevent volatility drag from polluting the trend signals.

## 2. Asset Universe
| Sector | 1x Signal Proxy | 3x Execution Vehicle |
| ------ | --------------- | -------------------- |
| Tech   | QQQ             | TQQQ                 |
| Semis  | SOXX (or equiv) | SOXL                 |
| Fin    | XLF             | FAS                  |
| Health | XLV             | CURE                 |
| Small  | IWM             | URTY                 |
| RealEst| XLRE            | DRN                  |
| Energy | XLE             | ERX                  |
*Defensive Asset*: BIL (1-3 Month T-Bill)

## 3. Position Sizing & Risk Budget
- **Total Risk Sleeve**: Fixed at 10% of portfolio.
- **Defensive Sleeve**: Fixed at 90% of portfolio (invested in BIL).
- **Internal Allocation**: The 10% risk sleeve is divided equally among the Top 2 qualified assets (5% each).

## 4. Signal & Rotation Engine (Monthly)
- **Schedule**: Calculated on the close of the signal day, executed on the open/close of the next trading day.
- **Momentum Score**: `Score_i = 0.5 * R_63 + 0.5 * R_126` (using 1x proxies).
- **Qualification Filters**: 
  1. 90-day return > 0.
  2. Current Price > SMA200.
- **Selection**: Rank qualified assets by Momentum Score. Select the Top 2. If < 2 assets qualify, the unused risk budget defaults to BIL.

## 5. Z-Score Overbought Trim (Auxiliary)
- **Metric**: Robust Z-score of the distance from SMA200 on the 1x proxy: 
  `d_t = ln(P_t / SMA200_t)`
  `Z_t = (d_t - Median(d_{t-252:t})) / (1.4826 * MAD(d_{t-252:t}))`
- **Trimming Logic (Applied to Risk Sleeve)**:
  - If $Z \ge 1.5$: Trim corresponding asset's allocation by 50% (e.g., 5% becomes 2.5%, remainder to BIL).
  - *No negative Z-score dip buying.*

## 6. Performance Measurement
- **TWR (Time-Weighted Return)**: Used for evaluating strategy edge.
- **XIRR (Money-Weighted Return)**: Used only for personal portfolio tracking with external cash flows. External cash injections flow into BIL and do not artificially inflate daily returns.
