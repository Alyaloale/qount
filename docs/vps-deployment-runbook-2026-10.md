# 新前端部署执行手册（qount.alyaloale.com）

> **状态**：资产、实盘收益、账户记录与十一线研究目录已部署｜**执行者**：owner／授权 Agent｜**最后更新**：2026-10-30 UTC
> **目标**：把新的只读 API + 双屏前端部署到既有域名 `https://qount.alyaloale.com/`，替换现有旧 dashboard。
> **本文性质**：**纯操作手册**。每一步都给出可直接复制的命令、预期输出、失败判据与回退方式。
> **默认边界**：`research_only=true / orders_authorized=false`。全程不涉及下单、不修改交易授权。

---

## 既有模拟任务自动重试与查询续接（2026-10-30 08:23 UTC）

owner要求确保后续正常运行。发布`/root/qount-releases/paper-continuity-20261030T081204Z/`仅更新`src/qount/api/ingest.py`，并为现有Dual daily/G20-open、CTA-R、research-paper四服务追加`zz-paper-reliability-20261030.conf`、为既有research-paper timer追加`95-paper-persistence-20261030.conf`；不覆盖原unit或`paper-forward.conf`，不改实盘、API或通知服务。仓库四个unit模板和timer同步相同行为。失败15分钟后重试、2小时最多3次启动；CTA-R清除`SuccessExitStatus=2`，输入不足须失败。结束后以`ExecStopPost`刷新既有派生查询，错误不改写主任务结果；G20-open失败也纳入查询状态。收尾命令列表先清空再添加，避免未来部署新模板时重复刷新。只追加派生查询目录的写权限及systemd本机查询所需AF_UNIX；特别是Dual的旧`paper-forward.conf`会清空可写列表，本次必须在它后面加载，否则主任务正常而查询收尾会报只读数据库。没有扩大Linux能力集。

配置经`systemd-analyze verify`验证，四服务主任务和查询收尾均实际exit 0。Persistent启用后实际触发原研究模拟补执行、追加0；原10,691行NAV、659行交易金融值及三个源账本无重复或变更。四个paper timer与实盘timer均enabled/active，实盘08:00自然周期成功，实盘保护哈希/2-0-0执行计数/API PID不变。30项本地针对性测试及VPS候选测试通过，包含本周末冬令时；隔离临时systemd服务以1秒测试间隔验证两次失败后恢复、持续失败止于3次及失败时收尾可读Result，未注入生产故障。`retry-check.json`、`actual-service-checks.json`、`verified.json`分别保存对应结果，临时服务已清理。`before/`保存原摄入源码和只读查询/模拟状态；不含凭据。

回退会核对本次发布哈希及四任务未在执行，移除新增覆盖、恢复原摄入源码并重新加载systemd及既有research-paper timer；不回滚金融账本、查询历史或实盘：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/paper-continuity-20261030T081204Z/rollback.py'
```

## 模拟日线、月末恢复与失败展示修复（2026-10-30 07:29 UTC）

发布与备份位于`/root/qount-releases/runtime-repair-20261030T072030Z/`。七文件为`research_data/paper_daily.py`、`research/cta_r_forward.py`、`dual_engine/market_data.py`、API的`ingest.py`/`db.py`与`web/app/research.js`/`app.js`；未修改实盘源码、服务配置、策略参数或权限。Yahoo日线双节点最多两轮、轮间1秒；月末收盘前恢复只处理已闭合输入，不提前请求当日月末信号，收盘后缺数据仍失败。CTA-R单标的尾部落后时只补取近期缺失日期，备用节点的复权重叠价格必须一致；取不全则失败，避免公共日期交集静默截短。既有paper服务失败状态经查询摄入传入页面，旧曲线可读时仍显示更新失败，健康接口为`partial`。

`before/`保留原七文件、Dual程序/快照、G20现金账本、CTA种子/账本/sidecar及派生查询SQLite一致性备份；不含凭据。`backup.json`记录原路径与保护哈希，`verified.json`记录旧金融行、历史前缀、执行计数和恢复后接口。Dual与CTA既有service均成功，分别推进至29日；第二次Dual为`no_new_closed_inputs`，CTA追加0。旧NAV与交易金融值完整保留，实盘执行记录仍2/0/0，七条模拟错误为空；只读API重启一次，匿名公网仍401。82项本地针对性Python测试、22项前端单测、VPS候选故障/会计测试及上线浏览器回归通过。另一次较宽本地API/前向旧测试有7项固定日期夹具过期失败，未将其计入通过数或放宽生产新鲜度过滤。

代码回退只恢复七文件并重启只读API，不回滚已追加的模拟历史、查询库、交易服务或调度。后续如有代码更新，先核对是否仍属于本次版本，避免覆盖新修改：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/runtime-repair-20261030T072030Z/rollback.py'
```

## G20模拟配置目录权限恢复（2026-10-29 12:30 UTC）

owner要求仅修复模拟盘，微信暂不处理。`/root/qount/config`仍为Mac UID501/GID50、0700；paper服务的`CapabilityBoundingSet=`为空，因此root进程也不能越过该目录权限读取公开分红配置。`setpriv --bounding-set=-all`只读复现失败后，仅对目录本身执行`chown root:root /root/qount/config`，保留0700及全部文件权限，不递归修改、不扩大服务能力或变更源码。后续同步该目录时保留VPS的root属主，避免重新带入Mac UID。

备份与验证位于`/root/qount-releases/paper-config-access-20261029T122809Z/`：`before.json`保留原目录元数据与保护文件哈希，三个JSON备份保留修复前G20/原四账户状态，`query-before.sqlite3`为一致性派生查询备份，`verified.json`记录实际续接与重复刷新结果。既有daily服务两次执行成功；首轮补齐G20三日、原四账户追加一个有效截止周期，第二轮无新输入跳过；原源历史前缀保留。G20最新207点至28日，7条模拟均新鲜，API未重启，交易权限与通知未操作。

权限回退仅为将该目录属主恢复为原501:50、权限继续0700；这会恢复已知读取故障，通常不应执行。修复没有部署新代码，不需要源码回退；不得用旧模拟/查询备份覆盖之后有效追加的数据。原G20代码发布的回退仍见下一节。

## G20现金分红模拟修复（2026-10-25 13:10 UTC）

owner要求修复优化最新G20模拟，发布位于`/root/qount-releases/g20-cash-20261025/`。`candidate/`以独立SQLite及模拟状态验证，再更新G20现金模块/适配器、既有收集器调用、公司行动查询展示与原注册表G20项；其他注册项保持线上原值。新增账本为`/var/lib/qount/paper/forward-20261022/dual-engine/g20-cash/forward.json`，由原每日及G20开盘timer调用，不新增服务。原四账户状态、冻结合同、旧历史和真实执行权限不改。

新账本除息记应收、付款日收盘转现金，未知付款日不使用；BIL金额/付款日核对发行人，税务与未核验金额精度限制见[结果](../state/research_runs/g20_cash_repair_20261025/report.md)。2026年204点全部标为本次历史重建，发布后新观测按真实时间追加。13:10发布后API为7条模拟/11条研究、ingest ok、stale/missing 0；G20累计21.3875%、MDD15.9479%，原18.5649%曲线保留作对照。其他10条线金融行、原四账户状态及实盘保护文件不变，orders/fills/macro_stops仍2/0/0；仅重启只读API一次。`published.json`和`verification.json`记录实际核对，`backup/`保留原源码、注册表及查询库一致性备份。

