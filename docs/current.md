# qount 当前状态

更新时间：2026-06-06

当前版本：`0.2.0`

这份文档是当前事实入口，只保留结论、能力边界和下一步。接手命令看
[quick-handoff.md](quick-handoff.md)，发现/验证边界看
[holdout.md](holdout.md)，长证据链看 [update-log.md](update-log.md)，架构评审和路线看
[optimization-plan.md](optimization-plan.md)，历史盈利研究路线看
[profit-research-plan.md](profit-research-plan.md)，架构天花板与现代量化 ML 升级看
[profit-engineering-plan.md](profit-engineering-plan.md)。

## 当前结论

```text
ETH-only research-only
bottom_line + future + ETH/USDT + 1 position
hourly model off
setup model phase6 on
live disabled
§7 profit-pursuit halted (2026-06-06, owner-confirmed)
```

- **2026-06-06 项目级决策(所有者确认):执行 §7 诚实止盈,停止追盈利。** 根因是架构级广度
  天花板——加密 majors r̄≈0.63,横截面有效广度仅 ~1.5、渐近天花板 `1/r̄≈1.6`(扩币救不了),
  §10.2 破局所需 IC 实际 ≈0.15、观测最强仅 0.05;横截面(XS-MOM/REV/funding)广度封死、
  日频 TS-MOM 已证伪、CARRY 已证伪——latency-insensitive 可触及路径穷尽,满足 §7 全局终止
  条件。**固化研究价值**(triple-barrier / purged-CV / DSR / PBO / effective-breadth 整套
  反过拟合 harness)作为成果,停止在择时盈利上继续投入。**这是停止投入,不放宽任何纪律**:
  live 仍关闭、不 forward paper、不放宽 broad gate、`validation_v1` once-only 资格继续保留。
  对账见 [profit-engineering-plan.md](profit-engineering-plan.md) §11.8。
- 生产真相仍是 WSL：`/home/alyaloale/Code/qount`。
- Mac 工作区是编辑和 git 表面：`/Users/alyaloale/Code/qount`。
- live 继续关闭：`QOUNT_LIVE_ENABLE=false`；`live-guard-status` 当前 `ok=false`，
  `reason=live_disabled`。
- `qount-runner.timer` / `qount-runner.service` 当前不应自动跑；最近读回为 inactive。
- 当前没有 promotion 证据，不能 forward paper，也不能 live。
- 旧 13-window 结果现在只能作为 discovery 证据；promotion 只看
  `holdout_role=validation_v1` 的 once-only 新窗口。
- 2026-06-04 第一次 `validation_v1` once-only 端到端验证失败；盈利导向补的
  `eth_short_range_noise_terminal_washout` blocker 能把这两个窗口降级 discovery 后转正。
- 2026-06-03..2026-06-04 的第一次 validation artifact 被 AI relay `auth_unavailable`
  污染；恢复后同策略复跑无 AI 错误，但 realized 更差，仍未过 `G_paper`。
- 不能用 2026-06-01..2026-06-04 已看过窗口调参后再当 validation。
- 2026-06-05 已按 [profit-engineering-plan.md](profit-engineering-plan.md) 启动 S0.1：
  research ML 依赖只作为 optional extra；live / `run-once` 默认依赖和交易行为不变。
- 2026-06-05 S1'（频段 × 策略族选择扫描）第一遍已全量跑完，结论是 CARRY 被 basis-tail
  证伪、唯一存活候选是预测族 `4h xs_mom lb24/h6` 但未过可执行 exit；计划与现实的对账见
  [profit-engineering-plan.md](profit-engineering-plan.md) §11，S2 重模型仍未启动。
- 2026-06-05 已按 §11.5 N1 做 `4h xs_mom` 的波动率缩放 triple-barrier：vol-scaling 修正了
  fixed barrier 的非对称止损病，PnL 随 barrier 加宽单调改善，但没有任何 σ 设置能跑赢"无
  barrier 持有到期"的 close-exit 基线，最佳 `tp4/sl4` 仍只有 `+0.165`(< close `+0.297`)、
  3 月仍负、~90% 收益来自 5 月单月。N1 门控未通过，**仍不进 S2**。
- 2026-06-05 又按 N1 做 entry 侧 regime dispersion 门：`thr0.034` 总收益不变(`+0.299`)、
  Sharpe `7.19→8.00`、回撤 `0.088→0.080`，并把 2026-03 从负翻正、4 月全部 ≥ 0——首个真正
  改善月度稳健性的子步骤;但属 in-sample 阈值、5 月仍约 82% 收益、无新 OOS，N1 仍未过、
  **不进 S2**;下一刀把 `thr0.034` 固定留到下一个完整 `validation_v1` once-only 复核。
- 2026-06-05 已按 §5/§9.x 给 scan 补 Deflated Sharpe Ratio：在选出候选的 81-cell 网格上
  DSR ≈ `0.082`，最佳 per-period Sharpe `0.278` < 噪声期望最大值 `0.407`——候选的网格内
  选择优势大概率是多重检验假象。S2 门控加硬:新 OOS 正 + 可接受 DSR/PBO 才进 S2。
- 2026-06-05 又补 PBO/CSCV：同一网格 pbo 4h=`0.020`/1h=`0.056`/1d=`0.214`(全 < 0.5)。
  与 DSR 互补:存在弱但排名稳定的横截面动量结构,但量级(DSR≈0.08)太弱不足以确认盈利;
  且同频段 config 高度相关会让 PBO 偏低。两指标都指向不进 S2,等新 OOS。
- **2026-06-06 决策:`4h xs_mom lb24/h6` 候选按 §7 诚实退出。** N1 反过拟合工具
  (vol-barrier / regime 门 / DSR / PBO)已全部做完,合起来给出的结论比"等新 OOS"更尖锐:
  (a) 选出候选的 81-cell 网格 **DSR ≈ 0.082**、最佳 per-period Sharpe `0.278` < 噪声期望
  最大值 `0.407`——网格内选择优势在统计上与"81 次噪声里挑最大"不可区分;(b) 没有任何
  可执行 path-dependent exit(fixed / σ-scaled barrier 及同类部分止盈/移动止损)跑得赢
  "无 barrier 持有到期"的 close 基线;(c) 即便最好的 regime 门 `thr0.034` 也仍有 ~82% 收益
  来自 5 月单月。三者合起来即 [profit-engineering-plan.md](profit-engineering-plan.md) §7
  的全局退出条件——"搜了 N 个 cell 后该候选的优势不显著"。**不为它消耗 once-only 日期**:
  今天(2026-06-06)相对该候选只多出 `2026-06-04..06` 约 2 薄天(4h 仅 ~12 根 bar),即便正也
  不可能把 DSR 从 0.08 拉到可接受;烧一次性日期在这么薄的窗口上是浪费。**关闭该候选的 S2
  晋级路径**,研究转向 §10 的换频段 / 换特征源(微结构 / funding / 时序基础模型特征),或按 §7
  接受研究价值、停止追盈利。纪律不变:不在已看 2–5 月上加任何旋钮,`validation_v1` once-only
  资格留给未来真正够厚的独立窗口。对账见 §11.7。
- **2026-06-06 §10 换特征源第一刀 kill-test:funding 作横截面预测特征 = 证伪。** 新增
  `xs_funding` / `xs_funding_rev` 两族(funding 以 as-of join 无前视对齐到每根 bar 当信号,
  区别于已被 basis-tail 证伪的 CARRY 现金流用法),复用横截面 IC / DSR / PBO harness。top12、
  120 天 discovery、post-cost、{4h,8h,1d}×{2 族}×holding{1,3,6}=18 cell:
  (a) **rank-IC 全 ≤ 0.030**(最强 4h/h3 仅 `+0.030`)——比已嫌弱的价量动量 `0.052` 还弱,
  远低于 §10.2 要求的 `0.06`;(b) 唯一正 cell `1d xs_funding_rev h6`(sum `+1.05`、sharpe
  `1.79`)的 rank-IC ≈ `0.005` ≈ 0,且相邻 holding 不一致(h1 负 / h3 `+0.50` / h6 `+1.05`),
  是 1d 仅 119 个重叠横截面上的噪声/overlap 假象;(c) **carry-tilt DSR ≈ `0.25`**,best
  per-period Sharpe `0.094` < 噪声期望最大值 `0.156`——选择优势与噪声不可区分;(d) **PBO
  ≈ 0.49–0.55**(8h/1d 相关频段),高过拟合概率;(e) 4h/8h 全被成本打负。继 CARRY 现金流
  之后,**funding 这一新信息源的第二种用法也证伪**,最便宜的新源耗尽,进一步压向 §7 诚实止盈。
  artifact:`state/research_runs/20260605T231910Z-...-s1-carry-tilt-funding-top12real-120d-20260606`
  (另有 4 币薄广度交叉验证 `...-funding-top12-120d-...`,结论一致)。只跑 discovery,未碰
  `validation_v1`。basis_pct 与 funding 经济上近共线;carry-tilt 路径暂未接 premium-index
  enrichment,如要确认性复核需补该 plumbing,优先级低。
