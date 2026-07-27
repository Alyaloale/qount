# qount 更新记录

> **状态**：active（记录链）｜**权威**：L5 证据链｜**最后更新**：2026-07-27
> **本文回答**：近期（2026-07-16 加密重启起）执行记录、验证结果、读法。
> **TL;DR**：只记近期；2026-07-20 及更早见 `archive/update-log-archive.md`；结论以 current.md 为准。

更新时间：2026-07-27

这份文档只记录**近期**关键变更、验证结果和当前读法（2026-07-21 起）。
**2026-07-20 及更早**的历史证据链移入 [archive/update-log-archive.md](archive/update-log-archive.md)。
当前策略结论以 [current.md](current.md) 为准；复跑命令和跨主机操作细节放在
[quick-handoff.md](quick-handoff.md)。

## 2026-07-27 (Round 30)

### Dashboard 私有账户观察自动刷新

新增独立 `qount-dashboard-account-observer.timer`，每五分钟仅运行现有私有只读 preflight，原子更新
`/var/lib/qount/blocked_runtime_observation.json`，再由既有 Dashboard publisher 发布。该 observer 不导入 executor 或 arm，
固定清空 live confirmation/token，`live_orders_allowed=false` 且 `private_api_order_attempted=false`；MiniTrend/FOMC live timer
仍保持关闭。它的职责仅是刷新余额、仓位和挂单观察，不能生成 readiness、arm 或订单。

### Dashboard v1 发布快照读取修复

Dashboard 前端此前先从可原子切换的 `data/v1` 链接读取 `publication.json`，再从同一链接并发读取模型；恰逢 publisher
切换 release 时，浏览器可能拼接两次发布而误报 `strategies 权威来源不一致`，并按失败关闭进入 `PRODUCTION STOPPED`。浏览器回归还发现
`strategies` 合法地包含模型专属 `system_health` hash，而 publication 只登记跨模型共享来源；反向地，publication 可包含全局
`blocked_runtime_observation`，而 `decisions` 只包含决策批次基础来源。旧客户端错误地要求一方来源集合包含另一方。前端现将已验证的
`publication_id` 固定为 `data/releases/<publication_id>/` 的不可变模型路径，并只对两者交集的来源 hash 做精确匹配；模型 ID/hash
与后端 release 校验继续负责全体来源的完整性，真实损坏仍失败关闭。当前 VPS `read_dashboard_v1()` 对 release 全量回读通过，publisher
保持 enabled/active，所有订单执行 timer 继续 disabled/inactive。聚焦 Dashboard 读模型测试和 `node --check web/site/app.js` 通过。

### 文档归档整理（清理=移动不删除，逐行守恒）

owner 要求梳理归档文档降低接手成本。本轮：① `update-log.md` 中 **2026-07-16..2026-07-20** 的历史证据链
整体移入 `archive/update-log-archive.md`（归档边界从 2026-07-14 前移到 2026-07-20，正文逐行守恒）；
② 为本周新增的三份分析文档补齐 §10.1 强制文档头（`long-run-personal-strategy-design.md`、
`personal-strategy-research-directions.md`、`fomc-trigger-study-and-v03-extension.md`）；
③ `project-rules.md` §3 分类表新增"个人组合设计/方向候选"行、§4 隔离表新增 PreEvent-Range 行；
④ `CLAUDE.md` 更新过期事实（MiniTrend timer 已停、FOMC `0.2.21` 已部署 order-disabled）并补文档地图；
⑤ `archive/README.md` 同步新归档边界。未删除任何文件，未 commit/push。

## 2026-07-27 (Round 29)

### `0.2.21` FOMC受控live runtime已部署，timer保持关闭

**release与验证**：owner授权把当前工作区整理为一个干净的`0.2.21` release并同步VPS。Mac全仓`2370/2370 OK`，VPS
production profile=`360/360 OK`，editable package安装为`qount==0.2.21`。VPS的`.qount-release-provenance.json`绑定
本release commit和source tree；`.qount-release-verification.json`逐文件验证通过。FOMC live unit经`systemd-analyze verify`校验，
其service/timer与`/etc/systemd/system`安装副本的SHA-256逐项一致。

