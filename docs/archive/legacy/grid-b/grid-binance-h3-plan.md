# GRID-B H3 预注册实施计划 v0.6:Delta-neutral 资金费 Carry —— 网格族最深一层 kill-test

> **状态**：archived/falsified（GRID-B 已收口 2026-06-11，已归档）｜索引见 [archive/README.md](../../README.md)｜当前事实以 [current.md](../../../current.md) 为准。

状态:**已实现 + 已判生死(2026-06-11)** · v0.6 · 代号 **GRID-B** · **H3-A FAIL(物理尾部门),网格族最深一层证伪,线 B 彻底收口(§8.6)**
上游:[grid-binance-next.md](../../../grid-binance-next.md)(S1/S1c/S1d/S1e 全证伪 + §5 收口)·
[grid-binance-s1e-plan.md](../../../grid-binance-s1e-plan.md)(H1 最深操作化)

> 属线 B,隔离边界见 [grid-binance-plan.md](../../../grid-binance-plan.md) 开头声明;变更只写回本线文档,
> **不写 `current.md` / `update-log.md`**。

---

## 0. 这份文件的合法性:为什么不是「旧假设换参数」

线 B 已于 2026-06-11 收口(S1/S1c/S1d/S1e 四轮 kill-test,H1/H2 双死)。收口纪律明文:
**重启须带新假设(新结构 / 新本位 / 新市场),不是旧假设换参数。** H3 满足该条:

- **新结构**:从 long-only(净多头、短 Gamma 裸奔)→ **delta-neutral**(永续对冲库存 Δ,把方向税锁死);
- **新市场**:从 BTC/ETH 现货 → **高资金费山寨永续**(资金费量级结构性更高,未被证伪过);
- **新真身**:剥掉网格皮,本体是 **资金费 Carry + 卖已实现方差**,不是「波动率收割」。

### 0.1 owner 决定:Tier-2 禁令对 H3 解除(2026-06-11)

`grid-binance-optim.md` §5 / `grid-binance-next.md` §6 的 **「Tier-2 永续生息叠加,维持不碰」** 禁令,
经 owner 显式决定,**仅对 H3 解除**(H3 的全部内容就是永续对冲腿)。其余线 B 不做清单继续有效。
理由:H3 不是「在 live 网格上叠永续生息」,而是把永续对冲作为**结构本体**做一轮诚实 kill-test。

### 0.2 核心诊断(承接上一轮,H3 的全部动机)

现货 long-only 网格 = **劣质合成 short put = 做空 Gamma**。其 PnL 分解(期权恒等式):

```
delta-hedged short-gamma 每次再平衡 PnL ≈ θ·dt − ½·Γ·(dS)²
                                          └carry┘   └已实现方差 项┘
```

推论(上一轮已证):**一旦做 delta-neutral,harvest(θ)与再对冲成本(½Γ(dS)²)是同一枚硬币
两面,大幅抵消。净额 ≈ 资金费 − 成本 − (已实现方差项)。** 网格那层 harvest 自己抵消掉了,
**剩下的唯一可能 edge 是资金费 carry。** 这就是 H3 要判生死的全部。

---

## 1. 核心假设(H3)与真 baseline(洞 1 修订)

**H3 命题**:在高资金费山寨永续上,delta-neutral 结构(现货多头 + 永续空头)的资金费收入,
在严格扣除【再对冲滑点 + 双边往返费 + 基差波动 + ADL/脱锚/退市尾部】后,净 EV 是否**结构性为正
且扛过周期**。

**关键修订(洞 1)——网格在 Path 1 里也是寄生虫**:delta-neutral 下永续空头 notional ≈ 现货库存,
而网格库存与价格**反相关**(越跌买越多)→ 狂热期(资金费最肥)空头最小、暴跌期(资金费转负)空头
最大,**网格调制把 carry 钉在与资金费完全反相位的节奏上**。故:

| 配置 | 定义 | 角色 |
|---|---|---|
| **H3-A 静态 carry(真 baseline)** | 恒定 notional 的 delta-neutral 空头,只收资金费 + 每 bar 对冲到平 | **本体**:carry 本身正不正 |
| **H3-B 网格调制** | 现货跑网格,永续按库存动态对冲到 Δ=0(Path 1 原案) | 对照:网格加不加分(**预测:减分**) |

