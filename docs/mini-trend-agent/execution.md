# MiniTrend Agent 执行手册

## Phase 0：只落设计，不碰生产

目标：

- 建本文档目录。
- 不改 VPS cron。
- 不改 `QOUNT_X4_LIVE_ENABLE`、`QOUNT_CXD_CARRY_ENABLE`。
- 不新增 live 权限。

完成条件：

- 文档可读。
- 方案不改变当前生产真相。

## Phase 1：实现最小 backtest

目标：

- 新增 `src/qount/mini_trend/` 的纯函数核心。
- 只支持 spot/long/cash。
- 400 USDT forward universe 固定 TOP3；TOP5 只保留为已完成的历史对照。
- 输出标准 artifact。
- 输出 scorecard。

最小实现顺序：

1. `config.py`
2. `signals.py`
3. `risk.py`
4. `execution.py`
5. `scripts/research/mini_trend_backtest.py`
6. `scorecard.py`

验证命令：

```bash
PYTHONPATH=src ./.venv/bin/python -m unittest \
  tests.test_mini_trend_signals \
  tests.test_mini_trend_risk \
  tests.test_mini_trend_execution \
  tests.test_mini_trend_scorecard \
  tests.test_mini_trend_backtest
```

最小 research backtest 入口：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/mini_trend_backtest.py \
  --start 2021-01 \
  --end 2022-12 \
  --output-dir state/mini_trend/research_runs/manual-2021-2022
```

验收口径：

- 同一输入重复运行结果 bit-for-bit 一致。
- 目标权重不因币种顺序变化而漂移。
- 小账户 min-notional block 被明确记录。
- 无任何 LLM 调用。
- scorecard 至少含 maxDD、fee/notional、order count、min-notional coverage。

通过线：

- 2021-2022、2023-2024、2025-2026 三段都能输出指标。
- min-notional coverage < 80% 时不能进入 paper，必须先缩 universe 或降目标 gross。
- 如果 BTC/ETH 因最小名义持续 blocked，不能进入 paper。

## Phase 1.5：冻结低频 forward monitoring

在读取 `2026-07-01` 后结果前先生成公开 spot rules 和 preregistration：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/alpha_agent_exchange_rules.py \
  --market spot --symbols BTCUSDT,ETHUSDT,BNBUSDT

PYTHONPATH=src ./.venv/bin/python scripts/research/mini_trend_forward.py \
  --preregister \
  --exchange-rules-path state/research_runs/<rules-run>/alpha_agent_exchange_rules.json
```

追加完成日线：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/mini_trend_forward.py \
  --run \
  --exchange-rules-path state/research_runs/<rules-run>/alpha_agent_exchange_rules.json \
  --preregistration-path state/research_runs/<prereg-run>/mini_trend_top3_forward_preregistration.json