**状态边界**：`qount-fomc-live.timer=disabled/inactive`、无NEXT；`/root/.config/qount/fomc-live.env`不存在，未运行
`prepare`、未创建arm、未开启live switch、未读取私有账户或下单。现有用户自有BTC USD-M仓位和两张条件单未作任何更改；owner平仓/撤单后，
仍须等待shadow信号`ARMED`并在入场窗口内重新作私有readiness预检，`verdict=ready_for_fomc_live_arm`才可进入手工arm。

## 2026-07-27 (Round 28)

### 长期个人组合设计文档入库（分析文档，非预登记合同）

owner 要求把长期可盈利策略设计分析写入文档：新增 `docs/long-run-personal-strategy-design.md`。
内容：基于 148 次 formal trial 的证伪资产（短周期择时/微观结构/跨所套利/币内横截面四堵墙）与
四项存活证据（L1 跨资产趋势 REAL、MiniTrend base=低 beta 风险包装器、Funding Veto 成本工程、
事件/被迫流），提出三层 sleeve 组合：核心跨资产月度趋势配置（70-80%）+ 事件/被迫流卫星（10-15%）
+ 研究线（0% 真钱）。本文档不改变任何授权状态；任何落地仍须走 G0 → 预登记 → shadow/canary 纪律。

### FOMC 触发率实证与 v0.3 延续持有扩展提案（同 Round，discovery 级）

owner 询问 FOMC 是否会触发、效应不够大怎么办、只做一天是否太短。新增
`docs/fomc-trigger-study-and-v03-extension.md`：用 OKX BTC/USDT 公共 K 线对 2024-01..2026-06 共
20 次 FOMC 复现冻结口径的 1h 方向锚——锚触发率 11/20（55%，叠加 15m 确认后估计 25-40%）；
D0 有利幅度 >=2 ATR 的 7/11，弱锚（<1.5 ATR）4 次中 3 次大幅反向，证明小效应事件不该降低门槛；
强突破 D0->D+3 有利幅度普遍扩大 2-4 倍（如 3.58->11.93 ATR），当日 19:00 硬平仓截断了主要利润。
提出 v0.3：19:00 检查点 >=2R 才转保本止损 + 3xATR 吊灯延续持有至 D+3，否则按 v0.2 全平。
本笔记为 discovery 级（n=11、OKX 数据），7/30 canary 仍按 v0.2 执行；v0.3 须另行预登记并用
Binance 数据复算。未 commit/push、未部署、未访问私有 API、未下单。

### 个人策略新研究方向设计（同 Round，分析文档）

owner 要求在低数据/低硬件/厚利润约束下设计新研究方向。新增
`docs/personal-strategy-research-directions.md`（D1 宏观事件篮子扩展 P0、D3 跨资产个人载体重认证 P0.5、
D2 forced-flow 均值回复 P1、D4 事件前区间 fade 泛化 P2），并在
`docs/research-advancement-roadmap.md` 末尾追加 §12 索引。全部为分析/候选，未开任何 trial、
未消费数据结果、未改变已冻结线状态。未 commit/push。

### D5 行业 ETF 轮动方向追加（同 Round）

owner 提出行业趋势 + 多 ETF 特征选择 ML。已在 `docs/personal-strategy-research-directions.md`
追加 D5（P1）：11 个 SPDR 行业 ETF 月度轮动，先过 `_panel_effective_breadth` 广度 G0（<2.0 则降级，
与加密横截面同尺）；ML 硬边界沿用 2026-07-19 证伪结论——只做特征排序辅助、简单动量基线先行、
purged-CV+DSR/PBO 显著性门，不输出仓位/方向/权重。roadmap §12 已同步。未开 trial，未 commit/push。

## 2026-07-27 (Round 27)

### PreEvent-Range 区间 fade 线预登记与 plan-only 工具落地（仅本地，未提交）

**owner 决定**：授权在 FOMC（7/30）前窗口以小额 canary 执行区间高抛低吸，明确接受本线跳过 shadow 晋级纪律（一次性豁免）。
**落地内容**：新增预登记合同 `docs/pre-event-range-strategy.md`（`SmallAccount-PreEvent-Range-v0.1`）；纯函数信号模块
`src/qount/small_account/range_signal.py`（冻结区间 fade 触发、破位/过窄/现金截止 fail-closed）及 15 项回归
`tests/test_small_account_range_signal.py`（全部通过）；plan-only CLI `scripts/operations/run_pre_event_range_plan.py`
（freeze 一次性不可覆盖 + scan 输出双向计划，复用 `size_linear_usdt_futures` 全成本 2R 门槛）。
**边界**：全程 `orders_authorized=false`、零私有 API、零订单；真实入场由 owner 依据 scan 计划手工执行并先挂原生
STOP_MARKET 保护；上海 7/30 01:00 前强制全平交还 FOMC 流程。本轮改动仅在本地工作区，未 commit/push、未部署 VPS。