**判定逻辑**:先判 H3-A;A 不过 → 网格族在最深层证伪(连静态 carry 都救不了),永久收口。
A 过、B 不过 → edge 在 carry 不在网格(找到一条 carry sleeve,可归并线 A carry 研究;网格仍死)。
A 过、B 也过且 B≥A → 唯一值得继续的小概率分支(不预期发生)。

---

## 2. 基建改造点(Harness Modifications,bar 级即可)

复用真实接口:`grid/data.py` `load_klines`/`Bar`、`grid/engine.py` `GridLadder`/`build_grid`/
`apply_buy_fill`/`apply_sell_fill`/`equity`、`grid/backtest.py` `_hold_above_ma`/`daily_states_by_date`/
`_max_drawdown`/`_year_of`。**新增 `run_h3()` + `H3Result`,不动 `run_s1*`。**

### 2.1 数据源扩充

- `grid/data.py`:`load_klines` 加 `market` 参数(`spot` | `um`),永续走 binance.vision
  `data/futures/um/...`;现货 vs 永续**各自独立撮合价**(洞 4)。
- **新增资金费序列加载**:binance.vision `futures/um/monthly/fundingRate`(8h 结算)→ 新函数
  `load_funding(symbol, start, end) -> list[(ts, rate)]`;严格按结算时点对齐 bar。

### 2.2 双腿账本(Dual-Leg Ledger)+ 收益正交分解(验证抵消定理)

```
H3Result 账目(严格正交,跑完必须分列):
  harvest_pnl   现货网格纯往返买卖差价(H3-B 用;H3-A 恒为 0)
  rehedge_pnl   永续腿追 Δ 中性的方向性损耗(高买低卖)
  funding_pnl   资金费累积 —— 必须按【时变空头 notional】结算,非固定 notional(洞 3)
  fee_cost      现货 maker/taker + 永续对冲强制 taker + 滑点 buffer
  residual_delta_pnl  收盘后残余 Δ 的方向 PnL(基线应 ≈0,做健全性读数)
  net = harvest + rehedge + funding − fee + residual
内部验证(H3-B):|harvest_pnl| 与 |rehedge_pnl| 应同量级(抵消定理的实测确认)
```

### 2.3 对冲节奏钉死(洞 3,反 forking-path)

基线:**每根 bar 收盘把组合对冲到 Δ=0,无容差 band**。永续对冲腿按 bar 最劣价 + 滑点 buffer
成交(洞 4 保守偏置)。band 宽度 / 懒对冲是**过门后**才允许动的 O 级旋钮,不在基线。

---

## 3. 极值与尾部处理(杀机所在,严禁平滑)

- **基差脱锚(Basis Dislocation)**:现货/永续按各自市场价撮合,**严禁用现货价替代永续回补价**。
- **毒性流滑点(Toxic Flow Slippage)**:对冲是市价追单;山寨 dump bar 内振幅极大,对冲单 `fill_price`
  按该 bar **最劣价**(或保守加权)计,严禁按 close 无损成交。
- **ADL 模拟**:单 bar 涨幅 > 阈值(如 +20%)→ 按比例强平对冲空头、强制更高价重建,记惩罚损耗。
- **退市/归零(洞 6)**:死亡标的(LUNA/FTT 类)现货腿按**终值 −100%** 计入账本,**不剔除**;
  这些标的只作**尾部生死局单列**,不进 §1 主 universe 的常规统计。

---

## 4. 预注册判生死(跑前钉死;含洞 2/6 修订)

**universe(洞 2,反选择偏差)**:**point-in-time 规则选取**——每月按过去 30 日 ADV 取 top-N U 本位
永续,含当时存活的全部标的,不偷看未来、不按资金费筛选。资金费是观测量。LUNA/FTT 仅尾部单列。

**样本下限(洞 6)**:每标的 ≥3 年或 ≥2 个完整周期方计入主统计;不足者只作诊断。

**判据(H3-A 三项全过才算 carry 活):**

