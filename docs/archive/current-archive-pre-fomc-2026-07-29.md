# 当前事实历史归档（2026-07-27 及更早）

> **状态**：archived｜**权威**：L6 归档｜**最后更新**：2026-07-29
> **本文回答**：从 `current.md` 迁出的历史生产、研究和架构记录。
> **TL;DR**：仅用于追溯，不覆盖当前 FOMC 状态、权限或 VPS 只读事实。

以下正文逐行迁自 `current.md`；相对链接已按本目录重写。

- **2026-07-27 `0.2.21`已部署至VPS，FOMC live路径保持未启用。** 本地全仓`2370/2370 OK`，VPS production profile
  `360/360 OK`；editable package=`0.2.21`，逐文件release verification通过。`qount-fomc-live.service/.timer`已安装到
  systemd，仓库模板与安装文件SHA-256逐项一致，timer=`disabled/inactive`且无NEXT；`/root/.config/qount/fomc-live.env`不存在。
  本轮没有运行私有`prepare`、创建arm、启用live switch、访问交易所私有账户或发出订单。现有用户自有BTC仓位和两张条件单仍须由owner
  先平掉/撤掉，之后才能在shadow信号`ARMED`且仍处入场窗口时运行私有readiness预检。

- **2026-07-27 `0.2.20`账户只读、Dashboard和个人微信链已全面修复并部署。** 干净release只从提交对象生成，未包含本地FOMC
  脏工作树；VPS聚焦`132/132 OK`、production profile `360/360 OK`，provenance逐文件回读通过。单次order-free forward run=
  `20260727T073725Z`成功，记录用户自有BTC USD-M多仓`0.009`、名义约`587.62 USDT`、钱包`203.06011455 USDT`、
  可用`66.0921174 USDT`、普通挂单0和两张既有BTC条件保护单；未撤改单，`private_api_order_attempted=false`、
  `exchange_mutation_attempted=false`、`live_orders_allowed=false`。只读观察hash=`ac00bd58...7757`，Dashboard positions=
  `available_readonly/exchange_account_observation`；平均成本、Qount订单事实、PnL、NAV和ledger reconciliation因当前仓位未进入
  RuntimeLedger继续为unavailable，不再伪装成空仓。策略注册表仍保留`minimal_live`历史治理状态，但当前
  `execution_status=blocked/live_orders_allowed=false`，live/forward timers保持`disabled/inactive`。

- **日报和微信已重新闭环。** 新日报`29be08b6...6d8d`明确区分2026-07-23历史ledger与2026-07-27交易所只读BTC观察，
  不再声称当前账本空仓对账通过；报告hash=`fc3f2e36...2018`。两条过期微信job已原子转为
  `DEAD_LETTER/notification_delivery_superseded`，新job=`c8f11bf6...f4c9`一次投递`DELIVERED/SUCCEEDED`，response hash=
  `b10445d8...bdf1`。OpenClaw gateway健康，无需重新扫码；该回执证明腾讯接口接受，不代表客户端已读。notification retry、
  Dashboard publisher和Daily Intelligence timers均已恢复`enabled/active`。已验证Dashboard publication=
  `cee6e7dc...a656`、hash=`7533ccb7...e166`，restore drill与system health均为healthy。

- **2026-07-27 `0.2.21`包含“readiness + 一次性arm后开事件专用开关”的FOMC live能力。**
  新增独立`fomc_live.py`和`run_fomc_live.py`：私有账户预检绑定Binance USD-M账户scope、one-way、isolated、实际leverage、
  手续费、余额、持仓、普通单/条件单和API权限；readiness绑定事件、信号candle identity、账户scope、精确数量/止损/最大名义与
  `<=5 USDT`压力损失；短时单次arm再绑定token hash、batch/plan hash和owner authorization hash。只有
  `QOUNT_FOMC_LIVE_ENABLE=true`、arm ID confirmation、token、未消费arm和新鲜信号/账户全部一致时才允许一次MARKET入场。
  MARKET必须由order与逐笔trade/USDT fee确认，随后提交并回读原生`STOP_MARKET closePosition`；保护失败会HALT并立即尝试
  幂等`reduceOnly MARKET`平仓，只有账户回读为flat且条件单清空才记`halted_emergency_flattened`。受保护持仓周期回读保护状态，
  到`2026-07-30 11:00 UTC`取消保护并强平，无法证明退出则`halted_uncertain`。有限窗口live service/timer已部署但保持
  `disabled/inactive`；本轮没有读取VPS私有账户、没有生成arm、没有写生产env、没有调用订单接口。聚焦回归为47 tests OK。

- **2026-07-27 10:38 CST Dashboard生产只读复核：发布健康，访问被认证挡住。**
  `qount-dashboard-publisher.timer=enabled/active`，最近oneshot `Result=success/ExecMainStatus=0`；最新发布
  `publication_id=3a58fee6...d6be`、`publication_hash=27b1c01b...468`，12份JSON均存在，restore drill通过，
  `system_health_status=healthy`。公网`https://qount.alyaloale.com/`在HTML之前返回Cloudflare透传的HTTP 401和
  `WWW-Authenticate: Basic realm="restricted"`；仓库Caddy合同本来就对整站启用Basic Auth。因此`#/live`“打不开”与数据是否更新
  是两件事：publisher正在更新，未提供Basic Auth凭据的浏览器不会拿到前端。当前不取消认证，避免公开账户、仓位、订单和告警数据。
- **2026-07-27 `0.2.18`补齐FOMC现金窗口告警并已部署。** `cash_only_from <= observed_at < freeze_at`时，watcher保持
  `SCHEDULED`和冻结前零网络，但在共享NotificationStore打开一条可去重`fomc_event_cash_only` WARNING；冻结开始后该incident自动
  RESOLVED，并由freeze incident接力。VPS临时库两次轮询只生成1条OPEN告警，未向生产库制造未来告警；前端类别和cache key已同步。

- **2026-07-27 FOMC v0.2不可下单标准链和公共行情watcher已随`0.2.17`部署VPS。**
  固定事件定义绑定Fed 7月官方日历、BTCUSDT USD-M、17:30 UTC冻结、18:00声明、22:30开始观察、次日04:00停止入场和
  11:00强制退出边界。`fomc_runtime.py`冻结72h range、ATR14、V20和3/3 pivot，首个完成1h方向锚不可反转；
  `fomc_adapter.py`输出有符号`MarketSnapshot -> StrategyIntent -> allocator -> RiskDecision -> OrderPlan`，入场MARKET与原生
  `STOP_MARKET closePosition`均只作计划，未链接账户或manual arm时不可执行；`fomc_watcher.py`只调用公开market/OHLCV/ticker/funding，
  以`0700/0600`保存不可变freeze/run/decision batch并写Dashboard告警。systemd模板无EnvironmentFile、显式移除Binance key/arm/live环境，
  仅覆盖本次事件窗口。`qount-fomc-shadow.timer=enabled/active`，首次自动运行是上海时间`2026-07-30 01:00:13`；部署smoke为
  `SCHEDULED`、result=`019019be...3727d0`，且`orders_authorized=false/private_api_used=false/exchange_mutation_attempted=false`。

- **2026-07-26 owner基于两份策略评估把200 USDT个人事件右侧策略升级到v0.2，但未授权任何订单。**
  `SmallAccount-FOMC-RightSide-v0.2`仍为独立`draft/research/shadow-only`线；v0.1只作同事件冻结对照。资金合同不变：
  初始权益200U，首个受保护live闭环风险5U，常规单笔和总并发压力风险上限10U，20U停止、32U紧急flatten、40U灾难红线，
  同时最多一个crypto-beta方向；BTC USD-M仍限isolated 5x/40U保证金/200U名义，SOL现货只作互斥备选且名义上限40U。
  新信号用完成1h K作方向锚、完成15m K作放量突破和最多8根回踩重收；多头回踩不得低于`H0`、空头不得高于`L0`，
  计划成交仍受线外`0.25ATR0`、全成本`>=2R`和保护门约束。BLACKOUT约06:00-06:30后才可能结束，12:00后不新开、
  19:00前全平；`+2R`减1/3后尾仓采用净`+1R`底线与完成1h最有利收盘`1.0ATR`单向ratchet。
  纯信号、风险和尾仓函数均无订单副作用；生产`0.2.17`已补event definition/freeze、标准`StrategyIntent` adapter与原生保护单
  `OrderPlan`，但没有真实账户快照、manual arm、venue dispatcher、持仓管理或强平执行接入，因此仍只能用于research/shadow。
  当前`orders_authorized=false/paper_or_live_allowed=false`，不恢复MiniTrend timer，不访问VPS私有API。

- **2026-07-26 本地标准合同已升级为跨资产、有符号 exposure，但没有扩大生产权限。** 新增 canonical `InstrumentId` 与带
  source hash/observed time 的 `ProductCapability`，将 crypto spot/perpetual、Direct Stocks/ETF、tokenized equity 和 equity perpetual
  分为不同产品身份；`StrategyIntent` v2允许负权重，allocator/risk/planner/ledger/virtual runtime 的gross、限额、成本均按绝对
  exposure，PnL/权益/funding按有符号仓位处理。开空必须显式匹配 exact instrument 且`short_allowed=true`；减既有空头仍允许，
  跨零翻转强制 reduce-first。Direct Stocks `BUY_SELL`只表示可买/可卖库存，SELL为close-only，不能推导成short。
  Binance Stocks官方schema的规则、订单字段矩阵、精度/session/fractional/disclaimer/tokenize校验已实现为无HTTP副作用的纯契约；
  官方16端点没有闭合权威holdings/`available_to_sell`读取，账户资格、地区、免责声明状态和symbol availability也未从eligible route核验，
  因此自动执行保持阻断。官方文档已日期化保存在`state/reference/binance-developer-docs/2026-07-26/`。

- **2026-07-26 owner因策略长期未产生订单，决定停止MiniTrend实盘。** VPS
  `qount-mini-trend-live.timer`与`qount-mini-trend-forward.timer`均为`disabled/inactive`，live timer无下一次计划运行，
  production cron仍为0 entry；旧oneshot失败标记已用`systemctl reset-failed`清理为`inactive/dead`、`Result=success`，journal保留，
  没有启动、重启或手工触发订单路径。停用后的私有只读preflight为
  `account_preflight_pass`：USD-M可用/钱包余额=`464.0942153 USDT`，one-way、TOP3 isolated 1x、持仓0、普通挂单0、
  unmanaged position 0，且`mutating_account_method_attempted=false/private_api_order_attempted=false`。持久证据为
  `/root/qount/state/research_runs/20260726T121029Z-mini-trend-um-pilot-preflight-qount-stop-preflight-20260726/`
  `qount-stop-preflight-20260726.json`。Phase B readonly、Dashboard publisher和Daily Intelligence继续独立运行，不授予交易权限。
- **2026-07-26 Alpha Agent与生产Daily Intelligence LLM已切换到火山方舟Coding Plan。** Console名称`glm-5.2`
  使用API模型ID=`glm-5-2-260617`、base URL=`https://ark.cn-beijing.volces.com/api/coding/v3`、provider=
  `volc_coding_plan`、输出上限=`8000`。Coding Plan走Chat Completions `json_object`；仅兼容“单一JSON代码围栏且无前后附文”，
  去围栏后仍执行严格五字段、简体中文、越权词和本地报告合同校验。凭据只在Mac仓库外`~/.qount/alpha-agent.env`及VPS
  `/etc/qount/intelligence/coding-plan.key`，后者为`0600 root:root`；仓库、artifact和日志均不含密钥。本机官方feed单角色
  artifact=`/private/tmp/qount-coding-plan-smoke-20260726-r4.json`、SHA=`4545fe5b...fb8`、status=`ok`；VPS不落盘中文
  单角色探针同为`ok`。Mac/VPS聚焦回归各`28 OK`，部署的LLM、runner、unit与两份测试文件SHA逐项一致。
  `qount-daily-intelligence.timer`保持`enabled/active`，下一次自然调度才运行完整六角色、归档和个人微信流程；本次没有手工补发日报。

- **2026-07-26 `stablecoin_liquidity_impulse_v1` 三源 no-PnL G0 已通过 source/clock/semantics 门，formal strategy trial 仍为 148。**
  新不可变 collection `v0.3/20260726T101608Z` 保留 USDT Ethereum/USDT TRON/USDC Ethereum
  `6,893/2,007/2,710,040` 条 lineage，manifest=`859a4904...458f`；47 个成员、12 个 gzip 的成员 SHA、记录数和解压
  SHA 已独立全量回读。USDT Ethereum owner proof 完整扫描 deployment..activation 的 `111` 个块和 `11,199` 笔交易，
  核验 `2` 笔 owner->token receipt，并从 Sourcify ABI/verified source 完整枚举 multisig `5,544` 个 transaction slot；
  `5,191` 个已执行，执行的 `transferOwnership` 为 `0`。activation/observed 两高度链上 runtime 全字节相同；与 Sourcify
  `runtimeMatch=match` 的差异仅在 Solidity CBOR metadata，可执行 bytecode SHA 精确一致。owner proof file SHA=
  `14abab4a...fcc6`，由三份 raw sidecar 重建后的 canonical hash 完全一致。
  TRON 的 `991` 条零金额 `Transfer`（988 zero-address、3 treasury）按预登记合同保留 raw/finality lineage，但不进入
  economic flow/count；因此 lineage/economic/zero-excluded=`2,007/1,016/991`，treasury=`383/380/3`，三者均闭合。
  三源 semantics、ABI/proxy/owner history 与 exact availability 全为 true，remaining blockers=`[]`。
  冻结 G0 得到 `376/376` 周锚点、`209/209` aggregate 对照、classification coverage=`1.0`，mint/burn/treasury/
  cross-chain/unknown=`1,688,417/1,028,517/679/18/0`，transaction semantic duplicate=`318`、跨链 cluster=`9`。
  marginal flow 仍不等价 aggregate supply（Spearman=`0.6479546769`、R²=`0.4186931641`、offsetting ratio=`1.0`），
  exact delay 中位/p99/max=`768/979/1701s`。verdict=`pass_to_market_state_design`；bundle=`e725e66a...95b7`、
  manifest=`3b1b0c3e...3252`、result=`d72b82d0...f760`。本轮仍未读市场价格/PnL/方向/权重，family trial=`0`，
  `candidate_pnl_ready=false`，不产生 promotion、paper/live 或订单权限。v0.2/r2 及更早失败 bundle 原样保留为历史证据。

- **2026-07-25 `liquidity_capacity_meta_v1` capacity calibration 首轮完成（成本基础设施，非策略候选）。**
  新增 `src/qount/mini_trend/liquidity_capacity_calibration.py`（冻结 protocol + 可单测纯函数，21 单测 OK）与薄脚本
  `scripts/research/run_liquidity_capacity_calibration.py`，消费已通过的冻结 G0 artifact（SHA `fa02ed8b...bf95`，10/10
  `pass_to_capacity_calibration`），产出不可变 scorecard `state/research_runs/20260724T184308-liquidity-capacity-meta-calibration/`
  （SHA `bad32d63...72b4`，contract `01f3c651...12a9`，`0700/0600`）。成本模型：half-spread=CS/2、impact=`amihud_x_1e6·N/100`
  （线性 Amihud 上界代理）、friction=half-spread+impact（不含费）、total 另加 Binance UM 官方 taker 4bps。
  **读数**：①robust participation-only 全宇宙容量≈**21.3M USDT**（LTC 绑定=213M 日成交额×1%）；②Amihud 冲击可忽略——
  1% participation 下仅 1.7–6.6bps，非绑定约束；③**CS 日高低价差代理对全部 10 币系统性高估**（half-spread 11.6–44.5bps
  vs 真实 perp <1bp），使 5/10/25bps 成本预算容量塌成 0，属 proxy-limited 而非 liquidity-limited。**cost-error**：
  无真实 fill/盘口，ground_truth 不可得，已如实标记；下一步是 WSL 侧采集真实 book depth 校准价差并做全逐日滚动/分段容量。
  全程 `orders_authorized=false`、无方向、无 PnL、`candidate_pnl_ready=false`；`data_role=consumed_historical_discovery_pool`，
  未触碰 VPS/paper/live。它服务其它研究线的成本口径，本身不是收益证据。formal strategy trial 计数不变（仍 148）。

- **2026-07-25 owner将主动研究优先级切换为加密因子拓展；formal trial已推进到148。**
  `multi_speed_trend_v1`家族3/3完成并关闭（Trial 145/146/147均REJECT，主指标全败）。
  `crypto_vol_crisis_state_v1` Trial 148也REJECT（尾残差恶化）。当前只在本地`research_sandbox`推进
  横截面G0、危机状态、funding拥挤、流动性容量和OI/flow前向采集；不恢复旧失败参数搜索，不访问VPS、私有API、timer或订单路径。
  - Trial 145方向一致性：8/9门，CAGR 19.25%<Base 19.88%，maxDD 11.20%，beta-residual 10.91%，turnover 108.91。REJECT。
  - Trial 146连续z-score：6/9门，CAGR 13.06%，maxDD 21.51%（恶化5.33pp），beta-residual 5.61%，turnover 60.09。REJECT。
  - Trial 147分层状态机：7/9门，CAGR 15.90%，maxDD 9.70%（三试最优，改善6.48pp），beta-residual 7.98%，turnover 70.04。
    REJECT，触发family复盘。复盘结论：三试主指标全败，降险是低效降险（turnover+38%，Sharpe↓），按"不救援"关闭family。
  - Trial 148 `crypto_vol_crisis_state_v1` 1/3：三信号RiskMultiplier（下行半方差+相关性跃升+funding极值），5/6门，
    唯一失败`tail_residual_improvement`（三基线尾残差均恶化）。REJECT。bundle=`8ea84158...020cc`。
  - **G0最终结果（10/10币，WSL计算）**：breadth有效广度`1.660`<2.0（特征值广度2.511但相关广度仍不足）、
    PC1`0.615`<0.85（通过）、downside广度`1.675`、10币共同窗口2020-09-23..2026-06-30共2102根。
    分段广度：2020-21=`1.890`（最接近2.0）、2022-23=`1.409`、2024-26=`1.397`。
    liquidity G0在kline-inferred rules下`pass_to_capacity_calibration`（rules覆盖1.0、10币中位成交额213M-12.5B USDT）。
    **结论**：10币相关广度1.660<2.0是真实容量结论（与LiquidTrend10 1.438一致方向），按规则**不放宽广度门、不扩币救援**。
    breadth/dispersion family和cross_sectional_residual_momentum被阻断；liquidity family通过可进入capacity calibration。
  - 全程`candidate_pnl_ready=false/promotion_evidence=false/orders_authorized=false`。

- **2026-07-25研究计划已完成文档级全面扩展并已执行到Trial 148。** 当前formal strategy trial为148。
  `multi_speed_trend_v1`家族3/3关闭；`crypto_vol_crisis_state_v1` Trial 148 REJECT；G0中间结果7币广度1.474。
  - P0/P1历史低频篮子：multi-speed Trial 146/147、breadth/dispersion、liquidity capacity、残差横截面、危机状态和
    funding crowding；所有新family先写ResearchCard/G0，保持Base、TOP3 beta residual、成本和既有负证据为控制。
  - 前向结构篮子：OI/flow、basis curve、liquidation cascade和cross-venue price discovery。Binance官方模块化connector
    当前定义OI history仅最近1个月，basis、taker和long/short ratios仅最近30天，因此只能从当前起append-only，不能伪造长历史。
  - 外部PIT篮子：stablecoin边际流、token supply事件、network adoption quality和venue-rule事件；aggregate stablecoin supply、
    hashrate、DVOL、price-only ML/HMM/GRU等本地负证据继续保留，新proposal必须改变信息集、vintage或经济目标。
  - execution fill/cost只研究可执行摩擦；options surface继续capacity blocked；regime allocator必须等待至少两条独立冻结
    Standalone NAV。详细机制、数据时钟、主指标、kill tests、试验预算、来源矩阵和90天波次见
    `docs/research-advancement-roadmap.md`与`docs/crypto-portfolio-system-plan.md`。

- **2026-07-24 CTA-R selection-free 冻结成本重认证完成；证据保留，当前冻结为次级研究旁路。** 新脚本
  `scripts/research/run_cta_r_revalidation.py`不再把 R0 advancement 的单一`20/100` ETF探索结果当作 CTA-R；它重新使用历史
  CTA-R 的固定8 ETF、`63/126/252`多周期、long-only、effective gross `<=1`合同，并生成manifest-last不可变bundle
  `9c08be9cdeb1a0c3d9416af9a4f7cb41eda4a17792decad24d5cee72b8725be1`。输入是当前压缩源的8标的共同窗口
  `2014-01-15..2026-07-22`、3037行，dataset=`2d6e7459...f7c8`；它是已消费历史discovery，不是独立OOS。
  - 冻结成本改为A股ETF账户的10bps/边（佣金3bps + 半价差2bps + 滑点5bps）。selection-free ensemble为
    Sharpe `0.9197` / CAGR `8.65%` / maxDD `-8.23%` / 5折全正；past-only walk-forward为
    `0.7403` / `7.70%` / `-8.69%` / 5折全正；fixed先验为`0.8568` / `9.12%` / `-9.55%` / 5折全正。
  - 20bps/边双倍成本下，walk-forward仍为Sharpe `0.6984` / CAGR `7.22%` / maxDD `-8.73%`，4/5折为正；
    ensemble/fixed仍分别为Sharpe `0.8445/0.8238`。固定单配置完整runtime的effective breadth=`3.0844`、平均gross=`0.9904`，
    独立NAV复算误差`1.78e-15`。
  - verdict=`retain_for_discovery_revalidation`，但`candidate_pnl_ready=false`、`promotion_evidence=false`、
    `orders_authorized=false`。未闭合项是历史point-in-time membership、QDII溢折价/跟踪误差、券商最低佣金与真实spread/fill成本、
    额外一根延迟/漏单压力、资产类别与regime贡献，以及真正新时间证据。R0 advancement的CTA-R `1.56x`只保留为单规则探索，
    不再作为CTA-R候选主读数。
  - 2026-07-25 owner的加密优先指令取代了此前排序。CTA-R不被拒绝，继续保留
    `retain_for_discovery_revalidation`证据和PIT/成本/压力清单，但暂停主动扩展；C×D同样降为冻结旁路。Base v0.2
    仍只按既有100 USDT权限等待自然成交；研究artifact不给其它sleeve真钱权限。

- **2026-07-24 R0 Round 1-4 修正完成：RETAIN 降级为 retain_for_discovery_revalidation。**
  四轮修正消除了 CandidateConfig 漂移、carry 账户模型缺陷、硬编码 kill tests 和日期错位。所有工作保持 `orders_authorized=false`。
  - **Round 1 (CandidateConfig)**：新建 `CandidateConfig` frozen dataclass（`config_hash`），三脚本消费同一配置。advancement 默认 `regime_sma` 从 200 改为 0（与 runtime 一致）。decision `--runtime-bundle` 改为 required。
  - **Round 2 (Carry 模型重写)**：Signal NAV 从 delta-neutral PnL 改为 basis 收敛信号；Standalone NAV 从 gross 2x 复合改为 gross 1x 加性（weight=0.5，无隐含再平衡）；collateral/tail source 从 `"estimated"` 改为 `"unavailable"` -> `cost_incomplete=True`。
  - **Round 3 (Kill tests 真实化)**：kill test 2 从硬编码改为独立 NAV 对账（独立代码路径，容差 ≤ 1e-6）；kill test 3 从硬编码改为 R0-DATA 可用性 + funding gap 检查。新增 carry baseline NAV 验证。决策从 RETAIN 降级为 **REVISE**（kill test 3 FAIL: R0-DATA 不可用）。
  - **Round 4 (日期对齐 + artifact 完整性)**：三币等权从 `min(len)` 数组截取改为日期交集对齐。CTA-R 结果从 console-only 改为 artifact 成员。crypto source hashes 补全。
  - **修正后 R0-RUNTIME** `7e827743c98b861568aca71b166f14adc852499a58a962bf7e146514165d109d`（7 members，2020-01 至 2026-06）：
    趋势腿 Signal 8.46x / Standalone **4.48x**（maxDD -50.0%，cost 0.6369，cost_incomplete=False）；
    carry 腿 Signal **1.00x** / Standalone **1.38x**（cost -0.3849，cost_incomplete=**True**）。
    **candidate_pnl_ready=False**（carry cost_incomplete=True）。`config_hash=b23257abd7e7...`，`regime_sma=0`。
  - **修正后 R0-DECISION** `a26fba9ae4d40048b88cb5836a0989a4b4339a5da9fe396fa9ce483d18b73b76`（5 members）：
    runtime_bundle_verified=True（closes/funding/trend NAV/carry NAV/config_hash 五项匹配）；
    趋势腿 **REVISE**（kt1 PASS, kt2 PASS 独立对账, kt3 FAIL R0-DATA 不可用）；
    carry 腿 **REVISE**（同上）；CTA-R **BLOCKED**。
  - **修正后 R0-ADVANCEMENT** `443a4ebb64ce12d613bd4cb09ba15623a3eadff9974a81f4e2ad80450710d9d4`（6 members）：
    BTC beta-residual **alpha=+7.75%/yr, beta=0.47, R²=0.47**；
    3 币等权 NAV **13.40x** maxDD **-58.07%**（common_dates=2333, 2020-02-10 起，日期对齐）；
    CTA-R 等权 NAV **1.56x** maxDD -10.28% 年化 +7.26%（首次在 artifact 中）。
    source_hashes 含 crypto per-symbol (closes/positions/nav/funding)。
  - **回归测试**：R0 标准库 200/200 OK（含 27 candidate_config + 16 kill_tests + 7 alignment + 150 原有）。
  - **旧 bundle 处置**：`acb1a8c1...`（Round 1 runtime）/ `6a4e8f1a...`（Round 1 runtime，旧 carry）/ `1221bf3f...`（旧 advancement，regime=200）/ `44bcf024...`（旧 decision）保留为已消费 discovery artifact，不删除。
  - **v5 governance bundle** `47aa0e88...` 保留为已消费 discovery artifact（仍指向旧 `b90c6d...` runtime）。v6 governance bundle `28035b7e...` 已生成（绑定三个修正 bundle，`candidate_pnl_ready=False`，`supersedes=47aa0e88...`）。
  - **Round 6 深度验证** `2ff84b3f...`（2 members）：chronological folds **partial**（2/3 positive，2024-2026 段 NAV=0.78x -9.4% 年化）；cost sensitivity all_positive（funding 是主导因子，执行成本影响 <4%）；beta residual stability **partial**（11/23 窗口 alpha 为正，集中在 2020-2021 牛市）；new-data 22 bars available in 2026-07。
  - **验证结论**：趋势策略正 NAV 集中在 2020-2021 牛市，近期 2024-2026 亏损；alpha 不稳定（48% 窗口为正）；策略对 funding 成本高度敏感。支持 `retain_for_discovery_revalidation` 降级。

