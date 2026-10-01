# 策略优化与 CTA-R 恢复推进计划

> **状态**：draft（待 owner 审阅）｜**权威**：本文仅为计划文档，不改变任何生产参数、服务、凭据或授权  
> **最后更新**：2026-09-24  
> **本文回答**：9 月 23–24 日复盘后的问题清单、CTA-R 重新接入方案、策略优化研究路线、基础设施改进步骤。  
> **TL;DR**：优先级 P0 = L1 Tiingo 凭据配置（owner 操作，解锁 SPY 基准和 L1 数据线）；P1 = CTA-R akshare 采集线重新接入（新合同根，研究限定）；P2 = C60 换手成本优化研究（本地脚本，不改冻结合同）；P3 = 日报 BadRequestError 排查。所有步骤均 `research_only=true / orders_authorized=false`，不含生产授权。
>
> **2026-09-29 进展**（owner：加密优先，开始执行）：
> - P0 诊断：本机 `.env` 的 Tiingo key 以最小请求验证 `HTTP 200`、有效，**不是过期**。缺口是 VPS
>   `/etc/qount/research-forward-collector.env` 从未写入 `QOUNT_TIINGO_API_KEY`（paper 服务用的是另一个文件的
>   `TIINGO_API_TOKEN`）。另：`src/qount/dual_engine/reference_data.py` 与 `--refresh-reference` 在本地仍未提交，
>   9-24 部署后 Dashboard SPY 基准是否已出现未能核实（公开数据端点需认证）。
> - P1 已于 9-27/9-29 完成（见 `current.md`）。
> - P2 已由预登记研究 [c60-cost-expectancy-preregistration-2026-09.md](c60-cost-expectancy-preregistration-2026-09.md)
>   （Trial 149/150）取代。近似分解显示约 86% 换手来自整仓进出，方案 B（最小换手阈值）基本无效，不再执行；
>   研究还确认冻结合同“每日重排候选”偏离研究原版“每月选候选”。
> - `crypto_vol_crisis_state_v1`：建议关闭 family（剩余 2 个 trial 不再使用），理由见 update-log 2026-09-29。

---

## 0. 当前问题清单（按优先级）

| 优先级 | 问题 | 根因 | 影响 |
|--------|------|------|------|
| P0 | L1 passive Tiingo 源 37/37 `insufficient` | VPS `/etc/qount/research-forward-collector.env` 未写入 `QOUNT_TIINGO_API_KEY` | SPY 基准为空；Dashboard 无法显示市场超额收益对比；L1 研究线无数据 |
| P0 | Dashboard SPY bars 全为 0 | 上一条直接导致 | 无法验证 G20/C60 相对 SPY 的超额收益 |
| P1 | CTA-R 从 active source graph 移除 | 2026-09-24 批次明确冻结 | A 股 ETF 前向采集中断；跨资产研究数据断档 |
| P1 | VPS 缺少 `/root/qount/state/cta_r/etf_source/etf_data.zip` | CTA-R 停止采集，种子文件未维护 | 即便恢复 akshare 采集，初始化也缺种子 |
| P2 | C60 YTD 基础成本 656 USD_EQ（占本金 6.56%），Executable NAV -0.94% vs Signal NAV +5.96% | C60 日频执行，32 个调仓事件/62 笔 fills（8月初以来） | 策略信号有效但成本吃掉全部 alpha |
| P3 | 日报 9 月 8 日起全部 `BadRequestError`，9/4、9/12 无工件 | LLM API quota 耗尽（owner 已决定暂不处理）；模型请求合同需排查 | 研究分析质量下降；六角色全 blocked |
| P4 | D15 YTD 收益（+11.97%）低于 GC5（+13.34%） | C60 成本拖累放大；短样本无法区分择时 alpha 与噪声 | D15 动态分配设计价值待证明 |
| P4 | Liquidation 窗口缺 gap（两次重启各约 50/33 分钟） | VPS 重启 | 180 天评估窗口最早 2027-02-14，当前不能得出信号结论 |

---

## 1. P0：L1 Tiingo 凭据配置

