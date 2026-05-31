# qount 更新记录

更新时间：2026-05-31

这份文档只记录近期关键变更、验证结果和当前读法。当前策略结论以
[current.md](current.md) 为准；复跑命令和跨主机操作细节放在
[quick-handoff.md](quick-handoff.md)。

## 当前总览

- live 仍关闭：`QOUNT_LIVE_ENABLE=false`，不能 forward paper / live。
- WSL 是生产和回测真相：`/home/alyaloale/Code/qount`。
- 当前有效 AI 路由是 `QOUNT_AI_MODEL=gpt-5.5`；`gpt-5.4` 会让回测 AI 请求失败。
- 最新有效 `gpt-5.5` 13-window walk-forward 合计
  `sum_realized_return_pct=+1.6184470183%`，但只有 `2/13` 正收益窗口。
- WS-4 `multi_range_action_pullback_sma_fast_gt008` 已完成隔离 shadow proof；
  两个独立窗口都没有成交，AI 对 24 条匹配候选全部 `hold`，不能加 gate。
- WS-4 另外两条候选也已复扫：`range_return24_gt012` 样本不足且 h3/h12 为负；
  `eth_reclaim_long_failed_breakdown_*` 所有 horizon 均值为负或样本不足。
- WS-2 min-edge 复核显示，已知 4 笔开仓 edge 最高只有 `0.00393`；
  收紧阈值会砍掉正收益窗口或直接 0 交易，不支持作为盈利改进。
- 继续补的 5/30 OOS 和 39-backtest root scan 仍是 `ready_tags=[]`；
  没有可进 gate 的新候选。
- 2026-05-31 已新增 [holdout.md](holdout.md)：已看过窗口固定为 `discovery_pool`，
  `validation_pool_v1` 从 2026-06-01T00:00:00Z 之后开始；promotion gate 改为
  `G_paper` / `G_live`。
- 研究工具新增 `--holdout-role`、`--ai-decision-cache`、
  `setup-edge-walk-forward`、`candidate-walk-forward`、
  `scripts/sync-to-wsl.sh`、`scripts/run-wsl-tests.sh`；不改 entry / risk / live。
- `research-slice-scan` 新增 `offline_future_edge_readiness`，旧
  `shadow_candidate_readiness` 保留为兼容别名。
- 结论：有历史盈利样本，不等于稳定盈利；仍处于 research-only。

## 2026-05-31

### Holdout / promotion 前置修复

新增：

```text
docs/holdout.md
```

当前规则：

- `wf-feb27` 到 `wf-may30-postlatest` 的已看过窗口全部是 `discovery_pool`。
- `validation_pool_v1` 从 2026-06-01T00:00:00Z 后的新数据开始。
- 任何在 `validation_v1` 上调参的窗口都会降级回 `discovery`。
- promotion 不再用旧 G1/G2；改用 `G_paper` / `G_live`。

### 实验工具前置修复

新增/修改：

```text
backtest --holdout-role discovery|validation_v1|unknown --ai-decision-cache
walk-forward --holdout-role discovery|validation_v1|unknown --ai-decision-cache
setup-edge-walk-forward
candidate-walk-forward
research-slice-scan offline_future_edge_readiness
scripts/sync-to-wsl.sh
scripts/run-wsl-tests.sh
```

边界：

- AI cache 只在历史 `backtest` / `walk-forward` 显式开启时使用。
- cache key 包含 snapshot、system prompt、decision prompt、model、temperature。
- `run-once` / live 不使用缓存。
- `setup-edge-walk-forward` 与 `candidate-walk-forward` 都不调用 AI、不执行订单。

验证：

```text
local unittest: 211 OK
sync-to-wsl.sh --install: OK
WSL unittest via run-wsl-tests.sh: 211 OK
```

## 2026-05-30

### 继续 OOS / root scan

