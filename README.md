# qount

`qount` 是按当前真实机器拓扑设计的 `AI 决策系统 + 风控执行器 + Binance 执行` 骨架。

系统工程主设计见 [docs/system-architecture-design.md](docs/system-architecture-design.md)：它定义统一合同、
策略到订单的追踪链、账本与对账、故障恢复、通知/日报、Dashboard read model、LLM边界和渐进迁移顺序。
当前生产事实仍以 [docs/current.md](docs/current.md) 为准。

当前源码候选为 `0.2.13`（增加最近已完成日线硬门、修复LLM flat仓位计数和中文越权扫描，并补Funding Veto beta残差报告）；VPS生产版本仍为
`0.2.12`（修复live oneshot自检循环并完成生产验收）；
`qount-mini-trend-live.timer` 已恢复 `enabled/active`。唯一获得真钱权限的连续策略是
`MiniTrend-UM-Base-v0.2`，固定 `100 USDT`、Binance USD-M TOP3、long/cash、one-way、isolated 1x、
effective gross `<=1`；RiskTier和FundingVeto只做shadow。旧forward timer、X4/C×D/line A交易入口和production cron保持关闭。
`0.2.12` provenance、通知库迁移、无订单周期、readiness 五轴、账本和对账均已验收。最新live cycle因冻结信号为全现金而完成
`duplicate_decision_noop`，0 market/0 stop、无交易所变更；这不是未启动，也不得强制制造首单。

## 主机职责

当前权威分工如下，详细路径、ExFAT边界和迁移门见
[docs/storage-topology.md](docs/storage-topology.md)：

| 节点 | 当前职责 |
| --- | --- |
| Mac | 研究设计、代码主仓、git、文档、轻量验证和任务编排；不长期保存全量数据 |
| Windows外置盘 `E:\qount_data` | 数据集、最终artifact、环境锁和备份的存储真相 |
| WSL `home:/home/alyaloale/Code/qount` | 7945HX/RTX 4060 CPU/GPU计算节点；本地只保留可清理scratch |
| VPS `/root/qount` | live/paper/dashboard运行和最小runtime state |

WSL不是Mac的持续镜像，也不是实盘真相。Mac只在计算接口变化时更新WSL代码；大数据直接在Windows/WSL侧
进入外置盘，训练完成后发布artifact和manifest，不经Mac中转。

- `Mac`
  - 研究设计、git、文档、只读看日志和手动运维入口
  - 只保留代码、轻量fixture和必要摘要，不长期保留`state/`大数据
  - 不跑实盘执行器
