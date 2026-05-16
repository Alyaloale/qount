# qount 当前 live 基线与策略现状（2026-05-17）

这份文档只记录一件事：

- **生产 WSL 节点此刻真实在跑什么**

如果你下次想快速回答下面这些问题，先看这份：

- 现在 live 到底是不是正常在跑
- 当前 `.env` 基线到底是什么
- 现在策略的主问题到底是运行故障，还是 fresh entry 质量
- 当前持仓为什么还在 `hold`

历史调参过程和旧结论不要再从 `2026-05-13` 那份文档倒推；那份已经转入 archive。

## 权威数据源

- 唯一生产节点：
  - `WSL /home/alyaloale/Code/qount`
- 权威运行状态：
  - `systemd --user qount-runner.timer`
  - `python -m qount.main preflight-live`
  - `python -m qount.main runtime-status`
  - `state/qount.db`
- 本地 Mac checkout 的代码和文档只是编辑入口，不是生产真相

## 本次核查时间

- 运行 / 账户 / 保护单核查：
  - `2026-05-17 01:48 CST`
- 最近管理层 `ETH` 复查样本：
  - 最新看到 `run_id=2015`
- 当前策略复盘窗口：
  - `signal-review --limit 160 --horizon-bars 3`
  - 已评估窗口：`run_id 1849-2010`

## 当前 live 基线

截至这次核查，生产 live 基线是：

- 节点：
  - `WSL /home/alyaloale/Code/qount`
- 模式：
  - `QOUNT_MODE=live`
  - `QOUNT_EXCHANGE_ID=binance`
  - `QOUNT_MARKET_TYPE=future`
- 交易对：
  - `QOUNT_SYMBOLS=SOL/USDT,XRP/USDT,BTC/USDT,ETH/USDT`
- 周期：
  - `QOUNT_TIMEFRAME=5m`
  - `QOUNT_CANDIDATE_TREND_TIMEFRAME=1h`
- 模型：
  - `QOUNT_AI_MODEL=gpt-5.4`
- 杠杆与仓位：
  - `QOUNT_CONTRACT_LEVERAGE=6`
  - `QOUNT_CONTRACT_MARGIN_MODE=isolated`
  - `QOUNT_MAX_OPEN_POSITIONS=3`
  - `QOUNT_MAX_ENTRY_SIZE_PCT=0.30`
  - `QOUNT_MAX_RISK_PER_TRADE_PCT=0.01`
- 新开仓硬阈值：
  - `QOUNT_MIN_EXPECTED_EDGE_PCT=0.0015`
  - `QOUNT_MIN_OPEN_SIZE_PCT=0.10`
  - `QOUNT_MIN_TAKE_PROFIT_PCT=0.015`
- 当前管理层保护参数：
  - `QOUNT_TRAILING_PROFIT_ARM_PCT=0.0075`
  - `QOUNT_TRAILING_PROFIT_RETRACE_PCT=0.003`
  - `QOUNT_PARTIAL_TAKE_PROFIT_ENABLE=true`
  - `QOUNT_PARTIAL_TAKE_PROFIT_TRIGGER_PCT=0.012`
  - `QOUNT_PARTIAL_TAKE_PROFIT_STEP_PCT=0.012`
  - `QOUNT_PARTIAL_TAKE_PROFIT_FRACTION=0.50`
  - `QOUNT_PARTIAL_TAKE_PROFIT_MAX_TIMES=1`
  - `QOUNT_BREAKEVEN_STOP_BUFFER_PCT=0.0012`
  - `QOUNT_DYNAMIC_PROTECTIVE_REFRESH_ENABLE=true`

当前 live 仍然是这条链：

`closed 5m bar -> snapshot -> candidate filter -> AI -> risk -> execute -> journal -> review`

它不是 intrabar 高频策略，也不是盯盘口手动辅助系统。

## 当前运行状态

这次现场核查到的状态是：

- `qount-runner.timer`
  - `active (waiting)`
- `live_guard`
  - `ok=true`
  - `armed=true`
  - `persistent=true`
- `runtime-status`
  - `halted=false`
  - `ai_failure_streak=0`
- `preflight-live`
  - 公有接口正常
  - 私有接口正常
  - `position_mode=oneway`
  - `balance_guard.ok=true`

这说明当前不是：

- timer 停了
- live guard 没放行
- 账户权限失效
- Binance 私有接口彻底不可用

要单独记一条风险：

- 近几小时出现过零星 `market_data_failed`
- 例如 `run_id=2000`
  - `status=market_data_failed`
  - `error=binance GET https://fapi.binance.com/fapi/v1/exchangeInfo`

但它后面已经恢复成连续 `completed + hold/noop`，所以当前更像偶发专线/公网抖动，不是主链路仍然坏着。

## 当前账户与持仓

`2026-05-17 01:48 CST` 核查时：

- `equity_quote=155.80669269`
- `quote_free=133.20985982`
- `quote_used=22.59683287`
- `wallet_balance_quote=156.31421269`
- `realized_pnl_quote=-1.01382914`
- `unrealized_pnl_quote=-0.51776`

当前真实持仓只有 1 笔：

- `ETH/USDT:USDT short`
- 数量：`0.064`
- 开仓均价：`2171.35`
- 当前标记价：约 `2179.44`
- 当前名义价值：约 `139.48 USDT`
- 当前未实现盈亏：约 `-0.52 USDT`

这笔仓不是裸仓。交易所侧还能查到两张 `reduceOnly` 条件单：

- `TP`
  - `triggerPrice=2127.92`
- `SL`
  - `triggerPrice=2187.64`

普通 `fetch_open_orders()` 看不到它们；要显式用 `trigger=true` 查 conditional orders。

