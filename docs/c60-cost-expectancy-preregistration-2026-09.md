# 预登记：c60_cost_expectancy_v1（Trial 149 / 150）

> **状态**：preregistered（结果未读前冻结）｜**权威**：L3 研究预登记｜**最后更新**：2026-09-29
> **本文回答**：C60 信号在真实成本和执行延迟下是否仍有正期望；冻结合同的“每日重排候选”与研究原版“每月选候选”哪个存活。
> **TL;DR**：两个 trial，零参数搜索；任一 G1–G6 不过即 reject。结果不改写 `DualEnginePaperContract.frozen_v1()`，不产生 paper/live/订单权限。

`research_only=true`、`orders_authorized=false`、`data_role=consumed_historical_discovery_pool`。
Owner 2026-09-29 指令：加密优先，开始执行。

## 1. 动机（已知事实，非本研究结果）

- 前向模拟盘 C60 YTD：Signal NAV `1.0596`，Executable NAV `0.9906`，基础成本 656 USD_EQ（本金 6.56%）。
- 研究原版（`scripts/research/crypto_trend_v1_phase_a3_final.py:get_c60_returns`）**每月末**选 90 日动量 Top2 候选，
  月内只每日跑 SMA20/BTC SMA50 闸门与 vol cap；冻结实现（`src/qount/dual_engine/strategy.py:build_c60_decision`）
  **每日**重排候选。主索引“每日 UTC 收盘后取 Top2”的描述与研究原版不符。这是研究→合同的规格漂移。
- 历史读数 CAGR≈75.9% 来自 0 bps、研究原版月度候选、yfinance 数据，不能代表冻结合同。

## 2. 两个 trial（全局 trial 149、150；family 预算 2）

| Trial | 规则 | 与冻结合同差异 |
| --- | --- | --- |
| 149 `frozen_daily` | 逐位复用冻结 C60 规则：每日 90 日正动量 Top2、own SMA20、BTC SMA50（PAXG 豁免）、20 日协方差 vol cap 60%、拒绝权重留现金 | 无 |
| 150 `research_monthly` | 候选只在每个 UTC 月最后一日收盘重选并持有整月；闸门与 vol cap 每日按冻结规则 | 仅候选重选频率 |

不允许搜索任何参数（动量窗、SMA、vol target、Top-N、阈值、成本假设均冻结）。

## 3. 数据与执行模型

- 数据：Binance Spot 公开 `/api/v3/klines` 1d，冻结合同全部 10 个标的；只用已收盘 bar。
- 窗口：10 标的共同日期起，前 99 个 bar 为 warmup（与 paper 取 100 根一致），截至运行时最后已收盘日。
  因 DOT/SOL/PAXG 上市较晚，窗口约从 2020 年末开始，不含研究原版的 2020 年上半年。
- 决策：第 t 日收盘后形成目标；T+0 在第 t 日收盘价成交（paper 取收盘后首笔成交，近似收盘价）；T+1 压力在 t+1 收盘成交。
- 换手 = Σ|目标权重 − 漂移后持仓权重|；成本 = 换手 × 单边 bps，从当日 NAV 扣除；现金收益 0。
- 基础成本 25 bps/边、压力 50 bps/边（冻结合同 `c60_cost_bps` / `c60_stress_cost_bps`）。

## 4. 冻结判据（每个 trial 独立判定）

| 门 | 条件 | 失败含义 |
| --- | --- | --- |
| G1 base | 25 bps、T+0 净 CAGR > 0 | 基础成本下无正期望 |
| G2 stress | 50 bps、T+1 净 CAGR > 0 | 对成本/延迟不稳健 |
| G3 break-even | T+0 下使 CAGR=0 的单边成本 ≥ 50 bps（基础 2×） | 成本安全垫不足 |
| G4 Sharpe | 25 bps、T+0 年化 Sharpe（日频，√365）≥ 0.5 | 风险调整后太弱 |
| G5 单年依赖 | 去掉净收益最高的自然年后，25 bps T+0 净 CAGR > 0 | 靠单一年份 |
| G6 幸存者 | 从宇宙删去 SOLUSDT 后，25 bps T+0 净 CAGR > 0 | 靠单一神币 |
| G7 DSR（仅信息） | N=150 全局 trial 下 DSR ≥ 0.95 | 不构成 promotion 证据，不参与 reject |

