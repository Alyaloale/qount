# qount fresh entry 调整方案（2026-05-14，已归档）

归档说明：

- 这份文档记录的是 `2026-05-14` 首批 fresh-entry 修复当时的详细设计推导
- 首批改动已经落地，不再作为当前主设计入口
- 当前默认入口改为：
  - [../strategy-optimization-design.md](../strategy-optimization-design.md)
  - [../fresh-entry-effect-check-2026-05-14.md](../fresh-entry-effect-check-2026-05-14.md)

这份文档把 `2026-05-14` 这次基于生产 `signal-review --limit 160 --horizon-bars 3` 的结论，落成下一轮**具体可执行**的策略改动方案。

补充状态：

- 这份文档里的**第一批改动已经在 `2026-05-14` 落地并同步到 WSL**
- 因此它现在既是第一批的设计记录，也是“这批到底改了什么、还有什么没做”的整理入口
- 真正的 post-fix 复查口径，统一看：
  - [../fresh-entry-effect-check-2026-05-14.md](../fresh-entry-effect-check-2026-05-14.md)

如果你现在关心的是“这套改动已经上线后，当前运行是否正常，以及下次怎么固定口径复查效果”，看：

- [../fresh-entry-effect-check-2026-05-14.md](../fresh-entry-effect-check-2026-05-14.md)

目标不是泛泛地说“优化开仓”，而是明确：

- 现在哪一层在坏
- 哪些 run 证明了这个问题
- 第一批应该改哪几个文件
- 哪些不该现在一起改
- 上线后用什么口径验收

## 结论先说

当前主问题仍然是 `fresh_entry`，而且要收窄成两个更具体的问题：

1. `XRP` 的 fresh entry 容易追在 5m 局部衰竭位上。
2. `SOL` 的一部分 flat-bias breakdown short 被过度保守地压成了 `hold`。

`management` 不是完全没问题，但它现在是第二优先级，不应该和 fresh entry 调整混在第一批上线。

复查后再补一句更重要的限制：

- 第一批不能把“late breakdown / late breakout”做成过于通用的硬拒模板

否则很容易把 `SOL` 这类本来还能做的 momentum short 一起误杀。

## 本次 review 证据

本次生产 review 的核心聚合结果：

- `actionable.reviewed=5`
- `actionable.avg_net_edge_pct=-0.0901%`
- `by_lifecycle.fresh_entry.avg_net_edge_pct=-0.1443%`
- `hold.reviewed=116`
- `hold.good_hold=110`
- `hold.missed_move=6`

这说明：

- 系统不是“整体不会判断”
- 大多数 `hold` 仍然合理
- 真正坏的是**少数新开仓样本质量**

### 重点坏样本

#### run `1038`，XRP fresh short，坏

- 时间：`2026-05-14 00:10 CST`
- 动作：`sell`
- 结果：`net_edge_pct=-0.5379%`
- review：`future_R=-2.06`

现场特征：

- `candidate_filter` 给的是 `candidate_ok`
- `higher_timeframe_bias=short`
- AI 也明确给 `sell`
- risk 完整放行

问题不在“没放行”，而在**5m 已经很弱、RSI 已经偏 oversold 时继续追空**。

#### run `924`，XRP fresh long，坏

- 时间：`2026-05-13 14:10 CST`
- 动作：`buy`
- 结果：`net_edge_pct=-0.2298%`
- review：`future_R=-2.47`

现场特征：

- `higher_timeframe_bias=long`
- AI 因“高周期偏多 + 5m 反弹”开多
- risk 还把 TP/SL 修到了最低可用值

问题和 `1038` 对称：**不是方向一定错，而是 entry 时机太晚，像是在追局部反弹末端。**

### 重点漏样本

#### run `1015` / `993` / `992`，SOL idle hold，漏掉可做 short

共同特征：

- 都是 `position_before=None`
- 都是 `review_action=hold`
- 都是 `decision_context=idle`
- `opportunity_edge_pct` 分别约 `0.325% / 0.323% / 0.350%`

其中 `993`、`992` 的共同原因尤其清楚：

- `candidate_filter_primary_reason=higher_timeframe_flat_bias_soft_penalty`
- AI 认为 `flat bias + oversold` 不够干净，所以没开

这些样本说明：

- 当前对 `flat` 高周期背景下的 fresh short，保守得有点过头
- 这条更像 `SOL` 问题，不像 `XRP` 问题

#### run `990`，XRP idle hold，漏掉大 short

