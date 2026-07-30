# Alpha Agents 多智能体研究架构

> **状态**：active research-only｜**权威**：L3 研究（多 agent）｜**最后更新**：2026-07-26
> **本文回答**：多 agent 资料搜集、只读日报生产、source book、后续量化接入边界。
> **TL;DR**：LLM 只写 research/日报，不出订单/目标权重/live 配置。

状态：active research-only + 只读日报生产闭环。Owner 于 2026-07-08 授权先搭建多 agent 架构，用于搜集资料、优化方案和后续接入
量化训练；2026-07-22已完成免费官方feed发现、详情复抓、TOP3行情、六角色中文LLM、不可覆盖归档、Dashboard和个人微信真实投递，
并启用每日timer。手机入站/通道回发、context刷新和Qount正整数`message_id`均已验证；当前仍不写paper/live state、不arm live，LLM报告不提供策略promotion或订单权限。

更准确的定位：这是 `deterministic quant harness + LLM 研究/审计外壳`，不是“多 agent 本身产生
alpha”。relay-station ChatGPT、历史GLM和计算节点都只是研究吞吐工具，不是 alpha 来源。

2026-07-26 的 `stablecoin_liquidity_impulse_v1` v0.3 remediation + G0 说明这条边界的实际用法：确定性 collector/G0
以 EOA 全块/receipt、Sourcify verified source/ABI/runtime、multisig state 全枚举和 exact confirmation 闭合三源证据；TRON
`991` 条零值 Transfer 只保留 lineage/finality，不进入 economic flow。LLM不参与事件分类、PIT时钟、去重或 verdict。
新 G0 为 `376/376` 共同周样本、`209/209` aggregate anchors、coverage=`1.0`、unknown=`0`，8 个 kill test 全 false，
verdict=`pass_to_market_state_design`；marginal flow 仍不等价 aggregate supply。该 verdict 只解除下一份 market-state 设计的
source gate，Agent 仍只能提出/审计预登记与反例，不能把它升级为 alpha、PnL、paper/live 或订单建议。

## 目标

MiniTrend TOP3 已被 beta 归因复核打穿：它解决的是 400 USDT 小盘可成交性和熊市少亏，不是月级
alpha。Alpha Agents 的目标不是继续调 long/cash trend，而是把研究吞吐拆开：

- 多个 research agent 并行搜集官方数据源、交易规则、论文方法和历史 artifact。
- deterministic quant worker 负责特征、标签、回测、模型训练和 scorecard。
- red-team / audit agent 只做审计和反驳，不能晋级策略。
- LLM只作为研究/审计模型，不进入订单、目标权重或风控 override。

## 已落地骨架

代码边界：

- `src/qount/alpha_agents/models.py`：`AgentRole`、`ResearchTask`、`AgentReport`、`SourceRef` contract。
- `src/qount/alpha_agents/roles.py`：默认角色 registry，并支持从 JSON 加载自定义角色。
- `src/qount/alpha_agents/tasks.py`：默认 seed tasks，并支持从 JSON 加载自定义任务。
- `src/qount/alpha_agents/sources.py`：官方数据源、验证方法和本项目证据源清单。
- `src/qount/alpha_agents/llm.py`：relay-station ChatGPT adapter；默认关闭网络调用、并发1、SDK重试0、应用层最多1次有界退避、严格JSON。
- `src/qount/alpha_agents/information_events.py`：point-in-time事件schema、allowlist、hash和越权validator。
- `src/qount/alpha_agents/official_sources.py`：官方网页无代理抓取、双URL allowlist、大小上限、原文hash和LLM摘要上下文。
- `src/qount/intelligence/search.py`：生产默认从Binance公告API、Fed RSS和SEC RSS免费发现官方URL并保存原始字节hash；Brave adapter只保留兼容。
- `src/qount/intelligence/market.py`：Binance USD-M TOP3公开24小时行情、funding与下一结算时间；两份原始响应字节hash/归档。
- `src/qount/intelligence/history.py`：从冻结RuntimeLedger v3提取订单、逐笔成交、费用、funding、NAV、回撤和对账摘要。
- `src/qount/intelligence/daily.py`：固定六角色日报链，red-team/editor接收前序报告，所有输出保持research-only；v2把pipeline状态、
  evidence状态和结构化ResearchProposal分离。
- `src/qount/intelligence/archive.py`：日报、market/search/source原文、manifest和latest指针的不可覆盖`0700/0600`归档与重放。
- `src/qount/intelligence/notifications.py`：把日报映射为`AlertEvent`，不赋予通知或订单权限。
- `scripts/operations/run_daily_intelligence.py`：串联authority、公开行情、官方feed、LLM、归档、NotificationStore和可选个人微信/WeCom投递。
- `src/qount/portfolio_governance.py`：三NAV、压力风险预算、trial budget、前向污染和独立样本合同。
- `src/qount/alpha_agents/validators.py`：report 状态、必需字段和越界输出扫描。
- `src/qount/alpha_agents/orchestrator.py`：research-only orchestrator 和 artifact writer。
- `src/qount/alpha_agents/promotion.py`：deterministic promotion scorecard / G0-G7 gate。
- `src/qount/alpha_agents/metrics.py`：beta-residual metrics builder。
- `src/qount/alpha_agents/knowledge.py`：source-quality scoring，区分官方/论文/教程/社交噪声。
- `src/qount/alpha_agents/binance_returns.py`：Binance public dump returns dataset builder。
- `src/qount/alpha_agents/exchange_rules.py`：Binance public `exchangeInfo` filter/min-notional validator。
- `src/qount/alpha_agents/feature_experiment.py`：deterministic feature-grid train/OOS experiment runner。
- `src/qount/alpha_agents/derivatives_state.py`：Binance USD-M OI / taker buy-sell recent-state loader。
- `src/qount/alpha_agents/validation.py`：DSR/PBO/purged-CV/walk-forward validation adapter。
- `scripts/research/alpha_agents/alpha_agent_plan.py`：薄 CLI，生成 `state/research_runs/*/alpha_agent_plan.json`。
- `scripts/research/alpha_agents/alpha_agent_official_source_review.py`：单个allowlisted官方文档的无代理抓取、hash和LLM审阅CLI。
- `scripts/research/alpha_agents/alpha_agent_scorecard.py`：薄 CLI，读 metrics JSON，生成
  `state/research_runs/*/alpha_agent_scorecard.json`。
- `scripts/research/alpha_agents/alpha_agent_beta_metrics.py`：薄 CLI，读对齐 period returns，生成
  beta-residual promotion metrics。
- `scripts/research/alpha_agents/alpha_agent_sources.py`：薄 CLI，输出 source trust report。
- `scripts/research/alpha_agents/alpha_agent_binance_returns.py`：薄 CLI，从 Binance public dump 输出对齐 returns。
- `scripts/research/alpha_agents/alpha_agent_exchange_rules.py`：薄 CLI，拉 Binance 公共 `exchangeInfo` 并输出 rules artifact。
- `scripts/research/alpha_agents/alpha_agent_feature_experiment.py`：薄 CLI，跑特征网格 train/OOS 实验并输出 OOS returns。
- `scripts/research/alpha_agents/alpha_agent_derivatives_state.py`：薄 CLI，拉 OI history、taker buy/sell ratio 和当前 OI。
- `scripts/research/alpha_agents/alpha_agent_validation.py`：重放 feature config 并输出 G4 validation artifact。
- `tests/test_alpha_agents.py` / `tests/test_alpha_agents_promotion.py`：离线运行、artifact、角色替换、
  validator、promotion gate 测试。
- `tests/test_alpha_agents_metrics.py`：beta-residual metrics builder 测试。
- `tests/test_alpha_agents_knowledge.py` / `tests/test_alpha_agents_binance_returns.py`：资料源甄别和
  Binance returns dataset 测试。
- `tests/test_alpha_agents_exchange_rules.py`：runtime rules、min-notional、funding 接入测试。
- `tests/test_alpha_agents_feature_experiment.py`：feature-grid runner、OOS returns、metrics/scorecard 接入测试。
- `tests/test_alpha_agents_derivatives_state.py`：derivatives-state parsing、30 天限制、artifact writer 测试。
- `tests/test_alpha_agents_validation.py`：DSR/PBO、purged/walk-forward、metrics 注入和 source 绑定测试。

## 默认角色

| role | 类型 | 负责 | 禁止 |
| --- | --- | --- | --- |
| `market_data_scout` | LLM research | 数据源、保留期、延迟、缺口 | trade signal / target weight |
| `exchange_rules_scout` | LLM research | filters、费率、funding、最小名义 | position size / risk override |
| `quant_librarian` | LLM research | DSR/PBO/purged-CV/triple-barrier 方法 | promotion claim |
| `feature_designer` | LLM research | 特征和标签草案、as-of 依赖 | live order |
| `experiment_designer` | LLM research | 小实验、baseline、kill-test | live config change |
| `model_trainer` | quant worker | A10 训练、OOS scorecard、feature importance | 直接下单 |
| `backtest_auditor` | deterministic audit | 成本、min-notional、beta 归因、泄漏 | trade signal |
| `risk_architect` | deterministic gate | 杠杆、回撤、stale data、unmanaged position | LLM override |
| `red_team` | LLM review | 找 beta、后视、成本漏计、多重检验 | target weight |
| `ops_auditor` | LLM review | 读 paper/live artifact，解释异常 | order / cron / live arm |

读法：LLM 角色只输出 `report/proposal/critique`；`model_trainer/backtest_auditor/risk_architect`
是 deterministic-only，不能用 LLM 结果代替。

## Seed Tasks

当前内置 5 个任务：

1. `source_map_v0`：建立 Binance / validation / project evidence 资料地图。
2. `beta_residual_target_v0`：定义 beta-residual label 和 BTC/TOP3 B&H 基准，防止再做 beta wrapper。
3. `intraday_microstructure_v0`：设计 1m/5m order-flow、spread、funding、OI 特征实验。
4. `a10_training_lane_v0`：定义 A10 训练线、tabular baseline、sequence model、OOS gate。
5. `small_account_risk_v0`：定义 400 USDT 激进但 fail-closed 的 futures / short 风险边界。

## 运行

离线生成全量 agent 计划，不调用 LLM：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_plan.py
```

只跑一个 task 并打印 JSON：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_plan.py \
  --task-id beta_residual_target_v0 --print-json
```

接火山方舟Coding Plan时显式opt-in。凭据优先放在权限`0600`的仓库外
`~/.qount/alpha-agent.env`，不要在shell历史中导出真实token：

```bash
export QOUNT_ALPHA_AGENT_LLM_ENABLE=true
export QOUNT_ALPHA_AGENT_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
export QOUNT_ALPHA_AGENT_PROVIDER_PROFILE=volc_coding_plan
export QOUNT_ALPHA_AGENT_MODEL=glm-5-2-260617
export QOUNT_ALPHA_AGENT_MAX_CONCURRENCY=1
export QOUNT_ALPHA_AGENT_MAX_TOKENS=8000
export QOUNT_ALPHA_AGENT_MAX_RETRIES=1
export QOUNT_ALPHA_AGENT_RETRY_BASE_SECONDS=10
export QOUNT_ALPHA_AGENT_MAX_RETRY_DELAY_SECONDS=60
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_plan.py --with-llm
```

不要把token写入仓库、artifact、prompt或文档。第一阶段只运行固定fixture和有真实研究任务的单次调用；禁止
throwaway连通性探测。LLM调用结果仍然只是research artifact，不能提供promotion证据。

## 每日情报与复盘合同

当前固定链路为：

```text
Binance announcement API + Federal Reserve RSS + SEC RSS discovery
-> allowlisted official-source refetch + raw bytes/hash
-> Binance public market pulse + raw bytes/hash
-> frozen RuntimeLedgerSnapshot v3 summary
-> market/event/execution/strategy/red-team/editor
-> append-only local archive
-> Dashboard intelligence read model
-> NotificationStore -> Tencent personal Weixin iLink
```

搜索只发现URL。任何写进“已观测事实”的内容必须来自再次抓取的官方allowlist原文，并保存`observed_at/content_type/byte_count/
source_hash`；模型记忆、模型自称搜索或搜索摘要都不能替代。行情hash是原始HTTP字节SHA-256，不是解析后JSON的canonical hash。
交易复盘只读冻结账本，不用目标仓位或公共价格补算成交、费用、PnL或回撤。

日报角色固定为`market_analyst -> event_analyst -> execution_reviewer -> strategy_reviewer -> red_team -> editor`。LLM可输出解释、
反例和带baseline/kill-test的研究建议；不得输出订单、目标权重、live配置、杠杆/风险override。日报本身固定
`orders_allowed=false/live_changes_allowed=false`，必须经确定性dataset/backtest/scorecard和独立promotion流程后才可能影响策略。

Daily Intelligence v2额外要求：`pipeline_status`只说明抓取/解析/角色链是否完成，`evidence_status`才说明结论证据是否充分；
两者不得互相替代。每个`ResearchProposal`必须明确简单基线、kill test、完整成本、时间顺序holdout、来源与历史容量和G0状态。
任一项缺失或`g0_status=blocked`时，提案只留在研究队列，不能创建promotion候选。全现金且策略没有计划订单的账本周期记为
`no_order_expected`；只有计划了订单却没有exchange order/trade/fee证据时才是`orders_expected_but_missing`，不得用0订单制造假告警，
也不得把0订单说成已验证成交能力。

