#!/usr/bin/env python3
"""Preregister and run the no-PnL funding-extreme independence G0."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import statistics
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from qount.contracts import canonical_hash  # noqa: E402
from qount.mini_trend.backtest import align_bars  # noqa: E402
from qount.research_data.market_data import Bar, Funding, load_funding, load_klines  # noqa: E402


SCHEMA_VERSION = "funding_extreme_independence_g0_v0.1"
FORCED_FLOW_SCHEMA_VERSION = "funding_extreme_forced_flow_diagnostic_v0.1"
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
DEFAULT_FUNDING_CACHE = REPO / "state" / "r0_runtime" / "funding"
DEFAULT_KLINE_CACHE = REPO / "state" / "r0_runtime" / "klines"
DEFAULT_TRIAL_PREREG = (
    REPO
    / "state"
    / "research_runs"
    / "20260719T093752Z-mini-trend-capitulation-rebound-preregistration"
    / "mini_trend_capitulation_rebound_preregistration.json"
)
DEFAULT_TRIAL_RESULT = (
    REPO
    / "state"
    / "research_runs"
    / "20260719T094147Z-mini-trend-capitulation-rebound-price-discovery"
    / "mini_trend_capitulation_rebound_price_discovery.json"
)
DEFAULT_OUTPUT_ROOT = REPO / "state" / "research_governance" / "funding_extreme_independence_g0"
DEFAULT_FORCED_FLOW_ROOT = REPO / "state" / "research_governance" / "funding_extreme_forced_flow"
UTC = dt.timezone.utc
SETTLEMENT_MS = 8 * 60 * 60 * 1000
MAX_CONSECUTIVE_GAP_MS = 12 * 60 * 60 * 1000
ANNUALIZATION_FACTOR = 3.0 * 365.0
EXTREME_ANNUALIZED_ABS_FUNDING = 0.50
MIN_CONSECUTIVE_SETTLEMENTS = 2
MIN_INDEPENDENT_EVENTS = 30
MAX_TRIAL_EVENT_OVERLAP = 0.60
FORCED_FLOW_START = "2021-01-01"
FORCED_FLOW_END = "2026-06-30"
FORCED_FLOW_ENTRY_LAG_BARS = 1
FORCED_FLOW_HOLDING_BARS = 3
FORCED_FLOW_BETA_LOOKBACK_DAYS = 180
FORCED_FLOW_TAKER_FEE_BPS_PER_SIDE = 10.0
FORCED_FLOW_SLIPPAGE_BPS_PER_SIDE = 2.0
DAY_MS = 24 * 60 * 60 * 1000


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _offline_only(url: str) -> bytes:
    raise RuntimeError(f"offline cache miss: {url.rsplit('/', 1)[-1]}")


def _date(ts_ms: int) -> dt.date:
    return dt.datetime.fromtimestamp(ts_ms / 1000.0, UTC).date()


def _iso(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000.0, UTC).isoformat().replace("+00:00", "Z")


def _month(value: str) -> tuple[int, int]:
    year, month = value[:7].split("-", 1)
    return int(year), int(month)


def _cache_manifest(cache_dir: Path, symbols: Sequence[str], start: str, end: str) -> list[dict[str, Any]]:
    start_month = _month(start)
    end_month = _month(end)
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        year, month = start_month
        while (year, month) <= end_month:
            path = cache_dir / f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
            if path.is_file():
                rows.append(
                    {
                        "path": str(path.relative_to(REPO)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "size_bytes": path.stat().st_size,
                    }
                )
            month += 1
            if month > 12:
                year, month = year + 1, 1
    return rows


def _validate_trial_contract(prereg: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    if prereg.get("protocol", {}).get("formal_trial", {}).get("project_trial_number") != 144:
        raise ValueError("trial_144_preregistration_required")
    signal = prereg.get("decision_contract", {}).get("signal", {})
    if signal.get("require_all_symbols_negative") is not True:
        raise ValueError("trial_144_signal_contract_mismatch")
    if result.get("contract_hash") != prereg.get("decision_contract", {}).get("contract_hash"):
        raise ValueError("trial_144_result_contract_hash_mismatch")
    if result.get("summary", {}).get("overlapping_episode_count") != 0:
        raise ValueError("trial_144_overlapping_episodes_present")


def _trial_signal_dates(result: Mapping[str, Any]) -> tuple[dt.date, ...]:
    episodes = result.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("trial_144_episodes_missing")
    dates = sorted({dt.date.fromisoformat(str(row["signal_date"])) for row in episodes})
    if len(dates) != len(episodes):
        raise ValueError("trial_144_signal_dates_not_unique")
    return tuple(dates)


def _extreme_rows(rows: Iterable[Funding]) -> list[Funding]:
    return [row for row in rows if abs(float(row.rate)) * ANNUALIZATION_FACTOR >= EXTREME_ANNUALIZED_ABS_FUNDING]


def _episodes(rows: Sequence[Funding]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: row.ts_ms)
    episodes: list[list[Funding]] = []
    current: list[Funding] = []
    for row in ordered:
        if current and row.ts_ms - current[-1].ts_ms > MAX_CONSECUTIVE_GAP_MS:
            if len(current) >= MIN_CONSECUTIVE_SETTLEMENTS:
                episodes.append(current)
            current = []
        current.append(row)
    if len(current) >= MIN_CONSECUTIVE_SETTLEMENTS:
        episodes.append(current)
    return [
        {
            "start_utc": _iso(group[0].ts_ms),
            "end_utc": _iso(group[-1].ts_ms),
            "start_date": _date(group[0].ts_ms).isoformat(),
            "end_date": _date(group[-1].ts_ms).isoformat(),
            "settlement_count": len(group),
            "max_annualized_abs_funding": max(
                abs(float(row.rate)) * ANNUALIZATION_FACTOR for row in group
            ),
            "signed_annualized_funding_mean": (
                sum(float(row.rate) for row in group) / len(group) * ANNUALIZATION_FACTOR
            ),
            "signs": sorted({"positive" if row.rate > 0 else "negative" for row in group}),
        }
        for group in episodes
    ]


def _cluster_episodes(by_symbol: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    flat = [dict(row, symbol=symbol) for symbol, rows in by_symbol.items() for row in rows]
    flat.sort(key=lambda row: row["start_utc"])
    clusters: list[list[dict[str, Any]]] = []
    for row in flat:
        start = dt.datetime.fromisoformat(row["start_utc"].replace("Z", "+00:00"))
        if not clusters:
            clusters.append([row])
            continue
        previous_end = max(
            dt.datetime.fromisoformat(item["end_utc"].replace("Z", "+00:00"))
            for item in clusters[-1]
        )
        if start - previous_end <= dt.timedelta(hours=24):
            clusters[-1].append(row)
        else:
            clusters.append([row])
    return [
        {
            "start_utc": min(row["start_utc"] for row in cluster),
            "end_utc": max(row["end_utc"] for row in cluster),
            "symbols": sorted({row["symbol"] for row in cluster}),
            "symbol_episode_count": len(cluster),
            "signed_annualized_funding_sum": sum(
                float(row["signed_annualized_funding_mean"]) for row in cluster
            ),
        }
        for cluster in clusters
    ]


def _add_cluster_directions(clusters: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    directed: list[dict[str, Any]] = []
    for cluster in clusters:
        signed = float(cluster["signed_annualized_funding_sum"])
        directed.append(
            dict(
                cluster,
                dominant_sign=("positive" if signed > 0.0 else "negative" if signed < 0.0 else None),
            )
        )
    return directed


def _overlap(signal_dates: Sequence[dt.date], clusters: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    covered: list[str] = []
    for signal_date in signal_dates:
        window_start = signal_date - dt.timedelta(days=1)
        matches_for_date = []
        for cluster in clusters:
            cluster_start = dt.datetime.fromisoformat(cluster["start_utc"].replace("Z", "+00:00")).date()
            cluster_end = dt.datetime.fromisoformat(cluster["end_utc"].replace("Z", "+00:00")).date()
            if window_start <= cluster_end <= signal_date:
                matches_for_date.append(cluster)
        covered.append(signal_date.isoformat())
        if matches_for_date:
            matches.append(
                {
                    "signal_date": signal_date.isoformat(),
                    "funding_event_cluster_count": len(matches_for_date),
                    "funding_symbols": sorted(
                        {symbol for cluster in matches_for_date for symbol in cluster["symbols"]}
                    ),
                }
            )
    return {
        "window": "funding event cluster end date in [trial_signal_date - 1 calendar day, trial_signal_date] UTC",
        "trial_signal_count": len(signal_dates),
        "covered_trial_signal_count": len(covered),
        "matched_trial_signal_count": len(matches),
        "overlap_rate": len(matches) / len(covered) if covered else None,
        "matches": matches,
    }


def build_preregistration(*, symbols: Sequence[str], funding_start: str, funding_end: str) -> dict[str, Any]:
    contract = {
        "hypothesis_family": "funding_extreme_forced_flow_v1",
        "research_question": "Are sustained extreme funding events independent of Trial 144 price-capitulation events?",
        "scope": "no_pnl_independence_g0",
        "symbols": list(symbols),
        "data": {
            "source": "existing Binance UM fundingRate archive",
            "cache_only": True,
            "funding_start": funding_start,
            "funding_end": funding_end,
            "settlement_interval_hours": 8,
            "top_n_expansion_allowed": False,
            "trial_144_price_event_source": str(DEFAULT_TRIAL_RESULT.relative_to(REPO)),
        },
        "extreme_event_definition": {
            "annualized_abs_funding_threshold": EXTREME_ANNUALIZED_ABS_FUNDING,
            "annualization": "abs(8h funding rate) * 3 settlements/day * 365 days/year",
            "minimum_consecutive_settlements": MIN_CONSECUTIVE_SETTLEMENTS,
            "maximum_gap_between_consecutive_settlements_hours": 12,
            "independence_cluster_gap_hours": 24,
        },
        "overlap_definition": {
            "price_event": "Trial 144 signal_date, not entry or outcome date",
            "funding_window": "funding event cluster end date in the preceding 1 calendar day through signal_date UTC",
            "denominator": "Trial 144 signal dates with available funding coverage",
        },
        "decision_gates": {
            "minimum_independent_funding_event_clusters": MIN_INDEPENDENT_EVENTS,
            "maximum_trial_144_overlap_rate": MAX_TRIAL_EVENT_OVERLAP,
            "overlap_at_or_above_threshold": "reject_duplicate_trial_144_mechanism",
            "overlap_below_threshold_with_insufficient_events": "block_g0_insufficient_data",
            "all_gates_pass": "retain_for_new_forced_flow_preregistration",
        },
        "forbidden": ["pnl", "parameter_search", "threshold_search", "orders", "paper", "live"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "funding_extreme_independence_g0_preregistration",
        "created_at": dt.datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "orders_authorized": False,
            "pnl_evaluated": False,
        },
        "contract": contract,
        "contract_hash": canonical_hash(contract),
    }


def run_g0(
    *,
    preregistration: Mapping[str, Any],
    trial_preregistration_path: Path,
    trial_result_path: Path,
    funding_cache_dir: Path,
) -> dict[str, Any]:
    trial_preregistration = _read_json(trial_preregistration_path)
    trial_result = _read_json(trial_result_path)
    _validate_trial_contract(trial_preregistration, trial_result)
    signal_dates = _trial_signal_dates(trial_result)
    symbols = tuple(preregistration["contract"]["symbols"])
    start = preregistration["contract"]["data"]["funding_start"]
    end = preregistration["contract"]["data"]["funding_end"]
    funding = {
        symbol: load_funding(
            symbol,
            start=_month(start),
            end=_month(end),
            cache_dir=str(funding_cache_dir),
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in symbols
    }
    by_symbol = {symbol: _episodes(_extreme_rows(rows)) for symbol, rows in funding.items()}
    clusters = _cluster_episodes(by_symbol)
    overlap = _overlap(signal_dates, clusters)
    funding_last_date = max((_date(row.ts_ms) for rows in funding.values() for row in rows), default=None)
    overlap_rate = overlap["overlap_rate"]
    if len(clusters) < MIN_INDEPENDENT_EVENTS:
        verdict = "block_g0_insufficient_data"
    elif overlap_rate is not None and overlap_rate >= MAX_TRIAL_EVENT_OVERLAP:
        verdict = "reject_duplicate_trial_144_mechanism"
    else:
        verdict = "retain_for_new_forced_flow_preregistration"
    data = {
        "symbols": list(symbols),
        "funding_cache_dir": str(funding_cache_dir.relative_to(REPO)),
        "funding_last_available_date": funding_last_date.isoformat() if funding_last_date else None,
        "funding_rows_by_symbol": {symbol: len(rows) for symbol, rows in funding.items()},
        "cache_manifest": _cache_manifest(funding_cache_dir, symbols, start, end),
        "trial_144_contract_hash": trial_preregistration["decision_contract"]["contract_hash"],
        "trial_144_price_data_hash": trial_result["data"]["data_hash"],
        "trial_144_signal_dates": [value.isoformat() for value in signal_dates],
        "symbol_extreme_episode_counts": {symbol: len(rows) for symbol, rows in by_symbol.items()},
        "independent_funding_event_cluster_count": len(clusters),
        "funding_event_clusters": clusters,
        "trial_144_overlap": overlap,
    }
    core = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "funding_extreme_independence_g0_result",
        "preregistration_contract_hash": preregistration["contract_hash"],
        "data": data,
        "verdict": verdict,
    }
    return {
        **core,
        "created_at": dt.datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "orders_authorized": False,
            "pnl_evaluated": False,
        },
        "result_hash": canonical_hash(core),
    }


def build_forced_flow_preregistration(g0_result: Mapping[str, Any]) -> dict[str, Any]:
    if g0_result.get("verdict") != "retain_for_new_forced_flow_preregistration":
        raise ValueError("funding_extreme_g0_did_not_pass")
    contract = {
        "hypothesis_family": "funding_extreme_forced_flow_v1",
        "research_question": (
            "After sustained extreme funding, does the opposite forced-flow direction produce "
            "positive cost-adjusted event return and positive BTC-beta residual?"
        ),
        "scope": "historical_event_diagnostic_only",
        "g0_result_hash": g0_result["result_hash"],
        "data": {
            "source": "existing Binance UM 1d kline and funding archives",
            "cache_only": True,
            "symbols": list(DEFAULT_SYMBOLS),
            "historical_start": FORCED_FLOW_START,
            "historical_end": FORCED_FLOW_END,
            "oi_or_liquidation_history_used": False,
            "future_forward_collection_required_for_full_mechanism": True,
        },
        "signal": {
            "event_source": "24h-clustered sustained extreme funding event from G0",
            "positive_funding_direction": "long_after_positive_funding_sell_pressure",
            "negative_funding_direction": "short_after_negative_funding_buy_pressure",
            "mixed_sign_cluster": "excluded_from_directional_diagnostic",
            "one_signal_per_cluster": True,
            "overlap_policy": "keep_earliest_chronological_cluster; exclude later cluster if entry_date <= prior outcome_date",
        },
        "execution_proxy": {
            "entry": "next completed daily bar open",
            "entry_lag_completed_bars": FORCED_FLOW_ENTRY_LAG_BARS,
            "holding_completed_bars": FORCED_FLOW_HOLDING_BARS,
            "exit": "third held daily bar close",
            "stop": "none; fixed horizon only",
            "taker_fee_bps_per_side": FORCED_FLOW_TAKER_FEE_BPS_PER_SIDE,
            "slippage_bps_per_side": FORCED_FLOW_SLIPPAGE_BPS_PER_SIDE,
            "funding_during_holding_included": True,
            "shorting_allowed": True,
            "leverage_boost_allowed": False,
            "paper_or_live_allowed": False,
        },
        "attribution": {
            "beta_lookback_days": FORCED_FLOW_BETA_LOOKBACK_DAYS,
            "benchmark": "same-direction BTCUSDT event return",
            "residual": "net_event_return - ex_ante_TOP3_to_BTC_beta * directional_BTC_return",
        },
        "decision_gates": {
            "minimum_independent_events": 12,
            "minimum_positive_event_rate": 0.55,
            "minimum_median_net_event_return": 0.0,
            "minimum_compound_net_event_return": 0.0,
            "minimum_positive_calendar_segments": 2,
            "minimum_median_btc_beta_residual": 0.0,
            "maximum_overlapping_events": 0,
            "failure_action": "reject_forced_flow_historical_diagnostic",
        },
        "forbidden": ["parameter_search", "threshold_search", "holding_period_search", "orders", "paper", "live"],
    }
    return {
        "schema_version": FORCED_FLOW_SCHEMA_VERSION,
        "artifact_type": "funding_extreme_forced_flow_preregistration",
        "created_at": dt.datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "orders_authorized": False,
            "pnl_evaluated": False,
        },
        "contract": contract,
        "contract_hash": canonical_hash(contract),
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _beta(strategy_returns: Sequence[float], benchmark_returns: Sequence[float]) -> float:
    if len(strategy_returns) != len(benchmark_returns) or len(strategy_returns) < 2:
        return 0.0
    strategy_mean = _mean(strategy_returns)
    benchmark_mean = _mean(benchmark_returns)
    variance = sum((value - benchmark_mean) ** 2 for value in benchmark_returns)
    if variance <= 0.0:
        return 0.0
    covariance = sum(
        (strategy - strategy_mean) * (benchmark - benchmark_mean)
        for strategy, benchmark in zip(strategy_returns, benchmark_returns)
    )
    return covariance / variance


def _max_drawdown(curve: Sequence[float]) -> float:
    peak = curve[0] if curve else 1.0
    drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1.0)
    return drawdown


def _funding_between(rows: Sequence[Funding], start_ms: int, end_ms: int, direction: int) -> float:
    return sum(-direction * float(row.rate) for row in rows if start_ms <= row.ts_ms < end_ms)


def _event_beta(aligned: Mapping[str, Sequence[Bar]], index: int) -> float:
    start = index - FORCED_FLOW_BETA_LOOKBACK_DAYS + 1
    top3_returns: list[float] = []
    btc_returns: list[float] = []
    for offset in range(start, index + 1):
        btc_return = aligned["BTCUSDT"][offset].close / aligned["BTCUSDT"][offset - 1].close - 1.0
        top3_return = _mean(
            [
                aligned[symbol][offset].close / aligned[symbol][offset - 1].close - 1.0
                for symbol in DEFAULT_SYMBOLS
            ]
        )
        btc_returns.append(btc_return)
        top3_returns.append(top3_return)
    return _beta(top3_returns, btc_returns)


def _event_curve(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    curve = [1.0]
    for row in rows:
        curve.append(curve[-1] * (1.0 + float(row["net_event_return"])))
    return curve


def _load_research_inputs(
    *, kline_cache_dir: Path, funding_cache_dir: Path
) -> tuple[dict[str, list[Bar]], dict[str, list[Funding]]]:
    bars = {
        symbol: load_klines(
            symbol,
            "1d",
            start=_month(FORCED_FLOW_START),
            end=_month(FORCED_FLOW_END),
            market="um",
            cache_dir=str(kline_cache_dir),
            fetch=_offline_only,
        )
        for symbol in DEFAULT_SYMBOLS
    }
    funding = {
        symbol: load_funding(
            symbol,
            start=_month("2020-01-01"),
            end=_month(FORCED_FLOW_END),
            cache_dir=str(funding_cache_dir),
            fetch=_offline_only,
            skip_missing=True,
        )
        for symbol in DEFAULT_SYMBOLS
    }
    return bars, funding


def run_forced_flow(
    *,
    preregistration: Mapping[str, Any],
    g0_result: Mapping[str, Any],
    kline_cache_dir: Path,
    funding_cache_dir: Path,
) -> dict[str, Any]:
    if preregistration.get("contract", {}).get("g0_result_hash") != g0_result.get("result_hash"):
        raise ValueError("forced_flow_g0_result_hash_mismatch")
    bars, funding = _load_research_inputs(
        kline_cache_dir=kline_cache_dir, funding_cache_dir=funding_cache_dir
    )
    aligned = align_bars(bars, DEFAULT_SYMBOLS)
    by_symbol = {symbol: _episodes(_extreme_rows(rows)) for symbol, rows in funding.items()}
    clusters = _add_cluster_directions(_cluster_episodes(by_symbol))
    date_to_index = {bar.date: index for index, bar in enumerate(aligned["BTCUSDT"])}
    cost = (FORCED_FLOW_TAKER_FEE_BPS_PER_SIDE + FORCED_FLOW_SLIPPAGE_BPS_PER_SIDE) / 10_000.0
    episodes: list[dict[str, Any]] = []
    excluded_mixed_sign = 0
    excluded_missing_window = 0
    excluded_overlapping = 0
    previous_outcome: dt.date | None = None
    for cluster in clusters:
        signal_date = dt.date.fromisoformat(str(cluster["end_utc"])[:10])
        if not (dt.date.fromisoformat(FORCED_FLOW_START) <= signal_date <= dt.date.fromisoformat(FORCED_FLOW_END)):
            continue
        if cluster.get("dominant_sign") is None:
            excluded_mixed_sign += 1
            continue
        signal_index = date_to_index.get(signal_date.isoformat())
        if signal_index is None or signal_index < FORCED_FLOW_BETA_LOOKBACK_DAYS:
            excluded_missing_window += 1
            continue
        entry_index = signal_index + FORCED_FLOW_ENTRY_LAG_BARS
        final_index = entry_index + FORCED_FLOW_HOLDING_BARS - 1
        if final_index >= len(aligned["BTCUSDT"]):
            excluded_missing_window += 1
            continue
        entry_date = dt.date.fromisoformat(aligned["BTCUSDT"][entry_index].date)
        outcome_date = dt.date.fromisoformat(aligned["BTCUSDT"][final_index].date)
        if previous_outcome is not None and entry_date <= previous_outcome:
            excluded_overlapping += 1
            continue
        direction = 1 if cluster["dominant_sign"] == "positive" else -1
        symbols_payload: dict[str, dict[str, float]] = {}
        for symbol in DEFAULT_SYMBOLS:
            entry_bar = aligned[symbol][entry_index]
            exit_bar = aligned[symbol][final_index]
            price_multiplier = exit_bar.close / entry_bar.open if direction == 1 else entry_bar.open / exit_bar.close
            funding_return = _funding_between(
                funding[symbol], entry_bar.ts_ms, exit_bar.ts_ms + DAY_MS, direction
            )
            net_multiplier = (1.0 - cost) * price_multiplier * (1.0 + funding_return) * (1.0 - cost)
            symbols_payload[symbol] = {
                "entry_price": entry_bar.open,
                "exit_price": exit_bar.close,
                "price_return": direction * (exit_bar.close / entry_bar.open - 1.0),
                "funding_return": funding_return,
                "net_return": net_multiplier - 1.0,
            }
        btc_entry = aligned["BTCUSDT"][entry_index].open
        btc_exit = aligned["BTCUSDT"][final_index].close
        directional_btc_return = direction * (btc_exit / btc_entry - 1.0)
        beta = _event_beta(aligned, signal_index)
        net_event_return = _mean([row["net_return"] for row in symbols_payload.values()])
        episode = {
            "signal_date": signal_date.isoformat(),
            "entry_date": entry_date.isoformat(),
            "outcome_date": outcome_date.isoformat(),
            "direction": "long" if direction == 1 else "short",
            "funding_cluster": cluster,
            "symbols": symbols_payload,
            "net_event_return": net_event_return,
            "directional_btc_return": directional_btc_return,
            "ex_ante_top3_to_btc_beta": beta,
            "btc_beta_residual": net_event_return - beta * directional_btc_return,
        }
        episode["event_id"] = canonical_hash(episode)
        episodes.append(episode)
        previous_outcome = outcome_date

    returns = [float(row["net_event_return"]) for row in episodes]
    residuals = [float(row["btc_beta_residual"]) for row in episodes]
    curve = _event_curve(episodes)
    summary = {
        "independent_event_count": len(episodes),
        "positive_event_rate": sum(value > 0.0 for value in returns) / len(returns) if returns else 0.0,
        "mean_net_event_return": _mean(returns),
        "median_net_event_return": statistics.median(returns) if returns else 0.0,
        "compound_net_event_return": curve[-1] - 1.0,
        "maximum_event_nav_drawdown": _max_drawdown(curve),
        "median_btc_beta_residual": statistics.median(residuals) if residuals else 0.0,
        "overlapping_events": 0,
        "excluded_mixed_sign_clusters": excluded_mixed_sign,
        "excluded_missing_window_clusters": excluded_missing_window,
        "excluded_overlapping_clusters": excluded_overlapping,
    }
    segments: list[dict[str, Any]] = []
    for label, start, end in (
        ("2021-2022", "2021-01-01", "2022-12-31"),
        ("2023-2024", "2023-01-01", "2024-12-31"),
        ("2025-2026", "2025-01-01", FORCED_FLOW_END),
    ):
        segment_rows = [row for row in episodes if start <= row["signal_date"] <= end]
        segment_curve = _event_curve(segment_rows)
        segments.append(
            {
                "label": label,
                "start": start,
                "end": end,
                "independent_event_count": len(segment_rows),
                "positive_event_rate": sum(float(row["net_event_return"]) > 0.0 for row in segment_rows) / len(segment_rows) if segment_rows else 0.0,
                "compound_net_event_return": segment_curve[-1] - 1.0,
                "median_net_event_return": statistics.median([float(row["net_event_return"]) for row in segment_rows]) if segment_rows else 0.0,
            }
        )
    gates = preregistration["contract"]["decision_gates"]
    gate_results = {
        "minimum_independent_events": summary["independent_event_count"] >= gates["minimum_independent_events"],
        "minimum_positive_event_rate": summary["positive_event_rate"] >= gates["minimum_positive_event_rate"],
        "minimum_median_net_event_return": summary["median_net_event_return"] > gates["minimum_median_net_event_return"],
        "minimum_compound_net_event_return": summary["compound_net_event_return"] > gates["minimum_compound_net_event_return"],
        "minimum_positive_calendar_segments": sum(row["compound_net_event_return"] > 0.0 for row in segments) >= gates["minimum_positive_calendar_segments"],
        "minimum_median_btc_beta_residual": summary["median_btc_beta_residual"] > gates["minimum_median_btc_beta_residual"],
        "maximum_overlapping_events": summary["overlapping_events"] <= gates["maximum_overlapping_events"],
    }
    verdict = "retain_for_forward_mechanism_validation" if all(gate_results.values()) else "reject_forced_flow_historical_diagnostic"
    core = {
        "schema_version": FORCED_FLOW_SCHEMA_VERSION,
        "artifact_type": "funding_extreme_forced_flow_result",
        "preregistration_contract_hash": preregistration["contract_hash"],
        "g0_result_hash": g0_result["result_hash"],
        "data": {
            "kline_cache_dir": str(kline_cache_dir.relative_to(REPO)),
            "funding_cache_dir": str(funding_cache_dir.relative_to(REPO)),
            "symbols": list(DEFAULT_SYMBOLS),
            "aligned_bar_count": len(aligned["BTCUSDT"]),
            "first_aligned_date": aligned["BTCUSDT"][0].date,
            "last_aligned_date": aligned["BTCUSDT"][-1].date,
            "funding_rows_by_symbol": {symbol: len(rows) for symbol, rows in funding.items()},
            "event_cluster_count_before_directional_filter": len(clusters),
        },
        "summary": summary,
        "segments": segments,
        "gate_results": gate_results,
        "verdict": verdict,
        "episodes": episodes,
    }
    return {
        **core,
        "created_at": dt.datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": True,
            "orders_authorized": False,
            "pnl_evaluated": True,
            "standalone_executable_nav_claimed": False,
        },
        "result_hash": canonical_hash(core),
    }


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--run-forced-flow", action="store_true")
    parser.add_argument("--funding-cache-dir", type=Path, default=DEFAULT_FUNDING_CACHE)
    parser.add_argument("--kline-cache-dir", type=Path, default=DEFAULT_KLINE_CACHE)
    parser.add_argument("--trial-preregistration-path", type=Path, default=DEFAULT_TRIAL_PREREG)
    parser.add_argument("--trial-result-path", type=Path, default=DEFAULT_TRIAL_RESULT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--g0-result-path", type=Path, default=DEFAULT_OUTPUT_ROOT / "result.json")
    parser.add_argument("--forced-flow-output-root", type=Path, default=DEFAULT_FORCED_FLOW_ROOT)
    parser.add_argument("--funding-start", default="2020-01-01")
    parser.add_argument("--funding-end", default="2026-07-31")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip())
    preregistration = build_preregistration(
        symbols=symbols,
        funding_start=args.funding_start,
        funding_end=args.funding_end,
    )
    prereg_path = args.output_root / "preregistration.json"
    _write(prereg_path, preregistration)
    print(f"preregistration={prereg_path}")
    print(f"contract_hash={preregistration['contract_hash']}")
    if not args.run and not args.run_forced_flow:
        return 0
    if args.run:
        result = run_g0(
            preregistration=preregistration,
            trial_preregistration_path=args.trial_preregistration_path,
            trial_result_path=args.trial_result_path,
            funding_cache_dir=args.funding_cache_dir,
        )
        result_path = args.output_root / "result.json"
        _write(result_path, result)
        print(f"result={result_path}")
        print(f"verdict={result['verdict']}")
        print(f"independent_funding_event_cluster_count={result['data']['independent_funding_event_cluster_count']}")
        print(f"trial_144_overlap_rate={result['data']['trial_144_overlap']['overlap_rate']}")
    if args.run_forced_flow:
        g0_result = _read_json(args.g0_result_path)
        forced_preregistration = build_forced_flow_preregistration(g0_result)
        forced_prereg_path = args.forced_flow_output_root / "preregistration.json"
        _write(forced_prereg_path, forced_preregistration)
        forced_result = run_forced_flow(
            preregistration=forced_preregistration,
            g0_result=g0_result,
            kline_cache_dir=args.kline_cache_dir,
            funding_cache_dir=args.funding_cache_dir,
        )
        forced_result_path = args.forced_flow_output_root / "result.json"
        _write(forced_result_path, forced_result)
        print(f"forced_flow_preregistration={forced_prereg_path}")
        print(f"forced_flow_contract_hash={forced_preregistration['contract_hash']}")
        print(f"forced_flow_result={forced_result_path}")
        print(f"forced_flow_verdict={forced_result['verdict']}")
        print(f"forced_flow_events={forced_result['summary']['independent_event_count']}")
        print(f"forced_flow_median_net_return={forced_result['summary']['median_net_event_return']}")
        print(f"forced_flow_median_btc_beta_residual={forced_result['summary']['median_btc_beta_residual']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
