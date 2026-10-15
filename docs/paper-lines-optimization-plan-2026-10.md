# 模拟盘研究线优化与 Tiingo 配额治理执行步骤（2026-10）

> **状态**：本地步骤已执行；48 小时线上观察与 291 点流水验收待完成｜**权威**：本文记录执行步骤与判据；当前事实仍看 [current.md](current.md)｜**最后更新**：2026-10-12
> **TL;DR**：先止血（三条线仍在伪造业绩数字 + Tiingo 配额在烧），再修口径（新鲜度写死日期、基准被填成 1.0），再接新线（持仓流水、CTA-R），最后做每条线各自的机制探索。
> **边界**：全程 `research_only=true / orders_authorized=false`。本文任何步骤都不下单、不改交易授权、不碰真实账户私有 API。密钥不打印、不提交、不导出。
> **性质**：**纯操作手册**。每条给出「做了什么 / 为什么 / 执行步骤 / 完成判据 / 回退」。不写代码，由 owner 执行。

## 0. 怎么用这份文档

执行顺序按优先级，**不要跳**：

| 阶段 | 内容 | 为什么排这里 |
| --- | --- | --- |
| 第 1 节 | 止血：三条线伪造数字、`/account` 伪造余额 | 正在污染界面结论，且与 design §2.1 修过的是同一个失败模式 |
| 第 2 节 | **Tiingo 配额治理** | 正在实际烧配额，今日已到上限 |
| 第 3 节 | 新鲜度与基准口径 | 两天后会自己触发一次误报（见 3.1 实测） |
| 第 4 节 | 持仓流水表 | 是 §6 所有机制探索的前提数据 |
| 第 5 节 | 其余研究线接入 | 依赖 §1 修完的 fail-closed 模式 |
| 第 6 节 | 每条研究线各自的机制探索方向 | 依赖 §4 的流水数据沉淀 |

**通用完成判据**（每阶段结束都跑）：

```bash
cd /Users/alyaloale/Code/qount
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
```

---

## 1. 止血：停止伪造业绩数字（P0）

### 1.1 问题事实（2026-10-12 只读核实）

`dual_engine` 已按 design §2.1 改成"无源即拒绝给数字"，但**同一条底线只落实在那一个文件**，其余四处仍在伪造：

| 位置 | 伪造内容 | 触发条件 |
| --- | --- | --- |
| `src/qount/api/routes/account.py:76` | `nav = 1000000.0` 直接穿透到界面显示 `¥1,000,000.00`，且 `error=None` | 调和包里找不到 `MA120_Band1.5pct` 基线 |
| `src/qount/api/routes/account.py:84` | `entry_date = "2026-04-24"` 常量兜底 | 同上 |
| `src/qount/api/adapters/binance_macro.py:28-46` | `LineMetrics(cagr_pct=41.29, max_drawdown_pct=36.63, sharpe=0.90, ...)` 与 7 个手写 `NavPoint` | `summary.json` 不存在 |
| `src/qount/api/adapters/ashare_master.py:28-40` | 同上模式，起始点写死 `NavPoint(date="2013-01-04", nav=1.0000)` | 同上 |
| `src/qount/api/adapters/personal_assistant.py:31-42` | 同上模式；`metrics` 全部硬编码；`except Exception: pass` 静默吞异常（:62, :91） | 同上 |

**为什么这是 P0**：界面上的 `+41.29%` 和一个真实的 `+41.29%` 无法区分。`docs/frontend-backend-rewrite-design-2026-10.md:49` 已经把这条写成硬规则——"任何新增适配器都必须通过对应的反例测试"——但这三条线没有对应的反例测试，反而被现有测试**断言成契约**。

### 1.2 步骤

**步骤 1.2.1 — 先给这三条线补反例测试（先写测试，后改代码）**

1. 打开 `tests/api/test_adapters.py`。
2. 仿照已有的 `test_dual_engine_missing_snapshot_reports_no_figures`（:130）写三个新测试：把 `config["run"]` 指向一个**确定不存在的临时目录**，然后断言：
   - `line.error` 非空且能看出是"源缺失"；
   - `line.metrics is None`；
   - `line.nav_series == []`；
   - `line.status == "MISSING"`、`line.freshness == "MISSING"`。