## 2026-07-27 (Round 26)

### 0.2.21封装FOMC受控live能力并推送仓库

**仓库发布**：包版本由`0.2.20`提升为`0.2.21`，收录Round 24已完成的FOMC私有预检、哈希readiness、短时单次arm、
MARKET成交与逐笔fee确认、原生`STOP_MARKET closePosition`保护、紧急reduce-only平仓、硬截止退出及有限窗口systemd模板。
这次只形成并推送仓库版本；未同步VPS、未安装或启用live timer、未读取生产私有账户、未创建arm、未调用订单接口。

## 2026-07-27 (Round 25)

### 0.2.20账户只读事实、Dashboard与个人微信全面修复并部署

**根因与口径修复**：历史Dashboard只接受RuntimeLedger作为仓位/订单权威；当前用户自有BTC仓位未进入Qount ledger，因而仓位和订单
模型都显示不可用，同时registry的`minimal_live`被误读成当前可下单。日报又把2026-07-23历史空仓对账当成当前事实。修复增加独立、
不可授予订单权的blocked runtime account observation：交易所现时数量/名义/余额可显示为`available_readonly`，但平均成本、订单沿袭、
PnL、NAV和ledger reconciliation必须继续unavailable；策略模型同时展示`registry_status=minimal_live`与
`execution_status=blocked/live_orders_allowed=false`。日报在旧ledger与新交易所观察冲突或过期时fail closed，并明确历史时点。

**低余额与执行安全**：旧forward shell在只读preflight后硬断言可用余额`>=100 USDT`，使账户观察无法发布。`0.2.20`允许低余额继续
完成只读采样和authority publication；只有实际增仓BUY intent才触发`available_balance_below_pilot_capital`并移除买单，reduce-only SELL和
后置对账语义不被误伤。所有路径仍由unit强制live开关false；未创建arm、未启用MiniTrend timer、未调用订单或账户变更API。

**发布与实机证据**：clean release commit=`3a4fb404ecf870c67301b15ce71fed3ddcdd5faa`、version=`0.2.20`、source tree=
`f38215708c3de6664f9d877bec680c4d0099b9840ddca652216f0cfff31103da`、provenance=
`76ee714d0bd1049aa98a569204ac42589d458e82da788fc51e72cae8d426afbe`、verification=
`565fe17b991f1a73f132a7b8ca89a4178290eb40eed89b97665ae2043c52b562`。只同步`52874a2..3a4fb40`七个修改文件与manifest，
回滚目录=`/root/qount-repair-backup-0.2.20.SvlnYe`。VPS聚焦`132 OK`、production profile `360 OK`，compileall、Bash/Node语法、
manifest SHA和editable package version均通过。

**账户只读oneshot**：手工运行order-free forward service一次，run=`20260727T073725Z`成功。账户事实为BTC USD-M long `0.009`、
名义`587.6163 USDT`、钱包`203.06011455 USDT`、可用`66.0921174 USDT`、普通挂单0；另有两张用户既有BTC条件保护单，
未撤改。observation hash=`ac00bd58320628b333c901973ac198b3af8ce1b46a0250618cefe3fedf687757`，全部
`private_api_order_attempted/exchange_mutation_attempted/live_orders_allowed=false`。live/forward timers始终`disabled/inactive`，
production cron仍无active entry。

**日报、微信和发布**：正确日报ID=`29be08b688941160ca82a4f9fe58253d3c4edd676419b3174ef319ef5f396d8d`、hash=
`fc3f2e36d8cb381bcfef33822beff802b5c27feafe0235452354491bb8fa2018`，明确当前BTC观察未进入ledger。旧job
`3bce57fe...`与`cd650cee...`各有唯一`delivery_cancelled`审计并转为`DEAD_LETTER/notification_delivery_superseded`；新job
`c8f11bf6...f4c9`一次`DELIVERED/SUCCEEDED`，response hash=`b10445d8...bdf1`。这只证明腾讯通道已接受，不代表客户端已展示或用户已读；
OpenClaw gateway保持active，无需扫码。
retry timer恢复后自然轮询processed=0。静态app/index精确安装，已验证publication=`cee6e7dc...a656`、hash=`7533ccb7...e166`，
positions为`available_readonly`、orders为ledger unavailable、strategy执行blocked，publisher restore drill和system health均healthy。

