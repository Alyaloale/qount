# 研究线总览

> 状态：active navigation｜权威：`docs/current.md`、[docs/personal-trading-assistant-guide.md](personal-trading-assistant-guide.md) 与各线路合同｜最后更新：2026-10-11
> TL;DR：当前主航道全面聚焦【个人量化交易助手与个人实战盈利】（ETF大趋势择时、极简核心资产、加密小账户）；公募基金式20仓全市场选股(Q-DIV-Core)、C60梯度等历史实验均已完成并保留失败证据归档参考，旧高频/微观套利线路永久冻结。

## 状态分类

| 线路 | 当前状态 | 代码/脚本 | 结论边界 |
| --- | --- | --- | --- |
| 个人量化交易助手 (主航道) | active 主航道 / 个人实战盈利 | `src/qount/`；`scripts/` | 见 [个人交易助手指南](personal-trading-assistant-guide.md)；聚焦 ETF 大趋势择时、加密小账户、极简高息，低频大周期，追求绝对收益与复利 |
| A股 Q-DIV-Core 20仓全市场选股 | completed / 门槛失败归档保留 | `src/qount/research/q_div_core.py`；`scripts/research/q_div_core_runner.py` | 2014-2026全历史四曲线回测完成；熊市抗跌但年化换手217%超标、牛市跑输Beta，门槛失败保留，不进行调参救援，正式归档 |
| 美股 / A股个股选择 | [新方向与数据证据](equity-selection-study-2026-10.md)；当前事实只看 current | `research_data/equity_archive.py`；`scripts/research/equity_archive_audit.py` | 用户档案资格与横截面研究；不强制低频，市场/收益证据分别验证 |
| 短周期机会：Binance / A 股 | [独立新信息协议与证据](short-horizon-opportunity-study-2026-10.md)；运行事实只看 current | `src/qount/research/opportunity_*`、`research_data/event_stats.py`；`scripts/research/opportunity_screen.py` | 固定小时标签、假设杠杆压力；A股来源门未通过不得运行收益，不继承 legacy 或其他线资格 |
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

## A股独立选股与持仓研究

owner指定A股为独立研究线，进取取向，以选股和持有规则检验盈利；[主协议](ashare-strategy-study-2026-10.md)、[研究索引](../config/ashare-research-registry.json)。行业/价格策略与企业/政策证据分层，逐项冻结候选后做成本/延迟代理回测，持仓/受阻/缺价、集中度及组合冷却单独管理。最新运行事实只看[current](current.md)；research_only=true/orders_authorized=false/promotion_evidence=false，不产生生产交易权限。

新增[Q-DIV-IVOL独立协议](ashare-q-div-ivol-study-2026-10.md)，以工业企业实际财报/分红、真实换手与市场残差波动做截止日筛选；历史版本/风险事件及组合执行引擎未完成前不产生历史收益。原低波候选与已失败价格实验保留。
