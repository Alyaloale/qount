"""Direct economic-target ML matrix for MiniTrend consumed-history research."""

from __future__ import annotations

import datetime as dt
import math
import random
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.regime_ml import FEATURE_NAMES
from qount.mini_trend.regime_ml import RegimeMLConfig
from qount.mini_trend.regime_ml import build_regime_ml_dataset
from qount.models import utc_now
from qount.settings import Settings


ECONOMIC_ML_VERSION = "mini_trend_regime_economic_ml_matrix_v0.2"
TARGET_FIELDS = {
    "return": "forward_return_horizon",
    "drawdown": "forward_path_max_drawdown",
}


@dataclass(frozen=True)
class EconomicMLConfig:
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    horizons: tuple[int, ...] = (10, 20, 30, 60)
    targets: tuple[str, ...] = ("return", "drawdown")
    models: tuple[str, ...] = (
        "ridge",
        "hist_gb",
        "random_forest",
        "lightgbm",
        "xgboost",
    )
    bootstrap_samples: int = 1_000
    seed: int = 20260718
    prior_family_trial_count: int = 13

    @property
    def trial_count(self) -> int:
        return len(self.horizons) * len(self.targets) * len(self.models)

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
                "features": list(FEATURE_NAMES),
                "split": "expanding annual folds purged on full horizon_end_date",
                "selection": "no hyperparameter search; fixed model definitions",
                "cross_fold_score_normalization": (
                    "test prediction minus train-prediction mean, divided by train-prediction std"
                ),
                "promotion_allowed": False,
            }
        )


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _rank(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(float(value) for value in values), key=lambda row: row[1])
    ranks = [0.0] * len(indexed)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average = (start + end - 1) / 2.0
        for offset in range(start, end):
            ranks[indexed[offset][0]] = average
        start = end
    return ranks


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean, right_mean = _mean(left), _mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    )
    return numerator / denominator if denominator > 0 else 0.0


def _spearman(left: Sequence[float], right: Sequence[float]) -> float:
    return _correlation(_rank(left), _rank(right))


def _rmse(actual: Sequence[float], predicted: Sequence[float]) -> float:
    return math.sqrt(_mean([(x - y) ** 2 for x, y in zip(actual, predicted)]))


def _mae(actual: Sequence[float], predicted: Sequence[float]) -> float:
    return _mean([abs(x - y) for x, y in zip(actual, predicted)])


def _quintile_spread(actual: Sequence[float], predicted: Sequence[float]) -> float:
    ordered = sorted(zip(predicted, actual), key=lambda row: row[0])
    count = max(len(ordered) // 5, 1)
    return _mean([row[1] for row in ordered[-count:]]) - _mean(
        [row[1] for row in ordered[:count]]
    )


def _bootstrap_spread(
    rows: Sequence[Mapping[str, float]], *, block_days: int, samples: int, seed: int
) -> dict[str, Any]:
    predicted = [float(row["predicted"]) for row in rows]
    low_threshold = _percentile(predicted, 0.2)
    high_threshold = _percentile(predicted, 0.8)
    rng = random.Random(seed)
    spreads = []
    count = len(rows)
    for _ in range(samples):
        sampled: list[Mapping[str, float]] = []
        while len(sampled) < count:
            start = rng.randrange(count)
            sampled.extend(rows[(start + offset) % count] for offset in range(block_days))
        sampled = sampled[:count]
        low = [float(row["actual"]) for row in sampled if row["predicted"] <= low_threshold]
        high = [float(row["actual"]) for row in sampled if row["predicted"] >= high_threshold]
        if low and high:
            spreads.append(_mean(high) - _mean(low))
    return {
        "block_days": block_days,
        "samples_completed": len(spreads),
        "median_spread": _percentile(spreads, 0.5),
        "p05_spread": _percentile(spreads, 0.05),
        "p95_spread": _percentile(spreads, 0.95),
        "probability_spread_positive": _mean([float(value > 0) for value in spreads]),
    }


def _model_factory(name: str, seed: int, *, use_gpu: bool):
    if name == "ridge":
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        return make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    if name == "hist_gb":
        from sklearn.ensemble import HistGradientBoostingRegressor

        return HistGradientBoostingRegressor(
            learning_rate=0.05,
            max_iter=200,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=seed,
        )
    if name == "random_forest":
        from sklearn.ensemble import RandomForestRegressor

        return RandomForestRegressor(
            n_estimators=400,
            max_depth=6,
            min_samples_leaf=20,
            max_features=0.7,
            n_jobs=16,
            random_state=seed,
        )
    if name == "lightgbm":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            n_estimators=300,
            learning_rate=0.03,
            num_leaves=15,
            max_depth=5,
            min_child_samples=30,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            n_jobs=16,
            random_state=seed,
            verbosity=-1,
        )
    if name == "xgboost":
        from xgboost import XGBRegressor

        return XGBRegressor(
            n_estimators=300,
            learning_rate=0.03,
            max_depth=3,
            min_child_weight=10,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            n_jobs=16,
            random_state=seed,
            tree_method="hist",
            device="cuda" if use_gpu else "cpu",
        )
    raise ValueError(f"unknown economic model: {name}")


