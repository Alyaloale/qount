# Qount 动态定投与止盈策略 (跨资产意图驱动版)

> **状态**：draft / active research ｜**权威**：Sleeve 策略设计｜**最后更新**：2026-07-30
> **本文回答**：小额资金如何通过意图驱动实现动态定投、跨资产配置与止盈，以及当前架构对跨资产的兼容边界。
> **TL;DR**：基于 20W MA 偏离度的周级动态定投策略，通过输出绝对 Target Weight 驱动 Qount 执行器；当前 TradFi 部分仅作为 Shadow/Virtual 实验。

本文档描述了一个专为小资金（每周 $10 增量资金）设计的**动态定投 (DDCA) + 阶梯止盈**交易策略。该策略深度集成于 `qount` 框架的**意图驱动 (Intent-Based)** 架构中，并完美契合 Binance 等平台对**加密货币 (Crypto) 与传统金融 (TradFi) 的双边支持**。

> ⚠️ **架构边界与实盘注意**：
> 1. 根据 L2 架构主设计，Tokenized equity 或 Direct Stocks (如 `SPY_TOKEN`) 当前在 Qount 中的执行适配器和持仓对账**尚未闭合**。因此，本策略的 TradFi 部分目前仅能在 `shadow/virtual` 模式下或设置 `research_only=true` 运行，无法产生实盘交易订单。
> 2. **代码路径规范**：根据 `project-rules.md`，本策略作为主动 Sleeve，代码须落于 `src/qount/research/sleeves/`，运维入口位于 `scripts/research/sleeves/`，且必须默认 `orders_authorized=false`。

---

## 一、 Qount 架构视角的策略定位

在 Qount 中，我们不把定投看作是一个独立的、挂着 `crontab` 跑的脚本，而是将其注册为一个合规的 **Sleeve (策略套管)**：

1. **策略身份 (Strategy Registration)**：在注册表 (Registry) 中，本策略属于 `strategy_kind="continuous"` 的持续运行模型。
2. **组合分层 (Core-Satellite)**：依托 `portfolio_governance.py`，本定投策略可作为主动卫星仓 (Active Satellite Sleeve) 存在。您可以将资金划分为两部分：一部分分配给 `L1_PASSIVE_ALLOCATION` (被动持有不卖出)，另一部分分配给本策略执行“低买高抛”。
3. **资金无感执行**：策略无需维护状态查询 Binance 的现金余额。它只需要向执行器 (`executor.py`) 宣告其针对目标标的的**目标权重 (`target_weights`)**，风控引擎 (`risk_engine.py`) 会负责资金可用性的硬性约束。

---

## 二、 动态权重 (Target Weight) 决策模型

在传统的动态定投中，常陷入“硬编码固定阈值”（如偏离均线 30% 就清仓）的过拟合陷阱。由于不同资产（如 BTC 与 SPY_TOKEN）的波动率存在天壤之别，且强趋势资产的尾部风险极大（卖飞即踏空整个牛市），固定的硬性阈值往往导致跑输最简单的无脑定投。

为此，本设计在 Qount 中引入**结构性优化 (Structural Optimization)**，摒弃固定百分比，采用**波动率归一化 (Z-Score)** 与 **核心-卫星底仓机制 (Core-Satellite Base)**。

### 1. 核心改进机制

1. **资产中立的波动率衡量 (Z-Score)**：
   计算标的价格相对于 20周均线 (20W MA) 的标准差得分：`Z = (Price - 20W_MA) / 20W_StdDev`。
   - 这使得策略能够无缝跨资产运行：SPY 的 Z=2 和 BTC 的 Z=2 在统计学上代表相同的极端狂热程度，无需为不同资产人工设置偏离参数。
2. **防踏空的底仓锁定 (Structural Floor)**：
   定投策略的终极敌人不是短期的回撤，而是**卖飞后踏空整个宏观牛市**。因此，本策略强制限定 `target_weight` 永远不允许等于 `0.0`。设定 `Floor = 0.5`，即无论市场多么狂热，始终保留 50% 的核心底仓享受长尾复利，仅用剩余的 50% “卫星仓位”进行高抛低吸。

### 2. 意图映射表 (Stateless Target Weight)

在 Qount 的合约 (`StrategyIntent`) 中，依据 Z-Score 计算出的 `target_weight` 将作为本周的绝对目标占比宣告给 Executor。策略无需读取上周状态，实现了纯函数式的意图输出：

