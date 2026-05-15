from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .models import AIDecision, ValidatedDecision


ALLOWED_ACTIONS = {"buy", "sell", "hold", "close"}


def _hold_fallback(symbol: str, now: datetime, prompt_version: str, reason: str) -> AIDecision:
    return AIDecision(
        timestamp=now.isoformat(),
        symbol=symbol,
        action="hold",
        size_pct=0.0,
        take_profit_pct=0.02,
        stop_loss_pct=0.01,
        ttl_minutes=60,
        confidence=0.0,
        reason=reason,
        prompt_version=prompt_version,
    )


def extract_json_payload(raw_text: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_text, dict):
        return raw_text
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw_text[start : end + 1])
        raise


def _distance_to_range(value: float, minimum: float, maximum: float) -> float:
    if value < minimum:
        return minimum - value
    if value > maximum:
        return value - maximum
    return 0.0


def _normalize_ratio_like_value(name: str, raw: Any) -> float:
    if isinstance(raw, str):
        text = raw.strip()
        if text.endswith("%"):
            return float(text[:-1]) / 100.0
        value = float(text)
    else:
        value = float(raw)

    if value < 0:
        return value
    if value > 1.0:
        return value / 100.0
    if name == "size_pct":
        return value

    target_max = 0.05 if name == "take_profit_pct" else 0.03
    if value > target_max:
        scaled = value / 100.0
        if _distance_to_range(scaled, 0.0, target_max) < _distance_to_range(value, 0.0, target_max):
            return scaled
    return value


def validate_decision(
    raw_text: str | dict[str, Any],
    allowed_symbols: tuple[str, ...],
    now: datetime,
    max_size_pct: float = 0.35,
    contract_market: bool = False,
) -> ValidatedDecision:
    prompt_version = "v1"
    try:
        payload = extract_json_payload(raw_text)
    except Exception as exc:
        fallback = _hold_fallback(allowed_symbols[0], now, prompt_version, "invalid json from ai")
        return ValidatedDecision(decision=fallback, valid=False, errors=[f"json_parse_error: {exc}"], raw_payload=None)

    errors: list[str] = []
    symbol = str(payload.get("symbol", allowed_symbols[0]))
    action = str(payload.get("action", "hold")).lower()
    prompt_version = str(payload.get("prompt_version", "v1"))

    if symbol not in allowed_symbols:
        errors.append(f"symbol_not_allowed:{symbol}")
        symbol = allowed_symbols[0]
    if action not in ALLOWED_ACTIONS:
        errors.append(f"action_not_allowed:{action}")
        action = "hold"

    def _float_field(name: str, default: float) -> float:
        raw = payload.get(name, default)
        try:
            if name in {"size_pct", "take_profit_pct", "stop_loss_pct"}:
                return _normalize_ratio_like_value(name, raw)
            return float(raw)
        except (TypeError, ValueError):
            errors.append(f"bad_float:{name}")
            return default

    def _int_field(name: str, default: int) -> int:
        raw = payload.get(name, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            errors.append(f"bad_int:{name}")
            return default

    decision = AIDecision(
        timestamp=str(payload.get("timestamp", now.isoformat())),
        symbol=symbol,
        action=action,
        size_pct=_float_field("size_pct", 0.0),
        take_profit_pct=_float_field("take_profit_pct", 0.02),
        stop_loss_pct=_float_field("stop_loss_pct", 0.01),
        ttl_minutes=_int_field("ttl_minutes", 60),
        confidence=_float_field("confidence", 0.0),
        reason=str(payload.get("reason", "no reason provided")),
        prompt_version=prompt_version,
    )

    if decision.size_pct < 0.0:
        errors.append("size_pct_negative")
    if not 0.0 <= decision.confidence <= 1.0:
        errors.append("confidence_out_of_range")
    if action == "buy" or (contract_market and action == "sell"):
        if decision.take_profit_pct < 0.0:
            errors.append("take_profit_pct_negative")
        if decision.stop_loss_pct < 0.0:
            errors.append("stop_loss_pct_negative")
    else:
        if decision.take_profit_pct < 0.0:
            errors.append("take_profit_pct_negative")
        if decision.stop_loss_pct < 0.0:
            errors.append("stop_loss_pct_negative")
    if not 0 <= decision.ttl_minutes <= 180:
        errors.append("ttl_minutes_out_of_range")

    if errors:
        fallback = _hold_fallback(symbol, now, prompt_version, "validation fallback to hold")
        return ValidatedDecision(decision=fallback, valid=False, errors=errors, raw_payload=payload)

    return ValidatedDecision(decision=decision, valid=True, errors=[], raw_payload=payload)