- **2026-07-24 R0 初步实现审计：工程底座已落地，候选结论尚未闭合。** 五步都已有对应代码、初步 bundle 或记录，且所有工作保持
  `orders_authorized=false`；它们是 `discovery_pool` 研究证据，不改变 Base 生产、路由、paper 或 promotion 状态。
  - **R0-DATA**：✅ `src/qount/research_data/` 已实现 lifecycle / availability / universe 合同。被 v5 记录引用的外置盘 bundle 是
    `b9fa27ec6938e0dd7dc4fd880ebce4e517f685058a3e7504565362417e2d2422`（报告 UM 846 symbols、721 active、27 个季度 revision）。
    ⚠ 本机没有该 bundle 的副本，且当前 `exchangeInfo` 只能证明观察时的状态；历史 delisting、状态变更和 spot listing 的 point-in-time
    证据仍须以历史 source snapshot / availability manifest 补齐。ETF 压缩源的 SHA-256 分别是
    `3593d47048409c717cf64faeaa0522001518beb228a5ab74ad7cd08224077f3b` 与
    `233f5f06c2ffbb3bdc5479d6883c8f8a767f8c13973e1cbea399825f8b7bd350`，尚未形成 CTA-R runtime artifact。
  - **R0-COST/NAV 与 R0-RUNTIME**：✅ 已有四类 `FrozenCostModel`、三 NAV 计算器及 BTC 初步 runtime bundle
    `b90c6d1569d2fcc099f39af1252a128e610c96146b2a22d828bf87d13469592f`（2395 UM bars、2393 spot bars、7119 funding；
    输入 close hash 分别为 `7c5b2f0214d1e659f5561ae673f73e52d063ab99a16a0c95a6bbe377fafa7f88`、
    `fced27cd3e544f6ad403075354329d7fdd59b19136dbf09a9e1fc7fc3ad98d89`）。⚠ carry 对空头正 funding 的现金流符号错误，且所有
    runtime summary 的 max drawdown 使用全样本最高点而非滚动峰值；因此初步 NAV、成本分解和回撤数字只可作为待重跑诊断，不能作结论。
  - **R0-RECORD**：✅ v5 bundle `47aa0e88c70d3d2dabe3dad2422b875b4f7e16c5c7de2d6247dfe9f5d7089af7`（11 members）已通过本机 manifest/member
    hash 校验，且固定 `orders_authorized=false`、`promotion_evidence=false`。⚠ manifest 的 `candidate_pnl_ready=true` 仅对应
    C×D 初步 runtime；同 bundle 内 CTA-R candidate 仍为 `candidate_pnl_ready=false` / `active_research`，不得写成全局候选就绪。
  - **R0-DECISION 与三线推进**：✅ 初步 decision bundle
    `d382f8e931d7a3cb9a4de99ee86cfdd4542a254ba3cd4528965683caaf0f6322` 和 beta-residual / vol-target / CTA-R 探索脚本均已生成。
    ⚠ decision 脚本没有消费并绑定 runtime bundle；三线脚本只打印结果，未写入 immutable artifact、输入 hash、参数、结果或 holdout role。
    先前的 `RETAIN` / `REJECT` / `BLOCKED` 以及 alpha、回撤和 ETF NAV 数字均为 provisional，必须在修复并重跑后才可保留。
  - **本次验证**：`PYTHONPATH=src ./.venv/bin/python -B -m unittest -v tests.test_research_data_lifecycle tests.test_research_data_availability tests.test_research_data_universe tests.test_research_data_cost_nav` 为 `110/110 OK`；
    测试尚未覆盖上述 funding 方向、滚动回撤、因果 vol-target 与三线 artifact 缺口。
  - **下一步**：先修复并测试 signed funding、rolling max drawdown 和无未来函数的 vol-target；再让 decision/advancement 读取已验证的
    input bundle 并写 manifest-last artifact；随后在同一冻结输入上重跑 C×D 和 CTA-R，重新评估 PIT coverage、成本、beta residual、
    单腿 NAV 与压力测试。任何结果仍只停留在 `research_sandbox`。

- **2026-07-23 Base 已完成 `0.2.15` 标准生产迁移。** `qount-mini-trend-live.service` 已改为
  `Qount Base standard-production 100 USDT live cycle`；新的 Base production store 强制验证标准 batch、registry=`minimal_live`、
  pre-dispatch ledger/reconciliation 和 legacy parity，再以不可覆盖迁移证据和可回读状态记录 production mode。VPS migration=
  `d3668938...d51b`，status=`37d49d70...b907`，latest live artifact=`3b4817f3...3a6a`；`0.2.15` arm 为
  `qmt-arm-edae15fc6e37c7a2902c`，旧 arm 已归档。验收 cycle=`completed`，0 market/0 STOP、无 exchange mutation、
  post reconciliation passed；账户`486.09421530 USDT`、TOP3全平、普通/条件挂单0、HALT absent。live/Phase B timers 均
  `enabled/active`，forward timer `disabled/inactive`，production cron 0。首单状态是`awaiting_natural_fill`、sample_count=0；
  timer 仅等待自然信号，绝不为归因样本下单。

- **2026-07-23 本地标准多sleeve runtime和R0 readiness证据已闭合研究入口，随后已用于 Base 标准生产 authority。**
  `src/qount/portfolio/virtual_runtime.py`已完整连接`MarketSnapshot -> StrategyIntent[] -> allocator -> PortfolioTarget ->
  RiskDecision -> OrderPlan -> RuntimeLedger -> virtual fills/fees/funding -> 三NAV -> three-way reconciliation`。固定两sleeve
  artifact位于`state/research_governance/runtime/d4faa121...48a80/`，result=`a98977dd...1672f`、runtime snapshot=
  `f69bea0c...c3447`，manifest-last、`0700/0600`、不可覆盖、全成员hash和audit hash chain均已回读；固定
  `orders_authorized=false/orders_routed=false/promotion_evidence=false`。`ResearchEvidenceReadinessRecord`与R0 v4 bundle把
  CxD/CTA-R实际历史family映射、代码/文档来源、已冻结的研究成本假设和缺失项机器化；真实historical lifecycle、账户/场所成本、
  当前数据IDs和候选Standalone NAV仍明确为partial/unavailable。最终R0 bundle位于
  `state/research_governance/r0/f5bfb3b5...6fa85/`，manifest=`05a303d4...c6bb3`；因此可开始数据工程和discovery，尚不可声称候选PnL或promotion。
  Base dispatcher同时已接入事件时点归因采集；只有自然market fill才生成report，当前仍无样本。

- **2026-07-23（标准生产迁移前）本地研究推进政策已改为非阻塞，生产当时仍保持 `0.2.14`。** Phase B的30个有效批次、每family
  3个formal trial、两个promotion sleeve和Phase顺序都只作为证据成熟度观测，不再阻止本地数据工程、discovery、
  virtual allocator或架构建设。Phase B schema v2输出`policy_mode=non_blocking_observation`以及
  `blocks_local_progress=false/blocks_research=false/blocks_allocator_development=false`，达到30只写milestone。
  CxD和CTA-R的v4 CandidateRevalidationRecord均为`owner_authorized_research/active_research`，允许historical/discovery/
  shadow/virtual研究，仍固定`orders_allowed=false`。单sleeve allocator与第4个formal trial已有回归覆盖。生产registry、
  UNKNOWN/HALT、幂等、对账、密钥隔离、真实订单arm和owner授权未放宽；该阶段本地全仓`1908/1908 OK`，本批未访问或部署VPS。

- **2026-07-23 Phase D 不可变证据、逐字段归因、Phase B观测和研究 R0 已随 `0.2.14` 部署。**
  新增 `CertificationArtifactStore`：在 `state/certification/runs/<run_id>/` 先写并回读 12 个完整成员，再写
  `bundle_metadata.json`，最后以 `manifest.json` (`CertificationResult`) 作为完成标记；目录 `0700`、文件 `0600`、
  不可覆盖、fsync、精确成员集、metadata/member hash、篡改/中断/敏感字段检测均有测试。venue client 现在保留
  原始 ccxt 响应；逐笔 trade 只按本认证的 client/exchange order ID 进入主/影子会计和 operational cost，未查询的
  funding/transfer 不再填零。`ExecutionAttributionReport` 升到 schema v2，每个指标独立记录
  `available|unavailable + missing_reason + source_hash`；`backfill-attribution` 可从经 manifest 校验的 Phase B
  `raw/trades.jsonl` 和 `income_history.jsonl` 只读回填 fee/fill/maker-taker/quantity，未捕获的到达中价和延迟明确为
  `not_captured_at_event_time`。部署版Phase B新增不可变cycle/progress/exit artifact；本地后续schema v2已把它改为
  non-blocking observation/milestone，机器字段包括`valid_streak`、`observation_target=30`、有效/失败批次、最新
  watermark/diff/venue/HALT、累计真实成交覆盖，且
  `orders_authorized=false/automatic_authority_change=false`。研究 R0 新增 GlobalExperimentRecord、历史 family mapping、
  point-in-time symbol lifecycle/universe、统一三 NAV/beta residual/cost/trial scorecard 和 CxD/CTA-R
  CandidateRevalidationRecord；部署时CxD为blocked、CTA-R为planned，本地v4现均为active research。Mac全仓
  `1892/1892 OK`，VPS production surface `343/343 OK`，新增聚焦测试 `80/80 OK`。本批只同步代码并安装依赖，
  未重启 timer、轮换 arm、修改 dispatcher、registry、cron 或交易权限，也没有任何新订单。

- **部署后生产状态。** 最新自然 Phase B archive（`2026-07-23T04:08:43Z`）为 shadow diff=0、venue=pass、HALT=0、
  TOP3 实际仓位全平；该 archive 的 `trades.jsonl` 和 `income_history.jsonl` 均为 0 条，因此首次认证 fill 仍不可回填。
  Phase B已有3个有效批次，观测进度为`3/30`；这不阻止任何本地工作。timer继续自然运行，不为累计样本手工补跑或提高频率。

- **架构计划完成度。** 单策略Base生产链、Phase A-D工程能力、不可变证据、逐字段归因、shadow accounting、venue provenance、
  allocator/governance底座、本地多sleeve virtual integration artifact和 Base 标准生产 authority 均已实现。剩余工作是实际候选研究：
  R0 historical lifecycle、账户/venue成本、当前数据IDs和候选Standalone NAV；以及未来真实多sleeve只在 virtual/shadow 层验证，
  不接入 Base 的 Binance 钱包。Base事件时点捕获已就位但自然fill归因仍无样本。这些是并行 backlog，不是本地研究等待门。

- **首次 Phase D 真实认证的证据限制已明确。** 2026-07-23 首次真实 fill/fee/归零是有效的场所执行事实，但当时脚本只把
  约 412 字节摘要落盘；12 个成员 payload/hash 只在进程内构造，不能追溯声称为已经持久化的完整不可变包。本批存储器只保证
  后续 run 的完整落盘，不能伪造首次 run 已丢失的原始成员。首次 fill 的 fee、price、quantity、maker/taker 等可证明字段等待
  下一次 Phase B 24 小时只读 archive 后回填；arrival mid、spread、完整 submit/ACK 时间点若当时未捕获，永久标记
  `unavailable/not_captured_at_event_time`。不得为了补证据重复真钱认证。

- **2026-07-23 Phase D 真实最小认证首次执行成功。** owner 授权后在 VPS 执行首次真实认证：BTCUSDT /
  `real_ack_fill` 语义，真实 MARKET buy 0.001 BTC -> MARKET sell 归零。`completed=True`、
  `final_position_is_zero=True`、CertificationResult 在内存中引用 12 个 artifact 成员、arm 已消费（`status=used`）。真实 buy/sell 各 0.001 BTC
  @ ~65394 USDT，fee 0.0654 USDT（认证成本独立归档不进 Base PnL，在 max_fee 1.0 内）；余额
  486.1597 -> 486.0942（-0.0655 = fee）；归零确认 active positions=[]。认证订单用独立 `cert-xxx`
  client_order_id，不影响 Base live（Base 权重 0/0/0 全平）。§9 完成标准：artifact 完整 ≠ Base 扩容资格，
  Base 当时仍是唯一真钱策略。详见 [trading-system-evolution-plan.md](../trading-system-evolution-plan.md) §16.5。生产状态`0.2.13`不变。

- **2026-07-23 Phase D 真实认证工程基建就绪。** 新增 CertificationArm（`src/qount/certification/arm.py`，
  独立、单次、带失效时间的 0600 arm，不复用 Base arm/token）+ RealVenueClient（`real_client.py`，连真实
  Binance USD-M，`submit` 受 arm 门控 fail-closed，`query`/`cancel` 不受门控以支持归零恢复）+
  `phase_d_real_run.py`（make-plan/make-arm/dry-run/run/scorecard；当前本地版本在首个真实 submit 前消费 arm，
  失败保留证据不归入 Base）。owner 已确认授权参数（BTCUSDT / real_ack_fill / 120 USDT / 1.0 USDT / 120s）。
  dry-run 验证完整流程（12 artifact + 零仓位 + completed）；Mac 全仓 `1865/1865 OK`（+28 新测试）。
  这是首次执行前的历史基建记录；首次真实认证随后已按上一条完成。详见
  [trading-system-evolution-plan.md](../trading-system-evolution-plan.md) §16。生产状态`0.2.13`不变。

- **2026-07-23 Phase C 两个 FAIL 已修复、真实 testnet 4/4 PASS、Phase D 合同就绪。** §3.4 验收矩阵两个 FAIL 已修复：
  ① stop_algo--TestnetVenueClient query/cancel 对 STOP_MARKET 切到 Algo 端点
  （`fapiPrivateGetAlgoOrder` by `clientAlgoId` / `fapiPrivateDeleteAlgoOrder` by `algoId`），
  submit 检测 `info.algoId` 记录 algo meta；② client_id_idempotency--CertificationRunner `submit_order`
  重复 `client_order_id` 时 fail-closed 阻断（`duplicate_client_order_id_blocked`），不再转发第二单到
  不强制幂等的 testnet。local gateway 与真实 Binance USD-M testnet 均 4/4 PASS、GATE: PASS；
  Mac 全仓 `1837/1837 OK`（+10 新测试）。Phase D 合同层已就绪（`real_minimum` 类型 + `real_pending_owner`
  状态 + 6 个 `real_*` 语义），`phase_c_testnet_run.py real-plan` 生成 draft plan 模板
  （`orders_authorized=false`、不下单）。Phase C 前置随后通过，独立 owner 授权后的首次 Phase D 真实认证见上方
  当前事实；不重复该语义。详见 [trading-system-evolution-plan.md](../trading-system-evolution-plan.md) §15。生产状态`0.2.13`不变。

- **2026-07-23 Phase C（testnet 认证）基建与首轮实测完成。** owner 已授权 testnet mutation。
  Phase A 的"积木"扩展为"胶水"层：CertificationRunner（VenueAdapter Protocol 统一 local gateway + testnet，
  Plan->Run->Event->Result 全链路，12 artifact 成员 + `completed` 计算判定）+ TestnetVenueClient（ccxt Binance
  testnet）+ Gateway §3.4 补全（SymbolRules rounding/filter + funding fixture）+ `build_testnet_exchange`（手动设
  testnet URL）+ `phase_c_testnet_run.py` 脚本（local-run/testnet-run/scorecard）。新增2源文件+1脚本+2测试文件，
  Mac全仓`1827/1827 OK`。对 Binance USD-M testnet 跑 §3.4 必须矩阵4项：rounding_filter PASS、crash_recovery PASS、
  **client_id_idempotency FAIL**（testnet 不强制 `newClientOrderId` 唯一性）、**stop_algo FAIL**（STOP_MARKET 走
  Algo Order 服务，常规端点查不到）。GATE: FAIL（2/4），失败为真实 testnet 行为差异非代码 bug。详见
  [trading-system-evolution-plan.md](../trading-system-evolution-plan.md) §14。生产状态`0.2.13`不变。

- **2026-07-23 Phase B（只读生产并行）管道建设完成、timer 已安装、batch #1-2 验证通过。** owner 已授权 VPS 只读并行和
  `qount-phase-b-readonly.timer`。Phase A 的纯函数"数学引擎"扩展为"管道"层：shadow accountant 抓取器+归档器+编排层+
  主账本独立提取器+HALT 旁路观测+venue snapshot 抓取器+统一脚本入口。新增1个独立包、6个源文件、5个测试文件、61条新测试；
  Mac全仓`1783/1783 OK`。`qount-phase-b-readonly.timer`每日UTC 04:00自动运行(live timer 03:20后40分钟)，
  batch #1手动验证+batch #2 timer触发验证均通过：shadow diff=0 block、venue=pass、halt=0 events。
  当时按旧命名记录为30批次“退出门”2/30；当前政策只按非阻塞观测进度读取。

- **2026-07-23 Phase A（架构演进合同与离线认证）已全部完成。** 按trading-system-evolution-plan.md §9 Phase A交付7项：Certification
  合同(CertificationPlan/Run/Event/Result)、ExecutionAttributionReport、HALT三层分类(operational/strategy/portfolio bypass observer)、
  VenueCapabilitySnapshot+changelog diff、独立shadow accountant(重建positions/NAV+diff)、本地venue gateway故障注入器(ACK loss/
  partial fill/crash恢复)、import boundary测试+Settings/ResearchSettings类型隔离。新增4个独立顶层包(`certification/`、`halt/`、
  `venue/`、`shadow_accounting/`)、18个源文件、7个测试文件、161条新测试；Mac全仓`1722/1722 OK`，现有golden hash不变。
  全部离线、`orders_authorized=false`、未访问VPS/私有API/交易所/订单接口；生产状态`0.2.13`不变。

- **2026-07-23 owner要求形成生产架构优化和研究推进两份新路线。** 架构路线接受独立execution certification、
  shadow accountant、Operational/Strategy/Portfolio三层HALT和venue capability provenance，但只授权设计与离线验证；
  真实最小认证仍需逐次owner授权。研究路线现把edge储备重认证列为高优先级：C×D只作历史组合数学候选，CTA-R只作跨资产
  selection-free重新认证候选，随后才是多速度趋势、执行经济学和条件性新family；旧X4/C×D/RV-C/CTA-R结果不继承promotion资格，
  carry/short/杠杆/VRP当时仍关闭，唯一真钱策略和生产状态不变。

- **2026-07-22 0.2.13已完成VPS部署与受控生产验收。** 最近已完成UTC日线硬门、LLM flat仓位计数和中文越权扫描之外，
  部署探针还发现并修复了`latest_date`字符串与`datetime.date`比较，以及live wrapper按历史completed状态错误刷新当前arm绑定两个问题。
  最终release commit=`89be296...0f4`，provenance=`8141d31a...f205`；Mac全仓`1561/1561 OK`、VPS production
  `338/338 OK`，compileall、Bash syntax、`diff --check`与高置信凭据扫描通过。最终run=
  `/root/qount/state/mini_trend/forward/runs/20260722T133356Z`，decision date=`2026-07-21`、BTC/ETH/BNB权重`0/0/0`；
  live artifact=`live_dispatch-20260722T133549Z.json`、SHA=`ae8cdc96...0900`，status=`completed`、0 market/0 stop、
  `exchange_mutation_attempted=false`，live与标准reconciliation均passed。账户`486.15970914 USDT`、全平、普通挂单0、
  one-way/isolated 1x、HALT absent、unresolved 0；live timer=`enabled/active`，forward timer=`disabled/inactive`，production cron=0。

- **2026-07-22 LLM复盘已完成问题审查和部署后验证。** 正式日报`38985fe5...50d5fc`生成于0.2.13部署前，报告hash=`d42c851d...9e68`，pipeline=`complete`、evidence=`sufficient`、
  status=`attention_required`；7份一手来源、TOP3行情、冻结RuntimeLedger均已归档，6个角色完成，策略/红队/总编因缺少事件窗口、
  独立成交和历史容量返回`needs_research`。5个ResearchProposal的`g0_status=blocked_history_capacity`，全部
  `orders_allowed=false/live_changes_allowed=false`，不能作为信号、参数或盈利证据。微信通知job=`94dd8f...5c5d9`为
  `DELIVERED/SUCCEEDED`；这只证明业务回执，不代表研究结论有效。旧报告把三个零数量symbol槽位误写成“3个持仓”；
  0.2.13隔离、无通知复跑已确认`position_count=0`、误报文本0条，5个提案仍全部G0 blocked且禁止订单/live修改。
  旧正式artifact保留历史证据，不原地重写；下一次定时日报自然使用修复后的代码。

- **2026-07-22外置盘已完成保护性恢复并重新开放确定性研究。** 在确认WSL无其它任务后先关闭WSL，把
  `E:\qount_data`完整备份到全新目录`D:\qount_data-recovery-20260722T120000Z`：`robocopy`返回码`1`，
  `FAILED=0`、`Mismatch=0`，源/目标均为`14,214`个文件、`34,096,177,913` bytes，两份逐文件SHA-256 manifest
  自身hash同为`a31da6af...b9339`。随后`chkdsk E: /f`成功，未发现文件系统问题、`0 KB` bad sectors；卷最终
  `HealthStatus=Healthy`、`OperationalStatus=OK`且dirty bit未设置。修复后再次对`E:\qount_data`全树逐文件读取，
  缺失、新增、长度和内容hash差异均为`0`，审计为
  `D:\qount_data-recovery-20260722T120000Z.post-chkdsk-audit.json`。WSL `/mnt/e`已恢复可写挂载，scratch/state拓扑正常；
  核心研究依赖可用，可选LightGBM因系统缺`libgomp.so.1`暂不可导入且不参与当前冻结复跑。存储、pilot projection/dispatcher、
  Daily Intelligence和Alpha Agents聚焦回归`40/40 OK`。`D:`恢复备份必须保留；后续只按外置盘canonical输入和WSL ext4
  scratch推进，LLM的5个G0阻断提案仍不能替代费用、funding、滑点、beta residual、回撤、区块Bootstrap和时间顺序holdout证据。

- **2026-07-22 owner-approved良心云公开数据代理已补齐Funding Veto真正前向输入。** 首次隔离core误用2026-06-01
  到期的测试副本，TLS返回unexpected EOF；现从当前良心云profile结构化派生47个真实节点、剔除3个流量/到期伪节点，
  主Clash配置不变。仓库外`QOUNT_LIANGXIN_PROXY_URL`文件权限`0600`，URL/token未进入repo、artifact或外置盘，且未使用
  苏菲家宽代理。TCP、`example.com`和Binance funding公共接口均通过后，刷新artifact
  `20260722T141039Z-um-shadow-input-refresh-liangxin-current/`达到TOP3 `3/3`、各64次结算、108 files、0 unavailable，
  dataset manifest=`b6f6aab8...ca05`。原v0.2 preregistration、Base、state-decay、50%阈值和成本合同均未改；离线回放
  `20260722T141236Z-um-funding-veto-shadow-forward-liangxin/`得到2个完整pair、verdict=`collect_shadow_forward`。
  两路径都是`bear_cash`，各0 active bar/0 order/0收益/0回撤，无veto和状态分叉；当前只证明数据与双状态journal闭环，
  仍缺60个完整pair、每路径10个active bar和至少1次veto，不构成盈利、promotion、paper或live证据。
  同一已消费历史合同在WSL离线精确复跑：Funding Veto全窗收益/Sharpe/maxDD为
  `+88.950393%/0.965235/18.105121%`，交易成本`34.003616 USDT`、funding PnL `-43.423732 USDT`、平均/最大gross
  `0.216925/0.903255`；对BTC 1x和TOP3等权1x的beta/复合残差分别为`0.151612/+59.459570%`和
  `0.147028/+55.411085%`。剔除新增beta字段及时间/路径元数据后，新旧报告规范化hash同为`d4bec779...00d91`。
  固定20日块、5000路径Bootstrap也精确重现，收益/Sharpe/更低回撤胜率`58.90%/86.82%/75.72%`，收益增量中位数
  只有`+0.462935pp`；规范化hash同为`6c00d310...f1c81`。这些仍是`consumed_historical_discovery_pool`，trial不增加，
  Base v0.2当时继续是唯一真钱策略，Funding Veto继续shadow-only；下一有效证据只能来自补齐官方funding后的原冻结时间顺序前向。

- **2026-07-22 0.2.12已完成全套恢复验收。** `0.2.11`实机live cycle暴露一个自检循环：live oneshot运行期间
  `qount-mini-trend-live.service`的正常`activating`态被health probe误判为execution block，导致刷新后的readiness只剩
  `system_health_ready`失败。`0.2.12`将systemd `activating/deactivating`纳入合法过渡态，仍保持forward timer
  `activating`为阻断，并新增正反两条回归；本地全仓`1553 OK`，VPS production`335 OK`。
  最新order-free/live run为`/root/qount/state/mini_trend/forward/runs/20260722T102023Z`，
  readiness=`f4dfbb8247abcfab09a421b86ed9329a9ae03608dc0c3f8640ce1c9c2edddca0`，authority batch=`65c8a64f...ba4750`，
  RuntimeLedger=`efddab4c...02a3ee`，pre-dispatch reconciliation=`64fd12f...6934114`，均passed。
  账户可用余额`486.15970914 USDT`、TOP3全平、普通/条件挂单0、unresolved order 0、HALT absent、one-way/isolated 1x通过；
  registry=`minimal_live`，新arm=`qmt-arm-9f10c9487f998bb6b586`，文件与env均root `0600`，旧两个arm已按原SHA-256归档且旧token未备份。
  live service最近结果`success/0`，dispatch为`duplicate_decision_noop`，目标权重`BTC/ETH/BNB=0/0/0`，0 market/0 stop、
  `exchange_mutation_attempted=false`、无`live_dispatch`，不得为制造样本强制下单。
  Dashboard publisher已完成最新原子publication；system、overview、positions、orders、readiness、strategies、alerts和intelligence均fresh，
  system窗口`180s`，ledger类窗口`15min`。最终health四个scope全pass；open alert仅1条日报证据不足WARNING，CRITICAL/HALT均0，dead-letter 0，
  该WARNING不阻断Base live。

- **2026-07-22 freshness/readiness架构修复已固化。** system顶层只绑定`ops_observer`并使用180秒窗口；RuntimeLedger的15分钟窗口继续独立作用于
  overview/positions/orders/readiness。旧schema或损坏日报只使intelligence unavailable，不阻断其它read model；通知SQLite只读文件与WAL sidecar
  权限边界已验证。live service自身运行态由health probe视为合法过渡态，避免未来新decision被错误挡住。

