# 历史文档与 Legacy 研究线

本目录是文档状态索引，不要求移动或删除历史文件。列出的文件仍保留原始实验、回测、失败证据和引用路径，
但不属于当前生产入口；其中的余额、订单、timer、live 开关、版本和“当前”措辞都必须按文件日期读取。

## 当前入口

- [../../CLAUDE.md](../../CLAUDE.md)：接手模型的导航入口（文档地图 + 纪律提要）。
- [current.md](../current.md)：当前事实、VPS 生产状态和下一步。
- [quick-handoff.md](../quick-handoff.md)：当前接手命令和运维边界。
- [system-architecture-design.md](../system-architecture-design.md)：当前系统工程架构。
- [crypto-portfolio-system-plan.md](../crypto-portfolio-system-plan.md)：100 USDT Base minimal-live 与未来组合目标。
- [project-rules.md](../project-rules.md)：文档分类、研究线隔离和清理规则。
- [research-advancement-roadmap.md](../research-advancement-roadmap.md)：加密研究路线、全局实验账本和 §11 下一轮执行步骤。

## 历史记录归档

- [update-log-archive.md](update-log-archive.md)：`update-log.md` 中 2026-07-20 及更早的历史证据链（含 line A / GRID-B /
  加密重启前）。当前近期记录仍在 [../update-log.md](../update-log.md)。
- [current-archive-line-a-readings.md](current-archive-line-a-readings.md)：`current.md` 移出的 line A `最新策略读数 /
  WS-1..WS-4 / T-B / T-G / T-C` 历史 discovery 读数。当前事实仍在 [../current.md](../current.md)。

## Legacy 生产线

- [crypto-x4-plan.md](../crypto-x4-plan.md)：X4/C×D，`legacy / live disabled`。
- [x4-live-position-management.md](../x4-live-position-management.md)：X4 旧仓位管理和回测，`archived`。
- [rv-c-plan.md](../rv-c-plan.md)：RV-C/carry，`research-only / carry disabled`。
- [mini-trend-agent/](../mini-trend-agent/README.md)：早期400/300 USDT与pre-live合同；当前100 USDT生产状态以当前入口为准。

## 已冻结或证伪的研究线

- `grid-binance-*.md`：GRID-B，已归档/证伪。
- `l1-cross-asset-plan.md`、`l3-information-edge-plan.md`、`l4-cross-exchange-plan.md`、`l6-microstructure-plan.md`：重启线历史证据。
- `ashare-etf-month-plan.md`：A股 ETF 线，owner-deprioritized/frozen。
- `optimization-plan.md`、`profit-research-plan.md`、`profit-engineering-plan.md`、`rebuild-plan.md`、`cta-r-value-gate-plan.md`：旧架构/盈利路线。

## 规则

历史文件不得作为 live/paper/order 的授权来源。任何生产判断先读当前入口，再用本索引中的文件追溯背景；
历史研究结果不能覆盖当前 `MiniTrend-UM-Base-v0.2`、固定 `100 USDT`、long/cash、one-way、isolated 1x、gross<=1 合同。