- **2026-06-06 架构级根因诊断:横截面广度是幻觉,§10.2 破局数字被经验证伪。** 不再机械试
  第三种特征源,先查 §10.2 整套破局逻辑的前提——「日频横截面 ~10 币 → BR~300 → 要求 IC 0.06」
  ——是否成立。直接读 funding artifact 已报的 `effective_breadth`(标准公式
  `N/(1+(N-1)·r̄)`):top12 的平均绝对两两相关 **r̄ ≈ 0.63**,**有效广度仅 ≈ 1.5**(4h 1.53 /
  8h 1.50 / 1d 1.52)。关键:有效广度随 N→∞ 收敛到 `1/r̄ ≈ 1.6`,即 **N=12 给 1.52、N=100 万
  也只有 1.59——扩币在数学上救不了**。把真实有效广度代回 Grinold(IR=IC·√BR、IR=1 口径):
  §10.2 假设 ~10 币给要求 IC `0.058`;真实 ~1.5 币使 BR 缩 ~6.5×、√BR 从 17 掉到 6.8,
  **要求 IC 实际 ≈ 0.148**。而观测最强横截面 IC 只有 xs_mom `0.052` / xs_funding `0.030`,
  **离真实要求约 3× 缺口**。结论:加密 majors 同涨同跌,横截面把"多币"折成 ~1.6 个有效独立
  资产,§10 押注的广度杠杆**结构性不存在**;要求 IC 被打回 ~0.15 的"5m 不可达"区间——这正是
  §10 想逃离的天花板。这是**架构级 §7 证据**:换特征源 / 扩币都改变不了广度天花板,xs_mom /
  ts_mom / xs_funding 全部过不了线是同一个根因。**2026-06-06 所有者已据此确认执行项目级 §7
  诚实止盈**(见上方「当前结论」)。对账见 §11.8。

## 当前能力

已经具备：

- 运行链路：`snapshot -> candidate_filter -> AI -> validate -> risk -> paper/live executor -> journal`。
- Binance USDT 合约执行骨架、live guard、runtime halt、日内权益隔离。
- `signal-review` / `paper-replay` / `backtest` / `walk-forward`。
- ETH-only research profile：固定当前 phase6 setup model、`ai_temperature=0.0`、
  `ETH/USDT`、`max_open_positions=1`。
- research artifact 持久化：外部 `/tmp` 输出会镜像到 `state/research_runs/...`。
- `research-slice-scan` 的 `offline_future_edge_readiness` 诊断。
- `backtest` / `walk-forward` 的 `--holdout-role` 和研究专用 `--ai-decision-cache`。
- `setup-edge-walk-forward`：只读 setup model 层，不调用 AI、不执行订单。
- `candidate-walk-forward`：只读 candidate 层，不调用 AI、不执行订单。
- `setup-model-compare`：离线对比 setup_model v1 与 `v2_interactions`，用时间顺序
  train/eval split 读 calibration / lift；不调用 AI、不执行订单。
- `ai-hold-baseline`：从已有 artifact 还原 fresh-entry prompt 样本，统计 AI hold-bias，
  支持 `v1` / `v2_remove_default_wait` / `v3_veto_only` 研究变体。
- `idle-window-diagnostic`：只读 0 交易窗口诊断，输出 setup / candidate / AI hold
  层分布和 top candidate future edge；不调用 AI、不改变交易链路。
- `strategy-selection-scan`：S1' 频段 × 策略族选择扫描，覆盖
  `5m,1h,4h,1d` × `xs_mom,xs_rev,ts_mom,carry`；只写 research artifact，不调用 AI、
  不执行订单、不改变 live。预测族显式支持 signal lookback / holding horizon 网格；CARRY
  显式支持旧 `directional_round_trip` 成本口径和
  research-only `per_order + spot_perp_gross` 口径，用于读 explicit spot/perp 双腿执行成本、
  资金占用、break-even order cost、basis 风险、单次 basis tail 压力、post-only economics
  和显式 research-only basis tail stop / basis entry regime filter；扫描 artifact 支持显式
  `holdout_role=discovery|validation_v1|unknown`；预测族支持 research-only
  `--directional-overlap-mode all|stride`，其中 `stride` 只保留每个 holding window 一次
  cross-section，用于降低重叠 horizon 膨胀；预测族还支持 research-only
  `--directional-evaluation-mode portfolio_replay` 和
  `--directional-max-open-positions`，用于限仓组合 replay；预测族支持 research-only
  `--directional-exit-mode close|triple_barrier`、`--directional-take-profit-pct`、
  `--directional-stop-loss-pct`，用于 OHLC intrabar TP/SL barrier 复核；预测族还支持
  research-only `--directional-purged-cv-folds` / `--directional-embargo-bars`，
  用于把 fixed cell 的时间分段稳定性和 embargo 区间写入 artifact；预测族还支持
  research-only `--directional-barrier-vol-lookback-bars` /
  `--directional-take-profit-sigma` / `--directional-stop-loss-sigma`，把 triple-barrier
  的 TP/SL 从固定百分比改为按决策时点近 N 根 bar 已实现收益 σ 缩放(防泄漏)，默认关闭；
  预测族还支持 research-only `--directional-regime-min-dispersion-pct`，在每个 cross-section
  上按各币 signal 离散度做 regime 入场门(低离散度跳过该 bar,纯决策时点)，默认关闭;scan
  顶层还输出 `directional_deflated_sharpe`(Deflated Sharpe Ratio)和 `directional_pbo`
  (PBO/CSCV,按频段分组的过拟合概率)，量化"搜了 N 个 cell 后最佳 Sharpe 还剩多少可信 +
  IS 赢家在 OOS 是否仍靠前"的两类多重检验惩罚，diagnostic only。
- Mac 到 WSL 同步与测试脚本：`scripts/sync-to-wsl.sh`、`scripts/run-wsl-tests.sh`。
- `pyproject.toml` 已有 research optional extra：默认提供 `numpy` / `scikit-learn`；
  `lightgbm` 单独放在 `research-lightgbm`，因为 Mac cp314 wheel 可安装但当前缺
  `libomp.dylib`，检查脚本会把它报告为可选不可用。验证入口：
  `PYTHON_BIN=./.venv/bin/python ./scripts/check-research-deps.sh`。

当前还不具备：

- 稳定盈利能力证明。
- forward paper 许可。
- live 许可。
- 已通过 validation 的可复用窄 candidate gate。
- 已验证的 AI prompt v2/v3 改进。
- 多币 promotion gate。
- S1' 可 promotion 的稳定胜出 cell；目前 120 天 discovery / 月度 sanity 没有稳定胜者。
- Kronos 接入候选层或执行层。

## 最新策略读数

2026-06-05 已完成 S1' 第一版工具和 30 天 discovery 初扫：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T065952Z-strategy-selection-scan-qount-strategy-selection-s1-30d-20260605/qount-strategy-selection-s1-30d-20260605.json
holdout_role=discovery
window=2026-05-02T00:00:00Z..2026-06-01T00:00:00Z
symbols=SOL/XRP/BTC/ETH USDT futures
frequencies=5m,1h,4h,1d
families=xs_mom,xs_rev,ts_mom,carry
best_cell=1d ts_mom
best_sum_return_pct=+0.3121233665
best_mean_return_pct=+0.0025171239
best_sharpe=2.2679849920
best_rank_ic_mean=+0.0085476003
best_effective_breadth=1.1323823788
5m_xs_rev_rank_ic_mean=+0.0289588724 but post-cost sum=-20.6197925003
carry_sum_return_pct=-0.1147211
```

读法：这是 discovery baseline，不是 promotion。初扫支持“5m 成本主导”的判断：
5m `xs_rev` 有正 rank-IC/t-stat，但每 5m 换手后 post-cost 大幅为负；30 天内 CARRY
在当前朴素“方向翻转即付成本”的口径下也为负。唯一正的 top cell 是 `1d ts_mom`，但
rank-IC 很弱、有效广度约 1.13，下一步只能继续做更长 discovery 扫描和参数/成本口径
健壮性检查，不能进入 S2/S3 或 forward paper。

随后用 120 天 discovery 和成本/月份 sensitivity 复核，`1d ts_mom` 不稳定：

```text
120d_full_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T070504Z-strategy-selection-scan-qount-strategy-selection-s1-120d-full-lb12-h1-20260605/qount-strategy-selection-s1-120d-full-lb12-h1-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
best_cell=1d ts_mom
sum_return_pct=-0.3885499348
mean_return_pct=-0.0008027891
sharpe=-0.4637426827
rank_ic_mean=-0.0524746039
effective_breadth=1.0810517903

1d_lbp3_h1_best=xs_rev sum=-0.0652799064
1d_lb12_h3_best=ts_mom sum=+0.5824374867 sharpe=+0.4579358431
1d_lb24_h1_best=ts_mom sum=-0.0867584111
```

月度分段（`1d ts_mom lb12/h1`）：

```text
Feb sum=+0.1023244575 sharpe=+0.3227715436 ic=-0.0267942952
Mar sum=-0.4297008569 sharpe=-2.2922293236 ic=-0.2166041018
Apr sum=-0.4340789583 sharpe=-2.8870027003 ic=-0.1636003147
May sum=+0.3233152390 sharpe=+2.3098638880 ic=+0.0316906244
```

成本压力：

```text
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T070712Z-strategy-selection-scan-qount-strategy-selection-s1-120d-5m-xsrev-carry-zero-cost-20260605/qount-strategy-selection-s1-120d-5m-xsrev-carry-zero-cost-20260605.json
zero_cost_5m_xs_rev_sum=+1.2386542488
zero_cost_carry_sum=+0.0824606

maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T070835Z-strategy-selection-scan-qount-strategy-selection-s1-120d-5m-xsrev-carry-maker-ish-20260605/qount-strategy-selection-s1-120d-5m-xsrev-carry-maker-ish-20260605.json
maker_ish_cost_per_directional_bet=0.0004
maker_ish_5m_xs_rev_sum=-26.4101457512
maker_ish_carry_sum=-0.0999394
```

读法：30 天 `1d ts_mom` 正收益主要是 2026-05 单月趋势贡献，120 天和 2/3/4 月不支持
它作为稳定 S2/S3 入口。5m 和 CARRY 都有 gross edge，但很薄，maker-ish 成本后转负；
当前不能把任何 cell 提升为 S2/S3 或 S-CARRY。下一步应先改进 carry 真实双腿/阈值模型
和扩大 universe，而不是上 GBDT。

2026-06-05 已补 `strategy-selection-scan` OHLCV 列回归测试，锁定 ccxt 输入列必须保持
`[timestamp, open, high, low, close, volume]`，避免把 `low` 当 `close`。本地和 WSL
全量测试随后升级为 `227 OK`。用同一生产 WSL 环境复跑 120 天 S1'，核心结论不变：
`1d ts_mom` 仍是排序上的 best cell，但 `sum=-0.3885499348`、`sharpe=-0.4637426827`、
`rank_ic=-0.0524746039`，decision 为 `no_positive_cell`。zero-cost 下 5m `xs_rev`
`+1.2386542488`、CARRY `+0.0824606`；maker-ish
`cost_per_directional_bet=0.0004` 后分别为 `-26.4101457512`、`-0.0999394`。

2026-06-05 已推进 S-CARRY 第一刀：`strategy-selection-scan` 增加显式
`--carry-model threshold_dual_leg`，只在 research 命令使用，默认 `naive` 不变。该模型加入
funding entry/exit 阈值、最短持仓周期、双腿开/平/换腿成本。120 天 4 币复跑：
zero-cost 为 `+0.04728436`，maker-ish `cost_per_directional_bet=0.0004` 后为
`-0.16871564`，说明阈值过滤保留了部分 gross cashflow，但当前 4 币/阈值/成本下仍不能进
S-CARRY paper。

2026-06-05 继续推进 S-CARRY 固定 discovery 网格和资金占用读数：grid =
entry `0.00004/0.00008/0.00012` × exit `0.00002/0.00004` × min-hold `1/3/6`。
本地和 WSL 全量测试升级为 `228 OK`。120 天 4 币 zero-cost grid best 为
entry `0.00004` / exit `0.00002` / min-hold `1`，`sum=+0.07147182`，
`utilization=0.6715`，双腿平均 gross exposure `1.3431`。同一 grid maker-ish best 为
entry `0.00012` / exit `0.00002` / min-hold `6`，`sum=-0.02967449`，
`utilization=0.2708`，双腿平均 gross exposure `0.5417`。Binance funding history
当前没有返回可用 mark/index 历史，`basis_sample_count=0`；basis 风险仍需单独数据源。
结论：固定 grid 后仍不能 paper；成本是主要瓶颈，下一步应扩大 universe 和补 basis 数据，
不是在 4 币已看窗口上继续挑阈值。

2026-06-05 已补 CARRY basis 数据源第一版：`strategy-selection-scan` 增加显式
`--carry-basis-source premium_index`，通过 ccxt `fetch_premium_index_ohlcv` 拉 Binance
8h premium index kline，并按 funding 8h bucket 合并到 CARRY cell 的 basis 诊断字段。
本地和 WSL 全量测试升级为 `229 OK`。120 天 4 币 maker-ish fixed grid 复跑：
`premium_index_8h` 每币 361 根；best cell 仍为 entry `0.00012` / exit `0.00002` /
min-hold `6`，`sum=-0.02967449`、`utilization=0.2708`、双腿平均 gross exposure
`0.5417`；basis 诊断从 0 样本变成 `basis_sample_count=390`、
`basis_avg_abs=0.0005576725`、`basis_max_abs=0.00143783`。结论不变：basis 数据已接入，
但 4 币 maker-ish 成本后仍不能 S-CARRY paper。

2026-06-05 已按下一步扩大 CARRY universe 到 12 币：
`BTC/ETH/ZEC/SOL/HYPE/WLD/XRP/BNB/NEAR/DOGE/ADA/SUI` USDT perpetuals。120 天 top12
premium basis fixed grid 读数：

```text
maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083609Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605.json
maker_ish_best_entry=0.00012
maker_ish_best_exit=0.00002
maker_ish_best_min_hold=6
maker_ish_sum=-0.07594874
maker_ish_turnover_events=221
maker_ish_utilization=0.2816239316
maker_ish_avg_dual_leg_gross_exposure=0.5632478632
maker_ish_basis_sample_count=1318
maker_ish_basis_max_abs=0.00265777
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083859Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605/qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605.json
zero_cost_best_entry=0.00004
zero_cost_best_exit=0.00002
zero_cost_best_min_hold=1
zero_cost_sum=+0.27826189
zero_cost_turnover_events=2104
zero_cost_utilization=0.6970085470
zero_cost_avg_dual_leg_gross_exposure=1.3940170940
```

读法：扩币后 zero-cost gross funding cashflow 明显转强，说明 S-CARRY 仍是有效研究方向；
但 maker-ish `cost_per_directional_bet=0.0004` 后所有 grid cell 仍为负，best cell 只有 WLD
单币为正（`+0.03113714`），组合仍不能 paper。下一刀不应继续在同一 discovery grid 上挑参数，
而应做显式 hedge / spot-perp 双腿执行、post-only 成交率、资金占用和 basis 风险 replay。

2026-06-05 已补 explicit spot/perp 资金占用口径：`strategy-selection-scan` 增加显式
`--carry-execution-cost-model per_order`、`--carry-capital-model spot_perp_gross`、
`--carry-perp-margin-fraction`。默认仍是旧 `directional_round_trip + perp_notional`，所以旧
artifact 口径不变。本地和 WSL 全量测试升级为 `230 OK`。top12 同 grid 用 6x perp margin
fraction `0.1666667` 复跑：

```text
explicit_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605.json
execution_cost_model=per_order
capital_model=spot_perp_gross
perp_margin_fraction=0.1666667
order_cost=0.0002
best_entry=0.00012
best_exit=0.00002
best_min_hold=6
sum=+0.0106725083
sharpe=+0.7275658326
turnover_events=221
gross_funding_return=+0.0864439347
execution_cost_sum=+0.0757714264
cost_to_gross_ratio=0.8765383794
break_even_order_cost=0.0002281703
positive_cells=3/18
basis_max_abs=0.00265777
```

成本压力：同口径把 per-order cost 提到 `0.00025` 后，best cell 立即转负：

```text
cost025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085742Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605.json
order_cost=0.00025
best_sum=-0.0082703483
best_sharpe=-0.5083163356
break_even_order_cost=0.0002281703
```

读法：显式 spot/perp 口径把 S-CARRY 从“旧保守成本下全负”推进到“有一个小正候选”，但
成本缓冲只有约 `0.00002817` per order，且 `basis_max_abs=0.00265777` 明显大于净收益边际。
这仍不能 paper；下一步必须先做 post-only 成交率 / 实测订单成本 / basis tail 风险压力，
并用独立窗口验证，不能把这个 discovery best cell 当 promotion。

2026-06-05 已给 `strategy-selection-scan` 补显式 `--holdout-role`，并用已选定 top12
explicit spot/perp best cell 跑一个新的 1 天 `validation_v1` 固定窗口
`2026-06-04T00:00:00Z..2026-06-05T00:00:00Z`。这是固定参数检查，不重新 grid search。

```text
val_jun04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103552Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605.json
holdout_role=validation_v1
sample_count=51
order_cost=0.0002
sum=+0.0003597343
sharpe=+2.6637283960
turnover_events=4
gross_funding_return=+0.0017311628
execution_cost_sum=+0.0013714285
cost_to_gross_ratio=0.7922007833
break_even_order_cost=0.0002524613
basis_sample_count=14
basis_max_abs=0.00235832

