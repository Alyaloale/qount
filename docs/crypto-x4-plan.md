# 线 D — X4 计划 v0.1:四策略加密模拟盘 bake-off

状态:预注册计划 v0.1 · 创建 2026-06-12 · 代号 **X4**(线 D) · **只计划,实现为下一轮先写单测**
上游资产:[grid-binance-plan.md](grid-binance-plan.md)(网格栈 + perp 账本)· [rv-c-plan.md](rv-c-plan.md)
(dated 基差,跨三线唯一过多重检验认证的正 edge)

---

## 0. 隔离声明(线 D,新建独立实验线)

线 D 是**独立的实验性「四策略 bake-off」研究线**,与线 A(¥100万 ETF 跨资产 CTA 主线,纪律冻结 /
§7 全局止盈)、线 B(GRID-B 网格,已彻底收口)、线 C(RV-C 硬锚相对价值,进行中)**完全隔离**。

- **约束最大放松(owner 显式)**:本线**不要求证伪/once-only 验证门**——owner 的目标不是「证明哪个能赚」,
  而是「把四个策略都设计到回测好看,再用**同等本金**跑模拟盘,横向比四者结果」。这是一次**赛马实验**,
  不是 kill-test。线 A 的 §7 止盈、broad-gate、once-only、WSL 生产真相链路**均不约束本线**。
- **仍保留的最小工程理性**(让对比有意义,不是让它通过门):① 四策略**同一标的、同一窗口、同一费用模型、
  同一本金、同一指标口径**(否则赛马不公平);② 扣真实双边费 + 滑点;③ 一轮只改一处先写单测。
- **复用资产**:`src/qount/grid/`(`data.py` 公开行情层、`perp.py` 时变账本、`engine.py` 网格引擎、
  `trend.py` 趋势滤网)、`src/qount/rv/`(`basis.py` / `stats.py` 评比统计)。**代码落独立命名空间
  `src/qount/x4/`,不原地改线 B/C 模块**(只 import 复用纯件)。
- 变更只写回**本线文档**(本文件),不写 `current.md` / `update-log.md` / 线 B / 线 C 文档。

---

## 1. 实验目标与设计哲学

**一句话**:在 BTC/ETH(+ 可选 SOL)上,把四类经典加密策略各自做到「回测曲线好看」,然后给每个策略
**$100k 独立账本**,在同一段前向行情上跑模拟盘,横向对比终值/风险/相关性,看哪种在**相同市场、相同本金**
下表现最好——纯实验,不预设结论、不下真单。

**四策略(owner 给定的四类)**:

| 代号 | 策略 | 风格 | 赚什么钱 | 已有先验(诚实标注,不影响仍跑) |
|---|---|---|---|---|
| **S1-GRID** | 网格交易 | 中风险 / 震荡 | 区间内低买高卖的波动差 | 线 B 已证伪「网格 > 持有」(扣费后 0/6 年跑赢 hold-above-200MA);本线**仍跑**,但口径=「四者横比」非「打败持有」 |
| **S2-PAIR** | 配对 / 统计套利 | 中风险 / 震荡 | BTC-ETH 价差均值回归 | 线 C 证:硬锚对(dated 基差)BTC/ETH 过多重检验,但**软统计对**协整不稳;本线用 BTC/ETH 比价对,属软对,先验薄 |
| **S3-CTA** | 趋势跟踪 | 高风险 / 方向 | 单边大趋势(双均线 / 布林) | 加密牛熊极端,趋势在牛市斩超额、震荡市被来回打脸;复用 `grid/trend.py` 滤网逻辑 |
| **S4-MOM** | 动量突破 | 高风险 / 方向 | 关键位 + 量 + OI 突破瞬间顺势 | 突破假信号多,靠高盈亏比;OI(持仓量)数据需 binance.vision metrics dump |

> **诚实前言(防自我感动,写在计划里)**:线 A/B/C 三轮经验高度一致——加密里**网格不是 alpha、软对协整
> 不稳、趋势/动量在震荡市被费拖**。本线**不与那些结论冲突**:它问的是一个**更弱、更诚实的问题**——「在
> 完全相同的条件下并排跑,这四种各自能跑成什么样、彼此相关性如何」。回测「好看」是 owner 的目标,但对比
> 报告会**同时给出诚实指标**(扣费净值、maxDD、是否单 regime 扛起),不把好看的曲线当 edge 兜售。

---

## 2. 四策略设计规格(预注册:跑前写死参数来源,禁事后调参挑曲线)

四策略统一:**标的 BTC/ETH(USDT-M 永续,可选 SOL)· 窗口 2021-01..2026-05 · 1h K 线 · 双边 taker 费
5bp + 滑点 2bp · 本金 $100k/策略 · 无跨策略保证金共享**。下面只列**信号与执行差异**。

### S1-GRID 网格交易
- 复用 `grid/engine.py` 等比网格账本 + `grid/trend.py` 200MA 滤网(只在站上 200MA 时持仓,规避线 B 单边
  暴跌套牢)。区间 = 滚动 N 日 ATR 倍数自适应;格数固定 20;每格成交计双边费。
- 参数来源写死:区间宽度 = `k_atr × ATR(14d)`,`k_atr` 取线 B 收口时的默认(不在本线再扫优化)。
- 出场:跌破 200MA 全平转现金(踏空可接受,记录为该策略的固有缺陷)。

### S2-PAIR 配对 / 统计套利(BTC-ETH)
- 信号 = ETH/BTC 比价的滚动 z-score(窗口 90d)。`z > +2` → 空 ETH 多 BTC(等 notional,Δ_USD≈0 是近似,
  非严格 delta-neutral);`z < -2` → 反向;`|z| < 0.5` → 平仓。
- 复用 `rv/stats.py` 做协整/半衰期诊断(只诊断、不当门)。两腿各计双边费 + 滑点(线 C 教训:两腿费吃薄 edge)。
- **诚实标注**:这是**软对**,协整随时可断(线 C 杀手 1);本线接受其脆弱,只作横比一员。

### S3-CTA 趋势跟踪(单标的双均线 + 布林)
- 信号 = 快慢均线交叉(20/100h)做多/做空 + 布林带(20h, 2σ)突破确认;趋势破坏(反向交叉或跌破中轨)止损。
- 永续多空双向,固定杠杆 1x(notional = 当前权益,equity-normalized,沿用线 C 口径);ATR 止损 3×ATR。
- 复用 `grid/perp.py` 账本记多空头寸与资金费(方向性策略要把资金费计入持有成本)。

### S4-MOM 动量突破(价 + 量 + OI)
- 信号 = 价格突破 N 日(20d)高/低 + 当根成交量 > 1.5× 均量 + OI(持仓量)环比上升 → 顺势开仓;
  反向突破或 M 日(5d)无新高则平。
- 数据:价/量用 `grid/data.py` K 线;**OI 需新增** binance.vision `futures/um/.../metrics` dump 解析
  (落 `x4/data.py`,缓存 `state/x4/`,不碰线 B glob)。OI 不可得时降级为「价 + 量」两因子(标注)。
- 永续双向,1x equity-normalized,3×ATR 止损。靠高盈亏比(截断亏损、让利润奔跑)。

---

## 3. 统一回测 + 模拟盘框架(公平性是本线的命)

赛马唯一有意义的前提 = **除策略逻辑外一切相同**。预注册统一口径(跑前写死):

```
标的:      BTC/ETH(USDT-M 永续);SOL 作可选第三标的(数据全时纳入)。
窗口:      回测 2021-01..2026-05(grid/rv 数据可得范围),1h bar。
本金:      每策略独立 $100,000,起点同日,无跨策略共享保证金/对冲。
费用:      双边 taker 5bp + 滑点 2bp,每笔成交都扣;方向性策略额外计资金费(perp.py)。
杠杆:      方向性(S3/S4)1x equity-normalized;网格/配对按各自 notional,记录有效杠杆。
执行:      bar-close 成交(无 look-ahead);信号用 t 收盘、成交按 t 收盘价 + 滑点。
模拟盘:    回测段结束后,前向 paper —— x4 自带 forward 引擎喂 Binance 公开 1h 行情(只读、不下真单),
           四策略同一行情流并行推进,每根 bar 各自更新独立账本。
```

**模拟盘引擎(`x4/papersim.py`,新)**:一个确定性事件循环,每 tick 拉一根新 K 线 → 把同一根喂给四个
策略对象 → 各自产生订单 → 在内部撮合器按 close + 滑点成交 → 更新四本独立账本 → 落 equity 快照。
**纯内部模拟,不接交易所私有 API、不下真单**(最干净的实验口径,且与线 A 运维零耦合)。

---

## 4. 评比口径(跑前写死,四策略同一张表)

对**回测段**与**模拟盘段**分别出同一张对比表:

| 指标 | 含义 |
|---|---|
| 终值 / 总收益 % | $100k 起点的终值 |
| 年化(CAGR) | 几何年化 |
| Sharpe / Sortino | 风险调整;复用 `rv/stats.py` |
| maxDD / Calmar | 最大回撤 / 年化÷maxDD |
| 胜率 / 盈亏比 | 方向性策略关键 |
| 换手 / 累计费 | 网格/动量换手高,费拖要显式 |
| **四策略相关性矩阵** | 终极看点:四者收益相关性(低相关 = 组合分散价值);复用 `rv/stats.py` |
| 单 regime 归因 | 21 牛 / 22 熊 / 23-24 震荡 / 25-26 各段贡献(防「单 regime 扛起」) |

**输出 = 一份对比报告**(`scripts/research/x4_compare.py` 生成,artifact 落 `state/x4/research_runs/`):
回测表 + 模拟盘表 + 相关性矩阵 + 四条 equity 曲线叠图 + 逐 regime 归因。**不评判生死、不设 gate**,
只如实并排呈现 + 诚实 caveat(哪条曲线是单 regime 撑起、哪条扣费后变薄)。

---

## 5. 工程落点(下一轮要建的全部,先写单测)

复用线 B/C 纯件,**新建 `src/qount/x4/`,不改线 B/C 模块**:

- `x4/data.py`:扩数据层加 **OI/metrics dump** 解析(`futures/um/.../metrics`,S4 用);复用 `grid.data`
  的 parser + cached fetcher,缓存落 `state/x4/`。
- `x4/strategies.py`(纯件):四个策略类,统一 `Strategy` 协议(`on_bar(bar) -> list[Order]`),
  内部各自 import 复用 `grid.engine`(网格)/ `grid.trend`(滤网)/ `rv.basis`+`rv.stats`(配对诊断)。
- `x4/account.py`:统一独立账本(import `grid.perp` 的均价/资金费/清算原语),四策略各持一本。
- `x4/backtest.py`:`run_x4_backtest()` —— 同一行情驱动四账本,出 §4 全指标。
- `x4/papersim.py`:前向 paper 引擎(§3),只读公开行情、内部撮合、四本并行。
- `scripts/research/x4_compare.py`:回测 + 模拟盘 + 对比报告 + 相关性矩阵;artifact 落 `state/x4/research_runs/`。
- 单测(`tests/test_x4_*.py`):四策略信号确定性、统一费用模型对账、账本与 `grid.perp` 复用对账、
  OI 解析、撮合无 look-ahead、相关性/指标计算、四账本独立性(无串保证金)。

---

## 6. 阶段与里程碑

| 阶段 | 内容 | 产出 |
|---|---|---|
| **B0** | 建 `x4/` 骨架 + 四策略类 + 单测;四策略各自回测调到「曲线好看」(参数来源预注册,不事后挑) | 四条回测 equity + §4 表 |
| **B1** | 统一框架对账:四策略同费用/同本金/同窗口跑通,出回测对比表 + 相关性矩阵 | `x4_compare.py` 回测报告 |
| **B2** | `papersim.py` 前向模拟盘:四策略同一行情流并行推进 N 周 | 模拟盘 equity 快照 |
| **B3** | 出终版对比报告(回测 + 模拟盘 + 相关性 + 逐 regime + 诚实 caveat) | `state/x4/research_runs/` artifact |

---

## 7. 不做清单(继承三线教训,守住实验边界)

- ❌ 把本线结果写回 `current.md` / `update-log.md` / 线 B / 线 C 文档(只写本文件);
- ❌ 用本线模拟盘结果动线 A 主线资本 / 放宽线 A 任何门;
- ⚠️ 接交易所私有 API 下真单:**原为禁,2026-06-14 owner 显式授权 ~$415(3000 RMB)小资金现货 pilot → 解除(见 §21)**;
  仍守:纯现货(无清算)、独立开关 `QOUNT_X4_LIVE_ENABLE`(不碰线 A 的 `QOUNT_LIVE_ENABLE`)、硬资金上限、默认 dry;
- ❌ 四策略用不同费用/本金/窗口对比(破坏赛马公平 = 报告作废);
- ❌ 事后挑参数让曲线好看后当 edge 兜售(回测好看是 owner 目标,但报告须标注单 regime / 费拖 / 软对脆弱);
- ❌ 原地改线 B/C 模块(只 import 复用)。

---

## 22. Phase 2:动态币池引擎 + walk-forward(2026-06-14)——严格无前视下,动态选币证伪,固定 TOP7 胜

owner(以研究负责人身份)定路线图 3→2→1:先上线基线、**再做动态币池引擎(Phase 2,他的 ★★★★★)**、最后才考虑
B+D。命题:趋势系统该「跟随当前资金流向」而非死抱过去赢家,固定币池原罪=永远持有老赢家;若动态 TOP7 能在**严格
无前视 + ragged listing + 防幸存者**下维持 TOP5 那档效率,才可能把 Sharpe 推到下一层级。

### 22.1 引擎 + 偏差防御(`src/qount/x4/dynuniverse.py`,纯件不改冻结模块)

`run_dynamic_trend_portfolio`:月度按 trailing 美元成交额从宽候选池重排 TOP-K,跑同一 per-coin S3 趋势 sleeve,
逆波动率合成 + BTC 大盘闸 + **换手成本**(换成员收 `turnover_fee`,仅闸开/真持仓时收,现金态轮换免费)。三偏差
**由构造防御**:① look-ahead——月初按**上月末为止**数据排名、交易下月;② listing 穿越——coin 在 asof 日须有
≥`min_history` 根历史才进候选,上市前绝不用;③ 退市/幸存者——数据停更(stale)的币自动掉出,候选池显式纳入
DECLINED+LATE。+10 单测(`test_x4_dynuniverse.py`,覆盖三防御)→ **x4 共 165 全绿**。

### 22.2 数据(`x4_universe_probe.py`)——池子有真牙齿,非幸存者受限

候选 48/48 全有 UM 1d 数据,**34 个非幸存币**。关键:**LUNAUSDT 仅 17 个月**(2022-05 崩盘退市的老 Terra,真死币)、
MATIC(→POL 改名掉队)、FTT(交易所暴雷)、SUI/ARB/OP/TIA/WIF/PEPE(晚上市新龙头)全入池。**动态账本真的重仓了
它们**(下表诊断:持 ≥1 非幸存币占 79%–100% 月份),故本测**非幸存者受限**——是干净的真检验。

### 22.3 walk-forward 结果(`x4_dynuniverse.py`,2021-01..2026-05,净换手)——证伪

| 引擎 | total | full S/DD | train S/DD | test S/DD | 持非幸存币月份占比 |
|---|---|---|---|---|---|
| **固定 TOP7(基线)** | +86% | **0.89/−20.6%** | **0.66/−12.9%** | **1.13/−20.6%** | — |
| 动态 TOP5 | +47% | 0.65/−14.7% | 0.56/−13.4% | 0.75/−14.7% | 79% |
| 动态 TOP7 | +44% | 0.64/−16.7% | 0.37/−16.7% | 0.89/−11.2% | 96% |
| 动态 TOP10 | +61% | 0.82/−12.6% | 0.62/−12.6% | 1.02/−11.1% | 100% |

**判定 = 证伪(命题反了)**:① **每个动态变体在 full/train/test 三段 Sharpe 全部低于固定 TOP7**;动态 TOP7
(0.64)够不到固定 TOP5(0.99)也打不过固定 TOP7(0.89)→ 动态选币**朝错误方向移动效率前沿**。② **机制**:
按成交额排名 = 追入「刚被关注/刚 pump」的名字(高 $vol = 近期热度)= §16.1 截面动量陷阱的成交额版,在 pump 末段
买顶(SUI/WIF/PEPE/ARB 进池即接近顶部然后 chop/dump);**固定 TOP7 的 BTC/ETH/SOL 等结构性主流币才是最干净的
趋势载体,且在加密里并未像担心的那样衰减——主流币持续是 beta,「持有过去赢家」恰好对**。③ **动态唯一的好处是
maxDD 更低(−12.6%~−16.7% vs −20.6%),但那是「持更多币=广度」降 DD,不是动态选择加 alpha**(固定 TOP10-14 同样会
低 DD;§21 已证固定 TOP14 Sharpe 0.87 也低于 TOP5/7)。

### 22.4 结论(里程碑)+ owner 命题对账

