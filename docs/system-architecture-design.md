# qount 个人量化交易系统架构设计

版本：`v1.2`

更新时间：`2026-07-22`

状态：目标架构与渐进迁移合同；单策略Base minimal-live已落地。本文本身不构成新的充值、扩容或策略晋级授权。

## 0. 文档定位

本文是 qount 的系统工程主设计，统一以下内容：

- 当前 Mac、Windows 外置盘、WSL、VPS 和 `qount.alyaloale.com` 的真实分工；
- 已有 Base、组合治理、MiniTrend dispatcher、研究 agents 和旧 X4/CxD 代码的复用边界；
- 数据、策略、组合、风险、执行、账本、对账、通知、Dashboard 和 LLM 的目标接口；
- 从当前 Base minimal-live 提升到可恢复、可解释的单策略 Level 3，再扩展多策略的顺序；
- 未来多策略扩展和持续优化必须遵守的治理规则。

本文不替代：

- [current.md](current.md)：当前生产状态和研究结论；
- [crypto-portfolio-system-plan.md](crypto-portfolio-system-plan.md)：策略组合和研究计划；
- [storage-topology.md](storage-topology.md)：跨主机存储与计算边界；
- [mini-trend-agent/execution.md](mini-trend-agent/execution.md)：现有 MiniTrend 试点执行细节。

发生冲突时，生产事实以 `current.md` 和 VPS 只读证据为准，主机路径以
`storage-topology.md` 为准，本文负责目标模块边界和迁移原则。

## 1. 系统要回答的问题

一个批次完成后，系统必须能用确定性证据回答：

| 问题 | 必须存在的证据链 |
| --- | --- |
| 当前为什么持有这些仓位 | `PositionReadModel -> LedgerPosition -> Fill -> OrderPlan -> RiskDecision -> PortfolioTarget -> StrategyIntent -> MarketSnapshot` |
| 订单由谁产生 | `exchange_order_id/client_order_id -> order_id -> batch_id -> decision_id -> strategy_id/version` |
| 实盘为什么和回测不同 | 信号差异、数据时点、价格延迟、spread/slippage、费用、funding、deadband、最小名义、rounding、部分成交和净额节省分项 |
| 数据错了或程序重启会怎样 | 数据质量门、单实例锁、checkpoint、订单状态恢复、三方对账和 fail-closed 事件 |
| 新策略凭什么获得实盘资格 | 冻结合同、数据/代码/配置 hash、trial ledger、promotion artifact、shadow/paper证据和 owner authorization |
| LLM 做了什么 | 原始来源 hash、受限上下文、模型/提示版本、结构化报告、人工或研究动作；不得存在订单或权重输出 |

如果某个仓位、资金变化、订单或配置变化不能沿这条链解释，它不是“暂时未知”，而是系统异常。

## 2. 当前事实基线

### 2.1 物理拓扑

```text
Mac /Users/alyaloale/Code/qount
  source/git truth、架构、研究设计、轻量测试、promotion审查

Windows E:\qount_data / WSL /mnt/e/qount_data
  immutable raw、dataset、artifact、manifest、环境锁、冷备份

WSL /home/alyaloale/Code/qount
  7945HX/RTX 4060研究计算、特征、回测、ML、Bootstrap

VPS /root/qount
  production truth、Base 100 USDT minimal-live、order-free refresh、journal、dashboard发布

qount.alyaloale.com
  Caddy + Basic Auth保护的只读静态监控站
```

生产 Key 只允许存在于 VPS 仓库外 `0600` 环境文件。Mac、WSL、外置 ExFAT 盘、LLM
上下文和 Dashboard 均不得持有生产 Key。

### 2.2 当前生产能力

当前 VPS 已有 MiniTrend Base 的独立日线minimal-live周期：

```text
runtime proof
  -> USD-M rules
  -> completed bars/funding
  -> private read-only preflight
  -> paper replay
  -> causal projection
  -> readiness
  -> dry dispatcher
  -> final readiness / manual arm / minimal-live registry
  -> live dispatcher / post-dispatch ledger reconciliation
```

已存在的可复用生产能力：

- Base v0.2 完成日线信号、3xATR 吊灯、3根冷却和35% deadband；
- 账户余额、one-way、逐仓1x、普通订单、条件订单和仓位的只读预检；
- source/decision/state hash 绑定和重复决策保护；
- 确定性 client order ID；
- Binance `STOP_MARKET closePosition` 保护计划；
- append-only row hash / chain hash journal；
- 成交后仓位和保护单对账；
- 5%试点单日损失或10%试点峰值回撤时 flatten-then-halt；
- 独立 manual arm、live switch 和 confirmation 三重授权。

`qount-mini-trend-live.timer`在0.2.7升级维护期间为`disabled/inactive`。恢复前必须重新验证release provenance、
canonical通知库迁移、无订单周期、readiness五轴、账本和post-dispatch对账。首次live cycle已写完整锁定、完成、账本和post-dispatch对账，
但Base信号为全现金，实际0订单、0成交；因此系统已获得minimal-live运行证据，尚未获得真实fill/fee/slippage/STOP触发证据。

### 2.3 当前代码问题

当前代码不是能力不足，而是边界分散：

| 现状 | 风险 |
| --- | --- |
| `mini_trend/` 同时包含核心信号、试点执行和大量研究实验 | 生产代码审查面过大，策略文件难以快速定位 |
| 顶层 `journal.py/risk_engine.py/notifier.py` 属旧运行链，MiniTrend 另有 JSONL 合同 | 账本、通知和风险口径存在两套来源 |
| `x4/`、`rv/`、C×D 和旧 cron 仍在仓库 | 容易把 legacy 状态或执行器误接回生产 |
| 入口分散在大量 `scripts/research` 和 `scripts/desktop` | 业务逻辑容易继续进入脚本，难以复用和测试 |
| 多策略 `StrategyIntent` 和 allocator 只在本机代码 | 目标组合架构尚未进入 VPS 生产运行链 |
| Dashboard v1 read-model链和publisher已在VPS运行；个人微信通知transport已接入，但publisher本身仍严格只读 | 不能把publisher健康刷新误当账户/决策刷新，也不能用本地fixture或旧JSON洗新 |
| 旧顶层`Notifier`与新`notifications/`并存 | 继续扩展transport前必须保持producer、凭据、限流和投递责任边界隔离 |
| production release已绑定commit、source tree和逐文件hash；Mac可继续有未同步文档或研究改动 | 任意生产代码/config变化都必须重新发布、order-free readiness并轮换arm，不能沿用旧provenance |

### 2.4 当前成熟度

| 能力 | 当前成熟度 | 解释 |
| --- | --- | --- |
| 研究治理 | Level 2-3 | hash、trial、历史/forward角色已较完整 |
| 策略研究 | Level 2-3 | Base稳定，CxD/CTA-R已开放historical/discovery/virtual；family mapping已落证据，actual lifecycle/cost/NAV待研究数据 |
| order-free运行 | Level 2 | systemd、preflight、paper、dry、readiness已部署 |
| 执行代码 | Level 2-3 | 首次live与recurring幂等周期已验证；真实有单成交路径仍只有模拟/故障测试证据 |
| 内部账本 | production Level 2 | SQLite WAL、event/cash/NAV、post-dispatch reconciliation已接入MiniTrend live |
| 恢复机制 | 本地Level 2 / production Level 1-2 | UNKNOWN/client-ID恢复合同和故障重放已本地实现；尚无真实交易所接入证据 |
| Dashboard | 本地Level 2 / production Level 2 | v1十页已接ledger v3、四项健康和trace；VPS publisher每两分钟发布真实order-free authority，账户/决策stale与系统健康fresh独立显示 |
| 通知与日报 | 本地Level 2 / production Level 2 | 分级事件、WAL outbox、重试、审计、确定性DailyBrief和六角色DailyIntelligence已实现；个人微信真实投递与每日scheduler已接入，交易权限保持隔离 |
| 实盘证据 | Level 1 | Base已manual arm并运行live；当前全现金，尚无真实成交样本 |

### 2.5 本地research-ready结论

本地共享底座已经可以推进研究：标准contracts/trace、不可变artifact、GlobalExperimentRecord、point-in-time universe合同、
三类NAV scorecard、单sleeve allocator、virtual目标、独立账本/对账、certification和venue provenance均已有实现与测试。
日历批次、trial数、promotion状态和sleeve数不再作为本地入口门。

本地研究入口已进一步闭合：标准多sleeve runtime已连接`MarketSnapshot`、多个`StrategyIntent`、allocator、`RiskDecision`、
reduce-before-increase `OrderPlan`、virtual venue、`RuntimeLedger`、三类NAV和三方对账，并落manifest-last不可变integration artifact；
R0历史family mapping已由实际代码/文档hash确认，lifecycle/cost/NAV的available与missing字段也有v4 readiness证据。架构仍未“全部完成”：
标准runtime尚未替代legacy MiniTrend production dispatcher，R0 actual point-in-time数据和候选Standalone NAV尚未产生，Base自然fill归因
尚无样本。后续工作可以并行，不需要等待30天或第二个promotion sleeve。

