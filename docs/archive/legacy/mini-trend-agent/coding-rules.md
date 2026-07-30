# MiniTrend 代码编写原则

## 目标

小、清楚、可测。不要把研究、执行、LLM、状态、交易所 IO 堆进一个文件。

## 文件大小约束

软限制：

- `src/qount/mini_trend/*.py`：单文件优先 < 300 行。
- `scripts/research/*.py`：优先 < 180 行。
- `scripts/desktop/*.py`：优先 < 220 行。
- 单个函数优先 < 60 行。

超过限制时优先拆纯函数，不先加类层级。

## 依赖原则

- live 路径只用当前基础依赖和 stdlib。
- LLM SDK / research ML / plotting 不进 live core。
- research-only 依赖走 optional extra。
- 交易所规则以 ccxt / exchangeInfo 运行时读数为准。
- 初版不新增 agent framework；agent 编排用普通函数和 JSON contract。

## 导入方向

允许：

```text
scripts/* -> src/qount/mini_trend/*
mini_trend/execution.py -> mini_trend/risk.py
mini_trend/risk.py -> mini_trend/config.py
```

禁止：

```text
src/qount/mini_trend/* -> scripts/research/*
src/qount/mini_trend/signals.py -> ccxt
src/qount/mini_trend/risk.py -> LLM client
LLM agent -> execution adapter
```

## 纯函数优先

优先形态：

```python
def target_weights(bars_by_symbol: Mapping[str, list[Bar]],
                   cfg: MiniTrendConfig) -> SignalResult:
    ...
```

避免：

```python
class MegaBot:
    def run_everything(self):
        ...
```

## State 写入

- 使用 atomic write：先写 `.tmp`，再 rename。
- JSONL 只 append 事件，不反复重写历史。
- `latest.json` 是面板源，不是唯一审计源。
- 所有订单事件必须进 `orders.jsonl`。

## 风控编码规则

- 风控默认 fail closed。
- 未知交易所规则 = block。
- 交易所仓位和本地状态冲突 = halt。
- filters / balances / positions 任一读取失败 = 不生成 live order。
- stop 成交后必须写 latch。
- latch 只由新的日线信号重置，不能被 cron tick 自动清掉。
- sell / close 不受 max order cap 限制，减险优先。
- spot 初版不允许 margin borrow；发现非零 borrow / liability 直接 halt。

## LLM 编码规则

- LLM client 放独立模块，默认不开启。
- LLM 输出先 JSON parse，再 schema validate。
- parse 失败只写 audit，不影响确定性交易。
- agent prompt 放短字符串或模板文件，不散落在业务逻辑里。
- agent 报告不得包含交易命令字段。

## 测试优先级

先写这些测试，再接 live：

1. target weights 在同输入下确定。
2. risk-off 时所有 long target 为 0。
3. min-notional below threshold 被 block。
4. rebalance band 内不下单。
5. target=0 全平不被 band 拦。
6. stop latch 后同日线目标不重开。
7. unknown position 触发 halt。
8. LLM malformed JSON 不影响 live 下单路径。
9. scorecard 缺字段时 verdict 不能是 `pass`。
10. spot liability 非零触发 halt。

## 实现切片

一次 PR / 一批改动只做一个 slice：

1. `signals + tests`
2. `risk + tests`
3. `execution + tests`
4. `scorecard + tests`
5. `paper runner`
6. `dry runner`
7. `LLM daily report`

不要在同一批里同时接交易所下单和 LLM。

## 命名

- 策略名：`MiniTrend-5`
- 包名：`qount.mini_trend`
- env prefix：`QOUNT_MINI_TREND_`
- state root：`state/mini_trend/`

不要复用 `QOUNT_X4_*` 表示新策略开关；避免和当前 X4/C×D 生产状态混判。
