# qount 当前状态

> **状态**：active｜**权威**：L1 当前事实（#1）｜**最后更新**：2026-07-30
> **本文回答**：当前生产事实、能力边界、运行状态、下一步、硬边界。
> **TL;DR**：本次 FOMC 已完整运行观察窗口，但未形成方向锚，故没有 arm、订单授权或交易所变更；live timer 已在无持仓复核后停用，shadow 继续完成事件证据采集。标准策略注册表只列连续策略，FOMC 是独立事件运行时。

更新时间：2026-07-30

VPS生产版本：`0.2.27`。当前release的commit、source tree、provenance和逐文件verification均保存在
`/root/qount/.qount-release-provenance.json`及`.qount-release-verification.json`；FOMC watcher、有限事件 live/shadow timer、
Dashboard只读账户视图和有界微信retry timer均已部署；除本次受限 FOMC live 路径外，所有交易执行权限仍关闭。

- **2026-07-30 FOMC live 收尾停机。** 入场截止已过，且 VPS 复核
  `execution_exists=false`、`attempt_exists=false`、`arm_exists=false`；没有任何仓位需要持仓管理或强制退出。
  因此 `qount-fomc-live.timer` 已改为 `disabled/inactive`，最近 service 结果为
  `Result=success/ExecMainStatus=0`。`qount-fomc-shadow.timer` 继续 `enabled/active` 完成公共数据和复盘证据采集；
  本操作未访问交易所、未创建 arm、未修改订单或风险权限。

- **2026-07-30 `0.2.27` FOMC 复盘与截止状态修复。** 有效入场窗口 `22:30–03:59 UTC` 内，live cycle 共运行
  `330` 次，全部为 `auto_waiting_for_signal`；shadow 共运行 `67` 次，全部为 `OBSERVE/side=none`。
  最后一轮有效 signal 明确为 `direction_anchor_missing`：冻结 `H0=65722.5`、`L0=62660.1`、`ATR0=356.6571`，
  需要完成 1h K 收盘高于 `65811.6643` 或低于 `62570.9357` 才进入后续 15m 突破/回踩、私有预检、arm 和订单门。
  因此本次未下单是策略的无信号结果，而不是交易所、账户或授权拒单；全程
  `orders_authorized=false`、`exchange_mutation_attempted=false`，没有 arm 或授权消费记录。
  修复 `auto_entry_window_closed` 被 CLI 错映射为 exit code `2` 的问题，使无持仓的入场截止不再把 systemd 标记为失败；
  已补 CLI 回归测试。已有仓位/尝试状态仍优先进入持仓管理与 `11:00 UTC` 强制退出路径，未改变任何订单或风控条件。

- **2026-07-30 FOMC 实机运行与 Dashboard 前端复核完成。** VPS 上 `qount-fomc-live.timer` 与
  `qount-fomc-shadow.timer` 均为 `enabled/active/waiting`；live 最近结果为
  `auto_waiting_for_observation`，shadow 最近结果为 `EVENT_FROZEN`。当前事件身份为
  `SmallAccount-FOMC-RightSide@0.2`，边界为 freeze `17:30 UTC`、statement `18:00 UTC`、press conference
  `18:30 UTC`、observation `22:30 UTC`、entry cutoff 次日 `04:00 UTC`、force exit 次日 `11:00 UTC`。
  本轮 `exchange_mutation_attempted=false`、`orders_authorized=false`，未生成 arm 或授权消费记录；因此 timer 正常运行不等于已有实盘订单。
  Chrome 已对 VPS 实际发布目录完成桌面和移动端截图检查（`/tmp/qount-vps-strategies-desktop.png`、
  `/tmp/qount-vps-strategies-mobile.png`），前端可渲染 `MiniTrend-UM-Base-v0.2`。

- **策略注册表与 FOMC 的可观测性边界。** Dashboard 的标准策略行来自
  `StrategyRegistry.entries`，当前只显示连续策略 `MiniTrend-UM-Base-v0.2`；FOMC 的
  `SmallAccount-FOMC-RightSide@0.2` 属于独立 event runtime，不会自动伪装成标准连续策略行。
  这解释了“策略注册表没有 FOMC”，不表示 FOMC runtime 故障。`NAV`/ledger unavailable 只限制账本投影和净值，不会隐藏策略行；偶发“已过期”来自
  `blocked_runtime_observation` freshness 超时，observer timer 本身仍正常运行。

- **2026-07-29 `0.2.26`修复 Dashboard v1 读模型解包。** 浏览器先验证带文件 SHA-256 的下载响应，随后只把
  read-model 本体写入渲染状态；此前错误保留响应包装导致 `overview.payload.account` 未定义并显示错误的
  `PRODUCTION STOPPED`。桌面和移动端均用 VPS 当前原子发布复验为可用；该修复只涉及只读前端，不读取交易所、
  不改变订单权限或 FOMC 授权。

