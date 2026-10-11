# 跨研究线修复：P1 数据与现金会计、P2 梯度闸门

> **状态**：active research / 工程与数据资格审计｜**权威**：本轮协议与交付记录，当前事实只看 [current.md](current.md)｜**最后更新**：2026-10-11
> **TL;DR**：主攻 Q-DIV 历史版本与原价现金会计；C60 单独冻结梯度试验，资格不足不伪造历史回测。
> **边界**：research_only=true / orders_authorized=false / promotion_evidence=false；不影响账户、既有 paper、VPS、服务或调度。

## 问题、停止条件与范围

本轮回答：现有财报是否足够构建历史滚动截面，原价分红会计能否独立通过场景验证，以及固定 BTC 梯度和不交易带能否降低 C60 历史成本而不损伤收益/回撤。数据资格不足则停止正式收益评价；C60 任一冻结门失败则保留失败，不改变阈值或选择诊断赢家。

owner 指定的外部计划已读取，路径与原文 SHA256 记录在 [来源回执](../state/research_runs/research_remediation_20261011/proposal-source.json)。本文是该计划在仓库内的执行与修正记录，原文保持。冲突按 current → project-rules → reference → proposal 处理。

| 位序 | 本轮处理 | 边界 |
| --- | --- | --- |
| P1 Q-DIV | 历史版本索引、季度截面审计、原价现金账本内核 | 先补历史证券池/版本/公司行动/一级行业/税费/基准，再运行正式收益 |
| P2 C60 | 固定 0/35/70/100% 梯度及 15% 不交易带的配对对比 | 独立 discovery 合同，不替换既有 paper 或十七轮登记排名 |
| P3 ETF 线性/宏观 | 后续单独冻结提案 | 不继续旧 GPU 训练或自动开启新搜索；先冻结因果宏观版本与 60/40 基准 |
| P4 forecast_upgrade | 后续公告版本配对与样本资格 | 可复用版本时钟方法，不复用 Q-DIV 的资格认证 |
| P5 CTA-R/短周期 | 不增加本轮实验 | CTA-R 当前冻结状态和已有采集状态只看 current；不据外部提案重启 |

原 Q-DIV-IVOL 合同与最新 Q-DIV-Core 设计均保持。FF3、ATR 阶梯退出、额外质量门和宏观择时属于后续新假说，本次未混入原规则、未新增 A 股收益实验。2015–2026 已消费历史不成为独立 OOS。

## P1：历史版本和现金账本

