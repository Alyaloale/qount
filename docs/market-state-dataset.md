# 当天市场状态数据集规范

本页定义本轮逐日状态学习的数据接口。owner当前决定与研究状态以[docs/current.md](current.md)为准。旧研究工件保留，当前入口不自动读取它们。

## 当前范围与入口

- Schema：`current_state_complete_crypto_v2`。
- 当前目录：`state/research_runs/market_state_complete_20261101/`。
- 7个币种，14,588条完整监督样本；每币2,084条，2021-01-28至2026-10-12（按原生K线开盘日）。
- 当前只使用两周参考尺度n=14，默认输入14根日线，28根用于更长上下文对照。参考尺度不是预测偏移或固定持仓时长。
- 预测目标：当天`S_n(k)`。离线标签窗口为`[k-n+1,k+n]`共2n根，到k+n才成熟。
- 缺失字段、缺失上下文和未确认监督答案不进入当前训练数据。零成交/零费率的真实零值不等于缺失；不会以零填充未知字段。

```python
from qount.research.market_state_dataset import CurrentStateDataset

ds = CurrentStateDataset()  # 加载时校验schema、完整性、时间和标签角色
x = ds.inputs([0, 1], lookback="n")
# x["market"]: [2, 14, 9]；x["asset_index"]: [2]
y = ds.targets([0, 1])
# state、attributes、changed、available_at；这些不进入x
```

旧schema不能通过该读取器静默加载。负索引、越界索引和浮点索引会报错，防止缺失索引`-1`取到数据末尾。

## 输入字段与价格单位

`market_names`固定为下列顺序；O/H/L/C为币安USDT本位合约原生价格，成交量为基础币数量，成交额为USDT，成交笔数保留整数含义。

|序号|字段|含义|
|---|---|---|
|0–3|open / high / low / close|开盘、最高、最低、收盘价格|
|4|base_volume|基础币成交数量|
|5|quote_volume|USDT成交额|
|6|trade_count|成交笔数|
|7|taker_buy_base_volume|主动买方发起的成交数量|
|8|taker_buy_quote_volume|主动买方发起的成交额|

模型读取逐根九列，不读取人工趋势指标。价格仅相对窗口第一根收盘价取对数，其他非负原生字段做log1p，保留原始副本；训练均值/标准差必须由当折训练行拟合。

当前训练默认`state_with_transition`：原GRU独立估计三类主状态，另一个小GRU学习延续／上行初期／下行初期／震荡初期四类辅助阶段及两个连续边界目标。主状态概率保持原模型结果，阶段概率不强制混入主分类。阶段定义是当天处于本段前3日，不能解释成预测未来3天会切换；主市场状态仍只有三类。

辅助目标由`transition_targets()`单独构造，段龄只作为监督；未知初始段龄的阶段损失被屏蔽，不伪造确定答案。当前段龄由已成熟的当前及前序标签定义，不使用段终点或剩余长度；全部辅助目标仍在k+n成熟。连续目标为方向分数和带符号的斜率/日振幅效率，与既有四个属性标签分开。训练可用历史价格/主动方向变化挑选成熟难负例，但这些诊断量不新增为推断通道。

连续目标的价格上下文由本完整集的历史窗口和`latest_inputs.npz`保留窗口重建，不依赖旧候选父目录。重叠原生价格必须逐值一致，缺少目标所需未来价格时明确报错，不代填。已在父目录路径不可用的情况下，全14,588条辅助目标与训练时目标逐值核对一致。

阶段校准只使用早于本季度、且标签已经成熟的历史前推预测（过去365日）。本季度标签不进入校准；历史不足时保留未校准输出。主状态校准和联合混合主状态均未取得优势，默认不采用。旧单模型通过`--model gru`保留，联合混合版本仅通过`--model typed_transition`作对照。

主动卖出量/额可由总量减主动买入还原。`flow_diagnostics`保存买卖量/额及主动买卖成交额差，仅作代数核对；默认不重复拼入输入。这些量描述成交主动性，不是交易所净充值或外部资金净流入。

