# X4 实盘仓位管理 — 优化分析与回测主文档（线 D）

> 隔离边界：本文属**线 D（X4 加密 bake-off）**,只向线 A 借教训不借纪律,变更写回本线文档,不写
> `current.md` / `update-log.md`。bake-off / 判生死 / 上线决策仍以 `docs/crypto-x4-plan.md` 为事实入口;
> **本文 = 「实盘仓位管理」这一横切面的优化分析与回测主文档**——加减仓机制、sizing、仓位占比是否正确等
> 问题在此解剖、回测、挂载优化候选,结论再回写 `crypto-x4-plan.md` 对应章节。
>
> 代码真相:`src/qount/x4/live.py`(纯函数仓位逻辑,网络无关、单测覆盖)+
> `scripts/desktop/x4_live.py`(驱动 + 落盘)+ `src/qount/x4/backtest.py:run_directional`(回测 sizing 真相)。
> 运行态:当前 **全量 ARMED**(`QOUNT_X4_LIVE_ENABLE=1` + `QOUNT_X4_SHORT_GATE=1`),本金 `auto`(实时
> USDT 余额 ~$485)。当前**多头闸 SHUT**(BTC 在 200MA 下 −16.5%)→ **做空闸开 6 条真实空仓**,gross
> ≈ 0.29、占用保证金 ~$70 = **买力的 ~14%**(本文 §8 专题解剖此数是否正确)。cron 每 10 分钟对账。

---

## 0. 一句话定性

当前实盘**有完整仓位管理**,但范式是**「目标权重对账制」(target-weight reconciliation)**,
**不是**传统的「分批加仓 / 金字塔 / 补仓摊低 / 分批止盈」。每个 cron tick 重算一套**目标权重**,再把
实际持仓**对账**成目标——「加仓 / 减仓」是这个对账的副产物,而非独立的策略动作。

---

## 1. 仓位是怎么定出来的(sizing 五层,逐层相乘)

`target_weights()`（`live.py:251`）每轮调用一次,层层相乘得到每个币的**绝对暴露权重**(占本金的比例,
Σ 不为 1):

1. **总闸 risk-on/off** — `portfolio_gate_open`（`live.py:153`):
   `BTC > SMA200` **OR** 全市场广度 ≥ 50%（`breadth_gate=0.5`, `breadth_combine="or"`）上各自 SMA200
   → 风险开;否则默认 **100% 现金**(若 `short_gate=True` 则对确认下跌的币反手做空,§24)。
2. **个币趋势过滤** — 持有该币 ⟺ `close > SMA200 AND SMA_fast(20) > SMA_slow(60)`（`_coin_windows_scales`,
   `live.py:208`）。`slow` 已按 §24.1 由 100 调到 **60**(训练/测试再优化,更早进趋势)。
3. **逆波动率相对权重** — `1/σ`(最近 `vol_lookback=30` 日收益的标准差),归一到 Σ=1
   （`_inverse_vol_parity`, `live.py:223`)。
4. **相关性惩罚** §21.4 D — 每个币 `÷ max(平均两两相关, corr_floor=0.2)`,压低与篮子同涨同跌的币。
5. **vol-parity 绝对仓位** — 相对权重 × `min(max_leverage=2.0, vol_target=0.03 / atr_pct)`,
   `atr_pct = ATR(14)/price`。**这是真正决定「每个币下多少钱」的旋钮**:把每个币定标到 3% 目标波动,2x 封顶。

**gross 防御性 clamp**（`compute_orders`, `live.py:472`）:若 `Σ|w| > max_leverage` 则整体等比缩小。
正常加密波动下 gross ≈ 0.5–1x,极端低波时才顶到 2x。

**本金口径**:`QOUNT_X4_CAPITAL=auto`（cron 默认）→ 本金 = 实时 USDT 钱包余额（`x4_live.py:157`),
盈亏让全账户仓位**自动伸缩**(隐含的 equity-curve sizing:赚了名义额涨、亏了缩)。固定数字或 unset 走
`LiveConfig` 默认 $415。

---

## 2. 「加减仓」机制(对账式,确实存在)

- **rebalance_band = 0.25**（`live.py:490`）:只有当 `|目标−现仓| > 25% × max(目标,现仓)` 才动这条腿,
  否则跳过不动 → 防止 10 分钟一跳的高频空转换手。**漂移超 25% 就自动加仓 / 减仓**,这就是它的「加减仓」。
- **全平 (target=0) 永不被 band 拦**:信号掉了 / 闸关了必定清仓(`tgt_usdt != 0` 才进 band 判断)。
- **下单上下限**:`min_order=$6`、`max_order = min(max_order_usdt, capital × max_leverage)`。
- swap 上用 **`reduce_only`** 精确区分「减仓 / 平仓」与「开仓 / 反手做空」（`live.py:511,525`):
  纯减多 / 纯平空 = reduceOnly;开空 / 加空 / 穿越零轴反手 = 非 reduceOnly。

---

## 3. 止损 / 减仓保护(三层)

1. **盘中 Chandelier 移动止损** `apply_chandelier_stops`（`live.py:296`):跟踪高点,跌破
   `peak − chandelier_mult(8)×ATR(22)`（≈ −28%）→ 强平并 **latch 锁死**到日线信号重置。
   注释明确这是**灾难 / 防强平兜底,不是收益优化器**(实测紧止损 3×ATR 掉 ~44pp,无稳定最优)。
   做空腿镜像:跟踪低点,被挤压上破 `trail_low + short_chandelier_mult(3)×ATR` 平。
2. **交易所原生兜底止损** `plan_stop_orders` + `sync_stop_orders`（`live.py:405,717`):在交易所挂
   reduce-only `STOP_MARKET closePosition`,防止两次 cron 之间的瞬间插针未被 10 分钟轮询接住;随移动止损
   cancel+replace,`stop_amend_band=1%` 去抖。(踩过坑:Binance 条件单要 `params={"stop":True}` 才查得到,
   否则每轮重挂触发 `-4130` 崩 run,`fetch_open_stops` 注释有记。)
