# qount 盈利优化 / 研究方案

> **状态**：frozen（line A legacy，历史研究线已归档）｜索引见 [archive/README.md](../../README.md)｜当前事实以 [current.md](../../../current.md) 为准。

创建时间：2026-05-30

目标：把 qount 从当前 **research-only、整体不盈利** 的状态，推进到一个
**手续费后期望为正、能过 promotion gate** 的策略基线。

本文件只写“怎么把策略做到盈利”的研究路线。它不改变以下既有事实，也不允许绕开它们：

- live 继续关闭（`QOUNT_LIVE_ENABLE=false`），不 forward paper。
- 当前结论仍以 [current.md](../../../current.md) 为准，操作细节看 [quick-handoff.md](../../../quick-handoff.md)。
- 任何 gate / 模型 / prompt 变更必须先写单测，再跑完整 walk-forward，再写回 `current.md`。
- 不把 `0/0` 窗口或 `total_return_pct` 当盈利证据。

---

## 1. 当前诚实基线（不要美化）

最新有效 13-window chronological walk-forward（`gpt-5.5`）：

```text
window_count=13
positive_realized_windows=2/13
total_paper_filled=4
sum_realized_return_pct=+1.6184470183%
```

全部正收益集中在 `wf-mar06`、`wf-apr15`，其余 11 个窗口 0 交易 / 0 收益。
这不是“稳定盈利”，是“有历史盈利样本”。

`current.md` 已经做过分层根因，本方案直接采用它的结论作为约束，不重复推导：

1. **alpha 太稀疏**：946 cycles 只有 4 次 fresh open。
2. **broad setup 手续费后期望为负**：`range_noise / short_rebound_fail / pullback / short_breakdown` 的 `avg_target_edge_pct` 都 < 0。
3. **成本是关键阻力但不是唯一**：把 fee/slippage 设 0 后，broad setup 仍只接近 breakeven。
4. **AI 非确定性是局部问题**，已用窄 override 修掉，不是整体不盈利主因。
5. **最大风险是为了增频放宽 broad gate**，那会把负期望样本重新放进交易链路。

> 核心判断：现在继续在负期望样本上调阈值是死路。必须改成 **寻找 / 转化新的正期望
> alpha**，且每一步都用完整 `candidate -> AI -> validate -> risk -> execute` 链路的
> realized return 来证伪，而不是只看离线 slice 的 `avg_target_edge_pct`。

---

## 2. 已知的、尚未被吃掉的正期望线索

离线 discovery 已经反复确认下面这些 **手续费后正期望、且跨时间折稳定** 的子切片
（来源：`current.md` 的 multi-range-action / eth-reclaim-long / eth-range-action 复核）：

| 线索 | 最强 horizon | 证据强度 | 现状 |
| --- | --- | --- | --- |
| `sell + range_noise + pullback + sma_fast_ratio>0.008`（multi） | h6/h12 `+0.0031 / +0.0054`，min-fold 正 | 强（h6/h12 都站住） | 从未经过交易链路 realized-return 转化 |
| `range + return_24bars>0.012`（multi/eth） | h6/h12/h24 正 | 中（h24 min-fold 偶尔负） | 覆盖几乎为 0 |
| `sell + range_noise + pullback + sma_slow_ratio>0.008`（eth） | h12/h24 正，min-fold 正 | 中 | snapshot/AI/risk 三层覆盖均为 0 |
| `ETH long_pullback_reclaim + failed_breakdown + sma_slow>0.004 + return1bar(0,0.0004]` | h6/h24 正且 min-fold 正 | 弱（n=5） | 覆盖极低 |

两个反复出现的**结构性矛盾**，是本方案要解决的真问题：

- **A. horizon 错配**：setup model 训练在 `horizon_bars=6`（30 分钟），但上面这些
  edge 普遍在 **h12/h24（1–2 小时）** 才最强。当前 trailing
  (`arm=0.0018 / retrace=0.003`) + `min_hold_bars=2` 把持仓压在短周期，
  很可能在 edge 真正展开前就退出。
- **B. 覆盖错配**：强子切片在当前 walk-forward 窗口里覆盖≈0，所以
  `shadow_candidate_readiness` 永远 `no_ready_tags`。但每个 OOS 窗口只有
  3–12 小时，rare slice 永远攒不够 `min_samples=8 × positive_windows>=2`。
  **不是策略没机会，是评测窗口太碎，永远证不出来。**

---

## 3. 方案总览：四条并行、可独立证伪的工作流

每条工作流都遵守同一个纪律：**离线 edge → 链路覆盖 → shadow readiness →
realized-return 转化 → 窄 gate**，任何一步不过就停在该步，不进下一步。

优先级（高 → 低，按“低风险高杠杆”排序）：

```text
WS-1 持仓 horizon 对齐    （低风险，直接测已知 h12/h24 edge 能否转化）
WS-2 成本结构与最小边际   （低风险，提高每笔期望）
WS-3 覆盖方法学修正       （解锁 readiness，不改任何交易行为）
WS-4 多币 / reclaim-long alpha 转化（中风险，真正扩 alpha 密度）
```

