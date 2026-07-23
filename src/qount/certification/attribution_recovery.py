"""Deterministic, read-only recovery of partial execution attribution."""

from __future__ import annotations

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


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _trade_quantity(trade: Mapping[str, Any]) -> float | None:
    for key in ("amount", "qty", "executedQty"):
        value = _float(trade.get(key))
        if value is not None:
            return abs(value)
    info = trade.get("info")
    if isinstance(info, Mapping):
        return _trade_quantity(info)
    return None


def _trade_price(trade: Mapping[str, Any]) -> float | None:
    value = _float(trade.get("price"))
    if value is not None:
        return value
    info = trade.get("info")
    if isinstance(info, Mapping):
        return _trade_price(info)
    return None


def _trade_fee(trade: Mapping[str, Any]) -> float | None:
    fee = trade.get("fee")
    if isinstance(fee, Mapping):
        value = _float(fee.get("cost"))
        if value is not None:
            return abs(value)
    value = _float(trade.get("commission"))
    if value is not None:
        return abs(value)
    info = trade.get("info")
    if isinstance(info, Mapping):
        return _trade_fee(info)
    return None


def _maker_or_taker(trades: Sequence[Mapping[str, Any]]) -> str:
    values: set[str] = set()
    for trade in trades:
        value = trade.get("takerOrMaker")
        if value is None:
            maker = trade.get("maker")
            if isinstance(maker, bool):
                value = "maker" if maker else "taker"
        if value is None:
            info = trade.get("info")
            if isinstance(info, Mapping):
                maker = info.get("maker")
                if isinstance(maker, bool):
                    value = "maker" if maker else "taker"
        if value in ("maker", "taker"):
            values.add(str(value))
    return next(iter(values)) if len(values) == 1 else UNAVAILABLE


def build_recovered_attribution(
    *,
    run_id: str,
    trades: Sequence[Mapping[str, Any]],
    income: Sequence[Mapping[str, Any]] = (),
    planned_quantity: float | None = None,
    source_metadata: Mapping[str, Any] | None = None,
) -> ExecutionAttributionReport:
    """Build only the fields proven by archived trade and income records."""

    normalized_trades = [dict(trade) for trade in trades]
    normalized_income = [dict(item) for item in income]
    source_payload = {
        "trades": normalized_trades,
        "income": normalized_income,
        "planned_quantity": planned_quantity,
        "source_metadata": dict(source_metadata or {}),
    }
    source_hash = canonical_hash(source_payload)
    values: dict[str, Any] = {}
    available: set[str] = set()

    quantity_price_pairs: list[tuple[float, float]] = []
    total_fee = 0.0
    fee_count = 0
    total_quantity = 0.0
    for trade in normalized_trades:
        quantity = _trade_quantity(trade)
        price = _trade_price(trade)
        if quantity is not None:
            total_quantity += quantity
        if quantity is not None and price is not None:
            quantity_price_pairs.append((quantity, price))
        fee = _trade_fee(trade)
        if fee is not None:
            total_fee += fee
            fee_count += 1
    if quantity_price_pairs:
        denominator = sum(quantity for quantity, _ in quantity_price_pairs)
        if denominator > 0:
            values["fill_vwap"] = sum(
                quantity * price for quantity, price in quantity_price_pairs
            ) / denominator
            available.add("fill_vwap")
    if fee_count:
        values["fee"] = total_fee
        available.add("fee")
    if planned_quantity is not None and planned_quantity > 0 and total_quantity > 0:
        values["planned_vs_filled_qty"] = total_quantity / planned_quantity
        available.add("planned_vs_filled_qty")

    maker_or_taker = _maker_or_taker(normalized_trades)
    if maker_or_taker != UNAVAILABLE:
        available.add("maker_or_taker")

    funding_records = [
        item
        for item in normalized_income
        if str(item.get("incomeType", "")) == "FUNDING_FEE"
    ]
    if normalized_income or funding_records:
        values["funding"] = sum(
            _float(item.get("income")) or 0.0 for item in funding_records
        )
        available.add("funding")

    evidence: dict[str, dict[str, Any]] = {}
    for field in _EVIDENCE_FIELDS:
        is_available = field in available
        evidence[field] = {
            "status": "available" if is_available else UNAVAILABLE,
            "missing_reason": (
                None if is_available else "not_captured_at_event_time"
            ),
            "source_hash": source_hash,
        }
    return ExecutionAttributionReport.create_partial_real_fill(
        run_id=run_id,
        values=values,
        maker_or_taker=maker_or_taker,
        field_evidence=evidence,
        attribution_source_hash=source_hash,
    )
