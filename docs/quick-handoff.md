# qount 快速接手手册

更新时间：2026-06-05

当前版本：`0.2.0`

这份文档给接手的大模型用，只放可执行入口、跨主机命令和容易踩坑的边界。当前结论看
[current.md](current.md)，证据长链看 [update-log.md](update-log.md)，架构路线看
[optimization-plan.md](optimization-plan.md)。

## 文档地图

- [current.md](current.md)：当前事实、能力边界、下一步。
- [holdout.md](holdout.md)：`discovery_pool` / `validation_pool_v1` 和 `G_paper` / `G_live`。
- [quick-handoff.md](quick-handoff.md)：接手命令和运维坑点。
- [update-log.md](update-log.md)：近期 artifact、验证结果、读法。
- [optimization-plan.md](optimization-plan.md)：2026-05-31 架构评审和 T-A..T-J 路线。
- [profit-research-plan.md](profit-research-plan.md)：盈利研究历史路线；旧 G1/G2 已被
  [holdout.md](holdout.md) 取代。
- [profit-engineering-plan.md](profit-engineering-plan.md)：2026-06-05 终审后的盈利工程
  主线；落地以 §10 的 S0 -> S1' -> S-CARRY 或 S2/S3 分叉为准。

## 第一原则

- Mac 是编辑和 git 工作区：`/Users/alyaloale/Code/qount`。
- WSL 是生产和回测真相：`/home/alyaloale/Code/qount`。
- WSL 目录不一定有 `.git`，不要用 WSL `git status` 判断提交状态。
- live 必须保持关闭：`QOUNT_LIVE_ENABLE=false`。
- 不要启动 `qount-runner.timer`，除非当前 promotion gate 已通过且用户明确要求。
- WSL 跑联网命令前必须 `source .env`，否则代理不会生效。
- 当前有效 AI 模型是 `QOUNT_AI_MODEL=gpt-5.5`；`gpt-5.4` 会导致当前 relay 502 / 全 hold。
- ETH-only 主线必须显式加 `--research-profile eth-only`。
- 已看过窗口只算 `discovery_pool`；新 promotion 证据必须是 `validation_v1` once-only。
- 当前盈利工程主线不是继续默认 5m 调参，而是先跑 S1' 频段 × 策略族选择扫描。

## 当前状态检查

先在 Mac 看工作区：

```bash
cd /Users/alyaloale/Code/qount
git status --short --branch
```

再从 Mac 查 WSL 运行状态：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF'
cd /home/alyaloale/Code/qount || exit 1
printf '%s\n' '--- env ---'
grep -E '^(QOUNT_MODE|QOUNT_MARKET_TYPE|QOUNT_RULE_MODE|QOUNT_LIVE_ENABLE|QOUNT_SYMBOLS|QOUNT_CONTRACT_LEVERAGE|QOUNT_MAX_OPEN_POSITIONS|QOUNT_AI_MODEL|HTTP_PROXY|HTTPS_PROXY)=' .env || true
printf '%s\n' '--- systemd ---'
systemctl --user is-active qount-runner.timer qount-runner.service || true
printf '%s\n' '--- runtime ---'
set -a
source .env
set +a
./.venv/bin/python -m qount.main runtime-status | python3 -m json.tool
printf '%s\n' '--- live guard ---'
./.venv/bin/python -m qount.main live-guard-status | python3 -m json.tool
EOF
```

常见读法：

- `live-guard-status ok=false reason=live_disabled` 是当前正确状态。
- `.env` 仍可能是旧 4-symbol live 形状；研究读数不要继承它。
- `Network is unreachable` 多数是 WSL 没 `source .env` 或代理不通。

如果 WSL 报 `binance GET https://fapi.binance.com/fapi/v1/exchangeInfo` 且代理是
`192.168.128.1:7907` 超时，先从 Mac 恢复 Windows 侧 qount 专线：

```bash
ssh -o ClearAllForwardings=yes home 'powershell.exe -NoProfile -Command -' <<'EOF'
Start-ScheduledTask -TaskName QountBinanceProxy
Start-Sleep -Seconds 6
Get-ScheduledTask -TaskName QountBinanceProxy | Select-Object TaskName,State
Get-NetTCPConnection -LocalPort 7907 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,State,OwningProcess
EOF
```

