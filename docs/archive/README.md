# 历史文档与 Legacy 研究线

本目录是文档状态索引。明确冻结的正文集中在 `legacy/` 下，根目录只保留同名短指针以兼容历史链接；
所有内容仍保留原始实验、回测和失败证据，但不属于当前生产入口。余额、订单、timer、live 开关、版本和“当前”措辞
都必须按文件日期读取。

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
- [current-archive-pre-fomc-2026-07-29.md](current-archive-pre-fomc-2026-07-29.md)：从 `current.md` 迁出的
  2026-07-27 及更早生产、研究和架构记录。当前 FOMC 事实仍在 [../current.md](../current.md)。

## Legacy 生产线

- [legacy/x4-rv/crypto-x4-plan.md](legacy/x4-rv/crypto-x4-plan.md)：X4/C×D，`legacy / live disabled`。
- [legacy/x4-rv/x4-live-position-management.md](legacy/x4-rv/x4-live-position-management.md)：X4 旧仓位管理和回测，`archived`。
- [legacy/x4-rv/rv-c-plan.md](legacy/x4-rv/rv-c-plan.md)：RV-C/carry，`research-only / carry disabled`。
- [legacy/mini-trend-agent/README.md](legacy/mini-trend-agent/README.md)：早期400/300 USDT与pre-live合同；当前生产状态以当前入口为准。

## 已冻结或证伪的研究线

- [legacy/grid-b/](legacy/grid-b/)：GRID-B，已归档/证伪。
- [legacy/restart-lines/](legacy/restart-lines/)：L1/L3/L4/L6 重启线历史证据。
- [legacy/ashare-etf/](legacy/ashare-etf/)：A股 ETF 线，owner-deprioritized/frozen。
- [legacy/line-a/](legacy/line-a/)：旧架构、盈利路线和 CTA-R 重构蓝图。
- [legacy/l1-personal-carrier/](legacy/l1-personal-carrier/)：L1-S2 personal-carrier 终止线的代码、脚本、测试和研究历史。

## 历史入口代码

- [../../scripts/archive/desktop-legacy/](../../scripts/archive/desktop-legacy/)：已停用的 X4、C×D、RV-C、CTA-R 和 Mac 桌面入口。
  三个历史 cron 路径保留 fail-closed guard，不能恢复调度或下单。

## 规则

历史文件不得作为 live/paper/order 的授权来源。任何生产判断先读当前入口，再用本索引中的文件追溯背景；
历史研究结果不能覆盖当前 `MiniTrend-UM-Base-v0.2`、固定 `100 USDT`、long/cash、one-way、isolated 1x、gross<=1 合同。
