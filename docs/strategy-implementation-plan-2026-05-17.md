# qount 策略可执行实施计划（2026-05-17）

这份文档不是讨论“方向大概应该怎样”，而是把当前主线收敛成一份**可以按阶段执行**的计划。

如果你当前想先看：

- 生产真实基线
- 当前 live 是否健康
- 当前持仓与当前主问题

先看：

- [live-baseline-and-strategy-current.md](live-baseline-and-strategy-current.md)

如果你想看更完整的长期设计 reasoning，配套看：

- [strategy-optimization-design.md](strategy-optimization-design.md)
- [fresh-entry-effect-check-2026-05-14.md](fresh-entry-effect-check-2026-05-14.md)

## 目标

当前目标不是“让系统看起来更活跃”，而是按下面顺序推进：

1. 先证明当前系统是否真的存在可持续正向边际
2. 再证明当前 review 口径不是在拟合 5m 噪声
3. 再压缩成本结构和交易宇宙
4. 必要时再比较 `gpt-5.4` 与 `gpt-5.4-mini` 是否真的有质量差异
5. 只有前面都站住后，才继续做现有工程阶段里的 explainability / fresh-entry / management 窄修

当前明确**不**以这些为第一优先级：

- 全局下调 `QOUNT_MIN_EXPECTED_EDGE_PCT`
- 再次整体放松 `candidate_filter`
- 重写 partial / breakeven / trailing / executor
- 提前推进 `add_position` / `reverse_entry`

## 本版修正

上一版计划更偏“如何安全迭代一个交易系统”，工程方法是对的，但它默认假设了一件当前还没被证明的事：

- **系统本身存在足够的 alpha，只是 entry / risk / management 还不够精细**

结合当前基线，这个假设现在不能直接成立。

当前更接近的现实是：

- `fresh_entry.avg_net_edge_pct = -0.20387`
- `actionable.avg_net_edge_pct = -0.11558`
- 大多数 `hold` 是合理 `hold`
- 少数真实出手样本扣掉成本后仍偏弱

所以这版计划要先回答两个更根本的问题：

1. 当前系统到底有没有正向预期，还是只是“风控把坏单挡住了，但好单本身不够多”？
2. 当前 `horizon-bars=3` 的 review 口径，到底是在评估 edge，还是在评估 15 分钟噪声？

## 为什么此前不是 `gpt-5.4`，以及这次为什么切到 `gpt-5.4`

这件事先分成**已确认事实**和**推断**。

### 已确认事实

本次改动前，生产实际生效值是：

- `QOUNT_AI_MODEL=gpt-5.4-mini`

而且这不是只在生产 `.env` 里偶然写成这样：

- 当时 `.env.example` 也是 `gpt-5.4-mini`
- 当时代码默认值也是 `gpt-5.4-mini`

我还直接从当前 relay 查了 `models`：

- `gpt-5.4` 可见
- `gpt-5.4-mini` 也可见

所以当时的事实是：

- **当前不是“relay 没有 5.4，所以只能用 mini”**

本次改动后，当前基线已经切到：

- `QOUNT_AI_MODEL=gpt-5.4`

### 当前没有被证明的事

仓库里没有我能找到的证据证明下面任何一条：

1. `gpt-5.4-mini` 在这个策略上比 `gpt-5.4` 更赚钱
2. `gpt-5.4` 曾做过系统性 A/B，然后因为收益不如 mini 才被拿掉
3. 当前选择 mini 的理由已经过严格策略验证

### 当前最合理的推断

基于此前代码和部署方式，最合理的推断是：

- `gpt-5.4-mini` 更像是**延迟 / 成本 / 调度稳定性**优先下的默认选择

这条推断和当前系统形态是吻合的：

- 5m 定时运行
- 4 symbols 顺序处理
- `AI_TIMEOUT_SECONDS=40`
- 当前 live 重点一直是“链路别卡死、别超时、别把 timer 拖垮”

但这仍然只是**工程推断**，不是已经证明的策略结论。

即使当前已经切到 `gpt-5.4`，下面这个问题仍然值得保留为受控验证项：

- `gpt-5.4` vs `gpt-5.4-mini` 的受控对照实验