- `VPS`
  - 唯一实盘 / 模拟盘生产节点：`qount-vps:/root/qount`（SSH别名或仓库外`QOUNT_VPS_HOST`）
  - 跑唯一的MiniTrend Base 100 USDT minimal-live周期、order-free refresh和dashboard发布；旧X4/C×D已停
  - Alpha S3 当前走 Mac 历史公开数据研究；冻结 trade-flow v1 的 ETH anchor 过 Q1/4 月历史 OOS，但
    BTC/BNB/SOL 复制全败，后续预注册的 flow/price absorption 与 premium dislocation 三币 discovery
    也均为 0/3 通过；固定的 depth + premium + price Logistic residual-trend 模型 March OOS 为 0/3，
    绑定原模型哈希、不重训的 2025Q1 时间复验再次 0/3，mean residual `-32.400521%`，A10 sequence
    仍关闭。G4/G5/G6 scorecard 继续 block，失败的 VPS collector 证据保留在 `/root/qount-alpha`，服务已停
  - 2026-07-16 owner 将研究优先级转回加密：A股 ETF 20 日线冻结保留；加密只从新的结构性信息源和
    ex-ante 预注册协议 research-only 重启，既有失败合同不重调，paper/live 与生产 crontab 均不恢复
  - 2026-07-17 新源矩阵选择 Deribit BTC/ETH DVOL 后，冻结的 `ETH DVOL - BTC DVOL` 三币 discovery
    为 0/3 通过；ETH/BNB 净 residual 为负，SOL 虽为正但 rank IC 仅 `0.004773`。2025 replication 与
    forward OOS 均未消费，options-DVOL 路线停止，不恢复 A10/paper/live
  - 后续 historical option-surface 与外部 liquidation/L2 容量审计也均在 G0 阻断：Deribit 公共历史
    无法枚举完整过期链或直接恢复 IV surface；Tardis 样本语义可校验，但匿名历史只返回 1 分钟，BTC raw
    L2 估算约 `256.90 GB/90d`，超过 32 GiB 本地预算。未生成新预注册
  - 2026-07-17 owner 选择不用高频、回到已有低频趋势资产。冻结 MiniTrend TOP3
    `BTC/ETH/BNB + spot long/cash + 1d`，先走 60 根完成日线/10 根 active 的 Mac forward；7 月 1-16 日
    首段 16/16 完整但总闸关闭、0 单、全现金，`collect_forward`，不进入 paper/live
  - 同日旧 X4 高收益归因发现日线 funding 只计到每日 3 次结算中的 00:00 一次；完整结算后 S3/S4
    从 `+115.18%/+98.39%` 更正为 `+84.93%/+70.77%`。收益主因是日线、取消空头、SMA200 熊市走现金，
    不是 2x 杠杆。后续 UM no-carry 候选固定为 TOP3 日线 long/cash、effective gross<=1，不恢复 short
  - UM base forward 在消费任何结果前升为 v0.2，显式绑定实际执行的 `3xATR` 日线吊灯；最新共同缓存日
    仍为 `2026-06-18`，`2026-07-17` 后 0 根，`await_forward_data`，不进入 paper/live
  - 单变量 UM 收益档把 `vol_target 1.5%→2.0%` 后，全窗收益 `+66.51%→+103.29%`，但 2025-2026
    恶化为 `-5.31%/13.78% maxDD`，击穿预登记弱市门，verdict `reject_historical_risk_tier`。不做中间值
    救援，最终策略仍选 1.5% base v0.2
  - 三阶段 UM overlay 只在“BTC>SMA200 + BTC SMA20>SMA60 + TOP3 breadth>=2/3”的 strong-bull 状态复用
    2.0% 风险档，transition/range 保持 1.5%、bear 走现金。全窗收益升到 `+85.94%`，但 Sharpe 略降且
    2025-2026 变成 `-5.13%/12.45% maxDD`，击穿预登记弱段门，仍拒绝；不调状态阈值救援
  - 无新阈值的 strong-bull stop latch 在既有 3xATR 止损后只撤销 2.0% 增益、退回 base 1.5%，把全窗
    收益/Sharpe 改善到 `+88.41%/0.945`，2025-2026 改善到 `-1.83%`；但全窗 maxDD `18.70%` 相对 base
    恶化 `1.418pp`，超过预登记 `1pp`，仍严格拒绝。它是当前最强历史机制证据，不是可上线策略
  - Owner 提供的优化建议经证据分流后，只立即实践了已有缓存可因果验证的 funding 成本过滤：未锁定
    strong-bull 若上一完整日 TOP3 funding 中位数简单年化 >50%，本 bar 2.0% boost 退回1.5%。17根 veto
    后全窗 `+88.95%/Sharpe 0.965/maxDD 18.11%`，全部历史门通过，verdict
    `retain_historical_funding_veto_candidate`；但事件仅覆盖2021/2023-24，仍非OOS/paper/live资格
  - 2026-07-18 对固定 Funding Veto 与 Stop-Latch 的1776日净收益做预登记配对20日循环区块Bootstrap
    （5000条路径、固定seed）：候选终值收益/Sharpe/更低maxDD胜率为 `58.90%/86.82%/75.72%`，三项增量
    中位数 `+0.463pp/+0.0191/-0.226pp`，通过冻结稳健门。收益胜率只属边际，仍仅保留历史候选，不晋级
  - 同日六组精确Shapley归因显示，相对Stop-Latch的 `+0.536pp` 中 funding节省贡献 `+0.443pp`、价格暴露
    `+0.097pp`、交易成本 `-0.004pp`；但事件日 `+1.842pp` 被后续路径 `-1.306pp` 抵消，17次veto传播为
    696个下游差异日。成本过滤机制成立，但路径依赖很强，仍须完整forward状态验证
  - 状态衰减审计进一步确认696个状态差异日全部来自目标权重，首次同步中位46日、最长56日；18个状态spell
    最长100日，只有最后事件在324日后达到窗口内稳定同步。吊灯、冷却、latch状态未分叉，但权益与deadband会
    让已同步权重再次发散，未来必须做双状态shadow forward，不能只记事件或当前仓位
  - 双状态shadow-forward v0.2已在任何新结果前冻结：`2026-07-19`起，200根历史仅作信号warmup，两路径均从
    400 USDT全现金启动，逐日保存双权益/收益组件/执行状态与链式哈希；只评估价格连续且决策日/持有日TOP3
    funding各至少3次结算的完整前缀，缺失结算不得按0成本计收益。修复后WSL已把外置盘公开日线补到
    `2026-07-21`，但当月funding公开REST仍`0/3`完整；最新冻结回放为0根evaluation、无journal和
    `await_complete_shadow_inputs`。未填0、未使用苏菲家宽代理，也未借用VPS数据冒充research canonical
  - 同一冻结历史报告在WSL精确复跑且新增BTC/TOP3 beta residual：Funding Veto为
    `+88.95%/Sharpe 0.965/maxDD 18.11%`，对TOP3等权1x的beta `0.1470`、复合残差`+55.41%`；旧字段规范化
    hash完全一致。5000路径20日块Bootstrap也逐字段重现，但收益胜率仅`58.90%`、增量中位数`+0.463pp`。
    这仍是已消费历史discovery，不增加trial，不改变Base真钱控制或Funding Veto shadow-only身份
  - 个人`research_sandbox`已用已有TOP3日线完成1765行因果ML数据集和2023-2026年度扩展Walk-Forward。
    Logistic/HGB/LightGBM/XGBoost概率均输常数先验；因果前向HMM仅有弱校准优势，平均Brier uplift
    `+0.013493`、3/4折为正，但硬分类严重偏向range/bull。固定的先验收缩、HMM状态增广和50/50融合均未
    超过原HMM，不能接仓位
  - 独立A10研究节点上的60日小型GRU可确定性复现，逐折model-state hash完全一致，但平均Brier uplift
    `-0.029635`、仅2/4折为正，且2023显著失败；当前不继续扫神经网络结构。数据、代码、CUDA和依赖已由
    环境manifest绑定；全部仍是`consumed_historical_discovery_pool`，不恢复paper/live
  - 后续经济目标审计排除了30日HMM风险分数、12个HMM目标、40个直接经济回归和40个DVOL增强回归。
    24格滚动窗只留下60日/365日RF排序信号，但固定3档只降风险消融全部失败；最佳仅改善`0.88pp` maxDD，
    却少赚`12.22pp`，说明预测排序不能直接逐日控制仓位
  - WSL直连Coin Metrics并将2020-2026共2373个BTC日频latest-vintage链上行直接写外置盘；7个固定方向因子
    只有滞后1日`hashrate_z90`通过，加入原滚动RF后rank IC升到`0.179447`。但同一冻结风险消融仍`0/3`，
    最佳Sharpe提高、maxDD改善`0.86pp`的代价是少赚`4.80pp`，击穿3pp门。算力模型只留研究，不接forward/
    paper/live；当时累计相关trial `131`
  - Federal Reserve H.4.1官方历史release已在WSL完成`289/289` point-in-time周频重建，稳定data hash
    `8af65a47...cb02`。固定4周资产变化把滚动RF rank IC提升到`0.202639`、高低组差`12.899pp`、bootstrap
    `95.17%`；4周加速度也保留，13周变化和宏观+算力融合拒绝。相同三档风险消融仍`0/3`，最佳以少赚
    `3.323pp`换`0.863pp`回撤改善，击穿冻结3pp门。累计trial `138`，正式策略仍是1.5% Base v0.2
  - 预登记的H.4.1低换手事件闸门也已完成3个trial：收缩期只阻止新开仓、扩张期只延迟SMA200总闸退出、
    二者合并。收缩状态在633根日线上介入并阻止1,358个symbol entry，收益从`+66.51%`降到`+1.72%`；
    扩张退出确认只介入2根日线/4个symbol exit，收益`+64.09%`、Sharpe `0.864`，也未改善风险收益。
    `0/3`保留、累计trial `141`；事件驱动本身不能修复错误的二元状态，不再扫分位/窗口/冷却期救援
  - 随后只对strong-bull额外0.5%风险做一次宏观否决，不碰Base 1.5%：固定使用已有60日RF的年度fold OOS
    标准分数`<=0`，并叠加在Funding Veto之后。2023-2026覆盖期内449个可boost日被否决303个，参考
    Funding Veto为`+90.36%/Sharpe 1.260/maxDD 18.10%`，候选反降至
    `+65.07%/1.095/19.26%`，甚至跑输Base `3.20pp`；`8/14`门通过、累计trial `142`，严格拒绝且不调阈值
  - Base v0.2逐币episode精确归因完成并与`266.0216 USDT`净利润对到`0.00000002 USDT`：77段持仓中，
    31个吊灯退出贡献`+403.61 USDT`，是利润来源；38个单币趋势/配置退出贡献`-56.61 USDT`，8个SMA200
    总闸退出贡献`-80.98 USDT`。1-7日和8-30日持仓合计亏`-179.66 USDT`，31日以上合计赚
    `+445.68 USDT`，说明策略靠少数长趋势而非高胜率
  - 归因后唯一预登记trial复用已有3日止损冷却来阻止单币趋势退出后的快速重入。收益
    `+66.505%→+66.805%`、Sharpe `0.9028→0.9079`、订单`261→252`，但Bootstrap收益/Sharpe/更低回撤
    胜率仅`58.96%/64.42%/55.88%`，`13/16`门通过、累计trial `143`，严格拒绝且不扫冷却天数
  - Coin Metrics append-only future vintage链已开始，首个快照绑定`2026-07-17`源日与UTC检索时间；
    H.4.1/Coin Metrics原始数据、artifact、manifest只在外置盘，Mac/VPS不保留副本
  - UM shadow输入刷新层已落地：研究canonical仍由WSL直写外置盘`datasets/binance_um_shadow/v1`；VPS另只保留
    TOP3 production-minimum cache，每日直连刷新公开rules/bar/funding并离线回放，不作为批量研究中转。
    策略trial累计仍为143
  - 一个月小资金实盘已由owner改为严格固定`100 USDT` canary；manual arm前只验证已审计USD-M可用余额不少于100，
    manual arm后冻结该次本金。无账户单日止损，权益峰值回撤10%时
    flatten+halt。Base v0.2仍是真钱控制；历史收益leader全局2.0%风险档弱市为负且59个独立30天窗有1次触发
    10%线，只做首选shadow，Funding Veto为次级shadow
  - paper runtime v0.3已把全局2.0%风险档和Funding Veto完整状态并入Base的append-only shadow日志；两者
    都显式不控制订单。VPS当前因冻结起点尚无完成bar而0 pair/0 day/0 journal，`await_paper_inputs`不是0收益结论
  - VPS绕开全部环境代理后的生产出口（具体IP仅存仓库外inventory）可访问Binance UM；owner接受当前credential
    继续作为生产key。它只存VPS且Reading/Futures/IP限制开启、Withdrawals关闭；Spot/Margin开启按owner指令允许，
    不再作为preflight/readiness blocker。TOP3现已全部为isolated 1x，账户全平且0挂单
  - VPS曾启用`qount-mini-trend-forward.timer`运行公开输入刷新、只读preflight、order-free paper、latest
    projection、当前账户/普通单/条件单对账、dry dispatcher和artifact-bound readiness；2026-07-20按安全要求已执行
    `systemctl disable --now`，当前为`disabled/inactive`。MiniTrend专用dispatcher已实现
    决策ID幂等、client order ID、append-only row/chain hash、`STOP_MARKET closePosition`、成交后仓位/保护单回读、
    当时的10%回撤flatten+halt和独立manual arm。最新run
    `/root/qount/state/mini_trend/forward/runs/20260719T091232Z`通过独立systemd runtime证明；dispatcher因尚无首个完成bar
    返回`await_dispatch_decision`，0单、0 dry day、`exchange_mutation_attempted=false`。当时readiness显示5个新数据累积缺口，
    `live_orders_allowed=false`
  - 历史阶段（2026-07-21）：owner要求直接推进Phase B/C/D，60 forward pairs、10 active bars、30 paper days、7 dry days均降为
    非阻断观察指标。标准batch/RuntimeLedger/三方对账已接入dispatcher；market fill必须有exchange order和逐笔trade/fee证据，
    超时进入UNKNOWN+HALT且不重发。观察项也纳入readiness hash防篡改，但不进入blocker。Binance短窗口cash ledger
    只接受原始有符号`income`和明确的funding/commission/transfer白名单，未知账变直接HALT。该阶段arm/timer/live switch仍关闭，0真实订单
  - 同日B/C/D已同步VPS并完成一次systemd order-free闭环：run `20260721T063854Z`最终readiness为
    `ready_for_manual_final_arm`、blocker 0，但`live_orders_allowed=false`；账户全平、普通/条件挂单0、dispatcher 0 market/stop intent且
    `exchange_mutation_attempted=false`。forward/active/paper/dry观察为`0/0/0/1`，funding完整；registry仍为`research`，manual arm为0，
    timer继续`disabled/inactive`。首单前仍须owner确认最终readiness、authority、RuntimeLedger和reconciliation四类hash
  - 多策略组合层已新增标准`StrategyIntent`、Base projection adapter和fail-closed allocator；最小名义按独立sleeve
    先于组合净额检查，避免Base掩盖不可成交alpha。第144个正式trial测试Base关闭时的TOP3极端下跌反弹，18个
    独立episode的中位净收益`-1.87%`、复合price+cost`-36.50%`、maxDD`39.52%`，已严格拒绝且不接shadow/live
  - 新低频方向已扩展到美股映射加密资产：Binance当前有11个`TRADIFI_PERPETUAL`，另有`*B`映射现货；
    Bybit有xStocks现货和对应linear合约。首个周末/非美股时段偏离研究仅18个独立现金交易日，日期聚类组合
    扣24bps往返成本与funding后为`+3.75%`、maxDD `4.00%`、Bootstrap正收益概率`71.16%`，只属早期发现
  - 固定300 USDT、无外部注资的周频定投/定减实验显示，均线DCA/DCR在BTC/TOP3/SPY都未超过buy-and-hold；
    buy/hold/sell因果标签的Logistic/HGB六个模型全部输常数先验。模型不会接入Base或实盘
  - 2026-07-19 owner计划最终扩到1000 USDT并采用多策略虚拟sleeve架构；统一合同见
    `docs/crypto-portfolio-system-plan.md`。`1000 USDT`只保留为历史/order-free研究兼容上界；本次真钱canary在readiness、arm、
    live dispatcher和live journal四层都强制精确`100 USDT`。除Base外的sleeve仍是research/shadow，不获得真钱订单权
  - LiquidTrend10首个G0容量审计已完成：10币共同日线覆盖`99.72%`、Funding和流动性通过，但平均绝对相关
    `0.6616`、有效广度仅`1.438`，且现有UM runtime规则只覆盖4/10。原始十币score trial被阻断，不回测收益
  - LLM非K线信息层已落地第一道确定性边界：官方来源、published/available/observed时点、实体、数值、原文hash、
    重复和越权交易语言全部验证；LLM摘要不能直接成为数值特征或订单。研究客户端现通过relay-station接
    ChatGPT，默认`gpt-5.6-terra`、并发1、重试0、严格JSON且显式opt-in；`official_sources.py`负责无代理、
    allowlist、重定向复核、大小限制和原文hash，模型本身不替代确定性官方源抓取
  - 首次terra官方源审阅只读Binance Public Data README，识别出`.CHECKSUM`与远端修订语义；数据层已新增
    `verified_archive_fetch`供新严格摄取使用，既有缓存不被自动声称为官方checksum已验证
  - Equity Mapping G0 v0.3已落成离线point-in-time合同：三腿决策前同步报价、bid/ask gap边界、公司行动
    归一化、压力场景血缘、经济事件/证据修订双hash和独立日期计数。当前仅2行合成fixture/1个独立日期，严格
    `collect`，不计算PnL，也没有shadow/paper/live/order资格
  - 站点：`https://qount.alyaloale.com/#/live`，Dashboard v1静态前端已接入真实order-free authority read model；
    publisher每两分钟只读刷新系统健康、原子release和已验证备份。最后一次授权账户观测为TOP3全平、0挂单，但authority已按
    15分钟规则标记stale；publisher不查询账户或交易所，也不赋予订单权限