再从 WSL 复测：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF'
(timeout 5 bash -lc 'cat </dev/null >/dev/tcp/192.168.128.1/7907') >/dev/null 2>&1 &&
  echo 'wsl_7907_tcp=ok' || echo 'wsl_7907_tcp=fail'
curl -sS --max-time 12 --proxy http://192.168.128.1:7907 \
  https://fapi.binance.com/fapi/v1/time
EOF
```

2026-06-04 已验证：`QountBinanceProxy` 任务启动后由 `verge-mihomo.exe` 监听 7907，
WSL 代理访问 Binance futures public API 恢复。

## 本地与 WSL 验证

本地测试：

```bash
cd /Users/alyaloale/Code/qount
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
```

research ML 依赖检查：

```bash
./.venv/bin/python -m pip install -e '.[research]'
PYTHON_BIN=./.venv/bin/python ./scripts/check-research-deps.sh
```

读法：`numpy` / `sklearn` 必须 ok；`lightgbm` 是可选项。当前 Mac 上 LightGBM wheel
可安装但 import 缺 `libomp.dylib`，所以后续默认用 sklearn `HistGradientBoosting`。

S1' 频段 × 策略族 discovery 扫描：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF'
set -euo pipefail
cd /home/alyaloale/Code/qount
set -a
source .env
set +a
./.venv/bin/python -m qount.main strategy-selection-scan \
  --research-profile multi-symbol \
  --families xs_mom xs_rev ts_mom carry \
  --frequencies 5m 1h 4h 1d \
  --lookback-days 30 \
  --signal-lookback-bars 12 \
  --holding-bars 1 \
  --output-path /tmp/qount-strategy-selection-s1-30d-20260605.json
EOF
```

读法：命令只拉 discovery 历史 OHLCV / funding 并写 artifact，不调用 AI、不执行订单。
2026-06-05 初扫 top cell 是 `1d ts_mom`，但 rank-IC 很弱、有效广度约 1.13；
5m `xs_rev` 有正 IC 但 post-cost 大幅为负，不能 promotion。

120 天 sanity 结论：`1d ts_mom lb12/h1` 从 30 天正收益变成
`sum=-0.3885499348`、`sharpe=-0.4637426827`；月度切分里 2026-03 和
2026-04 都显著为负，不能进入 S2/S3。5m / CARRY 在 zero-cost 下转正，但
maker-ish `cost_per_directional_bet=0.0004` 后分别变成
`5m_xs_rev_sum=-26.4101457512`、`carry_sum=-0.0999394`。

2026-06-05 已补 OHLCV 列回归测试并在 WSL 复跑同一 120 天核心扫描，结论不变：
artifact 前缀为 `20260605T071948Z...ohlcv-rerun...`、`20260605T072101Z...zero-cost-ohlcv-rerun...`、
`20260605T072410Z...maker-ish-ohlcv-rerun...`。

S-CARRY 第一版 `threshold_dual_leg` 已接入显式 research 参数，默认 naive carry 不变。
120 天 4 币、entry `0.00008`、exit `0.00004`、min hold 3：
zero-cost `sum=+0.04728436`；maker-ish `cost_per_directional_bet=0.0004` 后
`sum=-0.16871564`，不能 paper。

固定 grid 已跑：entry `0.00004/0.00008/0.00012` × exit `0.00002/0.00004` ×
min-hold `1/3/6`。zero-cost best `sum=+0.07147182`，maker-ish best
`sum=-0.02967449`、entry `0.00012`、exit `0.00002`、min-hold `6`、
utilization `0.2708`、双腿平均 gross exposure `0.5417`。funding history 没有可用
mark/index，`basis_sample_count=0`。本地 / WSL 全量测试均为 `228 OK`。

`--carry-basis-source premium_index` 已接通 Binance 8h premium index kline。同一 fixed grid
maker-ish 复跑 artifact：
`/home/alyaloale/Code/qount/state/research_runs/20260605T083154Z-strategy-selection-scan-qount-strategy-selection-s-carry-fixed-grid-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-fixed-grid-premium-basis-maker-ish-20260605.json`。
结果：每币 361 根 premium bars，best 仍 `sum=-0.02967449`；basis `sample_count=390`、
avg abs `0.0005576725`、max abs `0.00143783`。本地 / WSL 全量测试均为 `229 OK`。

top12 universe 已完成同一 fixed grid + premium basis 扩币读数：