val_jun04_cost025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103620Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605.json
order_cost=0.00025
sum=+0.0000168771
sharpe=+0.1072893774
cost_to_gross_ratio=0.9902509791
```

读法：独立窗口没有立即证伪 top12 CARRY best cell，但证据极薄：只有 51 条 funding 样本、
4 个 entry events，`order_cost=0.00025` 时几乎完全贴近 break-even，且 `basis_max_abs`
仍远大于净收益。它最多支持继续做 post-only / 实测成本 / basis-tail 验证，仍不能 paper。

随后复跑同一固定窗口，只新增 basis-tail 诊断字段，不改变 PnL 计算：

```text
val_jun04_basis_tail_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T104512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605.json
holdout_role=validation_v1
sample_count=51
order_cost=0.0002
sum=+0.0003597343
basis_max_abs=0.00235832
basis_single_tail_loss_on_capital=0.0020214171
basis_single_tail_to_net_ratio=5.6191951202
portfolio_sum_after_single_basis_tail=-0.0016616828
```

读法：1 天 fixed-cell 的小正收益会被同窗口观察到的一次 basis tail 压力直接抹掉并转负，
tail/net 比例约 `5.62x`。这把 S-CARRY 当前状态从“需要 basis-tail 验证”推进为
“basis-tail 已经证伪当前 paper 资格”。下一刀不能 promotion，只能先做 post-only fill /
真实订单成本和 basis-tail-aware hedge / exit 模型。

2026-06-05 继续补了显式 `--carry-basis-tail-stop-pct`，只在 research scan 中启用；默认
`None`，历史 artifact 口径不变。本地和 WSL 全量测试升级为 `231 OK`。同一 1 天
`validation_v1` fixed-cell 跑三个 simple basis stop：

```text
stop001_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105545Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605.json
stop=0.0010
sum=-0.0008075743
basis_tail_stop_events=2
basis_max_abs=0.00081857
after_single_basis_tail=-0.0015092057

stop0015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105616Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605.json
stop=0.0015
sum=-0.0004218600
basis_tail_stop_events=1
basis_max_abs=0.00112691
after_single_basis_tail=-0.0013877828

stop0020_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105622Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605.json
stop=0.0020
sum=-0.0004218600
basis_tail_stop_events=1
basis_max_abs=0.00112691
after_single_basis_tail=-0.0013877828
```

读法：simple basis stop 能降低持仓期最大 basis 暴露，但新增退出成本和少收 funding 后，
三个阈值都把 fixed-cell 从小正变成负收益。当前不能靠单一 hard stop 解决 S-CARRY；
下一步只能继续做 post-only fill / 实测订单成本，或更细的 symbol/filter 与 hedge timing，
不能 paper。

2026-06-05 继续做只读成本和 symbol/filter 复核。`execution-cost-audit --limit 200`
只找到 4 笔历史 live 市价单可分析，fee 缺失；实际 abs slippage 中位约 `0.0441%`，
高于 S-CARRY fixed-cell 假设的 `0.0200%` per-order。按 120 天 discovery 逐币贡献，
只有 `WLD/SOL/ZEC` 为正，其中 ZEC 的 discovery after-tail 已为负；tail-aware 过滤后
只保留 `WLD/SOL`：

```text
wld_sol_discovery_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110031Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
sum=+0.0378574446
after_single_basis_tail=+0.0355793561
break_even_order_cost=0.0006330100

wld_sol_val_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T110033Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
sum=+0.0000535886
after_single_basis_tail=-0.0006480428
break_even_order_cost=0.0002312600

wld_sol_val_cost025=/home/alyaloale/Code/qount/state/research_runs/20260605T110109Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605.json
order_cost=0.00025
sum=-0.0000321257

wld_sol_val_cost045=/home/alyaloale/Code/qount/state/research_runs/20260605T110114Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605.json
order_cost=0.00045
sum=-0.0003749828
```

读法：WLD/SOL 是当前最像样的 S-CARRY filter 方向，120 天 discovery 在成本和 after-tail
上都更健康；但 1 天 sanity 只有 SOL 成交，after-tail 仍为负，且成本 `0.00025` 就转负。
历史 live slippage 样本还提示真实 taker 成本可能更高。结论仍是不 paper；下一刀应先证明
post-only / maker fill 能把 per-order 成本压到 `0.000231` 以下，或继续找更多独立日期验证
WLD/SOL 是否稳定，而不是扩大到 live。

同日继续拆 WLD/SOL 的 discovery 月度稳定性和 6 月逐日读数，全部不作为 promotion：

```text
wld_sol_feb=/home/alyaloale/Code/qount/state/research_runs/20260605T111620Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-feb-20260605/qount-strategy-selection-s-carry-wld-sol-feb-20260605.json
sum=+0.0040478056
after_tail=+0.0028153799

wld_sol_mar=/home/alyaloale/Code/qount/state/research_runs/20260605T111622Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-mar-20260605/qount-strategy-selection-s-carry-wld-sol-mar-20260605.json
sum=+0.0028695942
after_tail=+0.0017230457

wld_sol_apr=/home/alyaloale/Code/qount/state/research_runs/20260605T111625Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-apr-20260605/qount-strategy-selection-s-carry-wld-sol-apr-20260605.json
sum=+0.0190945623
after_tail=+0.0168164738

wld_sol_may=/home/alyaloale/Code/qount/state/research_runs/20260605T111627Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-may-20260605/qount-strategy-selection-s-carry-wld-sol-may-20260605.json
sum=+0.0119759397
after_tail=+0.0104161540

wld_sol_jun01_04=/home/alyaloale/Code/qount/state/research_runs/20260605T111629Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605.json
holdout_role=discovery
sum=+0.0003015686
after_tail=-0.0004000628

wld_sol_jun05_partial=/home/alyaloale/Code/qount/state/research_runs/20260605T111654Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605.json
holdout_role=unknown
sample_count=4
sum=-0.0002471743
after_tail=-0.0003076628
```

读法：WLD/SOL 在 2-5 月 discovery 每月 after-tail 都为正，但 4/5 月主要靠 WLD；6/1-6/4
已看窗口 after-tail 转负，6/5 partial 也为负且样本太少。这个 filter 仍值得观察，但现在的
真实下一步是等待新的完整独立日期，或先解决 maker/post-only 成本；不能继续拿 6/1-6/5
调参后声称 validation。

用户明确要求“不等完整独立日期”后，继续推进 maker/post-only 成本证明。2026-06-05 已补
research-only post-only economics 诊断：`--carry-maker-order-cost-pct` /
`--carry-taker-order-cost-pct` 只计算所需 maker fill rate，不改变 PnL。本地和 WSL 全量测试
升级为 `232 OK`。用 maker cost `0`、taker cost `0.00045`（接近历史 live 市价单 slippage
中位）跑 WLD/SOL：

```text
wld_sol_discovery_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113704Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605.json
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
after_tail=+0.0355793561
required_maker_fill_after_tail=0.0
after_tail_feasible=true

wld_sol_jun01_04_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113706Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605.json
window=2026-06-01T00:00:00Z..2026-06-05T00:00:00Z
after_tail=-0.0004000628
required_maker_fill_after_tail=1.0741555556
after_tail_feasible=false

wld_sol_jun05_partial_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113709Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605.json
holdout_role=unknown
after_tail=-0.0007569857
required_maker_fill_after_tail=1.0461944444
after_tail_feasible=false
```

读法：maker/post-only 能解释 120 天 discovery 的成本可行性，但不能拯救 6/1-6/5 的
after-tail 亏损；已看窗口 after-tail 为正需要超过 100% maker fill，数学上不可行。下一步
不应继续成本调参，而应进入更细的 hedge timing / basis regime filter，或转向次优路线
1d TS-MOM 扩 universe。

同日继续按下一步做 WLD/SOL basis regime filter。`strategy-selection-scan` 新增显式
research-only `--carry-basis-entry-max-abs-pct`，只在 CARRY 新入场时阻止 basis 已经偏离
过大的交易，默认关闭，不影响 live / `run-once`。本地和 WSL 全量测试升级为 `233 OK`。
用 WLD/SOL fixed cell 跑三个 entry basis 阈值：

```text
basis_entry_max_abs=0.0008
discovery120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114908Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00008-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00008-20260605.json
discovery120d_sum=-0.0066684341
discovery120d_after_tail=-0.0083560026
discovery120d_blocked_entries=19
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114911Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00008-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00008-20260605.json
jun01_04_sum=-0.0003841457
jun01_04_after_tail=-0.0010857771
jun01_04_required_maker_after_tail=1.0741555556

basis_entry_max_abs=0.0010
discovery120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114914Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00010-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00010-20260605.json
discovery120d_sum=-0.0010824000
discovery120d_after_tail=-0.0028620256
discovery120d_blocked_entries=8
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114917Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00010-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00010-20260605.json
jun01_04_sum=-0.0003841457
jun01_04_after_tail=-0.0010857771
jun01_04_required_maker_after_tail=1.0741555556

basis_entry_max_abs=0.0015
discovery120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114920Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00015-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-discovery120d-b00015-20260605.json
discovery120d_sum=+0.0020099742
discovery120d_after_tail=+0.0002303486
discovery120d_blocked_entries=2
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114922Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00015-20260605/qount-strategy-selection-s-carry-wld-sol-basis-entry-jun01_04-b00015-20260605.json
jun01_04_sum=-0.0003841457
jun01_04_after_tail=-0.0010857771
jun01_04_required_maker_after_tail=1.0741555556
```

读法：entry-only basis filter 不能救 WLD/SOL。0.0008 / 0.0010 在 120 天 discovery 上已转负；
0.0015 只剩极薄正收益，而且 6/1-6/5 已看窗口完全不改善，after-tail 仍负且需要超过 100%
maker fill。这个 filter 只能保留为 rejected/diagnostic，不进入 paper。

随后转向备选路线：扩大 `1d ts_mom` universe 到同一 top12。结果比 4 币更差：

```text
top12_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T114959Z-strategy-selection-scan-qount-strategy-selection-s1-tsmom-top12-120d-20260605/qount-strategy-selection-s1-tsmom-top12-120d-20260605.json
symbols=12
window=2026-02-01T00:00:00Z..2026-06-01T00:00:00Z
sum=-2.6698947371
mean=-0.0018387705
sharpe=-0.7852540386
rank_ic=-0.0517447570
effective_breadth=1.4732977614

