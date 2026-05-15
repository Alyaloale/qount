# qount 策略优化方案

这份文档记录 `2026-05-12` review 之后的新计划。

目标不是把系统改复杂，而是把当前“保守但 edge 偏薄”的 5m futures 策略，收敛成一条更可解释、可验证、不会靠小样本乱调参的实现路径。

补充说明：

- `2026-05-13` 之后，交易所侧 reduceOnly 保护单、TP/SL management 回读、浮盈回撤保护、futures 持仓详情修正、SL sizing、更细 review、多次 partial take profit、breakeven stop，以及动态保护单刷新已经落地
- 旧的分支计划文档已经收进 `docs/archive/`
- 当前策略优化只保留这份文档作为**主设计入口**

本文件仍保留 2026-05-12 的策略优化原则，尤其是“先 review，再调参，避免小样本过拟合”。

补充一条 `2026-05-14` 的最新状态：

- live 链路已经恢复正常，当前重点不再是“系统会不会跑”
- 最近 live timer / `run-once` 都已重新回到 `completed`
- 当前策略处于**偏保守观望**状态，不是停摆
- 当前主问题已经收敛成：**fresh entry 质量弱**，而不是“系统不会管理”或“系统没在跑”

这意味着：

- 现在不应该为了“看起来没交易”去推翻主链路
- 也不应该把 `entry`、`management`、`executor`、`add/reverse` 一起混改
- 当前活跃实施路线应先修 `fresh_entry timing`，再按 post-fix 样本决定要不要继续动 `expected_edge` 或 management

再补一条基于 **`2026-05-14 16:35 CST` 远端 WSL 真实运行与当前代码** 的修正：

- 首批 fresh-entry timing 修复已经落地
- 但截至这次复查，post-fix live 还**没有产生新的 actionable / fresh_entry 成交样本**
- 当前真正需要优先盯的，不再是继续抽象细化 `late_breakdown / late_breakout` 规则，而是：
  - 这些新规则是否真的开始命中 live 样本
  - 以及当前 `candidate -> AI -> risk -> hold` 的阻塞点到底卡在哪一层

再补一条基于 **`2026-05-15 10:4x CST` 最新复查 + 新代码部署** 的修正：

- 第二轮窄优化已经落地，不再停留在“只观察不动代码”
- 这轮不去重写 prompt / management / executor 主链路，只针对两类最新 live 问题做窄修：
  - `SOL long fresh_entry` 继续收紧 late / overextended long chase
  - `XRP blocked_entry.buy` 给一条更窄的 reclaim / reversal risk 通道
- 代码已同步到远端 WSL，并重新 `pip install -e .`
- 本地和远端 WSL 都已经重新跑通：
  - `PYTHONPATH=src python3 -m unittest tests.test_strategy_optimization`
- 下次复查必须把这轮代码和第一轮 `run_id >= 1175` 修复样本拆开

这份文档现在的用途是：

- 上半部分只保留**当前默认执行顺序**
- 中间部分记录**当前已经落地的首批调整**和**后续未启用能力**
- 下半部分把 `2026-05-12` 的 edge-first reasoning 归档保存
- 如果两边口径冲突，永远以 `2026-05-14` 活跃计划和配套复查文档为准

如果你要看这批方案上线后，下一次应该按什么口径复查，看：

- [fresh-entry-effect-check-2026-05-14.md](fresh-entry-effect-check-2026-05-14.md)

如果你要看历史细节而不是当前主线，看：

- [archive/fresh-entry-tuning-plan-2026-05-14.md](archive/fresh-entry-tuning-plan-2026-05-14.md)
- [archive/position-management-sizing-review-2026-05-13.md](archive/position-management-sizing-review-2026-05-13.md)

## 2026-05-14 当前活跃计划

这节是当前默认执行顺序。下文保留 `2026-05-12` 版的 edge-first 设计原则，作为历史 reasoning 和补充参考；但如果两边有顺序冲突，以这节为准。

### 阶段 1：先修 fresh entry 质量，不动主执行链路

当前第一优先级不是再调“会不会出手”，而是提升“新开仓一旦出手，质量是不是够好”。

第一批只做这几件事：

