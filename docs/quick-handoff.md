# qount 快速接手手册

更新时间：2026-07-22

当前版本：`0.2.0`

这份文档给接手的大模型用，只放可执行入口、跨主机命令和容易踩坑的边界。当前结论看
[current.md](current.md)，证据长链看 [update-log.md](update-log.md)，架构路线看
[system-architecture-design.md](system-architecture-design.md)。

## 文档地图

- [current.md](current.md)：当前事实、能力边界、下一步。
- [project-rules.md](project-rules.md)：项目规则、文档分类、研究线隔离、代码清理纪律。
- [storage-topology.md](storage-topology.md)：Windows外置盘、WSL计算、迁移校验和清理边界。
- [holdout.md](holdout.md)：`discovery_pool` / `validation_pool_v1` 和 `G_paper` / `G_live`。
- [quick-handoff.md](quick-handoff.md)：接手命令和运维坑点。
- [update-log.md](update-log.md)：近期 artifact、验证结果、读法。
- [optimization-plan.md](optimization-plan.md)：2026-05-31 架构评审和 T-A..T-J 路线。
- [profit-research-plan.md](profit-research-plan.md)：盈利研究历史路线；旧 G1/G2 已被
  [holdout.md](holdout.md) 取代。
- [profit-engineering-plan.md](profit-engineering-plan.md)：2026-06-05 终审后的盈利工程
  主线；落地以 §10 的 S0 -> S1' -> S-CARRY 或 S2/S3 分叉为准。
- [alpha-agent-plan.md](alpha-agent-plan.md)：Alpha Agents research-only 架构、Strategy V0 和 S3 collector。

## 第一原则

- Mac是研究设计、代码主仓和git工作区：`/Users/alyaloale/Code/qount`；不长期保存全量数据。
- Windows外置盘`E:\qount_data`是数据和artifact存储真相；WSL路径为`/mnt/e/qount_data`。
- WSL `/home/alyaloale/Code/qount`是7945HX/RTX 4060计算工作区，代码按需更新，不要求每次镜像Mac。
- VPS 是所有 live / paper forward / dashboard 的生产真相：`qount-vps:/root/qount`；真实host只存仓库外inventory。
- WSL不作为当前实盘依据；完成数据必须发布到外置盘，WSL ext4只留可清理scratch。
- 旧 line A 必须保持关闭：`QOUNT_LIVE_ENABLE=false`。
- 加密 X4 / C×D 实盘看 `QOUNT_X4_LIVE_ENABLE`、`QOUNT_RV_LIVE_ENABLE`、
  `QOUNT_CXD_CARRY_ENABLE` 和 VPS state，不用 `QOUNT_LIVE_ENABLE` 推断。
- 不要在 WSL 启动 `qount-runner.timer`；当前加密生产调度看 VPS `crontab -l`。
- 生产cron当前必须为零entry；`deploy/cron/qount-production.crontab`只保留`DISABLED`历史命令。只读
  `qount-dashboard-publisher.timer`和`qount-daily-intelligence.timer`已获授权并保持`enabled/active`；后者每日`04:30 UTC`抓免费官方feed、
  运行六角色中文LLM、不可覆盖归档并发送个人微信。不得恢复live/paper cron、MiniTrend forward
  或其他交易systemd timer。未来重新评审时，外层lock仍必须直接放在
  `/run/lock/qount-*.lock`，不能依赖重启后不存在的`/run/lock/qount/`子目录。
- 2026-07-20 `qount-mini-trend-forward.timer`已纠正并保持`disabled/inactive`，authority writer oneshot保持`static/inactive`；
  publisher只读发布既有authority、系统健康和备份，不访问交易所、不刷新账户。Daily Intelligence unit显式移除Binance私钥和全部live
  authority，只访问官方公开源、relay和个人微信；不要把它与交易timer混淆，也不要恢复MiniTrend timer。个人微信凭据只保留
  `account_id/base_url/recipient/token`，最新context token从`/root/.openclaw/openclaw-weixin/accounts`动态读取；unit依赖
  `openclaw-gateway.service`并只读挂载该目录。不要重新复制静态context token到Qount凭据。
- 2026-07-22最新日报ID为`24defae6...6adc`、report hash为`f4d90e84...63a94`，3份feed、8份详情、2份行情和六角色请求均已归档；
  Dashboard `intelligence`为`available`，微信任务为`DELIVERED/SUCCEEDED`。外层`incomplete`来自四个角色的`needs_research`证据判断，
  不是运行故障。检查命令：

```bash
ssh -o ClearAllForwardings=yes qount-vps \
  'systemctl list-timers --all qount-daily-intelligence.timer --no-pager'
ssh -o ClearAllForwardings=yes qount-vps \
  'journalctl -u qount-daily-intelligence.service -n 40 --no-pager'
```
- 最新动态会话验证job为`6d51a764...4324`，状态`DELIVERED/SUCCEEDED`；生产NotificationStore为5 event/job/attempt、20行audit chain。
  旧代码回滚目录为`/root/qount-notify-backup.rl6QL6`，其中不含凭据。不得用该代码回滚覆盖当前四字段凭据；若必须回滚provider，需同时恢复
  相容凭据合同并重新执行真实通知验证。
- 2026-07-21 owner授权固定`100 USDT` canary并直接推进B/C/D。readiness中的60/10 forward、30 paper days和7 dry days
  只作观察并纳入readiness hash防篡改，不再阻断manual-arm readiness；账户/仓位/订单、funding/schema、标准batch/ledger/
  三方对账、UNKNOWN停机和owner最终hash确认仍阻断。`1000 USDT`仅是历史/order-free兼容上界，真钱四层强制100。
  VPS成功order-free run为`/root/qount/state/mini_trend/forward/runs/20260721T063854Z`；最终readiness为
  `ready_for_manual_final_arm`且blocker 0，但`live_orders_allowed=false`。四项最终证据为readiness
  `8496f70e...ad2a87`、batch/manifest `70d1b38b...6ff0a49` / `1520b6af...e2ec3`、ledger
  `70184860...575fb`、reconciliation `9971ca5f...22d96` passed。观察值为`0/0/0/1`且funding完整。
  当前未创建arm、registry仍为`research`、未开启live switch/timer、未发真实订单。Mac全仓`1497 OK`；VPS
  production/B-C-D/post-fix为`303/59/21 OK`。
