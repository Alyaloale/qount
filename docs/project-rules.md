# qount 项目规则与文档分类

更新时间：2026-07-18

这份文档定义项目级规则、文档分类、研究线隔离和代码整理纪律。它不替代
[current.md](current.md)：`current.md` 仍是当前事实、生产状态和下一步的入口。

## 1. 权威顺序

当文档互相冲突时，按下面顺序判定：

1. [current.md](current.md)：当前事实、运行状态、owner 决策、硬边界。
2. 本文件：项目规则、文档分类、研究线隔离、代码治理。
3. [quick-handoff.md](quick-handoff.md)：可执行命令、跨主机操作、运维坑。
4. 各研究线主文档：只约束本线，不能越权改变其他线或生产状态。
5. [update-log.md](update-log.md)：证据链、artifact、执行记录。
6. 历史计划文档：仅作为背景，除非被 `current.md` 或本文件重新引用。

旧文档里凡是写“WSL 是生产真相”的内容，自 2026-07-07 起只按历史语境读取。当前
live / paper forward / dashboard 的生产真相是 VPS `/root/qount`。

## 2. 主机职责

| 主机 | 职责 | 禁止 |
| --- | --- | --- |
| Mac `/Users/alyaloale/Code/qount` | 研究设计、代码主仓、git、文档、轻量验证、任务编排 | 不跑实盘，不长期保存全量数据或模型批次 |
| Windows外置盘 `E:\qount_data` | 大数据、最终artifact、环境锁和备份的存储真相 | 不存`.env`/密钥，不直接运行SQLite/venv |
| WSL `/home/alyaloale/Code/qount` | 7945HX/RTX 4060大型CPU/GPU计算、权威复跑、临时scratch | 不作为实盘真相，不把完成数据长期留ext4 |
| VPS `qount-vps:/root/qount` | 当前唯一 live / paper forward / dashboard 生产真相 | 真实host只存仓库外inventory；不保存研究大数据，不用手工改动绕过仓库规则 |

生产判断优先读VPS state、cron和log。WSL是计算节点但不是生产判断依据；
`scripts/sync-to-wsl.sh`只在计算接口变化时显式使用，`scripts/run-wsl-tests.sh`验证WSL计算环境，不应成为每次
研究的无条件同步步骤。数据路径和清理门见[storage-topology.md](storage-topology.md)。

## 3. 文档分类

| 分类 | 文件 | 用途 | 更新触发 |
| --- | --- | --- | --- |
| 当前事实 / 规则 | `current.md`, `project-rules.md` | 当前结论、硬边界、项目规范 | 改变生产真相、研究状态、全局规则 |
| 存储 / 计算拓扑 | `storage-topology.md` | 外置盘、WSL scratch、迁移校验、节点分工 | 数据位置、计算节点或迁移规则变化 |
| 接手 / 运维 | `quick-handoff.md`, `README.md` | 新会话启动、命令入口、主机职责 | 命令、主机、验证入口变化 |
| 验证边界 | `holdout.md` | discovery / validation / promotion gate | 样本池或晋级规则变化 |
| 记录链 | `update-log.md` | 每批有意义执行的结果、artifact、验证 | 代码、运行、规则或跨线结论变化 |
| 线 A legacy | `profit-*.md`, `optimization-plan.md`, `cta-r-value-gate-plan.md` | 旧 `qount.main` / ETH-only / CTA-R 研究 | 仅追溯或 owner 授权重启 |
| 线 B GRID | `grid-binance-*.md` | 网格实验线 | 本线 changelog；不污染 current，除非影响全局 |
| 线 C RV | `rv-c-plan.md` | 相对价值 carry 线 | 本线 live/carry 事实变化或风控变化 |
| 线 D X4 / CxD | `crypto-x4-plan.md`, `x4-live-position-management.md` | 当前加密趋势 / 组合实盘线 | VPS production、risk、sizing、execution 变化 |
| 重启线 L1/L3/L4/L6 | `l*-*.md` | 已证伪、固化或暂停的结构性重启线 | 只在 owner 授权重启或修正结论时更新 |
| A股 ETF 20 日 | `ashare-etf-month-plan.md` | 主题状态、固定组合月度研究、收盘触发 | 数据、状态合同、风险上限或 evidence gate 变化 |
| 重构蓝图 | `rebuild-plan.md` | CTA-R / A股系统化思路 | 蓝图变化；不得覆盖当前生产事实 |
| Alpha Agents | `alpha-agent-plan.md` | 多 agent 研究组织、资料搜集、量化接入骨架 | 角色、任务、source book、agent 边界变化 |

