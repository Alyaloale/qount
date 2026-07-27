# qount 策略研究与情报推进路线

> **状态**：active｜**权威**：L3 研究路线｜**最后更新**：2026-07-26
> **本文回答**：全局实验账本、加密 family 图谱、来源矩阵、阶段门、§11 下一轮执行步骤。
> **TL;DR**：加密优先；每 family 3 trial 强制复盘、不救援；multi_speed/breadth/residual 已关闭，liquidity 已首轮 calibration，stablecoin 三源 no-PnL G0 已通过并只允许进入新的 market-state 预登记设计。

版本：`v0.12`

更新时间：`2026-07-26`

状态：owner已把主动研究方向切换为加密优先，授权本地research_sandbox、historical discovery、因子工程、数据工程和
virtual allocator并行推进。CTA-R与C×D既有证据冻结保留为次级旁路；该授权不构成promotion、paper、live、真实订单、
short、杠杆或生产配置变更授权。

v0.6修订只扩展研究设计。v0.7记录2026-07-25执行批次。**v0.8记录Track A/B/C 执行完成后的最终读数**：
- `multi_speed_trend_v1`：Trial 145/146/147 全REJECT，按"不救援"关闭（3/3）。
- Track A（WSL直连`data.binance.vision`下载全10币UM 1d klines+funding，751 OK/29 fail=上市前月份；`fapi`不可达，
  rules从kline推断10/10 present、coverage=1.0）：**10币breadth有效广度`1.6602`<2.0 → `block_capacity`**；
  liquidity `pass_to_capacity_calibration`。
- Track B `crypto_vol_crisis_state_v1` Trial 148：5/6门，唯一失败`tail_residual_improvement`，
  verdict=`reject_crisis_state_mechanism_not_sufficient`（1/3）。
- Track C：`stablecoin_liquidity_impulse_v1` source-capacity `pass_to_g0`。前向4 schema `continue_collection`。

**v0.11补记 stablecoin remediation + G0 重跑**：collection `v0.2/20260725T171019Z` 已补齐三源 exact confirmation、
USDC 4 段 implementation/proxy timeline 与 USDT TRON 两段 owner history；42 个成员和 9 个 gzip 全量核验通过。修正 TRON
zero-address 常量后的 r2 得到共同周样本 `376/376`、aggregate comparison `209/209`，marginal flow 仍不等价 aggregate
supply（Spearman `0.6479546769`、R² `0.4186931641`、offsetting ratio `1.0`）；同交易 native/zero Transfer 语义重复
正确识别 `318` 条，treasury 计数从错误的 `698` 更正为 `380`。但 USDT Ethereum owner round-trip absence 未证明，且
USDT TRON 的 991 条零金额 Transfer 与 G0 正金额事件合同造成 finality=`2,007 vs 1,016`、treasury=`383 vs 380`
count mismatch；分类覆盖=`0.9998899777`，verdict 仍为 `block_capacity`。这不是策略 trial、PnL 或机制拒绝，formal
trial=`148`、family trial=`0`。r2 bundle=`2c1ed8cd...ecb6e`；含错误常量的 r1 保留但不作为当前读数。

**v0.12完成 stablecoin v0.3 确定性补证与 no-PnL G0**：新 collection `v0.3/20260726T101608Z`（manifest=
`859a4904...458f`）以完整块/receipt、Sourcify ABI/verified source 和 multisig `transactionCount()/transactions(id)` 全枚举
闭合 USDT Ethereum owner history；`111` blocks、`11,199` transactions、`5,544` multisig slots，执行的
`transferOwnership=0`。链上 runtime 在 activation/observed 全字节一致，Sourcify `runtimeMatch=match` 只容许并明确记录
CBOR metadata 差异，可执行 bytecode SHA 一致。TRON 991 条零值 Transfer 保留 lineage/finality、排除 economic flow/count；
三源 semantics/finality 均 complete。冻结 G0 v0.2 的 8 个 kill test 全 false，coverage=`1.0`、unknown=`0`、
`376/376` 周锚点、`209/209` aggregate anchors，verdict=`pass_to_market_state_design`，bundle=`e725e66a...95b7`。
仍未读市场/PnL，formal trial=`148`、family trial=`0`，不授予 promotion/paper/live/order 权限；v0.2/r2 不覆盖。

所有读数`orders_authorized=false`、`data_role=consumed_historical_discovery_pool`，未触碰生产/paper/live。formal trial累计`148`。

**本轮最关键结论**：R0-DATA已闭合（10币全下载），横截面容量问题从"数据缺失"变成**真实容量限制**——10币相关有效广度
`1.6602`（3币`1.225`/7币`1.474`/10币`1.660`；特征值广度`2.511`>2.0但相关广度不足；PC1`0.615`<0.85通过）。这与
LiquidTrend10`1.438`同方向。按规则**不放宽广度门、不扩币救援**：`market_breadth_dispersion_v1`与传递依赖它的
`cross_sectional_residual_momentum_v1`关闭；`liquidity_capacity_meta_v1`作为eligibility/cost基础设施继续。
Trial 148也确认危机状态降险机制在尾部不够有效（呼应147低效降险）。下一轮在**已通过G0的线**上推进：
liquidity真实盘口校准、stablecoin market-state 新预登记、carry active-basis 与前向采集器启动决策。详见文末
"下一轮执行步骤"。

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
- 当前部署约束只约束可部署候选和真实账户行为；本地research/discovery可检验超出部署约束的假设并如实标记，不需等待阶段或样本门。

## 1. 对三组建议的研究分流