```text
symbols=BTC/ETH/ZEC/SOL/HYPE/WLD/XRP/BNB/NEAR/DOGE/ADA/SUI USDT perpetuals
maker_ish_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083609Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605/qount-strategy-selection-s-carry-top12-premium-basis-maker-ish-20260605.json
maker_ish_best=sum -0.07594874, entry 0.00012, exit 0.00002, min_hold 6, turnover 221
zero_cost_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T083859Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605/qount-strategy-selection-s-carry-top12-premium-basis-zero-cost-20260605.json
zero_cost_best=sum +0.27826189, entry 0.00004, exit 0.00002, min_hold 1, turnover 2104
```

读法：top12 zero-cost 证明 gross carry cashflow 变厚，但 maker-ish 成本后仍没有正 cell；WLD
是 maker-ish best cell 里唯一单币正贡献。下一步不要继续在同一 discovery grid 上挑阈值，
要转向 explicit hedge / spot-perp 双腿 replay、post-only 成交率、资金占用和 basis 风险。

`--carry-execution-cost-model per_order` + `--carry-capital-model spot_perp_gross` 已接入，
用于 explicit spot/perp 双腿资金占用读数；默认旧口径不变。top12、6x perp margin fraction
`0.1666667` 复跑：

```text
explicit_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-20260605.json
order_cost=0.0002
best=sum +0.0106725083, entry 0.00012, exit 0.00002, min_hold 6, turnover 221
gross_funding=+0.0864439347
execution_cost=+0.0757714264
break_even_order_cost=0.0002281703
positive_cells=3/18
cost025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T085742Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-gross-cost025-20260605.json
order_cost=0.00025
best=sum -0.0082703483
```

读法：出现小正候选，但成本缓冲很窄，basis max abs `0.00265777` 大于净收益边际；
仍不能 paper。下一步先做 post-only 成交率 / 实测订单成本 / basis tail 压力，不要把
discovery best cell 当 promotion。

`strategy-selection-scan` 已支持 `--holdout-role`。固定 top12 explicit spot/perp best cell
跑了新的 1 天 `validation_v1` sanity：

```text
val_jun04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103552Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-20260605.json
window=2026-06-04T00:00:00Z..2026-06-05T00:00:00Z
order_cost=0.0002
sum=+0.0003597343
break_even_order_cost=0.0002524613
basis_max_abs=0.00235832
val_jun04_cost025_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T103620Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-cost025-20260605.json
order_cost=0.00025
sum=+0.0000168771
```

读法：新窗口没有立即证伪，但只有 1 天 / 51 funding samples / 4 entry events，成本压力后
几乎贴着 break-even；仍不能 paper。

同一 fixed-cell 已补 basis-tail 诊断复跑：

```text
val_jun04_basis_tail_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T104512Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-basis-tail-20260605.json
sum=+0.0003597343
basis_max_abs=0.00235832
basis_single_tail_loss_on_capital=0.0020214171
basis_single_tail_to_net_ratio=5.6191951202
portfolio_sum_after_single_basis_tail=-0.0016616828
```

读法：当前 1 天 fixed-cell 的小正收益被单次 basis tail 压力抹掉后转负；basis-tail 已经是
paper blocker。下一步不是 promotion，而是补 post-only fill / 实测订单成本，以及
basis-tail-aware hedge / exit 模型。

simple basis tail stop 已补为显式 research-only 参数 `--carry-basis-tail-stop-pct`，默认
不改变旧 artifact。已在同一 1 天 fixed-cell 上测试三个阈值：

```text
stop001_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105545Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop001-20260605.json
stop=0.0010 sum=-0.0008075743 basis_tail_stop_events=2 after_tail=-0.0015092057

stop0015_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105616Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00015-20260605.json
stop=0.0015 sum=-0.0004218600 basis_tail_stop_events=1 after_tail=-0.0013877828

stop0020_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T105622Z-strategy-selection-scan-qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605/qount-strategy-selection-s-carry-top12-explicit-spot-perp-val-jun04-tail-stop00020-20260605.json
stop=0.0020 sum=-0.0004218600 basis_tail_stop_events=1 after_tail=-0.0013877828
```

读法：simple hard stop 降低了最大 basis 暴露，但退出成本和少收 funding 后都转负；
不要继续在这个 1 天窗口调 stop 阈值。

