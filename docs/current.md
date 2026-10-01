# qount 当前状态

> **状态**：active｜**权威**：L1 当前事实（#1）｜**最后更新**：2026-09-29
> **本文回答**：当前生产事实、能力边界、运行状态、下一步、硬边界。
> **TL;DR**：9 月 23 日再次重启后 SSH 恢复，已修复发布来源证明并缓解 SSH 未认证连接限流；Dashboard operations 恢复 healthy，paper/公共采集正常。交易 timer 仍关闭，旧 arm 已过期；研究来源缺口和已记录的采集中断仍保留。

更新时间：2026-09-30

- **2026-09-30 CTA-R 研究前瞻账本（D1，owner 授权，已部署）。** 新增 `qount-research-cta-r-forward.{service,timer}`，
  每日 18:45 CST 从公共腾讯前复权日线刷新自有 seed（VPS 上 Eastmoney 不通），追加哈希链前瞻账本
  `/var/lib/qount/research/cta-r-forward/forward-ledger.jsonl`，并重建 `/var/www/qount/data/cta_r_paper.json`（年初起回放 + forward 摘要）。
  规则与侧车相同，未改参数（2 bps 基础 + 10 bps 压力）。创世条目为 2026-09-29（bar 2848），权重与原侧车一致；
  合同 hash `fa988d78...095a7b`。没有改动 CTA-R collector 及其 seed（hash 仍为 `d060f1f6...`）、ops-health-v3 或 Dual-Engine。
  首跑 `valid`。部署目录 `/var/lib/qount/deployments/cta-r-forward-v1-20260930T065004Z/`（含 ROLLBACK.md）。
  合同与评估规则见 [cta-r-forward-ledger-2026-09.md](cta-r-forward-ledger-2026-09.md)。

- **2026-09-29 统一 forward collector 迁至 `ops-health-v3`（owner 授权，已验收）。** 原 `ops-health-v2` 自
  `2026-09-27T19:30:27+08:00` 起 `forward_contract_mismatch`（9-27 CTA-R 部署改了共享 `forward_collector.py`，
  而合同冻结其源 hash），链停在 9-27，保持只读不改。新合同根 `/var/lib/qount/research/forward/ops-health-v3`
  （contract hash `a6981a01…`），collector 与 dashboard publisher 的 `--state-root/--forward-root` 已同步。
  首条记录为 09:16Z 手动运行（未加载 env，Tiingo insufficient，属预期）；09:19Z systemd 周期
  `l1_passive_tiingo=valid`、`api_key_used=true`；publisher 首跑 `runtime:forward` 与全部来源检查 pass，
  失败单元为 0。`l1_passive.data_conclusion` 仍为 insufficient，需累积样本。9-27 至 9-29 的采集缺口不可补。
  回退见 `/var/lib/qount/deployments/ops-health-v3-*/ROLLBACK.md`。发布来源证明 `ops_release_provenance_block`
  为既有问题，本批次文件会扩大差异，仍需 owner 统一重新认证。

- **2026-09-29 C60 合同 v2 research-paper 侧车已部署。** owner 授权按月度候选规则（Trial 150）开 v2，作为与冻结
  v1 并行的比较线（`replaces_frozen_v1=false`、`research_only=true`、`orders_authorized=false`），不改 Dual-Engine
  合同、账户或 timer。`qount-research-c60-v2-paper.timer` 每日 08:20 CST 生成 `/var/www/qount/data/c60_v2_paper.json`，
  前瞻哈希链账本从 2026-09-30 开始。首跑 `valid`；样本内 2026 YTD v2 -8.15%/78 次调仓，同引擎 v1 -6.02%/108 次，
  故 v2 优势仅见于 2020–2026 全样本（成本研究），今年未体现。回退见部署目录 `ROLLBACK.md`。