WS-1/2/3 都是 **不改 candidate eligibility** 的研究口径变更，可以并行。
WS-4 是唯一会动候选生成层的工作流，必须等 WS-1/2/3 给出明确读数后再做，且仍走 shadow-proof。

---

### WS-1：持仓 horizon 对齐（先做）

**假设**：当前 realized return 偏弱，部分原因是退出过早，在 edge（h12/h24）展开前平仓。
把训练 horizon 和退出参数对齐到 edge 实际所在的 horizon，realized return 应改善，
且不需要放宽任何入场。

**只改这些（研究口径，不碰 eligibility）**：

- setup model 训练 `--horizon-bars 12`（对照 6）。
- 退出参数对照：`trailing_profit_arm_pct / trailing_profit_retrace_pct /
  min_hold_bars`，让 trailing 在 h12 edge 上不被噪声打掉。

> ⚠️ **前提（已核对代码，必读）**：`main.py:144,149` 先 `Settings.from_env()`
> 再 `apply_research_profile()`。`eth-only` profile 用 `replace()` **硬覆盖**
> `trailing_profit_arm_pct=0.0018`、`trailing_profit_retrace_pct=0.003`、
> `ai_temperature=0.0`（`research_profile.py:48-50`）。所以
> **在 `--research-profile eth-only` 下用 `QOUNT_TRAILING_*` env 改 trailing 是无效的**，
> 会被 profile 静默盖回基线，实验测不到任何东西。
>
> 只有 profile **没设的字段**才会保留 env，例如 `QOUNT_MIN_HOLD_BARS`、
> `QOUNT_MIN_EXPECTED_EDGE_PCT`。`--horizon-bars` 作为 CLI 参数显式传时会覆盖
> profile（`setup_model_horizon_bars_for_profile` 里 explicit 优先），所以 h12 训练本身没问题。

**2026-05-30 已落地推荐路径**：`walk-forward` / `backtest` 支持
`--trailing-arm-pct / --trailing-retrace-pct`，并在 profile 应用之后再 `replace()`，
所以命令行覆盖会赢过 `eth-only` profile 默认值。artifact 的 `audit_context` 会记录
最终生效的 trailing 值，跑完先核对这里。

如果需要临时绕开这条 CLI 路径，剩余 fallback 是：

- 或临时改 `research_profile.py` 的 `ETH_ONLY_TRAILING_*` 常量跑探针，跑完还原（git 可回退）。
- 或**不用 profile**，手动用 env 复刻 eth-only 形状
  （`QOUNT_MARKET_TYPE=future`、`QOUNT_SYMBOLS=ETH/USDT`、`QOUNT_MAX_OPEN_POSITIONS=1`、
  `QOUNT_SETUP_MODEL_ENABLE=true`、`QOUNT_AI_TEMPERATURE=0`、加上要测的 `QOUNT_TRAILING_*`），
  风险是容易和 4-symbol live 形状混淆，最不推荐。

窗口时间戳不要凭空编：直接从既有 13-window artifact 取
（`state/research_runs/20260529T154450Z-walk-forward-...-gpt55-...` 的 `walk_forward.json` 里逐窗 `start_utc/end_utc`）。

**命令骨架**（WSL，`source .env` 后；下例假设已加 CLI 覆盖参数）：

```bash
# 基线（h6，profile 默认 trailing）
python -m qount.main walk-forward --research-profile eth-only \
  --window wf-mar06=<start>,<end> [...从 artifact 取齐全部 13 窗] \
  --artifact-dir /tmp/qount-wf-h6-baseline

# 对照（h12，退出参数同步放宽）—— 用新增 CLI 覆盖，不要靠 QOUNT_TRAILING_* env
python -m qount.main walk-forward --research-profile eth-only --horizon-bars 12 \
  --trailing-arm-pct 0.0030 --trailing-retrace-pct 0.0050 \
  --window wf-mar06=<start>,<end> [...全部 13 窗] \
  --artifact-dir /tmp/qount-wf-h12-probe
# min_hold 可继续用 env：QOUNT_MIN_HOLD_BARS=4（profile 不覆盖它）
```

> 计算成本提示：walk-forward 每个窗口都会**重训 setup model** 并对每个被选中的 candidate
> 发一次 AI 请求。13 窗 × 多组 horizon/trailing 组合会累计上百次 `gpt-5.5` 调用，
> 先用 `--max-bars` 或少数代表窗口（如 `wf-mar06`、`wf-apr15` 这两个有成交的窗）做粗筛，
> 再跑全 13 窗确认。

**成功判据**（对比同 13 窗）：

- `sum_realized_return_pct` 提升，且 `positive_realized_windows` 不减少。
- `total_review_missed_candidate_move` 不增加。
- 没有引入新的负 `review_avg_net_edge_pct` 窗口。

**失败即停**：如果 h12 不优于 h6，说明退出不是瓶颈，记录结论，转 WS-2/WS-4。

