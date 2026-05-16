# qount 生产故障段与恢复记录（2026-05-13）

这份文档记录 `2026-05-13` 这次 `qount` 生产故障段的真实时间线、根因拆解、修复动作和最终验证结果，目标是下次不要再从“是不是 Binance 又抽风了”开始猜。

补充说明：

- 如果你关心的是这次修复之后“当前 live 基线是什么、现在持什么仓、当前策略状态如何”，优先去看：
  - [docs/live-baseline-and-strategy-current.md](live-baseline-and-strategy-current.md)

## 2026-05-16 当前基线更新

`2026-05-14` 那节基线现在已经不够新，至少有两处不能继续直接复用：

- 旧固定叶子：
  - `🇯🇵日本高速03|BGP|流媒体`
  - 当前已经不在新的 `clash-verge.yaml` 里
- 旧出口 IP：
  - `18.163.116.238`
  - 也不再是这次验证时的当前出口

`2026-05-16 14:45 CST` 现场重新验证后的当前口径是：

- 当前 dedicated Binance 叶子：
  - `🇯🇵日本高速02|BGP|CUCM`
- Windows `status -Probe` 曾经返回过的出口 IP：
  - `203.10.99.12`
- WSL 默认 Binance 专线仍然是：
  - `http://192.168.128.1:7907`

这次还要额外记一条经验：

- Windows `QountBinanceProxy` 计划任务状态
- `status -Probe`
- WSL `curl --proxy`

三者在抖动时可能互相打架。

这次现场就出现过：

- `status -Probe` / ScheduledTask 看起来不健康
- 但 WSL `7907 -> Binance time` 已经先恢复
- 随后 `preflight-live` 重新全绿
- 再跑出一条新的 `completed` live run

所以从这次开始，当前生产真相的优先级应该明确成：

1. `WSL -> 192.168.128.1:7907` 实测是否能通
2. `preflight-live` 是否全绿
3. 最新真实 `run` 是否重新回到 `completed`
4. 最后才拿 Windows `status -Probe` / ScheduledTask 当辅助证据

这次 `2026-05-16` 的部署验证收尾结果是：

- 第一次手动 `run-once`
  - `run_id=1783`
  - `status=market_data_failed`
  - `error=binance GET https://fapi.binance.com/fapi/v1/exchangeInfo`
- 专线按当前真实叶子重建并复证后：
  - `preflight-live` 重新全绿
  - 第二次手动 `run-once`
    - `run_id=1784`
    - `status=completed`
    - `symbol=SOL/USDT:USDT`
    - `action=hold`
    - `order_status=noop`
  - `qount-runner.timer`
    - 已恢复为 `active + waiting`

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

## 2026-05-15 13:20-14:05 CST 专线恢复续补

这段补记的是 `2026-05-15` 这次新的 live 故障和恢复过程。

这次最容易搞混的点，不是“代理坏了”这么简单，而是：

- relay / AI 路径和 Binance 专线路径是两条不同的出口
- Windows `status -Probe` 看到的结果，不一定等于 WSL 真正走到的 `7907` 出口

### 当时的真实拓扑

- AI / relay 路径：
  - Mac `127.0.0.1:8317`
  - `ssh home-tunnel`
  - Windows `127.0.0.1:8317` CLIProxyAPI
  - Windows `127.0.0.1:7897` Clash Verge mixed-port
- Binance 专线路径：
  - WSL `HTTP_PROXY` / `HTTPS_PROXY=http://192.168.128.1:7907`
  - Windows `QountBinanceProxy`

当时已经现场确认：

- relay / AI 这条出口还是 `203.10.97.121`
- 但 `qount` 的 `7907` 专线并没有正常工作

### 2026-05-15 13:20 CST 当时的故障真相

故障面上看到的是：

- `run_id=1486`
- `status=market_data_failed`
- 报错：
  - `binance GET https://fapi.binance.com/fapi/v1/exchangeInfo`

继续往下查后，真正的问题分成两层：