- 当前有效 AI 模型是 `QOUNT_AI_MODEL=gpt-5.5`；`gpt-5.4` 会导致当前 relay 502 / 全 hold。
- ETH-only 主线必须显式加 `--research-profile eth-only`。
- 已看过窗口只算 `discovery_pool`；新 promotion 证据必须是 `validation_v1` once-only。
- 当前盈利工程主线不是继续默认 5m 调参，而是先跑 S1' 频段 × 策略族选择扫描。
- 每批有意义执行完成后必须更新记录文档：本线 changelog；若影响当前事实、生产或全局规则，
  同步更新 [current.md](current.md) 和 [update-log.md](update-log.md)。
- 新增研究或清理弃用代码前先按 [project-rules.md](project-rules.md) 做线归属和引用审计。

WSL存储预检：

```bash
ssh -o ClearAllForwardings=yes home \
  'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && scripts/storage/wsl_compute_storage.sh status"'
```

## 当前状态检查

先在 Mac 看工作区：

```bash
cd /Users/alyaloale/Code/qount
git status --short --branch
```

Alpha S3 的正式 7 天 public-data session 已在约 21 小时后中断并 fail closed；它不是训练或 promotion
证据。以下命令只用于检查和保留失败现场，不得 resume 或拼接：

```bash
ssh qount-vps 'systemctl status qount-alpha-collector.service --no-pager'
ssh qount-vps 'cd /root/qount-alpha && python3 -m json.tool \
  state/alpha-collector-current/alpha_agent_live_collector_session.json'
ssh qount-vps 'cd /root/qount-alpha && find state/alpha-collector-current/segments \
  -name "events.jsonl.gz.partial" -printf "%p %s bytes\n"'
launchctl print gui/$(id -u)/com.qount.alpha-collector-offload
tail -n 80 state/logs/alpha_collector_offload.log
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_live_collector.py \
  --verify-session-dir \
  state/research_runs/20260714T135630Z-alpha-agent-live-collector-session-7d-vps
```

读法：当前预期是 systemd `inactive/dead`、manifest `continuous_gate_eligible=false`、Mac offload
`last exit code=1`。22 个闭段中 19 pass/3 block，并有 orphan partial；这些文件保留为失败证据。不要启动
第二份，也不要让 offloader 删除失败段。需要确认服务保持停止时：

```bash
ssh qount-vps 'systemctl stop qount-alpha-collector.service'
```

旧 Mac session `20260714T112649Z-...-7d` 和失败 VPS session 都不得拼接。研究主路径改为 Mac 上的
checksum-verified Binance 历史归档：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_historical_microstructure.py
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_historical_derivatives.py \
  --start-date 2024-01-01 --end-date 2024-03-31
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_historical_tradeflow.py \
  --symbols ETHUSDT --start-date 2024-01-01 --end-date 2024-03-31 \
  --datasets aggTrades --cadence monthly
```

冻结 trade-flow v1 的 ETH anchor 已过 Q1/April 历史 IC/成本，但预注册 BTC/BNB/SOL Q1 复制全败，
DSR/PBO/G5/G6 仍 block。不要改冻结参数后复用 Q1/April，不要下载复制 April 追结果，也不做 runtime parity；
7 天连续采集不再是构造历史 dataset 的前置条件。

再从 Mac 查 VPS 运行状态：

```bash
ssh qount-vps 'cd /root/qount && git status --short --branch || true'
ssh qount-vps 'cd /root/qount && crontab -l'
ssh qount-vps 'cd /root/qount && tail -n 120 ~/cxd_live.log'
ssh qount-vps 'cd /root/qount && python3 -m json.tool state/x4/live/latest.json'
ssh qount-vps 'cd /root/qount && python3 -m json.tool state/cxd/live/latest.json 2>/dev/null || true'
ssh qount-vps 'free -m; ps -eo pid,rss,comm,args --sort=-rss | head -n 15'
```

production publisher当前路径评审：

```bash
ssh qount-vps 'cd /root/qount && PYTHONPATH=src ./.venv/bin/python \
	  scripts/operations/audit_publisher_paths.py \
	  --authority-root /var/lib/qount/dashboard-authority \
	  --backup-root /var/lib/qount/dashboard-backups \
	  --owner-authorized'
```

2026-07-20 19:37 CST记录的真实VPS审计返回`ready_for_authorization`、`authority_bundle_verified=true`、
`backup_state=verified_snapshot`、`enable_authorized=true`，audit hash为
`0dcabe64e648b358f9a280806f23d6eb8d64a6c0df303a2799107d9c4c7bcf1f`。publisher timer现已受控启用；它只读完整真实
batch/registry/ledger/notification/health/brief、OS健康和备份，不查询交易所、不授权订单。transport发送仍需独立授权；不得复制
fixture/legacy JSON、恢复production crontab、MiniTrend forward timer或打开订单/live开关。

authority writer只读接入命令（仅在重新获得具体私有API/order-free周期授权并生成新run后执行）：

```bash
ssh qount-vps 'cd /root/qount && PYTHONPATH=src ./.venv/bin/python \
  scripts/operations/write_authority_bundle.py \
  --repo-root /root/qount \
  --source-root /root/qount/state/mini_trend/forward/latest \
  --authority-root /var/lib/qount/dashboard-authority \
  --runtime-root /var/lib/qount/dashboard-runtime \
  --backup-root /var/lib/qount/dashboard-backups \
  --dashboard-root /var/www/qount/data \
  --lock-path /run/qount-dashboard/publisher.lock'
