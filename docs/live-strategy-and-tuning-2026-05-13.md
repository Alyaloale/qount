# qount 当前 Live 策略与本次调参记录（2026-05-13）

这份文档记录 `2026-05-13` 这次 live 修复之后，`qount` 当前实际在跑的策略口径、已落地的执行与风控调整、它们能解决什么问题，以及它们解决不了什么问题。

如果你下次主要关心的是：

- 现在实盘到底按什么策略在跑
- 本次为什么要调开仓规模、TP 下限、浮盈回撤保护
- 这些改动对“赚了不平、最后回吐”到底有没有用

优先看这份文档。  
如果你关心的是 `2026-05-14` 基于最新 `signal-review` 得出的**下一轮具体改动方案**，看：

- [strategy-optimization-design.md](strategy-optimization-design.md)

如果你关心的是当天专线代理 / 白名单 / WSL 断链怎么恢复的，去看：

- [live-recovery-2026-05-13.md](live-recovery-2026-05-13.md)

## 当前 live 运行基线

截至 `2026-05-13`，当前生产 live 运行基线是：

- 节点：
  - 生产唯一节点仍是 WSL：`/home/alyaloale/Code/qount`
- 模式：
  - `QOUNT_MODE=live`
  - `QOUNT_MARKET_TYPE=future`
- 交易对：
  - `QOUNT_SYMBOLS=SOL/USDT,XRP/USDT`
- 周期：
  - `QOUNT_TIMEFRAME=5m`
- 杠杆与保证金：
  - `QOUNT_CONTRACT_LEVERAGE=3`
  - `QOUNT_CONTRACT_MARGIN_MODE=isolated`

当前 live 不是高频 / 盯盘型策略，而是：

`closed 5m bar -> snapshot -> candidate filter -> AI -> risk -> execute -> review`

它只基于**已经闭合的 5m K 线**做决策，不按 intrabar 浮动 tick 做主决策。

## 当前关键参数

### 来自生产 `.env` 的直接设置

- `QOUNT_MAX_ENTRY_SIZE_PCT=0.30`
- `QOUNT_MAX_RISK_PER_TRADE_PCT=0.01`
- `QOUNT_MIN_NOTIONAL_QUOTE=5`
- `QOUNT_CONTRACT_LEVERAGE=3`
- `QOUNT_MIN_EXPECTED_EDGE_PCT=0.0015`

### 这次新增并已写入生产 `.env` 的设置

- `QOUNT_MIN_OPEN_SIZE_PCT=0.10`
- `QOUNT_MIN_TAKE_PROFIT_PCT=0.015`
- `QOUNT_TRAILING_PROFIT_ARM_PCT=0.01`
- `QOUNT_TRAILING_PROFIT_RETRACE_PCT=0.005`

### 当前仍走代码默认值的设置

这些值当前 `.env` 没显式写，但 live 节点实际仍按代码默认值生效：

- `QOUNT_ESTIMATED_FEE_PCT=0.0004`
- `QOUNT_ESTIMATED_SLIPPAGE_PCT=0.0002`
- `QOUNT_MIN_HOLD_BARS=2`
- `QOUNT_SAME_SYMBOL_REENTRY_COOLDOWN_BARS=3`

### 候选过滤与 fresh entry 风控的最新放松

这轮后续微调又额外放松了三处：

- `candidate_filter`
  - `MIN_CANDIDATE_VOLATILITY_PCT` 从 `0.0025` 放到 `0.0020`
  - `MIN_CANDIDATE_VOLUME_RATIO` 从 `0.75` 放到 `0.60`
  - 对“方向明确但量能/波动略弱”的候选，不再一刀切拒绝，而是改成 `soft_penalty`
- `AI prompt`
  - 对 `candidate_filter` 已选出的 symbol，不再要求“几乎完美 setup”才允许 fresh entry
  - 对方向一致、只有轻微量能不足的候选，更倾向小仓位试单而不是默认 `hold`
- `risk gate`
  - `MIN_OPEN_SIGNAL_TREND_RETURN_PCT` 从 `0.0010` 放到 `0.0005`
  - `MIN_OPEN_SIGNAL_VOLUME_RATIO` 从 `1.0` 放到 `0.60`

这组调整的目的不是无脑增交易，而是把原来卡在 `candidate_ok -> AI hold`、或 `AI 已给方向但 risk 只差一点点打回` 的样本放出来。

