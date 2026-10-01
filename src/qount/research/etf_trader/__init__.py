"""Research-only cross-market ETF expert trader (proposal v4.1).

Design: ``docs/etf-imitation-policy-design-2026-09.md``.  Everything in this package is
simulation code for generated worlds; it never reads accounts, emits StrategyIntent or
orders, and does not consume trials.  Only ``policy`` (not yet written) depends on torch.
"""

RESEARCH_GUARDS = {
    "research_only": True,
    "orders_authorized": False,
    "trial": False,
}
