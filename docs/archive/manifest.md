# Archive manifest

> **状态**：active inventory｜**权威**：L3 archive-control record｜**最后更新**：2026-10-02
> **适用范围**：候选归档、外置盘迁移与未追踪运行产物的审计；不授予删除或移动权限。
> **TL;DR**：本轮 P2 文档归档已获 owner 明确授权；其他条目仍为保留优先的候选或已分类资产。`pending_review` 不是批准；不得因本表恢复 legacy、移动数据、删除日志或启用调度。

## Handling rules

1. 只有 `状态=approved` 的条目可以进入移动阶段；执行后记录为 `archived`，不能将特定文档的批准扩展到代码、数据、模型或其他研究线。
2. 移动前必须先更新引用、部署入口与兼容层，然后重跑 `repository_hygiene.py check` 和相关测试。
3. 原始数据、模型、缓存、运行状态和日志默认不进 Git。外置盘产物需要另附相对路径、SHA-256、生成命令、来源与保留期；本表不伪造这些尚未核验的元数据。

| 原路径 | 类别 | 状态 | 引用结果 | 目标位置 / 外置存储定位 | 处理结论 |
| --- | --- | --- | --- | --- | --- |
| `.env` | local_configuration | excluded_from_archive | 私有本机配置；内容不扫描、不记录 | Mac 私有路径 | 绝不加入 Git、manifest 值或外置盘；仅用 `config-check` 做非回显预检。 |
| `.qount-release-provenance.json` | runtime_data | pending_review | 未追踪本机 release/provenance 元数据 | VPS/外置盘定位待 owner 核验 | 保留原处；不读取内容、不移动或删除。 |
| `data/` | runtime_data | pending_review | 未追踪；被研究脚本和本地输出使用的可能性未知 | `E:\qount_data\qount\datasets\…`（待 owner 提供 manifest） | 保留原处；不自动添加、移动或删除。 |
| `models/` | runtime_data | pending_review | 未追踪模型 artifact | `E:\qount_data\qount\models\…`（待 hash） | 保留原处；不自动添加、移动或删除。 |
| `mac_nohup_experiments.log`, `mac_nohup_v4.log` | runtime_data | pending_review | 根目录本机日志 | 外置盘 `logs/`（待保留期与 hash） | 保留为证据；禁止按名称清理。 |
| `v4_round3_report.md` … `v4_round7_alpha_attribution.md` | documentation | archived | 已审计：仅由对应历史回放/归因脚本生成或引用 | `docs/archive/research-reports/` | 已迁移；保留原文件名和内容，仅作历史证据。 |
| `diagnostic_report_baselines.md` | documentation | archived | 已审计：仅由 `scripts/calc_baselines.py` 生成 | `docs/archive/research-reports/` | 已迁移；脚本输出路径已同步。 |
| `docs/crypto-trend-v1-*.md`, `docs/traditional-v1-*.md` | active_research | active | 当前未追踪研究文档 | `docs/`，待形成主索引后再判断 | 不是归档候选；保持原位。 |
| 根 `scripts/train_*.py`, `scripts/replay_*.py`, `scripts/backtest_*.py`, `scripts/predict_*.py` | legacy_compatibility | pending_reference_audit | 存在新 `scripts/research/` 和 `scripts/operations/` 域；尚未确认 test/deploy/doc 引用 | `scripts/archive/` 或带 warning 的兼容 wrapper（待批准） | 本轮不改名、不移动。 |
| `deploy/systemd/qount-*-*.service` 与 `*.timer` 的删除/新增 | deployment | user_worktree_change | 当前脏工作区资产 | VPS 部署清单（仅静态校验） | 不恢复、不安装、不修改远端。 |

已归档正文的入口为 [README.md](README.md)。归档文档中的历史相对链接仅作证据，不构成当前导航或可恢复的运行指令。

## 既有P2归档布局的提交前保留核验（2026-10-04）