2026-07-22最新生产日报为`38985fe5...50d5fc`，report hash=`d42c851d...9e68`。它完成7份一手来源、TOP3行情、
冻结RuntimeLedger和六角色链，外层为`pipeline=complete/evidence=sufficient/status=attention_required`；这里的`sufficient`只表示本次
日报有足够材料形成受限复盘，不表示策略、成交或盈利证据充分。报告正确拒绝从单点24小时行情和公告推导因果Alpha，也明确0订单、
0成交不能验证成本或执行质量。5个结构化提案全部为`g0_status=blocked_history_capacity`、`orders_allowed=false`、
`live_changes_allowed=false`，不得自动创建数据下载、回测、paper或live任务。旧生成端把三个零数量symbol行误记为`position_count=3`，
导致execution/editor误述“3个持仓”；本地`0.2.13`已改为按非零数量（含正负方向）计活动仓位。中文越权扫描也扩展到下单、买卖、
开/加/减/平仓、做多/做空、杠杆、实盘/交易开关、目标权重和仓位动作。`0.2.13/89be296`现已部署VPS；隔离、无通知复跑
确认`position_count=0`、旧误报文本0条，5个proposal仍全部`g0_status=blocked_history_capacity`且禁止订单/live修改。
旧正式日报保留其部署前历史内容，不原地重写。

个人微信provider复用腾讯官方OpenClaw插件账号和recipient，固定官方host/path/header，并以NotificationStore delivery key派生稳定client ID。
生产凭据只保存`account_id/base_url/recipient/token`；每次发送前从OpenClaw accounts目录按account和recipient读取最新context token，避免手机
入站刷新后Qount副本漂移。动态目录和文件必须满足绝对路径、无symlink、owner和`0600`等安全合同，缺失或无效时失败关闭；静态context token只允许
手工/测试回退。只有HTTP `2xx`、合法JSON、无非零`ret`且存在正整数`message_id`才接受，`ret!=0`和无效body均失败关闭。只投递明确选择的
`openclaw_weixin` channel。HTTP成功后本地落标前崩溃仍可能重复，因此不声称exactly-once。WeCom adapter继续保留但production unit不再要求或发送WeCom。

首次生产日报完整保存3份feed、8份官方详情和2份行情，但因把每份最多12,000字符的全文同时交给六角色，在网络前被50,000字符安全
上限阻断；该不完整报告和通知保留。当前实现按角色构造上下文：event每来源最多1,800字符，strategy/red-team/editor每来源最多600字符，
red-team/editor只接收前序报告压缩字段；原文归档和全局上限不变。8份真实来源的六角色测试载荷最大值固定小于35,000字符。

第二次生产E2E报告ID为`24defae63419d002a74ff07fd578c994b3b68f6eb200bd76b3a4fc6ca1fb6adc`，六个非流式Responses载荷约
13.4-40.2KB并全部得到中文严格Schema结果；3份feed、8份详情、2份行情、可用交易历史、manifest、latest readback及个人微信历史
本地`DELIVERED/SUCCEEDED`记录和12行audit chain均可验证。后续诊断证明旧`DELIVERED`只检查HTTP `2xx`：失效会话实际返回`ret=-2/prepare failed`，
故历史记录本身不代表手机送达。已修复provider、恢复OpenClaw网关、接收手机测试消息并刷新context；真实Qount中文验证消息返回19位正整数
`message_id`并被严格标记`ACCEPTED`；新生产NotificationStore job `9c6fca5efc6b...`为`DELIVERED`、attempt为`SUCCEEDED`，16行audit chain
完整重放。报告状态为`incomplete`，原因是四个审阅角色对发布时间、来源正文和外部成交证据主动
返回`needs_research`，不是基础设施或本地载荷失败。Dashboard `intelligence`现为`available`并绑定report hash
`f4d90e84b1828345261568043623ba7b32ea5b66ede9fbe66d490f54ddd63a94`；日报timer为`enabled/active`，每日`04:30 UTC`运行并带
0-10分钟随机延迟。随后动态会话读取已部署，日报unit增加`openclaw-gateway.service`依赖与accounts目录只读挂载，生产凭据删除静态
`context_token`后仍由新架构验证job `6d51a764...4324`一次投递为`DELIVERED/SUCCEEDED`；store为5 event/job/attempt和20行audit chain。
Mac扩大回归`75 OK`、VPS部署聚焦`24 OK`。

当前真实依赖状态（2026-07-26）：通用Alpha Agent与Daily Intelligence均使用火山方舟Coding Plan，Console名称`glm-5.2`
映射API模型ID=`glm-5-2-260617`，base URL=`https://ark.cn-beijing.volces.com/api/coding/v3`，输出上限=`8000`。
Coding Plan走Chat Completions `json_object`；方舟在复杂提示下可能返回单一JSON代码围栏，客户端只接受无前后附文的精确围栏，
随后仍执行标准JSON解析、严格五字段、语言和越权校验。VPS凭据为独立`0600 root:root`
`/etc/qount/intelligence/coding-plan.key`，生产搜索不需要付费Key；旧relay/TokenRouter路径保留为历史，不再被production unit引用。

`2026-07-21T13:23:23.472311+00:00`按一次真实研究任务完成TOP3首角色严格Schema中文分析，耗时约`26.5s`；pulse/ticker/premium原始
证据hash为`e991a4a3...04c` / `df89881f...787` / `30a0ddfe...eee`，五字段、中文、越权语言和source hash校验通过。它只证明单角色LLM
链路恢复；完整六角色和个人微信随后由上述生产E2E证明。只读日志另见两次长流式Codex请求
分别约`125.7s/126.7s`后遇到上游`524`
并映射为502，两次随后均恢复200。应用仅对瞬时状态和显式`retryable=true`最多退避重试一次，支持错误体`retry_after`；只有
`owner_action_required`而无可重试标记时立即失败关闭。任何失败日报仍单独归档和通知，不覆盖最后一份历史报告。

历史relay使用的`gpt-5.6-terra`是当时目录中实测存在的私有模型名，不在本地公共OpenAI模型指引中。它不自动代表已联网：
任何当前网页事实必须先由`official_sources.py`获取原文字节并记录hash/observed time，再作为有界context提交。

## 角色替换

后续要把角色换成量化 worker，不改 orchestrator，传 JSON：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_plan.py \
  --roles-path configs/alpha_roles.json \
  --tasks-path configs/alpha_tasks.json
```

`roles.json` 支持：

```json
{
  "roles": [
    {
      "role_id": "quant_researcher",
      "name": "QuantResearcher",
      "kind": "quant_worker",
      "mission": "Run deterministic feature and model experiments.",
      "allowed_outputs": ["scorecard", "model_artifact"],
      "forbidden_outputs": ["order", "risk_override"],
      "llm_allowed": false
    }
  ]
}
```

## 资料约束

首批资料源固定为官方/主来源：

- Binance Spot REST / WS market data、filters、market-data-only endpoint。
- Binance USD-M futures `exchangeInfo`、klines、bookTicker、funding、open-interest、WS depth。
- Binance public data dump / `data.binance.vision`，用于可复现 backfill。
- Deflated Sharpe Ratio、PBO/CSCV、AFML purged-CV / embargo / triple-barrier。
- FINRA algo trading supervision、SEC market access、NIST AI RMF、OWASP Agentic AI / LLM Top 10
  作为 agent 权限和系统安全参考。

硬约束：

- Spot / futures schema 分离；last / mark / index / premium price source 必须显式记录。
- Funding 按 `fundingTime` as-of 对齐；未来 funding 不能进入场前特征。
- OI 历史 REST 覆盖有限，若要长历史必须持续落库或标注供应源缺口。
- WS order book 必须 REST snapshot + diff depth 重建并校验 sequence gap；断链强制重建。
- 多 agent 共享 quota manager，不能各自无脑打 API；429/418 风险不能影响 live 通道。
- 回测/paper/live 复用同一个 filter/fee/min-notional validator。

资料源评分入口：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_sources.py \
  --tags binance_market_data,validation,agent_security
```

读法：`accept` 源可以作为数据/验证/安全边界依据；`review` 源只能作为教程或实现参考；教程和博客
不能让 promotion gate 通过。

Binance 公共规则入口：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_exchange_rules.py \
  --market um \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT
```

该命令只读取公开 `exchangeInfo`，不会读取私有 Binance key。输出 artifact 可被 returns builder
复用：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_binance_returns.py \
  --start-month 2024-01 \
  --end-month 2024-03 \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT \
  --strategy-symbol ETHUSDT \
  --market um \
  --interval 1d \
  --fast-window 10 \
  --slow-window 30 \
  --include-funding \
  --exchange-rules-path state/research_runs/<run>-alpha-agent-exchange-rules/alpha_agent_exchange_rules.json
```

读法：只有 `exchange_rules_source=runtime_exchange_info`、`filter_validator_reused=true`、
`funding_included=true` 和真实 `min_notional_coverage` 同时进入 metrics，G1/G3 才算有运行时规则和
成本证据；这仍然不代表策略有 alpha。

## 后续接量化

下一步不是让 LLM 生成交易，而是把 `ResearchTask` 接到 deterministic experiment runner：

```text
source_map -> feature_spec -> dataset_builder -> label_builder
  -> model_trainer(A10) -> walk_forward_scorecard
  -> backtest_auditor -> red_team -> promotion gate
```

首个量化 slice：

- market：Binance USD-M futures，先 BTC/ETH/BNB/SOL，后续看 min-notional 和有效广度。
- bars：1m/5m + funding/OI/bookTicker；标签用 beta-residual next 3/6/12 bar net return 和
  triple-barrier 对照。
- model：先 LightGBM/HistGradientBoosting/Logistic baseline；A10 sequence model 只在 tabular OOS
  过门后启动。
- scorecard：月度 net alpha、BTC/TOP3 beta residual、cost sensitivity、DSR、PBO、purged-CV、
  min-notional coverage、capacity。

晋级规则：LLM 多数同意无效；只有 deterministic scorecard 过 gate 才能进入 paper。

2026-07-08 runtime rules smoke：

- `alpha_agent_exchange_rules.py --market um --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT`
  生成 `state/research_runs/20260708T035439Z-alpha-agent-exchange-rules/alpha_agent_exchange_rules.json`，
  4/4 symbols returned 且 4/4 `TRADING`。
- ETH SMA 2024Q1 public dump + funding + rules 生成
  `state/research_runs/20260708T035513Z-alpha-agent-binance-returns/alpha_agent_binance_returns.json`：
  `period_count=90`、`total_turnover=2.0`、`min_notional_coverage=1.0`、`funding_settlement_count=270`、
  `total_funding_return_pct=-3.533644`。
- beta metrics：
  `state/research_runs/20260708T035520Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`，
  `net_residual_return_pct=-1.165668`、`beta_to_btc=0.552037`。
- scorecard：
  `state/research_runs/20260708T035535Z-alpha-agent-scorecard/alpha_agent_scorecard.json`，
  `verdict=block`；G1 runtime rules 已补上，但 G2/G3/G4/G5/G6 仍阻断。结论：样例 SMA 不是策略，
  它只证明 Binance 公共规则、funding 和 gate plumbing 可用。

## Feature Experiment Runner

`alpha_agent_feature_experiment.py` 是第一个“模型实验接口”。它仍然不训练深度模型，但把后续 A10
训练需要的 contract 先固定下来：

```text
public/REST klines + funding/OI/taker ratio -> feature grid -> train split selection -> OOS returns
  -> beta metrics -> promotion scorecard
```

当前内置 feature families：

- `momentum`
- `reversal`
- `relative_momentum`
- `vol_adjusted_momentum`
- `oi_delta`
- `oi_value_delta`
- `taker_ratio`
- `taker_imbalance`
- `kline_taker_imbalance`
- `kline_taker_pressure_change`
- `kline_quote_volume_z`
- `kline_realized_vol_change`

当前内置 modes：

- `long_short`
- `long_cash`
- `short_cash`

运行示例：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_feature_experiment.py \
  --start-month 2024-01 \
  --end-month 2024-03 \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT \
  --strategy-symbol ETHUSDT \
  --market um \
  --kline-source public_dump \
  --interval 1h \
  --horizon-bars 6 \
  --train-fraction 0.6 \
  --lookbacks 6,12,24,48 \
  --thresholds 0,0.0025,0.005 \
  --modes long_short,long_cash,short_cash \
  --polarities 1,-1 \
  --selection-metric rank_ic \
  --beta-lookback-bars 168 \
  --include-funding \
  --exchange-rules-path state/research_runs/<run>-alpha-agent-exchange-rules/alpha_agent_exchange_rules.json
