# qount 当前状态

更新时间：2026-07-22

源码版本：`0.2.10`（独立freshness最终修复发布候选）

VPS生产版本：`0.2.9`（release `41cd42f...ef99c5`，升级维护中，live timer已停）

这份文档是当前事实入口，只保留结论、能力边界和下一步。接手命令看
[quick-handoff.md](quick-handoff.md)，项目规则和文档分类看
[project-rules.md](project-rules.md)，发现/验证边界看
[holdout.md](holdout.md)，长证据链看 [update-log.md](update-log.md)。当前系统工程主设计看
[system-architecture-design.md](system-architecture-design.md)，100 USDT Base与未来组合合同看
[crypto-portfolio-system-plan.md](crypto-portfolio-system-plan.md)，Alpha Agents研究层看
[alpha-agent-plan.md](alpha-agent-plan.md)。旧研究线、历史计划和legacy运行手册统一从
[archive/README.md](archive/README.md)进入，不再混入当前生产导航。

- **2026-07-22 0.2.10独立freshness最终修复待验收，VPS继续保持停盘维护。** `0.2.9`已部署，publisher与
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
  新的[系统架构设计](system-architecture-design.md)固定模块化单体、标准trace IDs、SQLite WAL运行账本+
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
  矩阵smoke均已通过。迁移结果、目录合同和删除门见[storage-topology.md](storage-topology.md)。A10产物已
  回收并可释放，后续默认使用本地4060；WSL代码只在计算接口或依赖变化时按需更新。

## 当前结论

```text
ETH-only research-only
bottom_line + future + ETH/USDT + 1 position
hourly model off
setup model phase6 on
legacy line A live disabled; crypto X4/C×D production on VPS
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
2026-07-18 future-only dual-state shadow monitoring v0.2 was preregistered before any eligible result: Stop-Latch and Funding Veto both start from 400 USDT cash on 2026-07-19 after 200 signal-only warmup bars, with separate equity/state hashes and an append chain. Only the contiguous prefix with complete prices and at least three TOP3 funding settlements per decision/holding day may be evaluated; missing funding is never zero-filled. The WSL/external refresh advanced the common UM cache through 2026-07-17, but that is still before the frozen start, so evaluation bars remain 0 and verdict is await_shadow_forward_data. Current-month public funding REST is unreachable directly from WSL (0/3 symbols); no zero fill or Sophie home proxy was used.
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
2026-07-19 formal trial 144 tested a distinct long-only Capitulation Rebound event sleeve after preregistration: Base gate off, all TOP3 negative, median 5-day return <=-8%, volatility score <=-1.5, next-open entry, three-day hold, 3xATR stop and 24bps round trip. On 2021-01-01..2026-07-17 consumed UM daily history it produced 18 independent episodes, 44.44% winners, median net event return -1.8747%, compound price+cost return -36.4990%, maxDD 39.5163% and median BTC-beta residual -0.5374%. Five of seven gates failed; verdict reject_historical_capitulation_rebound. No threshold/holding rescue, funding replay, shadow, paper or live. Total formal strategy trial count is now 144.
```

- **2026-06-06 项目级决策(所有者确认):执行 §7 诚实止盈,停止追盈利。** 根因是架构级广度
  天花板——加密 majors r̄≈0.63,横截面有效广度仅 ~1.5、渐近天花板 `1/r̄≈1.6`(扩币救不了),
  §10.2 破局所需 IC 实际 ≈0.15、观测最强仅 0.05;横截面(XS-MOM/REV/funding)广度封死、
  日频 TS-MOM 已证伪、CARRY 已证伪——latency-insensitive 可触及路径穷尽,满足 §7 全局终止
  条件。**固化研究价值**(triple-barrier / purged-CV / DSR / PBO / effective-breadth 整套
  反过拟合 harness)作为成果,停止在择时盈利上继续投入。**这是停止投入,不放宽任何纪律**:
  live 仍关闭、不 forward paper、不放宽 broad gate、`validation_v1` once-only 资格继续保留。
  对账见 [profit-engineering-plan.md](profit-engineering-plan.md) §11.8。
- **2026-07-07 owner 决策:所有实盘部署到 VPS。** 当前 live / paper forward /
  dashboard 的生产真相是 `qount-vps:/root/qount`（仓库外SSH inventory），站点
  `qount.alyaloale.com`。Mac 工作区 `/Users/alyaloale/Code/qount` 只作为编辑和 git
  表面；部署通过 `scripts/sync-to-vps.sh` / `scripts/run-vps-tests.sh`。
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
- VPS只读审计确认旧生产cron自`2026-07-11`仍停用、无qount交易进程；旧C×D状态残留shorting/2x，绝不能
  恢复旧cron。`2026-07-19`在清空全部代理变量且设置`QOUNT_EXCHANGE_BYPASS_PROXY=true`后复核：直接出口
  仓库外production egress的地理结果是PH，Binance UM公共API正常，因此不是美国代理问题。旧credential曾由
  `apiRestrictions`返回`-2008 Invalid Api-Key ID`、spot/UM账户接口返回`-2015`；owner随后要求轮换，Mac/VPS
  `.env`中的API key与secret变量均已无备份删除，两个文件仍为`0600`。VPS绕过代理的两个独立IPv4身份来源与SSH
  公网入口一致，三个强制IPv6探针均不可达；精确IPv4只保存在仓库外production inventory。轮换后的测试credential
  只通过无回显stdin原子写入VPS `.env`并保持`0600`，Mac继续无凭证。Binance认证、读取/Futures/IP限制、提现关闭、
  one-way、全平与全账户0挂单均通过；但Spot/Margin仍开启、可用资金低于300 USDT，TOP3只读symbol config均为
  isolated 2x。由于credential经对话明文传输，最终实盘前必须在交易所再次轮换并直接写VPS。代码的
  `QOUNT_EXCHANGE_BYPASS_PROXY`默认false，不改变既有路径；诊断未调用下单、撤单、转账、杠杆或保证金写接口。
- readiness v0.3又补齐API Futures/IP限制、余额、全平账户和open-orders硬门。最终artifact
  `20260718T100615Z-um-live-pilot-readiness-v04`为`blocked_live_pilot_readiness`，20项blocker、
  `live_orders_allowed=false`，readiness hash `2b072733...a8b1e`，manifest content hash
  `7d4de1b8...f5594`。300 USDT精确本金、公共路由、旧guard关闭和rollback已通过；开始日、forward/paper/dry、
  私有账户与独立live runtime仍阻断。同时冻结的append-only每日journal：
  每行保存权益/钱包、目标与实际权重、订单意图/结果、funding/费用、执行状态和risk flags，并绑定row/chain
  hash；重复日期或历史篡改直接拒绝。本轮未同步VPS代码、未改`.env`、未触碰订单。owner方向已记录，但
  开始日和最终arm仍须在全部安全门通过后单独确认。
- **独立MiniTrend UM order-free forward/paper生产周期曾在VPS启用，现已按安全要求停止。** paper固定Base v0.2、300 USDT
  全现金、200根signal-only warmup、TOP3日线、完整价格与每币每日3次funding，只有10%累计回撤halt，无账户
  单日止损；v0.3同时完整记录Risk 2.0%与Funding Veto shadow且二者不控制订单。`qount-mini-trend-forward.timer`
  曾按每日`03:20 UTC`后随机延迟最多10分钟运行，已于2026-07-20执行`disable --now`并复核为`disabled/inactive`；其历史运行合同显式关闭所有legacy live开关、清空环境代理、`flock`防重入、`umask
  077`并尊重`HALT`。最近完整run为VPS
  `/root/qount/state/mini_trend/forward/runs/20260719T081828Z`：TOP3规则`3/3`，公共日线到`2026-07-18`，funding
  `3/3`完整；冻结起点`2026-07-19`尚无完成bar，因此仍为0 pair/0 paper day/0 journal。preflight v0.3只剩
  `spot_margin_disabled/pilot_capital_available/isolated_one_x_verified`三项账户blocker；readiness v0.4阻断10项，
  artifact全部`0600`且`live_orders_allowed=false`。
- 最新完成bar projector已独立实现：只追加一个明确不计收益的flat synthetic outcome以复用Base状态机并投影最后决策；
  测试证明同一决策在真实任意outcome到来后与paper replay的target和execution-state hash一致。当前因起点bar未完成返回
  `paper_start_bar_not_available/decision=None`。它不等于订单dispatcher；exchange-native stop同步、幂等live执行和7日
  dry仍未实现/未通过，因此`independent_runtime_verified=false`。rollback已同时覆盖forward timer；旧crontab有效行仍为0。
- **固定本金的定投/定减与买卖标签已完成首轮历史discovery。** BTC UM按周25%阶梯、TOP3 UM按周50%阶梯
  （300 USDT下25%会违反BTC最小名义价值）、SPY复权历史按周25%阶梯；均不追加外部资金、不做空、gross不
  超过1，并比较buy-and-hold、经典DCA、均线DCA/DCR和均线全仓/现金。BTC的经典DCA/均线DCA-DCR/持有收益为
  `+47.96%/+51.52%/+87.40%`，TOP3为`+82.34%/+46.81%/+104.91%`，SPY为
  `+79.40%/+62.19%/+82.47%`；均线DCA/DCR均未战胜持有，策略本身不晋级。
- 同一实验用未来20根、波动率归一化triple barrier生成`buy/hold/sell`目标；特征只读决策日已完成数据，
  Logistic/HGB采用按年扩展Walk-Forward且以`label_end_date` purge。六个模型的平均Brier和log-loss uplift都为
  负。TOP3 HGB虽显示`+216.99%`，但4/4 Brier折均输常数先验、2025单年贡献`+92.66%`且2026为
  `-21.11%`，判定为路径/时点运气，不连接仓位。最终artifact
  `/mnt/e/qount_data/qount/artifacts/experiments/20260718T155058Z-periodic-allocation-v02/mini_trend_periodic_allocation.json`
  SHA-256 `0bd6d491...fc`，manifest content hash `aefb001a...49`。
- **美股映射加密资产成为新的低频结构研究线，但产品结构严格分层。** Binance USD-M当前有TSLA/MSTR/AMZN/
  COIN/META/NVDA/GOOGL/QQQ/SPY/AAPL/MSFT共11个`TRADIFI_PERPETUAL`，最早TSLA也只从`2026-01-28`
  开始；Binance spot另有`NVDAB/TSLAB/SPYB`等`*B`映射token。Bybit有AAPLX/AMZNX/COINX/GOOGLX/
  METAX/NVDAX/TSLAX等xStocks现货和对应equity linear合约。映射现货涉及发行/托管/赎回与交易所风险，
  永续只提供合成价格敞口并有funding、标记价格和清算风险，不能混为同一资产或共享回测成本模型。
- 首个冻结假设检验“周末/美股休市期间永续折价，下一美股现金时段部分收敛”：用纽约DST与SPY真实现金
  日历，从前一现金收盘到下一开盘前代理价；只在周末收益为负时做多，下一现金收盘退出，同日标的等权且
  总gross=1，扣24bps往返成本与实际funding。11个标的仅有126个symbol-event、18个独立cash date；周末/
  现金时段相关`-0.188459`、反号率`56.35%`、71个做多信号。按日期聚类后的组合收益`+3.7516%`、maxDD
  `4.0029%`、日期cluster bootstrap正均值概率`71.16%`，证据偏弱，不进paper/live。早期按126个横截面事件
  顺序复利的`+29.69%`重复使用了同一笔资本，已经作废。最终artifact
  `/mnt/e/qount_data/qount/artifacts/experiments/20260718T155058Z-tradifi-weekend-v02/binance_tradifi_weekend.json`
  SHA-256 `d857361f...02c`，manifest content hash `821ad7d2...08`。
- **2026-07-19 owner把下一资金规模设为计划1000 USDT，并要求建设Base+结构Alpha+横截面+LLM信息的组合系统。**
  新文档[crypto-portfolio-system-plan.md](crypto-portfolio-system-plan.md)定义Data/Research/Strategy/Portfolio/
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
  每假设族最多3个正式trial；查看前向结果后改规则会把该时间段降为consumed。Base 60日只作运行证据，Equity按
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
- **2026-07-18 owner将研究治理切换为个人实验`research_sandbox`，已有历史可继续做标签、参数和模型探索。**
  仓库外`qount-doc-autopilot`已改为`research_sandbox / promotion_review / paper_live`三层：历史复用、动态
  ATR/deadband、HGB/LightGBM/XGBoost、HMM/Markov和小型神经网络不再被旧失败结论一概阻断，但必须记录
  trial、时间切分、泄漏检查并把已看窗口称为discovery。首轮已完成：1765行数据覆盖
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
- **2026-07-10 VPS 资源耗尽事故已在 2026-07-11 修复。** 根因不是 Caddy/new-api 网关，
  而是 root crontab 中 C×D live `*/2`、C×D publisher `*/5`、X4 paper daily 三个入口都没有
  `flock`/总 `timeout`；Binance DNS 抖动时，CCXT `load_markets()` 还会额外访问私有
  `/sapi/v1/capital/config/getall`，旧进程不退、新 cron 继续叠加，最终让 1.6G VPS 的 fork/内存
  资源耗尽。修复已部署：三个 cron 入口共用 `scripts/desktop/cron_guard.sh`，脚本内层 non-blocking
  `flock` + process-group timeout；crontab 外层再做同类防线；live 改为每 5 分钟、publisher 错峰
  到第 2 分钟，并由 `deploy/cron/qount-production.crontab` 固化；C×D 删除重复的私有余额读取；
  `build_exchange()` 禁用不需要的
  `fetchCurrencies`；交易腿失败不再刷新网页时间戳伪装成成功。策略权重、2x 上限、short gate、
  exchange-native STOP_MARKET 和 carry paused 均未改变。理由：当前信号是日线，交易所止损已覆盖
  轮询间隙，2 分钟改 5 分钟减少 60% 调度/API 压力，不改变已验证 alpha 语义。
- **VPS 容量余量仍偏薄，但当前不是 qount 残留。** 2026-07-11 00:26 CST 两轮新 live cron
  成功后，qount 相关进程为 0、swap 为 0；主要常驻 RSS 是 `new-api≈433M`、`sub2api≈380M`，
  整机 `MemAvailable≈322M`。因此本次复发链已由 lock/timeout 切断，但“网关 + 多容器 + 实盘”
  共用 1.6G 仍有容量风险。长期仍应给 VPS 加内存或把 qount/网关拆机；没有应用级证据前，
  本轮不擅自给 new-api/sub2api 加可能导致服务抖动的硬 memory cap。
- **2026-07-07 项目治理规则已固定。** 新增
  [project-rules.md](project-rules.md)，作为文档分类、研究线隔离、执行记录、反过拟合规范、
  代码架构和弃用清理的项目级规则。后续每批有意义更改必须更新本线 changelog 或
  [update-log.md](update-log.md)；影响当前事实、生产真相或全局规则时同步更新本文件。
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
  [ashare-etf-month-plan.md](ashare-etf-month-plan.md)、`src/qount/ashare_etf_month.py` 和薄 CLI，
  标准库直连 Tushare `fund_daily + fund_adj`，token 只读 `TUSHARE_TOKEN`；本轮 token 未注入，最终
  artifact `state/research_runs/20260716T094924Z-ashare-etf-month/ashare_etf_month.json` 使用腾讯前复权
  日线。7 月 16 日状态为 `hardware_pullback_application_rotation`：硬件距 MA20 平均 `-12.50%`，
  但 AI 核心距 MA120 `+11.72%`、60 日相对沪深300 `+15.36%`，所以不是全 AI 逻辑结束。四套固定
  组合 59 个不重叠 20 日样本中位数和胜率全部不过；严格同状态只有 1 个独立负样本，轮动杠铃
  `-1.24%`、最大回撤 `-4.62%`，gate `block`。75% 目标被缩至 37.5% 上限/62.5% 现金；当前只有
  只有红利首笔 6.25% 满足条件，即初始暴露最多 6.25%；消费必须等 `0.648-0.655` 回踩或收盘
  `0.670` 放量突破。该读数只保留为历史 discovery；同日后续 owner 决策已冻结本线，不再执行上述
  条件、不接 paper/live，也不改变 L6 或加密生产状态。
