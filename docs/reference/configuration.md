# Configuration reference

> **状态**：active｜**权威**：L2 configuration contract｜**最后更新**：2026-10-11
> **适用范围**：环境变量、配置来源、密钥边界和只读预检。
> **TL;DR**：机器可读权威是 [`../../config/environment-contract.toml`](../../config/environment-contract.toml)。本文件解释如何安全使用它；不包含任何实际值、账户标识或凭证。

P3 v2's non-secret [expanded training contract](../../config/etf-alpha-expanded-20261003.json) registers past-only bootstrap sources, seven ablations, five seeds, 259 fits and 24 CPU workers. It retains `max_hours=null/wall_clock_limit_enabled=false`, fixed per-fit pretraining and early stopping. The WSL contract is authorized by the latest owner instruction recorded in [current.md](../current.md); the separate3080Ti cloud contract remains paused. `automatic_restart_authorized=false` applies to both: connectivity recovery or a failed run does not restart tasks. A supervisor exits after the registered tasks finish. Original data limitations, discovery/fresh-confirmation boundaries and service/order limits remain unchanged.

The isolated [3080Ti cloud contract](../../config/etf-alpha-cloud-3080ti-20261003.json) adds an explicit `compute_profile`: owner-designated machine, actual data mount/root, GPU type, CPU quota20/default18 workers, eightGiB disk reserve, four diagnostic threads, runtime compilation choices and declared hourly price. It changes storage topology only; dataset/fold hashes, learning options, seeds and risk/selection protocol remain fixed. This JSON is non-secret and does not load `.env` or expand the public `config-check` host profiles. The cloud adapter supplies its own cgroup/mount/GPU/input preflight. New cloud storage is temporary compute with final important results returned to E; deployment details are in [P3 §20](../etf-p3-research-plan-2026-10.md#20-3080-ti-付费云计算交付与性能策略2026-10-03).

## Individual-equity selection intake contract

`config/c60-gradient-20261011.json` is a separate discovery contract: fixed BTC SMA50 distance thresholds −2/0/+2%, 0/35/70/100% budgets, unchanged own SMA20/PAXG/selection rules, and a portfolio L1 15% band against actual pretrade weights. It binds twelve 25/50bps × 0/1-delay comparison ledgers and same-hash public open projections; revision1/2 missing-input failures remain preserved. It does not amend the Q-DIV designs, original C60 contracts, seventeen-round ranking or deployed parameters. [Execution record](../research-remediation-plan-2026-10.md).

`config/q-div-full-acquisition-20261011.json` revision3 freezes P1 all-market public-input scope, 2013Q1–2026Q3 financial periods across all12 report types and2014–2026-10-09 market warmup/research input range. It captures636 financial-only identifiers as unqualified data, adds BSE alias mapping, monthly historical ST and index metadata, and reuses earlier six-type/master-inventory shards. It allows eight Mac threads sharing420 requests/minute, five bounded transient retries, an adaptive cooldown and a40,000-attempt ceiling. Successful prior research shards are reused through hash-bound public job inventories. Credentials remain in the Mac's private0600 configuration/memory; all bulk public responses are immutable E files. This input contract neither changes strategy rules nor certifies PIT/full historical universe or total returns. The later owner instruction “不考虑st” is recorded in `owner-scope-update-20261011.json` beside the immutable dataset; it excludes the st event endpoint from acquisition completion without rewriting the original contract/failure. Exact transport repairs preserve the original inventory and bind its SHA256 before fetching only failed network shards.

`config/ashare-q-div-core-design-20261011.json` is a frozen research-design specification, with 28 fixed-role designs, 124 strategy/diagnostic paths and four universe-control ledgers planned. It is not accepted by an existing runner: qualified historical inputs, total-return benchmark IDs, dated cash/tax/execution evidence and implementation hashes remain pending. It preserves the prior Q-DIV contract; no CLI, environment or service interface is added. See [the active protocol](../ashare-q-div-ivol-study-2026-10.md#精简q-div-core研究设计2026-10-11设计冻结未执行).

`config/ashare-q-div-ivol.json` freezes the new Q-DIV rules, implementation hashes, same-source price references, bounded public snapshot sources and proposed four-curve/gate protocol. Revision2 preserves the pre-selection revision1 receipt-format failure; no economic parameter changed. It explicitly scopes this implementation to dated screening and research primitives: full historical inputs and a separately validated portfolio execution engine are still required before producing returns. The 120-name IVOL-ordered financial collection limit is a declared snapshot scope, never a historical universe or an implicit all-A completeness claim. See the [primary study](../ashare-q-div-ivol-study-2026-10.md).

`config/ashare-q-div-review-20261011.json` binds a separate descriptive dividend review to that unchanged strategy contract, snapshot manifest, financial acquisition contract and review implementation. It declares zero new strategy rules and no re-selection/returns; payment-window ratios, matched fiscal-year ratios and missing capex/FCF are separate. It is not a backtest or source-acquisition contract.


[ashare-tushare-supplement-20261009.json](../../config/ashare-tushare-supplement-20261009.json) binds a bounded 807-request same-source acquisition: Mac-only, hidden in-memory credential input, serial official HTTPS with no redirects/retries, credential-free raw responses streamed to E. It records current L/D/P identity snapshots, two calendars, all 408 prior flagged factor series and 196 missing retired targets; it never persists credentials or treats completion as price semantics/PIT certification. `daily/stock_basic` use the documented 6000 rejection threshold; `adj_factor` has no invented row cap and requires explicit completeness plus date reconciliation.

[ashare-tushare-proxy-qualification-20261009.json](../../config/ashare-tushare-proxy-qualification-20261009.json) binds acquisition, prior evidence, owner provenance and a scoped semantic review before source traversal. Qualification compares flagged original factor dates to fresh same-vendor dates and original adjusted OHLC to raw × same-date factor × fixed security anchor. A passing receipt qualifies only `vendor_defined_adjusted_price_proxy`; it does not certify cash total return, economic corporate actions, historical as-of factor vintages, PIT or fills. Vendor-reproduced reference-price bridge residuals remain explicit. Original proposals/receipts stay immutable.

[ashare-information-run-20261010.json](../../config/ashare-information-run-20261010.json) is the later actual-run freeze. It binds the unchanged original proposal and implementation plan, scoped affirmative receipt, original ZIP/source/calendar manifests, exact Python version and all implementation source hashes. One information experiment uses 3211 original locators plus 196 same-provider retired targets; one positive activity candidate, a full 2855-date grid and common 2745-date maturity/purge/embargo mask, shared membership across four label cells, typed unknowns and the original statistical gate. Diagnostic definitions are fixed before labels; no parameter search, independent OOS, portfolio or execution claim is authorized. A false or mismatched qualification fails before market-panel access. Connectivity recovery never retries an experiment; result state is only in [current](../current.md).

[ashare-next-evidence-plan-20261010.json](../../config/ashare-next-evidence-plan-20261010.json) binds the completed information result, independent verifier and endpoint source audit. It records the frozen candidate's stop/no-promotion disposition and the then-proposed evidence sequence, with no additional experiment or API request. It remains an immutable planning snapshot. The later [owner scope clarification](../current.md#a股选股推进范围修正2026-10-10) supersedes its historical-evidence-first priority for current screening: use decision-time eligibility, sufficient signal inputs and explicit freshness; obtain historical lifecycle/settlement evidence only for claims or paths that depend on it. The completed experiment and its unknowns are unchanged, and screening does not authorize orders or certify performance.

[ashare-data-supplement-20261009.json](../../config/ashare-data-supplement-20261009.json) binds the owner's Tushare confirmation, unchanged economic proposal, completed two-exchange calendar review, public-source rules, SDK and original/metadata manifests. It permits a bounded single-connection acquisition of 196 missing retired main-board-prefix source identities on WSL/E, preserves every response and stops on failure without retries. BaoStock raw quotes and factor events stay separate from the Tushare archive; neither a source supplement nor a present-day metadata snapshot certifies adjustment semantics, PIT membership or terminal recovery.

[ashare-information-stage-20261009.json](../../config/ashare-information-stage-20261009.json) is the earlier implementation-plan snapshot, whose original false/status fields remain unchanged. It preserves the original hypothesis and gates while fixing exact session endpoints, one maturity/purge/embargo mask, unknown-member handling and noncircular 60-session moving-block resampling. Its later scoped qualification and actual runner are separately bound by the 2026-10-10 run contract above. This plan neither arms a runtime nor certifies an executable portfolio.

[ashare-selection-evidence-20261009.json](../../config/ashare-selection-evidence-20261009.json) binds the later owner evidence instruction, unchanged source/audit, prior calendar review and 31 official numeric examples. It freezes relative amount/volume scales and reference-price/change/pct consistency tolerances before a fresh WSL/E forensic audit. Matches corroborate algebra and examples; they cannot authenticate the original vendor, absolute units, paging, corporate actions or PIT. No financial labels/rankings are produced and prior source gates remain unchanged.

[ashare-selection-qualification-20261009.json](../../config/ashare-selection-qualification-20261009.json) records the later owner instruction to begin A-share research and binds the unchanged design snapshot by SHA256. The first phase permits only official-calendar and past-window qualification on WSL/E. It neither relaxes source semantics nor treats authorization as evidence: information labels require verified source/adjustment/calendar; a portfolio further requires units, dated identities/tradability/industry, corporate actions and opening fills. Source-window counts use file prefixes only as locators and never certify historical main-board eligibility. No features, rankings or returns are produced in qualification; existing output roots are rejected. The calendar review and source/code manifests are frozen before the run, and failures do not auto-restart.

[ashare-selection-proposal-20261009.json](../../config/ashare-selection-proposal-20261009.json) is a design-only A-share proposal following the owner's explicit instruction not to execute. It describes one price-stratified relative-amount hypothesis, a primary20-session label and diagnostic5-session label, independent cash-owned subledgers and dated execution/cost evidence gates. All market-panel compute, signals, backtests, fits, acquisitions and remote-launch authorizations are false; no runtime consumes this file. Parameters are untested proposals. It does not amend the frozen intake/source audit, authorize a launch, or grant production permissions. A later owner instruction and separate code/data/rule-bound run freeze are required. Full methodology and failure criteria are in the [primary study](../equity-selection-study-2026-10.md).

[equity-selection-intake-20261009.json](../../config/equity-selection-intake-20261009.json) records the owner scope change to CN/US individual-equity research without a forced low-frequency policy or monthly entry cap. It binds a user ZIP by SHA256/bytes and immutable E dataset root, with four CPU audit workers, no imputation and no return labels in the intake phase. The proposed price-strength baseline/relative-trading-activity increment and5/20-session labels require a separate frozen economic protocol before evaluation. Historical-universe, adjustment, corporate-action and tradability evidence remain distinct from a structural CSV audit. The original short-horizon contract remains an immutable historical study; its cap and thresholds are not edited for the new line. [Primary study](../equity-selection-study-2026-10.md).

## Short-horizon opportunity contract

[short-horizon-opportunity-20261009.json](../../config/short-horizon-opportunity-20261009.json) freezes one Binance hourly flow/reclaim candidate, a price-only control and cash across 10/25bps per-side costs and 0/1-hour extra delay: 12 diagnostic cells, not independent trials. BTC/ETH, 168-hour volume/24-hour low prefixes, a 6-hour holding label, global 72-hour cooldown and four entries per UTC month are fixed before labels. Any feature-window gap makes the complete acceptance plan unknown; accepted unknown/censored paths cannot free slots or pass the gate. All history through2026-08 is discovery. No future window, P3 outer or liquidation collector result is read.

Funding uses signed archived events and conditional hourly mark bounds, with an explicit `[entry,exit)` ownership proxy. Hourly stress includes the exit boundary mark open; assumed maintenance rates and1/3/5/10/20 leverage scenarios never certify historical liquidation or safe leverage. This is per-entry-notional event research, not executable NAV. The complete A-share dictionary is frozen too: one main-board disclosure-upgrade idea, PIT/corporate-action/tradability evidence requirements, financing=false and returns_run_authorized=false. Public-cache reuse changes acquisition routing only, with source manifests/checksums retained; no `.env` is loaded. [Primary study](../short-horizon-opportunity-study-2026-10.md).

## Sources and ownership

The non-secret [residual pilot proposal](../../config/etf-alpha-residual-pilot-20261003.json) remains the historical, unfitted plan snapshot. Its [implemented runtime contract](../../config/etf-alpha-residual-ready-20261003.json) binds that proposal hash and preserves all target/model/seed/selection/budget/execution fields. It adds only declared engine choices: CUDA eager FP32, AdamW betas/epsilon and clip1, 500 interval draws, 400 stability draws, a first-2015-session rebalance phase, the shared CUDA lock and frozen original-fold path. `training_start_authorized=false/training_status=ready_waiting_owner` allows preparation but requires a later explicit owner instruction and a fresh receipt binding the ready/code/input manifests before fitting. The source contract stays immutable when a future receipt activates one new run. Pilot stops at51 fits without increment; the passing schedule caps at272 total fits. No automatic restart, ten-seed extension, cloud resumption or production authority. [Methods and deployment](../etf-p3-research-plan-2026-10.md#22-残差训练引擎实施与待命部署2026-10-03).

The current [reviewed R3 contract](../../config/etf-alpha-residual-reviewed-20261003.json), schema-v2, retains those research fields and binds the historical runtime hash. It registers `null_minimum_shift_sessions=25` (20-session labels plus five-session separation) and `portfolio_boundary_policy=continuous_close_decisions_next_open_fills`. The engine rejects near-date null pairings and executes joined annual forecasts so a year-end close decision can fill at the next year's open. These refinements add no models, seeds or fits. Historical schema-v1 deliveries remain immutable evidence; use the current ready pointer rather than selecting a contract by filename. [Review and innovation choices](../etf-p3-research-plan-2026-10.md#23-r3开训前复审修正与创新取舍2026-10-03).

The waiting-owner flags in a proposal, prepared contract or `READY.json` are snapshot fields. A later owner activation is a separate receipt bound to that snapshot and exactly one new output directory. Read the activated run's `owner-activation.json`, `status.json` and sibling exit receipt for execution state; `state/research_runs/etf_alpha_residual/latest-run.json` locates the run on the Mac. Keep all original contracts unchanged after completion, and do not treat a consumed activation as permission for another run.

| Host | Configuration source | Secret policy | Data boundary |
| --- | --- | --- | --- |
| Mac | `<repo>/.env`（私有、`0600`） | 可保留本机研究所需最小密钥；不回显、不提交 | 代码、轻量 fixture 与摘要，不长期保存全量数据或生产状态。 |
| Windows external disk | no `.env` | 禁止密钥 | `E:\qount_data` 保存数据集、不可变 artifact、环境锁与备份 manifest。 |
| WSL | `deploy/wsl/qount-compute.env` | 不存密钥；只加载非敏感计算拓扑 | scratch 可清理；最终产物直写外置盘。 |
| Owner-designated P3 cloud compute | standalone research JSON / public delivery | 不发送凭据或私有环境文件 | 数据盘临时生成/计算，最终重要结果回收到E；不承载生产服务。 |
| VPS | `/etc/qount/*.env`，按服务拆分、`root:root 0600` | 仅服务需要的密钥；禁止复制回 Mac/WSL/外置盘 | 最小运行状态、公开缓存和审计材料。 |

`deploy/wsl/qount-compute.env` 是非敏感拓扑文件，不得与私有 `.env` 合并，不得放入外置盘。VPS 的 `/etc/qount/*.env` 是主机拥有的部署配置，不在本仓库内创建或修改。

## Research training proposals

The bounded P3 Stage 1 run uses [config/etf-alpha-overnight-20261003.json](../../config/etf-alpha-overnight-20261003.json), an explicit research authorization/runtime contract layered over the immutable October 2 parameter proposal. It fixes the dataset/fold hashes, eight-hour ceiling, 224-fit ceiling, seeds, float32/no AMP and one RTX4060 trainer. It is consumed only by the research package/adapter, requires mounted E storage and does not load any `.env` or grant order/service authority. The historical proposal's `training_start_authorized=false` describes its original delivery; the new run contract and `current.md` record the later owner decision.

[`config/etf-alpha-stage1-proposal-20261002.json`](../../config/etf-alpha-stage1-proposal-20261002.json) 保存 ETF P3 Stage 1 的待审批网络、训练与预算参数，
对应 [P3 主计划 §16](../etf-p3-research-plan-2026-10.md#16-研究数据标准调整与-alpha-训练审批方案2026-10-02)。
其中研究数据门按 owner 决定通过；原交付时 `training_start_authorized=false`；后续批准由上方独立运行合同承接，原提案仅提供冻结参数，不单独授予执行或生产权限。
后续批准须在 `current.md` 单独登记，并在新 run 中冻结训练合同；原数据审计与 manifest 不覆写。

## Contract and preflight

每个环境变量在合同中声明名称、域、类型、是否敏感、允许主机、必填条件、默认策略、消费者和 legacy 状态。新增变量必须先进入合同；legacy 条目不应被用于新逻辑。

```bash
# 只解析键名和文件权限；不会联网、创建 state 或打印任何值。
qount-run config-check --profile mac --env-file .env

# WSL 仅允许非敏感拓扑变量。
qount-run config-check --profile wsl --env-file deploy/wsl/qount-compute.env
```

检查会报告缺失、未知、主机不允许、包含已配置密钥的文件权限不安全、以及请求 live/已禁用线路的互斥配置。输出只包含变量名和分类，永远不包含值、长度、前缀或哈希。检查失败退出码为 `2`。

## Safe local loading

只加载你信任且权限正确的本机 `.env`，不要使用 `export $(grep … | xargs)` 之类会错误解析空格、引号和注释的写法。

```bash
set -a
. ./.env
set +a
qount-run config-check --profile mac
qount-run --help
```

`.env.example` 是 Mac 安全模板：只含本机可用的非敏感默认值和空占位符。VPS 专用变量只在合同与部署说明中说明目标环境文件，绝不复制任何凭证。

## Troubleshooting

- `unknown`: 先将新变量加入合同并写明消费者；不要绕过检查。
- `host_not_allowed`: 将配置移到批准的主机，不把密钥同步到 WSL 或外置盘。
- `unsafe_permissions`: 若文件有已配置密钥，人工执行 `chmod 600 <file>`；检查工具只报告，不修改权限。
- `disabled_strategy_requested` / `live_enable_requested`: 立即移除该请求；本次治理不授权 live、arm、订单、timer 或 cron。

## G20/C60 离线研究合同

[ashare-quality-momentum-backtest-20261010.json](../../config/ashare-quality-momentum-backtest-20261010.json) freezes price stability relative to the same-day industry median, MA60/120 trend, 60-session risk-adjusted return, ten-session reviews, 18% close trailing exit, age >252 and 20%/63-full-session portfolio cooldown. Four declared curves preserve the same industry caps in the liquidity control. Its minimum gate requires positive cost/delay zero-recovery CAGRs, base positive CAGR, drawdown ≤40% and ≥100 closed trades; improvement over the control is descriptive only. Quality means price stability, not financial quality. This consumed-history discovery has no promotion authority.

[ashare-business-review-20261010.json](../../config/ashare-business-review-20261010.json) records the purpose-specific business/dated-trend review of the ten existing lowrisk virtual holdings plus two explicitly limited operating comparisons. It adds no strategy, backtest or threshold; H1 financials, 9/30 qualified trend and 10/9 separate raw references remain distinct. A/B/C means research priority; valuation and current tradability remain unresolved. Formal scope recording followed partial evidence acquisition, so it is not a preregistered economic experiment.

[ashare-leader-backtest-20261010.json](../../config/ashare-leader-backtest-20261010.json) freezes one new technical-leader/trend discovery: eligible-industry strength/liquidity intersections, MA20/60/200 and prior20-close breakout, cost-based initial/profit-trailing stops, 8 slots and 12%/20-session portfolio protection. Its declared annualized-return/drawdown research gate compares with the already-consumed lowrisk result; this is not independent OOS or business-leadership certification.

[ashare-lowrisk-backtest-20261010.json](../../config/ashare-lowrisk-backtest-20261010.json) freezes the separately registered low-volatility/uptrend candidate: MA200, five-session ranking buffer, industry risk slots including unknowns, portfolio drawdown exit and 63-session cooldown. It reuses frozen synthetic accounting; base/double-cost/extra-day and declared liquidity control are discovery curves, never cash-NAV or production certification.

[ashare-strategy-backtest-20261010.json](../../config/ashare-strategy-backtest-20261010.json) binds the aggressive A-share sector/momentum/holding discovery rules, three cost/delay cells and same-universe price control. Capital, entry lots/budgets, concentration slots, trailing/MA/age exits, persistent blocked sells, missing-mark interval and assumed costs are frozen with source/code/Python hashes. Synthetic adjusted units do not certify cash dividends or actual executable NAV. [ashare-research-registry.json](../../config/ashare-research-registry.json) indexes this independent research line; it is never a production/runtime configuration.


[ashare-sector-company-screen-20261010.json](../../config/ashare-sector-company-screen-20261010.json) freezes one dated sector/company discovery queue: 61 exact sessions,252 past valid raw observations,20-session median amount≥CNY20m,10 members per sector, positive20-session median and≥50% breadth, top5 sector60-session medians and top2 stocks per sector. Industry descriptors are the stated 2026-10-09 snapshot, not historical PIT. Financial/policy review is a separate cited qualitative overlay; volatility is diagnostic only. Source/code/Python/calendar/scoped qualification bindings precede WSL/E access; no future labels, portfolio or orders.


这些JSON是独立离线研究的运行前合同，均为`research_only=true/orders_authorized=false/promotion_evidence=false`；既有paper合同和当前授权按[current.md](../current.md)读取。下表的候选与曲线是各轮固定口径，完整算法、比较与修订见[主研究总览](../dual-engine-optimization-2026-10.md#研究总览与阅读路径)。

| 轮次 | 冻结合同 | 新候选 / 历史曲线 | 固定研究范围 |
| --- | --- | ---: | --- |
| 1 | [optimization](../../config/dual-engine-optimization-20261004.json) | 2 / 17 | 有限优化 |
| 2 | [execution](../../config/dual-engine-execution-20261004.json) | 2 / 64 | 归因与执行 |
| 3 | [structural](../../config/dual-engine-structural-20261004.json) | 7 / 60 | 结构探索 |
| 4 | [expansion](../../config/dual-engine-expansion-20261004.json) | 19 / 116 | 扩仓、基本面与危机 |
| 5 | [nextgen](../../config/dual-engine-nextgen-20261004.json) | 16 / 104 | 来源改革与版本维护 |
| 6 | [regimes](../../config/dual-engine-regimes-20261004.json) | 16 / 104 | 核心交接与自主卫星 |
| 7 | [breadth](../../config/dual-engine-breadth-20261005.json) | 14 / 84 | 广度与保护退出 |
| 8 | [clocks](../../config/dual-engine-clocks-20261005.json) | 8 / 60 | 盈亏归因与交易时钟 |
| 9 | [reform](../../config/dual-engine-reform-20261005.json) | 14 / 100 | 批次意图与资本分书 |
| 10 | [renewal](../../config/dual-engine-renewal-20261005.json) | 10 / 72 | 风险恢复与再分配 |
| 11 | [sources](../../config/dual-engine-sources-20261005.json) | 8 / 52 | 公开信息源 |
| 12 | [zonal](../../config/dual-engine-zonal-20261005.json) | 8 / 72 | 恢复范围与实际敞口 |
| 13 | [zorder](../../config/dual-engine-zorder-20261005.json) | 8 / 76 | 共同结算与家族刷新 |
| 14 | [features](../../config/dual-engine-features-20261005.json) | 4 / 32 | C60闭合路径质量与年化／回撤／胜率三目标 |
| 15 | [states](../../config/dual-engine-states-20261005.json) | 6 / 40 | 自身历史状态、共同反弹防护与局部加速获取 |
| 16 | [execution-ownership](../../config/dual-engine-execution-ownership-20261005.json) | 9 / 72 | G20源所有权与C60重复获取成本 |
| 17 | [cashflow](../../config/dual-engine-cashflow-20261005.json) | 1 / 12 | BTC现货／永续双腿资金代理与范围、净费用、独立USDT抵押；诊断line不进入原排名 |

[holdings归因合同](../../config/dual-engine-holdings-20261005.json)绑定前七轮549曲线及原现金／单位账本，不创建新候选；区分闭合与未退出持仓，并将实际费用分配到资产／持仓段。仅权重历史标记为不支持完整单位归因。

[研究登记索引](../../config/dual-engine-research-registry.json)绑定各轮原结果根／manifest、所有策略描述、固定四格最弱超额Sharpe政策、剔除理由和确认收据。`prior_*`保留原轮次快照；旧轮次数量、领先与冻结后检查不覆盖当前登记，也不能确认新版本。宏观候选存在修订暴露时按原声明排除选择；全球trial计数和DSR/PBO限制见主研究。

G20月度资本份额、日度实际投资额指令和穿透杠杆是不同约束；迟到成交与价格漂移使20%／40%决策预算不等于连续硬上限。第十三轮预算触及扩为全书共同再平衡，可能买入风险资产。C60周度刷新、名义零退出及非周日恢复有各自范围，不能把卫星周度版本解释为所有核心交易都停止。所有买卖费用按原现金单位／分书规则计入，不合成独立收益。

运行使用独立新E目录，源码／输入／合同在读收益前绑定；失败v1、修正版v2及其manifest分开保留。warmup修正记录在原结果与主研究，本文不修改冻结JSON。任何确认需要对应候选自己的账户和窗口，旧确认或准备快照不授予重跑／调度权限。

第十四轮只改变C60原非PAXG名义权重的连续缩减，20/60/90方向一致性、60日路径效率和下行平方回报占比均只读闭合历史。原月度选择、风险门和`sat_week`时钟保留；`uniform75`固定缩仓控制预先排除选择，不称精确风险匹配。三目标门独立于原排名：四格年化均提高、回撤均不恶化、扣费完整持仓段胜率均提高。未退出持仓单列；固定20日标签与分箱只作重叠、非独立的历史诊断，不进入拟合或目标生成。

第十五轮从agreement目标出发，状态使用排除当日的过去252日60日效率midrank，至少60有效历史；unknown保留权重，PAXG不变。成熟／反弹减半与额外加速获取分开为六候选，原时钟范围与新资产事件取并集，不由单一新事件扩为全核心。延迟时额外事件失效冻结已有单位，名义零仍走原退出；原计划范围不被取消。三目标相对agreement四格独立报告，排名政策不变；33个不同反弹入选日期不是独立大样本。完整负结果和已冻结停止条件见主研究§20。

第十六轮携带G20最后显式稀疏源，预算补集不含源零资产；最新闭合源零取消正目标，在原全书／范围意图执行日也可能退出已有仓位。原暖启动／月度资本转移／gross费用保留，正确性不等于收益改善。C60复制rebound_half目标，只抑制已持有且非恢复／续填的10%或25%小额补仓，冻结单位；local恢复仅触发家族，仍周日卫星刷新。原减仓／零退出不抑制，风险门为计划门而非实际硬波动上限。两个比例和五C60版本在读取结果前冻结，无阈值搜索或理论最优声称。
