# qount 架构评审与下一步优化计划

创建时间：2026-05-31

这份文档不替代 [current.md](current.md)（当前结论）和
[profit-research-plan.md](profit-research-plan.md)（盈利研究路线）。它做的是另一件事：

- 把项目读完之后，列出**当前架构 / 策略 / 实验流程上结构性的问题**。
- 在已有的 WS-1..WS-4 之外，给出**下一步真正值得投入的方向**和优先级。
- 不放宽任何既有硬约束（live 关闭、不放宽 broad gate、不把 0/0 当晋级证据）。

读法：先读第 1 节"现状一句话"，再读第 2 节问题清单，最后读第 3 节路线。
结构性问题清单基于 2026-05-30 artifact；2026-05-31 已补入 T-A/T-B/T-D/T-G 的
实现进展和 WSL 读数。

---

## 1. 现状一句话

```text
ETH-only research-only.
13-window walk-forward (gpt-5.5): sum_realized=+1.6184%, positive=2/13.
全部正收益集中在 wf-mar06 (+1.5617%) 与 wf-apr15 (+0.0567%)。
WS-1/2/3 全部读数为"不支持继续"。
WS-4 三条候选均不能进 step 4 gate：
  - pullback_sma_fast_gt008  step 3 失败（AI 24/24 hold，0 成交）
  - range_return24_gt012     step 2 不 ready
  - eth_reclaim_long_*       step 2 不 ready
最新 5/30 OOS 仍是 0 成交、0 readiness。
```

读完文档后的总判断：现有路线（继续在已看过的窗口上做 tag readiness → shadow proof
→ 窄 gate）已经走完一遍，结论是"alpha 稀疏 + 评测窗口太碎 + AI 全 hold + setup model
表达不了交互"四件事**叠加**成一个本地最小值。继续按相同方法跑下一个 OOS 不会破局。

---

## 2. 当前架构 / 策略 / 流程的结构性问题

按"修起来杠杆从大到小"排序。每条都给出**证据**与**最小可验证修复**。

### 2.1 Promotion Gate 在当前 alpha 密度下数学上不可达

**证据**：

- `profit-research-plan.md §4` G1 要求 ≥13 窗 / G2 要求"有成交窗口 ≥5 且 ≥60% 正"。
- `current.md` 9-window 链路统计：946 cycles → 17 fresh selected → **4** opened，
  其中 3 笔来自同一窗 `wf-mar06`，1 笔来自 `wf-apr15`，其余 11 个窗口 0 交易。
- 即使 AI 把 hold 全开放，按当前 candidate selected=17，最多也只能得到
  ≈17 traded 样本，分布在 ≤2 个窗口；远远不够 G2。

**结论**：在 ETH-only / 5m / 6-bar horizon 上，**结构性**凑不出 G1+G2，所以
"promotion gate"实际上变成了"永远不能 promote"。这不是策略不行，是评测设计与样本
密度不匹配。

**最小修复**：把 promotion 拆成两级（不放宽 G3/G4/G5/G6/G7，只重新设计 G1/G2）：

```text
G_paper（forward paper 进入条件，不开 live）：
  - 累计 traded 样本 >= 20（来自任意窗口组合，不看 window 数）
  - sum_realized > 0 且 traded-sample-weighted avg_realized > 0.10%
  - 去掉贡献最大的"窗口"后仍 > 0（保留 G7 思想，但 unit 改为 traded-sample 分组）
  - 0 candidate-aligned miss，0 open positions

G_live（在 G_paper 通过基础上叠加）：
  - forward paper 上线后再跑 N 周新样本（完全没参与过 discovery / debug）
  - 这 N 周样本上仍然过 G_paper 的全部门槛
```

也就是说，**先承认 ETH-only 这个口径下"足量 traded 样本"得用累计而不是 window 数
计**；window 数只是噪声。

### 2.2 真正的 OOS 已经被用过几十次

**证据**：

- `wf-mar06 / wf-apr15 / wf-may26 / wf-may26pm / wf-may27am / wf-may28-* / wf-may29-* /
  wf-may30-*` 这一串"OOS"窗口在 `current.md` 与 `update-log.md` 里反复出现。
- 同一窗口已多次用于：调 deterministic override、调 weak-trend shallow blocker、
  调 neutral reclaim short blocker、调 trailing arm/retrace、对比 h6/h12 horizon、
  比较 multi vs eth-only target slice、跑 step 3 shadow proof 等。
- `profit-research-plan.md §4.1` 自己写了"frozen + holdout + 多重比较折扣"，但
  **当前没有任何字段记录 holdout / discovery 边界**。所有 13 窗都同时是发现样本和
  验证样本。

**结论**：当前所谓 OOS 已经全部被"看过"，统计意义上不能再当 promotion 证据。
任何在已看过窗口上"再调一次阈值就能过"的写法都构成 p-hacking。

