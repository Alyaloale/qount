# qount 当前状态

更新时间：2026-05-31

当前版本：`0.2.0`

这份文档是当前事实入口，只保留结论、能力边界和下一步。接手命令看
[quick-handoff.md](quick-handoff.md)，发现/验证边界看
[holdout.md](holdout.md)，长证据链看 [update-log.md](update-log.md)，架构评审和路线看
[optimization-plan.md](optimization-plan.md)，历史盈利研究路线看
[profit-research-plan.md](profit-research-plan.md)。

## 当前结论

```text
ETH-only research-only
bottom_line + future + ETH/USDT + 1 position
hourly model off
setup model phase6 on
live disabled
```

- 生产真相仍是 WSL：`/home/alyaloale/Code/qount`。
- Mac 工作区是编辑和 git 表面：`/Users/alyaloale/Code/qount`。
- live 继续关闭：`QOUNT_LIVE_ENABLE=false`；`live-guard-status` 当前 `ok=false`，
  `reason=live_disabled`。
- `qount-runner.timer` / `qount-runner.service` 当前不应自动跑；最近读回为 inactive。
- 当前没有 promotion 证据，不能 forward paper，也不能 live。
- 旧 13-window 结果现在只能作为 discovery 证据；promotion 只看
  `holdout_role=validation_v1` 的 once-only 新窗口。

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
- Mac 到 WSL 同步与测试脚本：`scripts/sync-to-wsl.sh`、`scripts/run-wsl-tests.sh`。

当前还不具备：

- 稳定盈利能力证明。
- forward paper 许可。
- live 许可。
- 可复用的窄 candidate gate。
- 已验证的 AI prompt v2/v3 改进。
- 多币 promotion gate。
- Kronos 接入候选层或执行层。

## 最新策略读数

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

## 代码结构

- `src/qount/settings.py`：运行配置与研究开关。
- `src/qount/research_profile.py`：`eth-only` / `multi-symbol` profile 覆盖。
- `src/qount/main.py`：CLI 入口。
- `src/qount/backtest.py`、`src/qount/walk_forward.py`：端到端研究执行。
- `src/qount/setup_model.py`：setup edge 模型、target slice、setup-edge walk-forward。
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

最近一次完整结果：本地 211 OK，WSL 211 OK。若本文件被后续提交更新，以提交前实际输出为准。

## 下一步

按 ROI 排序：

1. T-B：量化 AI hold-bias，冻结 prompt v2/v3 假设，只在 `validation_pool_v1` once-only 验证。
2. T-C：`setup_model` v2，加入 phase × bin 交互和 per-phase ridge；先做 calibration / lift。
3. T-G：0 交易窗口诊断，输出 setup 预测分布和 candidate 拒绝原因直方图。
4. T-E：把 5 条窄 ETH gate 集合化，测试从 fixture 回到 axis spec。
5. T-F：隔离 `Settings` / `ResearchSettings`，live 入口拒收 research-only 配置。
6. T-H：多币 paper-only 独立 track，不与 ETH-only 共用 promotion gate。
7. T-I：Kronos 只做 offline overlay，且只在 T-C 证明 v2 不优于 v1 后启动。

硬边界：

- 不开 live。
- 不 forward paper。
- 不把 `discovery_pool` 窗口当 validation。
- 不放宽 broad `range_noise` / `short_rebound_fail`。
- 不把 `offline_future_edge_readiness` 当 promotion 证据。
- 不把 Kronos 接入 candidate / risk / live。
