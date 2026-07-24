# CTA-R 估值过滤门 预注册计划 v0.1:P/E·P/B 分位剔除 kill-test

> **状态**：frozen（CTA-R blueprint/guarded，历史研究线原地保留）｜索引见 [archive/README.md](archive/README.md)｜当前事实以 [current.md](current.md) 为准。

状态:**v0.1 已实现 + J0 判死收口(2026-06-12)** · 代号 **V-GATE**(线 A · CTA-R 增量)· 见 §6 终判
上游事实:[rebuild-plan.md](rebuild-plan.md)(CTA-R 跨资产趋势主线,OOS Sharpe 0.84,诚实 ~7-9%/yr)
上游教训:`cta-r-commodity-breadth-falsified`(过门控后加广度≠加收益,edge 量级被 2020-26 窗口封在 ~0.4)

---

## 0. 纪律声明(线 A · 不是新线)

本计划是 owner 授权的、对**已验证 CTA-R 主线的单层增量**,不是新研究线,受线 A 全部铁律约束:

- **一轮只改一处** = 只加「估值过滤门」一层(不同时动 entry / vol-target / 执行)。
- **先写单测**:门 `value_gate` 走 config flag,**默认 off**;首个断言 = 门 off 时输出**逐位等于**现引擎(零回归)。
- **live 必须关闭**(`QOUNT_LIVE_ENABLE=false`);不 forward paper、不在 `discovery_pool` 上调参当 promotion。
- **过不了判据 → 判死写回本文档**,不进 candidate/paper/live,不污染已验证引擎。
- 验证链路:本地 unittest → `scripts/sync-to-wsl.sh --install` → `scripts/run-wsl-tests.sh` → 研究命令 → artifact 落 `state/research_runs` → 写回 current.md / update-log.md(**仅当判活**)。

---

## 1. 核心假设(V-GATE)与蓝图对账

**假设**:在 CTA-R 的多窗口 TSMOM 动量信号之上,叠加一个**估值过滤门**——按月剔除滚动 P/E、P/B 历史分位 ≥ θ(默认 80%)的权益标的——能在扣同样费用后,对现无门引擎产生**正的风险调整增量**(躲过「贵了还追」的增长陷阱回撤)。

**蓝图四引擎对账(关键:三个半已建,这一刀只加半个)**:

| 蓝图引擎 | CTA-R 现状(`cta_sim.py` / `cta_portfolio.py`) | 本计划动它吗 |
|---|---|---|
| 1 标的池 | 8-ETF 已建:510300/510500/159915/510050/518880/511010/513100/513500 | 否 |
| 2 信号·动量 | `_target_weights` 多窗口 TSMOM 集成(`sign(P_t/P_{t-L}-1)` 均值),比单根 SMA200 稳健 | 否 |
| **2 信号·估值门** | **无** | **✅ 唯一新层** |
| 3 风控/仓位 | target-vol parity(`vol_lookback_days`=63)+ `max_weight` + 回撤降杠杆(`dd_threshold`/`dd_factor`) | 否 |
| 4 执行/会计 | T+1 成交、滑点、equity-normalized 复利、paper 账本、equity 曲线 | 否 |

> 蓝图把它写成「全新系统」,但 CTA-R 已经是「动量触发 + vol-parity + 熔断 + equity-normalized + T+1」的完整体,且 walk-forward 过了。**真正的新增量只有估值门。** 所以这是单层 kill-test,不是重建。

---

## 2. 三个致命先验风险(可能在接 API 前就判死)

跑前必须正视——这一层的先验是**伤害**,不是帮助:

**R1(几乎判死前提)· 估值门对真正赚钱的半个篮子是瞎的。** 8 sleeve 里:
- 黄金ETF(518880)、国债ETF(511010):**没有 P/E·P/B**(非权益),估值门**物理上无法作用**。
- 纳指(513100)、标普(513500)QDII:有估值但 **Tushare 不覆盖**美股指数。
- 估值门只能管 **4 个 A股权益 sleeve**(沪深300/中证500/创业板/上证50)。
- 而 `cta-r-rebuild-authorized` 记录:**近 4 年 A股股票几乎归零,收益靠金/债/海外轮动接力**。
- ⇒ **估值门恰好对扛轿子的那半个篮子失明,只能给近年贡献 ~0 的 A股子篮加滤网。** 这条本身就可能让整件事失去意义。

