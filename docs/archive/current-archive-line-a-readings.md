# qount current.md 历史归档 — line A 策略读数

> **状态**：archived（历史归档）｜**权威**：L6 归档｜**最后更新**：2026-07-25
> 本文件是 `docs/current.md` 移出的历史内容：① line A（`qount.main` eth-only）历史 discovery 读数
> （`最新策略读数 / WS-1..WS-4 / T-B / T-G / T-C setup_model v2`）；② `当前结论` 中 2026-07-16 加密重启之前的
> 历史详细条目（见文末同名小节）。按原始日期读取，均为
> `consumed_historical_discovery_pool`，不构成当前事实、promotion 或 live 依据。当前事实以 `docs/current.md` 为准。
> （注：正文内相对链接按原 `docs/` 位置书写，从本归档目录可能失效，按文件名到 `docs/` 下查找。）

---

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

## 当前结论历史条目（2026-07-16 之前，已归档）

- **2026-06-06 项目级决策(所有者确认):执行 §7 诚实止盈,停止追盈利。** 根因是架构级广度
  天花板——加密 majors r̄≈0.63,横截面有效广度仅 ~1.5、渐近天花板 `1/r̄≈1.6`(扩币救不了),
  §10.2 破局所需 IC 实际 ≈0.15、观测最强仅 0.05;横截面(XS-MOM/REV/funding)广度封死、
  日频 TS-MOM 已证伪、CARRY 已证伪——latency-insensitive 可触及路径穷尽,满足 §7 全局终止
  条件。**固化研究价值**(triple-barrier / purged-CV / DSR / PBO / effective-breadth 整套
  反过拟合 harness)作为成果,停止在择时盈利上继续投入。**这是停止投入,不放宽任何纪律**:
  live 仍关闭、不 forward paper、不放宽 broad gate、`validation_v1` once-only 资格继续保留。
  对账见 [profit-engineering-plan.md](profit-engineering-plan.md) §11.8。
- **2026-07-07 owner 决策:所有实盘部署到 VPS。** 当前 live / paper forward /
  dashboard 的生产真相是 `qount-vps:/root/qount`（仓库外SSH inventory），站点
  `qount.alyaloale.com`。Mac 工作区 `/Users/alyaloale/Code/qount` 只作为编辑和 git
  表面；部署通过 `scripts/sync-to-vps.sh` / `scripts/run-vps-tests.sh`。
- VPS只读审计确认旧生产cron自`2026-07-11`仍停用、无qount交易进程；旧C×D状态残留shorting/2x，绝不能
  恢复旧cron。`2026-07-19`在清空全部代理变量且设置`QOUNT_EXCHANGE_BYPASS_PROXY=true`后复核：直接出口
  仓库外production egress的地理结果是PH，Binance UM公共API正常，因此不是美国代理问题。旧credential曾由
  `apiRestrictions`返回`-2008 Invalid Api-Key ID`、spot/UM账户接口返回`-2015`；owner随后要求轮换，Mac/VPS
  `.env`中的API key与secret变量均已无备份删除，两个文件仍为`0600`。VPS绕过代理的两个独立IPv4身份来源与SSH
  公网入口一致，三个强制IPv6探针均不可达；精确IPv4只保存在仓库外production inventory。轮换后的测试credential
  只通过无回显stdin原子写入VPS `.env`并保持`0600`，Mac继续无凭证。Binance认证、读取/Futures/IP限制、提现关闭、
  one-way、全平与全账户0挂单均通过；但Spot/Margin仍开启、可用资金低于300 USDT，TOP3只读symbol config均为
  isolated 2x。由于credential经对话明文传输，最终实盘前必须在交易所再次轮换并直接写VPS。代码的
  `QOUNT_EXCHANGE_BYPASS_PROXY`默认false，不改变既有路径；诊断未调用下单、撤单、转账、杠杆或保证金写接口。
- readiness v0.3又补齐API Futures/IP限制、余额、全平账户和open-orders硬门。最终artifact
  `20260718T100615Z-um-live-pilot-readiness-v04`为`blocked_live_pilot_readiness`，20项blocker、
  `live_orders_allowed=false`，readiness hash `2b072733...a8b1e`，manifest content hash
  `7d4de1b8...f5594`。300 USDT精确本金、公共路由、旧guard关闭和rollback已通过；开始日、forward/paper/dry、
  私有账户与独立live runtime仍阻断。同时冻结的append-only每日journal：
  每行保存权益/钱包、目标与实际权重、订单意图/结果、funding/费用、执行状态和risk flags，并绑定row/chain
  hash；重复日期或历史篡改直接拒绝。本轮未同步VPS代码、未改`.env`、未触碰订单。owner方向已记录，但
  开始日和最终arm仍须在全部安全门通过后单独确认。
- **独立MiniTrend UM order-free forward/paper生产周期曾在VPS启用，现已按安全要求停止。** paper固定Base v0.2、300 USDT
  全现金、200根signal-only warmup、TOP3日线、完整价格与每币每日3次funding，只有10%累计回撤halt，无账户
  单日止损；v0.3同时完整记录Risk 2.0%与Funding Veto shadow且二者不控制订单。`qount-mini-trend-forward.timer`
  曾按每日`03:20 UTC`后随机延迟最多10分钟运行，已于2026-07-20执行`disable --now`并复核为`disabled/inactive`；其历史运行合同显式关闭所有legacy live开关、清空环境代理、`flock`防重入、`umask
  077`并尊重`HALT`。最近完整run为VPS
  `/root/qount/state/mini_trend/forward/runs/20260719T081828Z`：TOP3规则`3/3`，公共日线到`2026-07-18`，funding
  `3/3`完整；冻结起点`2026-07-19`尚无完成bar，因此仍为0 pair/0 paper day/0 journal。preflight v0.3只剩
  `spot_margin_disabled/pilot_capital_available/isolated_one_x_verified`三项账户blocker；readiness v0.4阻断10项，
  artifact全部`0600`且`live_orders_allowed=false`。
- 最新完成bar projector已独立实现：只追加一个明确不计收益的flat synthetic outcome以复用Base状态机并投影最后决策；
  测试证明同一决策在真实任意outcome到来后与paper replay的target和execution-state hash一致。当前因起点bar未完成返回
  `paper_start_bar_not_available/decision=None`。它不等于订单dispatcher；exchange-native stop同步、幂等live执行和7日
  dry仍未实现/未通过，因此`independent_runtime_verified=false`。rollback已同时覆盖forward timer；旧crontab有效行仍为0。
- **固定本金的定投/定减与买卖标签已完成首轮历史discovery。** BTC UM按周25%阶梯、TOP3 UM按周50%阶梯
  （300 USDT下25%会违反BTC最小名义价值）、SPY复权历史按周25%阶梯；均不追加外部资金、不做空、gross不
  超过1，并比较buy-and-hold、经典DCA、均线DCA/DCR和均线全仓/现金。BTC的经典DCA/均线DCA-DCR/持有收益为
  `+47.96%/+51.52%/+87.40%`，TOP3为`+82.34%/+46.81%/+104.91%`，SPY为
  `+79.40%/+62.19%/+82.47%`；均线DCA/DCR均未战胜持有，策略本身不晋级。