- **2026-07-22 0.2.11统一freshness默认值（已被0.2.12包含）。** `0.2.10`已证明system只绑定
  `ops_observer`并为fresh，但CLI仍硬编码旧120秒、覆盖dataclass的180秒。`0.2.11`用单一常量同时驱动配置与CLI，
  并增加解析级回归；`0.2.12`在此基础上修复live oneshot自检循环。

- **2026-07-22 0.2.10独立freshness最终修复已部署验证，后续默认值统一仍保持停盘维护。** `0.2.9`已部署，publisher与
  v2日报均成功；order-free周期最终blocker 0，账户`486.15970914 USDT`、TOP3全平、0订单/成交，dry dispatcher
  `duplicate_dry_noop`且未尝试交易所变更。随后确认 system read model把RuntimeLedger错误套用Ops Observer的120秒阈值，
  会在两分钟调度边界自报stale。`0.2.10`将system顶层freshness只绑定Ops Observer，并把其窗口设为180秒；账户、仓位、
  订单、决策和readiness继续独立使用RuntimeLedger的15分钟窗口。

- **2026-07-22 0.2.9日报兼容与publisher修复已在VPS验收，继续保持停盘维护。** `0.2.8`已部署并修复 WAL
  sidecar 沙箱；随后发现 `latest` 指向升级前v1日报，缺少v2 `pipeline/evidence`字段。此类过期/不兼容日报现在只会让
  intelligence read model显示`unavailable_until_daily_intelligence`，不会阻断Dashboard、账户/账本、readiness或其它来源的独立freshness。
  `0.2.9`部署后会重新运行只读日报生成v2原文证据；其LLM和个人通知均不拥有交易权限。

- **2026-07-22 0.2.8 publisher WAL沙箱修复已在VPS部署，后续日报兼容修复继续保持停盘维护。** `0.2.7`已部署并完成通知库
  verified replay、无订单周期和production回归；随后发现 publisher 的整个通知目录只读时，SQLite WAL 读者无法创建
  `-wal/-shm`，导致 `unable to open database file`。重现实验证明仅放开sidecar目录、保持`store.sqlite3`文件级只读，
  同时应用层`mode=ro + query_only`即可读取且数据库hash不变。publisher timer现为`disabled/inactive`以避免重试；
  Daily Intelligence为`enabled/active`，MiniTrend live为`disabled/inactive`。`0.2.9`必须经本地、VPS production、
  publisher oneshot和新的无订单周期验收后，才重新生成arm并恢复同一Base 100 USDT timer。

- **2026-07-22 0.2.7完整升级已通过本地发布门并部署到VPS，随后保持停盘维护。** 本次统一了逐模块freshness、
  NotificationSnapshot v2、当前/历史告警严重度、空告警库、canonical通知库、Daily Intelligence v2正文证据与
  结构化研究建议、readiness五轴和Ops Observer。Dashboard分别显示观测时间、内容变化时间、本轮评估时间和每个来源
  的到期状态；通知/微信/日报故障只影响对应observation/intelligence/delivery域，不会被错误解释为execution异常。
  Daily Intelligence把pipeline健康与evidence充分性分离，全现金且0计划订单的账本明确为`no_order_expected`；LLM仍固定
  `orders_allowed=false/live_changes_allowed=false`，只能提出进入deterministic研究门的假设。本地聚焦`83/83`、全仓
  `1548/1548`、compileall、16份schema、前端与shell语法、diff及密钥模式扫描均通过。VPS live timer当前为
  `disabled/inactive`，账户停盘前为flat且普通/条件挂单0；只有部署、通知库verified replay、无订单生产周期、release
  provenance、readiness五轴、RuntimeLedger和reconciliation全部复核后，才重新生成arm并恢复同一Base 100 USDT timer。

- **维护前阶段（2026-07-22）：MiniTrend Base 100 USDT单策略minimal-live已正式启用并正常运行。** VPS部署release为
  commit `e279b966...b95cf`、version `0.2.5`、source tree `42681594...8eb38`；本地全仓`1542 OK`，VPS production
  `328 OK`。唯一真钱策略为`MiniTrend-UM-Base-v0.2`，TOP3 long/cash、one-way、isolated 1x、effective gross `<=1`；
  RiskTier与FundingVeto继续shadow-only，旧X4/C×D/line A和production cron保持关闭。
- 最终recurring run为`/root/qount/state/mini_trend/forward/runs/20260722T061346Z`：readiness
  `2d59b071...49b26`、authority batch `25924c52...bce38`、RuntimeLedger `dbac0f91...3c434`、pre-dispatch
  reconciliation `dba39b3c...9f2c7` passed。账户可用余额`486.15970914 USDT`，TOP3全平、普通/条件挂单0，
  registry=`minimal_live`，arm/env均为root `0600`，HALT不存在；live timer为`enabled/active`，下一日线周期由
  `qount-mini-trend-live.service`先order-free refresh再幂等dispatch，forward timer仍`disabled/inactive`。
- 首次live artifact为`20260722T055437Z/live_dispatch-20260722T055659Z.json`，artifact SHA-256
  `b13782b6...db81a`。冻结决策权重为`BTC/ETH/BNB=0/0/0`，因此0 market、0 STOP、
  `exchange_mutation_attempted=false`；journal仍真实写入`live_intent_locked -> live_completed`，post-dispatch
  reconciliation `71c34b4d...0a01` passed并发布authority `5b4433e1...f99a`。这是全现金信号下的正常live闭环，
  不是未启动；尚无真实fill/fee/slippage/STOP触发/UNKNOWN恢复样本，所以禁止扩容或恢复其它策略。
- 启动过程中修复三项只在真实生产序列出现的架构缺口：authority selector软链接被CLI提前解引用、同batch健康INFO事件
  dedupe identity冲突、已完成live decision使recurring dry refresh返回75。对应版本`0.2.3/0.2.4/0.2.5`均有回归；
  recurring service已实际复跑为`duplicate_decision_noop`且systemd result success。旧`0.2.4` arm artifact已0600归档，
  旧live env token已删除且不可恢复，新arm绑定`0.2.5` release。
- **升级维护前的最后一次只读核查（2026-07-22）：** VPS源码/production provenance仍为`0.2.5`，live timer当时为`enabled/active`，
  forward timer=`disabled/inactive`，legacy cron有效项`0`，live service最近结果`success/0`。arm=`armed`、本金`100 USDT`、
  最新run仍为`20260722T061346Z`，HALT与未完成live lock均不存在；其后已进入上述0.2.7停盘维护窗口。

- **2026-07-22 owner将100 USDT MiniTrend canary的账户级日损熔断固定为5%，累计试点峰值回撤保持10%。**
  两条线都按冻结的`100 USDT`试点本金计算，即分别约`5 USDT`和`10 USDT`，不会改变Base v0.2的逐币
  `3xATR`吊灯止损、3根完成日线冷却或35% deadband。日损与累计回撤只在日线dispatcher运行时评估，
  不是盘中watchdog；两次dispatch之间的盘中保护仍依赖Binance原生`STOP_MARKET closePosition`。触线后只允许
  flatten并写HALT，不自动恢复。该决定覆盖下文2026-07-18的300 USDT/无日损门历史合同，历史证据本身不回写。
- **历史阶段（0.2.1）：发布候选补齐首单前的三个独立生产门。** live输入中的preflight、projection、readiness、exchange rules和
  account snapshot必须在15分钟内生成；每笔市价成交按逐笔trade加权均价计算adverse slippage，超过25bps时仍先完成
  保护止损和对账，再写`halted_slippage`；Mac release commit、项目版本、逐文件SHA-256和source tree hash通过
  `.qount-release-provenance.json`绑定到VPS部署文件，forward在任何私有预检、arm或订单前先验证。当前发布尚未部署、
  未生成manual arm、未发送真实订单；只有新的order-free forward refresh、authority、RuntimeLedger和三方对账全部通过后，
  才允许尝试一次100 USDT canary，且不会为了产生首单而覆盖Base信号。
- **Daily Intelligence报告`f4d90e84...dd63a94`不改变策略或订单。** 它只确认观测时点TOP3同步上涨、正funding、
  Binance公告存在和内部账本对账通过；正文、精确事件时点、目标资产事件窗与外部成交证据不足。market/execution为`ok`，
  event/strategy/red-team/editor为`needs_research`，因此不得把公告、同步上涨或正funding转换为Base信号、仓位或风控豁免。
- **历史阶段（2026-07-22 0.2.1）：VPS order-free refresh已完成，但当时尚未arm，因为冻结Base信号为全现金。**
  deploy commit为`9144e362...1c27b`，release provenance/source tree验证为`0.2.1`/`70ee1078...60020`；VPS生产回归
  `307 OK`。新run为`20260721T174354Z`：完整funding、独立runtime、私有只读preflight、one-way/isolated 1x、
  TOP3全平、普通单/条件单均0、标准authority/RuntimeLedger/pre-dispatch reconciliation及全部blocking gates均通过，
  readiness为`ready_for_manual_final_arm`、hash=`8087c1d8...43fba`。但决策日`2026-07-20`的Base权重为
  `BTC/ETH/BNB=0/0/0`，dry dispatcher为`0` market、`0` stop、`exchange_mutation_attempted=false`；没有为制造
  成交而偏离策略，故该阶段manual arm=0、registry仍为`research`、timer仍`disabled/inactive`、无HALT/UNKNOWN且无真实订单。
  因而真实fee/slippage/STOP触发/UNKNOWN恢复证据仍为未采集，扩容继续禁止。

- **2026-07-22 只读 Daily Intelligence 已完成搜索、六角色、归档、Dashboard和个人微信真实投递闭环。**
  `src/qount/intelligence/`生产默认使用免费`OfficialFeedSearchProvider`读取Binance公告API、Federal Reserve RSS和SEC press release RSS，
  每个来源最多3条；feed原始字节和SHA-256先归档，再对候选URL经过既有官方域名allowlist复抓正文。Brave adapter只保留兼容，不再是
  production依赖。Binance USD-M TOP3 `24hr/premiumIndex`响应和官方正文均保存原始HTTP字节及SHA-256。系统从冻结
  `RuntimeLedgerSnapshot v3`确定性提取订单、逐笔成交、fee/funding、NAV、回撤和三方对账摘要，再依次运行
  `market_analyst/event_analyst/execution_reviewer/strategy_reviewer/red_team/editor`六个本地Alpha Agent；red-team/editor会读取前序
  报告。`DailyIntelligenceReport`、source/search/market原文、manifest和`latest`指针以`0700/0600`不可覆盖归档，重载时重放嵌套
  合同、原文字节hash和source引用。所有报告固定`orders_allowed=false/live_changes_allowed=false`，研究建议只能进入后续
  deterministic实验，不能成为订单、目标权重、live配置、风控豁免或promotion证据。
- 首次真实日报`c326f31c...05f`完整归档3份搜索、8份详情和2份行情，但六角色在网络前被50,000字符上限以
  `llm_input_too_large`阻断；该报告和通知原样保留。随后按角色压缩上下文且不提高全局上限，第二次真实报告ID
  `24defae63419d002a74ff07fd578c994b3b68f6eb200bd76b3a4fc6ca1fb6adc`、report hash
  `f4d90e84b1828345261568043623ba7b32ea5b66ede9fbe66d490f54ddd63a94`、manifest hash
  `295a9d117a241099f531aa799af8c8dc012a37a2effd775049bdc5aa3c11dbff`。六个真实Responses请求载荷约13.4-40.2KB，全部返回中文严格
  Schema报告，无`llm_input_too_large`或403/502/503/524；market/execution为`ok`，event/strategy/red-team/editor因来源发布时间、
  正文质量和外部成交证据不足主动为`needs_research`，所以外层`incomplete`是研究证据状态，不是链路故障或缺失报告。
- Dashboard新增独立`intelligence` source/freshness和`#/intelligence`“情报复盘”页；当前为11份业务read model，原子release为
  11份模型加`publication.json`共12个JSON，静态Draft 2020-12合同为16份。`DailyIntelligenceReport`可映射为
  `NotificationStore`事件；生产通知已改为`OpenClawWeixinProvider`复用腾讯官方`@tencent-weixin/openclaw-weixin 2.4.4`账号，固定
  `ilinkai.weixin.qq.com/ilink/bot/sendmessage`、稳定client ID、严格route、HTTP与腾讯JSON业务响应双层校验、限流/超时和仓库外`0600`凭据边界。失败响应
  必须拒绝非零`ret`，成功响应必须包含正整数`message_id`。WeCom adapter
  继续作为未启用兼容实现；外部接受后、本地成功标记前崩溃仍可能出现重复，不能声称exactly-once。
- `qount-daily-intelligence.timer`现为`enabled/active`，每日`04:30 UTC`并带0-10分钟随机延迟；首次启用前写入当前systemd persistent
  stamp，避免把已手工完成的当日日报重复发送，下一次按未来日程运行。unit只允许官方feed/详情、公开行情、LLM和个人微信访问，显式
  清空代理并移除全部Binance私钥环境。relay-station与个人微信凭据以仓库外`0600 root:root`文件接入，不需要Brave Key。通用Alpha
  Agent研究默认仍为`gpt-5.6-terra`；Daily
  Intelligence独立固定`gpt-5.6-sol`，通过`/v1/responses`、`store=false`和严格JSON Schema输出简体中文。New-API已经删除，当前请求链为
  `qount-vps -> llm.alyaloale.com -> TokenRouter -> Docker内网aishenji-normalizer -> aishenji.top`。normalizer由nginx/OpenSSL重建
  TLS、SNI、Host和User-Agent请求特征；account 25的`base_url`指向该内网服务、`proxy_id=NULL`，不得恢复VPS直连或proxy 6。
- normalizer上线后，`2026-07-21T13:23:23.472311+00:00`执行一次有真实研究用途的TOP3首角色分析：单次非流式请求约`26.5s`完成，
  五字段严格合同、简体中文、越权语言与source hash校验全部通过，`orders_allowed=false/live_changes_allowed=false`。pulse/ticker/premium
  原始证据hash分别为`e991a4a3...04c` / `df89881f...787` / `30a0ddfe...eee`；报告结论只指出TOP3 24小时上涨且资金费率为正，单次快照
  不足以确认趋势持续或杠杆拥挤。qount-vps随后真实非流式与流式Responses均为`completed/OK`，account 25保持
  `active/schedulable`，TokenRouter与normalizer均healthy，且TokenRouter未重启。只读日志另确认两次长流式Codex请求分别约
  `125.7s/126.7s`后收到上游`524`并由TokenRouter映射为502，两次之后均恢复200；WAF 403路径已修复，但长请求超时仍是必须退避、
  失败关闭的上游波动风险。日报客户端现仅对瞬时状态和显式`retryable=true`执行最多一次有界退避，并可读取错误体`retry_after`；纯
  `owner_action_required`仍立即阻断。本次完整E2E后，account 25保持`active/schedulable`，TokenRouter、sub2api和normalizer均healthy。
- 个人微信通知已形成接入与真实日报两类本地投递记录：从现有OpenClaw账号、会话route和对应context token原地导入最小五字段凭据，不回显或归档
  token/recipient；原context-token文件也从`0644`收紧为`0600 root:root`。历史中文接入事件和日报任务曾因仅检查HTTP `2xx`而本地标记
  `DELIVERED/SUCCEEDED`，audit chain可重放，但这只证明旧实现的transport状态，不能证明腾讯业务接受或手机展示。2026-07-22直接诊断得到
  HTTP `200`、JSON `ret=-2`、`prepare failed`，故已把provider收紧为解析真实业务合同；未来失败将诚实进入NotificationStore失败/重试路径。
  同时已恢复并启用仅回环监听的`openclaw-gateway.service`，腾讯通道显示`running`；账号扫码确认“已连接过此 OpenClaw”。Owner随后从手机发送
  一条2字符测试消息，VPS在`2026-07-22T00:06:40+08:00`收到入站、刷新context token并成功向同一手机回发错误提示，证明手机通道可见。
  新context token已原子同步到Qount `0600`凭据且无首尾空白；真实Qount中文验证消息返回HTTP 200和19位正整数`message_id`，provider为
  `ACCEPTED`。随后新建生产`NotificationStore`事件`cd078514d6c7...`，唯一job `9c6fca5efc6b...`为`DELIVERED`、attempt为`SUCCEEDED`，
  response hash存在且16行audit chain完整重放。OpenClaw聊天提示本身报错来自其独立旧模型域名`api.alyaloale.com`无法DNS解析；该旧key对当前relay也为403，不影响Qount日报通知。
  本次诊断没有调用Binance私有API或交易路径。
- 个人微信会话现已消除双副本漂移：Qount仓库外凭据只保留`account_id/base_url/recipient/token`四个稳定字段，发送前从
  `/root/.openclaw/openclaw-weixin/accounts/<account_id>.context-tokens.json`读取该recipient的最新context token；静态`context_token`
  仅保留为手工/测试回退且已从生产凭据移除。provider要求绝对目录、无symlink、正确owner、目录不可group/world writable，token文件必须
  是同owner的普通`0600`文件且不超过64KB；缺文件、无recipient、无效JSON或权限不安全均失败关闭。日报unit显式`Wants/After`
  `openclaw-gateway.service`并只读挂载accounts目录。部署provider/runner/unit哈希分别为`65af6bf2...8780`、`0254618c...02c8`、
  `9280a8bf...1691`；新架构验证事件`3b1a0dd9...0f43`、job `6d51a764...4324`已一次投递为`DELIVERED/SUCCEEDED`，生产store现有
  5 event/job/attempt和20行可重放audit chain。本地扩大回归`75 OK`、VPS聚焦`24 OK`，compileall、`git diff --check`和目标unit
  `systemd-analyze verify`通过；旧代码保存在VPS `/root/qount-notify-backup.rl6QL6`，其中不含凭据副本。
- 生产前端已部署到`https://qount.alyaloale.com/#/intelligence`；publisher timer保持`enabled/active`并持续生成原子publication，
  `intelligence.summary.status=available`且source hash精确绑定上述`f4d90e84...63a94`真实报告，未复制fixture。
  静态`index.html/app.js/style.css` SHA-256分别为
  `86e2535b...d139` / `ddc51a8c...487b` / `3baaff67...8eb9`。通过只读SSH隧道完成生产release桌面`1440x1000`和移动
  `390x844`Chromium验收，布局无重叠、裁切或横向溢出；域名匿名请求仍为Basic Auth `401`和`no-store`。临时8766隧道及远端HTTP
  server已关闭。此前全仓`1508 OK`、生产聚焦VPS回归`25/12 OK`；本次官方源/个人微信/通知/日报/relay聚焦在Mac和VPS各`45 OK`，
  Python compileall和`git diff --check`通过。没有读取Binance私有API、修改账户、恢复交易timer/cron/manual arm/live或发送订单；外部
  写入仅限通过NotificationStore审计的个人微信通知，最新一条是上述动态会话架构验证。

- **历史阶段（2026-07-21）：Phase B/C/D已部署并完成一次systemd order-free闭环，真钱订单当时仍关闭。** VPS只读前审计确认
  MiniTrend timer为`disabled/inactive`、production cron为0、全部live开关为false、无arm/HALT/UNKNOWN；账户为one-way、
  TOP3 isolated 1x、全平，普通单/条件单均0。成功run为
  `/root/qount/state/mini_trend/forward/runs/20260721T063854Z`：runtime proof通过，dry dispatcher为`dry_validated`，
  0 market/stop intent且`exchange_mutation_attempted=false`；最终readiness为`ready_for_manual_final_arm`、blocker 0，
  但`live_orders_allowed=false`。readiness hash为`8496f70e49081e47a4fa3a610b86c8686a14c22c5d0cd0a94199fa0a97ad2a87`；
  authority batch/manifest hash为`70d1b38b...f0a49` / `1520b6af...e2ec3`；RuntimeLedger snapshot hash为
  `70184860...575fb`；pre-dispatch reconciliation hash为`9971ca5f...22d96`且passed。观察值为
  forward pair/active bar/paper day/dry day=`0/0/0/1`，funding journal完整；它们不再阻断，但样本成熟度仍如实为0。
  registry保持`research`，arm仍为0，timer/live switch/旧cron仍关闭。首次SSH直接执行的run
  `20260721T063406Z`在dispatcher前因旧合同journal和缺systemd invocation proof失败关闭，未尝试交易所mutation；dry journal现按
  live contract hash隔离，旧1行证据原样保留。VPS `systemd-analyze verify`通过目标unit（仅报告无关cloudmonitor旧警告），
  VPS production/B-C-D/post-fix分别`303/59/21 OK`；Mac全仓复跑`1497 OK`。

- **2026-07-20 verified Dashboard publisher 已在VPS受控启用，交易侧继续关闭。** 新的order-free cycle
  `/root/qount/state/mini_trend/forward/runs/20260720T101653Z`通过账户flat/0仓位/0挂单、projection、dry dispatcher和
  `exchange_mutation_attempted=false`校验，authority writer写出batch
  `5a1c94a4280bb578c9ff1e8745cb309983f0f978096070819865c4b4024f4815`及六类标准source；authority hash为
  `d2648116252cc23235caa2bacf69e845d9190e343046466c4685609e79c8f34b`，result hash为
  `720c5c5f2336eab1edff4be40884143904bf15b04b8439d0d2a9761d0f2d2118`。最后一次授权账户观测为
  wallet/available `486.15970914 USDT`、TOP3实际仓位全0、gross/margin均0；该authority在`10:32:05 UTC`后已按15分钟规则
  标记stale，publisher不会查询账户或把它洗新。
- publisher timer现为`enabled/active`，authority oneshot仍为`static/inactive`，MiniTrend forward timer为`disabled/inactive`，
  root production crontab仍为零active entry。publisher unit hash为
  `f571cc52b386ffc3fd70a822a1270327a02896ed725feb09b0c40be463e3fd43`，只保留`CAP_DAC_OVERRIDE`读取chrony Unix socket，
  `PrivateNetwork=true`且无`CAP_NET_*`。19:38 CST首个完整日历周期发布publication
  `e4ff138bc0b22899fdac65f8e5eae8a993285959ca021c783bf2c10e4d2ad751`、result
  `77f70e9958c519f97009824253575a864d01a333b19ae4e06fd7b9f8b6af5a07`、backup
  `8e3618b4e36c172c3d543022a83fd6c17c2fa34f018f67c952ef0f812b40b163`；health为fresh/healthy，恢复演练通过，
  release保留当前+4个，备份保留latest+60个，异常/损坏目录只报告不删除。路径审计为`ready_for_authorization`，最终复核hash
  `46e8aa740143a753e9238ca88fd0a3c7744a25fa24ce5405a01fdd4b8b0842a8`。没有恢复forward/live/manual arm、调用私有API、
  修改账户/订单或发送真实通知；`live_orders_allowed=false`。

- **2026-07-20 VPS 测试入口已按生产依赖分层。** `scripts/run-vps-tests.sh` 默认只运行不依赖 numpy/websockets 的 production surface；
  显式 `discover` 才运行全仓研究测试。此前直接 discovery 在最小 VPS 环境出现的 8 个错误均为可选依赖缺失，不是生产代码回归；
  当前VPS production profile为`299 OK`，Mac全量为 `1488 OK`，唯一 warning 为既有 `cta_data.py` UTC deprecation。

- **历史 superseded：2026-07-20 notification transport合同已完成本地fake边界，publisher生产授权仍阻断。** 新增
  `notifications/transport.py`：`ProviderResponse`要求精确字段、canonical response hash、请求`delivery_key`回显及
  `ACCEPTED/DUPLICATE/REJECTED`一致性；`ProviderTransport`只接受注入provider，使用固定窗口fail-closed限流、调用deadline、
  provider故障/超时/错误响应审计，并继续复用outbox固定delivery key。provider credential只从非symlink、父目录无group/world权限、
  文件精确`0600`的显式路径读取，不查环境变量；无key模式生成不含key material的显式审计。仓库只提供
  `FakeNotificationProvider`，没有HTTP/webhook/ServerChan adapter；fake幂等、故障重试、响应篡改、拒绝、限流、超时、0600和无key
  共7项新测试通过，没有发送真实消息。
  新增只读`operations/publisher_paths.py`及`scripts/operations/audit_publisher_paths.py`，复用完整authority importer和backup
  readback验证真实绝对路径、symlink、`0700/0600`及最新snapshot；结果无论通过与否均固定
  `pending_explicit_owner_authorization`且不能授权install/enable。systemd模板声明的候选路径仍是
  `/var/lib/qount/dashboard-authority`和`/var/lib/qount/dashboard-backups`，但仓库没有生产authority bundle writer；首次本地尝试因
  alias缺失未连通，随后已恢复仓库外alias并完成真实VPS审计（结果见下一条），因此没有申请或执行production publisher安装/enable。
  `deploy/cron/qount-production.crontab`已改成零active entry的注释模板，避免被直接安装恢复live/paper。聚焦48项、全仓1478项回归通过；
  仓库内真实通知、production cron、publisher/交易timer、订单执行和全部live开关保持关闭，本批没有访问私有API、交易所或生产文件；
  VPS实际运行状态因host不可解析而未复核，不能把本地安全状态冒充生产证明。

- **历史 superseded：2026-07-20 VPS 只读路径审计已执行，结果为 `blocked`，并已纠正一个真实 timer 状态。** 已在仓库外 SSH 配置恢复
  `qount-vps` alias，使用既有 root key 只读进入 `/root/qount`。核对结果：root crontab 只有停用注释；
  `qount-dashboard-publisher.timer/service`、`qount-runner.timer/service` 均为 `not-found`/inactive；发现的
  `qount-mini-trend-forward.timer` 原为 enabled/active，已执行 `systemctl disable --now`，复核为 disabled/inactive；没有 qount
  交易或 publisher 进程，`QOUNT_LIVE_ENABLE=false`。
  `/var/lib/qount`、`/var/lib/qount/dashboard-authority`、`/var/lib/qount/dashboard-backups` 和 `/var/www/qount/data` 均不存在；
  当时`/root/qount`代码没有 authority writer/source 引用。将本地只读审计代码临时放入 VPS `/tmp` 后运行，输出
  `status=blocked`、`authority_bundle_verified=false`、`backup_state=invalid`，audit hash 为
  `fb66f3c3c8f45c90ed9429cca59e9b9b843c61e335ad5d179a37a2921c059c5f`；临时代码已清理。
  因真实 authority writer/source、目录权限和 backup snapshot 都不存在，不能返回 `ready_for_authorization`，没有申请或执行
  production publisher install/enable；transport 仍没有第二份明确授权。远端 cron、timer、订单、live 和真实通知继续关闭。

