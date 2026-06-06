"""L4 cross-exchange funding/basis arbitrage research layer (restart line, changes the game).

After §7 (price/volume) and L3 (slow non-price data) both falsified on the *breadth*
ceiling, and L1 (cross-asset trend) found the project's first real edge but at a
retail-ETF magnitude below the broker gate, every prior line lived *inside*
``IR = IC × √BR`` and tried to predict direction. L4 steps outside that formula: it does
not predict direction at all. It harvests the *cross-exchange funding spread* — go long
the perp on the venue with the lowest (or most negative) funding and short the perp on
the venue with the highest funding, same asset, same notional, net delta ≈ 0, collecting
the funding differential regardless of where price goes.

This module is the L4 data layer + the first, cheapest kill-test: pull multi-venue perp
funding history (ccxt ``fetch_funding_rate_history``), align it to a common 8h bucket via
strict as-of join, and measure whether the cross-venue spread's magnitude × persistence
clears a realistic two-venue round-trip cost. Single-venue CARRY already proved funding
cash-flow is real but eaten by cost (>100% maker fill needed); L4 bets the cross-venue
*spread* is larger / more persistent. If it is not, L4 falsifies before any second
account is opened.

research-only; nothing here is imported by the live / ``run-once`` path. No orders, no
positions — only read-only funding history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable

import ccxt

from .exchange_utils import call_with_time_sync_retry
from .l3_information_edge import _utc_iso_from_ms
from .l3_information_edge import _write_cache
from .l3_information_edge import load_cached_supply
from .settings import Settings
from .strategy_selection import _sharpe
from .strategy_selection import compute_directional_deflated_sharpe
from .strategy_selection import compute_directional_pbo
from .strategy_selection import normalize_funding_history


L4_CROSS_EXCHANGE_VERSION = "l4_cross_exchange_v1"
L4_FAMILY = "l4_cross_exchange_funding"

# Funding settles every 8h on most venues; align everything to a common 8h grid.
L4_BUCKET_FREQUENCY_LABEL = "8h"
L4_BUCKET_MS = 8 * 60 * 60 * 1000
_YEAR_MS = 365.0 * 24.0 * 60.0 * 60.0 * 1000.0

# ccxt ids for the candidate venues. Reachability from the production host is only known
# after a real WSL run (same lesson as L1/Tiingo; all three need the configured proxy);
# the scan keeps any venue that fails to fetch out of the panel and needs >= 2 reachable
# venues to form a spread. Default panel is the USDT-settled, directly-symbol-shared set.
# Hyperliquid is deferred to S2: it settles in USDC (different symbol/quote, so a separate
# basis) and funds hourly — funding-interval heterogeneity is already normalized to an 8h
# basis below, but the USDC↔USDT quote mismatch needs its own mapping before inclusion.
DEFAULT_L4_VENUES: tuple[str, ...] = ("binance", "bybit", "okx")

# Unified ccxt linear-perp symbols (settle in USDT).
DEFAULT_L4_SYMBOLS: tuple[str, ...] = (
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "DOGE/USDT:USDT",
    "BNB/USDT:USDT",
)

# Gates: net annualized capture must be positive after cost, the multiple-testing
# penalties (DSR/PBO) must pass, and harvesting must be feasible (required maker fill ≤ 1,
# the wall that killed single-venue CARRY).
L4_DSR_PASS_THRESHOLD = 0.95
L4_PBO_PASS_THRESHOLD = 0.5

_MISSING_VENUE_DETAIL = (
    "Fewer than two venues returned funding history; need >= 2 reachable perp venues to "
    "form a cross-exchange spread. Check venue reachability / proxy from the host."
)


def _funding_rows_sorted(rows: Any) -> list[dict[str, Any]]:
    """Return funding rows sorted ascending by timestamp, keeping only priced rows."""

    if not isinstance(rows, list):
        return []
    cleaned = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("timestamp_ms") is not None
        and row.get("funding_rate") is not None
    ]
    return sorted(cleaned, key=lambda item: int(item["timestamp_ms"]))


def asof_funding_rate(rows_sorted: list[dict[str, Any]], timestamp_ms: int) -> float | None:
    """As-of join: funding rate from the most recent row settled at or before ``timestamp_ms``.

    ``rows_sorted`` must be ascending by ``timestamp_ms``. Strictly no look-ahead — funding
    settled after the bucket is never visible.
    """

    candidate: float | None = None
    for row in rows_sorted:
        if int(row["timestamp_ms"]) <= timestamp_ms:
            candidate = float(row["funding_rate"])
        else:
            break
    return candidate


def _median_interval_ms(rows_sorted: list[dict[str, Any]], fallback_ms: int) -> int:
    """Median spacing between consecutive funding settlements (the venue's native interval).

    Venues fund at heterogeneous intervals (8h on Binance/Bybit/OKX majors, 4h on some
    alts, 1h on Hyperliquid). A raw funding rate is per-interval, so cross-venue rates are
    only comparable once normalized to a common basis — this recovers each series' interval
    so the caller can scale every rate to an 8h-equivalent.
    """

    diffs = [
        int(rows_sorted[i]["timestamp_ms"]) - int(rows_sorted[i - 1]["timestamp_ms"])
        for i in range(1, len(rows_sorted))
    ]
    diffs = [d for d in diffs if d > 0]
    if not diffs:
        return fallback_ms
    diffs.sort()
    mid = len(diffs) // 2
    median = diffs[mid] if len(diffs) % 2 == 1 else (diffs[mid - 1] + diffs[mid]) // 2
    return max(int(median), 1)


def _bucket_grid(start_ms: int, end_ms: int, bucket_ms: int) -> list[int]:
    if bucket_ms <= 0 or end_ms < start_ms:
        return []
    grid: list[int] = []
    cursor = start_ms
    while cursor <= end_ms:
        grid.append(cursor)
        cursor += bucket_ms
    return grid


def evaluate_l4_cross_exchange_funding(
    *,
    funding_by_venue: dict[str, dict[str, list[dict[str, Any]]]],
    symbols: list[str],
    start_ms: int,
    end_ms: int,
    cost_per_side_pct: float,
    taker_cost_per_side_pct: float | None = None,
    bucket_ms: int = L4_BUCKET_MS,
    frequency_label: str = L4_BUCKET_FREQUENCY_LABEL,
    holdout_role: str = "discovery",
) -> dict[str, Any]:
    """Cross-exchange funding-spread kill-test (market-neutral; no direction predicted).

    For each symbol, on a common bucket grid: as-of each venue's funding rate, then pick
    the delta-neutral pair (long the lowest-funding venue, short the highest). The per-
    bucket gross capture is the spread ``max − min``; a pair change pays a 4-leg round-trip
    (close 2 + open 2), a hold pays 0, the first entry pays 2 legs. ``net = gross − legs ×
    cost_per_side``. Each symbol's net series is one trial for the reused Sharpe/DSR/PBO
    harness, plus ``break_even_cost_per_side`` and (if a taker cost is given) the
    ``required_maker_fill`` that decides feasibility — the wall that killed single-venue
    CARRY. research-only; no positions, no live impact.
    """

    venues = sorted(funding_by_venue)
    buckets = _bucket_grid(start_ms, end_ms, bucket_ms)
    periods_per_year = _YEAR_MS / bucket_ms if bucket_ms > 0 else 0.0

    cells: list[dict[str, Any]] = []
    portfolio_net_by_ts: dict[int, list[float]] = {}
    portfolio_gross_by_ts: dict[int, list[float]] = {}
    total_legs_all = 0
    total_gross_all = 0.0

    for symbol in symbols:
        venue_rows = {v: _funding_rows_sorted(funding_by_venue[v].get(symbol, [])) for v in venues}
        # Scale each venue's per-interval funding to an 8h-equivalent so spreads are
        # comparable across heterogeneous settlement intervals (8h/4h/1h).
        venue_interval_ms = {v: _median_interval_ms(venue_rows[v], bucket_ms) for v in venues}
        venue_scale = {v: bucket_ms / venue_interval_ms[v] for v in venues}
        net_series: list[float] = []
        gross_series: list[float] = []
        period_returns: dict[int, float] = {}
        prev_pair: tuple[str, str] | None = None
        total_legs = 0
        pair_changes = 0
        for bucket in buckets:
            rates: dict[str, float] = {}
            for v in venues:
                rate = asof_funding_rate(venue_rows[v], bucket)
                if rate is not None:
                    rates[v] = rate * venue_scale[v]
            if len(rates) < 2:
                continue
            long_venue = min(rates, key=lambda v: rates[v])
            short_venue = max(rates, key=lambda v: rates[v])
            if long_venue == short_venue:
                continue
            spread = rates[short_venue] - rates[long_venue]
            pair = (long_venue, short_venue)
            if prev_pair is None:
                legs = 2
            elif pair != prev_pair:
                legs = 4
                pair_changes += 1
            else:
                legs = 0
            net = spread - legs * cost_per_side_pct
            gross_series.append(spread)
            net_series.append(net)
            period_returns[bucket] = net
            portfolio_net_by_ts.setdefault(bucket, []).append(net)
            portfolio_gross_by_ts.setdefault(bucket, []).append(spread)
            total_legs += legs
            prev_pair = pair

        if len(net_series) < 2:
            continue
        gross_sum = sum(gross_series)
        net_sum = sum(net_series)
        bucket_count = len(net_series)
        total_legs_all += total_legs
        total_gross_all += gross_sum
        cells.append(
            {
                "family": L4_FAMILY,
                "frequency": frequency_label,
                "symbol": symbol,
                "signal_lookback_bars": 0,
                "holding_bars": 1,
                "bucket_count": bucket_count,
                "gross_sum_capture_pct": gross_sum,
                "net_sum_capture_pct": net_sum,
                "gross_annualized_capture_pct": (gross_sum / bucket_count) * periods_per_year,
                "net_annualized_capture_pct": (net_sum / bucket_count) * periods_per_year,
                "portfolio_sharpe": _sharpe(net_series, frequency_label),
                "gross_sharpe": _sharpe(gross_series, frequency_label),
                "portfolio_period_count": bucket_count,
                "total_rebalance_legs": total_legs,
                "pair_changes": pair_changes,
                "venue_funding_interval_ms": venue_interval_ms,
                "mean_pair_holding_buckets": bucket_count / (pair_changes + 1),
                "break_even_cost_per_side": (gross_sum / total_legs) if total_legs > 0 else None,
                "period_returns_by_timestamp": period_returns,
            }
        )

    # Equal-weight portfolio across whatever symbols are present each bucket.
    portfolio_net: list[float] = []
    portfolio_gross: list[float] = []
    for bucket in sorted(portfolio_net_by_ts):
        nets = portfolio_net_by_ts[bucket]
        grosses = portfolio_gross_by_ts[bucket]
        portfolio_net.append(sum(nets) / len(nets))
        portfolio_gross.append(sum(grosses) / len(grosses))

    portfolio_net_sum = sum(portfolio_net)
    portfolio_gross_sum = sum(portfolio_gross)
    portfolio_buckets = len(portfolio_net)
    portfolio_net_annualized = (
        (portfolio_net_sum / portfolio_buckets) * periods_per_year if portfolio_buckets else None
    )
    portfolio_gross_annualized = (
        (portfolio_gross_sum / portfolio_buckets) * periods_per_year if portfolio_buckets else None
    )

    # required_maker_fill: with taker cost t and maker cost ~0, a fraction f of legs filling
    # as maker makes effective leg cost (1-f)·t. Net >= 0 needs (1-f)·t·legs <= gross_all, i.e.
    # f >= 1 - gross_all/(t·legs). f > 1 => infeasible (the single-venue CARRY wall).
    required_maker_fill: float | None = None
    if taker_cost_per_side_pct and total_legs_all > 0:
        taker_cost_total = taker_cost_per_side_pct * total_legs_all
        if taker_cost_total > 0:
            required_maker_fill = 1.0 - (total_gross_all / taker_cost_total)

    break_even_cost_per_side_all = (total_gross_all / total_legs_all) if total_legs_all > 0 else None

    deflated = compute_directional_deflated_sharpe(cells)
    pbo = compute_directional_pbo(cells)

    portfolio_sharpe = _sharpe(portfolio_net, frequency_label)
    dsr_value = deflated.get("deflated_sharpe_ratio") if deflated else None
    pbo_value = pbo.get("pbo") if pbo else None

    # The honest hurdle is net-positive capture *after the provided realistic per-leg cost*
    # (the cost wall single-venue CARRY failed), plus the DSR/PBO multiple-testing penalties
    # over the per-symbol trials. ``required_maker_fill`` / ``break_even_cost_per_side`` stay
    # as diagnostics — they are not a pass/fail gate, since the spread is >= 0 by
    # construction (we always pick the profitable side), so maker fill can always rescue a
    # thin-but-positive gross. What matters is whether the *net* margin is real and robust.
    net_pass = portfolio_net_annualized is not None and portfolio_net_annualized > 0.0
    dsr_pass = isinstance(dsr_value, (int, float)) and dsr_value >= L4_DSR_PASS_THRESHOLD
    pbo_pass = isinstance(pbo_value, (int, float)) and pbo_value < L4_PBO_PASS_THRESHOLD
    passes_s1 = bool(net_pass and dsr_pass and pbo_pass)

    for cell in cells:
        cell.pop("period_returns_by_timestamp", None)

    return {
        "family": L4_FAMILY,
        "holdout_role": holdout_role,
        "frequency": frequency_label,
        "venues": venues,
        "venue_count": len(venues),
        "symbols": list(symbols),
        "cost_per_side_pct": cost_per_side_pct,
        "taker_cost_per_side_pct": taker_cost_per_side_pct,
        "bucket_count": portfolio_buckets,
        "cells": cells,
        "portfolio_net_sum_capture_pct": portfolio_net_sum,
        "portfolio_gross_sum_capture_pct": portfolio_gross_sum,
        "portfolio_net_annualized_capture_pct": portfolio_net_annualized,
        "portfolio_gross_annualized_capture_pct": portfolio_gross_annualized,
        "portfolio_sharpe": portfolio_sharpe,
        "total_rebalance_legs": total_legs_all,
        "break_even_cost_per_side": break_even_cost_per_side_all,
        "required_maker_fill": required_maker_fill,
        "deflated_sharpe": deflated,
        "pbo": pbo,
        "kill_test": {
            "net_pass": net_pass,
            "dsr_pass": dsr_pass,
            "pbo_pass": pbo_pass,
            "passes_s1": passes_s1,
            "dsr_pass_threshold": L4_DSR_PASS_THRESHOLD,
            "pbo_pass_threshold": L4_PBO_PASS_THRESHOLD,
        },
        "window_start_utc": _utc_iso_from_ms(start_ms),
        "window_end_utc": _utc_iso_from_ms(end_ms),
        "decision": "advance_to_s2" if passes_s1 else "cross_exchange_spread_below_gate",
    }


def _build_l4_exchange(settings: Settings, venue: str) -> Any:
    """Build a public ccxt linear-perp client for ``venue`` (proxy as configured)."""

    exchange_class = getattr(ccxt, venue)
    options: dict[str, Any] = {
        "enableRateLimit": True,
        "options": {"defaultType": "swap", "defaultSubType": "linear"},
    }
    if settings.https_proxy:
        options["httpsProxy"] = settings.https_proxy
    elif settings.http_proxy:
        options["httpProxy"] = settings.http_proxy
    return exchange_class(options)


def _fetch_venue_funding(
    *,
    exchange: Any,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    """Paginated funding-rate history for one venue+symbol, normalized + de-duplicated."""

    fetch_history = getattr(exchange, "fetch_funding_rate_history", None)
    if not callable(fetch_history):
        return []
    rows: list[dict[str, Any]] = []
    cursor = start_ms
    last_timestamp: int | None = None
    while cursor <= end_ms:
        batch = call_with_time_sync_retry(exchange, fetch_history, symbol, since=cursor, limit=1000)
        if not batch:
            break
        normalized = normalize_funding_history(batch, symbol=symbol, start_ms=start_ms, end_ms=end_ms)
        added = 0
        for row in normalized:
            timestamp = int(row["timestamp_ms"])
            if last_timestamp is not None and timestamp <= last_timestamp:
                continue
            rows.append(row)
            last_timestamp = timestamp
            added += 1
        if added == 0:
            break
        cursor = int(rows[-1]["timestamp_ms"]) + 1
    return rows


def fetch_cross_exchange_funding(
    *,
    settings: Settings,
    venues: list[str],
    symbols: list[str],
    start_ms: int,
    end_ms: int,
    cache_dir: str | Path | None = None,
    fetcher: Callable[[str, str], Any] | None = None,
    force_refresh: bool = False,
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], dict[str, str], dict[str, dict[str, int]]]:
    """Fetch + cache + normalize multi-venue funding history.

    Returns ``(funding_by_venue, venue_status, point_counts)``. A venue that raises on every
    symbol is recorded as ``unreachable`` and dropped from the panel. ``fetcher(venue,
    symbol)`` lets tests inject raw rows without the network.
    """

    funding_by_venue: dict[str, dict[str, list[dict[str, Any]]]] = {}
    venue_status: dict[str, str] = {}
    point_counts: dict[str, dict[str, int]] = {}
    for venue in venues:
        exchange: Any = None
        per_symbol: dict[str, list[dict[str, Any]]] = {}
        counts: dict[str, int] = {}
        any_ok = False
        any_error = False
        for symbol in symbols:
            cache_path = None
            if cache_dir is not None:
                safe_symbol = symbol.replace("/", "_").replace(":", "_")
                cache_path = Path(cache_dir) / f"funding_{venue}_{safe_symbol}.json"
            if cache_path is not None and not force_refresh:
                cached = load_cached_supply(cache_path)
                if cached is not None:
                    per_symbol[symbol] = _funding_rows_sorted(cached)
                    counts[symbol] = len(per_symbol[symbol])
                    any_ok = True
                    continue
            try:
                if fetcher is not None:
                    raw = fetcher(venue, symbol)
                    normalized = normalize_funding_history(
                        raw, symbol=symbol, start_ms=start_ms, end_ms=end_ms
                    )
                else:
                    if exchange is None:
                        exchange = _build_l4_exchange(settings, venue)
                    normalized = _fetch_venue_funding(
                        exchange=exchange, symbol=symbol, start_ms=start_ms, end_ms=end_ms
                    )
            except Exception:
                any_error = True
                continue
            rows = _funding_rows_sorted(normalized)
            per_symbol[symbol] = rows
            counts[symbol] = len(rows)
            if cache_path is not None:
                _write_cache(cache_path, rows)
            any_ok = True
        if any_ok:
            funding_by_venue[venue] = per_symbol
            point_counts[venue] = counts
            venue_status[venue] = "partial" if any_error else "ok"
        else:
            venue_status[venue] = "unreachable"
    return funding_by_venue, venue_status, point_counts


@dataclass
class L4CrossExchangeFundingService:
    """L4 S1 driver: fetch multi-venue funding history and run the cross-spread kill-test."""

    settings: Settings

    def run(
        self,
        *,
        start_ms: int,
        end_ms: int,
        venues: list[str] | None = None,
        symbols: list[str] | None = None,
        cost_per_side_pct: float | None = None,
        taker_cost_per_side_pct: float | None = None,
        cache_dir: str | Path | None = None,
        fetcher: Callable[[str, str], Any] | None = None,
        force_refresh: bool = False,
        holdout_role: str = "discovery",
    ) -> dict[str, Any]:
        venue_list = venues or list(DEFAULT_L4_VENUES)
        symbol_list = symbols or list(DEFAULT_L4_SYMBOLS)
        if cost_per_side_pct is None:
            cost_per_side_pct = max(float(self.settings.estimated_fee_pct), 0.0) + max(
                float(self.settings.estimated_slippage_pct), 0.0
            )

        funding_by_venue, venue_status, point_counts = fetch_cross_exchange_funding(
            settings=self.settings,
            venues=venue_list,
            symbols=symbol_list,
            start_ms=start_ms,
            end_ms=end_ms,
            cache_dir=cache_dir,
            fetcher=fetcher,
            force_refresh=force_refresh,
        )

        if len(funding_by_venue) < 2:
            return {
                "version": L4_CROSS_EXCHANGE_VERSION,
                "source": "ccxt_cross_exchange_funding",
                "error": "insufficient_reachable_venues",
                "detail": _MISSING_VENUE_DETAIL,
                "venue_status": venue_status,
                "venues_requested": venue_list,
                "symbols": symbol_list,
            }

        result = evaluate_l4_cross_exchange_funding(
            funding_by_venue=funding_by_venue,
            symbols=symbol_list,
            start_ms=start_ms,
            end_ms=end_ms,
            cost_per_side_pct=cost_per_side_pct,
            taker_cost_per_side_pct=taker_cost_per_side_pct,
            holdout_role=holdout_role,
        )
        result.update(
            {
                "version": L4_CROSS_EXCHANGE_VERSION,
                "source": "ccxt_cross_exchange_funding",
                "venue_status": venue_status,
                "venues_requested": venue_list,
                "funding_point_counts": point_counts,
                "cache_dir": None if cache_dir is None else str(cache_dir),
            }
        )
        return result
