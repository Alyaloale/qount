# qount 当前文档

这份文档是当前唯一保留的仓库内文档。

它只回答 4 件事：

1. 现在生产节点在哪
2. 当前 live 到底按什么配置在跑
3. 当前决策流程是什么
4. 最近该怎么解读 `hold/noop`

历史计划、历史复盘、旧调参文档不再保留在仓库里。

## 最新接续摘要（2026-05-23）

当前远端 WSL `.env` 读回：

- `mode=live`
- `market_type=future`
- `QOUNT_RULE_MODE=bottom_line`
- `QOUNT_LIVE_ENABLE=false`
- `qount-runner.timer / qount-runner.service` 均为 `inactive`

当前策略结论：

1. `ETH-only after2` 仍是当前可参考主基线
   - `feb27-after2`: `1 / 1`, `+0.51232666%`
   - `mar06-after2`: `3 / 3`, `+1.35851281%`
   - `mar11-after2 / apr15-after2`: `0 / 0`
2. `after3` 不晋级
   - `feb27` 从好单退化为 `flat`
   - `mar06` 收益大幅收缩到 `+0.47871107%`
   - `apr15` 漏出 `1 / 1 flat` 训练外弱单
3. `after4` 只保留一条训练外漏单修复
   - 新底线 reason：`setup_model_weak_pullback_short_rebound_fail`
   - 只拦 `ETH fresh sell + short_rebound_fail_confirmed + 1h pullback + weak_favorable setup model + 训练统计偏负`
   - WSL `20260523-eth-after4-apr15` 已回到 `0 / 0`

下一步继续推进时，不要再扩大 `short_rebound_fail_confirmed / pullback` 新开仓。应回到 `mar06-after2` 剩余的 `run 123 / run 132`，只做更窄的 close 子类验证，并继续用 `feb27 / mar06 / mar11 / apr15` 四窗一起验收。

## 生产真相

- 唯一生产节点：
  - `WSL /home/alyaloale/Code/qount`
- 唯一生产状态来源：
  - `systemd --user qount-runner.timer`
  - `python -m qount.main preflight-live`
  - `python -m qount.main runtime-status`
  - `state/qount.db`
- `Mac` 本地仓库只是编辑入口，不是生产真相

## 当前 live 基线

截至 `2026-05-18` 当前仓库和远端 WSL 已同步到下面这套基线：

- `QOUNT_MODE=live`
- `QOUNT_LIVE_ENABLE=false`
- `QOUNT_EXCHANGE_ID=binance`
- `QOUNT_MARKET_TYPE=future`
- `QOUNT_SYMBOLS=SOL/USDT,XRP/USDT,BTC/USDT,ETH/USDT`
- `QOUNT_TIMEFRAME=5m`
- `QOUNT_CANDIDATE_TREND_TIMEFRAME=1h`
- `QOUNT_AI_MODEL=gpt-5.4`
- `QOUNT_RULE_MODE=bottom_line`
- `QOUNT_CONTRACT_LEVERAGE=6`
- `QOUNT_CONTRACT_MARGIN_MODE=isolated`
- `QOUNT_MAX_OPEN_POSITIONS=3`
- `QOUNT_MAX_ENTRY_SIZE_PCT=0.30`
- `QOUNT_MAX_RISK_PER_TRADE_PCT=0.01`
- `QOUNT_TRAILING_PROFIT_ARM_PCT=0.0025`
- `QOUNT_TRAILING_PROFIT_RETRACE_PCT=0.0015`
- `HTTP_PROXY=http://192.168.128.1:7907`
- `HTTPS_PROXY=http://192.168.128.1:7907`

## 当前生产状态

截至 `2026-05-18` 当前生产状态是：

- `qount-runner.timer` 已停
- `live_guard` 已停
- 原因是 `live_disabled`
- 当前无持仓
- 当前不允许真实下单

当前主线不是恢复 live，而是先把：

1. `fresh-entry` 质量
2. `management` 提前止损 / 提前保护
3. `SOL/ETH` long re-entry churn

在 `paper/backtest` 里证明后再谈恢复实盘

## 当前流程

当前 live 主链路是：

1. closed `5m` bar -> `snapshot`
2. `candidate_filter` 排序和标注
3. `AI` 选择 symbol 和动作
4. `validate_decision` 规范化字段
5. `risk_engine`
6. `executor`
7. `journal / review`

其中当前最关键的变化是：

- `QOUNT_RULE_MODE=bottom_line`
- 这意味着：
  - `candidate_filter` 不再充当前置裁判，主要负责排序和标注
  - `candidate_filter` 在 `bottom_line` 下默认可把候选池放到 `top 3`，让 `AI` 多看一个符号再自己判断
  - `risk_engine` 不再用旧的启发式条件替 AI 做方向判断

## 当前 bottom_line 含义

在 `bottom_line` 下，rule 层只保留底线约束，例如：

- 日亏损停机
- 系统 `halted`
- 最大持仓数
- 可用余额不足
- 交易所最小名义不满足
- 风险仓位上限
- 同向 / 相关暴露过大
- 开仓必须有正的、可执行的止损

不再默认由 rule 层去做这些方向 veto：

- `expected_edge_below_minimum`
- `open_signal_*`
- fresh-entry 形态 veto
- `min_hold_bars_active`
- supportive close veto
- 旧的 reentry / flip 启发式阻断

## 当前 live 解读口径

`run_id>=2300` 是当前 `bottom_line` 上线后的新 live 样本起点。

到目前为止：

- 最近新样本里，`candidate_filter` 已经会把弱样本送进 AI
- 最近 `hold/noop` 不是 risk 再把 AI 动作压回去
- 最近样本里，AI 自己直接给了 `hold`
- risk 返回的是 `approved` 且 `reasons=["ok"]`

因此当前默认解释应改成：

- 先怀疑 `AI 没看到足够 setup`
- 或者当前市场本身没有足够好的 setup
- 不要再先默认是旧规则层把交易挡掉了

## 2026-05-18 修后完整评估

这轮评估不再只看单笔，而是围绕 `run_id 1997-2403` 拆成 3 个关键窗口，对比：

- 历史真实 live 结果
- 当前代码 `paper backtest`
- 同窗口 `signal-review --horizon-bars 3`

### 关键窗口

| window | CST 时间窗 | 关注交易 |
| --- | --- | --- |
| `w1_eth_short` | `2026-05-17 00:40 -> 02:55` | `ETH short` |
| `w2_sol_xrp_shorts` | `2026-05-17 09:30 -> 10:40` | `SOL short` + `XRP short` |
| `w3_sol_eth_longs` | `2026-05-17 17:20 -> 22:20` | `SOL long` + `ETH long` |

### 修前 / 修后对比

| window | 历史 live 开/平 | 历史 live 已实现PnL | 历史 live 截止浮盈亏 | 修后 backtest 开/平 | 修后 backtest 已实现PnL | 修后 backtest 截止浮盈亏 |
| --- | --- | --- | --- | --- | --- | --- |
| `w1_eth_short` | `1 / 0` | `0` | `-0.61568` | `0 / 0` | `0` | `0` |
| `w2_sol_xrp_shorts` | `2 / 1` | `-0.5139558` | `-0.0331` | `2 / 2` | `+0.0457510` | `0` |
| `w3_sol_eth_longs` | `2 / 1` | `-0.21031725` | `-0.26187718` | `3 / 3` | `-0.30608002` | `0` |

窗口截止口径下，历史 live 合计：

- 开仓 `5`
- 平仓 `2`
- 已实现 `-0.72427305`
- 截止浮盈亏 `-0.91065718`

同口径修后 backtest 合计：

- 开仓 `5`
- 平仓 `5`
- 已实现 `-0.26032902`
- 截止浮盈亏 `0`

这意味着：

- 这轮修正并没有把系统变成“不开仓”
- 也没有把系统修成“刚开就砍”
- 但它已经明显减少了最差的亏损路径

### 各窗口结论

`w1_eth_short`

- 历史是 1 笔 `ETH short`，到窗口截止仍未平，浮亏约 `-0.61568`
- 修后同窗口 `paper backtest` 完全不再开这笔单
- 结论：这次针对 short chase 的修正已经挡掉最差的 `ETH short` 模式

`w2_sol_xrp_shorts`

- 历史里 `SOL short` 是主亏损来源
- 修后不再复刻那笔 `SOL short`
- 修后改成 2 笔 `XRP short`
  - 第一笔：`20` 分钟，盈利 `+0.1848906561`
  - 第二笔：`15` 分钟，亏损 `-0.1391396586`
- 窗口净值从亏损翻成小幅盈利
- 结论：short 侧已经从“连续做错”变成“允许试错，但会更快退出”

`w3_sol_eth_longs`

- 历史里是 2 笔 long：
  - `SOL long` 约 `180` 分钟后亏损平仓
  - `ETH long` 到窗口截止仍在浮亏
- 修后是 3 笔 long：
  - `SOL long`：`40` 分钟，亏 `-0.1816406250`
  - `SOL long` 再入：`5` 分钟，亏 `-0.0534286297`
  - `ETH long`：`10` 分钟，亏 `-0.0710107632`
- 结论：修后 long 侧不再死扛，但出现了 `re-entry churn`

### signal-review 结论

`w1_eth_short`

- 历史 `fresh_entry.avg_net_edge_pct = -0.2167211529`
- 修后没有 fresh-entry 样本

`w2_sol_xrp_shorts`

- 历史 `fresh_entry.avg_net_edge_pct = -0.0129494108`
- 修后 `fresh_entry.avg_net_edge_pct = -0.0491619023`
- 但修后实际 realized 已转正
- 说明这段改善更多来自：
  - 开仓对象变了
  - 管理更快了
  - 不是 review edge 本身已经变漂亮

`w3_sol_eth_longs`

- 历史 `fresh_entry.avg_net_edge_pct = -0.1699322836`
- 修后 `fresh_entry.avg_net_edge_pct = -0.2031318802`
- 修后 `management_hold.reviewed` 从 `64` 缩到 `8`
- 说明 long 侧当前主问题已经从“死扛”切到“fresh-entry 质量弱 + 重开偏多”

## 2026-05-18 long 侧最新同口径重跑

