# qount 快速接手手册

更新时间：2026-05-26

当前版本：`0.2.0`

这份文档给接手的大模型用，目标是少踩环境和转义坑，直接进入有效验证。
当前策略结论以 [current.md](current.md) 为准。

## 第一原则

- Mac 是编辑和 git 工作区：`/Users/alyaloale/Code/qount`。
- WSL 是生产和回测真相：`/home/alyaloale/Code/qount`。
- WSL 目录不一定是 git repo；不要依赖 WSL `git status`。
- live 必须保持关闭：`QOUNT_LIVE_ENABLE=false`。
- WSL 跑联网命令前必须 `source .env`，否则代理不生效。
- 研究入口用 `--research-profile eth-only`，不要直接继承 `.env` 的 4-symbol live 配置。

## 当前代码范围

本轮 `0.2.0` 发布涉及下列核心文件。如果接手时 `git status` 仍显示脏工作树，
先确认是不是这些文件的后续改动，不要为了“干净”去回滚你没有亲自改的东西。

本轮主要修改/新增文件包括：

```text
README.md
docs/current.md
docs/quick-handoff.md
src/qount/backtest.py
src/qount/candidate_filter.py
src/qount/entry_quality.py
src/qount/main.py
src/qount/review.py
src/qount/risk_engine.py
src/qount/setup_model.py
src/qount/research_profile.py
src/qount/walk_forward.py
tests/test_strategy_optimization.py
```

接手前先跑：

```bash
cd /Users/alyaloale/Code/qount
git status --short --branch
```

只改和任务相关的文件。不要回滚你没有亲自改的东西。

## WSL 状态检查

从 Mac 跑多行 WSL 命令时，用 here-doc，绕开 PowerShell 引号吞命令：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF'
cd /home/alyaloale/Code/qount || exit 1
printf '%s\n' '--- env ---'
grep -E '^(QOUNT_MODE|QOUNT_MARKET_TYPE|QOUNT_RULE_MODE|QOUNT_LIVE_ENABLE|QOUNT_SYMBOLS|QOUNT_CONTRACT_LEVERAGE|QOUNT_MAX_OPEN_POSITIONS|QOUNT_HOURLY_MODEL_ENABLE|QOUNT_SETUP_MODEL_ENABLE|QOUNT_SETUP_MODEL_PATH|HTTP_PROXY|HTTPS_PROXY)=' .env || true
printf '%s\n' '--- systemd ---'
systemctl --user is-active qount-runner.timer qount-runner.service || true
printf '%s\n' '--- runtime ---'
set -a
source .env
set +a
./.venv/bin/python -m qount.main runtime-status | python3 -m json.tool
EOF
```

注意：

- 不要用 `printf '--- env ---\n'`；某些 shell 会把 `---` 当选项。用 `printf '%s\n' '--- env ---'`。
- WSL 里没有 `rg` 时用 `grep` / `find`。
- 如果看到 `Network is unreachable` 访问 `fapi.binance.com`，先检查是不是忘了 `source .env`。

## 本地和 WSL 测试命令

本地：

```bash
cd /Users/alyaloale/Code/qount
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
```

WSL：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p '\''test*.py'\''"'
```

坑点：