def run_economic_ml_walk_forward(
    dataset: Mapping[str, Any],
    *,
    target: str,
    model_name: str,
    use_gpu: bool,
    seed: int,
    bootstrap_samples: int,
    feature_names: Sequence[str] = FEATURE_NAMES,
    training_window_days: int | None = None,
    include_predictions: bool = False,
) -> dict[str, Any]:
    import numpy as np

    if target not in TARGET_FIELDS:
        raise ValueError(f"unknown economic target: {target}")
    target_field = TARGET_FIELDS[target]
    rows = list(dataset["rows"])
    test_years = tuple(dataset["contract"]["test_years"])
    fold_rows = []
    predictions: list[dict[str, float | str | int]] = []
    for test_year in test_years:
        test_start = dt.date(test_year, 1, 1)
        test_end = dt.date(test_year, 12, 31)
        train_start = (
            test_start - dt.timedelta(days=training_window_days)
            if training_window_days is not None
            else None
        )
        train = [
            row
            for row in rows
            if dt.date.fromisoformat(row["horizon_end_date"]) < test_start
            and (
                train_start is None
                or dt.date.fromisoformat(row["decision_date"]) >= train_start
            )
        ]
        test = [
            row
            for row in rows
            if test_start <= dt.date.fromisoformat(row["decision_date"]) <= test_end
        ]
        if not train or not test:
            continue
        x_train = np.asarray(
            [[float(row["features"][name]) for name in feature_names] for row in train],
            dtype=float,
        )
        y_train = np.asarray([float(row[target_field]) for row in train], dtype=float)
        x_test = np.asarray(
            [[float(row["features"][name]) for name in feature_names] for row in test],
            dtype=float,
        )
        actual = [float(row[target_field]) for row in test]
        model = _model_factory(model_name, seed + test_year, use_gpu=use_gpu)
        model.fit(x_train, y_train)
        train_predicted = [float(value) for value in model.predict(x_train)]
        predicted = [float(value) for value in model.predict(x_test)]
        prediction_mean = _mean(train_predicted)
        prediction_std = statistics.stdev(train_predicted) if len(train_predicted) > 1 else 0.0
        normalized_predicted = [
            (value - prediction_mean) / prediction_std if prediction_std > 0 else 0.0
            for value in predicted
        ]
        constant = [float(np.mean(y_train))] * len(test)
        fold_rows.append(
            {
                "test_year": test_year,
                "train_rows": len(train),
                "test_rows": len(test),
                "train_last_horizon_end_date": max(row["horizon_end_date"] for row in train),
                "test_first_date": test[0]["decision_date"],
                "purge_check_passed": max(row["horizon_end_date"] for row in train)
                < test[0]["decision_date"],
                "rmse": _rmse(actual, predicted),
                "constant_rmse": _rmse(actual, constant),
                "rmse_improvement_vs_constant": _rmse(actual, constant)
                - _rmse(actual, predicted),
                "mae": _mae(actual, predicted),
                "constant_mae": _mae(actual, constant),
                "mae_improvement_vs_constant": _mae(actual, constant)
                - _mae(actual, predicted),
                "train_prediction_mean": prediction_mean,
                "train_prediction_std": prediction_std,
                "rank_ic": _spearman(normalized_predicted, actual),
                "high_minus_low_actual": _quintile_spread(actual, normalized_predicted),
            }
        )
        predictions.extend(
            {
                "decision_date": row["decision_date"],
                "test_year": test_year,
                "predicted": forecast,
                "raw_predicted": raw_forecast,
                "actual": outcome,
            }
            for row, forecast, raw_forecast, outcome in zip(
                test, normalized_predicted, predicted, actual
            )
        )
    actual = [float(row["actual"]) for row in predictions]
    predicted = [float(row["predicted"]) for row in predictions]
    bootstrap = _bootstrap_spread(
        predictions,
        block_days=int(dataset["contract"]["horizon_days"]),
        samples=bootstrap_samples,
        seed=seed,
    )
    ranking_gates = {
        "all_horizon_purge_checks_passed": bool(fold_rows)
        and all(row["purge_check_passed"] for row in fold_rows),
        "pooled_rank_ic_above_005": _spearman(predicted, actual) > 0.05,
        "positive_rank_ic_in_three_folds": sum(row["rank_ic"] > 0 for row in fold_rows) >= 3,
        "positive_quintile_spread_in_three_folds": sum(
            row["high_minus_low_actual"] > 0 for row in fold_rows
        )
        >= 3,
        "block_bootstrap_spread_probability_at_least_80pct": bootstrap[
            "probability_spread_positive"
        ]
        >= 0.8,
    }
    amplitude_gate = _mean(
        [row["rmse_improvement_vs_constant"] for row in fold_rows]
    ) > 0
    gates = {
        **ranking_gates,
        "mean_rmse_improvement_positive": amplitude_gate,
    }
    ranking_supported = all(ranking_gates.values())
    result = {
        "target": target,
        "target_field": target_field,
        "model": model_name,
        "feature_count": len(feature_names),
        "training_window_days": training_window_days,
        "rows": len(predictions),
        "conservative_effective_rows": math.ceil(
            len(predictions) / int(dataset["contract"]["horizon_days"])
        ),
        "folds": fold_rows,
        "mean_rmse_improvement_vs_constant": _mean(
            [row["rmse_improvement_vs_constant"] for row in fold_rows]
        ),
        "mean_mae_improvement_vs_constant": _mean(
            [row["mae_improvement_vs_constant"] for row in fold_rows]
        ),
        "pooled_rank_ic": _spearman(predicted, actual),
        "pooled_high_minus_low_actual": _quintile_spread(actual, predicted),
        "positive_rank_ic_fold_count": sum(row["rank_ic"] > 0 for row in fold_rows),
        "positive_spread_fold_count": sum(
            row["high_minus_low_actual"] > 0 for row in fold_rows
        ),
        "bootstrap": bootstrap,
        "gates": gates,
        "passed_gate_count": sum(gates.values()),
        "gate_count": len(gates),
        "verdict": (
            "retain_calibrated_economic_model"
            if ranking_supported and amplitude_gate
            else "retain_economic_ranking_signal"
            if ranking_supported
            else "reject_economic_model"
        ),
    }
    if include_predictions:
        result["prediction_rows"] = predictions
    return result


