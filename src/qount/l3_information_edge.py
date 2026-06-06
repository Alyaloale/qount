"""L3 information-edge research data layer (S0.1).

This module is the data access layer for the L3 restart line described in
``docs/l3-information-edge-plan.md``: swap the information source from price/volume
features to non-price slow data (stablecoin supply, on-chain flows, derivatives
positioning) on a daily/weekly horizon.

S0.1 scope only: fetch DefiLlama aggregate stablecoin supply, cache it under
``state/`` for offline replay, and normalize it into a sorted, de-duplicated
series with strict as-of (no look-ahead) joins. No strategy behavior, no IC
computation (that is the S1 kill-test). research-only; nothing here is imported
by the live / ``run-once`` path.
"""

from __future__ import annotations

import itertools
import json
import math
import urllib.request
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Callable

from .exchange_utils import build_exchange
from .exchange_utils import call_with_time_sync_retry
from .exchange_utils import resolve_market_symbols
from .settings import Settings
from .strategy_selection import _sharpe
from .strategy_selection import _t_stat
from .strategy_selection import compute_directional_deflated_sharpe
from .strategy_selection import compute_directional_pbo
from .strategy_selection import pearson_correlation
from .strategy_selection import spearman_rank_correlation
from .trade_policy import timeframe_to_ms


L3_INFORMATION_EDGE_VERSION = "l3_information_edge_v1"

# DefiLlama aggregate stablecoin chart (all chains). Free, no key. ``date`` is a
# unix-seconds string, ``totalCirculatingUSD.peggedUSD`` is total stablecoin
# market cap in USD.
DEFILLAMA_STABLECOIN_CHARTS_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
DEFAULT_STABLECOIN_SUPPLY_FIELD: tuple[str, ...] = ("totalCirculatingUSD", "peggedUSD")

DAY_MS = 24 * 60 * 60 * 1000
WEEK_MS = 7 * DAY_MS

# Weekly cadence is labelled "7d" so the reused DSR/PBO/_sharpe harness (which only
# understands m/h/d via timeframe_to_ms) annualizes correctly at 365/7 ≈ 52.14/yr.
WEEKLY_FREQUENCY_LABEL = "7d"
L3A_FAMILY = "l3a_stablecoin_timing"

# Plan §2/§5 breadth-adjusted required IC (IR=1 with ~150 independent weeks → √150≈12).
# The kill-test gates on the more conservative of this reference and the realized 1/√N.
L3A_BREADTH_ADJUSTED_IC_REFERENCE = 0.083
L3A_DSR_PASS_THRESHOLD = 0.95
L3A_PBO_PASS_THRESHOLD = 0.5


@dataclass(frozen=True)
class SupplyPoint:
    """A single observed supply value at its own observation timestamp."""

    timestamp_ms: int
    value: float


def _coerce_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _parse_date_to_ms(value: Any) -> int | None:
    """Parse a DefiLlama ``date`` field into epoch milliseconds.

    DefiLlama emits unix seconds (often as a string). We accept ints, floats, or
    numeric strings. Values that already look like milliseconds (>= 1e11) are kept
    as-is so the function is robust to either convention without ever inventing a
    future-leaning timestamp.
    """

    seconds = _coerce_float(value)
    if seconds is None or seconds <= 0:
        return None
    if seconds >= 1e11:
        return int(seconds)
    return int(seconds * 1000)


def _extract_nested(obj: Any, path: tuple[str, ...]) -> Any:
    cursor = obj
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return None
        cursor = cursor[key]
    return cursor


def normalize_stablecoin_supply_series(
    raw_rows: Any,
    *,
    field_path: tuple[str, ...] = DEFAULT_STABLECOIN_SUPPLY_FIELD,
) -> list[SupplyPoint]:
    """Convert raw DefiLlama chart rows into a sorted, de-duplicated supply series.

    No look-ahead is introduced: every point keeps its own observation timestamp.
    Rows missing the field, with an unparseable date, or with a non-positive value
    are skipped. When two rows share a timestamp the later one in input order wins
    (DefiLlama does not normally duplicate, this is only defensive).
    """

    if not isinstance(raw_rows, list):
        return []
    by_timestamp: dict[int, float] = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        timestamp_ms = _parse_date_to_ms(row.get("date"))
        if timestamp_ms is None:
            continue
        value = _coerce_float(_extract_nested(row, field_path))
        if value is None or value <= 0.0:
            continue
        by_timestamp[timestamp_ms] = value
    return [SupplyPoint(timestamp_ms=ts, value=by_timestamp[ts]) for ts in sorted(by_timestamp)]


def asof_supply_at(series: list[SupplyPoint], timestamp_ms: int) -> float | None:
    """Return the most recent supply value at or before ``timestamp_ms``.

    Strict as-of join: only points whose observation time is <= the anchor are
    eligible, so the result can never use information from the future. ``series``
    is expected sorted ascending (as produced by ``normalize_stablecoin_supply_series``).
    Returns ``None`` if no observation exists at/before the anchor.
    """

    chosen: float | None = None
    for point in series:
        if point.timestamp_ms <= timestamp_ms:
            chosen = point.value
        else:
            break
    return chosen


