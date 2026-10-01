# C60 换手归因诊断（描述性，非 trial）

> **状态**：预登记（冻结于运行前）｜**日期**：2026-09-29｜**全局 trial 计数**：150（本诊断不增加）
> `research_only=true / orders_authorized=false / data_role=consumed_historical_discovery_pool`

## 1. 问题

成本研究（Trial 149/150）显示 C60 年换手 31.7x–51.7x，2026 YTD v2 仍有 78 次调仓。本诊断只回答：
换手与成本由哪些机制产生。不评估任何新规则、不比较参数、不产生 promote/reject 结论。

## 2. 数据与规则

- 数据：`state/research_runs/c60_cost_expectancy_v1/7495a6fbc649fd2d/closes.json`（data hash `1fa1b9037212`），不重新下载。
- 规则：冻结 `frozen_daily`（Trial 149）与 `research_monthly`（Trial 150），目标由 `c60_cost_study.target_path` 生成，成本 25 bps，T+0。
- 区间：全样本（与 Trial 149/150 相同，预热后首个收盘 2020-12-05 起）与 2026-01-01 起（与 v2 侧车一致）。

## 3. 归因定义（逐交易日，L1 权重）

设 `w_t` 为收盘前漂移后持仓，`T_{t-1}`、`T_t` 为昨日与今日目标：

- `total = |T_t − w_t|`：实际换手。
- `drift = |T_{t-1} − w_t|`：仅把漂移拉回昨日目标所需换手。
- `change = |T_t − T_{t-1}|`：目标本身的变化，按单一主因归入一类（优先级从上到下）：
  1. `candidate`：候选集合变化；
  2. `gate`：候选不变但通过闸门的集合变化（own SMA20 / BTC SMA50）；
  3. `vol_scalar`：集合不变，仅波动率缩放系数变化。
- `netting = drift + change − total ≥ 0`（两部分相互抵消的量）。

另报：换手 < 1% 的"小额交易"天数与其成本占比。

## 4. 输出与边界

每个模式、每个区间报告：交易天数、各类换手合计与占比、按 25 bps 折算成本、主因天数。
结果只写入 `state/research_runs/c60_turnover_attribution_v1/`（0600）。任何据此提出的新规则
（如不交易带、按月调 vol scalar）必须另行预登记为新 trial，计入全局计数，并在未消耗数据上检验。

## 5. 结果（2026-09-29 运行，未改动 §1–§4）

输出 `state/research_runs/c60_turnover_attribution_v1/7aa7bffdae14ace8.json`；逐日合计换手与 `simulate` 一致（单测与运行时断言）。

| 模式 / 区间 | 年换手 | 年成本(25 bps) | drift | candidate | gate | vol_scalar | <1% 小额交易换手占比 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| frozen_daily 全样本 | 51.7x | 1293 bps | 3.9% | 53.8% | 42.2% | 2.7% | 0.5% |
| frozen_daily 2026 | 41.9x | 1047 bps | 1.6% | 44.5% | 53.3% | 1.6% | 0.6% |
| research_monthly 全样本 | 31.7x | 792 bps | 5.1% | 12.2% | 82.1% | 3.4% | 0.9% |
| research_monthly 2026 | 28.0x | 699 bps | 1.6% | 6.3% | 90.7% | 2.1% | 0.7% |

结论（描述性）：
- 月度候选已把候选切换换手从 54% 压到 12%；剩余换手 82–91% 来自冻结闸门（own SMA20 / BTC SMA50）的进出，
  月度模式全样本约 650 bps/年成本由闸门产生。
- 漂移再平衡、vol scalar 微调和小额交易合计 < 10%，"不交易带 / 最小交易额"类改动几乎没有空间。
- 小额交易天数多（约 40%）但换手占比 < 1%；v2 侧车显示的"调仓次数"主要反映这些天，不代表成本。
- 本诊断未区分 own SMA20 与 BTC SMA50 各自的贡献（§3 未预登记该拆分）。
- 可检验方向只剩闸门迟滞/确认（如 N 日确认、带宽）；须作为新 trial 另行预登记，且历史池已消耗，
  只能作为 forward 候选。
