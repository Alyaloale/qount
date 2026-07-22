# qount 更新记录

更新时间：2026-07-22

这份文档只记录近期关键变更、验证结果和当前读法。当前策略结论以
[current.md](current.md) 为准；复跑命令和跨主机操作细节放在
[quick-handoff.md](quick-handoff.md)。

## 2026-07-22

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

## 2026-07-14

### Alpha S3 collector migrated to isolated VPS + verified Mac offload

Owner 明确确认采用“VPS 持续采集、Mac 定时拉取”的低成本方案。本轮只处理 Binance USD-M public data；
不读取账户/API key、不下单、不写 paper/live state。部署目录为 `/root/qount-alpha`，与交易生产
`/root/qount` 隔离；原 qount production crontab 仍保持停用。

实现：

- session schema 升为 `v0.3`，manifest/segment/daily 使用 `session_relative_v1` / `segment_relative_v1`
  路径合同；VPS 归档搬到 Mac 后无需改 raw 或伪造来源即可重新做完整 verifier。verifier 继续兼容现有 v0.2
  Mac 会话，并按旧 manifest 原始字段重算 contract hash。
- 新增 `live_collector_offload.py` / `alpha_agent_collector_offload.py`。Mac 仅处理 manifest 已登记的闭段，
  rsync 后逐段核对 bytes/SHA、artifact config/audit，并完整重跑 `audit_event_file`/depth replay；通过后先写
  本地 `verified` receipt，再调用远端幂等 ack。远端再次核对 manifest/SHA/bytes，按 `verified -> deleted`
  两阶段 fsync receipt 仅删除 `events.jsonl.gz`，保留小型审计 JSON。重复 pull 不重复复制或删除。
- gzip writer 加入周期磁盘检查。正式 VPS 合同固定 `min_free_disk_bytes=8GiB`；Mac pull 固定保留 20GiB，
  任一端空间不足均不继续删除/写爆磁盘。
- 新增独立 `qount-alpha-collector.service`：`Restart=no`、Nice/idle IO、CPU 80%、MemoryHigh 450M、
  MemoryMax 600M、TasksMax 64；Mac `com.qount.alpha-collector-offload` 在登录/唤醒后运行并每 30 分钟重试。

真实 VPS 验证：

```text
60s smoke: 104,338 market events, pass_data_smoke, blockers=none
2x15s smoke: 45,105 events, 1,122 depth replay updates
connection restart/boundary gap/trade-book-depth break=0
snapshot/trade/depth/event-time strict errors=0
remote verifier=pass_data_gate
Mac pull: copied=2, verified=2, remote_deleted=2
Mac final verifier=pass_data_gate; VPS raw=0, artifact=2, partial=0
idempotent second pull: copied=0, verified=0, remote_deleted=0
```

正式新会话：

```text
service=qount-alpha-collector.service
remote_session=/root/qount-alpha/state/research_runs/20260714T135630Z-alpha-agent-live-collector-session-7d-vps
stable_link=/root/qount-alpha/state/alpha-collector-current
started_at=2026-07-14T13:56:47Z
expected_end=2026-07-21T13:56:47Z
duration=604800s; segment_limit=3600s; Restart=no
initial_status=running/incomplete; NRestarts=0; boot-enabled=false; MemoryCurrent~40MB
```

旧 Mac session `20260714T112649Z-alpha-agent-live-collector-session-7d` 已停止，约 492MB partial 原样保留，
并用 `superseded_by_replacement_session` 指向新 VPS session；verifier 稳定返回 `incomplete`。两边 raw 不得
拼接后声称连续 7 天。代码验证：collector/session 聚焦 `30 OK`、Alpha `66 OK`、最终完整回归
`1006 OK`，`compileall`/`git diff --check`/LaunchAgent plist/systemd unit 均通过。正式 7 天完成前仍不构造
训练集、不启动 A10、不 forward paper、不 live。

### Alpha Agents S3 deterministic session verifier

在 7 天 collector 不重启、继续写 raw 的前提下，补齐最终只读 data gate：

- `live_collector_session.py` 新增 `verify_live_collector_session()`；默认最低 604,800 秒，校验 0 resume、
  strict S3 symbols/streams/threshold、contract hash、aggregate、daily/segment 一致性、session 内路径约束、
  raw bytes/SHA，并重新执行每段 depth replay。
- gate 对 connection/snapshot final error、trade gap/out-of-order、bookTicker out-of-order、depth
  break/resync/overflow/invalid/empty/crossed/unanchored、event missing/future/stale 全部零容忍，并要求四币
  每段都有 bookTicker/aggTrade/depthUpdate/snapshot。
- CLI 新增 `--verify-session-dir` 和测试覆盖用 `--minimum-session-duration-seconds`；退出码 0 为
  `pass_data_gate`，2 为 `incomplete`，1 为其他 `block_data`。入口只读，不获取 collector lock、不访问网络。
- 单测覆盖 replayable pass、running/incomplete、raw tamper、malformed numeric field 和 path escape。

真实对照：

```text
20260714T112301Z 2x15s smoke + --minimum 30 -> pass_data_gate, exit 0
same smoke + default 604800s minimum -> block_data(minimum_duration_not_met), exit 1
20260714T112649Z formal 7d running session -> incomplete, exit 2
```

验证：collector/session 聚焦 `26 OK`；Alpha `63 OK`；完整回归 `1002 OK`；`compileall` OK。完整回归仍只有
既有 `cta_data.py` UTC deprecation warning。正式 7 天进程保持 launchd runs=1、PID/锁不变，partial raw
继续增长；本轮未重启 collector、未训练、未访问账户/VPS、未触碰 paper/live。

### Alpha Agents S3 continuous writer rotation + 7-day forward-data run started

沿 resumable session 的 `restart_per_segment` 负结果继续推进，仍只做 Mac/Binance public-data research；
不读取账户、不碰 VPS、不训练、不写 paper/live。

实现：

- `src/qount/alpha_agents/live_collector.py`
  - 新增连续多段 capture：public/market websocket 在 segment 边界不关闭，connection id 跨段保持；后续段
    写 `connection_continuation`，audit 接受它作为连接证据但不伪装成新连接。
  - 旧 gzip close、`.partial` 原子 rename 和新 gzip open 在同一写锁内完成；修掉首版 close/open 之间可能
    让 route writer 看到空指针并丢边界事件的竞态。
  - writer generation 切换后 depth route 立即补 snapshot；每段固化 aggTrade/bookTicker/depth first/last
    sequence boundary。
  - 已关闭段的 gzip audit、实际订单簿 replay、SHA 和 artifact 写入转到独立 spawn process；父进程继续接收
    websocket，并在结果返回后原子更新 session/daily manifest。
- `src/qount/alpha_agents/live_collector_session.py`
  - schema 升为 `v0.2`，connection mode 固定为 `continuous_in_stream_rotation`。
  - 段界要求 connection id 相同，并检查 aggTrade `last+1`、bookTicker 单调和 depth `pu/u` 连续；真实重启、
    sequence break、单段 block 或 orphan 均 fail closed。
- 测试新增 connection continuation 与双段不重连 writer rotation；伪 public/market route 两段只建立两条
  websocket，而不是每段重建两条。

首版同步 audit 双段 artifact `20260714T112005Z-alpha-agent-live-collector-session` 虽为
`pass_data_smoke`，但首段收尾读取 gzip 时让第二段 p95 latency 从 `250ms` 升到 `2.5s`、max `1.625s`；
该实现被独立 audit process 取代，不作为最终读数。

最终真实命令：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_live_collector.py \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT \
  --snapshot-interval-seconds 5 \
  --session-duration-seconds 30 \
  --segment-duration-seconds 15
```

最终 artifact：

- `state/research_runs/20260714T112301Z-alpha-agent-live-collector-session/alpha_agent_live_collector_session.json`
- 两段共 16,723 events、948 replay updates，均 `pass_data_smoke`。
- connection restart/boundary gap/boundary trade-book-depth break 全为 0；snapshot final error、段内 trade gap、
  depth break、invalid/empty/crossed、event missing/future/stale 全为 0。
- 两段 p95 latency 均 `250ms`，max `241ms` / `309ms`；gzip test、SHA 和离线 replay parity 全通过。

验证：Alpha 聚焦 `56 OK`；本地完整 `995 OK`；`compileall` OK。完整回归只有既有
`cta_data.py` UTC deprecation warning。

正式 7 天 session 已启动：

```text
path=state/research_runs/20260714T112649Z-alpha-agent-live-collector-session-7d/
launchd_label=com.qount.alpha-collector-7d-20260714-v2
started_at=2026-07-14T11:27:20Z
expected_end=2026-07-21T11:27:20Z
duration=604800s; segment_limit=86400s; UTC midnight clipping=true
current_status=running/incomplete
```

LaunchAgent 的 `KeepAlive=false`，配合 `caffeinate -i`、session 单写锁和原子 raw；启动后 launchd/PID/lock
一致，partial raw 持续增长。一次更早的 `20260714T112533Z-...-7d` 预启动因发现
`launchctl submit` 隐含 KeepAlive 而立即停止，0 completed segment，不作为证据。当前仍未通过 7 天 gate；
完成前不构造训练集、不启动 A10、不 forward paper、不 live。

### Alpha Agents S3 public microstructure collector + actual depth replay

继续推进 Strategy V0 的 S3 `live_collector_v0`，保持 Mac/local research-only：只读取 Binance USD-M
public websocket 和 public depth snapshot，不读取私钥或账户、不访问 private endpoint、不写 paper/live
state、不碰 VPS。S1/S2/G4 的负向结论不变，A10 仍暂停。

实现：

- `src/qount/alpha_agents/live_collector.py`
  - 采集 `bookTicker`、`aggTrade`、100ms diff-depth、`forceOrder` 到 gzip JSONL，artifact 固化 config
    hash、raw SHA-256、来源、holdout role 和 research/live 边界。
  - public/market route 独立连接；审计 aggTrade id gap、bookTicker 乱序、depth `pu/u` 连续性、snapshot
    anchor/resync/buffer、连接错误与 event-time latency/future/stale。
  - public WS-API depth snapshot 增加默认 2 次有限重试、0.5 秒间隔；瞬时失败写 `snapshot_retry`，只有
    耗尽才写 `snapshot_error`，最终错误率默认门槛保持 `1%`，不再靠放宽到 50% 获得 pass。
  - 新增实际订单簿 replay：用 Decimal 档位加载 snapshot、依序应用 diff，懒堆维护 top-of-book，并
    阻断非法价量、空簿、crossed book；artifact 报告 replay updates 和四币最终 bid/ask。
- CLI 默认流从逐笔 `trade` 对齐为 S3 设计指定的 `aggTrade`，并暴露 snapshot retry 参数。
- 新增/扩展 collector 单测，覆盖路由、消息标准化、gap/乱序、future event、snapshot retry 恢复/耗尽、
  gzip 离线 replay、订单簿更新和 crossed-book 阻断。

严格复现先得到：

- `state/research_runs/20260714T092326Z-alpha-agent-live-collector/alpha_agent_live_collector.json`
- BTC 45 秒、8,419 条事件；aggTrade gap 与 depth sequence 均为 0，但首次 snapshot
  `SSLEOFError` 让最终 error rate 为 1/3，严格 `1%` 门槛下 `block_data`。

有限重试与实际 replay 完成后的最终四币命令：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_live_collector.py \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT \
  --duration-seconds 60 \
  --snapshot-interval-seconds 15
```

最终 artifact：

- summary：`state/research_runs/20260714T093402Z-alpha-agent-live-collector/alpha_agent_live_collector.json`
- raw：`state/research_runs/20260714T093402Z-alpha-agent-live-collector/events.jsonl.gz`
- `holdout_role=forward_research_data_only`，`training_allowed=false`，`replayable=true`。

结果：

```text
market_events=23,339
bookTicker/aggTrade/depthUpdate/forceOrder=20,524/833/1,981/1
snapshots=16/16; retries=0; final errors=0
aggTrade sequence observations=829; missing=0; out_of_order=0
depth sequence observations=1,915; breaks=0; resyncs=0; buffer_overflows=0
depth replay updates=1,919; invalid_levels=0; empty_books=0; crossed_books=0
all four symbols anchored; event missing/future/stale=0/0/0
verdict=pass_data_smoke
```

public route 的第一次建连在 `connection_open` 前遇到一次 `SSLEOFError`，随后 public-2 成功并持续到
deadline；没有形成市场数据 gap。BTC `092617Z` 和四币 `092732Z` 预验证也通过，最终读法以原生包含
replay 指标的 `093402Z` 为准。

验证：

- Alpha/数据/artifact 聚焦：`68 OK`。
- collector 单测：`11 OK`。
- 本地完整回归：`987 OK`（仅既有 `cta_data.py` UTC deprecation warning）。
- `compileall`：OK。

读法：S3 gap/replay 实现与 60 秒四币严格 data smoke 通过，但这不是策略 edge 或 promotion。计划要求的
连续 7 天采集尚未完成；在 7 天按日 gap/replay gate 通过前，不构造训练集、不启动 A10、不 forward
paper、不 live。

### Alpha Agents S3 resumable session + restart-gap kill-test

在单段 gap/replay smoke 之后继续固化 7 天采集合同，仍只做 Mac public-data research，不碰 VPS、账户、
paper/live 或训练。

实现：

- `src/qount/alpha_agents/live_collector.py`
  - 单段 raw 先写 `events.jsonl.gz.partial`，capture 完成后才原子 rename；summary JSON 使用 fsync + rename。
  - 同一输出目录已有 raw/partial/summary 时拒绝覆盖。
  - capture 记录 public/market 各 route 的首末市场事件接收时间，跨段 gap 不再用包含 snapshot worker
    等待时间的函数返回时间估算。
- `src/qount/alpha_agents/live_collector_session.py`
  - 冻结 collector/session contract hash，按 UTC 午夜裁剪 segment。
  - 原子维护 session manifest 与 daily manifest，汇总逐段 audit、raw SHA 和 boundary gap。
  - 本机单写锁防并发；死 PID lock 留 stale 证据；失败 partial/raw 作为 orphan 保留并阻断。
  - 支持 `--max-segments` 暂停和 `--resume-session-dir` 恢复，只按 manifest 冻结 config 续跑。
  - `boundary_gap_present`、orphan、session error 或任一段 block 均 fail closed；manifest 明确
    `segment_connection_mode=restart_per_segment`、`continuous_gate_eligible`。
- CLI 增加 `--session-duration-seconds`、`--segment-duration-seconds`、`--max-segments` 和
  `--resume-session-dir`；不带 session 参数时单次采集行为不变。
- 测试覆盖 UTC 午夜裁剪、单段原子封口、暂停/恢复、contract 复用、daily manifest、失败 orphan 和锁清理。

真实暂停/恢复 artifact：

- `state/research_runs/20260714T094828Z-alpha-agent-live-collector-session/alpha_agent_live_collector_session.json`
- 15 秒 segment 1 结束后为 `paused/incomplete`，resume 后完成 segment 2；`resume_count=1`。
- 两段均 `pass_data_smoke`，合计 23,288 events、724 depth replay updates；4 次 snapshot retry 全恢复，
  final error=0；段内 trade gap/depth break/invalid/empty/crossed/stale/future 全为 0。
- 两段 raw SHA-256 与 manifest 一致，离线 replay 均保持 `pass_data_smoke`，无遗留 partial/tmp/lock。
- 人工暂停形成 `25,612ms` boundary gap，因此总 session `block_data(boundary_gap_present)`。

为排除“只因人工暂停”又跑不暂停的两段 kill-test：

- `state/research_runs/20260714T100453Z-alpha-agent-live-collector-session/alpha_agent_live_collector_session.json`
- 两段均 `pass_data_smoke`，合计 15,522 events、919 depth replay updates；所有段内 data blocker 为 0，
  SHA 与离线 replay 全通过，无 orphan。
- 但串行关闭第一段 collector、等待 snapshot worker、原子写 manifest、再建立第二段 websocket，按 route
  实际市场事件覆盖产生 public `6,277ms`、market `7,499ms` gap；总 session `verdict=block_data`、
  `continuous_gate_eligible=false`。
- 早期 `20260714T095422Z` 用 capture 返回时间得到 `82ms`，该口径低估真实断流，已被 `100453Z`
  route-coverage artifact 取代，不作为结论。

验证：

- collector/session 聚焦：`16 OK`。
- Alpha/数据/artifact 聚焦：`73 OK`。
- 本地完整回归：`992 OK`（仅既有 `cta_data.py` UTC deprecation warning）。
- `compileall`、`git diff --check`、最终 manifest 断言、两段 raw SHA-256：OK。

读法：恢复、原子性和逐日证据面通过，但 restart-per-segment 不能满足“连续 7 天”。这是一条基础设施
负结果，不是策略负结果；当前不得直接启动 7 天或训练。下一步实现同 websocket 连接内 writer rotation，
先用双段 smoke 证明零连接空窗和逐段 replay，再启动 7 天 forward-research data gate。

## 2026-07-11

### VPS 资源耗尽事故修复与 live 调度降频

2026-07-10 23:47 CST 前后，VPS 出现 ping/TCP 可达但 SSH banner、HTTPS 和阿里云工作台全部
协议层超时。控制台硬重启恢复后，只读核对确认服务、容器、磁盘和 DNS 当前正常；事故证据指向
root crontab 的 qount 进程堆积，而不是 Caddy/new-api 网关故障。

根因链：

- active `cxd_live_cron.sh live` 每 2 分钟启动，`cxd_publish_cron.sh` 每 5 分钟，paper 每日启动；
  三个入口均无 `flock`、无总运行 timeout。
- Binance/DNS 抖动时，带私钥的 CCXT `load_markets()` 会先调用名为 public、实际走私有 SAPI 的
  `fetchCurrencies -> /sapi/v1/capital/config/getall`；卡住的 bash/python 不退出，后续 cron 继续叠加。
- 1.6G VPS 最终进入进程堆积 + swap/fork 饥饿，sshd/Caddy/new-api 仍 listen，但无法及时 fork/处理连接。

实现：

- 新增 `scripts/desktop/cron_guard.sh`：外层 GNU `timeout` 对整个进程组设置墙钟上限，内层
  non-blocking `flock` 防止同一任务重叠；缺少安全命令时 fail closed。三个 active cron 均接入。
- live 默认 110 秒、publisher 90 秒、paper 1800 秒；crontab 外层再加略大的 `flock + timeout` 兜底。
- 新增 `deploy/cron/qount-production.crontab` 固化生产调度；外层锁直接使用
  `/run/lock/qount-*.lock`，避免 VPS 重启后 `/run/lock/qount/` 子目录消失导致 cron fail closed。
- `scripts/sync-to-vps.sh` 同步清单加入 `deploy/`，避免以后只更新 Mac 上的 crontab 模板。
- live 从 `*/2` 降到 `*/5`，publisher 改到 `2-57/5` 错峰。X4 信号是日线，且持仓已有交易所原生
  reduce-only STOP_MARKET，因此降频减少 60% 调度/API 压力，不改变信号、仓位或止损语义。
- `cxd_live_cron.sh` 删除编排层重复的 `load_markets + fetch_balance` 私有读取；订单 sizing 仍只由
  `x4_live.py` 的实时 walletBalance 决定。交易腿失败时保留最后成功网页快照，不更新时间伪装成功。
- `src/qount/exchange_utils.py` 明确 `fetchCurrencies=False`，并提供有界
  `QOUNT_CCXT_TIMEOUT_MS`（默认 10 秒、范围 1-60 秒）。不重试订单提交，避免超时后的成交歧义。
- 未改策略权重、2x 上限、short gate、scale-out、exchange-native stops 或 carry paused。
  “促进盈利”本轮只做可证明的可用性/成本改善；没有新的 OOS 证据，不临时调高杠杆或改 alpha。

验证：

- 本地：`bash -n` 通过；cron guard/CCXT/X4/RV 聚焦 `158 OK`；完整 `976 OK`。
- VPS：选择性同步本轮文件，避免部署工作区其他未提交内容；远端聚焦 `141 OK`、当前全量 `865 OK`。
- 事故后初次只读状态：服务 active，123 processes，available memory 923M，swap 0，DNS 正常。
  部署后 `00:20`/`00:25` 两个 live tick 与 `00:17` publisher 均成功，无 guard alert/skip、无残留
  qount 进程；live armed、trend-only、3 条 short 持仓和 exchange-native stops 均存在，0 新订单。
- 容量残余：完整服务负载下 `MemAvailable≈322M`，主要 RSS 为 `new-api≈433M`、`sub2api≈380M`，
  qount 进程为 0。这不推翻事故根因，但说明 1.6G 共机仍脆弱；长期需加内存或拆机。
- 原 crontab 已备份到 `/root/crontab.qount-before-20260711.bak`。

## 2026-07-10

### Alpha Agents kline taker-flow + rolling-beta IC

继续推进 Strategy V0 的 S1 `kline_taker_flow_v0`，保持 research-only：只读取 Binance public dump、
public funding 和既有 runtime exchange rules，不读取私钥、不访问账户、不写 paper/live state、不碰 VPS。

实现：

- `src/qount/grid/data.py`
  - `Bar` 向后兼容保留 Binance kline 原生 `quote_volume`、`trade_count`、
    `taker_buy_base_volume`、`taker_buy_quote_volume`。
- `src/qount/alpha_agents/feature_experiment.py` v0.2
  - 新增 `kline_taker_imbalance`：lookback 窗口聚合主动买量不平衡。
  - 新增 `kline_taker_pressure_change`：相邻窗口 taker imbalance 变化。
  - 新增 `kline_quote_volume_z` 和 `kline_realized_vol_change`。
  - 新增 `polarity=+1/-1`，同一 feature 可审计地测试顺向/反向关系。
  - 新增 `selection_metric=rank_ic` 和 `beta_lookback_bars`。
  - IC label 使用仅依赖过去 bar 的 rolling BTC beta：
    `ETH forward return - beta_asof * BTC forward return`，无未来数据进入 beta。
  - rolling beta/forward residual label 使用前缀统计一次性预计算，不再由每个 candidate 重扫
    2016-bar 窗口；h3 同配置复跑约 37 秒，IC 和 OOS 输出与优化前一致。
- `scripts/research/alpha_agent_feature_experiment.py`
  - 新增 `--polarities`、`--selection-metric`、`--beta-lookback-bars`。
- `tests/test_grid_data.py` / `tests/test_alpha_agents_feature_experiment.py`
  - 覆盖原生 kline flow 字段、四类新特征、inverse polarity 和 rank-IC 选择。

真实 S1 固定合同：

```text
market=Binance USD-M
symbols=BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT
strategy_symbol=ETHUSDT
interval=5m
window=2024-01..2024-08
train_fraction=0.75 (约 Jan-Jun train / Jul-Aug OOS)
horizons=3,6,12 bars
lookbacks=3,6,12,24
families=kline taker imbalance/pressure, quote-volume z, realized-vol change, momentum
polarities=+1,-1
selection=train rolling-beta rank IC
beta_lookback=2016 bars (约 7 天)
trials=40 per horizon
cost=taker fee 5bps + slippage 2bps per turnover + funding
runtime filters=min_notional_coverage 1.0
```

结果：

| horizon | selected | train rank IC | OOS rank IC | OOS beta | OOS net residual | verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 3 | `kline_taker_imbalance_lb3_inv` | 0.01993 | 0.03481 | 0.464995 | -166.019% | block |
| 6 | `momentum_lb24_inv` | 0.02349 | 0.02344 | 0.019812 | -91.363% | block |
| 12 | `momentum_lb24_inv` | 0.03678 | 0.01326 | 0.830903 | -58.191% | block |

h3 的 Jul/Aug gross return 分别约 `+34.83%/+2.34%`，但 turnover cost 约
`199.64%/206.78%`；弱 taker-flow 信息无法覆盖 taker 执行成本。h6/h12 训练选择回到已失败的
price momentum inverse，并没有形成新的 taker-flow edge。S1 kill 条件中 `net residual <= 0` 和
`cost-stress net <= 0` 三个 horizon 全触发；h3 train IC 也略低于 `0.02`，h12 OOS IC 低于 `0.02`
且 beta > `0.5`。

feature artifacts：

- h3: `state/research_runs/20260710T132313Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`
- h6: `state/research_runs/20260710T132029Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`
- h12: `state/research_runs/20260710T131856Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`

metrics / scorecards：

- h3: `20260710T132403Z-alpha-agent-beta-metrics-02` / `20260710T132414Z-alpha-agent-scorecard`
- h6: `20260710T132403Z-alpha-agent-beta-metrics` / `20260710T132414Z-alpha-agent-scorecard-01`
- h12: `20260710T132403Z-alpha-agent-beta-metrics-01` / `20260710T132414Z-alpha-agent-scorecard-02`

读法：`kline_taker_flow_v0` 当前 sign/taker 执行合同停止，不围绕已看 Jul-Aug 继续调 threshold 后宣称
OOS。它没有资格进入 A10、forward paper 或 live。下一步先补 walk-forward/DSR/PBO adapter；若后续
设计 sparse/no-trade 执行，必须在新的 discovery/window 上验证。更高信息量的 bookTicker、aggTrade、
diff-depth、forceOrder 仍走 S3 collector + gap/replay，不从当前 kline 结果外推。

### Research artifact 同秒并发覆盖修复

并行生成 h3/h6/h12 beta metrics 时发现：原 `persistent_research_dir` 只使用秒级时间戳，同一秒的
多个进程会得到同一目录并覆盖 JSON。实际第一次并行运行三条命令都返回
`20260710T131019Z-alpha-agent-beta-metrics`，最终只剩一个 payload。

修复：

- `src/qount/artifacts.py` 现在先原子创建目录；同秒碰撞依次分配原名、`-01`、`-02`。
- 新增 `tests/test_artifacts.py`，固定同一 `utc_now` 连续写两份 artifact，验证目录和 payload 独立。
- 修复后并行 metrics 实测得到 base/`-01`/`-02` 三条独立路径；并行 scorecard 同样独立。

验证：

- Alpha/数据/artifact 聚焦测试：`52 OK`。
- 完整本地测试：`PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'`：
  `965 OK`。
- `compileall`：OK。
- `git diff --check`：OK。
- 性能/数值 parity：
  `state/research_runs/20260710T132950Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`
  与原 h3 artifact 的 selected candidate、rank IC、beta 和 net residual 一致。

读法：这是多 agent/多实验并发下的数据完整性修复，不改变任何策略、paper 或 live 行为。

### Alpha Agents G4 validation adapter

继续推进 deterministic promotion 的 G4 层。此前 beta metrics 对 DSR/PBO/purged-CV/embargo 默认写
blocking value；本轮新增可重放的 validation artifact，并把它与源 feature experiment 做强绑定。

新增：

- `src/qount/alpha_agents/validation.py`
  - 从源 feature artifact 读取冻结 config，使用本地 Binance cache 重放全部 candidate。
  - 普通 feature artifact 不写大型 matrix；validation 运行时临时构造日级成本后收益矩阵和
    决策级 feature/rolling-beta residual label。
  - DSR 评估源实验实际选中的 candidate，trial benchmark 使用全 40-cell Sharpe dispersion。
  - CSCV/PBO 在每个 IS 组合内按源实验 `selection_metric=rank_ic` 选 winner，再用 OOS
    beta-residual Sharpe 排名；不是另一个 Sharpe-selection pipeline。
  - purged-CV 使用双侧训练、1 日 embargo；walk-forward 使用 expanding prior-only 训练。
  - `purged_cv_pass` 要求 purged 和 walk-forward 同时满足至少 60% 正 fold且 aggregate OOS > 0。
- `scripts/research/alpha_agent_validation.py`
  - research-only CLI，输出 `state/research_runs/*/alpha_agent_validation.json`。
- `scripts/research/alpha_agent_beta_metrics.py`
  - 新增 `--validation-path`；validation 的 source feature path 必须与 `--returns-path` 完全一致。
- `src/qount/alpha_agents/metrics.py`
  - 将匹配 validation 的 DSR/PBO/purged/largest/embargo 和 artifact/source path 写入 metrics。
- `tests/test_alpha_agents_validation.py`
  - 稳健矩阵可填充 G4、负矩阵保持 block、G6 不被绕过、source mismatch 拒绝、artifact writer。

真实 h3 验证命令：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_validation.py \
  --feature-experiment-path state/research_runs/20260710T132950Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json \
  --fold-count 5 --embargo-periods 1 --pbo-splits 10
```

最终 validation artifact：

- `state/research_runs/20260710T134718Z-alpha-agent-validation/alpha_agent_validation.json`

读数：

```text
source_candidate=kline_taker_imbalance_lb3_thr0_long_short_inv
source_candidate_parity=true
selected_per_period_sharpe=-2.276393
expected_max_per_period_sharpe=1.389110
DSR=3.1863e-152
PBO=0.781746 (197/252 CSCV combinations overfit)
purged_cv=0/5 positive, aggregate=-99.999975%
walk_forward=0/5 positive, aggregate=-99.998755%
largest_contributor_removed=-99.997476%
embargo_applied=true
```

重要口径修正：首次 artifact
`state/research_runs/20260710T134252Z-alpha-agent-validation/alpha_agent_validation.json` 的 PBO 使用
Sharpe 作为 IS winner 选择标准，得到 `PBO=0.0`，与源实验 `rank_ic` 选择语义不一致。实现评审后已
改为 source-selection CSCV；该早期 artifact 被 `134718` 取代，不进入 metrics/scorecard 或项目结论。

最终 metrics / scorecard：

- `state/research_runs/20260710T134758Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`
- `state/research_runs/20260710T134808Z-alpha-agent-scorecard/alpha_agent_scorecard.json`

G4 blockers：

```text
dsr_below_threshold
pbo_above_threshold
purged_cv_not_passed
largest_contributor_removed_not_positive
```

验证：

- 本地完整测试：`970 OK`。
- Alpha/数据/validation/artifact 聚焦测试：`57 OK`。
- compileall、CLI `--help`、`git diff --check`：OK。

读法：G4 现在可以被真实 quant artifact 填充，不再只能默认阻断；但 S1 的四项反过拟合证据全部失败。
低 PBO 不能替代正收益，本轮最终 PBO 也在匹配 source selection 后升至 `0.7817`。S1 继续不进 A10、
paper 或 live；下一步转 S3 collector 数据完整性层，而不是继续在已看窗口调参。

## 2026-07-08

### Alpha Agents 多智能体研究骨架

按 owner 要求先搭建多 agent 架构，用于搜集资料、优化方案、后续接量化；当前只做
research-only scaffold，不改 VPS、不写 paper/live state、不下单、不 arm live。

新增 [alpha-agent-plan.md](alpha-agent-plan.md) 和 `src/qount/alpha_agents/`：

- `models.py`：`AgentRole` / `ResearchTask` / `AgentReport` / `SourceRef` contract。
- `roles.py`：默认 10 个角色，并支持 `--roles-path` 从 JSON 替换角色。
- `tasks.py`：5 个 seed tasks，并支持 `--tasks-path` 从 JSON 替换任务。
- `sources.py`：Binance 官方数据源、DSR/PBO/AFML、本项目证据和 relay GLM-5.2 source book。
- `llm.py` / `validators.py`：OpenAI-compatible adapter 默认关闭；显式 `--with-llm` +
  `QOUNT_ALPHA_AGENT_API_KEY` 才调用 `https://llm.alyaloale.com/v1` / `glm-5.2`；已加
  report validator 和 forbidden output scanner，拦截订单、目标权重、杠杆和 live arm 语言。