```text
may30_latest_rescan=/home/alyaloale/Code/qount/state/research_runs/20260530T162100Z-research-slice-scan-qount-rescan-may30-latest-current-tags/qount-rescan-may30-latest-current-tags-.json
may30_postlatest_wf=/home/alyaloale/Code/qount/state/research_runs/20260530T162254Z-walk-forward-qount-wf-eth-may30-postlatest-20260530T1625Z
may30_postlatest_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T162349Z-research-slice-scan-qount-rescan-may30-postlatest-current-tags-20260530T1625Z/qount-rescan-may30-postlatest-current-tags-20260530T1625Z.json
root_rescan=/home/alyaloale/Code/qount/state/research_runs/20260530T162449Z-research-slice-scan-qount-root-rescan-through-may30-postlatest-20260530T1627Z/qount-root-rescan-through-may30-postlatest-20260530T1627Z.json
```

结果：

```text
wf-may30-postlatest:
  window=2026-05-30T05:40:00Z..2026-05-30T16:15:00Z
  paper_filled=0
  realized_return_pct=0.0
  open_positions=0

may30_postlatest_scan:
  ready_tags=[]
  eth_reclaim_long_failed_breakdown_base snapshot_count=2
  h3/h6/h12/h24 avg=+0.0003093/+0.0005721/+0.0002104/-0.0008515

root_rescan:
  backtest_count=39
  ready_tags=[]
  top near miss=eth_range_action_pullback_sma_slow_gt008
```

读法：补样本后仍没有可写 gate 的候选。`eth_range_action_pullback_sma_slow_gt008`
和 `*_sma_fast_gt008` 是 near miss，但 h12/h24 覆盖不足、AI/risk 覆盖只有 2 条；
只能继续观察，不能进 targeted shadow proof / gate。

### WS-4 step 3 隔离 shadow proof

新增研究专用入口：

```text
backtest / walk-forward:
  --research-shadow-candidate-tags <tag...>
```

边界：

- 只用于隔离 backtest / walk-forward 的 targeted shadow proof。
- 默认不生效；live 模式忽略。
- 匹配 tag 的 fresh-entry 会进入 AI/risk，不匹配的 fresh-entry 被排除。
- 不改变 production candidate gate，不开 paper / live。

已验证：

```text
local unittest: 210 OK
WSL unittest: 210 OK
```

`multi_range_action_pullback_sma_fast_gt008` 两个独立窗口结果：

```text
mar03_backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T134311Z-backtest-qount-ws4-step3-shadow-fast-sma-mar03-20260530T133841Z
mar03_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T143151Z-research-slice-scan-qount-ws4-step3-shadow-fast-sma-mar03-scan-20260530T143150Z/qount-ws4-step3-shadow-fast-sma-mar03-scan-20260530T143150Z.json
target_snapshot_count=60
target_ai_decision_count=20
target_risk_final_count=20
AI actions: hold=20
paper_filled=0
realized_return_pct=0.0

apr20_backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T143701Z-backtest-qount-ws4-step3-shadow-fast-sma-apr20-20260530T143555Z
apr20_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T143740Z-research-slice-scan-qount-ws4-step3-shadow-fast-sma-apr20-scan-20260530T143739Z/qount-ws4-step3-shadow-fast-sma-apr20-scan-20260530T143739Z.json
target_snapshot_count=8
target_ai_decision_count=4
target_risk_final_count=4
AI actions: hold=4
paper_filled=0
realized_return_pct=0.0
```

读法：该 tag 虽然在 h3/h6/h12 离线 readiness 上达标，但进入完整 AI/risk 链路后
没有 realized-return 转化；失败点是 AI 全 hold，不是 risk 拦截。不能进入
candidate gate，也不能在这两个窗口上事后调 prompt / 阈值。

### WS-4 剩余候选 step 2 复扫

