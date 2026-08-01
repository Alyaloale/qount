# 200 USDT 个人事件右侧策略

> **状态**：draft / 2026-07 FOMC 单次受限自动执行已取消部署｜**权威**：L3 新策略合同｜**最后更新**：2026-07-30
> **本文回答**：如何把 200 USDT、20 USDT 正常策略回撤停止阈值的想法改造成可监控、可计算、可停止的个人交易系统。
> **TL;DR**：只做一个 crypto-beta 方向；用完成 1h K 定方向、完成 15m K 做突破回踩；首个闭环风险 5 USDT、常规单笔及总并发风险上限 10 USDT；回撤 20 USDT 停止正常交易。2026-07 FOMC 路径已取消部署，当前仅保留研究合同。

更新时间：2026-07-29

## 1. 决策

本策略替代“100U 保证金 × 10x × 固定 2% 止损”和“另用 100U 全仓高 beta 现货”两条同时运行的原方案。

保留的核心优势是：长期空仓、事件后才做右侧确认、交易次数少、允许做空、严格止损、系统全天监控。删除的部分是：

- 不把 40 USDT 全部分给两次正常止损。40 USDT 是灾难预算，不是下注额度。
- 不同时持有 BTC 合约和 SOL/山寨现货。它们在压力期属于同一个 crypto-beta 风险。
- 不使用固定的 67,200 / 64,000 作为永久触发价；事件前冻结区间和 ATR，事件后不重画。
- 不按“偏鸽=多、偏鹰=空”下单。文字解释只可 veto，方向只由可成交价格确认。
- 不把 10x 当作收益来源。收益由名义仓位和价格变化决定，杠杆只改变保证金与清算距离。
- 不把止损移到开仓价称为“无风险”；净保本价必须覆盖双边费用、资金费和退出滑点。

策略标识升级为 `SmallAccount-FOMC-RightSide-v0.2`。`v0.1` 只保留为 shadow 对照，不得混用两套条件挑选更好看的结果。
它是新线，不继承已停用 `MiniTrend-UM-Base-v0.2` 的 registry、arm、timer 或订单权限。

## 2. 2026-07-26 事实快照

### 2.1 已核验事实

- 2026-07-29 owner 已授权本次事件的受限自动执行：BTCUSDT USD-M、200 USDT sleeve、20 USDT 正常策略回撤停止阈值。
  `authorize-auto` 的私有只读预检已通过，授权绑定事件定义、账户 scope 与完整风险 policy。`auto-cycle` 在观察开始前不访问
  交易所，只有新鲜 shadow `ARMED` 才会重新做私有预检、验证 risk scope、消费授权并创建短时内部 arm。无信号、账户不平、
  规则/杠杆/保证金模式变化、风险超限或授权过期都不下单。20 USDT 是策略控制阈值，不是跳空或场所故障下的精确成交保证。

- `0.2.18/5fe2b91`已把公共行情watcher、现金窗口告警和固定事件timer部署VPS；timer只覆盖本次窗口，所有结果固定
  `orders_authorized=false/paper_or_live_allowed=false/private_api_used=false/exchange_mutation_attempted=false`。
- Federal Reserve 官方日历确认 2026 年 7 月 FOMC 为 **7 月 28-29 日**，本次没有星号，因此没有预定 SEP/点阵图。
- Fed 7 月日历列出的声明时间为 7 月 29 日 14:00 EDT、记者会为 14:30 EDT，即上海时间
  **7 月 30 日 02:00 / 02:30**，不是上海时间 7 月 29 日。
- BEA 官方日历列出 Q2 GDP 初值和 6 月 Personal Income and Outlays/PCE 均在 7 月 30 日 08:30 EDT，
  即上海时间 **7 月 30 日 20:30**。它距离 FOMC 声明只有 18.5 小时，是第二个独立事件风险。
- CoinGecko 在 `2026-07-26T13:07:10Z` 的公开快照为 BTC `64,380`、ETH `1,883.27`、SOL `74.76` USDT；
  24 小时变化约为 `+0.48%/+1.20%/+1.13%`。用户给出的价格量级基本准确，但 24 小时方向已经变化。