1. 在 `candidate_filter` 增加 fresh-entry exhaustion 的 explainability penalty。
2. 在 prompt 明确禁止局部衰竭位追单。
3. 在 `risk_engine` 对仍然想追末端的 fresh entry 加 hard reject 兜底。
4. 只对 `flat-bias short` 做有限放行，不碰 `long-bias short conflict`。

这一阶段明确不做：

- 不改 partial / trailing / protective-order 主链路
- 不改 add / reverse
- 不继续扩符号、扩 timeframe、扩 schema
- 不为了几笔 missed move 直接放开 against-1h-bias 的反向单

### 阶段 2：用 post-fix live 样本证明第一批方向是否正确

第一批上线后，先不要立刻继续加规则，而是固定用：

- `signal-review --limit 160 --horizon-bars 3 --threshold-pct 0.003`
- `fresh_entry`
- `missed_move`
- `by_symbol`
- `by_blocked_group.blocked_entry`
- `blocked_sell`

来判断：

- `fresh_entry.avg_net_edge_pct` 是否明显高于当前负基线
- `actionable.avg_net_edge_pct` 是否回到接近 `0` 或转正
- `hold.missed_move` / `blocked_entry` / `blocked_sell` 是否没有被第一批改动明显打坏

在满足下面两个最小 post-fix 样本前，不下“方向已经证明有效/无效”的结论：

- `post-fix reviewed >= 12`
- `post-fix fresh_entry reviewed >= 6`

不足时只记两件事：

- 运行链路是否健康
- 新 reason / 新拒单是否开始按预期命中真实样本

截至 `2026-05-14 16:35 CST`，这一步的真实状态是：

- `post-fix reviewed = 26`
- `post-fix actionable reviewed = 0`
- `post-fix fresh_entry reviewed = 0`
- `post-fix management_hold reviewed = 13`
- `post-fix missed_move reviewed = 1`

所以当前还**不能**下“fresh-entry 修复已经有效/无效”的结论。  
当前只能下两条结论：

- live 运行链路健康
- 首批修复还没有得到新的实盘 fresh-entry 样本验证

这也意味着：如果下一轮还没有 fresh-entry 样本，阶段 2 的工作重点应先转成**阻塞点诊断**，而不是继续空转调 `late_breakdown` 细节。

如果第一批只是“出手更多”，但 `avg_net_edge_pct` 更差，那就先回滚设计方向，不继续叠第二批规则。

### 阶段 3：只有在真实阻塞点明确后，才决定是否动 `expected_edge_pct`

`expected_edge_pct` 重构仍然值得做，但它现在不再是第一批。

只有当：

- fresh entry timing 问题已经明显收敛
- 或 post-fix 记录持续显示 `candidate_ok / AI directional action` 被 risk 压回 `hold`
- 但 post-cost edge 仍然系统性偏薄

才推进 `risk_engine` 里的 explainable post-cost edge proxy 重构。

这一步仍然遵守旧原则：

- 不做双重计数
- 不一次拆出很多方向专用阈值
- 不把 edge 打分做成复杂的多段评分器

结合这次远端记录，要特别补一条：

- 如果后续继续出现像 `run_id 1221~1232` 这样：
  - `candidate_filter` 已经选出 symbol
  - AI 已经给出 `buy`
  - 最终主要被 `expected_edge_below_minimum` 压回 `hold`
- 那么下一轮该优先审的是：
  - `expected_edge_pct`
  - `open_signal_return_24bars`
- 而不是继续先改 `late_breakdown / late_breakout`

### 阶段 4：management 只做窄修，不和 fresh entry 混上线

当前 `management` 不是完全没问题，但它是第二优先级。

只有当 post-fix review 继续显示：

- `management_hold.missed_move` 仍集中在“已有小浮盈后转弱却继续 hold”

才做窄修：

- 提前 `management_adverse_hold_to_close`
- 或补一层更直接的弱化 close 条件

不要在这一步再去重写 partial / breakeven / trailing / executor，因为这些链路已经是当前 live 安全基线。

### 阶段 5：最后才考虑 add / reverse / 更激进放行

下面这些能力都只能后置：

- `add_position`
- `reverse_entry`
- 更激进的 short precheck 放松
- 更复杂的 portfolio / allocation 逻辑

触发条件必须是：

