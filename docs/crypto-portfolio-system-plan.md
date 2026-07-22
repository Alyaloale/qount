# qount 加密多策略组合系统计划

更新时间：2026-07-22

状态：源码版本`0.2.7`是完整升级发布候选；VPS仍为`0.2.5`且交易timer在维护期已停。多策略部分仍为`research_sandbox`；
唯一允许在升级验收后恢复的例外是已单独授权的Base `100 USDT` minimal-live。本文记录未来
`1000 USDT`目标架构，不构成扩容或其它sleeve下单授权。60/10 forward、30 paper days和7 dry days仍是观察项；
账户、订单、funding、标准authority/RuntimeLedger/对账、HALT和arm继续是每轮硬门。RiskTier与FundingVeto只做shadow。

本文负责策略sleeve、研究合同和晋级顺序。跨策略通用的运行架构、账本/对账、故障恢复、通知、Dashboard和LLM
边界以 [system-architecture-design.md](system-architecture-design.md) 为主设计，避免在策略计划中重复维护第二套
系统接口。

## 1. 系统目标

系统不再要求单个策略同时承担生存、收益增强和信息发现。目标拆成四个可以独立证伪的收益 sleeve：

| Sleeve | 任务 | 当前角色 | 主要失败方式 |
| --- | --- | --- | --- |
| Base v0.2 | 低频趋势参与与熊市现金保护 | 控制组 | 牛市参与不足、震荡反复 |
| Equity Mapping Alpha | 美股休市/跨场所/开盘收敛 | 新结构研究 | 锚定错误、样本少、交易成本 |
| LiquidTrend | 高流动性币横截面相对趋势 | G0容量审计 | 高相关导致虚假广度、幸存者偏差 |
| Funding Event | 拥挤状态与趋势条件交互 | 事件研究 | 极端样本少、反向信号过早 |
| Capitulation Rebound | Base关闭时的极端下跌反弹 | trial 144已拒绝 | 接飞刀、成本和beta暴露 |

核心关系不是“提高单策略杠杆”，而是：

```text
可持续绝对利润 = 可验证Alpha × 可投入资本 × 可执行容量 × 存活时间
组合质量       = 多个正期望来源 + 低相关性 + 统一风险和执行
```

Base 是生存底盘和共同对照，不被包装成致富策略。任何收益增强都必须同时报告相对 Base、BTC 1x、TOP3 1x 的
净收益、beta residual、回撤、成本、换手和跨时段稳定性。

## 2. 物理架构

```text
公开/授权来源
  Binance/Bybit/传统市场/公司公告/宏观/链上
            |
            v
Windows外置盘 E:\qount_data\qount
  immutable raw + as-of metadata + manifests
            |
            v
WSL 7945HX/RTX4060
  特征、标签、回测、模型、容量/成本审计
            |
            v
Mac代码主仓
  研究设计、合同、审查、轻量测试、artifact索引
            |
            v
VPS production host
  只部署晋级后的确定性策略、组合风控、订单、journal/dashboard
```

物理边界继续遵循 [storage-topology.md](storage-topology.md)：Mac/VPS不做批量数据中转，WSL计算scratch任务后
清理，外置ExFAT盘只保存不可变数据和最终artifact，不运行活跃SQLite/venv/高频小文件训练。

## 3. 软件分层

### 3.1 Data Plane

- `raw_store`：原始响应、下载时间、来源URL、HTTP元数据和SHA-256。
- `asof_normalizer`：统一`event_time/published_at/observed_at/available_at`，禁止只保留自然日期。
- `feature_store`：只保存可在决策时点观察的数值和血缘；未来数据只能进入label/outcome。
- `dataset_manifest`：数据树hash、文件数/字节数、缺失、重复、时间覆盖和source vintage。

### 3.2 Research Plane

- 每条策略有独立`contract_hash/data_hash/code_hash/trial_count/holdout_role`。
- 研究历史统一标`consumed_historical_discovery_pool`；时间序列使用chronological split和purge/embargo。
- 容量、有效广度和成本审计先于收益回测；回测失败不通过调门或换窗口改写。
- LLM可提出假设、抽取文本和做红队审查，确定性代码生成标签、信号、权重、PnL和scorecard。

