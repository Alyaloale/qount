# CLAUDE.md

本文件给在本仓库工作的 Claude Code 使用，是**接手入口**。它只做导航与纪律提要，不复制事实；
当前事实一律以 `docs/current.md` 为准。

## 交流约定

- **始终用中文回答**（代码、命令、commit message、英文专有名词保持原样）。
- 除非 owner 显式授权，**不碰真实账户、VPS、订单、paper/live、forward timer、生产 cron**。
- 研究读数默认 `orders_authorized=false`、`research_only=true`。

## 一句话：这是什么

`qount` 是「AI 决策 + 风控执行器 + Binance 执行」骨架。真钱状态（2026-07-27）：
`MiniTrend-UM-Base-v0.2` 的 live/forward timer 已于 2026-07-26 由 owner 停用（`disabled/inactive`）；
`SmallAccount-FOMC-RightSide-v0.2` 的受控 live runtime（`0.2.21`）已部署 VPS 但保持 order-disabled
（未 prepare/arm/switch）；`SmallAccount-PreEvent-Range-v0.1` 为 plan-only + owner 手工执行。其余所有线（X4/C×D、RV-C、GRID-B、line A、L1/L3/L4/L6、
A股ETF）均为 legacy/frozen/falsified，**不复活**。主动研究方向为**加密优先**（2026-07-16 起）。

## 权威顺序（冲突时按此判定，来自 project-rules §1）

1. `docs/current.md` — 当前事实、运行状态、owner 决策、硬边界。
2. `docs/project-rules.md` — 项目规则、文档分类、研究线隔离、代码治理。
3. `docs/quick-handoff.md` — 可执行命令、跨主机操作、运维坑。
4. 各研究线主文档 — 只约束本线。
5. `docs/update-log.md` — 证据链、artifact、执行记录（近期在此，历史见 `docs/archive/update-log-archive.md`）。
6. 历史计划文档 — 仅背景，除非被上面重新引用。

## 接手先读顺序

1. `docs/current.md`（尤其顶部结论、"当前能力"、"下一步"、"硬边界"）。
2. `docs/project-rules.md`（分类 §3、研究线隔离 §4、反过拟合 §6、代码架构 §7、清理 §8）。
3. `docs/quick-handoff.md`（命令与运维）。
4. `docs/research-advancement-roadmap.md`（研究路线、全局实验账本、family 图谱、§11 下一轮执行步骤）。
5. `docs/holdout.md`（discovery/validation/promotion gate）。
6. `docs/archive/README.md`（legacy 线状态索引）。

## 文档地图

**当前活跃**
- 事实/规则：`current.md`、`project-rules.md`
- 接手/运维：`README.md`、`quick-handoff.md`
- 架构：`system-architecture-design.md`（统一合同、权威链、账本对账、恢复、LLM 边界）
- 存储/计算拓扑：`storage-topology.md`
- 验证边界：`holdout.md`
- MiniTrend Base：`crypto-portfolio-system-plan.md`（100 USDT + 未来组合目标）
- 研究/情报路线：`research-advancement-roadmap.md`
- 生产控制面演进：`trading-system-evolution-plan.md`
- 多智能体研究层：`alpha-agent-plan.md`
- 记录链：`update-log.md`（近期）、`archive/update-log-archive.md`（历史）
- 事件策略线：`personal-200u-event-strategy.md`（FOMC 右侧合同）、`pre-event-range-strategy.md`（事件前区间 fade）、
  `fomc-trigger-study-and-v03-extension.md`（触发率 discovery + v0.3 提案）
- 个人组合与新方向：`long-run-personal-strategy-design.md`（三层 sleeve 组合设计）、
  `personal-strategy-research-directions.md`（D1-D5 候选，索引见 roadmap §12）
- 当前研究草稿：`carry-active-basis-hypothesis.md`（R5 carry 新假设）、
  `crypto-vol-crisis-state-preregistration.md`（危机状态预登记草稿）、
  `external-bot-cra-teardown.md`（外部机器人 CRA 拆解，T4）

**归档/legacy（原地保留，不删不移；索引见 `docs/archive/README.md`）**
- line A：`profit-*.md`、`optimization-plan.md`、`cta-r-value-gate-plan.md`
- GRID-B：`grid-binance-*.md`（archived/falsified）
- C RV：`rv-c-plan.md`；D X4/CxD：`crypto-x4-plan.md`、`x4-live-position-management.md`
- 重启线：`l1/l3/l4/l6-*-plan.md`；A股 ETF：`ashare-etf-month-plan.md`；重构蓝图：`rebuild-plan.md`
- 早期 MiniTrend 设计：`docs/mini-trend-agent/`