**最小修复**：

```text
1. 在 docs/ 下新增一个 ground-truth holdout 列表，例如 `docs/holdout.md`：
   - 写明：从今天起冻结某个时间点之前的所有 13 窗为"discovery + tuning 池"
   - 该日期之后只允许做"recording + once-only validation"，不允许调阈值再回测
2. walk-forward / setup-edge-study artifact 里新增字段
   `holdout_role: discovery | validation | unknown`，由命令行显式指定
3. promotion 判定（无论 G_paper 还是 G_live）只能用 validation 池的累积样本
4. 任何在 validation 池上调过阈值的实验自动把那段窗口"降级回 discovery 池"
   并记录在 `docs/update-log.md`
```

### 2.3 AI 全 hold 是 WS-4 step 3 失败的真因，但还没量化过

**证据**：

- `update-log.md 2026-05-30` WS-4 step 3：mar03 + apr20 两个独立窗口，
  `target_ai_decision_count=20+4`，全部 hold；`paper_filled=0`。失败点是 AI，不是 risk。
- `prompts/system_prompt_v1.txt` 与 `ai_client.py:23-95` 充斥 "default wait"
  / "prefer waiting" / "treat as insufficient by itself and prefer waiting" 这类
  保守语义，且对每一类 setup model 信号都有"再等一根 bar"出口。
- 同样的 prompt 在 `wf-mar06` 上也 hold 过 `run 76`，最后是用 deterministic override
  把它强制改成 sell 才得到 `+1.56%`——也就是说，**正收益样本 4 笔里至少 1 笔
  是绕过 AI 决策得到的**。
- 9-window 链路里 `ai_held_candidate=7`，其中
  `avg_candidate_aligned_future_return_pct=-0.1553%`——AI hold 在大多数情况下
  是对的，但在 candidate-aligned 强 setup（mar06、step 3 这种）上系统性 hold 错。

**结论**：现有 prompt 的"先 wait 再说"风格在 setup_model 已经给出强信号的窄候选上
属于过度保守。WS-4 step 3 之所以 readiness 通过却 0 成交，主因是这条 prompt 风格。

**最小修复**：

```text
1. 加一个新研究入口 ai-hold-baseline：
   - 取一段已持久化 backtest，对每个 fresh-entry candidate
     重新发同一份 prompt N 次，统计 hold rate / sell rate / buy rate
     的 baseline 与方差
2. 新增 prompt 变体（只在研究 profile 下生效，不动 live）：
   - prompt_v2_remove_default_wait：删掉 "default wait" / "prefer waiting"
     的兜底语句，但保留 terminal_risk / overextension 的具体反对项
   - prompt_v3_veto_only：把 AI 改成"对 setup_model.quality=strong_favorable
     的候选只能输出 sell/buy/hold 中的 hold 当且仅当能给出具体反对项"
3. 在 WS-4 step 3 已有的两个 shadow 窗口上对比这两个 prompt 与基线，
   读 realized return / candidate-aligned future return 的差
   注意：这是 prompt-level 实验，按"4.1 反过拟合纪律"它们必须先冻结假设，
   再用未参与 discovery 的窗口做 once-only 验证
```

如果 prompt v2/v3 在 holdout 上把 AI hold rate 砍下来、且 realized return 不变差，
则 WS-4 才有继续往 step 4 走的余地。否则现有 alpha 在 AI 这一关就被吃掉，下面
WS-4/5 都是白做。

2026-05-31 进展：`ai-hold-baseline` 已落地。WSL dry-run 复现 WS-4 fast-SMA
step3 两个窗口 `stored_hold=24/24`；eth-only `v3_veto_only` 小样本 smoke 仍是
`hold=2/2`，且理由是具体 veto。当前结论是工具化完成、v3 未证明可推进。

### 2.4 setup_model 是 16 维线性 ridge，无法表达已知 alpha 所在的交互维度

**证据**：

- `setup_model.py:34-105`：feature 共 16 维，全部线性 ridge（手写 GD），无交互项、
  无树模型、无分桶。
- `current.md` discovery 反复确认强切片是 **交互**：
  `phase × sma_fast_bin>0.008`、`phase × range_pct × return_24bars`、
  `phase × rsi_bin × sma_slow_bin`，min-fold 大多正。
- 9-window 实际开仓 4 笔的 `final_expected_edge_pct` 都在 `0.0020..0.0039`，
  setup model 对这些样本只能给出 weak/neutral 这一档预测——这就是为什么很多 fresh
  candidate 被 AI hold：setup model 自己也说 "weak_favorable"。
- `profit-research-plan.md §5` 已经识别这个问题，但放在"长期 / 高风险"里。

