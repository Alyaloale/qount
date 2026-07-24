# 预登记草稿：crypto_vol_crisis_state_v1

> **状态**：DRAFT（无结果预登记）｜**权威**：L3 研究草稿｜**最后更新**：2026-07-25
> **本文回答**：`crypto_vol_crisis_state_v1` 的冻结合同、门与 kill test（吸收 CRA 两条规则）。
> **TL;DR**：Trial 148 已按此跑并 REJECT（尾残差恶化）；Trial 2/3 须引入不同信息否则关闭家族。

状态：**DRAFT / 无结果预登记**。`orders_authorized=false`、`paper_or_live_allowed=false`、`research_only=true`、
`existing_cache_only=true`。本文冻结合同**在读取任何候选结果之前**；正式 `protocol_hash` / `contract_hash` 由 build
脚本对本合同做 canonical hash 生成，owner 运行实验时回填全局实验账本（`research-advancement-roadmap.md` §2）。

归属：`research-advancement-roadmap.md` §R3（波动率与危机状态，P1）、R1.1-A 表 `crypto_vol_crisis_state_v1` 行。
两条被吸收的规则来自外部机器人 CRA 拆解（`docs/external-bot-cra-teardown.md`，来源等级 T4，仅作机制线索，不作证据）。

## 0. 本草稿要点

- 家族只输出 **RiskMultiplier ∈ [0,1]**，作用在 Base v0.2 的目标 gross 上；**不预测方向、不产生新仓位架构**。
  Base 保持控制组不变（RiskMultiplier ≡ 1）。
- 吸收 CRA 两条规则，**诚实改写为因果、非方向的风险状态触发器**：
  1. **防瀑布（anti-cascade）** → 崩盘/波动跃升触发的非对称快速降险（CRA 原文「1 分钟急跌 >2% 暂停加仓」）。
  2. **反向信号退出（reverse-signal exit）** → 改写为**regime-flip 加速降险**（CRA 原文「信号翻转即平仓」是方向性退出，
     本家族只缩放风险，故改为"趋势 regime 在高波动态下翻转时把 RiskMultiplier 打到地板"，不选多空）。
- **必须与两类既有失败显式区别**（否则计作旧 family 后续，不新开）：
  - (a) 已失败的 price-only RF/HMM/GRU vol scaling 和宏观/链上风险缩放 → 本家族新增**非对称、事件触发、含横截面相关跃升**
    的信息，且主指标是降险**效率**与尾部残差，不是 Sharpe、不是方向准确率。
  - (b) 刚关闭的 `multi_speed_trend_v1` Trial 147 快层 de-risk（已证明**低效**：Sharpe 1.291<1.416、turnover +38%）→
    本家族是**纯风险 overlay**（不改架构），且 kill test **直接瞄准 147 失败的那条轴**：若降险效率不达标或 turnover 超预算即拒绝。

## 1. ResearchCard（R1.1 卡片，缺一不得进正式 trial）

| 卡片字段 | 内容 |
| --- | --- |
| family / mechanism / causal direction | `crypto_vol_crisis_state_v1`；高波动/下行半方差/振幅扩张/相关性跃升降低趋势的单位风险回报；因果方向=状态→未来风险，只降险不择向 |
| decision clock / outcome horizon / independence unit | TOP3 完成日线收盘决策；outcome=下一持有区间的回撤/尾部；独立单位=日 bar（因果，只用已完成 bar） |
| required raw sources / PIT / history limit | 现有缓存 `state/r0_runtime/klines`（TOP3 UM 1d）+ `funding`；无需新下载；1 分钟级 anti-cascade 的**真分辨率**需 sub-daily 数据（当前缓存没有）→ 见 §5 数据诚实说明 |
| features / missing-data rule / eligibility rule | 见 §3；缺 bar 不前视填补，funding 缺失禁填 0；eligibility=Base 已持有的 TOP3 |
| baseline / control / primary metric / secondary | 控制=Base v0.2（RM≡1）；对照=固定对称 vol-target、multi_speed 参考；主指标见 §4.1 |
| cost model / beta-residual plan / stress plan | 复用 Base 冻结成本（taker 10bps、slippage 2bps、funding_included）；报 raw 与 TOP3 beta-residual；压力=成本×2、延迟1 bar、随机漏单、分段 |
| kill tests / allowed sensitivities / trial budget | 见 §4.2 / §4.3；预算 3 |
| overlap with local negative evidence / promotion blockers | 与 price-only vol scaling、147 快层 de-risk、crash filter 有重叠 → 见 §0 区别；promotion blocker=已消费历史、无 PIT、成本 estimated、无新时间证据 |