- **2026-07-08 Alpha Agents research-only 骨架已接入。** Owner 授权先搭建多 agent 架构用于
  搜集资料、优化设计并后续接入量化训练。新增 [alpha-agent-plan.md](alpha-agent-plan.md) 和
  `src/qount/alpha_agents/`：内置 market-data / exchange-rules / quant-librarian /
  feature / experiment / red-team / ops-audit 等 LLM research 角色，以及 `model_trainer`、
  `backtest_auditor`、`risk_architect` 三个 deterministic/quant 角色；支持从 JSON 替换角色和任务。
  默认不调用 LLM，显式 `--with-llm` + `QOUNT_ALPHA_AGENT_API_KEY` 才接
  `https://llm.alyaloale.com/v1` / `glm-5.2`。硬边界：agent 只写 research artifact，不输出订单、
  目标权重、live 配置或风控 override；promotion 仍必须靠 deterministic scorecard。
- **2026-07-08 Alpha Agents deterministic scorecard 已接入。** 新增
  `src/qount/alpha_agents/promotion.py` 和 `scripts/research/alpha_agent_scorecard.py`，把
  proposal/data/baseline/cost/anti-overfit/breadth/paper/live/LLM-boundary 做成 G0-G7/GX gate。
  该 CLI 只读 metrics JSON 并写 research artifact，不调用 LLM、不访问私有交易所、不写生产 state；
  真实策略必须由 dataset / label / backtest / A10 trainer 产出 metrics，不能用 LLM 报告或手填值
  通过 promotion。
- **2026-07-08 Alpha Agents beta-residual metrics builder 已接入。** 新增
  `src/qount/alpha_agents/metrics.py` 和 `scripts/research/alpha_agent_beta_metrics.py`，从对齐 period
  returns 计算 BTC beta、beta-residual return、相对 BTC / TOP3 equal-weight / current live baseline
  的超额，并生成 promotion metrics。高阶验证字段(DSR/PBO/purged-CV/paper/capacity)默认是
  blocking value，必须由真实 quant artifact 补齐；示例 fixture 正 residual 仍会被 scorecard 的
  G4/G5/G6 block。
- **2026-07-08 Alpha Agents source scoring 与 Binance public returns 已接入。** 新增
  `src/qount/alpha_agents/knowledge.py` / `scripts/research/alpha_agent_sources.py` 对官方文档、论文、
  书籍、教程和安全资料做 trust scoring；教程只能作为 learning material，不能满足 promotion。
  新增 `src/qount/alpha_agents/binance_returns.py` /
  `scripts/research/alpha_agent_binance_returns.py`，复用 Binance public dump 生成对齐 returns。
  2024Q1 UM ETH SMA smoke 已跑通并生成 beta metrics，但 scorecard 正确 block：未用 runtime
  exchangeInfo/filter validator，跑输 BTC/TOP3，BTC beta 过高，未计 funding/min-notional，也没有
  DSR/PBO/paper 证据。
- **2026-07-08 Alpha Agents Binance runtime rules 与 funding 层已接入。** 新增
  `src/qount/alpha_agents/exchange_rules.py` 和
  `scripts/research/alpha_agent_exchange_rules.py`：只拉 Binance 公共 `exchangeInfo`，解析
  `PRICE_FILTER`、`LOT_SIZE`、`MARKET_LOT_SIZE`、`MIN_NOTIONAL`，并对 400 USDT 小盘目标名义做
  min-notional/step-size coverage；不读取私钥、不访问账户、不下单。`binance_returns.py` 现可通过
  `--exchange-rules-path` / `--fetch-exchange-info` 接 runtime rules，并通过 `--include-funding`
  从 Binance public dump 计 USD-M funding cashflow。2024Q1 ETH SMA 复跑：
  `min_notional_coverage=1.0`、`funding_included=true`，但 `net_residual_return_pct=-1.165668`、
  `beta_to_btc=0.552037`，scorecard 仍 `verdict=block`。读法：Binance 规则/成本 plumbing 已补，
  但样例 SMA 明确不是 alpha；下一步应做真正 feature/label/model runner。
- **2026-07-08 Alpha Agents feature experiment runner 已接入。** 新增
  `src/qount/alpha_agents/feature_experiment.py` 和
  `scripts/research/alpha_agent_feature_experiment.py`：从 Binance public dump 读取 klines/funding，
  在 train split 上选 feature grid，再输出 OOS 月度 returns 给 beta metrics/scorecard。当前内置
  `momentum/reversal/relative_momentum/vol_adjusted_momentum` 与
  `long_short/long_cash/short_cash`，仅作为 A10 前的 deterministic baseline contract。2024Q1 ETH
  1h smoke 选中 `relative_momentum_lb12_thr0_long_short`，OOS `strategy_total=-30.103078%`、
  BTC B&H `+39.471843%`、TOP3 EW `+54.382491%`、`beta_to_btc=7.494191`、
  `net_residual_return_pct=-302.677680`，scorecard `verdict=block`。读法：第一批简单价量 feature
  被 OOS 打穿；已打通模型实验接口，但没有可交易 edge。下一步应补 walk-forward/DSR/PBO 与更强
  microstructure/OI/bookTicker 特征，而不是继续调这个候选。
- **2026-07-08 本地 GLM-5.2 Alpha Agents 已跑通并产出 Strategy V0（历史快照，运行配置已由7月19日合同取代）。** Owner授权把gateway key
  放入本机用户级环境；已写入 `~/.qount/alpha-agent.env`，权限 `600`，由本地 runner 自动读取，
  不进入仓库、artifact 或 `.env`。`alpha_agent_plan.py --with-llm` 现支持 `max_concurrency=3`、
  `max_tokens=4000`、`max_retries=1`，单个 LLM 输出失败会重试或降级为 blocked report，不再打断整批。
  全量 agent artifact：
  `state/research_runs/20260708T044141Z-alpha-agent-plan/alpha_agent_plan.json`。基于结果在
  [alpha-agent-plan.md](alpha-agent-plan.md) 增补 `Strategy V0: Microstructure Residual Alpha`：
  第一刀是 USD-M 1m/5m residual alpha，先做 `kline_taker_flow_v0` 和 `derivative_state_v0` kill-test，
  bookTicker/aggTrade/diff-depth/forceOrder 先走 live collector gap/replay，不直接 promotion。
- **2026-07-08 Alpha Agents derivatives-state 数据层已接入。** 新增
  `src/qount/alpha_agents/derivatives_state.py` 和
  `scripts/research/alpha_agent_derivatives_state.py`，只用 Binance public REST 拉
  `/futures/data/openInterestHist`、`/futures/data/takerlongshortRatio` 和 `/fapi/v1/openInterest`，
  写 research artifact，不读私钥、不访问账户、不下单。该接口按官方 recent-data 限制只作为近 30 天
  research/forward 输入，不能伪装成 2021-2026 长历史。真实 1 天 5m smoke artifact：
  `state/research_runs/20260708T045352Z-alpha-agent-derivatives-state/alpha_agent_derivatives_state.json`；
  BTC/ETH/BNB/SOL 的 OI 与 taker ratio 各 288 rows、0 gaps、coverage ≈ `0.9965`，
  `open_interest_hist_count=1152`、`taker_long_short_count=1152`、`current_open_interest_count=4`、
  `error_count=0`。
- **2026-07-08 derivative-state feature runner 已接入并完成第一刀 smoke。**
  `alpha_agent_feature_experiment.py` 现支持 `--kline-source public_dump|rest`、
  `--derivatives-state-path`、`--min-feature-coverage`，并新增 `oi_delta`、`oi_value_delta`、
  `taker_ratio`、`taker_imbalance`。当前 Mac 到 `fapi.binance.com` REST kline 直连超时/SSL EOF；
  public dump fallback 因 ETH/SOL 2026-07-07 5m daily dump 尚未发布，完整 BTC/ETH/BNB/SOL smoke
  被 coverage gate 正确拦截。可运行的 BTC/BNB 两币 BNB smoke：
  `state/research_runs/20260708T093014Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`，
  OOS `strategy_total_return_pct=-7.056039%`、BTC `+1.403648%`、equal-weight `+1.135040%`、
  `net_residual_return_pct=-7.301083`；metrics
  `state/research_runs/20260708T093052Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`；
  scorecard `state/research_runs/20260708T093102Z-alpha-agent-scorecard/alpha_agent_scorecard.json`
  为 `verdict=block`。读法：OI/taker ratio 接入链路可用，但这一刀没有 alpha；不能 forward paper
  或 live，下一步应补 taker-flow/walk-forward/DSR/PBO，并在 ETH/SOL dump 或 REST 路由恢复后复跑完整 universe。
- **2026-07-10 `kline_taker_flow_v0` 已完成并按当前执行合同停止。** `Bar` 现保留 Binance kline
  原生 quote volume、trade count、taker-buy base/quote volume；feature runner v0.2 新增
  `kline_taker_imbalance`、`kline_taker_pressure_change`、`kline_quote_volume_z`、
  `kline_realized_vol_change`、显式 `polarity=+1/-1`，以及 rolling as-of BTC beta 的 forward residual
  rank-IC 选择。真实 BTC/ETH/BNB/SOL、5m、2024-01..08、train 6 月/OOS 2 月、40 trials/horizon：
  h3 选中 `kline_taker_imbalance_lb3_inv`，train/OOS rank IC `0.01993/0.03481`，但 OOS
  `net_residual=-166.019%`；h6/h12 均选中已知 price momentum inverse，OOS rank IC
  `0.02344/0.01326`，net residual `-91.363%/-58.191%`。三份 scorecard 均 `verdict=block`。
  读法：h3 taker imbalance 有弱信息，但训练 IC 未过 `0.02` 且 taker 换手成本把 gross edge 完全吃掉；
  h6/h12 没有产生新 taker-flow 候选。不能在已看 Jul-Aug 上继续调 threshold 后把它当 validation，
  不进 A10/paper/live；本轮随后已补 walk-forward/DSR/PBO，结果继续 block，下一步转 collector 数据层。
- **2026-07-10 research artifact 并发覆盖已修复。** 并行生成 h3/h6/h12 metrics 时发现原目录名只有
  秒级时间戳，三个进程会写同一路径。`persistent_research_dir` 现通过原子目录创建分配
  `base/-01/-02`，同秒并发 artifact 不再互相覆盖；三路并行 metrics/scorecard 已实测生成独立路径。
- **2026-07-10 Alpha Agents G4 validation adapter 已接入并完成真实负向验证。** 新增
  `src/qount/alpha_agents/validation.py` 和 `scripts/research/alpha_agent_validation.py`，按源 feature
  artifact 的冻结 config 重放 candidate matrix，计算源选中候选 DSR、按原 `rank_ic` 选择语义的
  CSCV/PBO、带 embargo 的 purged folds 和 expanding walk-forward；普通 feature artifact 仍保持精简。
  `alpha_agent_beta_metrics.py --validation-path` 只接受 source feature path 完全匹配的 validation，
  防止跨实验拼接 G4。真实 h3：selected per-period Sharpe `-2.2764`、DSR `3.19e-152`、
  PBO `0.781746`、purged `0/5` 正、walk-forward `0/5` 正、largest-contributor-removed
  `-99.9975%`；最终 scorecard 的 G4 同时因 DSR/PBO/purged/largest-contributor block。
  artifact：`20260710T134718Z-alpha-agent-validation`、metrics `20260710T134758Z`、scorecard
  `20260710T134808Z`。旧 `20260710T134252Z` 使用 Sharpe-selection PBO，已被最终 source-selection
  CSCV artifact 取代，不作为结论。完整测试 `970 OK`，Alpha/数据/validation 聚焦测试 `57 OK`。
- **2026-07-14 Alpha Agents S3 public microstructure collector 已完成严格 60 秒数据层 smoke。**
  新增 `src/qount/alpha_agents/live_collector.py` 和
  `scripts/research/alpha_agent_live_collector.py`，research-only 采集 Binance USD-M public
  `bookTicker`、`aggTrade`、diff-depth、`forceOrder`，并用 public WS-API/REST depth snapshot
  做 update-id gap、事件时间和订单簿重放审计；不读取账户、不下单、不写 paper/live state。
  snapshot 获取现使用有限重试并保留 retry 诊断，只有重试耗尽才计最终错误，默认错误率门槛仍为 1%；
  默认交易流已对齐 S3 合同为 `aggTrade`。最终 BTC/ETH/BNB/SOL 60 秒 artifact
  `state/research_runs/20260714T093402Z-alpha-agent-live-collector/alpha_agent_live_collector.json`
  共 23,339 条市场事件、16/16 snapshots、aggTrade gap `0`、depth sequence break `0`，实际重放
  1,919 个 depth update 后非法档位/空簿/crossed book 均为 `0`，四币全部锚定，event stale/future
  均为 `0`，`verdict=pass_data_smoke`。一次 public 流首次建连 `SSLEOFError` 后重连成功，发生在
  `connection_open` 前，未形成数据 gap。读法：S3 gap/replay 实现和短时公网 smoke 已通过，但计划要求的
  7 天 forward data gate 尚未完成；这不是 alpha、scorecard 或 promotion 证据，不能训练 A10、forward
  paper 或 live。
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
- 2026-07-07 已部署 X4 live 执行修复到 VPS：交易所原生 STOP_MARKET 在两分钟 cron
  间隔内打平后，会根据上一轮 holdings + 当前交易所仓位同步写入本地 Chandelier
  `latched`，防止同一日线 short 目标下立即重开；`cxd_live_cron.sh` 同步加入 5MB
  默认日志轮转，只归档 `/root/cxd_live.log` 到 qount 自身 `state/logs/archive/`。
- 旧 line A / ETH-only 研究线当前没有 promotion 证据，不能 forward paper，也不能 live。
- 旧 13-window 结果现在只能作为 discovery 证据；promotion 只看
  `holdout_role=validation_v1` 的 once-only 新窗口。
- 2026-06-04 第一次 `validation_v1` once-only 端到端验证失败；盈利导向补的
  `eth_short_range_noise_terminal_washout` blocker 能把这两个窗口降级 discovery 后转正。
- 2026-06-03..2026-06-04 的第一次 validation artifact 被 AI relay `auth_unavailable`
  污染；恢复后同策略复跑无 AI 错误，但 realized 更差，仍未过 `G_paper`。
- 不能用 2026-06-01..2026-06-04 已看过窗口调参后再当 validation。
- 2026-06-05 已按 [profit-engineering-plan.md](profit-engineering-plan.md) 启动 S0.1：
  research ML 依赖只作为 optional extra；live / `run-once` 默认依赖和交易行为不变。
- 2026-06-05 S1'（频段 × 策略族选择扫描）第一遍已全量跑完，结论是 CARRY 被 basis-tail
  证伪、唯一存活候选是预测族 `4h xs_mom lb24/h6` 但未过可执行 exit；计划与现实的对账见
  [profit-engineering-plan.md](profit-engineering-plan.md) §11，S2 重模型仍未启动。
