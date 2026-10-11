# Repository map

> **状态**：active｜**权威**：L3 repository reference｜**最后更新**：2026-10-11
> **适用范围**：目录职责、公开入口、部署引用与治理检查。
> **TL;DR**：生产控制面、活跃研究、冻结兼容、部署、文档和运行数据分层；基础清单由 `repository_hygiene.py inventory` 生成，研究职责表人工维护；不记录密钥或运行时值。

## Stable public entry points

- CLI: `qount-run` → `qount.main:main`; monitor: `qount-monitor` → `qount.mac_monitor:main`.
- Current fact source: [`../current.md`](../current.md). Operational navigation: [`../operations/host-runbooks.md`](../operations/host-runbooks.md).
- Main verification: `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -p 'test*.py'` (full suite); focused governance verification is documented in [`cli-and-scripts.md`](cli-and-scripts.md).

## Domain ownership

| Domain | Responsibility | Host / entry |
| --- | --- | --- |
| `src/qount/cli`, `contracts`, `execution`, `governance`, `ledger`, `risk`, `operations`, `notifications`, `persistence`, `portfolio`, `reporting`, `venue` | Public CLI composition, production control plane and shared contracts | VPS is runtime truth; Mac performs lightweight checks. |
| `src/qount/mini_trend`, `dual_engine`, `small_account`, `alpha_agents`, `research_data`, `research/sleeves`, `research/etf_trader`, `research/etf_alpha`, `research/dual_engine_*` | Active research or no-order simulations | Mac/WSL research; owner-designated P3 cloud is temporary compute; E holds final large artifacts. |
| `src/qount/legacy` and `scripts/archive` | Frozen compatibility and historical evidence | No new business logic or timer restoration. |
| `deploy/systemd`, `deploy/wsl`, `deploy/dual_engine`, `deploy/research`, `deploy/cloud` | Deployment templates and host topology | Static validation only without explicit host authorization; cloud research delivery is isolated. |
| `docs` | Current fact, rules, operations, reference and archive navigation | `docs/current.md` is the sole current fact source. |

## Inventory snapshot

以下为2026-10-03生成时的历史快照，文件数及Git状态不代表当前工作区。`inventory --write`会重写整页，包括人工维护的研究职责表；本次仅梳理职责表，不重新生成该快照。

Git status at generation time: `ignored=73, modified=6, untracked=60`.

| Category | Files scanned |
| --- | ---: |
| `active_research` | 527 |
| `deployment` | 52 |
| `documentation` | 206 |
| `legacy_compatibility` | 118 |
| `production_control_plane` | 466 |
| `runtime_data` | 4336 |
| `unclassified` | 16 |

Root-level review candidates are recorded in [`../archive/manifest.md`](../archive/manifest.md); candidates are not approved for movement or deletion merely by appearing there.

## Generated checks

`scripts/maintenance/repository_hygiene.py check` verifies relative Markdown links, environment-contract coverage, repository-owned deployment references, production-to-script import boundaries, required document metadata, manifest shape, and unclassified root files. It never accesses a remote host or reads secret values.

## G20/C60 offline research ownership

`research/q_div_pit.py` owns immutable indexed financial versions and rolling conditional sections, `q_div_history.py` the WSL/E evidence audit, and `q_div_cash.py` the separately tested raw-share/receivable/lot-tax accounting kernel. The kernel has explicit fee/tax policies and is not a qualified historical portfolio runner. `scripts/research/q_div_history.py` only parses/delegates. `research/c60_gradient_study.py` owns the independently frozen gradient comparison, `c60_gradient_verify.py` independent currency/unit/bisection accounting checks, and `scripts/research/c60_gradient.py` its thin adapter. Owning tests are `test_q_div_pit.py`, `test_q_div_cash.py`, `test_c60_gradient.py` and `test_c60_gradient_verify.py`. [Remediation evidence](../research-remediation-plan-2026-10.md).