## 2026-07-27 (Round 24)

### FOMC受控live路径本地闭环，Dashboard 401根因复核

**实现**：新增事件专用私有账户preflight、哈希readiness、10分钟内单次arm、0600 env与独立live switch；订单入口绑定事件、账户、
信号candle identity、batch/plan、方向、数量、名义、`<=5 USDT`压力风险、止损和硬退出时间。MARKET入场要求order与逐笔trade/USDT fee
共同确认，原生`STOP_MARKET closePosition`必须回读；保护失败后HALT并尝试幂等`reduceOnly MARKET`紧急平仓，只有账户flat且条件单清空
才记为已平。持仓周期校验原生保护，到`11:00 UTC`取消保护并强平；歧义保持`halted_uncertain`。新增`prepare/arm/switch/cycle` CLI和
只覆盖本次事件窗口的service/timer模板，生产默认未部署、未enable。

**验证**：`PYTHONPATH=src .venv/bin/python -m unittest tests.test_small_account_fomc_live tests.test_small_account_fomc_runtime
tests.test_small_account_fomc_adapter tests.test_small_account_fomc_watcher`为`37 OK`；全仓`2345 OK`，相关Python `compileall`、CLI help和
`git diff --check`通过。没有访问私有账户、创建arm、写生产env、部署unit、启用timer或调用订单接口。

**Dashboard只读生产核验**：2026-07-27 10:38 CST publisher timer为`enabled/active`，最近oneshot success；最新publication
`3a58fee6...d6be`、hash=`27b1c01b...468`，12份JSON存在，restore drill和system health通过。公网匿名请求在HTML前被Caddy
Basic Auth返回`401/WWW-Authenticate: Basic realm="restricted"`。结论是发布健康、访问受保护；未取消认证，避免公开账户与订单数据。

## 2026-07-27 (Round 23)

### 0.2.18补齐FOMC现金窗口告警并部署

**缺口与实现**：固定timer从`17:00 UTC`开始，但`0.2.17`在`17:00-17:30`只写`SCHEDULED`结果，Dashboard没有明确的现金窗口告警。
`0.2.18`新增`fomc_event_cash_only` WARNING：只在`cash_only_from <= observed_at < freeze_at`打开，identity绑定event/cash/freeze时钟，
5分钟重复运行保持同一alert；冻结开始后由同一producer scope自动RESOLVED，并由freeze incident接力。运行结果仍为`SCHEDULED`，冻结前
不访问交易所；告警只进入Dashboard channel，不声称账户已平仓或授予订单权限。前端增加`FOMC 现金窗口`分类，cache key升为`v=25`。

**Release与部署**：实现提交`5fe2b914fd832ba20a4b1a1ecc7daf6f8aac3e62`已push并同步VPS。安装版本=`0.2.18`、source tree=
`af137375...d20697`、production provenance=`7b28fd69...0a6bda3`；逐文件verification无mismatch/unexpected，verification hash=
`974512d2...7378a2`。Dashboard served资产与release hash一致，旧版备份在`/root/qount-dashboard-static-backup-0.2.18-predeploy`；
Node/Caddy和原子11-model readback通过，公网仍为Basic Auth `401`与`no-store`。

**验证与边界**：本地FOMC`26/26 OK`、notifications/dashboard`49/49 OK`、全仓`2303/2303 OK`；VPS FOMC`26/26 OK`、
production profile`343/343 OK`。VPS临时目录在`17:00/17:05`两轮后验证1条OPEN cash-only incident、全权限字段false，退出后自动删除；
没有写生产NotificationStore、访问私有账户/API、运行paper/live或下单。FOMC timer保持`enabled/active`，MiniTrend live/forward仍为
`disabled/inactive`，production cron仍无entry。

## 2026-07-27 (Round 22)

### 0.2.17 FOMC order-free watcher已部署并启用固定事件窗口