- 2026-06-05 已按 §11.5 N1 做 `4h xs_mom` 的波动率缩放 triple-barrier：vol-scaling 修正了
  fixed barrier 的非对称止损病，PnL 随 barrier 加宽单调改善，但没有任何 σ 设置能跑赢"无
  barrier 持有到期"的 close-exit 基线，最佳 `tp4/sl4` 仍只有 `+0.165`(< close `+0.297`)、
  3 月仍负、~90% 收益来自 5 月单月。N1 门控未通过，**仍不进 S2**。
- 2026-06-05 又按 N1 做 entry 侧 regime dispersion 门：`thr0.034` 总收益不变(`+0.299`)、
  Sharpe `7.19→8.00`、回撤 `0.088→0.080`，并把 2026-03 从负翻正、4 月全部 ≥ 0——首个真正
  改善月度稳健性的子步骤;但属 in-sample 阈值、5 月仍约 82% 收益、无新 OOS，N1 仍未过、
  **不进 S2**;下一刀把 `thr0.034` 固定留到下一个完整 `validation_v1` once-only 复核。
- 2026-06-05 已按 §5/§9.x 给 scan 补 Deflated Sharpe Ratio：在选出候选的 81-cell 网格上
  DSR ≈ `0.082`，最佳 per-period Sharpe `0.278` < 噪声期望最大值 `0.407`——候选的网格内
  选择优势大概率是多重检验假象。S2 门控加硬:新 OOS 正 + 可接受 DSR/PBO 才进 S2。
- 2026-06-05 又补 PBO/CSCV：同一网格 pbo 4h=`0.020`/1h=`0.056`/1d=`0.214`(全 < 0.5)。
  与 DSR 互补:存在弱但排名稳定的横截面动量结构,但量级(DSR≈0.08)太弱不足以确认盈利;
  且同频段 config 高度相关会让 PBO 偏低。两指标都指向不进 S2,等新 OOS。
- **2026-06-06 决策:`4h xs_mom lb24/h6` 候选按 §7 诚实退出。** N1 反过拟合工具
  (vol-barrier / regime 门 / DSR / PBO)已全部做完,合起来给出的结论比"等新 OOS"更尖锐:
  (a) 选出候选的 81-cell 网格 **DSR ≈ 0.082**、最佳 per-period Sharpe `0.278` < 噪声期望
  最大值 `0.407`——网格内选择优势在统计上与"81 次噪声里挑最大"不可区分;(b) 没有任何
  可执行 path-dependent exit(fixed / σ-scaled barrier 及同类部分止盈/移动止损)跑得赢
  "无 barrier 持有到期"的 close 基线;(c) 即便最好的 regime 门 `thr0.034` 也仍有 ~82% 收益
  来自 5 月单月。三者合起来即 [profit-engineering-plan.md](profit-engineering-plan.md) §7
  的全局退出条件——"搜了 N 个 cell 后该候选的优势不显著"。**不为它消耗 once-only 日期**:
  今天(2026-06-06)相对该候选只多出 `2026-06-04..06` 约 2 薄天(4h 仅 ~12 根 bar),即便正也
  不可能把 DSR 从 0.08 拉到可接受;烧一次性日期在这么薄的窗口上是浪费。**关闭该候选的 S2
  晋级路径**,研究转向 §10 的换频段 / 换特征源(微结构 / funding / 时序基础模型特征),或按 §7
  接受研究价值、停止追盈利。纪律不变:不在已看 2–5 月上加任何旋钮,`validation_v1` once-only
  资格留给未来真正够厚的独立窗口。对账见 §11.7。
- **2026-06-06 §10 换特征源第一刀 kill-test:funding 作横截面预测特征 = 证伪。** 新增
  `xs_funding` / `xs_funding_rev` 两族(funding 以 as-of join 无前视对齐到每根 bar 当信号,
  区别于已被 basis-tail 证伪的 CARRY 现金流用法),复用横截面 IC / DSR / PBO harness。top12、
  120 天 discovery、post-cost、{4h,8h,1d}×{2 族}×holding{1,3,6}=18 cell:
  (a) **rank-IC 全 ≤ 0.030**(最强 4h/h3 仅 `+0.030`)——比已嫌弱的价量动量 `0.052` 还弱,
  远低于 §10.2 要求的 `0.06`;(b) 唯一正 cell `1d xs_funding_rev h6`(sum `+1.05`、sharpe
  `1.79`)的 rank-IC ≈ `0.005` ≈ 0,且相邻 holding 不一致(h1 负 / h3 `+0.50` / h6 `+1.05`),
  是 1d 仅 119 个重叠横截面上的噪声/overlap 假象;(c) **carry-tilt DSR ≈ `0.25`**,best
  per-period Sharpe `0.094` < 噪声期望最大值 `0.156`——选择优势与噪声不可区分;(d) **PBO
  ≈ 0.49–0.55**(8h/1d 相关频段),高过拟合概率;(e) 4h/8h 全被成本打负。继 CARRY 现金流
  之后,**funding 这一新信息源的第二种用法也证伪**,最便宜的新源耗尽,进一步压向 §7 诚实止盈。
  artifact:`state/research_runs/20260605T231910Z-...-s1-carry-tilt-funding-top12real-120d-20260606`
  (另有 4 币薄广度交叉验证 `...-funding-top12-120d-...`,结论一致)。只跑 discovery,未碰
  `validation_v1`。basis_pct 与 funding 经济上近共线;carry-tilt 路径暂未接 premium-index
  enrichment,如要确认性复核需补该 plumbing,优先级低。
- **2026-06-06 架构级根因诊断:横截面广度是幻觉,§10.2 破局数字被经验证伪。** 不再机械试
  第三种特征源,先查 §10.2 整套破局逻辑的前提——「日频横截面 ~10 币 → BR~300 → 要求 IC 0.06」
  ——是否成立。直接读 funding artifact 已报的 `effective_breadth`(标准公式
  `N/(1+(N-1)·r̄)`):top12 的平均绝对两两相关 **r̄ ≈ 0.63**,**有效广度仅 ≈ 1.5**(4h 1.53 /
  8h 1.50 / 1d 1.52)。关键:有效广度随 N→∞ 收敛到 `1/r̄ ≈ 1.6`,即 **N=12 给 1.52、N=100 万
  也只有 1.59——扩币在数学上救不了**。把真实有效广度代回 Grinold(IR=IC·√BR、IR=1 口径):
  §10.2 假设 ~10 币给要求 IC `0.058`;真实 ~1.5 币使 BR 缩 ~6.5×、√BR 从 17 掉到 6.8,
  **要求 IC 实际 ≈ 0.148**。而观测最强横截面 IC 只有 xs_mom `0.052` / xs_funding `0.030`,
  **离真实要求约 3× 缺口**。结论:加密 majors 同涨同跌,横截面把"多币"折成 ~1.6 个有效独立
  资产,§10 押注的广度杠杆**结构性不存在**;要求 IC 被打回 ~0.15 的"5m 不可达"区间——这正是
  §10 想逃离的天花板。这是**架构级 §7 证据**:换特征源 / 扩币都改变不了广度天花板,xs_mom /
  ts_mom / xs_funding 全部过不了线是同一个根因。**2026-06-06 所有者已据此确认执行项目级 §7
  诚实止盈**(见上方「当前结论」)。对账见 §11.8。
- **2026-06-06 重启方向设计:L3 换信息源(链上/流/叙事 + AI)。** §11.8 规定唯一合法重启触发是
  「结构性新输入」;经五杠杆(L1 跨资产 / L2 事件驱动 / L3 换信息源 / L4 跨所套利 / L5 换目标)
  权衡,所有者选 **L3**——把信息源从价量换成非价量慢数据、horizon 抬到日/周线、AI 从最终 gate
  挪到慢特征/regime 标注层,攻基本定律的 **IC 项**。新计划文档
  [l3-information-edge-plan.md](l3-information-edge-plan.md):优先 **L3a 稳定币供给→市场择时**
  (广度来自时间 ~150 周、要求 IC ≈0.083 比横截面 0.15 更可达、执行最干净);第一刀 kill-test 即
  DefiLlama 稳定币供给对 BTC 周线 forward-return 的时序 IC + DSR/PBO。仍 research-only、先证伪
  再投入、全套硬约束不变;不过则 L3 也按 §7 退出。
- **2026-06-06 L3 S0.1 数据接入层已落地并端到端验证(research-only)。** 新模块
  `src/qount/l3_information_edge.py` + research-only 命令 `l3-stablecoin-fetch`:拉 DefiLlama
  聚合稳定币总供给、缓存到 `state/`、归一化成排序去重日度序列、严格 as-of(无前视)join 到周线
  锚点;只用 stdlib `urllib`、不引入新依赖、live / `run-once` 不 import。local/WSL unittest 均
  `254 OK`(+5 新单测)。WSL 实网拉取:3112 日度观测(2017-11..2026-06)、归一化零丢点、近 4 年
  窗口 209 周锚点全覆盖(全历史 444 周)、缓存命中路径已验证。artifact
  `state/research_runs/20260606T045947Z-l3-stablecoin-fetch/`。**只做数据层,未算 IC、未下注**;
  下一步 S1 kill-test(稳定币供给增速 → BTC 周线 forward-return 时序 rank-IC + DSR/PBO,门控
  breadth-adjusted 要求 IC ≈0.083)。硬约束全不变,未碰 `validation_v1`。
- **2026-06-06 L3 S1 kill-test 完成:L3a(稳定币供给→BTC 周线择时)= 证伪。** 新增
  `evaluate_l3a_stablecoin_timing` + 命令 `l3-stablecoin-timing-scan`:供给 log-增速
  (lookback 4/8/13 周)对 BTC t→t+h(1..4 周)forward-return 的时序 rank-IC,复用 §7 的
  DSR/PBO/Spearman/`_sharpe` harness,12 个 (L×h) config 全计 DSR trial,BTC 走期货 fapi。
  local/WSL `257 OK`(+3 单测)。两窗口实跑均 `falsified_l3a`:全窗口 2020-07..2026-06(309 周)
  best |rank-IC|=`0.054` < 门控 `0.083`(净正只是退化恒做多的 BTC beta,DSR/PBO 因 config 雷同
  虚高、不具判别力);子窗口 2022-06..2026-06(209 周)|rank-IC|=`0.154` 虽过门控却**符号翻转为负**
  (与"供给=干火药→涨"先验相反)+ PBO `0.64`(高过拟合)。**符号在窗口间翻转 = 无稳定样本外预测**
  ——供给与 BTC 同骑一条流动性周期(内生共动),与 §7 价量 IC ~0.05 天花板同源。rank-IC 对单调变换
  不变,z-score 救不了。artifact `state/research_runs/20260606T051647Z-...` 与 `...051746Z-...`。
  下一步按 §5/§8:测 L3b(链上横截面,相关天花板+共动顾虑仍在)或经济动机耗尽则 L3 按 §7 退出。
  硬约束全不变,未碰 `validation_v1`。
- **2026-06-06 L3b(链 TVL 横截面)kill-test 完成 = 证伪;L3a+L3b 均证伪 → L3 整体证伪,按 §8/§7
  退出。** 新增 `evaluate_l3b_chain_tvl_cross_section` + 命令 `l3-chain-tvl-scan`:DefiLlama 链
  TVL log-增速横截面排序 12 个链 token,复用 §7 harness + `_panel_effective_breadth`。local/WSL
  `259 OK`(+2 单测)。WSL 实跑(209 周):**effective_breadth=`1.68`**(r̄=0.559)< 逃逸阈 2.5 →
  breadth 不逃逸;best |rank_ic_mean|=`0.0755`(t=3.47,正、全 9 cell 符号稳定、DSR 0.953/PBO 0.36
  都过)< 门控 0.15 → `falsified_l3b`。**这是 §2"广度幻觉"的经验证实**:L3b 找到了真实、显著、
  符号稳定的弱信号(链 TVL↑→token 涨),但 token 收益面板有效广度仍只有 1.68(贴着 §7 价量天花板
  1.6),要求 IC 仍 ~0.15、真信号只有一半——**绑定约束是广度不是信号,§7 架构级根因在新数据源原样
  复现**。慢数据换信息源没绕开广度天花板。下一次重启需真正结构性新输入(L1 低相关 universe / L4
  跨所套利 / L5 换目标),非 L3 内部堆特征。artifact `state/research_runs/20260606T052959Z-...`。
  硬约束全不变,未碰 `validation_v1`。