### 3.3 Strategy Plane

每个sleeve只输出标准化`StrategyIntent`，不输出交易所订单：

```json
{
  "strategy_id": "...",
  "decision_time": "...",
  "data_cutoff": "...",
  "target_weights": {"BTCUSDT": 0.0},
  "expected_holding_bars": 1,
  "target_stress_loss_fraction": 0.0,
  "evidence_hash": "...",
  "state_hash": "..."
}
```

Research LLM的schema不得出现`target_weights/target_stress_loss_fraction/order/leverage`字段。

### 3.4 Portfolio Plane

通过晋级的sleeve同时维护三类NAV，再由确定性allocator聚合：

```text
Signal NAV                = 原始信号目标 + 标准研究成本
Standalone Executable NAV = 假设该sleeve独立执行时的真实bid/ask、费用、funding和规则
Portfolio Realized NAV    = 净额合并后的真实fills、费用、funding和账户PnL
```

晋级只读取`Standalone Executable NAV`；账户对账只读取`Portfolio Realized NAV`。组合净额节省不得进入
standalone结果，也不得让两个sleeve重复认领同一笔组合利润。

第一版allocator不使用协方差优化器。每个sleeve先按冻结的压力损失预算缩放：

```text
risk_scalar_s = min(capacity_scalar_cap_s,
                    target_stress_loss_s / estimated_standalone_stress_loss_s)
scaled_weight_s,i = standalone_weight_s,i × risk_scalar_s
w_port,i = Σ_s scaled_weight_s,i
portfolio_gross = Σ_i |w_port,i| <= 1.0
```

`target_stress_loss_s`表示该sleeve对账户压力损失的目标贡献，不是现金占比、gross占比或保证金占比。所有标量
冻结且不由回测训练或LLM决定。冲突信号按组合净目标合并；组合层再检查单标的、相关簇、总gross、压力场景、
最小名义价值、可用保证金和未管理仓位。

### 3.5 Execution And Audit Plane

- 一根完成日线最多一个组合决策批次；事件策略可使用独立冻结时间窗，但必须有幂等event id。
- 交易计划与交易所回报分开journal；每行带row hash和chain hash。
- 私有API未知、余额未知、意外short、非白名单仓位、规则缺失、时间断层均fail closed。
- 研究artifact不能成为订单输入；只有版本化promotion artifact可以解锁dispatcher允许的strategy id。

## 4. 1000 USDT资金与风险合同

1000 USDT使用一个USD-M钱包和多个虚拟sleeve账本，避免小资金被拆散后持续违反最小名义价值。在账户权益低于
`3000 USDT`前，最多一个连续型策略拥有实盘资格、最多一个事件型策略拥有最小试单资格；其余策略只能运行
virtual NAV或shadow execution。

| Sleeve | 1000 USDT阶段实际资格 | 成熟架构目标，不是当前分仓 |
| --- | --- | ---: |
| Base | 唯一连续型实盘候选，仍需门禁 | 50%-60%压力风险预算 |
| Equity Mapping | forward collection/shadow；达门后最多最小事件试单 | 20%-25% |
| LiquidTrend | research/shadow | 15%-20% |
| Funding Event | feature/filter research | 5%-10% |

第三列只描述账户大于3000 USDT且多个策略各自取得独立实盘证据后的目标架构。百分比是压力风险贡献预算，不是
静态现金分仓。所有阶段保持：

- `long/cash`、one-way、逐仓、无carry、无short、无杠杆增益、组合effective gross `<=1.0`。
- Base沿用35% deadband、3xATR逐币吊灯和3根完成日线冷却。
- 当前100 USDT试点按冻结本金设置5%账户级单日损失线，并保留权益峰值回撤10%累计线；任一触发都flatten+halt，恢复必须人工审计。
- 新事件单次模型化最大亏损目标不超过账户的0.25%；若最小名义价值或跳空使其不可满足，只能shadow。
- LiquidTrend单币目标不超过25%，同一动态相关簇最多2个仓位；相关簇限制不影响Base控制组的历史合同。