本发布回退会拒绝覆盖后续源码/其他注册项，恢复原源码与注册表后从当前来源重建派生查询并重启API；保留新现金账本、原模拟状态和真实账户，不用旧SQLite覆盖后续金融状态：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/g20-cash-20261025/publish.py --rollback'
```

## 模拟公开日线容错及精度修复（2026-10-23 15:01 UTC）

owner要求修复ETF HTTP 501和Dual-Engine未推进。发布`/root/qount-releases/paper-input-repair-20261023T145537Z/`，仅更新`src/qount/research_data/paper_daily.py`。腾讯主/备用节点分别成对取得原始及复权日线，完整校验后写缓存；明确结束日期，避免开放查询追加两位小数复权报价而与三位小数原始收盘不一致，旧查询缓存不复用。Yahoo完整OHLC/日期校验移入双节点重试，不放松校验或填造价格。

`backup/`保留原模块、模拟账户状态与SQLite一致性备份，未备份凭据。Dual及research-paper既有服务实际运行成功；7条模拟/11条研究、ingest ok，Dual四账户各304条至22日，ETF3266条至23日。原净值与交易前缀一致，第二次运行无重复追加；27项本地测试、VPS六项故障回归及三标的公开日线校验通过。实盘源码、交易service/timer哈希与执行计数2/0/0不变，未重启API。恢复过程和校验结果见本目录`before.json`、`verified.json`。

回退只恢复原模拟输入模块，拒绝覆盖后续版本，保留已追加的模拟记录、缓存、真实账户和调度：

```bash
ssh qount-vps 'python3 /root/qount-releases/paper-input-repair-20261023T145537Z/rollback.py'
```

## 宏观日线空值与提前预取修复（2026-10-22 14:25 UTC）

owner要求修复BLOCKED、增加重试、提前获取数据并分析补单。14:00故障来自Yahoo两节点13个代理10月21日日线全部空值，非币安订单拒绝。发布`/root/qount-releases/qount-macro-daily-20261022T142200Z/`，仅`src/qount/research_data/macro_live.py`、`src/qount/execution/macro_live.py`、`scripts/operations/run_macro_1atr.py`。校验失败切换节点；预取最多4次、轮间退避1秒，正式窗口最多2次，各5秒超时。沿既有小时timer在纽约交易日17:00、06:00、09:00预取；保留同日期有效缓存、最新完整日线检查和90秒下单截止。

周期锁内确认真实空仓及无挂单，备份三文件、SQLite、状态和原失败收据；将Mac当天10:41 UTC保存的13份完整Yahoo原始快照按原字节/哈希恢复到运行缓存，研究源未改。`input-sources.json`记录来源及时间，`release.json`记录源码/保护文件哈希，`read-only-check/result.json`保留隔离状态和仅GET客户端回查：14:00为`HOLD_NO_SIGNAL / candidate_count=0 / regime_off`，不补单。76项本地相关测试通过；VPS候选67项运行、1项缺历史缓存跳过。线上全部代理日期及8合约公开输入实际校验成功，14:26:30运行既有自动service为`HOLD_MISSED_DECISION`、exit 0；持仓、普通/Algo挂单均0，执行计数2/0/0未变，预算/配置/service/timer哈希保持原值，API未重启。

回退在VPS原服务环境加载后执行（脚本不加载或复制凭据）：

```bash
cd /root/qount
PYTHONPATH=src .venv/bin/python /root/qount-releases/qount-macro-daily-20261022T142200Z/publish.py --rollback
```

回退会检查当前代码仍属本发布、账户新鲜空仓且无未决状态，仅恢复三处源码；保留真实执行库、状态、已校验公开缓存及timer。原始失败收据保留在发布目录`backup/live-result.json`，不把事后诊断写成正式决策。

## 25%风险预算优化发布（2026-10-20 08:12 UTC）

owner明确要求“优化并发布”，08:12:19 UTC发布`/root/qount-releases/macro-risk25-20261020T081024Z/`，仅三个文件：

- `src/qount/strategies/macro_1atr.py`：压力预算50%→25%，入场和既有资金费续期均读取此常量。
- `scripts/operations/run_macro_1atr.py`：收据从同一常量读取预算，避免运行值与展示值不一致。
- `web/app/index.html`：当前策略说明同步25%。

保留原信号、八资产、成交量容量、20倍名义上限、50倍设置杠杆上限、7/21天期限和小时自动timer。没有部署盘口扩容、2x名义上限或部分续期减仓实验。

发布前及08:19发布后直接GET确认USDT权益15.27112826、无持仓、普通挂单或Algo挂单；周期锁内备份原三文件、执行SQLite、状态及旧收据。SQLite quick_check与源文件备份哈希核对通过；回退保留真实账本与后续状态，不用旧快照覆盖。136项相关Python测试、7项前端测试、仓库检查通过；旧50%研究控制及新25%候选入场几何、资金费预算和时间因果核对通过。回退导入校验兼容旧版字面量预算收据，已在隔离进程验证，未执行线上回退。

08:12:34 UTC运行既有`qount-1atr-auto.service`返回`auto_live / WAIT_NY_1000 / FLAT`、预算0.25、exit 0。08:18核对timer active/enabled、API health ok、PID368717未变；代码/HTTP哈希匹配，接口预算0.25。执行orders/fills/macro_stops仍2/0/0（2条为原有记录），无新增订单或成交。下一检查09:00:05 UTC，下一允许入场14:00 UTC（北京时间22:00）。源站和Mac公网匿名请求均401；VPS公网请求被Cloudflare以403拒绝，按网络视角单独记录，没有改动边缘访问配置。保护文件哈希、交易服务和timer配置保持一致，未重启API。

发布记录为`release.json`、`published.json`、`verification.json`；回退先确认账户新鲜空仓、无未决状态和当前源码仍属本发布，拒绝覆盖后续版本：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/macro-risk25-20261020T081024Z/rollback.py'
```

回退仅恢复三个代码/页面文件，预算恢复50%，保留真实执行库、状态和原timer；只用于本次发布故障恢复。

## Yahoo行情代理路径修复（2026-10-20 14:26 UTC）

owner要求“修复根因查看”。正式14:00周期再次`URLError`；加载服务环境代理后两个Yahoo节点均约5秒超时，局部无代理直连约0.5秒成功。发布`/root/qount-releases/macro-yahoo-direct-20261020T142700Z/`，只替换`src/qount/research_data/macro_live.py`：Yahoo日线使用独立`ProxyHandler({})`，保留双节点各5秒和原数据校验，不改环境或币安客户端。

周期锁内直接GET确认空仓及无普通/Algo挂单，备份原源码、执行SQLite、宏观状态和失败收据。65项本地测试通过；VPS回归48通过/1缺历史缓存跳过。公开GET实际补齐13份10月19日日线并验证8合约小时/资金费/容量输入，约6秒。隔离副本仅GET回查今日14:00为`HOLD_NO_SIGNAL / candidate_count=0`，只作事后输入诊断，不替代正式失败记录。随后既有自动service成功返回`14:26:52Z / HOLD_MISSED_DECISION`，未补单；只读observer刷新后运行状态`AUTO`，API未重启。直接GET再次确认空仓、普通/Algo挂单均0，USDT权益15.27112826，执行计数仍2/0/0；策略、配置及service/timer哈希不变。

