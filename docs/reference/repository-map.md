# Repository map

> **状态**：active｜**权威**：L3 repository reference｜**最后更新**：2026-10-05
> **适用范围**：目录职责、公开入口、部署引用与治理检查。
> **TL;DR**：生产控制面、活跃研究、冻结兼容、部署、文档和运行数据分层；基础清单由 `repository_hygiene.py inventory` 生成，研究职责表人工维护；不记录密钥或运行时值。

## Stable public entry points

- CLI: `qount-run` → `qount.main:main`; monitor: `qount-monitor` → `qount.mac_monitor:main`.
- Current fact source: [`../current.md`](../current.md). Operational navigation: [`../operations/host-runbooks.md`](../operations/host-runbooks.md).
- Main verification: `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'` (full suite); focused governance verification is documented in [`cli-and-scripts.md`](cli-and-scripts.md).

## Domain ownership

| Domain | Responsibility | Host / entry |
| --- | --- | --- |
| `src/qount/cli`, `contracts`, `execution`, `governance`, `ledger`, `risk`, `operations`, `notifications`, `persistence`, `portfolio`, `reporting`, `venue` | Public CLI composition, production control plane and shared contracts | VPS is runtime truth; Mac performs lightweight checks. |
| `src/qount/mini_trend`, `dual_engine`, `small_account`, `alpha_agents`, `research_data`, `research/sleeves`, `research/etf_trader`, `research/etf_alpha`, `research/dual_engine_*` | Active research or no-order simulations | Mac/WSL research; owner-designated P3 cloud is temporary compute; E holds final large artifacts. |
| `src/qount/legacy` and `scripts/archive` | Frozen compatibility and historical evidence | No new business logic or timer restoration. |
| `deploy/systemd`, `deploy/wsl`, `deploy/dual_engine`, `deploy/research`, `deploy/cloud` | Deployment templates and host topology | Static validation only without explicit host authorization; cloud research delivery is isolated. |
| `docs` | Current fact, rules, operations, reference and archive navigation | `docs/current.md` is the sole current fact source. |

## Inventory snapshot

以下为2026-10-03生成时的历史快照，文件数及Git状态不代表当前工作区。`inventory --write`会重写整页，包括人工维护的研究职责表；本次仅梳理职责表，不重新生成该快照。

Git status at generation time: `ignored=73, modified=6, untracked=60`.

| Category | Files scanned |
| --- | ---: |
| `active_research` | 527 |
| `deployment` | 52 |
| `documentation` | 206 |
| `legacy_compatibility` | 118 |
| `production_control_plane` | 466 |
| `runtime_data` | 4336 |
| `unclassified` | 16 |

Root-level review candidates are recorded in [`../archive/manifest.md`](../archive/manifest.md); candidates are not approved for movement or deletion merely by appearing there.

## Generated checks

`scripts/maintenance/repository_hygiene.py check` verifies relative Markdown links, environment-contract coverage, repository-owned deployment references, production-to-script import boundaries, required document metadata, manifest shape, and unclassified root files. It never accesses a remote host or reads secret values.

## G20/C60 offline research ownership

These offline modules live in `src/qount/research/`; deployed paper implementations stay in `src/qount/dual_engine/`. [Study overview](../dual-engine-optimization-2026-10.md#研究总览与阅读路径) owns protocols/results; [configuration](configuration.md#g20c60-离线研究合同) owns frozen contracts; [CLI reference](cli-and-scripts.md#g20c60-research-studies) owns adapter parameters.

| Responsibility | Owning modules |
| --- | --- |
| Baseline, execution and independent verification | `dual_engine_optimization`, `dual_engine_execution_study`, `dual_engine_execution_verify`, `g20_drift_control`, `c60_execution_control`; shared exact fees in `research_data/replay_fees.py`. |
| Architecture, expanded public data and sources | `dual_engine_structural`, `dual_engine_expansion`, `dual_engine_expansion_data`, `dual_engine_nextgen`, `dual_engine_nextgen_data`, `dual_engine_regimes`, `dual_engine_regimes_data`, `dual_engine_breadth`. |
| Saved versions and conditional confirmation | `dual_engine_registry`, `dual_engine_confirmation`; all earlier descriptors, exclusions and receipts preserved. |
| Scoped settlement, clocks and profit/loss attribution | `dual_engine_books`, `dual_engine_clocks`, `dual_engine_holdings`; owned-unit and weight-only evidence remain distinct. |
| Vintage risk intents and financed capital books | `dual_engine_intents`, `dual_engine_capital`, `dual_engine_reform`; captured ownership, explicit transfers and gross per-book fees. |
| Recovery and closed-signal capital allocation | `dual_engine_recovery`, `dual_engine_redistribution`, `dual_engine_renewal`; warmup and all-cash initialization are part of accounting. |
| Information availability and target interventions | `dual_engine_information_data`, `dual_engine_sources`; causal settled funding/closed flow, snapshot qualification and macro exclusions. |
| Recovery ownership and delayed exposure control | `dual_engine_zonal_recovery`, `dual_engine_containment`, `dual_engine_zonal`; scoped acquisitions, source epochs and funded BIL sales. |
| Joint settlement and separate family refresh | `dual_engine_coordinator`, `dual_engine_family_clock`, `dual_engine_zorder`; source/budget coordination and declared full-book risk buys. |

Matching `scripts/research/dual_engine_*.py` files parse arguments, delegate to package functions and write declared artifacts. Owning tests are `tests/test_dual_engine_*.py`, `test_g20_drift_control.py`, `test_c60_execution_control.py` and `test_replay_fees.py`. Existing module paths and public CLIs are preserved; production packages do not import research adapters.

Mac holds code, docs and lightweight receipts; WSL performs isolated computation; Windows E retains full immutable datasets, cash/unit ledgers, holding episodes and version descriptors. Local `state/research_runs/` metadata is not a Git-delivered artifact collection. No research module grants service, paper promotion or order authority.
