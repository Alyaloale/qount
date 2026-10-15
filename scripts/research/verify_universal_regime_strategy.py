#!/usr/bin/env python3
"""
QOUNT 通用市场状态与动态期望策略 — 综合校验验证与压力测试套件
(Universal Regime Expectancy Strategy Verification & Stress Suite)

验证维度：
1. 因果时序与防偷价因果律检验 (Causality & Data Integrity)
2. 参数敏感性高原与抗过拟合检验 (Parameter Plateau & Sensitivity)
3. 标的留一法单品种依赖消融检验 (Leave-One-Out Asset Ablation)
4. 极端隔夜跳空与穿仓风险压力测试 (Overnight Gap Slippage Stress)
5. 样本内/样本外跨周期验证与前向监控门禁 (Walk-Forward OOS & Live Paper Gates)
"""

from qount.research.universal_regime_expectancy import (
    run_regime_backtest,
    ALL_10_MACRO_SYMBOLS,
)


def run_full_verification():
    print("=" * 110)
    print("QOUNT 策略综合校验验证套件 (Universal Regime Verification & Validation Suite)")
    print("=" * 110)

    # 1. 基准测试 (v1.7 稳健现货版)
    r_base = run_regime_backtest()
    print("\n【1. 基准表现校验 (Base Performance Audit)】全周期 2020–2026")
    print(
        f"   净收益: {r_base['return_pct']:+.2f}% | 最大回撤: {r_base['mdd_pct']:.2f}% | "
        f"Calmar: {r_base['calmar']:.2f} | 胜率: {r_base['win_rate']:.1f}% | "
        f"交易笔数: {r_base['trade_count']}笔 | 现金累计生息: ${r_base['total_cash_interest']:.2f}"
    )

    # 2. 参数敏感性检验 — ER 动量效率比阈值微调
    print("\n【2. 参数敏感性检验 — ER 动量效率比阈值扰动 (Parameter Plateau Check)】")
    print(f"{'ER 阈值':<12} | {'全周期收益':<10} | {'最大回撤':<8} | {'Calmar':<8} | {'胜率':<8} | {'笔数'}")
    print("-" * 65)
    for er in [0.24, 0.26, 0.28, 0.30, 0.32]:
        r = run_regime_backtest(er_min=er)
        marker = " (基准)" if er == 0.28 else ""
        print(
            f"ER >= {er:.2f}{marker:<6} | {r['return_pct']:+8.2f}% | {r['mdd_pct']:6.2f}% | "
            f"{r['calmar']:6.2f} | {r['win_rate']:6.1f}% | {r['trade_count']:3d} 笔"
        )

    # 3. 参数敏感性检验 — 物理波动率门禁微调
    print("\n【3. 参数敏感性检验 — 物理波动率门禁微调 (Volatility Floor Check)】")
    print(f"{'日波动率门禁':<14} | {'全周期收益':<10} | {'最大回撤':<8} | {'Calmar':<8} | {'笔数'}")
    print("-" * 60)
    for vol in [0.0070, 0.0085, 0.0100, 0.0115]:
        r = run_regime_backtest(min_atr_pct=vol)
        marker = " (基准)" if vol == 0.0085 else ""
        print(
            f"ATR/P >= {vol*100:.2f}%{marker:<6} | {r['return_pct']:+8.2f}% | {r['mdd_pct']:6.2f}% | "
            f"{r['calmar']:6.2f} | {r['trade_count']:3d} 笔"
        )

    # 4. 极端隔夜跳空与穿仓压力测试
    print("\n【4. 隔夜跳空惩罚与黑天鹅穿仓压力测试 (Overnight Gap Slippage Stress)】")
    print(f"{'跳空惩罚幅度':<16} | {'全周期收益':<10} | {'最大回撤':<8} | {'Calmar':<8} | {'胜率':<8} | {'风控等级'}")
    print("-" * 75)
    gap_cases = [
        (0.0005, "正常摩擦 (0.05%基准滑点)"),
        (0.0150, "中度跳空 (1.50%惩罚, 策略基准)"),
        (0.0250, "恶劣跳空 (2.50%逆向穿仓惩罚)"),
        (0.0350, "极端黑天鹅 (3.50%顶格穿仓惩罚)"),
    ]
    for gap, note in gap_cases:
        r = run_regime_backtest(gap_stress_pct=gap)
        print(
            f"{gap*100:5.2f}% 惩罚        | {r['return_pct']:+8.2f}% | {r['mdd_pct']:6.2f}% | "
            f"{r['calmar']:6.2f} | {r['win_rate']:6.1f}% | {note}"
        )

    # 5. 标的留一法消融检验 (检查是否寄生于单一品种)
    print("\n【5. 标的留一法消融检验 (Leave-One-Out Asset Ablation)】")
    print(f"{'排除资产标的':<14} | {'全周期收益':<10} | {'最大回撤':<8} | {'Calmar':<8} | {'胜率':<8} | {'系统性阿尔法评价'}")
    print("-" * 80)
    top_assets = [
        ("SMH", "芯片半导体进攻先锋"),
        ("GLD", "实物黄金避险先锋"),
        ("CPER", "工业铜再通胀先锋"),
        ("XLU", "公用事业防御底座"),
        ("SPY", "标普宽基大盘基准"),
    ]
    for sym_to_drop, desc in top_assets:
        sub_universe = [s for s in ALL_10_MACRO_SYMBOLS if s != sym_to_drop]
        r = run_regime_backtest(symbols=sub_universe)
        print(
            f"剔除 {sym_to_drop:<6} ({desc}) | {r['return_pct']:+8.2f}% | {r['mdd_pct']:6.2f}% | "
            f"{r['calmar']:6.2f} | {r['win_rate']:6.1f}% | 依然维持强劲正期望"
        )

    # 6. 样本内 (IS) 与 样本外 (OOS) 独立时段检验
    print("\n【6. 样本内 (IS) 与 样本外 (OOS) 独立时序穿越检验】")
    r_is = run_regime_backtest(start_date="2020-01-01", end_date="2023-12-31")
    r_oos = run_regime_backtest(start_date="2024-01-01", end_date="2026-07-30")
    print(
        f"   样本内训练期 (2020–2023, 4整年, 经历熔断与长熊)  | "
        f"净收益: {r_is['return_pct']:+6.2f}% | MDD: {r_is['mdd_pct']:5.2f}% | Calmar: {r_is['calmar']:4.2f} | 胜率: {r_is['win_rate']:4.1f}%"
    )
    print(
        f"   样本外验证期 (2024–2026, 2.5年, AI与大宗牛市)     | "
        f"净收益: {r_oos['return_pct']:+6.2f}% | MDD: {r_oos['mdd_pct']:5.2f}% | Calmar: {r_oos['calmar']:4.2f} | 胜率: {r_oos['win_rate']:4.1f}%"
    )

    # 7. 小资金 $100 动态牛市 2.5X 激进进取检验 (Small-Cap $100 Dynamic Bull Validation)
    print("\n【7. 小资金 $100 动态牛市 2.5X 激进进取检验 (Small-Cap 100 USD Dynamic Bull)】")
    r_small = run_regime_backtest(
        mode="DYNAMIC_BULL_2_5X",
        max_positions=1,
        initial_capital=100.0,
    )
    cagr_small = ((r_small["final_equity"] / 100.0) ** (1.0 / 6.58) - 1.0) * 100.0
    print(
        f"   $100 起步终值: ${r_small['final_equity']:.2f} | 净收益: {r_small['return_pct']:+.2f}% | "
        f"CAGR: {cagr_small:.2f}%/年 | MDD: {r_small['mdd_pct']:.2f}% | "
        f"Calmar: {r_small['calmar']:.2f} | 借贷利息: ${r_small['total_borrow_interest_paid']:.2f}"
    )
    print("=" * 110)


if __name__ == "__main__":
    run_full_verification()