发布源码及备份哈希、保护文件哈希和前后账户核对分别保存在`release.json`与`verified.json`；隔离诊断在`read-only-check/`。回退检查当前源码属于本发布、账户新鲜空仓且无未决单/状态，仅恢复源码，保留真实账本、缓存、状态及timer：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/macro-yahoo-direct-20261020T142700Z/publish.py --rollback'
```

## 入场公开输入容错修正（2026-10-19 14:24 UTC）

今日14:00正式周期报`input_or_exchange_error:URLError`，仍空仓、无新订单。原收据无法确定底层网络原因；复查两个Yahoo节点均恢复可达。按本轮发布并运行授权，补发`/root/qount-releases/macro-input-retry-20261019T142435Z/`，仅`src/qount/research_data/macro_live.py`与`src/qount/execution/macro_live.py`：公开日线最多两个节点各5秒，在原每小时周期的纽约交易日09:00空仓分支预取已完成日线；失败不占用正式决策、不使用旧数据。策略、档位修正、权限及服务/timer配置保持原值。

175项相关测试与仓库检查通过。空仓及周期锁内备份两文件、执行SQLite、状态和失败收据；哈希与导入验证通过。13个代理文件截至10月16日、8个合约历史已实际预热；14:25在本发布的`read-only-check/`隔离副本与仅GET客户端回查14:00信号，得到XLE0.47/8x候选，非实际可成交证明。随后重新运行既有自动service，14:25:42收据`HOLD_MISSED_DECISION / entry_decision_window_expired`、exit 0，未补单。14:26核对timer active，执行orders/fills/macro_stops计数仍2/0/0，空仓；下一入场10月20日14:00 UTC。

回退仅恢复本轮两个源码文件，保留真实账户/执行账本与timer；检查当前文件仍属本发布且账户新鲜空仓：

```bash
/root/qount/.venv/bin/python /root/qount-releases/macro-input-retry-20261019T142435Z/rollback.py
```

先回退本轮才能回退早先档位补丁；旧发布的哈希保护会拒绝覆盖后续代码。取消本轮会失去预热与有界重试，不改变真实档位修正。

## 逐合约保证金档位修正（2026-10-19 UTC）

owner要求“先发布优化后的策略并运行”，09:23 UTC发布`/root/qount-releases/macro-brackets-20261019T092306Z/`：仅`src/qount/strategies/perpetual.py`与`src/qount/execution/macro_live.py`。取消统一维持保证金不超过1%的拒绝门槛，以账户真实档位约束杠杆、名义金额与清算距离；下单前重查。研究参数仍50%压力预算、20倍名义上限、原10%分钟量容量，不发布容量/风险实验变体。

163项相关测试及仓库规范检查通过；在空仓、无订单、周期锁内备份代码、执行SQLite和状态，数据库quick_check通过。源码哈希、运行导入、策略配置和服务/timer哈希核对通过。立即启动既有`qount-1atr-auto.service`，09:23:26 UTC收据`auto_live / WAIT_NY_1000 / FLAT`，exit 0；自动timer active，订单/成交/保护表计数未增加（orders表2条为既有记录）。账户权益15.27112826USDT。未重启API，下一允许入场10月19日14:00 UTC。

回退只恢复这两个源码文件，保留真实账本和timer；需新鲜空仓观测、无未决状态及当前文件仍属本发布：

```bash
/root/qount/.venv/bin/python /root/qount-releases/macro-brackets-20261019T092306Z/rollback.py
```

回退会重新引入旧1%门槛，应仅用于本修正故障恢复。

## 跨年日历维护（2026-10-18 UTC）

owner要求“先补齐日历支持”，发布`/root/qount-releases/calendar-20261018T071711Z/`，仅`src/qount/research_data/bars.py`与`src/qount/execution/macro_live.py`两文件。按[NYSE官方日历](https://www.nyse.com/trade/hours-calendars)收录2027、2028休市及提前收市，保留2026全部行为。纽约10:00决策由ZoneInfo换算，提前收市日线仍16:00可用；跨年特征及只读接口的下一允许入场日期使用同一日历。

- 未收录年份仍拒绝新仓；已有持仓先做已知退出、保护与已完成小时移动止损，续期日历未知按续期失败全平。其余日历检查报阻塞，保留原生止损，不默认把未知年份当交易日。
- 本地121项相关Python测试通过，含365天旧日历逐日比较、休市/提前收市、夏令时、跨年特征/接口、未知年份保护和退出。原基础/双成本完整曲线及成交精确复现；VPS两份离线测试共43项，42项通过、1项缺本地历史行情缓存而跳过，使用替身交易所及临时状态，无真实下单。
- 发布前既有observer确认账户空仓，在周期锁内备份两个原文件、执行SQLite及宏观状态/收据，SQLite quick_check通过。`release.json`保存前后源码与受保护文件哈希，`before/`为原代码、`state/`为执行状态备份；未复制凭据或覆盖真实账本。
- 只读API重启一次；交易timer、service配置、策略参数、资产映射、纯策略函数与Caddy哈希不变。07:18 UTC核对当前两文件与保护文件哈希匹配，API/自动timer active、AUTO、无HALT、空仓、USDT权益15.27112826、新策略订单0；下一允许入场仍为10月19日14:00 UTC。

回退只恢复本轮两文件并重启只读API，保留执行/账户状态和timer配置；要求新鲜空仓观测、无持仓/未决状态且当前文件仍属本发布，否则拒绝覆盖。恢复旧日历会重新限于2026，跨年后不能把回退当作继续运行的方案：

```bash
ssh qount-vps 'python3 /root/qount-releases/calendar-20261018T071711Z/rollback.py'
```

## 到期退出与必要告警修复（2026-10-17 UTC）

owner在精简设计后要求“执行”。发布目录`/root/qount-releases/live-reliability-20261017T132315Z/`，共9个源码/部署模板文件；实际observer新增通知库环境drop-in，未新增timer或服务。既有自动交易周期配置、原策略参数/资产映射和Caddy保持原值；只读API主动重启一次。发布前核对账户空仓、无未决状态，持有既有周期锁时保存执行库和宏观状态。

- 到期退出提前于非必要查询，明细采集不再作为风险退出前置；续期income未知按原续期失败规则退出。保留原client ID核对、实际数量边界和原生保护，部分退出/超时/重启场景经回归验证。未实际触发新策略开平仓。
- 两个0700入口目录仅所有者修正为root，模式不变；既有通知重试与账户observer在实际服务约束下成功。通知通过独立observer复用原通知库/重试；失败、阻塞、timer停止及收据过期去重通知，恢复只提示一次，普通等待不推送。通知失败不阻塞执行，不覆盖VPS整机失联。
- 前端依据实际timer/服务与周期收据展示状态，透出最近正式决策/拒绝原因，并读取实际微信投递结果。历史微信`ret=-2`失败在owner发送新入站消息刷新会话后恢复；13:31:55 UTC一条明确授权的验收通知首次发送即获`DELIVERED`，只表示通道接受。投递诊断两文件补丁记在`release.json`内，当前哈希已更新，原版备份在`delivery-diagnostic-before/`。
- `state/`包含执行库、宏观状态/收据与账户历史备份；SQLite使用backup API，隔离恢复的quick_check及JSON身份核对通过，凭据不在备份内。同机副本用于误操作恢复，不作为异机灾备。
- 129项相关Python、17项前端测试通过；核心发布版本正式浏览器六宽度回归通过。投递诊断两文件补丁后浏览器重跑因SSH转发中断未完成，另行直连SSH核对API/自动timer active，API结果、当前9文件及静态HTTP哈希通过。13:24 UTC核对收据13:00:05为`WAIT_NY_1000`，空仓、无HALT、新策略订单0，USDT权益15.27112826；13:34 observer返回AUTO及通知通道接受状态。跨年日历未在本轮扩展。

代码回退先核对当前9文件哈希且要求宏观状态空仓、无未决意图；只恢复源码及observer通知库drop-in，保留真实账户/执行状态和目录所有者修正，不停交易timer，不恢复错误的旧策略。遇后续版本拒绝覆盖，执行前必须另行只读核对交易所实际仓位及未决单：

```bash
ssh qount-vps 'python3 /root/qount-releases/live-reliability-20261017T132315Z/rollback.py'
```

本次修复沿用既有宏观实盘修正与本轮“执行”授权，不扩大资金、策略或真实交易权限。当前状态见[current](current.md)，实施范围及按需项见[设计计划](system-improvement-design-plan-2026-10.md)。

## 个人系统、真实收益与研究查询发布（2026-10-16/17 UTC）

owner明确要求发布并更新计划。发布目录`/root/qount-releases/personal-system-20261016T153000Z/`。2026-10-16 15:35 UTC切换24个账户/查询/前端文件，含随后补丁共主动重启API两次。沿用实际查询库`/var/lib/qount/api/candidates/assets-20261015T105250Z.db`及原注册表环境路径；不更改Caddy、交易配置、权限或调度。源文件、注册表、查询库备份在`before/`，交付与保护文件哈希在`delivery.json`，发布收据在`published.json`。

- 研究目录11条，10条历史来源可读；宏观和简化1ATR分别展示，按run切换/对照/查询成交。通用状态前向来源仍缺失，严格前向模拟0条；历史来源可读不等于新鲜前向或实盘授权。
- 采集修复兼容历史缺少派生字段，保留原始payload；真实数值冲突仍拒绝覆盖。既有observer手动只读刷新并继续原定时器，成交和income成功持久化。
- `/account/performance`读取真实USDT权益和income，链式Modified Dietz调整划转；含手动及旧策略交易，未知区间断开，不冒充当前策略独立收益。
- 2026-10-17约03:10 UTC补3文件修正：极小额BNB保证金不再抑制USDT权益，其他保证金保留未估值；前端明确USDT口径。补丁直接GET真实资产验证，3文件的初版备份位于`hotfix-before/`；`delivery.initial.json`保留初版哈希，`delivery.json`为当前哈希。账户/文案补丁无需重启API；随后修正快照微秒与income毫秒边界时重启只读API一次，交易服务未重启。
- 2026-10-17 03:15 UTC复核：API active/running、NRestarts=0，成交11/income27采集成功；收益467点、2段且覆盖最新观测，136个旧权益缺项保留。正式浏览器回归通过，源站四路径及Mac公网匿名首页401；HTTP/磁盘与交易保护文件哈希一致。
- 首次发布后权益采集的缺口（10月16日15:36起至17日03:10前）保留，恢复后新段独立起算；不删除或补造历史。候选使用实时资产GET的检查已补上，防止仅验证历史快照遗漏当前资产范围。

完整回退仅恢复本轮代码、注册表和派生查询缓存，**不恢复或删除真实资产历史、账户成交、策略执行账本，不停交易定时器**。先检查当前文件仍匹配本发布哈希，遇后续版本拒绝覆盖：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/personal-system-20261016T153000Z/publish.py rollback'
```

本轮只读发布授权不扩大当前宏观策略的交易范围。后续研究优先事项与已完成事项见[更新计划](personal-system-consolidation-plan.md)，当前运行事实见[current](current.md)。

## 宏观实盘实现修正与旧仓交接（2026-10-16 13:46 UTC）

owner要求修正实盘，并选择“保留原保护单，旧仓结束后由新策略接管”。当前执行ID为 `rolling7_risk_no_chase_mr_signal_gap_1atr`；不再使用简化SMA120入口。8个ETF宏观信号、禁止追涨、均值回归信号至入场1ATR跳空门、50%资金压力预算、20倍名义上限／50倍设置上限、实际清算距离与成本容量约束均沿用选定研究。趋势持有至多7天，均值回归至多21天、每7天资金费复核，失败全平；2R后按已完成小时收盘更新2ATR移动止损。

- `qount-1atr-auto.timer` 改为 `*-*-* *:00:05 UTC`，无随机延迟、无Persistent补单；仅纽约交易日10:00允许入场，90秒过期拒绝补单。旧plan timer仍disabled。API保持只读，新旧策略成交分开归属。
- 新执行 `scripts/operations/run_macro_1atr.py --execute`；`--check`只读核对；`--warm-inputs`仅更新公开行情。状态／SQLite／公开缓存位于 `/var/lib/qount/1atr/`。新仓使用Algo接口、CONTRACT_PRICE、reduce-only STOP_MARKET；原CL的MARK_PRICE单保持不动。重启查询原client ID，不重复创建未知订单；限价IOC按实际成交数量保护，替换止损先确认新单再撤旧单。
- 122项相关Python与9项JS测试通过；基础成本7笔、双成本1笔的原研究完整回放精确复现，实盘入场函数在8个历史入场点的排序、数量、止损、杠杆、预算一致。候选公共输入已更新至10月15日ETF收盘，并续接8个原生合约小时缓存；只是代码与历史一致性验证，尚无新策略真实成交验证。
- 发布后服务success，收据13:46:29Z为 `HOLD_LEGACY_POSITION`。交易所发布前后均为CL多头0.15、均价96.10，原保护单 `q1atr-stop-9486bf417a70f630 / NEW / 90.06 / MARK_PRICE`，普通订单0；未提交新订单、撤旧保护或修改旧仓设置。
- 本次只部署22个运行／规则文件、窄改账户状态函数和实盘HTML／JS，共25个文件；不发布整体导航整理、不改Caddy、凭据、账户observer/publisher的服务配置或其他策略。备份 `/var/lib/qount/1atr/releases/20261016T134622Z-macro-fix/`。回退恢复代码与只读页面，**停用自动timer并保留实际成交数据库和运行状态**，不自动恢复错误的旧策略交易。

```bash
ssh qount-vps 'python3 /var/lib/qount/1atr/releases/20261016T134622Z-macro-fix/rollback.py'
```

本节是owner明确授权的生产修正，其余历史只读发布的默认边界不扩大。当前事实以 [current.md](current.md) 为准。

## 账户真实成交与资金流水发布（2026-10-16 UTC）

owner要求增加真实交易记录，发布目录 `/root/qount-releases/account-records-20261016/`。六文件：新增 `src/qount/operations/account_trades.py`，更新只读observer、账户API路由、`index.html`／`app.js`／`live.js`。仅调用币安GET `/fapi/v1/userTrades` 与 `/fapi/v1/income`；Agent未读取、传输或修改凭据文件，既有采集服务按原配置使用凭据。查询近7天、持久保留，先收入查询再扩展成交合约范围；账户记录不自动归属1ATR。页头“下单未启用”描述实际运行状态，不以“未授权”否定owner已经提出的请求。

- 新数据：`/var/lib/qount/account-trades.sqlite3`，0600；既有资产库、查询库及严格legacy observation不改结构。首次8笔成交、22条资金流水，9个合约采集成功，包括收入流水发现的XRPUSDT，无错误。新只读端点 `/account/trades?limit=100`，上限500。
- 19项账户、52项API、16项前端检查通过；VPS候选独立路由测试无私有请求；候选／正式五页六宽度无JS错误或溢出，真实8／22条渲染一致。记录分页预算、缺口、不可用、去重与冲突都有明确状态，不以空列表伪装查询失败。
- 六文件磁盘及三静态HTTP哈希匹配，API为新路由重启一次后PID299959、NRestarts=0、active、health正常。既有 `qount-dashboard-account-observer.service` 手动运行一次成功，未增加／修改定时器；Caddy哈希与认证不变，源站匿名新接口401。没有启用交易服务、划转、撤单或下单。
- 代码备份 `before/`，交付清单 `delivery.json`，收据 `published.json`。回退保留真实交易数据库，仅恢复代码并重启只读API；存在后续版本时拒绝覆盖。