- 同一实验用未来20根、波动率归一化triple barrier生成`buy/hold/sell`目标；特征只读决策日已完成数据，
  Logistic/HGB采用按年扩展Walk-Forward且以`label_end_date` purge。六个模型的平均Brier和log-loss uplift都为
  负。TOP3 HGB虽显示`+216.99%`，但4/4 Brier折均输常数先验、2025单年贡献`+92.66%`且2026为
  `-21.11%`，判定为路径/时点运气，不连接仓位。最终artifact
  `/mnt/e/qount_data/qount/artifacts/experiments/20260718T155058Z-periodic-allocation-v02/mini_trend_periodic_allocation.json`
  SHA-256 `0bd6d491...fc`，manifest content hash `aefb001a...49`。
- **美股映射加密资产成为新的低频结构研究线，但产品结构严格分层。** Binance USD-M当前有TSLA/MSTR/AMZN/
  COIN/META/NVDA/GOOGL/QQQ/SPY/AAPL/MSFT共11个`TRADIFI_PERPETUAL`，最早TSLA也只从`2026-01-28`
  开始；Binance spot另有`NVDAB/TSLAB/SPYB`等`*B`映射token。Bybit有AAPLX/AMZNX/COINX/GOOGLX/
  METAX/NVDAX/TSLAX等xStocks现货和对应equity linear合约。映射现货涉及发行/托管/赎回与交易所风险，
  永续只提供合成价格敞口并有funding、标记价格和清算风险，不能混为同一资产或共享回测成本模型。
- 首个冻结假设检验“周末/美股休市期间永续折价，下一美股现金时段部分收敛”：用纽约DST与SPY真实现金
  日历，从前一现金收盘到下一开盘前代理价；只在周末收益为负时做多，下一现金收盘退出，同日标的等权且
  总gross=1，扣24bps往返成本与实际funding。11个标的仅有126个symbol-event、18个独立cash date；周末/
  现金时段相关`-0.188459`、反号率`56.35%`、71个做多信号。按日期聚类后的组合收益`+3.7516%`、maxDD
  `4.0029%`、日期cluster bootstrap正均值概率`71.16%`，证据偏弱，不进paper/live。早期按126个横截面事件
  顺序复利的`+29.69%`重复使用了同一笔资本，已经作废。最终artifact
  `/mnt/e/qount_data/qount/artifacts/experiments/20260718T155058Z-tradifi-weekend-v02/binance_tradifi_weekend.json`
  SHA-256 `d857361f...02c`，manifest content hash `821ad7d2...08`。
- **2026-07-10 VPS 资源耗尽事故已在 2026-07-11 修复。** 根因不是 Caddy/new-api 网关，
  而是 root crontab 中 C×D live `*/2`、C×D publisher `*/5`、X4 paper daily 三个入口都没有
  `flock`/总 `timeout`；Binance DNS 抖动时，CCXT `load_markets()` 还会额外访问私有
  `/sapi/v1/capital/config/getall`，旧进程不退、新 cron 继续叠加，最终让 1.6G VPS 的 fork/内存
  资源耗尽。修复已部署：三个 cron 入口共用 `scripts/desktop/cron_guard.sh`，脚本内层 non-blocking
  `flock` + process-group timeout；crontab 外层再做同类防线；live 改为每 5 分钟、publisher 错峰
  到第 2 分钟，并由 `deploy/cron/qount-production.crontab` 固化；C×D 删除重复的私有余额读取；
  `build_exchange()` 禁用不需要的
  `fetchCurrencies`；交易腿失败不再刷新网页时间戳伪装成成功。策略权重、2x 上限、short gate、
  exchange-native STOP_MARKET 和 carry paused 均未改变。理由：当前信号是日线，交易所止损已覆盖
  轮询间隙，2 分钟改 5 分钟减少 60% 调度/API 压力，不改变已验证 alpha 语义。
- **VPS 容量余量仍偏薄，但当前不是 qount 残留。** 2026-07-11 00:26 CST 两轮新 live cron
  成功后，qount 相关进程为 0、swap 为 0；主要常驻 RSS 是 `new-api≈433M`、`sub2api≈380M`，
  整机 `MemAvailable≈322M`。因此本次复发链已由 lock/timeout 切断，但“网关 + 多容器 + 实盘”
  共用 1.6G 仍有容量风险。长期仍应给 VPS 加内存或把 qount/网关拆机；没有应用级证据前，
  本轮不擅自给 new-api/sub2api 加可能导致服务抖动的硬 memory cap。
- **2026-07-07 项目治理规则已固定。** 新增
  [project-rules.md](project-rules.md)，作为文档分类、研究线隔离、执行记录、反过拟合规范、
  代码架构和弃用清理的项目级规则。后续每批有意义更改必须更新本线 changelog 或
  [update-log.md](update-log.md)；影响当前事实、生产真相或全局规则时同步更新本文件。
- **2026-07-08 Alpha Agents research-only 骨架已接入。** Owner 授权先搭建多 agent 架构用于
  搜集资料、优化设计并后续接入量化训练。新增 [alpha-agent-plan.md](alpha-agent-plan.md) 和
  `src/qount/alpha_agents/`：内置 market-data / exchange-rules / quant-librarian /
  feature / experiment / red-team / ops-audit 等 LLM research 角色，以及 `model_trainer`、
  `backtest_auditor`、`risk_architect` 三个 deterministic/quant 角色；支持从 JSON 替换角色和任务。
  默认不调用 LLM，显式 `--with-llm` + `QOUNT_ALPHA_AGENT_API_KEY` 才接
  `https://llm.alyaloale.com/v1` / `glm-5.2`。硬边界：agent 只写 research artifact，不输出订单、
  目标权重、live 配置或风控 override；promotion 仍必须靠 deterministic scorecard。
- **2026-07-08 Alpha Agents deterministic scorecard 已接入。** 新增
  `src/qount/alpha_agents/promotion.py` 和 `scripts/research/alpha_agent_scorecard.py`，把
  proposal/data/baseline/cost/anti-overfit/breadth/paper/live/LLM-boundary 做成 G0-G7/GX gate。
  该 CLI 只读 metrics JSON 并写 research artifact，不调用 LLM、不访问私有交易所、不写生产 state；
  真实策略必须由 dataset / label / backtest / A10 trainer 产出 metrics，不能用 LLM 报告或手填值
  通过 promotion。
- **2026-07-08 Alpha Agents beta-residual metrics builder 已接入。** 新增
  `src/qount/alpha_agents/metrics.py` 和 `scripts/research/alpha_agent_beta_metrics.py`，从对齐 period
  returns 计算 BTC beta、beta-residual return、相对 BTC / TOP3 equal-weight / current live baseline
  的超额，并生成 promotion metrics。高阶验证字段(DSR/PBO/purged-CV/paper/capacity)默认是
  blocking value，必须由真实 quant artifact 补齐；示例 fixture 正 residual 仍会被 scorecard 的
  G4/G5/G6 block。