3. **每日收盘信号退出**:个币趋势 / 总闸在**日线收盘**判定,信号掉 → 下一轮对账全平。

**杠杆安全**:`prepare_swap`（`live.py:588`)设逐仓 + 2x 后**读回校验**,无法确认 2x 的币拒绝交易
(防 Binance 新合约默认 20x → ~−5% 强平)。

---

## 4. 明确**没有**的东西(传统加减仓手法对照)

| 传统手法 | 现状 | 说明 |
|---|---|---|
| 金字塔 / 浮盈加仓 | ❌ 无 | 仓位每日由 vol-parity 一次性定,不分批堆叠 |
| 补仓 / 摊低成本 (DCA into loser) | ❌ 无 | 与趋势纪律冲突 |
| 分批止盈 / 移动止盈减半 | ✅ **已接(默认关,§10.1)** | `apply_scale_out`:浮盈每 +20% 落袋,armed via `QOUNT_X4_SCALE_OUT` |
| 组合级回撤动态减仓 | ⚠️ **仅回测有** | 见 §5,实盘未接 |

---

## 5. ⚠️ 回测 ↔ 实盘的关键缺口:动态回撤减仓 (T3-8)

回测 `run_s7_combine` 有 **T3-8 `dd_derisk`**（`backtest.py:625`):当组合回撤超
`dd_derisk_threshold` 时,把总暴露按 `dd_derisk_vol_target / vol_target` 砍(如 3%→2%),作为回撤护盾。

**`x4_live.py` 这条实盘路径里没有接它。** 实盘的回撤保护只剩:
- 宽 Chandelier(−28%,本就是灾难兜底非渐进护盾);
- 2x 强平线。

考虑 v2 永续 2x 的 in-sample maxDD ≈ **−42%**,这是一个**值得补的缺口**:实盘缺渐进式降杠杆,
回撤里没有「先减一档仓位」的中间态,从满仓直接到宽止损 / 强平。

---

## 6. 后续优化挂载点(候选,均须先回测验证再上 paper,守线 D 赛马纪律)

1. **把 T3-8 动态回撤减仓接进实盘** —— 优先级最高,直接补 §5 缺口。组合级 equity 回撤超阈 → 临时下调
   `vol_target` 重算 `target_weights`,band 自然把仓位减下来。需要一个组合级 equity 回撤的实盘状态(可复用
   `equity_history.json` / `equity_daily.json`,已落盘)。
2. **评估浮盈加仓 / 分批止盈是否值得** —— **已回测(§10)**:浮盈条件化收紧止损 = 无 edge;**分批止盈 =
   真·风险调整改善**(Sharpe 0.91→1.00、maxDD −28%→−22%,train/test 双段不劣,代价 ~18pp 总收益),正对
   「利润回吐」。**未接 live**(live.py 走 `target_weights`+`apply_chandelier_stops`,非 `run_directional`)。
3. **band / vol_target / chandelier 的联合 sweep** —— 现值多为预注册或单因子优化,缺联合面板。
4. **auto-capital 的伸缩节奏** —— 盈亏即时改名义额,回撤中是否会过快缩仓值得 forward 观察;**做空侧的
   「探底加仓」逆周期问题(§8.3①)已回测=不值得修**(wallet 口径 ≈ margin,见 §9),不再列为候选。
5. **做空书 BTC 掉单的可达性**(§8.2) —— $485 本金下 BTC 空腿落不下去、书向山寨集中,本金到 ~$600 才补齐;
   评估是「等本金到位」还是「为做空书单独放宽 BTC 的最小下单逻辑 / 接受无 BTC 的山寨做空书」。

---

## 8. 当前快照解剖 — 「14% 购买力仓位」是否正确(2026-06-18)

> 数据源:VPS `state/x4/live/latest.json`,bar `2026-06-17`,本金 `auto`。

### 8.1 这 14% 到底是哪个数

| 量 | 值 | 口径 |
|---|---|---|
| capital(本金,auto=**walletBalance** 已实现口径) | **$485.40** | sizing 基;§11 修:此前误用 marginBalance |
| buying_power(= capital × max_leverage 2x) | **$970.81** | 名义可下满额 |
| deployed(6 条空仓 gross 名义) | **$140.16** | 实际敞口 |
| margin_used(= deployed ÷ 2x) | **$70.08** | 真占用保证金 |
| gross_exposure(= deployed ÷ capital) | **0.289** | 看板「敞口×」 |

「**14% 购买力仓位**」= `deployed / buying_power = 140.16 / 970.81 = 14.4%`,等价于
`margin_used / capital = 70.08 / 485.40 = 14.4%`。**它不是一个被设定的目标值,而是 vol-parity sizing 的
输出。** 当前是**做空闸**的书(多头闸 SHUT:BTC $63.6k vs SMA200 $77.3k,−16.5%),用的是 §24 验证过的
保守档 `short_vol_target=0.02 / short_max_leverage=1.5`(比多头 0.03 / 2.0 小一半),所以输出本就该小。

### 8.2 结论:口径正确,但这是个「打了折」的输出 ⚠️

**✅ 机制正确、且与回测验证档逐字一致。** live 的 `LiveConfig` 做空默认(`short_regime_sma=100`、
`short_vol_target=0.02`、`short_max_leverage=1.5`、`short_chandelier_mult=3.0`)= `crypto-x4-plan.md` §24
可部署中心 `regime100 + 止损3x + size2%/1.5x`(注:§24「3x」是**止损 ATR 倍数**,不是杠杆;杠杆是 1.5x)。
14% 是「做空闸刻意做成多头一半权重」的保守输出,**不是仓位过大**。