历史pilot曾从已审计USD-M余额动态选择`100-1000 USDT`；代码中的`1000 USDT`上界现在只兼容已消费的300 USDT
research/paper和旧order-free证据。本次canary在readiness、manual arm、live dispatcher和live journal四层均强制严格
`100 USDT`，manual arm时冻结。未来扩到1000 USDT仍需新的owner授权，不会让未晋级sleeve自动获得真钱风险预算。

## 5. 策略合同

### 5.1 Base v0.2

保持现有TOP3日线合同，不做收益救援：

```text
G = 1[BTC>SMA200 OR TOP3 breadth>=0.5]
eligible_i = G AND close_i>SMA200_i AND SMA20_i>SMA60_i
raw_i = 1 / (vol20_i × max(avg_corr_i, 0.2))
scale_i = min(1, 0.015 / ATR14pct_i)
```

所有新策略必须以Base净收益路径为共同对照。Risk2和Funding Veto继续是shadow，不改变Base订单。

### 5.2 Equity Mapping Alpha

产品层分开：Binance/Bybit映射spot、xStocks、股票perpetual/linear不能混用同一成本或托管假设。

```text
RawGap      = TokenPreOpen / PreviousCashClose - 1
TrueGapMid  = TokenMid_USDT * USDTUSD_Mid * Multiplier / AdjustedStockMid_USD - 1
GapLower    = TokenBid * USDTUSD_Bid * Multiplier / AdjustedStockAsk - 1
GapUpper    = TokenAsk * USDTUSD_Ask * Multiplier / AdjustedStockBid - 1
ResidualGap = r_token - beta_nq*r_NQ - beta_sector*r_sector - beta_btc*r_BTC
```

第一阶段只研究：Gap方向/幅度、流动性、spread/depth、funding、隔夜长度、财报/公司行动、NQ/行业/BTC控制后，
下一现金时段是否收敛。无可靠盘前价格时不得把相对上一收盘的变化称为“错价”。

首个正式合同只允许`GapUpper<0`后的long convergence；中点为负但完整bid/ask不确定区间穿过0时只记观察，不能
成为候选。正偏离只能跳过或作为风险过滤，不计理论做空收益。G0特征时钟固定为纽约交易所日历和DST规则：
`09:25:00 America/New_York`决策，只允许`09:24:30-09:25:00`且在决策前可见的同步报价。后续shadow
execution另采`09:25:00-09:25:30`成交报价；决策后的报价只能评价可执行性，绝不能回流到G0特征。

现金开盘参考为`09:30:00`；半日市、节假日和停牌由point-in-time日历决定。公司行动是数据有效性门，不是交给
模型自行学习的普通特征：当前v0.3只允许来源明确的split/reverse-split乘法归一化，未知或非乘法事件阻断。
mapped/cash/USDTUSD三腿的base、quote、venue和price-multiplier作用域都必须由映射合同显式绑定。

事件名义价值按压力损失而非普通止损确定：

```text
event_notional = account_equity × 0.25% / stress_loss_pct
```

`stress_loss_pct`必须带`observation_end_at/available_at/source_hash`，并显式覆盖mapped spread、稳定币换算spread、
fees、slippage、gap tail和market impact；结果低于交易所最小名义价值时只能shadow。G0的容量计算通过不等于
minimal-live资格；没有后决策可执行报价时`minimal_live_trial_eligible`永久为false。

### 5.3 LiquidTrend10 v0.1

冻结初始研究池：`BTC/ETH/BNB/SOL/XRP/DOGE/ADA/LINK/AVAX/LTC`，只用历史当时已上市且数据完整的合约。

```text
Score_i = rank_cs(r20_i) + rank_cs(r60_i) + 0.5*rank_cs(r120_i)
          - rank_cs(vol20_i) - rank_cs(funding30_ann_i)
```

G0先审计bar/funding/rules/quote-volume覆盖和有效广度：

```text
r_bar = mean(|corr_ij|)
effective_breadth = N / [1 + (N-1)*r_bar]
effective_breadth_eigen = (Σ_j lambda_j)^2 / Σ_j(lambda_j^2)
```