## 当前策略到底在做什么

### 1. 候选层

入口：

- [src/qount/candidate_filter.py](../src/qount/candidate_filter.py)

当前逻辑：

- 先过滤低波动、低成交量候选，但已经改成“硬拒 + 软惩罚”两级
- futures `short` 仍然会先走一层 precheck，避免明显 rebound / countertrend short 先送去给模型
- 如果已有持仓，会优先把持仓 symbol 作为 `position_management`
- 仍然是单 symbol 决策，不是组合分配器

### 2. AI 决策层

入口：

- [src/qount/ai_client.py](../src/qount/ai_client.py)
- [prompts/system_prompt_v1.txt](../prompts/system_prompt_v1.txt)
- [prompts/decision_prompt_v1.txt](../prompts/decision_prompt_v1.txt)

当前口径：

- 只用闭合 5m bar 的 snapshot
- `buy` 表示开/加多
- `sell` 表示开/加空
- `close` 表示平当前仓位
- `hold` 表示不动

这次 prompt 已经补了三条新的硬偏好：

- fresh futures entry 默认不要太小，清晰 setup 时更偏向 `size_pct=0.10~0.15`
- fresh entry 的 `take_profit_pct` 不要太紧，通常至少 `0.015`
- 如果已有明显浮盈，不要轻易把它完整吐回去

另外一条新口径是：

- 如果 `candidate_filter` 已经选出 1~2 个候选，模型不需要再等“完美 setup”
- 对方向一致、没有直接冲突、只是量能略弱的 fresh entry，更偏向小仓位试单

### 3. 风控层

入口：

- [src/qount/risk_engine.py](../src/qount/risk_engine.py)

当前风控会做这些事：

- 过滤边际不足的新开仓
- 过滤方向冲突的新开仓
- 控制最短持仓时间
- 控制反手冷却 / 同 symbol 重进冷却
- 对现有持仓做 management 判断

最新变化是：

- `min_expected_edge_pct` 已从 `0.0025` 放到 `0.0015`
- open signal 对 `return_24bars` 和 `volume_ratio_20` 的 fresh-entry 下限也已经同步放松
- 这样 candidate filter 和 AI 已放松后，不会继续被更后面的 risk gate 全部抵消

### 4. 执行层

入口：

- [src/qount/executor.py](../src/qount/executor.py)

当前 futures live 执行已经不是“只下进场单然后等下个 bar 再说”了，而是：

- 开仓成交后，立即挂交易所侧 `reduceOnly`：
  - `TAKE_PROFIT_MARKET`
  - `STOP_MARKET`
- 平仓前先清掉本系统挂过的旧保护单
- 如果保护单下单失败，会优先应急平掉刚开的仓，避免裸仓暴露

补一条 `2026-05-13 23:54 CST` 之后确认过的细节：

- Binance futures 的这两类保护单在交易所侧属于 `conditional/algo` 单
- 所以排查时不能只看普通 `fetch_open_orders()`
- 需要显式走 `fetch_open_orders(symbol, params={"trigger": True})`，取消时也要带 `trigger=true` 和 `clientAlgoId`
- 这次已经把 `src/qount/executor.py` 修到这条真实接口上；否则会出现“库里明明记录了 TP/SL 创建成功，但后续查询结果像是没有保护单”的假象

## 这次到底改了什么

## 0. 让“太保守”真正往下走一层

这一步不是抽象调参，而是直接把主瓶颈从“几乎不出手”往前推了一层。

现场验证里已经出现过这种样本：

- `candidate_filter` 已经给出 `candidate_ok`
- AI 已经给出真实 `sell`
- 但旧 risk gate 还会因为：
  - `expected_edge_below_minimum`
  - 或 `open_signal_low_volume`
  - 或 `open_signal_return_24bars_too_weak`
  把它压回 `hold`

现在这些门槛已经同步放松，目标是让“方向一致、成本后仍有一点边际、但不算特别强”的 5m futures short 能真实落地，而不是永远卡在 `hold/noop`。

## 1. 提高默认开仓规模

改动：

- 新增 `QOUNT_MIN_OPEN_SIZE_PCT=0.10`
- 风控会把过小的 fresh entry 尺寸抬到至少 `0.10`

代码：

