# RV-C 预注册计划 v0.1:硬锚相对价值 —— dated-futures 基差收敛 kill-test

状态:预注册计划 v0.1 · 创建 2026-06-11 · 代号 **RV-C**(线 C) · **只计划,实现为下一轮**
上游教训:[grid-binance-h3-plan.md](grid-binance-h3-plan.md)(H3 delta-neutral carry 死于永续无到期锚 +
物理清算尾部)· 线 B 全弧(网格=劣质执行皮,真身是 carry/RV,但扣真实尾部后 sub-gate)

---

## 0. 隔离声明(线 C,新建独立实验线)

线 C 是**独立的实验性硬锚相对价值(Relative Value)研究线**,与线 A(¥100万 ETF 跨资产 CTA 主线,
纪律冻结/§7 全局止盈)、线 B(GRID-B 网格,已彻底收口)**完全隔离**。

- **约束放松**(同线 B):可追盈利、可自推 paper/live(小资金实验可接受)、不受线 A §7 与 once-only 门约束。
- **保留工程理性**:kill-test、扣**两腿**费、与诚实基线对比、**跑前预注册判据**、一轮只改一处先写单测。
- **复用资产**:`src/qount/grid/`(线 B 收口资产)的 `perp.py` 时变账本、`backtest.py` 的 `run_h3_carry`
  (equity-normalized + 物理清算尾部门)、`data.py` 数据层、`universe.py`。**代码落独立命名空间
  `src/qount/rv/`,不原地改线 B 模块**(可 import 复用其纯件)。
- 变更只写回**本线文档**(本文件),不写 `current.md` / `update-log.md` / 线 B 文档。

---

## 1. 核心假设(RV-C / H-RV)与「为什么这次不同」

**诊断(承接线 B 元结论)**:网格死于在**非平稳的绝对价格**上赌均值回归。正确版本 = 把头寸铺到
**有真实收敛锚的相对价值价差**上,结构上 Δ≈0,消灭方向税(S1e 的 −247% 根因)。

**owner 决定:硬锚对优先**。硬锚 vs 软统计对的区别是 RV 的核心陷阱:

> **回归保证住在没钱的地方(硬锚、薄价差);钱住在没保证的地方(软对、宽价差、协整随时断)。**

第一刀选**最硬的锚 + 数据可得 + 基建可复用**者:**dated quarterly futures 基差(cash-and-carry)**。

| | H3(永续 carry,已死) | RV-C(dated 基差) |
|---|---|---|
| 收敛锚 | **无**(永续不到期)→ 死在无限持有的尾部 | **契约性到期收敛**(季度合约到期必须 = 现货)→ 真锚 |
| 结构 | 现货多 + 永续空,Δ≈0 | 现货多 + **dated 季度空**,Δ≈0(cash-and-carry) |
| 收益源 | 资金费(mania 正、dump 负、无下限) | 基差溢价(到期前的年化升水,**有到期收敛保证**) |
| 复用 | — | **直接套 `run_h3_carry`**(空腿换 dated future,资金费换基差收敛,清算尾部门照用) |

**H-RV 命题**:long 现货 + short 季度合约(到期或滚动前平),捕获基差年化溢价。在严格扣除
【两腿往返费 + 滚动成本 + 物理清算尾部(空腿在 pump 中被挤爆的 gap)】后,equity-normalized 净 EV
是否结构性为正且扛过周期(尤其 backwardation 的熊市段)。

---

## 2. 四个杀手 + 预注册防御(StatArb 的命在这一节)

| # | 杀手 | 预注册防御 |
|---|---|---|
| 1 | **样本外协整/收敛不稳** | dated 基差的收敛由**到期契约**保证(非统计估计),天然免疫此杀手——这正是选它当第一刀的理由。滚动选约规则点 point-in-time 写死。 |
| 2 | **两腿费 + 滚动成本吃薄 edge** | 两腿 taker 往返 + 每季滚动(平旧约/开新约)全计费;基差年化要先减这些才看净。空腿用 `perp.py` 账本。 |
| 3 | **多重检验(N² 对/选约运气)** | 第一刀只跑 **BTC、ETH** 两个最深流动性标的的基差(非挑选),不在 N² 对里捞;若扩软对,强制上线 A 的 DSR/PBO harness。 |
| 4 | **硬/软对混淆** | 第一刀**只做硬锚**(dated 基差);软统计对(SOL/APT 类)留作后置、且需 OOS 协整稳定性 + DSR/PBO 才动。 |
| + | **物理清算尾部(H3 教训)** | 直接套 `run_h3_carry` 的 equity-normalized + 清算门:空腿在 pump 中被挤爆的 gap 必须计入,杠杆 sweep(∞/10/5/3x),L=3 为预注册判据杠杆。 |

