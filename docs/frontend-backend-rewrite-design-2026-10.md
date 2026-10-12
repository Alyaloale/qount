# 前后端重写设计（2026-10）

> **状态**：P0–P4 已实施（25 项 API 专项测试、全仓 3,527 项通过、Hygiene 通过）；**P4.5 已完成**——`dual_engine` 适配器的硬编码假数据已移除并改为读真实快照。四账户已拆分注册。待办：持仓流水表、真实 Binance 账户、其余研究线接入、VPS 部署｜**权威**：本文记录重写设计与实施事实，当前事实仍看 [current.md](current.md)｜**最后更新**：2026-10-12
> **TL;DR**：前端＝真实 Binance 账户＋模拟盘探索；后端＝binance 行情＋模拟盘。当前 4 条线要扩到覆盖 G20/C60/GC5/D15 四账户与其余研究方向。`dual_engine` 适配器目前输出**编造曲线**，是本次首要修复项。
> **边界**：`/account` 只读，不实现任何下单／撤单／改单；读私有账户需 owner 明确授权只读密钥；默认 `research_only=true / orders_authorized=false`。

---

## 1. 现状与目标差距

### 1.1 已交付（P0–P4）

`src/qount/api/`（14 个模块）、`web/app/`（双屏前端）、`config/paper-lines.json`（4 条线）、`tests/api/`（22 项）。旧合同层与原工件原位保留，可回退。

### 1.2 本轮 owner 提出的新要求

| # | 要求 | 现状 | 差距 |
| --- | --- | --- | --- |
| 1 | 前端显示**真实 Binance 账户** | `/account` 读的是本地调和包（`personal_assistant_reconciled_20261012`），显示 ¥4,349,345.74 | 需接交易所只读 API 取真实余额／持仓 |
| 2 | 模拟盘覆盖 **G20／C60／GC5／D15** 四账户 | 注册表只有 1 条 `dual_g20`，且是假数据 | 需拆成 4 条线并接真实快照 |
| 3 | 保留**年化约 15%** 那条表现好的线 | 未接入 | 见 2.2 节定位结论 |
| 4 | **其他方向策略**也放进模拟盘 | 已接 3 条研究线（助手／币安／麒麟） | 需扩展到 S3-B 索引的全部线路 |
| 5 | **记录持仓**，方便后续分析 | `positions` 字段存在但只有当前快照 | 需加历史持仓／调仓流水表 |
| 6 | 部署到 **VPS 替换原有程序** | 本地跑 | 需 systemd + Caddy + 数据同步 |

### 1.3 关于账户命名的澄清

owner 提到 "g20 c20 g60 c60"。经全库检索（`C20`／`G60` 在 `src/` 下**零命中**）：

- 实际存在的是 **G20、C60、GC5、D15** 四个独立账户，各 10,000 USD_EQ 起始（`src/qount/dual_engine/contracts.py:796-798`）。
- **`C20` 与 `G60` 不存在**。推测是 "G20/C60" 的口误或记混。**不新建这两个账户**——按 `docs/qount_strategy_master_index.md` 的冻结合同，账户集合本身是冻结口径，新增账户需独立设计而非改名。

## 2. 首要修复项（P4.5）

### 2.1 `dual_engine` 适配器输出编造数据 ✅ 已修复

**这是修复前最严重的问题，且直接违反项目底线。**

`src/qount/api/adapters/dual_engine.py` 原先的净值曲线与指标是**硬编码的字面量**：10 个手写 NAV 点、写死的 `ytd_return_pct=12.3` / `max_drawdown_pct=8.1`、以及一个固定的 `SPY 100%` 持仓。真实数据只在 VPS 的 `<state_root>/current/paper_program_snapshot.json`。适配器找不到文件时**不报错、不标记 MISSING，而是静默返回假数据**——界面上 "G20 +12.3% / -8.1% / 持仓 SPY 100%" 与真实截图（+15.26% / 持仓 BIL 77.81% + ERX 21.40%）完全不符。

已完成的修复：

