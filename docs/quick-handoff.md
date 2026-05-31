# qount 快速接手手册

更新时间：2026-05-31

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

## 本地与 WSL 验证

本地测试：

```bash
cd /Users/alyaloale/Code/qount
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
```

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

只读 candidate 层：

```bash
python -m qount.main candidate-walk-forward \
  --research-profile eth-only \
  --holdout-role discovery \
  --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00 \
  --max-bars-per-window 20
```

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
- `offline_future_edge_readiness` 只是离线 future-edge 读数，不是 promotion gate。
- `ready_tags=[]` 的窗口不要靠补 narrow override 强行变成 gate。

## 代码指针

- CLI：`src/qount/main.py`
- 配置：`src/qount/settings.py`
- 研究 profile：`src/qount/research_profile.py`
- backtest / walk-forward：`src/qount/backtest.py`、`src/qount/walk_forward.py`
- setup model：`src/qount/setup_model.py`
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
- 不用旧 G1/G2 解释 promotion。
- 不为了成交频率放宽 broad `range_noise`、`short_rebound_fail` 或 reclaim-long gate。
- 不把 Kronos 接到 candidate / risk / live。
- 不把 WSL `.env` 的 4-symbol 形状当 ETH-only 研究口径。

## 下一步执行顺序

1. 先做 T-B：统计 AI hold-bias，冻结 prompt v2/v3，再等 `validation_pool_v1` once-only 验证。
2. 并行做 T-C：`setup_model` v2，加 phase × bin 交互和 per-phase ridge。
3. 做 T-G：对 0 交易窗口输出 setup 预测分布、candidate 拒绝原因、AI hold 原因。
4. 工程化做 T-E/T-F：窄 gate 集合化，`Settings` / `ResearchSettings` 隔离。
5. 只有 `G_paper` 通过后才讨论 forward paper；只有 forward paper 后才讨论 `G_live`。