- `Windows / WSL`
  - 正式CPU/GPU计算环境，代码路径`/home/alyaloale/Code/qount`
  - 大数据与最终artifact写外置盘`/mnt/e/qount_data/qount`；WSL ext4只作临时scratch
  - 不作为 live / paper / dashboard 生产真相

## 当前工程范围

这版已经落下来了：

- 配置加载
- 市场快照构建
- AI JSON 决策请求
- AI 前轻量 candidate filter
- 决策校验
- 成本感知风控裁决
- `paper` 执行器
- `live` 现货 / USDT 合约执行骨架
- SQLite 审计链
- 成本感知 `signal-review`
- A股 ETF 20 日 research-only 状态判别、Tushare/公开复权数据和固定组合证据门（当前冻结保留）
- VPS 运行脚本、同步脚本、Dashboard v1原子发布合同和order-free authority writer；publisher timer为`enabled/active`，
  每轮验证authority、健康、恢复演练，并保留当前+4个release及latest+60个备份。authority oneshot保持`static/inactive`，
  MiniTrend live timer为`enabled/active`，forward timer和production cron保持关闭；订单权限只存在于独立0600 arm/env与
  `minimal_live` registry同时有效的MiniTrend service内

## 初始化

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

首版建议先跑：

```bash
. .venv/bin/activate
export $(grep -v '^#' .env | xargs)
python -m qount.main healthcheck
python -m qount.main preflight-live
python -m qount.main run-once
python -m qount.main runtime-status
python -m qount.main clear-halt
python -m qount.main paper-status
python -m qount.main signal-review --limit 20 --horizon-bars 3
python -m qount.main paper-replay
python -m qount.main backtest --start 2026-05-14T22:00:00+08:00 --end 2026-05-14T23:30:00+08:00 --max-bars 8 --review-horizon-bars 3 --review-threshold-pct 0.003
python -m qount.main backtest --research-profile eth-only --start 2026-05-14T22:00:00+08:00 --end 2026-05-14T23:30:00+08:00 --max-bars 8 --review-horizon-bars 3 --review-threshold-pct 0.003
```