**Release与provenance**：实现提交`0a6915d9f2c4ae37ade2e22e303f02d83b6eeb4f`已push到
`origin/crypto-lines-bcd`，并由干净工作区执行`./scripts/sync-to-vps.sh --install`。VPS安装版本=`0.2.17`、source tree=
`022dec86...d7b2fbb`、production provenance=`06af5c51...a697af`；逐文件验证无mismatch/unexpected，verification hash=
`f48cd775...2f82fc7`。

**Watcher部署**：`/var/lib/qount/fomc`为`0700 root:root`，run/latest为`0600`；service/timer安装hash与release模板一致。
当前时刻手工smoke为`SCHEDULED`、result=`019019be...3727d0`、service success，五个权限/副作用字段全部false，0 signal、0 batch、
0 order。`qount-fomc-shadow.timer=enabled/active`，首次自动触发为上海时间`2026-07-30 01:00:13`，调度只覆盖
`2026-07-29 17:00 UTC`至`2026-07-30 11:00 UTC`。MiniTrend live/forward timer仍为`disabled/inactive`，production cron仍无entry。

**公共行情与Dashboard**：在显式移除代理和Binance凭据环境后，VPS collector成功读取BTCUSDT的`899`根完成1h K、`299`根完成15m K、
ticker、funding和symbol rules，未写freeze/state。Dashboard三份静态资产已部署并逐项hash一致，旧版备份在
`/root/qount-dashboard-static-backup-0.2.17-predeploy`；Caddy和Node检查通过，公网匿名访问保持Basic Auth `401`、`no-store`和安全响应头。
production publisher随后成功发布并原子readback 11份model与19条既有alerts；事件仍为`SCHEDULED`，没有制造假FOMC告警。

**验证与权限**：VPS FOMC聚焦`25/25 OK`，notifications/dashboard关联`49/49 OK`，标准production profile`343/343 OK`；
systemd unit验证和三段UTC日历解析通过，仅报告VPS既有`cloudmonitor.service`警告。本轮没有读取私有账户/API、paper/live或下单，
没有恢复任何交易执行timer；FOMC adapter虽能生成订单计划，仍缺exact account/side/notional/max-loss/manual arm和venue dispatcher授权。

## 2026-07-26 (Round 21)

### 0.2.17完成FOMC不可下单标准链、公共watcher与VPS候选单元

**范围与权限**：owner要求先把FOMC策略接入现有系统并部署VPS，另授权add、补丁版本提升和push；仍未绑定exact
account/side/notional/max-loss/arm，因此没有paper/live或订单权限。包版本由`0.2.16`提升为`0.2.17`，所有新运行结果固定
`orders_authorized=false/paper_or_live_allowed=false/private_api_used=false/exchange_mutation_attempted=false`。

**实现**：新增不可变事件定义/冻结/扫描运行时与标准适配器，冻结72h range、ATR14、1h/15m V20和3/3 pivot，首个完成1h方向锚锁定；
有符号long/short intent进入allocator/risk，5U canary全成本仓位输出MARKET入场与原生`STOP_MARKET closePosition`计划，未链接账户或manual arm
时不可执行。公共watcher只调用Binance market/OHLCV/ticker/funding，严格排除观测边界K线，以`0700/0600`持久化不可改写freeze/run/
decision batch，并把freeze/readiness/armed写入共享NotificationStore。新增固定Fed事件配置、薄CLI和仅覆盖7月29-30日的systemd oneshot/timer；
unit无EnvironmentFile、移除所有Binance key/arm/live环境。Dashboard alerts新增`event_strategy`来源并突出FOMC类别、当前数量和响应式事件行。

**验证与部署边界**：fake exchange覆盖冻结前零网络、freeze不可变、BLACKOUT、ARMED标准批次/告警和数据不足HALT；FOMC聚焦`25/25 OK`，
Mac全仓`2302/2302 OK`，compileall、Node语法、Dashboard schema、diff和常见secret扫描通过，唯一warning仍为既有CTA UTC deprecation。
Mac无凭据公共Binance探针因出口地区返回451；VPS同一`fapi/v1/exchangeInfo`返回200/1,042,597 bytes，且三条systemd日历均由VPS当前版本解析。
本记录时`0.2.17`尚未同步、安装、reload或enable；MiniTrend live/forward timer和production cron保持关闭，未访问private API或下单。

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