**§21+§22 合成结论**:edge 在**「固定 + 高质量少数主流币(TOP5-7)」**,不在**「广度」**也不在**「动态轮换」**——
轮换追噪声、广度摊薄趋势。owner「边际来自交易什么而非信号增强」的直觉**半对**:§21 证固定 TOP5(0.99)≫ TOP14
(0.87)= 资产**质量/集中**真的重要;但由此外推「动态选币会更好」**被 §22 证伪**——不是「选择」(主动轮换)有用,
而是「静态锁定结构主流」最好。owner 自己那句「大多数看似合理的增强最后只带来边际改善(甚至变差)」在此精确兑现,
且这次是 ★★★★★ 的头号假设被**干净数据**否决。**与线 A/B/C/D 全弧第 N 次同型**:广度/选择从来不是约束,edge 量级
(锁定结构主流的趋势)才是。**realizable 最优仍 = §21 固定 TOP7 纯现货 S7-mini**;A 证伪,代码留存为「动态币池证伪
+ 可复用 PIT/ragged 引擎」资产。**E 低波因子不再做**(owner 正确指出与逆波动率重复下注;且 §22 已证选币方向无 alpha)。

---

## 21. 小资金现货 LIVE pilot(2026-06-14)——S7-mini 7 币 + ccxt 自动下单(owner 授权 ~$415)

owner 决定上**真钱小资金 ~$415(3000 RMB)**,先抓趋势、暂不要 carry 压舱石,问「能不能结合两线优化出
7 币小资金策略 + 接 API 自动下单」。本节 = 优化 RUN + 实盘执行模块 + 隔离/安全设计。

### 21.1 小资金优化 RUN(`scripts/research/x4_smallcap.py`)——两个真发现

扫**币数**(a priori 按流动性定档,非回测挑曲线)×**杠杆**(2x vs 现货 1x),S7 inverse_vol + BTC 大盘闸,
2021-01..2026-05(1d):

| 币池 | 杠杆 | total | Sharpe | maxDD |
|---|---|---|---|---|
| S3-BTC 单标的(基线) | 2x | +87% | 0.74 | −19% |
| TOP4(BTC/ETH/BNB/SOL) | spot 1x | +98% | **0.96** | −19% |
| TOP5(+XRP) | spot 1x | +101% | **0.99** | −20% |
| **TOP7(+ADA/LINK)** | **spot 1x** | **+86%** | **0.89** | −21% |
| TOP10 | spot 1x | +84% | 0.87 | −23% |
| TOP14(原 S7) | spot 1x | +80% | 0.87 | −21% |

- **优化 1:缩币是改进不是妥协**——5-7 个最流动币(0.89-0.99)**反打过** 14 币(0.87);原池被低流动山寨稀释。
- **优化 2:现货 1x ≡ 2x 杠杆**(数字几乎一致)——证实 §19.7「vol_target=2% 把仓位压在 1x 下、杠杆 cap 不绑定」
  → **纯现货跑零损失,且无清算风险**。对 $415 决定性。
- **定档 = TOP7 纯现货**(BTC/ETH/BNB/SOL/XRP/ADA/LINK),不选 TOP5 最高分(守不事后挑曲线纪律;0.89 vs 0.99 是
  样本内噪声,§17 头条被近期牛灌高,**诚实前向锚 ~0.6-0.7 / maxDD ~−20%**)。

### 21.2 实盘执行模块(`src/qount/x4/live.py` + `scripts/desktop/x4_live.py`)

**隔离(守线 A)**:**只复用通用 ccxt 件 `exchange_utils.build_exchange`**,**不走线 A 的 `Executor`**(冻结、
`QOUNT_LIVE_ENABLE=false` 不动);本线自带开关 **`QOUNT_X4_LIVE_ENABLE`**(默认关)。

**安全护栏**:① 纯现货 → 无杠杆/无清算/不可能负余额;② 硬上限 `capital_usdt`(总)+ `max_order_usdt`(单笔),
代码层拒超;③ **对账式下单**(读真实余额 → 比目标 → 只下差额,band 闸控)→ **幂等**(同账重跑 = no-op,不重复成交);
④ 三档 dry/live + 开关双锁;⑤ 市价单:BUY 用 `quoteOrderQty`(花 $X)、SELL 用 base 量按 stepSize 向下取整;
⑥ LOT_SIZE / MIN_NOTIONAL 过滤跳 dust。owner 选 **市价单 + 全自动 launchd**。

**目标权重**复用 §20.5 `_held_coins` 规则(per-coin SMA200 + 20/100 cross + BTC 大盘闸 + 逆波动率 parity),
提进 `live.target_weights`(纯件,无 look-ahead)。

**单测**:`tests/test_x4_live.py` +21(目标权重/闸、对账 diff/band/双上限/lot 取整/min-notional/卖不超持仓、
dry-不发单/live-无开关被拦/有开关才发)→ **x4 共 147 全绿;rv 56 回归绿**。

**dry-run 端到端验证(2026-06-14)**:bar 2026-06-12 → **gate=SHUT(BTC 在 200MA 下)→ 0 目标 → 0 单**,7 币全
skip,落 `state/x4/live/latest.json`。公共行情读取正常(无需代理),私有余额无 key 报 AuthenticationError → 按空仓
处理(设计如此)。**数据→闸→目标→读交易所→对账→日志全链路在 $0 市场风险下跑通。**

### 21.3 诚实定性 + 待办

**$415 上接 API 的价值 = 把下单/对账/护栏链路在亏得起的钱上跑通,不是那 ~$25/yr 的 edge**(薄 carry 同型)。
**当前 BTC 在 200MA 下 = 大盘闸关 = 接上也下 0 单**,正是低风险 burn-in 窗口:先验证读/对账路径,等 BTC 站上
200MA 再真开仓。**待办(需 owner 动手)**:① 建 Binance API key(**只开现货交易、关提现**、IP 白名单)→ 设
`QOUNT_BINANCE_API_KEY/SECRET`;② dry 跑几日确认订单清单合理;③ 设 `QOUNT_X4_LIVE_ENABLE=1` + 接 launchd 每日;
④ carry 压舱石(ETH cash-and-carry)留到资金放大到 ~$2-3k 再叠(BTC 季度 $100/张在 $415 下太粗;§20 已实现可复用)。

### 21.4 reviewer 增强候选 B/C/D 诚实检验(2026-06-14)——三个引擎开关 + train/test 切分

owner 转述一份外部 review,提 5 个增强(A 动态币池 / B 广度闸替代纯 BTC 闸 / C ADX 滤波 / D 相关性惩罚 /
E 低波动因子),并正确点出真问题:「**哪些真提升 Sharpe、哪些只是回测优化**」。落三个**默认关**引擎开关(不动现有行为/
155 单测全绿):`run_trend_portfolio(breadth_gate/breadth_combine)`(B)、`TrendFollow(adx_min/adx_period)`(C)、
`combine(scheme="inverse_vol_corr")`(D,逆波动率÷avg_corr,floor 0.2)。runner `x4_smallcap_optim.py` **逐个 vs
TOP7 spot 基线,切净值曲线 train(21-23)/test(24-26) 避预热偏差**,预注册判据 = **真改进须 train 且 test 都打过
基线 Sharpe 且 DD 不显著恶化**。