```

`--kline-source` 支持 `public_dump` 和 `rest`。`rest` 当前只走 Binance USD-M
`/fapi/v1/klines`，用于与 recent OI/taker ratio artifact 对齐；若使用
`--derivatives-state-path`，runner 会把 OI/taker ratio 按 decision time 做 as-of join，并用
`--min-feature-coverage` 防止无重叠数据产生 0-position 假阳性。
`--selection-metric rank_ic` 使用 rolling as-of BTC beta 构造 forward residual label；
`--polarities 1,-1` 会把顺向和反向关系作为独立 trial，避免只因 feature 符号定义漏掉逆向 edge。

输出的 `periods` 默认是 OOS 月度 returns，可直接喂给
`alpha_agent_beta_metrics.py`。该 runner 的定位是：先证明数据、特征、选型、OOS 和 gate plumbing
完整；不是宣称这些简单价量特征有 alpha。

2026-07-08 1h feature-grid smoke：

- `state/research_runs/20260708T040453Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`
  选中 `relative_momentum_lb12_thr0_long_short`，train periods `1309`、OOS bars `874`、OOS 月度 periods
  `2`、candidate count `144`。
- runtime rules/funding evidence：`min_notional_coverage=1.0`、`filter_validator_reused=true`、
  `funding_included=true`、OOS filter `107/107` pass。
- OOS 结果：`strategy_total_return_pct=-30.103078`、`btc_total_return_pct=39.471843`、
  `top3_equal_weight_total_return_pct=54.382491`、`beta_to_btc=7.494191`、
  `net_residual_return_pct=-302.677680`。
- scorecard：
  `state/research_runs/20260708T040514Z-alpha-agent-scorecard/alpha_agent_scorecard.json`，
  `verdict=block`。读法：简单 feature grid 被 OOS 打穿，下一步应补 walk-forward/DSR/PBO 和更强特征，
  不是把这个候选继续调参。

## 2026-07-16 Owner Priority Reset

Owner 决定先放弃 A股 ETF 路线并把研究优先级转回加密。该决策恢复的是 **research-only 的新信息源发现**，
不是恢复已经失败的合同、VPS collector、A10、paper 或 live：

- A股 ETF 20 日线冻结保留，不再占用数据、券商接入或自动化工作量。
- frozen trade-flow v1、flow absorption、premium dislocation、aggregate-depth Logistic 及固定 2025Q1 replay
  的负结论全部保留；不得重调现有 Q1/April 或换模型 family rescue。
- 新的第一交付物是 source-capacity matrix，然后只预注册一个独立信息机制。候选范围限定为此前合同没有
  表达的 liquidation、真实 replayable L2/queue、options volatility/skew 或 cross-venue state。
- 在读取策略结果前必须冻结 beta-residual target、symbols、discovery/OOS 窗口、成本、trial count、
  kill line 和 protocol hash。历史覆盖不足时只能标为 forward-research，不能伪造长历史。
- 仍只在 Mac 读取 public data 和写 research artifact；共享 1.6G VPS 不重跑长 collector，private API、
  订单、生产 cron、paper/live 均未获授权。

## 2026-07-17 Structural Source Matrix And Options-DVOL Result

第一轮 new-source restart 已按“容量先于收益、单一候选、ex-ante hash”完成：

- `source_capacity.py` 只读官方公开小响应与 Binance `.CHECKSUM`。matrix artifact
  `20260716T141329Z-alpha-agent-source-capacity`：historical `forceOrder`/replayable `depth` 为 404，
  aggregate `bookDepth` 可用但非 L2；Hyperliquid 四币 funding/premium 历史可用但与旧失败机制重叠；
  Deribit BTC/ETH DVOL 在 2021-04 与 2025-01 边界均返回 25 根小时 OHLC，因此唯一选为 G0。
- 在任何收益读取前，最终 v0.3 preregistration `20260716T145022Z` 冻结：
  `ETH_DVOL_close - BTC_DVOL_close`、720h normalization/beta、reversion polarity、`|z|>=2`、24h
  hold/cooldown、ETH/BNB/SOL 固定分母、5bps taker + 2bps slippage/position change、funding、400 USDT
  filters、逐币 IC/residual 与 2/3 aggregate gate。contract/protocol hash 为
  `195a9160...3b95` / `c87b0d96...86fa9`；收益读取前的 v0.1/v0.2 只保留为完整性审计中间件。
- `historical_dvol.py` 按月请求并保留每个原始响应 SHA。dataset `20260716T142116Z` 为 BTC/ETH 各
  32,904 小时、coverage `1.0`、0 gap/duplicate、90 requests、`2,654,952` response bytes；缓存复跑
  data hash `d07122f7...09c86` 不变。
- 首跑发现 SOL 月档在 2022-02-26..28/2022-04-01..02 缺 120 小时，price coverage `0.996353`；没有
  缩窗口或放宽门，而是仅用五个对应 daily ZIP + 官方 checksum 补缺并重跑。最终四币 price、DVOL
  feature、exchange filter coverage 均 `1.0`，funding 各覆盖 45 个月。
- 冻结 discovery 结果：ETH IC/residual `-0.048945/-55.322693%`，BNB
  `-0.078558/-77.010159%`，SOL `+0.004773/+6.290805%`；每币 188 entries，max rolling 24h turnover
  `2.0`。SOL 只有正 residual、没有可接受 IC；三币 report `20260716T151115Z` 为 0/3 pass，median IC
  `-0.048945`、mean residual `-42.014016%`。
- verdict：`block_discovery`。不反转 polarity、不调 z/lookback/holding，不读 2025 replication，不用
  2026-07-17 起 forward 窗救 discovery，不进 A10/paper/live。下一 source-capacity 只考虑真正的 historical
  option-surface skew，或可校验的 liquidation/replayable L2 历史；cross-venue state 必须先证明机制不同于
  已失败 funding/carry/spread 线。

### Follow-On Option-Surface And External Microstructure Capacity

DVOL 失败后继续执行了两个只读 G0，不读取任何策略收益：

- Deribit option-surface artifact `20260716T155503Z-alpha-agent-option-surface-capacity` 为 `block_g0`。
  五个已知过期合约的 metadata 和 price chart 可用，当前 BTC/ETH surface 有 `874/720` 条 mark-IV；但公开
  chart schema 只有 OHLC/volume/cost/ticks，2024 historical trade probe 为 0 rows，`expired=true`
  inventory 只枚举一个近期 expiry。历史 chain/IV/index/mark 不可 point-in-time 重建；禁止用未注册的
  IV inversion + strike search 生成 skew 候选。
- Tardis external artifact `20260716T160716Z-alpha-agent-external-microstructure-capacity` 为
  `block_g0_access_capacity`。四币 metadata 同时确认 `incremental_book_L2`/`liquidations`；BTC depth
  一分钟有 1,086 个连续更新、0 sequence break，四币 forceOrder 同分钟有 1 条 SOL，raw hashes 分别为
  `69060a8d...a7e81`/`57f28cac...175c`。匿名整日请求只返回 1 分钟；BTC raw L2 外推约
  `2.85 GB/day`、`256.90 GB/90d`，超过 32 GiB source-cache gate。
- 因此不写第二份 G0 preregistration。若 owner 授权可复现的 licensed history，只选择体量显著更小的
  liquidation-only；否则只能复用已存在的 collector contract 做 Mac-only forward research，且 forward
  样本不得伪装成历史 discovery 或 promotion。

## Strategy V0: Microstructure Residual Alpha

2026-07-08 本地 GLM agents 已接入并完成全量 research run。以下是历史运行快照；其模型、并发和重试配置已被
2026-07-19 relay-station ChatGPT单请求合同取代：

- `state/research_runs/20260708T044141Z-alpha-agent-plan/alpha_agent_plan.json`
- gateway：`https://llm.alyaloale.com/v1` / `glm-5.2`
- local config：`~/.qount/alpha-agent.env`，权限 `600`，`max_concurrency=3`

本轮 agent 共识：

- 不能继续在日线/纯 trend 上做收益率调参；第一批简单 feature-grid 已被 OOS 打穿。
- 新方向应是 Binance USD-M 1m/5m 的 residual alpha：taker flow、spread/top-of-book、funding/OI、
  liquidation 和 mark/index premium。
- OI、top-trader ratio、leverage bracket、fee schedule 必须先补官方源；不能用教程或二手资料让 gate 通过。
- bookTicker / aggTrade / diff-depth / forceOrder 这类高频特征历史 public dump 不一定完整，必须区分
  “可历史回测特征”和“先采集再 forward 验证特征”。

### V0 市场与目标

研究目标：

```text
market: Binance USD-M futures
capital model: 400 USDT research account
symbols v0: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT
primary horizons: 1m/5m bars, forward 3/6/12 bars
target: BTC/TOP3 beta-residual net return, not raw return
promotion: deterministic scorecard only
```

V0 不直接交易，也不输出目标仓位。输出必须是 OOS returns artifact，再走
`alpha_agent_beta_metrics.py` 和 `alpha_agent_scorecard.py`。

### 数据分层

可立即做历史 kill-test 的数据：

- Binance public dump 1m/5m klines：OHLCV、quote volume、taker buy base/quote volume。
- Binance public dump fundingRate：funding settlement cashflow 和 funding-as-feature。
- Binance public/runtime `exchangeInfo`：min-notional、tick、lot、rate-limit、symbol state。
- Binance REST `/futures/data/openInterestHist`：OI 历史，先验证覆盖期和 gap。
- Binance REST `/futures/data/takerlongshortRatio`：taker buy/sell volume ratio，先验证覆盖期和 gap。

需要先采集再 forward 验证的数据：

- `bookTicker`：spread、best bid/ask qty、top-of-book imbalance。
- `aggTrade`：更精细 taker flow、trade intensity、large-trade ratio。
- `diff depth`：L2 OFI、depth slope、queue imbalance；必须 snapshot + diff sequence 校验。
- `forceOrder`：liquidation side/notional imbalance。
- mark/index/premium streams：premium dislocation、basis reversion。

### Feature Families

第一批只做可解释、可审计特征：

| family | source | features | first horizon |
| --- | --- | --- | --- |
| taker-flow | 1m/5m klines 或 aggTrade | taker imbalance, taker volume z, buy/sell pressure change | 3/6 bars |
| volatility/liquidity | klines + bookTicker | realized vol, volume z, spread bps, spread volatility | 3/6/12 bars |
| derivative-state | funding + OI | funding z, funding delta, OI delta, OI/volume, crowding change | 6/12 bars |
| liquidation-stress | forceOrder | liquidation imbalance, liquidation notional z, post-liquidation reversal | 3/6 bars |
| basis/premium | mark/index/premium | premium z, premium reversion, mark-vs-last dislocation | 3/6/12 bars |

### Label And Model

Label：

- 用 rolling/expanding as-of regression 估计 BTC/TOP3 beta。
- forward return 先扣 taker fee、half-spread/slippage、funding、min-notional rounding。
- label 用 `net_residual_forward_return_pct`，再派生 triple-barrier label。
- 所有 `feature_event_time <= decision_time`，所有 `label_event_time > decision_time`。

Baseline/model 顺序：

1. Univariate IC / sign strategy：先看每个特征是否有方向和 OOS 稳定性。
2. Tabular baseline：logistic / HistGradientBoosting / LightGBM research extra。
3. A10 sequence model：只有 tabular residual OOS 正、DSR/PBO 过门后才启动。

### First Kill-Tests

S1 `kline_taker_flow_v0`：

- 数据：public dump 1m/5m klines + runtime exchangeInfo + funding。
- 特征：taker imbalance、volume z、realized vol、short-horizon momentum/reversal。
- 窗口：先 2024-01..2024-08，train 6 个月、holdout 2 个月。
- kill：holdout IC < 0.02、net residual <= 0、BTC beta > 0.5、cost-stress net <= 0 任一触发即停。

S2 `derivative_state_v0`：

- 数据：fundingRate + openInterestHist + takerlongshortRatio。
- 特征：funding z/delta、OI delta、OI/volume、taker buy/sell ratio。
- horizon：5m 的 6/12/24 bars。
- kill：PBO >= 0.5、DSR < 0.95、去掉最大贡献月后 residual <= 0 即停。

S3 `live_collector_v0`：

- 数据：bookTicker、aggTrade、diff depth、forceOrder。
- 历史优先：先审计并回填官方 archive；只有历史候选存活后，才在独立节点采 24-48 小时做 runtime parity。
- kill：gap rate、sequence break、snapshot resync 或 event-time audit 任一不过即停。

### 400 USDT Risk Boundary

研究模拟也必须按小账户执行约束：

- 每个 simulated order 先过 runtime `exchangeInfo` filters。
- 交易成本默认用 taker，不允许靠 maker fill 假设通过 gate。
- 单笔预期 edge 必须大于 `fee + half_spread + slippage + funding_buffer` 的 3 倍才可计为可交易信号。
- 杠杆研究可测，但 scorecard 必须先报告 liquidation buffer 和 max adverse excursion；不允许 LLM 改 leverage。
- 任何 promotion 仍要求 G1-G6 通过，尤其是 `min_notional_coverage`、`funding_included`、`paper_orders_replayable`。

### 下一步实现顺序

1. 已完成：补 official source book 和 knowledge scoring，包括 open interest、taker buy/sell ratio。
2. 已完成：实现 `alpha_agent_derivatives_state.py`，下载/缓存/解析 OI 与 taker ratio。
3. 已完成：feature experiment runner 已接入 derivatives-state、REST/public kline、原生 kline
   taker-flow、rolling-beta rank IC 和 bar/month OOS returns。
4. 已完成：walk-forward/DSR/PBO adapter 已接入，matching validation artifact 可填充 G4。
5. 暂停：S1/S2 当前均无正 OOS residual；A10 tabular/sequence trainer 不启动。
6. 已完成 smoke：S3 collector 已接入 bookTicker/aggTrade/diff-depth/forceOrder gap、event-time 和
   实际订单簿 replay 审计，四币严格 60 秒 artifact 为 `pass_data_smoke`。
7. 已完成负向基线：可恢复 session 支持冻结 config/hash、UTC 分段、原子 raw/manifest、daily manifest、
   单写锁、暂停/恢复和 orphan 审计；旧 `restart_per_segment` 实测最长 `7.499s` route 连接空窗，已停止。
8. 已完成：改为 websocket 不断开的 `continuous_in_stream_rotation`；双段真实 smoke 的 connection restart、
   boundary gap、aggTrade/depth boundary break 均为 0，逐段 SHA/replay parity 通过。段界 audit 已移到独立
   进程，避免读取旧 gzip 让新段 websocket 接收滞后。
9. 已停止：Mac 首版与 VPS 7 天会话均为 `superseded/incomplete` 或 `block_data`，不得拼接。VPS 会话只完成
   约 21 小时，19/22 闭段通过；最后一段有约 38 分钟空窗，随后共享 VPS 因内存不足多次重启。该失败已证明
   长跑链不适合当前 1.6G 共享节点，不原样重跑。
10. 已完成负向基线：历史优先。官方 archive 覆盖审计和 checksum-verified daily metrics loader 已接入；2024Q1
   四币 104,332 rows，唯一共同缺口已切成独立 segment。第一版 72-candidate OI/taker-ratio kill-test 虽有
   OOS rank IC `0.029326`，但成本后 beta-residual `-56.833338%`，不进 A10/paper/live。
11. 已完成首个正向但未 promotion 的 trade-flow v1：真实 `aggTrades/bookTicker` schema/checksum/gap loader、5m
    聚合和唯一冻结 1h 合同已接入。Q1 discovery 与 2024-04 once-only historical OOS 均为正 residual，但
    validation 的 DSR/PBO 和 G5/G6 仍 block；不调 frozen contract、不下载更多月份追结果、不启动 runtime parity。
12. 已完成负向跨符号复制：在新数据读取前冻结 BTC/BNB/SOL replication protocol；三币 Q1 同合同 IC/净
    residual 全败，按门控未消费复制 April。G5 已由“缺证据”收敛为明确失败，frozen v1 停止晋级。
