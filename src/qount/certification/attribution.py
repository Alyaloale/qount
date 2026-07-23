"""Execution attribution with honest per-field evidence availability."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import is_sha256
from qount.contracts.trace import trace_id


ATTRIBUTION_SCHEMA_VERSION = 2
ATTRIBUTION_SCHEMA_VERSIONS = (1, 2)
UNAVAILABLE = "unavailable"
ATTRIBUTION_SOURCES = (UNAVAILABLE, "real_fill")
FIELD_AVAILABILITY = ("available", UNAVAILABLE)

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
_EVIDENCE_FIELDS = (*_NUMERIC_FIELDS, "maker_or_taker")


def _evidence_row(
    *,
    status: str,
    source_hash: str,
    missing_reason: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "missing_reason": missing_reason,
        "source_hash": source_hash,
    }


@dataclass(frozen=True)
class ExecutionAttributionReport:
    """Execution-quality evidence for one real fill or order sequence.

    Schema v2 allows each metric to remain unavailable with a reason and
    source hash.  This lets a real fee or fill be retained even when arrival
    mid, spread, or latency was not captured at event time.  Schema v1
    objects remain readable for historical artifact compatibility.
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
    field_evidence: Mapping[str, Mapping[str, Any]]
    attribution_source_hash: str
    report_hash: str

    @classmethod
    def create_unavailable(
        cls,
        *,
        run_id: str | None = None,
        attribution_source_hash: str,
        missing_reason: str = "no_real_fill_sample",
    ) -> ExecutionAttributionReport:
        if not is_sha256(attribution_source_hash):
            raise ValueError("execution_attribution_source_hash_invalid")
        if not missing_reason:
            raise ValueError("execution_attribution_missing_reason_empty")
        values = {field: UNAVAILABLE for field in _NUMERIC_FIELDS}
        evidence = {
            field: _evidence_row(
                status=UNAVAILABLE,
                source_hash=attribution_source_hash,
                missing_reason=missing_reason,
            )
            for field in _EVIDENCE_FIELDS
        }
        return cls._create_v2(
            run_id=run_id,
            attribution_source=UNAVAILABLE,
            values=values,
            maker_or_taker=UNAVAILABLE,
            field_evidence=evidence,
            attribution_source_hash=attribution_source_hash,
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
        values = {
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
        evidence = {
            field: _evidence_row(
                status="available",
                source_hash=attribution_source_hash,
                missing_reason=None,
            )
            for field in _EVIDENCE_FIELDS
        }
        return cls._create_v2(
            run_id=run_id,
            attribution_source="real_fill",
            values=values,
            maker_or_taker=maker_or_taker,
            field_evidence=evidence,
            attribution_source_hash=attribution_source_hash,
        )

    @classmethod
    def create_partial_real_fill(
        cls,
        *,
        run_id: str | None,
        values: Mapping[str, Any],
        maker_or_taker: str = UNAVAILABLE,
        field_evidence: Mapping[str, Mapping[str, Any]],
        attribution_source_hash: str,
    ) -> ExecutionAttributionReport:
        """Create a report that keeps real fields without fabricating gaps."""

        unknown = set(values) - set(_NUMERIC_FIELDS)
        if unknown:
            raise ValueError(
                "execution_attribution_unknown_fields:"
                + ",".join(sorted(unknown))
            )
        normalized_values = {
            field: values.get(field, UNAVAILABLE)
            for field in _NUMERIC_FIELDS
        }
        return cls._create_v2(
            run_id=run_id,
            attribution_source="real_fill",
            values=normalized_values,
            maker_or_taker=maker_or_taker,
            field_evidence=field_evidence,
            attribution_source_hash=attribution_source_hash,
        )

    @classmethod
    def _create_v2(
        cls,
        *,
        run_id: str | None,
        attribution_source: str,
        values: Mapping[str, Any],
        maker_or_taker: str,
        field_evidence: Mapping[str, Mapping[str, Any]],
        attribution_source_hash: str,
    ) -> ExecutionAttributionReport:
        normalized_evidence = {
            field: dict(field_evidence[field])
            for field in sorted(field_evidence)
        }
        core = {
            "schema_version": ATTRIBUTION_SCHEMA_VERSION,
            "run_id": run_id,
            "attribution_source": attribution_source,
            **{field: values[field] for field in _NUMERIC_FIELDS},
            "maker_or_taker": maker_or_taker,
            "field_evidence": normalized_evidence,
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
            attribution_source=attribution_source,
            decision_to_submit_ms=values["decision_to_submit_ms"],
            submit_to_ack_ms=values["submit_to_ack_ms"],
            ack_to_fill_ms=values["ack_to_fill_ms"],
            planned_vs_filled_qty=values["planned_vs_filled_qty"],
            partial_fill_count=values["partial_fill_count"],
            cancel_replace_count=values["cancel_replace_count"],
            arrival_mid=values["arrival_mid"],
            bid_ask_spread=values["bid_ask_spread"],
            fill_vwap=values["fill_vwap"],
            adverse_slippage=values["adverse_slippage"],
            maker_or_taker=maker_or_taker,
            fee=values["fee"],
            funding=values["funding"],
            unfilled_exposure_time=values["unfilled_exposure_time"],
            protection_order_latency=values["protection_order_latency"],
            stop_gap=values["stop_gap"],
            field_evidence=normalized_evidence,
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
        if self.schema_version >= 2:
            result["field_evidence"] = {
                field: dict(evidence)
                for field, evidence in sorted(self.field_evidence.items())
            }
        result["attribution_source_hash"] = self.attribution_source_hash
        return result

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version not in ATTRIBUTION_SCHEMA_VERSIONS:
            errors.append("execution_attribution_schema_version_invalid")
        if self.attribution_source not in ATTRIBUTION_SOURCES:
            errors.append("execution_attribution_source_invalid")
        if not is_sha256(self.attribution_source_hash):
            errors.append("execution_attribution_source_hash_invalid")

        if self.schema_version == 1:
            errors.extend(self._validate_v1_values())
        elif self.schema_version == 2:
            errors.extend(self._validate_v2_values())

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

    def _validate_v1_values(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.field_evidence:
            errors.append("execution_attribution_v1_field_evidence_forbidden")
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
            return tuple(errors)
        for field_name in _NUMERIC_FIELDS:
            errors.extend(
                self._numeric_value_errors(
                    field_name,
                    getattr(self, field_name),
                )
            )
        if self.maker_or_taker not in ("maker", "taker"):
            errors.append("execution_attribution_maker_or_taker_invalid")
        return tuple(errors)

    def _validate_v2_values(self) -> tuple[str, ...]:
        errors: list[str] = []
        if set(self.field_evidence) != set(_EVIDENCE_FIELDS):
            errors.append("execution_attribution_field_evidence_set_invalid")
            return tuple(errors)
        for field_name in _EVIDENCE_FIELDS:
            evidence = self.field_evidence.get(field_name)
            if not isinstance(evidence, Mapping):
                errors.append(
                    f"execution_attribution_{field_name}_evidence_invalid"
                )
                continue
            if set(evidence) != {"status", "missing_reason", "source_hash"}:
                errors.append(
                    f"execution_attribution_{field_name}_evidence_fields_invalid"
                )
                continue
            status = evidence.get("status")
            missing_reason = evidence.get("missing_reason")
            source_hash = evidence.get("source_hash")
            if status not in FIELD_AVAILABILITY:
                errors.append(
                    f"execution_attribution_{field_name}_status_invalid"
                )
                continue
            if not is_sha256(source_hash):
                errors.append(
                    f"execution_attribution_{field_name}_source_hash_invalid"
                )
            value = (
                self.maker_or_taker
                if field_name == "maker_or_taker"
                else getattr(self, field_name)
            )
            if status == UNAVAILABLE:
                if value != UNAVAILABLE:
                    errors.append(
                        f"execution_attribution_{field_name}_must_be_unavailable"
                    )
                if not isinstance(missing_reason, str) or not missing_reason:
                    errors.append(
                        f"execution_attribution_{field_name}_missing_reason_invalid"
                    )
            else:
                if missing_reason is not None:
                    errors.append(
                        f"execution_attribution_{field_name}_missing_reason_for_available"
                    )
                if field_name == "maker_or_taker":
                    if value not in ("maker", "taker"):
                        errors.append(
                            "execution_attribution_maker_or_taker_invalid"
                        )
                else:
                    errors.extend(self._numeric_value_errors(field_name, value))
        if self.attribution_source == UNAVAILABLE and any(
            evidence.get("status") == "available"
            for evidence in self.field_evidence.values()
        ):
            errors.append(
                "execution_attribution_unavailable_source_has_available_field"
            )
        return tuple(errors)

    @staticmethod
    def _numeric_value_errors(field_name: str, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return (f"execution_attribution_{field_name}_cannot_be_string",)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return (f"execution_attribution_{field_name}_invalid",)
        if not math.isfinite(numeric):
            return (f"execution_attribution_{field_name}_not_finite",)
        return ()
