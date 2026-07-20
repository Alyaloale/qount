"""Economic reliability audit for causal MiniTrend HMM regime probabilities."""

from __future__ import annotations

import datetime as dt
import math
import random
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.futures_recovery_backtest import VariantResult
from qount.mini_trend.regime_ml import REGIME_LABELS
from qount.mini_trend.regime_ml import RegimeMLConfig
from qount.mini_trend.regime_ml import _hmm_outputs
from qount.mini_trend.regime_ml import _metrics
from qount.models import utc_now
from qount.settings import Settings


HMM_AUDIT_VERSION = "mini_trend_regime_hmm_economic_audit_v0.1"


@dataclass(frozen=True)
class HMMAuditConfig:
    probability_bins: int = 5
    economic_horizon_days: int = 30
    bootstrap_block_days: int = 30
    bootstrap_samples: int = 2_000
    seed: int = 20260718
    trial_count: int = 1

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "model": "three-state GaussianHMM with causal filtering from regime_ml v0.2",
                "score": "p_bull - p_bear",
                "validation": "expanding annual folds with label-end purge",
                "interpretation": "consumed-history discovery only",
            }
        )


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
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
        average_rank = (start + end - 1) / 2.0
        for offset in range(start, end):
            ranks[indexed[offset][0]] = average_rank
        start = end
    return ranks


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean, right_mean = _mean(left), _mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_variance = sum((x - left_mean) ** 2 for x in left)
    right_variance = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_variance * right_variance)
    return numerator / denominator if denominator > 0 else 0.0


def _spearman(left: Sequence[float], right: Sequence[float]) -> float:
    return _correlation(_rank(left), _rank(right))