- **2026-07-08 Alpha Agents source scoring 与 Binance public returns 已接入。** 新增
  `src/qount/alpha_agents/knowledge.py` / `scripts/research/alpha_agent_sources.py` 对官方文档、论文、
  书籍、教程和安全资料做 trust scoring；教程只能作为 learning material，不能满足 promotion。
  新增 `src/qount/alpha_agents/binance_returns.py` /
  `scripts/research/alpha_agent_binance_returns.py`，复用 Binance public dump 生成对齐 returns。
  2024Q1 UM ETH SMA smoke 已跑通并生成 beta metrics，但 scorecard 正确 block：未用 runtime
  exchangeInfo/filter validator，跑输 BTC/TOP3，BTC beta 过高，未计 funding/min-notional，也没有
  DSR/PBO/paper 证据。
- **2026-07-08 Alpha Agents Binance runtime rules 与 funding 层已接入。** 新增
  `src/qount/alpha_agents/exchange_rules.py` 和
  `scripts/research/alpha_agent_exchange_rules.py`：只拉 Binance 公共 `exchangeInfo`，解析
  `PRICE_FILTER`、`LOT_SIZE`、`MARKET_LOT_SIZE`、`MIN_NOTIONAL`，并对 400 USDT 小盘目标名义做
  min-notional/step-size coverage；不读取私钥、不访问账户、不下单。`binance_returns.py` 现可通过
  `--exchange-rules-path` / `--fetch-exchange-info` 接 runtime rules，并通过 `--include-funding`
  从 Binance public dump 计 USD-M funding cashflow。2024Q1 ETH SMA 复跑：
  `min_notional_coverage=1.0`、`funding_included=true`，但 `net_residual_return_pct=-1.165668`、
  `beta_to_btc=0.552037`，scorecard 仍 `verdict=block`。读法：Binance 规则/成本 plumbing 已补，
  但样例 SMA 明确不是 alpha；下一步应做真正 feature/label/model runner。
- **2026-07-08 Alpha Agents feature experiment runner 已接入。** 新增
  `src/qount/alpha_agents/feature_experiment.py` 和
  `scripts/research/alpha_agent_feature_experiment.py`：从 Binance public dump 读取 klines/funding，
  在 train split 上选 feature grid，再输出 OOS 月度 returns 给 beta metrics/scorecard。当前内置
  `momentum/reversal/relative_momentum/vol_adjusted_momentum` 与
  `long_short/long_cash/short_cash`，仅作为 A10 前的 deterministic baseline contract。2024Q1 ETH
  1h smoke 选中 `relative_momentum_lb12_thr0_long_short`，OOS `strategy_total=-30.103078%`、
  BTC B&H `+39.471843%`、TOP3 EW `+54.382491%`、`beta_to_btc=7.494191`、
  `net_residual_return_pct=-302.677680`，scorecard `verdict=block`。读法：第一批简单价量 feature
  被 OOS 打穿；已打通模型实验接口，但没有可交易 edge。下一步应补 walk-forward/DSR/PBO 与更强
  microstructure/OI/bookTicker 特征，而不是继续调这个候选。
- **2026-07-08 本地 GLM-5.2 Alpha Agents 已跑通并产出 Strategy V0（历史快照，运行配置已由7月19日合同取代）。** Owner授权把gateway key
  放入本机用户级环境；已写入 `~/.qount/alpha-agent.env`，权限 `600`，由本地 runner 自动读取，
  不进入仓库、artifact 或 `.env`。`alpha_agent_plan.py --with-llm` 现支持 `max_concurrency=3`、
  `max_tokens=4000`、`max_retries=1`，单个 LLM 输出失败会重试或降级为 blocked report，不再打断整批。
  全量 agent artifact：
  `state/research_runs/20260708T044141Z-alpha-agent-plan/alpha_agent_plan.json`。基于结果在
  [alpha-agent-plan.md](alpha-agent-plan.md) 增补 `Strategy V0: Microstructure Residual Alpha`：
  第一刀是 USD-M 1m/5m residual alpha，先做 `kline_taker_flow_v0` 和 `derivative_state_v0` kill-test，
  bookTicker/aggTrade/diff-depth/forceOrder 先走 live collector gap/replay，不直接 promotion。
- **2026-07-08 Alpha Agents derivatives-state 数据层已接入。** 新增
  `src/qount/alpha_agents/derivatives_state.py` 和
  `scripts/research/alpha_agent_derivatives_state.py`，只用 Binance public REST 拉
  `/futures/data/openInterestHist`、`/futures/data/takerlongshortRatio` 和 `/fapi/v1/openInterest`，
  写 research artifact，不读私钥、不访问账户、不下单。该接口按官方 recent-data 限制只作为近 30 天
  research/forward 输入，不能伪装成 2021-2026 长历史。真实 1 天 5m smoke artifact：
  `state/research_runs/20260708T045352Z-alpha-agent-derivatives-state/alpha_agent_derivatives_state.json`；
  BTC/ETH/BNB/SOL 的 OI 与 taker ratio 各 288 rows、0 gaps、coverage ≈ `0.9965`，
  `open_interest_hist_count=1152`、`taker_long_short_count=1152`、`current_open_interest_count=4`、
  `error_count=0`。
- **2026-07-08 derivative-state feature runner 已接入并完成第一刀 smoke。**
  `alpha_agent_feature_experiment.py` 现支持 `--kline-source public_dump|rest`、
  `--derivatives-state-path`、`--min-feature-coverage`，并新增 `oi_delta`、`oi_value_delta`、
  `taker_ratio`、`taker_imbalance`。当前 Mac 到 `fapi.binance.com` REST kline 直连超时/SSL EOF；
  public dump fallback 因 ETH/SOL 2026-07-07 5m daily dump 尚未发布，完整 BTC/ETH/BNB/SOL smoke
  被 coverage gate 正确拦截。可运行的 BTC/BNB 两币 BNB smoke：
  `state/research_runs/20260708T093014Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`，
  OOS `strategy_total_return_pct=-7.056039%`、BTC `+1.403648%`、equal-weight `+1.135040%`、
  `net_residual_return_pct=-7.301083`；metrics
  `state/research_runs/20260708T093052Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`；
  scorecard `state/research_runs/20260708T093102Z-alpha-agent-scorecard/alpha_agent_scorecard.json`
  为 `verdict=block`。读法：OI/taker ratio 接入链路可用，但这一刀没有 alpha；不能 forward paper
  或 live，下一步应补 taker-flow/walk-forward/DSR/PBO，并在 ETH/SOL dump 或 REST 路由恢复后复跑完整 universe。
