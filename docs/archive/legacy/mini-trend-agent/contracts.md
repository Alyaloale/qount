# MiniTrend Agent Contracts

## 原则

- 所有跨模块数据用 JSON-compatible dataclass / dict。
- LLM 输出必须是 `report` 或 `proposal`，不能是 `order`。
- 执行层只接受 `ExecutionPlan`，且只能由确定性 `RiskGate` 放行后生成。
- schema 变更必须 bump `schema_version`。

## SignalResult

```json
{
  "schema_version": 1,
  "strategy": "MiniTrend-5",
  "bar": "2026-07-06",
  "universe": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"],
  "gate": {
    "risk_on": false,
    "btc_close": 64023.6,
    "btc_sma200": 74615.83,
    "breadth": 0.2
  },
  "targets": {
    "BTCUSDT": 0.0,
    "ETHUSDT": 0.0
  },
  "diagnostics": {
    "vol_target": 0.015,
    "rebalance_band": 0.35
  }
}
```

## RiskResult

```json
{
  "schema_version": 1,
  "allow": false,
  "halt": false,
  "reasons": [
    "risk_off_master_gate",
    "target_below_min_notional"
  ],
  "limits": {
    "capital_cap_usdt": 400.0,
    "max_gross": 1.0,
    "max_daily_loss_pct": 0.02,
    "max_weekly_loss_pct": 0.05
  },
  "blocked_symbols": [
    {
      "symbol": "BTCUSDT",
      "target_usdt": 7.5,
      "min_notional_usdt": 10.0
    }
  ]
}
```

## ExecutionPlan

```json
{
  "schema_version": 1,
  "mode": "dry",
  "armed": false,
  "orders": [
    {
      "symbol": "BTCUSDT",
      "side": "buy",
      "type": "market",
      "quote_qty": 25.0,
      "reduce_only": false,
      "reason": "target_rebalance"
    }
  ],
  "no_order_reasons": [
    "not_armed",
    "risk_blocked"
  ]
}
```

## ExecutionReport

```json
{
  "schema_version": 1,
  "mode": "live",
  "ts": "2026-07-07T10:26:07Z",
  "orders_submitted": 0,
  "fills": [],
  "positions_after": [],
  "state_write": "state/mini_trend/live/latest.json",
  "alerts": []
}
```

## Scorecard

所有模式都要尽量输出同一结构。字段缺失必须写进 `missing_fields`。

```json
{
  "schema_version": 1,
  "strategy": "MiniTrend-5",
  "mode": "paper",
  "window": {
    "start": "2026-07-01",
    "end": "2026-07-31"
  },
  "metrics": {
    "total_return_pct": 0.0,
    "max_drawdown_pct": 0.0,
    "fee_to_notional_pct": 0.0,
    "order_count": 0,
    "min_notional_coverage": 1.0,
    "stop_reentry_count": 0,
    "unmanaged_position_count": 0,
    "schema_error_count": 0
  },
  "blocked_symbols": [],
  "missing_fields": [],
  "verdict": "pass"
}
```

允许的 `verdict`：

- `pass`
- `watch`
- `block`

## AgentReport

LLM agent 只能输出这种形态：

```json
{
  "schema_version": 1,
  "agent": "OpsAuditAgent",
  "ts": "2026-07-07T10:30:00Z",
  "severity": "info",
  "summary": "No unmanaged positions. No order submitted.",
  "findings": [
    {
      "kind": "risk",
      "message": "Risk-off master gate blocked all entries.",
      "evidence": {
        "btc_to_sma": -0.142
      }
    }
  ],
  "proposals": []
}
```

允许的 `severity`：

- `info`
- `watch`
- `halt_recommended`

不允许的字段：

- `place_order`
- `override_risk`
- `set_live_enable`
- `change_env`
- `execution_plan`
- `target_weights`

## Proposal

LLM 只能提出 research proposal：

```json
{
  "kind": "research_proposal",
  "title": "test vol_target 0.020 in paper",
  "hypothesis": "Higher vol target may improve return without breaking maxDD gate.",
  "required_artifacts": ["backtest_scorecard", "paper_scorecard"],
  "live_allowed": false
}
```

`live_allowed` 必须固定为 `false`。任何非 false 都按 schema error 处理。

## Agent 调用边界

| Agent | 输入 | 输出 | 能否影响 live |
| --- | --- | --- | --- |
| `ResearchAgent` | backtest / paper artifacts | research proposal | 否 |
| `RiskReviewAgent` | `RiskResult` | explanation | 否 |
| `OpsAuditAgent` | fills / positions / latest state | audit findings | 可建议 halt，不能执行 |
| `RedTeamAgent` | proposal + artifacts | objections | 否 |
| `DailyBriefAgent` | all reports | daily summary | 否 |

`halt_recommended` 只触发通知。真正 halt 由确定性规则或人工执行。

## Prompt 约束

每个 LLM agent 的 system prompt 必须包含：

```text
You are not allowed to generate orders, change live settings, or override risk gates.
Return only JSON matching AgentReport.
If evidence is missing, say so in findings and do not infer a trade.
```

LLM API 失败时：

- report 标记为 `agent_unavailable`。
- live 交易不因 agent 不可用而新增风险。
- 如果该 agent 是审计必需项，则 `RiskGate` 可选择 fail closed。