如果要验证训练窗口和验证窗口是否严格分离，再跑：

```bash
python -m qount.main train-setup-model --research-profile eth-only
python -m qount.main walk-forward --research-profile eth-only --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00 --setup-phases range_noise
python -m qount.main setup-edge-walk-forward --research-profile eth-only --holdout-role discovery --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00
python -m qount.main candidate-walk-forward --research-profile eth-only --holdout-role discovery --window demo=2026-05-23T00:00:00+00:00,2026-05-23T03:00:00+00:00 --max-bars-per-window 20
```

`--research-profile eth-only` 会把 setup-model 训练默认值对齐当前 phase6 口径：`horizon_bars=6`、`split_higher_phase=true`。显式传 `--horizon-bars` 或 `--split-higher-phase` 时，以命令行参数为准。
`backtest` / `walk-forward` 支持 `--holdout-role discovery|validation_v1|unknown` 和研究专用 `--ai-decision-cache`；live / run-once 不使用该缓存。

当前 MiniTrend 生产状态从 VPS 只读读取：

```bash
ssh qount-vps 'systemctl is-enabled qount-mini-trend-live.timer; systemctl is-active qount-mini-trend-live.timer'
ssh qount-vps 'systemctl is-enabled qount-mini-trend-forward.timer; systemctl is-active qount-mini-trend-forward.timer'
ssh qount-vps 'systemctl show qount-mini-trend-live.service -p Result -p ExecMainStatus -p ActiveState -p SubState'
ssh qount-vps 'crontab -l'
```

