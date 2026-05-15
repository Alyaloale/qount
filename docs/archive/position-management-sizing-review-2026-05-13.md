# qount 仓位管理、风险 sizing 与 review 切片方案评审（2026-05-13，已归档）

归档说明：

- 这份文档保留的是 `2026-05-13` 对后续 `management / sizing / add / reverse` 的详细专项评审
- 其中已落地部分已经并回当前代码与主设计文档
- 目前它不再作为顶层主计划入口；当前默认入口改为：
  - [../strategy-optimization-design.md](../strategy-optimization-design.md)

这份文档评审并设计下面四类后续策略能力：

- 分批减仓 / 移动止盈
- 真正按 stop loss 反推仓位
- 加仓 / 反手的独立规则
- 更细的 `signal-review` 切片

结论先说清楚：**都值得做，但不能一起上线**。当前 live 主链路已经能跑，问题不是缺一个更复杂的 AI prompt，而是仓位、退出、加仓和复盘口径还没有形成闭环。正确顺序应该是：

1. 先修持仓入场价数据源，并扩展 review 切片。
2. 再把 `QOUNT_MAX_RISK_PER_TRADE_PCT` 做成真实 sizing 约束。
3. 再上分批减仓和移动止盈 / 移动止损。
4. 最后才拆加仓和反手规则。

## 执行状态

第一批已落地：

- futures 持仓快照优先用 `fetch_positions()`，`fetch_balance().info.positions` 只作为 fallback
- futures 开仓按 `stop_loss_pct + estimated_cost_pct` 反推 `final_size_pct`
- 如果交易所最小名义仓位会突破单笔风险预算，则拒单并记录 `risk_budget_below_exchange_minimum`
- `signal-review` 增加 `decision_lifecycle / exit_source / blocked_group`
- `signal-review` 增加 `planned_risk_pct_of_equity / future_R / mfe_pct / mae_pct / giveback_pct`

第二批最小版已落地：

- risk 层确定性触发单次 `partial_take_profit`
- `RiskVerdict` 增加 `close_fraction`
- futures executor 支持 `close_fraction < 1.0` 的 reduceOnly 部分平仓
- 部分平仓后取消旧保护单，并给剩余仓位重挂 reduceOnly 保护单
- 剩余 stop 移到入场价加/减 `QOUNT_BREAKEVEN_STOP_BUFFER_PCT`
- 只有执行成功后才写入 `partial_tp_done:*` 和 `breakeven_stop_armed:*`
- 如果剩余保护单重挂失败，executor 会应急平掉剩余仓位，避免裸仓

第三批最小版已落地：

- `hold` 下支持动态保护单刷新，不需要先发 market close
- 已触发 partial 的剩余仓位，或已进入 trailing arm 的持仓，会按 bar-close 管理结果刷新保护单
- 当目标保护价未变化时，不重复 cancel/recreate 订单
- 当目标保护价变化时，先校验剩余数量和目标 stop，再刷新保护单
- 如果刷新后重挂失败，executor 会应急平掉剩余仓位，避免裸仓

第四批最小版已落地：

- partial take profit 已支持多次阶梯触发，而不是同一阈值反复触发
- 第 `N+1` 次 partial 的触发阈值按 `trigger_pct + N * step_pct` 计算
- 当前实现默认在 partial 之后不给剩余仓位挂 full-size TP，避免和下一档 partial 冲突
- 剩余仓位主要由 breakeven / trailing protective refresh 管理
- 如果 partial 已发生，management 不会再按原始开仓 TP 过早把剩余仓位整平

仍未启用：

- 加仓独立规则
- 反手拆单执行

这些仍应按后续阶段单独实现，不能和 sizing / review 修正混在同一次 live 变更里。

## 当前事实基线

截至 2026-05-13，生产 live 基线仍是：

- `QOUNT_MODE=live`
- `QOUNT_MARKET_TYPE=future`
- `QOUNT_SYMBOLS=SOL/USDT,XRP/USDT`
- `QOUNT_TIMEFRAME=5m`
- `QOUNT_CANDIDATE_TREND_TIMEFRAME=1h`
- `QOUNT_CONTRACT_LEVERAGE=3`
- `QOUNT_CONTRACT_MARGIN_MODE=isolated`

当前策略仍然是：

