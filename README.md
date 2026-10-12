# qount：个人量化交易助手

> **目标**：构建简洁、务实、服务个人实战盈利的 AI 量化交易助手。
> **当前事实**：[docs/current.md](docs/current.md) 是运行登记、研究裁决与 owner 决策的唯一来源。

## 当前研究定位

聚焦 1–3 只核心高流动性资产、低频操作、真实费用和大回撤控制。个人账户可以按规则降低仓位或转现金；趋势过滤的样本内防御价值仍需与收益损失、假突破和实际执行一起评价。

**麒麟与币安多资产合约的旧高收益结论已撤销，研究封存。** Q-DIV-Core 和 C60 梯度候选失败保留；ETF 神经模型尚未证明相对简单基线的增量。既有 paper 是公共数据无订单模拟，不是实盘业绩。

年换手 <0.5x 属于设计目标，不能从交易笔数推定已达标；集中持仓、ETF 载体和止损也不保证保本。后续优先级、逐线问题与验收条件见 [修补整理计划](docs/research-repair-and-consolidation-plan-2026-10.md)。

## 研究与产品范围

| 方向 | 可验证的问题 |
| --- | --- |
| 少量 A 股／跨境 ETF | 趋势与现金切换能否改善个人账户回撤，真实成本如何影响收益 |
| BTC／ETH | 简单现货基线及独立新信息是否具有扣费后的增量 |
| 质量／红利／低波选股 | 经营、现金流、估值和趋势能否支持新鲜的研究候选 |
| 跨资产配置 | 冻结 CTA-R 与 Dual-Engine 的实现、成本和前向一致性 |
| AI 助手 | 因果信号、确定性风险摘要、看板和通知如何减少个人重复操作 |

每项研究单独维护来源、窗口、代码版本和停止条件；数据规模、模型容量和报告数量不等于盈利证据。

## 开发与验证

Mac 负责代码、Git、文档和轻量验证；WSL 负责已明确范围的 CPU／GPU 计算，完整公开数据与工件留 Windows E 盘。VPS 既有服务按自身运行合同处理。

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
```

## 安全与执行边界

默认 `research_only=true / orders_authorized=false`。未经 owner 明确授权不得启用或触发生产下单、交易 timer 或 cron。完整收盘信号在收盘后生成，下一交易时点尝试执行；盘中只作预览，不假定止损价必成交。

凭据不打印、不复制、不提交、不传 WSL／E 盘；Mac 私有配置保持 0600。已冻结线路不恢复，原结果与不可变工件不覆盖。

## 文档入口

- [当前事实](docs/current.md)
- [研究线导航](docs/research-lines.md)
- [修补整理计划](docs/research-repair-and-consolidation-plan-2026-10.md)
- [个人交易助手指南](docs/personal-trading-assistant-guide.md)
- [快速接手](docs/quick-handoff.md)
- [项目规则](docs/project-rules.md)
- [主机手册](docs/operations/host-runbooks.md)
- [系统架构](docs/system-architecture-design.md)
- [历史归档](docs/archive/README.md)
