# 研究线总览

> **状态**：active navigation｜**权威**：导航；当前裁决与权限只在 [current.md](current.md)｜**最后更新**：2026-10-15
> **TL;DR**：按证据强度分类导航。所有策略均为 `research_only=true / orders_authorized=false`，无实盘下单授权。旧旗舰申报已撤销，不从历史报告推定运行权限。

---

2026-10-16本地整理新增 `one_atr` 原生合约独立回测，结果与限制见[current](current.md)。网页研究目录与前向模拟开关分开；paused/archived不自动恢复采集或实盘。通用状态所有旧Calmar字段按current更正，不继续引用1.02作标准基准。

## 分类说明

| 分类 | 含义 |
| --- | --- |
| **A. 有正向证据** | 存在可复现回测或模拟盘运行，但均未经独立样本外验证；过拟合风险由低到高标注 |
| **B. 门槛失败或已封存** | 回测未通过预设门槛、旧高收益结论已撤销、或研究已主动封存 |
| **C. 辅助与长期采集** | 不直接产生交易信号，为其他线提供数据、情报或长期前向观察 |
| **D. 已停止 / 归档** | 不恢复、不新增实验 |

---

## A. 有正向证据（均未通过独立 OOS 验证）

### A1. ETF 均线择时研究
- **主文档**：[开发指南](personal-trading-assistant-guide.md)、[交付复查](research-s1-independent-review-2026-10.md#8-交付复查与验收范围修订2026-10-12-utc)
- **代码**：`research/personal_trading_assistant.py`
- **状态**：普通研究线；兼容标识 `personal_assistant`；S3-A/B/C 已交付
- **证据**：513100.SH，2013-05-15 至 2026-10-09，CAGR ~12.05%，MDD 28.16%；3,256 交易日，37 笔买卖。策略 CAGR 低于同窗买持 ~21.28%
- **过拟合风险**：中低。规则简单（展示基线为 MA120＋1.5% 带宽择时），参数少，但样本内结果，且低于买持基准
- **下一步**：如要继续前向记录，须先明确其将检验的策略问题及信息价值

### A2. 通用市场状态与动态期望策略
- **主文档**：[策略方案](universal-regime-expectancy-strategy-2026-10.md)
- **代码**：`research/universal_regime_expectancy.py`（878 行）
- **状态**：v1.9 完成；10 大宏观正交标的（SPY, SMH, IWM, XLI, XLB, GLD, CPER, XLU, TLT, UUP）
- **证据**：
  - **可信基准（v1.3 因果律修复后）**：1X 现货全周期 +26.70%，MDD 26.22%，旧收益/MDD 字段1.02（非标准Calmar）；样本外 +27.14%，MDD 8.62%，Calmar 3.15
  - **后续版本（v1.4–v1.9）**：每版均提升业绩，v1.7 声称 +74.33%/Calmar 7.11，v1.8 声称 +280.72%/Calmar 9.17（2.5X 杠杆）
- **过拟合风险**：**高**。一周内从 v1.0 迭代到 v1.9，每个版本都恰好提升业绩；每次"修复"针对已知失败交易做事后优化。后续版本声称的 Calmar 7–9 不应作为实盘准备依据
- **关键限制**：
  - 2020–2022 连续三年亏损约 -26.5%，全部正收益来自 2023–2026 商品牛市
  - 黄金（GLD/CPER）贡献了绝大部分利润；剔除后收益骤降
  - 跳空敏感性致命：1.5% 跳空 Calmar 1.02 → 2.0% 跳空 Calmar 0.08
  - 统计检验（p=0.0012、蒙特卡洛）仅覆盖 1X 现货，不覆盖 2.5X 版本
  - 币安 TradFi 合约 2026-04 才上线，流动性极薄（买一挂单 $35–$96），历史期间不可执行
- **下一步**：冻结当前版本做真正的前向验证（3–6 个月未见数据）；停止版本迭代；旧 Calmar 1.02 实为累计收益/MDD，不作实盘准备依据；是否安排新实验按研究问题决定

### A3. Dual-Engine G20／C60／GC5／D15
- **主文档**：[paper 合同](qount_strategy_master_index.md)、[离线研究](dual-engine-optimization-2026-10.md)
- **代码**：`dual_engine/`、`scripts/operations/`
- **状态**：四账户公共数据模拟已部署 VPS
- **证据**：G20 YTD +15.26%，MDD -16.33%，291 个观测点；十七轮离线研究（287 版本/1,137 曲线）
- **过拟合风险**：中。17 轮迭代寻找领先机制，但 YTD 包含历史回放不是实盘收益
- **下一步**：月度重建资金现金流已失败；离线领先仍待新鲜确认

### A4. A 股低波动上升趋势
- **主文档**：[选股研究](ashare-strategy-study-2026-10.md)
- **代码**：`research/ashare_*.py`
- **状态**：通过最低研究门，待新鲜确认
- **证据**：2015–2026-09-30 价格代理基础累计 +201.23%，年化 10.22%，MDD 33.86%；10 仓虚拟持仓
- **过拟合风险**：中。规则相对简单，但全部为复权价格代理，现金总回报/公司行动/PIT/独立 OOS 均未认证
- **下一步**：等新鲜行情确认；当前源包截止 2026-09-30

### A5. CTA-R 独立侧车
- **主文档**：[跨市场复现](cta-r-us-replication-and-c60-vol-matched-2026-09.md)、[前瞻合同](cta-r-forward-ledger-2026-09.md)
- **代码**：`research/cta_r_*.py`
- **状态**：已部署前瞻采集；5 个观测点/4 个前向交易日
- **证据**：冻结规则美股复现通过最低研究门，未超 60/40 Sharpe，未获晋级
- **下一步**：成本/可交易性与前向一致性待确认

---

## B. 门槛失败或已封存

| 线路 | 主文档 | 代码 | 结论 |
| --- | --- | --- | --- |
| A 股 Q-DIV-Core | [研究](ashare-q-div-ivol-study-2026-10.md) | `research/q_div_*.py` | 四曲线完成，CAGR 3.42% < 基准+1%，换手 2.17x > 1.20x 上限，年度胜率 5/11；不调参救援 |
| A 股 Q-DIV-IVOL | [研究](ashare-q-div-ivol-study-2026-10.md) | `research/q_div_*.py` | 截止日 20 候选名单完成，历史回测未运行 |
| A 股赛道轮动 A／综合 C | [封存说明](ashare-sector-momentum-study-2026-10.md) | `research/ashare_sector_momentum.py` | 旧高收益结论撤销，不继续称旗舰 |
| A 股 EKF-MPC／麒麟 | [EKF-MPC](ashare-ekf-mpc-study-2026-10.md)、[麒麟](ashare-master-strategy-design-2026-10.md) | `research/ashare_ekf_mpc.py` | 各变体不互相继承收益或复核资格 |
| A 股龙头趋势 | [研究](ashare-strategy-study-2026-10.md) | `research/ashare_*.py` | 基础年化 -21.28%，回撤 94.97% |
| A 股质量动量复合 | [研究](ashare-strategy-study-2026-10.md) | `research/ashare_*.py` | 基础年化 -14.92%，回撤 90.04% |
| A 股行业强势 | [研究](ashare-strategy-study-2026-10.md) | `research/ashare_*.py` | 基础 -15.21%，回撤 61.60% |
| A 股 ETF 趋势／红利盾牌 | [代理研究](ashare-etf-trend-shield-study-2026-10.md) | `research/ashare_trend_etf.py` | 指数代理单列；实际 ETF、份额拆分、成本/换手待核 |
| 币安全球多资产合约 | [封存说明](binance-global-macro-design-2026-10.md) | `research/binance_global_macro.py` | 未通过准入，旧高收益撤销 |
| C60 v1／v2 | [时点宇宙复核](c60-pit-universe-survivorship-2026-09.md) | `research/c60_*.py` | 选币优势撤回，梯度失败 |
| 小额合约突破 v0.1–v0.3 | [研究](small-account-breakout-study-2026-10.md) | `research/small_account_breakout*.py` | 冻结历史验证净期望为负；无晋级授权 |
| Binance 10 USDT 状态门 | [方案](binance-micro-regime-breakout-plan-2026-10.md) | `research/small_account_breakout*.py` | 96 组诊断完成，1H 有门仅两笔赢家贡献 99.93% 利润，成本稳健性未通过 |
| ETF Trader P2／P3 Alpha | [P3 结果](etf-p3-research-plan-2026-10.md) | `research/etf_trader/`、`research/etf_alpha/` | P2 停训；P3 v2 CAGR 5.69%，未证明神经增量；R3 pilot 无增量停止 |

---

## C. 辅助与长期采集

| 线路 | 主文档 | 代码 | 说明 |
| --- | --- | --- | --- |
| 清算级联 | [采集合同](research-forward-collector.md) | `mini_trend/` | 有效窗口从 2026-08-18 起；最早 2027-02-14 才可评估 |
| Alpha Agents／日报 | [研究角色](alpha-agent-plan.md) | `alpha_agents/`、`intelligence/` | LLM 只输出资料与审计，不产生订单 |
| 稳定币流动性冲量 | [来源 G0](alpha-agent-plan.md) | — | 来源资格通过，待市场状态检验；不等于预测或现金收益证据 |
| 短周期机会／业绩上修 | [研究](short-horizon-opportunity-study-2026-10.md) | `research/opportunity_*.py` | 小时主动流候选零触发停止；业绩上修 data_gate=pending |

---

## D. 已停止 / 归档

| 线路 | 归档 | 说明 |
| --- | --- | --- |
| FOMC／PreEvent | [事件研究](personal-200u-event-strategy.md) | FOMC live 部署已取消 |
| 被动 Sleeve | [被动合同](l1-passive-allocation-preregistration.md) | 不继承 L1-S2 资格 |
| GRID／RV／X4／旧 MiniTrend 实盘 | [历史索引](archive/README.md) | 停止或冻结，不恢复、不新增实验 |

---

## 研究记录规则

1. 当前裁决只写入 current；本页和主机全景只导航，绩效数字与窗口保留在本线证据中。
2. `research_only=true / orders_authorized=false`；来源、数据截止、代码/合同版本、样本身份和停止条件写清。
3. 旧结果不覆盖。错误修复不把旧历史变成独立 OOS；原 JSON 字段名不是最终裁决。
4. 交易次数、名义换手、单边/双边口径分开；价格/全收益/现金净值分开。
5. 各线规则数、模型 fits、曲线数和历史 formal trial 不相加为全局试验数；全局核对完成前标为未知。
6. 旧方案的优先级与启动安排按当时快照读取，不能覆盖 [修补整理计划](research-repair-and-consolidation-plan-2026-10.md)或 current 权限。

## 接手导航

- [当前事实](current.md)
- [项目规则](project-rules.md)
- [修补整理计划](research-repair-and-consolidation-plan-2026-10.md)
- [主机手册](operations/host-runbooks.md)
- [复核前申报快照](archive/current-archive-pre-review-2026-10-11.md)