在上面的 long 修正之后，又补了一轮更偏 AI 行为本身的 prompt 收紧，目标不是再加硬 veto，而是让 AI 自己更稳定地放弃：

- 薄边际 long
- `fast SMA` 还没收复的弱 reclaim long
- starter long 开出后 2 根 bar 还没有 follow-through 的被动持有

同样只看 `w3_sol_eth_longs`，并保持相同 `SOL/ETH` universe，三版结果如下：

| variant | artifact | 开/平 | same_symbol_reentry_rate | realized pnl |
| --- | --- | --- | --- | --- |
| `baseline` | `20260517T165442Z-20260517T0920-20260517T1420` | `3 / 3` | `0.3333` | `-0.30608002` |
| `reentry_cooldown_only` | `20260517T170333Z-20260517T0920-20260517T1420` | `2 / 2` | `0.0000` | `-0.32078844` |
| `prompt2_current` | `20260518T-run-current-w3-sol-eth-prompt2` | `1 / 1` | `0.0000` | `-0.01378201` |

这版最新行为变化非常明确：

- 原来 `run 17` / `run 19` 的薄边际 `SOL long` 被 AI 主动放弃
- 第一笔 `SOL long` 被延后到 `run 25`
- 该笔在 `run 27` 很快管理平仓，亏损只有 `-0.01378201`
- 原来 `run 39` 的 `SOL` 同符号再入完全消失
- 原来 `run 53` 的 `ETH long` 也完全消失

这说明：

- 这轮最有效的不是再加一层 hard filter
- 而是把 long 侧“为什么现在不该开 / 为什么不该继续拖”写得更明确，让 AI 自己做出更保守但更一致的判断
- 在 `w3` 这个最差 long 窗口里，这版已经把 realized 亏损从 `-0.30608002` 压到了 `-0.01378201`

### 当前综合判断

当前结论要更新成：

- `short` 侧最差模式仍然是已经收缩的
- `long` 侧最差窗口 `w3` 已经被明显压住
- 最新有效路径不是“再堆规则”，而是更明确地把薄边际 long / 弱 reclaim / 弱 follow-through 的语义交给 AI
- 当前主问题已经从 `SOL/ETH long re-entry churn` 变成：
  - 这版会不会在更长窗口里抓机会太少
  - 以及这种 prompt 驱动改善能不能迁移到更长评估窗口

## 下一步优化方案

下一轮不优先再加新的 hard parameter，而是先做完整效果扩展验证：

1. 用当前 prompt 版重跑更长窗口
   - 目标：验证改善不只停留在 `w3`，同时确认没有退化成“几乎不抓机会”
2. 对比 `w1 / w2 / 更长窗口` 的开仓数和 realized
   - 目标：确认 `short` 侧已有改善不被破坏，`long` 侧压亏损后总净值能否转正
3. 如果更长窗口出现“过度保守”
   - 目标：优先把 `expected_edge / threshold_gap / shadow_open_signal_reasons` 作为 AI 提示补充进去，而不是先回退到更多硬规则

### 下一轮验证门槛

`w1_eth_short`

- 开仓数维持 `0`

`w2_sol_xrp_shorts`

- 窗口 realized 不低于 `0`
- 不要把 `SOL short` 重新放回来

`w3_sol_eth_longs`

- 开仓数维持 `1` 或至少不高于 `2`
- `same_symbol_reentry_rate` 压到 `0`
- realized 亏损至少维持优于 `-0.01378201`
- 不允许退化成“完全不抓任何像样机会”

## 2026-05-18 phasev2 结构化阶段回测结论

这轮不是只改 prompt，而是把文档里的结构化阶段方案往前推进了一步：

- `higher_timeframe` 现在补了 `trend_direction / trend_phase / trend_strength / slope / distance`
- `entry_quality` 现在会给 fresh entry 打 `setup_phase`
- `candidate_filter` 现在会把排序真正按分数顺序送进 AI，而不是只在 summary 里排序
- `bottom_line` 现在不再把 `low_volatility / low_volume / higher_timeframe_unavailable` 这类硬劣质样本继续强塞给 AI
- review 现在会从持久化的 `candidate_filter` 摘要里恢复 `setup_phase / higher_timeframe_phase`

这轮先跑了一个失败版，再修成当前版：

- `20260518-phasev2-w3-sol-eth`
  - `122 runs`
  - `0 开 / 0 平`
  - `realized = 0`
  - 结论：第一版过度保守，long 窗口被直接压成全程 `hold`
- `20260518-phasev2b-w3-sol-eth`
  - `71 runs`
  - `1 开 / 1 平`
  - `realized = -0.01378201`
  - 结论：修正后回到当前 long 侧最优口径，不再是“完全不交易”

同口径补跑 `w1 / w2 / w3` 后，当前版结果是：

| window | artifact | 开/平 | realized pnl | 结论 |
| --- | --- | --- | --- | --- |
| `w1_eth_short` | `20260518-phasev2b-w1-eth` | `0 / 0` | `0` | 继续挡掉最差 `ETH short`，通过 |
| `w2_sol_xrp_shorts` | `20260518-phasev2b-w2-sol-xrp` | `0 / 0` | `0` | 没把 `SOL short` 放回来；相对旧版更保守，但仍满足“不低于 0” |
| `w3_sol_eth_longs` | `20260518-phasev2b-w3-sol-eth` | `1 / 1` | `-0.01378201` | 维持当前最优 long 侧结果，通过 |

### 这轮实际学到的东西

- `trend_phase + setup_phase` 这条路是有效的，但第一版如果同时放宽候选池、又让 AI 看到太多 `range_noise + low_volatility`，会直接把系统压成全程 `hold`
- 真正关键的不是“把更多差样本送进 AI”，而是：
  - 保留 `bottom_line`
  - 但不要把已经明确是硬劣质的样本继续上推
- long 侧 `pullback_reclaim_confirmed` 阈值如果太紧，会只剩极少数可交易样本；稍微放宽后，`w3` 才恢复到 `1` 笔可接受交易
- 当前剩余问题已经从 `w3` 的 long 侧崩盘，切成：
  - `w2` short 侧机会抓得偏少
  - 候选原因里 `low_volatility` 仍然占比过高
  - 后续应该继续查：哪些 `candidate_ok / short_continuation_confirmed / long_pullback_reclaim_confirmed` 其实值得放行

### 2026-05-18 `w2` 后续探索结论

围绕 `w2_sol_xrp_shorts` 又额外试了 3 个变体，但都没有优于 `phasev2b`：

- `20260518-phasev2c-w2-sol-xrp`
  - 做法：prompt 放宽 `short_continuation_confirmed` starter short
  - 结果：恢复 `1` 笔 `XRP short`，但下一根被过早平掉
  - `realized = -0.07677543`
- `20260518-phasev2d-w2-sol-xrp`
  - 做法：继续放宽 short management prompt，不让它因为一根 pause bar 立刻 close
  - 结果：仓位留到窗口结束仍未平，窗口截止浮亏约 `-0.085306`
  - `realized = 0`，但 `final_equity_quote = 199.91469396`
- `20260518-phasev2e-w2-sol-xrp`
  - 做法：加一层很窄的 thesis-aware short continuation close 延后保护
  - 结果：与 `phasev2d` 本质一致，仍然只是把早平改成尾仓未平
- `20260518-phasev2f-w2-sol-xrp`
  - 做法：恢复 `short_continuation_confirmed` starter short 放行，并把过早 `close` 改成 thesis-aware reject
  - 结果：比 `phasev2c` 略好，但仍是亏损平仓
  - `realized = -0.05971422`

结论更新成：

- `w2` 目前最稳的版本仍然是 `phasev2b`
- 问题已经证明不是“把 short continuation 更容易放行”就能解决
- 也不是“把第一根管理 close 延后一根”就能解决
- 甚至“starter short 放行 + 半成品 thesis-aware close reject”也仍然跑不过 `phasev2b`
- 当前更值得投入的下一步不再是 prompt 微调，而是文档里原计划的：
  - 真正把 `entry_thesis` 持久化给 management
  - 让管理判断基于“原始 setup 是否失效”，而不是只看当前一根 bar

### 2026-05-18 phasev3 实现状态

这轮已经把“完整版 `entry_thesis` 持久化 + thesis-invalidated management”真正接进代码，不再只是 prompt 实验：

- `risk_engine`
  - fresh entry 会生成结构化 `entry_thesis`
  - management 现在会读取上一次 open 的 `entry_thesis`
  - 支持：
    - `AI close` 但 thesis 仍成立 -> reject close
    - `AI hold` 但 thesis 已失效 -> force close
- `orchestrator`
  - 会把最终生效的 `entry_thesis` 写回 `validated.raw_payload`
- `executor`
  - open fill 的 `raw` 现在也带 `entry_thesis`
- `journal`
  - `get_recent_signal_actions()` 现在会把 `entry_thesis` 连同 `entry_setup_phase / higher_timeframe_phase` 一起带出来
- `review`
  - 现在有 `by_entry_thesis`

本地回归测试口径已扩到 `100` 条，并通过：

- `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization`

### phasev3 窗口结果

| window | artifact | 开/平 | realized pnl | 结论 |
| --- | --- | --- | --- | --- |
| `w2_sol_xrp_shorts` | `20260518-phasev3-w2-sol-xrp` | `0 / 0` | `0` | thesis-aware 代码已生效，但真实窗口结果仍回到 `phasev2b` 的保守基线 |
| `w3_sol_eth_longs` | `20260518-phasev3-w3-sol-eth` | `1 / 1` | `-0.01378201` | 维持 long 侧当前最优结果，没有被新 management 打坏 |

同轮又补了一个很窄的结构化增强：

- `20260518-phasev3b-w2-sol-xrp`
  - 做法：把 `entry_thesis_candidate` 提前放进 `candidate_context`，让 AI 在开仓前就看到同一套 thesis 结构
  - 结果：`0 / 0 / 0`
  - 结论：仅靠“把 thesis 结构更早暴露给 AI”本身，不足以改变 `w2` 的 entry 行为

这意味着：