```
(1) 绝对净额:扣全部成本后 Net_Annualized > +2%
(2) 时间鲁棒:净额为正的年份 ≥ 4/6(或可交易期 ≥66%)
(3) 尾部生存:把历史最坏单次尾部(资金费深负 + 基差瞬间 >10% + ADL)完整计入后,
            项目期总净额仍 > 0 —— 不允许「单次黑天鹅吃掉多年 carry」的隐性脆弱

H3-A 过 → 判 H3-B:B 的 net 是否 ≥ A(网格是否加分)。预期 B < A(洞 1)→ 网格死、carry 活。
H3-A 不过 → 网格族最深一层证伪 → §6 永久收口。
```

**无中间带救援**:carry 是结构性的,擦边不过即不过,不调参续命(forking paths)。

---

## 5. 单测规划(先写测;含洞 5 修订)

新增 `tests/test_grid_h3.py`:

```
□ test_delta_neutral_offset(洞 5):人工正弦波 + 无费无资金费下,
   断言 harvest_pnl + rehedge_pnl ≤ 0 且 |残差| ≤ 离散化容差
   （离散对冲 short gamma 系统性亏于连续 = 物理正确,残差为负不是 bug)
□ test_funding_accumulation:跨 8h 结算点的 bar,资金费按【时变空头 notional】正负扣款精确,
   不重复/不漏算(洞 3)
□ test_funding_on_varying_notional:库存增大时空头 notional 同步增大→资金费基数随之变(洞 1/3 联检)
□ test_basis_dislocation_hit:注入永续偏离现货 15% 的异常 bar,验证对冲重置成本真实造成大额放血
□ test_adl_simulation:单 bar +20% → 空头被按比例强平 + 更高价重建,惩罚损耗入账
□ test_delisting_terminal_loss(洞 6):死亡标的现货腿终值 −100% 正确入账,不被剔除
□ test_static_vs_grid_leg(洞 1):H3-A 恒定 notional 与 H3-B 库存调制的 funding 基数差异可复现
□ test_h3a_zero_harvest:H3-A 配置下 harvest_pnl 恒为 0(无现货网格往返)
```

预期 grid 模块单测 56 → ~64,全绿才跑 artifact。

---

## 6. 收口预案(若 H3-A 不过——预期主路径)

H3-A 是网格族最深一层(delta-neutral + 高资金费山寨)。它败 = 连 carry 都救不了 → **网格族彻底死**。
按 L6 / S1e 同型收口:

1. **结论定稿**(写入本文件 §8 + grid-binance-next.md changelog):网格在加密资产上,无论标的(S1c)、
   时间(S1e)、还是剥皮后的 delta-neutral carry(H3),扣费 + 尾部后均无结构性正 EV。
2. **资产清点**:`grid/` 全模块 + ~64 单测 + S1/S1c/S1d/S1e/H3 artifact;新增的**永续对冲腿 +
   资金费账本 + ADL/基差模拟**定性为可复用资产(任何 delta-neutral / carry 研究可借)。
3. **线 B 状态维持「已收口」**,H3 作为「收口后唯一授权的新假设 kill-test」记录在案;再重启须**再**带新假设。
4. **若 H3-A 过、H3-B 不过**:carry sleeve 单独成立,定性为「线 A carry 研究的加密候选」,
   网格仍判死;后续归并由 owner 决定。

---

## 7. 诚实预测(防自我感动,跑前写下)

按抵消定理 + 洞 1:H3-B 的 harvest≈rehedge 抵消,且库存调制与资金费反相位 → **H3-B 大概率 < H3-A**。
H3-A 本身:山寨资金费 mania 期年化可 50–200%,但 dump 期深负 + 基差脱锚 + ADL 高度**正相关**
(同时发生)→ 我赌 **整窗口被尾部腿拉回 ~0 或负**,即又一次 sub-gate carry,只是这次死在 carry 门
而非方向税门。但它**没被测过**,值得一周买个「死得更深的明白」。若结果勉强过 (1) 而 (2)/(3) 擦边,
先回看是不是少数 mania 月在抬轿(同 S1d 局限),不急着认。

---

## 8. 实测结果

**真实判据待跑**:需对 point-in-time 选出的 universe 跑**全窗口 2021-01..2026-05**(含 dump 段负
资金费 + ADL + 基差尾部)才出 §4 三判据的真结论。artifact 落 `state/grid_b/research_runs/h3_*.json`。