def _ranking_key(row: Mapping[str, Any]) -> tuple[float, ...]:
    return (
        float(row["passed_gate_count"]),
        float(row["positive_rank_ic_fold_count"]),
        float(row["bootstrap"]["probability_spread_positive"]),
        float(row["mean_rmse_improvement_vs_constant"]),
    )


def build_economic_ml_matrix(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    config: EconomicMLConfig | None = None,
    *,
    use_gpu: bool = False,
) -> dict[str, Any]:
    config = config or EconomicMLConfig()
    trials = []
    data_hashes = {}
    for horizon in config.horizons:
        dataset = build_regime_ml_dataset(
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
        data_hashes[str(horizon)] = {
            "contract_hash": dataset["contract"]["contract_hash"],
            "data_hash": dataset["data_hash"],
        }
        for target in config.targets:
            for model_name in config.models:
                trial = run_economic_ml_walk_forward(
                    dataset,
                    target=target,
                    model_name=model_name,
                    use_gpu=use_gpu,
                    seed=config.seed + horizon * 100 + config.models.index(model_name),
                    bootstrap_samples=config.bootstrap_samples,
                )
                trial["trial_id"] = f"h{horizon}_{target}_{model_name}"
                trial["horizon_days"] = horizon
                trials.append(trial)
    ranked = sorted(trials, key=_ranking_key, reverse=True)
    retained = [row for row in ranked if row["verdict"].startswith("retain_")]
    return {
        "schema_version": ECONOMIC_ML_VERSION,
        "artifact_type": "mini_trend_regime_economic_ml_matrix",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "network_download_used": False,
            "gpu_requested": use_gpu,
            "paper_or_live_allowed": False,
        },
        "contract": {
            **asdict(config),
            "trial_count": config.trial_count,
            "cumulative_trial_count": config.cumulative_trial_count,
            "contract_hash": config.contract_hash,
        },
        "data_lineage": data_hashes,
        "trials": trials,
        "ranking": [row["trial_id"] for row in ranked],
        "best_by_target": {
            target: next((row for row in ranked if row["target"] == target), None)
            for target in config.targets
        },
        "retained_trial_ids": [row["trial_id"] for row in retained],
        "diagnostics": {
            "trial_count": len(trials),
            "cumulative_trial_count": config.cumulative_trial_count,
            "retained_trial_count": len(retained),
            "verdict": (
                "retain_direct_economic_models_for_ablation"
                if retained
                else "reject_direct_economic_model_matrix"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_economic_ml_matrix_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-regime-economic-ml-matrix",
        path_key="artifact_path",
        default_filename="mini_trend_regime_economic_ml_matrix.json",
        explicit_path=explicit_path,
    )
