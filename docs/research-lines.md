# 研究线总览

> 状态：active navigation｜权威：`docs/current.md`、`docs/project-rules.md` 与各线路合同｜最后更新：2026-10-04
> TL;DR：当前只推进有明确合同的 research-only 线路；Dual-Engine 是已部署的无订单模拟盘，CTA-R 只保留独立数据侧车，旧线路全部冻结。

## 状态分类

| 线路 | 当前状态 | 代码/脚本 | 结论边界 |
| --- | --- | --- | --- |
| Dual-Engine G20/C60/GC5/D15 | deployed paper / research-only | `src/qount/dual_engine/`、`scripts/operations/` | 公共行情无订单模拟；不产生订单或账户授权 |
| C60 v2 月度候选 | research-paper sidecar；前瞻自 2026-09-30 | `src/qount/research/c60_*`、`scripts/research/c60_*` | Trial 150 规则与冻结 v1 并行比较；换手归因：闸门进出占 82%（见 `c60-turnover-attribution-diagnostic-2026-09.md`）；时点宇宙下选币优势不成立（剔除 2021 年 Sharpe 0.47，低于仅 BTC 闸门的 0.69），视为 BTC beta（见 `c60-pit-universe-survivorship-2026-09.md`）；不替代 v1，无订单权限 |
| CTA-R ETF | data sidecar valid；规则冻结；前瞻账本自 2026-09-30 起（`cta-r-forward-ledger-2026-09.md`）；Trial 151 美股复现 `replicated`（Sharpe 0.75，未超 60/40） | `src/qount/research/cta_r_*`、`scripts/research/cta_r_*` | 只提供独立研究输入和历史侧车；不写 Dual-Engine 账本，不生成 StrategyIntent |
| ETF Trader P2 / P3 Alpha | research-only；[证据与设计入口](README-P2.md)，[R3残差pilot结果](etf-p3-research-plan-2026-10.md#24-r3残差pilot执行与结果2026-10-04)、[v2完整结果](etf-p3-research-plan-2026-10.md#195-完整结果与回读核验2026-10-03)、[开训前复审](etf-p3-research-plan-2026-10.md#23-r3开训前复审修正与创新取舍2026-10-03)、[准备/启动方法](../deploy/wsl/alpha-residual/README.md)；运行事实仅看 current | P2：`src/qount/research/etf_trader/`、`scripts/research/etf_trader_*.py`；P3：`src/qount/research/etf_alpha/`、`scripts/research/etf_alpha_*.py` | P2 历史验收与 P3 Alpha 架构分开；工程ready不等于训练授权，历史结果不产生 paper 或订单资格 |
| Alpha Agents | active research-only | `src/qount/alpha_agents/`、`scripts/research/alpha_agents/` | 采集、特征和角色实验；不写订单、目标权重或 live 配置 |
| MiniTrend / liquidation cascade | public-data forward research | `src/qount/mini_trend/`、`scripts/research/mini_trend/` | 只读公开数据和健康证据；不恢复 live、arm、timer 或 cron |
| FOMC / PreEvent / sleeves | preregistered or research-only | `src/qount/small_account/`、`src/qount/research/sleeves/` | 只做证据和模拟，必须遵守各自停止条件 |
| GRID / RV-C / X4 / L1/L3/L4/L6 / legacy A-share | archived / frozen | `src/qount/legacy/`、`scripts/archive/research-legacy/`、`docs/archive/legacy/` | 历史证据，不恢复、不新增实验、不继承 promotion 资格 |

## 研究记录规则

1. 当前事实只写入 `docs/current.md`；研究结果写入对应 active 文档或 artifact 说明。
2. 每条 active 线路必须写明 `research_only=true`、`orders_authorized=false`、数据来源、截止日期和停止条件。
3. 历史报告放在 `docs/archive/research-reports/`，旧线路正文放在 `docs/archive/legacy/`；归档内容不可成为运行指令。
4. 研究结论不会自动升级为 paper、promotion 或 live 资格；需要单独的 owner 决策和当前版本证据。

## 当前导航

- 运行状态与数据新鲜度：[current.md](current.md)
- 目录和线路规则：[project-rules.md](project-rules.md)
- Dual-Engine 口径：[qount_strategy_master_index.md](qount_strategy_master_index.md)
- CTA-R 与优化待办：[strategy-optimization-plan-2026-09.md](strategy-optimization-plan-2026-09.md)
- 跨线综合判断与方向设计（2026-09-29，待 owner 决策）：[research-direction-review-2026-09.md](research-direction-review-2026-09.md)
- Alpha Agents 路线：[alpha-agent-plan.md](alpha-agent-plan.md)
- 历史索引：[archive/README.md](archive/README.md)