**⚠️ 但实际书比目标书小、且被 BTC 掉单扭曲。** 7 币目标权重之和 `Σ|w| = 0.401`(意图 gross ≈ 40% 本金),
而**最大那条腿 BTC(−10.3%)被静默跳过**——目标名义 ~$50 < BTCUSDT 永续最小 lot(~$60)→ 落不下去。
结果实际只剩 6 币、gross 从意图 40% 掉到 **29%**(= 14% 买力)。这个掉单**不中性**:

- 砍掉的恰是**单笔最大、最有流动性**的腿,realized 书被**集中到 6 个山寨**;
- 山寨的逼空右尾比 BTC 更凶 → 对一个**做空书**,这正是最不想要的偏斜(每块钱的 squeeze 风险被抬高)。

**要忠实跑出验证过的书,本金需高到 BTC 空腿可达**:BTC 目标权重 0.103 × 本金需 ≥ ~$60 lot ⇒ 本金
≈ **$600**(当前 $485 差一档)。在那之前,做空书会持续缺 BTC、向山寨集中。

### 8.3 加减仓机制本身的两个真问题(不是 14% 本身)

1. **auto-capital 在做空侧是「逆向顺周期」(机制真,量级=微不足道 → 已回测证伪此修复)。** 本金 =
   `marginBalance`(含未实现盈亏)。空头**赚钱时**(价跌)→ equity 涨 → capital 涨 → 目标名义涨 →
   `rebalance_band` 触发**对赢钱的空头加仓**——而那往往是**接近底部 / 均值回归区**,对做空是逆风的金字塔。
   反过来被逼空时 equity 跌 → 自动**减仓降险**(这一侧是对的)。**净效应:逼空里护、探底里加**,方向不对称。
   **→ 已回测验证「做空侧改 walletBalance 口径」(§9):wallet 与 margin 几乎逐位重合(total +243.4% vs
   +245.8%、Sharpe 1.16=1.16、maxDD −30.2%=−30.2%、空头成交 477 vs 479),机制存在但量级二阶可忽略 →
   不部署。** 根因:做空书 size 仅 2%/1.5x(gross ~0.3x)+ 紧 3×ATR chandelier 很快 latch 掉赢家,浮盈来不及
   喂回仓位;band 0.25 又吸收了那点漂移。
2. **组合级动态降杠杆(T3-8)实盘仍未接**(同 §5)。不过做空侧的尾是**逼空(右尾)**,而做空闸用的是**紧
   chandelier 3×ATR**(≈ 多头 8× 的两倍紧)+ 交易所兜底止损,所以做空腿的尾护盾其实比多头腿到位。T3-8
   的价值主要在**多头满仓**时,做空这 14% 暂不是它的主战场。

### 8.4 一句话给 owner

当前 **14% 买力 = 验证过的保守做空档的正常输出,口径没错、也不算大**;真正该盯的不是「14% 对不对」,
而是 **① BTC 空腿在 $485 本金下落不下去 → 做空书缩水 40%→29% 且向山寨集中**(本金到 ~$600 才补齐),
**② auto-capital 让赢钱的空头在探底区被动加仓**。这两点都是「加减仓机制」层面的结构问题,优先级高于调
14% 这个数本身。

---

## 7. 落盘产物(便于回放 / 复盘)

`state/x4/live/` 下:`latest.json`(看板源)、`orders.jsonl`(仅在有对账事件时 append 的交易审计)、
`snapshots.jsonl`(每轮精简状态时间线)、`equity_history.json`(盘中 10 分钟点)、`equity_daily.json`
(日线一日一点)、`stops.json`(Chandelier trail 状态)、`inception.json`(总盈亏基线)。

---

## 9. 回测验证 — 做空侧本金口径 walletBalance vs marginBalance(2026-06-18,= 不部署)

**命题**(§8.3①):做空侧 sizing 改用 `walletBalance`(已实现口径,不含浮盈)替代 `marginBalance`(含浮盈),
消掉「对赢钱的空头在探底区加仓」的逆周期。

**工程**:`X4Account.wallet_balance()`(= `equity` 减开仓 MTM)+ `run_directional(wallet_sizing=)` 旋钮
(默认关,关时与旧路径字节级一致;`backtest.py:166`)。研究脚本 `scripts/research/x4_short_wallet_sizing.py`
复用 `x4_short_gate.py` 的载入/闸/拼接原语,**唯一变量 = 空头 sleeve 的本金口径**,多头书两臂共模。+6 单测
(account 3 + volsizing 3,验 wallet 不含浮盈 / 赢家不金字塔 / 输家不减仓);**x4 共 252 全绿**。

**配置** = §24 可部署中心 / live 做空默认:`ShortTrend(fast20/slow100/regime100)` + 止损 3×ATR + size
2%/1.5x。基线逐位对账 §24(现状 +142.0%/0.91/−28.2%、margin 做空闸 +245.8%/1.16/−30.2%)。

| 本金口径 | total | Sharpe | maxDD | train | test | 空头成交笔数 |
|---|---|---|---|---|---|---|
| 现状(闸SHUT→现金,无空头) | +142.0% | 0.91 | −28.2% | 0.78 | 1.01 | — |
| **margin(现状/含浮盈)** | **+245.8%** | **1.16** | **−30.2%** | 1.04 | 1.27 | 479 |
| **wallet(已实现/不含浮盈)** | **+243.4%** | **1.16** | **−30.2%** | 1.06 | 1.25 | 477 |

(空头书本体:margin +23.0%/0.33/−35.6%/SHUT 段 +42.9% vs wallet +22.3%/0.33/−35.2%/SHUT 段 +41.9%。)