生产调度不是隐含基础设施。当前唯一交易timer是`qount-mini-trend-live.timer`；forward timer和root crontab
必须保持关闭，旧 X4/C×D cron 只能按历史证据读取，不能直接安装。live oneshot service 空闲时显示
`inactive/dead`是正常的，最近结果必须为`Result=success`。完整运维读法见
[docs/quick-handoff.md](docs/quick-handoff.md)，安全冻结的生产 crontab 模板见
[deploy/cron/qount-production.crontab](deploy/cron/qount-production.crontab)。

发布 / 验证入口：

```bash
./scripts/sync-to-vps.sh --install
./scripts/run-vps-tests.sh
```

旧 `scripts/mac-monitor.sh` 是 WSL + `qount.main` 时代的 line A 面板，默认已弃用；不要把它当
当前加密实盘状态入口。

## 运行模式

- `QOUNT_MODE=paper`
  - 不需要 Binance key
  - 用本地 paper portfolio 演进仓位
- `QOUNT_MODE=live`
  - 需要 Binance API key / secret
  - 执行真实下单

## 市场类型

- `QOUNT_MARKET_TYPE=spot`
  - 默认模式
  - `buy=开/加现货多头`
  - `close=平现货`
- `QOUNT_MARKET_TYPE=future`
  - Binance USDT 本位永续合约最小可用版
  - `buy=开/加多`
  - `sell=开/加空`
  - `close=平当前仓位`
  - 当前实现按 `one-way` 仓位模式设计，不支持对冲模式
  - `QOUNT_CONTRACT_LEVERAGE` 只控制杠杆，不改变 `size_pct` 作为“目标名义仓位占权益比例”的语义
  - `QOUNT_CONTRACT_MARGIN_MODE` 目前支持 `isolated` / `cross`