feb_sum=-0.9962962887 sharpe=-0.9621629776 ic=-0.0674655117
mar_sum=-1.0361457305 sharpe=-1.3703927744 ic=-0.1333032818
apr_sum=-1.2542758681 sharpe=-1.9515156302 ic=-0.1175958164
may_sum=+0.7414512205 sharpe=+0.7641721588 ic=+0.0031381398
```

读法：top12 扩币没有给 `1d ts_mom` 提供稳定候选；2/3/4 月全负，5 月单月正但 IC 接近 0。
这条线不能进 S1.1/S1.2，更不能 paper。当前可行动方向缩到两类：等新的完整独立日期复核
WLD/SOL carry 是否恢复，或离开当前 S-CARRY/TS-MOM 两条 discovery best，重新做更宽的
strategy-family / universe / 执行约束设计。

同日继续把 S1' 扩成多 horizon 网格。`strategy-selection-scan` 新增
`--signal-lookback-grid-bars` / `--holding-grid-bars`，只影响 research scan 的预测族 cell
展开，默认行为不变。本地和 WSL 全量测试升级为 `235 OK`。低频 top12 网格：
`1h/4h/1d` × `xs_mom/xs_rev/ts_mom` × lookback `3/12/24` × holding `1/3/6`，120 天
discovery 读数如下：

```text
lowfreq_grid_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121551Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605/qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605.json
cell_count=81
best_cell=4h xs_mom lookback=24 holding=6
sum=+3.5251307739
mean=+0.0048892244
sharpe=+7.1555415974
rank_ic=+0.0523457125
turnover_events=4326
sample_count=8652

