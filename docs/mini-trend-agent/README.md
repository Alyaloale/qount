# MiniTrend Agent 方案总览

状态：v0.7 低频 TOP3 forward monitoring + 独立 UM futures no-carry 研究分支，线 D / X4 的小资金子方案。
当前不改变 VPS 生产配置，不 arm 新实盘，不替代 `docs/current.md`。

## 目标

为约 400 USDT 小盘账户设计一套更适合当前资金量的加密交易系统：

- 保留已验证相对靠谱的日线趋势骨架。
- 删除或延后小资金不适配的复杂腿：C×D carry、动态币池、分钟级短线、软配对、网格。
- 用 LLM API 构建多 agent 审计 / 研究 / 风控解释层，但不让 LLM 直接决定买卖方向。
- 代码保持小模块、薄入口、强 contract、可单测，不堆单个巨文件。

## 依据

当前项目结论给出的约束：

- 旧 line A / ETH-only 已 research-only，不能复活当 live 方案。
- X4 日线趋势是当前可复用主骨架；400 USDT 的真实可成交性复核只支持 TOP3，TOP4/TOP5 会被
  SOL/XRP 最小名义拖累。
- RV-C BTC/ETH dated carry 是真 edge，但薄、窄、多场所，400 USDT 阶段不优先。
- 最近 VPS 审计暴露 stop 成交后立即重开问题；任何新方案必须把 latch 作为硬风控。
- Binance 最小名义价值、lot size、费用和 funding 必须运行时读交易所规则，不能凭固定数。

复盘后的约束收紧：

- spot TOP3 仍是已冻结的历史 forward 基线；owner 新指令把后续资金架构改为“资金进 USD-M futures wallet、
  carry=off”，但不等于满仓或加杠杆。
- `MiniTrend-UM-Recovery-v0.1` 已独立预登记但历史诊断拒绝，不能调参救援、paper 或 live；UM 旧趋势控制线
  只有另写 baseline forward preregistration 后才能收集新数据。
- 先优化执行可靠性和可成交性，再谈收益增强。
- LLM agent 先接审计日报，不进 paper/live 主循环的放行链。
- 任何参数优化必须用 scorecard 评价，不用单一收益或 Sharpe 排序。

## 推荐策略

名称：`MiniTrend TOP3 frozen forward`（artifact 内保留原 `MiniTrend-5` strategy id 以绑定旧 anchor）

spot 基线形态：

- universe：`BTCUSDT, ETHUSDT, BNBUSDT`
- 市场：spot only；UM futures 另有隔离研究合同，不复用 spot promotion 资格。
- 方向：400 USDT 阶段只做 long / cash；`short_gate` 默认关闭。
- 总闸：`BTC close > SMA200` 或 breadth >= 0.5 才允许风险暴露。
- 个币闸：`close > SMA200 and SMA20 > SMA60`。
- 权重：逆波动率 + 相关性惩罚 + 冻结 `vol_target=0.015`。
- 调仓：每日收盘后目标权重对账，盘中只做止损 / 风控同步。
- 风控：stop latch、日亏损停机、周亏损停机、最小成交额过滤、账户 hard cap。

## 当前 Forward

- preregistration：`20260717T030622Z-mini-trend-top3-forward-preregistration`
- final report：`20260717T031824Z-mini-trend-top3-forward`
- window：`2026-07-01..2026-07-16`，16/16 completed spot daily bars，0 gap。
- readout：master gate shut，16 cash bars，0 active bars，0 orders，0 blocked symbols；策略约 0%，
  BTC/TOP3 EW 分别 `+8.88%/+10.75%`。
- verdict：`collect_forward`。至少 60 根 forward 且 10 根 active 才允许另做 paper-readiness review；
  不因错过反弹调整 SMA200/breadth gate。

## UM Futures Research Branch