- `entry_thesis` 基础设施已经具备
- 但当前 phase-specific invalidation 阈值还不够“赚钱”，它更多是让行为回到 `phasev2b` 的安全面
- 把 thesis 结构前置给 AI 也已经试过，但单靠这一招还不够
- 之后如果要继续推进，不该再先做“是否持久化”这种基础设施，而该直接做：
  - 各个 thesis 类型的失效条件精修
  - `by_entry_thesis` 真正对照哪类 setup 有正边际

### 2026-05-20 phasev4 收紧 long reclaim 结果

在把 `entry_thesis` 基础设施接完之后，这轮继续推进的是：

- 不再把 `1h trend` 阶段、且已经明显站上双均线、`return_24bars` 已偏正、`RSI` 偏高的 long 样本继续归类成 `long_pullback_reclaim_confirmed`
- 这类样本现在改判为 `long_late_breakout_chase`

直接验证结果：

| window | artifact | 开/平 | realized pnl | 结论 |
| --- | --- | --- | --- | --- |
| `w3_sol_eth_longs` | `20260520-phasev4-w3-sol-eth` | `0 / 0` | `0` | 砍掉了此前那笔小亏 long，窗口从 `-0.01378201` 提到 `0` |
| mixed `4sym/120bars` | `20260520-phasev4g-mixed-4sym-120bars` | `0 / 0` | `0` | 把 `phasev3g` 的 `-0.23424486` 拉回到 `0` |

同轮也验证了一个失败分支：

- `20260520-phasev4b-w2-sol-xrp`
  - 在 `phasev4` 基线上重新加回窄 `short_continuation_confirmed` 提示
  - 结果又回到旧的 `1 开 / 1 平 / realized = -0.07677543`
  - 结论：这条短空 prompt 放权路径依然不值得保留，已回退

后来又补了一轮：

- `20260520-phasev4e-w2-sol-xrp`
  - 条件：在完整 `entry_thesis` close reject 已生效的版本上，再验证同一条窄 short continuation 提示
  - 结果：`1 开 / 1 平 / realized = -0.05971422`
  - 结论：比纯 prompt 放权版 `-0.07677543` 略好，但仍然不盈利，因此也不保留在当前基线
- `20260520-phasev4f-w2-sol-xrp`
  - 条件：再次确认同一条短空 thesis，在真实同步后的完整链路里重跑
  - 结果：仍然是 `1 开 / 1 平 / realized = -0.05971422`
  - 结论：这已经排除了“之前是远端代码没同步”的可能，说明 `short_continuation_confirmed` 本身在这段 `w2` 里就是不赚钱

当前结论更新成：

- `phasev4` 已经把当前可见的亏钱 long reclaim 样本清掉
- 现在系统在已验证窗口上已经从“亏损”提升到“至少不亏”
- `short_continuation_confirmed` 在当前已验证 `w2` 窗口里，即便叠加 thesis-aware close reject，仍然没有跑出正收益
- 因此下一步不该再继续围绕 `short_continuation_confirmed` 打补丁，而该把主要火力切到 `short_rebound_fail_confirmed` 或其它 short thesis
- 但还没有找到稳定正收益的 thesis，下一步仍然应该围绕：
  - `short_rebound_fail_confirmed`
  - 以及 `by_entry_thesis` 真实样本扩充
  继续做更有针对性的多空边际筛选

### 2026-05-21 short 侧继续推进

这轮继续验证 short 侧到底该往哪条 thesis 推：

1. `short_continuation_confirmed`

- 重新在完整 `entry_thesis` 管理链路上复跑：
  - `20260520-phasev4e-w2-sol-xrp`
  - `20260520-phasev4f-w2-sol-xrp`
- 结果一致：
  - `1 开 / 1 平`
  - `realized = -0.05971422`
- 结论：
  - 这已经排除了“是同步问题/偶发问题”的可能
  - `short_continuation_confirmed` 在当前 `w2` 里仍然不赚钱
  - 这条路彻底降级为次优，不再继续围绕它打补丁

2. `short_breakdown_confirmed`

这轮新增了一条更贴近历史盈利样本的 short thesis：

- `short_breakdown_confirmed`
  - 目标不是追 terminal flush
  - 而是抓：
    - `1h short trend`
    - `5m` 强势向下动量
    - 有量能
    - 但最新收盘没有完全钉死在最低点

当前状态：

- 代码里已经接入：
  - `entry_quality`
  - `candidate_filter`
  - `entry_thesis` / invalidation
  - `review` 映射
- 同时补了 prompt 语义，让 AI 把它当成“可交易 breakdown”，不是单纯 terminal flush

但这轮验证结果还不够：

- `20260521-phasev6-w2-sol-xrp`
  - `0 / 0 / 0`
- `20260521-phasev6c-short-breakdown-window`
  - `4sym`
  - `09:40 -> 10:10`
  - `0 / 0 / 0`
- `20260521-phasev6e-short-breakdown-run26-window`
  - `4sym`
  - `10:20 -> 10:40`
  - `0 / 0 / 0`
- `20260521-phasev6f-w2-4sym`
  - `4sym`
  - `09:30 -> 10:40`
  - `0 / 0 / 0`

结论更新成：

- `short_breakdown_confirmed` 已经是当前最值得继续做的 short thesis
- 但第一版、第二版阈值 + prompt 还不足以把它转成真钱单
- 它现在更像是一个“已经能在离线识别里命中目标样本，但还不够说服 AI 下单”的半成品 thesis
- 下一步如果继续推进盈利，优先级应改成：
  - 继续精修 `short_breakdown_confirmed`
  - 再考虑 `short_rebound_fail_confirmed`
  - 暂时不再投入 `short_continuation_confirmed`

### 2026-05-21 candidate entry viability preview

这轮没有把 rule 层重新做回前置 veto，而是补了一层只给 AI 看的候选可交易性预览：

- `orchestrator` 现在会在送给 AI 的 `candidate_context` 里补 `entry_viability_preview`
- 这层预览来自当前 `risk_engine` 的现成计算，但只作为诊断，不会直接替 AI 做开仓裁决
- 预览里现在会给出：
  - `preview_action`
  - `entry_archetype`
  - `expected_edge.final_expected_edge_pct`
  - `expected_edge.required_threshold_pct`
  - `expected_edge.required_threshold_gap_pct`
  - `expected_edge.edge_surplus_pct`
  - `shadow_open_signal_reasons`
  - `portfolio_pressure`

这层的目标不是“重新加规则”，而是解决当前 short 侧最典型的问题：

- `short_breakdown_confirmed` 已经能被离线识别
- 但 AI 看到的仍主要是阶段标签，不够直观看出“这笔单离可交易阈值到底差多少”
- 因此这轮改成把 `expected_edge / threshold_gap / shadow_open_signal_reasons` 直接前置给 AI

当前状态：