top2=4h xs_mom lookback=12 holding=6 sum=+3.2301871618 sharpe=+7.0705584839 ic=+0.0449501019
top3=1d xs_mom lookback=24 holding=6 sum=+2.9144790792 sharpe=+5.3167601423 ic=+0.0376682141
```

固定 best cell 月度 sanity：

```text
feb_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121631Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-feb-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-feb-20260605.json
feb_sum=+0.0054374620 sharpe=+0.0534812097 ic=-0.0258203335
mar_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121636Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-mar-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-mar-20260605.json
mar_sum=-0.3056398179 sharpe=-2.9328919686 ic=-0.0228488089
apr_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121640Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-apr-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-apr-20260605.json
apr_sum=+0.9769441561 sharpe=+11.6825529071 ic=+0.0950044431
may_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121645Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-may-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-may-20260605.json
may_sum=+2.8938136721 sharpe=+16.4429358388 ic=+0.1603904117
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121653Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-jun01_04-20260605.json
jun01_04_sum=+0.2839507666 sharpe=+6.4057144483 ic=+0.1217418945
```

Top-fraction sensitivity（同一 fixed cell，120 天 discovery）：

```text
top010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121834Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-top010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-top010-20260605.json
top_fraction=0.10 sum=+5.4599023538 sharpe=+5.9026198051 turnover=1442
top025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121839Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-top025-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-top025-20260605.json
top_fraction=0.25 sum=+3.5251307739 sharpe=+7.1555415974 turnover=4326
top050_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T121846Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-top050-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-top050-20260605.json
top_fraction=0.50 sum=+1.3829792744 sharpe=+4.5968178554 turnover=8652
```

随后补 overlap sanity：`strategy-selection-scan` 增加显式
`--directional-overlap-mode all|stride`，默认 `all` 保持旧读数；`stride` 每个 holding
window 只取一次 cross-section，先降低 `holding=6` 的重叠 horizon 膨胀。本地和 WSL 全量测试
均为 `236 OK`。同一 fixed best 的 stride 读数：

```text
stride_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T123357Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605.json
stride_120d_sum=+0.5087944384
stride_120d_sharpe=+6.0811826595
stride_120d_rank_ic=+0.0607409120
stride_120d_cross_sections=121
stride_feb_sum=-0.0026969105 sharpe=-0.1324295271 ic=-0.0195321919
stride_mar_sum=-0.0234895413 sharpe=-1.1990799524 ic=-0.0039335664
stride_apr_sum=+0.0796046219 sharpe=+6.1468061927 ic=+0.1037672005
stride_may_sum=+0.5008009667 sharpe=+17.4927001500 ic=+0.1761363636
stride_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T123424Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605.json
stride_jun01_04_sum=+0.0627083513
stride_jun01_04_sharpe=+6.9612473463
stride_jun01_04_cross_sections=4
```

随后补第一版限仓 portfolio replay：`--directional-evaluation-mode portfolio_replay`，
`--directional-max-open-positions 12`，同一 fixed best、top12 universe、4h、lb24/h6、
top_fraction `0.25`，仍为 research-only。本地和 WSL 全量测试均为 `236 OK`。

```text
portfolio_replay_120d_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T125713Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605.json
portfolio_replay_120d_sum=+0.2974912983
portfolio_replay_120d_sharpe=+7.1945433715
portfolio_replay_120d_max_dd=0.0876673733
portfolio_replay_120d_trades=1446
portfolio_replay_120d_skipped=2880
portfolio_replay_120d_win_rate=0.4951590595
portfolio_replay_feb_sum=+0.0062629159 sharpe=+0.6960748519
portfolio_replay_mar_sum=-0.0094161679 sharpe=-1.0453679061
portfolio_replay_apr_sum=+0.0656249961 sharpe=+9.4341419585
portfolio_replay_may_sum=+0.2463757288 sharpe=+16.7819812990
portfolio_replay_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T125741Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605.json
portfolio_replay_jun01_04_sum=+0.0082009038
portfolio_replay_jun01_04_sharpe=+2.2971433970
```

读法：这是今天第一个像样的 prediction-family candidate。它在 stride sanity 和限仓
portfolio replay 下都保持 120 天聚合正收益，说明不是纯重叠 horizon 幻觉；但 2026-03
月度 replay 仍为负，2 月也只是微正，`jun01_04` 只是已看窗口 sanity，不能当 promotion。
继续补 triple-barrier：`--directional-exit-mode triple_barrier` 使用 holding window 内 OHLC
高低点触发 TP/SL，默认 `close` 不变。固定同一 top12 / 4h / lb24/h6 /
portfolio_replay / max_open_positions `12`，120 天扫 4 个简单 TP/SL 组合：

```text
triple_tp015_sl010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132052Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.015-sl0.010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.015-sl0.010-20260605.json
triple_tp015_sl010_sum=-0.2542260860 sharpe=-21.9420203800
triple_tp020_sl010_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132057Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.010-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.020-sl0.010-20260605.json
triple_tp020_sl010_sum=-0.2307013696 sharpe=-16.8127315231
triple_tp020_sl015_sum=-0.2296270771 sharpe=-14.6592774682
triple_tp030_sl015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132109Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605.json
triple_tp030_sl015_sum=-0.1635040433 sharpe=-8.7264450618
```

用最不差的 TP `0.030` / SL `0.015` 做月度拆分：

```text
triple_exit_reason_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132953Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605.json
triple_120d_exit_counts=stop_loss 873, take_profit 400, time 173
triple_120d_win_rate=0.3443983402
triple_feb_sum=-0.0356452182 sharpe=-7.8031867350
triple_feb_exit_counts=stop_loss 224, take_profit 110, time 8
triple_mar_sum=-0.0631122398 sharpe=-12.6468869769
triple_mar_exit_counts=stop_loss 242, take_profit 107, time 29
triple_apr_sum=-0.0812657295 sharpe=-17.4805448327
triple_apr_exit_counts=stop_loss 211, take_profit 73, time 82
triple_may_sum=+0.0203985601 sharpe=+4.3481178441
triple_may_exit_counts=stop_loss 205, take_profit 116, time 57
triple_jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132208Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605.json
triple_jun01_04_sum=+0.0177000000
```

读法：`4h xs_mom` 不是纯重叠 horizon 幻觉，但简单 fixed TP/SL triple-barrier 已经否定当前
paper 资格：120 天四个 barrier 组合全负，最不差组合也只有 5 月和已看 6 月为正，2/3/4 月
全负。原因不是 rank-IC 完全消失，而是固定 barrier 的路径执行失败：120 天 stop-loss 触发
`873` 次、take-profit `400` 次、到期 `173` 次，止损约为止盈 `2.18x`，再叠加 per-trade
成本后把 close-to-close/replay 正收益吃掉。当前下一步只能做 purged-CV / exit 设计 / 新
OOS，不能 paper，也不要继续盲扫简单 TP/SL。

随后补 fixed-cell purged/embargo CV 诊断：`strategy-selection-scan` 新增显式
research-only `--directional-purged-cv-folds` / `--directional-embargo-bars`，默认关闭，
不影响 live / `run-once` / CARRY。固定 top12、`4h xs_mom`、lookback `24`、holding `6`、
`portfolio_replay`、`max_open_positions=12`、close exit，4 fold + 6 bars embargo：

```text
purged_cv_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T133904Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605.json
full_sum=+0.2974912983
full_sharpe=+7.1945433715
positive_folds=3/4
mean_fold_sum=+0.0743728246
min_fold_sum=-0.0566596009
fold1_2026-02-01_to_2026-03-02=+0.0467298450
fold2_2026-03-03_to_2026-04-01=-0.0566596009
fold3_2026-04-02_to_2026-05-01=+0.0611460588
fold4_2026-05-02_to_2026-06-01=+0.2462749954
```

读法：purged/embargo artifact 已能机器化记录 fold 稳定性，但仍未过 paper 前置。
3/4 folds 为正说明 candidate 仍值得研究；`2026-03-03..2026-04-01` fold 为负且 IC 为负，
说明收益仍明显依赖后段行情。下一步不再重复 close/replay/purged sanity，而是做更稳健的
exit 设计、模型层 purged-CV，或等待新的完整 OOS 日期。

2026-06-05 已按 §11.5 N1 做"波动率缩放 barrier"(simple fixed TP/SL 已证不行,不再重复)：
`strategy-selection-scan` 新增 research-only `--directional-barrier-vol-lookback-bars` /
`--directional-take-profit-sigma` / `--directional-stop-loss-sigma`，把 triple-barrier 的
TP/SL 从固定百分比改为按"决策时点近 N 根 bar 已实现收益 σ"缩放，默认关闭、live /
`run-once` / CARRY 不变。本地和 WSL 全量测试升级为 `240 OK`。固定同一 `4h xs_mom lb24/h6`、
top12、portfolio_replay、`max_open=12`、vol lookback `24`、120 天 discovery，扫 σ 倍率：

```text
artifact_dir=/home/alyaloale/Code/qount/state/research_runs/20260605T1410*-...-volbarrier-*-120d-20260605
close_exit_baseline_sum=+0.2974912983 (无 barrier，既有 replay 读数)
tp1.5/sl1.5 sum=-0.143287 sharpe=-5.9154 SL=643 TP=635 TIME=168
tp2.0/sl2.0 sum=-0.050339 sharpe=-1.8044 SL=514 TP=544 TIME=388
tp3.0/sl2.0 sum=+0.037766 sharpe=+1.2470 SL=539 TP=339 TIME=568
tp3.0/sl3.0 sum=+0.118739 sharpe=+3.8430 SL=303 TP=360 TIME=783
tp4.0/sl4.0 sum=+0.165134 sharpe=+4.7454 SL=192 TP=222 TIME=1032
```

最佳 `tp4.0/sl4.0` 月度（同 fixed cell，每月独立窗口）：

```text
feb_sum=+0.034363 sharpe=+4.3075 ic=-0.02582
mar_sum=-0.039638 sharpe=-4.7000 ic=-0.02285
apr_sum=+0.032380 sharpe=+5.2807 ic=+0.09500
may_sum=+0.149386 sharpe=+12.8808 ic=+0.16039
```

读法：vol-scaling 确实改掉了 fixed barrier 的非对称止损病(fixed `tp0.030/sl0.015` 是
stop-loss `873` / take-profit `400`，约 `2.18x`；vol `tp2/sl2` 已收敛到 `514/544` 接近 1:1)，
且 PnL 随 barrier 加宽单调改善。但**没有任何 σ 设置能跑赢"无 barrier 持有到期"的 close-exit
基线 `+0.2974912983`**：barrier 越宽，越多仓位以 `time` 退出、越接近 close 基线，最佳
`tp4/sl4` 也只有 `+0.165134`，仍低于 close。月度上最佳 barrier 的 3 月仍为负、约 90% 收益
来自 5 月单月，单月依赖未改善，且全部是已看过的 120 天 discovery。结论：N1 门控未通过——
可执行 path-dependent exit 仍未跑赢持有，且无月度稳健性;**不进 S2**。下一刀只能等新的完整
独立 OOS 日期复核，或做更细的持仓管理(部分止盈/移动止损/regime 过滤),不能 paper。

2026-06-05 继续按 N1 做 entry 侧 **regime dispersion 门**(part/移动止损本质仍是已被证伪的
路径 exit,故选未被排除的 entry 过滤):`strategy-selection-scan` 新增 research-only
`--directional-regime-min-dispersion-pct`，在每个 cross-section 上计算各币 signal 的离散度
(sample std,纯决策时点),低于阈值就跳过该 bar(同涨同跌、无相对强弱 = 不下注)。默认关闭,
live / `run-once` / CARRY / ts_mom 不变。本地和 WSL 全量测试升级为 `241 OK`。该候选 120 天
每根 bar 的 dispersion 分布 p25/p50/p75 = `0.034/0.048/0.068`。固定同一 `4h xs_mom lb24/h6`、
top12、close-exit、portfolio_replay、`max_open=12`，120 天 discovery 扫阈值：

```text
thr0.000 sum=+0.297491 sharpe=+7.1945 dd=0.0877 gated=0   traded=721 win=0.4952
thr0.034 sum=+0.298812 sharpe=+7.9989 dd=0.0798 gated=178 traded=543 win=0.5119
thr0.048 sum=+0.272640 sharpe=+8.9771 dd=0.1021 gated=356 traded=365 win=0.4940
thr0.068 sum=+0.195078 sharpe=+11.8154 dd=0.0527 gated=539 traded=182 win=0.4953
```

`thr0.034`(跳过最低 ~25% dispersion bar)月度，对比无过滤 close-exit 基线：

```text
feb_sum=+0.024688 ic=-0.00846  (baseline +0.0063)
mar_sum=+0.002786 ic=-0.00387  (baseline -0.0094 → 翻正)
apr_sum=+0.063078 ic=+0.10121
may_sum=+0.246376 ic=+0.16039
```

读法：这是 N1 里第一个**在正确的轴上**改善候选的子步骤。`thr0.034` 总收益不变
(`+0.298812` vs `+0.297491`)、Sharpe `7.19→8.00`、回撤 `0.088→0.080`、换手更少,而且把
**2026-03 从负翻正**、4 个月全部 ≥ 0——直接打到"月度全靠单月"的门控失败点。`thr0.068`
过滤太狠,2/3 月又转负。但仍有两条硬保留:(1) 阈值是在同一 120 天窗口的 dispersion 分布上
选的(p25),属 in-sample 阈值选择,有轻微过拟合风险;(2) 5 月仍占约 82% 收益,只是不再有
负月。且全部是已看 discovery。结论:候选现在处于明显更好的状态,但 N1 门控仍未通过(无新
完整 OOS、仍偏单月),**仍不进 S2**;下一刀就是把这个 `thr0.034` 固定参数留到下一个完整
`validation_v1` 独立窗口 once-only 复核。

2026-06-05 已按计划 §5 / §9.x 给 `strategy-selection-scan` 补 **Deflated Sharpe Ratio (DSR)**
多重检验惩罚(新增 `compute_directional_deflated_sharpe`,scan 顶层输出
`directional_deflated_sharpe`;López de Prado 口径,正态简化,research-only diagnostic)。本地和
WSL 全量测试升级为 `243 OK`。在**选出该候选的那张 81-cell 低频网格**
(`1h/4h/1d × xs_mom/xs_rev/ts_mom × lb3/12/24 × h1/3/6`、top12、120 天 discovery)上读 DSR：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T143817Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-dsr-120d-20260605/qount-strategy-selection-s1-lowfreq-top12-dsr-120d-20260605.json
trial_count=81
best_by_per_period_sharpe=1d xs_mom lb24/h6
best_per_period_sharpe=0.27825601
expected_max_per_period_sharpe=0.40655144   # 81 次噪声下的期望最大 Sharpe
trial_per_period_sharpe_variance=0.02741146
best_period_count=119
deflated_sharpe_ratio=0.08171240
assumes_normal_returns=true
```

读法：这是迄今最重要的反过拟合读数。**观测到的最佳 per-period Sharpe `0.278` 比 81 次随机
试验下噪声的期望最大值 `0.407` 还低,DSR ≈ `0.082`**(通常要求 > 0.95)。也就是说,在选出
候选的那张网格上,最佳 cell 的 Sharpe 在统计上与"81 次噪声里挑最大"不可区分;而且这还用了
正态假设(对肥尾会高估 DSR),真实 DSR 只会更低。这把结论从"候选还需新 OOS"收紧为
"**候选的网格内选择优势本身大概率是多重检验假象**"。S2 门控据此加硬:即便将来某个完整新
OOS 上 `thr0.034` 仍正,也必须同时给出可接受的 DSR/PBO 才能进 S2;否则按 §7 全局退出条件
诚实退出。当前**仍不进 S2**。

