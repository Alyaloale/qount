"""Execution attribution report contract.

Implements the ExecutionAttributionReport defined in
trading-system-evolution-plan.md section 4.4.

When no real fill sample exists, all numeric fields are "unavailable"
and attribution_source is "unavailable".  Backtest constants are
explicitly rejected -- this report can only be populated from
real execution evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import aware_datetime
from qount.contracts.trace import is_sha256
from qount.contracts.trace import trace_id


ATTRIBUTION_SCHEMA_VERSION = 1
UNAVAILABLE = "unavailable"
ATTRIBUTION_SOURCES = (UNAVAILABLE, "real_fill")

_NUMERIC_FIELDS = (
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
    "fee",
    "funding",
    "unfilled_exposure_time",
    "protection_order_latency",
    "stop_gap",
)


@dataclass(frozen=True)
class ExecutionAttributionReport:
    """Attribution of execution quality for one fill or order sequence.

    Without real fill evidence, create an unavailable report.
    With real fills, all numeric fields must be finite numbers and
    attribution_source must be "real_fill".
    """

    schema_version: int
    report_id: str
    run_id: str | None
    attribution_source: str
    decision_to_submit_ms: Any
    submit_to_ack_ms: Any
    ack_to_fill_ms: Any
    planned_vs_filled_qty: Any
    partial_fill_count: Any
    cancel_replace_count: Any
    arrival_mid: Any
    bid_ask_spread: Any
    fill_vwap: Any
    adverse_slippage: Any
    maker_or_taker: str
    fee: Any
    funding: Any
    unfilled_exposure_time: Any
    protection_order_latency: Any
    stop_gap: Any
    attribution_source_hash: str
    report_hash: str

    @classmethod
    def create_unavailable(
        cls,
        *,
        run_id: str | None = None,
        attribution_source_hash: str,
    ) -> ExecutionAttributionReport:
        """Create a report with all fields unavailable."""
        if not is_sha256(attribution_source_hash):
            raise ValueError(
                "execution_attribution_source_hash_invalid"
            )
        core = {
            "schema_version": ATTRIBUTION_SCHEMA_VERSION,
            "run_id": run_id,
            "attribution_source": UNAVAILABLE,
            "decision_to_submit_ms": UNAVAILABLE,
            "submit_to_ack_ms": UNAVAILABLE,
            "ack_to_fill_ms": UNAVAILABLE,
            "planned_vs_filled_qty": UNAVAILABLE,
            "partial_fill_count": UNAVAILABLE,
            "cancel_replace_count": UNAVAILABLE,
            "arrival_mid": UNAVAILABLE,
            "bid_ask_spread": UNAVAILABLE,
            "fill_vwap": UNAVAILABLE,
            "adverse_slippage": UNAVAILABLE,
            "maker_or_taker": UNAVAILABLE,
            "fee": UNAVAILABLE,
            "funding": UNAVAILABLE,
            "unfilled_exposure_time": UNAVAILABLE,
            "protection_order_latency": UNAVAILABLE,
            "stop_gap": UNAVAILABLE,
            "attribution_source_hash": attribution_source_hash,
        }
        report_hash = canonical_hash(core)
        return cls(
            schema_version=ATTRIBUTION_SCHEMA_VERSION,
            report_id=trace_id(
                "execution_attribution_report",
                {"report_hash": report_hash},
            ),
            run_id=run_id,
            attribution_source=UNAVAILABLE,
            decision_to_submit_ms=UNAVAILABLE,
            submit_to_ack_ms=UNAVAILABLE,
            ack_to_fill_ms=UNAVAILABLE,
            planned_vs_filled_qty=UNAVAILABLE,
            partial_fill_count=UNAVAILABLE,
            cancel_replace_count=UNAVAILABLE,
            arrival_mid=UNAVAILABLE,
            bid_ask_spread=UNAVAILABLE,
            fill_vwap=UNAVAILABLE,
            adverse_slippage=UNAVAILABLE,
            maker_or_taker=UNAVAILABLE,
            fee=UNAVAILABLE,
            funding=UNAVAILABLE,
            unfilled_exposure_time=UNAVAILABLE,
            protection_order_latency=UNAVAILABLE,
            stop_gap=UNAVAILABLE,
            attribution_source_hash=attribution_source_hash,
            report_hash=report_hash,
        )

    @classmethod
    def create_real_fill(
        cls,
        *,
        run_id: str | None,
        decision_to_submit_ms: float,
        submit_to_ack_ms: float,
        ack_to_fill_ms: float,
        planned_vs_filled_qty: float,
        partial_fill_count: int,
        cancel_replace_count: int,
        arrival_mid: float,
        bid_ask_spread: float,
        fill_vwap: float,
        adverse_slippage: float,
        maker_or_taker: str,
        fee: float,
        funding: float,
        unfilled_exposure_time: float,
        protection_order_latency: float,
        stop_gap: float,
        attribution_source_hash: str,
    ) -> ExecutionAttributionReport:
        """Create a report from a real fill sample.

        All numeric fields must be finite.  Backtest constants are
        not accepted -- only real execution evidence.
        """
        numeric_values = {
            "decision_to_submit_ms": decision_to_submit_ms,
            "submit_to_ack_ms": submit_to_ack_ms,
            "ack_to_fill_ms": ack_to_fill_ms,
            "planned_vs_filled_qty": planned_vs_filled_qty,
            "partial_fill_count": partial_fill_count,
            "cancel_replace_count": cancel_replace_count,
            "arrival_mid": arrival_mid,
            "bid_ask_spread": bid_ask_spread,
            "fill_vwap": fill_vwap,
            "adverse_slippage": adverse_slippage,
            "fee": fee,
            "funding": funding,
            "unfilled_exposure_time": unfilled_exposure_time,
            "protection_order_latency": protection_order_latency,
            "stop_gap": stop_gap,
        }
        for name, value in numeric_values.items():
            if isinstance(value, str):
                raise ValueError(
                    f"execution_attribution_{name}_cannot_be_string"
                )
            try:
                float_value = float(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"execution_attribution_{name}_invalid"
                )
            if not math.isfinite(float_value):
                raise ValueError(
                    f"execution_attribution_{name}_not_finite"
                )
        if maker_or_taker not in ("maker", "taker"):
            raise ValueError("execution_attribution_maker_or_taker_invalid")
        if not is_sha256(attribution_source_hash):
            raise ValueError(
                "execution_attribution_source_hash_invalid"
            )
        core = {
            "schema_version": ATTRIBUTION_SCHEMA_VERSION,
            "run_id": run_id,
            "attribution_source": "real_fill",
            "decision_to_submit_ms": float(decision_to_submit_ms),
            "submit_to_ack_ms": float(submit_to_ack_ms),
            "ack_to_fill_ms": float(ack_to_fill_ms),
            "planned_vs_filled_qty": float(planned_vs_filled_qty),
            "partial_fill_count": int(partial_fill_count),
            "cancel_replace_count": int(cancel_replace_count),
            "arrival_mid": float(arrival_mid),
            "bid_ask_spread": float(bid_ask_spread),
            "fill_vwap": float(fill_vwap),
            "adverse_slippage": float(adverse_slippage),
            "maker_or_taker": maker_or_taker,
            "fee": float(fee),
            "funding": float(funding),
            "unfilled_exposure_time": float(unfilled_exposure_time),
            "protection_order_latency": float(protection_order_latency),
            "stop_gap": float(stop_gap),
            "attribution_source_hash": attribution_source_hash,
        }
        report_hash = canonical_hash(core)
        report = cls(
            schema_version=ATTRIBUTION_SCHEMA_VERSION,
            report_id=trace_id(
                "execution_attribution_report",
                {"report_hash": report_hash},
            ),
            run_id=run_id,
            attribution_source="real_fill",
            decision_to_submit_ms=float(decision_to_submit_ms),
            submit_to_ack_ms=float(submit_to_ack_ms),
            ack_to_fill_ms=float(ack_to_fill_ms),
            planned_vs_filled_qty=float(planned_vs_filled_qty),
            partial_fill_count=int(partial_fill_count),
            cancel_replace_count=int(cancel_replace_count),
            arrival_mid=float(arrival_mid),
            bid_ask_spread=float(bid_ask_spread),
            fill_vwap=float(fill_vwap),
            adverse_slippage=float(adverse_slippage),
            maker_or_taker=maker_or_taker,
            fee=float(fee),
            funding=float(funding),
            unfilled_exposure_time=float(unfilled_exposure_time),
            protection_order_latency=float(protection_order_latency),
            stop_gap=float(stop_gap),
            attribution_source_hash=attribution_source_hash,
            report_hash=report_hash,
        )
        errors = report.validate()
        if errors:
            raise ValueError(
                f"execution_attribution_invalid:{','.join(errors)}"
            )
        return report

    def _core(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "attribution_source": self.attribution_source,
        }
        for field_name in _NUMERIC_FIELDS:
            result[field_name] = getattr(self, field_name)
        result["maker_or_taker"] = self.maker_or_taker
        result["attribution_source_hash"] = self.attribution_source_hash
        return result

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != ATTRIBUTION_SCHEMA_VERSION:
            errors.append("execution_attribution_schema_version_invalid")
        if self.attribution_source not in ATTRIBUTION_SOURCES:
            errors.append("execution_attribution_source_invalid")
        if self.attribution_source == UNAVAILABLE:
            for field_name in _NUMERIC_FIELDS:
                if getattr(self, field_name) != UNAVAILABLE:
                    errors.append(
                        f"execution_attribution_{field_name}_must_be_unavailable"
                    )
            if self.maker_or_taker != UNAVAILABLE:
                errors.append(
                    "execution_attribution_maker_or_taker_must_be_unavailable"
                )
        elif self.attribution_source == "real_fill":
            for field_name in _NUMERIC_FIELDS:
                value = getattr(self, field_name)
                if isinstance(value, str):
                    errors.append(
                        f"execution_attribution_{field_name}_cannot_be_string"
                    )
                    continue
                try:
                    float_value = float(value)
                except (TypeError, ValueError):
                    errors.append(
                        f"execution_attribution_{field_name}_invalid"
                    )
                    continue
                if not math.isfinite(float_value):
                    errors.append(
                        f"execution_attribution_{field_name}_not_finite"
                    )
            if self.maker_or_taker not in ("maker", "taker"):
                errors.append(
                    "execution_attribution_maker_or_taker_invalid"
                )
        if not is_sha256(self.attribution_source_hash):
            errors.append("execution_attribution_source_hash_invalid")
        expected_hash = canonical_hash(self._core())
        if self.report_hash != expected_hash:
            errors.append("execution_attribution_hash_invalid")
        expected_id = trace_id(
            "execution_attribution_report",
            {"report_hash": expected_hash},
        )
        if self.report_id != expected_id:
            errors.append("execution_attribution_id_invalid")
        return tuple(errors)