- 本地回归测试已扩到 `108` 条，并通过：
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization`
- 已确认新字段会真正进入 AI bundle，不只是留在 summary / review 里

当前阻塞：

- 这轮尝试在 `Mac` 本机直接跑 `w2` 短窗 backtest，但未能完成
- 阻塞不是策略逻辑，而是当前本机网络链路：
  - `192.168.128.1:7907` Binance 代理超时
  - `192.168.128.1:8318/v1/models` relay 也超时
- 因此这轮还不能宣称“短窗已验证盈利改善”
- 下一步真实窗口验证应改到：
  - 先恢复本机到 relay / Binance 的链路
  - 或直接回到 `WSL` 生产节点上重跑同窗口验证

### 2026-05-21 传统方法 + 通用 `1h` 回归模型结果

这轮沿着“传统方法 + AI + 小模型”继续推进，先后做了两层增强：

1. `traditional_signal_context`

- 给 `candidate_context` 增加经典结构语义：
  - `failed_rebound_breakdown`
  - `fresh_support_break`
  - `failed_breakdown_reclaim`
  - `fresh_resistance_reclaim`
- 同时给出：
  - `conviction_score`
  - `terminal_risk`
  - `range_expansion_ratio`
  - `compression_score`
- 目标是让 AI 不再只看 `setup_phase`，而能看到更传统的形态解释

2. 通用 `1h` ridge 回归模型

- 新增了 `train-hourly-model`
- 用最近 `120` 天 `1h` OHLCV，按 symbol 训练预测未来 `3` 根 `1h` 收益的轻量 ridge 模型
- 训练结果：
  - `SOL/USDT:USDT`
    - `samples=2860`
    - `mae_pct=0.0083617`
    - `directional_accuracy=0.50699`
  - `XRP/USDT:USDT`
    - `samples=2860`
    - `mae_pct=0.0076352`
    - `directional_accuracy=0.50629`
  - `BTC/USDT:USDT`
    - `directional_accuracy=0.49860`
  - `ETH/USDT:USDT`
    - `directional_accuracy=0.49580`
- 这层模型现在会作为 `higher_timeframe.model_signal` 注入 snapshot，供 candidate 排序和 AI 一起使用

### `w2` 重跑结果

在 `traditional_signal_context + higher_timeframe.model_signal` 都接进去之后，又重跑了：

- `artifact`
  - `20260521-traditional-hourly-model-w2`
- `window`
  - `2026-05-17 09:30 -> 10:40 CST`

结果：

- `runs_completed = 30`
- `paper_filled = 1`
- `paper_closed = 1`
- `final_equity_quote = 199.6150830422696`
- `total_realized_pnl_quote = -0.3849169577304112`
- `total_return_pct = -0.1924584788652055`

行为变化：

- 这次终于不再是全程 `hold`
- `XRP/USDT:USDT` 在 `1778985000000` 这条原本的 `missed_move` 样本上，AI 确实开出了 `sell`
- 但后续这笔 short 实际变成亏损平仓：
  - `review_action = sell`
  - `outcome = bad`
  - `avg_loss_pct = 0.5405574168`
- 下一根管理 `close` 只拿回了一点，整轮最终仍是亏损

### 这轮结论

这轮最重要的结论不是“模型没用”，而是：

- `traditional_signal_context` + 通用 `1h` 回归，已经足以把系统从“完全不出手”推到“会出手”
- 但这版通用 `1h` 回归模型质量太弱，不能直接作为进场推动器
- 它更像一个很粗的 soft second opinion，而不是可直接决定开仓的 alpha

因此下一步不该是继续扩大这版通用 `1h` 回归的权重，而该转成更窄的建模方向：

1. 只针对当前真实 setup 建模
   - `short_breakdown_confirmed`
   - `short_rebound_fail_confirmed`
   - `long_pullback_reclaim_confirmed`
2. 按 symbol 单独建模
   - 至少先拆 `SOL/XRP` 与 `BTC/ETH`
3. 训练目标改成更贴近执行
   - 未来 `3-6` 根 `5m` 的 post-cost edge
   - 或 `good_trade / bad_trade / should_hold`
4. 让模型只在强质量时发声
   - 不再默认所有训练出的模型都进入 live decision
   - 先加准确率 / edge 门槛，再决定是否给 AI 看

### 2026-05-21 `5m setup` 监督模型结果

在确认通用 `1h` 回归只能把系统从“完全不出手”推到“会亏钱地出手”之后，这轮继续往更窄的方向推进：

- 新增了 `train-setup-model`
- 训练对象不再是泛化方向，而是：
  - `symbol + setup_phase`
  - 目标是未来 `3` 根 `5m` 的 post-cost edge
- 当前接入方式：
  - runtime 会把它作为 `candidate_context.setup_model_signal`
  - 它只做 soft second opinion，不直接替 AI 开平仓

#### 第一轮：覆盖样本多的 setup

用最近 `120` 天训练、`min_samples=40` 后，真正样本足够的只有：

- `long_pullback_reclaim_confirmed`
- `short_rebound_fail_confirmed`

结果几乎一致：

- `BTC/ETH/SOL/XRP` 上，这些 setup 的 `avg_target_edge_pct` 全是负的
- 方向准确率虽然看起来在 `0.73 ~ 0.81`
- 但那主要反映“多数样本本来就是负 edge”，不代表它们值得交易

这轮实际意义是：

- 它明确告诉我们：当前代码口径下，`short_rebound_fail_confirmed` 和 `long_pullback_reclaim_confirmed` 不能再被默认当成“高概率赚钱 setup”

#### 第二轮：单独拉 `short_breakdown_confirmed`

因为 `w2` 的关键问题就是 `XRP short_breakdown_confirmed`，又单独补训了一版：

- `lookback_days=180`
- `min_samples=8`
- `setup_phase=short_breakdown_confirmed`

结果：

- `BTC/USDT:USDT`
  - `samples=15`
  - `positive_edge_rate=0.1333`
  - `avg_target_edge_pct=-0.0013144`
- `ETH/USDT:USDT`
  - `samples=15`
  - `positive_edge_rate=0.3333`
  - `avg_target_edge_pct=-0.0010919`
- `SOL/USDT:USDT`
  - `samples=14`
  - `positive_edge_rate=0.4286`
  - `avg_target_edge_pct=-0.0005392`
- `XRP/USDT:USDT`
  - `samples=16`
  - `positive_edge_rate=0.3125`
  - `avg_target_edge_pct=-0.0010380`

这说明：

- `short_breakdown_confirmed` 在这几个币上不是“缺少放权”的问题
- 而更像是：
  - 样本极少
  - 平均 post-cost edge 为负
  - 默认就不该被当成赚钱主力 thesis

#### 用这层模型重跑 `w2`

这轮又专门用 `short_breakdown_confirmed` 的 setup 模型重跑：

- `artifact`
  - `20260521-setup-model-short-breakdown-w2`
- 同时临时关闭通用 `1h` 模型，只保留：
  - `traditional_signal_context`
  - `setup_model_signal`

结果：

- `runs_completed = 29`
- `paper_filled = 0`
- `paper_closed = 0`
- `final_equity_quote = 200.0`
- `total_realized_pnl_quote = 0`
- `total_return_pct = 0.0`

和上一轮对比：

- `traditional + hourly`
  - 会开出 `XRP short`
  - 最终亏损 `-0.38491696`
- `traditional + setup_model(short_breakdown)`
  - 不再开这笔 `XRP short`
  - 回到 `0 / 0 / 0`

#### 当前更新后的结论

当前结论要再收紧一层：

- `short_breakdown_confirmed` 不是现在最该继续放权的赚钱 short thesis
- 它更像一个：
  - 样本少
  - 平均 post-cost edge 为负
  - 容易在局部窗口里看起来“像机会”，但真实执行后并不赚钱

所以接下来如果继续推进盈利，不该再围绕 `short_breakdown_confirmed` 做更多放权或 prompt 鼓励，而该转去：

1. 寻找新的 short thesis
   - 不再默认从 `breakdown_confirmed` 继续深挖
   - 优先从更多历史样本里找更稳定的 short setup
2. 用 `setup_model` 做“反向筛掉负期望 setup”
   - 当前它已经证明很适合干这个
   - 先别急着让它“推动开仓”
3. 下一轮更值得建模的对象是：
   - `多样本、正 edge、低 giveback` 的 setup
   - 而不是“只是刚好在某个坏窗口里看起来像该做”的 setup

### 2026-05-21 `higher_phase` 分裂训练结果

在上面的 `setup-edge-study` 跑完之后，又继续做了一步更细的验证：

- 新增了 `train-setup-model --split-higher-phase`
- 允许同一个 `symbol + setup_phase` 再按：
  - `trend`
  - `pullback`
  - `reclaim`
  继续拆子模型

原因很直接：

- `setup_phase` 总体为负
- 不代表它在某个 `higher_timeframe_phase` 子集里也为负

这轮先只看：

- `setup_phase = short_rebound_fail_confirmed`
- `horizon_bars = 6`

结果里唯一真正站到正侧的是：

- `ETH/USDT:USDT`
  - `setup_phase = short_rebound_fail_confirmed`
  - `higher_timeframe_phase = reclaim`
  - `samples = 21`
  - `positive_edge_rate = 0.428571`
  - `avg_target_edge_pct = +0.00021923`

其余子集仍然都是负的，例如：

- `XRP short_rebound_fail + reclaim`
  - `samples = 26`
  - `avg_target_edge_pct = -0.00044805`
- `SOL short_rebound_fail + reclaim`
  - `samples = 27`
  - `avg_target_edge_pct = -0.00149029`
- `BTC short_rebound_fail + reclaim`
  - `samples = 20`
  - `avg_target_edge_pct = -0.00161319`

这说明：

- “`short_rebound_fail_confirmed` 值不值得做”这个问题，不能只看 setup_phase 总体均值
- 真正可能值得继续推进的是：
  - `ETH`
  - `1h reclaim`
  - `6 bars` 持有
  这一条极窄子集

### 当前更新后的推进方向

当前最值得继续往下做的，不再是：

- 泛化 `1h` 模型
- 泛化 `short_breakdown_confirmed`
- 泛化 `short_rebound_fail_confirmed`

而是：

1. 针对 `ETH short_rebound_fail_confirmed + 1h reclaim + horizon 6` 做定点验证
2. 把 phase-split setup model 当成：
   - 窄 alpha 候选筛选器
   - 而不是全局开仓推动器
3. 继续寻找是否还有别的：
   - `symbol + setup_phase + higher_phase + horizon`
   子集能站到正的 post-cost edge

### 2026-05-21 `ETH short_rebound_fail + 1h reclaim + horizon 6` 定点验证

在发现：

- `ETH`
- `short_rebound_fail_confirmed`
- `higher_timeframe_phase = reclaim`
- `horizon = 6`

是当前唯一站到正 `avg_target_edge_pct` 的窄子集之后，这轮又继续做了定点窗口验证。

#### 先做 `weak_favorable / strong_favorable` 分层

为了避免把“略正但不稳”的样本和“明显更强”的样本混在一起，这轮又把 `setup_model_signal` 继续细分成：

- `strong_favorable`
- `weak_favorable`

当前口径：

- `strong_favorable`
  - `predicted_edge_pct >= 0.0025`
  - `confidence_ratio >= 1.5`
  - `positive_edge_rate >= 0.40`
  - `avg_target_edge_pct > 0`
- `weak_favorable`
  - 方向虽正，但 edge 薄或统计不稳
  - 默认仍优先等待

也就是：

- `strong_favorable` 才真正推动开仓
- `weak_favorable` 只算“可以再观察”，不再默认放权

#### 3 个定点窗口结果

`window-a`

- 时间窗：
  - `2026-03-06 16:35 -> 18:05 CST`
- 关键样本：
  - `1772787900000`
  - `target_edge_pct = +0.0108385`
  - `traditional_pattern = failed_rebound_breakdown`
  - `conviction_score = 0.814421`
- v2 结果：
  - `1` 笔 `ETH short`
  - 当前窗口截止仍持有
  - `final_equity_quote = 200.48856348`
  - `total_return_pct = +0.24428174`
  - review 里这笔 entry 是 `good`

`window-b`

- 时间窗：
  - `2026-02-27 07:40 -> 09:15 CST`
- 关键正样本：
  - `1772151000000`
  - `target_edge_pct = +0.0047266`
  - `conviction_score = 0.646547`
- 第一版行为：
  - 更早在 `1772150400000` 就开 short
  - 只做到 `flat`
- v2 行为：
  - 不再更早开
  - 延后到 `1772151000000` 才开
  - 该笔 review 已转成 `good`
  - `final_equity_quote = 201.13784521`
  - `total_return_pct = +0.56892260`

`window-c`

- 时间窗：
  - `2026-05-06 12:35 -> 14:05 CST`
- 关键样本：
  - `1778043900000`
  - `target_edge_pct = +0.0028323`
  - `conviction_score = 0.480324`
- v2 结果：
  - `0` 开仓
  - `0 / 0 / 0`
  - 全部 `good_hold`

#### 当前更新后的判断

这轮已经把主线再收紧了一层：

- 当前最值得继续推进的，不是泛化 `short_rebound_fail_confirmed`
- 而是：
  - `ETH`
  - `1h reclaim`
  - `failed_rebound_breakdown`
  - 且 `setup_model_signal = strong_favorable`
  这一条很窄的 short thesis

同时也学到两点：

1. 不是所有正样本都值得直接放权
   - `window-c` 说明：
     - 样本虽然为正
     - 但 conviction 不够高时，继续 `hold` 更好
2. “延后 1 根 bar 再入”是真有价值的
   - `window-b` 从原来的偏平，修成了正 edge

#### 下一步最合理的推进

当前最值得做的是：

1. 把这条窄 thesis 从“定点窗口验证通过”扩到更长 ETH-only 窗口
2. 检查它在多周样本里是否还能维持：
   - 正 realized
   - 低 giveback
   - 不过度空窗
3. 如果更长 ETH-only 窗口也稳定，再考虑：
   - 是否把它接入当前更大的 `SOL/XRP/BTC/ETH` 候选池
   - 但也只作为窄 short special-case，而不是泛化 short 主逻辑

### 2026-05-22 ETH-only 长窗口验证

为了确认上面的定点正样本不是偶然，这轮继续把同一条窄主线放进更长的 `ETH-only` 窗口：

- 统一口径：
  - `QOUNT_SYMBOLS=ETH/USDT`
  - `QOUNT_HOURLY_MODEL_ENABLE=false`
  - `QOUNT_SETUP_MODEL_ENABLE=true`
  - `QOUNT_SETUP_MODEL_PATH=state/models/setup_edge_model_short_rebound_phase6.json`
  - `QOUNT_MAX_OPEN_POSITIONS=1`
  - `review_horizon_bars=6`

#### window-feb27-long

- 时间窗：
  - `2026-02-27 02:10 -> 14:15 CST`
- 结果：
  - `final_equity_quote = 200.55055114`
  - `total_return_pct = +0.27527557`
  - `paper_filled = 1`
  - `paper_closed = 1`
  - `missed_move = 17`
  - `actionable avg_giveback_pct = 0.00716092`
- 解读：
  - 这条线在更长窗口里仍能盈利
  - 交易次数很少
  - giveback 很低
  - 说明这更像“窄而稳”的机会捕捉，不是高频 churn

#### window-mar06-long

- 时间窗：
  - `2026-03-06 11:05 -> 23:05 CST`
- 结果：
  - `final_equity_quote = 201.21854785`
  - `total_return_pct = +0.60927393`
  - `paper_filled = 5`
  - `paper_closed = 5`
  - `wins = 3`
  - `losses = 2`
  - `missed_move = 42`
  - `actionable avg_giveback_pct = 0.28485459`
  - `same_symbol_reentry_rate = 0.6`
- 解读：
  - 整体窗口仍然盈利
  - 但这段明显更容易过度交易
  - giveback 和 re-entry 都偏高
  - 说明这条线一旦放进更长窗口，仍需要进一步约束重复开空和管理拖延

### 当前更新后的结论

这轮长窗口验证把结论再推进了一步：

- `ETH + short_rebound_fail_confirmed + 1h reclaim + horizon 6`
  已经不只是“定点样本可行”，而是：
  - `window-feb27-long` 为正
  - `window-mar06-long` 也为正
- 这说明它已经是当前最值得继续扩展的窄 short 主线

但同时也暴露出新的真实问题：

- 不是“能不能开出第一笔”
- 而是：
  - 长窗口里是否会过度 re-entry
  - 是否会把已得浮盈回吐太多

因此下一步最值得做的，不再是继续找 entry，而是围绕这条 ETH-only 线做两件事：

1. 限制同一条 ETH reclaim short 的重复再入
   - 尤其是连续 `sell -> close -> sell` 的过密循环
2. 更早锁住浮盈
   - 避免 `good entry` 最后被管理拖回去

### 2026-05-22 网络重试与 `v3` 长窗口复验

这轮又补了一层基础设施修正：

- 给 `backtest / setup-edge-study / train-setup-model` 的 `load_markets()` 和历史 `fetch_ohlcv()` 接了共享网络重试
- 目标是吸收当前 WSL 链路里偶发的：
  - `SSL EOF`
  - `Max retries exceeded`

这层补完后，长窗口研究/回测已经不再像之前那样一开始就直接因为 `load_markets()` 抖动失败。

同时又继续把 ETH-only 长窗口重跑了一轮：

- `artifact`
  - `20260522-eth-longwindow-feb27-v3`
  - `20260522-eth-longwindow-mar06-v3`

#### `feb27`：修后反而退化

`window-feb27-long-v3`

- 时间窗：
  - `2026-02-27 02:10 -> 14:15 CST`
- 结果：
  - `final_equity_quote = 199.88634489`
  - `total_return_pct = -0.05682756`
  - `paper_filled = 2`
  - `paper_closed = 2`
  - `same_symbol_reentry_rate = 0.0`
  - `actionable avg_giveback_pct = 0.14164871`
  - `missed_move = 14`

对比上一版：

- `v2`
  - `+0.27527557%`
  - `1 / 1`
  - `avg_giveback_pct = 0.00716092`
- `v3`
  - `-0.05682756%`
  - `2 / 2`
  - `avg_giveback_pct = 0.14164871`

说明：

- 这轮修正虽然继续压住了“平后马上再入”的一类问题
- 但它也把 `feb27` 从单次稳健盈利，带成了两次动作后的小亏

后续继续拆 `feb27-v3` / `v4` 后，这条线又补了一轮 `v5`：

- 新增修正：
  - `candidate_filter` 不再把“最近一次动作”误读成中间的 `hold`
  - same-symbol reentry cooldown 现在明确基于最近一次 `close`
  - `ETH range_noise` short 只有更强的结构性 breakdown 才允许送进 AI
  - `short_rebound_fail_confirmed` 如果 setup-model 明确 `unfavorable`，直接不送进 fresh entry

`window-feb27-long-v5`

- 结果：
  - `final_equity_quote = 200.56358895`
  - `total_return_pct = +0.28179448`
  - `paper_filled = 1`
  - `paper_closed = 1`
  - `same_symbol_reentry_rate = 0.0`
  - `actionable avg_giveback_pct = 0.06198956`
  - `missed_move = 11`

和 `v4` 对比：

- `v4`
  - `+0.25772141%`
  - `2 / 2`
  - `avg_giveback_pct = 0.15656259`
  - `missed_move = 15`
- `v5`
  - `+0.28179448%`
  - `1 / 1`
  - `avg_giveback_pct = 0.06198956`
  - `missed_move = 11`

这说明：

- `feb27` 的剩余坏单根因已经基本找到了
- 真正有效的是：
  - 不让 `unfavorable` 的 `short_rebound_fail_confirmed` 再去 fresh entry
  - 不让弱 `range_noise` short 混进来

后续继续把 `ETH reclaim short` 的 profit-protection close 再收紧后，又补了一轮：

`window-feb27-long-v6`

- 结果：
  - `final_equity_quote = 200.54394464`
  - `total_return_pct = +0.27197232`
  - `paper_filled = 1`
  - `paper_closed = 1`
  - 仍然有 `1` 笔 `bad close`

结论：

- 仅靠“下行动量仍在时，不要太早 risk close”这条规则，还不足以消掉 `feb27` 的剩余坏平仓

继续再收窄后：

`window-feb27-long-v7`

- 结果：
  - `final_equity_quote = 201.02465331`
  - `total_return_pct = +0.51232666`
  - `paper_filled = 1`
  - `paper_closed = 1`
  - `same_symbol_reentry_rate = 0.0`
  - `actionable avg_giveback_pct = 0.17875970`
  - `missed_move = 13`
  - `bad = 0`
  - `flat = 1`

这版相比 `v5` / `v6` 的关键变化是：

- `bad close` 被消掉了
- 窗口总收益进一步抬高
- 当前剩余的不是“明显错误的平仓”，而是还有一笔 `flat close`

#### `mar06-v6` / `mar06-v7`

在同一轮管理优化中，`mar06` 又连续重跑了两版：

`window-mar06-long-v6`

- `final_equity_quote = 202.05288993`
- `total_return_pct = +1.02644497`
- `paper_filled = 3`
- `paper_closed = 3`
- `same_symbol_reentry_rate = 0.0`
- `actionable avg_giveback_pct = 0.20693536`
- `bad = 3`
- `flat = 0`

这版的特点是：

- re-entry 已经完全压到 `0`
- 交易数继续收缩
- 收益继续抬高
- 但仍然还有几笔明显偏早的 `management close`

继续把“下行动量还在时不要太早 risk close”加进去之后：

`window-mar06-long-v7`

- `final_equity_quote = 202.87313558`
- `total_return_pct = +1.43656779`
- `paper_filled = 5`
- `paper_closed = 5`
- `same_symbol_reentry_rate = 0.2`
- `actionable avg_giveback_pct = 0.25875877`
- `bad = 4`
- `flat = 1`

### 当前更新后的判断

这轮长窗结果说明：

- 对 `feb27`
  - 最新管理修正是明确有效的
  - `bad close` 已经被消掉
- 对 `mar06`
  - 最新修正把总收益继续抬高了
  - 但同时又把交易数、坏 close、giveback 带高了一些

因此当前最重要的结论是：

- `ETH reclaim short` 这条线已经是当前最赚钱的窄主线
- 但“收益最高”不等于“管理已经最稳”
- 现在真正该拆的，不再是 fresh entry
- 而是：
  - `mar06-v7` 里那几笔 `bad/flat close`
  - 尤其是 AI 主动 close 与 risk close 各自什么时候该让步

### 2026-05-22 管理 close 继续细化后的 `v8`

在把：

- `ETH` 盈利空单
- `AI close`
- 以及 `risk profit-protection close`

继续按“反转是否真的确认”拆开之后，又补了一轮：

`window-mar06-long-v8`

- `artifact`
  - `20260522-eth-longwindow-mar06-v8`
- 结果：
  - `final_equity_quote = 202.79893682`
  - `total_return_pct = +1.39946841`
  - `paper_filled = 4`
  - `paper_closed = 4`
  - `same_symbol_reentry_rate = 0.25`
  - `actionable avg_giveback_pct = 0.25875877`
  - `bad = 3`
  - `flat = 1`
  - `good = 4`

和 `mar06-v7` 对比：

- `v7`
  - `+1.43656779%`
  - `5 / 5`
  - `bad = 4`
  - `flat = 1`
  - `same_symbol_reentry_rate = 0.2`
- `v8`
  - `+1.39946841%`
  - `4 / 4`
  - `bad = 3`
  - `flat = 1`
  - `same_symbol_reentry_rate = 0.25`

这说明：

- 最新的 AI-close 保护确实吃掉了一部分“太早平仓”
- `bad close` 数量下降了
- 但也轻微牺牲了总收益
- 说明这一步已经进入：
  - `收益`
  - `坏单数量`
  - `回撤/回吐`
  三者之间的 tradeoff 区

继续再只收 `AI close` 这一类之后，又重跑了：

`window-mar06-long-v9`

- `final_equity_quote = 203.45894346`
- `total_return_pct = +1.72947173`
- `paper_filled = 5`
- `paper_closed = 5`
- `same_symbol_reentry_rate = 0.2`
- `actionable avg_giveback_pct = 0.22477128`
- `bad = 3`
- `flat = 2`
- `good = 5`

和 `v8` 对比：

- `v8`
  - `+1.39946841%`
  - `4 / 4`
  - `actionable avg_giveback_pct = 0.25875877`
  - `bad = 3`
  - `flat = 1`
- `v9`
  - `+1.72947173%`
  - `5 / 5`
  - `actionable avg_giveback_pct = 0.22477128`
  - `bad = 3`
  - `flat = 2`

进一步拆分后，当前 `mar06-v9` 剩余 close 的责任已经非常清楚：

- `AI close 太早`
  - `run 100`
  - `run 131`
  - `run 21` (`flat`)
- `risk close 太早`
  - `run 110` (`flat`)

这说明：

- 再细分 `AI close` 这条线，仍然能继续提高收益
- 但它不会自动减少所有 `bad/flat close` 的数量
- 当前已经进入更细的子类优化阶段：
  - `trend + range_noise` 的 AI close
  - `exhaustion + short_breakdown_chase` 的 AI close
  应该分开处理，而不是继续共用一条规则

#### `mar06-v10` / `mar06-v11` 纠偏验证

这轮继续往下拆时，先暴露出一个关键口径问题：

- 远端 `.env` 里默认是 `QOUNT_RULE_MODE=bottom_line`
- 而这次新增的 `ETH short AI close` 窄管理修正都挂在 `not bottom_line_rules`
- 所以最先跑出来的 `mar06-v10` 虽然收益更高，但实际上根本没有启用到这两条新规则

`mar06-v10`（`bottom_line` 口径）：

- `artifact`
  - `20260522-eth-longwindow-mar06-v10`
- 结果
  - `total_return_pct = +1.84883463%`
  - `paper_filled = 5`
  - `paper_closed = 5`
  - `actionable avg_giveback_pct = 0.22118879`
  - `bad = 3`
  - `flat = 2`
  - `same_symbol_reentry_rate = 0.2`
- 但 `run 100 / 131` 仍然还是原样 `ai_close -> bad`
  - `risk_reasons = ["ok"]`
  - 说明这版不能拿来判断新规则是否有效

因此又按相同窗口，补跑了真正启用窄管理规则的：

- `QOUNT_RULE_MODE=strict`
- `artifact`
  - `20260522-eth-longwindow-mar06-v11`

`mar06-v11`（`strict` 口径）结果：

- `total_return_pct = +0.98551276%`
- `paper_filled = 3`
- `paper_closed = 3`
- `actionable avg_giveback_pct = 0.15920941`
- `bad = 3`
- `flat = 0`
- `missed_move = 19`
- `same_symbol_reentry_rate = 0.0`

这说明：

- `trend + range_noise` 这条窄规则是生效的
  - `run 100` 从 `ai_close -> bad` 变成了 `management_close_rejected_eth_short_trend_range_noise_reversal_not_confirmed -> good_hold`
  - 同类 `run 101` 也一起被挡住
- `exhaustion + short_breakdown_chase` 这条线只挡住了第一拍
  - `run 131` 被 `min_hold_bars_active:1<2` 挡成了 `good_hold`
  - 但下一根又在 `run 132` 变成了新的 `ai_close -> bad`
  - 新坏样本已经从 `short_breakdown_chase + exhaustion` 演化成了 `range_noise + exhaustion`
- `risk close` 也出现了新的坏样本
  - `run 103`
  - `management_entry_thesis_invalidated:directional_follow_through_lost`

### 当前统一结论

现在需要把结论改成两条明确口径，而不是再混用一组 `v7/v8/v9/v10/v11` 名字：

- `live / bottom_line` 口径
  - 当前远端 `.env` 真实默认值仍是 `QOUNT_RULE_MODE=bottom_line`
  - 所以如果目标是贴近当前 live 执行形态，收益参考应看：
    - `mar06-v10`
    - `+1.84883463%`
  - 但这版不能拿来证明新加的 `ETH short AI close` 窄管理规则是否有效
- `strict / 窄规则验证` 口径
  - 如果目标是验证这轮 `AI close` 子类拆分是否真的命中样本，应看：
    - `mar06-v11`
    - `run 100` 已被成功挡住
    - `run 131` 第一拍也被挡住
  - 但它的总代价是：
    - `total_return_pct` 掉到 `+0.98551276%`
    - 交易数降到 `3 / 3`

因此当前更准确的统一判断是：

- `ETH reclaim short` 这条线已经有稳定赚钱能力
- 但文档和回测必须严格区分：
  - `盈利参考`
  - `规则验证`
- 这轮 `AI close` 细分不是无效
  - `trend + range_noise` 已经打中
- 目前真正剩下的主问题已经变成：
  - `exhaustion` 里 flush 之后的下一根弱反弹 AI close
    - `run 132`
  - `risk_close` 的 `directional_follow_through_lost`
    - `run 103`

下一步应继续只拆：

1. `exhaustion + range_noise` 的 AI close
2. `risk_close` 里 `directional_follow_through_lost` 这一类

而不是再回头重调已经打中的 `trend + range_noise`。

#### `mar06-v5b`

在同一轮修正下，又重跑了：

- `artifact`
  - `20260522-eth-longwindow-mar06-v5b`

结果：

- `final_equity_quote = 201.90804763`
- `total_return_pct = +0.95402381`
- `paper_filled = 4`
- `paper_closed = 4`
- `same_symbol_reentry_rate = 0.25`
- `actionable avg_giveback_pct = 0.20773388`
- `missed_move = 19`

和 `mar06-v4` 对比：

- `v4`
  - `+0.93491837%`
  - `6 / 6`
  - `same_symbol_reentry_rate = 0.16666667`
  - `avg_giveback_pct = 0.23116388`
  - `missed_move = 26`
- `v5b`
  - `+0.95402381%`
  - `4 / 4`
  - `same_symbol_reentry_rate = 0.25`
  - `avg_giveback_pct = 0.20773388`
  - `missed_move = 19`

这说明：

- 这轮对 `mar06` 也是净改善
- 交易数从 `6` 收到 `4`
- 总收益继续抬高
- giveback 继续下降
- missed_move 也明显下降

### 当前更新后的判断

`ETH reclaim short` 这条线现在的状态可以更新成：

- `entry` 侧已经明显变好
  - `feb27-v5` 相比 `v4` 更稳
  - `mar06-v5b` 相比 `v4` 也更好
- 当前剩余最主要的问题，不再是“又开了不该开的第二笔 short”
- 而是：
  - `management close` 的时机仍然不够优
  - 尤其是 `feb27-v5` 里那笔唯一 remaining `bad`，已经更像“平得不够好”而不是“开得不该开”

因此下一步不该再优先收紧 entry，而该把优化主火力切到：

1. `ETH reclaim short` 的管理退出时机
   - 什么时候该让盈利单继续拿
   - 什么时候该保护性 close
2. 识别“风险 close 太早”与“风险 close 太晚”
   - 当前已经能看出这类管理误差在吃掉 edge

#### `mar06`：修后改善

`window-mar06-long-v3`

- 时间窗：
  - `2026-03-06 11:05 -> 23:05 CST`
- 结果：
  - `final_equity_quote = 201.55160419`
  - `total_return_pct = +0.77580209`
  - `paper_filled = 7`
  - `paper_closed = 7`
  - `wins = 5`
  - `losses = 2`
  - `same_symbol_reentry_rate = 0.42857143`
  - `actionable avg_giveback_pct = 0.22174557`
  - `missed_move = 26`

对比上一版：

- `v2`
  - `+0.60927393%`
  - `5 / 5`
  - `same_symbol_reentry_rate = 0.6`
  - `avg_giveback_pct = 0.28485459`
  - `missed_move = 42`
- `v3`
  - `+0.77580209%`
  - `7 / 7`
  - `same_symbol_reentry_rate = 0.42857143`
  - `avg_giveback_pct = 0.22174557`
  - `missed_move = 26`

说明：

- 这轮修正对 `mar06` 是有效的
- re-entry 降了
- giveback 降了
- 总收益升了
- missed_move 也明显减少

### 当前更新后的结论

这轮最关键的结论是：

- 共享网络重试已经值得保留
- `ETH reclaim short` 本身也仍然是当前最好的窄主线
- 但它对不同窗口的反应并不稳定：
  - `mar06` 受益
  - `feb27` 退化

因此下一步最值得做的，不是继续扩大这条线，而是进一步把：

- `entry` 触发条件
- 和 `re-entry` 触发条件

再拆得更细，尤其要解释：

- 为什么 `feb27` 里会从 `1` 笔好交易，变成 `2` 笔后小亏
- 哪一笔新增交易其实不该开

## 2026-05-22 reclaim short 管理回归

这轮没有再去放宽新的 fresh-entry，也没有再围绕单个短窗加 prompt 补丁。

改动点只落在 `risk_engine` 的 `entry_thesis` 管理层：

- 对盈利中的 `ETH`
- 原始开仓 thesis 是：
  - `short_rebound_fail_confirmed`
  - 或 `short_continuation_confirmed`
  - 且 `entry_higher_timeframe_phase = reclaim`
- 如果当前仍满足：
  - `1h` 仍是 `short`
  - `sma_slow_ratio < 0`
  - 没有出现真正确认的强反转
  - 并且当前短侧结构仍然有延续压力

则不再因为 setup 临时退化成 `range_noise`，就把盈利单过早 `AI close` / `thesis invalidated` 掉。

这轮目标不是“让系统多开单”，而是：

1. 先把当前最赚钱窄主线的管理误杀降下来
2. 同时确认不会把训练外窗口也带成过度交易

### 本地与远端验证

- 本地回归测试：
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization`
  - `130` 条通过
