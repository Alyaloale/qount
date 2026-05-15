# qount 生产故障段与恢复记录（2026-05-13）

这份文档记录 `2026-05-13` 这次 `qount` 生产故障段的真实时间线、根因拆解、修复动作和最终验证结果，目标是下次不要再从“是不是 Binance 又抽风了”开始猜。

补充说明：

- 如果你关心的是这次修复之后“当前 live 策略是什么、收益相关调参做了哪些、这些改动是否有效”，优先去看：
  - [docs/live-strategy-and-tuning-2026-05-13.md](live-strategy-and-tuning-2026-05-13.md)

## 2026-05-14 当前基线

这份文档前半部分保留 `2026-05-13` 那次故障与恢复的历史过程；但下次如果只是要快速判断“是不是 IP 又变了、当前应该加哪个白名单、现在默认该跑哪组命令”，先看这一节，不要直接复用文档里较早的历史 IP。

当前默认基线是：

- Binance 白名单当前实测出口 IP：`18.163.116.238`
- 当前固定专线叶子：`🇯🇵日本高速03|BGP|流媒体`
- Windows 专线任务：`QountBinanceProxy`
- WSL 默认 Binance 专线：`http://192.168.128.1:7907`

`2026-05-14 15:30 CST` 现场复核结果：

- Windows `status -Probe`
  - `running=true`
  - `listening=true`
  - `ruleTarget=🇯🇵日本高速03|BGP|流媒体`
  - `ip=18.163.116.238`
- `preflight-live` 全绿
  - `credentials.ok=true`
  - `position_mode.ok=true`
  - `balance_guard.ok=true`
  - `live_guard.ok=true`
- 手动 `run-once`
  - `run_id=1219`
  - `status=completed`
  - `symbol=SOL/USDT:USDT`
  - `action=hold`
  - `order_status=noop`
- 自动 timer 恢复后新样本
  - `run_id=1221`
  - `run_id=1222`
  - `run_id=1223`
  - 都是 `completed`

这里要明确两件事：

- 文档后面出现的 `95.40.7.69` 和 `🇯🇵日本高速01|BGP|流媒体`，是 `2026-05-13` 那次恢复完成时的历史值，不是当前白名单基线。
- 共享出口 `7898` 当前不应当作为默认修复路径。`2026-05-14` 现场验证里，这条路由会碰到 `418/-1003`，所以只适合作对照，不适合作默认 live Binance 出口。

## 2026-05-14 之后默认恢复检查命令

下次如果你只想最快回答三件事：

1. 现在专线是不是活着
2. 当前真实出口 IP 是多少
3. Binance 私有接口是不是已经跟白名单重新对上

直接按下面顺序跑。

### 1. 先查 Windows 专线状态和当前出口 IP

```bash
ssh home "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\15470\Code\relay-station\scripts\windows\Start-QountBinanceProxy.ps1 status -CandidateProxyName \"🇯🇵日本高速03|BGP|流媒体\" -Probe"
```

这里重点看：

- `running`
- `listening`
- `ruleTarget`
- `ip`
- `binanceTime`

如果这里的 `ip` 变了，就先把新 IP 补进 Binance 白名单，再继续看后面的 `preflight-live`。

### 2. 再查 WSL 通过 `7907` 的实际出口和 Binance 公有接口

```bash
ssh home "wsl.exe bash -lc 'echo ---IPIFY---; curl -sS --max-time 15 --proxy http://192.168.128.1:7907 https://api.ipify.org; echo; echo ---BINANCE_TIME---; curl -sS --max-time 15 --proxy http://192.168.128.1:7907 https://fapi.binance.com/fapi/v1/time; echo'"
```

这一步用来证明：

- `WSL -> 192.168.128.1:7907` 这条桥没断
- 实际出口 IP 和 Windows `status -Probe` 一致
- Binance 公有接口已经能通

### 3. 再查 `qount` 自己的 live preflight

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main preflight-live | python3 -m json.tool'"
```

重点看：

- `credentials.ok`
- `position_mode.ok`
- `balance_guard.ok`
- `live_guard.ok`

如果：

- `public_api.ok=true`
- 但 `credentials.ok=false` 且报 `-2015`

那就不要再猜策略，直接按“当前出口 IP 没进白名单，或者 API 权限没对上”处理。

### 4. 最后用一次真实 `run-once` 收尾

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main run-once | python3 -m json.tool'"
```

