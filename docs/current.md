# qount 当前状态

更新时间：2026-05-26

当前版本：`0.2.0`

这份文档只保留当前决策状态。操作细节、接手命令、PowerShell / WSL 坑点写在
[quick-handoff.md](quick-handoff.md)。

不要把旧的 after2 / after4 / hard-reclaim 历史当成当前计划。需要历史证据时看
`git log`、旧 artifact、或 `quick-handoff.md` 里列出的当前关键 artifact。

## 当前结论

- 生产真相仍是 WSL：`/home/alyaloale/Code/qount`。
- Mac：`/Users/alyaloale/Code/qount`，作为编辑面和 git 工作区。
- live 继续关闭：`QOUNT_LIVE_ENABLE=false`。
- 远端 `qount-runner.timer` / `qount-runner.service` 仍为 `inactive`。
- 当前没有实盘开放仓位；上一轮 `dashboard-snapshot --include-exchange` 读回 `account_overview.positions=[]`。
- 当前研究主线是 `ETH-only`，入口必须显式使用 `--research-profile eth-only`。
- 最新完整 6-window chronological walk-forward 仍未过 promotion gate；不能 forward paper / live。

当前策略状态不是“马上上线”，而是：

```text
ETH-only research-only
bottom_line + future + ETH/USDT + 1 position
hourly model off
setup model phase6 on
live disabled
```

## 生产与运行状态

最近 WSL `.env` 读回：

```text
QOUNT_MODE=live
QOUNT_MARKET_TYPE=future
QOUNT_RULE_MODE=bottom_line
QOUNT_LIVE_ENABLE=false
QOUNT_SYMBOLS=SOL/USDT,XRP/USDT,BTC/USDT,ETH/USDT
QOUNT_MAX_OPEN_POSITIONS=3
QOUNT_CONTRACT_LEVERAGE=6
HTTP_PROXY=http://192.168.128.1:7907
HTTPS_PROXY=http://192.168.128.1:7907
```

注意：

- `.env` 仍是旧的 4-symbol live 形状，不是研究证明口径。
- 研究和回测必须用 `--research-profile eth-only` 覆盖 `.env`。
- WSL 跑 Binance / backtest / walk-forward 前必须 `source .env`，否则代理不会生效，容易报 `Network is unreachable`。
- WSL 目录不保证有 `.git`；git 状态以 Mac 工作区为准。

最近 `runtime-status`：

```json
{
  "mode": "live",
  "exchange_id": "binance",
  "market_type": "future",
  "quote_currency": "USDT",
  "halted": false,
  "ai_failure_streak": 0,
  "day_start_equity_key": "day_start_equity:live:binance:future:USDT:2026-05-26",
  "day_start_equity": null
}
```

## ETH-only 标准口径

使用：

```bash
python -m qount.main backtest --research-profile eth-only ...
python -m qount.main train-setup-model --research-profile eth-only ...
python -m qount.main walk-forward --research-profile eth-only --window ...
```

`eth-only` profile 当前等价于：

```text
market_type=future
live_enable=false
rule_mode=bottom_line
symbols=ETH/USDT
max_open_positions=1
hourly_model_enable=false
setup_model_enable=true
setup_model_path=state/models/setup_edge_model_short_rebound_phase6.json
setup_model horizon_bars=6
setup_model split_higher_phase=true
trailing_profit_arm_pct=0.0018
trailing_profit_retrace_pct=0.003
```

风险管理里还有一个更窄的 ETH reclaim short effective retrace：

```text
ETH_RECLAIM_SHORT_TRAILING_PROFIT_RETRACE_PCT=0.0008
```

这个只对 `ETH/USDT:USDT + short + higher_timeframe_phase=reclaim + setup_phase=short_rebound_fail_confirmed` 的已有仓位生效。

## 最新验证结果

### 代码验证

本地：

```text
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
164 tests OK
```

WSL：

```text
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
164 tests OK
```

### trailing peak 修复

修复点：

- 文件：`src/qount/risk_engine.py`
- 函数：`_should_force_trailing_profit_close`
- 问题：第一次达到 trailing arm 后，如果 peak 没有高于默认值，旧逻辑不会把 peak 写入 `runtime_state`。
- 后果：下一根回撤时会把当前低值当成新 peak，导致 tight retrace 不触发。
- 修复：首次 `stored_peak is None` 且 `peak_return_pct >= trailing_profit_arm_pct` 时立即落库。

新增回归测试：

- `test_risk_engine_persists_initial_trailing_peak_before_retrace`
- `test_risk_engine_uses_tighter_retrace_for_eth_reclaim_short`

### targeted 两窗

Artifact：

```text
/tmp/qount-wf-eth-range-reclaim-local-breakdown-arm018-2w-rerun-20260526T1538Z
```

