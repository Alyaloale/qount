"""Primary ledger snapshot extractor for shadow accountant diff.

Reads the RuntimeLedger SQLite database directly (without importing
qount.ledger.store) and extracts positions, NAV, and cash events
into the dict format expected by diff_positions() and diff_nav().

The snapshot is read in a single read-only transaction using SQLite
URI mode=ro to guarantee no writes can occur.

Import boundary: this module must NOT import qount.ledger.store,
qount.ledger.reconciliation, qount.execution, or qount.mini_trend.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


_PRIMARY_SNAPSHOT_VERSION = 1


def extract_primary_snapshot(
    runtime_ledger_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Extract a primary ledger snapshot from the RuntimeLedger SQLite.

    Returns a dict with keys:

    * ``positions``: ``{symbol: {"quantity": float, "average_cost": float, "realized_trading_pnl": float}}``
    * ``nav``: ``{"equity": float|None, "realized_pnl": float|None, "unrealized_pnl": None, "funding": float|None, "commission": float|None, "transfer": float|None}``
    * ``cash_events``: list of ``{"event_type": str, "amount": float, "asset": str, "symbol": str, "occurred_at": str}``
    * ``unknown_order_count``: int
    * ``reconciliation_passed``: bool | None
    * ``reconciliation_halt_required``: bool | None
    * ``snapshot_version``: int

    Field mapping notes:

    * ``nav_marks.fees`` maps to ``nav.commission`` (diff_nav expects "commission").
    * ``nav_marks.trading_pnl`` maps to ``nav.realized_pnl``.
    * ``unrealized_pnl`` is not stored in nav_marks; it is set to None
      so diff_nav produces a "warn" (not "block") for that field.
    """
    path = Path(runtime_ledger_path)
    if not path.is_file():
        raise FileNotFoundError(f"primary_ledger_not_found:{path}")

    connection = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        positions = _extract_positions(connection)
        nav = _extract_latest_nav(connection)
        cash_events = _extract_cash_events(connection)
        unknown_order_count = _count_unknown_orders(connection)
        recon_passed, recon_halt = _extract_latest_reconciliation(connection)
    finally:
        connection.close()

    return {
        "snapshot_version": _PRIMARY_SNAPSHOT_VERSION,
        "positions": positions,
        "nav": nav,
        "cash_events": cash_events,
        "unknown_order_count": unknown_order_count,
        "reconciliation_passed": recon_passed,
        "reconciliation_halt_required": recon_halt,
    }


def extract_runtime_state(
    runtime_ledger_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Extract runtime state for HALT bypass observation.

    Returns a dict with:

    * ``unknown_order_count``: int
    * ``reconciliation_passed``: bool | None
    * ``reconciliation_halt_required``: bool | None
    * ``data_quality_blockers``: int (currently always 0; reserved for future)
    """
    path = Path(runtime_ledger_path)
    if not path.is_file():
        raise FileNotFoundError(f"primary_ledger_not_found:{path}")

    connection = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        unknown_order_count = _count_unknown_orders(connection)
        recon_passed, recon_halt = _extract_latest_reconciliation(connection)
    finally:
        connection.close()

    return {
        "unknown_order_count": unknown_order_count,
        "reconciliation_passed": recon_passed,
        "reconciliation_halt_required": recon_halt,
        "data_quality_blockers": 0,
    }


def _extract_positions(
    connection: sqlite3.Connection,
) -> dict[str, dict[str, float]]:
    rows = connection.execute(
        "SELECT symbol, quantity, average_cost, realized_trading_pnl "
        "FROM positions ORDER BY symbol"
    ).fetchall()
    return {
        row["symbol"]: {
            "quantity": float(row["quantity"]),
            "average_cost": float(row["average_cost"]),
            "realized_trading_pnl": float(row["realized_trading_pnl"]),
        }
        for row in rows
    }


def _extract_latest_nav(
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT equity, trading_pnl, funding, fees, transfers, residual "
        "FROM nav_marks ORDER BY marked_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return {
            "equity": None,
            "realized_pnl": None,
            "unrealized_pnl": None,
            "funding": None,
            "commission": None,
            "transfer": None,
        }
    return {
        "equity": float(row["equity"]),
        "realized_pnl": float(row["trading_pnl"]),
        "unrealized_pnl": None,
        "funding": float(row["funding"]),
        "commission": float(row["fees"]),
        "transfer": float(row["transfers"]),
    }


def _extract_cash_events(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT event_type, amount, asset, symbol, occurred_at "
        "FROM cash_events ORDER BY occurred_at"
    ).fetchall()
    return [
        {
            "event_type": row["event_type"],
            "amount": float(row["amount"]),
            "asset": row["asset"],
            "symbol": row["symbol"] or "",
            "occurred_at": row["occurred_at"],
        }
        for row in rows
    ]


def _count_unknown_orders(
    connection: sqlite3.Connection,
) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM orders WHERE status = 'UNKNOWN'"
        ).fetchone()[0]
    )


def _extract_latest_reconciliation(
    connection: sqlite3.Connection,
) -> tuple[bool | None, bool | None]:
    row = connection.execute(
        "SELECT passed, halt_required "
        "FROM reconciliations ORDER BY reconciled_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None, None
    return bool(row["passed"]), bool(row["halt_required"])
