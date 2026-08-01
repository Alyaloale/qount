# 🏛️ Qount 宏观量化交易系统 - 核心策略总集 (Master Index)

> **状态**：deployed paper / 2026 YTD curves active｜**权威**：Dual-Engine 策略与模拟盘合同｜**最后更新**：2026-08-02
> **TL;DR**：当前有效实现固定为 G20 20% 风险预算、1x 代理资产 63 日 Top1 且无绝对动量门；C60 使用含 LTC、不含 MATIC 的 10 币池。四个 10,000 USD_EQ 模拟账户只用 Tiingo/Binance 公共数据，永不下单。owner 授权的 2026 YTD replay 已上线 Dashboard，每账户 217 个曲线点；曲线是公开历史行情模拟，不是真实账户收益。

**系统代号**: Qount Dual-Engine (G20 + C60 Dynamic)

本文档归档双引擎研究，并冻结当前模拟盘实现口径。文中的长期 CAGR / MaxDD / Sharpe 仍仅来自既有研究脚本；本次 2026 YTD replay 只建立当前 paper 状态和曲线，不能验证那些长期数字，更不得当作收益承诺。

## 当前有效模拟盘合同（覆盖下方历史歧义）

| 项目 | 冻结口径 |
| --- | --- |
| 模拟起点 | owner 授权从 `2026-01-01T00:00:00Z` 做 YTD replay；首个会计点 `2026-01-02T15:00:30Z`，随后由正常 timer 延续 |
| 历史执行价 | G20 使用 Tiingo 日线首个有效 open；C60 使用下一 UTC 日 Binance 有效开盘分钟；仅用于 `simulated_not_realized` 曲线 |
| 独立账户 | G20、C60、GC5、D15；各 `10,000 USD_EQ` |
| G20 | 1x 代理资产 63 日 Top1；风险资产 20%、BIL 80%；无 `>0` 绝对门；月末信号、T+1 首个有效盘中价 |
| C60 | `BTC/ETH/SOL/BNB/XRP/ADA/LTC/BCH/DOT/PAXG`；日频 90 日正动量 Top2；SMA20、BTC SMA50、PAXG 例外、20 日协方差、60% vol cap |
| C60 执行 | UTC 日线收盘后第一笔有效公共成交；基础成本 25 bps，压力成本 50 bps |
| 组合 | GC5 固定 95/5；D15 按 2.5/7.5/10/15%；仅 G20 月度执行事件允许跨袖套再平衡 |
| 净值 | `Signal NAV`（分数份额、零成本）与 `Executable NAV`（步长/最小名义额/基础成本）；真实组合净值明确不可用 |
| 数据与权限 | Tiingo + Binance 公共 API；`orders_authorized=false`、不读交易所私有账户、不访问 broker/testnet/order API |

实现入口为 `src/qount/dual_engine/`；YTD 构建入口为 `scripts/operations/backfill_dual_engine_ytd.py`，正常公共采集与
状态推进入口为 `scripts/operations/collect_dual_engine_market.py`；Dashboard 独立读模型为 `paper.json` / `#/paper`。

---

## 核心架构设计概览

本系统采用“核心-卫星”与“双引擎独立护城河”的现代资产组合设计，拆分为两大袖套（Sleeve），由上层协调器进行资产划拨：

1. **主引擎 (G20)**: 基于 1x 行业/宽基代理资产形成选择信号，再映射到杠杆 ETF 执行标的；不使用绝对动量门。
2. **第二引擎 (C60)**: 基于加密货币大市值资产的趋势追踪与波动率缩放系统，在承担“刺客组件”角色的同时，通过严苛的系统级闸门确保极低的尾部风险贡献。
3. **资金协调与再平衡**: 严格月度调仓与容忍权重漂移，隔绝跨市场高频摩擦。

---

## 📘 引擎一：传统美股主引擎 (G20)

### 策略基线 (G20_Full)
* **资产池**: TQQQ, SOXL, FAS, CURE, URTY, DRN, ERX (7只高贝塔/3倍杠杆美股ETF) + BIL (短期国债/现金代理)
* **代理动量规则**:
  - 测算周期：63 日 (约一季度) 收益率。
  - 信号代理映射：`TQQQ→QQQ, SOXL→SMH, FAS→XLF, CURE→XLV, URTY→IWM, DRN→VNQ, ERX→XLE`。
  - 选品：每月度选取 63 日收益最高的 **Top 1**；即使全部为负也不切换为全现金。
  - 风险降级：风险标的固定 **20%**，剩余 **80%** 为 BIL；23.5% 只属于历史调参切片，不进入当前合同。
  - 执行：月末收盘形成信号，下一美股交易日使用首个有效盘中价；单边模拟摩擦 20 bps。