## 2. decision_contract 骨架（可直接转 preregistration.json）

```json
{
  "hypothesis_family": "crypto_vol_crisis_state_v1",
  "candidate_id": "crisis_state_anti_cascade_v1",
  "data": {
    "market": "um", "interval": "1d",
    "start_month": "2020-02", "end_month": "2026-06",
    "universe": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
    "existing_cache_only": true,
    "data_role": "consumed_historical_discovery_pool"
  },
  "execution": {
    "control": "MiniTrend-UM-Base-v0.2",
    "capital_usdt": 400.0, "direction": "long_cash",
    "shorting_allowed": false, "leverage_boost_allowed": false,
    "funding_included": true, "taker_fee_bps": 10.0, "slippage_bps": 2.0,
    "estimated_min_notional_usdt": 5.0, "stop_cooldown_completed_bars": 3
  },
  "signal": {
    "output": "risk_multiplier_[0,1]_applied_to_base_target_gross",
    "predicts_direction": false,
    "parameter_search_allowed": false,
    "risk_state_inputs": "see_section_3_frozen"
  },
  "sizing": { "maximum_effective_gross": 1.0 },
  "trial": { "family_trial_budget": 3, "trial_number_within_family": 1 }
}
```

## 3. 冻结信号定义（看结果前冻结，不做参数搜索）

RiskMultiplier 只**下调**Base 的 gross，从不放大（上限 1.0）。三个触发器全部用**已完成 bar**（因果）：

### 3.1 Rule-1 anti-cascade（防瀑布，主触发器）
CRA 原文：1 分钟内急跌 >2% 暂停加仓。日线因果改写（避免固定百分比拟合，用相对波动标准化）：

- **崩盘 bar**：已完成日 bar 收益 `r_t ≤ -k_sigma × vol20_{t-1}`（`k_sigma=3.0` 冻结，即约 3σ 下行日），
  **或** 当日振幅 `(high-low)/close ≥ p_range × median_range20_{t-1}`（`p_range=2.5` 冻结）。
- **响应**：触发后下一决策 bar 起 `RiskMultiplier = floor`（`floor=0.3` 冻结），冷却 `N=3` 完成 bar（与 Base stop_cooldown 一致），
  之后**线性恢复到 1.0**（非对称：快切慢回）。

### 3.2 Rule-2 regime-flip de-risk（反向信号退出的非方向改写，次触发器）
CRA 原文：出现反向信号即清仓。本家族不择向，改为"高波动态下趋势 regime 翻转→打地板"：

- **regime-flip**：Base 的 60 日 trailing return 由正转负（`sign(ret60_{t}) ≠ sign(ret60_{t-1})` 且转负）
  **且** 当前 `vol20_t` 处于全样本滚动上 1/3 分位（`vol_tercile=top` 冻结）。
- **响应**：`RiskMultiplier = floor`，同样 `N=3` 冷却后线性恢复。
- **诚实标注**：literal "reverse-signal exit" 是方向性退出逻辑，更自然属于 trend/execution 家族；此处只保留其"信号翻转即降险"
  的**非方向**内核，作用于 Base 已有方向，不新增多空判断。

### 3.3 新增信息元素（与 price-only vol scaling 区别的关键）
- **相关性跃升**：BTC–ETH / BTC–BNB 的 20 日滚动相关同时升破 `corr_jump=0.9`（冻结）→ 触发降险。
  这是**横截面**信息，不在旧单资产 price-only vol scaling 里，是本家族声称"新信息集"的依据。

三触发器取**最强降险**（min RiskMultiplier）。三个正式 trial 分别隔离：

| Trial | 内容 | 隔离目的 |
| --- | --- | --- |
| 1 | 仅 Rule-1 anti-cascade（含 3.3 相关跃升） | 测最便宜、最可证伪的崩盘降险 |
| 2 | 仅 Rule-2 regime-flip de-risk | 测趋势翻转降险是否独立有效 |
| 3 | 三触发器合成非对称 crisis-state | 强制 family 复盘 |

## 4. 主指标、Kill test 与允许敏感度

