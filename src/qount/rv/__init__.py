"""RV-C: experimental hard-anchor relative-value line (项目线 C).

Isolated from the qount CTA research line (线 A) and from GRID-B (线 B, closed out).
See ``docs/rv-c-plan.md`` for the pre-registered v0.1 plan and discipline.

The first cut (H-RV) is a ``cash-and-carry`` on **dated quarterly futures**: long spot
+ short the quarterly COIN-M future, Δ≈0, harvesting the annualized basis premium. Unlike
H3's perpetual carry (line B, dead), the dated future is **contractually forced to converge
to spot at expiry** -- a real anchor, not a statistical estimate. This package reuses line
B's pure accounting primitives (``grid.perp``, ``grid.data`` parsers) without modifying
them, and lives entirely under ``src/qount/rv/``.
"""
