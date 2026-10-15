# 历史文档与 Legacy 研究线

本目录是文档状态索引。明确冻结的正文集中在 `legacy/` 下，根目录不再保留重复正文或旧方案指针；
所有内容仍保留原始实验、回测和失败证据，但不属于当前生产入口。余额、订单、timer、live 开关、版本和“当前”措辞
都必须按文件日期读取。

## 当前入口

- [AGENTS.md](../../AGENTS.md)：Agent 研究、工程与权限总指引。
- [current.md](../current.md)：当前事实、VPS 生产状态和下一步。
- [quick-handoff.md](../quick-handoff.md)：当前接手命令和运维边界。
- [system-architecture-design.md](../system-architecture-design.md)：当前系统工程架构。
- [crypto-portfolio-system-plan.md](../crypto-portfolio-system-plan.md)：历史 100 USDT Base 与未来组合合同参考，不授予恢复权限。
- [project-rules.md](../project-rules.md)：文档分类、研究线隔离和清理规则。
- [research-advancement-roadmap.md](../research-advancement-roadmap.md)：历史加密研究路线、实验账本与阶段记录。

## 历史记录归档

- [system-architecture-design-pre-2026-10-12.md](system-architecture-design-pre-2026-10-12.md)：旧架构完整正文与迁移记录；当前主设计已按研究、助手展示与生产执行分工重写，旧成熟度与部署描述保留原时点身份。
- [current-archive-pre-review-2026-10-11.md](current-archive-pre-review-2026-10-11.md)：本轮结论统一移出的六段策略申报；旧旗舰／高收益文字不作为当前裁决，原段落 hash 与链接重定位说明保留。

- [update-log-archive.md](update-log-archive.md)：`update-log.md` 中 2026-07-20 及更早的历史证据链（含 line A / GRID-B /
  加密重启前）。当前近期记录仍在 [../update-log.md](../update-log.md)。
- [research-reports/](research-reports/)：根目录 v4 回放、归因和基线诊断报告的历史副本；不可作为当前研究或运行依据。
- [current-archive-line-a-readings.md](current-archive-line-a-readings.md)：`current.md` 移出的 line A `最新策略读数 /
  WS-1..WS-4 / T-B / T-G / T-C` 历史 discovery 读数。当前事实仍在 [../current.md](../current.md)。
- [current-archive-pre-fomc-2026-07-29.md](current-archive-pre-fomc-2026-07-29.md)：从 `current.md` 迁出的
  2026-07-27 及更早生产、研究和架构记录。当前 FOMC 事实仍在 [../current.md](../current.md)。

## P2 ETF Trader 的历史文档

- [P2 历史分类索引](p2-history/README.md)：训练时点记录、实现/优化诊断和已撤回结论的说明；历史文字与命令不构成当前运行或验收依据。
- [2026-10-02 文档归档审计](p2-history/archive-audit-20261002.md)：owner 授权范围、引用扫描、移动路径与内容 hash。
- 当前替代入口为 [实际架构与研究结果](../p2-project-summary-20261002.md) 和 [设计协议](../etf-imitation-policy-design-2026-09.md)；文档归档不代表将 P2 研究代码冻结为 legacy。

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
- [../../src/qount/legacy/l1/](../../src/qount/legacy/l1/)：L1-S2 personal-carrier 终止线代码；脚本和文档分别见归档线路目录。

## 历史入口代码

- [../../scripts/archive/desktop-legacy/](../../scripts/archive/desktop-legacy/)：已停用的 X4、C×D、RV-C、CTA-R 和 Mac 桌面入口。
  三个历史 cron 路径保留 fail-closed guard，不能恢复调度或下单。

## 规则

历史文件不得作为 live/paper/order 的授权来源。任何运行判断先读 current，再用本索引追溯背景；
历史 MiniTrend 合同、账户规模或资金配比也只按其时点读取，不能覆盖当前停止／冻结状态或推定新的执行权限。
