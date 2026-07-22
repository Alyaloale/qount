# qount 交易系统架构优化与扩展计划

版本：`v0.3`

更新时间：`2026-07-23`

状态：owner要求形成的架构演进合同；只授权设计、拆解和离线验证，不授权真实认证订单、策略晋级、资金扩容、
carry、short、杠杆提升或恢复legacy交易入口。

## 0. 文档定位

本文定义从当前单策略`100 USDT` minimal-live系统，演进到可独立认证执行、独立复核会计、分层停机和可安全承载
未来多sleeve的生产架构。当前生产事实仍以[current.md](current.md)和VPS只读证据为准，基础目标架构仍以
[system-architecture-design.md](system-architecture-design.md)为准。

本文不改变以下当前事实：

- 唯一有真钱权限的策略是`MiniTrend-UM-Base-v0.2`；
- Base固定`100 USDT`、TOP3日线、long/cash、one-way、isolated 1x、effective gross `<=1`；
- X4、C×D、RV-C和旧line A交易入口关闭；
- RiskTier和FundingVeto只能shadow；
- 真实fill/fee/slippage/STOP/UNKNOWN恢复样本仍为0，不得为制造样本强制Base下单；
- VPS是生产真相，Mac是源码真相，WSL是研究计算节点，外置盘是大型数据和最终artifact真相。

## 1. 对外部建议的事实校正

| 建议 | 处理 | 当前解释 |
| --- | --- | --- |
| 生产控制面已经较成熟 | 接受 | provenance、arm、registry、readiness、确定性client ID、SQLite/JSONL、三方对账和fail-closed均已落地 |
| 当前瓶颈主要是收益源和真实执行证据 | 接受 | 工程成熟度高于实盘收益证据；当前仍是单一趋势风险暴露 |
| 纯加密横截面受有效广度约束 | 接受为研究先验 | TOP3/LiquidTrend历史读数不能当三个独立alpha；扩币前必须重新证明有效广度、容量和残差 |
| C×D趋势+carry、CTA-R跨资产是最高价值候选 | 接受为候选排序 | 历史组合读数和CTA-R ETF结果属于consumed/guarded evidence；需要当前版本、独立NAV、执行合同和新时间证据，不直接获得live资格 |
| 建独立execution certification lane | 接受但隔离 | 默认先本地网关/故障注入和testnet；任何真实最小单仍需新的明确owner授权 |
| 建独立shadow accountant | 接受 | 必须避免与dispatcher/主账本共享同一仓位聚合实现 |
| 将HALT拆成Operational/Strategy/Portfolio | 接受，渐进迁移 | 当前全局`HALT`仍保留；分层事件先旁路观测，验证后才改变处置 |
| 把交易所规格漂移纳入release proof | 接受 | Git/source hash之外增加`VenueCapabilitySnapshot`和兼容性判定 |
| 已有CTA-R、X4、RV-C三个可直接组合的认证edge | 拒绝为当前事实 | 它们是legacy、guarded blueprint或consumed-history证据，不继承promotion/live资格 |
| X4 live正在补真实执行样本 | 拒绝为当前事实 | X4/C×D当前关闭，不能作为Base readiness的实盘样本来源 |
| 立即恢复carry或期权VRP | 不进入本计划 | 当前owner约束为no-carry；研究和生产都不能由本计划自动解锁 |
| maker/post-only、TWAP/VWAP | 接受为执行研究 | maker必须建模成交概率、撤改单和逆向选择；TWAP/VWAP只在容量/名义门通过后研究，不为100 USDT canary增加复杂度 |

## 2. 目标架构增量

```text
                         Governance / Owner Authorization
                                      |
             +------------------------+-------------------------+
             |                        |                         |
             v                        v                         v
     Strategy Production      Venue Certification       Research/Intelligence
       Base minimal-live        separate registry          no trading auth
             |                        |
             v                        v
     Portfolio/Risk Target      CertificationPlan
             |                        |
             +-----------+------------+
                         v
                 Venue Adapter / Gateway
                         |
                         v
                    Binance USD-M
                         |
             +-----------+------------+
             |                        |
             v                        v
      Primary Runtime Ledger   Independent Shadow Accountant
             |                        |
             +-----------+------------+
                         v
                 Reconciliation Diff
                         |
                         v
       Operational / Strategy / Portfolio HALT Router
                         |
                         v
              Alerts / Dashboard / Daily Brief
```

关键隔离：

