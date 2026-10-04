# CLI and scripts reference

> **状态**：active｜**权威**：L2 stable interface reference｜**最后更新**：2026-10-04
> **适用范围**：公开 CLI、脚本分类、只读验证和禁止的 legacy 入口。
> **TL;DR**：`qount-run` 与 `qount-monitor` 是稳定公开入口。`main.py` 是兼容门面，参数定义由 `src/qount/cli/` 注册；完整参数以 `qount-run --help` 为准。

## Public commands

| Command | Input / output | Safety status |
| --- | --- | --- |
| `qount-run config-check --profile {mac,wsl,vps} [--env-file PATH]` | Env key names and value-free JSON report | Read-only; no network or state writes. |
| `qount-run --help` | Current command registry and supported arguments | Read-only. |
| `qount-run healthcheck`, `runtime-status`, `paper-status`, `dashboard-snapshot` | Runtime diagnostic JSON | May contact configured services; do not use as an authorization mechanism. |
| `qount-run backtest`, `walk-forward`, `strategy-selection-scan`, `l*-*-scan` | Declared research artifacts | Research-only; choose a documented artifact directory. |
| `qount-monitor` | Local monitoring interface | Preserve existing behavior and host boundary. |

The historical `cta-paper-sim` command remains a compatibility delegation to `qount.cta_sim`; it is not a newly supported production surface.

## CLI ownership

`qount-run = qount.main:main` remains unchanged. Its code is intentionally split by responsibility:

| Location | Responsibility | Compatibility rule |
| --- | --- | --- |
| `src/qount/main.py` | Early `cta-paper-sim` delegation, safe configuration preflight, settings/profile setup and command dispatch | Do not rename the public entry point or alter exit behavior incidentally. |
| `src/qount/cli/registry.py` | Active parser registration and small parser-only helpers | Add or change command arguments here, with parser tests. |
| `src/qount/cli/legacy_research.py` | Frozen L1/L3/L4/L6 parser compatibility | Keep commands parseable for reproducibility; do not treat visibility as permission to revive a line. |

New command behavior belongs in a testable package function. A CLI module should only define arguments, validate local combinations and pass values to that function.

## Script domains

| Directory | Role | Rule |
| --- | --- | --- |
| `scripts/operations/` | Deployment/runtime thin adapters | Parse arguments, call package functions and write only declared artifacts. |
| `scripts/research/<line>/` | Active research thin adapters | No production import of these scripts. |
| `scripts/maintenance/` | Repository/metadata maintenance | `repository_hygiene.py` is read-only except explicit generated-map writes. |
| `scripts/archive/` | Frozen historical scripts | Do not run, install or restore timers from these paths. |
| `scripts/desktop/` | Existing MiniTrend operations compatibility surface | Do not use it to re-enable live, arm, timer or cron. |
| `scripts/hosts/` | Mac-side compute-host connection helpers | `qount-wsl.sh [status\|ensure\|shell]` self-heals Mac→WSL SSH; compute hosts only, never VPS/production. |
| `scripts/sync-to-wsl.sh`, `scripts/run-wsl-tests.sh` | Explicit WSL code sync / remote unittest | Default `QOUNT_WSL_HOST=qount-wsl` (direct SSH into WSL, 2026-09-30); run `qount-wsl.sh ensure` first. |

## ETF Trader historical research adapters

