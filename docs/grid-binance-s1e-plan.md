# GRID-B S1e 实施计划 v0.5:三态混合构型的工程落地与预注册判生死

> **状态**：archived/falsified（GRID-B 已收口 2026-06-11，原地保留）｜索引见 [archive/README.md](archive/README.md)｜当前事实以 [current.md](current.md) 为准。

状态:实施计划 v0.5 · 创建 2026-06-11 · 代号 **GRID-B**
上游:[grid-binance-next.md](grid-binance-next.md)(v0.3 推进方向 + D0/D1/D2 实测)·
[grid-binance-optim2.md](grid-binance-optim2.md)(v0.4 条件化优化,Track A 挂本文件宿主)

> 属线 B,隔离边界见 [grid-binance-plan.md](grid-binance-plan.md) 开头声明;变更只写回本线文档,
> 不写 `current.md` / `update-log.md`。

---

## 0. 这份文件补的是什么洞

D2 决策树(v0.3 §8)落在 **S1e**:`H1 活(chop Δ +24.09%) → 进 S1e 三态混合构型`。
但到今天为止,S1e 只有两处 design-level 描述——v0.3 §3 的一段构型定义 + v0.4 §4 工程落点表的
一行(`trend.py 加三态 regime;backtest.py 加 hybrid 模式`)。**没有 code-level 的实施步骤**,
也没把"过门后 Track A(O-A3/A1/A2)解冻"的工程钩子钉死。

本文件补这个洞:把 S1e 从"设计"推进到**可执行的一轮改动**(精确到函数/字段/单测),并把
预注册判据从 v0.3 §3 的文字**操作化成可计算量**(这是把"尚未跑"的判据精确化,**不是**改判
任何已跑结果——S1e 还没实现)。

**纪律边界**:本文件**只写计划,不实现**。实现是下一轮独立的"一轮只改一处先写单测"
(§3 是那一轮要改的全部,§5 是先写的测)。

---

## 1. 出发点的诚实复述:H1 的信号有多脆

H1 活的全部依据 = S1d chop 桶 Δ **+24.09%/yr**(v0.3 §8)。但文档自己标注的**三重脆弱性**必须
带进 S1e 的设计动机,免得把一个脆信号工程化成自我感动:

1. **样本薄**:chop 桶只有 13 个**非连续**月、跨 6 年;`annualized_delta` 用 `^(12/13)` 几何折算,
   少数大月(2024-04 +14.5% / 2025-02 +17.0% / 2023-06 −11.1%)主导结果。
2. **后视镜标注**:chop 用「以该月为中心的 91 天窗口实现收益+波动」事后贴标,是**对网格最慷慨的上界**。
3. **测的不是同一个网格**:S1d 的 grid 是 **S1 未播种**网格;S1e 的 range 态网格是**播种**网格(§2)。
   播种网格起手就接近持有,它相对 hold 的 Δ **量级更小** → S1d 的 +24% 很可能**高估** S1e 的 range edge。

**先验(v0.3 §3 已写,这里强化)**:S1e = 事前识别 + 付切换税 + 播种(更贴近 hold)的现实版,
通常只能拿到后视镜上界的一**小**部分。**S1e 大概率死。** 它的设计目标不是"让它过",是
**用最诚实的事前构型给 H1 一个干净的生死判定**——这一周买的是"死得明白"(v0.3 §7)。
任何"调参/叠优化调到过为止"都是 garden of forking paths(v0.4 §0.1 已禁)。

---

## 2. 结构洞察:S1e 与 hold 的差异**全部**发生在 range 态(锐化全案)

这是读现有 `backtest.py` 后得到的、能简化整个 kill-test 的关键事实:

```text
hold-above-200MA 基线:  ACTIVE(close>SMA200 确认) 时持有,否则空仓。
                        ACTIVE = uptrend ∪ range(都在均线上)。
S1e 三态:                uptrend → 持有 ;  range → 播种网格 ;  below → 空仓。
```

逐态对照:

| regime | hold 基线 | S1e | 两者是否相同 |
|---|---|---|---|
| uptrend | 持有 | 持有 | **相同** |
| range | 持有 | 播种网格 | **唯一不同点** |
| below | 空仓 | 空仓 | **相同** |

> **推论:`Δ(s1e − hold)` 的全部增益/亏损都在 range 态产生**(只差边界切换的时点税)。
> 于是 S1e 的生死判定收敛成一句话:**「在事前识别的 range 段里,一个无 look-ahead 的播种网格,
> 扣切换税后,能不能赢『就一直持有』?」** ——这正是 S1d 后视镜 chop Δ 的**事前诚实版**。

