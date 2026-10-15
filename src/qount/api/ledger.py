"""Shared, strict parser for the personal assistant's simulated position ledger."""

from __future__ import annotations

import math
from datetime import date
from typing import Any


def _day(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) == 8 and raw.isdigit():
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return date.fromisoformat(raw[:10]).isoformat()


def parse_personal_assistant_position_ledger(
    events: Any, *, as_of: str
) -> tuple[float, str | None]:
    """Resolve shares and entry date through BUY/SELL and split corporate actions.

    Raises ValueError when the event stream is incomplete or internally inconsistent.
    """
    if not isinstance(events, list):
        raise ValueError("ledger_not_a_list")
    cutoff = _day(as_of)
    ordered = sorted(
        (( _day(row.get("date")), row) for row in events if isinstance(row, dict)),
        key=lambda item: item[0],
    )
    shares = 0.0
    entry_date: str | None = None
    seen_model_event = False
    for event_date, row in ordered:
        if event_date > cutoff:
            continue
        action = str(row.get("action") or "").upper()
        if action == "BUY":
            quantity = _positive(row.get("shares"), "buy_quantity_invalid")
            if shares <= 1e-9:
                entry_date = event_date
            shares += quantity
            seen_model_event = True
        elif action == "SELL":
            quantity = _positive(row.get("shares"), "sell_quantity_invalid")
            if quantity > shares + max(1e-7, shares * 1e-8):
                raise ValueError("ledger_sell_exceeds_position")
            shares -= quantity
            if shares <= 1e-9:
                shares = 0.0
                entry_date = None
            seen_model_event = True
        elif action in {"CORPORATE_ACTION_SPLIT", "SPLIT"}:
            before = _positive(row.get("shares_before"), "split_shares_before_missing")
            after = _positive(row.get("shares_after"), "split_shares_after_missing")
            if not seen_model_event or abs(shares - before) > max(1e-6, before * 1e-8):
                raise ValueError("split_does_not_match_ledger_position")
            ratio = row.get("split_ratio")
            if ratio is not None and abs(after / before - float(ratio)) > max(1e-8, float(ratio) * 1e-8):
                raise ValueError("split_ratio_mismatch")
            shares = after
        else:
            raise ValueError("ledger_event_action_unknown")
    if events and not seen_model_event:
        raise ValueError("ledger_has_no_target_model_events")
    return shares, entry_date


def _positive(value: Any, error: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(error)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(error)
    return number