| 变体 | total | full S/DD | train S/DD | test S/DD | 判 |
|---|---|---|---|---|---|
| BASELINE TOP7 spot | +86% | 0.89/−20.6% | 0.66/−12.9% | 1.13/−20.6% | — |
| **B 广度-OR 0.5** | +93% | 0.94 | **0.75** | 1.13 | **弱 regime+(牛市中性)** |
| B 广度-AND 0.5 | +40% | 0.55 | 0.32 | 0.77 | worse |
| B 广度-only 0.5 | +45% | 0.59 | 0.42 | 0.77 | worse |
| C ADX≥20 | +74% | 0.88/−18.8% | 0.72/**−8.3%** | 1.03 | 降 DD/Sharpe 持平(风控档非 alpha) |
| C ADX≥25 | +46% | 0.65 | 0.58 | 0.73 | worse |
| **D 相关性惩罚** | +91% | 0.94 | **0.76** | 1.13 | **弱 regime+(牛市中性)** |
| **B-OR + D 组合** | +97% | **0.98** | **0.83** | 1.13/−20.2% | **弱 regime+,两杠杆叠加** |

**诚实结论**:① **B 广度-OR + D 相关性惩罚 = 唯一两个站得住的**,但**不是 REAL(两 regime 都打过),而是「只改善
2021-23 弱 regime(chop/熊),牛市完全中性、DD 中性」**——且**方向与 curve-fit 相反**(curve-fit 是把近期牛灌高,
这俩在牛市 test 恒 1.13 没动、只把 chop 的 0.66 抬到 0.75/0.76,组合叠到 0.83)。机制成立(BTC 横盘时广度-OR 捕 ALT
趋势、相关性惩罚把权重从 BTC/ETH/SOL 抱团里摊开),低下行风险,**采纳为 S7-mini 可部署默认(诚实标注:已证收益只在
chop/熊单 regime)**。② **C ADX = 风控档非 alpha**:把熊期 DD −12.9%→−8.3% 砍掉不少、但牛市 Sharpe 1.13→1.03,
net headline 持平 = sizing 型取舍;**怕回撤可开 ADX≥20,默认关**(ADX≥25 过度,worse)。③ **广度-AND/only、ADX≥25
全 worse**——去掉 BTC 闸保护或过滤过猛都伤。④ **A 动态币池 + E 低波动币池 = 需引擎支持时变 universe 成员(ragged
listing),当前 `run_trend_portfolio` 固定币池做不了,且静态用全样本选币=look-ahead**;记为下一轮引擎工作(E 部分
冗余,逆波动率已 low-vol 倾斜)。**元结论同 §14/§16.1/§19**:5 个增强无一产生跨 regime 的 robust Sharpe;baseline
(双闸+逆波动率)已近可实现天花板,最佳两个只在弱 regime 加边际、牛市中性。

### 21.5 固定 TOP7 基线上线(2026-06-14)——launchd 部署 + 仓库外 arming

经 §22 证伪动态币池、§21.4 证 B/C/D 只弱 regime 边际后,owner 定**上线 §21 固定 TOP7 纯现货 S7-mini**(BTC/ETH/
BNB/SOL/XRP/ADA/LINK · spot · 1x · 逆波动率 · BTC 200d 闸)= 未被任何增强击败的 realizable 最优。策略代码即
`x4/live.py`(`SMALLCAP_UNIVERSE` + `target_weights` 已是此规格),**无需改策略**,只补自动化:
- `scripts/desktop/x4_live_daily.sh`(wrapper:跑 `x4_live.py live` + 日志 `~/Library/Logs/x4_live.log` + 失败
  osascript 告警)+ `com.qount.x4-live.plist`(launchd 每日 10:05 本地 ≈ 02:05 UTC,对齐 x4-paper 后 5 分钟,7 天/周)。
- **安全 arming**:密钥 + 开关放**仓库外** `~/.config/qount/x4_live.env`(chmod 600,wrapper 存在才 source);
  文件不存在 → 跑 `live` 但 `QOUNT_X4_LIVE_ENABLE` 未设 → place_orders 打印拟下单、**发 0 单**。arm = 建该文件
  (`QOUNT_BINANCE_API_KEY/SECRET` 现货交易只读不提现 + IP 白名单,`QOUNT_X4_LIVE_ENABLE=1`)。
- **已 `launchctl load -w` + kickstart 端到端验证**:`com.qount.x4-live` 注册、跑通,`state/x4/live/latest.json` =
  `mode=live, armed=false, gate_open=false(BTC 在 200MA 下), 0 orders`。**当前未 arm + 闸关 = 双重零风险 burn-in**:
  自动累积拟下单记录,owner 建 env 文件即 arm,BTC 站上 200MA 即真开仓。停用:`launchctl unload
  ~/Library/LaunchAgents/com.qount.x4-live.plist`。

**切线收尾(2026-06-14)**:owner 定**停掉旧 3 线 paper + 把新实盘上面板**。① `launchctl unload
~/Library/LaunchAgents/com.qount.x4-paper.plist` 停掉 §18/§19.7/§20.4 的三条模拟 track(3 腿/S7/C×D combo;源码与
`state/x4/paper/` 历史保留,随时可重 load)。② Übersicht 面板换装:撤下 `x4paper.jsx`(3 线持仓面板)、装上
`x4live.jsx` + `x4live_fetch.sh`(读 `state/x4/live/latest.json`,纯本地只读),显示武装状态 / BTC 大盘闸及距离
(当前 BTC 63.5k vs 200MA 77.9k = −18.4%,闸关)/ 资金部署 / 持仓(闸开时按逆波动率)/ 当日订单(未武装标"拟")。
`x4_live.py` 快照富化(+`capital/deployed/cash/btc_px/btc_sma200/btc_to_sma/holdings`)供面板用。`ctar.jsx`(线 A)不动。

**代理坑修复(2026-06-14,境内必读)**:owner 报浏览器打不开币安。诊断=本机跑 Clash 代理 `127.0.0.1:7897`,**终端有
`HTTP_PROXY` 故 curl 币安全域名 200/202 通,但浏览器走规则模式 binance 落 DIRECT → GFW 墙网站**(修:Clash 开系统代理/
全局/加 binance 规则)。**关键连带坑:launchd 不继承 shell 的 `HTTP(S)_PROXY`** → 实测之前 kickstart 真的 ccxt
`RequestTimeout: api.binance.com/exchangeInfo`(无代理连不上)。**修复(`x4_live_daily.sh`)**:① 头注释标坑;
② source env 文件后**归一化代理变量**(从 `QOUNT_HTTPS_PROXY/HTTPS_PROXY/HTTP_PROXY/ALL_PROXY` 取到的统一导出给
curl + ccxt,`build_exchange` 读 `QOUNT_HTTPS_PROXY`);③ **预检** `curl api.binance.com/api/v3/ping`,连不上则
`[ALERT]`+osascript 通知+`exit 1`**跳过本次,不盲目下单**(实测无代理路径 = 干净告警退出,非 ccxt traceback)。
**arm 时须把代理也写进 `~/.config/qount/x4_live.env`**(`export HTTPS_PROXY=http://127.0.0.1:7897`),否则 launchd
跑不通。**运维提醒:本套靠本地代理连币安,代理一断真单推不出 → wrapper 失败通知会触发,Clash 须常驻。**

**反爬 / 节点 / IP 白名单坑(2026-06-14,境内建 key 必读)**:owner 系统代理(Clash 设上 7897)后浏览器仍打不开币安。
诊断到底层:**①交易 API `api.binance.com` 在该节点 HTTP 200 返真数据(BTC 价)= bot 完全正常,只用 API 不受影响;
②网页 `www`/`accounts.binance.com` HTTP 202 + 0 字节 = 币安反爬拦截该出口 IP**(台湾电信数据中心 IP `1.168.186.131`,
共享机房 IP 被风控标记 → 空挑战页 → 浏览器空白)。**与 Safari/Clash 规则/系统代理全无关**——curl 和浏览器拿到同一个
空 202,换浏览器/重启/刷 DNS 都没用,加 Clash 规则也没用(规则已全放行,curl 走代理证实 binance 全域名可达)。**建 key
两条路**:① Clash 换节点(多试几个,只需一个网页端没被反爬标记的出口)→ 开 `accounts.binance.com`;② **手机币安 App
建 key(住宅 IP 不被反爬,最省事,绕开桌面节点)**。**IP 白名单坑**:代理出口是共享/可能轮换的节点 IP,若给 key 绑 IP
白名单而节点 IP 一变 → bot API 调用被拒(每天可能断)。两选:用**固定出口 IP** 的机场专线节点再绑白名单;或 **$415 小
资金先不绑 IP 白名单**,靠「只勾现货交易 + 关提现」保证安全(最坏 key 泄露也只能交易不能提币)。

---

## 20. C×D 合成账 kill-test(2026-06-13)——趋势(线 D)+ carry(线 C)压舱石,PASS

承上一轮元判断:三条加密线只活下来两个**赚不同钱**的 edge,而且**尾部指向相反**——线 D 的 S7 趋势是方向性
crypto-beta(诚实前向 ~0.70、maxDD −21% 调参砍不掉,死法=暴跌),线 C 的 RV-C BTC/ETH dated cash-and-carry 是
delta-neutral(Sharpe ~1.4、薄 +6.4%/yr、回撤极小,尾部=向上逼空)。**命题**:一个容量受限的小 carry sleeve 当
**压舱石**(线 A「金/债压舱石」同型),应同时抬合成 Sharpe + 砍趋势自己砍不掉的尾。

### 20.1 工程(复用,不改 C/D 模块)

纯件 `src/qount/x4/combo.py`:`align_curves`(两引擎不同数据源/不同 bar 数 → 按 UTC 时间戳取交集 + 各自归一化到
初始本金,按 ts 配对使两引擎半根 bar 约定差无影响)、`combine_fixed`(**固定权重**逐 bar 再平衡——carry 容量受限,
a priori 按容量定占比比让 inverse_vol 给薄低波 sleeve 灌权重更诚实)、`kill_verdict`。复用 `x4.portfolio`
(correlation/sharpe_of)+ `rv.stats`,**未改线 B/C/D 任何模块**。**+9 单测 → x4 共 126 全绿;rv 53 / grid 106 回归绿。**
runner `scripts/research/x4_combo.py`:TREND=S7(inverse_vol/BTC闸/vt2% 可部署档)+ CARRY=RV-C BTC+ETH(always-on
maker inverse L=3 认证档,两腿等权合成)。**预注册杀线**:在**可部署 carry 权重(≤40%,容量封顶)**下,合成必须
**同时**打过 trend-alone 的 Sharpe **且** maxDD 更浅;否则合成无意义,杀。

### 20.2 实测结果(2021-01..2026-03,1898 共同日 bar)——PASS

`corr(TREND, CARRY) = −0.196`(**负相关**,比预期的零相关更好,印证反向尾部命题):

| 账本 | total | Sharpe | maxDD |
|---|---|---|---|
| TREND alone(S7) | +80.2% | 0.89 | −21.4% |
| CARRY alone(BTC+ETH) | +33.5% | 1.28 | −5.1% |
| **80/20** | +71.4% | 1.00 | −15.9% | **PASS** |
| **70/30** | +66.8% | 1.08 | −13.1% | **PASS** |
| **60/40** | +62.2% | **1.18** | **−10.2%** | **PASS** |
| 50/50 | +57.5% | 1.31 | −7.2% | PASS |

**所有 carry 权重全过双门。** 可部署 40% carry:Sharpe **0.89→1.18(+0.30)**、maxDD **−21.4%→−10.2%(尾砍近半)**。
代价 = 绝对收益 +80%→+62%(40% 本金从趋势发动机挪进薄 carry,放弃部分上行)——但这正是预注册接受的取舍:**用
absolute upside 换 risk-adjusted return + 砍尾**,杀线只要 Sharpe↑ 且 maxDD↓,达成。artifact 落
`state/x4/research_runs/combo_*.json`。

### 20.3 结论与诚实 caveat

**C×D 合成账 = PASS:carry 压舱石真能给 S7 趋势抬 Sharpe(0.89→1.18 @40%)+ 砍尾近半(−21%→−10%),负相关
−0.20 是结构性的(方向 vs 中性),非样本运气。** 这是跨三线**第一次把两个独立认证的 edge 拼成一本更优的账**,
完全在隔离边界内(纯件复用、未改 C/D 模块)。**诚实 caveat(写进 runner 输出)**:两条 sleeve **都隐性做多同一个
「crypto 还活着 / contango 持续」宏观因子**——carry 在持续 backwardation 段会转负(§7.9)、趋势靠闸空仓零收益,
**多年加密寒冬下两者会同时变薄**。所以正交性**在短期尾部(崩盘 vs 逼空)是真的,在多年 regime 层是假的**:合成账
改善 Sharpe 与短期回撤,**但不是全天候**。与线 A「远期诚实 ~7-9% 非头条、近年靠金+债需盯反转」同型。

### 20.4 forward paper 化(2026-06-13)——第三条 track 上线

60/40 合成账已 forward paper 化(§18/§19.7 同构,纯模拟无真单):`x4_paper.py` 加 `forward-combo` 模式
(每日重跑 S7 趋势 + RV-C BTC+ETH carry 两 sleeve → `align_curves` 按 ts 交集 → `combine_fixed` 60/40 →
快照落**独立** `state/x4/paper/combo_snapshots.jsonl` / `combo_latest.json`,不撞前两条 track)。
`x4_paper_daily.sh` 加第三条 `run_track forward-combo`,launchd 每日三条 track 各查独立 marker、任一失败告警。
combo 60/40 = **$162,393 / +62.4% / Sharpe 1.16 / maxDD −10.2%**(corr −0.20、trend-alone 0.87/−21.4%、
carry-alone 1.27/−5.1%),与 §20.2 in-sample 一致;daily wrapper 三 track 0 ALERT。

**combo 日更(2026-06-13,修掉月更约束)**:carry 的 dated 合约 leg 原只读 monthly dump(§18 日包 fallback 只惠及
spot/um),曾使 combo 卡在上月末。**实测 Binance 也发 dated 合约的 per-day dump**(2026-06-10/11/12 全 HTTP 200,
6 月月包 404)→ 给 `rv.data` 加 dated 日包 fallback(`dated_day_url`/`download_dated_day`/`_download_dated_month_daily`,
镜像 §18;**仅对当前进行中月触发**,过去 404 月是合约未上市不浪费请求)。**+3 单测 → rv 共 56 全绿;x4 126/grid 106
回归绿**。combo 现推进到 bar 2026-06-12,**三条 track 全部日更对齐**。caveat 收窄为只剩"非全天候"(两 sleeve 同多
crypto-beta 宏观因子)。

**桌面面板(线 A 同型,Übersicht)**:owner 实际跑的宿主是 **Übersicht**(线 A 用的是 `ctar.jsx` 组件,非 SwiftBar
——SwiftBar 未安装)。故主面板 = `scripts/desktop/x4paper.jsx`(Übersicht 桌面组件)+ `x4paper_fetch.sh`(取数)。
与线 A 的 `ctar.jsx` 关键区别=**数据全在 Mac 本地**(`state/x4/paper/*latest.json`),**无需 ssh 读 WSL**,纯本地只读。
显示:大字 combo 总收益、前向净值曲线(自部署起成形)、三条 track 的净值/总收益/Sharpe/maxDD + 当前持仓态(3 腿空仓
闸防御 / S7 趋势空仓 BTC 闸关 / combo 趋势空仓+carry 恒在场)+ corr + 数据 bar 新鲜度;可拖动记住位置。装入
`~/Library/Application Support/Übersicht/widgets/`。snapshot 补 `trend_flat` 字段(BTC 末根 vs SMA200,便宜)供面板
显示实时空仓态。(SwiftBar 形态 `x4paper.5m.py` 已删——owner 未装 SwiftBar,避免混淆。)

### 20.5 面板改"以今天为准"的实际持仓(2026-06-13)

owner:面板别显示**回测收益**(+62.4% 是 2021-26 样本内,误导),要**以今天为部署起点**显示**实际持仓的价格/数量/
收益**。新增 `x4_paper.py holdings` 模式 + `holdings_latest.json`:① **前向锚**=首次运行 pin `deploy_date`=今日、
`anchor_bar`=最新 bar,各账 equity 曲线**重基到 deploy 当根 $100k** → 前向收益**今日起从 0 累积**(非回测);
② **实际持仓**=combo 的 carry 4 腿(BTC/ETH 现货多 + 当前活跃 dated 合约 `BTCUSD_260626`/`ETHUSD_260626` 空,各
$20k 名义、按当前日收盘价标数量)+ 趋势持仓(当前 BTC 在 200MA 下→**趋势空仓**,持仓 0)+ 现金;**carry delta-neutral
记一次资金**(40%=$40k,空腿是对冲不额外占资金,不重复计 → 现金 = 趋势 60% = $60k)。面板 `x4paper.jsx` 重写为
**持仓表**(方向/币种/数量/现价/市值)+ 自部署收益 + 现金,**不再显示回测净值/收益**;`x4paper_fetch.sh` 改读
`holdings_latest.json`。daily wrapper 加第四条 `run_track holdings`,0 ALERT。**当前实测**(deploy 2026-06-13):combo
前向 +0.00%/$100k(今日起算)、现金 $60k、4 腿 carry 在场(基差极薄 dated≈现货 +0.04%)、趋势空仓待 BTC 站上 200MA。
三 track + holdings 转纯 OOS 运营。

---

## 19. S7-TREND-PORT 多币趋势组合(2026-06-13)——预注册计划(翻转命题:分散已验证信号,不选币)

owner 问:别在 BTC 上耗着,能不能聚类多币、从不同大类选最强几个、看协方差(top5)?**先 review 命题再定方向。**

### 19.1 为什么不做"聚类选币"(否定 §16.1 重演)

§16.1 的 S6-XMOM(截面动量 top-K 轮动)已**实测证伪**,且关键事实:**那 −86% maxDD 是带着每币各自 SMA200 闸
发生的**(`cross_sectional_rank` 已含 per-symbol regime gate + 只选正动量)。所以:

1. **加趋势闸救不了**——闸滞后,进场时"在 200MA 上"的最热山寨照样跳水 86%;**集中度(top1)才是凶手**。
2. **选币动作本身负 alpha**——§16.1 证 naive 等权持有全 universe(Sharpe 0.77)> 选币(0.71)。帮上忙的是
   **"持有更多名字"(分散)**,不是 **"选"**。聚类 / 协方差只改"配权重",改不了已判死的信号内核。
3. **协方差是 error-maximizer**——逆协方差权重放大估计噪声(Markowitz);加密相关性非平稳、崩盘趋近 1,
   平静期估的结构正好在尾部失效。**最需要分散的那一刻救不了你。**
4. **聚类基本是噪声**——14 标的全大盘 BTC-beta(互相关 0.7-0.9),板块标签(L1/L2/DeFi/meme)不对应独立风险
   因子,risk-on/off 一起动。"每簇选一个"很可能是 5 个仍 0.8 互相关的币 = 假分散。
5. **幸存者偏差**——universe 全是活到 2026 的;截面山寨动量回测被系统性灌高(归零币不在样本)。

### 19.2 命题翻转:S7-TREND-PORT(分散 × 已验证信号)

把命题从 **"选哪几个币"(选择)** 翻成 **"把 §17 唯一过样本外的趋势信号铺到多币上"(分散)**:

> 在每个币上**独立跑 S3 趋势**(walk-forward 过 0.70、泛化 ETH 0.53-0.55 的真 edge),每币自带 SMA200 闸自然让
> 下跌的币空仓,**再按逆波动率等风险合成**(复用现成 `portfolio.combine(scheme="inverse_vol")`,无 look-ahead)。

吃的是**已证真信号 × 真分散**(各币趋势择时的 idiosyncratic timing),不是 §16.1 的**已证伪信号 × 集中**。
不做截面 rank、不赌"谁最热";哪个币有趋势就在哪个币顺势,没趋势空仓——真实多市场 CTA 的标准做法。

### 19.3 工程落点(纯件,先写单测;复用 run_directional + TrendFollow + combine 不改)

- `strategies.py`:`sma_regime_mask(closes, window) -> list[bool]`(纯件:bar t 收盘是否在自身 window-SMA 上,
  warmup→False,无 look-ahead)= **BTC 大盘闸** overlay 的判据。
- `backtest.py`:`run_trend_portfolio(bars_by_sym, *, fast/slow/regime_sma, weighting, master_gate_sym,
  master_gate_sma, vol_target/max_leverage/chandelier..., fees)`。每币 `run_directional(TrendFollow long-only +
  regime_sma)` → per-sleeve curve;`combine(scheme=weighting)` 合成(逆波动率在**真**sleeve 收益上算,正确);
  **BTC 大盘闸**作顶层 risk-off:`master_gate_sym` 跌破其 SMA 的那一步组合收益置 0(吃现金)。`extra` 暴露
  per-sleeve curves / n_syms / gate_active_frac。
- 协方差**先不上**:逆波动率(等风险)在加密里大概率与 HRP 一样好且更稳;真要协方差感知用 **HRP(避矩阵求逆
  噪声放大)**,等等风险版立住再说,否则分不清是分散有用还是优化器过拟合噪声。

### 19.4 预注册判据(跑前写死,赛马非 kill-test 但杀线明确)

- **对照基线(必须打败)**:① S3-on-BTC(0.70 / maxDD −29%);② **naive 等权持有全 universe(0.77)**——
  §16.1 证这是真正难打的那个。
- **杀线**:Sharpe **同时** > 0.70 且 > 0.77,**且** maxDD **显著优于单 BTC(目标 < −25%)**——分散本就该降 DD;
  若只是 return 高、DD 也高 → 同 §16.1 判负、留存证伪。
- **测量诚实性前置**:universe 必须处理幸存者偏差(point-in-time 上市名单或纳入退市/归零币历史),否则比较无效。
- **诚实先验**:加密 beta 主导 → 跨币分散收益**比传统多资产 CTA 小**(一起跌救不了系统性尾部);但 alt 有
  BTC-only 抓不到的 idiosyncratic 趋势 + 每币闸砍单币尾 → 合理预期**更平滑净值 / 更低 maxDD,Sharpe 小幅改善**
  (把 −29% 压到 −20% 出头、Sharpe 站稳 0.7+),**别指望翻倍**。
- **更狠的诚实问题**:若多币趋势组合也打不过 S3-on-BTC,则线 D realizable 结论 = **「BTC 单标的趋势 + 风控已是
  天花板,多币只是雕花」**——与线 A「广度从来不是约束、edge 量级才是」同型,本身有价值。

### 19.5 本轮交付边界

本轮 = **预注册计划写回 + 先写单测 + 引擎实现(保持绿)**。**研究 RUN(对照 §19.4 基线的赛马 / 杀线判定)是下一
步**,由本预注册治理(跑前不调参挑曲线)。

### 19.6 研究 RUN 结果(2026-06-13)——杀线 FAIL(尾部),但命题成立(Sharpe)+ 幸存者稳健性强

`scripts/research/x4_trendport.py`(交集对齐 + 14 币幸存者 universe,**与 §16.1 apples-to-apples**;S3 验证参数
fast20/slow100/regime200、vol_target3%/2x;扫 {equal,inverse_vol}×{无闸,BTC 大盘闸})。

**CORE(14 币,2021-01..2026-05,1972 bars):**

| 策略 | total | Sharpe | maxDD |
|---|---|---|---|
| naive 等权持有 | +393.6% | 0.77 | −78.7% |
| S3 BTC 趋势(单) | +124.7% | 0.70 | −28.9% |
| S7 equal/BTC闸 | +42.4% | 0.50 | −21.7% |
| S7 inverse_vol/无闸 | +128.6% | 0.76 | −45.8% |
| **S7 inverse_vol/BTC闸** | **+134.7%** | **0.88** | **−30.5%** |

**逐预注册判据(§19.4)对账**:① Sharpe **0.88 同时 > S3 的 0.70 且 > 等权持有的 0.77 → 过**;② maxDD **−30.5% 未达
< −25%、且 ≈ 单 BTC 的 −28.9%(没降反略升)→ 不过**。**两条须同时满足 → 严格杀线判定 = FAIL**(不挪门,守线 A 不
事后挑曲线纪律)。两条各自的 intent:**"分散能不能加 risk-adjusted 价值"= 成立(命题对,选择→分散这一翻转正确,
决定性打过 §16.1 的选币 0.71)**;**"分散能不能砍尾"= 不成立(crypto-beta 主导,一起跌,多币趋势没把系统性回撤压到
单 BTC 之下)= §19.4 诚实先验精确兑现。** 机制:inverse_vol 自动把资本路由到**在趋势中的**腿(现金腿 std=0→权重 0),
故 ≫ equal(等权浪费在空仓腿);BTC 大盘闸把 inverse_vol 的 −45.8% 压到 −30.5%(闸有效但不够)。

**杠杆/风险预算诊断(2026-06-13 补)**:扫 max_leverage 1.0→2.5,**Sharpe 恒 0.88-0.89、maxDD 恒 −30%**——
因 vol_target=3% 波动率定仓早把仓位压在 1x 下,**杠杆 cap 不绑定**。推论:① Sharpe 是杠杆不变量且稳健 = S7 真打过
S3 的 0.70(杠杆无关的真相);② **−30% DD 不是杠杆 artifact、砍不掉**——是 vol_target 这个风险预算的产物,加密崩盘
波动率飙+相关性趋近 1 下,波动率定仓+双闸+14 币分散仍 −30%。**故 §19.4 的 maxDD<−25% 本质是"风险预算/Sharpe"
之争**:同 Sharpe 下调 vol_target(3%→2%)→ DD≈−20% 过线但收益同比缩(沿前沿挪,非加 alpha);**同杠杆下 S7 在
Sharpe 上严格占优 S3**。即杀线 FAIL 半是"绝对 DD 门 leverage-dependent"所致,risk-adjusted 真相是 S7 > S3。

**STRESS(CORE + ICPUSDT 重伤幸存者,1816 bars):幸存者偏差结论(本轮最强信号)**:加一个从发行跌 ~95% 的币,
**等权持有 Sharpe 0.77→0.16 崩(total −52.9%,一路扛跌)**;**S7 inverse_vol/BTC闸 0.88→1.02 反升**(每币趋势闸早把
ICP 平掉)。→ **§16.1 当作"难打的基线"的等权持有 0.77 本身是幸存者偏差产物,加一个暴雷币就塌**;**S7 因趋势闸退出
垂死币,结构上远低于幸存者偏差暴露**。这反而强化:S7 的真实相对优势比 CORE 表更大。

**结论**:① **§19.2 命题对**——分散已验证趋势信号 risk-adjusted 决定性胜过 §16.1 的截面选币,且 Sharpe 过两基线;
② **但严格杀线 FAIL 于尾部**——多币没把回撤压到单 BTC 之下(crypto 一起跌),S3-on-BTC 仍是 maxDD 之王;③ **S7
inverse_vol/BTC闸(0.88/+134.7%/−30.5%)是比 S3 更高 Sharpe/更高收益、近似 DD 的合理候选**,但**头条 0.88 仍是
样本内被近期牛灌高**(§17:S3 诚实前向 ~0.70 walk-forward / 0.53-0.55 ETH 泛化),前向应锚更低、按 ~−30% DD size。
**未做**:完整 point-in-time/归零币 universe 需引擎支持参差上市(ragged listing),记为后续;协方差/HRP 权重按 §19.3
仍不上(逆波动率已够,且尾部问题不是权重能解的)。

### 19.7 可部署 size 定档 + forward paper 化(2026-06-13)

**B 可部署 size(按风险预算定 size,非加 alpha)**:扫 vol_target(max_leverage 固定 2x),**Sharpe 恒 ~0.87 不变**、
DD/收益同比缩放:1.5%→−16.5%/+56.9%、**2.0%→−21.4%/+80.2%**、2.5%→−26.2%/+105.8%、3.0%→−30.5%/+134.7%。
**定档 vol_target=2.0%**:+80.2% / Sharpe 0.87 / maxDD **−21.4%**,过预注册 −25% 门有余量。此档下严格杀线三条全过
(0.87 > 0.70 且 > 0.77 且 −21.4% < −25%),但**诚实标注:过门来自 sizing(Sharpe 不变),不是找到新 alpha**;与 §18
3 腿「按保守 size 部署」同纪律。**为何不再继续优化**:杠杆/vol_target 扫描证 Sharpe 是杠杆不变量、~0.88 是这套方法
in-sample 天花板附近;§14 集群化=鲁棒保险非 alpha、§16.1 选择=负、§17 头条被牛灌高。再调参 = 雕 2021-26 单窗口。
**−30% 尾砍不掉是 crypto-beta 结构问题(一起跌),非调参能解。** 故停 in-sample 优化,转 OOS 前向。

**A forward paper 化(§18 同构,独立 track)**:`x4_paper.py` 加 `forward-s7` 模式 + `_load_universe`(交集对齐,走日包
fallback 每日推进)+ 部署配置常量;快照落**独立** `state/x4/paper/s7_snapshots.jsonl` + `s7_latest.json`(不碰 3 腿
§18 文件)。`x4_paper_daily.sh` 抽 `run_track` 函数,launchd 每日**两条 track**(forward + forward-s7)各查独立 marker、
任一失败告警。端到端验证:forward-s7 推进到 bar 2026-06-12,equity $180,213/+80.2%/0.87/−21.4%、**BTC 大盘闸 49% 时间
在场**、与回测一致;daily wrapper 跑通无 ALERT。**前向预期(§17 锚):Sharpe ~0.70(非 in-sample 0.88),按 ~−21% DD size。**

**S7 最终态**:命题成立(分散 > 选择、Sharpe 占优两基线)、严格杀线在 vol_target=2% 档过、**S3-on-BTC 仍单标的 DD 之
王而 S7 是更高 Sharpe 的多币候选**;已 forward paper 化,转纯 OOS 运营。代码留存为可复用多币趋势组合资产。

---

## 18. B2 模拟盘部署(2026-06-13)——3 腿引擎建成 + 验证 + 前向就绪

owner 定:部署 **3 腿(S1+S3+S4,剔除 §17 证伪的 S2)**,先回放验证引擎再真前向。落 `x4/papersim.py` 引擎 +
`scripts/research/x4_paper.py` ops runner(+6 单测 → x4 共 **105 全绿**)。

**引擎设计(保真度由构造保证)**:paper = 每日累积 bar → **重跑确定性回测**(`run_grid`+`run_directional`×2 +
`combine`)→ 落新 equity 点。因回测因果无 look-ahead,重跑全历史 ≡ 增量,**sleeve 净值与 §15 回测 bit-for-bit
相同**(`test_x4_papersim.py` 钉死 fidelity + incremental==full-rerun)。无真单,纯模拟。

**回放验证(真实数据)**:组合 **+72.9% / Sharpe 0.76 / maxDD −16.7%**(精确匹配 §17 的 S1+S3+S4);sleeve 总
S1 +5.4 / S3 +115.2 / S4 +98.4 逐根对齐 §15 → **引擎验证通过**。**当前状态信号:截至 2026-05-31 三腿全空仓**
(S3/S4 w=0、S1 无库存,equity 自 2026-01 冻结)→ **BTC 在 SMA200 下、regime 闸正确让全员吃现金躲非趋势期**
(设计的防御行为,非 bug)。

**前向就绪**:`x4_paper.py forward` 拉最新日 bar、跑引擎、追加快照到 `state/x4/paper/snapshots.jsonl` +
`latest.json`。**每日 cron 此命令累积前向记录**(日线策略,有意义读数需数月,慢速前向验证)。

**预注册判据(跑前写死,§17 重校)**:① 前向 Sharpe ~0.4-0.7(非 in-sample 0.88);② 组合 maxDD ~−17%;
③ **关键机制:遇熊/震荡 SMA200 闸应让 S3/S4 空仓、组合不深亏**(回放已见 2026 空仓防御,正是此机制)。
paper 检查 = execution 保真(已构造保证)+ 前向落在预注册带内 + 换手/费匹配回测。

**每日自动化(已装 + 验证)**:`scripts/desktop/x4_paper_daily.sh`(wrapper:`.venv` 跑 forward + 日志
`~/Library/Logs/x4_paper.log` + 失败 osascript 通知)+ launchd `com.qount.x4-paper`(每日 10:00 本地 ≈ 02:00 UTC,
7 天/周,对齐既有 `ctar-daily` 约定但去掉 weekday 过滤);plist reference 存 `scripts/desktop/com.qount.x4-paper.plist`。
**已 `launchctl load -w` + kickstart 验证端到端跑通**(写日志 + 追加快照)。停用:`launchctl unload
~/Library/LaunchAgents/com.qount.x4-paper.plist`。(注:同日重跑会按 bar 日期追加重复行,分析时按 date 去重即可。)

**日包 fallback 修复(2026-06-13)**:发现前向**实际推进不了**——`grid.data.load_klines` 只读 **monthly** dump,
当月(in-progress)的月度包要到月末后才发布,`skip_missing=True` 直接跳过整个当月 → forward 永远卡在上月最后一根
(实测连跑两次都停 2026-05-31)。「每日」任务实为「每月」任务。**修复**:`load_klines` 月包缺失时回退到 **per-day
dump**(`day_url`/`download_day`/`_download_month_daily`,只迭代到今天 UTC、逐日独立缓存、未发布日 404 跳过),
`skip_missing` 语义保留(日包也全空才跳/raise)。`x4_paper.py`/launchd **一行未改**,fallback 在数据层透明生效。
**+3 单测(`day_url` 形状 + 日包补齐 + 日包缓存)→ grid 共 106 全绿;x4 105/线 C 53 回归绿**。验证:`forward`
现自动推进到 **bar 2026-06-12(n_bars 1989)**。**caveat**:funding 仍仅 monthly(binance 不发 funding 日包,已验
404),当月 funding 回退 0;现 S1 空仓/S3-S4 不吃 funding 故无影响,carry 上仓时此处会偏乐观,需另接日度 funding 源。
**6 月实测**:BTC 在 200MA 下(73.6k vs SMA 79.5k,价/SMA 0.926),6 月震荡下行 71.4k→60.9k 再回 63.5k(深 −15%),
三腿全程空仓 → 组合净值钉死 $172,903 零波动 = **SMA200 闸防御机制在真前向中如期生效**(预注册判据③兑现)。

**B2 状态:引擎建成 + 真实数据验证 + 前向持久化 + 每日 launchd 自动化 + 日包 fallback(真正每日推进),全就绪。**
下一步纯运营:每日自动累积、周/月对账(paper vs 回测同期)。deployable = S1+S3+S4 等权(无 S2),按 ~0.5 Sharpe /
−17% DD 保守 size;2x vol-parity 杠杆在真账户须建清算线。

---

## 17. 样本外 / Walk-forward 验证(2026-06-13)——趋势族过、S2 证伪、预期重校(里程碑)

§9-§16 全弧的参数都在 2021-26 整段上选 = 样本内。这是诚实性检验(`x4_walkforward.py`,无新 src,切片测量
全序列净值避 warmup 偏差,因果无 look-ahead)。三部分:

### A. 固定当前参数 TRAIN(21-23) vs TEST(24-26)

| 策略 | TRAIN total/Sharpe/maxDD | TEST total/Sharpe/maxDD |
|---|---|---|
| S1-GRID | +2.6% / 0.23 / −4.5% | +2.7% / 0.55 / −2.7% |
| S2-PAIR | +12.3% / 0.30 / −22.2% | +29.8% / 0.78 / −14.2% |
| S3-CTA | +18.4% / **0.35** / −26.8% | +76.0% / **0.94** / −29.4% |
| S4-MOM | +13.4% / **0.33** / −22.4% | +69.5% / **0.99** / −23.8% |
| S1+S3+S4 等权 | +13.7% / 0.40 / −12.9% | +48.9% / **1.05** / −16.7% |

**全部 test ≫ train → edge 高度集中在 2024-26 近期牛;2021-23 Sharpe 仅 0.33-0.40。头条 0.67-0.88 是被近期牛拉高的
均值,诚实前向预期应锚在 train 的 ~0.4。**

### B. Walk-forward 选参(真正的过拟合检验):TRAIN 选参 → 读 TEST

- **S3:TRAIN-best (10,80,0.03) → TEST Sharpe 0.70**(事后 TEST-best 1.06)。**用过去选参前向仍拿稳健 0.70 → S3 通过,
  edge 真实**(过拟合代价 = 0.70 vs 1.06,但前向仍正且强)。
- **S2:TRAIN-best (30,2.5,3.0) → TEST Sharpe −0.75(亏!)**(事后 TEST-best 60,2.5,3.0 = 0.78)。**一直用的 window=60
  只是事后才好看;诚实前向选参选出 window=30,在 test 亏损 → S2 明确过拟合 FAIL**。§13 的「S2 脆」caveat **从怀疑变证明**。

### C. ETH 泛化(BTC-selected 参数直接上 ETH)

| | total | Sharpe | maxDD |
|---|---|---|---|
| S3 on BTC | +115.2% | 0.67 | −29.4% |
| **S3 on ETH** | +76.3% | **0.55** | −32.1% |
| S4 on BTC | +98.4% | 0.70 | −23.8% |
| **S4 on ETH** | +60.0% | **0.53** | −25.2% |

**趋势 edge 泛化到 ETH(0.53-0.55,正且同型)→ 非 BTC 单标的拟合。**

### §17 结论(里程碑)

1. **趋势族 S3/S4 = 整轮唯一通过样本外的真 edge**:walk-forward 选参 0.70、ETH 泛化 0.53-0.55。**前向可信。**
2. **S2 = 确认过拟合 FAIL**:walk-forward 前向亏损 −0.75。**部署必须剔除 S2**(§13 caveat 被证明)。
3. **预期重校(诚实)**:edge 集中近期牛,**前向 Sharpe 大概率接近 train 的 ~0.4-0.7,非头条 0.88**;maxDD 真实
   (S3/S4 单腿 ~−25~−30%,组合 ~−13~−17%)。**部署用 S1+S3+S4(无 S2),按 ~0.5 Sharpe / ~−17% DD 的保守预期 size,
   不按 in-sample 0.88。**
4. **这是 X4 从「回测好看实验」转「前向可信」的关键检验**:好消息 = 趋势 alpha 真实且可泛化;诚实的坏消息 =
   量级被近期牛灌高、S2 是幻觉。与线 A CTA 主线「远期诚实 ~7-9%/yr 非头条 12%」同型纪律。

---

## 16. 剩余路线图:新数据/新市场(2026-06-13)——S6 实测证伪 + 两个设计-only

owner 路线图三项需新数据/市场。**可用现有 binance.vision 数据做的(S6 截面动量)→ 直接实现实测;另两项(Maker/LP、
stETH)→ 设计-only,标注数据阻塞。**

### 16.1 S6-XMOM 截面动量山寨轮动 —— 已实现 + 实测**证伪(risk-adjusted)**

落 `cross_sectional_rank`(纯件:波动率调整动量 = mom/σ,按各币自身 SMA200 闸,选 top-K)+ `run_cross_sectional`
(每 rebalance_days 轮动、等权 top-K、换手计费;+8 单测 → x4 共 **99 全绿**)。`x4_xmom.py` 14 标的 universe、
2021-26、扫 lookback/top_k/rebalance 18 配置,**杀手对比 vs 三基线**:

| 策略 | total | Sharpe | maxDD |
|---|---|---|---|
| BTC 买入持有 | +151.1% | 0.58 | −76.7% |
| **universe 等权持有** | **+393.6%** | **0.77** | −78.7% |
| **S3 BTC 趋势** | +124.7% | **0.70** | **−28.9%** |
| XMOM 最优(lb30/top1/rb7) | +295.6% | 0.71 | **−86.1%** |

**终判:截面选择 = 负 alpha**。① 全部 18 配置 maxDD **−83~−93%**(灾难);② 最优 Sharpe 0.71 **既不过 S3(0.70 但
maxDD 只 −29%)、也不过 naive 等权持有(0.77)** → **排序/轮动加了换手($10-25k)+ 集中度风险却没提 Sharpe,反不如
持有全 universe**。根因 = **线 C 广度面板教训复现**:动量追入最热山寨 = 买在波动最大名字的顶部 → −86% 尾灾。
**「2024 山寨轮动 alpha」在 RETURN 上真实(等权 +393%)但在 RISK 上不可投(−79~−86% 回撤 = 清盘级)**。
**S3 BTC 趋势仍是 risk-adjusted 之王(0.70 / −29%)。** 可能的尾控后续(basket 波动率平价 + BTC 大盘闸 + 吊灯)留作
设计,但核心已清:截面选择不增 alpha。代码留存为「山寨截面动量证伪」资产。

### 16.2 Maker-only / Uniswap V3 LP —— 设计-only(数据阻塞:盘口队列 / 链上)

**命题**:S1 网格散户 taker 没活路(§9/§12),本质是做市/提供流动性,应转 Maker 赚费率甚至返佣,或迁 Uniswap V3
集中流动性赚 swap 费。**预注册设计**:① CEX Maker:Post-Only 挂单 + 队列填充模型(挂单是否成交取决于对手 taker 流量,
有逆向选择);判据 = maker 返佣 + 价差 − 逆向选择损失 > 0。② Uniswap V3 LP:ATR 动态区间设集中流动性,收益 = swap 费 −
**无常损失(IL)** − gas;判据 = 费 − IL − gas > 持有。**数据阻塞**:CEX 需逐笔盘口/成交流(估队列位置),binance.vision
klines 无此粒度;V3 需链上 pool 事件(swap/mint/burn)+ 历史 IL,需 The Graph/节点。**未实现,需新数据管道**。
诚实先验:Maker 逆向选择常吃掉返佣(追势必被填在错边);V3 IL 在趋势市常 > swap 费(= 做空 gamma,与网格同病)。

### 16.3 期现 / stETH 硬锚对 —— 设计-only(期现=线 C 已做且认证)

**命题**:S2 软对协整真断(Kalman 已证 §12),RV 应做**硬回归约束**对:① 期现基差(现货 vs 永续/季交割);
② stETH/ETH(质押机制保证最终 1:1 赎回)。**关键**:① **期现基差 = 线 C RV-C 已完整实现 + 五轮检验 + 多重检验认证
(BTC/ETH dated cash-and-carry,Sharpe~1.0-1.3,见 `docs/rv-c-plan.md`)** → 本线不重复,直接指线 C。② stETH/ETH:
赎回锚是新锚型;**数据阻塞**:需 Deribit 或链上 stETH/ETH 价 + 赎回队列状态,binance.vision 无 stETH um 历史。
**预注册判据**(若攻下数据):复用线 C `run_basis_carry` 的 equity-normalized + 清算尾门,judge ann net > +2% / ≥4/6 年
/ 尾部生存。诚实先验:stETH 脱锚事件(2022-06 Celsius/3AC)是肥左尾,赎回锚"最终"成立但中途可深贴水。

**§16 结论**:① **S6 截面动量实测证伪**(选择负 alpha、−86% 尾灾、不如持有,S3 仍王);② Maker/LP、stETH 需新数据
管道/新市场,设计已预注册,**实现阻塞在数据**;③ **期现硬锚对其实线 C 已做且认证** → RV 方向的真 edge 在线 C 不在线 D。
**bake-off 用现有数据能榨的 alpha 已榨尽,realizable 最优仍是 S3/S4 趋势族 + §13 组合 + §15 吊灯-S4。**

---

## 15. 非对称退出 / 吊灯止损(2026-06-13)——S4 的 Pareto 胜利,但策略特异

owner 建议:慢进场 + 快出场,吊灯止损(从持仓最高点回撤 `mult×ATR` 即离场,棘轮上移)打 S4 的 2021 高位回吐
(−19.2%)。落 `run_directional(chandelier_mult, chandelier_lookback)`:long-only 跟踪止损 = `HH_since_entry −
mult×ATR`,被 bar.low 击穿则平仓 + **闩锁**(latch),直到底层信号归零/转空再重进(慢进快出);+3 单测 → x4 共 **91 全绿**。

| S4 吊灯 | total | Sharpe | maxDD | 2021 | exits |
|---|---|---|---|---|---|
| off | +88.9% | 0.62 | −27.1% | −19.2% | 0 |
| **4x(headline)** | **+98.4%** | **0.70** | **−23.8%** | **−13.9%** | 8 |
| 2x(保守 max-Sharpe) | +45.6% | **0.77** | **−8.6%** | **+5.7%** | 17 |

**S3 吊灯 = 反而打残**(2x −6.4%、4x +18.3%,全烂于 baseline +115%)。根因:**S3 双均线本身已有好出场(下穿)**,
吊灯叠加 = 双重止损;且 **S3 信号在上涨趋势里恒为「多」(raw=1)→ 闩锁永不释放 → 止损后空仓到趋势结束、错过整段**。
**S4 的 Donchian 信号频繁归零 → 闩锁能释放重进 → 适配。**

**结论(策略特异,不可一刀切)**:
1. **吊灯只配信号会频繁归零的策略**:S4(Donchian)✅ → 4x 三项全面 Pareto 占优 baseline(收益+Sharpe↑、DD↓、
   2021 −19→−14);S3(MA-cross)❌ → 闩锁把它锁在场外。**owner 把目标定在 S4 是对的(S4 的 giveback 是真痛点)。**
2. **复利级副作用:吊灯-S4 降相关 + 抬组合**:S4 在下跌里行为变了 → S3/S4 corr **0.69→0.66** → §13 组合再上一台阶:
   **S1+S3+S4 等权 Sharpe 0.71→0.76(maxDD −16.7%)、全 4 等权 0.83→0.88(maxDD −12.3%)**。
3. 2x 是「最小回撤」变体(maxDD −8.6%、2021 翻正 +5.7%),但截断赢家、总收益腰斩 → 看风险偏好选 4x(进攻)或 2x(防守)。

**X4 当前最优态(§15 后)**:S1 +5.4%/0.30、S2 +45.8%/0.48(脆)、S3 +115.2%/0.67、**S4 +98.4%/0.70**;
**可部署组合 = S1+S3+S4 等权 Sharpe 0.76 / maxDD −16.7%**(全诚实腿,不赌 S2),或纳入 S2 博 **0.88 / −12.3%**。
吊灯-S4 是继波动率平价、组合融合之后第三个真实有效的结构改进。

---

## 14. 参数集群化(2026-06-13)——鲁棒性保险,不是 Sharpe alpha(教科书预期被纠正)

owner 建议:S3/S4 单参数存在「参数悬崖」,拆仓给 N 组周期、信号平均 → 抹平震荡颠簸、提 Sharpe。落
`EnsembleStrategy`(信号平均,共识度即仓位,mean weight∈[-1,1] 直接喂 `run_directional`;+5 单测 → x4 共
**88 全绿**)+ 真跑(日线 2021-26,带波动率平价):

**S3 各单成员 Sharpe 有结构性悬崖(非随机)**:快区 10/50~25/100 = **0.54-0.73(全好)**;慢区 30/120~60/240 =
**0.32-0.45(全差)**。机制:加密趋势里快参数捕获更早、慢参数滞后——慢成员是**结构性更差**,不是「不同视角」。

| 配置 | total | Sharpe | maxDD | 说明 |
|---|---|---|---|---|
| S3 单参(20/100) | +115.2% | 0.67 | −29.4% | baseline |
| S3 宽扇形(含慢成员) | +66.2% | **0.50** | −24.4% | **负优化**:平均进 0.32-0.45 烂成员 |
| S3 窄扇形(快区 4 组) | +110.6% | **0.69** | −27.8% | ≈ 最优单参,去掉单参依赖 |
| 最优单参(25/100,事后) | +132.5% | 0.73 | −27.1% | 事后运气,前向不可依赖 |

**结论(教科书预期被纠正)**:
1. **「集群化提 Sharpe」在单标的趋势上不成立**——教科书假设成员独立;但单资产趋势上成员高度相关,且慢成员
   只是**更差**。盲目全周期 fan = 把已知更差的策略平均进来 = **负优化(0.67→0.50)**。
   **严格确认(2026-06-13)**:① 成员两两相关 **min0.67/mean0.86/max0.98**(教科书需低相关,此处近乎共线 → 没方差
   可分散);② 四条件交叉验证(无摩擦/带费 × 无仓位平价/有仓位平价)**全部**solo>宽扇形(0.63>0.56 / 0.71>0.65 /
   0.61>0.54 / 0.70>0.63)→ 非费拖伪影、非仓位平价混淆、非偶然。**精确表述:不是「教科书错」,是教科书前提
   (成员低相关)在单标的趋势上失效**——这才是真盲区。快扇形 ≈ solo(去单参依赖,不提 Sharpe)。
2. **集群化真实价值 = 鲁棒性保险**:窄扇形(只取 edge 所在的快区)给 ≈ 最优单参的 Sharpe(0.69 vs 0.73),但
   **避免误选 50/200(0.32)的灾难**。代价 = 放弃 ~0.04 Sharpe 换「不赌单参」。**这是 insurance,不是 alpha。**
3. **副作用:同质化抬相关**——集群化让 S3/S4 corr **0.69→0.83**,反削弱 §13 组合分散(all4 集群版 Sharpe 0.70 <
   单参版 0.83)。**单腿去参数依赖 与 组合层分散 有张力。**
4. **必须把扇形限制在 edge 区域(快趋势)**,否则负优化。

**部署建议**:若担心单参运气,用**窄快区扇形(Sharpe 0.69)**作 S3 的鲁棒版;但**别期待它提 Sharpe**,它换的是
「前向不被参数悬崖坑」的保险。组合层(§13)的低相关分散仍是更大的 Sharpe 杠杆,且与集群化的同质化相冲——
**二选一时优先组合层分散。**

---

## 13. 顶层组合融合(2026-06-13)——风险平价 / 等权,验证「Sharpe 推到 0.8」

owner 问:S3/S4 日净值相关性?低相关下顶层风险平价能否把组合 Sharpe 推到 0.8?落纯件 `x4/portfolio.py`
(`correlation` / `combine`(等权 / 逆波动率 risk-parity,无 look-ahead) / `sharpe_of`,+8 单测 → x4 共 **83 全绿**)
+ 真跑(日线 2021-26 优化态净值):

**相关矩阵**:S3/S4=**0.69**(略高于 0.6);**S1、S2 与所有腿近零相关**(S1/S4=0.06、S2/全=~0)= 真分散器。

| 组合 | total | Sharpe | maxDD |
|---|---|---|---|
| S3 单独 | +115.2% | 0.67 | −29.4% |
| S3+S4 等权 | +107.1% | 0.70 | −24.8% |
| S3+S4 风险平价 | +128.6% | 0.72 | −31.9% |
| **全 4 等权** | +68.3% | **0.83** | **−13.3%** |
| 全 4 风险平价 | +93.3% | 0.66 | −24.3% |
| S1+S3+S4 等权(去 S2) | +70.4% | 0.71 | −17.5% |
| S2+S3+S4 等权(去 S1) | +93.2% | 0.82 | −17.4% |

**结论(回答 + 诚实 caveat)**:
1. **0.8 达成,但机制 ≠ owner 预期**:不是 S3+S4 风险平价推到 0.8(它俩 0.69 相关,组合只 0.70-0.72),而是**加入近零
   相关的弱分散器 S1/S2**才把 Sharpe 顶到 **0.83**、maxDD 腰斩到 −13.3%。**分散红利来自低相关,非强强联合。**
2. **等权 > 逆波动率风险平价**(0.83 vs 0.66):naive inverse-vol **过配低波动但低收益的 S1 网格**,反拖累 →
   风险平价不是越纯越好,要按 edge 质量加权。
3. **诚实 caveat:0.83 部分骑 S2**(去 S2 后 S1+S3+S4 = 0.71)。S2 是 Kalman 已证无稳健 edge 的脆腿,其低相关
   可能是运气、实盘未必兑现。**最稳妥的全诚实组合 = S1+S3+S4 等权:Sharpe 0.71、maxDD −17.5%**,仍把单 S3
   的 −29% 回撤腰斩,且不赌脆弱 S2。**推荐这个作为可部署组合,而非追名义最高的 0.83。**

**X4 系统级结论**:顶层等权融合是真实的 free lunch(低相关 → maxDD 腰斩、Sharpe 0.67→0.71~0.83)。realizable
最优 = **S1+S3+S4 等权(0.71/−17.5%)**(全诚实腿)或纳入 S2 博 0.83(承认骑脆腿)。这是 bake-off 的工程终点:
单腿真 edge 是趋势族,组合层用低相关分散把回撤腰斩。

---

## 12. 动态参数优化(2026-06-13)——静态参数遇 regime 切换失效的对症

owner 三条对症建议(静态固宽网格 / 静态 60 日 z / 静态 1x 仓位 → regime 切换失效)。逐条实现(纯件
`x4/indicators.py` ATR + KalmanHedge,+13 单测 → x4 共 **75 全绿**)+ 真跑:

| 优化 | 机制 | 实测(日线 2021-26) | 定性 |
|---|---|---|---|
| **S3/S4 波动率平价仓位** | `run_directional(vol_target,max_leverage)`:仓位=`min(cap, vt/atr%)`,高波动缩仓、低波动加仓(风险暴露恒定) | S3 +108→**+115%**/Sharpe0.58→**0.67**/maxDD−34→**−29%**;S4 +69→**+89%**/0.48→**0.62**/−42→**−27%** | **最佳建议:vt3%/cap2x 严格 Pareto 占优 baseline**(收益↑+Sharpe↑+DD↓);2021 痛点缓解(S3 −26→−15) |
| **S1 ATR 动态网格** | `run_grid(atr_mult)`:半宽=`clamp(atr_mult×atr%,5%,40%)`,高波动拓宽防破网、低波动收窄提周转 | +4.8→**+5.4%**/Sharpe0.23→**0.30**/maxDD−6→−4.5%/换手↓ | 干净小胜,稳健(atr_mult 4/5/6 单调改善) |
| **S1 资金费叠加** | `run_grid(funding)`:long 库存按资金费结算 | funding = **−$79(微拖累)** | **诚实纠正 owner 设想**:long-only 网格 contango 里**付**资金费,「吃 funding」须**短 perp = 线 C 的 delta-neutral carry**,不是 long-only 网格 |
| **S2 Kalman 动态对冲比** | `run_kalman_pair`:`KalmanHedge` 在线更新 β,信号 = 标准化 Kalman 残差(替静态 z) | z 分布 p99=0.44/max=1.21 **几乎不触发**;低阈值多交易 **−16.4%**、高阈值仅噪声 | **principled 但反证无 edge**:Kalman 把结构漂移**吸收进 β**→残差无持续回归→「软对真断」时它诚实「放弃下注」。**S2 静态 z 的 +45.8% = 样本内调参假象,Kalman 暴露之** |

