"""One fixed H.4.1 plus hash-rate fusion trial for MiniTrend discovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.macro_h41_model import augment_dataset_with_h41_feature
from qount.mini_trend.regime_economic_ml import run_economic_ml_walk_forward
from qount.mini_trend.regime_ml import FEATURE_NAMES, RegimeMLConfig
from qount.mini_trend.regime_ml import build_regime_ml_dataset
from qount.mini_trend.regime_onchain_model import ONCHAIN_MODEL_FEATURE
from qount.mini_trend.regime_onchain_model import augment_dataset_with_hashrate
from qount.models import utc_now
from qount.settings import Settings


MACRO_ONCHAIN_FUSION_VERSION = "mini_trend_macro_onchain_fusion_v0.1"
MACRO_FEATURE = "fed_assets_4w_change_pct"
MACRO_TRIAL_ID = f"h41_{MACRO_FEATURE}"
FUSION_FEATURE_NAMES = (*FEATURE_NAMES, ONCHAIN_MODEL_FEATURE, MACRO_FEATURE)
ONCHAIN_MODEL_VERDICT = "retain_onchain_rolling_ranker_for_strategy_ablation"


@dataclass(frozen=True)
class MacroOnchainFusionConfig:
    candidate_id: str = "h60_train365_base_plus_hashrate_plus_h41_4w_random_forest"
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    horizon_days: int = 60
    training_window_days: int = 365
    model: str = "random_forest"
    target: str = "return"
    bootstrap_samples: int = 10_000
    seed: int = 20260718
    prior_research_trial_count: int = 134

    @property
    def trial_count(self) -> int:
        return 1

    @property
    def cumulative_trial_count(self) -> int:
        return self.prior_research_trial_count + self.trial_count

    @property
    def model_seed(self) -> int:
        return self.seed + self.horizon_days * 100 + self.training_window_days

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "model_seed": self.model_seed,
                "feature_names": list(FUSION_FEATURE_NAMES),
                "selection": (
                    "one fixed fusion of the retained 4-week H.4.1 feature and retained hash-rate feature"
                ),
                "no_feature_or_model_search": True,
                "paper_or_live_allowed": False,
            }
        )


def build_macro_onchain_fusion(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    h41_dataset: Mapping[str, Any],
    h41_audit: Mapping[str, Any],
    onchain_dataset: Mapping[str, Any],
    onchain_model: Mapping[str, Any],
    config: MacroOnchainFusionConfig | None = None,
) -> dict[str, Any]:
    config = config or MacroOnchainFusionConfig()
    if MACRO_TRIAL_ID not in h41_audit.get("retained_trial_ids", []):
        raise ValueError("required H.4.1 feature was not retained")
    if onchain_model.get("diagnostics", {}).get("verdict") != ONCHAIN_MODEL_VERDICT:
        raise ValueError("required on-chain model was not retained")
    macro_parent = next(
        row for row in h41_audit["trials"] if row["trial_id"] == MACRO_TRIAL_ID
    )
    onchain_parent = onchain_model["candidate"]
    base = build_regime_ml_dataset(
        bars_by_symbol,
        funding_by_symbol,
        RegimeMLConfig(
            start_date=config.start_date,
            end_date=config.end_date,
            horizon_days=config.horizon_days,
            barrier_sigma=1.0,
            trial_count=config.trial_count,
            seed=config.seed,
        ),
    )
    onchain_augmented = augment_dataset_with_hashrate(base, onchain_dataset)
    dataset = augment_dataset_with_h41_feature(
        onchain_augmented, h41_dataset, MACRO_FEATURE
    )
    result = run_economic_ml_walk_forward(
        dataset,
        target=config.target,
        model_name=config.model,
        use_gpu=False,
        seed=config.model_seed,
        bootstrap_samples=config.bootstrap_samples,
        feature_names=FUSION_FEATURE_NAMES,
        training_window_days=config.training_window_days,
        include_predictions=True,
    )
    fold_2026 = next(row for row in result["folds"] if row["test_year"] == 2026)
    parents = (macro_parent, onchain_parent)
    gates = {
        "all_horizon_purge_checks_passed": all(
            row["purge_check_passed"] for row in result["folds"]
        ),
        "positive_rank_ic_in_three_folds": result["positive_rank_ic_fold_count"] >= 3,
        "positive_spread_in_three_folds": result["positive_spread_fold_count"] >= 3,
        "bootstrap_probability_at_least_80pct": (
            result["bootstrap"]["probability_spread_positive"] >= 0.8
        ),
        "positive_2026_rank_ic_and_spread": (
            fold_2026["rank_ic"] > 0 and fold_2026["high_minus_low_actual"] > 0
        ),
        "pooled_rank_ic_not_lower_than_both_parents": (
            result["pooled_rank_ic"] >= max(row["pooled_rank_ic"] for row in parents)
        ),
        "pooled_spread_not_lower_than_both_parents": (
            result["pooled_high_minus_low_actual"]
            >= max(row["pooled_high_minus_low_actual"] for row in parents)
        ),
        "bootstrap_probability_not_lower_than_both_parents": (
            result["bootstrap"]["probability_spread_positive"]
            >= max(row["bootstrap"]["probability_spread_positive"] for row in parents)
        ),
    }
    retained = all(gates.values())
    return {
        "schema_version": MACRO_ONCHAIN_FUSION_VERSION,
        "artifact_type": "mini_trend_macro_onchain_fusion",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "onchain_source_vintage": "latest_available_response_not_historical_vintage",
            "point_in_time_promotion_ready": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "feature_names": list(FUSION_FEATURE_NAMES),
            "model_seed": config.model_seed,
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "contract_hash": config.contract_hash,
        },
        "lineage": {
            "h41_data_hash": h41_dataset["data_hash"],
            "h41_audit_hash": canonical_hash(h41_audit),
            "onchain_data_hash": onchain_dataset["data_hash"],
            "onchain_model_hash": canonical_hash(onchain_model),
            "fusion_dataset_contract_hash": dataset["contract"]["contract_hash"],
            "fusion_dataset_data_hash": dataset["data_hash"],
        },
        "parents": {
            "macro": macro_parent,
            "onchain": onchain_parent,
        },
        "candidate": result,
        "comparison": {
            "versus_macro": {
                "pooled_rank_ic_delta": result["pooled_rank_ic"] - macro_parent["pooled_rank_ic"],
                "pooled_spread_delta": (
                    result["pooled_high_minus_low_actual"]
                    - macro_parent["pooled_high_minus_low_actual"]
                ),
                "bootstrap_probability_delta": (
                    result["bootstrap"]["probability_spread_positive"]
                    - macro_parent["bootstrap"]["probability_spread_positive"]
                ),
            },
            "versus_onchain": {
                "pooled_rank_ic_delta": result["pooled_rank_ic"] - onchain_parent["pooled_rank_ic"],
                "pooled_spread_delta": (
                    result["pooled_high_minus_low_actual"]
                    - onchain_parent["pooled_high_minus_low_actual"]
                ),
                "bootstrap_probability_delta": (
                    result["bootstrap"]["probability_spread_positive"]
                    - onchain_parent["bootstrap"]["probability_spread_positive"]
                ),
            },
        },
        "diagnostics": {
            "gates": gates,
            "passed_gate_count": sum(gates.values()),
            "gate_count": len(gates),
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "verdict": (
                "retain_macro_onchain_fusion_for_strategy_ablation"
                if retained
                else "reject_macro_onchain_fusion"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_macro_onchain_fusion_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-macro-onchain-fusion",
        path_key="artifact_path",
        default_filename="mini_trend_macro_onchain_fusion.json",
        explicit_path=explicit_path,
    )