- `opportunity_edge_pct=0.8582%`
- 但当时 `higher_timeframe_bias=long`

这是一个很显眼的 missed move，但**第一批不建议直接因此放开“against 1h long 的 fresh short”**。

原因：

- 当前 fresh entry 坏样本本来就集中在 `XRP`
- 如果第一批一边修 `XRP` 追单问题，一边再放开 `XRP` 对冲高周期做空，风险会混在一起，无法判断是哪条改动起作用

这个样本应该先记为第二阶段观察点，而不是第一批上线理由。

### management 次要问题

#### run `962` / `961`，XRP management hold，后面回撤

共同特征：

- 持仓前是 `XRP long`
- AI 给 `hold`
- risk 也没强制 `close`
- review 后都属于 `missed_move`

这说明：

- `management_adverse_hold_to_close` 方向上没错
- 但在“已有小幅浮盈的 long 开始转弱”这类场景，触发偏晚了 `1~2` 根 bar

这条值得改，但不该挤进第一批。

## 设计目标

第一批方案只做三件事：

1. 减少 `XRP` fresh entry 追单。
2. 放开一部分 `SOL` 的 flat-bias breakdown short。
3. 保持现有 management / executor 主链路不动。

第一批明确**不做**：

- 不上新的加仓规则
- 不动 partial / trailing / TP/SL 执行链路
- 不放开 against `1h long` 的 `XRP` fresh short
- 不引入一堆新的 `.env` 配置项

原则是：先把最明显的坏 entry 修掉，再决定要不要恢复更激进的反向 short。

补充一条实现原则：

- 第一批优先做 `soft penalty + prompt 收紧 + risk 兜底`
- 不要先做“大范围 candidate hard reject”

截至 `2026-05-14 11:31 CST`，上面这第一批已经完成部署。下面各节保留原设计 reasoning，但会同步标出**实际落地点**，避免继续把它读成“纯待办”。

## 第一批改动方案（已落地）

## 1. 在 candidate filter 增加 fresh entry 追单衰竭过滤

### 目标

优先拦住 `run 1038` 和 `run 924` 这类“方向故事成立，但 entry 已经太晚”的样本。

### 改动文件

- [src/qount/candidate_filter.py](/Users/alyaloale/Code/qount/src/qount/candidate_filter.py)
- [src/qount/entry_quality.py](/Users/alyaloale/Code/qount/src/qount/entry_quality.py)
- [tests/test_strategy_optimization.py](/Users/alyaloale/Code/qount/tests/test_strategy_optimization.py)

### 已落地状态

实际实现没有把 fresh-entry exhaustion 散在多个 ad hoc 函数里，而是收敛成了共享 helper：

- `assess_fresh_entry(...)`
- `short_setup_late_breakdown_soft_penalty`
- `long_setup_late_breakout_soft_penalty`
- `short_setup_pre_breakdown_watch`
- `long_setup_pre_breakout_watch`

其中：

- terminal extension 在 candidate 层记为 `*_soft_penalty`
- 早段 continuation 在 candidate 层记为 `*_pre_break*watch`
- 这样既保留 explainability，也没有把第一批写成“只要 oversold/overbought 就硬拒”

### 具体做法

在 `candidate_filter.py` 里新增一层 fresh-entry exhaustion precheck，位置放在现有：

- `_short_candidate_precheck()`
- `_candidate_quality_gate()`

之间更合适，或者直接把 `_short_candidate_precheck()` 拆成更对称的：

- `_fresh_entry_exhaustion_reasons()`
- `_short_candidate_precheck()`
- `_long_candidate_precheck()`

第一批不建议搞 symbol-specific hardcode。规则写成通用，但第一版默认应先作为 `soft penalty / explainability reason`，而不是直接 hard reject。

### 计划规则

对 fresh short，如果同时满足：

- `higher_timeframe_bias == "short"`
- `return_24bars` 已经明显为负
- `return_1bar` 也已经明显为负
- `rsi_14` 已经落在偏 oversold 区间
- `volume_ratio_20` 没有强到足以说明“刚开始加速”
- 最近 `1~2` 根闭合 bar 更像延伸末端，而不是新的放量破位起点

则先标记类似：

- `short_setup_late_breakdown_soft_penalty`

并且从 candidate 阶段就不再把它当成干净的 `candidate_ok`。

