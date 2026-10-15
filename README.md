# qount：个人量化交易助手

> **目标**：提高个人账户长期实盘风险调整后财富增长，以实验和可重复证据推动迭代。
> **开发指引**：[AGENTS.md](AGENTS.md) 定义自主研究、工程执行和权限底线。
> **当前事实**：[docs/current.md](docs/current.md) 是运行登记、研究裁决与 owner 决策的唯一来源。

## 当前研究定位

优先评价净 CAGR、最大回撤、Calmar、样本外稳定性、实际可执行性和资源效率。允许研究趋势、轮动、多因子、Transformer、强化学习和混合策略；资产数量、集中度、持有现金与交易频率由实验比较决定。

**麒麟与币安多资产合约的旧高收益结论已撤销，研究封存。** Q-DIV-Core 和 C60 梯度候选失败保留；ETF 神经模型尚未证明相对简单基线的增量。既有 paper 是公共数据无订单模拟，不是实盘业绩。

1–3 只核心资产与年换手 <0.5x 是既有助手方案的目标，不是全项目限制；20% 年化等目标也不代表已实现收益。当前任务、冻结决定与下一步看 current；逐线问题与历史修补顺序见 [修补整理计划](docs/research-repair-and-consolidation-plan-2026-10.md)。

## 研究与产品范围

| 方向 | 可验证的问题 |
| --- | --- |
| 少量 A 股／跨境 ETF | 趋势与现金切换能否改善个人账户回撤，真实成本如何影响收益 |
| BTC／ETH | 简单现货基线及独立新信息是否具有扣费后的增量 |
| 质量／红利／低波选股 | 经营、现金流、估值和趋势能否支持新鲜的研究候选 |
| 跨资产配置 | 冻结 CTA-R 与 Dual-Engine 的实现、成本和前向一致性 |
| 模型与策略学习 | 新特征、Transformer、RL 或集成是否相对简单基线带来稳定的净增量 |
| AI 助手 | 因果信号、确定性风险摘要、看板和通知如何减少个人重复操作 |

以“假设 → 最小实验 → 结果 → 改进”推进，每项研究保留来源、窗口、版本和停止条件；重要结果同时报告成本、收益、回撤、基准与样本属性。

## 开发与验证

Mac 负责代码、Git、文档和轻量验证；WSL 负责已明确范围的 CPU／GPU 计算，完整公开数据与工件留 Windows E 盘。VPS 既有服务按自身运行合同处理。

先检查工作区并保留已有修改；局部代码执行针对性测试，研究候选补样本外证据，生产候选再扩大验证。纯文档检查链接、事实和格式。具体命令见 [本地开发](docs/operations/local-development.md)。

## 安全与执行边界

默认 `research_only=true / orders_authorized=false`。授权范围内的离线研究、仿真和纸面交易直接推进；实盘下单、交易定时器、生产服务及账户配置变更须有 owner 明确授权。完整收盘信号在收盘后生成，下一可交易时点尝试执行；盘中只作预览，不假定止损价必成交。

凭据不打印、不复制、不提交、不传 WSL／E 盘；Mac 私有配置保持 0600。已冻结线路不恢复，原结果与不可变工件不覆盖。

## 文档入口

- [Agent 开发指引](AGENTS.md)
- [当前事实](docs/current.md)
- [研究线导航](docs/research-lines.md)
- [修补整理计划](docs/research-repair-and-consolidation-plan-2026-10.md)
- [个人交易助手指南](docs/personal-trading-assistant-guide.md)
- [快速接手](docs/quick-handoff.md)
- [项目规则](docs/project-rules.md)
- [主机手册](docs/operations/host-runbooks.md)
- [系统架构](docs/system-architecture-design.md)
- [历史归档](docs/archive/README.md)