在没有做这个对照之前，不应该把 `mini` 或 `5.4` 当成策略上绝对更优的既定事实。

## 冻结基线

这份计划的 frozen baseline 以 `2026-05-17 01:48 CST` 的生产 WSL 核查为准。

### 运行面

- `qount-runner.timer = active (waiting)`
- `preflight-live = 全绿`
- `runtime-status.halted = false`
- `ai_failure_streak = 0`

### live 配置

- `QOUNT_MARKET_TYPE=future`
- `QOUNT_TIMEFRAME=5m`
- `QOUNT_CANDIDATE_TREND_TIMEFRAME=1h`
- `QOUNT_SYMBOLS=SOL/USDT,XRP/USDT,BTC/USDT,ETH/USDT`
- `QOUNT_AI_MODEL=gpt-5.4`
- `QOUNT_CONTRACT_LEVERAGE=6`
- `QOUNT_MAX_OPEN_POSITIONS=3`
- `QOUNT_MAX_ENTRY_SIZE_PCT=0.30`
- `QOUNT_MAX_RISK_PER_TRADE_PCT=0.01`
- `QOUNT_MIN_EXPECTED_EDGE_PCT=0.0015`
- `QOUNT_MIN_OPEN_SIZE_PCT=0.10`
- `QOUNT_MIN_TAKE_PROFIT_PCT=0.015`

### 当前 review 基线

固定复查口径：

```bash
PYTHONPATH=src ./.venv/bin/python -m qount.main signal-review --limit 160 --horizon-bars 3 --threshold-pct 0.003
```

当前窗口结论：

- `reviewed = 140`
- `good_hold = 133`
- `flat actionable = 6`
- `missed_move = 1`
- `overall.avg_net_edge_pct = -0.00495`
- `actionable.avg_net_edge_pct = -0.11558`
- `fresh_entry.avg_net_edge_pct = -0.20387`

这意味着：

- 当前大多数 `hold` 不是问题
- 当前主问题仍然是 **fresh-entry 质量弱**
- 但这还**不能直接推出**：
  - 只要继续优化 entry 规则，系统就会盈利

### 当前 management 基线

当前代码存在明显不对称：

- 已有：
  - `management_profitable_long_momentum_cooldown_close`
- 没有：
  - 对称的 profitable short cooldown close

但当前这件事仍然不是第一优先级，因为最近主问题仍然是 fresh entry。

### 当前成本与执行基线

当前成本相关的几个硬事实是：

- 代码默认 `estimated_fee_pct = 0.0004`
- 代码默认 `estimated_slippage_pct = 0.0002`
- live executor 当前真实开平仓主路径使用的是 **market order**
  - [src/qount/executor.py](/Users/alyaloale/Code/qount/src/qount/executor.py)

也就是说，当前系统至少在自己的内部成本模型里，已经假设了相当薄的 post-cost cushion；而执行层也还没有把 maker-entry 当成当前基线能力。

## 执行原则

整个实施过程都遵守这 6 条：

1. 一次只动一层主逻辑。
2. 先补 review / explainability，再补放行。
3. 所有阶段都要保留 WSL 生产验证。
4. 不为了增加出手，放掉明显坏单。
5. 没拿到最小样本前，不下策略效果结论。
6. 每阶段都要有明确“继续 / 停止 / 回滚”条件。
7. 前置研究允许共享同一批历史窗口并行跑，但 live 交易轮次默认仍保持多 symbol 串行提交，不直接改成 4-symbol 并发下单。

## 前置阶段 0：先验证 review 口径是否可靠

### 目标

先确认当前 `signal-review --horizon-bars 3` 的结论是否稳定。

如果同一批样本在：

- `horizon=3`
- `horizon=6`
- `horizon=12`
- `horizon=24`

之间结论大幅翻转，那么当前优化方向不能继续依赖 `3-bar` 口径。

### 本阶段改动范围

- 默认**不改交易逻辑**
- 只允许补 review / backtest 报告脚本、文档、对照命令

### 本阶段具体任务

1. 固定 1-2 周历史窗口，分别跑：
   - `horizon-bars=3`
   - `horizon-bars=6`
   - `horizon-bars=12`
   - `horizon-bars=24`