**结论**：**这是当前最大的中期杠杆**。即使 promotion gate 与 OOS 设计修好，
如果 setup model 的输出空间表达不出 discovery 里那些交互正切片，AI 永远拿不到足够
强的信号去离开 hold 区域。

**最小修复**：

```text
1. 新增 setup_model v2，最小改动：
   - 不换框架（保留 ridge，便于审计），但在特征构造层加 hand-crafted 交互：
       phase_pullback × sma_fast_ratio_bin
       phase_pullback × sma_slow_ratio_bin
       phase_range × return_24bars_bin
       phase_reclaim × rsi_centered_bin
   - bin 用离线 discovery 已用过的阈值（>0.008、>0.012 等），不再造新阈值
2. 训练目标保持 target_edge_pct，但训练样本按 phase 拆开拟合
   （同一份代码，不同 phase 一个 ridge），降低线性挤压
3. 输出沿用 predicted_edge_pct / confidence_ratio / quality 三档接口，
   不动 prompt schema 与 candidate_filter 的 entry block 逻辑
4. 评估：
   - 在 discovery 池上训练；在 holdout 池上算 calibration、AUC-like、
     post-cost realized lift
   - 必须先在 9 窗 walk-forward 上跑出"对 4 笔已有正收益开仓的预测均值更高"
     这个最低 sanity，再考虑替换主线模型
```

### 2.5 candidate_filter 的窄 gate 已堆成"事后修复链"

**证据**（按文件 `candidate_filter.py` 中出现顺序）：

- `setup_model_neutral_reclaim_short_rebound_fail`（mar11 run 97 修补）
- `setup_model_weak_trend_shallow_short_rebound_fail`（may26 run 96 修补）
- ETH fresh long veto
- ETH weak reclaim short gate（trend_strength + reclaim bonus + breakdown pressure）
- ETH reclaim short tight retrace
- deterministic_eth_reclaim_support_breakdown_override（mar06 run 76 修补）

**问题**：

- 这些 gate 的触发条件极窄、几乎都是"对某一个具体 run 的回填"。
- 多个 gate 在 `_setup_model_entry_block_reason` / orchestrator override 里
  互相耦合，新增一条要核对所有旧条件，回归成本越来越高。
- 它们的存在让"再开放一类 fresh entry"这个动作几乎不可能：你不能确定打开
  以后哪条窄 gate 不该再生效。
- 单测的覆盖也是按 run 写的，会把"具体 run 的输入完整复制成 fixture"，所以
  refactor 时这些测试本身就是脚手架而不是 spec。

**最小修复**：

```text
1. 把 5 条 ETH 窄 gate 的触发条件做一次"集合化"：
   - 提取共同特征 axis：(setup_phase, higher_timeframe_phase, direction,
     setup_model.quality, setup_model.confidence_ratio,
     setup_model.positive_edge_rate, support_break_pct, trend_strength)
   - 在一张矩阵里检查每条 gate 是不是其他几条的子集；若是，合并
2. 把 deterministic override 改名 / 上锁：当前它在 research profile 下绕过 AI，
   但 prompt v2/v3 实验如果成功，override 可能就不需要了。给 override 加一个
   "expires_at"或"depends_on_prompt_version"字段，方便以后退役。
3. 单测 fixture 不再复制具体 run，改成只断言"在 setup_model_signal=X、
   traditional_signal_context=Y、support_break_pct=Z 时 _setup_model_entry_block_reason
   返回 R"，使其与 candidate_filter 解耦。
```

### 2.6 research 与 production 边界过于隐蔽，已经踩过坑

**证据**：

- `research_profile.py:38-50` 用 `dataclasses.replace` **静默覆盖**
  `trailing_profit_arm_pct / retrace_pct / ai_temperature`，
  导致 `QOUNT_TRAILING_*` env 在 `--research-profile eth-only` 下完全无效，
  之前 WS-1 实验已经踩过这个坑（已修复成 CLI override，但 root cause 没动）。
- `research_shadow_candidate_tags` 直接接进 `candidate_filter.apply` 主路径
  （`candidate_filter.py:264-301`），通过 `live_mode/live_enable` 判断回退；
  一旦未来误把 research profile 与 live=true 同时存在的设置打开，就会改 live 行为。
- `current.md / quick-handoff.md` 反复警告"不要把 .env 4-symbol live 形状当研究
  口径"，说明这个边界靠人记，不是靠类型系统挡。

**最小修复**：

```text
1. 把 Settings 拆成 Settings (live-shape) 与 ResearchSettings (研究 shape)
   两个类型；apply_research_profile 只能产出 ResearchSettings
2. CandidateFilter / RiskEngine 在 live 路径上拒绝接收 ResearchSettings；
   research 入口反过来也拒绝接 Settings（编译期挡，不靠 if）
3. ResearchSettings 上保留 audit_context，记录所有 override 的来源
   （CLI / profile 默认 / env），artifact 里 dump 它，方便复核
4. 影响最大的字段（trailing / ai_temperature / shadow tags）走显式 require，
   不允许"默认值兜底"
```