### 背景
`forward-sources.json` 的 `l1_passive_tiingo` 源配置 `api_key_env: "QOUNT_TIINGO_API_KEY"`，
但 VPS `/etc/qount/research-forward-collector.env` 文件当前不含该键，导致每次采集返回 `insufficient`。
`dual-engine-paper.env` 已正确配置 `TIINGO_API_TOKEN`，两者是不同服务文件，不能合并。

### 步骤（owner 在 VPS 上执行，不修改代码）

**步骤 1.1 — 检查当前 env 文件是否存在**
```bash
# VPS 上
ls -la /etc/qount/research-forward-collector.env 2>/dev/null || echo "NOT FOUND"
```
若文件不存在则创建；若存在则追加。

**步骤 1.2 — 写入凭据（值从本机 `.env` 的 `QOUNT_TIINGO_API_KEY` 获取，不在此处记录）**
```bash
# VPS 上，以 root 执行
cat >> /etc/qount/research-forward-collector.env << 'EOF'
QOUNT_TIINGO_API_KEY=<从本机 .env 复制，此处不写值>
EOF
chmod 600 /etc/qount/research-forward-collector.env
chown root:root /etc/qount/research-forward-collector.env
```

**步骤 1.3 — 验证下一个自然周期**

等待 15 分钟，检查 collector 日志：
```bash
journalctl -u qount-research-forward-collector -n 20 --no-pager
```
预期：`l1_passive_tiingo` 源状态从 `insufficient` 变为 `valid`；
`forward/ops-health-v2` 链新记录中 `l1_passive.data_conclusion=valid`。

**步骤 1.4 — SPY reference artifact 更新**

`collect_dual_engine_market.py` 每天运行时会拉取 `dual_engine/reference_data.py` 中的 SPY/TLT 数据。
凭据到位后，等待下一次 paper daily 执行（VPS 北京时间 06:30），
Dashboard 的 `benchmarks` 字段应从空数组变为含 SPY 数据。

### 完成标志
- `forward-sources.json` `l1_passive` 线路 `data_conclusion=valid`
- Dashboard `#/paper` 显示 SPY 基准折线
- 不修改 `forward-sources.json`、代码或 systemd 模板

---

## 2. P1：CTA-R akshare 采集线重新接入

### 背景与定性

CTA-R 原有两个层次：
1. **数据采集层**：akshare 拉取 8 只 A 股 ETF 日线（510300/510500/159915/510050/518880/511010/513100/513500），本地存 `etf_data.zip` 种子 + 日更 cache。
2. **策略层**：多窗口 TSMOM + vol-parity + 回撤降杠杆，2026-06 J0 资格门判死（金/债/QDII近年贡献 93% 但估值门对其完全失明）。

**本次只恢复第 1 层（数据采集），不复活策略层**。理由：A 股 ETF 日线数据是独立研究资产，可用于：
- 跨资产相关性研究（A 股与美股/加密/大宗的相关性随市场状态变化）
- CTA-R 策略层未来 regime 重评（当 A 股权益重新成为收益主力时）
- L1 passive 扩展研究（当前只有 SPY/TLT，A 股 ETF 是独立收益源候选）

这是 `research_only` 数据采集，不产生 StrategyIntent、不写 paper、不生成订单授权。

### 实现方案

**合同边界**：CTA-R 重新接入必须使用新合同根（新 state root），不修改现有 `ops-health-v2` 链。
根据 `research-forward-collector.md` §Adding A Line Or Source：
> 改变插件集或适配器源会创建新状态根合同，不得原地修改现有采集历史。

因此新链根路径为 `/var/lib/qount/research/forward/cta-r-akshare-v1`。

#### 步骤 2.1 — 准备 etf_data.zip 种子（Mac 本地，须 akshare 环境可用）

`src/qount/legacy/line_a/cta_data.py` 的 `akshare` 路径接受 `etf_source_path`（`etf_data.zip` 的本地缓存路径）。种子文件格式：宽表 CSV，列为 ETF 代码，行为日期，值为收盘价。

```bash
# Mac 本地，确认 akshare 可用
PYTHONPATH=src ./.venv/bin/python -c "import akshare; print(akshare.__version__)"
```

若 akshare 不在 venv，不安装到生产 venv，单独建研究环境：
```bash
python3 -m venv .venv_research_cta
.venv_research_cta/bin/pip install akshare
```