2. 比较这些窗口下的稳定性：
   - `fresh_entry.avg_net_edge_pct`
   - `actionable.avg_net_edge_pct`
   - `by_lifecycle`
   - `by_hold_path`
   - `missed_move`

3. 输出统一对照表；如果现有 review 输出还不够，就先补一个轻量报告脚本。至少固定成下面这种格式：

   | horizon | fresh_entry.avg_net_edge_pct | actionable.avg_net_edge_pct | direction_consistency |
   | --- | ---: | ---: | --- |
   | 3 | -0.2039 | -0.1156 | 基线 |
   | 6 | ... | ... | 一致 / 不一致 |
   | 12 | ... | ... | 一致 / 不一致 |
   | 24 | ... | ... | 一致 / 不一致 |

4. 明确写出：
   - 哪些结论对窗口变化稳定
   - 哪些结论明显在随窗口漂移

### 本阶段验收

只有在下面任一条件满足后，才允许把这个口径继续拿去指导后面的策略判断：

1. 关键结论跨窗口方向一致
2. 或者明确证明当前 `3-bar` 口径不可靠，并据此把默认 review 窗口改掉

如果这一步做不出来，就停止继续调 entry 规则。

## 前置阶段 1：先压成本和简化交易宇宙

### 目标

在 current edge 未证明为正之前，先测试更宽容的成本 / 结构配置，而不是继续微调过滤规则。

这一步默认和**前置阶段 0**共享同一批历史窗口并行推进；但凡涉及 `horizon` 的最终解释，仍以阶段 0 的口径结论为准。

### 本阶段具体任务

1. 做一组**研究配置**，不直接改生产：
   - `QOUNT_CONTRACT_LEVERAGE=3`
   - `QOUNT_SYMBOLS=BTC/USDT,ETH/USDT`
   - 必要时 `QOUNT_MAX_OPEN_POSITIONS=2`

2. 用同一历史窗口比较：
   - 当前生产配置
   - `3x + BTC/ETH`
   - `3x + BTC/ETH + 更长 review horizon`

3. 固定比较口径时，不只看 `avg_net_edge_pct`，还要至少补齐：
   - `fresh_entry.win_rate`
   - `actionable.win_rate`
   - `fresh_entry.avg_win_pct`
   - `fresh_entry.avg_loss_pct`
   - `actionable.avg_win_pct`
   - `actionable.avg_loss_pct`
   - `avg_win / avg_loss ratio`

4. 做真实执行成本审计：
   - 当前 live 入口是 market order
   - 从 journal 的 `orders.raw_json.entry_price` 和同 run 的 `snapshots.snapshot_json` 提取下单时价格，计算真实滑点分布
   - 至少输出 `by_symbol` 的 `p50 / p90 / max slippage`
   - 明确真实滑点是否显著高于当前 `estimated_slippage_pct = 0.0002`

5. 只在拿到真实滑点分布后，再判断：
   - maker-entry feasibility 是否值得单开一条研发支线
   - 还是当前主要问题仍然是 alpha / risk，不是执行路径

### 本阶段明确不做

- 不马上把生产 live 改成 maker
- 不在这一阶段直接做 maker 改造
- 不先动 prompt
- 不因为 `3x` 看起来更稳就直接切生产

### 本阶段验收

只有当“简化宇宙 / 降杠杆”在 backtest / review 口径下没有明显恶化，才允许继续拿当前 4-symbol / 6x 作为唯一优化对象。

如果 `BTC/ETH + 3x` 明显更稳，就优先把它提升为 paper / research baseline，再决定是否进 live。

## 前置阶段 2（低优先级并行项）：做模型对照实验，不默认 mini 就是对的

### 目标

把下面这个问题从推测变成证据：

- 在同一数据、同一 prompt、同一 risk/executor 下，`gpt-5.4` 和 `gpt-5.4-mini` 的结果差异到底有多大？

这一步默认在**前置阶段 0**确定默认 review 口径后再启动；它不需要阻塞前置阶段 1，也不要求先于后续解释面/报告增强完成。

### 本阶段具体任务

1. 用相同历史窗口做对照：
   - `QOUNT_AI_MODEL=gpt-5.4`
   - `QOUNT_AI_MODEL=gpt-5.4-mini`

