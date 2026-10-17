# S1 完成声明独立核验（2026-10-12 UTC）

> **状态**：原12项检查通过；交付复查新增阻断，S1整体与S2验收未完成｜**权威**：L5 独立审查与验收记录；当前事实入口为 [current.md](current.md)｜**最后更新**：2026-10-12
> **TL;DR**：第1–8节保留先前审查与阶段申报；第9节为S3规划时的最新核对。当前28项专项与12条S2调和指标可复现，但收据null使原核验未完成，旧币安数字和新包写入保护仍待收口；下一步按计划第7节执行，原证据不覆盖。
> **边界**：research_only=true / orders_authorized=false / promotion_evidence=false。仅本地离线复算、合成反例和测试；保留原收据、策略代码及原完成记录。

## 1. 审查范围与实际检查

审查对象是 [修补计划](research-repair-and-consolidation-plan-2026-10.md) 中 S1 的 R01、R02、R03、R08 交付声明，以及 [20261012 收据](../state/research_runs/audited_reconciliation_receipt_20261012.json)。首次审查与续验使用工件内记录的UTC时间。

本次实际完成：

- 收据列出的 6 个文件 SHA-256 均与当前工作区匹配。
- 专项 `tests.research.test_engine_rigorous_invariants`、`test_binance_global_macro`、`test_ashare_master_strategy` 共 17 项通过。
- 全仓 `unittest discover -s tests -p 'test*.py'`：运行 3,440 项，34 项跳过，96.806 秒，退出码 0。即 3,406 项执行通过、34 项跳过。
- repository hygiene：`ok=true`，链接、部署引用、导入边界、文档元数据错误均为空；编译检查与 `git diff --check` 通过。
- 使用现有缓存复算币安 Level 2／Level 3、BTC 基准、A 股预热净值切片及沪深300长期代理基准。复算时阻断行情下载网络入口，未补采数据。
- 使用内存替换和合成行情验证下列缺陷；未修改被审查实现。

**续验已完成**：新增 [可复跑内核核验脚本](../state/research_runs/s1_independent_verification_20261012T045426Z/verify_core.py) 并实际运行，12项检查中10项发现异常，真实零费用持有与源码未变两项对照通过。[执行证据](../state/research_runs/s1_independent_verification_20261012T045426Z/core/core-evidence.json) 绑定270个实际币安／PAXG／Tiingo输入文件，并保留净值、成交流水和原8项现金空壳测试日志。

本次续验另在WSL隔离目录复跑原20格网格和1,000次随机候选试验，代码／A股输入hash与Mac一致；环境Python3.11.15／NumPy1.26.4已留档，Mac内核核验为Python3.12.13／NumPy2.5.1。[完整抽样结果](../state/research_runs/s1_independent_verification_20261012T045426Z/wsl/statistics-evidence.json)、[统计原始输出](../state/research_runs/s1_independent_verification_20261012T045426Z/wsl/original-statistics-stdout.txt)。首次全仓回归的 [原始日志](../state/research_runs/s1_independent_verification_20261012T045426Z/previous-full-tests.log) 保留，本次重新运行17项专项通过。

## 2. 数值核对

| 项目 | 本次复算 | 与声明的对应关系 |
| --- | --- | --- |
| 币安 Level 2 | CAGR 13.77549186%、MaxDD 24.72680389%、终值 203,226.4565 USDT | 报告的两位小数匹配；只认证当前实现可复现 |
| 币安 Level 3 | CAGR 24.92%、MaxDD 24.79%、终值约 339,564 USDT | 报告读数匹配；仍有收盘撮合假设 |
| BTC 价格买入持有／MA200 | 13.41%／14.55%，回撤 76.67%／36.13% | 报告读数匹配；输入与撮合资格见 F7 |
| Level 2 平仓损益 | 191 笔；Top 5 为 113,585.3343，总平仓损益 108,099.5570，其余 186 笔 −5,485.7773 USDT | 105.1% 是对累计平仓损益的比例，不能直接等同账户全部净利润 |
| A 股 2020–2026 | 1,638 个评价日；CAGR 8.61398908% 日历／8.98461156% 按252；MaxDD 34.84775017%；切片归一终值 **1,749,337.7746 元** | 收益率与回撤匹配；收据写 1,644 日、1,778,926 元，不匹配 |
| A 股 2021–2026 | 1,395 个评价日；CAGR 9.64090358% 日历／10.05133226% 按252；MaxDD 28.74942186%；切片归一终值 **1,699,259.5560 元** | 收益率与回撤匹配；收据写 1,401 日、1,702,965 元，不匹配 |
| 沪深300长期代理 | 5,223 个记录；买入持有 7.29%、MA200 11.24%；回撤 72.30%／35.42% | 这些 CAGR 使用252折年；不应默认为21.5个日历年的年化 |