## 文件与字段角色

|文件/字段|形状或单位|角色|
|---|---|---|
|dataset.npz / asset、source_symbol|N|真实币安合约标识|
|source_dataset、source_row|路径、N个父数据行号|可追溯父数据；不是模型特征|
|market|N×9，float64|当天原始九列|
|n_raw_market / two_n_raw_market|N×14×9 / N×28×9|完整已收盘原始序列，按旧到新排列|
|n_scaled_market / two_n_scaled_market|同形状，float32|窗口内量纲缩放后的模型输入|
|n_source_rows / two_n_source_rows|N×14 / N×28|父数据行号，最后一根必须是样本当天|
|bar_open_at / bar_close_at|UTC epoch毫秒|原生开盘/收盘时刻|
|decision_at / market_available_at|UTC epoch毫秒|沿用收盘后一分钟决策约定；当前为bar_close_at+60,001ms|
|state / state_names|N，0/1/2|监督：上行/下行/震荡，不包含“转换待确认”类别|
|attributes / attribute_names|N×4|监督：收缩比、收缩标记、日波动率、路径效率|
|previous_state_label / switch_label|N / N布尔|辅助监督：上一日事后标签与当天是否切换；不是当天已知状态|
|label_available_at|UTC epoch毫秒|监督答案可确认时间：decision_at+n天|
|label_context_source_rows|N×28|事后标注窗口行号，含未来；禁止作为输入|
|latest_inputs.npz|7条完整末日输入|不含状态/属性标签，供估计缓存末日当天状态|
|funding_events.npz|原始结算事件|完整费率、时间、类型；无缺失markPrice列；默认不进入模型|

所有默认输入及监督标签均无NaN，不需要逐行补值掩码。原始候选中的缺失列不在当前模型字段集合内。

## 当前主标签的实际规则

当前`state`继承原五类的`merged_three`：先以加权方向分数阈值±0.5和斜率/日振幅效率门槛0.1判断上/下行，再应用原固定28根窗口内的`pair_combined`边界规则，最后把轮动、收缩、低效率震荡合并为震荡。实现见[基础证据](../src/qount/research/market_daily_states.py)、[边界规则](../src/qount/research/market_state_boundaries.py)及[三类来源](../scripts/research/compare_market_state_factorizations.py)。四个属性单独保存；此处斜率/日振幅效率与属性中的路径效率是不同的量。

此前备选`factored_three`仅用方向分数划分类别，当前未采用；完整集两者有1,557条（10.67%）标签不同。11月1日已从原生上下文全量复现当前标签并核对来源，保留现有标签进行切换学习对照，不因备选定义更容易预测就自动替换。边界修正相对原五类基础规则仅影响44条，不能把全部切换困难归因于该边界修正。见[切换诊断](../state/research_runs/market_state_switch_diagnosis_20261101/report.md)。

## 监督与推断的区别

训练需有成熟答案，因此剔除末尾缺少未来n根的98条币种记录；这不意味着推断需要等n天。缓存末日的七条完整行情输入单独保存，未伪造未来标签：

```python
latest = ds.latest_inputs()
# market [7,14,9]，asset_index、asset、decision_at、source_row
# 这是现有缓存2026-10-26日线的输入，不是实时行情。
```

`inputs()`与`latest_inputs()`不会返回state、attributes、switch_label或真实段龄。数据中不包含“待确认”监督类别；概率不突出的解释属于模型输出层。

新默认权重可离线推断，输入仍为上述窗口内缩放值，训练折标准化由推断函数读取保存参数完成：

```python
import torch
from qount.research.market_state_transition import infer_state_with_transition

checkpoint = torch.load("state/research_runs/market_state_transition_default_20261101/latest.pt",
                        map_location="cpu", weights_only=True)
latest = ds.latest_inputs()
output = infer_state_with_transition(checkpoint, latest["market"], latest["asset_index"])
# state_probabilities [7,3]、phase_probabilities [7,4]、early_trend_probability [7]
# continuous_predictions [7,2]；不读取真实状态、段龄或未来行情。
```