这条洞察直接决定了 §4 的判据账本:**`range_harvest`(range 态网格 booked net) vs `switch_tax`
(切换+重布的 taker 费)** 是唯一要算清的两个量,其余都和 hold 抵消。

---

## 3. 工程落点(精确到函数/字段——下一轮要改的全部)

复用现有纯件,**不新建模块**:`GridLadder` / `build_grid`(engine.py)、`daily_states_by_date`
/ `_max_drawdown` / `_year_of`(backtest.py)、`sma` / `trend_states`(trend.py)。

### 3.1 `src/qount/grid/trend.py` — 新增三态 regime 函数

```python
class HybridRegime(enum.Enum):
    UPTREND = "UPTREND"   # ACTIVE 且 r90 ≥ +r90_threshold → 满仓持有
    RANGE   = "RANGE"     # ACTIVE 且 r90 < +r90_threshold → 播种网格
    BELOW   = "BELOW"     # 非 ACTIVE(DERISK/PAUSED/warm-up) → 空仓

def hybrid_regimes(closes, *, window=200, confirm_bars=2,
                   r90_window=90, r90_threshold=0.15) -> list[HybridRegime]: ...
```

实现要点(全部沿用现有件,只做组合):

- **below 门最高**:先用现有 `trend_states()` 拿 `TrendState`;凡非 `ACTIVE`(DERISK/PAUSED/warm-up)
  一律映射 `BELOW`。SMA200 是逃生门,r90 只在"已站上均线确认"内部细分。
- **ACTIVE 内部按 r90 细分**:`r90 = close / close[i-r90_window] − 1`(日线,事前可得,无 look-ahead)。
  - `r90 ≥ +0.15` → `UPTREND`
  - `r90 < +0.15`(含负值)→ `RANGE`
- **边界裁定(写明,防后续含糊)**:`ACTIVE 且 r90 ≤ −0.15`(站上均线但 90 日仍深跌——刚强反弹但
  动量未起)**归 RANGE 不归 BELOW**。理由:方向尾部风险已由 below(SMA)门控住,r90 负只说明"反弹不强",
  此时 play 网格无方向押注,符合"网格只填趋势空窗"的初衷。
- **warm-up**(SMA 未成形 或 不足 `r90_window` 日)→ `BELOW`(保守,同 trend.py 现有"无信息则空仓"哲学)。
- **基线 S1e 用对称阈值**(进出 range 同一 `±0.15`),**刻意不带滞回**——把"切换被打脸"的损失
  暴露出来,好让过门后的 O-A3(不对称滞回)有可证的改进空间。滞回是 O-A3 的活,不在基线。

### 3.2 `src/qount/grid/backtest.py` — 新增 `run_s1e()`

签名对齐 `run_s1`(同 `step/maker_fee/taker_fee/sma_window/confirm_bars`),增 `r90_window/r90_threshold/
z/range_horizon_days` 等 range 布网参数。主循环按 hourly bar 查当日 `HybridRegime`,三态驱动:

```text
UPTREND:  持有满仓。首次从非持有进入 → 按当前 close taker 买入(同 run_s1 hold 腿的计费),
          inventory 标记到 close。
RANGE:    跑播种网格(见下 O-A0 布网 + 播种规则);网格在 range 内 bar-replay,
          沿用 run_s1 的 crossing 成交语义(买:last_ref>P_k 且 low≤P_k;卖:high≥P_{k+1};
          无同 bar 往返)。所有成交按 maker 计费(墙压测是后续 S2)。
BELOW:    清仓空仓。持仓全部 taker 卖出 + 撤网。
```

**range 布网(O-A0 规格,无 look-ahead)** —— 每次**进入** range 态当日按下式新建一个 `GridLadder`
(经 `build_grid`),range 期间 harvest 累计;离开 range 时撤掉:

```text
center = 进入 range 态当日收盘价
σ_d    = 过去 30 日日收益率标准差(事前)
[L,U]  = center · exp(∓ z·σ_d·√H)      z=2, H=range_horizon_days=90
step   = 1%(基线;O-A1 再动)
range 内价格越界但 regime 仍 range → 整体重布(计费、计次,并入 switch_tax 的隐性税)
```

**播种规则(本案最敏感的一个建模选择,显式写死)**:进入 range 当日,把网格**播种成约半仓**——
所有买线 `P_k ≤ center` 的 cell 视为"已在 `P_k` 买入并持有"(`apply_buy_fill`),上方挂卖梯、
下方留买梯。从"进 range 前的实际持仓"调整到这个播种持仓的差额,按 **taker** 计费,计入 `switch_tax`。

