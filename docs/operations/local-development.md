# Local development

> **状态**：active｜**权威**：L3 local runbook｜**最后更新**：2026-08-02
> **适用范围**：Mac checkout, virtual environment, lightweight verification and local research entry.
> **TL;DR**：Mac 是代码主仓、文档与轻量验证节点。它不是 production truth，也不运行实盘执行器。

## Setup and safe preflight

```bash
uv sync --extra test
set -a
. ./.env  # only after manually confirming it is trusted and mode 0600 when it contains a secret
set +a
qount-run config-check --profile mac
qount-run --help
```

The repository's baseline test tooling is `unittest`, not pytest. Start with the narrow test that owns the changed module; preserve any user worktree changes rather than resetting the checkout.

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_config_contract tests.test_repository_hygiene
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
```

After a package-structure change, use:

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
```

## Research and data boundary

Use the documented research command for the active line and write to a declared artifact location. Do not download or persist full datasets on Mac; use WSL/external disk for CPU/GPU data work. A research result remains `research_only` and cannot change production state, orders, strategy parameters or scheduling.

When a compute interface changes, use the existing sync/run workflow described in [host runbooks](host-runbooks.md); do not keep WSL as a general purpose continuous mirror.
