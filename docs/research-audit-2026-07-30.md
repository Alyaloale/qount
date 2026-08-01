# 2026-07-30 Research Revalidation Audit

本次复盘只覆盖四条组合影响最大的线：MiniTrend Base/Funding Veto、L1、CTA-R、FOMC。所有状态使用以下四值：

- `valid`: 该层面的证据满足当前合同，结论可保留。
- `insufficient`: 证据未完成，不能继续外推。
- `flawed`: 原方法或数据边界会系统性误导结论，旧结论不能沿用。
- `rejected`: 已触发预先定义的否决条件，当前假设不保留。

每条线分别报告：机制结论、数据结论、策略收益结论。`valid` 的机制不等于 `valid` 的收益。

## 统计修复

旧 directional 统计有三处问题：

1. purged CV 的 embargo 只是字段，没有限制 holding-period label 跨 fold；
2. overlap 默认使用 `all`，同一持有期内的重叠 bet 被当作独立观察；
3. time-series momentum 把同一时间的多标的 bet 当作 portfolio period，放大了样本量和 Sharpe 的确定性。

当前实现已改为：

- 默认 overlap=`stride`；需要重叠诊断的旧测试显式传 `overlap_mode="all"`；
- CV 评估区间为 `fold_start + embargo` 到 `fold_end - holding_horizon - embargo`，并记录 `label_end_must_be_before_utc`；
- 规则型策略明确标记为 `purged_label_fold_stability_no_training`，不再冒充训练型 CV；
- portfolio period 先按 timestamp 聚合，再按 Bartlett 加权自相关估算 `effective_period_count`；DSR、effective rank-IC t-stat 使用该数值；
- DSR 保留有效样本数的浮点值，不再把例如 1.9 截成 1。

因此，旧 directional CV、旧 overlap 独立样本数和旧 TS-Momentum 样本量结论均为 `flawed`，不能作为本次四条线的收益证据。修复后的统计实现为 `valid`，但它只修复估计口径，不自动让任何策略收益变成通过。

## Vol Crisis 合同与 Synthetic Tests

本次固定的决策时点是：决策发生在 aligned bar `i` 收盘；目标权重从 bar `i` close 作用到 bar `i+1` close。决策 bar `i` 可见价格特征截至 `i` 的收盘；funding 特征只使用已经完成的区间。

Funding interval 明确定义为左开右闭：`(bar_open_i, bar_open_i+1]`。synthetic test 验证了：起点 timestamp 不计入、终点 timestamp 计入、区间外 timestamp 不计入；`[0.2, 0.6]` 的期望结果通过。决策特征 prefix test 也验证了决策 bar 的最后一根 feature 被纳入，下一根 feature 不会泄漏。

这使 Vol Crisis 的时点/区间机制结论为 `valid`。历史收益结论仍为 `insufficient`：旧 bundle 的 gates 为 5/6，tail residual improvement 未通过，且数据是 consumed discovery data、历史 exchange rules 未完成 PIT 认证、成本仍为估算值。不能用原有结果宣称风险乘数已证明有效。

## 修复后独立重跑

MiniTrend Base/Funding Veto 已修复为可分别指定 kline 与 funding cache，并用真实 `state/r0_runtime/klines`、`state/r0_runtime/funding` 独立重跑：三资产各 `2036` 根日线、各 `6021` 条 funding；Base 净收益 `70.2653467%`、最大回撤 `16.77264567%`；Funding Veto control 净收益 `70.2653467%`、candidate `86.06635439%`、17 个 veto、funding coverage `1.0`。这两项是 consumed-history diagnostic，机制/历史回放可标记 `valid`，当前 forward 与治理升级仍是 `insufficient`，不应写成“策略收益已通过”。

FOMC 已修复为纽约时间 `14:00` 日历，并在汇总中排除 D+3 不完整事件；修复后产物为 [FOMC repaired study](/Users/alyaloale/Code/qount/state/research_governance/macro_event_anchor_trigger/20260730_fomc_repaired/fomc_anchor_trigger_study.json)，统计为 `19/20` 完整、`10/19` anchor、`7/10` strong。该线的 1H discovery 机制为 `valid`，数据与策略收益仍为 `insufficient`。

## 四条重跑线

