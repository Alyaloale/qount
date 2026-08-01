# Archive manifest

> **状态**：active inventory｜**权威**：L3 archive-control record｜**最后更新**：2026-08-02
> **适用范围**：候选归档、外置盘迁移与未追踪运行产物的审计；不授予删除或移动权限。
> **TL;DR**：下列条目均为保留优先的候选或已分类资产。`pending_review` 不是批准；不得因本表恢复 legacy、移动数据、删除日志或启用调度。

## Handling rules

1. 只有 `状态=approved` 的条目可以进入第二阶段；本清单当前没有 `approved` 项。
2. 移动前必须先更新引用、部署入口与兼容层，然后重跑 `repository_hygiene.py check` 和相关测试。
3. 原始数据、模型、缓存、运行状态和日志默认不进 Git。外置盘产物需要另附相对路径、SHA-256、生成命令、来源与保留期；本表不伪造这些尚未核验的元数据。

| 原路径 | 类别 | 状态 | 引用结果 | 目标位置 / 外置存储定位 | 处理结论 |
| --- | --- | --- | --- | --- | --- |
| `.env` | local_configuration | excluded_from_archive | 私有本机配置；内容不扫描、不记录 | Mac 私有路径 | 绝不加入 Git、manifest 值或外置盘；仅用 `config-check` 做非回显预检。 |
| `.qount-release-provenance.json` | runtime_data | pending_review | 未追踪本机 release/provenance 元数据 | VPS/外置盘定位待 owner 核验 | 保留原处；不读取内容、不移动或删除。 |
| `data/` | runtime_data | pending_review | 未追踪；被研究脚本和本地输出使用的可能性未知 | `E:\qount_data\qount\datasets\…`（待 owner 提供 manifest） | 保留原处；不自动添加、移动或删除。 |
| `models/` | runtime_data | pending_review | 未追踪模型 artifact | `E:\qount_data\qount\models\…`（待 hash） | 保留原处；不自动添加、移动或删除。 |
| `mac_nohup_experiments.log`, `mac_nohup_v4.log` | runtime_data | pending_review | 根目录本机日志 | 外置盘 `logs/`（待保留期与 hash） | 保留为证据；禁止按名称清理。 |
| `v4_round3_report.md` … `v4_round7_alpha_attribution.md` | documentation | pending_review | 根目录研究报告，可能被后续研究引用 | `docs/archive/research-reports/`（须先做引用审计） | 仅列候选；不移动。 |
| `diagnostic_report_baselines.md` | documentation | pending_review | 根目录诊断报告 | `docs/archive/research-reports/`（须先确认替代入口） | 保留，不移动。 |
| `docs/crypto-trend-v1-*.md`, `docs/traditional-v1-*.md` | active_research | active | 当前未追踪研究文档 | `docs/`，待形成主索引后再判断 | 不是归档候选；保持原位。 |
| 根 `scripts/train_*.py`, `scripts/replay_*.py`, `scripts/backtest_*.py`, `scripts/predict_*.py` | legacy_compatibility | pending_reference_audit | 存在新 `scripts/research/` 和 `scripts/operations/` 域；尚未确认 test/deploy/doc 引用 | `scripts/archive/` 或带 warning 的兼容 wrapper（待批准） | 本轮不改名、不移动。 |
| `deploy/systemd/qount-*-*.service` 与 `*.timer` 的删除/新增 | deployment | user_worktree_change | 当前脏工作区资产 | VPS 部署清单（仅静态校验） | 不恢复、不安装、不修改远端。 |

已归档正文的入口为 [README.md](README.md)。归档文档中的历史相对链接仅作证据，不构成当前导航或可恢复的运行指令。