- `orchestrator.py`：research-only orchestrator，写 `state/research_runs/*/alpha_agent_plan.json`。
- `scripts/research/alpha_agent_plan.py`：薄 CLI，不读取私钥、不调交易所私有接口、不写生产 state。
- `tests/test_alpha_agents.py`：覆盖离线运行、artifact 写入、角色/任务替换。

默认角色分层：

- LLM research/review：`market_data_scout`、`exchange_rules_scout`、`quant_librarian`、
  `feature_designer`、`experiment_designer`、`red_team`、`ops_auditor`。
- deterministic/quant：`model_trainer`、`backtest_auditor`、`risk_architect`，明确
  `llm_allowed=false`。

外部资料 agent 首批结论已纳入架构约束：Binance spot/futures 数据源分离，WS order book 必须
snapshot+diff+sequence 校验，funding 按 `fundingTime` as-of 对齐，OI 长历史不能只依赖近月
REST hist，多 agent 必须共享 quota/rate-limit，回测/paper/live 必须复用 filter/fee/min-notional
validator。验证层继续沿用 DSR/PBO/purged-CV/triple-barrier，LLM 不能输出订单、目标权重或风控
override。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents`：`6 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/alpha_agents scripts/research/alpha_agent_plan.py`：OK。
- `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_plan.py --task-id beta_residual_target_v0 --print-json`：OK，生成 research artifact
  `state/research_runs/20260707T162147Z-alpha-agent-plan/alpha_agent_plan.json`。
- `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_plan.py --task-id source_map_v0`：OK，生成 research artifact
  `state/research_runs/20260707T164144Z-alpha-agent-plan/alpha_agent_plan.json`。

读法：这是研究组织和证据收集层，不是策略 promotion。下一步应把 seed task 接到 deterministic
dataset / label / backtest / A10 training runner，而不是让 LLM 直接给交易信号。

### Alpha Agents deterministic promotion scorecard

继续推进多 agent 架构的量化接入口，新增 deterministic scorecard 层；它不调用 LLM、不访问交易所
私有接口、不写 paper/live state，只读 metrics JSON 并输出 gate artifact。

新增：

- `src/qount/alpha_agents/promotion.py`：`evaluate_promotion_scorecard`、G0-G7/GX gate、
  metrics loader 和 artifact writer。
- `scripts/research/alpha_agent_scorecard.py`：薄 CLI，读 `--metrics-path`，输出
  `state/research_runs/*/alpha_agent_scorecard.json`，verdict 为 block 时以 exit code 2 返回。
- `tests/test_alpha_agents_promotion.py`：覆盖 pass、beta/cost blocker、LLM 越界 blocker、
  live pilot blocker、artifact writer。
- `tests/fixtures/alpha_agent_passing_metrics.json`：可复现 smoke fixture，也是后续 A10/backtest
  输出 contract 的最小示例。

当前 gate：

- `G0 proposal`：必须有 label / benchmark / data / cost / kill line，且必须是 beta-residual target。
- `G1 data`：point-in-time、as-of join、可重放、data/code/config hash、trial count、
  runtime exchangeInfo、filter validator。
- `G2 baseline`：residual net return > 0，并打败 cash / BTC B&H / TOP3 EW B&H / current live baseline。
- `G3 cost`：扣 taker/spread/funding/min-notional 后仍正，worst-case 成本仍正，maker fill 不能靠假设。
- `G4 anti-overfit`：DSR、PBO、purged-CV、embargo、去掉最大贡献窗口后仍正。
- `G5 breadth/capacity`：effective breadth、相关性压力、capacity。
- `G6 paper`：validation_v1 / forward paper、30 天、0 schema/unmanaged/unknown filter、订单可 replay。
- `G7 live pilot`：7 天 dry-run、pilot cap <= 200 USDT、禁提现、one-way、isolated、rollback 已写。
- `GX LLM boundary`：LLM 不得生成订单、目标权重或风控 override。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents tests.test_alpha_agents_promotion`：
  `11 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/alpha_agents scripts/research/alpha_agent_plan.py scripts/research/alpha_agent_scorecard.py`：OK。
- `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_scorecard.py --metrics-path tests/fixtures/alpha_agent_passing_metrics.json --target paper`：OK，
  生成 `state/research_runs/20260707T165208Z-alpha-agent-scorecard/alpha_agent_scorecard.json`，
  `verdict=pass`。

读法：这只是 gate harness，不是策略通过。真实策略必须由 dataset / label / backtest / A10 trainer
产出 metrics，不能手填 fixture 值。下一步应实现第一个 deterministic experiment runner，把
`beta_residual_target_v0` 接到实际 Binance futures 历史数据和 TOP3/BTC baseline attribution。

### Alpha Agents beta-residual metrics builder

继续把 agent 架构接向确定性量化实验，新增第一个 deterministic experiment adapter：从对齐的
period return 序列生成 promotion metrics，先解决 MiniTrend 复盘暴露的核心问题——不能再把 raw
return / 牛市 beta 当 alpha。

新增：

- `src/qount/alpha_agents/metrics.py`：`ReturnRow`、`load_return_rows`、
  `build_beta_residual_metrics`、`write_beta_metrics_artifact`。
- `scripts/research/alpha_agent_beta_metrics.py`：薄 CLI，支持 JSON / JSONL / CSV returns 输入，
  输出 `state/research_runs/*/alpha_agent_beta_metrics.json`。
- `tests/test_alpha_agents_metrics.py`：覆盖 JSON/CSV loader、beta residual、artifact writer、以及
  “缺 DSR/PBO/paper 证据必须被 scorecard block”。
- `tests/fixtures/alpha_agent_returns.json`：正 residual 的小样本 fixture。

计算口径：

- 输入 period returns 使用 percent points。
- `beta_to_btc = cov(strategy, btc) / var(btc)`。
- `net_residual_return_pct = sum(strategy_return_pct - beta_to_btc * btc_return_pct)`。
- 同时输出策略复合收益、BTC / TOP3 equal-weight / current live baseline 复合收益和超额。
- 若 `meta.costs_included` 不为 true，则 `cost.net_after_cost_pct` 默认 0，G3 block。
- DSR/PBO/purged-CV/paper/capacity 等高阶字段默认写 blocking value，只有真实 quant artifact
  可以补齐。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents tests.test_alpha_agents_promotion tests.test_alpha_agents_metrics`：
  `14 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/alpha_agents scripts/research/alpha_agent_plan.py scripts/research/alpha_agent_scorecard.py scripts/research/alpha_agent_beta_metrics.py`：OK。
- `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_beta_metrics.py --returns-path tests/fixtures/alpha_agent_returns.json --holdout-role discovery --source-label fixture-beta --print-json`：OK，
  生成 `state/research_runs/20260708T033300Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`，
  `net_residual_return_pct=4.0`、`beta_to_btc=0.5`。
- 再用该 metrics 跑 scorecard：
  `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_scorecard.py --metrics-path state/research_runs/20260708T033300Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json --target paper --print-json`
  返回 exit code 2 且 `verdict=block`，block gate 为 G4/G5/G6；这是预期结果，说明单一正残差不会被误晋级。

读法：这一步把“去 beta”做成了可执行 contract，但还没接真实 Binance 数据或 A10 模型。下一步应做
dataset builder：从 Binance public dump / existing backtest artifacts 生成对齐 returns，再喂给
beta metrics 和 scorecard。

### Alpha Agents source scoring + Binance public returns

继续按 owner 要求让多 agent 能“搜集足够丰富的信息并学会甄别”，同时接 Binance research 数据层。
新增两条 research-only 入口，均不使用私有 Binance key、不写 paper/live state、不碰 VPS。

新增：

- `src/qount/alpha_agents/knowledge.py` + `scripts/research/alpha_agent_sources.py`：对 `SOURCE_BOOK`
  资料源按 `official_exchange_doc` / `official_exchange_data` / `primary_research` / `book` /
  `security_reference` / `tutorial` 等类型评分，输出 `accept|review|reject` 和 allowed use。
  教程/博客只能作为 learning material，不能满足 promotion gate。
- `src/qount/alpha_agents/binance_returns.py` + `scripts/research/alpha_agent_binance_returns.py`：
  复用 `qount.grid.data.load_klines` 从 Binance public dump 生成对齐 returns；内置
  `sma_long_cash` / `sma_long_short` 只是 smoke candidate，不是推荐策略。
- `tests/test_alpha_agents_knowledge.py` / `tests/test_alpha_agents_binance_returns.py`：离线 fake zip
  验证 source scoring 和 public dump returns builder，不触网。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents tests.test_alpha_agents_promotion tests.test_alpha_agents_metrics tests.test_alpha_agents_knowledge tests.test_alpha_agents_binance_returns`：
  `18 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/alpha_agents scripts/research/alpha_agent_plan.py scripts/research/alpha_agent_scorecard.py scripts/research/alpha_agent_beta_metrics.py scripts/research/alpha_agent_sources.py scripts/research/alpha_agent_binance_returns.py`：OK。
- Source report smoke：
  `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_sources.py --tags binance_market_data,validation,agent_security`
  生成 `state/research_runs/20260708T034323Z-alpha-agent-knowledge/alpha_agent_knowledge.json`，
  `source_count=15`、`accept=13`、`review=2`、`reject=0`。
- Binance public dump smoke：
  `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_binance_returns.py --start-month 2024-01 --end-month 2024-03 --symbols BTCUSDT,ETHUSDT,BNBUSDT --strategy-symbol ETHUSDT --market um --interval 1d --fast-window 10 --slow-window 30`
  生成 `state/research_runs/20260708T034514Z-alpha-agent-binance-returns/alpha_agent_binance_returns.json`，
  `period_count=85`、`total_turnover=2.0`。
- 该 returns artifact 进入 beta metrics：
  `state/research_runs/20260708T034535Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`，
  `net_residual_return_pct=7.717009`、`beta_to_btc=0.595825`。
- 再进 scorecard：
  `state/research_runs/20260708T034554Z-alpha-agent-scorecard/alpha_agent_scorecard.json`，
  `verdict=block`，block gate 为 G1/G2/G3/G4/G5/G6：未用 runtime exchangeInfo/filter validator、
  跑输 BTC/TOP3、BTC beta 过高、未计 funding/min-notional、无 DSR/PBO/paper。

读法：Binance 数据链路已通，甄别机制也工作。这个 smoke candidate 有正 residual 但被正确阻断，
说明系统不会把教程/LLM/单窗口收益误当 alpha。下一步应补真实 dataset builder 的 runtime
exchangeInfo/filter/funding/min-notional 层，或把现有 MiniTrend/X4 artifacts 转成同一 returns
contract 做统一归因。

### Alpha Agents Binance runtime rules + funding

继续推进 owner 要求的 Binance 接入，但保持 research-only：只使用公开 `exchangeInfo` 和
Binance public dump，不读取私有 Binance key、不访问账户、不下单、不写 paper/live state。

新增：

- `src/qount/alpha_agents/exchange_rules.py`：解析 Binance `exchangeInfo`，抽取
  `PRICE_FILTER`、`LOT_SIZE`、`MARKET_LOT_SIZE`、`MIN_NOTIONAL`，对目标名义订单做
  min-notional / minQty / maxQty / step-size coverage。
- `scripts/research/alpha_agent_exchange_rules.py`：薄 CLI，拉公共 exchangeInfo 或读取 raw
  exchangeInfo JSON，输出瘦身 rules artifact。
- `src/qount/alpha_agents/binance_returns.py`：新增 `include_funding`、`account_equity_usdt`、
  `target_notional_fraction`、`leverage`、`symbol_rules/exchange_info` 参数；returns artifact 现在
  可写入 `exchange_rules_source=runtime_exchange_info`、`filter_validator_reused=true`、
  `min_notional_coverage`、`funding_included` 和 funding cashflow。
- `scripts/research/alpha_agent_binance_returns.py`：新增 `--exchange-rules-path`、
  `--fetch-exchange-info`、`--include-funding`、`--account-equity-usdt`、
  `--target-notional-fraction`、`--leverage`。
- `tests/test_alpha_agents_exchange_rules.py`：覆盖 runtime rules 解析、rules artifact roundtrip、
  400 USDT min-notional coverage 和 funding cashflow。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents_exchange_rules tests.test_alpha_agents_binance_returns tests.test_alpha_agents_metrics tests.test_alpha_agents_promotion tests.test_alpha_agents_knowledge tests.test_alpha_agents`：
  `22 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/alpha_agents scripts/research/alpha_agent_exchange_rules.py scripts/research/alpha_agent_binance_returns.py scripts/research/alpha_agent_beta_metrics.py scripts/research/alpha_agent_scorecard.py scripts/research/alpha_agent_sources.py scripts/research/alpha_agent_plan.py`：OK。
- `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_exchange_rules.py --market um --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT`
  生成 `state/research_runs/20260708T035439Z-alpha-agent-exchange-rules/alpha_agent_exchange_rules.json`；
  `returned_symbol_count=4`、`trading_symbol_count=4`。
- `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_binance_returns.py --start-month 2024-01 --end-month 2024-03 --symbols BTCUSDT,ETHUSDT,BNBUSDT --strategy-symbol ETHUSDT --market um --interval 1d --fast-window 10 --slow-window 30 --include-funding --exchange-rules-path state/research_runs/20260708T035439Z-alpha-agent-exchange-rules/alpha_agent_exchange_rules.json`
  生成 `state/research_runs/20260708T035513Z-alpha-agent-binance-returns/alpha_agent_binance_returns.json`；
  `period_count=90`、`total_turnover=2.0`、`min_notional_coverage=1.0`、
  `funding_settlement_count=270`、`total_funding_return_pct=-3.533644`。
- 该 returns artifact 进入 beta metrics：
  `state/research_runs/20260708T035520Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`；
  `net_residual_return_pct=-1.165668`、`beta_to_btc=0.552037`。
- 再进 scorecard：
  `state/research_runs/20260708T035535Z-alpha-agent-scorecard/alpha_agent_scorecard.json`；
  `verdict=block`。G1 的 runtime rules/filter evidence 已补上；G2/G3/G4/G5/G6 仍阻断，原因包括
  residual 为负、跑输 BTC/TOP3、BTC beta 过高、cost net 为负、无 DSR/PBO/paper 证据。

读法：这一步补的是“交易所真实规则和成本证据”，不是新策略。ETH SMA smoke 被打回是好事，说明
scorecard 没有因为接上 Binance 就放水。下一步应实现 feature/label/model experiment runner：
1m/5m USD-M bars + funding/OI/bookTicker 特征，输出 beta-residual OOS scorecard；A10 只接训练和
评估，不接订单决策。

### Alpha Agents feature experiment runner

继续把多 agent 架构接向确定性量化实验。新增第一个“模型实验接口”：它不让 LLM 下单，也不直接
启用 A10；先用无新依赖的 feature grid 固定 contract：

```text
public klines/funding -> feature grid -> train split selection -> OOS returns
  -> beta metrics -> promotion scorecard
```

新增：

- `src/qount/alpha_agents/feature_experiment.py`：读取 Binance public klines/funding，构造
  `momentum` / `reversal` / `relative_momentum` / `vol_adjusted_momentum` 特征；在 train split 上按
  beta-residual 选候选；在 OOS split 输出 returns；可复用 runtime exchangeInfo filter coverage。
- `scripts/research/alpha_agent_feature_experiment.py`：薄 CLI，支持 `--lookbacks`、`--thresholds`、
  `--modes`、`--horizon-bars`、`--include-funding`、`--exchange-rules-path`、
  `--fetch-exchange-info`。
- `tests/test_alpha_agents_feature_experiment.py`：离线 fake public dump/funding/exchangeInfo，覆盖
  OOS returns、rules/funding 元数据、metrics/scorecard 接入。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents_feature_experiment tests.test_alpha_agents_exchange_rules tests.test_alpha_agents_binance_returns tests.test_alpha_agents_metrics tests.test_alpha_agents_promotion tests.test_alpha_agents_knowledge tests.test_alpha_agents`：
  `24 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/alpha_agents scripts/research/alpha_agent_feature_experiment.py scripts/research/alpha_agent_exchange_rules.py scripts/research/alpha_agent_binance_returns.py scripts/research/alpha_agent_beta_metrics.py scripts/research/alpha_agent_scorecard.py scripts/research/alpha_agent_sources.py scripts/research/alpha_agent_plan.py`：OK。

真实 public-data smoke：

- `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_feature_experiment.py --start-month 2024-01 --end-month 2024-03 --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT --strategy-symbol ETHUSDT --market um --interval 1h --horizon-bars 6 --train-fraction 0.6 --lookbacks 6,12,24,48 --thresholds 0,0.0025,0.005 --modes long_short,long_cash,short_cash --include-funding --exchange-rules-path state/research_runs/20260708T035439Z-alpha-agent-exchange-rules/alpha_agent_exchange_rules.json`
  生成 `state/research_runs/20260708T040453Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`；
  选中 `relative_momentum_lb12_thr0_long_short`，candidate count `144`、train periods `1309`、
  raw OOS bars `874`、OOS 月度 periods `2`。
- runtime rules/funding evidence：`filter_validator_reused=true`、`funding_included=true`、
  `min_notional_coverage=1.0`、OOS filter `107/107` pass、funding settlements `272`。
- OOS 结果：`strategy_total_return_pct=-30.103078`、BTC `+39.471843`、TOP3 EW `+54.382491`、
  `beta_to_btc=7.494191`、`net_residual_return_pct=-302.677680`。
- beta metrics：
  `state/research_runs/20260708T040502Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`。
- scorecard：
  `state/research_runs/20260708T040514Z-alpha-agent-scorecard/alpha_agent_scorecard.json`，
  `verdict=block`。G1 data gate 已通过；G2/G3/G4/G5/G6 阻断，原因包括残差为负、跑输 cash/BTC/TOP3/live、
  BTC beta 过高、成本后为负、没有 anti-overfit/paper 证据。

读法：feature-grid runner 已经能把模型实验产物接进统一 scorecard，但第一批简单价量特征在 OOS
上严重失败。后续不能围绕该候选继续调参；下一步应补 walk-forward/DSR/PBO，然后接更高信息量的
1m/5m microstructure、OI、bookTicker 和 funding-as-feature 数据，A10 只替换 model trainer 层。

### Local GLM agents + Strategy V0

按 owner 要求把 gateway key 放入本机用户级环境，而不是仓库或 artifact：

- `~/.qount/alpha-agent.env`，权限 `600`。
- `~/.zshrc` source 该文件。
- `AlphaLLMConfig.from_env()` 现在会自动读取该文件，因此非交互 research CLI 也能拿到本地 key。
- 本地参数：`QOUNT_ALPHA_AGENT_MAX_CONCURRENCY=3`、
  `QOUNT_ALPHA_AGENT_MAX_TOKENS=4000`、`QOUNT_ALPHA_AGENT_TIMEOUT_SECONDS=180`、
  `QOUNT_ALPHA_AGENT_MAX_RETRIES=1`。

工程修复：

- `src/qount/alpha_agents/llm.py`：压缩 prompt，但保留 4000 token 输出上限；要求严格五字段 JSON；
  支持 code fence / 前后文本里的 JSON 抽取；数组可容忍 dict/string/number；解析或校验失败时自动
  重试一次；单 agent LLM 请求失败会生成 blocked report，不中断整批。
- `src/qount/alpha_agents/orchestrator.py`：`ThreadPoolExecutor` 并发执行 role/task reports，
  report 顺序按原始 task/role 稳定输出。
- `src/qount/alpha_agents/sources.py`：补 Binance official OI、taker buy/sell ratio、top trader
  ratio、notional/leverage bracket source refs。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents tests.test_alpha_agents_feature_experiment tests.test_alpha_agents_exchange_rules tests.test_alpha_agents_metrics tests.test_alpha_agents_promotion tests.test_alpha_agents_knowledge tests.test_alpha_agents_binance_returns`：
  `24 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/alpha_agents scripts/research/alpha_agent_plan.py`：OK。
- Config readback 不打印 key，只确认：
  `api_key_present=True`、`model=glm-5.2`、`timeout_seconds=180`、`max_tokens=4000`、
  `max_concurrency=3`。

Agent runs：

- 首次 `intraday_microstructure_v0` 暴露 GLM JSON 问题：
  `state/research_runs/20260708T043424Z-alpha-agent-plan/alpha_agent_plan.json`，一个 report 返回
  `{}`，一个 report 因未加引号表达式导致 JSON parse error。
- 修复后重跑 `intraday_microstructure_v0`：
  `state/research_runs/20260708T043816Z-alpha-agent-plan/alpha_agent_plan.json`。`feature_designer`
  和 `experiment_designer` 均 `status=ok`，提出 taker-flow、spread/top-of-book、funding、liquidation、
  mark/premium 和 OI（待 source）方向。
- 全量 seed plan：
  `state/research_runs/20260708T044141Z-alpha-agent-plan/alpha_agent_plan.json`。13 个 research/worker
  reports 中，LLM research/review 角色产出 source map、beta-residual label、microstructure feature、
  A10 lane、small-account risk 设计；deterministic-only roles 仍离线 scaffold。

基于 agent 结果更新 [alpha-agent-plan.md](alpha-agent-plan.md) 的
`Strategy V0: Microstructure Residual Alpha`：

- market：Binance USD-M futures，先 BTC/ETH/BNB/SOL。
- target：1m/5m 的 BTC/TOP3 beta-residual net return，不看 raw return。
- 可立即历史 kill-test：kline taker-flow、funding、runtime exchangeInfo、OI hist、taker buy/sell ratio。
- 需先采集再 forward：bookTicker、aggTrade、diff-depth、forceOrder、mark/index/premium。
- S1 `kline_taker_flow_v0`：public 1m/5m klines + funding + exchangeInfo，kill if OOS IC < 0.02、
  net residual <= 0、BTC beta > 0.5 或 cost-stress net <= 0。
- S2 `derivative_state_v0`：funding + OI + taker ratio，kill if PBO >= 0.5、DSR < 0.95、
  去掉最大贡献月后 residual <= 0。
- S3 `live_collector_v0`：7 天 bookTicker/aggTrade/diff-depth/forceOrder gap/replay，不训练不过关数据。

读法：agent 已经用于策略设计，但仍是 research-only。V0 的价值不是“发现已可交易策略”，而是把下一步
可执行 kill-test 收束到两个历史特征线和一个数据采集线，避免继续在已失败的 SMA/趋势候选上调参。

### Alpha Agents derivatives-state loader

继续推进 Strategy V0 的 S2 `derivative_state_v0` 输入层。按 Binance 官方 docs，`/futures/data/*`
recent data endpoints 只适合作近 30 天 research/forward 输入，不能用来冒充 2021-2026 长历史回测。

新增：

- `src/qount/alpha_agents/derivatives_state.py`
  - `openInterestHist` parser/cache/chunking。
  - `takerlongshortRatio` parser/cache/chunking。
  - `/fapi/v1/openInterest` current OI parser。
  - 30 天窗口硬限制。
  - coverage / gap diagnostics。
  - public REST transient error retry。
- `scripts/research/alpha_agent_derivatives_state.py`
  - research-only CLI，不读私钥、不访问账户、不下单。
- `tests/test_alpha_agents_derivatives_state.py`
  - fake REST JSON 覆盖解析、artifact、30 天限制。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents_derivatives_state tests.test_alpha_agents_knowledge tests.test_alpha_agents tests.test_alpha_agents_feature_experiment tests.test_alpha_agents_exchange_rules tests.test_alpha_agents_binance_returns tests.test_alpha_agents_metrics tests.test_alpha_agents_promotion`：
  `29 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/alpha_agents scripts/research/alpha_agent_derivatives_state.py`：OK。
- Source scoring：
  `PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_sources.py --tags binance_derivatives_state --print-json`
  6 个 derivatives 官方源全部 `accept`。

真实 public REST smoke：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_derivatives_state.py \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT \
  --period 5m \
  --days 1
```

artifact:

- `state/research_runs/20260708T045352Z-alpha-agent-derivatives-state/alpha_agent_derivatives_state.json`

结果：

- `open_interest_hist_count=1152`
- `taker_long_short_count=1152`
- `current_open_interest_count=4`
- `error_count=0`
- 每个 symbol OI 与 taker ratio 均为 288 rows、0 gaps、coverage ≈ `0.9965`。

读法：OI/taker ratio 输入层可用，但它是 recent-history / forward research 数据。下一步应把该
artifact 接入 feature experiment runner，生成 `derivative_state_v0` 的 OOS returns，再走
beta-residual metrics 和 scorecard；不能直接把数据接入等同于策略通过。

### Alpha Agents derivative-state feature runner

继续推进 Strategy V0 的 S2 `derivative_state_v0`，把 recent OI / taker buy-sell ratio 接进
deterministic feature experiment runner。仍然 research-only：不读私钥、不访问账户、不写 paper/live
state、不下单。

新增/修改：

- `src/qount/alpha_agents/feature_experiment.py`
  - 新增 `--kline-source` 对应的 `public_dump` / `rest` 数据源分支。
  - `rest` 分支读取 Binance USD-M `/fapi/v1/klines` JSON，并可按 derivatives-state artifact 的
    `window.start_ms/end_ms` 对齐 recent data。
  - 新增 derivatives-state as-of feature：`oi_delta`、`oi_value_delta`、`taker_ratio`、
    `taker_imbalance`。
  - 新增 `min_feature_coverage` gate，防止无数据重叠时选出 0-position 假候选。
  - 输出 diagnostics 记录 kline source、derivatives-state source/history-limit 和 feature coverage。
- `scripts/research/alpha_agent_feature_experiment.py`
  - 新增 `--kline-source public_dump|rest`、`--derivatives-state-path`、`--min-feature-coverage`。
- `tests/test_alpha_agents_feature_experiment.py`
  - 新增 fake REST kline JSON 覆盖，离线验证 `kline_source=rest`。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents_feature_experiment`：
  `4 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_alpha_agents_derivatives_state tests.test_alpha_agents_knowledge tests.test_alpha_agents tests.test_alpha_agents_feature_experiment tests.test_alpha_agents_exchange_rules tests.test_alpha_agents_binance_returns tests.test_alpha_agents_metrics tests.test_alpha_agents_promotion`：
  `31 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/alpha_agents scripts/research/alpha_agent_derivatives_state.py scripts/research/alpha_agent_plan.py scripts/research/alpha_agent_feature_experiment.py`：
  OK。

真实数据限制：

- Mac 到 `https://fapi.binance.com/fapi/v1/klines` 当前直连超时 / SSL EOF，REST kline 实网 smoke
  未生成 artifact；这不是私有账户问题，curl 到同 endpoint 也超时。
- `data.binance.vision` public daily dump 可用但发布不齐：运行时 BTC/BNB 的
  `2026-07-07` 5m daily dump 已发布，ETH/SOL 同日文件仍 404。因此完整
  BTC/ETH/BNB/SOL recent smoke 被 `min_feature_coverage` 正确拦截，而不是产生假结果。

可复现实跑：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_feature_experiment.py \
  --start-month 2026-07 \
  --end-month 2026-07 \
  --symbols BTCUSDT,BNBUSDT \
  --strategy-symbol BNBUSDT \
  --market um \
  --kline-source public_dump \
  --interval 5m \
  --horizon-bars 3 \
  --train-fraction 0.5 \
  --lookbacks 1,3,6 \
  --feature-families oi_delta,oi_value_delta,taker_imbalance,taker_ratio \
  --thresholds 0,0.001 \
  --modes long_short,long_cash,short_cash \
  --include-funding \
  --output-granularity bar \
  --derivatives-state-path state/research_runs/20260708T045352Z-alpha-agent-derivatives-state/alpha_agent_derivatives_state.json \
  --exchange-rules-path state/research_runs/20260708T035439Z-alpha-agent-exchange-rules/alpha_agent_exchange_rules.json
