from __future__ import annotations

from typing import Literal


ConfidenceBucket = Literal["low", "medium", "high"]


def timeframe_to_ms(timeframe: str) -> int:
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    if unit == "m":
        return value * 60_000
    if unit == "h":
        return value * 3_600_000
    if unit == "d":
        return value * 86_400_000
    raise ValueError(f"unsupported timeframe: {timeframe}")


def is_open_action(action: str, contract_market: bool) -> bool:
    return action == "buy" or (contract_market and action == "sell")


def action_direction(action: str, *, contract_market: bool, position_side: str | None = None) -> int | None:
    if action == "buy":
        return 1
    if action == "sell":
        if contract_market:
            return -1
        return -1
    if action == "close":
        if position_side == "short":
            return 1
        return -1
    return None


def estimated_action_cost_pct(
    action: str,
    *,
    contract_market: bool,
    fee_pct: float,
    slippage_pct: float,
) -> float:
    if action == "hold":
        return 0.0
    per_leg_pct = max(fee_pct, 0.0) + max(slippage_pct, 0.0)
    if action == "close" or (not contract_market and action == "sell"):
        return per_leg_pct
    return per_leg_pct * 2.0


def confidence_bucket(confidence: float) -> ConfidenceBucket:
    if confidence < 0.34:
        return "low"
    if confidence < 0.67:
        return "medium"
    return "high"
