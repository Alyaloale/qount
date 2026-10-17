# Research code

研究问题优先，复用已有数据和计算；不同研究线分别保留参数、状态和结果。

- `lines/macro_1atr.py`：当前宏观规则的独立回放，复用原生行情、宏观ETF特征和容量缓存；基础／双成本分别保存。
- `lines/one_atr.py`：已退役简化规则的历史对照，与当前宏观实盘规则不同。
- `lines/simple_trend.py`：固定SMA120+20日动量基准，按数据可用时间生成特征；原生候选时点不补造上市前历史。与原宏观共用账户、成本、仓位与分钟容量计算。
- `engine/`：共享仓位、合约账户、标准净值指标与精确输入的结果复用。
- `qount.research_data`：行情读取、时点和公共特征；不从停止的策略实现导入工具函数。
- 既有 A 股、ETF、Dual-Engine、模型等模块按需要逐步归入本线，不做全仓搬迁。
- 旧突破/通用状态路径只是历史导入兼容，真实实现位于 `qount.legacy`，不作为新研究入口。

默认输出 `state/research_runs/<line>/<run_id>/summary.json`、`nav.json`、`trades.json`。同输入、代码和参数可复用；新实验不覆盖旧实验，各线不共享可写持仓或模型。已消费历史在任何目录里仍是已消费历史。

结果写入临时目录，完整后原子发布；身份包含实际代码依赖、输入内容、参数与Python版本，物理主机路径不决定结果身份。宏观特征单独复用，改变交易成本不重算特征。`config/paper-lines.json`明确指定展示run，API提供本线其他完整run；不按文件mtime选择结论，曲线和成交始终绑定同一run。

结果保留区间、标的、资金、成本、基准、样本身份和限制；研究产物 `research_only=true / orders_authorized=false`。研究清单、运行事实和冻结边界见 [current](../../../docs/current.md)。

成本归因入口为`scripts/research/diagnose_macro_1atr_costs.py`，结果在`macro_cost_attribution/`；简单趋势对照入口为`scripts/research/compare_macro_simple_trend.py`，结果在`macro_simple_baseline/`。成本归因的空`nav.json`明确表示没有固定路径回测曲线；基准对照则保存各情景完整曲线。复现命令见[研究入口](../../../scripts/research/README.md)，结论集中维护在现有计划与current，不另建台账。

针对新增成本归因与简单特征的测试为`tests/test_macro_cost_attribution.py`和`tests/test_simple_trend_baseline.py`，覆盖资金费/滑点拆分、观察函数恢复、未来价格不影响过去信号、收盘可用时间与原生上市范围。均值回归7/21天持有实验尚未执行。