**R2 · 估值门与动量天然对抗。** 趋势系统里「涨到 80 分位以上」恰是动量最强标的——它贵*因为*它在涨。θ=80% 截断会**机械砍掉跑最猛的赢家**。必须能区分「门加了 alpha」还是「只是砍了赢家碰巧躲过一次回撤」。

**R3 · 广度/加层非绑定约束(已证伪先验)。** `cta-r-commodity-breadth-falsified`:过门控后加信号层 ≠ 加收益;edge 量级被 2020-26 窗口封顶。估值门是**减法门**,只删机会——最好情况是「风险调整略好」,**不可能加收益**。天花板先认清,不要期待头条数字。

---

## 3. 工程落点

**3.1 代码(零回归优先)**
- `cta_sim.SimConfig` 加字段:`value_gate: bool = False`、`value_gate_pct: float = 0.80`、`value_gate_lookback_days: int = 756`(~3y 分位窗)。
- `_target_weights` 末端、vol-target **之前**插一个纯函数 `_apply_value_gate(weights, pe_panel, pb_panel, t, config)`:对每个**有估值**的权益 sleeve,算其 P/E(及 P/B)在 `value_gate_lookback_days` 内的分位;≥ θ 则该 sleeve 权重置 0;无估值的 sleeve(金/债/QDII)**原样放行**(显式 pass-through,不是 NaN 漏判)。
- 月频重算门状态(避免日频抖动 + 前视),门状态在月内 carry。
- **数据缺口策略**:某权益 sleeve 估值序列缺失 → 该 sleeve **不被门管**(保守:缺数据不等于贵),并在 artifact 里计数,防止「靠丢数据躲过回撤」的假阳性。

**3.2 数据(仅门判活后才接,且只接这一项)**
- 源:Tushare `index_dailybasic`(指数每日 PE/PB)。ETF→标的指数映射:

  | ETF | 标的指数(Tushare ts_code) |
  |---|---|
  | 510300.SH 沪深300 | 000300.SH |
  | 510500.SH 中证500 | 000905.SH |
  | 159915.SZ 创业板 | 399006.SZ |
  | 510050.SH 上证50 | 000016.SH |
  | 518880 / 511010 / 513100 / 513500 | 无映射(金/债/QDII,门放行) |

- **前视/PIT 纪律**:PE 取**收盘后公布值**,信号在 T 用 ≤ T-1 的估值;绝不用未来修正值。研究用**独立缓存**(`state/research_cache/value_gate/`),不碰生产 glob。
- **token 安全**:Tushare token 走环境变量 `TUSHARE_TOKEN`,**不写进文件、不 commit**。(你已明文贴出该 token,建议先 revoke 重发。)

---

## 4. 预注册判据(跑前锁死,采纳蓝图三关)

门要判**活**,必须**全部**通过;任一不过 → 判死:

**J0 · 资格门(最先跑,可能直接终结)。** 量化 R1:在已建 A股 walk-forward 上,统计估值门实际能作用的 sleeve-天数占比,以及「被门剔除的那部分」历史上的收益贡献。若门只能触及近年贡献 ~0 的 A股子篮、对总 equity 影响 < 噪声 → **直接判死,不接 Tushare**。

**J1 · 正增量门。** 同一条 A股 walk-forward、扣**同样**费用/滑点,门 on 对门 off 必须:OOS 年化或 Sharpe 有**真实正增量**(非噪声内),且不是靠少数几次幸运回避。

**J2 · 参数平原(反过拟合)。** θ ∈ {70%, 80%, 90%} × 分位窗 ∈ {1y, 2y, 3y} × 动量窗 {150/200/250}。若 EV 在网格内转负或出现数量级断层 → 过拟合,作废。

**J3 · 尾部压力。** 强制在 2015 A股股灾、2018、2020、2022 股债双杀四段窗口跑,门 on 不得让 MaxDD 比门 off **更差**(估值门若真有价值,这里应是它发光处;若无差别甚至更差 ⇒ 它没在防尾部)。

**J4 · 摩擦放大 ×3。** 滑点/费率 ×3 重跑,门 on 的净增量必须**仍为正**——证明赚的是结构,不是在估值门换手里收噪声。

---

## 5. 实施顺序(严格)

