# qount 更新记录

> **状态**：active（记录链）｜**权威**：L5 证据链｜**最后更新**：2026-07-26
> **本文回答**：近期（2026-07-16 加密重启起）执行记录、验证结果、读法。
> **TL;DR**：只记近期；2026-07-14 及更早见 `archive/update-log-archive.md`；结论以 current.md 为准。

更新时间：2026-07-26

这份文档只记录**近期**关键变更、验证结果和当前读法（2026-07-16 加密优先重启起）。
**2026-07-14 及更早**的历史证据链移入 [archive/update-log-archive.md](archive/update-log-archive.md)。
当前策略结论以 [current.md](current.md) 为准；复跑命令和跨主机操作细节放在
[quick-handoff.md](quick-handoff.md)。

## 2026-07-26 (Round 20)

### 0.2.16本地release基线完成全仓验证

**范围与权限**：owner授权对当前工作区执行add、补丁版本提升和push，以建立后续FOMC VPS接入所需的干净release基线。
包版本由`0.2.15`提升为`0.2.16`；该release归档本日已记录的Coding Plan聚焦补丁、跨资产有符号合同、Binance Stocks纯契约、
stablecoin/liquidity研究模块和`SmallAccount-FOMC-RightSide-v0.2`纯信号/风险/管理代码。它不恢复任何交易timer、cron或订单权限，
也不把本地版本冒充为已部署VPS provenance。

**验证**：Mac执行`PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'`，结果`2277/2277 OK`；
`git diff --check`与仓库源码/文档/脚本的常见API key、AWS key和private-key header扫描通过。后续FOMC标准链、shadow watcher、
告警和待命systemd单元作为独立release增量实现与部署。

## 2026-07-26 (Round 19)

### 200 USDT FOMC策略按两份评估升级为v0.2混合周期shadow合同

**决策与权限**：owner要求结合两份评估优化`SmallAccount-FOMC-RightSide-v0.1`。两份报告分别主张15m提速和更晚观察，
且都没有本账户成交或事件样本，因此没有把任一报告整体视为收益证据。合同升级为
`SmallAccount-FOMC-RightSide-v0.2`的`draft/research/shadow-only`版本，v0.1只作冻结对照；风险、账户与订单权限不变，
`orders_authorized=false/paper_or_live_allowed=false`。本轮未访问VPS、私有API、timer、paper/live或订单路径。

**信号优化**：事件前继续冻结72根完成1h的`H0/L0/ATR0`，新增冻结`V20_15m`；BLACKOUT后先等一根完成1h K收在
`H0+0.25ATR0`或`L0-0.25ATR0`外，再由完成15m K确认。突破K要求`>=1.5x V20_15m`、实体占比`>=60%`，
多头/空头close-location分别`>=0.80/<=0.20`；其后最多8根15m必须触及线外`0.10ATR0`范围并重收，重收量
`>=80%`突破量。多头任一回踩低点`<H0`或空头任一高点`>L0`即整次事件`NO_TRADE`；计划入场不得伸出突破线
`0.25ATR0`，冻结结构障碍前仍须满足全成本净`>=2R`。这既减少原两根1h加四根1h的延迟，也没有放弃1h方向过滤。

**时钟与退出**：本sleeve在上海时间01:00前必须CASH；记者会结束且声明后至少四根完整1h前继续BLACKOUT，
不无证据地硬等07:00/08:00，但shadow记录这两个反事实时间标签。最晚开仓从14:30提前到12:00，主动强制全平从20:00提前到19:00。
净`+1R`改由完成15m确认后推全成本保本；净`+2R`减1/3并完成fill/数量对账后，尾仓止损取旧止损、净`+1R`价格、
完成1h最有利收盘回撤`1.0ATR`中最保护利润的一侧，只能收紧。`0.5ATR`和前一根1h高低点只记录为反事实，不直接使用。

**实现**：新增`src/qount/small_account/event_signal.py`，纯函数输出`OBSERVE/ARMED/NO_TRADE`与稳定reason codes；新增
`src/qount/small_account/management.py`实现`+2R`后的单向tail-stop ratchet。新增信号/管理聚焦测试20个，覆盖多空对称、
原区间边界、深回踩失效、量能/实体/收盘位置、8根时限、12:00截止、完成K时序、部分退出确认和利润底线；连同原风险测试的
`small_account`聚焦回归为`45/45 OK`。

## 2026-07-26 (Round 18)

### 200 USDT个人事件右侧策略完成设计与确定性风险边界

**owner目标与权限**：owner明确以200 USDT、最大容忍回撤40 USDT设计个人交易系统，允许研究合约/short/事件策略，
但本轮没有绑定exact account/symbol/side/notional或下单时刻，因此只创建
`SmallAccount-FOMC-RightSide-v0.1`的`draft/research-only`合同与纯风险代码；
`orders_authorized=false/paper_or_live_allowed=false`。未访问VPS私有API、未恢复MiniTrend live/forward timer、未发订单。

**事实核验**：Fed官方FOMC日历与2026年7月日历确认会议为7月28-29日，声明/记者会为14:00/14:30 EDT，
即上海时间7月30日02:00/02:30；本次无预定SEP。BEA官方日历确认Q2 GDP初值与6月PCE均在同日08:30 EDT，
即上海时间20:30。因此特别版约06:00-06:30后才可进入观察、14:30后不新开FOMC仓位、20:00前强制全平。
CoinGecko `2026-07-26T13:07:10Z`快照为BTC 64,380、ETH 1,883.27、SOL 74.76 USDT；
固定67,200/64,000相对BTC现价约`+4.38%/-0.59%`，存在明显非对称，降级为观察参考而非订单阈值。

**策略与风险决策**：40U改为灾难缓冲，不再拆成两个20U正常止损。首个受保护live round trip全成本风险5U；
常规单笔及open+pending总压力风险上限10U；滚动24h亏损10U停机、正常策略高水位回撤20U停止、32U紧急flatten、
40U灾难红线。同时只允许一个crypto-beta方向，BTC合约与SOL现货互斥。BTC首版限制one-way/isolated/
`autoAddMargin=false`、杠杆`<=5x`、isolated margin`<=40U`、notional`<=200U`；严格40U tail模式下SOL现货
notional同样`<=40U`。仓位由结构失效价、压力越价、双边fee/slippage和funding反推，净计划收益必须`>=2R`。

**事件规则**：事件前冻结72根完成1h K的`H0/L0`、ATR14与20根成交量中位数；声明后至少4根完成1h K且记者会已结束前保持
BLACKOUT。方向只由连续两根完成K突破、第二根`>=1.5x`中位量、4根内回踩重收和全成本可执行性确认，
宏观/LLM文本只能veto/reduce/halt。达到`+1R`后才推到含成本的净保本，`+2R`减1/3并以1.5ATR追踪；
8根1h未到`+1R`退出，同一FOMC最多一次尝试。

**实现与验证**：策略全文见`docs/personal-200u-event-strategy.md`。纯风险模块位于`src/qount/small_account/`，
覆盖账户guard、首单降险、全成本仓位、quantity step、spot/futures硬上限与净`2R`门；聚焦测试见
`tests/test_small_account_risk.py`。风险模块自身`25/25 OK`；连同portfolio governance、标准runtime contracts、MiniTrend
preflight/dispatcher、RuntimeLedger、notification和system health的聚焦回归为`104/104 OK`，`py_compile`与
`git diff --check`通过。本轮不实现event watcher或执行适配器；后者必须先shadow并另获生产与manual arm授权。

## 2026-07-26 (Round 17)

### Owner停用MiniTrend实盘；Alpha Agent与生产日报切换方舟Coding Plan

**停盘与账户事实**：owner确认资金已从资金账号划回，并因策略长期不下单决定先停用。VPS
`qount-mini-trend-live.timer`与forward timer均为`disabled/inactive`，live无NEXT，production cron仍为0 entry；未触发订单路径。
旧oneshot失败标记已清为`inactive/dead`、`Result=success`，未删除journal，也未启动service。
停用后私有只读preflight为`account_preflight_pass`：可用/钱包余额=`464.0942153 USDT`、one-way、TOP3 isolated 1x、
持仓0、普通挂单0、unmanaged position 0，且没有账户变更或订单API调用。证据保存在
`20260726T121029Z-mini-trend-um-pilot-preflight-qount-stop-preflight-20260726`。

**Coding Plan接入**：Console名称`glm-5.2`映射API ID=`glm-5-2-260617`，base URL=
`https://ark.cn-beijing.volces.com/api/coding/v3`，provider=`volc_coding_plan`，输出上限从`2000`提高到`8000`。
首轮Responses在2000上限返回`incomplete`；提高上限后完整返回，但复杂提示即使声明`json_object`仍带单一Markdown围栏。
最小探针确认Chat Completions `response_format=json_object`可用，因此Coding Plan改走该接口；客户端只解包无前后附文的单一
JSON围栏，之后仍用标准JSON解析并执行严格五字段、简体中文、越权词和AgentReport合同。relay provider继续走原严格
Responses `json_schema`路径，未知provider和非allowlist base URL失败关闭。

**部署与验证**：Mac仓库外`~/.qount/alpha-agent.env`已设`8000`；VPS key通过stdin写入
`/etc/qount/intelligence/coding-plan.key`并保持`0600 root:root`，未回显、归档或提交。production unit显式冻结base/provider/
model/max tokens，日报timer保持`enabled/active`；本次没有手工运行完整日报或发送微信。Mac官方Fed feed单角色artifact
`/private/tmp/qount-coding-plan-smoke-20260726-r4.json`为`status=ok`；VPS不落盘中文单角色探针同为`ok`、五字段各有内容。
Mac/VPS聚焦回归各`28 OK`，compileall、CLI help、`git diff --check`和systemd verify通过；systemd仅报告宿主机无关
`cloudmonitor.service`旧警告。部署的LLM/runner/unit/两份测试文件SHA逐项相等；该精确运行补丁基于`0.2.15`，原release
provenance不冒充覆盖本次未提交补丁。

## 2026-07-26 (Round 16)

### Stablecoin v0.3 三源证据闭合 + 冻结 no-PnL G0 通过

**范围、文献与权限**：`research_sandbox`；owner 提供的 6 项 T1 proposal 已按可核实/未核实边界记录到
`research-advancement-roadmap.md` §9.1，未补写作者、DOI 或数字结论。stablecoin 本轮未读取市场价格、收益、PnL、方向或权重，
未碰 VPS/private API/paper/live/订单；formal strategy trial 保持 `148`，family trial 保持 `0`。冻结 preregistration 的
protocol=`5c48cc7ce78889c3eae288c0bdf8210640bccfbb57914eb8a11eb0c8bd8420dc`、contract=
`38ab023545cd4dc027e0b319ce0909e23f666c1729ed30a5ef6b1d67f25df539`、file SHA=
`8e1b143bd4c3d57dc1432170db48118ab7e2fa8f8763be61552738228b0189a5`；本地重新校验合法。

**v0.3 collection 与零值合同**：不可变 collection=
`/mnt/e/qount_data/qount/datasets/stablecoin_chain_events/v0.3/20260726T101608Z`，manifest=
`859a4904ad4eb2be6c1d81a79c252754fd01824405741f5e69dc40138638458f`。USDT Ethereum、USDT TRON、
USDC Ethereum 的 lineage/economic/zero-excluded 分别为 `6,893/6,893/0`、`2,007/1,016/991`、
`2,710,040/2,710,040/0`；TRON treasury 为 `383/380/3`。991 条零金额 Transfer 保留 raw/finality lineage，
但不进入 economic flow/count，不再把 lineage 数与正金额经济事件数错误比较。三源均为
`stablecoin_chain_event_source_v0.3`，`semantics_verified=true`、`exact_availability=true`、blockers=`[]`。
manifest 共 47 个 member、12 个 gzip；成员 size/SHA 全匹配，全部 gzip 完整解压，record count 与 uncompressed SHA 全匹配。
旧 v0.2 collection manifest 仍为
`7b57486ed19e0d9c21dd95583b208a50fc0b6f96725672914fdecc43f048ac65`，未覆盖或改写。

**USDT Ethereum zero-address/treasury、ABI/proxy/owner proof**：initial EOA 从 deployment 到 activation 完整扫描
`111` blocks / `11,199` transactions，核验 owner->token receipts=`2`。Sourcify multisig verified source SHA=
`6eec72c23a95a15c2c60865f3f7e2fd8f044cc81a7d8e69e0f0347e1401e002d`，ABI SHA=
`39401071b306d13610235a62ad470c3b172220f0edf0e2d714caa5cdb2b92e98`；`transactionCount()` 与全部
`transactions(id)` 枚举得到 `5,544` slots，其中 executed=`5,191`、token destination=`5,390`、executed
`transferOwnership=0`。owner proof file SHA=
`14abab4a961e6cc330ec4f15c54da55a005446b001002751273b7bb464f0fcc6`，内嵌 proof hash=
`659fd5f0165a13f1951a0acd773725598202d8e5365626aea38eb0c58d977fd2`；三份 raw sidecar 可独立重建出 canonical-equal proof。

**Runtime 证据读法**：activation/observed 两个链上高度的 full runtime 完全一致。Sourcify
`runtimeMatch=match` 通过 Solidity CBOR metadata 边界解释：compiled full runtime SHA=
`86ea62e9028d124c7515206fe9baf5af56549a16ed5c09e428afce2b4ba30e37`，on-chain full runtime SHA=
`a658996593d84755b24195fc9c863efc567cd43610e736c461a85a229671eac2`，二者只在 metadata 不同；去 metadata 后
executable runtime SHA 均为 `2d4ae76b055a10b02052423062532dc954bd51caa4ceb90c72537d8a0889e2c9`。未将这一
`match` 写成 `exact_match`；后者仍要求 full runtime hash 完全相同。

**冻结 G0 重跑**：不可变 bundle=
`/mnt/e/qount_data/qount/artifacts/experiments/stablecoin-liquidity-impulse-g0-v03/bundles/`
`e725e66a4fd215d5aa71a43c0d21e54efa0db9229c17c911e6353028ce8695b7`。六组 hash 为 manifest=
`3b1b0c3e1f636534853cd7ce212d644c1a5f14e5479ac8907698b606a08b3252`、result=
`d72b82d05c0243e522da15d1ec84bf90bd982b50d7a92cbe6fd47f112063f760`、weekly=
`965dd20381a0712af9aa1dfffb86919dd8d1ddc57a86e33cb30a146c3b8e3c4e`、source inventory=
`92e55f8cf8577678a6929aeb0640f846ba5e786b862a88394b417219bcbd6b0e`、code=
`3f32da6e0525682a66d7ee94755edb2445cc80a5317b061e93045ef64cb8999e`、bundle id 即目录名。52 个输入、4 个成员及
全部 canonical hash 独立重算一致。

**G0 读数与边界**：verdict=`pass_to_market_state_design`，weekly anchors=`376/376`、aggregate anchors=`209/209`、
classification coverage=`1.0`、remaining blockers=`[]`，8 个 kill test 全 false。mint/burn/treasury/cross-chain/unknown=
`1,688,417/1,028,517/679/18/0`，transaction semantic duplicates=`318`，cross-chain clusters=`9`，zero lineage
excluded=`991`。aggregate 对照 Spearman=`0.6479546769020453`、R²=`0.4186931641216695`、offsetting ratio=`1.0`，
`equivalent_to_aggregate_supply=false`；exact finality median/p99/max=`768/979/1701s`。`market_data_read`、
`strategy_results_read`、`pnl_evaluated`、`formal_strategy_trial_created`、`promotion_evidence`、`orders_authorized` 全为 false，
`candidate_pnl_ready=false`；该 pass 只允许另立结果前 market-state 合同，不授权策略 PnL、promotion、paper/live 或订单。

**RPC 与实现诊断**：有界 retry/pacing 下，PublicNode 缺所需 archive state，dRPC 返回 HTTP 429/500，Merkle 返回 429；
最终 BlastAPI 完成公开历史证据获取。当前关键实现 SHA：chain event=`63c898e0...7980`、remediation=
`ec120120...19b9`、G0=`7fb6f3d9...42cb`、remediation runner=`783d4226...b26d`、G0 runner=
`8aeb13b0...e560`。Mac 项目 `.venv` 与 WSL 分别 **34/34 OK**，两端 focused `py_compile` 通过；外置盘 collection/G0
全量只读复核通过，`git diff --check` 通过。

## 2026-07-26 (Round 15)

### Stablecoin 三源 evidence remediation + no-PnL G0 rerun：exact confirmation 闭合，容量仍阻断

**范围与权限**：`research_sandbox`；复用冻结 preregistration `e1dd4a4a...ba37`、source-capacity
`69463c84...bea`、DefiLlama aggregate baseline `e93067db...bd3`。未读市场价格、收益、PnL、方向或权重，未碰
VPS/private API/paper/live/订单；formal strategy trial=`148`、family trial=`0`。

**Remediation collection**：固定 run-id=`20260725T171019Z`，output=
`/mnt/e/qount_data/qount/datasets/stablecoin_chain_events/v0.2/20260725T171019Z`。USDT Ethereum/USDT TRON/USDC Ethereum
事件数=`6,893/2,007/2,710,040`，implementation 数=`1/1/4`；USDC 3 次升级、TRON 两段 owner history 完整。三源均有
exact confirmation sidecar：Ethereum `event block + 64 blocks`，TRON `event producer + 18 distinct subsequent SRs`。
collection manifest=`7b57486e...ac65`；独立 verifier 重算 canonical manifest、42 个成员、4 个代码源，并完整解压 9 个 gzip
校验 record count、compressed/uncompressed SHA，全部一致。唯一 source-level semantic blocker 是 USDT Ethereum
`ethereum_owner_history_round_trip_absence_not_proven`，未将 451 个等值 checkpoints 写成无往返证明。

**初跑与实现核验**：`stablecoin-g0-v02-r1` exit=`0`，bundle=`e9938c41...54d`。随后逐交易交叉核验发现 G0 的
TRON zero-address 常量少一个 `k`（错误 `...h8unkh...`，正确 `...h8unkkh...`），使 318 条应与 native
`Issue/Redeem` 配对的 zero-address `Transfer` 被误分为 treasury，transaction semantic duplicate 错报为 0。修复
`stablecoin_impulse_g0.py` 并新增集成回归 `test_tron_zero_address_transfer_is_semantically_deduplicated`；r1 artifact 不覆盖，
仅保留为实现缺陷的历史证据，不作为当前读数。

**修正后 G0 r2**：job=`stablecoin-g0-v02-r2` exit=`0`；相同独立输出根=
`/mnt/e/qount_data/qount/artifacts/experiments/stablecoin-liquidity-impulse-g0-v02` 下生成新 bundle=
`2c1ed8cd68e20e0836477ef5a1bf51a9c1433a17bd525dd192e060a3865ecb6e`，manifest=
`76c4fab962420fea85713e366f1a108d29f1cc56513210169dfbeb7f1874abd7`。4 个 member 的 size/SHA 逐项一致；
manifest/result/weekly/source-inventory/code/bundle 六组 canonical hash 独立重算均匹配，bundle 目录名也匹配；r1 仍存在。
运行代码 SHA=`e7ca6f18...3e4f`，结果 canonical hash=`7573db97...4ec3`。

**读数**：共同窗口=`2019-04-17..2026-06-24`，weekly anchors=`376/376`；aggregate comparison=`209/209`，
Spearman=`0.6479546769`、R²=`0.4186931641`、material offsetting ratio=`1.0`，因此
`equivalent_to_aggregate_supply=false`。有效事件分类 mint/burn/treasury/cross-chain/unknown=
`1,688,417/1,028,517/380/18/299`，coverage=`0.9998899777`；raw/transaction duplicates=`0/318`，跨链 cluster=`9`。
validated-event exact delay 中位/p99/max=`768/979/1701s`，低于 6 小时门。

**TRON 独立语义核验**：2,007 条 raw/finality rows 均通过 `producer + 18 distinct subsequent SRs` 检查且 raw identity
duplicate=`0`；事件构成为 native=`318`、zero-address Transfer=`1,306`、treasury Transfer=`383`。其中零金额分别为
zero-address=`988`、treasury=`3`，正金额事件=`1,016`；318 个 native key 与 318 个正金额 zero-address key 一一配对，
与 r2 的 transaction semantic duplicate=`318` 一致。

**阻断读法**：verdict 仍为`block_capacity`。USDT Ethereum owner-history 未闭合使 299 条 treasury 候选保持 unknown；
USDT TRON 的 991 条零金额 Transfer（988 zero-address、3 treasury）被冻结的正金额事件校验判 invalid，使 exact-finality
声明=`2,007`、G0 正金额有效事件=`1,016`，treasury 声明=`383`、G0 正金额有效事件=`380`，分别触发 finality/treasury
count mismatch。当前 true kill tests 为 classification、event/treasury semantics、
transaction audit、cross-chain audit 与 revision/finality count；source coverage、weekly/baseline 和 aggregate-equivalence
均未触发。r1 和旧 Round 14 bundle 均不覆盖。下一次 remediation 必须先冻结零值 lineage/经济排除合同并取得 owner-history
的完整状态变更证明；不得 post-hoc 过滤救援，也不得据非重包装结果跳到 market-state。

## 2026-07-25 (Round 14)

### Stablecoin marginal-flow G0 completed: data-capacity block, no strategy trial

**范围**：`research_sandbox` no-PnL G0；所有历史=`consumed_historical_discovery_pool`，未读价格、收益、PnL、方向或权重，
未碰 VPS/paper/live/订单。formal strategy trial 保持`148`，family trial=`0`。

**冻结合同与采集**：预登记固定三源共同窗口、UTC周锚点、`2026-07-01T00:00:00Z` exclusive cutoff；aggregate baseline 比较
固定为 2022-06 起的 209 anchors。公开端点重建的 full-history collection 位于
`/mnt/e/qount_data/qount/datasets/stablecoin_chain_events/v0.1/20260725T133234/`，manifest hash=`7fce3d72...ca4c0`；
USDT Ethereum=`243`（首事件 2017-11-28）、USDT Tron=`318`（2019-04-18）和 USDC Ethereum=`2,710,040`
（2018-09-10）。9 个 manifest member 重算全部一致，6 个 gzip sidecar 通过完整性检查。

**工程与可扩展性**：Tron Base58 地址改为大小写保真的原地址；Ethereum provider 的`blockTimestamp`优先使用，避免为每个
事件块下载完整 block。原始 provider rows 与标准化事件改为确定性 gzip NDJSON sidecar，collection manifest-last；G0
逐行消费 sidecar、使用紧凑事件对象，并把周频聚合改为单次有序游标。ExFAT 无法表达 POSIX mode，因此 bundle 改为唯一目录+
`xb` write-once+fsync+SHA readback+manifest-last，不降低成员不可覆盖或完整性核验。

**G0 读数**：共同窗口 `2019-04-24..2026-06-24`，weekly independent samples=`375/375`；classification coverage=`1.0`，
raw/transaction duplicates=`0/0`，跨链 cluster=`9`（18 events）。aggregate comparison=`209/209`，Spearman=`0.647955`、
R²=`0.418699`、material offsetting-flow ratio=`1.0`，故`equivalent_to_aggregate_supply=false`。但三源的 zero-address/
treasury transfer、ABI/proxy/treasury 历史语义及 exact historical finality/available-at 均不完整；近似 Ethereum delay
中位/p99/max 均为`768s`，不能冒充 exact clock。verdict=`block_capacity`，不是机制拒绝，也不产生 market-state。

**证据与验证**：bundle=`17f6440a...06c58`，manifest=`8832719e...cf841`，5 个 bundle member hash 重算无差异；
Mac `tests.test_stablecoin_impulse_g0 + tests.test_stablecoin_source_capacity`=`18 OK`，WSL G0 suite=`10 OK`，两端新增模块编译通过，
`git diff --check`通过。下一步只允许补齐上述 source semantics/finality 证据后重跑 G0；不得以当前非重包装读数跳过容量门。

## 2026-07-25 (Round 13)

### 研究记录归位（roadmap v0.8）+ 文档整理计划执行（Phase 1/2/4/5，Phase 3 refined）

**范围**：纯文档，不改代码/生产。承接 owner 批准的 5 阶段文档整理计划。

**研究记录归位（roadmap → v0.8）**：把 Round 11 的 Track A/B/C 最终读数写入路线图：
- `multi_speed_trend_v1` 3/3 CLOSED；`market_breadth_dispersion_v1` 10 币 `block_capacity`（相关广度 1.6602<2.0，真实容量）
  CLOSED，`cross_sectional_residual_momentum_v1` 传递 CLOSED；`liquidity_capacity_meta_v1` `pass_to_capacity_calibration`；
  `crypto_vol_crisis_state_v1` Trial 148 REJECT（尾残差恶化，1/3）；`stablecoin` `pass_to_g0`。
- §11 从"数据工程 to-do"改写为"已完成 + 下一轮候选（liquidity calibration/stablecoin G0/vol-crisis 2-3/carry/前向采集）"。

**文档整理**：
- **Phase 1（文档头标准化）**：33 份文档全部加统一状态头（活跃：状态/权威 Lx/最后更新/本文回答/TL;DR；19 份遗留：
  frozen 标签指向 archive/README）。
- **Phase 2（current.md 瘦身）**：3062→**1615 行**（−47%）。两步移档到 `archive/current-archive-line-a-readings.md`，
  原位留指针，逐行守恒：① line A 历史读数（`最新策略读数/WS-1..4/T-B/T-G/T-C`，951 行）；② `当前结论` 中 **2026-07-16
  加密重启之前**的历史详细条目（按日期分组，51/82 块，504 行）。post-check 确认 current 中 0 条 pre-07-16 leading-date 条目。
  保留：`当前结论` 的 fenced summary + 31 个 2026-07-16 起的当前条目。
- **Phase 3（README 去 line-A 误导）**：因 line-A CLI 与当前 env 文档交织（非计划假设的连续块），改用**加 line-A 历史横幅**
  （初始化/Review 工具/当前流程）而非抽取，避免误删当前 env 内容；未新建 line-a-cli-reference.md。
- **Phase 4（架构一页图）**：`system-architecture-design.md` 顶部加「架构一页总览 TL;DR」（权威链/节点拓扑/生产vs研究/LLM 边界）。
- **Phase 5（一致性护栏）**：`project-rules.md` 新增 §10「文档维护规则」（文档头模板、单一事实源、清理=移动不删、接手 3 步可达性）。

**验证**：`git diff --check` 干净；current.md 与 update-log 拆分逐行守恒；33 文档头全覆盖；活跃文档内部链接全解析
（仅两份归档文件内 line-A 历史相对链接从 archive/ 目录失效，已在归档头加说明）。纯 Markdown，无需跑测试。

**owner 已决策并执行**：`current.md` 的 `当前结论` 已按 2026-07-16 加密重启边界切分（更早移档、之后保留）。

## 2026-07-25 (Round 12)

### 文档梳理：恢复 CLAUDE.md 接手入口 + 拆分 update-log + 分类归位

**范围**：纯文档治理，不改代码/策略/artifact，不碰生产。目标是让接手模型更容易遵守规范、看清架构/工具/纪律。
按 owner 选择"保持原地 + 强化导航"（不删/不移遗留文档——审计显示每份被引用 3–21 处，且 archive/README 明确约定原地保留）。

- **恢复 `CLAUDE.md`**（此前被删且 HEAD 版本是过时的 line A/GRID-B 结构）：重写为准确精简的接手入口——交流约定、
  权威顺序、接手先读顺序、文档地图（活跃 vs 归档）、主机/工具定位、测试入口（Mac unittest / WSL `run-wsl-tests.sh`）、
  研究纪律、硬边界、代码架构、记录规则。
- **拆分 `update-log.md`**（7572 行）：保留 2026-07-16 加密重启起的近期记录（3100 行），2026-07-14 及更早移入
  `archive/update-log-archive.md`（4472 行）；两端加指针，内容逐行守恒（3100+4472=7572）。
- **分类归位**：`project-rules.md` §3 新增两行（加密研究草稿/外部拆解、接手导航 CLAUDE.md），§1 补 CLAUDE.md 导航说明；
  `archive/README.md` 加 CLAUDE.md/roadmap 入口与历史记录归档段；`README.md` 文档入口补 CLAUDE.md 与 3 份新研究草稿。
- 3 份新文档（`carry-active-basis-hypothesis`/`crypto-vol-crisis-state-preregistration`/`external-bot-cra-teardown`）
  正式接入分类与导航。

**验证**：纯 Markdown 变更，未跑测试（无代码改动）。文件行数守恒已校验。

## 2026-07-25 (Round 11)

### Trial 148 危机状态 + Track A 数据脚本 + Track C stablecoin 容量

**范围**：research-only；全程`orders_authorized=false`，未碰VPS/paper/live。formal trial由`147`推进到`148`。新增18测试；全量2147 OK。

**Track B: `crypto_vol_crisis_state_v1` Trial 148（1/3，REJECT）**：
- 三信号危机合成（下行半方差+BTC-alt相关性跃升+funding极值）-> RiskMultiplier[0,1]，叠加到Base/multi-speed(145)/fixed-vol-target三基线。
- 5/6门通过，唯一失败：`tail_residual_improvement`——三基线的crisis-scaled尾残差均恶化（Base 19.96%->16.62%，multi 18.92%->17.73%，voltarget 12.68%->9.95%）。
- 回撤改善极小（0.81pp/0.26pp/0.69pp），分段改善3/3（非单次崩盘拟合）。去风险时机不精准。
- 与旧price-only vol/HMM/GRU和147快层de-risk均有书面区别，但机制不够有效。bundle=`8ea84158...020cc`，decision=reject。

**Track A 最终结果（WSL 10币计算）**：
- WSL直连`data.binance.vision`下载全部10币UM 1d klines+fundingRate（751 OK / 29 fail，fail为上市前月份）。
- `fapi.binance.com`从WSL不可达（直连和7907代理均超时）；exchange rules从kline数据推断（10/10 present，coverage=1.0，min_notional=5.0研究代理值）。
- **breadth G0**：有效广度`1.660`<2.0 -> `block_capacity`。特征值广度2.511>2.0但相关广度仍不足。PC1`0.615`<0.85（通过）。
  分段：2020-21=`1.890`、2022-23=`1.409`、2024-26=`1.397`。downside广度`1.675`。
- **liquidity G0**：`pass_to_capacity_calibration`（rules覆盖1.0、10币中位成交额213M-12.5B USDT、Amihud通过）。
- **容量结论**：10币相关广度1.660<2.0是真实容量限制，与LiquidTrend10 1.438一致方向。按规则不放宽广度门、不扩币。
  breadth/dispersion family和cross_sectional_residual_momentum被阻断；liquidity family通过。

**Track C: stablecoin source-capacity**：
- `stablecoin_liquidity_impulse_v1` source-capacity artifact：3个链上PIT源（USDT ETH/Tron + USDC ETH）不可变可重建；attestation部分可追溯；exchange inventory仅latest。verdict=`pass_to_g0`。
- 与已失败aggregate supply的区别：目标是marginal mint/redeem flow，不是总供应增速。

**下一步**：breadth/残差横截面已关闭（容量不足）；liquidity可进capacity calibration；前向4 schema待owner决定启采集器；stablecoin source-capacity已通过可建G0；carry active-basis可并行historical/discovery。

## 2026-07-25 (Round 10)

### multi_speed_trend_v1 家族关闭 + P0 横截面 G0 阻断 + 前向/PIT 审计

**范围**：research-only；全程`orders_authorized=false`、`data_role=consumed_historical_discovery_pool`，未碰VPS/paper/live/订单。
formal trial由`145`推进到`147`。新增34测试；本机核验已过（见下）。

**multi_speed_trend_v1（3/3 完成，family关闭）**：

- Trial 146 连续z-score等权：6/9门，REJECT。CAGR `13.06%` < Base `19.88%`；maxDD `21.51%` 恶化`5.33pp`（超2pp门）。
- Trial 147 分层状态机（slow regime + medium + fast de-risk）：7/9门，REJECT，触发family复盘。
  CAGR `15.90%` < Base；只1/3分段跑赢。maxDD `9.70%` 改善`6.48pp`（三试最优）；双成本`+14.05%`、延迟`+14.18%`、
  top3 residual `+7.98%`。bundle=`2e17c4fd...f05f6`，decision=reject。
- **复盘结论**：三试主指标全败，按"不救援"关闭family。关键修正——Trial 147降险是**低效降险**：turnover `70.04` vs Base
  `50.56`（+38%），Sharpe `1.291` < Base `1.416`，回撤改善是敞口下降副产品而非alpha。仅保留为`crypto_vol_crisis_state_v1`
  需区别的旧证据。

**P0 横截面 G0（均 block_capacity，同一根因）**：

- `market_breadth_dispersion_v1`：有效广度`1.2253`<2.0、PC1`0.8169`>0.85、7/10宇宙symbol缺失、PIT universe不可重建。
- `liquidity_capacity_meta_v1`：rules覆盖`0.0`（PIT rules artifact缺失）、7 symbol缺失、盘口采集未启动。
- **读法**：非机制否定，是数据阻断——`state/r0_runtime/klines|funding`只有TOP3。补齐7个alt（SOL/XRP/DOGE/ADA/LINK/AVAX/LTC）
  与PIT exchange-rules快照后重跑；若10币仍广度<2，是与LiquidTrend10`1.438`一致的真实容量结论，按规则关闭。

**前向衍生品 schema（Wave 3）**：4 family全`continue_collection`，冻结raw source/clock/dedup/gap/独立窗口，
`read_results_before_window=false`；未达窗口不读结果。

**外部PIT source-capacity（Wave 4）**：选中`stablecoin_liquidity_impulse_v1`；阻断`network_adoption_quality_v1`/
`venue_rule_event_v1`/`token_supply_event_v1`。标准`pit_vintage_availability_first`。

**验证（本会话独立核验）**：Mac无pytest，改用`PYTHONPATH=src python -m unittest`跑新增7个测试文件=**34 tests OK**，
`test_cta_eval`=22 OK。逐项核对Trial 147 artifact数字（CAGR/maxDD/turnover/beta-residual/门计数）与global record
`decision=reject`一致；门逻辑为数据驱动非硬编码（`multi_speed_state_machine.py:461`）。全量2137未在Mac复跑（应在WSL侧）。

**下一步**：见`research-advancement-roadmap.md`§11。绑定约束是Track A数据工程（补齐宇宙+PIT rules，解锁breadth/liquidity/
residual momentum三线）；Track B `crypto_vol_crisis_state_v1`可并行在TOP3上立即跑（须区别旧price-only缩放与147快层de-risk）。

### 外部机器人 CRA（币富量化）拆解 → `docs/external-bot-cra-teardown.md`

owner 提供第三方付费AI交易软件说明（3份PDF），要求吸收方法。已按T4厂商营销材料拆解：

- **核心机制**：马丁加倍补仓（1→2→4→8→16x）+ 1–100x杠杆 + 高循环，外套 EMA60/EMA10/振幅开仓过滤。
  "每天盈利几十刀"是马丁特征（高胜率小盈利掩盖左尾），排行榜=幸存者偏差，点卡/激活码/邀请分佣=类MLM变现。
- **可吸收（正向）**：①防瀑布"1分钟急跌>2%暂停加仓"→喂 `crypto_vol_crisis_state_v1` 的de-risk规则；②反向信号退出→退出/换手对照想法。
- **映射**：顺势(EMA60×EMA10多周期)≈已关闭的`multi_speed_trend_v1`变体；逆势(振幅fade)≈已证伪的capitulation-rebound/`range_noise`。
- **拒绝**：马丁/杠杆/扩币/第三方API托管/采信排行榜收益——均与硬边界和跨线经验冲突。
- **处置**：不新增研究线、不改Base、不进paper/live；仅把两条风控规则记入Track B ResearchCard候选，走标准kill test。

### crypto_vol_crisis_state_v1 无结果预登记草稿 → `docs/crypto-vol-crisis-state-preregistration.md`

按owner要求把CRA两条规则写进Track B家族预登记草稿。DRAFT，`orders_authorized=false`、`existing_cache_only=true`，未跑实验。

- 家族只输出RiskMultiplier∈[0,1]纯降险overlay，不择向；Base为控制组(RM≡1)。
- Rule-1 anti-cascade改写为日线因果崩盘触发(3σ下行/振幅扩张，floor 0.3，3 bar冷却慢回)；Rule-2 reverse-signal改写为
  非方向regime-flip降险；新增BTC-alt相关跃升(>0.9)作为区别price-only缩放的新信息。
- 主指标=降险效率(drawdown saved/return sacrificed)+尾部CVaR残差；kill test直接瞄准147低效降险失败轴
  (效率<1、Sharpe恶化、turnover>1.3×Base、单段拟合、等价对称vol-target即拒绝)。冻结阈值不作参数搜索。
- 诚实标注：CRA原1分钟规则当前TOP3日线缓存无法真分辨率复现，§3.1为日线proxy，真验证是sub-daily/前向数据任务。
- 已从roadmap R3加指针。下一步owner评审冻结阈值→build hash生成preregistration.json→在TOP3缓存跑Trial 1。

## 2026-07-25 (Round 9)

### 加密因子研究图谱、来源矩阵与验证路线文档化

**范围**：owner要求只更新详细研究计划并由owner后续实验验证。本轮没有修改策略/数据代码、没有运行回测或测试、
没有创建research artifact、没有访问VPS、私有API、timer或订单路径；formal strategy trial保持`145`。

**一手资料核验**：通过确定性HTTP/API读取Crossref、NBER、BIS和Binance官方GitHub仓库，而不是把模型记忆当作web evidence。

- 核对了TSMOM、trend century、momentum crash、volatility-managed portfolios、crypto market/size/momentum、
  crypto network/attention、跨所套利/分割、BIS Crypto Carry、Amihud、Corwin-Schultz、DSR、PBO和Gu-Kelly-Xiu的
  DOI或官方working-paper身份。
- 修正来源索引：Makarov-Schoar *Trading and Arbitrage in Cryptocurrency Markets* 的正式版本为
  `10.1016/j.jfineco.2019.07.001`；此前建议中的NBER `w25234`实际是另一篇计量论文，不再作为该研究引用。
- Binance开发站在当前命令行路径返回WAF challenge，故字段和可用期以官方`binance-public-data` README与新的
  `binance-connector-python` source定义交叉核对。确认公开archive有日/月文件、kline taker-buy字段、`.CHECKSUM`和可修订历史；
  OI statistics只保留最近1个月，basis、taker、global/top-trader long-short ratios只保留最近30天，funding history支持按
  时间分页。实时liquidation只能作为前向采集，不声称有官方完整历史归档。

**计划扩展**：

- 路线图从六条加密family扩展为分层因子图谱：核心趋势/广度/流动性，残差动量/危机/funding，OI-basis-liquidation-
  cross-venue前向结构，stablecoin-token-network-venue事件外部PIT，calendar/execution，options/allocator条件项。
- 每条family现在固定经济机制、决策时钟、最小原始源、PIT与修订规则、独立样本单位、baseline、主指标、成本/beta residual、
  kill test、允许敏感性、trial预算、既有负证据边界和promotion blocker。数据先过G0/source-capacity，失败时不读PnL。
- 新90天路线按Wave 0-5分解：先冻结ResearchCard和G0，后做现有低频trial，再积累前向衍生品窗口，最后才考虑外部PIT、执行或
  allocator。前向短历史不能被重叠切片伪装成多个fold；组合不能回记单腿netting收益。

**文档更新**：

- `docs/research-advancement-roadmap.md`：升级到`v0.6`，新增全面因子图谱、官方数据/时点合同、Wave路线和一手来源矩阵。
- `docs/crypto-portfolio-system-plan.md`：扩展sleeve候选地图、ResearchPacket接口、因子到策略组合边界、90天路线和首批研究任务。
- `docs/alpha-agent-plan.md`：把agent交付限制为ResearchCard，补Source Librarian/Data-Clock Skeptic/Economic Reviewer/
  Replication Designer/Red Team审查链。
- `docs/current.md`：记录文档级扩展、不新增trial以及短历史数据必须append-only的当前事实。

**不变约束**：外部文献只支持假设和方法，不证明qount收益；Base仍是唯一生产控制，Trial 145仍拒绝且不救援；
CTA-R/C×D仍冻结次级旁路；no-carry/no-short/effective gross`<=1`约束、options capacity block和全部paper/live/order权限不变。

## 2026-07-25 (Round 8)

### 加密优先因子拓展与 Trial 145：方向一致性降回撤，但主指标未超过Base

**方向调整**：owner要求优先拓展加密线、多找因子并测试更多策略。CTA-R的Round 7历史证据保留为
`retain_for_discovery_revalidation`，但主动优先级降为冻结次级旁路；C×D同样不占当前研究预算。当前加密研究拆成
`multi_speed_trend_v1`、`cross_sectional_residual_momentum_v1`、`crypto_vol_crisis_state_v1`、
`funding_crowding_meta_v1`、`liquidity_capacity_meta_v1`和`oi_flow_forward_v1`六个互相独立的假设族。

**实现与预登记**：
- 新增`src/qount/mini_trend/multi_speed_trend.py`和`scripts/research/run_crypto_multi_speed_trend.py`；现有UM历史执行器
  新增显式的候选target selector、交易成本倍率和funding倍率入口，默认Base行为不变。
- Trial 145是`multi_speed_trend_v1`的第1/3个冻结trial：20/60/120日总收益全票为正，120日BTC或2/3 breadth
  慢门，long/cash、gross`<=1`；风险预算、相关惩罚、deadband、3xATR、3日冷却、funding和12bps成本均与Base对齐。
- 结果读取前先写无结果预登记：contract=`62aaa607...166a1`、protocol=`304bc24d...14ec7`，
  `strategy_results_evaluated=false/orders_authorized=false`；只允许双倍交易成本和额外一根信号延迟两项压力。

**数据与artifact**：
- 只读本地`state/r0_runtime`缓存，462个UM日线/funding压缩包全部入SHA-256 inventory；共同窗口
  `2020-02-10..2026-06-30`为2333行，warmup后2132个持有区间。BTC/ETH/BNB每个区间均有2-4次funding结算，
  零结算间隔为0；data hash=`40e8e080...a16e`。
- bundle=`d4ca0c3eaa82e15674a1d83bf803aa7078f730d00856670451767577b1d50cb8`，5个成员加manifest-last，
  member/manifest hash和`0700/0600`权限均已回读。

**结果**：

| 口径 | Standalone proxy NAV | CAGR | Sharpe | maxDD | turnover |
| --- | ---: | ---: | ---: | ---: | ---: |
| Base v0.2同窗 | 2.8836x | 19.88% | 1.416 | 16.18% | 50.56 |
| 方向一致性候选 | 2.7966x | 19.25% | 1.399 | 11.20% | 108.91 |
| 候选双倍交易成本 | 2.4545x | 16.62% | 1.230 | 12.90% | 108.89 |
| 候选额外一根信号延迟 | 2.4171x | 16.31% | 1.223 | 13.78% | 109.11 |

候选TOP3 beta=`0.1220`、beta-residual CAGR=`10.91%`；分段相对Base CAGR差为2020-21 `+1.57pp`、
2022-23 `-9.97pp`、2024-26 `+6.09pp`。它降低全窗回撤`4.98pp`并通过双成本、延迟、beta residual、
2/3分段、gross、NAV对账和funding完整性，但全窗CAGR仍低于Base `0.63pp`，故仅`8/9`门通过并严格拒绝：
`reject_direction_consistency_continue_distinct_family_trials`。不调整20/60/120、投票或慢门救援。

**下一步**：Trial 146只测试预先冻结的连续多速度forecast；Trial 147才测试
`slow regime + medium position + fast de-risk`。并行先做残差横截面、危机状态、funding拥挤和流动性容量的G0，
OI/taker/order-flow只开始point-in-time前向采集，不伪造长历史。全部保持
`candidate_pnl_ready=false/promotion_evidence=false/orders_authorized=false`，未访问VPS、私有API、timer或订单。

**验证**：新增多速度与研究记录测试`11/11 OK`；全部`test_mini_trend_futures*.py`为`62/62 OK`；新模块、共享
UM执行器和runner的`compileall`通过；预登记CLI幂等复跑返回同一protocol/path；`git diff --check`和现行优先级/试验计数
一致性扫描通过。

## 2026-07-24 (Round 7)

### CTA-R selection-free 冻结成本重认证：历史edge保留，PIT/执行证据仍阻断

**目标**：修正R0 advancement的CTA-R口径，并判断历史CTA-R selection-free合同在当前ETF数据和更保守成本下是否仍值得推进。

**实现**：
- `src/qount/cta_eval.py`的grid/gate/walk-forward新增并传播`cost_per_side_pct`；`cta_sim` CLI的
  `--cost-per-side-pct`现在对gate和walk-forward真实生效，不再被静默忽略。
- `default_cta_r_etf_cost_model`场所从`us_etf_brokerage`修正为`cn_etf_brokerage`。
- 新增`scripts/research/run_cta_r_revalidation.py`：固定8 ETF、`63/126/252`多周期、long-only、gross<=1，
  读取压缩源并保存数据/代码/配置/成本/结果/GlobalExperimentRecord/CandidateRevalidationRecord的manifest-last bundle。
- 新增2条成本传播回归测试，并给ETF成本场所补断言。

**输入与成本**：
- 8标的共同窗口`2014-01-15..2026-07-22`、3037行；dataset hash=`2d6e7459...f7c8`。
- 压缩源和逐标的序列均有SHA-256；数据角色固定`consumed_historical_discovery_pool`。
- 冻结成本10bps/边=佣金3bps + 半价差2bps + 滑点5bps；压力为20bps/边。

**结果**：

| 口径 | 10bps/边 Sharpe | CAGR | maxDD | 折正 | 20bps/边 Sharpe | CAGR | maxDD | 折正 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| selection-free ensemble | 0.9197 | 8.65% | -8.23% | 5/5 | 0.8445 | 7.86% | -8.32% | 5/5 |
| past-only walk-forward | 0.7403 | 7.70% | -8.69% | 5/5 | 0.6984 | 7.22% | -8.73% | 4/5 |
| fixed a-priori | 0.8568 | 9.12% | -9.55% | 5/5 | 0.8238 | 8.73% | -9.55% | 5/5 |

固定单配置完整runtime另得effective breadth=`3.0844`、平均gross=`0.9904`、Sharpe=`0.8043`、CAGR=`9.36%`、
maxDD=`-10.50%`，独立NAV复算误差`1.78e-15`。它与selection-free fixed读数窗口不同：完整runtime在自身warmup后开始，
selection-free为公平比较12个配置而从所有cell共同warmup后开始。

**结论**：bundle=`9c08be9cdeb1a0c3d9416af9a4f7cb41eda4a17792decad24d5cee72b8725be1`，
verdict=`retain_for_discovery_revalidation`。候选仍为`candidate_pnl_ready=false/promotion_evidence=false/orders_authorized=false`；
历史PIT membership、QDII溢折价/跟踪误差、真实成本样本、额外延迟/漏单、类别/regime压力和新时间证据仍未闭合。
R0 advancement的CTA-R `1.56x`降为单规则探索读数，不再代表CTA-R主候选。当时排序曾改为CTA-R第一、C×D第二；
2026-07-25 owner随后用加密优先指令取代该排序，CTA-R证据冻结保留而非作废。

**验证**：
- `PYTHONPATH=src ./.venv/bin/python -m unittest -v tests.test_cta_eval tests.test_research_data_cost_nav` -> `90 OK`。
- bundle 6个成员与manifest hash已回读，目录/文件权限为`0700/0600`。
- 本轮未访问VPS、私有账户、timer、broker或订单路径。

## 2026-07-24 (Round 6)

### R0 深度验证：chronological folds + 成本敏感性 + beta residual stability + new-data review

**目标**：在修正后的 artifact 上完成四项深度验证，评估趋势候选的时间稳定性、成本鲁棒性和 alpha 一致性。

**新增**：`scripts/research/run_r0_validation.py` - 四项验证脚本，使用 `CandidateConfig.default()` (fast=20, slow=100, regime_sma=0)，生成 immutable validation artifact。

**验证结果**：

1. **Chronological folds (partial, 2/3 positive)**：
   - 2020-2021: NAV=**2.96x** maxDD=-43.7% annual=+71.9%（牛市强正）
   - 2022-2023: NAV=**1.41x** maxDD=-25.2% annual=+18.7%（温和正）
   - 2024-2026: NAV=**0.78x** maxDD=-39.5% annual=**-9.4%**（近期亏损）
   - **结论**：趋势策略的正 NAV 集中在 2020-2021 牛市，近期 2024-2026 段亏损。

2. **Cost sensitivity (all_positive=True, range [2.40, 6.11])**：
   - Funding 是主导成本因子：0.5x funding -> NAV 6.11x (+36.5%)，2x funding -> NAV 2.40x (-46.4%)
   - Taker fee 和 slippage 影响极小（5x taker 仅 -3.8%，5x slippage 仅 -1.9%）
   - **结论**：策略对执行成本鲁棒，但对 funding 成本高度敏感。

3. **Beta residual fold stability (partial, 11/23 positive alpha)**：
   - 滚动 365 天窗口，90 天步长，共 23 个窗口
   - Alpha 范围：-28.1% 到 +56.1%（年化），仅 48% 窗口为正
   - 正 alpha 集中在 2020-2021；2022-2024 多数窗口为负；2025-2026 混合
   - **结论**：alpha 不稳定，不能宣称持续正 alpha。

4. **New-data review (22 bars in 2026-07)**：
   - 2026-07 有 22 个日线 bars 可用（未消费）
   - 可用于 mini OOS 测试，但 7 月数据不完整（funding 缺失）

**总结论**：验证证据支持 "retain_for_discovery_revalidation" 的降级决定。趋势策略的正 NAV 主要来自 2020-2021 牛市，近期表现不佳（2024-2026 亏损）。Alpha 不稳定（48% 窗口为正）。策略对 funding 成本高度敏感。这些发现不改变 Base 生产、路由、paper 或 promotion 状态。

**Artifact**：`2ff84b3f783dbaf0cf231445a620ad0abdaf0f60f815979ff6d475f1db2b3037`（2 members），`orders_authorized=False`。

**不变约束**：`orders_authorized=false`，不改变 Base 生产、路由、paper 或 promotion。

## 2026-07-24 (Round 5)

### R0 治理记录 v6 + 文档同步：RETAIN 降级为 retain_for_discovery_revalidation

**问题**：v5 GlobalExperimentRecord 仍指向旧 `b90c6d...` runtime bundle（carry 0.76x），未绑定修正后的三个 bundle。`docs/current.md:19` 仍称"RETAIN 不再 provisional"。`docs/carry-active-basis-hypothesis.md:5` 仍以"0.76x rejected"为前提。`docs/research-advancement-roadmap.md:302-311` 仍引用旧数字和 bundle IDs。

**修复**：
- 新建 `scripts/research/update_r0_records_v6.py`：读取 Round 2 runtime (`7e827743...`)、Round 3 decision (`a26fba9a...`)、Round 4 advancement (`443a4ebb...`) bundle manifests，生成 v6 governance bundle。`GlobalExperimentRecord.result_artifact_hash` 指向新 runtime，`source_hashes` 含三个 bundle ID + `candidate_config_hash`。`CandidateRevalidationRecord.decision="revise"`，`execution_contract.candidate_pnl_ready=False`。manifest 增加 `r0_decision_bundle_id`/`r0_advancement_bundle_id`/`supersedes` 字段。
- `docs/current.md:19-43`：替换为 Round 1-4 修正后的完整状态。RETAIN 降级为 **retain_for_discovery_revalidation**。全部 bundle IDs 和数字更新。
- `docs/carry-active-basis-hypothesis.md:3-14`：更新前置条件为"REVISE（kill test 3 FAIL）"，carry Standalone NAV 1.38x（cost_incomplete=True）。旧 0.76x 作为历史记录保留。
- `docs/research-advancement-roadmap.md:302-311`：替换为 Round 1-4 修正后的数字和 bundle IDs。
- `docs/update-log.md`：追加 Round 5 记录。

**验证**：
- 本地全量测试通过。
- WSL 全量测试通过。
- v6 governance bundle 待生成（需跑 `update_r0_records_v6.py`）。

**与 v5 对比**：
| 指标 | v5 (47aa0e88...) | v6 (待生成) |
|---|---|---|
| result_artifact_hash | b90c6d... (旧, carry 0.76x) | 7e827743... (新, carry 1.38x) |
| candidate_pnl_ready | True | **False** |
| trend decision | (未记录) | REVISE |
| carry decision | (未记录) | REVISE |
| decision_bundle_id | (无) | a26fba9a... |
| advancement_bundle_id | (无) | 443a4ebb... |
| supersedes | (无) | 47aa0e88... |

**不变约束**：`orders_authorized=false`，不改变 Base 生产、路由、paper 或 promotion。

## 2026-07-24 (Round 4)

### R0 Advancement 日期对齐 + artifact 完整性

**问题**：① 三币等权组合按 `min(len(v))` 数组下标截取而非日期对齐（BTC/ETH 从 2020-01-01 起 2373 bars，BNB 从 2020-02-10 起 2333 bars，旧代码将 BTC 1 月数据与 BNB 2 月数据配对）；② advancement artifact `source_hashes` 仅含 `etf_zip`，无 crypto bars/funding/positions/NAV 哈希；③ CTA-R 1.46x 结果仅 console 输出，未保存为 immutable artifact；④ crypto TrendFollow 仍用 `args.*` 而非 `candidate_config.*`（Round 1 遗漏）。

**修复**：
- `run_r0_advancement.py` crypto 循环：① TrendFollow 改用 `candidate_config.*`（修复 Round 1 遗漏）；② 存储 `all_crypto_dates[symbol]`（从 `bars[i].date` 提取）；③ 每个 symbol 计算 `crypto_source_hashes`（closes/positions/nav/funding SHA-256）；④ `crypto_results[symbol]` 增加 `first_date`/`last_date`。
- 三币等权组合：从 `min(len(v))` 改为日期交集。用 `set.intersection(*date_sets)` 找公共日期，构建 `nav_by_date` 字典，仅在公共日期上计算等权 NAV。新增 `common_dates`/`first_date`/`last_date` 到结果。
- CTA-R 结果：`etf_results` 和 `cta_r_portfolio` 保存到 `bundle_core`；新增 `etf_results.json` 和 `cta_r_portfolio.json` 成员文件。
- `source_hashes` 增加 `crypto` 字段（per symbol: closes/positions/nav/funding hash）。

**验证**：
- 新增 `tests/test_r0_advancement_alignment.py`（7 条测试）：日期交集排除错位 bars、无交集产生空集、全交集保留全部 bars、旧 `min(len)` 方式错误验证、artifact 结构包含 etf_results/cta_r_portfolio/crypto source_hashes。
- 本地 200 测试 OK（148 research + 27 candidate + 25 r0/kill/alignment）。
- WSL 2091 测试 OK（1 pre-existing `jsonschema` 环境错误，1 skip）。
- 新 advancement bundle `443a4ebb64ce12d613bd4cb09ba15623a3eadff9974a81f4e2ad80450710d9d4`（6 members）：
  - BTC Standalone NAV=**4.4766**（与 runtime 一致，旧为 5.77x 因 regime_sma=200）
  - 3 币等权 NAV=**13.40x** maxDD=**-58.07%** annual=+50.08%（common_dates=2333, 2020-02-10 至 2026-06-30）
  - BTC beta-residual alpha=**+7.75%/yr** beta=0.47 R²=0.47（旧为 +13.48%/yr 因 regime_sma=200）
  - CTA-R 等权 NAV=**1.56x** maxDD=-10.28% annual=+7.26%（10 ETFs, 5 asset classes）
  - `source_hashes.crypto` 含 3 symbols × 4 hashes each
  - `etf_results` 含 10 ETFs
  - `cta_r_portfolio` 在 artifact 中
  - `orders_authorized=False`

**与旧 advancement 对比**：
| 指标 | 旧 (1221bf3f...) | 新 (443a4ebb...) | 变化原因 |
|---|---|---|---|
| BTC Standalone | 5.77x | 4.4766x | regime_sma 200->0 |
| 3币等权 NAV | 19.28x | 13.40x | 日期对齐 + regime_sma=0 |
| 3币等权 maxDD | -36.78% | -58.07% | 日期对齐暴露真实风险 |
| Beta alpha | +13.48%/yr | +7.75%/yr | regime_sma=0 |
| CTA-R NAV | 1.46x (console) | 1.56x (artifact) | 在 artifact 中 |
| Members | 3 | 6 | +etf_results +cta_r_portfolio +candidate_config |
| source_hashes | etf_zip only | +crypto per symbol | 完整证据链 |

**旧 bundle 处置**：`1221bf3f...`（旧 advancement，regime_sma=200，数组截取）保留为已消费 discovery artifact。

**不变约束**：`orders_authorized=false`，不改变 Base 生产、路由、paper 或 promotion。

## 2026-07-24 (Round 3)

### R0 Kill tests 真实化：独立 NAV 对账 + PIT data gap 检查

**问题**：`run_r0_decision.py:206-216` 中 kill test 2（`independent_nav_reconciliation_failure`）和 kill test 3（`point_in_time_data_gap`）均被硬编码为 `"pass": True`。kill test 2 不是独立实现的 NAV 对账，kill test 3 没有读取 R0-DATA gap/lifecycle/availability 证据。此外，decision 脚本验证了 trend baseline NAV 与 runtime bundle 匹配，但 **没有验证 carry baseline NAV**。

**修复**：
- 新增 `_independent_trend_nav(closes, positions, cost_model, funding_rates)`：独立 NAV 计算器，直接从 cost_model components 提取 rate，用简单循环计算 multiplicative NAV。不复用 `compute_standalone_nav`。
- 新增 `_independent_carry_nav(spot_closes, perp_closes, cost_model, funding_rates, weight)`：独立 carry NAV 计算器，使用 additive NAV（匹配 Round 2 新 carry 模型）。不复用 `compute_carry_standalone_nav`。
- 重写 `evaluate_kill_tests`：新增 `independent_nav`/`runtime_nav` 参数（kill test 2 比较两者，容差 ≤ 1e-6）；新增 `funding_missing_count`/`funding_incomplete`/`r0_data_available` 参数（kill test 3 检查 R0-DATA 可用性和 funding gap）。
- 修改 `main`：carry baseline 计算提前到 verification 之前；`input_verification` 增加 `carry_nav_match`（验证 carry baseline NAV 与 runtime bundle 匹配）；从 runtime bundle manifest 读取 `funding_aggregation.missing_count` 和 `incomplete`；检查 `state/research_governance/r0_data/` 目录是否存在。
- 两条腿的 `evaluate_kill_tests` 调用现在传入 `independent_nav`/`runtime_nav`/`funding_missing_count`/`funding_incomplete`/`r0_data_available`。

**验证**：
- 新增 `tests/test_r0_kill_tests.py`（16 条测试）：独立 trend/carry NAV 与主计算匹配、kill test 2 通过/失败/无数据场景、kill test 3 R0-DATA 不可用/funding gap/通过场景、decision retain/revise/reject 逻辑。
- 本地 193 测试 OK（148 research + 27 candidate + 18 r0/kill_tests）。
- WSL 2084 测试 OK（1 pre-existing `jsonschema` 环境错误，1 skip）。
- 新 decision bundle `a26fba9ae4d40048b88cb5836a0989a4b4339a5da9fe396fa9ce483d18b73b76`（5 members）：
  - `runtime_bundle_verified=True`（含 `carry_nav_match=True` 新增项）
  - 趋势腿 **REVISE**：kill test 1 PASS（所有 stress NAV > 1.0）、kill test 2 **PASS**（独立 NAV 4.4766 匹配 runtime 4.4766）、kill test 3 **FAIL**（R0-DATA 不可用）
  - carry 腿 **REVISE**：kill test 1 PASS、kill test 2 **PASS**（独立 NAV 1.3802 匹配 runtime 1.3802）、kill test 3 **FAIL**（R0-DATA 不可用）
  - `orders_authorized=False`

**与 Round 2 对比**：
| 指标 | Round 2 (旧 kill tests) | Round 3 (真实 kill tests) |
|---|---|---|
| Kill test 2 | 硬编码 PASS | **真实验证** PASS（独立 NAV 对账） |
| Kill test 3 | 硬编码 PASS | **FAIL**（R0-DATA 不可用） |
| Trend decision | RETAIN | **REVISE** |
| Carry decision | RETAIN | **REVISE** |
| carry_nav_match | 未检查 | **True**（新增验证） |

**正确解释**：RETAIN 降级为 REVISE 是正确的--R0-DATA bundle 不可用意味着 PIT membership 无法验证，候选晋级决定不能闭合。独立 NAV 对账通过证明 NAV 计算正确，但 PIT 数据完整性仍未验证。

**旧 bundle 处置**：Round 2 的 decision bundle（如有）保留为已消费 discovery artifact。

**不变约束**：`orders_authorized=false`，不改变 Base 生产、路由、paper 或 promotion。

## 2026-07-24 (Round 2)

### R0 Carry 账户模型重写：basis 收敛信号 + gross≤1 + additive NAV + cost_incomplete

**问题**：旧 carry 模型有 5 个缺陷：① gross 2x 未归一化（long 1x + short 1x）；② NAV 逐日复利相当于动态调仓但不收再平衡成本；③ collateral_cost/tail_cost 为 0.0 `"estimated"` 却得到 `cost_incomplete=False`；④ `basis_at_entry` 参数未参与计算；⑤ Signal NAV 计算的是 delta-neutral PnL（`spot_return - perp_return`）而非 basis 收敛信号。

**修复**：
- `src/qount/research_data/nav.py:compute_carry_signal_nav`：重定义为 basis 收敛信号。`basis_t = (perp_t - spot_t) / spot_t`，per-bar signal return = `basis_{t-1} - basis_t`（basis 缩窄 = 正收益）。`basis_at_entry` 改为可选（`None` 时从首 bar 自动计算），作为参考元数据存储，不影响 per-bar 计算。
- `src/qount/research_data/nav.py:compute_carry_standalone_nav`：① 新增 `weight=0.5` 参数（每腿 0.5x，gross = 2*weight = 1.0）；② NAV 改为加性（`nav += market_pnl - bar_cost`，非乘性），固定名义量不复合；③ 持仓成本按 `weight` 缩放（`_compute_holding_costs(-weight, ...)`）；④ turnover = `4*weight = 2.0`（非 4.0）。
- `src/qount/research_data/cost_model.py:default_cxd_carry_cost_model`：`collateral_cost` 和 `tail_cost` 的 source 从 `"estimated"` 改为 `"unavailable"`。`has_unavailable` 返回 `True` -> `cost_incomplete=True`。无需新属性。
- `scripts/research/run_r0_runtime.py`：`compute_carry_signal_nav` 调用不再传 `basis_at_entry=0.0`（改为自动计算）。

**验证**：
- 更新 `tests/test_research_data_cost_nav.py`：新增 4 条测试（basis_at_entry 自动计算、signal 跟踪 basis 非 delta-PnL、gross≤1 turnover=2.0、additive NAV 不复合、cost_incomplete 因 unavailable），更新 3 条（turnover 4.0->2.0、cost_incomplete False->True、standalone<signal 改为 standalone has costs）。
- 本地 177 测试 OK（148 research + 27 candidate + 2 r0_artifacts）。
- WSL 2068 测试 OK（1 pre-existing `jsonschema` 环境错误，1 skip）。
- `compileall` 通过。
- 新 runtime bundle `7e827743c98b861568aca71b166f14adc852499a58a962bf7e146514165d109d`（7 members，2020-01 至 2026-06）：
  trend Signal 8.46x / Standalone **4.48x**（maxDD -50.0%，cost 0.6369，cost_incomplete=False）；
  carry Signal **0.9997x** / Standalone **1.3802x**（cost -0.3849，cost_incomplete=**True**）。
  `candidate_pnl_ready=**False**`（carry cost_incomplete=True），`orders_authorized=False`，`config_hash=b23257abd7e7...`。

**与 Round 1 对比**：
| 指标 | Round 1 (旧 carry) | Round 2 (新 carry) | 变化原因 |
|---|---|---|---|
| Signal NAV | 0.9905x | 0.9997x | basis 收敛信号 ≠ delta-neutral PnL |
| Standalone NAV | 2.1432x | 1.3802x | gross 2x→1x + additive NAV |
| total_cost | -0.7698 | -0.3849 | weight 减半，funding 收入减半 |
| cost_incomplete | False | True | collateral/tail → "unavailable" |
| candidate_pnl_ready | True | False | carry cost_incomplete=True |

**正确解释**：carry Standalone NAV 1.38x 仍 > 1.0（主要来自 funding 收入 -0.3875），但 `cost_incomplete=True` 表明账户模型尚未完整（collateral/tail 未估算）。历史正 funding 可能存在可研究的风险溢价，但尚未证明 basis-carry 账户模型可执行。

**旧 bundle 处置**：`6a4e8f1a...`（Round 1 runtime，旧 carry 模型）保留为已消费 discovery artifact。

**不变约束**：`orders_authorized=false`，不改变 Base 生产、路由、paper 或 promotion。

## 2026-07-24 (Round 1)

### R0 CandidateConfig 统一：消除三脚本 regime_sma 漂移

**问题**：runtime (`regime_sma=0`)、decision (硬编码 fallback `regime_sma=200`)、advancement (默认 `regime_sma=200`) 研究的不是同一个趋势候选。advancement 的 beta-residual alpha (+13.48%/yr) 和 3 币等权 (19.28x) 属于 SMA200 版本，不能挂到 runtime/decision 保留的无 regime gate 版本上。三脚本无共享配置对象。

**修复**：
- 新建 `src/qount/research_data/candidate_config.py`：`CandidateConfig` frozen dataclass（`fast`, `slow`, `regime_sma`, `allow_short`），带 `config_hash`（canonical_hash over schema_version + 4 fields）。`create()` 验证 fast>0、slow>fast、regime_sma>=0；`from_dict()` 验证 hash 一致性；`default()` 返回 fast=20/slow=100/regime_sma=0/allow_short=False。
- `run_r0_runtime.py`：argparse 后创建 `CandidateConfig`，manifest `trend_config` 改为 `candidate_config.to_dict()`（含 `config_hash`），`trend_config.json` 成员文件同步更新。
- `run_r0_decision.py`：`--runtime-bundle` 改为 `required=True`；删除硬编码 `regime_sma: 200` fallback；从 runtime bundle manifest 读取 `trend_config`，用 `CandidateConfig.from_dict()` 解析并验证 `config_hash`；`input_verification` 增加 `config_hash_match`；bundle_core 和成员文件增加 `candidate_config`。
- `run_r0_advancement.py`：默认 `--regime-sma` 从 `200` 改为 `0`；新增 `--runtime-bundle` 可选参数，提供时从 bundle 继承 `CandidateConfig`；`TrendFollow` 创建改用 `candidate_config.*`；bundle_core 增加 `candidate_config` 和 `runtime_bundle_id`；新增 `candidate_config.json` 成员文件。

**验证**：
- 新增 `tests/test_candidate_config.py`（27 条测试）：create 验证、hash 稳定性/差异性、tamper 检测、序列化 round-trip、跨脚本一致性。
- 本地全量 173 测试 OK（27 新增 + 146 原有 R0/research）。
- WSL 2064 测试 OK（1 pre-existing `jsonschema` 环境错误，1 skip，与本次改动无关）。
- `compileall` 通过。
- 新 runtime bundle `6a4e8f1a8d9270b4f5793834231fe680cce6467932c8236c50bfb6bf6961a405`（7 members，2020-01 至 2026-06）：
  trend Signal 8.46x / Standalone 4.48x（maxDD -50.0%，cost 0.6369，cost_incomplete=False）；
  carry Signal 0.99x / Standalone 2.14x（cost -0.7698，cost_incomplete=False）。
  manifest `trend_config.config_hash=b23257abd7e7...`，`regime_sma=0`，`candidate_pnl_ready=True`，`orders_authorized=False`。
- decision dry-run 消费新 bundle：`config_hash_match=True`，`closes_hash_match=True`，`funding_hash_match=True`，`baseline_nav_match=True`，`runtime_bundle_verified=True`。BTC Standalone NAV=4.4766 与 runtime 一致。
- advancement dry-run 消费新 bundle：BTC Standalone NAV=4.4766 与 runtime 一致（之前 regime_sma=200 时为 5.77x）。三脚本现在消费同一 `config_hash`。

**旧 bundle 处置**：`acb1a8c1...`（Round 0 runtime，无 config_hash）保留为已消费 discovery artifact。新 bundle `6a4e8f1a...` 为 Round 1 产物，将在 Round 2（carry 模型重写）后被取代。

**不变约束**：`orders_authorized=false`，不改变 Base 生产、路由、paper 或 promotion。`QOUNT_LIVE_ENABLE=false`。

## 2026-07-24

### P0.5 funding settlement aggregation fix + provenance closure + vol-target window contract

审查发现 P0.5 阻断项：funding 仍按"每日一条最近费率"计入而非按真实 8h 结算逐笔累计。本轮修复了 funding 聚合、completeness 检测、
decision provenance 链和 vol-target 窗口契约。所有工作固定 `orders_authorized=false`，不改变 Base 生产或路由订单。

**P0.5-1 funding 结算聚合错误**（`scripts/research/run_r0_runtime.py`）：
- 旧 `align_funding_to_bars` 对每个 bar 取"最近一条 ≤ bar open"的费率，7,119 次原始结算仅累计约三分之一（0.2587 vs 0.7752）。
- 新增 `FundingAlignment` dataclass + `aggregate_funding_to_bars()`：对每个持有区间 `[bar_i.ts_ms, bar_{i+1}.ts_ms)` 求和全部 settlement rate。
- 复用 `grid/backtest.py:899` 的双指针扫描模式，自然解决毫秒偏移（2,394 个 bar open 中 1,091 个无精确匹配 settlement）。

**P0.5-2 funding 缺失 fail-closed**：
- 2026-07-01 至 07-21 共 21 个持有日无 funding settlement，旧逻辑静默前向填充 0.00003327。
- 新逻辑：区间内 0 笔结算且此前有过 settlement -> `incomplete=True`，记录到 `missing_intervals`；首日无数据不算 gap。
- `compute_standalone_nav` / `compute_carry_standalone_nav` 新增 `funding_incomplete: bool` 参数，OR 入 `cost_incomplete`。
- `candidate_pnl_ready` 现在受 `funding_incomplete` 阻断。

**P1 decision provenance 闭合**（`scripts/research/run_r0_decision.py`）：
- 新增 `--runtime-bundle` CLI 参数（原 docstring 提到但未实现）。
- 从 runtime bundle manifest 读取 `um_closes_hash` / `funding_raw_hash` / `trend_standalone_nav.final_nav`，
  重载 cache 数据后验证三者匹配，任一不匹配 fail-closed 拒绝生成 decision。
- Decision manifest 新增 `runtime_bundle_id` / `runtime_bundle_verified` / `input_verification` 字段。

**P1 advancement manifest-last artifact**（`scripts/research/run_r0_advancement.py`）：
- 新增 write-once artifact 输出到 `state/research_governance/r0_advancement/`。
- Manifest 绑定 `source_hashes`（ETF zip）、`universe`（crypto + ETF panel）、`holdout_role=discovery_pool`、`config`、`results`。
- 新增 `--output-dir` / `--dry-run` CLI 参数。

**P1 vol-target 窗口契约**（`scripts/research/run_r0_advancement.py`）：
- `range(lookback, len)` -> `range(lookback + 1, len)`，明确"lookback=20 = 20 个 completed returns"语义。
- 旧逻辑在 i=20 时仅用 19 个 returns；新逻辑在 i=21 时用 20 个 returns。

**Runtime manifest 扩展**：
- `data_hashes.json` 新增 `funding_raw_hash`（sorted [ts_ms, rate] pairs 的 SHA-256）、`funding_aggregation`（method/expected_per_day/
  total_settlements/missing_count/incomplete/settlement_counts/missing_intervals）。
- `manifest.json` 新增 `funding_raw_hash` / `funding_aggregation` 字段。

**回归测试**：新增 15 条测试（`TestFundingAggregation` 11 条 + `TestFundingCompletenessPropagation` 4 条），覆盖：
- 3 笔/日求和、1 笔/日、0 笔 gap 检测、首日 0 笔不算 gap、跨日边界、2ms/5ms 偏移、trailing incomplete、空 funding、sum 校验。
- funding_incomplete 传播到 NavResult.cost_incomplete、3x cost vs 1x cost 对比、carry 传播、deprecated alias 兼容。
- vol-target 测试更新为 lookback+1 语义（bar 21 而非 bar 20）。
- R0 标准库 136/136 OK（121 原有 + 15 新增）；compileall 通过。

**现有 bundle 处置**：`8d353...`（R0-RUNTIME）和 `1eede...`（R0-DECISION）保留为已消费的 discovery artifact（funding 聚合错误，数值无效），
不删除、不覆盖。修正后重跑将生成新 bundle。

**重跑结果（2026-07-24，完整 funding 窗口 2020-01 至 2026-06）**：在完整 funding 窗口上重跑了 R0-RUNTIME / R0-DECISION / R0-ADVANCEMENT，
全部通过 provenance 验证，**candidate_pnl_ready=true，cost_incomplete=false，missing_count=0**。

- **R0-RUNTIME** `acb1a8c1433732b3d4459d4117e1d92ea91025b9b7d635b30eacdaf2314acb38`（7 members，2373 bars）：
  趋势腿 Signal 8.46x / Standalone 4.48x（maxDD -50.0%，cost 0.6369，cost_incomplete=False）；
  carry 腿 Signal 0.99x / Standalone 2.14x（cost -0.7698，cost_incomplete=False）；
  **candidate_pnl_ready=true**（0 个缺失 funding 区间）。
  旧 bundle `8d353...` trend cost 0.2151 -> 新 0.6369（~3x，符合 3 笔/日 vs 1 笔/日的预期）；carry cost -0.2534 -> -0.7698（~3x funding income）。
- **R0-DECISION** `44bcf024ab0074930f65cd17351a5c91c6514c8bf07d44c01a60b0ee81be5b11`（4 members）：
  runtime_bundle_verified=True（closes_hash/funding_hash/baseline_nav 三项匹配）；
  趋势腿 RETAIN（cost_doubling 4.41x、delay 5.86x、10% 漏单 5.01x、5x 滑点 4.39x）；
  carry 腿 RETAIN（baseline 2.14x、5x 滑点 2.14x）；CTA-R BLOCKED。
- **R0-ADVANCEMENT** `1221bf3fdea551155ac2862345b984e080c427481642671e9903df5e8c5d762b`（3 members）：
  BTC beta-residual alpha=+13.48%/yr beta=0.41 R²=0.41；
  vol-target BTC maxDD -2.71%（lookback+1 语义）；3 币等权 NAV 19.28x maxDD -36.78%；
  CTA-R 等权 NAV 1.46x maxDD -8.72% 年化 +6.15%。
- **provisional 窗口 bundle（2026-07 窗口，保留备查）**：`0fe09d4c...`（runtime，incomplete=True）/ `9e89124a...`（decision）/ `7d5c6a7a...`（advancement）--
  因 7 月 21 天 funding gap 标记 provisional，不作为正式结论。
- **下一步**：R0-DATA WSL/外置盘只读 source-snapshot 审计；在完整 provenance 下复做 fold stability 和 candidate decision。
  所有结果仍只停留在 `research_sandbox`，不改变 Base 生产。

### P0 fixes: signed funding, rolling drawdown, causal vol-target + corrected rerun

修复了 2026-07-24 审计发现的三个 P0 bug，新增 11 条回归测试，并在修正后的代码上重跑了 R0-RUNTIME 和 R0-DECISION。
所有工作仍固定 `orders_authorized=false`，不改变 Base 生产或路由订单。

**P0-1 funding 符号修复**（`src/qount/research_data/nav.py:128`）：`_compute_holding_costs` 中 funding 成本从
`abs(position) * funding_rate * multiplier` 改为 `position * funding_rate * multiplier`。Binance UM 永续的 funding 约定是
正 funding 时多头付给空头；因此对空头仓位（position < 0），正 funding 是收入（负成本），不是支出。旧代码的 `abs()` 使空头
always 付出正 funding，导致 carry 腿 Standalone NAV 被低估。修复后 carry 腿 Standalone NAV 从 0.7628 (-23.72%) 变为
1.2796 (+27.96%)，funding cost_breakdown 从 +0.2586 变为 -0.2586（income），total_cost 从 +0.2638 变为 -0.2534。
carry 腿 kill test `standalone_nav_non_positive_after_tail` 从 FAIL 变为 PASS，决策从 REJECT 翻转为 RETAIN。

**P0-2 rolling drawdown 修复**（`src/qount/research_data/nav.py` 新增 `compute_max_drawdown()` 函数）：旧代码使用
`peak = max(series); max_dd = min((v - peak) / peak for v in series)`，即全样本最高点对所有点（包括峰值出现之前的点）
计算回撤。这会在 NAV 单调上升的系列中把起始点报告为 -90% 的"回撤"。新函数使用逐期 rolling high-watermark：
`peak_t = max(nav[0:t+1]); dd_t = (nav[t] - peak_t) / peak_t`。三个脚本（`run_r0_runtime.py` / `run_r0_decision.py` /
`run_r0_advancement.py`）的 `nav_summary` 函数和两处等权组合 maxDD 全部改用 `compute_max_drawdown()`。修复后趋势腿
Signal maxDD 从 -92.28% 变为 -50.91%、Standalone maxDD 从 -90.48% 变为 -53.17%；CTA-R 等权 maxDD 从 -35.64% 变为 -8.72%；
3 币等权 maxDD 从 -96.92% 变为 -34.89%。buy-hold maxDD 也被修正（BTC 从 -96.18% 变为 -76.67%）。

**P0-3 因果 vol-target 修复**（`scripts/research/run_r0_advancement.py` `vol_target_positions`）：旧代码在 bar `i` 使用
`range(i - lookback + 1, i + 1)` 计算已实现波动率，包含 `closes[i] / closes[i-1]`（当期收益），属于未来函数。新代码改为
`range(max(1, i - lookback), i)`，只使用 bar `i-1` 及之前的收益。同时修复了 `j=0` 时 `closes[j-1]` 回绕到列表末尾的 Python
索引 bug。修复后 vol-target maxDD 从 -10.04% 变为 -2.37%（BTC），-10.69% 变为 -2.14%（ETH），-11.49% 变为 -2.33%（BNB）。

**回归测试**：`tests/test_research_data_cost_nav.py` 新增 11 条测试：
- `TestFundingSignRegression`（4 条）：多头正 funding 为成本、空头正 funding 为收入、空头负 funding 为成本、carry funding 收入
  提升 NAV。
- `TestRollingDrawdownRegression`（5 条）：峰值前低点不计为回撤、单调上升零回撤、单次回撤、空序列、起始点不报告为回撤。
- `TestCausalVolTargetRegression`（2 条）：当期收益不参与 vol 估计、高波动期仓位被缩减。

**修正后重跑结果**：
- R0-RUNTIME bundle `8d35353a899fcb404168bf6a8abf0fe48bee7c22aaf16554de77142dbcf59b3c`（7 members，0700/0600 verified）：
  趋势腿 Signal 10.62x / Standalone 8.57x（maxDD -53.17%）；carry 腿 Signal 0.99x / Standalone 1.28x（maxDD -1.24%）。
- R0-DECISION bundle `1eede72a30e74a7b6cc453982b23d33b6ecfc8709bcf0a4758e48c176b3f09c8`（4 members）：
  趋势腿 RETAIN（成本翻倍 8.39x、延迟 8.93x、10% 漏单 7.35x、5x 滑点 8.33x，全部 NAV > 1.0）；
  carry 腿 RETAIN（baseline 1.28x、5x 滑点 1.28x，NAV > 1.0）；
  CTA-R BLOCKED（不变）。
- advancement 控制台输出：BTC beta-residual alpha=+18.66%/yr（不变，NAV 计算无 bug）；vol-target maxDD -2.37%（BTC）；
  3 币等权 NAV 26.47x maxDD -34.89%；CTA-R 等权 NAV 1.46x maxDD -8.72% 年化 +6.15%。

**P1 provenance（已撤回"不影响数值结论"措辞）**：`run_r0_decision.py` 原从缓存读数据而非消费并验证 runtime bundle manifest；
`run_r0_advancement.py` 原只打印控制台、未写 immutable artifact。**本轮已修复**：decision 新增 `--runtime-bundle` 参数并验证
closes/funding/baseline NAV hash；advancement 新增 write-once manifest-last artifact。但 P0.5 funding 聚合错误与此 provenance
缺口共同阻断了 `8d353...` / `1eede...` 的数值结论，此前"P1 不影响数值结论"的措辞已撤回。

**测试与同步**：R0 标准库 121/121 OK（110 原有 + 11 新回归）；全仓 2007 tests，12 pre-existing errors（numpy/websockets），
0 new failures。compileall 通过。Mac + WSL 双端同步。

### R0 evidence audit: preliminary route reopened before candidate conclusion

复核了 R0 初步数据、实现、artifact 和测试。`b90c6d1569d2fcc099f39af1252a128e610c96146b2a22d828bf87d13469592f` runtime bundle 与
`47aa0e88c70d3d2dabe3dad2422b875b4f7e16c5c7de2d6247dfe9f5d7089af7` v5 records bundle 均在 Mac 通过目录身份、manifest hash
和 member hash 校验；二者固定 `orders_authorized=false`，v5 也固定 `promotion_evidence=false`。R0-DATA bundle
`b9fa27ec6938e0dd7dc4fd880ebce4e517f685058a3e7504565362417e2d2422` 只由 v5 reference 指向，未保留在 Mac；需在 WSL/外置盘
执行只读 manifest/source snapshot 审计，不能把引用当作本机已验证副本。

审计发现三项会影响候选读数的阻断问题：

- `compute_carry_standalone_nav()` 对 spot long / perp short 的正 funding 使用绝对头寸计入成本；正 funding 对空头是收入，因此
  静态 carry 的 `0.7628448296480167`、`REJECT` 与由它派生的 active-basis 路由都必须降级为 provisional。
- runtime、decision 和 advancement 的 max drawdown 以全样本最高 NAV 为峰值，而不是逐期 rolling high-watermark；所有
  `~-90%`、vol-target `~-10%` 及 ETF `-35.6%` 回撤读数无效。advancement 的 volatility window 还包含当期回报，属于未来函数。
- `run_r0_decision.py` 重新从 cache 读数据而不是消费并验证 runtime bundle；`run_r0_advancement.py` 仅打印控制台输出，未保存
  input/source/code/config hash、参数、universe、holdout role 或 immutable result artifact。故 `RETAIN` / `REJECT` / `BLOCKED`、
  `+18.66%/yr`、`1.46x / +6.15%` 不构成可复核结论。

本机使用
`PYTHONPATH=src ./.venv/bin/python -B -m unittest -v tests.test_research_data_lifecycle tests.test_research_data_availability tests.test_research_data_universe tests.test_research_data_cost_nav`
复跑为 `110/110 OK`。现有测试未覆盖 signed funding、rolling drawdown、无未来 vol-target、runtime-to-decision provenance 或三线
artifact；先修复并补测，再在同一冻结输入上生成新的 manifest-last bundles。未访问 VPS、账户或订单接口，也未修改任何 live/paper 开关。

## 2026-07-23

### R0 initial five-step implementation + preliminary three-track exploration (superseded by 2026-07-24 audit)

实现并初步运行了 R0-DATA -> R0-COST/NAV -> R0-RUNTIME -> R0-RECORD -> R0-DECISION，以及趋势 beta-residual、
多币广度 + vol-target、CTA-R ETF exploration。全部固定 `orders_authorized=false`，不改变 Base 生产或路由订单。以下数字是
当日的 discovery 输出；2026-07-24 审计已发现 funding、drawdown 和 artifact/provenance 缺口，必须重跑后才可保留。

**R0-DATA（point-in-time 数据真相）**：新建 `src/qount/research_data/` 包（`lifecycle.py` / `availability.py` /
`universe.py`），从 Binance exchangeInfo（spot/um/cm）采集 `PointInTimeSymbolLifecycle` 并生成冻结
`PointInTimeUniverseRevision`。`scripts/research/build_r0_data.py` 编排脚本在 WSL 生成真实 bundle `b9fa27ec...`：
UM 846 symbols（721 active）、27 季度 revisions（2020-2026）、source hash + contamination role + write-once 0700/0600。
ETF 数据入库 `state/cta_r/etf_source/`（etf_data.zip SHA `3593d47048409c717cf64faeaa0522001518beb228a5ab74ad7cd08224077f3b`、
stocks.zip SHA `233f5f06c2ffbb3bdc5479d6883c8f8a767f8c13973e1cbea399825f8b7bd350`），含 1733 ETF 日线 + adj factor +
上市日期 + 基准指数信息，覆盖 A 股 / 海外股 / 债券 / 黄金 / 商品 5 类资产。

**R0-COST/NAV（冻结成本 + 三 NAV）**：`cost_model.py` 提供 4 种 `FrozenCostModel`（C×D trend: taker_fee + slippage +
funding 3 组件；C×D carry: taker/maker/spread/slippage/legging/collateral/tail/funding 8 组件；CTA-R ETF:
etf_fee/spread/slippage/tax/fx 5 组件；CTA-R futures: futures_fee/spread/slippage/roll 4 组件）。每个 `CostComponent`
带 `source` 标签（official_rate / estimated / certified_sample / unavailable）。`nav.py` 提供 `compute_signal_nav`（纯信号）、
`compute_standalone_nav`（信号 - 冻结成本）、`compute_carry_signal_nav` / `compute_carry_standalone_nav`（delta-neutral basis）。
110 个标准库单测通过；当时尚无测试覆盖空头 funding 的收入方向。

**R0-RUNTIME（初步 NAV 计算）**：`scripts/research/run_r0_runtime.py` 加载 BTCUSDT UM 日线 2395 bars + spot 2393 bars +
funding 7119 条。趋势腿（SMA 20/100 + regime 200 闸）Signal NAV 10.62x、Standalone NAV 8.57x（成本 0.2151 = taker 0.0136 +
slippage 0.0068 + funding 0.1947，cost_incomplete=False）。carry 腿（spot long + perp short delta-neutral）Signal NAV 0.99x、
Standalone NAV 0.76x（成本 0.2638，cost_incomplete=False）。Bundle `b90c6d1569d2fcc0...`，7 members，0700/0600 verified。carry
funding 符号和 max drawdown 后被审计判定需重算，不能用作最终候选结论。

**R0-RECORD（回填治理记录 v5）**：`scripts/research/update_r0_records_v5.py` 读取 R0-DATA + R0-RUNTIME bundle，用真实
dataset IDs、cost model hashes 和 NAV artifacts 回填 `GlobalExperimentRecord` / `CandidateRevalidationRecord`。v5 bundle
`47aa0e88c70d3d2d...`（11 members = 8 evidence + 2 candidate + 1 global experiment），`candidate_pnl_ready=True`（仅 C×D 初步成本完整、
NAV 已计算），`orders_authorized=False`，`promotion_evidence=False`。C×D candidate 现引用 R0-DATA bundle ID 和 R0-RUNTIME
bundle ID；CTA-R 仍为 partial（无 cross-asset runtime）。

**R0-DECISION（初步 retain/revise/reject）**：`scripts/research/run_r0_decision.py` 运行 4 种尾部压力测试并应用 3 个 kill test。
C×D 趋势腿 **RETAIN**：成本翻倍 NAV 8.39x、延迟 1 bar 8.93x、10% 漏单 7.35x、5x 滑点 8.33x——全部 NAV > 1.0，但 maxDD 持续
~-90% 需后续 beta-residual 审计。C×D carry 腿 **REJECT**：Standalone NAV 0.76x ≤ 1.0，kill test
`standalone_nav_non_positive_after_tail` FAIL；静态 delta-neutral carry 不 work，允许带 active basis-capture 的新版本。
CTA-R **BLOCKED**：无 runtime NAV，证据不足。Decision bundle `d382f8e931d7a3cb...`。该脚本未绑定 runtime bundle，且继承上述计算问题；
三个标签均为 provisional。

**三线推进（初步控制台输出）**：`scripts/research/run_r0_advancement.py` 同时运行三条研究线。
① 趋势 beta-residual：BTC trend vs BTC buy-hold 回归得 **alpha = +18.66%/yr、beta = 0.41、R² = 0.41**——趋势策略以 41% 的
方向暴露获得正 alpha，59% 方差是时机 alpha。BTC Standalone NAV 8.57x vs buy-hold 9.18x（绝对收益略低但风险暴露减半）。
② 多币广度 + vol-target：BTC/ETH/BNB 三币 Standalone NAV 均为正（8.57x / 15.23x / 29.32x）；vol-target 2% 年化把 maxDD 从
-90%+ 压到 -10%（BTC -10.0%、ETH -10.7%、BNB -11.5%），但收益也降到 ~1.10x；3 币等权 NAV 26.47x、maxDD -96.9%（需 vol-target）。
③ CTA-R selection-free：10 ETF 跨 5 类资产（A 股 / 海外股 / 债券 / 黄金 / 商品）等权组合 NAV **1.46x**、maxDD -35.6%、年化
**+6.15%**。黄金 ETF 最强（2.45x），海外股次之（标普 1.69x、纳指 1.66x），A 股趋势不 work（沪深300 0.85x、上证50 0.89x）。
该脚本未创建 immutable artifact，也未记录完整输入/参数/holdout role；所有数值须在审计修复后重跑，不能作为 CTA-R 或 C×D 的证据。

**Carry 新假设**：`docs/carry-active-basis-hypothesis.md` 提出 Active Basis-Capture State Machine。核心区别：不再静态持有
至到期，而是 funding MA 7d + basis z-score 条件触发建仓，basis 收缩 / funding 反转 / 时间止损 / adverse move 止损时平仓。
4 个 kill test 预登记（`standalone_nav_non_positive_after_tail` / `signal_nav_non_positive` /
`funding_signal_predictive_power_insufficient` / `turnover_too_high`），不复活旧静态版本。

**测试与同步**：R0 模块 110 个标准库单测（lifecycle 39 + availability 18 + universe 15 + cost/NAV 38）通过。此前记载的全仓
1996 tests、12 个环境错误、compileall 和 Mac/WSL 同步属于原执行报告；本次 Mac 审计只独立复跑了 110 个 R0 单测和本机 runtime/v5
manifest/member hash，未复跑全仓或访问 WSL。

新增文件：`src/qount/research_data/`（`__init__.py` / `lifecycle.py` / `availability.py` / `universe.py` / `cost_model.py` /
`nav.py`）、`scripts/research/build_r0_data.py` / `run_r0_runtime.py` / `update_r0_records_v5.py` / `run_r0_decision.py` /
`run_r0_advancement.py`、`tests/test_research_data_*.py`（4 文件）、`docs/carry-active-basis-hypothesis.md`。
新增 artifacts：`state/research_governance/r0_data/b9fa27ec...`（WSL）、`state/research_governance/r0_runtime/b90c6d15...`、
`state/research_governance/r0/47aa0e88...`（v5）、`state/research_governance/r0_decision/d382f8e9...`。

### 0.2.15 Base standard-production migration and natural-fill observer deployed

- owner 授权后将 Base 从兼容命名的 MiniTrend production entry 迁入标准 authority：`MarketSnapshot -> StrategyIntent -> allocator ->
  RiskDecision -> OrderPlan -> RuntimeLedger -> reconciliation -> ExecutionAttributionReport`。projection 与 venue dispatcher 现在只作
  input/adapter，任何订单前必须匹配标准 batch、plan、registry、pre-dispatch ledger/reconciliation 和 economic parity。
- 新增 `operations/base_production.py` state store（`prepare_base_standard_production_store` /
  `record_base_standard_production_cycle`）。每个正式 cycle 在 `state/mini_trend/standard-production/` 生成不可覆盖 release migration
  artifact（`0700/0600`、O_EXCL、fsync/readback、hash）并原子更新状态；真实自然 fill 才会把逐字段 attribution 与脱敏 raw exchange evidence
  固化为独立样本。store 在 live dispatch 前预检可写性，缺失或不可写不能取得执行路径。
- release commit=`a8d12ca29266b5c787176368b05a4a78b7eaf608`，version=`0.2.15`，source tree=`c6577f36...e15bb`，
  provenance=`80fb1c38...b745`。VPS 先停 timer 触发并备份 `0.2.14` 代码，再同步、安装、回读 provenance、更新 unit、order-free
  refresh、轮换 arm，最后恢复 timer；避免 rsync/安装窗口与 timer 重叠。
- VPS migration=`d3668938...d51b`、status=`37d49d70...b907`。正式验收 artifact=`3b4817f3...3a6a`：`completed`、0 market/0 STOP、
  `exchange_mutation_attempted=false`、standard parity=true、post reconciliation passed；账户`486.09421530 USDT`、TOP3/普通单/条件单均为0、
  HALT absent。首单状态`awaiting_natural_fill`、sample_count=0，不制造订单。
- `qount-mini-trend-live.timer` 与 `qount-phase-b-readonly.timer` 为`enabled/active`，forward timer保持`disabled/inactive`、cron为0；
  下一 live 触发为 2026-07-24 03:20 UTC 加最多10分钟随机延迟。Mac全仓`1911/1911 OK`，VPS生产链聚焦`71/71 OK`，真实 cycle 后 provenance
  再验证通过。

### Standard multi-sleeve virtual runtime and evidence-backed R0 readiness

- 新增标准本地链：`MarketSnapshot -> StrategyIntent[] -> allocator -> PortfolioTarget -> RiskDecision -> OrderPlan ->
  RuntimeLedger -> virtual execution -> three NAVs -> three-way reconciliation`。Risk对坏类型/非有限限额fail closed；OrderPlan按
  reduce-before-increase排序并执行step/min-qty/min-notional检查。virtual venue逐单记录`SUBMITTING/ACKNOWLEDGED/FILLED`、fill、fee和
  funding，不调用交易所。
- multi-sleeve bundle保留完整decision batch、ledger snapshot、audit rows、execution、sleeve NAV和result；manifest-last、目录`0700`、
  文件`0600`、不可覆盖、fsync/readback、嵌套hash、精确成员集和audit sequence/previous/row/final hash均验证。固定fixture artifact为
  `state/research_governance/runtime/d4faa121...48a80/`，result=`a98977dd...1672f`、snapshot=`f69bea0c...c3447`，
  `orders_authorized=false/orders_routed=false/promotion_evidence=false`。
- R0新增`ResearchEvidenceReadinessRecord`。实际family mapping绑定历史代码/文档hash；CxD/CTA-R的lifecycle、成本和NAV按字段记录
  `available/partial/unavailable + missing reason`。生成8份readiness、1份GlobalExperimentRecord和两个v4 candidate，不再使用
  `historical_evidence_pending_revalidation/current_data_pending/to_be_frozen`占位。最终bundle为
  `state/research_governance/r0/f5bfb3b5...6fa85/`、manifest=`05a303d4...c6bb3`；candidate PnL仍为not ready，架构fixture不冒充策略收益。
- MiniTrend Base dispatcher在自然market submit前捕获arrival book，保存独立submit/ACK/fill/protection时点、脱敏submit/order/trade原始证据，
  并在真实fill后构造逐字段`ExecutionAttributionReport`；order-book不支持时arrival字段unavailable但不阻断执行。当前信号仍全现金，未制造样本。
- 新增聚焦测试覆盖零/单/双sleeve、reduce-first、min-notional、账本/对账、经济重放、权限、manifest缺失、外层/ledger audit深层篡改、
  R0 bundle幂等/缺manifest/篡改及Base归因journal。架构边界/persistence/ledger聚焦`53/53 OK`，Mac全仓`1908/1908 OK`，
  compileall和`git diff --check`通过；全批未访问VPS、私有交易所、testnet，未创建arm、修改timer/registry/dispatcher权限或发送订单。

### Local research policy made non-blocking and R0 moved to research-ready

- Owner取消了日历、样本数量、阶段顺序、双sleeve和固定trial上限对本地推进的硬阻塞。生产资金安全不变量保持不变：
  真实账户mutation仍要求显式授权/arm，订单幂等、UNKNOWN/HALT、零仓位、对账、密钥隔离和风险预算没有放宽；本批未访问或部署VPS。
- Phase B progress升到schema v2：`30`改为`observation_target`，输出
  `policy_mode=non_blocking_observation`、`blocks_local_progress=false`、`blocks_research=false`、
  `blocks_allocator_development=false`和`authority_effect=none`。达到目标只写
  `milestones/phase_b_observation_target.json`，不再生成新的exit gate；schema v1 keyword仅作输入兼容。
- formal trial的`3`次硬上限改为review milestone。所有trial仍要求ID、family、预注册主指标/失败条件/敏感性范围和连续编号，
  但第4个及后续trial不再被代码拒绝；机器观测固定`blocks_additional_trials=false`。
- CxD和CTA-R CandidateRevalidationRecord更新为v3，均为`owner_authorized_research/active_research`，允许historical/discovery/
  shadow/virtual研究且`blocks_local_progress=false/trial_budget_blocks_research=false`；两者继续`orders_allowed=false`。
  artifact分别为`state/research_governance/r0/candidate-cxd-trend-carry-revalidation-v3.json`
  (`SHA-256 8d2f6d06...215769`)和`candidate-cta-r-cross-asset-revalidation-v3.json`
  (`SHA-256 a651eb8d...2d53a`)。
- allocator代码审计确认不存在双sleeve硬编码，并新增单research sleeve无需promotion即可allocatable的回归；零sleeve仍返回可解释的
  fail-closed blocker。registry审计确认`research`环境本来就不受promotion顺序限制，production status/owner/risk检查未改。
- 权威文档已统一把Phase视为并行workstream：证据缺失降低结论强度，不冻结family或virtual架构。本地现在具备开始R0/R1研究的
  contracts、trace、不可变artifact、point-in-time universe、三NAV scorecard、allocator、shadow accounting和governance底座。
  尚未完全闭合的是标准多sleeve runtime替代legacy dispatcher、真实多sleeve virtual integration artifact、R0真实
  family/lifecycle/cost/NAV数据和Base自然fill归因样本；这些是并行backlog，不是等待门。
- 验证：非阻塞/R0/allocator/registry/architecture聚焦回归`61/61 OK`，Mac全仓`1895/1895 OK`，compileall与
  `git diff --check`通过。测试仅使用本地fixture/fake client，无私有API、timer、arm、权限或订单变更。

### 0.2.14 Phase D/Phase B/R0 release deployed

- 收到 owner 对本批代码同步的授权，范围限定为 Phase D evidence store、逐字段 attribution、Phase B progress 和 R0 合同；
  不包含新订单、arm 轮换、timer 频率变化、dispatcher/registry/权限变化或重复真钱认证。
- 本地 release commit=`23355079fc0a196ab932d8085bc4b4deb8da94d3`，version=`0.2.14`，source tree=`a5a3f9c3...f387955`；
  已通过 `scripts/sync-to-vps.sh --install` 同步并在 VPS 完成 editable install。部署 provenance=`e3ad4d7d...1d0f9`。
- VPS production surface `343/343 OK`，本批新增认证/归因/Phase B/R0 聚焦测试 `80/80 OK`，compileall 与 provenance readback 通过。
- 部署前一次 live 周期曾因旧文件树 provenance mismatch fail closed，未进入订单路径；部署后 provenance 可验证。没有手工重跑 live 或
  Phase B，两个 timer 均继续 `enabled/active`，production cron 仍为零。
- 最新自然 Phase B archive 为 shadow diff=0、venue=pass、HALT=0、仓位全平，但 trades/income 均为 0 条；有效批次累计为 `3/30`，
  新的 machine progress artifact 从下一次自然周期开始生成。架构整体仍未完工：Phase B 30 日门、Base 自然成交证据、R0真实数据/NAV 和
  Phase E 两个独立 promotion sleeve 尚未满足。

### Phase D immutable evidence, partial attribution, Phase B exit state, and R0 contracts completed locally

- Added `CertificationArtifactStore`: publishes exactly 12 referenced member envelopes under
  `state/certification/runs/<run_id>/`, then self-hashed `bundle_metadata.json`, and writes
  `manifest.json` (`CertificationResult`) last. Directories are `0700`, files `0600`; writes are
  no-overwrite/fsync/readback verified. Tests cover missing members, interruption before manifest,
  member and metadata tamper, duplicate publish, sensitive keys, exact file set, and import boundaries.
- `TestnetVenueClient`/`RealVenueClient` now retain the raw ccxt submit/query/cancel response. Runner
  filters snapshot trades by this certification's client/exchange order IDs before primary/shadow
  reconstruction and cost attribution. Complete observed fees produce real commission/total;
  unqueried funding/transfer remain `unavailable`, never synthetic zero. Future real plans must bind
  actual preflight and venue-capability inputs; the arm is persisted `used` before first submit.
- `ExecutionAttributionReport` schema v2 supports per-field availability, missing reason, and source
  hash while keeping schema v1 readable/hash-compatible. `backfill-attribution` verifies a Phase B
  archive manifest and can recover fill VWAP, fee, maker/taker, quantity ratio, and evidenced funding;
  uncaptured mid/spread/latency fields remain `not_captured_at_event_time`.
- Phase B now writes immutable cycle/progress history plus a one-time exit artifact. It separates
  valid/failed batches, reports `valid_streak`, `required=30`, remaining cycles, latest watermark/diff/
  venue/HALT, cumulative real-trade coverage, and always publishes
  `orders_authorized=false/automatic_authority_change=false`. This code is local only; production
  remains `2/30`, timer cadence unchanged.
- R0 added hashed GlobalExperimentRecord/family mapping, point-in-time symbol lifecycle/universe,
  unified three-NAV/beta-residual/cost/trial scorecard, and CandidateRevalidationRecord contracts.
  The generated CxD record is blocked/virtual-only; CTA-R is planned/research-only. No allocator or
  order authority was connected to VPS.
- Verification: Mac full suite `1892/1892 OK`, architecture boundaries `14/14 OK`, compileall and
  `git diff --check` passed. A local Phase D dry-run published/read back a complete 12-member bundle
  with correct permissions. No VPS write/deploy, timer change, private exchange call, arm mint, or
  order occurred in this batch.
- Historical correction: the first real Phase D run persisted only the small summary. Its 12 payloads
  were built in memory, not stored as an immutable bundle. Existing real fill/fee/zero-position facts
  remain valid, but missing raw members cannot be recreated. Backfill must use the next natural read-only
  archive and leave event-time gaps unavailable; no repeat real certification is authorized.

### Phase D 真实最小认证首次执行成功

- owner 授权后在 VPS 执行首次 Phase D 真实最小认证（§9 Phase D）。BTCUSDT / `real_ack_fill` 语义，
  真实 MARKET buy 0.001 BTC -> MARKET sell 归零。`completed=True`、`final_position_is_zero=True`、
  CertificationResult 在内存中引用 12 个 artifact 成员、arm 已消费（`status=used`，不可复用）。当时只落盘摘要，
  未形成完整 12 成员不可变目录；这一限制以上一节为当前读法。生产状态 `0.2.13` 不变，Base 仍是唯一真钱策略。

- **执行流程**：commit Phase C/D 代码 -> `sync-to-vps.sh --install` 同步到 VPS -> VPS production 测试 343 OK
  + 认证测试 114 OK -> 只读账户快照确认 486.16 USDT / 全平 / one-way -> `make-plan`（owner 授权 hash）
  -> `make-arm`（0600，1h 失效）-> `run`（真实 buy/sell 归零）-> `mark_used` 消费 arm -> scorecard。
- **结果**（`state/certification/runs/20260723T072005Z_phase_d_real.json`）：
  - 真实 buy 0.001 BTC @ ~65394 USDT（cost 65.39，fee 0.0327 USDT）；
  - 真实 sell 0.001 BTC @ ~65394 USDT（cost 65.39，fee 0.0327 USDT）；
  - 买卖几乎持平（<5s 内市价单），净亏损 = fee = 0.0654 USDT；
  - 余额 486.15970914 -> 486.0942153（-0.0655 USDT = 认证成本，独立归档不进 Base PnL）；
  - 归零确认 active positions=[]；参数全在预算内（notional 65.4<120、fee 0.0654<1.0、holding <5s<120）。
- **纪律**：认证订单用独立 `cert-xxx` client_order_id，不影响 Base live（Base 权重 0/0/0 全平）；
  归零失败处置路径未触发；认证成本不进策略 PnL；§9 完成标准：artifact 完整 ≠ Base 扩容资格。
  未修改 timer/arm/registry/cron/live 开关；Base live timer 继续 0.2.13 行为。

### Phase D 真实认证工程基建就绪

- Phase D（§9 真实最小认证）工程基建已就绪：CertificationArm + RealVenueClient + `phase_d_real_run.py`。
  owner 已确认授权参数（BTCUSDT / real_ack_fill / 120 USDT / 1.0 USDT / 120s）。Mac 全仓 `1865/1865 OK`
  （+28 新测试）。生产状态 `0.2.13` 不变，未修改 timer/arm/registry/cron/live 开关，未下真单。

- **CertificationArm 合同**：`src/qount/certification/arm.py`。独立、单次（`mark_used` 返回 `status=used`
  新实例，不可逆）、带失效时间（`expires_at`）的 0600 arm，不复用 Base arm/token（§3.1）。
  `orders_authorized` 反映 `real_authorized` 状态；`is_valid_at(now)` 检查未过期；hash/id tamper 检测。
  20 条测试。
- **RealVenueClient**：`src/qount/certification/real_client.py`。继承 TestnetVenueClient（含 STOP_MARKET
  Algo 端点），连真实 Binance USD-M。`submit` 受 arm 门控（`CertificationArmNotAuthorized` fail-closed）；
  `query`/`cancel` 不受 arm 门控（归零/恢复必须可用，§5.3）。8 条测试。
- **phase_d 脚本入口**：`scripts/operations/phase_d_real_run.py`。子命令：`make-plan`（real_minimum plan，
  0600）、`make-arm`（0600 arm，单次带失效）、`dry-run`（LocalVenueGateway 离线验证）、`run`（真实 Binance
  下单，消费 arm）、`scorecard`。`run` 流程：加载 plan+arm -> 校验 arm 有效 -> build_exchange(private=True)
  -> MARKET buy -> MARKET sell 归零 -> generate_result（12 artifact + 双会计）-> mark_used 消费 arm。
  这是首次执行前的历史实现；当前本地版本已改为首个 submit 前消费 arm，失败不得重试，并要求真实 preflight/
  venue-capability 输入。arm 文件 0600 权限验证。
- `dry-run` 验证完整流程：completed=True、final_position_is_zero=True、12 artifact 成员。
- 新增文件：`arm.py`、`real_client.py`、`phase_d_real_run.py`、2 个测试文件。全仓 `1865/1865 OK`，
  现有 golden hash 不变，`orders_authorized=false` 在所有 certification 合同中恒定。
  未访问 VPS/私有 API/交易所/订单接口；未修改 timer/arm/registry/cron/live 开关。

### Phase C FAIL 修复与 Phase D 合同就绪

- Phase C §3.4 验收矩阵两个 FAIL 已本地修复，local gateway 4/4 PASS、GATE: PASS；Phase D 合同层就绪。
  Mac 全仓 `1837/1837 OK`（+10 新测试）。生产状态 `0.2.13` 不变，未修改 timer/arm/registry/cron/live 开关。

- **stop_algo 修复**：`src/qount/certification/testnet_client.py` 的 submit 检测 STOP_MARKET 的 Algo Order
  响应（`info.algoId`），记录 `is_algo`/`algo_id`/`client_algo_id`；query 切到 `fapiPrivateGetAlgoOrder`
  （by `clientAlgoId`）；cancel 切到 `fapiPrivateDeleteAlgoOrder`（by `algoId`）。正是 §14.5 发现的 Algo
  Order 服务能力矩阵差异。+4 条 mock 测试（TestnetVenueClientStopAlgoTest）；local-run + 真实 testnet stop_algo PASS。
  ccxt 的 `info.algoId` 提取路径在真实 testnet 上确认正确。
- **client_id_idempotency 修复**：`src/qount/certification/runner.py` 的 `submit_order` 在
  `client_order_id` 已在 `_known_order_ids` 时 fail-closed 抛 `duplicate_client_order_id_blocked`，
  不转发第二单。原 `_known_order_ids.add()` 只跟踪不阻止，testnet 不强制幂等时创建第二单。+3 条测试
  （DuplicateClientIdBlockedTest）；local-run client_id_idempotency PASS。
- **Phase D 合同就绪**：`contracts.py` 已支持 `real_minimum` 类型、`real_pending_owner`/`real_authorized`
  状态、6 个 `real_*` 语义、`real` 事件源；`orders_authorized` 由 `validate()` 强制 False。
  `phase_c_testnet_run.py` 新增 `real-plan` 子命令，生成 `real_minimum` draft plan 模板（占位 hash、
  `orders_authorized=false`、不下单），落 `state/certification/plans/<plan_id>.json`。+3 条 RealMinimumPlanTest。
- 修改文件：`runner.py`、`testnet_client.py`、`phase_c_testnet_run.py`、3 个测试文件。全仓 `1837/1837 OK`，
  现有 golden hash 不变，`orders_authorized=false` 恒定。未访问 VPS/私有 API/交易所/订单接口。

- **真实 testnet 重跑验证**（2026-07-23）：用 `~/.qount/testnet.env` 跑 `phase_c_testnet_run.py testnet-run`，
  Binance USD-M testnet（BTCUSDT, 0.002 BTC/笔）4/4 PASS、GATE: PASS：client_id_idempotency PASS
  （runner fail-closed 阻断重复 cid）、stop_algo PASS（Algo 端点 query/cancel 正确）、rounding_filter PASS、
  crash_recovery PASS。零仓位 YES、无替代单 YES、UNKNOWN 闭合 YES、全部 completed YES。Phase C 退出门
  （§9.1）满足，从 FAIL 2/4 变 PASS 4/4。artifact 落 `state/certification/runs/20260723T065108Z_testnet.json`。
  这是 testnet mutation（owner 已授权 testnet mutation），不是真实订单；生产状态 `0.2.13` 不变。
  Phase D 真实认证前置 C 已通过，但仍需独立 owner 授权，当前未授权。

### Phase C testnet 认证基建与首轮实测完成

- 按trading-system-evolution-plan.md §9 Phase C，owner已授权testnet mutation。建设"胶水"层把Phase A积木拼成端到端认证运行。
  新增2源文件(runner.py+testnet_client.py)+1脚本(phase_c_testnet_run.py)+2测试文件；Mac全仓`1827/1827 OK`（0 errors/failures/skips）。
  生产状态`0.2.13`不变，未修改timer/arm/registry/cron/live开关。testnet凭证存仓库外`~/.qount/testnet.env`(0600)，与生产key严格隔离。

- **CertificationRunner**：`src/qount/certification/runner.py`定义VenueAdapter Protocol（统一LocalVenueGateway+TestnetVenueClient），
  串联CertificationPlan->Run->Event->Result全链路。`generate_result()`组装§3.3的12个artifact成员+manifest，
  `completed`由"12成员齐全+3 proof hash合法+零仓位"计算。`submit_order`/`cancel_order`/`query_order`/`recover_from_crash`/
  `rest_snapshot_recover`记录CertificationEvent。shadow accountant从trades独立重建positions并与primary对账。18条测试。
- **TestnetVenueClient**：`src/qount/certification/testnet_client.py`实现VenueAdapter Protocol，用ccxt Binance连testnet。
  submit/cancel/query/snapshot/recover_from_crash；`orders_authorized`恒False；`_crashed`恒False（真实交易所不crash）。
  15条测试（mock ccxt，不需真实连接）。
- **Gateway §3.4补全**：`gateway.py`加SymbolRules(minQty/minNotional/stepSize/tickSize)+GatewayFilterError+`simulate_funding`fixture。
  submit()在有rules时校验rounding/filter；snapshot()含funding_payments。+10条测试。
- **Settings隔离**：`settings.py`加`testnet_enable/api_key/api_secret`，全部加入`PRODUCTION_CRITICAL_FIELDS`防ResearchSettings覆盖。
  `exchange_utils.py`加`build_testnet_exchange`（手动设testnet URL，不用ccxt已废弃的`set_sandbox_mode`；`fetchCurrencies:False`防超时）。4条测试。
- **脚本入口**：`scripts/operations/phase_c_testnet_run.py`支持`local-run`/`testnet-run`/`scorecard`三子命令。
  artifact落`state/certification/runs/<run_id>_*.json`；scorecard打印退出门状态。
- **Import boundary**：`runner.py`加入`CERTIFICATION_GATEWAY_MODULES`（禁止ccxt/exchange_utils/executor）；runner/contracts不import ccxt。

- **Testnet认证结果**（Binance USD-M testnet, BTCUSDT, 0.002 BTC/笔, 5000 USDT余额）：
  - **rounding_filter PASS**：MARKET订单正常接受、成交、归零。
  - **crash_recovery PASS**：query恢复无替代单，UNKNOWN闭合。
  - **client_id_idempotency FAIL**：testnet不强制`newClientOrderId`唯一性。直接API验证：同一client ID提交两次，返回不同exchange order ID（23491125564 vs 23491127040），两笔均成交。生产Binance预期行为不同。
  - **stop_algo FAIL**：STOP_MARKET走Algo Order服务（`POST /fapi/v1/algo/order`），返回`algoId`而非`orderId`。常规`/fapi/v1/order`查询/撤销不认识Algo订单（-2013/-2011）。Algo正确端点：query by `clientAlgoId`（✓）、cancel by `algoId`（✓）。正是§6预见的"STOP/Algo必须按Algo Service能力矩阵验证"。
  - GATE: FAIL（2/4），失败为真实testnet行为差异非代码bug。零仓位✓、无替代单✓、UNKNOWN闭合✓、全部completed✓。

### Phase A 架构演进合同与离线认证完成

- 按trading-system-evolution-plan.md §9 Phase A交付全部7项，完成标准满足：全部离线、`orders_authorized=false`、不需要VPS或私有API。
  新增4个独立顶层包、18个源文件(3375行)、7个测试文件(2031行)、161条新测试；Mac全仓`1722/1722 OK`，现有golden hash不变。
  生产状态`0.2.13`不变，未修改timer/arm/registry/cron/live开关。

- **WP-1 Certification合同**：`src/qount/certification/contracts.py`定义CertificationPlan/Run/Event/Result四个frozen dataclass，
  全部`orders_authorized=False`/`strategy_id=None`/`batch_type="venue_certification"`/`pnl_attribution="operational_certification_cost"`/
  `portfolio_nav="excluded"`；`completed`只在12个必需artifact成员齐全+零仓位证明时为True。注册到`persistence/codec.py`的
  `_TYPE_BY_CLASS`/`_payload`/`_decode_payload`。42条测试覆盖round-trip/tamper/duplicate-key/unknown-field/golden-hash。
- **WP-7 ExecutionAttributionReport**：`src/qount/certification/attribution.py`，无真实fill时所有数值字段=`"unavailable"`、
  `attribution_source="unavailable"`；`create_real_fill`拒绝字符串和回测常数。12条测试。
- **WP-2 HALT三层分类**：`src/qount/halt/`包含HaltEvent合同(operational/strategy/portfolio × venue/execution_plane/
  single_strategy_version/full_account)、`classify_from_halt_reason`映射8个现有HALT reason到三层分类、`classify_from_runtime_state`
  从UNKNOWN/对账/数据质量生成事件、bypass router读取HALT文件但不修改。恢复流程`validate_recovery_flow`验证UNKNOWN闭合→双会计diff→
  recovery report→owner auth→resume顺序。35条测试。
- **WP-3 VenueCapabilitySnapshot**：`src/qount/venue/`包含VenueCapabilitySnapshot(exchange_info_schema_hash/symbol_rules_hash/
  position_mode/margin_mode/leverage/compatibility=pass|review_required|blocked)和ChangelogDiff。`build_venue_capability_snapshot`
  纯函数从exchange_info dict构建快照，对比previous_snapshot检测schema/rules/changelog变化→review_required。21条测试。
- **WP-4 Shadow accountant**：`src/qount/shadow_accounting/`独立重建positions(long-only平均成本)、NAV(恒等式
  `equity=initial+realized+unrealized+funding-commission+transfer`)、cash events(unknown incomeType→HALT候选)、
  coverage window(缺口检测)、与主账本逐字段diff(pass/warn/block)。不导入`qount.execution`/`qount.mini_trend.pilot_dispatcher`/
  `qount.ledger.store`/`qount.ledger.reconciliation`。20条测试含golden rebuild。
- **WP-5 Gateway故障注入器**：`src/qount/certification/gateway.py`内存模拟交易所，`fault_injection.py`定义10种故障类型
  (ack_loss/rest_timeout/partial_fill/crash_at_submitting/crash_at_acknowledged/crash_at_partial/ws_reorder/ws_duplicate/
  ws_disconnect/duplicate_client_id)，`replay.py`崩溃恢复(查询不替代UNKNOWN、REST snapshot覆盖WS gap)。
  16条测试覆盖§3.4验收矩阵。
- **WP-6 Import boundary + Settings split**：`tests/test_architecture_boundaries.py`新增4组AST boundary测试(shadow_accounting/
  certification_gateway/venue/halt)，`src/qount/settings.py`新增`ResearchSettings`frozen dataclass、`PRODUCTION_CRITICAL_FIELDS`
  集合、`safe_research_replace()`函数阻止`dataclasses.replace`覆盖`live_enable`/`contract_leverage`/`binance_api_key`等生产字段。
  15条测试(4 boundary + 11 settings isolation)。
- Codec注册9个新artifact类型(certification_plan/run/event/result、halt_event、venue_capability_snapshot、venue_changelog_diff、
  execution_attribution_report)到现有`persistence/codec.py`的`_TYPE_BY_CLASS`/`_object_id`/`_payload`/`_decode_payload`，
  复用`_exact_fields`/`_verify_reconstruction`/`_strict_object` tamper检测。现有`test_immutable_contract_artifacts.py` golden hash
  `7bb07f55...2968`不变。
- 本批未访问VPS、私有API、交易所、订单接口；未修改timer、arm、registry、cron或live开关；未改变Base v0.2唯一真钱策略权限。

### 生产架构优化与研究情报路线冻结

- 新增`trading-system-evolution-plan.md`，把外部建议分流为独立execution certification lane、独立shadow accountant、
  三层HALT、venue capability provenance、生产import边界和多sleeve接入前置门。真实最小认证明确要求新的逐次owner授权；
  不为制造执行样本强制Base下单，不复用Base arm，不把认证成本计入策略PnL。
- 新增`research-advancement-roadmap.md`，定义GlobalExperimentRecord、LiteratureRecord、source trust、LLM旁路角色、
  每周论文/研报发现和多速度趋势/point-in-time universe/危机状态/ML元任务的条件路线。旧X4/C×D/RV-C/CTA-R只作
  legacy或consumed evidence，不改写为当前已认证edge；carry、short、杠杆和VRP仍未获授权。
- 根据owner后续edge储备分析，路线文档升级为`v0.3`：先重新认证C×D组合假设和CTA-R跨资产selection-free候选，再推进多速度趋势、
  maker/post-only执行经济学、风险预算和条件性VRP；新增ExecutionAttributionReport、T-D/T-F技术债、TWAP/VWAP容量门和候选组合
  重认证顺序；最终复核又补充`CandidateRevalidationRecord`、C×D/CTA-R最小退出门和架构Phase A-E依赖/回退矩阵。该优先级变化只更新
  研究/架构合同，不改变当前Base唯一真钱权限、carry/no-short约束或任何paper/live开关。
- 只读探测确认Binance USD-M changelog当前经HTTP 202重定向到英文页面，arXiv q-fin.TR RSS、Crossref、OpenAlex、
  Fed RSS和SEC RSS为HTTP 200；测试的NBER RSS返回403、BIS RSS路径返回404，因此路线不虚构这两条RSS，改用metadata发现后回到官方原文。
- 本批只改文档和导航，没有修改代码、VPS、timer、arm、registry、账户、订单或生产artifact。

## 2026-07-22

### 0.2.13 VPS部署、良心云funding补齐与冻结shadow启动

- VPS最终release为`0.2.13`、commit=`89be296014a9d826353c4b72d9d9487714b3c0f4`、source tree=
  `21ddfb09...3705`、provenance=`8141d31a...f205`。部署中修复`latest_date`字符串与`date`比较，以及live wrapper
  按历史completed状态错误刷新当前arm绑定两个实机问题。Mac全仓`1561/1561 OK`、VPS production`338/338 OK`；
  compileall、Bash syntax、`diff --check`与高置信凭据扫描通过。
- 最终run=`/root/qount/state/mini_trend/forward/runs/20260722T133356Z`，decision date=`2026-07-21`、TOP3权重
  `0/0/0`，readiness=`b25442fe...68fd`、authority batch=`092c95f9...a1f2`。受控live artifact SHA=
  `ae8cdc96...0900`、status=`completed`、0 market/0 stop、`exchange_mutation_attempted=false`，live与标准
  reconciliation均passed。余额`486.15970914 USDT`、全平、普通挂单0、one-way/isolated 1x、HALT absent、
  unresolved 0；live timer active、forward timer inactive、production cron 0。没有强制下单或扩大100 USDT本金。
- WSL良心云隔离代理首次因沿用2026-06到期测试副本而TLS unexpected EOF；从当前profile重新派生后保留47个真实节点、
  排除3个流量/到期伪节点，主Clash未改。仓库外代理env mode=`0600`，URL/token未进入repo、artifact或外置盘，
  未使用苏菲家宽代理。TCP、`example.com`与Binance funding公共接口均为200。
- 输入刷新`artifacts/experiments/20260722T141039Z-um-shadow-input-refresh-liangxin-current/`达到TOP3 `3/3`、
  各64次结算、108 files、0 unavailable；dataset/refresh experiment manifest hash分别为
  `b6f6aab8...ca05`/`ae878275...40b4`。冻结回放
  `artifacts/experiments/20260722T141236Z-um-funding-veto-shadow-forward-liangxin/`绑定原v0.2 preregistration、
  Base和state-decay，得到2个完整pair、verdict=`collect_shadow_forward`。两路径都是`bear_cash`、0 active、0 order、
  0收益、0回撤、0 veto、0状态分叉；只证明输入与journal闭环，不能声称盈利或晋级。shadow experiment manifest=
  `a3ed130c...7a53`，环境manifest/code bundle hash=`3c32811f...15a0`/`386b7bc3...48d3`，不含生产凭据；
  8个最终JSON经ext4 staging解析通过，scratch已清理。
- 正式日报`38985fe5...50d5fc`生成于部署前，5个proposal虽全部G0 blocked且禁止订单/live，但旧代码把3个零数量
  symbol槽位误写为“3个持仓”。`0.2.13`隔离、无通知复跑得到`position_count=0`、误报文本0条；pipeline complete、
  evidence sufficient、5个proposal仍全部blocked，`orders_allowed=false/live_changes_allowed=false`。临时审计目录已清理，
  正式archive、Dashboard、生产timer和arm未改。

### 0.2.13 本地实盘数据时点硬门与 LLM 复盘边界修复（部署前阶段）

- 只读复核发现VPS公开日线补数缺少`2026-07-21`的BTC/ETH/BNB三个ZIP；旧投影仍可从缓存生成`2026-07-20`决策。
  `0.2.13`在生产投影入口要求`expected_latest_date=UTC今天-1天`，缺失时返回`await_latest_completed_pilot_bar`；live dispatcher再独立检查
  `decision_date`和`decision_available_after`，即使有人手工构造新artifact也不能把旧日线送到交易所。
- `summarize_trading_history`把`position_count`改为非零数量计数，正负方向均计。当前VPS账本三行TOP3数量均为`0.0`，因此复盘应写活动仓位`0`，不再把跟踪行数误报为持仓数。
- Alpha Agent validator新增中文直接`下单/买入/卖出/开仓/加仓/减仓/平仓/做多/做空/杠杆/实盘/交易开关/目标权重/仓位`指令扫描；报告仍固定研究旁路，禁止订单、目标权重和风险override。
- 版本升至`0.2.13`；聚焦回归`37/37 OK`，加入availability正反边界后全仓`1558/1558 OK`，compileall、
  `git diff --check`、文档版本冲突扫描和密钥模式扫描通过。未同步VPS，未重启timer，未调用下单接口。
- 最新VPS日报`38985fe5...50d5fc`（hash=`d42c851d...9e68`）pipeline complete/evidence sufficient/status attention_required；7份官方来源和冻结账本已归档，5个研究提案全部`g0_status=blocked_history_capacity`，微信业务回执为`DELIVERED/SUCCEEDED`。它不能证明策略盈利或授权实盘改参。
- 初次只读检查确认唯一Ubuntu和`alyaloale`用户可用，但WSL代码目录已不存在且`/mnt/e`未挂载；重新连接后虽可读顶层，
  Windows仍报告`HealthStatus=Warning/OperationalStatus=Full Repair Needed`，存储查询会拖住WSL命令。该阶段精确终止挂起进程并
  fail closed，没有强行研究、下载数据或以Mac/VPS缓存替代canonical数据；随后在WSL ext4重建代码和独立`.venv`，关键源码hash匹配。
- Owner确认WSL无其它任务并授权恢复后，先关闭WSL，再把`E:\qount_data`备份到全新目录
  `D:\qount_data-recovery-20260722T120000Z`。`robocopy`返回码`1`，`FAILED=0`、`Mismatch=0`；源/目标均为
  `14,214 files/34,096,177,913 bytes`，逐文件SHA-256 manifest自身hash均为
  `a31da6afbf707dbc3201bc985780090b16f1db967cc554d303484deec56b9339`。`chkdsk E: /f`成功且报告`0 KB` bad sectors，
  卷最终`Healthy/OK`、dirty bit未设置。修复后全树再次逐文件读取，与修复前manifest相比missing/extra/content mismatch均为`0`；
  审计位于`D:\qount_data-recovery-20260722T120000Z.post-chkdsk-audit.json`，恢复备份不得删除。
- WSL重新挂载`/mnt/e`为可写`9p`，外置盘约`954G`、已用`34G`，ext4 scratch可用约`894G`，marker和`state`链接正常。
  Python `3.12.3`、NumPy `2.4.6`、scikit-learn `1.9.0`可用；可选LightGBM因缺`libgomp.so.1`不可导入，本轮冻结复跑不依赖它。
  storage topology、pilot projection/dispatcher、Daily Intelligence和Alpha Agents聚焦回归`40/40 OK`。这只恢复研究计算资格，
  没有部署`0.2.13`、重启VPS、调用私有API或改变订单/生产开关。

### WSL修复后冻结Funding Veto重放与beta residual补齐

- WSL专属输入/shadow回归`11/11 OK`、Funding Veto审计回归`20/20 OK`。公开Binance Vision TOP3日线从
  `2026-07-17`补到`2026-07-21`，archive unavailable=0；cache为`105 files/84,368 bytes`、content hash
  `30fab795588a33d27052886edba21bc36fb8321b13f6ef0a57b4621f3ea866da`。刷新artifact为
  `artifacts/experiments/20260722T123145Z-um-shadow-input-refresh-post-recovery/`。
- WSL直连`fapi.binance.com`及`fapi1..4`全部超时，`data-api.binance.vision/fapi/v1/fundingRate`返回404；当月
  funding完整symbol仍`0/3`。最新冻结回放
  `artifacts/experiments/20260722T123559Z-um-funding-veto-shadow-forward-post-recovery/`返回
  `last_common_date=2026-07-21`、`evaluation_bars=0`、`strategy_results_evaluated=false`、
  `await_complete_shadow_inputs`。未填0、未访问私有API、未借用VPS或LLM数据。
- Funding Veto主历史报告补入已存在的BTC 1x/TOP3等权1x beta residual，只增加只读指标，不改变策略、参数、
  收益或trial；新增回归后Mac/WSL相关测试`8/8`、`17/17 OK`。冻结历史复跑artifact
  `artifacts/experiments/20260722T124533Z-um-funding-veto-frozen-beta-residual-rerun/`保持
  `+88.9503928%/Sharpe 0.96523468/maxDD 18.10512106%`，交易成本`34.00361607 USDT`、funding PnL
  `-43.42373169 USDT`。TOP3等权1x beta/复合残差为`0.14702785/+55.41108512%`；剔除新增字段及非确定元数据后，
  新旧规范化SHA-256同为`d4bec779c2387668c1838169cfd2fe98398ff9a51c1396adc94201fd93e00d91`。
- 原预登记20日循环块、5000路径Bootstrap在
  `artifacts/experiments/20260722T124742Z-um-funding-veto-frozen-bootstrap-rerun/`逐字段重现：收益/Sharpe/更低
  maxDD胜率`58.90%/86.82%/75.72%`，收益/Sharpe/DD增量中位数
  `+0.46293455pp/+0.01910168/-0.22626954pp`；新旧规范化SHA-256同为
  `6c00d310eb3c66c6ea8564d6b193c2645a3e2179784212b3dabc6c36ebef1c81`。
- 新增dataset/refresh/shadow/beta/bootstrap五份manifest均从外置盘重算回读一致；环境锁
  `environments/wsl/20260722T124742Z-qount-funding-veto-frozen-rerun.json`的manifest/code bundle hash为
  `5054dc53...0a3d`/`afc51389...d1ae`。最终JSON stage到ext4后解析成功，marker保护scratch已清空。
  Mac全仓`1559/1559 OK`，compileall和`git diff --check`通过。全部仍为`consumed_historical_discovery_pool`、
  trial增量0；Base继续唯一真钱策略，Funding Veto继续shadow-only，VPS `0.2.12`和全部生产状态未改变。

### 0.2.12 live oneshot health self-check 修复与生产恢复

- `0.2.11`首轮真实live service揭示health probe的自检循环：`qount-mini-trend-live.service`在`Type=oneshot`执行期间为
  `ActiveState=activating`，但旧probe只接受`active/inactive/failed`，导致authority health `unavailable`、readiness
  `system_health_ready`失败。修复将`activating/deactivating`作为合法过渡态；明确要求`qount-mini-trend-forward.timer=inactive`
  的策略不变，并新增live通过/forward阻断回归。
- 版本`0.2.12`代码修复commit=`063b59d...9753a`，本地全仓`1553/1553 OK`，VPS production`335/335 OK`；同步后现场release
  provenance通过，未恢复旧X4/C×D、forward timer或production cron。
- 按owner授权归档旧arm并删除旧env token；新arm=`qmt-arm-9f10c9487f998bb6b586`，固定`100 USDT`，registry原子提升为`minimal_live`。
  私有只读preflight再次确认余额`486.15970914 USDT`、TOP3全平、普通/条件挂单0、one-way、isolated 1x、HALT absent、unresolved order 0。
- 最终order-free/live run=`/root/qount/state/mini_trend/forward/runs/20260722T102023Z`，readiness hash
  `f4dfbb8247abcfab09a421b86ed9329a9ae03608dc0c3f8640ce1c9c2edddca0`，authority batch=`65c8a64f...ba4750`，RuntimeLedger
  `efddab4c...02a3ee`，pre-dispatch reconciliation=`64fd12f...6934114`；readiness 0 blocker，system health四 scope全pass。
- 首轮受控live service最终为`success/0`和`duplicate_decision_noop`，决策权重`0/0/0`，0 market/0 stop、无`live_dispatch`、
  `exchange_mutation_attempted=false`；不得强制下单以制造fill/fee样本。随后开启`qount-mini-trend-live.timer=enabled/active`，
  `qount-mini-trend-forward.timer=disabled/inactive`。
- publisher最终原子publication成功；system窗口`180s`，RuntimeLedger类read model窗口`15min`，主read model均fresh。
  alert summary为open 1 WARNING（日报证据不足）、CRITICAL/HALT 0、dead-letter 0；该WARNING是研究提醒而非execution故障。

### 0.2.11 publisher CLI/config freshness default parity

- `0.2.10`生产发布证明system freshness已只绑定`ops_observer`，但实机read model仍显示120秒窗口；根因是publisher CLI
  参数默认值仍硬编码120，覆盖了`PublisherConfig`的180。
- 新增单一`DEFAULT_SYSTEM_STALE_AFTER_SECONDS=180`，配置对象和CLI均引用同一值；解析级回归锁定两者相等。
  这不改变RuntimeLedger 15分钟窗口、情报36小时窗口或告警5分钟窗口。

### 0.2.10 per-source freshness boundary correction

- `0.2.9`部署后，publisher、v2日报、通知与order-free authority均成功，但system read model仍把
  RuntimeLedger纳入Ops Observer的120秒阈值；账本在周期后约2分钟即令system模块显示stale，而overview/readiness仍按正确的
  15分钟窗口fresh，形成前端模块矛盾。
- system顶层freshness现在只描述Ops Observer；RuntimeLedger仍通过source hash和system payload展示，但其时效权威归
  overview/positions/orders/readiness的15分钟窗口。Ops Observer阈值从120秒改为180秒，覆盖两分钟timer和随机延迟。
  新增回归证明ledger可以stale而system仍fresh，反向也可独立stale；不通过放宽账户/执行数据窗口洗新。

### 0.2.9 legacy Daily Intelligence compatibility isolation

- `0.2.8` WAL修复后，publisher读到升级前的v1 `latest`日报时严格v2合同拒绝其缺失的
  `pipeline_status/evidence_status/evidence_summary`，此前会使整个publisher失败。该artifact来自升级前的已完成只读日报，
  不是账户、通知库或交易执行异常。
- publisher现在只将无效、损坏或旧schema日报降级为`unavailable_until_daily_intelligence`；Dashboard继续原子发布其它
  权威read model和其各自freshness。新增回归覆盖“存在但无效的latest”不得阻断发布。下一次有效v2日报仍会恢复正常
  intelligence模型；该降级不把旧报告重写为新证据，也不掩盖该来源的不可用状态。

### 0.2.8 publisher SQLite WAL sandbox repair

- `0.2.7`部署、通知库verified replay与无订单闭环后，publisher首次在`ProtectSystem=strict`和整个
  `/var/lib/qount/notifications`只读挂载下失败：`NotificationStore.verified_rows()`读取WAL数据库时SQLite无法打开
  `-wal/-shm`，报`sqlite3.OperationalError: unable to open database file`。这不是通知库损坏、账户异常或交易执行故障。
- 生产形态对照使用临时`0700/0600` WAL数据库复现：整个目录只读时读取失败；仅目录可写、
  `store.sqlite3`文件级只读时`NotificationStore(read_only=True)`成功，且应用仍强制SQLite`mode=ro`和
  `PRAGMA query_only`。canonical数据库SHA-256在实验前后不变。publisher timer已主动停为`disabled/inactive`，防止重复失败；
  Daily Intelligence保持运行，MiniTrend live继续停盘。
- `0.2.8`将publisher unit改为仅允许通知WAL sidecar目录写入，并将canonical数据库单独只读挂载；回归测试锁定两条
  systemd路径和应用层只读约束。该补丁不授予publisher通知写入、交易所网络、订单权限或任何live开关。

### 0.2.7 observability, readiness and intelligence architecture upgrade

- 维护窗口开始前只读确认USD-M钱包`486.15970914 USDT`、TOP3全平、普通挂单0、one-way和isolated 1x；随后
  `qount-mini-trend-live.timer`停为`disabled/inactive`，service为`inactive/success`。publisher和Daily Intelligence timer保持运行，
  回滚包为VPS root-only目录`/root/qount-maintenance-backup-20260722T072740Z`，新版恢复验证前不删除。
- NotificationSnapshot升级到v2：分离监控观测、内容变化与捕获时间；OPEN和历史严重度分开；空库为合法0事件；authority/live/
  publisher统一到`/var/lib/qount/notifications/store.sqlite3`，publisher保持只读；新增verified、idempotent legacy replay迁移，明确
  不重放delivery历史。Daily Intelligence incident使用supersession关闭旧故障，不把历史INFO保留为当前告警。
- Dashboard freshness按来源逐项计算，旧source不会被其它模块或重新发布的较新时间洗新。readiness新增publication integrity、
  observation state、operational state、trading authority、evidence state五轴；Ops Observer只读检查Caddy、publisher、日报、
  OpenClaw、live/forward timer、live service、HALT、manual arm和release provenance，并以影响域区分execution、observation、
  intelligence和delivery。通知/LLM故障不再错误阻断execution。
- Daily Intelligence升级为v2：官方feed按主题和45天窗口过滤，Binance JSON、Federal Reserve article和SEC press release正文使用
  专用抽取器；来源保存published/modified/observed、body hash、parser/extractor和content quality。交易历史区分
  `no_order_expected/orders_expected_but_missing/fills_verified`，pipeline与evidence状态分离，研究建议结构化为baseline、kill test、
  成本、holdout、source/history容量和G0状态。LLM仍固定research-only，不得改订单、仓位、风险或promotion。
- 静态控制台显示各模块和各来源的独立时间/到期状态、readiness五轴、OPEN/RESOLVED/outbox三类告警、Ops Observer以及事实/缺口/
  假设/研究建议分区；桌面和iPhone 13 Playwright验收无重叠、裁切或横向溢出。静态资源版本为v23。
- 本地组合回归`83/83`、全仓`1548/1548`通过；Python compileall、16份JSON Schema自检、`node --check`、shell `bash -n`、
  `git diff --check`和密钥模式扫描均通过。DailyBrief与Dashboard golden SHA-256分别更新为
  `4c80cea12ad9bdd9a6feb885809869b4a0b3dedcdd0f7a53762b8b3c6ed7845a`和
  `9872e15ba253df032f4f8600aa984da8b24380553f304012da38e4f3f7e78df5`。
- 本条只记录`0.2.7`发布候选，不预写VPS部署成功。恢复范围仍严格限定为`MiniTrend-UM-Base-v0.2`固定100 USDT、TOP3、
  long/cash、one-way、isolated 1x和gross<=1；RiskTier/FundingVeto只做shadow，不恢复forward timer、legacy cron、X4/CxD、
  line A、carry、short或其它sleeve。

### Source package version bumped to 0.2.6

- `pyproject.toml`从`0.2.5`升至`0.2.6`，作为下一次源码发布版本；当前VPS仍运行已验证的`0.2.5` release，未执行同步、部署或任何交易路径变更。
- 当时最新VPS只读核查为：live timer=`enabled/active`、forward timer=`disabled/inactive`、legacy cron有效项`0`、live service最近结果
  `success/0`、arm=`armed`、capital=`100 USDT`、HALT与未完成live lock为空；最新run仍为`20260722T061346Z`。
- 文档入口已清理为当前事实/架构/交接/项目规则加`docs/archive/README.md`索引；旧研究线文件保留为历史证据，不再出现在当前生产导航中。

### MiniTrend Base 100 USDT minimal-live enabled and recurring path closed

- Owner再次确认昨夜已批准的精确合同：`MiniTrend-UM-Base-v0.2`、固定`100 USDT`、Binance USD-M TOP3、
  long/cash、one-way、isolated 1x、effective gross `<=1`；RiskTier与FundingVeto只做shadow，不恢复X4/C×D/carry/多策略。
- 新增独立`qount-mini-trend-live.service/.timer`与`mini_trend_um_live_cycle.sh`。首次dispatch绑定arm原始readiness；
  后续周期强制先在全部live开关关闭的环境执行order-free refresh，再按decision ID幂等处理。arm/env要求非symlink、root `0600`；
  HALT、legacy live switch、unresolved live intent、权限或freshness异常全部fail closed。回滚脚本已覆盖新unit。
- `0.2.2`初版live架构本地`1538 OK`、VPS`324 OK`。真实arm暴露CLI对`forward/latest`调用`.resolve()`，导致
  `authority_source_selector_must_be_symlink`；`0.2.3`同时修复arm与post-dispatch authority调用点，并让authority refresh错误使
  service返回失败。本地`1540 OK`、VPS`326 OK`。
- 第二次arm暴露健康路径INFO事件使用“固定batch dedupe + 变化health source”的不可变身份冲突；`0.2.4`把dedupe绑定
  batch和health snapshot，旧事件由incident sync resolve、新事件open。本地`1541 OK`、VPS`327 OK`。
- 首次`0.2.4` arm/promotion成功，readiness=`0025c165...b57ef`，registry=`minimal_live`。首次live artifact
  `/root/qount/state/mini_trend/forward/runs/20260722T055437Z/live_dispatch-20260722T055659Z.json`，SHA-256
  `b13782b6f9d8a5a9d2093009cb8b71eebaca0aac9e40d320a5ec8b495b4db81a`。Base权重`0/0/0`，0 market/0 STOP、
  `exchange_mutation_attempted=false`；journal写入`live_intent_locked/live_completed`，最终chain
  `658d2f20...c1db`，post-dispatch reconciliation=`71c34b4d...0a01` passed，authority=`5b4433e1...f99a`。
- 手工演练后续周期又暴露已执行live decision会让dry plan阻断、forward writer返回75。timer立即disable，0订单、无HALT、
  无unresolved lock。`0.2.5`仅让`decision_already_executed`阻断live replay，dry仍走既有`duplicate_dry_noop`；本地
  `1542 OK`、VPS`328 OK`。最终部署commit=`e279b9664135a5936973afb4e92478d0714b95cf`、source tree=
  `42681594c8d77c9043d34e6d37ad5ca1a7c853b71e92868613e60672e008eb38`。
- code hash变化后authority正确回到`research`。旧`0.2.4` arm artifact以0600归档，旧live env token删除且不可恢复；
  新arm绑定`0.2.5` readiness。最终recurring run `/root/qount/state/mini_trend/forward/runs/20260722T061346Z`：
  readiness=`2d59b0716df9721370d025f90fce762186d71b7ddeffb8e92a0108b50bc49b26`、batch=
  `25924c5274d8f53c923ef2d7d2328bdf72deaa1d335b0515c7fbbc350debce38`、ledger=
  `dbac0f9141c89eeb4fdc50deb85e428e69c1210b1ce83665ed0657299e13c434`、pre-reconciliation=
  `dba39b3ce5b8eb43e2a96505d715fc6aacf6ad718be7bcdf87e2e0c1be79f2c7` passed。recurring service实际返回
  `duplicate_dry_noop -> authority written -> duplicate_decision_noop`且systemd success。
- 该阶段最终生产状态：`qount-mini-trend-live.timer=enabled/active`，forward timer=`disabled/inactive`，legacy cron有效项0，
  HALT不存在，arm/env root `0600`，registry=`minimal_live`；账户可用余额`486.15970914 USDT`，TOP3全平、普通/条件挂单0。
  当前尚无真实fill/fee/slippage/STOP/UNKNOWN恢复样本，禁止扩容、强制首单或开放其它sleeve。
- 当前事实面已同步更新README、current、quick handoff、系统架构、组合计划和项目规则；同日0.2.1/Phase B-C-D旧状态明确标为
  历史阶段。该docs-only变更不重新同步VPS，避免改变已验证的`0.2.5` release provenance和现有arm绑定。

### MiniTrend 100 USDT canary risk calibration and release gates

- Owner明确否决2%账户日损门，认为它对小额加密日线趋势试点过严。当前合同改为按冻结的100 USDT试点本金计算：
  单日损失5%（约5 USDT）或试点峰值累计回撤10%（约10 USDT）均在下一次日线dispatch执行flatten+halt；
  不改变Base v0.2的3xATR逐币吊灯、3根完成日线冷却和35% deadband。dispatcher不是盘中watchdog，盘中保护仍由
  Binance原生`STOP_MARKET closePosition`承担。paper和dispatcher测试覆盖5%日损与10%累计回撤可同时触发。
- live source freshness固定15分钟，覆盖preflight/projection/readiness/exchange rules/account snapshot；缺时间、过期或
  明显未来时间都在订单前失败关闭。每笔市价成交从确认的逐笔trade计算加权均价、fee和adverse slippage；超过25bps时
  已确认成交不会被伪装成失败，执行器继续保护止损和对账，然后写`halted_slippage`与HALT供后续扩容评估。
- 新增file-level release provenance：clean Git commit、项目版本、默认发布文件逐项SHA-256、source tree hash和manifest hash
  随rsync部署，VPS forward在私有预检、arm和订单前验证。readiness与manual-arm owner authorization hash同时绑定release证据。
  标准计划哈希适配器也补齐`execution_reference_prices/source_freshness/halt_reason`，避免0.2.1计划被旧字段集合错误拒绝。
- 首次0.2.1 VPS回归在297项后因Dashboard合同测试缺少`jsonschema`而导入失败，未执行forward。项目现显式声明
  `test` extra，受控VPS安装使用`.[test]`；这只补齐测试环境合同，不把可选研究依赖装入生产venv。
- Daily Intelligence报告`f4d90e84...dd63a94`只作为只读研究事实：TOP3同步上涨、正funding、Binance公告存在和内部账本
  对账通过不能建立事件因果或策略结论；`needs_research`结果不得进入Base信号、订单、live参数或风险豁免。
- 本条记录写入时仍未部署0.2.1、未生成manual arm、未发送真实订单。发布、order-free refresh和100 USDT canary结果必须在
  后续同日条目中按真实artifact/hash/订单/fee/slippage/保护单/HALT状态追加，不能预写成功。
- `9144e362...1c27b`已部署到VPS，release provenance验证为version=`0.2.1`、source tree=`70ee1078...60020`；首次验证发现
  旧rsync遗留5个已删除的CTA-R Dashboard文件，精确移至可恢复目录`/root/qount-stale-release.vRctSs`后manifest通过。
  目标forward unit已安装、daemon-reload和`systemd-analyze verify`通过（仅有无关cloudmonitor历史warning）；交易timer继续
  `disabled/inactive`、active cron为0。VPS production回归为`307 OK`。
- 明确授权的单次order-free `systemctl start --wait qount-mini-trend-forward.service`生成run
  `20260721T174354Z`。release/runtime/funding/preflight/account/authority/ledger/reconciliation硬门全部通过，最终readiness
  `ready_for_manual_final_arm`，hash=`8087c1d81fa5a58c7df40283ccb39a3520c0617e832e5c81f9b6feffe3e43fba`，authority batch=
  `98bd95b6...3d094`，ledger snapshot=`dc5b979c...b096f`，reconciliation=`03303187...1e74c` passed；账户可用余额
  `486.15970914 USDT`、TOP3全平、普通/条件挂单0，forward/active/paper/dry观察为`1/0/1/1`且funding完整。
- 该完成日线的冻结Base决策为TOP3权重`0/0/0`，投影和dry dispatcher均为0 market/0 STOP、
  `exchange_mutation_attempted=false`。因此不创建manual arm、不把registry提升为minimal_live，也不强制买入以伪造
  100 USDT实盘；timer、live switch、arm和HALT保持关闭。没有真实成交，所以fee、adverse slippage、原生STOP触发以及
  UNKNOWN/HALT恢复数据均仍未采集，扩容结论维持禁止。

### Dynamic OpenClaw context-token cutover and audited production verification

- 修复长期会话漂移风险：Qount凭据不再复制会被手机入站刷新的context token，只保留`account_id/base_url/recipient/token`四个稳定字段；
  `OpenClawWeixinProvider`新增动态accounts目录，在每次发送前读取`<account_id>.context-tokens.json`中的目标recipient。静态字段只保留为
  手工/测试回退，生产`/etc/qount/intelligence/openclaw-weixin.json`已原子删除`context_token`且继续为`0600 root:root`。
- 动态读取失败关闭：目录必须是无symlink的绝对目录、owner为当前用户且不可group/world writable；文件必须是无symlink的普通文件、同owner、
  精确`0600`且最多64KB；重复JSON key、无效recipient映射、缺少当前recipient或无效token均拒绝。日报CLI新增
  `--personal-weixin-context-token-directory`；systemd unit显式`Wants/After=openclaw-gateway.service`、增加accounts目录condition和只读挂载。
- 精确同步provider、日报runner、unit及两份测试到VPS，SHA-256为`65af6bf2...8780` / `0254618c...02c8` / `9280a8bf...1691`；
  安装unit经daemon-reload后正确依赖gateway。旧代码保存在`/root/qount-notify-backup.rl6QL6`，临时部署目录和短暂凭据回滚副本已清理，
  回滚目录不含secret。Mac通知/日报/Dashboard扩大回归`75 OK`，VPS部署聚焦`24 OK`，compileall和`git diff --check`通过；
  `systemd-analyze verify`只报告无关的cloudmonitor既有警告。
- 使用四字段凭据和动态目录，经生产NotificationStore发送“Qount 动态微信通知架构已上线”。事件`3b1a0dd9...0f43`、job
  `6d51a764...4324`一次完成为`DELIVERED/SUCCEEDED`，response hash为`77706ae2...4025`；全store现为5 event、5 job、5 attempt和
  20行完整audit chain。最终复核OpenClaw/日报/Dashboard均`enabled/active`，日报oneshot最近结果`success`，MiniTrend timer
  `disabled/inactive`、active cron 0、manual arm 0；站点匿名访问仍为Basic Auth `401`和`no-store`。未调用Binance私有API、未修改账户或订单、
  未启用live switch，也未发送任何真实订单。

### Personal Weixin handset-delivery diagnosis and truthful failure handling

- 手机未出现日报通知的根因不是Qount调用或交易路径：VPS上的`openclaw-gateway.service`当时为`disabled/inactive`，没有OpenClaw
  进程，微信客户端因而显示“暂无法连接 OpenClaw”。已将该服务设为`enabled/active`；它只绑定`127.0.0.1:18789`，腾讯微信通道探针为
  `running`，未开放公网端口、未改动任何交易timer、账户或订单。
- 历史`DELIVERED/SUCCEEDED`的语义纠正：旧`OpenClawWeixinProvider`只要HTTP为2xx就接受并丢弃body。使用当前凭据、官方host/header、
  官方client ID格式以及有/无旧context token的真实诊断均返回HTTP `200`、JSON `ret=-2`、`errmsg=prepare failed`，所以此前的本地
  状态不能被表述为腾讯业务接受、手机展示或已读。`src/qount/notifications/weixin.py`现要求有限大小的JSON object；非零`ret`、缺失或无效
  正整数`message_id`以及无效body均失败关闭，新增覆盖HTTP 200 + `ret=-2`与无效body的测试。
- 已按腾讯插件官方流程扫码重绑；腾讯返回“已连接过此 OpenClaw”，没有替换或泄露凭据。Owner随后从手机发送一条2字符测试消息，VPS在
  `2026-07-22T00:06:40+08:00`记录真实入站并刷新context-token文件；同一微信通道随后成功把一条OpenClaw错误提示回发到手机，证明下行展示可见。
  该错误不是微信传输失败，而是OpenClaw独立聊天模型仍指向无法DNS解析的旧`api.alyaloale.com`；旧key对当前relay返回403，未冒险混用日报key。
- 新context token已原子写回Qount仓库外凭据，文件保持`0600`且去除通用loader禁止的首尾空白。真实成功响应合同不是`ret=0`，而是仅含正整数
  `message_id`；provider现要求合法JSON、无非零`ret`且有正整数`message_id`，并将该真实ID写入`ProviderResponse`。最终中文
  “Qount 微信通知链路验证完成”请求得到19位`message_id`、`accepted=true/status=ACCEPTED`和response hash。Mac/VPS通知聚焦各13项通过，
  随后通过生产`NotificationStore`新建事件`cd078514d6c7...`，唯一job `9c6fca5efc6b...`为`DELIVERED`、attempt为`SUCCEEDED`、response hash存在，
  16行audit chain完整重放。compileall与`git diff --check`通过。每日timer保持启用，未触及Binance私有API、账户、订单、arm或交易timer。

### Free official-feed Daily Intelligence completed production E2E

- 放弃付费Brave依赖。真实预检中GDELT连续429、DuckDuckGo对Fed/SEC查询返回反自动化202；生产改用固定的Binance公告API、
  Federal Reserve RSS和SEC press release RSS。三类入口均稳定200，每个feed最多取3条，避免Binance独占详情名额；保存feed原始字节和
  SHA-256后，候选URL仍须通过HTTPS/官方域名allowlist、无代理、重定向复核、content-type/大小/XML实体限制并再次抓取正文。
  Brave adapter只保留兼容，production unit不需要搜索Key。
- 第一次完整oneshot报告ID`c326f31cc4dbd1799cf2f853bd15d3d966a98356fb74d513db1e44844dc0053f`、report hash
  `368f8756d2b11a680e6e8e6d63afb5602ceeda78f881cc6dff533be99ed88da8`、manifest hash
  `0534773ada0444cef564d86312e10c5f04d89368e8213b9b3a74d31d907f8f66`；3份feed、8份详情、2份行情、可用交易历史和个人微信通知均已归档，
  但8份最多12,000字符的正文让六角色在网络前触发`llm_input_too_large`。该不完整报告、原文、manifest和通知全部保留，未覆盖或删除。
- 修复官方正文恰在空格边界截断后留下尾空白、进而被`SourceEvidence`拒绝的问题；原文字节和hash不变。六角色改为按职责构造有界context：
  event每来源最多1,800字符，strategy/red-team/editor每来源最多600字符，red-team/editor只读取前序报告的受限summary/findings/proposals/
  risks；market主要读行情、execution主要读账本。全局`AlphaLLMConfig.max_input_chars=50_000`没有提高，8份真实形状来源的测试要求每个角色
  序列化context都小于35,000字符。
- 第二次production oneshot从`2026-07-21T15:11:03.900365+00:00`运行至`15:14:23`，报告ID
  `24defae63419d002a74ff07fd578c994b3b68f6eb200bd76b3a4fc6ca1fb6adc`、report hash
  `f4d90e84b1828345261568043623ba7b32ea5b66ede9fbe66d490f54ddd63a94`、manifest hash
  `295a9d117a241099f531aa799af8c8dc012a37a2effd775049bdc5aa3c11dbff`。再次保存3份feed、8份详情和2份行情；六个qount专用非流式
  Responses载荷约13.4-40.2KB，全部返回中文严格Schema报告，无`llm_input_too_large`、403、502、503或524。
- market/execution角色为`ok`；event/strategy/red-team/editor根据正文截断、发布时间不精确、目标资产行情和外部成交证据缺口诚实返回
  `needs_research`，所以总状态仍为`incomplete`。这是研究证据状态而不是E2E失败；不得把它改写为`clear`。报告固定
  `orders_allowed=false/live_changes_allowed=false`，readback已重放报告、manifest、source/search/market原文字节hash。
- 新日报个人微信job`57c0da6c51b01509dfab285398f8b5125fc928065be1f87df32ec5d4062dcd2a`为`DELIVERED`，首次attempt
  `9e63f07074cafee7ee7ae9adc886a51c61997cf1fc7d458f93a43dbc5987cc00`为`SUCCEEDED`，NotificationStore共12行canonical audit chain
  完整重放。Dashboard publisher随后把`intelligence.summary.status=available`发布到受Basic Auth保护的
  `https://qount.alyaloale.com/#/intelligence`，source hash精确等于上述report hash；publisher readback和备份恢复演练通过。
- `qount-daily-intelligence.timer`已设为`enabled/active`，每日`04:30 UTC`并带0-10分钟随机延迟。首次启用前创建当前persistent stamp，
  避免把同日手工oneshot当漏跑而重复通知；启用后service保持inactive，下一次指向未来日程。`qount-dashboard-publisher.timer`继续
  `enabled/active`，MiniTrend/其它交易timer、production cron、manual arm和全部live switch保持关闭。
- Mac与VPS官方源/日报/个人微信/通知/relay聚焦测试各`45 OK`，compileall和`git diff --check`通过。VPS上sub2api与
  aishenji-normalizer均healthy，account 25为`active/schedulable`；没有读取Binance私有API、修改账户/仓位/挂单、发送订单或赋予LLM交易权限。

## 2026-07-21

### Personal Weixin production notification delivered through Tencent iLink

- 新增`notifications/weixin.py`，复用VPS已安装的腾讯官方`@tencent-weixin/openclaw-weixin 2.4.4`账号合同，固定
  `ilinkai.weixin.qq.com/ilink/bot/sendmessage`、iLink鉴权头、版本编码、recipient/context token和中文纯文本payload；client ID由
  NotificationStore稳定delivery key派生。`deliver_due(channel=...)`只处理指定channel，避免个人微信transport误投递历史WeCom任务。
- 日报CLI新增个人微信enqueue/send/credential参数，拒绝同轮同时选择WeCom和个人微信；production unit改为要求仓库外
  `/etc/qount/intelligence/openclaw-weixin.json`并只发送个人微信。WeCom adapter保留为兼容代码，不再是production unit依赖。日报timer
  继续`disabled/inactive`，Brave凭据缺失时unit condition失败关闭。
- 从现有OpenClaw账号文件、主会话delivery route和对应context-token对象生成最小五字段凭据；全程未输出、提交或归档token、context token
  或recipient。新文件为`0600 root:root`，原先`0644`的context-token源文件同步收紧为`0600 root:root`。代码请求合同逐字段对照腾讯插件
  TypeScript源码确认。
- 首次投递在网络前因凭据JSON末尾换行被通用loader拒绝，fail-closed且任务保持`PENDING`、无网络请求；原子去掉末尾换行后重试同一任务，
  腾讯接口接受，job `DELIVERED`、attempt `SUCCEEDED`，NotificationStore 4行canonical audit chain完整重放。该消息是中文接入通知，服务端
  成功不等同客户端已读回执。
- Mac和VPS个人微信/通知/日报/WeCom聚焦测试各`20 OK`，compileall、`git diff --check`与`systemd-analyze verify`通过；后者只有无关
  cloudmonitor旧unit警告。没有调用LLM、Brave、Binance私有API，没有改账户、订单、arm、交易timer/cron/live；当前完整六角色日报唯一
  外部阻塞为Brave Search API Key。

### Daily Intelligence Responses recovered through the internal normalizer

- 旧New-API请求路径已经删除，当前链路为
  `qount-vps -> llm.alyaloale.com -> TokenRouter -> aishenji-normalizer -> aishenji.top`，其中normalizer仅在Docker内网可见。根因确认是
  aishenji Cloudflare WAF间歇误杀TokenRouter的Go HTTP/TLS请求特征，并非qount key、
  Responses、严格Schema、非流式协议、VPS资源或单一出口IP。normalizer使用nginx/OpenSSL重建TLS、SNI、Host和browser User-Agent；
  account 25的`credentials.base_url`已指向内网normalizer且`proxy_id=NULL`，不得再绑定proxy 6或恢复VPS直连。配置真相在relay-station的
  `deploy/aishenji-normalizer/nginx.conf`与`deploy/aishenji-normalizer.compose.yml`，TokenRouter未重启。
- qount-vps原API Key的真实非流式与流式`/v1/responses`均返回`completed/OK`。account 25为`active/schedulable`，TokenRouter和
  normalizer均healthy，修复后观测请求为HTTP 200且无新增403/502/503。通用Alpha Agent研究默认保持`gpt-5.6-terra`；日报unit和CLI
  独立显式使用`gpt-5.6-sol`，避免把日报模型选择误写成全局默认变更。
- `2026-07-21T13:23:23.472311+00:00`执行一次有实际研究用途的TOP3首角色请求：`store=false`、非流式、简体中文、严格JSON Schema、
  应用层重试关闭，约`26.5s`完成。pulse/ticker/premium原始证据hash为
  `e991a4a3ca181d764129415d72d26e56b13eb6db20fff3898ed64dfcfa87d04c` /
  `df89881fe27fe207a4c4d9a76ac5cbb85af0a4673a7adc15a5018658e87c3787` /
  `30a0ddfeb457dee77c84c6cc1401b229846e52bf3a758cccd2811f9c2765deee`。五字段、中文、越权语言和source hash校验均通过，报告固定
  `orders_allowed=false/live_changes_allowed=false`；这只是research-only单角色证据，不是策略、promotion或订单授权。
- 残余风险是两次长流式Codex请求分别约`125.7s/126.7s`后收到上游Cloudflare `524`，TokenRouter映射为502；两次随后均恢复200。
  WAF 403路径已经解决，但长请求超时仍要求有界退避、失败关闭和本地审计。日报客户端新增明确分类：仅对瞬时HTTP状态和错误体
  `retryable=true`最多重试一次，可从响应头或错误体读取并封顶`retry_after`；纯`owner_action_required`继续立即阻断。Brave与WeCom凭据
  文件仍缺失，因此没有运行六角色完整日报、没有enable日报timer、没有发送真实企业微信，也没有调用Binance私有API、创建arm、
  启用交易timer或订单路径。
- 日报默认模型改动已精确同步VPS：`run_daily_intelligence.py`新增`--llm-model`且默认sol，production service显式传
  `--llm-model gpt-5.6-sol`，测试同时锁定通用research默认仍为terra。本地与VPS聚焦`20 OK`，Python compileall、CLI help、
  `systemd-analyze verify`和`git diff --check`通过；补充上游波动分类后本地日报/relay/WeCom聚焦`21 OK`，日报timer继续
  `disabled/inactive`。

### Historical failed relay investigation before the normalizer (superseded above)

以下记录保留故障定位过程，不代表当前生产路径；其中New-API、标准池双account和Chat Completions描述已由上方Responses/normalizer事实覆盖。

- 将新增情报合同、11业务read model前端、15份schema、publisher空日报处理和未启用日报unit同步到VPS及域名served root。
  `qount-dashboard-publisher.timer`保持`enabled/active`；`qount-daily-intelligence.timer`与`qount-mini-trend-forward.timer`均为
  `disabled/inactive`，production cron仍为零active entry。当前release ID
  `14374b14f09c89b249b3a3ddeb2ec5288954aa6cfd8f4d8acc87d611a9391d16`包含11份业务read model和
  `publication.json`，情报authority明确为`unavailable_until_daily_intelligence`，未复制测试fixture。
- 生产`index.html/app.js/style.css` SHA-256为`86e2535b...d139` / `ddc51a8c...487b` / `3baaff67...8eb9`。
  通过只读SSH隧道对真实release执行Chromium桌面`1440x1000`和移动`390x844`验收，无可见重叠、裁切或横向溢出；匿名域名请求仍为
  Basic Auth `401`和`no-store`。临时本地隧道与VPS `127.0.0.1:8766` HTTP server随后均已关闭。
- relay-station token只写入VPS仓库外`/etc/qount/intelligence/relay-station.key`，权限`0600 root:root`；未回显、归档或提交。
  Brave和WeCom凭据文件仍缺失。模型目录无代理查询为200、16个模型且包含`gpt-5.6-terra`。此前两次请求返回502后，按退避合同于
  `2026-07-21T09:17:15Z`执行唯一一次真实中文TOP3市场分析：Binance公共行情成功，pulse hash
  `73bddd0104d6d1dd4e84e416980156b52dfaabe2323dc1a6714af844f09bd8e8`，ticker/premium原始字节hash为
  `b7dc27f...dece7` / `f9c36e2c...59a1`；Chat Completions仍返回Cloudflare `502`、`Retry-After: 60`和跟踪头。
  relay VPS只读日志确认生产Caddy直接反代TokenRouter `127.0.0.1:8080`，停用的`new-api.service`不是故障点。本次请求先命中
  Standard Pool account 25并自动切换26；两者都收到上游`403 Your request was blocked`，进入10分钟临时摘除后返回
  `no available OpenAI accounts supporting model`并映射为502。过去12小时terra `/v1/chat/completions`共3次且全部502；同期
  sol `/v1/responses`虽有成功，也存在大量502/503，不能把静态模型目录当健康证据。立即停止重试且不切模型或协议；这属于relay
  上游可用性阻断，不是中文五字段报告校验失败。
- 本地最终全仓`1508 OK`，新增修改聚焦`14/26 OK`；VPS生产聚焦`25/12 OK`。Python compileall、Node语法、15份Schema JSON、
  `systemd-analyze verify`和`git diff --check`通过。没有调用Binance私有API、修改账户、启用交易/日报timer、arm、发通知或下单。

### Read-only daily intelligence, review, Dashboard and WeCom plane

- 新增`src/qount/intelligence/`的`MarketPulse/SearchEvidence/SourceEvidence/DailyIntelligenceReport`合同和日报编排。Brave只负责URL
  discovery；候选URL必须再次通过官方allowlist抓取。Brave响应、Binance USD-M TOP3 `ticker/24hr`与`premiumIndex`响应、官方正文
  全部保存原始HTTP字节SHA-256，不再用解析后canonical JSON冒充网络响应hash。
- 从冻结`RuntimeLedgerSnapshot v3`确定性提取订单、逐笔fill、fee/funding、NAV、current/peak drawdown和reconciliation；修正初版
  摘要误读`filled_quantity/fee_amount/current_equity`等不存在字段的问题。六角色固定为market/event/execution/strategy/red-team/editor，
  后两者读取前序报告；报告嵌套对象、source map、角色顺序、只读authority和外层hash均可重放验证。
- `archive.py`使用`0700`目录、`0600`不可覆盖文件、manifest/hash和原子latest相对symlink，归档report及market/search/source原文；
  readback逐文件复核字节数/hash及报告引用。Dashboard新增第11份`intelligence`业务read model与独立freshness，release为12个JSON；新增
  `daily-intelligence-v1`和`dashboard-v1-intelligence`，总schema为15份，并扩展publication/envelope/alerts合同。
- 新增企业微信群机器人provider：严格固定`qyapi.weixin.qq.com/cgi-bin/webhook/send`、校验`errcode/errmsg`、复用NotificationStore
  delivery key、限流/超时和仓库外`0600`凭据。WeCom没有服务端幂等键，HTTP成功后本地落标前崩溃可能导致可见重复，不能宣称
  exactly-once。新增`qount-daily-intelligence.service/.timer`未启用模板，候选每日`04:30 UTC`运行；它允许公网但清空代理、移除全部
  Binance私钥，Brave/relay/WeCom各用独立凭据文件。
- Dashboard/情报/WeCom/账本聚焦回归当前`61 OK`，Dashboard ledger golden更新为
  `23076111ee2d578ef7b93ccee4a9bc7af78731a7693f0d8b1ebc45215536a7f9`。本批仍是`research_sandbox`：没有真实凭据，因此未执行
  Brave、relay LLM、WeCom消息或VPS/systemd部署；未改账户、订单、manual arm、live/timer/cron。全仓回归`1506 OK`，唯一warning
  为既有`cta_data.py` UTC deprecation；Node语法、15份Schema JSON、Python compileall和`git diff --check`通过。Chromium桌面
  `1440x1000`与移动`390x844`首屏及完整长页验收通过，文档宽度等于viewport，六角色和来源证据完整，无越界、重叠或裁切。

### Phase B/C/D VPS order-free deployment and final-arm readiness

- VPS部署前只读审计确认MiniTrend timer `disabled/inactive`、旧runtime inactive、root cron 0、全部live开关false、无arm/HALT，
  RuntimeLedger无`SUBMITTING/PARTIALLY_FILLED/UNKNOWN`；私有只读preflight与dispatcher snapshot确认可用余额
  `486.15970914 USDT`、one-way、TOP3 isolated 1x、全平、普通单和条件单均0。所有artifact仍固定100 USDT canary。
- 首次SSH直接cycle `/root/qount/state/mini_trend/forward/runs/20260721T063406Z`在dispatcher前失败关闭：旧
  `dispatcher.jsonl`的单行绑定旧contract hash，且非systemd调用缺`INVOCATION_ID`。没有创建dispatch row、authority、arm、HALT或
  交易所mutation。forward cycle现将dry journal写入`dry/contracts/<contract_hash>/dispatcher.jsonl`，旧证据不删除、不覆盖；新增
  回归证明不同live合同不会错误续链。
- 更新并reload `qount-mini-trend-forward.service`后，以`systemctl start --wait`手工运行oneshot，timer继续`disabled/inactive`。
  成功run `/root/qount/state/mini_trend/forward/runs/20260721T063854Z`通过independent runtime、账户preflight、projection、dry
  dispatcher、standard authority/RuntimeLedger/三方对账与最终readiness。dispatcher为`dry_validated`，0 market/stop intent、
  `exchange_mutation_attempted=false`；账户仍0仓位/0普通单/0条件单。
- 最终readiness verdict为`ready_for_manual_final_arm`、blocker 0、`live_orders_allowed=false`，hash
  `8496f70e49081e47a4fa3a610b86c8686a14c22c5d0cd0a94199fa0a97ad2a87`。authority batch/manifest为
  `70d1b38bd6769122b67634f46bd4cf6e2b28533f8bee86abf0b526e596ff0a49` /
  `1520b6afe616ddd9d7c35467c4477d054d1338bed9fe912580d0d1b2dd2e2ec3`；RuntimeLedger snapshot为
  `701848603d3ea41d8089e841072acec15826e6db27d70cb95cc84c23444575fb`；pre-dispatch reconciliation为
  `9971ca5f5b93ec324f8654f9998ecd17f558ea413f6cb254848924de58222d96`且passed。observations为
  forward pair/active/paper/dry=`0/0/0/1`，funding journal完整。
- registry仍为`research`且hash `e9de92af...c7bd`；manual arm为0，所有live switch、MiniTrend timer和旧cron保持关闭。
  `systemd-analyze verify`通过目标unit，仅报告无关cloudmonitor旧unit警告。VPS production/B-C-D/post-fix测试为
  `303/59/21 OK`；Mac全仓最终复跑`1497 OK`。首次全仓运行曾有1个历史derivatives并行fixture瞬时失败，单测与整套复跑均通过，
  未改动或放宽该校验。

### Phase B/C/D 本地执行链收口

- DailyBrief与legacy replay golden按规范生成器重建并绑定SHA-256；registry允许在batch之后由manual arm原子晋级，
  下一order-free batch在合同/code/config不变时延续已有`minimal_live`授权。对应晚registry与跨日继承已有明确测试。
- `1000 USDT`恢复为历史300 USDT research/paper及旧order-free证据兼容上界，但真钱canary在readiness、arm、live dispatcher
  和live journal四层均严格要求`100 USDT`；100.01会失败关闭。60/10/30/7观察值纳入readiness hash防篡改但不进入blocker。
- Binance短窗口cash ledger修复CCXT将金额绝对值化的问题：以原始有符号`income`为准，只处理funding、commission和transfer
  白名单；未知非零incomeType触发HALT，`REALIZED_PNL`不重复写cash ledger。
- 当时本地全仓`1496 OK`、B/C/D聚焦`39 OK`；compileall、Bash语法、DailyBrief golden
  `26c53f28...f382`、legacy replay golden `5b9bbbc0...15d2`及`git diff --check`通过。唯一输出为既存
  `cta_data.py` UTC deprecation warning；Mac无`systemd-analyze`。本轮仍未创建arm、未开启timer/live switch、未发真实订单。

## 2026-07-20

### Verified dashboard publishing activated with bounded backups

- 新的授权order-free周期`/root/qount/state/mini_trend/forward/runs/20260720T101653Z`通过账户flat、TOP3仓位/普通单/条件单均0、
  latest projection、dry dispatcher和`exchange_mutation_attempted=false`校验；authority writer生成batch
  `5a1c94a4280bb578c9ff1e8745cb309983f0f978096070819865c4b4024f4815`，authority/result hash为
  `d2648116252cc23235caa2bacf69e845d9190e343046466c4685609e79c8f34b` /
  `720c5c5f2336eab1edff4be40884143904bf15b04b8439d0d2a9761d0f2d2118`。最后一次授权账户观测为wallet/available
  `486.15970914 USDT`、gross/margin/仓位均0；publisher不会调用私有API刷新它，10:32:05 UTC后Dashboard按合同显示stale。
- VPS缺`systemd-timesyncd`的`OffsetUSec`接口，clock探针新增严格`chronyc -c tracking` CSV fallback；格式错误、非有限偏差、未知leap状态或
  `Not synchronised`全部失败关闭。authority/publisher unit只增加`/run/chrony`访问和`CAP_DAC_OVERRIDE`，继续
  `PrivateNetwork=true`、`AF_UNIX` only且无`CAP_NET_*`。把service allowlist移到`health_probes.py`后，VPS
  `python -W error -m qount.operations.dashboard_publisher --help`及实际周期均不再出现runpy warning。
- 审计发现publisher只裁剪release而备份snapshot无限增长；先执行`disable --now`保护停机，再新增备份保留合同。每轮在新backup逐文件验证、
  restore drill通过后，只删除完整验签、非latest且超出“latest+60个历史”的snapshot；损坏、非法名、异常类型和symlink只报告不删除。
  `PublisherResult`把retained/pruned/skipped backup IDs纳入result hash，systemd显式固定`--retain-previous-backups 60`。本地5轮测试以
  `retain_previous_backups=2`收敛到3份并证明latest保留，异常snapshot保持不动且被报告。
- Mac聚焦`29 OK`、全仓`1488 OK`，VPS production profile `299 OK`；compileall、`-W error` CLI、`git diff --check`和
  `systemd-analyze verify`通过，后者只报告无关cloudmonitor旧unit警告。publisher unit最终SHA-256为
  `f571cc52b386ffc3fd70a822a1270327a02896ed725feb09b0c40be463e3fd43`；authority/timer unit分别保持
  `bf9773e7d5509b21534996a14679a20847f4896ee9bf0cfd9fe4bfb3c7372f9e` /
  `6c807c26e55e6520de4ea8022b67753bb8503331c72a7a7dc4edf409a6f28bf8`。
- publisher timer恢复为`enabled/active`后，手工周期、Persistent触发和19:38 CST完整日历周期均成功且health=`healthy`、restore drill通过、
  无warning。19:38周期的publication/result/backup为
  `e4ff138bc0b22899fdac65f8e5eae8a993285959ca021c783bf2c10e4d2ad751` /
  `77f70e9958c519f97009824253575a864d01a333b19ae4e06fd7b9f8b6af5a07` /
  `8e3618b4e36c172c3d543022a83fd6c17c2fa34f018f67c952ef0f812b40b163`。路径审计记录为
  `ready_for_authorization`、`authority_bundle_verified=true`、`backup_state=verified_snapshot`，audit hash
  `0dcabe64e648b358f9a280806f23d6eb8d64a6c0df303a2799107d9c4c7bcf1f`。MiniTrend forward timer仍`disabled/inactive`，
  authority oneshot仍`static/inactive`，production cron零入口；没有调用私有API、改账户/订单、恢复live/manual arm或发送真实通知。

### Order-free authority writer and readiness lineage hold

- 新增`qount.operations.authority_writer`与`scripts/operations/write_authority_bundle.py`。writer只读选择的VPS forward run，拒绝
  symlink越界、非`0600`文件、重复JSON键、缺失/覆盖的dispatcher readiness、非order-free flags、projection/dry hash/parity错误、非flat
  账户和open orders；通过后才把标准`VerifiedDecisionBatch`、research`StrategyRegistry`、只读`RuntimeLedgerSnapshot`、
  `NotificationSnapshot`、四项OS`SystemHealthSnapshot`和`DailyBrief`写入staging并导入回读。它不查询交易所、不读取legacy DB、不发送真实
  通知、不生成订单授权；runtime冲突或发布异常保留旧authority目录。
- `scripts/desktop/mini_trend_um_forward_cycle.sh`修正source lineage：dispatcher第一次使用的readiness保存为
  `dispatch_readiness.json`，dispatch完成后最终readiness另存`live_readiness.json`，`dry_dispatch.source_hashes.readiness`不再指向会被覆盖的文件。
- 新增`deploy/systemd/qount-dashboard-authority.service`，`PrivateNetwork=true`、`ProtectSystem=strict`、清空proxy/live/arm/key环境、
  共享`/run/qount-dashboard/publisher.lock`，只允许oneshot手工/后续受控调度；`SuccessExitStatus=75`把source缺失表示为安全停点，unit未enable，
  SHA-256为`5f22cd1efc2124aff4d6f30f167f84479df9690397c8d5d88c8ecc983a8d0bff`。
- writer本地成功/失败关闭和unit边界聚焦`28 OK`，Mac全量`1484 OK`；authority unit已安装到VPS并保持`static/inactive`。真实运行选择
  `/root/qount/state/mini_trend/forward/runs/20260720T032512Z`，因缺`dispatch_readiness.json`返回`status=blocked`、
  `blocker=dispatch_readiness_source_missing`、退出码`75`，systemd result hash为
  `da4a6cca019529b8d68cf97fbe32f3fbfee4df605eecad041344e44824127819`。运行前后authority空目录hash均为
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`，runtime目录未创建。该旧run也只到`2026-07-18`且无completed
  decision，只读preflight另见`BTCUSDT`多仓`0.006`/`account_flat=false`；没有调用被停用的forward timer、私有API或账户/订单路径。

### Governed architecture baseline pushed and publisher installed disabled

- 审计并固定当前大工作区基线：Mac全仓`1478 OK`，Python compile、shell/Node语法、JSON/schema、凭据扫描和
  `git diff --check`通过；提交`230840c feat: establish governed quant architecture`已推送到`origin/crypto-lines-bcd`。
- `scripts/sync-to-vps.sh --install`已把该基线同步到`/root/qount`并重新editable install。VPS保持生产最小依赖；测试入口现默认运行
  production surface，authority writer接入后的最新结果为`295 OK`，显式`discover`才运行需numpy/websockets等可选依赖的研究/collector测试。
- owner明确授权publisher安装后，已创建`/var/lib/qount/dashboard-authority`、`/var/lib/qount/dashboard-backups`（`0700`）和
  `/var/www/qount/data`（`0755`），安装`qount-dashboard-publisher.service/.timer`并daemon-reload。unit hash分别为
  `dc8d854c34a7083c2bbb676a73db042021815198b8b2f6063131debf127932ef`和
  `6c807c26e55e6520de4ea8022b67753bb8503331c72a7a7dc4edf409a6f28bf8`；service/timer保持inactive，timer保持disabled。
- publisher path audit增加显式`--owner-authorized`记录：它只使`install_authorized=true`，完整source未通过时仍固定
  `enable_authorized=false`。writer实测后的最新VPS审计为`blocked`、`authority_bundle_verified=false`、`backup_state=prepared_empty`，hash
  `31a5de02b90920271a00f979c7a977f9c11a128e1d0977bfd363be4a81521458`。缺失项是标准batch/registry/ledger/notification/health/brief；
  没有复制fixture/legacy state，没有恢复旧cron、MiniTrend timer、订单、真实通知或live开关。

### Injected notification transport and publisher authorization hold

- 新增`notifications/transport.py`的严格`ProviderResponse`与`ProviderTransport`。provider response必须精确匹配schema、状态、
  acceptance、provider message ID、请求delivery key和canonical hash；错误回显、显式reject、provider exception和timeout均失败关闭。
  outbox重试继续复用原有稳定delivery key，fake provider对相同key返回相同message ID与`DUPLICATE`。
- transport使用注入的固定窗口rate limit、调用deadline和审计sink；credential只从显式私有文件读取，要求非symlink、父目录无
  group/world权限且文件精确`0600`。无key是显式本地fake模式并写`credential_present=false/value_omitted=true`审计；审计不含key，
  代码不查询env。仓库没有任何真实HTTP/webhook/provider adapter。
- 新增只读`operations/publisher_paths.py`和CLI，要求真实authority/backup绝对路径，检查全部symlink和`0700/0600`，复用
  `read_vps_authority_bundle()`及最新backup readback；输出hash化审计并固定install/enable为false、authorization为
  `pending_explicit_owner_authorization`。本地完整fixture与权限/symlink/相对路径故障均通过。
- VPS只读评审尝试失败：当前环境无法解析`qount-vps`且无`QOUNT_VPS_HOST`，未读取任何生产路径。静态审计只证明unit候选路径为
  `/var/lib/qount/dashboard-authority`与`/var/lib/qount/dashboard-backups`，同时确认仓库尚无生产authority bundle writer；因此没有把
  候选路径当真实source，也没有申请/执行publisher install或enable。
- `deploy/cron/qount-production.crontab`改为零active entry，原live/paper命令只保留`DISABLED`注释供授权后重新评审。通知/authority/
  cron/publisher/dashboard聚焦`48 OK`、全仓`1478 OK`，compileall和`git diff --check`通过；没有真实通知、cron/systemd timer、私有API、订单或live开关变更。

### VPS read-only path audit and timer safety hold

- 已从仓库外 SSH 配置恢复`qount-vps` alias，使用既有 root key 进入`/root/qount`；未把真实host/IP写入仓库。
- 只读核对发现 root crontab 只有 2026-07-11 的停用注释，`qount-dashboard-publisher.timer/service`和`qount-runner.timer/service`
  均未安装/未运行；`qount-mini-trend-forward.timer`原先为`enabled/active`，按本轮安全要求执行
  `systemctl disable --now qount-mini-trend-forward.timer`，复核为`disabled/inactive`。无qount交易/发布进程，`.env`为`0600`且
  `QOUNT_LIVE_ENABLE=false`。
- `/var/lib/qount`、`/var/lib/qount/dashboard-authority`、`/var/lib/qount/dashboard-backups`和`/var/www/qount/data`均缺失，远端
  `/root/qount`源码没有authority writer/source引用。未读取credential内容、未调用交易所或私有API。
- 将本地审计模块只读复制到VPS`/tmp/qount-path-audit`执行后立即清理；审计于`2026-07-20T08:57:21.938599+00:00`返回
  `status=blocked`、`authority_bundle_verified=false`、`backup_state=invalid`，hash为
  `fb66f3c3c8f45c90ed9429cca59e9b9b843c61e335ad5d179a37a2921c059c5f`。因为真实source/writer和backup snapshot都不存在，不能
  申请或执行production publisher install/enable；transport也没有获得第二份授权。远端真实通知、cron、timer、订单和live开关继续关闭。

### Production-shaped dashboard publisher and verified operations layer

- 新增`operations/health_probes.py`的真实只读探针：clock绑定`timedatectl`同步与OffsetUSec原始输出，disk绑定
  `shutil.disk_usage`，service只允许固定systemd unit allowlist，backup读取严格`0700/0600`、非symlink、canonical且hash完整的
  success marker/manifest。命令/容量/marker证据分别进入source ID/hash；无法观测clock/disk时明确输出`unavailable + null`，
  不用0偏差或0容量伪造健康。
- 新增`operations/backups.py`和`operations/dashboard_publisher.py`。publisher使用非阻塞`flock`，只读完整
  `VerifiedDecisionBatch/StrategyRegistry/RuntimeLedgerSnapshot/NotificationSnapshot/SystemHealthSnapshot/DailyBrief` authority bundle，
  用实时健康替换导入时的历史health source后重建十份read model，调用既有同目录原子publisher并做最终readback。
  每个成功release随后以11个精确文件、逐文件size/SHA-256、manifest/marker hash做私有备份，并在临时树恢复为`0644/0755`
  release后重放全部read-model/publication校验；只删除已完整验证、未被`v1`引用且超出“当前+最近N个”的release，非法目录保持不动。
- 新增未启用的`qount-dashboard-publisher.service/.timer`模板：`Type=oneshot`、`UMask=0077`、`PrivateNetwork=true`、
  `ProtectSystem=strict`、精确`ReadWritePaths`、清空proxy/live/arm/key环境和固定资源上限。没有安装/enable该模板，没有访问VPS、
  生产目录、交易所、私有API、订单或真实通知。
- 新增lock busy、发布失败旧指针、备份篡改、恢复演练、release保留、命令/磁盘不可用、架构禁止live依赖及systemd hardening测试；
  本批聚焦`34 OK`，全仓`1468 OK`，唯一warning仍为既有`cta_data.py` UTC deprecation。13份Draft 2020-12 schema和含
  unavailable health的11个release实例通过registry校验，Node语法、compileall和`git diff --check`通过。
- 前端补充clock/disk不可用中文显示，并在浏览器截图中发现/修复`390px`面板头短hash末位换行。Playwright 1.61.1 + Chromium 1217
  对`1440x1000`和`390x844`复核后，正文/导航/标题为`14/13/22px`（移动标题`20px`），文档宽度等于视口、无控制台错误、哈希单行。
  本会话Browser插件文件存在但未暴露其必需的Node REPL执行入口，因此按技能规定使用本机Playwright fallback，没有把fallback称为
  in-app Browser验收。QA入口为`http://127.0.0.1:64257/#/system`。

### VPS authority artifact importer and explicit health assembly

- 新增 `reporting/artifact_importer.py` 的只读 `read_vps_authority_bundle()`。它只接受完整
  `VerifiedDecisionBatch`、`StrategyRegistry`、`RuntimeLedgerSnapshot`、`NotificationSnapshot`、
  `SystemHealthSnapshot` 与 `DailyBrief`，严格限制目录/文件权限、symlink、canonical JSON、重复 key 和完整文件集合，
  并交叉验证 batch/manifest/plan、日报 source hashes 及 Dashboard builder 全链；legacy state、额外文件、内容/hash篡改
  均失败关闭。该 importer 不访问网络、交易所、SQLite、环境变量，也不写 release。
- 新增 `notifications/collector.py` 的 `collect_system_health()`，将 `clock/disk/service/backup` 四项显式 probe 结果
  组装为经 `SystemHealthSnapshot` 验证的快照；每项必须带 source identity/hash，具体 OS/systemd/backup 探针由后续单写者注入。
  `RuntimeLedgerSnapshot` 与 `NotificationSnapshot` 增加严格 `from_dict()` 回读，重放各自 hash/业务约束。
- 新增 `tests/test_authority_importer.py` 的完整导入、额外/篡改/权限拒绝和四项健康完整性测试；本批聚焦回归 `54 OK`，架构扫描、
  Node 语法和 `git diff --check`均通过。仍未接 production publisher、systemd timer、真实 notification transport、cron、
  订单或通知开关。

### Dashboard 中文显示与字号优化

- `web/site/index.html`导航、品牌说明、初始状态和无数据提示改为中文；`app.js`把路由标题、账户/回撤事实、订单、策略、风险、
  就绪、系统健康、告警、日报及固定证据链节点做展示层中文化。权威 `node.type`、reason code、策略 ID、hash、SQLite/JSONL 和
  RuntimeLedger 等审计术语不改写，避免翻译污染证据。
- `style.css`新增苹方、冬青黑体、微软雅黑、思源黑体 CJK fallback，统一正文/导航/标题/指标/表格字号为`14/13/20-22/18-21/12px`，
  中文 tertiary 文案不再低于`11px`；开启严格中文断行、抗锯齿和等宽数字，移动端保留两列指标并在`360px`以下继续收缩内边距。
- 本地完整 fixture 用 Playwright 1.60 + Chromium 1223复核桌面`1440x1000`、移动`390x844`六页、移动菜单稳定帧和仓位到决策追踪；
  无控制台异常、页面级横向溢出或重叠，最终菜单侧栏`transform=0`。离线页面仍显示中英双语`生产已停止 / PRODUCTION STOPPED`并失败关闭。
- 本批验证：聚焦`38 OK`，全仓`1455 OK`，`node --check`、13份Schema JSON和`git diff --check`通过；未创建生产fixture、未启用
  publisher/transport、未恢复cron或发送通知/订单。
- 新静态文件已通过 staging 哈希校验部署到`https://qount.alyaloale.com/#/live`：
  `index.html=062ccd08dc1818addfca4acdfcc3223adc0d4f29dc79cb94080d4c6a34afd3b6`、
  `app.js=c41c30e35b9bb716178b7e9b45fc994854ba38e3a97fb847faa365812e3b128`、
  `style.css=5e431878a72f984fbbb31a4c3534b8e65c24ba9e1ed8c72ddfa7f985d4ec1c45`；旧中文优化前目录保留在
  `/root/qount-dashboard-backup-cn-20260720T090000Z`，Caddy、Basic Auth、安全响应头和停机 cron 未改变。

### Phase B/C account facts, health, trace UI, and static production cutover

- `ledger/store.py`新增schema v2 `account_observations`，`RuntimeLedgerSnapshot`升级schema v3。账户观测绑定batch/time/quote/source/hash，
  exact replay幂等，内容冲突和时间倒退失败；snapshot在同一SQLite事务读取完整NAV历史与最新观测，输出wallet/available、actual
  gross、margin、peak equity和current/peak drawdown，并校验NAV连续性、账户/NAV同时间、余额关系和派生回撤。
- 新增`SystemComponentObservation/SystemHealthSnapshot`，固定`clock/disk/service/backup`四组件及强类型metrics、source/hash和独立
  freshness；backup age绑定观测时间。缺组件、component/snapshot篡改失败，service unavailable令system HALT。
- Dashboard扩展为`overview/positions/orders/strategies/decisions/risk/readiness/system/alerts/reports`十份read model。
  positions链接`#/decisions?trace=<id>`，decision chain固定覆盖batch/snapshot/intents/portfolio/risk/order plan/ledger/reconciliation；
  overview和DailyBrief展示账户与回撤事实。release为十模型加publication共11个JSON，`web/schemas`共13份。
- 完整health + DailyBrief组合的原子发布首次暴露`SystemHealthSnapshot.as_dict()` tuple经JSON落盘变list后的最终对象不等价；公开
  `as_dict()`已规范为JSON-native list，并将组合路径加入原子readback回归。12个实际model/publication/brief实例通过Draft 2020-12
  `jsonschema 4.25.1`验证。Dashboard/DailyBrief golden更新为`f2840c99a4403c1a50e39c497e4b6bd571dcc4442d4e77e635e53c5453b66c32`
  和`6ea5d7f0ca239382e672fe0b4ad9115d631f1e81548d2bda386d7f533a58e6f9`。
- 前端重写为运维控制台，默认/非法hash归一到`#/live`，只读取v1模型；Live显示balance/gross/margin/drawdown，Positions可点击
  trace，Decisions高亮证据节点，System显示四项健康，无release显示`PRODUCTION STOPPED`。Playwright 1.60 + Chromium 1223在
  `1440x1000`和`390x844`检查Live、Positions->Decisions、System、移动菜单和offline长页，无控制台异常、页面级横向溢出、重叠或裁切。
- 旧X4/C×D cron展示副作用已删除，部署模板不再调度`cxd_publish_cron.sh`，未来恢复策略cron也不会重建legacy web JSON；策略、
  订单和state写入逻辑未改变。架构测试禁止read side导入网络客户端、legacy Notifier、settings、exchange或executor。
- `https://qount.alyaloale.com/#/live`已切换新静态站。旧`/var/www/qount`完整移到
  `/root/qount-dashboard-backup-20260719T183341Z`，新served root只含三个`0644`静态文件且hash与本地QA一致；旧`data/`未部署。
  Caddy active，未认证401及Basic Auth/no-store/nosniff/DENY/no-referrer保留，qount cron仍停。没有production v1 release时认证后
  必须失败关闭；没有复制fixture、恢复cron、访问私有API、发送通知或订单。
- 真实transport评审要求新adapter保留outbox delivery key、provider response、限流/超时、0600凭据和无密钥审计；legacy
  `Notifier`/shell ServerChan不合格。当时production publisher评审仍缺VPS artifact importer、health collector、systemd单写者、同盘发布/
  保留/备份和恢复演练；该历史结论已由本文顶部的operations批次取代。两者均未启用。边界聚焦`71 OK`，全仓`1455 OK`，唯一warning为既有UTC deprecation。

### Phase B/C authoritative orders, risk, system, and incident lifecycle completed locally

- `RuntimeLedgerSnapshot`升级到schema v2。`ledger/read_model.py`在原有SQLite integrity、已发布audit outbox、canonical
  JSONL chain、同批最新NAV和最新reconciliation门内，用同一读事务冻结`position_details`、完整订单、订单事件、fills、
  cash events和recoveries；当前batch的plan hash与`VerifiedDecisionBatch`交叉验证。snapshot重建会校验ID/hash、时间顺序、
  累计数量、最新transition、fill/order关联、现金事件、仓位hash和recovery report，不能用计划订单补执行事实。
- `reporting/read_models.py`新增`orders/risk/system`。`orders`提供当前状态、累计/剩余量、成交计数/名义金额/费用、
  client/exchange ID、protective phase、UNKNOWN/拒单/部分成交和逐笔fill；`risk`提供RiskDecision、runtime gate、三方对账差异、
  NAV residual、现金事件合计和保护单状态；`system`提供snapshot/audit/reconciliation/recovery完整性以及
  `healthy/attention_required/halt_required`结论。order latency/slippage和无权威source的系统观测保持unavailable。
- 原子Dashboard release现在精确包含`overview/orders/strategies/risk/readiness/system/alerts/reports/publication`九个JSON；
  `web/site`新增订单、风险、系统三页，共八条路由。新增`dashboard-v1-orders/risk/system.schema.json`并扩展envelope/publication，
  `web/schemas`当前共11份Draft 2020-12 schema。浏览器仍不访问交易所、生产SQLite或重算PnL。
- DailyBrief订单段现在直接汇总runtime订单状态、fill数量/数量/名义金额/费用、保护单状态和最近恢复报告；订单段仅
  latency/slippage继续unavailable。`ProducerIncidentSync`、`synchronize_producer_incidents()`和
  `NotificationStore.resolve_superseded_alerts()`完成显式生命周期：先幂等enqueue当前事件，再在同source/category范围关闭不再
  active的旧OPEN incident；健康观察可产生零active和一组resolved IDs，sync ID/hash确定性可复核。仍未接scheduler和真实transport。
- 聚焦命令覆盖runtime ledger、legacy replay、ledger-Dashboard bridge、Dashboard read models、notifications、DailyBrief和
  notification producers七个测试模块，结果`60 OK`；全仓
  `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'`为`1448 OK`。`compileall`、Node语法、11份
  schema JSON解析及`git diff --check`通过，唯一warning仍是既有`src/qount/cta_data.py` UTC deprecation。
- Dashboard ledger、DailyBrief和notification producer golden SHA-256分别更新为
  `9fbae84fa1413ea10590c3c891e2c01fb900745a545afed5f4fe6111d1a9fda9`、
  `09ecfc088aec7ed7e40a41f3f0e85d39fa73851d8383817c2d47f4559744f17b`、
  `76a708e8fdcd0e3d85234b8f78c24cbeb036b171b536a6fc7d184fa97ae9d580`。
- 本地QA release为`http://127.0.0.1:8770/`，九个`/data/v1/*.json`均HTTP 200；fixture含3个订单、1个UNKNOWN、1笔fill、
  `risk gate=block`、`system=halt_required`和`DailyBrief=halt_required`。当前会话没有可用Browser/node_repl，因此没有为新增三页
  生成新桌面/移动截图；最后真实视觉证据仍是此前`8768`报告页验收，HTTP/DOM/JS/CSS验证不冒充视觉通过。
- 本批只使用临时SQLite、fixture和本地静态站点，没有访问VPS、生产publisher、凭据、私有API、交易所/订单接口、真实webhook、
  systemd/cron或live开关。这是`research_sandbox`架构证据，不是生产账户状态、通知送达、paper/live或下单授权。

### Phase C read-only alert producer adapters completed locally

- 新增`notifications/producers.py`，把完整`VerifiedDecisionBatch`、冻结`RuntimeLedgerSnapshot`和显式
  `SystemHealthObservation`分别映射为`AlertEvent`。decision adapter重放manifest、完整trace和artifact references；runtime
  adapter先执行snapshot/NAV/reconciliation/hash校验；system observation冻结component/status/time/detail/source/trace及自身
  ID/hash。三个adapter都是纯函数，不查询SQLite、交易所、网络、环境变量或当前时钟。
- 健康source不生成事件。映射覆盖incomplete data quality、portfolio allocation、risk decision、non-executable plan、recoverable/
  UNKNOWN order、three-way reconciliation、NAV residual以及system degraded/unavailable。recoverable order与HALT reconciliation
  固定为`HALT`；非HALT reconciliation、NAV/risk blocker和system unavailable为`CRITICAL`；allocation/plan/system degraded为
  `WARNING`。每个事件绑定精确source ID/hash和batch trace，不包含order authority。
- runtime order-recovery事件绑定`audit_last_hash`，而不是包含`captured_at`的snapshot hash；同一ledger source晚抓或重新发布时，
  alert/event/delivery identity保持完全一致，不能靠recapture制造新incident或洗新。真实source状态变化才产生新的immutable事件；
  旧incident的supersession/resolve仍需后续显式生命周期合同，当前不自动隐藏。
- producer事件已通过`NotificationStore -> NotificationSnapshot -> Dashboard alerts -> DailyBrief/reports`端到端测试：exact replay
  enqueue幂等，HALT order recovery在alerts页可见，并把DailyBrief提升为`halt_required`及
  `resolve_recoverable_order_states/review_open_halt_alerts`两个owner actions。新QA release为
  `http://127.0.0.1:8769/#/alerts`；六份release JSON均可读，前端代码未变，视觉响应式结果沿用上一批已完成的Chromium验收。
- 新增`tests/test_notification_producers.py`的11项健康/分级/篡改/recapture/幂等/端到端/golden测试，并把producer纳入禁止
  exchange/settings依赖的架构扫描。Phase B/C聚焦`101 OK`、全仓`1446 OK`，唯一warning仍为既有`cta_data.py` UTC
  deprecation。`tests/fixtures/notification_producers_v1_golden.json` SHA-256为
  `76a708e8fdcd0e3d85234b8f78c24cbeb036b171b536a6fc7d184fa97ae9d580`。
- 本批只创建临时ledger/notification store和本地静态QA release；没有接scheduler、自动incident resolve、真实transport或
  production publisher，没有访问/部署VPS、生产artifact、私有API、交易所/订单接口，也没有修改凭据、systemd/cron/live开关。
  它是`research_sandbox`本地架构证据，不是production通知送达、账户状态或订单授权。

### Phase B/C deterministic DailyBrief and Dashboard reports completed locally

- 新增`reporting/daily_brief.py`。builder只接受完整`VerifiedDecisionBatch`、治理`StrategyRegistry`、冻结
  `RuntimeLedgerSnapshot`和`NotificationSnapshot`；生成前重放batch lineage/artifact references、registry/version/budget、
  ledger snapshot和notification audit校验，并要求账本batch/manifest/plan与决策批次精确一致。`brief_id/brief_hash`及四个
  source hash均为确定性值，Dashboard接入时会从原source重建日报，不能用自报hash绕过内容校验。
- DailyBrief直接映射ledger equity和最新NAV PnL bridge、actual/expected positions、strategy decision/reason codes、当前
  planned/protective order和recoverable order scope、registry promotion状态、三方对账、notification delivery及open alerts。
  recoverable/UNKNOWN订单、reconciliation HALT或open HALT alert得到`halt_required`；其他对账失败、WARNING/CRITICAL或
  dead-letter得到`attention_required`；否则为`clear`。owner actions只来自固定确定性代码，LLM固定
  `not_requested_deterministic_only`，每个strategy的`live_orders_allowed=false`。
- 对当前Phase B不能证明的balance、actual gross、margin、peak drawdown、当日fills/rejections/partial fills、protective
  runtime states和slippage，日报显式列为unavailable，未用目标仓位或公共价格补算。Dashboard新增第五份`reports` read model；
  缺日报时显示`unavailable_until_phase_c_daily_brief`，有日报时使用独立`daily_brief` source hash与freshness，不会被其他source
  的更新洗新。
- 原子release现在精确包含`publication/overview/strategies/readiness/alerts/reports`六个canonical JSON；新增
  `daily-brief-v1.schema.json`和`dashboard-v1-reports.schema.json`，静态Draft 2020-12 schema总数为8。readback验证精确文件
  集合、`0644`权限、canonical JSON、所有model/publication hash及DailyBrief内容，覆盖半写、stale、内容/hash和release篡改。
- `web/site`新增`#/reports`，展示日报状态、equity/PnL、仓位与reason chain、sources、unavailable coverage、gates、owner
  actions和未解决告警。前端没有增加交易所/private API/SQLite读取或PnL计算。Node语法、8份schema JSON、静态HTTP以及真实
  Chromium桌面`1440x1000`/移动`390x844`（含完整长页）检查通过，无重叠、空白或非预期裁切；移动仓位表按设计横向滚动。
  本地fixture QA站点为`http://127.0.0.1:8768/#/reports`。
- 新增`tests/test_daily_brief.py`的6项测试和`tests/fixtures/daily_brief_v1_golden.json`。DailyBrief三模块聚焦`23 OK`、
  Phase B/C架构聚焦`90 OK`、全仓`1435 OK`；唯一warning仍为既有`cta_data.py` UTC deprecation。DailyBrief golden SHA-256为
  `4743a80e3408bf4590cf0ea04deff8cf1da13b3c909790d553828ba13c265d9c`，Dashboard ledger golden当前SHA-256为
  `62a1a6e69da0c7d0a37837ca586d25ae91768d1ccd916e655a47fb3735923d4b`。
- 本批只使用测试fixture、临时SQLite/JSONL和本地静态release；没有访问/部署VPS、生产artifact、私有API、交易所或订单接口，
  没有真实webhook、producer或publisher，也没有修改凭据、systemd/cron/live开关。结果是`research_sandbox`本地架构证据，
  不是production账户、成交、通知送达、日报部署或订单授权证据。

### Phase C durable alerts and Dashboard notification view completed locally

- 新增`notifications/`边界。`AlertEvent`冻结severity/category/title/summary/source/trace/dedupe和稳定ID/hash；
  `NotificationStore`在`0700`私有目录用`0600` SQLite WAL、foreign keys、FULL synchronous和busy timeout保存immutable
  events、OPEN/RESOLVED state、delivery jobs、attempts与hash-linked audit rows。alert/job exact replay幂等，同identity不同
  content/max-attempt合同冲突；任何业务row或audit chain篡改都拒绝生成snapshot。
- transport始终由调用方注入，本批没有网络实现或真实发送。每个job固定delivery idempotency key；失败按指数退避进入
  `RETRY_WAIT`，耗尽进入`DEAD_LETTER`，成功进入`DELIVERED`。外部成功后若进程在DB marker前崩溃，重启复用同一
  STARTED逻辑attempt和delivery key，不创建新identity或超过max attempts。delivery审计只保存canonical response hash与
  error type，不把webhook响应或密钥写入read model。
- `NotificationSnapshot`在单个SQLite读事务中验证events/states/jobs/attempts/audit后冻结severity/delivery counts、open alerts、
  source update和audit tail。`reporting/read_models.py`新增第四份`alerts`；有snapshot时source只有`notification_store`，无
  snapshot时明确`unavailable_until_phase_c_notification_store`。alerts freshness独立于batch/registry/ledger三模型，告警更新
  不能掩盖旧账户数据的STALE。原子release现在包含5个JSON，静态Schema为6份。
- `web/site`新增`#/alerts`，展示severity、OPEN/RESOLVED、title/summary、source trace、channel delivery state、attempt count、
  next retry与dead-letter；顶栏freshness随当前页面切换。前端仍没有Binance/private API/SQLite读取或PnL推导。Node语法、
  schema JSON、静态HTTP和真实Chromium桌面`1440x1000`/移动`390x844`截图通过，无裁切、重叠或空白；本地QA站点为
  `http://127.0.0.1:8767/#/alerts`。
- 新增8项notification故障测试并扩展Dashboard atomic/stale/tamper/golden矩阵。架构聚焦`92 OK`，全仓`1429 OK`；唯一warning
  仍为既有`cta_data.py` UTC deprecation。Dashboard ledger golden因第四份alerts引用更新，canonical SHA-256现为
  `1dd8379003745628e72778b8a2e217d36ce32a874c7ea952bbd319e467faeab8`。
- owner授权删除旧展示：仓库移除CTA-R SwiftBar/Übersicht源、旧`cta.json`推送脚本及plist，本机
  `com.qount.dashboard` LaunchAgent已bootout，SwiftBar缓存/stamp/旧ctar备份移入
  `~/.Trash/qount-cta-display-removed-20260720`。`com.qount.ctar-daily`是独立研究数据任务，未删除。本批没有访问/部署VPS、
  私有API、交易所、订单接口或真实webhook，没有修改systemd/cron/live开关；本地截图和fixture不能作为production证据。

### Phase B legacy dry dispatcher migration replay completed locally

- 新增`ledger/legacy_replay.py`。builder要求projection evidence hash与legacy plan source精确链接，并逐字节语义hash核对
  projection/plan decision和live contract；随后复用Base adapter、单sleeve Portfolio allocator、legacy Risk/Execution
  adapter和complete batch manifest，生成可由账本再次重放全部lineage的`VerifiedDecisionBatch`。legacy plan hash、风险
  blocker、合同错链或经济动作parity任一失败时，不登记账本。
- replay只接受隔离的空ledger或同一batch的精确幂等状态；登记前后都验证SQLite integrity、outbox与chain JSONL。报告固定
  `evidence_class=research_sandbox_local_migration_replay`和`replay_semantics=planned_only_not_executed`，记录legacy/standard
  economic-state hash、完整trace hashes、expected positions/tolerance、planned client IDs及audit tail。所有订单必须保持
  `PLANNED`；order event、fill、cash event、position、NAV、reconciliation和recovery count必须为0，因缺NAV/对账
  `risk_increase_allowed=false`。manifest继续`orders_authorized=false`，没有路由或成交声明。
- 新增7项组合测试和`tests/fixtures/legacy_dispatch_replay_golden.json`，覆盖完整batch登记、重启精确幂等、DB先提交而JSONL
  未写、JSONL已追加而publish marker未写、source/plan/report/journal篡改及已有执行状态拒绝重标。golden SHA-256为
  `f52af0a63d22044affee5c1a398341f266d0ffc57407b9f9c5ec57725429529a`。架构Phase A/B聚焦`75 OK`，
  MiniTrend/dispatcher`37 OK`，全仓`1420 OK`；唯一warning仍为既有`cta_data.py` UTC deprecation。
- 本批只创建测试临时SQLite/JSONL并使用既有fixture，没有读取生产legacy artifact、连接
  `mini_trend/pilot_dispatcher.py`、访问/部署VPS、私有API或订单接口，也没有修改凭据、systemd/cron/live开关。该报告只是
  本地迁移与恢复证据，不证明任何订单已发送、成交、对账或production deployment；真实生产行为仍归legacy dispatcher。

## 2026-07-19

### Phase B frozen ledger snapshot connected to Dashboard v1 locally

- 新增`ledger/read_model.py`的`RuntimeLedgerSnapshot`和builder。它没有交易所或订单接口；构建前补刷audit outbox，持
  journal lock验证SQLite integrity/foreign keys、完整outbox和canonical chain JSONL，再用单个SQLite read transaction冻结
  最新batch identity、positions、recoverable orders、NAV与同批最新reconciliation。对账必须是审计链最后一次状态事件，
  所以对账后新增fill/cash/order状态不能继续发布旧NAV；缺NAV/对账、batch/plan错链、审计或快照hash篡改均失败关闭。
- `reporting/read_models.py`新增可选`ledger_snapshot`输入。没有快照时保留原有
  `unavailable_until_phase_b_ledger`；有快照时三个模型共同增加`runtime_ledger` source hash，overview直接映射实际仓位与
  equity/trading PnL/funding/fees/transfers/residual bridge，strategy页只显示明确为portfolio scope的signal/standalone NAV，
  不伪造逐策略归因。`UNKNOWN`/in-flight状态和失败对账进入readiness blocker；健康快照只得到`read_model_ready`，所有策略的
  `live_orders_allowed`仍恒为false，不表示production或order authority。
- freshness使用快照内由audit尾事件确定的`source_updated_at`，不使用`captured_at`或publisher时间；同一账本晚抓取、晚发布
  仍在原`stale_at`到期。5份Draft 2020-12 schema已严格支持base-only和base+runtime source、available/unavailable仓位、
  PnL与NAV union。前端显示后端权威值和对账门，不增加Binance请求、账户访问或PnL算式。
- 新增8项桥接测试与`tests/fixtures/dashboard_v1_ledger_golden.json`，覆盖确定性快照、缺NAV/对账、对账后状态变化、audit与
  snapshot篡改、UNKNOWN可见且阻断、原子发布读回、重新发布不洗新和完整模型hash回放；golden文件SHA-256为
  `e21d6fc5...ca99302`。架构聚焦`68 OK`、MiniTrend/dispatcher`37 OK`、全仓`1413 OK`，compileall/Node/schema JSON/
  空白检查通过；唯一warning仍为既有`cta_data.py` UTC deprecation。没有访问/部署VPS、私有API或订单接口，没有创建生产
  DB/read model，没有修改凭据、systemd/cron/live开关，也没有接`mini_trend/pilot_dispatcher.py`或生产publisher。

### Phase B SQLite WAL ledger, UNKNOWN recovery, and reconciliation implemented locally

- 新增`ledger/store.py`，将完整`VerifiedDecisionBatch`及其planned orders作为账本唯一批次入口；对象和manifest引用会在
  写入前重放完整lineage/hash校验。SQLite运行在私有目录，固定WAL、foreign keys、FULL synchronous和busy timeout，
  覆盖batches/orders/order_events/fills/cash_events/positions/nav_marks/reconciliations/order_recoveries/audit_outbox。
  batch、order、fill和cash identity均幂等，同identity不同内容拒绝覆盖。
- 新增`ledger/audit.py`的canonical append-only JSONL chain与transactional outbox。业务事务先提交业务行和完整待发布
  row，提交后持锁fsync JSONL并补publish marker；启动会验证journal与全部outbox前缀。测试注入了“DB已提交、JSONL
  未写”和“JSONL已追加、DB marker未写”两种故障，重启均精确恢复且不重复；sequence/hash、canonical JSON、重复key、
  时间、权限、symlink和内容篡改均失败关闭。
- 新增`execution/state_machine.py`和`execution/recovery.py`。合法状态固定为PLANNED/SUBMITTING/ACKNOWLEDGED/
  PARTIALLY_FILLED/FILLED/REJECTED/CANCELED/EXPIRED/UNKNOWN；发送前先落SUBMITTING，累计成交量不得倒退、超计划或
  更换exchange order ID。恢复器只有按确定性client ID读取观察的接口；查询无结果、异常或无效观察转UNKNOWN并HALT，
  不把not-found当rejected，不创建替代订单，也不导入交易所adapter。
- fill按long-only平均成本更新内部position；funding、fee、transfer独立入账。NAV按
  `equity_change = trading_pnl + funding - fees + transfers + residual`从已入账事件计算，residual超限阻止风险增加，
  已封NAV区间拒绝晚到事件静默改写。三方对账持久化前必须匹配batch冻结target/tolerance、当前ledger position/open
  orders及最新residual；unmanaged/missing order、ledger/exchange仓位差异或residual超限要求HALT。
- 新增9项runtime ledger测试并扩展架构依赖测试。Phase A/B聚焦联合回归`60 OK`；MiniTrend signals/risk/execution/
  scorecard/backtest、pilot dispatcher与标准adapter窄回归`37 OK`；`compileall`、`node --check`、schema JSON解析、
  legacy浏览器PnL关键词扫描和`git diff --check`通过；全仓`1405 OK`，唯一warning仍为既有`cta_data.py` UTC
  deprecation。未访问/部署VPS、私有API或订单接口，未创建生产DB/journal，未改凭据、systemd/cron/live开关。
  新账本尚未接legacy dispatcher或Dashboard PnL，当前不构成live authority。

### Phase A Dashboard v1 authoritative read models implemented locally

- 新增`reporting/read_models.py`，生成schema v1的`overview/strategies/readiness`。入口只接受
  `VerifiedDecisionBatch`和治理`StrategyRegistry`，重新校验完整batch lineage、manifest artifact references、registry
  hash、策略版本、环境资格与风险预算；不读取legacy runtime JSON、浏览器状态、交易所或环境变量。
- Phase A没有运行账本输入，实际仓位、equity和PnL固定为`unavailable_until_phase_b_ledger`，不得用snapshot price或目标
  权重伪造。freshness绑定source created/data cutoff，重新发布旧batch不能重置stale时间；到期模型和readiness均显示STALE。
- 发布使用`releases/<publication_id>/`不可变`0700`目录、`0600`canonical JSON和`v1`相对symlink原子切换；半写失败
  删除临时release且保留旧指针。读取拒绝逃逸/非预期symlink、额外/缺失文件、权限异常、非canonical JSON、hash和
  publication/model错配。`web/schemas/`新增5份Draft 2020-12静态schema。
- `web/site`替换为overview/strategy/readiness只读监控台，只拉`data/v1/publication.json`及三份模型；已删除Binance
  公共ticker请求、`patchLive/livePx/unrealized_pnl`和浏览器equity/PnL重算。新增8项read-model/原子发布/stale/篡改/
  schema/前端边界测试。HTTP静态烟测通过；当前会话无可用Browser/Playwright/Chromium，未完成真实桌面/移动端截图验收。
  本批没有生成或部署生产read model，没有访问VPS；production站点在显式部署前仍不能视为已切v1。

### Phase A complete decision batch manifest and recovery implemented locally

- 新增纯合同`contracts/batch.py`。`ArtifactReference`绑定成员type、object ID、payload/artifact hash和固定安全文件名；
  `DecisionBatchManifest`把MarketSnapshot、多StrategyIntent、PortfolioTarget、RiskDecision、OrderPlan组成第九类标准
  artifact，生成确定性manifest hash/ID，并固定`orders_authorized=false`。
- 新增完整lineage校验：Intent必须共享snapshot/decision time/data cutoff；Portfolio的decision IDs和sleeves必须与
  intents一致，sleeve之和必须等于proposed target；Risk必须读取同一Portfolio目标；OrderPlan必须绑定同一batch、risk、
  target、snapshot和decision集合，批准目标必须等于Risk输出。Risk未允许increase时拒绝加仓动作，reduce/protective/
  cancel由`reduce_risk_allowed`独立控制，保留违规时必要减仓的语义。
- 新增`persistence/batch_store.py`。批次目录固定`0700`、artifact固定`0600`，成员逐个不可覆盖发布，`manifest.json`
  最后写入和fsync后才算complete；读取要求文件集合精确相等、无symlink、权限正确、每个成员与manifest引用一致并重放
  全部lineage断言。缺manifest的中断目录只标记incomplete，不会被Dashboard或后续执行当作完整批次。
- 新增显式`resume_incomplete_decision_batch()`：调用方必须重新提供完整标准对象；已有成员逐个验证且从不覆盖，只补缺失
  项并最后写manifest。冲突、额外文件、hash或权限异常停止恢复并保留原目录审计。该恢复没有交易所、账户、订单或arm能力。
- 新增12项批次golden/failure/recovery测试，覆盖manifest确定性与订单越权、manifest-last顺序、两次发布字节一致、
  no-overwrite、部分目录恢复、冲突恢复、缺/多成员、篡改和有效替换、跨对象错链、sleeve和风险权限、路径/时间、权限及
  黄金envelope hash。聚焦`59 OK`、MiniTrend`234 OK`、全仓`1387 OK`；`compileall`和空白/依赖边界检查通过，唯一
  warning仍为既有`cta_data.py` UTC deprecation。本批只写测试临时目录，没有访问或部署VPS、私有账户或订单接口，
  也未修改凭据、systemd/cron/live开关；complete batch不构成promotion、arm、订单已发送或实盘授权。

### Phase A immutable standard artifact persistence implemented locally

- 新增`persistence/codec.py`，为`MarketSnapshot`、traced `StrategyIntent`、`PortfolioTarget`、`RiskDecision`、含订单和
  撤单的`OrderPlan`、`StrategyRegistration`、`StrategyRegistry`、`DeploymentManifest`提供八类显式codec。统一
  envelope包含artifact schema/type/object ID、canonical payload hash和完整artifact hash；只允许精确字段集合，拒绝
  legacy schema 0 intent、未知schema/type、重复JSON key和非canonical JSON。
- 解码不使用通用dataclass注入。可重建对象全部重新调用权威`create()`，再把重建payload与持久化payload做canonical
  字节比较；嵌套`PlannedOrder/PlannedCancellation`也按batch重算确定性ID。Deployment manifest先验证自身合同，读回后
  仍可与独立读回的registry执行`validate_against_registry()`；所有manifest继续固定`orders_authorized=false`。
- 新增`persistence/immutable_json.py`：同目录创建`0600`临时文件，写入后flush/fsync，以hard link实现原子且不可覆盖的
  发布，再逐字节回读和完整解码；已有目标不会被替换，`.tmp/.partial`、截断JSON或篡改文件不能作为完成artifact。
  模块不读取环境变量，也不依赖ccxt、settings、executor、execution或交易所helper。
- 新增11项artifact回放/失败测试及1项架构依赖测试，覆盖八类round-trip、确定性字节和黄金envelope hash、payload/
  object ID篡改、未知schema/type、重复key、期望类型错配、no-overwrite、`0600`、临时/截断文件、OrderPlan完整字段和
  registry-manifest关联。聚焦`47 OK`、MiniTrend`234 OK`、全仓`1375 OK`；唯一warning仍为既有`cta_data.py` UTC
  deprecation。本批只在测试临时目录创建shadow fixture，没有生成真实registry/deployment artifact，没有访问或部署
  VPS、私有账户或订单接口，也未修改凭据、systemd/cron/live开关；持久化artifact不构成promotion、arm或实盘授权。

### Phase A strategy registry and deployment manifest contracts implemented locally

- 新增纯治理`governance/registry.py`。`StrategyRegistration`绑定strategy ID/version/kind、contract/code/config hash、
  promotion状态、promotion artifact、owner authorization、gross/stress上限、前序entry和recovery evidence；内容hash
  与确定性entry ID可发现篡改。`StrategyRegistry`每个逻辑策略只允许一个当前版本，并生成不可变registry hash/ID。
- 状态迁移固定为`draft -> research -> frozen_candidate -> shadow -> paper -> minimal_live -> scaled_live`或任意状态进入
  `halted`。同版本推进禁止改kind/contract/code/config；新版本只能回到research。任何gross或stress预算增加都必须绑定
  owner authorization；halt状态风险预算必须为0，恢复必须绑定reconciliation evidence和owner authorization，且不能
  高于halt前级别。非halted策略不能从新registry无解释消失。
- 新增registry到标准intent的纯校验：要求schema v1 trace、精确strategy/version、目标环境promotion资格以及不超过
  registry冻结的maximum gross/stress loss；未注册、legacy、版本错配或超预算intent在进入Portfolio前失败关闭。
- `DeploymentManifest`绑定git commit、dirty flag、code tree/dependency lock/runtime config hash、registry ID/hash、
  strategy entries、promotion/owner bundle、deployer、时间与rollback target。production必须`dirty=false`、所选策略至少
  `minimal_live`且有promotion/owner证据，并绑定可验证rollback；manifest始终`orders_authorized=false`，不能替代arm。
  Base adapter新增显式registration构造器，绑定权威Base version和现有live pilot contract hash，不自动声明晋级状态。
- 新增13项测试覆盖确定性、篡改、跳级、同版本换代码、新版本重回research、risk increase授权、halt/recovery、registry
  删除、intent版本/状态/预算、dirty/unpromoted production、rollback和manifest订单越权。治理聚焦`58 OK`、全部
  MiniTrend`234 OK`、全仓`1363 OK`；`compileall`、核心依赖扫描与`git diff --check`通过，唯一warning仍为既有
  `cta_data.py` UTC deprecation。本批未持久化或发布真实registry/manifest，未访问VPS、私有账户或订单接口，也未修改
  账户、凭据、systemd/cron和live开关；legacy dispatcher继续拥有全部生产行为。

### Phase A dry dispatcher risk/execution adapters implemented locally

- 新增纯内存`risk/validation.py`和`risk/legacy_dispatch.py`：前者按legacy `_finalize_plan()`同一14字段重算
  `plan_hash`，只接受dry mode并核对projection decision ID、`PortfolioTarget` decision IDs和原始目标权重；后者生成
  标准`RiskDecision`，把hash篡改、trace错链、diagnostic blocker和异常批准目标全部作为violations，批准目标归零且
  禁止加仓。drawdown flatten仍批准清仓目标，明确`reduce_risk_allowed=true`、`increase_risk_allowed=false`。
- `contracts/runtime.py`新增确定性`PlannedCancellation`，`OrderPlan`现在同时hash撤单、retained order IDs、预期仓位和
  reconciliation tolerance，并验证全局action sequence固定为reduce market -> increase market -> protective cancel ->
  protective submit。所有订单与撤单都保存source decision IDs；新client/cancellation ID由batch和动作内容确定性生成。
- 新增纯内存`execution/legacy_dispatch.py`与`execution/parity.py`。转换器只接受与标准target/risk完全匹配的已验证dry
  artifact，任何转换错误都返回空且不可执行的`OrderPlan`；它不发送订单，也不导入ccxt、settings、executor、交易所
  helper、文件系统或环境变量。黄金比较刻意忽略新旧client ID，只比较数量、方向、phase、order type、reduce-only、
  close-position、stop price、撤单、retained stops、expected positions和对账容差。
- 现有dispatcher夹具的3笔market和3笔`STOP_MARKET closePosition`全部经济行为一致；新增测试覆盖确定性ID、hash篡改、
  decision/target错链、legacy blocker、回撤清仓、保护单撤销/保留和依赖边界。聚焦`47 OK`、全部MiniTrend`234 OK`、
  全仓`1350 OK`，`compileall`与`git diff --check`通过；唯一warning仍是既有`cta_data.py` UTC deprecation。
  本批只是本地兼容适配器，VPS真实生产行为仍由legacy `mini_trend/pilot_dispatcher.py`拥有。本轮未访问或部署VPS，
  未读取私有账户、调用订单接口、修改systemd/cron、凭据或live开关。

### Phase A standard trace contracts implemented locally

- 新增`contracts/trace.py`与`contracts/runtime.py`，建立确定性、无密钥的64位SHA-256标识和本地完整合同链：
  `MarketSnapshot -> StrategyIntent -> PortfolioTarget -> RiskDecision -> OrderPlan`。每一级保存上游ID和内容hash，
  hash或ID被篡改会在`validate()`失败；合同层不导入ccxt、settings、executor、文件系统或环境变量。
- traced `StrategyIntent`现包含schema 1、strategy version、projection decision ID、snapshot ID、reason codes和
  `intent_hash`。旧位置参数/API仍生成schema 0 legacy intent并保持原校验，但`portfolio_target_from_allocation()`
  明确拒绝无trace对象。allocator原始返回结构和迁移前黄金hash保持不变。
- Base adapter新增`base_snapshot_from_projection()`，用既有data/rules/contract/evidence hash生成稳定snapshot reference，
  intent沿用既有projector decision ID并生成可审计理由。该bridge明确标记`account_snapshot_linked=false`和
  `funding_values_embedded=false`，只建立trace，不冒充Data Plane完整生产snapshot或Risk批准。
- `PortfolioTarget`保留proposed target、实际fail-closed target和各sleeve贡献；blocker存在时非零target直接非法。
  `RiskDecision`禁止有违规时允许增加风险；每个`PlannedOrder`保存source decision IDs，client ID由batch/decision/
  symbol/phase/sequence确定性生成；`OrderPlan`固定reduce -> increase -> protective顺序，合同本身没有订单发送能力。
- 新增`test_runtime_contracts.py`，覆盖稳定ID、snapshot/intent防篡改、完整五级链、blocker归零、账户未知禁止加仓和
  先加后减拒绝。聚焦合同/治理/Projection/Equity Mapping`53 OK`、全部MiniTrend`234 OK`、全仓`1340 OK`；
  `compileall`、核心依赖扫描和`git diff --check`通过，唯一warning仍是既有`cta_data.py` UTC deprecation。
  本轮未访问或部署VPS，未读取私有账户、调用订单接口、修改systemd/cron、凭据或live开关。

### Architecture Phase A package boundaries established

- 把564行的`portfolio_governance.py`按职责迁入四个明确包：`contracts`保存order-free `StrategyIntent`与稳定哈希，
  `portfolio`保存NAV/压力风险预算和fail-closed allocator，`governance`保存小账户运行资格、正式试验、独立证据单元和
  Equity Mapping事件容量，`strategies/base.py`保存Base projection到标准intent的适配器。新核心域不包含交易所、
  订单、环境变量、文件系统或模型调用。
- 保留`qount.portfolio_governance`与`qount.mini_trend.portfolio_intent`为显式兼容层；旧调用方得到的class/function
  与新权威对象完全相同。Equity Mapping生产代码改为直接导入新governance边界，其red-team来源清单也改读新的
  `governance/event_capacity.py`，避免继续审阅已经无业务逻辑的兼容文件。
- 新增`test_architecture_boundaries.py`，锁定旧新对象同一性、兼容层无业务定义、核心包无ccxt/settings/executor/
  exchange依赖，以及迁移前allocator黄金hash
  `8c2f5dfd...a3055d5`。原有合同保持不变：long-only、gross不超过1、未来data cutoff非法、异常整批归零、
  standalone与聚合后最小名义双检、小账户sleeve上限和正式试验族最多3次。
- 聚焦治理/Projection/Equity Mapping/架构测试`46 OK`，全部MiniTrend测试`234 OK`，全仓`1333 OK`；唯一提示仍是
  既有`cta_data.py` UTC deprecation。`compileall`和`git diff --check`通过。Phase A仍在进行中，尚未实现其余
  trace contracts、registry、manifest或Dashboard v1 read models；本轮未访问或
  部署VPS，未修改账户、systemd、cron、凭据、订单或live开关。

### Personal quant system architecture consolidated

- 新增[系统架构设计](system-architecture-design.md)，把当前Mac/外置盘/WSL/VPS拓扑、MiniTrend Base、
  本机multi-sleeve governance、legacy X4/RV代码和`qount.alyaloale.com`前端统一到一套渐进目标。核心选择为
  模块化单体+systemd、VPS ext4 SQLite WAL运行账本、append-only chain JSONL审计、静态Dashboard read model、
  确定性Risk/Execution和LLM只读分析旁路。
- 文档定义了MarketSnapshot -> StrategyIntent -> PortfolioTarget -> RiskDecision -> OrderPlan -> Fill -> Ledger/
  Reconciliation完整trace，订单UNKNOWN/部分成交/重启恢复矩阵，三类NAV、PnL residual、通知outbox、DailyBrief、
  Dashboard十个视图、目标目录和failure/golden replay测试。
- 当前前端仍是Caddy Basic Auth保护的静态SPA，读取legacy `x4_live/x4_paper/cxd_live/cta` JSON并在浏览器用公共价格
  重算实时权益；目标前端保留现有视觉外壳，但只展示VPS原子发布的权威v1 read models，不增加交易或arm按钮。
  域名匿名HTTP检查返回401，认证边界仍有效；当前环境无浏览器会话，未做认证后视觉截图检查。
- 迁移顺序固定为统一合同/trace -> 统一账本、订单状态和恢复 -> 通知、Dashboard和日报 -> Base minimal-live审查
  -> 多策略组合 -> 持续研究。本文不构成live授权；本轮未改代码、前端、VPS、账户或订单状态。

### Multi-sleeve allocator completed; Capitulation Rebound trial rejected

- 新增标准order-free `StrategyIntent`与Base causal projection adapter。组合allocator按每个sleeve冻结的压力损失预算
  缩放，检查allowlist、同批decision time、总gross、单币cap、相关簇和最小名义；任一异常让整个组合目标归零，
  同时保留proposed weights、blockers和allocation hash。最小名义在Standalone sleeve和组合两层分别检查，Base
  净额不能替一个自身不可成交的alpha sleeve补足交易所floor。当前只在research/shadow边界，不改VPS dispatcher。
- 修复一个既有回归：`pilot_300_research`误把已消费历史的固定300 USDT本金与当前动态pilot的1000 USDT上限做
  相等比较。现在历史研究本金仍严格冻结300，只要求它落在当前100-1000允许区间，历史结果不会随实时余额漂移。
- 在读取结果前生成Capitulation Rebound v0.1预登记：Base gate off、TOP3五日全跌、中位`<=-8%`、波动率分数
  `<=-1.5`、下一开盘等权long、持有3日、3xATR stop、5日cooldown、24bps round trip；formal trial=144，
  不做参数搜索。预登记artifact
  `state/research_runs/20260719T093752Z-mini-trend-capitulation-rebound-preregistration/mini_trend_capitulation_rebound_preregistration.json`，
  SHA-256 `b4ec5853...0ba9`，contract/protocol hash `6c219cc6...18eb`/`ef9d183a...5f09`。
- 最终price+cost discovery只读Mac既有UM日线cache，2021-01-01..2026-07-17共同2024根、data hash
  `f9af7728...20ac`；57个原始信号折为18个独立episode，正收益率`44.44%`、中位/均值净收益
  `-1.8747%/-2.1278%`、复合`-36.4990%`、maxDD`39.5163%`、中位BTC-beta residual`-0.5374%`、9个symbol
  触发stop。2021-22/2023-24/2025-26分段复合均为负，5/7门失败，verdict
  `reject_historical_capitulation_rebound`。最终artifact
  `state/research_runs/20260719T094147Z-mini-trend-capitulation-rebound-price-discovery/mini_trend_capitulation_rebound_price_discovery.json`，
  SHA-256 `cf7e8348...8ca9`；
  不调阈值/持有期，不补funding replay，不进shadow/paper/live。
- WSL/外置盘节点本轮SSH超时；未把研究转移到VPS、未联网补cache、未调用私有API或订单。MiniTrend全量聚焦
  `234 OK`，allocator/Capitulation/Projection/历史300合同聚焦`24 OK`，全仓`1328 OK`；compileall、CLI help、
  `git diff --check`均通过，唯一warning仍是既有`cta_data.py` UTC deprecation。VPS最终只读复核保持timer
  enabled/active、service result success/0、`HALT` absent、latest run `20260719T091232Z`，没有部署或生产变更。

### MiniTrend dry dispatcher and independent VPS runtime completed

- Owner把固定300 USDT合同改为manual arm前读取已审计USD-M可用余额，范围`100-1000 USDT`，当前生产基线
  `488.89481071 USDT`；owner接受当前VPS-only credential和Spot/Margin权限。Reading/Futures/IP restriction开启、
  Withdrawals关闭，TOP3均为one-way/isolated 1x，账户全平且0挂单。credential bytes和精确生产IP均未写入仓库。
- 新增MiniTrend专用dispatcher：绑定preflight/projection/rules/readiness及文件hash，重算decision/execution-state hash，
  严格读取普通订单和Binance独立条件单簿，拒绝unmanaged/short，使用确定性client order ID和预写live intent锁；
  append-only journal带row/chain hash并自动按唯一decision date统计dry证据。live路径实现market reconcile、
  `STOP_MARKET closePosition`、成交后仓位/保护单回读和10%权益峰值回撤flatten+halt。
- 新增最终arm生成器：只有`ready_for_manual_final_arm`、人工确认精确readiness hash、0600不可覆盖arm文件、独立token、
  `QOUNT_MINI_TREND_LIVE_ENABLE=true`和匹配arm ID的confirmation同时存在才允许live。当前没有arm，unit强制全部
  legacy/MiniTrend live开关为false，并在order-free cycle内清除confirmation/token环境。
- latest projector现在把状态机trail high转换为同一3xATR原生保护价。systemd cycle已接入runtime proof、dry dispatcher
  和dry journal自动计数。Mac与VPS聚焦测试均为`37 OK`，compile/shell/diff检查通过，部署文件hash一致。
- 最新VPS run `/root/qount/state/mini_trend/forward/runs/20260719T091232Z`成功：independent runtime verified，账户快照
  pass；尚无`2026-07-19`完成bar，因此dry为`await_dispatch_decision`、0市场单/0止损单/0 journal，
  `exchange_mutation_attempted=false`、`live_orders_allowed=false`。readiness只剩五项未来数据门：60 forward pair、
  10 active bar、30 paper day、7 unique dry day和完整funding journal。timer继续enabled/active。

### Replacement Binance credential accepted; account remains fail-closed

- Replacement credential通过关闭回显的stdin只写入VPS `/root/qount/.env`，未进入命令、日志、artifact或文档；
  VPS `.env`保持`0600`且两项各一行/64字符，Mac `.env`继续无Binance credential。由于该credential曾经由对话
  明文传输，它只用于本次接入测试；最终实盘前必须在Binance再次轮换并直接写VPS。
- Binance只读审计确认credential有效：Reading/Futures/IP restriction开启、Withdrawals关闭；账户为one-way、
  当前全平、无unmanaged position且全账户open orders为0。Spot/Margin Trading仍开启，权限过宽；可用资金未达到
  300 USDT；BTC/ETH/BNB的只读symbol config均为isolated 2x，不符合冻结的1x合同。未自动修改权限、杠杆、
  保证金模式或资金。
- preflight升为v0.3：显式确认一次ccxt高权重的全账户open-orders只读查询，并用`fetch_leverages`/
  `fetch_margin_modes`审计空仓symbol config；不再把ccxt warning或空仓positions省略误判为账户证据。readiness升为
  v0.4，新增Reading必须开启、Spot/Margin必须关闭两项正式gate，合同hash随权限边界更新。
- Mac全部MiniTrend pilot测试`23 OK`、live readiness`7 OK`；VPS部署文件与Mac SHA-256一致，聚焦`15 OK`。
  最新order-free run `/root/qount/state/mini_trend/forward/runs/20260719T081828Z`成功：preflight只剩
  `spot_margin_disabled/pilot_capital_available/isolated_one_x_verified`三项blocker，readiness阻断10项，
  `live_orders_allowed=false`；全部JSON为`0600`，没有订单或账户写方法调用。

### Old Binance credential removed; production IPv4 boundary verified

- Owner改为轮换Binance credential。Mac与VPS `.env`中的`QOUNT_BINANCE_API_KEY`和
  `QOUNT_BINANCE_API_SECRET`均已按变量名无备份删除，复核为absent；两个文件权限保持`0600`，未输出旧值。
- VPS在unset全部代理变量并强制`--noproxy '*' -4`后，两个独立公网身份服务返回同一IPv4，且与SSH-facing地址
  一致；三个强制IPv6探针均无法连接。精确地址只保留在仓库外production inventory，不写入仓库。
- 新key的Binance边界固定为：只绑定该单一VPS IPv4，只开读取与USD-M Futures交易，关闭提现与未使用的
  Spot/Margin权限。owner完成配置前，order-free forward timer保留，公开bar/funding继续采集，私有preflight
  对缺失凭证fail closed；live开关、订单端点和旧cron均未启用。
- 删除后只读复核artifact `/root/qount/state/mini_trend/forward/preflight-credential-removed.json`保持`0600`：
  `credentials_present=false`、错误为`missing_api_credentials`、15个账户门阻断、
  `private_api_order_attempted=false`、`live_orders_allowed=false`。forward timer仍为enabled/active，oneshot服务
  当前inactive且上次`Result=success`。

### MiniTrend order-free VPS forward cycle deployed; live remains blocked

- Owner要求继续使用已有Binance credential。Mac/VPS现有pair只比较指纹且一致，credential bytes未改写；两个`.env`
  均为`0600`。VPS清空代理后的公开UM route可用，但同一旧key的私有balance仍返回`-2015`，preflight保持13项阻断；
  这不是IP或代理已解决的证据，也没有通过API permissions、余额、仓位、one-way、open orders或1x逐仓审计。
- 新增`mini_trend_um_forward_cycle.sh`、readiness artifact证据提取模块和systemd service/timer。周期使用`umask 077`、
  `flock`、`HALT`、直连no-proxy、显式关闭`QOUNT_LIVE_ENABLE/QOUNT_X4_LIVE_ENABLE/QOUNT_RV_LIVE_ENABLE/
  QOUNT_CXD_CARRY_ENABLE`；每天`03:20 UTC`后随机延迟最多10分钟，只运行公开rules/input refresh、只读private
  preflight、order-free paper、latest projection和readiness。旧root crontab有效行0，旧qount/alpha服务均inactive。
- 首次实跑暴露两项数据工程问题并修复：Binance funding `endTime`不能覆盖带1-13ms抖动的次日00:00 settlement；
  现按既有LiquidTrend语义把1秒内抖动归一到最近分钟，并给查询上界60秒grace，再在archive/snapshot合并时统一
  canonical timestamp。另让seed只填充不存在的目标cache，不再让后到stale seed阻断已验证canonical cache。
- 最近成功run `/root/qount/state/mini_trend/forward/runs/20260719T074248Z`：UM rules `3/3`，公开TOP3日线到
  `2026-07-18`，funding完整`3/3`，input verdict `shadow_inputs_refreshed`。因冻结起点`2026-07-19`尚无完成bar，
  paper仍为0 pair/0 day/0 journal，latest projector返回`paper_start_bar_not_available/decision=None`；readiness
  仍阻断20项、`live_orders_allowed=false`。运行source artifact均绑定path/bytes/SHA-256，无订单API调用。
- 新增causal latest-bar projector，明确追加flat synthetic outcome只触发最新决策而丢弃其PnL。回归测试证明：在
  outcome未知时投影的同日Base target/execution-state hash，与后来加入任意大跌outcome后的paper replay完全一致。
  projector不等于live dispatcher；exchange-native stop、幂等订单/恢复、7日dry与manual arm仍缺，
  `independent_runtime_verified=false`。
- 本地MiniTrend为`217 OK`、全仓`1307 OK`，唯一warning仍是既有`cta_data.py` UTC deprecation；VPS生产runtime
  聚焦`33 OK`，systemd cycle result=`success`且timer enabled/active。VPS宽泛MiniTrend discovery测试运行166项后有
  5项因production venv刻意不含`numpy`而报错；未为研究测试向VPS安装optional依赖，生产聚焦集不受影响。策略trial
  count保持143；没有新增参数搜索、充值、下单、撤单、转账或旧cron恢复。

### Equity Mapping public source capacity blocked before the first market event

- 新增`mini_trend/equity_mapping_sources.py`与薄CLI，把来源选择从raw sealing中隔离出来：初始/最终HTTPS host
  allowlist、禁环境代理、单响应2 MiB上限、8秒bounded timeout和并发小探针；输入只允许固定11个映射symbol。
  Binance mapping/bookTicker解析分别绑定TRADIFI perpetual语义与server `time`；Bitstamp USDTUSD绑定
  `microtimestamp`；任何缺失market quote时点的响应都不能用HTTP接收时间补写。
- Nasdaq适配器只把target-date一致的market-info接受为cash calendar。cash quote必须为real-time、有bid/ask且有
  可解析quote-event timestamp；split不能从混有其他日期的rows推断无公司行动，earnings空rows或未绑定目标日期的
  rows也保持阻断。新增测试覆盖delayed/N/A报价、未来quote timestamp、split date scope与空earnings响应。
- `20260719T065611Z-equity-mapping-source-capacity/equity_mapping_source_capacity.json` SHA-256
  `ee0799d7...09d58`，contract hash `b12a7f23...ed6dd`。10个公开无代理小探针只有Nasdaq market-info通过；Binance
  两项与Coinbase/Kraken/Bitstamp/Gemini USDTUSD均以`transport_unavailable`记录，不能误读为来源已被否证。
  Nasdaq cash quote是delayed/N/A/无quote-event timestamp，split/earnings无法证明目标日语义，stress source未分配，
  最终7/8 required roles阻断。
- 4份Nasdaq raw body共`10,349 bytes`，逐文件readback SHA-256与manifest一致，manifest content hash
  `aa91e8d1...466d7`。artifact固定`trial_count=0`、`market_event_created=false`、`future_return_evaluated=false`、
  `pnl_evaluated=false`、`orders_allowed=false`；首个`2026-07-20`窗口readiness和G0 v0.4合同均未改写。
- 聚焦Equity Mapping为`36 OK`，全部MiniTrend为`209 OK`，本地完整回归`1299 OK`；唯一告警仍是既存
  `cta_data.py` UTC deprecation。`compileall`、source-capacity CLI help、artifact JSON invariant和raw hash复核通过。
  本轮未访问VPS、私有API、订单或cron，也未安装collector或生成第144个策略trial。

### Equity Mapping raw collection gate added before the first real cash date

- Equity Mapping合同显式升为G0 v0.4 / input v0.2；旧v0.3 artifact保留，不静默改写。新增
  `mini_trend/equity_mapping_collection.py`与薄CLI，按纽约DST固定`09:24:30-09:25:00`采集窗口，要求三腿
  quote source/capture时点均在决策前且全批最大skew 5秒。逐资产必须覆盖instrument mapping、mapped quote、
  cash premarket quote、corporate action、event context，全局必须覆盖USDTUSD、cash calendar、stress scenario。
- 该入口是provider-neutral raw intake/sealing，不执行网络抓取或市场字段解析；真实cash premarket、USDTUSD、
  官方日历/公司行动adapter仍未选定/接入。readiness只说明窗口合同已冻结，不能误读为采集服务已经运行。
- raw输入只允许`response_body_only`，单响应/单批上限2/16 MiB；HTTPS source URL必须命中显式host allowlist，
  拒绝userinfo、非443端口、fragment及常见key/token/signature query。每份原始bytes计算SHA-256并回读验证，
  bundle按`cash-date/batch-hash`写入不可覆盖目录；同内容幂等，任一响应变化只生成新bundle，旧bytes保持不变。
- G0非合成`point_in_time_collection`新增强制raw lineage：`--raw-manifest`先重算batch hash并回读全部原始响应，
  随后按同一现金日核对每个事件的8类source hash。缺manifest、伪sealed状态、synthetic bundle、跨日或任一hash
  缺失均把verdict改为`block_equity_mapping_g0_raw_lineage`，`market_evidence_claimed=false`；合成fixture保持只作
  plumbing，不被错误要求伪造raw market来源。
- v0.4合成复跑仍为2个asset-event/1个独立cash date、`collect_equity_mapping_independent_dates`，artifact位于
  `state/research_runs/20260719T054823Z-equity-mapping-g0-qount-equity-mapping-g0-v04-fixture/`，文件
  `qount-equity-mapping-g0-v04-fixture.json`，SHA-256 `b2b0833c...9359`。首个真实目标日readiness artifact
  `state/research_runs/20260719T054823Z-equity-mapping-collection-readiness/equity_mapping_collection_readiness.json`
  SHA-256 `b8576583...d463`，目标`2026-07-20 09:24:30-09:25:00 America/New_York`（UTC
  `13:24:30-13:25:00`），当前`await_collection_window`且`market_evidence_present=false`。
- 结构化G0输入不能内嵌或自报`raw_collection_manifests`；只有CLI的`--raw-manifest`逐文件完成manifest/batch/raw
  readback后，才通过显式trusted参数交给dataset builder，避免输入JSON伪造`raw_readback_verified=true`。
- 聚焦Equity Mapping为`28 OK`，全部MiniTrend为`201 OK`，本地完整回归`1291 OK`；完整回归只有既存
  `cta_data.py` UTC deprecation warning。`compileall`、两条CLI help、artifact JSON检查和
  `git diff --check`通过；URL校验另拒绝IP literal，损坏manifest/raw继续fail closed。当前环境未安装`ruff`，
  因此未声称lint已运行。本轮未访问VPS、私有API、订单或cron，
  未产生第144个策略trial，未把窗口前readiness计作独立现金日期。

### Equity Mapping G0 v0.3 built and red-teamed without execution authority

- 新增`mini_trend/equity_mapping.py`、离线G0 CLI和结构化fixture。v0.3固定纽约`09:25`决策、决策前30秒报价窗、
  三腿最大5秒skew，并要求mapped/cash premarket/USDTUSD的base、quote、venue、`quote_at/available_at`、source
  hash和product kind全部point-in-time可核验。USDTUSD按USD/USDT相乘，price multiplier显式定义为映射报价到一股
  现金股票基准。
- `TrueGapMid`只作观察；long候选必须满足使用三腿bid/ask构造的`GapUpper<0`。无效/NaN报价变成带原因的null阻断
  记录，不产生非标准JSON。公司行动只允许来源明确的split/reverse-split乘法归一化；未知、未来可见、停牌、闭市、
  日历/报价迟到全部fail closed。
- event sizing仍按账户0.25%压力损失预算，但`stress_loss_fraction`现必须绑定scenario id、观测截止、可见时间、
  source hash，并声明覆盖mapped/stablecoin spread、fees、slippage、gap tail和market impact。压力容量通过不构成
  minimal-live资格；G0所有事件固定`orders/paper/live=false`，后决策成交报价必须在独立shadow阶段收集。
- 经济事件ID现在只由venue/symbol/cash date/decision/closure/contract生成；每次原始证据另有revision hash。
  report重算事件ID并拒绝伪造ID、重复经济事件、非法ID和contract hash漂移，避免同一事件重采样膨胀asset-event。
- 新增只读`mini_trend_equity_mapping_red_team.py`。第一次调用被旧shell环境的`glm-5.2`和并发/重试覆盖正确阻断；
  显式单次切回`gpt-5.6-terra`、并发1、重试0且`trust_env=false`后完成三次审阅。模型指出的中点、公司行动、重复、
  压力血缘、外部ID和venue问题均经代码复现后修复；对真实USDTUSD、公司行动方向和交易日历的意见保留为待官方
  fixture验证的假设，不直接采信。
- 最终合成输入2个asset-event/1个独立cash date，2/2数据合同有效但不足30日，verdict
  `collect_equity_mapping_independent_dates`。artifact
  `state/research_runs/20260718T180643Z-equity-mapping-g0/equity_mapping_g0.json` SHA-256
  `fd93d83a...2266`，contract hash`dcbef759...1e46`；fixture SHA-256`ab533ef5...9cbc`。这是contract plumbing，
  `market_evidence_claimed=false`，不计入旧18个日期、不算PnL、不触发strategy trial。
- G0聚焦`20 OK`，与组合治理/旧TradFi研究/relay边界的聚焦集`37 OK`；全仓`1283 OK`，唯一告警仍是既存
  `cta_data.py` UTC deprecation。`compileall`、两条CLI help、fixture JSON、`git diff --check`和凭据字面值扫描
  均通过；测试生成的6个临时artifact及两个被替代中间artifact已清理，Mac `state/`保留最小证据链约76 KiB。
  未访问VPS、Binance私有API、cron或订单端点，也未使用环境代理、美国代理或苏菲家宽代理。

### Relay research default moved to gpt-5.6-terra; official-source retrieval boundary added

- Owner要求从即将退场的`gpt-5.4-mini`切到当前主流relay模型。无环境代理、无推理的OpenAI SDK
  `GET /v1/models`返回200/16个模型，确认`gpt-5.6-terra`和旧mini均存在；代码默认、`.env.example`、
  用户级`~/.qount/alpha-agent.env`、Alpha Agent文档和`qount-doc-autopilot`已统一到terra，私有配置仍为0600。
- 本地bundled公共OpenAI模型指引只列到`gpt-5.5`，没有`gpt-5.6-terra`；因此文档只把terra称为当前relay目录
  实测模型，不声称它是OpenAI公共API官方推荐。官方OpenAI Docs MCP已注册到Codex全局配置，当前会话需重启后
  才会暴露该工具。
- 新增`alpha_agents/official_sources.py`：只允许HTTPS官方域，拒绝内嵌凭据、IP literal和非443端口；初始URL与
  重定向最终URL都过allowlist；抓取显式`ProxyHandler({})`，不使用苏菲家宽或任何环境代理；单文档最多512 KB，
  保存observed time、content type、byte count和原文SHA-256，HTML移除script/style后最多给LLM 12,000字符。
- 新增5个官方源测试，覆盖hash/可见文本、未知域/凭据拒绝、重定向复核、超限拒绝和无代理抓取。该层只提供
  可验证网页正文，不让LLM的模型记忆或自称搜索成为交易证据；没有启动批量抓取、策略trial、paper/live或订单。
- Binance开发者站和GitHub HTML在Mac无代理直连均超时，没有改走美国/苏菲代理；GitHub官方API可达，抓取
  `api.github.com/repos/binance/binance-public-data/readme`的raw media type成功：`5144 bytes`、source hash
  `085ab913...f7c6`。新增可复跑的`alpha_agent_official_source_review.py`后，以terra执行一次真实source review，
  status `ok`、context hash `f5072a3b...4255`、orders/paper/live均false。artifact
  `state/research_runs/20260718T173443Z-alpha-official-source-review/alpha_official_source_review.json`的SHA-256为
  `018195cb...4695`。
- 报告指出Spot/UM/CM archive分类、daily/monthly发布时间、`.CHECKSUM`和2025 Spot微秒时点；代码逐项核验后，
  微秒归一化与去重已存在，checksum缺口成立。`grid/data.py`新增sidecar URL/格式解析、文件名绑定、SHA-256验证和
  `verified_archive_fetch`，并删除“远端ZIP不可变”的错误假设。严格helper只服务新摄取，既有缓存不被追溯标成
  官方checksum已验证；没有调整策略、回测收益或trial count。
- URL安全复核进一步确认仅allowlist `github.com`域名不足；官方源层现对GitHub再绑定owner/repository，当前只允许
  `binance/binance-public-data`，任意其他仓库即使同域也拒绝。最终全仓`1262 OK`，新增链路聚焦`38 OK`；
  `compileall`、CLI help、`git diff --check`、模型/私有配置和凭据字面值检查通过。全仓测试临时目录已删除，仅保留
  上述14.8 KB真实terra review artifact，Mac `state/`约28 KB。

### Portfolio governance hardened and relay-station ChatGPT boundary connected

- 1000 USDT表不再表示四策略立即真钱分仓：账户权益低于3000 USDT时，最多一个连续型live候选和一个事件型
  最小试单，其余只运行virtual/shadow。风险预算统一定义为账户压力损失贡献，v1只使用固定标量、单标的/相关簇/
  gross/压力上限，不使用协方差优化器。
- 新增`portfolio_governance.py`和8个单测：Signal/Standalone Executable/Portfolio Realized三NAV分账，晋级
  只读取Standalone且拒绝把netting savings写回；每假设族最多3个正式trial；查看前向结果后改规则会自动降级为
  consumed；Base 60日只作运行证据，Equity Mapping按独立美股交易日、Funding按拥挤episode计数。
- LiquidTrend容量合同升为v0.2代码语义：首个PnL前冻结robust rank、至少8币、缺funding剔除、121根warm-up、
  周一固定窗口和买ask/卖bid；新增特征值有效维度、PC1占比、BTC beta、BTC下跌条件相关和相关簇稳定性。既有
  v02 G0 artifact没有重写，仍是已消费容量诊断和阻断结论。
- `alpha_agents/llm.py`默认改为relay-station `https://llm.alyaloale.com/v1`的ChatGPT
  `gpt-5.4-mini`：显式opt-in、并发1、SDK重试0、输入/输出限长、精确五字段JSON、无tools。用户级
  `~/.qount/alpha-agent.env`已在不读取/回显token的情况下更新并保持0600；仓库新增6个InformationEvent fixture，
  覆盖五类有效官方事件和一次未来时点拒绝。客户端强制`trust_env=False`，不继承任何环境代理；使用同一SDK的
  只读`GET /v1/models`返回200、16个模型且包含`gpt-5.4-mini`，没有发推理请求。
- qount仓库中的VPS公网IP已从当前/历史文档、脚本默认值、launchd和生成元数据移除；统一使用仓库外
  `QOUNT_VPS_HOST`或SSH别名`qount-vps`。raw双物理副本、外部root hash锚定、随机checksum审计、journal独立
  只写锚定和恢复演练写入长期合同。
- 本轮没有发送ChatGPT throwaway推理请求、没有访问交易所私有API、没有部署VPS、没有恢复cron或生成订单。
- 最终聚焦治理/LLM/LiquidTrend为`25 OK`，Mac全仓`1253 OK`；唯一告警仍是既存`cta_data.py` UTC
  deprecation。`compileall`、修改脚本Bash语法、launchd plist、fixture JSON、`git diff --check`、公网IP和已知
  凭据字面值扫描均通过。全仓测试生成的6个临时research目录已定点删除，Mac `state/`恢复约12 KiB。

### 1000-USDT multi-strategy architecture defined; LiquidTrend10 stopped at G0

- 新增`docs/crypto-portfolio-system-plan.md`，把owner计划的1000 USDT定义为未来组合合同而非即时实盘授权。
  系统分为Data/Research/Strategy/Portfolio/Execution五层；Base、Equity Mapping、LiquidTrend、Funding Event
  使用独立虚拟NAV和统一allocator。当前只有Base保留控制角色，其他sleeve真钱风险预算为0；300 pilot、无单日
  止损、10%累计回撤halt和no short/carry/leverage boost/gross<=1约束不被自动替换。
- 新增`mini_trend/liquid_trend.py`、薄CLI和5个单测。G0固定十币、1000 USDT、2021-07-20..2026-05-31，
  只审计bar/funding/quote-volume/runtime filters/相关性，不计算预留momentum score或PnL，trial count=0。
- 首跑发现Funding完整率仅81.7%；审计确认不是缺档，而是Binance标准结算时间存在1-46ms抖动，导致相邻日被
  分成2/4次。v0.2在最近分钟规范化后再按`bar_open<settlement<=bar_open+24h`分桶，10/10 Funding覆盖通过，
  新增亚秒抖动回归测试；未填0或修改收益口径。
- 最终1777个BTC参考日/1772个共同日，覆盖`99.7186%`；最低单币日quote-volume中位数`225,466,636.60
  USDT`。平均绝对相关`0.661578`、有效广度`1.437979`；分段为`1.384389/1.627722/1.276677`。原始十币
  横截面没有越过2.0门。
- 现有runtime UM规则仅BTC/ETH/BNB/SOL 4/10。WSL无代理和IPv4直连`fapi.binance.com`均超时，Binance Vision
  替代路径返回404；没有使用VPS中转或苏菲家宽代理。最终5/9门通过，verdict
  `block_liquid_trend_g0_data_or_execution`，原始score trial不启动。
- 最终artifact
  `/mnt/e/qount_data/qount/artifacts/experiments/20260718T164231Z-liquidtrend10-g0-v02/liquid_trend10_capacity.json`
  SHA-256 `743f83c1...2728`、data/contract hash `187a6d3d...f75`/`4373e8c2...d02`、manifest content hash
  `93206835...101c`。v01为Funding时间分桶错误的中间件，清理后只保留v02。

### LLM information-event boundary implemented before model integration

- 新增`alpha_agents/information_events.py`与4个单测。`InformationEvent`绑定HTTPS允许来源、原文SHA-256、
  `published_at<=available_at<=observed_at`、实体、事件类型、数值、原文片段、抽取器版本和确定性event id。
- validator拒绝非允许域、naive/future时点、重复、非有限数值及`set leverage/market buy`等越权语言；audit batch
  只有全部事件有效且无重复才允许生成research feature rows。feature row只含event flags和原始numeric fields，
  不含LLM摘要，且显式`orders_allowed=false/paper_or_live_allowed=false`。
- 本地LiquidTrend+InformationEvent聚焦`9 OK`；Mac全仓`1237 OK`，唯一告警仍是既存`cta_data.py` UTC
  deprecation。全量`compileall`、CLI/import smoke、Bash语法、`git diff --check`和凭据/代理URL扫描通过。
  WSL LiquidTrend聚焦`5 OK`，v02 artifact和manifest回读匹配，scratch只留marker+空state；Mac测试生成的6个
  临时research目录已删除并恢复约12KiB。尚未调用LLM、抓取公告、生成交易特征、部署VPS或改变策略。

### Tokenized US-equity market opened as a new low-frequency discovery line

- 官方公共市场面盘点确认Binance USD-M有11个活跃`TRADIFI_PERPETUAL`：TSLA、MSTR、AMZN、COIN、META、
  NVDA、GOOGL、QQQ、SPY、AAPL、MSFT；最早TSLA也仅从`2026-01-28`开始。Binance spot还有NVDAB、
  TSLAB、SPYB等映射`*B`token。Bybit有AAPLX、AMZNX、COINX、GOOGLX、METAX、NVDAX、TSLAX等xStocks
  spot及对应equity linear。文档明确区分发行/托管/赎回型token与funding/清算型永续，不把它们混成普通币。
- WSL直连Binance Vision，经HKG CloudFront直接把11个永续从上市月至2026-06的小时K线和funding写外置盘；
  90个不可变文件、1,252,474 bytes，dataset content hash `7a813714...05d`。未使用代理、Mac或VPS中转。
- 冻结研究使用纽约DST、SPY现金交易日历和“前一现金收盘 -> 下一开盘前代理价 -> 下一现金收盘”；周末收益
  为负才long，下一现金收盘退出，同日标的等权、总gross=1，扣24bps往返成本和funding。126个symbol-event
  只有18个独立cash date；周末/现金收益相关`-0.188459`、反号率`56.35%`、71个long signal。
- 正确的date-cluster组合为`+3.7516%`、maxDD `4.0029%`、bootstrap正均值概率`71.16%`。首版把126个
  横截面事件顺序复利得到`+29.69%`，违反同日共享资本约束，已经明确作废；最终v02 artifact
  `/mnt/e/qount_data/qount/artifacts/experiments/20260718T155058Z-tradifi-weekend-v02/binance_tradifi_weekend.json`
  SHA-256 `d857361f...02c`、manifest content hash `821ad7d2...08`。Mac/WSL聚焦测试均`4 OK`。
- 结论只属`short_recent_history_discovery`：18个独立事件不够训练神经网络，也不够进paper/live。下一数据产品
  是point-in-time跨场所basis panel，按时点同步Binance perp/`*B` spot与Bybit xStocks/linear，并追加真实
  未来周末；不部署collector/cron，不触碰订单。

### Fixed-capital DCA/DCR and causal action-label discovery completed

- 新增`periodic_allocation.py`及CLI/4个测试。BTC UM与SPY每周25%阶梯；TOP3 UM因300 USDT下25%会违反BTC
  最小名义价值，使用50%阶梯；所有策略不追加资金、不做空、gross<=1。BTC经典DCA/均线DCA-DCR/持有为
  `+47.96%/+51.52%/+87.40%`，TOP3为`+82.34%/+46.81%/+104.91%`，SPY为
  `+79.40%/+62.19%/+82.47%`。定投定减未战胜buy-and-hold。
- 用未来20根、波动率归一化triple barrier生成buy/hold/sell标签；特征只使用决策日已完成数据，Logistic/HGB
  按年扩展Walk-Forward并按`label_end_date` purge。六个模型平均Brier/log-loss uplift全部为负。TOP3 HGB的
  `+216.99%`因4/4 Brier折输常数先验、2025贡献`+92.66%`而2026亏`-21.11%`，作为路径运气拒绝。
- 最终artifact
  `/mnt/e/qount_data/qount/artifacts/experiments/20260718T155058Z-periodic-allocation-v02/mini_trend_periodic_allocation.json`
  SHA-256 `0bd6d491...fc`、manifest content hash `aefb001a...49`。Mac/WSL聚焦测试均`4 OK`；不接Base、
  paper或live。

### Direct Binance key diagnosis separated credential failure from proxy routing

- VPS在unset全部代理变量并显式bypass环境代理后，仓库外production egress的geo为PH，Binance UM公共API
  正常。保存的key/secret均存在且长度64；`apiRestrictions`返回`-2008 Invalid Api-Key ID`，spot账户和UM
  balance返回`-2015`。因此不是美国代理路由，Binance生产端不认识当前Key ID；可能已删除/轮换、复制错误，
  或来自testnet/另一账户。
- 下一必要条件是新建生产Binance key，只开读取与USD-M交易、禁提现、IP白名单使用仓库外production inventory。本轮只做
  私有只读诊断，没有下单、撤单、转账、改杠杆或保证金模式；cron/live仍关闭。
- 本轮最终验证：Mac全仓`1228 OK`，唯一告警仍是既存`cta_data.py` UTC deprecation；periodic/TradFi聚焦
  各`4 OK`，全量`compileall`、三组CLI help、全部Bash语法、`git diff --check`和已知凭据/代理URL扫描通过。
  外置盘两个最终artifact SHA-256已从WSL回读匹配；WSL scratch只剩marker和空`state/`，Mac测试生成的6个
  临时research目录已定点删除，Mac `state/`恢复约12KiB。

## 2026-07-18

### Owner superseded the pilot risk contract; paper now records two profit shadows

- Owner把试点冻结为300 USDT、30天，并明确取消账户级单日止损；逐币3xATR吊灯、3根完成日线冷却、35%
  deadband继续生效，唯一账户级收益路径停机线是从试点峰值计算的10%累计回撤。该规则覆盖下方较早的
  `200 USDT / 2%日损 / 5%回撤`历史记录，不回写旧证据。
- 真钱控制仍是Base v0.2；消费历史的300 USDT对比中，全局2.0%风险档收益最高但弱市和30天尾部风险更差，
  因此只作为首选收益shadow，Funding Veto作为次级shadow。两者都不得生成或改变真钱订单。
- `pilot_paper.py`升为v0.3：同一完整日线并行重放三条路径，并在Base hash-chain journal的
  `execution_state.shadow_paths`保存两条shadow的权益、目标权重、gross、费用、funding、止损/冷却状态和
  累计回撤；报告显式写`controls_live_orders=false`。Base达到10%线时仍按合同停止并要求flatten，shadow
  自身越线只记录，不成为Base订单输入。
- 聚焦标准库测试`20 OK`，其中显式覆盖“无daily halt、10%累计回撤halt”、影子不控单、journal追加/防篡改、
  preflight与dry fail-closed；Mac全仓`1220 OK`，唯一告警仍是既有`cta_data.py` UTC deprecation。Mac/WSL
  paper v0.3聚焦均`5 OK`，`compileall`、Bash语法、CLI、敏感字面值扫描和`git diff --check`通过。
- WSL复用外置盘现有229根canonical日线离线生成当前artifact
  `20260718T102907Z-um-pilot-paper-v03`；最新日`2026-07-17`早于`2026-07-19`冻结起点，仍为0 pair/day/row、
  `await_paper_inputs`、`live_orders_allowed=false`。artifact SHA-256为`43c085d9...6e23`，manifest content
  hash为`c024dac1...d213`。已回读JSON/hash/manifest，删除被替代的paper v02和中间v03，只保留最终v03；
  WSL marker保护scratch再次清空。
- VPS只读复核仍为0 cron/0交易进程；公共TOP3通过但私有key返回`-2015`，preflight 13项阻断、dry 0个
  would-place order。没有调用订单、取消单、转账、杠杆或保证金模式写接口。

### One-month small-capital live pilot requested; readiness blocked fail-closed

- Owner提出执行一个月小资金实盘。没有恢复旧X4/C×D，而是新增MiniTrend独立readiness合同：真钱只选
  Base v0.2，TOP3 UM long/cash日线，`capital<=200 USDT`、1x逐仓、one-way、gross<=1、每日单批；
  Funding Veto只做shadow。2%日损或5%试点回撤触发flatten+halt。
- VPS只读审计确认生产cron自7月11日停用且没有qount交易进程；旧状态仍显示shorting/2x，旧`.env`通用
  live guard仍armed，不能当成新授权。带旧显式代理的公共/私有预检全部失败；VPS直连公共Binance正常，
  说明是代理路由故障。绕开代理后time/exchangeInfo通过，但旧key返回`-2015`，余额、仓位、one-way和1x
  逐仓无法审计。
- `exchange_utils.build_exchange`新增默认关闭的`QOUNT_EXCHANGE_BYPASS_PROXY`，用于新试点明确选择直连，
  不改变现有环境。新增`live_pilot.py`、readiness CLI与测试，合同强制无short/carry/leverage boost、无提现key、
  单批幂等和未知状态halt。
- 首版审查发现遗漏执行手册已有的7天dry-run和独立runtime验证门；readiness升为v0.2并fail closed补齐。
  最终artifact `20260718T091310Z-um-live-pilot-readiness-v03`为`blocked_live_pilot_readiness`，17项blocker、
  readiness hash `1e9f1dfc...82821`、manifest content hash `24a03cf1...c90a6`、
  `live_orders_allowed=false`。带row/chain hash的append-only每日journal重复决策日或篡改会fail closed；本轮
  未部署VPS、未改生产env、未调用订单接口。
- 最终readiness与manifest已从外置盘回读，旧v02目录已删除，只保留上述v03。Mac全仓`1205 OK`、WSL
  readiness/journal与exchange route聚焦`16 OK`，`compileall`、Bash语法、凭据/代理字面值扫描和
  `git diff --check`通过；`x4_live_daily.sh`命中只是环境变量示例引用。Mac测试临时artifact已定点删除，
  WSL marker保护scratch已清空，Mac `state/`恢复约12KiB。

### Independent UM paper runtime added; first canonical run has zero eligible days

- 新增`pilot_paper.py`和`mini_trend_um_paper.py`，只实现order-free paper：Base v0.2从200 USDT现金启动，
  200根历史只作signal warmup；只有连续TOP3日线和每币每日3次funding完整前缀才能运行。CLI不接私有API，
  不包含live模式或订单调用。
- paper replay复用冻结3xATR吊灯、3根冷却、35% deadband、gross<=1和实际UM filters；2%日损或5%试点
  回撤触发halt。每日行写钱包/权益、目标与实际权重、paper意图/结果、funding/费用、执行状态与risk flag，
  复用row/chain hash；replay hash变化或非前缀追加会fail closed。
- 首个canonical artifact `20260718T093019Z-um-pilot-paper-v01`读取229根共同日线，最新日仍为
  `2026-07-17`，早于冻结paper起点`2026-07-19`；结果`await_paper_inputs`、0 pair/0 paper day/0 journal row、
  `live_orders_allowed=false`。manifest content hash `2b4dd60c...19ece`。未部署VPS/timer，dry/live runtime
  仍未实现或验证，readiness仍为17项blocker。
- `run_variant`只增加默认不变的可选初始本金注入，旧研究调用仍使用400 USDT。Mac专用paper测试`5 OK`、
  关联回归`12 OK`，WSL paper/shadow/readiness逐模块`5/4/7 OK`；Mac全仓升级为`1210 OK`，唯一告警仍是
  既存`cta_data.py` UTC deprecation。

### WSL UM shadow inputs advanced to July 17; current-month funding transport remains blocked

- 新增`futures_shadow_inputs.py`与WSL CLI，把公开网络刷新和冻结Funding Veto shadow回放分离。Binance
  Vision使用WSL直连；可选标准HTTP(S)代理只能由仓库外环境变量注入，artifact不记录URL/token。本轮没有
  使用Mac/VPS下载，也没有使用苏菲家宽代理。
- 首次canonical刷新复用外置盘已迁移的2025-12..2026-05不可变缓存，直连补齐2026-06 TOP3 UM日线/funding
  月包和2026-07-01..17日线。最终`datasets/binance_um_shadow/v1`为`93 files/80,144 bytes`，manifest
  content hash `8dcce911...13746`，刷新输入data hash `abdd8736...8c207`；archive unavailable=0。
- 当前月funding官方REST从WSL直连全部超时，完整symbol `0/3`，刷新artifact
  `20260718T081136Z-um-shadow-input-refresh-v02`明确 verdict=`await_complete_shadow_input_transport`。
  刷新器逐日验证每币至少3次结算，空响应不能通过；没有生成伪快照或按0补成本。
- 冻结shadow CLI新增离线合并append-only funding快照能力。离线复跑artifact
  `20260718T080849Z-um-funding-veto-shadow-forward`把TOP3共同最新日推进到`2026-07-17`；因合同起点是
  `2026-07-19`，仍为0个forward pair、`strategy_results_evaluated=false`、无evaluation/journal，
  verdict=`await_shadow_forward_data`。这不是策略失败或收益结果，累计策略trial保持143。
- dataset/refresh/shadow manifest均已生成；环境锁`20260718T081243Z-qount-compute.json`的manifest/code
  bundle hash为`03be436e...7823`/`ff78f5e8...bbc6`。Mac/WSL聚焦测试均为`29 OK`，后续完成全仓验证并清空
  marker保护的WSL scratch。

### Base episode attribution completed; three-bar signal-exit cooldown rejected

- 在任何新策略结果前先冻结描述性episode合同，`trial_count=0`、累计trial仍为142。episode定义为单币目标
  权重从0变正到再次归零；每根日线按当时组合权益精确分摊价格PnL、holding-day funding和入场/调仓/退出
  成本，MFE/MAE使用持仓期间outcome bar高低点。预登记
  `20260718T060748Z-base-episode-preregistration`合同哈希`152c804e...2f119`，manifest content hash
  `1c5ae622...3658`。
- 77个episode全部闭合，组合净利润`266.02158322 USDT`、归因`266.02158324 USDT`，差
  `0.00000002 USDT`；价格/funding/成本分别为`+328.72644972/-34.36676676/-28.33809974 USDT`，分量
  恒等式误差为0。Base全窗仍为`+66.5054%/Sharpe 0.90277/maxDD 17.2845%`，相对BTC/TOP3 1x的beta
  residual compound为`+43.2785%/+40.4218%`。
- 31个吊灯退出episode贡献`+403.6133 USDT`，22/31盈利，中位持有43日、中位MFE `24.6316%`，且四个
  有样本年份净PnL全正。38个单币趋势/配置退出贡献`-56.6102 USDT`，11/38盈利，中位持有4日；8个
  SMA200总闸退出全部亏损、合计`-80.9815 USDT`，但未过预登记10例门。1-7日和8-30日持仓分别亏
  `-101.6869/-77.9728 USDT`，31-90日和>90日分别赚`+251.2261/+194.4551 USDT`。因此不收紧3xATR，
  不做时间止损。
- episode机制筛选只保留单币趋势/配置退出。36个此类退出后仍有下一episode，其中12次在已有3日止损冷却
  周期内重入，后续仅2次盈利、合计`-22.02423192 USDT`。episode首次/复跑删除时间戳与输出路径后的规范化
  SHA-256同为`55984ca5...66c7`；最终复跑`20260718T061138Z-base-episode-attribution-rerun` manifest
  content hash `bf806d24...ebf2`。
- 据此只预登记1个新策略trial：总闸仍risk-on且单币趋势退出时，复用现有3根完成日线止损冷却，SMA、吊灯、
  deadband、risk target、gross和成本口径全不变，不扫冷却天数。预登记
  `20260718T061740Z-signal-exit-cooldown-preregistration`合同哈希`12bd8d99...5b920`，manifest content hash
  `687ccbf1...19cb`，累计trial从142增至143。
- 候选触发34次signal exit、阻止20个symbol-bar重入，把episode `77→72`、订单`261→252`、decision batch
  `187→185`、交易成本`28.3381→27.2536 USDT`。收益`+66.50539581%→+66.80462087%`、Sharpe
  `0.90276990→0.90787557`、maxDD `17.28450833%→17.27738693%`，TOP3 beta residual compound
  `+40.4218%→+40.7890%`。但改善主要来自2021/2023，2025反而少`0.6720pp`。
- 配对20日块Bootstrap的终值收益/Sharpe/更低maxDD胜率仅`58.96%/64.42%/55.88%`，三条预登记稳健门
  全失败，最终`13/16`通过，verdict `reject_signal_exit_cooldown_ablation`。首次/最终复跑规范化SHA-256
  同为`1b1fb7c7...a9e1`；最终artifact SHA-256 `0f4edb59...c58e`、report manifest content hash
  `1a87b5e9...e5f3`。WSL环境锁`20260718T062306Z-qount-compute.json`的manifest/code bundle hash为
  `1e027a5c...1054`/`61817b67...5270`。
- 结论：3日冷却的经济方向合理，但现有历史优势太小且不稳定，不能进入forward/paper/live，也不允许扫
  2/4/5日救援。正式策略仍是Base v0.2，Funding Veto仍只是首选历史候选。
- 验证与清理完成：Mac全仓`1192 OK`，Mac/WSL episode、信号退出冷却和回测变换聚焦各`14 OK`；Mac全量
  与WSL聚焦`compileall`、两端CLI help、Bash语法、已知凭据扫描和`git diff --check`通过。Mac测试生成的
  6个临时artifact目录已按时间戳删除，WSL marker保护的scratch已清空，Mac `state/`恢复约12KiB；唯一
  告警仍为既存`cta_data.py` UTC deprecation。未访问VPS/private API、未下载新数据或使用代理。

### H.4.1 marginal strong-bull boost veto rejected

- 先核对预测语义：保留的H.4.1 RF是TOP3等权指数未来60日收益的时间序列模型，每个决策日只有一个分数，
  不能用于BTC/ETH/BNB横截面轮动。为避免前轮长期闸门继续损伤Base，只预登记1个新trial：现有Funding
  Veto和Stop-Latch先运行；只有原本仍可使用strong-bull 2.0%风险档时，若年度fold OOS标准分数`<=0`，
  当日退回Base 1.5%。不允许低于Base、改SMA/止损/deadband、扫阈值或读取`actual`目标。
- 预登记在策略结果前写入
  `20260718T054840Z-h41-boost-veto-preregistration/mini_trend_h41_boost_veto_preregistration.json`，
  contract hash `6cb8f926...94642`，绑定1205个`2023-01-01..2026-04-19` OOS分数、H.4.1 audit、UM rules和
  Funding Veto合同。manifest content hash `941fa2c2...beab`；累计trial从141增至142。
- 相同OOS覆盖期内，Base为`+68.26966286%/Sharpe 1.19340353/maxDD 17.27560245%`，Funding Veto参考为
  `+90.36206739%/1.26015785/18.10164617%`。449个funding/stop之后仍可boost的强牛日中，宏观否决303个；
  候选降到`+65.07240229%/1.09500905/19.26371432%`。相对参考少赚`25.28966510pp`、Sharpe下降
  `0.16514880`、maxDD恶化`1.16206815pp`；相对Base也少`3.19726057pp`且回撤恶化`1.98811187pp`。
- 2023/2024/2025相对Funding Veto年度收益差为`-9.1349/-8.8536/-0.3028pp`。候选相对TOP3 1x的beta
  residual compound只有`+25.5054%`，低于参考`+41.0275%`。配对20日块Bootstrap的终值/Sharpe/更低
  maxDD胜率为`1.54%/6.90%/63.40%`，最终`8/14`门通过，verdict
  `reject_h41_boost_veto_ablation`。
- 首次报告`20260718T054935Z-h41-boost-veto-ablation`与最终复跑
  `20260718T055103Z-h41-boost-veto-ablation-rerun`删除时间戳/输出路径后的规范化SHA-256同为
  `5720cb3d...fb8d`。最终artifact SHA-256为`9038b5b4...a5fad`，report manifest content hash
  `566bdaa9...71f8`。WSL环境锁`20260718T055231Z-qount-compute.json`的manifest/code bundle hash为
  `fe69531a...cc3b`/`5dfdd3b8...07ec`。
- 结论：H.4.1在全时间轴有60日排序信息，但在技术面已经筛出的强牛子样本中不能管理边际风险；自然零点仍
  否决过多主升浪，并通过权益/deadband/latch路径扩大损耗。该机制关闭，不做分位、阈值、持有期或投票
  rescue。Base v0.2仍是正式选择，Funding Veto仍只是首选历史候选，不恢复paper/live。
- 验证与清理完成：Mac全仓`1185 OK`，Mac/WSL宏观boost、funding、event和回测变换聚焦各`23 OK`；
  Mac全量与WSL聚焦`compileall`、两端CLI help、Bash语法、已知凭据扫描和`git diff --check`通过。Mac测试
  生成的6个临时artifact目录已按时间戳删除，WSL marker保护的scratch已清空，Mac `state/`恢复约12KiB；
  唯一告警仍为既存`cta_data.py` UTC deprecation。未访问VPS/private API、未下载新数据或使用代理。

### H.4.1 event-driven realization rejected after preregistered ablation

- 为直接检验“慢信号只能事件驱动兑现”的建议，在读取任何策略结果前预登记3个固定trial。合同只允许
  H.4.1 `release_date + 1d`可见状态、4周资产变化的经济零阈值，以及Base新开仓/SMA200总闸退出两个既有
  事件；1.5%风险目标、35% deadband、3xATR吊灯、3日冷却、gross<=1、no-carry/no-short均冻结。
  preregistration为`20260718T051752Z-h41-event-preregistration`，contract hash
  `3080b17d...a2a45a2c`，累计trial从138增至141。
- 控制仍为收益`+66.50539581%`、Sharpe `0.89822201`、maxDD `17.28450833%`。收缩期阻止新开仓在
  633根日线上介入、阻止1,358个symbol entry，候选只有`+1.72233341%/0.09040619/8.43238764%`；
  收益损失`64.7831pp`，Bootstrap Sharpe胜率仅`5.64%`。H.4.1收缩符号覆盖了QT的大部分年份，不能作为
  趋势策略的长期开仓许可。
- 扩张期延迟总闸退出只介入2根日线/4个symbol exit，得到
  `+64.08873436%/0.86420311/17.23845709%`。它满足3pp收益代价上限，但Sharpe下降、maxDD仅改善
  `0.0461pp`，Bootstrap Sharpe/maxDD胜率仅`16.46%/20.56%`。双确认受收缩闸门主导，收益仅
  `+0.34077807%`。三项最终均拒绝，verdict `reject_h41_event_gate_ablation`。
- 最终确定性复跑artifact为`20260718T052500Z-h41-event-ablation-rerun`，report manifest content hash
  `f36a1e63...520a`；与首次运行的全部报告指标一致。WSL环境锁
  `20260718T052600Z-qount-compute.json`绑定manifest/code bundle hash
  `71ffd6cf...5e36`/`cd96da83...c5c5`。全部结果仍是`consumed_historical_discovery_pool`。
- 结论：事件驱动只解决重复调仓，不能把一个持续过久的排序特征变成有效二元交易状态。H.4.1 4周变化仍
  保留为60日排序信息，但不进入Base仓位、开仓许可或退出闸门；不再扫描10%/90%分位、5/10年窗口、
  20/45日冷却、风险档或投票权重救援。Base v0.2与Funding Veto历史候选层级均不变，不恢复paper/live。
- 运维复核定位到Mac collector文件会重现的根因：旧`com.qount.alpha-collector-offload` LaunchAgent仍以
  30分钟间隔运行，累计105次。已`bootout`并删除plist；外置副本完成SHA/JSON/gzip回读后只删除Mac重复
  文件。当前服务与plist均不存在，Mac `state/`约12KiB。未访问VPS/private API、未下载新市场数据。
- 验证完成：Mac全仓`1180 OK`，Mac事件闸门/回测变换/存储聚焦`13 OK`、WSL聚焦`11 OK`；Mac全量及WSL聚焦
  `compileall`、两端CLI help、相关Bash语法、已知凭据扫描和`git diff --check`通过。全仓测试生成的6个
  临时Mac research artifact目录已按测试前清单删除，WSL marker保护的scratch已清空；唯一告警仍为既存
  `cta_data.py` UTC deprecation。

### Point-in-time H.4.1 macro round completed; prediction retained, strategy rejected

- 新增Coin Metrics append-only vintage采集器。首个真实快照直接由WSL写外置盘，source date
  `2026-07-17`、retrieved at `2026-07-18T04:12:05Z`、snapshot hash
  `f83b288f...d6dfb`；provider没有publication timestamp，因此本地UTC检索时间是证据边界。raw chain
  manifest为`1 file/463 bytes`、content hash `fe7bb1e9...7c0c4`，不回填为历史vintage。
- Federal Reserve H.4.1 source G0覆盖三种官方档案布局：2021-01-07旧`H41.TXT`、2021-03-04独立
  `h41.htm`、2025-01-02内嵌HTML。修复了HTML标签把`Wednesday`和日期粘连导致列日期误判，以及过渡期
  索引页/报表页分离问题；三个probe的观察日/总资产分别为`2021-01-06/7,334,809`、
  `2021-03-03/7,557,524`、`2025-01-01/6,852,491` USD millions。
- WSL直连下载`2021-01-07..2026-07-16`共`289/289`个官方release，生成276个滞后一日可用周特征；
  layout为旧TXT/linked HTML/inline HTML=`8/108/173`，发布滞后1/2/5日=`278/10/1`，0重复观察日、
  0未来join。raw tree为`406 files/252,249,757 bytes`、content hash `d0f939db...4592`。data hash最初
  错误包含cache-hit运行状态，修正后两次全缓存重建均为`8af65a47...cb02`。
- 固定三个单宏观特征trial全部使用原60日目标/365日滚动RF/model seed `20267083`。控制rank IC/
  高低组差/bootstrap为`0.167001/7.629963pp/79.55%`；`fed_assets_4w_change_pct`为
  `0.202639/12.899478pp/95.17%`且8/8通过，`fed_assets_4w_acceleration`为
  `0.180153/8.583904pp/84.06%`且8/8通过，13周变化因IC降到`0.155576`而7/8拒绝。两次确定性复跑
  逐值一致，累计trial从131到134。
- 唯一跨源融合trial把4周H.4.1与`hashrate_z90`同时加入，得到
  `0.189245/12.205835pp/93.24%`；虽优于算力父模型，却三项均低于4周宏观父模型，5/8拒绝。随后只对
  4周宏观复用既有三档downside-only风险规则，仍0/3：最佳`z<=-0.5 -> 1.0%`把Sharpe
  `1.1934 -> 1.2772`、maxDD改善`0.863pp`，但收益`68.27% -> 64.95%`、少`3.323pp`，略超冻结3pp门，
  8/9拒绝；不改成3.5pp救援。累计trial为138，Base v0.2 1.5%仍是正式选择，所有宏观结果仍是
  `consumed_historical_discovery_pool`，不接forward/paper/live。
- 最终artifact为`20260718T044100Z-h41-feature-audit-v03-predictions`、
  `20260718T045000Z-macro-onchain-fusion-v02`和`20260718T044137Z-h41-strategy-ablation`；manifest content
  hash分别为`0aaafcda...f8eb7`、`8b5ba68c...a8d5d`、`66e2016a...f94a0`。WSL环境manifest
  `20260718T045100Z-qount-compute.json`的manifest/code bundle hash为
  `752f2b59...b139`/`94ccc633...5ea0`。发布后WSL scratch已清空；Mac残留collector经两文件投影
  SHA/gzip/JSON回读后删除，`state/`现约12KiB。验证为Mac全仓`1174 OK`、Mac/WSL本轮聚焦各`22 OK`，
  `compileall`、CLI help、Bash语法、凭据扫描和`git diff --check`通过；唯一告警仍是既有`cta_data.py`
  UTC deprecation。未访问VPS/private API、未使用代理、未触发订单。

### Windows external storage and WSL compute topology migration completed

- Owner固定新职责：Mac负责研究设计、代码主仓、文档、轻量测试和编排；Windows外置ExFAT盘
  `E:\qount_data\qount`保存大数据、最终artifact、环境锁和备份；WSL
  `/home/alyaloale/Code/qount`使用7945HX 32线程与RTX 4060 8GB做大型CPU/GPU计算；VPS只保留冻结策略和
  最小runtime state。A10证据已回收，本地4060成为默认GPU，云GPU只在实测显存或吞吐不足时临时租用。
- 外置根已建立`datasets/artifacts/environments/manifests/migrations/runtime-backups/scratch`。既存23G L2
  归档已在同一盘原子移动到`datasets/l6_l2_archive`，旧`qount_l2_archive`目录不再保留。ExFAT在WSL中是
  drvfs/9p，只保存大文件和不可变发布物；活跃SQLite、venv、训练小文件与中间张量留WSL ext4 scratch。
- WSL旧`state/`已按内容manifest迁移并分类到外置盘：`6974 files/1,280,658,614 bytes`，content hash
  `fab49809...c412`。Mac旧`state/`为`11,968 files/8,101,349,852 bytes`，content hash
  `2bdf6c62...74c`。两侧均完成源/目标manifest一致性与外置盘回读`cmp`，随后删除本地大副本；Mac保留空
  `state/`，WSL `state`只指向`/home/alyaloale/.cache/qount-compute/state`。
- Mac/WSL旧runtime展开备份因ExFAT稀疏文件膨胀到约735MiB，已压成
  `runtime-backups/archives/{mac,wsl}-legacy-20260718.tar.gz`，大小`10,130,588/8,329,682 bytes`；两包的
  `gzip -t`、`tar -tzf`和SHA-256校验均通过后删除展开副本，`runtime-backups`最终约18MiB。
- VPS完整旧state另存为`migrations/20260718/sources/vps/vps-state-20260718.tar.gz`（`4,684,915 bytes`，
  `gzip -t`通过）。只删除明确非runtime的research klines、paper和deploy backups，VPS源从约28MiB缩到
  约16MiB；无qount进程且crontab仍停用，未触碰订单、私有Binance API或恢复live。
- WSL计算环境已补齐NumPy/SciPy/scikit-learn/LightGBM/XGBoost/hmmlearn/PyTorch/pandas/ccxt；Torch
  `2.13.0+cu130`识别RTX 4060，2048矩阵CUDA smoke全部有限。环境manifest写入
  `environments/wsl-7945hx-rtx4060-20260718.json`，manifest/code bundle hash为
  `caf95857...519e`/`463bf57b...20e`。安装显式清除代理变量并使用阿里云PyPI镜像，未使用苏菲家宽代理。
- WSL旧无git代码区已按计算职责一次性重铺，只同步`deploy/docs/prompts/scripts/src/tests`并保留`.env/.venv`；
  后续只在计算接口或依赖变化时更新，不把WSL当Mac持续镜像。WSL聚焦测试`9 OK`，本地全仓`1143 OK`；仅有
  既存`cta_data.py` UTC deprecation warning。
- 后台可靠性也经实践修正：远程启动的WSL user-systemd/tmux会随`wsl.exe`退出被回收；macOS临时
  `launchctl submit`会被推断keepalive并循环重启失败任务。长任务固定由Mac detached `screen`持有前台
  SSH/`wsl.exe`，WSL `wsl_long_job.sh`负责flock、日志和退出码；完成状态只看退出码、manifest和读取验证。

### MiniTrend regime ML, causal HMM and deterministic GRU discovery completed

- 新增`regime_ml.py`与CLI：用Mac已有TOP3 USD-M日线/funding构造1765行数据，窗口
  `2021-07-20..2026-05-19`，30日/1.0σ triple-barrier的bear/bull/range为`401/526/838`，28个特征均为
  point-in-time；2023-2026年度扩展Walk-Forward按label结束日purge，四折检查全过。dataset artifact为
  `state/research_runs/20260717T180206Z-mini-trend-regime-ml-discovery/mini_trend_regime_ml_discovery.json`，
  contract/data hash=`45d21773...79c`/`0fd5bba6...09de9`，Mac/A10数据分布与hash一致。
- 完整tabular/HMM artifact为
  `state/research_runs/20260717T181512Z-mini-trend-regime-ml-discovery/mini_trend_regime_ml_discovery.json`。
  Logistic/HGB/LightGBM/XGBoost的balanced accuracy为`0.391626/0.353053/0.356775/0.338702`，平均Brier
  uplift为`-0.207976/-0.511406/-0.417971/-0.316735`，全部不可用。因果前向HMM为`0.358605`和
  `+0.013493`，Brier/log-loss均3/4折改善，但2024硬分类全为range、2025-2026不预测bear，只能当弱概率特征。
- 模型trial 2固定加入unweighted Logistic、HMM+训练先验50/50、HMM状态后验增广Logistic及HMM+Logistic
  50/50，不扫描权重。artifact
  `state/research_runs/20260718T010000Z-mini-trend-regime-ml-calibration-discovery/mini_trend_regime_ml_discovery.json`
  的平均Brier uplift依次为`-0.177369/+0.009683/-0.183699/-0.027013`；原HMM仍最好，2023仍为负，所有
  新候选停止，不连接风险档/仓位。
- 新增固定60日、32 hidden、单层GRU与CUDA deterministic训练。首轮artifact
  `state/research_runs/20260717T182800Z-mini-trend-regime-neural-discovery/mini_trend_regime_neural_discovery.json`
  的balanced accuracy/macro-F1=`0.379848/0.303852`，Brier/log-loss uplift=`-0.029635/-0.040234`，仅
  2/4折改善，总训练`2.214s`、峰值显存约`133MB`。第二次CUDA复跑artifact
  `20260718T000000Z-mini-trend-regime-neural-determinism`除wall time外规范化hash一致，四折model-state hash、
  best epoch和validation loss逐项相同；失败是可复现结果，不继续LSTM/TCN/Transformer扫参。
- 新增可测试的研究计算环境manifest生成器。A10 artifact
  `state/research_runs/20260718T020000Z-research-gpu-environment/research_gpu_environment.json`记录Alibaba Cloud
  Linux 4、8 CPU、29.1GiB RAM、NVIDIA A10、Torch `2.12.1+cu130`、CUDA 13.0、42项pip freeze、数据与代码
  hash；manifest hash=`4fbb9c2f...fa5ea`。节点未接收生产`.env`、Binance私钥或live state。
- 全程复用已有缓存，未下载市场数据、未访问生产VPS/private API、未下单。验证：本地ML/GRU/manifest聚焦
  `7 OK`，MiniTrend warnings-as-error `82 OK`，全仓`1141 OK`；只有既存`cta_data.py` UTC deprecation warning。
  下一步先做HMM OOS概率的可靠性与经济条件审计，不先用动态风控包装分类结果。

### Regime economic audit, rolling adaptation, and on-chain source round completed

- 新增HMM经济审计/目标敏感性、直接经济回归、DVOL增强、滚动适应和固定确认模块。原30日HMM风险分数与
  未来TOP3收益Spearman为`-0.175822`、高低组差`-3.3042pp`；12个HMM目标0保留。Ridge/HGB/RF/
  LightGBM/XGBoost × return/drawdown × 10/20/30/60日共40格0保留；扩展到2026-06的BTC/ETH DVOL完整
  `46,008`小时后，DVOL增强40格仍0保留。
- 24格滚动适应矩阵只保留`h60_train365_base_random_forest`。固定确认artifact
  `artifacts/experiments/20260717T221830Z-rolling-confirm`为7/7：rank IC `0.167001`、60日差
  `+7.629963pp`，30/60/90日区块正差概率`84.66%/80.15%/78.63%`；三个p05仍负。3个冻结的只降风险
  trial全部拒绝，最佳少赚`12.216pp`仅换来`0.878pp` maxDD改善，不能连接策略。
- WSL直连Coin Metrics官方社区API；未使用代理，原始响应直接写
  `datasets/coinmetrics/btc_asset_metrics_daily/v1/raw/2020-01-01_2026-06-30.json`。冻结免费字段为MVRV、
  活跃地址、交易数、算力、交易所流入/流出；SOPR、Realized Cap、NVT和LTH供给返回403，未用近似替代。
  dataset artifact `20260717T223559Z-onchain-dataset`有2373日、coverage 1.0、data hash
  `f1631c7b...75f6`，全部特征滞后1日。API无历史vintage，因此明确不是point-in-time promotion证据。
- 首版链上feature audit误把2021-2022计入年度fold，artifact `20260717T223636Z`只作工程中间件。修正后的
  v0.2 `20260717T223827Z-onchain-feature-audit-v02`严格只用合同2023-2026折；7个固定方向trial中只有
  `hashrate_z90`通过5/5：rank IC `0.159730`、高低组60日差`+9.959073pp`、bootstrap正差`98.95%`、
  p05 `+2.009506pp`。MVRV只过4/5，不拼入下一模型。
- 唯一新增模型trial在原60日/365日滚动RF上加入算力，artifact
  `20260717T224144Z-onchain-rolling-model`通过9/9：rank IC `0.179447`、差`+9.252003pp`、bootstrap
  `85.40%`，相对原模型提升`+0.012446/+1.622041pp/+5.40pp`。但2023折仍负且RMSE均值仍差于常数，
  定位为ranking signal而非幅度预测。
- 同一3个冻结风险规则的策略artifact `20260717T224435Z-onchain-strategy-ablation`仍0/3。最佳
  `z<=-0.5 -> 1.0%`把Sharpe `1.1934 -> 1.2552`、maxDD改善`0.862pp`，但raw return少`4.795pp`，超过
  预定3pp代价，8/9拒绝；BTC/TOP3 beta-residual compound各小幅改善约`0.31/0.11pp`也不能覆盖raw gate。
  不把门改成5pp，不用2023后启用等后见规则救援。累计相关trial为131。
- 确定性复跑：滚动确认/链上RF最大浮点差为`1.55e-15/1.11e-15`且结构完全一致；链上dataset data hash
  完全一致，策略逐值一致。关键manifest content hash依次为rolling confirm `a73b42eb...9c6c`、原模型风险
  ablation `83bbf258...2a5`、链上dataset `b50aac7f...e6eb`、v0.2 feature audit `a88e8c28...f6f0`、
  链上模型 `5c28f2c2...9f90`、链上策略 `198506bd...ddc9`；raw dataset tree为`e1614707...1f4a9`。
- 最新WSL环境manifest `environments/wsl/20260717T225720Z-qount-compute.json`的manifest/code bundle
  hash=`36a51cbe...63994`/`3a473573...f3e68`；普通`source`
  `deploy/wsl/qount-compute.env`后LightGBM 4.6.0可导入。发布完成后marker保护的`clean-scratch`把WSL计算
  暂存从约42MiB清空，只留marker和空state；Mac/VPS没有链上数据副本，生产cron/private API/订单未触碰。
- 最终验证：Mac新增研究聚焦`17 OK`、全仓`1160 OK`，WSL新增研究聚焦`17 OK`；`compileall`、Bash语法/
  环境导出、skill官方`quick_validate.py`、凭据字面量扫描和`git diff --check`均通过。全仓仅有既存
  `src/qount/cta_data.py`的`utcfromtimestamp` deprecation warning。
- 最终Mac空间复核发现迁移后仍残留一份旧collector压缩段`178,026,679` bytes。外置盘同路径副本的字节数
  与SHA-256 `4b8d1cef...757f`完全一致，且`gzip -t`通过；按删除门移除Mac源和本轮全测生成的临时
  research-run后，本轮再次核验并把Mac `state/`收敛到约12KiB，只保留11KiB运维日志和零字节锁。

### Personal research sandbox reopened; stale skill guardrails revised

- Owner明确项目是个人实验量化，原`qount-doc-autopilot`把promotion规则前置成了research禁令。已更新仓库外
  `/Users/alyaloale/.codex/skills/qount-doc-autopilot/SKILL.md`：默认`research_sandbox`允许复用已有历史做
  标签、特征、参数搜索、动态ATR/deadband、HGB/LightGBM/XGBoost、HMM和神经网络；复用窗口仍标discovery、
  记录trial和泄漏检查。只有`promotion_review`和`paper_live`维持冻结候选、独立证据与显式授权要求。
- 同步更新skill的`agents/openai.yaml`和`references/ops-reference.md`，加入独立GPU研究节点：不复制生产`.env`、
  Binance私钥或live state；默认单A10 24GB/8 vCPU/30-32GiB RAM即可，训练artifact必须带数据/代码/环境hash。
- 官方`quick_validate.py`最初因本机缺`PyYAML`无法启动；本轮改用一次性`uv --with pyyaml`环境执行，结果
  `Skill is valid!`，没有向项目venv写依赖。此前系统Ruby YAML的frontmatter/命名/描述检查也通过。
- 原计划实际完成度：技术三阶段规则、Stop-Latch、Funding Veto及历史审计已完成；统一信号矩阵、动态
  ATR/deadband、宏观评分、MiniTrend日线ML、链上因子、HMM/Markov和叙事标签尚未实现。新版路线先用已有
  1776日构造因果状态+30日triple-barrier未来标签和特征矩阵，再跑tabular、HMM与小型sequence模型；全部先属
  personal discovery，不因旧residual-trend失败而禁止新目标实验，也不自动进入paper/live。

### Funding-veto dual-state shadow forward hardened before eligible data

- 初版v0.1预登记/0根freshness（`20260717T161203Z`/`20260717T161255Z`）发现一个forward输入完整性缺口：
  月内funding缓存未齐时，风险选择器虽会退回base风险，但收益引擎会把缺失结算合计为0。两份artifact均无
  eligible pair、无evaluation/journal且`strategy_results_evaluated=false`；保留审计但在首根结果前由v0.2
  supersede，未消费future OOS。
- 当前v0.2预登记
  `state/research_runs/20260717T162621Z-mini-trend-um-funding-veto-shadow-forward-preregistration/mini_trend_um_funding_veto_shadow_forward_preregistration.json`，
  contract/protocol hash `3c6fe31f...82ea69` / `e0f525a9...52fad4`。它仍绑定同一UM base v0.2、状态衰减
  artifact和rules，起始日、资金、策略参数及晋级门不变；200根历史只做信号warmup，两路径从400 USDT
  全现金、空吊灯/冷却、未锁定latch启动，禁止携带已消费历史交易状态。
- v0.2只评估从起始日开始价格连续、且每个决策日与持有结果日TOP3各至少3次funding结算的完整前缀；缺失
  funding不再按0成本进入净值。CLI `--end-month`默认随UTC当前月滚动，但`_offline_only`继续拒绝网络。
- 新journal逐日保存Stop-Latch与Funding Veto两套权益、gross/price/funding/cost/net、完整execution state、
  各自state hash、row hash和前向chain hash；首次状态同步后仍持续记录。实现只调用同一确定性`run_variant`，
  不接paper/live/order路径。
- 固定复核门为60个完整forward pair、双路径各10 active、至少1次veto、candidate maxDD `<=15%`、无gap、
  candidate funding coverage=1.0、filter coverage=1.0、0 duplicate/reentry、journal coverage=1.0。没有
  “candidate必须跑赢”门；全过也只允许`review_shadow_forward_evidence`，`paper_or_live_allowed=false`不变。
- v0.2 freshness artifact
  `state/research_runs/20260717T162632Z-mini-trend-um-funding-veto-shadow-forward/mini_trend_um_funding_veto_shadow_forward.json`
  只读本地缓存，三币共同200根为`2025-12-01..2026-06-18`，起始日后0根输入/0个结果pair，未创建evaluation
  或journal，`strategy_results_evaluated=false`，verdict=`await_shadow_forward_data`。未下载、未访问VPS/private
  API、未触发订单，也未消费future OOS。
- 验证：新增shadow-forward `4 OK`，MiniTrend全聚焦warnings-as-error `76 OK`，本地完整 `1134 OK`；完整
  回归只有既存`src/qount/cta_data.py` UTC deprecation warning。

### Funding-veto state decay resolves eventually but repeatedly re-diverges

- 在读取状态结果前生成
  `state/research_runs/20260717T155209Z-mini-trend-um-funding-veto-state-decay-preregistration/mini_trend_um_funding_veto_state_decay_preregistration.json`，
  contract/protocol hash `4cbbc402...bfb62d3b` / `79997bf0...ed4ce00`。合同绑定原历史/归因artifact、17个事件、
  713/696收益差异计数和UM rules；状态字段固定为risk stage、vol target、目标权重、吊灯高点、剩余冷却和
  selector latch，容差 `1e-12`，不扫描字段或持续时间阈值。权益明确排除在“执行状态同步”外，收益路径单独审计。
- `run_variant` 只新增决策结束后的审计快照，不改变目标、费用、funding、止损或净值。最终报告
  `state/research_runs/20260717T155312Z-mini-trend-um-funding-veto-state-decay-historical/mini_trend_um_funding_veto_state_decay_historical.json`
  对1776日完整覆盖，原收益/Sharpe/maxDD零差重放，返回差异713日、非事件返回差异696日与归因逐项一致；
  7门全过，verdict=`historical_execution_state_decay_resolved`。
- 执行状态差异696日（39.19%），分成18个spell，长度中位27.5日、最长100日；收益差异713日（40.15%），
  16个spell中位31.5日、最长101日。17个事件只落在5个状态spell，另外13个spell无新veto，是旧权益/权重
  路径在表面同步后重新发散。
- 每个事件都在14-56日内首次同步，中位46日；12/17事件在首次同步前又遇到后续veto。只有最后一次
  2024-12-05事件在窗口内取得“直到边界不再发散”的稳定同步：首次同步35日，但稳定同步要324日，到
  2025-10-25。其余事件在下一事件前均出现再发散或被新事件截断。
- facet总计显示risk stage/vol target各差17日、目标权重差696日，吊灯高点/冷却/latch内部状态均0差异。
  所以路径延续来自目标权重、deadband和权益反馈，不是stop/latch实现漂移。未来独立shadow forward必须保存
  两套权益和完整状态，不能在首次权重相等时停止candidate对照；本诊断不改变base v0.2正式选择或paper/live关闭。
- 全程只读Mac已有缓存，未下载、未访问VPS/private API、未触发订单。新增状态审计测试4项并补既有回测状态
  字段断言；MiniTrend warnings-as-error `72 OK`，本地完整 `1130 OK`。完整回归只有既存 `cta_data.py` UTC
  deprecation warning；`compileall`、CLI help、artifact门、凭据扫描和 `git diff --check` 通过。

### Funding-veto exact attribution supports cost savings but exposes downstream path drag

- 在读取归因结果前生成
  `state/research_runs/20260717T153223Z-mini-trend-um-funding-veto-attribution-preregistration/mini_trend_um_funding_veto_attribution_preregistration.json`，
  contract/protocol hash `1c3acd02...56e9d3` / `bee20675...f638e1`。预登记绑定原Funding Veto历史报告、条件
  Bootstrap报告、17个事件日期、全窗数据与UM rules；固定事件/下游 × 价格/funding/交易成本六组，穷举64个
  coalition做终值复利Shapley，不扫分组、顺序或参数。
- 为避免另写一个可能漂移的回测器，只在既有 `run_variant` 每日结果中记录已经用于净值计算的
  `gross_price_return/funding_return/trading_cost_return/net_return`，仓位、费用、funding、止损和净值逻辑不变。
  最终报告
  `state/research_runs/20260717T153320Z-mini-trend-um-funding-veto-attribution-historical/mini_trend_um_funding_veto_attribution_historical.json`
  精确重放旧指标；逐日组件与六组闭合误差分别仅 `6.94e-18/5.20e-18`，Shapley闭合误差0，17/17事件匹配，
  7门全过，verdict=`historical_cost_veto_mechanism_supported`。
- 按经济组件，candidate相对Stop-Latch的 `+0.536350pp` 终值增益由funding节省 `+0.443474pp`（82.68%）、
  价格暴露 `+0.096965pp`（18.08%）、交易成本 `-0.004089pp`（-0.76%）组成。这支持“降低高funding下的
  持仓成本”，但不是carry收入或独立alpha。
- 按时间，17个事件日合计 `+1.842439pp`：价格 `+1.590752pp`、funding `+0.357244pp`、交易成本
  `-0.105557pp`。其后非事件路径合计 `-1.306088pp`：价格 `-1.493787pp`，后续funding/成本
  `+0.086231/+0.101468pp`。因此约71%的事件日优势被后续路径吃掉；17个事件最终产生713个差异日，其中
  696个为下游日。未来验证必须完整重放仓位、deadband、权益和latch状态，不能只抽17个事件次日。
- 读法：成本过滤机制在已消费历史中成立，但强路径依赖解释了为何Bootstrap终值收益胜率仅58.90%。这仍不是
  OOS、forward、paper或live资格；正式策略保持base v0.2，Funding Veto维持首选历史候选且50%阈值冻结。
- 全程只读Mac已有缓存，未下载、未访问VPS/private API、未触发订单。新增归因测试4项，并在既有回测测试中
  加入组件恒等式断言；MiniTrend warnings-as-error `68 OK`，本地完整 `1126 OK`；完整回归只有既存
  `cta_data.py` UTC deprecation warning。
  `compileall`、CLI help、artifact闭合/安全断言、凭据扫描和 `git diff --check` 通过。

### Funding-veto paired block bootstrap passed, with only marginal terminal-return evidence

- 为反证17个 funding veto 事件是否只靠少数历史路径，在读取 Bootstrap 结果前生成预登记
  `state/research_runs/20260717T151224Z-mini-trend-um-funding-veto-robustness-preregistration/mini_trend_um_funding_veto_robustness_preregistration.json`，
  contract/protocol hash `d14f39d2...a0a7bd` / `7ae206a9...beff3c`。它绑定原 Funding Veto 预登记、历史
  retain artifact SHA、全窗数据hash和UM rules hash；固定 paired circular moving-block bootstrap、20完成日
  block、5000条路径、seed=`20260717`，不扫block/seed/指标。
- 审计从同一离线 bars/funding/filters/cost 合同重放 Stop-Latch reference 与 Funding Veto candidate，得到1776个
  同日净简单收益；原报告两策略收益/Sharpe/maxDD六项重放差均为0。每条Bootstrap路径使用同一组区块索引，
  保留策略间同日关系；它不在合成市场路径重新计算regime、latch、deadband或订单状态。
- 最终报告
  `state/research_runs/20260717T151318Z-mini-trend-um-funding-veto-robustness-historical/mini_trend_um_funding_veto_robustness_historical.json`：
  候选终值收益高于reference概率 `58.90%`、Sharpe更高概率 `86.82%`、maxDD更低概率 `75.72%`；三项增量
  中位数 `+0.462935pp/+0.019102/-0.226270pp`，全部7个预登记门通过，verdict
  `retain_historical_candidate_after_conditional_bootstrap`。
- 反证边界同样重要：终值收益增量5%-95%区间为 `-4.187260..+4.443793pp`，收益胜率只比55%门高3.9pp；
  Sharpe区间 `-0.008551..+0.050975`，maxDD增量区间 `-1.116548..+0.295595pp`。故证据更支持“风险质量
  可能改善”，不支持稳定收益alpha或跨周期alpha。正式选择仍是base v0.2，Funding Veto只保留为首选历史
  候选，必须等独立新日线；不进入forward/paper/live。
- 全程只用已有Mac缓存，离线cache miss fail closed；未下载数据、未访问VPS/private API、未触发订单，artifact
  和源码凭据扫描为空。
- 验证：新增审计 `5 OK`，MiniTrend全聚焦warnings-as-error `64 OK`，本地完整 `1122 OK`；完整回归只有
  既存 `cta_data.py` UTC deprecation warning。`compileall`、CLI help、artifact门断言、凭据扫描和
  `git diff --check` 通过。

## 2026-07-17

### External suggestions triaged; lagged-funding cost veto retained on consumed history

- Owner 提供链上顶底、宏观流动性、ADX、动态ATR/deadband、funding、ML/Markov和叙事周期建议，并明确
  “不要奉为真理，以实践为准”。证据分流写入 `docs/mini-trend-agent/review.md`：ADX已有9折WF反证；动态
  风控参数、超1x和carry与当前证据/约束冲突；链上/宏观/情绪缺point-in-time、授权、发布时点G0；ML与
  regime-switching延后。只立即实践已有缓存可因果验证、直接对应持仓成本的lagged funding。
- 单一候选沿用stop-latch：只在尚未锁定的strong-bull读取上一完整持有日已结算funding，TOP3日和中位数
  简单年化 `>50%` 时，本bar 2.0% boost退回1.5%；缺失同样降到1.5%。不使用未来settlement、不改变
  选币、不做carry。50%来自owner外部假设且读取结果前冻结，family trial=2，不扫阈值。
- 预登记
  `state/research_runs/20260717T144609Z-mini-trend-um-funding-veto-preregistration/mini_trend_um_funding_veto_preregistration.json`，
  contract/protocol hash `f56bafc2...75ed5` / `a777ac71...c31c7`。最终报告
  `state/research_runs/20260717T145148Z-mini-trend-um-funding-veto-historical/mini_trend_um_funding_veto_historical.json`
  只读本地缓存，funding coverage=1.0、0 missing、17 veto bars。
- 全窗 base/stop-latch/funding-veto：收益 `+66.505396%/+88.414042%/+88.950393%`、Sharpe
  `0.902770/0.945436/0.965235`、maxDD `17.284508%/18.702705%/18.105121%`。funding-veto相对base
  收益 `+22.444997pp`、DD恶化 `0.820613pp <=1pp`；平均/max gross `0.216925/0.903255`。三段为
  `-0.697801%/+58.242857%/-1.833021%`，所有预登记门通过，verdict
  `retain_historical_funding_veto_candidate`，仍禁止paper/live。
- 相对stop-latch，funding veto全窗收益 `+0.536350pp`、Sharpe `+0.019798`、DD改善 `0.597584pp`；
  主要修复2023-2024 DD `-1.464175pp`，2025-2026无veto、结果完全相同。17事件中10次次日直接改善、
  7次变差，中位直接增量 `+0.055483pp`，最大正事件占全部正贡献 `26.58%`；事件分布为2021六次、
  2023-2024十一次、2025-2026零次。历史retain不是跨周期alpha或独立OOS。
- 路线重排：base v0.2仍是正式选择；funding-veto冻结为首选历史候选，不调50%。链上/宏观下一步只做
  source/release-time G0；ADX、动态ATR/deadband、超1x、carry关闭；ML/Markov/叙事延后到确定性特征
  独立OOS和DSR/PBO之后。未访问VPS/private API、未下载数据、未触发订单。
- 验证：MiniTrend全聚焦 `59 OK`，本地完整 `1117 OK`；完整回归只有既存 `cta_data.py` UTC deprecation
  warning。`compileall`、CLI help、artifact全门断言、凭据扫描与 `git diff --check` 通过。

### UM strong-bull stop latch fixed the weak segment but missed the full-DD gate

- Owner 要求不等待新日线、继续利用已有历史。为避免继续调 SMA/breadth/确认天数/1.75% 风险档，只设计一个
  无新数值阈值的执行反馈：三阶段分类不变，每个连续 strong-bull 初始仍用 2.0%；任一币触发既有 3xATR
  stop 后，从下一根完成日线只退回 base 1.5%，原逐币 3-bar cooldown 不变；先退出 strong-bull，后续
  再进入时才解锁。其余 TOP3、UM wallet、funding、10bps+2bps、filters、gross<=1、no carry/short/
  leverage boost 全部不变。
- 结果读取前生成 preregistration
  `state/research_runs/20260717T134653Z-mini-trend-um-regime-stop-latch-preregistration/mini_trend_um_regime_stop_latch_preregistration.json`，
  contract/protocol hash `8198c38e...3759a` / `18b62218...2c8df`，绑定前一 regime overlay 的拒绝 artifact。
  历史门固定为全窗收益增量 `>=10pp`、Sharpe 不降、全窗 DD 相对 base 恶化 `<=1pp`、任一分段 DD 恶化
  `<=2pp`、2025-2026 收益最多落后 base `1pp`、平均 gross `<=0.23`，并要求 latch 实际触发；trial=1。
- 最终 artifact
  `state/research_runs/20260717T135551Z-mini-trend-um-regime-stop-latch-historical/mini_trend_um_regime_stop_latch_historical.json`
  只读本地缓存，`network_download_used=false`。全窗 control/candidate 收益
  `+66.505396%/+88.414042%`、Sharpe `0.902770/0.945436`、maxDD `17.284508%/18.702705%`、平均 gross
  `0.182424/0.218771`；候选交易成本 `33.985078 USDT`、funding PnL `-44.934231 USDT`、max gross
  `0.903042`。22 个 strong-bull stops 形成 11 次 latch entry，535 boosted/149 latched bars。
- 分段均未降低收益：2021-2022 `-0.973818% -> -0.557559%`，2023-2024
  `+41.489075% -> +57.946535%`，2025-2026 `-2.018860% -> -1.833021%`。尤其弱段相对未加锁 overlay
  的 `-5.128630%/12.445085% DD` 显著修复到 `-1.833021%/9.855771% DD`，Sharpe、分段 DD、weak、gross、
  filters、duplicate、stop reentry 门全部通过。
- 唯一失败门是全窗 DD：相对 base 恶化 `1.418197pp > 1pp`，区间为
  `2024-03-13..2024-10-25`，并非 2025 弱段。verdict=`reject_historical_regime_stop_latch`。不因只差
  `0.418pp` 把门放宽到 1.5pp，也不根据 latched bars 的已看结果追加 cash rescue。它定性为当前最强
  consumed-history 机制证据，但不是 OOS/paper/live 资格；选定策略仍是 base v0.2。
- 验证：MiniTrend 全聚焦 `52 OK`，本地完整 `1110 OK`；完整回归只有既存 `cta_data.py` UTC deprecation
  warning。`compileall`、CLI help、artifact 单失败门断言、凭据扫描与 `git diff --check` 通过。

### UM bull/range/bear overlay preregistered, backtested, and rejected

- 按 owner“增加牛市熊市震荡多阶段叠加判断”，只设计一个 stage-aware 风险 overlay，不扫参：strong bull
  固定为 `BTC close>SMA200 + BTC SMA20>SMA60 + TOP3 中至少 2/3 close>SMA200`，复用已测试的 2.0%
  `vol_target`；base 总闸已开但不满足 strong bull 为 transition/range，保持 1.5%；总闸关闭为 bear/cash。
  TOP3、UM wallet、1d、long/cash、完整 funding、10bps fee+2bps slippage、runtime filters、3xATR stop、
  3-bar cooldown、gross<=1、no carry/short/leverage boost 全部不变。
- 在读取候选收益前生成 preregistration
  `state/research_runs/20260717T132304Z-mini-trend-um-regime-overlay-preregistration/mini_trend_um_regime_overlay_preregistration.json`，
  contract/protocol hash `4fda4c46...c01e6f` / `7ced6ae9...64101`，并绑定先前全局 2.0% risk-tier 的
  `reject_historical_risk_tier` 证据。历史门预先固定为：全窗增收 `>=10pp`、Sharpe 不降、全窗 maxDD
  `<=20%`、任一分段 DD 恶化 `<=2pp`、2025-2026 相对 base 收益最多恶化 `1pp`、平均 gross `<=0.25`，
  三态覆盖和执行审计必须完整；trial=1，禁止参数/universe 搜索和 paper/live。
- 最终报告
  `state/research_runs/20260717T132757Z-mini-trend-um-regime-overlay-historical/mini_trend_um_regime_overlay_historical.json`
  只读本地缓存，`network_download_used=false`。全窗 control/candidate 收益
  `+66.505396%/+85.937218%`、Sharpe `0.902770/0.901776`、maxDD `17.284508%/19.297611%`、平均 gross
  `0.182424/0.227027`；分段增量为 2021-2022 `+0.987702pp`、2023-2024 `+15.488647pp`、
  2025-2026 `-3.109770pp`。filters coverage=1.0、0 duplicate、0 same-bar stop reentry、gross<=1。
- 失败机制不是全窗收益不足，而是 regime 不稳定：2025-2026 收益从 `-2.018860%` 恶化到
  `-5.128630%`，maxDD 从 `8.042619%` 加深到 `12.445085%`；其中 64 根 strong-bull bars 的收益从
  `-1.454390%` 放大到 `-3.910642%`、阶段 DD 从 `5.996161%` 加深到 `9.033857%`。最差 strong-bull
  outcome 2025-10-10 从 base `-3.644761%` 放大到 `-4.878515%`，8 月另有两次约 `-2.30%`，不是单一
  异常点。全窗 Sharpe 还下降 `0.000994`；Sharpe、分段 DD、弱段收益三门失败。
- verdict=`reject_historical_regime_overlay`。不事后加确认天数、改 breadth/SMA、试 1.75% 或放宽杀线；
  最终选择仍是 UM base v0.2 1.5%。新增模块仅是可审计研究资产，不进入 forward/paper/live；未访问 VPS、
  private API 或订单路径，也未下载数据。
- 验证：MiniTrend 全聚焦 `47 OK`，本地完整 `1105 OK`；完整回归只有既存 `cta_data.py` UTC deprecation
  warning。`compileall`、CLI help、artifact 安全断言与 `git diff --check` 通过。

### UM 2.0% risk tier preregistered, backtested, and rejected

- 按 owner“继续推进、吸取实盘经验、设计策略并回测”，只设计一个单变量收益风险档：TOP3、UM wallet、
  1d、long/cash、SMA20/60/200、breadth 0.5、相关性惩罚、3xATR stop、3-bar cooldown、10bps fee +
  2bps slippage、完整 funding、no carry/short/leverage boost 全部沿用 base v0.2；唯一信号尺寸变化是
  `vol_target 0.015 -> 0.020`，max effective gross 仍为 1.0。没有参数网格或 universe 搜索。
- 在读取真实候选收益前生成 v0.1 preregistration
  `state/research_runs/20260717T123954Z-mini-trend-um-risk-tier-preregistration/mini_trend_um_risk_tier_preregistration.json`，
  contract/protocol hash `ab015ffd...fbc7` / `241481a2...f8cb`。历史门固定为：全窗收益增量 `>=10pp`、
  Sharpe 下降 `<=0.03`、全窗 maxDD `<=25%`、任一分段 DD 恶化 `<=5pp`、最差分段收益 `>=-5%`、
  平均 gross `<=0.30`、filters/重复决策/同 bar 止损重入全干净。
- v0.1 首次真实运行在读取完整收益前被 `effective gross exceeded preregistered cap` fail-closed：逐币
  deadband 保留旧仓后，组合 gross 可超过 1.0。失败 artifact
  `state/research_runs/20260717T124305Z-mini-trend-um-risk-tier-historical/mini_trend_um_risk_tier_historical.json`
  为 `reject_execution_contract_incomplete`，没有用异常绕过风险上限。
- v0.2 在重新读取收益前只补执行合同：组合 gross cap 优先于 deadband，若超限则按 runtime filter floors
  把 active targets 确定性归一化到 gross=1.0；信号和 2.0% 参数不变。预登记
  `state/research_runs/20260717T124409Z-mini-trend-um-risk-tier-preregistration/mini_trend_um_risk_tier_preregistration.json`，
  contract/protocol hash `d94b2190...1b0e` / `a0db6ef7...cb2f`。
- 最终历史 artifact
  `state/research_runs/20260717T124433Z-mini-trend-um-risk-tier-historical/mini_trend_um_risk_tier_historical.json`
  只读已有缓存，`network_download_used=false`。全窗 control/candidate：收益
  `+66.505396%/+103.292645%`、Sharpe `0.902770/0.973606`、maxDD `17.284508%/21.211666%`、平均 gross
  `0.182424/0.239709`；gross cap 归一化仅 1 次、filter coverage 1.0、0 duplicate、0 same-bar reentry。
  分段收益：2021-2022 `-0.973818%/+1.368616%`，2023-2024 `+41.489075%/+65.101363%`，
  2025-2026 `-2.018860%/-5.313845%`。
- verdict=`reject_historical_risk_tier`：2025-2026 candidate maxDD `13.782484%`，比 control 深
  `5.739864pp`，同时击穿“DD 恶化 <=5pp”和“最差分段收益 >=-5%”。高全窗收益不能覆盖弱市失败。
  不继续试 1.75%/1.8%、drawdown threshold 或放宽门；最终选择仍是 UM base v0.2 `vol_target=1.5%`，
  risk-tier 不进入 forward/paper/live。
- 验证：MiniTrend 全聚焦 warnings-as-error `43 OK`，相关 X4 funding/账本/波动率/吊灯 `37 OK`；本地
  完整 `1101 OK`，只有既存 `cta_data.py` UTC deprecation warning；`compileall`、CLI help、
  `git diff --check` 通过。

### Retired X4 high-return attribution and exact UM base v0.2 contract

- 新增 `src/qount/mini_trend/high_return_attribution.py`、薄 CLI 和 funding 对齐单测；命令只读取已有
  `state/grid_b/klines`，network fetch 被显式 fail-closed。artifact：
  `state/research_runs/20260717T121616Z-mini-trend-high-return-attribution/mini_trend_high_return_attribution.json`，
  holdout role=`discovery_pool`、window=`2021-01-01..2026-05-31`、BTC 1d/1h bars=`1977/47448`、
  `network_download_used=false`、verdict=`legacy_high_return_explained_not_promotable`。
- 逐机制桥接：rehedge deadband 只给 S3/S4 `+4.18/+0.07pp`；1h→1d 给 `+61.46/+57.94pp`；保持
  同信号去掉空头再给 `+59.42/+63.40pp`；SMA200 regime gate 给 `+48.56/+58.28pp`；3% vol target
  给 `+7.42/+19.74pp`，S4 4xATR chandelier 再给 `+9.46pp`。S4 的 volume multiple 1.5→1.0
  反而贡献 `-48.51pp`，不是收益来源。
- 发现旧日线 funding 口径缺陷：`funding_ts == bar.ts_ms` 只命中每日 00:00 settlement，漏掉
  08:00/16:00。旧 artifact 保留不覆盖；按完成日线收盘后的完整下一持有日三次 settlement 更正后，S3
  `+115.184257% -> +84.931098%`、Sharpe `0.665105 -> 0.559143`、maxDD
  `29.431616% -> 31.500496%`；S4 `+98.389913% -> +70.773274%`、Sharpe
  `0.697759 -> 0.569959`、maxDD `23.779415% -> 24.813183%`。漏计分别虚高
  `30.253159pp/27.616640pp`；完整 funding 相对不计 funding 拖累 `39.782074pp/34.617089pp`。
- 新增 `src/qount/x4/funding.py:holding_period_funding`，把完成 bar 的信号对齐到下一 close-to-close 持有期
  全部 settlement；`x4_compare.py` 后续新跑默认使用正确口径并在 artifact 写入 `funding_alignment`。
  修后离线复跑 artifact `state/x4/research_runs/x4_compare_2021-01_2026-05_1d_20260717T122845Z.json`
  给出 S3/S4 `+84.931098%/+70.773274%`，与 attribution 更正值一致；历史错误口径的逐位复现仅保留在
  attribution runner 的显式 legacy 分支，不再作为新报告默认值。
- 2x cap 相对 1x 对 S3/S4 return 只贡献 `-1.171822pp/+2.539444pp`，且 Sharpe 都下降；旧高收益
  不是杠杆 edge。同期正确 funding、5bps fee+2bps slippage 的 BTC 1x/TOP3 EW 为
  `+37.720851%/+355.401261%`，maxDD `78.929066%/73.594966%`。旧趋势书解决的是以较低 beta 捕获
  牛市并在熊市走现金，不是稳定正收益 alpha。
- 当前 UM base 用同一全窗、正确 funding、10bps+2bps、真实 filters 的 discovery readout 为
  `+66.505396% / Sharpe 0.902770 / maxDD 17.284508%`，平均有效 gross `0.182424`；与旧实盘
  `-2.166870%`、5 重复单、8 组同 bar 反向和 66 次未知本金 fail-closed 一起，支持继续
  `UM wallet + no carry + TOP3 + 1d + long/cash + no leverage boost`，不支持恢复 short/recovery。
- 原 UM base v0.1 contract 没显式绑定 runner 实际使用的 `3xATR` 日线 chandelier。由于尚未消费任何
  forward result，升为 v0.2 并生成
  `state/research_runs/20260717T121646Z-mini-trend-um-base-forward-preregistration/mini_trend_um_base_forward_preregistration.json`，
  contract/protocol hash `796d3297...64cd` / `2f8cb562...f363`；策略参数和执行行为不变，只补完整合同。
  新 freshness artifact `20260717T121715Z-mini-trend-um-base-forward` 仍为 latest common
  `2026-06-18`、evaluation bars `0`、`strategy_results_evaluated=false`、`await_forward_data`。
- 验证：当时 MiniTrend 全聚焦 warnings-as-error `39 OK`，相关 X4 账本/波动率/吊灯 `46 OK`，funding 对齐
  `3 OK`，本地完整 `1097 OK`（只有既存 `cta_data.py` UTC deprecation warning）；新增模块与 CLI `compileall`、
  `git diff --check` 通过，归因 runner 完整离线跑通。
  未访问 VPS/private API、未下载数据、未写 paper/live state、未下单。

### Owner selected low-frequency existing-data path; frozen TOP3 forward started

- Owner 明确“推进、不用高频”。路线从等待 licensed liquidation/L2 改为复用已有日线趋势资产；不恢复
  5m/1h Alpha 模型、分钟 collector、VPS cron、paper 或 live。新增 `mini_trend/forward.py`、薄 CLI 和
  `test_mini_trend_forward.py`，不修改 MiniTrend signal/risk/execution 核心。
- Binance spot `api.binance.com` 在当前 Mac 返回 451；切到官方 public market-data 域
  `data-api.binance.vision`，USD-M URL 不变。rules artifact
  `20260717T030547Z-alpha-agent-exchange-rules`、raw hash `184faa32...8d13`：BTC/ETH/BNB 全部
  `TRADING`，min-notional 5 USDT，step size `0.00001/0.0001/0.001`。
- 在读取 7 月结果前写 preregistration
  `20260717T030622Z-mini-trend-top3-forward-preregistration`：绑定旧 TOP3 anchor 的 config/summary/equity
  SHA，固定 spot long/cash、1d、400 USDT、SMA20/60/200、breadth 0.5、vol target 0.015、band 0.35、
  10bps fee + 2bps slippage、trial 1；禁止参数/universe search、高频、short、leverage 和自动 paper/live。
  contract/protocol hash `37302065...68b2` / `029835ae...773c`；60 forward bars + 10 active bars 才允许
  paper-readiness review。
- 首跑 `20260717T030915Z-mini-trend-top3-forward` 因 Binance Vision 个别日包瞬时失败只有 9/14 对齐日，
  `data_complete=false`，保留为中间 fail-closed 证据。CLI 加有限网络重试和显式“最后完成日”尾部截断门，
  不改协议；最终 artifact `20260717T031824Z-mini-trend-top3-forward` 为 2026-07-01..16 共 16/16、
  预期尾日 07-16、0 gap，data hash
  `494f01da...cf98`。旧 research-filter anchor equity `401.85455267` 精确复现；runtime filters 的历史
  equity drift 仅 `+0.019512 USDT`。
- 当前信号：BTC close/SMA200 `63,830.20/73,438.14`、breadth `0.0`，master gate shut，TOP3 targets
  全 0。16 cash bars、0 active、0 orders/blocked；策略 `+0.002866%`、maxDD `0.001026%`，同期 BTC B&H
  `+8.879345%`、TOP3 EW `+10.747795%`。verdict `collect_forward`，blockers 仅为 60 bars/10 active 未满；
  这说明低 beta 防守没有追到本轮反弹，不是 alpha 通过，也不允许事后放宽总闸。
- 验证：MiniTrend forward/core + exchange rules 聚焦 warnings-as-error `31 OK`，本地完整 `1081 OK`；
  `compileall`、CLI help、`git diff --check` 通过。完整回归只有既存 `cta_data.py` UTC warning。未访问
  VPS/private API、未写 paper/live state、未下单。

### Retired X4 live audit and no-carry UM recovery diagnostic

- 按 owner 要求做 VPS 只读历史审计，读取远端 `orders.jsonl`、`snapshots.jsonl`、guarded daily equity、
  `stops.json`、`latest.json` 和日志；远端 SHA/行数被记录，原始日志临时副本在统计后删除。新增
  `src/qount/mini_trend/live_lessons.py`、`scripts/research/mini_trend_live_lessons.py` 和测试。
- audit artifact：`state/research_runs/20260717T033716Z-mini-trend-live-lessons/mini_trend_live_lessons.json`。
  24 个 guarded daily points 的可比区间为 484.57 -> 474.07，策略 return `-2.166870%`；6 月末 499.36
  到 7 月 11 日 474.07 回吐 `25.29 USDT`，回吐前期增益约 `170.99%`。最新 415.00 与 guarded daily
  末点的 `59.07 USDT` 差额是 owner 撤资/重置，latest 的 `-14.36%` 不作为策略 PnL。
- 订单/执行证据：37 个 inception 之后已发单；5 个完全重复单（125ms 内同批 5 单）、7 个同日同向重复
  单、8 组同日方向反转、2 个停止事件；BTC+BNB 名义时间占比 `60.084012%`。日志安全统计为 66 次未知
  本金 fail-closed、21 次旧 fallback balance 读取、11,818 条 `+0.00` min-order skip、1 次 stop sync。
  新合同因此固定单日单批、stop latch/cooldown、runtime filter coverage、unknown-capital fail-closed，
  不用杠杆补小资金。
- owner 同时明确后续资金架构为 `USD-M futures wallet + carry off`；这不授权 VPS/私有 API/paper/live。
  新增 `src/qount/mini_trend/futures_recovery.py`、`futures_recovery_backtest.py`、
  `futures_recovery_report.py`、薄 CLI 和测试。preregistration 在收益读取前生成：
  `state/research_runs/20260717T034500Z-mini-trend-um-recovery-preregistration/mini_trend_um_recovery_preregistration.json`，
  contract hash `284a78e4...e103`、protocol hash `13ebf76d...0308`，固定 UM TOP3/1d/funding、long/cash、
  recovery 25% gross、3 根 20 日线确认、1.05 filter buffer、10bps+2bps 成本、3 根 stop cooldown、trial 1。
- 历史诊断 artifact：`state/research_runs/20260717T035442Z-mini-trend-um-recovery-historical/mini_trend_um_recovery_historical.json`。
  只读已有 `state/grid_b/klines` 缓存，`network_download_used=false`；控制/候选净收益分别为：
  `2021-2022 -0.973818%/-9.392283%`（增量 `-8.418465pp`）、`2023-2024 41.489075%/39.385339%`
  （`-2.103736pp`）、`2025-2026 -2.018860%/-1.848545%`（`+0.170316pp`）。只有 1/3 段增量为正，
  首段回撤恶化约 `9.54pp`，verdict `reject_historical_candidate`。不调参救援，不消费新 forward，不进 paper/live。
- 数据下载纪律：不使用苏菲家宽代理做批量下载；需要新增大批量 public data 时只走仓库外配置的
  owner-approved Liangxin Cloud proxy；凭据不写入 repo/artifact/命令输出。本轮 UM 诊断未下载新数据，
  缓存缺失会直接 fail closed。
- 验证：实盘审计聚焦 `3 OK`，UM 合同/回测聚焦 `5 OK`；新增模块 `compileall` 和 CLI help 通过。尚未
  做 full local regression；未同步 VPS、未恢复 cron、未调用私有 API、未下单。
- recovery 失败后没有把它调参改成“成功”；按 owner 的“之前趋势策略”方向，另写并生成 future-only UM
  base control v0.1 preregistration（后被同日未读结果的 v0.2 完整合同替代）：`state/research_runs/20260717T040358Z-mini-trend-um-base-forward-preregistration/mini_trend_um_base_forward_preregistration.json`，
  contract hash `b2a86d61...bd16`、protocol hash `4df7acee...b5d8`，固定原 TOP3 日线趋势、funding、
  no-carry、long/cash、effective gross `<=1.0`、runtime filters、3 根 stop cooldown、60 forward bars /
  10 active bars。`strategy_results_evaluated=false`；当前 UM 缓存没有 2026-07-17 之后完整日线，未读取
  forward 收益，未下载新数据。
- 新增 `src/qount/mini_trend/futures_base_forward_report.py` 和 freshness CLI `--run`，用离线缓存运行
  `state/research_runs/20260717T043314Z-mini-trend-um-base-forward/mini_trend_um_base_forward.json`。
  三币 latest common completed bar=`2026-06-18`，forward start=`2026-07-17`，evaluation bars=`0`，
  `strategy_results_evaluated=false`，verdict=`await_forward_data`。该 artifact 不把历史控制线收益冒充
  新 forward，也没有触发下载、私有 API、paper/live 或订单。
- 用户确认“已有历史数据也可以用”后，新增 `futures_historical_benchmark.py` 及 CLI，复用已登记 UM
  历史窗口做基准分解，artifact：`state/research_runs/20260717T115728Z-mini-trend-um-historical-benchmark/mini_trend_um_historical_benchmark.json`。
  所有 benchmark 使用同一 400 USDT、UM 1d、funding、10bps+2bps 口径；control 相对 BTC 1x/TOP3 EW
  在 2021-2022、2023-2024、2025-2026 的收益差分别为 `+49.569743pp/+26.925232pp`、
  `-126.222007pp/-97.540173pp`、`+37.022291pp/+30.069310pp`。control 绝对正收益仅 `1/3` 段，
  但相对基准胜出 `2/3` 段，解释为低 beta 风险 wrapper，不是稳定 alpha；artifact `discovery_only`、
  `promotion_allowed=false`，未调参、未下载新数据。

### Historical option-surface and external microstructure audits blocked at G0

- 新增 `option_surface_capacity.py` + CLI/tests。artifact
  `20260716T155503Z-alpha-agent-option-surface-capacity`、data hash `e8ab2da2...bb6868`：五个
  2021/2024/2025 已过期 BTC/ETH instruments 的 metadata/chart 均可用；当前 BTC/ETH surface 为
  `874/720` 条 mark-IV。但 historical charts 只有 OHLC/volume/cost/ticks，2024 trade queries 为 0 rows，
  `expired=true` inventories 只枚举一个近期 expiry，无法重建 point-in-time chain/IV/index/mark。verdict
  `block_g0`；没有用 price-only inversion/strike search，也没有写 skew preregistration。
- 新增 `external_microstructure_capacity.py` + CLI/tests，并在 source registry 加 Tardis。最终 artifact
  `20260716T160716Z-alpha-agent-external-microstructure-capacity`、data hash `cc591bb7...5bf4f`：provider
  metadata 确认 BTC/ETH/BNB/SOL 全部有 `incremental_book_L2`/`liquidations`；BTC depth 一分钟
  `1,982,255` bytes、1,086 updates、0 invalid/sequence break，raw hash `69060a8d...a7e81`；四币
  forceOrder 同分钟 1 条 SOL、243 bytes，hash `57f28cac...175c`。
- 匿名整日 forceOrder 请求仍只返回同一 1 分钟，`x-slice-size=1`；BTC raw L2 外推
  `2,854,447,200 bytes/day`、`256,900,248,000 bytes/90d`，超过 32 GiB cache gate。verdict
  `block_g0_access_capacity`，blockers 为 licensed history 未授权、anonymous truncation、raw L2 超预算；
  只在 owner 授权且完整历史可复现后优先 liquidation-only，否则选 Mac-only forward collection。
- 首次真实 CLI 因标准库请求缺 Tardis 必需的 `Accept-Encoding: gzip|zstd` 收到 406，错误页没有作为最终
  容量证据。客户端随后固定 gzip 并在哈希/解析前解压；full-horizon gate 改用服务端 `x-slice-size`，避免
  稀疏 liquidation 事件跨度误判覆盖。最终工件复现手工 probe hashes。
- 验证：external/option/source-capacity 聚焦 `12 OK`，Alpha 全聚焦 warnings-as-error `128 OK`，本地完整
  `1075 OK`；`compileall`、`git diff --check` 通过。完整回归只有既存 `cta_data.py` UTC deprecation
  warning。未购买数据、未访问 VPS/private API、未写策略收益/preregistration/paper/live、未下单。

### Structural source matrix selected options DVOL; preregistered discovery failed 0/3

- 新增 `source_capacity.py` + CLI/tests，按官方公开小响应做四类 source-capacity matrix。artifact
  `20260716T141329Z-alpha-agent-source-capacity`、data hash `64c00692...4fa41`：Binance historical
  `forceOrder` 与 replayable `depth` checksum 路径均 404；aggregate `bookDepth` checksum 可用但不是
  diff-depth/L2；Deribit BTC/ETH DVOL 的 2021-04/2025-01 边界均为 25 根完整小时 OHLC；Hyperliquid
  BTC/ETH/BNB/SOL funding/premium 各 24 行可用，但机制与旧 funding/cross-venue 线重叠。唯一选择
  `deribit_options_dvol_relative_stress`，没有读取策略收益。
- 收益读取前 preregistration 经三轮完整性审计：v0.1/v0.2 分别因缺显式 beta/entry 与逐币/coverage 门被
  取代；最终只接受 v0.3 artifact `20260716T145022Z-alpha-agent-options-dvol-preregistration`，绑定 matrix
  SHA `46b3fdc...b3774`。固定 `ETH DVOL - BTC DVOL`、720h normalization/beta、reversion、`|z|>=2`、
  24h hold/cooldown、ETH/BNB/SOL、7bps/position change、funding、400 USDT filters、trial count 1、
  coverage `0.999` 和 2/3 kill line；contract/protocol hash `195a9160...3b95` / `c87b0d96...86fa9`。
- 新增 `historical_dvol.py` + CLI/tests。dataset
  `20260716T142116Z-alpha-agent-historical-dvol`：Deribit 90 个按月原始响应、`2,654,952` bytes，每个响应
  SHA 持久化；BTC/ETH 各 32,904 小时、coverage `1.0`、0 gap/duplicate，cache rerun data hash
  `d07122f7...09c86` 一致。
- 新增 `options_dvol.py` + CLI/tests，绑定 prereg/DVOL/price/funding/rules hashes，复用 as-of BTC-beta、
  400 USDT filter 和成本评分。月档首跑发现 SOL 在 2022-02-26..28 与 2022-04-01..02 缺 120 小时，
  三币 artifacts 因 price coverage `0.996353 < 0.999` 保留为中间失败证据；未改协议，新增只针对缺日的
  official daily ZIP + `.CHECKSUM` gap fill 后重跑，最终四币 price、feature、filter coverage 均为 `1.0`。
- 最终 ETH `20260716T151012Z`：rank IC/residual `-0.048945/-55.322693%`；BNB
  `20260716T151049Z`：`-0.078558/-77.010159%`；SOL `20260716T151042Z`：
  `+0.004773/+6.290805%`。每币 188 entries、total turnover 376、max rolling 24h turnover `2.0`、
  filter coverage `1.0`；funding 三币各覆盖完整 45 个月。
- final report `20260716T151115Z-alpha-agent-options-dvol=block_discovery`：passing/positive IC/positive
  residual `0/3,1/3,1/3`，median IC `-0.048945`、mean residual `-42.014016%`，所有 source/coverage/hash
  mismatch 为 0。2025 replication 与 2026-07-17 起 forward OOS 均未消费；不调 polarity/z/lookback/
  holding，不进 A10/paper/live，不访问 VPS/private API、不下单。
- 验证：新增三组聚焦单测与 Alpha 全聚焦 `120 OK`（warnings-as-error），CLI help、`compileall`、
  `git diff --check` 通过；本地完整回归 `1067 OK`，只有既存 `src/qount/cta_data.py` UTC
  deprecation warning。未同步 VPS、未跑远端测试。

## 2026-07-16

### Owner priority reset: A-share frozen, crypto research resumes

- Owner 明确决定先放弃 A股 ETF 方向并推进加密路线。A股 ETF 20 日线状态改为
  `frozen / owner-deprioritized / evidence gate block`；停止 Tushare parity、日频复跑、自动提醒、
  广发/东吴/QMT 券商接入以及任何 paper/live 工作。已有代码、测试和
  `20260716T094924Z-ashare-etf-month` discovery artifact 保留，不删除、不解释为交易授权。
- 加密恢复为唯一主动研究优先级，但本次授权限定在 Mac public-data / deterministic research。没有授权
  私有 Binance 账户访问、订单、VPS collector/crontab 恢复、forward paper 或 live。
- 既有负证据边界不变：frozen trade-flow v1 跨符号复制失败，flow absorption/premium/residual-trend
  均为 0/3，2025Q1 固定模型 replay 仍为 0/3；旧 S1'/S-CARRY/TS-MOM/5m GBDT 也不重开。
- 新的第一交付物改为 crypto new-source source-capacity matrix + 单一 G0 preregistration。候选必须引入
  独立结构性信息（liquidation、真实 replayable L2/queue、options vol/skew 或 cross-venue state），并在
  结果读取前固定 target/symbols/window/cost/trials/kill line/protocol hash；没有新信息不得换模型救旧数据。
- 本轮只更新 README/current/update-log/A股计划/Alpha 计划/project rules；未运行研究、未访问 VPS/private
  API、未恢复服务、未写 paper/live state、未下单。

### Frozen residual-trend 2025Q1 temporal replay failed 0/3

- 新增 `residual_trend_replay.py` + CLI/tests，只从保存的 scaler mean/scale、逐特征 coefficients 和 intercept
  手工重建概率，代码无 `fit`/CV/model search。结果读取前 preregistration
  `20260716T125427Z-alpha-agent-residual-trend-replay` 固定 2025Q1 完整窗口、原 10 features、`0.55/0.45`
  阈值、6h/18h 状态机、7bps cost/funding，并绑定原 ETH/BNB/SOL artifacts SHA；protocol hash
  `2f15b7af...cfcbfe`。明确即使时间复验转正也不能反转 March anchor failure、promotion 或 A10。
- 官方只读 metadata probe 为 396/396 HTTP 200，预算 depth/premium `162,843,538/7,443,575 bytes`。depth
  首跑 `20260716T125951Z` 因 `BTCUSDT 2025-03-09` 瞬时 TLS EOF fail closed 为 359/360；未改协议，复用
  checksum cache 重跑后最终 `20260716T130420Z` 为 360/360、103,620 complete 5m rows、四币 coverage
  `0.999421`、data hash `26f2a982...d01e`。premium `20260716T130534Z` 为 36/36、103,680 complete rows、
  coverage `1.0`、data hash `b6798ce0...5823`。
- 首次 ETH replay 在通用 K 线 loader 遇到 monthly TLS EOF 后静默退 daily；在产出概率 artifact 前主动中断。
  回放入口随后加入有限 archive retry 和严格价格覆盖审计，protocol hash 未改变；最终四币 2024-12 warmup
  至 2025Q1 小时 K 线覆盖 `1.0`，三币 model feature/filter coverage `0.997674/1.0`。
- ETH `20260716T131147Z`：AUC/IC/Brier improvement `0.502287/+0.012601/-0.010654`，87 entries、turnover
  `3.0`、net residual `-42.209377%`、DSR `0.007971`。BNB `20260716T131221Z`：
  `0.462687/-0.066387/-0.011183`，81 entries、turnover `3.0`、residual `-13.971742%`、DSR `0.130511`。
  SOL `20260716T131255Z`：`0.515403/+0.005188/-0.006259`，87 entries、turnover `3.0`、residual
  `-41.020445%`、DSR `0.066449`。三币 Brier 均劣于保存的 anchor train base-rate，cost residual 全负。
- final report `20260716T131339Z-alpha-agent-residual-trend-replay=temporal_replay_complete_no_promotion`：
  supportive/positive residual `0/3`、positive rank IC `2/3` 但均未过 `0.02`、mean residual
  `-32.400521%`，PBO fail-closed `1.0`、promotion/A10 false。固定 depth+premium+price Logistic 路线关闭；
  不再换年份、调阈值或换 HGB/LightGBM/Transformer，下一模型线须先有新信息源或不同 target。
- 验证：Alpha 全聚焦 `111 OK`、本地完整 `1058 OK`、replay/model FutureWarning-as-error `7 OK`、CLI help、
  `compileall`、`git diff --check` 通过；完整回归只有既存 `cta_data.py` UTC deprecation warning。未访问
  VPS/private API、未写 paper/live state、未下单。

### Fixed residual-trend probability model completed; March OOS failed 0/3

- 新增 `historical_depth.py` + CLI/tests：官方 daily `bookDepth` checksum、严格十档 percentage snapshot、
  流式 5m 聚合，明确 `replayable_l2=false`。单日 smoke `20260716T103655Z` 为 4/4 包、1,152 rows；最终
  Q1 dataset `20260716T104132Z-alpha-agent-historical-depth` 为 364/364 包、`165,500,458 bytes`、104,768
  rows。四币各 26,192/26,208、coverage `0.999389`、8 segments、约 261.75k snapshots；16 个共同缺桶
  分布在 7 个短区间，完整小时不跨 gap。
- 用户要求深度推进趋势/模型预测。按 A10 门控，只实现固定 tabular baseline，不启动 sequence model。
  结果读取前 preregistration `20260716T104401Z-alpha-agent-residual-trend-model` 固定 10 features、L2 Logistic
  `C=1`、Jan-Feb train、6h purge、March OOS、5-fold TimeSeriesSplit gap=6、0.55/0.45 概率门、6h/18h
  低换手状态机和 7bps position-change cost；contract/protocol hash 为 `a729ea39...20d979` /
  `be9f2123...477646`，trial count 1，禁止 feature/model/threshold search。
- ETH March：AUC `0.484692`、IC `-0.004346`、Brier improvement `-0.018288`、CV +IC `2/5`、29 entries、
  net residual `-17.444056%`、DSR `0.094571`。artifact `20260716T104452Z-alpha-agent-residual-trend-model`。
- BNB March：AUC `0.500214`、IC `-0.019693`、Brier improvement `-0.011088`、CV +IC `4/5`、30 entries、
  turnover `3.0`、net residual `-8.485764%`、DSR `0.243385`。artifact `20260716T104506Z-...-01`。
- SOL March：AUC `0.514279`、IC `+0.051771`、Brier improvement `-0.005436`、CV +IC `3/5`、30 entries、
  turnover `3.0`、net residual `-7.127153%`、DSR `0.299464`。artifact `20260716T104506Z-...`。
- final report `20260716T104522Z-alpha-agent-residual-trend-model=block_discovery`：passing/positive residual
  `0/3`、mean residual `-11.018991%`、filters 1.0、PBO fail-closed `1.0`、April unconsumed、
  `a10_sequence_enabled=false`。模型可产出概率、calibration、walk-forward、JSON scaler/coefficients 和成本
  回测，但当前没有可交易预测力；不在 Q1 换 HGB/LightGBM/Transformer 追分。
- 验证：Alpha 全聚焦 `107 OK`、本地完整 `1054 OK`、`compileall`、FutureWarning-as-error 和
  `git diff --check` 通过；完整回归只有既存 `cta_data.py` UTC deprecation warning。未访问 VPS/private API、
  未写 paper/live state、未下单。

### Premium/mark/index data passed; preregistered premium reversion failed 0/3

- 新增 `historical_premium.py` + CLI：official USD-M monthly
  `premiumIndexKlines/markPriceKlines/indexPriceKlines`，固定 5m/12-column schema，逐包 `.CHECKSUM` +
  SHA-256、原子 cache、三源 as-of merge。最终 strict artifact
  `20260716T102324Z-alpha-agent-historical-premium` 为 36/36 包、`7,613,751` compressed bytes、104,832
  complete rows；四币各 26,208 rows、coverage `1.0`、单 segment、0 blocker，data hash
  `784a816a...89d7381`。宽松 parser 首跑 `102040Z` 的 data hash 相同；加固没有改变数据或策略数值。
- 在读取任何 Q1 策略结果前写 preregistration
  `20260716T102055Z-alpha-agent-premium-dislocation`：contract hash `f07d0702...fa05d55`、protocol hash
  `6d842c44...4315c2f`。唯一候选取每小时 12 个 completed 5m premium close 均值，用过去 168h z-score，
  极端正 premium 做空/极端负 premium 做多；`|z|>=2`、hold 6h/cash 18h、5bps taker + 2bps slippage/
  position change，并计 funding 和 400 USDT filters。至少 2/3 标的过门才允许 April。
- 最终 strict replay：ETH IC/residual `-0.046471/-0.863166%`、BNB
  `-0.001891/-8.707943%`、SOL `+0.045684/-1.153916%`；entries `37/34/33`，filter coverage 全为
  `1.0`。SOL 窗口末强制平仓使 max rolling 24h turnover `3.0`，其余为 `2.0`；按冻结合同保留该成本和
  blocker。experiment artifacts 为 `20260716T102345Z`、同秒 `-01/-02`。
- final report `20260716T102358Z-alpha-agent-premium-dislocation=block_discovery`：passing `0/3`、positive
  IC `1/3`、positive residual `0/3`、median IC `-0.001891`、mean residual `-3.575008%`，April
  `reserved_oos_consumed=false`。不改 polarity/threshold/holding 救结果，不进 A10/paper/live。
- 已继续审计下一数据源：`bookDepth` 不是 diff-depth，而是约 30 秒一组 `±1%..±5%` 累计
  depth/notional。2024-01-01 单日四币包合计约 `1,813,245 bytes`；Q1 月首边界日 checksum probe artifact
  `20260716T102632Z-alpha-agent-historical-microstructure` 为 12/12 available、0 missing/error。下一轮先做
  strict snapshot parser + 5m 1% notional imbalance 聚合，不声称 L2 replayability。
- 验证：premium/flow 聚焦 `12 OK`，Alpha 全聚焦 `102 OK`，本地完整 `1049 OK`，`compileall` 与
  `git diff --check` 通过；仅有既存 `cta_data.py` UTC deprecation warning。未访问 VPS/private API、未写
  paper/live state、未下单。

### Flow/price absorption preregistered kill-test failed 0/3 symbols

- 在读取本轮策略结果前新增 `flow_absorption.py`、薄 CLI 和 2 个测试，并写 preregistration
  `20260716T100011Z-alpha-agent-flow-absorption`。合同 hash `8f30e701...f5bf124`、protocol hash
  `0c6f277c...a82d816`；trial count 1，固定 ETH/BNB/SOL Q1 分母和 April reserved OOS。
- 机制不是重调 frozen v1：完成小时 aggressive-flow 用过去 168h 标准化；若 flow z-score 与同小时
  BTC beta-residual 价格反应异号/为零，定义 passive absorption，取反向信号；`|z|>=2` 入场、持有 6h、
  cash 18h、禁止直翻。成本仍为每次 position change 的 taker 5bps + slippage 2bps，并计 funding 和
  400 USDT exchange filters；至少 2/3 标的各自过门才允许另写 April OOS 预注册。
- Q1 全败：ETH IC/residual `-0.024471/-8.056549%`、BNB `0.018082/-15.461342%`、SOL
  `-0.018355/-9.206446%`；entries `11/19/15`，filter coverage 全为 `1.0`，24h turnover 全为 `2.0`。
  单币 artifacts 为 `20260716T100023Z`、`100039Z`、`100043Z-alpha-agent-flow-absorption`。
- 最终 report `20260716T100057Z-alpha-agent-flow-absorption=block_discovery`：passing `0/3`、positive IC
  `1/3`、positive residual `0/3`、median IC `-0.018355`、mean residual `-10.908112%`，April
  `reserved_oos_consumed=false`。按协议停止，不改方向/阈值/持有期救结果。
- 现有 runner 只增加默认关闭的 hourly signal-transform hook；旧 frozen v1 hash 复核仍为
  `2b61627c...c9094`，默认行为未变。验证：新/旧 trade-flow 聚焦 `7 OK`，Alpha 全聚焦 `97 OK`，本地完整
  `1044 OK`，`compileall` 与 `git diff --check` 通过；只有既存 `cta_data.py` UTC deprecation warning。
  全程复用 Mac 已有 checksum-verified Q1 artifact/cache，未下载 April、未访问 VPS/private API、未写
  paper/live state、未下单。
- 读法：单源 aggressive-flow 的顺势和“被吸收后反转”都不能成为跨 majors 稳健 edge。下一轮必须加入
  独立状态变量，不能继续在已看 Q1 上派生第三套 aggTrades-only 规则。
- 已继续完成 `bookTicker` source-capacity audit：只读 `.CHECKSUM` artifact
  `20260716T100514Z-alpha-agent-historical-microstructure` 为 Q1 四币 12/12 月包 available、0 missing/error；
  official HEAD Content-Length 合计 `58,608,259,115 bytes`（`54.58 GiB`）。当前 Mac 约 `87 GiB` 可用，
  全量缓存会让余量低于约 33 GiB 且未计临时文件，因此没有下载。下一优先级改为小体量 mark/index
  premium；bookTicker 只保留为先写磁盘预算的抽样/流式备选。

### A-share ETF one-month regime study: hardware pullback, evidence gate blocked

- Owner 授权从加密慢线转做近期 A股 ETF 一个月方案，并要求区分“AI 硬件回调”和“整个 AI 逻辑结束”。
  新增 `src/qount/ashare_etf_month.py`、薄 CLI、7 个离线测试和
  [ashare-etf-month-plan.md](ashare-etf-month-plan.md)；与 L6/CTA-R/crypto production 隔离，
  research-only，无订单或 live side effect。
- 数据层直接调用 Tushare Pro `fund_daily + fund_adj`，只读 `TUSHARE_TOKEN`，token 不进缓存/artifact；
  同时支持东方财富/腾讯前复权公开源。本机未注入 token，东方财富发生短时拒绝后停止重试，最终使用
  腾讯 qfq 数据；共同窗口 2021-02-23..2026-07-16，共 1,308 sessions。Tushare 跨源 parity 待 token。
- 状态合同固定硬件 `512480/515880`、核心 `159819`、应用代理 `512980`、基准 `510300`，按
  20/60/120 日趋势和相对强弱判别。当前为 `hardware_pullback_application_rotation`：硬件 gap-MA20
  `-12.50%`、5 日相对 `-11.94%`，但应用相对硬件强度差 `+13.78%`、AI 核心 gap-MA120
  `+11.72%`/60 日相对 `+15.36%`，`broad_ai_weak=false`，不能写成全 AI 逻辑结束。
- 四套用户方案固定权重，不调参；收盘信号、次日开盘进入、20 日收盘退出、单边 6bp。59 个不重叠
  月度样本中，AI 重仓/科技防守/轮动杠铃/AI退出的中位数分别 `-0.13%/-0.30%/-0.30%/-0.16%`，
  胜率均低于 50%。严格同状态只有 5 个重叠日期、全部为负；去重后 1 个 episode，轮动杠铃净收益
  `-1.24%`、最大回撤 `-4.62%`，evidence gate `block`。
- 原 75% 轮动目标按 gate 缩为 37.5% 总暴露/62.5% 现金；7 月 16 日只有红利 ETF 首笔 6.25%
  满足收盘条件，消费仍须等 `0.648-0.655` 回踩或 `0.670` 放量突破，初始现金为 93.75%。其余按文档
  回踩/均线修复/放量突破条件等待，不因跌深抄底。最终 artifact：
  `state/research_runs/20260716T094924Z-ashare-etf-month/ashare_etf_month.json`。
- 验证：聚焦 `8 OK`、本地完整 `1042 OK`、compileall 与 `git diff --check` 通过；仅有既存
  `cta_data.py` UTC deprecation warning。未访问 VPS/private API，未写 paper/live state，未下单。

### Frozen trade-flow v1 failed preregistered BTC/BNB/SOL replication

- 在任何复制 archive 内容读取前生成 preregistration `20260716T083420Z-alpha-agent-tradeflow-replication`，
  protocol hash `d2c9ca4e...d03da1`：BTC/BNB/SOL 复用 exact ETH contract，禁止调参/符号筛选；只有该符号
  Q1 discovery 通过才读 April；PBO 保持 fail-closed `1.0`。
- Q1 dataset `20260716T085640Z-alpha-agent-historical-tradeflow`：BTC/BNB/SOL 9/9 月包 checksum verified，
  295,897,363 raw trades -> 78,624 个 5m rows，各币 100% coverage、1 segment、0 ID gap。
- frozen discovery 全败：BTC IC/residual `0.007095/-4.150084%`，BNB `-0.016277/-8.680766%`，SOL
  `-0.028842/-5.175364%`；45/46/46 entries、turnover budget 2.0、filter coverage 1.0。三币 April
  `oos_consumed=false`，没有为结果补看新窗口。
- 最终 replication report `20260716T090929Z=block_correlation_stress`；matching metrics
  `20260716T090941Z`，scorecard `20260716T090958Z=block`，G0-G3/GX pass，G4/G5/G6 block。读法：ETH historical OOS 正收益
  保留，但缺乏跨 majors 复制；frozen v1 停止晋级，不做 runtime parity/A10/paper/live。
- 验证：replication/trade-flow/validation 聚焦 `14 OK`、Alpha 全聚焦 `95 OK`、本地完整 `1034 OK`，
  compileall 与 `git diff --check` 通过；仅有既存 `cta_data.py` UTC deprecation warning。公共历史 cache
  当前 `5.8G`，Mac 仍余约 `87GiB`；未访问 VPS/private API、未恢复 collector/cron、未写 paper/live state。

### Frozen trade-flow v1 survived Q1 and April historical OOS, but scorecard remains blocked

- 新增 `historical_tradeflow.py` + CLI/tests：official `aggTrades/bookTicker` ZIP、SHA-256 sidecar、CSV schema、
  事件顺序/跨 archive ID、5m coverage/segment 审计。真实 BTC 2024-01-01 双源 12,747,457 事件聚合为
  288/288 完整桶，0 checksum/schema/sequence/crossed-book blocker；artifact `20260716T042522Z`。
- Q1 ETH 3 个月 113,092,010 aggregate trades -> 26,208 个 5m 桶，100% coverage、1 segment、跨月 ID gap 0；
  artifact `20260716T043347Z-alpha-agent-historical-tradeflow`。
- 在读取新窗口前冻结唯一 1h 合同 `agg_trade_imbalance_z168_entry2_hold6_cooldown18_momentum_v1`，hash
  `2b61627c...c9094`，trial count 1。Q1 discovery rank IC `0.024647`、41 entries、net residual
  `+7.163938%`，触发一次性 2024-04 OOS。
- April 数据从 3/24 预热，4/1 强制空仓后才计分；720/720 小时 feature coverage，rank IC `0.039999`、
  16 entries、net residual `+6.196189%`、去掉最大单小时贡献 `+2.427747%`。data/experiment artifact：
  `20260716T044055Z-alpha-agent-historical-tradeflow`、`20260716T044439Z-alpha-agent-tradeflow-experiment-01`。
- fixed-candidate validation `20260716T044644Z`：frozen-beta April residual `+7.663555%`、purged time-fold pass，
  但 DSR `0.915342`，单候选 PBO 不可识别并 fail closed `1.0`。metrics `20260716T044704Z`，scorecard
  `20260716T044724Z=block`：G0-G3/GX pass；G4(DSR/PBO)、G5(correlation stress)、G6(forward paper) block。
- 只运行 Mac public historical research；未访问 VPS/private API、未恢复 cron/collector、未写 paper/live state、
  未下单。读法：保留第一份正历史 edge，但不进 A10/paper/live，不在 Q1/4 月调参或继续消费月份。
- 验证：trade-flow/validation 聚焦 `19 OK`、Alpha 全聚焦 `92 OK`、本地完整 `1031 OK`，compileall 与
  `git diff --check` 通过；仅有既存 `cta_data.py` UTC deprecation warning。

### Alpha S3 switched to historical-first after VPS collector failure

- 只读复核确认 production root crontab 已于 2026-07-11 资金撤出后停用；X4 历史 JSONL 16,204 行、0
  invalid/倒序/重复，最后状态空仓无订单，但未访问私有账户确认当前交易所仓位。
- VPS 7 天 collector 只完成约 21 小时：22 个闭段 19 pass/3 block，最后闭段有约 38 分钟 market-event
  空窗、trade gap/stale/depth unanchored，另留 orphan partial；Mac offload 在第 0 阻断段 fail closed。
  Owner 确认 VPS 随后因内存不足多次重启。session 不 resume、不拼接，共享 VPS 不再重跑长采集。
- 新增 `src/qount/alpha_agents/historical_microstructure.py` 与 CLI/tests，只读 Binance 官方 checksum sidecar。
  artifact `20260716T032055Z-alpha-agent-historical-microstructure`：40 probes 中 36 available、4 missing、
  0 error；`aggTrades=12/12`、`bookTicker=8/12`、`bookDepth=8/8`、`metrics=8/8`。确认 public
  `bookDepth` 是百分比聚合深度，不可冒充 `U/u/pu` diff-depth；forceOrder/receive latency 仍无等价历史源。
- 新增 `historical_derivatives.py` 与 CLI/tests：并发回填 daily metrics，官方 SHA-256 checksum 校验，输出
  兼容 feature runner 的 OI/taker-ratio artifact。Q1 artifact `20260716T033710Z-alpha-agent-historical-derivatives`
  为 364/364 archives、104,332 rows、四币覆盖 `0.995230`、0 error；2024-02-16 共同约 10.5 小时缺口
  写为新 `segment_id`。feature runner 同步禁止 derivative lookback、K线收益、beta、label/PnL 跨 gap。
- 2024Q1 5m 第一版 72-candidate kill-test 最终 artifact `20260716T035639Z-alpha-agent-feature-experiment`：训练
  冻结 `oi_delta_lb1_thr0_long_short`，train/OOS rank IC `0.022246/0.029326`，但 turnover `4,223`、
  OOS beta-residual `-56.833338%`。metrics `20260716T035652Z`，scorecard `20260716T035706Z=block`。
  rolling beta 完全按 gap 重置前的 `034337Z/034357Z/034406Z` 数值相同，仅保留为中间证据。读法：
  历史数据主路径成立，当前简单高换手阈值策略失败；不进 A10/paper/live，不在 Q1 继续挑参。
- 验证：Alpha 全聚焦 `78 OK`，本轮历史/feature 聚焦 `36 OK`，本地完整 `1017 OK`，compileall 与
  `git diff --check` 通过。只运行 Mac 研究链；未同步 VPS、未访问私有账户、未恢复 collector/cron、
  未运行远端测试。

---

更早记录（2026-07-14 及以前）见 [archive/update-log-archive.md](archive/update-log-archive.md)。
