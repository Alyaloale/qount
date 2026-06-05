# qount 盈利工程方案（架构天花板与现代量化 ML 升级）

创建时间：2026-06-05

这份文档不替代任何现有文档，它解决的是一个不同层级的问题。

- [current.md](current.md)：当前事实与硬边界。
- [holdout.md](holdout.md)：`discovery_pool` / `validation_pool_v1` 与 `G_paper` / `G_live`。
- [optimization-plan.md](optimization-plan.md)：T-A..T-J，**实验流程与现有架构内的清理/挤压**。
- [profit-research-plan.md](profit-research-plan.md)：WS-1..WS-4，**现有链路里找正期望切片**。

T-A..T-J 和 WS-1..WS-4 已经走完一遍，结论一致：当前是一个"alpha 稀疏 + 评测窗口太碎 +
AI 全 hold + setup_model 线性"叠加成的**本地最小值**。本文件不再在这个最小值里调参，
而是回答两个更上层的问题：

1. 为什么把 T-A..T-J 和 WS-1..WS-4 全部做完，当前架构形态在**统计上**仍然几乎不可能
   证明稳定盈利？（第 1 节，结构性诊断）
2. 用当今主流量化方法论 + 现代 AI 模型，目标架构应该长什么样、按什么顺序迁移？
   （第 2–4 节）

读法：先读第 1 节的天花板论证（这是全文前提），再读第 2 节目标架构，再按第 3 节模块
逐个看落点。第 4 节是路线图，第 5 节是反过拟合验证，第 6 节是继承 + 新增的硬约束。
**第 9 节是 2026-06-05 评审后修订的详细分步执行计划（S0–S5），落地时以第 9 节为准。**

> 2026-06-05 评审决策（已由项目所有者确认）：
>
> - **依赖哲学**：允许引入完整 ML 栈（numpy / sklearn / lightgbm 等），但**只作为
>   research optional extra**，live / run-once 路径保持纯 Python。见 §9 的 S0.1。
> - **执行节奏**：严格沿用项目铁律"一轮只改一处 + 先单测"，按 §9 的 S0→S5 顺序增量推进，
>   **不做一次性大爆炸重构**。
> - **第一刀是 kill-test**：在投入重模型前，先用最便宜的纯 Python harness 测多币横截面 IC；
>   IC 不成立则整个重构不做（§9 S1）。这是评审新增、原 §4 路线图据此修订。
>
> 2026-06-05 **终审追加决策**（更深一层）：
>
> - **解除 5m 假设**。整套系统（含所有现有文档）默默把"5m bar + 单一择时开仓"当成给定，
>   而这从未被验证。终审判断：**5m 大概率是本系统最差的频段**（与做市商/HFT 正面竞争、
>   本系统是秒级延迟的 cron+代理+AI-in-loop，没有任何低延迟优势）。
> - **频段（5m/1h/4h/1d）与策略族（横截面动量/反转、趋势、资金费率 carry）从此是
>   由证据选择的决策变量，不是给定**。S1 从"测 5m IC"升级为"频段 × 策略族 选择扫描"。
> - 以盈利为唯一目标：**最可能真盈利的是最简单的 funding carry（结构性现金流，非预测），
>   不是最花哨的 5m GBDT**。详见 **§10 终审修订**，落地以 §10 为准、其次 §9。

本文件**不放宽任何现有硬约束**：live 关闭、不 forward paper、不放宽 broad gate、
不在 `discovery_pool` 上调参后当 promotion、Kronos / 任何外部模型不进 candidate/risk/live。
所有新方法仍然必须先过 [holdout.md](holdout.md) 的 `G_paper`。

---

## 1. 结构性诊断：当前架构的天花板

### 1.1 一句话

当前系统在用一个**极低 breadth（广度）**的形态，去追一个**极稀疏、极薄边际**的 alpha，
并把最终决策权交给一个**系统性过度保守**的通用 LLM。这三件事相乘，决定了无论怎么调阈值，
统计显著的盈利都几乎不可达。这不是某个 bug，是架构选型的数学后果。

### 1.2 用主动管理基本定律量化天花板（这是全文最重要的一段）

主动管理基本定律（Grinold's Fundamental Law of Active Management）：

```text
IR ≈ IC × sqrt(BR)
```

- `IR`：信息比率（策略风险调整后超额收益的稳定性）。
- `IC`：信息系数（单次预测与实际结果的相关性，衡量"信号有多准"）。
- `BR`：breadth，**每年独立下注次数**。

把当前 qount 代进去：

- `current.md`：946 cycles → 4 fresh open，集中在 ≤2 个窗口。按真实成交密度，ETH-only /
  5m / 单仓 / 6-bar horizon 一年的**独立**下注数量级是 **几十次**，乐观估计 BR ≈ 50。
- 这些开仓的 `final_expected_edge_pct` 在 `0.0020..0.0039`，post-cost 边际贴着 0 线，
  对应的 IC 极低。

结论：`sqrt(50) ≈ 7`。要让 IR 达到一个"能证明、能上线"的水平（比如 IR ≈ 1，对应
约 1 的年化夏普），单次预测的 IC 需要高到 `≈ 0.14`。**在 5m 加密噪声里，单一资产、
单一 horizon 上长期维持 IC=0.14 是不现实的**——顶级 CTA 在更慢周期上的 IC 通常也只有
0.02–0.05，靠的是成百上千的 breadth 把它放大。

这就是 `holdout.md` 里"原 G1/G2 在当前 alpha 密度下数学上不可达"的**根因**，也是
为什么 `optimization-plan.md §2.1` 不得不把 promotion 从"窗口数"改成"累计成交样本数"——
但改计数口径只是承认了样本不够，没有解决样本为什么不够。

**真正的杠杆是把 `BR` 提高一到两个数量级，而不是继续在 BR≈50 上把 IC 抠到 0.14。**
要把 BR 从 ~50 提到 ~5000，路径只有三条，且可以叠加：

1. **横截面扩币**：从 1 个资产到 N 个资产，BR 近似 ×N（前提是信号在资产间不高度相关）。
2. **持续小仓位下注**：从"罕见强 setup 才开 1 笔"到"每根 bar 都对每个资产给一个
   conviction 分并连续调仓"，把"下注"从离散事件变成连续过程。
3. **多 horizon / 多信号正交叠加**：不同 horizon、不同 setup family 当作弱相关的独立信号
   合成，而不是互斥地择一。

当前架构同时放弃了这三条：单币、罕见离散开仓、单 horizon 择一。所以它的 BR 被锁死在
最低档。**这是天花板的第一根柱子。**

> 终审补充（见 §10.2）：上面 `required IC ≈ 0.14` 是**在 5m 单币**下算的。一旦换到
> **日频横截面（~10 币）**，有效独立下注数升到数百量级，`required IC` 降到约 **0.06**——
> 落进加密横截面动量文献的 IC 区间（0.03–0.08）。**换频段+扩广度比任何模型升级都更能
> 破这根柱子**，所以终审把"频段选择"放到了模型升级之前（§10）。

### 1.3 第二根柱子：标注（labeling）与目标错配

- `setup_model.py` 用固定 `horizon_bars`（默认 6，eth-only profile phase6）做 target，
  即"未来固定 N 根 bar 的 post-cost edge"。
- 但 `profit-research-plan.md §2` 自己反复确认：强子切片的 edge 普遍在 **h12/h24** 才最强
  （`pullback_sma_fast_gt008` h6=+0.0048 / h12=+0.0089）。
- 同时实际持仓由 trailing（`arm=0.0018 / retrace=0.003`）+ `min_hold_bars` 决定，是
  **路径依赖**的退出，和"固定 N 根 bar 的收益"这个训练目标根本不是同一个量。

也就是说，模型训练的标签、风控实际实现的退出、和真实想捕捉的 edge，是**三个不同的目标**。
这会系统性地让模型学到的东西在实盘链路里被路径依赖退出吃掉（WS-1 h12 探针就是典型：
realized 反而更差，收益全留在未平仓浮盈里）。

主流答案是 **triple-barrier labeling**（López de Prado, *Advances in Financial Machine
Learning*）：标签由"先碰到止盈线 / 止损线 / 时间线哪一个"决定，标签天然路径依赖、天然和
退出规则同构。这把"训练目标 = 退出规则 = 想捕捉的 edge"三者统一。**这是天花板的第二根柱子。**

### 1.4 第三根柱子：模型表达力

- `setup_model.py:106` 是手写 GD 的 16 维线性 ridge（`_fit_linear_regression`）。
- discovery 反复证明 alpha 在**交互**里（`phase × sma_fast_bin × return_24bars` 等）。
- T-C 的 v2 用**手工交互项**（`SETUP_EDGE_MODEL_V2_EXTRA_FEATURE_NAMES`，11 个手搓 bin
  乘积）尝试补救，结论是 lift 不够、`strong_favorable=0`。