```bash
ssh qount-vps 'python3 /root/qount-releases/account-records-20261016/publish.py rollback'
```

接口依据：[币安成交查询](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List)、[收入流水查询](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Get-Income-History)。当前官方文档限制单次成交时间窗7天且fromId不能与时间范围混用；实现使用时间分割，明确不承诺账户全生命周期历史覆盖。

## 实盘只读页发布（2026-10-16 UTC）

按owner要求增加“实盘”前端入口，发布 `live-view-20261016T034500Z`，仅 `web/app/index.html`、`app.js`、`style.css` 与新增 `live.js` 四文件。页面展示1ATR宏观杠杆候选、变化中的USDⓈ-M USDT权益／可用余额、模型压力预算参考及账户持仓；读既有 `/account/assets`，不新增账户请求服务。显式标记自动交易未启用、实时策略信号／实盘账本未接入，收益不使用回测代替。资产来源失败清空，过期暂停预算参考，手机导航使用短标签容纳第五页。

- 147项相关Python、15项前端测试通过；候选与正式SSH转发的Chrome五页×六宽度（320／375／500／768／1200／1440px）无溢出或JS错误，动态80／60／40、失败及过期场景通过。截图位于Mac `/tmp/qount-live-view-20261016/`。未测手机真机或认证域名浏览器。
- 发布前核对与线上原三文件逐字差异，备份位于 `/root/qount-releases/live-view-20261016T034500Z/before/`，交付清单 `delivery.json`、发布收据 `published.json`。四文件磁盘与HTTP哈希一致，API PID278518、NRestarts=0、active、health正常；不重启API，不改数据库、服务单元、Caddy、密钥、observer或publisher。
- Caddy哈希保持不变；源站匿名 `/`、`/live.js`、`/account/assets` 均401，Mac公网匿名首页401。VPS自身通过公网域名探测曾403，与源站401分别记录，不将403当作登录验证。
- 离线动态资金改动留在Mac研究内核，不部署至交易服务；原先15.3049911USDT的审阅仅为起始本金测试。页面没有划转、撤单、开仓或启用交易控件。

仅回退本轮四个静态文件（先检查当前与备份哈希，遇后续版本拒绝覆盖；无需重启）：

```bash
ssh qount-vps 'python3 /root/qount-releases/live-view-20261016T034500Z/publish.py rollback'
```

## 气泡堆叠上下文修复发布（2026-10-15 14:31 UTC）

owner 反馈“气泡框被遮挡了”，随后授权“发布”。根因是 14:16 那轮未真正解决的一处堆叠上下文问题：`#mascot-bubble` 位于 `.asset-hero` 子树内，而 `.asset-hero { isolation: isolate }` 创建了独立堆叠上下文，把气泡的 `z-index:60` 困在 hero 内部；`isolation` 不改变 fixed 定位的包含块，故 `overflow:hidden` 并未裁剪它，真正问题是其 z-index 无法与根上下文里 `z-index:50` 的粘性 `.topbar` 竞争，气泡永远压在顶栏之下。`isolation:isolate` 是 hero 内 `z-index:-1` 装饰伪元素可见的前提，不能移除。

修复只改 `web/app/app.js` 的 `mascotSay`：显示时把气泡幂等地迁移到 `document.body`，让其 `position:fixed; z-index:60` 在根堆叠上下文中解析并稳定高于顶栏；同时在 `.mascot-stage` 未布局（尺寸为 0，例如账户屏隐藏时跨标签 `fetchAlerts` 触发）时保持气泡隐藏、不再误定位。

- 发布目录：`/root/qount-releases/bubble-20261015T143131Z/`，含 `static-before/app.js`（原 `200f5685…`）、`app.js.new`（`0f56190…`）、`manifest.json`、`backup.json`、`published.json`、`rollback-static.py`。`StaticFiles` 按请求读盘，**未重启服务**。
- 本地：`node --check` 通过、12 项前端测试全绿、hygiene `ok:true`；浏览器几何验证气泡上线后 `parentElement===body`、`closest('.asset-hero')` 为 false、与顶栏交叠处 `elementFromPoint` 命中气泡本身、隐藏标签守卫使气泡保持 `hidden`。
- 唯一变更文件核对：本地 `style.css`／`research.js`／`index.html` SHA-256 与线上逐字相符，仅 `app.js` 变化；发布前与 `static-before` 备份哈希相符后才原子 `mv` 覆盖。
- VPS：暂存／磁盘／HTTP（经 `localhost:8000`，不含凭据）三处 `app.js` SHA-256 均为 `0f56190…`；`qount-api.service` MainPID `278518` 未变、`NRestarts=0`、`active`；health `ok`、9 条线、`research_only=true / orders_authorized=false`；公网未认证 `/`、`/app.js`、`/account/assets` 均 `401`，Caddy 认证与路由逐字未改。未改 API 代码、数据库、systemd、凭据或 timers。
- 诚实边界：浏览器验证以 `evaluate_script` 几何与 DOM 关系取证，未取像素截图；应用内浏览器文档处于隐藏态会暂停 CSS 动画，故透明度类读数不可信，改以堆叠链／命中测试为准。认证域名浏览器与手机真机仍未验收；3–5 日观察期继续。

仅回退本轮（脚本先核对线上 `app.js` 仍属本轮或原版，否则拒绝覆盖）：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/bubble-20261015T143131Z/rollback-static.py'
```

恢复 `static-before/app.js`（`200f5685…`，即 14:16 那版），无需重启；不要用上一轮三文件整包回退替代这一步。

## 交互、曲线与气泡修复发布（2026-10-15 14:16 UTC）

owner 要求把本轮前端修复部署到 VPS。纯静态三文件增量：`web/app/app.js`、`index.html`、`style.css`；`research.js` 与 `assets/` 未改，沿用上一发布。内容为曲线开关修复（`setOption` notMerge + datazoom 监听只绑一次 + `chartRowCount` 闭包）、曲线 emphasis／面积／初始线／最大回撤标注、可点击猫猫人偶与状态气泡、气泡被 hero 裁剪／尾巴朝向／越界钳制修复、人偶定位级联修复、以及研究卡片 `source.label` 的 XSS 转义。

- 发布目录：`/root/qount-releases/20261015T141617Z/`，含 `static-before/`（原三文件）、`new/`、`manifest.json`、`published.json`、`rollback-static.py`。`StaticFiles` 按请求读盘，未重启服务。
- 本地：`node --check` 通过、12 项前端测试全绿、hygiene `ok:true`、逐条 XSS 审计（仅 `source.label` 一处原始 innerHTML 注入，已修）；人偶与气泡经浏览器 DOM 几何测量（591px 窄窗四档滚动，`inViewport` 全 true、尾巴翻转与越界钳制确认）。
- VPS：暂存／上线／HTTP（经 SSH `localhost:8000`，不含凭据）三处 SHA-256 与清单逐一相符；`research.js` 哈希未变；health `ok`、9 条线、`research_only=true / orders_authorized=false`；`qount-api.service` active、`NRestarts=0`；未改 API 代码、数据库、systemd、Caddy、凭据或 timers。
- 诚实边界：公网 `https://qount.alyaloale.com/` 输入 Basic Auth 后的浏览器验收、手机真机、以及 >600px 宽屏实测均未执行（宽屏以 CSS 级联推断与改版前一致）；3–5 日观察期继续。

仅回退本轮静态界面（脚本会先核对线上三文件仍属本轮，否则拒绝覆盖）：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/20261015T141617Z/rollback-static.py'
```

## 动画、文字与九线目录发布（2026-10-15 12:12 UTC 复验）

按 owner 继续部署及“先整理已接入的 9 条”要求，发布 `ui-20261015T115414Z`。仅更新 `web/app/index.html`、`app.js`、`style.css` 和新增 `research.js`，统一九线名称、分类、结论与数据状态，加入筛选、封存区、页面／卡片／角色动效、刷新反馈及减少动画支持。

- 发布目录：`/root/qount-releases/ui-20261015T115414Z/`，含交付清单、`static-before/` 原三文件、`backup.json`、`published.json` 和 `rollback-static.py`。原文件从上一发布交付件恢复备份并与本轮发布前哈希逐一核对。
- 本地 12 项前端、52 项 API 检查通过；候选及正式服务经 SSH 转发的 Chrome 四页、9 条详情回归通过，视口覆盖 320／375／500／600／768／900／1024／1200／1440px。筛选与搜索、刷新保留条件、减少动画、键盘焦点、延迟／失败／乱序、可见性轮询检查通过，无横向溢出或 JS 错误。未声称手机真机或认证域名浏览器验收。
- 四文件磁盘及 HTTP SHA-256 均匹配清单。既有 API PID `278518` 未变、`NRestarts=0`、health 为 `ok`；真实资产接口 10 钱包、只读且无下单授权。来源仍为 5 条陈旧、3 条缺失，`ingest_status=partial`。
- 未改 API 代码、数据库、服务配置、Caddy 或凭据；observer／publisher timers 均保持 active，公网匿名 `/` 与 `/account/assets` 均返回 401。独立候选验证完成后关闭临时 API 与 SSH 转发。

仅回退本轮静态界面，先核对所有线上文件仍属于本轮，并核对备份哈希；发现后续修改即拒绝覆盖：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/ui-20261015T115414Z/rollback-static.py'
```

脚本恢复原三文件并移除新 `research.js`，无需重启。不要用上一轮资产发布的整包回退替代这一步，以免同时回退 API 和查询库。

## 资产分析发布（2026-10-15 11:30 UTC）

owner 明确要求“优化字标，最后检查修复并上线”，随后要求查找原对话继续部署。本轮续接已准备的候选发布 `assets-20261015T105250Z`，发布 13 个前端、只读账户 API、研究线命名及 observer 文件。真实账户只读采集取得 10 个钱包，合约权益／未实现盈亏完整，正式资产历史从本轮采集开始积累。