只读 `execution-cost-audit --limit 200` 只有 4 笔历史 live 市价单可分析，fee 缺失；
`p50_abs_slippage_pct=0.0440920717%`，已经高于当前 fixed-cell 假设的 `0.0200%`
per-order。

按 120 天 discovery 逐币贡献，`WLD/SOL/ZEC` 为正，但 ZEC 的 after-tail 为负；tail-aware
过滤后只保留 `WLD/SOL`：

```text
wld_sol_discovery=/home/alyaloale/Code/qount/state/research_runs/20260605T110031Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-20260605.json
sum=+0.0378574446
after_tail=+0.0355793561
break_even_order_cost=0.0006330100

wld_sol_val=/home/alyaloale/Code/qount/state/research_runs/20260605T110033Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-20260605.json
sum=+0.0000535886
after_tail=-0.0006480428
break_even_order_cost=0.0002312600

wld_sol_val_cost025=/home/alyaloale/Code/qount/state/research_runs/20260605T110109Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000025-20260605.json
order_cost=0.00025
sum=-0.0000321257

wld_sol_val_cost045=/home/alyaloale/Code/qount/state/research_runs/20260605T110114Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605/qount-strategy-selection-s-carry-wld-sol-valjun04-cost000045-20260605.json
order_cost=0.00045
sum=-0.0003749828
```

读法：WLD/SOL 是最像样的 filter，但 1 天 sanity 对 basis tail 和成本都不过关；不能 paper。

WLD/SOL 月度 discovery 复核：

```text
feb=/home/alyaloale/Code/qount/state/research_runs/20260605T111620Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-feb-20260605/qount-strategy-selection-s-carry-wld-sol-feb-20260605.json sum=+0.0040478056 after_tail=+0.0028153799
mar=/home/alyaloale/Code/qount/state/research_runs/20260605T111622Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-mar-20260605/qount-strategy-selection-s-carry-wld-sol-mar-20260605.json sum=+0.0028695942 after_tail=+0.0017230457
apr=/home/alyaloale/Code/qount/state/research_runs/20260605T111625Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-apr-20260605/qount-strategy-selection-s-carry-wld-sol-apr-20260605.json sum=+0.0190945623 after_tail=+0.0168164738
may=/home/alyaloale/Code/qount/state/research_runs/20260605T111627Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-may-20260605/qount-strategy-selection-s-carry-wld-sol-may-20260605.json sum=+0.0119759397 after_tail=+0.0104161540
```

6 月已看/partial 读数：

```text
jun01_04=/home/alyaloale/Code/qount/state/research_runs/20260605T111629Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-20260605.json sum=+0.0003015686 after_tail=-0.0004000628
jun05_partial=/home/alyaloale/Code/qount/state/research_runs/20260605T111654Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-20260605.json holdout_role=unknown sum=-0.0002471743 after_tail=-0.0003076628
```

读法：2-5 月 discovery 支持 WLD/SOL filter，但 6/1-6/5 不支持 promotion；等新的完整独立
日期，或先解决 maker/post-only 成本。

用户要求不等新完整日期后，已补 post-only economics 诊断，只算所需 maker fill rate，不改
PnL。参数：`--carry-maker-order-cost-pct 0 --carry-taker-order-cost-pct 0.00045`。

```text
wld_sol_discovery_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113704Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-discovery120d-postonly-econ-20260605.json
after_tail=+0.0355793561
required_maker_fill_after_tail=0.0

wld_sol_jun01_04_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113706Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun01-04-postonly-econ-20260605.json
after_tail=-0.0004000628
required_maker_fill_after_tail=1.0741555556

wld_sol_jun05_partial_postonly=/home/alyaloale/Code/qount/state/research_runs/20260605T113709Z-strategy-selection-scan-qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605/qount-strategy-selection-s-carry-wld-sol-jun05-partial-postonly-econ-20260605.json
holdout_role=unknown
after_tail=-0.0007569857
required_maker_fill_after_tail=1.0461944444
```

读法：成本不是唯一问题；6/1-6/5 after-tail 为正需要超过 100% maker fill，数学上不可行。

WLD/SOL basis-entry regime filter 已做完，不要重复当下一刀。新参数只影响 research scan：
`--carry-basis-entry-max-abs-pct` 会在新 CARRY 入场时过滤 abs(basis) 过大的 funding period；
默认关闭，不影响 live / `run-once`。已测阈值：

