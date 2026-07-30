# Sleeve 1 passive allocation preregistration

> **状态**：preregistered / research-only｜**权威**：L3 研究合同｜**最后更新**：2026-07-30
> **本文回答**：Sleeve 1 被动 60/40 配置的冻结规则和系统边界。

Status: preregistered for research governance only. This is a separate policy from the
failed L1-S2 trend carrier. It has no `StrategyIntent`, scheduler, broker, paper, or live
authority.

The policy fixes the following choices without using the terminal trend evaluation to
add assets, tune weights, or change the calendar:

| Field | Frozen rule |
| --- | --- |
| Assets and weights | `SPY` 60%; `TLT` 40%. Long-only, unlevered, no substitutions. |
| Strategic cash | 0% USD cash target. USD is only an operational residual for rounding, fees, unsettled distributions, dividends, coupons, and external flows. |
| Cash deployment | Hold permitted USD cash until the next scheduled rebalance, then include it in portfolio value and restore 60/40. No signal-dependent cash allocation or intra-period deployment. |
| Rebalance calendar | Annually, using the first eligible full NYSE regular trading session on or after January 1. Observe after the official close; any future target is effective only on the next eligible session. |
| Closures and early closes | Skip them and use the next eligible full NYSE regular session. A missed rebalance follows the same defer rule. |
| Drift bands | None. There are no intra-year threshold or calendar exceptions. |

The 60/40 asset list was already present as a benchmark in the result-free L1-S2
preregistration (contract `05d46a2378d2adec4a96d9e8961a909941c45021f3a84f6de77bb54cae643a38`).
That provenance is recorded only to show the assets and weights were not selected from the
subsequent trend result; this is a new contract with an independent identity and authority
state.

The canonical contract also fixes USD as the base currency, excludes external cash flows
from strategy return, models no tax wrapper or tax-loss harvesting, and requires a new
preregistration if either ETF becomes permanently untradeable. It makes no historical
performance claim and does not authorize a historical evaluation.

## System boundary

`l1_passive_sixty_forty@0.1.0` can be recorded in the shared strategy registry at
`research` status only. The registry's full-loss and unit-gross bounds are deliberately
fail-closed placeholders, not a risk certification. `shadow`, `paper`, `production`,
portfolio allocation, venue mapping, order plans, and cron dispatch remain rejected until
separate promotion evidence and owner authorization exist.

The registration command seals its JSON document with no-overwrite, fsync-backed
publication and then writes the standard immutable registry artifacts:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/research/preregister_l1_passive_allocation.py
PYTHONPATH=src ./.venv/bin/python scripts/research/register_l1_passive_allocation_strategy.py \
  --preregistration '<sealed-passive-preregistration.json>'
```
