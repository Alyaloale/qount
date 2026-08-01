# qount

`qount` 是一个按真实多主机拓扑运行的 AI 决策、风控执行与 Binance 研究/模拟系统。它同时维护生产控制面、无订单模拟、活跃研究和冻结历史线路。

当前运行事实、服务状态与 owner 决策的唯一来源是 [docs/current.md](docs/current.md)。本 README 只提供稳定入口；不复制版本、账户、订单、计时器或研究结果等易过期事实。

## Safety boundary

本仓库默认 fail closed：本次工作不启用或恢复 live、arm、订单、交易 timer 或生产 cron，也不改变策略参数、外部账户、VPS 或密钥。研究与模拟产物不构成生产授权。

## Quick start (Mac)

```bash
uv sync --extra test
set -a
. ./.env  # only after manually verifying this private file is trusted
set +a
qount-run config-check --profile mac
qount-run --help
```

`config-check` 仅检查变量名称、主机边界和权限，不联网、不创建状态，也从不输出值或凭证片段。详细的配置规则见 [configuration reference](docs/reference/configuration.md)。

## Documentation

- [Current facts and hard boundaries](docs/current.md)
- [Project rules](docs/project-rules.md)
- [Agent handoff](AGENTS.md)
- [Documentation index](docs/README.md)
- [Local development](docs/operations/local-development.md)
- [Host runbooks](docs/operations/host-runbooks.md)
- [CLI and scripts](docs/reference/cli-and-scripts.md)
- [Repository map](docs/reference/repository-map.md)
- [Archive index](docs/archive/README.md)

## Directory overview

```text
src/qount/       production control plane, research domains and legacy compatibility
scripts/         operations, research, maintenance and archived thin entry points
deploy/          systemd, WSL, paper-program and research deployment templates
config/          value-free environment contract
docs/            current facts, rules, runbooks, references and archive navigation
```

For all behavioral changes, start with the narrowest existing test. Package structure changes use the full `unittest` suite documented in [local development](docs/operations/local-development.md). Existing public entry points `qount-run`, `qount-monitor` and tested module paths remain compatibility surfaces.