### 8.1 管线冒烟测试(2026-06-11,**非判据**,DOGEUSDT 2024-01..2024-02 两月窗口)

仅验证 Increment 2 数据/编排管线在真实数据上跑通,**刻意短窗、不是 §4 判据**(单年、正资金费段、
无 dump/ADL,c2 以 1/1 年通过=洞6 弱点,需全窗口才有效)。两个核心机制在真实 DOGE 上确认:

| 配置 | net | harvest | spot_inv | perp_dir | funding | offset_residual | 读数 |
|---|---|---|---|---|---|---|---|
| **H3-A 静态** | +2.66% | 0.00% | +31.00% | −31.10% | +2.91% | **−0.10%** | delta 中性成立,方向精确抵消,funding=carry |
| **H3-B 网格** | −18.20% | +5.83% | −1.46% | −22.51% | +0.50% | **−23.97%** | 480 次按 bar 最劣价 rehedge,harvest 被碾碎 |

确认:① **offset 定理**——H3-A 的 spot_inv(+31%)被 perp_dir(−31.1%)抵消到 residual −0.10%,
净额=funding−fees;② **洞1/offset 在真实数据**——H3-B harvest +5.83% 被 perp_dir −22.51% 吃光,
H3-B ≪ H3-A,正是预测方向。**注**:H3-B 的 rehedge 用 bar 最劣价(洞4 故意保守),其量级不宜过读;
但 H3-A(判据之门)不依赖网格 rehedge,故此保守性不污染判据之门。decomposition 严格求和到 net
(+5.83−1.46−22.51+0.50−0.55=−18.19✓)。

### 8.2 首个全 panel 跑 = 无效(发现 bug,与 S1e 播种 phantom 同型,2026-06-11)

9 候选全窗口首跑出非物理数字(组合 net +157796%、DOGE net −8426%、LUNA basis 15900%、
offset_residual −10705%)。**不采信、不当判据**(预注册纪律双向:不能从崩坏数字宣布收口)。根因两条:

1. **ADL 模型严重过触发(主 bug)**:预注册 §3「单 bar >20% → 强平 50%」对加密山寨一年触发几十次,
   币本位空头(`cap/spot0`,巨量币数)× 大价差 → 单次实现 −300%+,33 次复利 = −8426%。
   **诊断铁证**:`adl=0` 的 ETH/LINK **完美干净**(offset +0.20%/+0.11%,net=funding);爆炸**全部**
   来自 `adl>0` 标的。核心账本对,ADL 那条 spec 写错了。
2. **LUNA 数据 artifact**:basis 15900%(159×)= LUNC 崩盘后重命名/重发行,现货/永续指向不同标的。

### 8.3 修正后 = 有效结果(option a:ADL 后置 + basis guard,2026-06-11)

owner 选 **(a)**:移除 ADL 腿(`enable_adl=False`,降级为后置独立尾部压力测试,像 S2 maker 墙);
`_align` 加 basis guard(|basis|>100% 的 bar 判脏数据剔除)。**这跑的是慷慨上界**——constant-coin-base
的 delta-neutral 空头 notional 随币价上涨(100x 币=100x 美元空头),funding 在膨胀 notional 上累积,
**假设无清算、无限保证金**(正是 ADL 笨拙想抓的真杀机)。与 S1 的 look-ahead 区间同性质:**连上界不过就死;
过则膨胀空头的清算/保证金是后置真尾部门。**

| 标的 | net | funding | offset_residual | basis | 读数 |
|---|---|---|---|---|---|
| BTCUSDT | +113.96% | +113.95% | +0.16% | 2.1% | 干净 |
| ETHUSDT | +220.76% | +220.71% | +0.20% | 2.5% | 干净,6/6 年正,maxDD −3.52% |
| BNBUSDT | −58.35% | −57.34% | −0.86% | 1.8% | funding 本身为负(BNB 多数时段负费) |
| SOLUSDT | +2485.10% | +2482.23% | +3.02% | 23.9% | funding 在膨胀 notional 上累积(注) |
| XRPUSDT | +296.38% | +296.41% | +0.12% | 4.0% | 干净 |
| DOGEUSDT | +2314.25% | +2313.60% | +0.80% | 3.3% | 同 SOL,mania notional 主导 |
| AVAXUSDT | +650.86% | +650.81% | +0.20% | 7.4% | 干净 |
| LINKUSDT | +155.69% | +155.73% | +0.11% | 2.8% | 干净 |
| **LUNAUSDT** | **+176.44%** | +179.30% | −2.70% | 96.1% | **崩盘段:丢3脏bar,perp 空头吃下 −99% 崩盘+funding,delta-neutral 扛过** |