| 建议 | 路线处理 |
| --- | --- |
| 多速度趋势 | 作为新的有限trial hypothesis family，Base继续作为冻结控制组，不做SMA参数无限扫描 |
| point-in-time流动性宇宙 | P0数据基础；先审计退市、规则、成交额、盘口、OI、funding和缺失，再看PnL |
| 横截面动量 | 可立即做数据、synthetic和discovery研究；新宇宙G0决定结果能否升级为候选证据 |
| 波动率/危机状态层 | 可研究，但必须引入与既有失败price-only缩放不同的信息或目标 |
| ML meta-labeling | 仅用于波动、成本、成交和异常等元任务；不直接生成live权重 |
| carry/basis | CxD/RV-C可立即做historical/discovery/shadow/virtual研究；真实多腿订单仍需独立授权 |
| VRP/期权 | 可继续本地数据和虚拟研究；当前options surface缺口降低结论强度，不能被写成可交易或卖波动资格 |
| 跨资产CTA-R | Round 7重认证证据保留；当前冻结为次级旁路，未来只按既有PIT/成本/压力清单复核，不继承promotion资格 |
| C×D趋势+carry | 冻结为次级组合数学旁路；carry/no-carry、双腿执行、尾部和场所权限仍是硬门，不直接进入paper/live |
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
  "decision": "planned|active_research|retain|reject|blocked",
  "contamination_notes": []
}
```

规则：

- 每个`hypothesis_family`第3个冻结正式trial是复盘里程碑，不是上限；后续trial继续编号，探索诊断也登记，不能通过改名逃避计数；
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

实现状态（2026-07-24 审计；初步工程已完成，候选结论重新打开）：

- `src/qount/governance/research_records.py` 已新增 `GlobalExperimentRecord`、`HistoricalFamilyMapping`、
  `PointInTimeSymbolLifecycle`、`PointInTimeUniverseRevision`、`UnifiedNavScorecard`、`ResearchEvidenceReadinessRecord` 和
  `CandidateRevalidationRecord` 的 hash/validation 合同；
- point-in-time universe builder 只按 `valid_from <= as_of < valid_to` 选择当时 active symbol，不用未来上市或已退市状态反填；
- 统一 scorecard 同时保存 Signal NAV、Standalone Executable NAV、Portfolio Realized NAV、beta residual、成本、trial count
  和 fold metrics；它是报告合同，不是 allocator 或 promotion；
- `scripts/research/run_multi_sleeve_virtual_runtime.py`已生成固定两sleeve标准链artifact，result=`a98977dd...1672f`；它验证
  allocator/Risk/OrderPlan/virtual ledger/fees/funding/三NAV/reconciliation，不是候选表现；
- `scripts/research/build_r0_records.py`现读取并验证上述artifact，生成8份readiness、1份GlobalExperimentRecord和两个v4候选。
  CxD实际映射到`x4_s7_trend_portfolio/rv_c_basis_carry/x4_cxd_combo_v1_9`，CTA-R映射到
  `l1_cross_asset_v1/cta_r_selection_free_a_share_etf`；来源文件均绑定SHA-256，不继承旧promotion结论。
- **R0-DATA**：✅ 已实现 `lifecycle.py` / `availability.py` / `universe.py`，并记录外置盘 bundle
  `b9fa27ec6938e0dd7dc4fd880ebce4e517f685058a3e7504565362417e2d2422`（报告 UM 846 symbols、27 季度 revisions）。⚠ 当前
  `exchangeInfo` 与 onboard date 不是完整历史状态链；delisting、状态变化、spot listing 和 availability 必须以历史 source snapshot
  重建后，才能声称 historical point-in-time universe 已闭合。
- **R0-COST/NAV**：✅ 已实现 4 种 `FrozenCostModel` 与三 NAV 计算器，相关标准库单测 `110/110 OK`。⚠ carry 现金流把空头收到的
  正 funding 记成成本，冻结模型与测试要先改为显式 signed funding cash flow，才能生成可解释的 carry Standalone NAV。
- **R0-RUNTIME**：✅ BTC 初步 runtime bundle
  `b90c6d1569d2fcc099f39af1252a128e610c96146b2a22d828bf87d13469592f`（2395 UM bars / 2393 spot bars / 7119 funding，7 members）
  已通过本机 manifest/member hash 校验。⚠ 它的 carry 读数受 funding 符号影响，且 summary 使用全样本 peak 计算 max drawdown；初步
  `10.62x / 8.57x / 0.99x / 0.76x` 和全部回撤读数均只能作为待重跑诊断。
- **R0-RECORD**：✅ v5 bundle
  `47aa0e88c70d3d2dabe3dad2422b875b4f7e16c5c7de2d6247dfe9f5d7089af7`（11 members）已通过本机 manifest/member hash 校验，
  `orders_authorized=false` / `promotion_evidence=false`。⚠ `candidate_pnl_ready=true` 只代表 C×D 初步记录；CTA-R record 仍为
  `candidate_pnl_ready=false` / `active_research`，不具备 runtime NAV、PIT lifecycle 或可执行成本证据。
- **R0-DECISION 与三线推进**：✅ 初步 decision bundle
  `d382f8e931d7a3cb9a4de99ee86cfdd4542a254ba3cd4528965683caaf0f6322` 和 advancement 脚本已经生成。⚠ decision 脚本重新读取缓存、
  未消费 runtime bundle；advancement 脚本不产出 artifact。故趋势的 `RETAIN`、静态 carry 的 `REJECT`、CTA-R 的 `BLOCKED`，以及
  `+18.66%/yr`、`-90% -> -10%`、`1.46x / +6.15%` 全部是 preliminary discovery output，不是冻结、可复核结论。
- **Carry 新假设已提出**：`docs/carry-active-basis-hypothesis.md` Active Basis-Capture State Machine，不复活旧版本。

### R0.0：当前可执行研究路线

以下是从当前 research-ready 状态到真实 candidate 复核的工作顺序。顺序用于减少返工，不是日历硬门；Base 自然首单由生产 timer
独立等待，不阻塞任何研究步骤。

1. **R0-DATA：建立 point-in-time 数据真相。** ✅ 已完成初始 lifecycle / availability / revision 实现和 bundle 生成；⚠ 未完成历史
   source snapshot、delisting/status/spot-listing 审计，暂不把 846-symbol / 27-revision 读数称为完整 PIT truth。
2. **R0-COST/NAV：冻结当前可执行成本与三 NAV。** ✅ 已完成成本合同和 110 个单测；⚠ 先修正 carry short funding 的 signed cash flow，
   再重算 Standalone NAV，并将 `estimated` 成本与 `certified_sample` / `official_rate` 分开报告。
3. **R0-RECORD：回填全局实验与候选记录。** ✅ 已完成 v5 records 与 immutable bundle；⚠ 将全局 `candidate_pnl_ready` 拆成每候选字段，
   并在重跑后写新 revision，旧 v5 保留为已消费 discovery evidence。
4. **R0-RUNTIME：用真实 candidate intent 重跑标准 virtual runtime。** ✅ BTC 单腿初步 runtime 已运行；⚠ 公共 rolling-drawdown、
   因果 vol-target 和 signed funding 修复后，需用已验证输入 bundle 重跑 BTC/ETH/BNB，并为 CTA-R 写独立 runtime artifact。
5. **R0-DECISION：分别作 retain/revise/reject 结论。** ✅ 已生成初步 decision 输出；⚠ 改为显式消费已验证 runtime bundle、记录
   code/config/source hash、holdout role 和压力结果。重跑前不保留任何 `RETAIN` / `REJECT` / `BLOCKED` 作为策略结论。

并行旁路：Base live timer保存首个自然 `decision -> submit -> ACK -> trades/fee -> protection -> ledger/reconciliation -> attribution`
样本；Phase B readonly timer继续累计有效/失败批次。两者用于更新执行成本和语义置信度，不是R0-DATA/R0-COST的启动条件。

### R0.0-A：审计修复与可复核重跑，P0 -- ✅ 完成

1. ✅ **signed funding 已修复**：`research_data/nav.py:151` 以 `position * funding_rate * multiplier` 替代 `abs(position) * ...`；
   补充 4 条回归测试。修复逻辑正确。
2. ✅ **rolling drawdown 已修复**：新增 `compute_max_drawdown()` 使用逐期 high-watermark；补充 7 条回归测试。修复逻辑正确。
3. ✅ **P0.5 funding 结算聚合已修复**：`align_funding_to_bars` 每日只选一条最近费率 -> 新增 `aggregate_funding_to_bars()` 按持有区间
   `[bar_t, bar_t+1)` 求和全部 8h settlement；7,119 次原始结算现全部累计（旧逻辑仅 ~1/3）。0 笔结算且此前有数据 -> `incomplete=True`；
   `nav.py` 新增 `funding_incomplete` 参数；runtime manifest 新增 `funding_raw_hash`/`settlement_counts`/`missing_intervals`。
   新增 11 条测试覆盖聚合与完整性传播。**在完整 funding 窗口（2020-01 至 2026-06）重跑后 candidate_pnl_ready=true，cost_incomplete=false。**
4. ✅ **P1 provenance 已修复**：decision 新增 `--runtime-bundle` hash 验证（closes/funding/baseline NAV 三项匹配，fail-closed）；
   advancement 新增 manifest-last artifact（绑定 source/config hash、universe、holdout_role=discovery_pool）。
5. ✅ **vol-target 窗口契约已修复**：`range(lookback, len)` -> `range(lookback+1, len)`，明确"20 个 completed returns"语义。
6. ⚠ **R0-DATA 审计未做**：需在 WSL/外置盘对 `b9fa...` 执行只读 manifest、member hash 和 source snapshot 审计；为 CTA-R 建立
   ETF lifecycle、时区、交易日、税费/FX、PIT universe 与 cost artifact。
7. ✅ **完整 provenance 下重跑已完成**：在 2020-01 至 2026-06 完整 funding 窗口上重跑了 R0-RUNTIME / R0-DECISION / R0-ADVANCEMENT。

**Round 1-4 修正后结果（2020-01 至 2026-06 完整 funding 窗口）**：
- **R0-RUNTIME** `7e827743...`（7 members）：趋势腿 Signal 8.46x / Standalone **4.48x**（maxDD -50.0%，cost 0.6369，cost_incomplete=False）；
  carry 腿 Signal **1.00x** / Standalone **1.38x**（cost -0.3849，cost_incomplete=**True**）；**candidate_pnl_ready=False**（carry cost_incomplete=True）。
  `config_hash=b23257abd7e7...`，`regime_sma=0`（统一 CandidateConfig）。
- **R0-DECISION** `a26fba9a...`（5 members）：runtime_bundle_verified=**True**（含 carry_nav_match）；
  趋势腿 **REVISE**（kt1 PASS, kt2 PASS 独立对账, kt3 FAIL R0-DATA 不可用）；
  carry 腿 **REVISE**（同上）；CTA-R **BLOCKED**。
- **R0-ADVANCEMENT** `443a4ebb...`（6 members）：BTC beta-residual **alpha=+7.75%/yr, beta=0.47, R²=0.47**；
  3 币等权 NAV **13.40x** maxDD **-58.07%**（common_dates=2333, 2020-02-10 起，日期对齐）；
  CTA-R 等权 NAV **1.56x** maxDD -10.28% 年化 +7.26%（首次在 artifact 中）。source_hashes 含 crypto per-symbol。
- **旧 bundle 处置**：`acb1a8c1...`/`6a4e8f1a...`（旧 runtime）/`1221bf3f...`（旧 advancement，regime=200）/`44bcf024...`（旧 decision）保留为已消费 discovery artifact。
  v5 governance bundle `47aa0e88...` 保留（仍指向旧 `b90c6d...`）。v6 governance bundle `28035b7e...` 已生成（`candidate_pnl_ready=False`，`supersedes=47aa0e88...`）。
- **回归测试**：R0 标准库 200/200 OK（含 27 candidate_config + 16 kill_tests + 7 alignment + 150 原有）。
- **Round 6 深度验证** (`2ff84b3f...`)：chronological folds **partial**（2020-2021 NAV=2.96x, 2022-2023 NAV=1.41x, 2024-2026 NAV=**0.78x** -9.4% 年化）；cost sensitivity all_positive（funding 主导，执行成本 <4%）；beta residual **partial**（11/23 窗口 alpha 为正，集中牛市）；new-data 22 bars in 2026-07。**验证结论**：趋势正 NAV 集中在 2020-2021 牛市，近期亏损，alpha 不稳定。

### R0.1：跨资产候选冻结旁路，P3

当前研究不把“工程能力强”当作收益证据，也不把单一加密市场的币数当作edge breadth。LiquidTrend10的有效广度`1.438`
是当前容量先验，足以阻止无边界扩币；它不是不经新数据就能外推到所有市场的数学定理。2026-07-25 owner把主动预算
切换到加密因子拓展后，以下两条线保留证据和缺口清单，但不再与加密P0争抢当前执行顺序：

1. **C×D重新认证**：把历史趋势+carry组合只作为组合构造假设，重新建立当前版本的两份Standalone NAV、共同因子/crypto beta、
   basis tail、双腿成本、场所集中和独立新时间证据。carry已可做historical discovery、observation、shadow attribution和
   virtual allocator；不能因为历史负相关或目标Sharpe直接paper/live。
2. **CTA-R跨资产重新认证**：未来复核selection-free ensemble、walk-forward OOS、可交易ETF/期货通道、真实费用、时区、税费和
   账户约束；跨资产广度若能稳定通过，不代表它自动成为当前Binance钱包的sleeve。期货券商、海外券商或新场所都需要独立
   venue/data/owner合同，不能把ETF研究读数当作已认证期货edge。

这两条路线的历史目标仍是验证“跨资产广度 × 多个低相关薄edge”的组合假设，而不是预先承诺Sharpe `1.0-1.3`或任何年化收益。
只有owner重新提高优先级时才继续主动运行；组合收益、风险贡献和尾部仍须先由统一allocator的virtual NAV重建。

每个候选必须先生成`CandidateRevalidationRecord`，再运行任何组合PnL：

```text
candidate_id / hypothesis_family / historical_evidence_ids
current_data_ids / untouched_data_ids / venue_and_account_scope
baseline_ids / frozen_cost_model / execution_contract
standalone_nav_artifacts / factor_and_beta_plan / tail_scenarios
primary_metric / kill_tests / trial_budget / owner_authorization_state
decision = planned | active_research | retain | reject | blocked
```

### R0.2：两个候选的证据清单

以下项目决定候选能否形成更强结论或进入production review，不阻止本地实验并行运行。

**C×D趋势+carry**需要报告：

1. 趋势腿和carry腿分别重建当前版本的Standalone Executable NAV，使用独立数据水位和成本模型；
2. 对两腿及组合分别报告crypto beta、market/momentum/carry暴露、basis tail、legging、资金占用和场所集中；
3. 在新时间或未消费窗口上完成价格连续、funding/contract完整和双腿可执行性审计；
4. virtual allocator可先用零/单腿/synthetic fixture验证架构；只有两腿证据齐全后才能把结果解释为C×D候选组合表现。

任一腿的after-tail净收益非正、required maker fill超过1、独立NAV无法对账或新时间证据缺失，应将该版本标为
`blocked|reject|insufficient_evidence`并降低结论强度；允许提出有实质变化的新实验，不能通过调组合权重伪造原版本通过。

**CTA-R跨资产趋势**需要报告：

1. 固定selection-free ensemble或预登记walk-forward，不以历史最优lookback作为唯一结果；
2. 保存point-in-time ETF/期货标的、上市/退市、跟踪误差、时区、费用、税费和容量；
3. 报告有效广度、单资产/类别贡献、债券/黄金/海外股regime集中和真实可交易通道；
4. 先进入cross-asset virtual sleeve，再讨论新的venue或期货授权，不能把杠杆带来的名义收益写成alpha。

若selection-free、当前成本或可交易通道任一硬门失败，保留方法记录但停止组合晋级；不为达到目标Sharpe增加资产、杠杆或
lookback网格。

### R0.3：CTA-R selection-free 冻结成本重认证，P3 -- frozen discovery retain

2026-07-24已完成当前版本的第一份独立CTA-R不可变重认证bundle
`9c08be9cdeb1a0c3d9416af9a4f7cb41eda4a17792decad24d5cee72b8725be1`。它纠正了R0 advancement把单一
`20/100`规则套在10只ETF后称作CTA-R的口径，恢复固定8 ETF、`63/126/252`多周期、selection-free ensemble、past-only
walk-forward和fixed先验三条读数；全部long-only、effective gross `<=1`、不下单。

- 输入：当前ETF压缩源共同窗口`2014-01-15..2026-07-22`、3037行，dataset=`2d6e7459...f7c8`，
  `data_role=consumed_historical_discovery_pool`；当前archive不能证明历史PIT membership。
- 冻结成本：A股ETF账户10bps/边。ensemble Sharpe/CAGR/maxDD=`0.9197/8.65%/-8.23%`；past-only walk-forward=
  `0.7403/7.70%/-8.69%`、5/5折正；fixed=`0.8568/9.12%/-9.55%`、5/5折正。
- 双倍成本20bps/边：walk-forward=`0.6984/7.22%/-8.73%`、4/5折正；selection-free结论仍通过。
- 固定完整runtime：effective breadth=`3.0844`、平均gross=`0.9904`，独立NAV对账通过。
- 结论：`retain_for_discovery_revalidation`，不是promotion。candidate record v7仍为`active_research`，
  `candidate_pnl_ready=false/promotion_evidence=false/orders_allowed=false`。

未来恢复该线时不再搜索lookback、资产或杠杆，只按以下冻结顺序推进：

1. **PIT与可交易性**：重建8 ETF上市/暂停/退市、复权vintage、交易日和公司行动；对QDII保存历史溢折价、限购/停牌和跟踪误差。
2. **成本认证**：把佣金、最低收费、spread、slippage从estimated升级为owner账户适用的official/certified evidence；保留10/20bps压力。
3. **固定压力**：只跑预登记的一根额外延迟、漏单、QDII premium shock、金债反转/whipsaw和类别贡献，不扩大参数网格。
4. **新时间**：冻结当前三条selection-free合同，建立point-in-time forward journal；至少覆盖多个21交易日再平衡周期后，才评估
   promotion review价值。任何paper、券商接入或真实订单都需新的owner授权。

Round 7曾使CTA-R成为最高优先候选；2026-07-25 owner随后用加密优先指令取代该排序。CTA-R证据不作废，但冻结为次级旁路；
C×D同样暂停主动扩展。加密线也不得复活旧单点均线、扩币或杠杆救援，只推进下述相互独立的新因子族。

### R1：多速度趋势族，P0

研究问题：固定的fast/medium/slow趋势forecast组合，能否降低Base单一参数点依赖，并在扣除真实规则和成本后改善残差风险收益？

统一表达为：

```text
Forecast[i,t] = clip(w_fast * F_fast[i,t]
                   + w_medium * F_medium[i,t]
                   + w_slow * F_slow[i,t])
