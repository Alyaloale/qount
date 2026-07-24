# qount 更新记录（历史归档）

本文件是 `docs/update-log.md` 的历史归档，收录 **2026-07-14 及更早** 的执行记录（含 line A / GRID-B /
早期 MiniTrend / 2026-07-16 加密优先重启之前的证据链）。当前近期记录见 `docs/update-log.md`。

历史条目里的余额、订单、timer、live 开关、版本和"当前/下一步"措辞一律按**条目日期**读取，不覆盖
`docs/current.md` 或 VPS 只读事实。

（注：正文内相对链接按原 `docs/` 位置书写，从本归档目录可能失效，按文件名到 `docs/` 下查找。）

---

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
