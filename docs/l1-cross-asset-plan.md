# L1 跨资产趋势计划：正面攻 BR(广度)

本文件是 §7 诚实止盈 + L3 证伪之后的**第二条重启线**。合法性同样来自
[profit-engineering-plan.md](profit-engineering-plan.md) §11.8 的「结构性新输入」——
L1 的结构性新输入是:**把 universe 从同涨同跌的 crypto majors 换成真正低相关的跨资产
(股指 / 债 / 商品 / FX / crypto)**,在日/周线上做时序动量(趋势跟踪 / CTA 风格)。

> 纪律不变:research-only;live 关闭、不 forward paper、不放宽 broad gate、
> `validation_v1` once-only、一轮只改一处、先写单测、先证伪再投入。

---

## 0. 为什么是 L1(接 §7 / L3 的对账)

`IR = IC × √BR`。§7 与 L3 已经反复证明:**绑定约束是 BR,不是 IC。**
- §7:crypto majors r̄≈0.63 → 有效广度 ~1.6;扩币、换频段都救不了。
- L3a:换慢数据(稳定币供给)做择时——无稳定样本外 IC。
- L3b:链 TVL 横截面找到**真实显著弱信号(IC 0.075, t=3.5)**,但 token 收益有效广度仍
  **1.68** < 逃逸阈 2.5,要求 IC 仍 ~0.15,真信号只有一半 → 广度天花板原样复现。

**唯一还没试过的杠杆是正面动 BR**:用一个**结构性低相关**的 universe。跨资产趋势是广度的
教科书来源——20–50 个跨类标的的有效广度可达 5–15(r̄ ≪ 0.30),且趋势跟踪是金融史上样本外
最稳健、最延迟无关、容量最大的策略类,**最贴本操作者优势(慢 + 耐心 + AI 慢判断)**。

---

## 1. 命门与最廉价的第一刀(S1 = 广度 kill-test)

L1 整条论点**只赌一件事:跨资产 universe 的有效广度是否 ≫ 1.6。** 若否,L1 与价量横截面
没有区别,直接证伪——**这一刀纯数据、零新场、零券商**。

```text
数据:  免费跨资产日线 EOD 面板(Tiingo)：SPY/EFA/EEM(股)、TLT/IEF/LQD/HYG(债)、
       GLD/SLV/DBC/USO(商品)、UUP(美元)、VNQ(REITs)[+ BTC 走已通的 Binance]
读数:  周线收益面板的 effective_breadth = N/(1+(N-1)·r̄)（复用 §7 的 _panel_effective_breadth）
判生死: effective_breadth > 2.5 → 广度论点成立,进 S2(ts_mom IR/DSR/PBO)
        effective_breadth ≲ 1.6 → L1 与 majors 无异,廉价证伪,转 L5
```

命令:`l1-cross-asset-breadth-scan`(已落地,research-only,无仓位、不算 IC)。

---

## 2. 数据源现实(重要的基建发现)

跨资产 TradFi **免费免-key 源从生产主机(WSL)全部不可用**(已实测):
- Stooq → 反爬 JS 挑战页;Yahoo Finance → 429 限流;FRED → 超时(网络路径被挡)。
- 可达且可用的是**需免费 key 的提供商**:Tiingo(200 实测可达,免费档 1000 req/天、
  500 标的/月,干净复权 EOD)、Alpha Vantage / Twelve Data / FMP(均可达,需 key)。

**选 Tiingo**:免费档最宽松,一次性拉满面板(≤14 标的)即落 `state/` 缓存离线复跑。
key 放 `.env`:`QOUNT_TIINGO_API_KEY=...`(即时注册、零成本、无审批)。缺 key 时命令**不崩溃**,
返回 `error=missing_tiingo_api_key` 提示。

---

## 3. 分步执行(带 kill-test 门控)