本次“梳理记录文档，并提交更新代码”核验既有工作区布局，没有新增文件移动或删除。原18项归档审计的正文SHA256逐项匹配；以下两份Git中仍位于根目录、工作区已位于归档的历史手册也确认正文完整保留，只增加4行历史/非恢复提示。提交既有布局时保留其归档正文与导航，不把此记录扩展为其他资产的移动批准。

历史快照保留原有Markdown硬换行、代码块空白和末尾空行；`.gitattributes`仅对`docs/archive/p2-history/**`关闭行尾/末尾空白诊断，以保持已审计正文hash。源码、活跃文档及其他路径继续采用默认Git空白检查。

| Git原路径 | 工作区保留位置 | 核验 | 状态 |
| --- | --- | --- | --- |
| `docs/p2-execution-guide.md` | [历史执行手册](p2-history/p2-execution-guide.md) | 原360行正文完整保留，新增4行归档提示 | existing_layout_verified |
| `docs/p2-monitoring-improvements.md` | [历史监控记录](p2-history/p2-monitoring-improvements.md) | 原419行正文完整保留，新增4行归档提示 | existing_layout_verified |

旧P2自动训练/并行搜索原型、`*.bak`、数据、模型及本地Agent配置继续保留原位置；本次提交范围为公开且有相关验证的代码、合同、测试与文档，未将这些本机材料纳入Git。

## P2 文档归档批准与执行（2026-10-02）

owner 本轮明确要求“梳理整理归档文档，写清目前架构结果细节”。以下 18 份文档移动和 1 段历史实施记录拆分据此获批；保留研究证据及原文件名，修正导航和撤回误导性结论，不移动运行产物或脚本。

移动前使用 `rg` 与逐文件引用扫描审计仓库正文/脚本/测试/根导航；未发现代码、部署或测试依赖。`.claude-context` 的旧更新入口改指当前 P2 导航。

| 原路径 | 类别 | 状态 | 引用结果 | 目标位置 | 处理结论 |
| --- | --- | --- | --- | --- | --- |
| `docs/P2-FINAL-STATUS.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/P2-FINAL-STATUS.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/P2-PROJECT-FINAL-REPORT.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/P2-PROJECT-FINAL-REPORT.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/P2-TODAY-SUMMARY.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/P2-TODAY-SUMMARY.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/P2-HANDOVER.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/P2-HANDOVER.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/P2-DOCS-CLEANUP.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/P2-DOCS-CLEANUP.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/P2-DOCS-CLEANUP-SUMMARY.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/P2-DOCS-CLEANUP-SUMMARY.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/p2-performance-results-20261002.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/p2-performance-results-20261002.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/p2-return-analysis.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/p2-return-analysis.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/p2-backtest-reality-check.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/p2-backtest-reality-check.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/p2-backtest-implementation-complete.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/p2-backtest-implementation-complete.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/p2-backtest-environment-issue.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/p2-backtest-environment-issue.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/p2-next-steps-20261002.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/p2-next-steps-20261002.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/p2-environment-setup.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/p2-environment-setup.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/wsl_final_report.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/wsl_final_report.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/ann_log_return-explanation.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/corrections-20261002/ann_log_return-explanation.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/p2-training-progress-20261002-1412.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/snapshots/p2-training-progress-20261002-1412.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/RECENT_UPDATES.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/snapshots/RECENT_UPDATES.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/cloud-server-setup.md` | documentation | archived | 无代码/部署/测试依赖；历史相对链接将重定位 | `docs/archive/p2-history/snapshots/cloud-server-setup.md` | 先记 approved 后执行；现已移动，保留现存正文并重定位链接 |
| `docs/etf-imitation-policy-design-2026-09.md#11.1` | documentation | archived | 稳定设计路径保留；原节替换为历史入口 | `docs/archive/p2-history/snapshots/implementation-20261001.md` | 先记 approved 后拆分；原始研究叙述保留，标明未经本轮重新验收 |
