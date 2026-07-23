# qount 策略研究与情报推进路线

版本：`v0.3`

更新时间：`2026-07-23`

状态：owner要求形成的research_sandbox路线；允许设计来源、实验合同和离线研究，不构成promotion、paper、live、
carry、short、杠杆、期权交易或生产配置变更授权。

## 0. 研究定位

当前系统最强的是可追溯生产控制面，最弱的是独立收益源、真实成本样本和从研究到成交的迁移证据。研究目标不是承诺
“私募级收益”，而是持续淘汰不能同时满足以下条件的假设：

1. 扣除可执行成本后仍有经济增量；
2. 相对BTC/TOP3和已有策略具有可解释的残差收益；
3. 在时间、市场阶段和参数邻域上不过度依赖单一点；
4. 能由当前或明确规划的交易架构执行；
5. 研究、shadow、paper和live差异可归因。

当前共同基线：

- Base v0.2是唯一真钱策略和所有加密方向研究的生产对照；
- BTC、ETH、BNB是三个交易载体，不默认视为三个独立收益源；必须用共同market/momentum/size等暴露和有效广度证明分散；
- X4、C×D、RV-C、CTA-R历史读数均为legacy/guarded/consumed evidence，不是可直接组合的已晋级edge；
- LiquidTrend10首个G0有效广度仅`1.438`，原10币横截面trial被阻断；
- 既有price-only ML、HMM、GRU、宏观/链上风险缩放和多个overlay已留下负证据；
- 当前部署约束仍是低频、Binance USD-M钱包、no-carry、no-short、无杠杆增益、effective gross `<=1`；
- 研究可以提出超出当前部署约束的未来路线，但开始相应正式trial前必须有owner对该hypothesis family的明确授权。

## 1. 对三组建议的研究分流

| 建议 | 路线处理 |
| --- | --- |
| 多速度趋势 | 作为新的有限trial hypothesis family，Base继续作为冻结控制组，不做SMA参数无限扫描 |
| point-in-time流动性宇宙 | P0数据基础；先审计退市、规则、成交额、盘口、OI、funding和缺失，再看PnL |
| 横截面动量 | 只有新宇宙G0证明有效广度和容量相对LiquidTrend10发生实质变化后才启动 |
| 波动率/危机状态层 | 可研究，但必须引入与既有失败price-only缩放不同的信息或目标 |
| ML meta-labeling | 仅用于波动、成本、成交和异常等元任务；不直接生成live权重 |
| carry/basis | 设为`blocked_pending_owner_authorization`；不因旧RV-C结果恢复 |
| VRP/期权 | 远期capacity lane；当前options surface数据门失败，不能直接回测或卖波动 |
| 跨资产CTA-R | 提升为高价值重新认证候选；先复核selection-free、新时间、可交易ETF/期货通道和成本，不继承旧promotion资格 |
| C×D趋势+carry | 作为组合数学候选单独复核；carry/no-carry、双腿执行、尾部和场所权限仍是硬门，不直接进入paper/live |
| maker/post-only | 作为执行经济学family，不把理论maker费率当作alpha；必须测成交率、等待成本、逆向选择和fallback taker |
| 风险预算/尾部保护 | 先研究波动率目标、权重上限、压力损失和相关性闸门；不默认使用协方差优化或期权对冲 |
| “三个真edge直接组合” | 不接受为前提；每条线必须重新生成独立当前版本证据 |
| 固定PBO/DSR/Sharpe行业门槛 | 只作研究参考；每个family在看结果前冻结自己的主指标和失败条件 |

## 2. 全局实验账本

现有分线trial记录继续保留，新增跨线只追加`GlobalExperimentRecord`索引：

```json
{
  "experiment_id": "...",
  "hypothesis_family": "multi_speed_trend_v1",
  "trial_number_within_family": 1,
  "research_question": "...",
  "economic_mechanism": "...",
  "baseline_ids": [],
  "preregistered_primary_metric": "...",
  "preregistered_failure_conditions": [],
  "allowed_sensitivity_range": {},
  "dataset_ids": [],
  "data_role": "discovery_pool",
  "untouched_data_ids": [],
  "code_hash": "...",
  "config_hash": "...",
  "source_hashes": {},
  "first_result_observed_at": null,
  "reviewer_observations": [],
  "result_artifact_hash": null,
  "decision": "planned|retain|reject|blocked",
  "contamination_notes": []
}
```

