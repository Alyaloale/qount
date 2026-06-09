# qount 重构计划:跨资产多策略系统化交易系统(CTA-R)

状态:草案 v0.1 · 创建 2026-06-06

> 本文件是一个**全新架构**的设计计划,**目标只有一个:在零售/小资本可及的范围内,搭一个期望盈利概率最高的全自动量化系统**。它不受现有 `docs/current.md` 的 §7 止盈纪律约束(那是旧研究线的边界);但保留旧项目里唯一被证据背书的 edge(L1 跨资产趋势)和最值钱的资产(反过拟合 harness)。代号 **CTA-R**(Cross-asset Trend-and-carry, Rebuilt)。

---

## 0. 核心判断(决定一切的前提)

> **盈利来源不是「预测得准」,而是「占住广度 + 收割风险溢价 + 把成本和风控做到极致」。**

旧项目全部证据都指向同一句话:

| 旧研究线 | 判决 | 根因 |
|---|---|---|
| 加密横截面 / 时序 / funding | 全证伪 | 广度天花板 eff-breadth≈1.6 |
| L3 换信息源(链上/稳定币 + AI) | 证伪 | 广度天花板在新数据源原样复现 |
| L4 跨所套利 | 证伪 | 成本地板 + pair 每 ~12h 翻转 |
| **L1 跨资产趋势** | **唯一真 edge** | **广度逃逸到 2.97** |

L1 是唯一真实、稳健、正、经济一致的 edge(21-ETF 跨资产 TSMOM,gross Sharpe 0.55、净 0.36–0.42、4/5 时间折正、2022 crisis-alpha)。它卡住的唯一原因是**零售 ETF universe 不够宽 + edge 量级不够**,而不是方法错。新系统的骨架因此确定为「**跨资产、多策略的系统化风险溢价收割机(mini-CTA / mini-AQR)**」。

---

## 1. 交易什么 —— 期货为主干

| 资产 | 角色 | 理由 |
|---|---|---|
| **期货(CME micros → 全尺寸)** | **主干(~90% 资金)** | 杠杆效率、跨资产类别天然广度、成本极低、流动性深、美国 1256 税优;趋势 + carry 最干净的载体 |
| 加密永续 | 配角(趋势 sleeve 里 1–2 个标的) | 已证伪加密**方向 alpha**;但和传统资产低相关,作分散品种有价值,不单独做加密策略 |
| 股票横截面(单票) | 后期可选 sleeve | 广度真大,是 LLM/另类数据唯一能合法加 IC 的地方;运维重,放最后 |
| ETF(零佣金碎股) | **仅 $500 启动期临时载体** | 资本 < $5k、未开期货账户前跑缩小版趋势;上期货后退役 |

**期货 universe(micros 阶段,~15–20 个,跨 6 大类):**

- 股指:MES / MNQ / M2K / MYM
- 利率:Micro 10Y / 2Y / 30Y 国债
- 金属:MGC(金) / SIL(微银)
- 能源:MCL(微原油) / MHG(微铜)
- 外汇:M6E / M6A / M6B
- 加密:MBT / MET

跨资产类别才是把有效广度从 1.6 拉到 10+ 的关键。资本上去后 micros 平滑换全尺寸 + 加品种(经典 CTA 50–100 个)。

---

## 2. 接口与数据(具体到名字)

**经纪商(执行):**

- **首选 Interactive Brokers (IBKR)** —— 全球期货 + micros + 股票 + 期权,成本低。接口 `ib_insync`(Python 最好用)/ 原生 TWS API / Web API。
- **备选 Tradovate** —— 期货专精,API 干净,micros 友好,门槛低。
- 加密 sleeve:沿用现有 **ccxt**。

**数据:**

- 期货历史(回测命脉):**Norgate Data**(零售 CTA 标准,连续合约/roll/回补到位)或 **Databento**(现代 API、CME、按量付费)。
- live 行情:IBKR / Tradovate 自带。
- 加密:ccxt。
- 股票/另类数据(后期):Alpaca 执行;基本面/另类源后选。

**避坑:** 期货回测难点不是策略,是「连续合约 + roll + 合约乘数 + 保证金」plumbing。用 Norgate + 自建 roll,别从原始 tick 拼。

---

## 3. 系统架构(干净重写)

事件驱动分层,每层 broker / asset 无关:

```
DataLayer        ── 统一行情/历史接口(期货/加密/股票适配器),连续合约 + roll
   ↓
SignalLayer      ── 每个策略 sleeve 独立产信号(纯函数,无副作用)
   ↓
PortfolioConstruction ── 多 sleeve 合成 + 风险平价 + 波动率定标 + 换算成合约张数
   ↓
RiskManager      ── 组合波动目标、单品种/单 sleeve 上限、回撤降杠杆、硬 kill switch
   ↓
ExecutionLayer   ── broker 适配器(IBKR/Tradovate/ccxt)、订单类型、滑点控制、对账
   ↓
Ledger / Journal ── 成交、持仓、PnL、归因
   ↓
Monitoring       ── 实时净值、风险、有效广度、告警
```

### 两条不可妥协的原则(不是官僚铁律,是「不这么做必然亏钱」)

1. **回测引擎和 live 共用同一份 Signal / Portfolio / Risk 代码**,只用 mode 开关切数据源与执行端。两套逻辑 = 你回测的不是你交易的东西 = 散户量化亏钱第一死因。
2. **保留旧项目的反过拟合 harness(DSR / PBO / purged-CV / effective-breadth)** 作为「质检线」。任何 sleeve 进 live 前必须过线。

### 新代码库目录(目标态)

```
src/qount/cta/
  data/        # 数据适配器 + 连续合约/roll + 合成数据(离线)
  signals/     # trend / carry / defensive sleeve(纯函数)
  portfolio/   # 风险平价 + 波动率定标
  risk/        # 波动目标 + 回撤降杠杆 + 限额 + kill switch
  execution/   # broker 适配器(IBKR/Tradovate/ccxt) + sim 成交
  engine/      # 统一 backtest/live 主循环(mode 开关)
  metrics/     # 复用现有 DSR/PBO/effective_breadth + 净值/回撤
```

第一版(本计划已交付)以单模块 `src/qount/cta_sim.py` 落地一个**垂直切片**:合成数据 → trend signal → 组合波动目标 → 回撤降杠杆 → 模拟成交 → 净值/指标。证明架构可跑、不是空中楼阁,然后再按上面目录拆分。

---

## 4. 策略 sleeves(按证据强度排序)

盈利不来自单一策略,来自**多个低相关 sleeve 叠加**。单 sleeve Sharpe 0.4–0.6,组合可达 0.8–1.2。

1. **跨资产趋势(主干,已验证)** —— 多 lookback(快/中/慢)+ 反波动率定权 + ensemble,跨全部期货。
2. **跨资产 carry(强分散器)** —— 注意:是**期货 carry / roll yield**(债券期限溢价、商品 backwardation、外汇利差),与已证伪的「加密 funding carry」是两回事;这是学术 + 实盘都稳健的持久溢价,且与趋势低相关,是把组合 Sharpe 从 0.4 推到 0.8 的关键拼图。
3. **防御 / 时序均值回归(小权重分散器)** —— 进一步降组合相关。
4. **(后期)股票横截面 value/momentum/quality** —— 广度真大,是 LLM + 另类数据唯一能合法加 IC 的战场;运维重,放最后。

---

## 5. 组合构建与风控(真正赚钱和保命的地方)

夏普在组合层和风控层,不在信号里:

- **波动率定标**:组合目标年化波动 10–15%,据此反推每个品种张数。
- **风险平价合成**:每个 sleeve / 资产类别贡献相近**风险**(非相近金额)。
- **回撤降杠杆**:进入回撤按规则降 gross,跌得越深仓越轻(CTA 护城河)。
- **live 监控有效广度**:实时算持仓相关矩阵 effective breadth,掉到阈值以下告警。
- **硬约束**:单品种/单 sleeve/总 gross 上限、kill switch、每日对账(持仓 vs broker 真值)。

---

## 6. LLM 的位置(诚实定位)

**LLM 不是 alpha 来源**,只有三个合法岗位:

1. **研究/运维加速**(最高价值):自动写 sleeve、跑 harness、解析数据、生成归因。
2. **股票横截面 sleeve 的另类数据提取**(后期):财报/新闻/招聘 → 结构化特征喂横截面模型。这是广度真大、IC 能加的唯一战场。
3. **regime / risk overlay**(可选,最后做,要先证明降回撤):检测宏观 risk-off → 动态降杠杆,当**减风险器**,不当信号源。

