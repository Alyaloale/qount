"""Single fixed rolling-RF ablation with the retained BTC hash-rate feature."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_economic_ml import run_economic_ml_walk_forward
from qount.mini_trend.regime_ml import FEATURE_NAMES
from qount.mini_trend.regime_ml import RegimeMLConfig, build_regime_ml_dataset
from qount.models import utc_now
from qount.settings import Settings


ONCHAIN_MODEL_VERSION = "mini_trend_onchain_rolling_model_ablation_v0.1"
ONCHAIN_MODEL_FEATURE = "hashrate_z90"
ONCHAIN_MODEL_FEATURE_NAMES = (*FEATURE_NAMES, ONCHAIN_MODEL_FEATURE)


@dataclass(frozen=True)
class OnchainModelConfig:
    candidate_id: str = "h60_train365_base_plus_hashrate_random_forest"
    source_candidate_id: str = "h60_train365_base_random_forest"
    required_feature_trial_id: str = "hashrate_z90_polarity_+1"
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    horizon_days: int = 60
    training_window_days: int = 365
    model: str = "random_forest"
    target: str = "return"
    bootstrap_samples: int = 10_000
    seed: int = 20260718
    prior_research_trial_count: int = 127

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
                "feature_names": list(ONCHAIN_MODEL_FEATURE_NAMES),
                "selection": "one retained on-chain feature added to the fixed rolling RF baseline",
                "source_vintage": "latest_available_response_not_historical_vintage",
                "paper_or_live_allowed": False,
            }
        )


def augment_dataset_with_hashrate(
    dataset: Mapping[str, Any], onchain_dataset: Mapping[str, Any]
) -> dict[str, Any]:
    by_date = {
        str(row["decision_date"]): float(row[ONCHAIN_MODEL_FEATURE])
        for row in onchain_dataset["daily_features"]
    }
    rows = [
        {
            **row,
            "features": {
                **row["features"],
                ONCHAIN_MODEL_FEATURE: by_date[row["decision_date"]],
            },
        }
        for row in dataset["rows"]
        if row["decision_date"] in by_date
    ]
    coverage = len(rows) / len(dataset["rows"]) if dataset["rows"] else 0.0
    contract = {
        **dataset["contract"],
        "feature_names": list(ONCHAIN_MODEL_FEATURE_NAMES),
        "onchain_feature": ONCHAIN_MODEL_FEATURE,
        "onchain_feature_lag_days": onchain_dataset["contract"]["decision_lag_days"],
        "onchain_source_vintage": "latest_available_response_not_historical_vintage",
        "base_contract_hash": dataset["contract"]["contract_hash"],
        "onchain_contract_hash": onchain_dataset["contract"]["contract_hash"],
        "feature_coverage": coverage,
    }
    contract["contract_hash"] = canonical_hash(contract)
    return {
        **dataset,
        "contract": contract,
        "rows": rows,
        "data_hash": canonical_hash(
            {
                "contract_hash": contract["contract_hash"],
                "onchain_data_hash": onchain_dataset["data_hash"],
                "rows": rows,
            }
        ),
        "onchain_feature_coverage": coverage,
    }


def build_onchain_model_ablation(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    onchain_dataset: Mapping[str, Any],
    onchain_audit: Mapping[str, Any],
    source_matrix: Mapping[str, Any],
    config: OnchainModelConfig | None = None,
) -> dict[str, Any]:
    config = config or OnchainModelConfig()
    if onchain_audit.get("retained_trial_ids") != [config.required_feature_trial_id]:
        raise ValueError("on-chain feature audit did not retain only the fixed hash-rate feature")
    source_trial = next(
        row for row in source_matrix["trials"] if row["trial_id"] == config.source_candidate_id
    )
    base_dataset = build_regime_ml_dataset(
        bars_by_symbol,
        funding_by_symbol,
        RegimeMLConfig(
            start_date=config.start_date,
            end_date=config.end_date,
            horizon_days=config.horizon_days,
            barrier_sigma=1.0,
            trial_count=source_matrix["diagnostics"]["trial_count"],
            seed=config.seed,
        ),
    )
    dataset = augment_dataset_with_hashrate(base_dataset, onchain_dataset)
    result = run_economic_ml_walk_forward(
        dataset,
        target=config.target,
        model_name=config.model,
        use_gpu=False,
        seed=config.model_seed,
        bootstrap_samples=config.bootstrap_samples,
        feature_names=ONCHAIN_MODEL_FEATURE_NAMES,
        training_window_days=config.training_window_days,
        include_predictions=True,
    )
    fold_2026 = next(row for row in result["folds"] if row["test_year"] == 2026)
    gates = {
        "onchain_feature_coverage_complete": dataset["onchain_feature_coverage"] >= 0.99,
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
        "pooled_rank_ic_not_lower_than_base": (
            result["pooled_rank_ic"] >= source_trial["pooled_rank_ic"]
        ),
        "pooled_spread_not_lower_than_base": (
            result["pooled_high_minus_low_actual"]
            >= source_trial["pooled_high_minus_low_actual"]
        ),
        "bootstrap_probability_not_lower_than_base": (
            result["bootstrap"]["probability_spread_positive"]
            >= source_trial["bootstrap"]["probability_spread_positive"]
        ),
    }
    retained = all(gates.values())
    return {
        "schema_version": ONCHAIN_MODEL_VERSION,
        "artifact_type": "mini_trend_onchain_rolling_model_ablation",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "source_vintage": "latest_available_response_not_historical_vintage",
            "point_in_time_promotion_ready": False,
            "network_download_used_by_source_dataset": True,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "feature_names": list(ONCHAIN_MODEL_FEATURE_NAMES),
            "model_seed": config.model_seed,
            "contract_hash": config.contract_hash,
        },
        "lineage": {
            "source_matrix_hash": canonical_hash(source_matrix),
            "source_candidate_id": source_trial["trial_id"],
            "base_dataset_contract_hash": base_dataset["contract"]["contract_hash"],
            "augmented_dataset_contract_hash": dataset["contract"]["contract_hash"],
            "augmented_dataset_data_hash": dataset["data_hash"],
            "onchain_data_hash": onchain_dataset["data_hash"],
            "onchain_audit_hash": canonical_hash(onchain_audit),
        },
        "source_trial": source_trial,
        "candidate": result,
        "comparison": {
            "pooled_rank_ic_delta": (
                result["pooled_rank_ic"] - source_trial["pooled_rank_ic"]
            ),
            "pooled_spread_delta": (
                result["pooled_high_minus_low_actual"]
                - source_trial["pooled_high_minus_low_actual"]
            ),
            "bootstrap_probability_delta": (
                result["bootstrap"]["probability_spread_positive"]
                - source_trial["bootstrap"]["probability_spread_positive"]
            ),
        },
        "diagnostics": {
            "gates": gates,
            "passed_gate_count": sum(gates.values()),
            "gate_count": len(gates),
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "verdict": (
                "retain_onchain_rolling_ranker_for_strategy_ablation"
                if retained
                else "reject_onchain_rolling_model_ablation"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_onchain_model_ablation_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-onchain-rolling-model-ablation",
        path_key="artifact_path",
        default_filename="mini_trend_onchain_rolling_model_ablation.json",
        explicit_path=explicit_path,
    )