**优化后终表(§12 全生效)**:S1 **+5.4%**/Sharpe0.30、S2 +45.8%(静态,Kalman 证脆)、S3 **+115.2%**/Sharpe**0.67**、
S4 **+88.9%**/Sharpe**0.62**。相关性 S3/S4=0.69、S2 近零相关。

**结论**:① **波动率平价是 owner 三条里最实的胜利**——风险平价标准技、单调改善、Pareto 占优,直接抹平颠簸(maxDD
腰斩)、抬 Sharpe,且 2021 顶部年靠自动缩仓缓解(这是 §10.1 论证「不可雕单年」之后,唯一**有原则地**改善 2021 的
途径——不是雕参数,是按波动率定仓);② ATR 网格小幅干净改善;③ 资金费叠加诚实证明 long-only 网格付费非收费;
④ **Kalman 是诚实的负结果**——它没把 S2 救成正,而是揭穿静态 z 的 +45.8% 是过拟合,软对真无稳健 edge。**realizable
结构 edge 仍是 S3/S4 趋势族(现 Sharpe 0.62-0.67),S1 薄正,S2 名义正但 Kalman 证伪。** 脚本配置即最终优化版。

---

## 11. S5-VEL 分钟级超短趋势 scalper(2026-06-13)——信号真实,散户 taker 不可兑现