2026-06-05 又按 §5/§9.x 补 **PBO / CSCV**(Probability of Backtest Overfitting,Bailey &
López de Prado;新增 `compute_directional_pbo`,scan 顶层输出 `directional_pbo`,按频段分组
做 combinatorial symmetric CV,research-only diagnostic)。同一 81-cell 网格读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T150603Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-dsr-pbo-120d-20260605/qount-strategy-selection-s1-lowfreq-top12-dsr-pbo-120d-20260605.json
block_count=10  combos=252  (每频段 27 个 config)
pbo_1h=0.0556  median_logit=1.9042
pbo_4h=0.0198  median_logit=2.8332
pbo_1d=0.2143  median_logit=1.9042   (primary：DSR 最佳 per-period Sharpe 所在频段)
```

读法：DSR 与 PBO 互补、且不矛盾。**DSR** 问"绝对 Sharpe 量级在 N 次试验通缩后是否显著"
→ 否(`0.082`);**PBO** 问"IS 最佳 config 在 OOS 是否仍排名靠前"→ 大体是(PBO 全部 < 0.5、
median_logit > 0)。合起来的诚实图景:存在一个**弱但排名稳定**的横截面动量结构(不是纯随机
→ PBO 低),但其**量级太弱**(DSR ≈ 0.08),在多重检验 + 成本 + 路径执行后不足以确认盈利。
两个指标都指向同一决策:**不进 S2**。一条诚实保留:同频段 27 个 config 高度相关(同族、
重叠 lookback),会让 CSCV 的排名稳定性虚高、PBO 偏低,所以低 PBO 不能解读为"低过拟合风险",
只能解读为"赢家不是每次随机换人"。决策仍以 DSR + 等新 OOS 为准。

最新盈利导向改动是一个窄 blocker：`eth_short_range_noise_terminal_washout`。它只拦
ETH fresh `sell` + `range_noise` + higher trend/short，且同时满足
`return_24bars <= -1.0%`、`rsi_14 <= 32`、`sma_fast_ratio <= -0.8%`、
`sma_slow_ratio <= -0.8%`、`volume_ratio_20 >= 1.5`、`range_pct >= 0.8%` 的
terminal washout。该 reason 已加入 `HARD_BOTTOM_LINE_REASONS`，`bottom_line` 不能覆盖。

在已失败的 2026-06-01..2026-06-03 validation 窗口上降级为 discovery 复测后：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T135759Z-walk-forward-qount-wf-eth-terminal-washout-block-discovery-20260604
holdout_role=discovery
positive_realized_windows=1/2
paper_filled=4
paper_closed=5
sum_realized_return_pct=+0.9173089048%
avg_realized_return_pct=+0.4586544524%
windows_with_open_positions=0
total_review_missed_candidate_move=2
disc-jun01=-0.1510033978%
disc-jun02=+1.0683123026%
```

读法：这是有价值的盈利方向证据，说明 6/2 bad trade 被有效挡住；但这些窗口已经被看过，
只能作为 discovery，不能作为 promotion。

随后在新的 once-only validation 窗口 2026-06-03..2026-06-04 上第一次复测同一 blocker：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T141045Z-walk-forward-qount-wf-eth-terminal-washout-block-val-jun03-20260604
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
```

读法：这份 artifact 不能当策略结论；run 46 起 AI 返回 `auth_unavailable`，导致
`halted=true` 和 open position remaining。

AI relay 恢复后，同策略、同窗口做 infra rerun：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T145900Z-walk-forward-qount-wf-eth-terminal-washout-block-val-jun03-infra-rerun-20260604
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

读法：有效复跑没有遗留仓位，所以主问题不是 exit cleanup，而是 6/3 后半段 repeated
`range_noise` short 质量差。6 笔 short 只有 1 笔盈利；后两笔亏损是更明显的 oversold
terminal washout，但当前 blocker 因 `range_pct >= 0.008` 和 `sma_fast <= -0.008`
仍漏掉。这个窗口已经看过，后续只能作为 discovery 设计下一条 blocker，不能作为 promotion。

第一次 `validation_v1` once-only walk-forward 使用 `gpt-5.5`、主线 v1 setup model：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T134036Z-walk-forward-qount-wf-eth-validation-v1-v1-20260604
windows=val-jun01 2026-06-01T00:00:00Z..2026-06-02T00:00:00Z
        val-jun02 2026-06-02T00:00:00Z..2026-06-03T00:00:00Z
holdout_role=validation_v1
oos_safe_windows=2
positive_realized_windows=0/2
paper_filled=7
sum_realized_return_pct=-0.7159862916%
total_review_missed_candidate_move=2
windows_with_open_positions=0
```

读法：

- 这批 validation 样本不满足 `G_paper`：`sum_realized_return_pct` 为负，
  `positive_realized_windows=0/2`，且存在 `missed_candidate_move=2`。
- actionable review 为负：`val-jun01 avg_net_edge=-0.0676%`，`val-jun02 avg_net_edge=-0.0558%`。
- `eth_trend_impulse_range_noise_range_gt012` / `washout` 在 `val-jun02` 是 bad trade，
  不能把这类 range-noise 旧 discovery tag 提升为 gate。
- `eth_trend_impulse_short_breakdown_chase` 在 `val-jun02` 有 2 个 missed candidate move，
  但整体 review 不支持靠放宽短线开仓来修复；这两个窗口已用作 validation，不再用于调参后复验。

最新有效 13-window chronological walk-forward 使用 `gpt-5.5`：

```text
sum_realized_return_pct=+1.6184470183%
positive_realized_windows=2/13
paper_filled=4
```

全部正收益集中在：

```text
wf-mar06  +1.5617%
wf-apr15  +0.0567%
```

读法：

- 有历史盈利样本，但 alpha 极稀疏。
- 946 cycles 只产生 4 笔 fresh open，分布在不超过 2 个窗口。
- 旧 G1/G2 以窗口数为核心，在当前成交密度下数学上不可达。
- [holdout.md](holdout.md) 已把已看过窗口冻结为 `discovery_pool`，新 gate 改为
  `G_paper` / `G_live`。

## WS-1..WS-4 结论

- WS-1 h12 + loose trailing：`wf-mar06` realized 只有 `+0.5828756239%`，低于 h6
  基线 `+1.5617328164%`，且留下 1 个 open position；不继续。
- WS-2 maker/min-edge：maker fee 只能小幅改善离线边际；提高 min-edge 会砍掉
  `wf-apr15` 正收益或直接变成 0 交易；不继续。
- WS-3 集合根扫描：`state/research_runs` 集合仍 `ready_tags=[]`；不写 gate。
- WS-4 `multi_range_action_pullback_sma_fast_gt008`：离线 h3/h6/h12 有 edge，但 step 3
  两个窗口 24/24 AI 全 hold，0 成交；不进 gate。
- WS-4 `range_return24_gt012`：样本少，h3/h12 为负；不 ready。
- WS-4 `eth_reclaim_long_*`：h3/h6/h12/h24 整体负或样本不足；不 ready。
- 2026-05-30 新 OOS 仍 0 成交，`ready_tags=[]`。

## T-B hold-bias 读数

2026-05-31 已完成第一步工具化：`ai-hold-baseline` 能按 research profile / symbol
过滤历史 artifact 中的 fresh-entry prompt 样本，并把结果持久化到
`state/research_runs`。

WSL 读数：

- multi-symbol WS-4 fast-SMA 两个 step3 窗口：`sample_count=24`，既有 AI 决策
  `hold=24/24`。artifact：
  `/home/alyaloale/Code/qount/state/research_runs/20260531T064411Z-ai-hold-baseline-qount-ai-hold-multi-fast-sma-dryrun-20260531/qount-ai-hold-multi-fast-sma-dryrun-20260531.json`
- eth-only profile 同一 tag 只取 ETH 样本：`sample_count=2`，确认 profile/symbol
  过滤已生效。artifact：
  `/home/alyaloale/Code/qount/state/research_runs/20260531T064410Z-ai-hold-baseline-qount-ai-hold-ethonly-symbol-filter-20260531/qount-ai-hold-ethonly-symbol-filter-20260531.json`
- eth-only `v3_veto_only` smoke：`repeat=1`、`sample_count=2`、`request_count=2`，
  结果仍是 `hold=2/2`。artifact：
  `/home/alyaloale/Code/qount/state/research_runs/20260531T064502Z-ai-hold-baseline-qount-ai-hold-ethonly-v3-smoke-20260531/qount-ai-hold-ethonly-v3-smoke-20260531.json`

读法：T-B 现在有可复现的 hold-bias 诊断入口；但小样本 v3 smoke 没有解锁开仓，
且 AI 给出的 hold 理由是具体 veto（SMA/24bar 冲突、负 expected_edge、反向 rebound 或
过热），不能把 prompt v3 当成 promotion 证据。

## T-G idle-window 读数

2026-05-31 已完成 `idle-window-diagnostic`，并修正全局 reason aggregate：窗口输出仍受
`--reason-limit` 限制，但 aggregate 使用未截断计数。WSL artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260531T072108Z-idle-window-diagnostic-qount-idle-window-diagnostic-ethonly-20260531-v2/qount-idle-window-diagnostic-ethonly-20260531-v2.json
```

关键读数：

```text
backtest_count=39
idle_window_count=36
skipped_traded_window_count=3
candidate_filter_hold_count=2878
ai_hold_count=87
selected_or_candidate_like_scored_count=890
positive_top_candidate_avg_future_edge_windows=5/36
```

setup model quality 分布：

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
```