- 发布与回退目录：`/root/qount-releases/assets-20261015T105250Z/`，含原代码、`database-before.db`、`backup.json`、`delivery/manifest.json`、`published.json`、`rollback.py`。
- 当前查询库：`/var/lib/qount/api/candidates/assets-20261015T105250Z.db`；旧库保留，未重新摄取或覆盖旧库。
- API 增量配置：`/etc/systemd/system/qount-api.service.d/95-assets-20261015T105250Z.conf`；指定新查询库、真实资产文件和本轮 `registry-vps.json`。该 VPS 注册表使用真实 Dual-Engine／CTA-R 路径和已部署 ETF 工件，避免用 Mac 默认路径摄取后误报缺源。
- 9 条线中 6 条有源，3 条缺源；4 条 Dual-Engine 与 ETF 回放截至 10 月 9 日，明确显示陈旧，CTA-R 截至 10 月 15 日。正式日报仍未配置；不据此生成今日研究状态。
- 本地 61 项 Python、9 项前端检查通过；VPS 候选 56 项通过，5 项因测试硬编码 Mac 路径／历史工件或行情缓存缺失跳过。候选已按 1440／1200／500／375px 检查四页和 500px 的 9 条详情，并核对 ETF 37 笔买卖／1 次拆分。
- 发布后经只读 SSH 转发对正式 `127.0.0.1:8000` 完成同样的四种宽度／四页及 9 条详情复验，无横向溢出或 JavaScript 错误；这是桌面 Chrome 的手机宽度检查，未声称手机真机或认证域名浏览器已验收。正式资产接口为 `AVAILABLE`，首次正式观测 `2026-10-15T11:30:04Z`，历史 1 点；API 为 active、`NRestarts=0`，内存约 55 MB，observer 成功且既有 observer／publisher timer 为 active。公网匿名 `/` 与 `/account/assets` 均为 401。
- Caddy 配置逐字未改，保留认证与既有 relay 路由。observer 复用既有服务与 timer，未新增定时器或交易权限。API／采集 `orders_authorized=false`。

仅在没有后续叠加修改时回退本轮：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/assets-20261015T105250Z/rollback.py'
```

脚本先核对当前文件属于本轮或原版，恢复原代码、移除本轮 API drop-in 并重启既有 API，使其使用原查询库；不改 Caddy、凭据、其他服务或已积累的真实资产历史。若后续代码已改变，脚本拒绝覆盖。

## 最近一次增量发布（2026-10-13 UTC）

owner 明确授权发布后，以 `frontend-20261013T045642Z` 的 15 文件白名单与 SHA-256 清单交付本轮显示整改。先核对并合并部署端已有修复，在独立候选目录、克隆数据库和 `127.0.0.1:8001` 上完成测试与浏览器回归，再同步文件、设置单一 API drop-in 并重启现有 `qount-api.service`。本地其他未提交工作保留；Caddy 配置及认证未改。

- 发布工件与回退资料：`/root/qount-releases/frontend-20261013T045642Z/`，含 `manifest.json`、`code-before.tar.gz`、`database-before.db`、`backup.json`、`published.json`、`rollback.py` 与验证记录。
- 运行数据库：`/var/lib/qount/api/candidates/frontend-20261013T045642Z.db`；原库 `/var/lib/qount/api/candidates/qount-20261012T154000Z.db` 保留。
- 本轮配置：`/etc/systemd/system/qount-api.service.d/90-frontend-20261013T045642Z.conf`，仅指定新 API 查询库与既有 CTA-R 来源目录。
- 验证：本地 API 52 项、窗口计算 6 项通过；VPS 候选 API 49 项通过、3 项因历史源／缓存缺失跳过；候选 1200／500／375px 浏览器回归通过；正式域名认证 Chrome 的实际 1200px 三页与全部 8 条详情通过；生产服务经 SSH 转发的 Chrome 实际 1200／500／375px 三页及 500px 全部 8 条详情通过。认证 Chrome 保留固定 1200px 视口，缩窄窗口不作为窄窗通过证据。手机真机和 3–5 日观察尚待完成。
- 现有 6 条有源线、2 条缺源封存／停止线；`ingest_status=partial` 反映两条缺源。日报只读接口已发布，正式来源未配置时返回 `MISSING`。

仅在当前仍为本轮发布且没有叠加后续变更时，回退使用：

```bash
ssh qount-vps '/root/qount/.venv/bin/python /root/qount-releases/frontend-20261013T045642Z/rollback.py'
```

该脚本恢复本轮覆盖前的代码，移除本轮新增文件与 API drop-in，重新加载并重启 API，使其重新使用原库；不修改 Caddy 或其他服务。

## 0. 执行前必读

### 0.1 现场事实（2026-10-12 实测）

| 项 | 值 | 影响 |
| --- | --- | --- |
| SSH 别名 | `qount-vps`（`8.220.130.35`，`root`） | 本文所有远端命令用它 |
| 应用目录 | `/root/qount`（**非 git 仓库**） | 靠 rsync 同步 |
| Python | `/root/qount/.venv/bin/python` = **3.11.2** | 已兼容 |
| 内存 | **1.6 GB**（已用 ~840 MB，可用 ~840 MB） | **必须 `--workers 1`** |
| CPU | 2 核 | — |
| 磁盘 | `/` 40 GB，已用 16 GB（42%） | 充足 |
| systemd | 252 | — |
| Caddy | v2.11.4 | 支持 `reverse_proxy` |
| 已装 Python 包 | `httpx 0.28.1`、`pydantic 2.13.4` | **缺 `fastapi` / `uvicorn`** |
| 旧前端根 | `/var/www/qount`（`index.html` + `app.js` + `data/v1 → releases/<hash>`） | 保留不动，供回退 |

### 0.2 现有 Caddy 配置

现网 `/etc/caddy/Caddyfile` 是权威副本，包含 relay 路由、Basic Auth 与安全响应头。**不要把配置复制到终端、日志或文档中**。阶段 6 的脚本只在 `qount.alyaloale.com` 站点块中把唯一一条 `file_server` 替换为 `reverse_proxy 127.0.0.1:8000`，其余行逐字保留。

### 0.3 三个必须知道的前提约束

**约束 A：`.gitignore` 忽略 `state/` 与 `/data/`**

```
state/
/data/
```

而 `/market/klines` 读的正是 `state/r0_runtime/klines` 与 `state/grid_b/klines`。同步清单包含 `./config/paper-lines.json`，但**没有 `./state` 和 `./data`**。因此：

> **VPS 上不会有 kline 缓存 → `/market/klines` 会返回空或 404。**
> 若需要行情接口在线上可用，见**阶段 8（可选）**。

**约束 B：静态目录按工作目录解析**

`main.py` 用 `os.path.abspath("web/app")`，即**相对于进程的 WorkingDirectory**。因此 systemd 必须设 `WorkingDirectory=/root/qount`，否则前端挂载失败、`/` 返回 404。

**约束 C：服务启动时会自动建库并 ingest**

`main.py` 的 `lifespan` 里：若 `paper_lines` 表为空，**自动调用 `run_ingest()`**。systemd 将 `QOUNT_DB_PATH` 指向 `/var/lib/qount/api/qount.db`，并只为该目录开放写权限；不在 `/root/qount/state/` 建库。

### 0.4 总览：8 个阶段

| 阶段 | 内容 | 是否需要停机 | 可回退 |
| --- | --- | --- | --- |
| 1 | Mac 提交代码 | 否 | — |
| 2 | 同步代码到 VPS | 否 | 覆盖前的文件需备份 |
| 3 | 装依赖 | 否 | `pip uninstall` |
| 4 | 手动跑通（端口 8001） | 否 | Ctrl-C |
| 5 | 装 systemd 服务 | 否 | `systemctl disable` |
| 6 | **Caddy 反代切换**（真正的替换点） | **是**（reload 约 1 秒） | 一条命令 |
| 7 | 验证与并行观察 | 否 | 阶段 6 回退 |
| 8 | 行情接口（可选） | 否 | 删软链 |

**阶段 6 之前，`https://qount.alyaloale.com/` 完全不受影响。**

---

## 阶段 1：Mac 提交代码

`sync-to-vps.sh` **要求工作区干净**（`git status --porcelain` 为空），否则拒绝同步。

```bash
cd /Users/alyaloale/Code/qount
git status --short
```

### 1.1 检查是否有敏感文件

```bash
git status --short | grep -E '\.env|\.key|secret|token' || echo "无敏感文件"
```

**必须是"无敏感文件"。** `.env`、`*.key`、密钥文件**绝不能提交**。

### 1.2 提交

```bash
git add -A
git commit -m "feat(api): 前后端重写 P0-P4、dual_engine 适配器改读真实快照、VPS 部署手册

- dual_engine 适配器移除硬编码假数据，改读 paper_program_snapshot.json
- 兼容真实快照字段名 executable/signal（原 executable_nav 读不到任何点）
- 无源数据一律返回 MISSING 并置 metrics=None，不再回退到默认值
- 四账户 G20/C60/GC5/D15 拆分为独立研究线
- /account 拆为 PAPER 与 /account/live 只读真实账户两个端点
- 前端账户屏改为双栏：真实账户与模拟盘分列，不合并
- 新增 VPS 部署执行手册"
```

**验证**：

```bash
git log --oneline -1
git status --porcelain          # 必须输出为空
```

**失败判据**：`git status --porcelain` 仍有输出 → 有未提交文件，回到 1.1 检查。

---

## 阶段 2：同步代码到 VPS

### 2.1 先备份 VPS 现状（重要）

VPS 不是 git 仓库，**没有版本控制兜底**，所以先备份：

```bash
ssh qount-vps 'backup=/root/qount-backup-$(date +%Y%m%d%H%M%S).tar.gz
 tar czf "$backup" \
  --exclude=qount/state --exclude=qount/.venv --exclude=__pycache__ \
  --exclude=qount/.env --exclude=qount/deploy/wsl/qount-compute.env \
  --exclude="*.env" --exclude="*.key" --exclude="*.pem" \
  -C /root qount && stat -c "%n|%s bytes" "$backup"'
```

