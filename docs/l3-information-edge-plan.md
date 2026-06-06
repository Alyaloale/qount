# L3 信息源边际计划：用非价量慢数据 + AI 攻 IC

> **状态(2026-06-06):L3 已按 §8 整体证伪。** S0.1 数据层落地;S1 kill-test 两条子路均证伪——
> **L3a**(稳定币供给→BTC 周线择时)无稳定样本外 IC(全窗口 |IC| 0.054 < 0.083、子窗口符号翻转
> + PBO 0.64);**L3b**(链 TVL 横截面)找到真实显著弱信号(|IC| 0.075、t=3.5、符号稳定、DSR/PBO 过)
> 但 token 收益 **effective_breadth 仅 1.68 < 逃逸阈 2.5**,要求 IC 仍 ~0.15、真信号只有一半。
> **§7 架构级广度根因在新数据源上原样复现:绑定约束是广度不是信号。** 回到 §7 诚实止盈;下一次
> 重启需真正结构性新输入(L1/L4/L5),非 L3 内部堆特征。证据链见 update-log.md 2026-06-06。

本文件是 §7 项目级诚实止盈之后的**重启计划**。重启的合法性来自
[profit-engineering-plan.md](profit-engineering-plan.md) §11.8 规定的唯一触发条件——
**结构性新输入**。L3 的结构性新输入是：**把信息源从价量特征换成非价量的慢数据
（链上流 / 交易所储备 / 稳定币供给 / 衍生品持仓 / 叙事），horizon 从 4h 抬到日/周线，
把 AI 从最终 gate 挪到慢特征生成层。**

> 纪律不变：本计划全程 research-only；live 关闭、不 forward paper、不放宽 broad gate、
> `validation_v1` once-only、一轮只改一处、先写单测。任何一步不证伪就不投入下一步。

---

## 0. 为什么是 L3（接 §11.8 的对账）

§7 诊断把可盈利空间钉死成一句话：`IR = IC × √BR`，当前设计两项同时触顶——
**BR 有效 ~1.6（majors r̄≈0.63 的相关天花板，扩币救不了）、IC ~0.05（价量特征在 majors
上的横截面预测内容）**，要求 IC ~0.15 不可达。

可盈利重设计**必须结构性换掉 BR / IC / 游戏之一**。L3 选择**换 IC 的来源**：

- 价量特征是加密里最拥挤、最被数据挖掘的信号面；majors 的价量横截面 IC 0.05 是其上限。
- 非价量慢数据（链上 / 流 / 持仓 / 基本面）在**日/周线**上 IC 可能更高，且：
  1. **延迟无关**——周线决策，操作者「cron + 代理 + WSL + 秒级延迟」不再是劣势；
  2. **AI 真正增值**——把原始链上序列变成特征需要判断（哪些流重要、regime 上下文、
     lead/lag），这是「慢 + AI + 耐心」操作者的比较优势，而不是 5m 上徒增延迟与 hold-bias；
  3. **容量大、换手低**——周线持仓，成本不再主导（§10.1 的三重受益在更低频上更强）。

**L3 攻的是基本定律的 IC 项；BR 项的处理见 §2（这是 L3 最容易自欺的地方）。**

---

## 1. 目标架构（与现有系统的关系）

```text
现有(冻结):  5m/4h 价量 → 16维 linear ridge → AI 最终 gate → ETH 单仓
L3(新线):    日/周线非价量慢数据 → AI 慢特征生成/regime 标注 → 预设经济假设的 IC 检验
             → (过门才) 仓位 → 最液体单一标的(L3a) 或 主题篮子(L3b)
```

- L3 是**独立研究线**，不改现有 `run-once` / live / setup model。
- 复用 §7 的反过拟合 harness（`strategy_selection.py` 引擎：rank-IC、purged-CV+embargo、
  DSR、PBO/CSCV、effective-breadth）作为验证骨架——这是项目最有价值的资产，现在指向新数据源。
- 复用现有 executor / risk / journal；L3 若 live 化是**独立工程轮**，先单测、先 paper。

---

## 2. 广度诚实检查（L3 最致命的自欺点）

**L3 不自动修广度。** 若在 12 个 majors 上做横截面，BR 仍是 ~1.6，要求 IC 仍 ~0.15。
所以 L3 必须明确分两条子路，**S1 kill-test 必须报出 breadth-adjusted 要求 IC**：