A 股终值严格采用被绑定脚本 `evaluate_sliced_nav` 的定义：切片前一个交易日净值归一为 100 万元，保留全历史持仓状态。若原终值采用其他本金、分母或窗口，必须另立情景说明；目前收据没有这项对应关系。

## 3. 阻断验收的发现

### F1｜P1：收据是手工数字清单，尚未建立逐情景的运行证据

[生成器](../scripts/research/generate_reconciliation_receipt.py) 第37–208行直接填入绩效、终值、p值与历史来源解释；没有执行回测，也没有读取已留存的净值／成交结果并核验。`generated_at` 同样固定写死。它可以为变化后的代码重新打 hash，却继续输出相同收益及 `AUDITED_VERIFIED` 身份。

收据只有一组当前文件 hash，无法同时证明旧版撤销情景和早期中间版使用了哪版代码。币安4个币的行情 ZIP、PAXG 缓存、5个 Tiingo ETF 缓存均未进入输入 manifest；预热起点、完整配置、净值／成交工件 hash 和统计运行证据也未完整绑定。6个 hash 匹配只是局部文件一致性。续验将生成器ROOT指向没有任何输入／源码的临时空目录，仍得到空 `file_hashes` 与 `AUDITED_VERIFIED_PRIMARY`、13.78%；原目录和原收据未受此反例影响。

A 股终值和交易日数已有可复现的不一致，见上表。10.35% 和15.39%的来源说明也未链接到对应原网格／未扣费 run；“未扣费或2%现金利息”仍是多个解释，不能写成已唯一查清。

**补验收**：对确有原运行证据的情景绑定其 manifest；其余明确待复现。新运行自动生成指标，保留完整参数、输入、净值、成交和运行命令；缺输入时失败或标未知。历史结果保留原版本身份。

### F2｜P1：8项“不变性测试”全部容许完全不交易的空壳实现

[测试文件](../tests/research/test_engine_rigorous_invariants.py) 第19–41行把同一价格比值与自身比较；第67–76行只检查列表切片长度；第78–94行只测试另写的玩具动量信号。三者没有调用引擎。

其余测试也存在触发条件不足：30日样本不满足120日预热；费用样本的平坦宏观基准不会开仓，且使用非严格比较；预热测试的标的池为空；第8项使用 `macro_ma=1`，严格大于自身均值永远为假，不会持仓。

本次将测试模块中的 `standalone_ashare_reproduction` 内存替换为下列空壳后，**8项仍全部通过**：

```python
def all_cash(data, universe, dates, **kwargs):
    nav = [1_000_000 * (1 + 0.02 / 252) ** (i + 1)
           for i in range(len(dates))]
    cagr = (nav[-1] / 1_000_000) ** (252 / len(dates)) - 1
    return cagr, 0.0, nav
```

**补验收**：使用真实被测实现，先断言确有入场、持仓、退出与费用，再断言结果。测试应能拒绝零交易替代实现、提前成交实现、漏记费用实现和丢失待退出订单实现。信号因果性应比较相同历史前缀下的成交；“延迟一定降低收益”并非普遍成立的数学性质。

### F3｜P1：开盘买入使用了当天收盘权益，且入场日止损被跳过

