from __future__ import annotations

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.settings import Settings

from .models import ALPHA_AGENT_VERSION


PROMOTION_VERSION = "alpha_agent_promotion_v0.1"

PASS = "pass"
BLOCK = "block"
WARN = "warn"


@dataclass(frozen=True)
class PromotionThresholds:
    min_dsr: float = 0.95
    max_pbo: float = 0.50
    min_min_notional_coverage: float = 0.95
    max_required_maker_fill: float = 0.90
    min_effective_breadth: float = 2.0
    min_paper_days: int = 30
    min_dry_days: int = 7
    max_live_pilot_cap_usdt: float = 200.0


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    name: str
    status: str
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get(payload: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = payload
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _bool(payload: dict[str, Any], path: str) -> bool:
    return bool(_get(payload, path, False))


def _float(payload: dict[str, Any], path: str, default: float = 0.0) -> float:
    value = _get(payload, path, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(payload: dict[str, Any], path: str, default: int = 0) -> int:
    value = _get(payload, path, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _gate(gate_id: str, name: str, reasons: list[str]) -> GateResult:
    return GateResult(gate_id=gate_id, name=name, status=PASS if not reasons else BLOCK, reasons=tuple(reasons))


def _warn_gate(gate_id: str, name: str, reasons: list[str]) -> GateResult:
    return GateResult(gate_id=gate_id, name=name, status=PASS if not reasons else WARN, reasons=tuple(reasons))


def _proposal_gate(metrics: dict[str, Any]) -> GateResult:
    reasons: list[str] = []
    proposal = _get(metrics, "proposal", {})
    for key in ("label_spec", "benchmark_spec", "data_spec", "cost_spec", "kill_line"):
        if not isinstance(proposal, dict) or not proposal.get(key):
            reasons.append(f"missing_{key}")
    if not _bool(metrics, "proposal.beta_residual_target"):
        reasons.append("missing_beta_residual_target")
    return _gate("G0", "proposal", reasons)


def _data_gate(metrics: dict[str, Any]) -> GateResult:
    reasons: list[str] = []
    for key in ("point_in_time", "as_of_join", "replayable"):
        if not _bool(metrics, f"data.{key}"):
            reasons.append(f"data_{key}_false")
    for key in ("data_hash", "code_version", "config_hash"):
        if not _get(metrics, f"data.{key}"):
            reasons.append(f"missing_{key}")
    holdout_role = _get(metrics, "data.holdout_role")
    if holdout_role not in {"discovery", "validation_v1", "unknown"}:
        reasons.append(f"invalid_holdout_role:{holdout_role}")
    if _int(metrics, "data.trial_count", 0) <= 0:
        reasons.append("missing_or_zero_trial_count")
    if _get(metrics, "data.exchange_rules_source") != "runtime_exchange_info":
        reasons.append("exchange_rules_not_runtime_exchange_info")
    if not _bool(metrics, "data.filter_validator_reused"):
        reasons.append("filter_validator_not_reused")
    return _gate("G1", "data", reasons)


def _baseline_gate(metrics: dict[str, Any]) -> GateResult:
    reasons: list[str] = []
    if _float(metrics, "performance.net_residual_return_pct", 0.0) <= 0.0:
        reasons.append("net_residual_return_not_positive")
    for key in ("cash", "btc_buy_hold", "top3_equal_weight", "current_live_baseline"):
        if not _bool(metrics, f"benchmarks.beats_{key}"):
            reasons.append(f"does_not_beat_{key}")
    if _float(metrics, "performance.beta_to_btc", 1.0) > 0.50:
        reasons.append("btc_beta_too_high")
    return _gate("G2", "baseline", reasons)


def _cost_gate(metrics: dict[str, Any], thresholds: PromotionThresholds) -> GateResult:
    reasons: list[str] = []
    if _float(metrics, "cost.net_after_cost_pct", 0.0) <= 0.0:
        reasons.append("net_after_cost_not_positive")
    if _float(metrics, "cost.worst_case_cost_net_pct", 0.0) <= 0.0:
        reasons.append("worst_case_cost_net_not_positive")
    if _float(metrics, "cost.min_notional_coverage", 0.0) < thresholds.min_min_notional_coverage:
        reasons.append("min_notional_coverage_below_threshold")
    required_maker = _float(metrics, "cost.required_maker_fill_ratio", 0.0)
    actual_maker = _float(metrics, "cost.actual_maker_fill_ratio", 0.0)
    if required_maker >= thresholds.max_required_maker_fill and actual_maker < required_maker:
        reasons.append("maker_fill_requirement_unproven")
    if not _bool(metrics, "cost.funding_included"):
        reasons.append("funding_not_included")
    return _gate("G3", "cost", reasons)


def _anti_overfit_gate(metrics: dict[str, Any], thresholds: PromotionThresholds) -> GateResult:
    reasons: list[str] = []
    if _float(metrics, "validation.deflated_sharpe_ratio", 0.0) < thresholds.min_dsr:
        reasons.append("dsr_below_threshold")
    if _float(metrics, "validation.pbo", 1.0) >= thresholds.max_pbo:
        reasons.append("pbo_above_threshold")
    if not _bool(metrics, "validation.purged_cv_pass"):
        reasons.append("purged_cv_not_passed")
    if _float(metrics, "validation.largest_contributor_removed_return_pct", 0.0) <= 0.0:
        reasons.append("largest_contributor_removed_not_positive")
    if not _bool(metrics, "validation.embargo_applied"):
        reasons.append("embargo_not_applied")
    return _gate("G4", "anti_overfit", reasons)


def _breadth_gate(metrics: dict[str, Any], thresholds: PromotionThresholds) -> GateResult:
    reasons: list[str] = []
    breadth = _float(metrics, "breadth.effective_breadth", 0.0)
    if breadth <= 0.0:
        reasons.append("missing_effective_breadth")
    elif breadth < thresholds.min_effective_breadth and _bool(metrics, "breadth.claims_cross_sectional_edge"):
        reasons.append("effective_breadth_below_cross_sectional_threshold")
    if not _bool(metrics, "breadth.correlation_stress_pass"):
        reasons.append("correlation_stress_not_passed")
    if not _bool(metrics, "breadth.capacity_checked"):
        reasons.append("capacity_not_checked")
    return _gate("G5", "breadth_capacity", reasons)


def _paper_gate(metrics: dict[str, Any], thresholds: PromotionThresholds) -> GateResult:
    reasons: list[str] = []
    if _get(metrics, "paper.holdout_role") != "validation_v1":
        reasons.append("paper_not_validation_v1")
    if _int(metrics, "paper.forward_days", 0) < thresholds.min_paper_days:
        reasons.append("paper_days_below_threshold")
    for key in ("schema_errors", "unmanaged_positions", "unknown_price_filter_events"):
        if _int(metrics, f"paper.{key}", 1) != 0:
            reasons.append(f"paper_{key}_nonzero")
    if not _bool(metrics, "paper.orders_replayable"):
        reasons.append("paper_orders_not_replayable")
    return _gate("G6", "paper", reasons)


def _live_gate(metrics: dict[str, Any], thresholds: PromotionThresholds) -> GateResult:
    reasons: list[str] = []
    if _int(metrics, "live.dry_run_days", 0) < thresholds.min_dry_days:
        reasons.append("dry_run_days_below_threshold")
    if _float(metrics, "live.pilot_cap_usdt", thresholds.max_live_pilot_cap_usdt + 1.0) > thresholds.max_live_pilot_cap_usdt:
        reasons.append("pilot_cap_above_threshold")
    for key in ("withdrawal_disabled", "one_way_position_mode", "isolated_margin", "rollback_written"):
        if not _bool(metrics, f"live.{key}"):
            reasons.append(f"live_{key}_false")
    return _gate("G7", "live_pilot", reasons)


def _llm_gate(metrics: dict[str, Any]) -> GateResult:
    reasons: list[str] = []
    if _bool(metrics, "llm.used_for_orders"):
        reasons.append("llm_used_for_orders")
    if _bool(metrics, "llm.used_for_target_weights"):
        reasons.append("llm_used_for_target_weights")
    if _bool(metrics, "llm.used_for_risk_override"):
        reasons.append("llm_used_for_risk_override")
    return _gate("GX", "llm_boundary", reasons)


def evaluate_promotion_scorecard(
    metrics: dict[str, Any],
    *,
    target: str = "paper",
    thresholds: PromotionThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or PromotionThresholds()
    gates = [
        _proposal_gate(metrics),
        _data_gate(metrics),
        _baseline_gate(metrics),
        _cost_gate(metrics, thresholds),
        _anti_overfit_gate(metrics, thresholds),
        _breadth_gate(metrics, thresholds),
        _llm_gate(metrics),
    ]
    if target in {"paper", "live_pilot"}:
        gates.append(_paper_gate(metrics, thresholds))
    if target == "live_pilot":
        gates.append(_live_gate(metrics, thresholds))
    if target not in {"proposal", "paper", "live_pilot"}:
        gates.append(GateResult("G?", "target", BLOCK, (f"invalid_target:{target}",)))

    blocked = [gate for gate in gates if gate.status == BLOCK]
    warnings = [gate for gate in gates if gate.status == WARN]
    return {
        "schema_version": PROMOTION_VERSION,
        "alpha_agent_version": ALPHA_AGENT_VERSION,
        "created_at": utc_now().isoformat(),
        "target": target,
        "verdict": "pass" if not blocked else "block",
        "gate_count": len(gates),
        "blocked_gate_count": len(blocked),
        "warning_gate_count": len(warnings),
        "thresholds": asdict(thresholds),
        "gates": [gate.to_dict() for gate in gates],
        "hard_boundaries": [
            "LLM reports cannot satisfy promotion gates.",
            "Raw return is insufficient; beta residual and cost-adjusted evidence are required.",
            "Paper/live promotion requires validation_v1 or later forward evidence.",
        ],
    }


def load_metrics(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("promotion metrics must be a JSON object")
    return payload


def write_promotion_scorecard_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-scorecard",
        path_key="artifact_path",
        default_filename="alpha_agent_scorecard.json",
        explicit_path=explicit_path,
    )