**绝不让 LLM 进趋势/carry 信号层**(广度游戏,加 LLM 只增过拟合面)。旧项目 L3 已证伪这条路。

---

## 7. 推进路线 + 资本台阶

### 阶段化(每阶段有门控,过了才进下一阶段)

- **Phase 0 — 重写内核** ✅(本计划已交付垂直切片):统一 backtest/sim 引擎、合成数据、trend sleeve、组合波动目标、回撤降杠杆、模拟成交、指标。**当前可离线跑本地模拟盘。**
- **Phase 1 — 趋势 sleeve 接真实数据 + 门控** ✅(DataLayer + 门控已交付,见 §9.1/§9.2):micros/ETF 真数据 → `--gate-scan` 出 DSR/PBO/折判决 → paper(IBKR paper account)→ 小额 live。**待你在装好数据源的机器上跑真实数据出判决。**
- **Phase 2 — 加 carry sleeve + 风险平价组合构建**:把单 sleeve 0.4 推向组合 0.8。
- **Phase 3 — 扩资本/品种/精修执行**:micros → 全尺寸,18 → 40+ 品种。
- **Phase 4(可选)** —— 股票横截面 + LLM 另类数据 sleeve。
- **Phase 5(可选)** —— 期权/波动率 sleeve。

### 资本台阶(别错配)

- **$500(现在)**:零佣金碎股 ETF 跑缩小版趋势 + 把 Phase 0 内核写完(已交付)。本质是验证执行/成本 + 攒可放大代码。
- **$5k–10k**:开 IBKR/Tradovate 上 micros,**真 CTA 从这里开始**。
- **$25k+**:全分散组合(趋势 + carry + 防御),接近满血。
- 再往上:线性放大,加品种/sleeve。

---

## 8. 现实预期(把丑话说前面)

- **现实 Sharpe ~0.8–1.2(组合,扣费)**:年化波动 10–15% → 年化收益约 10–18%。**不是暴富。**
- **回撤 15–25% 正常**,CTA 会有 1–2 年横盘/回撤期,熬不住会在最差时关掉。
- **$500 阶段绝对金额≈零**,真金白银收益要到 $25k+。系统价值在**可放大**(同一套代码,资本进来收益线性增长)。
- **最大风险不是没 edge,是执行/运维/纪律**:roll 搞错、对账漏、回撤期手动干预、过拟合漂亮回测。架构里那两条不可妥协原则才是真护城河。

---

## 9. 本地模拟盘(Phase 0 交付物)

模块 `src/qount/cta_sim.py` + 命令 `cta-paper-sim`,纯 stdlib、离线即跑:

- **DataLayer**:`generate_synthetic_panel` 生成跨资产日线面板(按资产类别的 block 相关结构 + regime-switching drift,让趋势有可捕捉的东西);或 `--prices-csv` 载入真实宽表。
- **SignalLayer**:多 lookback TSMOM ensemble(`sign(P_t/P_{t-L}-1)` 求均值)+ 反波动率定权,严格只用决策时点及以前数据。
- **PortfolioConstruction**:gross 归一 + 组合波动率定标到 `--target-vol`。
- **RiskManager**:回撤降杠杆(净值低于峰值 `dd_threshold` 时按 `dd_factor` 降杠杆)+ 最大杠杆上限。
- **ExecutionLayer(sim)**:周期再平衡、next-bar 成交、按换手收 `cost_per_side` 成本。
- **Metrics**:年化收益/波动/Sharpe、最大回撤、换手、**有效广度**(复用 `_panel_effective_breadth`,把核心论点接回生产)。

运行(**首选标准独立入口,纯 stdlib、无需 ccxt,任何机器离线可跑**):

```bash
PYTHONPATH=src python -m qount.cta_sim --days 1500 --seed 7 \
  --target-vol 0.12 --rebalance-days 5 --lookback-days 63 126 252
```

> 已装全栈(ccxt 等,如 WSL 生产机)的主机也可走 `python -m qount.main cta-paper-sim ...`,参数相同;但本地 Mac 通常没装 ccxt,`qount.main` 的导入链会失败,所以**本地一律用 `python -m qount.cta_sim`**。

输出净值曲线摘要 + 指标 + 落 `state/research_runs/...` artifact。这是把整条 Signal→Portfolio→Risk→Execution 链路跑通的最小证明;接真实数据只是把 DataLayer/ExecutionLayer 适配器换掉,核心逻辑不变。

> **重要诚实声明:合成数据上的 Sharpe(实测约 2.0+)是被生成器人为拔高的**——synthetic 面板带干净的持续趋势,趋势策略当然好看。它**只验证引擎正确、链路跑通,不代表任何真实 edge**。真实数据(§8)现实 Sharpe 约 0.8–1.2。别把合成回测数字当盈利证据。

### 9.1 DataLayer:真实数据接入(`src/qount/cta_data.py`)

DataLayer 是文档 §3 架构里**唯一需要随数据源改变的层**,signal/portfolio/risk/execution 全部不动。`--data-source` 选源,适配器把任意源转成对齐后的 `dict[name -> list[float]]` 价格面板喂给同一个 `run_paper_sim`。`cta_data.py` **import 时纯 stdlib**:IBKR / Norgate 的重依赖(`ib_insync` / `norgatedata` / `pandas`)只在真正用到时惰性导入,缺依赖或缺账户时给清晰的安装/配置报错,不影响离线 synthetic/csv。

| `--data-source` | 数据 | 依赖/前置 | 今天能否跑 |
|---|---|---|---|
| `synthetic`(默认) | 合成跨资产面板 | 无 | ✅ 任何机器离线 |
| `csv` | 任意宽表(date + ticker 列) | 无 | ✅ 自备 CSV |
| `tiingo` | 跨资产 ETF EOD(13 只) | `QOUNT_TIINGO_API_KEY`(免费)+ 网络 | ✅ 有 key 即可(**最便宜的真实数据路径**) |
| `ibkr` | IBKR 连续期货日线 | `ib_insync` + TWS/IB Gateway 登录 + 行情订阅 | 需在你装好 IBKR 的机器上 |
| `norgate` | Norgate 连续期货(`&SYM_CCB`) | `norgatedata` + 付费订阅 + NDU 在跑 | 需 Windows + 订阅 |

**各源运行命令(本地统一用 `python -m qount.cta_sim`,纯 stdlib 入口):**

```bash
# 1) 真实数据最便宜路径:跨资产 ETF(对应 §1 期货 universe 的 ETF 代理),今天就能跑
export QOUNT_TIINGO_API_KEY=...   # 免费 key,tiingo.com
PYTHONPATH=src python -m qount.cta_sim --data-source tiingo \
  --tickers SPY EFA EEM TLT IEF LQD HYG GLD SLV DBC USO UUP VNQ \
  --start-date 2010-01-01 --target-vol 0.12

# 2) IBKR paper(先开 TWS 或 IB Gateway 并登录 paper 账户,启用 API,端口 7497)
pip install ib_insync
PYTHONPATH=src python -m qount.cta_sim --data-source ibkr \
  --ibkr-port 7497 --ibkr-duration "10 Y"
#   默认期货:ES NQ RTY ZF ZN ZB GC SI HG CL 6E 6A 6B(连续合约 ContFuture)
#   注:历史回测用 IBKR,实盘执行也走 IBKR,数据/执行一套账户,省 Norgate 订阅

# 3) Norgate(Windows + 订阅 + NDU 在跑)
pip install norgatedata
PYTHONPATH=src python -m qount.cta_sim --data-source norgate --start-date 2005-01-01
```

> **数据源现状交代:** 本机(Mac)未装 ccxt/ib_insync/norgatedata、也无 Tiingo key,所以这一轮我只能**实跑并验证 synthetic / csv 两条路径 + 验证 IBKR/Norgate/Tiingo 在缺依赖/缺 key 时给出正确报错**;IBKR/Norgate 的真实拉取代码已写好,需在你装好对应依赖+账户的机器上执行。**推荐路径:先用 `tiingo`(免费 key)在真实跨资产 ETF 上跑通并过 DSR/PBO,再上 `ibkr` paper 接真期货**——ETF 代理足以验证 §0 的广度论点和趋势 edge 是否在真实数据上存活。