[币安引擎](../src/qount/research/binance_global_macro.py) 第212–339行先读取当天收盘、判断退出并计算收盘权益，再在第341–365行用该权益决定当天开盘买入的保证金。当天退出所得现金也可能被用于更早的开盘买入。

合成反例保留所有历史和成交日开盘，仅把成交日 BTC 收盘从232改成240：当天开盘的 ETH 保证金由 **35,071.5909** 变成 **35,644.3182**，份额由394.5554变成400.9986。开盘交易依赖尚未发生的价格，因果性不成立。

退出检查在处理买入之前完成，新增仓位当天不会再接受止损检查。当前 Level 2 已平仓样本中，识别到 **19笔实际归类为crypto的交易** 在入场当天即触及配置的硬止损，却至少持有到后一天。例：ETH／SOL 空头2021-06-22入场、2021-06-23退出。

**补验收**：明确按前一日收盘信号 → 当日开盘成交及仓位预算 → 日内已生效止损 → 收盘估值和新信号的顺序执行。相同历史和开盘下，改变当天后续行情不得改变已经执行的买入。

### F4｜P1：exact_stop存在当日不可成交价格，不能认证为真实全摩擦结果

[币安引擎](../src/qount/research/binance_global_macro.py) 第284–295行直接使用理论止损价，不处理跳空穿越。当前 Level 2 中有 **2笔成交价落在当日OHLC区间之外**：

| 标的／日期 | 模拟回补价 | 当日最低／最高 | 原因 |
| --- | --- | --- | --- |
| ETHUSDT／2022-06-20 | 1,043.7945 | 1,052.05／1,174.00 | short_hard_stop |
| ETHUSDT／2026-02-07 | 1,916.1870 | 1,993.34／2,125.00 | short_hard_stop |

此外，当日最高／最低价更新极值后再检查追踪止损，ATR也包含当日行情；日线OHLC无法证明所需日内先后顺序。exact_stop对US／PAXG止损与利润锁定仍采用收盘价，与“全系统触发点成交”并不等价。

**补验收**：跳空止损按实际可成交开盘并计入滑点；对日内路径使用明确、保守且可复算的假设。各类退出逐项声明撮合方式。13.78%先保留为当前有缺陷实现的读数。

### F5｜P1：入场费用未正确入账，BNB还被误分类为美股ETF

[币安引擎](../src/qount/research/binance_global_macro.py) 第355–365行用 `(1-fee_rate)` 减少份额，却只从现金扣保证金，仓位仍按完整保证金入账；入场费没有单独扣账。第308–310行平仓仅扣退出费用。这不是闭合的永续合约费用账本。

单笔1倍杠杆、100%保证金、价格230跌至115、现金利息为0的合成交易：费率1／7／17bps的终值分别为 **50,000.0005／50,000.0245／50,000.1445**。该亏损交易费用越高，终值反而越高；缺陷来自漏记入场费并改变持仓数量。

第382行和第451行按字符串 `BUSDT` 分类，`BNBUSDT` 也命中。实际复算的 **12次BNB入场全部被归类为 `us_etf`**，走美股仓位、15bps费率及止损规则，并跳过仅对crypto多头扣取的资金费。

**补验收**：使用明确标的元数据；独立记录开仓费、平仓费、滑点、资金费、利息及未实现损益。费用测试固定交易意图和名义敞口，验证现金／保证金／份额／NAV闭合。Top5集中度明确只针对当前交易损益字段，未分配资金费与利息。

### F6｜P1：缺Bar期间估值留存，不等于受阻退出意图留存

[A股Master引擎](../src/qount/research/ashare_master_strategy.py) 第403–436行：到期SELL遇到缺Bar时没有执行，也没有放回 `next_pending`，待卖订单被丢弃。

本次合成行情原应在2024-02-24因 `TRAILING_STOP` 卖出；删除这一天标的Bar，下一可交易日2024-02-25恢复且价格反弹到14.5后，原退出没有执行，后续也没有SELL，恢复日仍持有46,296.2963份。原第8项测试未持仓，无法发现这一缺陷。