- `StrategyProduction`的收益和NAV不得包含认证测试；
- `VenueCertification`不得产生StrategyIntent，也不得进入策略PnL；
- `ShadowAccountant`只读交易所归档和主账本快照，不参与下单；
- `HALTRouter`不能让局部策略事件绕过账户级资本边界；
- Intelligence只能形成影响评估或研究提案，不能改venue能力矩阵、arm或订单权限。
- 历史组合的高Sharpe、低相关或跨资产广度只能进入`candidate_revalidation`，不能绕过当前registry、holdout、venue和owner门。

## 3. Workstream A：Execution Certification Lane

### 3.1 权限域

新增独立治理对象，不复用策略registry状态：

```text
certification_status = draft | local_sim | testnet | real_pending_owner | real_authorized | completed | halted
batch_type           = venue_certification
pnl_attribution      = operational_certification_cost
strategy_id          = null
portfolio_nav        = excluded
```

真实认证的放行条件必须同时包含：

- 指定测试编号、标的、动作、最大名义、最大费用和最长持仓时间的owner authorization；
- 独立、单次、带失效时间的`0600` certification arm，不得复用Base arm/token；
- 认证前账户、仓位、普通单、条件单和position mode只读快照；
- 明确的回到零仓位计划和失败时人工处置路径；
- 当前venue capability snapshot通过；
- 认证artifact、主账本和shadow accountant均准备好接收事件。

没有上述授权时，所有认证工具必须固定`orders_authorized=false`。

### 3.2 两类认证

本地网关/testnet负责故障和恢复语义：

- ACK丢失、响应体丢弃、REST超时、查询延迟；
- WebSocket乱序、重复、断流和重连；
- `SUBMITTING`、`ACKNOWLEDGED`、`PARTIALLY_FILLED`时崩溃；
- duplicate decision/client ID、部分成交、STOP创建失败；
- 进程重启后按client ID恢复，UNKNOWN期间禁止替代订单；
- REST全量快照覆盖WebSocket gap后的状态恢复。

真实最小规模认证只验证testnet不能证明的场所事实：

- 实际market或owner指定订单类型的ACK/fill；
- quantity/price rounding、minQty/minNotional和precision；
- maker/taker fee及逐笔trade证据；
- STOP/Algo订单创建、查询、撤销和最终0仓位；
- funding/income history语义；
- Dashboard、SQLite、JSONL、主对账和shadow diff闭环。

每个真实测试只能验证预先指定的一项场所语义；建仓和归零动作必须属于同一`CertificationPlan`，并共享总名义、
费用和最长暴露时间上限。归零失败时不得把残余仓位归入Base，也不得以“等待下一次策略信号”作为处置方案。

禁止在真实账户主动注入危险UNKNOWN、断网或部分成交。此类故障只在本地网关/testnet制造。

### 3.3 最小artifact集合

```text
certification/runs/<run_id>/
  authorization.json
  venue_capability_snapshot.json
  preflight.json
  certification_plan.json
  order_events.jsonl
  exchange_raw/
  query_coverage.json
  primary_ledger_snapshot.json
  shadow_accountant_snapshot.json
  reconciliation_diff.json
  operational_cost.json
  zero_position_proof.json
  manifest.json
```

`manifest.json`最后写入。任何成员缺失、hash错配或最终非零仓位都不能标`completed`。

### 3.4 首批验收矩阵

| 场景 | local gateway | testnet | real minimum | 通过条件 |
| --- | ---: | ---: | ---: | --- |
| client ID幂等 | 必须 | 必须 | 只读复核 | 不重复订单 |
| ACK丢失/REST超时 | 必须 | 可选 | 禁止主动制造 | 查询后唯一闭合状态 |
| 部分成交 | 必须 | 尽力 | 禁止主动制造 | 剩余量、fee、仓位一致 |
| STOP/Algo语义 | 必须 | 必须 | owner另授权 | 创建/查询/撤销/0仓位闭环 |
| rounding/filter | 必须 | 必须 | owner另授权 | 计划值与场所接受值可解释 |
| funding/income | fixture | testnet若可用 | 只读观察 | 原始符号与白名单会计一致 |
| 崩溃恢复 | 必须 | 必须 | 禁止主动制造 | 无替代单、无未解UNKNOWN |

## 4. Workstream B：Independent Shadow Accountant

### 4.1 独立性约束

Shadow Accountant应位于独立包，例如`src/qount/shadow_accounting/`，并通过导入测试禁止依赖：

```text
qount.execution
qount.mini_trend.pilot_dispatcher
qount.ledger position aggregation/reconciliation implementation
```

它可以复用canonical hashing、不可变artifact codec和通用时间/数值类型，但仓位、成本、NAV和现金事件必须独立实现。
生产取数也不得只读取dispatcher已经整理过的聚合结果：查询时间、分页游标、重试节奏和覆盖窗口必须由shadow路径独立决定，
最后再与主账本对比。允许双方读取同一份已归档原始交易所响应，但必须各自验证原始hash、分页完整性和解析版本。