手工交互必然失败，因为它要求人**先猜对**哪些交互重要、阈值切在哪。这正是梯度提升树
（GBDT：LightGBM / XGBoost / CatBoost）存在的理由：树天然表达高阶交互和非线性分桶，
不需要手猜阈值。继续在线性 ridge 上加手工乘积，是在用最弱的工具做最需要表达力的事。
**这是天花板的第三根柱子。**

### 1.5 第四根柱子：LLM 被放在错误的位置

- `prompts/decision_prompt_v1.txt` / `system_prompt_v1.txt` 有**几十条** "prefer
  waiting" / "default wait" / "prefer hold" 规则。
- `optimization-plan.md §2.3`：WS-4 step 3 readiness 通过却 0 成交，失败点是 **AI 全 hold**，
  不是 risk。`wf-mar06` 的正收益样本里至少 1 笔是用 deterministic override **绕过 AI**
  才拿到的。
- `current.md` 的诚实读数：AI hold 在大多数样本上是**对的**（candidate-aligned 平均
  future return 为负），但在少数强 setup 上**系统性错**。

这说明把通用 LLM 当作"对薄边际数值机会的最终 buy/sell gate"是错配。LLM 不擅长对
post-cost ±0.001 量级的统计边际做概率化裁决（它没有校准的概率输出），但它擅长**否决明显
不该做的交易**、**总结上下文/新闻/regime**、**给出可解释的反对项**。当前 prompt 把它用在
了它最不擅长的那一档。**这是天花板的第四根柱子。**

### 1.6 诊断小结

| 柱子 | 当前形态 | 后果 | 主流解法（第 3 节展开） |
| --- | --- | --- | --- |
| 1 广度 BR | 单币/罕见离散/单 horizon | IR 上限被锁死 | 横截面扩币 + 连续 conviction sizing |
| 2 标注 | 固定 horizon，与退出错配 | 训练目标≠实盘目标 | triple-barrier + meta-labeling |
| 3 表达力 | 16 维线性 ridge + 手工交互 | 学不到交互 alpha | GBDT + purged CV |
| 4 LLM 位置 | 当最终薄边际 gate | 系统性 over-hold | 降级为 veto / regime / 特征层 |

四根柱子是**乘性**的：只修一根（比如只上 GBDT）不会破局，因为 BR 仍然是 50、LLM 仍然全 hold。
所以第 4 节的路线图是**按依赖顺序协同推进**，不是单点替换。

---

## 2. 目标架构

把当前链路：

```text
closed 5m bar -> snapshot -> candidate_filter -> AI(最终gate) -> validate -> risk -> executor -> journal -> review
```

演进为一个标准的现代量化决策栈（每一层职责单一、可独立验证）：

```text
            ┌─────────────────────────────────────────────────────────────┐
            │ L0 数据与特征层                                                │
            │   多币 OHLCV + 微结构(funding/basis/盘口) + 时序基础模型特征    │
            └───────────────┬─────────────────────────────────────────────┘
                            ▼
            ┌─────────────────────────────────────────────────────────────┐
            │ L1 主模型 (primary): GBDT 方向/edge 预测                        │
            │   triple-barrier 标签, purged+embargo CV, 每资产每根bar打分     │
            └───────────────┬─────────────────────────────────────────────┘
                            ▼
            ┌─────────────────────────────────────────────────────────────┐
            │ L2 元标注 (meta-label): GBDT 二分类"这一笔该不该做+多大把握"     │
            │   输出校准概率 p(profit) —— 取代 LLM 当最终 gate                │
            └───────────────┬─────────────────────────────────────────────┘
                            ▼
            ┌─────────────────────────────────────────────────────────────┐
            │ L3 横截面组合构造: 对 N 币按 conviction 排序, 连续目标权重       │
            │   分数 Kelly / 风险预算 sizing —— 把 BR 从 ~50 提到 ~数千        │
            └───────────────┬─────────────────────────────────────────────┘
                            ▼
            ┌─────────────────────────────────────────────────────────────┐
            │ L4 LLM veto/解释层 (非数值 gate):                              │
            │   仅在能给出具体反对项时否决; 输出 regime 标签与可读理由         │
            └───────────────┬─────────────────────────────────────────────┘
                            ▼
            ┌─────────────────────────────────────────────────────────────┐
            │ L5 风控执行 (复用现有 risk_engine bottom_line + executor)       │
            │   底线约束 + maker/post-only 执行 + 审计链                      │
            └─────────────────────────────────────────────────────────────┘
```

关键设计原则：

- **职责单一**：方向预测（L1）、是否下注（L2）、下多少/分散到哪（L3）、否决与解释（L4）
  彻底分离。当前架构把 L1/L2/L4 全揉进一个 LLM prompt，所以无法独立验证、无法定位失败点。
- **概率化而非二元**：L2 输出**校准过的概率**，L3 据此连续 sizing。当前是"开/不开"的二元，
  丢掉了 conviction 这个维度，也就丢掉了 sizing alpha。
- **现有资产全部复用**：`risk_engine` 的 bottom_line、`executor`、SQLite 审计链、
  `backtest`/`walk-forward`/`review` 全部保留为 L5 和验证框架。setup_model 不是删除，
  而是被 GBDT 在同一接口（`predicted_edge_pct / confidence_ratio / quality`）下替换实现。
- **LLM 不被丢弃，而是搬到它擅长的位置**（L4）。

---

## 3. 模块级方案

每个模块给：动机（对应哪根柱子）→ 主流做法 → 在 qount 的落点 → 验证口径 → 不破坏的硬约束。
模块编号 P1–P7，和 optimization-plan 的 T-x、profit-research-plan 的 WS-x 正交，可交叉引用。

### P1 — 标注体系：triple-barrier + meta-labeling（修柱子 2 + 4）

**动机**：固定 horizon 标签与路径依赖退出错配（§1.3）；LLM 当最终 gate 系统性 over-hold（§1.5）。

**主流做法**（López de Prado, AFML 第 3–4 章）：

- **Triple-barrier**：对每个候选时点，设上轨（止盈，按波动率 σ 缩放）、下轨（止损）、
  垂直轨（最大持仓 bar 数）。标签 = 先触哪条轨。这让标签天然包含"赚多少、亏多少、多久"。
- **Meta-labeling**：用一个**主模型**（L1）决定方向，再用一个**二级模型**（L2）只回答
  "在主模型已经给出方向的前提下，这一笔做了会不会盈利"，输出概率 p。二级模型的正样本是
  "主模型方向正确且触上轨"，负样本是"触下轨"。这把"该不该下注"变成一个有标签、可校准、
  可回测的**监督学习问题**——正好是当前用 LLM 硬扛、且扛不好的那一档。

**在 qount 的落点**：

- 新增 `src/qount/labeling.py`：triple-barrier 标签生成，σ 用现有 `range_pct` /
  ATR 类指标缩放（特征已在 snapshot 里）。
- `setup_model.py` 的 target 从"固定 horizon edge"切到 triple-barrier 收益/标签，
  作为研究开关（`--label-scheme triple_barrier`），v1 固定 horizon 保留为默认。
- 新增 L2 meta-label 模型文件 `src/qount/meta_label_model.py`，接口对齐现有 setup_model
  的 `predicted_edge_pct / confidence_ratio / quality`，但语义是 p(profit)。
- **LLM 降级**：meta-label 概率成为最终 gate；LLM 移到 L4（见 P5）。这正是
  `optimization-plan.md §2.3` 的 v3_veto_only 思路，但用**校准的监督模型**取代
  prompt 措辞，从根上解决 over-hold。

**验证口径**：在 `discovery_pool` 训练 L1+L2，在 `validation_pool_v1` once-only 比较
"meta-label gate vs 现有 AI gate"的 realized return / hold rate / missed move。
必须满足：meta-label gate 在 holdout 上 hold rate 下降且 realized 不变差。

**硬约束**：标签方案切换只在研究命令；live / run-once 不变直到过 `G_paper`。
meta-label 的概率阈值写进单测冻结，不在 validation 上事后调。

> **2026-06-05 评审修正（样本饥饿）**：meta-label 不能用"已执行交易"训练——系统总共只开过
> 4 笔仓，正样本几乎为零，监督学习无从谈起。正确做法是用**全体候选时点的 triple-barrier
> 结局**当标签（每根 bar 每个候选方向都有一个"若按规则进场会触上轨还是下轨"的 label），
> 而不只是真实成交。这把"判断这一笔交易"重述为"判断这一类候选状态"，样本量从个位数
> 扩到数千。代价是 label 与"真实下单后的滑点/部分成交"有差距，需在 §9 验证里单列。

