# Configuration reference

> **状态**：active｜**权威**：L2 configuration contract｜**最后更新**：2026-08-02
> **适用范围**：环境变量、配置来源、密钥边界和只读预检。
> **TL;DR**：机器可读权威是 [`../../config/environment-contract.toml`](../../config/environment-contract.toml)。本文件解释如何安全使用它；不包含任何实际值、账户标识或凭证。

## Sources and ownership

| Host | Configuration source | Secret policy | Data boundary |
| --- | --- | --- | --- |
| Mac | `<repo>/.env`（私有、`0600`） | 可保留本机研究所需最小密钥；不回显、不提交 | 代码、轻量 fixture 与摘要，不长期保存全量数据或生产状态。 |
| Windows external disk | no `.env` | 禁止密钥 | `E:\qount_data` 保存数据集、不可变 artifact、环境锁与备份 manifest。 |
| WSL | `deploy/wsl/qount-compute.env` | 不存密钥；只加载非敏感计算拓扑 | scratch 可清理；最终产物直写外置盘。 |
| VPS | `/etc/qount/*.env`，按服务拆分、`root:root 0600` | 仅服务需要的密钥；禁止复制回 Mac/WSL/外置盘 | 最小运行状态、公开缓存和审计材料。 |

`deploy/wsl/qount-compute.env` 是非敏感拓扑文件，不得与私有 `.env` 合并，不得放入外置盘。VPS 的 `/etc/qount/*.env` 是主机拥有的部署配置，不在本仓库内创建或修改。

## Contract and preflight

每个环境变量在合同中声明名称、域、类型、是否敏感、允许主机、必填条件、默认策略、消费者和 legacy 状态。新增变量必须先进入合同；legacy 条目不应被用于新逻辑。

```bash
# 只解析键名和文件权限；不会联网、创建 state 或打印任何值。
qount-run config-check --profile mac --env-file .env

# WSL 仅允许非敏感拓扑变量。
qount-run config-check --profile wsl --env-file deploy/wsl/qount-compute.env
```

检查会报告缺失、未知、主机不允许、包含已配置密钥的文件权限不安全、以及请求 live/已禁用线路的互斥配置。输出只包含变量名和分类，永远不包含值、长度、前缀或哈希。检查失败退出码为 `2`。

## Safe local loading

只加载你信任且权限正确的本机 `.env`，不要使用 `export $(grep … | xargs)` 之类会错误解析空格、引号和注释的写法。

```bash
set -a
. ./.env
set +a
qount-run config-check --profile mac
qount-run --help
```

`.env.example` 是 Mac 安全模板：只含本机可用的非敏感默认值和空占位符。VPS 专用变量只在合同与部署说明中说明目标环境文件，绝不复制任何凭证。

## Troubleshooting

- `unknown`: 先将新变量加入合同并写明消费者；不要绕过检查。
- `host_not_allowed`: 将配置移到批准的主机，不把密钥同步到 WSL 或外置盘。
- `unsafe_permissions`: 若文件有已配置密钥，人工执行 `chmod 600 <file>`；检查工具只报告，不修改权限。
- `disabled_strategy_requested` / `live_enable_requested`: 立即移除该请求；本次治理不授权 live、arm、订单、timer 或 cron。