### 4.2 输入与输出

输入：

- Binance逐笔trades、orders、conditional/algo orders和income history原始响应；
- 每条响应的query window、observed_at、source hash和分页完整性；
- 独立价格mark和symbol rules；
- 只读主账本snapshot，仅用于最后diff，不参与重建。

输出：

- 逐symbol数量、成本基础、realized/unrealized PnL；
- commission、funding、transfer和未知incomeType；
- account NAV和`期末权益 = 期初权益 + realized + unrealized变化 + funding - commission + transfer`恒等式；
- 与主账本逐字段diff、容差、阻断级别；
- 历史下载覆盖窗口和最早可恢复时间。

### 4.3 保留和归档

- VPS保留恢复所需最小滚动窗口和最新快照；
- 完整原始历史按加密、manifest和readback校验后归档到外置盘，不把外置盘当活跃SQLite；
- 交易所在线查询不是永久档案，分页和时间窗口必须在每日任务中显式记录；
- 主账本和shadow抓取至少错开一个可配置时间窗，并分别记录延迟、重试和最终水位，防止同一瞬时缺口造成“一致地漏记”；
- 未知非零incomeType不得自动归类到PnL，必须形成Operational HALT候选。

### 4.4 ExecutionAttributionReport

真实成交样本一旦在未来获得明确授权，必须立即写入独立的`ExecutionAttributionReport`；没有样本时字段保持
`unavailable`，不能用回测常数填充：

```text
decision_to_submit_ms / submit_to_ack_ms / ack_to_fill_ms
planned_vs_filled_qty / partial_fill_count / cancel_replace_count
arrival_mid / bid_ask_spread / fill_vwap / adverse_slippage
maker_or_taker / fee / funding / unfilled_exposure_time
protection_order_latency / stop_gap / attribution_source_hash
```

这份报告用于判断薄edge是否被执行吃掉，不进入策略信号。`post_only`是独立执行假设：必须同时记录实际成交率、等待机会成本、
逆向选择和最终fallback taker成本；不得假定maker 100%成交，也不得让未成交订单伪装成持仓收益。

## 5. Workstream C：三层HALT模型

### 5.1 事件分类

| 类型 | 示例 | 默认影响 | 自动动作 |
| --- | --- | --- | --- |
| Operational HALT | UNKNOWN订单、对账失败、数据不完整、保护单缺失、规格漂移、时钟/磁盘异常 | 场所或整个执行平面 | 禁止新增风险；状态未知时不盲目flatten |
| Strategy HALT | 换手/成本/信号分布/回撤/因子暴露偏离冻结合同 | 单一strategy version | 阻止该sleeve增加风险，保留可验证减仓 |
| Portfolio HALT | gross、账户回撤、策略相关性跃升、场所/稳定币集中风险 | 全账户 | 阻止全部新增风险，按冻结处置决定是否flatten |

### 5.2 迁移规则

当前`state/mini_trend/HALT`继续作为最终账户级硬门。迁移分三步：

1. 先只生成结构化`HaltEvent`和建议scope，不改变现有处置；
2. 用历史fixture和故障注入验证分类、升级、降级和恢复；
3. owner单独批准后，才允许Strategy HALT不升级为全局HALT。

当前唯一已生效的账户资本硬边界仍是`100 USDT` canary权益峰值回撤10%后的flatten+全局HALT；当前事实明确没有
账户单日止损。外部建议的单日5%只能作为未来`PortfolioHaltPolicy`候选，在口径、时区、mark价格、资金流处理和恢复动作
预登记并经owner单独批准后启用，不能由本文档直接写成现行生产规则。任何已生效账户级边界都不得被局部scope降级。

无论scope如何，HALT路由必须保持三条不变量：UNKNOWN未闭合时不发替代单；任何减仓/flatten都要先确认不会放大净风险；
恢复必须绑定事件、证据水位、双会计diff和新的owner authorization，不允许仅删除HALT文件。

### 5.3 恢复

```text
halt detected
-> freeze risk increase
-> close UNKNOWN/order/account evidence gaps
-> primary + shadow accounting diff pass
-> write recovery report
-> owner authorization
-> resume at same or lower promotion level
```

## 6. Workstream D：Venue Capability Provenance

Git provenance之外新增动态`VenueCapabilitySnapshot`：