**组合(point-in-time top-5,等权,月度重平衡)**:net **+300.16%**,年化 **+29.18%**,正收益年 **4/6**。
分年:2021 +294% / 2022 −16.65% / 2023 −2.72% / 2024 +16.20% / 2025 +3.23% / 2026 +4.40%。

**§4 三判据**:(1) 年化 +29.18% > +2% ✓ · (2) 4/6 ≥ 66% ✓ · (3) 尾部生存 net +300% > 0 ✓ →
**H3-A 三项全过**。这是**线 B 第一个通过自己 kill-test 门的构型**(S1/S1c/S1d/S1e 全败)——
**剥掉网格皮后,真身(delta-neutral 资金费 carry)在慷慨上界下为正**,印证「网格从来不是 alpha,真身是 carry」。

> **三条诚实注记(防自我感动,与 S1 look-ahead 同型)**:① 这是**上界**——假设膨胀空头永不清算/
> 保证金无限;真 sleeve 必须过后置尾部门(pump 中空头被挤爆的 gap risk),那会咬掉一大块。
> ② **notional-scaling**:SOL/DOGE 的 +2482%/+2313% 是 funding 在「随币价涨到 10–100×cap 的 notional」
> 上累积,对**初始**资本的 %,被 mania 杠杆放大;对**平均部署 notional** 的真实 %/yr 小得多(数十 %)。
> ③ **集中度**:组合被 SOL/DOGE 两个 mania 标的主导,等权也压不住。

### 8.4 H3-B 对照(洞1 在真实数据的铁证)

同一 ETHUSDT 全窗口,static vs grid:

| 配置 | net | funding | harvest | offset_residual | rehedges |
|---|---|---|---|---|---|
| H3-A 静态 | **+220.76%** | **+220.71%** | 0.00% | +0.20% | 1 |
| H3-B 网格 | **−114.11%** | **+7.36%** | +67.06% | −182.76% | 16439 |

**洞1 铁证**:同一标的同一窗口,网格调制把 funding 从 **+220.71% 砍到 +7.36%**(−97%)——网格库存与
价格反相(狂热期卖光=funding 最肥时空头最小),carry 被钉在反相位;叠加 16439 次最劣价 rehedge
(offset −182.76%)→ net −114%。**H3-B ≪ H3-A 决定性成立:网格是 carry 的寄生皮,确认判死。**

### 8.5 物理尾部门暴露了框架的归一化缺陷(2026-06-11,**非判据**)

加 `run_h3(liq_leverage=L)` 物理清算门(intrabar pump 穿过清算价 → 罚金+gap;net 损失非整保证金,
因 spot 浮盈对冲)后跑杠杆 sweep,结果**不自洽**:

| 杠杆 | 年化 | net | 赢年 | liq_cost |
|---|---|---|---|---|
| ∞(上界) | +29.18% | +300.16% | 4/6 | 0% |
| 10x | +40.50% | +530.86% | 6/6 | **6205%** |
| 5x | **−100%** | −72374% | 4/6 | 1210% |
| 3x | +13.23% | +96.02% | 4/6 | 294% |

**非单调 = bug**:杠杆越高(清算越多)收益反而越高(10x +40% > 上界 +29%),5x 直接 −100%。根因
**与 ADL 爆炸同病第三次发作**:整个 H3 框架把一切都对**初始资本**计量,而 delta-neutral 的 **notional
随币价膨胀**(币本位空头,DOGE pump 80× → notional 80×cap)。于是:① liq_cost 是膨胀 notional 的 %,
对初始 cap 算出 6205%;② 单月收益能 **< −100%**(curve = cap + spot − perp − liq_cost,liq_cost 900%cap
→ 权益变负);③ 组合按 `∏(1+月收益)` 链式复利,一旦某月 < −100% 链就翻负 → 后续全是垃圾(10x 反超上界
的来源)。