新增 [版本索引](../src/qount/research/q_div_pit.py)，按 API/证券/报告期/可用日期保留所有版本，二分查询严格早于 signal date 的最新版本。以 `max(ann_date,f_ann_date)` 为 vendor 条件时钟，`update_flag` 不决定历史可用性；数值相同重复记录合并，同日数值冲突列未知。未来修订不重写此前截面。外部公告核验记录需绑定完整行 hash、原公告 hash、可核引用和公开日期；即便单行对上，仍不认证全宇宙历史覆盖。[Tushare 利润表字段说明](https://tushare.pro/document/2?doc_id=44)将 f_ann_date 与 update_flag 分别列为实际公告日期和更新标志，未把最新版标志定义为历史版本认证。

复用原 480 份公开响应并验证哈希/行数，WSL 审计 120 只当前技术短名单、47 个日历季度截止日（2015Q1–2026Q3；**不是交易所执行日历**）。合计 7,580 条合并报表记录、5,424 个报告期/公告组、2,155 个多记录组、3 个同日数值冲突。5,640 个截面中 4,403 个未知、1,237 个为可条件计算的 vendor snapshot；2015Q1、2015Q4、2020Q4 均为 120/120 未知，2026Q3 为 119 个条件可算＋1 个未知。完整结果在 E，Mac 仅保留[摘要](../state/research_runs/research_remediation_20261011/q-div-history-summary.json)、[冲突](../state/research_runs/research_remediation_20261011/q-div-history-conflicts.json)和[manifest](../state/research_runs/research_remediation_20261011/q-div-history-manifest.json)。

**这些多记录不能凭排序“修好”：** 有不同日期的修订按时钟选择；同日矛盾需要原公告裁决；原先没有收集的历史版本/证券必须补来源。120 只当期短名单不能回填为历史股票池，1,237 个条件截面也不等于 PIT 认证。正式四曲线未运行，A 股累计主要规则/已评价规则仍为 8/6。

新增 [CashBook](../src/qount/research/q_div_cash.py) 是原价现金会计内核，原 [ashare_strategy.Book](../src/qount/research/ashare_strategy.py) 保留为复权单位代理，不能叠加现金股息。新内核支持登记日收盘批次权益、除息日应收、付款日收盘入现金、付款后再投资、FIFO 分批卖出和按批次保留的股息税负。付款前应收不能买股；已付股息待结算税款从可用现金中预留，出售后按该批次的最终税率结算。持有期税负降低单列为负债变化，不重复计股息。税率/日期费率由显式 policy 注入，合成测试参数不是法律或券商费率认证。

内核还支持 T+1、买入单次到期开盘尝试、100 股买入手数、上一决策 ADV 的 1% 成交上限；新买入按当前标价/扣费后 NAV 约束行业 20% 容量。价格漂移、历史行业变更和受阻卖单仍需外层目标求解器处理，不能宣称实际权重连续不超限。真实涨跌停/停牌/开盘成交证据、送转/配股/注销/退市结算、取消股息、特别分红分类与股本桥、动态组合引擎以及历史税费尚未闭环。**内核不是完整策略回测引擎，未认证真实现金总回报。**

历史审计根：`/mnt/e/qount_data/qount/artifacts/equity_selection/q_div_history_audit_20261011T073000Z`。

## P2：冻结梯度对比口径

[合同](../config/c60-gradient-20261011.json)只新增一个主要候选 `gradient_deadband`，`gradient_only` 为一个拆解诊断，`binary` 为原规则对照；每个固定 25/50 bps × 0/1 日额外延迟，共 12 条完成目标曲线，不做参数搜索。BTC 已闭合 close/SMA50−1 在 ≤−2%、(−2%,0]、(0,2%]、>2% 时分别给出 0/35/70/100% 预算。自身 SMA20、月末 PIT 选币与 90 日动量排名保持，PAXG 仍豁免 BTC 闸门，之后沿用 60% 年化波动目标。因此阶梯数值是闸门预算，不保证组合实际总敞口恰等于这些数值。

不交易带比较**实际开盘漂移后的整组合 L1 权重变动**，包含换币两边；≤15% 时不成交，>15% 执行原目标。不是比较昨日目标，也不是每只证券分别 15%。小额退出同样可能被抑制，持仓可暂留，不另加未登记的安全退出规则。开盘才有的权重仅用于成本/成交量阈值，不用开盘价重新选币或计算趋势信号。

主评价为 2021-01-01–2026-08-31，所有账户从同日起点现金开始、月度选择状态从历史预热继承；2026 YTD 是该连续账本从 1/1 切片，不重置资产或 NAV。四个成本/延迟格均须换手下降、CAGR 不低于 binary、最大回撤不恶化；任何失败保留失败。本门仅为历史筛查，不能授予 forward/paper/生产权限；未做 DSR/PBO，全局 trial 数仍待核。

[既有归因](c60-turnover-attribution-diagnostic-2026-09.md)的 82.1% 是自身 SMA20 与 BTC SMA50 **联合闸门**的全样本目标换手归因，2026 对应 90.7%，没有分离 BTC 单独贡献，也不是可保证削掉的成本。梯度函数和不交易带的效果均由本轮结果判断。

原开盘价缓存不足时运行在候选收益前停止，保留两个缺输入目录与 revision1/2 合同。先合并既有扩展/状态/广度研究的同源开盘价缓存，再按原哈希仅补 DASH 的 2025-12、2026-01 两个 Binance 月包；包 hash 与原收盘/成交量逐行一致才投影为开盘价。revision3 仅增补输入来源，经济规则和实现 hash 未变，未读候选结果后调参。先前控制曲线也保留，不隐去失败准备过程。

## P2：完成结果（2026-10-11）

**冻结候选失败，保留且不晋级。** 四格换手均下降，但 CAGR 全部下降，三格最大回撤恶化。`gradient_only` 的四格换手反而略高于 binary；组合换手的下降来自所测不交易带，不能解释为 BTC 梯度已削掉 82% 闸门磨损。

| 成本/额外延迟 | binary CAGR → 梯度＋死区 | binary 最大回撤 → 梯度＋死区 | 年化双边换手变化 |
| --- | --- | --- | --- |
| c25-d0 | 14.43% → 13.04% | 45.48% → 52.65% | 29.80× → 27.75×（-6.88%） |
| c25-d1 | 8.50% → 6.47% | 48.93% → 49.69% | 30.18× → 27.78×（-7.97%） |
| c50-d0 | 6.21% → 5.46% | 50.08% → 56.68% | 29.78× → 27.73×（-6.87%） |
| c50-d1 | 0.61% → -0.68% | 56.72% → 54.20% | 30.16× → 27.76×（-7.97%） |

25bps/无额外延迟的 2026-01-01–08-31 连续账本切片收益为 binary **+8.04%**、仅梯度 **+5.89%**、梯度＋死区 **+2.27%**。其它三格 YTD 的候选与原规则也全部列于[完整摘要](../state/research_runs/research_remediation_20261011/c60-summary.json)，不只展示有利格。该历史 PIT 宇宙和执行窗口不是既有 v1/v2 paper 的复现，不能直接拼接其当前收益。12 条完成曲线均无缺失标价；“原始二元闸门”也是历史对照，不代表获得晋级。

完整根：`/mnt/e/qount_data/qount/artifacts/dual_engine/gradient_20261011T073000Z_v3`；[manifest 回执](../state/research_runs/research_remediation_20261011/c60-manifest.json)。[总研究索引](../config/dual-engine-research-registry.json)以 supplemental discovery 登记一个主要规则、一个诊断、12 条完成对比曲线及先前两条完整 binary 控制回放，共 14 次曲线暴露；原十七轮 1,137 曲线/152 候选的冻结排名范围和领先者保持，合计已知曲线暴露为 1,151，全局 trial 数仍未解决。

## 凭据与交付边界

### 全市场历史补采（2026-10-11）

**本轮约定输入范围已完成**：27,345个必需分片全部取得/复用并独立核验，原计划27,346分片全部进入审计；owner明确“不考虑st”，排除1个st事件接口，保留其原40203拒绝。主批一次HTTP不完整读取失败另根精确补抓完成，原失败继续保留。最终7组独立审计经hash/计划ID/分页/字段/身份/期别与分区覆盖合并0完整性错误，[合并摘要](../state/research_runs/q_div_full_data_20261011/full-audit-summary.json)。

[Mac采集模块](../src/qount/research/q_div_acquisition.py)、[薄入口](../scripts/research/q_div_acquire.py)、[Windows公开接收器](../scripts/research/q_div_public_sink.ps1)按[合同](../config/q-div-full-acquisition-20261011.json)revision3运行：8线程共享420次/分钟上限，限流全局冷却/降速，网络/429/5xx/IncompleteRead最多5次退避，认证/权限/结构错误不重试，存储失败停止。公开响应发送前检测凭据泄漏，E独占写入并复读hash，令牌仅Mac私有0600文件与内存。主批请求21,810，复用5,939完成分片；v1/v2各246/5,963响应、未完分页、源代码/合同及中止记录均封存。新补抓绑定原jobs清单hash，仅处理已失败运输分片，不覆盖成功或权限拒绝。

三所L/D/P主表5,912代码/339退市记录；55季度×三表×12报告类型1,980分片；分红6,715代码（含248北交映射/636财报独有代码，仅未认证历史身份输入）。3,102联合开市日、18,123行情分片，六个指数代码和14年SHIBOR已补取。供应商返回行数如下，不代表逐证券日期或公告原版本全部合格。

| 输入 | 行数 |
| --- | ---: |
| 利润表 | 1,578,554 |
| 现金流量表 | 1,537,489 |
| 资产负债表 | 806,330 |
| 分红全阶段 | 273,383 |
| 日线原价 | 12,374,680 |
| 逐日指标 | 12,284,050 |
| 复权因子 | 12,940,048 |
| 涨跌停 | 12,705,477 |
| 停复牌 | 386,967 |
| 备用名单 | 10,807,179 |
| 业绩预告 | 96,611 |
| 业绩快报 | 23,352 |
| 披露日 | 221,422 |
| 指数日线 | 20,040 |
| SHIBOR | 3,411 |

主输入 `E:/qount_data/qount/datasets/equity_selection/q_div_full_v3_20261011T084100Z`；补抓 `E:/qount_data/qount/datasets/equity_selection/q_div_transport_repair_20261011T093600Z`；合并核验 `E:/qount_data/qount/artifacts/equity_selection/q_div_full_reconciled_audit_20261011T094500Z`。原始压缩响应、phase计划、失败、源代码和hash清单保留E，Mac仅代码/文档/轻量回执。直接WSL SSH的E挂载不可用，现有Windows入口启动的WSL命名空间可读E；未改挂载、服务、持久环境、主checkout或虚拟环境。[独立审计模块](../src/qount/research/q_div_data_audit.py)重新读取原响应；明确ID分区最终不重叠覆盖原计划，补抓来源单独核验后精确合并，不把部分通过当全量通过。

在WSL读取本轮完整来源时，必须显式绑定运输补抓根；原失败根单独读取会拒绝该日期：

```python
from qount.research.q_div_sources import PublicHistorySources

sources = PublicHistorySources(
    "/mnt/e/qount_data/qount/datasets/equity_selection/q_div_full_v3_20261011T084100Z",
    repair_roots=["/mnt/e/qount_data/qount/datasets/equity_selection/q_div_transport_repair_20261011T093600Z"],
)
for page in sources.pages("daily", trade_date="20210917"):
    rows = page["items"]  # 已核验4,593行；仍不是可交易资格或策略信号
```

财报762,643合并时点组中257,204多记录、191同日经济冲突，未按update_flag挑有利版本。61,494条标为实施的分红中3,686缺付款日、32缺除息日、5缺登记日；13,255含送转。bak_basic虽已请求2016起各日，但非空仅始于2016-08-09；此前空响应不补成历史名单。BSE日历为空、vendor证券日期缺记录、历史身份/行业公告时钟及原始公告版本仍待证据，不能填零或将除息当到账。数据采集可用与历史PIT/完整总回报资格分开，正式四曲线未运行。

[流式读取器](../src/qount/research/q_div_sources.py)核验原分页/继承/补抓来源，并保留原字段和版本hash；财报索引按证券访问，时钟/冲突语义保持。[预声明读取测试](../state/research_runs/q_div_full_data_20261011/reader-smoke-summary.json)：5证券×3期读取65行，4条件截面/1冲突未知，要求原公告证据时5只全部未知。Mac和WSL各95项专项通过，编译/新CLI/hygiene/diff通过，[验证](../state/research_runs/q_div_full_data_20261011/validation.json)；未重跑全仓。WSL首次测试包缺共享fixture而失败的compute-v5目录/源码保留，补依赖v6通过92，运输修复v7通过95。合并器首版集合互斥断言写错而停止，修正后覆盖/hash合并通过；原脚本/失败回执保留，未重采原数据。原策略设计/9月30日截面/8规则6已评价保持，无新筛选、收益、规则或参数搜索；research_only=true/orders_authorized=false/promotion_evidence=false。

本轮公开源码/文档/回执归档 `/mnt/e/qount_data/qount/artifacts/equity_selection/q_div_full_delivery_archive_20261011T095000Z`，包hash `c6d719d89d47b963aad18f390934c8abff6bc5777f650fd1885d9da8e897a280`，66声明文件＋manifest共67成员独立核验通过，未含凭据；[归档回执](../state/research_runs/q_div_full_data_20261011/final-delivery-receipt.json)。归档内文档为追加本回执前快照。

此前小范围验证阶段，owner 明确要求保留的 Tushare 凭据仅存 Mac `~/.config/qount/tushare.env`，`0600`；未复制到仓库、WSL/E 或 VPS，当时未接入采集器。旧凭据官方 HTTPS 日历/三表/分红 5 个只读探测均返回 `40101`，追加一次日历确认提示 token 不正确；共 6 次请求，无自动重试或批量采集。[旧无凭据探测回执](../state/research_runs/research_remediation_20261011/tushare-probe.json)保留。

2026-10-11 08:10 UTC，按 owner 后续要求原子替换最新凭据并立即使用。日历及 600900.SH 的利润表、现金流量表、资产负债表、分红共5次官方 HTTPS 只读请求均 code=0、返回字段匹配，分别1/12/15/12/54行，无自动重试；最新凭据认证与这些小范围接口访问已验证。[最新无凭据回执](../state/research_runs/research_remediation_20261011/tushare-latest-probe-20261011T081006Z.json)仅含状态、行数、响应hash与私有路径，不含凭据或原始财报数据。权限检查为0600，未同步或批量采集；本次接口成功不解决历史版本/PIT、历史宇宙覆盖或配额充分性。

最新凭据的小范围接口门已通过，owner随后授权的全市场补采预算已冻结并执行；正式历史运行仍须补齐公告版本证据、历史证券身份和公司行动口径，不能将供应商当前快照宣布为历史PIT。Mac 保留代码/文档/轻量回执，WSL 用独立 public-only 源码交付，不改主 checkout、虚拟环境或服务；E 保存完整输入/曲线/审计结果。

## 验证与保留

Mac 全仓 `unittest discover -s tests -p test*.py` 实际执行 3,395 项，3,361 通过、34 条件跳过，98.084 秒 exit0；该次完成后新增的独立 C60 会计核验模块另有 1 项专项通过。最终 owning suites 为 C60 59 项、Q-DIV 51 项；WSL 交付前 42 项聚焦场景通过。新增入口 help、公开 qount-run help、src/scripts-maintenance 与新适配器编译通过，hygiene/diff检查通过。不存在部署或 VPS 运行验证声明。

P1 另用原 `report_map` 路径选择原始版本并直接计算 TTM/ROE/CFO/杠杆，复算 1,128 个有可比数值的截面、5,543 个数值，误差 0；其余 109 个条件截面属于排除/无有效分母等情况，未声称独立复核全部未知原因。[P1 复算回执](../state/research_runs/research_remediation_20261011/q-div-history-verification.json)。

P2 独立以现金和份额、币种原价及二分求解费用复算 12 账本/24,828 日记录/158,970 数值，最大相对误差 1.17e−15；核对实际漂移权重、整组合死区、费用和收益。该复算未独立重排全历史选币/信号，不能扩大为全链路独立认证。[P2 复算回执](../state/research_runs/research_remediation_20261011/c60-verification.json)。

独立 public-only 交付过程有两次准备失败（不存在的 tests init、遗漏测试依赖），均在候选收益前停止，旧目录保留。WSL 原 checkout 的 `.venv/bin/python` 是指向 Mac 的失效链接，本轮未修复主机/环境；隔离交付使用 WSL 自带 Python3/标准库。来源与交付清单在[交付回执](../state/research_runs/research_remediation_20261011/delivery.json)，Mac 不保留完整数据或曲线。

最终 public-only 归档位于 `/mnt/e/qount_data/qount/artifacts/equity_selection/remediation_delivery_archive_20261011T075000Z`，包 SHA256 `8eed187982a817c083e19652f6c7517ccc2f21615ca6ae107a00e18af0d7d820`，81 个声明文件逐项哈希核对通过；包另含声明 manifest，共82文件。归档不含凭据、数据全集或活动数据库。见[归档回执](../state/research_runs/research_remediation_20261011/archive-receipt.json)；包内文档为本回执追加前快照。