生成种子：
```bash
# 新建独立采集脚本（见步骤 2.2），用它产出种子 ZIP
PYTHONPATH=src .venv_research_cta/bin/python scripts/research/cta_r_seed_builder.py \
    --out state/research_cache/cta_r_seed/etf_data.zip \
    --start 2015-01-01
```

#### 步骤 2.2 — 新建采集脚本 `scripts/research/cta_r_seed_builder.py`

该脚本是 thin adapter，只调用 `cta_data.py` 的 akshare 路径：
```python
"""Build or refresh the CTA-R A-share ETF seed ZIP for forward collection."""
# research_only=true / orders_authorized=false
# 入参: --out <path> --start <date> --end <date>
# 产出: etf_data.zip（宽表 CSV，date x ETF 收盘价）
# 依赖: akshare（研究环境，不进生产 venv）
```
脚本不进 `src/qount/`，只在 `scripts/research/` 下，符合项目规则（thin adapter）。

#### 步骤 2.3 — 在 `forward_collector.py` 新增 `CtaRAksharePlugin`

插件位于 `src/qount/research/forward_collector.py`（或新建 `src/qount/research/cta_r_forward_plugin.py`）。
接口：

```python
class CtaRAksharePlugin:
    name = "cta_r_akshare_inputs"

    def collect(self, context: CollectionContext) -> PluginResult:
        """
        Read the local etf_data.zip seed (cache-first) and check freshness.
        Returns valid if all 8 ETF series have data within 3 trading days.
        Returns insufficient if seed missing, any series stale, or akshare unavailable.
        Never calls order paths; never produces strategy weights.
        research_only=true / orders_authorized=false
        """
```

设计原则：
- **cache-first**：优先读 `etf_data.zip`，不强制在线拉取（VPS 无 akshare 时返回 `insufficient` 而非报错）
- **freshness check**：检查最新一条记录日期是否在最近 3 个交易日内
- **无 akshare 依赖**：插件本身只读 ZIP；在线刷新由单独维护任务处理，不绑定 15 分钟 collector 周期
- **数据只读**：不写入 paper、NAV、策略权重或任何订单路径

#### 步骤 2.4 — 更新 `forward-sources.json`

在 `sources` 节新增：
```json
"cta_r_akshare": {
  "kind": "cta_r_akshare",
  "state_root": "/var/lib/qount/research/cta_r/etf_source",
  "seed_path": "etf_data.zip",
  "symbols": ["510300","510500","159915","510050","518880","511010","513100","513500"],
  "role": "A-share ETF daily close series for CTA-R cross-asset research"
}
```

在 `research_lines` 节新增：
```json
{
  "id": "cta_r_akshare",
  "sources": ["cta_r_akshare"],
  "mechanism_conclusion": "valid",
  "data_conclusion": "insufficient",
  "strategy_return_conclusion": "insufficient"
}
```

**注意**：修改 `forward-sources.json` 会触发 source_config_hash 变化，现有 `ops-health-v2` 合同会检测到不匹配并拒绝启动。因此需要创建新合同根 `cta-r-akshare-v1`，并更新 systemd 服务的 `--state-root` 参数，或部署新的独立服务单元（推荐后者：两个独立 timer，互不干扰）。

**推荐方案**：保持 `ops-health-v2` 不变（其合同已固定），新建独立 timer/service：
- `qount-research-cta-r-collector.service` + `qount-research-cta-r-collector.timer`
- 状态根：`/var/lib/qount/research/forward/cta-r-akshare-v1`
- 采集频率：每日一次（A 股 ETF 日线，15 分钟采集没有意义）

#### 步骤 2.5 — 提供 etf_data.zip 到 VPS

```bash
# 种子生成后（Mac 本地），传至 VPS
scp state/research_cache/cta_r_seed/etf_data.zip \
    qount-vps:/var/lib/qount/research/cta_r/etf_source/etf_data.zip
# VPS 上设置权限
ssh qount-vps "chmod 600 /var/lib/qount/research/cta_r/etf_source/etf_data.zip"
```

#### 步骤 2.6 — 部署验收