- 第一批和第二批已经证明 `fresh_entry` 质量改善
- review 切片能够明确区分 `fresh_entry` / `management` / `add` / `reverse`
- 当前收益瓶颈确实已经从“entry 质量”转移

## 2026-05-14 首批调整已落地

当前活跃路线里的第一批改动已经完成，本文件不再把它们当“待实施计划”。

这批已落地的关键点是：

- 把 fresh-entry timing 判断收敛到共享 `entry_quality` 逻辑
- candidate 层增加：
  - `short_setup_late_breakdown_soft_penalty`
  - `long_setup_late_breakout_soft_penalty`
  - `short_setup_pre_breakdown_watch`
  - `long_setup_pre_breakout_watch`
- prompt / `ai_client` 同步收紧：
  - 不追 terminal extension
  - `pre_break*watch` 是早段观察信号，不是自动 veto
  - `flat` 高周期背景允许 clean short，但不允许模糊偏空故事硬开
- risk 层增加：
  - `fresh_entry_late_breakdown`
  - `fresh_entry_late_breakout`
  - 作为对 terminal extension 的 hard reject 兜底
- 相关测试已经补到 `tests/test_strategy_optimization.py`

当前代码里已经稳定存在、文档必须按实情承认的能力还包括：

- `partial_take_profit`
- `breakeven_stop`
- `dynamic_protective_refresh`
- `decision_lifecycle / by_blocked_group / by_exit_source`

所以后续设计不能再假设这些还是“待补功能”，而应该直接把它们当成当前 live 基线。

当前默认结论不是“还要不要做这批”，而是：

- 这批已经上线
- 现在只需要按 post-fix 样本继续复查它是否有效

但基于本次 live 记录，还要再补一条更现实的状态判断：

- 当前不是“这批修复已经跑出大量新鲜样本”
- 而是“这批修复已上线，但 live 仍主要停留在 management hold / blocked entry”
- 所以下一步不是盲目继续细化 first batch，而是先确认：
  - 新 reason 是否真的开始命中
  - 风控是否在 candidate+AI 之后系统性压回某一类 entry

## 2026-05-15 二次窄优化已落地

这轮是在首批 fresh-entry timing 修复之后，根据更新到 `2026-05-15 10:07 CST` 的复查结果继续做的第二轮窄优化。

这轮不是泛化式“再调保守/激进”，而是只针对两类已经被 live review 证明的问题：

1. `SOL long fresh_entry` 仍差
   - `run_id >= 1286` 下：
     - `SOL fresh_entry_reviewed = 3`
     - `SOL fresh_entry_avg_net_edge_pct = -0.2068%`
   - 代表样本：
     - `1295`
     - `1355`
   - 共同特征更像：
     - 顺着 `1h long` 去追高位 long
     - `24bar return` 已经不低
     - `RSI` / `volume` / candle body 都不算便宜

2. `XRP blocked_entry.buy` 漏掉太多
   - `run_id >= 1286` 下：
     - `blocked_entry.buy.reviewed = 40`
     - `blocked_entry.buy.missed_move = 8`
   - 当前主因仍然集中在：
     - `expected_edge_below_minimum`
     - `open_signal_return_24bars_too_weak`
     - `open_signal_sma_fast_conflict`
     - `open_signal_sma_slow_conflict`
   - 代表样本：
     - `1408`
     - `1409`
     - `1422`
     - `1423`
     - `1344`

### 这轮代码具体做了什么

#### 1. 继续收紧 `SOL long` 这类坏 fresh entry

落点：

- `src/qount/entry_quality.py`

这轮新增了两类 long 侧 terminal-extension 识别：

- 更早拦住 low-participation late long
  - 把 long 侧 `LATE_ENTRY_LONG_MIN_RSI` 从 `62.0` 下调到 `58.0`
  - 这样像 `1355` 这类中高 RSI、低确认量、已不便宜的 late long，会更早被 `fresh_entry_late_breakout` 拦住
- 新增 `overextended_long_chase`
  - 针对：
    - `24bar return` 已经很高
    - `1bar` 仍在顺势上冲
    - `volume` 偏高
    - `RSI` 偏高
    - body 仍偏大
  - 目标是拦住像 `1295` 这类并不一定满足“贴近极值”定义，但本质已经是 chase long 的样本