- live lessons audit：`state/research_runs/20260717T033716Z-mini-trend-live-lessons/mini_trend_live_lessons.json`
- recovery preregistration：`state/research_runs/20260717T034500Z-mini-trend-um-recovery-preregistration/mini_trend_um_recovery_preregistration.json`
- historical diagnostic：`state/research_runs/20260717T035442Z-mini-trend-um-recovery-historical/mini_trend_um_recovery_historical.json`
- base-trend v0.1 preregistration（已被 v0.2 替代）：`state/research_runs/20260717T040358Z-mini-trend-um-base-forward-preregistration/mini_trend_um_base_forward_preregistration.json`
- base-trend v0.1 freshness（历史中间证据）：`state/research_runs/20260717T043314Z-mini-trend-um-base-forward/mini_trend_um_base_forward.json`
- historical benchmark decomposition：`state/research_runs/20260717T115728Z-mini-trend-um-historical-benchmark/mini_trend_um_historical_benchmark.json`
- retired X4 high-return attribution：`state/research_runs/20260717T121616Z-mini-trend-high-return-attribution/mini_trend_high_return_attribution.json`
- base-trend v0.2 preregistration：`state/research_runs/20260717T121646Z-mini-trend-um-base-forward-preregistration/mini_trend_um_base_forward_preregistration.json`
- base-trend v0.2 freshness：`state/research_runs/20260717T121715Z-mini-trend-um-base-forward/mini_trend_um_base_forward.json`
- risk-tier v0.1 execution rejection：`state/research_runs/20260717T124305Z-mini-trend-um-risk-tier-historical/mini_trend_um_risk_tier_historical.json`
- risk-tier v0.2 historical rejection：`state/research_runs/20260717T124433Z-mini-trend-um-risk-tier-historical/mini_trend_um_risk_tier_historical.json`
- regime-overlay preregistration：`state/research_runs/20260717T132304Z-mini-trend-um-regime-overlay-preregistration/mini_trend_um_regime_overlay_preregistration.json`
- regime-overlay final historical rejection：`state/research_runs/20260717T132757Z-mini-trend-um-regime-overlay-historical/mini_trend_um_regime_overlay_historical.json`
- regime stop-latch preregistration：`state/research_runs/20260717T134653Z-mini-trend-um-regime-stop-latch-preregistration/mini_trend_um_regime_stop_latch_preregistration.json`
- regime stop-latch final historical rejection：`state/research_runs/20260717T135551Z-mini-trend-um-regime-stop-latch-historical/mini_trend_um_regime_stop_latch_historical.json`
- funding-veto preregistration：`state/research_runs/20260717T144609Z-mini-trend-um-funding-veto-preregistration/mini_trend_um_funding_veto_preregistration.json`
- funding-veto final historical retain：`state/research_runs/20260717T145148Z-mini-trend-um-funding-veto-historical/mini_trend_um_funding_veto_historical.json`
- funding-veto robustness preregistration：`state/research_runs/20260717T151224Z-mini-trend-um-funding-veto-robustness-preregistration/mini_trend_um_funding_veto_robustness_preregistration.json`
- funding-veto robustness conditional retain：`state/research_runs/20260717T151318Z-mini-trend-um-funding-veto-robustness-historical/mini_trend_um_funding_veto_robustness_historical.json`
- funding-veto attribution preregistration：`state/research_runs/20260717T153223Z-mini-trend-um-funding-veto-attribution-preregistration/mini_trend_um_funding_veto_attribution_preregistration.json`
- funding-veto attribution mechanism support：`state/research_runs/20260717T153320Z-mini-trend-um-funding-veto-attribution-historical/mini_trend_um_funding_veto_attribution_historical.json`
- funding-veto state-decay preregistration：`state/research_runs/20260717T155209Z-mini-trend-um-funding-veto-state-decay-preregistration/mini_trend_um_funding_veto_state_decay_preregistration.json`
- funding-veto state-decay resolved：`state/research_runs/20260717T155312Z-mini-trend-um-funding-veto-state-decay-historical/mini_trend_um_funding_veto_state_decay_historical.json`
- funding-veto shadow-forward v0.2 preregistration：`state/research_runs/20260717T162621Z-mini-trend-um-funding-veto-shadow-forward-preregistration/mini_trend_um_funding_veto_shadow_forward_preregistration.json`
- funding-veto shadow-forward v0.2 freshness：`state/research_runs/20260717T162632Z-mini-trend-um-funding-veto-shadow-forward/mini_trend_um_funding_veto_shadow_forward.json`
- WSL UM公开输入刷新：`/mnt/e/qount_data/qount/artifacts/experiments/20260718T081136Z-um-shadow-input-refresh-v02/mini_trend_um_shadow_input_refresh.json`
- canonical缓存离线shadow freshness：`/mnt/e/qount_data/qount/artifacts/experiments/20260718T080849Z-um-funding-veto-shadow-forward/mini_trend_um_funding_veto_shadow_forward.json`
- 结果：recovery 增量只有 `1/3` 段为正，verdict `reject_historical_candidate`；不消费新 forward、不进入 paper/live。
- 旧趋势控制线当前 verdict `await_forward_data`：WSL/external canonical三币最新共同完成日线已推进到
  `2026-07-17`，但仍早于双状态冻结起点`2026-07-19`，没有evaluation bar；不把数据刷新改写成控制线通过。
- 历史基准分解显示 control 在 2/3 段相对 BTC/TOP3 更抗跌，但只在 1/3 段取得绝对正收益；它是低 beta
  wrapper，不应作为持续盈利 alpha 对外宣称。