```

成功authority来自`/root/qount/state/mini_trend/forward/runs/20260720T101653Z`：账户preflight为flat、TOP3仓位/挂单为0，
projection与dry dispatcher通过且`exchange_mutation_attempted=false`。batch为
`5a1c94a4280bb578c9ff1e8745cb309983f0f978096070819865c4b4024f4815`，authority/result hash分别为
`d2648116252cc23235caa2bacf69e845d9190e343046466c4685609e79c8f34b` /
`720c5c5f2336eab1edff4be40884143904bf15b04b8439d0d2a9761d0f2d2118`。最后一次授权账户观测为
`486.15970914 USDT`、TOP3全平、0挂单；它已按15分钟规则标记stale，不能被publisher刷新成当前账户事实。不要为了刷新页面调用
private API、手工补文件、复制fixture或恢复forward timer。authority unit保持`static/inactive`，SHA-256为
`bf9773e7d5509b21534996a14679a20847f4896ee9bf0cfd9fe4bfb3c7372f9e`。

常见读法：

- `cxd_live_cron.sh` 是当前加密组合实盘入口；standalone `x4_live_cron.sh` 不应同时交易同一账户。
- `QOUNT_CXD_CARRY_ENABLE=0` 是当前默认：carry 暂停，趋势腿仍跑。
- `cron_guard.sh` 是未来若获授权后仍必须保留的脚本内防线：live 110 秒、publisher 90 秒、paper 1800 秒；
  crontab 外层 timeout 略大，只做最后兜底。`[SKIP] previous run still active` 是正常防重入，
  `[ALERT] exceeded ... runtime limit` 才是需要排查的超时。
- `build_exchange()` 默认 `fetchCurrencies=False`。Qount 不依赖 Binance 币种充值元数据，不要为了
  `load_markets()` 重新打开会访问私有 SAPI 的 currency fetch。
- 1.6G VPS 的常驻大户当前是 new-api/sub2api，不是 qount。若 `MemAvailable` 长时间低于约 250M、
  swap 持续增长或协议层再次超时，先看 top RSS 和残留 qount 进程；不要只看端口是否 listen。
- 仓库前端已改成只读Dashboard v1并部署到`https://qount.alyaloale.com/#/live`。served root只有
  静态assets和publisher生成的`data/v1`；旧legacy `data/*.json`已移出并备份到`/root/qount-dashboard-backup-20260719T183341Z`。
  publisher timer现为`enabled/active`，每两分钟验证真实authority、刷新四项系统健康、原子发布release、创建逐文件hash备份并做恢复演练；
  release保留当前+4个，备份保留latest+60个。Mac/WSL fixture不得复制上线。
  `RuntimeLedgerSnapshot` schema v3用同一SQLite读事务冻结positions、orders/events、fills、cash、recoveries、完整NAV历史、账户观测和
  三方对账；balance/available、actual gross、margin和peak/current drawdown已有权威账本合同。`SystemHealthSnapshot`固定要求
  `clock/disk/service/backup`四项强类型观测并使用独立freshness。
  Dashboard当前有`overview/positions/orders/strategies/decisions/risk/readiness/system/alerts/reports`十页，原子release为十份模型加
  `publication.json`共11个JSON，静态schema共13份。positions可点击进入decision trace；浏览器不读取legacy JSON、生产SQLite或
  交易所，也不重算PnL。最后一次授权账户快照为TOP3全平和`486.15970914 USDT`，但已按15分钟规则显示stale；system health
  独立保持fresh。authority writer保持`static/inactive`，publisher不刷新账户；真实webhook未接，order latency/slippage继续显式unavailable。
- `ledger/legacy_replay.py`只用于隔离的本地migration replay：输入必须是相互hash链接的projection与legacy dry plan，输出
  完整`VerifiedDecisionBatch`、仅`PLANNED`的临时账本和哈希报告。它不读取生产文件、不导入dispatcher或交易所adapter，
  也不能把已有transition/fill/cash/NAV/reconciliation状态重标成dry；不要把测试golden或临时SQLite复制到VPS当生产状态。
- `notifications/store.py`只由注入transport发送，固定delivery idempotency key并持久化attempt/audit；
  `notifications/transport.py`现有严格provider response、限流/超时、0600 credential和无key审计，但只提供fake provider，当前
  transport和本地`alerts.json`都是fixture。旧CTA-R SwiftBar/Übersicht与`cta.json`前端推送已删除，`com.qount.dashboard`已从Mac
  launchd卸载；`com.qount.ctar-daily`是独立研究任务，仍保留。
- WSL 的 `7907` 代理、`.env`、`qount-runner.timer` 只属于历史 line A 运维链路。

## 本地与 VPS 验证

本地测试：

```bash
cd /Users/alyaloale/Code/qount
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
```

架构Phase B/C本地聚焦验证：

```bash
./.venv/bin/python -m unittest \
  tests.test_runtime_ledger \
  tests.test_legacy_dispatch_replay \
  tests.test_ledger_dashboard_bridge \
  tests.test_dashboard_read_models \
  tests.test_notifications \
  tests.test_notification_producers \
  tests.test_daily_brief

./.venv/bin/python -m unittest \
  tests.test_mini_trend_signals \
  tests.test_mini_trend_risk \
  tests.test_mini_trend_execution \
  tests.test_mini_trend_scorecard \
  tests.test_mini_trend_backtest \
  tests.test_mini_trend_pilot_dispatcher \
  tests.test_dispatch_contract_adapters
```

当前读法：Phase B/C/D dispatcher现已接标准RuntimeLedger，market成交必须由exchange order和逐笔trade/USDT fee确认；
`SUBMITTING -> UNKNOWN + HALT`超时路径不会重发，异常authority发布halted registry。manual-arm动作会把同一hash绑定的registry
原子提升为`minimal_live`，但当前未运行该动作。本轮operations/health/publisher/authority/system-health历史边界聚焦为`29 OK`，
Mac全仓历史读数`1488 OK`，VPS默认production profile历史读数为
`299 OK`；更早的Phase B/C与边界`71 OK`、legacy adapter
`37 OK`等读数保留历史语境。更早的完整Phase A/B/C
`101 OK`等批次读数保留在`current.md`和`update-log.md`，不覆盖其历史语境。`ledger/store.py`、legacy dry replay、冻结snapshot adapter、notification
outbox/producers、incident sync、DailyBrief和Dashboard v1合同仍未接入订单路径、producer scheduler或真实webhook；publisher只读既有
标准source且`live_orders_allowed=false`。不要用fixture创建生产DB/read model，也不要据此打开live。
最新read-model QA使用Playwright 1.60 + Chromium 1223，桌面`1440x1000`和移动`390x844`检查Live、Positions到Decisions点击追踪、
System四项健康、移动菜单和缺release页面；无控制台异常、页面级横向溢出、重叠或裁切。生产release来自VPS authority writer，
不是测试fixture。

research ML 依赖检查：

```bash
./.venv/bin/python -m pip install -e '.[research]'
PYTHON_BIN=./.venv/bin/python ./scripts/check-research-deps.sh
```

读法：`numpy` / `sklearn` 必须 ok；`lightgbm` 是可选项。当前 Mac 上 LightGBM wheel
可安装但 import 缺 `libomp.dylib`，所以后续默认用 sklearn `HistGradientBoosting`。

S1' 频段 × 策略族 discovery 扫描：