结果：

| window | paper filled/closed | realized_return_pct | review_avg_net_edge_pct | open_positions |
| --- | ---: | ---: | ---: | ---: |
| wf-mar06 | 2 / 3 | +1.4803231765% | +0.0738814176 | 0 |
| wf-apr15 | 1 / 1 | +0.0680570422% | +0.0532214651 | 0 |

`apr15` 的关键行为变化：

- 旧结果：`run 79/80` 都 hold，`run 81` close，最终 `-0.1136873727%`。
- 新结果：`run 79` 写入 `trailing_profit_peak` 并刷新 trailing stop。
- 新结果：`run 80` 触发 `management_trailing_profit_retrace:0.000945|peak=0.001826|retrace=0.000880`。
- 新结果：`run 80` close 后单笔盈利，targeted `apr15` 转正。

### 完整 6-window

Artifact：

```text
/tmp/qount-wf-eth-range-trailing-peak-persist-6-20260526T1545Z
```

汇总：

```text
oos_safe_windows=6/6
positive_realized_windows=2/6
windows_with_open_positions=0
total_paper_filled=4
total_paper_closed=5
sum_realized_return_pct=+1.2430423825%
avg_realized_return_pct=+0.2071737304%
```

逐窗：

| window | paper filled/closed | realized_return_pct | review_avg_net_edge_pct | blockers |
| --- | ---: | ---: | ---: | --- |
| wf-feb27 | 0 / 0 | 0.0% | 0.0 | non_positive_realized_return, non_positive_review_edge |
| wf-mar06 | 2 / 3 | +1.4803231765% | +0.0738814176 | none |
| wf-mar11 | 1 / 1 | -0.2939949958% | -0.0319788034 | non_positive_realized_return, non_positive_review_edge |
| wf-apr15 | 1 / 1 | +0.0567142019% | +0.0532214651 | none |
| wf-may06 | 0 / 0 | 0.0% | 0.0 | non_positive_realized_return, non_positive_review_edge |
| wf-may23 | 0 / 0 | 0.0% | null | non_positive_realized_return |

读法：

- `mar06` 仍是主正收益窗。
- `apr15` 已由 trailing peak persistence 修复转正。
- `mar11` 仍是明确亏损窗，下一步若继续研究，应优先查这个窗口。
- `feb27 / may06 / may23` 仍是 0 交易或非正窗口，不能用“没亏”当 promotion 证据。
- 当前完整 6-window 仍没有足够覆盖，不能进入 forward paper / live。

## 当前代码边界

保留：

- `--research-profile eth-only`
- `walk-forward` 按窗口训练 setup model，并保留原始模型文件名 `setup_edge_model_short_rebound_phase6.json`
- review 写入 `candidate_direction`、`candidate_aligned_future_return_pct`、`missed_candidate_move`
- ETH fresh long veto：只在 short-rebound 研究口径下挡 `ETH` fresh buy
- ETH weak reclaim short gate：挡 `ETH + short_rebound_fail_confirmed + reclaim + trend_strength<2.0` 且没有强 reclaim bonus / local breakdown pressure 的 fresh short
- ETH reclaim short tight trailing retrace
- trailing peak 首次达到 arm 后立即落库

不要做：

- 不要打开 live。
- 不要把 `.env` 的 4-symbol live 形状当研究口径。
- 不要恢复 broad `short_continuation_confirmed`。
- 不要宽泛放开 `short_rebound_fail_confirmed / pullback` fresh entry。
- 不要把 `0/0` 当成盈利晋级。
- 不要只看 `total_return_pct`；优先看 `realized_return_pct / open_unrealized_pnl_quote / open_positions`。
- 不要在同一轮同时改 entry、management、setup model、prompt；否则结果不能作为晋级证据。

## 下一步

如果继续研究，优先做：

1. 读最新 6-window artifact 的 `wf-mar11`：
   - `/tmp/qount-wf-eth-range-trailing-peak-persist-6-20260526T1545Z/03-wf-mar11`
   - 目标是确认亏损单的 entry thesis、risk reasons、管理退出时点。
2. 只提出一个窄 hypothesis。
3. 先写单测，再跑 targeted `mar11 + mar06 + apr15`。
4. targeted 通过后再跑完整 6-window。
5. 更新本文件和 `quick-handoff.md`。

当前不能做：

```text
forward paper
small live
multi-symbol live
position sizing increase
```

## 快速接手入口

接手模型先读：

1. 本文件。
2. [quick-handoff.md](quick-handoff.md)。
3. `git status --short --branch`。
4. WSL `runtime-status` 和 `.env` 读回。

详细命令和坑点不要再写进本文件，统一放在 `quick-handoff.md`。
