# 研究线总览

> **状态**：active navigation｜**权威**：导航；当前裁决与权限只在 [current.md](current.md)｜**最后更新**：2026-11-02
> **TL;DR**：按证据强度分类导航。研究工件默认 `research_only=true / orders_authorized=false`；现行宏观的既有生产授权与参数仅见current，不由本页新增或撤销。旧旗舰申报已撤销，不从历史报告推定运行权限。

---

2026-10-16本地整理新增 `one_atr` 原生合约独立回测，结果与限制见[current](current.md)。网页研究目录与前向模拟开关分开；paused/archived不自动恢复采集或实盘。通用状态所有旧Calmar字段按current更正，不继续引用1.02作标准基准。

面向以后资产管理的策略筛选与角色建议见[策略选择与设计依据](asset-management-strategy-review-2026-10.md)：优先纳指ETF风险预算/G20，CTA-R作分散化候选；不按不同窗口的收益数字给全项目排名。

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
- **历史展示口径**：旧MA120账户为小数份额与假定现金2%收益，不与最新整数份额回放混排。
- **最新同引擎对照**：513100.SH，2014-01-02至2026-10-09，10万元、100份整手、单边6bp佣金/5bp滑点及最低5元、现金0收益；MA120 CAGR11.42%/MDD28.15%，买持20.00%/28.56%，周度波动预算17.99%/18.79%。创业板同波控3.81%/53.52%，不支持泛化；均已消费历史。
- **过拟合风险**：中低。规则简单（展示基线为 MA120＋1.5% 带宽择时），参数少，但样本内结果，且低于买持基准
- **前向**：原MA120/1.5%/两日确认账户已按owner要求续接历史与补算，沿用小数份额和假定现金年收益2%；分段身份及当前状态见current，不能把混合曲线当独立前向。
- **新研究入口**：`scripts/research/compare_etf_risk_budget.py`，固定周度波动预算与买持/择时/静态配置对照；[10月25日结果](../state/research_runs/etf_risk_budget_20261025_final/report.md)，当前裁决只见current。

### A2. 通用市场状态与动态期望策略
- **主文档**：[策略方案](universal-regime-expectancy-strategy-2026-10.md)
- **代码**：`research/universal_regime_expectancy.py`（878 行）
- **状态**：v1.9历史研究保留；10月22日起只运行显式固定的v1.3基准前向；10 大宏观正交标的（SPY, SMH, IWM, XLI, XLB, GLD, CPER, XLU, TLT, UUP）
- **证据**：v1.3原1X全期累计+26.70%、MDD26.22%；原收益/MDD字段1.02及后续7–9不是标准Calmar。历史文档标作“样本外”的区间已被后续迭代消费，不作为今天独立OOS。后续高杠杆申报保留历史身份，不用于当前策略排名。
- **过拟合风险**：**高**。一周内从 v1.0 迭代到 v1.9，每个版本都恰好提升业绩；每次"修复"针对已知失败交易做事后优化。后续版本声称的 Calmar 7–9 不应作为实盘准备依据
- **关键限制**：
  - 2020–2022 连续三年亏损约 -26.5%，全部正收益来自 2023–2026 商品牛市
  - 黄金（GLD/CPER）贡献了绝大部分利润；剔除后收益骤降
  - 跳空敏感性致命：1.5% 跳空 Calmar 1.02 → 2.0% 跳空 Calmar 0.08
  - 统计检验（p=0.0012、蒙特卡洛）仅覆盖 1X 现货，不覆盖 2.5X 版本
  - 币安 TradFi 合约 2026-04 才上线，流动性极薄（买一挂单 $35–$96），历史期间不可执行
- **研究问题**：保留现有固定v1.3模拟，判断新数据能否支持原机制；不自动新增观察天数或后续版本。旧收益/MDD不作标准Calmar；后续实验按具体问题和current边界决定。

