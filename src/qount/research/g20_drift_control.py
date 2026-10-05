"""Offline G20 drift control in adjusted-price units, with no order or I/O path.

The 20% cap is an execution target, not a continuous exposure guarantee. Close
observations schedule reduce-only intents; prices available at the eventual
open determine whether a sale is still needed. Monthly signals take priority.
"""

from __future__ import annotations

import math
from typing import Mapping

from qount.research.dual_engine_optimization import EquityPanel, OptimizationStudyError, _grow
from qount.research_data.replay_fees import trade_to_target


def _risk(weights: Mapping[str, float]) -> float:
    return sum(weight for symbol, weight in weights.items() if symbol != "BIL")


def _monthly_target(signal: Mapping, *, risk_weight: float, benchmark: bool) -> dict[str, float]:
    if benchmark:
        return {"SPY": 0.6, "BIL": 0.4}
    original = signal["target"]
    active = [symbol for symbol, weight in original.items() if symbol != "BIL" and weight > 0.0]
    if len(active) > 1:
        raise OptimizationStudyError("g20_requires_single_monthly_risk_asset")
    if not active or risk_weight == 0.0:
        return {"BIL": 1.0}
    selected = active[0]
    if signal.get("selected", selected) != selected:
        raise OptimizationStudyError("g20_monthly_winner_mismatch")
    return {"BIL": 1.0 - risk_weight, selected: risk_weight}


def replay_equity_control(
    panel: EquityPanel,
    signals: Mapping[int, Mapping],
    *,
    start: str,
    cost_bps: float,
    delay: int,
    reduce_only: bool = False,
    risk_weight: float = 0.2,
    benchmark: bool = False,
    exact_fees: bool = True,
) -> dict:
    """Replay fixed monthly winners, optionally reducing upward weight drift.

    ``risk_weight`` sets the monthly sleeve and the close-observed reduction
    threshold. Monthly fills cancel all prior reduction intents, including
    a same-open intent. A pending reduction can never buy risk or act on a
    new monthly sleeve. ``exact_fees=False`` retains legacy fee arithmetic
    for an accounting comparison; it is not the self-financing model.

    All marks are supplied adjusted total-return units. This function does
    not model actual dividend cash payment dates or brokerage split shares.
    """
    if (delay not in (1, 2) or not math.isfinite(cost_bps) or not 0.0 <= cost_bps < 10_000.0
            or not math.isfinite(risk_weight) or not 0.0 <= risk_weight <= 1.0
            or (benchmark and reduce_only)):
        raise OptimizationStudyError("equity_control_settings_invalid")
    first = next((i for i, day in enumerate(panel.dates) if day >= start), None)
    if first is None or first == 0:
        raise OptimizationStudyError("equity_start_invalid")
    schedule = {}
    for index, signal in signals.items():
        if not isinstance(index, int) or not 0 <= index < len(panel.dates):
            raise OptimizationStudyError("equity_signal_index_invalid")
        if signal["signal_date"] != panel.dates[index]:
            raise OptimizationStudyError("equity_signal_date_mismatch")
        target = _monthly_target(signal, risk_weight=risk_weight, benchmark=benchmark)
        if any(symbol not in panel.total_closes or symbol not in panel.total_opens for symbol in target):
            raise OptimizationStudyError("equity_target_price_missing")
        schedule[index + delay] = {"signal_date": signal["signal_date"], "target": target}

    weights: dict[str, float] = {}
    pending: dict[int, dict] = {}
    generation = 0
    records, events = [], []
    for index in range(first, len(panel.dates)):
        day = panel.dates[index]
        previous_risk = _risk(weights)
        overnight, weights = _grow(weights, {
            symbol: panel.total_opens[symbol][index] / panel.total_closes[symbol][index - 1]
            for symbol in weights
        })
        pre_trade = dict(weights)
        pre_risk = _risk(weights)
        monthly = schedule.get(index)
        intent = pending.pop(index, None)
        target = None
        trade_kind = None
        reduce_status = None
        reduce_signal_date = None
        cancelled = 0
        if monthly is not None:
            # No close-generated reduction is allowed to survive a monthly fill,
            # even when the new monthly winner is the same asset.
            cancelled_intents = ([intent] if intent is not None else []) + list(pending.values())
            pending.clear()
            cancelled = len(cancelled_intents)
            for old_intent in cancelled_intents:
                events.append(old_intent | {"execution_date": day, "status": "monthly_cancelled"})
            reduce_status = "monthly_cancelled" if cancelled else None
            generation += 1
            target = monthly["target"]
            trade_kind = "monthly"
        elif intent is not None:
            reduce_signal_date = intent["signal_date"]
            held = [symbol for symbol, weight in weights.items() if symbol != "BIL" and weight > 0.0]
            if intent["generation"] != generation or held != [intent["symbol"]]:
                reduce_status = "skipped_stale"
            elif pre_risk <= risk_weight + 1e-12:
                reduce_status = "skipped_below_cap"
            else:
                target = {"BIL": 1.0 - risk_weight, intent["symbol"]: risk_weight}
                trade_kind = "reduce"
                reduce_status = "executed"
            events.append(intent | {"execution_date": day, "status": reduce_status})
        if target is None and index == first:
            target = {"BIL": 1.0}
            trade_kind = "initial"
        remaining, turnover, fee = 1.0, 0.0, 0.0
        if target is not None:
            remaining, turnover = trade_to_target(weights, target, cost_bps, exact=exact_fees)
            fee = 1.0 - remaining
            weights = dict(target)
        post_open = dict(weights)
        post_risk = _risk(weights)
        intraday, weights = _grow(weights, {
            symbol: panel.total_closes[symbol][index] / panel.total_opens[symbol][index]
            for symbol in weights
        })
        close_risk = _risk(weights)
        scheduled = None
        if reduce_only and close_risk > risk_weight + 1e-12:
            held = [symbol for symbol, weight in weights.items() if symbol != "BIL" and weight > 0.0]
            if len(held) != 1:
                raise OptimizationStudyError("g20_reduce_requires_single_held_asset")
            # The execution index is known now; the future execution date is
            # deliberately not read, preserving prefix records at the data end.
            scheduled = {"signal_date": day, "symbol": held[0],
                         "execution_index": index + delay, "generation": generation}
            pending[index + delay] = scheduled
        records.append({
            "date": day,
            "return": overnight * remaining * intraday - 1.0,
            "cash_return": panel.total_closes["BIL"][index] / panel.total_closes["BIL"][index - 1] - 1.0,
            "turnover": turnover,
            "cost_fraction": fee,
            "gross": sum(weights.values()),
            "signal_date": monthly["signal_date"] if monthly is not None else None,
            "weights": dict(weights),
            "trade_kind": trade_kind,
            "target_weights": dict(target) if target is not None else None,
            "pre_trade_weights": pre_trade,
            "post_open_weights": post_open,
            "risk_exposure_previous_close": previous_risk,
            "risk_exposure_pre_trade": pre_risk,
            "risk_exposure_post_open": post_risk,
            "risk_exposure_close": close_risk,
            "nav_after_fee_ratio": remaining,
            "reduce_signal_date": reduce_signal_date,
            "reduce_status": reduce_status,
            "reduce_cancelled_count": cancelled,
            "reduce_intent_scheduled": scheduled,
        })
    return {"records": records, "reduce_events": events,
            "pending_reductions": list(pending.values()),
            "fee_model": "exact_self_financing" if exact_fees else "legacy_approximation",
            "research_only": True, "orders_authorized": False}
