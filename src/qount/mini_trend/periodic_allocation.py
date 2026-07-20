"""Low-frequency periodic allocation and causal label-learning research."""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.models import utc_now
from qount.rv.stats import sharpe
from qount.settings import Settings


PERIODIC_ALLOCATION_VERSION = "mini_trend_periodic_allocation_discovery_v0.1"
ACTION_LABELS = ("buy", "hold", "sell")
FEATURE_NAMES = (
    "return_1",
    "return_5",
    "return_20",
    "return_60",
    "sma20_distance",
    "sma60_distance",
    "sma200_distance",
    "sma20_sma60_spread",
    "volatility_20",
    "volatility_60",
    "drawdown_60",
)


@dataclass(frozen=True)
class AssetSeries:
    asset_id: str
    dates: tuple[str, ...]
    closes: tuple[float, ...]
    funding_returns: tuple[float, ...]
    periods_per_year: float
    decision_stride: int
    allocation_step: float
    turnover_cost_bps: float

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.closes):
            raise ValueError("asset dates and closes must align")
        if len(self.funding_returns) != max(len(self.closes) - 1, 0):
            raise ValueError("funding returns must align to outcome intervals")
        if any(value <= 0.0 or not math.isfinite(value) for value in self.closes):
            raise ValueError("asset closes must be positive and finite")
        if self.decision_stride <= 0:
            raise ValueError("decision stride must be positive")
        if not 0.0 < self.allocation_step <= 1.0:
            raise ValueError("allocation step must be in (0, 1]")


@dataclass(frozen=True)
class PeriodicAllocationConfig:
    start_date: str = "2021-07-20"
    end_date: str = "2026-05-31"
    label_horizon_bars: int = 20
    volatility_lookback_bars: int = 20
    barrier_sigma: float = 1.0
    feature_warmup_bars: int = 200
    test_years: tuple[int, ...] = (2023, 2024, 2025, 2026)
    models: tuple[str, ...] = ("logistic", "hist_gb")
    capital_usdt: float = 300.0
    seed: int = 20260719

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "features": list(FEATURE_NAMES),
                "labels": list(ACTION_LABELS),
                "label_definition": (
                    "first hit of +/- one trailing-volatility barrier over 20 future bars; "
                    "future prices are targets only"
                ),
                "split": "expanding annual walk-forward; train label_end_date before test year",
                "allocation": (
                    "weekly discrete increase/decrease; no short, no leverage, no external cash"
                ),
                "holdout_role": "consumed_historical_discovery_pool",
                "paper_or_live_allowed": False,
            }
        )


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _std(values: Sequence[float]) -> float:
    return statistics.stdev(values) if len(values) > 1 else 0.0


def _return(closes: Sequence[float], index: int, lookback: int) -> float:
    return closes[index] / closes[index - lookback] - 1.0


def _features(closes: Sequence[float], index: int) -> dict[str, float]:
    sma20 = _mean(closes[index - 19 : index + 1])
    sma60 = _mean(closes[index - 59 : index + 1])
    sma200 = _mean(closes[index - 199 : index + 1])
    returns = [
        closes[offset] / closes[offset - 1] - 1.0
        for offset in range(index - 59, index + 1)
    ]
    values = {
        "return_1": _return(closes, index, 1),
        "return_5": _return(closes, index, 5),
        "return_20": _return(closes, index, 20),
        "return_60": _return(closes, index, 60),
        "sma20_distance": closes[index] / sma20 - 1.0,
        "sma60_distance": closes[index] / sma60 - 1.0,
        "sma200_distance": closes[index] / sma200 - 1.0,
        "sma20_sma60_spread": sma20 / sma60 - 1.0,
        "volatility_20": _std(returns[-20:]),
        "volatility_60": _std(returns),
        "drawdown_60": closes[index] / max(closes[index - 59 : index + 1]) - 1.0,
    }
    if tuple(values) != FEATURE_NAMES:
        raise AssertionError("periodic allocation feature order changed")
    return values