### P2 — 主模型升级：GBDT + 严格 CV 替代线性 ridge（修柱子 3）

**动机**：alpha 在交互里，线性 ridge + 手工交互（T-C v2）表达不出来（§1.4）。

**主流做法**：

- **LightGBM / XGBoost / CatBoost** 做 `predicted_edge_pct` 回归或方向分类。树模型天然
  表达 `phase × sma_fast × return_24bars` 这类高阶交互，不需要手猜阈值——这正是 T-C v2
  手工交互失败的原因。
- **Purged K-Fold + Embargo CV**（AFML 第 7 章）：金融时序样本有重叠 horizon，普通 CV 会
  泄漏。purge（剔除与测试集 label 重叠的训练样本）+ embargo（测试集后留空档）是标准做法。
  这也直接强化了团队最在意的反过拟合纪律。
- **特征重要性 + SHAP**：树模型给可解释的特征贡献，帮助把"哪些交互真的有 edge"
  从 T-C 的手工猜测变成数据驱动，回填到 candidate_filter 的窄 gate 设计。

**在 qount 的落点**：

- `setup_model.py` 抽象出 `SetupModel` 接口（`fit / predict_edge / quality`），现有
  ridge 作为 `v1`，新增 `v3_gbdt` 实现。保持 `setup_model_version` 开关语义（已有
  `v1` / `v2_interactions` 的先例，第 134–142 行）。
- 训练/评估复用现有 `setup-model-compare`（chronological split），新增 purged-CV 评估口径。
- 依赖（2026-06-05 评审修正）：当前代码库是**刻意的零数值依赖纯 Python**
  （`pyproject.toml` 只有 ccxt + openai，`setup_model.py` 手写 GD ridge 就是因为没有
  numpy），运行环境是 **Python 3.14**。已确认采用完整 ML 栈，但必须满足：
  (a) ML 依赖放进 `[project.optional-dependencies].research`，live / run-once 不依赖它们；
  (b) 先**验证 numpy / sklearn / lightgbm 是否有 cp314 wheel**，没有则 fallback 到
  HistGradientBoosting（仅 numpy+sklearn）或为研究单独建 3.13 venv（见 §9 S0.1）；
  (c) WSL 生产节点同步安装走 `scripts/sync-to-wsl.sh`，并跑 import smoke。

**验证口径**：先离线 sanity（`optimization-plan.md §2.4` 已定义）——对现有 4 笔正收益开仓
的预测均值 ≥ v1；再在 `validation_pool_v1` 上比 top-decile post-cost lift 与校准曲线。
GBDT 不优于 v1 则不替换主线（接受现实，转 P6 时序基础模型 overlay）。

**硬约束**：GBDT 走和 v2 完全一样的研究隔离路径；不替换主线 setup_model 直到 holdout 证明
优于 v1；模型可解释性（SHAP/特征重要性）必须 dump 进 artifact，禁止黑箱进 gate。

### P3 — 广度扩张：横截面多币排序（修柱子 1，最大杠杆）

**动机**：BR≈50 锁死 IR 上限（§1.2）。这是**单点改动里杠杆最大的一条**。

**主流做法**（加密 quant 主线）：

- **Cross-sectional ranking**：每根 bar 对 universe（如 BTC/ETH/SOL/XRP/BNB/... top-N
  流动性永续）用同一个 L1+L2 模型打分，做多分数最高的、做空分数最低的，或纯多头取 top-k。
  这是把 BR 从"单币罕见开仓"提到"每根 bar × N 币"的标准手段。
- **市场中性 / beta 对冲**：横截面多空天然抵消大盘 beta，把信号从"猜 BTC 涨跌"变成"猜
  相对强弱"，后者的 IC 更稳定、更接近真正的 alpha。
- **相关性去冗余**：对高度相关的币（如 ETH/BTC）做风险预算，避免 BR 被相关性虚高。

**在 qount 的落点**：

- 这正是 `optimization-plan.md §2.11 / T-H` 的"多币 paper-only 独立 track"，但本文件
  **把它从'后做'提级为与 P1/P2 并列的主线**——因为 §1.2 的定律说明：ETH-only 单币几乎
  数学上不可能过 `G_paper`，把多币无限挂在 ETH-only 之后等于把整个项目锁死。
- 复用已存在的 `setup_edge_model_multi_symbol.json` 和 `MULTI_RECLAIM_SMA_SYMBOLS`
  （`setup_model.py:87`）。`max_open_positions` 从 1 提到 k（研究 profile，不动 live）。
- 新增横截面组合构造层（L3 的雏形）：`src/qount/portfolio.py`，输入每币 conviction，
  输出目标权重；先在 backtest/walk-forward 里跑，不进 live。

**验证口径**：独立 `G_paper_multi`（holdout.md 已留口子）：累计 traded ≥ 20（多币下很容易
达到，这本身就证明了 breadth 论点）、sum_realized > 0、去掉贡献最大单币后仍 > 0、
去掉贡献最大窗口后仍 > 0（继承 G7 思想，unit 改为币×窗口）。

**硬约束**：多币 walk-forward 必须用 multi-symbol setup_model，不用 ETH-only 的；
多币不复用 ETH-only 的窄 gate 和 deterministic override（`optimization-plan.md §2.11`
已要求显式断言）；多币不开 live、不 forward paper 直到 `G_paper_multi` 过。

> **2026-06-05 评审修正（广度放大符号 + 加密同涨同跌）**：广度只放大 IC 的**绝对值**，
> 不改它的**符号**。如果信号本身后成本 IC 为负（团队已证 broad setup 后成本期望为负），
> 加币只会让你**更显著地确认在亏钱**。因此 P3 **必须硬门控在 §9 S1 的 kill-test 跑出
> 横截面正 IC、且 S2 模型有正 lift 之后**才启动，绝不先扩币后找信号。另外加密永续高度
> 同涨同跌（都跟 BTC），N 个币的**有效**广度远小于 N，"提两个数量级"是上界；现实预期
> 是 5–10 倍，组合层要做相关性去冗余/风险预算，不能按裸 N 计 breadth。

### P4 — Sizing：校准概率 + 分数 Kelly（修柱子 1 的连续下注维度）

**动机**：当前是"开/不开"二元 sizing，丢掉 conviction。§1.2 的连续下注路径需要 sizing。

**主流做法**：

- **概率校准**：L2 meta-label 的原始分用 isotonic / Platt 校准成可信概率 p。
- **分数 Kelly**：仓位 ∝ `f* × (edge / variance)`，f* 取保守分数（0.2–0.5 Kelly，
  实务标准，避免全 Kelly 的高破产风险）。薄边际样本自动得到小仓位、强边际得到大仓位——
  这恰好回应 `profit-research-plan.md` 的"edge 贴 0 线没有安全边际"：不再二元拒绝薄边际，
  而是给它一个**小到无所谓**的仓位，把决策从离散变连续。
- **波动率目标（vol targeting）**：组合层按目标年化波动反缩放总暴露，是 CTA 标准件。

**在 qount 的落点**：

- L3 `portfolio.py` 里实现；现有 `size_pct` 语义（合约下是 pre-leverage margin fraction）
  保留，sizing 由模型概率驱动而非 LLM 提议。
- `risk_engine` 的 bottom_line（max size / exposure / 最小名义）作为**上界裁剪**保留不变。

**验证口径**：在 holdout 上比"连续 Kelly sizing vs 固定 size_pct"的 realized return 和
max drawdown；要求风险调整后（return/MDD 或 Sharpe）改善，不只看绝对收益。

**硬约束**：Kelly 分数上限硬编码 ≤ 0.5 且写进单测；任何 sizing 输出仍过 risk_engine
bottom_line 裁剪；不因 sizing 放宽任何 entry gate。

### P5 — LLM 重定位：从最终 gate 到 veto / regime / 特征层（修柱子 4）

**动机**：LLM 在薄边际数值裁决上 over-hold（§1.5），但在否决/上下文/解释上有价值。

**主流做法**（当前 LLM-in-trading 的稳健范式）：

- **LLM 不做最终数值 gate**。最终 gate 是 L2 校准概率（P1）。
- **LLM 作为 hard veto**：只有当 LLM 能给出**具体、结构化**的反对项（如 "terminal
  washout: bar 收在区间下沿 + volume 3×"）时才否决，且 veto 必须落成可单测的结构化字段，
  不是自由文本"prefer waiting"。这把现有 prompt 里几十条软性 "prefer waiting" 收敛成
  少量**可验证的硬反对项**。