### 9.1.1 境内期货路径(中国大陆用户,合规,`--data-source tqsdk`)

大陆用户受外汇管制(个人 5 万美元额度且不得用于境外期货),**境外 IBKR 入金是灰色 + 摩擦大**;境内期货账户合规、人民币入金、商品期货几乎零门槛,且**国内商品是成熟的 CTA 趋势战场**。因此大陆主路是**境内商品期货**。

- **开户**:任一正规期货公司 App(永安/中信/国泰君安/银河/海通),身份证 + 银行卡,免费 T+1。选 CTP 通道。
- **数据/API**:**天勤 tqsdk**(免费历史数据 + 免费模拟账户 + Python 原生),只需注册免费天勤账户(shinnytech.com)。
- **默认 universe(跨板块、多为零门槛,`cta_data.TQSDK_DEFAULT_FUTURES`)**:有色(cu/al/zn/ni)、黑色(rb/hc)、贵金属(au/ag)、农产品油脂(m/c/y/p)、软商品能化(SR/CF/MA/SA),用主连合约 `KQ.m@EXCHANGE.product`。
  - 股指(IF/IC/IM)、国债(T/TF)需 ¥50 万验资 + 考试;铁矿/原油 SC/PTA 等特定品种需 ¥10 万验资——有权限再用 `--tickers` 加。

```bash
pip install tqsdk                       # 免费天勤账户:shinnytech.com 注册
export QOUNT_TQSDK_USER=...  QOUNT_TQSDK_PASS=...
# 国内商品期货上重新验证广度 + 门控(DSR/PBO/折)
PYTHONPATH=src python -m qount.cta_sim --gate-scan --data-source tqsdk --tqsdk-bars 2000
```

> **必须重新验证**:Sharpe 0.77 是美国 ETF 上的结果;国内 universe 不同,且**板块内相关极高**(黑色系/有色各自同涨跌),广度只能靠跨板块。换到国内品种后 breadth + 门控要在国内数据上重跑才算数。tqsdk 有免费数据可直接做。
> 执行层:tqsdk 的 `TqKq`(快期模拟)/`TqSim` 可做实时模拟盘,属 Execution adapter(Phase 1.5),本轮先做数据层 + 门控。

### 9.2 Phase 1 门控:真 edge 还是过拟合(`src/qount/cta_eval.py`)

光有净值数字不够——必须回答「这是真 edge 还是搜参搜出来的假象」。`--gate-scan` 跑一个**故意粗的参数网格**(3 组 lookback × 2 vol × 2 再平衡 = 12 cell),然后套用项目反过拟合 harness 出**判决**:

| 指标 | 含义 | 门控 |
|---|---|---|
| 年化 Sharpe(best cell) | 扣费后量级 | ≥ 0.5 |
| **DSR**(Deflated Sharpe) | best cell 的 Sharpe 扣掉「N 次试验取最大」的期望后,还有多大概率是真的 | ≥ 0.95 |
| **PBO**(CSCV) | IS 赢家在 OOS 是否仍在中位以上 | < 0.5 |
| 时间折 +占比 | best 配置在连续 OOS 折中为正的比例 | ≥ 0.6 |

DSR/PBO 是 `strategy_selection` 里那套 López de Prado / Bailey 公式的**忠实纯 stdlib 移植**(原模块经 ccxt 无法在本地 import)。门控阈值对齐 L1 跨资产 kill-test(IR 0.5 / DSR 0.95 / PBO 0.5)。

```bash
# 真实数据上出判决(同样支持 --data-source tiingo/ibkr/norgate)
PYTHONPATH=src python -m qount.cta_sim --gate-scan --data-source tiingo \
  --tickers SPY EFA EEM TLT IEF LQD HYG GLD SLV DBC USO UUP VNQ --start-date 2010-01-01
```

**门控已验证不是橡皮图章**(本地实跑):
- 合成趋势面板 → `PASS ✅`(DSR 1.000、PBO 0.024、折 +占比 1.00)
- **纯随机游走面板(零漂移、无趋势)→ `BELOW GATE ❌`**(best 年化 Sharpe −0.24、DSR 0.051、PBO 0.837、折 +占比 0.20、五项全挂)

也就是说:**给它噪声,它会拒绝;给它真信号,它会通过。** 真实 ETF/期货数据跑出来若是 `BELOW GATE`,就按 §0 老实承认零售量级不够、别投钱;若 `PASS`,才进 Phase 2(加 carry sleeve)。

---

## 10. Review 记录

2026-06-07 `/code-review`(high effort,7 角度)对 Phase 0 交付物(`cta_sim.py` + `main.py` 接入 + 单测 + 本文档)的结论:

- **[已修复] 文档 run 命令在无 ccxt 主机失效**:原 §9 写 `python -m qount.main cta-paper-sim`,而 `qount.main` 导入链需要 ccxt,本地 Mac 通常没装 → `ModuleNotFoundError`。已改为独立入口 `python -m qount.cta_sim`(纯 stdlib),并保留全栈主机的 `qount.main` 走法。
- **[已知,已护栏] 极端杠杆下负净值**:`max_leverage=3` 时单根极端 bar 理论上能把单期组合收益打到 < -1 → 净值转负。下游指标已护栏(`cagr` 返回 None、`net_daily` 跳过非正前值),不会崩;默认 12% 波动目标 + 合成面板下不可达。v1 接受。
- **[已知,minor] CSV 前导缺口回填**:`load_prices_csv` 用首个未来有效价回填前导 None(轻微前视),仅影响真实 CSV 的前导缺口,对价格水平基本无害。

核心 sim 主循环无前视(`tests/test_cta_sim.py::NoLookaheadTest` 用「篡改未来价格,决策时点权重不变」断言验证),成本敏感性(2.16→1.61)、跨种子稳健(breadth≈7.3)均符合预期。本地 `python -m unittest tests.test_cta_sim` 13 项全绿。

**待办(下一轮,按 §7 Phase 1):** 把 DataLayer 接 IBKR paper / Norgate 真实数据,在真实面板上复跑并过 DSR/PBO,再谈 live。

### 11. 真实数据首跑结果(2026-06-07,WSL,Tiingo)

在 WSL 生产机上用真实 Tiingo 跨资产 ETF(13 只,2010-01..2026,4130 交易日)跑 `--gate-scan`:

```
decision = PASS ✅
effective breadth = 2.62        # 真实逃出加密 1.6 天花板(与 L1 21-ETF 的 2.97 同源)
best ann Sharpe   = 0.77        # > 0.5 券商门控
DSR = 0.992 (≥0.95)  PBO = 0.230 (<0.5)  5 折全正 [0.90,0.96,0.57,0.96,0.39]
12 个网格 cell 全部为正(annSharpe 0.42–0.77)
```

**这是项目首次在真实数据上通过真实反过拟合门控。** 强于早先 L1 周频 TSMOM 的净 Sharpe ~0.4,因为 daily 多 lookback ensemble + 波动率定标 + DSR-罚过的网格最优。门控判别力已用纯噪声反证(噪声→BELOW GATE,DSR 0.05/PBO 0.84)。

**诚实 caveat(两项伪样本外检验):**
- 现实成本 5bps/腿(全历史):Sharpe **0.68**、CAGR 7.5%、最大回撤 **−23%** —— 扛得住成本。
- **近期 2022+(实际交易 2023–2026):Sharpe −0.03、总收益 −2.3%** —— 走平。强 Sharpe 前置在 2010–2022;2023–2026 趋势策略普遍难做,本策略同步走平。**edge 真但不平稳**:需准备 1–2 年横盘 + 20%+ 回撤(印证 §8)。**【2026-06-09 修正:此走平是 Tiingo 13-ETF 美股 universe 的结果,不可推广到实际可交易的 akshare 8-ETF 篮子——后者按年诊断 2023–2026 每年都正,见 §11.6。】**
- **$500 现金跑不出该 Sharpe**:12% 波动目标需 ~1.5–2x 杠杆,现金 ETF 账户做不到 → 要这个量级必须上期货(IBKR micros)。

artifact:`state/research_runs/manual-cta-gate-tiingo.json`(WSL)。结论:**方法被真实数据验证;不立刻赚钱;真正变现需期货账户。** 下一步 Phase 2(carry sleeve)或先上 IBKR paper 接真期货 micros 复核。