#### 2. 给 `XRP` 的窄 long reclaim / reversal 一条更合理的 risk 通道

落点：

- `src/qount/risk_engine.py`

这轮新增三条只对 `1h long` 生效的窄通道：

- `higher_timeframe_long_reclaim`
  - 给像 `1408` 这种：
    - `1h long` 很强
    - 本地 `24bar` 只是在零轴附近
    - `fast SMA` 已经回正
    - `slow SMA` 还没翻回
  - 一个小 edge bonus，并允许它不再被：
    - `expected_edge_below_minimum`
    - `open_signal_return_24bars_too_weak`
    - `open_signal_sma_slow_conflict`
    三重一起压死

- `higher_timeframe_long_reversal`
  - 给像 `1422 / 1423` 这种：
    - `1h long` 仍强
    - 本地 `24bar` 已经显著回撤
    - 本地 RSI 很低
    - 最新 `1bar` 开始回拉
  - 允许它不再因为：
    - `open_signal_return_24bars_too_weak`
    - `open_signal_sma_fast_conflict`
    - `open_signal_sma_slow_conflict`
    被机械压回 `hold`

- `higher_timeframe_long_fast_pullback`
  - 给像 `1344` 这种：
    - 高周期 long 很强
    - 本地 `24bar` 仍显著为正
    - 但最新 `1bar` 是小回踩
    - `fast SMA` 暂时翻负
  - 只豁免 `open_signal_sma_fast_conflict`
  - 不顺手豁免其它弱化条件，避免直接放宽成 chase long

### 这轮明确不做什么

这轮仍然没有做：

- 不改 management 主链路
- 不改 partial / breakeven / trailing
- 不继续放松 against-`1h` bias 的 short
- 不把 `expected_edge_pct` 改成一整套复杂分段评分器

原因很直接：

- 当前最值钱的信息，仍然来自最近几批 live 样本的窄问题
- 不是“大逻辑完全错了”
- 所以第二轮仍应保持“能解释、能复查、能回滚”的窄修节奏

### 这轮已完成验证

本地已验证：

- `PYTHONPATH=src python3 -m unittest tests.test_strategy_optimization`
  - `53` 条全部通过

远端 WSL 已验证：

