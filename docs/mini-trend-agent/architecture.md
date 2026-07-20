# MiniTrend Agent 架构

## 一句话

交易核心必须是确定性程序；LLM 多 agent 只做研究、审计、解释和异常分诊。下单路径只接受
结构化、可验证、可重放的 JSON。

v0.2 默认实现只覆盖 `spot + long/cash`。swap、short gate、carry 只能作为后续独立 slice，
不能和最小闭环一起开发。

## 数据流

```text
market data
  -> signal core
  -> target weights
  -> risk gate
  -> execution plan
  -> broker adapter
  -> fills / positions / state
  -> audit agents / reports
```

LLM agent 只读 `market data / targets / risk result / fills / state / artifacts`，输出
`report` 或 `proposal`。任何 `proposal` 都必须先进入 research / paper，不直接进入 live。

初期主循环不依赖 LLM：

```text
signal core -> risk gate -> execution plan
```

LLM 报告是旁路：

```text
state / fills / scorecard -> LLM agents -> reports
```

## 代码模块建议

新增包：`src/qount/mini_trend/`

建议文件：

| 文件 | 职责 | 约束 |
| --- | --- | --- |
| `config.py` | `MiniTrendConfig`、默认 universe、风控阈值 | 只放配置 dataclass，不读环境 |
| `market.py` | 交易所规则、K 线、价格、账户快照的薄模型 | 不做策略判断 |
| `signals.py` | SMA、ATR、breadth、目标权重 | 纯函数，无 IO |
| `risk.py` | 最小名义、gross、亏损、stop latch、live guard | 只返回 allow/block 和 reasons |
| `execution.py` | 目标权重到订单计划、rebalance band、rounding | 不直接调 ccxt |
| `state.py` | state JSON 读写、schema version、atomic write | 不含策略逻辑 |
| `scorecard.py` | 统一计算回测 / paper / dry 指标 | 不排序、不调参 |
| `agents.py` | agent report/proposal contract glue | 不进下单决策 |

入口保持薄：

| 文件 | 职责 |
| --- | --- |
| `scripts/research/mini_trend_backtest.py` | 参数解析、调用纯函数、写 artifact |
| `scripts/desktop/mini_trend_um_paper.py` | 当前只读canonical输入并追加paper journal；没有私有API或下单模式 |
| future independent dry/live entry | 尚未实现；不得复用旧X4/C×D执行器 |
| `scripts/desktop/mini_trend_cron.sh` | venv/env/log wrapper |

测试拆分：

| 文件 | 重点 |
| --- | --- |
| `tests/test_mini_trend_signals.py` | SMA/breadth/权重确定性 |
| `tests/test_mini_trend_risk.py` | min notional、日亏损、stop latch |
| `tests/test_mini_trend_execution.py` | rounding、rebalance band、no duplicate orders |
| `tests/test_mini_trend_scorecard.py` | maxDD、费用、blocked symbols、stop re-entry |
| `tests/test_mini_trend_agents.py` | agent JSON contract，不测模型质量 |

## Agent 分层

### Deterministic Agents

这些不是 LLM，而是确定性组件：

- `SignalCore`：计算候选权重。
- `RiskGate`：硬拒绝或放行。
- `ExecutionPlanner`：生成订单计划。
- `StateReconciler`：对账交易所仓位和本地状态。

### LLM Agents

这些只读、只建议：

- `ResearchAgent`：读 backtest / paper artifact，提出下一轮研究假设。
- `RiskReviewAgent`：解释本轮 risk gate 为什么 block / allow。
- `OpsAuditAgent`：检查 fills、stop、re-entry、费用、外部成交。
- `RedTeamAgent`：反驳研究假设，找过拟合和成本漏计。
- `DailyBriefAgent`：把当天状态压缩成日报。

### Supervisor

`Supervisor` 不下单，只汇总：

```text
signal targets + risk gate + execution result + agent reports
  -> status: ok | watch | halt_recommended
```

真正停机由确定性 `RiskGate` 或人工操作完成。

## 状态目录

```text
state/mini_trend/
  paper/latest.json
  paper/snapshots.jsonl
  paper/scorecard.json
  live/latest.json
  live/orders.jsonl
  live/stops.json
  live/latches.json
  live/scorecard.json
  reports/daily/*.json
  research_runs/<timestamp>/
```

每个 state JSON 必须带：

- `schema_version`
- `ts`
- `mode`
- `strategy`
- `config_hash`
- `exchange`
- `armed`
- `targets`
- `risk`
- `orders`
- `positions`
- `scorecard_ref`

## 运行模式

| 模式 | 行为 |
| --- | --- |
| `backtest` | 离线 K 线，不读私有 API，不下单 |
| `paper` | 读公开行情，内部撮合，写 paper state |
| `dry` | 读真实账户和行情，生成订单计划，不下单 |
| `live` | 必须 armed + risk allow + exchange preflight，全链路审计 |

默认模式必须是 `dry` 或 `paper`，不能默认 live。