## 3. 架构原则与关键取舍

### 3.1 不变量

```text
strategy_never_calls_exchange
portfolio_gross <= 1.0
no_unexpected_short
no_unmanaged_position
one_completed_bar_one_decision
one_decision_one_order_batch
all_orders_have_decision_id
all_fills_have_order_id
all_positions_are_reconciled
all_cash_changes_are_explained
all_live_strategies_are_promoted
no_incomplete_bar_in_signal
no_future_data_in_feature
llm_never_changes_live_risk
```

这些不变量应同时存在于类型校验、运行时断言、failure tests 和 Dashboard health 中。

### 3.2 技术取舍

| 决策 | 选择 | 原因 |
| --- | --- | --- |
| 部署形态 | 模块化单体 + systemd | 日线、小账户、单VPS，不需要微服务复杂度 |
| 主运行语言 | Python 3.11+ | 与当前代码、ccxt、研究工具一致 |
| 生产可查询存储 | VPS ext4上的SQLite WAL | 单写者、低频、事务和备份足够；不在ExFAT运行 |
| 审计记录 | append-only JSONL + row/chain hash | 人可读、可归档、可独立验证篡改 |
| Dashboard | 先保留静态SPA + 原子发布read model | 当前规模无需先建Web后端，攻击面小 |
| 实时显示 | 后端生成权威估值，前端只展示和轮询 | 避免浏览器形成第二套PnL |
| 配置 | TOML/JSON非密配置 + 环境变量密钥 + 0600 arm | 配置可hash，密钥不入库 |
| 调度 | systemd timer/service | 已部署、可审计、资源限制和失败状态明确 |
| LLM | 只读信息与分析旁路 | 允许提高研究和解释效率，不扩大交易权限 |
| 策略晋级 | promotion artifact + owner authorization | 研究结果不能自动变成真钱风险 |

只有出现以下任一条件时才评估 PostgreSQL 或只读 API 服务：多个并发写者、需要跨设备复杂查询、
SQLite备份窗口不可接受，或 Dashboard 历史查询已无法通过预生成read model满足。

## 4. 目标总体架构

```text
                         Governance / Registry
                contracts, versions, promotion, authorization
                                  |
                                  v
Sources -> Data Plane -> MarketSnapshot -> Strategy Runtime
              |                              |
              | Promotion data               | StrategyIntent[]
              v                              v
        Research Plane                 Portfolio Allocator
              |                              |
              | PromotionArtifact            | PortfolioTarget
              +---------------------> Governance allowlist
                                             |
                                             v
                                      Deterministic Risk
                                             |
                                             v
                                         OrderPlan
                                             |
                                             v
                                    Execution State Machine
                                             |
                                    OrderEvent / FillEvent
                                             |
                                             v
                                    Ledger + Reconciliation
                                             |
                  +--------------------------+------------------------+
                  |                          |                        |
                  v                          v                        v
             Read Models                Alerts                 Daily Reports
                  |                          |                        |
                  +--------------------------+------------------------+
                                             |
                              qount.alyaloale.com / notifications

Verified sources -> InformationEvent -> LLM sidecar -> InsightReport/Proposal
                                                (never target/order/risk override)
```

核心规则：策略只表达“希望持有什么”；组合层决定账户目标；风险层决定是否允许增加风险；
执行层决定如何从当前仓位到达批准目标；账本负责解释最终发生了什么。

## 5. 九个核心域

### 5.1 Governance

Governance 维护：

- `StrategyContract`：市场、标的、周期、信号、参数、成本、风险、停止条件；
- `StrategyVersion`：语义版本、code hash、config hash；
- `TrialRecord`：假设、数据角色、trial编号、结果和决定；
- `PromotionArtifact`：候选证据和允许的下一运行模式；
- `StrategyRegistry`：当前每个策略的状态和允许风险预算；
- `OwnerAuthorization`：manual arm、风险增加、暂停和恢复的人工决定。

允许状态：

```text
draft -> research -> frozen_candidate -> shadow -> paper
      -> minimal_live -> scaled_live

任何运行状态 -> halted
halted -> 只能经reconciliation + owner authorization恢复到原级或更低级
```

规则或参数变化必须创建新 `strategy_version`。不得覆盖旧合同，也不得让 Dashboard 上的显示名称掩盖
真实版本。

### 5.2 Data Plane

数据固定为四层：

```text
raw -> normalized -> point_in_time -> feature/dataset
```

所有记录至少包含：

```text
venue, symbol, event_time, published_at, observed_at,
available_at, ingested_at, source_hash, schema_version
```

`MarketSnapshot` 是生产策略唯一输入。它是不可变批次对象，必须绑定：

- 完成bar和funding的截止时间；
- 交易规则版本；
- 账户只读快照引用；
- 数据质量结果；
- snapshot hash；
- 决策最早可用时间。

本地已实现的v1合同字段为：

```json
{
  "schema_version": 1,
  "snapshot_id": "...",
  "decision_time": "...",
  "data_cutoff": "...",
  "prices": {},
  "funding": {},
  "features": {},
  "exchange_rules_hash": "...",
  "account_snapshot_hash": null,
  "data_quality": {"complete": true, "blockers": []},
  "source_hashes": {"market_data": "..."},
  "snapshot_hash": "..."
}
```

`snapshot_hash`覆盖全部合同字段，`snapshot_id`由decision time和snapshot hash确定性生成。过渡期Base projection
adapter会生成一个只绑定数据/rules/evidence lineage的snapshot reference，并明确标记
`account_snapshot_linked=false`、`funding_values_embedded=false`；它只用于建立trace，不能单独作为Risk或Execution
放行证据。生产接入时必须由Data Plane在决策前生成包含实际funding和账户只读引用的完整snapshot。

数据异常不得由策略自行猜测。缺失完成bar、funding不完整、时间倒退、source hash不闭合时，
本批次不能增加风险。

### 5.3 Research

Research 只读取公开/授权数据和研究环境，输出 artifact，不读取生产交易 Key。

正式试验必须记录：

```text
hypothesis, strategy_contract, primary_metric, failure_condition,
dataset_hash, code_hash, config_hash, trial_number,
holdout_role, result, decision
```

数据角色：

```text
discovery_pool     可反复研究和调参
promotion_pool     冻结候选的一次性审查
forward_live_pool  只追加运行证据，不回写规则
```

Research 可以利用 LLM 提出假设、审阅报告和解析文本，但 labels、weights、PnL、scorecard 和
promotion verdict 必须由确定性代码生成。

### 5.4 Strategy Runtime

每个策略实现同一接口：

```python
class Strategy:
    def decide(self, snapshot: MarketSnapshot, state: StrategyState) -> StrategyIntent:
        ...
```

`StrategyIntent` 至少包含：

```json
{
  "schema_version": 1,
  "strategy_id": "mini_trend_um_base",
  "strategy_version": "0.2.0",
  "decision_id": "...",
  "snapshot_id": "...",
  "decision_time": "...",
  "data_cutoff": "...",
  "target_weights": {"BTCUSDT": 0.18},
  "expected_holding_bars": 1,
  "target_stress_loss_fraction": 0.0,
  "reason_codes": ["MASTER_GATE_ON", "BTC_TREND_ELIGIBLE"],
  "state_hash": "...",
  "evidence_hash": "...",
  "intent_hash": "..."
}
```

`intent_hash`覆盖strategy version、snapshot/decision关联、目标、理由、状态和证据。迁移期旧调用可以继续构造
`schema_version=0`的无trace intent，但这种对象不能生成标准`PortfolioTarget`，也不能进入未来production allowlist。

策略层禁止读取：API Key、真实余额、订单ID、重试状态、maker/taker实现和 arm token。

### 5.5 Portfolio

Portfolio 接收 allowlist 中同一决策时点的 `StrategyIntent[]`，输出唯一 `PortfolioTarget`。

```json
{
  "schema_version": 1,
  "portfolio_target_id": "...",
  "snapshot_id": "...",
  "decision_ids": ["..."],
  "decision_time": "...",
  "proposed_target_weights": {},
  "target_weights": {},
  "sleeve_contributions": {"mini_trend_um_base": {"BTCUSDT": 0.18}},
  "blockers": [],
  "allocatable": true,
  "allocation_hash": "...",
  "target_hash": "..."
}
```

任何blocker出现时，`allocatable=false`且`target_weights`必须全部为零；超限的proposed target仍保留作审计，
不能被误当成批准目标。

职责：

- 为每个sleeve维护 Signal、Standalone Executable、Portfolio Realized 三类NAV；
- 按冻结压力损失预算缩放；
- 在独立sleeve层先检查最小名义价值；
- 合并同标的目标和冲突信号；
- 检查单币、相关簇、保证金和总gross；
- 保存每个sleeve对最终目标的贡献。

小账户规则保持：账户权益低于 `3000 USDT` 时，最多一个连续策略拥有live资格，最多一个事件策略
拥有minimal-live资格；其他策略只能virtual/shadow。

### 5.6 Risk