`closed 5m bar -> snapshot -> candidate filter -> AI -> risk -> execute -> review`

这意味着它不是 tick 级趋势跟踪，也不是小时级开平仓系统。主决策周期是闭合 5m bar，1h 只作为趋势背景。

最近一次现场 review 结果显示：

- 近期可复盘样本里，大量 `hold` 是合理 `good_hold`
- 真正 `actionable` 样本仍少
- entry / close / management 的差异需要更细切片才能判断
- 当前收益瓶颈不应被粗暴归因为“交易太少”

## 必须先修的前置问题

### 持仓入场价来源不稳定

现场验证发现，Binance futures 的 `fetch_balance()` 返回的 `positions` 里可能没有：

- `entryPrice`
- `markPrice`
- `leverage`
- `marginType`
- `liquidationPrice`

但 `fetch_positions()` 可以拿到这些字段。

这对后续仓位管理是硬前置。因为下面这些逻辑都依赖真实入场价：

- 当前持仓收益率
- 原始 TP/SL 是否命中
- 浮盈峰值和回撤
- 分批止盈触发
- 保本止损
- R 倍数和 MAE/MFE review

如果不先修这个，后面做移动止盈或分批减仓会出现两个问题：

- 明明已有浮盈，系统算不出收益率
- review 看起来有数据，但实际基准价为空或错误

### 设计处理

应该把 futures 持仓快照统一收敛为：

- 优先 `fetch_positions(resolved_symbols)`
- `fetch_balance().info.positions` 只作为余额和可用保证金来源
- `PositionSnapshot.average_entry_price` 必须尽量填上
- `PositionSnapshot.mark_price` 优先用交易所 mark，缺失时才 fallback 到 snapshot last close

代码落点：

- `src/qount/market.py`
- `src/qount/analytics.py`
- `tests/test_exchange_throttling.py`
- `tests/test_strategy_optimization.py`

验收标准：

- live snapshot 中当前持仓 `average_entry_price` 不再是 `null`
- `live_status(include_exchange=True)` 的 position 能展示 entry、mark、liq、margin mode
- management TP/SL 和 trailing profit 在有持仓时都能拿到 `current_position_return_pct`

## 方案 1：扩展 review 切片

### 是否应该做

应该最先做。

原因不是它最赚钱，而是它最低风险。它不改变下单，只提高判断能力。当前系统已经有 `hold/actionable/by_context/blocked_sell`，但还不足以回答这些问题：

- 是 entry 差，还是 close 差？
- 是平早了，还是平晚了？
- 是没有保护浮盈，还是本来没有浮盈？
- 加仓到底是在顺势扩大优势，还是追高追低？
- 反手到底减少亏损，还是制造 churn？
- 被挡掉的 short/add/reverse 是保护系统，还是错过机会？

### 新增切片

建议在 `signal-review` 增加这些维度：

- `decision_lifecycle`
  - `fresh_entry`
  - `add_position`
  - `management_hold`
  - `partial_reduce`
  - `full_close`
  - `reverse_close`
  - `reverse_entry`
  - `idle_hold`
- `exit_source`
  - `ai_close`
  - `risk_take_profit`
  - `risk_stop_loss`
  - `trailing_profit_retrace`
  - `partial_take_profit`
  - `breakeven_stop`
  - `protective_exchange_tp`
  - `protective_exchange_sl`
- `blocked_group`
  - `blocked_entry`
  - `blocked_add`
  - `blocked_reverse`
  - `blocked_close`
  - `blocked_sell`

### 新增指标

建议新增这些 review 指标：

- `planned_risk_pct_of_equity`
  - 按开仓时 `size_pct * leverage * (stop_loss_pct + cost_pct)` 估算
- `realized_R`
  - 平仓结果 / 计划亏损
- `future_R`
  - horizon 之后方向结果 / 计划亏损
- `mfe_pct`
  - 入场后若干 bar 内最大有利波动
- `mae_pct`
  - 入场后若干 bar 内最大不利波动
- `giveback_pct`
  - 最大有利波动减最终锁定收益
- `late_exit_giveback_pct`
  - 管理层继续 hold 以后回吐掉的浮盈
- `early_exit_missed_pct`
  - close 以后原方向继续走出的空间

### 评审结论

这个方案风险最低，优先级最高。它不应该等加仓或分批减仓以后再做，因为没有这些切片，后续每个新规则都会变成凭感觉调参。

