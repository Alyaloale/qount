# qount 快速接手手册

> **状态**：active｜**权威**：L4 运维导航｜**最后更新**：2026-08-02
> **本文回答**：首次接手的最短阅读路径、值隐藏预检和跨主机安全边界。
> **TL;DR**：生产事实只看 [current.md](current.md)。本项目当前不因接手工作启用 live、arm、订单、交易 timer 或生产 cron；不要把已有部署模板或历史命令当作授权。

## First five minutes

1. 阅读 [current.md](current.md) 确认 owner 决策与当前服务事实。
2. 阅读 [project-rules.md](project-rules.md) 确认代码、研究和 legacy 的边界。
3. 在当前主机按 [host runbooks](operations/host-runbooks.md) 确认职责；VPS 是 runtime truth，Mac 是代码主仓，WSL 是计算节点，外置盘是大数据/artifact 真相。
4. 仅在已人工确认可信的本机环境中执行值隐藏预检：

```bash
set -a
. ./.env
set +a
qount-run config-check --profile mac
qount-run --help
```

5. 改动前先找到最窄 `unittest`；结构、配置或文档入口改动后运行：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
```

## Non-negotiable boundaries

- 不回显、复制、提交、导出或同步任何凭证；VPS `/etc/qount/*.env` 仅由受授权的主机运维处理。
- 不启用或恢复 `systemctl` unit、交易 timer、production cron、arm 或订单路径。
- 所有研究与模拟结果默认 `research_only=true`、`orders_authorized=false`，不能修改生产参数或状态。
- 不从 `src/qount/legacy/`、`scripts/archive/` 或历史文档恢复功能；它们只保留证据。
- 不移动或删除 `data/`、`models/`、日志、根目录报告或未追踪内容。候选和引用审计见 [archive manifest](archive/manifest.md)。

## Where details live

- [Configuration contract and safe loading](reference/configuration.md)
- [CLI and scripts](reference/cli-and-scripts.md)
- [Local development](operations/local-development.md)
- [Host runbooks and VPS recovery limit](operations/host-runbooks.md)
- [Repository map](reference/repository-map.md)
- [Storage and compute topology](storage-topology.md)
- [Architecture design](system-architecture-design.md)
- [Active research roadmap](research-advancement-roadmap.md)
- [Historical archive index](archive/README.md)

长命令、一次性部署细节和历史服务状态不在本页重复维护；需要时先由 `current.md` 选择对应的运行手册，再取得明确 owner 授权。