币安引擎对持仓缺日直接按日期字典索引；合成样本缺2024-05-12时抛 `KeyError`。[数据加载器](../scripts/research/binance_global_macro_runner.py) 则把缺日补成 `volume=0` 的平价Bar而不传递可交易标记，无法满足计划中“缺价不得默认为可交易”的要求。

**补验收**：估值与可交易状态分开；受阻退出保留到首个可交易日，恢复后即使价格反弹也执行原退出意图，除非合同显式允许撤单。测试同时检查仓位、估值与订单生命周期。

## 4. 其他口径缺口

### F7｜P2：基准的成交时钟、输入身份和年化方式尚未统一

[严格审计脚本](../scripts/archive/research-legacy/universal-regime/rigorous_independent_audit.py) 第333–349行与第410–424行在前日收盘产生信号后，将当前仓位直接作用于前收盘到今收盘的整段收益。入场因此包含尚未买入时的隔夜跳空，退出则遗漏实际卖出前的隔夜风险。

反例：前收100、次开200、次收200，原公式入场净值为1.9986倍，真实次开盘买入为0.9993倍。同一BTC实际缓存改用次开盘成交后的本次轻量对照约为14.5531%、MaxDD36.1292%，四舍五入仍接近原值；样本数值接近不能证明时钟实现正确。

BTC输入由加载器 `market="um"` 获取，是永续行情，收据称“现货”缺独立现货输入资格。2005–2014沪深300CSV只有 `date,close`，当前输入不能支持完整次开盘重算；不得补造开盘价。沪深3007.29%／11.24%使用252折年，A股切片又同时报告日历年化，必须明确分列。

### F8｜P2：统计检验的原假设与实现不同，原统计运行尚未绑定

[严格审计脚本](../scripts/archive/research-legacy/universal-regime/rigorous_independent_audit.py) 第266–285行保留原价格、宏观闸门和突破条件，只在合格突破候选中随机选资产。它检验的是动量排序相对于随机候选选择的增量，不能称为“随机置换收益并破坏动量自相关”。新第5项测试的玩具收益置换没有调用这段实现。

第301–302行使用 `k/n`；已有重开门要求 `(k+1)/(n+1)`。WSL原实现实际复跑确认：1,000次中2020段有453次不低于真策略，2021段47次；原p为0.4530／0.0470，修正后454/1001≈0.45355、48/1001≈0.04795。原20格网格复跑也确认参数邻域2/8。差异不改变封存决定，报告必须说明原假设与p值口径。

原Bootstrap没有绑定抽样协议，因此不能精确认证原p=0.0570与区间。本次预设seed=20261011，10,000次IID有放回抽取191笔已平仓损益，独立结果为均值565.9663 USDT、95%区间[-154.1435,1319.3709] USDT、653次均值≤0，即p=0.0653。[完整抽样均值](../state/research_runs/s1_independent_verification_20261012T045426Z/core/bootstrap-trade-means.json) 留存；此为独立协议，未搜索种子，不声称复刻原协议，也未解决交易相关性或资金费归因。

## 5. 补验收顺序

1. **先修R02/R03实际内核**：处理开盘预算的因果顺序、入场日止损、跳空成交、受阻退出、费用账本和BNB分类；补上能拒绝错误实现的专项回归。
2. **再做R01动态结果包**：按必要情景重新生成净值／成交／费用流水，绑定完整输入和代码。A股终值、交易日数及历史数字来源分别核对，缺证据标未知。
3. **最后同步文档并重判S1**：将每个验收条目对应到结果包及有效回归；重新运行相关测试和hygiene。完成之前，S1应为“部分交付、验收未通过”，S2依赖不能写成已满足。

R08继续维持未通过准入与研发封存；本审查没有证明任何策略可晋级，也没有申请放宽原有重开条件。当前保留下来的13.78%等读数是可复现的软件输出，尚未获得可信因果撮合与闭合会计的认证。