def weekly_anchors(start_ms: int, end_ms: int) -> list[int]:
    """Generate weekly anchor timestamps in ``[start_ms, end_ms]`` (inclusive)."""

    if end_ms < start_ms:
        return []
    anchors: list[int] = []
    cursor = start_ms
    while cursor <= end_ms:
        anchors.append(cursor)
        cursor += WEEK_MS
    return anchors


def resample_supply_to_anchors(
    series: list[SupplyPoint], anchors_ms: list[int]
) -> list[tuple[int, float | None]]:
    """As-of join the supply series onto each anchor timestamp (no look-ahead)."""

    return [(anchor, asof_supply_at(series, anchor)) for anchor in anchors_ms]


def _utc_iso_from_ms(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def load_cached_supply(cache_path: str | Path) -> Any | None:
    """Return cached raw rows if the cache file exists, else ``None``."""

    path = Path(cache_path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(cache_path: str | Path, raw_rows: Any) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw_rows, ensure_ascii=False), encoding="utf-8")


def _default_http_get_json(url: str, *, settings: Settings | None) -> Any:
    proxy = None
    if settings is not None:
        proxy = settings.https_proxy or settings.http_proxy
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    else:
        opener = urllib.request.build_opener()
    request = urllib.request.Request(url, headers={"User-Agent": "qount-l3-research/1.0"})
    with opener.open(request, timeout=60) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def fetch_stablecoin_supply_raw(
    *,
    settings: Settings | None = None,
    cache_path: str | Path | None = None,
    url: str = DEFILLAMA_STABLECOIN_CHARTS_URL,
    fetcher: Callable[[str], Any] | None = None,
    force_refresh: bool = False,
) -> tuple[Any, str]:
    """Fetch raw DefiLlama stablecoin chart rows, with optional state cache.

    Returns ``(raw_rows, source)`` where ``source`` is ``"cache"`` or ``"network"``.
    ``fetcher`` lets tests inject a payload without touching the network. When
    ``cache_path`` is set and present (and not ``force_refresh``), the cache is
    used and the network is never hit.
    """

    if cache_path is not None and not force_refresh:
        cached = load_cached_supply(cache_path)
        if cached is not None:
            return cached, "cache"
    if fetcher is not None:
        raw_rows = fetcher(url)
    else:
        raw_rows = _default_http_get_json(url, settings=settings)
    if cache_path is not None:
        _write_cache(cache_path, raw_rows)
    return raw_rows, "network"


def _weekly_log_growth(weekly: list[tuple[int, float | None]]) -> list[float]:
    growth: list[float] = []
    previous: float | None = None
    for _, value in weekly:
        if value is not None and value > 0.0:
            if previous is not None and previous > 0.0:
                growth.append(math.log(value / previous))
            previous = value
    return growth