以下 WSL 研究命令只作为历史证据链保留；当前不要把它当 live / paper 生产入口。

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF'
set -euo pipefail
cd /home/alyaloale/Code/qount
set -a
source .env
set +a
./.venv/bin/python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families xs_mom xs_rev ts_mom carry \
  --frequencies 5m 1h 4h 1d \
  --lookback-days 30 \
  --signal-lookback-bars 12 \
  --holding-bars 1 \
  --output-path /tmp/qount-strategy-selection-s1-30d-20260605.json
EOF
```

读法：命令只拉 discovery 历史 OHLCV / funding 并写 artifact，不调用 AI、不执行订单。
2026-06-05 初扫 top cell 是 `1d ts_mom`，但 rank-IC 很弱、有效广度约 1.13；
5m `xs_rev` 有正 IC 但 post-cost 大幅为负，不能 promotion。

120 天 sanity 结论：`1d ts_mom lb12/h1` 从 30 天正收益变成
`sum=-0.3885499348`、`sharpe=-0.4637426827`；月度切分里 2026-03 和
2026-04 都显著为负，不能进入 S2/S3。5m / CARRY 在 zero-cost 下转正，但
maker-ish `cost_per_directional_bet=0.0004` 后分别变成
`5m_xs_rev_sum=-26.4101457512`、`carry_sum=-0.0999394`。

2026-06-05 已补 OHLCV 列回归测试并在 WSL 复跑同一 120 天核心扫描，结论不变：
artifact 前缀为 `20260605T071948Z...ohlcv-rerun...`、`20260605T072101Z...zero-cost-ohlcv-rerun...`、
`20260605T072410Z...maker-ish-ohlcv-rerun...`。

S-CARRY 第一版 `threshold_dual_leg` 已接入显式 research 参数，默认 naive carry 不变。
120 天 4 币、entry `0.00008`、exit `0.00004`、min hold 3：
zero-cost `sum=+0.04728436`；maker-ish `cost_per_directional_bet=0.0004` 后
`sum=-0.16871564`，不能 paper。

固定 grid 已跑：entry `0.00004/0.00008/0.00012` × exit `0.00002/0.00004` ×
min-hold `1/3/6`。zero-cost best `sum=+0.07147182`，maker-ish best
`sum=-0.02967449`、entry `0.00012`、exit `0.00002`、min-hold `6`、
utilization `0.2708`、双腿平均 gross exposure `0.5417`。funding history 没有可用
mark/index，`basis_sample_count=0`。本地 / WSL 全量测试均为 `228 OK`。

`--carry-basis-source premium_index` 已接通 Binance 8h premium index kline。同一 fixed grid
maker-ish 复跑 artifact：
`/home/alyaloale/Code/qount/state/research_runs/20260605T083154Z-strategy-selection-scan-qount-strategy-selection-s-carry-fixed-grid-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-fixed-grid-premium-basis-maker-ish-20260605.json`。
结果：每币 361 根 premium bars，best 仍 `sum=-0.02967449`；basis `sample_count=390`、
avg abs `0.0005576725`、max abs `0.00143783`。本地 / WSL 全量测试均为 `229 OK`。

top12 universe 已完成同一 fixed grid + premium basis 扩币读数：

```text
symbols=BTC/ETH/ZEC/SOL/HYPE/WLD/XRP/BNB/NEAR/DOGE/ADA/SUI USDT perpetuals
maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083609Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605.json
maker_ish_best=sum -0.07594874, entry 0.00012, exit 0.00002, min_hold 6, turnover 221
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083859Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605/qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605.json
zero_cost_best=sum +0.27826189, entry 0.00004, exit 0.00002, min_hold 1, turnover 2104
```

读法：top12 zero-cost 证明 gross carry cashflow 变厚，但 maker-ish 成本后仍没有正 cell；WLD
是 maker-ish best cell 里唯一单币正贡献。下一步不要继续在同一 discovery grid 上挑阈值，
要转向 explicit hedge / spot-perp 双腿 replay、post-only 成交率、资金占用和 basis 风险。

`--carry-execution-cost-model per_order` + `--carry-capital-model spot_perp_gross` 已接入，
用于 explicit spot/perp 双腿资金占用读数；默认旧口径不变。top12、6x perp margin fraction
`0.1666667` 复跑：

```text
explicit_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605.json
order_cost=0.0002
best=sum +0.0106725083, entry 0.00012, exit 0.00002, min_hold 6, turnover 221
gross_funding=+0.0864439347
execution_cost=+0.0757714264
break_even_order_cost=0.0002281703
positive_cells=3/18
cost025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085742Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605.json
order_cost=0.00025
best=sum -0.0082703483
```

读法：出现小正候选，但成本缓冲很窄，basis max abs `0.00265777` 大于净收益边际；
仍不能 paper。下一步先做 post-only 成交率 / 实测订单成本 / basis tail 压力，不要把
discovery best cell 当 promotion。

`strategy-selection-scan` 已支持 `--holdout-role`。固定 top12 explicit spot/perp best cell
跑了新的 1 天 `validation_v1` sanity：

```text
val_jun04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103552Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
order_cost=0.0002
sum=+0.0003597343
break_even_order_cost=0.0002524613
basis_max_abs=0.00235832
val_jun04_cost025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103620Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605.json
order_cost=0.00025
sum=+0.0000168771
```

读法：新窗口没有立即证伪，但只有 1 天 / 51 funding samples / 4 entry events，成本压力后
几乎贴着 break-even；仍不能 paper。

同一 fixed-cell 已补 basis-tail 诊断复跑：

```text
val_jun04_basis_tail_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T104512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605.json
sum=+0.0003597343
basis_max_abs=0.00235832
basis_single_tail_loss_on_capital=0.0020214171
basis_single_tail_to_net_ratio=5.6191951202
portfolio_sum_after_single_basis_tail=-0.0016616828
```

读法：当前 1 天 fixed-cell 的小正收益被单次 basis tail 压力抹掉后转负；basis-tail 已经是
paper blocker。下一步不是 promotion，而是补 post-only fill / 实测订单成本，以及
basis-tail-aware hedge / exit 模型。

simple basis tail stop 已补为显式 research-only 参数 `--carry-basis-tail-stop-pct`，默认
不改变旧 artifact。已在同一 1 天 fixed-cell 上测试三个阈值：

```text
stop001_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105545Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605.json
stop=0.0010 sum=-0.0008075743 basis_tail_stop_events=2 after_tail=-0.0015092057

