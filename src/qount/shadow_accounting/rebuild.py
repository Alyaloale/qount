"""Pure functions to rebuild positions and NAV from raw exchange responses.

These functions are intentionally independent of qount.ledger position
aggregation.  They take raw Binance USD-M trade and income responses
and rebuild positions, cost basis, and NAV from first principles.

Import boundary: this module must NOT import qount.execution,
qount.mini_trend.pilot_dispatcher, or qount.ledger.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

from qount.contracts.hashing import canonical_hash
from qount.shadow_accounting.contracts import ShadowCashEvent
from qount.shadow_accounting.contracts import ShadowCoverageWindow
from qount.shadow_accounting.contracts import ShadowNavMark
from qount.shadow_accounting.contracts import ShadowPosition


def _parse_amount(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ms_to_iso(ms: int | float | str) -> str:
    try:
        timestamp = dt.datetime.fromtimestamp(
            int(ms) / 1000.0, tz=dt.timezone.utc
        )
        return timestamp.isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _classify_income_type(income_type: str) -> str:
    mapping = {
        "COMMISSION": "commission",
        "FUNDING_FEE": "funding",
        "TRANSFER": "transfer",
        "REALIZED_PNL": "realized_pnl",
    }
    return mapping.get(income_type, "unknown_income")


def rebuild_positions(
    trades: Sequence[Mapping[str, Any]],
) -> dict[str, ShadowPosition]:
    """Rebuild long-only average-cost positions from raw trade responses.

    Each trade is a Binance USD-M user trade dict with at minimum:
      symbol, side ("BUY"|"SELL"), price, qty, commission, realizedPnl, time

    Returns a dict mapping symbol -> ShadowPosition with zero unrealized_pnl
    (mark prices are applied separately in rebuild_nav).
    """
    positions: dict[str, dict[str, float]] = {}
    for trade in trades:
        symbol = str(trade.get("symbol", ""))
        if not symbol:
            continue
        side = str(trade.get("side", "")).upper()
        price = _parse_amount(trade.get("price"))
        qty = _parse_amount(trade.get("qty"))
        commission = _parse_amount(trade.get("commission"))
        realized_pnl = _parse_amount(trade.get("realizedPnl"))

        if symbol not in positions:
            positions[symbol] = {
                "quantity": 0.0,
                "cost_basis": 0.0,
                "realized_pnl": 0.0,
                "total_commission": 0.0,
            }
        pos = positions[symbol]

        if side == "BUY":
            new_quantity = pos["quantity"] + qty
            if new_quantity > 0:
                pos["cost_basis"] = (
                    pos["cost_basis"] * pos["quantity"]
                    + price * qty
                ) / new_quantity
            pos["quantity"] = new_quantity
        elif side == "SELL":
            if pos["quantity"] > 0:
                pos["realized_pnl"] += realized_pnl
            pos["quantity"] -= qty
            if pos["quantity"] < 0:
                pos["quantity"] = 0.0
                pos["cost_basis"] = 0.0

        pos["total_commission"] += commission

    result: dict[str, ShadowPosition] = {}
    for symbol, pos in positions.items():
        result[symbol] = ShadowPosition.create(
            symbol=symbol,
            quantity=pos["quantity"],
            cost_basis=pos["cost_basis"],
            realized_pnl=pos["realized_pnl"],
            unrealized_pnl=0.0,
        )
    return result


def apply_mark_prices(
    positions: dict[str, ShadowPosition],
    mark_prices: Mapping[str, float],
) -> dict[str, ShadowPosition]:
    """Apply mark prices to compute unrealized PnL for each position."""
    result: dict[str, ShadowPosition] = {}
    for symbol, pos in positions.items():
        mark = _parse_amount(mark_prices.get(symbol, 0.0))
        unrealized = (mark - pos.cost_basis) * pos.quantity
        result[symbol] = ShadowPosition.create(
            symbol=symbol,
            quantity=pos.quantity,
            cost_basis=pos.cost_basis,
            realized_pnl=pos.realized_pnl,
            unrealized_pnl=unrealized,
        )
    return result


def rebuild_cash_events(
    income_history: Sequence[Mapping[str, Any]],
) -> list[ShadowCashEvent]:
    """Rebuild cash events from raw Binance USD-M income history responses.

    Unknown incomeType values are classified as "unknown_income" and
    must form Operational HALT candidates (handled by the caller).
    """
    events: list[ShadowCashEvent] = []
    for income in income_history:
        symbol = str(income.get("symbol", ""))
        income_type_raw = str(income.get("incomeType", ""))
        event_type = _classify_income_type(income_type_raw)
        amount = _parse_amount(income.get("income"))
        timestamp = _ms_to_iso(income.get("time", 0))
        events.append(
            ShadowCashEvent.create(
                event_type=event_type,
                symbol=symbol,
                amount=amount,
                timestamp=timestamp,
                income_type=income_type_raw,
            )
        )
    return events


def rebuild_nav(
    *,
    positions: dict[str, ShadowPosition],
    cash_events: Sequence[ShadowCashEvent],
    initial_equity: float,
    current_equity: float,
    residual_tolerance: float = 1e-8,
) -> ShadowNavMark:
    """Rebuild NAV from positions and cash events.

    Verifies the identity:
      equity = initial + realized + unrealized + funding - commission + transfer

    Unknown non-zero income types are NOT included in the identity;
    they must be handled as Operational HALT candidates by the caller.
    """
    total_realized = sum(pos.realized_pnl for pos in positions.values())
    total_unrealized = sum(pos.unrealized_pnl for pos in positions.values())
    total_funding = 0.0
    total_commission = 0.0
    total_transfer = 0.0
    for event in cash_events:
        if event.event_type == "funding":
            total_funding += event.amount
        elif event.event_type == "commission":
            total_commission += -event.amount
        elif event.event_type == "transfer":
            total_transfer += event.amount
        elif event.event_type == "realized_pnl":
            pass
        elif event.event_type == "unknown_income":
            pass

    return ShadowNavMark.create(
        equity=float(current_equity),
        initial_equity=float(initial_equity),
        realized_pnl=total_realized,
        unrealized_pnl=total_unrealized,
        funding=total_funding,
        commission=total_commission,
        transfer=total_transfer,
        residual_tolerance=residual_tolerance,
    )


def verify_coverage_window(
    query_windows: Sequence[tuple[str, str]],
) -> ShadowCoverageWindow:
    """Verify query window coverage and detect gaps.

    Each query window is a (start_time, end_time) ISO datetime pair.
    Returns a ShadowCoverageWindow with detected gaps.
    """
    if not query_windows:
        return ShadowCoverageWindow.create(
            earliest_recoverable_time="",
            latest_observed_time="",
            gaps=(),
        )
    sorted_windows = sorted(query_windows)
    earliest = sorted_windows[0][0]
    latest = sorted_windows[-1][1]
    gaps: list[tuple[str, str]] = []
    for i in range(len(sorted_windows) - 1):
        current_end = sorted_windows[i][1]
        next_start = sorted_windows[i + 1][0]
        if current_end < next_start:
            gaps.append((current_end, next_start))
    return ShadowCoverageWindow.create(
        earliest_recoverable_time=earliest,
        latest_observed_time=latest,
        gaps=tuple(gaps),
    )


def detect_unknown_income_halt_candidates(
    cash_events: Sequence[ShadowCashEvent],
) -> list[ShadowCashEvent]:
    """Return cash events with unknown income types that have non-zero amounts.

    Per section 4.3: unknown non-zero incomeType must NOT be auto-classified
    into PnL; it must form an Operational HALT candidate.
    """
    return [
        event
        for event in cash_events
        if event.event_type == "unknown_income" and abs(event.amount) > 1e-12
    ]