这条不是"现在不工作"的 bug；它是"未来某次 refactor 必然会出事"的隐患。

### 2.7 实验流程被 AI 调用成本/环境复杂度卡住

**证据**：

- `update-log.md 2026-05-30 WS-2 min-edge`：完整 13-window 四档扫描中止；
  改成 2-window 粗筛仍中止；最终只能用 baseline 离线判读。
- `update-log.md 2026-05-30 WS-1`：完整 13-window 探针中止；只跑 wf-mar06 单窗。
- `quick-handoff.md` 同步流程：Mac → Windows USERPROFILE → WSL 三跳；
  每次实验前置 5 行 scp + 1 行 ssh wsl bash here-doc。
- WSL 侧需要 `set -a; source .env; set +a` 才能联网，否则 binance 502。
- 关键复跑命令长度都在 600+ 字符，手动改一个参数容易整条引号失衡。

**结论**：**实验密度已经被工程长尾压垮**，不是策略不愿试，是试一次太贵。
WS-1/WS-2 的所有"不支持继续"读法都建立在不完整 artifact 上。

**最小修复**：

```text
1. AI 决策缓存（仅研究环境）：
   - 把 (snapshot_hash, prompt_version, model_id, temperature) 做 cache key
   - 同一 walk-forward 复跑时直接命中缓存，节省 90%+ AI 调用
   - 注意：必须把 prompt 与 system prompt 完整 hash 进 key，不能只 hash 模型
   - 缓存只在 backtest/walk-forward/setup-edge-study 下生效；live / paper 永不缓存
2. 把"完整 13-window 跑一次"做成一个长跑 background script，
   写 partial.json 进度（已有 walk_forward.partial.json 框架，复用），
   即使中止也能读已完成 N 个窗的子结论
3. Mac→WSL 同步只保留两条最常用命令为脚本 scripts/sync-to-wsl.sh /
   scripts/run-wsl-tests.sh，不再让接手模型每次自拼引号
4. 研究命令统一加 --dry-run 或 --max-cycles 参数，先估时再开跑
```

如果不解决这一条，下面 §3 的所有路线都会同样跑不动。

### 2.8 walk-forward 把 horizon / setup model / AI / risk 耦合在一次实验里

**证据**：

- 每次 `walk-forward --horizon-bars X` 都会重训 setup model + 跑 AI + 走 risk +
  paper 执行。
- WS-1 h12 实验失败的原因里包括"trailing 没收尾干净"——但这是 risk 层问题，
  跟 horizon 验证无关；现有实验把它们混在一起，所以读数难解释。
- WS-4 step 3 同样耦合：AI hold 与 risk 不阻断没法分开统计。

**最小修复**：

```text
1. 拆出 setup-edge-walk-forward 命令：
   - 只重训 setup model
   - 不跑 AI、不跑 risk、不跑 paper
   - 输出 setup_model.predicted_edge_pct vs realized_target_edge_pct 的
     calibration / 排序质量
2. 拆出 candidate-walk-forward 命令：
   - 用固定的 setup model
   - 跑 candidate filter 输出，不跑 AI
   - 输出 candidate_selected / fresh_entry_selected / entry_viability_preview
     的统计
3. 现有 walk-forward 保留为"端到端"命令，但只在两层拆分都有正读数后才用
```

这样 WS-1 才能干净地"先证 horizon 12 的预测优于 6"，再决定是否动退出参数。

### 2.9 readiness 与 realized return 的耦合错位

**证据**：

- `research-slice-scan.shadow_candidate_readiness` 只看 snapshot 序列里某 tag 的
  h3/h6/h12/h24 future-edge：
  - sample_count >= 8 / positive_edge_rate >= 0.5 / positive_windows >= 2。
- 这是**离线 future-edge** 的统计，不要求该 tag 经过完整 candidate→AI→risk→执行链路。
- WS-4 step 3：同一个 tag readiness 通过、隔离链路 0 成交、realized 0。
  也就是说，**readiness 是必要条件，但远远不充分**，但当前 readiness 字段的命名
  会让人误以为它已经接近 promotion 证据。

**最小修复**：

```text
1. readiness 改名为 offline_future_edge_readiness，明确只表达离线 future-edge
   层面的最低门槛
2. 新增第二档 link_ready：
   - 该 tag 在历史 backtest 链路里有过 fresh_entry_selected 出现
   - AI 对该 tag 的 hold rate 不超过门槛（例如 < 0.7）
3. 新增第三档 promotion_ready：
   - 在隔离 shadow harness 里跑过完整 AI/risk，并产生过非零 realized return
   - 在两个独立 holdout 窗口上都满足
4. step 3 / step 4 的纪律改用第二、三档作为入口判定
```