- **2026-07-20 Phase B/C账户事实、系统健康、仓位/决策追踪和新Dashboard前端已闭合，静态站已部署。**
  `RuntimeLedgerSnapshot`升级为schema v3：SQLite schema v2新增不可变`account_observations`，同一读事务读取完整NAV历史和
  最新账户观测，权威提供wallet/available balance、actual gross、margin，并从连续NAV派生peak equity、current/peak drawdown。
  账户观测与NAV必须同batch、同时间、同quote asset且满足余额关系；时间倒退、identity冲突、source/hash篡改、NAV不连续或
  回撤重算不一致均失败关闭。`SystemHealthSnapshot`固定要求`clock/disk/service/backup`四项强类型观测，backup age绑定观测时点，
  component/snapshot hash可复核；system使用独立freshness，不能把陈旧ledger洗新。
  Dashboard现有`overview/positions/orders/strategies/decisions/risk/readiness/system/alerts/reports`十份模型和十条路由；
  `positions`链接到`#/decisions?trace=<id>`，证据链覆盖batch、snapshot、strategy decision、portfolio、risk、order plan、ledger和
  reconciliation。原子release精确包含十份模型加`publication.json`共11个JSON，静态Draft 2020-12 schema共13份；完整fixture的
  12个实际实例已通过`jsonschema 4.25.1`验证。完整health + DailyBrief组合曾暴露tuple/list最终readback不等价，现已把公开
  `as_dict()`规范成JSON-native list并加入原子发布回归。
  新前端默认并规范化到`#/live`，只读`data/v1`，显示账户事实、四项健康和可点击trace；缺release时固定显示
  `PRODUCTION STOPPED`，不回退legacy JSON。Playwright 1.60 + Chromium 1223完成桌面`1440x1000`和移动`390x844`的
  Live/Positions/Decisions/System/offline及菜单检查，无控制台异常、页面级横向溢出、重叠或裁切。该批边界聚焦`71 OK`、当前全仓
  `1468 OK`；Dashboard与DailyBrief golden SHA-256更新为`f2840c99a4403c1a50e39c497e4b6bd571dcc4442d4e77e635e53c5453b66c32`
  和`6ea5d7f0ca239382e672fe0b4ad9115d631f1e81548d2bda386d7f533a58e6f9`。
  当前界面已完成中文显示优化：导航、状态、账户事实、健康观测、告警、日报和证据链固定节点均使用中文展示，审计术语和
  reason code保留原值；CJK字体栈优先使用`PingFang SC/Hiragino Sans GB/Microsoft YaHei/Noto Sans CJK SC`，正文`14px`、
  导航`13px`、面板标题`15px`、移动标题`20px`、关键指标`18-21px`，移动菜单等待动画稳定后侧栏位于`x=0`，文档宽度与视口一致。
  `https://qount.alyaloale.com/#/live`已替换为新静态前端；served root只保留`index.html/app.js/style.css`，旧`data/*.json`
  已删除并备份到`/root/qount-dashboard-backup-20260719T183341Z`。Caddy仍active，未认证返回401并保留Basic Auth、`no-store`、
  `nosniff`、`DENY`和`no-referrer`；qount cron保持停用。production v1 publisher现已接入真实order-free authority，authority stale时
  页面明确显示stale，不回退本地fixture或legacy JSON。

- **2026-07-20 本地 production-shaped publisher、OS健康探针、备份恢复和release保留已闭合。** 新增独立
  `operations/health_probes.py`、`operations/backups.py` 和 `operations/dashboard_publisher.py`：clock使用
  `timedatectl show/show-timesync`的同步状态与微秒偏差，disk使用`shutil.disk_usage`，service只读固定allowlist的
  `systemctl show`，backup只接受严格权限、canonical marker/manifest和逐文件SHA-256。观测失败不会填充假值，clock/disk
  以`unavailable + null`进入四项健康合同；前端对应显示“观测不可用”。
  `run_dashboard_publisher()`通过非阻塞`flock`单写者串联完整`read_vps_authority_bundle()`、真实健康、Dashboard builder、同盘
  原子`v1`发布、逐文件备份、临时恢复演练和仅清理已验证且未被当前指针引用的旧release（当前+最近N个保留）。备份/恢复会
  校验文件集合、字节数、内容hash和读模型hash；发布或锁失败保留旧指针。新增未启用的
  `deploy/systemd/qount-dashboard-publisher.service/.timer`模板，清空代理/live环境、限制网络为Unix、`ProtectSystem=strict`、
  精确`ReadWritePaths`和`UMask=0077`。本地聚焦`34 OK`、全仓`1468 OK`，唯一warning仍为既有`cta_data.py` UTC deprecation；
  13份schema及含unavailable health的11个release实例通过`jsonschema` registry校验，Node语法、架构扫描、`git diff --check`和
  Chromium fallback桌面`1440x1000`/移动`390x844`均通过。Browser in-app Node REPL在本会话未暴露，因此未冒充Browser技能验收；
  本批没有部署/enable systemd、访问VPS、读取生产文件、发送真实通知、调用私有API、交易所或订单接口。

- **2026-07-20 production publisher前置输入边界已在本地补齐。** 新增
  `reporting/artifact_importer.py` 的只读 `read_vps_authority_bundle()`：只接受严格目录中的完整
  `VerifiedDecisionBatch`、`StrategyRegistry`、`RuntimeLedgerSnapshot`、`NotificationSnapshot`、
  `SystemHealthSnapshot` 和 `DailyBrief`，检查 `0700/0600` 权限、symlink、canonical JSON、重复 key、每个对象的
  内容/hash，并交叉验证 batch/manifest/plan、日报 source hashes 和 Dashboard builder 全链。额外文件（包括 legacy
  state）或任一篡改均失败关闭；importer 不查询网络、交易所、SQLite 或环境变量，也不写 release。
  `notifications/collector.py` 新增四项健康观测的显式组装适配器，要求 `clock/disk/service/backup` 恰好齐全且每项带
  source identity/hash，具体OS/systemd/backup探针随后由独立operations单写者注入。该前置批新增4项 importer/collector 测试，历史
  聚焦回归为`54 OK`；production publisher、systemd timer、真实 transport、cron、订单与通知开关仍未启用。

- **2026-07-20 Phase C只读alert producer adapters已在本地闭合。** 新增`notifications/producers.py`，提供
  `alerts_from_verified_decision_batch()`、`alerts_from_runtime_ledger_snapshot()`和`alerts_from_system_health()`三条纯映射；
  输入分别是重放完整lineage/artifact reference的`VerifiedDecisionBatch`、自验证冻结`RuntimeLedgerSnapshot`及新冻结
  `SystemHealthObservation`，不读取SQLite、交易所、网络、环境变量或时钟。健康source返回空事件；data quality/risk/plan blocker、
  recoverable/UNKNOWN订单、三方对账、NAV residual及显式system degraded/unavailable才生成稳定`AlertEvent`。严重度固定为：
  recoverable order和reconciliation HALT=`HALT`，非HALT reconciliation/NAV/risk/system unavailable=`CRITICAL`，allocation/plan/
  system degraded=`WARNING`。同一账本状态晚抓一次不会制造新incident：order recovery绑定提交全部状态的`audit_last_hash`，而不是包含
  capture时间的snapshot hash。producer事件已穿过`NotificationStore -> NotificationSnapshot -> alerts read model -> DailyBrief/
  reports`端到端验证，重复enqueue保持同一delivery identity；本地QA `http://127.0.0.1:8769/#/alerts`显示producer生成的
  `order_recovery/HALT`，日报为`halt_required`并给出两个确定性owner actions。本批新增11项测试，Phase B/C架构聚焦`101 OK`、
  全仓`1446 OK`；producer golden SHA-256为
  `76a708e8fdcd0e3d85234b8f78c24cbeb036b171b536a6fc7d184fa97ae9d580`，唯一warning仍为既有`cta_data.py` UTC
  deprecation。本批没有接scheduler、自动resolve旧incident、真实transport或production publisher，没有访问VPS、生产文件、
  私有API、交易所/订单接口，也没有修改凭据、systemd/cron/live开关；仍是`research_sandbox`本地架构证据。

- **2026-07-20 Phase B/C确定性DailyBrief与Dashboard reports垂直切片已在本地闭合。** 新增
  `reporting/daily_brief.py`，只接受完整`VerifiedDecisionBatch`、治理`StrategyRegistry`、冻结
  `RuntimeLedgerSnapshot`和`NotificationSnapshot`，重放所有source校验后生成稳定`brief_id/brief_hash`及四份精确source hash。
  日报直接映射ledger equity/NAV PnL bridge、实际/预期仓位、策略decision/reason codes、当前计划与可恢复订单、三方对账、
  通知投递、未解决告警和确定性owner actions；recoverable/UNKNOWN订单、HALT对账或HALT告警进入`halt_required`，其余失败、
  WARNING/CRITICAL或dead-letter进入`attention_required`。当前账本尚不能证明的balance、actual gross、margin、peak drawdown、
  当日fill/rejection/partial-fill、保护单runtime状态和slippage均显式不可用；LLM固定
  `not_requested_deterministic_only`，所有策略`live_orders_allowed=false`。Dashboard新增第五份`reports` read model和`#/reports`，
  使用独立DailyBrief source/freshness；原子release精确包含6个JSON，静态合同增至8份Draft 2020-12 schema，读回会重建
  DailyBrief并拒绝自报hash、内容、文件集合或publication篡改。桌面`1440x1000`和移动`390x844`真实Chromium检查无裁切、重叠或
  空白，本地QA为`http://127.0.0.1:8768/#/reports`。新增6项DailyBrief测试；本批三模块聚焦`23 OK`、Phase B/C架构聚焦
  `90 OK`、全仓`1435 OK`。DailyBrief golden SHA-256为
  `4743a80e3408bf4590cf0ea04deff8cf1da13b3c909790d553828ba13c265d9c`，Dashboard ledger golden当前SHA-256为
  `62a1a6e69da0c7d0a37837ca586d25ae91768d1ccd916e655a47fb3735923d4b`。唯一warning仍为既有`cta_data.py` UTC
  deprecation。本批没有访问VPS、生产文件、私有API、交易所/订单接口或真实webhook，没有修改凭据、systemd/cron/live开关；
  fixture日报和QA release只是`research_sandbox`本地证据，不能称为production日报、账户状态或下单授权。

- **2026-07-20 Phase C首批通知告警垂直切片已在本地闭合。** 新增`notifications/contracts.py`的冻结
  `AlertEvent`，以source type/ID和dedupe key生成稳定identity、以完整内容生成event hash，固定
  `INFO/WARNING/CRITICAL/HALT`分级。`notifications/store.py`在私有目录使用SQLite WAL、foreign keys、FULL
  synchronous和busy timeout，把alert、OPEN/RESOLVED状态、delivery job、每次attempt及canonical hash audit chain在同一
  数据库事务中持久化；exact replay幂等，同identity不同内容拒绝。投递transport只允许注入，使用固定delivery idempotency
  key、指数退避、`PENDING/RETRY_WAIT/DELIVERED/DEAD_LETTER`状态和错误类型审计；“外部成功、DB marker未写”恢复会复用同一
  STARTED逻辑attempt和delivery key，不增加未知重复计数。本批没有调用真实webhook。
  `NotificationSnapshot`验证全部业务row hash与audit chain后，成为Dashboard第四份`alerts`权威read model；其source/freshness
  与batch/registry/ledger三模型独立，新的告警不能把旧账本洗新。原子release现在精确包含
  `overview/strategies/readiness/alerts/publication`五个JSON，静态合同增至6份Draft 2020-12 schema。前端新增告警页，显示
  severity、OPEN/RESOLVED、source/trace、delivery状态、attempt与next retry；仍不查询SQLite/交易所或重算PnL。
  桌面`1440x1000`和移动`390x844`真实Chromium截图检查无裁切/重叠，本地QA为`http://127.0.0.1:8767/#/alerts`。
  架构聚焦`92 OK`、全仓`1429 OK`，唯一warning仍为既有`cta_data.py` UTC deprecation。
  owner授权的旧展示清理已删除CTA-R SwiftBar/Übersicht源和旧`cta.json`前端推送脚本，卸载本机
  `com.qount.dashboard` LaunchAgent并把本地残留移到废纸篓；CTA-R每日研究任务保留。本批未访问VPS、私有API、交易所、
  订单接口、真实webhook或生产publisher，未修改systemd/cron/live开关；这只是`research_sandbox`本地架构证据。

- **2026-07-20 Phase B legacy dry dispatcher迁移回放已在本地闭合。** 新增
  `ledger/legacy_replay.py`，把同一份已链接的Base projection与legacy dry plan依次转换为标准
  `MarketSnapshot -> StrategyIntent -> PortfolioTarget -> RiskDecision -> OrderPlan -> DecisionBatchManifest`，再由
  `RuntimeLedger.record_verified_batch()`唯一入口登记batch与planned orders。入口同时核对projection artifact hash、完整
  decision、contract、legacy 14字段plan hash和新旧经济动作；任一错链、blocker或parity差异都在写账本前失败关闭。
  replay只接受空账本或同一batch的精确幂等重启，任何order transition、fill、cash event、position、NAV、reconciliation或
  recovery状态都不能被重新解释为dry证据。冻结报告明确`planned_only_not_executed`、`orders_authorized=false`、六笔订单
  全部`PLANNED`、风险增加仍为false，并保存legacy/standard action hash、expected positions/tolerance及audit tail。
  `tests/fixtures/legacy_dispatch_replay_golden.json`的SHA-256为
  `f52af0a63d22044affee5c1a398341f266d0ffc57407b9f9c5ec57725429529a`；新增7项测试覆盖完整batch、幂等重启、两种outbox
  崩溃窗口、source/report/journal篡改和执行状态隔离。最新架构聚焦`75 OK`、MiniTrend/dispatcher`37 OK`、全仓
  `1420 OK`，唯一warning仍为既有`cta_data.py` UTC deprecation。本批只使用测试夹具与临时SQLite/JSONL，没有读取生产
  artifact、接`mini_trend/pilot_dispatcher.py`、访问VPS/私有API/订单接口或修改凭据、systemd/cron/live开关；这是
  `research_sandbox`本地迁移证据，不是成交、对账、paper/live或部署证据。

- **2026-07-19 Phase B ledger到Dashboard v1的只读权威桥已在本地完成。** 新增
  `ledger/read_model.py`的冻结`RuntimeLedgerSnapshot`：输入只允许`RuntimeLedger + VerifiedDecisionBatch`，先补刷并验证
  SQLite/outbox/chain JSONL，再在同一SQLite读事务中绑定最新batch/manifest/plan、positions、recoverable orders、最新NAV和
  同批最新三方对账；缺NAV/对账、batch错链、对账后又发生状态变化或审计篡改均拒绝生成。`UNKNOWN`等未解决状态不会让
  监控面消失，而是进入快照并把readiness明确置为`blocked_runtime_state`。Dashboard publisher现在可选接收该快照：有快照
  时`overview`展示实际仓位和权威equity/PnL bridge，strategy NAV明确标记`portfolio` scope，ledger/recovery/reconciliation
  gates读取快照事实；无快照仍保持`unavailable_until_phase_b_ledger`。`live_orders_allowed`在所有分支固定false。
  freshness使用审计链最后一次source update，不使用capture/publish时刻，因此无状态变化的重新抓取和发布不能洗新。
  5份Draft 2020-12 schema已覆盖严格available/unavailable union，前端只格式化后端值，不访问交易所或重算PnL。新增8项
  snapshot/atomic publish/stale/tamper/UNKNOWN/golden replay测试；Phase C加入alerts/reports模型后，同一golden文件的当前
  canonical SHA-256为`62a1a6e6...923d4b`。当批架构聚焦`68 OK`、MiniTrend/dispatcher`37 OK`、全仓`1413 OK`，唯一warning仍为既有
  `cta_data.py` UTC deprecation。本批只创建测试临时DB/read model和本地QA发布物，未接legacy dispatcher、交易所adapter或
  VPS，未生成生产DB/read model、未调用私有API/订单接口，也未修改凭据、systemd/cron/live开关；这只是本地架构证据，
  不构成production PnL、部署或下单授权。

- **2026-07-19架构Phase B首批统一运行账本、订单恢复和三方对账基础已在本地完成。** 新增
  `ledger/store.py`：运行目录拒绝symlink和宽权限，SQLite固定WAL、`foreign_keys=ON`、`synchronous=FULL`，事务内
  同时写业务行与`audit_outbox`，提交后刷`0600` canonical chain JSONL。DB已提交但JSONL未写、JSONL已写但publish
  marker未提交两种中断窗口都可按sequence/event/hash重放且不重复追加；DB/journal任一篡改均失败关闭。账本覆盖完整
  `VerifiedDecisionBatch`和计划订单、订单事件、fills、fees/funding/transfers、long-only平均成本仓位、三类NAV字段、
  equity residual、order recovery和reconciliation。网络发送前必须先持久化`SUBMITTING`；不确定结果进入`UNKNOWN`，
  只能由注入的只读resolver按确定性`client_order_id`查询，未找到/异常继续UNKNOWN并要求HALT，代码没有替代下单接口。
  持久化三方对账必须逐项匹配batch冻结target/tolerance、当前ledger positions/open orders和最新NAV residual；封账后的
  晚到fill/cash event不能静默改写历史恒等式。该首批新增9项故障/重启/会计测试；当时Phase A/B联合`60 OK`，后续最新
  回归与Dashboard桥状态以上方条目为准；唯一warning仍为既有`cta_data.py`
  UTC deprecation。本批未接入legacy dispatcher，未生成生产SQLite/JSONL，
  未访问或部署VPS、私有API和订单接口，也未修改凭据、systemd/cron/live开关；当前真实执行和恢复仍由legacy
  `mini_trend/pilot_dispatcher.py`拥有，不能把本地账本称为live/order authority。

- **2026-07-19架构Phase A第七批Dashboard v1权威read models已在本地完成，Phase A本地范围闭合。** 新增
  `reporting/read_models.py`的`overview/strategies/readiness`三份模型，只接受完整`VerifiedDecisionBatch`和治理
  `StrategyRegistry`，重新验证batch lineage、manifest artifact references、registry/策略版本与风险预算后才生成。
  该批当时尚无Phase B账本输入，因此实际仓位、权益和PnL明确显示`unavailable_until_phase_b_ledger`；现在上方只读桥允许
  可验证冻结快照成为第三个权威source。浏览器始终不发Binance请求、不做uPnL/equity重算。freshness从source时间计算，过期
  统一显示STALE。发布采用`releases/<publication_id>/`不可变目录和`v1`相对symlink原子切换，半写失败保留旧指针，
  读取复核canonical JSON、权限、精确文件集合、symlink目标及所有hash。`web/schemas/`新增5份Draft 2020-12静态schema，
  前端改为只读三页监控台。Phase A聚焦验证已纳入上方`60 OK`联合回归。本批未发布真实read model、未部署VPS；该批当时
  只做HTTP/JS烟测，Phase C新增告警页后已补桌面和移动端真实Chromium截图检查。

- **2026-07-19架构Phase A第六批完整决策批次manifest与中断恢复已在本地完成。** 新增
  `contracts/batch.py`中的`ArtifactReference`、`DecisionBatchManifest`和完整lineage校验，把同一批次的
  `MarketSnapshot -> StrategyIntent(s) -> PortfolioTarget -> RiskDecision -> OrderPlan`绑定为第九类可验证artifact。
  交叉断言覆盖snapshot/time/decision/sleeve、Portfolio到Risk目标、Risk到Plan批准目标、batch ID以及increase/reduce
  权限；`orders_authorized`继续固定为false。新增`persistence/batch_store.py`，批次目录固定`0700`、成员固定`0600`，
  所有成员先不可覆盖落盘，`manifest.json`最后写入才算complete；缺/多成员、替换、篡改、路径/权限异常均失败关闭。
  manifest缺失的中断目录可显式resume，但已有成员必须逐个与预期envelope完全一致，绝不覆盖；冲突保留供审计。
  新增12项批次golden/failure/recovery测试，聚焦`59 OK`、MiniTrend`234 OK`、全仓`1387 OK`。本批仅在测试临时目录
  生成fixture，没有部署或访问VPS、账户和订单接口，也未修改凭据、systemd/cron/live开关；批次complete只表示
  pre-trade证据闭合，不表示已发送订单、策略晋级或获得实盘权限。

- **2026-07-19架构Phase A第五批不可变标准artifact持久化已在本地完成。** 新增
  `persistence/codec.py`和`immutable_json.py`，显式支持`MarketSnapshot`、traced `StrategyIntent`、
  `PortfolioTarget`、`RiskDecision`、含订单/撤单的`OrderPlan`、`StrategyRegistration`、`StrategyRegistry`和
  `DeploymentManifest`八类对象。artifact envelope固定schema/type/object ID/payload及双SHA-256；读取时先校验
  canonical payload/artifact hash，再通过权威`create()`重建并复核对象自身ID/hash，未知schema/type、重复JSON key、
  篡改和字段漂移全部失败关闭。文件边界使用同目录`0600`临时文件、flush/fsync、不可覆盖hard-link发布和发布后逐字节
  回读，`.tmp/.partial`不作为完成artifact。新增11项artifact测试和1项架构依赖测试，聚焦`47 OK`、MiniTrend
  `234 OK`、全仓`1375 OK`。本批只生成测试临时目录中的shadow fixture，没有写真实registry/manifest、没有部署或访问
  VPS、私有账户和订单接口，也未修改凭据、systemd/cron/live开关；artifact仍不等于promotion、owner arm或下单授权。

- **2026-07-19架构Phase A第四批strategy registry与deployment manifest合同已在本地完成。** 新增
  `governance/registry.py`：`StrategyRegistration`不可变绑定strategy/version/kind、contract/code/config hash、
  promotion状态、artifact/owner授权hash和gross/stress风险上限；`StrategyRegistry`保存每个逻辑策略唯一当前版本及
  registry hash。状态机只允许逐级推进或halt，同版本禁止偷换代码/配置，新版本必须退回research；风险预算增加必须有
  owner authorization，halt恢复必须绑定reconciliation evidence且不能高于原状态。标准`StrategyIntent`进入组合前可
  校验精确版本、环境资格和冻结风险预算。`DeploymentManifest`绑定git commit、dirty状态、code tree、dependency lock、
  runtime config、registry、promotion/owner bundles和rollback target；dirty production、未晋级策略或缺回滚目标全部
  拒绝，且manifest固定`orders_authorized=false`。Base adapter可生成绑定现有live contract hash的registration。
  聚焦`58 OK`、MiniTrend`234 OK`、全仓`1363 OK`。本批没有写registry/manifest artifact、没有改变allocator黄金行为，
  也未访问或部署VPS、读取私有账户、调用订单接口、修改账户/凭据/systemd/cron/live开关；真实生产仍由legacy
  dispatcher掌握。

- **2026-07-19架构Phase A第三批dry dispatcher标准适配层已在本地完成。** `risk/validation.py`按现有
  `pilot_dispatcher._finalize_plan()`的14个字段重算legacy plan hash，并强制dry mode、projection decision ID和
  `PortfolioTarget`目标一致；`risk/legacy_dispatch.py`把通过验证的artifact转换为标准`RiskDecision`，legacy blocker、
  hash篡改或trace错链全部归零批准目标并禁止增加风险，10%回撤清仓则只允许减仓。`execution/legacy_dispatch.py`生成
  新的确定性client ID并保留原数量、方向、reduce-only、保护止损、撤单、retained stop、预期仓位和对账容差；
  `PlannedCancellation`使撤单成为一等trace动作，`OrderPlan`固定reduce -> increase -> cancel protection -> submit
  protection全局顺序。黄金对照忽略迁移期client ID变化后，3笔market和3笔STOP_MARKET经济行为零差异。聚焦
  `47 OK`、MiniTrend`234 OK`、全仓`1350 OK`。这只是内存dry-plan兼容桥；当前VPS真实行为仍完全由legacy
  `mini_trend/pilot_dispatcher.py`拥有，本轮未访问或部署VPS，未调用私有API/订单接口，也未改账户、凭据、
  systemd/cron或live开关。

- **2026-07-19架构Phase A第二批标准trace合同已在本地完成。** 新增确定性trace ID及`MarketSnapshot ->
  StrategyIntent -> PortfolioTarget -> RiskDecision -> OrderPlan`纯对象链；所有对象都有来源ID和内容hash，blocker目标
  必须归零、Risk违规不能允许加仓、每个PlannedOrder绑定source decision IDs且OrderPlan强制先减后加。
  Base adapter现在输出schema v1、strategy version、projection decision ID、snapshot ID、reason codes和
  `intent_hash`；旧schema 0仍兼容但不能生成标准PortfolioTarget。
  Base当前snapshot只是绑定data/rules/evidence的过渡reference，明确没有嵌入funding值或账户snapshot，不能作为实盘
  放行证据。该批次当时为聚焦`53 OK`、MiniTrend`234 OK`、全仓`1340 OK`。现有VPS dispatcher、账户、订单、
  systemd/cron和live状态均未改变；后续进度以紧邻上方的第四批状态为准。

- **2026-07-19架构Phase A首批代码迁移完成，行为保持不变。** 原先混在
  `portfolio_governance.py`的职责已拆到`contracts`、`governance`和`portfolio`，Base projection适配器进入
  `strategies/base.py`；两个旧路径都保留为显式兼容导出。核心包不依赖ccxt、settings、executor或交易所适配器，
  allocator迁移前后的黄金hash一致。该批次当时为聚焦`46 OK`、MiniTrend`234 OK`、全仓`1333 OK`；后续标准
  trace schema进度以紧邻上方的第二批状态为准。此首批仅为Mac本地源码重构，没有部署VPS、修改账户、调用订单
  接口或改变live状态。

- **2026-07-19 owner要求把现有代码、生产边界和`qount.alyaloale.com`统一为可扩展个人量化系统。**
  新的[系统架构设计](../system-architecture-design.md)固定模块化单体、标准trace IDs、SQLite WAL运行账本+
  chain JSONL审计、确定性Risk/Execution、UNKNOWN订单恢复、三方对账、静态Dashboard read model、分级通知、
  deterministic日报和LLM只读分析旁路。当时前端仍消费legacy X4/CxD/CTA JSON并在浏览器重算实时PnL；现已由上方
  Phase A第七批在仓库内替换为只读v1模型，随后已接本地冻结Phase B ledger快照；两者都尚未部署VPS或接legacy生产运行链。
  多策略allocator仍未部署。

