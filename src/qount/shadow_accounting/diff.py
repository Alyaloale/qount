"""Diff shadow accountant results against the primary ledger.

This module compares the shadow accountant's independently rebuilt
positions and NAV against the primary ledger snapshot.  It only
reads the primary ledger snapshot for comparison -- it does not
import or reuse the primary ledger's aggregation implementation.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from qount.shadow_accounting.contracts import ShadowNavMark
from qount.shadow_accounting.contracts import ShadowPosition
from qount.shadow_accounting.contracts import ShadowReconciliationDiff


def _within_tolerance(
    primary: Any,
    shadow: Any,
    tolerance: float,
) -> bool:
    try:
        return abs(float(primary) - float(shadow)) <= tolerance
    except (TypeError, ValueError):
        return False


def diff_positions(
    shadow_positions: Mapping[str, ShadowPosition],
    primary_positions: Mapping[str, Mapping[str, Any]],
    *,
    quantity_tolerance: float = 1e-8,
) -> list[ShadowReconciliationDiff]:
    """Diff shadow positions against primary ledger positions.

    primary_positions is a dict mapping symbol -> {"quantity": float, ...}.
    """
    diffs: list[ShadowReconciliationDiff] = []
    all_symbols = set(shadow_positions) | set(primary_positions)
    for symbol in sorted(all_symbols):
        shadow_qty = shadow_positions.get(symbol, None)
        primary_qty = primary_positions.get(symbol, {}).get("quantity", 0.0)
        shadow_value = shadow_qty.quantity if shadow_qty else 0.0
        if _within_tolerance(primary_qty, shadow_value, quantity_tolerance):
            blocking = "pass"
        elif abs(float(primary_qty or 0) - float(shadow_value)) <= quantity_tolerance * 100:
            blocking = "warn"
        else:
            blocking = "block"
        diffs.append(
            ShadowReconciliationDiff.create(
                field=f"position_quantity:{symbol}",
                primary_value=primary_qty,
                shadow_value=shadow_value,
                tolerance=quantity_tolerance,
                blocking_level=blocking,
            )
        )
    return diffs


def diff_nav(
    shadow_nav: ShadowNavMark,
    primary_nav: Mapping[str, Any],
    *,
    equity_tolerance: float = 1e-6,
) -> list[ShadowReconciliationDiff]:
    """Diff shadow NAV against primary ledger NAV.

    primary_nav is a dict with keys like "equity", "realized_pnl", etc.
    """
    diffs: list[ShadowReconciliationDiff] = []
    fields = (
        ("equity", shadow_nav.equity, equity_tolerance),
        ("realized_pnl", shadow_nav.realized_pnl, equity_tolerance),
        ("unrealized_pnl", shadow_nav.unrealized_pnl, equity_tolerance),
        ("funding", shadow_nav.funding, equity_tolerance),
        ("commission", shadow_nav.commission, equity_tolerance),
        ("transfer", shadow_nav.transfer, equity_tolerance),
    )
    for name, shadow_value, tolerance in fields:
        primary_value = primary_nav.get(name, None)
        if primary_value is None:
            blocking = "warn"
        elif _within_tolerance(primary_value, shadow_value, tolerance):
            blocking = "pass"
        elif _within_tolerance(primary_value, shadow_value, tolerance * 1000):
            blocking = "warn"
        else:
            blocking = "block"
        diffs.append(
            ShadowReconciliationDiff.create(
                field=f"nav:{name}",
                primary_value=primary_value,
                shadow_value=shadow_value,
                tolerance=tolerance,
                blocking_level=blocking,
            )
        )
    if not shadow_nav.identity_verified:
        diffs.append(
            ShadowReconciliationDiff.create(
                field="nav:identity_verified",
                primary_value=True,
                shadow_value=False,
                tolerance=0.0,
                blocking_level="block",
            )
        )
    return diffs


def has_blocking_diff(diffs: list[ShadowReconciliationDiff]) -> bool:
    """Check whether any diff has blocking_level='block'."""
    return any(d.blocking_level == "block" for d in diffs)