这一步仍然是最终证据，因为：

- `status -Probe` 只能证明 Windows 专线活着
- `curl --proxy` 只能证明 public 路由通
- `preflight-live` 只能证明 live guard 放行
- 真正 private API 和 live 执行链路是否恢复，还是要看一次真实 `run-once`

### 5. 如果还要补自动链路，再看 timer 和最新 runs

```bash
ssh home "wsl.exe bash -lc 'systemctl --user status qount-runner.timer --no-pager --full | sed -n \"1,40p\"'"
```

```bash
cat <<'PY' | ssh home 'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && python3 -"'
import sqlite3, json
con = sqlite3.connect('state/qount.db')
con.row_factory = sqlite3.Row
rows = con.execute("""
select id, started_at, finished_at, status, summary_json
from runs
where mode='live'
order by id desc
limit 12
""").fetchall()
out = []
for r in rows:
    s = json.loads(r["summary_json"] or "{}")
    out.append({
        "run_id": r["id"],
        "started_at": r["started_at"],
        "finished_at": r["finished_at"],
        "status": r["status"],
        "symbol": s.get("symbol"),
        "action": s.get("action"),
        "order_status": s.get("order_status"),
        "error": s.get("error"),
    })
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
```

如果这里已经重新出现新的 `completed` live runs，就说明自动定时链路也已经恢复，不只是手动 probe 成功。

## 适用范围

- 生产真相仍然以 WSL 节点为准：`/home/alyaloale/Code/qount/state/qount.db`
- Windows 侧专用 Binance 代理入口：
  - 脚本：`C:\Users\15470\Code\relay-station\scripts\windows\Start-QountBinanceProxy.ps1`
  - 工作目录：`C:\ProgramData\qount-binance-proxy`
  - WSL 访问地址：`http://192.168.128.1:7907`
- 本次所有结论都来自现场命令，不是只看仓库配置推断

## 先说结论

这次故障不是 timer 停了，也不是策略突然不交易了，而是两层问题叠在一起：

1. `QountBinanceProxy` 没有稳定常驻，导致 `WSL -> 192.168.128.1:7907` 这条 Binance 专线直接断掉。
2. 专线恢复后，Binance 私有接口还会单独受当前出口 IP 白名单约束；只有把当时实际出口 IP 加进白名单，`preflight-live` 和真实 `run-once` 才会恢复。

这次已经做掉的事情：

- 把 `QountBinanceProxy` 改成 watchdog 常驻任务，不再因为一次子进程退出就整条专线失效。
- 把 dedicated 配置从“匹配 group 名 `良心云`”改成“固定到当前实际选中的叶子节点”，避免每次重启都重新漂出口。
- 重新安装并验证 Windows 计划任务。
- 在 Binance 白名单补进当前真实出口 IP 后，重新验证 `preflight-live` 和真实 `run-once`。

## 故障时间线

### 1. 故障开始点

生产库里最后一条成功 completed live run 是：

- `run_id=760`
- `started_at=2026-05-12T16:45:00.746853+00:00`
- 北京时间约 `2026-05-13 00:45 CST`
- 结果：`symbol=XRP/USDT:USDT`、`action=hold`、`order_status=noop`

紧接着第一条失败 run 是：

- `run_id=761`
- `started_at=2026-05-12T16:50:00.833701+00:00`
- 北京时间约 `2026-05-13 00:50 CST`
- 结果：`status=market_data_failed`
- 错误：`binance GET https://fapi.binance.com/fapi/v1/exchangeInfo`

也就是说，这一段故障的真正起点不是 5 月 13 日中午，而是 `2026-05-13 00:50 CST`。

### 2. 中午现场状态

在 `2026-05-13 12:45 CST` 左右现场检查时：

- `qount-runner.timer` 仍然是正常 `active (waiting)`
- 最近 run 仍按 5 分钟触发
- 但最近连续失败都统一落在：
  - `status=market_data_failed`
  - `error=binance GET https://fapi.binance.com/fapi/v1/exchangeInfo`

这一步非常关键：`timer 正常` 不等于 `live 交易链路正常`。

### 3. 首次断点定位

当时从 WSL 直接测：

```bash
curl -sS --max-time 12 http://192.168.128.1:7907
curl -sS --max-time 12 --proxy http://192.168.128.1:7907 https://api.ipify.org
curl -sS --max-time 12 --proxy http://192.168.128.1:7907 https://fapi.binance.com/fapi/v1/time
```