stop0015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105616Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605.json
stop=0.0015 sum=-0.0004218600 basis_tail_stop_events=1 after_tail=-0.0013877828

stop0020_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105622Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605.json
stop=0.0020 sum=-0.0004218600 basis_tail_stop_events=1 after_tail=-0.0013877828
```

读法：simple hard stop 降低了最大 basis 暴露，但退出成本和少收 funding 后都转负；
不要继续在这个 1 天窗口调 stop 阈值。

只读 `execution-cost-audit --limit 200` 只有 4 笔历史 live 市价单可分析，fee 缺失；
`p50_abs_slippage_pct=0.0440920717%`，已经高于当前 fixed-cell 假设的 `0.0200%`
per-order。

按 120 天 discovery 逐币贡献，`WLD/SOL/ZEC` 为正，但 ZEC 的 after-tail 为负；tail-aware
过滤后只保留 `WLD/SOL`：

```text
wld_sol_discovery=/home/alyaloale/Code/qount/state/research_runs/20260605T110031Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605.json
sum=+0.0378574446
after_tail=+0.0355793561
break_even_order_cost=0.0006330100

wld_sol_val=/home/alyaloale/Code/qount/state/research_runs/20260605T110033Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-20260605.json
sum=+0.0000535886
after_tail=-0.0006480428
break_even_order_cost=0.0002312600

wld_sol_val_cost025=/home/alyaloale/Code/qount/state/research_runs/20260605T110109Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605.json
order_cost=0.00025
sum=-0.0000321257

wld_sol_val_cost045=/home/alyaloale/Code/qount/state/research_runs/20260605T110114Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605.json
order_cost=0.00045
sum=-0.0003749828
```

读法：WLD/SOL 是最像样的 filter，但 1 天 sanity 对 basis tail 和成本都不过关；不能 paper。

WLD/SOL 月度 discovery 复核：

```text
feb=/home/alyaloale/Code/qount/state/research_runs/20260605T111620Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-feb-20260605/qount-strategy-selection-s-carry-wld-sol-feb-20260605.json sum=+0.0040478056 after_tail=+0.0028153799
mar=/home/alyaloale/Code/qount/state/research_runs/20260605T111622Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-mar-20260605/qount-strategy-selection-s-carry-wld-sol-mar-20260605.json sum=+0.0028695942 after_tail=+0.0017230457
apr=/home/alyaloale/Code/qount/state/research_runs/20260605T111625Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-apr-20260605/qount-strategy-selection-s-carry-wld-sol-apr-20260605.json sum=+0.0190945623 after_tail=+0.0168164738
may=/home/alyaloale/Code/qount/state/research_runs/20260605T111627Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-may-20260605/qount-strategy-selection-s-carry-wld-sol-may-20260605.json sum=+0.0119759397 after_tail=+0.0104161540
```

6 月已看/partial 读数：

```text
jun01_04=/home/alyaloale/Code/qount/state/research_runs/20260605T111629Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605.json sum=+0.0003015686 after_tail=-0.0004000628
jun05_partial=/home/alyaloale/Code/qount/state/research_runs/20260605T111654Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605.json holdout_role=unknown sum=-0.0002471743 after_tail=-0.0003076628
```

读法：2-5 月 discovery 支持 WLD/SOL filter，但 6/1-6/5 不支持 promotion；等新的完整独立
日期，或先解决 maker/post-only 成本。

用户要求不等新完整日期后，已补 post-only economics 诊断，只算所需 maker fill rate，不改
PnL。参数：`--carry-maker-order-cost-pct 0 --carry-taker-order-cost-pct 0.00045`。

```text
wld_sol_discovery_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113704Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605.json
after_tail=+0.0355793561
required_maker_fill_after_tail=0.0

wld_sol_jun01_04_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113706Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605.json
after_tail=-0.0004000628
required_maker_fill_after_tail=1.0741555556