---

## 3. 预注册判生死(跑前写死;同 H3 §4 三判据 + RV 专属)

```
基线/口径:  equity-normalized(notional=k×当前权益,k=1),日重平衡,物理清算门 L=3x。
            BTC、ETH dated 季度基差,2021-01..2026-05(数据可得范围),滚动持有。
判据(全过才算硬锚 RV 活):
  (1) 扣全部成本(两腿费+滚动+清算尾部)后 annualized net > +2%
  (2) >= 4/6 (>=66%) 年 net-positive —— 关键看 backwardation 熊市段是否扛得住(不许单牛年扛)
  (3) 尾部生存:清算尾部 + 基差最深 backwardation 段完整计入后,总净 > 0
过:    硬锚 RV 成立 → 扩到 stETH/ETH 等赎回锚对(数据攻克后)+ S2 maker/盘口压力 + S3 DSR/PBO。
不过:  硬锚 RV 也 sub-gate → 与线 B 同型收口,RV 族判死(连最硬的锚都不够 edge)。

诚实先验(防自我感动,写在 verdict 旁):
  dated 基差是真实风险溢价(给多头杠杆),mania 段年化 10-40%、但 backwardation 熊市段转负;
  到期锚保证收敛(无 H3 的无限持有尾部),但空腿在 pump 中的清算 gap 仍在。我赌:比 H3 永续
  更robust(有锚),但大概率仍是 regime-dependent 薄 edge,L=3 扣尾后接近临界。买的仍是「死得明白」,
  只是这次锚是真的,问题纯粹是「薄 edge 在零售两腿费下剩不剩」——这是比 grid/carry 干净的问题。
```

---

## 4. 工程落点(下一轮要改的全部,先写单测)

复用线 B 纯件,**新建 `src/qount/rv/`,不改线 B 模块**:

- `rv/data.py`:扩 `grid/data.py` 加 **`cm`(COIN-M)市场** + dated 季度合约的 point-in-time 滚动选约
  (binance.vision `futures/cm/monthly/klines/{BTCUSD_YYMMDD}`),拼接连续基差序列(每季滚动)。
- `rv/basis.py`(新,纯件):`basis_series(spot, dated)`(年化基差)、`roll_schedule`(选约/滚动规则,
  point-in-time 无 look-ahead)、到期收敛对账。
- `rv/backtest.py`:`run_basis_carry()` —— 镜像 `run_h3_carry`(import 复用 `PerpHedgeLeg` /
  清算门 / equity-normalized sizing),空腿换 dated future、carry 源换基差收敛、到期滚动计费。
- `scripts/research/rv_c_basis.py`:BTC/ETH 真跑 + §3 三判据对账 + 杠杆 sweep;artifact 落
  `state/rv_c/research_runs/`。
- 单测:基差年化计算、滚动选约无 look-ahead、到期收敛对账、清算门复用对账、decomposition 求和。

---

## 5. 不做清单(继承线 B 教训)

- ❌ 第一刀就上软统计对(协整不稳 + 多重检验,§2 杀手 1/3/4);
- ❌ 永续基差当「硬锚」(永续无到期锚,= H3 已死);
- ❌ 跳过物理清算尾部门只报上界(H3 的 §8.5 教训:上界会骗人);
- ❌ 对初始资本计量 + 让单头寸 notional 膨胀(H3 §8.5 框架缺陷,必须 equity-normalized);
- ❌ VRP/期权(同 short-gamma 肥左尾,需 Deribit infra,缓做)、零售微观结构 MM(必输队列)。

---

## 7. v0.2 实现 + 第一刀实测(2026-06-11)——**过 gate,跨线 A/B 首个 gate 内正结果**

### 7.1 工程落点(已实现,先写单测)

落独立命名空间 `src/qount/rv/`,**未改任何线 B 模块**(只 import 复用其纯件):