### 不应做的事

不要一开始就做复杂可视化，也不要把 review 直接变成回测引擎。第一步只要把 journal 已有 snapshot、risk verdict、order 和未来 K 线串起来即可。

## 方案 2：真正按 SL 反推仓位

### 是否应该做

应该做，而且优先级高。

当前参数里有：

- `QOUNT_MAX_RISK_PER_TRADE_PCT=0.01`
- `QOUNT_MAX_ENTRY_SIZE_PCT=0.30`
- `QOUNT_CONTRACT_LEVERAGE=3`
- `QOUNT_MIN_OPEN_SIZE_PCT=0.10`

但当前风险层更像是在控制最大开仓比例，并没有严格按 `stop_loss_pct` 反推仓位。结果是：

- 如果 SL 很宽，实际最大亏损可能超过 1% equity
- 如果 SL 很窄，风险预算又没有被有效利用
- `max_risk_per_trade_pct` 容易变成“看起来有，但没有真正控制风险”的配置

### sizing 公式

在 futures 模式下，`size_pct` 是保证金占权益比例，名义仓位是：

`notional = equity * size_pct * leverage`

如果止损距离是 `stop_loss_pct`，再加一轮估算交易成本 `cost_pct`，则单笔账户风险约为：

`risk_pct_of_equity = size_pct * leverage * (stop_loss_pct + cost_pct)`

所以反推：

`max_size_pct_by_risk = max_risk_per_trade_pct / (leverage * (stop_loss_pct + cost_pct))`

最终开仓比例应该是：

`final_size_pct = min(ai_size_pct, max_entry_size_pct, max_size_pct_by_risk)`

然后再检查：

- 是否低于 `QOUNT_MIN_OPEN_SIZE_PCT`
- 是否低于交易所最小名义仓位
- 是否超过 free margin
- 是否因为最小名义仓位而突破风险预算

### 推荐规则

新增配置：

- `QOUNT_RISK_SIZING_ENABLE=true`
- `QOUNT_RISK_SIZING_INCLUDE_COST=true`
- `QOUNT_MIN_EFFECTIVE_STOP_LOSS_PCT=0.005`
- `QOUNT_MAX_EFFECTIVE_STOP_LOSS_PCT=0.03`

规则：

1. 新开仓必须有有效 `stop_loss_pct`。
2. `stop_loss_pct` 先归一到 `[0.005, 0.03]`。
3. 用上面的公式反推 `max_size_pct_by_risk`。
4. 如果交易所最小名义仓位要求导致风险超过 `max_risk_per_trade_pct`，拒单，而不是强行抬仓。
5. `QOUNT_MIN_OPEN_SIZE_PCT` 只能在不突破风险预算时生效。

### 示例

账户权益 `160 USDT`，杠杆 `3x`，风险预算 `1%`。

如果 `stop_loss_pct=0.01`，成本按 `0.0012`，则：

`max_size_pct = 0.01 / (3 * 0.0112) = 0.2976`

这接近当前 `QOUNT_MAX_ENTRY_SIZE_PCT=0.30`，合理。

如果 `stop_loss_pct=0.03`，则：

`max_size_pct = 0.01 / (3 * 0.0312) = 0.1068`

这意味着宽止损不能再开 30% 保证金仓位。

### 评审结论

这个方案应该在分批减仓之前落地。因为分批止盈解决的是“赚了以后怎么处理”，而 SL sizing 解决的是“错了最多亏多少”。后者是系统安全底座。

### 主要风险

- 如果账户太小、交易所最小名义仓位太高，可能导致很多单被拒。
- 如果模型给的 SL 太小，仓位会被放大到上限，需要 `MIN_EFFECTIVE_STOP_LOSS_PCT` 防止虚假窄止损。
- 如果模型给的 SL 太大，仓位会被压得很小，需要 review 判断是否影响收益。

## 方案 3：分批减仓与移动止盈

### 是否应该做

应该做，但不要第一步就做复杂版本。

当前已经有：

- 原始 TP/SL 回读
- 交易所侧 reduceOnly TP/SL
- 浮盈峰值回撤保护

但当前管理仍偏“全平 / 不动”：

- `close` 是平整个当前仓位
- 没有 partial reduce
- 没有保本止损
- 交易所侧保护单初始挂好后，不会根据剩余仓位动态调整

