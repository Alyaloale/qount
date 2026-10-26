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

`run_macro_1atr.py --mr-hold-days 7`或`21`仅调整离线MR最长期限，可与`--scenario base`或`double_cost`组合，四组结果分别保存；未传此参数沿用原配置，不改变实盘规则。

`compare_macro_funding_headroom.py --output <新路径>`复用10月19日缓存与对照，检验MR初始定仓预留10%压力预算，保留原总风险/资金费预算与退出规则；输出12组组合、80次成对单事件及闭合episode统计。放大容量组仍是未验证成交的反事实；拒绝覆盖旧结果，不接入实盘。

`compare_macro_depth_execution.py --output <新路径>`比较原量代理与固定限价内折扣盘口定仓，含延迟、部分/零成交、90秒截止与退出深度核对；`--download`仅补缺失的官方公开档案并验证checksum。18组均为条件成交压力研究，存留比例未经校准，缺失/不一致退出盘口保留未知，不接入实盘。

`compare_macro_exit_depth.py --output <新路径>`接续该盘口研究，运行29组全仓退出、缺失盘口价格压力、统一退出冲击与25%/50%预算对照，包含退出延迟内结算及逐笔账本重算；`--download`仅补实际触及的公开档案。缺失盘口的假设全平不代表已验证成交。`sample_macro_depth.py --seconds 120 --output <新路径>`只读采样XLE/IWM/CL公开L2，限60–180秒；固定限价比较后续可见数量，不能把夜间样本当作日间成交率，不启动持续服务。

`diagnose_macro_return_sources.py --output <新路径>`固定统一50bp退出冲击，对原成交量约束和盘口定仓做逐episode/资产剔除及全部20个合格信号单事件对照，共64次回放。剔除为事后脆弱性诊断，完整重算后续机会和仓位；单位名义收益、闭合/截尾、拒绝原因与逐笔成本同时保留，不将影子相加或按历史输赢生成交易规则。`--download`仅补实际触及的公开档案。

`compare_macro_risk_candidate.py --output <新路径>`保留原成交量约束，完成40组25%预算、2x名义上限、邻近预算与相同机会缺失对照，并在研究进程内核对16个既有实盘纯策略函数入场样例，结束后恢复调用前的常量。结果明确区分闭合/截尾、异常退出冲击及资金费路径；研究入口不会发布或改写生产。实际预算采用情况见`docs/current.md`。

`diagnose_macro_1atr_costs.py`复现原基础/双成本回放，区分固定成交路径的直接成本与账户路径残差，输出`macro_cost_attribution/<run_id>/`。固定路径不是可执行回测，`nav.json`为空，不生成虚构回撤。逐笔归因保留闭合/截尾身份，实际仓位计算尝试保存在摘要中。

`compare_macro_simple_trend.py`比较固定SMA120+20日动量与原宏观规则，采用相同事前预算上限、成本和分钟容量约束，输出`macro_simple_baseline/<run_id>/`的八组完整曲线与成交。简单特征位于`src/qount/research/lines/simple_trend.py`。493个新增公开分钟窗口已另存，当前复现无需下载；只有显式`--download-missing`才补缺失窗口，不改写原缓存。该组结果留在本地研究目录，未自动登记到线上研究列表。