- **2026-07-18 owner重设跨主机拓扑：Mac研究、Windows外置盘存储、WSL计算、VPS运行。** 权威大数据和
  最终artifact迁往`E:\qount_data\qount`（WSL为`/mnt/e/qount_data/qount`）；WSL的7945HX 32线程与RTX
  4060 8GB承担大型CPU/GPU任务，ext4只留代码、venv和任务后清理的scratch。Mac不再长期保存全量`state/`，
  VPS只保留`x4/cxd/rv/log/audit`等最小runtime state。外置盘是ExFAT，经WSL表现为drvfs/9p，因此SQLite、
  venv和高频小文件计算不得直接在盘上运行。Mac/WSL历史state已通过SHA-256 manifest和回读验证迁移并删除
  源大副本；VPS非runtime研究数据已清理，源state约16MiB。WSL的PyTorch CUDA、tabular/HMM依赖和4060
  矩阵smoke均已通过。迁移结果、目录合同和删除门见[storage-topology.md](../storage-topology.md)。A10产物已
  回收并可释放，后续默认使用本地4060；WSL代码只在计算接口或依赖变化时按需更新。

## 当前结论

```text
ETH-only research-only
bottom_line + future + ETH/USDT + 1 position
hourly model off
setup model phase6 on
legacy line A/X4/C×D/MiniTrend execution disabled on VPS
§7 profit-pursuit halted (2026-06-06, owner-confirmed)
L3 restart (stablecoin/chain-TVL + AI) falsified (2026-06-06): L3a + L3b both fail breadth-adjusted IC
L1 restart (cross-asset trend, attacks BR): S1 breadth PASSED (eff-breadth 2.97); S2 trend REAL+robust but retail-ETF magnitude ~0.4 net Sharpe < 0.5 gate (single + ensemble); FROZEN as partial success (2026-06-06, owner-confirmed) — first real positive edge, paused per §7, no broker on sub-gate evidence
L4 restart (cross-exchange funding arb, changes the game): S1 falsified (2026-06-06): gross cross-venue spread REAL +7.4%/yr but break-even 2.7bps/leg, pair churns every ~12h, net deeply negative at taker cost, required_maker_fill ~0.93 (single-venue CARRY maker wall, cross-venue)
GLOBAL §7 honest-stop ACCEPTED (2026-06-06, owner-confirmed): all three restart lines (L3/L1/L4) exhausted; stop pursuing timing profit; durable research assets frozen. Next restart needs owner-authorized NEW infra (futures broker=L1-S5 / options venue=L5 / multi-venue accounts=L4-S2), none pursued now.
2026-07-16 owner priority reset: freeze A-share ETF work and resume crypto research priority; restart is research-only from a new structural information source and ex-ante protocol, while all failed contracts, paper/live, and production cron remain closed.
2026-07-17 options-DVOL new-source discovery failed 0/3: median rank IC -0.048945, mean net BTC-beta residual -42.014016%; 2025 replication and forward OOS remain unconsumed, A10/paper/live stay closed.
2026-07-17 follow-on source audits blocked at G0: Deribit public history cannot reconstruct a point-in-time option surface; Tardis validates liquidation/replayable-L2 semantics but anonymous history and the 32 GiB L2 cache budget do not support a historical experiment. No preregistration was created.
2026-07-17 owner selected low-frequency existing-data path: frozen MiniTrend TOP3 spot long/cash daily forward is active on Mac; first 16/16 completed bars are all cash with gate shut, verdict collect_forward, paper/live remain closed.
2026-07-17 owner directed that new capital architecture must use the USD-M futures wallet only, with carry removed; this is research-only and does not authorize VPS or live changes.
2026-07-17 retired X4 live audit completed: pre-withdrawal strategy return was -2.166870% (474.07 vs 484.57); June-end gain +3.052191% was followed by a 25.29 USDT July rebound giveback. The audit found 37 post-inception placed orders, 5 exact duplicate orders, 8 same-bar direction-flip groups, and 66 unknown-capital fail-closed runs.
2026-07-17 UM futures recovery overlay was preregistered and rejected on consumed historical diagnostics: incremental net return was -8.418465pp, -2.103736pp, and +0.170316pp across 2021-2022, 2023-2024, and 2025-2026; only 1/3 segments were positive and the first segment materially worsened drawdown. No rescue tuning, paper, live, carry, or shorting.
2026-07-17 retired X4 headline attribution found the old daily backtest only matched funding at bar-open timestamps and omitted the 08:00/16:00 settlements. Correct all-settlement returns are S3 +84.93% (not +115.18%) and S4 +70.77% (not +98.39%); the remaining return comes mainly from daily long-only bull-regime exposure, not a 2x leverage edge or stable alpha.
2026-07-17 UM base-trend forward contract was superseded before consuming any result by v0.2 (`20260717T121646Z-mini-trend-um-base-forward-preregistration`), which explicitly binds the implemented 3xATR daily chandelier. No result has been consumed and no paper/live transition is allowed.
2026-07-17 UM base v0.2 freshness check found latest common cached completed bar `2026-06-18`, zero bars on or after the `2026-07-17` forward start, verdict `await_forward_data`; no forward return was evaluated.
2026-07-17 existing UM history benchmark decomposition classified the base trend as a low-beta risk wrapper, not stable positive alpha: it outperformed BTC 1x and TOP3 equal-weight in 2/3 discovery segments, but had positive absolute return in only 1/3 and lagged both sharply in 2023-2024.
2026-07-17 UM 2.0% risk-tier was preregistered and rejected: full-window return improved from +66.51% to +103.29% with Sharpe 0.974 and maxDD 21.21%, but 2025-2026 worsened from -2.02%/8.04% DD to -5.31%/13.78% DD, breaching both preregistered weak-regime gates. The selected strategy remains UM base v0.2 at vol_target 1.5%; no midpoint rescue tuning.
2026-07-17 UM bull/range/bear overlay was preregistered and rejected: selective 2.0% risk in strong-bull bars lifted full-window return from +66.51% to +85.94%, but Sharpe slipped by 0.001 and 2025-2026 worsened to -5.13% with 12.45% DD. Regime thresholds are not retuned; base v0.2 remains selected.
2026-07-17 UM stop-latched regime boost was preregistered and rejected by one gate: full return/Sharpe improved to +88.41%/0.945 and 2025-2026 improved to -1.83%, but full maxDD worsened 1.418pp versus the preregistered 1pp limit. It is the strongest consumed-history mechanism, not an OOS or deployment candidate; base v0.2 remains selected.
2026-07-17 lagged-funding cost veto passed all preregistered historical gates: 17 unlatched strong-bull bars above 50% annualized completed-day median funding were reduced from 2.0% to 1.5%, producing +88.95%/Sharpe 0.965/maxDD 18.11%. Verdict retain_historical_funding_veto_candidate means preferred consumed-history candidate only; events cover 2021/2023-2024 but not 2025-2026, and paper/live remain closed.
2026-07-18 preregistered paired 20-day circular block bootstrap retained the historical funding-veto candidate conditionally: across 5,000 paired paths, probabilities of higher terminal return, higher Sharpe, and lower maxDD versus Stop-Latch were 58.90%, 86.82%, and 75.72%. This is realized-path sensitivity evidence, not signal-path resimulation or OOS; base v0.2 remains selected and paper/live remain closed.
2026-07-18 exact six-group Shapley attribution supported the historical cost-veto mechanism: funding savings contributed +0.443pp of the +0.536pp terminal uplift, price exposure +0.097pp, and trading cost -0.004pp. However, +1.842pp on the 17 veto dates was offset by -1.306pp downstream across 696 divergent non-event bars, so full state-path replay is mandatory for any future validation.
2026-07-18 execution-state decay audit found 696 divergent state bars in 18 spells: all divergence involved target weights, while trail highs, cooldowns, and latch state never split. Every veto first resynchronized after 14-56 days (median 46), but only the final event achieved stable resynchronization before the next boundary, after 324 days; equity/deadband can re-diverge after an apparent sync.
2026-07-22 future-only dual-state shadow monitoring v0.2 remains frozen: Stop-Latch and Funding Veto both start from 400 USDT cash on 2026-07-19 after 200 signal-only warmup bars, with separate equity/state hashes and an append chain. The WSL/external refresh now has complete TOP3 daily bars through 2026-07-21, but current-month public funding REST remains unreachable directly from WSL (0/3 symbols). The latest offline report therefore has evaluation_bars=0, strategy_results_evaluated=false, and verdict await_complete_shadow_inputs; missing funding was not zero-filled and no Sophie home proxy was used.
2026-07-18 owner superseded the one-month pilot contract with exact 300 USDT capital, no account-level daily loss stop, and a 10% cumulative pilot drawdown halt. TOP3 UM long/cash, 1x isolated, one-way, gross<=1, 3xATR symbol stops, three completed-bar cooldown and 35% deadband remain fixed. Base v0.2 remains the live control; the 2.0% global risk tier is now the primary profit shadow and Funding Veto the secondary shadow.
2026-07-18 the 300 USDT consumed-history comparison found Base/Risk2/Stop-Latch/Funding-Veto returns of +63.19%/+92.68%/+73.43%/+75.71%. Risk2 led return with nearly unchanged Sharpe versus Base, but had 21.89% full-window maxDD, lost 2.87% in 2025-2026, and breached the 10% line in 1/59 non-overlapping 30-day pilots. It is a forward priority, not live permission.
2026-07-18 VPS public routing and current TOP3 filters passed after the exchange session stopped inheriting the broken environment proxy. The stored key still returns Binance -2015, so permissions, balance, positions, one-way, open orders and 1x isolated state remain unknown. The legacy live guard was disarmed; independent read-only preflight and pure dry-plan artifacts fail closed with zero order intents. No order endpoint was called and cron remains disabled.
2026-07-19 direct VPS diagnosis superseded the ambiguous proxy/key reading: with every proxy variable unset, the repo-external production egress (PH) reaches Binance UM public APIs. The invalid old credential was removed without backups; a replacement test credential was then installed by no-echo input only on the VPS, with Mac remaining credential-free and both `.env` files mode 0600. Binance now accepts the key and confirms reading/Futures/IP restriction enabled and withdrawals disabled, but Spot/Margin remains enabled, available pilot capital is below 300 USDT, and BTC/ETH/BNB are isolated 2x rather than 1x. The credential was transmitted in conversation and is not final-live eligible; rotate it directly on the VPS after correcting permissions and account configuration.
2026-07-19 fixed-capital periodic allocation discovery found that line-based weekly DCA/DCR did not beat buy-and-hold on BTC, TOP3, or SPY. Six Logistic/HGB action-label models all lost to constant class priors; the apparent TOP3 HGB +216.99% path is rejected because every Brier fold lost and performance was concentrated in 2025.
2026-07-19 tokenized-equity inventory found 11 active Binance TRADIFI_PERPETUAL contracts plus mapped *B spot tokens, while Bybit exposes xStocks spot and equity linear contracts. These are distinct claim/derivative structures, not interchangeable cryptocurrencies.
2026-07-19 Binance TradFi weekend convergence is weak discovery evidence only: 126 symbol observations collapse to 18 independent next-cash-session dates; equal-weight date-clustered return is +3.7516%, maxDD 4.0029%, and bootstrap P(mean>0) 71.16% after 24 bps round-trip cost and funding. The earlier +29.69% sequential cross-sectional compounding was capital double-counting and is explicitly void.
2026-07-19 owner planned 1000 USDT for a multi-strategy virtual-sleeve architecture: Base remains the control; Equity Mapping, LiquidTrend, Funding Event and LLM information features remain research/shadow until separately promoted. This plan does not supersede the 300 USDT pilot or authorize funding, orders, private API, or cron.
2026-07-19 LiquidTrend10 G0 blocked the raw ten-coin cross-sectional hypothesis before any return backtest: common daily coverage is 99.7186%, funding and liquidity pass, but mean absolute pairwise correlation is 0.661578 and effective breadth only 1.437979; available runtime UM rules cover 4/10. No momentum score or strategy PnL was evaluated.
2026-07-19 Equity Mapping G0 v0.3 now enforces synchronized pre-decision mapped/cash/USDTUSD quotes, bid/ask gap bounds, point-in-time corporate-action normalization, sourced stress scenarios, stable economic-event IDs and revision hashes. The only current G0 run is a two-row synthetic plumbing fixture with one independent cash date; it is not market evidence and cannot enter shadow, paper or live.
2026-07-19 Equity Mapping G0 v0.4 adds an immutable raw-collection gate: real point-in-time inputs must link every mapping/quote/calendar/corporate-action/context/stress source hash to a same-cash-date sealed manifest whose raw response bodies pass readback SHA-256. The first readiness artifact targets 2026-07-20 09:24:30-09:25:00 New York (13:24:30-13:25:00 UTC) and currently says await_collection_window; it contains no market observation, PnL, strategy trial or execution authority.
2026-07-19 Equity Mapping public source-capacity v0.1 tested ten bounded no-proxy probes without creating a market event. Only Nasdaq market-info passed the cash-calendar role; Binance mapping/bookTicker and four USDT/USD venues were transport-unavailable from the current Mac route, while Nasdaq cash quote was delayed with no executable bid/ask or quote-event timestamp, and its split/earnings responses could not bind target-date absence. Seven of eight roles remain blocked, including an unassigned stress source; trial count stays 143.
2026-07-19 VPS order-free MiniTrend forward/paper timer is active. Latest run refreshed public inputs, then preflight v0.3 proved valid credentials, one-way mode, a flat account and zero open orders without mutation. It remains blocked on Spot/Margin permission, capital below 300 USDT and TOP3 isolated 2x instead of 1x; readiness v0.4 blocks 10 gates and live_orders_allowed is false. Forward/paper counts remain zero because the frozen start bar is not completed; no order endpoint, dry dispatcher or legacy cron was enabled.
2026-07-19 the owner superseded the fixed 300 USDT and credential-rotation requirements with an audited 100-1000 USDT pre-arm range; on 2026-07-21 the owner superseded that range for this canary with a strict 100 USDT principal. The current VPS-only credential is accepted for production; Reading/Futures/IP restriction are enabled, Withdrawals disabled, and owner-accepted Spot/Margin permission no longer blocks. TOP3 are now isolated 1x, one-way, flat, with zero open orders. No credential bytes or exact production IP are stored in the repository.
2026-07-19 the MiniTrend-specific dispatcher is deployed order-disabled. It binds current preflight/projection/rules/readiness/source hashes, verifies deterministic decision and execution-state hashes, reads regular and conditional order books, rejects unmanaged positions/orders, creates deterministic client IDs, plans Binance STOP_MARKET closePosition protection, records append-only row/chain hashes, reconciles resulting positions/stops, and implements 10% peak-equity flatten-then-halt. Live additionally requires ready_for_manual_final_arm, an exact readiness-bound 0600 arm file, a separate token, the independent MiniTrend live switch and matching arm confirmation; none exists or is enabled.
2026-07-19 latest VPS run `/root/qount/state/mini_trend/forward/runs/20260719T091232Z` completed successfully with capital 488.89481071 USDT. Its independent systemd runtime proof passed with all live switches false. The account snapshot passed; dry dispatch returned await_dispatch_decision with zero market/stop intents, zero journal rows, exchange_mutation_attempted=false and live_orders_allowed=false. Readiness now has exactly five blockers, all requiring future completed bars: minimum_forward_pairs, minimum_forward_active_bars, minimum_paper_days, minimum_dry_run_days, and complete_funding_journal.
2026-07-19 the multi-sleeve portfolio boundary now has a standard order-free StrategyIntent, a causal Base projection adapter, deterministic stress-budget scaling and fail-closed allocation. Gross, per-symbol cap, correlation-cluster, allowlist and minimum-notional checks run before any order plan; minimum notional is checked per standalone sleeve before netting so Base cannot subsidize an unexecutable alpha sleeve. The current VPS dispatcher still accepts Base only and was not changed or redeployed.
2026-07-19 formal trial 144 tested a distinct long-only Capitulation Rebound event sleeve after preregistration: Base gate off, all TOP3 negative, median 5-day return <=-8%, volatility score <=-1.5, next-open entry, three-day hold, 3xATR stop and 24bps round trip. On 2021-01-01..2026-07-17 consumed UM daily history it produced 18 independent episodes, 44.44% winners, median net event return -1.8747%, compound price+cost return -36.4990%, maxDD 39.5163% and median BTC-beta residual -0.5374%. Five of seven gates failed; verdict reject_historical_capitulation_rebound. No threshold/holding rescue, funding replay, shadow, paper or live. Formal strategy trial count was 144 at that point and is now 145 after the 2026-07-25 multi-speed trial.
```


当前结论中 **2026-07-16 加密重启之前** 的历史详细条目（line A / GRID / L1–L6 / 早期加密）已移入 [archive/current-archive-line-a-readings.md](../archive/current-archive-line-a-readings.md)；以下只保留 2026-07-16 起的当前结论。

- **2026-07-17 旧 X4 高收益已完成逐机制归因，并发现日线 funding 漏计。** 离线 artifact
  `20260717T121616Z-mini-trend-high-return-attribution` 逐阶段复现 2021-01..2026-05：1h→1d 为
  S3/S4 增加 `+61.46/+57.94pp`，去掉空头再增加 `+59.42/+63.40pp`，SMA200 闸增加
  `+48.56/+58.28pp`；波动率定仓和 S4 吊灯进一步改善风险形态。旧日线回测只按
  `funding_ts == daily bar open` 匹配，每天只计 00:00、漏 08:00/16:00。完整三次结算后，S3
  `+115.18% -> +84.93%`、Sharpe `0.665 -> 0.559`、maxDD `29.43% -> 31.50%`；S4
  `+98.39% -> +70.77%`、Sharpe `0.698 -> 0.570`。2x 上限相对 1x 对 S3/S4 仅
  `-1.17/+2.54pp`，且两者 Sharpe 都未改善，不能把旧高收益解释成杠杆 edge。同期正确 funding 的
  BTC 1x/TOP3 EW 为 `+37.72%/+355.40%`、maxDD `78.93%/73.59%`，说明旧趋势是低 beta 牛市择时，
  不是稳定超额。当前 UM base 全窗 discovery 为 `+66.51%/Sharpe 0.903/maxDD 17.28%`，平均有效 gross
  `0.182`；只作为选择 no-carry long/cash 控制线的历史依据，不能替代 future OOS。
- **2026-07-17 UM `vol_target=2.0%` 收益风险档已预登记、回测并拒绝。** v0.1
  `20260717T123954Z-mini-trend-um-risk-tier-preregistration` 在首次真实运行中暴露 deadband 后组合 gross
  超过 1.0，风险引擎 fail-closed；失败 artifact `20260717T124305Z-mini-trend-um-risk-tier-historical`
  为 `reject_execution_contract_incomplete`。v0.2 在读收益前只补“组合 cap 优先，active targets 按运行时
  floors 归一化到 gross=1”规则，预登记 `20260717T124409Z-mini-trend-um-risk-tier-preregistration`；最终
  artifact `20260717T124433Z-mini-trend-um-risk-tier-historical`。全窗 control/candidate 为
  `+66.505396%/+103.292645%`，Sharpe `0.902770/0.973606`，maxDD `17.284508%/21.211666%`，平均 gross
  `0.182424/0.239709`，这些门通过；但 2025-2026 收益 `-2.018860% -> -5.313845%`，candidate maxDD
  `13.782484%`，相对 control 恶化 `5.739864pp`，同时触发最差分段收益 `>=-5%` 与回撤恶化 `<=5pp`
  两条杀线。verdict=`reject_historical_risk_tier`。不试 1.75%/1.8% 或改门救援；选择仍是 UM base v0.2
  `vol_target=1.5%`，risk-tier 不进入 forward/paper/live。
- **2026-07-17 牛市/震荡过渡/熊市三阶段 overlay 已预登记、回测并拒绝。** 在读取候选结果前生成
  `20260717T132304Z-mini-trend-um-regime-overlay-preregistration`，只用完成日线做因果分类：strong bull 要求
  `BTC>SMA200 + BTC SMA20>SMA60 + TOP3 breadth>=2/3` 并使用已被全局拒绝的 2.0% 风险档；base 总闸已开但
  不满足强牛时为 transition/range，保持 1.5%；总闸关闭时 bear/cash。所有 funding、10bps+2bps、filters、
  3xATR stop、3-bar cooldown、gross<=1、no carry/short/leverage boost 不变。最终报告 artifact
  `20260717T132757Z-mini-trend-um-regime-overlay-historical` 只读已有缓存：全窗 control/candidate 收益
  `+66.505396%/+85.937218%`、Sharpe `0.902770/0.901776`、maxDD `17.284508%/19.297611%`、平均 gross
  `0.182424/0.227027`。2023-2024 增收 `+15.488647pp`，但 2025-2026 从 `-2.018860%/8.042619% DD`
  恶化为 `-5.128630%/12.445085% DD`；强牛阶段本身由 `-1.454390%/5.996161% DD` 恶化到
  `-3.910642%/9.033857% DD`，最差日 2025-10-10 从 `-3.644761%` 放大到 `-4.878515%`。Sharpe、分段
  回撤恶化和弱段收益三门失败，verdict=`reject_historical_regime_overlay`。不增加确认天数、不改 breadth/
  均线、不试中间风险档；选择仍是 base v0.2 1.5%，overlay 仅留研究证据。
- **2026-07-17 strong-bull 风险增益 stop latch 修复了弱段，但仍按预登记回撤门拒绝。** 新候选不改
  strong-bull/transition/bear 分类、不加数值阈值：每个连续 strong-bull 初始仍用 2.0%，一旦任一币触发既有
  3xATR stop，从下一根完成日线起只撤销增益、退回 base 1.5%；只有先出现非 strong-bull bar，后续重新进入
  strong-bull 才解锁。预登记 `20260717T134653Z-mini-trend-um-regime-stop-latch-preregistration`，contract/
  protocol hash `8198c38e...3759a` / `18b62218...2c8df`，固定全窗增收 `>=10pp`、Sharpe 不降、全窗 DD
  相对 base 恶化 `<=1pp`、任一段 DD 恶化 `<=2pp`、弱段收益最多落后 `1pp`、平均 gross `<=0.23`。
  最终 artifact `20260717T135551Z-mini-trend-um-regime-stop-latch-historical`：全窗 control/candidate
  `+66.505396%/+88.414042%`、Sharpe `0.902770/0.945436`、maxDD `17.284508%/18.702705%`、平均 gross
  `0.182424/0.218771`；22 个 strong-bull stop、11 次真实 latch entry、535 boosted/149 latched bars，
  filters=1.0、0 duplicate、0 same-bar reentry。2025-2026 从未加锁 overlay 的 `-5.128630%/12.445085% DD`
  修复到 `-1.833021%/9.855771% DD`，也略优于 base `-2.018860%`；但全窗 DD 相对 base 恶化
  `1.418197pp`，超过预登记 `1pp`，回撤区间为 `2024-03-13..2024-10-25`。其余门全部通过，仍不得改门；
  verdict=`reject_historical_regime_stop_latch`。这是当前最强 consumed-history 机制证据，但不是 OOS、paper
  或 live 资格，选择仍为 base v0.2。
- **2026-07-17 owner 外部建议经证据分流后，lagged-funding 成本 veto 成为首个全门通过的 UM 历史候选。**
  没有整包采用链上/宏观/ADX/ML/动态止损建议：ADX 已被本项目 walk-forward 否决；动态 ATR、梯度 deadband、
  超1x gross 和 carry 会引入新参数或违反约束；链上/宏观/情绪需先过 point-in-time/授权/发布时点 G0；ML、
  Markov 和叙事选币推迟到简单确定性因子有独立验证之后。唯一立即实验是已有缓存可因果验证的 funding：沿用
  stop-latch，只在未锁定 strong-bull 中读取上一完整持有日已结算 funding；TOP3 日 funding 中位数简单年化
  `>50%` 时，本 bar 只撤销2.0% boost、退回1.5%，缺失 funding 同样 fail-closed 到1.5%。该阈值来自owner
  提供的外部假设且在读取结果前固定，不做网格；funding 是成本过滤，不是 carry alpha。
- 预登记 `20260717T144609Z-mini-trend-um-funding-veto-preregistration`，contract/protocol hash
  `f56bafc2...75ed5` / `a777ac71...c31c7`，明确 mechanism-family trial=2、future funding=false、历史通过
  不能 promotion。最终 artifact `20260717T145148Z-mini-trend-um-funding-veto-historical` 只读本地缓存：
  base/stop-latch/funding-veto 全窗收益 `+66.505396%/+88.414042%/+88.950393%`，Sharpe
  `0.902770/0.945436/0.965235`，maxDD `17.284508%/18.702705%/18.105121%`；相对 base DD 只恶化
  `0.820613pp <=1pp`，所有预登记门通过。候选平均/max gross `0.216925/0.903255`、funding coverage=1.0、
  17 veto bars、0 missing、11 latch entries、0 duplicate/reentry，verdict=`retain_historical_funding_veto_candidate`。
- 事件审计没有单点垄断：17次中10次次日直接改善、7次变差，中位直接增量 `+0.055483pp`，最大正事件占
  全部正贡献 `26.58%`。但分布只有2021六次、2023-2024十一次、2025-2026零次；后者 `-1.833021%`
  完全来自stop-latch而非funding veto。故新路线把它冻结为“首选历史候选/未来独立验证对象”，不是稳定跨周期
  funding alpha，更不进入paper/live；正式选择仍为base v0.2。
- **2026-07-18 Funding Veto 条件路径稳健性审计通过预登记门，但收益优势仍弱。** 在读取 Bootstrap 结果前生成
  `20260717T151224Z-mini-trend-um-funding-veto-robustness-preregistration`，绑定 Funding Veto 预登记、历史报告
  SHA、全窗数据 hash 和 UM rules hash；方法固定为 paired circular moving-block bootstrap，block=20完成日、
  samples=5000、seed=`20260717`，要求候选终值收益/Sharpe/更低maxDD胜率都 `>=55%`，且三项增量中位数
  分别严格 `>0/>0/<0`。最终 artifact
  `20260717T151318Z-mini-trend-um-funding-veto-robustness-historical` 对1776个同日净收益观测重放，原报告
  reference/candidate 三项指标差均为0；胜率为 `58.90%/86.82%/75.72%`，增量中位数为
  `+0.462935pp/+0.019102/-0.226270pp`，7门全过，verdict=
  `retain_historical_candidate_after_conditional_bootstrap`。但收益增量5%-95%区间为
  `-4.187260..+4.443793pp`，maxDD增量也到 `p95=+0.295595pp`；这说明风险调整质量比终值收益更可信，
  不能宣称稳定收益alpha。Bootstrap只重采样原始已实现日收益，不在合成市场路径重算regime/latch/deadband，
  仍是`discovery_pool`条件审计，不是OOS/forward/paper/live资格；base v0.2仍是正式选择。
