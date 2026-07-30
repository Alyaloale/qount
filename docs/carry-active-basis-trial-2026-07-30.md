# Active Basis Trial 1

> **状态**：`reject_mechanism`｜**范围**：historical research-only｜**日期**：2026-07-30

本次试验检验 `carry_active_basis_v1` 的首个固定变体：BTCUSDT、日线、正 basis、现货多/永续空。所有结果均来自已消费的历史 discovery pool，不是 OOS、candidate、paper 或 live 证据。

## Frozen Contract

- 观察窗口：2020-01-01 至 2026-06-30；spot/perp 日线与 Binance UM funding archive。
- 决策：日线收盘，只使用当前收盘及此前 basis 历史；持仓收益从下一根日线开始。
- 入场：30 日 basis z-score `>=1.0`、basis 为正、7 日 funding 年化均值 `>=20%`，且最近每日均有至少 3 次 funding settlement。
- 退出：basis z-score `<=0.25`、funding 均值转负、basis z-score `>=2.5`，或持仓达到 10 天。
- 资本：现货腿与永续腿各承担 0.5 gross；现货/永续手续费、滑点和 legging cost 分别计入。
- 基线：同一窗口的 funding-only active capture 与 static positive carry。
- 成本模型状态：`incomplete`。已计入手续费、滑点和 legging 估计，但未计入 collateral opportunity cost、basis-tail insurance，也没有认证后的真实 fill/legging 样本。

合同 hash：`6d453400c077d9a618747172843c89f87f66d817e6671c7bee5310f5bd685fdf`。

## Result

数据闭合：`2,373` 个共同日线、`7,119` 条 funding settlement，funding coverage `1.0`。

| 版本 | 净收益 | 年化 Sharpe | 最大回撤 | 交易次数 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| Active positive basis | `+2.69%` | `0.759` | `-1.07%` | `33` | 失败 |
| Funding-only baseline | `+10.89%` | `2.020` | `-0.89%` | `38` | 胜出 |
| Static positive carry | `+37.21%` | `8.443` | `-1.15%` | `1` | 胜出 |

Active 版本的 funding PnL 为 `+10.69%`，market/basis PnL 为 `+1.23%`，执行成本为 `-9.24%`。因此它没有形成足够独立的 basis 增量，交易成本几乎消耗了全部优势。

分段结果为：2020-2022 `+3.01%`，2023-2024 `-0.32%`，2025-2026 无触发。未通过 `beats_funding_only_baseline`、`beats_static_positive_carry` 和 `at_least_two_positive_segments` 三道门。

此外，`complete_executable_cost_model` 明确为 `false`。本结果可以支持历史机制筛选，但不能作为 paper/live 执行依据。

结果 hash：`5c40d69c14d326a9a2b898e104f56984cebff20fcb0fedc479d1a66ca98f8950`。

## Decision

关闭“正 basis z-score + funding 7 日均值”的 Trial 1。不得在同一历史池上调整 z-score、funding 阈值、持有期或成本假设救援。

这不否定所有 carry/basis 研究，但下一次必须引入实质不同的信息集或执行合同，例如 dated-future curve、真实盘口/legging 样本或独立的前向数据；不能把旧静态 carry 改名后重新计算。

机器工件：

- `state/research_runs/20260730T151048Z-btcusdt-active-basis-trial-1/preregistration.json`
- `state/research_runs/20260730T151048Z-btcusdt-active-basis-trial-1/result.json`