这会导致两个问题：

- 有浮盈但趋势未坏时，全平可能早
- 趋势继续走但中间回撤时，不减仓可能晚

### 第一阶段规则：风控驱动，不改 AI schema

第一阶段不让 AI 输出 `partial_reduce`，由 risk management 确定性触发。

建议保持 AI action 仍然是：

- `buy`
- `sell`
- `hold`
- `close`

内部扩展 `RiskVerdict`：

- 增加 `close_fraction`
- 默认 `1.0`
- 当 `final_action=close` 且 `close_fraction < 1.0` 时，executor 做部分平仓

这样可以避免 prompt/schema 一起变复杂。

推荐配置：

- `QOUNT_PARTIAL_TAKE_PROFIT_ENABLE=true`
- `QOUNT_PARTIAL_TAKE_PROFIT_TRIGGER_PCT=0.012`
- `QOUNT_PARTIAL_TAKE_PROFIT_STEP_PCT=0.012`
- `QOUNT_PARTIAL_TAKE_PROFIT_FRACTION=0.50`
- `QOUNT_BREAKEVEN_STOP_BUFFER_PCT=0.0012`
- `QOUNT_PARTIAL_TAKE_PROFIT_MAX_TIMES=2`

触发逻辑：

1. 持仓收益率 `current_position_return_pct >= 0.012`。
2. 当前 open run 没做过 partial reduce。
3. 当前 5m 和 1h 没有明显反向信号。
4. 平掉 50%。
5. 剩余仓位 stop 移到保本加成本缓冲。
6. 记录 runtime state，避免重复分批。

runtime state key：

- `partial_tp_done:{mode}:{exchange}:{market_type}:{symbol}:{open_run_id}`
- `breakeven_stop_armed:{mode}:{exchange}:{market_type}:{symbol}:{open_run_id}`

### 第二阶段规则：移动止损 / 移动止盈

第二阶段再做动态保护单调整。

触发逻辑：

- 浮盈达到 `QOUNT_TRAILING_PROFIT_ARM_PCT`
- 每根闭合 bar 更新 peak
- 若 peak 回撤超过 `QOUNT_TRAILING_PROFIT_RETRACE_PCT`，平剩余仓位
- 如果已经 partial reduce，则 trailing 只管理剩余仓位

交易所侧处理：

1. partial reduce 前取消本系统旧保护单。
2. 执行 reduceOnly market 部分平仓。
3. 按剩余数量重挂 TP/SL。
4. 如果重挂失败，优先保护剩余仓位，必要时平掉剩余仓位。

### 评审结论

应该做，但要排在 SL sizing 之后。否则部分止盈可能掩盖首仓风险失控的问题。

### 主要风险

- 账户和仓位太小，50% partial 可能低于交易所最小数量。
- 多一次 market reduce 会多一次手续费和滑点。
- 保护单取消 / 重挂失败时，必须有应急逻辑。
- 如果触发阈值太近，会把 5m 小噪音当成利润管理。

## 方案 4：加仓独立规则

### 是否应该做

应该做，但必须后置。

当前 prompt 说 `buy=open or add to long`、`sell=open or add to short`，但实际风控没有清晰区分：

- fresh entry
- add position
- reverse entry

如果继续共用一套门槛，会出现两个问题：

- 加仓可能变成追涨杀跌
- review 里看不清 entry 和 add 谁贡献了亏损

### 推荐加仓规则

新增配置：

- `QOUNT_ADD_POSITION_ENABLE=false`
- `QOUNT_ADD_MIN_POSITION_RETURN_PCT=0.006`
- `QOUNT_ADD_MIN_EXPECTED_EDGE_PCT=0.003`
- `QOUNT_MAX_ADD_SIZE_PCT=0.08`
- `QOUNT_ADD_COOLDOWN_BARS=3`
- `QOUNT_MAX_TOTAL_POSITION_SIZE_PCT=0.30`

触发条件：

1. 已有同方向持仓。
2. 当前持仓浮盈至少 `0.6%`。
3. 1h trend bias 与持仓方向一致。
4. 最新 closed 5m bar 不逆向。
5. `expected_edge_pct` 高于普通 fresh entry。
6. 加仓后总仓位不超过 `QOUNT_MAX_TOTAL_POSITION_SIZE_PCT`。
7. 加仓后按合并仓位重新计算计划风险，不突破 `QOUNT_MAX_RISK_PER_TRADE_PCT`。

