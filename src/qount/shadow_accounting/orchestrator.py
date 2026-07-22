"""Shadow accountant orchestration layer.

Coordinates fetch, archive, rebuild, and diff into a single run.
Accepts an injected exchange client and primary snapshot; does NOT
import qount.execution, qount.ledger.store, or ccxt.

Import boundary: this module must NOT import qount.execution,
qount.mini_trend.pilot_dispatcher, qount.ledger, or ccxt.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any, Mapping, Sequence

from qount.shadow_accounting.archive import archive_json
from qount.shadow_accounting.archive import archive_raw_responses
from qount.shadow_accounting.archive import archive_shadow_run
from qount.shadow_accounting.contracts import FetchResult
from qount.shadow_accounting.contracts import ShadowRun
from qount.shadow_accounting.contracts import WatermarkContract
from qount.shadow_accounting.diff import diff_nav
from qount.shadow_accounting.diff import diff_positions
from qount.shadow_accounting.diff import has_blocking_diff
from qount.shadow_accounting.fetch import ReadOnlyExchange
from qount.shadow_accounting.fetch import fetch_income_history
from qount.shadow_accounting.fetch import fetch_open_orders
from qount.shadow_accounting.fetch import fetch_private_trades
from qount.shadow_accounting.rebuild import apply_mark_prices
from qount.shadow_accounting.rebuild import detect_unknown_income_halt_candidates
from qount.shadow_accounting.rebuild import rebuild_cash_events
from qount.shadow_accounting.rebuild import rebuild_nav
from qount.shadow_accounting.rebuild import rebuild_positions
from qount.shadow_accounting.rebuild import verify_coverage_window


def _ms_to_iso(ms: int) -> str:
    try:
        return dt.datetime.fromtimestamp(
            ms / 1000.0, tz=dt.timezone.utc
        ).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def run_shadow_accountant(
    *,
    exchange: ReadOnlyExchange,
    symbols: Sequence[str],
    start_ms: int,
    end_ms: int,
    primary_snapshot: Mapping[str, Any],
    initial_equity: float,
    current_equity: float,
    live_cycle_completed_at: str,
    mark_prices: Mapping[str, float] | None = None,
    venue: str = "binance_usdm",
    run_dir: str | os.PathLike[str] | None = None,
    min_delay_seconds: float = 60.0,
    page_size: int = 1000,
    max_retries: int = 3,
    retry_delay_seconds: float = 1.0,
) -> ShadowRun:
    """Run one complete shadow accountant cycle.

    Steps:
    1. Verify delay since live cycle (watermark contract, section 4.3).
    2. Fetch trades, income history, open orders independently.
    3. Archive raw responses (if run_dir provided).
    4. Rebuild positions, cash events, NAV from first principles.
    5. Diff against primary snapshot.
    6. Archive shadow run summary (if run_dir provided).

    The primary_snapshot is read-only input used only for diff;
    it does not participate in the rebuild (section 4.1).

    initial_equity and current_equity must be obtained independently
    by the caller (e.g. from Binance account API), not from the
    primary ledger.
    """
    shadow_fetch_started_at = dt.datetime.now(dt.timezone.utc).isoformat()

    live_time = dt.datetime.fromisoformat(live_cycle_completed_at)
    shadow_time = dt.datetime.fromisoformat(shadow_fetch_started_at)
    actual_delay = (shadow_time - live_time).total_seconds()
    delay_satisfied = actual_delay >= min_delay_seconds

    watermark = WatermarkContract.create(
        live_cycle_completed_at=live_cycle_completed_at,
        shadow_fetch_started_at=shadow_fetch_started_at,
        min_delay_seconds=min_delay_seconds,
        delay_satisfied=delay_satisfied,
        shadow_coverage_start=_ms_to_iso(start_ms),
        shadow_coverage_end=_ms_to_iso(end_ms),
    )

    trades_result = fetch_private_trades(
        exchange,
        symbols,
        start_ms=start_ms,
        end_ms=end_ms,
        page_size=page_size,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    income_result = fetch_income_history(
        exchange,
        start_ms=start_ms,
        end_ms=end_ms,
        page_size=page_size,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    orders_result = fetch_open_orders(
        exchange,
        symbols,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    fetch_results: list[FetchResult] = [
        trades_result,
        income_result,
        orders_result,
    ]

    if run_dir is not None:
        archive_raw_responses(fetch_results, run_dir=run_dir)

    positions = rebuild_positions(trades_result.records)
    if mark_prices is not None:
        positions = apply_mark_prices(positions, mark_prices)
    cash_events = rebuild_cash_events(income_result.records)
    nav = rebuild_nav(
        positions=positions,
        cash_events=cash_events,
        initial_equity=initial_equity,
        current_equity=current_equity,
    )
    halt_candidates = detect_unknown_income_halt_candidates(cash_events)

    query_windows: list[tuple[str, str]] = []
    for fetch_result in fetch_results:
        for query in fetch_result.queries:
            if query.query_start_ms > 0 or query.query_end_ms > 0:
                query_windows.append(
                    (_ms_to_iso(query.query_start_ms),
                     _ms_to_iso(query.query_end_ms))
                )
    coverage_window = verify_coverage_window(query_windows)

    primary_positions = primary_snapshot.get("positions", {})
    primary_nav = primary_snapshot.get("nav", {})
    pos_diffs = diff_positions(positions, primary_positions)
    nav_diffs = diff_nav(nav, primary_nav)
    all_diffs = pos_diffs + nav_diffs
    blocking = has_blocking_diff(all_diffs)

    if run_dir is not None:
        archive_json(
            {
                sym: {
                    "quantity": pos.quantity,
                    "cost_basis": pos.cost_basis,
                    "realized_pnl": pos.realized_pnl,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "position_hash": pos.position_hash,
                }
                for sym, pos in positions.items()
            },
            file_name="shadow_positions.json",
            run_dir=run_dir,
        )
        archive_json(
            {
                "equity": nav.equity,
                "initial_equity": nav.initial_equity,
                "realized_pnl": nav.realized_pnl,
                "unrealized_pnl": nav.unrealized_pnl,
                "funding": nav.funding,
                "commission": nav.commission,
                "transfer": nav.transfer,
                "residual": nav.residual,
                "identity_verified": nav.identity_verified,
                "nav_hash": nav.nav_hash,
            },
            file_name="shadow_nav.json",
            run_dir=run_dir,
        )
        archive_json(
            {
                "diffs": [
                    {
                        "field": d.field,
                        "primary_value": d.primary_value,
                        "shadow_value": d.shadow_value,
                        "tolerance": d.tolerance,
                        "blocking_level": d.blocking_level,
                        "diff_hash": d.diff_hash,
                    }
                    for d in all_diffs
                ],
                "has_blocking_diff": blocking,
            },
            file_name="reconciliation_diff.json",
            run_dir=run_dir,
        )
        archive_json(
            {
                "earliest_recoverable_time": coverage_window.earliest_recoverable_time,
                "latest_observed_time": coverage_window.latest_observed_time,
                "gaps": [list(g) for g in coverage_window.gaps],
                "window_hash": coverage_window.window_hash,
            },
            file_name="coverage_window.json",
            run_dir=run_dir,
        )
        archive_json(
            {
                "live_cycle_completed_at": watermark.live_cycle_completed_at,
                "shadow_fetch_started_at": watermark.shadow_fetch_started_at,
                "min_delay_seconds": watermark.min_delay_seconds,
                "delay_satisfied": watermark.delay_satisfied,
                "shadow_coverage_start": watermark.shadow_coverage_start,
                "shadow_coverage_end": watermark.shadow_coverage_end,
                "watermark_hash": watermark.watermark_hash,
            },
            file_name="watermark.json",
            run_dir=run_dir,
        )

    shadow_run = ShadowRun.create(
        observed_at=shadow_fetch_started_at,
        venue=venue,
        symbols=symbols,
        fetch_results=fetch_results,
        position_hashes=[pos.position_hash for pos in positions.values()],
        nav_hash=nav.nav_hash,
        coverage_window_hash=coverage_window.window_hash,
        unknown_income_count=len(halt_candidates),
        diff_hashes=[d.diff_hash for d in all_diffs],
        has_blocking_diff=blocking,
        watermark=watermark,
    )

    if run_dir is not None:
        archive_shadow_run(shadow_run, run_dir=run_dir)

    return shadow_run