```

fast负责事件后的快速降险，medium承担主要持仓，slow表达长期牛熊状态。`F`可以来自breakout、EMA或标准化收益动量，
但尺度、标准化、裁剪和`w_fast/w_medium/w_slow`必须在读取候选结果前冻结；连续forecast不得被事后阈值化成新的参数搜索。

首个family先运行三个冻结正式trial并在此处强制复盘，后续trial不被代码禁止：

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

#### Trial 145：方向一致性基线，已拒绝

预登记protocol=`304bc24da6bf4c471d2a98f6edd8b767a62cc719f1e1796f072483d77ed14ec7`，固定20/60/120日
总收益全票为正、120日BTC或2/3 breadth慢门，其余风险与执行合同复用Base v0.2。共同数据`2020-02-10..2026-06-30`
共2333行，warmup后2132个持有区间；462个本地源包入inventory，三币均无零funding结算区间。

- Base同窗Standalone proxy NAV/CAGR/Sharpe/maxDD=`2.8836x/19.88%/1.416/16.18%`；候选=
  `2.7966x/19.25%/1.399/11.20%`。
- 候选把回撤降低`4.98pp`，TOP3 beta-residual CAGR=`10.91%`，在2020-21与2024-26跑赢Base；但2022-23
  CAGR仅`6.64%`，比Base低`9.97pp`，全窗主指标也低`0.63pp`。
- 双倍交易成本和额外一根信号延迟后的CAGR分别为`16.62%/16.31%`；turnover=`108.91`，约为Base
  `50.56`的2.15倍。8/9门通过仍严格拒绝，不调整lookback、投票数或慢门救援。
- bundle=`d4ca0c3eaa82e15674a1d83bf803aa7078f730d00856670451767577b1d50cb8`；结论只否定
  `multi_speed_direction_consistency_v1`。Trial 146继续固定连续forecast，Trial 147才测试分层状态机。

#### Trial 146：固定连续forecast等权组合，已拒绝

固定连续z-score forecast（20/60/120日标准化收益等权，尺度/裁剪冻结），其余合同复用Base v0.2。

- 结果：**6/9门通过，REJECT**。候选CAGR `13.06%` vs Base `19.88%`（低`6.82pp`，主指标失败）；maxDD `21.51%` vs
  Base `16.18%`（恶化`5.33pp`，`maximum_drawdown_worsening_within_2pp`门失败）。
- 连续forecast把仓位摊平后既没跑赢也没降险，是三试里最差的一个；按规则拒绝，不事后阈值化把连续值改成新参数搜索。

#### Trial 147：分层状态机（slow regime + medium position + fast de-risk），已拒绝；触发family复盘

预登记protocol=`37331edceb8c6f454f6a79b1a6b59ae2b16efbb313020ccca3f7f2e00c3809d0`；
bundle=`2e17c4fd3d8761c5aaa786fc7d63c86c03ad56b5d14a8792eb2fcdfe769f05f6`，
`decision=reject`，`verdict=reject_state_machine_family_review_required`。

- 结果：**7/9门通过，REJECT**。失败两门：`candidate_standalone_cagr_above_base`（候选`15.90%` < Base`19.88%`）与
  `candidate_outperforms_base_in_at_least_2_segments`（只有2024-2026一段跑赢`+3.95pp`，2020-21输`12.9pp`、2022-23输`8.9pp`）。
- maxDD `9.70%` vs Base `16.18%`（改善`6.48pp`，三试最优）；双成本CAGR `+14.05%`、延迟CAGR `+14.18%`、
  top3 beta-residual `+7.98%` 均正。
- **降险insight需打折**：候选turnover `70.04` vs Base `50.56`（多交易38%），且Sharpe `1.291` < Base `1.416`——
  回撤降低是敞口下降的副产品，风险调整后反而更差；应记为"低效降险"，不是可直接提炼的crisis-state edge。

#### `multi_speed_trend_v1` family 复盘与关闭

| Trial | 机制 | Gates | CAGR | maxDD | Sharpe | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| 145 | 方向一致性投票 | 8/9 | 19.25% | 11.20% | 1.399 | reject |
| 146 | 连续z-score等权 | 6/9 | 13.06% | 21.51% | – | reject |
| 147 | 分层状态机 | 7/9 | 15.90% | 9.70% | 1.291 | reject（触发复盘）|
| Base | – | – | 19.88% | 16.18% | 1.416 | 控制组 |

三个trial主指标（CAGR > Base）全部失败。按"不救援"规则关闭family：不调lookback、投票数、慢门或组合权重救援，
不把相邻SMA/EMA拆成新family。保留的方法教训：快层de-risk能降回撤但以Sharpe↓和turnover↑为代价（低效降险），
供未来`crypto_vol_crisis_state_v1`设计时作为需要区别的旧证据，而非可直接复用的信号。

#### G0 执行结果（2026-07-25 批次）

| Family | G0 verdict | 根因 | 处置 |
| --- | --- | --- | --- |
初次G0（3币缓存）：两者均`block_capacity`，根因是宇宙只有TOP3。Track A 补齐10币后**最终G0**：

| Family | 最终G0 verdict | 关键读数 | 处置 |
| --- | --- | --- | --- |
| `market_breadth_dispersion_v1` | `block_capacity`（真实容量）| 10币相关有效广度`1.6602`<2.0（3币`1.225`/7币`1.474`）；特征值广度`2.511`>2.0但相关广度不足；PC1`0.615`<0.85通过；分段2020-21`1.890`/2022-23`1.409`/2024-26`1.397` | **关闭**：与LiquidTrend10`1.438`同方向的真实容量限制，不放宽广度门、不扩币救援 |
| `cross_sectional_residual_momentum_v1` | 传递阻断 | 依赖广度≥2.0 | **关闭**（随breadth关闭）|
| `liquidity_capacity_meta_v1` | `pass_to_capacity_calibration` | rules覆盖`1.0`、10币中位成交额213M–12.5B USDT、Amihud通过 | **通过**：作为universe eligibility/cost基础设施继续 |

Track A 已把横截面问题从"数据缺失"证成"真实容量限制"：R0-DATA闭合（10币全下载：WSL直连`data.binance.vision`，
751 OK/29 fail=上市前月份；`fapi`不可达，rules从kline推断10/10 present）。breadth及依赖它的residual momentum关闭，
不再重开；liquidity通过进capacity calibration。

#### 前向衍生品 append-only schema（Wave 3，已冻结）

4个family（`oi_flow_forward_v1`、`basis_curve_dislocation_v1`、`liquidation_cascade_forward_v1`、
`cross_venue_price_discovery_v1`）已冻结raw source/clock/dedup/gap/独立窗口合同，`read_results_before_window=false`，
全部`continue_collection`。官方历史限制：OI 1月、basis 30天、liquidation无官方归档、cross-venue需多场所同步。
未达预登记独立窗口前不读结果；容量不足继续采集但不宣称0 alpha。

#### 外部PIT source-capacity（Wave 4，已审计）

选中`stablecoin_liquidity_impulse_v1`（链上铸造/赎回事件PIT可重建）。阻断：`network_adoption_quality_v1`
（provider vintage修订）、`venue_rule_event_v1`（exchangeInfo仅当前快照）、`token_supply_event_v1`（P2名额已用于
stablecoin）。选择标准冻结为`pit_vintage_availability_first`。下一步是为选中family建实际source-capacity artifact，
未建成前不进入正式trial。

### R1.1：加密因子研究组合总图

当前按“一个family一个经济机制”组织，任何family到第3个正式trial强制复盘。G0数据/容量失败可以在读取PnL前阻断trial；
同一失败合同不能通过改名、扩币、替换模型或阈值扫描重启。family优先级表示研究顺序，不表示预期收益高低：

| 层级 | 研究目的 | Family |
| --- | --- | --- |
| P0 核心 | 用现有低频数据尽快做最便宜、最可证伪的测试 | `multi_speed_trend_v1`、`market_breadth_dispersion_v1`、`liquidity_capacity_meta_v1` |
| P1 独立机制 | 在不恢复旧参数救援的前提下寻找第二收益/风险来源 | `cross_sectional_residual_momentum_v1`、`crypto_vol_crisis_state_v1`、`funding_crowding_meta_v1` |
| P1 前向结构 | 官方历史短，必须从当前起append-only积累 | `oi_flow_forward_v1`、`basis_curve_dislocation_v1`、`liquidation_cascade_forward_v1`、`cross_venue_price_discovery_v1` |
| P2 外部PIT | 先证明历史vintage、事件时点和许可，再允许结果解释 | `stablecoin_liquidity_impulse_v1`、`token_supply_event_v1`、`network_adoption_quality_v1`、`venue_rule_event_v1` |
| P2 低预算异常 | 容易多重检验，只允许少量预登记问题 | `calendar_session_v1`、`execution_fill_cost_v1` |
| P3 容量/组合 | 数据、账户或独立sleeve不足时不争抢主动预算 | `options_surface_state_v1`、`regime_allocator_meta_v1` |

每个ResearchProposal必须在结果前写满以下卡片，缺一项不得进入正式trial：

```text
family / mechanism / causal direction
decision clock / outcome horizon / independence unit
required raw sources / PIT and revision policy / history limit
features / missing-data rule / eligibility rule
baseline / control / primary metric / secondary metrics
cost model / beta-residual plan / stress plan
kill tests / allowed sensitivities / trial budget
overlap with local negative evidence / promotion blockers
```

#### A. 趋势、横截面和危机状态

| Family | 经济机制与首批因子 | 数据时钟与首个测试 | 基线、主指标与Kill test | 预算/状态 |
| --- | --- | --- | --- | --- |
| `multi_speed_trend_v1` | 趋势在不同形成/衰减速度上持续；标准化20/60/120日收益、breakout距离、快慢背离 | TOP3完成日线；连续forecast，然后`slow regime + medium position + fast de-risk` | Base v0.2；相对Base Standalone CAGR受maxDD约束；不超过Base、回撤恶化>2pp、2/3分段失败或成本/延迟失败即拒绝 | 3/3已用；**CLOSED**；P0 |
| `market_breadth_dispersion_v1` | 趋势扩散、横截面分散和相关性压缩可区分健康行情与单币beta推动 | PIT流动池日线；上涨占比、距中期趋势分布、残差dispersion、第一主成分解释率、相关簇同步度；先只输出state | TOP3 breadth和BTC趋势；主指标为对下一持有期残差收益/尾部的增量；若等价于BTC收益、breadth<2或只在单一年份有效则拒绝 | **CLOSED**（10币广度1.660<2.0）；P0 |
| `cross_sectional_residual_momentum_v1` | 个币相对强弱在扣除共同market/TOP3/相关簇暴露后仍可能持续 | PIT月/周revision；1/2/4/12周past-only残差动量，long/cash流动性约束排名 | 原始相对动量、BTC/TOP3和LiquidTrend10；主指标为净TOP3-beta residual CAGR及有效广度；PIT/rules不全、breadth<2、残差非正或单币/单阶段集中即拒绝 | **CLOSED**（随breadth传递关闭）；P1 |
| `crypto_vol_crisis_state_v1` | 高波动、下行半方差、range扩张和相关性跃升会降低趋势的单位风险回报 | TOP3日线/可验证衍生品状态；只输出`RiskMultiplier [0,1]`，先比较固定vol scaling和非对称de-risk | Base、multi-speed、简单vol target；主指标为`drawdown saved / return sacrificed`和尾部残差；少赚超过预算、尾部无改善或只拟合单次崩盘即拒绝 | 1/3已用；Trial 148 REJECT（尾残差恶化）；P1 |

#### B. 衍生品、拥挤和强平状态

| Family | 经济机制与首批因子 | 数据时钟与首个测试 | 基线、主指标与Kill test | 预算/状态 |
| --- | --- | --- | --- | --- |
| `funding_crowding_meta_v1` | 极端funding是杠杆需求、拥挤和持仓成本共同状态，不等同于可得carry | 完成结算as-of日线；横截面分散、持续时间、price/funding背离、funding变化而非单一水平；条件化趋势风险 | 旧50% TOP3 Funding Veto、无funding趋势；主指标为残差收益/回撤/换手增量；等价旧veto、事件不足或完整状态路径吞噬增量即拒绝 | 3；P1 |
| `basis_curve_dislocation_v1` | perp premium、dated-future basis和曲线斜率反映杠杆需求、套利资本约束及崩盘风险 | premium-index、funding与dated basis；先做前向日线/4h state，不做现金carry | funding-only和price-only state；主指标为对未来尾部或趋势失效的增量；若30日历史容量不足、与funding高度重复或扣延迟后失效则阻断/拒绝 | 2；P1前向 |
| `oi_flow_forward_v1` | OI变化与主动买卖流组合可区分新风险建立、平仓和挤压，而单独OI方向含义不稳定 | 当前起append-only 5m/1h聚合到4h/1d；`price x OI x taker imbalance x funding`状态，不回填长历史 | 常数、价格、简单趋势、单变量OI/taker；主指标为future-only rank IC和残差/风险增量；时点、覆盖不足或baseline不败即拒绝 | 2；仅前向 |
| `liquidation_cascade_forward_v1` | 强平流在流动性变薄时可能形成短暂价格冲击、相关性同步和后续风险持续 | 官方实时liquidation stream + OI/depth/price；按事件强度/OI、方向、集中度和恢复速度聚合，首测为de-risk/entry veto而非抄底 | 同幅度price shock和vol spike；主指标为尾部损失避免与误杀成本；重复事件、clock gap、观察延迟后无增量或只支持已拒绝capitulation rebound即拒绝 | 2；仅前向 |

#### C. 流动性、场所与事件结构

| Family | 经济机制与首批因子 | 数据时钟与首个测试 | 基线、主指标与Kill test | 预算/状态 |
| --- | --- | --- | --- | --- |
| `liquidity_capacity_meta_v1` | 流动性决定可纳入宇宙、成本和容量，未必直接预测方向 | 决策前volume/quote turnover、Amihud、Corwin-Schultz、book spread/depth、规则与缺失；先校准eligibility/cost | 仅volume过滤和静态成本；主指标为PIT可交易覆盖、容量和成本误差；rules<100%、PIT不可重建、容量不足或误差大于edge即阻断 | **calibration首轮完成**（robust容量≈21.3M USDT；CS价差代理全高估→待WSL盘口）；P0 |
| `cross_venue_price_discovery_v1` | 场所分割、客户结构和套利资本约束可造成可预测的低频lead-lag，但名义价差不等于可交易套利 | 多场所同步trade/quote、mark/index、fee和可转移性；5m/1h聚合后预测laggard残差，不做低延迟抢单 | 单场所动量、共同market move和零成本价差；主指标为扣双边成本/延迟后的残差收益；时钟skew、venue outage、transfer/borrow/fee后非正即拒绝 | 2；P1前向/外部数据 |
| `venue_rule_event_v1` | listing/delisting、filter、funding interval、合约状态和交易时段变化会改变流动性、容量和价格发现 | 官方公告published/available time + exchangeInfo快照revision；先做eligibility和event study | 同类非事件标的和市场残差；主指标为事件后流动性/成本变化，不先追公告动量；时点不可证、事件聚类过少或依赖幸存者样本即阻断 | 2；P2 |
| `calendar_session_v1` | 24/7市场仍受周末、UTC结算、欧美/亚洲交易时段、月季末和传统市场开闭影响 | 1h/4h完成bar；只允许预登记2个时区/结算问题，按独立日或周聚类 | 全时段、相邻时段和BTC beta；主指标为扣成本后的独立日期均值；多重检验、DST/节假日错配或单一事件主导即拒绝 | 2；P2低预算 |
| `execution_fill_cost_v1` | maker折扣只有在成交概率、等待成本和逆向选择后仍有净价值时才改善可执行收益 | bookTicker/depth、order lifecycle、真实或fixture fill；先预测fill/cost，不预测方向 | 固定taker和理论maker；主指标为realized implementation shortfall和required fill rate；required fill>1、尾部后净值非正或取消/重挂吞噬收益即拒绝 | 3；P2执行线 |

#### D. 资金供给、代币供给和网络状态

| Family | 经济机制与首批因子 | 数据时钟与首个测试 | 基线、主指标与Kill test | 预算/状态 |
| --- | --- | --- | --- | --- |
| `stablecoin_liquidity_impulse_v1` | 铸造/赎回、交易所净流和peg压力可能代表边际加密资金供给；总供应增速本身已被本项目证伪 | 三源共同UTC周锚点；exact finality、ABI/proxy、owner history与“零值保留lineage/排除economic”合同均已闭合 | 已失败的DefiLlama aggregate supply、BTC趋势；G0已证实非 aggregate 重包装；下一合同先测market-state/residual增量，不直接跳策略PnL | **G0 v0.2 `pass_to_market_state_design`**；family trial `0/2`；P2，须新预登记 |
| `token_supply_event_v1` | unlock、vesting、emission、burn和treasury transfer改变可交易供给和卖压风险 | 项目官方schedule、链上执行和交易所可用性三时钟；按事件/日期聚类，先做eligibility或风险折扣 | 市场/size/momentum控制及伪事件；主指标为事件后残差和流动性变化；公告修订不可追、执行量不可核验、样本幸存或只有事后日期即阻断 | 2；P2 |
| `network_adoption_quality_v1` | 使用、费用、活跃实体和结算价值可能反映网络需求；生产成本/算力不必预测收益 | 带vintage的active entity、fees、transfer value、realized cap/settlement；周频/月频，先做横截面残差 | price-only、size/momentum、已失败hashrate因子；主指标为跨币残差rank IC；若只是价格变换、latest-vintage回填、覆盖太窄或策略层不增量即拒绝 | 2；P2 |

#### E. 期权与组合元层

| Family | 经济机制与首批因子 | 数据时钟与首个测试 | 基线、主指标与Kill test | 预算/状态 |
| --- | --- | --- | --- | --- |
| `options_surface_state_v1` | IV term/skew、realized-implied gap和crash insurance price可表达尾部状态 | 完整PIT option chain、bid/ask、Greeks和expiry；先做capacity和risk-state，不恢复已失败DVOL spread | DVOL、realized vol、funding/basis；主指标为surface覆盖与尾部增量；无法重建过期链、成本/保证金未知或只是DVOL变体即阻断 | 2；P3 capacity blocked |
| `regime_allocator_meta_v1` | 独立sleeve的预期风险/相关性会变化，但组合器不能制造单腿alpha | 至少2条冻结Standalone NAV和共同stress calendar后才运行；输出风险预算，不改信号 | 固定权重、单sleeve、简单cap；主指标为OOS组合尾部和风险贡献稳定性；任何单腿非正、优化权重不稳定或收益只来自netting即拒绝 | 2；P3，尚未满足输入门 |

策略层优先组合顺序保持受限：`continuous multi-speed trend -> residual cross-sectional momentum -> trend + volatility de-risk ->
funding-crowding-conditioned trend -> liquidity-constrained selection`。前向结构family先独立积累，不抢占历史trial预算。只有至少两条
Standalone证据独立成立后，才允许测试`regime_allocator_meta_v1`；组合层不能挽救单腿失败，也不能把netting节省记回单腿alpha。

### R1.2：数据来源、历史边界与时点合同

2026-07-25通过确定性HTTP/API检索核对官方资料。Binance开发站对当前命令行入口返回WAF challenge，因此字段和历史限制以
Binance官方`binance-public-data`仓库及新模块化`binance-connector-python`源定义为可复核依据；正式实验仍要保存实际响应、
最终URL、source commit/hash和访问时点。

| 数据层 | 官方可核验事实 | 研究可用性 | 不得推断 |
| --- | --- | --- | --- |
| Binance Public Data | spot/futures aggTrades、klines、trades按日/月归档；日文件次日可用，月文件次月首个周一可用；kline含taker-buy量；ZIP配`.CHECKSUM`且历史归档可能修订 | 长历史价格、成交量和kline内主动买量；每个文件保存checksum、retrieved_at和revision | 当前可下载不等于历史symbol lifecycle完整；未核验旧缓存不得声称官方checksum通过 |
| USD-M `exchangeInfo` | 返回当前trading rules、symbol、onboard/delivery/status、precision和filters | 当前规则快照；必须从现在起定时保存revision | 当前快照不能重建过去filter、status和delisting真相 |
| USD-M funding history | `/fapi/v1/fundingRate`支持`startTime/endTime/limit`，无时点参数时返回最近200条并按时间升序分页 | 可按settlement时点重建已开放区间，必须检查每天完整结算和interval变更 | 不得把缺失settlement填0，也不得把日线只对齐一条funding |
| Premium/index/mark klines | 官方SDK暴露premium/index/mark price kline接口 | basis/premium历史候选源；逐symbol审计最早日期、缺口和修订 | 接口存在不证明任意symbol有完整长历史 |
| Basis statistics | `/futures/data/basis`官方定义仅保留最近30天 | 从现在起append-only；可做dated/perp曲线前向研究 | 不得伪造2020年以来官方basis历史 |
| OI statistics | `/futures/data/openInterestHist`官方定义仅保留最近1个月 | 从现在起append-only，聚合到4h/1d并保存原始响应 | 当前OI或最近月数据不能代表长周期历史状态 |
| Taker/long-short/top-trader ratios | 官方定义均只提供最近30天；top trader为margin balance最高20%账户/仓位比例 | 前向拥挤与flow状态；与kline taker-buy量分开建模 | 账户比例不是资金规模，position ratio不是净市场仓位，二者不能互换 |
| Liquidation stream | 官方模块化connector提供实时liquidation WebSocket stream；本次核验未发现官方历史归档承诺 | 只允许当前起实时收集、去重、断线/补缺标记和事件聚合 | 不得把第三方样本或近期流冒充官方完整历史 |
| 外部场所/链上/代币事件 | 各来源需独立许可、PIT revision、event/available/observed时点和clock normalization | 先做source-capacity artifact，再决定历史或前向 | 聚合站当前页面、项目最新schedule或HTTP接收时间不能反填历史可见事实 |

### R1.3：分波次研究路线

波次是依赖关系，不是收益承诺；同一波可由owner并行实验，但每个family独立记trial和污染状态。

| 波次 | 研究任务 | 进入条件 | 退出/切换条件 |
| --- | --- | --- | --- |
| Wave 0 文档冻结 | 为Trial 146/147和所有G0写ResearchCard；冻结source、clock、baseline、metric、kill和预算 | 本文完成 | owner开始实验前生成无结果预登记 |
| Wave 1 现有数据 | Trial 146连续forecast；breadth/dispersion与liquidity的无PnL G0 | TOP3数据和现有PIT审计输入可读 | Trial 146读数归档；G0失败则不读相关PnL |
| Wave 2 历史低频 | Trial 147、vol crisis、funding crowding、容量通过后的residual momentum | 各自G0通过且与旧失败机制有书面差异 | 每family第3个trial复盘；失败不跨family拼接救援 |
| Wave 3 前向衍生品 | OI/flow、basis curve、liquidation和cross-venue append-only | 原始响应、clock、去重、断线和source revision合同通过 | 达到预登记独立窗口才读结果；容量不足继续采集但不宣称0 alpha |
| Wave 4 外部PIT | stablecoin impulse、token supply、network quality、venue rule events | source-capacity、许可、历史vintage和事件时点通过 | 无可靠PIT或只是本项目旧失败的替代表达则关闭 |
| Wave 5 执行/组合 | maker fill economics、options capacity、regime allocator | 有真实/fixture执行样本；allocator另需2条独立Standalone NAV | required fill/capacity失败即停；组合不得回写单腿alpha |

每个波次结束只允许四种结论：`retain_for_next_evidence`、`reject_mechanism`、`block_capacity`、`continue_collection`。
`best Sharpe`、`promising`或`needs tuning`不能替代结论和下一条可证伪问题。

### R2：point-in-time universe与残差横截面动量，P1条件项

discovery PnL可随时启动，但只有R0证明相对当前LiquidTrend10发生以下实质变化，结果才可升级为候选或promotion证据：

- 历史上市/下架和可交易状态可重建；
- 至少8个同期标的具有完整bar/funding/rules/流动性；
- 有效广度、第一主成分和相关簇达到预登记容量门；
- 上线时长、成交额、盘口深度、OI、spread、缺失率、min-notional和precision均按决策时可见值过滤；
- 退市/缺失标的不会从历史中消失。

首个方向仍为long/cash，只在总风险门允许时做相对强度选择。第一版先把1、2、4、12周相对动量对BTC、TOP3和动态相关簇
做past-only beta residual，再冻结各尺度权重；排除新上市、已公告或可识别的临近退市、极端funding和不可执行标的，单币和
相关cluster均有上限。第一阶段不做long/short。若新宇宙仍表现为单一crypto beta、有效广度低于2或runtime rules不完整，
先停止PnL解释，不为得到结果放宽广度门。

### R3：波动率和危机状态，P1

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

首份无结果预登记草稿见 `docs/crypto-vol-crisis-state-preregistration.md`：RiskMultiplier∈[0,1] 纯降险overlay，
吸收CRA机器人（`docs/external-bot-cra-teardown.md`，T4）的"防瀑布急跌降险"与"信号翻转降险"两条规则，改写为因果非方向
触发器并新增横截面相关跃升信息以区别旧price-only缩放；主指标为降险效率（drawdown saved / return sacrificed）+ 尾部残差，
kill test直接瞄准Trial 147低效降险（Sharpe↓/turnover↑）的失败轴。属Track B，可立即在TOP3缓存上跑。

### R3.1：funding拥挤、流动性容量与OI/flow，P1/P2

- `funding_crowding_meta_v1`不预测carry，先研究横截面funding dispersion、价格/funding背离和拥挤持续时间。它必须在状态、
  作用对象或目标上实质区别于既有“TOP3中位数简单年化>50%”Funding Veto；否则计作旧family后续trial。
- `liquidity_capacity_meta_v1`先为universe eligibility、capacity和execution cost服务。volume/turnover/Amihud只能使用决策时可见窗口；
  spread/depth/rules缺失不能用0填充。独立alpha检验排在容量与成本校准之后。
- `oi_flow_forward_v1`从当前时点开始append-only采集OI、taker ratio和可验证order-flow；任何近期REST状态都不得伪装成2020年以来
  的长历史。只有达到预登记的eligible future窗口后才读取结果，并与常数、价格和简单趋势baseline比较。

### R4：ML元模型，P2条件项

先使用架构计划中的认证和自然成交数据，研究：

- 波动率、滑点和stop gap风险预测；
- 成交概率和maker等待价值；
- 订单/账户/数据异常检测；
- 不同策略相关性是否进入异常状态；
- 主信号meta-label，但只输出研究概率。

Logistic/常数先验/确定性规则是强制baseline。使用chronological walk-forward、purge/embargo和真实成本；预测准确率不能替代净收益或执行改进。

### R5：carry/basis，本地研究已开放

旧RV-C和C×D只提供机制与工程教训，不提供当前promotion资格。owner现已授权historical/discovery/shadow/virtual重启；研究应新建
独立StrategyIntent和新版本合同，覆盖spot/dated/perp数据、多腿状态机、legging risk、collateral、venue exposure、tail stress
和独立NAV。不得把carry重新塞进Base过滤器后声称独立收益源。

本地各层可并行建设；以下顺序只约束真实权限升级，每一级保留独立artifact，paper/live需要新的owner授权：

```text
funding observation
-> shadow attribution
-> paper hedge
-> minimal delta-neutral live
```

每一级分别归因funding forecast误差、basis变化、两腿费用/滑点、legging损失、资金占用和场所集中；所谓market-neutral必须由
实际beta和压力情景证明，不能由“现货多 + 永续空”的名义结构直接推出。

C×D组合回测可先用synthetic/历史腿验证管道，但只有两条独立NAV都完成当前版本重建后，结果才可解释为当前候选证据；组合结果
不回写Base参数，不把carry过滤器包装成趋势alpha，也不允许用组合净额掩盖某一腿的不可执行或basis-tail失败。

### R6：options/VRP，远期capacity lane

当前Deribit历史option surface和公共容量在G0证据不足，因此优先做数据/许可/执行能力审计；允许synthetic/discovery PnL用于
验证方法，但必须标为不可交易证据：

- 可获得的point-in-time chain、IV surface、bid/ask和expiry历史；
- delta hedge、保证金、尾部压力和多腿恢复；
- 远OTM保护成本和极端跳空；
- 数据预算、交易权限和场所风险。

期权family可写本地trial；capacity缺失必须进入scorecard并阻止可交易结论，真实场所或订单仍需独立owner授权。

若未来研究卖波动，优先采用“净carry + 远OTM保护成本 + 压力损失预算”的尾部对冲合同，而不是裸卖vol；保护成本、delta
hedge滑点、保证金占用和跳空损失必须进入Standalone NAV。这个合同仍不改变当前options surface G0阻断和no-options权限。

### R7：跨资产趋势，P1高价值重新认证

CTA-R历史可作为方法和baseline背景，但当前仍是guarded blueprint。优先顺序是：

1. 固定selection-free ensemble和walk-forward合同，先在可交易ETF上复核；
2. 报告跨资产有效广度、单一资产/类别贡献、债券/黄金/海外股regime集中和真实跟踪误差；
3. 再评估期货券商或其他场所的容量与执行，不把杠杆或期货授权当作策略收益证明；
4. 可先用research/synthetic输入进入virtual allocator验证架构；新时间、成本、账户权限和venue capability齐全后，
   才能把结果解释为可执行CTA-R候选证据。

多频段趋势（例如fast 20-60日、medium 60-120日、slow 120-250日）可以作为一个冻结trial合同；不得围绕最近结果继续扩展
lookback网格，也不得以“期货杠杆”掩盖ETF边际收益或新venue风险。

### R8：执行经济学与风险预算，P1条件项

这条线不先声称新增alpha，而是验证薄edge是否能被兑现、组合是否能在尾部保持可控：

- `post_only/maker`：冻结maker/taker费、实际fill概率、等待机会成本、逆向选择、取消/重挂和fallback taker成本；
  required fill rate超过1或after-tail净收益非正时拒绝该版本，不冻结新的实质机制研究；
- `TWAP/VWAP`：可随时用fixture/virtual slice replay验证；只有组合名义和容量确实需要时才进入paper或生产设计；
- 风险预算：先用固定压力损失预算、单资产上限和per-sleeve volatility target；协方差只作为稳健滚动估计，相关性趋近1或
  流动性同步下降时必须降风险，不能依赖优化器“找到”分散；
- 每个组合候选都输出单sleeve、组合、因子和无法解释残差，并把执行成本和尾部对冲成本从alpha中剥离。

### R9：跨策略组合复核，P1条件项

统一allocator研究立即开放：先用零sleeve fail-closed、单sleeve passthrough以及多个synthetic/research sleeve验证等风险/压力损失
预算，再比较波动率目标、权重上限和相关性约束。C×D、CTA-R或其他候选的promotion状态只决定输入能否代表真实候选或进入生产，
不阻止allocator代码与virtual归因。不得直接把协方差优化器当成生产配置；目标是验证增量风险贡献和尾部改善，不是把历史Sharpe相加。

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

### 5.3 研究与真实账户权限分离

```text
discovery
-> frozen candidate
-> promotion review on eligible new-time evidence
-> virtual NAV
-> shadow execution
-> paper
-> minimal live
```

这条梯子只描述证据和真实账户权限，不限制本地workstream并行。每次真实权限升级只增加一层，并冻结上一层的信号、成本模型、
预期换手/持有期、回撤区间和数据版本。迁移scorecard逐层比较：

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
- ✅ 完成多速度趋势Trial 145/146/147三个冻结trial（全reject），按"不救援"规则关闭`multi_speed_trend_v1`；
- ✅ Track A 补齐10币后最终G0：breadth `block_capacity`（相关广度1.660<2.0，真实容量）→关闭，residual momentum 传递关闭；
  liquidity `pass_to_capacity_calibration`→通过。危机状态 Trial 148 REJECT（尾残差恶化）。funding拥挤G0待做；
- 为OI/flow、basis curve、liquidation和cross-venue建立append-only source/clock/gap schema，不在达到独立窗口前读取结果；
- stablecoin、token supply、network和venue-rule只做source-capacity与PIT revision审计，不把最新网页反填历史；
- CTA-R与C×D保留现有proposal和证据清单，冻结为次级旁路，不占主动加密研究预算；
- 与架构计划并行建立T-D/T-F、execution certification离线fixture、shadow accountant和执行归因schema。

### 2-5个月：趋势核心与执行科学

- 完成多速度趋势首批3个冻结trial并复盘；
- 通过则进入独立virtual/shadow，未通过则关闭family或提出不同机制；
- 容量通过后运行残差横截面首个long/cash trial，并分别测试一个breadth state、危机RiskMultiplier和funding拥挤条件化trial；
- 前向结构family只在预登记独立窗口充足后各读取一次首批结果；basis/funding/ratio的30日窗口不得被重叠切片伪装成多个fold；
- CTA-R/C×D只有在owner重新提高优先级时恢复PIT、成本与tail复核，且仍不接期货实盘或carry paper；
- 用认证/自然成交证据建立滑点、rounding和stop语义基线；
- 决定point-in-time universe是否具备启动横截面trial的容量。

### 5-8个月：第二机制候选

- 在多速度、breadth、危机状态、funding拥挤和横截面动量中，按预登记顺序逐条完成family复盘，不并行追逐历史最优；
- 只从通过source-capacity的stablecoin/token/network/venue事件中选择一条外部PIT family进入正式trial；
- ML只做元任务并与简单baseline竞争；
- options capacity不足时仍可继续数据/fixture/discovery，结果保持低证据等级；
- 立即用零/单/多synthetic sleeve运行统一allocator的风险预算/相关性闸门消融，真实候选NAV成熟后再替换fixture；
- carry/basis已可进行historical/discovery/virtual正式trial；真实多腿订单仍需独立owner授权；
- 每个family独立记账，不提前混合信号。

### 8-12个月：组合化审查

- 最多选择一个拥有新时间/独立执行证据的candidate进入promotion review；
- 先virtual NAV、shadow execution，再决定是否需要paper；
- allocator和风险贡献架构可随时评估；两个真实sleeve证据只影响能否作真实组合结论；
- 一次只晋级一个新策略，任何live仍需另行owner授权。

月份是资源规划，不是结果承诺；capacity或kill test失败时应提前停止，不为满足日历继续投入。

## 7. 固定运行节奏

| 频率 | 任务 | 节点 | 输出 |
| --- | --- | --- | --- |
| 每日04:30 UTC | 现有Daily Intelligence | VPS | 生产/市场一手简报，不改交易 |
| 每日03:20 UTC | Base standard-production + natural-fill observer | VPS | 自然决策、标准对账、仅有fill时生成归因样本 |
| 每日04:00 UTC | Phase B readonly observation | VPS | valid/failed批次、watermark/diff/venue/HALT/fill覆盖 |
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

## 9. 一手来源矩阵与种子资料

本表记录2026-07-25已通过Crossref、NBER/BIS官方页或Binance官方仓库核对的身份。它只提供机制和方法依据，不是qount
策略有效性证明。正式`LiteratureRecord`仍需保存原文bytes/hash、版本、访问时点和正文抽取结果。

| 来源 | 已核对身份 | 支持的研究设计 | 不证明什么 |
| --- | --- | --- | --- |
| Moskowitz, Ooi, Pedersen, [*Time Series Momentum*](https://doi.org/10.1016/j.jfineco.2011.11.003) | JFE 2012，DOI `10.1016/j.jfineco.2011.11.003` | 多资产趋势持续、统一forecast和跨市场控制组 | 不证明TOP3 crypto某个lookback或Base替代方案有效 |
| Hurst, Ooi, Pedersen, [*A Century of Evidence on Trend-Following Investing*](https://doi.org/10.3905/jpm.2017.44.1.015) | JPM 2017，DOI `10.3905/jpm.2017.44.1.015` | 长样本趋势机制和跨阶段检验 | 不证明短加密样本具有同样分散或成本 |
| Daniel, Moskowitz, [*Momentum Crashes*](https://doi.org/10.1016/j.jfineco.2015.12.002) | JFE 2016，DOI `10.1016/j.jfineco.2015.12.002`；[NBER `w20439`](https://www.nber.org/papers/w20439) | momentum尾部、反弹期和危机状态需要单独检验 | 不自动支持任何事后crash filter；本地capitulation rebound已失败 |
| Barroso, Santa-Clara, [*Momentum Has Its Moments*](https://doi.org/10.1016/j.jfineco.2014.11.010) | JFE 2015，DOI `10.1016/j.jfineco.2014.11.010` | momentum风险随波动变化，可设计风险管理对照 | 不证明本地vol overlay；qount既有多条缩放已失败 |
| Moreira, Muir, [*Volatility-Managed Portfolios*](https://doi.org/10.1111/jofi.12513) | JF 2017，DOI `10.1111/jofi.12513`；[NBER `w22208`](https://www.nber.org/papers/w22208) | 以volatility管理风险的通用机制和效用框架 | 不证明crypto expected return不会随vol变化，也不授权降风险规则 |
| Liu, Tsyvinski, Wu, [*Common Risk Factors in Cryptocurrency*](https://doi.org/10.1111/jofi.13119) | JF 2022，DOI `10.1111/jofi.13119`；[NBER `w25882`](https://www.nber.org/papers/w25882) | crypto market/size/momentum暴露与横截面归因 | 不证明long-only残差动量扣成本后有alpha，也不解决PIT幸存者偏差 |
| Liu, Tsyvinski, [*Risks and Returns of Cryptocurrency*](https://doi.org/10.1093/rfs/hhaa113) | RFS 2021，DOI `10.1093/rfs/hhaa113`；[NBER `w24877`](https://www.nber.org/papers/w24877) | crypto特有momentum、attention和network-factor假设 | 不证明latest-vintage链上数据可用于历史决策；production-factor结果也不是普遍禁令 |
| Makarov, Schoar, [*Trading and Arbitrage in Cryptocurrency Markets*](https://doi.org/10.1016/j.jfineco.2019.07.001) | JFE 2020，DOI `10.1016/j.jfineco.2019.07.001` | 跨所分割、价格发现和套利资本限制 | 不证明公开API延迟下可执行套利；此前误列的NBER `w25234`与该论文无关，不再引用 |
| Schmeling, Schrimpf, Todorov, [*Crypto carry*](https://www.bis.org/publ/work1087.htm) | BIS Working Paper 1087，2023，2025-10修订 | basis/carry反映趋势追逐、便利收益和有限套利资本，高carry可作crash/crowding假设 | 不证明qount可获得cash-and-carry净收益；collateral、basis tail和双腿执行仍是硬门 |
| Amihud, [*Illiquidity and Stock Returns*](https://doi.org/10.1016/S1386-4181(01)00024-6) | JFM 2002，DOI `10.1016/S1386-4181(01)00024-6` | 低频price-impact/illiquidity代理与容量排序 | 不替代crypto实时spread、depth、min-notional和市场冲击样本 |
| Corwin, Schultz, [*A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices*](https://doi.org/10.1111/j.1540-6261.2012.01729.x) | JF 2012，DOI `10.1111/j.1540-6261.2012.01729.x` | 无历史盘口时的低频spread代理与对照 | 不证明估计spread等于可成交成本；必须与真实book样本校准 |
| Bailey, Lopez de Prado, [*The Deflated Sharpe Ratio*](https://doi.org/10.3905/jpm.2014.40.5.094) | JPM 2014，DOI `10.3905/jpm.2014.40.5.094` | trial selection、非正态和Sharpe膨胀修正 | 不提供统一通过阈值，也不能弥补错误数据和成本模型 |
| Bailey et al., [*The Probability of Backtest Overfitting*](https://doi.org/10.21314/JCF.2016.322) | JCF 2016，DOI `10.21314/JCF.2016.322` | 配置集合上的PBO/CSCV和多重试验治理 | 小样本/少配置时可能不可识别，不能被伪精确化 |
| Gu, Kelly, Xiu, [*Empirical Asset Pricing via Machine Learning*](https://doi.org/10.1093/rfs/hhaa009) | RFS 2020，DOI `10.1093/rfs/hhaa009`；[NBER `w25398`](https://www.nber.org/papers/w25398) | 非线性交互、特征重要性和严格基线的研究方法 | 不证明深度/树模型适合qount；本地price-only/HMM/GRU负证据继续保留 |
| [Binance Public Data](https://github.com/binance/binance-public-data) | 官方GitHub `binance/binance-public-data` README | archive字段、可用频率、次日/月发布、`.CHECKSUM`和历史修订语义 | 不提供完整历史exchangeInfo/lifecycle，也不自动认证旧本地缓存 |
| [Binance modular connector](https://github.com/binance/binance-connector-python/blob/15c2bfcbb9e9654d7186680a0dd32287a3285e11/clients/derivatives_trading_usds_futures/src/binance_sdk_derivatives_trading_usds_futures/rest_api/api/market_data_api.py) | 官方GitHub `binance/binance-connector-python`，核对commit `15c2bfcbb9e9654d7186680a0dd32287a3285e11` | USD-M endpoint、参数、当前规则字段及OI/basis/ratio的30日或1月历史限制 | connector定义不替代实际响应归档、source revision、断线和数据完整性审计 |

### 9.1 2026-07-25 owner 提供的文献 proposal queue

本批由owner基于可访问URL整理并送入队列；此处保留其访问状态和“不确定即未核实”的标记，不把摘要可访问写成全文已审计，
也不补作者、DOI、版本或数值结论。正式`LiteratureRecord`仍须另存原文bytes/hash、`observed_at`和parser version。全部提案
`orders_allowed=false`、`live_changes_allowed=false`、`holdout_role=discovery_pool`，triage=`accept_into_queue`只表示值得做下一道
source-capacity/G0，不表示机制通过、策略trial开始或部署约束解除。

| Proposal | 可核对身份与访问状态 | Family映射 | 机制增量与本地边界 |
| --- | --- | --- | --- |
| 1 | Maik Schmeling, Andreas Schrimpf, Karamfil Todorov, [*Crypto carry*](https://www.bis.org/publ/work1087.htm)，BIS WP 1087 / SSRN `4268371`；2023、2025-10修订；官方HTML/PDF可获取，版本=`BIS WP 1087, revised October 2025`；T1 | `carry_active_basis_v1` | 高carry、便利收益、杠杆趋势需求与有限套利资本支持“主动basis时序/crash state”假设；区别于已失败静态hold-to-convergence。真实delta-neutral腿仍涉及short、多腿费用、保证金和legging，超出当前部署约束，只做historical/discovery |
| 2 | Daniele Bianchi, Luca Rossini, Matteo Iacopini, [*Stablecoins and cryptocurrency returns: What is the role of Tether?*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3605451)，SSRN `3605451`；2020、2021修订；摘要可访问，全文/version未核实；T1 working paper | `stablecoin_liquidity_impulse_v1` | USDT/USD parity deviation是价格/边际流动性代理，不等于已失败aggregate supply；但论文不能替代链上mint/redeem PIT证据。v0.3 链上 no-PnL G0 已通过 source gate，market residual 仍未读取，须另立结果前合同 |
| 3 | [*Liquidation Mechanisms and Price Impacts in DeFi*](https://www.bankofcanada.ca/2025/03/staff-working-paper-2025-12/)，Bank of Canada SWP 2025-12，DOI `10.34989/swp-2025-12`；2025；官方页/PDF可获取；作者名单未核实；T1 | `liquidation_driven_flow_v1`，与`liquidation_cascade_forward_v1`/`crypto_vol_crisis_state_v1`路由复核 | fixed-spread与auction的竞争/参与成本改变清算价格冲击，属于机制与事件信息，不是Trial 148对称vol缩放。只可用DeFi链上事件或真实前向CeFi流；不得由DeFi机制外推多年CeFi liquidation历史 |
| 4 | Hugo E. Ramirez, Julián Fernando Sanchez, [*Optimal liquidation with temporary and permanent price impact, an application to cryptocurrencies*](https://arxiv.org/abs/2303.10043)，arXiv `2303.10043v1`；2023；摘要/PDF可获取；T1 | 用户标签`liquidity_capacity_v1`映射本地`liquidity_capacity_meta_v1` | BNB LOB用于估计temporary/permanent impact，直接服务真实book对CS日高低代理的校准；经济目标是成本/容量，不是方向alpha。长期LOB仍partial/昂贵，不得用近期样本拼成长期真值 |
| 5 | [*Asymmetric volatility spillovers and interconnectedness in major cryptocurrencies: evidence across time horizons and turbulent periods*](https://link.springer.com/article/10.1007/s40821-026-00348-8)，Eurasian Business Review，2026；摘要可访问、全文可能付费墙；作者/version未核实；T1 | `crypto_vol_crisis_state_v1`新信息候选 | 负/正半方差的非对称溢出、频率分解和动荡期相关跃升可区别Trial 148对称状态；只有取得所需高频历史并冻结新信息合同才可占用Trial 2/3，日频近似不得冒充5-minute复现 |
| 6 | Emre Inan, [*Predictability of Funding Rates*](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5576424)，SSRN `5576424`；2025；摘要可访问，全文/version未核实；T1 working paper | `carry_active_basis_v1` | DAR的funding OOS预测是active timing的前置可证伪问题，不证明basis策略扣成本后成立；本地funding容量ready，可先比较forecast error/no-change，再决定是否进入多腿状态机 |

| Proposal | 最小首测、控制与指标 | Capacity / kill / trial治理 |
| --- | --- | --- |
| 1 | BTC/ETH spot、perp/dated basis与funding的PIT日/8h状态；对照Base v0.2与旧静态carry；主指标=真实成本后net Sharpe及BTC/TOP3 beta-residual、分段、DSR/PBO；显式计maker/taker、funding、滑点、换手和双腿费用 | 跨所basis/保证金历史`partial`；成本×2或延迟1 bar后≤0、crash尾残差恶化、3个trial主指标仍失败即关闭；预算3 |
| 2 | v0.3 G0已确认真实链上边际flow不等价aggregate supply；下一合同把USDT parity deviation作为独立代理/控制，先测market-state与future residual增量、仍不读PnL；通过后才讨论纯现货成本和BTC/TOP3 residual | 三源严格mint/redeem PIT已ready，parity price可构建，但前向预测证据仍缺；无前向增量、与aggregate高度共线或成本/延迟后失效即拒绝；预算3，但当前family trial仍0 |
| 3 | 链上清算事件、机制类型、参与/竞争代理和事件价格冲击；对照同幅度price shock、对称vol-target与Trial 148；主指标=尾残差改善/误杀成本，计高滑点 | DeFi可做event study；官方CeFi多年OI/liquidation blocked，只允许近窗+append-only；尾残差不改善、与对称vol无区别或有效样本/PBO不足即停；预算3且必须新信息 |
| 4 | 真实LOB/trades估计effective spread及temporary/permanent impact，校准当前CS/Amihud成本；主指标=代理误差和capacity，不要求beta residual | 长期历史LOB partial；无法取得足够样本、校准后代理仍显著偏误或对低频成本无增量即停；预算3，属于成本基础设施而非strategy trial |
| 5 | 多币realized semi-variance、负/正spillover与频率状态；对照Trial 148/简单对称vol；主指标=尾残差和非对称降险效率，低频实现必须标proxy | 5-minute历史partial；与对称vol无增量、尾残差无改善或高频不可复现即拒绝；占`crypto_vol_crisis_state_v1`剩余预算，不新开同义family |
| 6 | Binance/Bybit BTC 8h funding，DAR对no-change的时间顺序OOS误差；只有forecast gate通过才测试active timing residual Sharpe；计funding与换手 | 本地funding`ready`；OOS预测不优、转策略后成本非正或分段不稳即拒绝；与Proposal 1共享`carry_active_basis_v1`总预算3，不各自获得3次 |

未检出可靠T1/T2且不以T4凑数的缺口继续保留：严格PIT链上mint/redeem边际流对crypto residual的前向力、官方多年CeFi
OI/basis term structure/liquidation历史、低频可用的长期真实book depth/impact公开集，以及独立于funding/basis/liquidation/price-only的
新venue-event family。总供应、近期窗口拼接、缺失值填0或商业数据“可购买”都不能替代这些证据。

仍保留但尚未升级为一手接受来源的metadata seeds：survivorship/delisting SSRN `4287573`、cross-sectional momentum
SSRN `2949379`、用户提供的2026 Bitcoin ML SSRN `6795938`及任何2026新论文。必须先核对作者、标题、版本、样本、成本、
代码/数据可得性和正文hash；未来论文的高Sharpe、token unlock或order-flow结论只能进入proposal queue。

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
- 不把OI、basis、long-short ratio或liquidation近期官方窗口拼接成虚假的多年历史；
- 不把stablecoin总供应、hashrate或DVOL换名后当成新信息源；新family必须改变数据、因果时点或经济目标；
- 不同时启动全部family的PnL网格；先做G0/source-capacity，再按Wave顺序读取结果；
- 不因短期论文热点改变Base参数或跳过新时间证据。

## 11. 下一轮执行步骤（2026-07-26 之后）

先读的文档：本文（尤其R0-DATA、R1.1的G0执行结果、R2）、`project-rules.md`§6数据边界、`current.md`下一步与硬边界。
执行前提：所有步骤`orders_authorized=false`、不碰VPS/paper/live；大批量下载只在Windows/WSL侧直落外置盘
（可直连或Liangxin云代理，禁止苏菲家宽代理），Mac只做编排、轻验证和文档。

### 已完成（Track A/B/C，2026-07-25 批次）

- **Track A（数据工程 + 10币G0）**：R0-DATA闭合，10币全下载。`market_breadth_dispersion_v1` 最终 `block_capacity`
  （相关有效广度`1.6602`<2.0，真实容量限制）→ **关闭**，`cross_sectional_residual_momentum_v1` 传递 **关闭**；
  `liquidity_capacity_meta_v1` `pass_to_capacity_calibration` → **通过**。
- **Track B（vol crisis）**：`crypto_vol_crisis_state_v1` Trial 148 REJECT（5/6门，尾残差恶化）；1/3已用。
- **Track C**：v0.2/r2 的 owner/零值阻断保留为历史；v0.3 已以 EOA 全块+receipt、Sourcify multisig source/ABI/
  runtime 和 `5,544` slots 全枚举闭合 USDT Ethereum owner history，并把 TRON `991` 条零值事件保留 lineage、排除
  economic flow/count。新 no-PnL G0 为 `376/376` 周锚点、`209/209` aggregate 对照、coverage=`1.0`、unknown=`0`，
  8 个 kill test 全 false，verdict=`pass_to_market_state_design`；仍未读市场结果。前向4 schema `continue_collection`。

### 下一轮候选（按已通过的线）

绑定约束不再是数据。可并行推进以下**已过G0/容量门**的线，每条仍 `orders_authorized=false`、预登记在前、看结果前冻结门：

1. **`liquidity_capacity_meta_v1` capacity calibration**（P0）-- ✅ **首轮完成（2026-07-25）**。
   模块 `src/qount/mini_trend/liquidity_capacity_calibration.py`（21 单测）消费冻结 G0 artifact
   （hash `fa02ed8b...bf95`，10/10 通过），脚本 `scripts/research/run_liquidity_capacity_calibration.py` 产出不可变
   scorecard `state/research_runs/20260724T184308-liquidity-capacity-meta-calibration/`（SHA `bad32d63...72b4`，
   contract `01f3c651...12a9`）。成本模型：half-spread=CS/2、impact=`amihud_x_1e6·N/100`（线性 Amihud 上界代理）、
   friction=half-spread+impact（不含费）、total 另加 Binance UM taker 4bps。**读数**：①robust participation-only 全宇宙容量
   ≈**21.3M USDT**（LTC 绑定，=213M 日成交额×1%）；②Amihud 冲击可忽略——即便 1% participation 冲击仅 1.7–6.6bps，
   非绑定约束；③**CS 日高低价差代理对全部 10 币高估**（half-spread 11.6–44.5bps vs 真实 perp <1bp），5/10/25bps
   预算容量因此塌成 0，属 proxy-limited 非 liquidity-limited。**cost-error 结论**：无真实 fill/盘口，ground_truth 不可得；
   下一步是 WSL 侧采集真实 book depth 校准价差、并在全逐日序列上做滚动/分段容量。`orders_authorized=false`、无方向无 PnL。
2. **`stablecoin_liquidity_impulse_v1` market-state design**（P2）-- ✅ **no-PnL G0 已通过（2026-07-26）**。
   v0.3 collection 与 G0 bundle 已独立全量回读，v0.2/r2 保留不覆盖。下一步必须另立结果前预登记，只测试 weekly marginal
   flow/分类状态对 aggregate supply、简单趋势与 BTC/TOP3 residual 的增量；先做无PnL预测/状态诊断，再决定是否占用 family
   trial。不得把本次 `pass_to_market_state_design` 写成 alpha、候选PnL、promotion 或部署资格。
3. **`crypto_vol_crisis_state_v1` Trial 2/3**（P1，可选）：148 已证明合成危机降险尾部不够有效。若继续，Trial 2/3 须引入
   与148不同的信息或目标（见 `docs/crypto-vol-crisis-state-preregistration.md`），否则按低效降险直接关闭family，不救援。
4. **carry active-basis**（R5，可并行）：`docs/carry-active-basis-hypothesis.md`，做 historical/discovery，不进 paper/live。
5. **前向采集器启动决策**（owner）：Wave 3 四个 schema 已冻结；是否/何时在 WSL 侧启动实际 append-only 采集器
   （OI/basis/liquidation/cross-venue）由 owner 决定，达到预登记独立窗口前不读结果。

### 优先级建议

最便宜、最能解锁下游的是 **①liquidity capacity calibration**（成本基础设施，多条线复用）-- **首轮已完成**（见上）；
后续增量是 WSL 侧真实 book depth 采集（替代高估的 CS 价差）与全逐日滚动/分段容量，属数据采集非 Mac 编排。stablecoin
G0 已证实“不只是 aggregate 重包装”且三源证据闭合；第2项现在只能先冻结 market-state 增量合同，不能借 G0 pass 直接读取
策略PnL。vol-crisis（③）证据已偏负，除非有实质新信息不必强推。carry（④）与前向采集（⑤）可低成本并行。
横截面（breadth/residual）已关闭，**不重开、不扩币**。


## 12. 个人策略新方向候选（2026-07-27，owner 要求：低数据/低硬件/厚利润）

详见 [personal-strategy-research-directions.md](personal-strategy-research-directions.md)。四条候选均避开
成本/延迟/执行/广度四堵已证伪墙，共享事件冻结 + 小额风险预算 + 原生保护单执行底座：

```text
D1 宏观事件右侧篮子扩展（CPI/NFP/PCE/GDP 复用 FOMC 链）  P0
D3 跨资产趋势个人载体重新认证（R7 提级，评估基准改为个人默认持仓）  P0.5
D2 极端 funding + 清算级联 forced-flow 均值回复（须先过与 Trial 144 的独立性 G0）  P1
D4 已知事件前低波动区间 fade 泛化（依赖 7/30 PreEvent-Range canary 证据）  P2
D5 美股行业 ETF 趋势轮动 + 受约束 ML 特征选择（owner 2026-07-27 提出；先过 11 行业有效广度 G0，
   ML 仅限特征排序辅助且须过 purged-CV/DSR/PBO 对简单动量基线的显著性门）  P1
```

排除：币内横截面轮动（广度墙）、日内时段效应（成本墙）、期权 VRP（PIT 数据墙）、
DCA 择时（已证伪）、网格/套利（薄利润）。所有候选仍从 G0/预登记开始，`orders_authorized=false`，
不新增守护进程，不改变本路线既有 R0-R9 优先级中已冻结/关闭线的状态。