1. 本地：`PYTHONPATH=src ./.venv/bin/python -m unittest tests/test_forward_collector.py` 覆盖新插件
2. VPS：手动触发一次 `qount-research-cta-r-collector.service`，确认 `Result=success`
3. 检查 `/var/lib/qount/research/forward/cta-r-akshare-v1/metadata/current.json`：`cta_r_akshare.status=valid`（或 `insufficient`，若种子不够新）

### 完成标志
- `cta_r_akshare` research line 在独立状态根下采集运行
- 原 `ops-health-v2` 链完全不受影响
- 8 只 A 股 ETF 日线数据可从新链读取用于研究
- `strategy_return_conclusion` 保持 `insufficient`（不是策略，只是数据）

---

## 3. P2：C60 换手成本优化研究

### 背景
C60 YTD Signal NAV +5.96%，Executable NAV -0.94%，差值 6.9 个百分点，
累计基础成本 656 USD_EQ（本金 6.56%）。8 月初以来 32 调仓事件、62 笔 fills，
G20 同期仅 2 事件、9.58 USD 成本。问题根因是 C60 日频决策产生大量微小调仓。

### 研究目标（本地 scripts/research，不改冻结合同）

验证以下三个降频方案的成本/信号权衡，采用已有历史数据（2026-01-01 YTD replay 区间）：

**方案 A：周频决策（每周五 UTC 收盘重新判断）**
- 不改信号逻辑，只改决策节点频率
- 预期：调仓事件从 32 降至约 6–8（周数约 35 周，但熔断触发仍可能中断）
- 风险：错过单日 BTC SMA50 穿越事件后的即时防守

**方案 B：最小换手阈值过滤（目标权重变化 < 5% 不调仓）**
- C60 候选集从 {ETH, SOL} 变为 {ETH, BTC} 或 {ETH, XRP} 时，若权重变化 < 5% 则跳过
- 保持日频决策时钟，但减少实际 fills
- 风险：阈值本身是参数，需验证 {3%, 5%, 8%, 10%} 的敏感性

**方案 C：降低波动率目标（C60 → C40）**
- 减少名义头寸大小，降低每笔摩擦的绝对美元数
- 信号权重和换手事件数不变，但每笔 fill 的名义额减少
- 这同时降低了收益和成本，需要看净收益的变化方向

### 验证框架

使用现有 `src/qount/dual_engine/strategy.py`（不修改）+ 新建研究脚本：

```bash
scripts/research/c60_cost_study_v1.py
```

脚本结构：
1. 读取已有 YTD paper 状态（只读，不修改）
2. 用相同历史市场数据，模拟三个方案的调仓序列和成本
3. 计算每个方案的 Signal NAV / Executable NAV 差值
4. 输出标准化报告到 `state/research_runs/c60_cost_study_v1/`

**判据（跑前锁死）**：
- 方案要判为"有改善"，必须同时满足：Executable NAV > -0.94%（超过现状）；调仓事件数减少 > 30%；Sharpe 不低于现状 × 0.9
- 任何方案若在历史最大回撤窗口（BTC SMA50 穿越期）表现比原版更差 > 2%，判为防守性失效

**重要约束**：
- 本研究结果不自动导入冻结合同
- 结果 → owner 审阅 → 若判活，单独开新 research issue，重新走 canonical replay + paper 晋级流程
- 不以 YTD 272 点（含回放）的短样本作唯一证据；必须补充 2020–2025 历史区间验证

---

## 4. P3：日报 BadRequestError 排查计划

### 背景
9 月 8 日起所有留存日报含 `BadRequestError`；9/4 和 9/12 无工件。
8 月 18 日以来 35 份全部 `incomplete`；21 份含 LLM 错误（15 BadRequest + 6 APITimeout）。

### 排查步骤（不发送新 API 请求，只分析现有工件）

**步骤 4.1 — 提取错误摘要**

读取 VPS 上保存的最近 10 份日报工件（路径待确认，通常在 `/var/lib/qount/reports/`），
提取 `BadRequestError` 的具体错误消息（模型名/请求体过大/参数不合法）：
```bash
# VPS 上
find /var/lib/qount/reports -name "*.json" -newer /var/lib/qount/reports/$(ls -t /var/lib/qount/reports | head -11 | tail -1) | xargs grep -h "BadRequestError\|error_code\|error_message" | head -40
```