**护栏**：horizon / 退出参数变更属于研究 profile / CLI 级别，**不要**写进 `.env`
的 4-symbol live 形状；只在研究命令里设置。

**2026-05-30 执行状态**：已先跑 `wf-mar06` 单窗粗筛，不扩到完整 13 窗。
h12 + loose trailing artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260530T100317Z-walk-forward-qount-ws1-h12-trailing-mar06-20260530T095148Z
```

对照既有 h6 基线 `wf-mar06`：

```text
h6 baseline realized=+1.5617328164%, unrealized=0.0%, open_positions=0
h12 probe   realized=+0.5828756239%, unrealized=+1.0361625344%, open_positions=1
```

读法：h12 + `arm=0.003/retrace=0.005/min_hold=4` 把收益更多留在未平仓浮盈里，
不满足 G6，也没有改善 realized return。WS-1 不支持按这个参数扩大到完整 13 窗。
若以后继续 WS-1，只能换一个“能收尾干净”的退出假设，而不是复跑当前 loose trailing。

---

### WS-2：成本结构与最小边际（先做，可与 WS-1 并行）

**背景（已核对 `trade_policy.py:48-52`）**：per-leg 成本
`= fee 0.0004 + slippage 0.0002 = 0.0006`。**开仓（buy/sell on contract）按 ×2 = `0.0012`
计费，且这 `0.0012` 已经被减进 `target_edge_pct` / `avg_target_edge_pct` 里**——
所以 discovery 报出的 `+0.0030` 这类切片**已经是手续费后正期望**，不是“还没扣成本”。
真正的现象是：broad setup 的 post-cost edge 就**贴着 0 线**（`±0.0010` 量级），
没有安全边际，噪声一抖就翻负。`min_expected_edge_pct` 默认 0.0025，是 risk 层阈值
（`risk_engine.py:2460`），profile **不覆盖它**，env 可控。

**假设**：(a) 把 risk 层 `min_expected_edge_pct` 提高，作为 post-cost edge 之上的
**安全边际**，砍掉贴 0 线的薄边际成交；(b) maker / 限价进场会降低 per-leg
（`fee` 那一项），等价于把已嵌入的 `0.0012` 开仓成本压低，让一批贴 0 线切片整体上移。

**两个独立子实验**：

1. **最小边际敏感性扫描**：在固定 13 窗上，扫
   `QOUNT_MIN_EXPECTED_EDGE_PCT ∈ {0.0025, 0.0035, 0.0045}`（profile 不覆盖该字段，env 生效），看
   `sum_realized_return_pct` 与 `total_paper_filled` 的权衡。期望：成交变少但
   `avg_realized_return_pct` 与 `review_avg_net_edge_pct` 上升。
2. **成本敏感性 / maker 假设（纯离线）**：用 `setup-edge-study` 在不同 fee 假设下复核
   目标切片的 `avg_target_edge_pct`，量化“如果 per-leg 从 taker 0.0006 降到 maker 档，
   哪些贴 0 线切片整体上移到有安全边际”。只改成本假设做离线量化，不改执行器下单方式。

```bash
python -m qount.main setup-edge-study --research-profile eth-only \
  --target-slice-set eth-range-action --horizon-bars 6 12 24 \
  --lookback-days 120
# 复核 maker 假设：调低 QOUNT_ESTIMATED_FEE_PCT 重跑同一 study，对比 avg_target_edge_pct
```

**成功判据**：找到一个 `min_expected_edge_pct`，在 13 窗上 `sum_realized_return_pct`
不降而 `review_avg_net_edge_pct` 上升；或证明某目标切片在 maker 费下从负翻正。

**护栏**：这是收紧（提高边际门槛），不是放宽，符合“不为增频放宽 broad gate”。
maker 进场如果要落到执行器，是单独的工程改动，必须另开一轮、先单测。

**2026-05-30 执行状态**：先做了 h6 `eth-range-action` 当前成本 vs maker-fee
离线对照；不改执行器。

```text
current=/home/alyaloale/Code/qount/state/research_runs/20260530T100928Z-setup-edge-study-qount-ws2-eth-range-action-h6-current-20260530T100855Z/qount-ws2-eth-range-action-h6-current-20260530T100855Z.json
maker=/home/alyaloale/Code/qount/state/research_runs/20260530T101000Z-setup-edge-study-qount-ws2-eth-range-action-h6-makerfee-20260530T100855Z/qount-ws2-eth-range-action-h6-makerfee-20260530T100855Z.json
```

结果：

```text
broad sell_range_noise_pullback_or_range:
  current avg=-0.0010096
  maker-fee avg=-0.0006096
pullback_sma_slow_gt008:
  current avg=+0.0011208
  maker-fee avg=+0.0015208
range_return24_gt012:
  current avg=+0.0014270
  maker-fee avg=+0.0018270
