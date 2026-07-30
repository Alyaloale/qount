# L1 Personal-Carrier Rollout

> **Status**: terminal L1-S2 research outcome recorded; execution blocked.
> **Authority**: L1-S2 re-certification contract and strategy specification.
> **Last updated**: 2026-07-30.

## Decision

The direction is sound with one non-negotiable correction: a passed historical
re-certification proves neither execution readiness nor portfolio eligibility. The
frozen 21-ETF signal is now a standard Qount `research` strategy, while its future
weekly scheduler, IB/Binance coordination, and sleeve allocation remain separately
gated work. This preserves the useful parts of the existing infrastructure without
turning a research artifact into an order path.

## Current State

| Item | State | Consequence |
| --- | --- | --- |
| Frozen signal, evaluator, sealed inputs | Consumed once | Owner-directed successor evaluation failed both CAGR gates; terminal passive fallback is recorded. |
| Tiingo cache on Windows external data root | Complete | 21/21 raw JSON caches admitted on 2026-07-30 before embargo; audit hash `90de1634...284e21e8`. |
| Mac private `.env` Tiingo credential | Verified present | The invoking WSL process must explicitly load its own private `.env`; settings do not autoload it. |
| Standard strategy registration | Recorded | `l1_personal_carrier_frozen_s2@0.1.1` is in the shared registry as `research` only; no intent is admitted after the terminal fallback. |
| Separate passive allocation | Preregistered | `l1_passive_sixty_forty@0.1.0` fixes SPY 60%, TLT 40%, 0% strategic USD cash, and annual first-full-NYSE-session rebalancing; it is `research` only. |
| Execution authority | Blocked | No instrument map, borrow/financing model, broker order path, paper authority, or live authority exists. |

The Mac observation is not evidence about the Windows external drive. The authoritative
Phase 0 result is the WSL cache-preparation artifact, which must report all 21 tickers.

## Phase 0: Cache Intake and Seal

**Objective:** complete the fixed Tiingo cache before the result window opens, with no
strategy result read.

Run on WSL against the durable data root after loading that node's private `.env`:

```bash
set -a
source .env
set +a
PYTHONPATH=src ./.venv/bin/python scripts/research/prepare_l1_personal_carrier_tiingo_cache.py \
  --preregistration state/research_runs/20260727T163203Z-l1-personal-carrier-recertification-preregistration/l1_personal_carrier_recertification_preregistration.json \
  --cache-dir state/research_cache/l1_personal_carrier_tiingo \
  --download-missing
```

The preparer has four deliberately narrow properties:

- Fixed 21-ETF universe and fixed Tiingo history start date.
- Downloads only files that do not exist; it never refreshes an existing cache.
- Audits each raw JSON file for usable `date` and `adjClose`, plus its SHA-256,
  raw-row count, and observation range.
- Refuses all network intake at or after `2026-07-31T00:00:00+00:00`.

**Completed 2026-07-30T07:07Z on WSL/Windows external storage.** The preparation artifact is
`/mnt/e/qount_data/qount/research_runs/20260730T070736Z-l1-personal-carrier-recertification-tiingo-cache-preparation/l1_personal_carrier_tiingo_cache_preparation.json`.
Its embedded artifact hash and cache audit hash verified; `cache_complete=true`,
`cached_tickers=21`, and `invalid_caches=0`. The sealed BTC CSV and source manifest were
copied from Mac and SHA-256 matched byte-for-byte before cache collection. No evaluator
was run during this phase.

## Phase 1: Re-certification and Standard Research Entry

**Objective:** evaluate once, then record the only permitted result disposition.

**Completed 2026-07-30T07:55:11Z.** Before reading results, the owner-directed
`v0.2` successor preregistration superseded only the original embargo timing and retained
the frozen signal, costs, benchmarks, gates, cache admission, and execution prohibitions.
It is contract `9290d8ec...56f9a`, explicitly linked to the original `05d46a23...43a38`
contract. The single evaluation is sealed at
`/mnt/e/qount_data/qount/research_runs/l1-personal-carrier-recertification-consumption/9290d8eca609e7ef0f924fd3e580fbc9a5c27a4ee5fa5aeb97fdf1a3f2d56f9a/evaluation.json`.
Its `input_manifest_hash` is `0cdc138b...bfb649`; `evaluation_hash` is
`85556411...e769bc`.

| Benchmark | Trend CAGR / max DD | Benchmark CAGR / max DD | Gate result |
| --- | --- | --- | --- |
| SPY/TLT 60/40 | 1.06% / 13.35% | 9.88% / 26.76% | Drawdown passes; CAGR fails. |
| BTCUSDT buy-and-hold | 1.04% / 13.35% | 38.51% / 76.63% | Drawdown passes; CAGR fails. |

Both benchmarks must pass, so the only valid decision is
`accept_buy_and_hold_plus_rebalance_as_sleeve_1_terminal_state`. The resulting
`terminal_passive_fallback` artifact is
`/mnt/e/qount_data/qount/research_runs/20260730T075544Z-l1-personal-carrier-recertification-research-intent/l1_personal_carrier_research_intent.json`.
It has no `StrategyIntent`, no paper/live authority, and no replacement trend target.

The original `v0.1` contract would have opened on `2026-07-31T00:00:00+00:00`; the
owner-directed `v0.2` successor consumed its equivalent sealed inputs earlier and is now
terminal. Its CLI was offline by construction, hashed every input before calculating the
two fixed benchmark comparisons, and rejected any cache file differing from the preparation
artifact. Before opening a market cache it claimed a one-shot consumption ledger under
`research_runs/l1-personal-carrier-recertification-consumption/<contract_hash>/` using an
exclusive `attempt.json`. A completed call writes `evaluation.json` and `completion.json`
without replacement; later calls verify and return that exact evaluation with
`recalculated=false`. An interrupted `started` claim is terminal for automation and
requires a separately documented research-governance review; it must not be rerun with
another cache or timestamp.