### 2.10 0 交易窗口被反复重跑，但其中潜在信息没有被提取过

**证据**：

- 11/13 窗口是 0 交易、0 review。`current.md §0-trade window inspection`
  只做了"是否暴露 candidate-aligned miss"这一项检查。
- 其余信息没有用：
  - 0 交易窗口里 `setup_model` 的预测分布是什么样？是不是大部分 weak_favorable？
  - 这些窗口在 discovery 切片上有没有命中过强子切片，但 AI 主动放弃？
  - candidate_filter 在这些窗口里的"接近 eligible"分布是什么？

**最小修复**：

```text
1. 增加一个 idle-window-diagnostic 命令，对每个 0 交易窗口输出：
   - setup_model.label / quality 直方图
   - candidate_filter.reasons 直方图（前 10 大 hold 原因）
   - traditional_signal_context.pattern_label 直方图
   - 最强 5 个 candidate 的 candidate_aligned_future_return_pct 分布
2. 这只是观测，不改 candidate / risk / live。但它能直接回答：
   "这些 0 交易窗口里 alpha 是真不存在，还是被 setup_model 一律压成 neutral？"
```

### 2.11 多币宇宙被关在 discovery 阶段，没有 staged forward path

**证据**：

- `current.md §multi-symbol target proof / multi-range-action target-slice`
  反复证明多币 discovery 的离线 alpha 比 ETH-only 强（h6/h12 强子切片正期望）。
- 但唯一推进路径是"先在 ETH-only 上过 promotion gate，再考虑多币"——而 ETH-only
  又因为 §2.1 数学上不可达，所以多币线被无限挂起。
- 多币 setup model `setup_edge_model_multi_symbol.json` 已存在，但没有任何
  multi-symbol walk-forward 提交过 realized return 数字。

**最小修复**：

```text
1. 把多币线明确成"独立 paper-only research track"，与 ETH-only 主线并行：
   - 不和 ETH-only 共用 promotion gate
   - 自有 G_paper'：累计 traded >= 20、sum_realized > 0、去最大窗后仍 > 0
   - 仍然不开 live
2. 多币 walk-forward 必须用 multi-symbol setup_model，不用 ETH-only 的
3. 多币与 ETH-only 之间共用的代码（candidate_filter / risk_engine / orchestrator）
   要保证多币不会回踩 ETH-only 的窄 gate 和 deterministic override
   （目前 orchestrator override 对单标的 + max_open_positions=1 有 guard，
   多币 max_open_positions=3，应该自动不触发，但要加显式断言）
```

### 2.12 Kronos 评估口径只写了"不做"

**证据**：

- `current.md §Kronos 评估口径` 详细写了"晋级条件"与"允许的推进方式"。
- 实际从未跑过任何 Kronos artifact。

**最小修复**：

```text
1. 接受现状："不接入交易链路"是对的；不要因为 §2.4 setup_model 升级慢就
   去 import Kronos
2. 但允许做一个最小 offline overlay：
   - 单独脚本，不动 src/qount
   - 输入：state/research_runs 已有窗口
   - 输出：每个窗口对应 Kronos directional_accuracy / post-cost edge / 与
     setup_model 的差异
3. 没有 §2.4 setup_model v2 之前不投入；§2.4 跑完再决定 Kronos 是否还有信息增量
```

---

## 3. 优化路线（按 ROI / 风险排序）

把 §2 里的修复打包成可执行 track。每个 track 都给：触发条件、产出、终止条件。
所有 track 在它结束之前**不**新增 entry gate / live / forward paper。

2026-05-31 执行状态：

```text
T-A  已落地：docs/holdout.md 已冻结 discovery_pool / validation_pool_v1，并定义 G_paper / G_live。
T-D  已落地：AI 决策缓存、setup-edge-walk-forward、candidate-walk-forward、Mac->WSL sync/test 脚本已实现。
T-G  已落地第一版：readiness 命名已改为 offline_future_edge_readiness；idle-window-diagnostic 已跑完 ETH-only root 诊断。
T-B  已落地第一版：ai-hold-baseline 已复现 WS-4 fast-SMA 24/24 stored hold。
T-C  已落地第一版 plumbing：v2_interactions + setup-model-compare 可跑；首轮 ETH-only 读数不支持替换主线。
```