**结论**:**sweep 的任何数字(含 L=3 的 +13%)都不可信,不能当判据。** 上界(§8.3)确立的是**符号**
(carry 为正、delta 中性 offset≈0)稳健;但**量级 + 尾部门**被「对初始资本计量 + notional 膨胀」污染。
正确修法是**框架级重构**:equity-normalized / 定期重平衡到「目标 notional = k×当前权益」的 sizing
(真实 carry 书的做法,不让单个头寸膨胀到 80×),使收益恒对**当前权益**计量、单月不破 −100%、清算成本有界。
这是一轮独立重构(改变被测对象的 sizing 定义),需 owner 决定。**H3-A 的最终判据待此重构后重跑。**

### 8.6 equity-normalized 重构 = H3-A 终判:**carry 真身也死在物理尾部门**(2026-06-11)

owner 选 A:做 `run_h3_carry`(equity-normalized)——头寸定期(日)重平衡到 **notional = k_gross×当前权益**
(k=1),清算 = 强平 + 在剩余权益上按当前价**重建**。收益恒对当前权益计量、notional 不膨胀、单月不破
−100%。清算门杠杆 sweep(top-5 EW 组合,+4 单测,grid 模块 99→103 全绿):

| 杠杆(空头) | 年化 | net | 赢年 | liq_cost | 判据 |
|---|---|---|---|---|---|
| ∞(上界,无清算) | **+4.70%** | +28.21% | 4/6 | 0% | PASS |
| 10x | −55.74% | −98.79% | 0/6 | 102% | FAIL |
| 5x | −12.35% | −51.02% | 0/6 | 74% | FAIL |
| **3x(预注册判据)** | **−0.83%** | **−4.41%** | **3/6** | 43% | **FAIL** |

**结果单调了**(杠杆越高越差=物理正确,§8.5 的非单调 bug 已除)。两个诚实读数:
1. **真实 carry 上界只有 +4.70%/yr**(非 §8.3 的虚高 +29%——那是 notional 膨胀的假象)。剥到最干净,
   delta-neutral 加密资金费 carry 在 1×权益、无清算假设下,就是个**单位数 %/yr 的薄 carry**。
2. **物理清算尾部门把它吃光**:任何资本有效的杠杆(L≥3)下,膨胀空头在 pump 中被挤爆的 gap(liq_cost
   43%~102%)> 上界 carry → net 转负。**L=3 预注册判据:年化 −0.83%、3/6 年、net −4.41% → 三项全不过。**

**§4 终判:H3-A FAIL。** 兑现了 §7 先验预测(「大概率被尾部拉回 ~0 或负 = sub-gate carry,死在 carry
门」)。**网格族最深一层(剥皮后的 delta-neutral 资金费 carry)在物理尾部下也不活** → §6 收口(本轮执行)。