- 远端 WSL 同口径回归：
  - 同样 `130` 条通过

### `bottom_line` + `ETH-only` + `setup_edge_model_short_rebound_phase6`

统一验证口径：

- `QOUNT_RULE_MODE=bottom_line`
- `QOUNT_SYMBOLS=ETH/USDT`
- `QOUNT_MAX_OPEN_POSITIONS=1`
- `QOUNT_HOURLY_MODEL_ENABLE=false`
- `QOUNT_SETUP_MODEL_ENABLE=true`
- `QOUNT_SETUP_MODEL_PATH=state/models/setup_edge_model_short_rebound_phase6.json`
- `review_horizon_bars=6`

结果：

| window | 开/平 | total_return_pct | same_symbol_reentry_rate | 备注 |
| --- | --- | --- | --- | --- |
| `feb27-long` | `1 / 1` | `+0.51232666%` | `0.0` | 已验证盈利窗口未退化 |
| `mar06-long` | `4 / 4` | `+1.39946841%` | `0.25` | 赚钱窗口仍保住，但 `giveback / bad close` 仍偏高 |
| `mar11-long` | `0 / 0` | `0` | `-` | 训练外负样本长窗未被放大成乱开单 |
| `apr15-long` | `0 / 0` | `0` | `-` | 训练外长窗仍偏保守，没有新坏单 |