Risk Engine 是无模型、确定性的最终否决层，输入 `PortfolioTarget + AccountSnapshot + RuntimeHealth`，
输出：

```json
{
  "risk_decision_id": "...",
  "batch_id": "...",
  "portfolio_target_id": "...",
  "approved": false,
  "input_target": {},
  "approved_target": {},
  "adjustments": [],
  "violations": ["ACCOUNT_STATE_UNKNOWN"],
  "risk_state_hash": "...",
  "increase_risk_allowed": false,
  "reduce_risk_allowed": true,
  "decision_hash": "..."
}
```

Risk 分四级：策略、标的、组合、账户。未知状态统一执行：

```text
禁止新开仓/加仓
保留可验证的必要减仓能力
写CRITICAL或HALT事件
进入人工审计
```

减少风险也不能在未知订单状态下盲目重复下单，必须先完成订单和仓位查询。

### 5.7 Execution

Execution 只接受批准后的目标，不做预测。一个批次顺序固定为：

```text
read current state
-> plan reductions
-> pre-trade validate
-> submit reductions
-> reconcile
-> plan increases
-> pre-trade validate again
-> submit increases
-> reconcile orders/fills/positions/stops
```

标准`OrderPlan`只描述计划，不发送订单：

```json
{
  "schema_version": 1,
  "order_plan_id": "...",
  "batch_id": "...",
  "risk_decision_id": "...",
  "portfolio_target_id": "...",
  "snapshot_id": "...",
  "decision_ids": ["..."],
  "current_position_hash": "...",
  "approved_target": {},
  "orders": [],
  "blockers": [],
  "executable": false,
  "plan_hash": "..."
}
```

每个`PlannedOrder`必须保存一个或多个source decision ID，并有唯一client ID和sequence。client ID由batch、
source decisions、标的、阶段和sequence确定性生成；订单显式属于`reduce`、`increase`或`protective`阶段，合同禁止
increase出现在reduce之前。`executable=true`只表示计划合同闭合，不代表live arm、账户状态或交易所发送授权。

订单状态机：

```text
PLANNED -> SUBMITTING -> ACKNOWLEDGED -> PARTIALLY_FILLED -> FILLED
                         |              |
                         +-> REJECTED   +-> CANCELED/EXPIRED

任何响应不确定 -> UNKNOWN -> query by client_order_id -> resolved or HALT
```

网络超时不等于订单失败。`UNKNOWN` 状态下不得创建替代订单，直到按确定性 client ID 查询交易所。

### 5.8 Ledger And Reconciliation

生产账本采用两层：

```text
SQLite WAL
  可查询的交易、成交、资金、仓位、PnL、策略归因和对账状态

append-only JSONL chain
  不可变批次、订单事件、fill、风险事件、人工授权和每日锚点
```

SQLite 是运行账本，不是唯一审计副本；交易所也不是内部账本的替代品。

最小账本表：

| 表 | 内容 |
| --- | --- |
| `batches` | 每次运行、snapshot、版本、状态 |
| `strategy_intents` | 每个策略的目标和理由 |
| `portfolio_targets` | 净额前后目标和sleeve贡献 |
| `risk_decisions` | 调整、违规和批准目标 |
| `orders` | client/exchange ID和状态机 |
| `fills` | 数量、价格、fee、时间 |
| `cash_events` | funding、fee、transfer、adjustment |
| `positions` | 内部仓位和成本 |
| `nav_marks` | 三类NAV和权益峰值 |
| `reconciliations` | 本地/交易所差异和residual |
| `alerts` | 事件、投递和确认状态 |
| `authorizations` | arm、halt、resume、risk change |

每日会计恒等式：

```text
equity_change = trading_pnl + funding - fees + transfers + residual
```

`residual` 超过冻结容差时必须告警并阻止风险增加。

三方对账：

```text
strategy/portfolio target
internal ledger position
exchange actual position/orders
```

#### 5.8.1 回测到实盘偏差归因

每个决策批次生成 `ExecutionAttributionReport`，逐层解释理论路径为什么没有变成相同的实盘路径：

| 层 | 必须记录的差异 |
| --- | --- |
| 数据 | snapshot时点、缺失/修订、bar/funding完整性、价格源差异 |
| 策略 | Signal目标与Standalone目标差异、状态恢复差异 |
| 组合 | sleeve净额、风险预算缩放、单币/相关簇裁剪 |
| 风险 | gross、保证金、回撤、未知状态导致的批准目标变化 |
| 计划 | deadband、min-notional、step/tick rounding、余额约束 |
| 执行 | 决策延迟、spread、slippage、部分成交、拒单、未成交 |
| 持有 | funding、fees、保护单触发、mark与结算价格 |
| 会计 | transfer、手工调整、仍无法解释的residual |

建议保持如下桥接关系：

```text
Signal NAV return
  + standalone execution adjustments
  = Standalone Executable NAV return
  + portfolio netting/risk adjustments
  + realized execution adjustments
  = Portfolio Realized NAV return
  + accounting residual
```

组合净额节省只能进入Portfolio Realized层，不能反向美化Standalone策略结果；无法归入上述类别的差异
必须进入residual和告警，不能塞进“其他收益”。

### 5.9 Operations, Reporting And Intelligence

Operations 负责调度、锁、时钟、健康检查、恢复、告警、read model 和报告，不包含策略逻辑。

可观测性必须拆成五个独立轴，禁止用一个总状态掩盖不同故障域：

| 轴 | 权威输入 | 主要影响域 |
| --- | --- | --- |
| publication integrity | 原子release、read model/hash readback | observation |
| observation state | 每个source自己的观测时间、内容变化时间和TTL | observation、execution |
| operational state | Caddy、publisher、日报、OpenClaw、交易timer/service、HALT、arm、provenance | execution、observation、intelligence、delivery |
| trading authority | registry、owner arm、runtime与staleness硬门 | execution |
| evidence state | 订单预期、fills、账本和三方对账 | execution、observation |

通知库只有一个canonical writer store。publisher只能只读复核它；每个快照分离`observed_at`、`content_updated_at`和
`captured_at`，当前OPEN严重度不能与RESOLVED历史混算。空库是合法的0事件状态，不生成合成INFO。旧通知库只能通过
验证audit chain的幂等replay迁移，且不得伪造历史delivery parity。

Daily Intelligence v2把`pipeline_status`与`evidence_status`分离：官方feed先按主题和时间窗筛选，再对allowlist正文复抓，
保存published/modified/observed时间、body hash、parser/extractor与content quality。研究建议使用带baseline、kill test、
成本、holdout和G0容量状态的结构化合同。LLM和情报平面永远不拥有订单、权重、参数晋级或风险豁免权限。

Intelligence 负责官方源抓取、`InformationEvent`、LLM分析和研究建议。LLM是旁路：

```text
verified source/state/read models -> LLM -> InsightReport/ResearchProposal
```

LLM失败只产生 `agent_unavailable`，不能改变订单、目标权重、arm、halt恢复或风险预算。

## 6. 统一追踪标识

所有对象必须使用稳定标识，形成一条可查询链：

```text
snapshot_id
  -> decision_id per strategy
  -> portfolio_target_id
  -> risk_decision_id
  -> batch_id
  -> order_plan_id
  -> order_id/client_order_id
  -> exchange_order_id
  -> fill_id
  -> ledger_entry_id
  -> reconciliation_id
```

ID 只由确定性输入生成，不含密钥或公网地址。建议核心组成：

```text
UTC decision timestamp + strategy/version + snapshot hash prefix + sequence
```

Dashboard 的每个仓位和订单都必须提供可点击的 trace，不允许只显示“BTC 多仓”而没有来源。

### 6.1 不可变artifact envelope

标准对象跨进程、重启和回放时使用统一JSON envelope：

```json
{
  "artifact_schema_version": 1,
  "artifact_type": "strategy_registry",
  "object_id": "...",
  "payload": {},
  "payload_hash": "...",
  "artifact_hash": "..."
}
```

`payload_hash`覆盖canonical payload，`artifact_hash`覆盖除自身外的完整envelope。解码器必须按artifact type使用显式
字段表和权威构造器，不能用通用dataclass反序列化绕过合同；重建对象的内容、派生hash和确定性ID必须与持久化payload
完全一致。未知schema/type、重复JSON key、缺失/额外字段、非有限数和任一层hash错配全部失败关闭。

本地不可变发布采用同目录`0600`临时文件、flush/fsync、不可覆盖hard-link和发布后逐字节回读；已有目标不能静默替换，
`.tmp/.partial`不能作为完成artifact读取。该边界用于Mac/APFS和VPS/ext4的小型审计对象，不改变
[storage-topology.md](storage-topology.md)中“ExFAT不运行高频状态和SQLite”的约束。hash提供完整性和可重放身份，不是
数字签名，也不代表promotion、owner authorization、live arm或订单发送权限。

### 6.2 完整决策批次与完成标记

一个可回放的pre-trade批次目录固定为：

```text
batches/<batch_id>/
  market_snapshot.json
  strategy_intent.<decision_id>.json
  portfolio_target.json
  risk_decision.json
  order_plan.json
  manifest.json
```