- 重新 `pip install -e .`
- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization`
  - `53` 条全部通过
- `runtime-status`
  - `halted=false`
  - `ai_failure_streak=0`
- `preflight-live`
  - 全绿

### 下次复查要怎么切

这轮代码上线后，下次复查必须把它和上一轮 `run_id >= 1175` 分开。

为避免把部署前后混在一起，这轮建议直接用：

- `run_id >= 1455`

作为第二轮窄优化的**干净起点**。  
这里的 `1455` 是：

- `2026-05-15 10:45 CST`
- 本轮代码同步远端并完成 `pip install -e .` 之后的第一条新 live run

新的判断重点不是：

- “第一轮修复有没有让系统重新出手”

而是：

- `SOL long fresh_entry` 有没有明显减少
- `XRP blocked_entry.buy.missed_move` 有没有下降
- 新放开的 `XRP` reclaim / reversal 会不会把 `fresh_entry` 质量重新打坏

## 2026-05-14 16:35 CST 代码与运行记录校正

这节只记录当前主设计必须吸收的**现实约束**。

### 当前代码现实

当前主链路已经不是“只有 candidate filter + risk 的最小版”，而是：

`closed 5m bar -> snapshot -> candidate filter -> AI -> validate -> risk -> execute -> review`

其中已实装并正在影响 live 的关键策略部件包括：

- `entry_quality`
  - fresh-entry terminal extension soft penalty / hard reject
  - pre-break continuation watch
- `risk_engine`
  - `min_expected_edge_pct`
  - open-signal checks
  - trailing profit retrace
  - partial take profit
  - dynamic protective refresh
- `review`
  - `decision_lifecycle`
  - `blocked_group`
  - `future_R / mfe / mae / giveback`

因此当前设计文档如果还把问题表述成“先把 review / sizing / executor 补齐再说”，就已经落后于代码现实。

### 当前运行现实

本次远端 `signal-review --limit 220 --horizon-bars 3 --threshold-pct 0.003` 摘要：

- 全窗：
  - `reviewed = 140`
  - `hold.reviewed = 135`
  - `actionable.reviewed = 5`
  - `by_lifecycle.fresh_entry.reviewed = 4`
  - `by_lifecycle.blocked_entry.reviewed = 12`
  - `by_lifecycle.management_hold.reviewed = 85`
- `by_symbol`
  - `SOL avg_net_edge_pct = +0.0019%`
  - `XRP avg_net_edge_pct = -0.0079%`
- `blocked_sell`
  - `reviewed = 3`
  - `missed_move = 0`
  - 全部是 `expected_edge_below_minimum`

这说明当前全窗口径下：

- 系统仍然主要是 `hold`
- `sell` 被 risk 错杀并不是当前最显著的问题
- `XRP` 相对 `SOL` 仍然更弱

post-fix 口径下（`run_id >= 1175`）：

- `reviewed = 26`
- `actionable reviewed = 0`
- `fresh_entry reviewed = 0`
- `management_hold reviewed = 13`
- `missed_move reviewed = 1`

这说明当前 post-fix 真相不是“fresh-entry 质量已经改善”，而是：

- 还没有新的实盘 fresh-entry 成交样本
- 当前复查重点必须先转成“为什么没有新样本”

### 最近 live run 的真实阻塞点

本次现场检查里，有三条尤其重要：

1. 最近 `120` 个 live run 里，`short_setup_pre_breakdown_watch`、`short_setup_late_breakdown_soft_penalty`、`long_setup_pre_breakout_watch`、`long_setup_late_breakout_soft_penalty` **一次都没有命中**。
2. post-fix `blocked_entry` 当前全部都是 `buy`，没有 `sell`。
3. 这 `8` 个 post-fix `blocked_entry buy` 里：
   - `7` 个是 `expected_edge_below_minimum`
   - `1` 个是 `open_signal_return_24bars_too_weak`

这意味着当前下一步不能再默认成：

- “继续围绕 late breakdown / late breakout 做第一优先级微调”

而应该改成：

- “先确认 first batch 规则为什么还没有遇到真实命中样本”
- “再确认当前真正卡住 live entry 的是不是 `expected_edge` / open-signal 这一层”

## 后续未启用能力

下面这些能力仍然应该后置，不能和 fresh-entry 修复重新混上线：

1. `management` 窄修
   - 仅考虑“已有浮盈后转弱仍继续 hold”的提前 profit lock
   - 不重写 partial / breakeven / trailing / executor 主链路
2. `add_position`
   - 必须和 `fresh_entry` 拆开评审、拆开复查
   - 不能复用 fresh-entry 的同一套 trigger / sizing 语义
3. `reverse_entry`
   - 必须先确认 close 和 re-entry 的拆单行为、保护单刷新、review 归类都独立可解释
4. 更激进的 short 放行
   - 包括 against `1h long` 的 fresh short
   - 只有在当前 first batch 已证明显著改善后才考虑

如果需要看这些后续能力的旧详细评审，去看归档深挖文档：

- [archive/position-management-sizing-review-2026-05-13.md](archive/position-management-sizing-review-2026-05-13.md)

## 当前判断

当前主链路已经成立：

`closed 5m bar -> snapshot -> candidate filter -> AI -> validate -> risk -> execute -> review`

这条链路先不推翻。当前问题也不是“系统不交易”，而是：

- 大量 `hold/noop` 大多是合理 `hold`
- 真正 `actionable` 的样本还少，不能按几笔成交直接过拟合
- 少数真实出手的 action，post-cost edge 仍然偏薄
- live 运行里，系统很大一部分时间其实是在管理已有仓位，而不是寻找全新 entry

但基于这次远端复查，当前判断还要再改得更精确一点：

- post-fix 之后，当前 live 不是“已经持续产出新 fresh entry，然后质量待评估”
- 而是“当前几乎没有新的 actionable / fresh_entry 样本，最近主要是 management hold 和 blocked long entry”
- 所以当前第一优先级不是继续大改 management
- 也不是继续抽象地优化 first-batch terminal-extension 逻辑
- 而是先把 `candidate -> AI -> risk -> hold` 的当前阻塞链看清楚

就目前数据看，最近更像下面这两类情况：

1. `candidate_filter` 已经给出 `candidate_ok` 或 soft-penalty 可选样本
2. AI 给出 `buy`
3. risk 因 `expected_edge_below_minimum` 或 `open_signal_return_24bars_too_weak` 压回 `hold`

以及：

1. `candidate_filter` 直接在最近几轮把 symbol 过滤成 `low_volume`
2. 或 `short_setup_countertrend_drift` / `short_setup_latest_bar_rebound`
3. 最终形成 `filtered_hold`

相关代码入口：

- 快照和高周期上下文：[src/qount/market.py](../src/qount/market.py)
- AI 前候选过滤：[src/qount/candidate_filter.py](../src/qount/candidate_filter.py)
- 成本感知风控：[src/qount/risk_engine.py](../src/qount/risk_engine.py)
- review 口径：[src/qount/review.py](../src/qount/review.py)

## 2026-05-12 归档 reasoning（不再作为默认执行顺序）

下面这部分保留的是 `2026-05-12` 当时的 edge-first 推理。它仍有参考价值，但**已经不是当前默认推进顺序**。现在默认顺序仍然是上文的：

`fresh-entry timing first -> post-fix review -> 再决定 expected_edge / management`

## 当时 review 后的结论

上一个版本里“继续直接调阈值”的方向太粗了，主要有 3 个问题：

1. `actionable` 样本还不够大，不能急着拆很多分方向门槛
2. 如果把同一组趋势/量能特征同时塞进 `expected_edge` 和 `open_signal_reasons`，会形成双重计数，后续很难解释为什么单被拒
3. 当前主行为是 `position_management -> hold/noop`，只盯着“新开仓阈值”改，可能对真实 live 行为影响很小

当时把计划收回来的原因是：

- **先重构 edge 评分，再决定要不要拆更多门槛**
- **先补 review 切片，再决定要不要放松 short precheck**
- **先避免双重计数，再谈更多复杂打分**

这套思路后来被 `2026-05-14` 的 fresh-entry-first 路线替代，原因不是它逻辑错误，而是 live 证据已经进一步收敛到了：

- 当前最差的是少量 fresh entry timing
- 不是 edge proxy 完全失真
- 也不是 management / executor 主链路失效

## 目标方案

优化后的目标链路仍然是：

`closed 5m bar -> snapshot -> candidate filter -> AI -> explainable cost-aware risk -> execute -> review`

这里的重点不是把 AI 放大，而是：

- AI 继续只在小范围候选里选一个动作
- 风控继续是真正的最终裁决层
- `expected_edge_pct` 要变成更可解释的 post-cost 代理，而不是简单“这根 K 动了多少”

## 设计原则

### 1. 先防小样本过拟合

当前 review 已经能说明“坏单主要在少数 entry”，但还不足以支持一次性拆出很多方向专用参数。

因此：

- 暂时保留一个主 `min_expected_edge_pct`
- 不先引入一堆 `open_long/open_short/add` 专用阈值
- 只有当 review 累积到足够样本后，才考虑拆分方向门槛

### 2. 避免双重计数

同一组特征不应该先在 `expected_edge_pct` 里扣一遍，又在 `open_signal_reasons` / `higher_timeframe_trend_conflict` 里再否一遍。

因此：

- `expected_edge_pct` 只负责给出一个更可解释的 edge proxy
- `open_signal_reasons` 继续保留，但先不额外加更多和 edge 重复的惩罚
- 高周期方向冲突继续保留为硬约束，不和 edge 打分混在一起

### 3. 不同时放松多层 short 保护

当前 short 路径已经有：

- prompt 限制
- candidate precheck
- open signal 检查
- higher timeframe 冲突检查

这些保护是叠加的。没有足够证据前，不应该一边放松 precheck，一边重写 edge，一边再调 threshold。

因此：

- 先保留当前 short precheck
- 只有当 review 明确证明某一类被挡掉的 short 持续是高质量 missed move，才只放松一个具体分支

## 历史分阶段思路（2026-05-12 版）

## 第一阶段：只重构 `expected_edge_pct`

这一阶段只做一件事：

- 把 `risk_engine` 里的 `expected_edge_pct` 改成一个更可解释的 post-cost proxy

### 这一步要做什么

保留现有输入面，不新增新数据源，只用现有 snapshot 指标：

- `atr_14_pct`
- `range_pct`
- `return_24bars`
- `return_1bar`

把它们组合成一个单独的“基础预期移动”项，再减去估算成本。

这一阶段的约束：

- 先不拆分 `buy/sell/add` 专用阈值
- 先不改 `open_signal_reasons`
- 先不改 `higher_timeframe_trend_conflict`
- 先不改 `candidate_filter` 的 short precheck

### 这一步不要做什么

- 不把 `sma_fast_ratio` / `sma_slow_ratio` / `higher_timeframe` / `volume_ratio` 同时塞进 edge 打分和硬拒绝逻辑
- 不引入一堆 edge bonus/penalty 参数
- 不把 `expected_edge_pct` 改成复杂的多段评分器

### 第一阶段完成标准

- `signal-review` 的 `actionable.avg_net_edge_pct` 比当前更好
- `hold.missed_move` 不明显恶化
- `blocked_sell` 没有明显变差
- 拒单原因仍然可解释

## 第二阶段：扩展 review 切片，再决定下一步

在调更多规则之前，先把 review 结果拆清楚。

### 这一步要做什么

继续复用 `signal-review`，但补更适合当前问题的切片，例如：

- `entry` vs `close/management`
- `decision_action=sell` 且被挡掉的样本
- `position_management` 场景下的 hold/close 表现
- 按 `candidate_filter` reason 的聚合

### 为什么先做这个

当前真正不清楚的是：

- edge 差到底主要出在“新开仓”还是“已有仓位管理”
- 被挡掉的 short 到底是该挡，还是确实挡掉了同一种高质量 setup

不先把这个拆开，后面继续调阈值会很容易调偏。

### 第二阶段完成标准

- 能把“entry 问题”和“management 问题”分开看
- 能判断 short precheck 到底是在保护系统，还是在持续错过同类机会

## 第三阶段：只有样本足够时，才拆方向阈值

这一步是条件触发，不是默认立刻做。

### 触发条件

只有当 review 里累积到足够样本，例如：

- `actionable` 总样本明显增多
- `sell` 样本不再只有极少几笔
- 且不同方向的净边际差异持续稳定

才考虑：

- 单独拆 `open long` / `open short` 门槛
- 必要时再拆 `add position` 门槛

### 这一步为什么后置

因为当前直接拆门槛，风险很大：

- 可能只是把噪声固化成参数
- 可能只得到“更少交易”
- 不一定能得到“更好交易”

## 第四阶段：只有证据足够时，才调整 short precheck

这一步也不是默认路线。

### 什么时候才动

只有当第二阶段 review 明确显示：

- 被 `candidate_filter` 挡掉的某一类 short setup
- 持续表现成高质量 `missed_move`
- 且不是偶然几笔

才考虑：

- 把某个具体的 short precheck 分支从硬拒绝改成 soft penalty

### 什么时候不动

如果 review 继续显示：

- `blocked_sell` 大多还是该挡
- 放行的 `sell` 仍然 post-cost 偏弱

那就继续保留当前 precheck，不要动。

## 明确不做

下面这些是 2026-05-12 当时判断“不要立刻做”的事项。到 2026-05-13，保护单已经作为 live 安全修复落地；其余复杂能力仍应按新的专项评审分阶段推进：

- bracket / 保护单
- 复杂组合分配器
- 更多 timeframe 叠加
- 更多 symbol 扩容
- 大规模 schema 改造
- 模型微调

这些都不是当前收益瓶颈，先做只会把系统做重。

## 实施顺序

按这个顺序走：

1. 只重构 `risk_engine` 里的 `expected_edge_pct`
2. 扩展 `signal-review`，把 `entry` / `management` / `blocked_sell` 切片补齐
3. 观察一段真实 live review
4. 只有样本足够时，才考虑拆方向阈值
5. 只有证据足够时，才考虑放松 short precheck

## 成功标准

这次优化是否成功，只看这些：

- `actionable.avg_net_edge_pct` 提升
- `sell` 的净边际不再系统性差于成本
- `flip_rate` 继续下降
- `hold.missed_move` 不明显恶化
- 没有破坏现有 live 安全链路

如果只是“参数更多”“文档更多”“理由更复杂”，但这些指标没改善，那就是无用功。