- [src/qount/risk_engine.py](../src/qount/risk_engine.py)

目的：

- 避免模型总是给出 `0.05` 这种太小的 starter，导致绝对盈利太薄

重要说明：

- 这不是“固定都开 10%”
- 而是“低于 10% 的 fresh entry，不再默认接受”
- 仍然受 `QOUNT_MAX_ENTRY_SIZE_PCT=0.30` 上限约束

## 2. 抬高 TP 下限

改动：

- 新增 `QOUNT_MIN_TAKE_PROFIT_PCT=0.015`
- fresh entry 的 TP 不再允许落到 `0.005~0.007` 这种太紧的级别

代码：

- [src/qount/risk_engine.py](../src/qount/risk_engine.py)

目的：

- 避免刚好赚一点点就被策略目标本身锁死
- 让持仓目标更接近“有一点波段空间”，而不是超短小波动套利

## 3. 新增浮盈回撤保护

改动：

- 新增 `QOUNT_TRAILING_PROFIT_ARM_PCT=0.01`
- 新增 `QOUNT_TRAILING_PROFIT_RETRACE_PCT=0.005`

含义：

- 当一笔持仓浮盈先达到 `1%`
- 后续如果从已实现峰值再回撤 `0.5%`
- management 层会强制 `close`

代码：

- [src/qount/risk_engine.py](../src/qount/risk_engine.py)

目的：

- 解决“中间已经有一段不错浮盈，但继续 hold，最后回吐很多甚至转亏”的问题

## 4. 把原开仓计划里的 TP/SL 真正接回 management

改动：

- bar-close 管理层会回读最近一次开仓计划里的：
  - `take_profit_pct`
  - `stop_loss_pct`
- 命中后会直接转 `close`

这意味着：

- 就算交易所保护单因为极端情况没先触发
- management 层也不会再把“当初自己设的 TP/SL”完全当空气

## 5. 上真实交易所侧 reduceOnly 保护单

改动：

- futures 开仓后立即下：
  - `TAKE_PROFIT_MARKET`
  - `STOP_MARKET`
- 都带 `reduceOnly`

这一步解决的是旧问题里最硬的一层：

- 以前如果网络中断、WSL 失明、下一根 5m bar 没跑到，浮盈保护完全靠后面的轮询管理
- 现在至少交易所侧已经有保护单，不再完全依赖后续轮询

## 6. 修正 Binance futures 条件保护单的可见性与管理链路

这是 `2026-05-13 23:23 CST` 左右现场重新核对时才确认的问题，不属于前面的“是否已经上保护单”，而是“系统后续能不能正确看到并管理这些保护单”。

### 现场症状

- `run_id=1024` 在 `2026-05-13 23:11 CST` 新开了 `SOL/USDT:USDT` 空头
- journal 里明确记录：
  - 进场价 `91.31`
  - `TAKE_PROFIT_MARKET` 触发价 `89.30`
  - `STOP_MARKET` 触发价 `91.99`
  - 两张单的 `algoStatus` 都是 `NEW`
- 但如果只用普通 `fetch_open_orders()` 查，返回会是空
- 这会让系统误以为“当前没有保护单”，从而影响：
  - 保护单是否已存在的判断
  - 平仓前撤旧保护单
  - partial reduce 后重挂剩余保护单
  - trailing / breakeven refresh 是否已经到位

### 根因

- Binance futures 把这类 `TAKE_PROFIT_MARKET` / `STOP_MARKET` 暴露在 `algo/conditional` 订单接口
- `ccxt.binance.fetch_open_orders(symbol)` 默认走的是普通 open orders
- 只有显式带 `params={"trigger": True}`，才会走 `Current-All-Algo-Open-Orders`
- 取消时同理，不能只走普通 `cancel_order(order_id, symbol)`；需要带：
  - `trigger=true`
  - `clientAlgoId=<qount-tp-... 或 qount-sl-...>`

### 这次修复

- `src/qount/executor.py`
  - futures 下查询 managed 保护单时，同时查普通 open orders 和 `trigger=true` 的 conditional orders
  - 对重复结果做去重
  - 对 managed conditional 保护单取消时，自动带 `trigger=true` 和 `clientAlgoId`