```text
T-A  Holdout 与 promotion gate 重设           （文档级，零代码）
T-B  AI hold-bias 量化与 prompt 实验           （研究级，零代码改 live）
T-C  setup_model v2 交互项                    （研究级，新模型不替换主线）
T-D  实验工具优化（AI 决策缓存 / 命令拆分）    （工程级）
T-E  candidate_filter 窄 gate 集合化           （工程级，0 行为变化）
T-F  research / production 类型隔离            （工程级，0 行为变化）
T-G  0 交易窗口诊断 + readiness 三档命名       （研究观察级）
T-H  多币 paper-only 独立 track                （研究 paper 级）
T-I  Kronos offline overlay                   （研究 artifact 级）
T-J  WS-1 持仓 horizon 重做（用拆分后的工具）  （研究级）
```

### T-A — Holdout 与 promotion gate 重设（**先做**，零代码）

> 修 §2.1 + §2.2。所有后续 track 共用这套 holdout，所以必须最先做。

任务：

1. 把现有 13 窗口冻结为 `discovery_pool`（已被反复回看）。
2. 选取**今天之后**的真实 forward 时间段为 `validation_pool_v1`（例如
   2026-06-01 起的滚动 14 天，每 24h 一个 1h-3h 窗口）。
3. 在 `docs/holdout.md` 写明哪段是哪段，artifact 里加字段
   `holdout_role: discovery | validation_v1 | unknown`。
4. 重写 promotion gate 为 G_paper / G_live 两级（见 §2.1 修复）。

终止条件：`docs/holdout.md` 提交、新 promotion 文档替代 §4 完成。
完成前 §3 的其他 track 不读"是否过 gate"这个问题，只读"是否在 discovery 池上
形成假设"。

### T-B — AI hold-bias 量化与 prompt 实验

> 修 §2.3。是 WS-4 step 3 失败之后**最值得做的一件事**。

阶段：

1. **量化基线**：在 `discovery_pool` 上对每个 fresh-entry candidate 重发 prompt
   N 次（N=3..5，温度=0.0 时也要看是否 deterministic），记录 hold rate。
   产出 `state/research_runs/.../ai-hold-baseline.json`。
2. **冻结 prompt v2 / v3 假设**（在看 validation_pool_v1 之前）：
   - v2：删除 default-wait 兜底语句，保留 terminal_risk 反对项。
   - v3：让 AI 在 setup_model.quality=strong_favorable 时只能 hold-with-reason。
3. **once-only 验证**：在 `validation_pool_v1` 上用 v2/v3 vs baseline 对比 hold
   rate / candidate-aligned future return / realized return（用 §3.T-D 的
   AI 决策缓存把同一 snapshot 的多 prompt 跑成 batch）。
4. **回收**：
   - 若 v2/v3 在 validation 上把 hold 率砍下来且 realized 不变差 → 替换主线 prompt。
   - 若不变好或变差 → 回归 baseline，并接受"AI 在当前 setup model 下就是这么保守"，
     转 T-C。

终止条件：在 validation_pool_v1 上得到至少一个明确的 win/tie/lose 读数。
**不允许在 discovery_pool 上调阈值后再去 validation。**

### T-C — setup_model v2 交互项（中期最大杠杆）

> 修 §2.4。这是把 discovery 真正接入决策的桥梁。

阶段：

1. 拆 `setup_model.py` 出一个 v2 训练函数（旧函数保留为 v1）：
   - phase × sma_fast_bin / sma_slow_bin / range_pct_bin / return_24bars_bin
     等 hand-crafted 交互。
   - 同特征空间，每 phase 一个 ridge 子模型。
2. 离线评估（不动主线 setup_model）：
   - 在 `discovery_pool` 上训练，在 `validation_pool_v1`（来自 T-A）上读
     calibration / AUC-like / post-cost lift。
   - 必须满足"对现有 4 笔正收益开仓的预测均值 >= v1"这一最低 sanity。
3. 上线条件：上面 sanity 通过，且在 holdout 上的 candidate-aligned signed lift
   显著 > 0。
4. 上线方式：仍走 `setup_model_path`，新加 `setup_model_version` 字段；
   `predicted_edge_pct / confidence_ratio / quality` 接口不变，
   `candidate_filter` 与 prompt 都不需要改。

终止条件：在 holdout 上证明 v2 优于 v1，或证明不优于 v1（接受现实并转 T-I 评 Kronos）。

2026-05-31 进展：第一版 `v2_interactions` 已落地，v1 默认路径不变。新增
`setup-model-compare` 做 chronological train/eval split，并允许研究命令显式
`--setup-model-version v2_interactions`。

WSL 默认相位 artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260531T075127Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-20260531/qount-setup-model-compare-ethonly-v2-20260531.json
```

读数：`example_count=705`、`eval_example_count=212`；
`v2_minus_v1_top_decile_avg_target_edge_pct=-0.0002249732`，`v2_minus_v1_mae=+0.0000124423`。

WSL 包含 `range_noise` artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260531T075351Z-setup-model-compare-qount-setup-model-compare-ethonly-v2-range-20260531/qount-setup-model-compare-ethonly-v2-range-20260531.json
```

