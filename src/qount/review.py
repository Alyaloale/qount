from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from statistics import mean
from statistics import median
from tempfile import TemporaryDirectory
from typing import Any

from .exchange_utils import build_exchange
from .entry_quality import assess_fresh_entry
from .journal import Journal
from .models import AccountSnapshot
from .models import AIDecision
from .models import Candle
from .models import MarketSnapshotBundle
from .models import PositionSnapshot
from .models import SymbolSnapshot
from .models import ValidatedDecision
from .models import to_jsonable
from .settings import Settings
from .trade_policy import action_direction
from .trade_policy import confidence_bucket
from .trade_policy import estimated_action_cost_pct
from .trade_policy import is_open_action
from .trade_policy import timeframe_to_ms


def _review_group(action: str) -> str:
    return "hold" if action == "hold" else "actionable"


def _position_direction(position_side: str | None) -> int | None:
    if position_side == "long":
        return 1
    if position_side == "short":
        return -1
    return None


def _decision_context(*, opened_position: bool, position_side_before_action: str | None) -> str:
    if position_side_before_action is not None:
        return "management"
    if opened_position:
        return "entry"
    return "idle"


def _decision_lifecycle(
    *,
    decision_action: str,
    review_action: str,
    contract_market: bool,
    position_side_before_action: str | None,
    close_fraction: float = 1.0,
) -> str:
    current_direction = _position_direction(position_side_before_action)
    if review_action == "hold":
        if decision_action == "hold":
            return "management_hold" if current_direction is not None else "idle_hold"
        if is_open_action(decision_action, contract_market):
            desired_direction = action_direction(
                decision_action,
                contract_market=contract_market,
                position_side=position_side_before_action,
            )
            if current_direction is None:
                return "blocked_entry"
            if desired_direction == current_direction:
                return "blocked_add"
            return "blocked_reverse"
        if decision_action == "close":
            return "blocked_close" if current_direction is not None else "idle_hold"
        return "idle_hold"

    if is_open_action(review_action, contract_market):
        desired_direction = action_direction(
            review_action,
            contract_market=contract_market,
            position_side=position_side_before_action,
        )
        if current_direction is None:
            return "fresh_entry"
        if desired_direction == current_direction:
            return "add_position"
        return "reverse_entry"

    if review_action == "close":
        if 0.0 < close_fraction < 1.0:
            return "partial_reduce"
        return "full_close"

    return "other"


def _exit_source(*, decision_action: str, review_action: str, risk_reasons: list[str]) -> str | None:
    if review_action != "close":
        return None
    for reason in risk_reasons:
        if reason.startswith("partial_take_profit"):
            return "partial_take_profit"
        if reason.startswith("management_take_profit_hit"):
            return "risk_take_profit"
        if reason.startswith("management_stop_loss_hit"):
            return "risk_stop_loss"
        if reason.startswith("management_trailing_profit_retrace"):
            return "trailing_profit_retrace"
    if decision_action == "close":
        return "ai_close"
    return "risk_close"


def _blocked_group(lifecycle: str) -> str | None:
    if lifecycle in {"blocked_entry", "blocked_add", "blocked_reverse", "blocked_close"}:
        return lifecycle
    return None


def _synthetic_entry_thesis_key(
    *,
    decision_action: str,
    setup_phase: str | None,
) -> str | None:
    if decision_action not in {"buy", "sell"} or not setup_phase:
        return None
    if setup_phase == "range_noise":
        return None
    if setup_phase in {"short_continuation_confirmed", "long_continuation_confirmed"}:
        invalidation = "continuation_follow_through_failed"
    elif setup_phase == "short_breakdown_confirmed":
        invalidation = "breakdown_reclaimed"
    elif setup_phase == "short_rebound_fail_confirmed":
        invalidation = "rebound_fail_reclaimed"
    elif setup_phase == "long_pullback_reclaim_confirmed":
        invalidation = "reclaim_failed"
    elif setup_phase == "long_pullback_reclaim_unconfirmed":
        invalidation = "early_reclaim_failed"
    else:
        invalidation = "generic_structure_lost"
    direction = "long" if decision_action == "buy" else "short"
    return f"{direction}:{setup_phase}:{invalidation}"


def _setup_phase_from_candidate_reason(primary_reason: str | None) -> str | None:
    if primary_reason == "short_setup_pre_breakdown_watch":
        return "short_continuation_confirmed"
    if primary_reason == "short_setup_breakdown_confirmed":
        return "short_breakdown_confirmed"
    if primary_reason == "long_setup_pre_breakout_watch":
        return "long_continuation_confirmed"
    if primary_reason == "long_setup_pullback_reclaim_confirmed":
        return "long_pullback_reclaim_confirmed"
    if primary_reason == "long_setup_pullback_reclaim_unconfirmed":
        return "long_pullback_reclaim_unconfirmed"
    if primary_reason == "short_setup_rebound_fail_confirmed":
        return "short_rebound_fail_confirmed"
    if primary_reason == "short_setup_late_breakdown_soft_penalty":
        return "short_breakdown_chase"
    if primary_reason == "long_setup_late_breakout_soft_penalty":
        return "long_late_breakout_chase"
    return None


def _mean_or_none(values: list[float]) -> float | None:
    return mean(values) if values else None


def _median_or_none(values: list[float]) -> float | None:
    return median(values) if values else None


def _numeric_values(items: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for item in items:
        value = item.get(key)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _positive_numeric_values(items: list[dict[str, Any]], key: str) -> list[float]:
    return [value for value in _numeric_values(items, key) if value > 0.0]


def _negative_abs_numeric_values(items: list[dict[str, Any]], key: str) -> list[float]:
    return [abs(value) for value in _numeric_values(items, key) if value < 0.0]


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def _reason_key(reason: str | None) -> str | None:
    if reason is None:
        return None
    value = str(reason).strip()
    if not value:
        return None
    return value.split(":", 1)[0]


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(percentile, 1.0)) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)