加仓尺寸：

`add_size_pct = min(ai_size_pct, QOUNT_MAX_ADD_SIZE_PCT, remaining_total_size_budget, risk_budget_remaining)`

### 评审结论

不应第一批上线。它的收益上限更高，但也最容易把一个原本对的仓位变成重仓回撤。必须等 review 能区分 `fresh_entry` 和 `add_position` 后再开。

## 方案 5：反手独立规则

### 是否应该做

应该做，但默认不做同一根 bar 直接反手。

当前已有保护：

- opposite position 会被 `opposite_position_open_requires_close` 拦住
- 有 `flip_cooldown_bars`
- 有 `same_symbol_reentry_cooldown_bars`

这些保护牺牲了速度，但避免了 5m 噪音下频繁多空切换。

### 推荐反手模式

新增配置：

- `QOUNT_REVERSE_MODE=pending_next_bar`
- `QOUNT_REVERSE_MIN_CONFIRM_BARS=1`
- `QOUNT_REVERSE_MIN_EXPECTED_EDGE_PCT=0.004`
- `QOUNT_REVERSE_ALLOW_COOLDOWN_BYPASS=false`

流程：

1. 当前有 long，出现强 short adverse signal。
2. risk 层先把 `hold` 或 AI close 转成 `close`，平掉现有仓位。
3. 写入 `pending_reverse:{symbol}`，记录目标方向、bar timestamp、原因。
4. 下一根 closed 5m bar 仍确认反向，才允许开反向仓。
5. 反向开仓必须重新通过 SL sizing、trend conflict、edge 和 free margin 检查。

只有在未来 review 明确证明错过太多强反转时，才考虑：

- `QOUNT_REVERSE_MODE=same_bar_strict`
- 同一 run close 后立刻反向开仓

### 评审结论

当前不建议 same-bar reverse。5m 策略不是 tick 级，直接反手很容易提高 `flip_rate`。更稳妥的是 pending next bar，牺牲 5 分钟速度换来更少 churn。

## 推荐实施顺序

### 阶段 0：数据源修复

目标：

- futures position 必须有 entry price
- live overview 与 snapshot 的持仓口径一致

改动：

- `market.py` 使用 `fetch_positions()` 补 futures 持仓
- `analytics.py` 使用同一套 position normalization
- 增加测试覆盖 `fetch_balance` 缺 entryPrice、`fetch_positions` 有 entryPrice 的场景

验收：

- 当前 XRP live position 的 `average_entry_price` 不再为空
- management return 计算可用

### 阶段 1：review 切片

目标：

- 先能量化问题，不先下单改行为

改动：

- `review.py` 增加 lifecycle / exit_source / MFE / MAE / giveback / planned risk
- dashboard 只展示摘要，不先做复杂 UI

验收：

- `signal-review` 能输出 `fresh_entry/add_position/partial_reduce/full_close/reverse` 等切片
- 能区分 `early_exit` 和 `late_exit`

### 阶段 2：SL sizing

目标：

- 让 `QOUNT_MAX_RISK_PER_TRADE_PCT` 成为真实约束

改动：

- `risk_engine.py` 在 open action 中按 SL 反推 `final_size_pct`
- 交易所最小名义仓位不得突破风险预算
- `RiskVerdict.reasons` 记录 `risk_sized_down` 或 `risk_budget_below_exchange_minimum`

验收：

- 每个 approved open 都有 `planned_risk_pct_of_equity <= max_risk_per_trade_pct`
- 若达不到交易所最小名义仓位，拒单而不是强行开仓

### 阶段 3：分批减仓 / 保本保护

目标：

- 解决“有浮盈但不锁一部分”的问题

状态：多次阶梯 partial 已落地，仍不开放 add/reverse。

改动：

- `RiskVerdict` 增加 `close_fraction`
- `executor.py` 支持 futures partial reduce
- partial reduce 后重挂剩余仓位保护单
- 剩余 stop 迁移到保本缓冲位置
- 执行成功后写入 runtime state，失败不误标

验收：

- 达到触发阈值时只平部分仓位
- 剩余仓位有新的 reduceOnly 保护单
- review 能看到 `partial_reduce` 的结果
- 重挂保护单失败时，应急平掉剩余仓位