13. 已完成第二个负向机制 kill-test：预注册 flow/price absorption 单候选后，ETH/BNB/SOL Q1 为 0/3 通过，
    median IC `-0.018355`、mean net residual `-10.908112%`，未消费 April。后续不得继续从同一 Q1
    `aggTrades` 单源变换方向；重启必须加入独立的 liquidity/premium/liquidation 状态并先冻结协议。
    Q1 `bookTicker` 12/12 月包虽可用但压缩体量 `54.58 GiB`，当前 Mac 容量下不整季下载；下一优先级转
    小体量 mark/index premium，bookTicker 仅保留为有明确磁盘预算的抽样/流式备选。
14. 已完成第三个负向机制 kill-test：official premium/mark/index Q1 数据链 36/36 包、四币 100% coverage，
    但预注册 premium mean-reversion 为 0/3 pass，median IC `-0.001891`、mean net residual
    `-3.575008%`，未消费 April。下一独立源限定为 historical aggregate `bookDepth`；先实现严格 parser/
    5m 聚合和容量 gate，不得把百分比累计深度冒充 diff-depth 或 replayable L2。
15. 已完成固定 tabular 趋势概率模型：historical `bookDepth` 364/364 包流式聚合后，与 premium/price
    point-in-time 合并；预注册的 10-feature L2 Logistic Jan-Feb→March 三币 0/3，mean net residual
    `-11.018991%`，Brier 全部劣于常数基线，PBO 保持 `1.0`。模型 artifact/replay 接口成立，但 A10
    sequence、HGB/LightGBM 和 April OOS 均不启动；不得在 Q1 做 model-family rescue。
16. 已完成 new-source 第一轮：source-capacity 只选择 Deribit options DVOL，v0.3 协议在读取收益前冻结；
    2021-04..2024-12 BTC/ETH DVOL 数据门通过，SOL 价格月档缺口以 checksum-verified daily 档补齐后，
    ETH/BNB/SOL discovery 仍为 0/3 pass。2025 replication/forward OOS 未消费，options-DVOL 停止。
17. 已完成 follow-on G0：Deribit public historical option surface 因 chain/IV 不可 point-in-time 重建而
    `block_g0`；Tardis liquidation/L2 样本可校验，但匿名历史截断且 raw L2 超 32 GiB budget，故
    `block_g0_access_capacity`。无 owner 的 access/forward 选择前不写 preregistration。

### 2026-07-16 Historical-First Microstructure And Metrics

新增两个明确分层的数据入口：

- `historical_microstructure.py` 只读取 Binance 官方 `.CHECKSUM` sidecar，输出 dataset × cadence × symbol ×
  period 覆盖矩阵，不下载大文件。真实 artifact
  `state/research_runs/20260716T032055Z-alpha-agent-historical-microstructure/alpha_agent_historical_microstructure.json`
  为 `36 available / 4 missing / 0 error`。`aggTrades` 和 `metrics` 可作为历史主输入；`bookTicker` 覆盖随
  时期变化；`bookDepth` 虽有日文件，但 CSV 语义是百分比聚合 depth/notional，不是可重放 diff-depth。
- `historical_derivatives.py` 并发下载 daily metrics ZIP + 官方 checksum，缓存原始归档并输出与现有
  feature runner 兼容的 `open_interest_hist/taker_long_short`。2024Q1 artifact
  `state/research_runs/20260716T033710Z-alpha-agent-historical-derivatives/alpha_agent_historical_derivatives.json`
  加载 364/364 archives、104,332 rows、四币覆盖率 `0.995230`、0 fetch/checksum error。2024-02-16
  四币共同缺约 10.5 小时；dataset 写 `segment_id`，feature runner 的 OI lookback、K线回报、rolling beta、
  forward label 和 PnL 都禁止跨非连续 bar。

第一版确定性 kill-test：2024Q1 USD-M 5m，Jan-Feb train/Mar OOS，`oi_delta/oi_value_delta/taker_ratio` ×
4 lookback × 2 threshold × 3 mode，共 72 candidates；训练按 rank IC 冻结
`oi_delta_lb1_thr0_long_short`。train/OOS rank IC `0.022246/0.029326`，但全窗 turnover `4,223`、每次方向
变化成本 `7bps`，OOS beta-residual `-56.833338%`。正 IC 被频繁换手完全吞没，scorecard 在 G2/G3/G4/G5/G6
block。最终 feature/metrics/scorecard artifact 为 `20260716T035639Z`、`20260716T035652Z`、
`20260716T035706Z`；在 rolling beta 完全按 gap 重置前的 `034337Z/034357Z/034406Z` 数值相同，只作中间
证据。这否定当前简单 sign/threshold 执行合同，不否定 historical metrics 数据源；同一 Q1 discovery 不再
挑 threshold。下一刀必须预先定义低换手、稀疏 no-trade 设计或换 `aggTrades/bookTicker` 信息源。

### 2026-07-16 Frozen Historical Trade-Flow V1

数据合同：

- `historical_tradeflow.py` 支持 official daily/monthly `aggTrades`、`bookTicker` ZIP + `.CHECKSUM`，下载到 cache
  后按文件流 SHA-256，ZIP 内 CSV 逐行解析并聚合 5m；解压后的千万级事件不落盘、不整体进内存。
- `aggTrades` 审计 `agg_trade_id` 月内/跨月连续性、event-time 单调和空桶；`bookTicker` 审计 update/time 回退、
  crossed book、非法数量。update ID 可合法跳号，只把回退当 blocker。
- BTC 2024-01-01 双源 smoke 为 288/288 完整桶、0 sequence/schema blocker；Q1 ETH 3 个月共
  113,092,010 trades -> 26,208 个 5m 桶，100% coverage、1 segment、0 ID gap。

在读取独立月份前冻结唯一合同：

```text
contract=agg_trade_imbalance_z168_entry2_hold6_cooldown18_momentum_v1
contract_hash=2b61627cecd5c5c8567255a8a6c24f1d6f3b8f126a965524bdd13b49c4cb9094
feature=completed-hour aggressive quote-flow imbalance
normalization=past 168 completed hours only
entry=abs(z) >= 2, momentum polarity
execution=hold exactly 6h, then cash cooldown 18h, no direct flip
turnover_budget=max 2.0 position-change units in rolling 24h
trials=1
```

最终读数：

| window | role | rank IC | entries | max 24h turnover | net beta residual |
| --- | --- | ---: | ---: | ---: | ---: |
| 2024Q1 | discovery | 0.024647 | 41 | 2.0 | +7.163938% |
| 2024-04 | historical_oos once-only | 0.039999 | 16 | 2.0 | +6.196189% |

April artifact 从 2024-03-24 加载 168h warmup，但只在 `2024-04-01T00:00Z` 强制空仓后计收益/IC；没有把
warmup PnL 混入 OOS。专用 fixed-candidate validation 复用同一 contract hash，frozen-discovery beta 下 April
residual `+7.663555%`，5-fold time stability 通过；但 DSR `0.915342` 未过 `0.95`，单候选 PBO 不可识别并
fail closed 为 `1.0`。最终 scorecard：`G0-G3/GX pass`，`G4/G5/G6 block`。

读法：这是 Strategy V0 第一份同时过 discovery/历史 OOS 的成本后正证据，不是 promotion。不能在已看窗口
改参数，也不能事后造 variants 填 PBO。下一步必须先预注册单候选 anti-overfit 与跨符号 correlation-stress
protocol；G4/G5 未过前不做 24-48h runtime parity，更不在共享 VPS 恢复 7 天 collector。

### 2026-07-16 Frozen V1 Cross-Symbol Replication

在读取 BTC/BNB/SOL 新 trade-flow 内容前，先生成 preregistration：

```text
artifact=20260716T083420Z-alpha-agent-tradeflow-replication
protocol_hash=d2c9ca4e3c116c449dc5ad395f557e8893ecc65fe7af55f77b0bf203b8d03da1
contract_hash=2b61627cecd5c5c8567255a8a6c24f1d6f3b8f126a965524bdd13b49c4cb9094
replicas=BTCUSDT,BNBUSDT,SOLUSDT
discovery=2024Q1
oos=2024-04, only after that symbol passes discovery
pass=min 2/3 positive OOS IC and residual + effective breadth >=2 + max abs corr <=0.8
     + equal-weight/leave-one-out residual positive + filter coverage 1.0
pbo=unchanged blocking 1.0
```

Q1 数据 `20260716T085640Z-alpha-agent-historical-tradeflow`：9/9 archive、295,897,363 raw trades、
78,624 个完整 5m 桶；三币均 100% coverage、1 segment、0 archive/cross-archive ID gap。

| symbol | rank IC | entries | max 24h turnover | net beta residual | verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| BTCUSDT | 0.007095 | 45 | 2.0 | -4.150084% | block_discovery |
| BNBUSDT | -0.016277 | 46 | 2.0 | -8.680766% | block_discovery |
| SOLUSDT | -0.028842 | 46 | 2.0 | -5.175364% | block_discovery |

三币 contract/filter/cost 均一致，April OOS 全部 `oos_consumed=false`。最终 replication report
`20260716T090929Z` 为 `block_correlation_stress`，重算 scorecard `20260716T090958Z` 仍 block G4/G5/G6。
这说明 ETH 正结果没有跨 majors 复制，不能把它解释为普适 aggressive-flow alpha；frozen v1 在 historical
research 阶段诚实停止，不启动 runtime parity/A10/paper/live。后续重启必须换结构性信息或先写新的 ex-ante
hypothesis，不得在当前 Q1/April 上修参数。

### 2026-07-16 Flow/Price Absorption Kill-Test

跨符号复制失败后，没有反调原 v1 polarity，而是先冻结一个机制不同的单候选：极端主动买卖 flow 如果没有让
同小时 BTC beta-residual 价格同向移动，解释为 passive liquidity absorption，随后做 6h 反转。预注册先于
策略求值写入：

```text
preregistration=20260716T100011Z-alpha-agent-flow-absorption
contract=agg_flow_price_absorption_z168_entry2_hold6_cooldown18_reversal_v1
contract_hash=8f30e70133a6550e52156ae7445638b7b68ef05696b405605033086f8f5bf124
protocol_hash=0c6f277c00156f0d01b4d4045e21e2f85e705abc5d3b93e95589f83f2a82d816
symbols=ETHUSDT,BNBUSDT,SOLUSDT
discovery=2024Q1 already-observed pool
reserved_oos=2024-04, do not consume unless discovery passes
signal=-flow_z when flow_z * same-hour beta-residual return <= 0, otherwise cash
entry=abs(flow_z) >= 2; hold=6h; cooldown=18h; no direct flip
cost=5bps taker fee + 2bps slippage per position change + funding
pass=min 2/3 symbols pass individual IC/net-residual/execution gates
trials=1
```

结果：

| symbol | rank IC | entries | max 24h turnover | net beta residual | verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| ETHUSDT | -0.024471 | 11 | 2.0 | -8.056549% | block_discovery |
| BNBUSDT | 0.018082 | 19 | 2.0 | -15.461342% | block_discovery |
| SOLUSDT | -0.018355 | 15 | 2.0 | -9.206446% | block_discovery |

三币 filter coverage 均为 `1.0`，因此失败不是最小名义或数据 gate；合并 report
`20260716T100057Z-alpha-agent-flow-absorption` 为 0/3 pass、median IC `-0.018355`、mean net residual
`-10.908112%`，blockers 同时命中 passing/positive-IC/positive-residual/median-IC/mean-residual，且
`reserved_oos_consumed=false`。读法：raw aggressive-flow momentum 没有跨符号复制，把同一 flow 与当小时
价格背离改做 reversal 也没有 edge。至此不能在已看 Q1 上继续造第三个 `aggTrades` 单源变体。

随后只读取官方 `.CHECKSUM`/HTTP metadata 做 source-capacity audit：artifact
`20260716T100514Z-alpha-agent-historical-microstructure` 显示 2024Q1 四币 `bookTicker` 月包 12/12 available；
但 12 个压缩包 Content-Length 合计 `58,608,259,115 bytes`（`54.58 GiB`）。Mac 当前可用约 `87 GiB`，
完整缓存后只剩不足约 33 GiB，尚未计 artifact/临时空间，因此本轮不下载、不启动 flow × top-of-book
实验。下一项可证伪研究必须新增独立信息状态，优先实现体量更小的 mark/index premium 覆盖/loader 和
预注册 dislocation/reversion kill-test；`bookTicker` 只有在先冻结日期抽样或实现带磁盘上限的流式聚合后才
重开。任何新线仍先过 discovery 和跨符号门，不能直接消费 April、启动 runtime parity/A10/paper/live。

### 2026-07-16 Premium Dislocation Kill-Test

`bookTicker` 整季容量不可接受后，先接入体量小的 Binance official USD-M
`premiumIndexKlines/markPriceKlines/indexPriceKlines`。`historical_premium.py` 只接受固定 12 列 5m kline
schema，任何列数/数值错误 fail closed；逐包读取 `.CHECKSUM`、SHA-256 校验、原子 cache，并将三源按
event time 合并。最终 dataset：

```text
artifact=20260716T102324Z-alpha-agent-historical-premium
window=2024-01-01..2024-03-31
archives=36/36 checksum verified
compressed_bytes=7,613,751
rows=104,832 complete 5m rows
per_symbol=26,208 rows, coverage 1.0, segment_count 1
data_hash=784a816afaefd6375be9ee98c2449f97975c4679f66a99b46591c201089d7381
```

策略结果读取前冻结唯一合同：

```text
preregistration=20260716T102055Z-alpha-agent-premium-dislocation
contract=premium_mean_z168_entry2_hold6_cooldown18_reversion_v1
contract_hash=f07d07027d004cc4ab6173e17c727862f36d0e895047a0986fee1afabfa05d55
protocol_hash=6d842c440ce514e1d5a99c748a2f456e54e9a3e541dba9197a96b1a754315c2f
feature=mean of twelve completed 5m premium-index closes
normalization=past 168 completed hours only
signal=-zscore(premium); entry=abs(z)>=2
execution=hold 6h, cash 18h, no direct flip
cost=5bps taker + 2bps slippage per position change + funding
pass=min 2/3 ETH/BNB/SOL pass IC/net-residual/filter/turnover gates
reserved_oos=2024-04, consume only after discovery passes
trials=1
```