2026-06-07 DataLayer 接入轮(§9.1):新增 `src/qount/cta_data.py`,把 `--data-source` 抽象成 synthetic/csv/tiingo/ibkr/norgate 适配器 + 公共日期对齐(交集,不 ffill,无前视);IBKR/Norgate vendor 依赖惰性导入、缺失给清晰安装/配置报错;import 时纯 stdlib(不引入 ccxt/ib_insync/norgatedata)。`tests/test_cta_data.py` +12 单测(对齐交集/排序、Tiingo 注入 fetcher 端到端、缺 key 报错、缺 vendor 优雅 RuntimeError、dispatch)。实跑验证:synthetic(Sharpe 1.42)、csv(3 资产 Sharpe 0.56)端到端通;ibkr/tiingo 在本机(无依赖/无 key)给出预期报错。**IBKR/Norgate 真实拉取代码已写好但未在真机执行**(本会话无账户/订阅/依赖),需在你装好对应环境的机器上跑。

2026-06-07 Phase 1 门控轮(§9.2):新增 `src/qount/cta_eval.py`,纯 stdlib 忠实移植 DSR(López de Prado 期望最大值)+ PBO(CSCV)+ 时间折稳健,`run_gate_scan` 跑 12-cell 网格出 `passes_gate/below_gate` 判决;`--gate-scan` 接入两个入口;`run_paper_sim` 加 `net_daily_returns`(单跑 artifact 中 pop 掉保持精简)。`tests/test_cta_eval.py` +14 单测,三个 cta 模块共 **39 项全绿**。判别力实跑验证:合成趋势 → PASS(DSR 1.0/PBO 0.024),纯噪声 → BELOW GATE(DSR 0.05/PBO 0.84,五项全挂)——门控会拒绝噪声、通过真信号,非橡皮图章。

### 11.1 Binance 加密篮子门控判决(2026-06-07,WSL,ccxt 现货)

所有者要求"先做 Binance 加密量化",诚实路径 = 给 DataLayer 加 `--data-source binance`(ccxt OHLCV,惰性导入 + 走生产代理 + `fetchMarkets.types` 限定避开 dapi/eapi),用**已验证的同一套跨资产趋势引擎**在真 Binance 数据上跑门控,让 DSR/PBO 判决"加密单独做趋势是不是真 edge"。`tests/test_cta_data.py` +8 单测(注入 fetcher 端到端、日线对齐、4h 日内分桶不塌、dispatch、默认篮子),三 cta 模块 **47 项全绿**;WSL 全量 316 项绿。

真跑(12 个 USDT 现货对 BTC/ETH/BNB/SOL/XRP/ADA/DOGE/AVAX/LINK/LTC/BCH/TRX,1000 根日线≈2023–2026):

```
decision = BELOW GATE ❌
effective breadth = 1.64       # 平均绝对两两相关 0.57 —— 几乎精确命中 §0 加密天花板 ~1.6
best ann Sharpe   = 0.66       # 过 IR 0.5(raw 趋势收益是有的)
DSR = 0.769 (< 0.95) ❌  PBO = 0.721 (> 0.5) ❌  折 +占比 0.67(过)
12 cell ann Sharpe 0.07–0.66,best 配置 IS 赢家在 OOS 反低于中位(PBO 0.72)
```

**这是项目第三次、在全新真实 Binance 数据上独立复现加密广度天花板。** 含义:加密篮子里只有 ~1.6 个独立 bet(全是 BTC-beta),raw Sharpe 0.66 看着能交易,但**两个反过拟合检验(DSR/PBO)双双否决**——搜参选出的最优在样本外不泛化。这正是把"手操能盈利 / 折线拟合转折点"量化后的结局:IS 漂亮、OOS 塌。

### 11.2 A 股跨板块指数门控判决(2026-06-07,WSL,吸收 OpenQuant 本地 sqlite)

所有者有大 A 账户,要求走路 A(A 股可交易标的的跨资产趋势)。决策:**吸收不合并**——OpenQuant(`D:\C++\code\OpenQuant`,DDD 分层 FastAPI 选股工作台)对路 A 的价值是**数据不是代码**:`data/db/market_data.sqlite`(4.9GB,`price_bars` 5507 股 qfq 日线 + `index_bars` 597 指数日线 + `company_quarterly` 25 万行财务因子,带退市日)。把它**只读**(`mode=ro`,纯 stdlib `sqlite3`)接成 CTA-R 的 `--data-source openquant` adapter(`index_bars`/`price_bars` 可选),不碰其代码/app/DB。`tests/test_cta_data.py` +8(注入 fetcher、真临时 sqlite 端到端 index/price、缺库报错、坏表报错、dispatch),三 cta 模块 **55 项全绿**;WSL cta_data 28 项绿。

真跑(17 个跨板块指数:4 宽基 + 国债 + 10 行业 + 商品/红利,共同窗口 2015-02..2026-03,2694 日):

```
decision = PASS ✅
effective breadth = 1.71       # 平均相关 0.56 —— 和加密 1.64 一样低(宽基+行业全是 A 股 beta,唯一真分散器=上证国债)
best ann Sharpe   = 1.05        best cell lb=[63,126,252] vol=42 reb=5
DSR = 0.995 (≥0.95) ✅  PBO = 0.274 (<0.5) ✅  5 折全正 [0.53,1.52,1.83,1.24,0.23] +占比 1.00 ✅
12 cell ann Sharpe 0.60–1.05 全正,五项门控全过
```

**关键对照(广度几乎相同,判决相反):** 加密 breadth 1.64 → BELOW GATE;A 股指数 breadth 1.71 → PASS。差别不在广度,在**信号本身**:A 股板块趋势强且时间稳定(DSR 0.995/PBO 0.27/五折全正),加密的趋势 OOS 不泛化(DSR 0.77/PBO 0.72)。低广度意味着这是"少数强相关的强趋势 bet",比真跨资产更依赖 regime——五折全正缓解但不消除这点(2015 牛/股灾 + 几段大板块趋势可能拔高了 1.05)。

**三个必须随结果一起讲的硬约束(决定能不能落到你账户):**
1. **多空 + ~2.6x 杠杆**:引擎信号 `sign()` 有正有负、gross≈2.65x。**现金 A 股账户不能做空、加不了 2.6 倍杠杆。** 这个 1.05 是多空理想化——长仓-only 无杠杆能剩多少未知(A 股熊市趋势的钱大半在空头侧)。**这是 #1 下一步:加 long-only + 杠杆=1 模式复跑。**
2. **成本敏感性(已测)**:best cell(reb=5 周频)Sharpe 1.05@2bps → 0.99@5 → 0.92@8 → 0.75@10bps;低换手(reb=21 月频)~0.76→0.69 几乎不受成本影响、但 DD 更深(−23.6%)。**真实 A 股成本(印花税 5bps 卖 + 佣金 + ETF 价差≈单边 8–10bps)下 edge 仍在(≥0.7)**——成本不是杀手,做空+杠杆才是。
3. **指数 ≠ 可交易**:回测在指数上,你买的是对应 ETF(有跟踪误差、费率,且多数行业 ETF 上市晚于指数)。

artifact:`state/research_runs/manual-cta-gate-openquant.json`(WSL)。**结论:A 股跨板块趋势在多空理想化下强过门控,且扛得住成本——是项目首个落在所有者可及账户上的 PASS;但 long-only 无杠杆约束未测,在补这一刀之前不要相信 1.05。** 下一步单点改动:给 `cta_sim` 加 `--long-only` + 杠杆上限,在同一 universe 上复跑门控,看现金 A 股账户真能拿到多少。

**2026-06-07 long-only 复跑(`--long-only --max-leverage 1.0`,现金不可做空账户):表面 PASS 但是假象。** 给 `cta_sim` 加 `long_only`(负趋势权重清零)+ 门控透传 `long_only/max_leverage`(modes 非搜索维,不增 DSR 试验数);`tests/test_cta_sim` +2(long-only 无负权重、gross≤1)。全 17 指数 long-only 门控:decision=PASS、best Sharpe **1.51**、maxDD 仅 **−2.9%**——好得反常,证伪后发现:**反波动率定权把 85% 仓位灌进上证国债指数(000012)**,这是个"国债趋势 + 股票点缀"的低波动组合,吃 2015–2026 国债牛(利率下行),CAGR 才 4.2%、vol 2.8%,是"现金+"不是股票收益。拆解:

| long-only 组合 | Sharpe | CAGR | vol | maxDD | gross | 国债权重 |
|---|---|---|---|---|---|---|
| 全 17(含国债) | 1.51 | 4.2% | 2.8% | −2.9% | 1.00 | **85%** |
| 纯股票 16(剔国债) | **0.42** | 3.2% | 8.2% | −24.2% | 0.48 | — |

**真相:① 多空 1.05 真但不可交易(需做空 + 2.6x 杠杆);② long-only "1.51" 是单一国债指数的利率牛 + 反波动率集中(85% 一个标的,广度 1.71 早已预警"分散是假的"),regime 依赖、且国债指数零售 ETF 难精确复制;③ 纯股票 long-only 趋势 edge 仅 0.42 < 门控——做空一砍边就没了。** 现金 A 股账户单靠"股票板块趋势"过不了门控;单靠一个国债指数过门控但收益低且脆弱。**这正是 ETF 数据成为关键下一步的原因:本地库只有一个非股票分散器(国债),结果证明它在裸奔;要让 long-only 路 A 真正稳健,需要更多可交易的真分散品种——黄金(518880)、跨境(纳指 513100/标普 513500)、商品(豆粕 159985/有色 159980)——这些库里没有,需用免费 `akshare` 拉。** artifact:`state/research_runs/manual-cta-gate-openquant-longonly.json`。下一步单点:加 `--data-source akshare` ETF 源,在**可交易 ETF 的真跨资产 long-only 篮子**上复跑门控。

### 11.3 可交易 ETF 跨资产门控(2026-06-07,akshare 源:本地 zip 播种 + 缓存 + 在线补全)

加 `--data-source akshare`:吸收本地 `etf_data.zip`(Tushare daily+adj_factor)→ 算复权 close → 持久化成紧凑 `date,close` 缓存(`state/etf_cache/`,避免限流)→ 可选 akshare 在线增量补尾(域内无需代理)。**缓存读取纯 stdlib**,offline 路径任意机可跑。`tests/test_cta_data.py` +7(zip 复权读取/排序、缓存 roundtrip、播种→缓存优先、在线只补新尾、缺数据报错、dispatch),三 cta 模块 **64 项全绿**。默认 universe = 8 个可交易 ETF、**4 大类**:宽基股票(510300/510500/159915/510050)+ 黄金(518880)+ 国债(511010)+ 海外股(纳指 513100/标普 513500),共同窗口 2014-01..2026-06(3002 日)。

| | LONG/SHORT(理想) | **LONG-ONLY lev1(现金账户真实约束)** |
|---|---|---|
| decision | below_gate | **below_gate** |
| **有效广度** | **3.11** | **3.11**(平均相关 0.225) |
| best Sharpe | 1.00 | **0.95**(CAGR 11.2%,vol 12.6%,maxDD **−11%**) |
| DSR | 0.999 ✅ | 0.999 ✅ |
| **PBO** | 0.611 ❌ | **0.639 ❌** |
| 5 折 +占比 | 1.00 ✅ | 1.00 ✅(五折全正) |
| 12 cell Sharpe | 0.76–1.00 全正 | 0.78–0.95 全正 |

**两个关键结论:**
1. **广度问题彻底解决:1.71 → 3.11。** 加黄金+债+海外股的可交易 ETF 篮子决定性逃出全股票天花板(超过 Tiingo 2.62、L1 2.97)。§0 广度论点在**所有者能买的标的上**被证实。
2. **收益是真的,不是上次的国债幻觉。** long-only 无杠杆满仓(gross 0.99):Sharpe 0.95、**CAGR 11.2%**、回撤 −11%。反波动率仍给国债 61% 资金权重(风险平价里债资金权重天然大、但风险均衡),但黄金 8% + 纳指/标普 16% 真在贡献收益——区别于 §11.2 指数版那个 85%国债/4.2% CAGR 的"现金+"。

**但仍 BELOW GATE,且只挂在 PBO(0.64>0.5),其余五项全过。** 诚实诊断:PBO 量的是"IS 最优 cell 在 OOS 是否仍最优"。这里 12 个 cell 全部 0.78–0.95、全正、DSR 0.999、五折全正——**策略本身在所有参数下都稳健盈利**,正因为都好且挤成一团,"哪个最优"成了噪声,PBO 被推高。这是 **PBO 在"配置全优且密集"时的已知失效模式,和加密(DSR+PBO 双挂 + Sharpe 弱 + 广度封顶)性质完全不同。** 但门控是门控,记为 below_gate,不挪门柱。

**合法下一步(非挪门柱):** 生产设计本就**不挑 IS 最优 cell**——而是 ensemble 多 lookback(§4);且当前是**裸反波动率**,§5 计划的是**风险平价合成**(国债 61% 资金权重正是裸反波动率的产物)。诚实测法:用**先验固定配置 / 全 cell 等权 ensemble** 做 walk-forward(无参数选择 → PBO 不适用),看是否仍稳健(五折全正强烈暗示是)。artifacts:`state/research_runs/manual-cta-gate-akshare{,-longonly}.json`(WSL)。**结论:路 A 首次同时拿到真广度(3.11)+ 可交易 long-only 真收益(Sharpe 0.95/CAGR 11.2%/DD −11%,纯 ETF、不做空、不加杠杆);仅卡在"配置全优导致的 PBO 噪声",不是策略无效。** 这是项目到目前为止最接近"所有者账户能落地"的结果。

### 11.4 selection-free walk-forward:正面解决 PBO 疑问(2026-06-07,akshare ETF,long-only lev1)

为判定 §11.3 的 below_gate 是"策略无效"还是"PBO 在配置全优时的噪声",加 `--walk-forward`(`run_walkforward_eval`):**不挑 IS 最优 cell**,给三个 selection-free 读数——① **ensemble**:12 cell 日收益等权平均(零选择);② **walk-forward OOS**:每个 split 用**仅历史数据**选当时最优 cell,再向前测(真 OOS,正是 PBO 担心的"选参"诚实版;引擎严格因果→切片合法);③ **fixed**:先验固定配置(lb=[63,126,252] vol=63 reb=21,事前定、非 IS 赢家)。`selection_free_robust` 复用项目既有阈值(IR≥0.5 + 折正占比≥0.6),非新造门柱。`tests/test_cta_eval.py` +3(结构/选择数、趋势 robust 噪声 not、历史不足),三 cta 模块 **67 项全绿**。

ETF 跨资产 long-only lev1(现金账户,2496 eval 日):

| 读数 | Sharpe | CAGR | maxDD | 折正占比 |
|---|---|---|---|---|
| ensemble(零选择) | **1.00** | 9.5% | −8.2% | 5/5 |
| **walk-forward OOS(过去选参→向前测)** | **0.84** | 9.2% | −8.8% | 5/5 |
| fixed 先验配置 | 0.90 | 9.6% | −9.6% | 5/5 |

→ `selection-free ROBUST ✅`。**三个零/诚实选择读数全部稳健、且每个的 5 个时间折全正。** walk-forward 的过去-最优 cell 确实在漂移(split1 lb[63,126,252]vol42reb5 → split3-4 lb[21,63,126]vol42reb21)——这正是 §11.3 PBO 高的原因(最优参数会变),但**不论你当时会选哪个,向前测都是正的 Sharpe 0.84/CAGR 9.2%**。这定量证明:§11.3 的 PBO 失败是"配置全优→选谁都对→排名是噪声"的已知失效模式,**不是策略无效**。

**诚实边界(仍须随结果讲,不挪门柱不吹):** ① 反波动率使组合仍 ~50–60% 国债**资金**权重(风险平价常态,风险更均衡),低回撤靠债打底、上行靠黄金+美股——**利率 regime 反转(债熊)会恶化回撤**;② 513100/513500 是 QDII,有溢价/限购,实盘跟踪可能偏离;③ 2014–2026 含黄金牛+美股牛+中债牛三顺风,五折全正缓解但不消除 regime 依赖;④ 默认 2bps 成本,真实 ETF 5–10bps,但 reb=21 低换手 + §11.2 敏感性显示 edge 扛得住;⑤ 仍是回测,下一步 paper/小额。artifact:`state/research_runs/manual-cta-walkforward-akshare-longonly.json`(WSL)。**结论:用所有者现有大 A 账户、纯 ETF、不做空、不加杠杆,这个跨资产趋势组合在 selection-free 口径下稳健(walk-forward OOS Sharpe 0.84/CAGR 9.2%/DD <9%);PBO 疑问以证据正面排除。这是 CTA-R 首个既过真广度、又在所有者账户上 selection-free 稳健的可交易组合。** 下一步:§5 风险平价替裸反波动率(降国债资金集中)→ 或上 paper 小额验证执行/成本。