如果你把 `QOUNT_MARKET_TYPE` 切到 `future`，`QOUNT_SYMBOLS` 可以继续写成：

```bash
QOUNT_SYMBOLS=BTC/USDT,ETH/USDT
```

运行时会自动解析到 Binance 合约 canonical symbol，例如 `BTC/USDT:USDT`。

## 交易所选择

仓库示例配置默认仍然保留 `binance`。
如果你的运行环境对 `api.binance.com` 有区域限制，不要机械地直接切成 `binanceus`；先确认你实际使用的是哪类账户和 API。

当前 VPS 生产路径里，已经验证通过的路径是：

- `QOUNT_EXCHANGE_ID=binance`
- Binance futures 私有接口
- VPS 直连 Binance，不依赖 Windows/WSL 的 `7907` 代理出口

研究数据下载边界：批量公开数据只在Windows/WSL侧下载并直接写外置盘，不经Mac或VPS中转。直连和
owner-approved Liangxin Cloud proxy均可，代理凭据留在仓库外本地环境；永不使用苏菲家宽代理。明确标为
offline的实验在缓存缺失时仍须直接失败，不能静默切换成联网运行。

只有当你**确实**在 Binance US 账户 / API 上运行时，才把：

```bash
QOUNT_EXCHANGE_ID=binanceus
```

写进 `.env`。

如果你要跑合约 live，还要确保：