**预期**：输出一个约几 MB 的 `.tar.gz`。

### 2.2 试运行（不实际传输）

```bash
cd /Users/alyaloale/Code/qount
scripts/sync-to-vps.sh --dry-run
```

**先看它打算传什么。** 重点确认列表中**没有 `.env`**、没有密钥。

**失败判据**：出现 `.env` 或任何密钥 → **停止**，先查为什么会被纳入。

### 2.3 实际同步

```bash
scripts/sync-to-vps.sh
```

> ⚠️ **第一次同步绝对不要加 `--delete`。** 不加时 rsync 只增改不删除，安全。

**预期输出**：`synced to qount-vps:/root/qount`

### 2.4 验证

```bash
ssh qount-vps 'ls /root/qount/src/qount/api/ && echo "---" && ls /root/qount/web/app/'
```

**预期**：列出 `api/` 下 14 个文件（`main.py`、`db.py`、`ingest.py`、`schemas.py`、`adapters/`、`routes/`）与 `web/app/` 下 `index.html`、`app.js`、`style.css`、`vendor/`。

**失败判据**：任一缺失 → 检查 `sync-to-vps.sh` 的 `items` 数组是否包含 `./src/qount` 与 `./web`。

### 回退

```bash
ssh qount-vps 'cd /root && tar xzf qount-backup-<时间戳>.tar.gz'
```

---

## 阶段 3：安装依赖

```bash
ssh qount-vps 'cd /root/qount && ./.venv/bin/pip install fastapi "uvicorn[standard]"'
```

**预期**：安装 `fastapi`、`uvicorn`、`starlette`（`pydantic` 与 `httpx` 已存在）。

### 验证 1：包已装

```bash
ssh qount-vps '/root/qount/.venv/bin/pip list | grep -iE "fastapi|uvicorn|starlette"'
```

### 验证 2：应用可导入（关键）

```bash
ssh qount-vps 'cd /root/qount && PYTHONPATH=src ./.venv/bin/python -c "
from qount.api.main import app
print(\"app.title =\", app.title)
print(\"routes =\", len(app.routes))
"'
```

**预期**：打印 `qount API` 与路由数（约 10+）。

**失败判据**：`ImportError` / `ModuleNotFoundError` → 说明阶段 2 未传全，或 Python 3.11 有语法不兼容。**在阶段 3 解决，不要往下走。**

### 回退

```bash
ssh qount-vps 'cd /root/qount && ./.venv/bin/pip uninstall -y fastapi uvicorn starlette'
```

---

## 阶段 4：手动跑通（端口 8001，不影响线上）

### 4.1 启动

```bash
ssh qount-vps 'cd /root/qount && \
  QOUNT_PAPER_STATE_ROOT=/var/lib/qount/paper/dual-engine \
  QOUNT_CTA_R_STATE_ROOT=/var/lib/qount/research/cta-r-forward \
  QOUNT_ACCOUNT_OBSERVATION_PATH=/var/lib/qount/blocked_runtime_observation.json \
  QOUNT_DB_PATH=/tmp/qount-api-manual.db \
  PYTHONPATH=src ./.venv/bin/python -m uvicorn qount.api.main:app \
  --host 127.0.0.1 --port 8001'
```

**保持这个终端开着。** 另开一个终端做下面的验证。

### 4.2 逐项验证

#### 验证 A：健康检查

```bash
ssh qount-vps 'curl -s localhost:8001/health'
```

**预期**：

```json
{"status":"ok","db_connected":true,"last_ingest_at":"...","paper_lines_count":8,
 "safety":{"research_only":true,"orders_authorized":false}}
```

**失败判据**：`paper_lines_count` 不是 8 → 注册表未正确加载，检查 `config/paper-lines.json` 是否同步。

#### 验证 B：四账户读到真实快照（**最关键**）

```bash
ssh qount-vps 'curl -s localhost:8001/paper/lines | python3 -m json.tool'
```

**预期**：8 条线。四条 `dual_*` 应为：

| line_id | status | freshness |
| --- | --- | --- |
| `dual_g20` | `ACTIVE_PAPER` | `FRESH` 或 `STALE` |
| `dual_c60` | `ACTIVE_PAPER` | 同上 |
| `dual_gc5` | `ACTIVE_PAPER` | 同上 |
| `dual_d15` | `ACTIVE_PAPER` | 同上 |

且 `error` 为空（FastAPI 可序列化为 `null`）。

`cta_r` 应从 `/var/lib/qount/research/cta-r-forward/forward-ledger.jsonl` 读取哈希链账本，显示 `ACTIVE_PAPER` 和前瞻净值点；若账本缺失或校验失败，必须为 `MISSING` 且无业绩数字。

**失败判据（重要）**：四条 `dual_*` 的 `status` 是 `MISSING` 且 `error` 含 `SNAPSHOT_NOT_FOUND`
→ `QOUNT_PAPER_STATE_ROOT` 没生效，或快照路径不对。排查：

```bash
ssh qount-vps 'ls -la /var/lib/qount/paper/dual-engine/current/paper_program_snapshot.json'
```

若文件不存在，改用 `find` 定位后再调整环境变量。

#### 验证 C：单条线详情（含净值曲线）

```bash
ssh qount-vps 'curl -s localhost:8001/paper/lines/dual_g20 | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(\"status:\", d[\"status\"], \"| as_of:\", d[\"as_of\"])
print(\"nav points:\", len(d[\"nav_series\"]))
m = d.get(\"metrics\") or {}
print(\"YTD:\", m.get(\"ytd_return_pct\"), \"% | MaxDD:\", m.get(\"max_drawdown_pct\"), \"%\")
print(\"holdings:\", [(p[\"symbol\"], round(p[\"weight\"]*100, 2)) for p in d[\"positions\"]])
"'
```

**预期**（应与截图一致）：

```
status: ACTIVE_PAPER | as_of: 2026-10-09
nav points: 291
YTD: 15.26 % | MaxDD: -16.33 %
holdings: [('BIL', 77.81), ('ERX', 21.4)]
```

**失败判据**：`nav points: 0` → 快照字段名不匹配，**立即停止并报告**（这是已修过的缺陷，若复现说明同步的代码不是最新版）。

#### 验证 D：模拟盘账户（PAPER）

```bash
ssh qount-vps 'curl -s localhost:8001/account | python3 -m json.tool'
```

**预期**：`mode: PAPER`，`nav` 约 434 万（若调和包存在），或 `error` 含 `SOURCE_NOT_FOUND`（若本地包不存在——**这也是可接受的正确行为**，不是错误）。

#### 验证 E：真实 Binance 账户（只读）

```bash
ssh qount-vps 'curl -s localhost:8001/account/live | python3 -m json.tool'
```

**预期**：

```json
{"mode":"LIVE_READONLY","source_kind":"binance_api","nav":0.36,
 "currency":"USDT","read_only":true,"positions":[],
 "safety":{"research_only":true,"orders_authorized":false}}
```

**失败判据**：`error` 含 `OBSERVATION_NOT_FOUND` → 观测文件路径不对，排查：

```bash
ssh qount-vps 'ls -la /var/lib/qount/blocked_runtime_observation.json'
```

#### 验证 F：前端静态页

```bash
ssh qount-vps 'curl -s -o /dev/null -w "%{http_code}\n" localhost:8001/'
ssh qount-vps 'curl -s localhost:8001/ | head -5'
```

**预期**：`200`，且 HTML 里含 `<title>qount · AI 个人量化交易助手</title>`。

**失败判据**：`404` → `web/app` 未同步，或 WorkingDirectory 不对。

#### 验证 G：研究线注册表

```bash
ssh qount-vps 'curl -s localhost:8001/research/registry | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(\"adapters:\", d[\"available_adapters\"])
for k, v in d[\"lines_adapter_status\"].items():
    print(\" \", k, \"→ registered:\", v[\"registered\"], \"enabled:\", v[\"enabled\"])
"'
```

**预期**：5 个 adapter（`dual_engine`、`cta_r_forward`、`personal_assistant`、`binance_macro`、`ashare_master`），8 条线全部 `registered: True`。

### 4.3 停止

回到运行 uvicorn 的终端按 `Ctrl-C`，再清除临时数据库：

```bash
ssh qount-vps 'rm -f /tmp/qount-api-manual.db /tmp/qount-api-manual.db-wal /tmp/qount-api-manual.db-shm'
```

**若任一验证失败，不要进入阶段 5。**

---

## 阶段 5：安装 systemd 服务

### 5.1 创建单元文件

```bash
ssh qount-vps 'cat > /etc/systemd/system/qount-api.service << "EOF"
[Unit]
Description=Qount read-only API and frontend (FastAPI)
Documentation=file:///root/qount/docs/vps-deployment-runbook-2026-10.md
After=network-online.target
[Service]
Type=simple
WorkingDirectory=/root/qount
# No EnvironmentFile: the read-only API must not inherit exchange or AI credentials.
Environment=PYTHONPATH=/root/qount/src
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=QOUNT_PAPER_STATE_ROOT=/var/lib/qount/paper/dual-engine
Environment=QOUNT_CTA_R_STATE_ROOT=/var/lib/qount/research/cta-r-forward
Environment=QOUNT_ACCOUNT_OBSERVATION_PATH=/var/lib/qount/blocked_runtime_observation.json
Environment=QOUNT_DB_PATH=/var/lib/qount/api/qount.db
Environment=QOUNT_LIVE_ENABLE=false
Environment=QOUNT_X4_LIVE_ENABLE=false
Environment=QOUNT_RV_LIVE_ENABLE=false
Environment=QOUNT_CXD_CARRY_ENABLE=false
Environment=QOUNT_MINI_TREND_LIVE_ENABLE=false
Environment=QOUNT_FOMC_LIVE_ENABLE=false
Environment=http_proxy=
Environment=https_proxy=
Environment=all_proxy=
Environment=HTTP_PROXY=
Environment=HTTPS_PROXY=
Environment=ALL_PROXY=
UnsetEnvironment=QOUNT_LIVE_CONFIRMATION
UnsetEnvironment=QOUNT_BINANCE_API_KEY
UnsetEnvironment=QOUNT_BINANCE_API_SECRET
UnsetEnvironment=QOUNT_MINI_TREND_LIVE_CONFIRMATION
UnsetEnvironment=QOUNT_MINI_TREND_ARM_TOKEN
UnsetEnvironment=QOUNT_FOMC_ARM_TOKEN
ExecStart=/root/qount/.venv/bin/python -m uvicorn qount.api.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-level warning
Restart=on-failure
RestartSec=10
TimeoutStopSec=15

UMask=0077
Nice=10
IOSchedulingClass=idle
CPUQuota=50%
MemoryHigh=192M
MemoryMax=320M
TasksMax=48
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/qount/api
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=multi-user.target
EOF'
```