def _quantile_groups(
    rows: Sequence[Mapping[str, Any]], key: str, count: int
) -> list[list[Mapping[str, Any]]]:
    ordered = sorted(rows, key=lambda row: (float(row[key]), str(row["decision_date"])))
    groups: list[list[Mapping[str, Any]]] = [[] for _ in range(count)]
    for index, row in enumerate(ordered):
        group = min(index * count // max(len(ordered), 1), count - 1)
        groups[group].append(row)
    return groups


def _compound(returns: Sequence[float]) -> float:
    value = 1.0
    for daily_return in returns:
        value *= 1.0 + float(daily_return)
    return value - 1.0


def _max_drawdown(returns: Sequence[float]) -> float:
    value = peak = 1.0
    drawdown = 0.0
    for daily_return in returns:
        value *= 1.0 + float(daily_return)
        peak = max(peak, value)
        drawdown = max(drawdown, (peak - value) / peak)
    return drawdown


def _hmm_prediction_rows(dataset: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = RegimeMLConfig(
        **{
            key: tuple(value) if key == "test_years" else value
            for key, value in dataset["contract"].items()
            if key != "contract_hash"
        }
    )
    rows = list(dataset["rows"])
    predictions: list[dict[str, Any]] = []
    fold_quality: list[dict[str, Any]] = []
    for test_year in config.test_years:
        test_start = dt.date(test_year, 1, 1)
        test_end = dt.date(test_year, 12, 31)
        train = [
            row for row in rows if dt.date.fromisoformat(row["label_end_date"]) < test_start
        ]
        test = [
            row
            for row in rows
            if test_start <= dt.date.fromisoformat(row["decision_date"]) <= test_end
        ]
        if not train or not test or set(row["label"] for row in train) != set(REGIME_LABELS):
            continue
        output = _hmm_outputs(rows, train, test, seed=config.seed + test_year)
        probabilities = output["label_probabilities"]
        train_labels = [row["label"] for row in train]
        train_distribution = [train_labels.count(label) / len(train_labels) for label in REGIME_LABELS]
        constant = [list(train_distribution) for _ in test]
        actual = [row["label"] for row in test]
        model_metrics = _metrics(actual, probabilities)
        constant_metrics = _metrics(actual, constant)
        purge_passed = max(row["label_end_date"] for row in train) < test[0]["decision_date"]
        fold_quality.append(
            {
                "test_year": test_year,
                "train_rows": len(train),
                "test_rows": len(test),
                "purge_check_passed": purge_passed,
                "model_multiclass_brier": model_metrics["multiclass_brier"],
                "constant_multiclass_brier": constant_metrics["multiclass_brier"],
                "brier_improvement_vs_constant": constant_metrics["multiclass_brier"]
                - model_metrics["multiclass_brier"],
                "model_log_loss": model_metrics["log_loss"],
                "constant_log_loss": constant_metrics["log_loss"],
                "log_loss_improvement_vs_constant": constant_metrics["log_loss"]
                - model_metrics["log_loss"],
            }
        )
        for row, probability in zip(test, probabilities):
            probability_map = {
                label: float(probability[index]) for index, label in enumerate(REGIME_LABELS)
            }
            predictions.append(
                {
                    "decision_date": row["decision_date"],
                    "test_year": test_year,
                    "actual_label": row["label"],
                    "causal_stage": row["causal_stage"],
                    "probabilities": probability_map,
                    "p_bear": probability_map["bear"],
                    "p_bull": probability_map["bull"],
                    "p_range": probability_map["range"],
                    "risk_score": probability_map["bull"] - probability_map["bear"],
                    "forward_return_horizon": float(row["forward_return_horizon"]),
                    "forward_path_max_drawdown": float(row["forward_path_max_drawdown"]),
                    "forward_max_adverse_return": float(row["forward_max_adverse_return"]),
                    "forward_max_favorable_return": float(row["forward_max_favorable_return"]),
                    "forward_realized_volatility": float(row["forward_realized_volatility"]),
                }
            )
    return predictions, fold_quality


def _attach_base_outcomes(
    predictions: Sequence[Mapping[str, Any]],
    base_result: VariantResult,
    horizon_days: int,
) -> list[dict[str, Any]]:
    base_rows = list(base_result.equity)
    index_by_date = {str(row["decision_date"]): index for index, row in enumerate(base_rows)}
    result = []
    for prediction in predictions:
        start = index_by_date.get(str(prediction["decision_date"]))
        if start is None or start + horizon_days > len(base_rows):
            continue
        window = base_rows[start : start + horizon_days]
        returns = [float(row["net_return"]) for row in window]
        result.append(
            dict(prediction)
            | {
                "base_forward_net_return": _compound(returns),
                "base_forward_max_drawdown": _max_drawdown(returns),
                "base_forward_average_gross": _mean([float(row["gross"]) for row in window]),
                "base_forward_active_days": sum(float(row["gross"]) > 0 for row in window),
                "base_forward_price_component": sum(
                    float(row["gross_price_return"]) for row in window
                ),
                "base_forward_funding_component": sum(float(row["funding_return"]) for row in window),
                "base_forward_cost_component": sum(
                    float(row["trading_cost_return"]) for row in window
                ),
            }
        )
    return result


def _probability_reliability(
    rows: Sequence[Mapping[str, Any]], label: str, bin_count: int
) -> dict[str, Any]:
    key = f"p_{label}"
    groups = _quantile_groups(rows, key, bin_count)
    bins = []
    for index, group in enumerate(groups):
        bins.append(
            {
                "bin": index + 1,
                "rows": len(group),
                "mean_probability": _mean([float(row[key]) for row in group]),
                "observed_rate": _mean(
                    [float(row["actual_label"] == label) for row in group]
                ),
                "mean_forward_return": _mean(
                    [float(row["forward_return_horizon"]) for row in group]
                ),
                "mean_forward_path_max_drawdown": _mean(
                    [float(row["forward_path_max_drawdown"]) for row in group]
                ),
            }
        )
    probabilities = [float(row[key]) for row in rows]
    actual = [float(row["actual_label"] == label) for row in rows]
    observed_rates = [float(row["observed_rate"]) for row in bins]
    return {
        "label": label,
        "rows": len(rows),
        "bins": bins,
        "expected_calibration_error": sum(
            row["rows"] / len(rows) * abs(row["mean_probability"] - row["observed_rate"])
            for row in bins
        )
        if rows
        else 0.0,
        "probability_outcome_spearman": _spearman(probabilities, actual),
        "bin_observed_rate_spearman": _spearman(list(range(len(bins))), observed_rates),
        "monotonic_non_decreasing_steps": sum(
            observed_rates[index] >= observed_rates[index - 1]
            for index in range(1, len(observed_rates))
        ),
    }


def _economic_bins(rows: Sequence[Mapping[str, Any]], bin_count: int) -> list[dict[str, Any]]:
    groups = _quantile_groups(rows, "risk_score", bin_count)
    return [
        {
            "bin": index + 1,
            "rows": len(group),
            "mean_risk_score": _mean([float(row["risk_score"]) for row in group]),
            "mean_top3_forward_return": _mean(
                [float(row["forward_return_horizon"]) for row in group]
            ),
            "top3_positive_rate": _mean(
                [float(row["forward_return_horizon"] > 0) for row in group]
            ),
            "mean_top3_path_max_drawdown": _mean(
                [float(row["forward_path_max_drawdown"]) for row in group]
            ),
            "mean_base_forward_return": _mean(
                [float(row["base_forward_net_return"]) for row in group]
            ),
            "base_positive_rate": _mean(
                [float(row["base_forward_net_return"] > 0) for row in group]
            ),
            "mean_base_forward_max_drawdown": _mean(
                [float(row["base_forward_max_drawdown"]) for row in group]
            ),
            "mean_base_average_gross": _mean(
                [float(row["base_forward_average_gross"]) for row in group]
            ),
        }
        for index, group in enumerate(groups)
    ]


def _spread(bins: Sequence[Mapping[str, Any]], key: str) -> float:
    return float(bins[-1][key]) - float(bins[0][key]) if bins else 0.0


def _bootstrap_spread(
    rows: Sequence[Mapping[str, Any]],
    *,
    metric: str,
    block_days: int,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    scores = [float(row["risk_score"]) for row in rows]
    low_threshold = _percentile(scores, 0.2)
    high_threshold = _percentile(scores, 0.8)
    rng = random.Random(seed)
    spreads = []
    count = len(rows)
    for _ in range(samples):
        sampled: list[Mapping[str, Any]] = []
        while len(sampled) < count:
            start = rng.randrange(count)
            sampled.extend(rows[(start + offset) % count] for offset in range(block_days))
        sampled = sampled[:count]
        low = [float(row[metric]) for row in sampled if float(row["risk_score"]) <= low_threshold]
        high = [float(row[metric]) for row in sampled if float(row["risk_score"]) >= high_threshold]
        if low and high:
            spreads.append(_mean(high) - _mean(low))
    return {
        "metric": metric,
        "block_days": block_days,
        "samples_requested": samples,
        "samples_completed": len(spreads),
        "low_score_threshold": low_threshold,
        "high_score_threshold": high_threshold,
        "median_spread": _percentile(spreads, 0.5),
        "p05_spread": _percentile(spreads, 0.05),
        "p95_spread": _percentile(spreads, 0.95),
        "probability_spread_positive": _mean([float(value > 0) for value in spreads]),
    }


def build_hmm_economic_audit(
    dataset: Mapping[str, Any],
    base_result: VariantResult,
    config: HMMAuditConfig | None = None,
) -> dict[str, Any]:
    config = config or HMMAuditConfig()
    predictions, fold_quality = _hmm_prediction_rows(dataset)
    rows = _attach_base_outcomes(predictions, base_result, config.economic_horizon_days)
    if not rows:
        raise ValueError("no HMM OOS rows overlap the base strategy outcome series")
    reliability = {
        label: _probability_reliability(rows, label, config.probability_bins)
        for label in REGIME_LABELS
    }
    economic_bins = _economic_bins(rows, config.probability_bins)
    fold_economics = []
    for year in sorted({int(row["test_year"]) for row in rows}):
        year_rows = [row for row in rows if int(row["test_year"]) == year]
        bins = _economic_bins(year_rows, config.probability_bins)
        fold_economics.append(
            {
                "test_year": year,
                "rows": len(year_rows),
                "conservative_effective_rows": math.ceil(
                    len(year_rows) / config.economic_horizon_days
                ),
                "risk_score_top3_return_spearman": _spearman(
                    [float(row["risk_score"]) for row in year_rows],
                    [float(row["forward_return_horizon"]) for row in year_rows],
                ),
                "high_minus_low_top3_return": _spread(bins, "mean_top3_forward_return"),
                "high_minus_low_base_return": _spread(bins, "mean_base_forward_return"),
                "high_minus_low_base_drawdown": _spread(
                    bins, "mean_base_forward_max_drawdown"
                ),
            }
        )
    bootstrap = {
        metric: _bootstrap_spread(
            rows,
            metric=metric,
            block_days=config.bootstrap_block_days,
            samples=config.bootstrap_samples,
            seed=config.seed + offset,
        )
        for offset, metric in enumerate(
            (
                "forward_return_horizon",
                "base_forward_net_return",
                "base_forward_max_drawdown",
            )
        )
    }
    positive_return_folds = sum(
        row["high_minus_low_top3_return"] > 0 for row in fold_economics
    )
    gates = {
        "all_label_end_purge_checks_passed": bool(fold_quality)
        and all(row["purge_check_passed"] for row in fold_quality),
        "hmm_brier_positive_in_at_least_three_folds": sum(
            row["brier_improvement_vs_constant"] > 0 for row in fold_quality
        )
        >= 3,
        "bull_probability_bins_mostly_monotonic": reliability["bull"][
            "monotonic_non_decreasing_steps"
        ]
        >= config.probability_bins - 2,
        "bear_probability_bins_mostly_monotonic": reliability["bear"][
            "monotonic_non_decreasing_steps"
        ]
        >= config.probability_bins - 2,
        "risk_score_top3_return_spread_positive": _spread(
            economic_bins, "mean_top3_forward_return"
        )
        > 0,
        "risk_score_return_spread_positive_in_three_folds": positive_return_folds >= 3,
        "block_bootstrap_return_spread_probability_at_least_80pct": bootstrap[
            "forward_return_horizon"
        ]["probability_spread_positive"]
        >= 0.8,
    }
    supported = all(gates.values())
    return {
        "schema_version": HMM_AUDIT_VERSION,
        "artifact_type": "mini_trend_regime_hmm_economic_audit",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "network_download_used": False,
            "paper_or_live_allowed": False,
        },
        "contract": {**asdict(config), "contract_hash": config.contract_hash},
        "lineage": {
            "dataset_contract_hash": dataset["contract"]["contract_hash"],
            "dataset_data_hash": dataset["data_hash"],
            "base_result_hash": canonical_hash(base_result.equity),
            "base_result_metrics": dict(base_result.metrics),
        },
        "sample": {
            "oos_prediction_rows": len(predictions),
            "economically_aligned_rows": len(rows),
            "first_date": rows[0]["decision_date"],
            "last_date": rows[-1]["decision_date"],
            "overlapping_horizon_days": config.economic_horizon_days,
            "conservative_effective_rows": math.ceil(
                len(rows) / config.economic_horizon_days
            ),
        },
        "fold_probability_quality": fold_quality,
        "probability_reliability": reliability,
        "economic_conditioning": {
            "score": "p_bull - p_bear",
            "bins": economic_bins,
            "risk_score_top3_return_spearman": _spearman(
                [float(row["risk_score"]) for row in rows],
                [float(row["forward_return_horizon"]) for row in rows],
            ),
            "risk_score_base_return_spearman": _spearman(
                [float(row["risk_score"]) for row in rows],
                [float(row["base_forward_net_return"]) for row in rows],
            ),
            "bear_probability_base_drawdown_spearman": _spearman(
                [float(row["p_bear"]) for row in rows],
                [float(row["base_forward_max_drawdown"]) for row in rows],
            ),
            "high_minus_low_top3_return": _spread(
                economic_bins, "mean_top3_forward_return"
            ),
            "high_minus_low_base_return": _spread(
                economic_bins, "mean_base_forward_return"
            ),
            "high_minus_low_base_drawdown": _spread(
                economic_bins, "mean_base_forward_max_drawdown"
            ),
            "folds": fold_economics,
            "positive_top3_return_spread_fold_count": positive_return_folds,
            "block_bootstrap": bootstrap,
        },
        "prediction_rows": rows,
        "diagnostics": {
            "gates": gates,
            "passed_gate_count": sum(gates.values()),
            "gate_count": len(gates),
            "verdict": (
                "retain_hmm_for_dynamic_risk_ablation"
                if supported
                else "reject_hmm_as_economic_risk_signal"
            ),
            "paper_or_live_allowed": False,
        },
    }


def write_hmm_economic_audit_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-regime-hmm-economic-audit",
        path_key="artifact_path",
        default_filename="mini_trend_regime_hmm_economic_audit.json",
        explicit_path=explicit_path,
    )
