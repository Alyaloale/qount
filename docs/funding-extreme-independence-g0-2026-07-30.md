# Funding Extreme Independence G0

> **状态**：`retain_for_new_forced_flow_preregistration` | **范围**：no-PnL research-only G0 | **日期**：2026-07-30

本轮只检验 `funding_extreme_forced_flow_v1` 是否与已拒绝的 Trial 144
`cross_market_capitulation_rebound` 重复，不评估收益，不产生订单，也不改变
paper/live 权限。

## Frozen Contract

- 数据：现有 Binance UM `fundingRate` archive，缓存目录 `state/r0_runtime/funding`；不联网、不扩充标的。
- 标的：`BTCUSDT`、`ETHUSDT`、`BNBUSDT`，即当前 TOP3 边界。
- 极值：`abs(8h funding rate) * 3 * 365 >= 50%`。
- 持续：至少连续 2 次结算，连续结算间隔不得超过 12 小时。
- 独立性聚类：不同标的事件在 24 小时内合并为一个 funding event cluster。
- 重叠窗口：funding cluster 的结束日落在 Trial 144 `signal_date` 前 1 个 UTC 日至当天。
- 关闭门：Trial 144 重叠率 `>=60%`；样本门：至少 30 个独立 funding clusters。

预登记合同 hash：`9fd924777b5d8067e463c6fa88c62cd7b514de667c2369a7f017e4c655ad73b8`。

## Result

- funding rows：BTC `7119`、ETH `7119`、BNB `6998`；可用日期至 `2026-06-30`。
- 标的级极值 episode：BTC `57`、ETH `79`、BNB `152`。
- 24 小时聚类后的独立事件：`116`，通过 `>=30` 样本门。
- Trial 144 事件：`18/18` 有 funding 覆盖。
- 重叠事件：`1/18`，重叠率 `5.5556%`，低于 `60%`。
- 唯一重叠 signal date：`2022-01-21`，仅 BNB funding cluster 命中。

结论：D2 通过“不是 Trial 144 换名”的独立性门，允许进入新的 forced-flow
结果前预登记。下一阶段必须另行冻结方向、持有期、成本、BTC beta residual
和 kill gates；本 G0 结果本身不是 alpha 或策略收益证据。

机器工件：

- `state/research_governance/funding_extreme_independence_g0/preregistration.json`
- `state/research_governance/funding_extreme_independence_g0/result.json`
- runner：`scripts/research/mini_trend/run_funding_extreme_independence_g0.py`