* **历史研究读数 (2018-2026，尚待 canonical replay)**: CAGR ≈ 17.10%, MaxDD ≈ -20.70%, Sharpe ≈ 0.94

---

## 📙 引擎二：加密资产趋势潜艇 (C60)

### 策略基线 (C60)
* **资产池**: BTC, ETH, SOL, BNB, XRP, ADA, **LTC**, BCH, DOT, PAXG (黄金)；MATIC 不在当前实现池。
* **轮动规则**:
  - 排名周期：90 日动量。
  - 选品：每日 UTC 收盘后从正 90 日动量中取 Top 2 候选资产。
* **风控防御体系 (核心灵魂)**:
  - **Idiosyncratic Gate (资产级防线)**: 候选资产价格必须 **> SMA20 (20日均线)**，否则驳回买入。
  - **Systemic Gate (系统级熔断)**: BTC 价格必须 **> SMA50 (50日均线)**，否则全盘清仓，所有 Crypto 多头头寸全部转为 USDC/USDT (例外：避险资产 PAXG 不受 BTC 熔断限制)。
  - **Vol Target (波动率限制)**: 对通过闸门的组合计算过去 20 日协方差年化波动率。设置目标上限为 **60% (C60)**。若实际波动率 > 60%，按比例无情削减仓位，强制降波。**只减仓，不加杠杆**。
* **历史研究读数 (2020.05-2026.07，尚待 canonical replay)**: CAGR ≈ 75.92%, MaxDD ≈ -23.05%, Sharpe ≈ 2.28
* **非对称属性**: 在 2021 山寨季捕获 >200% 暴利，但在 2022 / 2026 市场大崩盘期间，依靠闸门 100% 退守现金，回撤仅 -13% 级别。

---

## 🔗 系统集成：动态资产分配 (Dynamic GC)

上层协议定义了 G20 与 C60 的资金互通逻辑。

### 调拨协议
* **频次**: 仅在每月的**第一个美股交易日**进行跨袖套（Sleeve）资金结算。
* **资金隔离**: 在月中，C60 与 G20 分别在自己的子系统预算内进行买卖交易（C60 可在月中随时因为跌破均线切为现金，但这笔现金留在 C60 账户，不提前转入美股）。

### 终极主版本：D15 (Dynamic V1 动态配额)
利用 C60 内部已有的状态指示器（BTC_SMA50, Top2_SMA20 达标数, 内部 Vol Target 缩放系数 k）来动态决定当月配给 Crypto 引擎的预算：
1. **防守 (2.5%)**: BTC < SMA50 或无合格资产。
2. **半进攻 (7.5%)**: 仅有 1 只 Top2 资产合格。
3. **进攻 (10.0%)**: 2 只候选全合格，但高波动引发强制缩仓 (k < 0.75)。
4. **强进攻 (15.0%)**: 2 只候选全合格，且趋势平稳未超波动率 (k ≥ 0.75)。

* **历史研究声明（尚待 canonical replay）**: 平均资金占用约 6.1%，研究脚本报告 **21.48% CAGR**、**-19.72% MaxDD**；不得在 Dashboard 中当作 forward 业绩。
* **保守影子版 (GC5)**: 固定配置 95% G20 + 5% C60。若追求极简运营可退化为此方案。

---

## 🗄️ 文件与代码映射目录 (Inventory)

### 📄 研究报告与文档 (Markdown)
所有报告均保存在 `docs/` 目录下：
1. `crypto-trend-v1-full-report.md` - C60 前期研发与参数消融实验大纲，奠定了 B20+M50 闸门与 C60 波控的基石。
2. `crypto-trend-v1-phase-a3.md` - 首次 GC 混合点对点测试（简单日度再平衡），确认了双引擎结合降波增益的神奇反应。
3. `crypto-trend-v1-c60-analysis.md` - C60 纯加密引擎**逐年战史剖析**，证明了系统熔断门在 2021 大赚、在 2022 逃顶的不对称收割能力。
4. `crypto-trend-v1-phase-a3-final.md` - G20+C60 联合深度测试，引入了尾部相关性矩阵与 극한压力测试 (剥夺2021, 剥夺SOL, 引入50bps摩擦)。
5. `crypto-trend-v1-phase-a3-real.md` - **最真实的跨日历/跨袖套月度再平衡审计**，揭示了 2020年3月新冠崩盘的历史全貌及 C60 对总投资组合的风险贡献。
6. `crypto-trend-v1-phase-b1.md` - **Dynamic Allocation 动态配置证明**，证实了 D15 动态配置的超额择时阿尔法。
7. `traditional_v1_ablation_results.md` - 传统美股 ETF 轮动策略的动量周期消融验证结果。