默认只输出概率，没有启用自动切换告警或交易。阶段概率目前是弱研究信号，其相对成熟频率基线的Brier差异区间仍跨零；不能据此宣称首日识别问题已经解决。见[修复验证](../state/research_runs/market_state_transition_repair_20261101/report.md)。

## 时间切分与标准化

```python
train, test = ds.split(cutoff_ms, end_ms)
# train: label_available_at < cutoff_ms
# test: cutoff_ms <= decision_at < end_ms
```

按时间滚动，每折只使用截止前已成熟标签，禁止随机分行后宣称独立样本外。重叠窗口及同市场标的相关性需在结果解释中保留。辅助切换监督需要的前一天标签早于当天标签成熟，不额外使用k+n之后的信息。

真实段龄、完整段长和剩余时长仍只在离线分析文件中；不作为实时输入。若以后按完整段长筛选训练样本，还需确认段结束在训练截止前已知。

## 暂不使用的数据

- ETF/商品代理：缺主动成交等原始字段，且供应商quote/复权快照口径不同，本轮整组不进入当前模型。
- OI及多空结构：只有BTC/ETH/SOL部分日期，不使用覆盖零散的输入块。
- 资金费率结算markPrice：历史有缺失，当前不使用该列，也不代填。
- ETF复权因子、净申赎、交易所净出入金：快照时点未认证或缺可靠原始序列，不使用。
- 资金费率原始结算上下文：保留完整记录，但首次发布时间未实测；当前默认训练不开启。仅离线研究明确允许1分钟发布时间假设时可用`ds.funding(..., allow_assumed_timing=True)`读取，不混入默认九列。

旧候选的OI、资金费率事件、ETF资料继续保留在原目录，不挪动、删除或把缺失改成零。

## 构建与实际读取入口

```bash
# 构建完整集，已有输出不会被覆盖；复现时用新的--output目录
PYTHONPATH=src ./.venv/bin/python scripts/research/build_market_state_complete_dataset.py

# 九通道读取/训练流程检查；只一折一轮，不用于报告性能
PYTHONPATH=src uv run --no-project --with 'torch==2.13.0' --with numpy --with scikit-learn --with threadpoolctl --python .venv/bin/python python scripts/research/train_market_state_current.py --smoke --output state/research_runs/market_state_complete_smoke_new
```

当前模型入口是`train_market_state_current.py`，其默认数据由`CurrentStateDataset`提供。旧`compare_market_state_raw_sequences.py`仅保留历史五通道/十五标的对照，不代表当前使用范围。`--smoke`结果不能当成完整训练或新准确率；既有五通道模型指标也不自动适用于新数据。

本轮配对训练为逐值复现此前基线，使用隔离环境Torch2.15.0、NumPy2.5.1、scikit-learn1.9.0、SciPy1.18.0；没有改变项目的Torch2.12～2.14依赖范围。项目范围内Torch2.13.0已通过18项相关测试及保存权重的离线推断验证，不将其称为重新训练的性能结果。完整对照可用相同隔离版本运行`train_market_state_transition.py --output 新目录`复现。

|目录|用途|
|---|---|
|market_state_complete_20261101|当前完整九通道训练集和缓存末日输入|
|market_state_native_flow_dataset_20261101|包含缺失块的原生字段/事件候选，非默认训练输入|
|market_state_current_raw_sequences_20261101|历史五通道当天状态对照|
|market_state_raw_sequences_20261101|历史预测n天后状态对照|
|market_state_dataset_distribution_20261101|历史十五标的分布及事后段龄诊断|

本轮只规范数据和读取代码；不更新线上服务、不授权交易。当前事实和验证结果见[current.md](current.md)。