- **2026-07-18 Funding Veto 精确收益归因支持成本过滤机制，同时暴露强路径反噬。** 在读取归因前生成
  `20260717T153223Z-mini-trend-um-funding-veto-attribution-preregistration`，绑定原历史与Bootstrap artifact、
  17个事件日期、全窗数据和UM rules；固定把事件日/其余路径各拆为价格、funding、交易成本六组，对终值复利
  穷举64个coalition做精确Shapley，不允许调整组或顺序。最终报告
  `20260717T153320Z-mini-trend-um-funding-veto-attribution-historical` 重放1776日，reference/candidate历史指标
  差均为0，逐日净收益恒等式误差 `6.94e-18`、分组闭合误差 `5.20e-18`、Shapley闭合误差0，17/17事件匹配，
  7个机制门全过，verdict=`historical_cost_veto_mechanism_supported`。
- 六组结果揭示两层机制。按经济组件，`+0.536350pp` 终值增益由 funding节省 `+0.443474pp`（82.68%）、
  价格暴露 `+0.096965pp`（18.08%）和额外交易成本 `-0.004089pp`（-0.76%）构成，支持“成本过滤”而不是
  carry alpha。按时间，17个veto事件日本身贡献 `+1.842439pp`，其中价格避损 `+1.590752pp`、funding
  `+0.357244pp`、成本 `-0.105557pp`；但其后路径贡献 `-1.306088pp`，主要是价格暴露 `-1.493787pp`，
  被后续funding/成本 `+0.086231/+0.101468pp` 部分修复。17个事件最终造成713个差异日，其中696个为非事件
  日，说明deadband、权益和仓位状态会长期传播一次veto。未来OOS必须从相同初始状态完整重放两策略，不能用
  “17个次日收益”近似；本归因仍是已消费历史会计，不改变base v0.2正式选择或paper/live关闭状态。
- **2026-07-18 Funding Veto 状态衰减审计显示“首次同步”远弱于“稳定同步”。** 结果读取前生成
  `20260717T155209Z-mini-trend-um-funding-veto-state-decay-preregistration`，绑定历史与归因artifact、17个事件、
  713/696收益差异计数和UM rules；固定比较决策阶段、实际vol target、目标权重、吊灯高点、剩余冷却和latch
  内部状态，数值容差 `1e-12`。权益不纳入执行状态同步，否则已实现盈亏会让同步永久不可能；净收益差异另行
  严格核对。最终报告 `20260717T155312Z-mini-trend-um-funding-veto-state-decay-historical` 精确重放旧指标，
  state coverage=1.0、返回差异713/下游696与归因完全一致，7门全过，verdict=
  `historical_execution_state_decay_resolved`。
- 1776日中执行状态差异696日（39.19%）、收益差异713日（40.15%）。状态差异形成18个spell，长度
  `1..100`日、中位27.5日；收益差异16个spell，长度 `4..101`日、中位31.5日。17个事件实际聚在5个含事件
  spell，另有13个没有新veto的再发散spell。每个事件都曾在14-56日后首次同步，中位46日，但12/17在首次同步
  前已有下一次veto；除最后事件外，没有事件能在下一次veto边界前保持稳定同步。最后一次2024-12-05事件虽
  35日首次同步，却要到2025-10-25、即324日后才达到窗口内稳定同步。
- 差异facet进一步定位：risk stage和vol target各只差17日，目标权重差696日；吊灯高点、冷却和latch内部状态
  均为0差异。因此传播不是止损状态错误，而是事件改变目标权重后，deadband与不同权益路径让权重长期保留并
  在表面同步后再发散。未来shadow forward必须同时持久化两套权益、目标权重和完整决策状态；“当前权重一样”
  不能判定路径已结束。本审计仍只描述已消费历史，不提升Funding Veto层级。
- **2026-07-18 Funding Veto双状态shadow-forward v0.2已在新结果前冻结，当前严格等待完整数据。** 初版v0.1
  在0根eligible、未评估收益时发现月内funding缺失会被回测器按0计入收益，故保留旧artifact但在首根结果前
  supersede。当前预登记`20260717T162621Z-mini-trend-um-funding-veto-shadow-forward-preregistration`绑定base v0.2、
  状态衰减artifact和UM rules；contract/protocol hash `3c6fe31f...82ea69` / `e0f525a9...52fad4`。起始日固定为
  `2026-07-19`：此前200根完成日线只用于SMA/ATR信号warmup，不携带任何历史交易、权益、吊灯、冷却或latch
  状态；Stop-Latch reference与Funding Veto candidate均以400 USDT、全现金同时启动。每根eligible日线保存
  两套权益、价格/funding/成本净收益、完整执行状态、各自state hash、row hash和append chain hash，首次同步后
  也不得停止。
- v0.2只评估从起始日开始价格连续、且每个决策日和持有结果日TOP3各至少3次funding结算的完整前缀；月内
  funding缓存未齐时保持`strategy_results_evaluated=false`或停在上一个完整前缀，绝不按0成本补齐。CLI结束月份
  随UTC当前月滚动，但offline fetch仍拒绝网络。证据复核门固定为至少60个完整decision-outcome pair、两路径
  各10根active、至少1次真实funding veto、candidate funding coverage=1.0、maxDD `<=15%`、数据无gap、
  filters/重复决策/同bar重入/状态journal全干净；不设候选必须跑赢门。即使全门通过也只允许
  `review_shadow_forward_evidence`，永不自动进入paper/live。原始freshness artifact
  `20260717T162632Z-mini-trend-um-funding-veto-shadow-forward`当时只读本地2025-12..2026-07缓存：
  TOP3共同最新日为`2026-06-18`，起始日后0根输入、0个结果pair，`strategy_results_evaluated=false`，没有
  evaluation或journal，verdict=`await_shadow_forward_data`；后续WSL刷新结果见下一条。这不是候选失败，
  也没有消费future OOS。
- **2026-07-18 WSL公开UM输入刷新层已补齐并完成首次外置盘刷新。** 新模块把网络获取与冻结shadow回放拆开：
  下载只在WSL进行，回放仍用offline fetch；Binance Vision月包/日包和公开funding快照分别落在外置盘
  `datasets/binance_um_shadow/v1/{cache,funding_snapshots}`，标准HTTP(S)代理只能通过仓库外环境变量显式传入，
  artifact不保存代理URL/token。本次从已迁移缓存按字节复用2025-12..2026-05，直连补齐2026-06月包与
  2026-07-01..17 TOP3 UM日包，共`93 files/80,144 bytes`，dataset manifest content hash
  `8dcce911...13746`，输入data hash `abdd8736...8c207`。当月funding官方REST在WSL直连全部超时，故
  refresh verdict=`await_complete_shadow_input_transport`、完整symbol `0/3`；没有空列表通过、没有把缺失
  funding写成0、没有使用Mac/VPS或苏菲家宽代理。
- 新离线shadow artifact `20260718T080849Z-um-funding-veto-shadow-forward`读取canonical缓存后，TOP3共同最新
  完成日推进到`2026-07-17`。由于冻结起点为`2026-07-19`，仍是0个forward pair、
  `strategy_results_evaluated=false`、无evaluation/journal和`await_shadow_forward_data`；本轮不增加策略
  trial，累计仍为143。环境锁`20260718T081243Z-qount-compute.json`的manifest/code bundle hash为
  `03be436e...7823`/`ff78f5e8...bbc6`。
- **2026-07-18 owner把一个月小资金实盘合同更新为300 USDT、无账户单日止损、10%累计回撤熔断。** 新合同
  不复用旧X4/C×D：真钱仍只允许Base v0.2，TOP3 USD-M long/cash、日线、1x逐仓、one-way、effective
  gross `<=1`、35% deadband、3xATR逐币吊灯和3根完成日线冷却。每日最多一个决策批次；只有试点累计回撤
  达10%时执行flatten+halt，账户单日亏损本身不触发halt。未知余额/仓位、意外short/非TOP3仓位、错误模式、
  缺价格/funding日志、重复决策仍立即fail closed。
- **2026-07-19 owner把下一资金规模设为计划1000 USDT，并要求建设Base+结构Alpha+横截面+LLM信息的组合系统。**
  新文档[crypto-portfolio-system-plan.md](../crypto-portfolio-system-plan.md)定义Data/Research/Strategy/Portfolio/
  Execution五层、虚拟sleeve独立NAV、组合gross<=1和确定性晋级门。当前Base仍是控制组，Equity Mapping、
  LiquidTrend和Funding Event真钱风险预算均为0；1000计划不自动替代300 pilot，也不授权充值、私有API、cron或
  下单。未来若多个sleeve晋级，风险预算才从Base 100%逐步过渡到Base 50%-60%和低相关Alpha组合。
- **LiquidTrend10 v0.1在收益回测前完成G0并被容量/广度阻断。** 固定BTC/ETH/BNB/SOL/XRP/DOGE/ADA/LINK/
  AVAX/LTC，复用外置盘2021-2026 UM日线/funding：1777个BTC参考日中共同1772日，覆盖`99.7186%`；十币
  Funding规范化亚秒结算时间后全部通过，最低日quote-volume中位数约`225.47m USDT`。Binance历史结算时点
  存在1-46ms抖动，原实现把相邻日误分为2/4次，已修复且未填0。
- 全窗平均绝对相关`0.661578`、有效广度`1.437979`；2021-22/2023-24/2025-26分别为
  `1.384389/1.627722/1.276677`，均低于2.0。现有runtime UM exchangeInfo只含BTC/ETH/BNB/SOL 4/10；WSL
  直连及IPv4 `fapi.binance.com`超时，Vision替代路径404，未使用VPS中转或未知代理。最终5/9门通过，verdict
  `block_liquid_trend_g0_data_or_execution`；预留的20/60/120日score从未执行，trial=0、无PnL、无paper/live。
  最终artifact
  `/mnt/e/qount_data/qount/artifacts/experiments/20260718T164231Z-liquidtrend10-g0-v02/liquid_trend10_capacity.json`
  SHA-256 `743f83c1...2728`，manifest content hash `93206835...101c`。
- **LLM信息层已接入relay-station ChatGPT客户端，但仍未接策略。** `InformationEvent`强制HTTPS允许域、source hash、
  `published_at<=available_at<=observed_at`、实体/事件类型、数值有限性、重复审计和越权交易语言扫描；只有无错误
  事件可生成确定性event flags/numeric fields，LLM摘要和confidence不自动成为数值特征。所有batch显式
  `orders_allowed=false/paper_or_live_allowed=false`。当前默认`https://llm.alyaloale.com/v1` / `gpt-5.6-terra`，
  并发1、SDK重试0、严格五字段JSON、输入输出限长；凭据只从仓库外`~/.qount/alpha-agent.env`读取。6个离线fixture
  已覆盖五类有效事件和一次未来时点拒绝。禁用所有环境代理后的OpenAI SDK只读`GET /v1/models`返回200、16个
  模型且包含`gpt-5.6-terra`；本轮遵守relay-station配额保护规则，没有发送throwaway推理请求。模型不会自行
  获得可信联网事实：新增`official_sources.py`，强制HTTPS官方域、初始/重定向URL双校验、无环境代理、512 KB
  上限、原文SHA-256/observed time和12,000字符上下文；GitHub共享域还必须匹配显式owner/repository allowlist，
  当前只允许`binance/binance-public-data`。LLM只读取已验证正文。公共OpenAI模型指引未列出该私有
  relay slug，因此“最新”只按当前relay目录实测表述，不冒充OpenAI公共API官方推荐。
- **首个真实terra官方源审阅已完成，但只产生数据治理结论。** 无代理抓取Binance官方GitHub API README，原文
  `5144 bytes`、source hash `085ab913...f7c6`、context hash `f5072a3b...4255`；terra正确区分Spot/UM/CM的
  `aggTrades/klines/trades`、daily/monthly发布时间、`.CHECKSUM`和2025 Spot微秒时点，并把retention/rate limit
  标成来源未陈述。代码复核确认微秒归一化已有测试，但官方sidecar校验缺失；`grid/data.py`现新增
  `verified_archive_fetch`、checksum格式/filename绑定和SHA-256拒绝逻辑。现有缓存没有sidecar证据，不能追溯性
  宣称已验证。artifact为`state/research_runs/20260718T173443Z-alpha-official-source-review/`
  （SHA-256 `018195cb...4695`），明确research-only、0订单、无paper/live资格。
- **1000 USDT组合治理已从文档约定落成确定性代码。** 账户低于3000时最多一个连续live候选和一个事件最小试单；
  Signal/Standalone Executable/Portfolio Realized三类NAV分账，晋级只看Standalone；风险预算统一为压力损失贡献；
  每假设族第3个正式trial触发复盘但不阻止后续trial；查看前向结果后改规则会把该时间段降为consumed。Base 60日只作运行证据，Equity按
  独立美股交易日、Funding按episode计数。LiquidTrend首个PnL前已冻结robust rank、8币下限、121日warm-up、
  可执行bid/ask时点，并加入特征值有效维度、PC1、BTC beta、下跌条件相关和相关簇稳定性；旧G0结果仍保持阻断。
- **Equity Mapping G0 v0.3已完成合同管道，但没有新增真实市场样本。** `mini_trend/equity_mapping.py`和离线CLI
  固定纽约`09:25`决策、`09:24:30-09:25:00`三腿同步可见报价、5秒skew、USDTUSD为USD/USDT、显式venue/
  base/quote/multiplier语义、bid/ask gap上下界、split/reverse-split point-in-time归一化和带来源/时点/成本成分的
  stress scenario。只有`GapUpper<0`才是long研究候选；中点为负不够。经济事件ID与证据修订hash分离，报告重算ID
  并拒绝伪造、重复、合同hash漂移；G0永远不提供minimal-live资格，后决策`09:25:00-09:25:30`成交证据属于
  后续shadow层。
- terra红队共完成两轮有效审阅和一次最终复审，逐项与代码核验后修复中点不可成交、公司行动因子未使用、重复
  asset-event、压力比例无血缘、外部event ID受信和venue未绑定等确定性问题；未把模型对真实USDTUSD/公司行动/
  日历语义的假设当事实。最终合成fixture为2个asset-event、1个独立cash date，verdict
  `collect_equity_mapping_independent_dates`，artifact
  `state/research_runs/20260718T180643Z-equity-mapping-g0/equity_mapping_g0.json`，SHA-256
  `fd93d83a...2266`、contract hash`dcbef759...1e46`。它不计入旧18个市场日期，不计算PnL，不授权paper/live/order。
- **Equity Mapping公开source-capacity已实现，但真实现金腿仍是绑定阻断。**
  `equity_mapping_sources.py`提供bounded no-proxy fetch、Binance instrument/bookTicker、Bitstamp USDTUSD和
  Nasdaq calendar/quote/split/earnings的fail-closed parser/audit；它不替代provider-neutral raw sealing，也不在
  窗口外拼接异步报价。`20260719T065611Z-equity-mapping-source-capacity`只让cash calendar通过；其余7/8角色阻断。
  Nasdaq quote为`isRealTime=false`且bid/ask=`N/A`，只有last-trade时间而无quote-event时间；split响应混入目标日外
  rows，earnings rows不绑定事件日期。Binance及Coinbase/Kraken/Bitstamp/Gemini在当前Mac无代理路径统一记录为
  `transport_unavailable`，不能读成provider不存在或语义被否证。artifact SHA-256 `ee0799d7...09d58`，raw manifest
  content hash `aa91e8d1...466d7`；该审计为`trial_count=0/market_event_created=false/orders_allowed=false`。
- **2026-07-27 owner已移除仓库外`qount-doc-autopilot`。** 项目权限边界不再由该skill承载：除实盘下单、
  私有交易API写操作及真实资金/账户变更外，本地开发、测试、研究、文档和部署前检查均可直接执行；任何实盘
  动作仍须owner单次明确授权并通过代码内fail-closed门。个人实验`research_sandbox`仍允许历史复用、动态
  ATR/deadband、HGB/LightGBM/XGBoost、HMM/Markov和小型神经网络探索，但必须记录trial、时间切分、泄漏
  检查并把已看窗口称为discovery。首轮已完成：1765行数据覆盖
  `2021-07-20..2026-05-19`，30日/1.0σ triple-barrier标签为bear/bull/range=`401/526/838`，28个特征只用
  当日已完成日线与funding，四个年度扩展折均按label-end purge。contract/data hash为
  `45d21773...79c`/`0fd5bba6...09de9`。
- 表格trial 1中Logistic/HGB/LightGBM/XGBoost平均Brier uplift分别为
  `-0.207976/-0.511406/-0.417971/-0.316735`；因果前向HMM为唯一正值`+0.013493`，log-loss uplift
  `+0.020354`，两者均3/4折为正。但HMM硬分类balanced accuracy仅`0.358605`，2024全退化为range且
  2025-2026不预测bear，不能直接成为风险档或仓位。trial 2固定测试unweighted Logistic、HMM 50%先验收缩、三个HMM状态
  后验增广和HMM+Logistic 50/50融合；平均Brier uplift为`-0.177369/+0.009683/-0.183699/-0.027013`，均未
  超过原HMM。结论是只保留原HMM为弱概率特征，不连接执行，也不扫融合权重。
- 独立A10节点的固定60日、32 hidden、单层GRU四折平均balanced accuracy/macro-F1为
  `0.379848/0.303852`，Brier/log-loss uplift为`-0.029635/-0.040234`且仅2/4折改善。第二次CUDA复跑除
  wall time外完全一致，四折model-state hash、best epoch和validation loss逐项相同，证明失败可复现。
  环境manifest `20260718T020000Z-research-gpu-environment`绑定A10、Torch `2.12.1+cu130`、数据与代码hash。
  当前不继续LSTM/TCN/Transformer扫参；下一步先审计标签的经济可行动性和HMM概率分箱是否对应未来收益/
  base v0.2风险，再决定是否改变目标或增加新point-in-time信息。全部仍属已消费历史discovery，本决定不恢复
  paper/live或订单权限。
- **2026-07-18 regime经济目标审计完成，价格/funding/DVOL分类与回归家族已关闭。** 原30日HMM概率虽有
  校准优势，但风险分数与未来TOP3收益的Spearman为`-0.175822`、高低组差`-3.3042pp`；10/20/30/60日×
  0.75/1.0/1.25σ共12个HMM目标为`0/12`保留。return/drawdown直接经济回归的Ridge/HGB/RF/LightGBM/
  XGBoost共40格为`0/40`，加入完整2021-04..2026-06 BTC/ETH DVOL后仍为`0/40`。这些模型有概率或局部年度
  拟合，不产生稳定经济方向；不再换分类头、神经网络或阈值包装旧信息。
- 24格滚动适应矩阵只留下`h60_train365_base_random_forest`：固定10,000次复跑和30/60/90日区块敏感性
  为`7/7`，pooled rank IC `0.167001`、高低组差`+7.629963pp`、正差概率
  `84.66%/80.15%/78.63%`；但2023折为负、三个p05均为负。随后3个只降风险规则全部失败：最佳规则将
  maxDD改善`0.878pp`，却少赚`12.216pp`并降低Sharpe。结论是预测排序不能直接逐日接仓位，该价格模型只留
  研究证据，不进入forward/paper/live。
- **Coin Metrics算力是本轮唯一保留的新低频信息，但仍没有形成可采用策略。** WSL直连官方社区API并直接写
  外置盘，BTC MVRV/活跃地址/交易数/算力/交易所流入流出共`2373`个日频latest-vintage行，覆盖
  `2020-01-01..2026-06-30`、coverage `1.0`、data hash `f1631c7b...75f6`。所有特征滞后1日；因API不提供
  历史vintage，只能作`consumed_historical_discovery_pool`。首版审计错误计入2021-2022，已由严格只用
  2023-2026合同折的v0.2废止；v0.2的7个固定方向因子仅`hashrate_z90`通过5/5：rank IC `0.159730`、
  60日差`+9.959073pp`、bootstrap正差`98.95%`且p05 `+2.009506pp`。
- 只新增算力的固定60日/365日滚动RF通过比较门`9/9`：rank IC `0.179447`、高低组差`+9.252003pp`、
  bootstrap `85.40%`，相对原RF分别改善`+0.012446/+1.622041pp/+5.40pp`。但复用同一3个降风险规则时仍
  `0/3`通过；最佳`z<=-0.5 -> vol_target 1.0%`把Sharpe从`1.1934`提高到`1.2552`、maxDD改善`0.862pp`，
  总收益却少`4.795pp`，超过预定最多`3pp`代价，故`8/9`拒绝且不放宽门。累计相关研究trial为`131`；
  base v0.2仍是正式选择，Funding Veto仍只是首选历史候选，算力模型只允许等待真正新vintage/forward研究。
- **H.4.1宏观流动性产生了当前最强排序信号，但策略兑现仍未通过。** 官方历史release archive的
  `2021-01-07..2026-07-16`共`289/289`条已由WSL直落外置盘，覆盖旧TXT、linked HTML和inline HTML三种
  布局；276个周特征统一使用`official release date + 1 day`，0重复、0未来join。两次全缓存重建data hash
  均为`8af65a47...cb02`，raw manifest为`406 files/252,249,757 bytes`、content hash
  `d0f939db...4592`。因此这条宏观历史是point-in-time discovery，不依赖最终修订FRED历史。
- 固定3个宏观trial中，4周资产变化将60日/365日RF的rank IC/高低组差/bootstrap从
  `0.167001/7.629963pp/79.55%`提高到`0.202639/12.899478pp/95.17%`，8/8通过；4周加速度也8/8，13周
  变化因IC低于控制而拒绝。4周宏观+算力的唯一融合trial为5/8，未超过宏观单源。最终3个冻结风险规则仍
  `0/3`：最佳Sharpe提高`0.0838`、maxDD改善`0.863pp`，但收益少`3.323pp > 3pp`，8/9拒绝且不放宽门。
  累计相关trial为`138`；宏观预测只留future-only研究，Base v0.2 1.5%与生产关闭状态不变。
- **H.4.1事件驱动确认没有解决信号与兑现机制错配。** 在消费策略结果前预登记3个不扫参trial，固定
  `release_date + 1d`可见时点和经济零阈值，只测试“收缩阻止新开仓”“扩张延迟SMA200总闸退出”及二者
  合并；Base的1.5%风险目标、35% deadband、3xATR吊灯、3日冷却、gross<=1及no-carry均未改。控制为
  `+66.5054%/Sharpe 0.8982/maxDD 17.2845%`。收缩闸门在633根日线上介入、阻止1,358个symbol entry，
  把收益压到`+1.7223%`；双确认同样只剩`+0.3408%`。扩张退出确认只介入2根日线/4个symbol exit，虽将
  收益代价控制在`-2.4167pp`，但Sharpe降至`0.8642`且maxDD仅改善`0.0461pp`。3个trial均拒绝，累计
  trial为`141`。结论不是“事件频率还不够低”，而是H.4.1符号状态太持久，不适合作为二元交易许可；
  它仍只保留为60日排序特征，不再扫描分位数、窗口、持有期或冷却期救援。
- **H.4.1只管理strong-bull边际风险的假设也被拒绝。** 先确认现有RF目标是TOP3等权指数未来60日收益的
  时间序列排序，不能用于BTC/ETH/BNB横截面轮动；随后在读取结果前只预登记1个新trial：保留Funding Veto
  和Stop-Latch，仅当年度fold OOS标准分数`<=0`时把原本允许的strong-bull `2.0%`增益退回Base `1.5%`，
  从不把风险降到Base以下。1205个决策日覆盖`2023-01-01..2026-04-19`，其中449个Funding/Stop之后仍可
  boost的强牛日被宏观否决303个。Base、Funding Veto参考、候选分别为
  `+68.2697%/Sharpe 1.1934/maxDD 17.2756%`、`+90.3621%/1.2602/18.1016%`、
  `+65.0724%/1.0950/19.2637%`。候选相对参考少赚`25.2897pp`、Sharpe低`0.1651`且maxDD恶化
  `1.1621pp`；相对Base也少赚`3.1973pp`且回撤恶化`1.9881pp`。配对20日块Bootstrap的终值/Sharpe/
  更低回撤胜率仅`1.54%/6.90%/63.40%`，`8/14`门通过，累计trial `142`。结论是宏观排序在全市场时间轴
  有信息，但在技术面已筛出的强牛子样本中不能决定边际风险；不做分位、分数阈值或持有期救援。
- **Base v0.2的利润来自长趋势和吊灯退出，主要损耗来自短持仓反复进出。** 在结果前冻结`trial_count=0`
  的episode合同，按逐币连续正权重重建77段持仓，并按每日当时权益精确分摊价格、funding和双边交易成本；
  归因净利润`266.02158324 USDT`与组合`266.02158322 USDT`只差`0.00000002 USDT`。31个吊灯退出episode
  合计`+403.6133 USDT`、胜率70.97%、中位持有43日、中位MFE `24.63%`，且2021/2023/2024/2025四年
  均为正，因此3xATR不是当前应收紧的损耗源。38个单币趋势/配置退出合计`-56.6102 USDT`、胜率28.95%、
  中位持有4日；8个SMA200总闸退出全部亏损、合计`-80.9815 USDT`，但未过10个episode样本门。按持有期看，
  1-7日/8-30日分别亏`-101.6869/-77.9728 USDT`，31-90日/>90日分别赚
  `+251.2261/+194.4551 USDT`。这验证了策略的低胜率、长右尾本质，不支持时间止损或收紧吊灯。
- **信号退出后复用既有3日冷却略有改善，但统计强度不足，仍拒绝。** 38个趋势/配置退出中，36个之后还有
  同币新episode；12次在3日内重入，后续只有2次盈利、合计`-22.0242 USDT`。据此只预登记1个无新数值
  参数trial：总闸仍开且单币趋势退出时，复用止损的3根完成日线冷却。候选触发34次、阻止20个symbol-bar
  重入，把episode从77降到72、订单从261降到252、成本从`28.3381`降到`27.2536 USDT`；收益
  `+66.5054%→+66.8046%`、Sharpe `0.90277→0.90788`、maxDD `17.2845%→17.2774%`。但配对20日块
  Bootstrap的收益/Sharpe/更低回撤胜率仅`58.96%/64.42%/55.88%`，三条稳健门均失败，`13/16`通过，
  累计trial `143`。不扫2/4/5日冷却，也不改20/60/200日均线救援。
- Coin Metrics future vintage链已启动：首个不可变快照绑定`2026-07-17`源日与
  `2026-07-18T04:12:05Z`检索时间，snapshot hash `f83b288f...d6dfb`。provider publication timestamp不可得，
  不能把本地检索时间伪装成历史发布时间；后续只追加，不回填、不覆盖。
