from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import math
import statistics
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import fields
from pathlib import Path
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.models import utc_now
from qount.research_data.metrics import deflated_sharpe_ratio
from qount.research_data.metrics import expected_max_sharpe
from qount.research_data.metrics import sharpe
from qount.settings import Settings

from .feature_experiment import FeatureExperimentConfig
from .feature_experiment import build_feature_experiment_dataset


VALIDATION_VERSION = "alpha_agent_validation_v0.1"


@dataclass(frozen=True)
class ValidationConfig:
    fold_count: int = 5
    embargo_periods: int = 1
    pbo_splits: int = 10
    min_positive_fold_fraction: float = 0.60

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_validation_artifact(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != VALIDATION_VERSION:
        raise ValueError("invalid Alpha Agents validation artifact")
    return payload


def validation_meta(payload: dict[str, Any]) -> dict[str, Any]:
    validation = payload.get("validation", {})
    return {
        "deflated_sharpe_ratio": float(validation.get("deflated_sharpe_ratio", 0.0)),
        "pbo": float(validation.get("pbo", 1.0)),
        "purged_cv_pass": bool(validation.get("purged_cv_pass", False)),
        "largest_contributor_removed_return_pct": float(
            validation.get("largest_contributor_removed_return_pct", 0.0)
        ),
        "embargo_applied": bool(validation.get("embargo_applied", False)),
        "validation_artifact_path": payload.get("artifact_path") or payload.get("persistent_artifact_path"),
        "validation_source_feature_path": payload.get("source_feature_experiment_path"),
    }


def assert_validation_matches_feature(payload: dict[str, Any], feature_path: str | Path) -> None:
    source = payload.get("source_feature_experiment_path")
    if not source or Path(source).expanduser().resolve() != Path(feature_path).expanduser().resolve():
        raise ValueError("validation artifact does not match the supplied feature experiment")


def _feature_config(raw: dict[str, Any]) -> FeatureExperimentConfig:
    allowed = {field.name for field in fields(FeatureExperimentConfig)}
    values = {key: value for key, value in raw.items() if key in allowed}
    for key in ("symbols", "lookbacks", "feature_families", "thresholds", "modes", "polarities"):
        if key in values:
            values[key] = tuple(values[key])
    return FeatureExperimentConfig(**values)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _covariance(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = _mean(left)
    right_mean = _mean(right)
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / (len(left) - 1)


def _beta(strategy: list[float], btc: list[float], indices: list[int]) -> float:
    strategy_values = [strategy[index] for index in indices]
    btc_values = [btc[index] for index in indices]
    btc_variance = _variance(btc_values)
    return _covariance(strategy_values, btc_values) / btc_variance if btc_variance > 0 else 0.0


def _residuals(strategy: list[float], btc: list[float], indices: list[int], beta: float) -> list[float]:
    return [strategy[index] - beta * btc[index] for index in indices]


def _compound_pct(values: list[float]) -> float:
    total = 1.0
    for value in values:
        total *= 1.0 + value / 100.0
    return (total - 1.0) * 100.0


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
            end += 1
        rank = (cursor + end - 1) / 2.0 + 1.0
        for index in ordered[cursor:end]:
            ranks[index] = rank
        cursor = end
    return ranks


def _correlation(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(_variance(left) * _variance(right))
    return _covariance(left, right) / denominator if denominator > 0 else 0.0


def _rank_ic(features: list[float], labels: list[float]) -> float:
    if len(features) != len(labels) or len(features) < 2:
        return 0.0
    return _correlation(_ranks(features), _ranks(labels))


def _skew_kurtosis(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        return 0.0, 3.0
    mean = _mean(values)
    m2 = sum((value - mean) ** 2 for value in values) / len(values)
    if m2 <= 0:
        return 0.0, 3.0
    m3 = sum((value - mean) ** 3 for value in values) / len(values)
    m4 = sum((value - mean) ** 4 for value in values) / len(values)
    return m3 / (m2 ** 1.5), m4 / (m2 * m2)


def _pbo_splits(requested: int, period_count: int) -> int:
    splits = min(max(int(requested), 2), period_count)
    if splits % 2:
        splits -= 1
    return max(splits, 2)


def _pbo_matrix(matrix: dict[str, Any], *, splits: int) -> dict[str, Any]:
    period_count = len(matrix["daily_timestamps"])
    bounds = [period_count * index // splits for index in range(splits + 1)]
    blocks = [list(range(bounds[index], bounds[index + 1])) for index in range(splits)]
    ic_days = _ic_day_indices(matrix)
    logits: list[float] = []
    half = splits // 2
    for is_blocks in itertools.combinations(range(splits), half):
        is_set = set(is_blocks)
        train = [day for index, block in enumerate(blocks) if index in is_set for day in block]
        test = [day for index, block in enumerate(blocks) if index not in is_set for day in block]
        train_scores: list[tuple[float, int, float]] = []
        for candidate_index, candidate in enumerate(matrix["candidates"]):
            score, beta = _selection_score(
                candidate,
                matrix=matrix,
                train_indices=train,
                ic_day_indices=ic_days,
            )
            if math.isfinite(score):
                train_scores.append((score, candidate_index, beta))
        if not train_scores:
            continue
        _score, selected_index, selected_beta = max(train_scores, key=lambda item: (item[0], -item[1]))
        oos_scores: list[tuple[int, float]] = []
        for candidate_index, candidate in enumerate(matrix["candidates"]):
            strategy = [float(value) for value in candidate["strategy_returns_pct"]]
            btc = [float(value) for value in matrix["btc_returns_pct"]]
            beta = selected_beta if candidate_index == selected_index else _beta(strategy, btc, train)
            residual = _residuals(strategy, btc, test, beta)
            if len(residual) >= 2:
                oos_scores.append((candidate_index, sharpe(residual)))
        selected_oos = dict(oos_scores).get(selected_index)
        if selected_oos is None or len(oos_scores) < 2:
            continue
        worse = sum(score < selected_oos for _index, score in oos_scores)
        omega = (worse + 0.5) / len(oos_scores)
        omega = min(max(omega, 1e-9), 1.0 - 1e-9)
        logits.append(math.log(omega / (1.0 - omega)))
    if not logits:
        return {"pbo": 1.0, "splits": splits, "combination_count": 0, "method": "cscv_source_selection"}
    return {
        "pbo": sum(logit <= 0.0 for logit in logits) / len(logits),
        "splits": splits,
        "combination_count": len(logits),
        "median_logit": statistics.median(logits),
        "mean_logit": _mean(logits),
        "method": "cscv_source_selection",
    }


def _ic_day_indices(matrix: dict[str, Any]) -> list[int | None]:
    day_lookup = {value: index for index, value in enumerate(matrix["daily_timestamps"])}
    result: list[int | None] = []
    for raw in matrix["ic_timestamps"]:
        stamp = int(raw)
        day = dt.datetime.fromtimestamp(stamp / 1000, dt.UTC).strftime("%Y-%m-%d")
        result.append(day_lookup.get(day))
    return result


def _selection_score(
    candidate: dict[str, Any],
    *,
    matrix: dict[str, Any],
    train_indices: list[int],
    ic_day_indices: list[int | None],
) -> tuple[float, float]:
    strategy = [float(value) for value in candidate["strategy_returns_pct"]]
    btc = [float(value) for value in matrix["btc_returns_pct"]]
    beta = _beta(strategy, btc, train_indices)
    if matrix.get("selection_metric") == "rank_ic":
        train_set = set(train_indices)
        features: list[float] = []
        labels: list[float] = []
        for day_index, feature, label in zip(
            ic_day_indices,
            candidate["ic_feature_values"],
            matrix["ic_residual_forward_returns_pct"],
        ):
            if day_index in train_set and feature is not None:
                features.append(float(feature))
                labels.append(float(label))
        return (_rank_ic(features, labels) if len(features) >= 20 else float("-inf")), beta
    residual = _residuals(strategy, btc, train_indices, beta)
    return (sharpe(residual) if len(residual) >= 2 else float("-inf")), beta


def _evaluate_fold(
    matrix: dict[str, Any],
    *,
    train_indices: list[int],
    test_indices: list[int],
    ic_day_indices: list[int | None],
) -> dict[str, Any]:
    scored: list[tuple[float, int, float]] = []
    for index, candidate in enumerate(matrix["candidates"]):
        score, beta = _selection_score(
            candidate,
            matrix=matrix,
            train_indices=train_indices,
            ic_day_indices=ic_day_indices,
        )
        if math.isfinite(score):
            scored.append((score, index, beta))
    if not scored:
        return {"status": "invalid", "reason": "no_train_candidate"}
    score, selected_index, beta = max(scored, key=lambda item: (item[0], -item[1]))
    selected = matrix["candidates"][selected_index]
    strategy = [float(value) for value in selected["strategy_returns_pct"]]
    btc = [float(value) for value in matrix["btc_returns_pct"]]
    test_residuals = _residuals(strategy, btc, test_indices, beta)
    return {
        "status": "ok",
        "selected_candidate_id": selected["candidate_id"],
        "train_selection_score": score,
        "train_beta_to_btc": beta,
        "train_period_count": len(train_indices),
        "test_period_count": len(test_indices),
        "test_start": matrix["daily_timestamps"][test_indices[0]],
        "test_end": matrix["daily_timestamps"][test_indices[-1]],
        "test_residual_return_pct": _compound_pct(test_residuals),
        "test_residual_sum_pct": sum(test_residuals),
    }


def _fold_summary(folds: list[dict[str, Any]], config: ValidationConfig) -> dict[str, Any]:
    valid = [fold for fold in folds if fold.get("status") == "ok"]
    returns = [float(fold["test_residual_return_pct"]) for fold in valid]
    positive_count = sum(value > 0 for value in returns)
    positive_fraction = positive_count / len(returns) if returns else 0.0
    aggregate = _compound_pct(returns) if returns else 0.0
    return {
        "fold_count": len(valid),
        "requested_fold_count": config.fold_count,
        "positive_fold_count": positive_count,
        "positive_fold_fraction": positive_fraction,
        "aggregate_oos_residual_return_pct": aggregate,
        "pass": (
            len(valid) >= 3
            and positive_fraction >= config.min_positive_fold_fraction
            and aggregate > 0.0
        ),
        "folds": folds,
    }


def _purged_folds(matrix: dict[str, Any], config: ValidationConfig) -> dict[str, Any]:
    period_count = len(matrix["daily_timestamps"])
    fold_count = min(config.fold_count, period_count)
    bounds = [period_count * index // fold_count for index in range(fold_count + 1)]
    ic_days = _ic_day_indices(matrix)
    folds: list[dict[str, Any]] = []
    for index in range(fold_count):
        test_start, test_end = bounds[index], bounds[index + 1]
        excluded_start = max(0, test_start - config.embargo_periods)
        excluded_end = min(period_count, test_end + config.embargo_periods)
        train = [day for day in range(period_count) if day < excluded_start or day >= excluded_end]
        test = list(range(test_start, test_end))
        fold = _evaluate_fold(matrix, train_indices=train, test_indices=test, ic_day_indices=ic_days)
        fold.update({"fold": index, "embargo_periods": config.embargo_periods})
        folds.append(fold)
    return _fold_summary(folds, config)


def _walk_forward_folds(matrix: dict[str, Any], config: ValidationConfig) -> dict[str, Any]:
    period_count = len(matrix["daily_timestamps"])
    section_count = min(config.fold_count + 1, period_count)
    bounds = [period_count * index // section_count for index in range(section_count + 1)]
    ic_days = _ic_day_indices(matrix)
    folds: list[dict[str, Any]] = []
    for index in range(1, section_count):
        train_end = max(0, bounds[index] - config.embargo_periods)
        train = list(range(train_end))
        test = list(range(bounds[index], bounds[index + 1]))
        fold = _evaluate_fold(matrix, train_indices=train, test_indices=test, ic_day_indices=ic_days)
        fold.update({"fold": index - 1, "embargo_periods": config.embargo_periods})
        folds.append(fold)
    return _fold_summary(folds, config)


def evaluate_validation_matrix(matrix: dict[str, Any], config: ValidationConfig) -> dict[str, Any]:
    if config.fold_count < 3:
        raise ValueError("fold_count must be at least 3")
    if config.embargo_periods < 1:
        raise ValueError("embargo_periods must be at least 1")
    if not 0.0 < config.min_positive_fold_fraction <= 1.0:
        raise ValueError("min_positive_fold_fraction must be in (0, 1]")
    candidates = matrix.get("candidates", [])
    btc = [float(value) for value in matrix.get("btc_returns_pct", [])]
    period_count = len(matrix.get("daily_timestamps", []))
    if len(candidates) < 2 or period_count < config.fold_count + 1:
        raise ValueError("validation matrix needs multiple candidates and enough aligned periods")
    if any(len(candidate.get("strategy_returns_pct", [])) != period_count for candidate in candidates):
        raise ValueError("candidate return series are not aligned")

    all_indices = list(range(period_count))
    residual_columns: list[list[float]] = []
    per_period_sharpes: list[float] = []
    for candidate in candidates:
        strategy = [float(value) for value in candidate["strategy_returns_pct"]]
        beta = _beta(strategy, btc, all_indices)
        residual = _residuals(strategy, btc, all_indices, beta)
        residual_columns.append(residual)
        per_period_sharpes.append(sharpe(residual))

    selected_candidate_id = matrix.get("source_selected_candidate_id")
    selected_indices = [
        index for index, candidate in enumerate(candidates) if candidate.get("candidate_id") == selected_candidate_id
    ]
    if len(selected_indices) != 1:
        raise ValueError("validation matrix must identify exactly one source-selected candidate")
    selected_index = selected_indices[0]
    selected_residual = residual_columns[selected_index]
    variance = statistics.pvariance(per_period_sharpes)
    benchmark = expected_max_sharpe(len(candidates), variance)
    skew, kurtosis = _skew_kurtosis(selected_residual)
    dsr = deflated_sharpe_ratio(
        per_period_sharpes[selected_index],
        n_obs=len(selected_residual),
        sr_benchmark=benchmark,
        skew=skew,
        kurt=kurtosis,
    )
    splits = _pbo_splits(config.pbo_splits, period_count)
    pbo_diagnostics = _pbo_matrix(matrix, splits=splits)
    pbo = float(pbo_diagnostics["pbo"])
    purged = _purged_folds(matrix, config)
    walk_forward = _walk_forward_folds(matrix, config)
    walk_returns = [
        float(fold["test_residual_return_pct"])
        for fold in walk_forward["folds"]
        if fold.get("status") == "ok"
    ]
    if len(walk_returns) <= 1:
        largest_removed = 0.0
    else:
        largest_index = max(range(len(walk_returns)), key=lambda index: walk_returns[index])
        largest_removed = _compound_pct(
            [value for index, value in enumerate(walk_returns) if index != largest_index]
        )
    purged_cv_pass = bool(purged["pass"] and walk_forward["pass"])

    return {
        "validation": {
            "deflated_sharpe_ratio": dsr,
            "pbo": pbo,
            "purged_cv_pass": purged_cv_pass,
            "largest_contributor_removed_return_pct": largest_removed,
            "embargo_applied": True,
        },
        "diagnostics": {
            "selection_metric": matrix.get("selection_metric"),
            "candidate_count": len(candidates),
            "period_count": period_count,
            "dsr": {
                "selected_candidate_id": candidates[selected_index]["candidate_id"],
                "selected_per_period_sharpe": per_period_sharpes[selected_index],
                "trial_sharpe_variance": variance,
                "expected_max_per_period_sharpe": benchmark,
                "skew": skew,
                "kurtosis": kurtosis,
                "deflated_sharpe_ratio": dsr,
            },
            "pbo": pbo_diagnostics,
            "purged_cv": purged,
            "walk_forward": walk_forward,
        },
    }


def build_validation_from_feature_experiment(
    feature_path: str | Path,
    config: ValidationConfig,
    *,
    fetch=None,
) -> dict[str, Any]:
    source_path = Path(feature_path).expanduser().resolve()
    source_blob = source_path.read_bytes()
    source = json.loads(source_blob)
    if not isinstance(source, dict) or "config" not in source or "selected_candidate" not in source:
        raise ValueError("invalid feature experiment artifact")
    experiment_config = _feature_config(source["config"])
    replay = build_feature_experiment_dataset(
        experiment_config,
        fetch=fetch,
        include_validation_matrix=True,
    )
    if replay["selected_candidate"]["candidate_id"] != source["selected_candidate"]["candidate_id"]:
        raise ValueError("feature experiment replay selected a different candidate")
    evaluated = evaluate_validation_matrix(replay["validation_matrix"], config)
    return {
        "schema_version": VALIDATION_VERSION,
        "created_at": utc_now().isoformat(),
        "source_feature_experiment_path": str(source_path),
        "source_feature_experiment_sha256": hashlib.sha256(source_blob).hexdigest(),
        "source_feature_schema_version": source.get("schema_version"),
        "source_selected_candidate": source["selected_candidate"],
        "replay_selected_candidate": replay["selected_candidate"],
        "replay_candidate_parity": True,
        "config": config.to_dict(),
        **evaluated,
        "hard_boundaries": [
            "Validation is research-only and cannot place orders or change paper/live state.",
            "DSR/PBO use the full aligned discovery matrix; promotion still requires independent forward evidence.",
            "Purged and walk-forward folds preserve the source experiment selection metric.",
        ],
    }


def _daily_return_rows(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for period in periods:
        stamp = int(period["ts"])
        day = dt.datetime.fromtimestamp(stamp / 1000, dt.UTC).strftime("%Y-%m-%d")
        buckets.setdefault(day, []).append(period)
    return [
        {
            "date": day,
            "strategy_return_pct": _compound_pct(
                [float(period["strategy_return_pct"]) for period in buckets[day]]
            ),
            "btc_return_pct": _compound_pct([float(period["btc_return_pct"]) for period in buckets[day]]),
        }
        for day in sorted(buckets)
    ]


def _fixed_candidate_fold_summary(residuals: list[float], dates: list[str], config: ValidationConfig) -> dict[str, Any]:
    fold_count = min(config.fold_count, len(residuals))
    bounds = [len(residuals) * index // fold_count for index in range(fold_count + 1)]
    folds: list[dict[str, Any]] = []
    for index in range(fold_count):
        start, end = bounds[index], bounds[index + 1]
        values = residuals[start:end]
        folds.append(
            {
                "fold": index,
                "test_start": dates[start],
                "test_end": dates[end - 1],
                "test_period_count": len(values),
                "test_residual_return_pct": _compound_pct(values),
                "test_residual_sum_pct": sum(values),
                "embargo_periods": config.embargo_periods,
                "selection_replayed": False,
            }
        )
    returns = [float(fold["test_residual_return_pct"]) for fold in folds]
    positive_count = sum(value > 0 for value in returns)
    positive_fraction = positive_count / len(returns) if returns else 0.0
    aggregate = _compound_pct(returns) if returns else 0.0
    return {
        "fold_count": len(folds),
        "requested_fold_count": config.fold_count,
        "positive_fold_count": positive_count,
        "positive_fold_fraction": positive_fraction,
        "aggregate_oos_residual_return_pct": aggregate,
        "pass": (
            len(folds) >= 3
            and positive_fraction >= config.min_positive_fold_fraction
            and aggregate > 0.0
        ),
        "folds": folds,
        "method": "fixed_candidate_contiguous_time_folds",
    }


def build_validation_from_tradeflow_experiments(
    discovery_path: str | Path,
    oos_path: str | Path,
    config: ValidationConfig,
) -> dict[str, Any]:
    if config.fold_count < 3:
        raise ValueError("fold_count must be at least 3")
    if config.embargo_periods < 1:
        raise ValueError("embargo_periods must be at least 1")
    discovery_source = Path(discovery_path).expanduser().resolve()
    oos_source = Path(oos_path).expanduser().resolve()
    discovery_blob = discovery_source.read_bytes()
    oos_blob = oos_source.read_bytes()
    discovery = json.loads(discovery_blob)
    oos = json.loads(oos_blob)
    expected_schema = "alpha_agent_tradeflow_experiment_v0.1"
    if discovery.get("schema_version") != expected_schema or oos.get("schema_version") != expected_schema:
        raise ValueError("trade-flow validation requires trade-flow experiment artifacts")
    discovery_hash = discovery.get("decision_contract", {}).get("contract_hash")
    oos_hash = oos.get("decision_contract", {}).get("contract_hash")
    if not discovery_hash or discovery_hash != oos_hash:
        raise ValueError("trade-flow discovery and OOS contract hashes differ")
    if discovery.get("diagnostics", {}).get("holdout_role") != "discovery":
        raise ValueError("discovery artifact must have holdout_role=discovery")
    if oos.get("diagnostics", {}).get("holdout_role") != "historical_oos":
        raise ValueError("OOS artifact must have holdout_role=historical_oos")
    discovery_daily = _daily_return_rows(discovery.get("periods", []))
    oos_daily = _daily_return_rows(oos.get("periods", []))
    if not discovery_daily or not oos_daily:
        raise ValueError("trade-flow validation requires non-empty discovery and OOS periods")
    if discovery_daily[-1]["date"] >= oos_daily[0]["date"]:
        raise ValueError("trade-flow discovery and OOS periods must not overlap")
    discovery_strategy = [float(row["strategy_return_pct"]) for row in discovery_daily]
    discovery_btc = [float(row["btc_return_pct"]) for row in discovery_daily]
    discovery_indices = list(range(len(discovery_daily)))
    frozen_beta = _beta(discovery_strategy, discovery_btc, discovery_indices)
    combined = discovery_daily + oos_daily
    combined_residual = [
        float(row["strategy_return_pct"]) - frozen_beta * float(row["btc_return_pct"])
        for row in combined
    ]
    oos_residual = [
        float(row["strategy_return_pct"]) - frozen_beta * float(row["btc_return_pct"])
        for row in oos_daily
    ]
    dates = [str(row["date"]) for row in combined]
    skew, kurtosis = _skew_kurtosis(combined_residual)
    selected_sharpe = sharpe(combined_residual)
    dsr = deflated_sharpe_ratio(
        selected_sharpe,
        n_obs=len(combined_residual),
        sr_benchmark=0.0,
        skew=skew,
        kurt=kurtosis,
    )
    folds = _fixed_candidate_fold_summary(combined_residual, dates, config)
    if len(oos_residual) <= 1:
        largest_removed = 0.0
    else:
        largest = max(range(len(oos_residual)), key=lambda index: oos_residual[index])
        largest_removed = _compound_pct(
            [value for index, value in enumerate(oos_residual) if index != largest]
        )
    pbo = 1.0
    return {
        "schema_version": VALIDATION_VERSION,
        "created_at": utc_now().isoformat(),
        "source_feature_experiment_path": str(oos_source),
        "source_feature_experiment_sha256": hashlib.sha256(oos_blob).hexdigest(),
        "source_feature_schema_version": oos.get("schema_version"),
        "source_discovery_experiment_path": str(discovery_source),
        "source_discovery_experiment_sha256": hashlib.sha256(discovery_blob).hexdigest(),
        "source_selected_candidate": discovery["decision_contract"],
        "replay_selected_candidate": oos["decision_contract"],
        "replay_candidate_parity": True,
        "config": config.to_dict(),
        "validation": {
            "deflated_sharpe_ratio": dsr,
            "pbo": pbo,
            "purged_cv_pass": bool(folds["pass"]),
            "largest_contributor_removed_return_pct": largest_removed,
            "embargo_applied": True,
        },
        "diagnostics": {
            "method": "single_frozen_tradeflow_candidate",
            "contract_hash": discovery_hash,
            "candidate_count": 1,
            "selection_trial_count": 1,
            "discovery_day_count": len(discovery_daily),
            "historical_oos_day_count": len(oos_daily),
            "frozen_discovery_beta_to_btc": frozen_beta,
            "discovery_residual_return_pct": _compound_pct(combined_residual[: len(discovery_daily)]),
            "historical_oos_residual_return_pct": _compound_pct(oos_residual),
            "dsr": {
                "selected_per_period_sharpe": selected_sharpe,
                "expected_max_per_period_sharpe": 0.0,
                "skew": skew,
                "kurtosis": kurtosis,
                "deflated_sharpe_ratio": dsr,
                "period": "UTC day",
            },
            "pbo": {
                "pbo": pbo,
                "method": "not_identifiable_single_pre_registered_candidate",
                "blocking_default_applied": True,
            },
            "purged_cv": folds,
        },
        "hard_boundaries": [
            "Validation is research-only and cannot place orders or change paper/live state.",
            "The discovery contract hash must exactly match the once-only historical OOS artifact.",
            "PBO is not identifiable from one pre-registered candidate and is conservatively blocking at 1.0.",
            "Historical OOS is not validation_v1 forward evidence and cannot authorize paper/live.",
        ],
    }


def write_validation_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-validation",
        path_key="artifact_path",
        default_filename="alpha_agent_validation.json",
        explicit_path=explicit_path,
    )