**结论 = 不部署。** wallet 与 margin **几乎逐位重合**:total −2.4pp(略劣)、Sharpe / maxDD 不变、train/test
互有微增减(各 ±0.02)、空头成交仅少 2 笔 → **「探底加仓」机制真存在,但量级二阶、可忽略**。根因:做空书
size 仅 2%/1.5x(gross ~0.3x)+ 紧 3×ATR chandelier 很快 latch 掉赢家,浮盈来不及喂回仓位;`rebalance_band`
0.25 又吸收那点漂移。**caveat**:① 回测每 sleeve 独立 100k 各自复利,live 是全账户共一本金池读一次——机制
同源(把浮盈排除出 sizing 基),量级结论可迁移;② wallet 是对称的——它同时拿掉了浮亏时的保护性减仓,所以
即便量级显著也未必净优。归入「已测·非增量」,旋钮保留默认关(研究用)。

## 10. 回测验证 — 出场/锁利:浮盈条件收紧 vs 分批止盈(2026-06-18,= 分批止盈值得,未接 live)

**命题**(§8 / owner 痛点「利润到手了又没了」):多头出场二元(信号掉→全平 / chandelier 宽 8×ATR ≈ 峰值
回撤 28% 才走),无分批止盈 / 浮盈锁利 → 一笔趋势可 +100% 回吐 28% 才平。回测两条对症候选 vs 现状宽 8×。

**工程**:`run_directional` 加两组默认关旋钮(关时字节级一致):① `profit_lock_threshold`/`profit_lock_mult`
(入场仍宽 8×,浮盈≥阈值后切紧 Y×ATR 锁利);② `scale_out_step`/`scale_out_frac`/`scale_out_residual`
(浮盈每 +step 永久减 frac,留 residual 残仓继续 trail,ratchet 不回吐再加仓)。+4 单测 → **x4 共 857 全绿**。
研究脚本 `scripts/research/x4_profit_taking.py`,复用 `x4_short_gate` 原语,基线由构造对账 §24(+142.0%/0.91/
−28.2%,train 0.78/test 1.01),唯一变量 = 多头 sleeve 出场参数。funding/taker/滑点已扣。

| 配置 | total | Sharpe | maxDD | train | test |
|---|---|---|---|---|---|
| **现状 宽8×(基线)** | **+142.0%** | **0.91** | **−28.2%** | 0.78 | 1.01 |
| ①锁利 +15%→3× | +69.7% | 0.66 | −27.9% | 0.75 | 0.55 |
| ①锁利 +40%→4×(①最优) | +145.0% | 0.94 | −30.7% | 0.75 | 1.11 |
| **②分批 每+20%减33%** | +124.4% | **0.99** | **−22.0%** | 0.76 | 1.23 |
| **②分批 每+20%减50%** | +123.2% | **1.00** | **−22.1%** | **0.79** | 1.22 |
| ②分批 每+30%减33% | +123.2% | 0.96 | −22.1% | 0.68 | 1.24 |

**结论**:
- **① 浮盈条件化收紧 = 无 edge。** 收紧后被噪声打出去又错过续涨;紧档(3×)毁收益(−70%档),宽档(4×/5×)
  顶多总收益持平但 **maxDD 普遍变差**(−30~32% vs −28.2%)、train 普遍降。不部署。
- **② 分批止盈 = 真·风险调整改善(同族里唯一过的)。** 每+20%减 33%/50% + 留 1/3 残仓:**Sharpe 0.91→0.99/
  1.00、maxDD −28.2%→−22.0%(砍 ~6pp)**,且 **train/test 双段都不劣**(减50%档 train 0.79≥0.78、test
  1.22≫1.01 = 不是过拟合,OOS 反更好)。代价 = 总收益 −18pp(+142%→+124%,卖了赢家让出部分上行)。
  **机制**:在分散趋势书上分批落袋,削掉权益曲线的波动与回吐而不杀掉趋势捕获(残仓仍 trail)。**这正是
  owner「利润回吐」的解药**;且在 **2x 永续**上砍 maxDD/降回吐比现货回测显示的更值。

**性质 = 风控/锁利旋钮(改善 Sharpe+DD、换总收益),非纯收益 alpha**——但与 T3-8(动态降仓,FAIL 双段)不同,
它**过了双段且对症痛点**。**推荐档**:`scale_out_step=0.20 / scale_out_frac=0.50 / scale_out_residual≈0.34`。

### 10.1 已接进实盘(2026-06-18,已部署 + armed)

- **纯函数** `live.py:apply_scale_out(targets, live_prices, entry_prices, positions_base, so_state, cfg)`:
  对**同向持仓**按交易所 `entryPrice` 算浮盈,每 +`step` 永久把目标权重砍 `frac`、floor 在 `residual`,
  **ratchet(steps 只增不减,回撤不再加仓)**,状态持久化 `state/x4/live/scale_out.json`(跨 2 分钟 cron)。
  对多/空腿对称生效(空腿同理,但验证是多头侧)。`compute_orders` 的 reduce-only 把砍下来的部分作减仓单。
- **runner 接入**:`x4_live.py` 在 `apply_chandelier_stops` 之后、`compute_orders` 之前调用;落 `scale_out.json`;
  快照加 `scale_out`/`scaled_out`/`scale_out_steps`(看板)。
- **arm 开关** `QOUNT_X4_SCALE_OUT=1`(env,默认关时**字节级一致**)→ 自动套推荐档。+6 live 单测(共 863 全绿)。
- **VPS 已部署 + armed**(md5 校验一致;env 加 `QOUNT_X4_SCALE_OUT=1`,已备份)。**当前 inert**:6 条空仓浮盈
  均 <20% → `scale_out_steps` 全 0、0 减仓单;待任一腿跑 +20% 自动落袋 50%、+40% 落到残仓 1/3。