第一版默认仍允许 symbol 进入 AI，只是在 `candidate_context.reasons` 里挂出这个 penalty。  
只有当它和现有的 `short_setup_countertrend_drift` / `short_setup_latest_bar_rebound` 一起形成“明显脏样本”时，才考虑直接 hard reject。

对 fresh long 做对称处理：

- `higher_timeframe_bias == "long"`
- `return_24bars` 明显为正
- `return_1bar` 也明显为正
- `rsi_14` 已经偏 overbought
- `volume_ratio_20` 没有新的扩张确认

则标记：

- `long_setup_late_breakout_soft_penalty`

同样，第一版先作为 soft penalty，不直接一刀切剔除。

### 为什么先放 candidate 层

因为 `run 1038` / `924` 的问题不是 risk 没挡住，而是模型已经拿到了一个“看起来方向顺、其实 entry 太晚”的候选。  
但复查后更稳妥的实现方式不是“候选层直接全部挡掉”，而是：

1. 候选层先标记 penalty，让 AI 明确看到“这不是干净 setup”
2. risk 再兜底拦住仍然要追单的样本

这样做比直接 hard reject 更容易观察：

- AI 是不是仍在追末端
- `SOL` 的 clean short 会不会被误杀

### 第一批不引入 env 配置

这里先用代码常量，不先把它们暴露成 `.env`：

- 避免这轮又变成一堆 live 参数试错
- 先观察方向是否正确
- 只有第一批方向验证通过后，再把最敏感的 `RSI` / `return_1bar` / `volume_ratio` / `bar extension` 阈值提升成配置

### 不要只靠 RSI 做 hard reject

这是这次复查后最重要的修正之一。

`run 1024` 的 `SOL short` 本身就带有：

- 顺方向 5m 走弱
- `RSI` 偏 oversold
- fresh short

但它的 review 结果并不差：

- `net_edge_pct=+0.2852%`

虽然还没过 `0.3%` 阈值，但它已经说明：

- “oversold + 顺方向下跌” 不等于坏 short

所以第一批不应该写成：

- `RSI oversold + return_1bar<0 + return_24bars<0 => reject`

正确写法应该更接近：

- `末端延伸 + 没有新增量能确认 + 最近 bar 结构更像衰竭，而不是刚开始加速`

## 2. 在 AI prompt 里明确禁止“局部衰竭位追单”

### 目标

把模型的口径从“方向一致就可以小仓试单”收紧成：

- 方向一致
- 不是明显衰竭位
- 不是已经跑过一段之后的末端 bar

### 改动文件

- [prompts/decision_prompt_v1.txt](/Users/alyaloale/Code/qount/prompts/decision_prompt_v1.txt)
- [prompts/system_prompt_v1.txt](/Users/alyaloale/Code/qount/prompts/system_prompt_v1.txt)
- [src/qount/ai_client.py](/Users/alyaloale/Code/qount/src/qount/ai_client.py)

### 已落地状态

这部分已经同步到了：

- prompt 文件本身
- `src/qount/ai_client.py` 的 fallback / inline 规则文案

当前实际口径已经包含：

- 末端延伸 / climactic bar 不追 fresh entry
- `short_setup_pre_breakdown_watch` / `long_setup_pre_breakout_watch` 是早段观察信号，不是自动 veto
- `flat` 高周期背景下允许 clean short，但不允许模糊偏空故事硬开

### 具体做法

在 prompt 里加两条硬口径：

1. 对 fresh short：
   - 如果最新闭合 5m bar 已经是明显下冲 bar，且 `RSI` 已偏 oversold，除非有新的量能扩张或结构性 breakdown 证据，否则优先 `hold`，不要追末端 short。
2. 对 fresh long：
   - 如果最新闭合 5m bar 已经是明显上冲 bar，且 `RSI` 已偏 overbought，除非有新的量能扩张或结构性 breakout 证据，否则优先 `hold`，不要追末端 long。

这里要注意：

- 不要写成“只要 oversold 就不做 short”
- 也不要写成“只要 overbought 就不做 long”

真正要禁止的是：

- `已经跑过一段`
- `最后一根 bar 继续延伸`
- `没有新的 volume expansion`

这种“末端追单”。

### 必须同步改掉现有的激进入场文案

不能只在 prompt 里“追加两句谨慎规则”，还必须同步收紧现有这类表述：

- `prefer a small starter entry over a passive hold`
- `对方向一致、只有轻微量能不足的候选，更偏向小仓位试单`

如果只新增“不要追末端”规则，但保留这类强推 starter entry 的表述不动，模型会同时收到两组互相打架的指令，漂移概率很高。

