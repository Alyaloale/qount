"""L1 cross-asset trend research data layer (restart line, attacks BR).

After §7 (price/volume) and L3 (slow non-price data) both falsified on the *breadth*
ceiling — crypto majors r̄≈0.63 -> effective breadth ~1.6 — the L1 restart attacks the
binding term of ``IR = IC × √BR`` head-on: swap the universe from co-moving crypto
majors to a genuinely low-correlation cross-asset panel (equities / bonds / commodities
/ FX / crypto), where time-series-momentum breadth can be much larger.

This module is the L1 data layer + the first, cheapest kill-test: fetch a free
cross-asset daily EOD panel (Tiingo), cache it under ``state/`` for offline replay,
and measure the panel's *effective breadth*. If effective breadth does not materially
exceed the ~1.6 ceiling, the whole L1 thesis is falsified before any broker is opened.
The time-series-momentum IR / DSR / PBO read is a later round.

research-only; nothing here is imported by the live / ``run-once`` path. Cross-asset
free no-key sources (Stooq / Yahoo / FRED) are unreachable from the production host, so
this uses Tiingo, which needs a free API key (``QOUNT_TIINGO_API_KEY``).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Callable

from qount.legacy.l3.l3_information_edge import SupplyPoint
from qount.legacy.l3.l3_information_edge import WEEK_MS
from qount.legacy.l3.l3_information_edge import WEEKLY_FREQUENCY_LABEL
from qount.legacy.l3.l3_information_edge import _coerce_float
from qount.legacy.l3.l3_information_edge import _panel_effective_breadth
from qount.legacy.l3.l3_information_edge import _utc_iso_from_ms
from qount.legacy.l3.l3_information_edge import _write_cache
from qount.legacy.l3.l3_information_edge import asof_supply_at
from qount.legacy.l3.l3_information_edge import load_cached_supply
from qount.legacy.l3.l3_information_edge import weekly_anchors
from qount.settings import Settings
from qount.strategy_selection import _sharpe
from qount.strategy_selection import compute_directional_deflated_sharpe
from qount.strategy_selection import compute_directional_pbo


L1_CROSS_ASSET_VERSION = "l1_cross_asset_v1"

TIINGO_EOD_URL_TEMPLATE = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
DEFAULT_TIINGO_START_DATE = "2010-01-01"
DEFAULT_TIINGO_PRICE_FIELD = "adjClose"

# Effective breadth must materially exceed the §7 majors ceiling (~1.6). The L3b
# escape threshold (2.5) is reused: below it, required IC stays ~0.15 and L1 is no
# better off than the price/volume cross-section.
L1_BREADTH_ESCAPE_THRESHOLD = 2.5

# A liquid cross-asset ETF panel, all covered by Tiingo's free tier. BTC is added
# separately via the already-reachable Binance feed (kept out of this default).
L1_DEFAULT_CROSS_ASSET_PANEL: tuple[str, ...] = (
    "SPY",  # US large-cap equity
    "EFA",  # developed ex-US equity
    "EEM",  # emerging-market equity
    "TLT",  # long US Treasuries
    "IEF",  # intermediate US Treasuries
    "LQD",  # investment-grade credit
    "HYG",  # high-yield credit
    "GLD",  # gold
    "SLV",  # silver
    "DBC",  # broad commodities
    "USO",  # crude oil
    "UUP",  # US dollar index
    "VNQ",  # US REITs
)


def _parse_iso_date_to_ms(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # Fall back to a plain date (YYYY-MM-DD).
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def normalize_tiingo_eod(
    raw_rows: Any, *, field: str = DEFAULT_TIINGO_PRICE_FIELD
) -> list[SupplyPoint]:
    """Convert Tiingo EOD rows ([{date, adjClose, ...}, ...]) into a close series.

    Uses the adjusted close so splits/dividends do not inject spurious jumps. No
    look-ahead: each point keeps its own observation date. Rows missing the field,
    with an unparseable date, or with a non-positive price are skipped.
    """

    if not isinstance(raw_rows, list):
        return []
    by_timestamp: dict[int, float] = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        timestamp_ms = _parse_iso_date_to_ms(row.get("date"))
        value = _coerce_float(row.get(field))
        if timestamp_ms is None or value is None or value <= 0.0:
            continue
        by_timestamp[timestamp_ms] = value
    return [SupplyPoint(timestamp_ms=ts, value=by_timestamp[ts]) for ts in sorted(by_timestamp)]


def _tiingo_get_json(url: str, *, attempts: int = 3) -> Any:
    # Tiingo is reachable directly from the production host (no proxy needed, unlike
    # Binance); keep this a plain direct opener. A small retry rides out the transient
    # SSL/connection drops seen when fetching a large panel sequentially.
    request = urllib.request.Request(
        url, headers={"User-Agent": "qount-l1-research/1.0", "Content-Type": "application/json"}
    )
    last_error: Exception | None = None
    for _attempt in range(max(1, attempts)):
        try:
            with urllib.request.build_opener().open(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last_error = error
    raise last_error if last_error is not None else RuntimeError("tiingo fetch failed")


def fetch_tiingo_eod_raw(
    ticker: str,
    *,
    api_key: str | None,
    cache_path: str | Path | None = None,
    start_date: str = DEFAULT_TIINGO_START_DATE,
    url_template: str = TIINGO_EOD_URL_TEMPLATE,
    fetcher: Callable[[str], Any] | None = None,
    force_refresh: bool = False,
) -> tuple[Any, str]:
    """Fetch raw Tiingo EOD rows for one ticker, with optional state cache.

    Returns ``(raw_rows, source)`` where ``source`` is ``"cache"`` or ``"network"``.
    ``fetcher`` lets tests inject a payload without the network (and without a key).
    """

    if cache_path is not None and not force_refresh:
        cached = load_cached_supply(cache_path)
        if cached is not None:
            return cached, "cache"
    base = url_template.format(ticker=ticker.lower())
    url = f"{base}?startDate={start_date}&format=json&token={api_key or ''}"
    raw_rows = fetcher(url) if fetcher is not None else _tiingo_get_json(url)
    if cache_path is not None:
        _write_cache(cache_path, raw_rows)
    return raw_rows, "network"


_MISSING_KEY_DETAIL = "Set QOUNT_TIINGO_API_KEY in .env (free key at tiingo.com) to run the L1 kill-tests."


def fetch_cross_asset_panel(
    *,
    settings: Settings,
    tickers: list[str],
    api_key: str | None = None,
    start_date: str = DEFAULT_TIINGO_START_DATE,
    cache_dir: str | Path | None = None,
    field: str = DEFAULT_TIINGO_PRICE_FIELD,
    fetcher: Callable[[str], Any] | None = None,
    force_refresh: bool = False,
) -> tuple[dict[str, list[SupplyPoint]], dict[str, str], dict[str, int]]:
    """Fetch + cache + normalize a Tiingo EOD panel into per-ticker close series.

    Returns ``(series_by_ticker, sources, point_counts)``. The caller is responsible
    for the missing-key guard (this is exercised by both L1 kill-tests).
    """

    resolved_key = api_key or settings.tiingo_api_key
    series_by_ticker: dict[str, list[SupplyPoint]] = {}
    sources: dict[str, str] = {}
    point_counts: dict[str, int] = {}
    for ticker in tickers:
        cache_path = None if cache_dir is None else Path(cache_dir) / f"tiingo_{ticker.upper()}.json"
        raw, source = fetch_tiingo_eod_raw(
            ticker,
            api_key=resolved_key,
            cache_path=cache_path,
            start_date=start_date,
            fetcher=fetcher,
            force_refresh=force_refresh,
        )
        series_by_ticker[ticker] = normalize_tiingo_eod(raw, field=field)
        sources[ticker] = source
        point_counts[ticker] = len(series_by_ticker[ticker])
    return series_by_ticker, sources, point_counts


@dataclass
class L1CrossAssetBreadthService:
    """L1 first kill-test: fetch the cross-asset panel and measure effective breadth.

    This decides the central L1 thesis (does a cross-asset universe escape the ~1.6
    majors breadth ceiling?) before any broker step. No positions, no IC yet.
    """

    settings: Settings

    def run(
        self,
        *,
        start_ms: int,
        end_ms: int,
        tickers: list[str] | None = None,
        api_key: str | None = None,
        start_date: str = DEFAULT_TIINGO_START_DATE,
        cache_dir: str | Path | None = None,
        field: str = DEFAULT_TIINGO_PRICE_FIELD,
        fetcher: Callable[[str], Any] | None = None,
        force_refresh: bool = False,
        holdout_role: str = "discovery",
    ) -> dict[str, Any]:
        panel = tickers or list(L1_DEFAULT_CROSS_ASSET_PANEL)
        resolved_key = api_key or self.settings.tiingo_api_key
        if resolved_key is None and fetcher is None:
            return {
                "version": L1_CROSS_ASSET_VERSION,
                "source": "tiingo_cross_asset_eod",
                "error": "missing_tiingo_api_key",
                "detail": _MISSING_KEY_DETAIL,
                "tickers": panel,
            }

        price_series_by_ticker, sources, point_counts = fetch_cross_asset_panel(
            settings=self.settings,
            tickers=panel,
            api_key=api_key,
            start_date=start_date,
            cache_dir=cache_dir,
            field=field,
            fetcher=fetcher,
            force_refresh=force_refresh,
        )

        anchors = weekly_anchors(start_ms, end_ms)
        return_panel: dict[str, list[float | None]] = {}
        coverage: dict[str, int] = {}
        for ticker, series in price_series_by_ticker.items():
            price_at = [asof_supply_at(series, anchor) for anchor in anchors]
            weekly: list[float | None] = []
            covered = 0
            for i in range(len(anchors)):
                if i + 1 < len(anchors) and price_at[i] and price_at[i + 1] and price_at[i] > 0.0:
                    weekly.append(price_at[i + 1] / price_at[i] - 1.0)
                    covered += 1
                else:
                    weekly.append(None)
            return_panel[ticker] = weekly
            coverage[ticker] = covered

        # Only keep tickers with enough weekly coverage in the breadth panel.
        covered_panel = {t: series for t, series in return_panel.items() if coverage[t] >= 2}
        breadth = _panel_effective_breadth(covered_panel)
        effective_breadth = breadth["effective_breadth"]
        breadth_escape = isinstance(effective_breadth, (int, float)) and effective_breadth > L1_BREADTH_ESCAPE_THRESHOLD

        return {
            "version": L1_CROSS_ASSET_VERSION,
            "source": "tiingo_cross_asset_eod",
            "holdout_role": holdout_role,
            "frequency": WEEKLY_FREQUENCY_LABEL,
            "tickers": panel,
            "fetched_from": sources,
            "price_point_counts": point_counts,
            "weekly_coverage": coverage,
            "anchor_count": len(anchors),
            "panel_size_in_breadth": len(covered_panel),
            "effective_breadth": breadth,
            "breadth_escape_threshold": L1_BREADTH_ESCAPE_THRESHOLD,
            "breadth_escape": breadth_escape,
            "window_start_utc": _utc_iso_from_ms(start_ms),
            "window_end_utc": _utc_iso_from_ms(end_ms),
            "cache_dir": None if cache_dir is None else str(cache_dir),
            "decision": "breadth_supports_l1" if breadth_escape else "breadth_ceiling_holds",
        }


# ---------------------------------------------------------------------------
# S2: cross-asset time-series momentum (trend) IR / DSR / PBO
# ---------------------------------------------------------------------------

L1_TSMOM_FAMILY = "l1_tsmom"
DEFAULT_TSMOM_LOOKBACK_WEEKS_GRID: tuple[int, ...] = (13, 26, 52)
DEFAULT_TSMOM_VOL_LOOKBACK_WEEKS = 26
# Annualized net Sharpe (IR) the trend portfolio must clear to be worth S3, plus the
# DSR/PBO multiple-testing gates. Classic cross-asset TSMOM runs ~0.8-1.2 gross.
L1_TSMOM_IR_PASS_THRESHOLD = 0.5
L1_TSMOM_DSR_PASS_THRESHOLD = 0.95
L1_TSMOM_PBO_PASS_THRESHOLD = 0.5
_WEEKS_PER_YEAR = (365.0 * 24.0 * 60.0 * 60.0 * 1000.0) / WEEK_MS


def _std_sample(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return var ** 0.5


def evaluate_l1_timeseries_momentum(
    *,
    price_series_by_ticker: dict[str, list[SupplyPoint]],
    anchors_ms: list[int],
    lookback_weeks_grid: list[int],
    vol_lookback_weeks: int,
    cost_per_side_pct: float,
    holdout_role: str = "discovery",
) -> dict[str, Any]:
    """Cross-asset time-series momentum (Moskowitz-Ooi-Pedersen style) kill-test.

    For each lookback L config: at every weekly anchor, each instrument's position is
    ``sign(trailing L-week return)`` scaled inversely by its trailing realized weekly
    volatility (decision-time only, no leak), normalized to unit gross exposure across
    instruments. The portfolio's weekly net return (after per-side turnover cost) feeds
    the reused annualized Sharpe / DSR / PBO harness. Each lookback is a trial so DSR
    penalizes the lookback search. research-only; no positions, no live impact.
    """

    tickers = list(price_series_by_ticker)
    n = len(anchors_ms)
    price_at = {t: [asof_supply_at(price_series_by_ticker[t], a) for a in anchors_ms] for t in tickers}
    weekly_ret: dict[str, list[float | None]] = {}
    for t in tickers:
        series: list[float | None] = []
        for i in range(n):
            if i + 1 < n and price_at[t][i] and price_at[t][i + 1] and price_at[t][i] > 0.0:
                series.append(price_at[t][i + 1] / price_at[t][i] - 1.0)
            else:
                series.append(None)
        weekly_ret[t] = series
    breadth = _panel_effective_breadth({t: weekly_ret[t] for t in tickers})

    cells: list[dict[str, Any]] = []
    yearly_by_config: dict[int, dict[str, float]] = {}
    for lookback in lookback_weeks_grid:
        weekly_net: list[float] = []
        weekly_gross: list[float] = []
        period_returns: dict[int, float] = {}
        previous_weights: dict[str, float] = {}
        yearly_net: dict[str, float] = {}
        for i in range(n):
            raw_weights: dict[str, float] = {}
            for t in tickers:
                if i < lookback or i < vol_lookback_weeks:
                    continue
                p_now = price_at[t][i]
                p_then = price_at[t][i - lookback]
                if not (p_now and p_then and p_then > 0.0):
                    continue
                trailing = p_now / p_then - 1.0
                sign = 1.0 if trailing > 0 else (-1.0 if trailing < 0 else 0.0)
                if sign == 0.0:
                    continue
                vol_window = [weekly_ret[t][k] for k in range(i - vol_lookback_weeks, i) if weekly_ret[t][k] is not None]
                vol = _std_sample(vol_window)
                if vol <= 0.0:
                    continue
                raw_weights[t] = sign / vol
            gross_norm = sum(abs(w) for w in raw_weights.values())
            weights = {t: w / gross_norm for t, w in raw_weights.items()} if gross_norm > 0.0 else {}
            # Realized forward (t->t+1) portfolio return.
            port = 0.0
            priced = False
            for t, w in weights.items():
                r = weekly_ret[t][i]
                if r is not None:
                    port += w * r
                    priced = True
            if not priced and not previous_weights:
                continue
            all_t = set(weights) | set(previous_weights)
            turnover = sum(abs(weights.get(t, 0.0) - previous_weights.get(t, 0.0)) for t in all_t)
            net = port - cost_per_side_pct * turnover
            weekly_gross.append(port)
            weekly_net.append(net)
            period_returns[anchors_ms[i]] = net
            year = _utc_iso_from_ms(anchors_ms[i])[:4]
            yearly_net[year] = yearly_net.get(year, 0.0) + net
            previous_weights = weights

        cells.append(
            {
                "family": L1_TSMOM_FAMILY,
                "frequency": WEEKLY_FREQUENCY_LABEL,
                "signal_lookback_bars": int(lookback),
                "holding_bars": 1,
                "lookback_weeks": int(lookback),
                "net_sum_return_pct": sum(weekly_net),
                "gross_sum_return_pct": sum(weekly_gross),
                "portfolio_sharpe": _sharpe(weekly_net, WEEKLY_FREQUENCY_LABEL),
                "gross_sharpe": _sharpe(weekly_gross, WEEKLY_FREQUENCY_LABEL),
                "portfolio_period_count": len(weekly_net),
                "period_returns_by_timestamp": period_returns,
            }
        )
        yearly_by_config[int(lookback)] = yearly_net

    scored = [c for c in cells if isinstance(c.get("portfolio_sharpe"), (int, float))]
    best_cell = max(scored, key=lambda c: float(c["portfolio_sharpe"]), default=None)
    deflated = compute_directional_deflated_sharpe(cells)
    pbo = compute_directional_pbo(cells)

    best_sharpe = float(best_cell["portfolio_sharpe"]) if best_cell else None
    dsr_value = deflated.get("deflated_sharpe_ratio") if deflated else None
    pbo_value = pbo.get("pbo") if pbo else None
    effective_breadth = breadth["effective_breadth"]
    br_annual = (effective_breadth * _WEEKS_PER_YEAR) if isinstance(effective_breadth, (int, float)) else None
    ic_required = (1.0 / (br_annual ** 0.5)) if br_annual and br_annual > 0 else None

    ir_pass = best_sharpe is not None and best_sharpe >= L1_TSMOM_IR_PASS_THRESHOLD
    net_pass = bool(best_cell) and float(best_cell["net_sum_return_pct"]) > 0.0
    dsr_pass = isinstance(dsr_value, (int, float)) and dsr_value >= L1_TSMOM_DSR_PASS_THRESHOLD
    pbo_pass = isinstance(pbo_value, (int, float)) and pbo_value < L1_TSMOM_PBO_PASS_THRESHOLD
    passes_s2 = bool(ir_pass and net_pass and dsr_pass and pbo_pass)

    for c in cells:
        c.pop("period_returns_by_timestamp", None)

    return {
        "family": L1_TSMOM_FAMILY,
        "holdout_role": holdout_role,
        "cost_per_side_pct": cost_per_side_pct,
        "vol_lookback_weeks": vol_lookback_weeks,
        "anchor_count": n,
        "token_count": len(tickers),
        "effective_breadth": breadth,
        "breadth_adjusted_annual_br": br_annual,
        "ic_required_breadth_adjusted": ic_required,
        "cells": cells,
        "best_cell": best_cell,
        "best_annualized_sharpe": best_sharpe,
        "yearly_net_by_lookback": yearly_by_config,
        "deflated_sharpe": deflated,
        "pbo": pbo,
        "kill_test": {
            "ir_pass": ir_pass,
            "net_pass": net_pass,
            "dsr_pass": dsr_pass,
            "pbo_pass": pbo_pass,
            "passes_s2": passes_s2,
            "ir_pass_threshold": L1_TSMOM_IR_PASS_THRESHOLD,
            "dsr_pass_threshold": L1_TSMOM_DSR_PASS_THRESHOLD,
            "pbo_pass_threshold": L1_TSMOM_PBO_PASS_THRESHOLD,
        },
        "decision": "advance_to_s3" if passes_s2 else "tsmom_below_gate",
    }


def _fold_sharpes(weekly_net: list[float], n_folds: int) -> list[dict[str, Any]]:
    """Contiguous-time fold Sharpes for an ensemble (no selection, so no PBO/DSR)."""

    folds: list[dict[str, Any]] = []
    total = len(weekly_net)
    if total < n_folds or n_folds < 2:
        return folds
    for f in range(n_folds):
        lo = total * f // n_folds
        hi = total * (f + 1) // n_folds
        chunk = weekly_net[lo:hi]
        folds.append(
            {
                "fold": f,
                "weeks": len(chunk),
                "net_sum": sum(chunk),
                "net_sharpe": _sharpe(chunk, WEEKLY_FREQUENCY_LABEL),
            }
        )
    return folds


def evaluate_l1_tsmom_ensemble(
    *,
    price_series_by_ticker: dict[str, list[SupplyPoint]],
    anchors_ms: list[int],
    lookback_weeks_grid: list[int],
    vol_lookback_weeks: int,
    cost_per_side_pct: float,
    n_folds: int = 5,
    holdout_role: str = "discovery",
) -> dict[str, Any]:
    """Equal-weight multi-lookback trend ensemble (parameter-free; no selection).

    Per instrument the ensemble signal is the mean of ``sign(trailing L-week return)``
    across the lookback grid (in [-1, 1]), inverse-vol scaled and normalized to unit
    gross. Because there is a single, parameter-free config there is no lookback
    selection — the honest robustness read is contiguous purged time folds rather than
    DSR/PBO (those penalize a search that no longer happens here). research-only.
    """

    tickers = list(price_series_by_ticker)
    n = len(anchors_ms)
    grid = sorted(set(int(l) for l in lookback_weeks_grid))
    price_at = {t: [asof_supply_at(price_series_by_ticker[t], a) for a in anchors_ms] for t in tickers}
    weekly_ret: dict[str, list[float | None]] = {}
    for t in tickers:
        series: list[float | None] = []
        for i in range(n):
            if i + 1 < n and price_at[t][i] and price_at[t][i + 1] and price_at[t][i] > 0.0:
                series.append(price_at[t][i + 1] / price_at[t][i] - 1.0)
            else:
                series.append(None)
        weekly_ret[t] = series
    breadth = _panel_effective_breadth({t: weekly_ret[t] for t in tickers})
    max_lookback = max(grid)

    weekly_net: list[float] = []
    weekly_gross: list[float] = []
    turnovers: list[float] = []
    previous_weights: dict[str, float] = {}
    yearly_net: dict[str, float] = {}
    for i in range(n):
        raw_weights: dict[str, float] = {}
        for t in tickers:
            if i < max_lookback or i < vol_lookback_weeks:
                continue
            signs: list[float] = []
            for lookback in grid:
                p_now = price_at[t][i]
                p_then = price_at[t][i - lookback]
                if p_now and p_then and p_then > 0.0:
                    trailing = p_now / p_then - 1.0
                    signs.append(1.0 if trailing > 0 else (-1.0 if trailing < 0 else 0.0))
            if not signs:
                continue
            ensemble_signal = sum(signs) / len(signs)
            if ensemble_signal == 0.0:
                continue
            vol_window = [weekly_ret[t][k] for k in range(i - vol_lookback_weeks, i) if weekly_ret[t][k] is not None]
            vol = _std_sample(vol_window)
            if vol <= 0.0:
                continue
            raw_weights[t] = ensemble_signal / vol
        gross_norm = sum(abs(w) for w in raw_weights.values())
        weights = {t: w / gross_norm for t, w in raw_weights.items()} if gross_norm > 0.0 else {}
        port = 0.0
        priced = False
        for t, w in weights.items():
            r = weekly_ret[t][i]
            if r is not None:
                port += w * r
                priced = True
        if not priced and not previous_weights:
            continue
        all_t = set(weights) | set(previous_weights)
        turnover = sum(abs(weights.get(t, 0.0) - previous_weights.get(t, 0.0)) for t in all_t)
        weekly_gross.append(port)
        weekly_net.append(port - cost_per_side_pct * turnover)
        turnovers.append(turnover)
        year = _utc_iso_from_ms(anchors_ms[i])[:4]
        yearly_net[year] = yearly_net.get(year, 0.0) + (port - cost_per_side_pct * turnover)
        previous_weights = weights

    net_sharpe = _sharpe(weekly_net, WEEKLY_FREQUENCY_LABEL)
    gross_sharpe = _sharpe(weekly_gross, WEEKLY_FREQUENCY_LABEL)
    folds = _fold_sharpes(weekly_net, n_folds)
    positive_folds = sum(1 for f in folds if isinstance(f["net_sharpe"], (int, float)) and f["net_sharpe"] > 0)
    effective_breadth = breadth["effective_breadth"]
    br_annual = (effective_breadth * _WEEKS_PER_YEAR) if isinstance(effective_breadth, (int, float)) else None
    ic_required = (1.0 / (br_annual ** 0.5)) if br_annual and br_annual > 0 else None

    ir_pass = isinstance(net_sharpe, (int, float)) and net_sharpe >= L1_TSMOM_IR_PASS_THRESHOLD
    net_pass = sum(weekly_net) > 0.0
    fold_pass = bool(folds) and positive_folds >= -(-len(folds) * 3 // 5)  # ceil(0.6 * n_folds)
    passes_s2 = bool(ir_pass and net_pass and fold_pass)

    return {
        "family": L1_TSMOM_FAMILY + "_ensemble",
        "mode": "ensemble",
        "holdout_role": holdout_role,
        "cost_per_side_pct": cost_per_side_pct,
        "vol_lookback_weeks": vol_lookback_weeks,
        "lookback_weeks_grid": grid,
        "anchor_count": n,
        "token_count": len(tickers),
        "effective_breadth": breadth,
        "breadth_adjusted_annual_br": br_annual,
        "ic_required_breadth_adjusted": ic_required,
        "net_sum_return_pct": sum(weekly_net),
        "gross_sum_return_pct": sum(weekly_gross),
        "net_annualized_sharpe": net_sharpe,
        "gross_annualized_sharpe": gross_sharpe,
        "avg_weekly_turnover": (sum(turnovers) / len(turnovers)) if turnovers else None,
        "portfolio_period_count": len(weekly_net),
        "yearly_net": yearly_net,
        "fold_count": len(folds),
        "positive_folds": positive_folds,
        "folds": folds,
        "kill_test": {
            "ir_pass": ir_pass,
            "net_pass": net_pass,
            "fold_pass": fold_pass,
            "passes_s2": passes_s2,
            "ir_pass_threshold": L1_TSMOM_IR_PASS_THRESHOLD,
            "fold_positive_required": -(-len(folds) * 3 // 5) if folds else None,
        },
        "decision": "advance_to_s3" if passes_s2 else "tsmom_ensemble_below_gate",
    }


@dataclass
class L1TimeSeriesMomentumService:
    """L1 S2 driver: fetch the cross-asset panel and run the trend IR/DSR/PBO kill-test."""

    settings: Settings

    def run(
        self,
        *,
        start_ms: int,
        end_ms: int,
        tickers: list[str] | None = None,
        api_key: str | None = None,
        start_date: str = DEFAULT_TIINGO_START_DATE,
        lookback_weeks_grid: list[int] | None = None,
        vol_lookback_weeks: int = DEFAULT_TSMOM_VOL_LOOKBACK_WEEKS,
        cost_per_side_pct: float | None = None,
        ensemble: bool = False,
        n_folds: int = 5,
        cache_dir: str | Path | None = None,
        fetcher: Callable[[str], Any] | None = None,
        force_refresh: bool = False,
        holdout_role: str = "discovery",
    ) -> dict[str, Any]:
        panel = tickers or list(L1_DEFAULT_CROSS_ASSET_PANEL)
        grid = lookback_weeks_grid or list(DEFAULT_TSMOM_LOOKBACK_WEEKS_GRID)
        if cost_per_side_pct is None:
            cost_per_side_pct = max(float(self.settings.estimated_fee_pct), 0.0) + max(
                float(self.settings.estimated_slippage_pct), 0.0
            )
        resolved_key = api_key or self.settings.tiingo_api_key
        if resolved_key is None and fetcher is None:
            return {
                "version": L1_CROSS_ASSET_VERSION,
                "source": "tiingo_cross_asset_tsmom",
                "error": "missing_tiingo_api_key",
                "detail": _MISSING_KEY_DETAIL,
                "tickers": panel,
            }

        price_series_by_ticker, sources, point_counts = fetch_cross_asset_panel(
            settings=self.settings,
            tickers=panel,
            api_key=api_key,
            start_date=start_date,
            cache_dir=cache_dir,
            fetcher=fetcher,
            force_refresh=force_refresh,
        )
        anchors = weekly_anchors(start_ms, end_ms)
        if ensemble:
            result = evaluate_l1_tsmom_ensemble(
                price_series_by_ticker=price_series_by_ticker,
                anchors_ms=anchors,
                lookback_weeks_grid=grid,
                vol_lookback_weeks=vol_lookback_weeks,
                cost_per_side_pct=cost_per_side_pct,
                n_folds=n_folds,
                holdout_role=holdout_role,
            )
        else:
            result = evaluate_l1_timeseries_momentum(
                price_series_by_ticker=price_series_by_ticker,
                anchors_ms=anchors,
                lookback_weeks_grid=grid,
                vol_lookback_weeks=vol_lookback_weeks,
                cost_per_side_pct=cost_per_side_pct,
                holdout_role=holdout_role,
            )
        result.update(
            {
                "version": L1_CROSS_ASSET_VERSION,
                "source": "tiingo_cross_asset_tsmom",
                "tickers": panel,
                "fetched_from": sources,
                "price_point_counts": point_counts,
                "lookback_weeks_grid": list(grid),
                "window_start_utc": _utc_iso_from_ms(start_ms),
                "window_end_utc": _utc_iso_from_ms(end_ms),
                "cache_dir": None if cache_dir is None else str(cache_dir),
            }
        )
        return result
