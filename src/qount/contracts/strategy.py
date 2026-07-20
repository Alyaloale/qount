"""Order-free strategy intent contract."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from qount.contracts.hashing import canonical_hash
from qount.contracts.trace import is_sha256
from qount.contracts.trace import timestamp_errors
from qount.contracts.trace import trace_id

_STRATEGY_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_REASON_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,95}$")


@dataclass(frozen=True)
class StrategyIntent:
    """A strategy target contract that cannot contain exchange orders."""

    strategy_id: str
    decision_time: str
    data_cutoff: str
    target_weights: Mapping[str, float]
    expected_holding_bars: int
    target_stress_loss_fraction: float
    evidence_hash: str
    state_hash: str
    schema_version: int = 0
    strategy_version: str = ""
    decision_id: str = ""
    snapshot_id: str = ""
    reason_codes: tuple[str, ...] = ()
    intent_hash: str = ""

    @classmethod
    def create(
        cls,
        *,
        strategy_id: str,
        strategy_version: str,
        snapshot_id: str,
        decision_time: str,
        data_cutoff: str,
        target_weights: Mapping[str, float],
        expected_holding_bars: int,
        target_stress_loss_fraction: float,
        reason_codes: Sequence[str],
        evidence_hash: str,
        state_hash: str,
        decision_id: str | None = None,
    ) -> StrategyIntent:
        normalized_reasons = tuple(reason_codes)
        normalized_weights = dict(target_weights)
        resolved_decision_id = decision_id or trace_id(
            "strategy_decision",
            {
                "schema_version": 1,
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "snapshot_id": snapshot_id,
                "decision_time": decision_time,
                "data_cutoff": data_cutoff,
                "target_weights": normalized_weights,
                "expected_holding_bars": expected_holding_bars,
                "target_stress_loss_fraction": target_stress_loss_fraction,
                "reason_codes": normalized_reasons,
                "evidence_hash": evidence_hash,
                "state_hash": state_hash,
            },
        )
        trace_core = {
            "schema_version": 1,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "decision_id": resolved_decision_id,
            "snapshot_id": snapshot_id,
            "decision_time": decision_time,
            "data_cutoff": data_cutoff,
            "target_weights": normalized_weights,
            "expected_holding_bars": expected_holding_bars,
            "target_stress_loss_fraction": target_stress_loss_fraction,
            "reason_codes": normalized_reasons,
            "evidence_hash": evidence_hash,
            "state_hash": state_hash,
        }
        intent = cls(
            strategy_id=strategy_id,
            decision_time=decision_time,
            data_cutoff=data_cutoff,
            target_weights=normalized_weights,
            expected_holding_bars=expected_holding_bars,
            target_stress_loss_fraction=target_stress_loss_fraction,
            evidence_hash=evidence_hash,
            state_hash=state_hash,
            schema_version=1,
            strategy_version=strategy_version,
            decision_id=resolved_decision_id,
            snapshot_id=snapshot_id,
            reason_codes=normalized_reasons,
            intent_hash=canonical_hash(trace_core),
        )
        errors = intent.validate()
        if errors:
            raise ValueError(f"strategy_intent_invalid:{','.join(errors)}")
        return intent

    @property
    def traced(self) -> bool:
        return bool(
            self.schema_version
            or self.strategy_version
            or self.decision_id
            or self.snapshot_id
            or self.reason_codes
            or self.intent_hash
        )

    def _trace_core(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "decision_id": self.decision_id,
            "snapshot_id": self.snapshot_id,
            "decision_time": self.decision_time,
            "data_cutoff": self.data_cutoff,
            "target_weights": dict(self.target_weights),
            "expected_holding_bars": self.expected_holding_bars,
            "target_stress_loss_fraction": self.target_stress_loss_fraction,
            "reason_codes": tuple(self.reason_codes),
            "evidence_hash": self.evidence_hash,
            "state_hash": self.state_hash,
        }

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.strategy_id:
            errors.append("strategy_id_empty")
        timestamp_issues = timestamp_errors(
            self.decision_time,
            self.data_cutoff,
            prefix="strategy_intent",
        )
        errors.extend(
            "data_cutoff_after_decision_time"
            if issue == "strategy_intent_data_cutoff_after_decision_time"
            else "strategy_intent_datetime_invalid"
            for issue in timestamp_issues
        )
        if not isinstance(self.expected_holding_bars, int) or self.expected_holding_bars < 1:
            errors.append("expected_holding_bars_invalid")
        try:
            stress_loss = float(self.target_stress_loss_fraction)
        except (TypeError, ValueError):
            stress_loss = math.nan
        if not math.isfinite(stress_loss) or not 0.0 <= stress_loss <= 1.0:
            errors.append("target_stress_loss_fraction_invalid")
        for name in ("evidence_hash", "state_hash"):
            if not is_sha256(getattr(self, name)):
                errors.append(f"{name}_invalid")

        if self.traced:
            if self.schema_version != 1:
                errors.append("strategy_intent_schema_version_invalid")
            if not _STRATEGY_VERSION_RE.fullmatch(self.strategy_version):
                errors.append("strategy_version_invalid")
            if not is_sha256(self.decision_id):
                errors.append("decision_id_invalid")
            if not is_sha256(self.snapshot_id):
                errors.append("snapshot_id_invalid")
            if not is_sha256(self.intent_hash):
                errors.append("intent_hash_invalid")
            elif self.intent_hash != canonical_hash(self._trace_core()):
                errors.append("intent_hash_mismatch")
            if not self.reason_codes:
                errors.append("reason_codes_empty")
            elif len(self.reason_codes) != len(set(self.reason_codes)):
                errors.append("reason_codes_duplicate")
            for reason_code in self.reason_codes:
                if not _REASON_CODE_RE.fullmatch(str(reason_code)):
                    errors.append(f"reason_code_invalid:{reason_code}")

        gross = 0.0
        for symbol, raw_weight in self.target_weights.items():
            try:
                weight = float(raw_weight)
            except (TypeError, ValueError):
                errors.append(f"target_weight_invalid:{symbol}")
                continue
            if not symbol or not math.isfinite(weight):
                errors.append(f"target_weight_invalid:{symbol}")
            elif weight < 0.0:
                errors.append(f"short_target_forbidden:{symbol}")
            else:
                gross += weight
        if gross > 1.0 + 1e-12:
            errors.append("standalone_target_gross_exceeds_one")
        return tuple(errors)
