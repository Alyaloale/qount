# L1-S2 个人载体重认证预登记

状态：原 `v0.1` 合同已冻结并被保留；在未读结果前，owner 已于 2026-07-30 创建仅取消 embargo
的 `v0.2` 继任合同并完成唯一一次评估。L1-S2 趋势信号未通过双基准 CAGR 门，现为
`terminal_passive_fallback`，不再允许重跑或生成趋势目标。

冻结信号是 L1-S2 最终的 21 ETF 周频趋势 ensemble：`{13,26,39,52}` 周回看等权合成、26 周
实现波动率反向定权、每周再平衡、单边成本 6bps。它绑定历史源提交
`ae6caeb2f2e18a55381a97c51dece72c6050d32d` 的 `l1_cross_asset.py` 内容哈希；不得替换为当前
13 ETF 默认面板、long-only、月度规则或任何新参数。

唯一变化是评价口径。策略需分别对以下两条基准都通过：

- 60/40：SPY 60% / TLT 40%，同一完成周锚点再平衡，单边成本同为 6bps。
- BTC 满仓：BTCUSDT 100%，初次进入后买入持有，单边成本 6bps。

每条基准在各自与策略共同可用的完成日期上比较：策略绝对最大回撤不得超过基准的一半，且几何年化
不得低于基准超过 2 个百分点。两条都过才算通过；失败直接接受“买入持有加再平衡”为 Sleeve 1
终态，不调参数、不扩 universe、不改变成本或基准。

输入读取前必须先固化 21 份 Tiingo 复权缓存与 BTC 日线缓存的路径、SHA-256、首末日期和行数；
网络下载被合同禁止。合同 artifact 为
`state/research_runs/20260727T163203Z-l1-personal-carrier-recertification-preregistration/l1_personal_carrier_recertification_preregistration.json`
（hash `05d46a2378d2adec4a96d9e8961a909941c45021f3a84f6de77bb54cae643a38`）。

继任 artifact 为
`/mnt/e/qount_data/qount/research_runs/20260730T075439Z-l1-personal-carrier-recertification-immediate-preregistration/l1_personal_carrier_immediate_recertification_preregistration.json`
（contract hash `9290d8eca609e7ef0f924fd3e580fbc9a5c27a4ee5fa5aeb97fdf1a3f2d56f9a`）。它只改变
`not_before_utc`，显式绑定原合同、声明 supersession 前未读结果，并保持信号、缓存、成本、基准、门槛和
`orders_authorized=false` 不变。评估工件 hash 为
`855564116065d8acfdb14ae6b9c94719b04b2b6387ea46db8f28f97d75e769bc`；60/40 与 BTC 基准均因
CAGR 门失败，终态 fallback artifact 为
`/mnt/e/qount_data/qount/research_runs/20260730T075544Z-l1-personal-carrier-recertification-research-intent/l1_personal_carrier_research_intent.json`。

该合同固定 `strategy_results_evaluated=false`、`orders_authorized=false`、`paper_or_live_allowed=false`；
它不授权券商、paper、live、FOMC 或 CPI 事件执行。

## 执行路径

以下 `v0.1` 命令和约束保留为原始证据，不得再以原合同或任何 successor 重跑；唯一 evaluation 与
`terminal_passive_fallback` 已在本文开头列出的 successor artifact 中完成并封存。

结果窗口开启后，只能使用已经存在的原始缓存运行：21 个 Tiingo 文件必须分别命名为
`tiingo_<TICKER>.json`，内容为 Tiingo 原始 EOD JSON 且使用 `adjClose`；BTC 必须是已封存的
UTF-8 CSV，表头包含 `date,close`，并配有来源归档清单。执行器会在计算前记录每个文件的绝对路径、SHA-256、行数和首末
观察日期，且验证 BTC CSV 与来源清单的哈希绑定；缺少任一文件即停止；它不下载、不拼接、不补尾数据。

当前已存在的 Binance BTCUSDT 日线归档可先封存为该输入。这个命令只消费本地 zip、检查日频连续性并写入来源哈希，
不读取策略结果：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/seal_l1_btc_daily_cache.py \
  --archive-dir state/r0_runtime/klines \
  --output-dir state/research_cache/l1_personal_carrier_btc_20260730