- `rv/basis.py`(纯件):`annualized_basis` / `raw_basis`(到期收敛对账)、`active_expiry`
  (point-in-time 选约,只用固定到期日历 + listing 存在性,**无 look-ahead**)、`build_active_series`
  (拼接 spot + 各季度合约成连续 active 流,`is_roll` 标记换约边界)。
- `rv/data.py`(IO):COIN-M dated 季度合约(`futures/cm`)。`last_friday` 季度到期日历、
  `quarterly_contracts`、`load_dated_klines` / `load_contract_set`(复用 `grid.data` 的 parser +
  cached fetcher,缓存落 `state/rv_c/`,不碰线 B glob)。
- `rv/backtest.py`:`run_basis_carry` —— 镜像 `run_h3_carry`(equity-normalized + L=3 物理清算门),
  空腿换 dated future、carry 源换基差收敛(无资金费项,carry 由 directional residual 实现:持有期
  F→S 由 `−short·dF` 银行入账,到期 F≡S 锁定全额基差);**换约 gap 不计入 PnL**,只计两腿换约费
  (`roll_cost` 与 rebalance `fee_cost` 分开归因)。
- `scripts/research/rv_c_basis.py`:BTC/ETH 真跑 + 杠杆 sweep(∞/10/5/3x)+ §3 三判据对账;
  artifact 落 `state/rv_c/research_runs/`。
- 单测 **28 个**(`tests/test_rv_{basis,data,backtest}.py`):基差年化、选约无 look-ahead、拼接/换约
  标记、到期收敛、清算门复用对账、decomposition 求和、换约 gap 不计入、清算尾灾难后置平。线 B 103
  单测 + 线 C 28 单测全绿。

### 7.2 实测结果(L=3 为预注册 gate;数据 2021-01..2026-03,日线,日重平衡,两腿 taker)

| 标的 | L=3 net | 年化 | 正年数 | carry | roll | fees | liq | maxDD |
|---|---|---|---|---|---|---|---|---|
| **BTCUSD** | **+33.32%** | **+5.67%** | **6/6** | +42.95% | 2.31% | 7.32% | 0x | −4.83% |
| **ETHUSD** | **+20.64%** | **+3.66%** | **4/6** | +34.26% | 2.15% | 9.30% | 2.17%(1x) | −7.08% |

逐年(L=3):BTC `21 +8.56 / 22 +1.37 / 23 +0.54 / 24 +13.49 / 25 +6.25 / 26 +0.62`;
ETH `21 +2.71 / 22 −0.36 / 23 −0.24 / 24 +12.94 / 25 +4.83 / 26 +0.26`。

**三判据对账(L=3 gate):BTC ✓✓✓、ETH ✓✓✓ → 两标的全过。** 这是**跨线 A/B/B 至今第一个
gate 内正结果**:edge 在 contango/牛年(21/24/25)厚、在 backwardation 熊段(ETH 22/23 −0.3%/年)薄微负
但量级小、被 delta-neutral 结构挡住价格崩。诚实签名 = 真实 basis trade(基差 = 散户多头为杠杆付的溢价,
能持现货 + 空 future 者收割),**不是单牛年扛、不是过拟合**——逐年真分散,2022 熊年 BTC 仍 +1.37%。

### 7.3 杠杆敏感性 + inverse 硬化(线性 vs inverse,#1 洞已闭合)

`inverse=True` 硬化(§7.4):COIN-M dated 是币本位 **inverse** 合约。**手推 + 单测证**:日重平衡下空腿
USD 方向 PnL 与线性**一阶完全相同**(短 USD PnL ≈ −notional·return,notional 每 bar 重置)→ carry/费
不变;**唯一实质差异在清算触发**——pump 时币抵押增值垫高清算价,inverse 清算价 `P_liq/ref =
(1−mm)/(1−1/L)`(L=3 → **+49.3%** 才触发)vs 线性 `1/L−mm`(+32.8%)。**inverse 更抗 pump,线性是保守侧**。

| L | BTC 线性 | BTC inverse | ETH 线性 | ETH inverse |
|---|---|---|---|---|
| ∞ | +33.32% / 0x | +33.32% / 0x | +23.51% / 0x | +23.51% / 0x |
| 10x | −80.21% / 40x | −62.85% / 25x | −98.78% / 79x | −96.45% / 61x |
| 5x | +23.66% / 2x | **+33.32% / 0x** | **−25.31% / 7x(死)** | **+4.19% / 2x(活)** |
| **3x(gate)** | +33.32% / 0x | **+33.32% / 0x** | +20.64% / 1x | **+23.51% / 0x** |