```

读法：maker 假设能把 post-cost edge 整体上移约 `+0.0004`，但 broad gate 仍为负；
当前不支持为了 maker 费率改执行器。强子切片仍必须先过 WS-3 readiness 和 WS-4
shadow proof。

**2026-05-30 追加：min-edge 敏感性离线判读**

先尝试按计划跑完整 13-window `QOUNT_MIN_EXPECTED_EDGE_PCT` 扫描，但 WSL 实测
几分钟只完成 `wf-feb27` 一个 0 交易窗口；随后改跑 `wf-mar06 + wf-apr15`
两条有成交窗口，仍在第一档耗时过高。两个长跑均已中止，partial artifact 不作为策略证据。

改用既有 13-window baseline 的 `risk_actions.risk_debug.expected_edge_components`
读取真实开仓边际：

```text
baseline=/home/alyaloale/Code/qount/state/research_runs/20260529T154450Z-walk-forward-qount-wf-eth-through-may29-afterpm-gpt55-20260529T1524Z

wf-mar06 run 76  final_expected_edge_pct=0.0027489
wf-mar06 run 104 final_expected_edge_pct=0.0039349
wf-mar06 run 130 final_expected_edge_pct=0.0032814
wf-apr15 run 76  final_expected_edge_pct=0.0019836
```

阈值读法：

```text
threshold=0.0015 kept=4/4
threshold=0.0025 kept=3/4   # 砍掉 wf-apr15 唯一正收益
threshold=0.0035 kept=1/4   # 只剩 wf-mar06 run 104
threshold=0.0045 kept=0/4   # 全部 0 交易
```

结论：当前所有 realized profit 都来自这些低到中等 expected-edge 的开仓。
收紧 `min_expected_edge_pct` 不会解决盈利稳定性，反而会减少已知正收益窗口，
让 G2/G7 更差；不支持把 `QOUNT_MIN_EXPECTED_EDGE_PCT` 提到 `0.0025+`
作为当前盈利改进。完整 13-window 多档重跑只有在新的候选线索通过 step 3 后才值得再做。

---

### WS-3：覆盖方法学修正（解锁 readiness，不改交易行为）

**先分清两个不同的“覆盖”问题（review 修正）**：

- **离线切片 edge 覆盖**：这个**已经被 `setup-edge-study` 在 90–120 天上大样本证明了**
  （强子切片 n=44–180，全程无 AI、无 backtest）。不需要再跑长 backtest 去“证明 edge 存在”。
- **决策流覆盖**：`shadow_candidate_readiness` 读的是 backtest **snapshot 序列**，
  而每个 OOS 窗只有 3–12h，rare slice 攒不到
  `min_samples_per_horizon>=8 × positive_windows>=2`。WS-3 要解的是**这一个**：
  目标 tag 在真实决策流里到底出不出现、出现得够不够频繁到值得为它写 gate。

**改法（纯研究可观测性，零交易影响）**：

1. **集合根扫描（先做，零额外成本）**：用
   `research-slice-scan --artifact-dir state/research_runs` 聚合**所有已存在**的
   持久化窗口，累计 snapshot 覆盖（`current.md` 已验证该能力）。这不需要新跑回测。
2. **必要时跑更长连续回测补覆盖**：若集合根仍不够，再跑一段连续 ETH backtest。
   ⚠️ **成本警告**：backtest 逐 bar 跑 `_process_cycle`，AI 只在 candidate 被选中时触发
   （历史上约 5% cycles），但 90–180 天仍意味着上千次 `gpt-5.5` 调用。**先用较短区间
   或 `--max-bars` 估算单位成本，再决定是否拉长**；不要无界跑。

```bash
# 1) 先零成本聚合已有窗口
python -m qount.main research-slice-scan \
  --artifact-dir state/research_runs --horizon-bars 3 6 12 24

# 2) 仅在覆盖仍不足时，受控地拉长（先小区间估成本）
python -m qount.main backtest --research-profile eth-only \
  --start 2026-05-01T00:00:00+00:00 --end 2026-05-08T00:00:00+00:00 \
  --review-horizon-bars 12 --artifact-dir /tmp/qount-eth-long-probe
python -m qount.main research-slice-scan \
  --artifact-dir /tmp/qount-eth-long-probe --horizon-bars 3 6 12 24