## 3. 在 risk 再加一层 fresh entry 追单兜底

### 目标

即使 prompt 以后又漂了，risk 也不应该继续把这种衰竭位 fresh entry 放行。

### 改动文件

- [src/qount/risk_engine.py](/Users/alyaloale/Code/qount/src/qount/risk_engine.py)
- [tests/test_strategy_optimization.py](/Users/alyaloale/Code/qount/tests/test_strategy_optimization.py)

### 已落地状态

这部分已经通过共享 `assess_fresh_entry(...)` 接回 risk：

- `fresh_entry_late_breakdown`
- `fresh_entry_late_breakout`

也就是说，现在的职责分工已经是：

- candidate：给 explainability / soft penalty
- prompt：尽量不让模型去追末端
- risk：对仍被开出来的 terminal extension 做 hard reject

### 具体做法

在 `risk_engine.py` 的 fresh-entry 逻辑里新增一层和 candidate 同方向的 reject reason。  
落点应放在：

- `_open_signal_reasons()`
- `evaluate()` 里 `is_open_action(...)` 分支

之间。

建议新增一个小函数，例如：

- `_fresh_entry_exhaustion_reasons(action, symbol_snapshot) -> list[str]`

如果命中，则追加类似 reason：

- `fresh_entry_late_breakdown`
- `fresh_entry_late_breakout`

并把：

- `final_action -> hold`
- `final_size_pct -> 0`

### 为什么 candidate 和 risk 都要改

因为两层职责不同：

- candidate 层负责少送明显脏样本给模型
- risk 层负责兜住模型未来的口径漂移

这不是重复工作，而是：

- candidate 负责降低噪声
- risk 负责保证底线

复查后更推荐的分工是：

- `candidate_filter`
  - 先加 `late_breakdown / late_breakout` soft penalty
- `risk`
  - 对仍然被 AI 明确开出的衰竭位 fresh entry 做 hard reject

## 4. 只对 flat-bias short 做适度放行，不碰 long-bias short conflict

### 目标

补掉 `run 1015 / 993 / 992` 这类 `SOL` missed move，但不把系统重新放回“什么都能做 short”的状态。

### 改动文件

- [prompts/decision_prompt_v1.txt](/Users/alyaloale/Code/qount/prompts/decision_prompt_v1.txt)
- [prompts/system_prompt_v1.txt](/Users/alyaloale/Code/qount/prompts/system_prompt_v1.txt)
- [src/qount/risk_engine.py](/Users/alyaloale/Code/qount/src/qount/risk_engine.py)
- [tests/test_strategy_optimization.py](/Users/alyaloale/Code/qount/tests/test_strategy_optimization.py)

### 已落地状态

这一条真正落地的主变化面是：

- prompt
- candidate explainability
- 针对 flat-bias clean short 的回归测试

按当前代码，risk 本来就不会因为 `flat` bias 直接硬拒 short；所以这里保留下来的原则也应该是：

- 第一批重点不是“重写 risk”
- 而是别让 `flat bias soft penalty` 在解释层被误读成“天然不能做 short”

### 具体做法

第一批只放松这一种情况：

- `higher_timeframe_bias == "flat"`
- 但 5m 方向已经连续走弱
- `return_24bars` 对 short 有利
- `sma_fast_ratio` / `sma_slow_ratio` 支持 short
- `volume_ratio_20` 不低
- 最新 bar 不是反抽 bar
- 且没有命中上面的 exhaustion 追空条件

这条可以通过两处实现：

1. prompt：明确告诉模型，`flat` 不是禁做 short，只是不能靠“模糊偏空故事”开单。
2. risk：对 `trend_bias == flat` 的 short，不新增 hard reject，只保留现有 `open_signal` 约束。

复查后这里需要再说清楚一层：

- 按当前代码，risk 本来就不会因为 `flat` bias 直接拒掉 short
- 所以第一批这条的主改动面应放在：
  - prompt
  - candidate summary / explainability

而不是先去动 risk 主逻辑

### 第一批明确不做的事

不放开：

- `trend_bias == long` 时的 fresh short

也就是：

- `run 990` 先记录为观察样本
- 但第一批不为了这一条去动 `higher_timeframe_trend_conflict`

原因很简单：

- 这会和“修 XRP 追空问题”直接打架
- 上线后无法判断是“更会抓机会了”还是“又把 countertrend short 放出来了”