- **2026-09-29 Tiingo 与 vol crisis。** L1 Tiingo key 已由 owner 授权写入 `/etc/qount/research-forward-collector.env`
  （0600，未回显值）；paper 的 SPY reference 已正常（185 bars 至 9-28），9-23 的 `benchmarks=[]` 已过时。
  `crypto_vol_crisis_state_v1` family 已关闭，剩余 2 trial 作废；全局 trial 计数 150。

- **2026-09-29 CTA-R 数据与前端对齐状态核实。** CTA-R 独立 collector timer 保持
  `enabled/active`，按北京时间每日 18:30 运行，最多随机延迟 5 分钟；最近一次服务执行成功，
  但 8 条 ETF 序列实际最新日期仍为 `2026-07-22`，sidecar 状态继续为 `insufficient/series_stale`。
  本批次不伪造新行情、不修改 timer，也不调用冻结 CTA-R 实现；前端明确显示原始回放末值、共同日期轴归一后的
  比较价值、实际数据截止日和采集计划。四个 Dual-Engine 主账户与 CTA-R 仍保持独立会计和 research-only 边界。

- **2026-09-29 CTA-R 公共数据已补采。** 通过公共 Eastmoney 日线接口重建 8 个 ETF 的前复权 seed，
  每条序列最新交易日为 `2026-09-29`，seed hash=`d060f1f6...151e3a`；远端隔离 collector 已验收
  `research_lines:valid`，记录 hash=`99bbabba...ae116`。Dashboard CTA-R sidecar 已重建并发布，
  `status=valid`、`data_cutoff=2026-09-29`、160 个回放点；原 seed 保存在远端隔离备份中。

- **2026-09-28 Dashboard 静态前端布局收敛并发布。** `#/paper` 现明确标出四个 Dual-Engine 主账户
  （G20/C60/GC5/D15）与第五个 CTA-R research-only 侧车；主快照缺失时不再用“曲线准备中”掩盖状态，
  而是分别显示主快照不可用和 CTA-R 侧车状态。此次只替换 `/var/www/qount/index.html`、`app.js`，未修改
  `data/v1`、publisher、timer 或任何交易权限；远端静态文件 hash 已与本地一致，回退副本保存在
  `/var/www/qount/.frontend-backups/qount-frontend-20260928-215327/`。

- **2026-09-27 owner 决策：恢复 CTA-R 公共 ETF 数据采集准备。** 授权范围仅为新建隔离的
  AkShare A 股 ETF 日线 seed 与 research-only forward collector，使用新合同根；不得修改
  `ops-health-v2`，不得恢复 CTA-R 策略/回放/paper，不产生 StrategyIntent、权重、订单或 live 权限。
  采集与部署须通过本地合同/测试、seed 来源和新状态根校验后分别验收。CTA-R AkShare 数据不使用 API key；
  L1 Tiingo key 是独立来源。本次只读检查发现 VPS research-forward-collector env 未配置 Tiingo key，
  因此未能判断该 key 是否过期；未读取或复制任何凭据。

- **2026-09-27 CTA-R AkShare 隔离采集已部署验收。** 新合同根为
  `/var/lib/qount/research/forward/cta-r-akshare-v1`，独立 timer 为
  `qount-research-cta-r-collector.timer=enabled/active`；旧 `ops-health-v2` 未修改。
  首次 service 返回 `Result=success`，记录 hash=`9b0fe200...cf7cb89`，8 条 ETF 序列均截至
  `2026-07-22`，来源状态为 `insufficient/series_stale`。seed 由本地历史 archive 转换而来，
  新 seed hash=`3d5f8a47...cfc2df0`；这证明格式、合同和只读链路可运行，不证明当前数据新鲜。
  AkShare 公共接口在 Mac 代理和无代理请求均被远端断开，未能在线刷新；没有发现 CTA-R key 过期问题，
  因为该路径不使用 key。研究守卫保持 `research_only=true/orders_authorized=false/pnl_evaluated=false`，
  未恢复策略、paper、订单或 live 权限。待有可用公共网络后，只需更新 seed 并等待该独立 timer 验收。

