# MiniTrend 复盘检查与优化

状态：v1.1 复盘结论。本文记录旧 TOP5、TOP3 forward、历史实盘订单审计和 UM no-carry 分支。

## 总判定

方向仍是交易核心确定性、LLM 只读审计和 400 USDT 阶段压低复杂度；但历史可成交性已经证明 TOP5
不适合作为默认。spot 基线冻结为 `long/cash + TOP3 + 1d`；owner 另指示资金统一进入 UM wallet、carry
关闭。UM recovery 已预登记但历史诊断拒绝，不能把它写成收益增强。

旧高收益也已完成更严格归因：X4 日线 artifact 只匹配到每日 00:00 funding，漏掉 08:00/16:00；完整
结算后 S3/S4 收益为 `+84.93%/+70.77%`，分别比旧 headline 低 `30.25/27.62pp`。高收益的主要机制是
1h→1d、去掉空头、SMA200 熊市走现金；2x cap 对两策略仅 `-1.17/+2.54pp` 且 Sharpe 都下降。因此合适的
后续不是恢复旧做空收益旋钮，而是保留 TOP3 日线 long/cash、no carry、无杠杆增益的 UM base v0.2。

随后预登记的 2.0% risk-tier 进一步确认：提高风险预算能把全窗收益从 `66.51%` 放大到 `103.29%`，
但 2025-2026 同时从 `-2.02%/8.04% DD` 恶化到 `-5.31%/13.78% DD`。它不是新 alpha，只是放大同一
beta timing；预登记弱市门拒绝后不再试中间值。因此“合适策略”最终定为 1.5% base v0.2。

进一步的三阶段 overlay 把 `BTC>SMA200`、`BTC SMA20>SMA60` 和 TOP3 breadth 叠加，只在 strong bull
复用 2.0% 风险档。它把全窗收益提高到 `85.94%`，却没有提高 Sharpe，并把 2025-2026 强牛标签内收益
从 `-1.45%` 放大为 `-3.91%`、阶段 maxDD 从 `6.00%` 加深到 `9.03%`。说明日线慢状态能躲开明确熊市，
但不能可靠地区分持续牛市与顶部/回落；不能用这个分类给同一 beta timing 加风险。预登记拒绝后保持 base。

随后使用既有 3xATR stop 作为无新阈值的风险反馈：连续 strong-bull 中第一次 stop 后只撤销 2.0% boost、
退回 base 1.5%，退出再进入 strong-bull 才重置。它把 2025-2026 修复到 `-1.83%`，全窗收益/Sharpe
提高到 `88.41%/0.945`，说明 stop latch 确有机制价值；但 2024-03..10 maxDD 仍为 `18.70%`，相对 base
恶化 `1.418pp`，超过预登记 `1pp`。这是近门但失败，不用事后把门放到 1.5pp；base 仍是唯一选择。

Owner 随后提供链上、宏观、ADX、动态风险、ML/Markov 和 funding 等外部建议。没有把建议当作事实；只将
已有完整缓存、可按发布时点因果对齐、且有直接经济含义的 lagged funding 作为成本 veto 实践。上一完整日
TOP3 funding 中位数简单年化 `>50%` 时，只把未锁定 strong-bull 的 2.0% 退回1.5%。17次 veto 后全窗
`88.95%/Sharpe 0.965/maxDD 18.11%`，全部历史门通过；但事件仅在2021和2023-2024出现，2025弱段改善仍
来自stop-latch。因此它是首选 consumed-history 候选，不是独立OOS或稳定跨周期alpha。

## 外部建议分流与新路线