**硬化后 gate 复判:BTC ✓✓✓(+5.67%/yr 6/6 年,0 清算)、ETH ✓✓✓(+4.13%/yr 4/6 年,0 清算,inverse 把
那 1 次清算也省了)→ 两标的仍全过,且 inverse 等于或优于线性。** ETH L=5 从线性「已死」翻成 inverse「活」,
存活边际被 inverse 抗性拓宽。**结论:过 gate 不是线性近似伪影,对正确合约力学稳健。** L≥10 仍被 pump 尾清零
(但 L=10 不是这笔交易;交易是 L≤3-5);代价仍在:spot 100% + short ~33% 保证金 → capital-on-capital 真实
回报低于头条年化;两腿 taker 费吃毛 carry ~1/4(BTC 7.32% / ETH 9.41% over 5y)。

### 7.4 hourly 清算精度复核(caveat 2 闭合,v0.4)

把数据从日线换 **hourly**(每日 margin top-up = rebalance 每 24 根,**逐小时**检查清算触发,接近真实
账户),复跑 inverse L=3:

| | BTC daily | BTC hourly | ETH daily | ETH hourly |
|---|---|---|---|---|
| L=3 net | +33.32% | **+33.49%** | +23.51% | **+24.91%** |
| 年化 | +5.67% | **+5.70%** | +4.13% | **+4.36%** |
| 正年 | 6/6 | 6/6 | 4/6 | 4/6 |
| 清算 | 0x | **0x** | 0x | **0x** |

**hourly 在 L=3 找到 0 个额外清算(两标的),净值与日线几乎一致(略高)→ 日线 liq 结果在交易杠杆 L=3
下未低估日内清算,判决对清算粒度稳健。caveat 2 闭合。**(L=10 hourly 仍死:BTC −42%/21x、ETH −83%/61x;
ETH L=5 hourly 临界 +1.44%/4x——L=5 edge 薄,但 gate 的 L=3 干净。)

### 7.5 诚实 caveat(过 gate + #1 洞已硬化 + 清算粒度已复核)

1. **~~#1 洞 inverse 凸性~~ —— 已闭合(v0.3)**:补 inverse 账本,手推证日重平衡 carry 一阶等价、清算触发
   更晚,复判等于或优于线性,**线性 first-cut 未美化 edge**。
2. **~~日线粒度清算~~ —— 已复核(v0.4)**:hourly 逐小时清算复跑,L=3 两标的 0 额外清算,判决稳健。
3. **薄 edge + 费拖(剩余真约束)**:净 ~5.7%/yr(BTC)、~4.4%/yr(ETH),retail taker 费占毛 carry 大头
   (BTC 7.2% / ETH 9.3% over 5y);maker/低费会松,但预注册用 taker(诚实)。**这是真实天花板,非可硬化洞。**
4. **资本效率(剩余真约束)**:跑这套要 spot 100% + short ~33% 保证金,capital-on-capital 真实回报低于
   头条年化;L≥10 被 pump 尾清零,只在 L≤3-5 近乎不带杠杆时活。

### 7.6 广度稳健性面板(v0.5)——**广度不成立,edge 窄而真**

预注册广度判据(跑前写死):同一硬锚假设跑全部有 dated 深历史的流动 COIN-M(非 cherry-pick = 取所有,不挑),
每标的判 §3 L=3 gate(inverse,各自可得年份)。**≥5/8 过 = 宽风险溢价;否则 = 窄/脆**。

| 标的 | 窗口 | 年化 | net | 正年 | 清算 | carry / fees | 判 |
|---|---|---|---|---|---|---|---|
| BTCUSD | 21-26 | +5.67% | +33.32% | 6/6 | 0x | +43.0/7.3% | **✓** |
| ETHUSD | 21-26 | +4.13% | +23.51% | 4/6 | 0x | +35.1/9.4% | **✓** |
| LINKUSD | 21-25 | +3.82% | +19.31% | 4/5 | 0x | +32.4/11.1% | **✓** |
| LTCUSD | 21-25 | +4.26% | +21.75% | 4/5 | 0x | +32.8/9.1% | **✓** |
| DOTUSD | 21-25 | +0.09% | +0.43% | 3/5 | 0x | +11.9/9.7% | ✗ 费拖 |
| SOLUSD | 24-26 | +0.41% | +0.66% | 2/3 | 0x | +4.2/3.0% | ✗ 薄 carry+费 |
| ADAUSD | 21-25 | −4.23% | −18.44% | 2/5 | 1x | +20.8/9.2% | ✗ pump 尾 |
| BCHUSD | 21-25 | −5.46% | −23.24% | 0/5 | 2x | +7.6/8.1% | ✗ pump 尾 |
| XRPUSD | 21-26 | −18.13% | −62.94% | 3/6 | 5x | +11.5/4.4% | ✗ pump 尾 |
| BNBUSD | 21-26 | −11.63% | −47.50% | 0/6 | 1x | **−4.4%** | ✗ 负基差 |