```json
{
  "venue": "binance_usdm",
  "observed_at": "...",
  "server_time_offset_ms": 0,
  "exchange_info_schema_hash": "...",
  "symbol_rules_hash": "...",
  "position_mode": "one_way",
  "margin_mode": "isolated",
  "leverage": 1,
  "order_endpoint_contract_hashes": {},
  "algo_endpoint_contract_hashes": {},
  "order_capabilities": {},
  "conditional_algo_capabilities": {},
  "query_retention_assumptions": {},
  "websocket_assumptions": {},
  "rest_recovery_assumptions": {},
  "changelog_last_reviewed_at": "...",
  "changelog_source_hash": "...",
  "compatibility": "pass|review_required|blocked",
  "blockers": []
}
```

生产行为：

- 精度、filter或端点能力发生未知变化时，允许只读刷新，但禁止新增风险；
- changelog文本变化只触发`review_required`，不能由LLM自动批准兼容；
- STOP/TAKE_PROFIT等条件单必须按当前普通订单与Algo Service能力矩阵验证，不能只因历史endpoint仍返回成功就判兼容；
- 在线订单/成交/income查询的保留窗口、分页上限和“缺失是否代表不存在”必须成为恢复合同，不能依赖未冻结假设；
- adapter contract test通过、owner/maintainer确认并发布新provenance后才恢复；
- 当前REST日线执行不应为尚未采用的WebSocket增加无必要运行依赖；WebSocket恢复测试只在启用该路径前成为硬门。

### 6.1 规模化执行算法门

- 单笔100 USDT canary继续使用简单日线执行，不为制造规模问题预先引入TWAP/VWAP；
- 只有当组合名义、symbol数量、盘口冲击或单日容量超过预登记门时，才研究TWAP/VWAP分批；
- 分批算法必须有可重放的slice计划、剩余暴露、取消/重试、partial fill、保护单和最终归零合同；
- 任何执行算法的净改善都必须以`ExecutionAttributionReport`和paper/shadow样本证明，不能只引用理论market impact。

建议监控`https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log`，保存最终URL、正文hash、
observed_at和上次已审版本。2026-07-23只读探测该入口返回HTTP 202并重定向到当前英文页面；实现时必须允许受控202/redirect，
再由正文解析和hash判断是否有效，不能只看HTTP状态。

## 7. Workstream E：生产代码边界

目标导入方向：

```text
contracts <- strategies/base <- portfolio <- risk <- execution <- ledger
                                      \-> reporting/operations

research modules -> contracts/artifacts only
production modules -X-> scripts/research, alpha_agents experiments, legacy x4/rv
```

优先动作：

- 固化`src/qount/strategies/base.py`为Base生产适配边界；
- 对生产import graph增加测试，禁止导入`mini_trend`中的研究报告/ML/实验模块；
- 旧`journal.py/risk_engine.py/notifier.py`继续legacy guard，不作为新能力依赖；
- 新venue/certification/accounting模块先以contract和fixture建立，不直接改当前live wrapper；
- 所有生产变更继续要求Mac完整回归、VPS production profile、release provenance和新arm轮换。

### 7.1 技术债与实验摩擦清理

多策略上线前先处理已知爆炸面，不把研究长尾当作“再写一个策略”问题：

- **T-F research/production类型隔离**：拆分不可变`Settings`与`ResearchSettings`；研究profile只能产生研究对象，
  `dataclasses.replace`不得静默覆盖live risk、leverage、gross或order flags；生产入口增加类型、profile和运行模式互斥校验；
- **Base信号物理边界**：`src/qount/strategies/base.py`是生产信号合同，研究/ML/实验模块不得反向导入执行器或live settings；
  `mini_trend`兼容导出逐步改为只读兼容层，先用import graph和字节级行为测试保护；
- **单一权威账本迁移**：SQLite WAL + append-only JSONL/chain是目标权威路径；旧`journal.py`、`risk_engine.py`、`notifier.py`
  只允许读对照和迁移审计，不能各自产生第二套NAV或告警真相；完成连续diff后再移除旧写入口；
- **T-D实验工具**：把Mac→WSL数据/代码/hash/命令参数固化成一键、可重放的实验入口，命令失败、依赖缺失、缓存命中和
  artifact发布都显式返回状态；不把LLM调用或手工复制作为实验合同的一部分。

### 7.2 组合兑现的工程前置

allocator接入前先把三件事做成可观察接口：

1. 每个sleeve独立的Signal/Standalone Executable NAV和成本账；
2. 组合前的执行可行性检查、最小名义、precision、容量和风险贡献；
3. 组合后的真实/模拟归因，包括market beta、共同因子、执行成本、保护单和残差。

历史C×D、CTA-R或其他“已验证edge”只能作为输入候选；任何一个sleeve缺少当前版本或执行证据时，allocator必须保留
`research/shadow`状态，不能用另一个sleeve的净额掩盖缺口。