| 建议 | 当前证据判断 | 路线决定 |
| --- | --- | --- |
| 已完成 funding 过热过滤 | 本地完整结算可因果对齐，直接对应持仓成本 | 已预登记实测并历史retain；阈值冻结50%，不扫参 |
| MVRV/SOPR/LTH/Realized Cap/交易所净流入 | Coin Metrics免费latest-vintage已验证MVRV、算力和交易所流；SOPR/Realized Cap/LTH受限且没有历史vintage | 已完成source G0与单因子审计；只保留算力研究，promotion前必须补vintage或真实forward |
| 美联储/央行资产负债表/美元流动性 | 必须绑定实际发布时间、数据vintage和交易可见时点 | 先做release-calendar G0，禁止按最终修订值回填 |
| 恐惧贪婪/社交情绪 | 方法学、供应商历史和可复现性不足 | 只列候选源，不作为当前硬闸 |
| ADX趋势强度 | 既有9折walk-forward未改善Sharpe，且多数折DD更深 | 不复活，不换20/25阈值重试 |
| 动态ATR、时间止损、梯度deadband | 参数自由度高，容易针对2024回撤过拟合 | `research_sandbox`重开，记录完整trial并与静态基线做消融 |
| gross 1.1-1.2或更高杠杆 | 旧2x归因无稳健Sharpe增量，当前gross<=1是硬约束 | 拒绝 |
| 闲置资金收益/carry | Owner明确全部资金进UM且carry关闭 | 拒绝 |
| RF/XGBoost/LSTM/Markov切换 | 特征与标签尚无独立验证，模型会放大数据窥探 | 立即进入个人discovery；tabular作基线，sequence可并行实验，不得伪称独立OOS |
| 叙事感知扩币 | point-in-time叙事标签与幸存者偏差不可控，且偏离TOP3 | 保留后续实验，先建立带发布时间的叙事标签和幸存者审计 |

新目标路线：正式选择仍是base v0.2；funding-veto v0.1冻结为首选历史候选，只接受未来独立数据验证，
不再调50%阈值。其短期路径审计已完成：预登记配对20日循环区块Bootstrap的5000条路径中，终值收益、
Sharpe和更低maxDD胜率为 `58.90%/86.82%/75.72%`，全部门通过；但收益胜率仅边际，且收益增量
`p05=-4.19pp`。进一步精确归因显示，终值增益82.68%来自funding节省，但事件日 `+1.842pp` 被下游路径
`-1.306pp` 抵消，17个veto传播为696个非事件差异日。所以证据支持成本过滤机制，却不支持稳定收益alpha；
未来验证必须完整重放状态。状态衰减进一步发现首次同步中位46日但只有最后事件在324日后稳定同步，且13个
无新事件spell由权益/deadband触发再发散；所以shadow forward不能在权重首次相同时停止。双状态v0.2合同已从
`2026-07-19`冻结，两路径同资金同现金启动，并只评估价格连续、决策日/持有日funding结算完整的前缀；当前
0根eligible且未读收益。

2026-07-18 owner将本线切换为个人实验`research_sandbox`。旧历史门继续约束“能否晋级”，不再约束“能否
实验”。现有三阶段规则已给1776日产生684 strong-bull、333 transition/range、759 bear/cash因果状态，但
训练目标不直接复制均线规则；新增30日波动率归一化triple-barrier未来标签，point-in-time特征先覆盖收益、
均线距离/斜率、breadth、ATR/波动率、相关性、回撤和完整funding。模型顺序为Logistic/HGB/LightGBM基线，
HMM/Markov和小型GRU/LSTM/TCN可并行实验；所有已看历史结果标discovery并记录trial。动态ATR/deadband作为
预测概率后的独立消融层。宏观、链上和叙事允许研究，但必须先解决历史发布时间与point-in-time对齐。

首轮实践已完成而且没有产生可接策略的模型。1765行未来标签为bear/bull/range=`401/526/838`；四个监督
tabular模型的平均概率质量全部输常数先验。HMM虽有平均Brier uplift `+0.013493`和3/4折改善，但硬分类偏向
range/bull，2023为负；trial 2的50%先验收缩、HMM状态后验增广和HMM/Logistic等权融合均未超过它。固定小型
GRU平均Brier uplift `-0.029635`、仅2/4折为正；A10二次复跑四折权重hash完全相同。因此当前停止结构扫参，
保留HMM为待审计的弱概率特征。

后续经济审计已经完成。原HMM风险分数与未来30日TOP3收益反向，12个目标敏感性、40个直接经济模型与40个
DVOL增强模型均无保留。24格滚动适应矩阵虽找到`60d/365d RF`排序信号，固定10,000次确认也通过7/7，但
3个只降风险规则全部失败：最佳少赚`12.216pp`只换来`0.878pp`回撤改善。因此价格/funding/DVOL模型家族
已停止，不用动态ATR/deadband包装。