owner 新假设:1m bar,**速度(一阶导=ROC)+ 加速度(二阶导=速度变化)**抓加速微趋势,**见好就收**(快 TP + 紧 SL)。
落 `VelocityScalper`(只发进场信号:动量为正且加速且过阈值)+ `run_scalper`(intrabar OHLC 触发 TP/SL,SL 先于
TP 检,每笔满扣往返费;+9 单测 → x4 共 **62 全绿**)。`scripts/research/x4_scalp.py` 在 **2024-03(BTC +16.46%
大牛月 = 动量最有利环境)** 扫 27 配置:

**全 27 配置费后皆负,0/27 正(最优 −37.98%);最干净的诊断 = 无摩擦/maker/taker 三档分解**:

| 配置 | 无摩擦 | maker 1bp | taker+slip | 胜率 | 往返 | fee% |
|---|---|---|---|---|---|---|
| vw20/al10 tp1.0%/sl0.5%(最优) | **+17.06%** | +6.91% | **−37.98%** | 35.8% | 453 | 35.9% |
| vw20/al10 tp0.6%/sl0.3% | +14.22% | −4.10% | −66.45% | 35.1% | 874 | 52.3% |
| vw5/al3 tp0.4%/sl0.2%(快) | **−2.67%** | −35.25% | −94.40% | 33.2% | 2037 | 66.7% |

**终判(三条,诚实写死)**:
1. **信号真实但毛 edge ≈ buy&hold**:慢配置无摩擦 +17.06% ≈ 同窗 buy&hold +16.46% → 不是独立 alpha,是**用多次
   多头脉冲复刻同一段牛市上涨**的趋势暴露代理(快配置 vw5 连无摩擦都 −2.67% = 纯噪声)。
2. **执行成本是唯一约束 + 不可兑现**:maker 1bp 砍半勉强活、**taker+slip −38%**;而**追加速度突破 = 必然吃价差
   (taker),散户拿不到 maker 成交(逆向选择)→ 真实口径 = taker → 不可兑现**。胜率 35% @ 盈亏比 2:1 毛刚平衡,
   14bp/笔往返费碾成深负。**越快越死(往返越多、edge 越少、费拖越重)。**
3. **同一教训第三次独立复现**:线 A-L6(close_auction 反转)、线 B(网格执行皮)、线 D S5(分钟 scalp)——
   **微观信号真实但散户 taker 不可兑现,费/价差吃光**。**加密能拿的钱 = 日线趋势拿住(S3),不是分钟见好就收。**

**「继续优化」的诚实边界**:S1-S4 已到过拟合临界(§10.1 论证雕 2021 即过拟合);S5 是该投入的「新假设」方向,
但实测证伪(retail taker)。**X4 至此:realizable edge 锁定在 S3-CTA long-only 日线趋势 + SMA200 闸;更短/更花
的执行皮(网格/分钟 scalp)一律被费吃穿——bake-off 已答尽,再优化是雕花。** S5 代码定性为可复用「微观信号
不可兑现」证据资产,不删。

### 11.1 三态震荡闸重测(2026-06-16)——震荡因子真砍换手 98%,但同把毛 edge 砍光,FAIL

owner 观察「分钟币常有三态:震荡/上升/下跌,只在上升态做短线」→ 这是 S5 唯一没显式做的一处(震荡因子)。
新增纯件 `EfficiencyRegime`(Kaufman 效率比 = 窗口净位移/路径长度 ∈[0,1];高=趋势、低=震荡,叠净位移符号
→ 三态 +1/0/−1)+ `GatedVelocityScalper`(只在 +1 上升态放行脉冲信号,震荡/下跌空仓);+8 单测 → x4 共
**173 全绿**。runner `scripts/research/x4_scalp_regime.py` 固定 §11 最优慢配置(vw20/al10 tp1.0%/sl0.5%),
只变 regime 闸,在**无摩擦/maker/taker 三档**对照 BTC 2024-03(同 §11 牛月,最有利环境):

| 闸 | 往返 | 胜率 | 无摩擦 | maker 1bp | taker+slip |
|---|---|---|---|---|---|
| bare(裸 S5) | 453 | 35.8% | +17.06%(费0%) | +6.91%(费9%) | **−37.98%**(费36%) |
| er30/0.30 | 229 | 34.5% | +3.74% | −0.91% | −24.78% |
| er30/0.40 | 144 | 36.1% | +5.80% | +2.79% | −13.59% |
| er60/0.40 | 32 | 40.6% | +3.47% | +2.81% | **−1.06%**(费3%) |
| er60/0.50 | 7 | 28.6% | −0.51% | −0.65% | −1.49% |