1. **删除全部字面量默认值**。改为解析真实快照的 `portfolios[].nav.points[]`、`benchmarks[].nav.points[]`、`holdings[]`。
2. **无源即拒绝给数字**。新增三个失败分支，均返回 `status=MISSING`、`freshness=MISSING`、`nav_series=[]`、`metrics=None`、并带 `error` 说明：`SNAPSHOT_NOT_FOUND`、`SNAPSHOT_UNREADABLE`、`PORTFOLIO_ABSENT`、`NAV_SERIES_EMPTY`、`UNKNOWN_ACCOUNT`。
3. **契约层加约束**：`PaperLine.metrics` 与 `PaperLineSummary.metrics` 改为 `Optional`，并新增 `error: Optional[str]`。没有源就没有业绩数字，类型上无法表达"0.0 的假收益"。
4. **测试改为对 fixture 断言**：新增 `tests/api/fixtures/dual_engine/current/paper_program_snapshot.json`（镜像真实快照形状），测试断言解析结果来自快照而非常量；并新增**反例测试** `test_dual_engine_missing_snapshot_reports_no_figures`，强制"无源不得返回业绩数字"。
5. **前端显式渲染不可用态**：新增 `status-missing` 徽章（`✕ 无数据源`）与 `data-unavailable` 文案，与"停止/失败"区分——后者是策略问题，前者只是没数据。
6. **`C20`/`G60` 显式拒绝**：`UNKNOWN_ACCOUNT` 分支保证不存在的账户名不会被静默映射到某个真实账户。

> **保留此项作为记录**：这是"适配层静默兜底"的典型失败模式——回退到默认值看似健壮，实际是在展示层伪造业绩。任何新增适配器都必须通过对应的反例测试。

### 2.2 "年化约 15%" 那条线的定位

owner 记忆中"最近年化达到 15%、表现挺好"的线，经比对现有数据最可能指向：

- **G20（美股轮动）**：截图显示**年初至今 +15.26%**，当前模拟资产 11,525.73（起始 10,000）。
- 但**必须同时读出回撤**：同期最大回撤 -16.33%，8 月以来 -3.77%。master index 的 2026-09-22 复盘显示 G20 YTD +13.49%、回撤 -16.33%。

**结论**：这不是"年化 15% 的好策略"，而是**约 8 个月、含部署期历史回放、期间最大回撤 16% 的模拟结果**。YTD 收益不能年化外推，且 `qount_strategy_master_index.md` 明确写着"YTD 含部署时回放，不能称为九个月真实 forward"。

界面上这条线必须**并排显示收益与回撤**，并把差异（信号净值 vs 可执行净值）一并展示——C60 两层净值差 6.90 个百分点，这正是"看起来好"与"真能拿到"的差距。

## 3. 目标架构（增量）

```
┌────────────────────────────────────────────────────────────┐
│ 前端 web/app/  (原生 JS + ECharts)                          │
│  屏一 账户    │ 屏二 模拟盘探索 │ 屏三 持仓流水(新增)          │
└───────────────┬────────────────────────────────────────────┘
                │ HTTP JSON
┌───────────────▼────────────────────────────────────────────┐
│ API src/qount/api/  (FastAPI, 只读)                         │
│  /account  /paper/lines  /paper/lines/{id}                  │
│  /paper/positions (新增)  /market/klines  /health           │
└───────────────┬────────────────────────────────────────────┘
                │
        ┌───────┴────────┐
        │                │
┌───────▼──────────┐ ┌───▼──────────────────────────────────┐
│ 模拟盘适配层      │ │ 账户源（新增，两选一）                  │
│ adapters/*.py    │ │  A. 本地快照（默认，离线可用）           │
│ 每条线一个        │ │  B. Binance 只读 API（需授权）          │
└───────┬──────────┘ └───┬──────────────────────────────────┘
        │                │
┌───────▼────────────────▼──────────────────────────────────┐
│ state/qount.db (SQLite)                                    │
│  paper_lines │ paper_nav │ paper_positions(新增) │ ingest_log│
└────────────────────────────────────────────────────────────┘
```

## 4. 真实 Binance 账户（新增能力）

### 4.1 授权前提

读私有账户需要 API 密钥，这属于"访问真实账户"，因此：

- **只读密钥**：API key 必须**仅勾选读取权限**，禁用现货／合约交易、禁用提现。这是硬要求，不是建议。
- **owner 明确授权后才接线**。默认实现走 4.3 的 A 方案（本地快照），B 方案（交易所直连）代码可先写但**默认关闭**，需 `QOUNT_ACCOUNT_SOURCE=binance` 显式开启。
- 密钥存储：沿用现有约定，本地 `0600`，**绝不打印、不提交、不导出**。新增环境变量只登记键名，值不入库、不入日志。

### 4.2 接口与字段