> 为什么播种成半仓而非沿用进场实际持仓:**路径无关性**。range 可能从 uptrend(满仓)进、也可能从
> below 反弹(空仓)进;若直接沿用进场持仓,range 行为会被进场路径污染,kill-test 不干净。固定播种成
> 半仓 → range 段的 Δ vs hold 只反映"网格 vs 持有",不掺路径。**这也是 §1 第 3 条"播种网格更贴近
> hold"的来源**:半仓起手,Δ 量级天然小于 S1d 的未播种 grid。

**切换计费**:每次 regime 跳变产生的建仓/清仓/建网/撤网/播种差额,按实际单数 **taker** 计费,
`switch_count += 1`、`switch_tax += 费`。range 内重布也计入 `switch_tax`(隐性税)。

**新增 dataclass `S1eResult`**(复用 `S1Result` 字段骨架 + 新字段):

```text
继承骨架:  grid_total_return / hold_total_return / grid_minus_hold / per_year /
           grid_curve / hold_curve / grid_max_drawdown / hold_max_drawdown
新增:      switch_count       切换总次数
           switch_tax         切换+重布的 taker 费总额(capital 单位)
           range_harvest      range 态 booked grid net(只累计 range,不含 uptrend inventory)
           whipsaw_cost       切换后 N 日内反向重切的频率 × 成本(诊断读数)
           regime_fractions   {uptrend, range, below} 时间占比(健全性 + O-B5 同型读数)
verdict:   "s1e {±%} vs hold {±%} (Δ {±%}); won {k}/6y; range_harvest {±%} /
            switch_tax {%} (tax/harvest {%}); switches {n}"
```

> `hold` 腿与 `run_s1` **逐字相同**(ACTIVE 持有、taker on switch),保证 apples-to-apples;
> 实现上抽出一个共享 `_hold_above_ma()` helper 供 `run_s1`/`run_s1e` 复用,避免两份 hold 漂移。

### 3.3 `scripts/research/grid_b_s1e.py` — 新增(镜像 `grid_b_s1d.py`)

```text
load BTCUSDT 2021-01..2026-05(小时线+日线,复用 grid/data.py) → run_s1e →
artifact: state/grid_b/research_runs/s1e_BTCUSDT_2021-01_2026-05_step0.01_*.json →
打印 verdict + §4 判据三项逐项对账(Δ符号 / 赢年数 / tax<harvest/3)。
```

---

## 4. 预注册判生死(跑前写死;把 v0.3 §3 操作化)

v0.3 §3 的判据原文:`Δ>0 且 ≥3/6 年正 且 切换税(whipsaw 成本) < chop 桶 harvest 的 1/3`。
其中"chop 桶 harvest"在 S1d 里不是直接报数(S1d 报的是 Δ,不是 harvest)。本文件把它**操作化**成
S1e 内部可直接计算的量(§3.2 已定义),保留原意"切换成本不许吃掉网格在 range 真正收割的 1/3 以上":

```text
基线:  hold-above-200MA(与 run_s1 逐字相同),全窗口 BTCUSDT 2021-01..2026-05。
判据(三项全过才算过):
  (1) Δ(s1e − hold) > 0
  (2) ≥ 3/6 年 grid_minus_hold > 0(不许单年扛)
  (3) switch_tax < range_harvest / 3   (切换+重布成本 < range 收割的 1/3)

过:    进 §6 Track A 优化序列(O-A3 → O-A1 → O-A2)→ 全链再过 S3(DSR/PBO + 参数敏感度)
       → S2(maker 墙)→ S4 paper(跑满 ≥1 次完整 range↔uptrend 切换)。
不过:  H1 关闭。混合构型是 H1 的最优操作化,它败 = 时间维度主场不存在 → §7 收口。
中间带救援(v0.4 §0.2 唯一条款):Δ>0 但 (2) 或 (3) 不满 → **仅用 O-A3 切换税工程重测一次**
       (切换税是纯成本工程,降它不是挖信号);其余 O-A1/O-A2 是信号侧旋钮,不享救援。一次,不过即收口。
```

**先验提醒(写进 verdict 输出旁)**:§1 三重脆弱 + §3.2 半仓播种 → 心理预期按"确认性证伪"设;
若结果勉强过 (1) 而 (2)/(3) 擦边,**不要**急着进救援,先回看是不是少数大月在抬轿(同 S1d 局限)。

---

## 5. 单测清单(先写测,镜像现有 37+7 风格)

`tests/test_grid_trend.py` 增(构造 closes 让 r90 跨 ±0.15):