规则：

- 每个`hypothesis_family`最多3个冻结正式trial；探索诊断也登记，但不能伪装成不计trial的promotion候选；
- 已查看窗口默认`consumed_historical_discovery_pool`；改参数后不能继续称其为独立OOS；
- 负结果、blocked capacity和未完成实验同样进入账本；
- 同一经济机制换模型、阈值或窗口仍属于同一family，除非预先证明信息集或执行合同发生实质变化；
- `reviewer_observations`记录谁在何时看过哪一版结果；任何被人或LLM读取过的结果窗口都不能继续列入`untouched_data_ids`；
- 任何candidate必须能从proposal追到source、preregistration、dataset、code、result和decision。

## 3. 研究情报平面扩展

### 3.1 与现有Daily Intelligence的边界

VPS现有Daily Intelligence继续只负责生产相关的一手信息：Binance公告、Fed、SEC、当前行情、运行账本、六角色复盘和微信通知。
它每日`04:30 UTC`运行，不承担批量论文库和模型训练。

新增`Research Intelligence`旁路：

```text
metadata discovery
-> candidate dedup/revision check
-> original publisher/official PDF fetch
-> raw bytes + hash + timestamps
-> deterministic metadata/text extraction
-> LiteratureRecord
-> LLM librarian/methodology/red-team review
-> bounded ResearchProposal
-> capacity/novelty gate
-> human or deterministic preregistration
-> experiment runner
```

研究情报建议由Mac编排、Windows/WSL执行并把最终记录写外置盘；不在VPS保存论文批次或运行研究模型。

### 3.2 来源等级

| 等级 | 类型 | 用途 | 是否能单独支持实验事实 |
| --- | --- | --- | ---: |
| T0 | Binance等交易场所官方规格/变更 | production impact、成本和执行合同 | 是，但仍需运行时验证 |
| T1 | 原始论文、官方working paper、监管/央行研究 | 机制、方法、数据定义 | 是，结论仍需本项目复现 |
| T2 | AQR、Man等机构研究 | 假设背景、实现差异、反例 | 否，需T1或本地证据 |
| T3 | Crossref/OpenAlex等元数据发现服务 | DOI、版本和候选发现 | 否，必须回到原文 |
| T4 | 博客、新闻、社交摘要 | 线索 | 否，不能进入数值特征或promotion |

### 3.3 首批订阅和探测结果

| 来源 | 频率 | 路由 | 2026-07-23只读探测 | 处理 |
| --- | --- | --- | --- | --- |
| Binance USD-M changelog | 每日 | 官方HTML | HTTP 202后重定向到英文当前页 | 保存最终URL/正文hash，变化触发生产影响审查 |
| Binance公告 | 每日 | 已有官方catalog API | 已在生产使用 | 保持现有pipeline |
| Federal Reserve | 每日 | 已有RSS | HTTP 200 XML | 保持现有pipeline |
| SEC | 每日 | 已有RSS | HTTP 200 RSS | 保持现有pipeline |
| arXiv `q-fin.TR` | 每周 | `https://rss.arxiv.org/rss/q-fin.TR` | HTTP 200 RSS | 论文候选发现，最终保存arXiv正文/PDF hash |
| Crossref | 每周 | `api.crossref.org` | HTTP 200 JSON | DOI/出版元数据发现，不作结论来源 |
| OpenAlex | 每周 | `api.openalex.org` | HTTP 200 JSON | 去重、引用和开放版本发现，不作结论来源 |
| NBER | 每周候选 | Crossref/OpenAlex或官方papers页 | `rss/new.xml`返回403 | 不写不存在的RSS适配器，最终回到nber.org原文 |
| BIS | 每周候选 | Crossref/OpenAlex或官方research页 | 测试RSS路径返回404 | 不写不存在的RSS适配器，最终回到bis.org原文 |
| SSRN | 双周/人工seed | metadata发现后回到原文 | seed页面直连探测返回HTTP 403 | 不依赖直抓；先审计可用官方版本、版权和抓取规则 |
| AQR/Man | 双周/人工seed | allowlisted HTML或搜索发现 | seed页面HTTP 200，尚未纳入当前allowlist/parser | 先做source capacity、版本和版权/抓取规则审计 |