新增文档前先判断是否能放进现有分类。新策略计划文件只有在 owner 明确授权新研究线时创建。

## 4. 研究线隔离

每条研究线必须有明确状态、文档归属、代码边界和 artifact 归属。

| 线 | 当前状态 | 主文档 | 代码边界 |
| --- | --- | --- | --- |
| A legacy `qount.main` / ETH-only | research-only / live disabled | `current.md`, `profit-*.md` | `src/qount/*.py` legacy core |
| B GRID | archived / falsified | `grid-binance-*.md` | `src/qount/grid/`, `scripts/research/grid_b_*.py` |
| C RV-C | carry 组件已接入 CxD，但当前 carry 默认暂停 | `rv-c-plan.md` | `src/qount/rv/`, `scripts/desktop/rv_live.py` |
| D X4 / CxD | VPS production | `crypto-x4-plan.md`, `x4-live-position-management.md` | `src/qount/x4/`, `scripts/desktop/*x4*`, `scripts/desktop/cxd_*` |
| L1 / L3 / L4 / L6 | frozen / falsified / lessons retained | 对应 `l*-plan.md` | `src/qount/l*_*.py`, `scripts/research/l*_*.py` |
| A股 ETF 20 日 | frozen / owner-deprioritized / discovery blocked | `ashare-etf-month-plan.md` | `src/qount/ashare_etf_month.py`, `scripts/research/ashare_etf_month.py` |
| CTA-R rebuild | blueprint / guarded | `rebuild-plan.md`, `cta-r-value-gate-plan.md` | `src/qount/cta_*.py`, `scripts/research/cta_*.py` |
| Alpha Agents | active research-only new-source restart | `alpha-agent-plan.md` | `src/qount/alpha_agents/`, `scripts/research/alpha_agent_*.py` |

隔离规则：

- 一条线的配置、数据、artifact、changelog 不能默认复用到另一条线。
- 跨线复用只能复用“方法”和“纯函数工具”，不能复用结论或 promotion 资格。
- 共享代码必须放在稳定模块中，带单测，并保持 production / research 导入方向清楚。
- 研究脚本应是薄入口；核心逻辑放在 `src/qount/<line>/` 或明确的 research-only 模块。
- 任何 line 进入 live / paper forward，必须先在本线文档和 `current.md` 写清开关、停止条件和回滚路径。
- 多 agent 线只能写 research artifact；LLM agent 不得输出订单、目标权重、live 配置或风控 override。

## 5. 执行记录规则

每一批有意义更改完成后，都必须更新记录文档：

- 只改本线研究代码或脚本：更新本线文档 changelog；如果结论影响当前状态，再更新
  `current.md` 和 `update-log.md`。
- 改 production、VPS、dashboard、live/paper forward、全局规则：更新 `current.md`、
  `quick-handoff.md`、`update-log.md`。
- 改文档分类或项目规范：更新本文件、`README.md` / `quick-handoff.md` 入口和 `update-log.md`。
- 改代码但未跑测试：记录“未跑”的具体原因，不允许写成已验证。
- 新 artifact 必须记录命令、窗口、holdout role、成本假设、数据源、输出路径和读法。

`update-log.md` 不是杂记。它只记录足以让下一轮判断“做了什么、验证了什么、结论是什么”的内容。

## 6. 验证与反过拟合规则

项目默认继承以下研究纪律：