### A3. Dual-Engine G20／C60／GC5／D15
- **主文档**：[paper 合同](qount_strategy_master_index.md)、[离线研究](dual-engine-optimization-2026-10.md)
- **代码**：`dual_engine/`、`scripts/operations/`
- **状态**：10月22日四账户已按owner要求从原现金/持仓续接历史、补算和后续模拟；分段身份及当前状态见current，旧YTD不冒充真实收益。
- **G20最新证据**：10月25日现金分红修正版已接入原模拟入口，2026-01-02至10-23累计21.39%/MDD15.95%，204点历史重建；不称当时前向。2018–2026美元总回报单位原20%为CAGR15.54%/MDD17.93%，固定15%12.41%/13.57%，动态13.69%/13.58%；成本/规模限制见[新对照](../state/research_runs/g20_fixed_budget_20261025_final/report.md)。
- **组件边界**：旧四账户和十七轮探索保留历史身份；GC5/D15是配置包装而非独立alpha，尚未继承本次G20分红修正，C60旧选币优势已撤回。不能将研究版本/曲线数量当独立证据数量。
- **过拟合风险**：中。17 轮迭代寻找领先机制，但 YTD 包含历史回放不是实盘收益
- **研究问题**：G20继续比较真实执行成本下的固定/动态风险取舍；原BTC双腿月度毛额重建已失败，与本次G20分红修复是不同问题，不互相覆盖。

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
- **状态**：10月22日恢复前瞻任务，16/19/20/21日缺口标为补算，保留原9月29日起连续账本、不在恢复日归一化；仍是原合同的收盘权重收益代理，不是下一开盘现金成交净值。
- **证据**：冻结规则美股复现2005-12-19至2026-09-28，10bp模型CAGR7.42%/MDD17.08%、Sharpe0.7474，20bp为6.94%/17.77%；未超同窗60/40的Sharpe0.7787。当前A股2/10bp账本与美股10/20bp复现口径不同，均非下一开盘现金成交认证。
- **下一步**：成本/可交易性与前向一致性待确认

### A6. 现行15U宏观策略研究
- **当前策略**：`rolling7_risk_no_chase_mr_signal_gap_1atr`，生产授权和25%压力预算见current，不由本页扩权。
- **证据**：2026-04-07至10-22前、15.2711USDT、原费用/容量与小时撮合，7笔模型交易闭合，基础累计32.56%/小时MDD12.18%，双成本−3.02%。同规则100/1000/10000USDT重跑基础2.15%/−2.78%/−3.27%，不能按小资金收益扩资。
- **设计定位**：固定小额执行实验，现行策略归属真实成交尚无证据；费用/容量/规模净优势未建立。见[规模研究](../state/research_runs/g20_fixed_budget_20261025_final/report.md)，与已封存的旧全球宏观区分。

### A7. G20 双核慢趋势全平策略（G20-DSF）
- **主文档**：[策略合同与归档](g20-dual-core-slow-trend-flat-2026-11.md)
- **代码**：`research/crypto_g20_hourly_portfolio.py`、`scripts/research/study_crypto_g20_daily_original_etf.py`
- **状态**：独立离线研究线；排除 BTC，使用 ETH/SOL 与原始 ETF 日线代理；未接入 paper/live，不继承现有 G20 现金/行业轮动权限
- **证据**：2022-06-28至2025-12-31、初始21.25U；双核心2仓总2x为57.95% CAGR/MDD67.69%，总4x为75.50%/87.20%；总6x及每仓10x均触发共享钱包清算
- **机制判断**：价格趋势为主要正贡献，资金费为负贡献；集中持仓、双腿同时失效才退出、固定数量造成的实际名义漂移共同制造高回撤。0.5x/1x/2x总名义的MDD仍为35.69%/50.20%/67.69%，不能把风险归因于杠杆单项
- **证据等级**：样本为复权 ETF 日线代理与同步加密采样，未独立 OOS；小资金最小名义、真实 ETF 永续成交、历史保证金档位和完整资金费未认证。保留研究价值，不给资金或实盘准入

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
| 清算级联 | [采集合同](research-forward-collector.md) | `mini_trend/` | 起点2026-08-18；10月16日已停采，原最早日期不能证明覆盖合格，本轮不恢复无关采集 |
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
2. 研究默认`research_only=true / orders_authorized=false`；来源、数据截止、代码/合同版本与样本身份写清，生产权限按current既有明确授权单独处理。
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