当前`DEFAULT_ALLOWED_SOURCE_DOMAINS`不包含arXiv、Crossref、OpenAlex、NBER、BIS、AQR、Man或SSRN。实现扩展前必须逐域增加：

- HTTPS/redirect/domain/端口验证；
- content type与最大字节数；
- PDF独立解析和原始字节保留；
- published/updated/observed/available时间；
- robots/使用条款和请求频率；
- fixture、重定向、超限、损坏PDF、版本修订和hash篡改单测。

### 3.4 LiteratureRecord

```json
{
  "literature_id": "doi|arxiv|publisher-id|content-hash",
  "title": "...",
  "authors": [],
  "publisher": "...",
  "published_at": "...",
  "updated_at": "...",
  "observed_at": "...",
  "discovery_sources": [],
  "canonical_url": "...",
  "doi": null,
  "document_hash": "...",
  "parser_version": "...",
  "asset_classes": [],
  "mechanism_tags": [],
  "sample_window": {},
  "cost_assumptions": {},
  "validation_method": [],
  "reported_limitations": [],
  "replication_capacity": "ready|partial|blocked",
  "project_novelty": "new_family|new_information|implementation_variant|duplicate",
  "orders_allowed": false,
  "live_changes_allowed": false
}
```

元数据和正文修改必须创建revision，不覆盖旧记录。标题或LLM摘要相似不能代替DOI/content hash去重。

### 3.5 LLM角色和输出

Research Intelligence使用五个旁路角色：

| 角色 | 输出 |
| --- | --- |
| Librarian | 来源身份、版本、重复、数据和代码可得性 |
| Methodology Reviewer | 样本、标签、成本、验证、统计方法和泄漏风险 |
| Economic Reviewer | 机制、风险承担、与Base/既有family的关系 |
| Replication Designer | 最小数据集、baseline、kill test、容量门和trial预算 |
| Red Team | 共同beta、幸存者偏差、多重检验、不可执行假设和反例 |

唯一可进入研究队列的输出是结构化`ResearchProposal`：

```text
hypothesis_family
mechanism
novelty_vs_existing_failures
required_sources
data_capacity_status
baseline
primary_metric
kill_test
cost_model
beta_residual_plan
holdout_role
trial_budget
implementation_scope
blocked_reasons
```

任何proposal仍固定`orders_allowed=false/live_changes_allowed=false`。LLM不得决定阈值、权重、promotion或owner authorization。

### 3.6 通知策略

- Binance规格或当前adapter能力变化：立即`production_impact_review`告警；
- 出现满足新机制、可获得数据、与现有失败不同且可做kill test的论文：进入每周研究摘要；
- 普通新论文、重复研究或无数据容量：只归档，不即时打扰；
- 每月输出source health、抓取失败、revision、重复率和proposal转实验率；
- 不因“论文声称高Sharpe”触发策略晋级或生产通知。

## 4. 研究优先级

### R0：研究基础设施和真实性，P0

目标：在新增策略前先建立GlobalExperimentRecord、LiteratureRecord、point-in-time universe和统一scorecard。

交付：

- 全局实验索引和历史family映射；
- Research Intelligence discovery/原文/hash/LLM proposal MVP；
- USD-M point-in-time symbol lifecycle、rules、delisting和数据完整性合同；
- 按月或按季度冻结universe revision，保存每次纳入/排除原因，不用今天仍存在的symbol反填过去；
- 统一`Signal NAV / Standalone Executable NAV / Portfolio Realized NAV`口径；
- 统一market/TOP3 beta residual、成本、trial count和fold稳定性报告。

实现状态（2026-07-23，合同已随 `0.2.14` 部署，未运行候选 PnL）：

- `src/qount/governance/research_records.py` 已新增 `GlobalExperimentRecord`、`HistoricalFamilyMapping`、
  `PointInTimeSymbolLifecycle`、`PointInTimeUniverseRevision`、`UnifiedNavScorecard` 和
  `CandidateRevalidationRecord` 的 hash/validation 合同；
- point-in-time universe builder 只按 `valid_from <= as_of < valid_to` 选择当时 active symbol，不用未来上市或已退市状态反填；
- 统一 scorecard 同时保存 Signal NAV、Standalone Executable NAV、Portfolio Realized NAV、beta residual、成本、trial count
  和 fold metrics；它是报告合同，不是 allocator 或 promotion；