2. 固定比较：
   - `fresh_entry.avg_net_edge_pct`
   - `actionable.avg_net_edge_pct`
   - `hold.good_hold`
   - `blocked_entry`
   - 请求耗时 / timeout 风险 / 成本
   - `ai_failure_streak` 累积风险 / 触发 halt 风险

3. 如果 `gpt-5.4` 明显更好，再决定：
   - 先切 paper/backtest baseline
   - 还是先保留 mini 作为 live，5.4 仅用于 research

### 本阶段验收

下面两条至少满足一条，才算本阶段完成：

1. 证明 `5.4` 与 `mini` 差异很小，那么可以继续保留 `5.4` 作为当前 baseline
2. 证明 `mini` 在延迟 / 成本 / 稳定性综合上更优且策略质量不差，那么再考虑是否回退

在这一步完成前，不要把 model choice 当成已优化完成的前提。

## 进入后续工程阶段的门槛

默认门槛改成下面这样：

1. **前置阶段 0** 已经给出可信 review 口径，或者明确改掉默认 horizon
2. **前置阶段 1** 已经给出成本/宇宙结论，并说明当前 4-symbol / 6x 是否仍然值得继续作为 baseline
3. **前置阶段 2** 可以继续并行跑，但不再作为阻塞后续工程阶段 1 的硬门槛

满足 `0 + 1` 后，才进入下面原有的工程阶段：

- 阶段 1：解释面与去重
- 阶段 2：fresh-entry 窄修
- 阶段 3：short management 窄修
- 阶段 4：slot ranking

如果前置阶段 1 已经产出更优配置，比如 `BTC/ETH + 3x` 明显优于当前生产冻结基线，那么后续工程阶段默认在这个**新 baseline** 上继续，不回退到旧的 `4-symbol / 6x`。

否则容易出现这种情况：

- 工程上越来越精细
- 但没有证明系统本身存在足够正向边际

## Kill Switch

如果下面三件事做完后，仍然拿不到可持续正向边际，就不要继续在 live 上精修：

1. review 口径跨 `3/6/12/24` bar 明显翻转，且无法给出可信默认窗口
2. `3x + BTC/ETH` 这类更简单配置也没有给出正向 post-cost edge，或者真实滑点已经足以吃掉当前最小边际
3. `gpt-5.4` 和 `gpt-5.4-mini` 差异很小，或者 `5.4` 的 timeout / halt 风险反而更高

满足上面组合条件时，默认动作是：

- 暂停 live 交易
- 转回 paper / backtest / review 研究模式
- 先重新定义 alpha 假设，再决定是否恢复 live

## 后续工程阶段 1：先补解释面与去重，不动全局阈值

### 目标

先把最近最常见的这类情况解释清楚：

1. `candidate_filter` 已经放过
2. AI 已给方向
3. 最后被 `expected_edge_below_minimum` 或 `open_signal_*` 压回 `hold`

当前最大问题之一不是“阈值太严”，而是：

- `expected_edge`
- `open_signal`

可能仍在对同一类弱信号做双重惩罚。

### 本阶段改动范围

- [src/qount/risk_engine.py](/Users/alyaloale/Code/qount/src/qount/risk_engine.py)
- [src/qount/review.py](/Users/alyaloale/Code/qount/src/qount/review.py)
- [tests/test_strategy_optimization.py](/Users/alyaloale/Code/qount/tests/test_strategy_optimization.py)
- 当前计划文档与复查文档

### 本阶段具体任务

1. 在 `review` 输出里显式落出这些字段：
   - `entry_archetype`
   - `shadow_open_signal_reasons`
   - `required_threshold_pct`
   - `required_threshold_gap_pct`
   - `expected_edge_components`

2. 在 `review` 里新增聚合切片：
   - `by_entry_archetype`
   - `by_primary_risk_reason`

3. 在 `risk_engine` 里收紧职责边界：
   - `open_signal_*` 只保留**硬结构冲突**
   - 较软的方向弱化尽量折进 `expected_edge` / archetype penalty
   - 本阶段**不**下调全局 `QOUNT_MIN_EXPECTED_EDGE_PCT`

4. 保留当前已落地的：
   - `flat_bias_short_flush` blocker
   - `risk_debug`
   - 当前组合暴露约束