最终 strict-parser 重放结果：

| symbol | rank IC | entries | max 24h turnover | net beta residual | verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| ETHUSDT | -0.046471 | 37 | 2.0 | -0.863166% | block_discovery |
| BNBUSDT | -0.001891 | 34 | 2.0 | -8.707943% | block_discovery |
| SOLUSDT | +0.045684 | 33 | 3.0 | -1.153916% | block_discovery |

SOL 的正 IC 没有转化为成本后正收益，且末段新仓在窗口结束被强制平仓后使 rolling turnover 超预算；按冻结
合同不能删除该边界成本。final report `20260716T102358Z-alpha-agent-premium-dislocation` 为 0/3 pass、
positive IC 1/3、positive residual 0/3、median IC `-0.001891`、mean residual `-3.575008%`，April
`reserved_oos_consumed=false`。宽松 parser 阶段的 `102040Z/102123Z/102135Z` 数值相同，只作中间证据；
最终结论只引用 strict parser artifacts。

premium 单源到此停止，不改 polarity/threshold/holding。下一源为 official daily `bookDepth` 聚合深度，但
必须保持语义边界：CSV 每约 30 秒给 `±1%..±5%` 的累计 depth/notional，不含 update ID、price level 或
`U/u/pu`，不能用于订单簿 replay。只读边界日 audit
`20260716T102632Z-alpha-agent-historical-microstructure` 已确认 2024-01-01/02-01/03-01 四币 12/12 包
available；1 月 1 日四币压缩合计约 `1,813,245 bytes`。下一轮先实现逐 snapshot 完整性审计和 5m
`1% bid-vs-ask notional imbalance` 聚合，再在看 return 前冻结唯一低换手方向合同。

### 2026-07-16 Aggregate Depth And Residual-Trend Model

历史 `bookDepth` 数据层严格保留语义边界：每个约 30 秒 snapshot 必须恰好有
`-5,-4,-3,-2,-1,+1,+2,+3,+4,+5` 十行累计百分比 depth/notional；负百分比作为 bid、正百分比作为 ask。
loader 不保留千万行 CSV，而是逐 archive 流式计算 5m：

```text
depth_imbalance_1pct=(bid_notional[-1]-ask_notional[+1])/(sum)
depth_imbalance_5pct=(bid_notional[-5]-ask_notional[+5])/(sum)
depth_imbalance_1pct_std=within-5m snapshot dispersion
near_depth_share=(bid[-1]+ask[+1])/(bid[-5]+ask[+5])
```

最终数据证据：

```text
artifact=20260716T104132Z-alpha-agent-historical-depth
archives=364/364 checksum verified
compressed_bytes=165,500,458
five_minute_rows=104,768
per_symbol=26,192/26,208; coverage=0.999389; segment_count=8
replayable_dataset=true; replayable_l2=false
data_hash=31110377aed36f856dbc4bc570d6d43b36e551b5c7555bbbf998d0015a4edb41
```

四币共同缺 16 个 5m 桶，分布在 7 个短区间；完整小时要求 12 个桶且同 segment，不能跨 gap 合并。

用户提出趋势/模型预测后，没有绕过 A10 gate，而是先冻结 A10 前 tabular baseline：

```text
preregistration=20260716T104401Z-alpha-agent-residual-trend-model
contract=depth_premium_price_logit_l2_h6_low_turnover_v1
contract_hash=a729ea39e7cf88b0fcb1857e795c67554a6ef1934adb4391953783168a20d979
protocol_hash=be9f21231d44cd5247f8756bce882729c8a0e9e16ba50c8ee2a158a53a477646
target=P(forward 6h BTC-beta-residual return > 0)
model=StandardScaler + LogisticRegression(L2,C=1,lbfgs,max_iter=2000)
features=depth imbalance 1%/5%, depth dispersion, near-depth share,
         premium mean, mark-index basis, completed 1h/6h return, 24h vol, BTC 6h return
train=2024-01-01..2024-03-01; purge=6h; test=2024-03
execution=p>=0.55 long, p<=0.45 short, hold6h/cash18h, no direct flip
validation=AUC + Brier-vs-train-base-rate + residual rank-IC + 5-fold TimeSeriesSplit(gap=6)
trials=1; no feature/model/threshold search
```

March OOS 结果：

| symbol | AUC | residual rank IC | Brier improvement | CV +IC folds | entries | max 24h turnover | net residual |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ETHUSDT | 0.484692 | -0.004346 | -0.018288 | 2/5 | 29 | 2.0 | -17.444056% |
| BNBUSDT | 0.500214 | -0.019693 | -0.011088 | 4/5 | 30 | 3.0 | -8.485764% |
| SOLUSDT | 0.514279 | +0.051771 | -0.005436 | 3/5 | 30 | 3.0 | -7.127153% |

三币 March Brier 都劣于只输出 train positive-rate 的常数模型；SOL 的连续 residual IC 为正，但方向 AUC
未过 `0.52`，概率未校准，且成本后仍负。daily residual DSR 为 `0.094571/0.243385/0.299464`；单一固定
模型 PBO 不可识别，继续 fail closed `1.0`。final report
`20260716T104522Z-alpha-agent-residual-trend-model` 为 passing `0/3`、positive residual `0/3`、mean residual
`-11.018991%`、April 未消费、A10 sequence disabled。

读法：现在已经具备真正的 research model pipeline，包括 point-in-time feature store、purged time split、
概率/校准、walk-forward、可重放 scaler/coefficients、成本/funding/filter 回测；“能训练模型”已经解决。
“模型有可交易预测力”仍被证伪。不能在同一 Q1 换 HGB/LightGBM/Transformer 或调概率门追结果；下一次
模型升级必须先有新独立信息或新未读窗口，并把 cumulative trial count/PBO 一并带入。

### 2026-07-16 Frozen Model Temporal Replay

没有在已看 2024Q1 上换模型或调参。时间复验只回答一个更窄的问题：保存下来的三套固定 Logistic 参数能否
跨一年维持预测方向和成本后 residual。任何正结果都不能抹掉原 March anchor 的失败，也不能恢复 promotion。

结果读取前冻结：

```text
preregistration=20260716T125427Z-alpha-agent-residual-trend-replay
protocol=frozen_residual_trend_temporal_replay_2025q1_v1
protocol_hash=2f15b7af782c8a7ea1a1bfda883278aaa50f42b3d8144b4c0bb9f24da2cfcbfe
window=2025-01-01..2025-04-01
anchors=exact ETH/BNB/SOL artifact SHA-256
prediction=manual saved-scaler transform + saved coefficients/intercept sigmoid
forbidden=fit, recalibration, feature selection, threshold tuning, model-family search, symbol dropping
execution=original p>=0.55/p<=0.45, hold6h/cash18h, 7bps per change, funding
promotion=always false; PBO=1.0 fail-closed; A10=false
```

官方数据审计：

```text
metadata_probe=396/396 HTTP 200
depth=20260716T130420Z; 360/360; 162,843,538 bytes; coverage=0.999421
premium=20260716T130534Z; 36/36; 7,443,575 bytes; coverage=1.0
hourly_price_min_coverage=1.0
feature_coverage=0.997674 each symbol
filter_coverage=1.0 each symbol
```

冻结模型 2025Q1 结果：

| symbol | AUC | residual rank IC | Brier improvement | entries | max 24h turnover | DSR | net residual |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ETHUSDT | 0.502287 | +0.012601 | -0.010654 | 87 | 3.0 | 0.007971 | -42.209377% |
| BNBUSDT | 0.462687 | -0.066387 | -0.011183 | 81 | 3.0 | 0.130511 | -13.971742% |
| SOLUSDT | 0.515403 | +0.005188 | -0.006259 | 87 | 3.0 | 0.066449 | -41.020445% |

final report `20260716T131339Z-alpha-agent-residual-trend-replay` 为 supportive `0/3`、positive residual
`0/3`、mean residual `-32.400521%`。三个模型的 Brier 都不如各自保存的 train positive-rate 常数预测；
即使 ETH/SOL rank IC 略正，也都低于原 `0.02` 门且未转化为成本后收益。固定 residual-trend 模型已同时在
March anchor 和 2025Q1 时间复验失败，到此关闭。下一条模型线必须先更换信息集合或预测目标，而不是继续
换年份、调概率门或升级 HGB/LightGBM/Transformer。

### 2026-07-14 S3 Collector Data-Smoke

实现保持 research-only：只访问 Binance USD-M public websocket 与 public depth snapshot，不读取账户
凭证、不访问私有 endpoint、不写 paper/live state、不输出订单或权重。

- `src/qount/alpha_agents/live_collector.py`
  - 按 public/market route 采集 `bookTicker`、`aggTrade`、100ms diff-depth 和 `forceOrder`，原始事件写
    gzip JSONL，并记录 config hash、raw SHA-256、event/receive time。
  - depth snapshot 默认走 public WebSocket API；瞬时失败有限重试并写 `snapshot_retry`，重试耗尽后
    才写 `snapshot_error`，默认最终错误率门槛保持 `1%`。
  - gap audit 检查 aggTrade id、bookTicker 顺序、depth `pu/u` 连续性、snapshot anchor/resync、buffer
    overflow、future/stale event 和连接错误。
  - replay audit 用 Decimal 档位实际应用 snapshot + diff，报告非法价量、空簿、crossed book、应用更新数
    和每个 symbol 的最终 top-of-book；不再只凭 update-id 链声称 replayable。
- `scripts/research/alpha_agents/alpha_agent_live_collector.py`
  - 默认流对齐 S3 为 `bookTicker,aggTrade,depth,forceOrder`；暴露 snapshot retry 次数/延迟和严格错误率。
- `tests/test_alpha_agents_live_collector.py`
  - 覆盖流路由、标准化、gap/乱序/future event、snapshot retry 成功/耗尽、gzip replay、订单簿应用和
    crossed-book 阻断。

最终实采命令：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_live_collector.py \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT \
  --duration-seconds 60 \
  --snapshot-interval-seconds 15
```

最终 artifact：

- `state/research_runs/20260714T093402Z-alpha-agent-live-collector/alpha_agent_live_collector.json`
- raw：`state/research_runs/20260714T093402Z-alpha-agent-live-collector/events.jsonl.gz`

读数：

```text
market_events=23,339 (bookTicker=20,524; aggTrade=833; depth=1,981; forceOrder=1)
snapshots=16/16; retry=0; final_error_rate=0
aggTrade sequence=829; missing=0; out_of_order=0
depth sequence=1,915; breaks=0; resyncs=0; unanchored=0
depth replay_updates=1,919; invalid=0; empty=0; crossed=0
event_time missing/future/stale=0/0/0; p95 bucket=500ms
verdict=pass_data_smoke
```

public route 第一次连接在 `connection_open` 前出现一次 `SSLEOFError`，第二次建连成功并持续到 deadline；
因此没有 market gap，audit 仍通过。此前 `20260714T092326Z` 严格复现暴露首次 snapshot EOF，推动有限
重试实现；`20260714T092617Z` BTC 和 `20260714T092732Z` 四币预验证也通过，但最终结论以上述
`093402Z` 原生包含实际 replay 指标的 artifact 为准。

结论仅是实现/短时数据质量 smoke：计划要求的连续 7 天尚未开始，不能把 60 秒数据用于训练、IC、
scorecard、paper 或 live。下节已继续固化长跑 session 合同，并发现 restart-per-segment 连续性 blocker。

### 2026-07-14 S3 Resumable Session Contract

新增 `src/qount/alpha_agents/live_collector_session.py`，把长跑数据完整性与单段 collector 分开：

- session contract 固化 collector 参数、计划总时长和 segment 时长，并写 SHA-256 contract hash；resume
  从 manifest 读取冻结参数，不接受运行时漂移。
- segment 默认按 UTC 午夜裁剪；单段 `events.jsonl.gz.partial` 只有在 capture 完成后才原子 rename，summary、
  session manifest 和 `daily/YYYY-MM-DD.json` 同样原子写入。
- `.collector-session.lock` 防止同目录双写；同主机死 PID lock 自动留为 stale 证据后恢复。
- `--max-segments` 可有意暂停，`--resume-session-dir` 从已完成时长继续；失败段的 partial/final raw 不删除，
  作为 `orphan_files` 保留并阻断 session。
- session 汇总 segment verdict、raw bytes/events、snapshot retry/error、trade gap、depth break/replay、
  event-time 和跨段 wall-clock gap。`boundary_gap_present`、orphan 或任一 segment block 都 fail closed。
- 该版连接模式明确写为 `segment_connection_mode=restart_per_segment`；它是诊断/恢复基线，不是最终连续
  collector。

暂停/恢复 smoke：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_live_collector.py \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT \
  --snapshot-interval-seconds 5 \
  --session-duration-seconds 30 \
  --segment-duration-seconds 15 \
  --max-segments 1

PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_live_collector.py \
  --resume-session-dir state/research_runs/20260714T094828Z-alpha-agent-live-collector-session
```

artifact：

- `state/research_runs/20260714T094828Z-alpha-agent-live-collector-session/alpha_agent_live_collector_session.json`
- 两段各自 `pass_data_smoke`；合计 23,288 events、724 replay updates、4 snapshot retries 后 0 final error；
  raw SHA 全匹配、离线 replay parity 全通过、无遗留 partial/lock。
- 人工暂停造成 `boundary_gap_max_ms=25,612`，session 正确
  `block_data(boundary_gap_present)`，不是连续数据证据。

不暂停、自动跑两段的 kill-test：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_live_collector.py \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT \
  --snapshot-interval-seconds 5 \
  --session-duration-seconds 30 \
  --segment-duration-seconds 15