- `scripts/research/build_r0_records.py` 生成两个不可覆盖的本地候选合同：CxD 为
  `blocked_pending_owner_authorization/observation-shadow-virtual-only`，CTA-R 为 `research_only/planned`；二者
  `orders_allowed=false`，未接入 VPS allocator；
- R0 尚未完成项仍包括历史 trial 的实际 family 迁移表、真实 USD-M lifecycle 数据摄取、LiteratureRecord/Research Intelligence MVP、
  两个候选的当前数据 IDs、冻结 cost model、Standalone NAV 和 Candidate scorecard。未完成项不得用占位记录替代证据。

### R0.1：Edge储备与组合候选重新认证，P0/P1

当前研究不把“工程能力强”当作收益证据，也不把单一加密市场的币数当作edge breadth。LiquidTrend10的有效广度`1.438`
是当前容量先验，足以阻止无边界扩币；它不是不经新数据就能外推到所有市场的数学定理。下一阶段应把研究预算从“第N个
crypto sleeve”转向两个可证伪的候选组合方向：

1. **C×D重新认证**：把历史趋势+carry组合只作为组合构造假设，重新建立当前版本的两份Standalone NAV、共同因子/crypto beta、
   basis tail、双腿成本、场所集中和独立新时间证据。carry仍处于`blocked_pending_owner_authorization`，因此只能先做
   observation、shadow attribution和virtual allocator，不能因为历史负相关或目标Sharpe直接paper/live。
2. **CTA-R跨资产重新认证**：优先复核selection-free ensemble、walk-forward OOS、可交易ETF/期货通道、真实费用、时区、税费和
   账户约束；跨资产广度若能稳定通过，不代表它自动成为当前Binance钱包的sleeve。期货券商、海外券商或新场所都需要独立
   venue/data/owner合同，不能把ETF研究读数当作已认证期货edge。

这两条路线的目标是验证“跨资产广度 × 多个低相关薄edge”的组合假设，而不是预先承诺Sharpe `1.0-1.3`或任何年化收益。
组合收益、风险贡献和尾部必须先由统一allocator的virtual NAV重建，再决定是否值得进入promotion review。

每个候选必须先生成`CandidateRevalidationRecord`，再运行任何组合PnL：

```text
candidate_id / hypothesis_family / historical_evidence_ids
current_data_ids / untouched_data_ids / venue_and_account_scope
baseline_ids / frozen_cost_model / execution_contract
standalone_nav_artifacts / factor_and_beta_plan / tail_scenarios
primary_metric / kill_tests / trial_budget / owner_authorization_state
decision = planned | retain | reject | blocked
```

### R0.2：两个候选的最小退出门

**C×D趋势+carry**必须依次通过：

1. 趋势腿和carry腿分别重建当前版本的Standalone Executable NAV，使用独立数据水位和成本模型；
2. 对两腿及组合分别报告crypto beta、market/momentum/carry暴露、basis tail、legging、资金占用和场所集中；
3. 在新时间或未消费窗口上完成价格连续、funding/contract完整和双腿可执行性审计；
4. 只在两腿都没有硬阻断时运行virtual allocator；carry仍停留在shadow/virtual，除非获得新的owner授权。

任一腿的after-tail净收益非正、required maker fill超过1、独立NAV无法对账或新时间证据缺失，candidate=`blocked|reject`，
不得通过调组合权重救援。

**CTA-R跨资产趋势**必须依次通过：

1. 固定selection-free ensemble或预登记walk-forward，不以历史最优lookback作为唯一结果；
2. 保存point-in-time ETF/期货标的、上市/退市、跟踪误差、时区、费用、税费和容量；
3. 报告有效广度、单资产/类别贡献、债券/黄金/海外股regime集中和真实可交易通道；
4. 先进入cross-asset virtual sleeve，再讨论新的venue或期货授权，不能把杠杆带来的名义收益写成alpha。

若selection-free、当前成本或可交易通道任一硬门失败，保留方法记录但停止组合晋级；不为达到目标Sharpe增加资产、杠杆或
lookback网格。

### R1：多速度趋势族，P1

研究问题：固定的fast/medium/slow趋势forecast组合，能否降低Base单一参数点依赖，并在扣除真实规则和成本后改善残差风险收益？

统一表达为：

```text
Forecast[i,t] = clip(w_fast * F_fast[i,t]
                   + w_medium * F_medium[i,t]
                   + w_slow * F_slow[i,t])
```