25%预算对照复用同一宏观入口和现有参数文件：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/run_macro_1atr.py --review state/research_inputs/macro_risk_budget_25/review.json --scenario base
PYTHONPATH=src ./.venv/bin/python scripts/research/run_macro_1atr.py --review state/research_inputs/macro_risk_budget_25/review.json --scenario double_cost
```

参数文件及完整曲线、成交、行情缓存保留在本地`state/`，不会因代码记录而重新生成或覆盖。关键结果和限制集中见[整理与研究计划](../../docs/personal-system-consolidation-plan.md#下一步研究先解释净收益与本金风险)，当前事实见[current](../../docs/current.md)。均值回归7/21天及后续自然闭合对照已执行，按各自报告的窗口和样本身份解读。

现有 Binance 宏观、A股、ETF、模型和采集入口按本线保留；当前运行和冻结事实见 [current](../../docs/current.md)。旧突破、传统策略、crypto-trend、ETF并行搜索、通用状态历史审计和R0版本修订位于 [归档](../archive/research-legacy/)，不从归档自动恢复运行。

旧P2计时、监控、性能分析及stale试验辅助脚本已移至归档`p2-tools/`；不再作为活动入口。

`compare_etf_risk_budget.py --output <新的空目录>`用已有实际ETF原价日线比较买持、MA120、固定75%及固定20日/15%波动预算，包含整手、最低佣金、次日/延迟开盘、成本压力与本金敏感性。事后平均仓位匹配仅为诊断，失败组合、各年结果与跨标的负面结果一并保留。输出`results.json`和简短`report.md`，无行情下载、训练、账户或订单路径；当前结论见current。

`analyze_g20_risk_budget.py --root <已保存的公开输入目录> --output <新的空目录>`拆解原G20模拟的窗口、资产净贡献、仓位漂移与BIL分红遗漏；统一线上adjClose信号后，用现有现金/单位引擎比较月度、周度、固定波动上限及QQQ对照，另保存初始等资本、不跨账户再平衡的组合诊断。旧raw-close研究控制独立复现，不覆盖历史；无行情请求、训练、真实账户或订单路径。输入位置、结果与限制见`state/research_runs/g20_risk_synthesis_20261025/report.md`及current。

`compare_g20_fixed_budget.py --output <新的空目录> --include-macro`比较月度20%/18%/15%/10%、周度18%与原动态波控，用独立现金/单位核算器验证长短窗，并复用已发布分红账本重跑100/1000/10000美元整数股账户；可选宏观比较保留原容量/费用门，对三档规模完整重跑，而不是放大15U净值。18%是事后平均暴露诊断，历史样本不称独立OOS，无新行情/订单/生产修改。

`compare_g20_carriers.py --output <新的空目录>`保持G20行业选择和时钟，比较实际杠杆ETF与一倍代理ETF；仅用决策前20日收益、包含BIL协方差的组合风险匹配权重，禁止借款、不按当前杠杆倍数乘历史收益。原月度20%/15%及动态三组预算、成本/延迟完整保留；另明确标注看到归因后追加的保留SOXL诊断。60账本/资产归因及24旧控制核对，非独立OOS，不认证基准等价或整数股执行，不改变线上。

`compare_g20_semiconductors.py --output <新的空目录> --soxx <原始Yahoo chart缓存>`固定原SMH代理排名，只替换SOXL载体为SMH/SOXX，其他行业仍用原杠杆ETF。三个预算、基础/严格情景、长短窗共36账本，包含历史基准变更前/过渡/2022后连续账户诊断；额外SOXX输入完整校验，默认无网络请求或新采集。结果仅用于区分基准与载体混杂，不据同窗排序自动更换线上。

`compare_g20_cash_carriers.py --output <新的空目录>`使用既有2026公开缓存和分红政策，对原G20及仅SOXL换风险匹配SMH候选重算1000/10000美元现金账户。三个原预算×两个载体×八种执行情景，共96账本；单独隔离可分割份额、整股、佣金下限、双成本和延迟一日。基础费用为5bp佣金＋15bp滑点，最低佣金只作用于佣金，非券商完整价目；未到账分红不支出，延迟账户不以更早月末陈旧信号填充起始仓位。6个旧现金控制和已发布204点须逐点复现，现金/成交/分红核对后写出`results.json`和`summary.json`。复用现金账本纯函数的显式研究参数，默认线上调用不变；无行情请求、账户查询或订单路径。2026不是独立OOS，不认证长窗现金、税务和券商结算。结论见[现金执行检验](../../state/research_runs/g20_cash_carriers_20261026_final/report.md)。

五类策略的研究投入顺序、下一项最小实验和采用条件见[资产管理策略选择与设计依据](../../docs/asset-management-strategy-review-2026-10.md#5-五类策略的研究优化优先级)。这里只记录研究问题，不自动启动实验、服务或观察期。

Git保存实现、测试与上述文档摘要；`state/`中的行情缓存、完整逐日结果和账户/发布工件按现有忽略规则保留，不随代码提交。仅克隆仓库不能直接复现依赖这些缓存的数值，需另行取得报告注明的原公开输入；不复制凭据或从缺失输入推造成绩。