```

Tiingo 缓存只能在 embargo 到期前补齐。下面的准备器固定 21 标的与 `2010-01-01` 起点，只下载**缺失**文件，
绝不刷新、覆盖或扩展已有文件；它只写缓存完整性 artifact，不计算收益、权重或任何通过/失败读数。到
`2026-07-31T00:00:00+00:00` 后，`--download-missing` 会 fail closed：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/prepare_l1_personal_carrier_tiingo_cache.py \
  --preregistration state/research_runs/20260727T163203Z-l1-personal-carrier-recertification-preregistration/l1_personal_carrier_recertification_preregistration.json \
  --cache-dir state/research_cache/l1_personal_carrier_tiingo \
  --download-missing
```

运行前在 WSL 加载该节点私有 `.env` 中的 `QOUNT_TIINGO_API_KEY`；`Settings.from_env()` 不会自行读取文件。
密钥不进入源码、文档、artifact 或命令输出。完成后，保存的 preparation artifact 必须显示
`cache_complete=true` 和 `cached_tickers=21`。没有 `--download-missing` 时，它只是只读审计，可用于确认缺口。

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/run_l1_personal_carrier_recertification.py \
  --preregistration state/research_runs/20260727T163203Z-l1-personal-carrier-recertification-preregistration/l1_personal_carrier_recertification_preregistration.json \
  --tiingo-cache-preparation '<pre-embargo-tiingo-preparation-artifact>' \
  --tiingo-cache-dir '<sealed-tiingo-cache-dir>' \
  --btc-cache '<sealed-btcusdt-daily.csv>' \
  --btc-source-manifest '<sealed-btcusdt-source-manifest.json>'
```

输出已固定为一次性 research consumption ledger 下的 `evaluation.json`，并由同目录
`attempt.json` / `completion.json` 绑定预登记合同、pre-embargo Tiingo preparation
hash、冻结源 hash 和 evaluation hash。首跑只消费一次历史结果窗口；重复命令只验证并
回显同一 evaluation（`recalculated=false`），不会创建第二个结果目录。若进程在
`attempt.json` 后中断而没有 completion，必须保留现场并走人工研究治理复核，不能换缓存、
换时间戳或重跑。两条共同完成周窗口上的 CAGR、最大回撤、成本和通过/失败门结论即使都通过，
仍为 `research_pass_not_promotion`；若任一失败，则按合同接受“买入持有 + 再平衡”为
Sleeve 1 终态，不能通过改参数重跑。本次已消费，后续调用只会回显同一 artifact。

通过后才可构建下一期的研究目标，且仍然不产生订单。构建器会重新哈希全部封存输入，要求其与评估 artifact 完全一致；随后仅重算
冻结信号在最后一个完成周锚点的目标权重。它要求一个完整的研究场地能力记录才会解除 `blocked_venue_short_capability`，但无论记录是否完整
都保留 `orders_authorized=false` 与 `paper_or_live_allowed=false`：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/build_l1_personal_carrier_research_intent.py \
  --preregistration state/research_runs/20260727T163203Z-l1-personal-carrier-recertification-preregistration/l1_personal_carrier_recertification_preregistration.json \
  --evaluation '<sealed-successor-evaluation-artifact>' \
  --tiingo-cache-dir '<same-sealed-tiingo-cache-dir>' \
  --btc-cache '<same-sealed-btcusdt-daily.csv>' \
  --btc-source-manifest '<same-sealed-btcusdt-source-manifest.json>'
```

完整的策略边界、场地依赖、失败回退和 promotion 前提见
[`l1-personal-carrier-strategy-spec.md`](l1-personal-carrier-strategy-spec.md)。

冻结策略已可作为标准 registry 的 `research` 条目入库，但这个条目不在 production authority allowlist 中：

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/register_l1_personal_carrier_strategy.py \
  --preregistration state/research_runs/20260727T163203Z-l1-personal-carrier-recertification-preregistration/l1_personal_carrier_recertification_preregistration.json
```

该命令发布可验证的 `strategy_registration.json` 与 `strategy_registry.json`，状态固定为 `research`，不含
promotion artifact 或 owner authorization。因此 `validate_registered_intents` 只会在 `research` 环境接收该
策略 intent；`shadow`、`paper` 和 `production` 均会拒绝它。