全部超时。

但从 Windows 本机跑：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\15470\Code\relay-station\scripts\windows\Start-QountBinanceProxy.ps1 start -Probe
```

又能瞬时拿到：

- 可用出口 IP
- Binance `/fapi/v1/time` 正常返回

这说明：

- 不是 `qount` Python 逻辑先坏了
- 也不是 Binance 一定完全不可达
- 更早的断点在 Windows 专用代理没有稳定常驻

### 4. 修复后重新收敛

脚本和任务修完后，`2026-05-13 13:10 CST` 左右再次检查：

- `QountBinanceProxy` 任务：`state=Running`
- `status -Probe`：
  - `running=true`
  - `listening=true`
  - `ruleTarget=🇯🇵日本高速01|BGP|流媒体`
  - `ip=95.40.7.69`
  - `binanceTime` 正常
- WSL 侧重新验证：
  - `curl --proxy http://192.168.128.1:7907 https://api.ipify.org` 返回 `95.40.7.69`
  - `curl --proxy http://192.168.128.1:7907 https://fapi.binance.com/fapi/v1/time` 正常

### 5. 白名单生效后的最终恢复

在当前出口 IP `95.40.7.69` 被加入 Binance 白名单后，再次从 WSL 验证：

- `python -m qount.main healthcheck`
  - `binance_ok=true`
- `python -m qount.main preflight-live`
  - `credentials.ok=true`
  - `position_mode.ok=true`
  - `balance_guard.ok=true`
  - `live_guard.ok=true`
- `python -m qount.main run-once`
  - 返回成功 completed run
  - `run_id=911`
  - `symbol=XRP/USDT:USDT`
  - `action=close`
  - `order_status=closed`

这说明到这里为止，恢复的不只是公网可达性，而是：

- 专线代理恢复
- WSL bridge 恢复
- Binance 公有接口恢复
- Binance 私有接口白名单恢复
- 真实 live 下单链路恢复

## 这次故障真正的根因

### 1. `QountBinanceProxy` 之前不是稳定常驻模型

旧逻辑的问题是：

- Windows 计划任务启动的是脚本 `run`
- 但脚本本身没有 watchdog 语义
- 一旦 `verge-mihomo.exe` 子进程退出，这条专线就直接消失
- 任务表面上还可能只显示跑过，但端口已经不在监听

所以这次出现的是：

- 生产 timer 继续每 5 分钟调 `qount`
- 但 `qount` 背后的 Binance 专线已经没了
- 于是所有 run 都变成 `market_data_failed`

### 2. 开机/环境早期时 WSL 网卡依赖太脆

旧脚本在处理防火墙规则时，默认要求：

- `vEthernet (WSL...)` 已经出现

如果开机早期 WSL 网卡还没起来，就可能直接把任务带死。  
这次已经把这块改成：

- WSL 网卡存在时，用精确子网规则刷新
- WSL 网卡暂时不存在时，保留已有规则或先建 fallback 规则

### 3. dedicated 配置以前会跟着 group 漂

旧 dedicated 配置的关键规则本质上是：

```text
MATCH,良心云
```

这会带来一个问题：

- `良心云` 是一个 group，不是最终出口节点
- 每次 dedicated 实例重启时，它可能重新走 group 当前状态
- 这样即使 Windows 主 Clash Verge 表面上看起来还是“良心云”，dedicated 实例的真实出口也可能漂

这次已经改成：

- 启动前读取 `profiles.yaml`
- 找到 `良心云` 当前真正选中的 `now`
- dedicated 配置直接写成：
  - `MATCH,<当前叶子节点>`

本次现场解析到的是：

- `良心云 -> 🇯🇵日本高速01|BGP|流媒体`

修复后两次受控重启拿到的出口 IP 都保持为：

- `95.40.7.69`

因此这次已经解决的是：

- “本机任务重启导致的选路漂移”

但要注意，下面这个问题并没有谁能用本地脚本彻底消灭：

- 如果上游供应商以后让 `🇯🇵日本高速01|BGP|流媒体` 自己换出口 IP，Binance 白名单还是要跟着改

也就是说：

- 本地漂移：这次已经修掉
- 上游节点自身换出口：只能靠自有固定出口彻底根治

## 这次实际改了什么

Windows 侧脚本：

- 文件：
  - `C:\Users\15470\Code\relay-station\scripts\windows\Start-QountBinanceProxy.ps1`
