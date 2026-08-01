# qount 当前状态

> **状态**：active｜**权威**：L1 当前事实（#1）｜**最后更新**：2026-08-02
> **本文回答**：当前生产事实、能力边界、运行状态、下一步、硬边界。
> **TL;DR**：所有 live timer、授权、arm 和订单权限仍关闭。Dual-Engine 已按 owner 授权从 2026 年初生成四账户公共行情模拟曲线并部署 Dashboard；四账户各有 217 个点，两个 paper timer 继续从历史回放末端向前推进。

更新时间：2026-08-02

VPS基础生产版本：`0.2.27`，基础 commit=`66034b0da5e25a2a08feb901e42355e6d3e77595`；Dual-Engine 当前
program=`1.1.0`、overlay content hash=`05258e5e...a8b1`，逐文件清单与验收记录保存在
`/var/lib/qount/deployments/dual-engine-ytd-curve-v1-20260802/`。基础 release 的 commit、provenance 和 verification 仍保存在
`/root/qount/.qount-release-provenance.json`及`.qount-release-verification.json`；FOMC watcher、有限事件timer、
Dashboard只读账户视图、有界微信retry timer和公开数据研究timer按既有状态运行；所有交易执行权限均关闭。

- **2026-08-02 Dual-Engine 2026 YTD 无订单模拟曲线已部署。** 当前冻结 G20/C60/GC5/D15 四个
  `10,000 USD_EQ` 独立账户，使用 Tiingo/Binance 公共行情、Signal/Executable 双层净值、25 bps 基础与
  50 bps 压力成本、月内袖套隔离和 append-only 哈希审计；Dashboard 增加独立 `paper.json` / `#/paper`。
  owner 明确授权的 YTD replay 从 `2026-01-01` 起取完整公开历史；第一个模拟点为 `2026-01-02T15:00:30Z`，
  当前最后点为 `2026-07-31T00:00:05Z`，对应截至 7 月 30 日的完整数据。217 个输入周期与 217 行审计一一对应，
  G20/C60/GC5/D15 各 217 点；快照 hash=`0a0ec01b...a063`。Dashboard 已发布四线 Executable NAV 总图和每账户
  Signal/Executable 小图；当前页面以中文显示策略含义、信号/可执行净值、日期和美元等值，并提供纵轴净值、
  横轴日期、1.000 基准线、可区分线型及移动端单列布局。该曲线固定标记 `simulated_not_realized`，不是账户实盘收益。
  所有合同固定 `orders_authorized=false/private_api_used=false/exchange_mutation_attempted=false`。VPS 上 daily 与
  G20-open timer 均为 `enabled/active`；日常探针在北京时间 `06:30`，G20 显式日期探针在工作日北京时间 `23:00`。
  本机私有 `.env` 的 `QOUNT_TIINGO_API_KEY` 已不回显地映射到 VPS `/etc/qount/dual-engine-paper.env` 的
  `TIINGO_API_TOKEN`；文件为 `0600 root:root`。Tiingo EOD/IEX 与 Binance Spot 公共接口均已验证。权威口径见
  [qount_strategy_master_index.md](qount_strategy_master_index.md)。

- **2026-07-30 owner 已取消 `SmallAccount-FOMC-RightSide-v0.2` 的部署。** VPS 上不存在
  `qount-fomc-live.service`、`qount-fomc-live.timer` 或 `/root/.config/qount/fomc-live.env`，没有 live 进程、arm、授权消费记录或订单。
  FOMC 公开日历和行情研究由统一 research forward collector 采集；不能恢复或转化为交易执行权限。

- **2026-07-28 `liquidation_cascade_forward_v1`公共前向采集已在VPS启动。**
  `qount-liquidation-cascade-collector.service=enabled/active`、`NRestarts=0`；它持续订阅
  BTCUSDT/ETHUSDT/BNBUSDT 的公开 Binance USD-M `forceOrder`，并每5分钟记录当前 OI、20档深度及 mark/index
  上下文，状态根为`/var/lib/qount/research/liquidation-cascade-v1`（root `0700`、原始段和元数据`0600`）。
  首次连接和三标的完整快照已验证，冻结合同 hash=`6bbd2f44...ec38ec7`。方向性被迫流只来自 `forceOrder` 的订单边；
  premium/funding 字段仅为同刻原始上下文，绝不把本线改称或降级为 `funding_crowding_meta_v1`。本服务不读取凭据、
  私有账户或订单路径，固定`orders_authorized=false/pnl_evaluated=false/read_results_before_window=false`；首个
  180天独立窗口不早于`2027-01-24T09:25:07Z`才可进入预登记的 de-risk/entry-veto 评估，不能作为均值回复或抄底信号。
  旧 Alpha collector 已从活动 systemd 部署模板移除，历史 session 只保留在 archive，不能恢复、拼接或复用。