`research/q_div_acquisition.py` owns budgeted Mac-only historical public acquisition, private-file credential loading, shared request pacing/retry and reuse of completed shards. `research/q_div_data_audit.py` independently verifies public-source bytes, paging and coverage on WSL/E. Thin adapters are `scripts/research/q_div_acquire.py` and `q_div_data_audit.py`; `q_div_public_sink.ps1` only receives/checks/writes declared public files on Windows/E. `research/q_div_sources.py` streams validated pages/inherited shards and explicitly hash-bound transport repairs into the historical financial index while preserving original fields/hashes and unknowns. Owning tests are `test_q_div_acquisition.py`, `test_q_div_data_audit.py` and `test_q_div_sources.py`. No credentials, private account APIs, strategy returns or scheduled services belong to this path.

`research/q_div.py` owns the separately frozen industrial-quality/dividend, single-factor IVOL, dated technical filters, capped target weights and exit predicates. `q_div_data.py` owns immutable public-response qualification and WSL/E snapshot screening, `q_div_report.py` the static review report, and `q_div_verify.py` independent bounded raw-input checks. `scripts/research/q_div.py` is a thin `price-screen` / `fundamental-screen` adapter. The historical portfolio execution engine is not yet connected; snapshots produce no returns or orders. [Q-DIV protocol](../ashare-q-div-ivol-study-2026-10.md).

`research/q_div_review.py` owns additive payment/fiscal-year/TTM diagnostics for the frozen Q-DIV candidates, and `q_div_review_report.py` their static HTML review. `scripts/research/q_div_review.py` is the thin WSL/E adapter; `test_q_div_review.py` verifies event clocks, units, duplicates, unknowns, source identity and fail-before-output guards. These modules do not modify frozen selection rules or produce returns.


`research/ashare_quality_momentum.py` owns the separately frozen industry-relative price-stability filter, MA60/120 trend and risk-adjusted momentum ranks, ten-session buffer, 18% trailing exit and full-session portfolio cooldown. It reuses frozen source/accounting helpers and preserves the liquidity control exposure caps. `scripts/research/ashare_quality_momentum.py` is its thin adapter; `test_ashare_quality_momentum.py` owns window, causal, selection, exit, cooldown and contract/gate fixtures.

`research/ashare_leader.py` owns exact-session technical-leader/trend/breakout selection, cost-basis close-confirmed initial/profit-trailing exits, 8-slot concentration and portfolio cooldown. It reuses frozen `ashare_strategy.Book` accounting; `scripts/research/ashare_leader.py` delegates and `test_ashare_leader.py` owns the causal/state fixtures. It does not certify fundamental industry leadership.

`research/ashare_lowrisk.py` owns the separately frozen low-volatility/uptrend ranking, MA200 exits, portfolio drawdown/cooldown and management snapshots, reusing `ashare_strategy.Book` accounting. `scripts/research/ashare_lowrisk.py` is a thin adapter; `test_ashare_lowrisk.py` owns its causal, buffer and cooldown fixtures.

`research/ashare_backtest_data.py` owns read-only original/retired exact-session price-proxy panels; `research/ashare_strategy.py` owns causal sector/momentum selection and synthetic capital/holdings/exit/cost simulation. `scripts/research/ashare_strategy.py` only delegates; owning fixtures are `test_ashare_backtest_data.py`, `test_ashare_strategy.py` and independent `test_ashare_strategy_review.py`. [A-share strategy line](../ashare-strategy-study-2026-10.md) remains separate from crypto, legacy and cash-return certification.


`research/ashare_sector_screen.py` owns exact-session price/liquidity features, explicit descriptor exclusions and the frozen sector/company queue. `scripts/research/ashare_sector_screen.py` is a thin adapter; `tests/test_ashare_sector_screen.py` owns window, gate, tie and no-lookahead fixtures. Financial/policy citations remain a separate research evidence overlay and never alter the immutable ranking.