**逐项说明**：

| 配置 | 为什么 |
| --- | --- |
| `WorkingDirectory=/root/qount` | `main.py` 用 `os.path.abspath("web/app")`，**必须**以此为工作目录，否则前端挂载失败 |
| 不加载 `.env`，并显式 `UnsetEnvironment=QOUNT_BINANCE_API_KEY/SECRET` | **API 只读文件，不需要也不应持有交易密钥** |
| `QOUNT_DB_PATH=/var/lib/qount/api/qount.db` | 让 SQLite 写在可写目录（`ProtectSystem=strict` 下 `/root` 是只读的） |
| `ReadWritePaths=/var/lib/qount/api` | 仅允许 SQLite 目录写入；账户观测与 paper 快照保持只读 |
| `--workers 1` + `MemoryMax=320M` | 内存只有 1.6 GB，多 worker 会 OOM |
| `ProtectSystem=strict` + `ProtectHome=read-only` | 最小权限；API 无理由写系统目录 |
| `Restart=on-failure` + `RestartSec=10` | 崩溃自愈 |

### 5.2 创建可写目录

```bash
ssh qount-vps 'mkdir -p /var/lib/qount/api && chmod 700 /var/lib/qount/api'
```

### 5.3 启用并启动

```bash
ssh qount-vps 'systemctl daemon-reload && systemctl enable --now qount-api.service'
```

### 5.4 验证

```bash
ssh qount-vps 'systemctl status qount-api.service --no-pager | head -20'
```

**预期**：`Active: active (running)`。

```bash
ssh qount-vps 'curl -s localhost:8000/health'
```

**预期**：与阶段 4.2 验证 A 相同的 JSON。

**失败判据**：`Active: failed` → 看日志：

```bash
ssh qount-vps 'journalctl -u qount-api.service -n 40 --no-pager'
```

常见原因：
- `WorkingDirectory` 不存在 → 检查 `/root/qount`
- 端口 8000 被占用 → `ssh qount-vps 'ss -tlnp | grep 8000'`
- 权限：`ProtectSystem=strict` 但没配 `ReadWritePaths` → 写库失败

### 5.5 再次验证四账户（确认线上进程也读到了真实快照）

```bash
ssh qount-vps 'curl -s localhost:8000/paper/lines | python3 -c "
import sys, json
for l in json.load(sys.stdin):
    if l[\"line_id\"].startswith(\"dual_\"):
        print(l[\"line_id\"], l[\"status\"], \"error:\", l.get(\"error\"))
"'
```

**预期**：四条全部 `ACTIVE_PAPER`，`error: None`。

### 回退

```bash
ssh qount-vps 'systemctl disable --now qount-api.service && rm /etc/systemd/system/qount-api.service && systemctl daemon-reload'
```

---

## 阶段 6：Caddy 反代切换（**真正的替换点**）

> ⚠️ 这是整个计划中唯一修改生产 Web 配置的一步。**执行前必读本节全部内容。**

### 6.1 备份

```bash
ssh qount-vps 'backup=/etc/caddy/Caddyfile.bak-$(date +%Y%m%d%H%M%S); install -m 600 /etc/caddy/Caddyfile "$backup" && stat -c "%n|mode=%a|%s bytes" "$backup"'
```

**记下这个备份文件名**，回退时要用。

### 6.2 改写 Caddyfile

改动只替换 `qount.alyaloale.com` 站点块里的 `file_server` 指令。下面先做不写入的结构检查；输出不会包含认证配置：

```bash
ssh qount-vps 'python3 - << "PYEOF"
from pathlib import Path
p = Path("/etc/caddy/Caddyfile")
text = p.read_text()
start = text.find("qount.alyaloale.com {")
marker = "# owner-aliyun-relay end"
end = text.find(marker, start)
assert start >= 0 and end > start, "qount site markers not found"
block = text[start:end]
assert block.count("basic_auth {") == 1, "expected one Basic Auth block"
assert block.count("header {") == 1, "expected one security header block"
assert block.count("handle /relay-") == 1, "expected one existing relay route"
assert block.count("reverse_proxy 127.0.0.1:16789") == 1, "existing relay upstream mismatch"
file_server_lines = [line for line in block.splitlines() if line.strip() == "file_server"]
assert len(file_server_lines) == 1, f"expected one file_server in qount site, got {len(file_server_lines)}"
print("qount_site_found=true")
print("basic_auth_preserved=true")
print("relay_route_preserved=true")
print("file_server_replacements=1")
PYEOF'
```

预览通过且阶段 6.1 备份完成后，执行单行替换。它保留 `root`、Basic Auth、安全响应头、relay 路由和文件权限，只改目标指令：

```bash
ssh qount-vps 'python3 - << "PYEOF"
from pathlib import Path
p = Path("/etc/caddy/Caddyfile")
text = p.read_text()
start = text.find("qount.alyaloale.com {")
marker = "# owner-aliyun-relay end"
end = text.find(marker, start)
assert start >= 0 and end > start, "qount site markers not found"
block = text[start:end]
assert block.count("basic_auth {") == 1, "expected one Basic Auth block"
assert block.count("header {") == 1, "expected one security header block"
assert block.count("handle /relay-") == 1, "expected one existing relay route"
lines = block.splitlines(keepends=True)
indices = [i for i, line in enumerate(lines) if line.strip() == "file_server"]
assert len(indices) == 1, f"expected one file_server, got {len(indices)}"
i = indices[0]
old = lines[i]
ending = "\r\n" if old.endswith("\r\n") else "\n" if old.endswith("\n") else ""
indent = old[:len(old) - len(old.lstrip())]
lines[i] = indent + "reverse_proxy 127.0.0.1:8000" + ending
updated = "".join(lines)
p.write_text(text[:start] + updated + text[end:])
print("qount_reverse_proxy_configured=true")
PYEOF'
```

### 6.3 校验配置（**必做**）

```bash
ssh qount-vps 'caddy validate --config /etc/caddy/Caddyfile 2>&1 | tail -5'
```

**预期**：`Valid configuration`。

**失败判据**：任何 `Error` → **不要 reload**，先用备份还原：

```bash
ssh qount-vps 'cp /etc/caddy/Caddyfile.bak-<时间戳> /etc/caddy/Caddyfile'
```

### 6.4 热加载

```bash
ssh qount-vps 'caddy reload --config /etc/caddy/Caddyfile --force'
ssh qount-vps 'systemctl is-active caddy'
```

**预期**：`active`。

此 VPS 的 `systemctl reload caddy` 会在 systemd namespace 阶段失败（`/run/systemd/unit-root/tmp` 缺失），所以用 Caddy admin API 直接热加载。若 SSH 在 reload 后断开，重新连接并检查 Caddy 状态及未认证访问仍为 `401`。

### 6.5 线上验证

#### 验证 A：从 Mac 访问域名

```bash
curl -sS -o /dev/null -w "health_status=%{http_code}\n" -u qount https://qount.alyaloale.com/health
```

**预期**：`200`。

`curl` 会在终端安全提示输入密码；不要把密码写进命令或 shell 历史。不带 `-u` 应返回 `401`（Basic Auth 生效）。若返回 `200`，说明认证被误删，立即回退。

#### 验证 B：浏览器

打开 `https://qount.alyaloale.com/`，输入 basic_auth 账号密码。

**应看到**：新的双屏界面（顶部 `qount` + `AI 个人量化` 标签、两个 Tab「账户概览」「模拟盘探索」）。

**账户屏应看到**：

```
┌────────────────────────┬──────────────────────────────┐
│ 真实 Binance 账户  只读  │ 研究模拟盘 (PAPER)  模拟非真实资产│
│ 钱包余额 0.36 USDT      │ 模拟净值 ¥4,349,345.74        │
│ 可用余额 0.36 USDT      │ 可用现金 ¥0.00                │
│ 持仓 0 项 · 只读         │ 1 只标的                      │
└────────────────────────┴──────────────────────────────┘
```

**模拟盘屏应看到**：7 条研究线，四条 `dual_*` 显示真实 YTD 与回撤。

#### 验证 C：确认旧前端已不可达

```bash
curl -sS -o /dev/null -w "old_api_path_status=%{http_code}\n" -u qount https://qount.alyaloale.com/data/v1/overview.json
```

**预期**：`404`（新 API 没有这个路径）。

### 6.6 回退（一条命令）

```bash
ssh qount-vps 'cp /etc/caddy/Caddyfile.bak-<时间戳> /etc/caddy/Caddyfile && caddy reload --config /etc/caddy/Caddyfile --force'
```

**切换在 1 秒内完成，旧前端立即可用**（`/var/www/qount` 未被删除）。

---

## 阶段 7：验证与并行观察

### 7.1 完整验收清单