```

结果：

- feature artifact：
  `state/research_runs/20260708T093014Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`。
- selected candidate：`oi_delta_lb1_thr0_long_short`。
- feature coverage：`0.113095`。
- OOS：`strategy_total_return_pct=-7.056039`、BTC `+1.403648`、equal-weight `+1.135040`、
  `beta_to_btc=-0.000082`、`net_residual_return_pct=-7.301083`。
- metrics：
  `state/research_runs/20260708T093052Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`。
- scorecard：
  `state/research_runs/20260708T093102Z-alpha-agent-scorecard/alpha_agent_scorecard.json`，
  `verdict=block`，G2/G3/G4/G5/G6 阻断。

读法：derivatives-state 接入链路通过，但第一刀 univariate OI/taker-ratio smoke 没有 alpha，且只是
discovery。不能 forward paper、不能 live、不能把 BNB 两币单窗结果扩展为策略结论。下一步应：
1. 等 ETH/SOL 5m daily dump 发布或 `fapi.binance.com` REST 路由恢复后复跑完整
   BTC/ETH/BNB/SOL。
2. 补 kline taker-flow feature family，利用 public dump kline 内置 taker buy volume，而不是只看 OI。
3. 接 DSR/PBO/walk-forward adapter；若 residual 仍 <= 0，直接 kill S2，不启动 A10。

## 当前总览

- 旧 line A live 仍关闭：`QOUNT_LIVE_ENABLE=false`，不能 forward paper / live。
- 当前 live / paper forward / dashboard 的生产真相是 VPS：
  `qount-vps:/root/qount`（仓库外SSH inventory）。WSL 只作为历史研究 artifact / legacy 追溯环境。
- 2026-07-07 已新增 [project-rules.md](project-rules.md)：项目规则、文档分类、研究线隔离、
  执行记录、反过拟合规范、代码架构和弃用清理纪律。
- 当前有效 AI 路由是 `QOUNT_AI_MODEL=gpt-5.5`；`gpt-5.4` 会让回测 AI 请求失败。
- 最新有效 `gpt-5.5` 13-window walk-forward 合计
  `sum_realized_return_pct=+1.6184470183%`，但只有 `2/13` 正收益窗口。
- WS-4 `multi_range_action_pullback_sma_fast_gt008` 已完成隔离 shadow proof；
  两个独立窗口都没有成交，AI 对 24 条匹配候选全部 `hold`，不能加 gate。
- WS-4 另外两条候选也已复扫：`range_return24_gt012` 样本不足且 h3/h12 为负；
  `eth_reclaim_long_failed_breakdown_*` 所有 horizon 均值为负或样本不足。
- WS-2 min-edge 复核显示，已知 4 笔开仓 edge 最高只有 `0.00393`；
  收紧阈值会砍掉正收益窗口或直接 0 交易，不支持作为盈利改进。
- 继续补的 5/30 OOS 和 39-backtest root scan 仍是 `ready_tags=[]`；
  没有可进 gate 的新候选。
- 2026-05-31 已新增 [holdout.md](holdout.md)：已看过窗口固定为 `discovery_pool`，
  `validation_pool_v1` 从 2026-06-01T00:00:00Z 之后开始；promotion gate 改为
  `G_paper` / `G_live`。
- 研究工具新增 `--holdout-role`、`--ai-decision-cache`、
  `setup-edge-walk-forward`、`candidate-walk-forward`、
  `scripts/sync-to-wsl.sh`、`scripts/run-wsl-tests.sh`；不改 entry / risk / live。
- 2026-05-31 新增 `ai-hold-baseline`：可从既有 artifact 还原 fresh-entry prompt，
  统计 v1/v2/v3 研究 prompt 的 hold-bias；不改 live / `run-once`。
- 2026-05-31 新增 `idle-window-diagnostic`：可从既有 artifact 汇总 0 交易窗口的
  setup / candidate / AI hold 读数；diagnostic only，不改 live / `run-once`。
- 2026-05-31 新增 `setup-model-compare` 和 setup_model `v2_interactions` plumbing；
  第一版 ETH-only compare 没有形成可交易 lift，不能替换主线模型。
- `research-slice-scan` 新增 `offline_future_edge_readiness`，旧
  `shadow_candidate_readiness` 保留为兼容别名。
- 2026-06-04 第一次 `validation_v1` once-only 端到端验证失败：
  `sum_realized_return_pct=-0.7159862916%`、`positive_realized_windows=0/2`、
  `paper_filled=7`、`total_review_missed_candidate_move=2`。不能 forward paper。
- 2026-06-04 盈利导向新增 `eth_short_range_noise_terminal_washout` hard blocker：
  已失败窗口降级 discovery 后转正为 `+0.9173089048%`。新的
  2026-06-03..2026-06-04 第一次 validation 被 AI relay `auth_unavailable` 污染；
  relay 恢复后同策略 infra rerun 无 AI 错误，但 `sum_realized_return_pct=-1.1912362466%`，
  仍不能 promotion。
- 2026-06-05 已按 `profit-engineering-plan.md §10` 启动盈利工程路线：先做 S0/S1'
  地基和“频段 × 策略族”选择扫描，不再默认把 5m 作为给定频段。
- 2026-06-05 新增 `strategy-selection-scan` 并完成 30 天 discovery 初扫；初扫 top cell
  是 `1d ts_mom`，但 rank-IC 很弱且有效广度约 1.13，不能 promotion。
- 2026-06-05 120 天和月度 sensitivity 否定了把 `1d ts_mom lb12/h1` 直接推进 S2；
  5m / CARRY 只在 zero-cost 下转正，maker-ish 成本后为负。
- 2026-06-05 S-CARRY 后续验证继续否定 promotion：WLD/SOL post-only 在 6/1-6/5
  after-tail 为正需要超过 100% maker fill；entry-only basis regime filter 在 120 天或
  6/1-6/5 上均不过关。
- 2026-06-05 top12 `1d ts_mom` 扩币 sanity 也不过关：120 天 `sum=-2.6698947371`，
  2/3/4 月全负，只有 5 月单月正。
- 2026-06-05 新增 prediction-family lookback/holding grid，低频 top12 扫描找到当前最强
  discovery cell：`4h xs_mom lookback=24 holding=6`，120 天 `sum=+3.5251307739`、
  `rank_ic=+0.0523457125`；但 2026-03 月度 sanity 为负，且 holding=6 仍需
  overlap-aware 组合复核。
- 2026-06-05 新增 `--directional-overlap-mode stride` overlap sanity；同一 fixed cell
  120 天 stride `sum=+0.5087944384`、`rank_ic=+0.0607409120`，但 2/3 月仍负，只能推进
  S1.1/S1.2，不能 paper。
- 2026-06-05 新增 `--directional-evaluation-mode portfolio_replay` 限仓组合 replay；
  同一 fixed cell、`max_open_positions=12` 的 120 天 replay `sum=+0.2974912983`、
  `sharpe=+7.1945433715`，但 2026-03 仍负，仍不能 paper。
- 2026-06-05 新增 `--directional-exit-mode triple_barrier`；同一 fixed cell 的 simple
  TP/SL barrier 120 天四组全负，最不差 `tp=0.030/sl=0.015` 也只有
  `sum=-0.1635040433`，进一步否定 paper。
- 2026-06-05 给 triple-barrier artifact 补 `directional_exit_reason_counts`；最不差
  `tp=0.030/sl=0.015` 的 120 天 stop-loss `873`、take-profit `400`、time `173`，
  解释了为什么 close-to-close/replay 正收益会被 fixed TP/SL 打负。
- 2026-06-05 新增 `--directional-purged-cv-folds` / `--directional-embargo-bars`；
  fixed `4h xs_mom lb24/h6` close/replay 的 4-fold 诊断为 `3/4` folds 正，但
  2026-03-03..2026-04-01 fold 为负，仍不能 paper。
- 2026-06-05 N1 新增波动率缩放 triple-barrier（σ 缩放 TP/SL）；修正了 fixed barrier 的
  非对称止损病，但没有任何 σ 设置能跑赢"无 barrier 持有到期" close-exit 基线 `+0.297`，
  最佳 `tp4/sl4=+0.165`、3 月仍负、~90% 收益来自 5 月，N1 门控未通过，仍不进 S2。
- 2026-06-05 N1 新增 entry 侧 regime dispersion 门；`thr0.034` 总收益不变(`+0.299`)、
  Sharpe `7.19→8.00`、回撤降、并把 2026-03 从负翻正、4 月全 ≥ 0,首个改善月度稳健性的
  子步骤;但属 in-sample 阈值、5 月仍约 82% 收益、无新 OOS，N1 仍未过、仍不进 S2。
- 2026-06-05 按 §5/§9.x 补 Deflated Sharpe Ratio；选出候选的 81-cell 网格 DSR ≈ `0.082`,
  最佳 per-period Sharpe `0.278` < 噪声期望最大值 `0.407`——候选的网格内选择优势大概率是
  多重检验假象。S2 门控加硬:新 OOS 正 + 可接受 DSR/PBO 才进 S2。
- 2026-06-05 再补 PBO/CSCV：pbo 4h=`0.020`/1h=`0.056`/1d=`0.214`(全 < 0.5)。与 DSR 互补——
  弱但排名稳定的横截面动量结构,但量级太弱不足以确认盈利;同频段 config 高相关令 PBO 偏低。
- 结论：有历史盈利样本，不等于稳定盈利；仍处于 research-only。
- 2026-06-06 决策（项目所有者确认）：`4h xs_mom lb24/h6` 候选按 §7 诚实退出。DSR ≈ `0.082`
  太弱(最佳 per-period Sharpe `0.278` < 噪声期望最大 `0.407`)、无可执行 exit 跑赢持有、~82%
  收益集中在 5 月——三条件齐备。不在 2026-06-04..06 的 ~2 薄天(~12 根 4h bar)上消耗
  `validation_v1` once-only 日期。**关闭该候选的 S2 晋级路径**;研究转向 §10 换频段 / 换特征源
  (微结构 / funding / 时序基础模型特征),或按 §7 接受研究价值、停止追盈利。详见
  `profit-engineering-plan.md §11.7`。硬边界不变(live 关闭、不 forward paper、不放宽 broad gate)。
- 2026-06-06 §10 换特征源第一刀 kill-test:**funding 作横截面预测特征 = 证伪**。新增
  `xs_funding` / `xs_funding_rev`(funding as-of join 无前视当信号,复用 IC/DSR/PBO harness)。
  top12 120 天 discovery post-cost:rank-IC 全 ≤ `0.030`(< 价量动量 `0.052` < 要求 `0.06`);
  唯一正 cell `1d xs_funding_rev h6` 的 rank-IC ≈ `0.005` ≈ 0(噪声/overlap);DSR ≈ `0.25`
  (best per-period sharpe `0.094` < 噪声期望最大 `0.156`);PBO ≈ 0.49–0.55;4h/8h 全被成本打负。
  继 CARRY 现金流后,funding 第二种用法也证伪,最便宜新源耗尽,压向 §7 诚实止盈。只跑 discovery。

## 2026-07-07

### MiniTrend Agent 小资金方案文档

按 owner 要求新增 `docs/mini-trend-agent/` 设计文档，作为线 D / X4 的小资金子方案草案，
当前不改变 VPS 生产真相、不 arm 新策略、不修改 `current.md`。文档拆成五份：

- `README.md`：400 USDT 小盘目标、依据、推荐 `MiniTrend-5` 轮廓和非目标。
- `architecture.md`：确定性交易核心 + LLM 多 agent 审计/研究层架构，建议代码模块和 state 目录。
- `execution.md`：从 backtest、paper、dry 到小额 live pilot 的阶段化执行手册和回滚规则。
- `contracts.md`：结构化 JSON contract 和 agent 边界。
- `coding-rules.md`：文件拆分、依赖、风控编码和测试原则。

读法：这是设计和执行计划，不是 promotion 证据；LLM agent 只允许输出报告/建议，不能生成订单或绕过风控。

复盘后补充 v0.2 收紧：

- 新增 `review.md`，记录 v0.1 的复盘问题、v0.2 默认实现、scorecard、promotion gate 和 agent 接入顺序。
- `README.md` 明确 v0.2 默认只做 `spot + long/cash + TOP5`；swap、short gate、carry 都是后续独立研究项。
- `architecture.md` / `execution.md` 增加 `scorecard.py`、scorecard state、30 天 paper、7 天 dry、
  min-notional coverage、stop re-entry gate。
- `contracts.md` 新增 `Scorecard` 和 `research_proposal` contract；LLM 仍不能输出订单、目标权重或执行计划。
- `coding-rules.md` 补充初版不接 agent framework、交易所读数失败 fail closed、spot liability halt、
  以及按 slice 实现的原则。

### MiniTrend Phase 1 本地核心实现

按 `docs/mini-trend-agent/execution.md` Phase 1 落地 research-only 纯函数核心，新增
`src/qount/mini_trend/`，不读取环境、不调用 LLM、不接 ccxt、不改变 VPS 生产状态：

- `config.py`：`MiniTrendConfig` 和 TOP5 默认配置，固定 `spot + long_cash`，默认
  `vol_target=0.015`、`rebalance_band=0.35`、`capital_cap_usdt=400`。
- `models.py`：`SignalResult`、`RiskResult`、`ExecutionPlan`、`Scorecard` 等 JSON-compatible
  dataclass contract。
- `signals.py`：BTC SMA200 OR breadth 总闸、个币 `close>SMA200 && SMA20>SMA60`、
  逆波动率 + 相关性惩罚 + vol target 权重，输出 long-only target。
- `risk.py`：min-notional coverage、日/周亏损降目标、stop latch、unmanaged position、
  unknown price/filter 和 spot liability fail-closed。普通风险关闭允许继续生成减仓/清仓计划；
  operational unknown 才 `halt`。
- `execution.py`：risk-adjusted target 到 spot market order plan，支持 rebalance band、lot
  rounding、min-notional skip、target=0 强制退出、live `armed` gate。
- `scorecard.py`：统一 scorecard 所需核心指标、缺字段不能 `pass`、min-notional coverage /
  stop re-entry / unmanaged position / schema error gate。

新增聚焦单测：

- `tests/test_mini_trend_signals.py`
- `tests/test_mini_trend_risk.py`
- `tests/test_mini_trend_execution.py`
- `tests/test_mini_trend_scorecard.py`

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_mini_trend_signals tests.test_mini_trend_risk tests.test_mini_trend_execution tests.test_mini_trend_scorecard`：`18 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/mini_trend`：OK。

读法：这是 MiniTrend 最小 backtest / paper runner 的本地核心积木，还不是 promotion 证据；
未写 state、未同步 VPS、未新增 cron、未 arm live。

### MiniTrend research backtest 接入口

按 owner「接入」要求把 Phase 1 core 接到最小 research-only backtest 链路，仍不接 paper/live/LLM：

- 新增 `src/qount/mini_trend/backtest.py`：对齐多币日线 bar、每日收盘后计算 signal→risk→execution、
  进行 spot long/cash 内部撮合，累计费用、订单、equity、blocked symbols，并生成统一 scorecard。
- 新增 `scripts/research/mini_trend_backtest.py`：薄 CLI，加载 Binance-vision spot 1d 数据，
  默认 TOP5 / 400 USDT / `vol_target=0.015` / `rebalance_band=0.35`，写 research artifact。
- artifact 文件：`config.json`、`summary.json`、`scorecard.json`、`equity.jsonl`、
  `orders.jsonl`、`blocked_symbols.jsonl`。
- 新增 `tests/test_mini_trend_backtest.py`，覆盖 bar 对齐、backtest scorecard/order 输出、
  artifact 写入。
- 更新 `docs/mini-trend-agent/execution.md`，加入 backtest 测试和 CLI 示例。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_mini_trend_signals tests.test_mini_trend_risk tests.test_mini_trend_execution tests.test_mini_trend_scorecard tests.test_mini_trend_backtest`：`21 OK`。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/mini_trend scripts/research/mini_trend_backtest.py`：OK。
- `PYTHONPATH=src ./.venv/bin/python scripts/research/mini_trend_backtest.py --help`：OK。

读法：这是接入可运行研究链路，不是实盘接入；默认 filters 是 research plumbing，
promotion 前仍必须换成真实 Binance filters / fees 分段跑 2021-2022、2023-2024、2025-2026。
本轮接入时未执行联网历史回测、未同步 VPS、未写 paper/latest、未新增 cron、未 arm live。

### MiniTrend 三段 backtest 首跑

按 Phase 1 验收口径跑完三段 research-only backtest，使用当前 CLI 默认：
TOP5 spot、400 USDT、`vol_target=0.015`、`rebalance_band=0.35`、fee 10bps、slippage 2bps、
research default min-notional 10 USDT。未接 LLM、未写 paper/latest、未同步 VPS、未 arm live。

| artifact | 实际窗口 | return | maxDD | orders | min-notional coverage | verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `state/mini_trend/research_runs/seg-2021-2022` | 2021-07-20..2022-12-31 | +8.6153% | 7.4910% | 82 | 0.75 | block |
| `state/mini_trend/research_runs/seg-2023-2024` | 2023-07-20..2024-12-31 | +37.5317% | 12.0268% | 222 | 0.50 | block |
| `state/mini_trend/research_runs/seg-2025-2026` | 2025-07-20..2026-06-30 | -0.1706% | 8.3995% | 67 | 0.60 | block |

实际窗口从 7 月 20 日附近开始，是因为 SMA200 / trend SMA warmup。三段都能输出完整指标，
schema/unmanaged/stop re-entry 均为 0；但三段全部被 scorecard block，直接原因是
`min_notional_coverage < 0.80`。blocked symbols 主要是 `SOLUSDT` 和 `XRPUSDT`：

- 2021-2022：`SOLUSDT` 2 次、`XRPUSDT` 27 次，平均目标名义分别约 9.35 / 7.55 USDT。
- 2023-2024：`SOLUSDT` 80 次、`XRPUSDT` 41 次，平均目标名义分别约 7.46 / 6.19 USDT。
- 2025-2026：`SOLUSDT` 4 次、`XRPUSDT` 14 次，平均目标名义分别约 9.50 / 8.09 USDT。

结论：MiniTrend TOP5 在 400 USDT 小盘和当前权重口径下不满足 paper gate。下一步应先做
小资金可成交性 slice，例如 TOP3/TOP4 或执行层最小名义聚合/跳过逻辑复核；不能因为收益段看起来
可接受就进入 paper。`glm-5.2` / LLM API 暂不接交易链路，后续只适合对这些 artifact 做只读
DailyBrief/OpsAudit 报告。

### MiniTrend 月度切片与当前实盘对比

按 owner 追问补月度切片，并只读 VPS 当前实盘状态(`state/x4/live/*`、`state/cxd/live/latest.json`)。
未改 VPS、未下单、未改 cron。

MiniTrend 三段共 48 个自然月读数，其中 active 月 26 个、空仓近 0 收益月 22 个；active 月 15 正 /
11 负，active 月均约 +1.687%。最强月是 2024-02 `+14.404%`，最差月是 2023-08 `-5.262%`。
主要月度读数：

- 2021：08 `+11.664%`、09 `-1.808%`、10 `+2.347%`、11 `+0.078%`、12 `-3.285%`；
  2022 基本全程 cash。
- 2023：08 `-5.262%`、10 `+12.293%`、11 `-1.675%`、12 `+7.942%`。
- 2024：02 `+14.404%`、03 `+4.740%`、04 `-3.504%`、06 `-1.658%`、08 `-4.414%`、
  11 `+12.477%`。
- 2025：07 `+1.030%`、08 `+0.558%`、09 `+0.922%`、10 `+0.020%`、11 `-2.653%`；
  2026-01..06 基本 cash。

当前 VPS 实盘只读状态(2026-07-07T15:32Z 附近)：

- C×D 当前是 trend-only，carry paused；X4 live `armed=true`。
- 市场形态是 `swap + short_gate=true + shorting=true`，不是 MiniTrend 的 `spot + long/cash`。
- 当前 gate shut，持有 BTC/BNB short，gross exposure 约 0.255、deployed 约 122 USDT、
  equity 约 478.73、unrealized PnL 约 -2.21。
- VPS `equity_daily.json` 短样本从 2026-06-18 开始：2026-06-18 inception equity 484.23，
  2026-07-07 latest equity 478.73，inception-to-latest 约 `-1.136%`。
- 实盘月度短样本：2026-06-18..06-30 `+3.125%`、DD `-2.103%`；2026-07-01..07-07
  `-4.131%`、DD `-4.131%`。

对比读法：MiniTrend spot long/cash 在 2026 风险关闭时基本现金，不赚下跌段但也避开 short squeeze；
当前实盘 short-gate 在 6 月下跌段贡献了收益，7 月反弹/震荡又快速回撤。当前实盘也有小资金可成交性
问题：日志里 ETH/SOL/XRP/ADA/LINK 多次 `below min_order`，实际只剩 BTC/BNB 等少数腿能稳定持有。
因此月度层面不能直接说实盘优于 MiniTrend；更准确是二者承担了不同风险，且都受 400-500 USDT
本金下的最小名义约束。下一步应优先跑 TOP3/TOP4 可成交性对照，而不是提高频率或让 LLM 介入交易。

### MiniTrend TOP3/TOP4 可成交性对照

按 owner「跑」执行小资金可成交性 slice，复用同一 research-only CLI 和三段窗口；未接 LLM、
未写 paper/latest、未同步 VPS、未改实盘。

配置：

- TOP3：`BTCUSDT,ETHUSDT,BNBUSDT`
- TOP4：`BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT`
- 对照 TOP5：`BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT`
- 资金/费用同前：400 USDT、fee 10bps、slippage 2bps、research min-notional 10 USDT。

| tier | segment | window | return | maxDD | orders | coverage | blocked | verdict |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| TOP3 | 2021-2022 | 2021-07-20..2022-12-31 | +5.5512% | 6.5155% | 51 | 1.00 | 0 | pass |
| TOP3 | 2023-2024 | 2023-07-20..2024-12-31 | +46.8542% | 11.1651% | 101 | 1.00 | 0 | pass |
| TOP3 | 2025-2026 | 2025-07-20..2026-06-30 | +0.4636% | 8.3553% | 55 | 1.00 | 0 | pass |
| TOP4 | 2021-2022 | 2021-07-20..2022-12-31 | +11.4512% | 6.5001% | 50 | 1.00 | 0 | pass |
| TOP4 | 2023-2024 | 2023-07-20..2024-12-31 | +41.1552% | 11.7684% | 163 | 0.67 | 56 | block |
| TOP4 | 2025-2026 | 2025-07-20..2026-06-30 | -0.7166% | 8.6950% | 67 | 0.75 | 1 | block |
| TOP5 | 2021-2022 | 2021-07-20..2022-12-31 | +8.6153% | 7.4910% | 82 | 0.75 | 29 | block |
| TOP5 | 2023-2024 | 2023-07-20..2024-12-31 | +37.5317% | 12.0268% | 222 | 0.50 | 121 | block |
| TOP5 | 2025-2026 | 2025-07-20..2026-06-30 | -0.1706% | 8.3995% | 67 | 0.60 | 18 | block |

blocked 明细：

- TOP3 三段无 blocked symbol，min-notional coverage 全为 1.00，是唯一三段全部 pass 的版本。
- TOP4 2023-2024 被 `SOLUSDT` 卡 56 次，平均目标名义约 7.65 USDT；2025-2026 被 SOL
  卡 1 次，coverage 仍低于 0.80。
- TOP5 继续被 `SOLUSDT` / `XRPUSDT` 拖累，2023-2024 blocked 121 次。

月度稳定性：

- TOP3 active 月：2021-2022 为 5 月(3 正/2 负)，2023-2024 为 17 月(10 正/7 负)，
  2025-2026 为 5 月(4 正/1 负)。最强 active 月 2024-02 `+15.125%`，最弱 2021-12
  `-3.251%`；2025-2026 段基本保本。
- TOP4 active 月：2023-2024 同样有强趋势月，但由于 SOL 目标名义过小，执行可成交性不合格；
  2025-2026 段 active 月均为负。

结论：400 USDT 小盘现阶段应把 MiniTrend 默认候选从 TOP5 收缩到 TOP3，TOP4/TOP5 暂不进 paper。
TOP3 解决了 min-notional 问题，但收益仍高度依赖趋势月，尤其 2025-2026 仅保本，下一步不该直接
paper，而应先做 TOP3 的真实 Binance filters/fees 复核、月度 artifact 汇总和 paper 状态机。

### MiniTrend TOP3 beta 归因复核

Owner 质疑「收益率不行，都是牛市带来的，不是策略」。按同一实际回测窗口补 BTC buy-and-hold 和
TOP3 等权 buy-and-hold 对照，结论支持该质疑：MiniTrend TOP3 解决的是小资金可成交性和熊市少亏，
不是可确认的收益 alpha。

| segment | MiniTrend TOP3 | BTC B&H | TOP3 EW B&H | excess vs TOP3 EW | strategy DD | TOP3 EW DD | monthly corr |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2021-2022 | +5.55% | -44.47% | -28.12% | +33.67% | -6.52% | -73.90% | 0.53 |
| 2023-2024 | +46.85% | +214.01% | +159.91% | -113.05% | -11.17% | -31.79% | 0.86 |
| 2025-2026 | +0.46% | -50.01% | -45.32% | +45.78% | -8.36% | -58.82% | 0.57 |

读法：

- 2023-2024 的正收益主要来自牛市 beta，但策略参与不足，显著跑输 BTC 和 TOP3 等权持有。
- 2021-2022 / 2025-2026 的「超额」主要来自 cash / risk-off 避免熊市下跌，不是择时收益增强。
- 月度上，强牛月份如 2024-02：MiniTrend `+15.12%`，TOP3 等权持有 `+41.01%`；2024-11：
  MiniTrend `+8.75%`，TOP3 等权持有 `+30.00%`。
- 熊市/下跌月保护有效，例如 2022-06 MiniTrend 近 0，TOP3 等权 `-37.67%`；2026-06 MiniTrend
  近 0，TOP3 等权 `-21.93%`。

结论更新：MiniTrend TOP3 不应作为「更优秀收益策略」推进；最多可作为小资金低 beta / 回撤控制
wrapper。若目标是提高月级收益，下一步不能继续在 TOP3/TOP4/TOP5、rebalance band 或 LLM 报告层
微调，必须换信息源、换交易目标或明确接受当前 VPS short-gate 这类更高风险形态。

### 项目规则、文档分类与 legacy 入口清理

本轮按 owner 要求先固定项目规范，再清理文档入口和明显弃用入口。新增
[project-rules.md](project-rules.md)，把以下规则落成项目级 contract：

- 文档权威顺序：`current.md` 当前事实最高；`project-rules.md` 管项目规范；
  `quick-handoff.md` 管命令；线文档只约束本线；`update-log.md` 管证据链。
- 文档分类：当前事实 / 接手运维 / 验证边界 / 记录链 / 线 A legacy / 线 B GRID /
  线 C RV / 线 D X4-C×D / L1-L3-L4-L6 重启线 / CTA-R 蓝图。
- 研究线隔离：每条线必须有状态、主文档、代码边界和 artifact 归属；跨线只复用方法和纯函数，
  不复用 promotion 资格或结论。
- 执行记录规则：每批有意义代码、运行、规则或生产变化完成后，必须更新本线 changelog 或
  `update-log.md`；影响当前事实或全局规则时同步更新 `current.md`。
- 代码架构规则：production 不 import research 脚本；研究脚本保持薄入口；共享能力沉淀为可单测函数；
  optional research 依赖不进入基础 live 依赖。
- 量化研究参考固定：DSR、PBO/CSCV、purged-CV/embargo、effective-breadth、交易所官方数据字段、
  funding 和 rate-limit 文档作为后续验证规则的默认依据。

同步修订：

- [README.md](../README.md)：当前文档入口改为按分类读取，并加入每批更改后更新记录文档的要求。
- [quick-handoff.md](quick-handoff.md)：新增 `project-rules.md` 入口、记录纪律、线级代码指针和
  “不新增未归类计划文档 / 不未经审计删除 legacy 代码”的禁止项。
- [current.md](current.md)：记录 2026-07-07 项目治理规则已固定，并把 `project-rules.md` 和
  各线模块纳入代码结构。
- `src/qount/mac_monitor.py`：补上与 `scripts/mac-monitor.sh` 一致的 legacy guard，避免用户绕过
  shell 脚本直接运行 `qount-monitor` 时误把旧 WSL 面板当当前实盘入口。

验证：

- `PYTHONPATH=src ./.venv/bin/python -m qount.mac_monitor --help`：OK，help 仍可读。
- `PYTHONPATH=src ./.venv/bin/python -m compileall -q src/qount/mac_monitor.py`：OK。
- `PYTHONPATH=src ./.venv/bin/python -m qount.mac_monitor --once`：按预期 exit 1，并提示
  `QOUNT_ALLOW_LEGACY_WSL=1` 后才允许旧 WSL 面板。
- `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'`：
  `910 OK`。输出包含既有 `utcfromtimestamp` deprecation warning 和 dry/live 模拟打印，
  无失败。
- 未同步或部署 VPS，未跑远端 `./scripts/run-vps-tests.sh`。

## 2026-06-09

### L6 厚样本重测 + close_auction T+0 执行实测 → 撞回 maker 墙,L6 同型固化止盈

承上(53 天数据到位)。**① 52 天 D1/D2/D4 重跑**:加厚样本把 close_auction 信号打回——ETF D1 rank-IC
从 17 天的 0.037 缩到 **0.021(t−3.38、符号 0.69)**,距广度要求(eff-breadth 1.85 → 0.046)从 0.76× 退到
**0.44×**(更多数据让信号回归零、离广度墙更远);D2 增量门仍过(控制价量后 partial IC 保留 103%,确属
价量正交的真新信息);D4 组合 OOS(purged-CV)崩到 +0.006 甚至翻负(组合提升是 in-sample 权重过拟合)。
绑定约束仍是广度(~1.85)。

**② 换问题:执行线 B**(`evaluate_l6_t0_execution` + 命令 `l6-t0-exec-scan`)。信号在 T 收盘竞价测得、
最早 T+1 开盘可动,唯一可兑现是 **T+1 open→close 日内 T+0**。把次日反转拆成隔夜/日内/收收三段,发现:
**收盘竞价买压 → 隔夜跳空续涨(IC +0.045/t8.5)→ 日内反转(IC −0.029/t4.5)**;D1 的 close-to-close
(−0.019)是两段反向力量打架后的净残值,把信号糊掉了。`capturable_frac≈2`——只吃日内 T+0 比持有过夜好
一倍(隔夜那段是反向的)。**T+0 是这个信号严格更优的载体,不是将就。**