**终判 = FAIL(三条,诚实写死)**:
1. **震荡闸是真的——往返砍 98%(453→7)、费从 36% 塌到 1%、taker 从 −38% 拉到 −1%(近平)**。owner 的三态直觉
   方向正确:不在震荡里乱打,确实把费血止住。
2. **但闸把毛 edge 砍得比费更狠**。裸 S5 无摩擦 +17.06%(≈ buy&hold +16.46%);收紧到能近平 taker 的 er60/0.40,
   无摩擦只剩 +3.47%——**因为毛 edge 本就是 buy&hold 的趋势暴露代理(§11 终判 1),少打=少暴露=毛收益同比蒸发**。
   把 taker 逼向 0 的唯一方法就是把毛收益也逼向 0 = 等于「几乎不交易」,收敛回 S3 日线趋势拿住。
3. **没有任何配置在 taker 转正;闸甚至让 maker 更差**(最佳 gated maker +2.81% < 裸 maker +6.91%,毛缩得比费多)。
   = 在最有利的牛月都救不活 → 震荡/熊月只会更没上升态可捕。**§11 主结论原样成立:加密能拿的钱是日线趋势拿住
   (S3),不是分钟见好就收;震荡因子能止损不能造 alpha。** caveat:单月 2024-03(与 §11 同口径,favorable-case
   证伪——最强反证)。`EfficiencyRegime`/`GatedVelocityScalper` 定性为可复用「震荡闸真砍换手但同砍 beta」证据资产。

### 11.2 日内多周期趋势(15m/1h 趋势 + 多空 + 见好就收反手)重测(2026-06-16)——周期×方向横比,确认 §9/§10 杀手

owner 细化想法:**读 1h/15m 趋势定方向做多/做空,趋势翻转立刻平仓反手(见好就收),逐币动态阈值结合波动/大盘**。
这恰是 §9/§10 已测过的两根承重柱(1h 周期 = 噪声反复打脸;做空结构性上涨资产被挤)。**纯复用**(S3 `TrendFollow`
交叉本身就翻转反手 = 见好就收;`run_directional` 的 `vol_target` = 逐币 ATR 波动率定仓 = 「逐币动态阈值结合
波动」;`chandelier` = 区间跟踪止损)→ runner `scripts/research/x4_timeframe.py` 把同一趋势策略在
**{日线/1h/15m} × {只做多/多空}** 横比 BTC+ETH(2021-01..2026-05,1x,fast20/slow100,只变周期与方向):

| sym | tf | dir | total | Sharpe | maxDD | trades |
|---|---|---|---|---|---|---|
| BTC | 1d | long-only | **+68.3%** | 0.45 | −43.2% | 59 |
| BTC | 1d | long+short | −9.9% | 0.24 | −60.6% | 955 |
| BTC | 1h | long-only | +69.5% | 0.44 | −64.0% | 1,625 |
| BTC | 1h | long+short | **−62.2%** | −0.01 | −78.5% | 24,396 |
| BTC | 15m | long-only | −48.2% | −0.10 | −73.5% | 6,732 |
| BTC | 15m | long+short | **−97.3%** | −0.79 | −98.5% | 98,133 |
| ETH | 1d | long-only | +14.8% | 0.31 | −72.6% | 66 |
| ETH | 1h | long-only | +65.1% | 0.44 | −61.7% | 1,898 |
| ETH | 15m | long-only | +79.5% | 0.47 | −58.2% | 7,662 |
| ETH | 15m | long+short | −88.5% | −0.10 | −96.2% | 98,560 |

**判决(三条)**:① **做空 = 最大杀手**——每个 long+short 全灾难(−10%~−97%):做空长期上涨资产被挤 + 翻转反手在日内
产 2.4 万~9.8 万笔吃 taker 绞死;owner 的「做多/做空」开关就是把 +68% 变 −62% 的那一下(§10「long-bias 是修复」
原样复现)。② **越日内越差**:15m+多空 = 全表最惨(BTC −97.3%/9.8 万笔),连纯做多 15m 都把 BTC 打到 −48%(假信号
翻倍)。③ **能赚的仍是日线/1h 纯做多(~+68%/Sharpe 0.44-0.47)= S3/S7**;且**日线 59 笔做到 Sharpe 0.45,1h 1625
笔、15m 6732 笔 Sharpe 一点没涨 → 日内化只多交易/多回撤/多脆弱不多 Sharpe**。owner 想法里「新」的部分(日内周期 +
见好就收反手做空)恰是最致命部分;能赚的「纯趋势做多」日线已用 59 笔做完。逐币 vol-parity / 区间止损是 refinement
(§12/§14 已证=鲁棒/风控非 alpha),翻不正负的内核。**realizable 最优仍 = 固定 TOP7 主流币日线纯做多(在跑 pilot)。**

### 11.3 稳健评价因子做空"确认的下跌趋势"——评价因子越好做空腿亏越多(2026-06-16)

owner 进一步澄清:**不是趋势一动就反手,而是先用评价因子高置信判定上升/下降趋势,再顺大方向持有**(上升做多、
下降做空,很少换向)。§11.2 的 20/100 快交叉乱翻(2.4-9.8 万笔)不是这个意思。隔离测剩下的真问题:**用稳健、5 年
只换几次向的分类器(50/200 金叉死叉 = 最真的「确定上升还是下降」),做空腿赚不赚?** runner `x4_regime_short.py`
日线 BTC/ETH/BNB/SOL,vol-parity(逐币动态阈值),把**做空腿净贡献 shortΔ = (long+short) − (long-only)** 单独剥出:

| sym | 分类器 | long-only | long+short | shortΔ |
|---|---|---|---|---|
| BTC | fast 20/100 | +48.6% | +15.0% | −33.5% |
| BTC | **robust 50/200** | +29.4% | −27.5% | **−57.0%** |
| ETH | fast 20/100 | +17.6% | −24.1% | −41.7% |
| ETH | robust 50/200 | +14.2% | −27.4% | −41.6% |
| BNB | fast 20/100 | +81.4% | +60.5% | −20.8% |
| BNB | **robust 50/200** | +33.2% | −22.0% | **−55.2%** |
| SOL | fast 20/100 | +36.2% | −16.8% | −53.0% |
| SOL | robust 50/200 | +48.4% | −0.7% | −49.2% |

**判决:shortΔ 全 4 币全分类器皆负,且越稳健的分类器做空腿亏越多**(BTC −33.5%→−57.0%、BNB −20.8%→−55.2%)。
**机制 = 结构性,非调参缺失**:高置信、少换向的下跌判定(死叉)**必然滞后**——跌势确认时大跌已发生大半,做空恰好
**空在底部区域,被 crypto 标志性 V 型反转/逼空打爆**(2022 熊→2023 反弹:死叉底部做空全吐回)。**评价因子越好=越晚=
越空在底接逼空。** 这正解释 §10「long-bias = 结构修复非侥幸」:加密资产长期上涨+暴跌后剧烈反转,做空「确认的下降
趋势」在数学上就是空底接逼空。**叠加:评价因子用于「选币」也已证伪(§16.1 S6 −86%、§22 动态币池)→ 评价因子无论
用于「判方向做空」还是「选币」,在 crypto 都是负贡献。** realizable 最优仍 = 固定 TOP7 主流币日线纯做多(在跑 pilot)。

### 11.4 整理区间突破 + 多周期同向确认(15m 早抓 + 小时趋势过滤)——假突破吃穿,多周期闸救不了(2026-06-16)

owner 再细化(最站得住的一版):**识别震荡整理区间,价格脱离震荡(突破)时在 15m 早抓那段趋势,只做与小时级趋势同向
的突破(多周期确认过滤假突破)**。精确映射 S4 `MomentumBreakout`:Donchian 突破=脱离前 `lookback` 区间;`regime_sma`=
高周期趋势闸=「符合小时级趋势」;long-only;突破后持有到反向破=做那段趋势。15m 上 1h=4 bar,故 regime_sma∈{16,48,96}≈
{4h,12h,24h} 递增确认强度。runner `x4_breakout_mtf.py`,BTC/ETH/SOL,vol-parity,对日线基线:

| sym | tf | 1h-gate | total | Sharpe | maxDD | trades |
|---|---|---|---|---|---|---|
| BTC | 1d | 日线基线 | **+38.4%** | 0.49 | −25.2% | 591 |
| BTC | 15m | none | −92.7% | −1.08 | −94.2% | 9,212 |
| BTC | 15m | 4h | **−97.2%** | −2.20 | −97.7% | 14,128 |
| BTC | 15m | 24h | −88.1% | −0.99 | −90.8% | 9,370 |
| ETH | 1d | 日线基线 | **+83.2%** | 0.85 | −15.4% | 548 |
| ETH | 15m | none | −75.6% | −0.31 | −87.0% | 11,082 |
| ETH | 15m | 24h | −65.8% | −0.25 | −81.1% | 10,828 |
| SOL | 1d | 日线基线 | **+66.0%** | 0.71 | −33.0% | 652 |
| SOL | 15m | none | −28.4% | 0.27 | −89.3% | 19,304 |
| SOL | 15m | 24h | −14.0% | 0.27 | −86.3% | 17,534 |

**判决(两条)**:① **15m 突破全负(−14%~−97%)vs 日线突破 +38%~+83%**——§9「突破在震荡市被假突破+费绞杀」复现:
15m 上「脱离震荡」绝大多数是假突破(捅出区间又缩回),9k-19k 笔被假突破+费绞杀;**日线突破赚正是因为日线天然滤掉
分钟噪声**。② **多周期确认不救反害**:「4h 确认」档全表最惨(BTC −97.2%/ETH −95.1%/SOL −96.2%),因 regime_sma 在 15m
上自己也抖→加滞后+额外进出 churn,滤掉的假突破不抵它的拖累;只有最强 24h 闸把交易压下点但「早抓」意义已失且照样亏。
**核心:整理区间突破+趋势确认本身对,但只在日线成立(基线行 +38%~+83%/591 笔)= 即 §10.1 winner shape;为「早抓」
下沉 15m=掉进假突破区,多周期确认在 15m 上确认信号自身即噪声救不了。owner「分钟突破一般和小时趋势符合」被证伪:
15m 尺度突破与后续趋势的符合率低到被费吃穿,正因 15m 突破多是假的。** realizable 最优仍=固定 TOP7 主流日线纯做多 pilot。

### 11.5 §11 收口(2026-06-16)——owner 四条细化想法全 FAIL,同根因,该线封板

§11.1–§11.4 把 owner 在 S5 主结论后提的四条「再细化一下也许能活」想法各做成隔离 runner 真跑,四脚本
(`x4_scalp_regime` / `x4_timeframe` / `x4_regime_short` / `x4_breakout_mtf`)**2026-06-16 复跑一遍,数字与上表逐行吻合
(独立复现)**;`EfficiencyRegime`/`GatedVelocityScalper` 两纯件 +8 单测 → **x4 共 173 全绿**。**四条全 FAIL**:

| 子节 | owner 细化想法 | 判决 | 同根因映射 |
|---|---|---|---|
| 11.1 | 加震荡因子,只在上升态做分钟 scalp | 闸真砍换手 98%,但同把毛 edge 砍光,taker 仍负 | 毛 edge = buy&hold 代理,少打=少暴露;闸能止损不能造 alpha |
| 11.2 | 读 1h/15m 趋势做多/做空,翻转见好就收 | long+short 全灾难(−10%~−97%),日内化只多换手不多 Sharpe | 做空结构性上涨被挤 + 日内 = 噪声反复打脸(§9/§10) |
| 11.3 | 稳健评价因子高置信判方向,顺势做空确认下跌 | shortΔ 全币全分类器皆负,越稳健做空越亏 | 死叉滞后→空在底接 V 反转/逼空(§10 long-bias 是结构修复) |
| 11.4 | 15m 早抓整理突破,只取与小时趋势同向 | 15m 突破全负,多周期确认不救反害(4h 闸最惨) | 假突破吃穿,15m 上确认信号自身即噪声(§9 突破被费绞杀) |

**统一根因(四条共一个)**:加密能拿的钱是**日线尺度、纯做多、拿住趋势**(S3/S7,在跑 pilot);任何往
**更短周期 / 加做空 / 更花执行皮**的方向走,都撞同一面墙——**日内是噪声、做空是接逼空、微观信号是 buy&hold
代理且被 taker 费吃穿**。这与 §11 主结论、§16.1(选币负 alpha)、§22(动态币池证伪)、线 A-L6(微观 taker 不可
兑现)第 N 次同型。**§11 该线封板:不再开分钟/日内/做空/突破皮的变体研究**;四 runner + 两纯件定性为可复用
「分钟/日内/做空在 crypto 被结构性证伪」证据资产,不删。realizable 最优锁定 = **固定 TOP7 主流币日线纯做多
(§21 在跑 live pilot)+ 放大本金后叠 §20 carry 压舱石**。

---

## 9. B1/B1-b headline 实测(2026-06-12)——四策略全 5 年可信终表

全窗口 **2021-01..2026-05、1h、47,448 根对齐 bar、各 $100k、taker5bp+slip2bp**(S3/S4 计 BTC 资金费;
S3/S4 已加 B1-b rehedge 死区 0.25、S2 已改仅 pos 变动才交易):

| 策略 | total | CAGR | Sharpe | maxDD | trades | fees$ | 逐年(21/22/23/24/25/26) |
|---|---|---|---|---|---|---|---|
| **S1-GRID** | **−0.1%** | −0.0% | **0.01** | −6.6% | 2,811 | 7,457 | −1.4/−4.3/+2.8/+3.5/−1.4/+1.0 |
| S2-PAIR | −94.5% | −41.5% | −1.44 | −95.6% | 2,148 | 27,192 | −61.6/−37.0/−38.8/−58.9/−6.8/−3.6 |
| S3-CTA | −61.7% | −16.2% | −0.01 | −79.1% | 690 | 39,257 | −29.9/−37.5/−18.5/**+121.2**/−39.8/−19.4 |
| S4-MOM | −98.0% | −51.6% | −0.94 | −98.7% | 907 | 9,811 | −82.3/−58.4/−53.4/−5.7/−45.0/+10.3 |

相关性:S3/S4 = **0.56**(同向趋势族);S2 与其余 **负相关**(−0.06/−0.10/−0.08,分散但自身是亏腿);S1 近独立。

**B1-b 关键发现 —— 我在 B1 的过度归因被自己的实验证伪**:加 rehedge 死区 + pair 仅 pos 变动交易后,
**换手砍 90~97%**(S3 29,079→690、S2 46,194→2,148、S4 29,855→907),**但总收益几乎不动**
(S3 −65.9%→−61.7%、S2 −94.9%→−94.5%、S4 −98.1%→−98.0%,费也只降 <10%)。**结论翻转**:
手续费一直由**真实信号交易**主导,B1 的「每 bar 重平衡税放大亏损」判断**错了**——**四策略的亏损是真的,
不是换手 artifact**。(这正是该跑 B1-b 而非假设的价值:把「重平衡税」从「策略逻辑」里剥出来后,亏损原样还在。)

**诚实主结论(三条,可信终表上写在脸上)**:
1. **S2-PAIR −94.5% = 软对真脆**:BTC-ETH 比价 2021-26 **真趋势不回归**(逐年全负),clean pos-gating 后仍亏
   94% → **不是 churn,是软统计对协整断裂**(线 C 杀手1 在 bake-off 复现)。
2. **S3-CTA −61.7% = 单 regime 扛起**:全靠 **2024 单年 +121%**,其余 5 年被来回打脸;S4-MOM −98% = 突破在
   震荡市被假突破 + 费绞杀。**趋势/动量在加密 = 高盈亏比低胜率、非平稳**——与线 A CTA 全弧同型。
3. **S1-GRID ~平 = 费用中性器非 alpha**:SMA200 gate 挡住单边套牢(maxDD 仅 −6.6%),但扣费净 ~0、Sharpe 0.01
   →(线 B 收口结论在 bake-off 复现)。**四者里唯一没爆的,但也没赚。**

**B1 状态:管道 + 对比报告成型、联网跑通、换手 artifact 已剥离 → 可信终表落定。** 这张表已**实质回答 owner
的赛马问题**:同 $100k 同口径下,**四策略回测无一真盈利**(S1 ~平、其余大亏)。artifact:
`state/x4/research_runs/x4_compare_2021-01_2026-05_1h_*.json`。**下一步可选**:B2 前向 paper(把这四条原样跑实盘
模拟,但回测已显示前三亏、grid ~平,paper 大概率复现);或承认赛马结论已出、止于回测。owner 定夺。

## 10. B3 优化(2026-06-12)——根因分析 + 对症,四策略回测全转正