## 8. Workstream F：多sleeve生产准备

多策略allocator代码存在不等于存在可上线alpha。接入生产前必须同时满足：

- 至少两个策略各自拥有独立的`Standalone Executable NAV`证据；
- 每个策略重新通过当前holdout/promotion合同，legacy结果不继承资格；
- 在压力期报告market/momentum/carry等共同因子暴露；
- 先在virtual/shadow验证最小名义、净额、成本和独立会计；
- 当前账户权益低于3000 USDT时，仍遵守最多一个连续live策略的治理规则；
- owner为每个新strategy version单独授权。

因此，allocator接VPS dispatcher属于后置工作，不是P0。

### 8.1 StrategyIntent扩展合同

未来sleeve必须在现有可追踪intent之上输出冻结的研究与风险元数据；这是候选接口，不改变当前Base生产schema：

```text
strategy_id / strategy_version
signal_timestamp / expiry_timestamp
target_exposure_by_symbol
forecast_strength
expected_volatility / expected_turnover / expected_holding_period
liquidity_requirement / capacity_estimate
market_beta / momentum_beta / size_beta / carry_beta
tail_loss_estimate
confidence_state
evidence_version / cost_model_version
```

策略只表达期望暴露及其证据，不自行决定账户资本。缺失、过期、非有限数、未知因子口径或成本模型版本不兼容时，allocator必须
fail closed。`confidence_state`只能来自冻结的证据状态机，不能由LLM自由文本或最近回测表现即时改写。

### 8.2 Allocator与组合风险合同

Allocator分配的是风险预算，不是按回测Sharpe分名义本金。输入至少包括预期增量收益、证据置信、边际风险、流动性、换手、
容量、相关性和尾部损失；输出必须能解释每个sleeve的边际风险贡献及被裁剪原因。

组合层在任何真钱多sleeve之前必须冻结并验证：

- 总crypto market beta，以及momentum、size、carry等共同因子暴露；
- 单币、生态/相关cluster、稳定币、交易场所和抵押品集中上限；
- 组合与单sleeve换手预算、单日可执行名义、容量和`expected cost / expected alpha`上限；
- 正常相关矩阵之外的压力情景：相关性趋近1、流动性同步下降、保护单跳空和场所不可用；
- 每个sleeve先独立通过min-notional/rounding/成本门，再做组合净额，禁止用Base净额掩盖不可执行候选；
- realized attribution同时输出策略PnL、market/momentum/size/carry因子解释和无法解释残差。

相关性和预期alpha只能影响限额内的风险分配，不能覆盖Operational或Portfolio HALT，也不能把未晋级策略变成真钱intent。

### 8.3 候选组合的重新认证顺序

为了避免把“组合数学成立”误读成“已获生产资格”，候选顺序固定为：

```text
historical C×D / CTA-R evidence
-> current-version independent NAV
-> factor and tail re-audit
-> virtual cross-sleeve allocator
-> shadow execution and cost attribution
-> paper
-> minimal live only after separate owner authorization
```

C×D的历史负相关、CTA-R的历史跨资产广度和任何目标Sharpe都只能影响研究优先级；不能跳过carry/no-short/venue/账户权限、
holdout或真实执行门。

## 9. 分阶段交付

### Phase A：合同与离线认证，立即可做

- `CertificationRun/Plan/Event/Result` schema和hash合同；
- 本地venue gateway故障注入器；
- 独立shadow accountant纯函数与golden fixtures；
- `HaltEvent`三层分类和现有全局HALT兼容器；
- `VenueCapabilitySnapshot`和changelog diff artifact；
- production import-boundary测试；
- T-D/T-F的实验入口与research/production类型隔离fixture。

完成标准：全部离线、`orders_authorized=false`、不需要VPS或私有API。

### Phase B：只读生产并行

状态：未来只读阶段；当前文档不自动授予VPS访问或任何订单权限。

- 在现有live周期后生成shadow accountant快照和diff；
- 只读生成venue capability snapshot；
- HALT分类只旁路观测；
- Dashboard增加certification/accounting/venue capability只读状态；
- 在首个授权fill后生成ExecutionAttributionReport，不提前填充模拟slippage/latency。

完成标准：不改变dispatcher决策或订单，至少连续30个运行批次无无法解释diff；样本目标是工程观察，不是自动晋级门。

### Phase C：testnet认证

状态：需要owner对testnet mutation的单独授权；没有授权时只运行local gateway。

- 运行完整故障矩阵；
- 验证重启、重复、部分成交、STOP/Algo和REST恢复；
- 形成testnet certification scorecard。

完成标准：所有UNKNOWN均闭合或正确HALT，任何重放不产生重复订单。