1. `QountBinanceProxy` 的 watchdog 任务参数已经漂到一个不存在的旧节点名：
   - `🇯🇵日本高速03|BGP|流媒体`
   - `task.log` 会反复刷：
     - `candidate proxy not found in source config`
2. Windows 上还残留了一个旧的 `SYSTEM` listener 长时间占着 `7907`
   - 导致“你以为已经切了 dedicated candidate”
   - 但 WSL 实际打到的还是那个旧 listener

这一步是这次最关键的新经验：

- **不要只看 Windows `status -Probe`**
- 必须再从 WSL 真实跑：
  - `curl --proxy http://192.168.128.1:7907 https://api.ipify.org`
  - `curl --proxy http://192.168.128.1:7907 https://fapi.binance.com/fapi/v1/time`

如果 Windows 说切好了，但 WSL 看到的出口 IP 还是旧的，就优先怀疑：

- `7907` 上有旧 listener 残留
- 当前切换没有真正落到 WSL 实际链路

### 这次恢复是怎么做通的

这次最后真正跑通的 dedicated candidate 是：

- `🇸🇬新加坡专线01|BGP|流媒体`

恢复步骤是：

1. 清掉占着 `7907` 的旧 listener
2. 重新用 dedicated `binance-proxy.yaml` 启动 `QountBinanceProxy`
3. 从 WSL 重复验证 `7907` 的真实出口，而不是只看 Windows 单次 probe

现场最终确认：

- WSL 经 `192.168.128.1:7907` 的真实出口稳定为：
  - `47.129.194.36`
- `fapi.binance.com/fapi/v1/time` 正常返回 `serverTime`

也就是说：

- 旧出口 `203.10.97.121` 那条是会触发 Binance `restricted location` 的旧路
- 恢复后的 dedicated 出口 `47.129.194.36` 可以正常访问 Binance 公有接口

### 白名单补完后的恢复结果

在把 `47.129.194.36` 加进 Binance API key 白名单之后，现场再次验证：

- `healthcheck.binance_ok=true`
- `preflight-live` 全绿
  - `credentials.ok=true`
  - `position_mode.ok=true`
  - `balance_guard.ok=true`
  - `live_guard.ok=true`
- `clear-halt` 之后：
  - `runtime-status.halted=false`
  - `runtime-status.ai_failure_streak=0`

最后没有强行手动 `run-once`，而是等真实 timer tick 收尾：

- `2026-05-15 14:05 CST`
- `run_id=1495`
- `status=completed`
- `symbol=XRP/USDT:USDT`
- `action=sell`
- `order_status=closed`

这说明到这一步：

- 不是只把 public path 修通了
- 而是 private API、live guard、真实下单链路也一起恢复了

### 这次要额外记住的判断分界

以后再看到类似故障，先把这两类错误分开，不要混成一句“Binance 不通”：

- `restricted location`
  - 说明当前出口 IP 本身属于 Binance 地区限制路径
- `-2015 Invalid API-key, IP, or permissions for action`
  - 说明当前出口已经能到 Binance
  - 但 API key 白名单或权限还没放行

这次两种错误都真实出现过，而且发生在**不同出口**上：

- `203.10.97.121`
  - `restricted location`
- `47.129.194.36`
  - 公有接口正常
  - 白名单补完前是 `-2015`
  - 白名单补完后恢复正常

所以以后如果你问“现在是地区受限还是白名单问题”，必须先先证：

1. WSL 真实 `7907` 出口 IP 是多少
2. 这个 IP 打 Binance 公有接口是 `serverTime` 还是 `restricted location`
3. 再看 private API 是不是 `-2015`

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

## 2026-05-15 18:35 CST 再恢复：专线坏了不是白名单坏了

这轮必须单独记，因为它和前面的 `-2015` 不是同一种故障。

### 当时现场状态

`2026-05-15 18:15 CST` 左右的真实现象是：

- `qount-runner.timer`
  - 仍然是 `active (waiting)`
- `runtime-status`
  - `halted=false`
  - `ai_failure_streak=0`
- 但 `preflight-live` 全红
  - `public_api.ok=false`
  - `symbols_ok.ok=false`
  - `credentials.ok=false`