- **2026-07-10 `kline_taker_flow_v0` 已完成并按当前执行合同停止。** `Bar` 现保留 Binance kline
  原生 quote volume、trade count、taker-buy base/quote volume；feature runner v0.2 新增
  `kline_taker_imbalance`、`kline_taker_pressure_change`、`kline_quote_volume_z`、
  `kline_realized_vol_change`、显式 `polarity=+1/-1`，以及 rolling as-of BTC beta 的 forward residual
  rank-IC 选择。真实 BTC/ETH/BNB/SOL、5m、2024-01..08、train 6 月/OOS 2 月、40 trials/horizon：
  h3 选中 `kline_taker_imbalance_lb3_inv`，train/OOS rank IC `0.01993/0.03481`，但 OOS
  `net_residual=-166.019%`；h6/h12 均选中已知 price momentum inverse，OOS rank IC
  `0.02344/0.01326`，net residual `-91.363%/-58.191%`。三份 scorecard 均 `verdict=block`。
  读法：h3 taker imbalance 有弱信息，但训练 IC 未过 `0.02` 且 taker 换手成本把 gross edge 完全吃掉；
  h6/h12 没有产生新 taker-flow 候选。不能在已看 Jul-Aug 上继续调 threshold 后把它当 validation，
  不进 A10/paper/live；本轮随后已补 walk-forward/DSR/PBO，结果继续 block，下一步转 collector 数据层。
- **2026-07-10 research artifact 并发覆盖已修复。** 并行生成 h3/h6/h12 metrics 时发现原目录名只有
  秒级时间戳，三个进程会写同一路径。`persistent_research_dir` 现通过原子目录创建分配
  `base/-01/-02`，同秒并发 artifact 不再互相覆盖；三路并行 metrics/scorecard 已实测生成独立路径。
- **2026-07-10 Alpha Agents G4 validation adapter 已接入并完成真实负向验证。** 新增
  `src/qount/alpha_agents/validation.py` 和 `scripts/research/alpha_agent_validation.py`，按源 feature
  artifact 的冻结 config 重放 candidate matrix，计算源选中候选 DSR、按原 `rank_ic` 选择语义的
  CSCV/PBO、带 embargo 的 purged folds 和 expanding walk-forward；普通 feature artifact 仍保持精简。
  `alpha_agent_beta_metrics.py --validation-path` 只接受 source feature path 完全匹配的 validation，
  防止跨实验拼接 G4。真实 h3：selected per-period Sharpe `-2.2764`、DSR `3.19e-152`、
  PBO `0.781746`、purged `0/5` 正、walk-forward `0/5` 正、largest-contributor-removed
  `-99.9975%`；最终 scorecard 的 G4 同时因 DSR/PBO/purged/largest-contributor block。
  artifact：`20260710T134718Z-alpha-agent-validation`、metrics `20260710T134758Z`、scorecard
  `20260710T134808Z`。旧 `20260710T134252Z` 使用 Sharpe-selection PBO，已被最终 source-selection
  CSCV artifact 取代，不作为结论。完整测试 `970 OK`，Alpha/数据/validation 聚焦测试 `57 OK`。
- **2026-07-14 Alpha Agents S3 public microstructure collector 已完成严格 60 秒数据层 smoke。**
  新增 `src/qount/alpha_agents/live_collector.py` 和
  `scripts/research/alpha_agent_live_collector.py`，research-only 采集 Binance USD-M public
  `bookTicker`、`aggTrade`、diff-depth、`forceOrder`，并用 public WS-API/REST depth snapshot
  做 update-id gap、事件时间和订单簿重放审计；不读取账户、不下单、不写 paper/live state。
  snapshot 获取现使用有限重试并保留 retry 诊断，只有重试耗尽才计最终错误，默认错误率门槛仍为 1%；
  默认交易流已对齐 S3 合同为 `aggTrade`。最终 BTC/ETH/BNB/SOL 60 秒 artifact
  `state/research_runs/20260714T093402Z-alpha-agent-live-collector/alpha_agent_live_collector.json`
  共 23,339 条市场事件、16/16 snapshots、aggTrade gap `0`、depth sequence break `0`，实际重放
  1,919 个 depth update 后非法档位/空簿/crossed book 均为 `0`，四币全部锚定，event stale/future
  均为 `0`，`verdict=pass_data_smoke`。一次 public 流首次建连 `SSLEOFError` 后重连成功，发生在
  `connection_open` 前，未形成数据 gap。读法：S3 gap/replay 实现和短时公网 smoke 已通过，但计划要求的
  7 天 forward data gate 尚未完成；这不是 alpha、scorecard 或 promotion 证据，不能训练 A10、forward
  paper 或 live。
- 2026-07-07 已部署 X4 live 执行修复到 VPS：交易所原生 STOP_MARKET 在两分钟 cron
  间隔内打平后，会根据上一轮 holdings + 当前交易所仓位同步写入本地 Chandelier
  `latched`，防止同一日线 short 目标下立即重开；`cxd_live_cron.sh` 同步加入 5MB
  默认日志轮转，只归档 `/root/cxd_live.log` 到 qount 自身 `state/logs/archive/`。
- 旧 line A / ETH-only 研究线当前没有 promotion 证据，不能 forward paper，也不能 live。
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
- **2026-06-06 重启方向设计:L3 换信息源(链上/流/叙事 + AI)。** §11.8 规定唯一合法重启触发是
  「结构性新输入」;经五杠杆(L1 跨资产 / L2 事件驱动 / L3 换信息源 / L4 跨所套利 / L5 换目标)
  权衡,所有者选 **L3**——把信息源从价量换成非价量慢数据、horizon 抬到日/周线、AI 从最终 gate
  挪到慢特征/regime 标注层,攻基本定律的 **IC 项**。新计划文档
  [l3-information-edge-plan.md](l3-information-edge-plan.md):优先 **L3a 稳定币供给→市场择时**
  (广度来自时间 ~150 周、要求 IC ≈0.083 比横截面 0.15 更可达、执行最干净);第一刀 kill-test 即
  DefiLlama 稳定币供给对 BTC 周线 forward-return 的时序 IC + DSR/PBO。仍 research-only、先证伪
  再投入、全套硬约束不变;不过则 L3 也按 §7 退出。
- **2026-06-06 L3 S0.1 数据接入层已落地并端到端验证(research-only)。** 新模块
  `src/qount/l3_information_edge.py` + research-only 命令 `l3-stablecoin-fetch`:拉 DefiLlama
  聚合稳定币总供给、缓存到 `state/`、归一化成排序去重日度序列、严格 as-of(无前视)join 到周线
  锚点;只用 stdlib `urllib`、不引入新依赖、live / `run-once` 不 import。local/WSL unittest 均
  `254 OK`(+5 新单测)。WSL 实网拉取:3112 日度观测(2017-11..2026-06)、归一化零丢点、近 4 年
  窗口 209 周锚点全覆盖(全历史 444 周)、缓存命中路径已验证。artifact
  `state/research_runs/20260606T045947Z-l3-stablecoin-fetch/`。**只做数据层,未算 IC、未下注**;
  下一步 S1 kill-test(稳定币供给增速 → BTC 周线 forward-return 时序 rank-IC + DSR/PBO,门控
  breadth-adjusted 要求 IC ≈0.083)。硬约束全不变,未碰 `validation_v1`。