```

**成功判据**：某个强子 tag 第一次出现 `shadow_candidate_readiness.status=ready_for_targeted_shadow_proof`。
**只有出现 ready，WS-4 才有资格对那个 tag 写候选层表达。**

**关键诚实点**：如果连集合根 + 受控长样本下这些 tag 仍是 0 决策流覆盖，说明候选生成层
根本表达不出这些市场状态——那 WS-4 的第一步就不是写 gate，而是先让 `assess_fresh_entry` /
`build_research_slice_tags` 能识别该状态（见 WS-4 步骤 0）。

**2026-05-30 执行状态**：已按 ETH-only profile 对 `state/research_runs` 做集合根扫描：

```text
/home/alyaloale/Code/qount/state/research_runs/20260530T093824Z-research-slice-scan-qount-ws3-existing-root-scan-ethonly-20260530T093824Z/qount-ws3-existing-root-scan-ethonly-20260530T093824Z.json
```

结果：

```text
source_mode=backtest_collection
backtest_count=33
cost_model=contract true, fee 0.0004, slippage 0.0002
shadow_candidate_readiness.status=no_ready_tags
ready_tags=[]
```

关键覆盖：

```text
eth_range_action_pullback_sma_slow_gt008=0
eth_range_action_range_return24_gt012=6
eth_reclaim_long_failed_breakdown_base=15
eth_reclaim_long_failed_breakdown_sma_slow_gt004=6
```

读法：现有 artifact 集合仍不够进入 WS-4 gate。下一步不是写候选层，而是二选一：
继续扩受控样本，或先补研究 tag/候选表达，让 `pullback_sma_fast_gt008` 这条 multi 线索能
在决策流里被单独统计。

---

### WS-4：多币 / reclaim-long alpha 转化（后做，唯一动候选层）

这是真正扩大 alpha 密度的主线，也是风险最高的一条，**必须** 等 WS-3 给出某 tag 的
ready 信号后才启动，且严格按 `current.md` 既定纪律推进。

候选 thesis 优先级（按离线证据强度）：

1. `sell + range_noise + pullback + sma_fast_ratio>0.008`（h6/h12 最强）。
2. `range + return_24bars>0.012`。
3. `ETH long_pullback_reclaim + failed_breakdown + sma_slow>0.004`（弱，n 小，最后做）。

**分步（任何一步不过即停）**：

- **步骤 0 — 表达**：确认 `build_research_slice_tags`（`entry_quality.py:190-287`）
  能给目标状态打 tag；若 `assess_fresh_entry` 把它归进 `range_noise` 默认桶而无法
  细分，先只在研究 tag 层把它表达出来（不改 eligibility）。
- **步骤 1 — 冻结假设（防 p-hacking，见第 4.1 节）**：在看任何 validation 窗口结果
  **之前**，把 tag 的精确定义和阈值写死（写进单测），并记录“这是从多少个 slice 里挑出来的”。
- **步骤 2 — 覆盖 + readiness**：WS-3 证明该 tag 在决策流里有 ≥ readiness 门槛覆盖，
  且 `shadow_candidate_readiness.status=ready_for_targeted_shadow_proof`。
- **步骤 3 — shadow proof（需先确认 / 搭建隔离执行入口）**：
  ⚠️ 现有 `research_slice_tags` / `shadow_candidate_readiness` 只是**只读观测**，
  代码里**没有**“生成候选但不交易、却能测它若被执行的 realized return”的现成机制。
  所以步骤 3 的可操作定义是：**写一个最窄的、仅对该 tag 生效的隔离 eligibility 表达，
  在一个独立 backtest/walk-forward artifact 里跑，专门统计该 tag 触发的 fresh-entry 的
  realized return**——而不是直接进主交易链路。若要真正的影子（不下单）执行，需要先建该 harness。
- **步骤 4 — 窄 gate**：只有步骤 3 在完整链路里转化为正 realized return，
  才在 `candidate_filter` 把它落成**最窄**的 eligibility 表达（不是放宽 broad
  `range_noise`，而是精确暴露 `range_noise ∧ pullback ∧ sma_fast>0.008` 这个交集），
  先写单测，再跑完整 13 窗。

**成功判据 = promotion gate（见第 4 节），且必须额外过第 4.1 节的 out-of-sample 验证。**

**护栏（直接引用 current.md 的硬约束）**：

- 不恢复 broad `short_continuation_confirmed`。
- 不宽泛放开 `short_rebound_fail_confirmed / pullback / range_noise` fresh entry。
- 一轮只改一处（entry / management / setup model / prompt 不同时改）。
- `terminal_volume_gt3` 已被 May28-latest OOS 否定，**不再做 gate 候选**。

**2026-05-30 执行状态（step 0）**：已补只读 research tag 表达：

```text
multi_range_action_pullback_sma_fast_gt008
multi_range_action_range_return24_gt012
eth_range_action_pullback_sma_fast_gt008
```

现有 artifact 集合根复扫：

```text
/home/alyaloale/Code/qount/state/research_runs/20260530T112331Z-research-slice-scan-qount-ws4-step0-fast-sma-scan-20260530T112329Z/qount-ws4-step0-fast-sma-scan-20260530T112329Z.json
multi_range_action_pullback_sma_fast_gt008=0
eth_range_action_pullback_sma_fast_gt008=0
ready_tags=[]
```

随后用离线样本定位出 90 天内 37 个 `sell + pullback + sma_fast>0.008` 样本，
并跑了一个 2 小时 multi-symbol 决策流探针：

```text
backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T113548Z-backtest-qount-ws4-step0-multi-fast-sma-backtest-20260530T113007Z
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T113548Z-research-slice-scan-qount-ws4-step0-multi-fast-sma-backtest-scan-20260530T113007Z/qount-ws4-step0-multi-fast-sma-backtest-scan-20260530T113007Z.json
window=2026-03-03T15:30:00+00:00..2026-03-03T17:30:00+00:00
runs_completed=41
paper_filled=0
multi_range_action_pullback_sma_fast_gt008=21
h6 avg_target_edge_pct=+0.0039374
h12 avg_target_edge_pct=+0.0087454
ready_tags=[]
```

读法：step 0 表达已经完成，这条线索能进入 snapshot 统计；但没有成交、没有 readiness，
所以还不能进入步骤 3/4。下一步只能继续补一个独立窗口的只读覆盖，或先实现真正的隔离
shadow execution harness。

**2026-05-30 追加独立窗口**：已补 `2026-04-20T07:00..08:00Z` multi-symbol
只读覆盖探针：

```text
backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T132420Z-backtest-qount-ws4-step0-multi-fast-sma-apr20-20260530T132009Z
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T132420Z-research-slice-scan-qount-ws4-step0-multi-fast-sma-apr20-scan-20260530T132009Z/qount-ws4-step0-multi-fast-sma-apr20-scan-20260530T132009Z.json
multi_range_action_pullback_sma_fast_gt008=8
h3/h6/h12 avg=+0.0035351/+0.0071846/+0.0093046
paper_filled=0
```

合并 `2026-03-03` 与 `2026-04-20` 两个独立窗口后，仅按 h3/h6/h12 评估：

```text
combined_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T132422Z-research-slice-scan-qount-ws4-step0-fast-sma-combined-h3h6h12-20260530T132009Z/qount-ws4-step0-fast-sma-combined-h3h6h12-20260530T132009Z.json
ready_tags=["multi_range_action_pullback_sma_fast_gt008"]
sample_count=29
h3 avg=+0.0011956, positive_edge_rate=0.5517, positive_windows=2
h6 avg=+0.0048332, positive_edge_rate=0.7931, positive_windows=2
h12 avg=+0.0088997, positive_edge_rate=0.7931, positive_windows=2
```

读法：step 2 在 h3/h6/h12 口径下已满足 readiness；h24 仍未覆盖，且两个探针都没有
真实成交。可以进入 step 3 的隔离 shadow proof/harness 设计，但不能跳到 step 4 gate。

**2026-05-30 step 3 执行状态**：已实现最窄隔离 harness：

```text
backtest / walk-forward:
  --research-shadow-candidate-tags multi_range_action_pullback_sma_fast_gt008