owner 指令:「起码优化成回测是赚的,分析原因并优化」。**根因(B1-b 终表的亏损为何是真的)**:
① **1h 时间框架** = 噪声反复打脸(趋势/动量经典有效尺度是日线非 1h);② **做空一个长期上涨的资产**
(BTC 2021-26 ~29k→100k+ 净大牛,S3/S4 多空在涨势里被挤);③ **S2 软对**(ETH/BTC 多年真趋势不回归)。

**对症优化(各一处,先写单测,4 新单测 → x4 共 50 全绿)**:
- **时间框架 1h→日线**(脚本 interval 参数,非改码):单此一项 S1 −0.1%→+4.8%、S3 −62%→−0.2%、S4 −98%→−40%。
- **方向 long-bias**(`TrendFollow`/`MomentumBreakout` 加 `allow_short=False`:下行→空仓不做空):避开做空挤压。
- **S4 Turtle 非对称退出**(`exit_lookback` 短于入场通道,长仓更快离场)。
- **S2 `stop_z` 协整断裂止损**(|z|>stop_z 强平 + latch flat,切跑飞的价差;短窗 z 有上界 ~√(n−1) 故只抓突跳)。

**优化后终表(日线、1977 bar、各 $100k、taker5bp+slip2bp;S3/S4 long-only)**:

| 策略 | total | CAGR | Sharpe | maxDD | 逐年(21/22/23/24/25/26) |
|---|---|---|---|---|---|
| S1-GRID | **+4.8%** | +0.9% | 0.23 | −6.0% | −1.5/0/+4.3/−0.6/+2.6/0 |
| S2-PAIR | **+45.8%** | +7.2% | 0.48 | −22.2% | +1.5/+0.8/+9.7/**+44.4**/−6.7/−3.7 |
| S3-CTA | **+59.2%** | +9.0% | 0.42 | −43.8% | −26.8/−14.3/**+55.2/+55.7**/+10.4/−4.9 |
| S4-MOM | **+10.9%** | +1.9% | 0.23 | −58.6% | −11.9/−38.5/**+64.5/+47.5**/−8.3/−8.0 |

相关性:S3/S4=0.63(趋势族);S2 近零相关(分散价值)。**四策略回测全正,目标达成。**

**诚实 caveat(必须随表说,不当 edge 兜售)**:
1. **利润主要来自 2023-24 牛市**:逐年行显示方向策略的钱几乎全在 2023/24,2021/2022 多为负 → **「单 regime
   扛起」签名仍在**。这是「牛市顺势捕获」,非全年候 edge;熊/震荡年靠 long-bias 空仓不亏死,但也不赚。
2. **S2 是 in-sample 调出来的脆弱腿**:120 个参数配置只 17 个为正(~14%),我取了有正邻域的稳健簇(非孤峰
   +107% 那个过拟合极值),但**仍是样本内选择**(线 C 杀手3);+45.8% 里 2024 单年占 +44.4% → **最不可信**。
3. **S3-CTA long-only 日线趋势 = 唯一结构性真 edge**:Sharpe 0.42、+59%,非过拟合(long-bias 顺加密牛、200MA
   级别空仓避熊 = 公认加密 CTA 结果),也是四者最强。**真要信一个,信这个。**
4. S4-MOM 正但颠簸(2022 −38.5%、maxDD −58.6%);S1-GRID 正但薄(费用中性器)。

**结论**:根因清楚(1h+做空+软对)、对症有效(日线+long-bias+止损),**四策略回测全转正**,但诚实读数是
**「long-bias 捕获 2023-24 加密牛」+ S2 样本内调参**,不是发现了全年候 alpha。与线 A/B/C 全弧一致:加密里能
赚的钱主要是「顺着牛市拿住」,择时/配对/网格本身仍非稳健 alpha。脚本配置即优化版,artifact 落 `state/x4/research_runs/`。

### 10.1 第二轮对症 —— SMA200 regime 闸(攻 2021/2022 残余亏损)

B3 后残余亏损集中在 S3/S4 的 **2021 −27%/−12%、2022 −14%/−39%**:long-bias 已避开做空,但中期均线/Donchian
在**熊市反弹**里仍产生**假多头**(bull trap)。对症 = 加**长周期 regime 闸**(`TrendFollow`/`MomentumBreakout`
加 `regime_sma`:只在价格 > 200 日 SMA 时持多,跌破即空仓;+3 单测 → x4 共 **53 全绿**)。

| 策略 | total(前) → (后) | Sharpe | maxDD | 2022 | 2021(残余) |
|---|---|---|---|---|---|
| S3-CTA | +59.2% → **+107.8%** | 0.42→**0.58** | −44%→**−34%** | −14.3%→**0.0%** | −25.9% |
| S4-MOM | +10.9% → **+69.2%** | 0.23→**0.48** | −59%→**−42%** | −38.5%→**0.0%** | −23.5% |

(S1 +4.8% / S2 +45.8% 不变。)**regime 闸是真正的结构修复**:2022 熊市两者精确归 **0%**(全程空仓躲过),
S3/S4 总收益近乎翻倍、Sharpe/maxDD 同步改善。**这是有原则的修复,不是过拟合。**

**残余 2021 −25% 的诚实定性 + 为何就此打住**:① 200MA 需 200 根预热 → 2021 上半年闸裸奔;② 2021 是加密
剧烈**顶部年**(Jul-Nov 冲顶后 Nov-Dec 回吐),趋势策略骑上又吐回。扫 `regime_sma`∈{100,150,200} 发现 **150 反而
更高**(S3 +118%/Sharpe0.60/2021 −15%),**但那是扫一圈挑最大 = 重演 S2 的多重检验过拟合;且 2021 在所有窗下都亏
(−15~−26%)→ 它不是窗口能修的,是结构性顶部年**。**专门修 2021(调窗到 150 / 堆止损钮)= 过拟合到单年形态,
故保留公认 200、就此打住。** = 与线 A/B/C 同一诚实纪律:对症修结构性病根(2022 bear-trap)、不雕一个特定年份。

**X4 最终优化态**:四策略回测全正(S1 +4.8% / S2 +45.8% / S3 +107.8% / S4 +69.2%),结构性 edge = **S3-CTA
long-only 日线趋势 + SMA200 regime 闸**(Sharpe 0.58、2022 完美避险);其余诚实读数不变(利润主来自 23-24 牛、
S2 样本内调参、2021 顶部年是不可过拟合的残余)。脚本配置即最终优化版。