```text
□ hybrid_regimes 三态分类:上穿 r90≥15% → UPTREND;均线上但 r90 小 → RANGE;均线下 → BELOW
□ below 门优先:站上均线但 confirm 未过(DERISK/PAUSED)→ BELOW(不因 r90 高就 UPTREND)
□ 边界裁定:ACTIVE 且 r90 ≤ −15% → RANGE(不归 BELOW)
□ warm-up(不足 200 日 SMA 或 90 日 r90)→ BELOW
```

`tests/test_grid_backtest.py` 增:

```text
□ run_s1e 纯 uptrend 序列 ≈ hold(退化对账:Δ≈0,switch 极少)
□ run_s1e 纯 below 序列 = 0(全程空仓,无 harvest 无税)
□ 切换计费:构造 N 次 regime 跳变 → switch_count==N 且 switch_tax ≈ N×taker 量级
□ range_harvest 只累计 range 态 booked net(uptrend 的 inventory mark 不计入)
□ O-A0 布网无 look-ahead:center==进入日收盘,[L,U] 只用过去 30 日 σ(注入未来价不改区间)
□ _hold_above_ma helper:run_s1 与 run_s1e 的 hold 腿逐 bar 相等(防两份 hold 漂移)
```

预期 grid 模块单测 **44 → ~52**,全绿才进 §3.3 跑 artifact。

---

## 6. 过门后:Track A 优化的工程钩子(提前钉死接口,保证一键退化)

把 v0.4 Track A 的 O-A3/A1/A2 落到具体参数与开关。**S1e 基线不过则本节全冻结**(v0.4 §0)。
顺序、kill-test、回退见 v0.4 §2 / §5;这里只补"改哪个参数、退化开关是什么":

```text
顺序 优化          改动点(在 §3 已落地的件上加开关)                          退化(=基线)
──────────────────────────────────────────────────────────────────────────────────────
 1  O-A3 切换税    trend.py:hybrid_regimes 加 enter_thr/exit_thr(进 0.15/出 0.20 不对称滞回);
                  backtest.py:加 maker 分批过渡(切换单先挂 maker,24h 残量 taker)+
                              渐进建格(进 range 分 3 日各建 1/3 网格)开关             enter==exit 且全 taker
 2  O-A1 ATR 间距  backtest.py:range 布网 step 改 clamp(k_atr·ATR14/price,0.5%,3%),
                              k_atr 扫 [0.5,1.5],重布触发 hysteresis ±20%               k_atr 旁路→固定 1%
 3  O-A2 高斯      build_grid 加 allocation_mode=gaussian:w_k∝exp(−(lnP_k−ln center)²/2σ²),
                              σ_alloc 使内 1/3 格≈70% 资金                              σ_alloc→∞→等额
```

每个优化:独立单测 + 独立 artifact + 对照 = 已合入的上一版 + 显式退化开关(同 v0.2 §1 哲学)。
**唯一救援**:S1e 中间带仅 O-A3 重测一次(§4)。

---

## 7. 收口预案(若 S1e 不过——预期主路径)

S1e 是 H1 的最优操作化,它败 = 时间维度主场不存在 → H1 死。此时 **H1、H2 双死**,按 v0.3 §5 收口
(不拖、不留"再调参"尾巴):

1. **结论定稿**(写入本文件 §9 + grid-binance-next.md changelog):网格在加密资产上,无论标的维度
   (S1c,含比价对)还是时间维度(S1e,事前识别 range 混合构型),扣费后均无法对"站上 200MA 就持有"
   产生正增量。harvest 层真实存在(~3.4%/yr)但量级即天花板。= 线 A L6 教训的加密**完全体**。
2. **资产清点**(代码不删,定性可复用):`grid/data.py`(可复现数据层)、`grid/engine.py` GridLadder
   (扣费配对账本)、`grid/trend.py` 四态机 + 三态机、`grid/backtest.py` bar-replay + regime_slices +
   run_s1e、~52 单测、S1/S1d/S1c/S1e artifact 证伪链。
3. **线 B 状态改"已收口"**:CLAUDE.md 文档地图 + 记忆更新;不开新网格变体;日后重启须带**新假设**
   (新结构/新本位/新市场),不是旧假设换参数。
4. **④ 生息叠加随之失效**(无 live 网格→无闲置 U,Tier-1 无附着点;Tier-2 本就不碰)。

---

## 8. 不做清单(继承 v0.3 §6 / v0.4 §6,本轮强调)