- **LLM 作为 regime/上下文特征**：用 LLM 把新闻、资金费率异动、宏观日历等**非结构化或
  跨源信息**压成离散 regime 标签（trend / chop / stress / event），喂给 L1 GBDT 当特征。
  这是 LLM 真正的信息增量来源，而当前 prompt 完全没用到。
- **LLM 作为解释器**：对 L1–L3 的最终决策生成人类可读理由，写进 journal，便于复盘——
  把当前"LLM 既决策又解释"拆成"模型决策、LLM 解释"。

**在 qount 的落点**：

- `ai_client.py` / `orchestrator.py`：LLM 调用从"产出 action"改为"产出结构化 veto +
  regime 标签 + 解释"。decision schema（`decision_schema.py`）相应新增 `veto`、
  `regime`、`objections[]` 字段。
- prompt v4：删除几十条软 "prefer waiting"，改为"仅在命中以下可枚举硬反对项之一时
  veto，否则放行模型决策"。这把 prompt 从"风格"变成"规则集"，可回归测试。

**验证口径**：在 holdout 上比"模型 gate + LLM veto" vs "模型 gate 无 veto" vs "现有
LLM gate"。要求新组合的 realized ≥ 模型 gate 单独，且 max drawdown 不更差（证明 veto
确实只砍坏交易）。

**硬约束**：LLM 不能把模型已否决的交易改成放行（veto 只能减少交易，不能增加）；
regime 特征作为 L1 输入要做泄漏检查（只用决策时点可得信息）；LLM 不确定性已知，
veto 规则必须 deterministic-fallback（LLM 不可用时默认放行模型决策，不阻塞链路）。

### P6 — 时间序列基础模型 overlay（修柱子 3 的补充，仅 offline）

**动机**：若 P2 的 GBDT 仍不优于 v1，需要更强的预训练表达。

**主流做法**：时序基础模型（time-series foundation models）做 zero-shot / few-shot 预测：

- **通用**：Amazon Chronos、Google TimesFM、Salesforce Moirai、Lag-Llama、Nixtla TimeGPT。
- **加密专用**：Kronos（K线基础模型，`current.md` 已点名）。

它们的正确用法是**特征提取器**：把基础模型的预测方向 / 分位 / 不确定性当作 L1 GBDT 的
**额外特征**，而不是当交易信号。这给薄数据的子切片注入预训练先验，可能补上单靠本地
ridge/GBDT 学不到的结构。

**在 qount 的落点**：

- 严格继承 `current.md` / `optimization-plan.md §2.12` 的口径：**只做 offline overlay**，
  独立脚本 `scripts/ts_foundation_overlay.py`，输入 `state/research_runs` 已有窗口，
  输出每窗 directional_accuracy / post-cost edge / 与 setup_model 的差异 JSON。
- **不 import 进 src/qount，不进 candidate/risk/live。** 只有当 overlay 在 holdout 上
  对 GBDT 有**独立增量**（去掉它 lift 明显下降）才考虑把它的输出固化成离线特征。

**验证口径 / 硬约束**：完全继承现有 Kronos 口径——仅在 P2 决定 GBDT 不优于 v1 后启动；
得到"是否提供独立增量"的明确读数即终止；绝不接入交易链路。

### P7 — 成本与微结构：maker/post-only 执行 + 资金费率特征（提升每笔净边际）

**动机**：`profit-research-plan.md` WS-2 已离线证明 maker 费能把 post-cost edge 整体上移
约 +0.0004，足以让一批贴 0 线切片转正；但当时不改执行器。现代永续策略还普遍把**资金费率/
基差**当独立 alpha+成本源，当前 feature set 里没有。

**主流做法**：

- **Post-only / maker 进场**：限价挂单赚 maker 返佣（或至少免 taker 费），把 per-leg 成本
  从 `0.0006` 压到 maker 档，等价于把 `trade_policy.py` 里嵌进 target_edge 的 `0.0012`
  开仓成本系统性降低。
- **资金费率感知**（永续特有）：funding rate 既是持仓成本/收益，本身也含**拥挤度信号**
  （极端正费率 = 多头拥挤，常预示回调）。作为 L1 特征和持仓成本同时建模。
- **执行算法**：大单拆分 / 滑点模型校准，把 `slippage_pct` 从固定 0.0002 改成
  规模/波动相关的估计。

**在 qount 的落点**：

- L0 特征层新增 funding/basis（合约 markPrice vs indexPrice）字段进 snapshot。
- `executor.py` 新增 post-only 限价进场模式（独立开关，先单测、先 paper）。
- `trade_policy.py` 的成本模型从常数升级为 maker/taker + 规模相关滑点。

**验证口径 / 硬约束**：执行方式改动**单独成轮**、先单测再 paper（`profit-research-plan.md`
WS-2 已明确）；post-only 会引入未成交风险，必须建模 fill 概率，不能假设 100% 成交；
funding 特征做泄漏检查。

---

## 4. 路线图（按依赖与 ROI 排序）

把 P1–P7 排成可执行阶段，并标注它和现有 T-x / WS-x 的关系。**每阶段结束前不开 live、
不 forward paper、不放宽 broad gate。**

```text
阶段 0（前置，复用现有，零新增风险）
  - 完成 optimization-plan 的 T-D（AI 缓存/命令拆分）与 T-F（research/prod 类型隔离）。
    本方案的所有研究迭代都依赖快速、隔离的实验环境。
  - 把本文件的验证口径接进现有 walk-forward artifact 字段（holdout_role 已有）。

阶段 1（标注 + 模型核心，最大策略杠杆，可内部并行）
  P1  triple-barrier + meta-labeling          —— 修标注错配 + LLM over-hold
  P2  GBDT 主模型 + purged CV                  —— 修表达力
  退出判据：在 validation_pool_v1 上 meta-label gate 的 hold rate 下降且 realized 不变差，
            且 GBDT top-decile lift ≥ v1。任一不过 → 记录、转 P6。

阶段 2（广度，单点最大杠杆，依赖阶段 1 的模型）
  P3  横截面多币排序（提级，不再无限后置）     —— 修 BR 天花板
  P4  校准概率 + 分数 Kelly sizing            —— 连续下注维度
  退出判据：G_paper_multi（独立多币门槛）拿到一份 baseline 数字（哪怕是亏的），
            打破 ETH-only 单币把项目锁死的局面。

阶段 3（LLM 重定位 + 成本，提升净边际与稳健性）
  P5  LLM 降级为 veto/regime/解释层 + prompt v4
  P7  maker/post-only 执行 + funding 特征（执行改动单独成轮、先单测先 paper）
  退出判据：holdout 上 "模型 gate + LLM veto" 的风险调整收益 ≥ 模型 gate 单独。

阶段 4（兜底，仅在阶段 1 GBDT 不优于 v1 时启动）
  P6  时序基础模型 offline overlay（Chronos/TimesFM/Kronos），只产 artifact
```

与现有路线的映射：

```text
本方案 P1 ⊃ optimization-plan T-B（AI hold-bias），但用 meta-label 取代 prompt 措辞。
本方案 P2 ⊃ optimization-plan T-C（setup_model v2），但用 GBDT 取代手工交互。
本方案 P3 = optimization-plan T-H（多币），但从'后做'提级为阶段 2 主线。
本方案 P5 ⊃ optimization-plan T-B / §2.3 的 v3_veto_only，systematize。
本方案 P6 = optimization-plan T-I / current.md Kronos 口径，完全继承。
本方案 P7 = profit-research-plan WS-2 的执行器落地部分。
```

---

## 5. 反过拟合与验证（继承并强化现有纪律）

团队最强的资产就是它的反过拟合纪律（holdout.md + profit-research-plan §4.1）。引入 ML
后必须**加强**而非削弱：

- **Purged K-Fold + Embargo CV**（P2）：替代普通 CV，防 horizon 重叠泄漏。
- **Combinatorial Purged CV (CPCV)**（AFML）：生成多条回测路径，得到收益分布而非单点。
- **Deflated Sharpe Ratio (DSR)** + **Probability of Backtest Overfitting (PBO)**：
  量化"我搜了 N 个模型/超参后这个夏普还剩多少可信"。这正面回应 §4.1 的"挑出来的正切片
  天然高估"。所有阶段 1/2 的模型选择必须报告 DSR / PBO。
- **样本权重**：按 label 重叠唯一性（uniqueness）加权样本，避免重叠 horizon 让有效样本数
  虚高（AFML 第 4 章）。
- **holdout 不变**：`discovery_pool` 训练、`validation_pool_v1` once-only。任何在
  validation 上看过结果再调的模型/阈值，自动把该窗降级 discovery（holdout.md 已有规则）。
- **模型卡（model card）**：每个上线候选模型在 artifact 里 dump：特征列表、训练区间、
  CV 方案、DSR/PBO、SHAP 重要性、对现有 4 笔正收益开仓的预测。黑箱不进 gate。