```

门控：至少 60 根 forward、10 根 active、0 gap/blocked/schema/unmanaged、maxDD `<=15%`、
fee/notional `<=0.12%`。达到这些条件也只允许 paper-readiness review，不自动启动 paper；任何参数、
universe、short/leverage 或高频数据变更都必须另写协议。

## Phase 1.6：UM no-carry research branch

owner 指定后续资金架构为 USD-M futures wallet，carry 关闭；这只是 research contract，不改变 VPS。
`MiniTrend-UM-Recovery-v0.1` 的 preregistration 和 historical diagnostic 已生成，但因 1/3 段增量为正而
被拒绝，不能调参救援。UM base-trend v0.1 因未显式绑定实际执行的 3xATR 日线 stop，在尚未消费任何结果时
由 v0.2 preregistration `20260717T121646Z-mini-trend-um-base-forward-preregistration` 替代；freshness artifact
`20260717T121715Z-mini-trend-um-base-forward` 原始freshness为 `await_forward_data`（当时三币最新共同完成日线
`2026-06-18`）；WSL公开输入刷新现已把canonical UM共同日推进到`2026-07-17`，但冻结forward起点仍在其后，
下一次只追加 `2026-07-19` 起价格与funding均完整的日线，
不消费已看窗口。历史 benchmark decomposition 已完成但只标 `discovery_only`，不能替代 future OOS。
单变量 `vol_target=2.0%` risk-tier 已按预登记历史门拒绝：虽然全窗收益提高，但 2025-2026 收益低于
`-5%` 且回撤恶化超过 `5pp`；不进入 forward，不再做中间参数救援，UM base v0.2 的 1.5% 保持唯一候选。
UM研究强制使用真实`exchangeInfo` filters、funding、10bps+2bps成本、单日单批、
stop latch + cooldown、unknown-capital fail-closed。大批量数据若确需新增，只在Windows/WSL侧直落外置盘，
直连或仓库外配置的Liangxin Cloud proxy均可；不使用苏菲家宽代理，URL/token不进入repo。

Funding Veto只允许走独立双状态shadow。预登记
`20260717T162621Z-mini-trend-um-funding-veto-shadow-forward-preregistration` 固定从`2026-07-19`开始：此前
200根只作SMA/ATR warmup，Stop-Latch和Funding Veto都从400 USDT现金状态启动，不携带历史权益或仓位。
每个新完成日线必须保存双权益、收益组件、execution state、state hash、row hash与chain hash，首次同步后
仍继续。v0.2只允许评估价格连续且决策日/持有日TOP3各至少3次funding结算的完整前缀；月内funding未齐时
不得按0成本计算收益，CLI月份虽自动滚动但网络仍禁用。当前freshness
`20260717T162632Z-mini-trend-um-funding-veto-shadow-forward`为0根、`await_shadow_forward_data`。首次WSL
刷新artifact `20260718T081136Z-um-shadow-input-refresh-v02`已补齐93个公开归档文件，离线复跑
`20260718T080849Z-um-funding-veto-shadow-forward`共同最新日为`2026-07-17`，仍早于起点且0根；当月funding
公开REST直连0/3可达，故刷新层显式`await_complete_shadow_input_transport`，没有填0。至少60个
结果pair、双路径各10 active、1次veto、candidate funding coverage=1.0且所有审计门通过后，也只允许shadow
evidence review，不进入paper/live。

## Phase 1.7：一个月小资金UM实盘readiness

2026-07-18 owner提出一个月小资金实盘方向。当前只生成readiness，不部署、不arm、不下单。真钱候选固定为
Base v0.2；全局2.0%风险档是首选收益shadow，Funding Veto是次级shadow，二者都不能控制真钱订单。旧X4/C×D
的7币、short、2x、carry和5分钟cron全部禁止复用。

冻结试点合同：`capital=300 USDT`、30天、TOP3、long/cash、1x逐仓、one-way、gross<=1、日线单批。
不设置账户级单日止损；保留逐币3xATR吊灯止损和3根完成日线冷却，试点权益从峰值累计回撤达到10%时
flatten后halt且不得自动恢复。API key只能有USD-M交易权限、必须关闭提现并绑定VPS IP。
未知余额/仓位、非TOP3或short仓位、错误模式、重复决策、缺价格/funding journal均直接halt。

VPS审计结果：cron和qount交易进程均关闭，旧通用live guard已关闭。直连Binance公共接口可用，旧显式代理
不可用；绕开代理后旧API key返回`-2015`，无法审计资金/仓位/one-way。readiness v0.3补齐Futures/IP权限、
余额、空仓、open orders、7天dry-run与独立runtime验证门；最终artifact
`20260718T100615Z-um-live-pilot-readiness-v04`有20项blocker，
`live_orders_allowed=false`。已加入每日
append-only JSONL，记录权益、钱包、双权重、订单意图/结果、funding/费用、执行状态和risk flags；row/chain
hash不闭合或重复决策日时拒绝追加。启动顺序固定为：

1. owner确认精确本金和30天开始日。
2. 新API key通过私有预检，并确认无未管理仓位、one-way、TOP3 1x逐仓。
3. 构建并验证不复用X4/C×D的独立MiniTrend UM runtime。
4. 完成60个forward pair/10 active、30天paper、7天dry-run和完整funding journal。
5. 写可执行rollback，关闭旧live guard，安装独立每日cron但保持新开关off。
6. 再次只读预检后，由owner单独确认manual final arm。

## Phase 2：paper forward

目标：

- 每日收盘后跑一次 paper。
- 写 `state/mini_trend/paper/latest.json` 和 `snapshots.jsonl`。
- 用内部撮合，不接私有 API。

验收口径：

- 连续 30 天无 state schema 破坏。
- 每次 bar 日期单调递增。
- 费用、滑点、min-notional 全入账。
- paper 订单和目标权重可回放。
- stop latch 模拟触发后，0 次同日线信号立即重开。

禁止：

- paper 阶段不接 API key。
- 不把 paper 结果写入 X4 live state。
- 不因为 1-2 周收益好就 live。

当前实现（2026-07-18）：

- `src/qount/mini_trend/pilot_paper.py`与`scripts/desktop/mini_trend_um_paper.py`已落地独立UM paper replay。
- 固定Base v0.2、300 USDT全现金、200根signal-only warmup；只消费连续日线和每币每日3次完整funding。
- 复用3xATR吊灯、3根冷却、35% deadband和gross<=1；无账户单日止损，10%试点累计回撤会写halt flag并停止
  Base路径。
- paper runtime v0.3在同一完成日线中并行记录Risk 2.0%与Funding Veto的权益、目标权重、费用、funding、
  止损/冷却状态和回撤；shadow只读，不产生或改变Base订单意图。
- append-only pilot journal复用row/chain hash；相同输入复跑只追加缺失日期，历史replay hash变化直接拒绝。
- CLI没有live模式，不读取私有账户，也没有任何order endpoint。
- 当前外置盘artifact `20260718T102907Z-um-pilot-paper-v03`只读229根canonical输入；最新日
  `2026-07-17`早于冻结起点`2026-07-19`，因此0 pair、0 paper day、0 journal row，仍为
  `await_paper_inputs`。artifact SHA-256为`43c085d9...6e23`，manifest content hash为
  `c024dac1...d213`；零天报告已固定两条shadow的300 USDT起始状态，但当前未部署timer，不能开始计算30天
  paper门。

## Phase 3：dry-run 对账

目标：

- 读真实账户、交易规则、余额、仓位。
- 生成 live 订单计划但不发单。
- 检查交易所 filters 和本地规则一致。

建议命令形态：

```bash
QOUNT_MINI_TREND_MODE=dry \
PYTHONPATH=src ./.venv/bin/python scripts/desktop/mini_trend_live.py
```

验收口径：

- 连续 7 天 dry。
- dry 输出含 `would_place_orders`。
- 余额不足、min-notional、dust 都明确 block。
- 交易所未知规则时 fail closed。
- 本地 state 和交易所仓位不一致时 block，而不是自动猜。
- filters / balances / positions 读取失败不得生成可执行订单计划。

## Phase 4：小额 live pilot

前置条件：

- paper 至少 30 天。
- dry 至少 7 天。
- stop latch 已有单测和模拟触发案例。
- API key 禁提现，初期不启用 Universal Transfer / Earn / COIN-M。
- live pilot capital固定为300 USDT；不得自动扩容。

当前UM live pilot默认：

```text
market=um
direction=long_cash
margin_mode=isolated
position_mode=oneway
exchange_leverage=1
short_gate=false
carry=false
vol_target=0.015
rebalance_band=0.35
max_daily_loss_pct=disabled
max_pilot_drawdown_pct=0.10
halt_on_unmanaged_position=true
llm_runtime_gate=false
```

升级条件：

- 连续 30 天无 unmanaged position。
- 0 次 stop 后同信号立即重开。
- realized fee / notional 与预期一致。
- 订单数、blocked symbols、dust 均在日报中可解释。

## Phase 5：扩容

只有账户超过阈值才打开复杂度：

| 账户规模 | 允许变化 |
| --- | --- |
| `<600 USDT` | 当前 owner 架构：UM wallet + TOP3 long/cash research-only；不 carry、不 short、不加杠杆 |
| `600-1000 USDT` | 仍只允许已登记的 UM base control；扩 universe 需要新协议 |
| `1000-2000 USDT` | 只有独立 scorecard 通过后才评估低 gross 扩展；不自动放开 short |
| `>2000 USDT` | 仍不自动恢复 carry；任何新复杂腿都要 owner 明确授权和新 preregistration |
| `>3000 USDT` | 才可另行评估自动再平衡和 Universal Transfer |

扩容不是自动动作。每跨一档都要重新跑 backtest / paper / dry 的 scorecard。

## 回滚

任何 live 异常先执行：

1. 停 cron。
2. 导出交易所持仓、open orders、fills。
3. 取消本策略 open orders。
4. 人工决定是否平仓。
5. 写 audit artifact。

禁止用脚本自动“修复”未知仓位。未知仓位只允许进入 `halted`。