### Phase D：真实最小认证，必须另获授权

状态：当前明确未授权；任何新授权都必须绑定一次性CertificationPlan和失效时间。

- owner指定每个测试的最大名义和费用预算；
- 每次只认证一个场所语义；
- 测试后回到零仓位并完成双会计和三方对账；
- 认证成本独立归档，不进入策略收益。

完成标准：artifact完整不等于Base或新策略获得扩容资格。

### Phase E：多策略生产化，等待研究候选

状态：依赖研究candidate和Phase A-D的适用证据，当前不进入VPS dispatcher。

- 先virtual NAV，再shadow execution，再paper；
- 一次只晋级一个新sleeve；
- 冻结StrategyIntent扩展字段、因子口径、压力矩阵和allocator裁剪理由；
- allocator、Risk、Ledger和Dashboard统一显示sleeve风险贡献、成本和因子暴露。

### 9.1 阶段依赖与退出门

| 阶段 | 必须先有 | 退出门 | 失败处理 |
| --- | --- | --- | --- |
| A 离线合同 | 无私有API、无订单权限 | schema/hash、故障fixture、import boundary和golden diff全通过 | 留在离线；不进入VPS |
| B 只读并行 | A通过、当前VPS只读授权、主/影子抓取水位合同 | 连续30批次无无法解释diff，capability兼容，HALT只旁路 | 停止并回到A；不改变dispatcher |
| C testnet | A通过、testnet明确授权 | 重放无重复单，UNKNOWN闭合或正确HALT，REST重建覆盖gap | 停止testnet；不进入真实认证 |
| D真实最小 | C通过、独立owner授权、账户/venue preflight通过 | 双会计/三方对账通过、成本归档、最终零仓位 | 保留artifact并halt；不归入策略PnL |
| E多sleeve | 至少两个候选通过当前promotion、A-D适用证据 | virtual→shadow→paper逐层对齐，风险/因子/容量门通过 | 回滚Base-only；不接真钱allocator |

任何阶段都不能用下一阶段的“计划完成”替代上一阶段的证据；阶段回退必须保留原artifact和失败原因。

## 10. 验证与回滚

每个阶段最低验证：

- schema/hash/tamper tests；
- 重复JSON key、未知字段、非有限数、时点倒退失败关闭；
- state-machine property tests和crash replay；
- primary/shadow accountant golden diff；
- incomplete artifact和分页缺口测试；
- systemd unit安全属性和资源限制；
- Dashboard只读、无交易credential、无写入口；
- 生产发布仍可整体回滚到当前Base-only release。

任何新模块未通过时，回滚目标是当前`0.2.13` Base-only行为：不恢复legacy cron、X4/C×D/RV-C或forward timer。

## 11. 当前明确不做

- 不为了认证执行链而强制Base产生交易；
- 不在真实账户主动制造UNKNOWN、部分成交或断网；
- 不把认证成本计为策略PnL；
- 不让shadow accountant参与订单决策；
- 不因为changelog无变化就跳过运行时exchangeInfo/filter校验；
- 不在没有独立候选证据时把allocator接成真钱多策略；
- 不恢复carry、short、杠杆提升、期权卖方或多交易所路由；
- 不建设Kafka/Kubernetes/微服务集群，继续采用Python模块化单体、SQLite WAL、JSONL和systemd。

## 12. Phase A 完成记录（2026-07-23）

### 12.1 完成状态

Phase A（§9 合同与离线认证）已全部完成。完成标准已满足：全部离线、`orders_authorized=false`、不需要VPS或私有API。
生产状态不变：`0.2.13`、唯一真钱策略`MiniTrend-UM-Base-v0.2`、所有timer/arm/registry/cron不变。

### 12.2 交付物与证据

| 交付物 | 落点 | 测试数 | 关键不变量 |
| --- | --- | ---: | --- |
| Certification 合同 | `src/qount/certification/contracts.py` | 42 | Plan/Run/Event/Result 全部 `orders_authorized=False`、`strategy_id=None`；`completed` 只在 12 成员齐全 + 零仓位时为 True |
| ExecutionAttributionReport | `src/qount/certification/attribution.py` | 12 | 无 fill 时全 `unavailable`，回测常数被拒 |
| HALT 三层分类 | `src/qount/halt/` | 35 | bypass_mode 不修改 HALT 文件；UNKNOWN 未闭合不发替代单；恢复需 owner auth + 双会计 diff |
| VenueCapabilitySnapshot | `src/qount/venue/` | 21 | pass/review_required/blocked 兼容性转换；changelog 文本变化触发 review_required |
| Shadow accountant | `src/qount/shadow_accounting/` | 20 | 独立重建 positions/NAV；NAV 恒等式验证；未知 incomeType -> HALT 候选；不导入 ledger.store/execution |
| Gateway 故障注入器 | `src/qount/certification/gateway.py` + `fault_injection.py` + `replay.py` | 16 | §3.4 验收矩阵：client ID 幂等/ACK loss/partial fill/STOP/crash 恢复/REST snapshot |
| Import boundary + Settings split | `tests/test_architecture_boundaries.py` + `src/qount/settings.py` | 15 | 4 组新 boundary（shadow/certification/venue/halt）；`safe_research_replace` 阻断生产字段覆盖 |