## 当前策略结论

当前更准确的结论不是“系统没交易，所以大概坏了”，而是：

- 运行链路健康
- 持仓管理也正常
- 当前主问题仍然是 **fresh entry 质量弱**

这次在生产 WSL 上跑出的复盘窗口结论：

- `reviewed=140`
- `good_hold=133`
- `flat actionable=6`
- `missed_move=1`
- `overall.avg_net_edge_pct=-0.00495`
- `actionable.avg_net_edge_pct=-0.11558`
- `fresh_entry.avg_net_edge_pct=-0.20387`

这组数的含义很直接：

- 最近大多数 `hold` 是站得住的，不是系统全面错过大行情
- 真正少数出手的样本，事后看边际还是偏薄
- 当前问题重点仍然是“开仓质量”，不是“管理层完全不会平仓”

最近常见的阻塞层仍然是：

- `low_volatility`
- `low_volume`
- `short_setup_countertrend_drift`
- `expected_edge_below_minimum`

## 当前这笔 ETH short 为什么一直 hold

这笔仓的开仓来源是：

- `run_id=1997`
- `action=sell`
- `size_pct=0.15`
- `take_profit_pct=0.02`
- `stop_loss_pct=0.0075`
- `entry_archetype=aligned_short_continuation_short`

当时开仓证据是成立的：

- `1h trend_bias=short`
- `5m return_24bars` 为负
- 本地快慢均线都偏空
- `volume_ratio_20` 很高
- `risk expected_edge` 只是刚刚高于阈值
  - `final_expected_edge_pct=0.0016757`
  - `required_threshold_pct=0.0015`

开仓后管理层之所以一直 `hold`，这次查到的是非常具体的原因，不是泛泛而谈：

### 1. AI 和 risk 最近几轮都没有给出平仓理由

最近 `ETH` 管理样本里：

- AI 决策就是 `hold`
- risk 最终也是 `hold`
- `risk.reasons=["ok"]`

也就是说：

- 不是 validator 拒了
- 不是 risk 把 `close` 打回 `hold`
- 而是当前管理输入本身还没触发强平条件

### 2. 这笔仓目前根本不在“该收利润”的状态

最近几轮 `position_before` 一直是小幅浮亏：

- 大致在 `-0.39 ~ -0.53 USDT`

所以当前不是：

- “已经有利润，但系统不肯收”

而是：

- “当前没有利润可收”

### 3. 它到现在都没碰到管理层的盈利保护门槛

当前配置里的关键门槛是：

- trailing arm：`+0.75%`
- trailing retrace close：从峰值回撤 `0.30%`
- partial take profit：`+1.20%`
- hard TP：`+2.00%`

把这笔 `ETH` short 开仓后的 5m 价格路径拉出来后，看到：

- 开仓后最好的一次有利低点大约只到 `2169.00`
- 对这笔 short 来说，最大浮盈只到约 `+0.108%`

这远低于：

- `+0.75%` trailing arm
- `+1.20%` partial take profit
- `+2.00%` hard TP

所以它既没有进入 `partial_take_profit`，也没有进入 `trailing_profit_retrace` 保护区。

### 4. 当前 1h 仍然偏空，5m 虽然回抽，但还没恶化到强制 close

最近几轮 `ETH` 快照里，比较稳定的是：

- `1h trend_bias=short`
- `1h sma_fast_ratio < 0`
- `1h sma_slow_ratio < 0`

本地 `5m` 确实出现了反抽：

- `sma_fast_ratio > 0`
- `sma_slow_ratio > 0`
- `rsi_14` 偏高

但当前 short 管理层的 adverse 条件不是“只要反抽就平”，它要求同时满足更强的本地逆转证据：

- `return_1bar >= 0.15%`
- `sma_fast_ratio > 0`
- 并且再叠加：
  - `trend_bias == long`
  - 或 `sma_slow_ratio > 0`
  - 或 `return_24bars >= 0.25%`

这几轮里，`1h` 仍然明显偏空，而本地 `1bar` 反抽多数只是轻微抖动，没稳定打到那条 adverse 触发线，所以 management 继续 `hold`。

## 现在该不该更积极收利润

对**这笔具体的 ETH short**，结论是：

- **现在不该用“更积极收利润”来描述下一步**

原因很简单：

- 现在它没有利润
- 而且开仓后历史最好浮盈也只有约 `+0.108%`
- 从来没进过当前策略定义里的“受保护盈利区”

如果你要更激进地处理它，真正对应的不是“收利润”，而是下面这类更防守的管理改法：

- 更早把 short 的本地 rebound 判成 `adverse`
- 给 profitable short 增加类似 long side 的 `momentum cooldown close`
- 在小幅浮亏且 5m 明显转强时更早收掉 continuation short

但这已经不是“把当前利润更快落袋”，而是**改 short 管理层的止盈/止损与反抽退出逻辑**。

## 当前文档入口

从现在开始，当前默认入口应当是：

- 当前 live 基线 / 当前持仓 / 当前策略现状：
  - [live-baseline-and-strategy-current.md](live-baseline-and-strategy-current.md)
- 当前 active design / 后续策略改动顺序：
  - [strategy-optimization-design.md](strategy-optimization-design.md)
- 当前 fresh-entry 效果复查口径：
  - [fresh-entry-effect-check-2026-05-14.md](fresh-entry-effect-check-2026-05-14.md)
- 生产故障、专线、白名单恢复记录：
  - [live-recovery-2026-05-13.md](live-recovery-2026-05-13.md)

旧文档处理方式：

- `2026-05-13` 那份 live strategy/tuning 文档
  - 现在只保留历史调参记录用途
  - 已转到 archive，不再作为当前入口