- **caveat**:`live.py` 仍另有**交易所兜底止损 amend 的 `-4130`/`OrderNotFound` churn**(预存在、非本次引入、
  非致命——旧止损仍在交易所护着仓,只是 trail 收紧没推上去),是独立待修项,与分批止盈无关。

## 11. 收益口径修正 + 做空 gross 抬到 0.6(2026-06-19,owner 反馈)

### 11.1 🔴 修:auto 本金/权益重复计未实现盈亏(收益虚高 ~2×)

**owner 发现**:看板「总盈亏」≈ 真实的两倍,且「我没平仓哪来已实现」。**根因坐实**(查交易所原始字段):
ccxt `fetch_balance()['USDT']['total']` 在 USDⓈ-M = **marginBalance**(= walletBalance + 未实现),
而 runner 把它当 `capital` 后又 `equity = capital + 未实现` → **未实现被加了两遍**。实测:
`totalWalletBalance=484.91 / totalUnrealizedProfit=4.06 / totalMarginBalance=488.97(=total)`。
旧:equity = 488.97 + 4.06 = 493.03(虚高);total_pnl ≈ 真实的 ~2×(未实现计两遍)。

**修**:新增纯件 `live.py:usdt_wallet_balance(bal)` 取 **walletBalance**(优先 `info.totalWalletBalance`,
回退 `total − totalUnrealizedProfit`,再回退 `total`);`_perp_usdt_balance` 改用它。于是 `capital` =
walletBalance(现金/已实现口径),`equity = capital + 未实现 = marginBalance`(只加一遍)。
**VPS 验真**:capital(wallet) $484.90 + 未实现 $3.51 = equity $488.41 = marginBalance ✓;
total_pnl = 488.41 − 484.57 = **$3.84(真实,非旧的 ~$7+)**。+4 单测(共 867 全绿)。**副益**:sizing 也
从 marginBalance 转 walletBalance(= §9 验证过 ~无差异且更对:不拿浮盈当本金下单),与 owner「没平仓不算钱」
直觉一致。

### 11.1b 收益曲线修复(历史点重建 + 防再污染)

旧 `equity_history.json` / `equity_daily.json` 的历史点是用**翻倍的 equity** 写的,且有一处 **$415 假点**
(auto 本金读取失败回退 `LiveConfig` 默认 → 曲线假跌)。**修两处**:
- **根因防再污染**:runner 在 `holdings_ok` 为真(余额已知)时才记曲线点 → auto 读取失败不再种假点。
- **历史重建**(一次性,VPS,原文件备份 `.prefix-bak`):从 `snapshots.jsonl`(存了每点 `capital`/`equity`/
  `unrealized_pnl`)重算真值——**pre-fix 真值 = `capital`(= marginBalance = 真权益)**,post-fix 真值 = `equity`;
  跳过 `capital==415` 的假点;按本地分钟去重。重建后 141 点、区间 $483.84–489.02(原 $483–493 + 415 假点)、
  无翻倍台阶、无假跌。going-forward 由修好的 runner 自然续写。

### 11.2 做空 gross 上限 0.40 → 0.60(owner 指定)

**owner**:「空头上线仓位给到 0.6」。**正确旋钮 = `short_vol_target`(非 cap)**:`short_max_leverage` cap
1.5 是**惰性**(per-coin scale ~0.3 远不触顶,实测 vt0.03 下 lev1.5≡lev2.0 → cap 不 bind);抬 gross 要动
vt。`short_vol_target 0.02→0.03` → 空书 gross ~0.40→~0.60。**回测**(拼账,§24 harness):
+246.5%→**+311.6%**、Sharpe 1.17→**1.23**、**train 1.04→1.12 / test 1.27→1.33 双升**、maxDD −30.2%→−31.1%
(~1pp 深 = 逼空尾代价)。过双段、利大于弊。**副益**:0.6 档下 BTC 空目标 $72 > 最小 lot → BTC 不再被
跳过,§8.2 的「BTC 掉单山寨集中」偏斜自动消除。**已部署 VPS**:`LiveConfig.short_vol_target=0.03` 默认改,
下一轮 reconcile 自动加空到 ~0.6(实测发 5 单加空,BTC 0→−75 等)。⚠️ vt0.03 偏离 §24 验证中心(vt0.02),
是 owner 知情的收益旋钮加注,2x 永续上尾 ~1pp 深。

## 12. 深度优化分析:动态杠杆 / 仓位管理 / 趋势判断 / 刷新频率(2026-06-19,owner 点名四方向)

脚本 `scripts/research/x4_optim_analysis.py`(daily 面板)+ `x4_refresh_freq.py`(日线 vs 4h)。LONG 组合
= live 全配置(slow60/vt3%/lev2/band.25/chand8 + breadth-OR + corr,funding-adjusted),**基线逐位对账
§24.1 = +172.8%/Sharpe 1.07/maxDD −26.1%/train 1.00/test 1.12**。判据:增量须 ① Sharpe 不劣 ② train&test
双段不劣 ③ maxDD 不恶化。

### ① 动态杠杆 = 无免费午餐(纯风险旋钮,非 alpha)

| 档 | total | Sharpe | maxDD |
|---|---|---|---|
| vol_target 0.02 | +99.3% | 1.07 | −18.2% |
| vol_target 0.03(现状) | +172.8% | 1.07 | −26.1% |
| vol_target 0.04 | +269.8% | 1.08 | −33.0% |

**Sharpe 在 vt 0.02–0.04 上恒定 ~1.07**——vol_target 只是沿同一条 风险/收益 直线滑动,不创造 alpha。
`max_leverage` cap 实测**惰性**(1.5≡2.0≡3.0 全 +172.8%,vol-parity scale 够不到顶)。T3-8 组合回撤降杠杆
=降 DD 也降收益、Sharpe≤基线(风控旋钮,已知)。**结论:杠杆没有「动态调出超额收益」的空间——它只决定你
坐在风险线的哪一点(=owner 风险偏好)。做空→0.6、vt 调档都是纯风险加注,不是 edge。**

