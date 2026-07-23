"""Event-time capture helpers for partial real execution attribution."""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, Mapping, Sequence

from qount.certification.attribution import UNAVAILABLE
from qount.certification.attribution import ExecutionAttributionReport
from qount.contracts.hashing import canonical_hash


_EVIDENCE_FIELDS = (
    "decision_to_submit_ms",
    "submit_to_ack_ms",
    "ack_to_fill_ms",
    "planned_vs_filled_qty",
    "partial_fill_count",
    "cancel_replace_count",
    "arrival_mid",
    "bid_ask_spread",
    "fill_vwap",
    "adverse_slippage",
    "maker_or_taker",
    "fee",
    "funding",
    "unfilled_exposure_time",
    "protection_order_latency",
    "stop_gap",
)
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|secret|password|passphrase|private[_-]?key|"
    r"access[_-]?token|bearer[_-]?token|listen[_-]?key|authorization|credential|signature)$",
    re.IGNORECASE,
)


def sanitize_exchange_evidence(value: Any) -> Any:
    """Return a deterministic JSON-safe copy with credential-like fields redacted."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            result[key] = (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(key)
                else sanitize_exchange_evidence(item)
            )
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_exchange_evidence(item) for item in value]
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc).isoformat()
        return value.astimezone(dt.timezone.utc).isoformat()
    if isinstance(value, bytes):
        return {
            "bytes_length": len(value),
            "bytes_hash": canonical_hash({"bytes_hex": value.hex()}),
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def exchange_evidence_envelope(
    *,
    submit_response: Mapping[str, Any],
    confirmed_order: Mapping[str, Any] | None = None,
    trades: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Bind sanitized raw exchange responses without persisting credentials."""

    core = {
        "submit_response": sanitize_exchange_evidence(submit_response),
        "confirmed_order": sanitize_exchange_evidence(confirmed_order),
        "trades": sanitize_exchange_evidence(list(trades)),
        "sensitive_fields_redacted": True,
    }
    return core | {"source_hash": canonical_hash(core)}


def capture_arrival_quote(
    exchange: Any,
    *,
    symbol: str,
    observed_at: str,
) -> dict[str, Any]:
    """Capture a top-of-book arrival quote without making it an execution gate."""

    fetch_order_book = getattr(exchange, "fetch_order_book", None)
    if not callable(fetch_order_book):
        core = {
            "status": UNAVAILABLE,
            "missing_reason": "order_book_query_unavailable",
            "observed_at": observed_at,
            "symbol": symbol,
        }
        return core | {"source_hash": canonical_hash(core)}
    try:
        response = fetch_order_book(symbol, 5)
        if not isinstance(response, Mapping):
            raise ValueError("order_book_response_invalid")
        bids = response.get("bids") or ()
        asks = response.get("asks") or ()
        bid = float(bids[0][0])
        ask = float(asks[0][0])
        if (
            not math.isfinite(bid)
            or not math.isfinite(ask)
            or bid <= 0.0
            or ask <= bid
        ):
            raise ValueError("order_book_top_invalid")
        bounded_response = dict(response)
        bounded_response["bids"] = list(bids[:5])
        bounded_response["asks"] = list(asks[:5])
        core = {
            "status": "available",
            "missing_reason": None,
            "observed_at": observed_at,
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2.0,
            "spread": ask - bid,
            "raw_order_book": sanitize_exchange_evidence(bounded_response),
        }
    except Exception as exc:
        core = {
            "status": UNAVAILABLE,
            "missing_reason": f"order_book_capture_failed:{type(exc).__name__}",
            "observed_at": observed_at,
            "symbol": symbol,
        }
    return core | {"source_hash": canonical_hash(core)}


def _timestamp(value: object) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def _milliseconds(start: object, end: object) -> float | None:
    start_time = _timestamp(start)
    end_time = _timestamp(end)
    if start_time is None or end_time is None or end_time < start_time:
        return None
    return (end_time - start_time).total_seconds() * 1_000.0


def _maker_or_taker(trades: Sequence[Mapping[str, Any]]) -> str:
    values: set[str] = set()
    for trade in trades:
        value = trade.get("takerOrMaker")
        info = trade.get("info")
        if value is None and isinstance(info, Mapping):
            value = info.get("takerOrMaker")
        if value is None:
            maker = trade.get("maker")
            if maker is None and isinstance(info, Mapping):
                maker = info.get("maker")
            if isinstance(maker, bool):
                value = "maker" if maker else "taker"
        if value in {"maker", "taker"}:
            values.add(str(value))
    return next(iter(values)) if len(values) == 1 else UNAVAILABLE