### 11.5 风险模式:权重上限 + 三档预设(2026-06-07,所有者要小资金高风险高收益)

**先校准一个技术点(写进决策):真·ERC 风险平价不会降低国债资金集中**——低波动资产在任何风险均衡方案里资金权重都大(ERC 甚至给更多)。所以"§5 风险平价替裸反波动率"按字面做解决不了"降国债集中 + 高收益"。真正的杠杆是 **per-asset 权重上限 + 资产类别剔除 + target_vol**,打包成**风险模式**。所有者选:权重上限 + 三档模式;进取档**完全剔除国债**。

实现(一处 cohesive 改动):`SimConfig.max_weight`(per-asset 上限,water-filling 再分配,纯函数)+ `cta_data.ETF_ASSET_CLASS`/`exclude_asset_classes`(按类剔除)+ `cta_sim.MODE_PRESETS`(三档)+ `--mode`/`--max-weight` CLI,`max_weight` 透传 gate/walk-forward(mode 非搜索维)。现金账户三档全 `long_only=True max_leverage=1.0`(不做空不加杠杆)。`tests/test_cta_sim` +7 / `test_cta_data` +2,三 cta 模块 **74 项全绿**;WSL 20 绿。

三档在 ETF 跨资产篮子(2014–2026)上的真实谱(walk-forward + fixed-config 表征):

| 模式 | universe | target/实际波动 | 最大单仓 | fixed CAGR | fixed maxDD | walk-fwd OOS Sharpe / 折正 |
|---|---|---|---|---|---|---|
| **稳健** | 8(含债) | 12%/12.0% | 国债 **60.9%** | 9.6% | −10% | 0.84 / **1.00** |
| **均衡** | 8 cap0.30 | 15%/16.6% | 27.6% | 13.5% | −12% | 0.85 / 0.80 |
| **进取** | 7(无债)cap0.35 | 25%/22.1% | 23.3% | **16.8%** | **−22%** | 0.86 / 0.80 |

**关键发现:**
1. **去集中不只是加风险,还抬了 Sharpe**——均衡/进取 ensemble Sharpe 1.08/1.04 > 稳健 1.00,且 CAGR 9.5%→13.6%。证明裸反波动率把 61% 灌进国债是**次优**,cap 后更均衡也更赚。最大单仓被精确压到 27.6%/23.3%。
2. **target_vol 是生效的真杠杆**(实际波动 12/16.6/22.1% 跟着目标走,gross 0.99/0.90/0.79 都没顶杠杆上限),不是我先前担心的"满仓封顶失效"。
3. **三档全 selection-free ROBUST**,但进取/均衡的 walk-forward OOS **折正占比从 1.00 掉到 0.80**(一个 OOS 折转负)——去掉国债压舱后**更依赖 regime**,这是高收益的代价。

**诚实边界:** ① 进取 OOS 一折为负,比稳健更挑时点;② 仍是 2014–2026 含黄金牛+美股牛三顺风,进取里黄金/美股权重更大、顺风依赖更重;③ QDII(513100/513500)溢价/限购在进取档影响更大(权重升);④ **现金账户无杠杆 → 风险天花板≈满仓风险资产的 ~22% 波动 / −22% 回撤,再高需两融(¥50万门槛,非小资金)**;⑤ 默认 2bps 成本,真实 5–10bps。artifacts:`state/research_runs/manual-cta-walkforward-akshare-{conservative,balanced,aggressive}.json`(WSL)。**结论:三档风险模式落地,小资金高风险高收益对应进取档(~17% CAGR/−22% DD/无国债),且不靠做空或杠杆。下一步:上 IBKR/券商 paper 或小额实盘验证执行/QDII 溢价/真实成本(铁律:先 paper 再 live)。**

**与跨资产对照(§11):** 同一引擎在 Tiingo 13-ETF(股/债/金/汇/商品)上 breadth 2.62、PASS;加密单独跑 breadth 1.64、BELOW GATE。差别不在方法,在 universe 广度——跨资产类别才逃得出天花板。**结论:加密的合法位置是跨资产组合里的 1–2 个低相关分散 sleeve(§1 既有定位),不单独做 Binance 方向策略。** artifact:`state/research_runs/manual-cta-gate-binance.json`(WSL)。LLM 新闻/regime overlay 仍按 §6 留作后期"减风险器"(须先证明降回撤),不进信号层。

### 11.6 按年×按资产归因诊断(2026-06-09,akshare 8-ETF,修正「走平」结论)

工具:`scripts/research/cta_yearly_attribution.py`(read-only,复用引擎 `_target_weights`/`SimConfig` 原样函数,直接读 `state/etf_cache` 拿对齐日期 + 收盘)。目的:判定 §11 那条「2023–2026 走平」是趋势旱季还是 edge 结构性衰减。fixed config(lb 63/126/252、reb21、cash long-only cap1.0)。

**按年净收益/Sharpe(2014–2026):** 2015 +29.3%/1.25、2017 +19.9%/1.94、2020 +29.2%/1.00、2022 −0.8%、**2023 +8.2%/2.66、2024 +9.8%/2.77、2025 +5.8%/0.94、2026(半年) +3.2%/2.22**。**2023–2026 每年都正,2023/24 还是好年——这个篮子根本没走平**(§11 的走平是 Tiingo 美股 universe)。

**按资产 gross 贡献:**

| 资产 | 类别 | 2014–2022 | 2023–2026 |
|---|---|---|---|
| 中证500 510500 | A股 | +43.2% | +0.4% |
| 上证50 510050 | A股 | +11.0% | +0.2% |
| 沪深300 510300 | A股 | +6.9% | −0.1% |
| 纳指 513100 | 海外 | +12.2% | +2.9% |
| 黄金 518880 | 黄金 | +3.5% | **+10.4%** |
| 国债 511010 | 债 | +12.2% | **+7.8%** |
| 标普 513500 | 海外 | +1.9% | +3.2% |
| 合计 | | +93.9% | +26.5% |

**判词:门控通过 ✅。** 2014–2022 靠 A股股票(中证500 一个 +43%)扛;**2023–2026 A股股票全归零,趋势正确撤出股票、轮进黄金(+10.4%)+国债(+7.8%)+海外,于是每年照赚——这是跨资产趋势按设计 regime 轮动、广度 3.11 真分散,不是衰减。**

**修正后的远期预期(写进决策):** ① **~7–9%/yr,不是回测头条 11–12%**(后者被 2015/2020 两个 A股大牛 +29% 灌高,近 4 年没有);② **近 4 年发动机=黄金+国债(~60% 贡献),金价已大涨/国债吃利率牛 → 若金或利率反转,当前驱动减弱,要等 A股股票趋势接力**(新依赖点,需盯);③ 准备 −15% 级回撤;④ Sharpe 与本金无关,¥100万 体量无容量压力、两融不划算。

### 11.7 操作化(②)+ 半自动组合跟踪(2026-06-09,所有者选「手动同步仓位 + 自动跟踪收益 + 提醒手动调仓」)

**8 ETF 境内可买性:** 全是普通现金账户 T+1 可买卖,买 ETF 不需要创业板/科创权限;唯一注意 513100/513500 是 QDII(溢价/限购,二级市场买卖不受限)。**A股 散户无开放 retail API**——合法程序化下单要 QMT(MiniQMT/xtquant)或 Ptrade + 券商量化权限(¥1M 够门槛)+ 程序化交易报备(2024 新规,月频很轻)。**所有者决定不全自动下单**(月频 12 次/年,全自动 ROI 低、增量风险高),改人在环里的半自动。

**交付物(research-only,不下单,不碰券商 API):**
- `scripts/research/cta_target_weights.py`:给定最新价 → 当前目标权重 → ¥金额/手数/残留现金的调仓表。
- `src/qount/cta_portfolio.py`(`python -m qount.cta_portfolio`,纯 stdlib,可单测,`tests/test_cta_portfolio.py` 12 项):
  - `init`:建本地持仓文件 `state/cta_portfolio/positions.json`(全现金起步);
  - `status [--refresh]`:估值/盈亏(总+分仓)+ 当前 vs 目标权重 + **调仓提醒**(cadence 21 交易日 OR 权重漂移≥5% 触发)+ 触发时打印买/卖手数清单;
  - `record-fill`:成交后一条命令同步本地持仓(blend 成本/扣现金);`mark-rebalanced`:盖调仓时间戳。