**③ 实测成本定生死。** 给 `daily_flow_features` 加 `day_open`(=mids[0])+ `quoted_spread_bps`(两边
有价快照的 `(ask1−bid1)/mid` 均值),从 47 个 ETF 归档重 ETL 46 天 ETF panel(独立根
`state/research_runs_etfopen/`,新基建 `scripts/research/l6_etf_reetl.sh`)。evaluator 改成**成本感知**
(用每个被交易 ETF 自身 T+1 价差算 taker 成本,给 taker/auction 双区间)。实测:日内 gross +7.6~9.9bp
(t>2.4)真实,但 **交易尾价差 ~13–14bp → taker 往返 ~31bp → net −23bp(t−7),taker 彻底死**;唯一
"幸存"的竞价撮合(仅佣金 2.5bp/腿)net +2.6/+4.9bp 但 **t<1.3 不显著**,且在薄 ETF 上量一大冲击=价差
另一种形式回来。**价差-信号陷阱**:信号活在不流动 ETF(强尾价差 14.4bp/gross+9.9bp),一上流动 top100
(价差 5.7bp)信号塌成 +2.3bp/t0.26 —— **edge 本质是薄 ETF 的流动性提供溢价,taker 拿不走;要拿只能
做 maker = L4/§3-Phase4 的 maker 墙**。

**④ 净结论 + 固化(所有者授权 A)**:close_auction 是项目迄今最干净的信号(真实+显著+价量正交+隔夜/日内
结构清楚),但不可 taker 兑现、edge=流动性溢价、收敛到已知撞死的 maker 墙。**B 诚实止盈、L6 与
§7/L1/L3b/L4 同型固化**:stop investing,不放宽任何纪律(live 关闭、不 forward paper、不放宽 broad gate、
`validation_v1` once-only 保留)。沉淀=D0–D4 + T0 隔夜/日内分解 + 实测 taker/auction 成本的反过拟合
harness。本地/WSL 全测 34 OK。artifact `state/research_runs/20260609T065032Z/065033Z-l6-t0-exec-scan`。

### L6 L2 数据扩到 53 天(2/3/4 月)+ 管线加固 + 两个坏文件收尾

隔夜跑批管线(`scripts/research/l6_pipeline.sh`,external 消费模式)把 L2 全个股日线 panel 从
**17 天扩到 53 天**(2/3/4 月连续交易日),落 WSL `state/research_runs/l6_daily_*`,每天 scored
99.7%–100%。**D1 现有 52 个 T→T+1 截面,远超 20–40 门槛**;续3–续6 的 D1/D2/D4 结论都建在 16 截面上,
现在 close_auction 单信号(D1/D2 真实但量级 0.036<广度要求 0.049)+ D4 purged-CV 可在厚样本上正经
重跑——下一步(尚未重跑)。

两个坏文件单独处理:

- **20260311** — 原 .7z 损坏(`_lzma.LZMAError: Corrupt input data`),解压秒失败;重下后 DONE
  (scored 7487,etf_archive 415M)。
- **20260210** — 合法低标的日(稳定 scored 5178,邻日 ~7500;ETF 归档仅 116B = 该日几无 T+0 ETF
  匹配代码段),非半包下载;加白名单 `LOW_OK_DATES` 放行、DONE。

**管线 bug 修复(只改运维脚本、不碰 `l6_microstructure.py` 核心)**:`process_one` 四个失败分支
(extract / etl / scored<6000 / xz verify)原本「原地留 .7z」→ 坏文件让 `processor` 的 `while true`
退不出、反复重试空转(本次坏文件让管线从 ~02:05 空转到 ~10:15)。改成移入 `$SRCDIR/_bad/`,文件离开
`*.7z` glob → 不再重试、能正常退出。新增 `LOW_OK_DATES` 白名单跳过 <6000 守卫。本地 + WSL `bash -n`
双验。

**运维坑(已记 quick-handoff)**:`ssh → wsl.exe bash -lc 'tmux new -d ...'` 起的后台进程**不持久**
——ssh 命令一返回,WSL 把 tmux+管线连同 `/tmp` 一起回收(昨晚跑通是从 Windows 侧交互式 WSL 终端起、
会话常开)。可靠做法=**前台阻塞跑**:ssh 连接全程挂着 = WSL 不回收,一次跑完两天。

硬约束全不变,research-only、未碰 `validation_v1`、未下单。

## 2026-06-08

### L6-daily D0 完成:L2 衍生日线知情流特征 ETL + 单日全截面验证

重启线 L6-daily(用 A股 逐笔 Level-2 重建日线知情流,攻 `IR=IC×√BR` 的 IC 项,见
[l6-microstructure-plan.md](l6-microstructure-plan.md) §4b)。D0 目标:写日线特征 + ETL +
单测,在单日全截面验证特征分布合理、无前视;**单日不能测预测力**(需 T 特征 → T+1 收益)。

代码:`src/qount/l6_microstructure.py` 的 `daily_flow_features` / `compute_daily_feature_panel`
+ research-only 命令 `l6-daily-features`(`--all-symbols` 枚举全市场)。五个 L2 衍生日线特征,
每(股,日)一向量、全部当日 intraday 聚合(收盘时点可得、无前视)、严格区别于券商粗主力净流入:
`aggressive_ofi`(主动买卖量不平衡,用 `BS标志` 非成交额分档)、`large_aggr_ofi`(仅 p90+ 大单)、
`late_minus_early_flow`(尾盘 14:30–15:00 − 早盘 09:30–10:00)、`close_auction_imbalance`
(14:57–15:00 收盘竞价净方向)、`cancel_imbalance`(买撤−卖撤;深市撤单在成交文件 `成交代码=C`、
沪市在委托文件 `委托类型=D`,代码按内容而非后缀判别,避开数据集把 SH 标的误标 `.SZ` 的坑)。

验证(本地 unittest 363 OK → sync-to-wsl → WSL 363 OK → 跑 ETL → artifact 落 state):

```text
20260407: scored 7762/7778 (99.8%)  artifact=state/research_runs/20260608T040443Z-l6-daily-features-l6_daily_20260407
20260408: scored 7714/7715 (100.0%) artifact=state/research_runs/20260608T042318Z-l6-daily-features-l6_daily_20260408
```

特征分布合理:五特征均值都贴近 0(A股轻微弱买压;0408 整体买压明显高于 0407,
`aggressive_ofi` mean +0.11 vs +0.03、收盘竞价 +0.19 vs +0.06,真实截面 regime 差异,
非 bug)、std 0.22–0.46、分位对称、饱和(|x|≥0.999)率仅 0.3%–7.4% 且集中在成交<500 笔的
低流动性微盘(成交太少→不平衡天然极端,预期内)。未打分标的为停牌/无成交(0407 16 只、0408 1 只)。

**数据工程红利兑现**:原始 38G+47G=85G 逐笔 → 全个股日线面板(每份几 MB artifact);
ETL 按 (股×日) 顺序处理、绝不全量进内存,单日全市场 ~5–6 分钟。

**ETF 原始归档 + 原始删除(所有者授权,网盘有全量备份)**:两天各 1356 只 T+0 ETF
(代码段 159/51x/56x/588)的原始三件套移到 `~/Desktop/l6_etf_raw/{date}/`(0407 4.9G、0408 6.1G,
留作日内线 Phase 1/2 跨日复核素材);全个股日线特征提取并验证后,删除两天原始日目录,释放 ~63G。
L6-daily 主线所需(全个股日线特征)已落 artifact,日内线所需(ETF 原始盘口/逐笔)已归档,两条线均不丢。

下一步 **D1**(生死第一刀,需多日数据):跨日 × 全个股截面 rank-IC + 跨日符号稳 + DSR/PBO +
`_panel_effective_breadth`,门控截面 IC > 0.06;当前只有 2 天、无法测预测力,需继续攒日。
硬约束全不变,未碰 `validation_v1`、未下任何单。

### L6 数据扩到 4 天 + 所有者选 ETF 版 L6-daily + L2 原始压缩归档

**L2 知情流扩到 4 个交易日**:0403 / 0407 / 0408 / 0409(0404–06 清明休市)。全个股日线 panel 四份
(scored 0403 7644/7661、0407 7762/7778、0408 7714/7715、0409 7693/7711,均 99.8%–100%),
留 `state/research_runs/`,L6-daily 个股主线(eff-breadth ~7)数据继续累积。

**所有者方向(2026-06-08):做 ETF 版 L6-daily**(把 universe 从个股换 T+0 ETF:ETF L2 知情流 →
ETF 次日收益)。**标签 blocker 解除**:`daily_flow_features` 输出自带 `day_close`(收盘 mid),
forward-return 直接跨天算,**不需要外部 ETF 日线**——所有者另给的「ETF日线行情」数据集(2012–
2026-03-13、1446 场内 ETF)止于 0313、与 L2(0407+)不重叠,弃用(仅余 D2 价量动量基线的边缘用途)。

**ETF 版 D0**:ETF 管线已验证(1356/1356/1356/1357 全打分)。但暴露两个隐忧:(a) **流动性长尾**——
1356 只 ETF 里近半成交<500 笔(冷门迷你/货币 ETF),尾盘竞价 / 时段流饱和率 18–20%(个股仅 7.4%),
需按成交额筛活跃子集;(b) **广度回落**——ETF 截面有效广度历史 ~1.7,正是 L6 主线当初选「全个股」
(~7)要逃的天花板(L1/L3b/§7 反复撞)。ETF 版的真实权衡:**广度↓(致命) vs T+0 日内可兑现↑
(个股 T+1 大半 alpha 不可兑现,这是 ETF 版唯一的救赎)**;生死要靠 `_panel_effective_breadth` 在
活跃 ETF 子集上实测。

**数据工程 / 存储归档**:每天 38–47G 全市场原始逐笔 → 一次 ETL 塌成几 MB panel。ETF 原始
(4 天 21.5G,日内 Phase 1/2 素材)经 `tar + zstd-19` 压到 **1.87G(8.7%)**,scp 归档到 Windows
`D:\qount_l2_archive\`(字节数逐一校验 + zstd checksum 全 OK);全个股原始删除、本地 ETF 删除,
现为 **Windows D 盘 + 网盘双备份**,Mac 只留 panel。跨主机存储原则确认:**压缩态冷存 Windows NTFS,
WSL 处理时解压到 ext4 `/home`——绝不让 WSL 直接遍历 `/mnt/c` 上的散装小文件(9P 慢 10–100×)**。

下一步 **D1-mini**:4 天 = 3 个 T→T+1 截面(0403→07、07→08、08→09),统计极薄,只能验管线 +
读首个 IC 符号/广度方向,**非 D1 结论**(正式 D1 需 20–40 天)。需写跨日 ETF 截面 rank-IC 评估器
(先写单测、本地→WSL)。硬约束全不变,research-only、未碰 `validation_v1`、未下任何单。

### L2 数据扩到 4 月全月 17 个连续交易日 + 并行 ETL 基建 + 全 Windows 存储

**数据规模**:从 4 天扩到 **17 个连续交易日**(0401/02/03、07/08/09、10、13–17、20–24,即 2026-04
全月除清明与周末),覆盖不同 regime。每天全个股 panel scored 7644–7762(99.7%–100%)。

**并行 ETL 基建(新增 research 工具,不改核心)**:
- `scripts/research/l6_parallel_etl.py`:`multiprocessing.Pool` 跨核调用 `l6_microstructure` 的
  per-symbol 函数,输出与 `l6-daily-features` 命令同形;单天 7700 标的从单线程 ~34min 降到
  10 核 ~8min / 32 核 ~5–7min。
- `scripts/research/l6_wsl_batch.sh`:WSL 单天串行流水线(py7zr 解压 .7z → ext4 → 并行 ETL →
  ETF 子集 xz 压缩到 D 盘 → 校验后删解压原始 + 删 .7z)。**单天串行**把 ext4/VHDX 峰值限制在
  一天 ~40G(WSL VHDX 在 D 盘、删文件不自动收缩,故不并行多天);**幂等**(删 .7z 后重跑自动跳过),
  ssh 断连可重入续跑;删 .7z 双保险(scored≥6000 且压缩包完整性校验通过)。

**跨主机流水线**:Mac 2 天(0401/02,`7zz` 解压 + scp 归档,~8min/天)+ WSL 11 天(0410–0424,
py7zr + xz,~12min/天)。原始 .7z 每天 ~4–6G(解压后 ~40G);ETF 子集压缩归档每天 ~340–540M。

**全 Windows 存储(所有者原则:Mac 不做数据存储)**:
- ETF L2 压缩归档 **17 个 / 7.8G** 在 Windows `D:\qount_l2_archive\`(Mac 产 6 个 `.tar.zst`、
  WSL 产 11 个 `.tar.xz`,`tar -xaf` 通吃);日内 Phase 1/2 素材。
- 全个股日线 panel **17 天**在 WSL `state/research_runs/l6_daily_*`(Mac 处理的 6 天已 tar→ssh
  迁入 WSL,Mac 本地 panel 删除)。
- 源 .7z 全删;Mac 回归纯编辑/git 面,零 L2 数据。WSL ext4 在 D 盘(752G/372G free,非 C 盘)。
- 工具:Mac `brew sevenzip`(7zz);WSL `pip py7zr`(免 sudo)+ 系统 `xz`(无 zstd);
  Windows D 盘经 `scp home:D:/...`(OpenSSH)。

**下一步 D1(可正式做)**:17 天 = **16 个 T→T+1 截面**,接近正式门槛(20–40 天)。写跨日 ETF
截面 rank-IC + 符号稳定性 + 活跃 ETF 子集 `_panel_effective_breadth`(先单测、本地→WSL)。
17 天 panel 已全在 WSL,可直接在生产真相上跑。硬约束全不变,research-only、未碰 `validation_v1`。

### D1 跨日截面 rank-IC kill-test:below_gate,但 close_auction 是首个真实显著信号

工具:`evaluate_l6_daily_d1` + 命令 `l6-daily-d1-scan`(`src/qount/l6_microstructure.py`)。T 日知情流
→ (T+h) 日 close-to-close 收益(用 panel 自带 `day_close`,无前视),逐日截面 rank-IC + 符号稳 +
top/bottom decile LS Sharpe + `_panel_effective_breadth`(复用 l3)+ DSR/PBO。universe 支持
all/etf/活跃 top-N(成交额代理)。local 367 OK + WSL 367 OK(+5 单测)。

WSL 实跑 17 天 / 16 截面(artifact 落 WSL `state/research_runs/...l6-daily-d1-scan`):

```text
ETF 全体(N=1363):  eff_breadth=1.69 (r̄=0.592)  best=close_auction_imbalance IC=-0.0365 t=-4.95 sign=0.87
ETF 活跃 top100(162): eff_breadth=1.80           best=late_minus_early IC=-0.055 t=-1.18(不显著)
ETF 活跃 top300(436): eff_breadth=1.71           best=late_minus_early IC=-0.043 t=-1.26(不显著)
全个股(N=7734):     eff_breadth=2.50 (r̄=0.40)  best=aggressive_ofi IC=-0.017 t=-1.10(不显著)
四个 universe 全 decision=l6_daily_d1_below_gate;DSR 0.36–0.62、PBO 0.27–0.43
```

**两个发现**:(a) **广度天花板经验证实**——ETF 截面 eff-breadth 仅 **1.69**(§7/L1/L3b 反复撞的 ~1.7),
全个股 **2.50**(印证主线选全个股,但 < L1 的 2.97)。(b) **`close_auction_imbalance` 是项目首个真实、
统计显著(t=-4.95)、符号稳(0.87)的日线 L2 信号**——收盘集合竞价买压 → 次日反转下跌。按 Grinold
(年 Sharpe=1、日频 250 期)ETF breadth 1.69 → 要求 IC ≈0.049;实测 0.037 = **0.76×,接近但不够**;
全个股要求 ≈0.040、实测 0.017 远不够(广度高但信号更弱)。

**判词**:与 L3b 同型(真信号但广度封死),但**没那么悲观**——close_auction 的 t 比 L3b 硬,ETF 0.037
距要求 0.049 仅 0.76×,且 **ETF T+0 可日内兑现**(个股 T+1 大半 alpha 不可兑现的致命伤在 ETF 不存在)。
16 天统计仍薄。**下一步未定**(攒更多天 / D2 增量门 close_auction vs 价量动量 / D4 多特征 GBDT 组合抬
有效 IC / 深挖 close_auction 反转+T+0 执行 / 接受广度天花板按 §7 停),待所有者决策。硬约束全不变。

### D2 增量门:close_auction 在 ETF 上通过 —— 价量没有的真新信息(项目首次)

工具:`evaluate_l6_daily_d2` + 命令 `l6-daily-d2-scan`。偏 rank-IC——close_auction_imbalance vs 次日
收益,**控制 trailing close-to-close 收益(价量动量/反转基线)**;保留比 = partial/raw,≥0.5 且同号
判 incremental。local 370 OK + WSL 370 OK(+3 单测)。WSL 实跑(14 截面):

```text
ETF 全体:     raw_ic=-0.0362(t-4.59)  partial_ic=-0.0343(t-3.51)  价量基线_ic=+0.0188(t0.23)
              共线度=-0.0396  保留比=94.6%  decision=l6_d2_incremental
ETF 活跃top300: raw=-0.0281  partial=-0.0207  保留比=73%  incremental(t 不显著,样本少)
全个股:        raw=+0.0022(≈0)  partial=+0.0007  保留比=30%  subsumed(但 raw≈0,无意义)
```

**结论(项目历史性一步)**:(a) close_auction 控制价量后**保留 94.6% IC、仍显著(t=-3.51)** → 不是
换皮重测拥挤反转因子;(b) **价量在 ETF 日线本身几乎无预测力**(基线 IC +0.019、t=0.23)→ close_auction
提供的是价量**根本没有**的信息;(c) 共线度仅 -0.04 → 与昨日收益近正交。**换信息源的尝试里,L3b 找到
信号但广度死、funding 直接弱——close_auction 是首个同时过 D1(真实显著 t=-4.95)+ D2(价量增量、保留
94.6%)的信号,L6 的核心假设「L2 真知情流 ≠ 价量」第一次被经验证实。** 保留的张力:|IC| 0.036 仍
< breadth(1.69)调整要求 0.049、14 截面偏薄。下一步待所有者决策(攒天确认量级/稳定性 / D4 多特征
GBDT 组合抬有效 IC / 深挖 close_auction 反转 + ETF T+0 执行经济学)。硬约束全不变,未碰 `validation_v1`。

### D4 多特征线性组合:临界,接近但未干净突破广度要求

工具:`evaluate_l6_daily_d4` + 命令 `l6-daily-d4-scan`。5 特征截面 z-score、按全样本符号对齐等权
(`sign_equal`)或 IC 加权(`ic_weighted`)合成 composite,对比 breadth-adjusted 要求
`required_ic = 1/sqrt(eff_breadth*250)`(Grinold IR=1、日频)。GBDT 推迟(16 截面必过拟合)。
local 372 OK + WSL 372 OK(+2 单测)。WSL 实跑(16 截面、required≈0.049):

```text
ETF 全体 sign_equal:    composite IC=+0.0326 t=2.08 sign=0.62  < 0.0487  below
ETF 全体 ic_weighted:   composite IC=+0.0417 t=4.15 sign=0.81  < 0.0487  below(0.86×,但 in-sample 权重)
ETF 活跃top300 sign_equal: composite IC=+0.0572 t=2.11        > 0.0484  breaks(但 t 仅 2.11、广度小)
ETF 活跃top100:         composite IC=+0.0436 t=1.52           < 0.0472  below
```

**判词**:组合确实把信号从单 close_auction 0.036 抬到 0.042(全体 ic_weighted,t=4.15/sign0.81)~
0.057(top300),方向对;但**没有一个配置干净突破**——全体 ic_weighted 0.042<0.049 且权重 in-sample
偏乐观、top300 破线但 t 仅 2.11、无"破线+t硬+全universe+非in-sample"四者兼得。**信号真实、组合有帮助,
但量级正卡在广度(1.69)要求 0.049 的临界线**,又一次印证广度是绑定约束。16 截面太薄(t 不稳)、
ic_weighted 需 purged-CV 验真实 OOS。下一步待所有者决策(攒天到 ~40 + purged-CV 验 ic_weighted 是否
稳定破线 / 接受临界按 §7 固化 / 深挖 close_auction+T+0 执行变现 0.04)。硬约束全不变,未碰 `validation_v1`。

**D4 purged-CV(leave-one-section-out + embargo,所有者选的最便宜判别)推翻了 in-sample**:给 D4 加
`--purged-cv`(权重只用其余截面训练、embargo 邻近,OOS 评估留出截面)。WSL 实跑:**所有配置 OOS
composite IC 崩到 ~0 甚至符号翻转**——ETF 全体 ic_weighted in-sample 0.042(t4.15)→ **OOS -0.004
(t-0.25),保留比 -0.09**;sign_equal 0.033 → OOS -0.024(翻负);top300 两种 → OOS -0.014/-0.025
(均翻负)。**in-sample 0.042-0.057 几乎全是 16 截面上权重选择的过拟合假象,真实 OOS 不成立。** 这正是
反过拟合 harness 的价值(没被 in-sample t=4.15 骗)。**修正净结论**:(a) 单 close_auction 真实(D1/D2
无权重选择、过拟合不了),但量级 0.036<0.049;(b) D4 多特征组合救不了——引入权重选择即在现有 16 截面
过拟合、OOS 崩;(c) 绑定约束仍是广度。组合突破这条路在现有数据上关闭。下一步待所有者决策(攒天到~40
让单信号更硬+组合 OOS 样本足 / 深挖 close_auction 单信号+ETF T+0 执行变现 0.036 / 接受按 §7 同型固化停)。
硬约束全不变,未碰 `validation_v1`。

## 2026-06-06

### 全局决策(所有者确认):接受 §7 全局诚实止盈,三条重启线走完

无代码改动(纯对账)。§7 原始止盈后,按 §11.8「唯一合法重启=结构性新输入」依次试了三条结构性重启线,
各攻 `IR=IC×√BR` 的不同项或游戏本身,**全部撞到同一类结构性/成本墙**:

```text
L3 换 IC 来源(非价量慢数据)   = 证伪：广度天花板在新数据源原样复现(L3b 真信号 IC 0.075 但 eff-breadth 1.68)
L1 攻 BR(跨资产趋势)          = 固化暂停：真逃逸广度天花板(eff-breadth 2.97)、找到项目首个真 edge，
                                  但零售 ETF 净 Sharpe ~0.4 < 0.5 券商门控；真量级需期货券商(未授权)
L4 换游戏(市场中性跨所套利)   = 证伪：跨所 spread 真实(毛 +7.4%/yr)但贴 maker 成本地板(回本 2.7bps)
                                  + 每 ~12h 翻转，换手吃光，required_maker_fill ~0.93(CARRY maker 墙跨所重现)
```

所有者从「L5 / L2 / L4-S2 / 接受全局止盈」中选**接受全局止盈**。

**固化的研究价值**(项目真成果):整套反过拟合 harness(triple-barrier / purged-CV / DSR / PBO /
effective-breadth / breadth-adjusted 要求 IC)、kill-test 方法论(最便宜的证伪优先、纯数据零新场先证伪)、
三条重启线的诚实证据链。**唯一合法的下一次重启触发仍是所有者授权的结构性新基建**:期货券商(L1-S5)/
期权场(L5)/ 多所账户(L4-S2)——**当前一个都不追**。这是停止投入,不放宽任何纪律:live 仍关闭、
不 forward paper、不放宽 broad gate、`validation_v1` once-only 资格继续保留。对账见 `profit-engineering-plan.md §11.8`。

### L4 跨所套利重启线:S1 跨所 funding spread kill-test 证伪

所有者从 L4/L5/L2 选 **L4 跨所套利(换「游戏」=市场中性,不预测方向)**。命门:跨所 funding spread 的
「幅度 × 持续性」能否跨过双所往返成本——纯数据、零新场、零下单。

变更:

```text
docs/l4-cross-exchange-plan.md（新建 L4 计划文档）
src/qount/l4_cross_exchange.py（数据层 + evaluate_l4_cross_exchange_funding + L4CrossExchangeFundingService）
src/qount/main.py（新增命令 l4-cross-exchange-funding-scan）
tests/test_strategy_optimization.py（新增 L4CrossExchangeTests，5 单测）
```

设计:ccxt 拉多所 perp funding 历史(复用 `normalize_funding_history`)、`state/` 缓存、**按各所原生
结算间隔(相邻时间戳中位推得)归一到 8h 当量**(否则 1h 的 Hyperliquid 与 8h 的 Binance 费率量级错配会
冒充 spread)、as-of 对齐到 8h bucket、每 bucket 取 `spread=max−min` 做多最低所/做空最高所(净 delta≈0)、
pair 翻转付 4 腿往返、复用 §7 的 `_sharpe`/DSR/PBO。修了一个口径 bug:spread 恒 ≥0 → `required_maker_fill`
数学上恒 ≤1,不能当生死门,改成「实测成本后净 capture>0 + DSR/PBO」为门,required_maker_fill/break-even 降为诊断。

基建发现(类比 L1 的 Tiingo):**三所 Binance/Bybit/OKX 均需配置代理(直连全 NetworkError),跑命令前
必须 `set -a && source .env && set +a`,否则 `Settings.from_env` 拿不到代理 → 全所 unreachable**(第一遍
默认含 Hyperliquid 的实跑就栽在这 + Hyperliquid USDC 符号);Hyperliquid 实测可达但 USDC 结算(不同符号/基差)
+ 1h funding,推迟 S2。验证:`local/WSL unittest=269 OK（264 → +5）`。

WSL 实跑(120d discovery、binance/bybit/okx、6 USDT 永续、261 共同 8h bucket、taker 0.0004):

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260606T113148Z-l4-cross-exchange-funding-scan/
毛年化 spread=+0.074（6 币毛值全正，真实跨所定价不一致）
break_even_cost_per_side=0.000027（2.7bps/腿）
pair_changes≈165/261（mean_hold≈1.5 bucket≈12h，最优 pair 每 ~12h 翻转）
净年化（taker 0.0004）=−1.6  组合 Sharpe 深负  required_maker_fill≈0.93
DSR=0.0（最佳 per-period 净 Sharpe −1.1 < 噪声期望最大 0.107）  PBO=0.083（低但因净负无意义）
decision=cross_exchange_spread_below_gate
```

读法:**跨所 funding spread 真实为正(毛 +7.4%/yr),但已被套利者压到 ~maker 成本地板(回本 2.7bps),
且残差每 ~12h 均值翻转 → 4 腿换手吃光毛值。** taker 成本下深负、要 93% 腿 maker 成交才回本——单所
CARRY 的 maker 墙跨所原样重现。绑定限制是「spread 已贴成本地板 + 换手过快」,非方法。只有 co-located
maker/返佣 HFT(另一种操作者、需多所账户基建)够得着;对本「慢 + 延迟无关」操作者证伪,正是计划 §5/§1
预判的成本墙。S1 未过 → 不进 S2。**L4 落在终局决策点**(退出转 L5/L2 / L4-S2 maker 执行研究需多所账户)。
硬约束全不变,未碰 `validation_v1`、未下任何单、未开多所账户。

### L1 终局决策(所有者确认):固化为部分成功,暂停

无代码改动(纯文档对账)。L1 跑到终局决策点:S1 广度过(eff-breadth 2.97)、S2 趋势真实但净年化
Sharpe ~0.36–0.42 < 0.5 门控且 DSR 0.856/PBO 0.627 不过、40-ETF 扩容确认零售 universe 在
eff-breadth ~3 / Sharpe ~0.4 处饱和。三条文档内合法路径(S5 券商 / 固化 / 转 L5),**所有者选固化**。

对账理由:
- **不开券商**:L1 计划 §3 规定「开券商(S5)只在 S1–S4 全过之后」,S2 未过 → 不在 sub-gate 证据上
  开真期货券商、不掏真实资金/建新工程轮。
- **不内部堆参**:在同批已看 ETF 上继续加旋钮/扩标的是 §5 禁止的「L1 内部堆参当重启」;40-ETF 已是
  最后一个零售杠杆且不升反降,L1 内部可触及路径穷尽。

固化内容:L1 是本项目**第一个真实、稳健、正、经济一致的 edge**(21-ETF 跨资产 TSMOM,gross Sharpe
0.55、净 0.36–0.42、4/5 时间折正、2022 利率趋势 crisis-alpha、与 crypto 无关),并**经验证实了 §2
广度逃逸论点**——结构性低相关跨资产 universe 把 majors 广度天花板从 1.6 抬到 2.97,绑定约束随之从
「广度」迁移到「零售 ETF 的 edge 量级」。**暂停而非删除**:S2 门控原样保留,未来开期货券商(独立
工程轮)或拿到结构性更优 universe 时,从 S3 续跑。

这是停止在 L1 上投入,不放宽任何纪律:live 仍关闭、不 forward paper、不放宽 broad gate、
`validation_v1` once-only 资格继续保留。下一次重启需新的结构性输入(L5 换预测目标=波动率 / L4
跨所套利),非 L1 内部微调。对账见 current.md 与 l1-cross-asset-plan.md §3/§5。

### L1 S2 扩 40-ETF:零售 universe 天花板确认(扩不升反降)

无新代码(仅 `_tiingo_get_json` 加 3 次重试抗 SSL 瞬断,40 标的顺序拉取需要)。`local/WSL
unittest=264 OK`。按所有者选择,开券商前用最后一个零成本杠杆——把 universe 从 21 扩到 40 ETF
(加 11→ 国家/板块股 EWZ/EWG/INDA/EWT/EWA/XLE/XLU、更多债 BWX/EMLC/MBB/PFF/BKLN/BNDX、
更多商品 CORN/WEAT/CPER/PPLT/PALL/GDX),重跑 S2 单一 + ensemble(2014-2026):

```text
breadth_40etf=/home/alyaloale/Code/qount/state/research_runs/...l1-cross-asset-breadth-scan(40)
21-ETF: eff_breadth=2.973 r̄=0.303 | best 单一净 Sharpe=0.421 | ensemble=0.363
40-ETF: eff_breadth=2.805 r̄=0.340 | best 单一净 Sharpe=0.318 DSR=0.759 PBO=0.571 | ensemble=0.227
```