wld_sol_jun05_partial_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113709Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605.json
holdout_role=unknown
after_tail=-0.0007569857
required_maker_fill_after_tail=1.0461944444
```

读法：成本不是唯一问题；6/1-6/5 after-tail 为正需要超过 100% maker fill，数学上不可行。

WLD/SOL basis-entry regime filter 已做完，不要重复当下一刀。新参数只影响 research scan：
`--carry-basis-entry-max-abs-pct` 会在新 CARRY 入场时过滤 abs(basis) 过大的 funding period；
默认关闭，不影响 live / `run-once`。已测阈值：

```text
basis_entry_max_abs=0.0008 discovery120d sum=-0.0066684341 after_tail=-0.0083560026
basis_entry_max_abs=0.0010 discovery120d sum=-0.0010824000 after_tail=-0.0028620256
basis_entry_max_abs=0.0015 discovery120d sum=+0.0020099742 after_tail=+0.0002303486
jun01_04 all thresholds sum=-0.0003841457 after_tail=-0.0010857771 required_maker_after_tail=1.0741555556
```

读法：0.0008 / 0.0010 在 120 天 discovery 已负；0.0015 只剩极薄正收益，且 6/1-6/5
完全不改善。entry-only basis filter 当前是 rejected/diagnostic，不是 paper 候选。

1d TS-MOM top12 扩币也已跑，不要把它当新候选：

```text
top12_120d=/home/alyaloale/Code/qount/state/research_runs/20260605T114959Z-strategy-selection-scan-qount-strategy-selection-s1-tsmom-top12-120d-20260605/qount-strategy-selection-s1-tsmom-top12-120d-20260605.json
sum=-2.6698947371
sharpe=-0.7852540386
rank_ic=-0.0517447570
effective_breadth=1.4732977614
feb_sum=-0.9962962887
mar_sum=-1.0361457305
apr_sum=-1.2542758681
may_sum=+0.7414512205
```

读法：top12 扩币后 1d TS-MOM 仍是 5 月单月贡献，2/3/4 月全负，不能进 S1.1/S1.2。

低频多 horizon prediction-family 网格已跑，这是当前最新主动推进方向。新参数：
`--signal-lookback-grid-bars` / `--holding-grid-bars`，只影响 `strategy-selection-scan`
预测族；`--directional-overlap-mode all|stride` 用于降低 overlapping holding horizon 膨胀；
`--directional-evaluation-mode portfolio_replay` / `--directional-max-open-positions` 用于限仓
组合 replay；`--directional-exit-mode triple_barrier` / `--directional-take-profit-pct` /
`--directional-stop-loss-pct` 用于 OHLC intrabar TP/SL barrier 复核；
`--directional-barrier-vol-lookback-bars` / `--directional-take-profit-sigma` /
`--directional-stop-loss-sigma` 用于波动率缩放 barrier(σ 缩放 TP/SL,防泄漏,默认关闭,
已证最佳仍跑不赢无 barrier 持有到期,不要重复);
`--directional-regime-min-dispersion-pct` 用于 entry 侧 regime dispersion 门(各币 signal
离散度低于阈值就跳过该 bar,纯决策时点,默认关闭;`thr0.034` 已证能把 3 月翻正且不降总收益,
下一刀只把它固定留到新完整 OOS once-only 复核,不要在已看窗口再调阈值)。这些参数默认不变，
不影响 live / `run-once`。scan 顶层还会输出 `directional_deflated_sharpe`(DSR) 与
`directional_pbo`(PBO/CSCV,按频段分组)两类多重检验惩罚;注意选出候选的 81-cell 网格
DSR ≈ 0.082(量级不显著)、pbo 4h=0.020/1h=0.056/1d=0.214(弱信号排名稳定但量级太弱),
进 S2 前必须有可接受 DSR/PBO。top12 低频网格：
`1h/4h/1d` × `xs_mom/xs_rev/ts_mom` × lookback `3/12/24` × holding `1/3/6`。

```text
lowfreq_grid=/home/alyaloale/Code/qount/state/research_runs/20260605T121551Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605/qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605.json
best=4h xs_mom lookback=24 holding=6
sum=+3.5251307739
sharpe=+7.1555415974
rank_ic=+0.0523457125
top2=4h xs_mom lookback=12 holding=6 sum=+3.2301871618
top3=1d xs_mom lookback=24 holding=6 sum=+2.9144790792
```

Fixed best 月度和已看 6 月 sanity：

```text
feb_sum=+0.0054374620 sharpe=+0.0534812097 ic=-0.0258203335
mar_sum=-0.3056398179 sharpe=-2.9328919686 ic=-0.0228488089
apr_sum=+0.9769441561 sharpe=+11.6825529071 ic=+0.0950044431
may_sum=+2.8938136721 sharpe=+16.4429358388 ic=+0.1603904117
jun01_04_sum=+0.2839507666 sharpe=+6.4057144483 ic=+0.1217418945
top_fraction 0.10/0.25/0.50 all positive on 120d discovery
```

Overlap sanity 已补，不要重复跑同一轮：

```text
stride_120d=/home/alyaloale/Code/qount/state/research_runs/20260605T123357Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605.json
stride_120d_sum=+0.5087944384
stride_120d_sharpe=+6.0811826595
stride_120d_rank_ic=+0.0607409120
stride_feb_sum=-0.0026969105
stride_mar_sum=-0.0234895413
stride_apr_sum=+0.0796046219
stride_may_sum=+0.5008009667
stride_jun01_04=/home/alyaloale/Code/qount/state/research_runs/20260605T123424Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605.json
stride_jun01_04_sum=+0.0627083513
```

读法：这是当前最像样的 prediction-family candidate，但还不是 paper。all-overlap 和 stride
下 120 天都为正，说明不是纯重叠 horizon 幻觉；但 2026-02 / 2026-03 月度 stride 仍为负，
`jun01_04` 只是已看窗口 sanity。下一刀做 S1.1/S1.2 的 purged-CV / triple-barrier /
overlap-aware portfolio replay；不要直接 promotion。

限仓 portfolio replay 也已补，不要重复当下一刀：

```text
portfolio_replay_120d=/home/alyaloale/Code/qount/state/research_runs/20260605T125713Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605.json
max_open_positions=12
sum=+0.2974912983
sharpe=+7.1945433715
max_dd=0.0876673733
trades=1446
skipped=2880
feb_sum=+0.0062629159
mar_sum=-0.0094161679
apr_sum=+0.0656249961
may_sum=+0.2463757288
jun01_04=/home/alyaloale/Code/qount/state/research_runs/20260605T125741Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605.json
jun01_04_sum=+0.0082009038
```

读法：限仓 replay 排除了“完全靠无限重叠下注”的解释，但 3 月仍为负，2 月只是微正；
现在下一刀是 purged-CV / triple-barrier / 新 OOS，不是继续 replay sanity，也不是 paper。

Simple triple-barrier 已补，不要重复当下一刀：

```text
tp/sl 120d:
  0.015/0.010 sum=-0.2542260860 sharpe=-21.9420203800
  0.020/0.010 sum=-0.2307013696 sharpe=-16.8127315231
  0.020/0.015 sum=-0.2296270771 sharpe=-14.6592774682
  0.030/0.015 sum=-0.1635040433 sharpe=-8.7264450618