### 12.3 新增包与文件

4 个独立顶层包（18 个源文件，3375 行）：
- `src/qount/certification/` — contracts、attribution、gateway、fault_injection、replay
- `src/qount/halt/` — contracts、classifier、router
- `src/qount/venue/` — contracts、snapshot、changelog
- `src/qount/shadow_accounting/` — contracts、rebuild、diff

7 个新测试文件（2031 行，161 条新测试）。

修改的现有文件：
- `src/qount/persistence/codec.py` — 注册 9 个新 artifact 类型
- `src/qount/settings.py` — 新增 `ResearchSettings`、`PRODUCTION_CRITICAL_FIELDS`、`safe_research_replace()`
- `tests/test_architecture_boundaries.py` — 新增 4 组 boundary 测试 + `_assert_no_forbidden_imports` 辅助

### 12.4 验证结果

- Mac 全仓 `1722/1722 OK`（Phase A 前为 1561，新增 161 条测试全绿）。
- 现有 `test_immutable_contract_artifacts.py` golden hash `7bb07f55...2968` 未变。
- 现有 `test_architecture_boundaries.py` 前 9 条测试全绿（新类型只增不改现有）。
- 现有 `test_decision_batch_artifacts.py` golden hash 未变。
- `orders_authorized=False` 在所有 certification 合同中恒定，由 `validate()` 强制。
- shadow_accounting 不导入 `qount.execution`/`qount.mini_trend.pilot_dispatcher`/`qount.ledger.store`，由 AST boundary 测试强制。
- HALT bypass_mode 不修改 `state/mini_trend/HALT` 文件，由 `test_classify_halt_does_not_modify_file` 验证。
- 本批未访问 VPS、私有 API、交易所、订单接口；未修改 timer、arm、registry、cron 或 live 开关。

### 12.5 下一步

Phase A 完成后，Phase B（只读生产并行）需要：A 通过 + 当前 VPS 只读授权 + 主/影子抓取水位合同。
Phase C（testnet 认证）需要 A 通过 + testnet 明确授权。
Phase D（真实最小认证）需要 C 通过 + 独立 owner 授权。
当前均未授权。

## 13. Phase B 推进记录（2026-07-23）

### 13.1 完成状态

Phase B（§9 只读生产并行）的本地管道建设已完成。owner 已授权 VPS 只读并行。
前置条件满足：A 通过 ✓、VPS 只读授权 ✓、主/影子抓取水位合同已实现（`WatermarkContract`）。
生产状态不变：`0.2.13`、唯一真钱策略 `MiniTrend-UM-Base-v0.2`、所有 timer/arm/registry/cron 不变。

### 13.2 交付物与证据

Phase A 交付了纯函数"数学引擎"，Phase B 建设了"管道"层（抓取 + 归档 + 编排 + 对比）。

| 交付物 | 落点 | 测试数 | 关键不变量 |
| --- | --- | ---: | --- |
| Private 数据抓取器 | `src/qount/shadow_accounting/fetch.py` | 15 | `ReadOnlyExchange` Protocol 注入；独立分页/重试/覆盖窗口；不导入 ccxt/execution/ledger |
| 原始响应归档器 | `src/qount/shadow_accounting/archive.py` | 12 | immutable JSONL + SHA-256 manifest；tamper 检测；重复归档拒绝 |
| Shadow 编排层 | `src/qount/shadow_accounting/orchestrator.py` | 7 | 全链路：fetch→archive→rebuild→diff→归档；水位合同；空状态 diff=pass |
| 主账本 snapshot 提取器 | `src/qount/primary_snapshot/extract.py` | 7 | 直接 sqlite3 只读读 RuntimeLedger；不导入 ledger.store；字段映射 fees→commission |
| HALT 旁路观测编排器 | `src/qount/halt/observer.py` | 8 | bypass_mode 不改 HALT 文件；无事件不归档；事件全 bypass |
| Venue snapshot 抓取器 | `src/qount/venue/fetch.py` + `orchestrator.py` | 12 | `VenueDataFetcher` Protocol 注入；exchangeInfo/changelog 抓取；202/redirect 处理 |
| Phase B 只读脚本入口 | `scripts/operations/phase_b_readonly_run.py` | — | 统一 shadow/venue/halt 子命令；构建 ccxt client；不改 dispatcher |
| Import boundary 扩展 | `tests/test_architecture_boundaries.py` | +1 | 新增 6 个模块到 SHADOW/VENUE/HALT boundary；新增 PRIMARY_SNAPSHOT boundary |
| Contracts 扩展 | `src/qount/shadow_accounting/contracts.py` | — | `QueryMetadata`/`FetchResult`/`WatermarkContract`/`ShadowRun`；修复 `ShadowCoverageWindow.validate` 的 `gaps` 引用 bug |