---

## 6. 硬约束（继承 + 新增）

继承（与 current.md / holdout.md / quick-handoff.md 完全一致）：

```text
不开 live；不 forward paper（在对应 G_paper / G_paper_multi 全过之前）。
不放宽 broad range_noise / short_rebound_fail / pullback fresh entry。
不在 discovery_pool 上调参后当 promotion；validation_v1 once-only。
不把 offline_future_edge_readiness 当 promotion 证据。
不把 Kronos / 任何外部模型接进 candidate / risk / live。
一轮只改一处（entry / management / model / prompt 不同时改）。
不把 WSL .env 的 4-symbol live 形状当研究口径。
```

本方案新增：

```text
- 所有新模型（GBDT / meta-label / 基础模型 overlay）走和 setup_model v2 完全相同的
  研究隔离路径；不替换主线直到 holdout 证明优于现有 v1。
- LLM veto 只能减少交易，不能把模型已否决的交易改成放行。
- LLM 不可用时必须 deterministic fallback（默认放行模型决策），不阻塞链路、不静默改行为。
- Kelly 分数上限硬编码 ≤ 0.5 并写进单测；所有 sizing 仍过 risk_engine bottom_line 裁剪。
- 任何上线候选模型必须报告 DSR / PBO 和 SHAP；不报告不进 gate。
- 时序基础模型仅 offline overlay，绝不 import 进 src/qount。
- 执行方式（maker/post-only）改动单独成轮，先单测、先 paper，并建模未成交风险。
```

---

## 7. 风险、成本与终止条件

| 模块 | 主要风险 | 工程成本 | 终止条件（证伪即停） |
| --- | --- | --- | --- |
| P1 标注/meta-label | triple-barrier 参数也可过拟合 | 中 | holdout 上 meta-gate 不降 hold rate 或 realized 变差 |
| P2 GBDT | 树更易过拟合小样本 | 中（优先零额外依赖的 HistGBT） | top-decile lift 不 ≥ v1（转 P6） |
| P3 多币 | 信号跨币相关性虚高 BR | 中高 | G_paper_multi baseline 仍系统性亏 |
| P4 Kelly | 校准漂移导致超配 | 低 | 风险调整收益不优于固定 size |
| P5 LLM veto | LLM 不稳定/成本 | 低中 | veto 不改善风险调整收益 |
| P6 基础模型 | 依赖重、环境复杂 | 高 | 对 GBDT 无独立增量 |
| P7 执行 | 未成交/滑点模型错 | 中 | maker 实测净边际改善不达离线预期 |

**全局终止条件（诚实退出）**：如果阶段 1 + 阶段 2 全部做完，多币横截面 + GBDT + meta-label
+ Kelly sizing 在 `validation_pool_v1` / `G_paper_multi` 上**仍**无法产生统计显著（DSR > 0、
PBO 低）的 post-cost 正收益，那么结论是 **5m 频段的加密择时 alpha 在当前数据/成本结构下
不足以支撑这套系统**。届时正确的动作不是再调参，而是要么换频段（更慢的 swing / 更快的
做市），要么接受研究价值并停止追盈利。把这个退出条件写进文档，本身就是反过拟合纪律的延伸。

---

## 8. 与现有文档的关系

- [current.md](current.md) 仍是当前事实真相，本文件不改它的任何结论。
- 本文件是 [optimization-plan.md](optimization-plan.md) 的**上一层**：optimization-plan
  在现有架构内挤压，本文件论证架构天花板并给出迁移路径。两者不冲突——阶段 0 直接复用
  optimization-plan 的 T-D / T-F。
- [profit-research-plan.md](profit-research-plan.md) 的 WS-2（成本）落进本文件 P7；
  WS-1（horizon）被 P1 的 triple-barrier 从根上重构。
- 推进纪律不变：**单测 → WSL 单测 → 对应拆分命令 / walk-forward → 写回 current.md →
  写回 update-log.md → artifact 落 state/research_runs**。

---

## 9. 详细分步执行计划（2026-06-05 评审修订，落地以本节为准）

本节把 P1–P7 拆成可独立提交、可独立证伪的步骤 `S0.x … S5.x`。

每一步统一给六项：**目标 / 触及文件 / 交付物 / 单测 / 验证 gate / kill 条件**，并标注
**依赖**。除非特别注明，每一步都遵循铁律：**先写单测 → 本地 unittest 全绿 →
`scripts/sync-to-wsl.sh --install` → `scripts/run-wsl-tests.sh` 全绿 → 跑对应研究命令 →
artifact 落 `state/research_runs` → 写回 current.md / update-log.md**。

**全局执行顺序（带门控）**：

```text
S0  地基（依赖 + 缓存 + 类型隔离）           —— 无策略行为变化
        │
S1  KILL-TEST：triple-barrier 标注 + 多币横截面 IC   ← 这里可能直接终止整个项目
        │   IC 不成立 → 停，写结论，不进 S2
        ▼
S2  模型核心（SetupModel 接口 + GBDT + meta-label）   ← 依赖 S0.1 / S1
        │   GBDT 不优于 v1 → 跳 S5（基础模型兜底）；meta-gate 不改善 → 回退
        ▼
S3  广度 + sizing（多币横截面 + Kelly）               ← 硬依赖 S1 正 IC + S2 正 lift
        │   G_paper_multi baseline 仍系统性亏 → 触发全局退出条件（§7）
        ▼
S4  LLM 重定位 + 成本/微结构（veto/regime + maker）   ← 依赖 S2，独立成轮
        │
S5  兜底：时序基础模型 offline overlay                ← 仅当 S2.2 GBDT 不优于 v1
```

> 注意 S1 是**可终止整个计划的一步**。在它给出正 IC 之前，S2/S3 的重模型与多币扩张
> 都不启动——这是评审最重要的修正：**先证伪，再投入**。

---

### S0 — 地基（无策略行为变化，可与 S1 并行准备）

#### S0.1 引入 research ML 依赖（依赖：无）

- **目标**：在不污染 live 路径的前提下让研究环境可用 numpy/sklearn/(lightgbm)。
- **触及文件**：`pyproject.toml`、`scripts/sync-to-wsl.sh`、（新）`scripts/check-research-deps.sh`。
- **交付物**：
  - `pyproject.toml` 新增 `[project.optional-dependencies].research = ["numpy", "scikit-learn", "lightgbm; python_version < '3.14'"]`（lightgbm 视 wheel 情况条件化）。
  - 先验证 cp314 wheel：`pip download --only-binary=:all: numpy scikit-learn lightgbm`。
    - 全有 → 用 lightgbm。
    - lightgbm 无 cp314 → 主线用 `sklearn.ensemble.HistGradientBoostingRegressor/Classifier`（只需 numpy+sklearn），lightgbm 列为可选。
    - numpy/sklearn 也无 cp314 → 为研究单独建 `.venv-research`（Python 3.13），live 仍用 3.14 主 venv。
  - import smoke：研究命令在缺依赖时给出清晰报错，**绝不**让 live 路径 import 这些包。
- **单测**：新增"live 入口（settings/orchestrator live 分支）不 import numpy/sklearn/lightgbm"的静态断言测试（用 `importlib` + module 检查或 AST 扫描）。
- **验证 gate**：本地 + WSL 都能 `python -c "import numpy, sklearn"`（在 research venv 下）；live unittest 不因新依赖变慢/变红。
- **kill 条件**：若三种环境方案都装不上，退回纯 Python 路线（meta-label/GBDT 用手写实现），仅 S2.2 受影响，其余不变。

#### S0.2 确认 AI 决策缓存 + 命令拆分可用（依赖：无）

- **目标**：复用 `optimization-plan` T-D 已落地的 `--ai-decision-cache` 与
  `setup-edge-walk-forward` / `candidate-walk-forward`，确保后续大量复跑可缓存命中。
- **触及文件**：（多为只读确认）`walk_forward.py`、`backtest.py`、`main.py`。
- **交付物**：一份"缓存命中率 + 单次 9-window 复跑耗时"基线读数，写进 update-log。
- **验证 gate**：缓存命中复跑 < 5 分钟（T-D 终止条件）。
- **kill 条件**：若耗时仍不可接受，先补 partial.json 进度落盘，不进 S1 大样本。

#### S0.3（可选）research/production 类型隔离骨架（依赖：无）

- **目标**：落地 `optimization-plan` T-F：拆 `Settings` / `ResearchSettings`，让 ML 模型/
  多币/新标签只能从 research 入口进，编译期挡住误用进 live。