### 4.1 主指标（primary_metric）
**降险效率比** = `(Base_maxDD − Cand_maxDD) / max(Base_CAGR − Cand_CAGR, ε)`（每牺牲 1pp 年化换回多少 pp 回撤），
`primary_metric = derisk_efficiency_ratio`。次指标：尾部（CVaR5%）残差改善、Sharpe 变化、turnover 增量、
raw 与 TOP3 beta-residual、分段稳定。**不以 Sharpe 或方向准确率作主指标。**

### 4.2 失败条件（failure_conditions，任一即 reject）
```
derisk_efficiency_ratio_below_frozen_floor            # 降险不划算（直接瞄准 147 低效降险失败）
tail_cvar5_not_improved_vs_base                        # 尾部没改善 = 白降险
sharpe_worsens_beyond_budget                           # 风险调整后更差（147 的病）
turnover_increase_exceeds_budget                       # 换手爆掉（147 +38% 的病）
derisk_benefit_concentrated_in_single_crash_segment    # 只拟合某一次崩盘（3 段里 ≥1 段无改善即警示）
not_positive_at_doubled_execution_cost
not_robust_to_one_bar_signal_delay
equivalent_to_symmetric_vol_target_within_noise        # 与旧 vol scaling 无实质区别 → 计旧 family 后续
gross_cap_or_nav_reconciliation_failure
funding_history_has_zero_settlement_holding_interval
```
冻结阈值（看结果前定）：`derisk_efficiency_ratio ≥ 1.0`（至少 1:1 换）、`sharpe 不低于 Base − 0.05`、
`turnover ≤ 1.3 × Base`、CVaR5% 需改善且非单段驱动。

### 4.3 允许敏感度（allowed_sensitivity_range）
```
signal_delay_bars: [0, 1]
transaction_cost_multiplier: [1.0, 2.0]
```
**不允许**搜索 `k_sigma / p_range / floor / N / corr_jump / vol_tercile`——它们是冻结合同，不是可扫参数。

### 4.4 分段（防单次崩盘拟合，沿用 147）
```
2020-2021 : 2020-02-10 .. 2021-12-31
2022-2023 : 2022-01-01 .. 2023-12-31
2024-2026 : 2024-01-01 .. 2026-06-30
```

## 5. 数据诚实说明（重要）

- CRA 的 anti-cascade 是 **1 分钟**级 intrabar 规则；当前缓存只有 **TOP3 日线**，无法在真分辨率复现。§3.1 是**日线代理**
  （单日 3σ 下行 / 振幅扩张），**必须**在报告里标为 proxy，不得声称已验证 1 分钟规则。
- 真分辨率验证是 sub-daily / 前向数据任务（与 Wave 3 前向采集同性质）：若日线代理显示有效率信号，再决定是否值得建 1m/5m
  append-only 采集去做忠实版本；反之若日线代理即失败，1 分钟版本先不投入。
- 全部 `data_role=consumed_historical_discovery_pool`：这是已看过的 discovery 窗口，改阈值后不得再当独立 OOS；任何 retain
  仅 `retain_for_next_evidence`，须新时间证据才谈 promotion。

## 6. interpretation（写入 protocol.interpretation）

> Formal discovery Trial(s) of `crypto_vol_crisis_state_v1`. Outputs a causal RiskMultiplier∈[0,1] only; never predicts
> direction. Absorbs two ideas from the T4 CRA bot teardown (anti-cascade de-risk; reverse-signal→regime-flip de-risk),
> rewritten as non-directional, causal risk-state triggers with a NEW cross-sectional correlation-jump input to distinguish
> it from the already-failed price-only vol/HMM/GRU scaling. The primary metric is de-risk EFFICIENCY (drawdown saved per
> return sacrificed) plus tail-CVaR residual — the exact axis on which the closed multi_speed_trend_v1 fast-layer de-risk
> (Trial 147: Sharpe↓, turnover↑) failed. A rejection closes or redirects the mechanism; it does not rescue Trial 147 nor
> any prior price-only scaling. orders_authorized=false throughout.

## 7. 下一步（owner 执行）

1. 评审本草稿，冻结/微调 §3 阈值（在**看结果前**）。
2. build 脚本对 decision_contract 做 canonical hash → 生成 `protocol_hash`/`contract_hash` 与无结果 preregistration.json，
   登记 GlobalExperimentRecord（`decision=planned`）。
3. 在现有 TOP3 缓存上跑 Trial 1（Track B，不受宇宙阻塞），读数回填账本；第 3 个 trial 强制 family 复盘。
4. 若日线代理有效率信号成立，再评估 sub-daily 忠实版本（前向数据任务）。