`DecisionBatchManifest`保存每个成员的type、object ID、payload hash、artifact hash和固定文件名，并再次固定
`orders_authorized=false`。批次交叉校验必须证明：所有Intent使用同一snapshot/time/cutoff，Portfolio包含同一组
decision和sleeve，Risk输入等于Portfolio目标，OrderPlan绑定同一batch/target/risk且批准目标等于Risk输出；Risk禁止
increase时不能出现increase订单，reduce/protective/cancel动作由独立的reduce权限控制。

成员先逐个不可覆盖写入，`manifest.json`最后写入并fsync。manifest存在才是`complete`，但它只表示pre-trade审计证据
闭合，不表示订单已提交或成交。进程若在manifest前崩溃，目录状态为`incomplete`；恢复只能在调用方重新提供完整标准
对象后显式进行，逐个验证已有成员、补齐缺失成员并最后写manifest。任何冲突、额外文件、symlink、`0700/0600`权限
偏差或hash错配都停止恢复，不能删除或覆盖冲突证据。

## 7. 标准日线批次

```text
01 acquire single-instance lock
02 check HALT, clock drift, disk, ledger and previous UNKNOWN orders
03 fetch exchange rules, completed bars, funding and private account snapshot
04 validate data completeness and build immutable MarketSnapshot
05 run allowlisted Strategy instances
06 validate StrategyIntent schemas, hashes and decision timestamps
07 build Standalone NAV marks and PortfolioTarget
08 run deterministic Risk Engine
09 persist complete pre-trade batch before any order
10 read exchange positions/orders again
11 plan and execute reductions
12 reconcile reductions and protective orders
13 plan and execute allowed increases
14 query orders/fills and resolve every submitted client ID
15 update ledger, fees, funding, positions and NAV
16 reconcile ledger vs exchange
17 write chain journal and immutable batch manifest
18 build Dashboard read models
19 generate deterministic operations/account report
20 run optional LLM insight agents on bounded read-only inputs
21 publish report and notifications
22 checkpoint and release lock
```

任一步骤失败，默认停止后续风险增加。Dashboard发布或LLM失败不应改变已批准交易结果，但必须进入健康状态。

## 8. 重启与故障模型

### 8.1 启动恢复

每次启动必须先执行：

1. 读取 `HALT`、最新 checkpoint 和最后一个未闭合 batch；
2. 校验 SQLite integrity、JSONL chain 和最新每日锚点；
3. 检查本地与交易所时钟偏差；
4. 查询所有本策略 open/conditional orders；
5. 按 client ID 恢复 `SUBMITTING/UNKNOWN/PARTIALLY_FILLED`；
6. 重建交易所实际仓位和保护单；
7. 与内部账本对账；
8. 只有所有未知状态归零后，才允许进入新批次。

程序重启不得依赖“上次请求应该失败了”或“空仓应该没有订单”这样的推断。

### 8.2 故障动作矩阵

| 故障 | 自动动作 | 恢复条件 |
| --- | --- | --- |
| 未完成bar或funding缺失 | 跳过新决策，保持/必要减仓 | 数据完整并形成新snapshot |
| 账户读取失败 | 禁止增加风险，CRITICAL | 连续成功读取并对账 |
| 发现非白名单仓位或short | HALT，不猜测修复 | 人工确认来源并完成对账 |
| 下单响应超时 | 标记UNKNOWN，按client ID查询 | 明确FILLED/REJECTED/CANCELED |
| 部分成交 | 冻结同标的新计划，对账剩余量 | 状态机闭合 |
| 保护单缺失 | 禁止增加该币风险，尝试一次确定性修复 | 保护单和仓位匹配 |
| ledger residual超限 | HALT风险增加 | residual有凭证解释并写审计 |
| chain hash断裂 | HALT | 从外部锚点恢复或人工审计 |
| 磁盘空间不足 | 停止新批次，CRITICAL | 空间和备份验证通过 |
| Dashboard失败 | 交易链不自动停止，WARNING | read model恢复并补发布 |
| 通知失败 | 本地落盘并重试，不改变交易 | 至少一个关键通道确认 |
| LLM失败/格式错 | 写agent_unavailable | 不要求恢复才能交易 |

## 9. 动态调整与持续进化

“动态”分成三类，权限不同。

### 9.1 可自动运行

- 冻结策略合同内的目标权重变化；
- deadband、止损、冷却和总gross裁剪；
- 冻结公式内的风险预算缩放；
- 订单数量按余额、规则和step size计算；
- 数据延迟、健康状态和通知升级；
- Dashboard实时估值和read model更新。

### 9.2 可自动研究、不可自动上线

- LLM提出新信息源、特征和策略假设；
- 研究系统生成实验合同草稿；
- WSL运行回测、walk-forward、Bootstrap和ML；
- 自动生成scorecard、对比和红队报告；
- 候选满足门后生成“请求promotion review”，但不能改变registry。

### 9.3 必须人工授权

- 策略从research进入shadow/paper/live；
- 修改live参数、universe、市场、方向或成本合同；
- 增加风险预算、资金或杠杆；
- 从HALT恢复；
- 轮换生产Key、改变权限或部署交易代码；
- 接受LLM建议形成新生产版本。

这使系统能够持续优化，但不会在无人知情时自我改写真钱行为。

## 10. LLM 信息、运维和研究层

### 10.1 输入边界

LLM只允许读取：

- allowlist 官方来源经过确定性抓取和hash后的正文；
- 已脱敏的 MarketSnapshot 摘要；
- StrategyIntent reason codes；
- RiskDecision、ExecutionReport、ReconciliationReport；
- deterministic scorecard和历史trial ledger；
- 系统健康和告警read model。

禁止输入生产Key、arm token、完整环境文件、精确生产公网信息和未脱敏错误堆栈。

### 10.2 建议角色

| Agent | 任务 | 输出 |
| --- | --- | --- |
| `MarketBriefAgent` | 汇总已验证公告、宏观、funding/OI/basis状态 | `MarketInsightReport` |
| `OpsAuditAgent` | 解释服务、数据、订单、对账和告警 | `OpsInsightReport` |
| `StrategyReviewAgent` | 比较Base/shadow/benchmark，找偏差和研究问题 | `StrategyInsightReport` |
| `RiskReviewAgent` | 解释risk allow/block和暴露变化 | `RiskInsightReport` |
| `ResearchProposalAgent` | 提出可证伪实验及所需数据 | `ResearchProposal` |
| `DailyBriefAgent` | 合并确定性结果和上述报告 | `DailyBrief` |

所有输出必须引用输入 artifact/source hash。没有证据时必须标记 `insufficient_evidence`。

### 10.3 明确禁止

LLM schema 中不得出现：

```text
target_weights, approved_target, order, leverage,
set_live_enable, override_risk, arm, resume_from_halt
```

LLM可以建议“研究某个止损变化”，但不能直接修改止损；可以解释市场风险，但不能直接减仓。

## 11. 每日报告与通知

### 11.1 报告结构

每日 `DailyBrief` 固定包含：

1. 账户权益、可用余额、gross、保证金和峰值回撤；
2. 当前仓位及每个仓位的策略、decision、reason codes；
3. 当日订单、成交、拒单、部分成交和保护单；
4. PnL拆分：price、funding、fees、slippage、transfers、residual；
5. Base、RiskTier shadow、Funding Veto shadow的三类NAV；
6. 回测/Standalone/Realized偏差归因；
7. 数据完整性、延迟、服务、磁盘、时钟和journal chain；
8. readiness和策略registry变化；
9. 已验证市场信息与LLM摘要；
10. LLM研究建议、反对意见和所需下一实验；
11. 所有未解决WARNING/CRITICAL/HALT及owner待办。

确定性报告先生成，LLM只为其增加解释。LLM不可用时日报仍必须发布。

### 11.2 默认节奏

| 事件 | 默认发布 |
| --- | --- |
| HALT、未知订单、未管理仓位、对账残差 | 立即 |
| 拒单、部分成交、数据缺口、服务失败 | 立即或5分钟聚合 |
| 每次日线批次结果 | 批次结束后立即 |
| 每日综合报告 | 当前日线批次后，默认约 `03:35 UTC / 12:35 JST` |
| 每周研究复盘 | 每周一次，不改变live配置 |

### 11.3 通知通道

第一阶段复用 `QOUNT_NOTIFY_WEBHOOK_URL`，但增加统一 `AlertEvent`、分级、去重键和投递日志。

建议优先级：

```text
HALT/CRITICAL -> Telegram或等价即时通道 + 邮件/第二webhook + Dashboard
WARNING       -> 即时通道 + Dashboard
INFO          -> Dashboard + 每日报告
```

通知失败不得丢事件：先写本地 outbox，再重试投递。交易线程不等待LLM或低级通知完成。

## 12. qount.alyaloale.com Dashboard设计

### 12.1 当前前端保留的资产

- Caddy自动HTTPS、Basic Auth、`no-store`和安全响应头；
- 无CDN的静态SPA，境内访问依赖少；
- 深浅色、移动端导航、权益曲线、表格、告警条和定时刷新；
- VPS本地静态文件发布，展示层与交易代码分离。