- 同期 CoinGecko 全市场口径约 `2.287T USD`、24 小时成交量约 `36.4B USD`、BTC 占比约 `56.45%`。
  与 CoinMarketCap 的市值和占比口径不同，不能混合成一个精确条件。

官方来源：

- Fed FOMC calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- Fed July 2026 calendar: https://www.federalreserve.gov/newsevents/2026-july.htm
- BEA release schedule: https://www.bea.gov/news/schedule
- CoinGecko price API: https://api.coingecko.com/api/v3/simple/price
- CoinGecko global API: https://api.coingecko.com/api/v3/global

### 2.2 对原阈值的诊断

以 BTC `64,380` 为参照：`67,200` 距现价约 `+4.38%`，`64,000` 仅约 `-0.59%`。这不是对称突破框架，
会让空头比多头更容易触发，并把某一时刻的图形判断永久写进规则。两个数字只能作为 7 月 26 日的观察参考，
不得直接成为 7 月 30 日的订单触发价。

`PCE 4.1%`、6 月 FOMC 的偏鹰讨论可以作为事件背景，但 7 月结果不能预设。CLARITY Act 的“7 月 4 日前签署”
目标已经失效；ETF 流、鲸鱼吸筹、Strategy 抛售、HYPE 叙事和“SOL 超跌”等未绑定具体来源与时点的描述，
不得进入自动交易条件。

### 2.3 对两份评估报告的取舍

采纳的是可直接减少执行歧义的部分：用 1h 定方向、15m 做触发；给回踩设置原区间失效线；定义突破 K 的实体、收盘位置和量能；
把最晚开仓提前到 12:00、强制平仓提前到 19:00；`+2R` 后加入净 `+1R` 利润底线并缩短 ATR 追踪距离。

以下建议暂不直接成为真钱参数：

- 不硬等到 07:00 或 08:00。现有证据只能支持“记者会结束且声明后至少四根完整 1h K”，再延迟会与抢占剩余 `2R` 空间冲突。
  shadow 记录信号是否发生在 07:00/08:00 前后，事件后再判断。
- 不要求回踩低点始终高于突破线 `0.1-0.15ATR`；那会把没有真正接近突破线的浅回落也叫作回踩。改为必须进入突破线外
  `0.10ATR` 的触碰带，同时绝不穿回 `H0/L0` 原区间。
- 不直接使用 `0.5ATR` 尾随，它可能小于事件后正常 1h 噪声；也不继续使用原来的 `1.5ATR`。首版折中为完成 1h 收盘极值的
  `1.0ATR` 追踪，并叠加净 `+1R` 利润底线。
- 报告中“收盘价距离最高价不能太近以避免长上影”方向写反。多头应收在 K 线顶部区域，空头应收在底部区域，具体由
  close-location 数学条件定义。

## 3. 资金与风险合同

所有百分比同时保留 USDT 绝对值，系统以更严格者为准。权益使用保守净清算权益：

```text
NLE = 现金 + 现货可成交价值 + 合约钱包余额 + 未实现盈亏
      - 预计平仓费 - 不利资金费 - 压力滑点
DD  = cashflow-adjusted HWM - NLE
```

充值和提现不改变高水位；未确认撤销的入场单计入 pending risk；未被保护单完整覆盖的仓位按压力损失计入 open risk。

| 项目 | 硬值 | 动作 |
| --- | ---: | --- |
| 绑定初始权益 | 200 USDT | 额外账户余额不自动进入本 sleeve |
| 首个受保护并完成对账的 live round trip | 5 USDT 全成本风险 | canary；完成前不提高 |
| 常规单笔全成本风险 | `<=10 USDT` | 是上限，不是每单必须用满 |
| open + pending 总压力风险 | `<=10 USDT` | 最多一个 crypto-beta 主题 |
| 滚动 24h 净亏损 | 10 USDT | 全平、当日不自动恢复 |
| 正常策略高水位回撤 | 20 USDT | 全平、停止新风险、人工复盘 |
| 紧急回撤 | 32 USDT | 撤入场单、reduce-only 平仓、HALT |
| 灾难红线 | 40 USDT | 目标权益底线 160；不是成交保证 |
| 同时持仓数 | 1 | BTC 合约与 SOL/现货互斥 |
| 最低计划净盈亏比 | 2.0R | 扣费用、滑点、资金费后计算 |