**4/10 过 → 广度不成立(< 预注册 5/8)。** 但失败诊断三类、信息量大:**① 负基差**(BNB,交易所币无持续
contango,结构性死);**② pump 尾清算吃光正 carry**(XRP 5x / BCH 2x / ADA 巨 gap,altcoin 暴烈上插把薄
carry 挤爆);**③ 纯费拖**(DOT/SOL,0 清算但正 carry 被两腿 taker 费抹平)。**edge 不是宽风险溢价,而是**
**窄而真**——只在同时满足【持续 contango + 不太暴烈的 pump 尾 + carry 厚到过费】的**最深 majors(BTC/ETH/
LINK/LTC)**成立。**非 BTC/ETH 特例(LINK/LTC 独立复现),但远非全市场可收割。**

**重要转向**:③ 类失败(DOT/SOL)是**纯费拖、0 清算、carry 为正**——若 S2 把两腿 taker 换 maker/低费,
DOT/SOL/可能 ADA 有望翻过 gate,**广度面板直接把 S2(攻费拖)从「锦上添花」升级为「能否拓宽 edge 的关键刀」**。

**结论(线 C 现状)**:dated 基差 carry = **跨线 A/B 首个真实、经三轮检验(inverse / hourly / 广度)稳健的
正 edge,但窄(4 深 majors)且薄(~4-6%/yr)**。不是收口(4 标的稳过、机制清楚),但广度证伪了「宽风险溢价」
的野心。下一步**首选 S2 maker/低费**(直击 ③ 类费拖,可能拓宽 + 抬净);其次 stETH 赎回锚对(新锚型,待攻数据);
S3 DSR/PBO。**仍不碰线 A 主线资本。**

### 7.7 S2 maker/低费(v0.6)——抬核心、**救不动薄 carry 边缘**,edge 确认窄

`run_basis_carry` 加 maker 费模型(`maker_open`/`maker_roll`/`maker_rebalance`,默认全 taker 向后兼容):
open/季度 roll(5 天 buffer = 可耐心挂)/日 rebalance(小、非紧急 delta)全可挂 **maker**;**清算重开仍 taker**
(强制/紧急)。用 BNB 折扣零售档(spot 7.5bp / dated 2bp)跑 §7.6 全面板,**taker vs maker 并排**:

| 标的 | carry | taker ann | maker ann | 判 |
|---|---|---|---|---|
| BTC | +43.0% | +5.67% ✓ | **+6.40% ✓** | 抬 |
| ETH | +35.1% | +4.13% ✓ | **+5.01% ✓** | 抬 |
| LINK | +32.4% | +3.82% ✓ | **+4.90% ✓** | 抬 |
| LTC | +32.8% | +4.26% ✓ | **+5.20% ✓** | 抬 |
| DOT | +11.9% | +0.09% ✗ | +1.09% ✗ | 更近仍不过 |
| SOL | +4.2% | +0.41% ✗ | +1.32% ✗ | 更近仍不过 |
| ADA/BCH/XRP | — | 负(pump 尾)✗ | 负 ✗ | 费无关 |
| BNB | −4.4% | −11.63% ✗ | −10.94% ✗ | 负基差,费无关 |

**maker(best-case)仍 4/10,零翻盘。** DOT/SOL 更近但仍 < +2% gate——**毛 carry 太薄(DOT ~2.4%/yr、SOL
~2.7%/yr),maker 砍 ~1%/yr 费不足以补**。pump 尾 / 负基差失败对费无关。**诚实关键**:maker 是 best-case
(假设挂单成交);即便如此零翻盘 → 结论稳健(真实成交率更低、帮助更小,只会更不翻盘)。