best_least_bad_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132109Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605.json
exit_reason_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132953Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605.json
120d_exit_counts=stop_loss 873, take_profit 400, time 173
120d_win_rate=0.3443983402
tp0.030/sl0.015 monthly:
  feb_sum=-0.0356452182
  feb_exit_counts=stop_loss 224, take_profit 110, time 8
  mar_sum=-0.0631122398
  mar_exit_counts=stop_loss 242, take_profit 107, time 29
  apr_sum=-0.0812657295
  apr_exit_counts=stop_loss 211, take_profit 73, time 82
  may_sum=+0.0203985601
  may_exit_counts=stop_loss 205, take_profit 116, time 57
  jun01_04_sum=+0.0177000000
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132208Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605.json
```

读法：fixed TP/SL triple-barrier 直接否定当前 paper 资格。现在 `4h xs_mom` 只能继续
purged-CV / exit 设计 / 新 OOS；不要把 close-to-close 或 replay 正收益当 paper。负收益
主因是路径止损和成本：120 天 stop-loss `873` 次、take-profit `400` 次，止损约为止盈
`2.18x`。

Fixed-cell purged/embargo CV 已补，不要重复同一 close/replay sanity。新参数：
`--directional-purged-cv-folds` / `--directional-embargo-bars`，只影响
`strategy-selection-scan` 预测族 artifact；默认关闭，不影响 live / `run-once` / CARRY。

```text
purged_cv_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T133904Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605.json
full_sum=+0.2974912983
full_sharpe=+7.1945433715
positive_folds=3/4
min_fold_sum=-0.0566596009
fold1=+0.0467298450
fold2=-0.0566596009
fold3=+0.0611460588
fold4=+0.2462749954
```

读法：purged/embargo 诊断支持继续研究 `4h xs_mom lb24/h6`，但 2026-03-03..2026-04-01
fold 仍为负，不能 paper。下一刀应是更稳健的 exit 设计、模型层 purged-CV，或新的完整 OOS，
不是重复 fixed close/replay/purged 读数。

同步到 VPS 并安装：

```bash
./scripts/sync-to-vps.sh --install
```

VPS 测试：

```bash
./scripts/run-vps-tests.sh
```

默认只跑production最小依赖surface；显式全仓discovery使用`./scripts/run-vps-tests.sh discover`，需要VPS另装research/collector可选依赖。
这两个脚本只同步代码和跑 unittest，不会改 VPS `~/.config/qount/x4_live.env`，不会开关 cron，
不会改变 live arming。

## 历史 WSL 长任务坑(legacy only)

本节只用于追溯 2026-06 的 L6/WSL 数据批处理，不是当前生产部署说明。

- **后台进程不持久**:`ssh home "wsl.exe bash -lc 'tmux new -d ...'"` 起的 tmux / nohup 后台
  进程,在 ssh 命令一返回后会被 WSL 连同 `/tmp` 一起回收(WSL 会话结束即拆)。只有从 Windows 侧
  交互式 WSL 终端起、且该终端常开,后台才活。**从 Mac 远程驱动时,可靠做法是前台阻塞跑**:
  ```bash
  ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF'
  cd ~/Code/qount && bash scripts/research/l6_pipeline.sh 2>&1 | tee /tmp/l6_pipeline.log
  EOF
  ```
  ssh 连接全程挂着 = WSL 不回收,任务能跑完。命令行工具会把长任务转后台,但本地 ssh 进程仍挂着,
  同样保活。
- **嵌套引号**:走 `'wsl.exe bash -s' <<'EOF' ... EOF`(quoted heredoc)最稳,`$VAR` / `$(...)`
  在 WSL 侧展开,不被 Mac/PowerShell 层吃掉;`wsl.exe bash -lc '...'` 里带 `$` 容易被吞。
- **`l6_pipeline.sh`(external消费模式)**：`.7z`默认下到
  `/mnt/e/qount_data/qount/scratch/l6-incoming/`，归档写
  `/mnt/e/qount_data/qount/datasets/l6_l2_archive/`；可用`QOUNT_L2_SOURCE_DIR/QOUNT_L2_ARCHIVE`覆盖。
  `touch .../.l6_download_done` 让它处理完自退。失败的 `.7z`(损坏 / etl 错 / scored<6000 / xz 坏)
  自动移入 `_bad/`,不再重试。合法的低标的交易日(源数据本身 <6000,如 20260210=5178)登记到脚本里
  `LOW_OK_DATES` 白名单即可放行。幂等:archive 已存在的日子自动 SKIP。

## 标准研究命令

端到端 backtest：

```bash
python -m qount.main backtest \
  --research-profile eth-only \
  --holdout-role discovery \
  --start 2026-05-23T00:00:00+00:00 \
  --end 2026-05-23T03:00:00+00:00 \
  --review-horizon-bars 6
```

端到端 walk-forward：

```bash
python -m qount.main walk-forward \
  --research-profile eth-only \
  --holdout-role discovery \
  --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00
```

只读 setup 层：

```bash
python -m qount.main setup-edge-walk-forward \
  --research-profile eth-only \
  --holdout-role discovery \
  --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00
```

setup_model v1/v2 离线对比：

```bash
python -m qount.main setup-model-compare \
  --research-profile eth-only \
  --setup-phases range_noise short_rebound_fail_confirmed long_pullback_reclaim_confirmed short_breakdown_confirmed \
  --lookback-days 90 \
  --horizon-bars 6 \
  --min-samples 20 \
  --split-higher-phase \
  --eval-fraction 0.30 \
  --output-path /tmp/qount-setup-model-compare-ethonly-v2-range.json
```

读法：这是 setup_model 研究诊断，只拉历史 K 线并做 chronological split，不调用 AI、
不执行订单。`v2_interactions` 只有在显式 `--setup-model-version v2_interactions` 或
`setup-model-compare` 中使用；当前主线 v1 不变。

只读 candidate 层：

```bash
python -m qount.main candidate-walk-forward \
  --research-profile eth-only \
  --holdout-role discovery \
  --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00 \
  --max-bars-per-window 20
```

AI hold-bias 诊断：

```bash
python -m qount.main ai-hold-baseline \
  --research-profile eth-only \
  --artifact-dir state/research_runs \
  --prompt-variant v1 \
  --target-tags multi_range_action_pullback_sma_fast_gt008 \
  --limit 30 \
  --dry-run
```

注意：`--research-profile eth-only` 会过滤到 `ETH/USDT` 样本；如果复核 WS-4 的
multi-symbol fast-SMA 全量 24 样本，要改成 `--research-profile multi-symbol`。
`v2_remove_default_wait` / `v3_veto_only` 只用于研究重放，不会改变 live / `run-once`。

0 交易窗口诊断：

```bash
python -m qount.main idle-window-diagnostic \
  --research-profile eth-only \
  --artifact-dir state/research_runs \
  --horizon-bars 6 \
  --top-candidates 5 \
  --reason-limit 12 \
  --output-path /tmp/qount-idle-window-diagnostic-ethonly.json
```

读法：这是 diagnostic-only，只读已有 `qount.db` / `summary.json`，不调用 AI、不执行订单、
不改变 candidate / risk / live。`--research-profile eth-only` 会过滤到 `ETH/USDT`；
全局 reason aggregate 使用未截断计数，窗口内展示受 `--reason-limit` 限制。

AI 缓存只在研究 backtest / walk-forward 显式开启：

```bash
python -m qount.main walk-forward \
  --research-profile eth-only \
  --holdout-role discovery \
  --ai-decision-cache state/research_cache/ai_decisions.sqlite \
  --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00