## 第二批改动方案

## 5. 把 management adverse close 提前半档，但只在已有浮盈时生效

### 目标

针对 `run 961 / 962` 这种：

- 持仓本来已有小浮盈
- 5m 开始转弱
- 但系统还继续 `hold`

### 改动文件

- [src/qount/risk_engine.py](/Users/alyaloale/Code/qount/src/qount/risk_engine.py)
- [tests/test_strategy_optimization.py](/Users/alyaloale/Code/qount/tests/test_strategy_optimization.py)

### 具体做法

不直接改掉现有 `_management_signal()` 主体，而是在 `evaluate()` 的 management 分支里，加一条更保守的 profit-protection 规则：

- 仅当 `current_position_return_pct > 0`
- 且 `return_1bar` 已经明显逆向
- 且 `sma_fast_ratio` 已经翻到不利一侧
- 且最新持仓收益不足以支撑继续容忍回撤

才追加：

- `management_early_adverse_profit_lock`

并强制 `close`。

### 为什么第二批才做

因为这条会直接影响 `management_hold`，而当前聚合结果里：

- `management` 组整体接近持平
- 不是当前最差的一层

所以它应该在 fresh entry 修完以后单独上线，避免把两个变量搅在一起。

## 明确不建议现在做的事

## 1. 不要直接继续下调 `QOUNT_MIN_EXPECTED_EDGE_PCT`

当前问题不是“risk 还不够松”。

证据很清楚：

- `run 1038`
- `run 924`

都已经是：

- `candidate_ok`
- AI 明确给方向
- risk 明确放行

继续下调 `min_expected_edge_pct` 只会把更多薄边际、末端 entry 放进来，不会解决 timing 问题。

## 2. 不要先动 `XRP` 的 higher-timeframe conflict 放行

`run 990` 虽然显眼，但它只有一个大 missed sample。  
在 fresh entry 坏样本已经集中在 `XRP` 的前提下，先放开 against `1h long` 的 short，会把回归方向搞乱。

这条应该等第一批稳定后，再单独拿最近一批 `XRP` missed_move / blocked_sell / actionable 样本看。

## 3. 不要把第一批方案做成大量 `.env` 参数

第一批的正确实现方式应该是：

- 代码常量
- 明确测试
- 明确 review 验收

而不是：

- 一次加 8 个 live 参数
- 再靠线上试错慢慢拨

## 代码改动清单

第一批建议改这些文件：

- [src/qount/candidate_filter.py](/Users/alyaloale/Code/qount/src/qount/candidate_filter.py)
  - 新增 fresh-entry exhaustion soft-penalty precheck
  - 保持现有 `short_setup_countertrend_drift` 逻辑不删
- [src/qount/risk_engine.py](/Users/alyaloale/Code/qount/src/qount/risk_engine.py)
  - 新增 fresh-entry exhaustion hard reject reasons
  - 不改 executor / protective order 主链路
  - 第一批不动 `higher_timeframe_trend_conflict`
- [prompts/decision_prompt_v1.txt](/Users/alyaloale/Code/qount/prompts/decision_prompt_v1.txt)
  - 补“不要在末端 bar 追 fresh entry”
  - 补“flat bias short 可以做，但必须是 clean breakdown”
- [prompts/system_prompt_v1.txt](/Users/alyaloale/Code/qount/prompts/system_prompt_v1.txt)
  - 与 decision prompt 同步
- [src/qount/ai_client.py](/Users/alyaloale/Code/qount/src/qount/ai_client.py)
  - 镜像内联规则文案，避免 prompt 文件和 runtime hint 脱节
  - 同步收紧现有“prefer a small starter entry”类表述
- [tests/test_strategy_optimization.py](/Users/alyaloale/Code/qount/tests/test_strategy_optimization.py)
  - 增加 fresh short late-breakdown reject 测试
  - 增加 fresh long late-breakout reject 测试
  - 增加 flat-bias clean short 允许测试
  - 保留 current `higher_timeframe_trend_conflict` 测试不改

第二批再动：

- [src/qount/risk_engine.py](/Users/alyaloale/Code/qount/src/qount/risk_engine.py)
  - management early adverse profit lock
- [tests/test_strategy_optimization.py](/Users/alyaloale/Code/qount/tests/test_strategy_optimization.py)
  - 对应 management regression tests

## 测试方案

第一批本地测试至少补这几类：

