# Traditional V1 Research & Evaluation Plan

## Phase A: Code & Metric Auditing
1. **Resolve Logic Conflicts**: Remove the contradictory Z-score dip-buying against SMA200 hard stops.
2. **Metric Separation**: Implement strict separation of TWR (Time-Weighted Return) for strategy edge evaluation and XIRR (Money-Weighted Return) for external cash flows.
3. **Execution Realism**: Enforce signal calculation at `T` close, and execution at `T+1`.
4. **Data Integrity**: Ensure Total Return (dividend and split adjusted) data is used.
5. **Universe Validity**: Apply point-in-time survivorship-bias-free universe (or clearly mark as synthetic proxy backtest).
6. **Signal Separation**: Separate 1x signal assets from 3x execution assets.

## Phase B: Module Ablation (M0 to M4)
Test the incremental value of each rule independently using TWR:
- **M0**: 90-day Top 2, monthly rotation.
- **M1**: M0 + 90-day return > 0.
- **M2**: M1 + Price > SMA200.
- **M3**: M2 + SMA200 Slope(20) > 0.
- **M4**: M3 + Positive Z-score trim.

*Goal: Prove that each layer provides a statistically significant improvement in $\Delta$CAGR, $\Delta$MaxDD, or $\Delta$Sharpe.*

## Phase C: Parameter Plateau Search
Perform grid search on the surviving modules across a neighborhood of parameters to confirm a stable "plateau" rather than an overfitted peak.
- Momentum windows: [63, 90, 126]
- SMA windows: [150, 200, 250]
- Top N count: [1, 2, 3]
- Z-score trim thresholds: [0.75, 1.0, 1.25, 1.5]

## Phase D: Nested Walk-Forward & Perturbation
Validate the parameter plateaus across out-of-sample forward slices.
- **Folds**: 2018-2019, 2020-2021, 2022-2023, 2024-2026.
- **Perturbations**: 
  - Execution day offsets (1st, 2nd, 3rd, 5th trading day of the month).
  - Trading costs (5, 10, 20, 50 bps).
  - Execution lag (T+1, T+2).

## Phase E: Benchmark Comparison
Compare the final candidate against fixed risk equivalents:
- 90% BIL + 10% TQQQ (Buy & Hold).
- 90% BIL + 10% Equal-weight 3x ETFs.

## Phase F: Forward Validation Freeze
Freeze all rules, data sources, and parameters starting from **August 3, 2026**. Run live out-of-sample forward tracking without retroactive modifications.