| 市场偏离状态 | Z-Score (相较 20W MA) | Target Weight 目标占比 | 动作释义 | Qount Reason Code |
| :--- | :--- | :--- | :--- | :--- |
| **极端狂热期** | `Z > 2.0` | **`0.5`** (触底下限) | 极度高估。通过降至 0.5 卖出 50% 卫星仓位锁定利润，但死守 50% 核心底仓防踏空。 | `DCA_TAKE_PROFIT_EXTREME` |
| **偏高估期** | `1.0 < Z <= 2.0` | **`0.7`** | 轻微获利了结，停止占比扩张，囤积更多现金。 | `DCA_TAKE_PROFIT_MILD` |
| **正常定投期** | `-1.0 <= Z <= 1.0` | **`0.9`** | 维持高比例运转。保留 10% 现金流以备日常波动。 | `DCA_NORMAL_BUY` |
| **恐慌低估期** | `Z < -1.0` | **`1.0`** (满仓状态) | 情绪恐慌，估值极具吸引力。消耗所有积攒现金全仓抄底。 | `DCA_MAX_ALLOCATION` |

> 🧮 **定投的数学本质**：
> 每周新增的 $10 会使得子账户 NAV 分母持续变大。在正常期 (`0.9`)，Executor 会自动消耗刚打入的部分现金来维持 90% 的占比，这就实现了平滑的 DCA。而在高估期 (`0.7`)，除了不买入新币，还会强制卖出超标部分，完美切合意图驱动的净额计算。

---

## 三、 标准化契约生成 (StrategyIntent)

无论是 Crypto 还是 TradFi 资产（例如 Binance 体系内或合成资产下的 `SPY_TOKEN`），在 Qount 中都享有同等的 `Symbol` 抽象地位。

以下是适配 `src/qount/contracts/strategy.py` 中 `StrategyIntent.create` 签名的伪代码实现：

```python
from qount.contracts.strategy import StrategyIntent

def generate_dca_intent(snapshot, history) -> StrategyIntent:
    # --- Z-Score 权重计算逻辑省略 (参考第二节表单) ---
    btc_target_weight = 0.9  # 根据 Z-Score 映射得出 (如 Z=0.5)
    spy_target_weight = 0.7  # 根据 Z-Score 映射得出 (如 Z=1.5)
    
    # 组装跨资产统一 Intent
    intent = StrategyIntent.create(
        schema_version=1,
        strategy_id="l1_dynamic_dca_cross_asset",
        strategy_version="1.0.0",
        snapshot_id=snapshot.snapshot_id,
        decision_time=snapshot.decision_time,
        data_cutoff=snapshot.data_cutoff,
        target_weights={
            "BTC/USDT": btc_target_weight,
            "SPY_TOKEN/USDT": spy_target_weight 
        },
        expected_holding_bars=1,             # 周级别定投，预期至少持有到下周
        target_stress_loss_fraction=0.20,    # 设定该策略的最大容忍压力回撤
        reason_codes=["DCA_CROSS_ASSET_REBALANCE"],
        evidence_hash=generate_evidence_hash(history),
        state_hash=snapshot.account_snapshot_hash or "empty_state"
    )
    return intent
```

---

## 四、 Qount 架构执行流闭环

1. **组合治理 (Portfolio Governance)**
   * 当上述 `StrategyIntent` 抛出时，`portfolio_governance.py` 会对其进行接管。它会验证 `target_weights` 总和（此处为 0.7）未超过 1.0（禁止裸做空或杠杆）。
2. **统一网关执行 (Executor)**
   * 得益于 Binance 等现代平台的跨资产支持，`executor.py` 不需要去维护多个隔离的券商 API Session。
   * Executor 比对上一次的快照差异。如果 BTC 需增仓、SPY 需减仓，Executor 会自动将其翻译为标准的 Limit / Market Orders 并发往单一交易所接口。
3. **资金沉淀优势**
   * 本策略在“偏高估期”虽然停止买入，但这并非意味着系统的钱处于绝对闲置。在复杂的 Qount 架构下，多余的法币净值可以被底层系统自动转入收益聚合协议 (如 Earn / 货基) 赚取利息，直到本策略在“恐慌期”宣告 `target_weight = 1.0` 时瞬间调用。