**S2 终判**:**maker 对核心 4 标的白送 ~1%/yr(BTC 抬到 +6.4%/yr),值得运营化;但救不动薄 carry 的边缘标的
→ 边缘的绑定约束是薄 carry / pump 尾,不是费 → edge 确认窄而真(4 深 majors)。** 费不是可拓宽 edge 的杠杆。
（注:4 PASS 标的 0 清算、确定性、字节复现;深 fail 标的幅度对数据完整性敏感,判决不变。)

### 7.8 S3 去多重检验(v0.7)——DSR + PBO:**认证收窄到预注册 BTC/ETH**

面板试了 10 个标的、过 4 个——「过 4」是真 edge 还是搜索运气(杀手3)?Bailey-LdP 双工具
(`rv/stats.py`,纯件 + 14 单测):**DSR**(去膨胀 Sharpe,按试验数去多重检验膨胀)+ **PBO/CSCV**
(选最优标的样本外泛化概率)。**关键:正确的多重检验结构**——BTC/ETH 是 §3 **预注册**第一刀(无搜索,
用 raw PSR=prob(真 SR>0));LINK/LTC 是广度面板 **N=8 搜索发现**,须扛 N=8 的期望最大 Sharpe 去膨胀。

| 标的 | 年化 SR | PSR(raw) | DSR_disc(N=8) | 认证 |
|---|---|---|---|---|
| BTC(预注册) | +1.26 | **0.998** | — | **✓ PSR>0.95** |
| ETH(预注册) | +0.87 | **0.974** | — | **✓ PSR>0.95** |
| LINK(广度发现) | +0.63 | 0.917 | **0.43** | ✗ 扛不住 N=8 |
| LTC(广度发现) | +0.71 | 0.936 | **0.49** | ✗ 扛不住 N=8 |
| 其余 6 | ≤+0.17 | ≤0.58 | ≪ | — |

**PBO/CSCV = 0.000**(9 个长历史标的,共同窗口 2021-01..2025-09,1720d,S=10):选最优标的样本外**完全泛化**
→ 排名稳定(BTC/ETH/LINK/LTC 跨切分稳居前),**选择过程不过拟合**。

**S3 终判**:① **PBO=0** = 排名真稳、非切分运气;② 但**绝对显著性**经多重检验后**只有预注册 BTC/ETH 站得住**
(PSR 0.998/0.974);**LINK/LTC 的 Sharpe 扛不住 N=8 广度搜索去膨胀(DSR_disc 0.43/0.49)→ 疑似搜索运气,
降权为「提示性、未认证」**。**认证 edge 从 4 收窄到 2(BTC/ETH)**;且即便认证,Sharpe 也薄(年化 ~1.0-1.3)。

**线 C 第一刀最终定型(五轮检验:inverse / hourly / 广度 / S2 / S3)**:dated 基差 carry = **跨线 A/B 首个
机制真实(基差风险溢价 + 硬到期锚)、排名稳健(PBO=0)、且经多重检验认证的正 edge——但认证范围仅预注册
BTC/ETH,Sharpe 薄(~1.0-1.3 年化、~5-6.4%/yr w/ maker),广度不成立、LINK/LTC 提示未认证。** 窄、薄、真。
**这是诚实的「小而真」,非「宽而肥」——但已是跨三线唯一过多重检验认证的可交易 edge。**

### 7.9 A1 基差条件化建仓(v0.8)——**证伪:基差水平不是择时信号,always-on 即最优**

唯一机制级「提收益」杠杆:`run_basis_carry(min_ann_basis=)`(默认 None=向后兼容字节复现;+4 单测 → 53 个)——
只在年化基差肥(≥阈值)时部署、薄/负时空仓吃现金(0 收益,保守,无 look-ahead)。在 BTC/ETH 上扫阈值
(maker + inverse L=3)看响应面是稳健带还是刀尖峰:

| BTC | always | 4% | 6% | 10% | 20% |
|---|---|---|---|---|---|
| 年化净 | **+6.40%** | +5.14% | +4.06% | +3.48% | +2.87% |
| Sharpe | **+1.41** | +1.19 | +0.97 | +0.88 | +0.87 |
| 部署% | 100% | 70% | 49% | 24% | 8% |

