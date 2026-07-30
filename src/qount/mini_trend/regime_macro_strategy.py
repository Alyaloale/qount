"""Reuse the frozen downside-only risk rules on the retained H.4.1 ranker."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_adaptation_ablation import AdaptationAblationConfig
from qount.mini_trend.regime_adaptation_ablation import build_adaptation_risk_ablation
from qount.models import utc_now
from qount.settings import Settings


MACRO_STRATEGY_VERSION = "mini_trend_h41_strategy_ablation_v0.1"
MACRO_AUDIT_VERDICT = "retain_h41_macro_features_for_strategy_ablation"
MACRO_CANDIDATE_ID = "h41_fed_assets_4w_change_pct"


def build_macro_strategy_ablation(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    macro_audit: Mapping[str, Any],
) -> dict[str, Any]:
    if macro_audit.get("diagnostics", {}).get("verdict") != MACRO_AUDIT_VERDICT:
        raise ValueError("H.4.1 audit did not authorize strategy ablation")
    if MACRO_CANDIDATE_ID not in macro_audit.get("retained_trial_ids", []):
        raise ValueError("fixed H.4.1 strategy candidate was not retained")
    candidate = next(
        row for row in macro_audit["trials"] if row["trial_id"] == MACRO_CANDIDATE_ID
    )
    if not candidate.get("prediction_rows"):
        raise ValueError("H.4.1 candidate is missing deterministic prediction rows")
    adapter = {
        "diagnostics": macro_audit["diagnostics"],
        "contract": {
            **macro_audit["contract"],
            "candidate_id": MACRO_CANDIDATE_ID,
        },
        "confirmation_result": candidate,
    }
    payload = build_adaptation_risk_ablation(
        bars_by_symbol,
        funding_by_symbol,
        rules_artifact,
        adapter,
        AdaptationAblationConfig(
            candidate_id=MACRO_CANDIDATE_ID,
            confirmation_verdict=MACRO_AUDIT_VERDICT,
            prior_family_trial_count=135,
        ),
    )
    retained = bool(payload["retained_trial_ids"])
    payload.update(
        {
            "schema_version": MACRO_STRATEGY_VERSION,
            "artifact_type": "mini_trend_h41_strategy_risk_ablation",
            "created_at": utc_now().isoformat(),
        }
    )
    payload["meta"].update(
        {
            "macro_source": "Federal Reserve H.4.1 official historical releases",
            "macro_point_in_time": True,
            "holdout_role": "consumed_historical_discovery_pool",
        }
    )
    payload["lineage"].update(
        {
            "macro_audit_hash": canonical_hash(macro_audit),
            "macro_audit_contract_hash": macro_audit["contract"]["contract_hash"],
            "h41_data_hash": macro_audit["data_lineage"]["h41_data_hash"],
        }
    )
    payload["diagnostics"].update(
        {
            "verdict": (
                "retain_h41_ml_risk_overlay_for_future_only_research"
                if retained
                else "reject_h41_ml_risk_overlay_after_strategy_ablation"
            ),
            "interpretation": (
                "The same three frozen downside-only risk rules are reused without threshold search; "
                "all evaluated market history is consumed discovery evidence."
            ),
            "paper_or_live_allowed": False,
        }
    )
    return payload


def write_macro_strategy_ablation_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-h41-strategy-risk-ablation",
        path_key="artifact_path",
        default_filename="mini_trend_h41_strategy_risk_ablation.json",
        explicit_path=explicit_path,
    )
