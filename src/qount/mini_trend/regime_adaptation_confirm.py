"""Fixed robustness confirmation for the retained rolling adaptation ranking signal."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_economic_ml import _bootstrap_spread
from qount.mini_trend.regime_economic_ml import run_economic_ml_walk_forward
from qount.mini_trend.regime_ml import FEATURE_NAMES
from qount.mini_trend.regime_ml import RegimeMLConfig
from qount.mini_trend.regime_ml import build_regime_ml_dataset
from qount.models import utc_now
from qount.settings import Settings


ADAPTATION_CONFIRM_VERSION = "mini_trend_regime_adaptation_confirm_v0.1"


@dataclass(frozen=True)
class AdaptationConfirmConfig:
    candidate_id: str = "h60_train365_base_random_forest"
    horizon_days: int = 60
    training_window_days: int = 365
    model: str = "random_forest"
    target: str = "return"
    bootstrap_samples: int = 10_000
    sensitivity_block_days: tuple[int, ...] = (30, 60, 90)
    sensitivity_minimum_probability: float = 0.75
    seed: int = 20260718
    cumulative_model_trial_count: int = 117

    @property
    def model_seed(self) -> int:
        return self.seed + self.horizon_days * 100 + self.training_window_days

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "model_seed": self.model_seed,
                "selection_source": "fixed retained cell from 24-trial adaptation matrix",
                "new_model_trial": False,
                "promotion_allowed": False,
            }
        )


def build_adaptation_confirmation(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    source_matrix: Mapping[str, Any],
    config: AdaptationConfirmConfig | None = None,
) -> dict[str, Any]:
    config = config or AdaptationConfirmConfig()
    source_trial = next(
        row for row in source_matrix["trials"] if row["trial_id"] == config.candidate_id
    )
    dataset = build_regime_ml_dataset(
        bars_by_symbol,
        funding_by_symbol,
        RegimeMLConfig(
            start_date="2021-07-20",
            end_date="2026-05-31",
            horizon_days=config.horizon_days,
            barrier_sigma=1.0,
            trial_count=source_matrix["diagnostics"]["trial_count"],
            seed=config.seed,
        ),
    )
    result = run_economic_ml_walk_forward(
        dataset,
        target=config.target,
        model_name=config.model,
        use_gpu=False,
        seed=config.model_seed,
        bootstrap_samples=config.bootstrap_samples,
        feature_names=FEATURE_NAMES,
        training_window_days=config.training_window_days,
        include_predictions=True,
    )
    predictions = result["prediction_rows"]
    sensitivity = {
        str(block_days): _bootstrap_spread(
            predictions,
            block_days=block_days,
            samples=config.bootstrap_samples,
            seed=config.model_seed + block_days,
        )
        for block_days in config.sensitivity_block_days
    }
    source_matches = all(
        abs(float(result[key]) - float(source_trial[key])) <= 1e-12
        for key in ("pooled_rank_ic", "pooled_high_minus_low_actual")
    ) and result["positive_rank_ic_fold_count"] == source_trial["positive_rank_ic_fold_count"]
    fold_2026 = next(row for row in result["folds"] if row["test_year"] == 2026)
    gates = {
        "source_candidate_fixed": source_matrix["retained_trial_ids"] == [config.candidate_id],
        "deterministic_rerun_matches_source": source_matches,
        "positive_rank_ic_in_three_folds": result["positive_rank_ic_fold_count"] >= 3,
        "positive_spread_in_three_folds": result["positive_spread_fold_count"] >= 3,
        "positive_2026_rank_ic_and_spread": fold_2026["rank_ic"] > 0
        and fold_2026["high_minus_low_actual"] > 0,
        "all_block_sensitivity_probabilities_at_least_75pct": all(
            row["probability_spread_positive"] >= config.sensitivity_minimum_probability
            for row in sensitivity.values()
        ),
        "all_block_sensitivity_median_spreads_positive": all(
            row["median_spread"] > 0 for row in sensitivity.values()
        ),
    }
    supported = all(gates.values())
    return {
        "schema_version": ADAPTATION_CONFIRM_VERSION,
        "artifact_type": "mini_trend_regime_adaptation_confirmation",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "new_model_trial": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "model_seed": config.model_seed,
            "contract_hash": config.contract_hash,
        },
        "lineage": {
            "source_matrix_hash": canonical_hash(source_matrix),
            "source_matrix_contract_hash": source_matrix["contract"]["contract_hash"],
            "dataset_contract_hash": dataset["contract"]["contract_hash"],
            "dataset_data_hash": dataset["data_hash"],
        },
        "source_trial": source_trial,
        "confirmation_result": result,
        "bootstrap_sensitivity": sensitivity,
        "diagnostics": {
            "gates": gates,
            "passed_gate_count": sum(gates.values()),
            "gate_count": len(gates),
            "verdict": (
                "retain_rolling_return_ranker_for_strategy_ablation"
                if supported
                else "reject_rolling_return_ranker_after_confirmation"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_adaptation_confirmation_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-regime-adaptation-confirm",
        path_key="artifact_path",
        default_filename="mini_trend_regime_adaptation_confirm.json",
        explicit_path=explicit_path,
    )