- `run-once`
  - `status=market_data_failed`
  - `error=binance GET https://fapi.binance.com/fapi/v1/exchangeInfo`

也就是说：

- 不是策略不交易
- 不是 API key 又被白名单卡住
- 而是 **`7907` 自己先坏了**

### 根因不是“mihomo 没起”，而是 watchdog 绑错叶子

这次真正的根因有两层：

1. Windows 计划任务 `QountBinanceProxy`
   - 仍然硬编码：
     - `-CandidateProxyName "🇸🇬新加坡专线01|BGP|流媒体"`
2. 手动 `status/start` 虽然口头显示：
   - `ruleTarget=🇯🇵日本高速02|BGP|CUCM`
   - 但实际落到 `C:\ProgramData\qount-binance-proxy\binance-proxy.yaml` 里的末尾规则还是：
     - `MATCH,🇸🇬新加坡专线01|BGP|流媒体`

所以现场会出现这种很容易误判的分叉：

- `profiles.yaml`
  - 已选中 `🇯🇵日本高速02|BGP|CUCM`
- `status -Probe`
  - 看起来在用 `日本02`
- 但真正被 `7907` 用于出站的 `MATCH` 规则
  - 仍然是旧的 `🇸🇬新加坡专线01|BGP|流媒体`

这就是为什么：

- `process` 还活着
- `port 7907` 还在听
- 但从 `2026-05-15 16:50 CST` 开始，`stderr.log` 里已经持续出现：
  - `context deadline exceeded`

### 这次修复动作

这轮现场做掉的是：

1. 重新安装 Windows 计划任务：
   - `QountBinanceProxy`
   - 固定为：
     - `-CandidateProxyName "🇯🇵日本高速02|BGP|CUCM"`
2. 停掉当前 `7907` 相关 mihomo 进程
3. 用同一候选重新 `start`
4. 再用 `status -Probe` / WSL `curl --proxy` / `preflight-live` / `run-once` 逐层复证

### 恢复后的新基线

`2026-05-15 18:39 CST` 左右现场复核结果：

- Windows `status -Probe`
  - `running=true`
  - `listening=true`
  - `ruleTarget=🇯🇵日本高速02|BGP|CUCM`
  - `ip=203.10.99.12`
  - `binanceTime` 正常返回
- WSL `7907`
  - `curl --proxy http://192.168.128.1:7907 https://fapi.binance.com/fapi/v1/time`
  - 已恢复 `serverTime`
- `preflight-live`
  - 重新全绿
  - `credentials.ok=true`
  - `position_mode.ok=true`
  - `balance_guard.ok=true`
  - `live_guard.ok=true`
- 真实 `run-once`
  - `run_id=1553`
  - `status=completed`
  - `symbol=SOL/USDT:USDT`
  - `action=hold`
  - `order_status=noop`

### 这次必须记住的判断分界

这次非常值得记住的一点是：

- 用 `7898` 临时覆写后，`preflight-live` 已经能证明：
  - 白名单 / API 权限是对的
- 但默认 `7907` 仍然会全红

所以以后如果用户说：

- “我已经认证成功了，为什么还是不行”

不要先怀疑认证没生效。  
先证明：

1. 用 `7898` 临时覆写是不是全绿
2. 如果 `7898` 绿、`7907` 红
   - 说明是 dedicated route 故障
   - 不是 API 权限故障

### 下次如果再出现同类故障，先查这个

先看 Windows 计划任务里真正写的是哪个 `CandidateProxyName`：

```bash
ssh home "powershell -NoProfile -Command \"Export-ScheduledTask -TaskName 'QountBinanceProxy'\""
```

重点不要只看：

- `profiles.yaml` 里当前选中的 leaf

还要看：

- 计划任务参数
- `binance-proxy.yaml` 末尾 `rules:` 里的 `MATCH,...`

如果：

- 任务参数还是旧叶子
- 或 `MATCH` 规则还是旧叶子

那就不是继续猜白名单，也不是继续猜策略，先把 watchdog 绑定的候选修对。