### 12.2 必须改变的边界

- 页面不再直接查询Binance并计算权威uPnL/equity；
- 旧 `x4_live/x4_paper/cxd_live` 不再作为当前生产真相；
- 前端不读取生产SQLite，不访问私有交易所API；
- 所有数字来自后端生成、带 `generated_at/data_cutoff/schema_version` 的read model；
- 页面过期时显示STALE，不保留看似实时但来源已失效的数字；
- Dashboard保持纯只读，不增加arm、resume、改单或撤单按钮。

### 12.3 页面信息架构

| 页面 | 核心内容 |
| --- | --- |
| 概览 | 权益、gross、回撤、仓位、当日PnL、系统健康、最新批次、关键告警 |
| 仓位 | 每个仓位的目标/实际/漂移、保护单、策略贡献和完整reason chain |
| 决策追踪 | snapshot -> intents -> portfolio -> risk -> order -> fill时间线 |
| 订单与成交 | 状态机、client/exchange ID、延迟、滑点、费用和UNKNOWN状态 |
| 策略 | registry状态、版本、三类NAV、shadow比较、readiness和promotion证据 |
| 风险 | gross、单币、相关簇、保证金、峰值回撤、HALT和风险裁剪 |
| 账本与对账 | equity bridge、funding、fees、transfers、residual和三方差异 |
| 数据与系统 | 数据时点、缺失、服务、时钟、磁盘、chain、备份和依赖健康 |
| 报告 | deterministic日报、LLM市场/运维/策略分析、周报和研究建议 |
| 告警 | 未解决事件、投递状态、确认人和解决证据 |

### 12.4 Read model

第一阶段继续由Caddy静态服务，publisher原子写入：

```text
data/v1 -> releases/<publication_id>
data/releases/<publication_id>/publication.json
data/releases/<publication_id>/overview.json
data/releases/<publication_id>/positions.json
data/releases/<publication_id>/orders.json
data/releases/<publication_id>/strategies.json
data/releases/<publication_id>/decisions.json
data/releases/<publication_id>/risk.json
data/releases/<publication_id>/readiness.json
data/releases/<publication_id>/system.json
data/releases/<publication_id>/alerts.json
data/releases/<publication_id>/reports.json
```

每个文件都包含：

```json
{
  "schema_version": 1,
  "generated_at": "...",
  "data_cutoff": "...",
  "source_hashes": {},
  "stale_after_seconds": 60,
  "payload": {}
}
```

刷新建议：系统心跳5-10秒、账户/订单15-30秒、公开mark 5-15秒、日线策略状态只在新批次后变化。
即便频率不同，所有口径仍由VPS后端生成。

只有当静态read model无法满足历史筛选和追踪查询时，再增加同源只读API；不能为了“看起来实时”先增加
一个可写Web后端。

## 13. 目标代码结构

这是渐进目标，不要求一次搬完所有文件：

```text
qount/
├── configs/
│   ├── strategies/          # 非密策略合同
│   ├── risk/                # 组合和账户限制
│   └── runtime/             # paper/dry/live非密配置
├── src/qount/
│   ├── contracts/           # 纯schemas、IDs和hash
│   ├── persistence/         # 显式codec、不可变artifact发布/回读
│   ├── governance/          # registry、promotion、authorization
│   ├── data/                # collectors、as-of、quality、snapshot、manifest
│   ├── strategies/          # Base及晋级后的策略适配器
│   ├── portfolio/           # allocator、virtual NAV、attribution
│   ├── risk/                # limits、account guard、kill switch
│   ├── execution/           # planner、state machine、router、recovery
│   │   └── adapters/        # Binance USD-M adapter
│   ├── ledger/              # store、entries、positions、reconciliation
│   ├── operations/          # runner、health、alerts、scheduler
│   ├── reporting/           # read models、daily brief、dashboard publisher
│   ├── intelligence/        # official sources、InformationEvent、LLM roles
│   └── legacy/              # 仅在证据迁移后隔离旧X4/RV兼容入口
├── scripts/
│   ├── research/            # 薄CLI，不放业务逻辑
│   ├── operations/          # reconcile、publish、backup等薄CLI
│   └── compatibility/       # 迁移期旧入口
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── replay/
│   ├── failure/
│   └── golden/
├── deploy/
│   ├── systemd/
│   └── cron/                # legacy only，目标runtime统一systemd
├── web/
│   ├── site/
│   └── schemas/             # read model JSON Schema
└── docs/
```

### 13.1 简洁性约束

- 每个包初期只保留2-4个真正有边界价值的文件，不为每个dataclass建文件；
- 入口只做参数解析、依赖装配、调用和退出码；
- 禁止新增业务逻辑到shell脚本；
- 研究实现按策略或机制归档，不继续全部堆在生产策略包根目录；
- 不先移动文件再理解行为；先建立合同和适配器，再逐个迁移；
- legacy代码在新运行链中默认不可导入，生产allowlist只列新入口。

### 13.2 当前代码迁移映射

| 当前模块 | 目标位置/动作 |
| --- | --- |
| `mini_trend/signals.py` | `strategies/base.py`共享纯函数，保持单一回测/实盘实现 |
| `mini_trend/portfolio_intent.py` | 已迁入`strategies/base.py`；旧路径仅保留兼容导出 |
| `portfolio_governance.py` | 已拆入`contracts/strategy.py`、`governance/*`和`portfolio/*`；旧路径仅保留兼容导出 |
| 标准trace/governance对象 | 已由`persistence/codec.py`显式编解码，`immutable_json.py`不可覆盖发布和回读 |
| 完整pre-trade批次 | `contracts/batch.py`交叉校验，`persistence/batch_store.py`按manifest-last发布/恢复 |
| `mini_trend/pilot_preflight.py` | `risk/account_guard.py` + Binance adapter |
| `mini_trend/pilot_dispatcher.py` | `execution/planner/router/recovery`，先适配不重写 |
| `mini_trend/live_pilot.py` | `governance/contracts`和`risk/limits` |
| `journal.py` | 只作legacy读取；新账本进入`ledger/store.py` |
| `notifier.py` | 扩展为`operations/alerts.py` + outbox + adapters |
| `alpha_agents/official_sources.py` | `intelligence/official_sources.py`复用 |
| `alpha_agents/information_events.py` | `intelligence/events.py`复用 |
| 大量regime/ML脚本 | 移入研究命名空间，不进入production dependency graph |
| `x4/`、`rv/`、C×D | 标记legacy；不删除历史证据，不进入新dispatcher |
| `web/site/app.js` | 保留UI外壳，改为读取v1 read models，删除权威PnL计算 |

## 14. 配置、状态与发布

### 14.1 配置层级

```text
StrategyContract       仓库内、版本化、可hash
RiskLimits             仓库内、版本化、可hash
RuntimeConfig          仓库内非密部分
SecretEnvironment      VPS仓库外0600
OwnerAuthorization     VPS仓库外0600、绑定readiness hash
EmergencyHALT          VPS本地显式文件
```

优先级必须固定且写入报告。环境变量不得静默覆盖策略合同；如果允许覆盖，必须进入 `config_hash` 和
Dashboard配置视图。

### 14.2 VPS状态

```text
/root/qount/state/production/
  runtime.sqlite
  journal/events.jsonl
  journal/daily_anchors.jsonl
  checkpoints/latest.json
  snapshots/<date>/<snapshot_id>.json
  batches/<batch_id>/manifest.json
  reports/daily/<date>.json
  read_models/v1/...
  alerts/outbox.jsonl
  backups/manifest.json
```

SQLite、锁和活跃journal只在VPS ext4。外置ExFAT只保存完成且校验过的压缩备份和manifest。

### 14.3 发布

生产发布必须绑定：

```text
git_commit
dirty=false
code_tree_hash
dependency_lock_hash
config_hash
promotion_artifact_hash
deployed_at
deployed_by
rollback_target
```

当前dirty worktree不能直接成为目标production release。应先形成干净提交或不可变source bundle，再通过
部署manifest发布。

## 15. 测试策略

### 15.1 必须覆盖的failure tests

- 同一completed bar重复运行不产生第二个batch或订单；
- 请求超时但交易所已接受订单时，不重发；
- 部分成交后重启能够恢复；
- 交易所返回未知仓位时阻止增加风险；
- 条件保护单缺失或数量不匹配；
- bar/funding不完整和时间倒退；
- snapshot/decision/config hash不匹配；
- SQLite事务失败和JSONL chain断裂；
- funding、fee、transfer遗漏导致residual超限；
- Dashboard read model过期；
- webhook失败进入outbox并可重试；
- LLM超时、非JSON、越权字段和伪来源全部降级；
- manual arm与readiness hash不一致；
- legacy策略或非allowlist策略尝试进入dispatcher。

### 15.2 Golden replay

至少保存以下不可变fixture：

```text
无信号全现金日
正常开仓日
deadband不调仓日
止损和冷却日
减仓后加仓批次
部分成交和恢复
账户未知HALT
10%回撤flatten-then-halt
```