```

行为边界：

- 只在研究 backtest / walk-forward 中使用；默认空。
- live 模式忽略该字段。
- 匹配 tag 的 fresh-entry 会进入 AI/risk；不匹配的 fresh-entry 被隔离排除。
- 不改 production candidate gate，不开 paper / live。

两个独立窗口 shadow proof：

```text
mar03_backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T134311Z-backtest-qount-ws4-step3-shadow-fast-sma-mar03-20260530T133841Z
mar03_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T143151Z-research-slice-scan-qount-ws4-step3-shadow-fast-sma-mar03-scan-20260530T143150Z/qount-ws4-step3-shadow-fast-sma-mar03-scan-20260530T143150Z.json
runs_completed=38
target_snapshot_count=60
target_ai_decision_count=20
target_risk_final_count=20
AI actions: hold=20
paper_filled=0
realized_return_pct=0.0
h3/h6/h12 avg_target_edge_pct=-0.0013262/-0.0010768/+0.0024751

apr20_backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T143701Z-backtest-qount-ws4-step3-shadow-fast-sma-apr20-20260530T143555Z
apr20_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T143740Z-research-slice-scan-qount-ws4-step3-shadow-fast-sma-apr20-scan-20260530T143739Z/qount-ws4-step3-shadow-fast-sma-apr20-scan-20260530T143739Z.json
runs_completed=15
target_snapshot_count=8
target_ai_decision_count=4
target_risk_final_count=4
AI actions: hold=4
paper_filled=0
realized_return_pct=0.0
h3/h6 avg_target_edge_pct=+0.0044437/+0.0084449
h12 sample_count=0
```

读法：这条 tag 已通过“观测层 readiness”，但在隔离候选进入完整 AI/risk 链路后
没有任何 realized-return 转化；失败点是 AI 全部 hold，不是 risk 拦截。
因此 `multi_range_action_pullback_sma_fast_gt008` **不能进入 step 4 gate**。
若以后继续这条大方向，必须冻结新的、不同的验证假设，并使用未参与 discovery /
本次 validation 的样本外窗口；不能在这两个窗口上事后调 prompt 或阈值。

**2026-05-30 继续执行：剩余 WS-4 候选 step 2 复扫**

第二优先级 `range + return_24bars>0.012`：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T152130Z-research-slice-scan-qount-ws4-step2-range-return24-collection-20260530T152130Z/qount-ws4-step2-range-return24-collection-20260530T152130Z.json
source_mode=backtest_collection
backtest_count=38
tag=multi_range_action_range_return24_gt012
snapshot_count=6
ai_decision_count=6
risk_final_count=6
ready_tags=[]
h3 avg_target_edge_pct=-0.0005002 positive_edge_rate=0.3333
h6 avg_target_edge_pct=+0.0000067 positive_edge_rate=0.6667
h12 avg_target_edge_pct=-0.0035458 positive_edge_rate=0.0
```

读法：样本不足，且 h3/h12 为负，不进入 step 3 shadow proof。

