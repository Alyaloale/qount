# L4 跨所套利计划：换「游戏」——市场中性,不预测方向

> **状态**：frozen/falsified（重启线，原地保留）｜索引见 [archive/README.md](archive/README.md)｜当前事实以 [current.md](current.md) 为准。

本文件是 §7 诚实止盈、L3 证伪、L1 固化暂停之后的**第三条重启线**。合法性同样来自
[profit-engineering-plan.md](profit-engineering-plan.md) §11.8 的「结构性新输入」——
L4 的结构性新输入是:**不再预测方向(IC 那条线已被广度天花板封死),改赚跨交易所之间的
funding/基差错位**。这是市场中性套利:在 funding 最低(或负)的所做多、在 funding 最高的所做空,
两腿同资产、同名义、净 delta≈0,收割两所之间的 funding 差,价格涨跌不影响。

> 纪律不变:research-only;live 关闭、不 forward paper、不放宽 broad gate、
> `validation_v1` once-only、一轮只改一处、先写单测、先证伪再投入。

---

## 0. 为什么是 L4(接 §7 / L3 / L1 的对账)

`IR = IC × √BR`。前三条线都在**这个公式内部**找盈利,全部撞墙:
- §7 / L3:绑定约束是 **BR**(majors r̄≈0.63 → 有效广度 ~1.6),换特征源、扩币都救不了。
- L1:正面抬 BR(跨资产 universe eff-breadth 2.97 真逃逸了),但零售 ETF 的 **edge 量级**只给
  净 Sharpe ~0.4 < 0.5,真 CTA 量级需期货券商(刻意推迟)。

L4 **跳出这个公式**:套利不预测方向,收益来自**两个市场对同一资产定价的不一致**,广度来自
「交易所对 × 标的」的数量,而非方向预测的独立下注。这是延迟无关、容量受 maker fill 限制、
但**不依赖任何方向 IC**的一类——和此前所有线(都在预测方向)正交。

**诚实前提**:单所 CARRY(§S-CARRY)已经证明 funding 现金流真实但被成本吃掉(已看窗口 after-tail
需 >100% maker fill,数学上不可行)。L4 赌的是**跨所 spread 比单所绝对 funding 更大、更持久**,
足以跨过双所往返成本。**若 spread 太小/太易翻转(套利者早压平),L4 廉价证伪**——这正是第一刀。

---

## 1. 命门与最廉价的第一刀(S1 = 跨所 spread kill-test)

L4 整条论点**只赌一件事:跨所 funding spread 的「幅度 × 持续性」是否跨得过双所往返成本。**
若否,L4 与单所 CARRY 没有区别,直接证伪——**这一刀纯数据(只读多所 funding 历史)、零新场、
零真实下单、零券商。**

```text
数据:  多所 perp funding 历史(ccxt fetch_funding_rate_history):
       Binance / Bybit / OKX × {BTC,ETH,SOL,...} USDT 永续(均 8h、共享符号串)
       [Hyperliquid 推迟到 S2:USDC 结算=不同符号/基差 + 1h funding,需独立映射]
对齐:  统一 8h bucket,严格 as-of(每所取 ≤ bucket 的最近一笔已结算 funding,无前视);
       各所 funding 按其原生结算间隔(8h/4h/1h,从相邻时间戳中位推得)归一到 8h 当量再比,
       避免 1h 与 8h 费率量级错配冒充 spread
信号:  每 bucket 取 spread = max_venue_funding − min_venue_funding(做多最低所、做空最高所)
读数:  per-bucket 净收割 = spread − 换腿成本;聚合年化 capture、Sharpe、
       break_even_cost_per_side、required_maker_fill、pair 持仓持续性 + DSR/PBO(每标的=一 trial)
判生死: 扣实测双所往返成本后年化 capture 显著 > 0 且 required_maker_fill ≤ 1 + DSR/PBO 过 → 进 S2
        否则(spread 被成本吃掉 / pair 每 bucket 翻转 / required_maker_fill > 1)→ L4 证伪,转 L5
```

命令:`l4-cross-exchange-funding-scan`(本轮落地,research-only、无仓位、不下单)。

---

## 2. 数据源现实(与 L1 同型的基建风险)

跨所 funding 历史走 ccxt,各所可达性**从生产主机(WSL)实测确认**(类比 L1 的 Tiingo 发现):
- **三所 Binance/Bybit/OKX 均需配置代理**(`HTTP(S)_PROXY` 必须在环境里;直连全部 NetworkError);
  跑命令前必须 `set -a && source .env && set +a`,否则 `Settings.from_env` 拿不到代理 → 全所 unreachable。
- 数据落 `state/` 缓存离线复跑。任一所不可达不崩溃:只用可达的所(需 ≥2 所才有 spread)。
- **funding 间隔异质已在 S1 处理**:各所(及同所不同币)原生结算间隔 8h/4h/1h 不一,代码按相邻
  时间戳中位推得 native interval、把每笔费率归一到 8h 当量再算 spread,artifact 记 `venue_funding_interval_ms`。