- **2026-07-29 `0.2.25`精确策略身份门已部署至FOMC自动路径。** 事件配置必须显式且精确匹配
  `SmallAccount-FOMC-RightSide@0.2`；缺失、错误 ID 或错误版本会在读取运行状态、访问交易所或生成 arm 前失败关闭。
  自动授权也重复验证身份，不能复用其他策略的授权、风险预算或内部 arm。该变更不扩大本次 FOMC 的事件、账户、
  标的、杠杆、名义、保证金或首笔风险授权。

- **2026-07-29 owner 授权本次 FOMC 的受限自动执行，尚未产生订单。** 授权范围固定为
  `SmallAccount-FOMC-RightSide-v0.2`、BTCUSDT USD-M、200 USDT sleeve 和 20 USDT 正常策略回撤停止阈值；更严格的
  首笔全成本压力风险 `<=5 USDT`、滚动 24h 亏损 `<=10 USDT`、单一 crypto-beta、isolated、实际杠杆 `<=5x`、
  40 USDT 保证金和 200 USDT 名义上限保持不变。release `01c7618` 已部署，源文件 hash 与本地逐项一致，systemd service
  改为 `auto-cycle`。`authorize-auto` 私有只读预检已通过并写入 0600 的事件/账户/策略绑定授权；当前没有 arm、token、
  授权消费记录或 `/root/.config/qount/fomc-live.env`。生产 smoke 已返回 `auto_disarmed` 和随后 `auto_waiting_for_observation`，
  均为 `exchange_mutation_attempted=false`。观察开始前不访问交易所；只有新鲜 shadow `ARMED`、新的私有 readiness 和所有
  scope/风险/账户检查同时通过后，才会消费该授权、生成短时内部 arm 并由 dispatcher 提交一次受原生
  `STOP_MARKET closePosition` 保护的 MARKET 入场。20 USDT 是策略停止/平仓阈值，不是跳空或交易所中断下的精确成交保证。

- **2026-07-28 `liquidation_cascade_forward_v1`公共前向采集已在VPS启动。**
  `qount-liquidation-cascade-collector.service=enabled/active`、`NRestarts=0`；它持续订阅
  BTCUSDT/ETHUSDT/BNBUSDT 的公开 Binance USD-M `forceOrder`，并每5分钟记录当前 OI、20档深度及 mark/index
  上下文，状态根为`/var/lib/qount/research/liquidation-cascade-v1`（root `0700`、原始段和元数据`0600`）。
  首次连接和三标的完整快照已验证，冻结合同 hash=`6bbd2f44...ec38ec7`。方向性被迫流只来自 `forceOrder` 的订单边；
  premium/funding 字段仅为同刻原始上下文，绝不把本线改称或降级为 `funding_crowding_meta_v1`。本服务不读取凭据、
  私有账户或订单路径，固定`orders_authorized=false/pnl_evaluated=false/read_results_before_window=false`；首个
  180天独立窗口不早于`2027-01-24T09:25:07Z`才可进入预登记的 de-risk/entry-veto 评估，不能作为均值回复或抄底信号。
  旧 `qount-alpha-collector.service` 继续`disabled/inactive`，没有被恢复、拼接或复用。

- **2026-07-30 L1-S2 21-ETF personal-carrier 已弃用，不再属于当前研究路线。** 它声明的 21 ETF、
  `{13,26,39,52}` 周回看与所引用提交中的 13 ETF、`{13,26,52}` 默认配置不一致；此前外部盘上的缓存和
  回放结论不作为当前可验证事实。本线不再拉取 Tiingo 数据、回放、登记策略、生成目标或新增自动化流程。
需要重新研究时，从新的个人研究问题和最小可用脚本开始，不复用这条历史流程。
代码、脚本、测试和专属研究文档已移至 [archive/legacy/l1-personal-carrier/](../archive/legacy/l1-personal-carrier/)。

- **2026-07-30 Sleeve 1 被动长期配置已独立预登记并接入 research registry。** `l1_passive_sixty_forty@0.1.0`
  固定为 `SPY 60% / TLT 40% / USD 现金目标 0%`，年度首个完整 NYSE 常规交易日为唯一再平衡锚点；现金流仅留至下一锚点，
  无 drift-band 或择时现金例外。合同 hash=`e87eeb77...b616d3`，registry hash=`4e53e10d...2ac03a`；两者均为
  `0600` 不可覆盖工件。它只处于 `research`，不产生 StrategyIntent、scheduler、paper/live、broker 或订单权限。

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