第三优先级 `ETH long_pullback_reclaim + failed_breakdown + sma_slow>0.004`：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T152226Z-research-slice-scan-qount-ws4-step2-eth-reclaim-long-collection-20260530T152225Z/qount-ws4-step2-eth-reclaim-long-collection-20260530T152225Z.json
source_mode=backtest_collection
backtest_count=38
eth_reclaim_long_failed_breakdown_base snapshot_count=15
eth_reclaim_long_failed_breakdown_sma_slow_gt004 snapshot_count=6
ready_tags=[]
base h3/h6/h12/h24 avg=-0.0007453/-0.0009093/-0.0044665/-0.0131250
sma_slow_gt004 h3/h6/h12/h24 avg=-0.0021505/-0.0032977/-0.0040575/-0.0118253
```

读法：覆盖和 edge 都不够，不能进入 step 3 shadow proof。

当前 WS-4 三条候选队列状态：

```text
1. multi_range_action_pullback_sma_fast_gt008: step 3 失败，AI 全 hold，无成交
2. multi_range_action_range_return24_gt012: step 2 不 ready，h3/h12 为负
3. eth_reclaim_long_failed_breakdown_sma_slow_gt004: step 2 不 ready，所有 horizon 均值为负
```

本轮 WS-4 不能继续写 gate。后续只能选择新的 frozen hypothesis、补真正样本外窗口，
或回到 WS-2 的 min-edge 敏感性扫描；不能在已看过的窗口上事后调参。

**2026-05-30 继续执行：新增 OOS / root scan 复核**

先对已有 `wf-may30-latest` 重新按当前 default target tags 扫描：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T162100Z-research-slice-scan-qount-rescan-may30-latest-current-tags/qount-rescan-may30-latest-current-tags-.json
source=state/research_runs/20260530T055103Z-walk-forward-qount-wf-eth-may30-latest-20260530T0549Z
paper_filled=0
realized_return_pct=0.0
ready_tags=[]
multi_range_action_range_return24_gt012 snapshot_count=6
h3/h6/h12/h24 avg=-0.0005002/+0.0000067/-0.0035458/-0.0026226
eth_reclaim_long_failed_breakdown_base snapshot_count=1
h3/h6/h12/h24 avg=-0.0030092/-0.0041461/-0.0059207/-0.0060344
```

然后补一个真正新样本外单窗：

```text
walk_forward=/home/alyaloale/Code/qount/state/research_runs/20260530T162254Z-walk-forward-qount-wf-eth-may30-postlatest-20260530T1625Z
window=2026-05-30T05:40:00Z..2026-05-30T16:15:00Z
paper_filled=0
realized_return_pct=0.0
open_positions=0
promotion_blockers=["non_positive_realized_return"]

scan=/home/alyaloale/Code/qount/state/research_runs/20260530T162349Z-research-slice-scan-qount-rescan-may30-postlatest-current-tags-20260530T1625Z/qount-rescan-may30-postlatest-current-tags-20260530T1625Z.json
ready_tags=[]
eth_reclaim_long_failed_breakdown_base snapshot_count=2
h3/h6/h12/h24 avg=+0.0003093/+0.0005721/+0.0002104/-0.0008515
```

最后重扫全量已持久化 research root：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T162449Z-research-slice-scan-qount-root-rescan-through-may30-postlatest-20260530T1627Z/qount-root-rescan-through-may30-postlatest-20260530T1627Z.json
source_mode=backtest_collection
backtest_count=39
ready_tags=[]
near_miss[0]=eth_range_action_pullback_sma_slow_gt008
near_miss[1]=eth_range_action_pullback_sma_fast_gt008
near_miss[2]=multi_range_action_pullback_sma_fast_gt008
```

读法：root scan 后仍没有可进入 targeted shadow proof 的 ready tag。`sma_slow_gt008`
/ `sma_fast_gt008` 的 pullback near miss 只在 h3/h6/h12 为正，h12/h24 覆盖不足，
且 AI/risk 覆盖只有 2 条；不能写 gate，也不能在已看过窗口上调阈值补门槛。

---

## 4. Promotion Gate（晋级到 forward paper 的硬门槛）

> 2026-05-31 更新：本节旧 G1/G2 已被 [holdout.md](../../../holdout.md) 的
> `G_paper` / `G_live` 取代。下面保留为历史上下文；当前 promotion 判断只看
> `docs/holdout.md`，并且已看过窗口只能算 `discovery_pool`。

当前 `walk_forward._promotion_blockers` 只逐窗判 `oos_safe / open_position /
realized>0 / review_edge>0`。这对“整体盈利”太弱。本方案把**组合级**门槛固化如下，
任何想推进 forward paper 的工作流都必须同时满足：

> 单位提醒（已核对 `backtest.py:510`）：`realized_return_pct` 是**百分数**
> （如 `+1.56` = 1.56%）；而 `avg_target_edge_pct` / 成本是**分数**（`0.0012` = 0.12%）。
> 下面所有门槛用百分数口径，不要混用。

```text
G1  完整 walk-forward 窗口数 >= 13，覆盖最近至少 2 个不同月份。
G2  在「有成交的窗口」中 positive_realized_windows 占比 >= 0.6，
    且有成交的窗口数 >= 5。
    （不要用 window_count 当分母：约一半窗口是结构性 0 交易窗，realized=0，
     会把比例机械压低，使任何策略都过不了。当前是 2/2 traded 正，但 traded 窗口太少不算数。）