读数：`example_count=19681`、`eval_example_count=5905`；
`v2_minus_v1_top_decile_avg_target_edge_pct=+0.0001926716`，但
`v2_top_decile_avg_target_edge_pct=-0.0013618186`，`v2_minus_v1_mae=+0.0000053851`，
`v2_strong_favorable=0`。

结论：第一版 v2 交互项 plumbing 成功，但 lift 不够，不能替换主线 setup model。
下一步若继续 T-C，只做 targeted ablation / calibration，先找出哪些 interaction
真的贡献 lift；不能把这版 v2 接进 gate。

### T-D — 实验工具优化（AI 缓存 + 命令拆分 + Mac/WSL 同步脚本）

> 修 §2.7 + §2.8。**与 T-A 并行做**，因为它放大所有后续 track 的速度。

任务：

1. AI 决策缓存：见 §2.7 修复 1。落 `state/research_cache/ai_decisions/`，
   按 `(snapshot_hash, prompt_version, model_id, temperature)` 分桶。
2. `walk-forward` 拆出 `setup-edge-walk-forward` 与 `candidate-walk-forward`
   两个命令（§2.8 修复）。
3. `scripts/sync-to-wsl.sh` 与 `scripts/run-wsl-tests.sh`，统一 Mac→WSL 流。
4. 所有研究命令默认开 `--max-cycles 50` 当 dry-run，`--no-max-cycles` 才完整。

终止条件：能在 5 分钟内跑完一次 9-window 缓存命中复跑（当前需要小时级）。

### T-E — candidate_filter 窄 gate 集合化（行为不变的工程化）

> 修 §2.5。**只在 T-A/T-B/T-D 完成之后**做，因为它要保证 0 行为变化，需要对照
> 多次 walk-forward 复跑。

任务：

1. 列出 5 条 ETH 窄 gate 的触发条件矩阵。
2. 把单测从"具体 run 输入复制"改成"基于 axis 输入断言 reason"。
3. 在 `discovery_pool` 上对 v1/v2 candidate_filter 做 100% 等价回归。

终止条件：所有 13 窗 walk-forward artifact 上 v1/v2 行为字段（filtered_hold /
fresh_entry_selected / reasons）逐 cycle 等价。

### T-F — research / production 类型隔离

> 修 §2.6。**与 T-E 并行**。零行为变化，只动类型 / 入口。

任务：

1. 拆 Settings / ResearchSettings；apply_research_profile 只产 ResearchSettings。
2. CandidateFilter.apply / RiskEngine 关键入口加 `assert isinstance(...)`。
3. `--research-shadow-candidate-tags` 只接 ResearchSettings。
4. live 入口 (`run-once` / `Orchestrator` 在 live 模式) 拒绝 ResearchSettings。

终止条件：本地 + WSL 单测全绿；Smoke：`run-once` paper 路径 / 各研究命令路径都
能跑通。

### T-G — 0 交易窗口诊断 + readiness 三档命名

> 修 §2.10 + §2.9。便宜且能立刻产出结论。

任务：

1. `idle-window-diagnostic` 命令（见 §2.10 修复）。
2. readiness 三档（`offline_future_edge_readiness` / `link_ready` /
   `promotion_ready`）。第一档对应当前 `shadow_candidate_readiness`，第二档
   要求历史 fresh_entry_selected ≥ 1，第三档要求 holdout 上的 realized return
   非零且非负。

终止条件：在 9-window 上跑完一次诊断，回答"0 交易窗里有没有被 setup_model 整体
压住的潜在 alpha"。

2026-05-31 进展：`idle-window-diagnostic` 已落地并在 WSL 对
`state/research_runs` 运行 ETH-only 诊断。artifact：

```text
/home/alyaloale/Code/qount/state/research_runs/20260531T072108Z-idle-window-diagnostic-qount-idle-window-diagnostic-ethonly-20260531-v2/qount-idle-window-diagnostic-ethonly-20260531-v2.json
```

读数：`39` 个 backtest 中跳过 `3` 个有成交窗口，诊断 `36` 个 idle 窗；
`candidate_filter_hold_count=2878`、`ai_hold_count=87`、
`positive_top_candidate_avg_future_edge_windows=5/36`。setup quality 为
`missing=2867 / unfavorable=72 / weak_favorable=12 / neutral=4 / strong_favorable=0`。

结论：没有看到"0 交易窗里大量 strong_favorable alpha 被 setup_model/AI 压掉"的证据；
主要 blocker 是 ETH short research 边界、range-noise 结构要求、低波动/低成交量。
因此 T-G 已回答第一版问题，后续只能作为诊断入口，不能直接产出 entry gate。