def _action_label(
    dates: Sequence[str],
    closes: Sequence[float],
    index: int,
    config: PeriodicAllocationConfig,
) -> dict[str, Any] | None:
    end = index + config.label_horizon_bars
    if end >= len(closes):
        return None
    trailing = [
        closes[offset] / closes[offset - 1] - 1.0
        for offset in range(index - config.volatility_lookback_bars + 1, index + 1)
    ]
    volatility = _std(trailing)
    if volatility <= 0.0:
        return None
    barrier = config.barrier_sigma * volatility * math.sqrt(config.label_horizon_bars)
    base = closes[index]
    label = "hold"
    hit = end
    for future in range(index + 1, end + 1):
        value = closes[future] / base - 1.0
        if value >= barrier:
            label, hit = "buy", future
            break
        if value <= -barrier:
            label, hit = "sell", future
            break
    return {
        "label": label,
        "label_end_date": dates[hit],
        "horizon_end_date": dates[end],
        "barrier_return": barrier,
        "forward_return_horizon": closes[end] / base - 1.0,
    }


def build_action_dataset(
    series: AssetSeries,
    config: PeriodicAllocationConfig | None = None,
) -> dict[str, Any]:
    config = config or PeriodicAllocationConfig()
    rows = []
    for index in range(max(config.feature_warmup_bars - 1, 200), len(series.closes)):
        date = series.dates[index]
        if date < config.start_date or date > config.end_date:
            continue
        target = _action_label(series.dates, series.closes, index, config)
        if target is None:
            continue
        rows.append(
            {
                "decision_date": date,
                **target,
                "features": _features(series.closes, index),
            }
        )
    counts = {label: sum(row["label"] == label for row in rows) for label in ACTION_LABELS}
    return {
        "asset_id": series.asset_id,
        "contract": asdict(config) | {
            "contract_hash": config.contract_hash,
            "features": list(FEATURE_NAMES),
            "labels": list(ACTION_LABELS),
        },
        "rows": rows,
        "diagnostics": {
            "row_count": len(rows),
            "label_counts": counts,
            "data_hash": canonical_hash(
                {
                    "dates": list(series.dates),
                    "closes": list(series.closes),
                    "funding_returns": list(series.funding_returns),
                }
            ),
            "future_values_in_features": False,
        },
    }


def _model(name: str, seed: int):
    if name == "logistic":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        return make_pipeline(
            StandardScaler(),
            LogisticRegression(
                max_iter=2_000,
                class_weight="balanced",
                random_state=seed,
            ),
        )
    if name == "hist_gb":
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=200,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=seed,
        )
    raise ValueError(f"unknown action model: {name}")


def _probability_metrics(
    actual: Sequence[str],
    probabilities: Sequence[Mapping[str, float]],
    predicted: Sequence[str],
) -> dict[str, float]:
    if not actual:
        return {"accuracy": 0.0, "balanced_accuracy": 0.0, "brier": 0.0, "log_loss": 0.0}
    recalls = []
    for label in ACTION_LABELS:
        indexes = [index for index, value in enumerate(actual) if value == label]
        if indexes:
            recalls.append(_mean([float(predicted[index] == label) for index in indexes]))
    brier = _mean(
        [
            sum(
                (float(row[label]) - float(label == outcome)) ** 2
                for label in ACTION_LABELS
            )
            for row, outcome in zip(probabilities, actual)
        ]
    )
    log_loss = -_mean(
        [math.log(max(float(row[outcome]), 1e-15)) for row, outcome in zip(probabilities, actual)]
    )
    return {
        "accuracy": _mean([float(left == right) for left, right in zip(actual, predicted)]),
        "balanced_accuracy": _mean(recalls),
        "brier": brier,
        "log_loss": log_loss,
    }


