"""Reuse the frozen downside-only risk rules on the retained on-chain ranker."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_adaptation_ablation import AdaptationAblationConfig
from qount.mini_trend.regime_adaptation_ablation import build_adaptation_risk_ablation
from qount.models import utc_now
from qount.settings import Settings


ONCHAIN_STRATEGY_VERSION = "mini_trend_onchain_strategy_ablation_v0.1"
ONCHAIN_MODEL_VERDICT = "retain_onchain_rolling_ranker_for_strategy_ablation"


def build_onchain_strategy_ablation(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    rules_artifact: Mapping[str, Any],
    onchain_model: Mapping[str, Any],
) -> dict[str, Any]:
    if onchain_model.get("diagnostics", {}).get("verdict") != ONCHAIN_MODEL_VERDICT:
        raise ValueError("on-chain rolling model did not authorize strategy ablation")
    candidate_id = str(onchain_model["contract"]["candidate_id"])
    adapter = {
        "diagnostics": onchain_model["diagnostics"],
        "contract": onchain_model["contract"],
        "confirmation_result": onchain_model["candidate"],
    }
    payload = build_adaptation_risk_ablation(
        bars_by_symbol,
        funding_by_symbol,
        rules_artifact,
        adapter,
        AdaptationAblationConfig(
            candidate_id=candidate_id,
            confirmation_verdict=ONCHAIN_MODEL_VERDICT,
            prior_family_trial_count=128,
        ),
    )
    retained = bool(payload["retained_trial_ids"])
    payload.update(
        {
            "schema_version": ONCHAIN_STRATEGY_VERSION,
            "artifact_type": "mini_trend_onchain_strategy_risk_ablation",
            "created_at": utc_now().isoformat(),
        }
    )
    payload["meta"].update(
        {
            "source_vintage": "latest_available_response_not_historical_vintage",
            "point_in_time_promotion_ready": False,
        }
    )
    payload["lineage"].update(
        {
            "onchain_model_hash": canonical_hash(onchain_model),
            "onchain_model_contract_hash": onchain_model["contract"]["contract_hash"],
        }
    )
    payload["diagnostics"].update(
        {
            "verdict": (
                "retain_onchain_ml_risk_overlay_for_future_only_research"
                if retained
                else "reject_onchain_ml_risk_overlay_after_strategy_ablation"
            ),
            "interpretation": (
                "The same frozen downside-only risk rules are reused without threshold search; "
                "latest-vintage discovery evidence only."
            ),
        }
    )
    return payload


def write_onchain_strategy_ablation_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-onchain-strategy-risk-ablation",
        path_key="artifact_path",
        default_filename="mini_trend_onchain_strategy_risk_ablation.json",
        explicit_path=explicit_path,
    )