新增 1 个独立顶层包（`primary_snapshot/`，2 个源文件）、6 个新源文件（fetch/archive/orchestrator × shadow+venue+halt）、
1 个脚本入口、5 个新测试文件。Mac 全仓 `1783/1783 OK`（Phase A 前为 1722，新增 61 条测试全绿）。
现有 golden hash 不变；`orders_authorized=false` 在所有 certification 合同中恒定。

### 13.3 新增包与文件

- `src/qount/primary_snapshot/` — 独立主账本 snapshot 提取器（不导入 ledger.store）
- `src/qount/shadow_accounting/fetch.py` — Private 数据抓取器（Protocol 注入）
- `src/qount/shadow_accounting/archive.py` — 原始响应归档器
- `src/qount/shadow_accounting/orchestrator.py` — Shadow 编排层
- `src/qount/venue/fetch.py` — Venue data 抓取器（Protocol 注入）
- `src/qount/venue/orchestrator.py` — Venue snapshot 编排层
- `src/qount/halt/observer.py` — HALT 旁路观测编排器
- `scripts/operations/phase_b_readonly_run.py` — 统一只读脚本入口

### 13.4 VPS 部署方式

初期手动 SSH 触发（不建新 systemd timer，待 30 批次验证后另获 owner 授权）：

```bash
ssh qount-vps 'cd /root/qount && PYTHONPATH=src ./.venv/bin/python \
  scripts/operations/phase_b_readonly_run.py \
  --mode all \
  --symbols BTCUSDT ETHUSDT BNBUSDT \
  --runtime-ledger-path /root/qount/state/mini_trend/forward/latest/runtime.sqlite3 \
  --halt-path /root/qount/state/mini_trend/HALT \
  --state-dir /root/qount/state/phase_b \
  --live-cycle-completed-at <ISO_TIMESTAMP>'
```

归档落点：`state/phase_b/shadow_accounting/runs/`、`state/phase_b/venue_snapshots/`、`state/phase_b/halt_observations/`。

### 13.5 当前限制

- 当前 live cycle 权重 `0/0/0`、0 成交：shadow 只能验证"空状态一致性 + 管道正确性"。
- 真正的 trades/income 重建能力要等首笔成交验证。
- 0 成交期间 `ExecutionAttributionReport` 保持 `unavailable`，不填模拟 slippage/latency。
- 30 批次退出门（§9.1）从 VPS 首次 shadow 运行开始计数。

### 13.6 首次 VPS 只读验证（batch #1）

2026-07-23 在 VPS 首次运行 `phase_b_readonly_run.py --mode all`，结果：

- **Shadow accountant**：`has_blocking_diff=false`、`unknown_income_count=0`。9 个 diff 字段全部 pass/warn
  （3 position quantity pass + equity pass + realized/funding/commission/transfer pass + unrealized warn）。
  24h 查询窗口、initial_equity 从 primary snapshot 获取。
- **Venue snapshot**：`compatibility=pass`、`blockers=[]`。exchangeInfo 845 symbols、changelog hash 首次记录。
- **HALT observer**：`event_count=0`。无 HALT 文件、无 UNKNOWN 订单、无 reconciliation 问题。
- 归档落 `state/phase_b/shadow_accounting/runs/20260722T170922Z/`、`state/phase_b/venue_snapshots/`。
- 未修改 dispatcher/订单/HALT 文件/timer/arm/registry。生产状态 `0.2.13` 不变。

30 批次退出门开始计数（batch #1/30）。

### 13.7 下一步

1. 在每个日线 live cycle 后手动运行 `phase_b_readonly_run.py`，积累剩余 29 批次。
2. 30 批次无无法解释 diff 后，Phase B 退出门通过。
3. 可选：建 `qount-phase-b-readonly.timer`（需 owner 对新 timer 的单独授权）。
4. Dashboard 只读状态（`phase_b_observability` read model）作为后续工作。