The prepared WSL command was consumed exactly once by the successor contract:

```bash
cd /home/alyaloale/Code/qount
QOUNT_STATE_DIR=/mnt/e/qount_data/qount PYTHONPATH=src ./.venv/bin/python \
  scripts/research/run_l1_personal_carrier_recertification.py \
  --preregistration /mnt/e/qount_data/qount/research_runs/20260730T075439Z-l1-personal-carrier-recertification-immediate-preregistration/l1_personal_carrier_immediate_recertification_preregistration.json \
  --tiingo-cache-preparation /mnt/e/qount_data/qount/research_runs/20260730T070736Z-l1-personal-carrier-recertification-tiingo-cache-preparation/l1_personal_carrier_tiingo_cache_preparation.json \
  --tiingo-cache-dir /mnt/e/qount_data/qount/research_cache/l1_personal_carrier_tiingo \
  --btc-cache /mnt/e/qount_data/qount/research_cache/l1_personal_carrier_btc_20260730/BTCUSDT-1d-sealed.csv \
  --btc-source-manifest /mnt/e/qount_data/qount/research_cache/l1_personal_carrier_btc_20260730/BTCUSDT-1d-sealed-manifest.json
```

| Evaluation outcome | Required action |
| --- | --- |
| Either benchmark fails | **Actual result.** Terminal passive Sleeve 1 fallback recorded. Do not re-parameterize, rebuild a target, or promote the registry entry. |
| Both benchmarks pass | Not reached. Would only have built an order-free research intent, never an execution permission. |

The successor registration writes immutable `strategy_registration.json` and
`strategy_registry.json` artifacts at
`/mnt/e/qount_data/qount/research_runs/20260730T080032Z-l1-personal-carrier-recertification-strategy-registry/`.
Its identity is `l1_personal_carrier_frozen_s2@0.1.1`; `maximum_stress_loss_fraction=1.0` and
`maximum_gross=1.0` are intentionally fail-closed. Shared registry validation accepts
this strategy only in a `research` environment, never shadow, paper, or production.

## Phase 2: Weekly Research Signal Scheduler

**Objective:** operate a new-time, append-only observation stream, not an execution
daemon.

Blocked: Phase 1 ended in its terminal passive fallback. Preconditions for any distinct
future scheduler would be a new owner-approved research question, a new point-in-time data contract,
and a new forward preregistration. The scheduler must store each completed weekly input
manifest, target intent, decision time, data cutoff, and hash chain. A missing member,
late market close, source revision, cache mutation, or failed registry check produces no
intent. It must not call an allocator, order planner, broker adapter, paper executor, or
authority writer.

The separately preregistered passive policy is not that scheduler. It fixes the strategic
allocation, cash treatment, and annual calendar only; it deliberately emits no target or
intent and grants no schedule, paper, live, or broker authority. Its contract is documented
in [`l1-passive-allocation-preregistration.md`](l1-passive-allocation-preregistration.md).

Promotion from `research` to `frozen_candidate` requires a distinct promotion artifact;
the registry will reject a status jump.

## Phase 3: Cross-Venue Execution Coordination

**Objective:** design the IB traditional-assets and Binance crypto coordination boundary
without coupling their credentials or authorizations.

This phase begins only after each participating sleeve has independently completed its
promotion path to paper and has explicit venue/instrument capabilities. The coordinator
needs a common `InstrumentId` mapping, product capability, currency/cash ledger,
session-calendar treatment, broker-specific idempotency keys, fill/fee evidence, and
partial-failure halt/reconciliation rules. A single sleeve or venue cannot use the
coordinator to bypass its own authority state.

No paired or cross-venue order should be sent until both legs have an approved order plan
and the coordinator can halt on `UNKNOWN` fill state. The present L1 ETF sleeve has none
of these prerequisites, so Phase 3 is design work only.

## Phase 4: Three-Sleeve Portfolio Allocation

**Objective:** allocate only promoted sleeves through the existing `StrategyIntent` ->
allocator -> portfolio target -> risk decision contract.

The intended composition remains:

| Sleeve | Function | Authority at this stage |
| --- | --- | --- |
| 1 | Cross-asset trend / beta-risk management | L1 is research-only. |
| 2 | Event and forced-flow satellite | Independent research/paper gate. |
| 3 | Research pipeline | Zero real capital. |

Use separate `SleeveRiskBudget` limits, individual minimum notionals, gross caps, and
stress-loss assumptions before combining exposures. Do not net a non-executable ETF
target against a crypto sleeve; the existing allocator's sleeve-level minimum-notional
checks are specifically meant to prevent that. A portfolio-level promotion artifact,
interaction stress test, and owner authorization are required before paper or live
allocation.

## Immediate Checklist

1. Retain the verified cache-preparation artifact, one-shot receipt, evaluation, and
   terminal fallback; do not refresh or add cache data to reinterpret this result.
2. Do not run the L1-S2 evaluator again. Repeating the CLI only verifies the same sealed
   result with `recalculated=false`.
3. Do not build a replacement trend target, venue capability record, scheduler, paper
   plan, or promotion artifact from this failed signal.
4. The passive allocation is now separately preregistered. Any forward observation,
   target construction, scheduler, or execution work still needs its own evidence and
   authorization; none is a continuation of this consumed window.
