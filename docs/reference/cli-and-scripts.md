# CLI and scripts reference

> **状态**：active｜**权威**：L2 stable interface reference｜**最后更新**：2026-09-30
> **适用范围**：公开 CLI、脚本分类、只读验证和禁止的 legacy 入口。
> **TL;DR**：`qount-run` 与 `qount-monitor` 是稳定公开入口。`main.py` 是兼容门面，参数定义由 `src/qount/cli/` 注册；完整参数以 `qount-run --help` 为准。

## Public commands

| Command | Input / output | Safety status |
| --- | --- | --- |
| `qount-run config-check --profile {mac,wsl,vps} [--env-file PATH]` | Env key names and value-free JSON report | Read-only; no network or state writes. |
| `qount-run --help` | Current command registry and supported arguments | Read-only. |
| `qount-run healthcheck`, `runtime-status`, `paper-status`, `dashboard-snapshot` | Runtime diagnostic JSON | May contact configured services; do not use as an authorization mechanism. |
| `qount-run backtest`, `walk-forward`, `strategy-selection-scan`, `l*-*-scan` | Declared research artifacts | Research-only; choose a documented artifact directory. |
| `qount-monitor` | Local monitoring interface | Preserve existing behavior and host boundary. |

The historical `cta-paper-sim` command remains a compatibility delegation to `qount.cta_sim`; it is not a newly supported production surface.

## CLI ownership

`qount-run = qount.main:main` remains unchanged. Its code is intentionally split by responsibility:

| Location | Responsibility | Compatibility rule |
| --- | --- | --- |
| `src/qount/main.py` | Early `cta-paper-sim` delegation, safe configuration preflight, settings/profile setup and command dispatch | Do not rename the public entry point or alter exit behavior incidentally. |
| `src/qount/cli/registry.py` | Active parser registration and small parser-only helpers | Add or change command arguments here, with parser tests. |
| `src/qount/cli/legacy_research.py` | Frozen L1/L3/L4/L6 parser compatibility | Keep commands parseable for reproducibility; do not treat visibility as permission to revive a line. |

New command behavior belongs in a testable package function. A CLI module should only define arguments, validate local combinations and pass values to that function.

## Script domains

| Directory | Role | Rule |
| --- | --- | --- |
| `scripts/operations/` | Deployment/runtime thin adapters | Parse arguments, call package functions and write only declared artifacts. |
| `scripts/research/<line>/` | Active research thin adapters | No production import of these scripts. |
| `scripts/maintenance/` | Repository/metadata maintenance | `repository_hygiene.py` is read-only except explicit generated-map writes. |
| `scripts/archive/` | Frozen historical scripts | Do not run, install or restore timers from these paths. |
| `scripts/desktop/` | Existing MiniTrend operations compatibility surface | Do not use it to re-enable live, arm, timer or cron. |
| `scripts/hosts/` | Mac-side compute-host connection helpers | `qount-wsl.sh [status\|ensure\|shell]` self-heals Mac→WSL SSH; compute hosts only, never VPS/production. |
| `scripts/sync-to-wsl.sh`, `scripts/run-wsl-tests.sh` | Explicit WSL code sync / remote unittest | Default `QOUNT_WSL_HOST=qount-wsl` (direct SSH into WSL, 2026-09-30); run `qount-wsl.sh ensure` first. |

## Focused checks

```bash
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py inventory --write
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_config_contract tests.test_cli_registry tests.test_repository_hygiene
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
qount-run --help
```

For package layout changes, use the full repository command from [local development](../operations/local-development.md). Deployment changes receive static `systemd`/shell reference validation only until the owner explicitly authorizes VPS work.
