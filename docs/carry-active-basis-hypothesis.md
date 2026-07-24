# Carry Leg 新假设: Active Basis-Capture State Machine

> **状态**：proposal｜**权威**：L3 研究草稿（R5）｜**最后更新**：2026-07-23
> **本文回答**：carry 腿的 Active Basis-Capture 状态机新假设（不复活旧静态 carry）。
> **TL;DR**：可做 historical/discovery，不进 paper/live；R0-DATA/collateral/tail 未闭合前不作候选证据。

状态: proposal (不复活旧静态 carry 版本)
日期: 2026-07-23
前置: R0-DECISION v6 已将 carry 腿降级为 REVISE（kill test 3 FAIL: R0-DATA 不可用）。Round 2 修正后 carry Standalone NAV 1.38x（cost_incomplete=True，collateral/tail 未估算），历史正 funding 可能存在可研究的风险溢价，但尚未证明 basis-carry 账户模型可执行。

## 1. 旧版本为何失败（历史记录）

静态 carry (long spot + short perp, hold-to-convergence) 的 R0-RUNTIME 旧版本结果（Round 0, b90c6d...）:
- Signal NAV 0.99x (-0.94%): spot 和 perp 日收益几乎完全抵消,无方向性收益
- Standalone NAV 0.76x (-23.7%): 4 腿 entry/exit 费用 + legging + funding 吃掉全部本金
- Kill test `standalone_nav_non_positive_after_tail` FAIL

注意：Round 2 修正后（gross≤1, additive NAV, basis 收敛信号, collateral/tail="unavailable"），carry Standalone NAV 为 1.38x，但 `cost_incomplete=True`。旧版本的 0.76x 已被取代，但作为历史记录保留。

根因: 静态持仓不捕捉 basis 时序动态--它只在 basis 恒定收敛时盈利,但实际 basis 随 funding 波动和 market regime 剧烈变化。

## 2. 新假设: Active Basis-Capture State Machine

### 2.1 经济机制

basis = perp_price - spot_price (正 = perp 溢价,负 = perp 折价)

新假设: **basis 的条件均值回归在特定 regime 下可被捕捉**,具体:
- 当 funding rate 持续为正且偏高时,perp 溢价 (正 basis) 扩大,随后 funding 下降导致 basis 收缩
- 当 funding rate 为负时,反向操作
- 关键区别: 不是持有至到期,而是**在 basis 扩张时建仓,在 basis 收缩时平仓**

### 2.2 状态机

```
State WAIT:
  - monitor funding rate 7d MA and basis z-score
  - when |funding_ma_7d| > threshold AND basis_zscore > entry_z:
    -> State OPEN
  - else: stay flat (no position)

State OPEN:
  - hold delta-neutral (long spot + short perp if basis > 0, reverse if < 0)
  - exit when:
    a) basis_zscore reverts to |z| < exit_z (profit taking)
    b) funding flips sign (regime change stop-loss)
    c) max holding period reached (time stop)
    d) basis expands further beyond adverse_z (adverse move stop)
  -> back to State WAIT
```

### 2.3 与旧版本的关键区别

| 维度 | 旧版本 (静态) | 新版本 (active) |
|---|---|---|
| 建仓时机 | 随机/固定 | funding + basis z-score 条件触发 |
| 持仓时长 | 到期/无限 | 条件平仓 (profit-take / stop-loss / time-stop) |
| Funding 处理 | 被动承受 | 主动选择 funding 有利的时段 |
| 成本结构 | 固定 4 腿 turnover | 动态: 仅在信号触发时交易 |
| 尾部风险 | 无保护 | adverse_z stop + time stop |

### 2.4 预登记主指标和 kill test

- 主指标: `cost_adjusted_standalone_executable_nav > 1.0` after active state machine
- Kill tests:
  1. `standalone_nav_non_positive_after_tail` (同旧)
  2. `signal_nav_non_positive` (如果信号 NAV 都不正,说明机制本身无 edge)
  3. `funding_signal_predictive_power_insufficient` (如果 funding 不能预测 basis 变化,机制前提不成立)
  4. `turnover_too_high` (如果状态机频繁切换,费用吃掉全部收益)

### 2.5 数据需求

- UM perp funding rate 历史 (已有: BTCUSDT 7119 条)
- UM perp + spot 日线 (已有: 2395 bars)
- 需要新增: basis 时序计算 (perp_close - spot_close) / spot_close

### 2.6 不做的事

- 不复活旧静态版本或调权重
- 不用组合净额掩盖 carry 腿的失败
- 不把 carry 塞进 Base 过滤器
- 不在没有 basis tail 审计时声称正 edge
- 真实多腿订单仍需独立 owner 授权

## 3. 下一步

1. 构建 basis z-score 和 funding regime 特征
2. 回测状态机 (funding_ma_7d threshold + basis_zscore entry/exit)
3. 用 R0-COST/NAV 的 carry 冻结成本模型计算 Standalone NAV
4. 如果通过 kill test,进入 R0-DECISION retain
5. 如果不通过,记录负证据,关闭此 family 变体