fast负责事件后的快速降险，medium承担主要持仓，slow表达长期牛熊状态。`F`可以来自breakout、EMA或标准化收益动量，
但尺度、标准化、裁剪和`w_fast/w_medium/w_slow`必须在读取候选结果前冻结；连续forecast不得被事后阈值化成新的参数搜索。

首个family只允许三个冻结正式trial：

1. 多速度方向一致性基线；
2. 固定连续forecast等权组合；
3. `slow regime + medium position + fast de-risk`分层合同。

要求：

- 速度、标准化、组合权重和裁剪在看结果前冻结；
- 不把相邻SMA/EMA/回看期网格拆成“新family”；
- Base v0.2完整路径是控制组，不修改其live参数；
- forecast先生成独立Signal NAV和Standalone Executable NAV，不在组合净额后才计算成本；
- 报告raw和BTC/TOP3 beta residual、成本翻倍、延迟一根bar、随机漏单、参数邻域和市场分段；
- 任何retain版本先进入virtual/shadow，不替换Base。

### R2：point-in-time universe与流动性约束横截面，P1条件项

只有R0证明相对当前LiquidTrend10发生以下实质变化才启动PnL trial：

- 历史上市/下架和可交易状态可重建；
- 至少8个同期标的具有完整bar/funding/rules/流动性；
- 有效广度、第一主成分和相关簇达到预登记容量门；
- 上线时长、成交额、盘口深度、OI、spread、缺失率、min-notional和precision均按决策时可见值过滤；
- 退市/缺失标的不会从历史中消失。

首个方向仍为long/cash，只在总风险门允许时做相对强度选择。第一版允许固定组合1、2、4、12周相对动量forecast，
但必须在看结果前冻结各尺度权重，并排除新上市、已公告或可识别的临近退市、极端funding和不可执行标的；单币和相关cluster均有上限。
第一阶段不做long/short。若新宇宙仍表现为单一crypto beta，不为得到PnL而放宽广度门。

### R3：波动率和危机状态，P2

目标是估计`RiskMultiplier in [0,1]`，不直接预测方向。候选输入优先：

- realized/downside volatility和range expansion；
- OI、funding/basis极值和价格背离；
- 可验证的流动性/深度退化；
- BTC-alt相关性跃升；
- 交易所、稳定币或规则异常的确定性事件。

既有price-only RF/HMM/GRU和宏观/链上风险缩放失败不能通过换阈值复活。新trial必须明确新增信息集或不同经济目标，并以
“少赚多少换回多少drawdown改善”和尾部残差为主，不只看Sharpe。

`crash-safe momentum`只能作为一个独立、预登记的风险状态假设：比较快速波动跃升、短长期趋势背离和相关性同步上升时的
非对称de-risk，与简单volatility scaling、Base和多速度趋势控制组逐项对比；不得在观察到某次崩盘后反向选择阈值。

### R4：ML元模型，P2条件项

先使用架构计划中的认证和自然成交数据，研究：

- 波动率、滑点和stop gap风险预测；
- 成交概率和maker等待价值；
- 订单/账户/数据异常检测；
- 不同策略相关性是否进入异常状态；
- 主信号meta-label，但只输出研究概率。

Logistic/常数先验/确定性规则是强制baseline。使用chronological walk-forward、purge/embargo和真实成本；预测准确率不能替代净收益或执行改进。

### R5：carry/basis，暂停等待授权

旧RV-C和C×D只提供机制与工程教训，不提供当前promotion资格。若owner未来明确重启，必须新建独立StrategyIntent和新版本合同，
覆盖spot/dated/perp数据、多腿状态机、legging risk、collateral、venue exposure、tail stress和独立NAV。不得把carry重新塞进Base过滤器后声称独立收益源。

若未来获批，固定按以下证据顺序推进，每一级都需要独立artifact和新的owner授权，不能跨级：

```text
funding observation
-> shadow attribution
-> paper hedge
-> minimal delta-neutral live
```

每一级分别归因funding forecast误差、basis变化、两腿费用/滑点、legging损失、资金占用和场所集中；所谓market-neutral必须由
实际beta和压力情景证明，不能由“现货多 + 永续空”的名义结构直接推出。

C×D的组合回测只能在两条独立NAV都完成当前版本重建后运行；组合结果不回写Base参数，不把carry过滤器包装成趋势alpha，
也不允许用组合净额掩盖某一腿的不可执行或basis-tail失败。