```jsonc
// GET /account
{
  "as_of": "2026-10-12T09:00:00Z",
  "mode": "LIVE_READONLY",        // PAPER | LIVE_READONLY
  "source_kind": "binance_api",   // local_snapshot | binance_api
  "balances": [                    // 账户余额
    {"asset": "USDT", "free": 1234.56, "locked": 0.0}
  ],
  "positions": [                   // 持仓（合约或现货折算）
    {"symbol": "BTCUSDT", "quantity": 0.5, "entry_price": 60000.0,
     "mark_price": 62000.0, "unrealized_pnl": 1000.0, "weight": 1.0}
  ],
  "nav_usdt": 50000.0,
  "read_only": true,
  "orders_authorized": false,
  "source": {"endpoint": "/api/v3/account", "fetched_at": "…"}
}
```

**只读保证**：`read_only` 与 `orders_authorized` 是**两个独立字段**，前者描述密钥权限，后者描述系统授权。两者都必须在界面常驻显示，避免"只读密钥"被误读为"系统不会下单"。

### 4.3 数据源两方案

| 方案 | 数据来源 | 优点 | 缺点 |
| --- | --- | --- | --- |
| **A. 本地快照（默认）** | 定时任务把交易所读数落 JSON，API 读文件 | 离线可看、无密钥暴露在 web 进程、无网络抖动 | 快照有延迟，需一个采集任务 |
| **B. 直连交易所** | API 进程直接调 Binance | 实时 | 密钥进入 web 进程上下文；网络失败影响首屏 |

**推荐 A 起步**：web 进程永远不持有密钥，采集任务单独跑、写入 `state/account/snapshot.json`，`/account` 只读文件。这与现有"VPS 拥有 runtime truth"的分工一致。

### 4.4 失败必须显式

密钥缺失、权限不足、IP 未白名单、网络失败——一律返回明确状态，**绝不回退到本地 PAPER 数值冒充 LIVE**：

```jsonc
{"mode": "LIVE_READONLY", "source_kind": "binance_api",
 "error": "AUTH_FAILED", "detail": "API key lacks read permission",
 "balances": [], "positions": [], "nav_usdt": null}
```

## 5. 模拟盘：四账户与其余研究线

### 5.1 四账户拆成 4 条线

注册表把单条 `dual_g20` 换成四行（`config.account` 决定读哪个账户）：

```jsonc
{"id": "dual_g20", "adapter": "dual_engine", "name": "美股轮动 (G20)",
 "category": "equity", "enabled": true, "config": {"account": "g20"}},
{"id": "dual_c60", "adapter": "dual_engine", "name": "加密趋势 (C60)",
 "category": "crypto", "enabled": true, "config": {"account": "c60"}},
{"id": "dual_gc5", "adapter": "dual_engine", "name": "固定组合 (GC5)",
 "category": "mixed",  "enabled": true, "config": {"account": "gc5"}},
{"id": "dual_d15", "adapter": "dual_engine", "name": "动态组合 (D15)",
 "category": "mixed",  "enabled": true, "config": {"account": "d15"}}
```

一个适配器处理四个账户（差异只在 `config.account`），符合"适配层是唯一理解差异的地方"。

### 5.2 其余研究方向接入

把 S3-B 索引的线路作为注册表候选，**逐条接入、逐条验证**，不追求一次全上：

| 线路 | 适配器 | 产物位置 | 预计状态 |
| --- | --- | --- | --- |
| C60 v1/v2、PIT、梯度 | `c60` | `state/research_runs/*c60*` | ARCHIVED（选币优势撤回） |
| CTA-R 侧车 | `cta_r` | `state/cta_r/` | ACTIVE_PAPER（前瞻账本） |
| Q-DIV-Core | `q_div` | `state/research_runs/ashare_q_div_core_20261011` | STOPPED（门槛失败） |
| ETF Trader P2/P3 | `etf_alpha` | `state/research_runs/etf_alpha_*` | STOPPED |
| 麒麟／赛道轮动 | `ashare_master` ✅已接 | `state/research_runs/ashare_sector_momentum_20261011` | STOPPED |
| 币安全球多资产 | `binance_macro` ✅已接 | `state/research_runs/binance_global_macro_20261011` | ARCHIVED |
| 个人助手 | `personal_assistant` ✅已接 | `state/research_runs/personal_assistant_reconciled_20261012` | ACTIVE_PAPER |

**接入顺序建议**：先修 `dual_engine`（假数据）→ 拆四账户 → 接 CTA-R（唯一有真实前瞻账本的线）→ 其余按需。

### 5.3 持仓记录（新增）