- 已看过窗口只能算 `discovery_pool`，不能调参后再当 validation。
- promotion 必须走 `holdout.md` 的 once-only 规则。
- 时间序列或重叠标签必须使用 purged split / embargo 或等价防泄漏设计。
- 任何网格搜索、参数扫描、模型选择都要记录 trial 数，并优先看 DSR、PBO/CSCV、OOS fold 稳定性。
- 横截面策略必须同时报告 rank-IC 和 effective breadth；不能只用币数或标的数当广度。
- 所有收益读数必须扣真实可执行成本，至少区分 taker、maker/auction、资金占用、换手、滑点或价差。
- 交易所字段顺序、funding 口径、费率和最小名义价值必须以官方文档或交易所返回为准。

### 6.1 数据下载代理边界

- 大批量public data只在Windows/WSL侧下载并直接写外置盘；Mac和VPS不得作为下载或数据中转节点。
- Windows/WSL可直连，也可使用owner-approved Liangxin Cloud proxy；永不使用owner的苏菲家宽代理。
  URL、token和代理凭据只存在仓库外的本地环境，不得写入源码、文档、artifact、命令输出或git。
- 能复用外置盘缓存就不新增下载；明确标为offline的实验在缓存缺失时必须fail closed，不能静默改成联网运行。

外部参考固定如下，后续新增资料要写进相关线文档或本节：

- Deflated Sharpe Ratio: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Probability of Backtest Overfitting / CSCV: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- Advances in Financial Machine Learning, purged CV / embargo: https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086
- Binance Spot Kline 字段顺序: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#klinecandlestick-data
- Binance USD-M funding history: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History
- CCXT rate limit / exchange behavior: https://docs.ccxt.com/

## 7. 代码架构规则

- `src/qount/main.py` 只做 CLI 分发，不堆研究逻辑。
- production 代码不得 import `scripts/research/*` 或隐式依赖 optional research extra。
- `scripts/research/*` 只做参数解析、读写 artifact、调用 `src/qount` 里的可测试函数。
- `scripts/desktop/*` 是运维入口；会下单或写生产 state 的脚本必须有 dry-run / armed 边界。
- 新共享能力优先放进已有模块：artifact 写入用 `artifacts.py`，交易所差异用 `exchange_utils.py`
  或本线 data 模块，统计方法优先沉淀成可单测函数。
- 新依赖默认不能进基础依赖；研究依赖走 optional extra，live 路径保持最小。
- 生成物和包元数据不是源代码真相。`src/qount.egg-info/*` 只随安装流程变化，不手写当设计入口。

## 8. 弃用和清理规则

清理无效代码必须先做引用审计：

1. `rg` 查 README、docs、scripts、src、tests 是否仍引用。
2. 如果是 production 入口，先加显式拒绝或 legacy guard，而不是直接删除。
3. 如果连续无引用、无 artifact 依赖、无文档保留价值，才删除文件。
4. 删除后跑最小相关测试；无法跑要写明原因。
5. 同步更新文档入口和 changelog，避免“代码删了但文档仍指向它”。

当前已知legacy入口：

- `scripts/mac-monitor.sh`、`qount-monitor`：旧line A/WSL桌面状态入口，不能作为生产状态。
- `scripts/sync-to-wsl.sh`和`run-wsl-tests.sh`已重新定位为按需计算工作区更新/验证，不再带legacy授权门，仍不得
  推断WSL是live/paper真相。
- 旧 WSL / line A 桌面面板不得作为当前加密实盘状态入口。

## 9. 跨线经验库

以下经验可以跨线复用，但不能把某线结果直接当另一线的证据：

- 广度比标的数量重要：majors / ETF / token 横截面多次证明高相关会把有效广度压到 1.5-2 左右。
- 真实 edge 常被成本墙吃掉：5m、L4、L6 都显示 gross 正不等于可执行净正。
- maker 假设必须实测：只要 required maker fill 接近 1，本项目默认判为不可由慢系统兑现。
- 组合权重和参数选择必须 OOS 复核：D4 in-sample 组合提升被 purged-CV 推翻，应作为模板教训。
- 数据源换新不等于约束解除：L3/L6 找到新信号后仍要重新过 breadth、cost、timing、capacity。
- 生产真相必须单一：Mac研究、外置盘数据、WSL计算、VPS运行，不能跨节点混读不同state后下结论。