`multi_range_action_range_return24_gt012`：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T152130Z-research-slice-scan-qount-ws4-step2-range-return24-collection-20260530T152130Z/qount-ws4-step2-range-return24-collection-20260530T152130Z.json
snapshot_count=6
ai_decision_count=6
risk_final_count=6
ready_tags=[]
h3 avg=-0.0005002
h6 avg=+0.0000067
h12 avg=-0.0035458
```

`eth_reclaim_long_failed_breakdown_*`：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T152226Z-research-slice-scan-qount-ws4-step2-eth-reclaim-long-collection-20260530T152225Z/qount-ws4-step2-eth-reclaim-long-collection-20260530T152225Z.json
eth_reclaim_long_failed_breakdown_base snapshot_count=15
eth_reclaim_long_failed_breakdown_sma_slow_gt004 snapshot_count=6
ready_tags=[]
base h3/h6/h12/h24 avg=-0.0007453/-0.0009093/-0.0044665/-0.0131250
sma_slow_gt004 h3/h6/h12/h24 avg=-0.0021505/-0.0032977/-0.0040575/-0.0118253
```

读法：WS-4 当前三条候选都不能写 gate；继续需要新的 frozen hypothesis、
新的样本外窗口，或回到 WS-2 min-edge 敏感性扫描。

### WS-2 min-edge 敏感性复核

尝试跑完整 13-window 四档扫描：

```text
QOUNT_MIN_EXPECTED_EDGE_PCT=0.0015/0.0025/0.0035/0.0045
```

但 WSL 实测完整扫描几分钟只完成 `wf-feb27` 一个 0 交易窗口；随后改跑
`wf-mar06 + wf-apr15` 两条有成交窗口，也仍在第一档耗时过高。两个 run 已中止，
partial artifact 不作为策略证据。

用既有 13-window baseline 的真实开仓 `risk_debug.expected_edge_components`
做离线判读：

```text
baseline=/home/alyaloale/Code/qount/state/research_runs/20260529T154450Z-walk-forward-qount-wf-eth-through-may29-afterpm-gpt55-20260529T1524Z
wf-mar06 run 76  final_expected_edge_pct=0.0027489
wf-mar06 run 104 final_expected_edge_pct=0.0039349
wf-mar06 run 130 final_expected_edge_pct=0.0032814
wf-apr15 run 76  final_expected_edge_pct=0.0019836
```

阈值影响：

```text
0.0015 keeps 4/4 opens
0.0025 keeps 3/4 opens, blocks wf-apr15
0.0035 keeps 1/4 opens
0.0045 keeps 0/4 opens
```

读法：收紧 min-edge 会砍掉已知正收益开仓，不会修复 0 交易窗口，也会让
G2/G7 更差；当前不支持提高 `QOUNT_MIN_EXPECTED_EDGE_PCT`。

### 模型路由修复

- WSL `.env` 从 `QOUNT_AI_MODEL=gpt-5.4` 修为 `QOUNT_AI_MODEL=gpt-5.5`。
- 原因：当前 relay `/v1/models` 不再列出 `gpt-5.4`，导致 AI 请求 502 / 全 hold。
- 备份：`.env.bak-ai-model-20260530T0520Z`。

### 盈利复核

Artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260529T154450Z-walk-forward-qount-wf-eth-through-may29-afterpm-gpt55-20260529T1524Z
```

结果：

```text
window_count=13
oos_safe_windows=13
positive_realized_windows=2
total_paper_filled=4
total_paper_closed=5
total_review_missed_candidate_move=0
sum_realized_return_pct=+1.6184470183
```

读法：

- `wf-mar06` 和 `wf-apr15` 贡献全部正收益。
- 5/29 新增窗口全部 0 交易。
- 不能把 `2/13` 正窗口解释成可上线盈利能力。

### multi-range-action target-slice

新增只读 target-slice set：

```text
setup-edge-study --target-slice-set multi-range-action
```

涉及文件：

```text
src/qount/setup_model.py
tests/test_strategy_optimization.py
docs/current.md
docs/quick-handoff.md
```

验证：

```text
local unittest: 202 OK
WSL unittest: 202 OK
```

关键结果：

| slice | h6 | h12 | h24 | 读法 |
| --- | ---: | ---: | ---: | --- |
| broad `sell+range_noise+pullback/range` | `-0.0009799` | `-0.0007499` | `-0.0003740` | broad 仍负 |
| `pullback+sma_fast>0.008` | `+0.0030693` | `+0.0054217` | `+0.0028383` | h6/h12 强，h24 有负折 |
| `range+return24>0.012` | `+0.0015924` | `+0.0024851` | `+0.0033432` | h6 稳，长 horizon 不稳 |
| `pullback+rsi>75` | `+0.0000734` | `+0.0005458` | `+0.0019411` | 只支持 h24 观察 |

读法：多币 discovery 发现了更强的离线 alpha 线索，但还没有经过完整
candidate -> AI -> risk -> execution 的 walk-forward realized-return 转化。
下一步只能做 targeted shadow proof，不能直接加 gate。

### WS-1 trailing CLI 覆盖

- `backtest` / `walk-forward` 新增 `--trailing-arm-pct`、
  `--trailing-retrace-pct`。
- 覆盖发生在 `apply_research_profile()` 之后，解决 `eth-only` profile 静默盖掉
  `QOUNT_TRAILING_*` env 的问题。
- `audit_context` 记录最终生效的 trailing 参数，h12 持仓 horizon 对照必须先核对这里。

读法：这是研究入口修正，不改变 candidate eligibility，不开 forward paper / live。

### Profit plan WS-1/2/3 first pass

WS-1 持仓 horizon 粗筛：

```text
probe=/home/alyaloale/Code/qount/state/research_runs/20260530T100317Z-walk-forward-qount-ws1-h12-trailing-mar06-20260530T095148Z
window=wf-mar06
horizon_bars=12
trailing_profit_arm_pct=0.003
trailing_profit_retrace_pct=0.005
QOUNT_MIN_HOLD_BARS=4
realized_return_pct=+0.5828756239
unrealized_return_pct=+1.0361625344
total_return_pct=+1.6190381583
open_positions=1
promotion_blockers=open_position_remaining
```

对照既有 h6 基线：

```text
baseline=/home/alyaloale/Code/qount/state/research_runs/20260529T154450Z-walk-forward-qount-wf-eth-through-may29-afterpm-gpt55-20260529T1524Z
window=wf-mar06
realized_return_pct=+1.5617328164
unrealized_return_pct=0.0
open_positions=0
```

读法：h12 + loose trailing 没有改善 realized return，而且留下未平仓，不能扩大到完整
13 窗。一次 2-window 全量探针曾启动但因运行时间/AI 调用成本超出粗筛预期而中止；
该中止 run 没有完整 `walk_forward.json`，不作为策略证据。

WS-2 成本敏感性：

```text
current_cost=/home/alyaloale/Code/qount/state/research_runs/20260530T100928Z-setup-edge-study-qount-ws2-eth-range-action-h6-current-20260530T100855Z/qount-ws2-eth-range-action-h6-current-20260530T100855Z.json
maker_fee=/home/alyaloale/Code/qount/state/research_runs/20260530T101000Z-setup-edge-study-qount-ws2-eth-range-action-h6-makerfee-20260530T100855Z/qount-ws2-eth-range-action-h6-makerfee-20260530T100855Z.json
```

| slice | current h6 avg | maker-fee h6 avg | 读法 |
| --- | ---: | ---: | --- |
| broad `sell_range_noise_pullback_or_range` | `-0.0010096` | `-0.0006096` | 仍为负 |
| `pullback_sma_slow_gt008` | `+0.0011208` | `+0.0015208` | 子切片更强，但仍只是离线 edge |
| `range_return24_gt012` | `+0.0014270` | `+0.0018270` | 子切片更强，但 min-fold 仍有负 |

读法：maker 费用假设会改善边际，但不足以把 broad gate 变成正期望；不能据此改执行器。

WS-3 集合根扫描：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T093824Z-research-slice-scan-qount-ws3-existing-root-scan-ethonly-20260530T093824Z/qount-ws3-existing-root-scan-ethonly-20260530T093824Z.json
source_mode=backtest_collection
backtest_count=33
cost_model=contract true, fee 0.0004, slippage 0.0002
shadow_candidate_readiness.status=no_ready_tags
ready_tags=[]
```

关键覆盖：