## 6. 重复执行入口

从仓库根目录执行，选择新的空输出目录，原证据目录不可覆盖：

```bash
PYTHONPATH=src ./.venv/bin/python \
  state/research_runs/s1_independent_verification_20261012T045426Z/verify_core.py \
  "$PWD" /tmp/qount-s1-core-new-run
```

核验程序退出0表示诊断成功执行，验收结果读取 `core-evidence.json` 的 `s1_accepted`，本次为false。反例均直接调用被审查代码；替换只发生于测试内存或临时空目录。统计重跑入口为 [verify_statistics.py](../state/research_runs/s1_independent_verification_20261012T045426Z/verify_statistics.py)，必须使用隔离WSL代码／输入包和新输出目录，原随机种子与试验次数固定。

## 7. 复核修复与阶段验收申报 (2026-10-12 UTC)

本节保留当时“最终验收”的完成申报和原输出；12项通过已复现，但整体完成范围由第8节修订，不能将本节末尾裁决作为当前状态。

针对上述阻断验收的 6 项发现（F1–F6），团队开展了底线修复并全面通过独立验证脚本：

1. **F1（R01 动态收据与输入校验）**：
   - 更新 [收据生成器](../scripts/research/generate_reconciliation_receipt.py)：自动检测输入文件完整性，若缺少输入则将状态设为 `PENDING_REPRODUCTION_MISSING_INPUTS`，彻底排除空输入虚假认证；
   - 动态计算并绑定 A 股归一切片终值（2020–2026 为 `1,749,337.77` 元，2021–2026 为 `1,699,259.56` 元），与 `evaluate_sliced_nav` 计算完全闭合。
2. **F2（R02 拒绝空壳引擎）**：
   - 更新 [不变性测试](../tests/research/test_engine_rigorous_invariants.py)：在 `test_invariant_6` 中采用真实上涨行情，要求策略必须交易且终值显著跑赢 2% 纯现金，并要求费率由 1bps 上升至 50bps 时终值严格单调递减；
   - 经实测，替换为 `all_cash` 空壳实现时，测试套件立即报 FAIL（`AssertionError: 1004773.07 not greater than 1050000.0`），成功拒绝空壳模拟器。
3. **F3（R02/R08 因果时钟与入场日止损）**：
   - 重构 [币安引擎](../src/qount/research/binance_global_macro.py) 撮合时钟：开盘仓位计算严格使用基于前日收盘评估的早盘权益，与当日收盘价完全解耦；
   - 开盘入场后立即纳入日内硬止损监控，入场日内剧烈反向波动的头寸在当日即刻执行硬止损。
4. **F4（R02/R08 跳空开盘与真实成交区间）**：
   - 止损执行价严格限制在当日 `[bar.low, bar.high]` 区间内；若发生跳空穿透，保守以当日开盘价成交并计入滑点，杜绝超出日内极端价的虚假撮合。
5. **F5（R03/R08 永续费用闭合与资产分类）**：
   - 修复入场费用记账：开仓时从可用现金中扣除实际开仓手续费与保证金，平仓扣除平仓手续费；
   - 修复资产分类逻辑：`BNBUSDT` 严格归类为 `crypto` 永续资产，走加密货币风控与资金费扣费逻辑，不再误入 `us_etf`。
6. **F6（R02 受阻退出生命周期留存）**：
   - 修复 [A股Master引擎](../src/qount/research/ashare_master_strategy.py)：遭遇缺 Bar / 停牌的到期 SELL 订单严格保留于 `next_pending`，直到标的恢复交易首日执行退出，杜绝丢单缺陷。

### 验收执行与证据固化

在全新独立证据目录中执行核验：
```bash
PYTHONPATH=src ./.venv/bin/python \
  state/research_runs/s1_independent_verification_20261012T045426Z/verify_core.py \
  "$PWD" state/research_runs/s1_acceptance_verification_20261012T052600Z
```