G3  sum_realized_return_pct > 0；且「有成交窗口」的 avg_realized_return_pct
    明显为正（建议 > 0.10%，即一个 round-trip 成本量级之上的安全边际）。
    注意成本已经被减进每笔的 edge/return，这里要的是净正，不是再扣一次成本。
G4  total_review_missed_candidate_move == 0           （没有系统漏掉的 candidate-aligned 大机会）
G5  每个有成交的窗口 review_avg_net_edge_pct > 0
G6  windows_with_open_positions == 0                  （收尾干净，不靠未平仓浮盈撑数）
G7  盈利不集中在单一窗口：去掉贡献最大的那个窗口后，sum_realized_return_pct 仍 > 0
G8  对应改动有新单测，且本地 + WSL unittest 全绿
G9  过第 4.1 节 out-of-sample 验证（在「发现期之外」的样本上仍正）
```

> G7 专门针对当前问题：现在去掉 `wf-mar06` 后总收益就崩了。一个不能通过 G7 的策略
> 不是“盈利策略”，是“一两个窗口运气”。

**只有 G1–G9 全过**，才允许在 `current.md` 把结论从 research-only 改为
“可进入 forward paper 评估”。在那之前一律不开 paper、不开 live。

### 4.1 反过拟合 / 多重比较纪律（新增，最重要）

当前“已知正期望子切片”是从 discovery **搜过几百上千个 slice** 后挑出来的
（`current.md`：`h24 ... positive slices=935`）。**挑出来的正切片天然高估真实 edge**，
stability 折又都落在**同一段 90 天发现样本**内，不构成真正的样本外证据。因此任何
WS-4 候选在晋级前必须额外满足：

- **冻结**：slice 定义与阈值在看 validation 结果前写死（写进单测），不再事后微调。
- **样本外**：用一段**完全没参与 discovery / 调参**的时间区间做最终验证
  （例如 discovery 用到某日期前，验证只用该日期后的窗口）。
- **多重比较折扣**：记录“候选是从 N 个 slice 里选的”，N 越大要求的样本外 edge 与
  样本量越高；单一 n<20 的孤立切片一律不晋级。
- **失败即弃**：样本外不正就丢弃该 thesis，不允许换阈值再试同一段数据。

---

## 5. 更长期 / 更高风险的方向（仅在 WS-1–4 给出正读数后考虑）

这些是 capacity 升级，风险和工程成本更高，**不要**在主线证明盈利前投入：

- **setup model 非线性 / 交互特征**：当前是 16 维线性 ridge
  (`setup_model.py:34-51`, `_fit_linear_regression`)，无法表达
  `sell × range_noise × pullback × sma_fast>0.008` 这种交互——而 alpha 恰恰在交互里。
  可加交互项 / 分桶特征，或换更强回归器，但必须仍输出可解释的
  `predicted_edge_pct / confidence_ratio`，并走同一 shadow-proof 流程。
- **Kronos 离线 overlay**：按 `current.md` 既定口径，只产 artifact，记录
  directional accuracy / post-cost edge / tag-specific lift，绝不接入
  candidate / risk / live。只能作为“给已发现 tag 加一个独立确认信号”的对照。
- **多币 live 宇宙**：在单币（ETH）主线过不了 promotion gate 之前，不碰。

---

## 6. 执行顺序与产出

1. **并行启动 WS-1（horizon）+ WS-2（min-edge/cost）+ WS-3（长样本覆盖）**——
   三者都不改 eligibility，可同时跑，互不污染结论。
2. 读 WS-3 结果：是否有 tag 达到 readiness。
   - 没有 → 回到 WS-4 步骤 0（先做表达），或扩样本继续等覆盖。
   - 有 → 进 WS-4 步骤 3 shadow proof。
3. 每条工作流的结论写回 [current.md](../../../current.md) 与 [update-log.md](../../../update-log.md)，
   promotion 级 artifact 一律落 `state/research_runs/...`（用结果里的
   `persistent_artifact_dir / persistent_artifact_path`）。
4. 任何候选层 / gate / 模型改动：**先单测 → 完整 13 窗 → 对照 Promotion Gate → 写文档**。

## 7. 明确不做（与 current.md 一致）

```text
不开 live / 不 forward paper（在 G1-G8 全过之前）
不把 .env 4-symbol live 形状当研究口径
不为补 0 交易窗硬造 gate
不宽泛放开 broad range_noise / short_rebound_fail / pullback
不把 0/0 窗或 total_return_pct 当晋级证据
不在一轮里同时改 entry/management/setup-model/prompt
不把 Kronos 接进 candidate/risk/live
```