```text
basis_entry_max_abs=0.0008 discovery120d sum=-0.0066684341 after_tail=-0.0083560026
basis_entry_max_abs=0.0010 discovery120d sum=-0.0010824000 after_tail=-0.0028620256
basis_entry_max_abs=0.0015 discovery120d sum=+0.0020099742 after_tail=+0.0002303486
jun01_04 all thresholds sum=-0.0003841457 after_tail=-0.0010857771 required_maker_after_tail=1.0741555556
```

读法：0.0008 / 0.0010 在 120 天 discovery 已负；0.0015 只剩极薄正收益，且 6/1-6/5
完全不改善。entry-only basis filter 当前是 rejected/diagnostic，不是 paper 候选。

1d TS-MOM top12 扩币也已跑，不要把它当新候选：

```text
top12_120d=/home/alyaloale/Code/qount/state/research_runs/20260605T114959Z-strategy-selection-scan-qount-strategy-selection-s1-tsmom-top12-120d-20260605/qount-strategy-selection-s1-tsmom-top12-120d-20260605.json
sum=-2.6698947371
sharpe=-0.7852540386
rank_ic=-0.0517447570
effective_breadth=1.4732977614
feb_sum=-0.9962962887
mar_sum=-1.0361457305
apr_sum=-1.2542758681
may_sum=+0.7414512205
```

读法：top12 扩币后 1d TS-MOM 仍是 5 月单月贡献，2/3/4 月全负，不能进 S1.1/S1.2。

低频多 horizon prediction-family 网格已跑，这是当前最新主动推进方向。新参数：
`--signal-lookback-grid-bars` / `--holding-grid-bars`，只影响 `strategy-selection-scan`
预测族；`--directional-overlap-mode all|stride` 用于降低 overlapping holding horizon 膨胀；
`--directional-evaluation-mode portfolio_replay` / `--directional-max-open-positions` 用于限仓
组合 replay；`--directional-exit-mode triple_barrier` / `--directional-take-profit-pct` /
`--directional-stop-loss-pct` 用于 OHLC intrabar TP/SL barrier 复核；
`--directional-barrier-vol-lookback-bars` / `--directional-take-profit-sigma` /
`--directional-stop-loss-sigma` 用于波动率缩放 barrier(σ 缩放 TP/SL,防泄漏,默认关闭,
已证最佳仍跑不赢无 barrier 持有到期,不要重复);
`--directional-regime-min-dispersion-pct` 用于 entry 侧 regime dispersion 门(各币 signal
离散度低于阈值就跳过该 bar,纯决策时点,默认关闭;`thr0.034` 已证能把 3 月翻正且不降总收益,
下一刀只把它固定留到新完整 OOS once-only 复核,不要在已看窗口再调阈值)。这些参数默认不变，
不影响 live / `run-once`。scan 顶层还会输出 `directional_deflated_sharpe`(DSR) 与
`directional_pbo`(PBO/CSCV,按频段分组)两类多重检验惩罚;注意选出候选的 81-cell 网格
DSR ≈ 0.082(量级不显著)、pbo 4h=0.020/1h=0.056/1d=0.214(弱信号排名稳定但量级太弱),
进 S2 前必须有可接受 DSR/PBO。top12 低频网格：
`1h/4h/1d` × `xs_mom/xs_rev/ts_mom` × lookback `3/12/24` × holding `1/3/6`。

```text
lowfreq_grid=/home/alyaloale/Code/qount/state/research_runs/20260605T121551Z-strategy-selection-scan-qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605/qount-strategy-selection-s1-lowfreq-top12-lb3-12-24-h1-3-6-20260605.json
best=4h xs_mom lookback=24 holding=6
sum=+3.5251307739
sharpe=+7.1555415974
rank_ic=+0.0523457125
top2=4h xs_mom lookback=12 holding=6 sum=+3.2301871618
top3=1d xs_mom lookback=24 holding=6 sum=+2.9144790792
```

Fixed best 月度和已看 6 月 sanity：

```text
feb_sum=+0.0054374620 sharpe=+0.0534812097 ic=-0.0258203335
mar_sum=-0.3056398179 sharpe=-2.9328919686 ic=-0.0228488089
apr_sum=+0.9769441561 sharpe=+11.6825529071 ic=+0.0950044431
may_sum=+2.8938136721 sharpe=+16.4429358388 ic=+0.1603904117
jun01_04_sum=+0.2839507666 sharpe=+6.4057144483 ic=+0.1217418945
top_fraction 0.10/0.25/0.50 all positive on 120d discovery
```