- `src/qount/orchestrator.py`
  - `filtered_hold` / AI failure fallback 改成优先写解析后的 symbol，例如 `SOL/USDT:USDT`
  - 不再把 portfolio bookkeeping 污染成 `symbol_not_allowed:SOL/USDT`

### 修复后的现场验证

- 同步前现场确认：
  - 普通 `fetch_open_orders()` 看不到 `SOL` 的两张保护单
  - `fetch_open_orders(..., params={"trigger": True})` 能看到两张单都还在
- `2026-05-13 23:52 CST`
  - 停掉 `qount-runner.timer`
  - 把修复同步到 WSL
  - 远端重新 `pip install -e .`
  - 远端 `unittest` 36 个用例通过
- `2026-05-13 23:54 CST`
  - 远端 helper 已能直接读到 `SOL` 的两张 managed 条件保护单
- `2026-05-13 23:55 CST`
  - timer 恢复后真实新 tick 跑出 `run_id=1035`
  - 结果是正常 `hold/noop`
  - 当前 `SOL` 持仓保护单仍然存在，数量 `2`

### 下次最快检查命令

如果你只是想确认“当前仓位到底有没有 qount 自己挂的交易所侧保护单”，直接在 WSL 跑这个：

```bash
ssh home cmd /c wsl -d Ubuntu -u alyaloale -- bash -lc '
cd /home/alyaloale/Code/qount &&
set -a && source .env && set +a &&
source .venv/bin/activate &&
export PYTHONPATH=src &&
python - <<\"PY\"
import json
from qount.settings import Settings
from qount.executor import Executor
from qount.journal import Journal

s = Settings.from_env()
executor = Executor(s, Journal(s.db_path))
exchange = executor._exchange()
sync = getattr(exchange, "load_time_difference", None)
if callable(sync):
    sync()

orders = executor._managed_protective_orders(exchange, "SOL/USDT:USDT")
print(json.dumps([
    {
        "id": str(o.get("id")),
        "clientOrderId": executor._order_client_id(o),
        "triggerPrice": (
            o.get("triggerPrice")
            or o.get("stopPrice")
            or (o.get("info") or {}).get("triggerPrice")
            or (o.get("info") or {}).get("stopPrice")
        ),
    }
    for o in orders
], ensure_ascii=False, indent=2))
PY
'
```

如果这里能看到两张单，而普通 `fetch_open_orders()` 看不到，不要再怀疑“保护单没挂上”，先怀疑你查的是错接口。

## 这次改动解决了什么

### 已明确解决的

- “赚了一段但系统完全不锁利，后来全部回吐”
  - 现在有交易所侧 TP/SL
  - 有 management TP/SL 回读
  - 有浮盈回撤保护

- “仓位太小导致单笔利润始终只剩几毛钱”
  - 现在至少不会再默认从 `0.05` 那么小的 fresh entry 起步

- “模型给太紧的 TP，本来就只想吃 0.5% 左右”
  - 现在 fresh entry 的 TP 至少会被抬到 `1.5%`

- “候选已经过了，但 AI 或 risk 还是层层回到 hold”
  - 现在 candidate filter、AI prompt、risk gate 的 fresh-entry 保守度已经统一下调
  - 不再要求每一层都各自重复追求“完美 setup”

### 仍然没有解决的

- 如果你想要的是明显更大的绝对收益，账户规模 / 杠杆 / 开仓比例仍然决定上限
- 当前策略仍然是闭合 5m bar 决策，不是 intrabar 趋势跟踪系统
- 当前仍然是单 symbol 决策，不是多持仓组合器
- 当前 entry 过滤仍然偏保守，只是从“太难出手”放松到“允许更合理的小仓位试单”

## 最新现场结果

这轮放松不是停留在 review 或 prompt 里，而是已经在 WSL 生产节点上出现了真实开仓：

- 真实 `run-once` 触发了一笔 `SOL/USDT:USDT sell`
- 成交数量约 `0.63`
- 名义仓位约 `57.5 USDT`
- 成交后 cached live status 已显示一笔 `SOL/USDT:USDT` short

这说明当前策略已经从“主要是健康 hold/noop”推进到“开始对更边缘但仍受控的 setup 真正出手”。

这不等于已经证明收益稳定，只说明：

- 候选过滤和 AI 的保守度下降已经生效
- risk gate 不再把这类轻度边缘样本全部压回 `hold`
- 下一步评估重点会从“为什么不出手”转到“这些新放行的 short 质量到底如何”