### L3a — 市场择时（广度来自时间，要求 IC 低）★ 首选
- 用宏观流信号（稳定币供给 Δ、聚合资金流、全市场持仓极值）**择时单一最液体标的**
  （BTC 或市场 beta）。
- 广度来自**独立的周**：3–4 年 ≈ 150–200 周 → √150 ≈ 12 → **要求 IC(IR=1) ≈ 0.083**，
  显著低于横截面的 0.15，更可达。
- 执行最干净：单一最液体标的，成本/滑点最小。
- 经济动机最硬：稳定币供给 = 入场干火药，是有文献的宏观流→市场回报信号。

### L3b — 横截面（广度受相关封死，要求 IC 高）
- 用 token-specific 链上（交易所净流、TVL/fee 增长）横截面排序一篮子。
- **诚实**：价格 r̄≈0.63 的相关天花板仍在；除非链上信号本身制造横截面 dispersion
  把**信号维度**的有效相关压到 < 0.4（有效广度 > 2.5），否则要求 IC 仍 ~0.15。
- S1 必须直接测：链上信号横截面的 effective_breadth 与 rank-IC，二者一起判生死。

> **优先级：先做 L3a。** 它要求 IC 低、执行干净、假设最硬。L3b 只在 L3a 证伪后、或 L3a
> 成立想加正交 sleeve 时再做。

---

## 3. 数据源（免费 / 零售可得 / 不需新交易所）

| 类别 | 信号 | 免费源 | 备注 |
| --- | --- | --- | --- |
| 稳定币供给 | USDT+USDC mcap、增速 | DefiLlama API（免费） | L3a 核心宏观流 |
| 链上 TVL / 费 | 链 / 协议 TVL、增速 | DefiLlama API | L3b 基本面 traction |
| 交易所流 | 净流入/出、储备 | CryptoQuant/Glassnode 免费档、或链上 explorer | 噪声大，需 AI/清洗 |
| 衍生品持仓 | 聚合 OI、跨所 funding、多空比、清算 | CoinGlass、Binance fapi（已接） | 周线持仓极值 |
| 市场结构 | 全市场 mcap、成交、BTC 占比 | CoinGecko API（免费） | regime 上下文 |

- **第一刀只用 DefiLlama（稳定币供给）+ 已接的 Binance fapi**——最可靠、最免费、最少新依赖。
- 所有外部拉取走现有代理基建；数据落 `state/` 缓存，离线复跑（同 `--ai-decision-cache` 思路）。
- 链上流类信号噪声大、口径乱，**第一阶段不碰**，等 L3a 的稳定币假设先证真/证伪。

---

## 4. 最便宜的 kill-test（S1，决定 L3 生死）

**问题（L3a）**：稳定币供给增速在周 t 是否预测 BTC（或市场 beta）t→t+1..t+4 周的 forward
return，扣费后、样本外、且过 DSR/PBO？

```text
数据:   DefiLlama 稳定币总供给周线（尽量长，3-4 年）+ BTC 周线 close
信号:   stablecoin_supply 的 z-score / Δ / 增速（严格 as-of，无前视）
目标:   BTC forward return 1..4 周
读数:   时序 rank-IC / IR、扣费净值、DSR（多 horizon = 多 trial）、
        purged-CV+embargo（周线 embargo 防泄漏）、月度/年度稳健性
判生死: breadth-adjusted 要求 IC ≈ 0.083；若 |IC| 显著 < 0.083 或 DSR 不过 → L3a 证伪
```

- 这一刀**廉价**：单一标的、单一免费数据源、复用现有 IC/DSR harness，几小时内出结论。
- 若 L3a 证伪，再以同样廉价方式测 L3b（链上横截面）；若两者都证伪，则 L3 这条信息源也按
  §7 诚实退出，回到「接受研究价值、停止追盈利」。

---

## 5. 分步执行计划（带 kill-test 门控）