Overlap sanity 已补，不要重复跑同一轮：

```text
stride_120d=/home/alyaloale/Code/qount/state/research_runs/20260605T123357Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-120d-20260605.json
stride_120d_sum=+0.5087944384
stride_120d_sharpe=+6.0811826595
stride_120d_rank_ic=+0.0607409120
stride_feb_sum=-0.0026969105
stride_mar_sum=-0.0234895413
stride_apr_sum=+0.0796046219
stride_may_sum=+0.5008009667
stride_jun01_04=/home/alyaloale/Code/qount/state/research_runs/20260605T123424Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-stride-jun01_04-20260605.json
stride_jun01_04_sum=+0.0627083513
```

读法：这是当前最像样的 prediction-family candidate，但还不是 paper。all-overlap 和 stride
下 120 天都为正，说明不是纯重叠 horizon 幻觉；但 2026-02 / 2026-03 月度 stride 仍为负，
`jun01_04` 只是已看窗口 sanity。下一刀做 S1.1/S1.2 的 purged-CV / triple-barrier /
overlap-aware portfolio replay；不要直接 promotion。

限仓 portfolio replay 也已补，不要重复当下一刀：

```text
portfolio_replay_120d=/home/alyaloale/Code/qount/state/research_runs/20260605T125713Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-120d-20260605.json
max_open_positions=12
sum=+0.2974912983
sharpe=+7.1945433715
max_dd=0.0876673733
trades=1446
skipped=2880
feb_sum=+0.0062629159
mar_sum=-0.0094161679
apr_sum=+0.0656249961
may_sum=+0.2463757288
jun01_04=/home/alyaloale/Code/qount/state/research_runs/20260605T125741Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-portfolio-replay-jun01_04-20260605.json
jun01_04_sum=+0.0082009038
```

读法：限仓 replay 排除了“完全靠无限重叠下注”的解释，但 3 月仍为负，2 月只是微正；
现在下一刀是 purged-CV / triple-barrier / 新 OOS，不是继续 replay sanity，也不是 paper。

Simple triple-barrier 已补，不要重复当下一刀：

```text
tp/sl 120d:
  0.015/0.010 sum=-0.2542260860 sharpe=-21.9420203800
  0.020/0.010 sum=-0.2307013696 sharpe=-16.8127315231
  0.020/0.015 sum=-0.2296270771 sharpe=-14.6592774682
  0.030/0.015 sum=-0.1635040433 sharpe=-8.7264450618
best_least_bad_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132109Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-120d-tp0.030-sl0.015-20260605.json
exit_reason_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132953Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-exitreasons-120d-tp0.030-sl0.015-20260605.json
120d_exit_counts=stop_loss 873, take_profit 400, time 173
120d_win_rate=0.3443983402
tp0.030/sl0.015 monthly:
  feb_sum=-0.0356452182
  feb_exit_counts=stop_loss 224, take_profit 110, time 8
  mar_sum=-0.0631122398
  mar_exit_counts=stop_loss 242, take_profit 107, time 29
  apr_sum=-0.0812657295
  apr_exit_counts=stop_loss 211, take_profit 73, time 82
  may_sum=+0.0203985601
  may_exit_counts=stop_loss 205, take_profit 116, time 57
  jun01_04_sum=+0.0177000000
jun01_04_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T132208Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-triple-jun01_04-tp0.030-sl0.015-20260605.json
```

读法：fixed TP/SL triple-barrier 直接否定当前 paper 资格。现在 `4h xs_mom` 只能继续
purged-CV / exit 设计 / 新 OOS；不要把 close-to-close 或 replay 正收益当 paper。负收益
主因是路径止损和成本：120 天 stop-loss `873` 次、take-profit `400` 次，止损约为止盈
`2.18x`。

Fixed-cell purged/embargo CV 已补，不要重复同一 close/replay sanity。新参数：
`--directional-purged-cv-folds` / `--directional-embargo-bars`，只影响
`strategy-selection-scan` 预测族 artifact；默认关闭，不影响 live / `run-once` / CARRY。