在首次查看PnL前固定：不做额外winsorize、横截面至少8币、缺funding则该次调仓剔除、上市至少121根完成日线、
有限极端波动保留、同分按symbol升序、周一`00:05 UTC`决策、`00:05-00:10`使用买ask/卖bid；缺可执行报价则
不交易，mark只用于保证金和风险。G0同时报告特征值有效维度、第一主成分占比、BTC beta、BTC下跌日条件相关、
相关簇和分段簇稳定性。

只有容量语义明确后才冻结首个策略trial：BTC/Breadth总闸、周频排名、前4候选、动态60日相关簇最多2个、单币
不超过25%、1.5%风险目标、35% deadband、3xATR、完整funding和12bps换手成本。不得先看结果再改排名权重。

### 5.4 Funding Event

Funding只作为成本/拥挤状态，不做carry：

```text
state = {trend strength, funding percentile, OI change, basis, spot taker flow}
outcome = {future return, max adverse excursion, max drawdown, continuation/reversal}
```

必须分开“强趋势+高funding”和“趋势衰减+高funding+OI上升”；不采用`funding高=>做空`的单变量规则。

### 5.5 Capitulation Rebound（已拒绝）

第144个正式trial在读取收益前固定为：Base总闸关闭、TOP3五日收益全部为负、中位收益`<=-8%`、中位波动率
归一化分数`<=-1.5`；下一根日线开盘等权做多TOP3，持有3根完成日线，3xATR固定风险退出，完成后冷却5根，
单边10bps taker与2bps slippage。该假设与Base趋势参与不同，测试的是强制平仓/恐慌后的短期价格过冲。

2021-01-01..2026-07-17已有UM日线得到57个原始信号、18个不重叠episode：正收益率`44.44%`、中位事件净收益
`-1.8747%`、复合price+cost收益`-36.4990%`、maxDD`39.5163%`、中位BTC-beta residual`-0.5374%`。2021-22、
2023-24、2025-26分段复合收益分别`-21.2188%/-17.8247%/-1.9117%`；5/7预登记门失败，verdict
`reject_historical_capitulation_rebound`。结果在未计funding时已显著为负，因此不做funding补算、阈值/持有期救援、
shadow、paper或live；该hypothesis family首个trial即停止，继续必须是不同经济机制。

## 6. LLM信息系统

LLM的目标是扩大point-in-time信息集，不是替代价格模型。前90天只建设`schema + validator + source allowlist +
5-10个固定fixture + 时间泄漏单测`，不开展大规模公告抓取、叙事评分或收益ablation。优先来源：

- 交易所公告：上市/下架、合约参数、维护、风险限额和公司行动处理。
- 公司/监管一手来源：财报、8-K/6-K、拆股、分红、停牌、监管文件。
- 宏观发布：官方发布时间、原始数值、修订vintage。
- 协议/链上：治理提案、升级、解锁、桥/稳定币异常、官方GitHub release。
- 市场叙事：只作低优先级候选，不能用无时间戳二手摘要直接生成信号。

统一`InformationEvent`：

```json
{
  "event_id": "source-hash",
  "source_url": "https://...",
  "published_at": "...",
  "observed_at": "...",
  "available_at": "...",
  "entities": ["NVDA"],
  "event_type": "earnings",
  "numeric_fields": {},
  "llm_summary": "...",
  "llm_confidence": 0.0,
  "source_hash": "...",
  "extractor_version": "..."
}
```

确定性validator检查source allowlist、时间顺序、实体映射、数值原文、重复和过期。LLM输出只允许进入研究
feature store；数值由确定性解析器从原文提取，不采信LLM计算值。

`alpha_agents/official_sources.py`是当前唯一网页正文入口：只允许HTTPS官方域、禁止内嵌凭据/IP literal/非443
端口，重定向后再次校验域名，`trust_env=false`，单文档最多512 KB；保存observed time、最终URL、content type、
原文字节数与SHA-256，只向LLM暴露最多12,000字符的可见文本。共享托管域还要绑定资源身份：GitHub当前只允许
`binance/binance-public-data`。模型提出的URL必须重新经过该层，不能直接成为事实。