`research_data/equity_archive.py` owns the independent user-equity ZIP structural audit: checksum/member boundaries, streaming CSV identity/date/price checks, adjustment coverage/anchor consistency and immutable E profiles. `scripts/research/equity_archive_audit.py` only parses/delegates; `tests/test_equity_archive.py` owns source/qualification tests. It generates no return labels, strategy intents or security recommendations. [Individual-equity study](../equity-selection-study-2026-10.md) defines the CN/US research expansion separately from old hourly and legacy studies.

The independent short-horizon line lives in `research/opportunity_screen.py` (closed-prefix signals, sparse acceptance, fixed labels, signed funding and hypothetical margin stress) and `research/opportunity_data.py` (official immutable archives, checksum-bound cache reuse, actual-import source binding and raw-source/cash verification). Shared sparse calendar-block statistics live in `research_data/event_stats.py`. `scripts/research/opportunity_screen.py` only parses/delegates; `tests/test_opportunity_screen.py` owns causal/gap/accounting/provenance tests. [Its primary study](../short-horizon-opportunity-study-2026-10.md) does not reuse G20/C60 or legacy A-share validation identity. A-share has a separate research-only synthetic price-proxy simulator; it has no financing or order authority.

These offline modules live in `src/qount/research/`; deployed paper implementations stay in `src/qount/dual_engine/`. [Study overview](../dual-engine-optimization-2026-10.md#研究总览与阅读路径) owns protocols/results; [configuration](configuration.md#g20c60-离线研究合同) owns frozen contracts; [CLI reference](cli-and-scripts.md#g20c60-research-studies) owns adapter parameters.

| Responsibility | Owning modules |
| --- | --- |
| Baseline, execution and independent verification | `dual_engine_optimization`, `dual_engine_execution_study`, `dual_engine_execution_verify`, `g20_drift_control`, `c60_execution_control`; shared exact fees in `research_data/replay_fees.py`. |
| Architecture, expanded public data and sources | `dual_engine_structural`, `dual_engine_expansion`, `dual_engine_expansion_data`, `dual_engine_nextgen`, `dual_engine_nextgen_data`, `dual_engine_regimes`, `dual_engine_regimes_data`, `dual_engine_breadth`. |
| Saved versions and conditional confirmation | `dual_engine_registry`, `dual_engine_confirmation`; all earlier descriptors, exclusions and receipts preserved. |
| Scoped settlement, clocks and profit/loss attribution | `dual_engine_books`, `dual_engine_clocks`, `dual_engine_holdings`; owned-unit and weight-only evidence remain distinct. |
| Vintage risk intents and financed capital books | `dual_engine_intents`, `dual_engine_capital`, `dual_engine_reform`; captured ownership, explicit transfers and gross per-book fees. |
| Recovery and closed-signal capital allocation | `dual_engine_recovery`, `dual_engine_redistribution`, `dual_engine_renewal`; warmup and all-cash initialization are part of accounting. |
| Information availability and target interventions | `dual_engine_information_data`, `dual_engine_sources`; causal settled funding/closed flow, snapshot qualification and macro exclusions. |
| Recovery ownership and delayed exposure control | `dual_engine_zonal_recovery`, `dual_engine_containment`, `dual_engine_zonal`; scoped acquisitions, source epochs and funded BIL sales. |
| Joint settlement and separate family refresh | `dual_engine_coordinator`, `dual_engine_family_clock`, `dual_engine_zorder`; source/budget coordination and declared full-book risk buys. |
| Closed path quality and three research objectives | `dual_engine_features`; causal quality sizing, matured descriptive labels, net closed-episode/monthly win rates, fixed de-risking control and independent cash/target verification. |
| Closed states and scoped transitions | `dual_engine_states`, `dual_engine_state_clock`, `dual_engine_states_verify`; causal own-history ranks, state sizing, asset-specific extra acquisitions, delayed event cancellation and independent cash/decision checks. Explicit clock fork preserves earlier engine snapshots. |
| Queue source ownership and repeat-acquisition costs | `dual_engine_ownership`, `dual_engine_acquisition`, `dual_engine_execution_ownership`, `dual_engine_ownership_verify`; explicit immutable engine forks, carried sparse source, latest-zero veto, local family recovery, small-buy suppression and independent book/cash verification. |
| New double-leg cashflow feasibility | `dual_engine_cashflow`, `dual_engine_cashflow_data`, `dual_engine_cashflow_qualification`, `dual_engine_cashflow_inputs`, `dual_engine_cashflow_mark_repair`, `dual_engine_cashflow_verify`; immutable official price archives, signed bounded funding, separate USDT collateral, paired closed episodes, full leg costs and independent raw-CSV/cash oracle. Diagnostic research only; WSL replay independently verified, monthly gross reset fails all four net-income cells. Source-only observed daily repair preserves unresolved stress coverage as unknown. |

Matching `scripts/research/dual_engine_*.py` files parse arguments, delegate to package functions and write declared artifacts. Owning tests are `tests/test_dual_engine_*.py`, `test_g20_drift_control.py`, `test_c60_execution_control.py` and `test_replay_fees.py`. Existing module paths and public CLIs are preserved; production packages do not import research adapters.

Mac holds code, docs and lightweight receipts; WSL performs isolated computation; Windows E retains full immutable datasets, cash/unit ledgers, holding episodes and version descriptors. Local `state/research_runs/` metadata is not a Git-delivered artifact collection. No research module grants service, paper promotion or order authority.

### A-share selection research ownership

`qount.research.ashare_selection` owns source/window qualification and pure fixed price/activity information primitives; `scripts/research/ashare_selection.py` only parses arguments and writes declared research artifacts. `qount.research_data.equity_archive` remains the shared immutable archive auditor. The [primary study](../equity-selection-study-2026-10.md) and [qualification contract](../../config/ashare-selection-qualification-20261009.json) define evidence and execution boundaries. No production package imports this research adapter.

`qount.research.ashare_tushare` owns credential-safe bounded same-source HTTP acquisition and response validation; `ashare_tushare.py` is the thin Mac CLI. `qount.research.ashare_source_reconcile` owns scope-bound field/application qualification, with no return labels. `qount.research.ashare_information` owns pure typed source guards, exact-session open labels, immutable membership/unknown accounting and gate aggregation. `qount.research.ashare_information_run` owns the WSL/E loader and single frozen conditional experiment; `scripts/research/ashare_information.py` is its thin adapter. Focused tests use synthetic fixtures only, including fail-before-read source guards, past-only windows and same-date factors. Neither a conditional interval nor a vendor price proxy certifies a portfolio, economic cash return or order authority.

`qount.research.ashare_supplement` owns bounded single-connection public retired-security source acquisition, raw pagination preservation and source profiles; `scripts/research/ashare_supplement.py` is its thin CLI. `qount.research.ashare_statistics` owns pure original-calendar maturity/purge/embargo masks and conditional moving-block mean intervals, with no market loader or real strategy runner. Their focused tests are `test_ashare_supplement.py` and `test_ashare_statistics.py`. Independent receipt reconciliation stays in the immutable research artifacts. Source supplementation never splices providers or certifies PIT/execution, and a conditional interval never resolves unknown labels by itself.

`qount.research.ashare_evidence` owns the fixed published-example, amount/volume-unit relationship and consecutive-session adjustment-reference source checks. `scripts/research/ashare_evidence.py` only parses/delegates; `tests/test_ashare_evidence.py` covers source identities, gaps, tolerances and host/fresh-output boundaries. The [evidence contract](../../config/ashare-selection-evidence-20261009.json) freezes diagnostics before source traversal. Algebraic matches never certify origin, and mismatches remain preserved without repair or financial labels. One-off public-source acquisitions and independent receipt reconciliation stay with the declared immutable research artifacts, outside production control paths.
