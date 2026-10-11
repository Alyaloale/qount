# 文档入口

> **状态**：active｜**权威**：L2 documentation navigation｜**最后更新**：2026-10-11
> **适用范围**：当前事实、规则、运行手册、参考资料、活跃研究和历史归档的稳定入口。
> **TL;DR**：当前事实只在 [current.md](current.md)。本页组织导航，不复制生产状态或研究结论。

## First read

- [当前事实](current.md) — 运行状态、owner 决策与硬边界（唯一当前事实源）。
- [个人交易助手指南](personal-trading-assistant-guide.md) — 个人实战策略体系与开发指引（Vibe Coding 必读）。
- [项目规则](project-rules.md) — 代码、研究、文档和清理规则。
- [接手与运维](quick-handoff.md) — 现有运维入口和已知边界。
- [本地开发](operations/local-development.md) — Mac 环境与验证。
- [主机运行手册](operations/host-runbooks.md) — Mac、外置盘、WSL、VPS 的职责。
- [配置参考](reference/configuration.md) — 环境合同、密钥原则和只读预检。
- [CLI 与脚本](reference/cli-and-scripts.md) — 公共入口和脚本域。
- [代码组织](reference/code-organization.md) — 包边界、兼容层和可读性重构规则。
- [仓库地图](reference/repository-map.md) — 目录职责、研究模块与生成清单快照。
- [研究线总览](research-lines.md) — 当前研究线状态、代码入口和权限边界。

## Architecture, research and records

- [架构主设计](system-architecture-design.md)
- [系统环境与研究全景手册](system-environment-and-research-landscape.md) — 四大主机分工、配置规范、四大研究线与五大排障手册。
- [存储与计算拓扑](storage-topology.md)
- [验证边界](holdout.md)
- [研究路线](research-advancement-roadmap.md)
- [跨研究线修复：Q-DIV 数据会计与 C60 梯度实验](research-remediation-plan-2026-10.md) — owner 指定计划的执行口径、数据门、独立合同与验证记录。
- [近期记录](update-log.md)
- [美股与A股个股选择](equity-selection-study-2026-10.md) — 用户股票档案接入、复权/PIT资格与横截面信息研究；频率不设硬上限。
- [A股Q-DIV-IVOL研究](ashare-q-div-ivol-study-2026-10.md) — 实际财报/分红、低特质波动与缩量条件的截止日筛选；历史回测未运行。
- [短周期机会筛选：Binance 与 A 股](short-horizon-opportunity-study-2026-10.md) — 单一主动流假说、低频与净期望门、杠杆压力和公告/PIT来源资格。
- [G20/C60 十七轮结果与现金流可行性](dual-engine-optimization-2026-10.md#研究总览与阅读路径) — 运行前协议、全部正负结果、归因、信息源与确认限制；[机器登记](../config/dual-engine-research-registry.json)绑定原结果，既有paper口径见[策略总集](qount_strategy_master_index.md)。
- [ETF P2 / P3 文档入口](README-P2.md) — P2 架构与证据、原验收协议、P3 分层重构及实施计划。
- [ETF P3 残差 pilot 结果与核验](etf-p3-research-plan-2026-10.md#24-r3残差pilot执行与结果2026-10-04) — 验证口径、增量门、对照与解释边界。
- 事件线：`personal-200u-event-strategy.md`、`pre-event-range-strategy.md`、`fomc-trigger-study-and-v03-extension.md`
- 主动研究：`alpha-agent-plan.md`、`l1-passive-allocation-preregistration.md`、`carry-active-basis-hypothesis.md`
- 组合与演进：`long-run-personal-strategy-design.md`、`personal-strategy-research-directions.md`、`trading-system-evolution-plan.md`

## Historical material

[历史归档索引](archive/README.md) 是唯一的旧正文入口。归档材料是不可恢复的历史证据；不得从根目录或归档脚本重新启用历史线路。候选移动与未追踪资产的保留记录见 [archive manifest](archive/manifest.md)。