研究客户端通过`relay-station`的`https://llm.alyaloale.com/v1/responses`访问ChatGPT，默认
`gpt-5.6-terra`、并发1、SDK重试0、应用层最多1次有界退避、`trust_env=false`、输入/输出限长、严格JSON Schema五字段、
`store=false`且无tools。Daily Intelligence另行显式使用`gpt-5.6-sol`，不改变通用研究默认。凭据只从仓库外
`~/.qount/alpha-agent.env`读取。接口是显式opt-in；离线fixture或单角色真实调用通过不代表模型可用于策略晋级，更不代表下单权限。

## 7. 晋级门

```text
机制假设 -> 冻结合同 -> discovery -> untouched/new-time review
         -> shadow -> 最小实盘 -> 风险预算逐级增加
```

- G0 Data/Capacity：来源、as-of、覆盖、规则、流动性、有效广度、成本和容量。
- G1 Research：相对Base/BTC/TOP3的净结果，分段稳定，trial ledger完整，无泄漏。
- G2 Promotion：冻结候选在新时间数据通过，敏感性和块Bootstrap不依赖单一事件/年份；多重试验按假设族记录。
- G3 Shadow：Base的60根完成日线继续构成operational observation，不构成新Alpha统计证据，也不阻断owner明确授权的
  100 USDT canary。Equity Mapping至少
  30个独立美股交易日期；Funding按独立拥挤episode；LiquidTrend按独立调仓日期和市场阶段报告。
- G4 Minimal Live：owner单独授权，私有预检、幂等、回滚、无未管理仓位、标准账本和三方对账；7天dry保留为观察指标。
- G5 Scale：实盘摩擦、偏差和容量均在合同内，才允许逐级增加风险预算。

## 8. 90天推进顺序

| 时间 | Base/Production | Equity Mapping | LiquidTrend | LLM信息 |
| --- | --- | --- | --- | --- |
| 第1-2周 | Key只读门、幂等、恢复、对账、1000规则模拟 | 只持续采集raw | 不推进PnL | schema/validator/allowlist |
| 第3-4周 | order-free paper | symbol/time/calendar/corporate-action合同 | G0数据审计 | 5-10个fixture和泄漏单测 |
| 第5-8周 | 达门才shadow/最小实盘 | 冻结唯一一个正式trial | 最多一个预注册trial | 不做收益特征研究 |
| 第9-12周 | 不因盈亏改参数 | 累积独立交易日期 | shadow或关闭假设族 | 只维护fixture基础层 |

资源分配目标为：Base/执行30%，Equity Mapping 35%，LiquidTrend 25%，Funding/LLM 10%。这不是日历硬承诺；
新数据和实际结果优先于计划。

## 9. 第一批执行任务

1. 生成LiquidTrend10 G0容量artifact：10币日线、funding、quote-volume、相关矩阵、有效广度和1000 USDT过滤器。
2. 建立Equity Mapping跨场所symbol contract，下一版补真实premarket锚和公司行动日历。
3. 为LLM事件层实现schema/validator/fixture，不接交易或权重。
4. Binance生产端已接受owner指定的现有Key并通过私有只读预检；2026-07-21/22 owner要求固定100 USDT并直接推进B/C/D与minimal-live。
   forward/paper/dry日历值继续观察但不阻断；有效arm、当前标准authority、账本/对账和账户安全门仍阻断每轮订单，
   旧交易cron不恢复。

执行进度（2026-07-22）：

- Phase B/C/D已部署为release `0.2.5`。Base完成manual arm、`minimal_live` promotion、首次live账本闭环和recurring幂等复跑；
  live timer在维护前为`enabled/active`，当前因0.2.7升级已停，forward timer和production cron为关闭。当前run
  `/root/qount/state/mini_trend/forward/runs/20260722T061346Z`的readiness为`2d59b071...49b26`，账户全平、0挂单、
  registry=`minimal_live`、HALT absent。首次live目标权重全零，0订单/0成交，但post reconciliation passed。