## 为什么之前 4~5 个点的时候只赚到 0.4~0.5 USDT

这个问题有两层原因。

### 1. 以前确实存在“该平没平”

之前那笔 `XRP` 空单已经证明：

- 开仓时自己就给了 TP
- 中途浮盈一度远高于那个 TP
- 但旧逻辑没有真实交易所保护单，也没有在 management 层强制执行原开仓 TP

所以这部分确实是策略/执行问题，不是你看错了。

### 2. 即使修好“不平仓”，绝对收益仍受仓位限制

按当前账户体量和参数，绝对收益并不会无限放大。

当前 live 账户权益大约在：

- `160 USDT` 左右

按新的最小 fresh entry 规则：

- `size_pct=0.10`
- 杠杆 `3x`

对应最小名义仓位大约是：

- `160 * 0.10 * 3 = 48 USDT`

这个量级下，大致收益是：

- 行情走 `1%`：约 `0.48 USDT`
- 行情走 `2%`：约 `0.96 USDT`
- 行情走 `4%`：约 `1.92 USDT`
- 行情走 `5%`：约 `2.40 USDT`

所以：

- 这次改动会显著改善“中途赚到却不锁住”的问题
- 也会把过小仓位往上抬
- 但如果你想让单笔收益再明显变大，还是要继续提高：
  - 仓位比例
  - 杠杆
  - 或账户本金

## 当前建议如何理解这套策略

当前这套 live 更准确的定位是：

- 低频
- 保守
- 5m 闭合 bar 驱动
- 候选先过滤
- AI 做单 symbol 决策
- 风控做最终裁决
- execution 负责真实保护单

它不再是“纯 AI 自己决定全流程”的系统，而是：

`候选过滤 + AI + 风控 + 交易所保护单`

## 这次改动之后，当前最值得继续观察的指标

下次复查优先看这些：

- recent live open 的 `size_pct` 是否真的不再总落在 `0.05`
- recent live open 的 `take_profit_pct` 是否已稳定抬到 `>= 0.015`
- 真实成交里是否开始出现：
  - 交易所侧 reduceOnly TP 成交
  - 或 management trailing profit retrace 触发的 `close`
- `signal-review` 里的：
  - `management` 组 `avg_net_edge_pct`
  - `actionable` 组 `avg_net_edge_pct`
  - 是否继续出现“明明已明显浮盈却最终 bad/flat close”

## 当前快速检查命令

### 看 live 是否健康

```bash
ssh home cmd /c wsl -d Ubuntu -u alyaloale -- bash -lc '
cd /home/alyaloale/Code/qount &&
set -a && source .env && set +a &&
source .venv/bin/activate &&
export PYTHONPATH=src &&
python -m qount.main preflight-live &&
python -m qount.main runtime-status
'
```

### 看最近 review

```bash
ssh home cmd /c wsl -d Ubuntu -u alyaloale -- bash -lc '
cd /home/alyaloale/Code/qount &&
set -a && source .env && set +a &&
source .venv/bin/activate &&
export PYTHONPATH=src &&
python -m qount.main signal-review --limit 30 --horizon-bars 3
'
```

### 看最近真实成交

```bash
ssh home cmd /c wsl -d Ubuntu -u alyaloale -- bash -lc '
cd /home/alyaloale/Code/qount &&
set -a && source .env && set +a &&
source .venv/bin/activate &&
export PYTHONPATH=src &&
python - <<\"PY\"
from qount.settings import Settings
from qount.orchestrator import Orchestrator
s = Settings.from_env()
o = Orchestrator(s)
print(o.live_status(include_exchange=True))
PY
'
```

## 对下次接手的人

如果下次再问“为什么收益还是小”或者“为什么赚了没平”，先分开回答：

1. 这是仓位太小的问题，还是执行/管理逻辑的问题？
2. 当前是没有浮盈，还是有浮盈却没有被保护？
3. 当前绝对收益不满意，是应该再调：
   - `QOUNT_MIN_OPEN_SIZE_PCT`
   - `QOUNT_CONTRACT_LEVERAGE`
   - `QOUNT_MIN_TAKE_PROFIT_PCT`
   - `QOUNT_TRAILING_PROFIT_*`

不要把这几类问题混成一句“策略不行”。
