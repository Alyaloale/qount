# qount

`qount` 是按当前真实机器拓扑设计的 `AI 决策系统 + 风控执行器 + Binance 执行` 骨架。

## 主机职责

- `Mac`
  - 开发、回测、看日志、手动运维
  - 不跑实盘执行器
- `Windows`
  - 提供 `Clash Verge`、`CLIProxyAPI`、WSL bridge
- `WSL Linux`
  - 唯一生产节点
  - 跑 `snapshot -> AI -> validate -> risk -> execute -> journal`

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
- WSL 运行脚本与 `systemd` 示例

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
```

如果你在 `Mac` 上不想盯 CLI，可以直接开本机浏览器面板：

```bash
./scripts/mac-monitor.sh --open
```

默认会在：

```text
http://127.0.0.1:8787
```

这个面板会通过 `ssh home -> WSL` 聚合：

- `healthcheck`
- `paper-status`
- `paper-replay`
- `signal-review`
- `live-guard-status`
- `systemd` timer 状态

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

当前这套 Windows/WSL live 文档里，已经验证通过的路径仍然是：

- `QOUNT_EXCHANGE_ID=binance`
- Binance futures 私有接口
- 独立 `7907` 代理出口

只有当你**确实**在 Binance US 账户 / API 上运行时，才把：

```bash
QOUNT_EXCHANGE_ID=binanceus
```

写进 `.env`。

如果你要跑合约 live，还要确保：

- Binance API key 已开通 futures/derivatives 权限
- 账户仓位模式是 `one-way`
- 账户可用保证金乘以 `QOUNT_CONTRACT_LEVERAGE` 后，能覆盖交易对最小名义价值

如果同时要让 WSL 内的 Python 访问本地 relay 和外网交易所，`.env` 里还要保留：

```bash
HTTP_PROXY=http://192.168.128.1:7907
HTTPS_PROXY=http://192.168.128.1:7907
NO_PROXY=127.0.0.1,localhost,192.168.128.1
```

当前这套 live 验证通过的链路里，`7907` 是给 `qount` 单独隔离出来的 Binance 专线，
避免和 Mac 浏览器或 Windows 其他代理客户端共用 `7897/7898` 的出口配额。

## Live 切换保护

`live` 模式不会因为你改了 `QOUNT_MODE=live` 就直接开单。

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

现在的 live guard 是“持续放行”语义，不再写入会过期的 arm 权限。
只要当前配置仍然满足 `QOUNT_MODE=live`、`QOUNT_LIVE_ENABLE=true`、确认短语正确，且每次运行前的交易所检查仍然通过，`run-once` 就会继续执行真实下单。

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

当前已验证过的 WSL smoke-run 示例：

```bash
ssh home "wsl.exe bash -lc 'cd /home/alyaloale/Code/qount && set -a && source .env && set +a && PYTHONPATH=src ./.venv/bin/python -m qount.main backtest --start 2026-05-14T22:00:00+08:00 --end 2026-05-14T23:30:00+08:00 --max-bars 8 --review-horizon-bars 3 --review-threshold-pct 0.003'"
```

这次验证结果里：

- `runs_completed=8`
- `paper_filled=1`
- `final_equity_quote=200.57048367093842`
- `total_return_pct=0.28524183546920767`

如果当前 `Mac` 本机的 `7907` 公有接口代理不通，优先在 WSL 节点上跑这条命令，不要先怀疑回测逻辑本身。

## 当前策略优化已落地部分

- `candidate filter`
  - 在 `AI` 前先过滤低波动、低成交量候选
  - 如果已有持仓，优先保留持仓 symbol 做管理决策，但仍会按 `max_open_positions - 当前持仓数` 放行少量非持仓候选
  - snapshot 会附带可选的高周期方向上下文，默认读 `QOUNT_CANDIDATE_TREND_TIMEFRAME=1h`
  - futures 下 `1h flat` 现在只做降分，不再直接把候选硬拒绝
- `risk gate`
  - 新开仓会检查 `min_expected_edge_pct`
  - futures 新开仓现在会把过小的 `size_pct` 抬到最小默认开仓比例，并把过低的 `take_profit_pct` 抬到最低止盈下限
  - futures 新开仓现在会按 `stop_loss_pct + estimated_cost_pct` 反推仓位，`QOUNT_MAX_RISK_PER_TRADE_PCT` 已经变成真实 sizing 约束
  - 如果交易所最小名义仓位要求会突破单笔风险预算，risk gate 会拒单并记录 `risk_budget_below_exchange_minimum`，不再为了成交强行抬仓
  - 会拦截过快反手、过早平仓、同 symbol 过快重进
  - 如果持仓已经积累到一定浮盈，后续又发生超过阈值的利润回撤，management 层会强制 `close` 锁住一部分利润
  - futures 持仓浮盈达到阈值后，risk 层会触发单次 `partial_take_profit`，通过 `close_fraction` 平掉一部分仓位
  - futures `sell` 现在仍会更早挡掉**明显** countertrend 的 short 候选；但 `1h` 偏空结构里的轻微 `5m` pullback 不再零容忍，会继续交给 `AI` / `risk gate` 判断
  - futures live 开仓现在会按通过风控后的 `take_profit_pct / stop_loss_pct` 立刻下交易所侧 `reduceOnly` 保护单；部分减仓后会取消旧保护单并给剩余仓位重挂保护单
  - 对 Binance futures 来说，这些 TP/SL 保护单属于 `conditional/algo` 单，不一定会出现在普通 `fetch_open_orders()` 结果里；现场排查要优先走 `trigger=true` / conditional 查询，而不是只看普通 open orders
- `review`
  - 不再只看方向对错，而是尽量贴近 post-cost 结果
  - 已增加 `decision_lifecycle / exit_source / blocked_group` 切片
  - 已增加 `planned_risk_pct_of_equity / future_R / mfe_pct / mae_pct / giveback_pct`，用于判断仓位风险、早平/晚平和回吐
  - 当前这轮 fresh-entry 复查不要只盯 `blocked_sell`
  - 应优先一起看：`by_lifecycle.fresh_entry`、`by_blocked_group.blocked_entry`、`by_symbol`，再用 `blocked_sell` 辅助判断 short 侧有没有被误伤

最新一次继续放松后，当前 live 节点已经出现新的真实 `sell` 开仓，不再只是 `hold/noop`。这说明当前主瓶颈已经从“太少出手”开始往“新放行样本质量如何”转移。

当前默认阈值都偏保守，建议先用 review 看真实 `net_edge_pct / flip_rate / same_symbol_reentry_rate`，再回调参数，不要直接继续加复杂规则。

## 相关参数

- `QOUNT_ESTIMATED_FEE_PCT`
- `QOUNT_ESTIMATED_SLIPPAGE_PCT`
- `QOUNT_CANDIDATE_TREND_TIMEFRAME`
- `QOUNT_MIN_EXPECTED_EDGE_PCT`
- `QOUNT_MIN_OPEN_SIZE_PCT`
- `QOUNT_MIN_TAKE_PROFIT_PCT`
- `QOUNT_FLIP_COOLDOWN_BARS`
- `QOUNT_MIN_HOLD_BARS`
- `QOUNT_SAME_SYMBOL_REENTRY_COOLDOWN_BARS`
- `QOUNT_TRAILING_PROFIT_ARM_PCT`
- `QOUNT_TRAILING_PROFIT_RETRACE_PCT`
- `QOUNT_PARTIAL_TAKE_PROFIT_ENABLE`
- `QOUNT_PARTIAL_TAKE_PROFIT_TRIGGER_PCT`
- `QOUNT_PARTIAL_TAKE_PROFIT_STEP_PCT`
- `QOUNT_PARTIAL_TAKE_PROFIT_FRACTION`
- `QOUNT_PARTIAL_TAKE_PROFIT_MAX_TIMES`
- `QOUNT_BREAKEVEN_STOP_BUFFER_PCT`
- `QOUNT_DYNAMIC_PROTECTIVE_REFRESH_ENABLE`

## 设计文档

- 当前 live 基线、持仓与策略现状：
  - [docs/live-baseline-and-strategy-current.md](docs/live-baseline-and-strategy-current.md)
- 当前按阶段执行的实施计划：
  - [docs/strategy-implementation-plan-2026-05-17.md](docs/strategy-implementation-plan-2026-05-17.md)
- 当前唯一主设计入口：
  - [docs/strategy-optimization-design.md](docs/strategy-optimization-design.md)
  - 这份文档已经吸收当前 active plan、首批已落地变更、后续未启用能力和归档入口
- 当前 post-fix 复查入口：
  - [docs/fresh-entry-effect-check-2026-05-14.md](docs/fresh-entry-effect-check-2026-05-14.md)
- 2026-05-12 生产运行、决策历史与收益复盘：
  - [docs/live-review-2026-05-12.md](docs/live-review-2026-05-12.md)
- 2026-05-13 生产故障段、Binance 专线修复与白名单恢复记录：
  - [docs/live-recovery-2026-05-13.md](docs/live-recovery-2026-05-13.md)
  - 当前白名单 IP、固定专线叶子、默认恢复检查命令，也继续维护在这份文档的 `2026-05-14 当前基线` 一节
- 归档的旧计划 / 细节推导：
  - [docs/archive/README.md](docs/archive/README.md)
  - 历史 live tuning 记录也已转入 archive

## 目录

```text
app logic: src/qount/
docs: docs/
prompts: prompts/
runtime state: state/
run scripts: scripts/
systemd examples: deploy/systemd/
```

## 下一步

这版已经把最小可用的 `candidate filter + cost-aware risk + review` 主链路接进来了，并补上了 futures 持仓详情、SL sizing、更细 review 切片、多次 partial take profit、breakeven stop，以及动态保护单刷新。下一步只应推进仍未启用的仓位管理执行层：

1. 加仓独立规则
2. 反手拆单执行

不要把这几类执行规则一次性上线；继续按 [docs/strategy-optimization-design.md](docs/strategy-optimization-design.md) 里的“后续未启用能力”顺序走；需要看旧详细推导时再查 [docs/archive/position-management-sizing-review-2026-05-13.md](docs/archive/position-management-sizing-review-2026-05-13.md)。