## 主机职责与工具定位（详见 project-rules §2、storage-topology.md）

| 节点 | 职责 | 禁止 |
| --- | --- | --- |
| Mac `/Users/alyaloale/Code/qount` | 研究设计、代码主仓、git、文档、轻量验证、编排 | 不跑实盘，不长期存全量数据 |
| Windows 外置盘 `E:\qount_data` | 数据集、最终 artifact、环境锁、备份的存储真相 | 不存 `.env`/密钥 |
| WSL `home:/home/alyaloale/Code/qount` | 7945HX/RTX4060 CPU/GPU 计算、权威复跑 | 不是 live/paper 真相 |
| VPS `/root/qount` | 唯一 live/paper/dashboard 生产真相 | 不存研究大数据，不手工绕仓库规则 |

- **数据下载边界**：大批量公开数据只在 Windows/WSL 侧下载并直写外置盘，Mac/VPS 不做下载或中转。
  直连或 owner-approved Liangxin 云代理；**永不用苏菲家宽代理**；凭据留仓库外，不写进代码/文档/artifact。
- **测试入口**：Mac 无 pytest。单文件用 `PYTHONPATH=src python -m unittest tests.test_xxx`；
  **全量跑 WSL**：`scripts/run-wsl-tests.sh`（ssh→host `home`→wsl unittest discover）；改了 src 计算接口先
  `scripts/sync-to-wsl.sh`（仅接口变化时）。
- **生产只读探针**：`ssh qount-vps 'systemctl is-active qount-mini-trend-live.timer'` 等（见 quick-handoff）。

## 研究纪律（project-rules §6、roadmap §2/§5）

- 每个 `hypothesis_family` 第 3 个冻结正式 trial 强制复盘；不达主指标按**不救援**关闭，不调参/扩币/改名救援。
- 已看过窗口=`consumed_historical_discovery_pool`，改参数后不得再当独立 OOS；promotion 走 holdout once-only。
- 看结果**前**冻结主指标与失败条件；报 raw + BTC/TOP3 beta-residual + 真实成本（taker/maker/funding/滑点/换手）
  + 成本×2/延迟1bar/漏单 + 分段稳定 + trial count/DSR/PBO。
- 横截面必须报 rank-IC 与 effective breadth（币数≠广度；LiquidTrend10 有效广度仅 1.438 是容量先验）。
- G0/source-capacity 在读 PnL 前阻断；`block_capacity`/`continue_collection` 是合法结论，不改写成 0 alpha。
- 任何 candidate 可从 proposal 追到 source→preregistration→dataset→code→result→decision（GlobalExperimentRecord）。
- LLM 不输出订单、目标权重、live 配置或风控 override。

## 硬边界（不做）

- 不改 Base 参数；不 short、不加杠杆增益、不超 gross 1；不启 forward timer / production cron；不复活 legacy 线。
- 缺 funding 禁填 0；交易所字段/费率/最小名义以官方为准。
- 不把 legacy（X4/RV-C/CTA-R/GRID）读数当当前认证 edge；不把文献/厂商 Sharpe 当可复制收益。
- 不用马丁/杠杆弥补 alpha（见 `external-bot-cra-teardown.md`）。

## 代码架构（project-rules §7）

- `src/qount/main.py` 只做 CLI 分发；production 代码不 import `scripts/research/*`。
- `scripts/research/*` 是薄入口（解析参数、读写 artifact、调 `src/qount` 可测函数）；核心逻辑放 `src/qount/<line>/`。
- 新共享能力进已有模块（artifact→`artifacts.py`、交易所差异→`exchange_utils.py`、统计沉淀成可单测函数）。
- 新依赖默认不进基础依赖；研究依赖走 optional extra，live 路径保持最小。

## 记录规则（每批有意义改动后）

- 只改本线研究代码：更新本线 changelog；影响当前状态再更 `current.md` + `update-log.md`。
- 改 production/VPS/dashboard/全局规则：更 `current.md` + `quick-handoff.md` + `update-log.md`。
- 改代码未跑测试：写明"未跑"原因，不得写成已验证。
- 新 artifact 必须记命令、窗口、holdout role、成本假设、数据源、输出路径和读法。