### 💻 核心回测验证代码 (Python Scripts)
所有代码存放在 `scripts/research/` 目录下，保留了演进的历史切片：
1. `crypto_trend_v1_phase_a2_a.py` - 加密货币调仓频率测试（月度 vs 周度）。
2. `crypto_trend_v1_phase_a2_b.py` - 系统级风控闸门开发（单币 SMA20 vs 叠加 BTC SMA50）。
3. `crypto_trend_v1_phase_a2_c.py` - Vol Target 波动率降权算法。
4. `crypto_trend_v1_phase_a2_5.py` - T+1 执行延迟与交易摩擦压力测试。
5. `crypto_trend_v1_phase_a3.py` & `..._final.py` - G20 + C60 联合配置、基准对比、尾部相关性。
6. `crypto_trend_v1_c60_analysis.py` - 逐年绩效归因分析器。
7. `crypto_trend_v1_phase_a3_real.py` - 真实月度独立袖套再平衡（跨市场时间戳对齐）与 RC (风险贡献) 计算。
8. `crypto_trend_v1_phase_b1.py` - D15 与 D20 状态机模型逻辑生成与择时阿尔法测算。

### 🧱 当前模拟盘生产形状代码

1. `src/qount/dual_engine/contracts.py` - 冻结合同、输入和 Dashboard 源快照。
2. `src/qount/dual_engine/strategy.py` - 无 I/O 的 G20/C60/D15 决策。
3. `src/qount/dual_engine/paper.py` - 四账户、双层净值、月内袖套隔离和哈希审计状态机。
4. `src/qount/dual_engine/market_data.py` - Tiingo/Binance 公共行情采集；不含账户或订单 API。
5. `src/qount/dual_engine/backfill.py` - owner 授权的 2026 YTD 公共数据批量收集与确定性重放输入。
6. `src/qount/reporting/paper_importer.py` - Dashboard 的严格只读、可缺省导入器。

---

## 🚀 部署注意事项
* **执行时间**: 月末 G20 信号与 T+1 首个有效盘中价分成两个事件；C60 使用 UTC 日线收盘后的第一笔公共聚合成交。
* **数据通道**: Tiingo EOD/IEX 和 Binance Spot 公共 REST；Tiingo 数据 token 只从仓库外环境文件读取。
* **交易通道**: 当前不存在。服务显式移除 Binance 私钥并固定 `orders_authorized=false`。
* **资金通道**: 没有真实资金划转；组合内跨袖套会计只在 G20 月度执行事件发生。
* **上线状态**: program=`1.1.0`、overlay content hash=`05258e5e...a8b1` 已部署到 VPS `0.2.27` 基线；两个 paper timer 与 Dashboard 12-model release 已启用。四账户各 217 点，snapshot hash=`0a0ec01b...a063`。部署清单固定 `orders_authorized=false/private_exchange_api_used=false`。
* **凭据映射**: 本机私有 `.env` 使用 `QOUNT_TIINGO_API_KEY`；VPS paper service 按合同读取仓库外
  `/etc/qount/dual-engine-paper.env` 中的 `TIINGO_API_TOKEN`。两者已安全映射，远端文件为 `0600 root:root`；不得在日志、文档或 artifact 中记录值。
* **数据状态**: Tiingo EOD、Tiingo IEX 1 分钟价和 Binance Spot 公共接口均已在 VPS 验证通过。YTD replay 使用 Tiingo 日线与 Binance 公共日线/分钟线；原始公开响应存于 0600 缓存以支持失败后续跑，不记录 token。Dashboard 已显示曲线；freshness 徽标由正常 daily 周期继续更新。

> **"没有回测魔术，只有资产配置和波动率控制的纪律。"**