下一笔可用风险不是固定 10U，而是：

```text
B_next = min(
    canary_or_normal_cap,
    10U - open_risk - pending_risk,
    10U - max(day_loss, rolling_24h_loss) - open_risk - pending_risk,
    20U - current_strategy_drawdown - open_risk - pending_risk
)
```

例如第一笔因越价实际亏 14U，第二笔最多只剩 6U 正常风险；若策略回撤已到 20U，就没有“第二颗子弹”。
其余 20U 专门覆盖跳价、断网、UNKNOWN 订单、交易所异常和强平尾部，不得继续下注。

止损触发价不是成交价。任何加密现货或合约都无法保证绝对不穿越 40U；若 40U 是法律意义上的不可突破损失，
只能把最坏可损本金本身限制在 40U，或使用提供真实保证止损的场所。此处的硬线是 fail-closed 设计目标，不是收益或成交保证。

## 4. 场所、杠杆与资本隔离

### 4.1 首选路径：BTC/USDT USD-M 永续

- 首轮只交易 BTC，不用 SOL 放大第一次事件执行风险。
- one-way、isolated、`autoAddMargin=false`。
- 杠杆上限 **5x**；若结构止损到压力清算距离不满足 `liquidation_distance >= 3 × stress_stop_distance`，降低杠杆或放弃交易。
- 隔离保证金上限 40U，名义仓位上限 200U；最终仓位还必须被全成本风险公式进一步压低。
- 其余 160U 保持在不会被合约自动追加保证金的账户/钱包切面。
- 交易所实际 fee tier、symbol filter、quantity step、minimum notional、mark/last trigger 和 leverage bracket 每次 preflight 重读。

5x 不是收益目标。它让最多 40U 隔离保证金承载最多 200U 名义价值，同时让清算价明显远于正常结构止损。
若 200U 名义仓位不足以满足预期收益，正确动作是放弃该策略或修改总风险目标，不是偷偷升到 1000U 名义价值。

### 4.2 备选路径：SOL 现货

现货不是“无风险”，只是没有强平。100U SOL 发生极端跳空或趋近归零时可能损失接近 100U，与严格 40U 红线冲突。
因此本版本中：

- SOL 现货只作为 BTC 合约的替代路径，不得同时持有。
- 严格模式现货名义上限 40U，结构止损仍按全成本公式计算，不能固定为 20%。
- 只有 BTC 已确认 risk-on、SOL 自身右侧突破并回踩、SOL/BTC 相对强度为正、行情与订单簿新鲜时才进入观察。
- “AI/DePIN 龙头”“热门叙事”“超跌”不是选择条件；必须绑定可成交性、相对强度和明确失效价。
- 只允许在盈利后加到预先计算的目标仓位，不向亏损仓位补仓。

若 owner 坚持 100U 现货，则必须明确把 40U 从“灾难级最大可能损失”降级为“正常止损计划损失”；本合同不做该隐含放宽。

## 5. FOMC 事件合同

### 5.1 事件前冻结

在官方计划声明时间前 30 分钟冻结，只使用当时已经完成的 BTC K 线：

```text
H0       = 前 72 根完成 1h K 的最高价
L0       = 前 72 根完成 1h K 的最低价
ATR0     = 冻结时的 1h ATR(14)
V20_1h   = 冻结时前 20 根完成 1h 成交量中位数（只供 v0.1 对照）
V20_15m  = 冻结时前 20 根完成 15m 成交量中位数
B_long   = H0 + 0.25 × ATR0
B_short  = L0 - 0.25 × ATR0
```

同时用冻结前 30 天完成 1h K 标记已确认的 3 左/3 右 pivot high/low。计划多头入场上方最近 pivot high、空头入场下方最近
pivot low 是冻结结构障碍；障碍前的全成本净收益不足 `2R` 就放弃。若该方向没有冻结障碍，显式记录 `NONE`，不得在信号出现后
人工补画一个有利目标。