要求"记录持仓记录，方便后续分析"。当前只有当前快照的 `positions`，无法回答"什么时候换的仓、换了什么"。

新增两张表 + 一个端点：

```sql
CREATE TABLE paper_positions (
  line_id TEXT, date TEXT, symbol TEXT,
  quantity REAL, weight REAL, price REAL, market_value REAL,
  action TEXT,              -- OPEN | CLOSE | ADJUST | HOLD
  PRIMARY KEY (line_id, date, symbol)
);
CREATE TABLE paper_trades (   -- 调仓流水
  line_id TEXT, date TEXT, symbol TEXT,
  side TEXT,                -- BUY | SELL
  quantity REAL, price REAL, cost REAL, note TEXT,
  PRIMARY KEY (line_id, date, symbol, side)
);
```

```
GET /paper/positions?line_id=dual_g20&start=2026-01-01&end=2026-10-12
GET /paper/trades?line_id=dual_g20&limit=100
```

前端屏三展示：当前持仓 + 调仓时间线。**口径必须标注**：这些是**模拟调仓**（`simulated_not_realized`），不是真实成交；成本按该线合同声明的费率（如 C60 基础 25 bps／压力 50 bps）。

## 6. VPS 部署（替换原有程序）

完整的逐步执行手册见 **[新前端部署执行手册](vps-deployment-runbook-2026-10.md)**（含全部命令、预期输出、失败判据与回退）。本节只记录设计取舍。

### 6.1 现状（2026-10-12 实测）

VPS `/root/qount`（**非 git 仓库**，靠 `scripts/sync-to-vps.sh` rsync）已运行 15 个 qount 单元 + Caddy 站点 `qount.alyaloale.com`（根 `/var/www/qount`，basic_auth 保护）。旧前端读 `/var/www/qount/data/v1 -> releases/<publication_id>`。主机 2 核 / 1.6 GB 内存。

### 6.2 部署阶段

| 阶段 | 动作 | 回退 |
| --- | --- | --- |
| V1 | 提交代码（rsync 要求工作区干净）+ 备份 VPS | tar 包还原 |
| V2 | `sync-to-vps.sh --dry-run` 再实际同步（**首次不加 `--delete`**） | tar 包还原 |
| V3 | 装 `fastapi` + `uvicorn` | `pip uninstall` |
| V4 | 手动跑端口 8001，逐项验证 7 个端点 | `Ctrl-C` |
| V5 | 装 `qount-api.service`（见下） | `systemctl disable` |
| **V6** | **Caddy 改反代（真正的切换点）** | **改回一行即恢复** |
| V7 | 并行观察 3–5 日，再 `stop` 旧 publisher | `systemctl start` |

### 6.3 三个关键设计取舍

**1. 用 `reverse_proxy` 而非静态目录覆盖。** Caddy 里只需把 `file_server` 换成 `reverse_proxy 127.0.0.1:8000`，`basic_auth` 与 `header` 块原样保留。这样回退只是把那一行改回去——**切换与回退都在 1 秒内、不断开现有连接**。若改为把新前端文件覆盖到 `/var/www/qount`，回退就要恢复整目录，风险大得多。

**2. systemd 里 `UnsetEnvironment` 显式剔除交易所密钥。** API 只需读快照文件，**不需要也不应持有 `QOUNT_BINANCE_API_KEY`／`SECRET`**。这是"web 进程永不持有密钥"的机制保障，而非口头约定。

**3. `qount-dashboard-account-observer` 必须继续运行。** 它的"写旧 release"职责被取代，但它的"读真实交易所账户"职责**正是 `/account/live` 的数据来源**（每 5 分钟写 `/var/lib/qount/blocked_runtime_observation.json`）。停掉它，真实账户读数就没了。

### 6.4 两处不可忽视的环境约束

- **`WorkingDirectory=/root/qount` 是必需的**：`main.py` 用 `os.path.abspath("web/app")`，静态挂载依赖工作目录。
- **`QOUNT_DB_PATH` 必须指向可写目录**（如 `/var/lib/qount/api/qount.db`）：`ProtectSystem=strict` 下 `/root` 只读，写库会失败。

### 6.5 部署一致性检查

手册阶段 7 给出 9 项验收清单（服务状态、健康、四账户真实数据、G1 数值、真实账户、域名可访问、basic_auth 生效、内存占用、无重启循环）。**避免"以为部署成功但跑的仍是旧代码"。**



## 7. 为便于修改而做的结构调整

owner 要求"方便修改提高"，因此：

