# 研究线总览

> **状态**：active navigation｜**权威**：导航；当前裁决与权限只在 [current.md](current.md)｜**最后更新**：2026-10-12
> **TL;DR**：以最终裁决导航，旧旗舰申报不再作为推荐。计划见 [修补整理计划](research-repair-and-consolidation-plan-2026-10.md)，本页不维护第二份绩效表或实时运行状态。

## 线路与证据入口

| 线路 | 主文档／证据入口 | 实现位置 | 阅读边界 |
| --- | --- | --- | --- |
| 个人量化交易助手 | [开发指南](personal-trading-assistant-guide.md)、[交付复查](research-s1-independent-review-2026-10.md#8-交付复查与验收范围修订2026-10-12-utc) | `research/personal_trading_assistant.py` | 原型待补验收；每日／回测规则一致性和数据资格未闭合 |
| A 股 ETF 趋势／红利盾牌 | [代理研究](ashare-etf-trend-shield-study-2026-10.md)、[修订计划R04](research-repair-and-consolidation-plan-2026-10.md) | `research/ashare_trend_etf.py`、`personal_trading_assistant.py` | 指数代理单列；实际ETF、份额拆分、成本／换手与现金路径待核 |
| A 股赛道轮动 A／综合 C | [历史申报与封存说明](ashare-sector-momentum-study-2026-10.md) | `research/ashare_sector_momentum.py` | 旧高收益结论撤销，不继续称实战旗舰 |
| A 股 EKF-MPC／麒麟 | [EKF-MPC 历史设计](ashare-ekf-mpc-study-2026-10.md)、[麒麟封存说明](ashare-master-strategy-design-2026-10.md) | `research/ashare_ekf_mpc.py`、`ashare_master_strategy.py` | 各变体不互相继承收益或复核资格 |
| A 股 Q-DIV-IVOL／Core | [筛选与设计协议](ashare-q-div-ivol-study-2026-10.md)、[Core 完成摘要](../state/research_runs/ashare_q_div_core_20261011/summary.json) | `research/q_div_*.py` | 截止日名单与已失败 Core 回测分开；不对原 20 仓调参救援 |
| A 股独立选股／经营研究 | [选股研究](ashare-strategy-study-2026-10.md)、[数据接入](equity-selection-study-2026-10.md)、[登记](../config/ashare-research-registry.json) | `research/ashare_*.py`、`research_data/equity_archive.py` | 低波候选待新鲜确认，其他失败实现保持；美股个股数据未取得 |
| 币安全球多资产合约 | [历史设计与封存说明](binance-global-macro-design-2026-10.md) | `research/binance_global_macro.py` | 旧高收益撤销，修复后的情景收据待统一 |
| Dual-Engine G20／C60／GC5／D15 | [paper 合同与有日期复盘](qount_strategy_master_index.md)、[离线研究](dual-engine-optimization-2026-10.md) | `dual_engine/`、`scripts/operations/` | 公共数据无订单模拟；离线排名不替换 paper |
| C60 v2／PIT／梯度 | [时点宇宙复核](c60-pit-universe-survivorship-2026-09.md)、[换手归因](c60-turnover-attribution-diagnostic-2026-09.md)、[梯度执行记录](research-remediation-plan-2026-10.md) | `research/c60_*.py` | 选币优势撤回，梯度失败；联合门归因不等于 BTC 单门可消除成本 |
| CTA-R 独立侧车 | [跨市场复现](cta-r-us-replication-and-c60-vol-matched-2026-09.md)、[前瞻合同](cta-r-forward-ledger-2026-09.md) | `research/cta_r_*.py` | 新 research 侧车与冻结 legacy CTA-R 分开；最低门通过不等于晋级 |
| ETF Trader P2／P3 Alpha | [统一入口](README-P2.md)、[P2 结果](p2-project-summary-20261002.md)、[P3 设计与结果](etf-p3-research-plan-2026-10.md) | `research/etf_trader/`、`research/etf_alpha/` | P2 停训、v2 完成、R3 无增量停止；旧 READY 不授予重启 |
| 短周期机会／业绩上修 | [独立研究](short-horizon-opportunity-study-2026-10.md) | `research/opportunity_*.py` | 严格小时候选停止；公告上修数据门待补，收益未运行 |
| 稳定币／Alpha Agents | [来源 G0 与研究角色](alpha-agent-plan.md) | `alpha_agents/`、`intelligence/` | 来源资格与预测收益分开；LLM 只输出资料、研究和审计 |
| 清算级联 | [采集合同](research-forward-collector.md)、[当前有效窗口](current.md) | `mini_trend/` | 有效窗口从 2026-08-18 起；最早评估日期以 current 为准 |
| FOMC／PreEvent／被动 Sleeve | [事件研究](personal-200u-event-strategy.md)、[PreEvent](pre-event-range-strategy.md)、[被动合同](l1-passive-allocation-preregistration.md) | `small_account/`、`research/sleeves/` | 独立 research 身份；不恢复取消的 FOMC live 或 L1-S2 |
| GRID／RV／X4／旧 MiniTrend 实盘／legacy | [历史索引](archive/README.md) | `legacy/`、`scripts/archive/` | 停止或冻结，不恢复、不新增实验 |

上表 `research/` 等实现路径相对 `src/qount/`；真实脚本入口查 [CLI 参考](reference/cli-and-scripts.md)。

## 研究记录规则

1. 当前裁决只写入 current；本页和主机全景只导航，绩效数字与窗口保留在本线证据中。
2. `research_only=true / orders_authorized=false`；来源、数据截止、代码／合同版本、样本身份和停止条件写清。
3. 旧结果不覆盖。错误修复不把旧历史变成独立 OOS；原 JSON 字段名不是最终裁决。
4. 交易次数、名义换手、单边／双边口径分开；价格／全收益／现金净值分开。
5. 各线规则数、模型 fits、曲线数和历史 formal trial 不相加为全局试验数；全局核对完成前标为未知。
6. 旧方案的优先级与启动安排按当时快照读取，不能覆盖 [修补整理计划](research-repair-and-consolidation-plan-2026-10.md)或 current 权限。

## 接手导航

- [当前事实](current.md)
- [项目规则](project-rules.md)
- [修补整理计划](research-repair-and-consolidation-plan-2026-10.md)
- [主机手册](operations/host-runbooks.md)
- [复核前申报快照](archive/current-archive-pre-review-2026-10-11.md)