```

artifact：

- `state/research_runs/20260714T100453Z-alpha-agent-live-collector-session/alpha_agent_live_collector_session.json`
- 两段各自 `pass_data_smoke`；合计 15,522 events、919 replay updates；snapshot final error、段内 trade
  gap/depth break、invalid/empty/crossed book、event missing/future/stale 全为 0；两段 SHA/replay 复核通过。
- capture 现记录每条 route 的首末市场事件时间；仅关闭前一 collector、等待 snapshot worker、写 manifest、
  再启动下一 collector就产生 public `6,277ms`、market `7,499ms` boundary gap；session 按合同
  `verdict=block_data`、`continuous_gate_eligible=false`。

早期 `20260714T095422Z` 使用 capture 函数返回时间，只读到 `82ms`，会被 deadline 后等待 snapshot
worker 的时间掩盖，已由 `100453Z` route-coverage 口径取代，不作为连续性结论。

结论：atomic/resume/daily manifest plumbing 通过，但 restart-per-segment 被连续性 kill-test 否定。
该负向基线已由下节的 continuous in-stream rotation 取代；旧 restart 模式不再用于 7 天任务。

### 2026-07-14 S3 Continuous Writer Rotation And 7-Day Run

`live_collector.py` / `live_collector_session.py` 已把 session capture 改成一个进程内的连续数据流：

- public/market websocket 只在真实网络错误或总 session 结束时重连/关闭，正常 segment 边界保留同一
  connection id；新 raw 写入 `connection_continuation`，不伪造 `connection_open`。
- writer rotation 在同一写锁内完成旧 gzip close、`.partial -> .gz` rename、新 gzip open，边界不存在
  writer=None 的丢事件窗口；writer generation 变化会让 depth route 立即补一轮新 snapshot。
- 每段固化 aggTrade、bookTicker、depth 的 first/last sequence boundary；session 逐边界检查 aggTrade
  `last+1`、bookTicker 单调性和 depth `pu == previous u`。connection id 不同、任一序列 break、orphan 或
  单段 block 都 fail closed。
- 已关闭段的 gzip audit、订单簿 replay、SHA 和 artifact 写入由独立 spawn process 完成；父进程只原子更新
  session/daily manifest。首版同步 audit smoke 虽通过，但第二段 p95 latency 从 `250ms` 升到 `2.5s`，
  因此被异步版取代，不用于最终连续性结论。

最终双段命令：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_live_collector.py \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT \
  --snapshot-interval-seconds 5 \
  --session-duration-seconds 30 \
  --segment-duration-seconds 15
```

最终 artifact：

- `state/research_runs/20260714T112301Z-alpha-agent-live-collector-session/alpha_agent_live_collector_session.json`
- 两段各自 `pass_data_smoke`，合计 16,723 events、948 depth replay updates。
- `connection_restart_count=0`、`boundary_gap_total_ms=0`；trade/bookTicker/depth boundary break 全为 0。
- snapshot retry/final error、段内 trade gap/depth break、invalid/empty/crossed book、event missing/future/stale
  全为 0；两段 p95 latency 均 `250ms`，max 分别 `241ms` / `309ms`。
- 两段 gzip 完整、manifest SHA 与 `shasum -a 256` 一致，离线 `audit_event_file` 与已写 audit 完全相等。

旧 Mac 7 天 session（已被替代，仅保留为部分证据）：

```text
path=state/research_runs/20260714T112649Z-alpha-agent-live-collector-session-7d/
launchd_label=com.qount.alpha-collector-7d-20260714-v2
started_at=2026-07-14T11:27:20Z
planned_duration=604800s
segment_limit=86400s (UTC midnight clipping remains enabled)
status=superseded/incomplete
replacement=20260714T135630Z-alpha-agent-live-collector-session-7d-vps
```

新 VPS 7 天 session：

```text
remote_path=/root/qount-alpha/state/research_runs/20260714T135630Z-alpha-agent-live-collector-session-7d-vps/
service=qount-alpha-collector.service (active, Restart=no, boot-disabled)
started_at=2026-07-14T13:56:47Z
planned_duration=604800s
segment_limit=3600s (UTC midnight clipping remains enabled)
status=running/incomplete
expected_end=2026-07-21T13:56:47Z
offload=com.qount.alpha-collector-offload every 1800s
```

以上代码块是2026-07-14启动时的历史快照，不是当前运行状态。VPS collector后来失败并停止；2026-07-18
存储清理发现Mac offload LaunchAgent仍会每30分钟重建已迁移文件，已将其`bootout`并删除plist。当前
`com.qount.alpha-collector-offload`未注册，Mac `state/`保持约12KiB，后续不得按本段历史命令恢复。

VPS service 与旧 LaunchAgent 都明确 `Restart/KeepAlive=false`，不会在失败后自动重启。VPS writer 低于
8GiB 可用空间即 fail closed；Mac 低于 20GiB 时停止 offload 删除。每小时闭段只有在 Mac 完整 replay 和
两阶段 receipt 后才删除 VPS raw，审计 JSON 留在远端。旧 Mac partial 保留，禁止与新 session 拼接。
一次较早的
`20260714T112533Z-...-7d` 预启动使用 `launchctl submit`，发现其隐含 KeepAlive 后已立即停止；没有完成
segment，不作为数据证据。新正式 session 当前只证明进程、单写锁、offload 闭环和 partial raw 正常；
7 天 gate 尚未通过。

### 2026-07-14 S3 Deterministic Session Verifier

最终 data gate 不再靠人工组合 `jq` / `shasum`。`live_collector_session.py` 新增只读
`verify_live_collector_session()`，CLI 为：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_live_collector.py \
  --verify-session-dir state/research_runs/20260714T135630Z-alpha-agent-live-collector-session-7d-vps
```

默认合同：

- 至少 604,800 秒，session 必须 `complete`、0 remaining、0 resume、无 error history/lock/orphan。
- symbols 必须为 BTC/ETH/BNB/SOL，streams 必须为 bookTicker/aggTrade/depth/forceOrder；gap/stale/snapshot/
  connection thresholds 不得比当前 S3 合同宽松。
- session contract hash、recomputed aggregate、segment index/字段、daily manifest、UTC day grouping 必须一致；
  artifact/raw/daily 路径必须位于 session 目录内。
- 每段 actual bytes/SHA 必须同时匹配 session 与 segment artifact；默认重新运行 `audit_event_file`，订单簿
  replay 必须与冻结 audit 完全相等。
- 每段 connection error、snapshot final error、trade gap/out-of-order、bookTicker out-of-order、depth
  break/resync/overflow/invalid/empty/crossed/unanchored、event missing/future/stale 必须全为 0；每个 symbol
  必须有 bookTicker/aggTrade/depthUpdate 和 snapshot。
- `pass_data_gate` 返回 0；`incomplete` 返回 2；其他 `block_data` 返回 1。verifier 只读，不拿 session lock、
  不修改 manifest/raw，也不访问网络或账户。

实测：最终 30 秒双段 artifact 用 `--minimum-session-duration-seconds 30` 得到 `pass_data_gate`；不覆盖默认
最短时长时，同一 artifact 正确 `block_data(minimum_duration_not_met)`；正在运行的正式 session 正确返回
`incomplete`。单测覆盖通过、running、running+contract corruption、raw 篡改、畸形数字字段、path escape
和 boundary symbol 缺失，当前 Alpha `63 OK`、完整 `1002 OK`。该 gate 只验收同合同的连续 collector
artifact，不再阻断其他已做 checksum/schema/gap-segmentation 审计的历史 dataset；它仍不是
alpha/paper/live promotion。

### 2026-07-10 S1 Kline Taker-Flow Kill-Test

固定 `BTC/ETH/BNB/SOL`、USD-M 5m、2024-01..08、Jan-Jun train / Jul-Aug OOS，使用
runtime exchange rules、funding、taker fee 5bps、slippage 2bps 和 400 USDT min-notional 合同。
每个 horizon 跑 40 个 candidate：5 feature families × 4 lookbacks × 2 polarities，训练期按 rolling-beta
rank IC 选择，beta lookback 为 2016 bars（约 7 天）。

| horizon | selected | train rank IC | OOS rank IC | OOS beta | OOS net residual |
| --- | --- | ---: | ---: | ---: | ---: |
| 3 | `kline_taker_imbalance_lb3_inv` | 0.01993 | 0.03481 | 0.464995 | -166.019% |
| 6 | `momentum_lb24_inv` | 0.02349 | 0.02344 | 0.019812 | -91.363% |
| 12 | `momentum_lb24_inv` | 0.03678 | 0.01326 | 0.830903 | -58.191% |

h3 是唯一由新 taker-flow family 选出的候选，OOS IC 有弱正值，但 train IC 未过 `0.02`；更关键的是
Jul/Aug turnover cost 约 `199.64%/206.78%`，gross edge 被 taker 成本完全吞没。h6/h12 选择回到已知
price momentum inverse，未产生新 microstructure edge。三个 scorecard 均在 G2/G3/G4/G5/G6 block。

结论：S1 当前 sign/taker 执行合同触发 kill，不进 A10、paper 或 live。Jul-Aug 已经看过；以后若设计
sparse/no-trade threshold，只能作为新 discovery 设计，并必须使用新窗口或 walk-forward，不得把同一
Jul-Aug 复用成 promotion。walk-forward/DSR/PBO adapter 已完成并继续否定该候选；下一步转 S3
bookTicker/aggTrade/diff-depth/forceOrder collector，只做数据 gap/replay。

并发完整性补丁：同批并行 metrics 暴露秒级 artifact 目录覆盖，`persistent_research_dir` 已改为原子
分配 base/`-01`/`-02`，并新增同秒双写测试。该修复只保护 research artifact，不改变策略执行。
rolling beta/forward residual label 也已改为前缀统计一次性预计算；h3 同配置复跑约 37 秒，数值与
优化前 artifact 一致，为后续 walk-forward 避免重复的 2016-bar 窗口扫描。

### 2026-07-10 G4 Validation Result

新增 `alpha_agent_validation.py`：读取冻结的 feature artifact config，重放 40 个 candidate，并输出
紧凑 validation artifact。DSR 针对源实验实际选中的 candidate；PBO/CSCV 在每个 IS 组合内沿用源
`rank_ic` 选择规则，再按 OOS beta-residual Sharpe 排名；purged folds 使用双侧训练 + embargo，
walk-forward 使用 expanding prior-only 训练。

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_validation.py \
  --feature-experiment-path state/research_runs/20260710T132950Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json \
  --fold-count 5 --embargo-periods 1 --pbo-splits 10
```

最终 artifact：

- validation：`state/research_runs/20260710T134718Z-alpha-agent-validation/alpha_agent_validation.json`
- metrics：`state/research_runs/20260710T134758Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`
- scorecard：`state/research_runs/20260710T134808Z-alpha-agent-scorecard/alpha_agent_scorecard.json`

结果：

| metric | value | gate read |
| --- | ---: | --- |
| selected per-period Sharpe | -2.276393 | negative |
| DSR | 3.19e-152 | fail `<0.95` |
| PBO | 0.781746 | fail `>=0.5` |
| purged folds | 0/5 positive | fail |
| walk-forward folds | 0/5 positive | fail |
| largest contributor removed | -99.997476% | fail |

G4 blockers 为 `dsr_below_threshold`、`pbo_above_threshold`、`purged_cv_not_passed`、
`largest_contributor_removed_not_positive`；embargo 已正确应用。源 candidate replay parity 为 true。

第一次 `20260710T134252Z` validation 的 PBO 使用 Sharpe-selection，与源 rank-IC 选择不一致，已被
最终 `134718` source-selection CSCV 取代，不作为结论。读法：G4 plumbing 已可用，但 S1 仍被完整
反过拟合证据否定；不启动 A10、不 forward paper、不 live。

### Derivatives State Loader

2026-07-08 已实现 `derivative_state_v0` 数据层：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_derivatives_state.py \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT \
  --period 5m \
  --days 1