| # | 检查项 | 命令 | 通过标准 |
| --- | --- | --- | --- |
| 1 | 服务运行 | `ssh qount-vps 'systemctl is-active qount-api'` | `active` |
| 2 | 健康 | `ssh qount-vps 'curl -s localhost:8000/health'` | `status: ok`, `paper_lines_count: 7` |
| 3 | 四账户真实 | `ssh qount-vps 'curl -s localhost:8000/paper/lines'` | 四条 `dual_*` = `ACTIVE_PAPER`，`error` 为空或 `null` |
| 4 | G20 数值 | `curl .../paper/lines/dual_g20` | YTD `15.26`，291 点 |
| 5 | 真实账户 | `curl .../account/live` | `LIVE_READONLY`，`read_only: true` |
| 6 | 域名可访问 | 浏览器 | 双屏界面正常 |
| 7 | basic_auth 生效 | 不带凭据访问 | `401` |
| 8 | 内存占用 | `ssh qount-vps 'systemctl status qount-api \| grep Memory'` | < 320 MB |
| 9 | 无重启循环 | `ssh qount-vps 'systemctl status qount-api \| grep "Active"'` | 无频繁 Restart |

### 7.2 观察期（建议 3–5 日）

```bash
ssh qount-vps 'systemctl status qount-api.service --no-pager | head -12'
ssh qount-vps 'journalctl -u qount-api.service --since "24 hours ago" -p err --no-pager | tail -20'
```

**关注**：内存是否持续增长（内存只有 1.6 GB）、是否有 500 错误。

### 7.3 旧服务处置（**观察期结束后**）

**只 stop，不 disable，不删文件：**

```bash
ssh qount-vps 'systemctl stop qount-dashboard-publisher.timer qount-dashboard-publisher.service'
```

> ⚠️ **`qount-dashboard-account-observer` 不要停！**
> 它每 5 分钟读真实 Binance 账户并写 `/var/lib/qount/blocked_runtime_observation.json`，
> **正是 `/account/live` 的数据来源**。停掉它，真实账户读数就没了。

**复停确认**：

```bash
ssh qount-vps 'systemctl is-active qount-dashboard-publisher.timer qount-dashboard-account-observer.timer'
```

**预期**：publisher 为 `inactive`，account-observer 为 `active`。

### 7.4 确认无引用后再清理（可选，延后执行）

只有在 `grep` 确认没有任何东西再读 `/var/www/qount/data` 后，才考虑：

```bash
ssh qount-vps 'mv /var/www/qount/data /var/www/qount/data.retired-$(date +%Y%m%d)'
```

**用 `mv` 而不是 `rm`**，保留可恢复性。

---

## 阶段 8（可选）：让 `/market/klines` 在线上可用

### 8.1 问题

`/market/klines` 读 `state/r0_runtime/klines` 与 `state/grid_b/klines`（按月 zip，本地 Mac 上有 773 个文件）。而 `sync-to-vps.sh` 的 `items` 不含 `./state`，且 `.gitignore` 忽略 `state/`，**所以 VPS 上没有这些文件**。

### 8.2 验证当前状态

```bash
ssh qount-vps 'curl -s "localhost:8000/market/klines?symbol=BTCUSDT&start=2021-01&end=2021-02" | head -c 300'
```

**若返回空 bars 或错误**，说明确实缺数据。

### 8.3 三个选项

**选项 A：不需要，接受缺失（推荐）**

当前双屏前端**不调用** `/market/klines`。若不需要 K 线图，**什么都不用做**，该端点返回空属预期。

**选项 B：只同步需要的月份**

```bash
ssh qount-vps 'mkdir -p /root/qount/state/r0_runtime/klines'
rsync -avz --include='BTCUSDT*' --exclude='*' \
  state/r0_runtime/klines/ qount-vps:/root/qount/state/r0_runtime/klines/
```

只传 BTC 的归档，体积可控。

**选项 C：改 API 去读 VPS 已有的缓存**

VPS 上 `/root/qount/state/grid_b/` 已存在（前期遗留）。先看有什么：

```bash
ssh qount-vps 'find /root/qount/state/grid_b -name "*.zip" | head -5; find /root/qount/state/grid_b -name "*.zip" | wc -l'
```

若已有足够数据，在 systemd 单元里加：

```ini
Environment=QOUNT_KLINES_CACHE_DIR=/root/qount/state/grid_b/klines
```

> 注意：当前 `market.py` **硬编码**两个候选目录，不读环境变量。若要走选项 C，需要先改代码。**本轮不动代码，故选项 C 暂不可用**——列出仅为完整性。

### 8.4 注意：`ReadWritePaths`

若开启行情接口且需要写缓存，`ProtectSystem=strict` 下需把缓存目录加入 `ReadWritePaths`。只读则不必要。

---

## 附录 A：故障速查

| 症状 | 可能原因 | 排查 |
| --- | --- | --- |
| `/` 返回 404 | `WorkingDirectory` 不对，或 `web/app` 未同步 | `ssh qount-vps 'ls /root/qount/web/app/'` |
| `/health` 正常但前端白屏 | 静态挂载失败 | `curl -s localhost:8000/app.js \| head -3` |
| 四条 `dual_*` 全 `MISSING` | `QOUNT_PAPER_STATE_ROOT` 未生效 | `systemctl show qount-api -p Environment` |
| `/account/live` 报 `OBSERVATION_NOT_FOUND` | 观测文件路径不对 | `ls -la /var/lib/qount/blocked_runtime_observation.json` |
| 服务反复重启 | 内存超限或写库权限 | `journalctl -u qount-api -n 50` |
| `caddy reload` 后 502 | API 未运行或端口不符 | `curl -s localhost:8000/health` |
| 域名返回 200 但无 basic_auth | `basic_auth` 块被误删 | **立即回退 Caddyfile** |
| Tiingo 429（paper-daily 失败） | 429 是外部限流响应；反复触发的请求预算、全历史轮询与缺少缓存属于本地调用设计问题。先检查采集证据中的 HTTP 状态与当日请求预算，完成配额核算前不要盲目重跑。 | 检查 `qount-research-forward-collector` 证据与调用预算；按 [Tiingo 配额治理步骤](paper-lines-optimization-plan-2026-10.md#2-tiingo-配额治理-p0-今天已在烧) 修复后再验证 |

## 附录 B：回退总表

| 阶段 | 回退命令 |
| --- | --- |
| 2 | `ssh qount-vps 'cd /root && tar xzf qount-backup-<时间戳>.tar.gz'` |
| 3 | `ssh qount-vps 'cd /root/qount && ./.venv/bin/pip uninstall -y fastapi uvicorn starlette'` |
| 5 | `ssh qount-vps 'systemctl disable --now qount-api && rm /etc/systemd/system/qount-api.service && systemctl daemon-reload'` |
| **6** | `ssh qount-vps 'cp /etc/caddy/Caddyfile.bak-<时间戳> /etc/caddy/Caddyfile && caddy reload --config /etc/caddy/Caddyfile --force'` |
| 7.3 | `ssh qount-vps 'systemctl start qount-dashboard-publisher.timer'` |

**最坏情况下，只要执行阶段 6 的回退，域名立刻回到旧前端。**

## 附录 C：本次涉及的环境变量

| 变量 | 值 | 用途 |
| --- | --- | --- |
| `QOUNT_PAPER_STATE_ROOT` | `/var/lib/qount/paper/dual-engine` | 四账户快照根目录 |
| `QOUNT_ACCOUNT_OBSERVATION_PATH` | `/var/lib/qount/blocked_runtime_observation.json` | 真实账户只读观测 |
| `QOUNT_DB_PATH` | `/var/lib/qount/api/qount.db` | API 的 SQLite |
| `QOUNT_ALLOW_LIVE_FETCH` | **不设**（默认关闭） | 允许联网补采 K 线 |
| `QOUNT_PAPER_LINES_REGISTRY` | **不设**（默认 `config/paper-lines.json`） | 研究线注册表 |

前 3 个已登记在 `config/environment-contract.toml`，`repository_hygiene.py check` 会校验。

---

## 执行清单（可勾选）

```
[x] 阶段 1  提交代码，git status 干净
[x] 阶段 2  备份 VPS → dry-run → 同步 → 验证文件在
[x] 阶段 3  装 fastapi/uvicorn → 验证可导入
[x] 阶段 4  手动跑 8001 → 逐项验证 A-G 全通过 → Ctrl-C
[x] 阶段 5  写单元 → mkdir /var/lib/qount/api → enable --now → 验证
[x] 阶段 6  备份 Caddyfile → 改写 → caddy validate → reload → 基础域名边界验证
[ ] 阶段 7  完成浏览器鉴权验收并观察 3-5 日 → 再评估 stop publisher（保留 observer）
[ ] 阶段 8  可选：行情接口（当前未启用）
```

research_only=true / orders_authorized=false / promotion_evidence=false。

## 本次执行记录（2026-10-12）

- 阶段 1–6 已执行。代码提交为 `802ecd8`，同日修复同日多时点 NAV 被 SQLite 日期键覆盖的问题（`65334a2`）；执行中发现的 reload 环境差异已补入本手册。
- VPS 代码备份：`/root/qount-backup-20261012201824.tar.gz`（4,398,317 bytes），凭据文件已排除。
- Caddy 回退备份：`/etc/caddy/Caddyfile.bak-20261012202540`，mode `0600`。
- API 专项 29 项通过；hygiene 与 API compile 通过。VPS API health 返回 7 条线，四条 dual 线为 `ACTIVE_PAPER`，G20 有 291 点、YTD 15.26%、最大回撤 -16.33%；真实账户端点为 `LIVE_READONLY`。
- Caddy admin API 的活动配置确认 qount 站点代理到 `127.0.0.1:8000`，Basic Auth、响应头和 relay 路由保留；未认证 `/` 与 `/health` 均返回 `401`。API 本地 `/` 为 `200`，旧路径 `/data/v1/overview.json` 为 `404`。
- systemd `qount-api.service` active、`NRestarts=0`、内存约 44 MB / 320 MB；进程未载入 `.env` 或交易/API 密钥。账户观察器与旧 publisher timers 保持 active，均未停止。
- 本 VPS 的 `systemctl reload caddy` 在 systemd namespace 设置阶段失败；直接 `caddy reload --config /etc/caddy/Caddyfile --force` 已加载新配置。后续回退也使用直接 Caddy reload。
- 阶段 7 观察期从 2026-10-12 开始；3–5 日观察及浏览器输入 Basic Auth 后的页面确认仍待完成。阶段 8 未启用，前端不调用 `/market/klines`。
