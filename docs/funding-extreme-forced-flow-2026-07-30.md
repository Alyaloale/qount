# Funding Extreme Forced-Flow Diagnostic

> **状态**：`reject_forced_flow_historical_diagnostic` | **范围**：historical research-only | **日期**：2026-07-30

Funding-extreme independence G0 已通过后，按新的结果前合同运行一次固定的
历史事件诊断。该结果不授予 paper/live/order 权限，也不代表真实清算流机制已验证：
历史部分没有 OI 或 liquidation archive，只使用 funding 与 UM 日线。

## Frozen Result Contract

- 事件：G0 的 24 小时 funding cluster；正 funding 后做多，负 funding 后做空。
- 混合符号 cluster 排除；每个 cluster 最多一个事件。
- 若持有期重叠，保留时间最早的事件，排除后续 `entry_date <= prior outcome_date` 的事件。
- 下一根完成日线开盘入场，持有 3 根完成日线，第三根收盘退出；不设额外止损。
- 单边手续费 `10bps`、滑点 `2bps`；持仓期间实际 funding 计入。
- 主结果门：独立事件数 `>=12`、正事件率 `>=55%`、中位净事件收益 `>0`、复合净收益 `>0`、至少两个正分段、BTC beta residual 中位数 `>0`。
- 禁止调阈值、调持有期、调权重、补 OI、订单、paper 或 live。

预登记合同 hash：`462287cab439dc1690fbe7b0c61a5a3c52fa93b12dabafdf3ca3b34408acdd9e`。

## Result

- 事件：`49` 个非重叠事件；18 个 cluster 因缺少完整持有窗口、7 个因持仓期重叠排除。
- 正事件率：`48.98%`，未过 `55%`。
- 中位净事件收益：`-0.3715%`，未过 `>0`。
- 复合净事件收益：`+33.66%`，但不足以覆盖中位收益和稳定性门。
- 最大事件净值回撤：`-18.16%`。
- BTC beta residual 中位数：`+0.3000%`，单独通过但不能挽救其它失败门。
- 分段复合净收益：2021-22 `+34.53%`、2023-24 `-0.64%`、2025-26 无完整事件。

最终结论：否决该 funding-only historical forced-flow 诊断。不得通过改成单币权重、
改变方向、延长持有期或补充筛选条件救援。若未来继续，只能等待独立的
public-only liquidation/OI forward 窗口，并重新建立不同信息集的结果前合同。

机器工件：

- `state/research_governance/funding_extreme_forced_flow/preregistration.json`
- `state/research_governance/funding_extreme_forced_flow/result.json`