保存原始数据 hash、freeze time、event source hash、symbol rules、费率和参数版本。事件后禁止重画 `H0/L0`、更换 ATR/量能周期、
删除插针或切换交易所 K 线。若官方时刻、K 线、订单簿或账户状态不完整，保持现金。

### 5.2 BLACKOUT 与可交易时钟

- 上海时间 7 月 30 日 01:00 前，本 sleeve 必须处于 `CASH`；01:00 起禁止新增风险。01:30 只做冻结快照，不交易。
- 至记者会实际结束、且声明发布后至少 4 根完整 1h K 已收盘前，保持 `BLACKOUT`。按已知日历，最早观察点约 06:00-06:30，
  但由实际 event availability、记者会结束时点和完整 K 线共同决定，不写死 06:00、07:00 或 08:00。
- FOMC 后未出现完整确认时，不因为“已经等了很久”而交易，也不追赶没有回踩的第一段行情。
- 上海时间 12:00 后禁止新开 FOMC 仓位；19:00 前强制全平，给 20:30 GDP/PCE 留出 90 分钟缓冲。
  GDP/PCE 若要交易，必须创建新事件实例、重新冻结区间并重新计算剩余风险。

### 5.3 v0.2 混合周期确认

方向仍由 1h 决定，入场形态改由 15m 完成 K 确认。多空完全对称，文本不决定方向：

1. `BLACKOUT` 结束后，至少一根完成 1h K 收在对应的 `B_long` 上方或 `B_short` 下方，形成方向锚。
2. 与方向锚同一收盘时点或之后的完成 15m 突破 K 必须收在线外，成交量 `>=1.5 × V20_15m`，
   `abs(close-open)/(high-low) >= 0.60`。多头 `CLV=(close-low)/(high-low) >=0.80`；空头 `CLV<=0.20`。
3. 突破后最多 8 根完成 15m K 内必须发生真正回踩。多头回踩最低价必须落在
   `[H0, B_long + 0.10×ATR0]`；空头回抽最高价必须落在 `[B_short - 0.10×ATR0, L0]`。
4. 序列最后一根完成 15m K 必须重新收在线外，且成交量 `>=0.80 × 突破K成交量`。没有触碰、没有重收或没有二次量能就不入场。
5. 回踩期间多头任一最低价 `<H0`、空头任一最高价 `>L0`，本次事件直接 `NO_TRADE`，不把深度跌回旧区间解释为有效回踩，
   也不在剧烈反转中换方向。
6. 计划成交价必须仍在线外，且距突破线不超过 `0.25×ATR0`。多头结构止损参考为
   `min(retest lows)-0.50×ATR0`，空头为 `max(retest highs)+0.50×ATR0`；压力越价和成本另行加入仓位公式。
7. 冻结结构障碍前的全成本净空间必须 `>=2R`，quote、mark/index、账户和保护单通道必须新鲜，且距 12:00 截止仍足以执行。

任何条件只读完成 K。突破后超过 8 根 15m 仍未完成回踩重收，或计划成交时已过 12:00，均为 `NO_TRADE`。
同一 FOMC 最多一次入场尝试；被止损后不反手，不允许用另一个参数版本再试。

### 5.4 shadow 对照

7 月 30 日默认同时计算、但不下单：

- `v0.1`：原两根 1h 确认 + 最多四根 1h 回踩；
- `v0.2`：一根 1h 方向锚 + 最多八根 15m 回踩重收。

两套规则在事件前冻结，事件中不得改参数。分别记录最早成立时间、计划入场/止损/目标、拒绝 reason codes、扣成本 MFE/MAE、
最终净 `R`，并标记信号发生在 07:00/08:00 前还是后。单个 FOMC 只能验证时效和流程，不能证明正期望；比较结果用于保留、收紧或
终止 `v0.2`，不自动获得 canary 权限。

### 5.5 v0.2 到期 scorecard

事件强制退出后，shadow watcher只使用公开 Binance USD-M 数据生成一次不可覆盖的
`fomc-v02-shadow-scorecard.json`。它绑定所有已保存的运行 result hash、首个满足完整仓位/目标/止损门的
`ARMED` v0.2 candidate、当时的入场价、tick 对齐后的止损、全成本模型和15m outcome K线 hash。