> **完整 H3 结论**:① 网格本体判死(§8.4 H3-B≪H3-A,洞1 铁证,网格是 carry 寄生皮);② carry 真身
> 上界为正但**薄**(+4.70%/yr),物理清算尾部门(膨胀空头 pump 挤爆)吃光 → 实盘杠杆下 net 负 → 也判死。
> = 线 A「edge 量级 ~0 / sub-gate carry」教训在加密 delta-neutral carry 上的重演。**「网格从来不是
> alpha,真身是 carry」成立;但这个 carry 扣掉真实尾部后不够活。** 线 B 彻底收口。

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-06-11 | v0.6 | 本文件:收口后 owner 授权的新假设 H3(delta-neutral 资金费 carry)预注册实施计划。Tier-2 禁令对 H3 解除(§0.1)。核心修订(对 owner 草案的 6 处加固):洞1 真 baseline 改静态 carry(网格是 carry 的寄生皮)、洞2 universe 改 point-in-time 反选择偏差、洞3 对冲节奏钉死 + 资金费按时变 notional、洞4 两腿一致保守撮合、洞5 单测断言改 `≤0`(离散对冲系统性亏)、洞6 样本下限 + 退市终值 −100%。**只计划不实现**。 |
| 2026-06-11 | Increment 1 | **§2.2 双腿账本核心落地**(先写单测):新增纯模块 `src/qount/grid/perp.py` `PerpHedgeLeg`(平均成本做空账本 + 时变 notional 资金费 + 基差/ADL),`tests/test_grid_h3.py` 14 单测全绿(grid 模块 56→70)。验证:**offset 定理**(无摩擦下 spot harvest + perp hedge 精确抵消 net≈0,places=8;含费后严格 net<0=洞5)、资金费按时变 notional 且 rate>0 时空头收取(洞3)、对冲空头与库存同向→与价格反相(洞1)、基差脱锚回补真实放血 + ADL 强平惩罚(洞4)。**不动 `run_s1*`。** |
| 2026-06-11 | Increment 2 | **数据层 + 编排 + 脚本落地**(先写单测):`data.py` 加 `market`(spot/um)参数 + `Funding`/`parse_funding_csv`/`load_funding`(binance.vision `futures/um/monthly/fundingRate`),`backtest.py` 新增 `run_h3()`+`H3Result`(H3-A 静态 carry / H3-B 网格调制,4 账户正交分解严格求和到 net,worst-of-bar rehedge + ADL + 基差),`scripts/research/grid_b_h3.py`(单标的真跑 + §4 判据对账)。单测 grid 模块 70→86 全绿(perp 14 + data 7 + run_h3 9)。**管线在真实 DOGE 数据上跑通(§8.1 冒烟测试,非判据)**,offset 定理与洞1 在真实数据确认。 |
| 2026-06-11 | Increment 3 | **point-in-time universe + 全窗口真判据**(先写单测):新增 `src/qount/grid/universe.py`(`trailing_adv`/`select_universe`,洞2 反选择偏差,+7 单测,grid 模块 86→93 全绿)、`scripts/research/grid_b_h3_panel.py`(9 候选月度选 top-5 等权组合)。**首跑无效**(ADL spec 过触发 + LUNA 数据 artifact,§8.2,与 S1e 播种 phantom 同型);owner 选 (a):`run_h3` 加 `enable_adl=False`(ADL 后置)+ panel `_align` 加 basis guard。**修正后有效结果(§8.3,慷慨上界)**:组合年化 +29.18%、4/6 年正、三判据全过 → **H3-A 是线 B 第一个过门的构型**(剥皮后真身 carry 为正)。§8.4:同 ETH static funding +220.71% vs grid +7.36% = 洞1 铁证,**H3-B 判死**。诚实注记:这是无清算上界,真 sleeve 须过后置尾部门(膨胀空头清算 gap)+ notional-scaling/集中度。 |
| 2026-06-11 | Increment 4 | **物理清算尾部门**(`run_h3` 加 `liq_leverage`/`mm_rate`/`liq_penalty`,intrabar pump 穿清算价→罚金+gap,净损非整保证金;+5 单测,grid 模块 94→99 全绿)。杠杆 sweep(∞/10/5/3x)**结果不自洽 → 暴露框架级缺陷(§8.5,同病第三次发作)**:一切对**初始资本**计量 + delta-neutral 的 notional 随币价膨胀 → liq_cost 算出 6205%、单月收益 < −100%、组合链式复利翻负(10x 反超上界)。**sweep 任何数字不可信、不当判据**;上界(§8.3)的**符号**(carry 为正/offset≈0)仍稳健,**量级+尾部门**待 equity-normalized 重平衡 sizing 重构后重跑。 |
| 2026-06-11 | Increment 5 / 终判 | **equity-normalized 重构 = H3-A 终判**(§8.6):新增 `run_h3_carry`(notional=k×当前权益、日重平衡、清算=强平+重建,+4 单测,grid 模块 99→103 全绿),panel 切到它。框架缺陷已除(sweep 单调)。**真实 carry 上界仅 +4.70%/yr**(非虚高 +29%);物理清算尾部门在 L≥3 把它吃光(L=3:年化 −0.83%、3/6 年、net −4.41% → **§4 三判据全不过**)。**H3-A FAIL**:carry 真身扣真实尾部后不够活,兑现 §7 先验。**网格族最深一层证伪 → §6 收口执行,线 B 彻底收口。** 代码(perp 账本/run_h3/run_h3_carry/universe/103 单测)定性为可复用 delta-neutral/carry 研究资产。 |
