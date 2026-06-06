# qount 更新记录

更新时间：2026-06-06

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
- 2026-05-31 新增 `ai-hold-baseline`：可从既有 artifact 还原 fresh-entry prompt，
  统计 v1/v2/v3 研究 prompt 的 hold-bias；不改 live / `run-once`。
- 2026-05-31 新增 `idle-window-diagnostic`：可从既有 artifact 汇总 0 交易窗口的
  setup / candidate / AI hold 读数；diagnostic only，不改 live / `run-once`。
- 2026-05-31 新增 `setup-model-compare` 和 setup_model `v2_interactions` plumbing；
  第一版 ETH-only compare 没有形成可交易 lift，不能替换主线模型。
- `research-slice-scan` 新增 `offline_future_edge_readiness`，旧
  `shadow_candidate_readiness` 保留为兼容别名。
- 2026-06-04 第一次 `validation_v1` once-only 端到端验证失败：
  `sum_realized_return_pct=-0.7159862916%`、`positive_realized_windows=0/2`、
  `paper_filled=7`、`total_review_missed_candidate_move=2`。不能 forward paper。
- 2026-06-04 盈利导向新增 `eth_short_range_noise_terminal_washout` hard blocker：
  已失败窗口降级 discovery 后转正为 `+0.9173089048%`。新的
  2026-06-03..2026-06-04 第一次 validation 被 AI relay `auth_unavailable` 污染；
  relay 恢复后同策略 infra rerun 无 AI 错误，但 `sum_realized_return_pct=-1.1912362466%`，
  仍不能 promotion。
- 2026-06-05 已按 `profit-engineering-plan.md §10` 启动盈利工程路线：先做 S0/S1'
  地基和“频段 × 策略族”选择扫描，不再默认把 5m 作为给定频段。
- 2026-06-05 新增 `strategy-selection-scan` 并完成 30 天 discovery 初扫；初扫 top cell
  是 `1d ts_mom`，但 rank-IC 很弱且有效广度约 1.13，不能 promotion。
- 2026-06-05 120 天和月度 sensitivity 否定了把 `1d ts_mom lb12/h1` 直接推进 S2；
  5m / CARRY 只在 zero-cost 下转正，maker-ish 成本后为负。
- 2026-06-05 S-CARRY 后续验证继续否定 promotion：WLD/SOL post-only 在 6/1-6/5
  after-tail 为正需要超过 100% maker fill；entry-only basis regime filter 在 120 天或
  6/1-6/5 上均不过关。
- 2026-06-05 top12 `1d ts_mom` 扩币 sanity 也不过关：120 天 `sum=-2.6698947371`，
  2/3/4 月全负，只有 5 月单月正。
- 2026-06-05 新增 prediction-family lookback/holding grid，低频 top12 扫描找到当前最强
  discovery cell：`4h xs_mom lookback=24 holding=6`，120 天 `sum=+3.5251307739`、
  `rank_ic=+0.0523457125`；但 2026-03 月度 sanity 为负，且 holding=6 仍需
  overlap-aware 组合复核。
- 2026-06-05 新增 `--directional-overlap-mode stride` overlap sanity；同一 fixed cell
  120 天 stride `sum=+0.5087944384`、`rank_ic=+0.0607409120`，但 2/3 月仍负，只能推进
  S1.1/S1.2，不能 paper。
- 2026-06-05 新增 `--directional-evaluation-mode portfolio_replay` 限仓组合 replay；
  同一 fixed cell、`max_open_positions=12` 的 120 天 replay `sum=+0.2974912983`、
  `sharpe=+7.1945433715`，但 2026-03 仍负，仍不能 paper。
- 2026-06-05 新增 `--directional-exit-mode triple_barrier`；同一 fixed cell 的 simple
  TP/SL barrier 120 天四组全负，最不差 `tp=0.030/sl=0.015` 也只有
  `sum=-0.1635040433`，进一步否定 paper。
- 2026-06-05 给 triple-barrier artifact 补 `directional_exit_reason_counts`；最不差
  `tp=0.030/sl=0.015` 的 120 天 stop-loss `873`、take-profit `400`、time `173`，
  解释了为什么 close-to-close/replay 正收益会被 fixed TP/SL 打负。
- 2026-06-05 新增 `--directional-purged-cv-folds` / `--directional-embargo-bars`；
  fixed `4h xs_mom lb24/h6` close/replay 的 4-fold 诊断为 `3/4` folds 正，但
  2026-03-03..2026-04-01 fold 为负，仍不能 paper。
- 2026-06-05 N1 新增波动率缩放 triple-barrier（σ 缩放 TP/SL）；修正了 fixed barrier 的
  非对称止损病，但没有任何 σ 设置能跑赢"无 barrier 持有到期" close-exit 基线 `+0.297`，
  最佳 `tp4/sl4=+0.165`、3 月仍负、~90% 收益来自 5 月，N1 门控未通过，仍不进 S2。
- 2026-06-05 N1 新增 entry 侧 regime dispersion 门；`thr0.034` 总收益不变(`+0.299`)、
  Sharpe `7.19→8.00`、回撤降、并把 2026-03 从负翻正、4 月全 ≥ 0,首个改善月度稳健性的
  子步骤;但属 in-sample 阈值、5 月仍约 82% 收益、无新 OOS，N1 仍未过、仍不进 S2。
- 2026-06-05 按 §5/§9.x 补 Deflated Sharpe Ratio；选出候选的 81-cell 网格 DSR ≈ `0.082`,
  最佳 per-period Sharpe `0.278` < 噪声期望最大值 `0.407`——候选的网格内选择优势大概率是
  多重检验假象。S2 门控加硬:新 OOS 正 + 可接受 DSR/PBO 才进 S2。
- 2026-06-05 再补 PBO/CSCV：pbo 4h=`0.020`/1h=`0.056`/1d=`0.214`(全 < 0.5)。与 DSR 互补——
  弱但排名稳定的横截面动量结构,但量级太弱不足以确认盈利;同频段 config 高相关令 PBO 偏低。
- 结论：有历史盈利样本，不等于稳定盈利；仍处于 research-only。
- 2026-06-06 决策（项目所有者确认）：`4h xs_mom lb24/h6` 候选按 §7 诚实退出。DSR ≈ `0.082`
  太弱(最佳 per-period Sharpe `0.278` < 噪声期望最大 `0.407`)、无可执行 exit 跑赢持有、~82%
  收益集中在 5 月——三条件齐备。不在 2026-06-04..06 的 ~2 薄天(~12 根 4h bar)上消耗
  `validation_v1` once-only 日期。**关闭该候选的 S2 晋级路径**;研究转向 §10 换频段 / 换特征源
  (微结构 / funding / 时序基础模型特征),或按 §7 接受研究价值、停止追盈利。详见
  `profit-engineering-plan.md §11.7`。硬边界不变(live 关闭、不 forward paper、不放宽 broad gate)。
- 2026-06-06 §10 换特征源第一刀 kill-test:**funding 作横截面预测特征 = 证伪**。新增
  `xs_funding` / `xs_funding_rev`(funding as-of join 无前视当信号,复用 IC/DSR/PBO harness)。
  top12 120 天 discovery post-cost:rank-IC 全 ≤ `0.030`(< 价量动量 `0.052` < 要求 `0.06`);
  唯一正 cell `1d xs_funding_rev h6` 的 rank-IC ≈ `0.005` ≈ 0(噪声/overlap);DSR ≈ `0.25`
  (best per-period sharpe `0.094` < 噪声期望最大 `0.156`);PBO ≈ 0.49–0.55;4h/8h 全被成本打负。
  继 CARRY 现金流后,funding 第二种用法也证伪,最便宜新源耗尽,压向 §7 诚实止盈。只跑 discovery。

## 2026-06-06

### 架构级根因:横截面广度天花板 ≈ 1.6,§10.2 破局数字被经验证伪

无新代码 / 无新扫描——直接读 funding artifact 已报的 `effective_breadth`(标准公式
`N/(1+(N-1)·r̄)`),查 §10.2「日频横截面 ~10 币 → BR~300 → 要求 IC 0.06」的前提是否成立。

```text
top12 平均绝对两两相关 r̄ ≈ 0.628（4h 0.620 / 8h 0.635 / 1d 0.628）
有效广度: N=12 → 1.52 ; N=20 → 1.55 ; N=30 → 1.56 ; N=100 → 1.58 ; N=1e6 → 1.59
渐近天花板 1/r̄ ≈ 1.59  → 扩币在数学上救不了（N→∞ 仍 < 1.6）
要求 IC(Grinold IR=IC·√BR, IR=1):
  §10.2 假设 ~10 币  BR≈300  √BR=17.3  IC_req=0.058
  真实   ~1.5 币    BR≈ 46  √BR= 6.8  IC_req=0.148
观测最强横截面 IC: xs_mom 0.052 / xs_funding 0.030 → 离要求 ~3x 缺口
```

结论：加密 majors 同涨同跌,横截面把"12 币"折成 ~1.6 个有效独立资产,§10 押注的广度杠杆
**结构性不存在**;要求 IC 被打回 ~0.15 的"5m 不可达"区间——正是 §10 想逃离的天花板。这是
**架构级 §7 证据**:xs_mom / ts_mom / xs_funding 全部过不了线是同一个根因(广度,不是特征),
换特征源 / 扩币都改变不了。

**2026-06-06 项目级决策(所有者确认):执行 §7 诚实止盈,停止追盈利。** latency-insensitive
可触及路径(横截面/日频时序/CARRY)均穷尽且证伪,广度杠杆结构性不存在 → 满足 §7 全局终止条件。
固化整套反过拟合 harness 作为研究成果,停止在择时盈利上继续投入;重启触发条件应是结构性新输入
(真正低相关 universe / 新资产类别 / 可执行低延迟微结构通道),而非继续在已穷尽空间搜索。
硬约束全不变(live 关闭、不 forward paper、不放宽 broad gate、validation_v1 once-only)。
详见 `profit-engineering-plan.md §11.8`。

### §10 换特征源 kill-test:funding 作预测特征(证伪)

变更：

```text
src/qount/strategy_selection.py（新增 xs_funding / xs_funding_rev 族 + 共享聚合重构）
src/qount/main.py（--families 增 xs_funding/xs_funding_rev、新增 --carry-tilt-signal）
tests/test_strategy_optimization.py（as-of 无前视 / 跳过缺 funding / rank-IC 还原 / basis 字段）
```

