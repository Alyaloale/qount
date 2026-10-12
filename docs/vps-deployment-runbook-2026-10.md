# 新前端部署执行手册（qount.alyaloale.com）

> **状态**：待执行｜**执行者**：owner 逐步执行｜**最后更新**：2026-10-12
> **目标**：把新的只读 API + 双屏前端部署到既有域名 `https://qount.alyaloale.com/`，替换现有旧 dashboard。
> **本文性质**：**纯操作手册**。每一步都给出可直接复制的命令、预期输出、失败判据与回退方式。
> **默认边界**：`research_only=true / orders_authorized=false`。全程不涉及下单、不修改交易授权。

---

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
{"status":"ok","db_connected":true,"last_ingest_at":"...","paper_lines_count":7,
 "safety":{"research_only":true,"orders_authorized":false}}
```

**失败判据**：`paper_lines_count` 不是 7 → 注册表未正确加载，检查 `config/paper-lines.json` 是否同步。

#### 验证 B：四账户读到真实快照（**最关键**）

```bash
ssh qount-vps 'curl -s localhost:8001/paper/lines | python3 -m json.tool'
```

**预期**：7 条线。四条 `dual_*` 应为：

| line_id | status | freshness |
| --- | --- | --- |
| `dual_g20` | `ACTIVE_PAPER` | `FRESH` 或 `STALE` |
| `dual_c60` | `ACTIVE_PAPER` | 同上 |
| `dual_gc5` | `ACTIVE_PAPER` | 同上 |
| `dual_d15` | `ACTIVE_PAPER` | 同上 |

且 `error` 为空（FastAPI 可序列化为 `null`）。

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

**预期**：4 个 adapter（`dual_engine`、`personal_assistant`、`binance_macro`、`ashare_master`），7 条线全部 `registered: True`。

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
ssh qount-vps 'systemctl reload caddy && systemctl is-active caddy'
```

**预期**：`active`。

> `reload` 是热加载，**不断开现有连接**，切换在 1 秒内完成。

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
ssh qount-vps 'cp /etc/caddy/Caddyfile.bak-<时间戳> /etc/caddy/Caddyfile && systemctl reload caddy'
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
| Tiingo 429（paper-daily 失败） | 外部限流，非本地问题 | `systemctl start qount-dual-engine-paper-daily` |

## 附录 B：回退总表

| 阶段 | 回退命令 |
| --- | --- |
| 2 | `ssh qount-vps 'cd /root && tar xzf qount-backup-<时间戳>.tar.gz'` |
| 3 | `ssh qount-vps 'cd /root/qount && ./.venv/bin/pip uninstall -y fastapi uvicorn starlette'` |
| 5 | `ssh qount-vps 'systemctl disable --now qount-api && rm /etc/systemd/system/qount-api.service && systemctl daemon-reload'` |
| **6** | `ssh qount-vps 'cp /etc/caddy/Caddyfile.bak-<时间戳> /etc/caddy/Caddyfile && systemctl reload caddy'` |
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
[ ] 阶段 1  提交代码，git status 干净
[ ] 阶段 2  备份 VPS → dry-run → 同步 → 验证文件在
[ ] 阶段 3  装 fastapi/uvicorn → 验证可导入
[ ] 阶段 4  手动跑 8001 → 逐项验证 A-G 全通过 → Ctrl-C
[ ] 阶段 5  写单元 → mkdir /var/lib/qount/api → enable --now → 验证
[ ] 阶段 6  备份 Caddyfile → 改写 → caddy validate → reload → 域名验证
[ ] 阶段 7  验收清单 9 项 → 观察 3-5 日 → stop publisher（保留 observer）
[ ] 阶段 8  可选：行情接口
```

research_only=true / orders_authorized=false / promotion_evidence=false。