### T-H — 多币 paper-only 独立 track

> 修 §2.11。在 T-A、T-D 完成后启动。

任务：

1. 多币 walk-forward 用 `setup_edge_model_multi_symbol.json`，跑
   `discovery_pool_multi`（用 13 窗的同区间但 4 个标的），读
   sum_realized / traded_count。
2. 把多币 promotion gate 写成独立的 `G_paper_multi`，与 ETH-only 不共用。
3. 不开 multi-symbol live，不开 multi-symbol forward paper（在 T-B/T-C 给出
   足够证据前）。

终止条件：拿到一份"多币 paper-only" baseline 数字（哪怕是亏的），不再因为 ETH-only
先打头而被无限阻塞。

### T-I — Kronos offline overlay（仅在 T-C 决定 v2 不优于 v1 时启动）

任务：

1. 单独 `scripts/kronos_overlay.py`，输入 `state/research_runs` 已有窗口。
2. 输出 directional_accuracy / post-cost edge / vs setup_model 差异的 JSON。
3. 不 import 进 src/qount。

终止条件：得到一份"Kronos 在已有 holdout 上是否比 setup_model 提供独立增量"的
明确读数。

### T-J — WS-1 持仓 horizon 重做（用拆分后的工具）

> 修 §2.8 + 把 WS-1 一年级失败的真因（h12 + loose trailing 收尾不干净）解开。

任务：

1. 用 `setup-edge-walk-forward` 跑 h6 vs h12 vs h24，比较预测质量本身。
2. 仅在 h12/h24 预测明显优于 h6 时，再跑端到端 walk-forward；并且必须用
   "hard timeout" 退出（例如 close_after_bars=12），先排除 trailing 收尾问题。
3. 任何"留下未平仓浮盈"的实验直接舍弃，不再当读数。

终止条件：要么得到 h12 端到端优于 h6 的明确读数（推动主线换 horizon），
要么明确证伪后关闭 WS-1。

---

## 4. 优先顺序总结

```text
已完成前置：
  T-A  holdout 与 promotion gate 重设
  T-D  实验工具优化（AI 缓存 / 命令拆分 / 同步脚本）

紧接（最大策略杠杆）：
  T-C  setup_model v2 targeted ablation / calibration（第一版 v2 不够）
  T-B  AI hold-bias 量化与 prompt 实验（第一版工具已完成）
  T-G  0 交易窗口诊断（第一版工具已完成）

并行的工程化（行为不变）：
  T-E  candidate_filter 窄 gate 集合化
  T-F  research / production 类型隔离

策略扩展（仅在前置 track 给出正读数后）：
  T-J  WS-1 持仓 horizon 重做
  T-H  多币 paper-only 独立 track

兜底（仅在 T-C 失败时启动）：
  T-I  Kronos offline overlay
```

---

## 5. 不做（与 current.md 一致 + 本评审新增）

```text
不开 live / 不 forward paper（在 G_paper / G_live 全过之前）。
不为 0 交易窗硬造 gate；本评审新增：不在 T-A 之前再"复用"任何 13 窗结果做 promotion。
不放宽 broad range_noise / short_rebound_fail / pullback。
不在一轮里同时改 entry / management / setup_model / prompt（与 current.md 一致）。
不把 Kronos 接进 candidate / risk / live。

本评审新增：
  - 不在已经被回看过的 13 窗（discovery_pool）上调任何 prompt / gate / 阈值
    再以同一窗的 realized return 当晋级证据。
  - 不在 setup_model v2 的 holdout 评估里参考 v1 的同窗 realized return。
  - 不在 multi-symbol 主线推进前修任何与 ETH-only 共用的窄 gate。
```

---

## 6. 与现有文档的关系

- [current.md](current.md) 仍是"当前状态真相"。本文件与它**不冲突**：
  current.md 给"当前不能做什么 / 已确认的窄修复"；本文件给"下一步怎么破局"。
- [profit-research-plan.md](profit-research-plan.md) WS-1..WS-4 仍然有效，
  但在本评审看来，它们都跑在"discovery_pool 已被污染 + AI 全 hold + setup_model
  线性"这三件事的影响下。本文件的 T-A/T-B/T-C 是 WS-1..WS-4 之前要先解的前置。
- [quick-handoff.md](quick-handoff.md) 接手命令仍然有效。新增 T-D 后，
  优先用脚本而不是 here-doc。

任何在本文件方向上做出的实质改动，按既有纪律：

```text
单测 -> WSL 单测 -> 完整 walk-forward 或对应拆分命令 -> 写回 current.md
-> 写回 update-log.md -> 用 persistent_artifact_dir / persistent_artifact_path
   引用 artifact，不再依赖 /tmp。
```