```text
purged_cv_artifact=/home/alyaloale/Code/qount/state/research_runs/20260605T133904Z-strategy-selection-scan-qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605/qount-strategy-selection-s1-xsmom-4h-lb24-h6-purgedcv-120d-20260605.json
full_sum=+0.2974912983
full_sharpe=+7.1945433715
positive_folds=3/4
min_fold_sum=-0.0566596009
fold1=+0.0467298450
fold2=-0.0566596009
fold3=+0.0611460588
fold4=+0.2462749954
```

读法：purged/embargo 诊断支持继续研究 `4h xs_mom lb24/h6`，但 2026-03-03..2026-04-01
fold 仍为负，不能 paper。下一刀应是更稳健的 exit 设计、模型层 purged-CV，或新的完整 OOS，
不是重复 fixed close/replay/purged 读数。

同步到 WSL 并安装：

```bash
./scripts/sync-to-wsl.sh --install
```

WSL 测试：

```bash
./scripts/run-wsl-tests.sh
```

这两个脚本使用 here-doc 进入 WSL，避免 Mac -> Windows PowerShell -> WSL 多层引号把
`-p 'test*.py'` 吞掉。脚本不会修改 WSL `.env`、不会启动 timer、不会打开 live。

## 标准研究命令

端到端 backtest：

```bash
python -m qount.main backtest \
  --research-profile eth-only \
  --holdout-role discovery \
  --start 2026-05-23T00:00:00+00:00 \
  --end 2026-05-23T03:00:00+00:00 \
  --review-horizon-bars 6
```

端到端 walk-forward：

```bash
python -m qount.main walk-forward \
  --research-profile eth-only \
  --holdout-role discovery \
  --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00
```

只读 setup 层：

```bash
python -m qount.main setup-edge-walk-forward \
  --research-profile eth-only \
  --holdout-role discovery \
  --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00
```

setup_model v1/v2 离线对比：

```bash
python -m qount.main setup-model-compare \
  --research-profile eth-only \
  --setup-phases range_noise short_rebound_fail_confirmed long_pullback_reclaim_confirmed short_breakdown_confirmed \
  --lookback-days 90 \
  --horizon-bars 6 \
  --min-samples 20 \
  --split-higher-phase \
  --eval-fraction 0.30 \
  --output-path /tmp/qount-setup-model-compare-ethonly-v2-range.json
```

读法：这是 setup_model 研究诊断，只拉历史 K 线并做 chronological split，不调用 AI、
不执行订单。`v2_interactions` 只有在显式 `--setup-model-version v2_interactions` 或
`setup-model-compare` 中使用；当前主线 v1 不变。

只读 candidate 层：

```bash
python -m qount.main candidate-walk-forward \
  --research-profile eth-only \
  --holdout-role discovery \
  --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00 \
  --max-bars-per-window 20
```

AI hold-bias 诊断：

```bash
python -m qount.main ai-hold-baseline \
  --research-profile eth-only \
  --artifact-dir state/research_runs \
  --prompt-variant v1 \
  --target-tags multi_range_action_pullback_sma_fast_gt008 \
  --limit 30 \
  --dry-run
```

注意：`--research-profile eth-only` 会过滤到 `ETH/USDT` 样本；如果复核 WS-4 的
multi-symbol fast-SMA 全量 24 样本，要改成 `--research-profile multi-symbol`。
`v2_remove_default_wait` / `v3_veto_only` 只用于研究重放，不会改变 live / `run-once`。

0 交易窗口诊断：

```bash
python -m qount.main idle-window-diagnostic \
  --research-profile eth-only \
  --artifact-dir state/research_runs \
  --horizon-bars 6 \
  --top-candidates 5 \
  --reason-limit 12 \
  --output-path /tmp/qount-idle-window-diagnostic-ethonly.json
```

读法：这是 diagnostic-only，只读已有 `qount.db` / `summary.json`，不调用 AI、不执行订单、
不改变 candidate / risk / live。`--research-profile eth-only` 会过滤到 `ETH/USDT`；
全局 reason aggregate 使用未截断计数，窗口内展示受 `--reason-limit` 限制。

AI 缓存只在研究 backtest / walk-forward 显式开启：

```bash
python -m qount.main walk-forward \
  --research-profile eth-only \
  --holdout-role discovery \
  --ai-decision-cache state/research_cache/ai_decisions.sqlite \
  --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00
```

不要在 live / `run-once` 里使用或模拟这个缓存。

## Artifact 规则