### R6：options/VRP，远期capacity lane

当前Deribit历史option surface和公共容量在G0被阻断，因此先做数据/许可/执行能力审计，不做卖波动PnL回测：

- 可获得的point-in-time chain、IV surface、bid/ask和expiry历史；
- delta hedge、保证金、尾部压力和多腿恢复；
- 远OTM保护成本和极端跳空；
- 数据预算、交易权限和场所风险。

只有capacity通过且owner明确允许新的期权研究family，才可写首个trial。

若未来研究卖波动，优先采用“净carry + 远OTM保护成本 + 压力损失预算”的尾部对冲合同，而不是裸卖vol；保护成本、delta
hedge滑点、保证金占用和跳空损失必须进入Standalone NAV。这个合同仍不改变当前options surface G0阻断和no-options权限。

### R7：跨资产趋势，P1高价值重新认证

CTA-R历史可作为方法和baseline背景，但当前仍是guarded blueprint。优先顺序是：

1. 固定selection-free ensemble和walk-forward合同，先在可交易ETF上复核；
2. 报告跨资产有效广度、单一资产/类别贡献、债券/黄金/海外股regime集中和真实跟踪误差；
3. 再评估期货券商或其他场所的容量与执行，不把杠杆或期货授权当作策略收益证明；
4. 只有新时间、成本、账户权限和venue capability均通过，才进入virtual allocator。

多频段趋势（例如fast 20-60日、medium 60-120日、slow 120-250日）可以作为一个冻结trial合同；不得围绕最近结果继续扩展
lookback网格，也不得以“期货杠杆”掩盖ETF边际收益或新venue风险。

### R8：执行经济学与风险预算，P1条件项

这条线不先声称新增alpha，而是验证薄edge是否能被兑现、组合是否能在尾部保持可控：

- `post_only/maker`：冻结maker/taker费、实际fill概率、等待机会成本、逆向选择、取消/重挂和fallback taker成本；
  required fill rate超过1或after-tail净收益非正时立即kill；
- `TWAP/VWAP`：只有组合名义和容量门触发才启动，先做paper/shadow slice replay；100 USDT canary不引入该复杂度；
- 风险预算：先用固定压力损失预算、单资产上限和per-sleeve volatility target；协方差只作为稳健滚动估计，相关性趋近1或
  流动性同步下降时必须降风险，不能依赖优化器“找到”分散；
- 每个组合候选都输出单sleeve、组合、因子和无法解释残差，并把执行成本和尾部对冲成本从alpha中剥离。

### R9：跨策略组合复核，P1条件项

只有C×D、CTA-R或其他候选各自通过当前promotion合同，才可研究统一allocator。先用等风险/压力损失预算的简单基线，
再比较波动率目标、权重上限和相关性闸门；不得直接把协方差优化器当成生产配置。目标是验证增量风险贡献和尾部改善，
不是把历史Sharpe相加或预先锁定组合Sharpe目标。

## 5. 统一统计和经济门

每个正式candidate至少报告：

1. point-in-time universe和退市/缺失处理；
2. 基础成本及其来源、换手、break-even cost；
3. chronological walk-forward和fold稳定性；
4. raw、BTC/TOP3 beta residual和适用的共同因子归因；
5. DSR、PBO/CSCV、effective sample size和family trial count；
6. 参数邻域、市场阶段和单一事件/年份贡献；
7. 费用/滑点翻倍、延迟一根bar、随机漏单、更差成交；
8. Standalone Executable NAV，不用组合净额美化单策略；
9. 最大回撤、尾部损失、恢复时间和容量；
10. 执行归因字段：decision-to-submit、ACK/fill延迟、planned-vs-filled、maker/taker、fee、funding、adverse slippage、
    protection latency和stop gap；无真实样本时明确`unavailable`；
11. 数据/代码/config/environment/artifact hash。

### 5.1 默认内部参考门

以下只作为新family预登记时的默认起点，不是行业标准，也不能覆盖样本量、持仓重叠或经济机制不适用的问题。任何偏离必须在
看结果前记录理由和替代主指标：