```text
eth_reclaim_long_failed_breakdown_base=15
eth_reclaim_long_failed_breakdown_sma_slow_gt004=6
eth_range_action_pullback_sma_slow_002_004=10
eth_range_action_pullback_sma_slow_gt008=0
eth_range_action_range_return24_gt012=6
eth_trend_impulse_short_breakdown_chase_terminal_volume_gt3=6
```

读法：既有 artifact 集合仍没有任何 tag 达到 targeted shadow proof readiness。
WS-4 不能进入候选层 / gate，只能先继续补表达或受控补样本。

### WS-4 step 0 research-tag 表达

新增只读 research tags：

```text
multi_range_action_pullback_sma_fast_gt008
multi_range_action_range_return24_gt012
eth_range_action_pullback_sma_fast_gt008
```

涉及文件：

```text
src/qount/entry_quality.py
src/qount/research_slice_scan.py
tests/test_strategy_optimization.py
```

这只改变 `candidate_context.research_slice_tags` / `research-slice-scan` 的观测层，
不改变 candidate eligibility、AI、risk、paper 或 live。

先扫既有集合根：

```text
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T112331Z-research-slice-scan-qount-ws4-step0-fast-sma-scan-20260530T112329Z/qount-ws4-step0-fast-sma-scan-20260530T112329Z.json
backtest_count=34
multi_range_action_pullback_sma_fast_gt008=0
eth_range_action_pullback_sma_fast_gt008=0
shadow_candidate_readiness.status=no_ready_tags
```

随后用离线样本定位到 90 天内 `sell + pullback + sma_fast>0.008` 有 37 个样本，
集中在 `2026-03-03`、`2026-03-31`、`2026-04-20` 等窗口。基于这个定位跑了一个
2 小时 multi-symbol 决策流覆盖探针：

```text
backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T113548Z-backtest-qount-ws4-step0-multi-fast-sma-backtest-20260530T113007Z
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T113548Z-research-slice-scan-qount-ws4-step0-multi-fast-sma-backtest-scan-20260530T113007Z/qount-ws4-step0-multi-fast-sma-backtest-scan-20260530T113007Z.json
runs_completed=41
paper_filled=0
paper_closed=0
realized_return_pct=0.0
open_positions=0
multi_range_action_pullback_sma_fast_gt008=21
h6 avg_target_edge_pct=+0.0039374
h12 avg_target_edge_pct=+0.0087454
shadow_candidate_readiness.status=no_ready_tags
```

读法：WS-4 step 0 已证明这条 multi fast-SMA 线索能被观测层表达，并能在真实
snapshot 流里出现；但它还没有成交、没有 targeted shadow proof readiness，不能写 gate。
下一步只能继续补第二个独立窗口的覆盖，或先设计真正的隔离 shadow execution harness。

第二个独立窗口覆盖探针：

```text
backtest=/home/alyaloale/Code/qount/state/research_runs/20260530T132420Z-backtest-qount-ws4-step0-multi-fast-sma-apr20-20260530T132009Z
scan=/home/alyaloale/Code/qount/state/research_runs/20260530T132420Z-research-slice-scan-qount-ws4-step0-multi-fast-sma-apr20-scan-20260530T132009Z/qount-ws4-step0-multi-fast-sma-apr20-scan-20260530T132009Z.json
window=2026-04-20T07:00:00+00:00..2026-04-20T08:00:00+00:00
runs_completed=23
paper_filled=0
paper_closed=0
realized_return_pct=0.0
open_positions=0
multi_range_action_pullback_sma_fast_gt008=8
h3 avg_target_edge_pct=+0.0035351
h6 avg_target_edge_pct=+0.0071846
h12 avg_target_edge_pct=+0.0093046
h24 sample_count=0
```

把 `2026-03-03` 和 `2026-04-20` 两个独立窗口合并后，只按 h3/h6/h12 做
readiness：