- `scripts/research/cta_yearly_attribution.py`:§11.6 的按年×按资产归因诊断。

**用法闭环:** 月度(或漂移触发)`status` → 照清单挂限价单 → 每笔 `record-fill` → `mark-rebalanced`。

**实时价 + Mac 桌面面板(2026-06-09 续):** ① **重要接缝**:缓存是 qfq 复权序列(只用于算信号/目标权重),其绝对价位 ≠ 可交易价;**估值/盈亏/下单手数必须用原始价**。东财 push2 从该 WSL 被断连,**新浪 `hq.sinajs.cn` / 腾讯 `qt.gtimg.cn` 直连可用**(域内、stdlib urllib、无代理无依赖)→ `fetch_spot_sina`(GBK 解析现价/昨收)。② `status` 默认用新浪实时原始价估值(取不到回退缓存收盘并标注),新增 `--json`(机器可读)+ 今日盈亏。③ **Mac 菜单栏面板** `scripts/desktop/ctar.5m.py`(SwiftBar/xbar 插件):Mac ssh→WSL 跑 `status --json` → 菜单栏显示今日盈亏、下拉显示分仓盈亏+目标权重+调仓订单;**到点/漂移触发时变红 + 弹 macOS 通知(每日去重)= 提醒推送 (a) 已落地**。`tests/test_cta_portfolio.py` 15 项(含新浪解析)。

**下一步 ③ paper/小额**:用这套小额跑 1–2 月,核 QDII 溢价/调仓滑点/跟踪误差 vs 回测。

### 11.8 模拟盘开跑 + Mac 桌面组件 + 本地复盘 + 自动调仓(2026-06-09)

**模拟盘已开跑**:`positions.json` 加 `paper` 标志(init 默认 true=模拟自动调仓;`go-live` 切 false=实盘手动);
`paper-rebalance` 按实时价一键模拟成交;¥100万 已建成进取档目标仓(6 ETF)。**本地复盘记录**:`equity.csv`
(每日净值,面板/daily 每刷新 upsert 一行)+ `trades.jsonl`(每笔成交,标 paper/live)+ `review` 命令(收益/峰谷/
最大回撤 + 流水)。**实时价接缝**:缓存是 qfq 复权(只算信号),估值/下单用**原始价**——东财被该 WSL 挡,改新浪
`hq.sinajs.cn` 直连(`fetch_spot_sina`,stdlib/域内/无代理)。**自动化**:`daily` 命令(刷新+落净值+paper 到点
自动调仓/live 仅提醒);WSL 空闲会关机故 cron 不可靠,**调度放常开的 Mac**——launchd `com.qount.ctar-daily`
每日 15:35 ssh→WSL 跑 daily。**Mac 桌面组件**:`scripts/desktop/ctar.jsx`(Übersicht,常驻桌面,显示总盈亏¥/
收益率/今日盈亏/**净值曲线 SVG**/分仓权重/调仓徽标)+ 取数 `ctar_fetch.sh`;另有 SwiftBar 菜单栏版 `ctar.5m.py`。
**日线缓存推进(stdlib,无 akshare):** `fetch_daily_sina`(新浪日线 kline,raw OHLC)+ `splice_daily`(纯函数:
锚定 cache 与 raw 的最新重叠日,按 raw 收益率比例把 cache 复权水平向前延伸 → **无接缝**,不论 cache 复权基准如何);
`_refresh_prices` 改用它,`daily`/`status --refresh` 每天把 8 只 ETF 缓存推进到最新(已验证 06-02→06-09 衔接平滑,
缓存复权价只算信号、估值/下单仍用新浪实时原始价)。caveat:锚点后若有分红会注微小跳变(这些 ETF 1–2 月窗口内罕见)。
`tests/test_cta_portfolio.py` 20 测。**全链路闭合,无遗留缺口。**

### 11.9 拓宽 ETF 篮子攻广度 = 证伪(2026-06-09,所有者选「拓宽广度」方向)

所有者要"提高收益",在三条合法杠杆(①加 carry sleeve 需期货 / ②拓宽 ETF 广度 / ③先验成本)中选 **②**。诚实测法:商品是当前 8-ETF 篮子缺的结构性新资产类别(现有 股/金/债/海外股,无商品),`ETF_ASSET_CLASS` 早已预注册 `159980.SZ`有色/`159981.SZ`能化/`159985.SZ`豆粕→`commodity` 但未进 `AKSHARE_DEFAULT_UNIVERSE`。**按经济先验选(三个低相关商品子板块),不挑回测,让门控判生死、好坏认账。**

**数据**:三只商品期货 ETF 均 2019 末上市,缓存/zip 种子都没有;**零依赖**走 `fetch_daily_sina`(新浪日线,域内,东财 push2 在该 WSL 被墙)拉到 ~1560 bars。商品期货 ETF 不分红 → raw close 的收益率==复权,raw 直接可用。**生产安全**:`cta_portfolio._load_panel` 是 `glob("*.csv")` 扫整个 `state/etf_cache/`——往生产缓存塞标的会让运行中的模拟盘悄悄改仓,故研究全程用独立 `state/etf_cache_wide/`,**没碰生产缓存**。

**apples-to-apples(同窗口 2020-01-17.. 1543 bars,long-only lev1):**

| | 有效广度 | 门控 | wf ensemble | wf OOS | fixed |
|---|---|---|---|---|---|
| BASE8 | 2.71 | PASS | 1.91 / 8.0% | 2.60 / 9.7% | 2.20 / 8.8% |
| WIDE11(+商品) | **3.37** | PASS | 1.64 / 7.5% | 2.19 / 8.8% | 1.85 / 8.1% |

进取档(剔国债/cap0.35)同窗口复核同向:无商品 wf OOS CAGR 23.3% → +商品 18.0%;仅回撤平滑 1–2pt。

**判词:证伪,不改生产篮子。** 广度真从 2.71 升到 3.37(§0 论点再次成立),但收益/Sharpe 两个风险模式、三个 selection-free 读数**全线轻微下降**。根因:**广度不是这个篮子收益的绑定约束**——BASE8 早以 breadth 2.71/DSR 0.997/PBO 0.004 轻松过门控,过线后"再加广度"≠"再加收益";2020–2026 是金+债+海外单边牛,集中在强趋势品种本就更赚,国内商品这段震荡弱趋势只起稀释。**不挑(不试"只留有色"/特殊权重 = 过拟合陷阱)。** ②路径关闭,真正抬收益只剩 ①carry sleeve(期货账户)或诚实接受零售现金 ETF 的 edge 量级天花板(§0/§11)。artifact `state/research_runs/manual-cta-wide-commodity.json`(WSL)。硬约束全不变,未碰生产缓存/`positions.json`。

### 11.10 ①carry sleeve:tqsdk 境内期货数据层跑通 + 趋势/carry 门控判决(2026-06-09,所有者授权开免费天勤账户)

所有者选 ①carry sleeve,提供免费天勤账户 → 写入 WSL `.env`(`QOUNT_TQSDK_USER/PASS`,gitignore)。**新增 carry sleeve(代码本来没有)**:`cta_sim` 加 `signal="carry"` 分支(期限结构 roll yield 的 sign × 反波动率,与趋势共用组合/风控,**趋势路径逐位不变**)+ 合成 carry 市场;`cta_eval` 加 carry 网格(平滑×vol×再平衡)+ walk-forward;`cta_data` 加期限结构 carry 构建器(纯函数:每日近月/次近月年化 roll yield `(near/far-1)·365/gap`)+ `fetch_tqsdk_carry_panel`(逐合约日线带缓存,live+expired 重建历史)。**Mac+WSL 86 单测全过**。

**运维坑(记 quick-handoff):天勤是域内服务器,必须取消代理直连**——`.env` 的 `HTTP(S)_PROXY` 是 Binance 专用,不 `unset` 会让 `auth.shinnytech.com` 走代理超时(`ProxyError`)。`adj_type` None/F/B 实测无差异(KQ.m@ 已是干净连续、非 raw 跳空)。

**判决(16 跨板块商品主连,2022-06.. ,long/short,扣费):**