- **2026-06-06 L3 S1 kill-test 完成:L3a(稳定币供给→BTC 周线择时)= 证伪。** 新增
  `evaluate_l3a_stablecoin_timing` + 命令 `l3-stablecoin-timing-scan`:供给 log-增速
  (lookback 4/8/13 周)对 BTC t→t+h(1..4 周)forward-return 的时序 rank-IC,复用 §7 的
  DSR/PBO/Spearman/`_sharpe` harness,12 个 (L×h) config 全计 DSR trial,BTC 走期货 fapi。
  local/WSL `257 OK`(+3 单测)。两窗口实跑均 `falsified_l3a`:全窗口 2020-07..2026-06(309 周)
  best |rank-IC|=`0.054` < 门控 `0.083`(净正只是退化恒做多的 BTC beta,DSR/PBO 因 config 雷同
  虚高、不具判别力);子窗口 2022-06..2026-06(209 周)|rank-IC|=`0.154` 虽过门控却**符号翻转为负**
  (与"供给=干火药→涨"先验相反)+ PBO `0.64`(高过拟合)。**符号在窗口间翻转 = 无稳定样本外预测**
  ——供给与 BTC 同骑一条流动性周期(内生共动),与 §7 价量 IC ~0.05 天花板同源。rank-IC 对单调变换
  不变,z-score 救不了。artifact `state/research_runs/20260606T051647Z-...` 与 `...051746Z-...`。
  下一步按 §5/§8:测 L3b(链上横截面,相关天花板+共动顾虑仍在)或经济动机耗尽则 L3 按 §7 退出。
  硬约束全不变,未碰 `validation_v1`。
- **2026-06-06 L3b(链 TVL 横截面)kill-test 完成 = 证伪;L3a+L3b 均证伪 → L3 整体证伪,按 §8/§7
  退出。** 新增 `evaluate_l3b_chain_tvl_cross_section` + 命令 `l3-chain-tvl-scan`:DefiLlama 链
  TVL log-增速横截面排序 12 个链 token,复用 §7 harness + `_panel_effective_breadth`。local/WSL
  `259 OK`(+2 单测)。WSL 实跑(209 周):**effective_breadth=`1.68`**(r̄=0.559)< 逃逸阈 2.5 →
  breadth 不逃逸;best |rank_ic_mean|=`0.0755`(t=3.47,正、全 9 cell 符号稳定、DSR 0.953/PBO 0.36
  都过)< 门控 0.15 → `falsified_l3b`。**这是 §2"广度幻觉"的经验证实**:L3b 找到了真实、显著、
  符号稳定的弱信号(链 TVL↑→token 涨),但 token 收益面板有效广度仍只有 1.68(贴着 §7 价量天花板
  1.6),要求 IC 仍 ~0.15、真信号只有一半——**绑定约束是广度不是信号,§7 架构级根因在新数据源原样
  复现**。慢数据换信息源没绕开广度天花板。下一次重启需真正结构性新输入(L1 低相关 universe / L4
  跨所套利 / L5 换目标),非 L3 内部堆特征。artifact `state/research_runs/20260606T052959Z-...`。
  硬约束全不变,未碰 `validation_v1`。