第一轮新增低频信息只保留BTC算力。Coin Metrics官方社区数据在WSL直落外置盘，2020-2026覆盖1.0，但没有
历史vintage，全部只能算latest-vintage discovery。严格2023-2026审计中，`hashrate_z90`的rank IC为
`0.159730`、60日高低组差`+9.959pp`、bootstrap正差`98.95%`且p05为正；加入原滚动RF后rank IC升到
`0.179447`并通过9/9比较门。不过策略复用同一冻结风险规则仍0/3：最佳Sharpe提高`0.0617`、maxDD改善
`0.862pp`，却少赚`4.795pp`，超过预登记3pp代价。它是“有预测信息、没有通过策略兑现”的研究结果，
不得接forward/paper/live。

宏观G0和实践现已完成。Federal Reserve H.4.1官方archive提供真实release date，289条周报跨旧TXT、linked
HTML和inline HTML三种布局全部解析，特征在release后再滞后1日，稳定data hash为`8af65a47...cb02`。
三个固定特征中，4周资产变化把原滚动RF的rank IC/高低组差/bootstrap提高到
`0.202639/12.899pp/95.17%`，4周加速度也通过，13周变化未超过控制。唯一宏观+算力融合5/8拒绝；4周宏观
进入同一三档策略消融后仍0/3，最佳只因收益代价`3.323pp > 3pp`而8/9拒绝。累计trial为138。结论仍是
“存在排序信息、没有通过策略兑现”，不扫描窗口、组合、风险阈值或放宽3pp门。Coin Metrics真实future
vintage链已开始追加；下一步只接受真正新数据的future-only复核，或预先定义不同的低换手兑现机制。

这个“不同的低换手兑现机制”随后也已实践，而不是停在建议层。预登记只使用H.4.1 4周变化的经济零阈值，
只在Base新开仓或SMA200总闸退出事件上确认，不连续缩放仓位。收缩阻止开仓在633根日线上介入、阻止1,358个
symbol entry，使收益从`+66.505%`降到`+1.722%`；扩张延迟退出仅介入2根日线/4个symbol exit，收益
`+64.089%`、Sharpe从`0.8982`降到`0.8642`，maxDD只改善`0.046pp`；双确认收益仅`+0.341%`。3个trial
全部拒绝，累计trial为141。由此否定的是“符号状态二元许可”而不是H.4.1的排序信息；事件驱动只减少调用
次数，不能修复持续数月/数季的错误状态。后续不做10%/90%分位、5/10年窗口、20/45日冷却或投票权重救援。

又进一步测试了对Base伤害最小的兑现方式：宏观只决定strong-bull额外0.5%风险是否允许，不改变Base
1.5%、SMA200、止损或funding成本闸。唯一trial使用已有年度fold OOS标准分数的自然零点，`score<=0`只撤销
boost。结果在449个原本可boost日中否决303个，候选相对Funding Veto少赚`25.290pp`、Sharpe下降`0.1651`、
maxDD恶化`1.1621pp`，并且相对Base仍少赚`3.197pp`。这说明全时间轴60日rank IC不能外推为“技术强牛
子样本中的风险许可”；即使不碰Base目标，deadband、权益和latch路径也会把过多增益否决传播为长期损耗。
累计trial为142，不再调分数阈值、极端分位或叠加投票。

随后不再加预测信号，而是对Base本身做逐币episode归因。77段持仓精确对上组合净利润；吊灯退出贡献
`+403.61 USDT`，而30日以内持仓合计亏`-179.66 USDT`、31日以上赚`+445.68 USDT`。这直接否定了“收紧
ATR止损”和“时间止损”方向：策略依赖长右尾，过早退出会切掉核心利润。真正重复损耗是总闸仍开时单币
趋势条件失效后的快速重入；12次三日内重入后续合计亏`22.02 USDT`。

对此只复用已有3日止损冷却做了一个trial，不扫天数。历史点估计小幅改善：收益`+0.299pp`、Sharpe
`+0.0051`、maxDD改善`0.007pp`、订单少9；但Bootstrap收益/Sharpe/回撤胜率只有
`58.96%/64.42%/55.88%`，不能区分于路径噪声。累计trial为143，仍保持Base不变。

## 主要问题