- 结算模型只模拟“原始保护止损的压力成交”或事件强平时的完成15m K收盘价；同时记录冻结目标是否被触及、扣合同成本后的 MFE/MAE 和最终净 `R`。
- 该模型不伪造真实成交，也不回放 `+1R/+2R` 后的部分止盈和尾仓管理；因此 scorecard 是冻结计划的流程与时效证据，不是实盘 PnL 或完整策略回测。
- source 不完整、K线断档或旧运行缺少已绑定的成本/止损字段时，scorecard保持 `pending`，不得用新参数或补画价格“修复”旧证据。
- 若没有 eligible setup，必须有一条在停止入场时刻或之后、强制退出前完成的已保存 shadow scan，才能写出 `no_eligible_v02_shadow_setup`；缺少该覆盖证据时保持 `pending`。
- `11:00 UTC` 首次结算失败后，timer 模板在 `11:05`、`11:10`、`11:15`、`11:20`、`11:25` 和 `11:30 UTC` 安排公开数据采集重试；重试不访问私有 API、不创建订单，也不改变任何权限。
- scorecard、CLI 摘要和到期 `EXPIRED` 运行记录均固定
  `orders_authorized=false`、`paper_or_live_allowed=false`、`promotion_evidence=false`。单个事件无论结果好坏都不能扩容、提升风险预算或自动进入 canary。
- v0.1 的历史对照仍须使用一份完整冻结的 reference runtime；v0.2 scorecard 不得被冒充为两版本的收益比较。

## 6. 全成本仓位公式

对 USDT 线性合约，设：

- `Pe`：实际/保守预计平均开仓价；
- `Ps`：结构止损触发价；
- `g`：止损触发后的压力越价率；
- `Pw`：压力成交价，多仓为 `Ps × (1-g)`，空仓为 `Ps × (1+g)`；
- `fe/fx`：开仓/平仓费率；
- `se/sx`：开仓/平仓滑点率；
- `u`：最大持仓期内不利资金费率总和；
- `B`：本笔剩余全成本风险预算；
- `q`：币数量。

```text
多仓 q_max = B / [
    (Pe - Pw)
    + Pe × (fe + se + u)
    + Pw × (fx + sx)
]

空仓 q_max = B / [
    (Pw - Pe)
    + Pe × (fe + se + u)
    + Pw × (fx + sx)
]

notional = floor_to_quantity_step(q_max) × Pe
margin   = notional / leverage
```

最终数量取以下最小值并向交易所 quantity step 向下取整：风险公式、200U 合约名义上限、40U 隔离保证金上限、
实际可用余额和交易所 filters。成交后必须用真实 fill VWAP、真实 fee 和真实数量重算；超出预算时只减仓，不加保证金。

压力模型固定使用开仓和退出各 5bps 手续费、各 5bps 滑点、两个不利资金费结算周期合计 6bps，以及 50bps 止损越价。
例如 1000U 名义仓位、2% 结构止损下，压力损失约为名义价值的 `2.748%`，即 **27.48U**，不是 20U。若风险预算为 10U，单看风险公式的名义上限约 364U；
但本合同还受 5x/40U 隔离保证金和 200U 名义上限约束，所以最终仍不超过 200U。

## 7. 下单与保护

1. 入场前写入唯一 `decision_id/client_order_id`，保存意图后才能提交。
2. 小资金不强求 maker；只有当预计 taker 全成本仍满足 `>=2R` 时才成交。未成交的限价单不追价。
3. 部分成交后取消剩余入场量，只为真实已成交数量建立保护。
4. 入场成交后立即提交交易所原生 `STOP_MARKET reduce-only/closePosition`，回读确认方向、触发类型和覆盖数量。
5. 保护单未确认、数量不足或触发规则不一致时，立即 reduce-only 平仓并 HALT。
6. `UNKNOWN` 订单禁止重发；先按 client order ID、订单、成交、仓位和账变完成对账。
7. 本地程序宕机时，交易所原生保护单仍必须存在；本地“软止损”只能作为附加退出，不能作为唯一保护。

## 8. 持仓管理

`R` 始终表示入场时冻结的全成本压力风险 USDT，不随主观判断改变。