## 8. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-06-16 | 研究(§11.1-11.4) | **owner 加密分钟/日内级择时探索 = 四轮新实测 + 早期共六角度全证伪,门=日线纯做多**(详见 §11.1-11.4)。owner 反复细化「分钟/15m 震荡-趋势短线」,逐版用其确切设定真跑(非引用旧结论):**§11.1 三态震荡闸**(新纯件 `EfficiencyRegime` Kaufman 效率比三态 + `GatedVelocityScalper`,+8 单测→x4 共 **173 全绿**;runner `x4_scalp_regime.py`)= 往返砍 98% 但毛 edge 同步砍光、taker 仍负;**§11.2 周期×方向**(runner `x4_timeframe.py`,纯复用 TrendFollow/run_directional)= 做空全灾难 −62%~−97%、越日内越差、日线 59 笔 Sharpe 0.45 而 1h/15m 多交易不多 Sharpe;**§11.3 稳健评价因子做空**(runner `x4_regime_short.py`,剥离 shortΔ)= 全 4 币做空腿皆负且**评价因子越稳健亏越多**(死叉滞后→空底接逼空,§10 long-bias=结构修复实锤);**§11.4 整理突破+多周期确认**(runner `x4_breakout_mtf.py`,MomentumBreakout 15m+regime_sma 当小时闸)= 15m 突破全负 −14%~−97% vs 日线 +38%~+83%,多周期闸不救反害(4h 档全表最惨)。**元结论:加密散户能拿的钱在日线纯做多趋势(=在跑 pilot),频率越高/越双向/越想早抓越被假突破+噪声+费吃穿;评价因子无论判方向做空(§11.3)还是选币(§16.1/§22)在 crypto 都是负贡献。** 四个 runner + 两纯件留存为「分钟级择时证伪」证据资产,未改任何既有策略模块。 |
| 2026-06-16 | ops(实盘核实) | **核实 §21 实盘 pilot 运行态 = VPS 健康,Mac 旧面已弃用(更正部署面误判)**。owner 问实盘是否在 VPS,核实(06-15 迁移后)**加密 live+paper 全在 VPS(`root@8.220.130.35`,墙外静态 IP 直连币安无代理)**:VPS crontab `*/10 x4_live_cron.sh` + `0 10 x4_paper_cron.sh`,**实测 2026-06-16 18:50 live 跑通**——armed / gate=SHUT(BTC −14.5%<200MA)/ $415 全现金 / 0 单 / 无 ALERT / 每 10 分钟推进 + 发布 `x4_live.json`→看板。**关键更正**:Mac 上 `x4_live_daily.sh`+launchd `com.qount.x4-live` 是**已弃用旧面**(不该加载,本地 `latest.json` 是陈旧副本);**坑=key 的 IP 白名单绑死 VPS 静态 IP→在 Mac 跑(走 Clash 台湾代理出口 `1.168.187.194`)必报 -2015/-2008,是预期保护非 key 坏**。验实盘须 SSH VPS 看 cron/log/latest.json,勿在 Mac 跑。**无需任何修复,pilot 武装待命等 BTC 站上 200MA 开仓。** |
| 2026-06-15 | ops(看板) | **收益看板两项修复(qount.alyaloale.com,只读展示,不碰交易逻辑)**。① **BTC 价格/均线"不更新"**:根因非前端(JS 每 60s no-store 拉取正常),是 `x4_live.py` 面板的 `btc_px` 取**日线收盘** `btc_closes[-1]`(日内不动)+ cron **每日仅一次**(10:30 CST)。修复=`btc_px` 改用**已抓的实时 ticker** `prices["BTCUSDT"]`(BTC 在 universe,零新增请求),**新增 `btc_close` 字段**,`btc_sma200`/`btc_to_sma` 仍走收盘口径 → **闸门/策略语义不变**;VPS crontab `30 10` → `*/10`(每 10 分钟);`orders.jsonl` 加守卫(仅真有调仓事件才追加,`latest.json` 每次刷新)避免提频灌爆审计日志。前端 BTC 卡片标「现价 ●实时 / 200日线·收盘」。实测 btc_px 与币安 ticker 完全一致、ts 实时。**bar 滞后**查清=`load_klines` 走 data.binance.vision 归档(daily dump 发布滞后 ~1 天),对 200d SMA 可忽略,**不改**(改实时 OHLCV 会丢回测可复现性)。② **收益曲线升级为带数轴+悬停的交互图**(纯手写 SVG,**零第三方库**,满足境内无 CDN):Y 轴 ¥/$ 刻度+网格、X 轴日期、鼠标十字准星+高亮点+气泡(日期/净值),窄 book 卡用 compact viewBox 防字号被缩糊。**后端 `x4_paper.py` 加 `_curve_payload()`**:回测净值降采样 ≤150 点,只塞 `*_latest.json`(不进 jsonl),三 track 经 cron 打包进 `x4_paper.json`(实测各 150 点,文件 13.7KB)。**诚实语义区分**:A股=前向真实日净值(cta.json,累积中);加密三本=**回测净值·样本内**(前向才 2 天无历史),UI 明确标注不当前向战绩。改动文件:`scripts/desktop/x4_live.py`、`scripts/research/x4_paper.py`、`web/site/{app.js,style.css}`,均已部署 VPS 验证;x4_live 21 单测 / papersim+trendport 26 单测回归绿。 |
| 2026-06-15 | ops(§21.5 反转) | **重新启用三条 paper forward track,用于收益看板展示**。§21.5(2026-06-14)曾 `launchctl unload com.qount.x4-paper` 停掉 3 腿 / S7 / C×D combo 三条模拟 track(切线去跑 VPS 实盘小仓)。因新建只读收益看板 **qount.alyaloale.com**(仓库 `web/`,线 D/A 跨线展示,Caddy basic_auth + 自动 HTTPS)需展示「前向」收益,owner 定**重新开启前向跑批**:`launchctl load -w ~/Library/LaunchAgents/com.qount.x4-paper.plist`(恢复每日 10:00),kickstart 跑通 4 个 track(forward / forward-s7 / forward-combo / holdings)无 ALERT,数据从 bar 2026-06-12 推进到 **2026-06-13** 并推上 VPS。**实盘小仓(§21)不受影响照常**;源码 / 历史快照本就保留,本次仅恢复调度。**同日再迁移:加密 paper 从 Mac 搬到 VPS 常驻**——owner 定让模拟盘也 7×24(Mac 关机也照跑)。新增 `scripts/desktop/x4_paper_cron.sh`(Linux 版,4 track + 打包发布 `x4_paper.json`,纯 stdlib 直连 binance.vision 无代理);rsync `src/qount` + 搬 `state/x4/paper/`(保住 deploy 锚点 06-13)到 VPS;VPS crontab 加 `0 10 * * *`(paper,live 仍 `30 10`);Mac `com.qount.x4-paper` unload(-w 持久禁用,plist 留作回滚),`push_dashboard.sh` 改为**只推 cta.json**(VPS 自产 x4_paper.json,避免 Mac 冻结数据覆盖)。**自此加密 live+paper 全在 VPS 常开,仅 A股(WSL 上算)依赖 Mac+家里机器在线**。看板数据流:VPS 自产 x4_live/x4_paper,Mac `com.qount.dashboard` 每 5 分钟只中继 A股。详见仓库 `web/README.md`。 |
| 2026-06-13 | v1.9(§20) | **C×D 合成账 kill-test:趋势(线 D S7)+ carry(线 C RV-C)压舱石 = PASS**。命题=两个独立认证 edge 尾部相反(趋势死暴跌、carry 尾在向上逼空)→ 小 carry sleeve 当压舱石(线 A「金/债压舱石」同型)。纯件 `x4/combo.py`(`align_curves` 按 ts 交集+归一化、`combine_fixed` 固定权重再平衡=容量受限 sleeve 的诚实 sizing、`kill_verdict`),复用 `x4.portfolio`/`rv.stats` **未改 C/D 模块**;**+9 单测 → x4 共 126 全绿;rv 53/grid 106 回归绿**。runner `x4_combo.py`(TREND=S7 vt2% 可部署档 + CARRY=RV-C BTC+ETH always-on maker inverse L=3)。**实测(1898 共同日 bar,corr −0.196 负相关)**:全 carry 权重过双门;可部署 **40% carry → Sharpe 0.89→1.18(+0.30)、maxDD −21.4%→−10.2%(尾砍近半)**,代价是总收益 +80%→+62%(换 risk-adjusted)。**跨三线首次把两 edge 拼成更优一本账**。诚实 caveat:两 sleeve 都隐性做多「crypto 活着/contango」宏观因子→短期尾部正交真、多年 regime 层假,**非全天候**。**§20.4 forward 化 + 日更 + 面板**:`x4_paper.py` 加 `forward-combo`(每日重跑两 sleeve→align→combine 60/40,独立 `combo_*.json`)+ `x4_paper_daily.sh` 第三条 track。**combo 日更**:实测 Binance 也发 dated 合约 per-day dump→给 `rv.data` 加 dated 日包 fallback(`dated_day_url` 等,镜像 §18,仅当前月触发),combo 从卡上月末→推进到 bar 2026-06-12,三 track 全日更对齐;**+3 单测 → rv 56/x4 126/grid 106 全绿**。**桌面面板** `scripts/desktop/x4paper.5m.py`(SwiftBar/xbar,线 A 同型但**数据本地无需 ssh**):菜单栏锚 combo,展开三 track 净值/Sharpe/maxDD+持仓态+corr+新鲜度;snapshot 补 `trend_flat`。combo $162,393/+62.4%/1.16/−10.2%,daily 0 ALERT,三 track 转纯 OOS。详见 §20。 |
| 2026-06-13 | v1.7(§19) | **S7-TREND-PORT 多币趋势组合预注册 + 引擎实现(先写单测)**。review owner「聚类选币 + 协方差 top5」→ 否定(§16.1 的 −86% 是**带每币 SMA200 闸**发生的,选币本身负 alpha、naive 等权持有 0.77>选币 0.71、协方差是 error-maximizer、聚类=BTC-beta 噪声、幸存者偏差灌高)。**命题翻转**:不选币,把 §17 唯一过样本外的 S3 趋势**铺到多币上、逆波动率合成**(已证真信号 × 真分散)。落 `sma_regime_mask`(纯件 BTC 大盘闸)+ `run_trend_portfolio`(每币独立 run_directional+TrendFollow → combine inverse_vol → 大盘闸 risk-off overlay),复用 run_directional/TrendFollow/combine 不改。预注册杀线:Sharpe 同时 > 0.70(S3-BTC)且 > 0.77(naive 等权持有)且 maxDD < −25%;幸存者偏差前置。**+12 单测 → x4 共 117 全绿;grid 106 / rv 53 回归绿。** **研究 RUN(`x4_trendport.py`)完成 → 严格杀线 FAIL(尾部):S7 inverse_vol/BTC闸 Sharpe 0.88 同时打过 S3(0.70)和等权持有(0.77)= 命题成立,但 maxDD −30.5% 未达 −25% 且 ≈ 单 BTC −28.9%(分散没砍尾,crypto-beta 一起跌=§19.4 先验兑现)。幸存者偏差强信号:加 ICP 重伤币,等权持有 0.77→0.16 崩、S7 0.88→1.02 反升(趋势闸退出垂死币)→ 等权持有 0.77 本身是幸存者偏差产物。S3-on-BTC 仍 maxDD 之王;S7 留作高 Sharpe 候选。头条 0.88 仍样本内牛市灌高。** 详见 §19.6。 |
| 2026-06-13 | v1.8(§19.7) | **S7 可部署 size 定档 + forward paper 化**。杠杆/vol_target 扫描证 **Sharpe 是杠杆不变量(~0.87 恒定)、−30% 尾是 crypto-beta 结构问题砍不掉**→停 in-sample 优化(再调=雕单窗口)。定档 **vol_target=2.0%**:+80.2%/0.87/maxDD **−21.4%**,过 −25% 门(诚实:过门来自 sizing 非 alpha)。**A forward 化**:`x4_paper.py` 加 `forward-s7`(独立 `s7_snapshots.jsonl`/`s7_latest.json`,走日包 fallback 每日推进)+ `x4_paper_daily.sh` 抽 `run_track` 跑两条 track。端到端验证:S7 推进 bar 2026-06-12,$180,213/+80.2%/0.87/−21.4%、BTC 闸 49% 在场,daily wrapper 无 ALERT。前向锚 §17 的 ~0.70。详见 §19.7。 |
| 2026-06-13 | v1.6(§18 ops) | **日包 fallback 修复:前向真正每日推进**。根因=`grid.data.load_klines` 只读 monthly dump,当月月包未发布 → `skip_missing` 跳过整月 → forward 卡在上月末(实测连跑两次停 2026-05-31,「每日」实为「每月」)。修复:月包缺失回退 per-day dump(`day_url`/`download_day`/`_download_month_daily`,只到今天 UTC、逐日缓存、未发布日 404 跳过,`skip_missing` 语义保留);`x4_paper.py`/launchd 未改,数据层透明生效。**+3 单测 → grid 106 全绿;x4 105/线 C 53 回归绿**。`forward` 现推进到 bar 2026-06-12。caveat:funding 仍仅 monthly(binance 无 funding 日包),当月回退 0,carry 上仓时偏乐观。6 月实测:BTC 在 200MA 下震荡 −15%,三腿全空仓→组合 $172,903 零波动=SMA200 闸防御如期(判据③兑现)。详见 §18。 |
| 2026-06-12 | v0.1 | 立线 D(X4 四策略加密 bake-off),owner 显式放松到「不证伪、回测好看 + 同本金模拟盘横比」。预注册四策略规格(网格 / BTC-ETH 配对 / 双均线-布林趋势 / 价量-OI 动量突破)+ 统一回测/模拟盘公平性口径(同标的/窗口/费用/本金/指标)+ 评比口径(终值/Sharpe/maxDD/相关性矩阵/逐 regime)+ 工程落点(`src/qount/x4/`,复用 grid/rv 纯件不改其模块)。**只计划,实现为下一轮先写单测。** |
| 2026-06-12 | v0.2(B0-a) | **B0 第一增量:统一账本地基,先写单测**。建 `src/qount/x4/`(未改线 B/C 模块):`account.py` `X4Account`(签名持仓版 perp 账本,统一费/滑点/资金费/equity-normalized,**实例独立无串保证金**)、`strategies.py`(`Strategy` 协议 + S3-CTA 双均线 + S4-MOM Donchian+量能突破两个干净方向策略;S1-GRID/S2-PAIR 声明占位待 B0 下一增量)、`backtest.py`(单标的方向驱动 + §4 指标,复用 `rv.stats` Sharpe)。**26 新单测全绿**(account 账本对账/独立性、策略 warmup 无 look-ahead/信号、驱动 equity-normalized 定价/指标);全量 604 绿(唯一失败=既有 `qount.main` 缺 ccxt 环境问题,与本线无关)。**下一步 B0-b:S1-GRID ladder 驱动(复用 `grid.engine`+`grid.trend`)+ S2-PAIR 双腿驱动。** |
| 2026-06-12 | v0.3(B0-b) | **B0 第二增量:补齐 S1-GRID + S2-PAIR 多形态驱动,先写单测**。`strategies.py` 的 GridStrategy/PairStrategy 改为预注册参数 dataclass(逻辑落驱动);`backtest.py` 加 `run_grid`(SMA200 gate:ACTIVE 全网格 / DERISK 只卖 / PAUSED 平仓转现金,复用 `grid.engine.GridLadder`+`grid.trend.trend_states`,买卖撞线检测 + 强平账本对账,`gate_override` 解耦滤网便于测)+ `run_pair`(ETH/BTC 比价 z-score,双 `X4Account` 腿共享 $100k、dollar-neutral、滞回进出场);`X4Result` 加非侵入 `extra` 暴露 grid fill 计数/pair 持仓。**9 新单测全绿**(grid 种格/round-trip 获利/单边只升不买/DERISK 拦买/PAUSED 强平/真 SMA 种格;pair warmup 无 look-ahead/进场方向/dollar-neutral/均值回归获利)。**x4 累计 35 单测全绿;线 B 103 / 线 C 53 回归全绿(未动其模块)**。**四策略全部实现完毕。下一步 B1:`x4/data.py` 拉 binance.vision 真实行情(+OI metrics dump)+ `x4_compare.py` 出回测对比表/相关性矩阵。** |
| 2026-06-12 | v0.4(B1) | **B1 真实数据 + 对比报告,先写单测**。`x4/data.py`:klines 直接复用 `grid.data`(spot/um);新增 **OI metrics dump** 纯件(`parse_metrics_csv`/`load_open_interest`/`align_oi_to_bars`,binance.vision `futures/um/.../metrics`,create_time 兼容 datetime 串与 epoch、无 look-ahead 前向填充,缓存 `state/x4/` 不碰线 B/C glob),给 S4 OI 就绪。**6 新单测全绿**。`scripts/research/x4_compare.py`:四策略同窗口/同费(taker5bp+slip2bp)/同 $100k 跑回测(S1/S3/S4 跑 BTC um perp、S2 跑 BTC-ETH 对;S3/S4 计 BTC 资金费),出 §4 对比表 + **四策略收益相关性矩阵** + 逐年 regime 归因 + JSON artifact。**端到端联网跑通,全 5 年 headline 见 §9。** 当时怀疑 equity-normalized 每 bar 重定仓的换手税污染量级 → 触发 B1-b。 |
| 2026-06-13 | v1.5(§18,B2) | **模拟盘部署:3 腿引擎建成 + 验证 + 前向就绪**。`x4/papersim.py`(部署 S1+S3+S4 等权,**剔除 S2**;每日重跑确定性回测落 equity,保真由构造保证)+ `x4_paper.py`(replay/forward ops,快照落 `state/x4/paper/`);+6 单测 → x4 共 **105 全绿;线 B/C 绿**。回放验证:组合 +72.9%/Sharpe0.76/maxDD−16.7% 精确匹配 §17、sleeve bit-for-bit 匹配 §15 → 引擎过。**当前三腿全空仓(2026-05 BTC 在 SMA200 下,闸防御吃现金)**。前向:`forward` 每日 cron 累积快照。预注册判据=前向 Sharpe~0.4-0.7/maxDD~−17%/熊市闸防御不深亏。详见 §18。 |
| 2026-06-13 | v1.4(§17) | **样本外 / Walk-forward 验证(里程碑)**。`x4_walkforward.py`(切片测量避 warmup,因果无 look-ahead)。A:全部 test(24-26)≫train(21-23),edge 集中近期牛(train Sharpe 仅 0.33-0.40 vs 头条 0.67-0.88)。B:**S3 walk-forward 选参→TEST Sharpe 0.70=通过**(真 edge);**S2 选参→TEST −0.75=过拟合 FAIL**(window=60 是事后幻觉,§13「S2 脆」从怀疑变证明)。C:S3/S4 泛化 ETH Sharpe 0.53-0.55=非单标的拟合。**结论:趋势族真且可泛化,S2 剔除,前向预期重校到 ~0.4-0.7 而非 0.88**。X4 从「实验」转「前向可信」。详见 §17。 |
| 2026-06-13 | v1.3(§16) | **剩余路线图:新数据/新市场。S6 截面动量实现实测 + 两项设计-only**。`cross_sectional_rank`(波动率调整动量+各币 SMA200 闸)+`run_cross_sectional`(top-K 轮动+换手计费,+8 单测→x4 共 **99 全绿**);`x4_xmom.py` 14 标的扫 18 配置。**S6 证伪**:最优 Sharpe 0.71 既不过 S3(0.70/maxDD−29% vs XMOM−86%)也不过 naive 等权持有(0.77)→ 截面选择=负 alpha+清盘级尾灾(线C广度教训复现);山寨轮动 RETURN 真实(等权+393%)但 RISK 不可投。Maker/LP + stETH 硬锚对=设计-only(数据阻塞:盘口队列/链上/Deribit);**期现硬锚对=线C已做且认证**。**realizable 最优仍 S3/S4 趋势族**。详见 §16。 |
| 2026-06-13 | v1.2(§15) | **非对称退出 / 吊灯止损(owner 建议),先写单测**。`run_directional(chandelier_mult)`:long-only 跟踪止损 HH−mult×ATR + 闩锁(慢进快出);+3 单测 → x4 共 **91 全绿;线 B/C 绿**。**策略特异**:S4(Donchian 信号频繁归零)**4x 三项 Pareto 占优**(+88.9→+98.4%/Sharpe0.62→0.70/maxDD−27→−24%/2021 −19→−14;2x 更激进 Sharpe0.77/maxDD−8.6%/2021 翻正但总收益腰斩);**S3(MA-cross 信号恒「多」)被闩锁锁死打残→不加**。副作用:降 S3/S4 corr 0.69→0.66 → 组合 S1+S3+S4 0.71→0.76、all4 0.83→**0.88**。详见 §15。 |
| 2026-06-13 | v1.1(§14) | **参数集群化(owner 建议),先写单测**。`EnsembleStrategy`(信号平均=共识仓位,+5 单测 → x4 共 **88 全绿**)。实测**纠正教科书预期**:S3 单成员 Sharpe 有结构悬崖(快区 0.54-0.73、慢区 0.32-0.45);**宽扇形(含慢成员)负优化 0.67→0.50**(平均进更差策略);**窄快区扇形 0.69 ≈ 最优单参但去单参依赖 = 鲁棒性保险非 alpha**;副作用同质化抬 S3/S4 corr 0.69→0.83 反削组合分散。**单腿去参依赖 vs 组合层分散 有张力,二选一优先组合分散**。详见 §14。 |
| 2026-06-13 | v1.0(§13) | **顶层组合融合(owner 问 S3/S4 相关 + 风险平价→0.8),先写单测**。纯件 `x4/portfolio.py`(correlation/combine 等权+逆波动率/sharpe_of,+8 单测 → x4 共 **83 全绿**)。相关:S3/S4=0.69、S1/S2 与全近零。实测:**全4等权 Sharpe 0.83/maxDD−13.3%(达成 0.8)**,但机制=低相关弱分散器(S1/S2)而非 S3+S4 强强联合(那只 0.70-0.72);等权>逆波动率(后者过配弱低波 S1)。**诚实 caveat:0.83 部分骑脆腿 S2(去 S2=0.71)→推荐全诚实组合 S1+S3+S4 等权 0.71/−17.5% 作可部署版**。详见 §13。 |
| 2026-06-13 | v0.9(§12) | **动态参数优化(owner 三条对症),先写单测**。纯件 `x4/indicators.py`(ATR + KalmanHedge);`run_directional` 加波动率平价仓位(`vol_target/max_leverage`)、`run_grid` 加 ATR 动态半宽(`atr_mult`)+ 资金费(`funding`)、新 `run_kalman_pair`(`KalmanPair` 配置)。**+13 单测 → x4 共 75 全绿;线 B/C 回归绿**。实测:**①波动率平价 = 最实胜利**(S3 +108→+115%/Sharpe0.58→0.67/maxDD−34→−29%、S4 +69→+89%/0.48→0.62/−42→−27%,vt3%/cap2x 严格 Pareto 占优,2021 缓解);②ATR 网格小胜(+4.8→+5.4%/Sharpe0.30);③资金费叠加诚实证 long-only 网格**付**费(「吃 funding」须短 perp=线C);④**Kalman 诚实负结果**:β 吸收结构漂移→残差无回归 edge→揭穿 S2 静态 z 的 +45.8% 是样本内过拟合。详见 §12。 |
| 2026-06-13 | v0.8(S5) | **S5-VEL 分钟级超短趋势 scalper(owner 新假设),先写单测**。速度(一阶导)+加速度(二阶导)抓加速微趋势、见好就收(TP/SL)。`VelocityScalper`+`run_scalper`(intrabar TP/SL,满扣往返费,+9 单测→x4 共 **62 全绿**);`x4_scalp.py` 在 2024-03 大牛月(+16.46%,动量最优环境)扫 27 配置。**0/27 费后正(最优 −38%)**。无摩擦/maker/taker 分解证:**信号真实但①毛 edge≈buy&hold(非独立 alpha,是趋势暴露代理)②死在执行成本(taker −38%,maker 1bp 砍半,散户追突破=吃价差不可兑现)③越快越死**。同一教训第三次复现(线A-L6/线B/线D-S5):微观信号真实但散户 taker 不可兑现。**realizable edge 锁定 S3 日线趋势;bake-off 答尽,再优化是雕花。** 详见 §11。 |
| 2026-06-12 | v0.7(B3.1) | **第二轮对症 = SMA200 regime 闸,先写单测**。残余亏损在 S3/S4 的 2021/2022(long-bias 后熊市反弹仍假多头)。`TrendFollow`/`MomentumBreakout` 加 `regime_sma`(只在 >200日SMA 持多,跌破空仓;修 deque 加长后 slow_ma 切片 bug);**3 新单测 → x4 共 53 全绿;线 B/C 回归绿**。结果:**S3 +59%→+107.8%(Sharpe0.58)、S4 +11%→+69.2%(Sharpe0.48),2022 熊市两者精确归 0%、maxDD 同步改善**。残余 2021 −25%:200MA 预热盲区 + 剧烈顶部年;扫 regime_sma 见 150 更高(+118%)但=多重检验过拟合且 2021 各窗皆亏→**保留公认 200、就此打住不雕单年**。详见 §10.1。 |
| 2026-06-12 | v0.6(B3) | **B3 优化:四策略回测全转正,先写单测**。根因=1h 噪声 whipsaw + 做空 BTC 长期涨势 + S2 软对不回归。对症:① 时间框架 1h→**日线**(脚本 interval,非改码);② 方向 **long-bias**(`TrendFollow`/`MomentumBreakout` 加 `allow_short=False`);③ S4 **Turtle 非对称退出**(`exit_lookback`);④ S2 **`stop_z` 协整断裂止损 + latch**。**4 新单测 → x4 共 50 全绿;线 B/C 回归绿**。终表(日线):S1 +4.8%/S2 +45.8%/S3 +59.2%(Sharpe0.42)/S4 +10.9%,**全正**。诚实 caveat:利润主要来自 2023-24 牛(单 regime 签名仍在)、S2 是 120 配置里 17 正的样本内选择(取稳健簇非孤峰 +107%,仍最不可信)、S3 long-only 日线趋势是唯一结构真 edge。结论:四正=「long-bias 捕获加密牛」+ S2 调参,非全年候 alpha,与线 A/B/C 全弧一致。详见 §10。 |
| 2026-06-12 | v0.5(B1-b) | **B1-b 剥离换手 artifact,先写单测**。`backtest.py` 加 `_should_rebalance` 死区(`run_directional` 新增 `rebalance_band`,默认 0、compare 用 0.25:仅开/平/翻转或漂移超带才交易,去掉手续费微漂 churn)+ `run_pair` 改**仅 pos 变动才交易**(held spread 不再每 bar 重定仓,标准 stat-arb 实现);compare 给 S3/S4 传 band 0.25。**4 新单测全绿**(directional 死区压微漂/翻转仍交易;pair held 不重 churn/退出回平),x4 累计 **45 全绿;线 B 103/线 C 53 回归绿**。**重跑 headline:换手砍 90~97%(S3 29079→690、S2 46194→2148、S4 29855→907)但总收益几乎不动(<5pp)、费降 <10% → B1 的「换手放大亏损」判断被自己实验证伪:亏损是真的,费由真实信号交易主导。** §9 改为可信终表:四策略回测无一真盈利(S1 ~平、S2 −94.5% 软对脆、S3 −61.7% 单 regime 扛、S4 −98% 突破绞杀)。**赛马问题实质已答。下一步可选 B2 前向 paper 或止于回测,owner 定。** |