- Base生产前置service已部署到VPS，由live cycle先刷新TOP3公开rules/bar/funding，再运行只读preflight、幂等paper journal、
  latest causal projection、当前账户/普通单/条件单快照、dry dispatcher、独立runtime proof和fail-closed readiness；
  `qount-mini-trend-forward.timer`保持`disabled/inactive`。2026-07-21只读审计显示可用余额`486.15970914 USDT`，仅用于验证
  至少覆盖本次固定`100 USDT` canary；owner接受现有VPS-only key和Spot/Margin权限，Reading/Futures/IP限制/提现关闭及
  TOP3 one-way/isolated 1x/全平/0挂单均通过。
- MiniTrend dispatcher已实现源hash与决策hash绑定、确定性client ID、重复决策锁、append-only row/chain journal、
  exchange-native `STOP_MARKET closePosition`、成交后仓位/保护单对账、5%日损/10%累计回撤flatten+halt和独立manual arm。
  当前recurring路径已验证order-free refresh、dry duplicate no-op和live decision幂等no-op。60/10 forward、30天paper、7天dry
  是非阻断观察项；完整funding journal、authority/RuntimeLedger/对账和有效arm继续作为每轮硬门。这些门只授权Base 100 USDT，
  不会让RiskTier、FundingVeto或其它sleeve获得订单权。
- 任务1已完成v0.2 G0 artifact。1777个BTC参考日中10币共同1772日，覆盖`99.7186%`；10币Funding经交易所
  结算时间最近分钟规范化后覆盖全部通过，最低单币日成交额中位数约`225.47m USDT`。原始毫秒时间戳会把
  相邻两天错误分成2/4次结算，已由回归测试修复，不做0填充。
- 全窗平均绝对相关性`0.661578`、有效广度`1.437979`；2021-22/2023-24/2025-26分别为
  `1.384389/1.627722/1.276677`。简单十币横截面没有越过2.0广度门，原始LiquidTrend10 score trial不启动。
- WSL直连`fapi.binance.com`和IPv4重试仍超时，`data-api.binance.vision/fapi`为404；现有runtime UM规则只有
  BTC/ETH/BNB/SOL共4/10。未使用VPS中转或未知代理，规则覆盖门保持阻断。
- 任务3的`InformationEvent`合同、来源域/时点/重复/下单语言validator和确定性feature row已实现；LLM摘要
  不自动进入数值特征，`orders_allowed=false`。已增加6个固定fixture并把研究默认客户端切到
  `relay-station` ChatGPT `gpt-5.6-terra`；遵守网关配额保护规则，本轮没有发送throwaway推理探测。
- 禁用环境代理后的OpenAI SDK只读`GET /v1/models`返回200、16个模型并包含`gpt-5.6-terra`；这只证明网关模型
  目录和认证链路可达，不证明任何LLM输出有效，也不构成策略或promotion证据。
- 官方源正文层已实现无代理抓取、初始/最终URL双allowlist、HTML可见文本解析、512 KB上限、原文hash和LLM上下文
  边界；当前只完成fixture验证，没有启动大规模公告采集或搜索型策略trial。
- 首个真实terra任务审阅Binance官方Public Data README，source SHA-256
  `085ab913...f7c6`。确定性复核确认现有解析器已有2025微秒时间戳归一化，但缺官方ZIP sidecar验证；现已新增
  `verified_archive_fetch`/`.CHECKSUM`解析与hash/filename双绑定。该helper只用于新严格摄取，旧缓存不会被静默
  标为已验证；远端归档可修订，因此本地精确bytes/hash/manifest仍是复跑真相。
- 组合治理合同已代码化：小账户并行实盘上限、三NAV归因、压力损失风险标量、每假设族3个正式trial、前向污染
  降级和独立样本计数均有fail-closed单测。
- 组合Strategy Plane进一步落地标准`StrategyIntent`和Base causal projection adapter；allocator只接受allowlist策略，
  按sleeve压力损失预算缩放后再聚合，并检查同批decision time、总gross、单币cap、相关簇和最小名义。最小名义
  先按Standalone sleeve检查，再按组合检查，禁止Base净额掩盖一个自身不可成交的事件sleeve。任一异常让整个批次
  目标归零并保留proposed targets/blockers/allocation hash；当前未接VPS dispatcher，不改变Base生产路径。
