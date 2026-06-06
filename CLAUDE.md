# CLAUDE.md

本文件给在本仓库工作的 Claude Code 使用。

## 交流约定

- **始终用中文回答。** 除非用户显式要求换语言,所有回复一律中文。
  （代码、命令、commit message、英文专有名词保持原样,不必硬翻译。）

## 文档地图

- `docs/current.md`：当前事实入口与硬边界。
- `docs/holdout.md`：`discovery_pool` / `validation_pool_v1` 与 `G_paper` / `G_live`。
- `docs/quick-handoff.md`：接手命令、跨主机操作、运维坑点。
- `docs/update-log.md`：近期变更与证据链。
- `docs/optimization-plan.md`：T-A..T-J 架构评审路线。
- `docs/profit-research-plan.md`：WS-1..WS-4 盈利研究历史路线。
- `docs/profit-engineering-plan.md`：盈利工程主线(S0–S5);§11 是计划与现实的对账。

## 推进铁律

- 一轮只改一处(entry / management / model / prompt 不同时改),先写单测。
- 验证流程：本地 unittest → `scripts/sync-to-wsl.sh --install` → `scripts/run-wsl-tests.sh`
  → 跑对应研究命令 → artifact 落 `state/research_runs` → 写回 current.md / update-log.md。
- live 必须保持关闭(`QOUNT_LIVE_ENABLE=false`);不 forward paper、不放宽 broad gate、
  不在 `discovery_pool` 上调参后当 promotion、Kronos / 外部模型不进 candidate/risk/live。
- Mac(`/Users/alyaloale/Code/qount`)是编辑和 git 表面;WSL
  (`/home/alyaloale/Code/qount`)是生产和回测真相。
