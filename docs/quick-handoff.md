# qount 快速接手手册 (Vibe Coding Handoff)

> **状态**：active｜**权威**：L4 接手导航；事实以 [current.md](current.md) 为准｜**最后更新**：2026-10-11
> **TL;DR**：先读最终裁决，再按问题修补。麒麟和币安合约旧高收益结论撤销；现有 paper 是无订单模拟，P3 残差训练已结束，旧 READY 不代表可自动重启。

## 5 分钟阅读路径

1. [current.md](current.md)：当前裁决、阶段快照读法、运行登记和权限。
2. [个人交易助手指南](personal-trading-assistant-guide.md)：少量核心资产、低频目标、因果时钟与真实费用。
3. [修补整理计划](research-repair-and-consolidation-plan-2026-10.md)：各线问题、优先级和最小验收。
4. [项目规则](project-rules.md)和[主机手册](operations/host-runbooks.md)：代码归属与主机边界。

## 接手时必须分清

- **当前裁决与旧申报**：麒麟／币安原旗舰数字已撤销，旧正文在 [历史快照](archive/current-archive-pre-review-2026-10-11.md)；专题报告里的历史数字不覆盖 current。
- **目标与已实现能力**：少量持仓、低于 0.5x 的年换手和回撤控制是待检验目标；止损线不保证成交或保本。
- **代理研究与可执行账户**：指数、复权价格、原价现金与真实 ETF 交易路径分开；低波选股名单和 Q-DIV 截止日名单不是当前买入指令。
- **历史回放与前向**：Dual-Engine YTD 含回放；CTA-R／C60 v2 前瞻从各自账本起点计，不反填为新证据。
- **准备与训练**：R3 已以 pilot_no_increment 结束，outer withheld，单轮启动授权已消费；云端暂停状态保持。
- **内容质量与服务健康**：日报定时运行、公开采集新鲜、研究结论成立分别检查，不能互相替代。

## 本地工作与验证

Mac 负责代码、Git、文档和轻量验证。需要重计算时按既有 WSL／E 盘手册准备，不能因接手或查看计划自动启动任务。

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
```

纯文档整理检查本地链接、口径、hygiene 和 diff；代码变更执行相关测试，未运行的检查不得写成通过。避免覆盖既有脏工作区修改。

## 权限与导航

默认 `research_only=true / orders_authorized=false`。未经 owner 明确授权不得启用或触发生产下单、交易 timer 或 cron；旧冻结线不得复活。凭据不打印、不复制、不提交，Mac 私有配置保持 0600。

- [研究线导航](research-lines.md)
- [系统环境与研究全景](system-environment-and-research-landscape.md)
- [配置参考](reference/configuration.md)
- [CLI 与脚本参考](reference/cli-and-scripts.md)
- [系统架构](system-architecture-design.md)
- [历史归档索引](archive/README.md)