- **触及文件**：`settings.py`、`research_profile.py`、`candidate_filter.py`、`risk_engine.py`、`orchestrator.py`。
- **单测**：live 入口拒绝 `ResearchSettings`；research 入口拒绝裸 `Settings`。
- **验证 gate**：本地 + WSL unittest 全绿；`run-once` paper 路径 smoke 通过。
- **说明**：这一步行为零变化，但能显著降低后续所有 ML 改动误入 live 的风险，强烈建议在 S2 前完成。

---

### S1 — KILL-TEST / 选择扫描：频段 × 策略族（依赖：S0.1）

> **2026-06-05 终审升级**：S1 不再只测"5m 现有特征的 IC"，而是一张
> **频段 × 策略族网格扫描**，由证据选出在哪个频段、哪个族上做。完整定义见 **§10.4**；
> 本处保留原 5m 子步骤作为该网格里的一个 cell（大概率落败，属预期）。
> S1.1 的 triple-barrier 标注对所有预测族通用；CARRY 族走 §10.5 专线、不依赖标注/重模型。

#### S1.1 triple-barrier 标注模块（P1 标注部分）

- **目标**：把固定 horizon 标签换成路径依赖的三轨标签。
- **触及文件**：（新）`src/qount/labeling.py`；`main.py` 加研究开关 `--label-scheme triple_barrier`（默认仍 `fixed_horizon`）。
- **交付物**：纯函数 `triple_barrier_labels(candles, *, up_sigma, down_sigma, max_bars, vol)`，σ 用现有 `range_pct`/ATR 类指标缩放；只用决策时点可得信息（防泄漏）。
- **单测**：构造已知路径（先触上轨 / 先触下轨 / 超时）三类 fixture，断言 label、触轨 bar、收益符号；显式 look-ahead 测试（标签不得使用 t 时刻之后才可知的量来决定 t 的特征）。
- **验证 gate**：单测全绿；在一段 discovery 数据上 dump 标签分布（上/下/超时占比合理，不全是超时）。
- **kill 条件**：无（纯地基）。

#### S1.2 横截面 IC 证伪 harness

- **目标**：测现有 16 维特征对 triple-barrier 收益的预测力，多币、purged+embargo CV。
- **触及文件**：（新）`src/qount/ic_diagnostic.py`；`main.py` 加 `cross-sectional-ic` 命令。
- **交付物**：输出 JSON：
  - 整体 IC（Spearman/rank）与 t 统计；
  - `by_symbol` / `by_phase` / `by_horizon`（h3/h6/h12/h24）IC；
  - 跨币信号相关矩阵 → 估**有效广度**（不是裸 N）；
  - IC 随 horizon 的衰减曲线。
- **数据口径**：用 `MULTI_RECLAIM_SMA_SYMBOLS` 的 OHLCV，时间用 `discovery_pool` 区间训练统计、不碰 `validation_pool_v1`。
- **单测**：合成一个"特征=未来收益+噪声"的可控数据集，断言 harness 能恢复出已知 IC（正确性自检）；合成"特征与未来无关"断言 IC≈0。
- **验证 gate / 决策分叉**：
  - **正 IC（rank-IC 在 h6/h12 上稳定 > 0、跨币 t 统计显著、有效广度 ≥ 数倍）** → 进 S2。
  - **零/负 IC** → **触发全局退出条件（§7）**：5m 现有特征无横截面 alpha。写结论，停止重构，转去评估"换频段 / 换特征源（微结构、funding、基础模型）"而非继续堆模型。
- **kill 条件**：见上，这一步本身就是 kill gate。

---

### S2 — 模型核心（依赖：S0.1 + S1.2 正 IC）

#### S2.1 SetupModel 接口抽象（行为零变化，P2 前置）

- **目标**：把 `setup_model.py` 抽象成可插拔接口，现有 ridge 原样保留为 `v1`。
- **触及文件**：`setup_model.py`（已有 `v1` / `v2_interactions` 版本开关先例，第 133–142 行）。
- **交付物**：`SetupModel` 协议（`fit / predict_edge / quality / dump_card`），ridge 实现为 `SetupModelRidgeV1`。
- **单测**：v1 路径逐样本输出与重构前**完全等价**（用现有 fixture 对照）。
- **验证 gate**：所有现有 setup_model 相关单测不变绿；一次 discovery walk-forward 的 setup 层字段逐 cycle 等价。
- **kill 条件**：无（纯结构）。

#### S2.2 GBDT 主模型 `v3_gbdt`（P2）

- **目标**：用 GBDT（lightgbm 或 sklearn HistGBT）表达交互 alpha。
- **触及文件**：`setup_model.py` 新增 `SetupModelGBDTV3`；`setup-model-compare` 加 `--setup-model-version v3_gbdt` 与 purged-CV 评估口径。
- **交付物**：GBDT 实现 + model card（特征重要性/SHAP、训练区间、CV 方案、DSR/PBO）dump 进 artifact。
- **单测**：可重复训练（固定 seed）、card 字段完整、缺依赖时清晰报错。
- **验证 gate**：离线 sanity（对现有 4 笔正收益开仓预测均值 ≥ v1）+ `validation_pool_v1` 上 top-decile post-cost lift 显著 > v1 且校准曲线不差。
- **kill 条件**：GBDT 不优于 v1 → 不替换主线，转 **S5（基础模型 overlay）**。

#### S2.3 meta-label gate（P1 meta 部分，取代 LLM 当最终 gate）

- **目标**：用校准概率 `p(profit)` 取代 LLM 做最终是否下注的 gate。
- **触及文件**：（新）`src/qount/meta_label_model.py`；orchestrator 研究路径加 `--gate meta_label`（默认仍 `ai`）。
- **交付物**：GBDT 二分类，训练样本是**全体候选时点的 triple-barrier 结局**（评审修正，非已执行交易），isotonic/Platt 校准；阈值写进单测冻结。
- **单测**：校准曲线单调性、阈值冻结、缺依赖回退。
- **验证 gate**：`validation_pool_v1` once-only 比 meta-gate vs 现 AI gate：hold rate 下降且 realized 不变差、missed move 不增加。
- **kill 条件**：meta-gate 不降 hold rate 或 realized 变差 → 回退到 AI gate，记录"AI 在当前模型下就是这么保守"。

---

### S3 — 广度 + sizing（硬依赖：S1 正 IC + S2 正 lift）

#### S3.1 多币横截面排序 track（P3）

- **目标**：把 BR 从 ~50 提到数倍～10x（按有效广度，不按裸 N）。
- **触及文件**：（新）`src/qount/portfolio.py`（先只做排序/选币）；walk-forward 支持多币 profile，`max_open_positions=k`（研究 profile，不动 live）。
- **交付物**：每根 bar 对 universe 用 S2 模型打分，输出 top-k 候选与多空结构；显式断言不复用 ETH-only 窄 gate / override。
- **单测**：多币 max_open_positions=k 下不触发 ETH-only 单仓 override；排序确定性。
- **验证 gate**：`G_paper_multi` baseline 数字（哪怕亏）落地，打破 ETH-only 锁死。
- **kill 条件**：见 §7 全局退出。

#### S3.2 组合构造 + 分数 Kelly sizing（P4）

- **目标**：按校准概率连续 sizing，取代二元开/不开。
- **触及文件**：`portfolio.py` 加 sizing；sizing 输出仍过 `risk_engine` bottom_line 裁剪。
- **交付物**：分数 Kelly（上限硬编码 ≤ 0.5，写进单测）+ 组合波动率目标 + 相关性去冗余。
- **单测**：Kelly 上限不被突破；bottom_line 裁剪生效；薄边际样本得到小仓位。
- **验证 gate**：holdout 上风险调整收益（return/MDD 或 Sharpe）优于固定 size。
- **kill 条件**：风险调整收益不改善 → 回退固定 size。

---

### S4 — LLM 重定位 + 成本/微结构（依赖：S2，独立成轮）

#### S4.1 LLM 降级为 veto/regime/解释层（P5）

- **目标**：LLM 不再做数值 gate，只做可枚举硬反对项的 veto + regime 特征 + 解释。
- **触及文件**：`decision_schema.py`（加 `veto/regime/objections[]`）、`ai_client.py`、`orchestrator.py`、`prompts/decision_prompt_v4.txt` + `system_prompt_v4.txt`（删几十条软 "prefer waiting"，改硬反对项规则集）。
- **单测**：veto 只能减少交易不能增加；LLM 不可用时 deterministic fallback（放行模型决策、不阻塞）；regime 特征只用决策时点信息（泄漏检查）。
- **验证 gate**：holdout 上"模型 gate + LLM veto" 风险调整收益 ≥ 模型 gate 单独。
- **kill 条件**：veto 不改善 → 只保留 regime/解释，不接 veto。