3. 同时**删掉**现有的字面量断言：`test_binance_macro_adapter`（:48-63）里的 `assertEqual(line.metrics.cagr_pct, 41.29)` 与 `assertEqual(line.metrics.max_drawdown_pct, 36.63)`——这两行是在把 bug 固化成契约。
4. 先跑一次，**预期这三个新测试全部失败**。这是正确的第一步：说明它们确实在伪造。

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest tests.api.test_adapters -v
```

**步骤 1.2.2 — 把三个适配器改成 fail-closed**

对 `binance_macro.py`、`ashare_master.py`、`personal_assistant.py` 各做同样四件事：

1. 删掉函数开头的 `LineMetrics(...)` 字面量块，改为 `metrics = None`。
2. 删掉 `nav_series` 的字面量列表，改为 `nav_series = []`。
3. 把 `except Exception: pass` 改成**显式失败分支**：捕获后返回带 `error` 的不可用行，不要继续往下走。错误码建议沿用 `dual_engine` 的命名（`SOURCE_NOT_FOUND` / `SOURCE_UNREADABLE` / `…_EMPTY`）。
4. 只有**真正解析到** `summary.json` / `baseline-replay.json` 之后才构造 `LineMetrics`。

改造后 `os.path.exists(summary_path)` 为假时，函数应返回与 `dual_engine._unavailable()` 同形状的行。

**步骤 1.2.3 — 修 `/account` 的伪造余额**

`src/qount/api/routes/account.py:70-107`：

1. `ma120_baseline` 为 `None` 时**不要**保留 `nav = 1000000.0`，改为构造 `error="BASELINE_ABSENT: …"` 的快照（该函数:47-61 已有正确的失败形状，照抄即可，只是换个错误码）。
2. 删掉 `entry_date = "2026-04-24"` 常量兜底——读不到 trades 文件就不给进场日期（`entry_date=None`）。
3. `:67` 的 `produced_at` 默认值 `"2026-10-12T09:00:00Z"` 和 `:110` 写死的 `as_of` 也是同类问题：读不到就用文件 mtime，不要写一个"看起来像真时间"的常量。

**步骤 1.2.4 — 前端补 `status-missing` 渲染确认**

`web/app/app.js` 已有 `status-missing` 徽章（:228）与 `data-unavailable` 文案（:270）。改完后打开界面确认：这三条线显示"✕ 无数据源"，而**不是**灰色 `--`。两者必须可区分。

### 1.3 完成判据

- 三个新反例测试 + 全部 `tests/api` 通过。
- 本地把三条线的 `config.run` 指向空目录，`curl` `/paper/lines` 返回的对应行 `metrics` 为 `null`、`error` 非空。
- 界面上这三条线显示"无数据源"，详情面板不显示任何数字。

### 1.4 回退

三条适配器文件各自 `git checkout` 回退；测试改动随代码一起回退。**不要只回退测试**——那会留下仍然伪造的代码。

---

## 2. Tiingo 配额治理（P0，今天已在烧）

### 2.1 问题事实（只读核算）

今日 Tiingo 到达上限，**不是代码 bug，是调用设计**：三个独立消费者共用一个免费 key，没有任何请求数记账，也没有任何缓存。

| 消费者 | 稳态请求数 | 频率 | 每日请求数 |
| --- | ---: | --- | ---: |
| `forward_collector.TiingoEodSource`（`src/qount/research/forward_collector.py`） | 2（SPY + TLT） | 15 分钟 timer；每个 UTC 日每标的最多请求一次 | 2 |
| `dual_engine` daily-close（`src/qount/dual_engine/market_data.py` + `reference_data.py`） | 通常 10：7 个执行标的 + BIL + SPY/TLT 基准；7 个 proxy 只在月末信号日刷新 | 每日 22:30 UTC | 通常 10；月末信号日 17 |
| `dual_engine` G20 open IEX（`src/qount/dual_engine/market_data.py`） | 7 | 13 个再平衡日；daily bars 与基准复用前一日缓存 | 通常 0；再平衡日 7 |
| **合计（稳态）** | | 普通日 / 月末信号日 / 月初再平衡日 | **12 / 19 / 19** |

冷启动缓存缺失时，dual_engine 首轮需为 15 个日线标的各请求一次完整 450 日窗口，连同 SPY/TLT 基准与 L1 passive 共 19 次；预算表按缓存建立后的稳态列示。每月唯一 Tiingo 标的并集为 17 个（7 proxy、7 execution、BIL、SPY、TLT），低于 25。

两个放大器让这个数字比看上去更糟：

1. **全历史取数只留最后一行。** `forward_collector.py` 每次请求 `startDate=2010-01-01`（来自 `deploy/research/forward-sources.json`）的全部 SPY/TLT 日线，然后只取最新可用行。旧逻辑是 96 次/天，扔掉的数据比留下的多四个数量级。
2. **零缓存。** 全仓 `state/research_cache/` 下只有 `tiingo_spdr_sector_etf`（由 `scripts/research/sleeves/run_spdr_sector_breadth_g0.py` 通过 `qount.legacy.l1.l1_cross_asset.fetch_cross_asset_panel(cache_dir=…)` 写入），**L1 passive 这条没有任何落盘缓存**，每轮都打网络。

3. **429 无退避，且不留证据。** `forward_collector.py:565-566` 的失败分支只记 `{"symbol": …, "error": type(error).__name__}`——**不记 HTTP 状态码**。所以限流在证据里看不出来，下一轮定时器照常再撞。`qount-research-forward-collector.service` 每 15 分钟 `Type=oneshot` 重启一次，没有跨轮状态。

原版 `docs/vps-deployment-runbook-2026-10.md` 把 "Tiingo 429" 归为"外部限流，非本地问题"；已按 owner 要求修正为：429 响应本身来自外部，但反复触发的预算、全历史轮询和无缓存属于本地调用设计问题。具体定性见 runbook 当前第 756 行。

### 2.2 目标预算

改造后目标：**每日 Tiingo 请求 ≤ 20，唯一标的数每月 ≤ 25**。留出至少 10 倍余量，因为免费档配额随时可能被同 key 的临时研究脚本（`scripts/research/` 下有多处直接读 Tiingo 的入口）吃掉。

### 2.3 步骤

**步骤 2.3.1 — 给 L1 passive 加落盘缓存（收益最大的一步）**

1. 参照已经存在的实现方式，不要另造轮子：`run_spdr_sector_breadth_g0.py:33-47` 用 `cache_dir` + `fetch_cross_asset_panel(...)` 落盘，`generate_reconciliation_receipt.py:96-104` 读同样路径的缓存。**L1 passive 复用这个模式。**
2. 缓存目录建议 `state/research_cache/tiingo_l1_passive/`，文件名 `tiingo_{SYMBOL}.json`，与既有命名一致。
3. 缓存写入时同时写 `sha256`，采集证据里带缓存来源标记，让"用了缓存"和"打了网络"在证据链里可区分——这与 `forward_collector` 现有的 `payload_hash` 链一致。
4. **不要把缓存做成静默兜底**：缓存缺失或过旧时，仍要如实报 `insufficient`，不要用陈旧缓存冒充当前观测。

**步骤 2.3.2 — 把"每 15 分钟"和"每天需要的 Tiingo 新数据"解耦**

L1 passive 是**日频 EOD** 来源，15 分钟轮询拿不到任何新信息。二选一：

- **方案 A（推荐）**：`forward_collector` 保留 15 分钟 timer 不动（它还要采 Binance REST / FOMC / liquidation，这些确实需要高频）；只在 `TiingoEodSource` 内部做"当日已有缓存则跳过网络"。这样 Tiingo 请求变成 **每日 2 次**，其余 94 轮走缓存，其他来源完全不受影响。
- **方案 B**：把 Tiingo 单独拆到一个每日 timer。改动更大、要动 systemd 单元，但隔离更彻底。

**判据**：改造后跑一天，`forward_collector` 的证据里应当只在每天第一次出现 Tiingo 网络请求，其余轮 `source=cache`。

**步骤 2.3.3 — 把全历史取数改成增量**

1. `forward_collector.py:544` 的 `startDate={start_date}`（固定 `2010-01-01`）改为增量：从缓存里最后一个交易日的前一天开始。
2. 缓存不存在时才做一次全历史（一年一次量级）。
3. 实际定时入口是 `collect_dual_engine_market.py` → `market_data.collect_market_cycle`；`dual_engine/backfill.py:collect_ytd_replay` 是独立历史回放，不是 daily-close 服务路径。`deploy/dual_engine/paper-v1.json` 的 450 日窗口用于首次建立足够长的滚动日线缓存。之后 7 个 proxy 只在月末信号日增量更新，平时从带哈希缓存读取；7 个执行标的与 BIL 每日增量更新，重叠前一日以覆盖修订。G20 open 复用最近 daily bars 和 SPY/TLT 基准缓存，只请求 7 个 IEX 首分钟价格。缺缓存或缓存校验失败不静默使用损坏数据；正常空缓存会进行一次完整窗口初始化。

**步骤 2.3.4 — 429 退避 + 显式记状态码**

1. 在 `_default_fetch_json`（`forward_collector.py:296`）里捕获 `urllib.error.HTTPError`，**把 `error.code` 带进错误对象**。
2. `TiingoEodSource.collect` 的 `errors` 列表里增加 `"http_status"` 字段。
3. 收到 429 时**不在同一轮内重试**（避免撞得更狠），而是记录 `throttled` 状态并让本轮该 source 返回 `insufficient`，等下一个周期。
4. 连续 N 轮（建议 4 轮 = 1 小时）都是 429 时，在状态里升一个显式告警级别，让 `/research/registry` 或证据链里看得出来——不要让它静默地一直是 `insufficient`。

**步骤 2.3.5 — 加请求预算表（防止回归）**

1. 在文档里维护一张"谁在消费 Tiingo、每天多少次"的表（即本文 2.1 那张），改任何 timer 或 startDate 时同步更新。
2. 在 `forward_collector` 的证据里记录本轮／当日请求数；Dual-Engine collector 将每次实际 Tiingo 请求追加到状态根 `tiingo-request-attempts.jsonl`，并在 systemd 输出中给出本轮请求数，供跨消费者累加核对。
3. 把"每 15 分钟全历史拉 SPY/TLT"这个具体反模式写进 `docs/project-rules.md` 的禁止项——它未来很容易被重新引入。

**步骤 2.3.6 — 治理 `scripts/research/` 下的直接入口**

`scripts/research/cta_r_us_replication.py`、`mini_trend_tradifi_weekend.py`、`mini_trend_periodic_allocation.py` 都直接持有 Tiingo 调用入口。这些当前不常跑，但**共用同一个 key**。步骤：

1. 逐个确认它们是否已走缓存；没有的加缓存。
2. 在文件头部注释里写明"本脚本消耗 Tiingo 配额，勿在未核对预算时批量运行"。

### 2.4 完成判据

- L1 passive 缓存目录出现，且第二轮采集的证据显示 `source=cache`。
- 连续观察 48 小时，Tiingo 每日请求数 ≤ 20（合并 `forward_collector` 每日账本与 `/var/lib/qount/paper/dual-engine/tiingo-request-attempts.jsonl`；临时脚本也须计入）。稳态预计普通日 12、月末信号日和月初再平衡日最多 19；冷启动完整缓存初始化可能高于稳态，须单独标记。
- 手动把缓存删掉再跑一轮：应当正常回落到网络取数并重建缓存，**不是**报错。
- 人为制造一次 429（或用错误 token）时，证据里能读到 `http_status: 429`，而不是只有一个裸的 `HTTPError`。

### 2.5 回退

缓存目录可整体删除（`rm -rf state/research_cache/tiingo_l1_passive`），删掉后行为退回当前状态。systemd 单元在本节**不做改动**（方案 A），因此没有单元回退需求。

---

## 3. 新鲜度与基准口径修正（P1）

### 3.1 `compute_freshness` 的参考日期写死（会自己触发）

**事实**：`src/qount/api/adapters/utils.py:31` 的 `reference_date` 默认值是 `"2026-10-12"`——**正是部署当天**。实测：

| 参考日期 | `compute_freshness("2026-10-09")` |
| --- | --- |
| 2026-10-12 | `FRESH` |
| 2026-10-15 | `STALE` |
| 2026-10-20 | `STALE` |

也就是说，**三天内全部研究线的新鲜度徽章会一起翻成"待更新"**，与数据实际是否更新无关。这是个会自己引爆的定时炸弹，不是风格问题。

**步骤**：

1. 把参考日期的来源改为"实际当天"（`datetime.now(timezone.utc).date()`），而不是常量。
2. 把"多少天算 STALE"从散落的 `4`（`utils.py:41`）抽到一个配置里——这正是 design §7 第 5 点承诺过但**从未创建**的 `config/api.json`。顺带把各适配器里的魔数一并集中过去。
3. 新增测试：把参考日期分别设为 `as_of+3` / `as_of+5`，断言 `FRESH` / `STALE` 翻转点在预期位置。**不要**再断言某个具体日期字符串——那正是这次写死默认值的成因。
4. 检查有没有别的适配器也传了 `config.get("reference_date")`：`dual_engine.py:264,315` 和 `personal_assistant.py:94` 都有这个模式。统一到同一个来源。

**判据**：把系统时间往后调 5 天，重跑测试仍通过（或显式断言翻转），而不是界面集体变"待更新"。

### 3.2 基准净值被填成 1.0

**事实**：`src/qount/api/adapters/dual_engine.py:202` 的 `benchmark_series.get(benchmark_date, 1.0)`；`schemas.py:12` 默认值 `benchmark_nav: float = 1.0`；`db.py:98` 的 `float(pt.get("benchmark_nav", 1.0))`。三层都是同一个默认值。

后果：**基准缺失时界面画一条恒定 1.0 的平线**，而 1.0 是合法净值——看起来像"基准原地不动"，无法区分于"基准不可用"。这与 design §2.1 反对的"静默兜底"是同一个错误。

**步骤**：

1. 把 `NavPoint.benchmark_nav` 改为 `Optional[float] = None`，`db.py` 的列允许 `NULL`。
2. `dual_engine.py:202` 改为 `benchmark_series.get(benchmark_date)`（缺失即 `None`）。
3. 前端 `app.js:372,458` 在基准全为 `null` 时不加那条 series，并显示"基准不可用"，而不是画平线。
4. 同时修 `:187` 的时间口径不一致：x 轴用完整时间戳（`_format_nav_point_time`），基准却用 `format_date_str(marked_at)` 取 key——**同一源两套口径**，同日多次标记的点永远匹配不到基准。统一为同一套 key。

### 3.3 `db.py` 的日期排序与生命周期

1. `db.py:145` 的 `ORDER BY date ASC`：`date` 列可能混存 `2026-10-09` 与 `2026-10-09T15:00:30Z` 两种格式，字典序 ≠ 时间序。改为在应用层按解析后的时间排序，或统一存储格式。
2. **下线线不删行**：`config/paper-lines.json` 里把线设成 `enabled: false` 后，`get_paper_lines_summary`（`db.py:112`）照样返回旧行。步骤：ingest 时对比注册表与库，把不在注册表里的 `line_id` 删掉或标记 `RETIRED`。
3. **每轮全量重写 NAV**（`db.py:96` 的 `DELETE` + 重插）：没有留存、没有审计轨迹，也让"两次 ingest 之间发生了什么"不可查。这与 §4 的流水表是同一个问题的两面。

### 3.4 本地库已经陈旧不一致（现场风险，先于上面任何步骤）

**事实**：`state/qount.db` 里只有 **4 条线**（`ashare_master`、`binance_macro`、`dual_g20`、`personal_assistant`）和 440 个 NAV 点——缺 `dual_gc5`、`dual_d15`（注册表共 7 条）。因为 `main.py:24` 只在表为空时才 ingest，**本地启动不会重新 ingest**，所以本地看到的是另一个世界的数字。

**步骤**：

1. 本地调试前先隔离库：`QOUNT_DB_PATH=/tmp/qount-dev.db`，或删掉 `state/qount.db` 后重启。
2. **不要**把本地库当线上事实对照——`scripts/sync-to-vps.sh:76-88` 的 `items` 不含 `./state`，VPS 的库是独立演化的。
3. 记一笔：全仓**没有任何 ingest timer**（`deploy/systemd/` 下没有对应单元）。publisher 按 runbook §7.3 停掉后，页面数据不会自己更新。**在停 publisher 之前，先决定 ingest 由谁定时触发。**

---

## 4. 持仓流水表落地（P1，§6 的前提）

### 4.1 为什么

owner 的原始要求是"记录持仓记录，方便后续分析"。当前只有当前快照的 `positions`（`dual_engine.py:234` 的 `_build_positions`），**无法回答"什么时候换的仓、换了什么"**。§6 所有机制探索方向都依赖这份流水。

design §5.3 描述过两张表与两个端点，**至今未实现**。

### 4.2 步骤

1. **建表**：按 design §5.3 的 `paper_positions` 与 `paper_trades` 定义建表。主键注意用 `(line_id, date, symbol)`；`date` 必须是带时间戳的形式，**否则会重演净值点被覆盖的那个 bug**。
2. **diff 生成流水**：每轮 ingest 时把新快照的 `holdings` 与库里上一轮对比，差异生成为一次 `OPEN` / `CLOSE` / `ADJUST` 记录。**不要**从净值曲线反推调仓——那是猜。
3. **口径标注（硬要求）**：所有记录标 `simulated_not_realized`。这不是真实成交，成本按该线合同声明的费率（`deploy/dual_engine/paper-v1.json` 及各线合同里注明的 25 bps 基础 / 50 bps 压力）。
4. **端点**：`GET /paper/positions?line_id=…&start=…&end=…` 与 `GET /paper/trades?line_id=…&limit=…`。参照 `routes/paper.py` 现有风格，保持只读。
5. **前端第三屏**：当前持仓 + 调仓时间线。**必须**和"当前持仓"分开展示，并在页面上明写这是模拟调仓。
6. **测试**：造一个两轮快照（第 2 轮换仓），断言生成的流水恰好是一条 BUY + 一条 SELL，且同一天两次标记不互相覆盖。

### 4.3 完成判据

拿 G20 的 291 个点跑一遍，`paper_trades` 里应当能读出每次月度再平衡的日期与标的。用 `docs/qount_strategy_master_index.md` 里记录的再平衡日为对照核对。

---

## 5. 其余研究线接入（P1）

### 5.1 接入顺序（有理由，不要按方便程度排）

design §5.2 给的顺序是对的，此处只补充**为什么**：

| 顺序 | 线路 | 理由 |
| ---: | --- | --- |
| 1 | **CTA-R 侧车** | **唯一有真实前瞻账本的线**（`qount-research-cta-r-forward.timer` 每日 18:45 在跑，写入 `/var/lib/qount/research/cta-r-forward`）。其余线都是回放，只有这条是真 forward。先接它，才能最早积累真实前瞻样本。 |
| 2 | Q-DIV-Core | 门槛失败被 STOPPED。接入的价值是**让失败可见**——design §2.1 明确要求"坚决不隐藏失败结论"。 |
| 3 | ETF Trader P2/P3 | 同上，STOPPED 状态需要如实展示。 |
| 4 | C60 v1/v2/PIT/梯度 | ARCHIVED（选币优势已撤回）。接与不接都可以，接了必须**显式标注撤回原因**，不能只留一条好看的曲线。 |

### 5.2 接入时的硬约束

1. **先修完 §1**，让 fail-closed 成为可复制的模板——否则新接入的线会重复同样的伪造模式。
2. design §5.2 的列表里 `state/cta_r/` 路径**当前是错的**：本地 `state/cta_r/` 下只有 `etf_source`，真实账本在 VPS 的 `/var/lib/qount/research/cta-r-forward`。接的时候按 VPS 路径写，并走 `QOUNT_*_STATE_ROOT` 这类环境变量覆盖，保持"一条注册表项在所有主机通用"。
3. 每条新线都要**配一个反例测试**（源缺失时不给数字），这是 design §2.1 立的规矩。
4. **不要把 STOPPED/ARCHIVED 的线设成 `enabled: false` 藏起来**——那会让 §3.3 的下线不删行问题更难发现。让它们在界面上显示为停止，正是这个面板的价值。

---

## 6. 每条研究线各自的机制优化探索方向

> **前提**：本节依赖 §4 的流水表。没有调仓流水，下面的探索只能得到"曲线看起来如何"，得不到"为什么"。
> **纪律**：每条方向都必须走 G0 → 预登记 → 证伪，`orders_authorized=false`。不要因为某条线 YTD 好看就跳过证伪。
> **共同警告**：G20 的 YTD +15.26% 含部署时历史回放，同期最大回撤 **-16.33%**（`docs/frontend-backend-rewrite-design-2026-10.md:2.2`）。**YTD 不能年化外推。** 任何优化必须以"收益与回撤并排"为验收口径。

### 6.1 G20（美股轮动，`1x` 代理 63 日 Top1，风险资产 20% / BIL 80%）

当前形状：`docs/qount_strategy_master_index.md:25`。核心特征是**已极度保守**（80% BIL），所以优化空间不在"加杠杆"，而在两个地方：

| 方向 | 假设 | 证伪判据 | 优先级 |
| --- | --- | ------- | --- |
| **G1. 风险预算动态化** | 固定 20% 风险资产在低波动期浪费了预算，在高波动期又不够保守 | 用 63 日实现波动分位分档，若分档后的可执行净值在**同最大回撤**下未超过固定 20%，则关闭 | P1 |
| **G2. 信号门去噪** | 当前"无 `>0` 绝对门"意味着弱动量也算数，可能是 16% 回撤的来源 | 加绝对动量门后，若交易次数下降但 Calmar 不升，则关闭 | P1 |
| **G3. Proxy/Execution 配对** | 用 1x 代理（QQQ 等）出信号、3x 执行（TQQQ 等）成交，**杠杆 ETF 的路径衰减**可能吃掉信号超额 | 把 `G20_PROXY_SYMBOLS` 与 `G20_EXECUTION_SYMBOLS` 的信号净值差拆开量化；若差值是衰减而非成本，则考虑 1x 执行 | **P0** |
| **G4. 再平衡日效应** | 月初 T+1 执行是否存在系统性逆向选择 | 用流水表统计每个再平衡日的执行价 vs 当日 VWAP 近似，若持续不利则调整执行窗口 | P2 |

**G3 排 P0 的理由**：这是唯一一个**收益与可执行性直接挂钩**的方向。`_ACCOUNT_TO_PORTFOLIO` 里 G20 的 signal/executable 两层净值差多少，直接决定"看起来好"和"真能拿到"的距离——design §2.2 已经在 C60 上量出过 6.90 个百分点的差。

**第一步动作**：先不改策略。用 §4 的流水表把 G20 每个月的"信号选择的标的"和"实际成交的标的"列出来，看 3x 执行标的是否长期跑输它对应的 1x 代理。这一步只读，零风险。

### 6.2 C60（加密趋势，日频 90 日正动量 Top2）

当前形状：`docs/qount_strategy_master_index.md:26`。已知问题：YTD 为负（-0.94%），累计成本 835.29（`tests/api/fixtures/.../paper_program_snapshot.json` 里 C60 的 `cumulative_cost`），signal 0.94526 vs executable 0.867023 —— **差 7.8 个百分点，是四条线里最大的一条**。

| 方向 | 假设 | 证伪判据 | 优先级 |
| --- | --- | ------- | --- |
| **C1. 成本结构重审** | 7.8pp 的 signal/executable 差远大于 25 bps 的名义费率，说明**换手频率**才是主因 | 把流水按 symbol 拆开算实际换手，若年换手 > 20 次，先降频而不是先改信号 | **P0** |
| **C2. Top2 集中度** | 10 个标的里选 Top2，单标的权重过大，导致 18.87% 的 YTD 回撤 | 对比 Top3/Top4 在**同回撤**下的收益；若无改善，关闭 | P1 |
| **C3. PAXG 例外的合理性** | 合约给 PAXG 开了例外（`master_index:26`），这个例外是不是过拟合 | 去掉例外重跑，若结论方向不变则该例外无用，关闭 | P1 |
| **C4. vol cap 60% 的紧松** | 60% 波动上限可能在牛市压制收益、在崩盘时来不及降 | 分档回测，看回撤分布是否真的被 cap 改善 | P2 |

**C1 排 P0 的理由**：design §2.2 明确写着"C60 两层净值差 6.90 个百分点，这正是'看起来好'与'真能拿到'的差距"。**先把成本算清楚，再谈信号优化**——否则所有优化都可能被换手成本吃掉。

**第一步动作**：用 §4 的流水表统计 C60 的实际年换手次数与每次的名义金额。这一步纯读库。

### 6.3 GC5（固定 95/5）与 D15（动态 2.5/7.5/10/15）

当前形状：`docs/qount_strategy_master_index.md:28`。这两条是**组合层**，不是信号层。它们的价值是回答"袖套怎么配"。

| 方向 | 假设 | 证伪判据 | 优先级 |
| --- | --- | ------- | --- |
| **P1. D15 权重阶梯是否值得** | 2.5/7.5/10/15 四档 vs 更简单的等权，复杂度是否换来收益 | 若 D15 相对 GC5 的超额 < 复杂度成本，则简化 | P1 |
| **P2. 再平衡触发条件** | 当前"仅 G20 月度执行事件允许跨袖套再平衡" | 对比纯日历再平衡 vs 阈值再平衡；若无改善，保持现状 | P2 |
| **P3. GC5 真的是"固定"吗** | 95/5 固定比例在剧烈行情下会漂移，是否有隐含的 drift | 从流水表核对实际权重路径 | P2 |

**注意**：P1/P2/P3 都**不应该**在 G20 的 G3（proxy/execution 配对）结论出来之前做——组合层的结论完全依赖袖套层的可执行净值是否可信。

### 6.4 麒麟 / A股赛道动量（`ashare_master`，当前 STOPPED）

`src/qount/api/adapters/ashare_master.py:81` 的裁决是"高收益结论撤销，研究封存"。**这条线的首要动作不是优化，是遵守封存。**

| 方向 | 说明 | 优先级 |
| --- | --- | --- |
| **K1. 确认封存纪律** | `docs/current.md` 已记录各变体"不能互相继承复核数字或准入资格"。**不要**因为界面上曲线好看而重启这条线。 | P0（纪律，非研究） |
| **K2. 失败原因归档** | 把这条线为什么失败（在哪一层的证据不足）写成一页，作为未来同类机制的对照 | P1 |
| **K3. 独立重认证（仅在 K1/K2 完成后考虑）** | 若未来重启，必须是新预登记、新门槛、独立样本，**不得复用**本线的数字 | P3 |

### 6.5 币安全球多资产（`binance_macro`，ARCHIVED）

裁决（`binance_macro.py:72`）："未通过准入，研究封存；修复逻辑后利润集中、成本与撮合仍需逐情景绑定收据，不继续历史调参救援。"

| 方向 | 说明 | 优先级 |
| --- | --- | --- |
| **B1. 利润集中度诊断** | 先回答"收益是否来自少数几笔"。这是被封存的**直接原因**，先量化 | P1 |
| **B2. 成本与撮合逐情景绑定** | 裁决原文要求的就是这个 | P1 |
| **B3. 不要做历史调参救援** | 裁决明确禁止。**任何以"调参让它变好"为形式的探索都违反封存结论。** | 禁止 |

### 6.6 个人量化交易助手（`personal_assistant`，ACTIVE_PAPER）

这是**唯一真正为个人服务、个人可执行**的线（`MA120_Band1.5pct` on `513100.SH`），也是 `CLAUDE.md` 定位里"低频、大周期、一年操作几次"最贴合的一条。指标：CAGR 12.05%、最大回撤 28.16%、Calmar 0.43、38 笔交易。

| 方向 | 假设 | 证伪判据 | 优先级 |
| --- | --- | ------- | --- |
| **A1. 参数稳健性** | `Band 1.5%` 这条带子是拟合出来的还是稳健的 | 在 1.0% / 1.5% / 2.0% 三档重跑，若结论方向翻转则该参数不可信 | **P0** |
| **A2. 标的集中度** | 单标的 `513100.SH` 是否有替代/互补载体 | 与 `000300.SH`、其他宽基对比同回撤下表现 | P1 |
| **A3. 回撤来源分解** | 28.16% 的最大回撤来自哪几段 | 用流水表定位；若集中在某一次假突破，考虑入场质量过滤 | P1 |
| **A4. 与其他线的相关性** | 这条线与 G20/C60 的相关性，决定它能不能作为独立袖套 | 计算净值相关系数；若 >0.8 则分散价值有限 | P2 |

**A1 排 P0 的理由**：这条线是整套系统里**最可能真的被个人执行**的一条（`CLAUDE.md` 的定位），而单一参数（1.5% 带子）承载了全部结论。参数稳健性是它唯一真正的风险点。

**第一步动作**：只改 `Band` 参数重跑，不动任何其他部分，看 Calmar 和回撤是否同向变化。注意：改参数前**先确认这条是预登记线还是不**——若已有预登记合同，改参数本身就是新预登记。

**A1 执行记录（2026-10-12）**：未找到旧稳健性预登记后，先冻结[新合同](../config/personal-assistant-band-robustness-20261012.json)，再用 513100.SH 同一完整样本（2013-05-15 至 2026-10-09，共 3,256 个交易日）运行 1.0% / 1.5% / 2.0%。252 日 CAGR 分别为 **11.9423% / 12.0498% / 12.0435%**，最大回撤均为 **28.1630%**，Calmar 分别为 **0.4240 / 0.4279 / 0.4276**。内核 `trade_count` 为 **42 / 38 / 32**，包含各档共同的一次拆分事件；BUY/SELL 成交数分别为 21/20、19/18、16/15。预登记的三项方向（高于现金 CAGR、相对买持 CAGR 的方向、回撤是否低于买持）在三档完全一致；因此这项检查未发现结论对 1.0%–2.0% 带宽敏感。CAGR 仍低于同窗买持的 21.2821%，此结果不支持策略优于买持，也不是独立样本外或晋级证据。既有 1.5% 摘要由不同源码哈希生成，但数据哈希相同，当前重跑的 CAGR、回撤、Calmar 与事件数均与旧摘要相同；完整差异与逐日曲线在本机 `state/research_runs/personal_assistant_band_robustness_20261012/`。

**A3 描述诊断（2026-10-12）**：同一条 1.5% 全历史净值的最大回撤从 **2020-02-13** 峰值 2,458,371 降至 **2020-03-16** 谷值 1,766,021（-28.163%）；持仓于 2019-03-14 建立，峰至谷之间没有任何成交，2020-03-18 才卖出，并于 2020-08-25 收复峰值。该段更符合持仓期间的市场急跌与确认/次日成交时钟暴露，不是一次入场后立即失败的单笔假突破；当前证据不支持据此增加入场过滤。此为已消费全样本的路径归因描述，不是新过滤器的效果检验。

### 6.7 跨线共性方向（所有线都适用）

| 方向 | 说明 | 优先级 |
| --- | --- | --- |
| **X1. 统一信号/可执行两层口径** | 四条 dual 线都有 signal/executable 两层，前端目前展示得不够显眼。design §2.2 要求"并排显示收益与回撤，并把差异一并展示"。**先把展示做好，再谈优化。** | P0 |
| **X2. 回撤与收益强制并排** | 任何界面位置出现收益数字时，同屏必须有回撤。防止"看起来好"的单一数字误导决策 | P0 |
| **X3. 前瞻 vs 回放的显式标注** | 除 CTA-R 外全是回放。要在每行上标出来，避免把回放当 forward | P1 |
| **X4. 失败线的可见性** | STOPPED / ARCHIVED / MISSING 必须与"正常"视觉上可分。design §2.1 已立此规矩 | P1 |

---

## 7. 执行顺序总表

| 顺序 | 阶段 | 预计 | 阻塞关系 |
| ---: | --- | --- | --- |
| 1 | §1 止血（三条线 + `/account`） | 半天 | 阻塞 §5 |
| 2 | §2 Tiingo 配额治理 | 一天 | 独立，但**今天就在烧**，建议与 §1 并行 |
| 3 | §3.4 本地库隔离 | 10 分钟 | 阻塞所有本地验证 |
| 4 | §3.1–3.3 新鲜度/基准/生命周期 | 半天 | 独立 |
| 5 | §4 持仓流水表 | 一到两天 | 阻塞 §6 全部 |
| 6 | §5 其余线接入（CTA-R 优先） | 一条线半天 | 依赖 §1 |
| 7 | §6 各线机制探索 | 每条线独立预登记 | 依赖 §4 |

**建议先做的两件事**：§2.3.1（L1 passive 加缓存）和 §3.4（本地换库）。前者止血最快、收益最大；后者防止后续所有验证都建立在陈旧数据上。

---

## 8. 待确认事项（需要 owner 决策）

1. **`config/api.json` 是否创建**（§3.1）：design §7 承诺过，从未落地。集中阈值 vs 保持散落，需要 owner 定。
2. **Tiingo 方案 A 还是 B**（§2.3.2）：A 改动小、隔离弱；B 隔离强、要动 systemd。
3. **停 publisher 之前 ingest 由谁触发**（§3.4）：目前没有任何 ingest timer。停掉 publisher 后页面不会自己更新。
4. **G20 的 G3 是否立即启动**（§6.1）：这是唯一可能改变"收益 vs 可执行"结论的方向，但是否值得在观察期内动，需 owner 判断。
5. **个人助手的 Band 参数是否已有预登记**（§6.6）：决定 A1 是"稳健性检验"还是"新预登记"。

### 8.1 已确认的 owner 决策（2026-10-12）

1. Tiingo 采用方案 A：保留 15 分钟 forward timer，在 EOD source 内做每日缓存去重。
2. 创建 `config/api.json` 集中新鲜度阈值。
3. 保持 dashboard publisher 与现有页面摄取安排运行；本轮不改 ingest 调度。
4. §4 后立即开始 G20 G3 只读 proxy/execution 配对核查。已完成本地初查；完整 291 点结论待本地可核验快照与成对行情。
5. 先查预登记文档：未找到 `MA120_Band1.5pct` 专属稳健性预登记，已先冻结独立合同后运行 A1。1.0% / 1.5% / 2.0% 三档均为同一方向：CAGR 高于现金但低于买持，回撤低于买持；全历史描述性检查未发现带宽结论翻转。结果不构成独立样本外或晋级证据，见 §6.6 与本机运行包。