| sleeve | 有效广度 | 门控 | walk-forward(ens/wf/fixed) |
|---|---|---|---|
| 趋势 | 3.46 | BELOW(DSR 0.854<0.95) | NOT ROBUST(0.25/0.40/0.47,全<0.5) |
| carry(经典:long backwardation) | 3.36 | BELOW 五项全挂(Sharpe **−1.01**) | NOT ROBUST(−1.38/−1.06/−1.26) |
| carry(符号翻转) | 3.36 | BELOW(DSR 0.983✓ 仅 PBO 0.607✗) | **ROBUST**(1.17/0.75/1.15) |

**诚实判词:**
1. **趋势单 sleeve ~0.4**,和计划 §4 预期一致(广度 3.46 真分散,但 edge 量级不够)。
2. **经典 carry(long backwardation)在中国商品 2022-26 彻底证伪**——截面 rank-IC **−0.038**(894 截面)、Sharpe −1,**符号是反的**(高 carry/backwardation → 次期收益更低)。
3. **翻转后信号是真的**(DSR 0.983、selection-free ROBUST Sharpe 1.17),PBO 0.607 是 §11.3 同型"配置全优"虚高。**但符号是看了数据才翻的 = 1-bit 过拟合**——按本项目纪律,**不能因为回测变好就翻符号当 edge**。这是一个真实但**仅在样本内**的 lead,**不可晋级**,需要:(a) 给"中国商品 carry 反向"一个事前经济理由(零售主导/金融化/近月投机溢价),(b) 用符号从未碰过的独立窗口(如 2018–2021)做真 OOS,(c) 用持仓量加权的流动主力合约重构 near/far(现按日历最近两月,近月可能偏薄)。

artifacts:`state/research_runs/manual-cta-tqsdk-commodity-{trend,carry}.json`(WSL)。硬约束全不变:research-only、未下单(天勤模拟账户未交易)、未碰生产。**carry sleeve 代码已固化为可复用资产**(对 IBKR 期货同样适用)。

**OOS 验证(2026-06-09 续):反向 carry = 符号 OOS 成立但量级 sub-gate,不晋级。** 所有者选"做真 OOS"。事前钉死:(a) 经济理由=中国商品零售/投机主导,陡 backwardation=近月拥挤多头→均值回归跑输→**事前承诺反向符号**(拥挤反转);(b) 独立窗口=从未碰过的 max-history..2022-05-31(免费天勤回到 ~2020,600 bars,与样本内 2022-06+ 不相交);(c) OI 加权流动主力重构留作符号活下来后的精修。给 `fetch_tqsdk_carry_panel` 加 `end_date`(纯构建函数不动,86 测过)。**OOS 实跑:① 原始 carry→fwd21d 截面 rank-IC=−0.0147(符号仍负,反向方向 OOS 成立——不是 2022-26 纯巧合),但量级是样本内 −0.038 的 ~40%;② 反向 carry 门控 BELOW(best 0.85、DSR 0.593<0.95、PBO 0.33✓、folds 0.80✓);③ selection-free walk-forward NOT ROBUST(ensemble 0.48<0.5 / wf 0.64 / fixed 0.90)。** 判词:**符号方向真实且 OOS 持续,但样本内 1.17 是 regime 灌高,OOS 只剩弱 tilt、不过门控**——撞回 §8/L1 同一堵墙:**信号真、零售单 sleeve 量级不够(趋势~0.4、反向 carry OOS~0.48,皆<0.5)**。按纪律 sub-gate 不晋级。固化:tqsdk 数据层 + carry sleeve + 期限结构 harness 作可复用资产;国内商品单 sleeve 追盈利按 §7/§8 同型止盈。下一次抬量级仍需结构性新输入(多 sleeve 风险平价组合需各 sleeve 先独立过线 / 真期货组合规模)。artifact `state/research_runs/manual-cta-tqsdk-carry-oos.json`(WSL)。

---

## 12. 跨主机角色与运维(CTA-R 专用)

> `docs/quick-handoff.md` 是 §7 止盈的旧加密线的运维手册;CTA-R 的跨主机现实记在这里。

### 12.1 角色定位

| | **Mac** `/Users/alyaloale/Code/qount` | **WSL**(`home`,`/home/alyaloale/Code/qount`) |
|---|---|---|
| 定位 | 编辑 + git 表面 + **本地开发验证** | **生产 / 回测真相** + 重依赖 + 网络 |
| 跑什么 | 本地 unittest;纯 stdlib `cta_sim`/`cta_eval`(**仅 synthetic/csv**,真实数据在 WSL)做 dev 验证——**确定性,与 WSL 逐位一致** | **权威** gate/walk-forward;全量测试套件;**所有真实数据 + artifact** |
| 依赖 | 仅 stdlib(`cta_*` 全程不需 ccxt/pandas) | ccxt/pandas/akshare/ib_insync;代理(Binance);`/mnt/d` 访问 Windows 数据 |
| git | git 表面;**WSL 不一定有 `.git`,别用 WSL `git status` 判断提交** | — |

**原则:** `cta_*` 是纯 stdlib + 确定性,离线源结果在 Mac 与 WSL 逐位相同;但**真实数据(ETF 缓存/openquant sqlite/zip)只存 WSL**,Mac 不留副本——所以 Mac dev 只能跑 synthetic/csv,真实数据的权威读数与 artifact 一律在 WSL(对齐铁律 + 数据归 WSL)。

### 12.2 数据源 × 依赖 × 跑在哪

| source | 依赖 | 数据位置 | 跑在哪 |
|---|---|---|---|
| `synthetic`/`csv` | stdlib | — | 任意 |
| `akshare`(ETF) | 缓存读**纯 stdlib**;在线补全需 akshare/pandas | **数据 canonical 在 WSL**:缓存 `state/etf_cache/` + 种子 `state/etf_data.zip`(`QOUNT_ETF_ZIP`) | **WSL**(数据在 WSL;Mac 只跑 synthetic/csv) |
| `openquant`(A 股) | stdlib `sqlite3` | `market_data.sqlite` 在 **Windows `D:`**,WSL 见 `/mnt/d` | **仅 WSL** |
| `binance` | ccxt + 代理 | API | **仅 WSL**(跑前 `set -a; source .env` 拿代理) |
| `tiingo` | stdlib urllib + key | API | WSL(key 只在 WSL `.env`) |
| `ibkr`/`norgate`/`tqsdk` | 各自 vendor | API/本地 | 装了对应依赖的机器 |

### 12.3 数据存储 = WSL canonical(`state/` gitignore 内)

**所有数据只存 WSL,Mac 不留副本**(`state/` 已 gitignore,永不进 git):

- ETF 缓存 `state/etf_cache/`、种子 `state/etf_data.zip`、artifact `state/research_runs/`、openquant sqlite `/mnt/d/...` —— 全在 WSL。
- `scripts/sync-to-wsl.sh` 只带代码(`README/pyproject/docs/prompts/scripts/src/qount/tests`),**不带 `state/`**——这是对的:代码 Mac→WSL,数据只在 WSL。
- **macOS 把 `~/Downloads` 对 shell/Python 都锁了(EPERM)**,所以 Mac 端搬不了原始 zip;放 zip 到 WSL 用你自己 shell:
  `! cat ~/Downloads/etf_data.zip | ssh -o ClearAllForwardings=yes home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && mkdir -p state && cat > state/etf_data.zip'"`
- 偶尔要在 Mac 看某个 artifact:反向 tar 拉单文件,**别把数据落进仓库提交**。

### 12.4 CTA-R 标准推进环

1. Mac 编辑 + `PYTHONPATH=src python -m unittest tests.test_cta_data tests.test_cta_sim tests.test_cta_eval`(纯 stdlib,秒级)
2. `scripts/sync-to-wsl.sh`(改了依赖加 `--install`)
3. `scripts/run-wsl-tests.sh [tests.test_cta_data]`
4. 需要新缓存 / 加 ETF 品种:**在 WSL** 上 `--data-source akshare --akshare-zip state/etf_data.zip`(首跑自动从 WSL zip 播种缓存)
5. WSL 跑权威 `python -m qount.cta_sim --data-source ... --gate-scan|--walk-forward [--mode ...]`
6. artifact 落 `state/research_runs/manual-cta-*.json`(WSL)
7. 写回 `rebuild-plan §11.x` + 记忆

ssh 模板:`ssh -o ClearAllForwardings=yes home 'wsl.exe bash -s' <<'EOF' ... EOF`
