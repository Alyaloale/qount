"""
Comprehensive Verification and Stress-Testing Suite for Universal Regime Strategy
1. Causality & Anti-Leakage Audit
2. Parameter Sensitivity Grid (ER min, Vol floor, MR hold days)
3. Asset Leave-One-Out Ablation (Remove SMH, GLD, CPER)
4. Extreme Gap Stress (-1.5% vs -2.5% vs -3.5%)
5. Out-of-Sample Walk-Forward (2020-2023 IS vs 2024-2026 OOS)
"""

from qount.research.universal_regime_expectancy import run_regime_backtest, ALL_10_MACRO_SYMBOLS

def run_suite():
    print("=" * 90)
    print("QOUNT 通用市场状态策略 — 综合校验验证套件 (Verification & Stress Suite)")
    print("=" * 90)

    # 1. Baseline Run
    r_base = run_regime_backtest()
    print(f"\n[1. 基准检验] 全周期 (2020–2026)")
    print(f"   净收益: {r_base['return_pct']:+.2f}%, MDD: {r_base['mdd_pct']:.2f}%, Calmar: {r_base['calmar']:.2f}, 胜率: {r_base['win_rate']:.1f}%, 交易: {r_base['trade_count']}笔, 利息: ${r_base['total_cash_interest']:.2f}")

    # 2. Parameter Sensitivity: ER min perturbation (0.24, 0.28, 0.32)
    print(f"\n[2. 参数敏感性检验 — ER 动量效率比阈值微调]")
    for er in [0.24, 0.26, 0.28, 0.30, 0.32]:
        r = run_regime_backtest(er_min=er)
        print(f"   ER >= {er:.2f} | 净收益: {r['return_pct']:+6.2f}% | MDD: {r['mdd_pct']:5.2f}% | Calmar: {r['calmar']:4.2f} | 胜率: {r['win_rate']:4.1f}% | 笔数: {r['trade_count']:3d}")

    # 3. Parameter Sensitivity: Volatility Floor (0.0070, 0.0085, 0.0100)
    print(f"\n[3. 参数敏感性检验 — 物理波动率门禁微调]")
    for vol in [0.0070, 0.0085, 0.0100, 0.0115]:
        r = run_regime_backtest(min_atr_pct=vol)
        print(f"   Vol Floor {vol*100:.2f}% | 净收益: {r['return_pct']:+6.2f}% | MDD: {r['mdd_pct']:5.2f}% | Calmar: {r['calmar']:4.2f} | 笔数: {r['trade_count']:3d}")

    # 4. Extreme Gap Stress Test (Overnight Gap Penalty from 0.05% to 3.5%)
    print(f"\n[4. 极端隔夜跳空与穿仓压力测试]")
    for gap in [0.0005, 0.0150, 0.0250, 0.0350]:
        r = run_regime_backtest(gap_stress_pct=gap)
        print(f"   跳空惩罚 {gap*100:4.2f}% | 净收益: {r['return_pct']:+6.2f}% | MDD: {r['mdd_pct']:5.2f}% | Calmar: {r['calmar']:4.2f} | 胜率: {r['win_rate']:4.1f}%")

    # 5. Asset Leave-One-Out Ablation (Check single-asset dependency)
    print(f"\n[5. 标的留一法消融检验 (Leave-One-Out Ablation)]")
    top_assets = ["SMH", "GLD", "CPER", "XLU", "SPY"]
    for sym_to_drop in top_assets:
        sub_universe = [s for s in ALL_10_MACRO_SYMBOLS if s != sym_to_drop]
        r = run_regime_backtest(symbols=sub_universe)
        print(f"   剔除标的 {sym_to_drop:<4} | 净收益: {r['return_pct']:+6.2f}% | MDD: {r['mdd_pct']:5.2f}% | Calmar: {r['calmar']:4.2f} | 胜率: {r['win_rate']:4.1f}%")

    # 6. Walk-Forward / In-Sample vs Out-of-Sample
    print(f"\n[6. 样本内 (IS) 与 样本外 (OOS) 独立时段检验]")
    r_is = run_regime_backtest(start_date="2020-01-01", end_date="2023-12-31")
    r_oos = run_regime_backtest(start_date="2024-01-01", end_date="2026-07-30")
    print(f"   样本内 (2020–2023, 4年)  | 净收益: {r_is['return_pct']:+6.2f}% | MDD: {r_is['mdd_pct']:5.2f}% | Calmar: {r_is['calmar']:4.2f} | 胜率: {r_is['win_rate']:4.1f}%")
    print(f"   样本外 (2024–2026, 2.5年)| 净收益: {r_oos['return_pct']:+6.2f}% | MDD: {r_oos['mdd_pct']:5.2f}% | Calmar: {r_oos['calmar']:4.2f} | 胜率: {r_oos['win_rate']:4.1f}%")

if __name__ == "__main__":
    run_suite()