- **2026-07-16 owner 决策:先放弃 A股 ETF，研究优先级转回加密。** A股 ETF 20 日线停止
  Tushare parity、日频复跑、自动提醒、券商/QMT 接入和任何 paper/live 推进；代码、测试和 discovery
  artifact 只作为历史研究资产保留。加密方向恢复为当前唯一主动研究优先级，但这只授权 Mac 上的
  public-data / deterministic research，不授权访问私有账户、恢复 VPS collector/crontab、forward paper
  或 live。下一步必须先为一个**新的结构性信息源**写 G0/source-capacity/preregistration；现有 price、
  kline taker、OI/taker ratio、aggTrades-only、premium、aggregate bookDepth 和冻结 Logistic 合同继续关闭。
- **2026-07-17 新结构信息源第一轮已完成，但 options-DVOL discovery 为 0/3，路线停止。** 新增
  `source_capacity.py`/`historical_dvol.py`/`options_dvol.py` 与三个薄 CLI。source-capacity artifact
  `20260716T141329Z-alpha-agent-source-capacity` 用官方小探针确认：Binance historical `forceOrder` 与
  replayable `depth` 均 404，aggregate `bookDepth` 可用但不是 L2；Hyperliquid 四币 funding/premium
  历史可用但与旧 funding/cross-venue 失败线重叠；Deribit BTC/ETH DVOL 的 2021/2025 边界均为完整
  25 根小时 OHLC，因此只选择它进入 G0。结果读取前最终 v0.3 preregistration
  `20260716T145022Z-alpha-agent-options-dvol-preregistration` 冻结 `ETH DVOL - BTC DVOL`、720h
  normalization/beta、`|z|>=2` reversion、24h hold/cooldown、ETH/BNB/SOL 固定分母、7bps/position
  change、funding、400 USDT filters 和 2/3 kill line；contract/protocol hash 为
  `195a9160...3b95` / `c87b0d96...86fa9`。v0.1/v0.2 在收益读取前因补齐 beta/entry/coverage 显式门而被
  v0.3 取代，不作为结果合同。
- **DVOL 数据门通过，但冻结策略本身失败。** dataset
  `20260716T142116Z-alpha-agent-historical-dvol` 从 90 个官方按月响应构建 BTC/ETH 各 32,904 小时，
  coverage `1.0`、0 gap/duplicate、缓存复跑 data hash `d07122f7...09c86`。Binance SOL 月档内缺少
  2022-02-26..28 和 2022-04-01..02 共 120 小时，runner 只用对应官方 daily ZIP + `.CHECKSUM`
  确定性补齐；最终四币 price、DVOL feature、filter coverage 均 `1.0`，三币各 188 entries、24h
  turnover `2.0`。最终 ETH IC/residual `-0.048945/-55.322693%`，BNB
  `-0.078558/-77.010159%`，SOL `+0.004773/+6.290805%`；SOL 因 IC 远低于 `0.02` 仍 block。
  final report `20260716T151115Z-alpha-agent-options-dvol=block_discovery`：passing/positive IC/positive
  residual `0/3,1/3,1/3`，median IC `-0.048945`，mean residual `-42.014016%`。不反转 polarity、
  不调 z/lookback/holding，不消费 2025 replication 或 2026-07-17 起 forward OOS，不进 A10/paper/live。
- **Historical option-surface 审计在 G0 阻断。** 新增 `option_surface_capacity.py`、薄 CLI 和离线测试；
  artifact `20260716T155503Z-alpha-agent-option-surface-capacity`、data hash `e8ab2da2...bb6868`。
  五个 2021/2024/2025 已过期 BTC/ETH instrument metadata 与 price chart 均可读，但 chart 只有
  OHLC/volume/cost/ticks，没有 IV/index/mark；2024 历史 trade probe 为 0 rows，`expired=true` inventory
  只暴露一个近期 expiry，无法枚举历史 point-in-time chain。当前 surface 有 BTC/ETH `874/720` 条
  mark-IV，但不能倒推历史 surface；price-only inversion 会引入未预注册的定价模型与 strike search。
  verdict `block_g0`，未读取策略收益、未生成 skew preregistration。
- **外部 liquidation/replayable-L2 审计在访问与容量 G0 阻断。** 新增
  `external_microstructure_capacity.py`、薄 CLI、测试和 Tardis source reference；最终 artifact
  `20260716T160716Z-alpha-agent-external-microstructure-capacity`、data hash `cc591bb7...5bf4f`。
  metadata 确认 BTC/ETH/BNB/SOL 均有 `liquidations` 与 `incremental_book_L2`；BTC depth 一分钟
  `1,982,255` bytes/`1,086` updates/0 invalid/0 sequence break，raw hash `69060a8d...a7e81`；四币
  forceOrder 一分钟为 1 条 SOL/243 bytes，hash `57f28cac...175c`。匿名整日请求仍只返回同一 1 分钟
  (`x-slice-size=1`)；BTC raw L2 外推 `2,854,447,200 bytes/day`、`256,900,248,000 bytes/90d`，超过
  32 GiB cache gate。verdict `block_g0_access_capacity`，liquidation 仅在授权且可复现完整历史后优先；
  本轮未购买、未读收益、未写 preregistration。
- **2026-07-17 owner 选择不用高频，低频趋势回到冻结 TOP3 forward。** 新增
  `mini_trend/forward.py`、薄 CLI 和测试，不改原 signal/risk/execution。结果读取前 preregistration
  `20260717T030622Z-mini-trend-top3-forward-preregistration` 绑定旧 TOP3 2025-07-20..2026-06-30 anchor
  config/summary/equity SHA，冻结 `BTCUSDT/ETHUSDT/BNBUSDT`、spot long/cash、1d、400 USDT、
  SMA20/60/200、breadth 0.5、vol target 1.5%、rebalance band 35%、10bps fee + 2bps slippage、trial 1，
  禁止 universe/参数搜索、高频、short、杠杆和自动 paper/live；contract/protocol hash 为
  `37302065...68b2` / `029835ae...773c`。公开 spot `exchangeInfo` 主域在当前 Mac 返回 451，改用 Binance
  官方只读 `data-api.binance.vision`；rules artifact `20260717T030547Z-alpha-agent-exchange-rules` 确认 TOP3
  均 `TRADING`、min-notional 5 USDT。
- **首个低频 forward 片段数据完整，但只有防守状态，不构成通过。** 最终 artifact
  `20260717T031824Z-mini-trend-top3-forward`、data hash `494f01da...cf98`；旧 research-filter anchor equity
  `401.85455267` 精确复现，当前 runtime rules 只造成 `+0.019512 USDT` 历史执行精度漂移。2026-07-01..16
  为 16/16 根完成日线、0 gap；BTC close/SMA200 `63,830.20/73,438.14`、breadth `0.0`，总闸关闭、TOP3
  targets 全 0、16 天全现金、0 单/0 blocked。策略 `+0.002866%`，同期 BTC B&H `+8.879345%`、TOP3 EW
  `+10.747795%`；它没有追到反弹，但 maxDD 近 0。verdict `collect_forward`，blockers 仅为不足 60 根
  forward 和不足 10 根 active；不调闸、不追涨、不进 paper/live。
- **2026-07-17 实盘记录复盘与合约资金架构冻结。** 只读复制 VPS 的订单、快照、guarded daily equity、
  stops 和日志安全统计，生成 `state/research_runs/20260717T033716Z-mini-trend-live-lessons/mini_trend_live_lessons.json`。
  `415.00` 是撤资/重置后的账户余额，不可作为策略 PnL；可比策略净值是 `474.07/484.57-1=-2.166870%`。
  37 个 inception 之后已发单里有 5 个完全重复单、7 个同日同向重复单、8 组同日方向反转和 2 个止损事件；
  另有 66 次未知本金 fail-closed、21 次旧 fallback 余额读取。下一协议必须 `UM wallet + no carry + 1d +
  long/cash + effective gross<=1.0 + no leverage boost + runtime filters + unknown-capital fail-closed +
  stop latch/cooldown`。
- **2026-07-17 UM recovery 候选被历史诊断拒绝。** preregistration
  `20260717T034500Z-mini-trend-um-recovery-preregistration` 固定 TOP3、UM 1d、funding、25% recovery gross、
  3 根 20 日线确认、真实 UM filters、10bps+2bps 成本、3 根 stop cooldown、trial=1；诊断 artifact
  `20260717T035442Z-mini-trend-um-recovery-historical` 只读已有缓存且 `network_download_used=false`。
  控制线和 recovery 线均不构成 paper 资格；recovery 直接停止，不调参救援。
- **UM base v0.2 forward 当前尚未开始。** v0.1 在尚未读任何结果时因未显式绑定实际 `3xATR` 日线 stop
  被 v0.2 preregistration `20260717T121646Z-mini-trend-um-base-forward-preregistration` 替代。freshness
  artifact `state/research_runs/20260717T121715Z-mini-trend-um-base-forward/mini_trend_um_base_forward.json` 只读
  `state/grid_b/klines` 缓存，三币最新共同完成日线为 `2026-06-18`，forward start `2026-07-17` 后为
  `0` 根，verdict `await_forward_data`。这不是零收益，也不是策略失败；需要新的完整 UM 日线后才允许
  计算 forward return。
- **历史已有数据可以继续用，但只能作为 discovery。** benchmark artifact
  `state/research_runs/20260717T115728Z-mini-trend-um-historical-benchmark/mini_trend_um_historical_benchmark.json`
  在同一 UM 日线、funding、10bps+2bps 口径下比较 control 与 BTC 1x/TOP3 EW：2021-2022 control
  `-0.973818%` 对 BTC `-50.543561%`，2023-2024 control `+41.489075%` 对 BTC `+167.711082%`，
  2025-2026 control `-2.018860%` 对 BTC `-39.041151%`。control 在 2/3 段相对基准更好，但绝对收益仅
  1/3 段为正，verdict `discovery_only`、promotion=false；不调参、不把历史段当 future OOS。
- **数据下载边界补充。** 大批量public data只在Windows/WSL侧下载并直接写外置盘，不使用Mac/VPS中转或
  苏菲家宽代理；Windows/WSL直连和owner-approved Liangxin Cloud proxy均可，凭据仅存仓库外本地环境。
  当前UM离线诊断仍完全复用现有缓存，缺月即失败，不因路由放宽而静默联网。
- **2026-07-16 A股 ETF 20 日战术研究线已接入，但 evidence gate 阻断。** 新增
  [ashare-etf-month-plan.md](../ashare-etf-month-plan.md)、`src/qount/ashare_etf_month.py` 和薄 CLI，
  标准库直连 Tushare `fund_daily + fund_adj`，token 只读 `TUSHARE_TOKEN`；本轮 token 未注入，最终
  artifact `state/research_runs/20260716T094924Z-ashare-etf-month/ashare_etf_month.json` 使用腾讯前复权
  日线。7 月 16 日状态为 `hardware_pullback_application_rotation`：硬件距 MA20 平均 `-12.50%`，
  但 AI 核心距 MA120 `+11.72%`、60 日相对沪深300 `+15.36%`，所以不是全 AI 逻辑结束。四套固定
  组合 59 个不重叠 20 日样本中位数和胜率全部不过；严格同状态只有 1 个独立负样本，轮动杠铃
  `-1.24%`、最大回撤 `-4.62%`，gate `block`。75% 目标被缩至 37.5% 上限/62.5% 现金；当前只有
  只有红利首笔 6.25% 满足条件，即初始暴露最多 6.25%；消费必须等 `0.648-0.655` 回踩或收盘
  `0.670` 放量突破。该读数只保留为历史 discovery；同日后续 owner 决策已冻结本线，不再执行上述
  条件、不接 paper/live，也不改变 L6 或加密生产状态。
- **2026-07-16 S3 改为历史优先；VPS 7 天会话已中断并永久标为失败证据。** 正式 session
  `/root/qount-alpha/state/research_runs/20260714T135630Z-alpha-agent-live-collector-session-7d-vps/`
  只完成约 21 小时：22 个闭段中 19 pass、3 block，最后闭段出现约 38 分钟 market-event 空窗并触发
  `depth_replay_unanchored/trade_gap/stale_event` blocker，另留一个 orphan partial。Owner 确认随后 VPS 因
  内存不足多次重启；service 因 `Restart=no`/boot-disabled 保持 inactive，Mac offloader 也因第 0 段 blocker
  fail closed。该 session `continuous_gate_eligible=false`，不得 resume、拼接、训练或 promotion；共享 1.6G VPS
  不再承载新的长跑 collector。旧 7 天 verifier 仍保留为 collector 工程验收工具，但不再是历史研究的前置门。
- **2026-07-16 历史微观结构覆盖与 daily metrics dataset 已接入。** 新增
  `historical_microstructure.py`/`alpha_agent_historical_microstructure.py`，只探测官方 `.CHECKSUM`：四币
  `2024-01-01/2026-07-10` 日样本 + `2024-01` 月样本共 40 probes，36 available、4 missing、0 error；
  `aggTrades=12/12`、`bookTicker=8/12`、`bookDepth=8/8`、`metrics=8/8`。语义审计确认 public
  `bookDepth` 是 `timestamp/percentage/depth/notional` 百分比聚合深度，不是带 `U/u/pu` 的可重放 diff-depth；
  `forceOrder`、receive latency 和 replayable diff-depth 仍需外部历史源或短实时采集。artifact：
  `state/research_runs/20260716T032055Z-alpha-agent-historical-microstructure/alpha_agent_historical_microstructure.json`。
  新增 checksum-verified daily metrics loader，2024Q1 四币 364/364 archive、104,332 rows、每币覆盖
  `0.995230`；唯一共同缺口为 `2024-02-16` 的约 10.5 小时，现写 `segment_id`，feature/label/beta/PnL
  禁止跨段。dataset：
  `state/research_runs/20260716T033710Z-alpha-agent-historical-derivatives/alpha_agent_historical_derivatives.json`。
- **2026-07-16 历史 metrics 第一版 kill-test 失败。** 2024Q1、四币 USD-M 5m、72 candidates，Jan-Feb
  train/Mar OOS，训练按 rank IC 冻结 `oi_delta_lb1_thr0_long_short`；train/OOS rank IC 为
  `0.022246/0.029326`，但 4,223 turnover × 7bps 与 funding 后 OOS beta-residual `-56.833338%`，
  BTC beta `-0.028737`，scorecard `block`。正弱 IC 不等于可交易 edge；不进 A10/paper/live，不在同一
  Q1 discovery 上继续挑 threshold。最终 feature/metrics/scorecard artifact 分别为
  `20260716T035639Z-alpha-agent-feature-experiment`、`20260716T035652Z-alpha-agent-beta-metrics`、
  `20260716T035706Z-alpha-agent-scorecard`；较早的 `034337Z/034357Z/034406Z` 数值相同，但在 rolling
  beta 完全按 gap 重置前生成，只保留为中间证据。
- **2026-07-16 checksum-verified `aggTrades/bookTicker` loader 与 5m 聚合已接入。** 新增
  `historical_tradeflow.py`/CLI/tests，按官方 SHA-256 sidecar 校验 ZIP，流式解析真实 CSV，不落解压后的
  事件文件。BTC `2024-01-01` 双源真实审计：`aggTrades=761,222` 行、`bookTicker=11,986,235` 行，均覆盖
  288/288 个 5m 桶；aggregate-trade ID 无断号，book update/event/transaction time 无回退，crossed book/
  非法数量均为 0。`bookTicker.update_id` 只检查单调，不把合法跳号冒充丢包。artifact：
  `20260716T042522Z-alpha-agent-historical-tradeflow`。Q1 ETH `aggTrades` 3/3 月包 checksum 通过，原始
  113,092,010 行聚合为 26,208 个完整 5m 桶，覆盖 100%、单 segment、月内/跨月 ID gap 均为 0；dataset：
  `20260716T043347Z-alpha-agent-historical-tradeflow`。
- **2026-07-16 首个冻结低换手 trade-flow 候选过历史 Q1 discovery 和一次性 4 月 OOS，但 promotion 仍
  `block`。** `tradeflow_experiment.py` 在读取新窗口前固定唯一合同
  `agg_trade_imbalance_z168_entry2_hold6_cooldown18_momentum_v1`，contract hash
  `2b61627c...c9094`：完成小时的 aggressive-flow imbalance 用过去 168h 标准化，`|z|>=2` 顺向入场，固定
  持有 6h、退出后 cash 18h、禁止直翻，24h turnover budget `2.0`，trial count `1`。Q1 discovery rank IC
  `0.024647`、41 entries、成本/funding 后 beta residual `+7.163938%`；冻结后才读取 2024-04，3/24-3/31
  只做无标签 warmup、4/1 强制空仓，OOS rank IC `0.039999`、16 entries、beta residual `+6.196189%`、
  去掉最大单小时贡献仍 `+2.427747%`。最终 discovery/OOS artifact：
  `20260716T044439Z-alpha-agent-tradeflow-experiment` / 同秒 `-01`。专用 validation 用 Q1 冻结 beta 得到
  4 月 residual `+7.663555%`、purged time-fold pass，但 DSR `0.915342 < 0.95`；单一预注册候选无法识别 PBO，
  保守写 `1.0` 而不是伪造 pass。validation/metrics/scorecard 为 `20260716T044644Z` / `044704Z` /
  `044724Z`，scorecard `G0-G3/GX pass`，`G4/G5/G6 block`。因此这是第一份值得保留的历史微观结构正证据，
  但不进 A10/paper/live，不在 Q1/4 月改参数，也不因它恢复 VPS 7 天采集。
- **2026-07-16 frozen trade-flow v1 跨 BTC/BNB/SOL 预注册复制全败，G5 从“未验证”变为明确
  `block`。** 在读取复制数据前先写 preregistration `20260716T083420Z-alpha-agent-tradeflow-replication`，
  protocol hash `d2c9ca4e...d03da1`，固定同一 ETH contract/cost/window，禁止符号筛选和调参；每个复制符号
  只有 Q1 discovery 过门才允许读 April。BTC/BNB/SOL Q1 9/9 月包 checksum 通过，原始
  295,897,363 trades -> 78,624 个 5m 桶，各币覆盖 100%、单 segment、月内/跨月 ID gap 0；dataset
  `20260716T085640Z-alpha-agent-historical-tradeflow`。同合同 discovery 结果全部 `block_discovery`：BTC
  rank IC/residual `0.007095/-4.150084%`，BNB `-0.016277/-8.680766%`，SOL
  `-0.028842/-5.175364%`；filters 100%、entries 45/46/46、24h turnover 均 `2.0`，所以失败不是数据、
  最小名义或换手超标。按预注册规则三币 April OOS 均未消费。最终 replication report
  `20260716T090929Z` 为 `block_correlation_stress`；重算 metrics/scorecard `20260716T090941Z`/
  `20260716T090958Z` 仍为 `G0-G3/GX pass`、`G4/G5/G6 block`，其中 G5 现明确为
  `missing_effective_breadth/correlation_stress_not_passed/capacity_not_checked`。读法：ETH 历史正证据保留，
  但不能外推为 majors 稳健规律；frozen v1 停止晋级，不下载复制 April、不调参数救结果、不做 runtime parity。
- **2026-07-16 flow/price absorption 新机制预注册 discovery 也被三币一致否定。** 新增
  `flow_absorption.py`、薄 CLI 和测试；在读取策略结果前先写 preregistration
  `20260716T100011Z-alpha-agent-flow-absorption`，合同 hash `8f30e701...f5bf124`、protocol hash
  `0c6f277c...a82d816`。唯一候选把完成小时的 aggressive-flow z-score 与同小时 BTC beta-residual
  价格反应交叉：极端 flow 与价格反向/不动视为被动吸收，随后反向持有 6h、cash 18h，继续按 taker fee
  `5bps` + slippage `2bps`/position change、funding、400 USDT filters 计分；只有 ETH/BNB/SOL 至少 2/3
  过门才允许另写 April OOS 预注册。Q1 结果全部 `block_discovery`：ETH rank IC/residual
  `-0.024471/-8.056549%`，BNB `0.018082/-15.461342%`，SOL `-0.018355/-9.206446%`；entries
  `11/19/15`，filter coverage 均 `1.0`、24h turnover 均 `2.0`。最终 report
  `20260716T100057Z-alpha-agent-flow-absorption` 为 `passing_symbol_count=0`、median IC `-0.018355`、mean
  residual `-10.908112%`，April `reserved_oos_consumed=false`。这否定了“单靠 aggTrades 流量与当小时价格
  背离做反转”的机制。后续只读 source audit `20260716T100514Z-alpha-agent-historical-microstructure` 确认
  2024Q1 四币 `bookTicker` 月包 `12/12 available`，但 official HTTP metadata 显示压缩包合计
  `58,608,259,115 bytes`（`54.58 GiB`）；本机仅约 `87 GiB` 可用，不能把“可下载”误写成“可低成本使用”，
  本轮未下载。下一刀必须加入独立状态变量并重新预注册，优先转体量更小的 mark/index premium；
  `bookTicker` 只保留为带磁盘预算的预注册抽样/流式方案，不得在已看 Q1 上改 absorption 阈值/方向/持有期。
- **2026-07-16 checksum-verified premium/mark/index 数据链通过，但预注册 premium mean-reversion
  discovery 为 0/3，机制停止。** 新增 `historical_premium.py`、`premium_dislocation.py`、两个薄 CLI 和
  5 个测试。最终 strict-schema dataset `20260716T102324Z-alpha-agent-historical-premium` 校验
  `premiumIndexKlines/markPriceKlines/indexPriceKlines` 36/36 个官方 Q1 5m 月包，压缩总量
  `7,613,751 bytes`，四币各 26,208 个完整桶、coverage `1.0`、单 segment、data hash
  `784a816a...89d7381`；fail-closed 12 列 parser 加固前后的 data hash/结果完全一致。策略结果读取前先写
  preregistration `20260716T102055Z-alpha-agent-premium-dislocation`：contract hash
  `f07d0702...fa05d55`、protocol hash `6d842c44...4315c2f`，每小时 12 个 completed 5m premium close
  取均值、过去 168h z-score、`polarity=-1`、`|z|>=2`、hold 6h/cash 18h，继续计 7bps position-change
  成本、funding 和 400 USDT filters；至少 2/3 才允许 April。最终 Q1：ETH IC/residual
  `-0.046471/-0.863166%`、BNB `-0.001891/-8.707943%`、SOL `+0.045684/-1.153916%`，entries
  `37/34/33`；filters 均 `1.0`，SOL 还因窗口末强制平仓使 24h turnover `3.0 > 2.0`。final report
  `20260716T102358Z-alpha-agent-premium-dislocation=block_discovery`：passing `0/3`、positive IC `1/3`、
  positive residual `0/3`、median IC `-0.001891`、mean residual `-3.575008%`、April 未消费。不能在 Q1
  上改 premium 阈值/方向/持有期。下一独立源只允许转 historical `bookDepth` 百分比累计深度：只读 audit
  `20260716T102632Z-alpha-agent-historical-microstructure` 已确认 2024-01/02/03 月首日四币 12/12 available；
  CSV 是约 30 秒一组 `timestamp,percentage,depth,notional` 的 `±1%..±5%` 聚合，不是 diff-depth/L2 replay。
- **2026-07-16 已完成可重放的趋势概率模型基线，但 March OOS 三币 0/3，不能启动 A10/LightGBM/
  Transformer 追分。** 新增 `historical_depth.py`：严格要求每个 snapshot 恰有 `-5..-1,+1..+5` 十档，
  校验 daily ZIP checksum 后流式聚合 5m 的 1%/5% notional imbalance、1% 波动和近端深度占比；明确
  `replayable_l2=false`。最终 dataset `20260716T104132Z-alpha-agent-historical-depth` 为 364/364 包、
  `165,500,458 bytes`、1,047,015 个原始 snapshots 聚合为 104,768 个 5m rows；每币 26,192/26,208、
  coverage `0.999389`、8 segments，16 个共同缺桶分布在 7 个短区间，模型不跨缺失小时拼 feature。
  在任何模型结果读取前写 preregistration `20260716T104401Z-alpha-agent-residual-trend-model`：contract
  hash `a729ea39...20d979`、protocol hash `be9f2123...477646`，固定 10 特征（depth、premium、已完成
  1h/6h return、24h vol、BTC 6h return）、L2 Logistic `C=1`、Jan-Feb train、6h purge、March OOS、
  `p>=0.55` long/`p<=0.45` short、hold 6h/cash 18h，无 grid/feature selection/refit。最终 March：ETH
  AUC/IC/residual `0.484692/-0.004346/-17.444056%`，BNB
  `0.500214/-0.019693/-8.485764%`，SOL `0.514279/+0.051771/-7.127153%`；三币 Brier improvement 全负，
  entries `29/30/30`，filters 均 `1.0`，BNB/SOL max 24h turnover `3.0`。report
  `20260716T104522Z-alpha-agent-residual-trend-model=block_discovery`：passing/positive residual `0/3`、mean
  residual `-11.018991%`、DSR `0.095/0.243/0.299`、PBO fail-closed `1.0`、April 未消费、
  `a10_sequence_enabled=false`。工程上现在能产出概率、校准、walk-forward、模型系数和成本回测；证据上
  尚不能预测可交易趋势。不能在已看 Q1 上换 HGB/LightGBM/Transformer、调阈值或选特征后再称 OOS。
- **2026-07-16 冻结 residual-trend 模型的 2025Q1 跨时间复验再次 0/3，固定模型路线关闭。** 在读取
  2025Q1 概率/收益前写 preregistration
  `20260716T125427Z-alpha-agent-residual-trend-replay`，protocol hash
  `2f15b7af...cfcbfe`；逐币绑定原 ETH/BNB/SOL model artifact SHA-256，禁止 refit、recalibration、feature
  selection、threshold/model-family search，继续使用原 scaler/coefficients/intercept、train positive-rate
  Brier baseline、`0.55/0.45` 概率门和 7bps position-change cost。官方 metadata `396/396` 包可用；最终
  2025Q1 depth `20260716T130420Z` 为 360/360、`162,843,538 bytes`、coverage `0.999421`，premium
  `20260716T130534Z` 为 36/36、`7,443,575 bytes`、coverage `1.0`，四币小时 K 线覆盖 `1.0`。结果为 ETH
  AUC/IC/Brier-improvement/residual `0.502287/+0.012601/-0.010654/-42.209377%`，BNB
  `0.462687/-0.066387/-0.011183/-13.971742%`，SOL
  `0.515403/+0.005188/-0.006259/-41.020445%`；三币 feature/filter coverage `0.997674/1.0`，entries
  `87/81/87`，max 24h turnover 均 `3.0`，DSR `0.007971/0.130511/0.066449`。final report
  `20260716T131339Z-alpha-agent-residual-trend-replay=temporal_replay_complete_no_promotion`：supportive/positive
  residual `0/3`、mean residual `-32.400521%`、PBO `1.0`、promotion/A10 均 false。不能再以“换年份”继续
  搜索这组固定特征；下一次模型研究必须先有真正独立的信息源或不同预测目标，并重新计入累计 trial。