- 本地仓库对应：
  - [../relay-station/scripts/windows/Start-QountBinanceProxy.ps1](../../relay-station/scripts/windows/Start-QountBinanceProxy.ps1)

本次新增/调整的关键行为：

- 新增 `task.log`，记录 watchdog 启动、重启、防火墙刷新
- 新增 `Get-ProxyState` / `Wait-ProxyHealthy`
- `start` 现在要求“端口监听 + 受管进程仍存活”双条件成立
- `run` 现在是 watchdog loop：
  - 保证代理启动
  - 阻塞等待子进程
  - 一旦退出就自动拉起
- `install-task` 现在带任务级 restart 策略
- dedicated 渲染时自动把 `良心云` 解析到当前叶子节点

## 当前最终验证结果

截至 `2026-05-13` 这次恢复完成时，现场验证结果是：

- Windows `QountBinanceProxy`：
  - `state=Running`
  - `running=true`
  - `listening=true`
  - `ruleTarget=🇯🇵日本高速01|BGP|流媒体`
  - `ip=95.40.7.69`
- WSL 经 `192.168.128.1:7907`：
  - `api.ipify.org` 正常
  - `fapi.binance.com/fapi/v1/time` 正常
- `qount`：
  - `healthcheck.binance_ok=true`
  - `preflight-live.credentials.ok=true`
  - `preflight-live.position_mode.ok=true`
  - `preflight-live.balance_guard.ok=true`
  - `run-once` 成功 completed
  - `runtime-status.halted=false`
  - `runtime-status.ai_failure_streak=0`

## 下次最快排查顺序

如果下次又出现“看起来在跑，但没有交易/全是失败”，不要从猜策略开始，直接按下面顺序查。

### 第 1 步：先看 Windows 专线代理是不是活着

```bash
ssh home 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\15470\Code\relay-station\scripts\windows\Start-QountBinanceProxy.ps1 status -Probe'
```

重点看：

- `running`
- `listening`
- `ruleTarget`
- `ip`
- `binanceTime`

解释：

- `running=false` 或 `listening=false`
  - 先修 `QountBinanceProxy`
- `running=true` 且 `binanceTime` 正常
  - 说明 Windows 本机 dedicated 出口层大概率正常

### 第 2 步：再看 WSL 到 Windows 7907 的桥是不是通

```bash
ssh home cmd /c wsl -d Ubuntu -u alyaloale -- bash -lc '
curl -sS --max-time 12 --proxy http://192.168.128.1:7907 https://api.ipify.org &&
echo &&
curl -sS --max-time 12 --proxy http://192.168.128.1:7907 https://fapi.binance.com/fapi/v1/time
'
```

解释：

- Windows `status -Probe` 正常，但 WSL 还是超时
  - 优先怀疑 WSL bridge / Windows firewall
- WSL 这里也正常
  - 说明 public 路由层已经通

### 第 3 步：再看 `qount` 自己的 live preflight

```bash
ssh home cmd /c wsl -d Ubuntu -u alyaloale -- bash -lc '
cd /home/alyaloale/Code/qount &&
set -a && source .env && set +a &&
source .venv/bin/activate &&
export PYTHONPATH=src &&
python -m qount.main healthcheck &&
python -m qount.main preflight-live
'
```

解释：

- `healthcheck.binance_ok=true`
  - 只说明 public 路由层正常
- `preflight-live.credentials.ok=false` 且报 `-2015`
  - 说明当前出口 IP 白名单或 API 权限还没对上
- `preflight-live` 全绿
  - 才说明 live guard 真正放行

### 第 4 步：最后用真实 `run-once` 收尾

```bash
ssh home cmd /c wsl -d Ubuntu -u alyaloale -- bash -lc '
cd /home/alyaloale/Code/qount &&
set -a && source .env && set +a &&
source .venv/bin/activate &&
export PYTHONPATH=src &&
python -m qount.main run-once &&
python -m qount.main runtime-status
'
```

原因：

- `healthcheck` 只能证明 public path
- `preflight-live` 只能证明 guard 条件
- 真正 private API 和执行链路是否恢复，还是要看一次真实 `run-once`

## 给下次的简短记忆

下次如果只记一句话，就记这个：

- `timer 正常 != 实盘正常`
- 先证 `QountBinanceProxy`，再证 `WSL -> 7907`，再证 `preflight-live`，最后用 `run-once` 收尾
