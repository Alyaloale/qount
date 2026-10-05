# qount 当前状态

> **状态**：active｜**权威**：L1 当前事实（#1）｜**最后更新**：2026-10-05
> **本文回答**：当前生产事实、能力边界、运行状态、下一步、硬边界。
> **TL;DR**：第十三轮共同结算与家族刷新研究完成，8候选／76曲线；累计248版本／981曲线／132本地候选。C60卫星周度刷新成为历史排名领先，稳定增量未确认；G20原领先保留，pending源退出缺口明确。全部research_only，未来确认pending；P3 outer withheld及既有paper／Dashboard／公共采集事实保留，交易timer关闭。

更新时间：2026-10-05

## G20 / C60 共同结算与家族刷新改革（2026-10-05，第十三轮完成）

owner再次授权“推进下一版大改研究”。[合同](../config/dual-engine-zorder-20261005.json)冻结8新候选／11控制／76曲线；G20共同表达源变化和已收盘投资额预算、一书单次实际费用求解，C60分开核心／卫星周度刷新及恢复连带。v1第二起始前迟到指令错误资本重置现场隔离，未据其收益调参；v2只补正月度／初始标记，18专项及新公开源码冻结后新目录单次WSL130.74秒、exit0。原日期、名义目标／选择、风险门、四格成本延迟及政策不变。

C60 `sat_week`成为条件历史排名领先，周日只刷新卫星、核心恢复仍耦合全书：基础／压力CAGR22.62%／22.02%，压力回撤16.90%，四格最弱Sharpe1.1531（在50bps次日格）、四格最坏回撤19.03%；旧卫星恢复24.12%／20.88%、23.13%、0.9780／25.23%。压力平均风险投资额20.58%→15.48%、波动21.82%→17.52%、费用减42.65%，削减核心周度刷新也损失基础收益。剔2021基础13.46%→11.17%、压力9.81%→10.23%；基础Sharpe区间跨零、压力Sharpe三块区间在0上方，但两格log-growth区间均跨零且未经全局选择校正，稳定增量未确认。核心周度／分日／局部核心恢复的完整取舍与负结果保留。

G20 joint40_rotate对daily40压力17.87%→18.31%、回撤34.34%→33.38%、最弱0.6991→0.7184，仍低原0.8914；实际投资额峰值44.40%、资本峰值49.11%，不是连续40%硬上限。触及预算扩为全书，允许风险购入、总费用反增；四压力格还出现11／10／7／4个买回决策名义已零旧资产的事件，源退出仍在队列时共同目标保存旧实际仓位，pending所有权缺口没有解决。全部历史结果保留，不在收益后修规则，不作晋级证据。

[登记](../config/dual-engine-research-registry.json)十三轮248版本／981曲线／132本地候选，旧229描述与十二结果、八诊断剔除及所有旧确认／信息／归因指针保留；222合资格（G20 109／C60 113）。G20仍`dual_engine_breadth_20261005/g20/aware_gold_rotate`；C60 `dual_engine_zorder_20261005/c60/sat_week`，不继承旧后续确认。状态historical_ranking_verified_stability_unconfirmed_pending_prospective；没有新独立OOS、DSR/PBO、后续采集、前向窗口、拟合或调度。

独立76现金账本、33,104因果风险决策、100,512共同书预算／3,122预算触及成交、38持仓归因通过；44控制收益精确相同，39账本字节相同、4仅取消资产列表顺序、1仅现金／费用相关浮点求和传播≤2.22e−16且单位／NAV／目标／收益精确相同，逐叶差异及失败复核日志保存。8源目标／选择字节相同，64源码同冻结；现金／指标／费用误差≤1.78e−15、财富误差≤1.23e−14，缺价／无法成交0。Mac18／WSL18专项，修正后全仓3,041（3,007通过／34跳过）95.876秒、exit0；编译／公开CLI及最后hygiene／diff／交接收据保存。