@dataclass
class L3StablecoinSupplyService:
    """Thin S0.1 diagnostic: fetch / cache / normalize and summarize the series.

    This exists so the data layer can be exercised end-to-end against the real
    DefiLlama API on the WSL production host and land an artifact. It computes no
    IC and takes no positions; the kill-test is S1.
    """

    settings: Settings

    def run(
        self,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        cache_path: str | Path | None = None,
        url: str = DEFILLAMA_STABLECOIN_CHARTS_URL,
        field_path: tuple[str, ...] = DEFAULT_STABLECOIN_SUPPLY_FIELD,
        fetcher: Callable[[str], Any] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        raw_rows, source = fetch_stablecoin_supply_raw(
            settings=self.settings,
            cache_path=cache_path,
            url=url,
            fetcher=fetcher,
            force_refresh=force_refresh,
        )
        raw_count = len(raw_rows) if isinstance(raw_rows, list) else 0
        series = normalize_stablecoin_supply_series(raw_rows, field_path=field_path)

        window_start = start_ms if start_ms is not None else (series[0].timestamp_ms if series else None)
        window_end = end_ms if end_ms is not None else (series[-1].timestamp_ms if series else None)

        weekly: list[tuple[int, float | None]] = []
        if window_start is not None and window_end is not None:
            weekly = resample_supply_to_anchors(series, weekly_anchors(window_start, window_end))
        weekly_covered = [pair for pair in weekly if pair[1] is not None]
        growth = _weekly_log_growth(weekly)

        payload: dict[str, Any] = {
            "version": L3_INFORMATION_EDGE_VERSION,
            "source": "defillama_stablecoin_supply",
            "fetched_from": source,
            "url": url,
            "field_path": list(field_path),
            "cache_path": None if cache_path is None else str(cache_path),
            "raw_point_count": raw_count,
            "normalized_point_count": len(series),
            "first_observation_utc": _utc_iso_from_ms(series[0].timestamp_ms) if series else None,
            "last_observation_utc": _utc_iso_from_ms(series[-1].timestamp_ms) if series else None,
            "latest_supply_usd": series[-1].value if series else None,
            "weekly_anchor_count": len(weekly),
            "weekly_covered_count": len(weekly_covered),
            "weekly_log_growth_count": len(growth),
            "weekly_log_growth_mean": (sum(growth) / len(growth)) if growth else None,
        }
        if window_start is not None:
            payload["window_start_utc"] = _utc_iso_from_ms(window_start)
        if window_end is not None:
            payload["window_end_utc"] = _utc_iso_from_ms(window_end)
        return payload


# ---------------------------------------------------------------------------
# S1 kill-test: stablecoin supply growth -> BTC weekly forward-return timing
# ---------------------------------------------------------------------------


def _sign(value: float) -> float:
    if value > 0.0:
        return 1.0
    if value < 0.0:
        return -1.0
    return 0.0


def normalize_close_series(raw_rows: Any) -> list[SupplyPoint]:
    """Convert ccxt OHLCV rows ([ts, o, h, l, c, v]) into a sorted close series."""

    if not isinstance(raw_rows, list):
        return []
    by_timestamp: dict[int, float] = {}
    for row in raw_rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        timestamp_ms = _parse_date_to_ms(row[0])
        close = _coerce_float(row[4])
        if timestamp_ms is None or close is None or close <= 0.0:
            continue
        by_timestamp[timestamp_ms] = close
    return [SupplyPoint(timestamp_ms=ts, value=by_timestamp[ts]) for ts in sorted(by_timestamp)]


def evaluate_l3a_stablecoin_timing(
    *,
    supply_series: list[SupplyPoint],
    price_series: list[SupplyPoint],
    anchors_ms: list[int],
    signal_lookback_weeks_grid: list[int],
    horizon_weeks_grid: list[int],
    cost_per_side_pct: float,
    holdout_role: str = "discovery",
) -> dict[str, Any]:
    """Time-series rank-IC kill-test for L3a (stablecoin supply -> BTC timing).

    For each (signal lookback L weeks, prediction horizon h weeks) config:
      - signal_t = log(supply_asof(t) / supply_asof(t-L))   (strict as-of, no leak)
      - rank-IC = Spearman(signal_t, BTC forward return t->t+h)
      - a weekly-rebalanced timing series holds sign(signal) for h weeks (overlapping
        claims averaged, the standard overlap remedy), marked weekly so every config
        shares one weekly time axis -> the reused DSR/PBO harness applies directly.

    Every (L, h) config is a trial, so DSR penalizes the multi-horizon search honestly.
    research-only diagnostic; no positions, no live impact.
    """

    price_at = [asof_supply_at(price_series, anchor) for anchor in anchors_ms]
    supply_at = [asof_supply_at(supply_series, anchor) for anchor in anchors_ms]
    n = len(anchors_ms)
    # Weekly BTC return r[i] = price(t_{i+1}) / price(t_i) - 1 (t->t+1, used by timing).
    weekly_return: list[float | None] = []
    for i in range(n):
        if i + 1 < n and price_at[i] and price_at[i + 1] and price_at[i] > 0.0:
            weekly_return.append(price_at[i + 1] / price_at[i] - 1.0)
        else:
            weekly_return.append(None)

    cells: list[dict[str, Any]] = []
    for lookback in signal_lookback_weeks_grid:
        # Base signal per anchor (None where supply lookback unavailable).
        base_signal: list[float | None] = []
        for i in range(n):
            if i >= lookback and supply_at[i] and supply_at[i - lookback] and supply_at[i - lookback] > 0.0:
                base_signal.append(math.log(supply_at[i] / supply_at[i - lookback]))
            else:
                base_signal.append(None)
        for horizon in horizon_weeks_grid:
            # Pure predictive read: Spearman(signal_t, forward return t->t+h).
            ic_signals: list[float] = []
            ic_forwards: list[float] = []
            for i in range(n):
                if base_signal[i] is None:
                    continue
                j = i + horizon
                if j < n and price_at[i] and price_at[j] and price_at[i] > 0.0:
                    ic_signals.append(base_signal[i])
                    ic_forwards.append(price_at[j] / price_at[i] - 1.0)
            rank_ic = spearman_rank_correlation(ic_signals, ic_forwards)

            # Weekly timing series: average sign over the h still-open claims.
            weekly_net: list[float] = []
            period_returns: dict[int, float] = {}
            previous_position = 0.0
            for i in range(n):
                if weekly_return[i] is None:
                    continue
                window_signs = [
                    _sign(base_signal[k])
                    for k in range(max(i - horizon + 1, 0), i + 1)
                    if base_signal[k] is not None
                ]
                position = sum(window_signs) / len(window_signs) if window_signs else 0.0
                gross = position * weekly_return[i]
                turnover = abs(position - previous_position)
                net = gross - cost_per_side_pct * turnover
                weekly_net.append(net)
                period_returns[anchors_ms[i]] = net
                previous_position = position

            sample_count = len(ic_signals)
            net_sum = sum(weekly_net)
            sharpe = _sharpe(weekly_net, WEEKLY_FREQUENCY_LABEL)
            ic_req_dynamic = (1.0 / math.sqrt(sample_count)) if sample_count >= 2 else None
            cells.append(
                {
                    "family": L3A_FAMILY,
                    "frequency": WEEKLY_FREQUENCY_LABEL,
                    "signal_lookback_bars": int(lookback),
                    "holding_bars": int(horizon),
                    "signal_lookback_weeks": int(lookback),
                    "horizon_weeks": int(horizon),
                    "sample_count": sample_count,
                    "rank_ic": rank_ic,
                    "ic_required_breadth_adjusted": ic_req_dynamic,
                    "net_sum_return_pct": net_sum,
                    "portfolio_sharpe": sharpe,
                    "portfolio_period_count": len(weekly_net),
                    "period_returns_by_timestamp": period_returns,
                }
            )

    scored = [cell for cell in cells if isinstance(cell.get("rank_ic"), (int, float))]
    best_cell = max(scored, key=lambda cell: abs(float(cell["rank_ic"])), default=None)
    deflated = compute_directional_deflated_sharpe(cells)
    pbo = compute_directional_pbo(cells)

    best_abs_ic = abs(float(best_cell["rank_ic"])) if best_cell else None
    dsr_value = deflated.get("deflated_sharpe_ratio") if deflated else None
    pbo_value = pbo.get("pbo") if pbo else None
    ic_gate = L3A_BREADTH_ADJUSTED_IC_REFERENCE
    if best_cell and isinstance(best_cell.get("ic_required_breadth_adjusted"), (int, float)):
        ic_gate = max(ic_gate, float(best_cell["ic_required_breadth_adjusted"]))

    ic_pass = best_abs_ic is not None and best_abs_ic >= ic_gate
    net_pass = bool(best_cell) and float(best_cell["net_sum_return_pct"]) > 0.0
    dsr_pass = isinstance(dsr_value, (int, float)) and dsr_value >= L3A_DSR_PASS_THRESHOLD
    pbo_pass = isinstance(pbo_value, (int, float)) and pbo_value < L3A_PBO_PASS_THRESHOLD
    passes_kill_test = bool(ic_pass and net_pass and dsr_pass and pbo_pass)

    # Strip the in-memory period series before it can reach the artifact.
    for cell in cells:
        cell.pop("period_returns_by_timestamp", None)

    return {
        "family": L3A_FAMILY,
        "holdout_role": holdout_role,
        "cost_per_side_pct": cost_per_side_pct,
        "anchor_count": n,
        "cells": cells,
        "best_cell": best_cell,
        "best_abs_rank_ic": best_abs_ic,
        "ic_gate_breadth_adjusted": ic_gate,
        "ic_reference": L3A_BREADTH_ADJUSTED_IC_REFERENCE,
        "deflated_sharpe": deflated,
        "pbo": pbo,
        "kill_test": {
            "ic_pass": ic_pass,
            "net_pass": net_pass,
            "dsr_pass": dsr_pass,
            "pbo_pass": pbo_pass,
            "passes_kill_test": passes_kill_test,
            "dsr_pass_threshold": L3A_DSR_PASS_THRESHOLD,
            "pbo_pass_threshold": L3A_PBO_PASS_THRESHOLD,
        },
        "decision": "advance_to_s2" if passes_kill_test else "falsified_l3a",
    }


@dataclass
class L3StablecoinTimingService:
    """S1 kill-test driver: fetch BTC weekly price + stablecoin supply, run IC test.

    research-only; computes diagnostics and a kill-test verdict, takes no positions
    and never touches live / ``run-once``.
    """

    settings: Settings
    public_exchange: Any | None = None

    def _fetch_daily_close(self, *, symbol: str, start_ms: int, end_ms: int) -> list[list[float]]:
        # Use the linear-futures market (fapi) like the rest of the research line; the
        # spot api.binance.com endpoint is geo-blocked on the production host, and the
        # weekly perpetual close is equivalent for this timing kill-test.
        futures_settings = replace(self.settings, market_type="future")
        exchange = self.public_exchange or build_exchange(futures_settings, private=False)
        markets = call_with_time_sync_retry(exchange, exchange.load_markets)
        resolved = resolve_market_symbols(markets, (symbol,), futures_settings)
        resolved_symbol = resolved[0] if resolved else symbol
        rows: list[list[float]] = []
        cursor = max(start_ms, 0)
        timeframe_ms = timeframe_to_ms("1d")
        last_timestamp: int | None = None
        while cursor <= end_ms:
            batch = call_with_time_sync_retry(
                exchange, exchange.fetch_ohlcv, resolved_symbol, timeframe="1d", since=cursor, limit=1000
            )
            if not batch:
                break
            added = 0
            for row in batch:
                timestamp = int(row[0])
                if timestamp < start_ms or timestamp > end_ms:
                    continue
                if last_timestamp is not None and timestamp <= last_timestamp:
                    continue
                rows.append(
                    [
                        timestamp,
                        _coerce_float(row[1]) or 0.0,
                        _coerce_float(row[2]) or 0.0,
                        _coerce_float(row[3]) or 0.0,
                        _coerce_float(row[4]) or 0.0,
                        _coerce_float(row[5]) or 0.0,
                    ]
                )
                last_timestamp = timestamp
                added += 1
            if added == 0:
                break
            cursor = int(rows[-1][0]) + timeframe_ms
        return rows

    def run(
        self,
        *,
        start_ms: int,
        end_ms: int,
        symbol: str = "BTC/USDT",
        signal_lookback_weeks_grid: list[int] | None = None,
        horizon_weeks_grid: list[int] | None = None,
        cost_per_side_pct: float | None = None,
        supply_cache_path: str | Path | None = None,
        price_cache_path: str | Path | None = None,
        url: str = DEFILLAMA_STABLECOIN_CHARTS_URL,
        field_path: tuple[str, ...] = DEFAULT_STABLECOIN_SUPPLY_FIELD,
        supply_fetcher: Callable[[str], Any] | None = None,
        price_rows: list[list[float]] | None = None,
        force_refresh: bool = False,
        holdout_role: str = "discovery",
    ) -> dict[str, Any]:
        lookback_grid = signal_lookback_weeks_grid or [4, 8, 13]
        horizon_grid = horizon_weeks_grid or [1, 2, 3, 4]
        if cost_per_side_pct is None:
            cost_per_side_pct = max(float(self.settings.estimated_fee_pct), 0.0) + max(
                float(self.settings.estimated_slippage_pct), 0.0
            )

        raw_supply, supply_source = fetch_stablecoin_supply_raw(
            settings=self.settings,
            cache_path=supply_cache_path,
            url=url,
            fetcher=supply_fetcher,
            force_refresh=force_refresh,
        )
        supply_series = normalize_stablecoin_supply_series(raw_supply, field_path=field_path)

        # Buffer the price fetch so the longest signal lookback has history before start.
        price_start_ms = start_ms - max(lookback_grid) * WEEK_MS - WEEK_MS
        price_source = "injected"
        if price_rows is not None:
            raw_price = price_rows
        elif price_cache_path is not None and not force_refresh and load_cached_supply(price_cache_path) is not None:
            raw_price = load_cached_supply(price_cache_path)
            price_source = "cache"
        else:
            raw_price = self._fetch_daily_close(symbol=symbol, start_ms=price_start_ms, end_ms=end_ms)
            price_source = "network"
            if price_cache_path is not None:
                _write_cache(price_cache_path, raw_price)
        price_series = normalize_close_series(raw_price)

        anchors = weekly_anchors(start_ms, end_ms)
        result = evaluate_l3a_stablecoin_timing(
            supply_series=supply_series,
            price_series=price_series,
            anchors_ms=anchors,
            signal_lookback_weeks_grid=lookback_grid,
            horizon_weeks_grid=horizon_grid,
            cost_per_side_pct=cost_per_side_pct,
            holdout_role=holdout_role,
        )
        result.update(
            {
                "version": L3_INFORMATION_EDGE_VERSION,
                "source": "defillama_stablecoin_supply_vs_btc_weekly",
                "symbol": symbol,
                "supply_fetched_from": supply_source,
                "price_fetched_from": price_source,
                "supply_point_count": len(supply_series),
                "price_point_count": len(price_series),
                "signal_lookback_weeks_grid": list(lookback_grid),
                "horizon_weeks_grid": list(horizon_grid),
                "window_start_utc": _utc_iso_from_ms(start_ms),
                "window_end_utc": _utc_iso_from_ms(end_ms),
                "supply_cache_path": None if supply_cache_path is None else str(supply_cache_path),
                "price_cache_path": None if price_cache_path is None else str(price_cache_path),
            }
        )
        return result


# ---------------------------------------------------------------------------
# S1 kill-test (L3b): chain TVL growth -> token weekly cross-sectional forward
# ---------------------------------------------------------------------------

DEFILLAMA_CHAIN_TVL_URL_TEMPLATE = "https://api.llama.fi/v2/historicalChainTvl/{chain}"
L3B_FAMILY = "l3b_chain_tvl_xs"
DEFAULT_CHAIN_TVL_FIELD: tuple[str, ...] = ("tvl",)
# Plan §2/§10.2 cross-sectional required IC under the majors correlation ceiling
# (r̄≈0.63 -> effective breadth ~1.6). L3b only escapes this if the TVL signal makes
# the *signal-dimension* effective breadth materially exceed it (plan: > 2.5).
L3B_IC_REFERENCE = 0.15
L3B_BREADTH_ESCAPE_THRESHOLD = 2.5
L3B_DSR_PASS_THRESHOLD = 0.95
L3B_PBO_PASS_THRESHOLD = 0.5

# Chain tokens that (a) trade on Binance USDT-margined futures and (b) have a
# DefiLlama chain-TVL series, so chain traction is the token's on-chain signal.
L3B_DEFAULT_CHAIN_TOKEN_MAP: dict[str, str] = {
    "ETH/USDT": "Ethereum",
    "SOL/USDT": "Solana",
    "BNB/USDT": "BSC",
    "AVAX/USDT": "Avalanche",
    "ARB/USDT": "Arbitrum",
    "SUI/USDT": "Sui",
    "TRX/USDT": "Tron",
    "OP/USDT": "OP_Mainnet",
    "APT/USDT": "Aptos",
    "NEAR/USDT": "Near",
    "POL/USDT": "Polygon",
    "ADA/USDT": "Cardano",
}


def fetch_chain_tvl_raw(
    chain: str,
    *,
    settings: Settings | None = None,
    cache_path: str | Path | None = None,
    url_template: str = DEFILLAMA_CHAIN_TVL_URL_TEMPLATE,
    fetcher: Callable[[str], Any] | None = None,
    force_refresh: bool = False,
) -> tuple[Any, str]:
    """Fetch DefiLlama historical chain TVL rows ([{date, tvl}, ...]), with cache."""

    url = url_template.format(chain=chain)
    if cache_path is not None and not force_refresh:
        cached = load_cached_supply(cache_path)
        if cached is not None:
            return cached, "cache"
    raw_rows = fetcher(url) if fetcher is not None else _default_http_get_json(url, settings=settings)
    if cache_path is not None:
        _write_cache(cache_path, raw_rows)
    return raw_rows, "network"


def _panel_effective_breadth(return_panel: dict[str, list[float | None]]) -> dict[str, Any]:
    """Mean absolute pairwise return correlation -> Grinold effective breadth.

    effective_breadth = N / (1 + (N-1)·r̄). This is the same diagnostic that pinned the
    price/volume cross-section at ~1.6 in §7; L3b must report it so a breadth illusion
    cannot hide behind a rank-IC number.
    """

    tokens = list(return_panel)
    n = len(tokens)
    if n < 2:
        return {"symbol_count": n, "mean_abs_pairwise_corr": None, "effective_breadth": float(n)}
    abs_corrs: list[float] = []
    for left, right in itertools.combinations(tokens, 2):
        xs: list[float] = []
        ys: list[float] = []
        for a, b in zip(return_panel[left], return_panel[right]):
            if a is not None and b is not None:
                xs.append(a)
                ys.append(b)
        corr = pearson_correlation(xs, ys)
        if corr is not None:
            abs_corrs.append(abs(corr))
    r_bar = (sum(abs_corrs) / len(abs_corrs)) if abs_corrs else 0.0
    effective = n / (1.0 + (n - 1) * r_bar)
    return {"symbol_count": n, "mean_abs_pairwise_corr": r_bar, "effective_breadth": effective}


def _l3b_long_short_weights(
    signal_by_token: dict[str, float], top_fraction: float
) -> dict[str, float]:
    """Equal-weight long top fraction / short bottom fraction by signal rank."""

    ranked = sorted(signal_by_token.items(), key=lambda item: item[1])
    count = len(ranked)
    if count < 2:
        return {}
    k = max(1, int(count * top_fraction))
    k = min(k, count // 2)
    weights: dict[str, float] = {}
    for token, _signal in ranked[:k]:
        weights[token] = -1.0 / k
    for token, _signal in ranked[-k:]:
        weights[token] = 1.0 / k
    return weights


def evaluate_l3b_chain_tvl_cross_section(
    *,
    tvl_series_by_token: dict[str, list[SupplyPoint]],
    price_series_by_token: dict[str, list[SupplyPoint]],
    anchors_ms: list[int],
    signal_lookback_weeks_grid: list[int],
    horizon_weeks_grid: list[int],
    cost_per_side_pct: float,
    top_fraction: float = 0.25,
    min_cross_section_tokens: int = 4,
    holdout_role: str = "discovery",
) -> dict[str, Any]:
    """Cross-sectional rank-IC kill-test for L3b (chain TVL growth -> token returns).

    For each (lookback L, horizon h) config, at every weekly anchor build the
    cross-section of tokens with a valid TVL log-growth signal and an h-week forward
    return, take the per-anchor Spearman rank-IC, and average it. A weekly-rebalanced
    long-short of the same ranking (overlap-averaged over h claims) provides the return
    series for DSR/PBO. The price-return effective breadth is reported alongside, since
    §2 says L3b only escapes the majors correlation ceiling if the signal lifts effective
    breadth past ~2.5. research-only; no positions, no live impact.
    """

    tokens = list(tvl_series_by_token)
    n = len(anchors_ms)
    price_at = {t: [asof_supply_at(price_series_by_token.get(t, []), a) for a in anchors_ms] for t in tokens}
    tvl_at = {t: [asof_supply_at(tvl_series_by_token.get(t, []), a) for a in anchors_ms] for t in tokens}
    weekly_ret: dict[str, list[float | None]] = {}
    for t in tokens:
        series: list[float | None] = []
        for i in range(n):
            if i + 1 < n and price_at[t][i] and price_at[t][i + 1] and price_at[t][i] > 0.0:
                series.append(price_at[t][i + 1] / price_at[t][i] - 1.0)
            else:
                series.append(None)
        weekly_ret[t] = series
    breadth = _panel_effective_breadth(weekly_ret)

    cells: list[dict[str, Any]] = []
    for lookback in signal_lookback_weeks_grid:
        signal: dict[str, list[float | None]] = {}
        for t in tokens:
            sig: list[float | None] = []
            for i in range(n):
                if i >= lookback and tvl_at[t][i] and tvl_at[t][i - lookback] and tvl_at[t][i - lookback] > 0.0:
                    sig.append(math.log(tvl_at[t][i] / tvl_at[t][i - lookback]))
                else:
                    sig.append(None)
            signal[t] = sig
        for horizon in horizon_weeks_grid:
            per_anchor_ic: list[float] = []
            total_pairs = 0
            for i in range(n):
                cs_signal: list[float] = []
                cs_forward: list[float] = []
                for t in tokens:
                    s = signal[t][i]
                    j = i + horizon
                    if s is None or j >= n:
                        continue
                    if price_at[t][i] and price_at[t][j] and price_at[t][i] > 0.0:
                        cs_signal.append(s)
                        cs_forward.append(price_at[t][j] / price_at[t][i] - 1.0)
                if len(cs_signal) >= min_cross_section_tokens:
                    ic = spearman_rank_correlation(cs_signal, cs_forward)
                    if ic is not None:
                        per_anchor_ic.append(ic)
                        total_pairs += len(cs_signal)
            rank_ic_mean = (sum(per_anchor_ic) / len(per_anchor_ic)) if per_anchor_ic else None
            rank_ic_t_stat = _t_stat(per_anchor_ic)

            # Overlap-averaged weekly long-short return series for DSR/PBO.
            weight_history: list[dict[str, float]] = []
            weekly_net: list[float] = []
            period_returns: dict[int, float] = {}
            previous_weights: dict[str, float] = {}
            for i in range(n):
                signal_now = {t: signal[t][i] for t in tokens if signal[t][i] is not None}
                target = _l3b_long_short_weights(signal_now, top_fraction) if len(signal_now) >= min_cross_section_tokens else {}
                weight_history.append(target)
                window = weight_history[max(i - horizon + 1, 0): i + 1]
                avg_weights: dict[str, float] = {}
                for weights in window:
                    for token, weight in weights.items():
                        avg_weights[token] = avg_weights.get(token, 0.0) + weight
                if window:
                    for token in list(avg_weights):
                        avg_weights[token] /= len(window)
                pnl = 0.0
                priced = False
                for token, weight in avg_weights.items():
                    r = weekly_ret[token][i]
                    if r is not None:
                        pnl += weight * r
                        priced = True
                if not priced and not previous_weights:
                    continue
                all_tokens = set(avg_weights) | set(previous_weights)
                turnover = sum(abs(avg_weights.get(token, 0.0) - previous_weights.get(token, 0.0)) for token in all_tokens)
                net = pnl - cost_per_side_pct * turnover
                weekly_net.append(net)
                period_returns[anchors_ms[i]] = net
                previous_weights = avg_weights

            cells.append(
                {
                    "family": L3B_FAMILY,
                    "frequency": WEEKLY_FREQUENCY_LABEL,
                    "signal_lookback_bars": int(lookback),
                    "holding_bars": int(horizon),
                    "signal_lookback_weeks": int(lookback),
                    "horizon_weeks": int(horizon),
                    "anchor_ic_count": len(per_anchor_ic),
                    "cross_section_pair_count": total_pairs,
                    "rank_ic_mean": rank_ic_mean,
                    "rank_ic_t_stat": rank_ic_t_stat,
                    "net_sum_return_pct": sum(weekly_net),
                    "portfolio_sharpe": _sharpe(weekly_net, WEEKLY_FREQUENCY_LABEL),
                    "portfolio_period_count": len(weekly_net),
                    "period_returns_by_timestamp": period_returns,
                }
            )

    scored = [cell for cell in cells if isinstance(cell.get("rank_ic_mean"), (int, float))]
    best_cell = max(scored, key=lambda cell: abs(float(cell["rank_ic_mean"])), default=None)
    deflated = compute_directional_deflated_sharpe(cells)
    pbo = compute_directional_pbo(cells)

    best_abs_ic = abs(float(best_cell["rank_ic_mean"])) if best_cell else None
    dsr_value = deflated.get("deflated_sharpe_ratio") if deflated else None
    pbo_value = pbo.get("pbo") if pbo else None
    effective_breadth = breadth["effective_breadth"]

    ic_pass = best_abs_ic is not None and best_abs_ic >= L3B_IC_REFERENCE
    breadth_escape = isinstance(effective_breadth, (int, float)) and effective_breadth > L3B_BREADTH_ESCAPE_THRESHOLD
    net_pass = bool(best_cell) and float(best_cell["net_sum_return_pct"]) > 0.0
    dsr_pass = isinstance(dsr_value, (int, float)) and dsr_value >= L3B_DSR_PASS_THRESHOLD
    pbo_pass = isinstance(pbo_value, (int, float)) and pbo_value < L3B_PBO_PASS_THRESHOLD
    passes_kill_test = bool(ic_pass and net_pass and dsr_pass and pbo_pass)

    for cell in cells:
        cell.pop("period_returns_by_timestamp", None)

    return {
        "family": L3B_FAMILY,
        "holdout_role": holdout_role,
        "cost_per_side_pct": cost_per_side_pct,
        "top_fraction": top_fraction,
        "anchor_count": n,
        "token_count": len(tokens),
        "tokens": tokens,
        "effective_breadth": breadth,
        "cells": cells,
        "best_cell": best_cell,
        "best_abs_rank_ic": best_abs_ic,
        "ic_reference": L3B_IC_REFERENCE,
        "breadth_escape_threshold": L3B_BREADTH_ESCAPE_THRESHOLD,
        "deflated_sharpe": deflated,
        "pbo": pbo,
        "kill_test": {
            "ic_pass": ic_pass,
            "breadth_escape": breadth_escape,
            "net_pass": net_pass,
            "dsr_pass": dsr_pass,
            "pbo_pass": pbo_pass,
            "passes_kill_test": passes_kill_test,
            "dsr_pass_threshold": L3B_DSR_PASS_THRESHOLD,
            "pbo_pass_threshold": L3B_PBO_PASS_THRESHOLD,
        },
        "decision": "advance_to_s2" if passes_kill_test else "falsified_l3b",
    }


@dataclass
class L3ChainTvlCrossSectionService:
    """S1 kill-test driver for L3b: chain TVL growth -> token weekly cross-section."""

    settings: Settings
    public_exchange: Any | None = None

    def _fetch_daily_close(self, *, symbol: str, start_ms: int, end_ms: int) -> list[list[float]]:
        return L3StablecoinTimingService(self.settings, self.public_exchange)._fetch_daily_close(
            symbol=symbol, start_ms=start_ms, end_ms=end_ms
        )

    def run(
        self,
        *,
        start_ms: int,
        end_ms: int,
        chain_token_map: dict[str, str] | None = None,
        signal_lookback_weeks_grid: list[int] | None = None,
        horizon_weeks_grid: list[int] | None = None,
        cost_per_side_pct: float | None = None,
        top_fraction: float = 0.25,
        min_cross_section_tokens: int = 4,
        cache_dir: str | Path | None = None,
        url_template: str = DEFILLAMA_CHAIN_TVL_URL_TEMPLATE,
        tvl_fetcher: Callable[[str], Any] | None = None,
        price_rows_by_token: dict[str, list[list[float]]] | None = None,
        force_refresh: bool = False,
        holdout_role: str = "discovery",
    ) -> dict[str, Any]:
        mapping = chain_token_map or L3B_DEFAULT_CHAIN_TOKEN_MAP
        lookback_grid = signal_lookback_weeks_grid or [4, 8, 13]
        horizon_grid = horizon_weeks_grid or [1, 2, 4]
        if cost_per_side_pct is None:
            cost_per_side_pct = max(float(self.settings.estimated_fee_pct), 0.0) + max(
                float(self.settings.estimated_slippage_pct), 0.0
            )
        price_start_ms = start_ms - max(lookback_grid) * WEEK_MS - WEEK_MS

        tvl_series_by_token: dict[str, list[SupplyPoint]] = {}
        price_series_by_token: dict[str, list[SupplyPoint]] = {}
        tvl_sources: dict[str, str] = {}
        price_sources: dict[str, str] = {}
        for token, chain in mapping.items():
            tvl_cache = None if cache_dir is None else Path(cache_dir) / f"tvl_{chain}.json"
            raw_tvl, tvl_source = fetch_chain_tvl_raw(
                chain,
                settings=self.settings,
                cache_path=tvl_cache,
                url_template=url_template,
                fetcher=tvl_fetcher,
                force_refresh=force_refresh,
            )
            tvl_series_by_token[token] = normalize_stablecoin_supply_series(raw_tvl, field_path=DEFAULT_CHAIN_TVL_FIELD)
            tvl_sources[token] = tvl_source

            if price_rows_by_token is not None:
                raw_price = price_rows_by_token.get(token, [])
                price_source = "injected"
            else:
                price_cache = None if cache_dir is None else Path(cache_dir) / f"price_{token.replace('/', '_')}.json"
                if price_cache is not None and not force_refresh and load_cached_supply(price_cache) is not None:
                    raw_price = load_cached_supply(price_cache)
                    price_source = "cache"
                else:
                    raw_price = self._fetch_daily_close(symbol=token, start_ms=price_start_ms, end_ms=end_ms)
                    price_source = "network"
                    if price_cache is not None:
                        _write_cache(price_cache, raw_price)
            price_series_by_token[token] = normalize_close_series(raw_price)
            price_sources[token] = price_source

        anchors = weekly_anchors(start_ms, end_ms)
        result = evaluate_l3b_chain_tvl_cross_section(
            tvl_series_by_token=tvl_series_by_token,
            price_series_by_token=price_series_by_token,
            anchors_ms=anchors,
            signal_lookback_weeks_grid=lookback_grid,
            horizon_weeks_grid=horizon_grid,
            cost_per_side_pct=cost_per_side_pct,
            top_fraction=top_fraction,
            min_cross_section_tokens=min_cross_section_tokens,
            holdout_role=holdout_role,
        )
        result.update(
            {
                "version": L3_INFORMATION_EDGE_VERSION,
                "source": "defillama_chain_tvl_vs_token_weekly",
                "chain_token_map": dict(mapping),
                "tvl_fetched_from": tvl_sources,
                "price_fetched_from": price_sources,
                "tvl_point_counts": {t: len(s) for t, s in tvl_series_by_token.items()},
                "price_point_counts": {t: len(s) for t, s in price_series_by_token.items()},
                "signal_lookback_weeks_grid": list(lookback_grid),
                "horizon_weeks_grid": list(horizon_grid),
                "window_start_utc": _utc_iso_from_ms(start_ms),
                "window_end_utc": _utc_iso_from_ms(end_ms),
                "cache_dir": None if cache_dir is None else str(cache_dir),
            }
        )
        return result