#### S4.2 maker/post-only 执行 + funding/basis 特征（P7，单独成轮）

- **目标**：压低 per-leg 成本（WS-2 离线已证 maker 可整体上移 +0.0004）+ 引入永续微结构 alpha。
- **触及文件**：`market.py`（snapshot 加 funding/markPrice-indexPrice）、`executor.py`（post-only 限价模式开关）、`trade_policy.py`（成本模型从常数升级为 maker/taker + 规模相关滑点）。
- **单测**：post-only 未成交风险建模（fill 概率，不假设 100%）；funding 特征泄漏检查；成本模型回归。
- **验证 gate**：先 paper 实测净边际改善达离线预期。
- **kill 条件**：maker 实测净边际不达预期 → 不改执行器，仅保留 funding 特征。

---

### S5 — 兜底：时序基础模型 offline overlay（仅当 S2.2 GBDT 不优于 v1）

#### S5.1 基础模型 overlay（P6）

- **目标**：用 Chronos/TimesFM/Kronos 当**离线特征提取器**，看是否对 GBDT 有独立增量。
- **触及文件**：（新独立脚本）`scripts/ts_foundation_overlay.py`，**不 import 进 src/qount**。
- **交付物**：每窗 directional_accuracy / post-cost edge / 与 setup_model 差异 JSON。
- **验证 gate**：去掉 overlay 特征后 GBDT lift 明显下降 → 有独立增量，才考虑固化成离线特征。
- **kill 条件**：无独立增量 → 终止，绝不接入交易链路。

---

### 9.x 贯穿全程的验证基建（不单列步骤，但每个建模步必须带）

- **Purged K-Fold + Embargo CV**：S1.2 起所有 IC/模型评估默认口径。
- **CPCV + Deflated Sharpe + PBO**：S2/S3 的模型与组合选择必须报告，量化"搜了 N 个配置后
  夏普还剩多少可信"。
- **样本唯一性加权**：重叠 horizon 样本按 uniqueness 降权。
- **model card**：每个上线候选模型 dump 特征/区间/CV/DSR/PBO/SHAP，黑箱不进 gate。
- **holdout 不变**：discovery 训练、validation_v1 once-only；validation 上看过结果再调 →
  该窗降级 discovery。

### 9.y 步骤与现有 T-x / WS-x 映射

```text
S0.2 = optimization-plan T-D        S0.3 = optimization-plan T-F
S1.1 = profit-engineering P1(标注)   S1.2 = 评审新增 kill-test
S2.1/2.2 ⊃ optimization-plan T-C / profit-engineering P2
S2.3 ⊃ optimization-plan T-B / profit-engineering P1(meta)
S3.1 = optimization-plan T-H / profit-engineering P3（提级为门控主线）
S3.2 = profit-engineering P4
S4.1 ⊃ optimization-plan §2.3 v3_veto_only / profit-engineering P5
S4.2 = profit-research-plan WS-2 落地 / profit-engineering P7
S5.1 = optimization-plan T-I / current.md Kronos 口径 / profit-engineering P6
```

---

## 10. 终审修订（2026-06-05）：解除 5m 假设，以盈利为唯一目标

前 9 节（以及 current / optimization-plan / profit-research-plan）有一个从未被验证、
只是被继承的假设：**5m bar + 单一"择时开仓"策略族**。终审把它当成可推翻的设计变量。

### 10.1 最深的未审视假设：5m 对本系统结构性不利

5m 不是要"调好"的频段，是要**承认它大概率没有 retail-accessible alpha** 并换掉。原因
针对**本系统**：

- 5m 是和做市商 / HFT 正面竞争的频段；本系统是 **cron 驱动 + Clash 代理 + WSL + AI-in-loop**，
  延迟在秒级以上，**没有任何微结构 / 低延迟优势**。
- post-cost edge 贴 0 线（团队反复证实）正是这个原因：在最拥挤的频段，taker 费 + 滑点
  吃掉薄边际。这不是策略不行，是**频段选错**。
- 高频 → 高换手 → 成本主导；又 → 海量 AI 调用 → `optimization-plan §2.7` 反复记录的
  工程长尾崩溃。低频在成本、算力、基建脆性上**三重受益**。

**这是天花板的第五根柱子：频段与系统延迟错配。** 它比前四根更底层——前四根都是"在 5m 上
怎么做得更好"，第五根是"根本不该死磕 5m"。

### 10.2 BR 数学在日频下重算（真正的破局数字）

```text
5m 单币：       BR ≈ 50    → required IC ≈ 0.14   （不现实，天花板）
日频横截面~10币：gross ≈ 10×365 = 3650/yr
               扣自相关/持仓重叠 → 有效独立下注 ~ 数百
               sqrt(300) ≈ 17 → required IC ≈ 0.06   （可达）
```

加密**横截面动量**的文献 IC 本就在 `0.03–0.08`。**从 5m 单币换到日频横截面，把"需要的
IC"从不现实的 0.14 拉到可达的 0.06**——这是全文最大的单一杠杆，超过任何模型升级。

### 10.3 策略族菜单（latency-insensitive，适配本系统）

把"5m 择时开仓"替换成一张由证据选择的菜单：

| 族 | 频段 | 性质 | 为何适配本系统 | 主要风险 |
| --- | --- | --- | --- | --- |
| XS-MOM 横截面动量 | 4h / 1d | 预测 | breadth 富、低换手、低延迟敏感、文献最稳 | 动量崩塌、拥挤 |
| XS-REV 横截面反转 | 1h / 4h | 预测 | 与 MOM 弱相关、可叠加增 breadth | 趋势市失效 |
| TS-MOM 趋势 (CTA) | 1d | 预测 | 经典稳健、低换手 | 震荡市磨损 |
| **CARRY 资金费率收割** | 8h / 持续 | **结构性（非预测）** | **最可能真盈利**：funding 是结构性现金流，不需预测方向；延迟不敏感、容量大；本系统已是永续基础设施 | funding 翻转、基差爆裂、双腿管理、交易所/对手方 |

**诚实的核心判断**：以盈利为唯一目标时，**最可能真盈利的是最简单的 CARRY，不是最花哨的
5m GBDT**。funding 收割是加密里最有文献支撑的持续 edge，且它甚至**不需要重 ML 栈**——
这恰恰说明前 9 节那套 GBDT/meta-label 管线虽然正确，但可能不是通往盈利的最短路径。

### 10.4 重构后的 S1：频段 × 策略族 选择扫描（取代假设）

S1 升级为一张网格扫描，**用证据选出策略，而不是假设策略**：

```text
频段 ∈ {5m, 1h, 4h, 1d}
族   ∈ {XS-MOM, XS-REV, TS-MOM, CARRY}
对每个 (频段, 族) cell 计算（纯离线、用历史 OHLCV + funding 历史）：
  - post-cost rank-IC / 信息比率 / 年化 Sharpe
  - 有效广度（跨币相关去冗余后）
  - 换手率与对应成本（低频下成本数量级下降，edge 曲面与 5m 完全不同）
输出：post-cost 风险调整 edge 最强的 cell。
```

- **触及文件**：（新）`scripts/strategy_selection_scan.py`，或扩展 §9 S1.2 的
  `cross-sectional-ic` 命令支持 `--frequencies 5m,1h,4h,1d` `--families xs_mom,xs_rev,ts_mom,carry`。
- **数据**：discovery 区间训练统计、不碰 validation_v1；需接 Binance funding 历史
  （`fapi` fundingRate endpoint，已在永续基础设施内）。
- **验证 gate / 分叉**：
  - 某预测族（很可能日频 XS-MOM）胜 → 在该频段落地 §9 的 S2/S3 ML 管线。
  - **CARRY 胜（很可能）→ 走 §10.5 专线**，可能完全跳过重 ML。
  - **所有 cell 在 holdout 上都无 post-cost 正 edge → 才触发全局退出**（比原"5m 无 alpha
    就停"严格得多，给了项目真正的破局空间）。
- **5m 全族落败是预期结果，不是项目失败。**

### 10.5 CARRY 专线（可能直接是答案，独立于 ML 主线）

若 S1 选出 CARRY：

- **信号层**：funding rate 历史 + 当前 + 基差（perp markPrice vs index）→ 收割方向 / 规模。
- **实现**：delta-neutral——长 spot / 短 perp 捕 funding；或纯 perp 按 funding 周期管理
  （必须明确腿管理与对冲，不能裸 perp）。
- **模型**：**不需要 GBDT / meta-label**；规则 + 阈值即可，验证仍走 backtest / walk-forward +
  holdout + DSR。
- **执行**：复用现有 `executor`，新增 spot+perp 双腿或 funding-aware 持仓管理（单独成轮、
  先单测、先 paper）。