| 问题 | 风险 | 优化 |
| --- | --- | --- |
| spot 和 swap 同时写成可选 | 400 USDT 账户容易用杠杆弥补本金不足 | spot 基线与 UM 研究分支隔离；UM 也不以杠杆补本金 |
| 只写 paper/dry 天数 | 可能“跑够天数但质量不合格” | 增加 scorecard 指标 |
| LLM agent 太早接入主流程 | agent 故障可能被误读为交易状态 | 初期只做日报和审计，不参与放行 |
| universe TOP5 还缺可成交性门 | 目标名义过小会导致权重失真 | min-notional coverage 成为硬指标 |
| stop latch 只写原则 | 无法判断修复是否真实有效 | 要求模拟触发 + dry/live 审计 0 次同信号重开 |

## v0.2 默认实现

```text
strategy=MiniTrend-5  # 保留 id 以绑定历史 anchor
market=spot
direction=long_cash
universe=BTCUSDT,ETHUSDT,BNBUSDT
capital_cap_usdt=400
live_pilot_cap_usdt=300
vol_target=0.015
rebalance_band=0.35
short_gate=false
carry=false
llm_runtime_gate=false
```

真钱控制仍只运行 `vol_target=0.015`；`vol_target=0.020`只作为首选收益shadow完整记录状态，不能控制订单。

## Scorecard

每次 backtest / paper / dry 结束必须输出同一张表。

| 指标 | 通过线 | 说明 |
| --- | --- | --- |
| max drawdown | spot paper <= 25% | 小盘先控制生存 |
| fee / notional | 与配置费率偏差 <= 20% | 发现费率或撮合口径错误 |
| order count | 不高于日线策略预期 | 防止 rebalance band 太窄 |
| min-notional coverage | >= 80% 目标名义可成交 | 低于则缩 universe 或降 gross |
| blocked symbols | 必须可解释 | 不能静默跳过核心 BTC/ETH |
| stop re-entry | 0 次同日线信号立即重开 | 当前 VPS 审计暴露过的问题 |
| unmanaged positions | 0 | 一次即 halt |
| schema errors | 0 | state 可重放 |
| LLM parse errors | 不影响交易主流程 | 只能影响报告完整性 |

## Promotion Gate

从 `backtest` 到 `paper`：

- scorecard 全字段存在。
- 使用真实 Binance filters / fees 假设。
- 至少包含 2021-2022、2023-2024、2025-2026 分段读数。
- 冻结 forward 至少 60 根完成日线，其中至少 10 根 active；当前 16 根全现金不满足。

从 `paper` 到 `dry`：

- 30 天 paper。
- 0 schema error。
- 0 stop re-entry。
- 目标权重和订单计划可重放。

从 `dry` 到 live pilot：

- 7 天 dry。
- 账户读数、filters、balances、positions 全可读取。
- unknown / unmanaged position 会 fail closed。
- API 权限只开必要交易权限，禁提现。

从 live pilot 扩到 400 USDT：

- 30 天 live pilot。
- 0 unmanaged position。
- realized fees 与预期一致。
- 所有 block / skip 都在日报里可解释。

## Agent 接入顺序

1. `DailyBriefAgent`：只读 state，生成日报。
2. `OpsAuditAgent`：检查 fills、fees、stop latch、unmanaged position。
3. `RiskReviewAgent`：解释 hard block。
4. `RedTeamAgent`：只评审 research proposal。
5. `ResearchAgent`：最后接，且只能产生 research proposal。

任何 agent 上线前必须先在 paper state 上离线跑 30 天历史报告回放。

## 后续优化队列

优先级从高到低：