def run_action_walk_forward(
    dataset: Mapping[str, Any],
    *,
    model_name: str,
    seed: int,
) -> dict[str, Any]:
    import numpy as np

    rows = list(dataset["rows"])
    test_years = tuple(int(value) for value in dataset["contract"]["test_years"])
    folds = []
    predictions = []
    for year in test_years:
        start = dt.date(year, 1, 1)
        end = dt.date(year, 12, 31)
        train = [row for row in rows if dt.date.fromisoformat(row["label_end_date"]) < start]
        test = [
            row
            for row in rows
            if start <= dt.date.fromisoformat(row["decision_date"]) <= end
        ]
        if not train or not test:
            continue
        x_train = np.asarray(
            [[float(row["features"][name]) for name in FEATURE_NAMES] for row in train]
        )
        y_train = np.asarray([row["label"] for row in train])
        x_test = np.asarray(
            [[float(row["features"][name]) for name in FEATURE_NAMES] for row in test]
        )
        fitted = _model(model_name, seed + year)
        fitted.fit(x_train, y_train)
        raw = fitted.predict_proba(x_test)
        classes = [str(value) for value in fitted.classes_]
        probability_rows = [
            {label: float(values[classes.index(label)]) if label in classes else 0.0 for label in ACTION_LABELS}
            for values in raw
        ]
        predicted = [max(ACTION_LABELS, key=values.get) for values in probability_rows]
        actual = [str(row["label"]) for row in test]
        train_counts = {label: sum(row["label"] == label for row in train) for label in ACTION_LABELS}
        denominator = len(train) + len(ACTION_LABELS)
        prior = {label: (train_counts[label] + 1.0) / denominator for label in ACTION_LABELS}
        constant_probabilities = [prior] * len(test)
        constant_label = max(ACTION_LABELS, key=prior.get)
        fold_metrics = _probability_metrics(actual, probability_rows, predicted)
        constant_metrics = _probability_metrics(
            actual,
            constant_probabilities,
            [constant_label] * len(test),
        )
        folds.append(
            {
                "test_year": year,
                "train_rows": len(train),
                "test_rows": len(test),
                "train_last_label_end_date": max(row["label_end_date"] for row in train),
                "test_first_date": test[0]["decision_date"],
                "purge_check_passed": max(row["label_end_date"] for row in train) < test[0]["decision_date"],
                **fold_metrics,
                "constant_brier": constant_metrics["brier"],
                "constant_log_loss": constant_metrics["log_loss"],
            }
        )
        predictions.extend(
            {
                "decision_date": row["decision_date"],
                "actual_label": outcome,
                "predicted_label": forecast,
                "probabilities": probabilities,
            }
            for row, outcome, forecast, probabilities in zip(
                test, actual, predicted, probability_rows
            )
        )
    pooled = _probability_metrics(
        [row["actual_label"] for row in predictions],
        [row["probabilities"] for row in predictions],
        [row["predicted_label"] for row in predictions],
    )
    return {
        "model": model_name,
        "folds": folds,
        "predictions": predictions,
        "pooled": pooled | {
            "mean_brier_uplift_vs_constant": _mean(
                [row["constant_brier"] - row["brier"] for row in folds]
            ),
            "mean_log_loss_uplift_vs_constant": _mean(
                [row["constant_log_loss"] - row["log_loss"] for row in folds]
            ),
            "positive_brier_uplift_fold_count": sum(
                row["constant_brier"] > row["brier"] for row in folds
            ),
            "all_purge_checks_passed": bool(folds)
            and all(row["purge_check_passed"] for row in folds),
        },
    }


def _line_action(features: Mapping[str, float]) -> str:
    above = features["sma200_distance"] > 0.0 and features["sma20_sma60_spread"] > 0.0
    below = features["sma200_distance"] < 0.0 and features["sma20_sma60_spread"] < 0.0
    return "buy" if above else "sell" if below else "hold"