def build_event_time_attribution(
    *,
    run_id: str,
    decision_time: str,
    submitted_at: str,
    acknowledged_at: str,
    planned_quantity: float,
    side: str,
    arrival_quote: Mapping[str, Any],
    fills: Sequence[Mapping[str, Any]],
    raw_trades: Sequence[Mapping[str, Any]],
    raw_exchange_evidence: Mapping[str, Any],
    protection_acknowledged_at: str | None,
    stop_price: float | None,
) -> ExecutionAttributionReport:
    """Build only metrics evidenced during a natural Base execution."""

    normalized_fills = [dict(fill) for fill in fills]
    normalized_trades = [dict(trade) for trade in raw_trades]
    source_payload = {
        "run_id": run_id,
        "decision_time": decision_time,
        "submitted_at": submitted_at,
        "acknowledged_at": acknowledged_at,
        "planned_quantity": planned_quantity,
        "side": side,
        "arrival_quote": dict(arrival_quote),
        "fills": normalized_fills,
        "raw_exchange_evidence": dict(raw_exchange_evidence),
        "protection_acknowledged_at": protection_acknowledged_at,
        "stop_price": stop_price,
    }
    source_hash = canonical_hash(source_payload)
    values: dict[str, Any] = {}
    reasons = {field: "not_captured_at_event_time" for field in _EVIDENCE_FIELDS}

    def available(field: str, value: Any) -> None:
        values[field] = value
        reasons.pop(field, None)

    decision_to_submit = _milliseconds(decision_time, submitted_at)
    submit_to_ack = _milliseconds(submitted_at, acknowledged_at)
    if decision_to_submit is not None:
        available("decision_to_submit_ms", decision_to_submit)
    if submit_to_ack is not None:
        available("submit_to_ack_ms", submit_to_ack)

    fill_times = [_timestamp(fill.get("occurred_at")) for fill in normalized_fills]
    valid_fill_times = [value for value in fill_times if value is not None]
    last_fill_time = max(valid_fill_times) if valid_fill_times else None
    if last_fill_time is not None:
        last_fill_at = last_fill_time.isoformat()
        ack_to_fill = _milliseconds(acknowledged_at, last_fill_at)
        unfilled_exposure = _milliseconds(submitted_at, last_fill_at)
        if ack_to_fill is not None:
            available("ack_to_fill_ms", ack_to_fill)
        if unfilled_exposure is not None:
            available("unfilled_exposure_time", unfilled_exposure)

    quantities = [float(fill["quantity"]) for fill in normalized_fills]
    prices = [float(fill["price"]) for fill in normalized_fills]
    total_quantity = sum(quantities)
    if planned_quantity > 0.0 and total_quantity > 0.0:
        available("planned_vs_filled_qty", total_quantity / planned_quantity)
        fill_vwap = sum(
            quantity * price for quantity, price in zip(quantities, prices, strict=True)
        ) / total_quantity
        available("fill_vwap", fill_vwap)
        available("partial_fill_count", max(0, len(normalized_fills) - 1))
        available("cancel_replace_count", 0)
        fee = sum(float(fill["fee"]) for fill in normalized_fills)
        available("fee", fee)
        if arrival_quote.get("status") == "available":
            mid = float(arrival_quote["mid"])
            spread = float(arrival_quote["spread"])
            available("arrival_mid", mid)
            available("bid_ask_spread", spread)
            adverse_bps = (
                (fill_vwap / mid - 1.0) * 10_000.0
                if side == "buy"
                else (1.0 - fill_vwap / mid) * 10_000.0
            )
            available("adverse_slippage", adverse_bps)
        else:
            quote_reason = str(
                arrival_quote.get("missing_reason")
                or "not_captured_at_event_time"
            )
            reasons["arrival_mid"] = quote_reason
            reasons["bid_ask_spread"] = quote_reason
            reasons["adverse_slippage"] = quote_reason
        if protection_acknowledged_at is not None and stop_price is not None:
            protection_latency = _milliseconds(
                last_fill_time.isoformat() if last_fill_time else None,
                protection_acknowledged_at,
            )
            if protection_latency is not None:
                available("protection_order_latency", protection_latency)
            available(
                "stop_gap",
                abs(fill_vwap - float(stop_price)) / fill_vwap * 10_000.0,
            )
        else:
            reasons["protection_order_latency"] = "not_applicable_no_protective_order"
            reasons["stop_gap"] = "not_applicable_no_protective_order"

    maker_or_taker = _maker_or_taker(normalized_trades)
    if maker_or_taker != UNAVAILABLE:
        reasons.pop("maker_or_taker", None)
    reasons["funding"] = "not_attributable_to_single_order"
    evidence = {
        field: {
            "status": "available" if field not in reasons else UNAVAILABLE,
            "missing_reason": reasons.get(field),
            "source_hash": source_hash,
        }
        for field in _EVIDENCE_FIELDS
    }
    return ExecutionAttributionReport.create_partial_real_fill(
        run_id=run_id,
        values=values,
        maker_or_taker=maker_or_taker,
        field_evidence=evidence,
        attribution_source_hash=source_hash,
    )