### 本阶段明确不做

- 不改 prompt
- 不改 executor
- 不重写 `candidate_filter`
- 不改 management close 逻辑

### 本阶段验收

代码验收：

- 本地测试通过
- 远端 WSL `pip install -e .` + 测试通过
- `preflight-live` 仍全绿

指标验收：

- `signal-review` 能直接回答“是哪类 archetype / 哪类 risk reason 在挡”
- `blocked_entry` 不再只剩一团 `expected_edge_below_minimum` 黑箱

推进门槛：

- 至少拿到新的 `post-change reviewed >= 12`
- 且 `post-change fresh_entry reviewed >= 6`

在达到这个样本门槛前，不推进下一阶段代码改动。

## 后续工程阶段 2：只做 fresh-entry 质量窄修

### 目标

在解释面清楚后，只改 fresh-entry 质量，不把 management / add / reverse 混进来。

### 本阶段改动范围

- [src/qount/entry_quality.py](/Users/alyaloale/Code/qount/src/qount/entry_quality.py)
- [src/qount/risk_engine.py](/Users/alyaloale/Code/qount/src/qount/risk_engine.py)
- 必要时少量补 [src/qount/candidate_filter.py](/Users/alyaloale/Code/qount/src/qount/candidate_filter.py)
- [tests/test_strategy_optimization.py](/Users/alyaloale/Code/qount/tests/test_strategy_optimization.py)

### 本阶段默认方向

只做两类优化：

1. **放 clean setup**
   - `aligned continuation`
   - `higher_timeframe reclaim / reversal`
   - 已经通过 candidate 和 AI 的 clean setup，不要再被软弱信号双重压死

2. **挡 bad chase**
   - `flat-bias short flush`
   - `terminal extension`
   - `overextended long chase`
   - 薄边际、低波动、低成交量 continuation

### 本阶段实现要求

1. archetype 优先于 symbol 讨论。
   - 先解释它是 `continuation / reclaim / reversal / flush chase` 哪一类
   - 不先按 `SOL/XRP/BTC/ETH` 做一堆硬编码

2. symbol 侧只允许保留当前已经有证据的窄限制。
   - 例如现有 `alt short penalty` 可以保留
   - 但不继续扩大成“更多 symbol 的固定特殊规则”

3. 任何放行都要通过 post-cost 角度解释。
   - 如果只是让成交更多，但 `avg_net_edge_pct` 更差，就视为失败

### 本阶段验收

样本门槛：

- `post-change reviewed >= 12`
- `post-change fresh_entry reviewed >= 6`

效果门槛：

- `fresh_entry.avg_net_edge_pct` 相比冻结基线至少改善 `0.10` 个百分点
  - 当前冻结基线是 `-0.20387`
- `actionable.avg_net_edge_pct` 至少改善到 `>= -0.05`
- `missed_move` 不能出现明显恶化
  - 在同样 `limit 160` 口径下，不接受从当前 `1` 条跳成明显放大

如果没有达到这些门槛：

- 先停在阶段 2
- 不进入 management 代码改动

## 后续工程阶段 3：short management 只做窄修

### 前置条件

只有当下面两条同时满足，才进入这一阶段：

1. 阶段 2 已经证明 fresh-entry 质量有改善
2. 复查仍显示 management 有清晰剩余问题

典型证据应是：

- `management_hold` 样本里反复出现：
  - 小幅浮盈后回吐继续 hold
  - 或小幅浮亏 + 本地 rebound 明显转强仍继续 hold

### 本阶段改动范围

- [src/qount/risk_engine.py](/Users/alyaloale/Code/qount/src/qount/risk_engine.py)
- [src/qount/review.py](/Users/alyaloale/Code/qount/src/qount/review.py)
- [tests/test_strategy_optimization.py](/Users/alyaloale/Code/qount/tests/test_strategy_optimization.py)

### 本阶段具体任务

1. 增加对称的 short-side 盈利降温退出：
   - `management_profitable_short_momentum_cooldown_close`

2. 增加一条窄的 short rebound loss-containment：
   - 只针对 `continuation short`
   - 只针对“小幅浮亏 + 5m 本地明显转强 + 1h 不再提供足够支撑”