| 指标 | 默认研究参考 | 读法 |
| --- | ---: | --- |
| PBO/CSCV | `<20%`，强候选争取`<10%` | 只在配置集合和切分数量足以识别时使用 |
| DSR | `>0.95` | trial count必须覆盖同family的失败和探索版本 |
| 净OOS Sharpe中位数 | `>0.5` | 同时报告各fold，不能用均值掩盖失败fold |
| break-even cost | `>=2x`基础成本 | 基础成本必须来自当前费率、spread/slippage或认证样本 |
| 单一阶段/年份PnL占比 | 默认`<=50%` | 超过不自动否决，但必须解释集中来源并加尾部压力 |
| 参数邻域 | 相邻大部分方向一致 | 不以“最佳点”替代稳定区域 |
| 成本压力 | fee和slippage翻倍后仍正期望 | 同时测试延迟、漏单和更差成交 |
| 实盘迁移 | 成本、换手、暴露和回撤未越过冻结区间 | 任何晋级只增加一层证据，不重写历史回测 |

White Reality Check或同类多重检验在实现并完成golden验证前只列为计划能力，不能写成已运行。即使所有默认参考门通过，
也只产生candidate，不自动获得paper/live资格。

### 5.2 因子与独立收益归因

所有方向或横截面candidate至少估计以下适用暴露：

```text
strategy return
= alpha
 + beta_market * crypto_market
 + beta_momentum * momentum
 + beta_size * size
 + beta_carry * carry
 + residual
```

报告必须区分总收益、因子解释收益和残差，并在正常期、压力期和滚动窗口分别估计。策略名称、币种数量或不同参数不构成
alpha breadth；只有扣成本后的残差、不同失效场景和Standalone Executable证据才能进入组合分散判断。

### 5.3 研究到实盘迁移门

```text
discovery
-> frozen candidate
-> promotion review on eligible new-time evidence
-> virtual NAV
-> shadow execution
-> paper
-> minimal live
```

每次晋级只增加一层权限，并冻结上一层的信号、成本模型、预期换手/持有期、回撤区间和数据版本。迁移scorecard逐层比较：

- forecast/目标暴露分布；
- 实际与预期换手、持有期和漏单；
- fee、slippage、funding和break-even cost；
- raw及beta residual收益、回撤和尾部损失；
- 与现有sleeve的正常/压力相关性。

偏离合同先触发Strategy HALT候选和归因审查，不能用重新拟合历史参数解释实盘偏差。一次最多晋级一个新sleeve。

## 6. 阶段路线

### 0-2个月：证据基础

- 完成GlobalExperimentRecord和历史family映射；
- 完成Research Intelligence MVP及每周摘要；
- 建立Binance changelog影响监控，仅在能力、字段、端点、filter或恢复假设可能受影响时告警；
- 建立point-in-time USD-M universe G0；
- 预登记多速度趋势family，不在预登记前扫参数；
- 预登记C×D组合复核和CTA-R selection-free复核的proposal，不读取结果前锁定新时间、成本和执行合同；
- 与架构计划并行建立T-D/T-F、execution certification离线fixture、shadow accountant和执行归因schema。

### 2-5个月：趋势核心与执行科学

- 完成多速度趋势最多3个冻结trial；
- 通过则进入独立virtual/shadow，未通过则关闭family或提出不同机制；
- 完成CTA-R可交易ETF的selection-free/walk-forward复核；若通过，再建立跨资产virtual sleeve，不接期货实盘；
- 以历史数据/fixture完成C×D双NAV、共同因子和basis-tail复核，carry仍不获得paper权限；
- 用认证/自然成交证据建立滑点、rounding和stop语义基线；
- 决定point-in-time universe是否具备启动横截面trial的容量。

### 5-8个月：第二机制候选

- 在危机状态、执行经济学、横截面动量中，只优先启动数据容量和执行合同最完整的一条；
- ML只做元任务并与简单baseline竞争；
- 若options capacity重新通过，才预登记tail-hedged VRP；否则保持blocked；
- 只有两个独立Standalone NAV均通过，才运行统一allocator的风险预算/相关性闸门消融；
- carry/basis只有收到新的明确owner授权才进入正式trial；
- 每个family独立记账，不提前混合信号。

### 8-12个月：组合化审查

- 最多选择一个拥有新时间/独立执行证据的candidate进入promotion review；
- 先virtual NAV、shadow execution，再决定是否需要paper；
- 只有两个sleeve均有Standalone Executable证据，才评估allocator和风险贡献；
- 一次只晋级一个新策略，任何live仍需另行owner授权。