- 直接嵌套 `-p "test*.py"` 容易被 PowerShell / bash 多层转义吞掉，可能出现 `Ran 0 tests`。
- 上面的 `'\''test*.py'\''` 是已经验证过的写法。
- 定点测试可以少一层复杂度：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_strategy_optimization.StrategyOptimizationTests.test_risk_engine_persists_initial_trailing_peak_before_retrace"'
```

## Mac 到 WSL 同步文件

不要假设 `scp home:~/...` 会展开到正确目录。SSH 到 Windows 时默认是 PowerShell，`~` 和 `mkdir -p` 都可能不按 bash 语义工作。

可靠流程：

1. 建 Windows 临时目录：

```bash
ssh -o ClearAllForwardings=yes home "New-Item -ItemType Directory -Force -Path 'C:\Users\15470\qount-sync\src\qount','C:\Users\15470\qount-sync\tests','C:\Users\15470\qount-sync\docs' | Out-Null"
```

2. 从 Mac 复制到 Windows 临时目录：

```bash
scp -o ClearAllForwardings=yes src/qount/risk_engine.py home:'C:/Users/15470/qount-sync/src/qount/risk_engine.py'
scp -o ClearAllForwardings=yes tests/test_strategy_optimization.py home:'C:/Users/15470/qount-sync/tests/test_strategy_optimization.py'
scp -o ClearAllForwardings=yes docs/current.md home:'C:/Users/15470/qount-sync/docs/current.md'
scp -o ClearAllForwardings=yes docs/quick-handoff.md home:'C:/Users/15470/qount-sync/docs/quick-handoff.md'
```

3. 从 Windows 临时目录复制进 WSL：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -lc "cp /mnt/c/Users/15470/qount-sync/src/qount/risk_engine.py /home/alyaloale/Code/qount/src/qount/risk_engine.py && cp /mnt/c/Users/15470/qount-sync/tests/test_strategy_optimization.py /home/alyaloale/Code/qount/tests/test_strategy_optimization.py && cp /mnt/c/Users/15470/qount-sync/docs/current.md /home/alyaloale/Code/qount/docs/current.md && cp /mnt/c/Users/15470/qount-sync/docs/quick-handoff.md /home/alyaloale/Code/qount/docs/quick-handoff.md"'
```

如果 Windows 用户目录变化，先查：

```bash
ssh -o ClearAllForwardings=yes home 'echo $env:USERPROFILE'
```

## 最新已验证 artifact

targeted 两窗：

```text
/tmp/qount-wf-eth-range-reclaim-local-breakdown-arm018-2w-rerun-20260526T1538Z
```

完整 6-window：

```text
/tmp/qount-wf-eth-range-trailing-peak-persist-6-20260526T1545Z
```

旧的负例对比：

```text
/tmp/qount-wf-eth-range-reclaim-local-breakdown-arm018-2w-20260526T0800Z
/tmp/qount-wf-eth-range-reclaim-local-breakdown-tight-retrace-apr15-20260526T0830Z
```

旧负例里 `apr15`：

```text
run 76 sell
run 79 hold
run 80 hold
run 81 close
realized_return_pct=-0.1136873727%
```

新正例里 `apr15`：

```text
run 76 sell
run 79 hold + trailing_stop_refresh
run 80 close + management_trailing_profit_retrace
realized_return_pct=+0.0567142019% in full 6-window
realized_return_pct=+0.0680570422% in targeted 2-window
```

## 读取 artifact 的常用脚本

汇总 walk-forward：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF'
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/qount-wf-eth-range-trailing-peak-persist-6-20260526T1545Z/walk_forward.json')
data = json.loads(p.read_text())
print(data['aggregate'])
for w in data['windows']:
    b = w.get('backtest') or {}
    print(
        w['label'],
        'filled/closed=', b.get('paper_filled'), '/', b.get('paper_closed'),
        'realized=', b.get('realized_return_pct'),
        'review=', b.get('review_avg_net_edge_pct'),
        'open=', b.get('open_positions'),
        'blockers=', w.get('promotion_blockers'),
    )
PY
EOF
```

查某个 backtest DB 的 runs / risk reasons：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF'
python3 - <<'PY'
import sqlite3, json
db = '/tmp/qount-wf-eth-range-trailing-peak-persist-6-20260526T1545Z/04-wf-apr15/backtest/qount.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
for run_id in range(74, 83):
    run = conn.execute('SELECT id, summary_json FROM runs WHERE id=?', (run_id,)).fetchone()
    if run is None:
        continue
    summary = json.loads(run['summary_json'])
    risk = json.loads(conn.execute('SELECT verdict_json FROM risk_actions WHERE run_id=?', (run_id,)).fetchone()['verdict_json'])
    order = conn.execute('SELECT status, action, side, pnl_quote FROM orders WHERE run_id=?', (run_id,)).fetchone()
    print(run_id, summary.get('generated_at'), summary.get('action'), risk.get('final_action'), risk.get('reasons'), dict(order) if order else None)
PY
EOF
```