```text
combined_scan=/home/alyaloale/Code/qount/state/research_runs/20260530T132422Z-research-slice-scan-qount-ws4-step0-fast-sma-combined-h3h6h12-20260530T132009Z/qount-ws4-step0-fast-sma-combined-h3h6h12-20260530T132009Z.json
backtest_count=36
ready_tags=["multi_range_action_pullback_sma_fast_gt008"]
sample_count=29
h3 avg=+0.0011956 positive_edge_rate=0.5517 positive_windows=2
h6 avg=+0.0048332 positive_edge_rate=0.7931 positive_windows=2
h12 avg=+0.0088997 positive_edge_rate=0.7931 positive_windows=2
```

读法：这已经满足 h3/h6/h12 的 targeted shadow proof readiness，但没有 h24 覆盖，
也没有任何真实成交。下一步可以做 WS-4 step 3：搭建或临时实现隔离 shadow execution
harness，专门统计这个 tag 如果被执行的 realized return；仍不能直接进 candidate gate。

## 2026-05-29

### OOS 和 readiness 扩展

- 追加 `wf-may29-latest`、`wf-may29-next`、`wf-may29-pm`、`wf-may29-afterpm`。
- 这些新增窗口都是 0 交易 / 0 realized return。
- `research-slice-scan` 增加：
  - `shadow_candidate_readiness`
  - `blocked_tags_ranked`
  - collection root 扫描 `state/research_runs`

关键结论：

```text
shadow_candidate_readiness.status=no_ready_tags
ready_tags=[]
```

读法：没有达到 targeted shadow proof 的最低覆盖门槛，不新增 entry gate。

## 2026-05-28

### research artifact 持久化

新增统一研究 artifact 持久化：

```text
src/qount/artifacts.py
```

效果：

- `setup-edge-study` 默认写入 `state/research_runs/...`。
- `research-slice-scan` 默认写入 `state/research_runs/...`。
- 外部目录 `backtest` / `walk-forward` 完成后会镜像到 `state/research_runs/...`。

读法：研究证据不再只依赖 `/tmp`，后续引用优先用 persistent artifact path。

### May28 OOS 和 Kronos

- May28 OOS 继续没有给出可晋级 gate。
- `terminal_volume_gt3` 被 h3/h6/h12/h24 负边际否定。
- Kronos 只保留为离线 overlay 候选，不能接入 candidate / risk / live。

## 2026-05-27

### ETH range-action discovery

- `setup-edge-study` 增加 action-aware discovery 和 `eth-range-action` target-slice。
- `research-slice-scan` 增加 h3/h6/h12/h24 future-edge overlay。
- broad `ETH sell + range_noise + pullback/range` 多次复核仍为负。

读法：不能为了提高交易频率放宽 broad `range_noise`。

### 交易链路修正

接受的窄修正：

- deterministic research profile：`eth-only` 固定 `ai_temperature=0.0`。
- `deterministic_eth_reclaim_support_breakdown_override`：只在 research shape 下把已证明 candidate 的 AI `hold` 改为 `sell`。
- `setup_model_weak_trend_shallow_short_rebound_fail`：挡住 May26 暴露的小亏 shallow trend short。

读法：这些是局部修复，不是新增宽 gate。

## 2026-05-26

### 风控和 blocker 修复

- trailing peak 首次达到 arm 后立即落库，避免 tight retrace 失效。
- `setup_model_neutral_reclaim_short_rebound_fail` 挡住 `wf-mar11 run 97` 旧亏损入口。

验证读法：

- 修复能改善已知亏损样本或管理逻辑。
- 仍没有把整体策略推到可上线盈利状态。

## 当前下一步

1. 不开 live，不 forward paper。
2. 不放宽 broad `range_noise` / `short_rebound_fail`。
3. 旧 13-window 和 5/30 前后 OOS 只算 `discovery_pool`；promotion 级读数必须等
   `validation_pool_v1` once-only 窗口。
4. 优先做 T-B：量化 AI hold-bias，冻结 prompt v2/v3，避免继续在已看过窗口上调参。
5. 并行做 T-C/T-G：setup model v2 交互项、0 交易窗口 setup/candidate/AI 拒绝原因诊断。
6. 只有 `G_paper` 通过后才进入 forward paper；只有 forward paper 后才讨论 `G_live`。