月份是资源规划，不是结果承诺；capacity或kill test失败时应提前停止，不为满足日历继续投入。

## 7. 固定运行节奏

| 频率 | 任务 | 节点 | 输出 |
| --- | --- | --- | --- |
| 每日04:30 UTC | 现有Daily Intelligence | VPS | 生产/市场一手简报，不改交易 |
| 每日 | Binance changelog hash与capability impact | VPS只读或Mac轻任务 | 仅变化时告警 |
| 每周 | arXiv/Crossref/OpenAlex和curated source discovery | Windows/WSL，Mac编排 | Research Intelligence周报 |
| 每周 | proposal novelty/capacity/trial-budget triage | Mac | 接受、拒绝、blocked列表 |
| 每月 | experiment ledger、source health、contamination audit | Mac + 外置盘manifest | 月度研究治理报告 |
| 每季度 | hypothesis family和生产约束复核 | owner review | 继续、关闭或新授权 |

周报默认只发以下变化：新机制、可复现数据、新反例、生产规格影响或现有family的重要负证据。论文数量不是KPI。

## 8. 成功标准

研究系统的成功不以“找到高Sharpe论文”衡量，而以：

- 100%正式trial进入全局账本，负结果不丢失；
- 100%论文结论可追到原始文档hash和版本；
- proposal能明确区别新机制、实现变体和旧失败救援；
- capacity失败在PnL回测前暴露；
- 每个retain candidate同时给出raw、beta residual、成本和fold稳定性；
- 没有LLM输出进入target weight、risk override或production config；
- 至少一个新family在真实未使用时间上完成诚实审查，结果可以是拒绝；
- 至少一个跨资产或跨edge候选完成当前版本的独立NAV和执行/尾部审计；通过与否都记录为证据；
- 只有具备Standalone Executable证据的策略才进入组合审查。

## 9. 种子资料队列

以下资料只作为首批`LiteratureRecord`候选。进入项目证据前仍需下载原文、保存hash、抽取版本和记录访问时点：

- Liu, Tsyvinski, Wu, *Common Risk Factors in Cryptocurrency*：
  `https://www.nber.org/papers/w25882`
- Liu and Tsyvinski, *Risks and Returns of Cryptocurrency*：
  `https://www.nber.org/papers/w24877`
- Hurst, Ooi, Pedersen, *A Century of Evidence on Trend-Following Investing*：
  `https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing`
- BIS Working Paper 1087, *Crypto carry*：
  `https://www.bis.org/publ/work1087.htm`
- Moreira and Muir, *Volatility-Managed Portfolios*：
  `https://www.nber.org/papers/w22208`
- Bailey et al., *The Probability of Backtest Overfitting*：
  `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253`
- Bailey and Lopez de Prado, *The Deflated Sharpe Ratio*：
  `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551`
- Ammann et al., cryptocurrency survivorship/delisting bias：
  `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4287573`
- 用户提供的cross-sectional momentum研究seed，身份和版本待验证：
  `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2949379`
- 用户提供的2026年Bitcoin ML交易研究seed，身份、版本和成本结论待验证：
  `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6795938`
- Binance USD-M change log：
  `https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/change-log`
- Man Group, trend-following implementation background：
  `https://www.man.com/insights/deep-dive-trend-following`

用户提供的其它论文链接先进入metadata queue，不在未验证标题、作者、版本和正文hash时写成已接受研究事实。

## 10. 当前不做

- 不把旧X4/RV-C/CTA-R结果改写成当前已认证edge；
- 不恢复legacy timer、cron、live开关或订单权限；
- 不为了多速度趋势做无界SMA/EMA网格；
- 不在point-in-time universe和退市合同缺失时扩到大量小币；
- 不把历史C×D、CTA-R、X4或RV-C读数直接写成当前认证edge、当前production allocator输入或live资格；
- 不以提高杠杆弥补alpha或实盘迁移证据不足；
- 不把组合目标Sharpe、低相关或跨资产广度当作预先承诺；它们只能是待验证假设；
- 不把公共API、单VPS和非共址环境投入低延迟做市竞争；小时级/事件级order-flow仍须另立低频合同；
- 不在当前no-carry约束下启动carry或VRP正式trial；
- 不让ML/LLM直接产生live方向、目标权重或杠杆；
- 不把文献中的Sharpe当作本项目可复制收益；
- 不因短期论文热点改变Base参数或跳过新时间证据。
