"""Historical regime-label dataset and tabular discovery models for MiniTrend."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.forward import TOP3
from qount.mini_trend.futures_regime_overlay import classify_regime
from qount.models import utc_now
from qount.settings import Settings


REGIME_ML_VERSION = "mini_trend_regime_ml_discovery_v0.2"
REGIME_LABELS = ("bear", "bull", "range")
_DAY_MS = 86_400_000

FEATURE_NAMES = (
    "btc_return_1d",
    "btc_return_5d",
    "btc_return_20d",
    "btc_return_60d",
    "top3_return_1d",
    "top3_return_5d",
    "top3_return_20d",
    "top3_return_60d",
    "btc_sma20_distance",
    "btc_sma60_distance",
    "btc_sma200_distance",
    "btc_sma20_sma60_spread",
    "breadth_above_sma200",
    "btc_volatility_20d",
    "btc_volatility_60d",
    "top3_volatility_20d",
    "top3_volatility_60d",
    "btc_atr14_pct",
    "btc_drawdown_60d",
    "average_pairwise_correlation_20d",
    "average_pairwise_correlation_60d",
    "funding_1d_annualized",
    "funding_7d_annualized",
    "funding_30d_annualized",
    "funding_30d_coverage",
    "stage_strong_bull",
    "stage_transition_range",
    "stage_bear_cash",
)
HMM_FEATURE_NAMES = (
    "top3_return_1d",
    "top3_return_5d",
    "top3_volatility_20d",
    "btc_sma200_distance",
    "funding_7d_annualized",
)
HMM_STATE_FEATURE_NAMES = tuple(f"hmm_state_{index}_probability" for index in range(3))


@dataclass(frozen=True)
class RegimeMLConfig:
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    horizon_days: int = 30
    volatility_lookback_days: int = 20
    barrier_sigma: float = 1.0
    feature_warmup_days: int = 200
    test_years: tuple[int, ...] = (2023, 2024, 2025, 2026)
    seed: int = 20260718
    trial_count: int = 1

    @property
    def contract_hash(self) -> str:
        return _canonical_hash(
            {
                "config": asdict(self),
                "features": list(FEATURE_NAMES),
                "labels": list(REGIME_LABELS),
                "label_definition": (
                    "TOP3 equal-weight close index first hits +/- barrier_sigma * "
                    "past-volatility * sqrt(horizon), otherwise range"
                ),
                "outcome_definition": (
                    "full-horizon TOP3 return, path drawdown, favorable/adverse excursion, "
                    "and realized volatility are targets only"
                ),
                "feature_timing": "completed daily bars and settlements only",
            }
        )


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _std(values: Sequence[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _return(values: Sequence[float], index: int, lookback: int) -> float:
    prior = index - lookback
    if prior < 0 or values[prior] <= 0:
        raise ValueError("insufficient values for return feature")
    return values[index] / values[prior] - 1.0


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean, right_mean = _mean(left), _mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_var = sum((x - left_mean) ** 2 for x in left)
    right_var = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_var * right_var)
    return numerator / denominator if denominator > 0 else 0.0


def _average_pairwise_correlation(
    returns_by_symbol: Mapping[str, Sequence[float]], index: int, lookback: int
) -> float:
    values = []
    for left_index, left in enumerate(TOP3):
        for right in TOP3[left_index + 1 :]:
            start = index - lookback + 1
            values.append(
                _correlation(
                    returns_by_symbol[left][start : index + 1],
                    returns_by_symbol[right][start : index + 1],
                )
            )
    return _mean(values)


def _atr_pct(bars: Sequence[Bar], index: int, lookback: int = 14) -> float:
    start = index - lookback + 1
    true_ranges = []
    for offset in range(start, index + 1):
        previous_close = bars[offset - 1].close
        bar = bars[offset]
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )
    return _mean(true_ranges) / bars[index].close


def _daily_funding(
    funding_by_symbol: Mapping[str, Sequence[Funding]],
) -> dict[str, dict[int, float]]:
    result: dict[str, dict[int, float]] = {symbol: {} for symbol in TOP3}
    for symbol in TOP3:
        for row in funding_by_symbol.get(symbol, []):
            bar_open = ((row.ts_ms - 1) // _DAY_MS) * _DAY_MS
            result[symbol][bar_open] = result[symbol].get(bar_open, 0.0) + float(row.rate)
    return result


def _top3_index(
    closes_by_symbol: Mapping[str, Sequence[float]],
) -> tuple[list[float], dict[str, list[float]]]:
    count = len(closes_by_symbol["BTCUSDT"])
    returns_by_symbol = {symbol: [0.0] * count for symbol in TOP3}
    index_values = [1.0] * count
    for offset in range(1, count):
        daily = []
        for symbol in TOP3:
            value = closes_by_symbol[symbol][offset] / closes_by_symbol[symbol][offset - 1] - 1.0
            returns_by_symbol[symbol][offset] = value
            daily.append(value)
        index_values[offset] = index_values[offset - 1] * (1.0 + _mean(daily))
    return index_values, returns_by_symbol


def _triple_barrier_label(
    index_values: Sequence[float],
    index_returns: Sequence[float],
    dates: Sequence[str],
    decision_index: int,
    config: RegimeMLConfig,
) -> dict[str, Any] | None:
    end_index = decision_index + config.horizon_days
    if end_index >= len(index_values):
        return None
    vol_start = decision_index - config.volatility_lookback_days + 1
    volatility = _std(index_returns[vol_start : decision_index + 1])
    if volatility <= 0:
        return None
    barrier = config.barrier_sigma * volatility * math.sqrt(config.horizon_days)
    base = index_values[decision_index]
    label = "range"
    hit_index = end_index
    forward_path = [index_values[index] / base for index in range(decision_index, end_index + 1)]
    peak = forward_path[0]
    path_max_drawdown = 0.0
    for value in forward_path:
        peak = max(peak, value)
        path_max_drawdown = max(path_max_drawdown, (peak - value) / peak)
    for future_index in range(decision_index + 1, end_index + 1):
        future_return = index_values[future_index] / base - 1.0
        if future_return >= barrier:
            label, hit_index = "bull", future_index
            break
        if future_return <= -barrier:
            label, hit_index = "bear", future_index
            break
    return {
        "label": label,
        "label_end_date": dates[hit_index],
        "barrier_return": barrier,
        "forward_return_at_label_end": index_values[hit_index] / base - 1.0,
        "horizon_end_date": dates[end_index],
        "forward_return_horizon": index_values[end_index] / base - 1.0,
        "forward_path_max_drawdown": path_max_drawdown,
        "forward_max_adverse_return": min(value - 1.0 for value in forward_path),
        "forward_max_favorable_return": max(value - 1.0 for value in forward_path),
        "forward_realized_volatility": _std(
            index_returns[decision_index + 1 : end_index + 1]
        ),
        "label_duration_days": hit_index - decision_index,
    }


def build_regime_ml_dataset(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    config: RegimeMLConfig | None = None,
) -> dict[str, Any]:
    config = config or RegimeMLConfig()
    bars = align_bars(bars_by_symbol, TOP3)
    dates = [bar.date for bar in bars["BTCUSDT"]]
    closes = {symbol: [float(bar.close) for bar in bars[symbol]] for symbol in TOP3}
    top3_index, returns_by_symbol = _top3_index(closes)
    top3_returns = [0.0] + [
        top3_index[index] / top3_index[index - 1] - 1.0
        for index in range(1, len(top3_index))
    ]
    btc_returns = returns_by_symbol["BTCUSDT"]
    funding = _daily_funding(funding_by_symbol)
    rows = []
    skipped_missing_funding = 0
    minimum_index = max(config.feature_warmup_days - 1, 200)
    for index in range(minimum_index, len(dates)):
        decision_date = dates[index]
        if decision_date < config.start_date or decision_date > config.end_date:
            continue
        label = _triple_barrier_label(top3_index, top3_returns, dates, index, config)
        if label is None:
            continue
        current_funding = [funding[symbol].get(bars[symbol][index].ts_ms) for symbol in TOP3]
        if any(value is None for value in current_funding):
            skipped_missing_funding += 1
            continue
        rolling_funding: list[float] = []
        covered_days = 0
        for offset in range(index - 29, index + 1):
            values = [funding[symbol].get(bars[symbol][offset].ts_ms) for symbol in TOP3]
            if all(value is not None for value in values):
                rolling_funding.append(statistics.median(float(value) for value in values))
                covered_days += 1
            else:
                rolling_funding.append(0.0)
        btc_close = closes["BTCUSDT"][index]
        sma20 = _mean(closes["BTCUSDT"][index - 19 : index + 1])
        sma60 = _mean(closes["BTCUSDT"][index - 59 : index + 1])
        sma200 = _mean(closes["BTCUSDT"][index - 199 : index + 1])
        breadth = _mean(
            [
                float(
                    closes[symbol][index]
                    > _mean(closes[symbol][index - 199 : index + 1])
                )
                for symbol in TOP3
            ]
        )
        stage = classify_regime(
            {symbol: bars[symbol][: index + 1] for symbol in TOP3}
        ).stage
        features = {
            "btc_return_1d": _return(closes["BTCUSDT"], index, 1),
            "btc_return_5d": _return(closes["BTCUSDT"], index, 5),
            "btc_return_20d": _return(closes["BTCUSDT"], index, 20),
            "btc_return_60d": _return(closes["BTCUSDT"], index, 60),
            "top3_return_1d": _return(top3_index, index, 1),
            "top3_return_5d": _return(top3_index, index, 5),
            "top3_return_20d": _return(top3_index, index, 20),
            "top3_return_60d": _return(top3_index, index, 60),
            "btc_sma20_distance": btc_close / sma20 - 1.0,
            "btc_sma60_distance": btc_close / sma60 - 1.0,
            "btc_sma200_distance": btc_close / sma200 - 1.0,
            "btc_sma20_sma60_spread": sma20 / sma60 - 1.0,
            "breadth_above_sma200": breadth,
            "btc_volatility_20d": _std(btc_returns[index - 19 : index + 1]),
            "btc_volatility_60d": _std(btc_returns[index - 59 : index + 1]),
            "top3_volatility_20d": _std(top3_returns[index - 19 : index + 1]),
            "top3_volatility_60d": _std(top3_returns[index - 59 : index + 1]),
            "btc_atr14_pct": _atr_pct(bars["BTCUSDT"], index),
            "btc_drawdown_60d": btc_close
            / max(closes["BTCUSDT"][index - 59 : index + 1])
            - 1.0,
            "average_pairwise_correlation_20d": _average_pairwise_correlation(
                returns_by_symbol, index, 20
            ),
            "average_pairwise_correlation_60d": _average_pairwise_correlation(
                returns_by_symbol, index, 60
            ),
            "funding_1d_annualized": statistics.median(
                float(value) for value in current_funding
            )
            * 365.0,
            "funding_7d_annualized": _mean(rolling_funding[-7:]) * 365.0,
            "funding_30d_annualized": _mean(rolling_funding) * 365.0,
            "funding_30d_coverage": covered_days / 30.0,
            "stage_strong_bull": float(stage == "strong_bull"),
            "stage_transition_range": float(stage == "transition_range"),
            "stage_bear_cash": float(stage == "bear_cash"),
        }
        if tuple(features) != FEATURE_NAMES:
            raise AssertionError("regime ML feature order changed")
        rows.append(
            {
                "decision_date": decision_date,
                "causal_stage": stage,
                **label,
                "features": features,
            }
        )
    label_counts = {label: sum(row["label"] == label for row in rows) for label in REGIME_LABELS}
    stage_counts = {
        stage: sum(row["causal_stage"] == stage for row in rows)
        for stage in ("strong_bull", "transition_range", "bear_cash")
    }
    return {
        "schema_version": REGIME_ML_VERSION,
        "artifact_type": "mini_trend_regime_ml_dataset",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "network_download_used": False,
            "paper_or_live_allowed": False,
        },
        "contract": {**asdict(config), "contract_hash": config.contract_hash},
        "features": list(FEATURE_NAMES),
        "summary": {
            "row_count": len(rows),
            "first_decision_date": rows[0]["decision_date"] if rows else None,
            "last_decision_date": rows[-1]["decision_date"] if rows else None,
            "label_counts": label_counts,
            "causal_stage_counts": stage_counts,
            "skipped_missing_current_funding": skipped_missing_funding,
        },
        "data_hash": _canonical_hash(
            {
                "bars": {
                    symbol: [[bar.ts_ms, bar.open, bar.high, bar.low, bar.close] for bar in bars[symbol]]
                    for symbol in TOP3
                },
                "funding": {
                    symbol: [[row.ts_ms, row.rate] for row in funding_by_symbol.get(symbol, [])]
                    for symbol in TOP3
                },
            }
        ),
        "rows": rows,
    }


def _model_factory(name: str, seed: int, *, use_gpu: bool):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if name in {"logistic", "logistic_unweighted"}:
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=1.0,
                class_weight="balanced" if name == "logistic" else None,
                max_iter=2000,
                random_state=seed,
            ),
        )
    if name == "hist_gb":
        return HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=200,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=seed,
        )
    if name == "lightgbm":
        from lightgbm import LGBMClassifier

        return LGBMClassifier(
            objective="multiclass",
            n_estimators=300,
            learning_rate=0.03,
            num_leaves=15,
            max_depth=5,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=seed,
            n_jobs=8,
            verbosity=-1,
        )
    if name == "xgboost":
        from xgboost import XGBClassifier

        return XGBClassifier(
            objective="multi:softprob",
            n_estimators=300,
            learning_rate=0.03,
            max_depth=3,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=seed,
            n_jobs=8,
            tree_method="hist",
            device="cuda" if use_gpu else "cpu",
            eval_metric="mlogloss",
        )
    raise ValueError(f"unknown regime model: {name}")


def _probabilities_for_labels(model, values, labels: Sequence[str]) -> list[list[float]]:
    raw = model.predict_proba(values)
    classes = list(model.classes_)
    return _normalize_probabilities([
        [float(row[classes.index(label)]) if label in classes else 0.0 for label in labels]
        for row in raw
    ])


def _normalize_probabilities(
    probabilities: Sequence[Sequence[float]],
) -> list[list[float]]:
    normalized = []
    for row in probabilities:
        clipped = [max(float(value), 1e-15) for value in row]
        total = sum(clipped)
        if total <= 0:
            raise ValueError("model returned an empty probability row")
        normalized.append([value / total for value in clipped])
    return normalized


def _blend_probabilities(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
    *,
    left_weight: float = 0.5,
) -> list[list[float]]:
    if not 0.0 <= left_weight <= 1.0:
        raise ValueError("left_weight must be between zero and one")
    if len(left) != len(right):
        raise ValueError("probability inputs must have the same row count")
    blended = []
    for left_row, right_row in zip(left, right):
        if len(left_row) != len(right_row):
            raise ValueError("probability inputs must have the same column count")
        blended.append(
            [
                left_weight * float(left_value)
                + (1.0 - left_weight) * float(right_value)
                for left_value, right_value in zip(left_row, right_row)
            ]
        )
    return _normalize_probabilities(blended)


def _causal_hmm_filter(
    values,
    *,
    start_probability,
    transition_matrix,
    means,
    diagonal_covariances,
    initial_posterior=None,
):
    import numpy as np

    observations = np.asarray(values, dtype=float)
    start = np.asarray(start_probability, dtype=float)
    transition = np.asarray(transition_matrix, dtype=float)
    means_array = np.asarray(means, dtype=float)
    covariance = np.asarray(diagonal_covariances, dtype=float)
    if covariance.ndim == 3:
        covariance = np.asarray([np.diag(row) for row in covariance], dtype=float)
    covariance = np.maximum(covariance, 1e-9)
    posterior = None if initial_posterior is None else np.asarray(initial_posterior, dtype=float)
    result = []
    for observation in observations:
        log_emission = -0.5 * np.sum(
            np.log(2.0 * math.pi * covariance)
            + (observation - means_array) ** 2 / covariance,
            axis=1,
        )
        log_emission -= float(np.max(log_emission))
        emission = np.exp(log_emission)
        prior = start if posterior is None else posterior @ transition
        posterior = np.maximum(prior * emission, 1e-300)
        posterior /= float(np.sum(posterior))
        result.append(posterior.copy())
    return np.asarray(result)


def _hmm_outputs(
    all_rows: Sequence[Mapping[str, Any]],
    train: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> dict[str, Any]:
    import numpy as np
    from hmmlearn.hmm import GaussianHMM
    from sklearn.preprocessing import StandardScaler

    def matrix(rows: Sequence[Mapping[str, Any]]):
        return np.asarray(
            [[float(row["features"][name]) for name in HMM_FEATURE_NAMES] for row in rows],
            dtype=float,
        )

    scaler = StandardScaler()
    train_values = scaler.fit_transform(matrix(train))
    model = GaussianHMM(
        n_components=3,
        covariance_type="diag",
        n_iter=300,
        tol=1e-4,
        random_state=seed,
        min_covar=1e-5,
    )
    model.fit(train_values)
    covariance = getattr(model, "_covars_", model.covars_)
    train_posterior = _causal_hmm_filter(
        train_values,
        start_probability=model.startprob_,
        transition_matrix=model.transmat_,
        means=model.means_,
        diagonal_covariances=covariance,
    )
    label_given_state = np.full((3, len(REGIME_LABELS)), 0.5, dtype=float)
    for posterior, row in zip(train_posterior, train):
        label_given_state[:, REGIME_LABELS.index(row["label"])] += posterior
    label_given_state /= label_given_state.sum(axis=1, keepdims=True)

    train_last_date = train[-1]["decision_date"]
    test_last_date = test[-1]["decision_date"]
    continuation = [
        row
        for row in all_rows
        if train_last_date < row["decision_date"] <= test_last_date
    ]
    continuation_values = scaler.transform(matrix(continuation))
    continuation_posterior = _causal_hmm_filter(
        continuation_values,
        start_probability=model.startprob_,
        transition_matrix=model.transmat_,
        means=model.means_,
        diagonal_covariances=covariance,
        initial_posterior=train_posterior[-1],
    )
    posterior_by_date = {
        row["decision_date"]: posterior
        for row, posterior in zip(continuation, continuation_posterior)
    }
    test_state_probabilities = [
        posterior_by_date[row["decision_date"]].tolist()
        for row in test
    ]
    label_probabilities = [
        list(posterior_by_date[row["decision_date"]] @ label_given_state)
        for row in test
    ]
    return {
        "label_probabilities": _normalize_probabilities(label_probabilities),
        "train_state_probabilities": train_posterior.tolist(),
        "test_state_probabilities": _normalize_probabilities(test_state_probabilities),
        "state_label_probabilities": label_given_state.tolist(),
    }


def _hmm_probabilities(
    all_rows: Sequence[Mapping[str, Any]],
    train: Sequence[Mapping[str, Any]],
    test: Sequence[Mapping[str, Any]],
    *,
    seed: int,
) -> tuple[list[list[float]], list[list[float]]]:
    outputs = _hmm_outputs(all_rows, train, test, seed=seed)
    return outputs["label_probabilities"], outputs["state_label_probabilities"]


def _metrics(actual: Sequence[str], probabilities: Sequence[Sequence[float]]) -> dict[str, Any]:
    from sklearn.metrics import accuracy_score
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.metrics import confusion_matrix
    from sklearn.metrics import f1_score
    from sklearn.metrics import log_loss

    predicted = [REGIME_LABELS[max(range(len(row)), key=lambda index: row[index])] for row in probabilities]
    one_hot = [[float(label == actual_value) for label in REGIME_LABELS] for actual_value in actual]
    brier = _mean(
        [
            sum((probability - truth) ** 2 for probability, truth in zip(row, target))
            for row, target in zip(probabilities, one_hot)
        ]
    )
    return {
        "rows": len(actual),
        "accuracy": float(accuracy_score(actual, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(actual, predicted)),
        "macro_f1": float(f1_score(actual, predicted, labels=REGIME_LABELS, average="macro")),
        "log_loss": float(log_loss(actual, probabilities, labels=REGIME_LABELS)),
        "multiclass_brier": brier,
        "actual_counts": {label: sum(value == label for value in actual) for label in REGIME_LABELS},
        "predicted_counts": {
            label: sum(value == label for value in predicted) for label in REGIME_LABELS
        },
        "confusion_matrix": confusion_matrix(actual, predicted, labels=REGIME_LABELS).tolist(),
    }


def run_regime_ml_walk_forward(
    dataset: Mapping[str, Any],
    *,
    model_names: Sequence[str] = ("logistic", "hist_gb", "lightgbm", "xgboost"),
    use_gpu: bool = False,
    model_trial_count: int = 1,
) -> dict[str, Any]:
    import numpy as np

    config = RegimeMLConfig(
        **{
            key: tuple(value) if key == "test_years" else value
            for key, value in dataset["contract"].items()
            if key != "contract_hash"
        }
    )
    rows = list(dataset["rows"])
    folds = []
    for test_year in config.test_years:
        test_start = dt.date(test_year, 1, 1)
        test_end = dt.date(test_year, 12, 31)
        train = [
            row
            for row in rows
            if dt.date.fromisoformat(row["label_end_date"]) < test_start
        ]
        test = [
            row
            for row in rows
            if test_start <= dt.date.fromisoformat(row["decision_date"]) <= test_end
        ]
        if not train or not test:
            continue
        if set(row["label"] for row in train) != set(REGIME_LABELS):
            continue
        x_train = np.asarray(
            [[float(row["features"][name]) for name in FEATURE_NAMES] for row in train],
            dtype=float,
        )
        y_train = [row["label"] for row in train]
        x_test = np.asarray(
            [[float(row["features"][name]) for name in FEATURE_NAMES] for row in test],
            dtype=float,
        )
        y_test = [row["label"] for row in test]
        train_distribution = [y_train.count(label) / len(y_train) for label in REGIME_LABELS]
        constant_probabilities = [list(train_distribution) for _ in test]
        hmm_model_names = {
            "hmm",
            "hmm_prior_shrink_50",
            "logistic_hmm_state",
            "hmm_logistic_unweighted_ensemble_50",
        }
        hmm_outputs = None
        if any(name in hmm_model_names for name in model_names):
            hmm_outputs = _hmm_outputs(
                rows,
                train,
                test,
                seed=config.seed + test_year,
            )
        fold = {
            "test_year": test_year,
            "train_rows": len(train),
            "test_rows": len(test),
            "train_first_date": train[0]["decision_date"],
            "train_last_decision_date": train[-1]["decision_date"],
            "train_last_label_end_date": max(row["label_end_date"] for row in train),
            "test_first_date": test[0]["decision_date"],
            "purge_check_passed": max(row["label_end_date"] for row in train)
            < test[0]["decision_date"],
            "constant_baseline": _metrics(y_test, constant_probabilities),
            "models": {},
        }
        if all("causal_stage" in row for row in test):
            stage_to_label = {
                "strong_bull": "bull",
                "transition_range": "range",
                "bear_cash": "bear",
            }
            causal_probabilities = []
            for row in test:
                predicted_label = stage_to_label[row["causal_stage"]]
                causal_probabilities.append(
                    [0.98 if label == predicted_label else 0.01 for label in REGIME_LABELS]
                )
            fold["causal_rule_baseline"] = _metrics(y_test, causal_probabilities)
        for name in model_names:
            if name == "hmm":
                assert hmm_outputs is not None
                probabilities = hmm_outputs["label_probabilities"]
                metrics = _metrics(y_test, probabilities)
                metrics["state_label_probabilities"] = hmm_outputs[
                    "state_label_probabilities"
                ]
                metrics["hmm_features"] = list(HMM_FEATURE_NAMES)
                model = None
            elif name == "hmm_prior_shrink_50":
                assert hmm_outputs is not None
                probabilities = _blend_probabilities(
                    hmm_outputs["label_probabilities"],
                    constant_probabilities,
                    left_weight=0.5,
                )
                metrics = _metrics(y_test, probabilities)
                metrics["model_definition"] = (
                    "50% causal HMM label probabilities + 50% purged-train class prior"
                )
                model = None
            elif name == "logistic_hmm_state":
                assert hmm_outputs is not None
                model = _model_factory("logistic_unweighted", config.seed + test_year, use_gpu=False)
                augmented_train = np.column_stack(
                    (x_train, np.asarray(hmm_outputs["train_state_probabilities"], dtype=float))
                )
                augmented_test = np.column_stack(
                    (x_test, np.asarray(hmm_outputs["test_state_probabilities"], dtype=float))
                )
                model.fit(augmented_train, y_train)
                probabilities = _probabilities_for_labels(model, augmented_test, REGIME_LABELS)
                metrics = _metrics(y_test, probabilities)
                metrics["additional_features"] = list(HMM_STATE_FEATURE_NAMES)
                metrics["model_definition"] = (
                    "unweighted Logistic with three causal HMM state posteriors"
                )
            elif name == "hmm_logistic_unweighted_ensemble_50":
                assert hmm_outputs is not None
                model = _model_factory("logistic_unweighted", config.seed + test_year, use_gpu=False)
                model.fit(x_train, y_train)
                logistic_probabilities = _probabilities_for_labels(model, x_test, REGIME_LABELS)
                probabilities = _blend_probabilities(
                    hmm_outputs["label_probabilities"],
                    logistic_probabilities,
                    left_weight=0.5,
                )
                metrics = _metrics(y_test, probabilities)
                metrics["model_definition"] = (
                    "50% causal HMM + 50% unweighted Logistic probabilities"
                )
            else:
                model = _model_factory(name, config.seed + test_year, use_gpu=use_gpu)
            if name in hmm_model_names:
                pass
            elif name == "xgboost":
                from xgboost import DMatrix

                model.fit(x_train, [REGIME_LABELS.index(label) for label in y_train])
                probabilities = _normalize_probabilities([
                    [float(value) for value in row]
                    for row in model.get_booster().predict(DMatrix(x_test))
                ])
            elif name == "lightgbm":
                model.fit(x_train, y_train)
                probabilities = _normalize_probabilities(model.booster_.predict(x_test))
            else:
                model.fit(x_train, y_train)
                probabilities = _probabilities_for_labels(model, x_test, REGIME_LABELS)
            if name != "hmm":
                metrics = _metrics(y_test, probabilities)
            metrics["log_loss_improvement_vs_constant"] = (
                fold["constant_baseline"]["log_loss"] - metrics["log_loss"]
            )
            metrics["brier_improvement_vs_constant"] = (
                fold["constant_baseline"]["multiclass_brier"]
                - metrics["multiclass_brier"]
            )
            fold["models"][name] = metrics
        folds.append(fold)
    aggregate = {}
    for name in model_names:
        model_folds = [fold["models"][name] for fold in folds if name in fold["models"]]
        aggregate[name] = {
            "fold_count": len(model_folds),
            "mean_balanced_accuracy": _mean([row["balanced_accuracy"] for row in model_folds]),
            "mean_macro_f1": _mean([row["macro_f1"] for row in model_folds]),
            "mean_log_loss_improvement_vs_constant": _mean(
                [row["log_loss_improvement_vs_constant"] for row in model_folds]
            ),
            "mean_brier_improvement_vs_constant": _mean(
                [row["brier_improvement_vs_constant"] for row in model_folds]
            ),
            "positive_log_loss_improvement_fold_count": sum(
                row["log_loss_improvement_vs_constant"] > 0 for row in model_folds
            ),
            "positive_brier_improvement_fold_count": sum(
                row["brier_improvement_vs_constant"] > 0 for row in model_folds
            ),
        }
    return {
        "schema_version": REGIME_ML_VERSION,
        "artifact_type": "mini_trend_regime_ml_walk_forward",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "paper_or_live_allowed": False,
            "gpu_requested": use_gpu,
        },
        "dataset_contract_hash": dataset["contract"]["contract_hash"],
        "dataset_data_hash": dataset["data_hash"],
        "models": list(model_names),
        "model_trial_count": model_trial_count,
        "folds": folds,
        "aggregate": aggregate,
        "diagnostics": {
            "all_purge_checks_passed": bool(folds)
            and all(fold["purge_check_passed"] for fold in folds),
            "dataset_trial_count": dataset["contract"]["trial_count"],
            "model_trial_count": model_trial_count,
            "verdict": "discovery_models_evaluated" if folds else "insufficient_walk_forward_folds",
            "paper_or_live_allowed": False,
        },
    }


def write_regime_ml_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-regime-ml-discovery",
        path_key="artifact_path",
        default_filename="mini_trend_regime_ml_discovery.json",
        explicit_path=explicit_path,
    )