```

不要在 live / `run-once` 里使用或模拟这个缓存。

## Artifact 规则

- 优先用 `state/research_runs/...` 下的持久 artifact。
- 如果命令显式写 `/tmp`，也要读取结果里的 `persistent_artifact_path` 或
  `persistent_artifact_dir`。
- promotion 级读数必须带 `holdout_role=validation_v1`。
- 2026-06-01..2026-06-03 两个 validation 窗口已经用过且端到端失败；后续不要在调参后
  复用它们宣称 promotion。
- `eth_short_range_noise_terminal_washout` blocker 把上述两个窗口降级 discovery 后转正，
  但 2026-06-03..2026-06-04 新 validation 的第一次 artifact 被 AI `auth_unavailable`
  污染；infra rerun 无 AI 错误但仍 realized 亏损。这个窗口也已经用过，后续只能降级
  discovery。
- `offline_future_edge_readiness` 只是离线 future-edge 读数，不是 promotion gate。
- `ready_tags=[]` 的窗口不要靠补 narrow override 强行变成 gate。

## 代码指针

- CLI：`src/qount/main.py`
- 配置：`src/qount/settings.py`
- 研究 profile：`src/qount/research_profile.py`
- backtest / walk-forward：`src/qount/backtest.py`、`src/qount/walk_forward.py`
- setup model / v2 compare：`src/qount/setup_model.py`
- research diagnostics：`src/qount/ai_hold_baseline.py`、`src/qount/idle_window_diagnostic.py`
- candidate / tags：`src/qount/candidate_filter.py`、`src/qount/entry_quality.py`
- AI：`src/qount/ai_client.py`、`src/qount/orchestrator.py`
- review / scan：`src/qount/review.py`、`src/qount/research_slice_scan.py`
- artifact：`src/qount/artifacts.py`
- 线 B GRID：`src/qount/grid/`、`scripts/research/grid_b_*.py`
- 线 C RV：`src/qount/rv/`、`scripts/desktop/rv_live.py`
- 线 D X4 / C×D：`src/qount/x4/`、`scripts/desktop/*x4*`、`scripts/desktop/cxd_*`
- 重启线 L1/L3/L4/L6：`src/qount/l*_*.py`、`scripts/research/l*_*.py`
- Alpha Agents / S3 collector：`src/qount/alpha_agents/`、`scripts/research/alpha_agent_*.py`
- 主测试：`tests/test_strategy_optimization.py`
- 交易所边界测试：`tests/test_exchange_throttling.py`

## 当前禁止事项

- 不把 `QOUNT_LIVE_ENABLE` 改成 `true`。
- 不安装production crontab，不enable任何qount systemd timer，不运行订单或真实notification transport。
- 不在 WSL 启动或 enable `qount-runner.timer`。
- 不把旧 `wf-*` 窗口当 validation。
- 不把 2026-06-01..2026-06-04 已看过窗口当新的 promotion 验证。
- 不用旧 G1/G2 解释 promotion。
- 不为了成交频率放宽 broad `range_noise`、`short_rebound_fail` 或 reclaim-long gate。
- 不把 Kronos 接到 candidate / risk / live。
- 不把 WSL `.env` 的 4-symbol 形状当 ETH-only 研究口径或生产实盘状态。
- 不把 WSL 当 live / paper / dashboard 生产面。
- 不新增未归类的计划文档；新研究线必须先写清归属、artifact 规则、promotion gate 和退出条件。
- 不删除 legacy 代码入口，除非先完成 `rg` 引用审计、文档改口和最小测试。
- 不启动第二份 Alpha S3 7 天 collector；失败 session 不 resume/拼接。历史 dataset 已替代 7 天前置 gate，
  但 frozen v1 的 G4/G5/G6 未过，仍不启动 A10/paper/live。

## 下一步执行顺序

> **2026-06-06 项目级决策（所有者确认）：执行 §7 诚实止盈，停止追盈利。** 根因是架构级广度
> 天花板——加密 majors r̄≈0.63，横截面有效广度仅 ~1.5、渐近天花板 `1/r̄≈1.6`（扩币救不了），
> 要求 IC 实际 ≈0.15、观测最强仅 0.05。横截面（XS-MOM/REV/funding）广度封死、日频 TS-MOM
> 已证伪、CARRY 已证伪。完整对账见 profit-engineering-plan.md §11.8。**不要再开新的特征 /
> 频段搜索**——那只会触发 §7 多重检验假象。

2026-07-08 owner 另行授权的 Alpha Agents / Strategy V0 属于“新微结构信息源”研究组织层，不推翻上述
旧特征空间停止结论。S3 public archive 数据 gate 和 frozen v1 historical OOS 已完成；当前只允许补其
预注册 anti-overfit/correlation-stress 证据，不借此恢复旧价格/频段扫描。

架构支线已完成账户/回撤、四项健康和position/decision trace。腾讯个人微信adapter及日报发送已获只读情报范围内授权并形成真实
`DELIVERED/SUCCEEDED`证据；legacy `Notifier`/shell ServerChan不得复用。production publisher和Daily Intelligence是当前两个active
qount timer，均不具备订单权限；authority writer保持`static/inactive`，最后一次授权账户快照已stale。不要为了刷新页面调用私有API或恢复
forward/cron；交易通知、订单和live仍未获授权。

1. **诚实停止 Alpha S3 trade-flow v1。** ETH Q1/April 为正，但 exact contract 在 BTC/BNB/SOL Q1 全败；
   不改 `z=2/hold=6/cooldown=18/polarity=momentum`，不下载复制 April，不事后造 candidate family，不做
   runtime parity，也不恢复 7 天 collector。重启必须先有结构性新信息或新的 ex-ante protocol。
2. **默认不再跑旧空间的新研究扫描。** 整套反过拟合 harness（triple-barrier、purged-CV+embargo、DSR、
   PBO/CSCV、effective-breadth、频段×族选择扫描）已作为研究成果固化；维护可跑回归测试，但不
   在已穷尽的特征/频段空间继续找 edge。
3. **重启的唯一触发条件是结构性新输入**：真正低相关的新 universe / 新资产类别，或可执行的低延迟
   微结构通道。普通的「再换一个特征 / 再加一个币」不构成重启理由（广度天花板与多重检验都封死）。
4. 已证伪、**不要重复**：`4h xs_mom` 的 exit/regime/barrier/purged-CV 复核；funding/basis 作
   预测特征（xs_funding/xs_funding_rev）；WLD/SOL entry-only basis filter；top12 1d TS-MOM；
   S-CARRY 现金流。
5. 硬纪律全不变：live 关闭、不 forward paper、不放宽 broad gate、`validation_v1` once-only 资格
   继续保留。止盈是停止投入，不是放松边界。
6. 只有 `G_paper` 通过后才讨论 forward paper；只有 forward paper 后才讨论 `G_live`——当前无
   promotion 证据，二者都不触发。