读法：**扩 ETF 不升反降——零售 universe 天花板确认。** 加 19 个 ETF 让有效广度略降
(2.973→2.805)、Sharpe 下降,因为零售 ETF 聚成同样 ~3 个宏观因子(股 beta / 利率 / 商品-美元),
加相关标的抬不动独立因子数(`40/(1+39×0.34)=2.8`)。**零售 ETF universe 在 effective-breadth
~3、净 Sharpe ~0.4 处饱和。** 最后一个零售杠杆已用尽:要突破只能换真正不同的工具=真期货
universe(单名商品 / 利率曲线各点),那需要券商(S5)。**L1 终局收窄为:S5 券商 / 固化部分成功
/ 转 L5。** 硬约束全不变,未碰 `validation_v1`、未开任何券商。

### L1 S2 ensemble:确认 edge 真实稳健但量级仍低于门控(零售 ETF 天花板)

变更：

```text
src/qount/l1_cross_asset.py（新增 evaluate_l1_tsmom_ensemble + _fold_sharpes；service 加 ensemble 模式）
src/qount/main.py（l1-cross-asset-tsmom-scan 加 --ensemble / --n-folds）
tests/test_strategy_optimization.py（+1 单测：ensemble 混合 lookback + 报 folds）
```

所有者从 S2 后续选 **lookback 等权 ensemble**(无参,直接回应 PBO=0.63「别选单一 lookback」)。
信号层混合:`ensemble_signal_i = mean_L sign(trailing_L)` ∈ [-1,1] → 反波动率定权 → 归一。
单一无参 config,无 lookback 选择 → 不算 DSR/PBO,改用连续 purged 时间折判稳健性。

验证：`local/WSL unittest=264 OK（263 → +1）`。

WSL 实跑(21-ETF、753 周、cost 0.0006/side、grid {13,26,39,52}、vol_lb 26、5 折)：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260606T064415Z-l1-cross-asset-tsmom-scan/
NET 年化 Sharpe=0.363（gross 0.553）  avg_weekly_turnover=0.253
folds 正 4/5（需 3）: 0.867 / 0.106 / 0.345 / -0.042 / 0.998（fold3≈2023 whipsaw 年负）
yearly: 多数正,2023=-0.081 最差;2019/2022/2024 最好
decision=tsmom_ensemble_below_gate（ir_pass=False 0.363<0.5, net_pass=True, fold_pass=True）
```

读法：ensemble 净 Sharpe(0.363)**反而略低于最佳单一 lookback(lb39w 0.421)**——等权纳入较弱
的快周期(lb13w 单独仅 0.10)把混合拉低;gross 略升(0.553)。所以 PBO 高不是过拟合噪声,而是
快/慢周期质量不齐;ensemble 解决了"选哪个 lookback"(4/5 折稳健为正),但**没提升量级**。

**L1 S2 完整定论:跨资产趋势是整个项目第一个真实、稳健、正、经济一致的 edge**(gross Sharpe
0.55、4/5 时间折为正、2022 利率趋势 crisis-alpha、与 crypto 无关的 diversifier),不同于此前
所有证伪。**但零售 ETF universe 上净 Sharpe 只有 ~0.36–0.42,低于开券商所需 0.5 门控**;绑定
限制是「原始 edge 量级 × 零售 universe」,非方法——经典 CTA 的 0.7–1.0 Sharpe 需 50–100 个期货
(券商,S5,刻意推迟)。S2(含 ensemble)按预设门控未过 → 不进 S3。L1 落在「广度命门已过 +
趋势真实正但零售档量级不足」的终局,下一步是所有者决策(S5 券商 / 固化为部分成功 / 转 L5)。
硬约束全不变,未碰 `validation_v1`、未开任何券商。

### L1 S2 趋势 kill-test:跨资产 TSMOM 真实正 edge 但低于门控

变更：

```text
src/qount/l1_cross_asset.py（抽出 fetch_cross_asset_panel；新增 evaluate_l1_timeseries_momentum
                            + L1TimeSeriesMomentumService）
src/qount/main.py（新增 research-only 命令 l1-cross-asset-tsmom-scan）
tests/test_strategy_optimization.py（+1 单测：持续趋势→正净 Sharpe、lookback 计 trial）
```

S1 广度通过后做 S2:在 21-ETF 跨资产面板上做经典时序动量(Moskowitz-Ooi-Pedersen 风格)——
每标的 position=sign(trailing L 周收益),按 trailing 已实现波动率反比定权(决策时点、防泄漏),
跨标的归一到单位 gross,周再平衡;聚合扣费净值喂 §7 的年化 Sharpe / DSR / PBO harness,每个
lookback 计一个 DSR trial。research-only,无仓位。门控:年化净 IR ≥ 0.5 + DSR ≥ 0.95 + PBO < 0.5。

验证：

```text
local unittest=263 OK（262 → +1）
sync-to-wsl.sh --install=OK
WSL unittest=263 OK
```

WSL 实跑(21-ETF、753 周 2012-2026、cost 0.0006/side、vol_lb 26 周、lookback {13,26,39,52})：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260606T063553Z-l1-cross-asset-tsmom-scan/
effective_breadth=2.973  BR_annual≈155  required_IC≈0.080
best 年化净 Sharpe=0.421（lb39w，gross 0.542）；4 lookback 净 Sharpe 全正 0.10/0.33/0.42/0.40
DSR=0.856（< 0.95）  PBO=0.627（> 0.5）  net 全正
逐年(lb39w): 多数年正,2013/2016/2018/2020/2023 负,集中在 2019/2022(+0.068,利率趋势)/2024
decision=tsmom_below_gate（ir_pass=False, dsr_pass=False, pbo_pass=False, net_pass=True）
```

读法：**与之前所有路本质不同——跨资产趋势是真实、正、经济一致的 edge**(4 lookback 全正、
2022 利率趋势 crisis-alpha),不是 L3a 式符号翻转噪声。**但在零售 ETF universe 上只有 ~0.42
净 Sharpe,低于预设 IR 门控 0.5;DSR/PBO 不过**(部分因 4 lookback 近乎等价、选不出单一最优——
PBO 高的正确回应是 ensemble 而非选一个)。绑定限制从「广度」变成「**零售 ETF 的原始 edge 量级**」:
真 CTA 用 50–100 个期货跨更多板块,广度与 Sharpe 都更高,而那需要券商(S5,刻意推迟)。S2 按
预设门控未过 → 不进 S3。下一步是所有者决策(见下方注):(a) lookback 等权 ensemble(无参、直接
回应 PBO);(b) 接受 ~0.42 Sharpe 作零售-ETF 天花板,决定是否值得 paper/券商;(c) 停。硬约束
全不变,未碰 `validation_v1`、未开任何券商。

### L1 S1 广度 kill-test 通过:跨资产 universe 逃逸 majors 广度天花板

变更：

```text
src/qount/l1_cross_asset.py（新模块：Tiingo EOD fetch/缓存/复权归一化 + 广度 kill-test service）
src/qount/main.py（新增 research-only 命令 l1-cross-asset-breadth-scan）
src/qount/settings.py（新增 tiingo_api_key，默认 None，从 QOUNT_TIINGO_API_KEY 读）
tests/test_strategy_optimization.py（新增 L1CrossAssetTests，3 单测）
docs/l1-cross-asset-plan.md（新计划文档）
```

所有者从 L1/L4/L5 选 **L1 跨资产趋势(正面攻 BR)**。L1 命门:跨资产 universe 的有效广度是否
≫1.6。纯数据、零新场:拉免费跨资产日线 EOD(Tiingo,复权 adjClose)→ as-of 周线 → 量
`_panel_effective_breadth`(复用 §7 harness)。research-only,无仓位、不算 IC。

**关键基建发现:** 跨资产 TradFi 免费免-key 源从生产主机全不可用——Stooq 反爬 JS 页、Yahoo 429、
FRED 超时;Tiingo/AV/TwelveData/FMP 可达需 key。**选 Tiingo**(已配 `QOUNT_TIINGO_API_KEY`),
缺 key 命令不崩溃返回提示。

WSL 实跑(广度随 universe 正确变宽单调改善)：

```text
crypto majors 基线(§7): N=12 r̄≈0.63 effective_breadth≈1.6   ← 天花板
L1 最小 13-ETF(SPY/EFA/EEM/TLT/IEF/LQD/HYG/GLD/SLV/DBC/USO/UUP/VNQ, 2010-2026, 857 周):
    r̄=0.354  effective_breadth=2.477  → 临界(< 2.5, breadth_ceiling_holds)
L1 完整 21-ETF 跨资产(+IWM/EWJ/FXI/SHY/EMB/TIP/UNG/DBA, 2012-2026, 753 周):
    r̄=0.303  effective_breadth=2.973  → breadth_supports_l1 ✅
artifact=/home/alyaloale/Code/qount/state/research_runs/20260606T062015Z-l1-cross-asset-breadth-scan/
```

验证：

```text
local unittest=262 OK（259 → +3）
sync-to-wsl.sh --install=OK
WSL unittest=262 OK
Tiingo SPY 实拉 schema=date(ISO)+adjClose,与归一化一致
```

单测(3,离线注入 fetcher)：Tiingo adjClose 归一化/排序/跳过坏行;近正交 Walsh 面板
effective_breadth > 2.0;缺 key 返回 error 不崩溃。

读法：**L1 命门论点成立。** 随 universe 从 crypto majors → 13-ETF → 21-ETF 正确变宽,
r̄ 0.63→0.354→0.303、有效广度 1.6→2.48→2.97(~1.86× crypto 天花板)单调改善——**真正跨资产
的 universe 结构性逃逸了 majors 广度天花板**(这正是 §7 / L3 都缺的那一项)。门控 2.5 未动,
只按论点本意把欠采样的 13-ETF 探针补成真实 CTA 风格 universe(加 natgas/ags/TIPS/EM 债/短端/
多股区域)。含义:eff_breadth 2.97 × ~52 周 → BR≈154 → **要求 IC≈0.081**(可达区,远好于横截面
0.15)。**S1 通过 → 进 S2**(ts_mom 聚合 IR / 扣费净值 / DSR / PBO)。诚实保留:广度过线是必要
非充分,趋势扣费后 IR 是否真过线是 S2 才知道;**开券商只在 S1–S4 全过后**。硬约束全不变,未碰
`validation_v1`。

变更：

```text
src/qount/l1_cross_asset.py（新模块：Tiingo EOD fetch/缓存/复权归一化 + 广度 kill-test service）
src/qount/main.py（新增 research-only 命令 l1-cross-asset-breadth-scan）
src/qount/settings.py（新增 tiingo_api_key，默认 None，从 QOUNT_TIINGO_API_KEY 读）
tests/test_strategy_optimization.py（新增 L1CrossAssetTests，3 单测）
docs/l1-cross-asset-plan.md（新计划文档）
```

所有者从 L1/L4/L5 选 **L1 跨资产趋势(正面攻 BR)**。按 §1 的命门——L1 整条论点只赌
「跨资产 universe 的有效广度是否 ≫1.6」——先做**纯数据、零新场**的广度 kill-test:拉免费
跨资产日线 EOD 面板(SPY/EFA/EEM/TLT/IEF/LQD/HYG/GLD/SLV/DBC/USO/UUP/VNQ),as-of 周线,
量 `_panel_effective_breadth`(复用 §7 harness)。research-only,无仓位、不算 IC。

**关键基建发现(已在 WSL 实测可达性):** 跨资产 TradFi **免费免-key 源从生产主机全部不可用**——
Stooq 返回反爬 JS 挑战页、Yahoo Finance 429 限流(直连+代理均是)、FRED 超时(网络路径被挡)。
可达且可用的是**需免费 key 的提供商**:Tiingo(200 实测可达、免费档 1000 req/天)、Alpha
Vantage / Twelve Data / FMP(均可达需 key)。**选 Tiingo**;缺 key 时命令不崩溃,返回
`error=missing_tiingo_api_key` 提示。所有者去拿 key,本轮先**离线预建适配层**。

验证：

```text
local unittest=262 OK（259 → +3）
sync-to-wsl.sh --install=OK
WSL unittest=262 OK
缺 key CLI 路径=干净返回 missing_tiingo_api_key（不崩溃）
```

单测(3,全离线注入 fetcher,不联网/不需 key)：Tiingo EOD 用 adjClose 归一化/排序/跳过坏行;
近正交 Walsh 面板的 effective_breadth > 2.0(去相关→广度高,正是 L1 要验证的);缺 key 返回
error 不崩溃。

读法：L1 数据层 + 广度 kill-test 已就绪,**等所有者把 `QOUNT_TIINGO_API_KEY` 放进 `.env`** 即可
跑真实广度检查。门控:effective_breadth > 2.5 → 广度论点成立、进 S2(ts_mom IR/DSR/PBO);
≲1.6 → 与 majors 无异、廉价证伪、转 L5。**开券商只在 S1–S4 全过之后,绝不提前。** 硬约束全不变。

### L3 全线证伪 → 按 §8/§7 退出:L3b 链 TVL 横截面证实"广度幻觉"

变更：

```text
src/qount/l3_information_edge.py（新增 evaluate_l3b_chain_tvl_cross_section + L3ChainTvlCrossSectionService
                                 + 链 TVL fetch/缓存 + _panel_effective_breadth）
src/qount/main.py（新增 research-only 命令 l3-chain-tvl-scan）
tests/test_strategy_optimization.py（+2 单测：effective-breadth 随相关变化 / 横截面强正 IC 还原）
```

按所有者选择,L3a 证伪后做 L3b(链上横截面)。计划 §2 硬性要求:**effective_breadth 与
rank-IC 二者一起判生死**。信号=DefiLlama 链 TVL log-增速(lookback 4/8/13 周),横截面排序
12 个"链 token"(ETH/SOL/BNB/AVAX/ARB/SUI/TRX/OP/APT/NEAR/POL/ADA,各自映射到 DefiLlama 链
TVL),预测 token t→t+h(1/2/4 周)forward return。复用 §7 harness(per-anchor Spearman →
rank_ic_mean、`_panel_effective_breadth` N/(1+(N-1)r̄)、DSR、PBO)。BTC 同款期货 fapi 价格。
research-only。门控:|IC| ≥ 0.15(§10.2 横截面参考)且 effective_breadth > 2.5(§2 逃逸条件)。

验证：

```text
local unittest=259 OK（257 → +2）
sync-to-wsl.sh --install=OK
WSL unittest=259 OK
```

WSL 实跑(12 链 TVL + 12 token 期货价格全缓存,2022-06..2026-06 / 209 周)：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260606T052959Z-l3-chain-tvl-scan/
effective_breadth=1.680  (N=12, mean_abs_pairwise_corr r̄=0.559)  < 逃逸阈 2.5 → breadth_escape=False
best |rank_ic_mean|=0.0755 (L4w/h4w, t=3.47, 正) < gate 0.15 → ic_pass=False
全 9 cell rank-IC 均为正、符号稳定; DSR=0.953(过) / PBO=0.361(过) / LS net 全正
decision=falsified_l3b
```

读法：**这是比 L3a 更精确、更有意义的证伪,且证实了计划 §2 预警的"广度幻觉"。** 与 L3a 的
符号翻转噪声不同,L3b 找到一个**真实、符号稳定、统计显著(t=3.5)、DSR/PBO 都过**的弱信号——
链 TVL 增长确实正向预测 token 收益。**但 token 收益面板的有效广度仍只有 1.68**(r̄=0.559,几乎
贴着 §7 价量天花板 1.6),远低于 2.5;广度不逃逸 → 要求 IC 仍 ~0.15,真信号 0.075 只有一半。
**§7 架构级根因在新数据源上原样复现:绑定约束是广度(majors 同涨同跌),不是信号;即便真信号也被
结构性广度天花板压死。** TVL 增长本身跨链同向(DeFi 周期),signal 维度也不制造正交 dispersion,
正是广度不逃逸之因。

**结论(按 §8):L3a + L3b 均证伪 → L3 这一信息源整体证伪 → 回到 §7 诚实止盈。** 慢数据换信息源
没有绕开广度天花板:择时(L3a)无稳定 IC、横截面(L3b)有真 IC 但广度封死。下一次重启需**真正
结构性新输入**(L1 真低相关 universe / L4 跨所套利不预测方向 / L5 换预测目标),而非 L3 内部继续
堆特征/调参。固化的反过拟合 + effective-breadth + DSR/PBO harness 现已覆盖价量与非价量两类源,
是项目主要研究成果。硬约束全不变(live 关闭、不 forward paper、未碰 `validation_v1`)。

### L3 S1 kill-test:稳定币供给增速 → BTC 周线择时(证伪)

变更：

```text
src/qount/l3_information_edge.py（新增 evaluate_l3a_stablecoin_timing + L3StablecoinTimingService）
src/qount/main.py（新增 research-only 命令 l3-stablecoin-timing-scan）
tests/test_strategy_optimization.py（+3 单测：close 归一化 / 强正 IC 还原 / 每 config 计 trial）
```

按 `l3-information-edge-plan.md` §4/§5 的 S1 做 L3a 决定生死的一刀:稳定币供给 log-增速
(lookback 4/8/13 周)在 t 是否横向时序预测 BTC t→t+h(h=1..4 周)的 forward return。复用 §7
已落地的反过拟合 harness——Spearman rank-IC、`compute_directional_deflated_sharpe`(DSR)、
`compute_directional_pbo`(PBO/CSCV)、`_sharpe`,周线 cadence 标 `7d`(annualization 365/7)。
12 个 (L×h) config **全部计入 DSR trial**(多 horizon = 多 trial)。BTC 价格走期货 fapi
(现货 api.binance.com 在生产主机被墙;永续周线 close 等价、且与全研究线一致)。research-only,
无仓位、不碰 live。门控:breadth-adjusted 要求 IC ≈0.083(§2,IR=1 / ~150 周 √BR≈12)。

验证：

```text
local unittest=257 OK（254 → +3）
sync-to-wsl.sh --install=OK
WSL unittest=257 OK
```

WSL 实跑两窗口(供给/价格均缓存命中,价格 2260 日度 bar)：

```text
artifact_full=/home/alyaloale/Code/qount/state/research_runs/20260606T051647Z-l3-stablecoin-timing-scan/
artifact_sub =/home/alyaloale/Code/qount/state/research_runs/20260606T051746Z-l3-stablecoin-timing-scan/
窗口 2020-07..2026-06 (309 周): best |rank_ic|=0.0543(L8w/h4w,正) < gate 0.083 → ic_pass=False
  所有 cell net 正,但退化:供给增速几乎恒正 → sign≈+1 → 策略≈恒做多 BTC,net 正是 beta 非择时;
  DSR=0.957 / PBO=0.282 因 12 config 高度雷同(都 long BTC)而虚高,不具判别力。decision=falsified_l3a
窗口 2022-06..2026-06 (209 周): best |rank_ic|=0.1537(L13w/h4w)过门控,但 **符号为负**
  (-0.154,与"供给=干火药→涨"先验相反)、top3 全负;DSR=0.666(<0.95)、PBO=0.643(>0.5,高过拟合)
  → decision=falsified_l3a
```

读法：**L3a 证伪**。决定性指标是 rank-IC(Spearman,对单调变换不变,故 z-score 救不了——只有
真正不同的信号如加速度/跨稳定币背离才算新信号,属 S2,而 S2 仅在 S1 正时才开)。两窗口给出
互补证伪:(a) 全窗口 |IC| 0.054 低于门控,净正只是退化恒做多的 BTC beta;(b) 子窗口 |IC| 虽过
门控却**符号翻转**且 PBO 0.64(过拟合)。**符号在窗口间翻转 = 无稳定、符号一致、样本外的预测关系**
——稳定币供给与 BTC 同骑一条流动性周期(内生共动,非外生预测),lead/lag 随 regime 翻号。这与 §7
价量横截面 IC ~0.05 天花板同源。下一步按 §5/§8:测 L3b(链上横截面,但相关天花板仍在、且共动顾虑
同样适用),或若经济动机耗尽则 L3 也按 §7 退出。硬约束全不变,未碰 `validation_v1`。

### L3 S0.1 数据接入层:DefiLlama 稳定币供给(fetch / 缓存 / as-of 归一化)

变更：

```text
src/qount/l3_information_edge.py（新模块：fetch + state 缓存 + as-of 无前视归一化）
src/qount/main.py（新增 research-only 命令 l3-stablecoin-fetch）
tests/test_strategy_optimization.py（新增 L3InformationEdgeTests，5 个单测）
```

按 `l3-information-edge-plan.md` §5 的 S0.1（数据接入层，无策略行为变化）落地 L3 第一线的
数据骨架：拉 DefiLlama 聚合稳定币总供给(`totalCirculatingUSD.peggedUSD`)、缓存到 `state/`
供离线复跑、归一化成排序去重的日度序列、以严格 as-of(无前视)join 到周线锚点。只用 stdlib
`urllib`(走 settings 代理),不引入新依赖;research-only,live / `run-once` 不 import 本模块、
行为不变。**只做数据层,不算 IC、不下注**——IC kill-test 是 S1。

单测(5)：归一化排序/去重/跳过坏行 + 秒→毫秒;as-of join 取 ≤ 锚点最近一笔且不泄漏未来、
锚点前返回 None、末点向后 carry;weekly_anchors + resample 对齐;缓存命中短路 fetcher
(网络绝不触发);fetch 写缓存后二次命中 + service summary 字段。

验证：

```text
local unittest=254 OK（249 旧 + 5 新）
sync-to-wsl.sh --install=OK
WSL unittest=254 OK
```

WSL 端到端真实拉取(DefiLlama 实网 + 缓存命中两条路径都验证)：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260606T045947Z-l3-stablecoin-fetch/l3_stablecoin_fetch.json
cache=state/l3_cache/defillama_stablecoin_supply.json
fetched_from=network（首跑） / cache（二跑，未走网络）
raw_point_count=3112  normalized_point_count=3112（零丢点）
first_obs=2017-11-29  last_obs=2026-06-06  latest_supply_usd=314,644,712,883
window 2022-06-01..2026-06-01: weekly_anchor_count=209 weekly_covered=209（全覆盖）
  weekly_log_growth_mean=+0.00336（约 0.34%/周供给增速）
full history 2017-11-29..2026-06-01: weekly_anchor_count=444 weekly_covered=444
```

读法：数据层成立。周线覆盖无缺口,3112 日度观测归一化零丢失,as-of resample 209/209 与
444/444 全覆盖。可用周线广度比计划估的 150–200 更宽——近 4 年窗口 209 周(√209≈14),全历史
444 周(2017–2020 是不同 regime,慎用)。下一步 **S1 kill-test**:稳定币供给增速对 BTC 周线
forward-return 的时序 rank-IC + DSR/PBO,门控 breadth-adjusted 要求 IC ≈0.083。硬约束全不变,
未碰 `validation_v1`。

### 重启方向设计:L3 换信息源(链上/流/叙事 + AI)

§7 止盈后,按 §11.8「唯一合法重启触发=结构性新输入」做重设计。先用基本定律把可盈利空间
框死(必须结构性换掉 BR/IC/游戏之一),给出五条杠杆并权衡:

```text
L1 跨资产趋势(低相关 universe 抬 BR)   —— 教科书正解,但需新交易所/经纪+跨资产基建
L2 事件驱动(广度来自独立事件)          —— 绕开相关天花板,慢版事件 HFT 不玩
L3 换信息源(非价量慢数据+AI 攻 IC)     —— 最贴操作者优势(慢+AI+耐心),kill-test 廉价  ★选中
L4 跨所 funding/基差套利(不预测方向)   —— 多场资本+执行受限(>100% maker fill)
L5 换预测目标(预测波动率而非方向)      —— 需期权场变现
```

所有者选 **L3**。新建计划文档 `docs/l3-information-edge-plan.md`:把信息源从价量换成非价量
慢数据(稳定币供给/链上流/TVL/衍生品持仓)、horizon 抬到日/周线、AI 从最终 gate 挪到慢特征/
regime 标注层(§P5 本来方向)。关键诚实点:**L3 不自动修广度**,故分两子路——
**L3a 市场择时**(广度来自时间 ~150 周、要求 IC ≈0.083、单一最液体标的执行最干净)优先;
**L3b 横截面**(相关天花板仍在,要求 IC ~0.15,需信号维度 effective-breadth>2.5 才成立)次之。
第一刀 kill-test:DefiLlama 稳定币供给对 BTC 周线 forward-return 的时序 rank-IC + DSR/PBO,
门控 breadth-adjusted 要求 IC ≈0.083。周线样本少(~150–200 obs)是头号过拟合风险,对策是
经济预设假设(非网格搜索)+ 复用 §7 已落地的 DSR/PBO/purged-CV/effective-breadth harness。
仍 research-only、硬约束全不变;两子路都证伪则 L3 也按 §7 退出。**尚未开工。**

### 架构级根因:横截面广度天花板 ≈ 1.6,§10.2 破局数字被经验证伪

无新代码 / 无新扫描——直接读 funding artifact 已报的 `effective_breadth`(标准公式
`N/(1+(N-1)·r̄)`),查 §10.2「日频横截面 ~10 币 → BR~300 → 要求 IC 0.06」的前提是否成立。

```text
top12 平均绝对两两相关 r̄ ≈ 0.628（4h 0.620 / 8h 0.635 / 1d 0.628）
有效广度: N=12 → 1.52 ; N=20 → 1.55 ; N=30 → 1.56 ; N=100 → 1.58 ; N=1e6 → 1.59
渐近天花板 1/r̄ ≈ 1.59  → 扩币在数学上救不了（N→∞ 仍 < 1.6）
要求 IC(Grinold IR=IC·√BR, IR=1):
  §10.2 假设 ~10 币  BR≈300  √BR=17.3  IC_req=0.058
  真实   ~1.5 币    BR≈ 46  √BR= 6.8  IC_req=0.148
观测最强横截面 IC: xs_mom 0.052 / xs_funding 0.030 → 离要求 ~3x 缺口
```

结论：加密 majors 同涨同跌,横截面把"12 币"折成 ~1.6 个有效独立资产,§10 押注的广度杠杆
**结构性不存在**;要求 IC 被打回 ~0.15 的"5m 不可达"区间——正是 §10 想逃离的天花板。这是
**架构级 §7 证据**:xs_mom / ts_mom / xs_funding 全部过不了线是同一个根因(广度,不是特征),
换特征源 / 扩币都改变不了。

**2026-06-06 项目级决策(所有者确认):执行 §7 诚实止盈,停止追盈利。** latency-insensitive
可触及路径(横截面/日频时序/CARRY)均穷尽且证伪,广度杠杆结构性不存在 → 满足 §7 全局终止条件。
固化整套反过拟合 harness 作为研究成果,停止在择时盈利上继续投入;重启触发条件应是结构性新输入
(真正低相关 universe / 新资产类别 / 可执行低延迟微结构通道),而非继续在已穷尽空间搜索。
硬约束全不变(live 关闭、不 forward paper、不放宽 broad gate、validation_v1 once-only)。
详见 `profit-engineering-plan.md §11.8`。

### §10 换特征源 kill-test:funding 作预测特征(证伪)

变更：

```text
src/qount/strategy_selection.py（新增 xs_funding / xs_funding_rev 族 + 共享聚合重构）
src/qount/main.py（--families 增 xs_funding/xs_funding_rev、新增 --carry-tilt-signal）
tests/test_strategy_optimization.py（as-of 无前视 / 跳过缺 funding / rank-IC 还原 / basis 字段）
```