- **2026-07-30 L1-S2 21-ETF personal-carrier 已弃用，不再属于当前研究路线。** 它声明的 21 ETF、
  `{13,26,39,52}` 周回看与所引用提交中的 13 ETF、`{13,26,52}` 默认配置不一致；此前外部盘上的缓存和
  回放结论不作为当前可验证事实。本线不再拉取 Tiingo 数据、回放、登记策略、生成目标或新增自动化流程。
需要重新研究时，从新的个人研究问题和最小可用脚本开始，不复用这条历史流程。
代码和测试已移至 [`src/qount/legacy/l1/`](../src/qount/legacy/l1/)，专属研究文档移至
[`docs/archive/legacy/l1-personal-carrier/`](archive/legacy/l1-personal-carrier/)。

- **2026-07-30 Sleeve 1 被动长期配置已独立预登记并接入 research registry。** `l1_passive_sixty_forty@0.1.0`
  固定为 `SPY 60% / TLT 40% / USD 现金目标 0%`，年度首个完整 NYSE 常规交易日为唯一再平衡锚点；现金流仅留至下一锚点，
  无 drift-band 或择时现金例外。合同 hash=`e87eeb77...b616d3`，registry hash=`4e53e10d...2ac03a`；两者均为
  `0600` 不可覆盖工件。它只处于 `research`，不产生 StrategyIntent、scheduler、paper/live、broker 或订单权限。

- **2026-07-31 已确认统一 research forward collector 在 VPS 运行。** 它以 15 分钟 systemd timer 统一记录 Binance UM
  REST/历史归档、FOMC 日历、liquidation 状态、CTA-R ETF archive 和 L1 passive 的 Tiingo SPY/TLT 来源，使用
  可扩展 source graph、固定 contract、append-only JSONL 与 SHA-256 链；每条研究线分开写 mechanism/data/strategy
  三层结论，默认 `orders_authorized=false/pnl_evaluated=false`。代码和配置见
  [`docs/research-forward-collector.md`](research-forward-collector.md)。VPS 上
  `qount-research-forward-collector.timer=enabled/active`，最近一次 service 执行 `Result=success`、退出码 `0`；
  状态根为 `/var/lib/qount/research/forward`。最近记录的 `research_lines` 总状态仍可能为 `insufficient`，这表示某条
  source 或研究证据不足，不表示采集器失败。旧 MiniTrend forward 与 FOMC shadow timer 已从活动部署模板删除；liquidation
  WebSocket 仍作为独立原始事件源运行，统一 collector 只读取其状态，不重复写入事件流。

2026-07-27 及更早的生产、研究和架构记录已逐行迁入
[archive/current-archive-pre-fomc-2026-07-29.md](archive/current-archive-pre-fomc-2026-07-29.md)。

这份文档是当前事实入口，只保留结论、能力边界和下一步。接手命令看
[quick-handoff.md](quick-handoff.md)，项目规则和文档分类看
[project-rules.md](project-rules.md)，发现/验证边界看
[holdout.md](holdout.md)，长证据链看 [update-log.md](update-log.md)。当前系统工程主设计看
[system-architecture-design.md](system-architecture-design.md)，100 USDT Base与未来组合合同看
[crypto-portfolio-system-plan.md](crypto-portfolio-system-plan.md)，Alpha Agents研究层看
[alpha-agent-plan.md](alpha-agent-plan.md)，生产控制面演进看
[trading-system-evolution-plan.md](trading-system-evolution-plan.md)，研究与文献情报路线看
[research-advancement-roadmap.md](research-advancement-roadmap.md)，200 USDT个人事件策略看
[personal-200u-event-strategy.md](personal-200u-event-strategy.md)。旧研究线、历史计划和legacy运行手册统一从
[archive/README.md](archive/README.md)进入，不再混入当前生产导航。