| 线 | 机制结论 | 数据结论 | 策略收益结论 | 本轮证据 |
| --- | --- | --- | --- | --- |
| MiniTrend Base | `valid`：no-carry、long-only、完成日收盘决策的风险管理基线 | `insufficient`：当前治理组合仍缺 exchange-rules、live-lessons、base preregistration 的完整绑定；缓存 admission 已通过 | `insufficient`：consumed-history replay 为 `valid`，当前 forward 仍不足以升级 | [独立重跑报告](research-independent-validation-2026-07-30.md)；[Base runner](../scripts/research/mini_trend/mini_trend_futures_base_forward.py) |
| Funding Veto | `valid`：funding 只作为 strong-bull boost 前的成本 veto；synthetic interval 与决策时点通过 | `insufficient`：治理组合仍缺 prior stop-latch immutable input；分离缓存 admission 已通过 | `insufficient`：consumed-history replay 为 `valid`，当前 forward/推广仍不足；旧 `+88.95%` 不引用 | [独立重跑报告](research-independent-validation-2026-07-30.md)；[Funding Veto runner](../scripts/research/mini_trend/mini_trend_futures_funding_veto.py) |
| L1 passive | `valid`：当前冻结的是 owner-directed `SPY 60% / TLT 40%` 被动配置，不是 alpha 选择器；L1-S2 trend carrier 已弃用 | `insufficient`：只有 preregistration，没有已授权的历史评价数据和成本/税务包装证据 | `insufficient`：本轮没有收益重跑；合同明确 `strategy_results_evaluated=false` | [l1 preregistration](/Users/alyaloale/Code/qount/state/research_runs/20260730T095844Z-l1-passive-allocation-preregistration/l1_passive_allocation_preregistration.json) |
| CTA-R | `valid`：固定 selection-free、long-only、unlevered、成本加倍压力测试的机制合同可执行 | `flawed`：数据角色仍是 consumed discovery pool；current ETF archive 不能证明历史 PIT membership，QDII premium/tracking error 未重建，成本未认证 | `insufficient`：正常成本 walk-forward Sharpe `0.7403`，双倍成本 `0.6984`，双倍成本 5 折中 4 折为正；但 `candidate_pnl_ready=false`、`promotion_evidence=false` | [CTA-R independent bundle](/Users/alyaloale/Code/qount/state/research_governance/cta_r_revalidation/20260730_independent/062c305617bb3cdebb41df788e79daccb2b7ea907a28f1f344b175cdb15dd011/results.json) |
| FOMC | `insufficient`：1h anchor discovery 不能代替 v0.2 的 15m confirmation、stop 和 force-exit 完整机制 | `insufficient`：本轮 entry-cutoff shadow 因 Binance restricted-location exchangeInfo 返回 451 而 HALTED；没有完整 15m outcome/scorecard | `insufficient`：无可认证成交 PnL；`orders_authorized=false`，不可从单次 canary 推出收益 | [FOMC shadow result](/Users/alyaloale/Code/qount/state/research_runs/20260730T_fomc_revalidation_state/events/72074a23e1054981e9a8344d18e9400f3eaf8463e2ba22d092c00ae62fb48af5/latest.json)；[discovery note](/Users/alyaloale/Code/qount/docs/fomc-trigger-study-and-v03-extension.md) |

### CTA-R 数值复核

本轮固定数据为 8 ETF、共同区间 `2014-01-15` 至 `2026-07-22`，共 3037 个共同日期；walk-forward evaluation 为 2025 日。结果：

- 冻结成本：annualized Sharpe `0.7403`，CAGR `7.698%`，最大回撤 `-8.693%`，5/5 fold 为正；
- 双倍成本：annualized Sharpe `0.6984`，CAGR `7.217%`，最大回撤 `-8.725%`，4/5 fold 为正，第三折为 `-0.0268`；
- independent NAV reconciliation 通过，差异 `1.78e-15`；但这只证明模拟账与独立 NAV 一致，不解决数据 PIT、可交易性或成本认证。

## 决策

本轮没有任何一条线获得 `strategy return = valid`。CTA-R 是唯一可以保留为 discovery revalidation candidate 的线，但不是 promotion candidate；MiniTrend Base/Funding Veto、L1、FOMC 均需要补齐明确缺失证据后再跑，旧收益数字不进入当前组合决策。

验证命令：

```text
.venv/bin/python -m unittest tests.test_strategy_optimization tests.test_vol_crisis_state tests.test_macro_event_trigger_study tests.test_small_account_fomc_scorecard tests.test_small_account_fomc_watcher tests.test_small_account_fomc_operations
```

结果：`296 tests`, `OK`。同时通过 `git diff --check` 和 `compileall`。