1. **注册表是一切的开关**。加线＝加一行 JSON；下线＝`enabled: false`；改数据源＝改 `config`。**不需要动 Python。**
2. **每个适配器一个文件**，函数签名统一为 `adapt(line_id, name, config) -> PaperLine`。新线照抄现有文件改解析逻辑即可。
3. **`schemas.py` 是唯一契约**。前端字段名只依赖它；改字段只改一处。
4. **前端 `app.js` 按屏分函数**（`renderAccount()` / `renderPaperList()` / `renderDetail()` / `renderPositions()`），新增屏只加函数与一个导航项。
5. **阈值集中在 `config/api.json`**（新增）：`freshness_stale_days`、`nav_history_limit`、`default_category_order`。避免散落在代码里的魔数。

## 8. 测试与验收

| 层 | 测试 | 关键断言 |
| --- | --- | --- |
| 适配器 | `tests/api/test_adapters.py` | 每条线对真实 fixture 解析正确；**源缺失时返回 MISSING 而非默认值** |
| 契约 | `tests/api/test_schemas.py` | 缺字段、空曲线、非法日期被拒 |
| API | `tests/api/test_api.py` | 端点形状、404、账户失败态 |
| 底线 | `tests/research/test_engine_rigorous_invariants.py` | 10 项不变性继续全过（防未来函数、真实费率、时钟因果） |
| 部署 | `scripts/operations/verify_deploy.sh` | 线上线数／`as_of`／`line_id` 集合与预期一致 |

**新增的强制验收项**：`test_adapters.py` 必须包含一条 **"无源数据不得返回业绩数字"** 的反例测试。这是防止 2.1 节问题复发的机制性保障。

## 9. 硬边界

- `/account` 只读；**不实现任何下单、撤单、改单路径**，不接交易 API 的写端点。
- 读私有账户需 owner 明确授权，密钥**只读权限**，本地 `0600`，绝不入库、入日志、入版本控制。
- 交易所失败时不回退到本地数值冒充 LIVE——**如实报错**。
- 模拟盘数据必须可溯源到 `source.path` + `sha256`；**不可溯源的条目不展示**。
- 所有模拟盘条目常驻免责声明："各研究线历史回放与无订单前向模拟结果，不是实盘账户收益"。
- 收益与回撤**必须并排显示**，且 `Signal NAV` 与 `Executable NAV` 差异一并展示。
- 不新建 `C20`／`G60` 账户（不存在，见 1.3 节）。

## 10. 未决项

1. **Binance 只读密钥**：owner 是否已创建、是否已加 IP 白名单？未确认前 B 方案不启用。
2. **四账户快照的跨机取材**：本地无 `paper_program_snapshot.json`。需从 VPS 取样本作 fixture，或让 VPS 上的采集任务把汇总 JSON 同步一份到可读位置。
3. **VPS 上 API 与旧 dashboard 的并行期**：建议至少并行 3–5 日再停旧单元。
4. **`/account` 的 LIVE 与 PAPER 如何共存**：建议顶部加模式切换，默认显示 LIVE（若可用），失败时明确提示而非静默切 PAPER。

## 11. 建议执行顺序

```
P4.5  修 dual_engine 假数据（删字面量 + MISSING 分支 + fixture 测试）   ✅ 已完成
P4.6  拆四账户注册表行（G20/C60/GC5/D15）                            ✅ 已完成
P4.7  加 paper_positions / paper_trades 表与两个端点                  ← 下一步
P5-A  账户：/account/live 接真实只读账户                             ✅ 已完成
P5-B  接入 CTA-R，再逐条接入其余研究线
P5-C  VPS 部署                        → 见 [执行手册](vps-deployment-runbook-2026-10.md)
P6    确认无引用后清理旧单元与 schemas
```

**已完成部分的验证（2026-10-12）**：

- API 专项 28 项、全仓 3,530 项通过（34 跳过）、`compileall` 与 `repository_hygiene.py check` 通过。
- **四账户已用 VPS 真实快照验证**（291 点/账户）：G20 YTD +15.26%／MaxDD -16.33%／持仓 BIL 77.81%+ERX 21.40%，与线上界面截图完全吻合。
- 真实账户端点读 VPS 现成的 `blocked_runtime_observation.json`，实测 **0.36 USDT**、无持仓。
- 修正了一处**纯本地测试无法发现**的字段名陷阱（快照用 `executable`/`signal`，非 `executable_nav`/`signal_nav`），并加回归测试锁住。

research_only=true / orders_authorized=false / promotion_evidence=false。