补充读法：

- `feb27-long`
  - `good = 1`
  - `bad = 0`
  - `flat = 1`
- `mar06-long`
  - `good = 4`
  - `bad = 3`
  - `flat = 1`
  - `avg_giveback_pct = 0.33877346`
- `mar11-long / apr15-long`
  - 都回到 `0 / 0 / 0`
  - 说明这轮改动至少没有把训练外窗口带成过度交易

### 这轮结论

这轮更准确的结论是：

- 这不是新的 alpha 扩张
- 这是对当前 `ETH reclaim short` 盈利主线的一次管理稳定化
- 它已经证明：
  - 已知盈利窗口没有被打坏
  - 训练外窗口没有被放大成乱开仓
- 但它也同时暴露：
  - 训练外窗口目前还是偏保守
  - `mar06` 的主要问题仍然是 `giveback / bad close`
  - 也就是：
    - 当前瓶颈已经不是“会不会乱开”
    - 而是“赚到后能不能拿得更稳”

因此下一步不该回头继续堆 entry 放权，而应继续拆：

1. `ETH reclaim short` 盈利单的 profit-protection / AI close 子类
2. 哪些 `bad close` 真的是反转确认，哪些只是短期噪音
3. 在不破坏 `mar11 / apr15` 这种训练外平稳性的前提下，再考虑是否扩大正样本覆盖