- **2026-09-27 CTA-R research-paper 侧车已恢复并接入 paper 前端展示。** 新实现位于
  `src/qount/research/cta_r_paper.py`，独立读取 8 只 ETF 的公开 seed，按 63/126/252 日
  TSMOM、逆波动率、21 个交易日调仓和 2 bps 模拟成本回放；它不导入冻结 `legacy/line_a`，不写
  StrategyIntent，不改变 Dual-Engine 的 G20/C60/GC5/D15 合同。Dashboard paper 页新增独立
  `CTA-R 研究模拟` 区块，显示状态、数据截止、净值曲线、权重、调仓与成本，并固定展示
  `research_only=true/orders_authorized=false/pnl_evaluated=false`。当前 sidecar 源 hash 对应的
  8 条序列共同截止 `2026-07-22`，截至本日为 `insufficient/series_stale`；曲线只作为历史研究证据，
  不代表当前策略结果，也没有 CTA-R 数据源 key 可过期或被读取。

- **2026-09-23 长期产出质量复核。** 12:39 CST 主机无失败单元、内存 available 约 771 MiB，
  swap 0、磁盘使用率 46%；当日日报已自动生成，但 `status=incomplete`、六角色全部 blocked。
  保留的 8 月 18 日至 9 月 23 日 35 份日报全部 incomplete，21 份含 LLM 请求错误；
  其中 15 份为 BadRequestError、6 份为 APITimeoutError。9 月 4 日与 12 日没有对应日期工件，
  原因未从当前留存日志证实。统一采集 37 个日期的末条记录抽样中，CTA-R 归档缺失与 L1 凭据
  不可用均持续存在；这不是刚重启产生的问题。模拟盘 272 行会计审计全量通过，但 SPY 基准为空。
  收益与成本分析见 [策略总集](qount_strategy_master_index.md#2026-09-23-长期运行结果复盘)，
  证据范围与改进优先级见 [更新记录](update-log.md#长期运行经验复盘只读)。本次未修改运行状态或参数。

- **2026-09-24 运维缺口修复批次（已上线并完成自然周期验收）。** owner 明确日报因 API
  额度耗尽暂不处理；本批次不重试日报、不发送通知、不改变交易权限。新增只读运行证据探针，
  在 Dashboard 发布时检查 forward head/记录新鲜度、来源状态、liquidation 心跳和研究守卫；
  磁盘预警提前到采集器 8 GiB 停止线（10 GiB warning），并拒绝符号链接、超大/非法 JSON 和路径穿越。
  unified collector 的 liquidation 状态改为健康摘要，不再每 15 分钟重复写入 recent event IDs；旧链保留，
  新合同根为 `ops-health-v2`。冻结 CTA-R 不再列入新的 active source graph；L1 缺少凭据仍明确为
  insufficient，不复制或生成凭据。Dual-Engine 增加独立的公共 SPY/TLT reference artifact，
  仅用于展示基准，不改写 NAV、audit 或回放结果，采集失败时保留 paper 核心结果并显示基准不可用。
  本地相关测试 53 项通过，compileall、repository hygiene、systemd 静态引用检查通过。
  SSH 于 16:00 CST 恢复；VPS 只读状态为 uptime 1 天 4 小时 47 分、failed units 0、磁盘 47%/21 GiB
  可用、内存 available 685 MiB、swap 0，现有 collector/publisher/liquidation 服务保持 active。
  新文件先放入 `/var/lib/qount/deployments/ops-health-v2-20260924/staged/` 做隔离备份和编译，随后完成原子安装、
  `daemon-reload`、systemd 静态校验和真实模块导入。17:15 collector 自然周期 `Result=success`，新
  `ops-health-v2` head 新鲜且 hash/研究守卫通过；17:18 publisher 自然周期 `Result=success`，publication
  与 restore drill 均通过。部署证据、校验 hash 和回滚说明在同一 deployment 目录。source 缺凭据仍只报
  `insufficient/warn`；这证明上线和当前窗口健康，不代表长期连续性或研究输入完整性已经证明。

- **2026-09-23 再次重启后的修复验收。** owner 要求修复并详细检查现有故障，随后于
  `2026-09-23 11:12:25 CST` 再次启动实例；SSH 恢复，无失败单元，复核内存 available 约 800 MiB、
  swap 使用 0。既有 public-data/paper/Dashboard 服务恢复，交易 timer 仍 disabled/inactive，root cron 0。
  - SSH 上次启动日志明确记录 `MaxStartups` throttling，曾持续 18 分 12 秒并丢弃 33 个连接；
    有界内核日志未发现 OOM 记录，不能据此排除未记录的其他故障。新增
    `/etc/ssh/sshd_config.d/00-qount-connection-limits.conf`，设置 `LoginGraceTime=30`、
    `PerSourceMaxStartups=3`，保留原登录认证方式和全局连接上限。`sshd -t`、热加载及新连接验证通过；
    这是对已观测连接饱和的缓解，不构成长期不再超时的保证。
  - 实际基础版本为 `0.2.29 / 30d20b4ca053757d15c39be0dc4ee21e42839521`。旧基础清单 1,010 项
    逐项匹配该 Git；8 个变化文件逐项匹配 8 月 18 日部署验收；217 个额外历史文件全部匹配
    当前 Git 内容或旧 `66034b0` Git 历史。本次保留文件和兼容路径，不移动、删除或调用旧入口。
    在完整来源核实后，部署 provenance 固定错误码诊断及相关测试，并移除统一 collector 的
    `--print-json` 日志参数，保留原 append-only 数据链、来源合同和 timer 日程。
    新清单覆盖 1,227 个文件，provenance hash=`e6cdfe5f...ca55aa2f`；基础 commit 不代表叠加修复本身。
    来源映射、变更前备份和验证记录在 `/var/lib/qount/deployments/post-reboot-repair-20260923/`。
  - Dashboard `2026-09-23T03:36:05.874909Z` 自然发布中，operations 已 healthy，
    `release:provenance=pass/release_provenance_verified`；12 个模型和 publication 完整校验通过。
    本地与远端相关测试各 29 项通过。已有 arm 创建于 7 月 23 日、所属版本 0.2.15，
    `end_date_exclusive=2026-08-18`，已过期；未重新 arm，`live_orders_allowed=false`。
  - Liquidation 心跳新鲜、连接/快照错误 0，两个 `collector_restart` gap 分别为
    `3,022,360 ms`（9 月 22 日，约 50 分 22 秒）与 `2,021,236 ms`（9 月 23 日，约 33 分 41 秒）。
    gap 由前次记录至新 session 启动计算，不等同于主机准确停机时长；未补造数据或评估策略结果。
    `2027-02-14` 仅为原窗口理论下限，实际评估前必须审计缺口与覆盖率，不能宣称连续完整 180 天。
  - Paper 快照仍 fresh，数据截至 `2026-09-22T20:00:00Z`；统一采集 head/hash 校验通过。
    CTA-R 缺失归档（冻结线路）和 L1 passive 缺少配置凭据仍为 insufficient；未复制或新增凭据，
    未恢复冻结线路。FOMC 两个限时 timer 仍 elapsed/无 NEXT，保留现状；本次未运行日报或发送通知。

- **2026-09-23 VPS 重启后只读复核（北京时间 10:38–10:42 的有效快照）。** 系统于
  `2026-09-22 20:58 CST` 启动，检查时 `systemctl is-system-running=running`、失败单元为 0；
  根盘使用率 47%、可用约 21 GiB，内存 available 720 MiB，swap 使用 0。
  Dashboard publisher、账户只读 observer、两条 Dual-Engine paper timer、统一 research collector 和
  notification retry 均为 enabled/active；已运行的对应 oneshot 最近 `Result=success/ExecMainStatus=0`。
  日报和 Phase B timer 已恢复，但本次开机后尚未到执行时间，不能用默认 `Result=success` 宣称执行成功。
  最新日报为 9 月 22 日 12:35 CST，下一次日报计划为 9 月 23 日 12:31 CST 左右。
  - Liquidation collector 自本次启动持续 active、`NRestarts=0`；检查时本 session 收到 1,327 条
    forceOrder，连接错误和快照错误均为 0，心跳 age 约 27 秒（阈值 180 秒）。有 1 条 gap 记录，
    本次未核实其时长，不能据此宣称独立窗口连续无缺口；研究守卫均保持 false。
  - Paper daily 于 9 月 23 日 06:30 CST 成功，G20-open 于 9 月 22 日 23:00 CST 成功；
    四账户快照数据截至 `2026-09-22T20:00:00Z`，snapshot hash=`8ca130c1...b8e28a`。
    `read_dashboard_v1` 对 12 个读模型和 publication 完整回读校验通过，paper freshness 为 fresh，
    `orders_authorized/private_api_used/exchange_mutation_attempted=false`。
  - 统一采集最近有效核查周期为 `2026-09-23T02:30:04.358082Z`，服务成功但来源汇总 insufficient：
    CTA-R 的 `/root/qount/state/cta_r/etf_source/etf_data.zip` 缺失；L1 passive 的
    `QOUNT_TIINGO_API_KEY` 不可用。Binance REST/archive、FOMC 日历与 liquidation 状态为 valid；
    所有策略收益结论仍 insufficient。CTA-R 已冻结，缺文件不构成恢复它的授权。
  - Dashboard 的 clock/disk/service/backup 为 healthy；operations 因
    `release_provenance_unavailable` 阻断，execution/observation 汇总 unavailable。
    这证明发布来源校验未通过，尚不能区分清单缺失与源码不匹配。
    探针同时报告 `/root/qount/state/mini_trend/arm/manual-final-arm.json` 存在；本次未读取授权内容、
    未确认其有效性。MiniTrend live/forward timer 均 disabled/inactive，FOMC live unit/env 不存在，
    root crontab 有效项为 0，Dashboard `trading_authority=blocked/live_orders_allowed=false`。
  - VPS 仍保留 enabled/active/elapsed 的 FOMC shadow 与 evidence-backup 限时 timer，均无 NEXT，
    最近触发在 7 月 30 日；旧 Alpha collector 为 disabled，MiniTrend forward timer 为 disabled。
    仓库活动模板已移除并不意味着 VPS unit 文件已删除。本次未改变任何服务、调度或授权。
  - 后续追加核查的 SSH 出现 `Connection timed out during banner exchange`；发布来源失败的
    具体原因、gap 时长及之后的主机状态未获核实。恢复连接后优先做有界只读检查。

VPS基础生产版本：`0.2.29`，基础 commit=`30d20b4ca053757d15c39be0dc4ee21e42839521`（9 月 23 日实机核实，含上方已记录修复）；Dual-Engine 当前
program=`1.1.0`、YTD curve overlay content hash=`05258e5e...a8b1`、可视化 overlay package hash=`42b56a1c...82cc`；逐文件清单与验收记录保存在
`/var/lib/qount/deployments/dual-engine-ytd-curve-v1-20260802/` 和
`/var/lib/qount/deployments/dual-engine-paper-visual-v1-20260803/`。基础 release 的 commit、provenance 和 verification 仍保存在
`/root/qount/.qount-release-provenance.json`及`.qount-release-verification.json`；FOMC watcher、有限事件timer、
Dashboard只读账户视图、有界微信retry timer和公开数据研究timer按既有状态运行；所有交易执行权限均关闭。

- **2026-08-18 liquidation WebSocket 与统一前向健康检查已修复部署。** 只读核查发现 2026-07-28
  至本次修复前的 collector 虽累计写入 `18,042` 组五分钟 REST 上下文快照，但旧 Binance
  `/stream?streams=...` 路径从未收到 `forceOrder` 消息；该段方向性事件证据不完整，不能计入 180 天独立窗口。
  collector 现使用 Binance 当前 `/market/stream?streams=...` 路径，并在同一公开连接中订阅只用于传输
  freshness 的 `BTCUSDT markPrice@1s` 心跳；心跳不写入研究事件、不生成信号。VPS 独立 smoke 在 8 秒内收到
  7 条心跳、3 条真实 `forceOrder` 和三标的完整 REST 快照，随后
  `qount-liquidation-cascade-collector.service` 于 `2026-08-18T06:31:56Z` 成功重启，保持
  `enabled/active`、`NRestarts=0`、合同 hash=`6bbd2f44...ec38ec7`。统一 collector 以 180 秒阈值校验
  status 与流心跳；因插件源码合同变更，新 append-only 链写入
  `/var/lib/qount/research/forward/stream-health-v1`，旧 `/var/lib/qount/research/forward` 链只读保留。
  新方向流独立窗口从本次重启开始，最早不早于 `2027-02-14T06:31:56Z` 才可评估；此前公布的
  `2027-01-24` 日期已失效。部署证据和回滚源保存在
  `/var/lib/qount/deployments/liquidation-stream-health-v1-20260818/`。全部守卫仍固定
  `orders_authorized=false/private_api_used=false/pnl_evaluated=false/read_results_before_window=false`。

- **2026-08-10 Dual-Engine 模拟收益与大盘对比视图已部署。** Dashboard 的四条策略线固定对应
  G20/C60/GC5/D15，可切换 YTD/180D/90D/30D、收益率/美元金额和单条显隐；缩放只由顶部独立滑条控制，左右日期窗口只由
  图下固定窗口滑条控制，不再用拖动曲线或滚轮平移。总图使用本地 Apache ECharts，提供十字准星和轴触发悬停提示。每个净值点都带经合同校验的逐日收益率和逐日美元金额，悬停任一日期会并列显示
  四条线的该日净值与收益。各账户的当前模拟权益、日收益、月收益、YTD 收益率与对应美元损益均由服务端 `Executable NAV`
  历史计算并在快照合同中校验，页面不自行重算或伪造收益。大盘只采用 Tiingo 公开的 SPY 未复权日收盘价，只有其历史完整覆盖模拟曲线起点时才发布；
  覆盖不足会明确显示等待状态，不用替代数据补线。该次发布只更新无订单模拟快照合同、Dashboard 资源及只读发布器，未触发
  paper 回放、未改变 timer、账户、授权、私有接口或订单权限；所有合同仍固定
  `orders_authorized=false/private_api_used=false/exchange_mutation_attempted=false`。

- **2026-08-03 Dual-Engine Dashboard 调仓与 K 线可视化已部署。** 在原有四账户 YTD 纸面曲线基础上，
  Dashboard 现在按真实时间比例绘制 NAV 横轴，显示执行层模拟调仓标记、组合/标的可选择的公开日线 K 线，以及完整
  模拟调仓表（时间、买卖方向、数量、参考价、名义金额和模拟成本）。K 线默认选择有调仓的非现金标的、展示近 90 个
  交易日，并可切换 45 日或 YTD 全程；证券价格轴为两位小数。行情展示固定使用原始未复权 OHLC，以保持与模拟成交
  参考价一致；BIL 的月初除息跳空会在页面明确说明，不应误读为数据断裂。新发布快照为 `219` 个输入周期和审计行，
  截至 `2026-08-02T00:00:00Z`；G20/C60/GC5/D15 各 219 点，含 18 个标的、3,290 根日线和总计 191 个模拟调仓事件，
  snapshot hash=`de633323...fe716`。展示数据仅来自 Tiingo/Binance 公开行情；调仓为 no-order 模拟执行记录，不是订单、成交
  或实盘收益。发布使用 Dashboard 的原子 `data/v1` 指针，线上静态文件已与发布源逐字比对，`qount-dashboard-publisher`、
  paper daily 和 G20-open timer 均为 `enabled/active`。部署前状态保存在
  `/var/lib/qount/paper/dual-engine-previsual-20260802T160700Z`；远端相关测试 38 项、Python compile、前端语法、
  JSON schema、Caddy 配置和发布快照哈希比对均通过。所有合同仍固定
  `orders_authorized=false/private_api_used=false/exchange_mutation_attempted=false`。

- **Dual-Engine 2026 YTD 无订单模拟曲线（初始部署 2026-08-02）。** 当前冻结 G20/C60/GC5/D15 四个
  `10,000 USD_EQ` 独立账户，使用 Tiingo/Binance 公共行情、Signal/Executable 双层净值、25 bps 基础与
  50 bps 压力成本、月内袖套隔离和 append-only 哈希审计；Dashboard 提供独立 `paper.json` / `#/paper`。
  owner 明确授权的 YTD replay 从 `2026-01-01` 起取完整公开历史，第一个模拟点为 `2026-01-02T15:00:30Z`；
  当前点数、数据截至时间和快照 hash 以本页 2026-08-03 发布事实为准。该曲线固定标记
  `simulated_not_realized`，不是账户实盘收益。VPS 上 daily 与 G20-open timer 均为 `enabled/active`；日常探针在
  北京时间 `06:30`，G20 显式日期探针在工作日北京时间 `23:00`。本机私有 `.env` 的 `QOUNT_TIINGO_API_KEY`
  已不回显地映射到 VPS `/etc/qount/dual-engine-paper.env` 的 `TIINGO_API_TOKEN`；文件为 `0600 root:root`。
  Tiingo EOD/IEX 与 Binance Spot 公共接口均已验证。权威口径见
  [qount_strategy_master_index.md](qount_strategy_master_index.md)。

- **2026-07-30 owner 已取消 `SmallAccount-FOMC-RightSide-v0.2` 的部署。** VPS 上不存在
  `qount-fomc-live.service`、`qount-fomc-live.timer` 或 `/root/.config/qount/fomc-live.env`，没有 live 进程、arm、授权消费记录或订单。
  FOMC 公开日历和行情研究由统一 research forward collector 采集；不能恢复或转化为交易执行权限。

- **2026-07-28 `liquidation_cascade_forward_v1`公共前向采集已在VPS启动。**
  `qount-liquidation-cascade-collector.service=enabled/active`、`NRestarts=0`；它持续订阅
  BTCUSDT/ETHUSDT/BNBUSDT 的公开 Binance USD-M `forceOrder`，并每5分钟记录当前 OI、20档深度及 mark/index
  上下文，状态根为`/var/lib/qount/research/liquidation-cascade-v1`（root `0700`、原始段和元数据`0600`）。
  首次连接和三标的完整快照已验证，冻结合同 hash=`6bbd2f44...ec38ec7`。方向性被迫流只来自 `forceOrder` 的订单边；
  premium/funding 字段仅为同刻原始上下文，绝不把本线改称或降级为 `funding_crowding_meta_v1`。本服务不读取凭据、
  私有账户或订单路径，固定`orders_authorized=false/pnl_evaluated=false/read_results_before_window=false`。本段原定
  180 天窗口起点已被 2026-08-18 的流路径核查否定；当前有效起点和最早评估日期以上方 2026-08-18 事实为准，
  不能作为均值回复或抄底信号。
  旧 Alpha collector 已从活动 systemd 部署模板移除，历史 session 只保留在 archive，不能恢复、拼接或复用。

- **2026-07-30 L1-S2 21-ETF personal-carrier 已弃用，不再属于当前研究路线。** 它声明的 21 ETF、
  `{13,26,39,52}` 周回看与所引用提交中的 13 ETF、`{13,26,52}` 默认配置不一致；此前外部盘上的缓存和
  回放结论不作为当前可验证事实。本线不再拉取 Tiingo 数据、回放、登记策略、生成目标或新增自动化流程。
需要重新研究时，从新的个人研究问题和最小可用脚本开始，不复用这条历史流程。
代码和测试已移至 [`src/qount/legacy/l1/`](../src/qount/legacy/l1/)，专属研究文档移至
[`docs/archive/legacy/l1-personal-carrier/`](archive/legacy/l1-personal-carrier/)。

- **2026-07-30 Sleeve 1 被动长期配置已独立预登记并接入 research registry。** `l1_passive_sixty_forty@0.1.0`
  固定为 `SPY 60% / TLT 40% / USD 现金目标 0%`，年度首个完整 NYSE 常规交易日为唯一再平衡锚点；现金流仅留至下一锚点，
  无 drift-band 或择时现金例外。合同 hash=`e87eeb77...b616d3`，registry hash=`4e53e10d...2ac03a`；两者均为
  `0600` 不可覆盖工件。它只处于 `research`，不产生 StrategyIntent、scheduler、paper/live、broker 或订单权限。

- **2026-07-31 已确认统一 research forward collector 在 VPS 运行。** 它以 15 分钟 systemd timer 统一记录 Binance UM
  REST/历史归档、FOMC 日历、liquidation 状态、CTA-R ETF archive 和 L1 passive 的 Tiingo SPY/TLT 来源，使用
  可扩展 source graph、固定 contract、append-only JSONL 与 SHA-256 链；每条研究线分开写 mechanism/data/strategy
  三层结论，默认 `orders_authorized=false/pnl_evaluated=false`。代码和配置见
  [`docs/research-forward-collector.md`](research-forward-collector.md)。VPS 上
  `qount-research-forward-collector.timer=enabled/active`，最近一次 service 执行 `Result=success`、退出码 `0`；
  当前状态根为 `/var/lib/qount/research/forward/stream-health-v1`；旧 `/var/lib/qount/research/forward` 合同链只读保留。
  最近记录的 `research_lines` 总状态仍可能为 `insufficient`，这表示某条
  source 或研究证据不足，不表示采集器失败。旧 MiniTrend forward 与 FOMC shadow timer 已从活动部署模板删除；liquidation
  WebSocket 仍作为独立原始事件源运行，统一 collector 只读取其状态，不重复写入事件流。

2026-07-27 及更早的生产、研究和架构记录已逐行迁入
[archive/current-archive-pre-fomc-2026-07-29.md](archive/current-archive-pre-fomc-2026-07-29.md)。

这份文档是当前事实入口，只保留结论、能力边界和下一步。接手命令看
[quick-handoff.md](quick-handoff.md)，项目规则和文档分类看
[project-rules.md](project-rules.md)，发现/验证边界看
[holdout.md](holdout.md)，长证据链看 [update-log.md](update-log.md)。当前系统工程主设计看
[system-architecture-design.md](system-architecture-design.md)，100 USDT Base与未来组合合同看
[crypto-portfolio-system-plan.md](crypto-portfolio-system-plan.md)，Alpha Agents研究层看
[alpha-agent-plan.md](alpha-agent-plan.md)，生产控制面演进看
[trading-system-evolution-plan.md](trading-system-evolution-plan.md)，研究与文献情报路线看
[research-advancement-roadmap.md](research-advancement-roadmap.md)，200 USDT个人事件策略看
[personal-200u-event-strategy.md](personal-200u-event-strategy.md)。旧研究线、历史计划和legacy运行手册统一从
[archive/README.md](archive/README.md)进入，不再混入当前生产导航。