### ② 仓位管理:band 0.4 轻微改善(噪声偏大);分批止盈才是主胜利(已上)

`rebalance_band` 0.25→0.4:+188.4%/Sharpe 1.09/maxDD −25.9%/train 0.98/test 1.18——少换手让仓位多骑一会,
总收益 +15pp、Sharpe +0.02,但细扫(0.3 跌/0.4 跳/0.45 跌/0.5 跳)**不是干净平台**、train 微降。轻量候选,
非必做。**仓位管理的真增量是 §10 分批止盈(已部署):Sharpe 0.91→1.00、maxDD −28→−22%。**

### ③ 趋势判断:核心参数已在最优;唯一新发现 = 轻量 ADX + 略宽 band 组合(值得验)

- **核心参数全部复核到最优**:slow=60(唯一 train≥1.0;40/50 train 仅 0.77/0.79=过拟合 test)、regime_sma=200
  (250 崩到 0.72;150 略差)、breadth_gate=0.5(0.3/0.4 漏 chop→0.90;0.6 漏机会)——**= baseline 近天花板,确认**。
- **🟢 新发现:轻量 ADX 是真·风险质量增量**。细扫 `adx_min 12–16` 是**平台**(非单点):

  | adx_min | total | Sharpe | maxDD | train | test |
  |---|---|---|---|---|---|
  | 0(现状) | +172.8% | 1.07 | −26.1% | 1.00 | 1.12 |
  | 14 | +175.4% | 1.10 | **−21.5%** | 0.99 | 1.20 |
  | 15 | +172.2% | 1.09 | −21.9% | 1.02 | 1.15 |
  | 16 | +175.7% | **1.11** | −22.7% | 0.99 | 1.22 |
  | 18 | +137.7% | 0.98 | −23.9% | 0.85 | 1.11 |

  adx 14–16:**总收益持平、Sharpe +0.03、maxDD −4~5pp,train/test 双段都不劣**。adx≥18 才开始毁收益——
  **修正旧「ADX 非 alpha」结论**:那是测 ≥20(过紧);**轻档(~14–15)只滤掉最烂的无趋势 chop,不杀趋势捕获**。
  **ADX15 + band0.4 叠加 = +183%/Sharpe 1.11/maxDD −21.9%/train 1.00/test 1.19**(两段都不劣,maxDD 砍 4pp,
  2x 永续上实在)。**= 看似同分批止盈一族的风险质量增量。** ⚠️ **但这是全样本单期数 → §12.1 walk-forward 证伪。**

#### 12.1 🔴 轻量 ADX walk-forward = 证伪(不上 live)

`x4_adx_walkforward.py`:9 个滚动 OOS 折(train 504 / test 126 / step 126)。

| 指标(OOS 均值) | 基线 adx0 | 固定 adx14 | WF-selected |
|---|---|---|---|
| Sharpe | **1.01** | 0.99 | 0.89 |
| maxDD | −8.5% | −8.1% | — |
| Sharpe ≥ 基线的折 | — | 5/9 | 7/9 |
| maxDD 不更深的折 | — | **4/9** | — |
| WF 选出的 adx 分布 | — | — | {0:3, 14:3, 16:3} |

**结论 = 证伪**:① 固定 adx14 OOS Sharpe **0.99 < 基线 1.01**(略劣);maxDD 改善**不泛化**——9 折里只有
**4/9** 不更深,多数折 ADX 反把回撤做**更深**;§12 全样本的 −4pp maxDD 几乎全由**单一事件**(2024-02..06 折:
adx14 −11.3% vs 基线 −16.5%)贡献,OOS 不复现。② 真 walk-forward(train 选 adx → 应用 OOS)**反而更差**
(0.89<1.01)且选择不稳({0,14,16} 各 1/3)。**= §12 的「ADX 增量」是全样本单 regime 假象,walk-forward
拍掉;原「ADX 非 alpha」成立,不上 live。** 教训:**全样本 train/test 双段过 ≠ 滚动 OOS 过**;maxDD 类
改善尤其易被单期主导——上真金前必过 walk-forward。**趋势侧无可上线增量,baseline 核心参数即天花板,确认。**

#### 12.2 继续找方向(2026-06-19,owner「接着找」)= universe / 加权 / 闸口径 全部再确认天花板

吸取 ADX 教训,凡 maxDD 类改善一律内建 walk-forward。

- **universe 多样化(`x4_universe_wf.py`,walk-forward)= 证伪**。把 LONG 书从 TOP7 扩到 TOP10/ALL18:

  | universe | total | Sharpe | maxDD | train | test |
  |---|---|---|---|---|---|
  | TOP7(现状) | +172.8% | **1.07** | **−26.1%** | 1.00 | 1.12 |
  | TOP10 | +125.7% | 0.89 | −29.2% | 0.71 | 1.06 |
  | ALL18 | +101.3% | 0.81 | −29.3% | 0.99 | **0.57** |

  walk-forward:broader OOS Sharpe **0.74 vs TOP7 1.01**,≥TOP7 仅 **2/9** 折。**加币反而更差**——低档山寨①趋势更
  噪(信号质量差)②崩盘时一起 dump(尾部不分散,maxDD 更深)。**「分散>选择」有质量上限:只在 quality 趋势币
  之间成立,加垃圾币是稀释不是分散。TOP7 已是好选择。** 推论:扩 universe 不是杠杆;真要纳更多币得是同档
  流动性 + 更大本金,且仍未必改善。
- **加权方案 = 现状最优**:inverse_vol_corr 1.07 > inverse_vol 1.05 > equal 0.79(等权差很多——vol-parity 是真增量,已在用)。
- **闸口径 = 现状最优**:breadth-OR 远胜 AND(0.53)/ breadth-only(0.67)。