def _bucketize_ranked(
    items: list[dict[str, Any]],
    key: str,
    *,
    labels: tuple[str, ...] = ("low", "mid", "high"),
) -> dict[str, list[dict[str, Any]]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        value = _float_or_none(item.get(key))
        if value is None:
            continue
        ranked.append((value, item))
    if not ranked:
        return {}

    ranked.sort(key=lambda pair: pair[0])
    total = len(ranked)
    result: dict[str, list[dict[str, Any]]] = {}
    for index, label in enumerate(labels):
        start = round((index * total) / len(labels))
        end = round(((index + 1) * total) / len(labels))
        bucket_items = [item for _value, item in ranked[start:end]]
        if bucket_items:
            result[label] = bucket_items
    return result


def _signed_bucket_direction(value: float | None, *, tolerance: float = 1e-9) -> str:
    if value is None:
        return "none"
    if value > tolerance:
        return "positive"
    if value < -tolerance:
        return "negative"
    return "flat"


def _directional_extremes_pct(
    candles: list[list[float]],
    *,
    entry_price: float,
    direction: int | None,
) -> tuple[float | None, float | None]:
    if direction is None or entry_price <= 0.0 or not candles:
        return None, None

    highs = [float(row[2]) for row in candles]
    lows = [float(row[3]) for row in candles]
    if direction > 0:
        mfe_pct = max(max(((high / entry_price) - 1.0) * 100.0 for high in highs), 0.0)
        mae_pct = max(max(((entry_price - low) / entry_price) * 100.0 for low in lows), 0.0)
        return mfe_pct, mae_pct

    mfe_pct = max(max(((entry_price - low) / entry_price) * 100.0 for low in lows), 0.0)
    mae_pct = max(max(((high - entry_price) / entry_price) * 100.0 for high in highs), 0.0)
    return mfe_pct, mae_pct


def _transition_metrics(items: list[dict[str, Any]], *, contract_market: bool, reentry_window_bars: int, timeframe_ms: int) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[str(item["symbol"])].append(item)

    transitions = 0
    flips = 0
    entry_count = 0
    reentries = 0
    reentry_window_ms = max(reentry_window_bars, 1) * timeframe_ms

    for symbol_items in grouped.values():
        ordered = sorted(symbol_items, key=lambda item: int(item["entry_ts"]))
        previous_actionable: dict[str, Any] | None = None
        previous_close: dict[str, Any] | None = None
        for item in ordered:
            action = str(item["review_action"])
            if action == "hold":
                continue
            if previous_actionable is not None:
                transitions += 1
                previous_direction = action_direction(
                    str(previous_actionable["review_action"]),
                    contract_market=contract_market,
                    position_side=previous_actionable.get("position_side_before_action"),
                )
                current_direction = action_direction(
                    action,
                    contract_market=contract_market,
                    position_side=item.get("position_side_before_action"),
                )
                if previous_direction is not None and current_direction is not None and previous_direction != current_direction:
                    flips += 1

            if bool(item.get("opened_position")):
                entry_count += 1
                if previous_close is not None and (int(item["entry_ts"]) - int(previous_close["entry_ts"])) <= reentry_window_ms:
                    reentries += 1

            if action == "close":
                previous_close = item
            previous_actionable = item

    return {
        "flip_rate": None if transitions == 0 else flips / transitions,
        "same_symbol_reentry_rate": None if entry_count == 0 else reentries / entry_count,
    }


def _summarize_reviews(
    items: list[dict[str, Any]],
    *,
    contract_market: bool,
    reentry_window_bars: int,
    timeframe_ms: int,
) -> dict[str, Any]:
    actionable_items = [item for item in items if item.get("review_group") == "actionable"]
    hold_items = [item for item in items if item.get("review_group") == "hold"]
    good_actionable_items = [item for item in actionable_items if item.get("outcome") == "good"]
    bad_actionable_items = [item for item in actionable_items if item.get("outcome") == "bad"]
    transition_metrics = _transition_metrics(
        items,
        contract_market=contract_market,
        reentry_window_bars=reentry_window_bars,
        timeframe_ms=timeframe_ms,
    )
    return {
        "reviewed": len(items),
        "good": sum(1 for item in items if item["outcome"] == "good"),
        "good_hold": sum(1 for item in items if item["outcome"] == "good_hold"),
        "bad": sum(1 for item in items if item["outcome"] == "bad"),
        "flat": sum(1 for item in items if item["outcome"] == "flat"),
        "missed_move": sum(1 for item in items if item["outcome"] == "missed_move"),
        "actionable_reviewed": len(actionable_items),
        "hold_reviewed": len(hold_items),
        "actionable_rate": _rate(len(actionable_items), len(items)),
        "win_rate": _rate(len(good_actionable_items), len(actionable_items)),
        "avg_win_pct": _mean_or_none(_positive_numeric_values(good_actionable_items, "net_edge_pct")),
        "avg_loss_pct": _mean_or_none(_negative_abs_numeric_values(bad_actionable_items, "net_edge_pct")),
        "avg_win_loss_ratio": (
            None
            if _mean_or_none(_negative_abs_numeric_values(bad_actionable_items, "net_edge_pct")) in {None, 0.0}
            or _mean_or_none(_positive_numeric_values(good_actionable_items, "net_edge_pct")) is None
            else float(_mean_or_none(_positive_numeric_values(good_actionable_items, "net_edge_pct")) or 0.0)
            / float(_mean_or_none(_negative_abs_numeric_values(bad_actionable_items, "net_edge_pct")) or 1.0)
        ),
        "avg_future_return_pct": _mean_or_none(_numeric_values(items, "market_future_return_pct")),
        "avg_gross_future_return_pct": _mean_or_none(_numeric_values(items, "gross_future_return_pct")),
        "avg_estimated_cost_pct": _mean_or_none(_numeric_values(items, "estimated_cost_pct")),
        "avg_net_edge_pct": _mean_or_none(_numeric_values(items, "net_edge_pct")),
        "avg_realized_post_cost_pct": _mean_or_none(_numeric_values(items, "net_edge_pct")),
        "avg_opportunity_edge_pct": _mean_or_none(_numeric_values(items, "opportunity_edge_pct")),
        "avg_planned_risk_pct_of_equity": _mean_or_none(_numeric_values(items, "planned_risk_pct_of_equity")),
        "avg_future_R": _mean_or_none(_numeric_values(items, "future_R")),
        "avg_mfe_pct": _mean_or_none(_numeric_values(items, "mfe_pct")),
        "avg_mae_pct": _mean_or_none(_numeric_values(items, "mae_pct")),
        "avg_giveback_pct": _mean_or_none(_numeric_values(items, "giveback_pct")),
        "avg_final_expected_edge_pct": _mean_or_none(_numeric_values(items, "final_expected_edge_pct")),
        "avg_required_threshold_pct": _mean_or_none(_numeric_values(items, "required_threshold_pct")),
        "avg_required_threshold_gap_pct": _mean_or_none(_numeric_values(items, "required_threshold_gap_pct")),
        "avg_volatility_component_pct": _mean_or_none(_numeric_values(items, "volatility_component_pct")),
        "avg_directional_component_pct": _mean_or_none(_numeric_values(items, "directional_component_pct")),
        **transition_metrics,
    }


def _blocked_reason_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        for reason in item.get("risk_reasons") or []:
            key = str(reason).split(":", 1)[0]
            counts[key] += 1
    return dict(sorted(counts.items()))


def _candidate_reason_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        key = str(item.get("candidate_filter_primary_reason") or "unknown")
        counts[key] += 1
    return dict(sorted(counts.items()))


def _hold_path(*, decision_action: str, review_action: str, candidate_filter_primary_reason: str) -> str | None:
    if review_action != "hold":
        return None
    if decision_action == "hold":
        if candidate_filter_primary_reason == "candidate_ok":
            return "candidate_ok_ai_hold"
        if candidate_filter_primary_reason == "position_management":
            return "management_ai_hold"
        return "candidate_penalty_ai_hold"
    if candidate_filter_primary_reason == "candidate_ok":
        return "candidate_ok_risk_hold"
    if candidate_filter_primary_reason == "position_management":
        return "management_risk_hold"
    return "candidate_penalty_risk_hold"


def _snapshot_directional_notional(account_positions: list[dict[str, Any]]) -> tuple[float, float]:
    long_notional_quote = 0.0
    short_notional_quote = 0.0
    for position in account_positions:
        notional_quote = abs(float(position.get("notional_quote") or position.get("market_value_quote") or 0.0))
        side = str(position.get("side") or "")
        if side == "long":
            long_notional_quote += notional_quote
        elif side == "short":
            short_notional_quote += notional_quote
    return long_notional_quote, short_notional_quote


def _action_notional_quote(item: dict[str, Any], *, contract_market: bool, leverage: float) -> float:
    review_action = str(item.get("review_action") or "hold")
    if is_open_action(review_action, contract_market):
        return max(float(item.get("equity_quote_before_action") or 0.0) * float(item.get("final_size_pct") or 0.0) * leverage, 0.0)
    if review_action == "close":
        return max(float(item.get("position_notional_before_action") or 0.0) * float(item.get("close_fraction") or 1.0), 0.0)
    return 0.0


def _cycle_summary(items: list[dict[str, Any]], *, contract_market: bool, leverage: float) -> dict[str, Any]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[int(item["entry_ts"])].append(item)

    cycles: list[dict[str, Any]] = []
    for entry_ts, cycle_items in sorted(grouped.items()):
        ordered = sorted(cycle_items, key=lambda item: int(item["run_id"]))
        first_item = ordered[0]
        start_long_notional_quote = float(first_item.get("snapshot_long_notional_quote") or 0.0)
        start_short_notional_quote = float(first_item.get("snapshot_short_notional_quote") or 0.0)
        delta_long_notional_quote = 0.0
        delta_short_notional_quote = 0.0
        symbol_details: list[dict[str, Any]] = []

        for item in ordered:
            action_notional_quote = _action_notional_quote(item, contract_market=contract_market, leverage=leverage)
            occupied_notional_quote = action_notional_quote
            if occupied_notional_quote <= 0.0:
                occupied_notional_quote = float(item.get("position_notional_before_action") or 0.0)

            review_action = str(item.get("review_action") or "hold")
            if review_action == "buy":
                delta_long_notional_quote += action_notional_quote
            elif review_action == "sell" and contract_market:
                delta_short_notional_quote += action_notional_quote
            elif review_action == "close":
                position_side_before_action = str(item.get("position_side_before_action") or "")
                if position_side_before_action == "long":
                    delta_long_notional_quote -= action_notional_quote
                elif position_side_before_action == "short":
                    delta_short_notional_quote -= action_notional_quote

            edge_metric_pct = item.get("exposure_future_return_pct")
            if edge_metric_pct is None:
                edge_metric_pct = item.get("net_edge_pct")
            symbol_details.append(
                {
                    "symbol": item["symbol"],
                    "review_action": review_action,
                    "outcome": item["outcome"],
                    "occupied_notional_quote": occupied_notional_quote,
                    "edge_metric_pct": edge_metric_pct,
                }
            )

        contributors = [
            detail["symbol"]
            for detail in symbol_details
            if float(detail.get("edge_metric_pct") or 0.0) > 0.0
        ]
        capacity_symbols = [
            detail["symbol"]
            for detail in symbol_details
            if float(detail.get("occupied_notional_quote") or 0.0) > 0.0
            and float(detail.get("edge_metric_pct") or 0.0) <= 0.0
        ]
        cycles.append(
            {
                "entry_ts": entry_ts,
                "processed_count": len(ordered),
                "processed_symbols": [item["symbol"] for item in ordered],
                "start_long_notional_quote": start_long_notional_quote,
                "start_short_notional_quote": start_short_notional_quote,
                "end_long_notional_quote": max(start_long_notional_quote + delta_long_notional_quote, 0.0),
                "end_short_notional_quote": max(start_short_notional_quote + delta_short_notional_quote, 0.0),
                "contributors": contributors,
                "capacity_symbols": capacity_symbols,
                "symbols": symbol_details,
            }
        )

    return {
        "cycles_reviewed": len(cycles),
        "avg_processed_symbols": _mean_or_none([float(cycle["processed_count"]) for cycle in cycles]),
        "max_processed_symbols": max((int(cycle["processed_count"]) for cycle in cycles), default=0),
        "avg_start_long_notional_quote": _mean_or_none([float(cycle["start_long_notional_quote"]) for cycle in cycles]),
        "avg_start_short_notional_quote": _mean_or_none([float(cycle["start_short_notional_quote"]) for cycle in cycles]),
        "avg_end_long_notional_quote": _mean_or_none([float(cycle["end_long_notional_quote"]) for cycle in cycles]),
        "avg_end_short_notional_quote": _mean_or_none([float(cycle["end_short_notional_quote"]) for cycle in cycles]),
        "cycles": cycles,
    }


def _candidate_filter_details(candidate_summary: dict[str, Any] | None, symbol: str) -> tuple[list[str], str, bool | None]:
    match = _candidate_filter_symbol_summary(candidate_summary, symbol)
    if not isinstance(match, dict):
        return [], "unknown", None
    reasons = [str(reason) for reason in (match.get("reasons") or [])]
    primary_reason = reasons[0] if reasons else "unknown"
    manage_only = match.get("manage_only")
    return reasons, primary_reason, None if manage_only is None else bool(manage_only)


def _candidate_filter_symbol_summary(candidate_summary: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    if not isinstance(candidate_summary, dict):
        return None
    symbol_summaries = candidate_summary.get("symbols") or []
    if not isinstance(symbol_summaries, list):
        return None
    match = next((item for item in symbol_summaries if str(item.get("symbol")) == symbol), None)
    return match if isinstance(match, dict) else None


def _bucket_summaries(
    items: list[dict[str, Any]],
    *,
    metric_key: str,
    contract_market: bool,
    reentry_window_bars: int,
    timeframe_ms: int,
) -> dict[str, dict[str, Any]]:
    return {
        bucket: _summarize_reviews(
            bucket_items,
            contract_market=contract_market,
            reentry_window_bars=reentry_window_bars,
            timeframe_ms=timeframe_ms,
        )
        for bucket, bucket_items in _bucketize_ranked(items, metric_key).items()
    }


def _symbol_snapshot_from_snapshot_entry(entry: dict[str, Any]) -> SymbolSnapshot | None:
    if not isinstance(entry, dict):
        return None
    recent_candles_raw = entry.get("recent_candles") or []
    if not isinstance(recent_candles_raw, list):
        return None
    recent_candles: list[Candle] = []
    for candle in recent_candles_raw:
        if not isinstance(candle, dict):
            continue
        recent_candles.append(
            Candle(
                timestamp_ms=int(candle["timestamp_ms"]),
                open=float(candle["open"]),
                high=float(candle["high"]),
                low=float(candle["low"]),
                close=float(candle["close"]),
                volume=float(candle["volume"]),
            )
        )
    if not recent_candles:
        return None
    indicators = entry.get("indicators") or {}
    return SymbolSnapshot(
        symbol=str(entry.get("symbol") or ""),
        timeframe=str(entry.get("timeframe") or "5m"),
        last_price=float(entry.get("last_price") or recent_candles[-1].close),
        indicators={str(key): float(value) for key, value in indicators.items()},
        recent_candles=recent_candles,
        exchange_min_cost_quote=(
            None if entry.get("exchange_min_cost_quote") is None else float(entry.get("exchange_min_cost_quote"))
        ),
        exchange_min_amount=(
            None if entry.get("exchange_min_amount") is None else float(entry.get("exchange_min_amount"))
        ),
        exchange_amount_step=(
            None if entry.get("exchange_amount_step") is None else float(entry.get("exchange_amount_step"))
        ),
        higher_timeframe=entry.get("higher_timeframe"),
        candidate_context=entry.get("candidate_context"),
    )


def _decision_control_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    ai_open_items = [item for item in items if bool(item.get("ai_open_requested"))]
    risk_veto_items = [item for item in ai_open_items if bool(item.get("risk_vetoed_ai_open"))]
    ai_open_executed_items = [item for item in ai_open_items if bool(item.get("opened_position"))]
    size_override_items = [item for item in ai_open_executed_items if bool(item.get("size_overridden"))]
    take_profit_override_items = [item for item in ai_open_executed_items if bool(item.get("take_profit_overridden"))]
    stop_loss_override_items = [item for item in ai_open_executed_items if bool(item.get("stop_loss_overridden"))]
    return {
        "reviewed": len(items),
        "ai_open_decisions": len(ai_open_items),
        "ai_open_action_rate": _rate(len(ai_open_items), len(items)),
        "ai_open_executed": len(ai_open_executed_items),
        "risk_veto_after_ai_open": len(risk_veto_items),
        "risk_veto_rate_after_ai_open": _rate(len(risk_veto_items), len(ai_open_items)),
        "size_override_count": len(size_override_items),
        "size_override_rate": _rate(len(size_override_items), len(ai_open_executed_items)),
        "take_profit_override_count": len(take_profit_override_items),
        "take_profit_override_rate": _rate(len(take_profit_override_items), len(ai_open_executed_items)),
        "stop_loss_override_count": len(stop_loss_override_items),
        "stop_loss_override_rate": _rate(len(stop_loss_override_items), len(ai_open_executed_items)),
    }


def _comparison_consistency(current: dict[str, Any], baseline: dict[str, Any]) -> str:
    current_actionable = _signed_bucket_direction(current.get("actionable_avg_net_edge_pct"))
    baseline_actionable = _signed_bucket_direction(baseline.get("actionable_avg_net_edge_pct"))
    current_fresh = _signed_bucket_direction(current.get("fresh_entry_avg_net_edge_pct"))
    baseline_fresh = _signed_bucket_direction(baseline.get("fresh_entry_avg_net_edge_pct"))
    if current_actionable == baseline_actionable and current_fresh == baseline_fresh:
        return "consistent"
    if "none" in {current_actionable, baseline_actionable, current_fresh, baseline_fresh}:
        return "insufficient_data"
    return "mixed"


def _bucket_monotonicity(by_bucket: dict[str, dict[str, Any]], *, metric_key: str) -> str:
    ordered_values = [
        _float_or_none((by_bucket.get(label) or {}).get(metric_key))
        for label in ("low", "mid", "high")
        if label in by_bucket
    ]
    if len(ordered_values) < 2 or any(value is None for value in ordered_values):
        return "insufficient_data"
    increasing = all(
        float(ordered_values[index] or 0.0) <= float(ordered_values[index + 1] or 0.0)
        for index in range(len(ordered_values) - 1)
    )
    decreasing = all(
        float(ordered_values[index] or 0.0) >= float(ordered_values[index + 1] or 0.0)
        for index in range(len(ordered_values) - 1)
    )
    if increasing and len(set(float(value or 0.0) for value in ordered_values)) > 1:
        return "increasing"
    if decreasing and len(set(float(value or 0.0) for value in ordered_values)) > 1:
        return "decreasing"
    return "mixed"


def _high_vol_bias_label(by_bucket: dict[str, dict[str, Any]]) -> str:
    low_bucket = by_bucket.get("low") or {}
    high_bucket = by_bucket.get("high") or {}
    low_actionable_rate = _float_or_none(low_bucket.get("actionable_rate"))
    high_actionable_rate = _float_or_none(high_bucket.get("actionable_rate"))
    low_realized = _float_or_none(low_bucket.get("avg_realized_post_cost_pct"))
    high_realized = _float_or_none(high_bucket.get("avg_realized_post_cost_pct"))
    if None in {low_actionable_rate, high_actionable_rate, low_realized, high_realized}:
        return "insufficient_data"
    if float(high_actionable_rate or 0.0) > float(low_actionable_rate or 0.0) and float(high_realized or 0.0) <= float(low_realized or 0.0):
        return "present"
    if float(high_actionable_rate or 0.0) <= float(low_actionable_rate or 0.0) and float(high_realized or 0.0) > float(low_realized or 0.0):
        return "not_obvious"
    return "mixed"


def _normalized_symbol_key(symbol: str) -> str:
    base = str(symbol).split(":", 1)[0]
    return base.strip().upper()


def _extract_fill_from_order(order: dict[str, Any]) -> tuple[float | None, float | None]:
    filled = _float_or_none(order.get("filled"))
    average = _float_or_none(order.get("average"))
    cost = _float_or_none(order.get("cost"))
    fill_price = average
    if (fill_price is None or fill_price <= 0.0) and filled is not None and filled > 0.0 and cost is not None and cost > 0.0:
        fill_price = cost / filled
    return fill_price, filled


def _extract_fee_metrics(order: dict[str, Any], *, fill_price: float | None, filled_quantity: float | None) -> tuple[float | None, float | None]:
    def collect_fee_entries(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            if (
                ("cost" in payload or "rate" in payload)
                and not any(key in payload for key in ("symbol", "type", "side", "amount", "filled", "average", "status"))
            ):
                return [payload]
            entries: list[dict[str, Any]] = []
            for key in ("fee", "fees"):
                child = payload.get(key)
                if isinstance(child, dict):
                    entries.append(child)
                elif isinstance(child, list):
                    entries.extend([item for item in child if isinstance(item, dict)])
            return entries
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    fee_entries = collect_fee_entries(order)
    info = order.get("info")
    fee_entries.extend(collect_fee_entries(info))
    fee_costs = [
        float(cost)
        for cost in (
            _float_or_none(entry.get("cost"))
            for entry in fee_entries
        )
        if cost is not None
    ]
    fee_rates = [
        float(rate)
        for rate in (
            _float_or_none(entry.get("rate"))
            for entry in fee_entries
        )
        if rate is not None
    ]
    fee_cost_quote = sum(fee_costs) if fee_costs else None
    fee_rate = _mean_or_none(fee_rates)
    if fee_rate is None and fee_cost_quote is not None and fill_price is not None and filled_quantity is not None:
        notional_quote = fill_price * filled_quantity
        if notional_quote > 0.0:
            fee_rate = fee_cost_quote / notional_quote
    return fee_cost_quote, fee_rate


class ReviewService:
    def __init__(self, settings: Settings, journal: Journal) -> None:
        self.settings = settings
        self.journal = journal

    def _exchange(self):
        return build_exchange(self.settings, private=False)

    def _signal_review_candidates(self, limit: int) -> list[dict[str, Any]]:
        return self.journal.get_signal_review_candidates(limit=limit)

    def _filter_candidates_by_symbols(
        self,
        candidates: list[dict[str, Any]],
        symbols_filter: list[str] | tuple[str, ...] | None,
    ) -> list[dict[str, Any]]:
        if not symbols_filter:
            return candidates
        normalized = {_normalized_symbol_key(symbol) for symbol in symbols_filter}
        return [
            candidate
            for candidate in candidates
            if _normalized_symbol_key(str((candidate.get("payload_json") or {}).get("decision", {}).get("symbol") or "")) in normalized
        ]

    def _bundle_from_snapshot_json(self, snapshot_json: dict[str, Any]) -> MarketSnapshotBundle:
        symbols: list[SymbolSnapshot] = []
        for symbol_entry in snapshot_json.get("symbols", []):
            recent_candles = [
                Candle(
                    timestamp_ms=int(candle["timestamp_ms"]),
                    open=float(candle["open"]),
                    high=float(candle["high"]),
                    low=float(candle["low"]),
                    close=float(candle["close"]),
                    volume=float(candle["volume"]),
                )
                for candle in (symbol_entry.get("recent_candles") or [])
            ]
            indicators = {
                str(key): float(value)
                for key, value in (symbol_entry.get("indicators") or {}).items()
            }
            symbols.append(
                SymbolSnapshot(
                    symbol=str(symbol_entry["symbol"]),
                    timeframe=str(symbol_entry["timeframe"]),
                    last_price=float(symbol_entry["last_price"]),
                    indicators=indicators,
                    recent_candles=recent_candles,
                    exchange_min_cost_quote=_float_or_none(symbol_entry.get("exchange_min_cost_quote")),
                    exchange_min_amount=_float_or_none(symbol_entry.get("exchange_min_amount")),
                    exchange_amount_step=_float_or_none(symbol_entry.get("exchange_amount_step")),
                    higher_timeframe=symbol_entry.get("higher_timeframe"),
                    candidate_context=symbol_entry.get("candidate_context"),
                )
            )

        account_json = snapshot_json.get("account") or {}
        open_positions = [
            PositionSnapshot(
                symbol=str(position["symbol"]),
                quantity=float(position["quantity"]),
                mark_price=float(position["mark_price"]),
                market_value_quote=float(position["market_value_quote"]),
                side=None if position.get("side") is None else str(position.get("side")),
                average_entry_price=_float_or_none(position.get("average_entry_price")),
                notional_quote=_float_or_none(position.get("notional_quote")),
                unrealized_pnl_quote=_float_or_none(position.get("unrealized_pnl_quote")),
                leverage=_float_or_none(position.get("leverage")),
                margin_mode=None if position.get("margin_mode") is None else str(position.get("margin_mode")),
                liquidation_price=_float_or_none(position.get("liquidation_price")),
            )
            for position in (account_json.get("open_positions") or [])
        ]
        account = AccountSnapshot(
            quote_currency=str(account_json.get("quote_currency") or self.settings.quote_currency),
            equity_quote=float(account_json.get("equity_quote") or 0.0),
            free_quote=float(account_json.get("free_quote") or 0.0),
            open_positions=open_positions,
            mode=str(account_json.get("mode") or self.settings.mode),
            market_type=str(account_json.get("market_type") or self.settings.market_type),
        )
        generated_at_raw = str(snapshot_json.get("generated_at") or "")
        generated_at = datetime.fromisoformat(generated_at_raw) if generated_at_raw else datetime.now()
        return MarketSnapshotBundle(
            generated_at=generated_at,
            timeframe=str(snapshot_json.get("timeframe") or self.settings.timeframe),
            symbols=symbols,
            account=account,
        )

    def _validated_from_candidate(self, candidate: dict[str, Any]) -> ValidatedDecision:
        payload_json = candidate["payload_json"]
        decision_json = payload_json["decision"]
        decision = AIDecision(
            timestamp=str(decision_json["timestamp"]),
            symbol=str(decision_json["symbol"]),
            action=str(decision_json["action"]),
            size_pct=float(decision_json["size_pct"]),
            take_profit_pct=float(decision_json["take_profit_pct"]),
            stop_loss_pct=float(decision_json["stop_loss_pct"]),
            ttl_minutes=int(decision_json["ttl_minutes"]),
            confidence=float(decision_json["confidence"]),
            reason=str(decision_json["reason"]),
            prompt_version=str(decision_json["prompt_version"]),
        )
        return ValidatedDecision(
            decision=decision,
            valid=bool(candidate["valid"]),
            errors=[str(error) for error in (candidate.get("errors_json") or [])],
            raw_payload=payload_json.get("raw_payload"),
        )

    def _replayed_candidates_with_current_risk(self, limit: int) -> list[dict[str, Any]]:
        from .risk_engine import RiskEngine

        candidates = list(reversed(self._signal_review_candidates(limit=limit)))
        if not candidates:
            return []

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay_settings = replace(
                self.settings,
                project_root=root,
                state_dir=root / "state",
                snapshot_dir=root / "state" / "snapshots",
                decision_dir=root / "state" / "decisions",
                log_dir=root / "state" / "logs",
                db_path=root / "state" / "replay.db",
            )
            replay_settings.ensure_directories()
            replay_journal = Journal(replay_settings.db_path)
            replay_journal.ensure_schema()
            replay_risk = RiskEngine(replay_settings, replay_journal)
            replayed: list[dict[str, Any]] = []

            for candidate in candidates:
                bundle = self._bundle_from_snapshot_json(candidate["snapshot_json"])
                validated = self._validated_from_candidate(candidate)
                replay_run_id = replay_journal.start_run(replay_settings.mode)
                replay_journal.record_snapshot(replay_run_id, bundle)
                replay_journal.record_validated_decision(replay_run_id, validated)
                replay_verdict = replay_risk.evaluate(validated, bundle)
                replay_journal.record_risk(replay_run_id, replay_verdict)
                replay_journal.finish_run(replay_run_id, "completed", {"run_id": replay_run_id, "replay": True})
                replayed.append(
                    {
                        **candidate,
                        "verdict_json": to_jsonable(replay_verdict),
                    }
                )
        return list(reversed(replayed))

    def _symbol_candles_for_candidates(self, candidates: list[dict[str, Any]]) -> dict[str, list[list[float]]]:
        timeframe_ms = timeframe_to_ms(self.settings.timeframe)
        symbol_to_min_ts: dict[str, int] = {}
        for candidate in candidates:
            snapshot = candidate["snapshot_json"]
            decision = candidate["payload_json"]["decision"]
            symbol = str(decision["symbol"])
            symbol_entry = next((entry for entry in snapshot.get("symbols", []) if entry["symbol"] == symbol), None)
            if not symbol_entry or not symbol_entry.get("recent_candles"):
                continue
            entry_ts = int(symbol_entry["recent_candles"][-1]["timestamp_ms"])
            symbol_to_min_ts[symbol] = min(entry_ts, symbol_to_min_ts.get(symbol, entry_ts))

        exchange = self._exchange()
        symbol_candles: dict[str, list[list[float]]] = {}
        for symbol, min_ts in symbol_to_min_ts.items():
            since = max(0, min_ts - timeframe_ms)
            symbol_candles[symbol] = exchange.fetch_ohlcv(symbol, timeframe=self.settings.timeframe, since=since, limit=1000)
        return symbol_candles

    def _signal_review_from_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        symbol_candles: dict[str, list[list[float]]],
        horizon_bars: int,
        threshold_pct: float,
    ) -> dict[str, Any]:
        if not candidates:
            return {
                "exchange_id": self.settings.exchange_id,
                "timeframe": self.settings.timeframe,
                "horizon_bars": horizon_bars,
                "threshold_pct": threshold_pct,
                "count": 0,
                "reviews": [],
            }

        timeframe_ms = timeframe_to_ms(self.settings.timeframe)
        reviews: list[dict[str, Any]] = []
        for candidate in candidates:
            snapshot = candidate["snapshot_json"]
            decision = candidate["payload_json"]["decision"]
            verdict = candidate["verdict_json"]
            review_action = str(verdict.get("final_action") or decision["action"])
            symbol = str(verdict.get("symbol") or decision["symbol"])
            symbol_entry = next((entry for entry in snapshot.get("symbols", []) if entry["symbol"] == symbol), None)
            if not symbol_entry or not symbol_entry.get("recent_candles"):
                reviews.append(
                    {
                        "run_id": candidate["run_id"],
                        "status": "incomplete",
                        "reason": "missing_symbol_snapshot",
                    }
                )
                continue

            entry_candle = symbol_entry["recent_candles"][-1]
            entry_ts = int(entry_candle["timestamp_ms"])
            entry_price = float(entry_candle["close"])
            horizon_ts = entry_ts + (horizon_bars * timeframe_ms)
            future_candle = next((row for row in symbol_candles.get(symbol, []) if int(row[0]) >= horizon_ts), None)
            if future_candle is None:
                reviews.append(
                    {
                        "run_id": candidate["run_id"],
                        "symbol": symbol,
                        "action": decision["action"],
                        "status": "incomplete",
                        "reason": "missing_future_candle",
                    }
                )
                continue

            account_positions = (snapshot.get("account") or {}).get("open_positions") or []
            snapshot_long_notional_quote, snapshot_short_notional_quote = _snapshot_directional_notional(account_positions)
            position_entry = next((item for item in account_positions if item.get("symbol") == symbol), None)
            position_side = None if position_entry is None else position_entry.get("side")
            position_notional_before_action = 0.0 if position_entry is None else abs(
                float(position_entry.get("notional_quote") or position_entry.get("market_value_quote") or 0.0)
            )
            risk_reasons = [str(reason) for reason in (verdict.get("reasons") or [])]
            risk_debug = verdict.get("risk_debug") or {}
            raw_payload = candidate["payload_json"].get("raw_payload") or {}
            candidate_summary = raw_payload.get("candidate_filter")
            candidate_summary_for_symbol = _candidate_filter_symbol_summary(candidate_summary, symbol) or {}
            entry_thesis = raw_payload.get("entry_thesis") or risk_debug.get("entry_thesis") or {}
            entry_thesis = entry_thesis if isinstance(entry_thesis, dict) else {}
            symbol_snapshot_for_assessment = _symbol_snapshot_from_snapshot_entry(symbol_entry)
            setup_phase = (
                candidate_context.get("setup_phase")
                if isinstance(candidate_context := (symbol_entry.get("candidate_context") or {}), dict)
                else None
            ) or candidate_summary_for_symbol.get("setup_phase")
            candidate_context = symbol_entry.get("candidate_context") or {}
            opened_position = is_open_action(review_action, self.settings.contract_market)
            close_fraction = float(verdict.get("close_fraction") or 1.0)
            decision_context = _decision_context(
                opened_position=opened_position,
                position_side_before_action=position_side,
            )
            decision_lifecycle = _decision_lifecycle(
                decision_action=str(decision["action"]),
                review_action=review_action,
                contract_market=self.settings.contract_market,
                position_side_before_action=position_side,
                close_fraction=close_fraction,
            )
            exit_source = _exit_source(
                decision_action=str(decision["action"]),
                review_action=review_action,
                risk_reasons=risk_reasons,
            )
            blocked_group = _blocked_group(decision_lifecycle)
            candidate_filter_reasons, candidate_filter_primary_reason, candidate_filter_manage_only = _candidate_filter_details(
                candidate_summary,
                symbol,
            )
            if setup_phase is None:
                setup_phase = _setup_phase_from_candidate_reason(candidate_filter_primary_reason)
            if setup_phase is None and symbol_snapshot_for_assessment is not None:
                assessment = assess_fresh_entry(symbol_snapshot_for_assessment, action=str(decision["action"]))
                if assessment.setup_phase != "range_noise":
                    setup_phase = assessment.setup_phase
            entry_thesis_key = None
            if entry_thesis:
                direction = str(entry_thesis.get("direction") or "unknown")
                setup = str(entry_thesis.get("setup_phase") or "unknown")
                invalidation = str(entry_thesis.get("invalidation_type") or "unknown")
                entry_thesis_key = f"{direction}:{setup}:{invalidation}"
            if entry_thesis_key is None:
                entry_thesis_key = _synthetic_entry_thesis_key(
                    decision_action=str(decision["action"]),
                    setup_phase=None if setup_phase is None else str(setup_phase),
                )
            higher_timeframe = symbol_entry.get("higher_timeframe") or {}
            higher_timeframe_phase = (
                candidate_context.get("higher_timeframe_phase")
                or candidate_summary_for_symbol.get("higher_timeframe_phase")
                or higher_timeframe.get("trend_phase")
            )
            setup_phase = candidate_context.get("setup_phase") or candidate_summary_for_symbol.get("setup_phase")
            setup_confirmed = candidate_context.get("setup_confirmed")
            if setup_confirmed is None:
                setup_confirmed = candidate_summary_for_symbol.get("setup_confirmed")
            hold_path = _hold_path(
                decision_action=str(decision["action"]),
                review_action=review_action,
                candidate_filter_primary_reason=candidate_filter_primary_reason,
            )
            future_close = float(future_candle[4])
            market_future_return_pct = ((future_close / entry_price) - 1.0) * 100.0
            position_direction = _position_direction(position_side)
            position_future_return_pct = (
                None if position_direction is None else market_future_return_pct * position_direction
            )
            direction = action_direction(
                review_action,
                contract_market=self.settings.contract_market,
                position_side=position_side,
            )
            gross_future_return_pct = 0.0 if direction is None else market_future_return_pct * direction
            estimated_cost_pct = estimated_action_cost_pct(
                review_action,
                contract_market=self.settings.contract_market,
                fee_pct=self.settings.estimated_fee_pct,
                slippage_pct=self.settings.estimated_slippage_pct,
            ) * 100.0
            net_edge_pct = gross_future_return_pct - estimated_cost_pct
            decision_size_pct = float(decision.get("size_pct") or 0.0)
            decision_take_profit_pct = float(decision.get("take_profit_pct") or 0.0)
            decision_stop_loss_pct = float(decision.get("stop_loss_pct") or 0.0)
            final_size_pct = float(verdict.get("final_size_pct") or 0.0)
            take_profit_pct = float(verdict.get("take_profit_pct") or 0.0)
            stop_loss_pct = float(verdict.get("stop_loss_pct") or 0.0)
            leverage = float(self.settings.contract_leverage) if self.settings.contract_market else 1.0
            planned_risk_pct_of_equity = None
            future_r = None
            if opened_position and final_size_pct > 0.0 and stop_loss_pct > 0.0:
                planned_risk_pct_of_equity = final_size_pct * leverage * (
                    stop_loss_pct + (estimated_cost_pct / 100.0)
                ) * 100.0
                if planned_risk_pct_of_equity > 0.0:
                    future_r = net_edge_pct / planned_risk_pct_of_equity
            future_window_candles = [
                row
                for row in symbol_candles.get(symbol, [])
                if entry_ts < int(row[0]) <= int(future_candle[0])
            ] or [future_candle]
            exposure_direction = direction if direction is not None else position_direction
            exposure_future_return_pct = (
                None if exposure_direction is None else market_future_return_pct * exposure_direction
            )
            mfe_pct, mae_pct = _directional_extremes_pct(
                future_window_candles,
                entry_price=entry_price,
                direction=exposure_direction,
            )
            giveback_pct = (
                None
                if mfe_pct is None or exposure_future_return_pct is None
                else max(mfe_pct - max(exposure_future_return_pct, 0.0), 0.0)
            )
            opportunity_edge_pct = max(
                abs(market_future_return_pct)
                - (
                    estimated_action_cost_pct(
                        "buy",
                        contract_market=self.settings.contract_market,
                        fee_pct=self.settings.estimated_fee_pct,
                        slippage_pct=self.settings.estimated_slippage_pct,
                    )
                    * 100.0
                ),
                0.0,
            )
            close_cost_pct = estimated_action_cost_pct(
                "close",
                contract_market=self.settings.contract_market,
                fee_pct=self.settings.estimated_fee_pct,
                slippage_pct=self.settings.estimated_slippage_pct,
            ) * 100.0
            threshold_pct_value = threshold_pct * 100.0
            expected_edge_components = risk_debug.get("expected_edge_components")
            expected_edge_components = expected_edge_components if isinstance(expected_edge_components, dict) else {}
            shadow_open_signal_reasons = [
                str(reason)
                for reason in (risk_debug.get("shadow_open_signal_reasons") or [])
            ]

            outcome = "flat"
            if review_action == "hold":
                if position_future_return_pct is None:
                    outcome = "missed_move" if opportunity_edge_pct > threshold_pct_value else "good_hold"
                else:
                    adverse_exit_edge_pct = max((-position_future_return_pct) - close_cost_pct, 0.0)
                    outcome = "missed_move" if adverse_exit_edge_pct > threshold_pct_value else "good_hold"
            elif net_edge_pct > threshold_pct_value:
                outcome = "good"
            elif net_edge_pct < -threshold_pct_value:
                outcome = "bad"

            ai_open_requested = is_open_action(str(decision["action"]), self.settings.contract_market)
            reviews.append(
                {
                    "run_id": candidate["run_id"],
                    "symbol": symbol,
                    "decision_action": str(decision["action"]),
                    "risk_final_action": review_action,
                    "review_action": review_action,
                    "review_group": _review_group(review_action),
                    "entry_ts": entry_ts,
                    "entry_price": entry_price,
                    "future_ts": int(future_candle[0]),
                    "future_close": future_close,
                    "market_future_return_pct": market_future_return_pct,
                    "gross_future_return_pct": gross_future_return_pct,
                    "estimated_cost_pct": estimated_cost_pct,
                    "net_edge_pct": net_edge_pct,
                    "opportunity_edge_pct": opportunity_edge_pct,
                    "confidence": float(decision["confidence"]),
                    "confidence_bucket": confidence_bucket(float(decision["confidence"])),
                    "equity_quote_before_action": float((snapshot.get("account") or {}).get("equity_quote") or 0.0),
                    "decision_size_pct": decision_size_pct,
                    "decision_take_profit_pct": decision_take_profit_pct,
                    "decision_stop_loss_pct": decision_stop_loss_pct,
                    "final_size_pct": final_size_pct,
                    "take_profit_pct": take_profit_pct,
                    "stop_loss_pct": stop_loss_pct,
                    "size_overridden": ai_open_requested and abs(final_size_pct - decision_size_pct) > 1e-9,
                    "take_profit_overridden": ai_open_requested and abs(take_profit_pct - decision_take_profit_pct) > 1e-9,
                    "stop_loss_overridden": ai_open_requested and abs(stop_loss_pct - decision_stop_loss_pct) > 1e-9,
                    "ai_open_requested": ai_open_requested,
                    "risk_vetoed_ai_open": ai_open_requested and review_action == "hold",
                    "position_side_before_action": position_side,
                    "position_notional_before_action": position_notional_before_action,
                    "position_future_return_pct": position_future_return_pct,
                    "opened_position": opened_position,
                    "close_fraction": close_fraction,
                    "decision_context": decision_context,
                    "decision_lifecycle": decision_lifecycle,
                    "exit_source": exit_source,
                    "blocked_group": blocked_group,
                    "hold_path": hold_path,
                    "planned_risk_pct_of_equity": planned_risk_pct_of_equity,
                    "future_R": future_r,
                    "exposure_future_return_pct": exposure_future_return_pct,
                    "mfe_pct": mfe_pct,
                    "mae_pct": mae_pct,
                    "giveback_pct": giveback_pct,
                    "snapshot_long_notional_quote": snapshot_long_notional_quote,
                    "snapshot_short_notional_quote": snapshot_short_notional_quote,
                    "portfolio_context": risk_debug.get("portfolio_context"),
                    "candidate_filter_reasons": candidate_filter_reasons,
                    "candidate_filter_primary_reason": candidate_filter_primary_reason,
                    "candidate_filter_manage_only": candidate_filter_manage_only,
                    "higher_timeframe_phase": higher_timeframe_phase,
                    "setup_phase": setup_phase,
                    "setup_confirmed": setup_confirmed,
                    "phase_match_score": (
                        candidate_context.get("phase_match_score")
                        if candidate_context.get("phase_match_score") is not None
                        else candidate_summary_for_symbol.get("phase_match_score")
                    ),
                    "entry_thesis": entry_thesis or None,
                    "entry_thesis_key": entry_thesis_key,
                    "close_cost_pct": close_cost_pct,
                    "risk_reasons": risk_reasons,
                    "primary_risk_reason": _reason_key(risk_reasons[0] if risk_reasons else None) or "ok",
                    "entry_archetype": str(risk_debug.get("entry_archetype") or "unknown"),
                    "shadow_open_signal_reasons": shadow_open_signal_reasons,
                    "expected_edge_components": expected_edge_components,
                    "final_expected_edge_pct": _float_or_none(expected_edge_components.get("final_expected_edge_pct")),
                    "required_threshold_pct": _float_or_none(
                        expected_edge_components.get("required_threshold_pct")
                        if expected_edge_components.get("required_threshold_pct") is not None
                        else expected_edge_components.get("threshold_pct")
                    ),
                    "required_threshold_gap_pct": _float_or_none(
                        expected_edge_components.get("required_threshold_gap_pct")
                        if expected_edge_components.get("required_threshold_gap_pct") is not None
                        else expected_edge_components.get("threshold_gap_pct")
                    ),
                    "volatility_component_pct": _float_or_none(expected_edge_components.get("volatility_component_pct")),
                    "directional_component_pct": _float_or_none(expected_edge_components.get("directional_component_pct")),
                    "valid": bool(candidate["valid"]),
                    "outcome": outcome,
                    "status": "reviewed",
                }
            )

        reviewed = [item for item in reviews if item.get("status") == "reviewed"]
        hold_reviews = [item for item in reviewed if item.get("review_group") == "hold"]
        actionable_reviews = [item for item in reviewed if item.get("review_group") == "actionable"]
        blocked_sell_reviews = [
            item
            for item in reviewed
            if item.get("decision_action") == "sell" and item.get("risk_final_action") == "hold"
        ]
        by_symbol = {
            symbol: _summarize_reviews(
                symbol_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for symbol, symbol_reviews in defaultdict(list, {
                symbol: [item for item in reviewed if item["symbol"] == symbol]
                for symbol in sorted({str(item["symbol"]) for item in reviewed})
            }).items()
        }
        by_action = {
            action: _summarize_reviews(
                action_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for action, action_reviews in defaultdict(list, {
                action: [item for item in reviewed if item["review_action"] == action]
                for action in sorted({str(item["review_action"]) for item in reviewed})
            }).items()
        }
        by_confidence = {
            bucket: _summarize_reviews(
                bucket_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for bucket, bucket_reviews in defaultdict(list, {
                bucket: [item for item in reviewed if item["confidence_bucket"] == bucket]
                for bucket in ("low", "medium", "high")
                if any(item["confidence_bucket"] == bucket for item in reviewed)
            }).items()
        }
        by_context = {
            context: _summarize_reviews(
                context_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for context, context_reviews in defaultdict(list, {
                context: [item for item in reviewed if item["decision_context"] == context]
                for context in ("entry", "management", "idle")
                if any(item["decision_context"] == context for item in reviewed)
            }).items()
        }
        by_lifecycle = {
            lifecycle: _summarize_reviews(
                lifecycle_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for lifecycle, lifecycle_reviews in defaultdict(list, {
                lifecycle: [item for item in reviewed if item["decision_lifecycle"] == lifecycle]
                for lifecycle in sorted({str(item["decision_lifecycle"]) for item in reviewed})
            }).items()
        }
        by_exit_source = {
            exit_source: _summarize_reviews(
                exit_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for exit_source, exit_reviews in defaultdict(list, {
                exit_source: [item for item in reviewed if item.get("exit_source") == exit_source]
                for exit_source in sorted({str(item["exit_source"]) for item in reviewed if item.get("exit_source") is not None})
            }).items()
        }
        by_blocked_group = {
            blocked_group: _summarize_reviews(
                blocked_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for blocked_group, blocked_reviews in defaultdict(list, {
                blocked_group: [item for item in reviewed if item.get("blocked_group") == blocked_group]
                for blocked_group in sorted({str(item["blocked_group"]) for item in reviewed if item.get("blocked_group") is not None})
            }).items()
        }
        by_candidate_reason = {
            reason: _summarize_reviews(
                reason_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for reason, reason_reviews in defaultdict(list, {
                reason: [item for item in reviewed if item["candidate_filter_primary_reason"] == reason]
                for reason in sorted({str(item["candidate_filter_primary_reason"]) for item in reviewed})
            }).items()
        }
        by_hold_path = {
            hold_path: _summarize_reviews(
                hold_reviews_for_path,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for hold_path, hold_reviews_for_path in defaultdict(list, {
                hold_path: [item for item in reviewed if item.get("hold_path") == hold_path]
                for hold_path in sorted({str(item["hold_path"]) for item in reviewed if item.get("hold_path") is not None})
            }).items()
        }
        by_primary_risk_reason = {
            reason: _summarize_reviews(
                reason_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for reason, reason_reviews in defaultdict(list, {
                reason: [item for item in reviewed if item["primary_risk_reason"] == reason]
                for reason in sorted({str(item["primary_risk_reason"]) for item in reviewed})
            }).items()
        }
        by_entry_archetype = {
            archetype: _summarize_reviews(
                archetype_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for archetype, archetype_reviews in defaultdict(list, {
                archetype: [item for item in reviewed if item.get("entry_archetype") == archetype]
                for archetype in sorted({str(item["entry_archetype"]) for item in reviewed if item.get("entry_archetype") is not None})
            }).items()
        }
        by_entry_thesis = {
            thesis_key: _summarize_reviews(
                thesis_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for thesis_key, thesis_reviews in defaultdict(list, {
                thesis_key: [item for item in reviewed if item.get("entry_thesis_key") == thesis_key]
                for thesis_key in sorted({str(item["entry_thesis_key"]) for item in reviewed if item.get("entry_thesis_key") is not None})
            }).items()
        }
        by_setup_phase = {
            phase: _summarize_reviews(
                phase_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for phase, phase_reviews in defaultdict(list, {
                phase: [item for item in reviewed if item.get("setup_phase") == phase]
                for phase in sorted({str(item["setup_phase"]) for item in reviewed if item.get("setup_phase") is not None})
            }).items()
        }
        by_higher_timeframe_phase = {
            phase: _summarize_reviews(
                phase_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            )
            for phase, phase_reviews in defaultdict(list, {
                phase: [item for item in reviewed if item.get("higher_timeframe_phase") == phase]
                for phase in sorted(
                    {
                        str(item["higher_timeframe_phase"])
                        for item in reviewed
                        if item.get("higher_timeframe_phase") is not None
                    }
                )
            }).items()
        }
        by_expected_edge_bucket = _bucket_summaries(
            reviewed,
            metric_key="final_expected_edge_pct",
            contract_market=self.settings.contract_market,
            reentry_window_bars=horizon_bars,
            timeframe_ms=timeframe_ms,
        )
        by_volatility_bucket = _bucket_summaries(
            reviewed,
            metric_key="volatility_component_pct",
            contract_market=self.settings.contract_market,
            reentry_window_bars=horizon_bars,
            timeframe_ms=timeframe_ms,
        )
        cycle_summary = _cycle_summary(
            reviewed,
            contract_market=self.settings.contract_market,
            leverage=float(self.settings.contract_leverage) if self.settings.contract_market else 1.0,
        )
        aggregate = {
            "reviewed": len(reviewed),
            "incomplete": len(reviews) - len(reviewed),
            "overall": _summarize_reviews(
                reviewed,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            ),
            "hold": _summarize_reviews(
                hold_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            ),
            "actionable": _summarize_reviews(
                actionable_reviews,
                contract_market=self.settings.contract_market,
                reentry_window_bars=horizon_bars,
                timeframe_ms=timeframe_ms,
            ),
            "blocked_sell": (
                _summarize_reviews(
                    blocked_sell_reviews,
                    contract_market=self.settings.contract_market,
                    reentry_window_bars=horizon_bars,
                    timeframe_ms=timeframe_ms,
                )
                | {"by_reason": _blocked_reason_counts(blocked_sell_reviews)}
            ),
            "by_symbol": by_symbol,
            "by_action": by_action,
            "by_confidence": by_confidence,
            "by_context": by_context,
            "by_lifecycle": by_lifecycle,
            "by_exit_source": by_exit_source,
            "by_blocked_group": by_blocked_group,
            "by_candidate_reason": (
                {
                    reason: summary
                    for reason, summary in by_candidate_reason.items()
                }
                | {"counts": _candidate_reason_counts(reviewed)}
            ),
            "by_hold_path": by_hold_path,
            "by_primary_risk_reason": by_primary_risk_reason,
            "by_entry_archetype": by_entry_archetype,
            "by_entry_thesis": by_entry_thesis,
            "by_setup_phase": by_setup_phase,
            "by_higher_timeframe_phase": by_higher_timeframe_phase,
            "by_expected_edge_bucket": by_expected_edge_bucket,
            "by_volatility_bucket": by_volatility_bucket,
            "decision_control": _decision_control_metrics(reviewed),
            "cycle_summary": cycle_summary,
        }
        return {
            "exchange_id": self.settings.exchange_id,
            "timeframe": self.settings.timeframe,
            "horizon_bars": horizon_bars,
            "threshold_pct": threshold_pct,
            "count": len(reviews),
            "aggregate": aggregate,
            "reviews": reviews,
        }

    def signal_review(
        self,
        limit: int = 20,
        horizon_bars: int = 3,
        threshold_pct: float = 0.003,
        *,
        replay_current_risk: bool = False,
        symbols_filter: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        candidates = (
            self._replayed_candidates_with_current_risk(limit=limit)
            if replay_current_risk
            else self._signal_review_candidates(limit=limit)
        )
        candidates = self._filter_candidates_by_symbols(candidates, symbols_filter)
        symbol_candles = self._symbol_candles_for_candidates(candidates)
        report = self._signal_review_from_candidates(
            candidates=candidates,
            symbol_candles=symbol_candles,
            horizon_bars=horizon_bars,
            threshold_pct=threshold_pct,
        )
        report["replay_current_risk"] = replay_current_risk
        report["symbols_filter"] = list(symbols_filter or [])
        return report

    def signal_review_study(
        self,
        *,
        limit: int = 160,
        horizons: list[int] | tuple[int, ...] = (3, 6, 12, 24),
        threshold_pct: float = 0.003,
        replay_current_risk: bool = False,
        symbols_filter: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        horizon_values = sorted({max(int(value), 0) for value in horizons})
        candidates = (
            self._replayed_candidates_with_current_risk(limit=limit)
            if replay_current_risk
            else self._signal_review_candidates(limit=limit)
        )
        candidates = self._filter_candidates_by_symbols(candidates, symbols_filter)
        symbol_candles = self._symbol_candles_for_candidates(candidates)
        reports: dict[str, dict[str, Any]] = {}
        comparison: list[dict[str, Any]] = []
        baseline_row: dict[str, Any] | None = None
        for horizon_bars in horizon_values:
            report = self._signal_review_from_candidates(
                candidates=candidates,
                symbol_candles=symbol_candles,
                horizon_bars=horizon_bars,
                threshold_pct=threshold_pct,
            )
            report["replay_current_risk"] = replay_current_risk
            report["symbols_filter"] = list(symbols_filter or [])
            aggregate = report.get("aggregate") or {}
            actionable = aggregate.get("actionable") or {}
            by_lifecycle = aggregate.get("by_lifecycle") or {}
            fresh_entry = by_lifecycle.get("fresh_entry") or {}
            by_expected_edge_bucket = aggregate.get("by_expected_edge_bucket") or {}
            by_volatility_bucket = aggregate.get("by_volatility_bucket") or {}
            row = {
                "horizon_bars": horizon_bars,
                "reviewed": aggregate.get("reviewed", 0),
                "actionable_avg_net_edge_pct": actionable.get("avg_net_edge_pct"),
                "fresh_entry_avg_net_edge_pct": fresh_entry.get("avg_net_edge_pct"),
                "actionable_sign": _signed_bucket_direction(_float_or_none(actionable.get("avg_net_edge_pct"))),
                "fresh_entry_sign": _signed_bucket_direction(_float_or_none(fresh_entry.get("avg_net_edge_pct"))),
                "edge_monotonicity": _bucket_monotonicity(
                    by_expected_edge_bucket,
                    metric_key="avg_realized_post_cost_pct",
                ),
                "high_vol_bias": _high_vol_bias_label(by_volatility_bucket),
            }
            if baseline_row is None:
                row["direction_consistency"] = "baseline"
                baseline_row = row
            else:
                row["direction_consistency"] = _comparison_consistency(row, baseline_row)
            comparison.append(row)
            reports[str(horizon_bars)] = {
                "reviewed": aggregate.get("reviewed", 0),
                "overall": aggregate.get("overall"),
                "hold": aggregate.get("hold"),
                "actionable": actionable,
                "decision_control": aggregate.get("decision_control"),
                "by_lifecycle": by_lifecycle,
                "by_hold_path": aggregate.get("by_hold_path"),
                "by_primary_risk_reason": aggregate.get("by_primary_risk_reason"),
                "by_expected_edge_bucket": by_expected_edge_bucket,
                "by_volatility_bucket": by_volatility_bucket,
            }
        return {
            "exchange_id": self.settings.exchange_id,
            "timeframe": self.settings.timeframe,
            "limit": limit,
            "threshold_pct": threshold_pct,
            "replay_current_risk": replay_current_risk,
            "symbols_filter": list(symbols_filter or []),
            "horizons": horizon_values,
            "comparison": comparison,
            "by_horizon": reports,
        }

    def execution_cost_audit(self, *, limit: int = 100, mode: str | None = None) -> dict[str, Any]:
        rows = self.journal.get_execution_audit_rows(limit=limit, mode=mode)
        analyzed: list[dict[str, Any]] = []
        skipped = {
            "non_market_or_missing_order": 0,
            "missing_snapshot_price": 0,
            "missing_fill_price": 0,
            "missing_fill_quantity": 0,
            "missing_fee_info": 0,
        }

        for row in rows:
            raw_json = row.get("raw_json") or {}
            if not isinstance(raw_json, dict):
                skipped["non_market_or_missing_order"] += 1
                continue
            order_payload = None
            if isinstance(raw_json.get("entry_order"), dict):
                order_payload = raw_json["entry_order"]
            elif isinstance(raw_json.get("close_order"), dict):
                order_payload = raw_json["close_order"]
            elif str(raw_json.get("type") or "").lower() == "market":
                order_payload = raw_json
            if not isinstance(order_payload, dict):
                skipped["non_market_or_missing_order"] += 1
                continue

            snapshot = row.get("snapshot_json") or {}
            symbol = str(row.get("symbol") or "")
            symbol_entry = next((item for item in (snapshot.get("symbols") or []) if str(item.get("symbol")) == symbol), None)
            reference_price = None
            if isinstance(symbol_entry, dict):
                reference_price = _float_or_none(symbol_entry.get("last_price"))
                if reference_price is None:
                    recent_candles = symbol_entry.get("recent_candles") or []
                    if recent_candles:
                        reference_price = _float_or_none((recent_candles[-1] or {}).get("close"))
            if reference_price is None or reference_price <= 0.0:
                skipped["missing_snapshot_price"] += 1
                continue

            fill_price, filled_quantity = _extract_fill_from_order(order_payload)
            if fill_price is None or fill_price <= 0.0:
                fill_price = _float_or_none(raw_json.get("entry_price"))
            if fill_price is None or fill_price <= 0.0:
                skipped["missing_fill_price"] += 1
                continue
            if filled_quantity is None or filled_quantity <= 0.0:
                filled_quantity = _float_or_none(row.get("quantity"))
            if filled_quantity is None or filled_quantity <= 0.0:
                skipped["missing_fill_quantity"] += 1
                continue

            fee_cost_quote, fee_rate = _extract_fee_metrics(
                order_payload,
                fill_price=fill_price,
                filled_quantity=filled_quantity,
            )
            if fee_cost_quote is None and fee_rate is None:
                skipped["missing_fee_info"] += 1

            side = str(order_payload.get("side") or row.get("side") or "").lower()
            raw_slippage_pct = ((fill_price / reference_price) - 1.0) * 100.0
            worse_slippage_pct = raw_slippage_pct if side == "buy" else -raw_slippage_pct
            verdict = row.get("verdict_json") or {}
            analyzed.append(
                {
                    "run_id": int(row.get("run_id") or 0),
                    "created_at": row.get("created_at"),
                    "mode": row.get("mode"),
                    "symbol": symbol,
                    "action": str(row.get("action") or ""),
                    "side": side,
                    "status": str(row.get("status") or ""),
                    "reference_price": reference_price,
                    "fill_price": fill_price,
                    "filled_quantity": filled_quantity,
                    "worse_slippage_pct": worse_slippage_pct,
                    "abs_slippage_pct": abs(worse_slippage_pct),
                    "fee_cost_quote": fee_cost_quote,
                    "fee_rate_pct": None if fee_rate is None else fee_rate * 100.0,
                    "final_size_pct": _float_or_none(verdict.get("final_size_pct")),
                    "stop_loss_pct": _float_or_none(verdict.get("stop_loss_pct")),
                }
            )

        def summarize_execution(items: list[dict[str, Any]]) -> dict[str, Any]:
            fee_rate_values = [float(value) for value in _numeric_values(items, "fee_rate_pct")]
            slippage_values = [float(value) for value in _numeric_values(items, "worse_slippage_pct")]
            abs_slippage_values = [float(value) for value in _numeric_values(items, "abs_slippage_pct")]
            return {
                "analyzed": len(items),
                "avg_fee_rate_pct": _mean_or_none(fee_rate_values),
                "avg_worse_slippage_pct": _mean_or_none(slippage_values),
                "avg_abs_slippage_pct": _mean_or_none(abs_slippage_values),
                "p50_abs_slippage_pct": _percentile(abs_slippage_values, 0.50),
                "p90_abs_slippage_pct": _percentile(abs_slippage_values, 0.90),
                "max_abs_slippage_pct": max(abs_slippage_values) if abs_slippage_values else None,
            }

        by_symbol = {
            symbol: summarize_execution([item for item in analyzed if item["symbol"] == symbol])
            for symbol in sorted({item["symbol"] for item in analyzed})
        }
        by_action = {
            action: summarize_execution([item for item in analyzed if item["action"] == action])
            for action in sorted({item["action"] for item in analyzed})
        }
        latest_snapshot = self.journal.get_latest_snapshot(mode=mode)
        latest_account = (latest_snapshot or {}).get("account") or {}
        equity_quote_basis = _float_or_none(latest_account.get("equity_quote")) or self.settings.paper_starting_quote
        current_open_positions = (latest_account.get("open_positions") or []) if isinstance(latest_account, dict) else []
        current_long_notional_quote, current_short_notional_quote = _snapshot_directional_notional(current_open_positions)
        open_entries = [item for item in analyzed if item["action"] in {"buy", "sell"}]
        recent_median_size_pct = _median_or_none(_numeric_values(open_entries, "final_size_pct"))
        recent_median_stop_loss_pct = _median_or_none(_numeric_values(open_entries, "stop_loss_pct"))
        stop_loss_basis_pct = recent_median_stop_loss_pct
        stop_loss_basis_source = "recent_median_open_verdict"
        if stop_loss_basis_pct is None or stop_loss_basis_pct <= 0.0:
            stop_loss_basis_pct = self.settings.min_effective_stop_loss_pct
            stop_loss_basis_source = "settings.min_effective_stop_loss_pct"
        configured_single_entry_notional_quote = equity_quote_basis * self.settings.max_entry_size_pct * float(self.settings.contract_leverage)
        configured_same_direction_notional_quote = configured_single_entry_notional_quote * self.settings.max_open_positions
        single_stop_drawdown_pct_of_equity = self.settings.max_entry_size_pct * float(self.settings.contract_leverage) * stop_loss_basis_pct * 100.0
        double_stop_drawdown_pct_of_equity = single_stop_drawdown_pct_of_equity * 2.0
        triple_stop_drawdown_pct_of_equity = single_stop_drawdown_pct_of_equity * 3.0
        daily_loss_limit_pct_of_equity = self.settings.daily_loss_limit_pct * 100.0
        stops_to_daily_loss_limit = None
        if single_stop_drawdown_pct_of_equity > 0.0:
            stops_to_daily_loss_limit = daily_loss_limit_pct_of_equity / single_stop_drawdown_pct_of_equity

        return {
            "mode": mode or self.settings.mode,
            "limit": limit,
            "orders_considered": len(rows),
            "market_orders_analyzed": len(analyzed),
            "estimated_fee_pct": self.settings.estimated_fee_pct * 100.0,
            "estimated_slippage_pct": self.settings.estimated_slippage_pct * 100.0,
            "configured_round_trip_cost_pct": (self.settings.estimated_fee_pct + self.settings.estimated_slippage_pct) * 2.0 * 100.0,
            "overall": summarize_execution(analyzed),
            "by_symbol": by_symbol,
            "by_action": by_action,
            "skipped": skipped,
            "samples": analyzed[: min(len(analyzed), 10)],
            "exposure_geometry": {
                "equity_quote_basis": equity_quote_basis,
                "configured_single_entry_notional_quote": configured_single_entry_notional_quote,
                "configured_same_direction_notional_quote": configured_same_direction_notional_quote,
                "configured_same_direction_multiple_of_equity": None if equity_quote_basis <= 0.0 else configured_same_direction_notional_quote / equity_quote_basis,
                "current_long_notional_quote": current_long_notional_quote,
                "current_short_notional_quote": current_short_notional_quote,
                "current_max_same_direction_notional_quote": max(current_long_notional_quote, current_short_notional_quote),
                "max_open_positions": self.settings.max_open_positions,
                "max_entry_size_pct": self.settings.max_entry_size_pct,
                "contract_leverage": float(self.settings.contract_leverage),
                "daily_loss_limit_pct_of_equity": daily_loss_limit_pct_of_equity,
                "recent_median_open_size_pct": recent_median_size_pct,
                "stop_loss_basis_pct": stop_loss_basis_pct * 100.0,
                "stop_loss_basis_source": stop_loss_basis_source,
                "single_stop_drawdown_pct_of_equity": single_stop_drawdown_pct_of_equity,
                "double_stop_drawdown_pct_of_equity": double_stop_drawdown_pct_of_equity,
                "triple_stop_drawdown_pct_of_equity": triple_stop_drawdown_pct_of_equity,
                "stops_to_daily_loss_limit": stops_to_daily_loss_limit,
            },
        }

    def paper_replay(self, include_noop: bool = False) -> dict[str, Any]:
        orders = self.journal.get_order_history(mode="paper")
        cash = self.settings.paper_starting_quote
        positions: dict[str, dict[str, float]] = {}
        realized_pnl = 0.0
        closed_trades = 0
        wins = 0
        losses = 0
        timeline: list[dict[str, Any]] = []

        for order in orders:
            event = {
                "run_id": order["run_id"],
                "created_at": order["created_at"],
                "status": order["status"],
                "symbol": order["symbol"],
                "action": order["action"],
            }
            if order["status"] == "paper_filled" and order["action"] == "buy":
                qty = float(order["quantity"] or 0.0)
                cost = float(order["notional_quote"] or 0.0)
                current = positions.get(order["symbol"])
                if current:
                    old_qty = current["quantity"]
                    old_cost = current["avg_entry"] * old_qty
                    new_qty = old_qty + qty
                    avg_entry = (old_cost + cost) / new_qty if new_qty else current["avg_entry"]
                else:
                    new_qty = qty
                    avg_entry = cost / qty if qty else 0.0
                positions[order["symbol"]] = {"quantity": new_qty, "avg_entry": avg_entry}
                cash -= cost
                event["cash_after"] = cash
                event["positions_after"] = positions.copy()
                timeline.append(event)
            elif order["status"] == "paper_closed":
                proceeds = float(order["notional_quote"] or 0.0)
                pnl = float(order["pnl_quote"] or 0.0)
                cash += proceeds
                realized_pnl += pnl
                closed_trades += 1
                wins += 1 if pnl > 0 else 0
                losses += 1 if pnl < 0 else 0
                positions.pop(order["symbol"], None)
                event["cash_after"] = cash
                event["pnl_quote"] = pnl
                event["positions_after"] = positions.copy()
                timeline.append(event)
            elif include_noop:
                event["cash_after"] = cash
                event["positions_after"] = positions.copy()
                timeline.append(event)

        latest_prices = self.journal.get_latest_snapshot_prices()
        unrealized_value = 0.0
        open_positions: dict[str, Any] = {}
        for symbol, position in positions.items():
            mark_price = latest_prices.get(symbol, position["avg_entry"])
            market_value = position["quantity"] * mark_price
            unrealized_value += market_value
            open_positions[symbol] = {
                "quantity": position["quantity"],
                "avg_entry": position["avg_entry"],
                "mark_price": mark_price,
                "market_value": market_value,
            }

        total_equity = cash + unrealized_value
        return {
            "mode": "paper",
            "exchange_id": self.settings.exchange_id,
            "starting_quote": self.settings.paper_starting_quote,
            "cash": cash,
            "unrealized_value": unrealized_value,
            "total_equity": total_equity,
            "realized_pnl": realized_pnl,
            "closed_trades": closed_trades,
            "wins": wins,
            "losses": losses,
            "open_positions": open_positions,
            "equity_curve": self.journal.get_equity_series(mode="paper", limit=200),
            "timeline": timeline,
        }