1. 已完成：MiniTrend spot-only backtest core。
2. 已完成：scorecard、TOP3 可成交性和 beta 归因。
3. 进行中：冻结 TOP3 低频 forward monitoring。
4. 待门控：paper forward state 和 replay。
5. Dry-run exchange filter / balance 对账。
6. DailyBrief + OpsAudit agent。
7. 300 USDT、30天live pilot；无账户单日止损，累计回撤10%停机。
8. UM no-carry 分支仅在另写 baseline forward preregistration 后收集新数据。
9. carry / Earn 从下一资金架构移除，不作为本轮收益补偿。
10. 已完成：旧 X4 headline funding 更正和逐机制归因；历史窗口只留 discovery，不按更正结果调参。
11. 已完成并拒绝：UM 2.0% risk-tier；不做 1.75%/1.8% 或新阈值救援。
12. 已完成并拒绝：UM bull/range/bear 三阶段 overlay；不改 breadth、均线、确认天数或风险档救援。
13. 已完成并拒绝：无新阈值的 strong-bull stop latch；只差全窗 DD 门，但不放宽 `1pp` 杀线。
14. 已完成并历史retain：lagged-funding cost veto；50%阈值冻结，作为未来独立验证的首选候选。
15. 已完成条件稳健性审计：Funding Veto配对20日区块Bootstrap通过，但不改变历史候选层级。
16. 已完成精确归因：成本veto机制获支持，但696个下游差异日要求未来做完整状态forward。
17. 已完成状态衰减：首次同步不稳定，未来shadow forward须持续保存两套权益和完整状态。
18. 进行中：Funding Veto双状态shadow-forward v0.2已预登记；WSL/external canonical UM日线已到
    `2026-07-17`，但冻结起点为`2026-07-19`，当前仍0根。月内funding公开REST直连0/3可达，必须用仓库外
    良心云标准代理配置或等待不可变月包，缺失不得填0。
19. 已完成：1765行因果状态、30日triple-barrier标签和28个point-in-time特征，四折label-end purge通过。
20. 已完成并不接策略：tabular、HMM及固定校准/融合trial 2；只保留原HMM为弱概率特征。
21. 已完成并停止扫结构：单A10小型GRU结果为负且可确定性复现；LSTM/TCN/Transformer暂不消耗trial。
22. 已完成并关闭：HMM经济审计、目标敏感性、直接经济回归、DVOL增强与滚动模型策略消融；预测层保留不等于
    策略层通过，不做动态ATR/deadband救援。
23. 已完成新信息G0：Coin Metrics latest-vintage链上数据覆盖完整，只有算力通过固定因子和模型门；同一策略
    消融仍失败。MVRV未过全门，SOPR/Realized Cap/LTH无免费历史字段，不拼接模型。
24. 已完成宏观G0和固定实践：H.4.1 289条point-in-time release通过；4周变化/加速度预测保留，13周与
    宏观+算力融合拒绝；同一三档策略消融0/3，不做阈值救援。
25. 已完成并拒绝：H.4.1符号状态的3个事件闸门trial；收缩开仓闸门过度持久，扩张退出闸门样本极少且
    Sharpe下降，不做分位/窗口/冷却/投票救援。
26. 已完成并拒绝：H.4.1只否决strong-bull额外0.5%风险的单trial；303/449个可boost日被否决，收益、Sharpe
    和回撤均劣于Funding Veto，且跑输Base，不做分数阈值救援。
27. 已完成Base episode归因：吊灯/长持有是利润源，短期趋势退出和总闸退出是损耗源；不收紧吊灯、不加时间止损。
28. 已完成并拒绝：趋势退出复用3日冷却仅有边际点估计优势，Bootstrap三项均未过门；不扫冷却周期。
29. 进行中：Coin Metrics append-only future vintage链；后续只追加真实检索时点，不回填历史vintage。
30. 下一实验只接受真正新vintage/forward读数，或不改变Base仓位和交易许可的预测校准；叙事标签仍须先解决
    发布时间与幸存者偏差。
31. 超1x、short和carry仍按owner当前资金约束关闭；research结果不自动恢复paper/live。
32. 新目标：owner提出一个月小资金实盘；独立readiness固定Base v0.2、300 USDT、TOP3 UM long/cash、
    1x逐仓、无账户单日止损和10%试点累计回撤熔断。v0.3当前20项blocker，旧API key `-2015`且账户状态
    未知，禁止arm；全局2.0%风险档与Funding Veto只做shadow，旧X4/C×D不得复用。
33. 已完成独立order-free paper runtime与首跑：300 USDT现金、200根warmup、完整价格/funding、10%累计回撤
    halt和hash-chain journal均已测试。canonical数据仍只到`2026-07-17`，早于`2026-07-19`起点，故0天；
    preflight/dry虽已实现但被`-2015`阻断，不改变20项readiness blocker与禁止下单结论。
34. paper runtime v0.3已加入Risk 2.0%首选收益shadow和Funding Veto次级shadow的完整逐日状态；两条shadow
    显式`controls_live_orders=false`，只用于30天同路径比较，不改变Base订单或累计回撤停机规则。