1. **先写单测,不接任何 API**:
   - `test_value_gate_passthrough`:`value_gate=False` 时 `_target_weights` 输出逐位 == 现引擎。
   - `test_value_gate_zeroes_expensive`:合成 PE 序列下,≥θ 的权益 sleeve 被置 0。
   - `test_value_gate_passes_through_nonequity`:金/债/QDII 在门 on 时权重不变。
   - `test_value_gate_missing_data`:估值缺失的 sleeve 不被门管,并被计数。
2. **跑 J0 资格门**(用合成 + 已有价格,**不需 Tushare**):验 R1。**大概率在此终结。**
3. J0 若过,才接 Tushare `index_dailybasic`(独立缓存),跑 J1–J4。
4. 全过 → 写回 current.md / update-log.md + paper;任一不过 → 判死写回本文档 §6。

---

## 6. 结论记录

### 第 1 步 — 单测 + 门实现(完成 2026-06-12)
- 实现:`cta_sim.py` 加 `value_gate` / `value_gate_pct` / `value_gate_lookback_days`(默认 off);纯函数 `_percentile_rank`、`_value_gated`(no_data/missing/expensive/ok 四态,PE/PB OR);门插在 `_target_weights` gross 归一化前;`valuation` 串过 `run_paper_sim`。
- 单测:`tests/test_cta_value_gate.py`(13 例)——passthrough 逐位等于现引擎 / 砍贵的 / 放行非权益 / 缺数据计数 / PB 单独可门 / run_paper_sim 端到端门 off 恒等。
- 回归:`cta_sim + cta_portfolio + cta_data + value_gate` 共 **100 测试全过**,零回归。

### 第 2 步 — J0 资格门
**J0 (a) 结构覆盖(完成,纸面判决,零数据)** `scripts/research/cta_value_gate_j0.py --structural-only`:

| 组 | sleeve | 门 |
|---|---|---|
| 可达(有 Tushare 指数 PE/PB) | 510300/510500/159915/510050(全 cn_equity) | **REACH 4/8** |
| 全瞎(PE/PB 未定义) | 518880 金 / 511010 债 / 513100 纳指 / 513500 标普 | **BLIND 4/8** |

⇒ 门结构上只能作用于半个篮子(4 个 A股权益),金/债/QDII 物理触不到。R1 前提的前半段**已坐实**。

**J0 (b) 实证贡献 + 终判 = FAIL(WSL 实测,2026-06-12)** `.venv/bin/python scripts/research/cta_value_gate_j0.py`(2014-01-15→2026-06-10,3008 天,validated long-only book):

| 组 | 2012-2022 | 2023-2026 |
|---|---|---|
| 门可达(A股权益:159915/510050/510300/510500) | **+64.1%** | **+1.8%** |
| 门全瞎(金/债/QDII) | +29.7% | **+23.9%** |
| 近年总贡献 | | **+25.7%** |

终判数字:2023-26 总贡献 +25.7% 里,**门能滤的只占 +1.8%(7%)**,门够不着的占 +23.9%(93%)。

**V-GATE 判死(收口)**:门结构上只能作用 4/8 sleeve(A股权益),而近年收益 93% 来自门完全失明的金/债/QDII。**滤一个近年 ~0 的子篮,对总 EV 无可能产生有意义增量**——J0 内置判据(reachable 占总 <20%)直接命中。**不接 Tushare(8000 积分一分未花)**,不进 J1–J4。

**根因(=R1):** 收益的 regime 已从 A股权益(2012-22 贡献 64%,510500 中证500 单挑 43%)转到金/债/海外(2023-26 贡献 24%)。估值门是为「贵的权益」设计的滤网,但**钱已经不在权益里了**。这是 `cta-r-commodity-breadth-falsified` 元结论的又一次重演:**绑定约束不是「缺一层滤网」,是 2020-26 窗口里 edge 量级本身被封顶 + 收益靠少数非权益 sleeve 接力**;再加任何只作用于权益的减法层,都只能在近年贡献 ~0 的篮子里做无用功。

**资产留存:** `value_gate` 门(默认 off,100 单测护住零回归)+ `_value_gated` 纯函数 + `cta_value_gate_j0.py` 归因脚本定性为**可复用资产**,不删除;若未来 A股权益 regime 回归(reachable 组贡献重新抬头),可原地开 `value_gate=True` 重跑 J0→若 PASS 再续 J1–J4。**本轮不再推进。**