同一fixture必须让research、paper、dry和live planner产生相同的信号、目标和风险结论；只有执行结果来源不同。

## 16. 安全与备份

- 研究Key和生产Key分离；
- 生产Key读取/Futures/IP限制开启，提现关闭；
- LLM、Dashboard、研究工作站不能读取生产Key；
- Caddy继续使用HTTPS、认证、`no-store`和安全响应头；
- Dashboard JSON禁止账户标识、凭据、精确公网信息和原始错误秘文；
- 每日备份SQLite一致性快照、journal、anchors、reports和deployment manifest；
- 备份离开VPS前加密，并在外置盘做readback hash；
- 定期执行恢复演练，不把“有备份文件”等同于“可以恢复”；
- Key轮换、arm、halt和resume都写authorizations和chain journal。

## 17. 分阶段迁移路线

### Phase A：统一合同和可观测性

目标：不改变Base行为，先让所有对象有统一ID和trace。

状态：**本地范围已完成，尚未接入VPS运行链**。2026-07-19已完成第一批行为不变迁移：

- `contracts/strategy.py`成为`StrategyIntent`唯一权威定义，`contracts/hashing.py`提供稳定审计哈希；
- `portfolio/models.py`承载三类NAV和sleeve压力风险预算，`portfolio/allocator.py`承载fail-closed聚合；
- `governance/eligibility.py`、`event_capacity.py`、`research.py`分别承载运行资格、事件容量和研究证据规则；
- Base projection适配器已迁入`strategies/base.py`；
- `portfolio_governance.py`和`mini_trend/portfolio_intent.py`只作兼容导出，不再保存业务实现；
- 架构测试固定旧新对象同一性、核心域禁止交易所/runtime依赖和allocator迁移前黄金哈希。

第二批已完成本地标准trace合同，但尚未接入VPS运行链：

- `contracts/trace.py`提供无密钥、确定性的64位SHA-256 trace ID；
- `contracts/runtime.py`实现`MarketSnapshot`、`PortfolioTarget`、`RiskDecision`、`PlannedOrder/OrderPlan`；
- traced `StrategyIntent`增加schema/version/snapshot/decision/reason codes和防篡改`intent_hash`，旧schema 0兼容；
- Base projection adapter生成可验证snapshot reference和标准intent，沿用既有projection decision ID；
- allocator结果可以转换为绑定同一snapshot和全部decision ID的`PortfolioTarget`；
- 合同断言覆盖hash篡改、blocker非零目标、风险违规仍加仓、重复订单ID和先加后减等失败路径。

第三批已完成现有dry dispatcher到标准Risk/Execution合同的本地适配，仍未接入VPS运行链：

- `risk/validation.py`精确复算legacy dispatcher的14字段`plan_hash`，只接受dry artifact，并绑定
  projection decision ID、标准`PortfolioTarget`及原始目标权重；
- `risk/legacy_dispatch.py`把legacy risk结果转换为确定性`RiskDecision`；hash、trace、diagnostic blocker或目标异常
  一律归零批准目标并禁止增加风险，drawdown flatten保持“可减仓、不可加仓”；
- `contracts/runtime.py`新增`PlannedCancellation`，撤单与订单共享source decision IDs和全局sequence；
- `execution/legacy_dispatch.py`按reduce market -> increase market -> protective cancel -> protective submit生成
  `OrderPlan`，保留retained stop、expected position和reconciliation tolerance，但不导入交易所、配置、文件系统或环境；
- `execution/parity.py`忽略迁移期新旧client ID差异，对数量、方向、订单类型、止损价、撤单、保留单和对账字段做
  黄金一致性比较，当前三笔market与三笔protective stop无经济行为差异。

第四批已完成本地Governance registry与deployment manifest合同，仍未发布artifact或接入VPS：

- `StrategyRegistration`不可变绑定strategy ID/version/kind、contract/code/config hash、promotion状态、
  promotion artifact、owner authorization和gross/stress风险上限；
- `StrategyRegistry`每个逻辑策略只保留一个当前版本，旧snapshot由registry hash保留；同版本状态推进不能改代码、配置
  或合同，新版本必须重新进入research；
- 状态只允许逐级推进或进入halted；risk budget增加必须有owner authorization，halt恢复必须有reconciliation evidence，
  且恢复级别不能高于halt前状态；
- `validate_registered_intents()`在Portfolio之前检查traced intent的strategy/version、环境资格及冻结gross/stress预算，
  legacy schema 0、未注册或超预算intent不能进入新allowlist；
- `DeploymentManifest`绑定git commit、dirty flag、code tree/dependency/config hash、registry、策略条目、promotion/owner
  bundles和rollback target；production拒绝dirty bundle、未到minimal-live的策略或缺失rollback；
- manifest固定`orders_authorized=false`，证明“可发布什么”不等于manual arm或“现在可以发单”；Base registration adapter
  绑定现有`LIVE_PILOT_CONTRACT.contract_hash`，但不判断Base当前已获得哪个promotion状态。

第五批已完成本地标准artifact持久化边界，仍未接入VPS运行链：

- `persistence/codec.py`显式支持`MarketSnapshot`、traced `StrategyIntent`、`PortfolioTarget`、`RiskDecision`、
  `OrderPlan`、`StrategyRegistration`、`StrategyRegistry`和`DeploymentManifest`，不接受legacy schema 0 intent；
- envelope固定artifact schema/type/object ID、payload hash和artifact hash；读取时按权威构造器重建，并逐字节比较重建
  payload，防止持久化ID/hash绕过对象不变量；
- `persistence/immutable_json.py`使用同目录`0600`临时文件、fsync、不可覆盖hard-link和发布后回读；已有文件、临时/部分
  路径、未知类型、重复key、字段漂移或任一hash篡改均失败关闭；
- registry与shadow manifest可分别落盘、读回并重新执行`validate_against_registry()`；manifest仍固定
  `orders_authorized=false`，本批只在临时测试目录生成shadow fixture，没有生成真实production manifest。

第六批已完成本地完整pre-trade决策批次，仍未接入VPS运行链：

- `contracts/batch.py`新增`ArtifactReference`、`DecisionBatchManifest`和完整lineage校验，绑定snapshot、多策略intent、
  portfolio target、risk decision和order plan；manifest作为第九类标准artifact持久化，仍固定
  `orders_authorized=false`；
- 交叉断言覆盖同一snapshot/time/cutoff/decision/sleeve、Portfolio到Risk目标、Risk到Plan批准目标、batch ID以及
  increase/reduce动作权限，单对象自身合法但跨对象错链的批次也会失败；
- `persistence/batch_store.py`按`0700`目录、`0600`文件、固定文件名和manifest-last完成标记发布；缺失、多余、替换、
  篡改、symlink或权限异常均不能读成complete；
- manifest前中断可显式resume：已有成员逐个验证、只补缺失项且不覆盖冲突，最后才写manifest。该恢复只恢复审计批次，
  不查询交易所、不发送订单，也不恢复live arm；测试只使用临时目录fixture。

第七批已完成Dashboard v1本地权威read model边界：

- `reporting/read_models.py`以`VerifiedDecisionBatch`和治理`StrategyRegistry`为必选source，生成
  `overview/strategies/readiness`；后续Phase B只读桥增加可选冻结ledger snapshot，Phase C再增加独立notification source的
  `alerts`和确定性DailyBrief source的`reports`；
- 生成前重放batch lineage、manifest artifact references、registry hash、策略版本、运行资格和风险预算校验；
- publisher没有Phase B ledger快照时，实际仓位、equity和PnL必须显示`unavailable_until_phase_b_ledger`，前端不能估算；
- freshness绑定batch/registry source时间；有ledger快照时再纳入audit尾事件时间，旧source重新抓取/发布不能洗新；过期模型
  显示STALE并阻断readiness；
- 发布使用不可变`releases/<publication_id>/`目录和`v1`相对symlink原子切换，半写失败保留旧指针；读回检查权限、
  精确文件集合、canonical JSON、symlink目标、source/model/publication hash；
- `web/schemas/`当前固定13份Draft 2020-12 schema，`web/site`只读取publication及十份v1模型；原子release精确包含
  `publication/overview/positions/orders/strategies/decisions/risk/readiness/system/alerts/reports`11个JSON，已删除交易所ticker请求和浏览器
  uPnL/equity重算。

Phase B后续本地批次已补上只读Dashboard桥，仍未进入生产：

- `ledger/read_model.py`在补刷/验证outbox与chain JSONL后，用单个SQLite读事务冻结最新batch、positions、recoverable
  orders、NAV和同批最新三方对账；对账必须是最后一次状态事件，缺失、错链、过期或篡改均拒绝发布；
- snapshot v3冻结`position_details/orders/order_events/fills/cash_events/recoveries`、完整NAV历史和同批最新账户观测，交叉核对当前batch plan hash，并验证
  状态顺序、累计成交、fill/order关联、现金事件、仓位hash及恢复报告，不能从计划订单推断执行事实；