- `scripts/research/etf_trader_download_history.py` writes public source JSON, canonical CSV and a source/hash manifest to an explicit data root; credentials are not inputs.
- `scripts/research/etf_trader_backtest.py` is the canonical adapter to `qount.research.etf_trader.historical_backtest`. Required inputs are repeated `--checkpoint`, a complete `--data-root`, and a new `--out` directory; `--start` / `--end` select the evaluation window. The old `--warmup` option is removed.
- `etf_trader_backtest_full.py`, `etf_trader_backtest_real.py`, `etf_trader_backtest_nopandas.py`, `batch_backtest_full.sh` and `batch_backtest_p2.sh` preserve their existing paths and delegate to the same frozen comparison workflow.
- Outputs are research artifacts, including the contract, checkpoint copies, action/curve CSVs, results and SHA256 manifest. No order or production service action is performed. Exact tested commands, limitations and storage paths are in the [P2 research document](../p2-project-summary-20261002.md#代码产物与复现).

## ETF P3 M0/M1 and public-data adapters

- `scripts/research/etf_alpha_preserve_p2.py` registers the existing P2 historical/provenance/recovery/data manifests, checks all declared hashes, validates saved model tensors on CPU and writes a new partial baseline registration. Required paths: `--historical`, `--provenance`, `--recovery`, `--data-root`, `--out`, `--repo`; `--mac-inventory` binds a separate public-source inventory. It performs no historical model inference or training.
- `scripts/research/etf_alpha_prepare.py` freezes the M1 protocol, features, next-open labels, purged folds, regimes, seeds, metrics and fixed baseline rules. Required paths: `--data-root`, `--baseline-manifest`, `--dataset-out`, `--out`, `--repo`; `--fixture-validation` binds an actual prior test receipt. It writes masks, event-based data and descriptive baseline diagnostics; its `D_gate` result controls research qualification, not production permissions.
- `scripts/research/etf_alpha_supplement.py` acquires allowlisted public issuer/calendar/fee sources, writes classified raw snapshots, retrospective normalized tables and reconciliation/qualification audits. Required paths: `--data-root`, `--out`, `--repo`; `--end` fixes the research cutoff. Optional `--source-cache` accepts an immutable public-source dataset, verifies its hashes and retains actual source observation times. Source errors remain failed/quarantined; unknown fees are null rather than zero. [Storage and qualification contract](../etf-p3-research-plan-2026-10.md#15-公开数据补采存储与资格分类2026-10-02).
- `scripts/research/etf_alpha_train.py --contract config/etf-alpha-overnight-20261003.json --out /mnt/e/qount_data/qount/artifacts/etf_alpha_p3/NEW_RUN` runs the authorized Stage 1 schedule. It checks the mounted E drive, frozen input hashes, common causal partitions and RTX4060 before preparing all folds on CPU. One GPU fit reuses resident tensors across seeds; two bounded diagnostic threads calculate validation reports. The contract fixes float32/no AMP, architectures, seeds, 224-fit ceiling and an eight-hour wall-clock ceiling. SIGTERM/deadline saves partial checkpoints; the original proposal is preserved as a historical approval snapshot.
- Training writes `status.json`, `events.jsonl`, per-epoch history, best/last checkpoints, predictions, IC/calibration reports and 1×/2×/3× no-order curves. Selection and seed extensions finish before `selection-freeze.json` unseals outer tests. `summary.json`, environment locks, source snapshot and a hash manifest describe completed/partial/failed results. The script never changes services or resumes P2/cloud jobs.
- `scripts/research/etf_alpha_report.py --input-run RUN --out NEW_REVIEW` verifies the completed run's declared hashes and writes `REPORT.md`, `validation-leaderboard.csv`, a source-manifest reference and its own immutable manifest. It does not fit/select models or modify the original run. Partial runs remain labelled partial and omit complete outer-test conclusions.
- `scripts/research/etf_alpha_analyze.py --input-run COMPLETED_V2_RUN --out NEW_ANALYSIS [--samples 400]` reads hash-bound predictions, reproduces original ledgers, attributes profit and perturbs validation selection with synchronous date blocks. `--identity-probe` instead performs CPU inference on frozen embeddings and checks the validation ensemble ledger. Both require a new E artifact directory and write a manifest; no fitting, source-run changes or formal PBO/DSR. [Methods](../etf-p3-research-plan-2026-10.md#21-负对照归因选模稳定性与下一轮训练方案2026-10-03). The residual pilot JSON remains a historical plan snapshot; the separate implemented R3 adapter is described below.
- `scripts/research/etf_alpha_expand.py --contract config/etf-alpha-expanded-20261003.json --out NEW_RUN --dataset-out NEW_DATASET [--reuse-bootstrap]` is the P3 v2 adapter. The owner-authorized WSL run retains `max_hours=null`, manual stop and fixed per-fit budgets; its runtime phase is recorded in `status.json`. The default WSL profile uses24 CPU-only workers before one CUDA trainer; an explicit cloud profile checks that host's quota, mount and3080Ti instead. `--reuse-bootstrap` verifies a fully published source/NumPy/input/causal/layout/hash-bound dataset rather than generating a second copy. Seven configurations ×seven folds ×five seeds plus fourteen Ridge/shuffle fits give259 fits; all selections freeze before all-family discovery reports. Fresh outputs stay under the declared profile's `etf_alpha_p3` roots. [Protocol](../etf-p3-research-plan-2026-10.md#19-结果复盘与大规模增强训练2026-10-03).
- `scripts/research/etf_alpha_residual.py pack/prepare/check/status` handles the public R3 delivery and numerical/data readiness without fitting. `launch/run --ready READY --authorization NEW_OWNER_ACTIVATION.json --out NEW_RUN` requires the later owner start instruction bound to frozen fingerprints. No authorization means exit2 before GPU/run creation. `prepare` freezes16 causal data slots, checks exact original outer execution dates and zero same-date null pairs, and probes unchanged CUDA weights with zero optimizer steps. The CLI only delegates to `residual_runtime.py/residual_run.py`; it preserves `qount-run/qount-monitor` and older research adapters. [Deployment and activation](../../deploy/wsl/alpha-residual/README.md).
- R3 completes a51-fit pilot first; no increment means `pilot_no_increment`, a normal exit0 with outer withheld. Otherwise153 inner fits freeze all choices/epochs before119 final fits, at most272 including pilot. Status/events/checkpoints/curves and sibling supervisor log/PID/exit receipts persist; SIGINT/SIGTERM saves partial work and exits. No scheduler, auto retry/restart or wall-clock ceiling. A ready engine is not a training authorization.
- Current R3 preparation uses `config/etf-alpha-residual-reviewed-20261003.json`: schema-v2 adds a25-session minimum null date shift and preserves close decisions across annual ledger boundaries. Its original proposal and schema-v1 contract remain frozen. CLI arguments and51/272-fit limits are unchanged; [P3 §23](../etf-p3-research-plan-2026-10.md#23-r3开训前复审修正与创新取舍2026-10-03) records the review. Read the stable ready pointer and run `check` again before activating a future run.
- `scripts/research/etf_alpha_residual.py status --path RUN` reads a launched run's progress; `status --path READY` reads only its preparation snapshot. Resolve the current run from `state/research_runs/etf_alpha_residual/latest-run.json` and inspect sibling `.exit.json` for final status. A `pilot_no_increment/exit_code=0` result is the registered pilot stop condition; it does not authorize a new run or an automatic retry. [Pilot diagnostics](../etf-p3-research-plan-2026-10.md#24-r3残差pilot执行与结果2026-10-04).

- `scripts/research/etf_alpha_cloud.py` supplies `pack/export-inputs/verify`, read-only `inspect`, and authorization-gated `prepare/benchmark/run`, plus manifest-checked result `collect`. The deterministic code package contains only public allowlisted source/config/tests/deployment instructions; a separate input export preserves the registered frozen manifest. CPU-only prepare and GPU training remain separate; calibration uses synthetic tensors and fixed batch/precision. The3080Ti cloud contract remains paused and blocks cloud computation; WSL authorization does not resume it. Neither contract automatically restarts tasks when connectivity returns. [Interfaces](../../deploy/cloud/alpha-3080ti/README.md), [cost/performance strategy](../etf-p3-research-plan-2026-10.md#20-3080-ti-付费云计算交付与性能策略2026-10-03).
- Original WSL adapters require mounted `/mnt/e/qount_data/qount`; the expanded/cloud adapter requires its explicit declared mount/root. Full arrays and curves stay on E or owner-authorized cloud scratch, with final cloud results returned to E. They never source an environment, accept credentials, connect a broker or change services. P2 and the public CLI remain compatible.
- Implementation and qualification evidence: [P3 plan, M0/M1 execution record](../etf-p3-research-plan-2026-10.md#14-m0m1-执行记录2026-10-02). Prediction training and the later Alpha/portfolio experiments have separate entry points still to be implemented.

## Synthetic engine generation and training

- `scripts/research/etf_trader_worlds.py` is the CPU-only adapter to `qount.research.etf_trader.worlds`. `--worlds` is the total world count; `--workers 0` selects the available CPUs, bounded by the number of shards. `--shard-worlds` fixes the dataset partition independently of worker count. The native library is built before workers start; workers limit BLAS threads when `threadpoolctl` is present, use `spawn`, and write NPY shards directly without sending full arrays through IPC.
- `--out` must be a new dataset directory below the mounted `/mnt/e/qount_data/qount/datasets/etf_trader/`. `--estimate-only` works locally without writes/compiler/GPU; `--resume` validates the exact config, source, NumPy, host and native build contract, keeps verified finished shards and rebuilds unfinished shards; corrupted finished shards fail. `--verify` checks a completed dataset without generating anything. A completed manifest is published only after every shard hash/layout passes.
- `scripts/research/etf_trader_train.py --world-dataset PATH` verifies and reads those worlds using mmap and one bounded prefetch thread. It never starts generation workers, silently reuses worlds, or regenerates missing data. The dataset must be `train` split, have the same account/durations/plausibility config and contain at least `episodes × batch-worlds` worlds. Model seed and dataset seed may differ and are recorded separately, allowing several model seeds to use the same frozen inputs.
- Dataset training requires a fresh model output directory and fails if CUDA is requested but unavailable. `--warmup-years`, `--plausibility-years`, `--compile-mode` and `--no-compile` make the contract explicit. GPU transfers use pinned memory, an explicit device copy stream, consumer stream dependencies and allocation lifetime tracking. Transfer timing is enqueue time, not a claimed DMA benchmark.
- Compilation uses the original model's forward callable plus stateless construction/cost callables; checkpoints keep the original `Trader` keys. `reduce-overhead` maps to `default`, and `max-autotune` maps to `max-autotune-no-cudagraphs`, because recurrent BPTT retains earlier forward tensors. Each callable records pending/active/fallback/disabled status and compile errors; CUDA uses fused Adam, with unchanged objective/risk coefficients. `--pipeline` delegates to this shared runtime and returns the canonical meta/history/lambda/checkpoint schema. Existing callers without `--world-dataset` retain the online generator compatibility path.
- These commands are engineering/research tools, not approval for P3 fitting or recovery of the stopped P2/cloud runs. Small fixture verification and current training authorization are recorded in [the active P3 plan](../etf-p3-research-plan-2026-10.md#17-研究引擎工程cpu-生成存储与-cuda-运行时2026-10-03) and `current.md`.

## Focused checks

```bash
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py inventory --write
PYTHONPATH=src ./.venv/bin/python scripts/maintenance/repository_hygiene.py check
PYTHONPATH=src ./.venv/bin/python -m unittest tests.test_config_contract tests.test_cli_registry tests.test_repository_hygiene
PYTHONPATH=src ./.venv/bin/python -m compileall -q src scripts/maintenance
qount-run --help
```

For package layout changes, use the full repository command from [local development](../operations/local-development.md). Deployment changes receive static `systemd`/shell reference validation only until the owner explicitly authorizes VPS work.