- 完整 1h K 重新收回原冻结区间，提前退出，不等硬止损。
- 达到净 `+1R` 且由完成 15m K 收盘确认后，止损只可移到**净保本价再加退出滑点缓冲**，不能简单放到开仓价。
- 达到净 `+2R` 且由完成 15m K 收盘确认后，先 reduce-only 平掉 1/3；只有部分平仓 fill 与剩余数量对账完成后才替换保护单。
- 尾仓按完成 1h 收盘价更新，`Cmax/Cmin` 是入场后最有利的完成 1h 收盘价，`P_+1R` 是按原始 `q/R` 和已知成本计算的净
  `+1R` 价格。追踪只能收紧：

```text
多仓 S_next = max(S_prev, P_+1R, Cmax - 1.0 × ATR14_1h)
空仓 S_next = min(S_prev, P_+1R, Cmin + 1.0 × ATR14_1h)
```

- 若计算时当前可成交价已经越过 `S_next`，直接 reduce-only 退出尾仓，不提交方向或触发关系异常的止损。
- 8 根完整 1h K 仍未达到 `+1R`，退出。
- 通用事件最长持有 72 小时；本次 FOMC 特别版最晚上海时间 7 月 30 日 19:00 全平。
- 预计下一笔不利资金费超过 `0.1R` 且尚未达到 `+1R`，退出或放弃入场。
- 新闻、LLM、人工感觉不得放宽止损、增加保证金、摊低成本或扩大已冻结风险。

live dispatcher 的管理边界：

- 入场 fill 后冻结真实 VWAP、真实开仓 USDT 手续费、两期不利 funding reserve 和完整压力 `R`，据此计算净保本、净 `+1R` 和净 `+2R` 价格；不能用开仓价替代净保本价。
- 准入时必须能按 `quantity_step` 向下取整出非零的 1/3 reduce-only 数量，并保留至少一个最小数量单位的尾仓；否则本次计划不可自动执行。以 BTCUSDT 的常见 `0.001 BTC` 步长计，200U 名义仓在 BTC 高于约 66,667 USDT 时通常无法满足这一条件，结果是 `NO TRADE`，而不是改成 50% 或全平。
- `+2R` 时原始原生止损会一直保留到部分市价单的完整 fill、剩余仓位和原止损都回读确认；之后才撤销旧单并提交、回读新的 `STOP_MARKET closePosition`。新单提交或回读失败且旧单已撤销时，必须先按新 client order ID 查询并撤销/确认新单终态，再 reduce-only 平掉剩余仓位并 HALT。
- 追踪仅使用完成的 1h K 与 14 根连续 true range；ATR 可使用入场前已完成的连续 K，`Cmax/Cmin` 仍只取入场后的完成 K。公共行情或 K 线不完整时不换止损，保留当前交易所原生止损。新止损若已被当前 mark price 越过，直接 reduce-only 退出，不提交无效的反向止损。

忽略滑点时的费用净保本价为：

```text
多仓 P_BE = [Pe × (1+fe) + funding/q] / (1-fx)
空仓 P_BE = [Pe × (1-fe) - funding/q] / (1+fx)
```

实际保护价还要加入预计退出滑点，因此“推保本”仍不是成交保证。

## 9. 24 小时状态机

```text
CASH
  -> EVENT_FROZEN
  -> BLACKOUT
  -> OBSERVE
  -> ARMED
  -> ENTRY_PENDING
  -> PROTECTED
  -> MANAGING
  -> EXIT_PENDING
  -> COOLDOWN
  -> CASH

任意状态 -> UNKNOWN -> 禁止增险，先对账
任意状态 -> HALTED  -> 只允许撤入场单和 reduce-only 降险/平仓
```

状态不变量：

- `open_risk + pending_risk <= B_next <= 10U`。
- 同时最多一个 crypto-beta 方向；SOL 和 BTC 不能伪装成两个独立 sleeve。
- 信号只读完成的 1h/15m K；风控、保护单和账户对账实时运行。
- LLM/日报只可输出 `veto/reduce/halt/review`，不能输出 side、quantity、leverage、stop 或订单。
- 任何 stale/UNKNOWN/unmanaged position 都禁止新增风险。
- HALT 不自动恢复；必须人工完成原因、账户、订单、保护单和权益对账后创建新 arm。