**步骤 4.2 — 确认 quota 状态**

Owner 已明确"API 额度耗尽暂不处理"。在此前提下，检查是否有以下次生问题：
1. 模型名是否使用已废弃的 model ID（如 `claude-3-opus-20240229` 已从某些端点下线）
2. 请求体是否因 forward 数据增长超过 token 限制（近 1 GB 的 forward 链）
3. 是否有 context 构建路径在 quota 耗尽时产生不可重试的 BadRequestError（应区分 quota 和 contract 问题）

**步骤 4.3 — 分离 no-order 证据缺失与 LLM 失败**

当前日报六角色全部 blocked，部分原因是 `no_order_expected` 导致执行证据天然为空，
而非 LLM 失败直接导致。需要在 Dashboard 上区分展示两类缺失：
1. "预期缺失"：no-order 模式下 ledger 对账证据本就不存在
2. "LLM 失败"：分析角色因 API 错误未能运行

这是一个代码修改任务（`src/qount/reporting/` 的日报生成路径），单独排期，不在本批执行。

---

## 5. 文档整理清单

当前文档问题：部分文档存在导航重复、已过时引用和历史遗留条目未清理。

### 需要更新的文档

| 文档 | 需要操作 | 理由 |
|------|----------|------|
| `docs/research-forward-collector.md` | 更新 §Adding A Line Or Source 示例，加入新合同根创建流程 | 当前示例不体现"修改 source graph → 必须新建 state root"的约束 |
| `docs/qount_strategy_master_index.md` | 补充 CTA-R 重新接入后的状态说明 | 当前写"CTA-R remains frozen historical evidence"，需区分"策略层冻结"与"数据采集恢复" |
| `docs/current.md` | P0–P1 完成后补充验收事实 | 凭据到位、CTA-R 采集上线后需记录 |
| `docs/update-log.md` | 同上 | 记录执行步骤和验收结果 |
| `docs/archive/legacy/line-a/cta-r-value-gate-plan.md` | 无需修改 | J0 判死结论已完整，保留为只读历史证据 |

### 不需要更新的文档

- `AGENTS.md`：当前约束仍有效，不因本计划改变
- `docs/research-advancement-roadmap.md`：上次更新 2026-07-26，本轮只做数据采集和成本研究，不触及 roadmap 中的 trial framework
- `docs/archive/*`：归档文档不修改

---

## 6. 执行顺序与依赖关系

```
P0: L1 Tiingo 凭据（owner VPS 操作，无代码变更）
    └→ 解锁 SPY 基准 → Dashboard 可显示超额收益对比
    └→ 解锁 L1 passive research line data_conclusion=valid

P1a: etf_data.zip 种子生成（Mac 本地，需 akshare，约 1–2 小时）
P1b: CtaRAksharePlugin 实现 + 单元测试（代码变更，约 2–3 小时）
P1c: forward-sources.json 新增 cta_r_akshare source（触发新合同根）
P1d: 新建独立 systemd timer/service（cta-r-collector）
P1e: etf_data.zip 传至 VPS + 部署验收
    └→ 依赖 P1a–P1d 全完成

P2: C60 换手成本研究脚本（本地，不依赖 P0/P1，可并行）
    └→ 完成后由 owner 审阅结论，决定是否进入参数变更流程

P3: 日报 BadRequestError 排查（依赖 owner 决定是否恢复 API quota，当前阻塞）
```

**P0 是最高性价比操作**：仅需 owner 在 VPS 写入一个环境变量，不改任何代码，立即解锁 SPY 基准和 L1 数据线。

---

## 7. 硬边界（本计划不包含）

以下事项不在本计划范围内，需单独 owner 授权：

- 修改 G20/C60/D15 冻结合同参数（`g20_risk_weight`、`c60_volatility_target`、`d15_budgets`）
- 将 C60 成本研究结论直接写入 `DualEnginePaperContract.frozen_v1()`
- 启用交易 timer、arm、订单权限或任何 live 路径
- 恢复 FOMC live service（已明确取消部署）
- 向研究脚本注入 Tushare token 或其他未经 owner 审阅的凭据
- 在 paper 账本、NAV 计算或 audit 链中写入 CTA-R 数据