按 §10 / §11.7 走"换特征源"的第一刀:把 funding 当**横截面预测特征**(问"funding 在 t
是否横截面预测 t→t+h 的 forward return"),区别于已被 basis-tail 证伪的 CARRY 现金流用法。
实现:`_asof_value` 严格 as-of join(取 fundingTime ≤ bar 的最近一笔,无前视)→
`build_carry_tilt_samples`(signal=funding_rate,`xs_funding_rev` 取负)→
`evaluate_cross_sectional_carry_tilt` 复用与价量族**同一套**横截面 IC / 多空 / 周期收益聚合
(抽出 `_aggregate_directional_cross_sections`),故 DSR/PBO 对 funding 与价信号一视同仁。
carry-tilt cell 独立成自己的 trial set 算 DSR/PBO,不与价量网格混合稀释多重检验惩罚。
research-only,不改 PnL / live;默认 `--families` 不含新族,opt-in。

验证：

```text
local unittest=249 OK（245 旧 + 4 新）
sync-to-wsl.sh --install=OK
WSL unittest=249 OK
```

读数（top12 `BTC/ETH/ZEC/SOL/HYPE/WLD/XRP/BNB/NEAR/DOGE/ADA/SUI`、120 天 discovery、
post-cost、{4h,8h,1d}×{xs_funding,xs_funding_rev}×holding{1,3,6}=18 cell）：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T231910Z-strategy-selection-scan-qount-s1-carry-tilt-funding-top12real-120d-20260606/qount-s1-carry-tilt-funding-top12real-120d-20260606.json
rank_ic: 全 |IC| ≤ 0.030（最强 4h/h3 xs_funding +0.030）
best_cell: 1d xs_funding_rev h6  sum=+1.0530  sharpe=+1.7894  但 rank_ic≈+0.0052≈0
           （相邻 holding 不一致 h1 负 / h3 +0.50 / h6 +1.05 → 1d 119 重叠横截面噪声）
carry_tilt_DSR=0.2495（best per-period sharpe 0.0937 < 噪声期望最大 0.1559）
carry_tilt_PBO: 4h=0.246 / 8h=0.552 / 1d=0.488（8h/1d ≈ 抛硬币）
4h/8h 全部 post-cost 负（高换手 × 微弱 edge → 成本主导）
```

另跑 4 币薄广度交叉验证(`...funding-top12-120d-20260606`，`multi-symbol` profile 实际仅
4 币 SOL/XRP/BTC/ETH):rank-IC 更弱、DSR ≈ `0.068`、PBO 顶 `0.687`,结论一致。

结论：funding-as-feature 的横截面预测内容比价量动量更弱、DSR/PBO 不过关、post-cost 无稳健
正 cell。继 CARRY 现金流(basis-tail 证伪)之后,funding 这一新信息源**两种用法均证伪**;
最便宜的新源耗尽。剩余 §11.7 named 源(微结构无廉价历史盘口、时序基础模型需重 ML 栈/libomp)
都不便宜。强化 §7 诚实止盈分支。硬约束全不变,未碰 `validation_v1` once-only。

### `4h xs_mom lb24/h6` 候选 §7 诚实退出

变更：

```text
docs/current.md
docs/profit-engineering-plan.md（§11.1 / §11.5 / 新增 §11.7）
docs/quick-handoff.md
docs/update-log.md
```

纯决策记录轮,无新研究扫描——遵守"不在已看 2–5 月上加任何旋钮"。把上一轮 N1/DSR/PBO 读数
(DSR ≈ `0.082`、PBO 4h=`0.020`、Sharpe 改善但 in-sample、~82% 收益来自 5 月)汇总成对 §7
诚实退出条件的判定:候选在穷尽当前频段/族的 grid 后,无统计显著的扣费后正 edge。

三条诚实退出依据：

1. **网格内选择优势大概率是多重检验假象**：81-cell DSR ≈ `0.082`,最佳 per-period Sharpe
   `0.278` 低于噪声期望最大值 `0.407`。
2. **没有任何可执行 exit 跑赢"持有到期"基线**：σ 缩放 triple-barrier 四组最佳
   `tp4/sl4=+0.165` < close-exit `+0.297`;fixed TP/SL 全负。
3. **收益高度时间集中**：~82% 来自 2026-05 单月,2/3 月度 sanity 反复为负。

为什么不烧 once-only：新 OOS 只多出 2026-06-04..06 的 ~2 天(~12 根 4h bar),薄到无法把
DSR ≈ `0.082` 的弱信号顶上统计显著;在已基本触发 §7 的情况下,消耗一次性日期是浪费稀缺资源。

状态变更：S1' prediction-family 路径 ⛔ 关闭;S2/S3 ⛔ 未启动;N1 门控 ✅ 判定关闭(DSR 分支先于
新 OOS 触发)。研究 pivot:§10 换频段 / 换特征源,或 §7 止盈。硬约束(live 关闭、不 forward paper、
不放宽 broad gate、不在 `discovery_pool` 调参后当 promotion、外部模型不进 candidate/risk/live)不变。

验证：

```text
本轮无新扫描；上一轮 local unittest=245 OK / WSL unittest=245 OK 仍是当前测试真相。
```

## 2026-06-05

### S1' PBO / CSCV 过拟合概率

变更：

```text
src/qount/strategy_selection.py
tests/test_strategy_optimization.py
```

按 §5 / §9.x 补 Probability of Backtest Overfitting（Bailey & López de Prado 的 CSCV）。
新增 `compute_directional_pbo`（按频段分组：时间轴切 S=10 个 block，对 C(10,5)=252 种
IS/OOS 划分，取 IS-best config 看其 OOS 相对排名 ω → logit；PBO = λ≤0 的比例）；各
directional evaluator 多输出一个**仅内存**的 `period_returns_by_timestamp` 序列供 DSR/PBO 用，
算完即从 cell 剥离、不进 artifact。scan 顶层输出 `directional_pbo`（含 `by_frequency`，
primary 频段对齐到 DSR 的最佳 per-period Sharpe 所在频段）。research-only，不改 PnL / live。
新增单测：一致最优 config 时 PBO=0、无公共序列返回 None。

验证：

```text
local unittest=245 OK
sync-to-wsl.sh --install=OK
WSL unittest=245 OK
```

同一 81-cell 低频网格读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T150603Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-dsr-pbo-120d-20260605/qount-strategy-selection-s1-lowfreq-top12-dsr-pbo-120d-20260605.json
block_count=10 combos=252 configs_per_freq=27
pbo_1h=0.0556 median_logit=1.9042
pbo_4h=0.0198 median_logit=2.8332
pbo_1d=0.2143 median_logit=1.9042   (primary)
```

读法：DSR 与 PBO 互补、不矛盾。DSR 问"绝对 Sharpe 量级通缩后是否显著"→ 否(0.082)；
PBO 问"IS-best 在 OOS 是否仍靠前"→ 大体是(PBO 全 < 0.5、median_logit > 0)。合起来：存在
**弱但排名稳定**的横截面动量结构(非纯随机 → PBO 低)，但量级太弱(DSR≈0.08)，多重检验 +
成本 + 路径执行后不足以确认盈利。诚实保留：同频段 27 个 config 高度相关会让 CSCV 排名稳定性
虚高、PBO 偏低，低 PBO 不等于低过拟合风险。两指标都指向**不进 S2**，等新完整 OOS。

### S1' Deflated Sharpe Ratio 多重检验惩罚

变更：

```text
src/qount/strategy_selection.py
tests/test_strategy_optimization.py
```

按计划 §5 / §9.x（"阶段 1/2 的模型/配置选择必须报告 DSR/PBO"）补 Deflated Sharpe Ratio。
新增 `compute_directional_deflated_sharpe(cells)`（López de Prado 口径，正态简化）+ 每个
directional cell 的 `portfolio_period_count`；scan 顶层输出 `directional_deflated_sharpe`。
research-only diagnostic，不改 PnL / live / `run-once`。新增单测：trial 越多越通缩、<2 trial
返回 None。

验证：

```text
local unittest=243 OK
sync-to-wsl.sh --install=OK
WSL unittest=243 OK
```

在**选出候选的那张 81-cell 低频网格**（`1h/4h/1d × xs_mom/xs_rev/ts_mom × lb3/12/24 ×
h1/3/6`、top12、120 天 discovery）上读 DSR：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T143817Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-dsr-120d-20260605/qount-strategy-selection-s1-lowfreq-top12-dsr-120d-20260605.json
trial_count=81
best_by_per_period_sharpe=1d xs_mom lb24/h6
best_per_period_sharpe=0.27825601
expected_max_per_period_sharpe=0.40655144
trial_per_period_sharpe_variance=0.02741146
best_period_count=119
deflated_sharpe_ratio=0.08171240
assumes_normal_returns=true
```

读法：迄今最重要的反过拟合读数。**观测最佳 per-period Sharpe `0.278` 比 81 次随机试验下
噪声期望最大值 `0.407` 还低，DSR ≈ `0.082`**（通常要求 > 0.95）——候选的网格内选择优势在
统计上与"81 次噪声里挑最大"不可区分，且正态假设对肥尾会高估 DSR，真实只会更低。结论从
"候选还需新 OOS"收紧为"网格内选择优势大概率是多重检验假象"。S2 门控加硬：新 OOS 正 +
可接受 DSR/PBO 才进 S2，否则按 §7 诚实退出。**仍不进 S2**。

### S1' N1 regime dispersion 入场门

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增 research-only 参数（在每个 cross-section 上按各币 signal 的离散度 sample std 做 regime
入场门；低于阈值 = 同涨同跌、无相对强弱 = 跳过该 bar 不下注；纯决策时点，无 look-ahead）：

```text
--directional-regime-min-dispersion-pct
```

默认 0(关闭)，历史 artifact、live / `run-once` / CARRY / ts_mom 全部不变。新增单测：
低离散度 cross-section 被 gate、turnover 与 gated 计数、artifact 新字段。

验证：

```text
local unittest=241 OK
sync-to-wsl.sh --install=OK
WSL unittest=241 OK
```

候选 `4h xs_mom lb24/h6` top12 120 天每根 bar 的 signal dispersion 分布：

```text
p10=0.02513 p25=0.03410 p50=0.04829 p75=0.06812 p90=0.10880 min=0.01326 max=0.16409
```

固定同一候选、close-exit、portfolio_replay、`max_open=12`、120 天 discovery 扫阈值：

```text
thr0.000 sum=+0.297491 sharpe=+7.1945 dd=0.0877 gated=0   traded=721 win=0.4952
thr0.034 sum=+0.298812 sharpe=+7.9989 dd=0.0798 gated=178 traded=543 win=0.5119
thr0.048 sum=+0.272640 sharpe=+8.9771 dd=0.1021 gated=356 traded=365 win=0.4940
thr0.068 sum=+0.195078 sharpe=+11.8154 dd=0.0527 gated=539 traded=182 win=0.4953
```

`thr0.034` 月度（对比无过滤 close-exit replay 基线）：

```text
feb_sum=+0.024688 ic=-0.00846  (baseline +0.0063)
mar_sum=+0.002786 ic=-0.00387  (baseline -0.0094 → 翻正)
apr_sum=+0.063078 ic=+0.10121
may_sum=+0.246376 ic=+0.16039
```

`thr0.068` 月度（过滤过狠，2/3 月又转负）：

```text
feb_sum=-0.016136 ic=-0.14038
mar_sum=-0.030840 ic=-0.11364
apr_sum=+0.036571 ic=+0.24559
may_sum=+0.205484 ic=+0.15315
```

artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260605T142637Z-...-regime-thr034-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/...-regime-{thr000,thr048,thr068}-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/...-regime-{0034,0068}-{feb,mar,apr,may}-20260605/
```

读法：这是 N1 里第一个**在正确轴上**改善候选的子步骤(部分止盈/移动止损本质仍是已被
vol-barrier 证伪的路径 exit,故改做 entry 侧 regime 过滤)。`thr0.034` 总收益不变、Sharpe
`7.19→8.00`、回撤 `0.088→0.080`、换手更少,并把 2026-03 从负翻正、4 月全部 ≥ 0,直接打到
"月度全靠单月"的门控失败点。但两条硬保留:(1) 阈值在同一 120 天窗口的 dispersion 分布上选
(p25),属 in-sample 阈值选择;(2) 5 月仍约 82% 收益,只是不再有负月;且全部已看 discovery。
结论:候选状态明显更好,但 §11.5 N1 门控仍未通过(无新完整 OOS、仍偏单月),**仍不进 S2**;
下一刀是把 `thr0.034` 固定参数留到下一个完整 `validation_v1` 独立窗口 once-only 复核。

### S1' N1 波动率缩放 triple-barrier

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增 research-only 参数（把 triple-barrier 的 TP/SL 从固定百分比改为按决策时点近 N 根
bar 已实现收益 σ 缩放，AFML 标准做法；σ 只用 t 时刻及之前的 close-to-close 收益，防泄漏）：

```text
--directional-barrier-vol-lookback-bars
--directional-take-profit-sigma
--directional-stop-loss-sigma
```

默认关闭(lookback=0)，历史 artifact 口径、live / `run-once` / CARRY 全部不变。新增单测：
`_recent_return_std` 忽略未来 bar(防泄漏)、双币 σ 自适应 barrier 行为、artifact 记录新字段。

验证：

```text
local strategy-selection tests=14 OK
local unittest=240 OK
sync-to-wsl.sh --install=OK
WSL unittest=240 OK
```

固定同一 `4h xs_mom lb24/h6`、top12、portfolio_replay、`max_open=12`、vol lookback `24`、
120 天 discovery（窗口 2026-02-01..2026-06-01），σ 倍率扫描：

```text
close_exit_baseline_sum=+0.2974912983 (无 barrier replay 既有读数)
tp1.5/sl1.5 sum=-0.143287 sharpe=-5.9154 SL=643 TP=635 TIME=168
tp2.0/sl2.0 sum=-0.050339 sharpe=-1.8044 SL=514 TP=544 TIME=388
tp3.0/sl2.0 sum=+0.037766 sharpe=+1.2470 SL=539 TP=339 TIME=568
tp3.0/sl3.0 sum=+0.118739 sharpe=+3.8430 SL=303 TP=360 TIME=783
tp4.0/sl4.0 sum=+0.165134 sharpe=+4.7454 SL=192 TP=222 TIME=1032
```

最佳 `tp4.0/sl4.0` 月度：

```text
feb_sum=+0.034363 ic=-0.02582
mar_sum=-0.039638 ic=-0.02285
apr_sum=+0.032380 ic=+0.09500
may_sum=+0.149386 ic=+0.16039
```

artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260605T141034Z-...-volbarrier-tp2-sl2-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T141103Z-...-volbarrier-tp15-sl15-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T141108Z-...-volbarrier-tp3-sl2-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T141113Z-...-volbarrier-tp3-sl3-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T141118Z-...-volbarrier-tp4-sl4-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T1411{56,01,06,11}Z-...-volbarrier-tp4-sl4-{feb,mar,apr,may}-20260605/
```

读法：vol-scaling 修正了 fixed barrier 的非对称止损病（fixed `tp0.030/sl0.015` 是
stop-loss `873` / take-profit `400` 约 `2.18x`；vol `tp2/sl2` 收敛到 `514/544` ≈ 1:1），
PnL 随 barrier 加宽单调改善。但没有任何 σ 设置能跑赢"无 barrier 持有到期"的 close-exit
基线 `+0.2974912983`——barrier 越宽越多 `time` 退出、越逼近 close，最佳 `tp4/sl4` 也只有
`+0.165134`。月度上最佳 barrier 的 3 月仍负、约 90% 收益来自 5 月单月，单月依赖未改善，
且全部是已看过 discovery。结论：§11.5 N1 门控未通过——可执行 path-dependent exit 仍未
跑赢持有、无月度稳健性；**仍不进 S2**。下一刀只能等新的完整独立 OOS 日期，或做更细的持仓
管理（部分止盈/移动止损/regime 过滤），不能 paper。

### 计划文档对账（代码 / 成果 / 计划三方校准）

本条只改文档，不动代码;本地全量测试仍 `237 OK`。把 `profit-engineering-plan.md` 的
前瞻计划与已落地代码、已跑 artifact 对账,发现并修正三处偏差:

```text
1. 计划/落地结构偏差:
   §9/§10 设计的 labeling.py / ic_diagnostic.py / cross-sectional-ic 命令 /
   scripts/strategy_selection_scan.py 均未单独存在;
   实际全部合并进 src/qount/strategy_selection.py(约 1647 行)+ strategy-selection-scan。
   triple-barrier=--directional-exit-mode triple_barrier;
   横截面 IC=cell.rank_ic_mean/effective_breadth;
   purged/embargo=--directional-purged-cv-folds/--directional-embargo-bars;
   CARRY 专线=--carry-model threshold_dual_leg + 全套 --carry-* flag。
   labeling.py / ic_diagnostic.py / meta_label_model.py / portfolio.py 当前不存在。
2. current.md 代码结构漏列 strategy_selection.py(最大研究模块),已补。
3. §10.4 分叉预测未成立:计划赌"CARRY 很可能胜",实际 CARRY 被 basis-tail 证伪,
   存活候选是预测族 4h xs_mom lb24/h6(非日频),且未过可执行 exit。
```

改动落点:

```text
docs/profit-engineering-plan.md  新增 §11「执行进展与计划校准」
                                 (S0–S5 进度表 / 模块映射偏差 / §10.4 分叉对照表 /
                                  带门控的下一步 N1–N4 / 硬约束不变)
docs/current.md                  代码结构补 strategy_selection.py;
                                 当前结论加 S1' 第一遍结论 + 指向 §11 的交叉引用
```

S0–S5 当前进度(校准后):

```text
S0.1 ✅ 已落地    S0.2 ✅ 复用既有    S0.3 ⬜ 未做(可选)
S1'  🔄 第一遍全量跑完,仍在 exit/OOS 复核期,无晋级候选
S2/S3/S4/S5 ⛔ 未启动(S2 硬门控未通过)
```

读法:这是一条 meta/对账记录,不引入新策略行为、不放宽任何硬约束、无新 artifact。
计划文档现在与代码和成果一致;S2 重模型仍按门控不启动,直到 4h xs_mom 在新 OOS 上
带可执行 exit 仍有 post-cost 正 edge。

### S1' low-frequency prediction grid

新增 research-only 参数：

```text
--signal-lookback-grid-bars
--holding-grid-bars
```

读法：只扩展 `strategy-selection-scan` 预测族的离线 grid，默认行为不变，不影响 live /
`run-once`。本地和 WSL 全量测试均为 `236 OK`。

关键结果：

```text
grid_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121551Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605/qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605.json
grid=1h/4h/1d x xs_mom/xs_rev/ts_mom x lookback 3/12/24 x holding 1/3/6
best=4h xs_mom lookback=24 holding=6
sum=+3.5251307739
sharpe=+7.1555415974
rank_ic=+0.0523457125
feb_sum=+0.0054374620
mar_sum=-0.3056398179
apr_sum=+0.9769441561
may_sum=+2.8938136721
jun01_04_sum=+0.2839507666
top_fraction 0.10/0.25/0.50 all positive
```

新增 research-only overlap sanity 参数：

```text
--directional-overlap-mode all|stride
```

默认 `all` 保持旧读数；`stride` 每个 holding window 只取一次 cross-section，先降低
`holding=6` 的重叠 horizon 膨胀。

```text
stride_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T123357Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605.json
stride_120d_sum=+0.5087944384
stride_120d_sharpe=+6.0811826595
stride_120d_rank_ic=+0.0607409120
stride_120d_cross_sections=121
stride_feb_sum=-0.0026969105
stride_mar_sum=-0.0234895413
stride_apr_sum=+0.0796046219
stride_may_sum=+0.5008009667
stride_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T123424Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605.json
stride_jun01_04_sum=+0.0627083513
```

结论：`4h xs_mom` 是当前最像样的 prediction-family discovery candidate；stride sanity
下仍为 120 天正收益，说明不是纯重叠 horizon 幻觉。但 2/3 月 stride 仍为负，`jun01_04`
是已看窗口。下一步不是 paper，而是 S1.1/S1.2：purged-CV、triple-barrier、
overlap-aware portfolio replay。

新增 research-only 限仓组合 replay 参数：

```text
--directional-evaluation-mode portfolio_replay
--directional-max-open-positions
```

默认仍是旧 `cross_section`，不影响历史 artifact / live / `run-once`。固定 `4h xs_mom`
lb24/h6、top12、top_fraction `0.25`、`max_open_positions=12`：

```text
portfolio_replay_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T125713Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605.json
portfolio_replay_120d_sum=+0.2974912983
portfolio_replay_120d_sharpe=+7.1945433715
portfolio_replay_120d_max_dd=0.0876673733
portfolio_replay_120d_trades=1446
portfolio_replay_120d_skipped=2880
portfolio_replay_120d_win_rate=0.4951590595
portfolio_replay_feb_sum=+0.0062629159
portfolio_replay_mar_sum=-0.0094161679
portfolio_replay_apr_sum=+0.0656249961
portfolio_replay_may_sum=+0.2463757288
portfolio_replay_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T125741Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605.json
portfolio_replay_jun01_04_sum=+0.0082009038
```

结论：限仓 replay 下 120 天仍为正，说明当前 candidate 不只是无限重叠下注的 artifact；
但 2026-03 仍为负，2026-02 只是微正，`jun01_04` 是已看窗口。下一步不是 paper，而是
S1.1/S1.2 的 purged-CV / triple-barrier / 新 OOS。

新增 research-only triple-barrier 参数：

```text
--directional-exit-mode close|triple_barrier
--directional-take-profit-pct
--directional-stop-loss-pct
```

默认 `close` 不变，不影响历史 artifact / live / `run-once`。同一 fixed cell、top12、
portfolio replay、max open `12`，120 天简单 barrier：

```text
tp015_sl010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132052Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.015-sl0.010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.015-sl0.010-20260605.json
tp015_sl010_sum=-0.2542260860
tp015_sl010_sharpe=-21.9420203800

tp020_sl010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132057Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.010-20260605.json
tp020_sl010_sum=-0.2307013696
tp020_sl010_sharpe=-16.8127315231

tp020_sl015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132104Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.015-20260605.json
tp020_sl015_sum=-0.2296270771
tp020_sl015_sharpe=-14.6592774682

tp030_sl015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132109Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605.json
tp030_sl015_sum=-0.1635040433
tp030_sl015_sharpe=-8.7264450618
```

最不差的 `tp=0.030/sl=0.015` 月度：

```text
exit_reason_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132953Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605.json
120d_exit_counts=stop_loss 873, take_profit 400, time 173
120d_win_rate=0.3443983402
feb_sum=-0.0356452182
feb_exit_counts=stop_loss 224, take_profit 110, time 8
mar_sum=-0.0631122398
mar_exit_counts=stop_loss 242, take_profit 107, time 29
apr_sum=-0.0812657295
apr_exit_counts=stop_loss 211, take_profit 73, time 82
may_sum=+0.0203985601
may_exit_counts=stop_loss 205, take_profit 116, time 57
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132208Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605.json
jun01_04_sum=+0.0177000000
```

结论：simple fixed TP/SL 把 120 天全部打负，且最不差参数 2/3/4 月全负，只剩 5 月和已看
6 月正。原因是路径执行失败：120 天 stop-loss 触发约为 take-profit 的 `2.18x`，交易成本
再把边际进一步压低。`4h xs_mom` 不能 paper；下一步只能做 purged-CV、exit 设计或新 OOS。

新增 fixed-cell purged/embargo CV 诊断参数：

```text
--directional-purged-cv-folds
--directional-embargo-bars
```

默认关闭，只影响 `strategy-selection-scan` 预测族 artifact，不影响 CARRY / live /
`run-once`。同一 fixed cell、top12、close exit、portfolio replay、max open `12`，
4 folds + 6 bars embargo：

```text
purged_cv_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T133904Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605.json
full_sum=+0.2974912983
full_sharpe=+7.1945433715
rank_ic=+0.0523457125
positive_folds=3/4
mean_fold_sum=+0.0743728246
min_fold_sum=-0.0566596009
fold1_sum=+0.0467298450
fold2_sum=-0.0566596009
fold3_sum=+0.0611460588
fold4_sum=+0.2462749954
```

结论：purged/embargo artifact 已把 fold 稳定性机器化，且 3/4 folds 为正，支持继续研究；
但 `2026-03-03..2026-04-01` fold 为负且 IC 为负，收益仍依赖后段行情。fixed close/replay
purged sanity 已跑完，不能 paper；下一步转向更稳健的 exit 设计、模型层 purged-CV 或新完整
OOS。

### S-CARRY basis-entry filter 和 top12 TS-MOM sanity

新增 research-only CARRY 参数：

```text
--carry-basis-entry-max-abs-pct
```

读法：只阻止 basis 已经偏离过大的新 CARRY 入场，默认关闭，不影响 live / `run-once`。
本地和 WSL 全量测试均为 `233 OK`。

关键结果：

```text
WLD/SOL basis_entry_max_abs=0.0008 discovery120d sum=-0.0066684341 after_tail=-0.0083560026
WLD/SOL basis_entry_max_abs=0.0010 discovery120d sum=-0.0010824000 after_tail=-0.0028620256
WLD/SOL basis_entry_max_abs=0.0015 discovery120d sum=+0.0020099742 after_tail=+0.0002303486
WLD/SOL jun01_04 all thresholds sum=-0.0003841457 after_tail=-0.0010857771
top12 1d ts_mom 120d sum=-2.6698947371 sharpe=-0.7852540386 rank_ic=-0.0517447570
top12 1d ts_mom monthly Feb/Mar/Apr all negative; May positive only
```

结论：entry-only basis filter 不能拯救当前 WLD/SOL S-CARRY；top12 扩币也不能让
`1d ts_mom` 进入 S1.1/S1.2。继续时不要重复这两条 sanity。

### profit-engineering S0.1 research 依赖隔离

变更：

```text
pyproject.toml
scripts/check-research-deps.sh
tests/test_strategy_optimization.py
```

读数：

```text
Mac Python=3.14.4
numpy=2.4.6 ok
sklearn=1.9.0 ok
lightgbm optional=false-to-import: missing libomp.dylib
local unittest=222 OK
```

落地结论：

- `research` optional extra 只默认安装 `numpy` / `scikit-learn`。
- `lightgbm` 单独放进 `research-lightgbm`；当前 Mac wheel 可安装但 import 需要额外
  `libomp.dylib`，所以后续 S2 默认用 sklearn `HistGradientBoosting`。
- 新增单测确认 `import qount.main` 不加载 `numpy` / `sklearn` / `lightgbm`，live /
  `run-once` 路径不因 research 依赖变化而改行为。
- 这一步只是 S0.1 地基，不是策略 promotion，不给 forward paper / live 许可。

### profit-engineering S1' strategy-selection-scan

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
src/qount/setup_model.py
```

新增命令：

```bash
python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families xs_mom xs_rev ts_mom carry \
  --frequencies 5m 1h 4h 1d \
  --lookback-days 30 \
  --signal-lookback-bars 12 \
  --holding-bars 1 \
  --output-path /tmp/qount-strategy-selection-s1-30d-20260605.json
```

WSL artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260605T065952Z-strategy-selection-scan-qount-strategy-selection-s1-30d-20260605/qount-strategy-selection-s1-30d-20260605.json
```

关键读数：

```text
window=2026-05-02T00:00:00Z..2026-06-01T00:00:00Z
best_cell=1d ts_mom
sum_return_pct=+0.3121233665
mean_return_pct=+0.0025171239
sharpe=2.2679849920
rank_ic_mean=+0.0085476003
effective_breadth=1.1323823788
5m_xs_rev_rank_ic_mean=+0.0289588724
5m_xs_rev_sum_return_pct=-20.6197925003
carry_sum_return_pct=-0.1147211
```

读法：

- 这只是 discovery 初扫，不是 promotion。
- 5m `xs_rev` 出现正 rank-IC，但 post-cost 大幅为负，支持“5m 成本主导/不适配本系统”的判断。
- CARRY 在当前朴素成本口径下为负；这不是最终否定，因为双腿持仓和方向翻转成本模型仍需更真实。
- `1d ts_mom` 暂列第一，但 rank-IC 很弱、有效广度约 1.13；下一步要做更长 discovery 和参数敏感性，不能直接进 S2/S3。
- 顺手修复 `discover_edge_slices` 同分排序的非确定性，WSL 全量测试从偶发失败恢复为稳定通过。

验证：

```text
local unittest=225 OK
WSL unittest=225 OK
WSL live_guard ok=false reason=live_disabled
qount-runner.timer/service inactive
```

### S1' 120 天 / 月度 / 成本敏感性

120 天全频段全族：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T070504Z-strategy-selection-scan-qount-strategy-selection-s1-120d-full-lb12-h1-20260605/qount-strategy-selection-s1-120d-full-lb12-h1-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
best_cell=1d ts_mom
sum_return_pct=-0.3885499348
mean_return_pct=-0.0008027891
sharpe=-0.4637426827
rank_ic_mean=-0.0524746039
effective_breadth=1.0810517903
```

1d 参数敏感性：

```text
lb3/h1 best=xs_rev sum=-0.0652799064 sharpe=-0.6990452037
lb12/h3 best=ts_mom sum=+0.5824374867 sharpe=+0.4579358431
lb24/h1 best=ts_mom sum=-0.0867584111 sharpe=-0.1035899869
```

月度 `1d ts_mom lb12/h1`：

```text
Feb sum=+0.1023244575 sharpe=+0.3227715436
Mar sum=-0.4297008569 sharpe=-2.2922293236
Apr sum=-0.4340789583 sharpe=-2.8870027003
May sum=+0.3233152390 sharpe=+2.3098638880
```

成本压力：

```text
zero_cost_5m_xs_rev_sum=+1.2386542488
zero_cost_carry_sum=+0.0824606
maker_ish_cost_per_directional_bet=0.0004
maker_ish_5m_xs_rev_sum=-26.4101457512
maker_ish_carry_sum=-0.0999394
```

读法：

- 30 天 `1d ts_mom` 正收益主要来自 2026-05，120 天和 3/4 月不支持稳定性。
- 5m `xs_rev` 和 CARRY 有 gross edge，但太薄，maker-ish 成本后转负。
- 当前不能进 S2/S3；下一步是更真实的 CARRY 双腿/阈值模型和扩 universe。

### S1' OHLCV 列回归测试后复跑

变更：

```text
tests/test_strategy_optimization.py
```

新增回归测试锁定 `strategy-selection-scan` 的 OHLCV fetch 输出必须保持 ccxt 标准列：
`[timestamp, open, high, low, close, volume]`。扫描评估层统一把 `row[4]` 当 close，
所以这个测试用于防止 close/low 列错位污染 S1' 读数。

验证：

```text
local unittest=226 OK
WSL unittest=226 OK
```

WSL 复跑 120 天全频段全族：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T071948Z-strategy-selection-scan-qount-strategy-selection-s1-120d-full-lb12-h1-ohlcv-rerun-20260605/qount-strategy-selection-s1-120d-full-lb12-h1-ohlcv-rerun-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
best_cell=1d ts_mom
sum_return_pct=-0.3885499348
mean_return_pct=-0.0008027891
sharpe=-0.4637426827
rank_ic_mean=-0.0524746039
effective_breadth=1.0810517903
decision=no_positive_cell
```

WSL 复跑成本压力：

```text
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T072101Z-strategy-selection-scan-qount-strategy-selection-s1-120d-5m-xsrev-carry-zero-cost-ohlcv-rerun-20260605/qount-strategy-selection-s1-120d-5m-xsrev-carry-zero-cost-ohlcv-rerun-20260605.json
zero_cost_5m_xs_rev_sum=+1.2386542488
zero_cost_carry_sum=+0.0824606

maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T072410Z-strategy-selection-scan-qount-strategy-selection-s1-120d-5m-xsrev-carry-maker-ish-ohlcv-rerun-20260605/qount-strategy-selection-s1-120d-5m-xsrev-carry-maker-ish-ohlcv-rerun-20260605.json
maker_ish_cost_per_directional_bet=0.0004
maker_ish_5m_xs_rev_sum=-26.4101457512
maker_ish_carry_sum=-0.0999394
```

读法：复跑没有改变 S1' 结论。当前没有可 promotion 的 prediction cell；CARRY 有结构性
gross cashflow，但当前朴素“方向翻转即付成本”模型在 maker-ish 成本下为负。下一步仍是
按 `profit-engineering-plan.md §10.5` 做真实 CARRY 双腿/阈值/最短持仓模型，而不是进入
5m GBDT 或 S2/S3。

### S-CARRY threshold_dual_leg 第一版

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式 research-only carry 模型：

```bash
python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families carry \
  --carry-model threshold_dual_leg \
  --carry-entry-threshold-pct 0.00008 \
  --carry-exit-threshold-pct 0.00004 \
  --carry-min-hold-periods 3
```

默认 `carry_model=naive` 不变；新模型只在显式参数下使用。模型计入：

```text
entry threshold / exit threshold
min_hold_periods
dual-leg entry cost = 2 * cost_per_directional_bet
dual-leg exit cost = 2 * cost_per_directional_bet
dual-leg switch cost = 4 * cost_per_directional_bet
idle periods / entry / exit / switch event counts
```

验证：

```text
local unittest=227 OK
WSL unittest=227 OK
```

WSL 120 天 zero-cost：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T073159Z-strategy-selection-scan-qount-strategy-selection-s-carry-threshold-dual-leg-zero-cost-20260605/qount-strategy-selection-s-carry-threshold-dual-leg-zero-cost-20260605.json
carry_model=threshold_dual_leg
entry_threshold=0.00008
exit_threshold=0.00004
min_hold_periods=3
sum_return_pct=+0.04728436
sharpe=+15.3873642125
turnover_events=270
entry_events=119
exit_events=119
switch_events=16
idle_periods=868
```

WSL 120 天 maker-ish：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T073141Z-strategy-selection-scan-qount-strategy-selection-s-carry-threshold-dual-leg-maker-ish-20260605/qount-strategy-selection-s-carry-threshold-dual-leg-maker-ish-20260605.json
cost_per_directional_bet=0.0004
sum_return_pct=-0.16871564
sharpe=-11.8459471734
turnover_events=270
entry_events=119
exit_events=119
switch_events=16
idle_periods=868
decision=no_positive_cell
```

读法：阈值/最短持仓把 naive carry 的 gross cashflow 从 `+0.0824606` 降到
`+0.04728436`，但更接近实际双腿执行；maker-ish 成本后仍为负。不能进入 S-CARRY paper。
下一步是固定 discovery 网格、扩大 universe，并加入 basis / 资金占用读数，而不是为了这
4 币窗口调阈值。

### S-CARRY fixed grid + utilization / basis diagnostics

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式固定 discovery grid 参数：

```bash
python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families carry \
  --carry-model threshold_dual_leg \
  --carry-entry-threshold-grid-pct 0.00004 0.00008 0.00012 \
  --carry-exit-threshold-grid-pct 0.00002 0.00004 \
  --carry-min-hold-grid 1 3 6
```

每个 grid 组合写成独立 carry cell，不自动改配置，不作为 promotion。输出新增：

```text
carry_invested_periods
carry_utilization_ratio
carry_dual_leg_gross_exposure_periods
carry_avg_dual_leg_gross_exposure_pct
basis_sample_count
basis_avg_abs_pct / basis_max_abs_pct
```

验证：

```text
local unittest=228 OK
WSL unittest=228 OK
```

WSL 120 天 fixed grid zero-cost：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T081342Z-strategy-selection-scan-qount-strategy-selection-s-carry-fixed-grid-zero-cost-20260605/qount-strategy-selection-s-carry-fixed-grid-zero-cost-20260605.json
cell_count=18
best_entry_threshold=0.00004
best_exit_threshold=0.00002
best_min_hold_periods=1
sum_return_pct=+0.07147182
sharpe=+24.8646327338
turnover_events=608
utilization=0.6715277778
avg_dual_leg_gross_exposure=1.3430555556
basis_sample_count=0
```

WSL 120 天 fixed grid maker-ish：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T081321Z-strategy-selection-scan-qount-strategy-selection-s-carry-fixed-grid-maker-ish-20260605/qount-strategy-selection-s-carry-fixed-grid-maker-ish-20260605.json
cell_count=18
cost_per_directional_bet=0.0004
best_entry_threshold=0.00012
best_exit_threshold=0.00002
best_min_hold_periods=6
sum_return_pct=-0.02967449
sharpe=-3.9818426324
turnover_events=73
utilization=0.2708333333
avg_dual_leg_gross_exposure=0.5416666667
basis_sample_count=0
decision=no_positive_cell
```

读法：固定 grid 没有找到 maker-ish 成本后仍为正的 CARRY cell。zero-cost best 说明 gross
cashflow 存在；maker-ish best 转负说明 4 币 universe 下成本仍吃掉 edge。Binance
`fetch_funding_rate_history` 当前未给可用 mark/index 历史，所以 basis 诊断字段存在但
`basis_sample_count=0`；basis 风险需要后续接 mark/index 或 premium index 历史数据源。
当前不能进入 S-CARRY paper。

### S-CARRY premium index basis source

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式 basis 数据源：

```bash
python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families carry \
  --carry-model threshold_dual_leg \
  --carry-basis-source premium_index
```

实现：通过 ccxt `fetch_premium_index_ohlcv` 拉 Binance 8h premium index kline，用 close
作为 premium/basis 代理，并按 funding 8h bucket 合并到 funding rows。默认
`carry_basis_source=funding_history` 不变；只有显式 `premium_index` 才多拉该数据源。

验证：

```text
local unittest=229 OK
WSL unittest=229 OK
```

WSL 120 天 fixed grid maker-ish + premium basis：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083154Z-strategy-selection-scan-qount-strategy-selection-s-carry-fixed-grid-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-fixed-grid-premium-basis-maker-ish-20260605.json
premium_index_8h_fetch=361 bars per symbol
cell_count=18
cost_per_directional_bet=0.0004
best_entry_threshold=0.00012
best_exit_threshold=0.00002
best_min_hold_periods=6
sum_return_pct=-0.02967449
turnover_events=73
utilization=0.2708333333
avg_dual_leg_gross_exposure=0.5416666667
basis_sample_count=390
basis_avg_abs_pct=0.0005576725
basis_max_abs_pct=0.00143783
decision=no_positive_cell
```

读法：basis 数据源已接通，之前 `basis_sample_count=0` 的问题已解决。收益结论没有变化：
premium basis 只是风险诊断，不改变 CARRY PnL；4 币 maker-ish 成本后 best cell 仍为负，
不能进入 S-CARRY paper。下一步是扩大 universe 和更真实 spot/perp 双腿资金占用/执行口径。

### S-CARRY top12 universe + premium basis cost control

WSL 120 天 top12 fixed grid maker-ish + premium basis：

```text
symbols=BTC/ETH/ZEC/SOL/HYPE/WLD/XRP/BNB/NEAR/DOGE/ADA/SUI USDT perpetuals
maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083609Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605.json
premium_index_8h_fetch=361 bars per symbol
sample_count=4680
cell_count=18
cost_per_directional_bet=0.0004
best_entry_threshold=0.00012
best_exit_threshold=0.00002
best_min_hold_periods=6
sum_return_pct=-0.07594874
sharpe=-2.9327964782
turnover_events=221
utilization=0.2816239316
avg_dual_leg_gross_exposure=0.5632478632
basis_sample_count=1318
basis_avg_abs_pct=0.0005359447
basis_max_abs_pct=0.00265777
decision=no_positive_cell
best_cell_only_positive_symbol=WLD/USDT:USDT +0.03113714
```

同 universe / grid / premium basis 的 zero-cost control：

```text
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083859Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605/qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605.json
cost_per_directional_bet=0
best_entry_threshold=0.00004
best_exit_threshold=0.00002
best_min_hold_periods=1
sum_return_pct=+0.27826189
sharpe=+20.6366164287
turnover_events=2104
utilization=0.6970085470
avg_dual_leg_gross_exposure=1.3940170940
basis_sample_count=3262
basis_avg_abs_pct=0.0004813930
basis_max_abs_pct=0.00265777
decision=carry_candidate
```

读法：扩到 12 币后，zero-cost gross funding cashflow 从 4 币 fixed grid 的 `+0.07147182`
提升到 `+0.27826189`，S-CARRY 仍值得继续；但这主要来自低阈值、高换手 cell，maker-ish
成本后同一 universe 全部 grid 仍为负。当前瓶颈从“没有 gross cashflow”收敛为“成本 / 双腿执行 /
资金占用 / basis 风险没有可交易证明”。不能进入 S-CARRY paper；下一步做 explicit hedge
history replay 与 post-only 成交率/资金占用模型。

### S-CARRY explicit spot/perp capital model

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式 research-only 参数：

```bash
python -m qount.main strategy-selection-scan \
  --families carry \
  --carry-model threshold_dual_leg \
  --carry-execution-cost-model per_order \
  --carry-capital-model spot_perp_gross \
  --carry-perp-margin-fraction 0.1666667
```

默认仍是旧 `directional_round_trip + perp_notional`，旧 artifact 口径不变。新字段包括
`carry_order_cost_pct`、`carry_capital_per_perp_notional`、
`carry_avg_dual_leg_gross_exposure_on_capital_pct`、`carry_gross_funding_return_pct`、
`carry_execution_cost_sum_pct`、`carry_cost_to_gross_ratio`、
`carry_break_even_order_cost_pct`。

验证：

```text
local unittest=230 OK
WSL unittest=230 OK
```

WSL 120 天 top12 explicit spot/perp gross，per-order cost `0.0002`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605.json
execution_cost_model=per_order
capital_model=spot_perp_gross
perp_margin_fraction=0.1666667
order_cost=0.0002
best_entry_threshold=0.00012
best_exit_threshold=0.00002
best_min_hold_periods=6
sum_return_pct=+0.0106725083
sharpe=+0.7275658326
turnover_events=221
gross_funding_return_pct=+0.0864439347
execution_cost_sum_pct=+0.0757714264
cost_to_gross_ratio=0.8765383794
break_even_order_cost_pct=0.0002281703
positive_cells=3/18
basis_sample_count=1318
basis_max_abs_pct=0.00265777
decision=carry_candidate
```

同口径 cost stress，per-order cost `0.00025`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085742Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605.json
order_cost=0.00025
best_sum_return_pct=-0.0082703483
best_sharpe=-0.5083163356
cost_to_gross_ratio=1.0956729742
break_even_order_cost_pct=0.0002281703
decision=no_positive_cell
```

读法：explicit spot/perp 口径下出现小正候选，但这不是 paper 许可。正收益完全依赖
`order_cost <= 0.00022817`，per-order 成本只增加 5bp 的一半级别就转负；同时 basis tail
`0.00265777` 大于净收益边际。下一步应先做 post-only 成交率和实测订单成本验证，再做
basis tail 压力；不能把 discovery best cell promotion。

### S-CARRY fixed-cell validation_v1 one-day sanity

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

`strategy-selection-scan` 新增显式 `--holdout-role discovery|validation_v1|unknown`，默认
仍为 `discovery`。用于把固定参数 sanity artifact 和 discovery grid artifact 区分开。

验证：

```text
local unittest=230 OK
WSL unittest=230 OK
```

固定参数：top12 explicit spot/perp best cell，entry `0.00012` / exit `0.00002` /
min-hold `6`，不跑 grid search。

WSL 1 天 `validation_v1` sanity，per-order cost `0.0002`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103552Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
holdout_role=validation_v1
sample_count=51
order_cost=0.0002
sum_return_pct=+0.0003597343
sharpe=+2.6637283960
turnover_events=4
gross_funding_return_pct=+0.0017311628
execution_cost_sum_pct=+0.0013714285
cost_to_gross_ratio=0.7922007833
break_even_order_cost_pct=0.0002524613
basis_sample_count=14
basis_max_abs_pct=0.00235832
decision=carry_candidate
```

同窗口 cost stress，per-order cost `0.00025`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103620Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605.json
order_cost=0.00025
sum_return_pct=+0.0000168771
sharpe=+0.1072893774
cost_to_gross_ratio=0.9902509791
break_even_order_cost_pct=0.0002524613
decision=carry_candidate
```

读法：这个新窗口没有立即证伪 CARRY fixed cell，但证据强度不足以 paper。窗口只有 1 天、
51 条 funding 样本、4 个 entry events；`0.00025` 成本下几乎贴着 break-even。basis tail
`0.00235832` 仍明显大于净收益边际。下一步继续做 post-only fill / 实测订单成本 / basis tail，
不是 promotion。

### S-CARRY basis tail diagnostic

变更：

```text
src/qount/strategy_selection.py
tests/test_strategy_optimization.py
```

`strategy-selection-scan` 的 CARRY cell 增加纯诊断字段，不改变
`portfolio_sum_return_pct`：

```text
basis_single_tail_loss_on_capital_pct
basis_single_tail_to_net_ratio
portfolio_sum_after_single_basis_tail_pct
by_symbol.*.sum_after_single_basis_tail_pct
```

验证：

```text
local unittest=230 OK
WSL unittest=230 OK
```

同一个 1 天 `validation_v1` fixed cell 复跑，per-order cost `0.0002`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T104512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
holdout_role=validation_v1
sample_count=51
order_cost=0.0002
portfolio_sum_return_pct=+0.0003597343
portfolio_sharpe=+2.6637283960
turnover_events=4
gross_funding_return_pct=+0.0017311628
execution_cost_sum_pct=+0.0013714285
cost_to_gross_ratio=0.7922007833
break_even_order_cost_pct=0.0002524613
basis_sample_count=14
basis_max_abs_pct=0.00235832
basis_single_tail_loss_on_capital_pct=0.0020214171
basis_single_tail_to_net_ratio=5.6191951202
portfolio_sum_after_single_basis_tail_pct=-0.0016616828
```

有实际持仓的逐币 tail 读数：

```text
ZEC sum=+0.0004934743 tail_ratio=4.0962968110 after_tail=-0.0015279428
SOL sum=+0.0000535886 tail_ratio=13.0929302623 after_tail=-0.0006480428
HYPE sum=-0.0000322629 tail_ratio=29.9391604676 after_tail=-0.0009981857
XRP sum=-0.0001550657 tail_ratio=3.8154883644 after_tail=-0.0007467171
```

读法：basis-tail 诊断没有改变原 PnL，但给出了更严格的风险压力结论。1 天 fixed-cell
`+0.0003597343` 的净收益会被同窗口观察到的一次最大 basis shock 估算压力抹掉并转成
`-0.0016616828`，tail/net 比例约 `5.62x`。这说明当前 S-CARRY 小正候选没有 paper
资格；下一步必须先补 post-only fill / 实测订单成本，以及 basis-tail-aware hedge / exit
模型，不能把 fixed-cell sanity 当 promotion。

### S-CARRY simple basis tail stop

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式 research-only 参数：

```text
--carry-basis-tail-stop-pct
```

默认 `None`，不改变旧扫描。显式设置后，`threshold_dual_leg` 在持仓且
`abs(basis_pct) >= threshold` 时强制退出，计入双腿平仓成本，并输出：

```text
basis_tail_stop_threshold_pct
basis_tail_stop_events
by_symbol.*.basis_tail_stop_events
```

验证：

```text
local strategy-selection tests=9 OK
local unittest=231 OK
sync-to-wsl.sh --install=OK
WSL unittest=231 OK
```

同一个 1 天 `validation_v1` fixed cell，per-order cost `0.0002`，测试三个 stop：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105545Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605.json
stop=0.0010
portfolio_sum_return_pct=-0.0008075743
portfolio_sharpe=-5.7715287233
basis_tail_stop_events=2
carry_execution_cost_sum_pct=0.0023999999
basis_max_abs_pct=0.00081857
basis_single_tail_loss_on_capital_pct=0.0007016314
basis_single_tail_to_net_ratio=0.8688134838
portfolio_sum_after_single_basis_tail_pct=-0.0015092057

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105616Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605.json
stop=0.0015
portfolio_sum_return_pct=-0.0004218600
portfolio_sharpe=-3.5005595112
basis_tail_stop_events=1
carry_execution_cost_sum_pct=0.0020571428
basis_max_abs_pct=0.00112691
basis_single_tail_loss_on_capital_pct=0.0009659228
basis_single_tail_to_net_ratio=2.2896763313
portfolio_sum_after_single_basis_tail_pct=-0.0013877828

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105622Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605.json
stop=0.0020
portfolio_sum_return_pct=-0.0004218600
portfolio_sharpe=-3.5005595112
basis_tail_stop_events=1
carry_execution_cost_sum_pct=0.0020571428
basis_max_abs_pct=0.00112691
basis_single_tail_loss_on_capital_pct=0.0009659228
basis_single_tail_to_net_ratio=2.2896763313
portfolio_sum_after_single_basis_tail_pct=-0.0013877828
```

读法：simple hard stop 能把最大持仓期 basis 从 `0.00235832` 降到 `0.00081857` /
`0.00112691`，但退出成本和少收 funding 直接把组合 PnL 转负。当前 S-CARRY 不能靠单一
basis hard stop 解决，仍不能 paper。下一步应转向 post-only fill / 实测订单成本，或做
更细的 symbol/filter 与 hedge timing，而不是继续在这个 1 天窗口调 stop 阈值。

### S-CARRY cost audit + WLD/SOL filter probe

只读 live 成本审计：

```text
command=execution-cost-audit --limit 200
orders_considered=200
market_orders_analyzed=4
avg_abs_slippage_pct=0.0421792397
p50_abs_slippage_pct=0.0440920717
p90_abs_slippage_pct=0.0544432983
max_abs_slippage_pct=0.0574514535
fee_rate_pct=null
missing_fee_info=4
```

读法：样本太少，且 fee 信息缺失，不能直接作为最终实测成本；但历史 live 市价单 slippage
中位约 `0.044%`，已经高于当前 S-CARRY fixed-cell 的 `0.020%` per-order 假设。

120 天 discovery explicit artifact 的逐币读法：

```text
source=/home/alyaloale/Code/qount/state/research_runs/20260605T085512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605.json
positive_by_symbol=WLD +0.0342318333, SOL +0.0036256113, ZEC +0.0009311400
ZEC_after_single_basis_tail=-0.0005715771
```

按 discovery tail-aware 过滤，只保留 `WLD/SOL`，固定参数复跑：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110031Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
holdout_role=discovery
sample_count=720
portfolio_sum_return_pct=+0.0378574446
portfolio_sharpe=+8.9535171438
turnover_events=51
gross_funding_return_pct=+0.0553431584
execution_cost_sum_pct=+0.0174857138
cost_to_gross_ratio=0.3159507749
break_even_order_cost_pct=0.0006330100
basis_max_abs_pct=0.00265777
portfolio_sum_after_single_basis_tail_pct=+0.0355793561
```

同一 WLD/SOL filter 在已看过的 1 天 sanity 窗口：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110033Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
holdout_role=validation_v1
sample_count=8
portfolio_sum_return_pct=+0.0000535886
portfolio_sharpe=+1.9439023230
turnover_events=1
gross_funding_return_pct=+0.0003964457
execution_cost_sum_pct=+0.0003428571
cost_to_gross_ratio=0.8648274669
break_even_order_cost_pct=0.0002312600
basis_max_abs_pct=0.00081857
portfolio_sum_after_single_basis_tail_pct=-0.0006480428
```

成本压力：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110109Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605.json
order_cost=0.00025
portfolio_sum_return_pct=-0.0000321257
cost_to_gross_ratio=1.0810343337
portfolio_sum_after_single_basis_tail_pct=-0.0007337571

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110114Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605.json
order_cost=0.00045
portfolio_sum_return_pct=-0.0003749828
cost_to_gross_ratio=1.9458618006
portfolio_sum_after_single_basis_tail_pct=-0.0010766143
```

读法：`WLD/SOL` 是当前最像样的 S-CARRY symbol filter，120 天 discovery 的 net / after-tail
都明显好于 top12。但 1 天 sanity 只有 SOL 成交，after-tail 仍为负；per-order cost
提高到 `0.00025` 即转负，而历史 live 市价单 slippage 中位约 `0.00044`。不能 paper。
下一步应先证明 maker/post-only fill 能把实际 per-order cost 压到 `0.000231` 以下，或找
新的独立日期继续验证 WLD/SOL 的稳定性。

### S-CARRY WLD/SOL monthly and early-June read

WLD/SOL 固定参数分月 discovery：

```text
feb_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111620Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-feb-20260605/qount-strategy-selection-s-carry-wld-sol-feb-20260605.json
sum=+0.0040478056
after_tail=+0.0028153799
turnover_events=19

mar_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111622Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-mar-20260605/qount-strategy-selection-s-carry-wld-sol-mar-20260605.json
sum=+0.0028695942
after_tail=+0.0017230457
turnover_events=15

apr_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111625Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-apr-20260605/qount-strategy-selection-s-carry-wld-sol-apr-20260605.json
sum=+0.0190945623
after_tail=+0.0168164738
turnover_events=7

may_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111627Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-may-20260605/qount-strategy-selection-s-carry-wld-sol-may-20260605.json
sum=+0.0119759397
after_tail=+0.0104161540
turnover_events=11
```

6 月已看窗口逐日固定参数复核全部降级 `discovery`，只看稳定性：

```text
jun01_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110450Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-day-jun01-20260605/qount-strategy-selection-s-carry-wld-sol-day-jun01-20260605.json
sum=0.0
turnover_events=0

jun02_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110452Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-day-jun02-20260605/qount-strategy-selection-s-carry-wld-sol-day-jun02-20260605.json
sum=0.0
turnover_events=0

jun03_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110455Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-day-jun03-20260605/qount-strategy-selection-s-carry-wld-sol-day-jun03-20260605.json
sum=-0.0000948771
after_tail=-0.0005669486
turnover_events=1

jun04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110458Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-day-jun04-20260605/qount-strategy-selection-s-carry-wld-sol-day-jun04-20260605.json
sum=+0.0000535886
after_tail=-0.0006480428
turnover_events=1

jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111629Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605.json
sum=+0.0003015686
after_tail=-0.0004000628
turnover_events=1
```

2026-06-05 当前只是 partial day，不作为 validation：

```text
partial_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111654Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605.json
holdout_role=unknown
sample_count=4
sum=-0.0002471743
after_tail=-0.0003076628
turnover_events=2
```

读法：WLD/SOL 在 2-5 月 discovery 月月为正，且 after-tail 也为正，说明它不是单日假象；
但 4/5 月主要靠 WLD，6/1-6/4 已看窗口 after-tail 为负，6/5 partial 也暂时为负。不能
paper。下一步只能等新的完整独立日期复核，或先解决 maker/post-only 成本；不能继续用
6/1-6/5 调阈值后声称 validation。

### S-CARRY post-only economics diagnostic

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增 research-only 诊断参数：

```text
--carry-maker-order-cost-pct
--carry-taker-order-cost-pct
```

这些参数只计算所需 maker fill rate，不改变 `portfolio_sum_return_pct`。输出新增：

```text
carry_post_only_maker_order_cost_pct
carry_post_only_taker_order_cost_pct
carry_post_only_target_order_cost_for_break_even_pct
carry_post_only_target_order_cost_after_single_basis_tail_pct
carry_required_maker_fill_rate_for_break_even
carry_required_maker_fill_rate_after_single_basis_tail
carry_post_only_break_even_feasible
carry_post_only_after_tail_feasible
```

验证：

```text
local strategy-selection tests=10 OK
local unittest=232 OK
sync-to-wsl.sh --install=OK
WSL unittest=232 OK
```

WLD/SOL 固定参数，maker cost `0`，taker cost `0.00045`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T113704Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
holdout_role=discovery
portfolio_sum_return_pct=+0.0378574446
portfolio_sum_after_single_basis_tail_pct=+0.0355793561
turnover_events=51
target_order_cost_for_break_even_pct=0.0006330100
target_order_cost_after_single_basis_tail_pct=0.0006069534
required_maker_fill_for_break_even=0.0
required_maker_fill_after_single_basis_tail=0.0
after_tail_feasible=true

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T113706Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605.json
window=2026-06-01T00:00:00Z..2026-06-05T00:00:00Z
holdout_role=discovery
portfolio_sum_return_pct=+0.0003015686
portfolio_sum_after_single_basis_tail_pct=-0.0004000628
turnover_events=1
target_order_cost_for_break_even_pct=0.0003759150
target_order_cost_after_single_basis_tail_pct=-0.0000333700
required_maker_fill_for_break_even=0.1646333333
required_maker_fill_after_single_basis_tail=1.0741555556
after_tail_feasible=false

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T113709Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605.json
window=2026-06-05T00:00:00Z..2026-06-05T11:00:00Z
holdout_role=unknown
portfolio_sum_return_pct=-0.0002471743
portfolio_sum_after_single_basis_tail_pct=-0.0007569857
turnover_events=2
target_order_cost_after_single_basis_tail_pct=-0.0000207875
required_maker_fill_after_single_basis_tail=1.0461944444
after_tail_feasible=false
```

读法：post-only economics 证明 WLD/SOL 120 天 discovery 并不依赖低成本，甚至 taker
`0.00045` 也可 after-tail 为正；但 6/1-6/5 的 after-tail 亏损不是 maker fill 能解决的，
因为 after-tail 为正需要超过 100% maker fill。下一步不应继续成本调参，应该研究
hedge timing / basis regime filter，或者转向 1d TS-MOM 扩 universe。

## 2026-06-04

### 7907 Binance 专线恢复

现象：

```text
QountBinanceProxy task=Ready
WSL tcp 192.168.128.1:7907=fail
candidate-walk-forward failed at binance fapi exchangeInfo proxy timeout
```

处理：

```powershell
Start-ScheduledTask -TaskName QountBinanceProxy
```

恢复读数：

```text
Windows 7907 listener=verge-mihomo.exe
WSL tcp 192.168.128.1:7907=ok
curl --proxy http://192.168.128.1:7907 https://fapi.binance.com/fapi/v1/time=ok
preflight-live public_api/symbols/credentials/position_mode/balance_guard=ok
live_guard ok=false reason=live_disabled
```

读法：这是基础设施恢复，不是 live 许可；`QOUNT_LIVE_ENABLE=false` 保持不变。

### validation_v1 candidate v1/v2 对比

命令口径：

```text
candidate-walk-forward --research-profile eth-only --holdout-role validation_v1
windows:
  val-jun01=2026-06-01T00:00:00Z,2026-06-02T00:00:00Z
  val-jun02=2026-06-02T00:00:00Z,2026-06-03T00:00:00Z
```

Artifacts：

```text
v1=/home/alyaloale/Code/qount/state/research_runs/20260604T132940Z-candidate-walk-forward-qount-candidate-wf-eth-validation-v1-v1-20260604
v2=/home/alyaloale/Code/qount/state/research_runs/20260604T132941Z-candidate-walk-forward-qount-candidate-wf-eth-validation-v1-v2-20260604
```

读数：

```text
window_count=2
total_cycles=578
total_fresh_entry_selected=25
v1_total_selected_cycles=25
v2_total_selected_cycles=25
v1_strong_favorable=0
v2_strong_favorable=0
```

读法：`v2_interactions` 没有增加 candidate 覆盖，也没有产生更强 setup quality；
不进入端到端验证，不替换主线 v1。

### validation_v1 端到端 walk-forward

命令口径：

```text
walk-forward --research-profile eth-only --holdout-role validation_v1 \
  --setup-model-version v1 --ai-decision-cache
windows:
  val-jun01=2026-06-01T00:00:00Z,2026-06-02T00:00:00Z
  val-jun02=2026-06-02T00:00:00Z,2026-06-03T00:00:00Z
```

Artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260604T134036Z-walk-forward-qount-wf-eth-validation-v1-v1-20260604
```

总读数：

```text
oos_safe_windows=2
positive_realized_windows=0/2
paper_filled=7
paper_closed=8
sum_realized_return_pct=-0.7159862916%
avg_realized_return_pct=-0.3579931458%
windows_with_open_positions=0
total_reviewed=40
total_review_missed_candidate_move=2
windows_with_missed_candidate_move=1
```

分窗：

```text
val-jun01 realized=-0.1510033978% paper_filled=1 paper_closed=1
  review_avg_net_edge=-0.0676188793% missed_candidate_move=0
val-jun02 realized=-0.5649828938% paper_filled=6 paper_closed=7
  review_avg_net_edge=-0.0558199036% missed_candidate_move=2
```

Tag 读法：

```text
eth_trend_impulse_range_noise_range_gt012:
  reviewed=1 bad=1 avg_net_edge=-0.9964830654%
eth_trend_impulse_range_noise_washout:
  reviewed=1 bad=1 avg_net_edge=-0.9964830654%
eth_trend_impulse_short_breakdown_chase:
  reviewed=9 hold_reviewed=9 missed_candidate_move=2
  avg_candidate_aligned_future_return_pct=-0.0240872630%
  avg_candidate_opportunity_edge_pct=+0.1548490521%
```

结论：

- 这次 once-only validation 不满足 `G_paper`，不能 forward paper。
- `range_noise_range_gt012` / `washout` 在新样本中直接变成 bad trade，不能进 gate。
- `short_breakdown_chase` 有 2 个 missed candidate move，但整体 tag/readout 不支持通过
  放宽 short entry 修复；这两个窗口已使用，后续调参不能再把它们当 validation。
- 保持 `ETH-only research-only`、live disabled。

### terminal washout blocker：盈利方向验证

改动：

```text
src/qount/candidate_filter.py
reason=eth_short_range_noise_terminal_washout
hard_bottom_line=true
```

触发条件：

```text
symbol=ETH/USDT:USDT
fresh_entry action=sell
setup_phase=range_noise
higher_timeframe_bias=short
higher_timeframe_phase=trend
return_24bars <= -0.0100
rsi_14 <= 32.0
sma_fast_ratio <= -0.0080
sma_slow_ratio <= -0.0080
volume_ratio_20 >= 1.50
range_pct >= 0.0080
```

本地窄测试：

```text
test_candidate_filter_hard_blocks_eth_range_noise_terminal_washout
targeted range_noise unittest: 9 OK
```

完整验证：

```text
local unittest discover: 221 OK
sync-to-wsl.sh: OK
WSL unittest via run-wsl-tests.sh: 221 OK
```

已失败 validation 窗口降级 discovery 后复测：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T135759Z-walk-forward-qount-wf-eth-terminal-washout-block-discovery-20260604
windows=disc-jun01 2026-06-01T00:00:00Z..2026-06-02T00:00:00Z
        disc-jun02 2026-06-02T00:00:00Z..2026-06-03T00:00:00Z
holdout_role=discovery
positive_realized_windows=1/2
paper_filled=4
paper_closed=5
sum_realized_return_pct=+0.9173089048%
avg_realized_return_pct=+0.4586544524%
windows_with_open_positions=0
total_review_missed_candidate_move=2
disc-jun01 realized=-0.1510033978%
disc-jun02 realized=+1.0683123026%
```

读法：这是有效的 loss-attribution blocker，说明 6/2 的 terminal washout short
不该开；但这两个窗口已在失败 validation 中被看过，只能作为 discovery。

新的 once-only validation 第一次运行：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T141045Z-walk-forward-qount-wf-eth-terminal-washout-block-val-jun03-20260604
window=val-jun03 2026-06-03T00:00:00Z..2026-06-04T00:00:00Z
holdout_role=validation_v1
oos_safe_windows=1
positive_realized_windows=0/1
paper_filled=2
paper_closed=1
sum_realized_return_pct=-0.3858229487%
unrealized_return_pct=+0.8770829226%
total_return_pct=+0.4912599739%
windows_with_open_positions=1
open_positions=1
max_drawdown_pct=2.8234367106%
total_review_missed_candidate_move=0
review_avg_net_edge_pct=-0.0005301342
promotion_blockers=open_position_remaining,non_positive_realized_return,non_positive_review_edge
raw_ai_error_count=227/289
validated_invalid=227
halted=true
```

读法：这份 artifact 的 open position 主要来自 AI auth outage，不是可直接调参的 exit 证据。

AI relay 恢复后做同策略 infra rerun：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T145900Z-walk-forward-qount-wf-eth-terminal-washout-block-val-jun03-infra-rerun-20260604
window=val-jun03 2026-06-03T00:00:00Z..2026-06-04T00:00:00Z
holdout_role=validation_v1
oos_safe_windows=1
positive_realized_windows=0/1
paper_filled=6
paper_closed=6
sum_realized_return_pct=-1.1912362466%
windows_with_open_positions=0
max_drawdown_pct=1.5370303348%
total_reviewed=26
total_review_missed_candidate_move=1
review_avg_net_edge_pct=-0.0383055167%
raw_ai_error_count=0/289
validated_invalid=0
promotion_blockers=non_positive_realized_return,non_positive_review_edge
```

Order attribution:

```text
entry_runs=20,43,206,234,241,250
closed_trades=6
wins=1
losses=5
run43 pnl=+0.3846991822 quote
run241 pnl=-0.9643193956 quote
run250 pnl=-0.1322188764 quote
```

Terminal-washout miss read:

```text
run241 return_24bars=-0.01710 rsi_14=15.17 sma_fast=-0.00973 sma_slow=-0.01457 volume_ratio_20=2.27 range_pct=0.00595
run250 return_24bars=-0.02331 rsi_14=28.59 sma_fast=-0.00771 sma_slow=-0.01788 volume_ratio_20=2.70 range_pct=0.00727
current blocker misses because range_pct>=0.008 and sma_fast<=-0.008 are too narrow
```

结论：方向上比原 baseline 好，但仍没有通过 `G_paper`。真实下一步是研究 repeated
`range_noise` short、loss reentry cooldown 和 terminal-washout 阈值；不要放宽
`range_noise` / `short_rebound_fail` 来追成交。2026-06-03..2026-06-04 已看过，后续调参后
不能再用它宣称 promotion。

## 2026-05-31

### Holdout / promotion 前置修复

新增：

```text
docs/holdout.md
```

当前规则：

- `wf-feb27` 到 `wf-may30-postlatest` 的已看过窗口全部是 `discovery_pool`。
- `validation_pool_v1` 从 2026-06-01T00:00:00Z 后的新数据开始。
- 任何在 `validation_v1` 上调参的窗口都会降级回 `discovery`。
- promotion 不再用旧 G1/G2；改用 `G_paper` / `G_live`。

### 实验工具前置修复

新增/修改：

```text
backtest --holdout-role discovery|validation_v1|unknown --ai-decision-cache
walk-forward --holdout-role discovery|validation_v1|unknown --ai-decision-cache
setup-edge-walk-forward
candidate-walk-forward
research-slice-scan offline_future_edge_readiness
scripts/sync-to-wsl.sh
scripts/run-wsl-tests.sh
```

边界：

- AI cache 只在历史 `backtest` / `walk-forward` 显式开启时使用。
- cache key 包含 snapshot、system prompt、decision prompt、model、temperature。
- `run-once` / live 不使用缓存。
- `setup-edge-walk-forward` 与 `candidate-walk-forward` 都不调用 AI、不执行订单。

验证：

```text
local unittest: 220 OK
sync-to-wsl.sh --install: OK
WSL unittest via run-wsl-tests.sh: 220 OK
```

### T-B AI hold-bias 工具化

新增：

```text
ai-hold-baseline
src/qount/ai_hold_baseline.py
```

能力：

- 从 backtest / walk-forward artifact 的 `qount.db` 还原 selected fresh-entry prompt 样本。
- 支持 profile / symbol / target tag / run_id 过滤。
- 支持 `v1`、`v2_remove_default_wait`、`v3_veto_only` prompt 研究变体。
- 默认结果写入 `state/research_runs`；diagnostic only，不是 promotion 证据。

WSL 读数：

```text
multi_symbol_dry_run=/home/alyaloale/Code/qount/state/research_runs/20260531T064411Z-ai-hold-baseline-qount-ai-hold-multi-fast-sma-dryrun-20260531/qount-ai-hold-multi-fast-sma-dryrun-20260531.json
sample_count=24
stored_hold=24/24
windows=ws4 step3 mar03 20 + apr20 4

eth_only_symbol_filter=/home/alyaloale/Code/qount/state/research_runs/20260531T064410Z-ai-hold-baseline-qount-ai-hold-ethonly-symbol-filter-20260531/qount-ai-hold-ethonly-symbol-filter-20260531.json
sample_count=2
symbols_filter=ETH/USDT

eth_only_v3_smoke=/home/alyaloale/Code/qount/state/research_runs/20260531T064502Z-ai-hold-baseline-qount-ai-hold-ethonly-v3-smoke-20260531/qount-ai-hold-ethonly-v3-smoke-20260531.json
sample_count=2
request_count=2
replayed_hold=2/2
```

读法：WS-4 fast-SMA step3 的 24 条目标样本确实是 AI 层全 hold；但 `v3_veto_only`
在 ETH-only 小样本 smoke 里仍 hold，且理由是具体 veto（负 expected_edge、SMA/24bar
冲突、rebound 或过热），所以不能把 prompt v3 直接推进到 gate。

### T-G 0 交易窗口诊断

新增/修改：

```text
idle-window-diagnostic
src/qount/idle_window_diagnostic.py
```

能力：

- 扫描既有 backtest / walk-forward artifact 的 `qount.db` / `summary.json`。
- 默认跳过有 paper fill/close 的窗口，只看 0 交易窗口。
- 输出 setup model label/quality、setup phase、candidate blocker、traditional pattern、
  AI hold reason 和 top candidate h6 future edge。
- 只读诊断，不调用 AI、不执行订单、不改 candidate / risk / live。
- 修正 reason aggregate：窗口展示受 `--reason-limit` 限制，aggregate 使用未截断计数。

WSL 读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T072108Z-idle-window-diagnostic-qount-idle-window-diagnostic-ethonly-20260531-v2/qount-idle-window-diagnostic-ethonly-20260531-v2.json
backtest_count=39
window_count=36
idle_window_count=36
skipped_traded_window_count=3
candidate_filter_hold_count=2878
ai_hold_count=87
selected_or_candidate_like_scored_count=890
positive_top_candidate_avg_future_edge_windows=5/36
positive_top_candidate_avg_future_edge_rate=0.1388888888888889
```

setup model quality：

```text
missing=2867
unfavorable=72
weak_favorable=12
neutral=4
strong_favorable=0
```

主要 candidate blocker：

```text
eth_short_research_blocks_fresh_outside_short_trend_family_open=1598
eth_short_range_noise_requires_breakdown_structure=1191
low_volatility=874
low_volume=609
low_volatility_soft_penalty=605
short_setup_countertrend_drift=441
low_volume_soft_penalty=405
```

验证：

```text
local unittest: 220 OK
sync-to-wsl.sh --install: OK
WSL unittest via run-wsl-tests.sh: 220 OK
```

读法：0 交易窗口主要是 research/candidate/market-quality 层主动拦截，setup_model
没有在这些窗口里给出大量 strong favorable 候选；5/36 正 top-candidate-edge 窗口仍是
已看过 discovery 样本，不能作为 promotion 或新 gate 证据。

### T-C setup_model v2 interaction 对比

新增/修改：

```text
setup_model v2_interactions
setup-model-compare
walk-forward / setup-edge-walk-forward / candidate-walk-forward --setup-model-version
```

能力：

- v1 默认不变。
- v2 在 v1 16 维特征上增加 higher-timeframe phase × bin 交互。
- `setup-model-compare` 用 chronological train/eval split 离线对比 v1/v2。
- 只拉历史 K 线并训练/评分，不调用 AI、不执行订单、不改变 candidate / risk / live。

WSL 默认相位读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T075127Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-20260531/qount-setup-model-compare-ethonly-v2-20260531.json
example_count=705
eval_example_count=212
v1_top_decile_avg_target_edge_pct=-0.0011523934
v2_top_decile_avg_target_edge_pct=-0.0013773666
v2_minus_v1_top_decile=-0.0002249732
v2_minus_v1_mae=+0.0000124423
```

WSL range-noise-inclusive 读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T075351Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-range-20260531/qount-setup-model-compare-ethonly-v2-range-20260531.json
example_count=19681
eval_example_count=5905
v1_top_decile_avg_target_edge_pct=-0.0015544902
v2_top_decile_avg_target_edge_pct=-0.0013618186
v2_minus_v1_top_decile=+0.0001926716
v2_minus_v1_mae=+0.0000053851
v2_directional_accuracy=0.7334010840
v1_directional_accuracy=0.7347560976
v2_strong_favorable=0
```

验证：

```text
local unittest: 220 OK
sync-to-wsl.sh --install: OK
WSL unittest via run-wsl-tests.sh: 220 OK
```

读法：第一版 v2 interaction plumbing 可用，但读数不支持推进。包含 `range_noise` 后
top decile 相对 v1 略好，但绝对 future edge 仍为负，MAE 和 directional accuracy 略差，
且 `strong_favorable=0`。不能替换主线 setup model，不能写 gate。

## 2026-05-30

### 继续 OOS / root scan

```text
may30_latest_rescan=/home/alyaloale/Code/qount/state/research_runs/20260530T162100Z-research-slice-scan-qount-rescan-may30-latest-current-tags/qount-rescan-may30-latest-current-tags-.json
may30_postlatest_wf=/home/alyaloale/Code/qount/state/research_runs/20260530T162254Z-walk-forward-qount-wf-eth-may30-postlatest-20260530T1625Z
may30_postlatest_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T162349Z-research-slice-scan-qount-rescan-may30-postlatest-current-tags-20260530T1625Z/qount-rescan-may30-postlatest-current-tags-20260530T1625Z.json
root_rescan=/home/alyaloale/Code/qount/state/research_runs/20260530T162449Z-research-slice-scan-qount-root-rescan-through-may30-postlatest-20260530T1627Z/qount-root-rescan-through-may30-postlatest-20260530T1627Z.json
```

结果：

```text
wf-may30-postlatest:
  window=2026-05-30T05:40:00Z..2026-05-30T16:15:00Z
  paper_filled=0
  realized_return_pct=0.0
  open_positions=0

may30_postlatest_scan:
  ready_tags=[]
  eth_reclaim_long_failed_breakdown_base snapshot_count=2
  h3/h6/h12/h24 avg=+0.0003093/+0.0005721/+0.0002104/-0.0008515

root_rescan:
  backtest_count=39
  ready_tags=[]
  top near miss=eth_range_action_pullback_sma_slow_gt008
```

读法：补样本后仍没有可写 gate 的候选。`eth_range_action_pullback_sma_slow_gt008`
和 `*_sma_fast_gt008` 是 near miss，但 h12/h24 覆盖不足、AI/risk 覆盖只有 2 条；
只能继续观察，不能进 targeted shadow proof / gate。

### WS-4 step 3 隔离 shadow proof

新增研究专用入口：

```text
backtest / walk-forward:
  --research-shadow-candidate-tags <tag...>
```

边界：

- 只用于隔离 backtest / walk-forward 的 targeted shadow proof。
- 默认不生效；live 模式忽略。
- 匹配 tag 的 fresh-entry 会进入 AI/risk，不匹配的 fresh-entry 被排除。
- 不改变 production candidate gate，不开 paper / live。

已验证：

```text
local unittest: 210 OK
WSL unittest: 210 OK
```

`multi_range_action_pullback_sma_fast_gt008` 两个独立窗口结果：

```text
mar03_backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T134311Z-backtest-qount-ws4-step3-shadow-fast-sma-mar03-20260530T133841Z
mar03_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T143151Z-research-slice-scan-qount-ws4-step3-shadow-fast-sma-mar03-scan-20260530T143150Z/qount-ws4-step3-shadow-fast-sma-mar03-scan-20260530T143150Z.json
target_snapshot_count=60
target_ai_decision_count=20
target_risk_final_count=20
AI actions: hold=20
paper_filled=0
realized_return_pct=0.0

apr20_backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T143701Z-backtest-qount-ws4-step3-shadow-fast-sma-apr20-20260530T143555Z
apr20_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T143740Z-research-slice-scan-qount-ws4-step3-shadow-fast-sma-apr20-scan-20260530T143739Z/qount-ws4-step3-shadow-fast-sma-apr20-scan-20260530T143739Z.json
target_snapshot_count=8
target_ai_decision_count=4
target_risk_final_count=4
AI actions: hold=4
paper_filled=0
realized_return_pct=0.0
```

读法：该 tag 虽然在 h3/h6/h12 离线 readiness 上达标，但进入完整 AI/risk 链路后
没有 realized-return 转化；失败点是 AI 全 hold，不是 risk 拦截。不能进入
candidate gate，也不能在这两个窗口上事后调 prompt / 阈值。

### WS-4 剩余候选 step 2 复扫

`multi_range_action_range_return24_gt012`：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T152130Z-research-slice-scan-qount-ws4-step2-range-return24-collection-20260530T152130Z/qount-ws4-step2-range-return24-collection-20260530T152130Z.json
snapshot_count=6
ai_decision_count=6
risk_final_count=6
ready_tags=[]
h3 avg=-0.0005002
h6 avg=+0.0000067
h12 avg=-0.0035458
```

`eth_reclaim_long_failed_breakdown_*`：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T152226Z-research-slice-scan-qount-ws4-step2-eth-reclaim-long-collection-20260530T152225Z/qount-ws4-step2-eth-reclaim-long-collection-20260530T152225Z.json
eth_reclaim_long_failed_breakdown_base snapshot_count=15
eth_reclaim_long_failed_breakdown_sma_slow_gt004 snapshot_count=6
ready_tags=[]
base h3/h6/h12/h24 avg=-0.0007453/-0.0009093/-0.0044665/-0.0131250
sma_slow_gt004 h3/h6/h12/h24 avg=-0.0021505/-0.0032977/-0.0040575/-0.0118253
```

读法：WS-4 当前三条候选都不能写 gate；继续需要新的 frozen hypothesis、
新的样本外窗口，或回到 WS-2 min-edge 敏感性扫描。

### WS-2 min-edge 敏感性复核

尝试跑完整 13-window 四档扫描：

```text
QOUNT_MIN_EXPECTED_EDGE_PCT=0.0015/0.0025/0.0035/0.0045
```

但 WSL 实测完整扫描几分钟只完成 `wf-feb27` 一个 0 交易窗口；随后改跑
`wf-mar06 + wf-apr15` 两条有成交窗口，也仍在第一档耗时过高。两个 run 已中止，
partial artifact 不作为策略证据。

用既有 13-window baseline 的真实开仓 `risk_debug.expected_edge_components`
做离线判读：

```text
baseline=/home/alyaloale/Code/qount/state/research_runs/20260529T154450Z-walk-forward-qount-wf-eth-through-may29-afterpm-gpt55-20260529T1524Z
wf-mar06 run 76  final_expected_edge_pct=0.0027489
wf-mar06 run 104 final_expected_edge_pct=0.0039349
wf-mar06 run 130 final_expected_edge_pct=0.0032814
wf-apr15 run 76  final_expected_edge_pct=0.0019836
```

阈值影响：

```text
0.0015 keeps 4/4 opens
0.0025 keeps 3/4 opens, blocks wf-apr15
0.0035 keeps 1/4 opens
0.0045 keeps 0/4 opens
```

读法：收紧 min-edge 会砍掉已知正收益开仓，不会修复 0 交易窗口，也会让
G2/G7 更差；当前不支持提高 `QOUNT_MIN_EXPECTED_EDGE_PCT`。

### 模型路由修复

- WSL `.env` 从 `QOUNT_AI_MODEL=gpt-5.4` 修为 `QOUNT_AI_MODEL=gpt-5.5`。
- 原因：当前 relay `/v1/models` 不再列出 `gpt-5.4`，导致 AI 请求 502 / 全 hold。
- 备份：`.env.bak-ai-model-20260530T0520Z`。

### 盈利复核

Artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260529T154450Z-walk-forward-qount-wf-eth-through-may29-afterpm-gpt55-20260529T1524Z
```

结果：

```text
window_count=13
oos_safe_windows=13
positive_realized_windows=2
total_paper_filled=4
total_paper_closed=5
total_review_missed_candidate_move=0
sum_realized_return_pct=+1.6184470183
```

读法：

- `wf-mar06` 和 `wf-apr15` 贡献全部正收益。
- 5/29 新增窗口全部 0 交易。
- 不能把 `2/13` 正窗口解释成可上线盈利能力。

### multi-range-action target-slice

新增只读 target-slice set：

```text
setup-edge-study --target-slice-set multi-range-action
```

涉及文件：

```text
src/qount/setup_model.py
tests/test_strategy_optimization.py
docs/current.md
docs/quick-handoff.md
```

验证：

```text
local unittest: 202 OK
WSL unittest: 202 OK
```

关键结果：

| slice | h6 | h12 | h24 | 读法 |
| --- | ---: | ---: | ---: | --- |
| broad `sell+range_noise+pullback/range` | `-0.0009799` | `-0.0007499` | `-0.0003740` | broad 仍负 |
| `pullback+sma_fast>0.008` | `+0.0030693` | `+0.0054217` | `+0.0028383` | h6/h12 强，h24 有负折 |
| `range+return24>0.012` | `+0.0015924` | `+0.0024851` | `+0.0033432` | h6 稳，长 horizon 不稳 |
| `pullback+rsi>75` | `+0.0000734` | `+0.0005458` | `+0.0019411` | 只支持 h24 观察 |

读法：多币 discovery 发现了更强的离线 alpha 线索，但还没有经过完整
candidate -> AI -> risk -> execution 的 walk-forward realized-return 转化。
下一步只能做 targeted shadow proof，不能直接加 gate。

### WS-1 trailing CLI 覆盖

- `backtest` / `walk-forward` 新增 `--trailing-arm-pct`、
  `--trailing-retrace-pct`。
- 覆盖发生在 `apply_research_profile()` 之后，解决 `eth-only` profile 静默盖掉
  `QOUNT_TRAILING_*` env 的问题。
- `audit_context` 记录最终生效的 trailing 参数，h12 持仓 horizon 对照必须先核对这里。

读法：这是研究入口修正，不改变 candidate eligibility，不开 forward paper / live。

### Profit plan WS-1/2/3 first pass

WS-1 持仓 horizon 粗筛：

```text
probe=/home/alyaloale/Code/qount/state/research_runs/20260530T100317Z-walk-forward-qount-ws1-h12-trailing-mar06-20260530T095148Z
window=wf-mar06
horizon_bars=12
trailing_profit_arm_pct=0.003
trailing_profit_retrace_pct=0.005
QOUNT_MIN_HOLD_BARS=4
realized_return_pct=+0.5828756239
unrealized_return_pct=+1.0361625344
total_return_pct=+1.6190381583
open_positions=1
promotion_blockers=open_position_remaining
```

对照既有 h6 基线：

```text
baseline=/home/alyaloale/Code/qount/state/research_runs/20260529T154450Z-walk-forward-qount-wf-eth-through-may29-afterpm-gpt55-20260529T1524Z
window=wf-mar06
realized_return_pct=+1.5617328164
unrealized_return_pct=0.0
open_positions=0
```

读法：h12 + loose trailing 没有改善 realized return，而且留下未平仓，不能扩大到完整
13 窗。一次 2-window 全量探针曾启动但因运行时间/AI 调用成本超出粗筛预期而中止；
该中止 run 没有完整 `walk_forward.json`，不作为策略证据。

WS-2 成本敏感性：

```text
current_cost=/home/alyaloale/Code/qount/state/research_runs/20260530T100928Z-setup-edge-study-qount-ws2-eth-range-action-h6-current-20260530T100855Z/qount-ws2-eth-range-action-h6-current-20260530T100855Z.json
maker_fee=/home/alyaloale/Code/qount/state/research_runs/20260530T101000Z-setup-edge-study-qount-ws2-eth-range-action-h6-makerfee-20260530T100855Z/qount-ws2-eth-range-action-h6-makerfee-20260530T100855Z.json
```

| slice | current h6 avg | maker-fee h6 avg | 读法 |
| --- | ---: | ---: | --- |
| broad `sell_range_noise_pullback_or_range` | `-0.0010096` | `-0.0006096` | 仍为负 |
| `pullback_sma_slow_gt008` | `+0.0011208` | `+0.0015208` | 子切片更强，但仍只是离线 edge |
| `range_return24_gt012` | `+0.0014270` | `+0.0018270` | 子切片更强，但 min-fold 仍有负 |

读法：maker 费用假设会改善边际，但不足以把 broad gate 变成正期望；不能据此改执行器。

WS-3 集合根扫描：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T093824Z-research-slice-scan-qount-ws3-existing-root-scan-ethonly-20260530T093824Z/qount-ws3-existing-root-scan-ethonly-20260530T093824Z.json
source_mode=backtest_collection
backtest_count=33
cost_model=contract true, fee 0.0004, slippage 0.0002
shadow_candidate_readiness.status=no_ready_tags
ready_tags=[]
```

关键覆盖：

```text
eth_reclaim_long_failed_breakdown_base=15
eth_reclaim_long_failed_breakdown_sma_slow_gt004=6
eth_range_action_pullback_sma_slow_002_004=10
eth_range_action_pullback_sma_slow_gt008=0
eth_range_action_range_return24_gt012=6
eth_trend_impulse_short_breakdown_chase_terminal_volume_gt3=6
```

读法：既有 artifact 集合仍没有任何 tag 达到 targeted shadow proof readiness。
WS-4 不能进入候选层 / gate，只能先继续补表达或受控补样本。

### WS-4 step 0 research-tag 表达

新增只读 research tags：

```text
multi_range_action_pullback_sma_fast_gt008
multi_range_action_range_return24_gt012
eth_range_action_pullback_sma_fast_gt008
```

涉及文件：

```text
src/qount/entry_quality.py
src/qount/research_slice_scan.py
tests/test_strategy_optimization.py
```

这只改变 `candidate_context.research_slice_tags` / `research-slice-scan` 的观测层，
不改变 candidate eligibility、AI、risk、paper 或 live。

先扫既有集合根：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T112331Z-research-slice-scan-qount-ws4-step0-fast-sma-scan-20260530T112329Z/qount-ws4-step0-fast-sma-scan-20260530T112329Z.json
backtest_count=34
multi_range_action_pullback_sma_fast_gt008=0
eth_range_action_pullback_sma_fast_gt008=0
shadow_candidate_readiness.status=no_ready_tags
```

随后用离线样本定位到 90 天内 `sell + pullback + sma_fast>0.008` 有 37 个样本，
集中在 `2026-03-03`、`2026-03-31`、`2026-04-20` 等窗口。基于这个定位跑了一个
2 小时 multi-symbol 决策流覆盖探针：

```text
backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T113548Z-backtest-qount-ws4-step0-multi-fast-sma-backtest-20260530T113007Z
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T113548Z-research-slice-scan-qount-ws4-step0-multi-fast-sma-backtest-scan-20260530T113007Z/qount-ws4-step0-multi-fast-sma-backtest-scan-20260530T113007Z.json
runs_completed=41
paper_filled=0
paper_closed=0
realized_return_pct=0.0
open_positions=0
multi_range_action_pullback_sma_fast_gt008=21
h6 avg_target_edge_pct=+0.0039374
h12 avg_target_edge_pct=+0.0087454
shadow_candidate_readiness.status=no_ready_tags
```

读法：WS-4 step 0 已证明这条 multi fast-SMA 线索能被观测层表达，并能在真实
snapshot 流里出现；但它还没有成交、没有 targeted shadow proof readiness，不能写 gate。
下一步只能继续补第二个独立窗口的覆盖，或先设计真正的隔离 shadow execution harness。

第二个独立窗口覆盖探针：

```text
backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T132420Z-backtest-qount-ws4-step0-multi-fast-sma-apr20-20260530T132009Z
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T132420Z-research-slice-scan-qount-ws4-step0-multi-fast-sma-apr20-scan-20260530T132009Z/qount-ws4-step0-multi-fast-sma-apr20-scan-20260530T132009Z.json
window=2026-04-20T07:00:00+00:00..2026-04-20T08:00:00+00:00
runs_completed=23
paper_filled=0
paper_closed=0
realized_return_pct=0.0
open_positions=0
multi_range_action_pullback_sma_fast_gt008=8
h3 avg_target_edge_pct=+0.0035351
h6 avg_target_edge_pct=+0.0071846
h12 avg_target_edge_pct=+0.0093046
h24 sample_count=0
```

把 `2026-03-03` 和 `2026-04-20` 两个独立窗口合并后，只按 h3/h6/h12 做
readiness：

```text
combined_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T132422Z-research-slice-scan-qount-ws4-step0-fast-sma-combined-h3h6h12-20260530T132009Z/qount-ws4-step0-fast-sma-combined-h3h6h12-20260530T132009Z.json
backtest_count=36
ready_tags=["multi_range_action_pullback_sma_fast_gt008"]
sample_count=29
h3 avg=+0.0011956 positive_edge_rate=0.5517 positive_windows=2
h6 avg=+0.0048332 positive_edge_rate=0.7931 positive_windows=2
h12 avg=+0.0088997 positive_edge_rate=0.7931 positive_windows=2
```

读法：这已经满足 h3/h6/h12 的 targeted shadow proof readiness，但没有 h24 覆盖，
也没有任何真实成交。下一步可以做 WS-4 step 3：搭建或临时实现隔离 shadow execution
harness，专门统计这个 tag 如果被执行的 realized return；仍不能直接进 candidate gate。

## 2026-05-29

### OOS 和 readiness 扩展

- 追加 `wf-may29-latest`、`wf-may29-next`、`wf-may29-pm`、`wf-may29-afterpm`。
- 这些新增窗口都是 0 交易 / 0 realized return。
- `research-slice-scan` 增加：
  - `shadow_candidate_readiness`
  - `blocked_tags_ranked`
  - collection root 扫描 `state/research_runs`

关键结论：

```text
shadow_candidate_readiness.status=no_ready_tags
ready_tags=[]
```

读法：没有达到 targeted shadow proof 的最低覆盖门槛，不新增 entry gate。

## 2026-05-28

### research artifact 持久化

新增统一研究 artifact 持久化：

```text
src/qount/artifacts.py
```

效果：

- `setup-edge-study` 默认写入 `state/research_runs/...`。
- `research-slice-scan` 默认写入 `state/research_runs/...`。
- 外部目录 `backtest` / `walk-forward` 完成后会镜像到 `state/research_runs/...`。

读法：研究证据不再只依赖 `/tmp`，后续引用优先用 persistent artifact path。

### May28 OOS 和 Kronos

- May28 OOS 继续没有给出可晋级 gate。
- `terminal_volume_gt3` 被 h3/h6/h12/h24 负边际否定。
- Kronos 只保留为离线 overlay 候选，不能接入 candidate / risk / live。

## 2026-05-27

### ETH range-action discovery

- `setup-edge-study` 增加 action-aware discovery 和 `eth-range-action` target-slice。
- `research-slice-scan` 增加 h3/h6/h12/h24 future-edge overlay。
- broad `ETH sell + range_noise + pullback/range` 多次复核仍为负。

读法：不能为了提高交易频率放宽 broad `range_noise`。

### 交易链路修正

接受的窄修正：

- deterministic research profile：`eth-only` 固定 `ai_temperature=0.0`。
- `deterministic_eth_reclaim_support_breakdown_override`：只在 research shape 下把已证明 candidate 的 AI `hold` 改为 `sell`。
- `setup_model_weak_trend_shallow_short_rebound_fail`：挡住 May26 暴露的小亏 shallow trend short。

读法：这些是局部修复，不是新增宽 gate。

## 2026-05-26

### 风控和 blocker 修复

- trailing peak 首次达到 arm 后立即落库，避免 tight retrace 失效。
- `setup_model_neutral_reclaim_short_rebound_fail` 挡住 `wf-mar11 run 97` 旧亏损入口。

验证读法：

- 修复能改善已知亏损样本或管理逻辑。
- 仍没有把整体策略推到可上线盈利状态。

## 当前下一步

1. 保持publisher与Daily Intelligence timer为`enabled/active`，MiniTrend live timer为`enabled/active`，forward timer、legacy live
   switch与production cron继续关闭；publisher只刷新系统健康、release、备份和Dashboard，不查询交易所。
2. 等待自然非零信号，不为采集fill/fee/STOP样本强制下单。每个live周期仍必须重新通过私有preflight、funding完整、无未管理仓位/挂单、
   authority、RuntimeLedger、三方对账和UNKNOWN/HALT门；readiness观察项不因缺少日历样本而人为填充。
3. 真实首单必须同时取得exchange order、逐笔trade/fee、保护单ACK、post-dispatch NAV/账本/三方对账和Dashboard authority；任一证据缺失
   进入`UNKNOWN + HALT`，不得重发或继续后续订单。当前Base仍固定`100 USDT`，RiskTier/FundingVeto和其它sleeve不获得订单权。
4. 当前唯一open alert是日报证据不足的`WARNING`，不是execution故障；继续补正文、事件窗、历史行情和逐笔账本证据，不能由标题或单点行情
   推导公告因果、策略Alpha或盈利结论。