**= universe / 加权 / 闸 三处再确认 baseline 即天花板。** 趋势书本体的参数面已被反复扫到尽头。

#### 12.3 本轮元结论:趋势书到顶,真正剩下的上行是「闲置现金」结构性低效(carry sleeve)

跨本轮 + 历史所有测试,**趋势策略本体确在天花板**(核心参数/杠杆/刷新/universe/加权/闸全部最优或证伪)。
继续扫趋势参数 = 低 EV。**唯一未被吃掉的大块上行是结构性的:大盘闸 SHUT ~50% 时间,这半数时间本金在
现金里赚 ~0**(做空闸 §24 只在确认熊时填一部分,且是收益旋钮非全天候)。填这个空窗的正解 = **C×D 的
delta-neutral 资金费 carry sleeve**(线 C),与趋势负相关、做压舱石(§20:corr −0.196、加 40% carry→Sharpe
0.89→1.18、maxDD 砍半)。**但这是「给 spot + COIN-M 钱包注资 + 建 `rv/live.py`」的部署/资金决策,不是趋势
策略的参数调优。** = 下一步真正值得投入的方向,已在 §20 / cxd 记忆里 scope 过,卡在注资。

---

### ④ 刷新频率:日线是对的;4h 刷新更差(maxDD 翻倍 + OOS 崩,确认「日内=噪声」)

`x4_refresh_freq.py`:同一套 200/20/60-**DAY** 经济信号,bar 粒度 日线 vs 4h(lookback 同比 ×6),无 funding:

| 刷新粒度 | total | Sharpe | maxDD | train | test |
|---|---|---|---|---|---|
| 日线(现状,~24h 滞后) | +206.3% | **1.18** | **−25.1%** | 1.09 | **1.24** |
| 4h(~4h 滞后) | +354.7% | 1.16 | **−56.5%** | 1.43 | **0.99** |

4h 总收益虚高(更小 per-bar ATR→更大仓→更像加杠杆),但 **maxDD 翻倍到 −56.5%(2x 永续=清算区)**,且
**OOS test Sharpe 从 1.24 崩到 0.99、train 1.43≫test 0.99 = 典型过拟合**。**结论:信号本就是日线级现象,
刷新滞后 ~24h 不是约束;早动 ~20h 的收益被近-crossing whipsaw 吃掉还赔上尾部——确认线 D §11「日内=噪声」**。
**关键澄清**:cron **已每 2 分钟跑**——盘中止损(chandelier)/ 交易所兜底止损 / 实时价是**实时反应**的;
「一日才刷新」的只是**趋势进出信号**,而那**恰恰应该**留在日线(改快=变差)。所以现状设计是对的。

### 总结与建议(给 owner)

| 方向 | 结论 | 动作 |
|---|---|---|
| 动态杠杆 | 无 alpha,纯风险旋钮(Sharpe 跨 vt 恒定;cap 惰性) | 不动;vt/做空 size = 风险偏好选择 |
| 仓位管理 | band 0.4 轻微(噪声);**分批止盈(已上)是主胜利** | band 可选不必;分批止盈已 armed |
| 趋势判断 | 核心参数已最优;轻量 ADX 全样本看似增量但 **walk-forward 证伪(§12.1)** | 不上;baseline 即天花板 |
| 刷新频率 | 日线信号正确;4h 更差(maxDD 翻倍/OOS 崩);止损本就实时 | 不动 |

**一句话(经 walk-forward 收口)**:策略主体确在天花板——核心趋势参数全复核最优、杠杆无免费午餐、刷新
不该加快;§12 一度看好的**轻量 ADX 门经 walk-forward 证伪(§12.1)= 全样本单 regime 假象**,不上 live。
**当前无可上线的趋势/杠杆/刷新/universe/加权/闸侧增量**;已上线的真增量止于分批止盈(§10)+ 做空闸(§24)+
收益口径修(§11)。walk-forward 这一关把会上真金的过拟合挡在门外(ADX/universe 都被它拍掉)——maxDD 类
「改善」上线前必过滚动 OOS。**趋势书本体已到顶,继续扫参数是低 EV;真正剩下的大块上行 = §12.3 的闲置现金
carry sleeve(C×D,线 C),是给 spot+COIN-M 注资 + 建 `rv/live.py` 的部署决策,不是趋势参数调优。**

---

## 13. carry 腿 net_delta 口径 bug + 统一 + 漂移告警(2026-06-25,owner 复盘成交记录)

复盘实盘成交记录时发现 **carry(线 C 现货+COIN-M)腿的 delta 在两个 publisher 之间口径不一致、连符号都反**:
- `rv/live/latest.json` 报 `net_delta = −26.78`
- `cxd/live/latest.json`(`cxd_publish.py` 对账)报 `net_delta = +12.51`
- **两者差 $39、符号相反** → 对账没真正收敛,看板/告警拿不到可信的「是否偏离 delta 中性」。

### 13.1 根因 = 漏算 COIN-M 保证金币

差额精确 = **COIN-M 交割钱包里的抵押币(ETH)** 没被算进多头边:

| | 公式 | 值 |
|---|---|---|
| `rv_live.py:221`(旧,错) | `sum(current.values())` = 现货多 + 空头名义 = `+63.22 + (−90.0)` | **−26.76** |
| `cxd_publish.py:46-49`(对) | `(spot+earn+COIN-M margin coin)*px − \|空名义\|` | **+12.51** |

**反向(COIN-M / inverse)合约的空头是用 base 币(ETH)做抵押的**,交割钱包里那 `0.0242 ETH ≈ $39` 本身就是
多头 delta,必须计入;旧 `rv_live` 把 carry 当 USDT 线性合约来加,系统性漏掉它 → 一个对冲好的书被报成
「净空 ~−保证金」。**−26.76 是有 bug 的诊断值,+12.51 才是真 delta。**(印证 sizing 是对的:target 现货 66.5 /
空 99.75 那个 1.5× 过度做空,正是为中和「现货 + 保证金币」。)

