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

## 当前文档

- 当前仓库内只保留一份当前文档：
  - [docs/current.md](docs/current.md)
- 不再在仓库里保留：
  - 旧计划
  - 旧复盘
  - archive 文档入口
- 历史事实以后直接看：
  - `git log / git diff`
  - `WSL /home/alyaloale/Code/qount/state/qount.db`
  - 远端 `systemd` 和运行命令结果

## 当前 live 基线

- 生产节点：
  - `WSL /home/alyaloale/Code/qount`
- 调度：
  - `systemd --user qount-runner.timer`
- 交易模式：
  - `QOUNT_MODE=live`
  - `QOUNT_EXCHANGE_ID=binance`
  - `QOUNT_MARKET_TYPE=future`
- 当前交易对：
  - `SOL/USDT`
  - `XRP/USDT`
  - `BTC/USDT`
  - `ETH/USDT`
- 当前周期：
  - `QOUNT_TIMEFRAME=5m`
  - `QOUNT_CANDIDATE_TREND_TIMEFRAME=1h`
- 当前模型：
  - `QOUNT_AI_MODEL=gpt-5.4`
- 当前规则模式：
  - `QOUNT_RULE_MODE=bottom_line`

## 当前流程

1. closed `5m` bar -> `snapshot`
2. `candidate_filter` 做排序和标注
3. `AI` 选择 symbol 和 `buy/sell/hold/close`
4. `validate_decision` 只做 JSON / 字段规范化
5. `risk_engine` 在 `bottom_line` 下只保留底线约束：
   - 日亏损停机
   - 系统 halt
   - 风险仓位上限
   - 交易所最小名义
   - 最大持仓数
   - 方向暴露
   - 基本止损合法性
6. `executor` 执行并写入 `journal`
7. `review` / `signal-review` 负责复盘

## 当前判断

- `run_id>=2300` 是当前 `bottom_line` live 样本起点
- 最近样本已经证明：
  - `candidate_filter` 会把弱样本继续送进 AI
  - risk 不再用旧的启发式 veto 把 AI 意图压回 `hold`
  - 最近 `hold/noop` 主要先按 “AI 没看到足够 setup” 理解，而不是先怀疑 rule 层还在挡
- 如果你在复现 `docs/current.md` 里的窄 `ETH` 管理退出实验：
  - 不要只继承远端 `.env`
  - 要显式设置 `QOUNT_RULE_MODE=strict`
  - 否则你跑出来的会是 `bottom_line` 口径，只能看收益，不足以验证那些 `AI close` 窄规则是否生效

## 相关参数

- `QOUNT_ESTIMATED_FEE_PCT`
- `QOUNT_ESTIMATED_SLIPPAGE_PCT`
- `QOUNT_RULE_MODE`
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

## 当前文档入口

- [docs/current.md](docs/current.md)

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

下一步默认不再写阶段计划文档，直接在：

- [docs/current.md](docs/current.md)

更新当前结论；

如果要判断“系统没下单到底是 AI 保守还是市场没 setup”，直接查：

- `state/qount.db`
- `signal-review`
- 最新 `run_id`