- `reporting/read_models.py`可选接收已自验证的`RuntimeLedgerSnapshot`。有快照时七份核心模型增加`runtime_ledger` source hash，
  显示权威账户、仓位、equity bridge、portfolio-scope NAV和recovery/reconciliation gate，并提供`positions/orders/decisions/risk/system`模型；
  无快照仍明确不可用；
- freshness取audit链最后一次source update，而不是capture/publish时刻；`UNKNOWN`不会隐藏，而是显示并阻断readiness；
- `read_model_ready`只代表监控读模型闭合，`live_orders_allowed`恒为false，不构成部署、promotion、arm或订单授权；
- golden replay固定snapshot/model/publication hashes。本地实现没有接legacy dispatcher、交易所adapter或VPS publisher。

至此Phase A定义的本地合同、trace、registry、不可变artifact、完整batch和Dashboard v1 read model已闭合。Phase B已用
隔离的legacy dry fixture开始迁移回放证据，但生产迁移仍未开始；VPS真实计划、发送、恢复和对账行为仍完全由legacy
`mini_trend/pilot_dispatcher.py`拥有。当前迁移没有访问或改变VPS运行链，也没有生成或部署生产read model。

交付：

- `MarketSnapshot/StrategyIntent/PortfolioTarget/RiskDecision/OrderPlan` schema；
- Base projection适配到统一合同；
- deployment manifest和strategy registry；
- Dashboard v1 overview/positions/orders/strategies/decisions/risk/readiness/system/alerts/reports read models；
- 旧CTA-R展示插件和legacy JSON前端推送已删除，仓库只保留Dashboard v1前端。

验收：任一目标仓位都能追溯到snapshot和reason codes。

### Phase B：统一账本、订单状态和恢复

目标：达到Level 3最关键的执行基础。

状态：**本地账本、legacy dry迁移回放、完整runtime snapshot和只读Dashboard adapter已实现；MiniTrend dispatcher已接入
标准batch、RuntimeLedger和authority发布链，尚未以真钱订单验证交易所行为**。
当前实现包括：

- `ledger/legacy_replay.py`把相互hash链接的Base projection与legacy dry plan转换为完整标准batch，并只向隔离ledger登记
  `PLANNED` orders；完整decision/contract/plan hash与经济动作parity在写入前验证。冻结report保存双方action hash、trace、
  expected positions/tolerance和audit tail，同时固定`orders_authorized=false`及`planned_only_not_executed`；
- migration replay只允许空账本或同一batch精确幂等重启。已有order transition、fill、cash、position、NAV、reconciliation
  或recovery记录一律拒绝，不能把执行历史重新包装成dry迁移证据；
- `ledger/store.py`在私有runtime目录使用SQLite WAL、foreign keys、FULL synchronous和busy timeout；完整
  `VerifiedDecisionBatch`与planned orders同事务登记，immutable identity只允许exact idempotent replay；
- 业务行与`audit_outbox`同一SQLite事务提交，之后持锁刷canonical chain JSONL。启动按sequence/event/row hash补刷，
  覆盖DB先提交和JSONL先追加两种崩溃窗口，不依赖跨文件伪原子事务；
- 状态机要求发送前先落`SUBMITTING`，成交量累计不倒退、不超计划，exchange order ID不可更换；不确定结果进入
  `UNKNOWN`，只读resolver只能按确定性client ID查询，not-found/异常保持UNKNOWN并要求HALT，不创建替代订单；
- fills更新long-only平均成本position，fee/funding/transfer入账；NAV从已登记事件计算equity bridge和residual，已封账
  时间段拒绝晚到事件静默改写；
- 三方reconciliation持久化前必须匹配batch冻结target/tolerance、当前ledger positions/open orders和最新NAV residual；
  unmanaged/missing order、ledger/exchange仓位差异或residual超限要求HALT。
- live提交前先把标准订单写为`SUBMITTING`；market成交只接受`fetch_order`与逐笔
  `fetch_order_trades/fetch_my_trades`共同确认的trade ID、数量、价格和USDT fee。create-order简略回包、查询超时、
  fee缺失或聚合fill一律转`UNKNOWN + HALT`，不重发也不继续后续订单；保护单明确ACK后记`ACKNOWLEDGED`。
- 成功后把position、account、短窗口cash ledger、NAV与post-dispatch reconciliation写回同一SQLite；失败也写HALT
  reconciliation并原子刷新authority，使Dashboard显示unresolved订单和halted registry，而不是保留旧的pre-dispatch健康画面。
- `ledger/read_model.py`只在SQLite/outbox/audit链、最新NAV和同批最新reconciliation共同闭合时生成冻结快照；Dashboard只消费
  该快照，不直接查询SQLite，也不从market snapshot/目标权重重建仓位或PnL。schema v3已包含仓位明细、完整订单/事件、fills、
  cash events、recoveries、完整NAV历史及账户观测，并继续绑定同一读事务、当前batch plan hash与audit tail。

本地故障矩阵覆盖legacy dry完整batch/golden replay、幂等重启、执行状态隔离、非法状态转换、
`SUBMITTING -> UNKNOWN -> FILLED`、resolver无结果/异常、部分成交重启、两个outbox中断窗口、JSONL篡改、会计恒等式、
residual和三方差异。它证明本地迁移/存储/恢复合同，不证明真实交易所行为、生产部署或live authority；接入legacy运行链前
仍需要生产artifact importer、部署审查和显式owner授权。

交付：

- SQLite WAL账本和JSONL审计双写；
- order state machine和UNKNOWN恢复；
- fills、fees、funding、transfer账本；
- 三方reconciliation和equity residual；
- failure replay和恢复演练。

验收：重启、超时、部分成交和账本差异均有确定性结果，不会重复下单。

### Phase C：通知、Dashboard和日报

目标：系统可看、可告警、可解释。

状态：**本地通知告警、只读producer adapters、显式incident生命周期、确定性DailyBrief、DailyIntelligence、十一页Dashboard和
production-shaped publisher已实现；静态前端与publisher scheduler已在VPS读取真实order-free authority运行，authority writer保持
手工oneshot；腾讯官方个人微信iLink、免费官方feed、完整六角色中文LLM、不可覆盖归档、Dashboard和每日timer已形成真实E2E证据**。

当前实现包括：

- `notifications/contracts.py`冻结`AlertEvent`，固定`INFO/WARNING/CRITICAL/HALT`分级、稳定identity、完整内容hash、source
  trace和dedupe key；exact replay幂等，同identity不同内容失败关闭；
- `notifications/store.py`在私有目录使用SQLite WAL、foreign keys和FULL synchronous，把alert状态、delivery job、attempt和
  canonical hash audit chain持久化；投递固定idempotency key，支持指数退避、dead-letter以及外部成功后DB marker中断恢复；
- transport继续由`NotificationStore`注入；`OpenClawWeixinProvider`固定腾讯官方iLink host/path/header，复用现有OpenClaw账号和
  recipient，以delivery key派生稳定client ID。仓库外`0600`凭据只保存稳定的account/base URL/recipient/token，最新context token在每次发送前
  从OpenClaw accounts目录按recipient读取；目录/文件owner、mode、symlink、大小和JSON映射不满足合同时失败关闭，静态token只作手工/测试回退；生产真实接入通知为
  `DELIVERED/SUCCEEDED`且audit chain重放通过。`WeComGroupRobotProvider`保留为未启用兼容实现；外部接受后、本地成功marker前崩溃
  仍可能重复；
- `NotificationSnapshot`验证业务row hash和audit chain后，成为第四份`alerts` read model；notification source/freshness与
  batch/registry/ledger独立，新告警不能把旧账户数据洗新；
- `notifications/producers.py`只接受完整`VerifiedDecisionBatch`、冻结`RuntimeLedgerSnapshot`或显式
  `SystemHealthObservation`，把data/risk/plan blocker、recoverable orders、reconciliation/NAV异常和system health状态映射为
  固定severity的`AlertEvent`。它不读取DB、交易所、网络、env或当前时钟；健康source返回空事件；
- runtime order incident绑定ledger `audit_last_hash`，同一source晚抓不会制造重复告警。producer输出已穿过store/snapshot/
  alerts/DailyBrief/reports端到端测试；`ProducerIncidentSync`先幂等enqueue当前事件，再按source/category显式resolve已被健康新观测
  supersede的旧OPEN incident，sync ID/hash可确定性复核。生命周期仍未接scheduler；
- `#/alerts`显示severity、OPEN/RESOLVED、source/trace、delivery状态、attempt、next retry和dead-letter。桌面`1440x1000`
  与移动`390x844`已用Chromium检查，无裁切或重叠；QA数据仍只来自测试fixture；
- `reporting/daily_brief.py`只从完整batch、registry、冻结ledger和notification snapshots生成确定性日报；source hashes、
  equity/NAV PnL bridge、actual/expected positions、decision/reason codes、planned/recoverable orders、对账、投递、告警、gates和
  owner actions均可重建验证，LLM固定不调用且日报永不授权订单；