- 旧 X4 日线 headline 漏掉每日 08:00/16:00 funding；完整结算后 S3/S4 为
  `+84.93%/+70.77%`，不是旧 `+115.18%/+98.39%`。高收益主要由日线、去空头、SMA200 闸贡献，2x cap
  对收益没有稳健增量。v0.1 base contract 未显式绑定实际 3xATR stop，尚未读结果前已由 v0.2 替代。
- 当前 UM base 全窗 discovery 为 `+66.51% / Sharpe 0.903 / maxDD 17.28%`，平均有效 gross `0.182`；
  只用于解释为何选择低暴露 long/cash 控制线，不能替代 2026-07-17 后 future OOS。
- 2.0% risk-tier 全窗虽然提高到 `+103.29%/Sharpe 0.974/maxDD 21.21%`，但 2025-2026 恶化为
  `-5.31%/maxDD 13.78%`，击穿预登记弱市收益和回撤恶化门，已拒绝且不做中间参数救援。
- 三阶段 overlay 只在 strong bull 使用 2.0%，transition/range 保持 1.5%、bear 现金；全窗提高到
  `+85.94%/Sharpe 0.902/maxDD 19.30%`，但 2025-2026 恶化到 `-5.13%/maxDD 12.45%`。强牛分类在
  2025 顶部/回落仍会误放大风险，已拒绝且不调整 breadth、均线、确认天数或风险中间值救援。
- stop-latched overlay 在 strong-bull stop 后仅把 2.0% 退回 1.5%，无新阈值；全窗提高到
  `+88.41%/Sharpe 0.945/maxDD 18.70%`，2025-2026 改善到 `-1.83%/maxDD 9.86%`。除全窗 DD 相对
  base 恶化 `1.418pp > 1pp` 外全部预登记门通过；仍按合同拒绝，只作为最佳历史机制证据。
- funding-veto 用上一完整日已结算 TOP3 funding 中位数简单年化 `>50%` 否决当前 strong-bull boost；17根
  veto 后全窗 `+88.95%/Sharpe 0.965/maxDD 18.11%`，全部历史门通过。相对stop-latch收益 `+0.536pp`、
  DD改善 `0.598pp`；事件只覆盖2021/2023-24，verdict仅为历史retain，不进入paper/live。
- 预登记配对20日循环区块Bootstrap在5000条固定seed路径上给出候选终值收益/Sharpe/更低maxDD胜率
  `58.90%/86.82%/75.72%`，三项增量中位数 `+0.463pp/+0.0191/-0.226pp`，通过稳健门；但收益增量
  `p05=-4.19pp`，只说明条件路径下风险质量较可信，不是OOS或稳定收益alpha。
- 六组精确Shapley把 `+0.536pp` 拆为funding `+0.443pp`、价格 `+0.097pp`、成本 `-0.004pp`，支持成本
  veto机制；但事件日 `+1.842pp` 被下游 `-1.306pp` 抵消，17个事件传播为696个非事件差异日。未来验证
  必须完整重放状态，不能只看事件次日。
- 状态衰减显示执行状态差异696日、18个spell，首次同步14-56日/中位46日；只有最后事件在324日后稳定同步。
  所有状态差异都涉及目标权重，吊灯/冷却/latch不分叉；13个无新事件spell证明权益与deadband会再发散。
- 双状态shadow v0.2从`2026-07-19`开始，200根只作warmup，两路径从400 USDT现金同时启动并保存链式状态
  journal；只评估价格连续且决策日/持有日TOP3各至少3次funding结算的完整前缀，缺失结算不按0成本计算。
  当前缓存止于`2026-06-18`，0根eligible、`strategy_results_evaluated=false`、`await_shadow_forward_data`。
- 所有新资金架构约束：`UM wallet + no carry + 1d + long/cash + effective gross<=1 + no leverage boost +
  runtime filters + fail-closed capital + stop latch/cooldown`。

## 文档地图

- [architecture.md](architecture.md)：模块和 agent 架构。
- [execution.md](execution.md)：从文档到 paper / live pilot 的执行步骤。
- [contracts.md](contracts.md)：结构化 JSON contract 和 agent 边界。
- [coding-rules.md](coding-rules.md)：代码编写原则、文件拆分和禁止事项。
- [review.md](review.md)：复盘发现、已收紧的设计和 scorecard。

## 外部硬约束

实现时以官方规则为准：

- Spot symbol filters: https://developers.binance.com/docs/binance-spot-api-docs/filters
- USD-M futures exchange info: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information
- Binance fee schedule: https://www.binance.com/en/fee

## 非目标

- 不追求把 400 USDT 做成高频或高杠杆账户。
- 不让 LLM 生成订单或改写风控放行结果。
- 不在同一设计轮里同时重做趋势、carry、dashboard 和部署；carry 在新资金架构中直接关闭。
- 不以回测头条收益作为上线依据；优先看可成交性、费用、回撤、审计一致性。
