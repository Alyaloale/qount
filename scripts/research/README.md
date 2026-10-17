# Research scripts

研究入口只负责参数和调用；代码与数据按研究问题复用，不为一次实验新增服务或阶段流水线。

当前独立原生合约例子：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/run_one_atr.py
PYTHONPATH=src ./.venv/bin/python scripts/research/run_macro_1atr.py
PYTHONPATH=src ./.venv/bin/python scripts/research/run_macro_1atr.py --scenario double_cost
PYTHONPATH=src ./.venv/bin/python scripts/research/diagnose_macro_1atr_costs.py
PYTHONPATH=src ./.venv/bin/python scripts/research/compare_macro_simple_trend.py
```

这些入口默认只读取已有缓存，输出按各自研究问题和`run_id`隔离。相同输入、代码和参数再次运行直接复用结果；默认没有下载、训练、账户请求或订单。

`one_atr`是已退役简化规则对照；`macro_1atr`为当前宏观规则回放，输出按`macro_1atr/<run_id>/`隔离。使用原选定参数与保留输入，不重新选参；基础与双成本是独立实验，可在研究页切换及同窗对照。

`diagnose_macro_1atr_costs.py`复现原基础/双成本回放，区分固定成交路径的直接成本与账户路径残差，输出`macro_cost_attribution/<run_id>/`。固定路径不是可执行回测，`nav.json`为空，不生成虚构回撤。逐笔归因保留闭合/截尾身份，实际仓位计算尝试保存在摘要中。

`compare_macro_simple_trend.py`比较固定SMA120+20日动量与原宏观规则，采用相同事前预算上限、成本和分钟容量约束，输出`macro_simple_baseline/<run_id>/`的八组完整曲线与成交。简单特征位于`src/qount/research/lines/simple_trend.py`。493个新增公开分钟窗口已另存，当前复现无需下载；只有显式`--download-missing`才补缺失窗口，不改写原缓存。该组结果留在本地研究目录，未自动登记到线上研究列表。

25%预算对照复用同一宏观入口和现有参数文件：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/run_macro_1atr.py --review state/research_inputs/macro_risk_budget_25/review.json --scenario base
PYTHONPATH=src ./.venv/bin/python scripts/research/run_macro_1atr.py --review state/research_inputs/macro_risk_budget_25/review.json --scenario double_cost
```

参数文件及完整曲线、成交、行情缓存保留在本地`state/`，不会因代码记录而重新生成或覆盖。关键结果和限制集中见[整理与研究计划](../../docs/personal-system-consolidation-plan.md#下一步研究先解释净收益与本金风险)，当前事实见[current](../../docs/current.md)。本轮先记录文档和代码，均值回归7/21天持有实验尚未执行。

现有 Binance 宏观、A股、ETF、模型和采集入口按本线保留；当前运行和冻结事实见 [current](../../docs/current.md)。旧突破、传统策略、crypto-trend、ETF并行搜索、通用状态历史审计和R0版本修订位于 [归档](../archive/research-legacy/)，不从归档自动恢复运行。

旧P2计时、监控、性能分析及stale试验辅助脚本已移至归档`p2-tools/`；不再作为活动入口。