def _curve_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    periods_per_year: float,
    capital: float,
) -> dict[str, Any]:
    returns = [float(row["net_return"]) for row in rows]
    equities = [capital] + [float(row["equity_usdt"]) for row in rows]
    years = sorted({str(row["decision_date"])[:4] for row in rows})
    return {
        "bar_count": len(rows),
        "return_pct": round((equities[-1] / capital - 1.0) * 100.0, 8),
        "sharpe": round(sharpe(returns, periods_per_year=periods_per_year), 8),
        "max_drawdown_pct": round(max_drawdown_pct(equities), 8),
        "average_exposure": round(_mean([float(row["weight"]) for row in rows]), 8),
        "maximum_exposure": round(max((float(row["weight"]) for row in rows), default=0.0), 8),
        "turnover": round(sum(float(row["turnover"]) for row in rows), 8),
        "decision_count": sum(bool(row["decision_action"]) for row in rows),
        "trade_count": sum(float(row["turnover"]) > 0.0 for row in rows),
        "fees_usdt": round(sum(float(row["fee_usdt"]) for row in rows), 8),
        "funding_pnl_usdt": round(sum(float(row["funding_pnl_usdt"]) for row in rows), 8),
        "annual_return_pct": {
            year: round(
                (
                    math.prod(
                        1.0 + float(row["net_return"])
                        for row in rows
                        if str(row["decision_date"]).startswith(year)
                    )
                    - 1.0
                )
                * 100.0,
                8,
            )
            for year in years
        },
    }