- **2026-06-06 重启线选定 L1(跨资产趋势,正面攻 BR);S1 广度 kill-test 通过。** 所有者从
  L1/L4/L5 选 L1。命门是「跨资产 universe 有效广度是否 ≫1.6」——纯数据、零新场(新模块
  `l1_cross_asset.py` + 命令 `l1-cross-asset-breadth-scan`:Tiingo 免费跨资产 EOD → as-of 周线
  → `_panel_effective_breadth`)。**基建发现:跨资产 TradFi 免费免-key 源(Stooq 反爬 / Yahoo
  429 / FRED 超时)从生产主机全不可用;选 Tiingo(已配 key)**。local/WSL `262 OK`(+3 单测)。
  WSL 实跑(广度随 universe 正确变宽单调改善):crypto majors r̄0.63/breadth 1.6 → L1 13-ETF
  r̄0.354/**2.477**(临界)→ L1 21-ETF 跨资产 r̄0.303/**2.973** > 2.5 → `breadth_supports_l1`。
  **真正跨资产 universe 结构性逃逸了 majors 广度天花板**(§7/L3 都缺的那一项);eff_breadth 2.97
  × ~52 周 → BR≈154 → 要求 IC≈0.081(可达,远好于横截面 0.15)。门控 2.5 未动,只按论点本意
  补全 universe。**S1 通过 → 进 S2**(ts_mom 聚合 IR / 扣费净值 / DSR / PBO)。诚实保留:广度
  过线必要非充分,趋势扣费 IR 是否过线是 S2 才知道;开券商只在 S1–S4 全过后。计划见
  [l1-cross-asset-plan.md](l1-cross-asset-plan.md)。artifact `...20260606T062015Z-...`。硬约束全不变。
- **2026-06-06 L1 S2 趋势 kill-test:真实正 edge 但低于门控(`tsmom_below_gate`)。** 21-ETF
  TSMOM(sign(trailing L 周收益)× 反波动率定权,周再平衡)+ 复用年化 Sharpe/DSR/PBO(命令
  `l1-cross-asset-tsmom-scan`)。local/WSL `263 OK`(+1 单测)。WSL 实跑(753 周):best 年化净
  Sharpe `0.421`(lb39w,gross 0.542)、4 lookback 净 Sharpe 全正、2022 利率趋势 crisis-alpha;
  但 < IR 门控 0.5,DSR `0.856`(<0.95)、PBO `0.627`(>0.5)均不过。**跨资产趋势是真实、正、经济
  一致的 edge(不同于 L3a 噪声),但零售 ETF universe 上只有 ~0.42 净 Sharpe**——绑定限制从广度
  变成「零售 ETF 的 edge 量级」,真 CTA 需 50–100 期货(券商,S5 推迟)。S2 未过 → 不进 S3。
  下一步所有者决策:lookback 等权 ensemble(无参、回应 PBO)/ 接受 ~0.42 作零售天花板 / 停。
  artifact `...20260606T063553Z-...`。硬约束全不变,未碰 `validation_v1`、未开券商。
- **2026-06-06 L1 S2 ensemble:确认 edge 真实稳健但量级仍 < 门控(`tsmom_ensemble_below_gate`)。**
  按所有者选择做 lookback 等权 ensemble(`--ensemble`,信号层 `mean_L sign(trailing_L)`,无参 →
  purged 时间折代替 DSR/PBO)。local/WSL `264 OK`(+1 单测)。WSL 实跑:净年化 Sharpe `0.363`
  (gross 0.553)、**4/5 时间折为正**(0.87/0.11/0.35/-0.04/1.00)——但**反而略低于最佳单一 lookback
  lb39w 0.421**(等权纳入较弱快周期 lb13w 0.10 拉低)。**L1 完整定论:跨资产趋势是本项目第一个
  真实、稳健、正、经济一致的 edge**(gross 0.55、4/5 折正、2022 crisis-alpha、与 crypto 无关),
  但零售 ETF 净 Sharpe 仅 ~0.36–0.42 < 开券商所需 0.5;绑定限制是「原始 edge 量级 × 零售 universe」
  非方法,经典 CTA 0.7–1.0 需 50–100 期货(券商 S5)。S2 未过 → 不进 S3。**L1 落在终局决策点**:
  S5 券商(真期货 universe)/ 固化为部分成功 / 转 L5。artifact `...20260606T064415Z-...`。硬约束
  全不变,未碰 `validation_v1`、未开券商。
- **2026-06-06 终局决策(所有者确认):L1 固化为部分成功,暂停。** 三条文档内合法路径
  (S5 券商 / 固化 / 转 L5)中,所有者选**固化**。理由对账:(a) L1 计划 §3 规定「开券商(S5)
  只在 S1–S4 全过之后」,而 S2 扣费 IR 不显著(净 Sharpe ~0.4 < 0.5)、DSR `0.856` < 0.95、
  PBO `0.627` > 0.5 均未过——**不在 sub-gate 证据上开真期货券商、不为它建新工程轮/掏真实资金**;
  (b) 在同批已看 ETF 数据上继续加旋钮/堆标的正是 §5 禁止的「L1 内部堆参当重启」,L1 内部可触及
  研究路径已穷尽。**固化内容**:L1 是本项目**第一个真实、稳健、正、经济一致的 edge**(21-ETF
  跨资产 TSMOM,gross Sharpe 0.55、净 0.36–0.42、4/5 时间折正、2022 利率趋势 crisis-alpha、与
  crypto 无关),并**经验证实了 §2 的核心论点**——把 universe 换成结构性低相关的跨资产能真正逃出
  majors 广度天花板(eff-breadth 1.6 → 2.97),绑定约束随之从「广度」迁移到「零售 ETF 的 edge
  量级」。**这是停止在 L1 上投入,不放宽任何纪律**:L1 按 §7 暂停而非删除——若未来开期货券商
  (独立工程轮)或拿到结构性更优 universe,S2 门控原样适用、从 S3 续跑。live 仍关闭、不 forward
  paper、不放宽 broad gate、`validation_v1` once-only 资格继续保留。下一次重启需新的结构性输入
  (L5 换预测目标=波动率 / L4 跨所套利),非 L1 内部微调。对账见
  [l1-cross-asset-plan.md](l1-cross-asset-plan.md) §3/§5。
- **2026-06-06 重启线选定 L4(跨所套利,换「游戏」=市场中性不预测方向);S1 跨所 spread kill-test
  证伪。** 所有者从 L4/L5/L2 选 L4。命门:跨所 funding spread 的「幅度 × 持续性」能否跨过双所往返
  成本——纯数据、零新场、零下单(新模块 `l4_cross_exchange.py` + 命令 `l4-cross-exchange-funding-scan`:
  ccxt 拉多所 perp funding 历史、`state/` 缓存、按各所原生间隔归一到 8h 当量、as-of 对齐、取
  `spread=max−min` 做多最低所/做空最高所、复用 §7 的 `_sharpe`/DSR/PBO)。**基建发现:三所
  Binance/Bybit/OKX 均需配置代理(直连全 NetworkError),跑命令前必须 `source .env`,否则
  `Settings.from_env` 拿不到代理→全所 unreachable;Hyperliquid 实测可达但 USDC 结算+1h funding,
  推迟 S2 需独立符号/基差映射。** local/WSL `269 OK`(+5 单测)。WSL 实跑(120 天 discovery、
  6 USDT 永续、binance/bybit/okx、261 共同 8h bucket):**(a) 跨所 spread 真实为正——毛年化
  `+0.074`(7.4%/yr)、6 币毛值全正**;(b) 但 `break_even_cost_per_side ≈ 0.000027`(**2.7bps/腿**),
  且最优 pair **每 ~1.5 bucket(~12h)翻转一次**(261 翻 ~165 次),每翻付 4 腿往返;(c) 按 taker
  `0.0004`:净年化 `−1.6`、组合 Sharpe 深负、**`required_maker_fill ≈ 0.93`**(单所 CARRY 的 maker
  墙跨所原样重现);(d) `DSR=0.0`(最佳 per-period 净 Sharpe `−1.1` < 噪声期望 `0.107`)、PBO 0.083
  (低但因净负无意义)。`decision=cross_exchange_spread_below_gate`。**根因:套利者已把跨所 funding
  spread 压到 ~maker 成本地板(回本 2.7bps),残差每 ~12h 均值翻转 → 4 腿换手吃光毛值**;只有
  co-located maker/返佣 HFT(另一种操作者、需多所基建)够得着,对本「慢+延迟无关」操作者证伪——
  正是计划 §5/§1 预判的成本墙。S1 未过 → 不进 S2。artifact
  `state/research_runs/20260606T113148Z-l4-cross-exchange-funding-scan/`。硬约束全不变,未碰
  `validation_v1`、未下任何单、未开多所账户。**L4 落在终局决策点**(退出转 L5/L2 /
  L4-S2 maker 执行研究需多所账户),对账见 [l4-cross-exchange-plan.md](l4-cross-exchange-plan.md) §3/§5。
- **2026-06-06 全局决策(所有者确认):接受 §7 全局诚实止盈,三条重启线全部走完,停止追择时盈利。**
  §7 原始止盈后,按 §11.8「唯一合法重启=结构性新输入」依次试了三条结构性重启线,各攻 `IR=IC×√BR`
  的不同项或游戏本身,**全部撞到同一类结构性/成本墙**:
  - **L3(换 IC 来源:非价量慢数据)= 证伪** —— 广度天花板在新数据源原样复现(L3b 找到真信号
    IC 0.075 但 token 收益 eff-breadth 仍 1.68,要求 IC ~0.15)。
  - **L1(攻 BR:跨资产趋势)= 固化暂停** —— 跨资产 universe 真逃逸广度天花板(eff-breadth 2.97),
    找到**项目首个真实、稳健、正、经济一致的 edge**(跨资产 TSMOM),但零售 ETF 量级净 Sharpe ~0.4
    < 0.5 券商门控;真 CTA 量级需期货券商(独立工程轮,未授权)。
  - **L4(换游戏:市场中性跨所套利)= 证伪** —— 跨所 funding spread 真实(毛 +7.4%/yr)但已被压到
    maker 成本地板(回本 2.7bps)+ 每 ~12h 翻转,换手吃光,required_maker_fill ~0.93(CARRY maker 墙跨所重现)。
  **固化的研究价值**:整套反过拟合 harness(triple-barrier / purged-CV / DSR / PBO /
  effective-breadth / breadth-adjusted 要求 IC)、kill-test 方法论(最便宜的证伪优先)、以及三条
  重启线的诚实证据链——**这些是项目的真成果**。**唯一合法的下一次重启触发仍是所有者授权的结构性
  新基建**:期货券商(L1-S5,把真 edge 量级补到券商档)/ 期权场(L5 波动率变现)/ 多所账户(L4-S2
  maker 执行)——**当前一个都不追**。**这是停止投入,不放宽任何纪律**:live 仍关闭、不 forward paper、
  不放宽 broad gate、`validation_v1` once-only 资格继续保留。对账见
  [profit-engineering-plan.md](profit-engineering-plan.md) §11.8。
- **2026-06-08 重启线 L6(A股 L2 微观结构,换信息源攻 IC 项):所有者授权,主线 L6-daily,D0 完成。**
  §11.8 规定唯一合法重启是「结构性新输入」;所有者提供 A股 逐笔委托级 Level-2(Wind 三件套,
  6TB/网盘),首个真正的结构性新数据源。**日内线 Phase 1(单日 20260407,15 ETF)实测**:订单流
  IC 真高(`micro_price_dev @1m` rank-IC +0.139,符号稳)——项目首次用新数据把 IC 抬过日频 0.05
  天花板,但每个可操作档(≥1m)净收益全负(振幅 ~0.8bp < T+0 往返成本 ~5–10bp),高振幅 IC 在
  亚分钟需 co-location=慢操作者够不着(L4 延迟墙变体)。**主线转 L6-daily**(所有者选定):用 L2
  重建**日线知情流**特征预测次日/次周截面收益——成本无关(日移动 1–3% >> 10bp)、全个股截面广度
  友好(~7 >> ETF 1.7)、数据极便宜(6TB → MB 级小面板)。**D0 完成**(写日线特征+ETL+单测,单日
  全截面验证分布合理、无前视):全个股 ETL 跑两天,20260407 scored 7762/7778(99.8%)、20260408
  7714/7715(100%),五特征(`aggressive_ofi`/`large_aggr_ofi`/`late_minus_early_flow`/
  `close_auction_imbalance`/`cancel_imbalance`,全 L2 衍生、区别于已证伪的券商粗主力)分布合理
  (均值近 0、饱和率 0.3%–7.4% 且集中在低流动性微盘)。本地 363 OK + WSL 363 OK。原始 85G 经一次
  ETL 塌成日线面板(几 MB);两天各 1356 只 T+0 ETF 原始三件套归档 `~/Desktop/l6_etf_raw/`
  (日内 Phase 1/2 素材),全个股原始删除(所有者授权、网盘有备份)释放 ~63G。下一步 **D1**(生死第一
  刀,需多日数据):跨日全个股截面 rank-IC + 符号稳 + DSR/PBO + 有效广度,门控截面 IC > 0.06;
  当前仅 2 天无法测预测力,需继续攒日。**D2 增量门**:须证明对「价量动量+粗主力」有增量 IC,否则
  只是换皮重测拥挤因子。硬约束全不变,research-only、未碰 `validation_v1`、未下单。计划见
  [l6-microstructure-plan.md](l6-microstructure-plan.md) §4b。artifact
  `state/research_runs/20260608T040443Z-...` 与 `...042318Z-...`。
- **2026-06-08(续)L6 扩到 4 天 L2 + 所有者选 ETF 版 L6-daily。** L2 知情流扩到 0403/0407/0408/0409
  (清明休市除外),全个股日线 panel 四份(99.8%–100%),个股主线数据继续累积。**所有者方向:做
  ETF 版 L6-daily**(universe 换 T+0 ETF:ETF L2 知情流 → ETF 次日收益);标签 blocker 解除——panel
  自带 `day_close`,forward-return 跨天直接算,不需外部日线。ETF 管线已验证(1356 全打分),但两个
  隐忧:流动性长尾(近半成交<500 笔、竞价饱和 18–20%)+ ETF 截面广度历史 ~1.7(正是主线选全个股
  =~7 要逃的天花板);ETF 版真实权衡=**广度↓(致命) vs T+0 日内可兑现↑(个股 T+1 大半 alpha 不可
  兑现,ETF 版唯一救赎)**,生死靠活跃子集 `_panel_effective_breadth` 实测。**数据工程**:每天 38–47G
  全市场原始 → 几 MB panel;ETF 原始 4 天 21.5G 压缩 8.7%(1.87G)归档 Windows `D:\qount_l2_archive\`
  (字节+zstd 校验),全个股原始删、本地 ETF 删,Windows+网盘双备份。
- **2026-06-08(续2)L2 扩到 4 月全月 17 个连续交易日 + 全 Windows 存储。** 从 4 天扩到 **17 天**
  (0401–0424,除清明/周末),每天 panel scored 99.7%–100%。新增并行 ETL 基建(不改核心):
  `scripts/research/l6_parallel_etl.py`(multiprocessing,单天 34min→32核 ~5min)+
  `scripts/research/l6_wsl_batch.sh`(WSL 单天串行流水线,py7zr 解压→并行 ETL→xz 压缩归档→校验后
  删 .7z,幂等可重入)。跨主机:Mac 2 天 + WSL 11 天。**所有者原则「Mac 不做数据存储」已落实**:
  ETF L2 压缩归档 17 个/7.8G 全在 Windows `D:\qount_l2_archive\`(6 `.tar.zst`+11 `.tar.xz`),
  全个股 panel 17 天全在 WSL `state/research_runs/l6_daily_*`(Mac 6 天已迁入 WSL、本地删),源 .7z
  全删,Mac 纯编辑面零数据;WSL ext4 在 D 盘(372G free)。**下一步 D1 可正式做**:17 天=16 个
  T→T+1 截面(接近 20–40 天门槛),写跨日 ETF 截面 rank-IC + 符号稳 + 活跃子集 eff-breadth
  (先单测、本地→WSL),17 天 panel 已在 WSL 生产真相上可直接跑。硬约束全不变。
- **2026-06-08(续3)ETF 版 D1 跨日截面 IC kill-test:below_gate,但 close_auction 是首个真实显著
  信号。** 工具 `evaluate_l6_daily_d1` + 命令 `l6-daily-d1-scan`(local/WSL 367 OK)。17 天/16 截面
  实跑:**广度天花板经验证实**——ETF 截面 eff-breadth **1.69**(§7/L1/L3b 反复撞的 ~1.7),全个股
  **2.50**(印证主线选全个股,但 < L1 2.97)。**`close_auction_imbalance` = 项目首个真实、显著
  (t=-4.95)、符号稳(0.87)的日线 L2 信号**(收盘竞价买压→次日反转),ETF IC -0.037;按 Grinold
  breadth 1.69 → 要求 IC ≈0.049,实测 0.037=0.76×(接近不够),全个股要求 0.040/实测 0.017(广度高
  但信号弱)。四 universe 全 below_gate(DSR 0.36–0.62/PBO 0.27–0.43)。与 L3b 同型(真信号但广度封死)
  但没那么悲观:close_auction t 更硬、ETF 0.037 距要求仅 0.76×、且 **ETF T+0 可兑现**(个股 T+1 致命伤
  在 ETF 不存在)。16 天仍薄。下一步待所有者决策(攒天/D2 增量/D4 组合/深挖 close_auction/§7 停)。
- **2026-06-08(续4)D2 增量门:close_auction 在 ETF 上通过 —— 价量没有的真新信息(项目首次)。**
  工具 `evaluate_l6_daily_d2` + 命令 `l6-daily-d2-scan`(local/WSL 370 OK)。偏 rank-IC 控制 trailing
  收益(价量基线):ETF close_auction raw IC -0.036 → **控制价量后 partial IC -0.034(t-3.51)、保留
  94.6%**,价量基线自己 IC +0.019(t0.23,几乎无预测力),共线度仅 -0.04。**close_auction 是价量根本
  没有的真新信息,非换皮重测反转因子**。换信息源尝试里 L3b 信号被广度死、funding 弱,**close_auction
  是首个同过 D1(真实显著)+ D2(价量增量)的信号,核心假设「L2 真知情流 ≠ 价量」首次经验证实**。
  张力仍在:|IC| 0.036 < breadth(1.69)调整要求 0.049、14 截面偏薄。下一步待所有者决策(攒天 / D4
  多特征组合 / 深挖 close_auction 反转+ETF T+0 执行)。硬约束全不变,未碰 `validation_v1`。
- **2026-06-08(续5)D4 多特征线性组合:临界,接近但未干净突破。** 工具 `evaluate_l6_daily_d4` +
  命令 `l6-daily-d4-scan`(local/WSL 372 OK)。5 特征 z-score 符号对齐/IC 加权合成,对比广度调整要求
  `1/√(eff_breadth·250)≈0.049`:组合把信号从单 close_auction 0.036 抬到 **全体 ic_weighted 0.042
  (t4.15/sign0.81,但<0.049 且 in-sample 权重)/ 活跃top300 0.057(>0.048 破线但 t 仅 2.11)**;无
  「破线+t硬+全universe+非in-sample」四者兼得。**信号真实、组合有帮助,但量级卡在广度(1.69)要求
  0.049 临界线**,再次印证广度是绑定约束。16 截面薄、ic_weighted 需 purged-CV。下一步待所有者决策
  (攒天到~40+purged-CV / 接受临界按 §7 固化 / 深挖 close_auction+T+0 执行)。硬约束全不变。
- **2026-06-08(续6)D4 purged-CV 推翻 in-sample:组合提升是过拟合。** 给 D4 加 `--purged-cv`
  (leave-one-section-out+embargo)。WSL 实跑:**所有配置 OOS composite IC 崩到 ~0 甚至翻负**——ETF
  全体 ic_weighted in-sample 0.042(t4.15)→ **OOS -0.004(保留比 -0.09)**;sign_equal/top300 OOS 均
  翻负。**in-sample 0.042-0.057 几乎全是 16 截面权重选择的过拟合假象**(反过拟合 harness 的价值)。
  **修正净结论**:单 close_auction 真实(D1/D2 无权重选择)但量级 0.036<0.049;D4 组合救不了(引入
  权重选择即过拟合、OOS 崩);绑定约束仍是广度,组合突破这条路在现有数据上关闭。下一步待所有者决策
  (攒天到~40 / 深挖 close_auction 单信号+ETF T+0 执行 / 接受按 §7 同型固化停)。硬约束全不变。
- **2026-06-09 L2 数据从 17 天扩到 53 天(2/3/4 月)——D1「16 截面偏薄」解除。** 隔夜跑批管线
  (`scripts/research/l6_pipeline.sh`,external 消费模式)收下 2/3/4 月连续交易日,全个股日线 panel
  落 WSL `state/research_runs/l6_daily_*`,每天 scored 99.7%–100%。两个坏文件单独处理:**20260311**
  原 .7z 损坏(`LZMAError`)、重下后 DONE(scored 7487);**20260210** 是合法低标的日(稳定 5178,
  邻日 ~7500;ETF 归档空 116B=该日几无 T+0 ETF),加白名单 `LOW_OK_DATES` 放行、DONE。**panel 总数
  = 53 天 → D1 有 52 个 T→T+1 截面,远超 20–40 门槛**;之前续3–续6 的 D1/D2/D4 结论都建在 16 截面上,
  现在 close_auction 单信号(D1/D2 真实但量级 0.036<广度要求 0.049)与 D4 purged-CV 可在厚样本上正经
  重跑——这是下一步(尚未重跑)。**管线加固(只改运维脚本、不碰 `l6_microstructure.py`)**:四个失败
  分支(extract/etl/scored<6000/xz)从「原地留 .7z」改成移入 `$SRCDIR/_bad/`,根除坏文件让
  `processor` `while true` 死循环空转的 bug;新增 `LOW_OK_DATES` 低标的日白名单跳过 <6000 守卫。
  **运维坑(记 quick-handoff)**:`ssh → wsl.exe bash -lc 'tmux ...'` 起的后台进程不持久(ssh 一返回
  WSL 即回收),可靠做法是**前台阻塞跑**(ssh 全程挂着 = WSL 不回收)。硬约束全不变,research-only、
  未碰 `validation_v1`、未下单。
- **2026-06-09 L6 厚样本重测 + close_auction T+0 执行实测 → 撞回 maker 墙,所有者授权 L6 同型固化止盈。**
  ① **52 天 D1/D2/D4 重跑**:加厚样本把 close_auction 信号打回——ETF D1 IC 从 17 天 0.037 缩到 **0.021
  (t−3.38,符号 0.69)**,距广度要求(eff-breadth 1.85→0.046)从 0.76× 退到 **0.44×**;D2 增量仍过
  (控制价量后 partial 保留 103%,确属价量正交的真新信息);D4 组合 OOS(purged-CV)崩到 0.006/翻负。
  广度墙(~1.85)未动、信号离它更远。② **换问题做执行线 B**(`evaluate_l6_t0_execution` + 命令
  `l6-t0-exec-scan`,绕开 IR=IC√BR 截面下界):信号在 T 收盘竞价测得、最早 T+1 开盘可动 → 唯一可兑现
  是 T+1 open→close 日内 T+0。**把次日反转拆成隔夜/日内/收收**:发现 **收盘竞价买压→隔夜跳空续涨
  (IC+0.045/t8.5)→日内反转(IC−0.029/t4.5)**,D1 的 close-to-close(−0.019)是两段反向力量的净残值;
  `capturable_frac≈2`(只吃日内 T+0 比持有过夜好一倍,隔夜那段反向)。③ **实测成本定生死**(给特征加
  `day_open`/`quoted_spread_bps`、重 ETL 46 天 ETF panel):日内 gross +7.6~9.9bp(t>2.4)真实,但
  **交易尾价差 ~13–14bp → taker 往返成本 ~31bp → net −23bp(t−7),taker 彻底死**;唯一"幸存"的竞价
  撮合(仅佣金)net +2.6/+4.9bp 但 **t<1.3 不显著**。**价差-信号陷阱**:信号活在不流动 ETF(强尾价差
  14.4bp/gross+9.9bp),一上流动 top100(价差 5.7bp)信号塌成 +2.3bp/t0.26——**edge 本质是薄 ETF 的
  流动性提供溢价,taker 拿不走;要拿只能做 maker = L4/§3-Phase4 的 maker 墙**。④ **净结论**:close_auction
  是项目迄今最干净的信号(真实+显著+价量正交+隔夜/日内结构清楚),但不可 taker 兑现、edge=流动性溢价、
  收敛到已知撞死的 maker 墙。**所有者授权 A:B 诚实止盈、L6 与 §7/L1/L3b/L4 同型固化**(stop investing,
  不放宽任何纪律:live 关闭、不 forward paper、不放宽 broad gate、`validation_v1` once-only 保留)。
  沉淀=D0–D4 + T0 隔夜/日内分解 + 实测 taker/auction 成本的反过拟合 harness。artifact
  `state/research_runs/20260609T065032Z/065033Z-l6-t0-exec-scan`。计划见
  [l6-microstructure-plan.md](l6-microstructure-plan.md) §5。

## 当前能力

已经具备：

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

- 稳定盈利能力证明。
- forward paper 许可。
- live 许可。
- 已通过 validation 的可复用窄 candidate gate。
- 已验证的 AI prompt v2/v3 改进。
- 多币 promotion gate。
- S1' 可 promotion 的稳定胜出 cell；目前 120 天 discovery / 月度 sanity 没有稳定胜者。
- Kronos 接入候选层或执行层。

## 最新策略读数

2026-06-05 已完成 S1' 第一版工具和 30 天 discovery 初扫：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T065952Z-strategy-selection-scan-qount-strategy-selection-s1-30d-20260605/qount-strategy-selection-s1-30d-20260605.json
holdout_role=discovery
window=2026-05-02T00:00:00Z..2026-06-01T00:00:00Z
symbols=SOL/XRP/BTC/ETH USDT futures
frequencies=5m,1h,4h,1d
families=xs_mom,xs_rev,ts_mom,carry
best_cell=1d ts_mom
best_sum_return_pct=+0.3121233665
best_mean_return_pct=+0.0025171239
best_sharpe=2.2679849920
best_rank_ic_mean=+0.0085476003
best_effective_breadth=1.1323823788
5m_xs_rev_rank_ic_mean=+0.0289588724 but post-cost sum=-20.6197925003
carry_sum_return_pct=-0.1147211
```

读法：这是 discovery baseline，不是 promotion。初扫支持“5m 成本主导”的判断：
5m `xs_rev` 有正 rank-IC/t-stat，但每 5m 换手后 post-cost 大幅为负；30 天内 CARRY
在当前朴素“方向翻转即付成本”的口径下也为负。唯一正的 top cell 是 `1d ts_mom`，但
rank-IC 很弱、有效广度约 1.13，下一步只能继续做更长 discovery 扫描和参数/成本口径
健壮性检查，不能进入 S2/S3 或 forward paper。

随后用 120 天 discovery 和成本/月份 sensitivity 复核，`1d ts_mom` 不稳定：

```text
120d_full_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T070504Z-strategy-selection-scan-qount-strategy-selection-s1-120d-full-lb12-h1-20260605/qount-strategy-selection-s1-120d-full-lb12-h1-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
best_cell=1d ts_mom
sum_return_pct=-0.3885499348
mean_return_pct=-0.0008027891
sharpe=-0.4637426827
rank_ic_mean=-0.0524746039
effective_breadth=1.0810517903

1d_lbp3_h1_best=xs_rev sum=-0.0652799064
1d_lb12_h3_best=ts_mom sum=+0.5824374867 sharpe=+0.4579358431
1d_lb24_h1_best=ts_mom sum=-0.0867584111
```

月度分段（`1d ts_mom lb12/h1`）：

```text
Feb sum=+0.1023244575 sharpe=+0.3227715436 ic=-0.0267942952
Mar sum=-0.4297008569 sharpe=-2.2922293236 ic=-0.2166041018
Apr sum=-0.4340789583 sharpe=-2.8870027003 ic=-0.1636003147
May sum=+0.3233152390 sharpe=+2.3098638880 ic=+0.0316906244
```

成本压力：

```text
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T070712Z-strategy-selection-scan-qount-strategy-selection-s1-120d-5m-xsrev-carry-zero-cost-20260605/qount-strategy-selection-s1-120d-5m-xsrev-carry-zero-cost-20260605.json
zero_cost_5m_xs_rev_sum=+1.2386542488
zero_cost_carry_sum=+0.0824606

maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T070835Z-strategy-selection-scan-qount-strategy-selection-s1-120d-5m-xsrev-carry-maker-ish-20260605/qount-strategy-selection-s1-120d-5m-xsrev-carry-maker-ish-20260605.json
maker_ish_cost_per_directional_bet=0.0004
maker_ish_5m_xs_rev_sum=-26.4101457512
maker_ish_carry_sum=-0.0999394
```

读法：30 天 `1d ts_mom` 正收益主要是 2026-05 单月趋势贡献，120 天和 2/3/4 月不支持
它作为稳定 S2/S3 入口。5m 和 CARRY 都有 gross edge，但很薄，maker-ish 成本后转负；
当前不能把任何 cell 提升为 S2/S3 或 S-CARRY。下一步应先改进 carry 真实双腿/阈值模型
和扩大 universe，而不是上 GBDT。

2026-06-05 已补 `strategy-selection-scan` OHLCV 列回归测试，锁定 ccxt 输入列必须保持
`[timestamp, open, high, low, close, volume]`，避免把 `low` 当 `close`。本地和 WSL
全量测试随后升级为 `227 OK`。用同一生产 WSL 环境复跑 120 天 S1'，核心结论不变：
`1d ts_mom` 仍是排序上的 best cell，但 `sum=-0.3885499348`、`sharpe=-0.4637426827`、
`rank_ic=-0.0524746039`，decision 为 `no_positive_cell`。zero-cost 下 5m `xs_rev`
`+1.2386542488`、CARRY `+0.0824606`；maker-ish
`cost_per_directional_bet=0.0004` 后分别为 `-26.4101457512`、`-0.0999394`。

2026-06-05 已推进 S-CARRY 第一刀：`strategy-selection-scan` 增加显式
`--carry-model threshold_dual_leg`，只在 research 命令使用，默认 `naive` 不变。该模型加入
funding entry/exit 阈值、最短持仓周期、双腿开/平/换腿成本。120 天 4 币复跑：
zero-cost 为 `+0.04728436`，maker-ish `cost_per_directional_bet=0.0004` 后为
`-0.16871564`，说明阈值过滤保留了部分 gross cashflow，但当前 4 币/阈值/成本下仍不能进
S-CARRY paper。

2026-06-05 继续推进 S-CARRY 固定 discovery 网格和资金占用读数：grid =
entry `0.00004/0.00008/0.00012` × exit `0.00002/0.00004` × min-hold `1/3/6`。
本地和 WSL 全量测试升级为 `228 OK`。120 天 4 币 zero-cost grid best 为
entry `0.00004` / exit `0.00002` / min-hold `1`，`sum=+0.07147182`，
`utilization=0.6715`，双腿平均 gross exposure `1.3431`。同一 grid maker-ish best 为
entry `0.00012` / exit `0.00002` / min-hold `6`，`sum=-0.02967449`，
`utilization=0.2708`，双腿平均 gross exposure `0.5417`。Binance funding history
当前没有返回可用 mark/index 历史，`basis_sample_count=0`；basis 风险仍需单独数据源。
结论：固定 grid 后仍不能 paper；成本是主要瓶颈，下一步应扩大 universe 和补 basis 数据，
不是在 4 币已看窗口上继续挑阈值。

2026-06-05 已补 CARRY basis 数据源第一版：`strategy-selection-scan` 增加显式
`--carry-basis-source premium_index`，通过 ccxt `fetch_premium_index_ohlcv` 拉 Binance
8h premium index kline，并按 funding 8h bucket 合并到 CARRY cell 的 basis 诊断字段。
本地和 WSL 全量测试升级为 `229 OK`。120 天 4 币 maker-ish fixed grid 复跑：
`premium_index_8h` 每币 361 根；best cell 仍为 entry `0.00012` / exit `0.00002` /
min-hold `6`，`sum=-0.02967449`、`utilization=0.2708`、双腿平均 gross exposure
`0.5417`；basis 诊断从 0 样本变成 `basis_sample_count=390`、
`basis_avg_abs=0.0005576725`、`basis_max_abs=0.00143783`。结论不变：basis 数据已接入，
但 4 币 maker-ish 成本后仍不能 S-CARRY paper。

2026-06-05 已按下一步扩大 CARRY universe 到 12 币：
`BTC/ETH/ZEC/SOL/HYPE/WLD/XRP/BNB/NEAR/DOGE/ADA/SUI` USDT perpetuals。120 天 top12
premium basis fixed grid 读数：

```text
maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083609Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605.json
maker_ish_best_entry=0.00012
maker_ish_best_exit=0.00002
maker_ish_best_min_hold=6
maker_ish_sum=-0.07594874
maker_ish_turnover_events=221
maker_ish_utilization=0.2816239316
maker_ish_avg_dual_leg_gross_exposure=0.5632478632
maker_ish_basis_sample_count=1318
maker_ish_basis_max_abs=0.00265777
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083859Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605/qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605.json
zero_cost_best_entry=0.00004
zero_cost_best_exit=0.00002
zero_cost_best_min_hold=1
zero_cost_sum=+0.27826189
zero_cost_turnover_events=2104
zero_cost_utilization=0.6970085470
zero_cost_avg_dual_leg_gross_exposure=1.3940170940
```

读法：扩币后 zero-cost gross funding cashflow 明显转强，说明 S-CARRY 仍是有效研究方向；
但 maker-ish `cost_per_directional_bet=0.0004` 后所有 grid cell 仍为负，best cell 只有 WLD
单币为正（`+0.03113714`），组合仍不能 paper。下一刀不应继续在同一 discovery grid 上挑参数，
而应做显式 hedge / spot-perp 双腿执行、post-only 成交率、资金占用和 basis 风险 replay。

2026-06-05 已补 explicit spot/perp 资金占用口径：`strategy-selection-scan` 增加显式
`--carry-execution-cost-model per_order`、`--carry-capital-model spot_perp_gross`、
`--carry-perp-margin-fraction`。默认仍是旧 `directional_round_trip + perp_notional`，所以旧
artifact 口径不变。本地和 WSL 全量测试升级为 `230 OK`。top12 同 grid 用 6x perp margin
fraction `0.1666667` 复跑：

```text
explicit_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605.json
execution_cost_model=per_order
capital_model=spot_perp_gross
perp_margin_fraction=0.1666667
order_cost=0.0002
best_entry=0.00012
best_exit=0.00002
best_min_hold=6
sum=+0.0106725083
sharpe=+0.7275658326
turnover_events=221
gross_funding_return=+0.0864439347
execution_cost_sum=+0.0757714264
cost_to_gross_ratio=0.8765383794
break_even_order_cost=0.0002281703
positive_cells=3/18
basis_max_abs=0.00265777
```

成本压力：同口径把 per-order cost 提到 `0.00025` 后，best cell 立即转负：

```text
cost025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085742Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605.json
order_cost=0.00025
best_sum=-0.0082703483
best_sharpe=-0.5083163356
break_even_order_cost=0.0002281703
```

读法：显式 spot/perp 口径把 S-CARRY 从“旧保守成本下全负”推进到“有一个小正候选”，但
成本缓冲只有约 `0.00002817` per order，且 `basis_max_abs=0.00265777` 明显大于净收益边际。
这仍不能 paper；下一步必须先做 post-only 成交率 / 实测订单成本 / basis tail 风险压力，
并用独立窗口验证，不能把这个 discovery best cell 当 promotion。

2026-06-05 已给 `strategy-selection-scan` 补显式 `--holdout-role`，并用已选定 top12
explicit spot/perp best cell 跑一个新的 1 天 `validation_v1` 固定窗口
`2026-06-04T00:00:00Z..2026-06-05T00:00:00Z`。这是固定参数检查，不重新 grid search。

```text
val_jun04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103552Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605.json
holdout_role=validation_v1
sample_count=51
order_cost=0.0002
sum=+0.0003597343
sharpe=+2.6637283960
turnover_events=4
gross_funding_return=+0.0017311628
execution_cost_sum=+0.0013714285
cost_to_gross_ratio=0.7922007833
break_even_order_cost=0.0002524613
basis_sample_count=14
basis_max_abs=0.00235832

val_jun04_cost025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103620Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605.json
order_cost=0.00025
sum=+0.0000168771
sharpe=+0.1072893774
cost_to_gross_ratio=0.9902509791
```

读法：独立窗口没有立即证伪 top12 CARRY best cell，但证据极薄：只有 51 条 funding 样本、
4 个 entry events，`order_cost=0.00025` 时几乎完全贴近 break-even，且 `basis_max_abs`
仍远大于净收益。它最多支持继续做 post-only / 实测成本 / basis-tail 验证，仍不能 paper。

随后复跑同一固定窗口，只新增 basis-tail 诊断字段，不改变 PnL 计算：

```text
val_jun04_basis_tail_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T104512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605.json
holdout_role=validation_v1
sample_count=51
order_cost=0.0002
sum=+0.0003597343
basis_max_abs=0.00235832
basis_single_tail_loss_on_capital=0.0020214171
basis_single_tail_to_net_ratio=5.6191951202
portfolio_sum_after_single_basis_tail=-0.0016616828
```

读法：1 天 fixed-cell 的小正收益会被同窗口观察到的一次 basis tail 压力直接抹掉并转负，
tail/net 比例约 `5.62x`。这把 S-CARRY 当前状态从“需要 basis-tail 验证”推进为
“basis-tail 已经证伪当前 paper 资格”。下一刀不能 promotion，只能先做 post-only fill /
真实订单成本和 basis-tail-aware hedge / exit 模型。

2026-06-05 继续补了显式 `--carry-basis-tail-stop-pct`，只在 research scan 中启用；默认
`None`，历史 artifact 口径不变。本地和 WSL 全量测试升级为 `231 OK`。同一 1 天
`validation_v1` fixed-cell 跑三个 simple basis stop：

```text
stop001_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105545Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605.json
stop=0.0010
sum=-0.0008075743
basis_tail_stop_events=2
basis_max_abs=0.00081857
after_single_basis_tail=-0.0015092057

stop0015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105616Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605.json
stop=0.0015
sum=-0.0004218600
basis_tail_stop_events=1
basis_max_abs=0.00112691
after_single_basis_tail=-0.0013877828

stop0020_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105622Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605.json
stop=0.0020
sum=-0.0004218600
basis_tail_stop_events=1
basis_max_abs=0.00112691
after_single_basis_tail=-0.0013877828
```

读法：simple basis stop 能降低持仓期最大 basis 暴露，但新增退出成本和少收 funding 后，
三个阈值都把 fixed-cell 从小正变成负收益。当前不能靠单一 hard stop 解决 S-CARRY；
下一步只能继续做 post-only fill / 实测订单成本，或更细的 symbol/filter 与 hedge timing，
不能 paper。

2026-06-05 继续做只读成本和 symbol/filter 复核。`execution-cost-audit --limit 200`
只找到 4 笔历史 live 市价单可分析，fee 缺失；实际 abs slippage 中位约 `0.0441%`，
高于 S-CARRY fixed-cell 假设的 `0.0200%` per-order。按 120 天 discovery 逐币贡献，
只有 `WLD/SOL/ZEC` 为正，其中 ZEC 的 discovery after-tail 已为负；tail-aware 过滤后
只保留 `WLD/SOL`：

```text
wld_sol_discovery_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110031Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
sum=+0.0378574446
after_single_basis_tail=+0.0355793561
break_even_order_cost=0.0006330100

wld_sol_val_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110033Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
sum=+0.0000535886
after_single_basis_tail=-0.0006480428
break_even_order_cost=0.0002312600

wld_sol_val_cost025=/home/alyaloale/Code/qount/state/research_runs/20260605T110109Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605.json
order_cost=0.00025
sum=-0.0000321257

wld_sol_val_cost045=/home/alyaloale/Code/qount/state/research_runs/20260605T110114Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605.json
order_cost=0.00045
sum=-0.0003749828
```

读法：WLD/SOL 是当前最像样的 S-CARRY filter 方向，120 天 discovery 在成本和 after-tail
上都更健康；但 1 天 sanity 只有 SOL 成交，after-tail 仍为负，且成本 `0.00025` 就转负。
历史 live slippage 样本还提示真实 taker 成本可能更高。结论仍是不 paper；下一刀应先证明
post-only / maker fill 能把 per-order 成本压到 `0.000231` 以下，或继续找更多独立日期验证
WLD/SOL 是否稳定，而不是扩大到 live。

同日继续拆 WLD/SOL 的 discovery 月度稳定性和 6 月逐日读数，全部不作为 promotion：

```text
wld_sol_feb=/home/alyaloale/Code/qount/state/research_runs/20260605T111620Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-feb-20260605/qount-strategy-selection-s-carry-wld-sol-feb-20260605.json
sum=+0.0040478056
after_tail=+0.0028153799

wld_sol_mar=/home/alyaloale/Code/qount/state/research_runs/20260605T111622Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-mar-20260605/qount-strategy-selection-s-carry-wld-sol-mar-20260605.json
sum=+0.0028695942
after_tail=+0.0017230457

wld_sol_apr=/home/alyaloale/Code/qount/state/research_runs/20260605T111625Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-apr-20260605/qount-strategy-selection-s-carry-wld-sol-apr-20260605.json
sum=+0.0190945623
after_tail=+0.0168164738

wld_sol_may=/home/alyaloale/Code/qount/state/research_runs/20260605T111627Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-may-20260605/qount-strategy-selection-s-carry-wld-sol-may-20260605.json
sum=+0.0119759397
after_tail=+0.0104161540

wld_sol_jun01_04=/home/alyaloale/Code/qount/state/research_runs/20260605T111629Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605.json
holdout_role=discovery
sum=+0.0003015686
after_tail=-0.0004000628

wld_sol_jun05_partial=/home/alyaloale/Code/qount/state/research_runs/20260605T111654Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605.json
holdout_role=unknown
sample_count=4
sum=-0.0002471743
after_tail=-0.0003076628
```

读法：WLD/SOL 在 2-5 月 discovery 每月 after-tail 都为正，但 4/5 月主要靠 WLD；6/1-6/4
已看窗口 after-tail 转负，6/5 partial 也为负且样本太少。这个 filter 仍值得观察，但现在的
真实下一步是等待新的完整独立日期，或先解决 maker/post-only 成本；不能继续拿 6/1-6/5
调参后声称 validation。

用户明确要求“不等完整独立日期”后，继续推进 maker/post-only 成本证明。2026-06-05 已补
research-only post-only economics 诊断：`--carry-maker-order-cost-pct` /
`--carry-taker-order-cost-pct` 只计算所需 maker fill rate，不改变 PnL。本地和 WSL 全量测试
升级为 `232 OK`。用 maker cost `0`、taker cost `0.00045`（接近历史 live 市价单 slippage
中位）跑 WLD/SOL：

```text
wld_sol_discovery_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113704Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
after_tail=+0.0355793561
required_maker_fill_after_tail=0.0
after_tail_feasible=true

wld_sol_jun01_04_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113706Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605.json
window=2026-06-01T00:00:00Z..2026-06-05T00:00:00Z
after_tail=-0.0004000628
required_maker_fill_after_tail=1.0741555556
after_tail_feasible=false

wld_sol_jun05_partial_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113709Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605.json
holdout_role=unknown
after_tail=-0.0007569857
required_maker_fill_after_tail=1.0461944444
after_tail_feasible=false
```

读法：maker/post-only 能解释 120 天 discovery 的成本可行性，但不能拯救 6/1-6/5 的
after-tail 亏损；已看窗口 after-tail 为正需要超过 100% maker fill，数学上不可行。下一步
不应继续成本调参，而应进入更细的 hedge timing / basis regime filter，或转向次优路线
1d TS-MOM 扩 universe。

同日继续按下一步做 WLD/SOL basis regime filter。`strategy-selection-scan` 新增显式
research-only `--carry-basis-entry-max-abs-pct`，只在 CARRY 新入场时阻止 basis 已经偏离
过大的交易，默认关闭，不影响 live / `run-once`。本地和 WSL 全量测试升级为 `233 OK`。
用 WLD/SOL fixed cell 跑三个 entry basis 阈值：

```text
basis_entry_max_abs=0.0008
discovery120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114908Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00008-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00008-20260605.json
discovery120d_sum=-0.0066684341
discovery120d_after_tail=-0.0083560026
discovery120d_blocked_entries=19
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114911Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00008-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00008-20260605.json
jun01_04_sum=-0.0003841457
jun01_04_after_tail=-0.0010857771
jun01_04_required_maker_after_tail=1.0741555556

basis_entry_max_abs=0.0010
discovery120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114914Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00010-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00010-20260605.json
discovery120d_sum=-0.0010824000
discovery120d_after_tail=-0.0028620256
discovery120d_blocked_entries=8
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114917Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00010-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00010-20260605.json
jun01_04_sum=-0.0003841457
jun01_04_after_tail=-0.0010857771
jun01_04_required_maker_after_tail=1.0741555556

basis_entry_max_abs=0.0015
discovery120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114920Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00015-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00015-20260605.json
discovery120d_sum=+0.0020099742
discovery120d_after_tail=+0.0002303486
discovery120d_blocked_entries=2
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114922Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00015-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00015-20260605.json
jun01_04_sum=-0.0003841457
jun01_04_after_tail=-0.0010857771
jun01_04_required_maker_after_tail=1.0741555556
```

读法：entry-only basis filter 不能救 WLD/SOL。0.0008 / 0.0010 在 120 天 discovery 上已转负；
0.0015 只剩极薄正收益，而且 6/1-6/5 已看窗口完全不改善，after-tail 仍负且需要超过 100%
maker fill。这个 filter 只能保留为 rejected/diagnostic，不进入 paper。

随后转向备选路线：扩大 `1d ts_mom` universe 到同一 top12。结果比 4 币更差：

```text
top12_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114959Z-strategy-selection-scan-qount-strategy-selection-s1-tsmom-top12-120d-20260605/qount-strategy-selection-s1-tsmom-top12-120d-20260605.json
symbols=12
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
sum=-2.6698947371
mean=-0.0018387705
sharpe=-0.7852540386
rank_ic=-0.0517447570
effective_breadth=1.4732977614

feb_sum=-0.9962962887 sharpe=-0.9621629776 ic=-0.0674655117
mar_sum=-1.0361457305 sharpe=-1.3703927744 ic=-0.1333032818
apr_sum=-1.2542758681 sharpe=-1.9515156302 ic=-0.1175958164
may_sum=+0.7414512205 sharpe=+0.7641721588 ic=+0.0031381398
```

读法：top12 扩币没有给 `1d ts_mom` 提供稳定候选；2/3/4 月全负，5 月单月正但 IC 接近 0。
这条线不能进 S1.1/S1.2，更不能 paper。当前可行动方向缩到两类：等新的完整独立日期复核
WLD/SOL carry 是否恢复，或离开当前 S-CARRY/TS-MOM 两条 discovery best，重新做更宽的
strategy-family / universe / 执行约束设计。

同日继续把 S1' 扩成多 horizon 网格。`strategy-selection-scan` 新增
`--signal-lookback-grid-bars` / `--holding-grid-bars`，只影响 research scan 的预测族 cell
展开，默认行为不变。本地和 WSL 全量测试升级为 `235 OK`。低频 top12 网格：
`1h/4h/1d` × `xs_mom/xs_rev/ts_mom` × lookback `3/12/24` × holding `1/3/6`，120 天
discovery 读数如下：

```text
lowfreq_grid_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121551Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605/qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605.json
cell_count=81
best_cell=4h xs_mom lookback=24 holding=6
sum=+3.5251307739
mean=+0.0048892244
sharpe=+7.1555415974
rank_ic=+0.0523457125
turnover_events=4326
sample_count=8652

top2=4h xs_mom lookback=12 holding=6 sum=+3.2301871618 sharpe=+7.0705584839 ic=+0.0449501019
top3=1d xs_mom lookback=24 holding=6 sum=+2.9144790792 sharpe=+5.3167601423 ic=+0.0376682141
```

固定 best cell 月度 sanity：

```text
feb_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121631Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-feb-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-feb-20260605.json
feb_sum=+0.0054374620 sharpe=+0.0534812097 ic=-0.0258203335
mar_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121636Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-mar-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-mar-20260605.json
mar_sum=-0.3056398179 sharpe=-2.9328919686 ic=-0.0228488089
apr_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121640Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-apr-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-apr-20260605.json
apr_sum=+0.9769441561 sharpe=+11.6825529071 ic=+0.0950044431
may_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121645Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-may-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-may-20260605.json
may_sum=+2.8938136721 sharpe=+16.4429358388 ic=+0.1603904117
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121653Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-jun01_04-20260605.json
jun01_04_sum=+0.2839507666 sharpe=+6.4057144483 ic=+0.1217418945
```

Top-fraction sensitivity（同一 fixed cell，120 天 discovery）：

```text
top010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121834Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-top010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-top010-20260605.json
top_fraction=0.10 sum=+5.4599023538 sharpe=+5.9026198051 turnover=1442
top025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121839Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-top025-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-top025-20260605.json
top_fraction=0.25 sum=+3.5251307739 sharpe=+7.1555415974 turnover=4326
top050_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121846Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-top050-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-top050-20260605.json
top_fraction=0.50 sum=+1.3829792744 sharpe=+4.5968178554 turnover=8652
```

随后补 overlap sanity：`strategy-selection-scan` 增加显式
`--directional-overlap-mode all|stride`，默认 `all` 保持旧读数；`stride` 每个 holding
window 只取一次 cross-section，先降低 `holding=6` 的重叠 horizon 膨胀。本地和 WSL 全量测试
均为 `236 OK`。同一 fixed best 的 stride 读数：

```text
stride_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T123357Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605.json
stride_120d_sum=+0.5087944384
stride_120d_sharpe=+6.0811826595
stride_120d_rank_ic=+0.0607409120
stride_120d_cross_sections=121
stride_feb_sum=-0.0026969105 sharpe=-0.1324295271 ic=-0.0195321919
stride_mar_sum=-0.0234895413 sharpe=-1.1990799524 ic=-0.0039335664
stride_apr_sum=+0.0796046219 sharpe=+6.1468061927 ic=+0.1037672005
stride_may_sum=+0.5008009667 sharpe=+17.4927001500 ic=+0.1761363636
stride_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T123424Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605.json
stride_jun01_04_sum=+0.0627083513
stride_jun01_04_sharpe=+6.9612473463
stride_jun01_04_cross_sections=4
```

随后补第一版限仓 portfolio replay：`--directional-evaluation-mode portfolio_replay`，
`--directional-max-open-positions 12`，同一 fixed best、top12 universe、4h、lb24/h6、
top_fraction `0.25`，仍为 research-only。本地和 WSL 全量测试均为 `236 OK`。

```text
portfolio_replay_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T125713Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605.json
portfolio_replay_120d_sum=+0.2974912983
portfolio_replay_120d_sharpe=+7.1945433715
portfolio_replay_120d_max_dd=0.0876673733
portfolio_replay_120d_trades=1446
portfolio_replay_120d_skipped=2880
portfolio_replay_120d_win_rate=0.4951590595
portfolio_replay_feb_sum=+0.0062629159 sharpe=+0.6960748519
portfolio_replay_mar_sum=-0.0094161679 sharpe=-1.0453679061
portfolio_replay_apr_sum=+0.0656249961 sharpe=+9.4341419585
portfolio_replay_may_sum=+0.2463757288 sharpe=+16.7819812990
portfolio_replay_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T125741Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605.json
portfolio_replay_jun01_04_sum=+0.0082009038
portfolio_replay_jun01_04_sharpe=+2.2971433970
```

读法：这是今天第一个像样的 prediction-family candidate。它在 stride sanity 和限仓
portfolio replay 下都保持 120 天聚合正收益，说明不是纯重叠 horizon 幻觉；但 2026-03
月度 replay 仍为负，2 月也只是微正，`jun01_04` 只是已看窗口 sanity，不能当 promotion。
继续补 triple-barrier：`--directional-exit-mode triple_barrier` 使用 holding window 内 OHLC
高低点触发 TP/SL，默认 `close` 不变。固定同一 top12 / 4h / lb24/h6 /
portfolio_replay / max_open_positions `12`，120 天扫 4 个简单 TP/SL 组合：

```text
triple_tp015_sl010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132052Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.015-sl0.010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.015-sl0.010-20260605.json
triple_tp015_sl010_sum=-0.2542260860 sharpe=-21.9420203800
triple_tp020_sl010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132057Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.010-20260605.json
triple_tp020_sl010_sum=-0.2307013696 sharpe=-16.8127315231
triple_tp020_sl015_sum=-0.2296270771 sharpe=-14.6592774682
triple_tp030_sl015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132109Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605.json
triple_tp030_sl015_sum=-0.1635040433 sharpe=-8.7264450618
```

用最不差的 TP `0.030` / SL `0.015` 做月度拆分：

```text
triple_exit_reason_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132953Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605.json
triple_120d_exit_counts=stop_loss 873, take_profit 400, time 173
triple_120d_win_rate=0.3443983402
triple_feb_sum=-0.0356452182 sharpe=-7.8031867350
triple_feb_exit_counts=stop_loss 224, take_profit 110, time 8
triple_mar_sum=-0.0631122398 sharpe=-12.6468869769
triple_mar_exit_counts=stop_loss 242, take_profit 107, time 29
triple_apr_sum=-0.0812657295 sharpe=-17.4805448327
triple_apr_exit_counts=stop_loss 211, take_profit 73, time 82
triple_may_sum=+0.0203985601 sharpe=+4.3481178441
triple_may_exit_counts=stop_loss 205, take_profit 116, time 57
triple_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132208Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605.json
triple_jun01_04_sum=+0.0177000000
```

读法：`4h xs_mom` 不是纯重叠 horizon 幻觉，但简单 fixed TP/SL triple-barrier 已经否定当前
paper 资格：120 天四个 barrier 组合全负，最不差组合也只有 5 月和已看 6 月为正，2/3/4 月
全负。原因不是 rank-IC 完全消失，而是固定 barrier 的路径执行失败：120 天 stop-loss 触发
`873` 次、take-profit `400` 次、到期 `173` 次，止损约为止盈 `2.18x`，再叠加 per-trade
成本后把 close-to-close/replay 正收益吃掉。当前下一步只能做 purged-CV / exit 设计 / 新
OOS，不能 paper，也不要继续盲扫简单 TP/SL。

随后补 fixed-cell purged/embargo CV 诊断：`strategy-selection-scan` 新增显式
research-only `--directional-purged-cv-folds` / `--directional-embargo-bars`，默认关闭，
不影响 live / `run-once` / CARRY。固定 top12、`4h xs_mom`、lookback `24`、holding `6`、
`portfolio_replay`、`max_open_positions=12`、close exit，4 fold + 6 bars embargo：

```text
purged_cv_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T133904Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605.json
full_sum=+0.2974912983
full_sharpe=+7.1945433715
positive_folds=3/4
mean_fold_sum=+0.0743728246
min_fold_sum=-0.0566596009
fold1_2026-02-01_to_2026-03-02=+0.0467298450
fold2_2026-03-03_to_2026-04-01=-0.0566596009
fold3_2026-04-02_to_2026-05-01=+0.0611460588
fold4_2026-05-02_to_2026-06-01=+0.2462749954
```

读法：purged/embargo artifact 已能机器化记录 fold 稳定性，但仍未过 paper 前置。
3/4 folds 为正说明 candidate 仍值得研究；`2026-03-03..2026-04-01` fold 为负且 IC 为负，
说明收益仍明显依赖后段行情。下一步不再重复 close/replay/purged sanity，而是做更稳健的
exit 设计、模型层 purged-CV，或等待新的完整 OOS 日期。

2026-06-05 已按 §11.5 N1 做"波动率缩放 barrier"(simple fixed TP/SL 已证不行,不再重复)：
`strategy-selection-scan` 新增 research-only `--directional-barrier-vol-lookback-bars` /
`--directional-take-profit-sigma` / `--directional-stop-loss-sigma`，把 triple-barrier 的
TP/SL 从固定百分比改为按"决策时点近 N 根 bar 已实现收益 σ"缩放，默认关闭、live /
`run-once` / CARRY 不变。本地和 WSL 全量测试升级为 `240 OK`。固定同一 `4h xs_mom lb24/h6`、
top12、portfolio_replay、`max_open=12`、vol lookback `24`、120 天 discovery，扫 σ 倍率：

```text
artifact_dir=/home/alyaloale/Code/qount/state/research_runs/20260605T1410*-...-volbarrier-*-120d-20260605
close_exit_baseline_sum=+0.2974912983 (无 barrier，既有 replay 读数)
tp1.5/sl1.5 sum=-0.143287 sharpe=-5.9154 SL=643 TP=635 TIME=168
tp2.0/sl2.0 sum=-0.050339 sharpe=-1.8044 SL=514 TP=544 TIME=388
tp3.0/sl2.0 sum=+0.037766 sharpe=+1.2470 SL=539 TP=339 TIME=568
tp3.0/sl3.0 sum=+0.118739 sharpe=+3.8430 SL=303 TP=360 TIME=783
tp4.0/sl4.0 sum=+0.165134 sharpe=+4.7454 SL=192 TP=222 TIME=1032
```

最佳 `tp4.0/sl4.0` 月度（同 fixed cell，每月独立窗口）：

```text
feb_sum=+0.034363 sharpe=+4.3075 ic=-0.02582
mar_sum=-0.039638 sharpe=-4.7000 ic=-0.02285
apr_sum=+0.032380 sharpe=+5.2807 ic=+0.09500
may_sum=+0.149386 sharpe=+12.8808 ic=+0.16039
```

读法：vol-scaling 确实改掉了 fixed barrier 的非对称止损病(fixed `tp0.030/sl0.015` 是
stop-loss `873` / take-profit `400`，约 `2.18x`；vol `tp2/sl2` 已收敛到 `514/544` 接近 1:1)，
且 PnL 随 barrier 加宽单调改善。但**没有任何 σ 设置能跑赢"无 barrier 持有到期"的 close-exit
基线 `+0.2974912983`**：barrier 越宽，越多仓位以 `time` 退出、越接近 close 基线，最佳
`tp4/sl4` 也只有 `+0.165134`，仍低于 close。月度上最佳 barrier 的 3 月仍为负、约 90% 收益
来自 5 月单月，单月依赖未改善，且全部是已看过的 120 天 discovery。结论：N1 门控未通过——
可执行 path-dependent exit 仍未跑赢持有，且无月度稳健性;**不进 S2**。下一刀只能等新的完整
独立 OOS 日期复核，或做更细的持仓管理(部分止盈/移动止损/regime 过滤),不能 paper。

2026-06-05 继续按 N1 做 entry 侧 **regime dispersion 门**(part/移动止损本质仍是已被证伪的
路径 exit,故选未被排除的 entry 过滤):`strategy-selection-scan` 新增 research-only
`--directional-regime-min-dispersion-pct`，在每个 cross-section 上计算各币 signal 的离散度
(sample std,纯决策时点),低于阈值就跳过该 bar(同涨同跌、无相对强弱 = 不下注)。默认关闭,
live / `run-once` / CARRY / ts_mom 不变。本地和 WSL 全量测试升级为 `241 OK`。该候选 120 天
每根 bar 的 dispersion 分布 p25/p50/p75 = `0.034/0.048/0.068`。固定同一 `4h xs_mom lb24/h6`、
top12、close-exit、portfolio_replay、`max_open=12`，120 天 discovery 扫阈值：

```text
thr0.000 sum=+0.297491 sharpe=+7.1945 dd=0.0877 gated=0   traded=721 win=0.4952
thr0.034 sum=+0.298812 sharpe=+7.9989 dd=0.0798 gated=178 traded=543 win=0.5119
thr0.048 sum=+0.272640 sharpe=+8.9771 dd=0.1021 gated=356 traded=365 win=0.4940
thr0.068 sum=+0.195078 sharpe=+11.8154 dd=0.0527 gated=539 traded=182 win=0.4953
```

`thr0.034`(跳过最低 ~25% dispersion bar)月度，对比无过滤 close-exit 基线：

```text
feb_sum=+0.024688 ic=-0.00846  (baseline +0.0063)
mar_sum=+0.002786 ic=-0.00387  (baseline -0.0094 → 翻正)
apr_sum=+0.063078 ic=+0.10121
may_sum=+0.246376 ic=+0.16039
```

读法：这是 N1 里第一个**在正确的轴上**改善候选的子步骤。`thr0.034` 总收益不变
(`+0.298812` vs `+0.297491`)、Sharpe `7.19→8.00`、回撤 `0.088→0.080`、换手更少,而且把
**2026-03 从负翻正**、4 个月全部 ≥ 0——直接打到"月度全靠单月"的门控失败点。`thr0.068`
过滤太狠,2/3 月又转负。但仍有两条硬保留:(1) 阈值是在同一 120 天窗口的 dispersion 分布上
选的(p25),属 in-sample 阈值选择,有轻微过拟合风险;(2) 5 月仍占约 82% 收益,只是不再有
负月。且全部是已看 discovery。结论:候选现在处于明显更好的状态,但 N1 门控仍未通过(无新
完整 OOS、仍偏单月),**仍不进 S2**;下一刀就是把这个 `thr0.034` 固定参数留到下一个完整
`validation_v1` 独立窗口 once-only 复核。

2026-06-05 已按计划 §5 / §9.x 给 `strategy-selection-scan` 补 **Deflated Sharpe Ratio (DSR)**
多重检验惩罚(新增 `compute_directional_deflated_sharpe`,scan 顶层输出
`directional_deflated_sharpe`;López de Prado 口径,正态简化,research-only diagnostic)。本地和
WSL 全量测试升级为 `243 OK`。在**选出该候选的那张 81-cell 低频网格**
(`1h/4h/1d × xs_mom/xs_rev/ts_mom × lb3/12/24 × h1/3/6`、top12、120 天 discovery)上读 DSR：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T143817Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-dsr-120d-20260605/qount-strategy-selection-s1-lowfreq-top12-dsr-120d-20260605.json
trial_count=81
best_by_per_period_sharpe=1d xs_mom lb24/h6
best_per_period_sharpe=0.27825601
expected_max_per_period_sharpe=0.40655144   # 81 次噪声下的期望最大 Sharpe
trial_per_period_sharpe_variance=0.02741146
best_period_count=119
deflated_sharpe_ratio=0.08171240
assumes_normal_returns=true
```

读法：这是迄今最重要的反过拟合读数。**观测到的最佳 per-period Sharpe `0.278` 比 81 次随机
试验下噪声的期望最大值 `0.407` 还低,DSR ≈ `0.082`**(通常要求 > 0.95)。也就是说,在选出
候选的那张网格上,最佳 cell 的 Sharpe 在统计上与"81 次噪声里挑最大"不可区分;而且这还用了
正态假设(对肥尾会高估 DSR),真实 DSR 只会更低。这把结论从"候选还需新 OOS"收紧为
"**候选的网格内选择优势本身大概率是多重检验假象**"。S2 门控据此加硬:即便将来某个完整新
OOS 上 `thr0.034` 仍正,也必须同时给出可接受的 DSR/PBO 才能进 S2;否则按 §7 全局退出条件
诚实退出。当前**仍不进 S2**。

2026-06-05 又按 §5/§9.x 补 **PBO / CSCV**(Probability of Backtest Overfitting,Bailey &
López de Prado;新增 `compute_directional_pbo`,scan 顶层输出 `directional_pbo`,按频段分组
做 combinatorial symmetric CV,research-only diagnostic)。同一 81-cell 网格读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T150603Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-dsr-pbo-120d-20260605/qount-strategy-selection-s1-lowfreq-top12-dsr-pbo-120d-20260605.json
block_count=10  combos=252  (每频段 27 个 config)
pbo_1h=0.0556  median_logit=1.9042
pbo_4h=0.0198  median_logit=2.8332
pbo_1d=0.2143  median_logit=1.9042   (primary：DSR 最佳 per-period Sharpe 所在频段)
```

读法：DSR 与 PBO 互补、且不矛盾。**DSR** 问"绝对 Sharpe 量级在 N 次试验通缩后是否显著"
→ 否(`0.082`);**PBO** 问"IS 最佳 config 在 OOS 是否仍排名靠前"→ 大体是(PBO 全部 < 0.5、
median_logit > 0)。合起来的诚实图景:存在一个**弱但排名稳定**的横截面动量结构(不是纯随机
→ PBO 低),但其**量级太弱**(DSR ≈ 0.08),在多重检验 + 成本 + 路径执行后不足以确认盈利。
两个指标都指向同一决策:**不进 S2**。一条诚实保留:同频段 27 个 config 高度相关(同族、
重叠 lookback),会让 CSCV 的排名稳定性虚高、PBO 偏低,所以低 PBO 不能解读为"低过拟合风险",
只能解读为"赢家不是每次随机换人"。决策仍以 DSR + 等新 OOS 为准。

最新盈利导向改动是一个窄 blocker：`eth_short_range_noise_terminal_washout`。它只拦
ETH fresh `sell` + `range_noise` + higher trend/short，且同时满足
`return_24bars <= -1.0%`、`rsi_14 <= 32`、`sma_fast_ratio <= -0.8%`、
`sma_slow_ratio <= -0.8%`、`volume_ratio_20 >= 1.5`、`range_pct >= 0.8%` 的
terminal washout。该 reason 已加入 `HARD_BOTTOM_LINE_REASONS`，`bottom_line` 不能覆盖。

在已失败的 2026-06-01..2026-06-03 validation 窗口上降级为 discovery 复测后：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T135759Z-walk-forward-qount-wf-eth-terminal-washout-block-discovery-20260604
holdout_role=discovery
positive_realized_windows=1/2
paper_filled=4
paper_closed=5
sum_realized_return_pct=+0.9173089048%
avg_realized_return_pct=+0.4586544524%
windows_with_open_positions=0
total_review_missed_candidate_move=2
disc-jun01=-0.1510033978%
disc-jun02=+1.0683123026%
```

读法：这是有价值的盈利方向证据，说明 6/2 bad trade 被有效挡住；但这些窗口已经被看过，
只能作为 discovery，不能作为 promotion。

随后在新的 once-only validation 窗口 2026-06-03..2026-06-04 上第一次复测同一 blocker：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T141045Z-walk-forward-qount-wf-eth-terminal-washout-block-val-jun03-20260604
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
```

读法：这份 artifact 不能当策略结论；run 46 起 AI 返回 `auth_unavailable`，导致
`halted=true` 和 open position remaining。

AI relay 恢复后，同策略、同窗口做 infra rerun：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T145900Z-walk-forward-qount-wf-eth-terminal-washout-block-val-jun03-infra-rerun-20260604
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

读法：有效复跑没有遗留仓位，所以主问题不是 exit cleanup，而是 6/3 后半段 repeated
`range_noise` short 质量差。6 笔 short 只有 1 笔盈利；后两笔亏损是更明显的 oversold
terminal washout，但当前 blocker 因 `range_pct >= 0.008` 和 `sma_fast <= -0.008`
仍漏掉。这个窗口已经看过，后续只能作为 discovery 设计下一条 blocker，不能作为 promotion。

第一次 `validation_v1` once-only walk-forward 使用 `gpt-5.5`、主线 v1 setup model：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T134036Z-walk-forward-qount-wf-eth-validation-v1-v1-20260604
windows=val-jun01 2026-06-01T00:00:00Z..2026-06-02T00:00:00Z
        val-jun02 2026-06-02T00:00:00Z..2026-06-03T00:00:00Z
holdout_role=validation_v1
oos_safe_windows=2
positive_realized_windows=0/2
paper_filled=7
sum_realized_return_pct=-0.7159862916%
total_review_missed_candidate_move=2
windows_with_open_positions=0
```

读法：

- 这批 validation 样本不满足 `G_paper`：`sum_realized_return_pct` 为负，
  `positive_realized_windows=0/2`，且存在 `missed_candidate_move=2`。
- actionable review 为负：`val-jun01 avg_net_edge=-0.0676%`，`val-jun02 avg_net_edge=-0.0558%`。
- `eth_trend_impulse_range_noise_range_gt012` / `washout` 在 `val-jun02` 是 bad trade，
  不能把这类 range-noise 旧 discovery tag 提升为 gate。
- `eth_trend_impulse_short_breakdown_chase` 在 `val-jun02` 有 2 个 missed candidate move，
  但整体 review 不支持靠放宽短线开仓来修复；这两个窗口已用作 validation，不再用于调参后复验。

最新有效 13-window chronological walk-forward 使用 `gpt-5.5`：

```text
sum_realized_return_pct=+1.6184470183%
positive_realized_windows=2/13
paper_filled=4
```

全部正收益集中在：

```text
wf-mar06  +1.5617%
wf-apr15  +0.0567%
```

读法：

- 有历史盈利样本，但 alpha 极稀疏。
- 946 cycles 只产生 4 笔 fresh open，分布在不超过 2 个窗口。
- 旧 G1/G2 以窗口数为核心，在当前成交密度下数学上不可达。
- [holdout.md](holdout.md) 已把已看过窗口冻结为 `discovery_pool`，新 gate 改为
  `G_paper` / `G_live`。

## WS-1..WS-4 结论

- WS-1 h12 + loose trailing：`wf-mar06` realized 只有 `+0.5828756239%`，低于 h6
  基线 `+1.5617328164%`，且留下 1 个 open position；不继续。
- WS-2 maker/min-edge：maker fee 只能小幅改善离线边际；提高 min-edge 会砍掉
  `wf-apr15` 正收益或直接变成 0 交易；不继续。
- WS-3 集合根扫描：`state/research_runs` 集合仍 `ready_tags=[]`；不写 gate。
- WS-4 `multi_range_action_pullback_sma_fast_gt008`：离线 h3/h6/h12 有 edge，但 step 3
  两个窗口 24/24 AI 全 hold，0 成交；不进 gate。
- WS-4 `range_return24_gt012`：样本少，h3/h12 为负；不 ready。
- WS-4 `eth_reclaim_long_*`：h3/h6/h12/h24 整体负或样本不足；不 ready。
- 2026-05-30 新 OOS 仍 0 成交，`ready_tags=[]`。

## T-B hold-bias 读数

2026-05-31 已完成第一步工具化：`ai-hold-baseline` 能按 research profile / symbol
过滤历史 artifact 中的 fresh-entry prompt 样本，并把结果持久化到
`state/research_runs`。

WSL 读数：

- multi-symbol WS-4 fast-SMA 两个 step3 窗口：`sample_count=24`，既有 AI 决策
  `hold=24/24`。artifact：
  `/home/alyaloale/Code/qount/state/research_runs/20260531T064411Z-ai-hold-baseline-qount-ai-hold-multi-fast-sma-dryrun-20260531/qount-ai-hold-multi-fast-sma-dryrun-20260531.json`
- eth-only profile 同一 tag 只取 ETH 样本：`sample_count=2`，确认 profile/symbol
  过滤已生效。artifact：
  `/home/alyaloale/Code/qount/state/research_runs/20260531T064410Z-ai-hold-baseline-qount-ai-hold-ethonly-symbol-filter-20260531/qount-ai-hold-ethonly-symbol-filter-20260531.json`
- eth-only `v3_veto_only` smoke：`repeat=1`、`sample_count=2`、`request_count=2`，
  结果仍是 `hold=2/2`。artifact：
  `/home/alyaloale/Code/qount/state/research_runs/20260531T064502Z-ai-hold-baseline-qount-ai-hold-ethonly-v3-smoke-20260531/qount-ai-hold-ethonly-v3-smoke-20260531.json`

读法：T-B 现在有可复现的 hold-bias 诊断入口；但小样本 v3 smoke 没有解锁开仓，
且 AI 给出的 hold 理由是具体 veto（SMA/24bar 冲突、负 expected_edge、反向 rebound 或
过热），不能把 prompt v3 当成 promotion 证据。

## T-G idle-window 读数

2026-05-31 已完成 `idle-window-diagnostic`，并修正全局 reason aggregate：窗口输出仍受
`--reason-limit` 限制，但 aggregate 使用未截断计数。WSL artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260531T072108Z-idle-window-diagnostic-qount-idle-window-diagnostic-ethonly-20260531-v2/qount-idle-window-diagnostic-ethonly-20260531-v2.json
```

关键读数：

```text
backtest_count=39
idle_window_count=36
skipped_traded_window_count=3
candidate_filter_hold_count=2878
ai_hold_count=87
selected_or_candidate_like_scored_count=890
positive_top_candidate_avg_future_edge_windows=5/36
```

setup model quality 分布：

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
```

读法：当前 ETH-only 0 交易窗口主要被 research/candidate/market-quality 约束拦住；
不是 setup_model 看见大量 strong favorable alpha 后被 AI 或 risk 系统性压掉。
36 个 idle 窗里只有 5 个窗口的 top candidate 均值 future edge 为正，且主要来自已看过
WS-4 fast-SMA / wf-mar11 / wf-may06 discovery 窗口；不能据此加 gate。

## T-C setup_model v2 读数

2026-05-31 已完成第一版 `v2_interactions` 训练/评分 plumbing：

- v1 默认不变。
- `--setup-model-version v2_interactions` 只在研究训练 / walk-forward 显式使用。
- v2 在 16 维 v1 基础上增加 higher-timeframe phase × bin 交互特征。
- 新增 `setup-model-compare`，只做离线 chronological split，不调用 AI、不执行订单。

WSL ETH-only 默认相位读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T075127Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-20260531/qount-setup-model-compare-ethonly-v2-20260531.json
example_count=705
eval_example_count=212
v1_top_decile_avg_target_edge_pct=-0.0011523934
v2_top_decile_avg_target_edge_pct=-0.0013773666
v2_minus_v1_top_decile=-0.0002249732
v2_minus_v1_mae=+0.0000124423
```

包含 `range_noise` 的读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T075351Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-range-20260531/qount-setup-model-compare-ethonly-v2-range-20260531.json
example_count=19681
eval_example_count=5905
v1_top_decile_avg_target_edge_pct=-0.0015544902
v2_top_decile_avg_target_edge_pct=-0.0013618186
v2_minus_v1_top_decile=+0.0001926716
v2_minus_v1_mae=+0.0000053851
v2_strong_favorable=0
```

读法：v2 第一版 plumbing 可用，但没有形成可交易 lift。包含 `range_noise` 时 top-decile
相对 v1 略好，但绝对值仍为负，MAE 稍差，且没有任何 `strong_favorable`。不能替换主线
setup model，不能作为 entry gate 或 promotion 证据。

2026-06-04 在 `validation_v1` 两个新窗口上做了只读 candidate 对比：

```text
v1_artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T132940Z-candidate-walk-forward-qount-candidate-wf-eth-validation-v1-v1-20260604
v2_artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T132941Z-candidate-walk-forward-qount-candidate-wf-eth-validation-v1-v2-20260604
window_count=2
total_cycles=578
total_fresh_entry_selected=25
v1_total_selected_cycles=25
v2_total_selected_cycles=25
v1_strong_favorable=0
v2_strong_favorable=0
```

读法：v2 没增加 candidate 覆盖，也没产生更强质量分布；这次不推进 v2 到端到端验证。

## 架构判断

当前主要问题不是某个单点 bug，而是四件事叠加：

- 旧 promotion gate 与成交密度不匹配。
- discovery / validation 边界此前没有机器可读记录。
- AI prompt v1 过度保守，强候选上出现系统性 hold。
- `setup_model` v1 是 16 维线性 ridge，表达不了当前 alpha 所在的 phase × bin × bin 交互。

已接受的前置修复：

- [holdout.md](holdout.md)：冻结 `discovery_pool`，定义 `validation_pool_v1`，改成
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
   已在VPS闭合；publisher与Daily Intelligence timer保持`enabled/active`，authority unit保持`static/inactive`，MiniTrend live timer
   保持`enabled/active`，forward timer和production cron保持关闭。publisher只刷新系统健康、release和备份，不查询交易所；账户/决策
   authority只由已授权live cycle刷新，并会在两次日线周期之间按15分钟规则自然stale。不得通过提高阈值、复制旧JSON或手工调用交易路径洗新。
   NotificationStore与个人微信transport已完成真实`DELIVERED/SUCCEEDED`验证，后续只监控投递失败、限流和context token轮换；它不接
   legacy `Notifier`/shell ServerChan，也不赋予订单权限。VPS publisher仍只能读取完整batch/registry/ledger/notification/health/brief，
   不能读取legacy state JSON或复制fixture。
2. 当前主动路线保留三条隔离的 research-only 记录：spot TOP3 forward 继续只追加完成的 spot 1d bars；
   UM base-trend v0.2 已完成完整 forward preregistration，等待新的完整 UM 日线后再收集；Equity Mapping
   只在纽约`09:24:30-09:25:00`冻结窗口追加有raw readback hash的同步三腿/日历/公司行动/压力证据。
   这些research/shadow记录都不改参数、不获得paper/live权限；spot forward 至少累计60根且10根active前保持`collect_forward`。
   当前Base 100 USDT minimal-live是独立例外，不能把它的授权扩散给RiskTier、FundingVeto或其它研究线。
   已拒绝的 UM 2.0% 全局档、三阶段 overlay 和stop-latch都不进入forward；funding-veto虽通过历史门和
   条件Bootstrap稳健门，也只冻结为首选 consumed-history 候选，不调50%阈值、不自动获得paper/live资格。
   双状态shadow-forward已从`2026-07-19`预登记；VPS canonical UM日线已到`2026-07-18`，但冻结起点尚无完成bar，
   当前仍为0根和`await_shadow_forward_data`。MiniTrend forward timer当前保持关闭；未来只有在重新获得明确授权的order-free周期中，
   才能由VPS直连刷新公开REST/日包，并且只在价格与每日三次funding同时完整后追加两套权益、仓位/deadband/latch
   状态，首次权重同步不能作为停止跟踪条件。禁止使用苏菲家宽代理，缺失funding禁止填0。
   Equity Mapping首个目标现金日是`2026-07-20`，当前`await_collection_window`；窗口前不得生成伪样本，窗口
   错过后不得用异步历史报价补写。只有同现金日sealed manifest逐项覆盖8类source hash，G0 v0.4才允许声称
   point-in-time market evidence；当前source-capacity只有cash calendar通过，必须先取得带source event timestamp的
   可执行cash premarket bid/ask，并补齐mapping、mapped quote、USDTUSD、公司行动、事件上下文和stress来源。
   Nasdaq当前delayed quote不能代替现金腿，也不得用HTTP接收时点冒充市场quote时点。仍需累计30个独立现金交易日，
   且不因此进入shadow/paper/live。
3. 一个月小资金实盘已进入`minimal_live`，下一步是等待自然信号并收集真实执行样本。2026-07-21 owner已把本金严格固定为
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
   `qount-mini-trend-live.timer`在该阶段为`enabled/active`，现已因0.2.7升级维护停用。当前信号全现金，所以没有真实订单或成交；不得为采集样本强制下单。
   旧X4/C×D cron与forward timer继续关闭，全局2.0%风险档和Funding Veto只能做shadow，不能控制真钱订单。

   该阶段本地全仓复跑为`1542 OK`，VPS production为`328 OK`。Python compileall、Bash语法、release provenance、
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

- 不在缺少最终hash确认和manual arm时开live。
- 不自动启用forward timer；order-free B/C/D演练只允许手工一次性执行。
- 不把 `discovery_pool` 窗口当 validation。
- 不放宽 broad `range_noise` / `short_rebound_fail`。
- 不把 `offline_future_edge_readiness` 当 promotion 证据。
- 不把 Kronos 接入 candidate / risk / live。
- 不把 LightGBM 当默认研究依赖；当前默认 GBDT 路线用 sklearn `HistGradientBoosting`。
- 不把“恢复加密研究优先级”解释为恢复 VPS collector、private API、paper 或 live。