- **2026-06-06 重启线选定 L1(跨资产趋势,正面攻 BR);S1 广度 kill-test 通过。** 所有者从
  L1/L4/L5 选 L1。命门是「跨资产 universe 有效广度是否 ≫1.6」——纯数据、零新场(新模块
  `l1_cross_asset.py` + 命令 `l1-cross-asset-breadth-scan`:Tiingo 免费跨资产 EOD → as-of 周线
  → `_panel_effective_breadth`)。**基建发现:跨资产 TradFi 免费免-key 源(Stooq 反爬 / Yahoo
  429 / FRED 超时)从生产主机全不可用;选 Tiingo(已配 key)**。local/WSL `262 OK`(+3 单测)。
  WSL 实跑(广度随 universe 正确变宽单调改善):crypto majors r̄0.63/breadth 1.6 → L1 13-ETF
  r̄0.354/**2.477**(临界)→ L1 21-ETF 跨资产 r̄0.303/**2.973** > 2.5 → `breadth_supports_l1`。
  **真正跨资产 universe 结构性逃逸了 majors 广度天花板**(§7/L3 都缺的那一项);eff_breadth 2.97
  × ~52 周 → BR≈154 → 要求 IC≈0.081(可达,远好于横截面 0.15)。门控 2.5 未动,只按论点本意
  补全 universe。**S1 通过 → 进 S2**(ts_mom 聚合 IR / 扣费净值 / DSR / PBO)。诚实保留:广度
  过线必要非充分,趋势扣费 IR 是否过线是 S2 才知道;开券商只在 S1–S4 全过后。计划见
  [l1-cross-asset-plan.md](l1-cross-asset-plan.md)。artifact `...20260606T062015Z-...`。硬约束全不变。
- **2026-06-06 L1 S2 趋势 kill-test:真实正 edge 但低于门控(`tsmom_below_gate`)。** 21-ETF
  TSMOM(sign(trailing L 周收益)× 反波动率定权,周再平衡)+ 复用年化 Sharpe/DSR/PBO(命令
  `l1-cross-asset-tsmom-scan`)。local/WSL `263 OK`(+1 单测)。WSL 实跑(753 周):best 年化净
  Sharpe `0.421`(lb39w,gross 0.542)、4 lookback 净 Sharpe 全正、2022 利率趋势 crisis-alpha;
  但 < IR 门控 0.5,DSR `0.856`(<0.95)、PBO `0.627`(>0.5)均不过。**跨资产趋势是真实、正、经济
  一致的 edge(不同于 L3a 噪声),但零售 ETF universe 上只有 ~0.42 净 Sharpe**——绑定限制从广度
  变成「零售 ETF 的 edge 量级」,真 CTA 需 50–100 期货(券商,S5 推迟)。S2 未过 → 不进 S3。
  下一步所有者决策:lookback 等权 ensemble(无参、回应 PBO)/ 接受 ~0.42 作零售天花板 / 停。
  artifact `...20260606T063553Z-...`。硬约束全不变,未碰 `validation_v1`、未开券商。
- **2026-06-06 L1 S2 ensemble:确认 edge 真实稳健但量级仍 < 门控(`tsmom_ensemble_below_gate`)。**
  按所有者选择做 lookback 等权 ensemble(`--ensemble`,信号层 `mean_L sign(trailing_L)`,无参 →
  purged 时间折代替 DSR/PBO)。local/WSL `264 OK`(+1 单测)。WSL 实跑:净年化 Sharpe `0.363`
  (gross 0.553)、**4/5 时间折为正**(0.87/0.11/0.35/-0.04/1.00)——但**反而略低于最佳单一 lookback
  lb39w 0.421**(等权纳入较弱快周期 lb13w 0.10 拉低)。**L1 完整定论:跨资产趋势是本项目第一个
  真实、稳健、正、经济一致的 edge**(gross 0.55、4/5 折正、2022 crisis-alpha、与 crypto 无关),
  但零售 ETF 净 Sharpe 仅 ~0.36–0.42 < 开券商所需 0.5;绑定限制是「原始 edge 量级 × 零售 universe」
  非方法,经典 CTA 0.7–1.0 需 50–100 期货(券商 S5)。S2 未过 → 不进 S3。**L1 落在终局决策点**:
  S5 券商(真期货 universe)/ 固化为部分成功 / 转 L5。artifact `...20260606T064415Z-...`。硬约束
  全不变,未碰 `validation_v1`、未开券商。
- **2026-06-06 终局决策(所有者确认):L1 固化为部分成功,暂停。** 三条文档内合法路径
  (S5 券商 / 固化 / 转 L5)中,所有者选**固化**。理由对账:(a) L1 计划 §3 规定「开券商(S5)
  只在 S1–S4 全过之后」,而 S2 扣费 IR 不显著(净 Sharpe ~0.4 < 0.5)、DSR `0.856` < 0.95、
  PBO `0.627` > 0.5 均未过——**不在 sub-gate 证据上开真期货券商、不为它建新工程轮/掏真实资金**;
  (b) 在同批已看 ETF 数据上继续加旋钮/堆标的正是 §5 禁止的「L1 内部堆参当重启」,L1 内部可触及
  研究路径已穷尽。**固化内容**:L1 是本项目**第一个真实、稳健、正、经济一致的 edge**(21-ETF
  跨资产 TSMOM,gross Sharpe 0.55、净 0.36–0.42、4/5 时间折正、2022 利率趋势 crisis-alpha、与
  crypto 无关),并**经验证实了 §2 的核心论点**——把 universe 换成结构性低相关的跨资产能真正逃出
  majors 广度天花板(eff-breadth 1.6 → 2.97),绑定约束随之从「广度」迁移到「零售 ETF 的 edge
  量级」。**这是停止在 L1 上投入,不放宽任何纪律**:L1 按 §7 暂停而非删除——若未来开期货券商
  (独立工程轮)或拿到结构性更优 universe,S2 门控原样适用、从 S3 续跑。live 仍关闭、不 forward
  paper、不放宽 broad gate、`validation_v1` once-only 资格继续保留。下一次重启需新的结构性输入
  (L5 换预测目标=波动率 / L4 跨所套利),非 L1 内部微调。对账见
  [l1-cross-asset-plan.md](l1-cross-asset-plan.md) §3/§5。
- **2026-06-06 重启线选定 L4(跨所套利,换「游戏」=市场中性不预测方向);S1 跨所 spread kill-test
  证伪。** 所有者从 L4/L5/L2 选 L4。命门:跨所 funding spread 的「幅度 × 持续性」能否跨过双所往返
  成本——纯数据、零新场、零下单(新模块 `l4_cross_exchange.py` + 命令 `l4-cross-exchange-funding-scan`:
  ccxt 拉多所 perp funding 历史、`state/` 缓存、按各所原生间隔归一到 8h 当量、as-of 对齐、取
  `spread=max−min` 做多最低所/做空最高所、复用 §7 的 `_sharpe`/DSR/PBO)。**基建发现:三所
  Binance/Bybit/OKX 均需配置代理(直连全 NetworkError),跑命令前必须 `source .env`,否则
  `Settings.from_env` 拿不到代理→全所 unreachable;Hyperliquid 实测可达但 USDC 结算+1h funding,
  推迟 S2 需独立符号/基差映射。** local/WSL `269 OK`(+5 单测)。WSL 实跑(120 天 discovery、
  6 USDT 永续、binance/bybit/okx、261 共同 8h bucket):**(a) 跨所 spread 真实为正——毛年化
  `+0.074`(7.4%/yr)、6 币毛值全正**;(b) 但 `break_even_cost_per_side ≈ 0.000027`(**2.7bps/腿**),
  且最优 pair **每 ~1.5 bucket(~12h)翻转一次**(261 翻 ~165 次),每翻付 4 腿往返;(c) 按 taker
  `0.0004`:净年化 `−1.6`、组合 Sharpe 深负、**`required_maker_fill ≈ 0.93`**(单所 CARRY 的 maker
  墙跨所原样重现);(d) `DSR=0.0`(最佳 per-period 净 Sharpe `−1.1` < 噪声期望 `0.107`)、PBO 0.083
  (低但因净负无意义)。`decision=cross_exchange_spread_below_gate`。**根因:套利者已把跨所 funding
  spread 压到 ~maker 成本地板(回本 2.7bps),残差每 ~12h 均值翻转 → 4 腿换手吃光毛值**;只有
  co-located maker/返佣 HFT(另一种操作者、需多所基建)够得着,对本「慢+延迟无关」操作者证伪——
  正是计划 §5/§1 预判的成本墙。S1 未过 → 不进 S2。artifact
  `state/research_runs/20260606T113148Z-l4-cross-exchange-funding-scan/`。硬约束全不变,未碰
  `validation_v1`、未下任何单、未开多所账户。**L4 落在终局决策点**(退出转 L5/L2 /
  L4-S2 maker 执行研究需多所账户),对账见 [l4-cross-exchange-plan.md](l4-cross-exchange-plan.md) §3/§5。
- **2026-06-06 全局决策(所有者确认):接受 §7 全局诚实止盈,三条重启线全部走完,停止追择时盈利。**
  §7 原始止盈后,按 §11.8「唯一合法重启=结构性新输入」依次试了三条结构性重启线,各攻 `IR=IC×√BR`
  的不同项或游戏本身,**全部撞到同一类结构性/成本墙**:
  - **L3(换 IC 来源:非价量慢数据)= 证伪** —— 广度天花板在新数据源原样复现(L3b 找到真信号
    IC 0.075 但 token 收益 eff-breadth 仍 1.68,要求 IC ~0.15)。
  - **L1(攻 BR:跨资产趋势)= 固化暂停** —— 跨资产 universe 真逃逸广度天花板(eff-breadth 2.97),
    找到**项目首个真实、稳健、正、经济一致的 edge**(跨资产 TSMOM),但零售 ETF 量级净 Sharpe ~0.4
    < 0.5 券商门控;真 CTA 量级需期货券商(独立工程轮,未授权)。
  - **L4(换游戏:市场中性跨所套利)= 证伪** —— 跨所 funding spread 真实(毛 +7.4%/yr)但已被压到
    maker 成本地板(回本 2.7bps)+ 每 ~12h 翻转,换手吃光,required_maker_fill ~0.93(CARRY maker 墙跨所重现)。
  **固化的研究价值**:整套反过拟合 harness(triple-barrier / purged-CV / DSR / PBO /
  effective-breadth / breadth-adjusted 要求 IC)、kill-test 方法论(最便宜的证伪优先)、以及三条
  重启线的诚实证据链——**这些是项目的真成果**。**唯一合法的下一次重启触发仍是所有者授权的结构性
  新基建**:期货券商(L1-S5,把真 edge 量级补到券商档)/ 期权场(L5 波动率变现)/ 多所账户(L4-S2
  maker 执行)——**当前一个都不追**。**这是停止投入,不放宽任何纪律**:live 仍关闭、不 forward paper、
  不放宽 broad gate、`validation_v1` once-only 资格继续保留。对账见
  [profit-engineering-plan.md](profit-engineering-plan.md) §11.8。
- **2026-06-08 重启线 L6(A股 L2 微观结构,换信息源攻 IC 项):所有者授权,主线 L6-daily,D0 完成。**
  §11.8 规定唯一合法重启是「结构性新输入」;所有者提供 A股 逐笔委托级 Level-2(Wind 三件套,
  6TB/网盘),首个真正的结构性新数据源。**日内线 Phase 1(单日 20260407,15 ETF)实测**:订单流
  IC 真高(`micro_price_dev @1m` rank-IC +0.139,符号稳)——项目首次用新数据把 IC 抬过日频 0.05
  天花板,但每个可操作档(≥1m)净收益全负(振幅 ~0.8bp < T+0 往返成本 ~5–10bp),高振幅 IC 在
  亚分钟需 co-location=慢操作者够不着(L4 延迟墙变体)。**主线转 L6-daily**(所有者选定):用 L2
  重建**日线知情流**特征预测次日/次周截面收益——成本无关(日移动 1–3% >> 10bp)、全个股截面广度
  友好(~7 >> ETF 1.7)、数据极便宜(6TB → MB 级小面板)。**D0 完成**(写日线特征+ETL+单测,单日
  全截面验证分布合理、无前视):全个股 ETL 跑两天,20260407 scored 7762/7778(99.8%)、20260408
  7714/7715(100%),五特征(`aggressive_ofi`/`large_aggr_ofi`/`late_minus_early_flow`/
  `close_auction_imbalance`/`cancel_imbalance`,全 L2 衍生、区别于已证伪的券商粗主力)分布合理
  (均值近 0、饱和率 0.3%–7.4% 且集中在低流动性微盘)。本地 363 OK + WSL 363 OK。原始 85G 经一次
  ETL 塌成日线面板(几 MB);两天各 1356 只 T+0 ETF 原始三件套归档 `~/Desktop/l6_etf_raw/`
  (日内 Phase 1/2 素材),全个股原始删除(所有者授权、网盘有备份)释放 ~63G。下一步 **D1**(生死第一
  刀,需多日数据):跨日全个股截面 rank-IC + 符号稳 + DSR/PBO + 有效广度,门控截面 IC > 0.06;
  当前仅 2 天无法测预测力,需继续攒日。**D2 增量门**:须证明对「价量动量+粗主力」有增量 IC,否则
  只是换皮重测拥挤因子。硬约束全不变,research-only、未碰 `validation_v1`、未下单。计划见
  [l6-microstructure-plan.md](l6-microstructure-plan.md) §4b。artifact
  `state/research_runs/20260608T040443Z-...` 与 `...042318Z-...`。
- **2026-06-08(续)L6 扩到 4 天 L2 + 所有者选 ETF 版 L6-daily。** L2 知情流扩到 0403/0407/0408/0409
  (清明休市除外),全个股日线 panel 四份(99.8%–100%),个股主线数据继续累积。**所有者方向:做
  ETF 版 L6-daily**(universe 换 T+0 ETF:ETF L2 知情流 → ETF 次日收益);标签 blocker 解除——panel
  自带 `day_close`,forward-return 跨天直接算,不需外部日线。ETF 管线已验证(1356 全打分),但两个
  隐忧:流动性长尾(近半成交<500 笔、竞价饱和 18–20%)+ ETF 截面广度历史 ~1.7(正是主线选全个股
  =~7 要逃的天花板);ETF 版真实权衡=**广度↓(致命) vs T+0 日内可兑现↑(个股 T+1 大半 alpha 不可
  兑现,ETF 版唯一救赎)**,生死靠活跃子集 `_panel_effective_breadth` 实测。**数据工程**:每天 38–47G
  全市场原始 → 几 MB panel;ETF 原始 4 天 21.5G 压缩 8.7%(1.87G)归档 Windows `D:\qount_l2_archive\`
  (字节+zstd 校验),全个股原始删、本地 ETF 删,Windows+网盘双备份。
- **2026-06-08(续2)L2 扩到 4 月全月 17 个连续交易日 + 全 Windows 存储。** 从 4 天扩到 **17 天**
  (0401–0424,除清明/周末),每天 panel scored 99.7%–100%。新增并行 ETL 基建(不改核心):
  `scripts/research/l6_parallel_etl.py`(multiprocessing,单天 34min→32核 ~5min)+
  `scripts/research/l6_wsl_batch.sh`(WSL 单天串行流水线,py7zr 解压→并行 ETL→xz 压缩归档→校验后
  删 .7z,幂等可重入)。跨主机:Mac 2 天 + WSL 11 天。**所有者原则「Mac 不做数据存储」已落实**:
  ETF L2 压缩归档 17 个/7.8G 全在 Windows `D:\qount_l2_archive\`(6 `.tar.zst`+11 `.tar.xz`),
  全个股 panel 17 天全在 WSL `state/research_runs/l6_daily_*`(Mac 6 天已迁入 WSL、本地删),源 .7z
  全删,Mac 纯编辑面零数据;WSL ext4 在 D 盘(372G free)。**下一步 D1 可正式做**:17 天=16 个
  T→T+1 截面(接近 20–40 天门槛),写跨日 ETF 截面 rank-IC + 符号稳 + 活跃子集 eff-breadth
  (先单测、本地→WSL),17 天 panel 已在 WSL 生产真相上可直接跑。硬约束全不变。
- **2026-06-08(续3)ETF 版 D1 跨日截面 IC kill-test:below_gate,但 close_auction 是首个真实显著
  信号。** 工具 `evaluate_l6_daily_d1` + 命令 `l6-daily-d1-scan`(local/WSL 367 OK)。17 天/16 截面
  实跑:**广度天花板经验证实**——ETF 截面 eff-breadth **1.69**(§7/L1/L3b 反复撞的 ~1.7),全个股
  **2.50**(印证主线选全个股,但 < L1 2.97)。**`close_auction_imbalance` = 项目首个真实、显著
  (t=-4.95)、符号稳(0.87)的日线 L2 信号**(收盘竞价买压→次日反转),ETF IC -0.037;按 Grinold
  breadth 1.69 → 要求 IC ≈0.049,实测 0.037=0.76×(接近不够),全个股要求 0.040/实测 0.017(广度高
  但信号弱)。四 universe 全 below_gate(DSR 0.36–0.62/PBO 0.27–0.43)。与 L3b 同型(真信号但广度封死)
  但没那么悲观:close_auction t 更硬、ETF 0.037 距要求仅 0.76×、且 **ETF T+0 可兑现**(个股 T+1 致命伤
  在 ETF 不存在)。16 天仍薄。下一步待所有者决策(攒天/D2 增量/D4 组合/深挖 close_auction/§7 停)。
- **2026-06-08(续4)D2 增量门:close_auction 在 ETF 上通过 —— 价量没有的真新信息(项目首次)。**
  工具 `evaluate_l6_daily_d2` + 命令 `l6-daily-d2-scan`(local/WSL 370 OK)。偏 rank-IC 控制 trailing
  收益(价量基线):ETF close_auction raw IC -0.036 → **控制价量后 partial IC -0.034(t-3.51)、保留
  94.6%**,价量基线自己 IC +0.019(t0.23,几乎无预测力),共线度仅 -0.04。**close_auction 是价量根本
  没有的真新信息,非换皮重测反转因子**。换信息源尝试里 L3b 信号被广度死、funding 弱,**close_auction
  是首个同过 D1(真实显著)+ D2(价量增量)的信号,核心假设「L2 真知情流 ≠ 价量」首次经验证实**。
  张力仍在:|IC| 0.036 < breadth(1.69)调整要求 0.049、14 截面偏薄。下一步待所有者决策(攒天 / D4
  多特征组合 / 深挖 close_auction 反转+ETF T+0 执行)。硬约束全不变,未碰 `validation_v1`。
- **2026-06-08(续5)D4 多特征线性组合:临界,接近但未干净突破。** 工具 `evaluate_l6_daily_d4` +
  命令 `l6-daily-d4-scan`(local/WSL 372 OK)。5 特征 z-score 符号对齐/IC 加权合成,对比广度调整要求
  `1/√(eff_breadth·250)≈0.049`:组合把信号从单 close_auction 0.036 抬到 **全体 ic_weighted 0.042
  (t4.15/sign0.81,但<0.049 且 in-sample 权重)/ 活跃top300 0.057(>0.048 破线但 t 仅 2.11)**;无
  「破线+t硬+全universe+非in-sample」四者兼得。**信号真实、组合有帮助,但量级卡在广度(1.69)要求
  0.049 临界线**,再次印证广度是绑定约束。16 截面薄、ic_weighted 需 purged-CV。下一步待所有者决策
  (攒天到~40+purged-CV / 接受临界按 §7 固化 / 深挖 close_auction+T+0 执行)。硬约束全不变。
- **2026-06-08(续6)D4 purged-CV 推翻 in-sample:组合提升是过拟合。** 给 D4 加 `--purged-cv`
  (leave-one-section-out+embargo)。WSL 实跑:**所有配置 OOS composite IC 崩到 ~0 甚至翻负**——ETF
  全体 ic_weighted in-sample 0.042(t4.15)→ **OOS -0.004(保留比 -0.09)**;sign_equal/top300 OOS 均
  翻负。**in-sample 0.042-0.057 几乎全是 16 截面权重选择的过拟合假象**(反过拟合 harness 的价值)。
  **修正净结论**:单 close_auction 真实(D1/D2 无权重选择)但量级 0.036<0.049;D4 组合救不了(引入
  权重选择即过拟合、OOS 崩);绑定约束仍是广度,组合突破这条路在现有数据上关闭。下一步待所有者决策
  (攒天到~40 / 深挖 close_auction 单信号+ETF T+0 执行 / 接受按 §7 同型固化停)。硬约束全不变。
- **2026-06-09 L2 数据从 17 天扩到 53 天(2/3/4 月)——D1「16 截面偏薄」解除。** 隔夜跑批管线
  (`scripts/research/l6_pipeline.sh`,external 消费模式)收下 2/3/4 月连续交易日,全个股日线 panel
  落 WSL `state/research_runs/l6_daily_*`,每天 scored 99.7%–100%。两个坏文件单独处理:**20260311**
  原 .7z 损坏(`LZMAError`)、重下后 DONE(scored 7487);**20260210** 是合法低标的日(稳定 5178,
  邻日 ~7500;ETF 归档空 116B=该日几无 T+0 ETF),加白名单 `LOW_OK_DATES` 放行、DONE。**panel 总数
  = 53 天 → D1 有 52 个 T→T+1 截面,远超 20–40 门槛**;之前续3–续6 的 D1/D2/D4 结论都建在 16 截面上,
  现在 close_auction 单信号(D1/D2 真实但量级 0.036<广度要求 0.049)与 D4 purged-CV 可在厚样本上正经
  重跑——这是下一步(尚未重跑)。**管线加固(只改运维脚本、不碰 `l6_microstructure.py`)**:四个失败
  分支(extract/etl/scored<6000/xz)从「原地留 .7z」改成移入 `$SRCDIR/_bad/`,根除坏文件让
  `processor` `while true` 死循环空转的 bug;新增 `LOW_OK_DATES` 低标的日白名单跳过 <6000 守卫。
  **运维坑(记 quick-handoff)**:`ssh → wsl.exe bash -lc 'tmux ...'` 起的后台进程不持久(ssh 一返回
  WSL 即回收),可靠做法是**前台阻塞跑**(ssh 全程挂着 = WSL 不回收)。硬约束全不变,research-only、
  未碰 `validation_v1`、未下单。
- **2026-06-09 L6 厚样本重测 + close_auction T+0 执行实测 → 撞回 maker 墙,所有者授权 L6 同型固化止盈。**
  ① **52 天 D1/D2/D4 重跑**:加厚样本把 close_auction 信号打回——ETF D1 IC 从 17 天 0.037 缩到 **0.021
  (t−3.38,符号 0.69)**,距广度要求(eff-breadth 1.85→0.046)从 0.76× 退到 **0.44×**;D2 增量仍过
  (控制价量后 partial 保留 103%,确属价量正交的真新信息);D4 组合 OOS(purged-CV)崩到 0.006/翻负。
  广度墙(~1.85)未动、信号离它更远。② **换问题做执行线 B**(`evaluate_l6_t0_execution` + 命令
  `l6-t0-exec-scan`,绕开 IR=IC√BR 截面下界):信号在 T 收盘竞价测得、最早 T+1 开盘可动 → 唯一可兑现
  是 T+1 open→close 日内 T+0。**把次日反转拆成隔夜/日内/收收**:发现 **收盘竞价买压→隔夜跳空续涨
  (IC+0.045/t8.5)→日内反转(IC−0.029/t4.5)**,D1 的 close-to-close(−0.019)是两段反向力量的净残值;
  `capturable_frac≈2`(只吃日内 T+0 比持有过夜好一倍,隔夜那段反向)。③ **实测成本定生死**(给特征加
  `day_open`/`quoted_spread_bps`、重 ETL 46 天 ETF panel):日内 gross +7.6~9.9bp(t>2.4)真实,但
  **交易尾价差 ~13–14bp → taker 往返成本 ~31bp → net −23bp(t−7),taker 彻底死**;唯一"幸存"的竞价
  撮合(仅佣金)net +2.6/+4.9bp 但 **t<1.3 不显著**。**价差-信号陷阱**:信号活在不流动 ETF(强尾价差
  14.4bp/gross+9.9bp),一上流动 top100(价差 5.7bp)信号塌成 +2.3bp/t0.26——**edge 本质是薄 ETF 的
  流动性提供溢价,taker 拿不走;要拿只能做 maker = L4/§3-Phase4 的 maker 墙**。④ **净结论**:close_auction
  是项目迄今最干净的信号(真实+显著+价量正交+隔夜/日内结构清楚),但不可 taker 兑现、edge=流动性溢价、
  收敛到已知撞死的 maker 墙。**所有者授权 A:B 诚实止盈、L6 与 §7/L1/L3b/L4 同型固化**(stop investing,
  不放宽任何纪律:live 关闭、不 forward paper、不放宽 broad gate、`validation_v1` once-only 保留)。
  沉淀=D0–D4 + T0 隔夜/日内分解 + 实测 taker/auction 成本的反过拟合 harness。artifact
  `state/research_runs/20260609T065032Z/065033Z-l6-t0-exec-scan`。计划见
  [l6-microstructure-plan.md](l6-microstructure-plan.md) §5。