读法：当前 ETH-only 0 交易窗口主要被 research/candidate/market-quality 约束拦住；
不是 setup_model 看见大量 strong favorable alpha 后被 AI 或 risk 系统性压掉。
36 个 idle 窗里只有 5 个窗口的 top candidate 均值 future edge 为正，且主要来自已看过
WS-4 fast-SMA / wf-mar11 / wf-may06 discovery 窗口；不能据此加 gate。

## T-C setup_model v2 读数

2026-05-31 已完成第一版 `v2_interactions` 训练/评分 plumbing：

- v1 默认不变。
- `--setup-model-version v2_interactions` 只在研究训练 / walk-forward 显式使用。
- v2 在 16 维 v1 基础上增加 higher-timeframe phase × bin 交互特征。
- 新增 `setup-model-compare`，只做离线 chronological split，不调用 AI、不执行订单。

WSL ETH-only 默认相位读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T075127Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-20260531/qount-setup-model-compare-ethonly-v2-20260531.json
example_count=705
eval_example_count=212
v1_top_decile_avg_target_edge_pct=-0.0011523934
v2_top_decile_avg_target_edge_pct=-0.0013773666
v2_minus_v1_top_decile=-0.0002249732
v2_minus_v1_mae=+0.0000124423
```

包含 `range_noise` 的读数：

```text
artifact=/home/alyaloale/Code/qount/state/research_runs/20260531T075351Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-range-20260531/qount-setup-model-compare-ethonly-v2-range-20260531.json
example_count=19681
eval_example_count=5905
v1_top_decile_avg_target_edge_pct=-0.0015544902
v2_top_decile_avg_target_edge_pct=-0.0013618186
v2_minus_v1_top_decile=+0.0001926716
v2_minus_v1_mae=+0.0000053851
v2_strong_favorable=0
```

读法：v2 第一版 plumbing 可用，但没有形成可交易 lift。包含 `range_noise` 时 top-decile
相对 v1 略好，但绝对值仍为负，MAE 稍差，且没有任何 `strong_favorable`。不能替换主线
setup model，不能作为 entry gate 或 promotion 证据。

2026-06-04 在 `validation_v1` 两个新窗口上做了只读 candidate 对比：

```text
v1_artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T132940Z-candidate-walk-forward-qount-candidate-wf-eth-validation-v1-v1-20260604
v2_artifact=/home/alyaloale/Code/qount/state/research_runs/20260604T132941Z-candidate-walk-forward-qount-candidate-wf-eth-validation-v1-v2-20260604
window_count=2
total_cycles=578
total_fresh_entry_selected=25
v1_total_selected_cycles=25
v2_total_selected_cycles=25
v1_strong_favorable=0
v2_strong_favorable=0
```

读法：v2 没增加 candidate 覆盖，也没产生更强质量分布；这次不推进 v2 到端到端验证。

## 架构判断

当前主要问题不是某个单点 bug，而是四件事叠加：

- 旧 promotion gate 与成交密度不匹配。
- discovery / validation 边界此前没有机器可读记录。
- AI prompt v1 过度保守，强候选上出现系统性 hold。
- `setup_model` v1 是 16 维线性 ridge，表达不了当前 alpha 所在的 phase × bin × bin 交互。

已接受的前置修复：

- [holdout.md](holdout.md)：冻结 `discovery_pool`，定义 `validation_pool_v1`，改成
  `G_paper` / `G_live`。
- 研究 artifact 增加 `holdout_role`。
- AI 决策缓存只用于 research `backtest` / `walk-forward`，live / `run-once` 不使用。
- setup/candidate 层 walk-forward 被拆出来，降低端到端读数的耦合。
- readiness 语义改名为 `offline_future_edge_readiness`，不再暗示可 promotion。

## 运行状态

最近 WSL `.env` 读回：

```text
QOUNT_MODE=live
QOUNT_MARKET_TYPE=future
QOUNT_RULE_MODE=bottom_line
QOUNT_LIVE_ENABLE=false
QOUNT_SYMBOLS=SOL/USDT,XRP/USDT,BTC/USDT,ETH/USDT
QOUNT_MAX_OPEN_POSITIONS=3
QOUNT_CONTRACT_LEVERAGE=6
QOUNT_AI_MODEL=gpt-5.5
HTTP_PROXY=http://192.168.128.1:7907
HTTPS_PROXY=http://192.168.128.1:7907
```

注意：`.env` 仍是旧 4-symbol live 形状，不是研究证明口径。研究命令必须显式使用
`--research-profile eth-only` 或 `--research-profile multi-symbol`。

最近 runtime 读回：

```json
{
  "mode": "live",
  "exchange_id": "binance",
  "market_type": "future",
  "quote_currency": "USDT",
  "halted": false,
  "ai_failure_streak": 0,
  "day_start_equity": null
}
```

最近 live guard 读回：

```json
{
  "ok": false,
  "armed": false,
  "persistent": true,
  "live_enable": false,
  "reason": "live_disabled"
}
```

2026-06-04 运维读回：`QountBinanceProxy` 曾是 `Ready` 但 7907 未监听，导致
WSL `binance GET https://fapi.binance.com/fapi/v1/exchangeInfo` 走
`192.168.128.1:7907` 超时。已从 Windows 侧 `Start-ScheduledTask -TaskName
QountBinanceProxy` 恢复；WSL `curl --proxy http://192.168.128.1:7907
https://fapi.binance.com/fapi/v1/time` 返回 serverTime，`preflight-live` 的
public API / symbols / credentials / one-way / balance guard 均通过。live guard 仍因
`live_disabled` 拒绝，这是当前正确状态。

## 代码结构

- `src/qount/settings.py`：运行配置与研究开关。
- `src/qount/research_profile.py`：`eth-only` / `multi-symbol` profile 覆盖。
- `src/qount/main.py`：CLI 入口。
- `src/qount/backtest.py`、`src/qount/walk_forward.py`：端到端研究执行。
- `src/qount/setup_model.py`：setup edge 模型、v2 interaction 研究、target slice、
  setup-edge walk-forward。
- `src/qount/ai_hold_baseline.py`、`src/qount/idle_window_diagnostic.py`：研究诊断工具。
- `src/qount/strategy_selection.py`：S1' 频段 × 策略族选择扫描引擎（约 1647 行），
  支撑 `strategy-selection-scan` 命令；triple-barrier / rank-IC / purged-CV / CARRY 双腿
  全部合并在此，纯 research-only，不调用 AI、不执行订单、不改 live。
- `src/qount/candidate_filter.py`、`src/qount/entry_quality.py`：候选生成、窄 blocker、research tags。
- `src/qount/orchestrator.py`、`src/qount/ai_client.py`：AI 决策、研究缓存、确定性 override。
- `src/qount/review.py`、`src/qount/research_slice_scan.py`：复盘和离线 readiness。
- `src/qount/artifacts.py`：研究 artifact 持久化。
- `tests/test_strategy_optimization.py`：策略、研究工具、artifact、walk-forward 主测试面。
- `tests/test_exchange_throttling.py`：交易所/候选执行边界测试。

## 验证状态

提交前必须保持：

```text
local unittest: PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
WSL unittest:   ./scripts/run-wsl-tests.sh
```

最近一次完整结果：本地 237 OK，WSL 237 OK。若本文件被后续提交更新，以提交前实际输出为准。

## 下一步

按 ROI 排序：

1. S1' prediction candidate：`4h xs_mom lookback=24 holding=6` 是当前最强 discovery cell；
   all-overlap、stride、限仓 portfolio replay 和 simple triple-barrier 都已跑；simple
   triple-barrier 120 天全负，不能 paper。下一刀只做 purged-CV / exit 设计 / 新 OOS。
2. S-CARRY：WLD/SOL post-only 与 basis-entry filter 均未过 6/1-6/5 after-tail；继续只能
   等新的完整独立日期，或重做 hedge timing / basis 风险模型，不进入 paper promotion。
3. 1d TS-MOM：top12 扩币 120 天和 2/3/4 月均为负；不能进入 S1.1/S1.2。
4. 对 5m 预测族只保留 cost-stress 证据：zero-cost 有 edge、maker-ish 成本后大幅转负；
   除非执行成本模型有实测突破，否则不继续 5m GBDT。
5. 若 CARRY 在真实双腿/阈值模型里稳定转正，再走 `profit-engineering-plan.md §10.5`
   专线；先 paper，不进入 live。
6. 旧 `val-jun03` repeated `range_noise` short 只能作为 discovery 诊断材料，不再作为主线第一优先级。

硬边界：

- 不开 live。
- 不 forward paper。
- 不把 `discovery_pool` 窗口当 validation。
- 不放宽 broad `range_noise` / `short_rebound_fail`。
- 不把 `offline_future_edge_readiness` 当 promotion 证据。
- 不把 Kronos 接入 candidate / risk / live。
- 不把 LightGBM 当默认研究依赖；当前默认 GBDT 路线用 sklearn `HistGradientBoosting`。