- 优先用 `state/research_runs/...` 下的持久 artifact。
- 如果命令显式写 `/tmp`，也要读取结果里的 `persistent_artifact_path` 或
  `persistent_artifact_dir`。
- promotion 级读数必须带 `holdout_role=validation_v1`。
- 2026-06-01..2026-06-03 两个 validation 窗口已经用过且端到端失败；后续不要在调参后
  复用它们宣称 promotion。
- `eth_short_range_noise_terminal_washout` blocker 把上述两个窗口降级 discovery 后转正，
  但 2026-06-03..2026-06-04 新 validation 的第一次 artifact 被 AI `auth_unavailable`
  污染；infra rerun 无 AI 错误但仍 realized 亏损。这个窗口也已经用过，后续只能降级
  discovery。
- `offline_future_edge_readiness` 只是离线 future-edge 读数，不是 promotion gate。
- `ready_tags=[]` 的窗口不要靠补 narrow override 强行变成 gate。

## 代码指针

- CLI：`src/qount/main.py`
- 配置：`src/qount/settings.py`
- 研究 profile：`src/qount/research_profile.py`
- backtest / walk-forward：`src/qount/backtest.py`、`src/qount/walk_forward.py`
- setup model / v2 compare：`src/qount/setup_model.py`
- research diagnostics：`src/qount/ai_hold_baseline.py`、`src/qount/idle_window_diagnostic.py`
- candidate / tags：`src/qount/candidate_filter.py`、`src/qount/entry_quality.py`
- AI：`src/qount/ai_client.py`、`src/qount/orchestrator.py`
- review / scan：`src/qount/review.py`、`src/qount/research_slice_scan.py`
- artifact：`src/qount/artifacts.py`
- 主测试：`tests/test_strategy_optimization.py`
- 交易所边界测试：`tests/test_exchange_throttling.py`

## 当前禁止事项

- 不把 `QOUNT_LIVE_ENABLE` 改成 `true`。
- 不启动或 enable `qount-runner.timer`。
- 不把旧 `wf-*` 窗口当 validation。
- 不把 2026-06-01..2026-06-04 已看过窗口当新的 promotion 验证。
- 不用旧 G1/G2 解释 promotion。
- 不为了成交频率放宽 broad `range_noise`、`short_rebound_fail` 或 reclaim-long gate。
- 不把 Kronos 接到 candidate / risk / live。
- 不把 WSL `.env` 的 4-symbol 形状当 ETH-only 研究口径。

## 下一步执行顺序

> **2026-06-06 项目级决策（所有者确认）：执行 §7 诚实止盈，停止追盈利。** 根因是架构级广度
> 天花板——加密 majors r̄≈0.63，横截面有效广度仅 ~1.5、渐近天花板 `1/r̄≈1.6`（扩币救不了），
> 要求 IC 实际 ≈0.15、观测最强仅 0.05。横截面（XS-MOM/REV/funding）广度封死、日频 TS-MOM
> 已证伪、CARRY 已证伪。完整对账见 profit-engineering-plan.md §11.8。**不要再开新的特征 /
> 频段搜索**——那只会触发 §7 多重检验假象。

1. **默认不再跑新研究扫描。** 整套反过拟合 harness（triple-barrier、purged-CV+embargo、DSR、
   PBO/CSCV、effective-breadth、频段×族选择扫描）已作为研究成果固化；维护可跑回归测试，但不
   在已穷尽的特征/频段空间继续找 edge。
2. **重启的唯一触发条件是结构性新输入**：真正低相关的新 universe / 新资产类别，或可执行的低延迟
   微结构通道。普通的「再换一个特征 / 再加一个币」不构成重启理由（广度天花板与多重检验都封死）。
3. 已证伪、**不要重复**：`4h xs_mom` 的 exit/regime/barrier/purged-CV 复核；funding/basis 作
   预测特征（xs_funding/xs_funding_rev）；WLD/SOL entry-only basis filter；top12 1d TS-MOM；
   S-CARRY 现金流。
4. 硬纪律全不变：live 关闭、不 forward paper、不放宽 broad gate、`validation_v1` once-only 资格
   继续保留。止盈是停止投入，不是放松边界。
5. 只有 `G_paper` 通过后才讨论 forward paper；只有 forward paper 后才讨论 `G_live`——当前无
   promotion 证据，二者都不触发。