### 2026-05-22 bottom_line 管理延伸

在上面的版本上，这轮又继续推进了一步，但仍然没有去放宽 fresh-entry：

- `entry_thesis` 管理保护不再只覆盖：
  - `ETH`
  - `higher_timeframe_phase = reclaim`
- 现在进一步扩到：
  - `ETH`
  - `short_rebound_fail_confirmed / short_continuation_confirmed`
  - `higher_timeframe_phase in {reclaim, trend}`
- 同时把原来只在 `strict` 验证口径下生效的两条 ETH short 提前平仓保护，接到了当前真实 `bottom_line` 路径：
  - `trend + range_noise` 的 AI close reject
  - `exhaustion + breakdown flush` 的 AI close reject

这轮目的仍然不是“多开单”，而是：

1. 把当前 live 默认 `bottom_line` 口径，真正对齐到已经验证过有效的 ETH short 管理保护
2. 继续压 `mar06` 里那几笔过早 close
3. 同时确认训练外长窗没有被带成过度交易

#### 本地 / 远端回归

- 本地：
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization`
  - `131` 条通过
- WSL：
  - 同样 `131` 条通过

#### `bottom_line` + `ETH-only` + `setup_edge_model_short_rebound_phase6` 二次重跑

结果：

| window | 开/平 | total_return_pct | same_symbol_reentry_rate | 备注 |
| --- | --- | --- | --- | --- |
| `feb27-after2` | `1 / 1` | `+0.51232666%` | `0.0` | 与上一版持平，没有退化 |
| `mar06-after2` | `3 / 3` | `+1.35851281%` | `0.0` | 收益略降，但坏单数和 re-entry 继续下降 |
| `mar11-after2` | `0 / 0` | `0` | `-` | 训练外负样本长窗继续稳定 |
| `apr15-after2` | `0 / 0` | `0` | `-` | 训练外长窗继续稳定 |

和上一版相比，`mar06` 的关键变化是：

- `paper_filled / paper_closed`
  - `4 / 4` -> `3 / 3`
- `same_symbol_reentry_rate`
  - `0.25` -> `0.0`
- `bad`
  - `3` -> `2`
- `flat`
  - 维持 `1`
- `total_return_pct`
  - `+1.39946841%` -> `+1.35851281%`

这说明：

- 这轮不是单纯“收益最大化”
- 而是用小幅收益回吐，换来了：
  - 更少的重复交易
  - 更少的坏平仓
  - 更贴近“真钱可用”的管理行为

#### `mar06-after2` 剩余问题

当前 `mar06` 里剩下的 3 个主要样本已经收缩成：

1. `run 97`
   - `short_continuation_confirmed`
   - 仍然是坏 fresh-entry
   - 说明 `pre_break_continuation` 这条 ETH short 入口线还没有被证明稳定赚钱
2. `run 123`
   - `trend + range_noise`
   - `flat close`
   - 说明趋势内的保护性平仓还有一类“平得不差，但仍然偏早”
3. `run 132`
   - `exhaustion + range_noise`
   - `bad close`
   - 说明 `run 131` 那类 exhaustion flush 提前平仓虽然被延后一拍，但下一根仍然可能太早 close

因此下一步优先级要继续收紧成：

1. 不再默认继续放权 `short_continuation_confirmed`
   - 它现在更像残余坏开仓来源，而不是明确的赚钱入口
2. 继续拆 `ETH` 盈利 short 的 close 子类
   - 尤其是：
     - `trend + range_noise`
     - `exhaustion` flush 之后的下一拍 `range_noise`
3. 继续坚持同一条验证纪律
   - 先看 `feb27 / mar06`
   - 再看 `mar11 / apr15`
   - 不允许为了修 `mar06` 再把训练外窗口带活成乱交易

## 2026-05-23 ETH reclaim short 管理继续收窄

这轮继续沿用上一节结论：不再放宽新的 fresh-entry，也不扩大 `short_continuation_confirmed` 的开仓权重，只处理已盈利 `ETH` short 的管理误杀。

本轮代码改动只落在 `risk_engine` 管理层：

1. `exhaustion + range_noise` 的 AI close
   - 之前只挡住了 `exhaustion + short_breakdown_chase` 的第一拍 flush
   - 下一根如果退化成 `range_noise`，但仍满足：
     - `1h` 还是 `short + exhaustion`
     - `sma_slow_ratio < 0`
     - `24bar` 仍有足够下行
     - 不是强反转 bar
     - 仓位已有盈利
   - 现在会拒绝 AI 的过早 `close`
   - 新 reason：
     - `management_close_rejected_eth_short_exhaustion_range_noise_reversal_not_confirmed`
2. `short_continuation_confirmed` 的 `directional_follow_through_lost`
   - 只在 `ETH`
   - 只在开仓 thesis 是 `short_continuation_confirmed`
   - 只在仓位已盈利、`1h` 仍偏空、`sma_slow_ratio` 未被收复时生效
   - 单根弱反弹不再直接触发：
     - `management_entry_thesis_invalidated:directional_follow_through_lost`
   - 如果出现强反转、慢均线收复、RSI 明显转强，仍允许 close

本轮验证：

- 本地回归：
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization`
  - `134` 条通过
