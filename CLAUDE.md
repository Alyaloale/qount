# Claude Code 接手入口

用中文协作（代码、命令、commit message 与英文专有名词可保持原样）。本文件只定义 Claude 的交流约定，不维护第二套项目事实、主机状态或运行规则。

1. 先读 [AGENTS.md](AGENTS.md)，再读 [docs/current.md](docs/current.md)。冲突时 `docs/current.md` 优先。
2. 除非 owner 明确授权，不碰真实账户、VPS、订单、paper/live、arm、交易 timer 或生产 cron。
3. 研究默认 `research_only=true`、`orders_authorized=false`；不能因研究结果推断生产授权。
4. 不回显、复制、提交或导出现有凭证。先用 `qount-run config-check` 做值隐藏的本地预检。
5. 运行方式、测试和跨主机边界看 [docs/operations/local-development.md](docs/operations/local-development.md) 与 [docs/operations/host-runbooks.md](docs/operations/host-runbooks.md)。