(ETH 同型:always +5.01%/Sharpe1.04 最优,逐阈值单调降。)**整条曲线单调向下、两标的一致 → 不是过拟合刀尖峰,
是稳健的负结果。** 先验(跳过 backwardation 抬 Sharpe)**被证伪**:① 年化净降 = 空仓期摊薄(丢掉的 carry 没东西
补);② **Sharpe 也降** = delta-neutral 下薄/负基差段本就不怎么亏,基差水平**不预测**前向 carry,空仓只是丢收益不
减等量风险。诚实补充:闲置资本按 0% 计是保守的;即便给闲置资本记 ~4% T-bill,gated 版 ≈ 与 always-on **打平**
(薄基差段的 carry 本就 ~T-bill 量级,= 拿一种薄收益换另一种,非加 alpha)。

**A1 终判:basis-conditional 不 work,always-on cash-and-carry 已是这条 edge 的最优形态。无需 S3(无任何阈值
改善,没什么可认证)。** 这也再次确认:**没有隐藏的「巨猛」——连唯一合法的优化都只是把 always-on 重新证明为最优。**

### 7.10 RV-C 作为线 D 趋势的压舱石(C×D 合成账,2026-06-13)——认证 carry 找到最佳用途

A1 证明 carry 自身已到顶(薄、窄、always-on 最优),但**它真正的价值不是单独跑,是当线 D 趋势的压舱石**。详见
`docs/crypto-x4-plan.md §20`:RV-C BTC+ETH(always-on maker inverse L=3)与线 D S7 趋势 **corr −0.196 负相关**
(中性 vs 方向,尾部相反=逼空 vs 暴跌),合成账(纯件 `x4/combo.py` 复用 `rv.stats` 不改本线模块)在可部署
**40% carry 权重**下把趋势 **Sharpe 0.89→1.18、maxDD −21.4%→−10.2%(尾砍近半)**,**kill-test PASS**。**这是 RV-C
这条窄薄真 edge 的最佳归宿——单独 +6.4%/yr 不性感,但作压舱石给趋势抬 Sharpe + 砍尾价值真实。** caveat:两者
都隐性多「crypto 活着/contango」宏观因子,短期尾部正交真、多年 regime 假,非全天候。

---