- Binance API key 已开通 futures/derivatives 权限
- 账户仓位模式是 `one-way`
- 账户可用保证金乘以 `QOUNT_CONTRACT_LEVERAGE` 后，能覆盖交易对最小名义价值

WSL 的 `HTTP_PROXY=http://192.168.128.1:7907` 等配置只属于历史研究 / 旧 line A 验证链路，
不能作为当前实盘连通性依据。

## Live 切换保护

`live` 模式不会因为你改了 `QOUNT_MODE=live` 就直接开单。

注意：本节是旧 `qount.main` line A 的通用保护，仅供历史代码测试。当前生产不通过
`QOUNT_LIVE_ENABLE`、`QOUNT_X4_LIVE_ENABLE`、`QOUNT_RV_LIVE_ENABLE`或`QOUNT_CXD_CARRY_ENABLE`开启；
唯一生产订单权限来自 MiniTrend 独立 `0600` arm/env、`minimal_live` registry、当前 readiness 和
`qount-mini-trend-live.timer` 的组合门。

还必须满足：

```bash
QOUNT_LIVE_ENABLE=true
QOUNT_LIVE_CONFIRMATION=I_UNDERSTAND_LIVE_TRADING
```

然后建议手动执行：

```bash
python -m qount.main preflight-live
python -m qount.main live-guard-status
```

旧 live guard 的“持续放行”语义不适用于当前 MiniTrend 生产。不要用 `qount.main run-once`、旧环境变量或
旧脚本获得订单权限；任何 release/config 变化都必须重新生成 order-free readiness 并轮换 arm。

对于 `future` 模式，guard 还会额外检查：

- futures 私有接口可访问
- 当前账户不是 hedged mode
- 可用保证金满足最小名义仓位要求

如果系统因为 AI 连续失败进入 `halted`，可以手动恢复：

```bash
python -m qount.main runtime-status
python -m qount.main clear-halt
```

日内亏损保护的基线现在按 `mode + exchange + quote currency + date` 隔离，不再把 `paper` 的日初权益和 `live` 账户混算。

## Review 工具

- `signal-review`
  - 批量回看已记录的最终风控动作
  - 输出 `gross_future_return_pct / estimated_cost_pct / net_edge_pct`
  - 输出 `by_symbol / by_action / by_confidence` 聚合
  - 输出 `by_context` 聚合，区分 `entry / management / idle`
  - 输出 `by_lifecycle / by_blocked_group` 聚合，区分 `fresh_entry / management_hold / blocked_entry / blocked_add / ...`
  - 输出 `by_candidate_reason` 聚合，直接看 `candidate_ok / position_management / ...` 这些候选原因在 review 里的表现
  - 输出 `blocked_sell` 聚合，专门看 `decision_action=sell` 但被 risk gate 压成 `hold` 的样本质量；它仍然有用，但只是 short 侧辅助切片
  - 输出 `flip_rate / same_symbol_reentry_rate`
- `paper-replay`
  - 根据已记录的 `paper` 订单历史重放组合现金和持仓变化
  - 输出当前 paper equity、已实现盈亏和时间线
- `backtest`
  - 基于历史 OHLCV 跑一套**隔离的 paper 回测**
  - 复用当前 `candidate -> AI -> validate -> risk -> execute` 链路
  - 输出独立 `db / summary.json / review.json`
  - 适合做“策略调完后，再跑同一时间窗验证效果”

注意：

- `signal-review` 是**历史真实决策复盘**
  - 依赖已记录的 `runs / snapshots / validated decisions / risk actions`
  - 再对照后续 OHLCV 计算 `net_edge_pct / missed_move / good_hold`
  - 适合判断“最近这套 live/paper 决策质量有没有改善”
- `paper-replay` 是**历史 paper 订单权益回放**
  - 依赖已存在的 `paper` 订单历史
  - 不会重新生成历史信号
- `backtest` 是**真正的历史 paper 回测命令**
  - 给定一段历史 OHLCV
  - 从头重跑 `candidate -> AI -> risk -> execute`
  - 输出 final equity、drawdown、order stats、review 聚合
  - 默认写到 `state/backtests/<timestamp>-<window>/`

如果你要问“历史数据回测是否盈利”，先明确是在问：

- 决策复盘口径：用 `signal-review`
- 已执行 paper 订单口径：用 `paper-replay`
- 纯历史 full backtest：用 `backtest`

当前 VPS MiniTrend 只读 smoke-check 示例：

```bash
ssh qount-vps 'systemctl is-enabled qount-mini-trend-live.timer && systemctl is-active qount-mini-trend-live.timer'
ssh qount-vps 'systemctl is-enabled qount-mini-trend-forward.timer; systemctl is-active qount-mini-trend-forward.timer'
ssh qount-vps 'systemctl show qount-mini-trend-live.service -p Result -p ExecMainStatus -p ActiveState -p SubState'
ssh qount-vps 'cd /root/qount && find state/mini_trend/forward/runs -mindepth 1 -maxdepth 1 -type d | sort | tail -1'
```