E根`/mnt/e/qount_data/qount/artifacts/dual_engine/zorder_20261005T093252Z_v2`，结果manifest `c9a2db406d4809c1516612c8bc5ffd728f9cfbc04b218cf7d4e26dbdb875fc78`，登记manifest `aec48f178b83edaee12b95f6be21e4f615db4c8735d20b0203d0297b64e11fcc`；拒绝v1保留`/mnt/e/qount_data/qount/artifacts/dual_engine/zorder_20261005T092858Z`。Mac`state/research_runs/dual_engine_zorder_20261005/`。[完整结果、归因与下一问题](dual-engine-optimization-2026-10.md#18-源目标与风险共同结算家族刷新分离第十三轮)。本轮research_only=true/orders_authorized=false/promotion_evidence=false；paper／生产／账户／服务／VPS／调度与各线窗口边界不变。

## G20 / C60 研究证据与接手路径

十三轮的运行前协议、完整正负结果、历轮排名和失败修订统一保存于[主研究总览](dual-engine-optimization-2026-10.md#研究总览与阅读路径)。本页上方只维护最新研究事实；旧轮次的累计数量和当轮领先是历史快照，不能覆盖当前登记或既有模拟盘合同。

- 查版本、固定选择政策及原结果hash：[研究登记](../config/dual-engine-research-registry.json)。
- 查候选与数据合同：[配置参考](reference/configuration.md#g20c60-离线研究合同)。
- 查采集、回放、登记与确认参数：[CLI参考](reference/cli-and-scripts.md#g20c60-research-studies)。
- 查包职责、薄适配器和验证位置：[仓库地图](reference/repository-map.md#g20c60-offline-research-ownership)。
- 查既有paper口径：[策略总集](qount_strategy_master_index.md#当前有效模拟盘合同覆盖下方历史歧义)；研究排名不更换paper参数。

所有原manifest、旧确认、失败结果与诊断剔除均保留；Mac只留轻量回执，E保留完整不可变数据／账本。下一窗口与其他研究线的授权按本文各线事实读取，不能从历史研究或部署模板推定。

## 最新 ETF P3 运行结论与已消费授权

- **2026-10-04 01:42 CST owner 决定：“开始训练！”**
  明确授权启动当前已部署的R3残差研究引擎，采用[复审schema-v2合同](../config/etf-alpha-residual-reviewed-20261003.json)及稳定ready指针绑定的代码/数据。授权仅作用于本次独立单轮运行，`training_start_authorized=true/automatic_restart_authorized=false/research_only=true/orders_authorized=false`；原提案、运行合同和READY保持不可变，实际激活由新owner回执承接。
  开训前再次check通过：准备/源码/原六输入hash、E盘挂载、隔离CUDA环境与共享锁正常，新激活回执绑定全部fingerprints及独立结果目录。**01:44:34 CST开始真实拟合，01:45:29完成pilot和选择，01:45:40完成manifest并正常退出，exit_code=0。** `training_status=pilot_no_increment/outer_test_status=withheld`，51/51 fits（45神经＋6确定性Ridge）、失败0；实际训练/选择55.36秒，含退出清单约66.70秒。01:46实机确认原PID1334已退出、共享CUDA锁释放、GPU利用率0%。
  **01:49:12 CST结果核验通过：** 345项结果文件/2,135,115bytes逐项hash匹配；90个best/last checkpoint严格CPU加载、360个模型tensor及optimizer状态有限，45份history共1,685epochs/13,024optimizer steps，51份预测有限且精确匹配各槽形状及输入hash。33组实际空对照原日期配对0、最小位移46日≥25。没有final/outer结果，选择未使用outer标签。run manifest SHA256=`312d1a8c7746515766b367204d8c10e870300b1dbf62ed96704877c27c204297`。
  两个真实候选均未合格，选择回落`zero_residual_reconstruction`：MLP平均残差RankIC0.05347、自身3/3年为正、3/5配对seed及Huber/组合增量门通过，但相对两种空对照的40/60/120日95%区间下界全部≤0；Ridge自身仅1/3年为正，另有区间、Huber及组合增量门失败。此次不能证明合格的残差增量，不能将正inner收益当作outer结论。[研究结果与失败门](etf-p3-research-plan-2026-10.md#24-r3残差pilot执行与结果2026-10-04)。
  结果根`/mnt/e/qount_data/qount/artifacts/etf_alpha_p3/residual_run_20261003T174223Z`；同级`_verification/`保存激活、preflight、启动/退出/结果核验及公开文档快照。Mac只保留轻量JSON和报告`state/research_runs/etf_alpha_residual_start_20261003T174223Z/`，稳定运行指针`state/research_runs/etf_alpha_residual/latest-run.json`。开训与结果交付阶段的repository hygiene与文档diff检查通过，当时未重跑全仓或新增训练测试；后续代码提交验证见[更新记录](update-log.md)。
  预设pilot停止条件已触发，未继续至272 fits或153-inner冻结/119-final阶段。不扩大模型、数据、seed、预算或自动放宽失败门，无自动重启、十seed扩展或云端恢复；VPS、P2、外部账户、生产服务和交易权限不变。历史仍为discovery，本次启动授权已经由已结束的单轮任务消费。

## 既有决策与实施记录

以下保留各次部署、待命、启动、停止与核验的时间快照；旧记录中的“当前”“等待”描述其当时阶段，不能覆盖上方最新运行结论或授予新一轮训练权限。

- **2026-10-04 owner 要求检查新一轮设计、优化创新、梳理文档并保持可开训；跨日完成复审部署。**
  继续已授权的R3实施/准备，不构成开训指令。复现并修正两处问题：分年账本可能漏掉年末收盘到次年开盘的21日再平衡；完整60日块含不完整尾块的错配可能仅移动2–18日，仍重叠20日标签。新 [schema-v2复审合同](../config/etf-alpha-residual-reviewed-20261003.json) 绑定原提案和首版合同hash，登记逐年预测拼接后连续执行、所有空对照日期位移≥25日（20＋5）；研究参数、模型、种子及51/272预算不变。
  **01:29:34 CST 实机核验通过：`training_status=ready_waiting_owner/training_start_authorized=false/automatic_restart_authorized=false`。** 16个数据槽与源码/原六输入/准备清单hash通过，inner标签尾部purge和原七fold outer执行日期匹配；160组控制实测最小位移28日、原日期配对0。CUDA前向/梯度有限、161参数权重未变；Ridge/神经拟合、optimizer steps、保存模型均为0。无激活的launch/run均exit2且不创建run；占用共享CUDA锁时check拒绝声明ready，实机残差trainer进程0。
  当前WSL代码 `/home/alyaloale/.cache/qount-compute/etf-alpha-residual-reviewed-20261003T144343Z`，Python沿用既有隔离环境；E盘准备根 `/mnt/e/qount_data/qount/artifacts/etf_alpha_p3/residual_reviewed_20261003T144343Z`。准备manifestSHA256=`65bec95f6742aeb51b118afa238909d9208ce8c5878772140888052fc571b448`，源码manifest=`be9e155fb161b253be83465e8059cee7efc2e10a903b2b8903cad11865a9ba60`。稳定指针已更新为 `state/research_runs/etf_alpha_residual_ready/latest-ready.json`；首版提案/runtime-v1/旧READY与v2结果均保留，不再作为本轮默认启动版本。
  Mac ETF Alpha owning suite120项运行、101通过/19 Torch或CUDA条件跳过；WSL R3聚焦31项全部通过、0跳过。公开55文件包与Mac当前逐项hash一致，准备/公开交付/环境锁/实机核验在E盘同级 `_delivery/`、`_verification/`；Mac仅有公开包与轻量回执 `state/research_runs/etf_alpha_residual_review_20261003T144343Z/`。compileall、公共CLI help、hygiene和diff检查通过，未将旧全仓回执计入本次验证。
  跨日连接中断因WSL关闭、既有Windows keepalive任务Ready；经已登记的 `qount-wsl.sh ensure` 唤醒计算环境后SSH恢复，任务回读Running。未改keepalive注册/触发或主机配置，未新增待命任务/调度器、未恢复训练。01:30 CST GPU利用率0%（1198/8188MiB），云端/VPS/P2/外部账户与生产不变。
  设计结论是先做小容量残差pilot；信号收缩、Rank loss、多因子残差等创新候选及采用条件已写入 [P3 §23](etf-p3-research-plan-2026-10.md#23-r3开训前复审修正与创新取舍2026-10-03)，没有加入本轮搜索。后续明确“训练”时再次check、登记激活并启动单次supervisor，无需重装或重新准备；pilot51 fits无增量正常停止，通过才继续至最多272 fits，十seed扩展仍未授权。结果保持discovery，不能影响生产。

- **2026-10-03 owner 决定：“参照方案部署训练引擎，做到随时能开始训练，等我说训练再立马开始”。**
  授权按 §21 方案实现并独立部署 WSL R3 残差引擎、准备数据和验证启动链路；**实际训练须等待后续明确“训练”指令**。本次 `training_start_authorized=false/automatic_restart_authorized=false`，不提供预授权回执或常驻自动启动任务。
  **22:19:16 CST 最终实机回读：`training_status=ready_waiting_owner/implementation_status=implemented`，16个数据槽准备及清单核验通过；Ridge/神经拟合、optimizer steps和保存的模型均为0。** CUDA前向/反向有限，161参数模型权重未变。WSL26项检查全部通过；Mac聚焦26项23通过/3 Torch条件跳过，全仓2762项2728通过/34条件跳过。旧 v2 启动授权不延伸到本轮，云端仍暂停；不改变 VPS、服务、P2 或生产。
  原 [残差提案](../config/etf-alpha-residual-pilot-20261003.json) 保留为历史方案快照；新 [运行合同](../config/etf-alpha-residual-ready-20261003.json) 绑定其 hash。九个inner2017–2025与七个final2020–2026槽均已冻结，外层执行日期精确匹配原日历；inner尾部标签purge，全年账本日期保留，final槽不存outer标签。两种打乱控制160组seed/槽检查均为零原日期配对。
  WSL代码 `/home/alyaloale/.cache/qount-compute/etf-alpha-residual-ready-20261003T141654Z`，环境沿用 `/home/alyaloale/.cache/qount-compute/venvs/etf-alpha-20261003/bin/python`。准备数据/公开源码快照/READY在 `/mnt/e/qount_data/qount/artifacts/etf_alpha_p3/residual_ready_20261003T141654Z`；准备manifest SHA256=`d985ba9a6fc7f964b984a695ca58ff8d78e8881acac92b0b85b0342f4f9eeed4`，部署源码manifest=`9e18e916f4a01a3c5993b43ca7c921a947945853e2de2823d159f0924932f43e`。
  公开54文件交付包、环境锁与实机回执分别在 E盘同级 `residual_engine_delivery_20261003T141654Z/`、`residual_ready_20261003T141654Z_verification/`；Mac只保留公开包/轻量回执，稳定指针 `state/research_runs/etf_alpha_residual_ready/latest-ready.json`。本次首份准备快照（140614Z）保留，最终指针只绑定141654Z版本。
  **22:25 CST 交付前复核：共享CUDA锁可获取，残差trainer进程0，GPU利用率0%（416/8188MiB）。** 最终公开包与Mac当前54源文件逐项hash一致；compileall、公共CLI help、hygiene与diff检查通过，未启动等待进程。
  `prepare/check/status`可用；缺少后续激活回执的`launch/run`实测exit2且不创建run。收到后续明确开训指令后，只需再次check、登记新owner激活并启动单次supervisor，免重装/重备数据。先51-fit pilot，无增量正常退出且outer withheld；通过后最多272 fits含pilot，153个inner fits后冻结全部选择/epochs再做119个final fits。无常驻等待任务、调度器或自动重启；十seed扩展未授权。细节见 [部署手册](../deploy/wsl/alpha-residual/README.md) 和 [P3 §22](etf-p3-research-plan-2026-10.md#22-残差训练引擎实施与待命部署2026-10-03)。

- **2026-10-03 owner 要求分析负对照收益、单年选模稳定性与模型原因，决定下一轮方案。**
  已完成冻结结果的WSL CPU诊断，无新增拟合；1,724个本轮读取的不同结果文件hash匹配，七组合×七折49条原2×曲线重放一致，105个冻结checkpoint原CPU预测复现（最大差1.4343e-7）。Mac新测试7项通过，ETF Alpha owning suite 89项运行/73通过/16条件跳过；WSL新测试7项通过。
  标签日期块shuffle累计净利润126.71%，QQQ＋SPY贡献83.38个百分点、占65.81%；上一验证年固定模板仍有CAGR8.04%。对照保留资产身份/均值，16/35fit存在原日期配对（最高12.77%），也使用真实验证标签选checkpoint；正利润不能视作预测Alpha。
  七折验证→次年排序五折反向，相关中位-0.4；2021折动量赢家日期块扰动保留率仅15.8%–23.0%。年度账户重置仅使selected CAGR由5.69%到5.96%，解释不了落后固定动量5.15个百分点。统一实际五seed平均预测的验证账本后，2026折诊断赢家由Ridge改为旧MLP；不回写原选择或重置连续风险状态。
  增强模型固定模板8.61%接近原8.97%；统一冻结身份embedding后仅3.14%，是身份先验依赖线索，不是重训去ID消融。负对照统一ID后仍11.75%，收益原因不局限于显式ID。方法、完整数字与边界见 [P3 §21](etf-p3-research-plan-2026-10.md#21-负对照归因选模稳定性与下一轮训练方案2026-10-03)。
  **下一轮选定** [残差pilot提案](../config/etf-alpha-residual-pilot-20261003.json)：20日收益扣训练资产均值/因果市场beta/残差资产均值；Ridge9参数与共享MLP161参数，真实数据、不扩大bootstrap/标的/网络，强化时间及资产打乱控制。前三年连续inner验证、checkpoint与inner评估分离，验证及outer交易同一五seed平均预测，保留成本/风险/21日日历与连续状态。
  先完成2017–2019三个inner槽，最多51fits（45神经＋6Ridge），无残差增量便在outer前停止；通过后全轮最多272fits（含pilot：240神经＋32Ridge），outer选择/epochs在报告前冻结。十seed扩展另登记，五seedpilot不构成R门通过。
  **分析交付时方案快照为 `training_start_authorized=false/training_status=plan_selected_not_started/implementation_status=planned_not_implemented/automatic_restart_authorized=false`；当前实现/部署事实以上方最新 owner 决定为准。** 当时仅决定方案，没有启动下一轮；旧259fits授权不自动延伸。已消费历史保持discovery，不进入Stage2/生产，云端仍暂停。
  数值分析/身份干预分别保存E盘同级 `expanded_20261003T074405Z_analysis_20261003T123218Z/`、`expanded_20261003T074405Z_identity_probe_20261003T124218Z/`；综合报告/CSV/提案/源码/回执在 `expanded_20261003T074405Z_analysis_review_20261003T130630Z/`。Mac仅有轻量副本，位置记录 `state/research_runs/etf_alpha_wsl_restart_20261003T074405Z/latest-analysis-location.json`；原run未改。

- **2026-10-03 本轮v2开训 owner 决定：“wsl已修复，开始训练！！！！”（固定任务现已完成）。**
  本次明确恢复 WSL RTX4060 的 P3 v2 固定研究训练，覆盖先前等待 WSL 的停止指令；[WSL v2 合同](../config/etf-alpha-expanded-20261003.json) 为 `training_start_authorized=true/training_status=authorized/automatic_restart_authorized=false`；运行阶段由新 run 的 `status.json` 记录。
  沿用 `max_hours=null/wall_clock_limit_enabled=false`，固定 7,168 个增强世界、七配置 ×七 folds ×五 seeds 加 14 个确定性对照，最多 259 fits；单 fit 预训练 256 epochs/600 秒与真实数据早停不变。
  SSH 已恢复、RTX4060 与独立 Torch2.13.0+cu130/NumPy2.5.1 环境的 CUDA 前向/反向有限值检查通过。E 盘旧挂载的 `No such device` 已在训练进程所在 systemd mount namespace 中重挂修复，剩余 979,088,441,344 bytes；Windows 只读 `chkdsk E:` 报告无文件系统问题、0 坏扇区，dirty 标记未主动清除。
  冻结 M0/M1 六个数据文件、原 manifest hash、fold-contract hash、七个因果切分已核验通过；公开代码包 63 项逐文件/整包核验通过，补齐打包测试依赖后 WSL 67 项全部通过、0 跳过。
  已于 **2026-10-03 15:59:59 CST** 在 tmux `alpha_v2_20261003T074405Z` 启动，supervisor/trainer PID 为 8391/8393；外层没有 `timeout`，共享 CUDA 锁防止重复启动，退出后保留原始退出回执。
  **现已正常完成：19:17:24 CST `status=complete/outer_test_status=complete`；19:19:06 CST 完成最终清单并退出，`exit_code=0`，总墙钟3小时19分07秒。259/259 fits完成（245神经+14确定性对照）、失败0。** 35个增强预训练fit均完成256epochs，平均271.20秒；19:37实机核实原supervisor/trainer均已退出，GPU利用率0%。固定任务已结束，不自动重启。
  **本次结果核验通过（19:48:25 CST）：** 3,498项结果文件/641,824,327bytes全部重新hash匹配；245个best checkpoint严格加载、3,570个tensor有限，735份seed预测及91份outer预测通过有限值/形状检查。七折选模重算匹配、全部在outer前冻结；13个family×三成本的连续CAGR/现金超额Sharpe/MDD从净值曲线复算一致。
  **19:58:21 CST 补充日期/因果核验通过：** 原六个冻结输入重新hash匹配，七fold的因果标签、purge/5日embargo重验通过；490份seed test/validation日期数组和91对outer prediction/IC日期均精确匹配冻结切分。回执为同一Mac证据根的 `prediction-date-audit-20261003T115821Z.json`，E盘同级另存 `.prediction-date-audit-20261003.json`，不改原run。
  2020–2026-10-01连续outer的最终selected在2×成本下为 **CAGR5.69%、现金超额Sharpe0.342、MDD16.23%**；剔除最佳完整年2024后CAGR3.96%。同规则简单动量为10.84%/0.753/13.63%，剔除最佳年仍9.47%。2026为部分年度，不作全年收益。
  七折最终选择依次为Ridge、动量、Ridge、现金、资产历史均值、资产历史均值、Ridge，神经模型0/7折胜出。增强模型仅1/7折合格，固定family的2×成本为8.97%/0.626/16.73%，低于同结构未增强版本9.36%/0.662/16.21%；点估计未改善，配对增量区间仍跨零。
  增强模型outer日期加权RankIC0.0840低于资产历史均值0.1403，配对差-0.0563的40/60/120日块95%诊断区间均在零以下；标签块打乱神经负对照反而为12.94%/0.920/15.34%，不能将其升级为策略成功。结果保持`research_diagnostics`，未证明神经/增强增量Alpha，不进入Stage2或生产；历史仍为discovery，新鲜确认不足。
  完整结果与边界见 [P3 §19.5](etf-p3-research-plan-2026-10.md#195-完整结果与回读核验2026-10-03)。派生核验报告已保存到E盘同级 `expanded_20261003T074405Z_review_20261003T115219Z/`，六项文件另有完整manifest回读；原run未改。Mac轻量报告在 `state/research_runs/etf_alpha_wsl_restart_20261003T074405Z/review-20261003T115219Z/REPORT.md`，实际核验回执为 `artifact-audit-20261003T114826Z.json`。
  **17:06:47 CST 回读：`status=gpu_training`，84 fits已启动、83/259 fits完成（14确定性对照+69神经fits）、失败0，bootstrap fits完成9/35，outer withheld。** 当前为 `WF2021/v2-bootstrap-rank-id/seed1004`；896/896 个分片、7,168 个增强世界已经完整保存并完成 hash 回读，CPU workers退出后才进入GPU，抽查分片 `torch_imported=false/validation_or_test_sampled=false`；无退出回执。
  **18:58:05 CST 本次只读回读：`status=gpu_training`，256 fits已启动、255/259 fits完成（98.5%）、失败0；当前为 `WF2026/v2-bootstrap-rank-id/seed1001`，outer仍withheld。** supervisor/trainer PID 8391/8393仍存活，trainer为运行态；RTX4060利用率87%、显存4740/8188 MiB、温度72°C。详细日志/选模文件的SSH回读曾超时，随后单独核实上述状态、进程和GPU，不添加新的validation或完整收益结论；未改变训练、主机或服务状态。轻量证据见 `state/research_runs/etf_alpha_wsl_restart_20261003T074405Z/progress-20261003T105805Z.json`。
  **17:06时的首折验证记录（历史中途快照）：** `WF2020` 使用训练2015–2018、验证2019，选择 `E3-ridge-raw`；本折所有神经候选均未过五seed排序增量门，bootstrap另未过Huber误差门。bootstrap五seed平均RankIC0.1338高于无预训练0.1123、低于历史均值基线0.1920；这不是2020 outer，也不代表后来全部七折。彼时统一冻结与outer未发布；当前完整结果以上方完成/核验记录为准。中途证据见 `state/research_runs/etf_alpha_wsl_restart_20261003T074405Z/validation-progress-20261003T090647.json`。
  新结果根 `/mnt/e/qount_data/qount/artifacts/etf_alpha_p3/expanded_20261003T074405Z`，增强数据在同名 `datasets/etf_alpha_p3/` 根；独立代码在 WSL ext4 `/home/alyaloale/.cache/qount-compute/etf-alpha-expanded-20261003T074405Z`，环境沿用已验证独立 venv。
  Mac 仅保留公开交付包和轻量启动/输入/测试/进度/结果核验证据：`state/research_runs/etf_alpha_wsl_restart_20261003T074405Z/`。启动准备时Mac expanded 15项（8通过、7 Torch/CUDA条件跳过）、cloud 12项全通过；当次hygiene/diff检查通过。本次结果检查采用上方实际产物回读与复算，不将旧unit test或全仓回执当作本次新验证。
  使用新的代码/结果/增强数据目录，保留此前停止产物；完整 CPU 增强数据保存并 hash 核验后才进入单 CUDA trainer。
  本次恢复范围为 WSL；新 3080Ti 合同仍暂停，不恢复 P2/3090，不改变 VPS、服务、云账号或实例状态。
  `research_only=true/orders_authorized=false/holdout_role=discovery`；固定任务完成退出，失败不自动重试，不进入 Stage 2 或生产。

- **2026-10-03 先前 owner 决定：“先梳理文档代码，停止，等我处理wsl”（WSL 停止现已被上方新指令覆盖，云端仍暂停）。**
  当前仅继续 Mac 本地代码、文档、轻量测试与交付包整理；停止云端安装/计算和后续发送/启动，等待 owner 处理 WSL。
  WSL v2 和新云端合同均为 `training_start_authorized=false/training_status=owner_stopped_waiting_wsl/automatic_restart_authorized=false`；取消八小时总限制的参数保留，但不构成当前启动权限。
  新云端只执行过只读检查和独立环境安装，**模型训练/增强生成/GPU标定均未开始**；只上传了独立安装脚本，完整代码包未继续发送。
  已向仅属于本任务的安装进程树发起 SIGTERM/必要时 SIGKILL 的停止请求；执行时 SSH 连接关闭，随后只读连接探测仍被服务器关闭，未能回读停止回执。
  因此云端安装目录按“可能中断、待核实”处理，不声称安装完成、无残留进程或平台已停止计费；恢复连接后先回读进程/停止记录/环境完整性，不能自动续装或开训。
  本地梳理与交付已完成：新增配额/挂载/GPU配置、独立CPU生成与严格复用、工程标定、确定性代码/输入/结果包、分阶段入口及部署手册；旧入口/精度/259fit合同保持。
  代码包在 `state/research_runs/etf_alpha_cloud_3080ti_20261003/delivery/qount-alpha-3080ti-20261003.tar.gz`，53项文件/128793bytes，逐文件和整包hash回读通过；不含真实数据或凭据，暂停合同已打入包，未继续发送。
  Mac聚焦67项运行、65通过、2 CUDA跳过；全仓2729项运行、2698通过、31条件跳过，hygiene/diff/compileall和安装脚本语法通过。新3080Ti GPU标定和CUDA运行测试未做。
  后续恢复计算须登记 owner 新指令，不因 WSL 或新实例上线而自动重启。旧 P2/3090、VPS 与生产服务不变。

- **2026-10-03 owner 决定：为内蒙 B 区 457 机 `jn1f8a7n6z` RTX3080Ti 打包、发送并准备高效的大规模 P3 计算。**
  owner 提供新实例连接，授权梳理程序、独立部署与性能准备；固定 P3 v2 任务和取消整轮八小时限制参数保留，当前暂停决定见上方。
  新计算主机仅承担 `research_only=true/orders_authorized=false/holdout_role=discovery` 计算；不恢复已停止的旧 3090/P2，不改变 VPS 或生产服务。
  此任务允许新云主机数据盘 `/root/autodl-tmp/qount` 临时保存冻结公开输入、增强数据及结果，代码/环境独立安装；最终重要结果仍回收到 E 盘，Mac 保存轻量交付包和摘要。
  已只读连通并核实单张 RTX3080Ti/12288 MiB、595.71.05 驱动；可见 CPU affinity=80，但 cgroup 配额=20 核、内存上限=30 GiB，数据盘=50 GiB 基本为空。
  原镜像 Python3.12.3、Torch2.7.0+cu128/NumPy2.2.6；独立新环境与代码交付正在准备，尚未启动 P3 模型训练。
  当前冻结 M0/M1 数据仍在离线 WSL/E 盘；新实例连接已解决，输入传输与 GPU 校验仍待完成。连接凭据不进入代码、配置、包、日志或产物。
  不新增租赁/扩容/实例释放/云账号权限；训练退出不会被当作实例已停止计费。新主机准备与固定任务范围见 [P3 §20](etf-p3-research-plan-2026-10.md#20-3080-ti-付费云计算交付与性能策略2026-10-03)。

- **2026-10-03 先前 owner 决定：开始大规模训练，并取消整轮八小时上限。**
  owner 明确回复“开始大规模训练”，随后要求“取消8小时上限，我都睡完了”；该授权覆盖上次停止和八小时墙钟要求。
  当时 [P3 v2 合同](../config/etf-alpha-expanded-20261003.json) 改为 `training_start_authorized=true/max_hours=null/wall_clock_limit_enabled=false`；当前再次暂停见顶部。
  固定 7,168 个世界、七个模型配置、七 folds、五 seeds、最多 259 fits 保持；单模型预训练最多 256 epochs/600 秒及真实数据早停保持。
  全部固定任务与诊断完成后退出，外层 supervisor 不再使用 `timeout`；手动 SIGTERM/SIGINT、错误退出和检查点继续有效，没有自动追加架构/seed 或重启失败任务。
  当前准备启动新 run：保留上次停止产物，在新 E 盘目录生成完整数据并发布/校验 manifest 后才进行 GPU 训练。
  **当前受计算主机离线阻碍，尚未启动新 run。** Mac Tailscale 为 Running，但 Windows/WSL peer 均 offline；最后在线分别为 14:30:15/14:30:46 CST，直接 SSH 超时，既有唤醒脚本报告 Windows offline。
  无时限代码/日志/手动停止验证已完成：Mac Torch 聚焦 31 项运行、29 通过、2 CUDA 跳过；Mac 全仓 2,717 项运行、2,686 通过、31 条件跳过；hygiene/diff/compileall 通过。
  已准备只含公开源代码的同步包和没有 `timeout` 的 supervisor，尚未能传入离线 WSL；WSL 的新版本 CUDA 检查与实际启动待恢复连接后继续，未将此前 69 项 WSL 通过当本次新验证。
  当时计划主机恢复后继续；最新停止决定已覆盖该自动继续安排。
  `research_only=true/orders_authorized=false/holdout_role=discovery`；无新增 P2/cloud/生产服务权限。

- **2026-10-03 owner 再授权：分析未达预期的 P3 结果，优化并推进下一轮大规模训练。**
  **随后 owner 要求“先别开始训练，计划完、代码搞完再开始，停止”，当时撤销启动并停止；其后新启动/取消时限授权见上方最新决定。**
  当前目标按已说明的默认值采用风险调整收益与回撤兼顾，沿用 WSL RTX4060、E 盘和 8 小时上限。
  已定位上一轮的换手保留规则过严：将实际换手不得超过父模型使用量当成风险边界；新协议改为硬预算 4.0 +1e-7，交易成本仍计入收益。
  旧 run/提案/源码快照保持不可变，旧入口显式使用 `parent_nonincrease_v1` 以保持原协议复现。
  新 [v2 合同](../config/etf-alpha-expanded-20261003.json) 提出七个固定神经配置 ×七 folds ×五 seeds，另 14 个 Ridge/块置换对照，最多 **259 次拟合**；原短暂运行/停止快照保留当时状态，现授权见上方。
  新表征保留 38 个当前横截面秩、八项固定单位水平和旧 38 个 trailing z-score；检验资产 ID、排序 loss、离线联合块增强的递进消融。
  每 fold **1,024 个 past-only 增强世界**，共 **7,168 个**，每世界 1,280 日热身 +1,260 日训练；预计约 **26.5 GiB**，24 个 CPU-only workers 完成并保存/校验后才进行 GPU 训练。
  增强来源仅该 fold 的 2015 年起、validation 起始前五个交易日之外的历史；20 日 next-open 标签跨拼接处无效。
  bootstrap 不增加独立市场观测，企业事件采用 TR 嵌入近似，仅用于预训练；原真实 next-open 标签与外层模拟账本保持同一冻结输入。
  所有候选先过正 RankIC/相对资产历史均值及匹配打乱标签增量、误差容差和硬约束，再按过去 validation 的固定 2× 成本风险效用选择；全部七 fold 冻结后比较所有固定 family 和 selected 的连续 outer 曲线。
  bootstrap 每 seed 预训练最多 256 epochs /600 秒，再用真实数据早停；全局预留十分钟 outer/收尾，没有到期后补 seed 或自动搜参。
  曾于 **2026-10-03 13:55 CST** 在 tmux `alpha_v2_20261003T055505Z` 启动；现按 owner 指令在 **13:59:55 CST** 全部退出，原八小时期限不再有运行任务。
  结果根 `/mnt/e/qount_data/qount/artifacts/etf_alpha_p3/expanded_20261003T055505Z`，增强数据在同名 `datasets/etf_alpha_p3/` 根；计算代码在 WSL ext4 `etf-alpha-expanded-20261003`。
  **停止核实：调度器、trainer、关联 CPU process group 均为空，GPU compute 应用为空；仅完成 14 个确定性 Ridge/负对照，CUDA 神经 fits=0，outer withheld**。
  部分分片/receipt 和日志留存，完整 bootstrap manifest 未发布，不能作合格训练数据。终止整个 process group 后运行记录原样报告 `BrokenProcessPool / failed / exit_code=1`；这是 owner 中断导致，另存同级 `owner-stop.json` 解释原因，不伪改原退出证据。
  WSL P3 69 项全部通过、0 跳过；Mac 全仓 2,716 项运行、2,686 通过、30 条件跳过；hygiene、diff check、compileall 通过。
  CPU 两个真实分片进程未导入 Torch；完整 fold 1,290,240×9×84 驻留输入的 CUDA 编译前向/loss/反向核对通过，峰值分配 4,084,366,336 bytes（约 3.80 GiB）。
  单线程同 2,562 日面板特征构建从 2.159 秒降至 1.163 秒（1.856×），资产 raw 特征完全一致，market/covariance 数值对照通过；这是该输入的工程实测，不是 Alpha 性能。
  新协议、分析与限制见 [P3 §19](etf-p3-research-plan-2026-10.md#19-结果复盘与大规模增强训练2026-10-03)；本段记原运行与停止证据，当前阶段以上方最新决定为准。
  `research_only=true/orders_authorized=false/holdout_role=discovery`；旧消费窗口仍为探索性研究，没有新增 Stage 2、paper/live、P2/3090 或服务权限。

- **2026-10-03 owner 授权：优化研究引擎，并在 WSL RTX4060 启动有界的 8 小时自动训练。**
  owner 明确要求检查训练速度、设计多维度自动脚本、梳理 WSL、使用 E 盘保存数据/产物，并添加记录和调试输出。
  默认范围已说明为当前 P3 Alpha：执行 §16 冻结的 E3/E4/E5 Stage 1 监督模型、七个时间切分、固定 seeds 和三档成本诊断；
  最多 224 次拟合、8 小时墙钟、一个 CUDA trainer。独立 [本轮运行合同](../config/etf-alpha-overnight-20261003.json)
  为 `training_start_authorized=true`；10 月 2 日提案的未审批标记作为当时快照保留。
  已于 **2026-10-03 02:35:09 CST** 启动，现 **提前完成并正常退出**；`training_status=complete / alpha_result_status=research_diagnostics`。
  8 小时为墙钟上限，训练/诊断实测 481.908 秒；214 次拟合全部完成、失败 0（189 次初筛/负对照 +25 次最终 seed 扩展，两 fold 选择确定性 Ridge，无 seed 扩展）。
  全部选择与扩展冻结后完成七个 outer test，未为耗时补搜或延长训练；02:44:01 CST 退出回执 `exit_code=0`。
  新 run 根 `/mnt/e/qount_data/qount/artifacts/etf_alpha_p3/overnight_20261002T183508Z`，tmux `alpha_20261002T183508Z`；
  七个 CPU fold 在 14.66 秒内准备/冻结完成；最终清单含 2,288 项文件，回读校验通过。
  2020–2026-10-01 连续 outer test 的 2× 成本 CAGR **9.55%**、现金超额 Sharpe **0.684**、MDD **16.36%**，
  剔除最好完整年 2025 后 CAGR **8.17%**；2026 为部分年度。40 日块超额收益区间跨零，RankIC 跨 fold 混合正负，不能据此声称 Alpha/正式门通过。
  五个 fold 的选择为四次 MTR MLP、一次静态市场 MLP，另两个 fold 为 Ridge；完整选择/预测/校准/成本/年份/seed 记录均保存。
  易读报告在同级新目录 `overnight_20261002T183508Z_review/REPORT.md`，原始结果保持不可变。
  验证：WSL 引擎 113 项、P3 55 项全部通过且无跳过；Mac 全仓 2,702 项运行，2,678 通过、24 项条件跳过。
  先在 CPU 准备并冻结全部 train/validation 数据，再在 GPU 复用驻留张量；所有结构选择和追加 seeds 冻结后才解封 outer test。
  使用独立 WSL Torch 2.13.0/CUDA 13.0、Python 3.12.3 环境 `/home/alyaloale/.cache/qount-compute/venvs/etf-alpha-20261003`，
  计算代码在 `/home/alyaloale/.cache/qount-compute/etf-alpha-overnight-20261003`；避免原 `.venv` 的 Mac symlink 与混合 Torch 包，不覆盖旧环境或恢复 P2/3090。
  E 盘挂载缺失、输入 hash/因果切分错误、CUDA/非有限梯度异常均有明确失败记录；到期保存 partial，不能将未完成模型作为合格结果。
  运行及验证见 [P3 主计划 §18](etf-p3-research-plan-2026-10.md#18-八小时自动监督训练2026-10-03)。
  `research_only=true/orders_authorized=false/holdout_role=discovery`；数据豁免仍不代替预测/组合/稳健性/新鲜确认门。

- **2026-10-02 owner 决定：降低 ETF P3 研究数据标准，现有数据判定通过；训练须先审批方案。**
  owner 明确要求以已有数据推进 Alpha，先敲定网络结构、参数与训练方案，明确允许后才开始训练。
  当前研究数据门采用 `research_snapshot_v1`，`D_gate=pass / qualification_basis=owner_accepted_limitations`；
  历史 PIT 修订证明、8 处发行商/Yahoo 差异、分配支付日会计和实测价差/券商费用资料转为已接受的研究限制，停止将其作为本轮监督训练的前置补采任务。
  保留数据 hash、因果特征、next-open 标签、日期整体切分及最长标签 purge/5 日 embargo 等必要检查。
  首轮选用冻结的 `m0_m1_20261002T112648Z` 面板/特征/标签，补采版作为来源审计参考；保持输入口径一致。
  原严格审计和其 `training_eligible=false` 标记作为历史证据保留，新研究资格单独登记；未伪造 `historical_asof_verified` 或修改原始事件。
  已形成 [Alpha Stage 1 审批方案](etf-p3-research-plan-2026-10.md#16-研究数据标准调整与-alpha-训练审批方案2026-10-02)
  和 [机器可读参数提案](../config/etf-alpha-stage1-proposal-20261002.json)：先共享 μ20 MLP，再做多任务/市场 GRU 消融。
  当次交付为 `training_start_authorized=false / training_status=awaiting_owner_plan_approval / alpha_result_status=not_run`；10 月 3 日后续授权见上方独立记录。
  `research_only=true/orders_authorized=false/holdout_role=discovery`；预测、组合、稳定性与新鲜确认门未被数据豁免替代。

- **2026-10-02 ETF P3 公开数据补采与分类完成（owner 要求“补齐数据，并合理储存标记分类”）。**
  最终数据版本 `public_sources_20261002T124605Z`，保存在外置盘 `datasets/etf_alpha_p3/`；WSL 直接获取、解析和回读，Mac 只保存代码、文档与轻量元数据。
  42 份官方来源全部取得；2009-01-02 至 2026-10-01 的十资产 44,640 行名义 OHLCV 从冻结输入标准化，
  另补发行商 935 条分配记录（830 条正现金、105 条零现金），除息/登记/支付日期完整，5 条支付日晚于行情截止日。
  独立交易所规则日历与 4,464 个行情交易日完全一致；监管费率保存为 21 段 SEC Section 31、9 段 FINRA TAF，
  其中早期 TAF 一段仍为连续性推断，不把监管费率当券商费用或 bid/ask 观测。
  原始来源、标准化表、审计、假设、元数据和代码证据分别分类；每条分配记录标记现金/零现金类型、来源对账结果与
  `historical_asof_verified=false/training_eligible=false`，真实采集时间保留，缓存导入不会伪造新观察时点。
  **补采交付时的严格 D 门为 `insufficient`，8 处发行商/Yahoo 差异保留；当前研究资格按上方 owner 决定处理，Alpha 训练未开始。**
  支付日期已补到数据层，但新 M1 的应收分配会计尚未接入；历史 PIT 修订、历史 bid/ask/冲击、券商传递与 SEC charge-date 映射仍缺资格证据。
  最终数据 63 项文件（14,397,621 bytes）hash 回读通过；原 P2 四组 625 项输入及原 M0/M1 清单全部仍匹配。
  新增 11 项数据测试通过；WSL P3 39 项通过、0 跳过；Mac 全仓运行 2,668 项，2,656 通过、12 项 Torch 条件跳过。
  `research_only=true/orders_authorized=false/holdout_role=discovery`；未改旧数据、历史结果、既有训练或生产运行。
  来源差异、版本分类、存储与复现见 [P3 主计划 §15](etf-p3-research-plan-2026-10.md#15-公开数据补采存储与资格分类2026-10-02)。

- **2026-10-02 ETF P3 M0/M1 已执行（owner 要求“执行m0m1”）。** M0 冻结登记完成，
  `baseline_id=p2-frozen-20261002/completion_status=partial`；原历史、来源、回收和数据清单共 625 项文件 hash
  在 M1 前后均匹配，4 个历史 checkpoint 与 38 个回收模型在 WSL CPU 严格加载、tensor 有限。
  保存 Git 与实际源码差异、模型配置、环境和历史暴露，区分五个 Stage B 的 ep60 权重与后续仅有日志的 episode；未恢复 3090。
  M1 工程实现与真实数据审计完成：2009-01-02 至 2026-10-01 的 4,464 个交易日、38 项资产特征、
  5/20/60 日 next-open 标签、2020–2026 七个 purged/embargo folds，以及 12 个固定基准版本 × 1×/2×/3× 成本。
  因果前缀、资产重排、协方差 PSD 和 2,700 个标签份额会计区间对账通过。
  **该冻结运行的数据 D 门为 `insufficient`，M1 资格状态为 `qualification_blocked`**：当时缺历史 as-of 修订来源、独立交易所日历、分配支付日、历史费率/价差审计；M2–M6 与 Alpha 训练未开始。后续数据补采见上方记录。
  完整产物在 `/mnt/e/qount_data/qount/artifacts/etf_alpha_p3/m0_m1_20261002T112648Z`，派生数据在同外置盘
  `datasets/etf_alpha_p3/m0_m1_20261002T112648Z`；Mac 仅保留代码、文档与轻量 JSON/验证日志。
  Mac 全仓 2,657 项测试通过（12 项 Torch 条件跳过），WSL 针对性 48 项全部通过；原 CN 生成器测试仅修正采样预算夹具。
  `research_only=true/orders_authorized=false/holdout_role=discovery`；未改 P2 模型/引擎/历史结果、WSL 既有训练、VPS 或服务权限。
  执行、验证与来源缺口见 [P3 主计划 §14](etf-p3-research-plan-2026-10.md#14-m0m1-执行记录2026-10-02)。

- **2026-10-02 ETF P3 结构重构推进计划（owner 要求，仅撰写文档）。** 将“P2 保留为冻结 baseline、先验证真实历史预测能力、再分离风险/组合/执行”的建议与原 v4.1 设计整合为
  [P3 研究及实施主计划](etf-p3-research-plan-2026-10.md)。原设计的 P3 一次历史验收与新 P3 Alpha 架构分别命名；原历史结果和 G5 失败保持原口径。
  初版交付时采用现有 checkpoint，不安排恢复 3090 或等待 100 episodes；当时新的 baseline manifest、P3 代码、训练、回测与前瞻验证均待实施。
  该次仅修改文档与导航，未变更模型、数据、运行进程、主机配置或服务；后续 M0/M1 执行见上方记录。`research_only=true/orders_authorized=false`，没有新增生产权限。

- **2026-10-02 P2 文档整理与归档（owner 明确授权）。** owner 要求“梳理整理归档文档，写清目前架构结果细节”。
  移动前完成引用审计并在 archive manifest 逐项登记 approved；18 份旧文档已归档，设计中的 2026-10-01 实施记录拆为历史快照。
  既有历史记录保留原路径，清除文档中的认证字面值；私有认证配置未改变。实际架构与研究结果集中在
  [P2 主文档](p2-project-summary-20261002.md)，设计协议保持原路径，撤回说明与旧状态经 [分类索引](archive/p2-history/README.md) 追溯。
  [归档审计](archive/p2-history/archive-audit-20261002.md) 记录批准、路径与 hash；本批次仅整理文档，未训练、回测或变更主机服务。

- **2026-10-02 云端 3090 P2 已按 owner 决定停训并完成回收（17:18–17:20 CST）。** owner 明确要求停止当前 3090 训练、回收保存重要结果和代码。
  已终止训练调度、5 个 Stage B trainer、全部关联子进程、自动续跑及 P2 监控；17:18 核查相关活跃进程为 0，GPU 利用率 0%、显存 1 MiB，17:20 GPU compute 进程仍为空。
  回收至外置盘 `/mnt/e/qount_data/qount/artifacts/etf_trader/cloud_recovery_20261002_1713`：原回收包 17,841,464 bytes，542 个文件 hash 回读全部匹配。
  重要产物包括当前实验 32 个 Stage A 最终模型、5 个 Stage B 最新 ep60 checkpoint、所有历史 checkpoint/日志、云端实际训练代码、相关测试和环境包版本；
  加载并校验 33 个最终模型（含 1 个早期 smoke 模型）及 5 个最新中间模型，共 38 个，tensor 全部有限。
  停训前 5 seeds 最后完成 episode index 为 64/62/65/62/63；可回收的最新持久化模型均为 ep60，未将后续仅有日志的 episode 冒充已保存模型。
  17:20 停止后源文件与冻结回收包没有差异，停止回执、代码和进程证据均已保存；未复制凭据、未改 WSL 训练或 VPS 生产状态。
  云实例仍开机，本批次未执行实例关机或删除。`research_only=true/orders_authorized=false`；Stage B 未完成，不能作为最终选模或正式 P3 通过。
  细节见 [P2 研究主文档 · 云端停训与回收](p2-project-summary-20261002.md#云端停训与回收)。

- **2026-10-02 P2 双端训练只读核实与 WSL 历史实测（16:39 CST）。** owner 授权查看进度、编写回测、在 WSL 实测并修正错误文档。
  WSL RTX4060 的 `experiments/p2_us_full_wsl_20261002_033008` Stage A 为 **27/32 次 seed 运行完成**；3 次最后 episode 22/30（从 0 编号），
  另 2 次没有完成产物，其中 1 次有 CUDA 异常、1 次日志自 03:30 无 episode。云端 RTX3090 的
  `/root/autodl-tmp/experiments/p2_us_optimized_20261002_040315` Stage A **32/32 完成**；Stage B 当前配置 5 seeds
  最后 episode 50–52/100，无最终模型，近期每 episode 169–184 秒，旧“17:00 完成”估算撤回。
  4 个提前冻结 checkpoint（WSL 两个 30-episode 模型、云端两个 ep40 中途模型）已在 WSL CPU 完成 2015-01-02 至 2026-10-01
  的真实 9-ETF 历史行情测试。2× 成本下 CAGR 6.38%–6.70%、回撤 13.86%–14.49%；固定评分器 5.86%/13.87%，
  真正 SPY/IEF 60/40 8.75%/21.18%。全窗口探索性 G1–G4 满足，但剔除最好完整年后 **4/4 均未满足 G5**。
  本轮为弱保留集探索性评估，P2 最终选模/两族验收和 P0 来源审计未完成，不能声称正式 P3 通过；未按历史结果调参。
  原产物位于外置盘 `/mnt/e/qount_data/qount/artifacts/etf_trader/historical_20261002_v1`，39 项 hash 已回读验证；
  WSL 相关 20 项测试通过。未终止/重启训练、未改生产服务；`research_only=true/orders_authorized=false`。
  证据、测试口径、数据限制及复现方式见 [P2 研究主文档](p2-project-summary-20261002.md)，架构与正式门槛见
  [ETF 交易员设计](etf-imitation-policy-design-2026-09.md)。本段不存储认证凭据。

- **2026-09-30 CTA-R 研究前瞻账本（D1，owner 授权，已部署）。** 新增 `qount-research-cta-r-forward.{service,timer}`，
  每日 18:45 CST 从公共腾讯前复权日线刷新自有 seed（VPS 上 Eastmoney 不通），追加哈希链前瞻账本
  `/var/lib/qount/research/cta-r-forward/forward-ledger.jsonl`，并重建 `/var/www/qount/data/cta_r_paper.json`（年初起回放 + forward 摘要）。
  规则与侧车相同，未改参数（2 bps 基础 + 10 bps 压力）。创世条目为 2026-09-29（bar 2848），权重与原侧车一致；
  合同 hash `fa988d78...095a7b`。没有改动 CTA-R collector 及其 seed（hash 仍为 `d060f1f6...`）、ops-health-v3 或 Dual-Engine。
  首跑 `valid`。部署目录 `/var/lib/qount/deployments/cta-r-forward-v1-20260930T065004Z/`（含 ROLLBACK.md）。
  合同与评估规则见 [cta-r-forward-ledger-2026-09.md](cta-r-forward-ledger-2026-09.md)。

- **2026-09-29 统一 forward collector 迁至 `ops-health-v3`（owner 授权，已验收）。** 原 `ops-health-v2` 自
  `2026-09-27T19:30:27+08:00` 起 `forward_contract_mismatch`（9-27 CTA-R 部署改了共享 `forward_collector.py`，
  而合同冻结其源 hash），链停在 9-27，保持只读不改。新合同根 `/var/lib/qount/research/forward/ops-health-v3`
  （contract hash `a6981a01…`），collector 与 dashboard publisher 的 `--state-root/--forward-root` 已同步。
  首条记录为 09:16Z 手动运行（未加载 env，Tiingo insufficient，属预期）；09:19Z systemd 周期
  `l1_passive_tiingo=valid`、`api_key_used=true`；publisher 首跑 `runtime:forward` 与全部来源检查 pass，
  失败单元为 0。`l1_passive.data_conclusion` 仍为 insufficient，需累积样本。9-27 至 9-29 的采集缺口不可补。
  回退见 `/var/lib/qount/deployments/ops-health-v3-*/ROLLBACK.md`。发布来源证明 `ops_release_provenance_block`
  为既有问题，本批次文件会扩大差异，仍需 owner 统一重新认证。

- **2026-09-29 C60 合同 v2 research-paper 侧车已部署。** owner 授权按月度候选规则（Trial 150）开 v2，作为与冻结
  v1 并行的比较线（`replaces_frozen_v1=false`、`research_only=true`、`orders_authorized=false`），不改 Dual-Engine
  合同、账户或 timer。`qount-research-c60-v2-paper.timer` 每日 08:20 CST 生成 `/var/www/qount/data/c60_v2_paper.json`，
  前瞻哈希链账本从 2026-09-30 开始。首跑 `valid`；样本内 2026 YTD v2 -8.15%/78 次调仓，同引擎 v1 -6.02%/108 次，
  故 v2 优势仅见于 2020–2026 全样本（成本研究），今年未体现。回退见部署目录 `ROLLBACK.md`。

- **2026-09-29 Tiingo 与 vol crisis。** L1 Tiingo key 已由 owner 授权写入 `/etc/qount/research-forward-collector.env`
  （0600，未回显值）；paper 的 SPY reference 已正常（185 bars 至 9-28），9-23 的 `benchmarks=[]` 已过时。
  `crypto_vol_crisis_state_v1` family 已关闭，剩余 2 trial 作废；全局 trial 计数 150。

- **2026-09-29 CTA-R 数据与前端对齐状态核实。** CTA-R 独立 collector timer 保持
  `enabled/active`，按北京时间每日 18:30 运行，最多随机延迟 5 分钟；最近一次服务执行成功，
  但 8 条 ETF 序列实际最新日期仍为 `2026-07-22`，sidecar 状态继续为 `insufficient/series_stale`。
  本批次不伪造新行情、不修改 timer，也不调用冻结 CTA-R 实现；前端明确显示原始回放末值、共同日期轴归一后的
  比较价值、实际数据截止日和采集计划。四个 Dual-Engine 主账户与 CTA-R 仍保持独立会计和 research-only 边界。

- **2026-09-29 CTA-R 公共数据已补采。** 通过公共 Eastmoney 日线接口重建 8 个 ETF 的前复权 seed，
  每条序列最新交易日为 `2026-09-29`，seed hash=`d060f1f6...151e3a`；远端隔离 collector 已验收
  `research_lines:valid`，记录 hash=`99bbabba...ae116`。Dashboard CTA-R sidecar 已重建并发布，
  `status=valid`、`data_cutoff=2026-09-29`、160 个回放点；原 seed 保存在远端隔离备份中。

- **2026-09-28 Dashboard 静态前端布局收敛并发布。** `#/paper` 现明确标出四个 Dual-Engine 主账户
  （G20/C60/GC5/D15）与第五个 CTA-R research-only 侧车；主快照缺失时不再用“曲线准备中”掩盖状态，
  而是分别显示主快照不可用和 CTA-R 侧车状态。此次只替换 `/var/www/qount/index.html`、`app.js`，未修改
  `data/v1`、publisher、timer 或任何交易权限；远端静态文件 hash 已与本地一致，回退副本保存在
  `/var/www/qount/.frontend-backups/qount-frontend-20260928-215327/`。

- **2026-09-27 owner 决策：恢复 CTA-R 公共 ETF 数据采集准备。** 授权范围仅为新建隔离的
  AkShare A 股 ETF 日线 seed 与 research-only forward collector，使用新合同根；不得修改
  `ops-health-v2`，不得恢复 CTA-R 策略/回放/paper，不产生 StrategyIntent、权重、订单或 live 权限。
  采集与部署须通过本地合同/测试、seed 来源和新状态根校验后分别验收。CTA-R AkShare 数据不使用 API key；
  L1 Tiingo key 是独立来源。本次只读检查发现 VPS research-forward-collector env 未配置 Tiingo key，
  因此未能判断该 key 是否过期；未读取或复制任何凭据。

- **2026-09-27 CTA-R AkShare 隔离采集已部署验收。** 新合同根为
  `/var/lib/qount/research/forward/cta-r-akshare-v1`，独立 timer 为
  `qount-research-cta-r-collector.timer=enabled/active`；旧 `ops-health-v2` 未修改。
  首次 service 返回 `Result=success`，记录 hash=`9b0fe200...cf7cb89`，8 条 ETF 序列均截至
  `2026-07-22`，来源状态为 `insufficient/series_stale`。seed 由本地历史 archive 转换而来，
  新 seed hash=`3d5f8a47...cfc2df0`；这证明格式、合同和只读链路可运行，不证明当前数据新鲜。
  AkShare 公共接口在 Mac 代理和无代理请求均被远端断开，未能在线刷新；没有发现 CTA-R key 过期问题，
  因为该路径不使用 key。研究守卫保持 `research_only=true/orders_authorized=false/pnl_evaluated=false`，
  未恢复策略、paper、订单或 live 权限。待有可用公共网络后，只需更新 seed 并等待该独立 timer 验收。

- **2026-09-27 CTA-R research-paper 侧车已恢复并接入 paper 前端展示。** 新实现位于
  `src/qount/research/cta_r_paper.py`，独立读取 8 只 ETF 的公开 seed，按 63/126/252 日
  TSMOM、逆波动率、21 个交易日调仓和 2 bps 模拟成本回放；它不导入冻结 `legacy/line_a`，不写
  StrategyIntent，不改变 Dual-Engine 的 G20/C60/GC5/D15 合同。Dashboard paper 页新增独立
  `CTA-R 研究模拟` 区块，显示状态、数据截止、净值曲线、权重、调仓与成本，并固定展示
  `research_only=true/orders_authorized=false/pnl_evaluated=false`。当前 sidecar 源 hash 对应的
  8 条序列共同截止 `2026-07-22`，截至本日为 `insufficient/series_stale`；曲线只作为历史研究证据，
  不代表当前策略结果，也没有 CTA-R 数据源 key 可过期或被读取。

- **2026-09-23 长期产出质量复核。** 12:39 CST 主机无失败单元、内存 available 约 771 MiB，
  swap 0、磁盘使用率 46%；当日日报已自动生成，但 `status=incomplete`、六角色全部 blocked。
  保留的 8 月 18 日至 9 月 23 日 35 份日报全部 incomplete，21 份含 LLM 请求错误；
  其中 15 份为 BadRequestError、6 份为 APITimeoutError。9 月 4 日与 12 日没有对应日期工件，
  原因未从当前留存日志证实。统一采集 37 个日期的末条记录抽样中，CTA-R 归档缺失与 L1 凭据
  不可用均持续存在；这不是刚重启产生的问题。模拟盘 272 行会计审计全量通过，但 SPY 基准为空。
  收益与成本分析见 [策略总集](qount_strategy_master_index.md#2026-09-23-长期运行结果复盘)，
  证据范围与改进优先级见 [更新记录](update-log.md#长期运行经验复盘只读)。本次未修改运行状态或参数。

- **2026-09-24 运维缺口修复批次（已上线并完成自然周期验收）。** owner 明确日报因 API
  额度耗尽暂不处理；本批次不重试日报、不发送通知、不改变交易权限。新增只读运行证据探针，
  在 Dashboard 发布时检查 forward head/记录新鲜度、来源状态、liquidation 心跳和研究守卫；
  磁盘预警提前到采集器 8 GiB 停止线（10 GiB warning），并拒绝符号链接、超大/非法 JSON 和路径穿越。
  unified collector 的 liquidation 状态改为健康摘要，不再每 15 分钟重复写入 recent event IDs；旧链保留，
  新合同根为 `ops-health-v2`。冻结 CTA-R 不再列入新的 active source graph；L1 缺少凭据仍明确为
  insufficient，不复制或生成凭据。Dual-Engine 增加独立的公共 SPY/TLT reference artifact，
  仅用于展示基准，不改写 NAV、audit 或回放结果，采集失败时保留 paper 核心结果并显示基准不可用。
  本地相关测试 53 项通过，compileall、repository hygiene、systemd 静态引用检查通过。
  SSH 于 16:00 CST 恢复；VPS 只读状态为 uptime 1 天 4 小时 47 分、failed units 0、磁盘 47%/21 GiB
  可用、内存 available 685 MiB、swap 0，现有 collector/publisher/liquidation 服务保持 active。
  新文件先放入 `/var/lib/qount/deployments/ops-health-v2-20260924/staged/` 做隔离备份和编译，随后完成原子安装、
  `daemon-reload`、systemd 静态校验和真实模块导入。17:15 collector 自然周期 `Result=success`，新
  `ops-health-v2` head 新鲜且 hash/研究守卫通过；17:18 publisher 自然周期 `Result=success`，publication
  与 restore drill 均通过。部署证据、校验 hash 和回滚说明在同一 deployment 目录。source 缺凭据仍只报
  `insufficient/warn`；这证明上线和当前窗口健康，不代表长期连续性或研究输入完整性已经证明。

- **2026-09-23 再次重启后的修复验收。** owner 要求修复并详细检查现有故障，随后于
  `2026-09-23 11:12:25 CST` 再次启动实例；SSH 恢复，无失败单元，复核内存 available 约 800 MiB、
  swap 使用 0。既有 public-data/paper/Dashboard 服务恢复，交易 timer 仍 disabled/inactive，root cron 0。
  - SSH 上次启动日志明确记录 `MaxStartups` throttling，曾持续 18 分 12 秒并丢弃 33 个连接；
    有界内核日志未发现 OOM 记录，不能据此排除未记录的其他故障。新增
    `/etc/ssh/sshd_config.d/00-qount-connection-limits.conf`，设置 `LoginGraceTime=30`、
    `PerSourceMaxStartups=3`，保留原登录认证方式和全局连接上限。`sshd -t`、热加载及新连接验证通过；
    这是对已观测连接饱和的缓解，不构成长期不再超时的保证。
  - 实际基础版本为 `0.2.29 / 30d20b4ca053757d15c39be0dc4ee21e42839521`。旧基础清单 1,010 项
    逐项匹配该 Git；8 个变化文件逐项匹配 8 月 18 日部署验收；217 个额外历史文件全部匹配
    当前 Git 内容或旧 `66034b0` Git 历史。本次保留文件和兼容路径，不移动、删除或调用旧入口。
    在完整来源核实后，部署 provenance 固定错误码诊断及相关测试，并移除统一 collector 的
    `--print-json` 日志参数，保留原 append-only 数据链、来源合同和 timer 日程。
    新清单覆盖 1,227 个文件，provenance hash=`e6cdfe5f...ca55aa2f`；基础 commit 不代表叠加修复本身。
    来源映射、变更前备份和验证记录在 `/var/lib/qount/deployments/post-reboot-repair-20260923/`。
  - Dashboard `2026-09-23T03:36:05.874909Z` 自然发布中，operations 已 healthy，
    `release:provenance=pass/release_provenance_verified`；12 个模型和 publication 完整校验通过。
    本地与远端相关测试各 29 项通过。已有 arm 创建于 7 月 23 日、所属版本 0.2.15，
    `end_date_exclusive=2026-08-18`，已过期；未重新 arm，`live_orders_allowed=false`。
  - Liquidation 心跳新鲜、连接/快照错误 0，两个 `collector_restart` gap 分别为
    `3,022,360 ms`（9 月 22 日，约 50 分 22 秒）与 `2,021,236 ms`（9 月 23 日，约 33 分 41 秒）。
    gap 由前次记录至新 session 启动计算，不等同于主机准确停机时长；未补造数据或评估策略结果。
    `2027-02-14` 仅为原窗口理论下限，实际评估前必须审计缺口与覆盖率，不能宣称连续完整 180 天。
  - Paper 快照仍 fresh，数据截至 `2026-09-22T20:00:00Z`；统一采集 head/hash 校验通过。
    CTA-R 缺失归档（冻结线路）和 L1 passive 缺少配置凭据仍为 insufficient；未复制或新增凭据，
    未恢复冻结线路。FOMC 两个限时 timer 仍 elapsed/无 NEXT，保留现状；本次未运行日报或发送通知。

- **2026-09-23 VPS 重启后只读复核（北京时间 10:38–10:42 的有效快照）。** 系统于
  `2026-09-22 20:58 CST` 启动，检查时 `systemctl is-system-running=running`、失败单元为 0；
  根盘使用率 47%、可用约 21 GiB，内存 available 720 MiB，swap 使用 0。
  Dashboard publisher、账户只读 observer、两条 Dual-Engine paper timer、统一 research collector 和
  notification retry 均为 enabled/active；已运行的对应 oneshot 最近 `Result=success/ExecMainStatus=0`。
  日报和 Phase B timer 已恢复，但本次开机后尚未到执行时间，不能用默认 `Result=success` 宣称执行成功。
  最新日报为 9 月 22 日 12:35 CST，下一次日报计划为 9 月 23 日 12:31 CST 左右。
  - Liquidation collector 自本次启动持续 active、`NRestarts=0`；检查时本 session 收到 1,327 条
    forceOrder，连接错误和快照错误均为 0，心跳 age 约 27 秒（阈值 180 秒）。有 1 条 gap 记录，
    本次未核实其时长，不能据此宣称独立窗口连续无缺口；研究守卫均保持 false。
  - Paper daily 于 9 月 23 日 06:30 CST 成功，G20-open 于 9 月 22 日 23:00 CST 成功；
    四账户快照数据截至 `2026-09-22T20:00:00Z`，snapshot hash=`8ca130c1...b8e28a`。
    `read_dashboard_v1` 对 12 个读模型和 publication 完整回读校验通过，paper freshness 为 fresh，
    `orders_authorized/private_api_used/exchange_mutation_attempted=false`。
  - 统一采集最近有效核查周期为 `2026-09-23T02:30:04.358082Z`，服务成功但来源汇总 insufficient：
    CTA-R 的 `/root/qount/state/cta_r/etf_source/etf_data.zip` 缺失；L1 passive 的
    `QOUNT_TIINGO_API_KEY` 不可用。Binance REST/archive、FOMC 日历与 liquidation 状态为 valid；
    所有策略收益结论仍 insufficient。CTA-R 已冻结，缺文件不构成恢复它的授权。
  - Dashboard 的 clock/disk/service/backup 为 healthy；operations 因
    `release_provenance_unavailable` 阻断，execution/observation 汇总 unavailable。
    这证明发布来源校验未通过，尚不能区分清单缺失与源码不匹配。
    探针同时报告 `/root/qount/state/mini_trend/arm/manual-final-arm.json` 存在；本次未读取授权内容、
    未确认其有效性。MiniTrend live/forward timer 均 disabled/inactive，FOMC live unit/env 不存在，
    root crontab 有效项为 0，Dashboard `trading_authority=blocked/live_orders_allowed=false`。
  - VPS 仍保留 enabled/active/elapsed 的 FOMC shadow 与 evidence-backup 限时 timer，均无 NEXT，
    最近触发在 7 月 30 日；旧 Alpha collector 为 disabled，MiniTrend forward timer 为 disabled。
    仓库活动模板已移除并不意味着 VPS unit 文件已删除。本次未改变任何服务、调度或授权。
  - 后续追加核查的 SSH 出现 `Connection timed out during banner exchange`；发布来源失败的
    具体原因、gap 时长及之后的主机状态未获核实。恢复连接后优先做有界只读检查。

VPS基础生产版本：`0.2.29`，基础 commit=`30d20b4ca053757d15c39be0dc4ee21e42839521`（9 月 23 日实机核实，含上方已记录修复）；Dual-Engine 当前
program=`1.1.0`、YTD curve overlay content hash=`05258e5e...a8b1`、可视化 overlay package hash=`42b56a1c...82cc`；逐文件清单与验收记录保存在
`/var/lib/qount/deployments/dual-engine-ytd-curve-v1-20260802/` 和
`/var/lib/qount/deployments/dual-engine-paper-visual-v1-20260803/`。基础 release 的 commit、provenance 和 verification 仍保存在
`/root/qount/.qount-release-provenance.json`及`.qount-release-verification.json`；FOMC watcher、有限事件timer、
Dashboard只读账户视图、有界微信retry timer和公开数据研究timer按既有状态运行；所有交易执行权限均关闭。

- **2026-08-18 liquidation WebSocket 与统一前向健康检查已修复部署。** 只读核查发现 2026-07-28
  至本次修复前的 collector 虽累计写入 `18,042` 组五分钟 REST 上下文快照，但旧 Binance
  `/stream?streams=...` 路径从未收到 `forceOrder` 消息；该段方向性事件证据不完整，不能计入 180 天独立窗口。
  collector 现使用 Binance 当前 `/market/stream?streams=...` 路径，并在同一公开连接中订阅只用于传输
  freshness 的 `BTCUSDT markPrice@1s` 心跳；心跳不写入研究事件、不生成信号。VPS 独立 smoke 在 8 秒内收到
  7 条心跳、3 条真实 `forceOrder` 和三标的完整 REST 快照，随后
  `qount-liquidation-cascade-collector.service` 于 `2026-08-18T06:31:56Z` 成功重启，保持
  `enabled/active`、`NRestarts=0`、合同 hash=`6bbd2f44...ec38ec7`。统一 collector 以 180 秒阈值校验
  status 与流心跳；因插件源码合同变更，新 append-only 链写入
  `/var/lib/qount/research/forward/stream-health-v1`，旧 `/var/lib/qount/research/forward` 链只读保留。
  新方向流独立窗口从本次重启开始，最早不早于 `2027-02-14T06:31:56Z` 才可评估；此前公布的
  `2027-01-24` 日期已失效。部署证据和回滚源保存在
  `/var/lib/qount/deployments/liquidation-stream-health-v1-20260818/`。全部守卫仍固定
  `orders_authorized=false/private_api_used=false/pnl_evaluated=false/read_results_before_window=false`。

- **2026-08-10 Dual-Engine 模拟收益与大盘对比视图已部署。** Dashboard 的四条策略线固定对应
  G20/C60/GC5/D15，可切换 YTD/180D/90D/30D、收益率/美元金额和单条显隐；缩放只由顶部独立滑条控制，左右日期窗口只由
  图下固定窗口滑条控制，不再用拖动曲线或滚轮平移。总图使用本地 Apache ECharts，提供十字准星和轴触发悬停提示。每个净值点都带经合同校验的逐日收益率和逐日美元金额，悬停任一日期会并列显示
  四条线的该日净值与收益。各账户的当前模拟权益、日收益、月收益、YTD 收益率与对应美元损益均由服务端 `Executable NAV`
  历史计算并在快照合同中校验，页面不自行重算或伪造收益。大盘只采用 Tiingo 公开的 SPY 未复权日收盘价，只有其历史完整覆盖模拟曲线起点时才发布；
  覆盖不足会明确显示等待状态，不用替代数据补线。该次发布只更新无订单模拟快照合同、Dashboard 资源及只读发布器，未触发
  paper 回放、未改变 timer、账户、授权、私有接口或订单权限；所有合同仍固定
  `orders_authorized=false/private_api_used=false/exchange_mutation_attempted=false`。

- **2026-08-03 Dual-Engine Dashboard 调仓与 K 线可视化已部署。** 在原有四账户 YTD 纸面曲线基础上，
  Dashboard 现在按真实时间比例绘制 NAV 横轴，显示执行层模拟调仓标记、组合/标的可选择的公开日线 K 线，以及完整
  模拟调仓表（时间、买卖方向、数量、参考价、名义金额和模拟成本）。K 线默认选择有调仓的非现金标的、展示近 90 个
  交易日，并可切换 45 日或 YTD 全程；证券价格轴为两位小数。行情展示固定使用原始未复权 OHLC，以保持与模拟成交
  参考价一致；BIL 的月初除息跳空会在页面明确说明，不应误读为数据断裂。新发布快照为 `219` 个输入周期和审计行，
  截至 `2026-08-02T00:00:00Z`；G20/C60/GC5/D15 各 219 点，含 18 个标的、3,290 根日线和总计 191 个模拟调仓事件，
  snapshot hash=`de633323...fe716`。展示数据仅来自 Tiingo/Binance 公开行情；调仓为 no-order 模拟执行记录，不是订单、成交
  或实盘收益。发布使用 Dashboard 的原子 `data/v1` 指针，线上静态文件已与发布源逐字比对，`qount-dashboard-publisher`、
  paper daily 和 G20-open timer 均为 `enabled/active`。部署前状态保存在
  `/var/lib/qount/paper/dual-engine-previsual-20260802T160700Z`；远端相关测试 38 项、Python compile、前端语法、
  JSON schema、Caddy 配置和发布快照哈希比对均通过。所有合同仍固定
  `orders_authorized=false/private_api_used=false/exchange_mutation_attempted=false`。

- **Dual-Engine 2026 YTD 无订单模拟曲线（初始部署 2026-08-02）。** 当前冻结 G20/C60/GC5/D15 四个
  `10,000 USD_EQ` 独立账户，使用 Tiingo/Binance 公共行情、Signal/Executable 双层净值、25 bps 基础与
  50 bps 压力成本、月内袖套隔离和 append-only 哈希审计；Dashboard 提供独立 `paper.json` / `#/paper`。
  owner 明确授权的 YTD replay 从 `2026-01-01` 起取完整公开历史，第一个模拟点为 `2026-01-02T15:00:30Z`；
  当前点数、数据截至时间和快照 hash 以本页 2026-08-03 发布事实为准。该曲线固定标记
  `simulated_not_realized`，不是账户实盘收益。VPS 上 daily 与 G20-open timer 均为 `enabled/active`；日常探针在
  北京时间 `06:30`，G20 显式日期探针在工作日北京时间 `23:00`。本机私有 `.env` 的 `QOUNT_TIINGO_API_KEY`
  已不回显地映射到 VPS `/etc/qount/dual-engine-paper.env` 的 `TIINGO_API_TOKEN`；文件为 `0600 root:root`。
  Tiingo EOD/IEX 与 Binance Spot 公共接口均已验证。权威口径见
  [qount_strategy_master_index.md](qount_strategy_master_index.md)。

- **2026-07-30 owner 已取消 `SmallAccount-FOMC-RightSide-v0.2` 的部署。** VPS 上不存在
  `qount-fomc-live.service`、`qount-fomc-live.timer` 或 `/root/.config/qount/fomc-live.env`，没有 live 进程、arm、授权消费记录或订单。
  FOMC 公开日历和行情研究由统一 research forward collector 采集；不能恢复或转化为交易执行权限。

- **2026-07-28 `liquidation_cascade_forward_v1`公共前向采集已在VPS启动。**
  `qount-liquidation-cascade-collector.service=enabled/active`、`NRestarts=0`；它持续订阅
  BTCUSDT/ETHUSDT/BNBUSDT 的公开 Binance USD-M `forceOrder`，并每5分钟记录当前 OI、20档深度及 mark/index
  上下文，状态根为`/var/lib/qount/research/liquidation-cascade-v1`（root `0700`、原始段和元数据`0600`）。
  首次连接和三标的完整快照已验证，冻结合同 hash=`6bbd2f44...ec38ec7`。方向性被迫流只来自 `forceOrder` 的订单边；
  premium/funding 字段仅为同刻原始上下文，绝不把本线改称或降级为 `funding_crowding_meta_v1`。本服务不读取凭据、
  私有账户或订单路径，固定`orders_authorized=false/pnl_evaluated=false/read_results_before_window=false`。本段原定
  180 天窗口起点已被 2026-08-18 的流路径核查否定；当前有效起点和最早评估日期以上方 2026-08-18 事实为准，
  不能作为均值回复或抄底信号。
  旧 Alpha collector 已从活动 systemd 部署模板移除，历史 session 只保留在 archive，不能恢复、拼接或复用。

- **2026-07-30 L1-S2 21-ETF personal-carrier 已弃用，不再属于当前研究路线。** 它声明的 21 ETF、
  `{13,26,39,52}` 周回看与所引用提交中的 13 ETF、`{13,26,52}` 默认配置不一致；此前外部盘上的缓存和
  回放结论不作为当前可验证事实。本线不再拉取 Tiingo 数据、回放、登记策略、生成目标或新增自动化流程。
需要重新研究时，从新的个人研究问题和最小可用脚本开始，不复用这条历史流程。
代码和测试已移至 [`src/qount/legacy/l1/`](../src/qount/legacy/l1/)，专属研究文档移至
[`docs/archive/legacy/l1-personal-carrier/`](archive/legacy/l1-personal-carrier/)。

- **2026-07-30 Sleeve 1 被动长期配置已独立预登记并接入 research registry。** `l1_passive_sixty_forty@0.1.0`
  固定为 `SPY 60% / TLT 40% / USD 现金目标 0%`，年度首个完整 NYSE 常规交易日为唯一再平衡锚点；现金流仅留至下一锚点，
  无 drift-band 或择时现金例外。合同 hash=`e87eeb77...b616d3`，registry hash=`4e53e10d...2ac03a`；两者均为
  `0600` 不可覆盖工件。它只处于 `research`，不产生 StrategyIntent、scheduler、paper/live、broker 或订单权限。

- **2026-07-31 已确认统一 research forward collector 在 VPS 运行。** 它以 15 分钟 systemd timer 统一记录 Binance UM
  REST/历史归档、FOMC 日历、liquidation 状态、CTA-R ETF archive 和 L1 passive 的 Tiingo SPY/TLT 来源，使用
  可扩展 source graph、固定 contract、append-only JSONL 与 SHA-256 链；每条研究线分开写 mechanism/data/strategy
  三层结论，默认 `orders_authorized=false/pnl_evaluated=false`。代码和配置见
  [`docs/research-forward-collector.md`](research-forward-collector.md)。VPS 上
  `qount-research-forward-collector.timer=enabled/active`，最近一次 service 执行 `Result=success`、退出码 `0`；
  当前状态根为 `/var/lib/qount/research/forward/stream-health-v1`；旧 `/var/lib/qount/research/forward` 合同链只读保留。
  最近记录的 `research_lines` 总状态仍可能为 `insufficient`，这表示某条
  source 或研究证据不足，不表示采集器失败。旧 MiniTrend forward 与 FOMC shadow timer 已从活动部署模板删除；liquidation
  WebSocket 仍作为独立原始事件源运行，统一 collector 只读取其状态，不重复写入事件流。

2026-07-27 及更早的生产、研究和架构记录已逐行迁入
[archive/current-archive-pre-fomc-2026-07-29.md](archive/current-archive-pre-fomc-2026-07-29.md)。

这份文档是当前事实入口，只保留结论、能力边界和下一步。接手命令看
[quick-handoff.md](quick-handoff.md)，项目规则和文档分类看
[project-rules.md](project-rules.md)，发现/验证边界看
[holdout.md](holdout.md)，长证据链看 [update-log.md](update-log.md)。当前系统工程主设计看
[system-architecture-design.md](system-architecture-design.md)，100 USDT Base与未来组合合同看
[crypto-portfolio-system-plan.md](crypto-portfolio-system-plan.md)，Alpha Agents研究层看
[alpha-agent-plan.md](alpha-agent-plan.md)，生产控制面演进看
[trading-system-evolution-plan.md](trading-system-evolution-plan.md)，研究与文献情报路线看
[research-advancement-roadmap.md](research-advancement-roadmap.md)，200 USDT个人事件策略看
[personal-200u-event-strategy.md](personal-200u-event-strategy.md)。旧研究线、历史计划和legacy运行手册统一从
[archive/README.md](archive/README.md)进入，不再混入当前生产导航。
