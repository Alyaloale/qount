# Sleeve 1 L1-S2 personal-carrier strategy specification

Status: terminal passive fallback recorded, execution blocked. This document completes the operating
contract around the frozen L1-S2 research signal. It makes no performance claim and
does not replace the result-free re-certification preregistration.

On 2026-07-30, the owner-directed embargo successor consumed the sealed inputs once.
The trend signal passed both drawdown comparisons but failed both CAGR comparisons, so its
only valid disposition is `accept_buy_and_hold_plus_rebalance_as_sleeve_1_terminal_state`.
No replacement target, paper run, execution plan, or promotion can be derived from it.

## Strategy identity

The strategy is the frozen 21-ETF cross-asset weekly trend ensemble from source commit
`ae6caeb2f2e18a55381a97c51dece72c6050d32d`. It uses the fixed universe
`SPY,EFA,EEM,TLT,IEF,LQD,HYG,GLD,SLV,DBC,USO,UUP,VNQ,IWM,EWJ,FXI,SHY,EMB,TIP,UNG,DBA`.
There is no long-only conversion, position cap, monthly conversion, overlay, parameter
search, or rebalance change in this strategy.

At each completed weekly anchor, calculate the equally weighted mean of the signs of
13, 26, 39, and 52-week trailing returns for every ETF. Divide each nonzero signal by
its realized 26-week weekly volatility, then normalize absolute weights to unit gross.
Hold the resulting target for one week and repeat. The replay and target builder charge
the frozen 6 bps per side target-weight turnover convention; no terminal liquidation
cost is invented for an unfinished holding period.

## Data and schedule

Only the 21 pre-existing raw Tiingo `adjClose` caches and the sealed BTCUSDT daily CSV
are admissible to the re-certification. Each evaluation records absolute cache paths,
SHA-256, row counts, and first/last observations before calculating metrics. The input
manifest must match byte-for-byte before a later research target can be rebuilt. Neither
the evaluator nor the target builder downloads, patches, or extends market data.

The historical re-certification is also consumed through a deterministic, no-overwrite
ledger keyed by its preregistration contract hash. The CLI writes `attempt.json` before
opening a market cache, then writes `evaluation.json` and `completion.json` only after
the fixed result has been calculated. A later invocation verifies and returns the sealed
evaluation instead of recalculating it. A `started` receipt without a completion record
is an interrupted one-shot study, not permission to retry; it requires a separately
documented research-governance disposition.

The target builder uses the final completed weekly anchor already represented in those
sealed inputs. It produces an order-free `StrategyIntent`, never an instrument mapping,
order plan, broker request, paper order, or live order.

The strategy has a standard registry identity
`l1_personal_carrier_frozen_s2` at SemVer `0.1.0`, but its initial registry status is
strictly `research`. The registry entry uses the re-certification contract hash, a full
loss stress bound, and unit gross only to make research artifacts compatible with the
shared contract model. It is not published to the production authority allowlist.

## Acceptance and fallback

The original `v0.1` re-certification was embargoed until `2026-07-31T00:00:00+00:00`.
Before reading results, its owner-directed `v0.2` successor superseded only that timing
and consumed the sealed inputs exactly once. The frozen strategy was required to
independently pass both comparisons on their own common completed-week windows:

- SPY 60% / TLT 40%, weekly rebalanced at the same anchors and using 6 bps per side.
- BTCUSDT 100%, bought once then held, using 6 bps for initial entry.

For each baseline, strategy maximum drawdown must be no greater than half of the
baseline maximum drawdown, and geometric CAGR may lag by no more than 2 percentage
points. Both must pass. A pass is only `research_pass_not_promotion`.

Any failure is terminal for this signal in Sleeve 1: accept long-only passive holding
plus periodic rebalancing. Do not rescue it by changing parameters, universe, costs,
rebalance frequency, benchmark, or a timing overlay. The separate passive allocation
now explicitly fixes `SPY` 60% / `TLT` 40%, a 0% strategic USD-cash target, and an
annual first-eligible-full-NYSE-session calendar. Its cash rule, missed-session handling,
and authority boundary are in [`l1-passive-allocation-preregistration.md`](l1-passive-allocation-preregistration.md).
It is a new result-independent contract, not a continuation or parameter change to this
consumed trend study.

## Venue and authority controls

The frozen signal can issue negative weights. Consequently, it requires a venue that
can carry both long and short positions for every member of the 21-ETF universe. A
cash-only ETF account is not a faithful implementation even if the current target has
no negative weight. The research-intent artifact always records
`requires_short_capability=true`.

A venue-capability record is acceptable for research review only when it identifies the
venue, records a SHA-256 evidence reference, is explicitly approved for research, and
attests to full-universe long and short support. Missing or incomplete evidence leaves
the target in `blocked_venue_short_capability`.

Even with a complete capability record, the output remains
`research_target_ready_execution_still_blocked`: `orders_authorized=false`,
`paper_or_live_allowed=false`, and its stress-loss field is deliberately 100% because
no carrier-specific execution-risk model is certified. It must not enter the portfolio
allocator or virtual runtime.

## Promotion prerequisites

Promotion needs a separate owner-authorized decision after all of the following are
available: point-in-time data controls, certified costs and financing/borrow treatment,
full venue and instrument mapping capability, new-time forward evidence, a defined
carrier risk model, sleeve-budget interaction testing, and explicit paper/live order
authority. None of these is implied by the re-certification, a research target, or this
specification.