- **Hyperliquid 推迟到 S2**:实测可达但 USDC 结算(符号 `BTC/USDC:USDC`、与 USDT 是不同基差)、
  且 1h funding;需独立 USDC↔USDT 符号/基差映射,不混进 S1 的 USDT 同符号面板。

---

## 3. 分步执行(带 kill-test 门控)

```text
S1   ⚠️ KILL-TEST: 跨所 funding spread 幅度 × 持续性 vs 双所往返成本 —— 已跑,证伪
       (`cross_exchange_spread_below_gate`)。门控: 扣成本净 capture>0 + DSR/PBO 过 → 进 S2。
       实测(120d、binance/bybit/okx、6 USDT 永续、261 个 8h bucket):毛年化 spread +0.074(真实正)、
       但 break-even 仅 2.7bps/腿、pair 每 ~12h 翻转、taker 成本下净年化 −1.6、required_maker_fill
       ~0.93、DSR 0.0 → 未过。
S2   执行现实(仅当 S1 正): 实测 maker fill 率 / 双所保证金占用 / 资金划转延迟 /
       单边腿被挤爆(legging risk)/ 提现-充值再平衡成本;门控: 真实可成交净 capture 仍>0 —— 未启动。
S3   组合与 sizing(仅当 S2 正): 多标的×多所对分散、保证金效率、跨所净额对冲 —— 未启动。
S4   纸面验证(仅当 S3 正): validation_v1 once-only;过 G_paper 才谈 forward paper —— 未启动。
S5   工程化: 若要 live,需多所账户 + 跨所资金管理 + legging 执行器——独立工程轮,先单测先 paper —— 未启动。
```

每步硬门控,不证伪不前进。**开多所账户/真实资金(S5)只在 S1–S4 全过之后**,绝不提前。

> **状态(2026-06-06):L4 S1 证伪。** 跨所 funding spread 真实为正(毛年化 +7.4%),但已被套利者压到
> ~maker 成本地板(回本 2.7bps/腿)且每 ~12h 均值翻转,4 腿换手吃光毛值;taker 成本下净年化 −1.6、
> required_maker_fill ~0.93(单所 CARRY 的 maker 墙跨所重现)、DSR 0.0。对本「慢+延迟无关」操作者证伪。
> 残留口子只有 maker/返佣 HFT 那条(co-located、需多所账户),属另一种操作者 + 新基建承诺,不在本线纪律内。

---

## 4. 反过拟合 & 硬约束

- 复用 §7 / L1 已落地 harness:`_sharpe`、`compute_directional_deflated_sharpe`、
  `compute_directional_pbo`、`normalize_funding_history`、`state/` 缓存与 as-of join。
- 多重检验面是「交易所对 × 标的」:每标的的净 capture 序列作一个 trial 计入 DSR;
  同频段(8h)cells 进 PBO/CSCV。**持续性必报**:pair 每 bucket 翻转 = 换腿成本爆掉,
  spread 再大也无意义(单所 CARRY 的成本墙在跨所原样适用)。
- 硬约束全继承:live 关闭、不 forward paper、不放宽 broad gate、外部模型/AI 不进
  candidate/risk/live;不在 `discovery_pool` 调参后当 promotion;`validation_v1` once-only。
- Mac 编辑/git,WSL 生产/回测真相。

---

## 5. 全局终止条件(L4 自己的诚实退出)

若跨所 funding spread 扣实测双所往返成本后年化 capture **不显著 > 0**,或 pair 持续性太差(换腿成本主导,
required_maker_fill 趋近不可成交),或 DSR/PBO 不过,则 **L4 也按 §7 退出**,转 L5(换预测目标=波动率)
或接受研究价值停止追盈利。下一次重启仍需新的结构性输入,而非 L4 内部堆标的/堆交易所/调阈值。

> **已触发(2026-06-06):S1 净年化 −1.6、pair 每 ~12h 翻转、required_maker_fill ~0.93、DSR 0.0 = §5
> 退出条件命中。** 与 L3a 纯噪声证伪不同:跨所 spread 真实为正(毛 +7.4%/yr),绑定限制是**它已被压到
> maker 成本地板 + 残差换手过快**,4 腿往返吃光。所有者据此决策:退出 L4 转 L5/L2,或(若认为 2.7bps
> 回本贴 maker 地板值得)做 L4-S2 实测 maker fill 执行研究——但那需开多所账户(真实基建/资金,§7 所有者授权域)。
> 不在已看窗口上调 hold/hysteresis 阈值救 L4(§5 禁止的内部调参)。

---

## 6. 一句话

> §7/L3/L1 证明在「预测方向」这个游戏里,广度和量级都封死。L4 换游戏——不预测方向,赚两个
> 交易所对同一资产定价的不一致。第一刀就是它最便宜的命门:只读多所 funding 历史,量跨所 spread
> 的幅度×持续性能否跨过双所往返成本;不过则诚实退出,零券商、零下单成本。