## 重跑最新 6-window 的命令

必须先 `source .env`：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -lc "cd /home/alyaloale/Code/qount && set -a && source .env && set +a && PYTHONPATH=src ./.venv/bin/python -m qount.main walk-forward --research-profile eth-only --window wf-feb27=2026-02-26T18:10:00+00:00,2026-02-27T06:15:00+00:00 --window wf-mar06=2026-03-06T03:05:00+00:00,2026-03-06T15:05:00+00:00 --window wf-mar11=2026-03-11T04:00:00+00:00,2026-03-11T15:00:00+00:00 --window wf-apr15=2026-04-15T04:00:00+00:00,2026-04-15T15:00:00+00:00 --window wf-may06=2026-05-06T04:35:00+00:00,2026-05-06T06:05:00+00:00 --window wf-may23=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00 --train-lookback-days 90 --horizon-bars 6 --gap-bars 1 --min-samples 60 --ridge-alpha 0.0005 --review-horizon-bars 3 --review-threshold-pct 0.003 --artifact-dir /tmp/qount-wf-eth-range-next-check"'
```

这个命令会比较久。运行中可另开只读命令看 partial：

```bash
ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF'
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/tmp/qount-wf-eth-range-next-check/walk_forward.partial.json')
if not p.exists():
    print('partial_missing')
else:
    data = json.loads(p.read_text())
    print('complete', data.get('complete'), 'window_count', data.get('window_count'), data.get('aggregate'))
    for w in data.get('windows', []):
        b = w.get('backtest') or {}
        print(w.get('label'), b.get('realized_return_pct'), b.get('review_avg_net_edge_pct'), b.get('open_positions'), w.get('promotion_blockers'))
PY
EOF
```

## 代码指针

核心入口：

```text
src/qount/main.py
src/qount/research_profile.py
src/qount/walk_forward.py
src/qount/backtest.py
src/qount/risk_engine.py
src/qount/review.py
```

最近关键风险逻辑：

```text
RiskEngine._should_force_trailing_profit_close
RiskEngine._effective_trailing_profit_retrace_pct
RiskEngine._eth_short_research_blocks_fresh_reclaim_short_open
RiskEngine._eth_short_reclaim_has_local_breakdown_pressure
ETH_RECLAIM_SHORT_TRAILING_PROFIT_RETRACE_PCT
```

最近关键测试：

```text
tests/test_strategy_optimization.py
test_risk_engine_persists_initial_trailing_peak_before_retrace
test_risk_engine_uses_tighter_retrace_for_eth_reclaim_short
test_eth_only_research_profile_applies_canonical_settings
test_walk_forward_trains_before_window_and_records_oos_summary
```

## 下一步建议

当前不要继续“加速上线”。下一步应只查一个窄问题：

```text
Why is wf-mar11 still losing after trailing peak persistence?
```

建议入口：

```text
/tmp/qount-wf-eth-range-trailing-peak-persist-6-20260526T1545Z/03-wf-mar11
```

流程：

1. 读 `summary.json` / `review.json` / `qount.db`。
2. 找亏损 entry 的 run id、entry thesis、risk reasons、close timing。
3. 确认是否已有窄 blocker 可以解释。
4. 只改一个 hypothesis。
5. 先补单测。
6. 先跑 targeted `mar11 + mar06 + apr15`。
7. 再跑完整 6-window。
8. 更新 `docs/current.md` 和本文件。

不要做：

- 不要 broad entry 放权。
- 不要为了把 `0/0` 变成有交易而降低门槛。
- 不要把 targeted 两窗结果当 promotion。
- 不要打开 live。
- 不要把 WSL 网络错误当策略失败。
- 不要把 PowerShell 引号错误导致的 `NO TESTS RAN` 当测试通过。