- **风险（必须 honest backtest 进去）**：funding 翻转、极端行情基差爆裂、双边手续费、
  交易所/对手方风险、spot/perp 资金分配。funding 历史必须真实回放，不能假设常正。

### 10.6 修订后的全局执行顺序

```text
S0   地基（依赖 / 缓存 / 类型隔离）                  无策略行为变化
S1'  频段 × 策略族 选择扫描   ← 选出在哪个频段、哪个族做（5m 大概率出局）
       ├─ CARRY 胜（很可能） → S-CARRY 专线（简单、可能最快盈利、无需重 ML）
       └─ 预测族(如日频 XS-MOM)胜 → S2/S3 ML 管线在该选定频段落地
S2   模型核心（在选定频段上，而非默认 5m）
S3   广度 + sizing（横截面 + 分数 Kelly）
S4   LLM 重定位（仍只做 veto/regime/解释）+ 成本/微结构
S5   兜底：基础模型 overlay
```

### 10.7 终审更新的硬约束 / 退出条件

- **全局退出条件**从"5m 无 alpha 就停项目"改为"**S1' 所有频段 × 族在 holdout 上都无
  post-cost 正 edge 才停**"。更严谨、更难触发，因为它先穷尽了频段/族空间。
- 频段 / 族切换只在研究；live 仍关闭直到对应 G_paper / G_paper_multi 通过。
- CARRY 的双腿 / 对冲若要 live 化，是独立工程轮，先单测、先 paper，funding 历史真实回放。
- 其余继承 §6 全部硬约束不变。

### 10.8 终审一句话

> 前 9 节回答的是"在 5m 上怎么做得更对"；第 10 节回答的是"根本不该死磕 5m"。
> 以盈利为唯一目标，**正确的第一步不是上 GBDT，是先跑频段 × 策略族扫描，并优先验证
> 日频横截面动量与资金费率 carry 这两条 latency-insensitive、文献最稳、容量最大的路径。**
> 重 ML 管线（S2–S5）只在选定的频段上、对选定的预测族才启动。

---

## 11. 执行进展与计划校准（2026-06-05，结合实际代码与成果）

本节是把 §9 / §10 的**前瞻计划**和**已落地的代码、已跑出的 artifact**对账的结果。
落地实情与原计划在结构上有偏差，记录在此；后续推进以本节的校准结论为准。

### 11.1 一句话

S0.1 地基已落地；S1'（频段 × 策略族选择扫描）**第一遍已全量跑完**，但
**§10.4 预测的"CARRY 很可能胜"没有成立**——CARRY 被 basis-tail 证伪，目前唯一还活着的
候选是一个**预测族** `4h xs_mom lb24/h6`，且它也只过了离线 sanity、被 fixed TP/SL exit
否定，未到 paper。**计划仍停在 S1'，S2 重模型未启动，没有任何 promotion 证据。**

### 11.2 S0–S5 实际进度

```text
S0.1 research ML 依赖隔离        ✅ 已落地（numpy/sklearn optional extra；lightgbm 可选不可用）
S0.2 AI 缓存 / 命令拆分           ✅ 复用既有（--ai-decision-cache / setup-edge / candidate-wf）
S0.3 research/prod 类型隔离骨架   ⬜ 未做（可选，未阻塞当前研究）
S1'  频段 × 策略族选择扫描        🔄 第一遍全量跑完，仍在 exit/OOS 复核期（未触发任何晋级）
S2   GBDT + meta-label           ⛔ 未启动（硬门控未通过：见 11.4）
S3   多币横截面 + Kelly           ⛔ 未启动（硬依赖 S2）
S4   LLM 重定位 + 成本/微结构      ⛔ 未启动
S5   时序基础模型 overlay         ⛔ 未启动
```

### 11.3 实现落点与原计划的偏差（重要）

§9 把 S1.1 / S1.2 设计成多个独立模块（`src/qount/labeling.py`、
`src/qount/ic_diagnostic.py`、`cross-sectional-ic` 命令），§10.4 又提到
`scripts/strategy_selection_scan.py`。**实际落地把这些全部合并进了一个引擎**：

```text
计划                                   实际落地
src/qount/labeling.py (triple-barrier) ─┐
src/qount/ic_diagnostic.py (rank-IC)    ├─► src/qount/strategy_selection.py（约 1647 行）
cross-sectional-ic 命令                 │   + CLI: strategy-selection-scan
scripts/strategy_selection_scan.py      ─┘
```

- triple-barrier → `--directional-exit-mode triple_barrier` + `--directional-take-profit-pct`
  / `--directional-stop-loss-pct`。
- 横截面 IC → cell 的 `rank_ic_mean` / `effective_breadth` 字段。
- purged/embargo CV → `--directional-purged-cv-folds` / `--directional-embargo-bars`。
- CARRY 专线（§10.5）→ `--carry-model threshold_dual_leg` 及全套
  `--carry-*` 参数（basis source / tail stop / spot-perp gross / post-only economics）。

读法：原计划的"一步一个新模块"被收敛成"一个 research-only 引擎 + 大量显式 flag，默认
不改 live / `run-once`"。这并不违反铁律（每个 flag 单独成轮、先单测），但意味着
**§9 的 S1.1 / S1.2 / §10.5 文件路径已过时**，未来引用应指向 `strategy_selection.py` /
`strategy-selection-scan`。`labeling.py` / `ic_diagnostic.py` / `meta_label_model.py` /
`portfolio.py` 目前都**不存在**；S2 起若新增模型层，再按需要决定是抽出独立模块还是继续
挂在现有引擎上。

### 11.4 S1' 分叉的实际结果（对照 §10.4 的预测）

§10.4 设了三个分叉。第一遍扫描后的实际落点：

| §10.4 预测 | 实际结果 | 证据（详见 current.md / quick-handoff） |
| --- | --- | --- |
| CARRY 很可能胜 → 走 §10.5 专线 | **未成立**：被 basis-tail 证伪 | 1 天 validation_v1 单次 basis tail 把小正收益抹平转负，tail/net≈5.62x；WLD/SOL 6/1–6/5 after-tail 转负且需 >100% maker fill |
| 预测族（如日频 XS-MOM）胜 → S2 落地 | **部分成立**：胜出的是 `4h xs_mom lb24/h6`，非日频 | 120 天 discovery `sum=+3.53 / sharpe=+7.16 / rank_ic=+0.052`，过 stride 去重叠 + 限仓 replay + purged-CV(3/4 fold 正) |
| 所有 cell 无正 edge → 全局退出 | **未触发** | 至少存在一个有正 rank-IC 的预测 cell |

但**胜出 cell 仍不可晋级**：

- fixed TP/SL triple-barrier 120 天四组全负（止损约止盈 2.18x），收益被路径止损 + 成本吃掉。
- 月度不稳：2026-02 仅微正、2026-03 为负；purged-CV 第 2 fold（3/3–4/1）为负、IC 为负。
- `jun01_04` 等只是已看窗口 sanity，不能当 promotion。

`1d ts_mom`（原计划最看好的日频）已被 top12 扩币 120 天证伪（`sum=-2.67`，2/3/4 月全负）。

### 11.5 校准后的下一步（带门控，仍只做 research）

仍按"先证伪、再投入"。当前**不进 S2**，因为 S2 的进入门控（§9 S2.2/S2.3）要求胜出
信号在 holdout 上有可交易、可执行的正 edge，而 `4h xs_mom` 的可执行 exit 尚未证明。

```text
N1  4h xs_mom 的稳健 exit / 模型层 purged-CV / 新完整 OOS
      —— close-to-close、stride、限仓 replay、simple fixed TP/SL、fixed-cell purged-CV
         都已跑完，不要重复；下一刀只做"波动率缩放 barrier / 持仓管理"或新 OOS 日期。
      门控：在新的 validation_v1 完整窗口上，带可执行 exit 仍有 post-cost 正 edge
           且月度不全靠单月 → 才考虑进 S2（在 4h 上落 GBDT/meta-label）。
N2  S-CARRY 只能等新的完整独立日期，或重做真实 hedge timing / basis-tail-aware exit；
      entry-only basis filter、simple hard stop、post-only economics 已证不够，不要重复。
N3  5m 全族保持出局：只保留 cost-stress 证据；除非执行成本实测突破，不上 5m GBDT。
N4  S2/S3/S4/S5 维持不启动，直到 N1 给出可执行正 edge。
```

### 11.6 本节不改动的硬约束

§6 / §10.7 的硬约束全部不变：live 关闭、不 forward paper、不放宽 broad gate、
不在 discovery 上调参后当 promotion、validation_v1 once-only、Kronos / 外部模型不进
candidate/risk/live、一轮只改一处。本节只校准计划与现实的对账，不放宽任何一条。