- WSL 回归：
  - `PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization`
  - `134` 条通过
  - `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
  - `140` 条通过

#### WSL `after3` 长窗验证结论

同步到 WSL 后，按同一口径补跑：

- `QOUNT_RULE_MODE=bottom_line`
- `QOUNT_SYMBOLS=ETH/USDT`
- `QOUNT_MAX_OPEN_POSITIONS=1`
- `QOUNT_HOURLY_MODEL_ENABLE=false`
- `QOUNT_SETUP_MODEL_ENABLE=true`
- `QOUNT_SETUP_MODEL_PATH=state/models/setup_edge_model_short_rebound_phase6.json`
- `review_horizon_bars=6`

结果：

| window | 开/平 | total_return_pct | entry review | 结论 |
| --- | --- | --- | --- | --- |
| `20260523-eth-after3-feb27` | `1 / 1` | `+0.45704399%` | `flat=1` | 相比 after2 的 `+0.51232666% / good` 退化 |
| `20260523-eth-after3-mar06` | `1 / 1` | `+0.47871107%` | `good=1` | 坏单消失，但收益从 after2 的 `+1.35851281%` 大幅收缩 |
| `20260523-eth-after3-mar11` | `0 / 0` | `0` | `-` | 训练外负样本仍稳定 |
| `20260523-eth-after3-apr15` | `1 / 1` | `+0.15416464%` | `flat=1` | 训练外窗口从 `0 / 0` 漏出一笔弱单 |

因此 `after3` 不能晋级为新基线：

- 它没有证明 `mar06-after2` 的 `run 123 / run 132` 被更好地处理
- 它把 `feb27` 从原本更干净的好单拖成 flat
- 更重要的是，`apr15` 漏出了一笔 `1h pullback + short_rebound_fail_confirmed + weak_favorable setup model` 的弱 ETH short

#### 2026-05-23 `after4` 训练外漏单修复

针对 `apr15-after3` 的 `run 17`，补了一条很窄的 candidate 底线：

- 只作用于：
  - `ETH/USDT:USDT`
  - fresh `sell`
  - `setup_phase = short_rebound_fail_confirmed`
  - `higher_timeframe_phase = pullback`
  - setup model 为 `weak_favorable`
  - 且训练统计本身偏弱：
    - `positive_edge_rate < 0.30`
    - 或 `avg_target_edge_pct <= 0`
- 新 reason：
  - `setup_model_weak_pullback_short_rebound_fail`
- 这条 reason 已放入 `bottom_line` hard reason，避免 weak pullback short 在当前 live 默认口径下继续被送给 AI。

验证：

- 本地：
  - `tests.test_strategy_optimization`
  - `135` 条通过
  - `unittest discover -s tests`
  - `141` 条通过
- WSL：
  - `tests.test_strategy_optimization`
  - `135` 条通过
  - `unittest discover -s tests`
  - `141` 条通过
- WSL targeted backtest：
  - `20260523-eth-after4-apr15`
  - `paper_filled / paper_closed = 0 / 0`
  - `total_return_pct = 0`
  - `run 17` 已变成 `filtered_hold`
  - candidate reason 命中：
    - `setup_model_weak_pullback_short_rebound_fail`

这轮结论：

- 当前优化仍然不是“多开单”
- 而是继续减少 `ETH reclaim short` 盈利单的过早退出
- 风险边界保持不变：
  - 不把 `range_noise` 变成新的开仓 thesis
  - 不放宽训练外窗口
  - 不改变 `candidate_filter` 的排序/标注角色
- `after3` 不晋级；当前更稳妥的策略判断是：
  - `after2` 仍是 `feb27 / mar06` 的主参考
  - `after4` 只证明了 `apr15` 的弱 pullback short 漏单已修掉
  - 下一步如果继续推进，应重新围绕 `mar06-after2` 的 `run 123 / run 132` 做更窄的 close 子类验证，不要再扩大 `short_rebound_fail_confirmed` / `pullback` 新开仓

## 2026-05-18 趋势判断与建平仓设计方案

当前代码并不是完全不看趋势，而是：

- `1h` 只给了一个很粗的 `trend_bias=long/short/flat`
- `5m` 已经有 `entry_quality`，但更偏“晚不晚、追不追”的形态判断
- `management` 主要还是看当前 `5m` 是否 adverse/supportive，没有和“这笔仓本来为什么开”强绑定

这会导致一个典型问题：

- 系统能知道“现在偏多”
- 但不一定能知道“这是主升延续、回调重建、弱反抽，还是已经接近衰竭”
- 于是容易把“方向偏多”误当成“已经确认到值得建仓”

### 设计目标

下一轮不再把趋势判断理解成“预测未来”，而是改成：

1. 用已收盘的 `1h` bar 判断大方向和大阶段
2. 用已收盘的 `5m` bar 判断是否进入可建仓阶段
3. 建仓时记录本次开仓 thesis
4. 平仓时按 thesis 是否失效来处理，而不是只看当前一根 bar

也就是把现在的“方向感驱动”升级成“阶段确认驱动”。

### 当前不足

当前最需要补的 3 个缺口是：

1. `higher_timeframe` 信息太粗
   - 现在只有 `return_12bars / sma_fast_ratio / sma_slow_ratio / rsi_14 / trend_bias`
   - 它只能回答“偏多还是偏空”，不能回答“处于趋势、回调、重建、震荡、衰竭”的哪一段
2. `entry_quality` 还不等于完整 setup phase
   - 现在已经能分 `continuation_watch` 和 `terminal_extension`
   - 但还没有明确地区分：
     - `reclaim_confirmed`
     - `reclaim_not_confirmed`
     - `continuation_confirmed`
     - `range_noise`
3. `management` 没有 thesis 绑定
   - 现在 `risk_engine` 里的 `management_signal` 主要靠 `return_1bar / return_24bars / fast/slow SMA / trend_bias`
   - 但它不知道这笔仓原本是：
     - 回调重建单
     - 延续单
     - 反转单
   - 所以容易被“1h 方向还没坏”拖着继续 hold

### 目标结构

#### 1. higher timeframe context v2

在 `src/qount/market.py` 里，把现在的 `higher_timeframe` 从单个 `trend_bias` 扩成下面这些字段：

- `trend_direction`
  - `long / short / flat`
- `trend_phase`
  - `trend`
  - `pullback`
  - `reclaim`
  - `range`
  - `exhaustion`
- `trend_strength`
  - 用于表达方向一致性和斜率强弱
- `fast_sma_slope`
- `slow_sma_slope`
- `distance_to_fast_sma`
- `distance_to_slow_sma`
- `distance_from_12bar_extreme`

这样 `1h` 就不只是“偏多”，而是能表达：

- `1h long trend`
- `1h long pullback`
- `1h long reclaim`
- `1h long exhaustion`

#### 2. 5m setup phase

在 `src/qount/entry_quality.py` 里，把 fresh entry 判断从“是否 terminal”升级成“当前处在什么 setup phase”。

目标新增的 setup phase：

- `long_continuation_confirmed`
- `long_pullback_reclaim_confirmed`
- `long_pullback_reclaim_unconfirmed`
- `long_late_breakout_chase`
- `short_continuation_confirmed`
- `short_rebound_fail_confirmed`
- `short_breakdown_chase`
- `range_noise`

核心原则：

- `1h` 负责方向和大阶段
- `5m` 负责是否真的进入可开仓阶段
- 方向正确但阶段未确认，默认仍应 `hold`

#### 3. candidate_filter 只做“阶段匹配排序”

在 `src/qount/candidate_filter.py` 里，不把 filter 重新做回旧式前置裁判，而是改成更清楚的 phase-match 评分。

目标行为：

- `1h long trend/pullback` + `5m reclaim_confirmed/continuation_confirmed`
  - 排名靠前
- `1h long` + `5m reclaim_unconfirmed`
  - 可送 AI，但显著降权
- `1h long exhaustion` + `5m late_breakout_chase`
  - 送 AI 时明确标成弱样本，默认低优先级
- `1h flat/range`
  - 默认不优先开新仓，除非 `5m` 结构特别干净

也就是：

- `candidate_filter` 继续负责排序和标注
- 不直接替 AI 做最终方向判断
- 但必须把“现在是趋势中的哪一段”讲清楚

#### 4. AI 决策使用结构化趋势语义

AI 侧继续保留当前方向：

- 规则层是 safety floor
- AI 负责 entry / hold / close 判断

但 prompt 和 snapshot 里要增加更明确的结构化语义：

- 大方向是什么
- 大阶段是什么
- 当前 5m setup 是否已确认
- 这是“趋势确认单”还是“弱重建候选”
- 本次如果开仓，失效条件大概是什么

AI 的目标不该是“猜未来涨跌”，而该是：

- 只有当 `1h direction` 和 `5m phase` 一致时才优先建仓
- 只有当 `post-cost edge` 明显强于 `hold` 时才建仓
- 如果只是方向没坏，但阶段没确认，则优先 `hold`

#### 5. 开仓时记录 thesis

下一轮需要在开仓时把 thesis 记录下来，至少包含：

- `entry_thesis.direction`
- `entry_thesis.higher_timeframe_phase`
- `entry_thesis.setup_phase`
- `entry_thesis.trigger_bar_timestamp`
- `entry_thesis.invalidation_type`
- `entry_thesis.follow_through_bars`

建议 thesis 先落在：

- `validated.raw_payload`
- `journal` 的 open action 记录
- review 报表里可回放字段

这样 management 才能知道：

- 这笔单是“trend continuation”
- 还是“pullback reclaim”
- 还是“reversal attempt”

#### 6. 平仓改成 thesis-invalidated 驱动

`src/qount/risk_engine.py` 里的 management 下一轮要从“看起来不太好”升级成“原始 thesis 已失效”。

建议按开仓类型拆：

- `continuation long`
  - 2 根 `5m` 没有 follow-through
  - 或重新跌回 `fast SMA` 下
  - 或 trigger bar 被吃回
  - 则优先 close
- `pullback reclaim long`
  - reclaim 后不能站稳 `fast SMA`
  - 或量能跟不上
  - 或重新测试前低失败
  - 则优先 close
- `continuation short`
  - 同理按反方向处理

关键点不是更激进止损，而是：

- 开仓理由是什么
- 该理由是否还成立

### 实施顺序

为了避免一口气改乱，按下面顺序做：

1. 扩 `higher_timeframe` 结构
   - 先补 `direction / phase / strength / slope / distance`
2. 扩 `entry_quality`
   - 把 `continuation / reclaim / chase / range_noise` 结构化
3. 扩 `candidate_context`
   - 把“当前阶段”和“确认/未确认”显式送进 AI
4. 给 open position 记录 `entry_thesis`
5. 把 management 改成 thesis-invalidated close
6. review 增加 `by_entry_thesis` / `by_setup_phase`

### 验证口径

验证不只看单窗口盈亏，还要同时看：

- 开仓数是否明显下降到“完全不抓机会”
- `same_symbol_reentry_rate` 是否继续维持低位
- `realized / unrealized pnl`
- `fresh_entry.avg_net_edge_pct`
- `management` 是否更早承认 thesis 失效
- `by_entry_thesis` 是否能看出哪类 setup 真的有正边际

下一轮验证应至少覆盖：

- `w1_eth_short`
- `w2_sol_xrp_shorts`
- `w3_sol_eth_longs`
- 以及一段更长的 mixed window

### 本轮设计结论

这轮设计不主张：

- 继续简单加硬参数
- 继续只用 `trend_bias=long/short/flat` 做多空判断
- 继续把平仓主要交给“1h 方向还没坏”

这轮设计主张：

- 用 `1h` 判断方向和大阶段
- 用 `5m` 判断 setup 是否确认
- 用 `entry_thesis` 决定后续平仓
- 用 AI 负责最终决策，但必须给 AI 更清楚的结构化趋势语义

## 当前常用命令

看 live 健康：

```bash
ssh -o ClearAllForwardings=yes home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main preflight-live | python3 -m json.tool'"
```

看运行状态：

```bash
ssh -o ClearAllForwardings=yes home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main runtime-status | python3 -m json.tool'"
```

看 timer：

```bash
ssh -o ClearAllForwardings=yes home "wsl.exe bash -lc 'systemctl --user status qount-runner.timer --no-pager --full | sed -n \"1,30p\"'"
```

手动跑一轮：

```bash
ssh -o ClearAllForwardings=yes home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && ./.venv/bin/python -m qount.main run-once | python3 -m json.tool'"
```

## 文档策略

从现在开始，仓库内文档只做当前态维护：

- 当前状态写这里
- 大改动后的新结论也写这里
- 不再新建阶段计划文档
- 不再在仓库里保留 archive 入口

如果要回看历史：

- 看 `git`
- 看 `state/qount.db`
- 看远端实际运行结果
