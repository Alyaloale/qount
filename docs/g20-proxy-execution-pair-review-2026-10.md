# G20 Proxy / Execution 配对核查（只读）

> **状态**：初步核查完成；完整配对待 291 点源快照与成对行情数据｜**日期**：2026-10-12  
> `research_only=true / orders_authorized=false`。本记录不改 G20 合同、参数或调仓，不读取 VPS，不请求 Tiingo。

## 已核实的信号与执行映射

`src/qount/dual_engine/contracts.py` 的冻结映射如下。G20 用左侧 1x 代理计算 63 日动量排名，再以右侧 ETF 执行；风险仓位为 20%，其余 80% 为 BIL。

| Proxy（信号） | Execution（模拟执行） |
| --- | --- |
| QQQ | TQQQ |
| SMH | SOXL |
| XLF | FAS |
| XLV | CURE |
| IWM | URTY |
| VNQ | DRN |
| XLE | ERX |

冻结口径是月末信号、T+1 首个有效盘中价，见 [策略主索引](qount_strategy_master_index.md)。

## 本地证据能说明什么

仓库没有 `state/dual_engine/current/paper_program_snapshot.json`，只有 API 测试 fixture。该 fixture 只有 3 个 G20 NAV 点（2026-01-02、2026-05-01、2026-10-09），且没有月度 `rebalances.events`、逐日代理信号或原始执行价。fixture 记录末值 `signal NAV=1.157073`、`executable NAV=1.152573`，两者相差 **0.004500 NAV（本金的 0.45 个百分点）**。这是 fixture 的描述性差额，混合了费用、份额取整和价格路径；无法把它拆成杠杆 ETF 路径衰减或成本。

已有 [2026-10-04 G20 执行研究复盘](../state/research_runs/dual_engine_execution_20261004/REPORT.md) 报告原 G20 在 20 bps / T+1 open 下的历史 CAGR 15.69%、BIL 超额 Sharpe 0.837、MDD -17.93%；40 bps / T+2 open 下 CAGR 13.65%、超额 Sharpe 0.730、MDD -22.17%。该报告比较调仓规则、成本与延迟场景，没有给出当前冻结账户逐月 proxy 与 execution 的配对账本，因此不能回答 G3 的路径衰减问题。

## 结论与下一步数据要求

目前只能确认账户曲线含 0.45 个百分点的 signal/executable 差（fixture），不能判断其中有多少来自杠杆路径衰减。要完成 G3，需取得实际 291 点快照（含每次 `rebalances.events[].fills` 与 `latest_decision.g20_selected`）及严格对齐的 7 组 proxy close、execution T+1 open/价格与费率数据；对拆分、分红和交易日缺口作同口径处理后，逐月报告 signal 选择、执行标的、毛路径差、费用与可执行净值差。缺任一来源时保持结论为未知，不用 3 点 fixture 外推。

本次不访问远端、不拉行情、不改策略，也不把历史执行研究误称为 G3 的配对结论。完整配对等待源账本可在本地核验后继续。

## 后续只读取材尝试（2026-10-12）

owner 确认 §4 后立即开始只读 G3 核查后，尝试对 VPS 快照做 `stat` 元数据读取，并检查 WSL/E 既有研究目录。当前运行环境拒绝 VPS SSH（连接在认证前关闭）和 WSL SSH（`Operation not permitted`）；未读取服务环境文件、未复制远端内容、未改远端状态，也未请求 Tiingo 或其他行情源。因此 G3 仍只有本地三点 fixture，完整 291 点配对结论待只读数据通道可用后继续。
