"""Causal latest-completed-bar projection for the MiniTrend UM pilot."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3, frozen_top3_config
from qount.mini_trend.futures_funding_veto_shadow_forward import (
    complete_forward_input_prefix,
)
from qount.mini_trend.futures_recovery import canonical_hash, selected_um_rules
from qount.mini_trend.futures_recovery_backtest import run_variant
from qount.mini_trend.futures_shadow_inputs import (
    canonical_funding_settlement_timestamp,
    merge_funding,
)
from qount.mini_trend.live_pilot import LIVE_PILOT_CONTRACT
from qount.mini_trend.pilot_paper import PILOT_PAPER_PROTOCOL, PilotPaperProtocol
from qount.models import utc_now
from qount.settings import Settings
from qount.research_data.indicators import ATR


PILOT_PROJECTION_VERSION = "mini_trend_um_pilot_latest_projection_v0.2"
_DAY_MS = 86_400_000


def _data_hash(
    bars: Mapping[str, Sequence[Bar]],
    funding: Mapping[str, Sequence[Funding]],
) -> str:
    return canonical_hash(
        {
            "bars": {
                symbol: [
                    [row.ts_ms, row.open, row.high, row.low, row.close, row.volume]
                    for row in bars[symbol]
                ]
                for symbol in TOP3
            },
            "funding": {
                symbol: [[row.ts_ms, row.rate] for row in funding.get(symbol, [])]
                for symbol in TOP3
            },
        }
    )


def _funding_counts(
    funding: Mapping[str, Sequence[Funding]],
) -> dict[str, dict[int, int]]:
    result: dict[str, dict[int, int]] = {symbol: {} for symbol in TOP3}
    for symbol in TOP3:
        for row in funding.get(symbol, []):
            timestamp = canonical_funding_settlement_timestamp(row.ts_ms)
            bar_open = ((timestamp - 1) // _DAY_MS) * _DAY_MS
            result[symbol][bar_open] = result[symbol].get(bar_open, 0) + 1
    return result


def _synthetic_flat_outcome(row: Bar) -> Bar:
    return Bar(
        row.ts_ms + _DAY_MS,
        row.close,
        row.close,
        row.close,
        row.close,
        0.0,
    )


def _atr_last(rows: Sequence[Bar], lookback: int) -> float | None:
    indicator = ATR(lookback)
    value = None
    for row in rows:
        value = indicator.update(row)
    return value


def build_latest_pilot_projection(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    *,
    protocol: PilotPaperProtocol | None = None,
    expected_latest_date: str | None = None,
) -> dict[str, Any]:
    protocol = protocol or PILOT_PAPER_PROTOCOL
    rules, rules_hash = selected_um_rules(rules_artifact)
    bars = align_bars(bars_by_symbol, TOP3)
    funding = merge_funding(
        funding_by_symbol,
        {symbol: () for symbol in TOP3},
    )
    dates = [row.date for row in bars["BTCUSDT"]]
    latest_date = dates[-1] if dates else None
    report: dict[str, Any] = {
        "schema_version": PILOT_PROJECTION_VERSION,
        "artifact_type": "mini_trend_um_pilot_latest_projection",
        "created_at": utc_now().isoformat(),
        "meta": {
            "causal_latest_completed_bar_only": True,
            "synthetic_outcome_controls_returns": False,
            "private_exchange_data": False,
            "private_api_order_attempted": False,
            "orders_allowed": False,
            "live_orders_allowed": False,
        },
        "contract": {
            "strategy": LIVE_PILOT_CONTRACT.strategy,
            "live_pilot_contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
            "paper_runtime_contract_hash": protocol.contract_hash,
            "paper_start_date": protocol.paper_start_date,
            "capital_usdt": protocol.capital_usdt,
            "warmup_completed_bars": protocol.warmup_completed_bars,
            "projection_method": "append_flat_synthetic_outcome_then_discard_outcome_pnl",
        },
        "exchange_rules_hash": rules_hash,
        "data": {
            "common_bar_count": len(dates),
            "first_common_date": dates[0] if dates else None,
            "last_common_date": latest_date,
        },
        "decision": None,
        "diagnostics": {
            "blockers": [],
            "verdict": "await_latest_completed_pilot_bar",
            "projection_ready": False,
            "dry_or_live_allowed": False,
        },
    }
    if not dates or latest_date < protocol.paper_start_date:
        report["diagnostics"]["blockers"] = ["paper_start_bar_not_available"]
        return report

    if expected_latest_date is not None:
        try:
            expected_date = dt.date.fromisoformat(expected_latest_date)
        except ValueError as exc:
            raise ValueError("expected_latest_date_invalid") from exc
        expected_date_text = expected_date.isoformat()
        report["data"]["expected_latest_date"] = expected_date_text
        if latest_date != expected_date_text:
            report["diagnostics"]["blockers"] = [
                "latest_completed_bar_not_available"
            ]
            report["diagnostics"]["verdict"] = "await_latest_completed_pilot_bar"
            return report

    start_index = next(
        index
        for index, date in enumerate(dates)
        if date >= protocol.paper_start_date
    )
    if start_index < protocol.warmup_completed_bars:
        report["diagnostics"]["blockers"] = ["insufficient_signal_warmup"]
        return report
    slice_start = start_index - protocol.warmup_completed_bars
    causal_bars = {
        symbol: list(rows[slice_start:]) for symbol, rows in bars.items()
    }
    timestamps = [row.ts_ms for row in causal_bars["BTCUSDT"]]
    if any(right - left != _DAY_MS for left, right in zip(timestamps, timestamps[1:])):
        report["diagnostics"]["blockers"] = ["non_contiguous_completed_bars"]
        return report

    prefix = complete_forward_input_prefix(
        bars,
        funding,
        start_index=start_index,
        minimum_settlements=(
            protocol.minimum_daily_funding_settlements_per_symbol
        ),
    )
    if prefix["complete_prefix_pair_count"] != prefix["total_price_pair_count"]:
        report["data"]["first_incomplete_pair"] = prefix["first_incomplete_pair"]
        report["diagnostics"]["blockers"] = ["incomplete_historical_forward_prefix"]
        return report

    latest = causal_bars["BTCUSDT"][-1]
    counts = _funding_counts(funding)
    latest_funding_counts = {
        symbol: counts[symbol].get(latest.ts_ms, 0) for symbol in TOP3
    }
    report["data"].update(
        {
            "complete_prefix_pair_count": prefix["complete_prefix_pair_count"],
            "latest_funding_settlement_count": latest_funding_counts,
        }
    )
    if any(
        value
        < protocol.minimum_daily_funding_settlements_per_symbol
        for value in latest_funding_counts.values()
    ):
        report["diagnostics"]["blockers"] = ["latest_completed_bar_funding_incomplete"]
        return report

    projected_bars = {
        symbol: [*rows, _synthetic_flat_outcome(rows[-1])]
        for symbol, rows in causal_bars.items()
    }
    result = run_variant(
        projected_bars,
        funding,
        rules,
        recovery_enabled=False,
        daily_chandelier_atr_multiple=(
            LIVE_PILOT_CONTRACT.daily_chandelier_atr_multiple
        ),
        stop_cooldown_completed_bars=(
            LIVE_PILOT_CONTRACT.stop_cooldown_completed_bars
        ),
        capital_usdt=protocol.capital_usdt,
    )
    expected_decisions = len(dates) - start_index
    if len(result.equity) != expected_decisions:
        raise ValueError("latest projection did not reconstruct every pilot decision")
    source = result.equity[-1]
    if source["decision_date"] != latest.date:
        raise ValueError("latest projection decision is not aligned to the latest bar")
    previous_weights = (
        {
            symbol: float(result.equity[-2]["execution_state"]["target_weights"][symbol])
            for symbol in TOP3
        }
        if len(result.equity) > 1
        else {symbol: 0.0 for symbol in TOP3}
    )
    pre_decision_equity = (
        float(result.equity[-2]["equity"])
        if len(result.equity) > 1
        else protocol.capital_usdt
    )
    execution_state = dict(source["execution_state"])
    desired_weights = {
        symbol: float(execution_state["target_weights"][symbol]) for symbol in TOP3
    }
    prices = {symbol: causal_bars[symbol][-1].close for symbol in TOP3}
    trail_high = execution_state.get("trail_high") or {}
    protective_stop_prices = {}
    for symbol in TOP3:
        if desired_weights[symbol] <= 0.0 or symbol not in trail_high:
            continue
        atr = _atr_last(causal_bars[symbol], frozen_top3_config().atr_lookback)
        if atr is None:
            continue
        stop_price = (
            float(trail_high[symbol])
            - LIVE_PILOT_CONTRACT.daily_chandelier_atr_multiple * atr
        )
        if stop_price > 0.0:
            protective_stop_prices[symbol] = stop_price
    data_hash = _data_hash(causal_bars, funding)
    available_after = dt.datetime.fromtimestamp(
        (latest.ts_ms + _DAY_MS) / 1000, dt.UTC
    ).isoformat()
    decision_core = {
        "decision_date": latest.date,
        "decision_available_after": available_after,
        "strategy": LIVE_PILOT_CONTRACT.strategy,
        "pre_decision_equity_usdt": pre_decision_equity,
        "prices": prices,
        "previous_weights": previous_weights,
        "desired_weights": desired_weights,
        "protective_stop_prices": protective_stop_prices,
        "projected_order_intent_count": int(source["orders"]),
        "risk_stage": source["risk_stage"],
        "execution_state": execution_state,
        "execution_state_hash": canonical_hash(execution_state),
        "data_hash": data_hash,
        "exchange_rules_hash": rules_hash,
    }
    report["decision"] = decision_core | {
        "decision_id": canonical_hash(
            {
                "live_pilot_contract_hash": LIVE_PILOT_CONTRACT.contract_hash,
                "decision": decision_core,
            }
        )
    }
    report["data"]["data_hash"] = data_hash
    report["diagnostics"].update(
        {
            "blockers": [],
            "verdict": "latest_causal_decision_projected",
            "projection_ready": True,
            "dry_or_live_allowed": False,
        }
    )
    return report


def write_latest_pilot_projection_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-um-pilot-latest-projection",
        path_key="artifact_path",
        default_filename="mini_trend_um_pilot_latest_projection.json",
        explicit_path=explicit_path,
    )