- DailyBrief订单段从snapshot v3读取order status、fills、quantity/notional/fees、protective runtime和最近recovery；其中
  order latency/slippage仍显式unavailable。账户balance、actual gross、margin和peak/current drawdown直接来自账户/NAV账本事实，
  不以目标仓位、市场价或浏览器计算补齐；
- `intelligence/`构成独立只读情报平面：生产默认从Binance公告API、Fed RSS和SEC RSS免费发现URL，官方allowlist重新抓取并保存原文；
  Binance `24hr/premiumIndex`和feed响应均保存原始HTTP字节SHA-256。冻结RuntimeLedger v3摘要依次交给
  market/event/execution/strategy/red-team/editor六角色，
  生成不可覆盖`DailyIntelligenceReport`。报告固定禁止订单和live修改，只能形成解释、批评和可证伪研究建议；
- `positions/decisions`提供可点击的仓位到批次证据链；`orders/risk/system`分别展示订单与成交、RiskDecision/runtime gate/三方差异和
  ledger/audit/recovery及`clock/disk/service/backup`健康状态；`reports/intelligence`分别使用独立DailyBrief/DailyIntelligence
  source/freshness。原子release为12个JSON，静态schema为16份；情报页已用Chromium完成桌面`1440x1000`和移动`390x844`
  首屏、完整长页及文档宽度检查，六角色与来源证据完整，无可见元素越界、重叠或裁切；
- 旧CTA-R SwiftBar/Übersicht展示源、缓存和`cta.json`推送链已删除，本机`com.qount.dashboard`已卸载；独立
  `com.qount.ctar-daily`研究采集任务保留。
- `operations/authority_writer.py`已把VPS order-free MiniTrend run作为唯一输入适配到上述六类标准source：它要求保留
  dispatcher初始`dispatch_readiness.json`和最终`live_readiness.json`，重放projection/dry plan hash与legacy parity，拒绝非flat账户、
  open orders、缺失source或任意order-capable flag；成功路径只记录`PLANNED` orders、只读账户/NAV/reconciliation和research registry，
  然后以staging目录导入校验后的bundle。它不读取exchange、私有API、legacy state数据库，不发送通知，也不设置live authority。

交付：

- AlertEvent、outbox、重试、分级和投递审计；
- Dashboard仓位、trace、订单、风险、账本、系统、报告页面；
- deterministic DailyBrief；
- Market/Event/Execution/Strategy/Red-team/Editor LLM报告旁路；
- stale、agent_unavailable和未解决事件显示。

验收：不登录VPS也能从受保护Dashboard和通知判断账户、策略、系统和待办。

真实transport评审结论：不得复用legacy `Notifier`或shell ServerChan发送；个人微信adapter已由`NotificationStore`注入并具备稳定
client ID、provider响应验证、限流/超时、0600凭据、中文最小payload、channel隔离和无密钥审计。完整生产E2E已验证3份feed、8份详情、
2份行情、六角色中文Responses、账本摘要、不可覆盖归档、Dashboard read model和日报微信`DELIVERED/SUCCEEDED`；每日systemd timer现为
`enabled/active`。会话单一真相已收口到OpenClaw accounts目录，日报unit依赖gateway并只读挂载该目录；删除Qount静态context token后的
真实验证仍为`DELIVERED/SUCCEEDED`，20行NotificationStore audit chain可重放。外层`incomplete/needs_research`必须按证据状态展示，
不能为了表面健康改写成`clear`。

production publisher评审结论：本地已具备只读VPS artifact importer、四项OS/systemd/backup探针、非阻塞systemd形单写者、同盘
原子发布、当前+4个release保留、逐文件备份、latest+60个backup保留和临时恢复演练；`qount-dashboard-publisher.timer`已在
authority完整且路径审计`enable_authorized=true`后受控启用。publisher只能读取完整batch/registry/ledger/notification/health/brief，
不得直接查询交易所、读取legacy state JSON或复制测试release；每轮只刷新OS健康、release和备份，不改变authority source time。
authority writer另有`static/inactive` oneshot unit并与publisher共享lock；live cycle会在授权环境内刷新flat/仓位/挂单和
order-free authority。publisher保留source time，authority在每次周期后按15分钟规则自然变stale，不能通过提高阈值或复制旧数据洗新。

### Phase D：Base最小实盘审查

目标：以固定`100 USDT` canary完成Base最小实盘审查，不等待日历观察指标自然累积。

状态：**Phase B/C/D工程链已部署，Base 100 USDT minimal-live已启用**。Owner在2026-07-21/22明确授权跳过约两个月等待，
`60 forward pairs / 10 active bars / 30 paper days / 7 dry decision days`降为非阻断观察指标。它们继续出现在
readiness与Dashboard中，用于解释样本成熟度，并纳入readiness hash防篡改，但不再决定`ready_for_manual_final_arm`。
当前recurring run `/root/qount/state/mini_trend/forward/runs/20260722T061346Z`为`ready_for_manual_final_arm`、blocker 0，
registry为`minimal_live`，live timer为`enabled/active`。首次live因目标权重全零而没有订单，但journal与post-dispatch
reconciliation均完成；recurring重复decision已验证为order-free refresh后幂等no-op。

前置：

- 本金严格等于`100 USDT`，long/cash、TOP3、isolated 1x、gross<=1；
- `1000 USDT`字段只兼容历史research/paper和order-free证据，不能进入live arm、dispatcher或live journal；
- 60/10 forward、30天paper、7天dry作为观察项，不是订单授权门；
- funding journal完整；
- 0 unmanaged/UNKNOWN/unreconciled position；
- rollback和恢复演练通过；
- 当前account/preflight、标准authority batch、RuntimeLedger snapshot和pre-dispatch reconciliation全部匹配；
- owner已为具体readiness hash签发manual arm；arm artifact同时成为`minimal_live` promotion evidence和owner authorization，
  live switch、confirmation和token仍须同时匹配。后续只有arm失效、release/config变化、HALT恢复或风险增加才需要新的owner授权；
  不得因为首个非零信号出现而临时改变合同。

操作边界：当前arm只授权冻结的Base/100 USDT/30天窗口，不授权扩容或其它sleeve。不得恢复旧X4/CxD cron或forward timer；
任意code/config/release变化必须重新order-free readiness并轮换arm。任意UNKNOWN、对账失败或HALT会停止风险增加并发布
`halted`；恢复必须重新审计和owner authorization。

验收：一个月试点期间每个订单、仓位、PnL和异常都可解释。盈利是观察结果，不是放宽工程门的理由。

### Phase E：多策略组合

目标：立即在本地把零/单/多sleeve接入统一Portfolio并形成virtual证据；Base生产路径保持独立。

顺序：

```text
virtual NAV -> shadow execution -> paper -> event minimal-live -> risk scaling
```

本地allocator没有双sleeve入口门：零sleeve fixture验证空状态，单sleeve验证passthrough，固定两sleeve integration artifact已验证
净额、风险、reduce-before-increase、rounding/min-notional、虚拟成交/费用/funding、账本、三NAV、对账、重放和篡改检测。
每个真实候选的Standalone Executable NAV成熟度影响结论强度和production资格，不阻止virtual架构运行。
CxD和CTA-R现已授权historical/discovery/virtual研究；二者都不因此获得Binance钱包订单权限。

### Phase F：持续研究与规模化

目标：建立“建议、试验、淘汰、晋级”的长期循环。

```text
verified information
-> LLM/research hypothesis
-> frozen experiment
-> deterministic artifact
-> promotion review
-> shadow/paper evidence
-> owner authorization
-> bounded live risk
```

规模化只增加已证明sleeve的风险预算，不自动增加杠杆、short、carry或交易频率。

## 18. 明确暂不建设

当前账户、频率和团队规模不需要：

- Kafka、Kubernetes、服务网格和几十个微服务；
- 高频事件总线和纳秒延迟监控；
- 在线GPU推理和强化学习下单；
- 复杂协方差优化器；
- 多交易所智能路由；
- Dashboard写交易、arm或配置功能；
- LLM自动改策略、晋级或分配真钱；
- 为目录整洁一次性重写已验证的MiniTrend执行代码。

先把单策略的账本、恢复、对账、通知和解释做到可靠，再增加组合复杂度。

## 19. 完成标准

第一阶段“完善的个人量化系统”不是策略数量多，而是以下条件同时成立：

```text
研究可以失败，但不会污染生产
策略可以亏损，但每一项损益可以解释
进程可以崩溃，但不会重复下单
交易所可以超时，但UNKNOWN状态会被恢复或HALT
数据可以缺失，但不会进入未来信息或伪造收益
多个策略可以冲突，但风险和收益不会重复计算
Dashboard可以实时显示，但不会创造第二套账户口径
LLM可以提供洞察，但不能直接改变真钱行为
新策略可以晋级，但必须有独立证据和人工授权
```

qount 的近期主线因此固定为：

```text
统一合同、trace、账本、恢复和read models作为共享底座
├─ Base minimal-live持续观测
├─ execution certification与shadow accounting持续观测
├─ R0/R1/... discovery和数据工程
└─ 零/单/多sleeve virtual allocator集成

任何paper/live/真实账户mutation再单独进入授权、arm、对账和回滚路径
```