- 任一 G1–G6 失败 → `reject`；全部通过 → `retain_for_forward_evidence`（仍不是 promotion）。
- DSR 的 Sharpe 方差采用单序列估计量方差 `(1 − γ3·SR + (γ4−1)/4·SR²)/(n−1)`；这是约定，不是跨 trial 实测方差。
- 描述性输出（不参与判定）：0 bps 信号收益、逐年净收益、年化换手、成本拖累、平均 gross、BTC 买入持有对照。

## 5. 结果处置

- 149 reject 且 150 retain：说明规格漂移是主要病因；只能作为 owner 考虑“C60 合同 v2”的材料，须新时间证据后才谈 paper 更换。
- 两者均 reject：C60 定性为展示线，停止成本优化研究，不做参数救援。
- 两者均 retain：C60 前向继续观察，成本问题归因于 2026 行情而非结构。
- 本研究不补 trial、不改判据；结果写回本文 §6。

## 6. 结果（2026-09-29 运行，判据未改）

bundle=`state/research_runs/c60_cost_expectancy_v1/7495a6fbc649fd2d`，preregistration hash=`c943b0fa1088...`，
data hash=`1fa1b9037212...`。10 标的共同窗口 `2020-08-28..2026-09-28`（2,223 bar），评估期 `2020-12-06..2026-09-28`。

| 口径 | 149 frozen_daily | 150 research_monthly |
| --- | ---: | ---: |
| 0 bps T+0 CAGR / MDD / Sharpe | +74.9% / -32.0% / 1.75 | +62.0% / -23.6% / 1.70 |
| 25 bps T+0 CAGR / MDD / Sharpe | +53.7% / -43.2% / 1.39 | +49.6% / -27.6% / 1.45 |
| 50 bps T+1 CAGR / MDD / Sharpe | +18.0% / -59.4% / 0.64 | +25.4% / -49.5% / 0.86 |
| 年化换手 / 25 bps 成本拖累 | 51.7x / 12.9% | 31.7x / 7.9% |
| break-even 单边成本 | 108 bps | 151 bps |
| 去掉 2021 后 CAGR | +26.6% | +28.7% |
| 去掉 SOL 后 CAGR（25 bps） | +28.2% | +25.4% |
| DSR（N=150，仅信息） | 0.789 | 0.827 |
| 判定 | retain_for_forward_evidence | retain_for_forward_evidence |

25 bps 逐年净收益：149 为 2021 +290.8%、2022 -29.2%、2023 +125.8%、2024 +87.1%、2025 -5.6%、2026 -6.0%；
150 为 2021 +209.0%、2022 +1.6%、2023 +132.7%、2024 +36.8%、2025 +13.6%、2026 -8.2%。
对照 BTC 买入持有：CAGR +28.8%、MDD -76.6%、Sharpe 0.73。

解读（描述性，不改判定）：
- 两个 trial 都通过“存活门”，但 DSR 均未过 0.95，且全部为已消费 discovery 数据，不构成 promotion 证据。
- 收益集中在 2021/2023/2024 三个趋势年；2025–2026 冻结版净值为负，2025 年 signal +9.3% 被成本拖成 -5.6%。
- 月度候选版换手少 39%、成本拖累低 5 个百分点、25 bps MDD 从 -43% 降到 -28%，T+1 压力下也更好；只有 0 bps CAGR 较低。
- T+1 压力使两者 MDD 扩大 16–22 个百分点：edge 依赖同收盘执行，paper 的“收盘后首笔成交”口径尚可，真实延迟需另证。
- 本回放 2026 读数（149：-6.0% 至 9-28）与前向 paper C60（-0.94% 至 9-22）口径不同（起点、成交价、截止日），未做对账。

处置（按 §5“两者均 retain”）：C60 前向继续观察，不做参数救援。规格漂移（每日 vs 每月候选）已被确认且月度版描述性占优，
是否以 150 规则开 C60 合同 v2 须 owner 单独决策并需新时间证据；本研究不改冻结合同。family 预算 2/2 已用完。