1. `XRP` fresh short，`higher_timeframe_bias=short`，但：
   - `return_1bar` 已明显为负
   - `return_24bars` 已明显为负
   - `rsi_14` 已偏 oversold
   - `volume_ratio_20` 不足
   - 最近 `1~2` 根 bar 更像末端延伸
   - 预期：`candidate_filter` 出现 penalty reason，`risk` 最终拦成 `hold`

2. `XRP` fresh long，`higher_timeframe_bias=long`，但：
   - `return_1bar` / `return_24bars` 已偏强
   - `rsi_14` 已偏 overbought
   - 量能没有继续放大
   - 最新 bar 更像末端拉升
   - 预期：`candidate_filter` 出现 penalty reason，`risk` 最终拦成 `hold`

3. `SOL` flat-bias short：
   - `higher_timeframe_bias=flat`
   - `return_24bars` 对 short 有利
   - `sma_fast_ratio` / `sma_slow_ratio` 支持 short
   - `volume_ratio_20` 足够
   - 最新 bar 不是 rebound
   - 最新 bar 不是末端衰竭 bar
   - 预期：仍允许 `sell`

4. against `1h long` 的 `XRP` short：
   - 预期：第一批仍然被 `higher_timeframe_trend_conflict` 拦掉

建议最少跑：

```bash
PYTHONPATH=src python3 -m unittest tests.test_strategy_optimization
```

这里不要再把 `pytest` 当默认路径。这个仓库当前已验证、且不依赖额外安装的是：

- `PYTHONPATH=src python3 -m unittest tests.test_strategy_optimization`

如果只想先看这轮策略回归：

```bash
PYTHONPATH=src python3 -m unittest tests.test_strategy_optimization.StrategyOptimizationTests
```

## 上线顺序

推荐按这个顺序走：

1. 先改 candidate + prompt + risk 第一批
2. 本地 `unittest` 过
3. 同步到 WSL，并刷新远端 editable install
4. 远端 `unittest` 过
5. 跑：

```bash
cd /home/alyaloale/Code/qount
set -a && source .env && set +a
./.venv/bin/python -m pip install -e .
PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization
./.venv/bin/python -m qount.main preflight-live
./.venv/bin/python -m qount.main signal-review --limit 160 --horizon-bars 3 --threshold-pct 0.003
```

6. 如果当时没有 live 持仓，且你就是要手动做一次真实链路验证，再额外跑：

```bash
./.venv/bin/python -m qount.main run-once
```

7. 如果当时已经有 live 持仓，默认不要为了“验证一下”强行手动跑 `run-once`；恢复 timer，等下一轮真实样本
8. 等至少 `12~24` 小时 live 样本后，再看要不要做第二批 management 调整

## 验收标准

第一批上线后，不要求立即“交易更多”，要求的是：

- 先满足最小样本门槛，再下效果结论：
  - `post-fix reviewed >= 12`
  - `post-fix fresh_entry reviewed >= 6`
- 在样本不足前，只允许下两种结论：
  - `修复版运行健康`
  - `新 reason / 新拒单已经开始按预期命中`

1. `fresh_entry.avg_net_edge_pct` 高于当前的 `-0.1443%`
2. `actionable.avg_net_edge_pct` 高于当前的 `-0.0901%`
3. 不再出现明显类似 `run 1038` / `run 924` 的 `XRP` fresh entry 追单坏样本
4. `hold.good_hold / hold.reviewed` 仍保持高占比，不要把整体 hold 质量打坏
5. `by_blocked_group.blocked_entry` 没有被第一批明显打坏
6. `blocked_sell` 仍然只作为 short 侧辅助切片，不能单独代表这第一批成败
7. 没有新增 runtime / executor / protective order 回归

## 回滚条件

出现下面任一情况就应直接回滚第一批：

- `fresh_entry` 数量增加了，但 `avg_net_edge_pct` 更差
- `XRP` fresh entry 坏样本明显变多
- `SOL` flat-bias short 放开后，连续出现被 squeeze 的坏样本
- `hold.good_hold` 比例明显下降

## 最终建议

下一轮不要再围绕“整体再放松一点”做抽象调参。  
最值得做的是：

1. 先修 `XRP` fresh entry 追单
2. 再补 `SOL` flat-bias short 的保守漏单
3. 最后才动 `management` 的提前 close

这个顺序的好处是：

- 每一批只改一个主要矛盾
- review 结果更容易解释
- 不会把 `XRP` 的坏 entry 和 `management` 的小回撤问题同时搅在一起