### 13.2 修复 = 统一口径(rv 跟 cxd 对齐)

`rv_live.py` 的 net_delta 改成与 `cxd_publish.py` 同一套:多头 = 现货(total)+ Simple Earn + COIN-M 保证金币;
空头 = |交割名义|;带 try/fallback 防瞬时读失败(delta 中性腿绝不能因一次瞬时读 page)。只读脚本带真 key
对照验证:旧 −26.76 → 新 **+12.50**,与 cxd +12.51 吻合,差额精确等于保证金币 $39.26。两个 publisher 现已一致。

> 注意:**口径统一 ≠ delta 归零**。统一后两边都诚实显示 **+12.5(≈12% deployed long 的净多)**——这是真实
> 漂移:空腿差 1 张 COIN-M(第 10 张挂不上 −2019,见 cron `cxd_live_cron.sh` 的颗粒度注释)。口径修复的价值
> 就在此:以前 −26.76 把「净多漂移」伪装成「净空」,现在如实暴露。**根治漂移仍待做**(充值让空腿有颗粒度
> 余量 / 让 BTC 可注资,见 `docs/crypto-x4-plan.md` §20 与 [[x4-live-v2-perp-2x]])。

### 13.3 接上 |net_delta| 漂移告警(已部署)

- `rv_live.py`:`abs(net_delta) > QOUNT_RV_DELTA_ALERT_FRAC`(默认 **10%**)× **deployed long**(实际部署多头,
  非 config pin)→ 置 `delta_breach=true` 写进 state(连带 `delta_long_usd` / `delta_unified` / `delta_alert_frac`);
  仅在 **unified 路径成功**(拿得到保证金币读 = live key)时才可信。
- `cxd_live_cron.sh`:carry 腿跑完读 state，`delta_breach && delta_unified` → 发 Server酱 告警,**每个 breach
  episode 只发一次**(`~/.cache/qount/rv_delta_alerted` flag 去重 every-2-min cron;回到中性删 flag 重新 arm)。
- 生产验证:`unified=True breach=True long=102.51 frac=0.1` → cron 出 `[ALERT] carry Δ breach`,flag 落、1 条
  告警不随 tick 增长。**当前账户处于 breach(+12.5 > 10%)= 正确暴露真实漂移。**

### 13.4 根治漂移 = 连续 spot 腿主动中和净 Δ(已修 + 已部署 + 生产收敛)

口径修好后定位漂移的**结构性根因**(非 −2019 / 非保证金不足,而是 band + floor):

1. **floor 截断**:`place_carry_orders` 对 COIN-M 整张**向下取整**(`int(99.75/10)=9 张=$90`),realized 短腿
   = `floor(N/contract)·contract ≤ N`;而 `target_legs` 的 spot 长 + 保证金却按**未取整的 N=99.75** 配 →
   长边 ~99.75、短边 floor 到 90 → 结构性 +9.75 残差。
2. **band 卡死**:短腿想补 −90→−99.75(差 9.8% < 10% band)被当噪声跳过 → 残差永不收敛。
3. **超配保证金**:autofund 按 99.75 配的保证金币($39.29 vs 模型 $33.25)多出 ~$6 的裸多。

**修法 = 让连续的 spot 腿主动把净 Δ 归零**(纯函数 `neutralize_spot_targets`,src/qount/rv/live.py + 3 单测):
COIN-M 短腿只能整张跳(粗、量化),spot 可任意金额(细、连续)→ 用 spot 吸收一切残差:

```
spot_target = |floored 短腿| − COIN-M 保证金币       (clamp ≥ 0)
→ long(spot + 保证金) == short == Δ≈0,deployed 略缩、carry 收入跟短腿名义不变
```

在 `rv_live.py` live 层调用(读 COIN-M 保证金币 → 覆盖 legs,**autofund 前**跑好让它按更低的中和 spot 目标
配资);纯模型 `target_legs` / `compute_carry_orders` 及其单测**不动**(dry/无 key 回退模型 legs)。

- 生产收敛:`[Δ-neutralize] spot re-aimed vs floored short − COIN-M margin [('ETHUSDT', 39)]` → 空腿 floored
  到 −90(不再 churn 贵腿)+ **卖 $13 现货**(64→51)→ 真实 Δ **+12.51 → +0.03**(long 90.03 / short 90.00)。
- **根治完成**:残差从 1 整张合约($10≈10%)的系统性漂移降到亚美元的取整噪声(< min_order,不可再经济收敛)。
- 既有独立坑(已修):COIN-M `fetch_ticker` 撞 dapi `RequestTimeout` 会让 rv_live 整轮 fail + 误报 C×D 告警;
  commit fde09db 只给 `load_markets` 加了重试。已把重试抽成通用 `_resilient(fn, what=…)` helper(`NetworkError`
  退避重试,非网络错立即抛),`load_markets` + spot/COIN-M 每个 `fetch_ticker` 全走它 → 瞬时 dapi/api blip 不再
  整轮 fail / 误报。

---

_建档:2026-06-18(§8 快照 + §9 walletBalance 回测 + §10 出场/锁利面板)。2026-06-19 加 §11(收益口径修正 +
做空 gross→0.6)+ §12(四方向深度优化分析)+ §12.1(轻量 ADX walk-forward 证伪)。2026-06-25 加 §13(carry
net_delta 口径 bug 统一 §13.1-2 + 漂移告警 §13.3 + 根治漂移=spot 主动中和 §13.4)。判生死 / 上线决策仍走
`docs/crypto-x4-plan.md`。_