## 10. 监控面

系统应按职责分开，不让“时事情报”直接控制订单：

| 面 | 最低输入 | 频率 | 失效动作 |
| --- | --- | --- | --- |
| 事件 | Fed/BEA/交易所官方 URL、published/available/observed time、原文 hash | 发现后立即 | 来源或时钟未知则 BLACKOUT |
| 信号 | 完成 1h/15m OHLCV、冻结区间、ATR、双周期成交量 | 每根完成 K | 缺 K、乱序或修订则不入场 |
| 可执行性 | bid/ask、mark/index、symbol filters、fee、funding | 入场前及持仓中 | 成本超预算则 veto/reduce |
| 账户 | balance、position、open/conditional orders、fills、fees | 私有流 + 有界 REST 对账 | UNKNOWN/HALT |
| 保护 | stop ack、覆盖数量、trigger、reduce-only | 成交后立即及周期回读 | 无保护则 flatten |
| 组合风险 | NLE、HWM、24h PnL、open/pending stress risk | 每次状态变化 | 触线 flatten/HALT |

系统通知只报告需要动作的状态：事件冻结、信号成立/过期、保护单异常、`+1R/+2R`、时间退出、风险线、UNKNOWN 和 HALT。
没有信号时保持现金，不用提醒制造交易。

## 11. 历史上线顺序与验收（已取消）

以下内容是已取消部署的历史设计记录，不构成当前执行授权；`SmallAccount-FOMC-RightSide-v0.2` 当前仅保留研究合同。

1. **历史阶段**：timer 只读取本地授权状态，不访问公共或私有交易所接口，也不会生成 arm 或订单。
2. **历史 FOMC 窗口**：`authorize-auto` 先以私有只读预检将 owner 授权绑定到当前账户；`auto-cycle` 只在新鲜
   `ARMED` 信号后重新冻结 exact account/symbol/side/notional/`<=5U` 风险/止损/退出 scope。它先消费授权，再写入 0600
   内部 token 和单次 arm；随后 dispatcher 仍须再次通过信号、报价、账户和订单回读检查才可提交一次 MARKET 入场。
3. **无条件放行不存在**：无信号、账户不平、普通单或条件单存在、scope/规则/杠杆/保证金模式改变、报价过期、风险超过上限或授权过期时
   都保持现金；不得改为人工追单或扩大金额。
4. **首个闭环后**：必须能从 order/trade/fee/funding/position/stop 证据重建净 PnL 与最大风险；否则保持 5U 或 HALT。
5. **提高到 10U 前**：至少一个完整受保护 round trip、无 UNKNOWN、无未保护时间窗、实际压力损失未越过 canary 预算。
6. **两次正常亏损或 20U 回撤**：停止本策略，不用“最后 20U”救援；复盘交易条件、成本与执行路径后另立版本。

最小记录字段：event/source hash、freeze values、1h/15m candle IDs、v0.1/v0.2 最早成立时间、decision/reason codes、
entry/stop/pressure exit、fee/slippage/funding 假设、quantity step 前后数量、计划 `R`、真实或 shadow fills/fees/funding、
保护 ack、每次止损变化、退出原因、NLE/HWM/DD 和最终 reconciliation。

## 12. 当前执行结论

- 7 月 28-29 日会议前保持现金是正确动作。
- 本次第一优先标的是 BTC 永续；SOL 只作为互斥备选，不是第二个并发仓位。
- 7 月 30 日 06:00-06:30 左右只是最早可能进入 `OBSERVE` 的时间，不是自动买卖时间。
- 7 月 30 日 12:00 后不新开 FOMC 仓位，19:00 前全平，避免把单一事件策略带入 20:30 的 GDP/PCE。
- 没有“完成 1h 方向锚 + 合格 15m 突破 + 未回旧区间的回踩重收 + 全成本 2R + 保护可用”，结果就是 **NO TRADE**。
- 本次授权不等于必然交易：生产 unit/timer 只会在符合所有冻结信号、账户和风控条件时创建一次入场；否则保持现金。

该策略追求的是可重复的风险纪律和少量清晰机会，不宣称已有高胜率或正期望证据。