读法：live timer 的 oneshot service 空闲时显示 `inactive/dead` 是正常的，最近一次结果需为
`Result=success`；forward timer 和 legacy cron 必须保持关闭。不要恢复 X4/C×D 或用旧 dry 入口刷新生产状态。

## 当前文档入口

- 当前事实：[docs/current.md](docs/current.md)。
- 项目规则、文档分类、研究线隔离和代码清理纪律：
  [docs/project-rules.md](docs/project-rules.md)。
- 接手命令、VPS 运维入口、sync/test 脚本和 artifact 规则：
  [docs/quick-handoff.md](docs/quick-handoff.md)。
- 验证边界：[docs/holdout.md](docs/holdout.md)，定义
  `discovery_pool` / `validation_pool_v1` 与 `G_paper` / `G_live`。
- 执行记录：[docs/update-log.md](docs/update-log.md)，记录近期 artifact、验证结果和读法。
- 多智能体研究层：[docs/alpha-agent-plan.md](docs/alpha-agent-plan.md)，定义 Alpha Agents
  research-only 角色、任务、source book、relay-station ChatGPT接入和后续量化接入边界。
- 旧研究线与历史文档索引：[docs/archive/README.md](docs/archive/README.md)。

当前基线：旧 line A `qount.main`、X4和C×D仍关闭；唯一可运行的真钱链为VPS `/root/qount` 上固定100 USDT的
MiniTrend Base minimal-live。Dashboard静态前端已部署，
served root的`data/v1`已由真实order-free authority生成；authority/backup/web data目录按`0700/0700/0755`运行。
publisher timer为`enabled/active`；它只读完整batch/registry/ledger/notification/health/brief，并每两分钟刷新系统健康、release、
备份和恢复演练；release保留当前+4个，备份保留latest+60个。最后一次授权账户观测为`486.15970914 USDT`、TOP3全平、0挂单；
recurring readiness已通过且registry为`minimal_live`。NotificationStore已接腾讯官方个人微信iLink provider，一条中文接入通知
在VPS真实投递为`DELIVERED/SUCCEEDED`并通过audit-chain重放；WeCom只保留为未启用兼容adapter。authority writer保持
`static/inactive`，MiniTrend forward timer和production cron保持关闭；live timer为`enabled/active`，publisher不查询交易所，也不授予订单权。
只读日报生产默认使用Binance公告API、Federal Reserve RSS和SEC RSS，不需要Brave；六角色中文Responses经
内网normalizer完成真实E2E并保存3份feed、8份详情和2份行情，个人微信投递为`DELIVERED/SUCCEEDED`。Dashboard
`intelligence`现发布真实报告且source hash为`f4d90e84...63a94`；日报timer为`enabled/active`，每日`04:30 UTC`运行。报告外层
`incomplete`来自证据不足的`needs_research`，不是基础设施失败。当前仅允许MiniTrend Base live timer运行，其它交易timer和production cron继续关闭。
Mac
`/Users/alyaloale/Code/qount` 是编辑和 git 工作区。研究命令必须显式使用
`--research-profile eth-only` 或 `--research-profile multi-symbol`；不要直接继承 WSL
`.env` 的旧 4-symbol live 形状。

每批有意义的代码、运行或规则更改完成后，必须按
[docs/project-rules.md](docs/project-rules.md) 更新对应记录文档：本线 changelog、
[docs/update-log.md](docs/update-log.md)，以及必要时的 [docs/current.md](docs/current.md)。

## 当前流程

```text
closed 5m bar -> snapshot -> candidate_filter -> AI -> validate -> risk -> executor -> journal -> review
```

`risk_engine` 在 `bottom_line` 下只保留底线约束：日亏损停机、系统 halt、仓位上限、
交易所最小名义、最大持仓数、方向暴露和基本止损合法性。

## 目录

```text
app logic: src/qount/
docs: docs/
prompts: prompts/
runtime state: state/ (VPS production runtime state)
research artifacts: state/research_runs/
run scripts: scripts/
vps scripts: scripts/desktop/*_cron.sh, scripts/sync-to-vps.sh
```

## 当前判断

有历史盈利样本，但没有稳定盈利或上线能力证明。已看过窗口只算 discovery，promotion
必须从 `validation_pool_v1` 重新 once-only 验证。继续研究默认先读
[docs/current.md](docs/current.md) 和 [docs/quick-handoff.md](docs/quick-handoff.md)。
