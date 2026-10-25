# 文档入口

> **状态**：active｜**权威**：文档导航；遵循 [AGENTS.md](../AGENTS.md)｜**最后更新**：2026-10-25
> **适用范围**：当前事实、规则、运行手册、参考资料、活跃研究和历史归档的稳定入口。
> **TL;DR**：当前事实只在 [current.md](current.md)。本页组织导航，不复制生产状态或研究结论。

## First read

先遵循 [AGENTS.md](../AGENTS.md)，再按任务读取下列资料；小改动不要求通读全部文档。项目事实与规则冲突按 `current → project-rules → runbooks/reference → 活动策略文档` 核对，历史合同只约束原实验。

- [当前事实](current.md) — 运行状态、owner 决策与硬边界（唯一当前事实源）。
- [个人资产管理交易系统研究指南](personal-trading-assistant-guide.md) — 盈利目标、开放策略研究、最小实验与证据方法。
- [项目规则](project-rules.md) — 代码、研究、文档和清理规则。
- [接手与运维](quick-handoff.md) — 现有运维入口和已知边界。
- [本地开发](operations/local-development.md) — Mac 环境与验证。
- [主机运行手册](operations/host-runbooks.md) — Mac、外置盘、WSL、VPS 的职责。
- [配置参考](reference/configuration.md) — 环境合同、密钥原则和只读预检。
- [CLI 与脚本](reference/cli-and-scripts.md) — 公共入口和脚本域。
- [代码组织](reference/code-organization.md) — 包边界、兼容层和可读性重构规则。
- [仓库地图](reference/repository-map.md) — 目录职责、研究模块与生成清单快照。
- [研究线总览](research-lines.md) — 当前研究线状态、代码入口和权限边界。
- [各研究线修补与整理计划](research-repair-and-consolidation-plan-2026-10.md) — 口径统一、逐线问题、依赖顺序与最小验收。

## Architecture, research and records

- [个人交易系统收敛方案](personal-system-consolidation-plan.md) — 个人项目的最小结构、数据复用、研究线分类和前后端职责。
- [资产管理策略选择与设计依据](asset-management-strategy-review-2026-10.md) — 纳指风险预算、G20、CTA-R等候选的证据、适用角色、资金规模与组合设计限制。
- [系统改进设计与实施计划](system-improvement-design-plan-2026-10.md) — 项目检查后的执行退出、通知、运行状态、策略绩效与连续运行改进设计；实施与生产授权分开。
- [架构主设计](system-architecture-design.md) — 当前研究、只读助手与生产执行边界；[旧架构与迁移记录](archive/system-architecture-design-pre-2026-10-12.md)保留历史细节。
- [系统环境与研究全景手册](system-environment-and-research-landscape.md) — 主机分工、配置规范、研究导航与排障。
- [存储与计算拓扑](storage-topology.md)
- [验证边界](holdout.md) — 通用样本使用原则及旧 ETH-only 冻结合同的适用范围。
- [历史研究路线](research-advancement-roadmap.md) — 原 family、试验预算与阶段记录，不作为所有新研究的统一门槛。
- [跨研究线修复：Q-DIV 数据会计与 C60 梯度实验](research-remediation-plan-2026-10.md) — 已执行批次及阶段限制；后续工作顺序见修补整理计划。
- [近期记录](update-log.md)
- [美股与A股个股选择](equity-selection-study-2026-10.md) — 用户股票档案接入、复权/PIT资格与横截面信息研究；频率不设硬上限。
- [A股Q-DIV-IVOL／Core研究](ashare-q-div-ivol-study-2026-10.md) — IVOL 截止日筛选与 Core 四曲线结果分开；Core 已完成并失败保留，原 20 仓不调参救援。
- [短周期机会筛选：Binance 与 A 股](short-horizon-opportunity-study-2026-10.md) — 单一主动流假说、低频与净期望门、杠杆压力和公告/PIT来源资格。
- [G20/C60 十七轮结果与现金流可行性](dual-engine-optimization-2026-10.md#研究总览与阅读路径) — 运行前协议、全部正负结果、归因、信息源与确认限制；[机器登记](../config/dual-engine-research-registry.json)绑定原结果，既有paper口径见[策略总集](qount_strategy_master_index.md)。
- [ETF P2 / P3 文档入口](README-P2.md) — P2 架构与证据、原验收协议、P3 分层重构及实施计划。
- [ETF P3 残差 pilot 结果与核验](etf-p3-research-plan-2026-10.md#24-r3残差pilot执行与结果2026-10-04) — 验证口径、增量门、对照与解释边界。
- 事件线：`personal-200u-event-strategy.md`、`pre-event-range-strategy.md`、`fomc-trigger-study-and-v03-extension.md`
- 主动研究：`alpha-agent-plan.md`、`l1-passive-allocation-preregistration.md`、`carry-active-basis-hypothesis.md`
- 历史方向提案：[长期个人组合](long-run-personal-strategy-design.md)、[个人研究方向](personal-strategy-research-directions.md)；旧优先级不覆盖当前修补计划。控制面设计另见 [系统演进](trading-system-evolution-plan.md)。

## Historical material

[历史归档索引](archive/README.md) 是旧正文入口。归档材料用于追溯，不能覆盖当前事实或授权恢复冻结线路。候选移动与未追踪资产的保留记录见 [archive manifest](archive/manifest.md)。