按 §10 / §11.7 走"换特征源"的第一刀:把 funding 当**横截面预测特征**(问"funding 在 t
是否横截面预测 t→t+h 的 forward return"),区别于已被 basis-tail 证伪的 CARRY 现金流用法。
实现:`_asof_value` 严格 as-of join(取 fundingTime ≤ bar 的最近一笔,无前视)→
`build_carry_tilt_samples`(signal=funding_rate,`xs_funding_rev` 取负)→
`evaluate_cross_sectional_carry_tilt` 复用与价量族**同一套**横截面 IC / 多空 / 周期收益聚合
(抽出 `_aggregate_directional_cross_sections`),故 DSR/PBO 对 funding 与价信号一视同仁。
carry-tilt cell 独立成自己的 trial set 算 DSR/PBO,不与价量网格混合稀释多重检验惩罚。
research-only,不改 PnL / live;默认 `--families` 不含新族,opt-in。

验证：

```text
local unittest=249 OK（245 旧 + 4 新）
sync-to-wsl.sh --install=OK
WSL unittest=249 OK
```

读数（top12 `BTC/ETH/ZEC/SOL/HYPE/WLD/XRP/BNB/NEAR/DOGE/ADA/SUI`、120 天 discovery、
post-cost、{4h,8h,1d}×{xs_funding,xs_funding_rev}×holding{1,3,6}=18 cell）：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T231910Z-strategy-selection-scan-qount-s1-carry-tilt-funding-top12real-120d-20260606/qount-s1-carry-tilt-funding-top12real-120d-20260606.json
rank_ic: 全 |IC| ≤ 0.030（最强 4h/h3 xs_funding +0.030）
best_cell: 1d xs_funding_rev h6  sum=+1.0530  sharpe=+1.7894  但 rank_ic≈+0.0052≈0
           （相邻 holding 不一致 h1 负 / h3 +0.50 / h6 +1.05 → 1d 119 重叠横截面噪声）
carry_tilt_DSR=0.2495（best per-period sharpe 0.0937 < 噪声期望最大 0.1559）
carry_tilt_PBO: 4h=0.246 / 8h=0.552 / 1d=0.488（8h/1d ≈ 抛硬币）
4h/8h 全部 post-cost 负（高换手 × 微弱 edge → 成本主导）
```

另跑 4 币薄广度交叉验证(`...funding-top12-120d-20260606`，`multi-symbol` profile 实际仅
4 币 SOL/XRP/BTC/ETH):rank-IC 更弱、DSR ≈ `0.068`、PBO 顶 `0.687`,结论一致。

结论：funding-as-feature 的横截面预测内容比价量动量更弱、DSR/PBO 不过关、post-cost 无稳健
正 cell。继 CARRY 现金流(basis-tail 证伪)之后,funding 这一新信息源**两种用法均证伪**;
最便宜的新源耗尽。剩余 §11.7 named 源(微结构无廉价历史盘口、时序基础模型需重 ML 栈/libomp)
都不便宜。强化 §7 诚实止盈分支。硬约束全不变,未碰 `validation_v1` once-only。

### `4h xs_mom lb24/h6` 候选 §7 诚实退出

变更：

```text
docs/current.md
docs/profit-engineering-plan.md（§11.1 / §11.5 / 新增 §11.7）
docs/quick-handoff.md
docs/update-log.md
```

纯决策记录轮,无新研究扫描——遵守"不在已看 2–5 月上加任何旋钮"。把上一轮 N1/DSR/PBO 读数
(DSR ≈ `0.082`、PBO 4h=`0.020`、Sharpe 改善但 in-sample、~82% 收益来自 5 月)汇总成对 §7
诚实退出条件的判定:候选在穷尽当前频段/族的 grid 后,无统计显著的扣费后正 edge。

三条诚实退出依据：

1. **网格内选择优势大概率是多重检验假象**：81-cell DSR ≈ `0.082`,最佳 per-period Sharpe
   `0.278` 低于噪声期望最大值 `0.407`。
2. **没有任何可执行 exit 跑赢"持有到期"基线**：σ 缩放 triple-barrier 四组最佳
   `tp4/sl4=+0.165` < close-exit `+0.297`;fixed TP/SL 全负。
3. **收益高度时间集中**：~82% 来自 2026-05 单月,2/3 月度 sanity 反复为负。

为什么不烧 once-only：新 OOS 只多出 2026-06-04..06 的 ~2 天(~12 根 4h bar),薄到无法把
DSR ≈ `0.082` 的弱信号顶上统计显著;在已基本触发 §7 的情况下,消耗一次性日期是浪费稀缺资源。

状态变更：S1' prediction-family 路径 ⛔ 关闭;S2/S3 ⛔ 未启动;N1 门控 ✅ 判定关闭(DSR 分支先于
新 OOS 触发)。研究 pivot:§10 换频段 / 换特征源,或 §7 止盈。硬约束(live 关闭、不 forward paper、
不放宽 broad gate、不在 `discovery_pool` 调参后当 promotion、外部模型不进 candidate/risk/live)不变。

验证：

```text
本轮无新扫描；上一轮 local unittest=245 OK / WSL unittest=245 OK 仍是当前测试真相。
```

## 2026-06-05

### S1' PBO / CSCV 过拟合概率

变更：

```text
src/qount/strategy_selection.py
tests/test_strategy_optimization.py
```

按 §5 / §9.x 补 Probability of Backtest Overfitting（Bailey & López de Prado 的 CSCV）。
新增 `compute_directional_pbo`（按频段分组：时间轴切 S=10 个 block，对 C(10,5)=252 种
IS/OOS 划分，取 IS-best config 看其 OOS 相对排名 ω → logit；PBO = λ≤0 的比例）；各
directional evaluator 多输出一个**仅内存**的 `period_returns_by_timestamp` 序列供 DSR/PBO 用，
算完即从 cell 剥离、不进 artifact。scan 顶层输出 `directional_pbo`（含 `by_frequency`，
primary 频段对齐到 DSR 的最佳 per-period Sharpe 所在频段）。research-only，不改 PnL / live。
新增单测：一致最优 config 时 PBO=0、无公共序列返回 None。

验证：

```text
local unittest=245 OK
sync-to-wsl.sh --install=OK
WSL unittest=245 OK
```

同一 81-cell 低频网格读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T150603Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-dsr-pbo-120d-20260605/qount-strategy-selection-s1-lowfreq-top12-dsr-pbo-120d-20260605.json
block_count=10 combos=252 configs_per_freq=27
pbo_1h=0.0556 median_logit=1.9042
pbo_4h=0.0198 median_logit=2.8332
pbo_1d=0.2143 median_logit=1.9042   (primary)
```

读法：DSR 与 PBO 互补、不矛盾。DSR 问"绝对 Sharpe 量级通缩后是否显著"→ 否(0.082)；
PBO 问"IS-best 在 OOS 是否仍靠前"→ 大体是(PBO 全 < 0.5、median_logit > 0)。合起来：存在
**弱但排名稳定**的横截面动量结构(非纯随机 → PBO 低)，但量级太弱(DSR≈0.08)，多重检验 +
成本 + 路径执行后不足以确认盈利。诚实保留：同频段 27 个 config 高度相关会让 CSCV 排名稳定性
虚高、PBO 偏低，低 PBO 不等于低过拟合风险。两指标都指向**不进 S2**，等新完整 OOS。

### S1' Deflated Sharpe Ratio 多重检验惩罚

变更：

```text
src/qount/strategy_selection.py
tests/test_strategy_optimization.py
```

按计划 §5 / §9.x（"阶段 1/2 的模型/配置选择必须报告 DSR/PBO"）补 Deflated Sharpe Ratio。
新增 `compute_directional_deflated_sharpe(cells)`（López de Prado 口径，正态简化）+ 每个
directional cell 的 `portfolio_period_count`；scan 顶层输出 `directional_deflated_sharpe`。
research-only diagnostic，不改 PnL / live / `run-once`。新增单测：trial 越多越通缩、<2 trial
返回 None。

验证：

```text
local unittest=243 OK
sync-to-wsl.sh --install=OK
WSL unittest=243 OK
```

在**选出候选的那张 81-cell 低频网格**（`1h/4h/1d × xs_mom/xs_rev/ts_mom × lb3/12/24 ×
h1/3/6`、top12、120 天 discovery）上读 DSR：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T143817Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-dsr-120d-20260605/qount-strategy-selection-s1-lowfreq-top12-dsr-120d-20260605.json
trial_count=81
best_by_per_period_sharpe=1d xs_mom lb24/h6
best_per_period_sharpe=0.27825601
expected_max_per_period_sharpe=0.40655144
trial_per_period_sharpe_variance=0.02741146
best_period_count=119
deflated_sharpe_ratio=0.08171240
assumes_normal_returns=true
```

读法：迄今最重要的反过拟合读数。**观测最佳 per-period Sharpe `0.278` 比 81 次随机试验下
噪声期望最大值 `0.407` 还低，DSR ≈ `0.082`**（通常要求 > 0.95）——候选的网格内选择优势在
统计上与"81 次噪声里挑最大"不可区分，且正态假设对肥尾会高估 DSR，真实只会更低。结论从
"候选还需新 OOS"收紧为"网格内选择优势大概率是多重检验假象"。S2 门控加硬：新 OOS 正 +
可接受 DSR/PBO 才进 S2，否则按 §7 诚实退出。**仍不进 S2**。

### S1' N1 regime dispersion 入场门

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增 research-only 参数（在每个 cross-section 上按各币 signal 的离散度 sample std 做 regime
入场门；低于阈值 = 同涨同跌、无相对强弱 = 跳过该 bar 不下注；纯决策时点，无 look-ahead）：

```text
--directional-regime-min-dispersion-pct
```

默认 0(关闭)，历史 artifact、live / `run-once` / CARRY / ts_mom 全部不变。新增单测：
低离散度 cross-section 被 gate、turnover 与 gated 计数、artifact 新字段。

验证：

```text
local unittest=241 OK
sync-to-wsl.sh --install=OK
WSL unittest=241 OK
```

候选 `4h xs_mom lb24/h6` top12 120 天每根 bar 的 signal dispersion 分布：

```text
p10=0.02513 p25=0.03410 p50=0.04829 p75=0.06812 p90=0.10880 min=0.01326 max=0.16409
```

固定同一候选、close-exit、portfolio_replay、`max_open=12`、120 天 discovery 扫阈值：

```text
thr0.000 sum=+0.297491 sharpe=+7.1945 dd=0.0877 gated=0   traded=721 win=0.4952
thr0.034 sum=+0.298812 sharpe=+7.9989 dd=0.0798 gated=178 traded=543 win=0.5119
thr0.048 sum=+0.272640 sharpe=+8.9771 dd=0.1021 gated=356 traded=365 win=0.4940
thr0.068 sum=+0.195078 sharpe=+11.8154 dd=0.0527 gated=539 traded=182 win=0.4953
```

`thr0.034` 月度（对比无过滤 close-exit replay 基线）：

```text
feb_sum=+0.024688 ic=-0.00846  (baseline +0.0063)
mar_sum=+0.002786 ic=-0.00387  (baseline -0.0094 → 翻正)
apr_sum=+0.063078 ic=+0.10121
may_sum=+0.246376 ic=+0.16039
```

`thr0.068` 月度（过滤过狠，2/3 月又转负）：

```text
feb_sum=-0.016136 ic=-0.14038
mar_sum=-0.030840 ic=-0.11364
apr_sum=+0.036571 ic=+0.24559
may_sum=+0.205484 ic=+0.15315
```

artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260605T142637Z-...-regime-thr034-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/...-regime-{thr000,thr048,thr068}-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/...-regime-{0034,0068}-{feb,mar,apr,may}-20260605/
```

读法：这是 N1 里第一个**在正确轴上**改善候选的子步骤(部分止盈/移动止损本质仍是已被
vol-barrier 证伪的路径 exit,故改做 entry 侧 regime 过滤)。`thr0.034` 总收益不变、Sharpe
`7.19→8.00`、回撤 `0.088→0.080`、换手更少,并把 2026-03 从负翻正、4 月全部 ≥ 0,直接打到
"月度全靠单月"的门控失败点。但两条硬保留:(1) 阈值在同一 120 天窗口的 dispersion 分布上选
(p25),属 in-sample 阈值选择;(2) 5 月仍约 82% 收益,只是不再有负月;且全部已看 discovery。
结论:候选状态明显更好,但 §11.5 N1 门控仍未通过(无新完整 OOS、仍偏单月),**仍不进 S2**;
下一刀是把 `thr0.034` 固定参数留到下一个完整 `validation_v1` 独立窗口 once-only 复核。

### S1' N1 波动率缩放 triple-barrier

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增 research-only 参数（把 triple-barrier 的 TP/SL 从固定百分比改为按决策时点近 N 根
bar 已实现收益 σ 缩放，AFML 标准做法；σ 只用 t 时刻及之前的 close-to-close 收益，防泄漏）：

```text
--directional-barrier-vol-lookback-bars
--directional-take-profit-sigma
--directional-stop-loss-sigma
```

默认关闭(lookback=0)，历史 artifact 口径、live / `run-once` / CARRY 全部不变。新增单测：
`_recent_return_std` 忽略未来 bar(防泄漏)、双币 σ 自适应 barrier 行为、artifact 记录新字段。

验证：

```text
local strategy-selection tests=14 OK
local unittest=240 OK
sync-to-wsl.sh --install=OK
WSL unittest=240 OK
```

固定同一 `4h xs_mom lb24/h6`、top12、portfolio_replay、`max_open=12`、vol lookback `24`、
120 天 discovery（窗口 2026-02-01..2026-06-01），σ 倍率扫描：

```text
close_exit_baseline_sum=+0.2974912983 (无 barrier replay 既有读数)
tp1.5/sl1.5 sum=-0.143287 sharpe=-5.9154 SL=643 TP=635 TIME=168
tp2.0/sl2.0 sum=-0.050339 sharpe=-1.8044 SL=514 TP=544 TIME=388
tp3.0/sl2.0 sum=+0.037766 sharpe=+1.2470 SL=539 TP=339 TIME=568
tp3.0/sl3.0 sum=+0.118739 sharpe=+3.8430 SL=303 TP=360 TIME=783
tp4.0/sl4.0 sum=+0.165134 sharpe=+4.7454 SL=192 TP=222 TIME=1032
```

最佳 `tp4.0/sl4.0` 月度：

```text
feb_sum=+0.034363 ic=-0.02582
mar_sum=-0.039638 ic=-0.02285
apr_sum=+0.032380 ic=+0.09500
may_sum=+0.149386 ic=+0.16039
```

artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260605T141034Z-...-volbarrier-tp2-sl2-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T141103Z-...-volbarrier-tp15-sl15-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T141108Z-...-volbarrier-tp3-sl2-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T141113Z-...-volbarrier-tp3-sl3-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T141118Z-...-volbarrier-tp4-sl4-120d-20260605/
/home/alyaloale/Code/qount/state/research_runs/20260605T1411{56,01,06,11}Z-...-volbarrier-tp4-sl4-{feb,mar,apr,may}-20260605/
```

读法：vol-scaling 修正了 fixed barrier 的非对称止损病（fixed `tp0.030/sl0.015` 是
stop-loss `873` / take-profit `400` 约 `2.18x`；vol `tp2/sl2` 收敛到 `514/544` ≈ 1:1），
PnL 随 barrier 加宽单调改善。但没有任何 σ 设置能跑赢"无 barrier 持有到期"的 close-exit
基线 `+0.2974912983`——barrier 越宽越多 `time` 退出、越逼近 close，最佳 `tp4/sl4` 也只有
`+0.165134`。月度上最佳 barrier 的 3 月仍负、约 90% 收益来自 5 月单月，单月依赖未改善，
且全部是已看过 discovery。结论：§11.5 N1 门控未通过——可执行 path-dependent exit 仍未
跑赢持有、无月度稳健性；**仍不进 S2**。下一刀只能等新的完整独立 OOS 日期，或做更细的持仓
管理（部分止盈/移动止损/regime 过滤），不能 paper。

### 计划文档对账（代码 / 成果 / 计划三方校准）

本条只改文档，不动代码;本地全量测试仍 `237 OK`。把 `profit-engineering-plan.md` 的
前瞻计划与已落地代码、已跑 artifact 对账,发现并修正三处偏差:

```text
1. 计划/落地结构偏差:
   §9/§10 设计的 labeling.py / ic_diagnostic.py / cross-sectional-ic 命令 /
   scripts/strategy_selection_scan.py 均未单独存在;
   实际全部合并进 src/qount/strategy_selection.py(约 1647 行)+ strategy-selection-scan。
   triple-barrier=--directional-exit-mode triple_barrier;
   横截面 IC=cell.rank_ic_mean/effective_breadth;
   purged/embargo=--directional-purged-cv-folds/--directional-embargo-bars;
   CARRY 专线=--carry-model threshold_dual_leg + 全套 --carry-* flag。
   labeling.py / ic_diagnostic.py / meta_label_model.py / portfolio.py 当前不存在。
2. current.md 代码结构漏列 strategy_selection.py(最大研究模块),已补。
3. §10.4 分叉预测未成立:计划赌"CARRY 很可能胜",实际 CARRY 被 basis-tail 证伪,
   存活候选是预测族 4h xs_mom lb24/h6(非日频),且未过可执行 exit。
```

改动落点:

```text
docs/profit-engineering-plan.md  新增 §11「执行进展与计划校准」
                                 (S0–S5 进度表 / 模块映射偏差 / §10.4 分叉对照表 /
                                  带门控的下一步 N1–N4 / 硬约束不变)
docs/current.md                  代码结构补 strategy_selection.py;
                                 当前结论加 S1' 第一遍结论 + 指向 §11 的交叉引用
```

S0–S5 当前进度(校准后):

```text
S0.1 ✅ 已落地    S0.2 ✅ 复用既有    S0.3 ⬜ 未做(可选)
S1'  🔄 第一遍全量跑完,仍在 exit/OOS 复核期,无晋级候选
S2/S3/S4/S5 ⛔ 未启动(S2 硬门控未通过)
```

读法:这是一条 meta/对账记录,不引入新策略行为、不放宽任何硬约束、无新 artifact。
计划文档现在与代码和成果一致;S2 重模型仍按门控不启动,直到 4h xs_mom 在新 OOS 上
带可执行 exit 仍有 post-cost 正 edge。

### S1' low-frequency prediction grid

新增 research-only 参数：

```text
--signal-lookback-grid-bars
--holding-grid-bars
```

读法：只扩展 `strategy-selection-scan` 预测族的离线 grid，默认行为不变，不影响 live /
`run-once`。本地和 WSL 全量测试均为 `236 OK`。

关键结果：

```text
grid_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121551Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605/qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605.json
grid=1h/4h/1d x xs_mom/xs_rev/ts_mom x lookback 3/12/24 x holding 1/3/6
best=4h xs_mom lookback=24 holding=6
sum=+3.5251307739
sharpe=+7.1555415974
rank_ic=+0.0523457125
feb_sum=+0.0054374620
mar_sum=-0.3056398179
apr_sum=+0.9769441561
may_sum=+2.8938136721
jun01_04_sum=+0.2839507666
top_fraction 0.10/0.25/0.50 all positive
```

新增 research-only overlap sanity 参数：

```text
--directional-overlap-mode all|stride
```

默认 `all` 保持旧读数；`stride` 每个 holding window 只取一次 cross-section，先降低
`holding=6` 的重叠 horizon 膨胀。

```text
stride_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T123357Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605.json
stride_120d_sum=+0.5087944384
stride_120d_sharpe=+6.0811826595
stride_120d_rank_ic=+0.0607409120
stride_120d_cross_sections=121
stride_feb_sum=-0.0026969105
stride_mar_sum=-0.0234895413
stride_apr_sum=+0.0796046219
stride_may_sum=+0.5008009667
stride_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T123424Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605.json
stride_jun01_04_sum=+0.0627083513
```

结论：`4h xs_mom` 是当前最像样的 prediction-family discovery candidate；stride sanity
下仍为 120 天正收益，说明不是纯重叠 horizon 幻觉。但 2/3 月 stride 仍为负，`jun01_04`
是已看窗口。下一步不是 paper，而是 S1.1/S1.2：purged-CV、triple-barrier、
overlap-aware portfolio replay。

新增 research-only 限仓组合 replay 参数：

```text
--directional-evaluation-mode portfolio_replay
--directional-max-open-positions
```

默认仍是旧 `cross_section`，不影响历史 artifact / live / `run-once`。固定 `4h xs_mom`
lb24/h6、top12、top_fraction `0.25`、`max_open_positions=12`：

```text
portfolio_replay_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T125713Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605.json
portfolio_replay_120d_sum=+0.2974912983
portfolio_replay_120d_sharpe=+7.1945433715
portfolio_replay_120d_max_dd=0.0876673733
portfolio_replay_120d_trades=1446
portfolio_replay_120d_skipped=2880
portfolio_replay_120d_win_rate=0.4951590595
portfolio_replay_feb_sum=+0.0062629159
portfolio_replay_mar_sum=-0.0094161679
portfolio_replay_apr_sum=+0.0656249961
portfolio_replay_may_sum=+0.2463757288
portfolio_replay_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T125741Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605.json
portfolio_replay_jun01_04_sum=+0.0082009038
```

结论：限仓 replay 下 120 天仍为正，说明当前 candidate 不只是无限重叠下注的 artifact；
但 2026-03 仍为负，2026-02 只是微正，`jun01_04` 是已看窗口。下一步不是 paper，而是
S1.1/S1.2 的 purged-CV / triple-barrier / 新 OOS。

新增 research-only triple-barrier 参数：

```text
--directional-exit-mode close|triple_barrier
--directional-take-profit-pct
--directional-stop-loss-pct
```

默认 `close` 不变，不影响历史 artifact / live / `run-once`。同一 fixed cell、top12、
portfolio replay、max open `12`，120 天简单 barrier：

```text
tp015_sl010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132052Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.015-sl0.010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.015-sl0.010-20260605.json
tp015_sl010_sum=-0.2542260860
tp015_sl010_sharpe=-21.9420203800

tp020_sl010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132057Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.010-20260605.json
tp020_sl010_sum=-0.2307013696
tp020_sl010_sharpe=-16.8127315231

tp020_sl015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132104Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.015-20260605.json
tp020_sl015_sum=-0.2296270771
tp020_sl015_sharpe=-14.6592774682

tp030_sl015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132109Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605.json
tp030_sl015_sum=-0.1635040433
tp030_sl015_sharpe=-8.7264450618
```

最不差的 `tp=0.030/sl=0.015` 月度：

```text
exit_reason_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132953Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605.json
120d_exit_counts=stop_loss 873, take_profit 400, time 173
120d_win_rate=0.3443983402
feb_sum=-0.0356452182
feb_exit_counts=stop_loss 224, take_profit 110, time 8
mar_sum=-0.0631122398
mar_exit_counts=stop_loss 242, take_profit 107, time 29
apr_sum=-0.0812657295
apr_exit_counts=stop_loss 211, take_profit 73, time 82
may_sum=+0.0203985601
may_exit_counts=stop_loss 205, take_profit 116, time 57
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132208Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605.json
jun01_04_sum=+0.0177000000
```

结论：simple fixed TP/SL 把 120 天全部打负，且最不差参数 2/3/4 月全负，只剩 5 月和已看
6 月正。原因是路径执行失败：120 天 stop-loss 触发约为 take-profit 的 `2.18x`，交易成本
再把边际进一步压低。`4h xs_mom` 不能 paper；下一步只能做 purged-CV、exit 设计或新 OOS。

新增 fixed-cell purged/embargo CV 诊断参数：

```text
--directional-purged-cv-folds
--directional-embargo-bars
```

默认关闭，只影响 `strategy-selection-scan` 预测族 artifact，不影响 CARRY / live /
`run-once`。同一 fixed cell、top12、close exit、portfolio replay、max open `12`，
4 folds + 6 bars embargo：

```text
purged_cv_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T133904Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605.json
full_sum=+0.2974912983
full_sharpe=+7.1945433715
rank_ic=+0.0523457125
positive_folds=3/4
mean_fold_sum=+0.0743728246
min_fold_sum=-0.0566596009
fold1_sum=+0.0467298450
fold2_sum=-0.0566596009
fold3_sum=+0.0611460588
fold4_sum=+0.2462749954
```

结论：purged/embargo artifact 已把 fold 稳定性机器化，且 3/4 folds 为正，支持继续研究；
但 `2026-03-03..2026-04-01` fold 为负且 IC 为负，收益仍依赖后段行情。fixed close/replay
purged sanity 已跑完，不能 paper；下一步转向更稳健的 exit 设计、模型层 purged-CV 或新完整
OOS。

### S-CARRY basis-entry filter 和 top12 TS-MOM sanity

新增 research-only CARRY 参数：

```text
--carry-basis-entry-max-abs-pct
```

读法：只阻止 basis 已经偏离过大的新 CARRY 入场，默认关闭，不影响 live / `run-once`。
本地和 WSL 全量测试均为 `233 OK`。

关键结果：

```text
WLD/SOL basis_entry_max_abs=0.0008 discovery120d sum=-0.0066684341 after_tail=-0.0083560026
WLD/SOL basis_entry_max_abs=0.0010 discovery120d sum=-0.0010824000 after_tail=-0.0028620256
WLD/SOL basis_entry_max_abs=0.0015 discovery120d sum=+0.0020099742 after_tail=+0.0002303486
WLD/SOL jun01_04 all thresholds sum=-0.0003841457 after_tail=-0.0010857771
top12 1d ts_mom 120d sum=-2.6698947371 sharpe=-0.7852540386 rank_ic=-0.0517447570
top12 1d ts_mom monthly Feb/Mar/Apr all negative; May positive only
```

结论：entry-only basis filter 不能拯救当前 WLD/SOL S-CARRY；top12 扩币也不能让
`1d ts_mom` 进入 S1.1/S1.2。继续时不要重复这两条 sanity。

### profit-engineering S0.1 research 依赖隔离

变更：

```text
pyproject.toml
scripts/check-research-deps.sh
tests/test_strategy_optimization.py
```

读数：

```text
Mac Python=3.14.4
numpy=2.4.6 ok
sklearn=1.9.0 ok
lightgbm optional=false-to-import: missing libomp.dylib
local unittest=222 OK
```

落地结论：

- `research` optional extra 只默认安装 `numpy` / `scikit-learn`。
- `lightgbm` 单独放进 `research-lightgbm`；当前 Mac wheel 可安装但 import 需要额外
  `libomp.dylib`，所以后续 S2 默认用 sklearn `HistGradientBoosting`。
- 新增单测确认 `import qount.main` 不加载 `numpy` / `sklearn` / `lightgbm`，live /
  `run-once` 路径不因 research 依赖变化而改行为。
- 这一步只是 S0.1 地基，不是策略 promotion，不给 forward paper / live 许可。

### profit-engineering S1' strategy-selection-scan

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
src/qount/setup_model.py
```

新增命令：

```bash
python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families xs_mom xs_rev ts_mom carry \
  --frequencies 5m 1h 4h 1d \
  --lookback-days 30 \
  --signal-lookback-bars 12 \
  --holding-bars 1 \
  --output-path /tmp/qount-strategy-selection-s1-30d-20260605.json
```

WSL artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260605T065952Z-strategy-selection-scan-qount-strategy-selection-s1-30d-20260605/qount-strategy-selection-s1-30d-20260605.json
```

关键读数：

```text
window=2026-05-02T00:00:00Z..2026-06-01T00:00:00Z
best_cell=1d ts_mom
sum_return_pct=+0.3121233665
mean_return_pct=+0.0025171239
sharpe=2.2679849920
rank_ic_mean=+0.0085476003
effective_breadth=1.1323823788
5m_xs_rev_rank_ic_mean=+0.0289588724
5m_xs_rev_sum_return_pct=-20.6197925003
carry_sum_return_pct=-0.1147211
```

读法：

- 这只是 discovery 初扫，不是 promotion。
- 5m `xs_rev` 出现正 rank-IC，但 post-cost 大幅为负，支持“5m 成本主导/不适配本系统”的判断。
- CARRY 在当前朴素成本口径下为负；这不是最终否定，因为双腿持仓和方向翻转成本模型仍需更真实。
- `1d ts_mom` 暂列第一，但 rank-IC 很弱、有效广度约 1.13；下一步要做更长 discovery 和参数敏感性，不能直接进 S2/S3。
- 顺手修复 `discover_edge_slices` 同分排序的非确定性，WSL 全量测试从偶发失败恢复为稳定通过。

验证：

```text
local unittest=225 OK
WSL unittest=225 OK
WSL live_guard ok=false reason=live_disabled
qount-runner.timer/service inactive
```

### S1' 120 天 / 月度 / 成本敏感性

120 天全频段全族：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T070504Z-strategy-selection-scan-qount-strategy-selection-s1-120d-full-lb12-h1-20260605/qount-strategy-selection-s1-120d-full-lb12-h1-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
best_cell=1d ts_mom
sum_return_pct=-0.3885499348
mean_return_pct=-0.0008027891
sharpe=-0.4637426827
rank_ic_mean=-0.0524746039
effective_breadth=1.0810517903
```

1d 参数敏感性：

```text
lb3/h1 best=xs_rev sum=-0.0652799064 sharpe=-0.6990452037
lb12/h3 best=ts_mom sum=+0.5824374867 sharpe=+0.4579358431
lb24/h1 best=ts_mom sum=-0.0867584111 sharpe=-0.1035899869
```

月度 `1d ts_mom lb12/h1`：

```text
Feb sum=+0.1023244575 sharpe=+0.3227715436
Mar sum=-0.4297008569 sharpe=-2.2922293236
Apr sum=-0.4340789583 sharpe=-2.8870027003
May sum=+0.3233152390 sharpe=+2.3098638880
```

成本压力：

```text
zero_cost_5m_xs_rev_sum=+1.2386542488
zero_cost_carry_sum=+0.0824606
maker_ish_cost_per_directional_bet=0.0004
maker_ish_5m_xs_rev_sum=-26.4101457512
maker_ish_carry_sum=-0.0999394
```

读法：

- 30 天 `1d ts_mom` 正收益主要来自 2026-05，120 天和 3/4 月不支持稳定性。
- 5m `xs_rev` 和 CARRY 有 gross edge，但太薄，maker-ish 成本后转负。
- 当前不能进 S2/S3；下一步是更真实的 CARRY 双腿/阈值模型和扩 universe。

### S1' OHLCV 列回归测试后复跑

变更：

```text
tests/test_strategy_optimization.py
```

新增回归测试锁定 `strategy-selection-scan` 的 OHLCV fetch 输出必须保持 ccxt 标准列：
`[timestamp, open, high, low, close, volume]`。扫描评估层统一把 `row[4]` 当 close，
所以这个测试用于防止 close/low 列错位污染 S1' 读数。

验证：

```text
local unittest=226 OK
WSL unittest=226 OK
```

WSL 复跑 120 天全频段全族：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T071948Z-strategy-selection-scan-qount-strategy-selection-s1-120d-full-lb12-h1-ohlcv-rerun-20260605/qount-strategy-selection-s1-120d-full-lb12-h1-ohlcv-rerun-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
best_cell=1d ts_mom
sum_return_pct=-0.3885499348
mean_return_pct=-0.0008027891
sharpe=-0.4637426827
rank_ic_mean=-0.0524746039
effective_breadth=1.0810517903
decision=no_positive_cell
```

WSL 复跑成本压力：

```text
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T072101Z-strategy-selection-scan-qount-strategy-selection-s1-120d-5m-xsrev-carry-zero-cost-ohlcv-rerun-20260605/qount-strategy-selection-s1-120d-5m-xsrev-carry-zero-cost-ohlcv-rerun-20260605.json
zero_cost_5m_xs_rev_sum=+1.2386542488
zero_cost_carry_sum=+0.0824606

maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T072410Z-strategy-selection-scan-qount-strategy-selection-s1-120d-5m-xsrev-carry-maker-ish-ohlcv-rerun-20260605/qount-strategy-selection-s1-120d-5m-xsrev-carry-maker-ish-ohlcv-rerun-20260605.json
maker_ish_cost_per_directional_bet=0.0004
maker_ish_5m_xs_rev_sum=-26.4101457512
maker_ish_carry_sum=-0.0999394
```

读法：复跑没有改变 S1' 结论。当前没有可 promotion 的 prediction cell；CARRY 有结构性
gross cashflow，但当前朴素“方向翻转即付成本”模型在 maker-ish 成本下为负。下一步仍是
按 `profit-engineering-plan.md §10.5` 做真实 CARRY 双腿/阈值/最短持仓模型，而不是进入
5m GBDT 或 S2/S3。

### S-CARRY threshold_dual_leg 第一版

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式 research-only carry 模型：

```bash
python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families carry \
  --carry-model threshold_dual_leg \
  --carry-entry-threshold-pct 0.00008 \
  --carry-exit-threshold-pct 0.00004 \
  --carry-min-hold-periods 3
```

默认 `carry_model=naive` 不变；新模型只在显式参数下使用。模型计入：

```text
entry threshold / exit threshold
min_hold_periods
dual-leg entry cost = 2 * cost_per_directional_bet
dual-leg exit cost = 2 * cost_per_directional_bet
dual-leg switch cost = 4 * cost_per_directional_bet
idle periods / entry / exit / switch event counts
```

验证：

```text
local unittest=227 OK
WSL unittest=227 OK
```

WSL 120 天 zero-cost：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T073159Z-strategy-selection-scan-qount-strategy-selection-s-carry-threshold-dual-leg-zero-cost-20260605/qount-strategy-selection-s-carry-threshold-dual-leg-zero-cost-20260605.json
carry_model=threshold_dual_leg
entry_threshold=0.00008
exit_threshold=0.00004
min_hold_periods=3
sum_return_pct=+0.04728436
sharpe=+15.3873642125
turnover_events=270
entry_events=119
exit_events=119
switch_events=16
idle_periods=868
```

WSL 120 天 maker-ish：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T073141Z-strategy-selection-scan-qount-strategy-selection-s-carry-threshold-dual-leg-maker-ish-20260605/qount-strategy-selection-s-carry-threshold-dual-leg-maker-ish-20260605.json
cost_per_directional_bet=0.0004
sum_return_pct=-0.16871564
sharpe=-11.8459471734
turnover_events=270
entry_events=119
exit_events=119
switch_events=16
idle_periods=868
decision=no_positive_cell
```

读法：阈值/最短持仓把 naive carry 的 gross cashflow 从 `+0.0824606` 降到
`+0.04728436`，但更接近实际双腿执行；maker-ish 成本后仍为负。不能进入 S-CARRY paper。
下一步是固定 discovery 网格、扩大 universe，并加入 basis / 资金占用读数，而不是为了这
4 币窗口调阈值。

### S-CARRY fixed grid + utilization / basis diagnostics

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式固定 discovery grid 参数：

```bash
python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families carry \
  --carry-model threshold_dual_leg \
  --carry-entry-threshold-grid-pct 0.00004 0.00008 0.00012 \
  --carry-exit-threshold-grid-pct 0.00002 0.00004 \
  --carry-min-hold-grid 1 3 6
```

每个 grid 组合写成独立 carry cell，不自动改配置，不作为 promotion。输出新增：

```text
carry_invested_periods
carry_utilization_ratio
carry_dual_leg_gross_exposure_periods
carry_avg_dual_leg_gross_exposure_pct
basis_sample_count
basis_avg_abs_pct / basis_max_abs_pct
```

验证：

```text
local unittest=228 OK
WSL unittest=228 OK
```

WSL 120 天 fixed grid zero-cost：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T081342Z-strategy-selection-scan-qount-strategy-selection-s-carry-fixed-grid-zero-cost-20260605/qount-strategy-selection-s-carry-fixed-grid-zero-cost-20260605.json
cell_count=18
best_entry_threshold=0.00004
best_exit_threshold=0.00002
best_min_hold_periods=1
sum_return_pct=+0.07147182
sharpe=+24.8646327338
turnover_events=608
utilization=0.6715277778
avg_dual_leg_gross_exposure=1.3430555556
basis_sample_count=0
```

WSL 120 天 fixed grid maker-ish：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T081321Z-strategy-selection-scan-qount-strategy-selection-s-carry-fixed-grid-maker-ish-20260605/qount-strategy-selection-s-carry-fixed-grid-maker-ish-20260605.json
cell_count=18
cost_per_directional_bet=0.0004
best_entry_threshold=0.00012
best_exit_threshold=0.00002
best_min_hold_periods=6
sum_return_pct=-0.02967449
sharpe=-3.9818426324
turnover_events=73
utilization=0.2708333333
avg_dual_leg_gross_exposure=0.5416666667
basis_sample_count=0
decision=no_positive_cell
```

读法：固定 grid 没有找到 maker-ish 成本后仍为正的 CARRY cell。zero-cost best 说明 gross
cashflow 存在；maker-ish best 转负说明 4 币 universe 下成本仍吃掉 edge。Binance
`fetch_funding_rate_history` 当前未给可用 mark/index 历史，所以 basis 诊断字段存在但
`basis_sample_count=0`；basis 风险需要后续接 mark/index 或 premium index 历史数据源。
当前不能进入 S-CARRY paper。

### S-CARRY premium index basis source

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式 basis 数据源：

```bash
python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families carry \
  --carry-model threshold_dual_leg \
  --carry-basis-source premium_index
```

实现：通过 ccxt `fetch_premium_index_ohlcv` 拉 Binance 8h premium index kline，用 close
作为 premium/basis 代理，并按 funding 8h bucket 合并到 funding rows。默认
`carry_basis_source=funding_history` 不变；只有显式 `premium_index` 才多拉该数据源。

验证：

```text
local unittest=229 OK
WSL unittest=229 OK
```

WSL 120 天 fixed grid maker-ish + premium basis：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083154Z-strategy-selection-scan-qount-strategy-selection-s-carry-fixed-grid-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-fixed-grid-premium-basis-maker-ish-20260605.json
premium_index_8h_fetch=361 bars per symbol
cell_count=18
cost_per_directional_bet=0.0004
best_entry_threshold=0.00012
best_exit_threshold=0.00002
best_min_hold_periods=6
sum_return_pct=-0.02967449
turnover_events=73
utilization=0.2708333333
avg_dual_leg_gross_exposure=0.5416666667
basis_sample_count=390
basis_avg_abs_pct=0.0005576725
basis_max_abs_pct=0.00143783
decision=no_positive_cell
```

读法：basis 数据源已接通，之前 `basis_sample_count=0` 的问题已解决。收益结论没有变化：
premium basis 只是风险诊断，不改变 CARRY PnL；4 币 maker-ish 成本后 best cell 仍为负，
不能进入 S-CARRY paper。下一步是扩大 universe 和更真实 spot/perp 双腿资金占用/执行口径。

### S-CARRY top12 universe + premium basis cost control

WSL 120 天 top12 fixed grid maker-ish + premium basis：

```text
symbols=BTC/ETH/ZEC/SOL/HYPE/WLD/XRP/BNB/NEAR/DOGE/ADA/SUI USDT perpetuals
maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083609Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605.json
premium_index_8h_fetch=361 bars per symbol
sample_count=4680
cell_count=18
cost_per_directional_bet=0.0004
best_entry_threshold=0.00012
best_exit_threshold=0.00002
best_min_hold_periods=6
sum_return_pct=-0.07594874
sharpe=-2.9327964782
turnover_events=221
utilization=0.2816239316
avg_dual_leg_gross_exposure=0.5632478632
basis_sample_count=1318
basis_avg_abs_pct=0.0005359447
basis_max_abs_pct=0.00265777
decision=no_positive_cell
best_cell_only_positive_symbol=WLD/USDT:USDT +0.03113714
```

同 universe / grid / premium basis 的 zero-cost control：

```text
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083859Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605/qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605.json
cost_per_directional_bet=0
best_entry_threshold=0.00004
best_exit_threshold=0.00002
best_min_hold_periods=1
sum_return_pct=+0.27826189
sharpe=+20.6366164287
turnover_events=2104
utilization=0.6970085470
avg_dual_leg_gross_exposure=1.3940170940
basis_sample_count=3262
basis_avg_abs_pct=0.0004813930
basis_max_abs_pct=0.00265777
decision=carry_candidate
```

读法：扩到 12 币后，zero-cost gross funding cashflow 从 4 币 fixed grid 的 `+0.07147182`
提升到 `+0.27826189`，S-CARRY 仍值得继续；但这主要来自低阈值、高换手 cell，maker-ish
成本后同一 universe 全部 grid 仍为负。当前瓶颈从“没有 gross cashflow”收敛为“成本 / 双腿执行 /
资金占用 / basis 风险没有可交易证明”。不能进入 S-CARRY paper；下一步做 explicit hedge
history replay 与 post-only 成交率/资金占用模型。

### S-CARRY explicit spot/perp capital model

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式 research-only 参数：

```bash
python -m qount.main strategy-selection-scan \
  --families carry \
  --carry-model threshold_dual_leg \
  --carry-execution-cost-model per_order \
  --carry-capital-model spot_perp_gross \
  --carry-perp-margin-fraction 0.1666667
```

默认仍是旧 `directional_round_trip + perp_notional`，旧 artifact 口径不变。新字段包括
`carry_order_cost_pct`、`carry_capital_per_perp_notional`、
`carry_avg_dual_leg_gross_exposure_on_capital_pct`、`carry_gross_funding_return_pct`、
`carry_execution_cost_sum_pct`、`carry_cost_to_gross_ratio`、
`carry_break_even_order_cost_pct`。

验证：

```text
local unittest=230 OK
WSL unittest=230 OK
```

WSL 120 天 top12 explicit spot/perp gross，per-order cost `0.0002`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605.json
execution_cost_model=per_order
capital_model=spot_perp_gross
perp_margin_fraction=0.1666667
order_cost=0.0002
best_entry_threshold=0.00012
best_exit_threshold=0.00002
best_min_hold_periods=6
sum_return_pct=+0.0106725083
sharpe=+0.7275658326
turnover_events=221
gross_funding_return_pct=+0.0864439347
execution_cost_sum_pct=+0.0757714264
cost_to_gross_ratio=0.8765383794
break_even_order_cost_pct=0.0002281703
positive_cells=3/18
basis_sample_count=1318
basis_max_abs_pct=0.00265777
decision=carry_candidate
```

同口径 cost stress，per-order cost `0.00025`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085742Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605.json
order_cost=0.00025
best_sum_return_pct=-0.0082703483
best_sharpe=-0.5083163356
cost_to_gross_ratio=1.0956729742
break_even_order_cost_pct=0.0002281703
decision=no_positive_cell
```

读法：explicit spot/perp 口径下出现小正候选，但这不是 paper 许可。正收益完全依赖
`order_cost <= 0.00022817`，per-order 成本只增加 5bp 的一半级别就转负；同时 basis tail
`0.00265777` 大于净收益边际。下一步应先做 post-only 成交率和实测订单成本验证，再做
basis tail 压力；不能把 discovery best cell promotion。

### S-CARRY fixed-cell validation_v1 one-day sanity

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

`strategy-selection-scan` 新增显式 `--holdout-role discovery|validation_v1|unknown`，默认
仍为 `discovery`。用于把固定参数 sanity artifact 和 discovery grid artifact 区分开。

验证：

```text
local unittest=230 OK
WSL unittest=230 OK
```

固定参数：top12 explicit spot/perp best cell，entry `0.00012` / exit `0.00002` /
min-hold `6`，不跑 grid search。

WSL 1 天 `validation_v1` sanity，per-order cost `0.0002`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103552Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
holdout_role=validation_v1
sample_count=51
order_cost=0.0002
sum_return_pct=+0.0003597343
sharpe=+2.6637283960
turnover_events=4
gross_funding_return_pct=+0.0017311628
execution_cost_sum_pct=+0.0013714285
cost_to_gross_ratio=0.7922007833
break_even_order_cost_pct=0.0002524613
basis_sample_count=14
basis_max_abs_pct=0.00235832
decision=carry_candidate
```

同窗口 cost stress，per-order cost `0.00025`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103620Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605.json
order_cost=0.00025
sum_return_pct=+0.0000168771
sharpe=+0.1072893774
cost_to_gross_ratio=0.9902509791
break_even_order_cost_pct=0.0002524613
decision=carry_candidate
```

读法：这个新窗口没有立即证伪 CARRY fixed cell，但证据强度不足以 paper。窗口只有 1 天、
51 条 funding 样本、4 个 entry events；`0.00025` 成本下几乎贴着 break-even。basis tail
`0.00235832` 仍明显大于净收益边际。下一步继续做 post-only fill / 实测订单成本 / basis tail，
不是 promotion。

### S-CARRY basis tail diagnostic

变更：

```text
src/qount/strategy_selection.py
tests/test_strategy_optimization.py
```

`strategy-selection-scan` 的 CARRY cell 增加纯诊断字段，不改变
`portfolio_sum_return_pct`：

```text
basis_single_tail_loss_on_capital_pct
basis_single_tail_to_net_ratio
portfolio_sum_after_single_basis_tail_pct
by_symbol.*.sum_after_single_basis_tail_pct
```

验证：

```text
local unittest=230 OK
WSL unittest=230 OK
```

同一个 1 天 `validation_v1` fixed cell 复跑，per-order cost `0.0002`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T104512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
holdout_role=validation_v1
sample_count=51
order_cost=0.0002
portfolio_sum_return_pct=+0.0003597343
portfolio_sharpe=+2.6637283960
turnover_events=4
gross_funding_return_pct=+0.0017311628
execution_cost_sum_pct=+0.0013714285
cost_to_gross_ratio=0.7922007833
break_even_order_cost_pct=0.0002524613
basis_sample_count=14
basis_max_abs_pct=0.00235832
basis_single_tail_loss_on_capital_pct=0.0020214171
basis_single_tail_to_net_ratio=5.6191951202
portfolio_sum_after_single_basis_tail_pct=-0.0016616828
```

有实际持仓的逐币 tail 读数：

```text
ZEC sum=+0.0004934743 tail_ratio=4.0962968110 after_tail=-0.0015279428
SOL sum=+0.0000535886 tail_ratio=13.0929302623 after_tail=-0.0006480428
HYPE sum=-0.0000322629 tail_ratio=29.9391604676 after_tail=-0.0009981857
XRP sum=-0.0001550657 tail_ratio=3.8154883644 after_tail=-0.0007467171
```

读法：basis-tail 诊断没有改变原 PnL，但给出了更严格的风险压力结论。1 天 fixed-cell
`+0.0003597343` 的净收益会被同窗口观察到的一次最大 basis shock 估算压力抹掉并转成
`-0.0016616828`，tail/net 比例约 `5.62x`。这说明当前 S-CARRY 小正候选没有 paper
资格；下一步必须先补 post-only fill / 实测订单成本，以及 basis-tail-aware hedge / exit
模型，不能把 fixed-cell sanity 当 promotion。

### S-CARRY simple basis tail stop

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增显式 research-only 参数：

```text
--carry-basis-tail-stop-pct
```

默认 `None`，不改变旧扫描。显式设置后，`threshold_dual_leg` 在持仓且
`abs(basis_pct) >= threshold` 时强制退出，计入双腿平仓成本，并输出：

```text
basis_tail_stop_threshold_pct
basis_tail_stop_events
by_symbol.*.basis_tail_stop_events
```

验证：

```text
local strategy-selection tests=9 OK
local unittest=231 OK
sync-to-wsl.sh --install=OK
WSL unittest=231 OK
```

同一个 1 天 `validation_v1` fixed cell，per-order cost `0.0002`，测试三个 stop：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105545Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605.json
stop=0.0010
portfolio_sum_return_pct=-0.0008075743
portfolio_sharpe=-5.7715287233
basis_tail_stop_events=2
carry_execution_cost_sum_pct=0.0023999999
basis_max_abs_pct=0.00081857
basis_single_tail_loss_on_capital_pct=0.0007016314
basis_single_tail_to_net_ratio=0.8688134838
portfolio_sum_after_single_basis_tail_pct=-0.0015092057

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105616Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605.json
stop=0.0015
portfolio_sum_return_pct=-0.0004218600
portfolio_sharpe=-3.5005595112
basis_tail_stop_events=1
carry_execution_cost_sum_pct=0.0020571428
basis_max_abs_pct=0.00112691
basis_single_tail_loss_on_capital_pct=0.0009659228
basis_single_tail_to_net_ratio=2.2896763313
portfolio_sum_after_single_basis_tail_pct=-0.0013877828

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105622Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605.json
stop=0.0020
portfolio_sum_return_pct=-0.0004218600
portfolio_sharpe=-3.5005595112
basis_tail_stop_events=1
carry_execution_cost_sum_pct=0.0020571428
basis_max_abs_pct=0.00112691
basis_single_tail_loss_on_capital_pct=0.0009659228
basis_single_tail_to_net_ratio=2.2896763313
portfolio_sum_after_single_basis_tail_pct=-0.0013877828
```

读法：simple hard stop 能把最大持仓期 basis 从 `0.00235832` 降到 `0.00081857` /
`0.00112691`，但退出成本和少收 funding 直接把组合 PnL 转负。当前 S-CARRY 不能靠单一
basis hard stop 解决，仍不能 paper。下一步应转向 post-only fill / 实测订单成本，或做
更细的 symbol/filter 与 hedge timing，而不是继续在这个 1 天窗口调 stop 阈值。

### S-CARRY cost audit + WLD/SOL filter probe

只读 live 成本审计：

```text
command=execution-cost-audit --limit 200
orders_considered=200
market_orders_analyzed=4
avg_abs_slippage_pct=0.0421792397
p50_abs_slippage_pct=0.0440920717
p90_abs_slippage_pct=0.0544432983
max_abs_slippage_pct=0.0574514535
fee_rate_pct=null
missing_fee_info=4
```

读法：样本太少，且 fee 信息缺失，不能直接作为最终实测成本；但历史 live 市价单 slippage
中位约 `0.044%`，已经高于当前 S-CARRY fixed-cell 的 `0.020%` per-order 假设。

120 天 discovery explicit artifact 的逐币读法：

```text
source=/home/alyaloale/Code/qount/state/research_runs/20260605T085512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605.json
positive_by_symbol=WLD +0.0342318333, SOL +0.0036256113, ZEC +0.0009311400
ZEC_after_single_basis_tail=-0.0005715771
```

按 discovery tail-aware 过滤，只保留 `WLD/SOL`，固定参数复跑：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110031Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
holdout_role=discovery
sample_count=720
portfolio_sum_return_pct=+0.0378574446
portfolio_sharpe=+8.9535171438
turnover_events=51
gross_funding_return_pct=+0.0553431584
execution_cost_sum_pct=+0.0174857138
cost_to_gross_ratio=0.3159507749
break_even_order_cost_pct=0.0006330100
basis_max_abs_pct=0.00265777
portfolio_sum_after_single_basis_tail_pct=+0.0355793561
```

同一 WLD/SOL filter 在已看过的 1 天 sanity 窗口：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110033Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
holdout_role=validation_v1
sample_count=8
portfolio_sum_return_pct=+0.0000535886
portfolio_sharpe=+1.9439023230
turnover_events=1
gross_funding_return_pct=+0.0003964457
execution_cost_sum_pct=+0.0003428571
cost_to_gross_ratio=0.8648274669
break_even_order_cost_pct=0.0002312600
basis_max_abs_pct=0.00081857
portfolio_sum_after_single_basis_tail_pct=-0.0006480428
```

成本压力：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110109Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605.json
order_cost=0.00025
portfolio_sum_return_pct=-0.0000321257
cost_to_gross_ratio=1.0810343337
portfolio_sum_after_single_basis_tail_pct=-0.0007337571

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110114Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605.json
order_cost=0.00045
portfolio_sum_return_pct=-0.0003749828
cost_to_gross_ratio=1.9458618006
portfolio_sum_after_single_basis_tail_pct=-0.0010766143
```

读法：`WLD/SOL` 是当前最像样的 S-CARRY symbol filter，120 天 discovery 的 net / after-tail
都明显好于 top12。但 1 天 sanity 只有 SOL 成交，after-tail 仍为负；per-order cost
提高到 `0.00025` 即转负，而历史 live 市价单 slippage 中位约 `0.00044`。不能 paper。
下一步应先证明 maker/post-only fill 能把实际 per-order cost 压到 `0.000231` 以下，或找
新的独立日期继续验证 WLD/SOL 的稳定性。

### S-CARRY WLD/SOL monthly and early-June read

WLD/SOL 固定参数分月 discovery：

```text
feb_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111620Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-feb-20260605/qount-strategy-selection-s-carry-wld-sol-feb-20260605.json
sum=+0.0040478056
after_tail=+0.0028153799
turnover_events=19

mar_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111622Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-mar-20260605/qount-strategy-selection-s-carry-wld-sol-mar-20260605.json
sum=+0.0028695942
after_tail=+0.0017230457
turnover_events=15

apr_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111625Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-apr-20260605/qount-strategy-selection-s-carry-wld-sol-apr-20260605.json
sum=+0.0190945623
after_tail=+0.0168164738
turnover_events=7

may_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111627Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-may-20260605/qount-strategy-selection-s-carry-wld-sol-may-20260605.json
sum=+0.0119759397
after_tail=+0.0104161540
turnover_events=11
```

6 月已看窗口逐日固定参数复核全部降级 `discovery`，只看稳定性：

```text
jun01_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110450Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-day-jun01-20260605/qount-strategy-selection-s-carry-wld-sol-day-jun01-20260605.json
sum=0.0
turnover_events=0

jun02_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110452Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-day-jun02-20260605/qount-strategy-selection-s-carry-wld-sol-day-jun02-20260605.json
sum=0.0
turnover_events=0

jun03_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110455Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-day-jun03-20260605/qount-strategy-selection-s-carry-wld-sol-day-jun03-20260605.json
sum=-0.0000948771
after_tail=-0.0005669486
turnover_events=1

jun04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110458Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-day-jun04-20260605/qount-strategy-selection-s-carry-wld-sol-day-jun04-20260605.json
sum=+0.0000535886
after_tail=-0.0006480428
turnover_events=1

jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111629Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605.json
sum=+0.0003015686
after_tail=-0.0004000628
turnover_events=1
```

2026-06-05 当前只是 partial day，不作为 validation：

```text
partial_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T111654Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605.json
holdout_role=unknown
sample_count=4
sum=-0.0002471743
after_tail=-0.0003076628
turnover_events=2
```

读法：WLD/SOL 在 2-5 月 discovery 月月为正，且 after-tail 也为正，说明它不是单日假象；
但 4/5 月主要靠 WLD，6/1-6/4 已看窗口 after-tail 为负，6/5 partial 也暂时为负。不能
paper。下一步只能等新的完整独立日期复核，或先解决 maker/post-only 成本；不能继续用
6/1-6/5 调阈值后声称 validation。

### S-CARRY post-only economics diagnostic

变更：

```text
src/qount/strategy_selection.py
src/qount/main.py
tests/test_strategy_optimization.py
```

新增 research-only 诊断参数：

```text
--carry-maker-order-cost-pct
--carry-taker-order-cost-pct
```

这些参数只计算所需 maker fill rate，不改变 `portfolio_sum_return_pct`。输出新增：

```text
carry_post_only_maker_order_cost_pct
carry_post_only_taker_order_cost_pct
carry_post_only_target_order_cost_for_break_even_pct
carry_post_only_target_order_cost_after_single_basis_tail_pct
carry_required_maker_fill_rate_for_break_even
carry_required_maker_fill_rate_after_single_basis_tail
carry_post_only_break_even_feasible
carry_post_only_after_tail_feasible
```

验证：

```text
local strategy-selection tests=10 OK
local unittest=232 OK
sync-to-wsl.sh --install=OK
WSL unittest=232 OK
```

WLD/SOL 固定参数，maker cost `0`，taker cost `0.00045`：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T113704Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
holdout_role=discovery
portfolio_sum_return_pct=+0.0378574446
portfolio_sum_after_single_basis_tail_pct=+0.0355793561
turnover_events=51
target_order_cost_for_break_even_pct=0.0006330100
target_order_cost_after_single_basis_tail_pct=0.0006069534
required_maker_fill_for_break_even=0.0
required_maker_fill_after_single_basis_tail=0.0
after_tail_feasible=true

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T113706Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605.json
window=2026-06-01T00:00:00Z..2026-06-05T00:00:00Z
holdout_role=discovery
portfolio_sum_return_pct=+0.0003015686
portfolio_sum_after_single_basis_tail_pct=-0.0004000628
turnover_events=1
target_order_cost_for_break_even_pct=0.0003759150
target_order_cost_after_single_basis_tail_pct=-0.0000333700
required_maker_fill_for_break_even=0.1646333333
required_maker_fill_after_single_basis_tail=1.0741555556
after_tail_feasible=false

artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T113709Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605.json
window=2026-06-05T00:00:00Z..2026-06-05T11:00:00Z
holdout_role=unknown
portfolio_sum_return_pct=-0.0002471743
portfolio_sum_after_single_basis_tail_pct=-0.0007569857
turnover_events=2
target_order_cost_after_single_basis_tail_pct=-0.0000207875
required_maker_fill_after_single_basis_tail=1.0461944444
after_tail_feasible=false
```

读法：post-only economics 证明 WLD/SOL 120 天 discovery 并不依赖低成本，甚至 taker
`0.00045` 也可 after-tail 为正；但 6/1-6/5 的 after-tail 亏损不是 maker fill 能解决的，
因为 after-tail 为正需要超过 100% maker fill。下一步不应继续成本调参，应该研究
hedge timing / basis regime filter，或者转向 1d TS-MOM 扩 universe。

## 2026-06-04

### 7907 Binance 专线恢复

现象：

```text
QountBinanceProxy task=Ready
WSL tcp 192.168.128.1:7907=fail
candidate-walk-forward failed at binance fapi exchangeInfo proxy timeout
```

处理：

```powershell
Start-ScheduledTask -TaskName QountBinanceProxy
```

恢复读数：

```text
Windows 7907 listener=verge-mihomo.exe
WSL tcp 192.168.128.1:7907=ok
curl --proxy http://192.168.128.1:7907 https://fapi.binance.com/fapi/v1/time=ok
preflight-live public_api/symbols/credentials/position_mode/balance_guard=ok
live_guard ok=false reason=live_disabled
```

读法：这是基础设施恢复，不是 live 许可；`QOUNT_LIVE_ENABLE=false` 保持不变。

### validation_v1 candidate v1/v2 对比

命令口径：

```text
candidate-walk-forward --research-profile eth-only --holdout-role validation_v1
windows:
  val-jun01=2026-06-01T00:00:00Z,2026-06-02T00:00:00Z
  val-jun02=2026-06-02T00:00:00Z,2026-06-03T00:00:00Z
```

Artifacts：

```text
v1=/home/alyaloale/Code/qount/state/research_runs/20260604T132940Z-candidate-walk-forward-qount-candidate-wf-eth-validation-v1-v1-20260604
v2=/home/alyaloale/Code/qount/state/research_runs/20260604T132941Z-candidate-walk-forward-qount-candidate-wf-eth-validation-v1-v2-20260604
```

读数：

```text
window_count=2
total_cycles=578
total_fresh_entry_selected=25
v1_total_selected_cycles=25
v2_total_selected_cycles=25
v1_strong_favorable=0
v2_strong_favorable=0
```

读法：`v2_interactions` 没有增加 candidate 覆盖，也没有产生更强 setup quality；
不进入端到端验证，不替换主线 v1。

### validation_v1 端到端 walk-forward

命令口径：

```text
walk-forward --research-profile eth-only --holdout-role validation_v1 \
  --setup-model-version v1 --ai-decision-cache
windows:
  val-jun01=2026-06-01T00:00:00Z,2026-06-02T00:00:00Z
  val-jun02=2026-06-02T00:00:00Z,2026-06-03T00:00:00Z
```

Artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260604T134036Z-walk-forward-qount-wf-eth-validation-v1-v1-20260604
```

总读数：

```text
oos_safe_windows=2
positive_realized_windows=0/2
paper_filled=7
paper_closed=8
sum_realized_return_pct=-0.7159862916%
avg_realized_return_pct=-0.3579931458%
windows_with_open_positions=0
total_reviewed=40
total_review_missed_candidate_move=2
windows_with_missed_candidate_move=1
```

分窗：

```text
val-jun01 realized=-0.1510033978% paper_filled=1 paper_closed=1
  review_avg_net_edge=-0.0676188793% missed_candidate_move=0
val-jun02 realized=-0.5649828938% paper_filled=6 paper_closed=7
  review_avg_net_edge=-0.0558199036% missed_candidate_move=2
```

Tag 读法：

```text
eth_trend_impulse_range_noise_range_gt012:
  reviewed=1 bad=1 avg_net_edge=-0.9964830654%
eth_trend_impulse_range_noise_washout:
  reviewed=1 bad=1 avg_net_edge=-0.9964830654%
eth_trend_impulse_short_breakdown_chase:
  reviewed=9 hold_reviewed=9 missed_candidate_move=2
  avg_candidate_aligned_future_return_pct=-0.0240872630%
  avg_candidate_opportunity_edge_pct=+0.1548490521%
```

结论：

- 这次 once-only validation 不满足 `G_paper`，不能 forward paper。
- `range_noise_range_gt012` / `washout` 在新样本中直接变成 bad trade，不能进 gate。
- `short_breakdown_chase` 有 2 个 missed candidate move，但整体 tag/readout 不支持通过
  放宽 short entry 修复；这两个窗口已使用，后续调参不能再把它们当 validation。
- 保持 `ETH-only research-only`、live disabled。

### terminal washout blocker：盈利方向验证

改动：

```text
src/qount/candidate_filter.py
reason=eth_short_range_noise_terminal_washout
hard_bottom_line=true
```

触发条件：

```text
symbol=ETH/USDT:USDT
fresh_entry action=sell
setup_phase=range_noise
higher_timeframe_bias=short
higher_timeframe_phase=trend
return_24bars <= -0.0100
rsi_14 <= 32.0
sma_fast_ratio <= -0.0080
sma_slow_ratio <= -0.0080
volume_ratio_20 >= 1.50
range_pct >= 0.0080
```

本地窄测试：

```text
test_candidate_filter_hard_blocks_eth_range_noise_terminal_washout
targeted range_noise unittest: 9 OK
```

完整验证：

```text
local unittest discover: 221 OK
sync-to-wsl.sh: OK
WSL unittest via run-wsl-tests.sh: 221 OK
```

已失败 validation 窗口降级 discovery 后复测：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T135759Z-walk-forward-qount-wf-eth-terminal-washout-block-discovery-20260604
windows=disc-jun01 2026-06-01T00:00:00Z..2026-06-02T00:00:00Z
        disc-jun02 2026-06-02T00:00:00Z..2026-06-03T00:00:00Z
holdout_role=discovery
positive_realized_windows=1/2
paper_filled=4
paper_closed=5
sum_realized_return_pct=+0.9173089048%
avg_realized_return_pct=+0.4586544524%
windows_with_open_positions=0
total_review_missed_candidate_move=2
disc-jun01 realized=-0.1510033978%
disc-jun02 realized=+1.0683123026%
```

读法：这是有效的 loss-attribution blocker，说明 6/2 的 terminal washout short
不该开；但这两个窗口已在失败 validation 中被看过，只能作为 discovery。

新的 once-only validation 第一次运行：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T141045Z-walk-forward-qount-wf-eth-terminal-washout-block-val-jun03-20260604
window=val-jun03 2026-06-03T00:00:00Z..2026-06-04T00:00:00Z
holdout_role=validation_v1
oos_safe_windows=1
positive_realized_windows=0/1
paper_filled=2
paper_closed=1
sum_realized_return_pct=-0.3858229487%
unrealized_return_pct=+0.8770829226%
total_return_pct=+0.4912599739%
windows_with_open_positions=1
open_positions=1
max_drawdown_pct=2.8234367106%
total_review_missed_candidate_move=0
review_avg_net_edge_pct=-0.0005301342
promotion_blockers=open_position_remaining,non_positive_realized_return,non_positive_review_edge
raw_ai_error_count=227/289
validated_invalid=227
halted=true
```

读法：这份 artifact 的 open position 主要来自 AI auth outage，不是可直接调参的 exit 证据。

AI relay 恢复后做同策略 infra rerun：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T145900Z-walk-forward-qount-wf-eth-terminal-washout-block-val-jun03-infra-rerun-20260604
window=val-jun03 2026-06-03T00:00:00Z..2026-06-04T00:00:00Z
holdout_role=validation_v1
oos_safe_windows=1
positive_realized_windows=0/1
paper_filled=6
paper_closed=6
sum_realized_return_pct=-1.1912362466%
windows_with_open_positions=0
max_drawdown_pct=1.5370303348%
total_reviewed=26
total_review_missed_candidate_move=1
review_avg_net_edge_pct=-0.0383055167%
raw_ai_error_count=0/289
validated_invalid=0
promotion_blockers=non_positive_realized_return,non_positive_review_edge
```

Order attribution:

```text
entry_runs=20,43,206,234,241,250
closed_trades=6
wins=1
losses=5
run43 pnl=+0.3846991822 quote
run241 pnl=-0.9643193956 quote
run250 pnl=-0.1322188764 quote
```

Terminal-washout miss read:

```text
run241 return_24bars=-0.01710 rsi_14=15.17 sma_fast=-0.00973 sma_slow=-0.01457 volume_ratio_20=2.27 range_pct=0.00595
run250 return_24bars=-0.02331 rsi_14=28.59 sma_fast=-0.00771 sma_slow=-0.01788 volume_ratio_20=2.70 range_pct=0.00727
current blocker misses because range_pct>=0.008 and sma_fast<=-0.008 are too narrow
```

结论：方向上比原 baseline 好，但仍没有通过 `G_paper`。真实下一步是研究 repeated
`range_noise` short、loss reentry cooldown 和 terminal-washout 阈值；不要放宽
`range_noise` / `short_rebound_fail` 来追成交。2026-06-03..2026-06-04 已看过，后续调参后
不能再用它宣称 promotion。

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
local unittest: 220 OK
sync-to-wsl.sh --install: OK
WSL unittest via run-wsl-tests.sh: 220 OK
```

### T-B AI hold-bias 工具化

新增：

```text
ai-hold-baseline
src/qount/ai_hold_baseline.py
```

能力：

- 从 backtest / walk-forward artifact 的 `qount.db` 还原 selected fresh-entry prompt 样本。
- 支持 profile / symbol / target tag / run_id 过滤。
- 支持 `v1`、`v2_remove_default_wait`、`v3_veto_only` prompt 研究变体。
- 默认结果写入 `state/research_runs`；diagnostic only，不是 promotion 证据。

WSL 读数：

```text
multi_symbol_dry_run=/home/alyaloale/Code/qount/state/research_runs/20260531T064411Z-ai-hold-baseline-qount-ai-hold-multi-fast-sma-dryrun-20260531/qount-ai-hold-multi-fast-sma-dryrun-20260531.json
sample_count=24
stored_hold=24/24
windows=ws4 step3 mar03 20 + apr20 4

eth_only_symbol_filter=/home/alyaloale/Code/qount/state/research_runs/20260531T064410Z-ai-hold-baseline-qount-ai-hold-ethonly-symbol-filter-20260531/qount-ai-hold-ethonly-symbol-filter-20260531.json
sample_count=2
symbols_filter=ETH/USDT

eth_only_v3_smoke=/home/alyaloale/Code/qount/state/research_runs/20260531T064502Z-ai-hold-baseline-qount-ai-hold-ethonly-v3-smoke-20260531/qount-ai-hold-ethonly-v3-smoke-20260531.json
sample_count=2
request_count=2
replayed_hold=2/2
```

读法：WS-4 fast-SMA step3 的 24 条目标样本确实是 AI 层全 hold；但 `v3_veto_only`
在 ETH-only 小样本 smoke 里仍 hold，且理由是具体 veto（负 expected_edge、SMA/24bar
冲突、rebound 或过热），所以不能把 prompt v3 直接推进到 gate。

### T-G 0 交易窗口诊断

新增/修改：

```text
idle-window-diagnostic
src/qount/idle_window_diagnostic.py
```

能力：

- 扫描既有 backtest / walk-forward artifact 的 `qount.db` / `summary.json`。
- 默认跳过有 paper fill/close 的窗口，只看 0 交易窗口。
- 输出 setup model label/quality、setup phase、candidate blocker、traditional pattern、
  AI hold reason 和 top candidate h6 future edge。
- 只读诊断，不调用 AI、不执行订单、不改 candidate / risk / live。
- 修正 reason aggregate：窗口展示受 `--reason-limit` 限制，aggregate 使用未截断计数。

WSL 读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T072108Z-idle-window-diagnostic-qount-idle-window-diagnostic-ethonly-20260531-v2/qount-idle-window-diagnostic-ethonly-20260531-v2.json
backtest_count=39
window_count=36
idle_window_count=36
skipped_traded_window_count=3
candidate_filter_hold_count=2878
ai_hold_count=87
selected_or_candidate_like_scored_count=890
positive_top_candidate_avg_future_edge_windows=5/36
positive_top_candidate_avg_future_edge_rate=0.1388888888888889
```

setup model quality：

```text
missing=2867
unfavorable=72
weak_favorable=12
neutral=4
strong_favorable=0
```

主要 candidate blocker：

```text
eth_short_research_blocks_fresh_outside_short_trend_family_open=1598
eth_short_range_noise_requires_breakdown_structure=1191
low_volatility=874
low_volume=609
low_volatility_soft_penalty=605
short_setup_countertrend_drift=441
low_volume_soft_penalty=405
```

验证：

```text
local unittest: 220 OK
sync-to-wsl.sh --install: OK
WSL unittest via run-wsl-tests.sh: 220 OK
```

读法：0 交易窗口主要是 research/candidate/market-quality 层主动拦截，setup_model
没有在这些窗口里给出大量 strong favorable 候选；5/36 正 top-candidate-edge 窗口仍是
已看过 discovery 样本，不能作为 promotion 或新 gate 证据。

### T-C setup_model v2 interaction 对比

新增/修改：

```text
setup_model v2_interactions
setup-model-compare
walk-forward / setup-edge-walk-forward / candidate-walk-forward --setup-model-version
```

能力：

- v1 默认不变。
- v2 在 v1 16 维特征上增加 higher-timeframe phase × bin 交互。
- `setup-model-compare` 用 chronological train/eval split 离线对比 v1/v2。
- 只拉历史 K 线并训练/评分，不调用 AI、不执行订单、不改变 candidate / risk / live。

WSL 默认相位读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T075127Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-20260531/qount-setup-model-compare-ethonly-v2-20260531.json
example_count=705
eval_example_count=212
v1_top_decile_avg_target_edge_pct=-0.0011523934
v2_top_decile_avg_target_edge_pct=-0.0013773666
v2_minus_v1_top_decile=-0.0002249732
v2_minus_v1_mae=+0.0000124423
```

WSL range-noise-inclusive 读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T075351Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-range-20260531/qount-setup-model-compare-ethonly-v2-range-20260531.json
example_count=19681
eval_example_count=5905
v1_top_decile_avg_target_edge_pct=-0.0015544902
v2_top_decile_avg_target_edge_pct=-0.0013618186
v2_minus_v1_top_decile=+0.0001926716
v2_minus_v1_mae=+0.0000053851
v2_directional_accuracy=0.7334010840
v1_directional_accuracy=0.7347560976
v2_strong_favorable=0
```

验证：

```text
local unittest: 220 OK
sync-to-wsl.sh --install: OK
WSL unittest via run-wsl-tests.sh: 220 OK
```

读法：第一版 v2 interaction plumbing 可用，但读数不支持推进。包含 `range_noise` 后
top decile 相对 v1 略好，但绝对 future edge 仍为负，MAE 和 directional accuracy 略差，
且 `strong_favorable=0`。不能替换主线 setup model，不能写 gate。

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
4. T-C 第一版 v2 已证不够；继续时只做 targeted ablation / calibration，不替换主线。
5. 继续做 T-B：扩大 AI hold-bias 对照，不在 discovery 上调 prompt。
6. T-G 第一版已落地；只补诊断，不从 discovery 0 交易读数直接加 gate。
7. 只有 `G_paper` 通过后才进入 forward paper；只有 forward paper 后才讨论 `G_live`。