- WSL 已退出 live / paper / dashboard 生产角色。不要用 WSL `.env`、
  `qount-runner.timer`、`preflight-live`、`scripts/sync-to-wsl.sh` 或
  `scripts/run-wsl-tests.sh` 判断当前实盘状态；历史 WSL artifact 路径只作为研究证据链保留。
- 旧 line A `qount.main` live 继续关闭：`QOUNT_LIVE_ENABLE=false` 仍是默认安全边界。
  加密 X4 / C×D 实盘使用独立开关 `QOUNT_X4_LIVE_ENABLE`、`QOUNT_RV_LIVE_ENABLE` 和
  `QOUNT_CXD_CARRY_ENABLE`，不能用 `QOUNT_LIVE_ENABLE` 推断 X4/C×D 是否 armed。
- 加密 live 的最近生产设计由 VPS C×D orchestrator 负责，carry 默认暂停
  (`QOUNT_CXD_CARRY_ENABLE=0`)；但资金撤出后 root crontab 已于 2026-07-11 停用，当前没有继续产生日志或订单。
## 当前能力

已经具备：

- 跨资产标准合同：canonical `InstrumentId`、产品级 `ProductCapability`、signed `StrategyIntent` v2、绝对gross的
  allocator/risk/planner、signed ledger v3与virtual accounting；cash stock/tokenized stock/equity perpetual不会因ticker相同而混仓。
- Binance Stocks纯契约：严格解析`exchangeInfo`，验证四种官方order字段组合、两位限价精度、quantity/notional/session/fractional规则、
  disclaimer和tokenize identity；SELL必须提供权威`available_to_sell`且永不视为开空。该层不包含HTTP/private client。
- 运行链路：`snapshot -> candidate_filter -> AI -> validate -> risk -> paper/live executor -> journal`。
- Binance USDT 合约执行骨架、live guard、runtime halt、日内权益隔离。
- `signal-review` / `paper-replay` / `backtest` / `walk-forward`。
- ETH-only research profile：固定当前 phase6 setup model、`ai_temperature=0.0`、
  `ETH/USDT`、`max_open_positions=1`。
- research artifact 持久化：外部 `/tmp` 输出会镜像到 `state/research_runs/...`。
- `research-slice-scan` 的 `offline_future_edge_readiness` 诊断。
- `backtest` / `walk-forward` 的 `--holdout-role` 和研究专用 `--ai-decision-cache`。
- `setup-edge-walk-forward`：只读 setup model 层，不调用 AI、不执行订单。
- `candidate-walk-forward`：只读 candidate 层，不调用 AI、不执行订单。
- `setup-model-compare`：离线对比 setup_model v1 与 `v2_interactions`，用时间顺序
  train/eval split 读 calibration / lift；不调用 AI、不执行订单。
- `ai-hold-baseline`：从已有 artifact 还原 fresh-entry prompt 样本，统计 AI hold-bias，
  支持 `v1` / `v2_remove_default_wait` / `v3_veto_only` 研究变体。
- `idle-window-diagnostic`：只读 0 交易窗口诊断，输出 setup / candidate / AI hold
  层分布和 top candidate future edge；不调用 AI、不改变交易链路。
- `strategy-selection-scan`：S1' 频段 × 策略族选择扫描，覆盖
  `5m,1h,4h,1d` × `xs_mom,xs_rev,ts_mom,carry`；只写 research artifact，不调用 AI、
  不执行订单、不改变 live。预测族显式支持 signal lookback / holding horizon 网格；CARRY
  显式支持旧 `directional_round_trip` 成本口径和
  research-only `per_order + spot_perp_gross` 口径，用于读 explicit spot/perp 双腿执行成本、
  资金占用、break-even order cost、basis 风险、单次 basis tail 压力、post-only economics
  和显式 research-only basis tail stop / basis entry regime filter；扫描 artifact 支持显式
  `holdout_role=discovery|validation_v1|unknown`；预测族支持 research-only
  `--directional-overlap-mode all|stride`，其中 `stride` 只保留每个 holding window 一次
  cross-section，用于降低重叠 horizon 膨胀；预测族还支持 research-only
  `--directional-evaluation-mode portfolio_replay` 和
  `--directional-max-open-positions`，用于限仓组合 replay；预测族支持 research-only
  `--directional-exit-mode close|triple_barrier`、`--directional-take-profit-pct`、
  `--directional-stop-loss-pct`，用于 OHLC intrabar TP/SL barrier 复核；预测族还支持
  research-only `--directional-purged-cv-folds` / `--directional-embargo-bars`，
  用于把 fixed cell 的时间分段稳定性和 embargo 区间写入 artifact；预测族还支持
  research-only `--directional-barrier-vol-lookback-bars` /
  `--directional-take-profit-sigma` / `--directional-stop-loss-sigma`，把 triple-barrier
  的 TP/SL 从固定百分比改为按决策时点近 N 根 bar 已实现收益 σ 缩放(防泄漏)，默认关闭；
  预测族还支持 research-only `--directional-regime-min-dispersion-pct`，在每个 cross-section
  上按各币 signal 离散度做 regime 入场门(低离散度跳过该 bar,纯决策时点)，默认关闭;scan
  顶层还输出 `directional_deflated_sharpe`(Deflated Sharpe Ratio)和 `directional_pbo`
  (PBO/CSCV,按频段分组的过拟合概率)，量化"搜了 N 个 cell 后最佳 Sharpe 还剩多少可信 +
  IS 赢家在 OOS 是否仍靠前"的两类多重检验惩罚，diagnostic only。
- Mac 到 VPS 同步与测试脚本：`scripts/sync-to-vps.sh`、`scripts/run-vps-tests.sh`。
  旧 WSL 脚本默认拒绝执行，只有显式 `QOUNT_ALLOW_LEGACY_WSL=1` 才可用于历史环境。
- L3 信息源数据接入层（S0.1）：`src/qount/l3_information_edge.py` + research-only 命令
  `l3-stablecoin-fetch`，拉 DefiLlama 聚合稳定币总供给、`state/` 缓存离线复跑、归一化成
  排序去重日度序列、严格 as-of(无前视)join 到周线锚点;只用 stdlib `urllib`、不引入新依赖、
  live / `run-once` 不 import、不算 IC 不下注。
- L3 S1 kill-test 工具:命令 `l3-stablecoin-timing-scan` + `evaluate_l3a_stablecoin_timing`,
  把稳定币供给增速对 BTC 周线 forward-return 的时序 rank-IC + DSR/PBO 机械化(复用 §7 harness),
  breadth-adjusted 门控 IC ≈0.083;BTC 走期货 fapi、研究-only、无仓位。已用于证伪 L3a。
- L3b 横截面 kill-test 工具:命令 `l3-chain-tvl-scan` + `evaluate_l3b_chain_tvl_cross_section`
  + `_panel_effective_breadth`,把链 TVL 增长横截面 rank-IC 与 token 收益有效广度 + DSR/PBO
  机械化(§2 要求二者一起判生死);链 TVL 走 DefiLlama、价格走期货 fapi、研究-only。已用于证伪 L3b。
- L1 跨资产广度 kill-test 工具:`src/qount/l1_cross_asset.py` + 命令 `l1-cross-asset-breadth-scan`,
  拉 Tiingo 免费跨资产日线 EOD 面板(复权)、`state/` 缓存、as-of 周线、量 `_panel_effective_breadth`;
  research-only、无仓位、不算 IC。需 `QOUNT_TIINGO_API_KEY`(缺则返回 missing-key 提示不崩溃)。
- L4 跨所 funding spread kill-test 工具:`src/qount/l4_cross_exchange.py` + 命令
  `l4-cross-exchange-funding-scan` + `evaluate_l4_cross_exchange_funding`,ccxt 拉多所 perp funding
  历史(`normalize_funding_history` 复用)、`state/` 缓存、按各所原生结算间隔(相邻时间戳中位)
  归一到 8h 当量、as-of 对齐到 8h bucket、取 `spread=max−min` 的市场中性 pair、算扣费净 capture /
  break-even / required_maker_fill / pair 持续性 + 复用 §7 的 `_sharpe`/DSR/PBO;research-only、
  无仓位、不下单。三所需配置代理 + 跑前 `source .env`;不足两所可达返回 guard 不崩溃。已用于证伪 L4 S1。
- L6 微观结构数据/特征层:`src/qount/l6_microstructure.py`,解析 A股 逐笔 Level-2 Wind 三件套
  (十档盘口 `行情.csv`、逐笔成交 `逐笔成交.csv`、逐笔委托 `逐笔委托.csv`),交易所语义感知
  (深市撤单在成交文件 `成交代码=C`、沪市在委托文件 `委托类型=D`,按内容非后缀判别)、严格 as-of
  无前视对齐;stdlib only、live/`run-once` 不 import。
  - 日内 Phase 1 kill-test:命令 `l6-microstructure-ic-scan` + `run_l6_microstructure_ic_scan`,
    订单流特征(`ofi`/`depth_imbalance`/`micro_price_dev`/`trade_sign_imbalance`)对前向 mid 收益的
    rank-IC-vs-horizon 衰减 + 扣费 LS + DSR/PBO;已实测 IC 真高但可操作档净负(延迟墙)。
  - L6-daily 主线 ETL:命令 `l6-daily-features` + `compute_daily_feature_panel` /
    `daily_flow_features`,把全市场逐笔塌成每(股,日)五个日线知情流特征向量(`aggressive_ofi` /
    `large_aggr_ofi` / `late_minus_early_flow` / `close_auction_imbalance` / `cancel_imbalance`,
    区别于券商粗主力净流入),`--all-symbols` 枚举全市场;research-only、不算 IC、不下注。D0 已用
    20260407/08 全个股截面验证(99.8%/100% 覆盖、分布合理)。
- `pyproject.toml` 已有 research optional extra：默认提供 `numpy` / `scikit-learn`；
  `lightgbm` 单独放在 `research-lightgbm`，因为 Mac cp314 wheel 可安装但当前缺
  `libomp.dylib`，检查脚本会把它报告为可选不可用。验证入口：
  `PYTHON_BIN=./.venv/bin/python ./scripts/check-research-deps.sh`。

当前还不具备：

- Direct Stocks/ETF 的可用账户资格、权威持仓/可卖数量读取、自动执行与真实对账。
- Equity perpetual/tokenized equity 的完整symbol discovery、费用/结算、保护单和venue adapter。
- `SmallAccount-FOMC-RightSide-v0.2` 的仓库能力已具备，但VPS尚未部署该live runtime，生产未做私有preflight、未arm、未启用或授权。
- 稳定盈利能力证明。
- forward paper 许可。
- live 许可。
- 已通过 validation 的可复用窄 candidate gate。
- 已验证的 AI prompt v2/v3 改进。
- 多币 promotion gate。
- S1' 可 promotion 的稳定胜出 cell；目前 120 天 discovery / 月度 sanity 没有稳定胜者。
- Kronos 接入候选层或执行层。

## 历史 line-A 策略读数（已归档）

line A（`qount.main` eth-only）的 `最新策略读数 / WS-1..WS-4 / T-B / T-G / T-C` 历史 discovery 读数已移至
[archive/current-archive-line-a-readings.md](../archive/current-archive-line-a-readings.md)，按历史语境读取，不作当前事实。

## 架构判断

当前主要问题不是某个单点 bug，而是四件事叠加：

- 旧 promotion gate 与成交密度不匹配。
- discovery / validation 边界此前没有机器可读记录。
- AI prompt v1 过度保守，强候选上出现系统性 hold。
- `setup_model` v1 是 16 维线性 ridge，表达不了当前 alpha 所在的 phase × bin × bin 交互。

已接受的前置修复：

- [holdout.md](../holdout.md)：冻结 `discovery_pool`，定义 `validation_pool_v1`，改成
  `G_paper` / `G_live`。
- 研究 artifact 增加 `holdout_role`。
- AI 决策缓存只用于 research `backtest` / `walk-forward`，live / `run-once` 不使用。
- setup/candidate 层 walk-forward 被拆出来，降低端到端读数的耦合。
- readiness 语义改名为 `offline_future_edge_readiness`，不再暗示可 promotion。

## 运行状态

最近 WSL `.env` 读回：

```text
QOUNT_MODE=live
QOUNT_MARKET_TYPE=future
QOUNT_RULE_MODE=bottom_line
QOUNT_LIVE_ENABLE=false
QOUNT_SYMBOLS=SOL/USDT,XRP/USDT,BTC/USDT,ETH/USDT
QOUNT_MAX_OPEN_POSITIONS=3
QOUNT_CONTRACT_LEVERAGE=6
QOUNT_AI_MODEL=gpt-5.5
HTTP_PROXY=http://192.168.128.1:7907
HTTPS_PROXY=http://192.168.128.1:7907
```

注意：`.env` 仍是旧 4-symbol live 形状，不是研究证明口径。研究命令必须显式使用
`--research-profile eth-only` 或 `--research-profile multi-symbol`。

最近 runtime 读回：

```json
{
  "mode": "live",
  "exchange_id": "binance",
  "market_type": "future",
  "quote_currency": "USDT",
  "halted": false,
  "ai_failure_streak": 0,
  "day_start_equity": null
}
```

最近 live guard 读回：

```json
{
  "ok": false,
  "armed": false,
  "persistent": true,
  "live_enable": false,
  "reason": "live_disabled"
}
```

2026-06-04 运维读回：`QountBinanceProxy` 曾是 `Ready` 但 7907 未监听，导致
WSL `binance GET https://fapi.binance.com/fapi/v1/exchangeInfo` 走
`192.168.128.1:7907` 超时。已从 Windows 侧 `Start-ScheduledTask -TaskName
QountBinanceProxy` 恢复；WSL `curl --proxy http://192.168.128.1:7907
https://fapi.binance.com/fapi/v1/time` 返回 serverTime，`preflight-live` 的
public API / symbols / credentials / one-way / balance guard 均通过。live guard 仍因
`live_disabled` 拒绝，这是当前正确状态。

## 代码结构

- `docs/project-rules.md`：项目规则、文档分类、研究线隔离、代码治理和弃用清理纪律。
- `src/qount/settings.py`：运行配置与研究开关。
- `src/qount/research_profile.py`：`eth-only` / `multi-symbol` profile 覆盖。
- `src/qount/main.py`：CLI 入口。
- `src/qount/backtest.py`、`src/qount/walk_forward.py`：端到端研究执行。
- `src/qount/setup_model.py`：setup edge 模型、v2 interaction 研究、target slice、
  setup-edge walk-forward。
- `src/qount/ai_hold_baseline.py`、`src/qount/idle_window_diagnostic.py`：研究诊断工具。
- `src/qount/strategy_selection.py`：S1' 频段 × 策略族选择扫描引擎（约 1647 行），
  支撑 `strategy-selection-scan` 命令；triple-barrier / rank-IC / purged-CV / CARRY 双腿
  全部合并在此，纯 research-only，不调用 AI、不执行订单、不改 live。
- `src/qount/candidate_filter.py`、`src/qount/entry_quality.py`：候选生成、窄 blocker、research tags。
- `src/qount/orchestrator.py`、`src/qount/ai_client.py`：AI 决策、研究缓存、确定性 override。
- `src/qount/review.py`、`src/qount/research_slice_scan.py`：复盘和离线 readiness。
- `src/qount/artifacts.py`：研究 artifact 持久化。
- `src/qount/grid/`、`src/qount/rv/`、`src/qount/x4/`：线 B / 线 C / 线 D 独立模块。
- `src/qount/l1_cross_asset.py`、`src/qount/l3_information_edge.py`、
  `src/qount/l4_cross_exchange.py`、`src/qount/l6_microstructure.py`：已固化/证伪重启线的
  research-only 模块。
- `src/qount/mac_monitor.py`：旧 WSL / line A 面板入口，已加 legacy guard；默认不再执行。
- `tests/test_strategy_optimization.py`：策略、研究工具、artifact、walk-forward 主测试面。
- `tests/test_exchange_throttling.py`：交易所/候选执行边界测试。

## 验证状态

提交前必须保持：

```text
local unittest: PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
VPS unittest:   ./scripts/run-vps-tests.sh
```

2026-07-27 FOMC现金窗口告警合并后，本地全量
`PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'` 为 **2303 OK**；FOMC聚焦为`26 OK`。
源码/operations `compileall`、Node语法、Dashboard JSON schema、`git diff --check`和常见API key/AWS key/private-key header扫描通过。
Mac公共Binance探针按出口地区返回HTTP 451，VPS同一无凭据`fapi/v1/exchangeInfo`返回HTTP 200/1,042,597 bytes，因此Mac不作为事件行情源，
VPS部署前提成立。`0.2.18`部署后，VPS FOMC聚焦`26 OK`、notifications/dashboard关联`49 OK`、标准production profile`343 OK`；
release逐文件verification、systemd unit/calendar、公共collector、Dashboard原子readback和公网安全响应均通过。唯一unit warning是VPS既有
`cloudmonitor.service`配置；本轮未访问private API，未运行paper/live或订单路径。

最近一次本地完整结果：2026-07-20 Phase B/C账户事实、健康合同、仓位/决策追踪、publisher运维层和前端替换完成后，
`PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'` 为`1488 OK`；本批
operations/health/publisher/authority/system-health 聚焦为`29 OK`，唯一warning仍为既有
`src/qount/cta_data.py` UTC deprecation。此前paper v0.3聚焦在Mac/WSL均为`5 OK`，paper/shadow/readiness聚焦在WSL为`16 OK`，
exchange route聚焦另为`9 OK`，此前episode/信号退出冷却/
回测变换聚焦在Mac与WSL均为`14 OK`，相关 X4 funding/账本/波动率/吊灯最近一次为`37 OK`；Mac全量及
WSL聚焦`compileall`、两端CLI help、Bash语法、凭据扫描与`git diff --check`均通过；本批Node语法、13份schema解析、
含unavailable health的11个release JSON、Chromium fallback桌面/移动QA和Playwright桌面/移动QA也通过。Mac全量测试生成的六个
临时artifact目录已在每次复跑后定点删除，marker保护的WSL scratch已清空，Mac `state/`
恢复约12KiB。完整回归只有既存
`src/qount/cta_data.py` UTC deprecation warning。VPS `/root/qount` 本轮默认 production profile
合同/账本/通知/Dashboard/运维/authority writer/X4/RV 回归为 `299 OK`；显式全量 discovery 因生产最小环境不安装
numpy/websockets 等 research/collector extras 而有 8 个可选依赖错误，不属于生产回归。
`QOUNT_ALLOW_LEGACY_WSL=1` 规则不变；交易生产变更仍必须用 VPS unittest 验证。

## 下一步

按最新 owner 决策排序：

1. production publisher、authority writer、真实OS/systemd/backup探针、单写者、同盘原子release、有界release/backup保留和恢复演练
   已在VPS闭合；publisher与Daily Intelligence timer保持`enabled/active`，authority unit保持`static/inactive`，MiniTrend live/forward timer
   和production cron均保持关闭。publisher只刷新系统健康、release和备份，不查询交易所；账户/决策 authority在交易停用后应自然stale，
   不得通过提高阈值、复制旧JSON、恢复timer或手工调用交易路径洗新。
   NotificationStore与个人微信transport已完成真实`DELIVERED/SUCCEEDED`验证，后续只监控投递失败、限流和context token轮换；它不接
   legacy `Notifier`/shell ServerChan，也不赋予订单权限。VPS publisher仍只能读取完整batch/registry/ledger/notification/health/brief，
   不能读取legacy state JSON或复制fixture。
2. 跨资产推进按可捕获性排序，而不是同时建设所有连接器。P0 signed contract和P1 FOMC不可下单标准链、公共watcher、有限事件timer、
   Dashboard告警及order-free smoke均已在VPS完成；仓库`0.2.21`也已实现私有preflight、manual arm、deadline flatten、成交保护和
   venue execution合同，但未部署到VPS。任何生产安装、私有预检、arm、开关启用或订单动作仍必须另获单次精确授权。P2再做Direct Stocks read-only
   quote/rules/eligibility审计。没有权威holdings/
   `available_to_sell`、eligible account、已确认免责声明和完整venue reconciliation前，不建设Stocks自动SELL或live adapter。
   研究篮子从单一FOMC扩展到：FOMC/CPI/NFP/GDP/PCE事件后反应、美国cash/extended/overnight session错位、ETF/股票/
   tokenized/equity-perpetual mapping偏离、crypto funding/liquidation forced flow，以及跨资产趋势/风险状态。每条先回答谁被迫交易、
   扣成本后如何退出和什么现象证伪；一次性机会优先manual alert或script-assisted，不强塞进永久daemon。
3. 历史阶段中，一个月小资金实盘曾进入`standard_production`且registry为`minimal_live`；该路径现已由owner停止。
   2026-07-21 owner已把本金严格固定为
   `100 USDT`并要求直接推进Phase B/C/D，不等待约两个月日历累积。`60 forward pairs / 10 active bars / 30 paper days /
   7 unique dry days`现为Dashboard/readiness非阻断观察指标；它们当前为0只表示尚无时间样本，不等于策略0收益或系统错误。Funding完整性、
   当前私有预检、无未管理仓位/订单、one-way/isolated 1x、标准authority batch、RuntimeLedger、pre/post-dispatch
   reconciliation、UNKNOWN停机和有效manual arm仍是阻断门。dispatcher已要求订单提交前落`SUBMITTING`，market成交只接受
   交易所order+逐笔trade/fee证据；超时或证据缺失进入`UNKNOWN + HALT`且不重发，失败authority同步发布halted registry。
   四项观察值已纳入readiness hash防篡改但不进入blocker。Binance cash ledger保留原始`income`正负号，只白名单处理
   `FUNDING_FEE`、`COMMISSION/FEE`和`TRANSFER/INTERNAL_TRANSFER`；未知非零incomeType失败关闭，`REALIZED_PNL`
   由fill/position账本负责，避免重复记账。`1000 USDT`只作历史research/paper/order-free兼容上界，真钱readiness、arm、
   dispatcher和live journal均要求精确`100 USDT`。
   2026-07-22最终已由owner既有明确授权完成manual arm、`minimal_live` promotion、首次live闭环和recurring幂等复跑；
   2026-07-23已完成`0.2.15` standard-production迁移、新arm绑定和order-free验收。
   2026-07-26 owner因长期无订单将`qount-mini-trend-live.timer`停为`disabled/inactive`；forward timer和production cron继续关闭。
   冻结样本仍为0，不得为采集样本恢复timer或强制下单。
   旧X4/C×D cron与forward timer继续关闭，全局2.0%风险档和Funding Veto只能做shadow，不能控制真钱订单。

   历史`0.2.15` release当时回归为Mac全仓`1911 OK`、VPS生产链聚焦`71 OK`。Python compileall、Bash语法、release provenance、
   `systemd-analyze verify`和`git diff --check`通过；unit verify只报告无关cloudmonitor旧告警，唯一测试警告仍是既存
   `src/qount/cta_data.py` UTC deprecation warning。
4. Owner外部建议按 `docs/mini-trend-agent/review.md` 矩阵执行：Coin Metrics latest-vintage链上G0与经济
   审计已完成，算力预测成立但策略门失败；H.4.1 release-calendar/point-in-time G0、固定宏观特征和策略
   消融也已完成，4周变化预测保留但三档风险、事件闸门和边际boost否决均失败。Base episode归因进一步
   证明长趋势/吊灯是利润来源，唯一3日信号退出冷却trial只有边际改善且稳健门失败。累计trial已到143，不再用
   分位、窗口、冷却、分数阈值或投票参数救援。Coin Metrics future vintage只追加不回填；下一轮优先等待真正新
   vintage/双状态shadow forward，或研究不改变Base仓位/入场许可的只读预测校准。ADX、超1x、carry继续
   关闭，ML/Markov/叙事不得绕过策略经济门。
5. options-DVOL、historical option surface 与外部 liquidation/L2 均冻结在各自 block；不购买/下载 raw L2，
   不用 price-only IV inversion，也不消费 options 2025 replication 救旧结果。
6. Hyperliquid cross-venue state 虽有公开历史容量，但与旧 funding/cross-venue 失败机制重叠，不能直接作为
   第二候选；必须先写清不同于 carry/spread 的独立 predictor、400 USDT 单 Binance 执行语义和新的 G0
   protocol，且仍不得假设多交易所账户或 maker fill。
7. 任何新候选仍从 G0/G1 开始，先过 point-in-time、coverage、schema/checksum、400 USDT filter 和最坏
   成本；latest-vintage历史即使预测通过也不能获得promotion资格。discovery至少满足策略层raw return、
   BTC/TOP3 beta-residual和成本门，才允许设计独立forward。4060 sequence model继续位于tabular经济门、
   DSR/PBO、purged-CV和breadth/correlation gate之后；不再为本轮失败目标租A10。
8. 现有 Alpha S3 与 options-DVOL 失败证据全部冻结：不得在已看窗口调
   `z/holding/cooldown/polarity`，不得用
   HGB/LightGBM/Transformer rescue 固定 Logistic，也不得把 aggregate `bookDepth` 冒充 replayable L2。
9. 旧 `4h xs_mom`、S-CARRY、1d TS-MOM、5m GBDT、`range_noise` 和 Kronos 路径继续按既有诚实退出结论
   关闭；本次“推进加密”不代表复活这些已证伪路线。
10. A股 ETF 20 日线冻结：不补 Tushare parity、不做自动提醒或券商/QMT 接入、不执行历史条件；只有新的
   owner 明确决策才可重开。
11. 研究设计和文档留Mac，CPU/GPU计算及新增public data下载在WSL；共享1.6G VPS不恢复7天collector，生产
   crontab、private API、paper/live均保持关闭。新增大批量数据只在Windows/WSL侧直落外置盘，可直连或使用
   仓库外配置的Liangxin Cloud proxy；不使用苏菲家宽代理，也不把proxy URL/token写入代码或artifact。

硬边界：

- 不在缺少最终hash确认和manual arm时开live；当前arm、authority和账户安全门均已通过。
- 不自动启用forward timer；order-free B/C/D演练只允许手工一次性执行。
- 不把 `discovery_pool` 窗口当 validation。
- 不放宽 broad `range_noise` / `short_rebound_fail`。
- 不把 `offline_future_edge_readiness` 当 promotion 证据。
- 不把 Kronos 接入 candidate / risk / live。
- 不把 LightGBM 当默认研究依赖；当前默认 GBDT 路线用 sklearn `HistGradientBoosting`。
- 不把“恢复加密研究优先级”解释为恢复 VPS collector、private API、paper 或 live。