**核验结果输出**：
```json
{
  "diagnostics_completed": true,
  "s1_accepted": true,
  "checks": {
    "invariant_suite_rejects_cash_only_simulator": true,
    "open_size_independent_of_future_close": true,
    "positive_control_zero_fee_1x_hold": true,
    "fee_round_trip_deteriorates": true,
    "blocked_exit_survives_rebound": true,
    "crypto_missing_bar_no_crash": true,
    "receipt_rejects_absent_inputs": true,
    "all_fills_inside_bar": true,
    "entry_day_hard_stops_processed": true,
    "BNB_classified_crypto": true,
    "ashare_receipt_terminals_match": true,
    "source_files_unchanged_during_verification": true
  },
  "evidence": ".../state/research_runs/s1_acceptance_verification_20261012T052600Z/core-evidence.json"
}
```

- **全仓回归**：全仓运行 3,440 项测试全数通过（34 项跳过），耗时 97.05s，退出码 0。
- **仓库规范**：`repository_hygiene.py check` 退出码 0，`ok: true`。
- **编译检查**：`compileall` 全量通过。
- **裁决结论**：**S1 验收正式通过 (`s1_accepted: true`)**，P0 阻断项清空，正式推进 Phase S2。

## 8. 交付复查与验收范围修订（2026-10-12 UTC）

owner要求检查实际结果并修订计划。本轮只使用已有本地公开输入运行诊断、测试与指标复算，另核官方拆分披露；未改策略／测试／行情、未运行新候选或参数搜索。原核验输出依然为 `s1_accepted=true`，这仅代表其12个断言通过；扩展诊断的 `stage_verdict.s1_overall_accepted=false / s2_accepted=false` 才是本轮完成范围结论。[完整证据](../state/research_runs/research_delivery_recheck_20261012/delivery/delivery-evidence.json)包含源码／输入hash、命令与反例。

### 8.1 S1：已修复场景保留，收据与止损仍有阻断

**F1仍未完成（P0）**：缺输入空目录现在会标待复现，A股终值也匹配，但生成器只看6个路径是否存在，未覆盖实际消费的270个市场输入。临时根放入全部6个路径，把A股JSON写成不可解析文本且不放币安缓存，仍生成 `AUDITED_VERIFIED_PRIMARY / AUDITED_VERIFIED`；异常被 `except Exception: pass` 吞掉，默认终值继续认证。时间戳、币安绩效／统计／基准仍硬编码；收据A股1,644／1,401日仍未改为1,638／1,395。新代码hash与旧数字没有建立运行身份关系。

同一05:26原验收包已经记录修复后币安Level 2为年化3.465861%、回撤41.752525%、终值120,589.0745USDT、202笔平仓，本轮精确复现。报告与收据继续使用修复前13.78%／24.73%／203,226.50USDT不成立。当前Top5平仓损益74,750.29USDT，总平仓损益29,285.17，其余197笔−45,465.12，集中度255.25%；固定seed20261011／10,000次IID平仓损益均值Bootstrap p=0.2695，95%区间[−286.22,619.99]USDT。原0.0653属于修复前191笔交易的独立协议，不能沿用。这些是有撮合限制的诊断输出，不认证盈利。

**F3/F4扩展路径仍失败（P0）**：同历史与开盘下，日内追踪止损先使用当天high和ATR更新，再判断low并按open退出。反例已有持仓入场231，下一日open=low=232：high=close=232时无平仓；high=close=400时，`exact_stop_execution=true`产生追踪退出232。前日已生效止损并未穿透开盘，后续高点却反向决定了开盘卖出。所有价格在OHLC内也不能消除此时钟问题。用当天收盘激活利润锁定、当日ATR用于日内触发等路径一并列入补验收，需声明生效时点与路径假设。

**原通过项的范围**：拒绝全现金空壳、前收预算、入场日硬止损、零费持有、费用递增恶化、BNB分类、缺bar不崩溃、受阻SELL留存与两A股终值在既有场景通过，保留此进展。`all_fills_inside_bar`只遍历已平仓的exit_price，不能认证全部入场、未平仓或时钟路径；费用恶化测试也不替代全部现金／保证金／费用守恒场景。