def run_allocation_policy(
    series: AssetSeries,
    dataset: Mapping[str, Any],
    *,
    policy: str,
    start_date: str,
    end_date: str,
    capital: float,
    prediction_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    feature_by_date = {row["decision_date"]: row["features"] for row in dataset["rows"]}
    prediction_by_date = {
        str(row["decision_date"]): str(row["predicted_label"])
        for row in prediction_rows
    }
    eligible = [
        index
        for index, date in enumerate(series.dates[:-1])
        if start_date <= date <= end_date and date in feature_by_date
    ]
    if not eligible:
        raise ValueError("allocation policy has no eligible dates")
    first = eligible[0]
    fee_rate = series.turnover_cost_bps / 10_000.0
    weight = 0.0
    equity = capital
    rows = []
    for index in eligible:
        date = series.dates[index]
        decision = (index - first) % series.decision_stride == 0
        action = ""
        wanted = weight
        if decision:
            if policy == "buy_hold":
                action, wanted = "buy", 1.0
            elif policy == "classic_dca":
                action, wanted = "buy", min(weight + series.allocation_step, 1.0)
            elif policy in {"line_dca_dcr", "line_full_cash"}:
                action = _line_action(feature_by_date[date])
                if policy == "line_full_cash":
                    wanted = 1.0 if action == "buy" else 0.0 if action == "sell" else weight
                elif action == "buy":
                    wanted = min(weight + series.allocation_step, 1.0)
                elif action == "sell":
                    wanted = max(weight - series.allocation_step, 0.0)
            elif policy.startswith("ml_"):
                action = prediction_by_date.get(date, "")
                if action == "buy":
                    wanted = min(weight + series.allocation_step, 1.0)
                elif action == "sell":
                    wanted = max(weight - series.allocation_step, 0.0)
            else:
                raise ValueError(f"unknown allocation policy: {policy}")
        turnover = abs(wanted - weight)
        price_return = series.closes[index + 1] / series.closes[index] - 1.0
        funding_return = -wanted * float(series.funding_returns[index])
        fee_return = turnover * fee_rate
        before = equity
        net_return = wanted * price_return + funding_return - fee_return
        equity *= 1.0 + net_return
        rows.append(
            {
                "decision_date": date,
                "outcome_date": series.dates[index + 1],
                "decision_action": action if decision else "",
                "weight": wanted,
                "turnover": turnover,
                "price_return": wanted * price_return,
                "funding_return": funding_return,
                "fee_return": -fee_return,
                "net_return": net_return,
                "equity_usdt": equity,
                "fee_usdt": before * fee_return,
                "funding_pnl_usdt": before * funding_return,
            }
        )
        weight = wanted
    return {
        "policy": policy,
        "start": rows[0]["decision_date"],
        "end": rows[-1]["outcome_date"],
        "metrics": _curve_metrics(
            rows,
            periods_per_year=series.periods_per_year,
            capital=capital,
        ),
    }


def build_periodic_allocation_report(
    series_by_asset: Mapping[str, AssetSeries],
    config: PeriodicAllocationConfig | None = None,
) -> dict[str, Any]:
    config = config or PeriodicAllocationConfig()
    assets = {}
    for asset_id, series in series_by_asset.items():
        if asset_id != series.asset_id:
            raise ValueError("asset series key mismatch")
        dataset = build_action_dataset(series, config)
        models = {
            name: run_action_walk_forward(dataset, model_name=name, seed=config.seed)
            for name in config.models
        }
        prediction_dates = sorted(
            {
                row["decision_date"]
                for model in models.values()
                for row in model["predictions"]
            }
        )
        walk_start = prediction_dates[0] if prediction_dates else config.start_date
        deterministic = {
            policy: run_allocation_policy(
                series,
                dataset,
                policy=policy,
                start_date=config.start_date,
                end_date=config.end_date,
                capital=config.capital_usdt,
            )
            for policy in ("buy_hold", "classic_dca", "line_dca_dcr", "line_full_cash")
        }
        walk_forward = {
            "buy_hold": run_allocation_policy(
                series,
                dataset,
                policy="buy_hold",
                start_date=walk_start,
                end_date=config.end_date,
                capital=config.capital_usdt,
            ),
            "line_dca_dcr": run_allocation_policy(
                series,
                dataset,
                policy="line_dca_dcr",
                start_date=walk_start,
                end_date=config.end_date,
                capital=config.capital_usdt,
            ),
        }
        for name, model in models.items():
            walk_forward[f"ml_{name}_dca_dcr"] = run_allocation_policy(
                series,
                dataset,
                policy=f"ml_{name}_dca_dcr",
                start_date=walk_start,
                end_date=config.end_date,
                capital=config.capital_usdt,
                prediction_rows=model["predictions"],
            )
        assets[asset_id] = {
            "series_contract": {
                "periods_per_year": series.periods_per_year,
                "decision_stride": series.decision_stride,
                "allocation_step": series.allocation_step,
                "turnover_cost_bps": series.turnover_cost_bps,
            },
            "dataset": dataset["diagnostics"],
            "models": models,
            "full_history_policies": deterministic,
            "walk_forward_policies": walk_forward,
        }
    model_trials = len(series_by_asset) * len(config.models)
    policy_trials = len(series_by_asset) * 4
    return {
        "schema_version": PERIODIC_ALLOCATION_VERSION,
        "artifact_type": "mini_trend_periodic_allocation_discovery",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "private_exchange_data": False,
            "network_downloaded": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract": asdict(config)
        | {
            "contract_hash": config.contract_hash,
            "model_trial_count": model_trials,
            "policy_trial_count": policy_trials,
            "total_trial_count": model_trials + policy_trials,
            "external_cash_contributions_assumed": False,
            "shorting_allowed": False,
            "maximum_effective_gross": 1.0,
        },
        "assets": assets,
        "diagnostics": {
            "model_targets_are_future_economic_outcomes": True,
            "model_targets_clone_moving_average_rules": False,
            "interpretation": (
                "Line policies test deterministic scaling. ML uses causal features and future "
                "barrier labels; all results remain consumed-history discovery."
            ),
        },
    }


def write_periodic_allocation_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-periodic-allocation",
        path_key="artifact_path",
        default_filename="mini_trend_periodic_allocation.json",
        explicit_path=explicit_path,
    )