### 阶段 4：加仓

目标：

- 只在盈利顺势时扩大仓位

改动：

- risk 层区分 `fresh_entry` 和 `add_position`
- add 使用更高 edge 门槛和独立 cooldown
- add 后重算总风险和保护单

验收：

- 加仓只发生在已有浮盈同方向
- `add_position.avg_net_edge_pct` 不低于 fresh entry

### 阶段 5：反手

目标：

- 趋势真的反转时能更及时从多到空或从空到多

改动：

- pending reverse runtime state
- 下一根 bar 确认后开反向仓
- review 增加 `reverse_close` / `reverse_entry`

验收：

- `flip_rate` 不恶化
- `reverse_entry.avg_net_edge_pct` 为正
- 没有同 symbol 连续噪音反手

## 参数建议

初始参数建议：

```bash
QOUNT_RISK_SIZING_ENABLE=true
QOUNT_RISK_SIZING_INCLUDE_COST=true
QOUNT_MIN_EFFECTIVE_STOP_LOSS_PCT=0.005
QOUNT_MAX_EFFECTIVE_STOP_LOSS_PCT=0.03

QOUNT_PARTIAL_TAKE_PROFIT_ENABLE=true
QOUNT_PARTIAL_TAKE_PROFIT_TRIGGER_PCT=0.012
QOUNT_PARTIAL_TAKE_PROFIT_STEP_PCT=0.012
QOUNT_PARTIAL_TAKE_PROFIT_FRACTION=0.50
QOUNT_PARTIAL_TAKE_PROFIT_MAX_TIMES=2
QOUNT_BREAKEVEN_STOP_BUFFER_PCT=0.0012

QOUNT_ADD_POSITION_ENABLE=false
QOUNT_ADD_MIN_POSITION_RETURN_PCT=0.006
QOUNT_ADD_MIN_EXPECTED_EDGE_PCT=0.003
QOUNT_MAX_ADD_SIZE_PCT=0.08
QOUNT_ADD_COOLDOWN_BARS=3
QOUNT_MAX_TOTAL_POSITION_SIZE_PCT=0.30

QOUNT_REVERSE_MODE=pending_next_bar
QOUNT_REVERSE_MIN_CONFIRM_BARS=1
QOUNT_REVERSE_MIN_EXPECTED_EDGE_PCT=0.004
QOUNT_REVERSE_ALLOW_COOLDOWN_BYPASS=false
```

## 总体评审

### 合理的部分

- `review` 先行是正确的，因为现在最缺的是判断粒度，不是更多规则。
- SL sizing 必须做，因为否则 `max_risk_per_trade_pct` 不是硬风险约束。
- 分批减仓适合当前小账户合约场景，可以减少“有浮盈但全部回吐”的体验问题。
- 加仓和反手有价值，但应该被独立切片、独立门槛约束。

### 不合理或需要克制的部分

- 不应该让 AI 直接输出复杂的 `partial_reduce/add/reverse` schema。第一版应由 risk 层 deterministic 管理。
- 不应该先上 same-bar reverse。当前 5m 策略不适合过快反手。
- 不应该让交易所最小名义仓位覆盖风险预算。小账户不够下单时，拒单比突破风险更正确。
- 不应该一次性开放加仓和分批减仓，否则 review 很难判断收益变化来自哪一层。

### 最大工程风险

- 保护单重挂失败：partial reduce 后必须保证剩余仓位不是裸仓。
- entry price 缺失：所有 management 逻辑都依赖这个前置修复。
- 小仓位精度：部分减仓后数量可能低于 Binance 最小量。
- review 误读：短期样本仍小，不能因为几笔 add/reverse 就调整一堆参数。

## 最终建议

推荐按下面顺序执行：

1. 修 futures position entry price。
2. 扩展 review 切片。
3. 上 SL risk sizing。
4. 上多次阶梯 partial reduce + breakeven/trailing protection。
5. 观察至少 50 到 100 条 clean completed live 样本。
6. 再决定是否打开 add。
7. 最后再决定是否从 pending reverse 升级到更激进的 reverse。

如果只做一件事，先做 `entry price + review 切片`。如果做两件事，再加 `SL sizing`。分批减仓、加仓、反手都应该建立在这两个基础上。