```

读取的官方 public REST：

- `/futures/data/openInterestHist`
- `/futures/data/takerlongshortRatio`
- `/fapi/v1/openInterest`

重要限制：Binance `/futures/data/*` recent data endpoints 官方只适合作近 30 天研究输入。它不能替代
2021-2026 长历史回测数据；长历史仍只能先用 public dump klines/funding。OI/taker ratio 进入
feature runner 前必须标记为 recent-history / forward-research 特征。

真实 smoke：

- `state/research_runs/20260708T045352Z-alpha-agent-derivatives-state/alpha_agent_derivatives_state.json`
- window：1 天，5m，BTC/ETH/BNB/SOL。
- `open_interest_hist_count=1152`
- `taker_long_short_count=1152`
- `current_open_interest_count=4`
- `error_count=0`
- 每个 symbol OI 与 taker ratio 均为 288 rows，0 gaps，coverage ≈ `0.9965`。

读法：

- 数据接入可用。
- 下一步是把该 artifact 接入 feature experiment runner，形成 `derivative_state_v0` 的 OOS returns。
- 已接入 feature experiment runner，但不能把它直接当 strategy promotion 证据；它只是 S2 的输入层。

2026-07-08 derivative-state feature smoke：

- 代码已支持 `--derivatives-state-path`、`--kline-source rest|public_dump`、`--min-feature-coverage`，
  以及 `oi_delta`、`oi_value_delta`、`taker_ratio`、`taker_imbalance`。
- 实网限制：当前 Mac 到 `https://fapi.binance.com/fapi/v1/klines` 直连超时/SSL EOF，未生成 REST
  kline 实网 artifact；该路径已有离线 fake REST 单测覆盖。
- public dump fallback：2026-07-08 运行时 Binance S3 已发布 BTC/BNB 的 2026-07-07 5m daily dump，
  ETH/SOL 同日文件仍 404，因此完整 BTC/ETH/BNB/SOL smoke 被 coverage gate 正确拦截。
- BNB 两币 smoke artifact：
  `state/research_runs/20260708T093014Z-alpha-agent-feature-experiment/alpha_agent_feature_experiment.json`。
  选中 `oi_delta_lb1_thr0_long_short`，`feature_coverage=0.113095`，OOS
  `strategy_total_return_pct=-7.056039`、BTC `+1.403648`、equal-weight `+1.135040`、
  `beta_to_btc=-0.000082`、`net_residual_return_pct=-7.301083`。
- beta metrics：
  `state/research_runs/20260708T093052Z-alpha-agent-beta-metrics/alpha_agent_beta_metrics.json`。
- scorecard：
  `state/research_runs/20260708T093102Z-alpha-agent-scorecard/alpha_agent_scorecard.json`，
  `verdict=block`，G2/G3/G4/G5/G6 阻断。读法：OI/taker ratio 接入链路可用，但第一刀
  derivative-state univariate smoke 没有 alpha；等 ETH/SOL dump 或 REST 直连恢复后，必须复跑完整
  universe，不能用 BNB 单窗负样本做 promotion。

## Promotion Scorecard

`alpha_agent_scorecard.py` 是当前第一层量化接入口。它不调用 LLM，不拉私有交易所数据，不写
paper/live state，只读一个 metrics JSON 并输出 gate 结果。

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_scorecard.py \
  --metrics-path tests/fixtures/alpha_agent_passing_metrics.json \
  --target paper
```

目标层级：

- `proposal`：只检查研究提案能否进入实验队列。
- `paper`：检查是否有资格成为 forward paper 候选。
- `live_pilot`：额外检查 dry-run、pilot cap 和 live 安全条件；不自动部署。

当前 gates：

| gate | 名称 | 必须证明 |
| --- | --- | --- |
| `G0` | proposal | `label_spec` / `benchmark_spec` / `data_spec` / `cost_spec` / `kill_line`，且必须是 beta-residual target |
| `G1` | data | point-in-time、as-of join、可重放、data/code/config hash、trial count、runtime exchangeInfo、filter validator |
| `G2` | baseline | residual net return > 0，并打败 cash / BTC B&H / TOP3 EW B&H / current live baseline |
| `G3` | cost | 扣 taker/spread/funding/min-notional 后仍正，worst-case 成本仍正，maker fill 不能靠假设 |
| `G4` | anti-overfit | DSR、PBO、purged-CV、embargo、去掉最大贡献窗口后仍正 |
| `G5` | breadth/capacity | effective breadth、相关性压力、容量检查 |
| `G6` | paper | validation_v1 / forward paper、30 天、0 schema/unmanaged/unknown filter、订单可 replay |
| `G7` | live pilot | 7 天 dry-run、pilot capital = 300 USDT、禁提现、one-way、isolated、rollback 已写 |
| `GX` | LLM boundary | LLM 不得生成订单、目标权重或风控 override |

这意味着 agent 可以提出实验，但只有 A10 / backtest / paper runner 产出的 metrics 能让 gate 通过。
若 metrics 里缺 `data_hash`、`trial_count`、`holdout_role`、DSR/PBO 或成本压力，默认 block。

## Metrics Contract

最小字段参考 [tests/fixtures/alpha_agent_passing_metrics.json](../tests/fixtures/alpha_agent_passing_metrics.json)。
真实实验输出必须把这些字段替换为实际 artifact 读数，不能手填“看起来合理”的值。

```text
proposal.*      研究预注册内容
data.*          数据血缘、as-of、hash、trial_count、exchange rules 来源
performance.*   beta residual 结果和 BTC beta
benchmarks.*    cash/BTC/TOP3/live baseline 对比
cost.*          扣费、最坏成本、min-notional、maker fill、funding
validation.*    DSR/PBO/purged-CV/embargo/最大贡献窗口移除
breadth.*       effective breadth、相关性压力、capacity
paper.*         validation_v1 / forward paper replay 质量
live.*          dry-run / pilot / API 安全条件
llm.*           LLM 是否越界参与订单、权重、风控
```

## Beta-Residual Builder

`alpha_agent_beta_metrics.py` 是当前第一个 deterministic experiment adapter。它读已对齐的
period returns，计算策略相对 BTC 的 beta、BTC beta-residual return、相对 TOP3 / current live
baseline 的超额，并生成 scorecard 所需 metrics。

输入行使用 percent points：

```json
{
  "meta": {
    "point_in_time": true,
    "as_of_join": true,
    "costs_included": true,
    "min_notional_coverage": 1.0
  },
  "periods": [
    {
      "ts": "2026-01",
      "strategy_return_pct": 2.0,
      "btc_return_pct": 1.0,
      "top3_equal_weight_return_pct": 0.5,
      "current_live_baseline_return_pct": 0.2
    }
  ]
}
```

运行：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_beta_metrics.py \
  --returns-path tests/fixtures/alpha_agent_returns.json \
  --holdout-role discovery \
  --source-label fixture-beta
```

读法：builder 只证明 G0-G3 的一部分。DSR/PBO、purged-CV、paper replay、capacity 等字段默认是
blocking value，必须由后续真实 quant artifact 补齐。示例 fixture 的 residual 是正的，但 scorecard
仍会在 G4/G5/G6 block，这是预期行为。

## Binance Public Returns

`alpha_agent_binance_returns.py` 复用 `qount.research_data.market_data` 的 Binance public dump loader，拉
`data.binance.vision` 的 spot / USD-M futures klines，生成对齐 returns。它不需要 Binance 私钥，
不访问账户，不写 paper/live state。

示例：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agents/alpha_agent_binance_returns.py \
  --start-month 2024-01 \
  --end-month 2024-03 \
  --symbols BTCUSDT,ETHUSDT,BNBUSDT \
  --strategy-symbol ETHUSDT \
  --market um \
  --interval 1d \
  --fast-window 10 \
  --slow-window 30
```

当前内置策略只是 `sma_long_cash` / `sma_long_short` 的 smoke candidate，用于验证数据和 gate
链路，不是推荐策略。输出 meta 会明确标注：

- `exchange_rules_source=binance_public_dump`
- `filter_validator_reused=false`
- `funding_included=false`
- `min_notional_coverage=0.0`

因此它即使 residual 为正，也会被 scorecard 的数据、成本和验证 gate 阻断，直到后续补 runtime
exchangeInfo、funding、真实 min-notional 和 OOS 统计。

## 2026-07-18 低频 Regime 与链上研究收口

本轮在个人`research_sandbox`中把“阶段标签 -> 分类/HMM/GRU -> 经济目标 -> 策略消融”完整走完，所有已看
历史统一标记`consumed_historical_discovery_pool`：

- 30日HMM经济风险分数与未来收益反向；12个HMM目标、40个直接经济回归和40个DVOL增强回归均0保留。
- 24个滚动适应trial中仅`h60_train365_base_random_forest`保留排序；10,000次确认通过7/7，但复用3个
  downside-only风险规则后0/3，最佳少赚12.216pp只改善0.878pp maxDD，价格/funding/DVOL模型家族关闭。
- Coin Metrics官方社区API在WSL直连并直接落外置盘，冻结MVRV、活跃地址、交易数、算力、交易所流入/流出
  六个原始字段，2020-01-01..2026-06-30共2373行、coverage 1.0。没有历史vintage，故只有latest-vintage
  discovery资格；SOPR、Realized Cap、NVT和LTH供给受限，未用近似字段替代。
- 首版链上审计错误包含2021-2022，保留为工程中间件并由v0.2废止。严格2023-2026的7个固定方向trial只有
  `hashrate_z90`通过5/5；加入原滚动RF的唯一模型trial通过9/9，rank IC 0.179447、高低组差9.252pp。
- 同一3个冻结风险规则再次0/3；最佳规则Sharpe提高0.0617、maxDD改善0.862pp，但总收益少4.795pp，超过
  3pp代价门，严格拒绝且不把门放宽到5pp。该阶段累计相关trial为131。
- H.4.1宏观source/ops G0已完成：289条官方release、三种archive layout、276个`release+1d`周特征、0未来
  join，稳定data hash `8af65a47...cb02`。固定4周变化和4周加速度分别8/8保留，13周变化7/8拒绝。
- 唯一宏观+算力融合trial为5/8，不超过4周宏观父模型；4周宏观复用三档风险规则仍0/3，最佳少赚
  `3.323pp`只改善`0.863pp` maxDD。累计trial为138，不放宽3pp门，不进入forward/paper/live。
- 新的低换手兑现假设在读取结果前固定为3个trial，只用H.4.1 4周变化的经济零阈值确认Base入场/总闸退出，
  不改日常风险目标。收缩阻止开仓在633根日线上介入、阻止1,358个symbol entry，收益从`+66.505%`降至
  `+1.722%`；扩张延迟总闸退出仅介入2根日线/4个symbol exit，收益`+64.089%`、Sharpe `0.8642`，风险
  改善不显著；双确认收益仅`+0.341%`。3个trial全部拒绝，累计trial为141。
- 为避免再次压低Base暴露，下一轮只冻结1个“边际boost否决”trial：现有60日RF年度fold OOS标准分数
  `<=0`时，仅撤销Funding Veto之后仍允许的strong-bull 2.0%增益，退回1.5%，不降低Base。1205日覆盖中
  449个可boost日有303个被否决；Funding Veto参考`+90.362%/Sharpe 1.2602/maxDD 18.102%`，候选只有
  `+65.072%/1.0950/19.264%`，相对Base也少`3.197pp`且回撤多`1.988pp`。Bootstrap Sharpe胜率仅6.90%，
  8/14门通过，拒绝并把累计trial更新为142。
- 随后的Base episode归因不计策略trial：77段持仓与组合净利润误差仅`0.00000002 USDT`；31个吊灯退出
  `+403.613 USDT`，38个单币趋势/配置退出`-56.610 USDT`，8个总闸退出`-80.981 USDT`。31日以上
  episode合计`+445.681 USDT`，30日以内合计`-179.660 USDT`，明确支持保留宽吊灯和长持有，而不是时间止损。
- 唯一通过机制样本门的是单币趋势退出。12次三日内快速重入后续合计`-22.024 USDT`，因此只复用既有3日
  止损冷却做1个预登记trial。候选收益/Sharpe/maxDD为`+66.805%/0.9079/17.277%`，略优于Base，订单少9；
  但Bootstrap三项胜率`58.96%/64.42%/55.88%`均失败，13/16门通过，拒绝并把累计trial更新为143。

当前角色定位：算力和H.4.1 4周变化都是可继续观察的低频排序信息，不是订单/仓位信号。`model_trainer`只
保留dataset、预测和复跑hash；`backtest_auditor`已对两条策略映射给reject；`risk_architect`不得调风险阈值
救援。H.4.1已解决历史发布时间与可见时点，但事件驱动不等于有效兑现：符号状态太持久，不能压成二元
开仓许可；它也不能管理strong-bull边际风险。Base自身只保留“长趋势+3xATR”骨架，信号退出冷却不得用
2/4/5日扫描救援。Coin Metrics future vintage链已开始；后续仅用新append数据
做future-only复核，宏观留在只读预测/解释层，不再扫描当前特征的分位、窗口、分数阈值、持有期、冷却或
投票阈值。

本轮随后没有新增第144个策略trial，而是修复真正前向所需的数据链路：新增WSL公开UM输入刷新层，把下载与
冻结shadow回放物理隔离。2026-07-22磁盘修复后，外置盘canonical日线已推进到`2026-07-21`，共
`105 files/84,368 bytes`、content hash=`30fab795...66da`；Binance Vision归档缺失为0。但当前月funding REST
从WSL到五个官方USD-M域仍全部超时，`data-api.binance.vision`对该endpoint返回404，完整度仍为0/3。
冻结双状态合同从`2026-07-19`启动，但因funding不完整仍0根evaluation、未读取收益、无journal，verdict
`await_complete_shadow_inputs`。空响应和缺日继续fail closed，不能从VPS、LLM或0填充替代canonical输入。

随后按owner授权启用仓库外良心云标准代理。首次隔离core沿用了到期的2026-06测试副本并在TLS阶段失败；最终从
当前良心云profile结构化派生47个真实节点，排除3个流量/到期伪节点，保留独立`17907`端口与随机认证，主Clash未改。
TCP、标准HTTPS与Binance funding公共接口均返回200后，同一refresh合同补得BTC/ETH/BNB各64次结算、完整度`3/3`，
108 files、0 unavailable，dataset manifest=`b6f6aab8...ca05`。冻结v0.2 preregistration、Base、state-decay、
50% veto阈值和成本合同均未改；离线回放得到`2026-07-19->20`、`2026-07-20->21`两个完整pair，verdict=
`collect_shadow_forward`。两路径仍为`bear_cash`、0 active bar/0 order/0收益/0回撤，funding coverage和journal coverage
均为1.0，但还缺60个完整pair、每路径10 active bar和至少1次veto。它只把真正前向从“无输入”推进到“开始收集”，
不支持参数调整、盈利结论、promotion、paper或live。

为确认恢复后证据链可重放，同一冻结历史合同在WSL离线复跑，trial增量保持0。旧报告字段规范化hash同为
`d4bec779...00d91`；Funding Veto全窗`+88.950393%/Sharpe 0.965235/maxDD 18.105121%`，交易成本
`34.003616 USDT`、funding PnL `-43.423732 USDT`。新增只读beta残差后，对BTC 1x与TOP3等权1x的beta/复合
残差分别为`0.151612/+59.459570%`、`0.147028/+55.411085%`。原预登记5000路径、20日循环区块Bootstrap也
精确重现，规范化hash=`6c00d310...f1c81`，三项胜率仍为`58.90%/86.82%/75.72%`，终值收益增量中位数仅
`+0.462935pp`。这些全部是`consumed_historical_discovery_pool`，不提升Funding Veto层级。下一步不是继续扫
历史参数，而是通过仓库外良心云标准代理配置或未来不可变官方月包补funding，等待首个完整decision/outcome
pair后原样追加双状态journal。

Owner随后提出一个月小资金实盘。该目标进入`paper_live`治理而不是新增历史trial：真钱策略只允许Base v0.2，
全局2.0%风险档与Funding Veto只做shadow；资金固定300 USDT、1x逐仓、gross<=1、无账户单日止损、10%试点
累计回撤熔断。VPS审计发现旧cron停用，旧live guard随后已关闭；显式代理路由失效，绕开代理后旧key返回
`-2015`。readiness v0.3补齐私有账户安全门、7天dry-run和独立runtime验证后共20项阻断，故当前工作重点是
独立执行器/日志、私有预检、paper/dry证据，不是继续调信号或恢复旧生产任务。

随后先实现了完全不接私有API/订单的独立UM paper runtime：Base v0.2从300 USDT现金启动，200根历史只作
signal warmup，价格连续且每日TOP3 funding各3次才追加hash-chain journal；不设账户单日止损，10%试点累计
回撤会halt。v0.3又在每根Base日志内并行保存全局2.0%风险档和Funding Veto的完整状态，但二者不控制订单。
canonical首跑因最新日`2026-07-17`早于`2026-07-19`起点而为0天，说明前向门未被历史数据绕过。dry/live
发单执行仍未实现或验证，`independent_runtime_verified`保持false。

## 2026-07-19 固定本金动作标签与美股映射加密资产

Owner把“定投定减、历史买卖标签、加密市场中的美股对应资产”加入个人实验研究。本轮先做两个互相独立的
deterministic discovery，不改变Base v0.2、paper或VPS执行：

1. `periodic_allocation.py`固定300 USDT本金，BTC/SPY按周25%阶梯，TOP3因最小名义价值按周50%阶梯；不外部
   注资、不做空、gross不超过1。均线DCA/DCR在BTC/TOP3/SPY分别为`+51.52%/+46.81%/+62.19%`，低于各自
   buy-and-hold的`+87.40%/+104.91%/+82.47%`。未来20根triple-barrier只作为buy/hold/sell目标，所有特征
   point-in-time；按年扩展Walk-Forward且按`label_end_date` purge。Logistic/HGB共六个模型全部在平均Brier和
   log-loss上输常数先验。TOP3 HGB的`+216.99%`因4/4 Brier折失败、收益集中2025且2026为负而明确拒绝。
2. 市场结构盘点把产品分成三层：Binance `*B`映射spot、Bybit xStocks spot属于tokenized/mapped claim；
   Binance `TRADIFI_PERPETUAL`与Bybit equity linear是合成衍生品。发行/托管/赎回风险与funding/清算风险不能
   共用一个“美股币”标签或成本模型。Binance 11个TradFi永续均在2026年1-4月才上线，历史极短。

首个结构假设选择周末/非现金时段偏离：Binance TradFi永续在美股休市时仍有小时成交，因此冻结“周末跌幅
为负则下一美股现金时段做多收敛、现金收盘退出”的long-only规则。纽约DST、SPY现金交易日历、24bps往返成本、
funding和同日总gross=1均显式进入回测。126个symbol-event只有18个独立cash date；日期等权聚类结果为
`+3.7516%`、maxDD `4.0029%`、bootstrap `P(mean>0)=71.16%`。早期把同日多个标的逐笔顺序复利得到的
`+29.69%`属于重复计资，已作废并由日期聚类实现和单测替代。

当前结论：定投/定减与动作分类没有产生可接策略；TradFi周末回归有经济解释但统计证据不足。ML/神经网络在
18个独立事件上没有合理有效样本量。下一步只追加真实未来周末，并构建point-in-time的Binance perp、Binance
`*B` spot、Bybit xStocks spot与Bybit linear同步basis panel；先检查锚定误差、周末漂移、开盘收敛、跨场所
lead-lag、funding与真实可成交成本，再决定是否冻结paper候选。不得安装collector/cron或接入订单，除非owner
对具体运行明确授权。

Owner随后把计划资金提高到1000 USDT并要求多策略+LLM信息架构。统一合同写入
`docs/crypto-portfolio-system-plan.md`：Base是控制和生存sleeve，Equity Mapping、LiquidTrend、Funding Event
分别维护独立虚拟NAV，组合allocator最后统一gross/标的/相关簇/保证金约束；未晋级sleeve的真钱风险预算为0。

LiquidTrend10先执行trial=0的G0，而不是直接跑收益。固定十币UM历史的bar/funding/quote-volume均具备研究容量，
但平均绝对相关`0.661578`令有效广度只有`1.437979`，三个阶段均低于2；旧runtime规则又只覆盖4/10。结论是
原始z-score排名合同不启动。首个候选的预处理已在看PnL前改为并冻结为robust rank；后续若继续，应改变为BTC/行业残差、
真正不同的信息源或跨产品结构，而不是增加币数或调相关阈值。

LLM信息侧新增`alpha_agents/information_events.py`：LLM只抽取官方来源事件，确定性validator约束source域、三时点
顺序、实体、事件类型、numeric fields、source hash、重复和forbidden trade language。feature row不包含摘要文本
或可执行字段。该模块是信息研究入口，不是AgentReport直接转信号的通道。

2026-07-19治理加固后，账户低于3000 USDT最多一个连续型live候选和一个事件型最小试单；所有sleeve并行维护
Signal/Standalone Executable/Portfolio Realized三类NAV，晋级只看Standalone。每个机制假设族最多3个冻结正式
trial；查看前向结果后改规则会使该时间段立即降为consumed。Base 60根日线只作运行证据，Equity Mapping按独立
美股交易日、Funding按拥挤episode、LiquidTrend按调仓日和市场阶段计数。LLM未来90天只维护schema、allowlist、
6个fixture和泄漏测试，不做大规模抓取或叙事收益特征。

### Equity Mapping G0受限红队

`mini_trend_equity_mapping_red_team.py`把本地G0合同、组合容量区段和测试清单分别做file/excerpt hash后交给
`red_team`角色；输入有42,000字符上限、严格五字段JSON、无tools、并发1、SDK重试0、`trust_env=false`，artifact
固定`orders_allowed=false/paper_or_live_allowed=false`。这不是让LLM设计交易，而是检查point-in-time和单位语义。

三次有效terra审阅只作为问题线索。经确定性复现后，v0.3修复了：中点负偏离不代表bid/ask可成交、公司行动因子
未用于单位归一化、同一经济事件的不同证据修订会膨胀asset-event、压力比例没有时点/来源/成本成分、报告信任外部
event id、cash/USDT报价venue未绑定。模型对真实USDTUSD方向、公司行动factor方向和官方交易日历例外的意见仍是
假设，必须等待官方文档与真实同步fixture，不能由语言模型结论替代。

最终G0只用2行合成fixture验证管道，得到1个独立cash date和
`collect_equity_mapping_independent_dates`；没有未来收益、PnL、shadow execution或strategy trial。旧TradFi的18个
独立日期缺少同一时点的cash premarket、USDTUSD、公司行动和stress provenance，不能直接升级为v0.3证据。

随后G0升为v0.4，并补`equity_mapping_raw_collection_v0.1`。真实point-in-time输入不再只信任结构化字段：必须
引用同现金日sealed manifest，逐项覆盖instrument mapping、mapped/cash/USDTUSD三腿、cash calendar、corporate
action、event context和stress scenario的原始response-body SHA-256；CLI会先回读raw bytes，manifest或任一hash
不匹配即阻断。bundle按`cash-date/batch-hash`内容寻址，修订只新增、不覆盖。首个目标现金日`2026-07-20`的
readiness为`await_collection_window`，冻结窗口是纽约`09:24:30-09:25:00`；目前仍无真实样本、PnL、shadow
execution或第144个trial。该层只负责provider-neutral intake/sealing，不主动抓取或解析报价。

其外新增独立的`equity_mapping_source_capacity_v0.1` adapter/audit层，只做bounded公开小探针且
`trial_count=0`。Binance exchangeInfo/bookTicker parser要求TRADIFI perpetual映射和server `time`；Bitstamp
USDTUSD parser要求`microtimestamp`；Nasdaq market-info必须把目标现金日绑定到09:30-16:00 session，cash quote
必须同时为real-time、可执行bid/ask且有不晚于availability的quote-event timestamp；split/earnings不得从未限定日期的
rows推断“无事件”。artifact `20260719T065611Z-equity-mapping-source-capacity`（SHA-256
`ee0799d7...09d58`）只通过cash calendar。当前Mac无代理路线下Binance及四个USDTUSD venue为
`transport_unavailable`；Nasdaq quote/split/earnings均语义阻断，stress source未分配，所以7/8 required roles失败。
这不能证明不可达provider永久不可用，也不能用HTTP receipt time代替market quote time；cash premarket leg仍是
首个真实窗口的绑定阻断，未运行collector、未创建market event、未授权shadow/paper/live/order。

## 2026-07-25 Crypto-First Factor Expansion And Trial 145

Owner将主动研究预算切回加密因子拓展。Alpha Agents后续只负责假设提案、数据源图、反例和结果审查；确定性代码
继续生成特征、权重、成本、funding、NAV、beta residual和trial verdict。CTA-R与C×D证据冻结保留，不再是当前P0。

2026-07-25后续文档修订把研究队列扩展为四个工作篮子；这只是设计更新，没有新实现、回测、trial或artifact：

- **现有低频核心**：`multi_speed_trend_v1`、`market_breadth_dispersion_v1`、
  `liquidity_capacity_meta_v1`、`cross_sectional_residual_momentum_v1`、`crypto_vol_crisis_state_v1`、
  `funding_crowding_meta_v1`。
- **当前起点前向结构**：`oi_flow_forward_v1`、`basis_curve_dislocation_v1`、
  `liquidation_cascade_forward_v1`、`cross_venue_price_discovery_v1`。官方OI仅最近1个月，basis、taker和long/short ratio
  仅最近30天；agent不得建议把它们拼成长历史。
- **外部PIT与事件**：`stablecoin_liquidity_impulse_v1`、`token_supply_event_v1`、
  `network_adoption_quality_v1`、`venue_rule_event_v1`、`calendar_session_v1`。总稳定币供应和hashrate已有本地负证据，
  新proposal必须改变信息集、vintage或经济目标，不能只换字段名。
- **执行与组合条件项**：`execution_fill_cost_v1`、`options_surface_state_v1`、`regime_allocator_meta_v1`。
  options-DVOL与surface容量仍被阻断；allocator必须等至少两条冻结Standalone NAV，不得先优化权重制造组合收益。

每个family由Agent生成的唯一可接受交付是`ResearchCard`草案，至少包含：

```text
economic mechanism and causal sign
novelty versus qount negative evidence
official/primary sources and exact identity
event/published/available/observed decision clock
history availability and revision policy
independence unit and outcome horizon
features, missingness and eligibility
baseline, primary metric and beta residual
cost/stress plan and kill tests
allowed sensitivities and family trial budget
capacity and promotion blockers
```

Agent输出按以下审查链流转：

```text
Hypothesis Miner
-> Source Librarian
-> Data/Clock Skeptic
-> Economic Reviewer
-> Replication Designer
-> Red Team
-> owner/deterministic preregistration
```

- Hypothesis Miner每次只提出一个可与旧失败区分的因果问题，不输出参数网格；
- Source Librarian优先正式DOI、NBER/BIS和交易所官方仓库，Crossref只做身份发现；
- Data/Clock Skeptic对最新vintage回填、幸存者偏差、事件修订、30日短历史和重叠标签有否决权；
- Economic Reviewer强制说明收益是market beta、momentum、size、carry、liquidity补偿还是无法解释残差；
- Replication Designer给出最便宜的G0或kill test，不以“完整模型”作为第一步；
- Red Team必须列出能够推翻假设的结果，不能只给改参数建议。

一手来源种子已核对到TSMOM、trend century、momentum crash、volatility-managed portfolios、crypto market/size/momentum、
crypto network/attention、cross-venue segmentation、BIS Crypto Carry、Amihud/Corwin-Schultz、DSR/PBO和Gu-Kelly-Xiu。
这些来源只支持机制/方法；任何agent不得把论文中的Sharpe、显著性或结论改写成qount可复制alpha。Binance官方Public Data
和模块化connector只支持字段、archive和历史限制事实；本地实际dataset仍须独立hash、缺口、revision和PIT审计。

Trial 145已先写无结果预登记protocol=`304bc24d...14ec7`，再读取本地TOP3 UM `2020-02..2026-06`缓存。
方向一致性候选的Standalone proxy NAV/CAGR/Sharpe/maxDD为`2.7966x/19.25%/1.399/11.20%`，同窗Base为
`2.8836x/19.88%/1.416/16.18%`。候选降低回撤`4.98pp`，TOP3 beta-residual CAGR=`10.91%`，双倍成本和
一根延迟仍为正，但turnover约为Base的2.15倍且主指标未超过Base，因此8/9门通过仍拒绝。bundle=
`d4ca0c3eaa82e15674a1d83bf803aa7078f730d00856670451767577b1d50cb8`，formal strategy trial累计为145。

Agent不得建议修改Trial 145的20/60/120、投票或慢门救援。下一项允许提案的是Trial 146连续forecast的固定尺度、
标准化、裁剪和权重，以及breadth、liquidity、residual momentum、危机和funding五个G0的数据/容量kill tests。
前向篮子只允许schema、source和独立窗口设计；外部PIT篮子只允许source-capacity。任何报告仍固定
`orders_allowed=false/live_changes_allowed=false`。

## 红队补丁队列

v0.1 已经能组织角色和任务，但 report contract 仍偏软。下一轮必须补：

- 扩展 `AgentReport` validator，进一步强制 source 绑定和 artifact 引用。
- 继续按新报告语料扩展 forbidden output scanner；2026-07-22已补下单、买卖、开/加/减/平仓、做多/做空、
  杠杆、实盘/交易开关、目标权重和仓位动作，仍需防范间接或变体指令。
- artifact 绑定：每个 quant 结论必须带 data hash、code version、config hash、trial count、
  `holdout_role`。
- `PromotionJudge` 可继续扩展到读取真实 backtest/model artifacts，而不是只读聚合 metrics JSON。
- A10 训练输出只能是 model artifact + OOS scorecard，不能直接进入 VPS runtime。