3. 把新的 short 管理理由接进 review：
   - 能独立看出它到底是：
     - trailing close
     - partial TP
     - short cooldown close
     - rebound containment close

### 本阶段明确不做

- 不重写 TP/SL
- 不重写 conditional order
- 不重写 protective refresh
- 不把 management 变成复杂打分器

### 本阶段验收

- 新管理规则只命中目标场景，不应把正常 short management 大面积打坏
- `management_hold` 的坏样本要减少
- 不允许出现“持仓一有轻微波动就全被提早扫掉”

## 后续工程阶段 4：最后才做 slot ranking，不进入 add/reverse

### 目标

多币同轮已经跑通，下一步不是开更多功能，而是让有限仓位槽位优先留给质量更高的候选。

### 本阶段改动范围

- [src/qount/risk_engine.py](/Users/alyaloale/Code/qount/src/qount/risk_engine.py)
- 必要时少量补 [src/qount/review.py](/Users/alyaloale/Code/qount/src/qount/review.py)

### 本阶段具体任务

1. 在同向暴露接近上限时，不只末端拦截，而是前置排序：
   - 先比较 `post-buffer expected edge`
   - 再比较 archetype 质量

2. 让 review 能回答：
   - 哪个 symbol 因为 slot ranking 没拿到仓位
   - 是净暴露限制挡住，还是相关暴露限制挡住

3. 保持：
   - `max_open_positions`
   - 现有 `portfolio_* exposure` 约束
   不变

### 本阶段明确不做

- 不做 `add_position`
- 不做 `reverse_entry`
- 不扩 symbol/timeframe

## 当前明确后置的能力

下面这些继续后置：

1. `add_position`
2. `reverse_entry`
3. 全局阈值大改
4. 更激进的 against-`1h` bias 放行
5. prompt / executor 主链路重写

这些都必须等到：

- fresh-entry 已证明改善
- management 窄修也已稳定
- review 切片足够解释 `fresh_entry / management / blocked_entry / add / reverse`

## 每阶段统一验证命令

### 本地

```bash
PYTHONPATH=src python3 -m unittest tests.test_strategy_optimization
```

### 远端 WSL 同步与测试

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && ./.venv/bin/python -m pip install -e . && PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization'"
```

### 远端运行健康

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && PYTHONPATH=src ./.venv/bin/python -m qount.main preflight-live'"
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && PYTHONPATH=src ./.venv/bin/python -m qount.main runtime-status'"
ssh home "wsl.exe bash -lc 'systemctl --user status qount-runner.timer --no-pager -l'"
```

### 远端复查

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && PYTHONPATH=src ./.venv/bin/python -m qount.main signal-review --limit 160 --horizon-bars 3 --threshold-pct 0.003'"
```

## 执行顺序摘要

如果直接按实施顺序压成一句话，当前应该这样做：

1. 先用同一批历史窗口并行推进：`review horizon` 可靠性 + `3x/BTC-ETH` 成本与宇宙对照
2. 在阶段 0 产出默认 review 口径后，再做 `gpt-5.4 vs gpt-5.4-mini` 对照
3. 只要阶段 `0 + 1` 已经站住，就进入解释面、fresh-entry、management、slot ranking
4. 如果阶段 1 产出更优 baseline，后续工程默认跟着新 baseline 走
5. 如果前置研究仍然证明不了正向边际，就触发 kill switch，退回 paper/backtest
6. `add/reverse` 继续后置

## 当前建议

从今天开始，默认按这个顺序执行：

- 共享同一批历史窗口，并行推进 **前置阶段 0 + 前置阶段 1**
- 一旦阶段 0 确定默认 review 口径，就启动 **前置阶段 2**
- 只要阶段 `0 + 1` 已经给出可信结论，就进入后续工程阶段 1
- 如果阶段 1 产出更优 baseline，后续工程直接在新 baseline 上做
- 如果前置研究整体失败，就执行 **kill switch**

不要再回到下面这种旧做法：

- 因为“最近没怎么交易”，就先下调全局阈值
- 因为“有一笔持仓没平”，就先改 management
- 因为“多币同轮已跑通”，就直接上 `add/reverse`
