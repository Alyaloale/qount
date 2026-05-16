from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from .exchange_utils import build_exchange
from .journal import Journal
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


def _mean_or_none(values: list[float]) -> float | None:
    return mean(values) if values else None


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
        "avg_future_return_pct": _mean_or_none(_numeric_values(items, "market_future_return_pct")),
        "avg_gross_future_return_pct": _mean_or_none(_numeric_values(items, "gross_future_return_pct")),
        "avg_estimated_cost_pct": _mean_or_none(_numeric_values(items, "estimated_cost_pct")),
        "avg_net_edge_pct": _mean_or_none(_numeric_values(items, "net_edge_pct")),
        "avg_opportunity_edge_pct": _mean_or_none(_numeric_values(items, "opportunity_edge_pct")),
        "avg_planned_risk_pct_of_equity": _mean_or_none(_numeric_values(items, "planned_risk_pct_of_equity")),
        "avg_future_R": _mean_or_none(_numeric_values(items, "future_R")),
        "avg_mfe_pct": _mean_or_none(_numeric_values(items, "mfe_pct")),
        "avg_mae_pct": _mean_or_none(_numeric_values(items, "mae_pct")),
        "avg_giveback_pct": _mean_or_none(_numeric_values(items, "giveback_pct")),
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
    if not isinstance(candidate_summary, dict):
        return [], "unknown", None
    symbol_summaries = candidate_summary.get("symbols") or []
    if not isinstance(symbol_summaries, list):
        return [], "unknown", None
    match = next((item for item in symbol_summaries if str(item.get("symbol")) == symbol), None)
    if not isinstance(match, dict):
        return [], "unknown", None
    reasons = [str(reason) for reason in (match.get("reasons") or [])]
    primary_reason = reasons[0] if reasons else "unknown"
    manage_only = match.get("manage_only")
    return reasons, primary_reason, None if manage_only is None else bool(manage_only)


class ReviewService:
    def __init__(self, settings: Settings, journal: Journal) -> None:
        self.settings = settings
        self.journal = journal

    def _exchange(self):
        return build_exchange(self.settings, private=False)

    def signal_review(self, limit: int = 20, horizon_bars: int = 3, threshold_pct: float = 0.003) -> dict[str, Any]:
        candidates = self.journal.get_signal_review_candidates(limit=limit)
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
            final_size_pct = float(verdict.get("final_size_pct") or 0.0)
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
                    "final_size_pct": final_size_pct,
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
                    "close_cost_pct": close_cost_pct,
                    "risk_reasons": risk_reasons,
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