## 6. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-06-11 | v0.1 | 立线 C(RV-C 硬锚相对价值),owner 选硬锚对优先 + 新建隔离实验线。第一刀=dated quarterly futures 基差收敛(最硬锚 + 数据可得 + 复用 `run_h3_carry` 清算/equity-normalized 基建)。预注册四杀手防御 + 三判据 + 工程落点。**只计划,实现为下一轮先写单测。** |
| 2026-06-11 | v0.2 | 实现 `src/qount/rv/`(basis/data/backtest,28 单测,未改线 B)+ `rv_c_basis.py`。第一刀实测:**BTC/ETH 全过 L=3 预注册 gate**(BTC +5.67%/yr 6/6 年、ETH +3.66%/yr 4/6 年),跨线 A/B 首个 gate 内正结果,逐年真分散非单牛年。caveat:#1 洞 inverse 合约凸性未建模(线性近似 first-cut)、L≥5 极度脆弱(ETH L=5 已死)、薄 edge 费拖大。**「过 gate」≠「终判活」,下一步硬化 inverse 账本复判,而非扩张。** |
| 2026-06-11 | v0.3 | **硬化 #1 洞 = inverse 合约账本**(`run_basis_carry(inverse=True)`,+3 单测 → 31 个)。手推证日重平衡下空腿 USD PnL 一阶等价线性、清算触发更晚(`P_liq/ref=(1−mm)/(1−1/L)`,L=3 +49.3% vs 线性 +32.8%)。**硬化复判两标的仍全过**(BTC +5.67%/yr 0 清算、ETH +4.13%/yr 0 清算,inverse 等于或优于线性;ETH L=5 从线性「死」翻「活」)。**过 gate 非线性伪影,对正确力学稳健;#1 洞闭合。** 剩余 caveat 降为工程精度(日线→hourly 清算粒度)。下一步走 §3 pass 分支(细粒度精度刀 → 扩赎回锚对 → S2/S3),不碰线 A 资本。 |
| 2026-06-11 | v0.4 | **复核 caveat 2 = hourly 清算粒度**(脚本加 `interval` 参数:hourly 每日 margin top-up + 逐小时清算触发)。复跑 inverse L=3:**hourly 两标的 0 额外清算,净值与日线几乎一致**(BTC +5.70%/yr 6/6、ETH +4.36%/yr 4/6,均 0 清算)→ 日线 liq 在 L=3 未低估日内清算,判决对清算粒度稳健,**caveat 2 闭合**。修 `BasisResult.verdict` cosmetic ann bug(去掉硬编码 365/n_bars,改由 caller 按 bars_per_year 年化)。两轮硬化后两标的仍全过;剩余两条 caveat(费拖、低杠杆资本效率)= 真实天花板非建模洞。下一步:扩 stETH 赎回锚对 / S2 maker 直击费拖 / S3 DSR/PBO。 |
| 2026-06-11 | v0.5 | **广度稳健性面板**(`rv_c_panel.py`,10 个流动 COIN-M,非 cherry-pick)。预注册 ≥5/8 过 = 宽;实测 **4/10 过(BTC/ETH/LINK/LTC)→ 广度不成立**。失败三类:负基差(BNB)/ pump 尾清算(XRP 5x、BCH、ADA)/ 纯费拖(DOT/SOL,0 清算正 carry 被 taker 费抹平)。**edge = 窄而真**:只在【持续 contango + 不暴烈 pump 尾 + carry 过费】的最深 majors 成立,非宽风险溢价但 LINK/LTC 独立复现 BTC/ETH。**非收口**(4 标的稳过、机制清楚)。重要转向:③类失败(DOT/SOL)是纯费拖 → **S2 maker 从锦上添花升为拓宽 edge 的关键刀**(首选下一步)。 |
| 2026-06-11 | v0.6 | **S2 maker/低费**(`run_basis_carry` 加 `maker_open/roll/rebalance`,默认 taker 向后兼容,+4 单测 → 35 个;清算重开仍 taker)。面板 taker-vs-maker 并排(maker = best-case 假设成交,BNB 折扣 spot 7.5bp/dated 2bp)。**结果:仍 4/10,零翻盘**——maker 把核心 4 标的各抬 ~+0.8-1.1%/yr(BTC→+6.40%),但 DOT(+1.09%)/SOL(+1.32%)更近仍不过 gate,薄 carry(非费)是绑定约束;pump 尾/负基差失败对费无关。**S2 终判:maker 值得运营化白送核心 ~1%/yr,但不能拓宽 edge → 费不是杠杆,edge 确认窄而真**。下一步剩 stETH 赎回锚对(新锚型,待攻数据)/ S3 DSR-PBO 对 4 标的去多重检验。 |
| 2026-06-11 | v0.7 | **S3 去多重检验**(`rv/stats.py` DSR + PBO/CSCV 纯件,+14 单测 → 49 个;`rv_c_s3.py`)。正确多重检验结构:BTC/ETH 预注册用 raw PSR、LINK/LTC 广度发现用 N=8 去膨胀。**结果:PBO=0(选择不过拟合,排名稳)但绝对显著性经多重检验后只有预注册 BTC/ETH 站得住(PSR 0.998/0.974>0.95);LINK/LTC 扛不住 N=8 去膨胀(DSR_disc 0.43/0.49)→ 疑似搜索运气,降权为提示性未认证**。**认证 edge 从 4 收窄到 2(BTC/ETH),Sharpe 薄(年化~1.0-1.3)**。线 C 第一刀经五轮检验定型 = 机制真 + 排名稳 + 多重检验认证,但范围窄(预注册 BTC/ETH)、Sharpe 薄;跨三线唯一过多重检验的可交易 edge。下一步:BTC/ETH 小资金 paper(认证对)或 stETH 新锚型拓宽。 |
| 2026-06-12 | v0.8 | **A1 基差条件化建仓**(`run_basis_carry(min_ann_basis=)`,默认 None 字节复现,+4 单测 → 53 个;`rv_c_a1.py` 阈值 sweep)。只在年化基差肥时部署、薄/负时空仓。**结果=证伪**:BTC/ETH 上整条阈值曲线**单调向下**(年化净 + Sharpe 同降,两标的一致 → 稳健负结果非过拟合峰),always-on(BTC +6.40%/Sharpe1.41)即最优。先验「跳过 backwardation 抬 Sharpe」被否:delta-neutral 下薄基差段本就不亏,基差水平不预测前向 carry。即便闲置资本记 ~4% T-bill 也只与 always-on 打平(换薄收益非加 alpha)。**basis-conditional 不 work,无需 S3。再次确认无隐藏「巨猛」。** |
