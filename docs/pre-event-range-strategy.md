# PreEvent-Range 事件前区间高抛低吸策略（预登记合同）

> **状态**：draft / owner 已授权小额 canary（明确接受跳过 shadow 纪律）｜**权威**：本文 + current.md
> **合同版本**：`SmallAccount-PreEvent-Range-v0.1`｜**最后更新**：2026-07-27
> **本文回答**：FOMC（2026-07-30）发布前的震荡区间 fade 策略边界、风险预算、硬截止与执行方式。
> **TL;DR**：独立于 FOMC sleeve 的区间 fade 线；信号/尺寸纯函数化并有回归；执行为 plan-only CLI +
> owner 手工下单；上海时间 7/30 01:00 前强制全平，把干净现金账户交还给 FOMC 流程。

## 1. 定位与边界

- 独立策略线，**不复用**也**不污染** `SmallAccount-FOMC-RightSide-v0.2` 的状态、资格与证据。
- 与 FOMC sleeve 共用同一 200U 账户，因此互斥：本策略持仓期间不得进入 FOMC 流程；
  **硬截止**：上海时间 2026-07-30 01:00（UTC 2026-07-29T17:00）前必须全平回 CASH，
  截止前 30 分钟（`cash_buffer_minutes=30`）起信号层直接 `NO_TRADE`。
- owner 决定（2026-07-27）：接受本线跳过 shadow 晋级纪律，直接以小额 canary 执行；
  该豁免仅限本次 FOMC 前窗口，不构成先例，不改变其他线的晋级要求。

## 2. 冻结与信号（纯函数，见 `src/qount/small_account/range_signal.py`）

- 冻结一次、不可覆盖：`H0/L0` = 冻结时前 72 根完成 1h K 高/低极值；`ATR0` = 1h ATR(14)；
  `V20_15m` = 前 20 根完成 15m 成交量中位数。冻结文件含 sha256，重复 freeze 直接拒绝。
- 区间有效性：`H0-L0 >= 3.0 × ATR0`，否则 `NO_TRADE(range_too_narrow)`。
- 破位失效：任一完成 15m 收盘越过 `L0 - 0.25×ATR0` 或 `H0 + 0.25×ATR0` →
  双向 `NO_TRADE(range_broken)`，本区间作废，不重画。
- 入场触发（只用完成 K）：
  - 多：15m 最低触及 `L0 + 0.25×ATR0` 区域后收回区域之上，CLV ≥ 0.60；
  - 空：对称触及 `H0 - 0.25×ATR0` 后收回之下，CLV ≤ 0.40；
  - 成交量 ≥ 1.0 × `V20_15m`；计划入场价距触发 K 收盘 ≤ 0.10×ATR0 且在本侧半区间内。
- 结构止损：多 `L0 - 0.35×ATR0`，空 `H0 + 0.35×ATR0`（在破位线之外）。
- 目标：区间中轴 `(H0+L0)/2`；全成本净收益风险比 < 2.0R 时由尺寸层拒绝。

## 3. 风险与尺寸（复用 `small_account/risk.py`，参数不放松）

- canary 单笔全成本风险预算 5U（`first_live_risk_cap`，保护闭环验证前不升到 10U）；
- BTC USD-M 永续、one-way、isolated、杠杆 ≤5x、isolated margin ≤40U、名义 ≤200U；
- 24h 净亏 10U 停止；回撤 20U/32U/40U 阶梯与 FOMC 合同一致（同一账户共享）；
- 同一时间最多一笔持仓；止损后同方向冷却至少 2 根完成 15m K；同一次区间触碰只入场一次。

## 4. 执行方式（本版本为 plan-only）

- `scripts/operations/run_pre_event_range_plan.py`：`freeze` 冻结区间；`scan` 只读公开行情，
  输出双向信号状态与（ARMED 时）含止损/目标/数量/保证金/压力损失的完整计划 JSON；
  `orders_authorized=false`、`exchange_mutation_attempted=false`，**不调用任何私有 API、不下单**。
- 真实执行由 owner 依据 scan 计划手工完成：入场后**必须先挂交易所原生 STOP_MARKET 保护单**
  （数量=持仓、触发=计划止损价），保护单未确认前不加任何风险；到达目标或硬截止前手工平仓。
- 自动化受控执行（prepare/arm/switch 链）不在 v0.1 范围；若后续需要，按 fomc_live 模式另行实现并评审。

## 5. 记录

- 每次 freeze/scan 的 JSON 输出与实际成交截图由 owner 留存；结果计入 update-log；
  本线不产生任何 registry promotion 证据。