- ❌ 把 S1e 的播种规则当旋钮调到过(半仓播种是路径无关性的设计选择,不是待优化参数);
- ❌ 在 S1e 基线未过时叠 O-A1/O-A2(forking paths,v0.4 §0.1);
- ❌ 用 look-ahead 区间布 range 网格(S1 的全窗口 min/max 是 S1 的慷慨上界,S1e 是要过 S3 的现实构型,O-A0 强制事前);
- ❌ 为"让 S1e 过"而摘 SMA200 below 门(裸 long 网格已知死法);
- ❌(继承)②追踪、Tier-2、死基线上的形状优化、多标的并行。

---

## 9. 实测结果

BTCUSDT 2021-01..2026-05,hourly,step=1%,confirm_bars=2,其余取 §3.2 默认值
(z=2.0/range_horizon_days=90/sigma_window=30/r90_window=90/r90_threshold=0.15)。
artifact: `state/grid_b/research_runs/s1e_BTCUSDT_2021-01_2026-05_step0.01_20260611T071226Z.json`。

| | 总收益 | maxDD | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| S1e 混合 | -93.7% | -97.2% | -54.52% | +0.00% | -40.33% | -2.06% | -76.61% | +0.00% |
| 持有(站上200MA) | +564.6% | -40.2% | +45.35% | +0.00% | +103.95% | +106.12% | +7.43% | +0.00% |
| Δ s1e−hold | **-658.3%** | | -99.88% | +0.00% | -144.28% | -108.17% | -84.04% | +0.00% |

regime 分布:uptrend 37.1% / range 17.9% / below 45.0%(below 期间持仓为零,与 hold 的空仓腿一致)。
switch_count=73,switch_tax=3.13%,range_harvest=**-247.2%**(range 态半仓播种网格的真实已实现盈亏,
扣除播种 phantom 后为大幅净亏),whipsaw_cost(诊断)=+0.31%。

判据对账:(1) Δ>0 [✗ -658.3%] · (2) ≥3/6 年正 [✗ 0/6] ·
(3) switch_tax < range_harvest/3 [✗ 3.13% vs -247.2%/3,harvest 本身为负] → **结论:FAIL,三项全不过,且远非擦边**

**实现期间发现并修复一个建模 bug**(播种 phantom):`_seed_range_ladder` 用 `apply_buy_fill` 播种半仓时,
cost basis 记为各格自己的网格价 `P_k`(均 ≤ center),但播种这件事经济上发生在"现在"、按 `center` 计价,
导致 `ladder.equity()` 在播种瞬间凭空多出 `Σ qty_k*(center-P_k)` 的浮盈("播种 phantom")。修复前的首次
实测出现 Δ=+523.3% 的 PASS(全 3 项过),经排查确认是该 phantom 在 73 次切换中复利累积所致——按所有者
确认的"偏移量修正"方案(常数 `seed_phantom_total` 从 equity 中扣除;`range_harvest` 按"首次卖出该格时
一次性核销其 phantom"的增量记账法核销)修复后,上表为修复后的诚实结果。

修复后的真相是:range 态(本应是收割层)在 honest 记账下**净亏 -247.2%**,远超 switch_tax(3.13%)——
半仓"在 center 播种"在价格继续下行时是一个真实的方向性亏损来源(播种价高于后续大部分卖出价),
不是 switch_tax 这种纯成本项能解释的。结合 maxDD -97.2%(接近清零),S1e 不是"擦边不过",
是**结构性失败**——直接进 §7 收口,不进中间带救援(中间带条款要求 Δ>0,本次 Δ 远 <0)。

---

## 10. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-06-11 | v0.5 | 本文件:S1e 三态混合构型的 code-level 实施计划——§2 结构洞察(Δ 全在 range 态)锐化判据;§3 精确落点(trend.py `hybrid_regimes` / backtest.py `run_s1e` + `S1eResult` / `grid_b_s1e.py`);§4 把 v0.3 §3 判据操作化为 `switch_tax < range_harvest/3`;§5 单测清单(44→~52);§6 Track A 钩子;§7 收口预案。**只计划不实现**,实现为下一轮。 |
| 2026-06-11 | v0.5 实测 | §3 全部落地(`HybridRegime`/`hybrid_regimes`、`run_s1e`/`S1eResult`、`grid_b_s1e.py`,单测 44→56)。实现期间发现并修复"播种 phantom" cost-basis bug(首跑 Δ=+523.3% PASS 不可信;偏移量修正后为诚实结果)。BTCUSDT 2021-01..2026-05 实测:Δ(s1e-hold)=-93.7% vs +564.6%=**-658.3%**,0/6 年正,range_harvest=-247.2%(本身为负,远大于 switch_tax 3.13%),maxDD -97.2%。**三项判据全不过且远非擦边 → §7 收口,H1/H2 双死**。 |