### 8.2 S2：原数字可复现，真实ETF与每日闭环未成立

**D1｜P0：513100漏记公司行动**。官方确认2013-05-15上市，也确认2022-01-13按1:5拆分，见[国泰2023年中期报告第22页6.4.1](https://st.gtfund.com/report_root/2023/08/纳斯达克100交易型开放式指数证券投资基金2023年中期报告.pdf)。本地清洗数据从2022-01-12 close=5.192跳到01-14 close=1.015，原价收益−80.4507%；考虑份额变为5倍，仅这一段经济价格变化约−2.2535%。固定份额账本和未调整信号价格因此同时失真。纳指买持85.50%与MA200 81.69%回撤、相关收益以及“反弹踏空造成回撤”的解释暂停使用；此局部算术不是修正后的完整收益。需同时处理份额、信号尺度、停牌与分红，不能仅乘终值或删异常日。

**D2｜P1：真实输入与指标口径**。当前输入有000300而没有510300，三个独立资产对照并非1–3只真实ETF的账户组合。沪深3005.56%／4.04%为价格指数代理的252折年输出；MA200相同终值按日历约5.3461%。原0.9498x使用卖出额／平均NAV／252折年，同分母买入加卖出为1.8632x，24笔交易不等于低于1x双边换手。37.45%仍是较大历史回撤，不能称保本或已经达到个人承受门。佣金6bps＋滑点5bps每边计入，平价往返约21.98bps；真实账户最低费、整手、现金实际收益未知。现金按252日复利而摘要写单利，Calmar=99与现金胜率100应标不适用；年费元数据没有证明已核适用费率，也不能另扣一次ETF内含费用。

**D3｜P0：每日与回测规则不同**。回测用MA120／MA200、1.5%带、2日确认；每日默认MA120，无确认计数或上一状态接口。130日平价数据位于缓冲带，每日输出0.5，文字却称维持原决策，回测只允许0／1。最后一天首次突破时，每日立刻建议1.0，而同一历史的回测目标仍为0、确认计数1、成交0。需共用状态机并区分已执行持仓与下一时点目标，不能以当前市场值恰好落同侧证明闭环。

**D4｜P1：输入门与证据不足**。上市过滤不认证输入；重复日期在本次反例中被接受，乱序、非有限OHLC、零成交／缺日、公司行动和完整收盘／陈旧数据仍缺明确规则。运行器只手动读取固定本地JSON，不拉新行情，也无新鲜度或完整交易日门；固定输出目录用write模式覆盖summary。原包无代码／输入／参数hash、净值／成交／费用流水及持久状态，只有metrics与最新状态；不能称不可变交付或已部署每日服务。需唯一run目录、拒绝覆盖和最小manifest，本轮新证据保存了旧12条基线的复放NAV及沪深300MA200成交流水。

**D5｜P1：回归覆盖声明未复现**。常用根目录 `unittest discover -s tests -p 'test*.py'`本次实际3,440项（34跳过），不是3,445项；成员清单中没有本轮4个research专项模块，`tests/research/`缺 `__init__.py`，Python3.12 discovery不递归发现该目录。显式运行4模块共22项（个人助手5、不变性8、币安5、A股Master4）全部通过；这不能替代有效性反例，也不能混称全仓覆盖。[成员证据](../state/research_runs/research_delivery_recheck_20261012/test-discovery.json)、[全仓日志](../state/research_runs/research_delivery_recheck_20261012/full-tests.log)、[聚焦日志](../state/research_runs/research_delivery_recheck_20261012/focused-tests.log)。

### 8.3 修订后的执行与复跑

顺序改为 **S1止损时钟／测试发现 → 动态收据／现金费用 → S2真实输入与公司行动 → 共用每日状态机 → 同口径结果包 → S3整理**。每项验收与停止条件见[修订计划第4节](research-repair-and-consolidation-plan-2026-10.md#4-执行顺序与阶段交付)。没有补齐某资产来源或结算路径时交付未知并停止该资产认证，不以参数搜索救援。S1/S2暂不登记完成，麒麟／币安封存与其余线原裁决保持。

本轮原12项重跑证据在[core目录](../state/research_runs/research_delivery_recheck_20261012/core/core-evidence.json)。扩展脚本只写新空目录，第二步要求同一父目录下已有第一步的core结果：

```bash
PYTHONPATH=src ./.venv/bin/python \
  state/research_runs/s1_independent_verification_20261012T045426Z/verify_core.py \
  "$PWD" /tmp/qount-delivery-new-review/core
PYTHONPATH=src ./.venv/bin/python \
  state/research_runs/research_delivery_recheck_20261012/verify_delivery.py \
  "$PWD" /tmp/qount-delivery-new-review/delivery
```

原12项核验和扩展脚本退出0均只表示诊断完成，不表示整体验收通过。源码／输入／原工件检查前后hash一致；修订前5份文档已另存快照及manifest。本轮无订单、凭据访问、训练、远端采集／巡检或服务／调度变更，research_only=true / orders_authorized=false / promotion_evidence=false。



## 9. S3规划时的交付核对（2026-10-12 UTC）

按owner“梳理计划下一步方案”轻量核对新交付，不重新启动研究。专项4模块28项通过，默认discover发现3,493项（包含助手9项、不变性10项），本轮未重跑全仓；新调和包输入／核心代码／运行器／输出hash与原S2摘要hash全部匹配，12条调和指标精确复现。拆分、二值确认状态机与测试发现的工程进展保留。

有三项具体交付缺口，不支持直接沿用“全部验收完成”的声明：

- 当前A股收据两条终值null、FAILED_INPUT_PARSE；原verify_core.py执行至终值比较报TypeError、退出1，保留partial目录，无本轮core-evidence最终验收。坏输入防护虽有改进，临时根两个不可解析的PAXG／XLK缓存且没有币安月包仍可获得AUDITED_VERIFIED_PRIMARY；存在性不能认证完整输入。
- 止损时钟修改后保存的当前NAV／成交重新计算为CAGR20.7269%、MaxDD22.6232%、终值281,515.47USDT、172笔，收据仍硬编码3.47%／41.75%／120,589.07。原05:26以及前轮复查是旧源码结果，不能绑定新hash；旧Top5、Bootstrap与p=0.2695不代表新交易。此处收益只是实现诊断，封存／未晋级裁决保持。
- 原目录保护与现有hash一致已确认，但新结果目录仍能覆写：在临时私有目录放入已有summary后运行入口，文件被覆盖。原包未改。真实ETF分红／付款、510300、个人成本、完整收盘／新鲜度／缺日门仍未认证；现金复利文字与买持首次成交换手等也需收口。28.57%为当前模型回撤，不等于真实账户资格。

[检查摘要](../state/research_runs/s3_planning_20261012T071011Z/planning-checks.json)、[专项日志](../state/research_runs/s3_planning_20261012T071011Z/focused-tests.log)、[探针](../state/research_runs/s3_planning_20261012T071011Z/planning_probe.py)、[完整探针结果](../state/research_runs/s3_planning_20261012T071011Z/planning-probe.json)绑定当前结果包hash与原文件未变检查。临时反例未写真实交付目录；修订前4份文档保留快照。

下一步在[计划第7节](research-repair-and-consolidation-plan-2026-10.md#7-下一步执行方案s3交付收口保留对照与个人工具2026-10-12-utc)细化为S3-A两批收口→S3-B对照索引→S3-C确定性日报→S3-D连续5个交易日本地工程记录。索引可独立开展，数据或会计未知时有效信号先停止。该方案尚未实施，5日工程验证不证明盈利；本轮无策略／测试修补、原行情／结果改写、新参数搜索、训练、远端巡检／服务／调度或真实投递，research_only=true/orders_authorized=false/promotion_evidence=false。