```text
S0  地基（无策略行为变化）
    S0.1 数据接入层: DefiLlama / CoinGecko fetch + state 缓存 + 归一化(as-of, 无前视)
         —— 先写单测(归一化、as-of join、缓存命中)
    S0.2 holdout 切分沿用 discovery / validation_v1；周线 embargo 规则明确

S1  KILL-TEST: L3a 稳定币→BTC 择时 时序 IC   ← 决定 L3 生死
    门控: breadth-adjusted 要求 IC ≈ 0.083；|IC| 显著达标 + DSR/PBO 过 + 年度稳健 → 进 S2
          否则测 L3b；L3b 也不过 → §7 退出

S2  特征层 + AI 重定位（仅当 S1 正）
    S2.1 把单信号扩成一组**经济预设**特征(供给增速/加速度/跨稳定币背离/与价格背离)
         —— 不是网格搜索；每个特征有事前经济假设
    S2.2 AI 慢特征/regime 标注层(§P5): LLM 读多源慢数据输出 regime 标签/特征，
         不做最终 gate；先 offline、先单测、先证它的标注有增量 IC

S3  组合与 sizing（仅当 S2 有可执行正 lift）
    S3.1 单标的择时 → 仓位规则(分数 Kelly, 周线再平衡)
    S3.2 若 L3b 成立: 主题篮子横截面 + effective-breadth 实测把关

S4  纸面验证（仅当 S3 有 holdout 正 edge）
    S4.1 validation_v1 once-only 完整窗口复核（仍不烧薄窗口）
    S4.2 过 G_paper 才讨论 forward paper；过 forward paper 才讨论 G_live

S5  兜底/扩展: 加正交慢数据 sleeve(衍生品持仓极值、TVL traction)，各自独立 kill-test
```

每步之间是**硬门控**：不证伪不前进。S2 重 AI/特征只在 S1 正 IC 后启动，重蹈
profit-engineering-plan「先证伪再投入」纪律。

---

## 6. 反过拟合（周线样本少，门更要紧，不是更松）

- **样本稀缺是 L3 头号风险**：周线 3–4 年 ≈ 150–200 obs。对策：
  1. **经济预设假设**，不在特征空间网格搜索（每个特征事前有动机，trial 数小且登记在案）；
  2. **DSR 按真实 trial 数惩罚**（多 horizon × 多特征都计入 trial）；
  3. **purged-CV + 周线 embargo** 防持仓重叠泄漏；
  4. 接受结论可能是「弱但真」而非「强」——弱信号若 DSR 过、经济动机硬、容量大，仍可做；
  5. **effective-breadth 必报**：L3b 不报有效广度不算数。
- 复用 §7 已落地的 `compute_directional_deflated_sharpe` / `compute_directional_pbo` /
  `_effective_breadth`；周线 horizon 下按需补 CPCV 多路径分布（profit-engineering-plan §11.3
  记的待补项）。

---

## 7. 硬约束（全部继承，不放宽一条）

- live 关闭 `QOUNT_LIVE_ENABLE=false`；不 forward paper、不放宽 broad gate、外部模型/AI 不进
  candidate/risk/live（AI 只做 offline 慢特征/regime 标注，且其输出也要先证有增量 IC）。
- 不在 `discovery_pool` 调参后当 promotion；`validation_v1` once-only，不烧薄窗口。
- 一轮只改一处、先写单测；本地 unittest → sync-to-wsl → WSL unittest → 研究命令 →
  artifact 落 `state/research_runs` → 写回 current.md / update-log.md。
- Mac 是编辑/git 表面，WSL 是生产/回测真相。

---

## 8. 全局终止条件（L3 自己的诚实退出）

继承 §7：若 L3a（稳定币→市场择时）与 L3b（链上横截面）在 holdout 上都无统计显著、扣费后、
DSR/PBO 可接受的正 edge，则**L3 这一信息源也证伪**，按 §7 接受研究价值、停止追盈利——
不在已耗尽的慢数据空间里继续堆特征/调参（那只会触发多重检验假象）。下一次重启仍需**新的
结构性输入**（L1 跨资产 / L2 事件驱动 / L4 跨所套利 / L5 换目标），而非 L3 内部的微调。

---

## 9. 一句话

> §7 证明了「majors × 价量 × 择时」盒子里没有 retail-accessible alpha。L3 不在盒子里加旋钮，
> 而是换盒子的**信息源**——用延迟无关的慢数据 + AI 慢判断攻 IC，优先做要求 IC 最低、执行最干净、
> 经济动机最硬的**稳定币供给→市场择时**。第一刀就是它的廉价 kill-test；不过则诚实退出。
