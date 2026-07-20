"""Rolling-window adaptation matrix after expanding-window economic ML failure."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_dvol_ml import ALL_DVOL_FEATURE_NAMES
from qount.mini_trend.regime_dvol_ml import augment_dataset_with_dvol
from qount.mini_trend.regime_economic_ml import _ranking_key
from qount.mini_trend.regime_economic_ml import run_economic_ml_walk_forward
from qount.mini_trend.regime_ml import FEATURE_NAMES
from qount.mini_trend.regime_ml import RegimeMLConfig
from qount.mini_trend.regime_ml import build_regime_ml_dataset
from qount.models import utc_now
from qount.settings import Settings


ADAPTATION_MATRIX_VERSION = "mini_trend_regime_adaptation_matrix_v0.1"


@dataclass(frozen=True)
class AdaptationMatrixConfig:
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    horizons: tuple[int, ...] = (10, 20, 30, 60)
    training_windows_days: tuple[int, ...] = (365, 730, 1095)
    feature_sets: tuple[str, ...] = ("base", "dvol")
    model: str = "random_forest"
    target: str = "return"
    bootstrap_samples: int = 1_000
    seed: int = 20260718
    prior_family_trial_count: int = 93

    @property
    def trial_count(self) -> int:
        return len(self.horizons) * len(self.training_windows_days) * len(self.feature_sets)

    @property
    def cumulative_trial_count(self) -> int:
        return self.prior_family_trial_count + self.trial_count

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "trial_count": self.trial_count,
                "cumulative_trial_count": self.cumulative_trial_count,
                "reason": "test whether stale expanding history caused 2026 sign reversal",
                "promotion_allowed": False,
            }
        )


def build_adaptation_matrix(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    dvol_payload: Mapping[str, Any],
    config: AdaptationMatrixConfig | None = None,
) -> dict[str, Any]:
    config = config or AdaptationMatrixConfig()
    trials = []
    lineage = {}
    for horizon in config.horizons:
        base_dataset = build_regime_ml_dataset(
            bars_by_symbol,
            funding_by_symbol,
            RegimeMLConfig(
                start_date=config.start_date,
                end_date=config.end_date,
                horizon_days=horizon,
                barrier_sigma=1.0,
                trial_count=config.trial_count,
                seed=config.seed,
            ),
        )
        dvol_dataset = augment_dataset_with_dvol(base_dataset, dvol_payload)
        datasets = {"base": base_dataset, "dvol": dvol_dataset}
        names = {"base": FEATURE_NAMES, "dvol": ALL_DVOL_FEATURE_NAMES}
        lineage[str(horizon)] = {
            feature_set: {
                "contract_hash": datasets[feature_set]["contract"]["contract_hash"],
                "data_hash": datasets[feature_set]["data_hash"],
                "rows": len(datasets[feature_set]["rows"]),
            }
            for feature_set in config.feature_sets
        }
        for feature_set in config.feature_sets:
            for training_window in config.training_windows_days:
                trial = run_economic_ml_walk_forward(
                    datasets[feature_set],
                    target=config.target,
                    model_name=config.model,
                    use_gpu=False,
                    seed=config.seed + horizon * 100 + training_window,
                    bootstrap_samples=config.bootstrap_samples,
                    feature_names=names[feature_set],
                    training_window_days=training_window,
                )
                trial["trial_id"] = (
                    f"h{horizon}_train{training_window}_{feature_set}_{config.model}"
                )
                trial["horizon_days"] = horizon
                trial["feature_set"] = feature_set
                trials.append(trial)
    ranked = sorted(trials, key=_ranking_key, reverse=True)
    retained = [row for row in ranked if row["verdict"].startswith("retain_")]
    return {
        "schema_version": ADAPTATION_MATRIX_VERSION,
        "artifact_type": "mini_trend_regime_adaptation_matrix",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "network_download_used": False,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "contract_hash": config.contract_hash,
        },
        "data_lineage": lineage,
        "dvol_data_hash": dvol_payload["meta"]["data_hash"],
        "trials": trials,
        "ranking": [row["trial_id"] for row in ranked],
        "best_trial": dict(ranked[0]) if ranked else None,
        "retained_trial_ids": [row["trial_id"] for row in retained],
        "diagnostics": {
            "trial_count": len(trials),
            "cumulative_trial_count": config.cumulative_trial_count,
            "retained_trial_count": len(retained),
            "verdict": (
                "retain_rolling_adaptation_candidates"
                if retained
                else "reject_rolling_adaptation_matrix"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_adaptation_matrix_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-regime-adaptation-matrix",
        path_key="artifact_path",
        default_filename="mini_trend_regime_adaptation_matrix.json",
        explicit_path=explicit_path,
    )
