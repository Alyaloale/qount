# Code organization reference

> **状态**：active｜**权威**：L2 maintainability reference｜**最后更新**：2026-08-02
> **适用范围**：包边界、公开入口、可读性重构和兼容层。
> **TL;DR**：按控制面、活跃研究、冻结兼容和 CLI/脚本入口阅读代码。重构优先缩小职责、保留导入路径和命令行为，不以目录整洁为由破坏兼容。

## Reading order

1. 从 [`current.md`](../current.md) 确认哪些线路仍可维护；历史事实不从代码或归档推断。
2. 从 [`project-rules.md`](../project-rules.md) 确定模块所属域与运行边界。
3. 对公开命令先看 [`cli-and-scripts.md`](cli-and-scripts.md) 和 `src/qount/main.py`。
4. 对业务实现从对应域的 `contracts`、`models` 或纯函数开始，再读适配器、存储和入口。

## Package boundaries

| Area | Read here first | Keep out |
| --- | --- | --- |
| Public CLI | `main.py`, `cli/registry.py`, `cli/legacy_research.py` | 业务计算、网络客户端和状态写入。 |
| Production control plane | `contracts/`, `execution/`, `governance/`, `ledger/`, `risk/`, `operations/`, `reporting/`, `venue/` | `scripts/research` 和 optional research-only dependencies. |
| Active research / simulation | `mini_trend/`, `dual_engine/`, `small_account/`, `alpha_agents/`, `research_data/`, `research/sleeves/` | 生产授权、账户写入和订单路径。 |
| Frozen compatibility | `legacy/` 和 `scripts/archive/` | 新业务逻辑、自动化重启和“顺手修复”式功能扩张。 |
| Thin adapters | `scripts/operations/`、`scripts/research/` | 核心策略逻辑、隐藏配置规则和跨域状态。 |

## Refactoring rules

- 每次只按一个可验证职责拆分：例如参数注册、输入解析、纯计算、持久化适配或输出渲染。
- `qount.main:main`、`qount-monitor`、测试导入路径和部署引用都是兼容表面；先加转发或重新导出，再考虑迁移。
- 公共 CLI 的参数、默认值、帮助文字、错误码和 `config-check` 的无副作用特性都要有针对性回归。
- 共享计算逻辑进入已有的公共域或 `research_data/`；不要在多个策略线复制公式、序列化或路径处理。
- 对超过单一职责的模块，先抽取无副作用的协作者并保留原文件为协调层。不要在没有测试覆盖时重写大型运行时模块。
- 路径、artifact 和环境变量通过合同、模型对象或显式函数参数传递；不要将它们藏在脚本全局变量中。

## Current maintainability queue

当前最大的模块优先按风险分批处理，而不是一次性改写：`small_account/fomc_live.py`、`reporting/read_models.py`、`mini_trend/stablecoin_chain_events_remediation.py`、`risk_engine.py` 和 `mini_trend/pilot_dispatcher.py`。它们分别关联事件运行时、Dashboard read model、历史研究和风险/调度行为；后续拆分必须先锁定单元测试和公开/部署引用。

本批已将 `qount-run` 的 parser 注册从执行门面中分离，并把冻结 L1/L3/L4/L6 命令集中到独立注册表。行为、命令名称和处理器仍由原入口兼容地提供。

### First pure-collaborator extractions

四个高复杂度模块已经各完成首个可单测的无副作用协作者；原模块仍是运行时协调层并继续导出既有接口：

- `reporting/read_model_validation.py`：Dashboard payload 的结构、数值、集合与 freshness 校验；`read_models.py` 保留原私有函数名作为别名。
- `mini_trend/pilot_dispatch_views.py`：交易所时间、数值、仓位和订单视图归一化；不包含交易所调用、计划构建或 journal 写入。
- `risk_state_keys.py`：日初净值和持仓管理状态键；`risk_engine.build_day_start_equity_key` 及三个 `RiskEngine._…key` 方法仍可调用。
- `small_account/fomc_market_rules.py`：Binance USD-M 市场规则归一化与稳定错误类型；预检、arm、账户状态和订单路径仍在 `fomc_live.py`。

下一批应优先从各运行时模块中继续提取纯验证/计划函数，并先为新接口编写定向测试；不要移动 FOMC 安全存储、dispatcher 调用或风险策略阈值树，除非其完整回归覆盖已单独锁定。
