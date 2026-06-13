"""X4: experimental four-strategy crypto bake-off line (项目线 D).

Isolated from the qount CTA research line (线 A, frozen discipline), GRID-B (线 B, closed),
and RV-C (线 C, in progress). See ``docs/crypto-x4-plan.md`` for the pre-registered v0.1 plan.

Unlike B/C this line is **not a kill-test**: the owner relaxed it to a bake-off — design four
classic crypto strategies (grid / BTC-ETH pair / dual-SMA+Bollinger trend / vol-OI breakout) so
each backtests well, then run them on equal capital ($100k each) over the same forward tape and
compare. Fairness is the whole point: identical symbol / window / fee / capital / metrics.

This package reuses line B/C pure primitives (``grid.engine``/``grid.trend``/``grid.perp``,
``rv.basis``/``rv.stats``) without modifying them, and lives entirely under ``src/qount/x4/``.
"""