```text
S0/S1 ✅ 数据接入层 + 广度 kill-test —— 已落地;真实广度通过:21-ETF 跨资产
        r̄=0.303 / effective_breadth=2.973 > 2.5(crypto 1.6 / 13-ETF 2.477 对比),逃逸天花板
        → 要求 IC≈0.081(可达)。命门已过。
S2   ⚠️ 时序动量 IR/DSR/PBO —— 已跑;真实正 edge 但 < 门控(`tsmom_below_gate` /
        `tsmom_ensemble_below_gate`)。21-ETF TSMOM 净年化 Sharpe 0.36(ensemble)~0.42(best lb39w)、
        gross 0.55、4/5 时间折正、2022 crisis-alpha;但 < IR 门控 0.5、DSR 0.856 < 0.95、
        PBO 0.627 > 0.5 均不过。门控:扣费 IR 显著 + DSR/PBO 过 —— 未过 → 不进 S3。
S3   组合与 sizing(仅当 S2 正):风险平价 / 波动率目标,周线再平衡 —— 未启动(S2 未过)。
S4   纸面验证(仅当 S3 holdout 正):validation_v1 once-only;过 G_paper 才谈 forward paper —— 未启动。
S5   工程化:若要 live,需新券商(IBKR/期货/ETF)——独立工程轮,先单测先 paper —— 未启动。
```

每步硬门控,不证伪不前进。**开券商(S5)只在 S1–S4 全过之后**,绝不提前。

> **状态(2026-06-06,所有者确认):L1 固化为部分成功,暂停。** S1 广度过、S2 趋势真实但
> 净 Sharpe ~0.4 < 0.5 门控且 DSR/PBO 不过。三条终局路径(S5 券商 / 固化 / 转 L5)中所有者选
> **固化**:不在 sub-gate 证据上开真期货券商(§3 门控),不在已看 ETF 上堆参当重启(§5)。
> L1 是本项目第一个真实、稳健、正、经济一致的 edge,并经验证实 §2 的广度逃逸论点。暂停而非删除:
> 未来开期货券商(独立工程轮)或拿到结构性更优 universe 时,S2 门控原样适用、从 S3 续跑。

---

## 4. 反过拟合 & 硬约束

- 复用 §7 已落地 harness:`_panel_effective_breadth`、`spearman`、`_sharpe`、
  `compute_directional_deflated_sharpe`、`compute_directional_pbo`、purged-CV+embargo。
- 趋势 IC 本就低(~0.03–0.05),靠 BR 不靠 IC——所以**广度必须先证实**(S1 命门)。
- 硬约束全继承:live 关闭、不 forward paper、不放宽 broad gate、外部模型/AI 不进
  candidate/risk/live;不在 `discovery_pool` 调参后当 promotion;`validation_v1` once-only。
- Mac 编辑/git,WSL 生产/回测真相。

---

## 5. 全局终止条件(L1 自己的诚实退出)

若跨资产 universe 的有效广度**不显著超过 1.6**(S1 证伪),或广度成立但扣费后聚合 IR
不显著 / DSR/PBO 不过(S2–S4 证伪),则 **L1 也按 §7 退出**,转 L5(换预测目标=波动率)
或接受研究价值停止追盈利。下一次重启仍需新的结构性输入,而非 L1 内部堆标的/调参。

> **已触发(2026-06-06):S2 扣费 IR 不显著(净 Sharpe ~0.4 < 0.5)+ DSR/PBO 不过 = §5 退出条件
> 命中。** 区别于纯证伪(L3a 那种"无稳定样本外 IC"):L1 的 edge 真实、正、经济一致,绑定限制是
> **零售 ETF 的 edge 量级**而非方法或广度。所有者据此选**固化为部分成功 + 暂停**(非删除):承认这是
> 项目首个真 edge、保留 S2 门控,未来真期货 universe(券商,独立工程轮)或更优结构性 universe 可从
> S3 续跑。当下停止在 L1 上投入,下一次重启转 L5(换预测目标=波动率)/ L4(跨所套利)等结构性新输入。

---

## 6. 一句话

> §7 + L3 证明绑定约束是广度(majors 同涨同跌)。L1 不在 crypto 盒子里加旋钮,而是把
> universe 换成结构性低相关的跨资产,正面抬 BR。第一刀就是它最便宜的命门——量这个 universe
> 的有效广度是否 ≫ 1.6;不过则诚实退出,零券商成本。