- 第144个正式trial为预登记Capitulation Rebound；18个独立episode的中位净收益`-1.8747%`、复合price+cost
  `-36.4990%`、maxDD`39.5163%`、BTC-beta residual中位`-0.5374%`，严格拒绝且不救援。预登记/最终artifact位于
  `state/research_runs/20260719T093752Z-mini-trend-capitulation-rebound-preregistration/`和
  `state/research_runs/20260719T094147Z-mini-trend-capitulation-rebound-price-discovery/`；WSL当时SSH超时，运行只读
  Mac既有小型UM日线cache，未下载、未使用VPS研究计算，也未计作promotion或Standalone Executable NAV。
- 任务2的结构化合同已由Equity Mapping G0 v0.3推进到v0.4 raw-lineage gate，但尚未获得真实三腿同步数据。合同固定纽约
  `09:25`、决策前30秒窗口、5秒三腿skew、USDTUSD与price multiplier显式方向、bid/ask gap区间、公司行动
  point-in-time归一化、压力场景血缘和0.25%账户压力预算。经济事件ID按venue/symbol/cash date稳定生成，证据
  修订另有hash；报告会重算ID并拒绝伪造、重复和合同hash漂移。
- 新增`equity_mapping_raw_collection_v0.1`：每批必须同时覆盖逐资产instrument mapping、mapped quote、cash
  premarket quote、corporate action、event context及全局USDTUSD、cash calendar、stress scenario；只保存
  response body，不保存认证header，HTTPS URL拒绝内嵌凭据/敏感query。三腿source/capture时点必须在冻结窗口内、
  全批skew不超过5秒。原始bytes经SHA-256回读后按`cash-date/batch-hash`写入不可覆盖目录，同内容幂等复用，
  修订内容生成新目录而不覆盖旧证据。
- 非合成`point_in_time_collection`现在必须通过`--raw-manifest`引用sealed bundle；G0按现金日核对mapping、三腿、
  日历、公司行动、event context和stress共8类source hash，缺任一项即
  `block_equity_mapping_g0_raw_lineage`，不得声称market evidence。旧v0.3 artifact不追溯升级。
- 两轮有效terra红队先后确认中点不可成交、公司行动因子未使用、asset-event修订重复、压力场景无来源和报告
  信任外部ID等缺口；只吸收可由代码复现的意见。最终合成fixture为2个asset-event/1个独立cash date，全部
  数据合同有效但严格停在`collect_equity_mapping_independent_dates`；它只证明管道，不计入真实市场证据。
- 最终G0 artifact：`state/research_runs/20260718T180643Z-equity-mapping-g0/equity_mapping_g0.json`，SHA-256
  `fd93d83a...2266`，contract hash `dcbef759...1e46`。下一有效输入必须来自同一决策时点可见的mapped/cash
  premarket/USDTUSD三腿、官方日历/公司行动和有血缘的stress scenario；旧18日期不能直接补成合格记录。
- 首个采集readiness artifact为
  `state/research_runs/20260719T054823Z-equity-mapping-collection-readiness/equity_mapping_collection_readiness.json`，
  SHA-256 `b8576583...d463`；目标现金日`2026-07-20`，纽约窗口`09:24:30-09:25:00`（UTC
  `13:24:30-13:25:00`），当前状态`await_collection_window`。它没有raw market observation、PnL或strategy
  trial；该时点累计策略trial为143，随后Capitulation Rebound正式trial使当前总数变为144。只有真实窗口到来且
  八类输入齐全时才能seal第一批。
- raw intake CLI仍只是provider-neutral sealing，不主动联网抓报价。其外新增
  `equity_mapping_source_capacity_v0.1`：bounded no-proxy fetcher验证初始/最终host并限制2 MiB，parser只接受
  Binance server-time bookTicker、Bitstamp microtimestamp L1、Nasdaq target-date calendar，以及显式可证明日期的
  quote/corporate-action/event context；HTTP接收时点永远不能补缺失的market quote时点。
