# Repository map

> **状态**：active｜**权威**：L3 generated reference｜**最后更新**：2026-08-02
> **适用范围**：目录职责、公开入口、部署引用与治理检查。
> **TL;DR**：生产控制面、活跃研究、冻结兼容、部署、文档和运行数据分层；本文件由 `repository_hygiene.py inventory --write` 生成，不记录密钥或运行时值。

## Stable public entry points

- CLI: `qount-run` → `qount.main:main`; monitor: `qount-monitor` → `qount.mac_monitor:main`.
- Current fact source: [`../current.md`](../current.md). Operational navigation: [`../operations/host-runbooks.md`](../operations/host-runbooks.md).
- Main verification: `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'` (full suite); focused governance verification is documented in [`cli-and-scripts.md`](cli-and-scripts.md).

## Domain ownership

| Domain | Responsibility | Host / entry |
| --- | --- | --- |
| `src/qount/contracts`, `execution`, `governance`, `ledger`, `risk`, `operations`, `notifications`, `persistence`, `portfolio`, `reporting`, `venue` | Production control plane and shared contracts | VPS is runtime truth; Mac performs lightweight checks. |
| `src/qount/mini_trend`, `dual_engine`, `small_account`, `alpha_agents`, `research_data`, `research/sleeves` | Active research or no-order simulations | Mac/WSL research; external disk holds large artifacts. |
| `src/qount/legacy` and `scripts/archive` | Frozen compatibility and historical evidence | No new business logic or timer restoration. |
| `deploy/systemd`, `deploy/wsl`, `deploy/dual_engine`, `deploy/research` | Deployment templates and host topology | Static validation only without explicit VPS authorization. |
| `docs` | Current fact, rules, operations, reference and archive navigation | `docs/current.md` is the sole current fact source. |

## Inventory snapshot

Git status at generation time: `deleted=8, ignored=60, modified=44, untracked=126`.

| Category | Files scanned |
| --- | ---: |
| `active_research` | 361 |
| `deployment` | 28 |
| `documentation` | 104 |
| `legacy_compatibility` | 118 |
| `production_control_plane` | 414 |
| `runtime_data` | 3058 |
| `unclassified` | 13 |

Root-level review candidates are recorded in [`../archive/manifest.md`](../archive/manifest.md); candidates are not approved for movement or deletion merely by appearing there.

## Generated checks

`scripts/maintenance/repository_hygiene.py check` verifies relative Markdown links, environment-contract coverage, repository-owned deployment references, production-to-script import boundaries, required document metadata, manifest shape, and unclassified root files. It never accesses a remote host or reads secret values.
