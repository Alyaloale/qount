# Independent Research-Line Validation

本报告按研究线分别加载数据、执行回放、计算指标；一条线的治理缺口不再直接推导另一条线失败。结论分为机制、历史回放、当前 forward/可交易性三层。

## MiniTrend Base

修复后通过独立 `--kline-cache-dir state/r0_runtime/klines` 与 `--funding-cache-dir state/r0_runtime/funding` 加载，BTC/ETH/BNB 各 2036 根共同日线，覆盖 `2021-01-01` 至 `2026-07-29`；funding 各 6021 条。规则使用本地 PIT rules proxy，hash 为 `1e0ed95fee15dc76c285ec1fae25d84c6ca9ffffcc848ce5f579d4b44dbe760b`。

固定 no-carry、long-only、3x ATR chandelier、3 根 cooldown 独立回放：

- 历史窗口 `2021-07-20` 至 `2026-07-29`：净收益 `70.2653%`，最大回撤 `16.7726%`，282 orders，31 stops，funding PnL `-32.9688 USDT`，交易成本 `30.0526 USDT`；
- 当前 forward `2026-07-17` 至 `2026-07-29`：13 根，0 active bars，0 orders，收益 `0%`。这不是亏损，而是 forward 样本不足且没有入场。

结论：机制 `valid`；历史回放 `valid`（consumed-history diagnostic）；当前 OOS/策略收益 `insufficient`，还不能满足 60 根 forward bars 和 10 根 active bars 的合同门槛。

## Funding Veto

修复后在同一数据窗口单独重建 control、stop-latch reference 和 candidate，没有读取旧 funding-veto 收益 artifact。结果：

- 全窗 candidate：净收益 `86.0664%`，最大回撤 `17.7842%`，Sharpe `0.9403`；
- control：净收益 `70.2653%`，最大回撤 `16.7726%`，Sharpe `0.9386`；
- candidate 相对 control：`+15.8010pp`，最大回撤恶化 `+1.0116pp`；
- funding coverage `1.0`，17 个 veto bars，17 个 veto events；
- 分段 candidate return：`2021-2022 -1.0075%`、`2023-2024 +56.0659%`、`2025-2026 -2.5905%`；
- 当前 forward `2026-07-19` 至 `2026-07-29`：11 根，0 active bars，0 orders，收益 `0%`。

结论：成本 veto 机制 `valid`；历史回放 `valid`（独立复现，但仍是 consumed history）；当前 forward/推广 `insufficient`。旧的 `+88.95%` 不是本次独立回放数字，不能继续引用。

## L1-S2

先做合同与输入 admission，再做收益计算。独立检查结果：

- 合同声明 21 ETF、lookbacks `[13,26,39,52]`；
- 绑定 source commit 实际只有 13 ETF、lookbacks `[13,26,52]`；
- source parity：`matches=false`，mismatches=`universe,lookback_weeks_grid`；
- 21 个 Tiingo adjusted-close cache：`0/21`，全部缺失；
- 因此不运行任何替代数据、网络数据或参数修复。

结论：合同/source 方法 `flawed`；数据 `insufficient`；本轮策略收益 `insufficient`，没有伪造 PnL。历史文档中的 `terminal_passive_fallback` 是旧封存结论，不能冒充本轮独立重跑。

## CTA-R

使用固定 8 ETF `etf_data.zip`，重新运行 selection-free、long-only、unlevered、正常成本和双倍成本压力测试。新 bundle：

[CTA-R independent results](/Users/alyaloale/Code/qount/state/research_governance/cta_r_revalidation/20260730_independent/062c305617bb3cdebb41df788e79daccb2b7ea907a28f1f344b175cdb15dd011/results.json)

- 共同日期 `3037`，区间 `2014-01-15` 至 `2026-07-22`；
- 正常成本 walk-forward Sharpe `0.7403`，CAGR `7.6985%`，5/5 folds positive；
- 双倍成本 Sharpe `0.6984`，CAGR `7.2174%`，4/5 folds positive；
- independent NAV reconciliation difference `1.78e-15`，通过；
- `candidate_pnl_ready=false`，`promotion_evidence=false`。

结论：固定机制与回放 `valid`（discovery scope）；数据可交易性 `flawed`，因为 current archive 不能证明 PIT membership，QDII premium/tracking error 和认证成本未重建；promotion/实盘收益结论 `insufficient`。

## FOMC

修复后的入口使用纽约时间 14:00 的官方 FOMC 日历，并在本地 OKX 1H cache 上独立重算 2024-01 至 2026-06 的 20 个事件；报告显式排除不完整 D+3 窗口：

- 20 个 scheduled events 中，19 个拥有完整 D+3 数据；`2026-06-17` 缺失，不能计入完整样本；
- 完整 19 个事件中，10 个触发 1H anchor，anchor rate `52.63%`；
- 10 个 anchor 中 7 个 strong，strong-given-anchor `70%`；
- weak reversal `3` 个。

修复后 artifact：[FOMC repaired study](/Users/alyaloale/Code/qount/state/research_governance/macro_event_anchor_trigger/20260730_fomc_repaired/fomc_anchor_trigger_study.json)。

这只验证 1H discovery anchor，不验证 v0.2 的 15m confirmation、真实 fill、stop 或 force-exit PnL。当前 entry-cutoff shadow 另因 Binance restricted-location 451 HALTED，未形成 scorecard。

结论：1H anchor 机制 `valid`（discovery）；数据 `insufficient`（19/20 complete，且无完整 v0.2 15m outcome）；策略收益 `insufficient`。

## 总结

不是每条线都失败：MiniTrend Base、Funding Veto 的历史机制/回放为正，CTA-R 的独立双成本结果稳定，FOMC 的 1H discovery 也有可复现的强 anchor 比例。当前真正不能升级为可交易策略的原因分别是 forward 样本不足、PIT/成本边界、L1 合同与 source 不一致，以及 FOMC 缺少完整执行结果；这些不应合并成一个“全部失败”。

验证基础：统计/Vol Crisis/FOMC 相关聚焦测试 `296 tests OK`，并通过 `git diff --check` 与 `compileall`；FOMC CLI 和两条 MiniTrend CLI 的 help/缓存加载检查通过。