- trial=0 source-capacity artifact
  `state/research_runs/20260719T065611Z-equity-mapping-source-capacity/equity_mapping_source_capacity.json`，SHA-256
  `ee0799d7...09d58`、contract hash `b12a7f23...ed6dd`、raw manifest content hash `aa91e8d1...466d7`。10个公开小
  探针中只有Nasdaq market-info通过cash-calendar；Binance两项和四个USDTUSD venue在当前Mac无代理路径为
  `transport_unavailable`，Nasdaq cash quote为delayed/N/A/无quote-event timestamp，split和earnings也不能证明
  目标日语义。required roles为1/8通过，stress source尚未分配，verdict
  `block_equity_mapping_source_capacity`。
- 这份容量证据不创建market event、不读取未来收益/PnL、不增加第144个trial，也不运行collector。真实窗口前仍须
  取得timestamped executable cash premarket bid/ask，并让mapping、mapped quote、USDTUSD、calendar、corporate
  action、event context、stress八类raw hash同批seal；否则不能生成非合成bundle或声称采集服务已运行。

最终artifact：
`/mnt/e/qount_data/qount/artifacts/experiments/20260718T164231Z-liquidtrend10-g0-v02/liquid_trend10_capacity.json`，
SHA-256 `743f83c1...2728`；manifest content hash `93206835...101c`。

## 10. 当前不可做

- 不因1000 USDT计划而立即提高Base风险目标、恢复Risk2、short、carry或总gross>1。
- 不把当前18个TradFi独立日期训练成神经网络。
- 不把10个高相关币当成10个独立下注，不使用当前市值倒推历史幸存者池却声称无偏。
- 不把LLM生成的情绪分数直接接仓位，不允许LLM修改风控或实盘配置。
- 不购买/下载高频大数据，除非低频结构假设明确证明现有数据无法检验且owner重新批准预算。

## 11. Attribution Contract

- `Signal NAV`用于回答信号本身在标准成本假设下做了什么，不等于可执行业绩。
- `Standalone Executable NAV`使用该sleeve独立执行的真实规则和成本，是唯一晋级口径。
- `Portfolio Realized NAV`使用净额合并后的真实成交，是账户PnL和对账口径。
- allocator必须单独记录netting savings；该节省不得分配回任何standalone NAV，不得重复归因。

## 12. Research Trial Budget

每个`hypothesis_family`最多3个冻结正式trial。每个trial必须预先写入
`hypothesis_family/preregistered_primary_metric/preregistered_failure_condition/allowed_sensitivity_range/
number_of_prior_trials`。三次未通过即关闭该假设族；继续研究必须提交不同经济机制，而不是围绕旧历史收益微调。

探索性诊断可以运行，但不得伪装成“未计trial”的正式候选，也不得参与promotion选择。

## 13. Forward Contamination Rule

- 新时间段第一次评价冻结候选时可标`promotion_pool`。
- 查看结果后，只要修改阈值、过滤条件、持有期、权重、数据处理或执行规则，该时间段立即变为`consumed_pool`。
- 修改后的版本必须等待下一段尚未发生的数据；不能继续把滚动前向窗口称为独立holdout。
- 只有未改规则的运行故障修复可申请保持pool角色，且必须证明没有改变任何信号、仓位、成本或成交语义。

## 14. Independence Unit

| Sleeve | 独立单位 | 必报辅助计数 |
| --- | --- | --- |
| Base | 完成日线只作运行单位 | operational days；statistical alpha units固定为0 |
| Equity Mapping | 独立美股现金交易日期 | asset-events、独立周、财报、普通周末、节假日 |
| Funding Event | 从进入极端到退出并冷却结束的episode | 原始观测数、episode数、持续时间 |
| LiquidTrend | 独立调仓日期并分市场阶段 | 调仓数、牛/熊/震荡覆盖、簇集中度 |

## 15. Security And Recovery

- 当前/一般文档和脚本不保存公网IP；使用仓库外`QOUNT_VPS_HOST`或本机SSH别名`qount-vps`。
- 研究只读、数据采集和生产交易使用不同凭据；生产交易凭据不进入Mac研究环境、artifact或LLM上下文。
- raw数据至少两份物理副本；每批生成Merkle/root manifest，并把root hash锚定到另一设备或私有远程仓库。
- 每日journal root hash签名后推送到独立只写存储；chain hash本身不能防止整链重建。
- 定期做随机checksum审计和恢复演练；artifact、manifest和运行代码不得只存在同一块外置盘。
