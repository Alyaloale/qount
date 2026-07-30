from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.metrics import brier_score_loss
from sklearn.metrics import log_loss
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar
from qount.research_data.market_data import Funding
from qount.research_data.market_data import load_funding
from qount.research_data.market_data import load_klines
from qount.models import utc_now
from qount.research_data.metrics import deflated_sharpe_ratio
from qount.research_data.metrics import sharpe
from qount.settings import Settings

from .exchange_rules import SymbolRules
from .exchange_rules import evaluate_period_filter_coverage
from .exchange_rules import load_symbol_rules
from .historical_depth import HISTORICAL_DEPTH_VERSION
from .historical_premium import HISTORICAL_PREMIUM_VERSION
from .premium_dislocation import aggregate_premium_to_hourly
from .tradeflow_experiment import HOUR_MS
from .tradeflow_experiment import FrozenTradeFlowContract
from .tradeflow_experiment import TradeFlowExperimentConfig
from .tradeflow_experiment import _align_bars
from .tradeflow_experiment import _build_periods
from .tradeflow_experiment import _information_coefficient
from .tradeflow_experiment import _rolling_beta_before_decision
from .tradeflow_experiment import _score_periods


RESIDUAL_TREND_MODEL_VERSION = "alpha_agent_residual_trend_model_v0.1"
FEATURE_NAMES = (
    "depth_imbalance_1pct_mean",
    "depth_imbalance_5pct_mean",
    "depth_imbalance_1pct_std",
    "near_depth_share_mean",
    "premium_index_mean",
    "mark_index_basis_mean",
    "return_1h_pct",
    "return_6h_pct",
    "realized_vol_24h_pct",
    "btc_return_6h_pct",
)


@dataclass(frozen=True)
class FrozenResidualTrendModelContract(FrozenTradeFlowContract):
    contract_id: str = "depth_premium_price_logit_l2_h6_low_turnover_v1"
    source_feature: str = "fixed_tabular_residual_trend_probability"
    entry_zscore: float = 0.10
    model_family: str = "sklearn_logistic_regression_l2"
    feature_names: tuple[str, ...] = FEATURE_NAMES
    target: str = "forward_6h_btc_beta_residual_return_gt_zero"
    train_start_utc: str = "2024-01-01T00:00:00+00:00"
    train_end_utc: str = "2024-03-01T00:00:00+00:00"
    test_start_utc: str = "2024-03-01T00:00:00+00:00"
    test_end_utc: str = "2024-04-01T00:00:00+00:00"
    purge_hours: int = 6
    regularization_c: float = 1.0
    max_iterations: int = 2000
    probability_long: float = 0.55
    probability_short: float = 0.45
    cv_splits: int = 5
    minimum_auc: float = 0.52
    minimum_brier_improvement: float = 0.0
    minimum_cv_positive_ic_fraction: float = 0.60


FROZEN_RESIDUAL_TREND_MODEL_CONTRACT = FrozenResidualTrendModelContract()


@dataclass(frozen=True)
class ResidualTrendModelProtocol:
    protocol_id: str = "fixed_tabular_residual_trend_cross_symbol_discovery_v1"
    discovery_symbols: tuple[str, ...] = ("ETHUSDT", "BNBUSDT", "SOLUSDT")
    benchmark_symbol: str = "BTCUSDT"
    discovery_window: str = "train=2024-01..02, test=2024-03"
    reserved_oos_window: str = "2024-04"
    contract_hash: str = FROZEN_RESIDUAL_TREND_MODEL_CONTRACT.contract_hash
    minimum_passing_symbol_count: int = 2
    minimum_positive_residual_count: int = 2
    minimum_mean_net_residual_pct: float = 0.0
    minimum_filter_coverage: float = 1.0
    maximum_rolling_24h_turnover: float = 2.0
    selection_trials: int = 1
    pbo_policy: str = "single fixed model is non-identifiable for PBO and remains blocking at 1.0"
    a10_policy: str = "sequence model remains disabled until independent OOS and G4/G5 pass"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def protocol_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()


FROZEN_RESIDUAL_TREND_MODEL_PROTOCOL = ResidualTrendModelProtocol()


@dataclass(frozen=True)
class ResidualTrendModelConfig:
    depth_path: str
    premium_path: str
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    strategy_symbol: str = "ETHUSDT"
    market: str = "um"
    kline_cache_dir: str = "state/alpha_agents/binance_klines"
    funding_cache_dir: str = "state/alpha_agents/binance_funding"
    exchange_rules_path: str | None = None
    include_funding: bool = True
    fee_pct: float = 0.0005
    slippage_pct: float = 0.0002
    account_equity_usdt: float = 400.0
    target_notional_fraction: float = 1.0
    leverage: float = 1.0
    min_feature_coverage: float = 0.98
    holdout_role: str = "discovery"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ts(raw: str) -> int:
    return int(dt.datetime.fromisoformat(raw).timestamp() * 1000)


def build_residual_trend_model_preregistration(
    protocol: ResidualTrendModelProtocol = FROZEN_RESIDUAL_TREND_MODEL_PROTOCOL,
) -> dict[str, Any]:
    return {
        "schema_version": RESIDUAL_TREND_MODEL_VERSION,
        "artifact_type": "preregistration",
        "created_at": utc_now().isoformat(),
        "contract": {
            **FROZEN_RESIDUAL_TREND_MODEL_CONTRACT.to_dict(),
            "contract_hash": FROZEN_RESIDUAL_TREND_MODEL_CONTRACT.contract_hash,
        },
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "diagnostics": {
            "verdict": "preregistered",
            "model_results_evaluated": False,
            "reserved_oos_consumed": False,
            "a10_sequence_enabled": False,
            "hyperparameter_tuning_allowed": False,
            "next_action": "fit the exact fixed model per registered symbol and evaluate March once",
        },
        "hard_boundaries": [
            "The model predicts six-hour BTC-beta-residual direction, not raw price direction.",
            "Feature list, logistic family, regularization, split, purge, probability thresholds, and costs are frozen before evaluation.",
            "No grid search, feature selection, probability-threshold tuning, symbol dropping, or March refit is allowed.",
            "April remains unconsumed unless at least two of three fixed March models pass discovery gates.",
            "Model output is a research probability artifact; it cannot authorize target weights, A10 sequence training, paper, live, or orders.",
        ],
    }


def _load_source(path: str, version: str, rows_key: str) -> tuple[dict[str, Any], str]:
    source = Path(path).expanduser()
    blob = source.read_bytes()
    payload = json.loads(blob)
    if payload.get("schema_version") != version or not isinstance(payload.get(rows_key), list):
        raise ValueError(f"invalid model source artifact: {source}")
    return payload, hashlib.sha256(blob).hexdigest()


def aggregate_depth_to_hourly(rows: list[dict[str, Any]], *, symbol: str) -> list[dict[str, Any]]:
    selected = [
        row
        for row in rows
        if str(row.get("symbol", "")).upper() == symbol.upper() and bool(row.get("complete"))
    ]
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in selected:
        ts_ms = int(row["ts_ms"])
        buckets.setdefault(ts_ms // HOUR_MS * HOUR_MS, []).append(row)
    result: list[dict[str, Any]] = []
    for hour_ts in sorted(buckets):
        bucket = sorted(buckets[hour_ts], key=lambda row: int(row["ts_ms"]))
        expected = [hour_ts + offset * 5 * 60_000 for offset in range(12)]
        actual = [int(row["ts_ms"]) for row in bucket]
        segments = {int(row.get("segment_id", -1)) for row in bucket}
        if actual != expected or len(segments) != 1:
            continue
        count = sum(int(row["snapshot_count"]) for row in bucket)
        if count <= 0:
            continue

        def pooled(field_mean: str, field_std: str | None = None) -> tuple[float, float]:
            mean = sum(float(row[field_mean]) * int(row["snapshot_count"]) for row in bucket) / count
            if field_std is None:
                return mean, 0.0
            second = sum(
                (float(row[field_std]) ** 2 + float(row[field_mean]) ** 2)
                * int(row["snapshot_count"])
                for row in bucket
            ) / count
            return mean, math.sqrt(max(0.0, second - mean * mean))

        imbalance_1, imbalance_1_std = pooled(
            "depth_imbalance_1pct_mean", "depth_imbalance_1pct_std"
        )
        imbalance_5, _ = pooled("depth_imbalance_5pct_mean", "depth_imbalance_5pct_std")
        near_share, _ = pooled("near_depth_share_mean")
        result.append(
            {
                "symbol": symbol.upper(),
                "hour_ts_ms": hour_ts,
                "decision_ts_ms": hour_ts + HOUR_MS,
                "segment_id": next(iter(segments)),
                "snapshot_count": count,
                "depth_imbalance_1pct_mean": imbalance_1,
                "depth_imbalance_5pct_mean": imbalance_5,
                "depth_imbalance_1pct_std": imbalance_1_std,
                "near_depth_share_mean": near_share,
            }
        )
    return result


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _build_model_samples(
    *,
    depth_hourly: list[dict[str, Any]],
    premium_hourly: list[dict[str, Any]],
    aligned: list[tuple[int, dict[str, Bar]]],
    strategy_symbol: str,
    contract: FrozenResidualTrendModelContract,
) -> list[dict[str, Any]]:
    depth_by_decision = {int(row["decision_ts_ms"]): row for row in depth_hourly}
    premium_by_decision = {int(row["decision_ts_ms"]): row for row in premium_hourly}
    index_by_ts = {ts_ms: index for index, (ts_ms, _bars) in enumerate(aligned)}
    decisions = sorted(set(depth_by_decision) & set(premium_by_decision) & set(index_by_ts))
    samples: list[dict[str, Any]] = []
    for decision_ts in decisions:
        index = index_by_ts[decision_ts]
        if index < 25 or index + contract.holding_hours - 1 >= len(aligned):
            continue
        if aligned[index + contract.holding_hours - 1][0] - decision_ts != (
            contract.holding_hours - 1
        ) * HOUR_MS:
            continue
        beta = _rolling_beta_before_decision(
            aligned,
            index=index,
            strategy_symbol=strategy_symbol,
            lookback=contract.beta_lookback_hours,
        )
        if beta is None:
            continue
        completed = aligned[index - 1][1]
        six_hour_base = aligned[index - 7][1]
        start = aligned[index - 1][1]
        end = aligned[index + contract.holding_hours - 1][1]
        strategy_forward = (
            end[strategy_symbol].close / start[strategy_symbol].close - 1.0
        ) * 100.0
        btc_forward = (end["BTCUSDT"].close / start["BTCUSDT"].close - 1.0) * 100.0
        residual_forward = strategy_forward - beta * btc_forward
        hourly_returns = []
        for return_index in range(index - 24, index):
            current = aligned[return_index][1][strategy_symbol].close
            previous = aligned[return_index - 1][1][strategy_symbol].close
            hourly_returns.append((current / previous - 1.0) * 100.0)
        depth = depth_by_decision[decision_ts]
        premium = premium_by_decision[decision_ts]
        features = {
            "depth_imbalance_1pct_mean": float(depth["depth_imbalance_1pct_mean"]),
            "depth_imbalance_5pct_mean": float(depth["depth_imbalance_5pct_mean"]),
            "depth_imbalance_1pct_std": float(depth["depth_imbalance_1pct_std"]),
            "near_depth_share_mean": float(depth["near_depth_share_mean"]),
            "premium_index_mean": float(premium["premium_index_mean"]),
            "mark_index_basis_mean": float(premium["mark_index_basis_mean"]),
            "return_1h_pct": (
                completed[strategy_symbol].close / completed[strategy_symbol].open - 1.0
            ) * 100.0,
            "return_6h_pct": (
                completed[strategy_symbol].close / six_hour_base[strategy_symbol].close - 1.0
            ) * 100.0,
            "realized_vol_24h_pct": math.sqrt(_variance(hourly_returns)),
            "btc_return_6h_pct": (
                completed["BTCUSDT"].close / six_hour_base["BTCUSDT"].close - 1.0
            ) * 100.0,
        }
        if not all(math.isfinite(value) for value in features.values()):
            continue
        samples.append(
            {
                "decision_ts_ms": decision_ts,
                "feature_values": [features[name] for name in contract.feature_names],
                "features": features,
                "target": int(residual_forward > 0.0),
                "residual_forward_return_pct": residual_forward,
                "beta_to_btc": beta,
            }
        )
    return samples


def _fit_model(
    train_rows: list[dict[str, Any]],
    *,
    contract: FrozenResidualTrendModelContract,
) -> tuple[StandardScaler, LogisticRegression]:
    x = np.asarray([row["feature_values"] for row in train_rows], dtype=float)
    y = np.asarray([row["target"] for row in train_rows], dtype=int)
    if len(set(y.tolist())) < 2:
        raise ValueError("training labels must contain both directions")
    scaler = StandardScaler()
    scaled = scaler.fit_transform(x)
    model = LogisticRegression(
        C=contract.regularization_c,
        solver="lbfgs",
        max_iter=contract.max_iterations,
        random_state=0,
    )
    model.fit(scaled, y)
    return scaler, model


def _predict(
    scaler: StandardScaler,
    model: LogisticRegression,
    rows: list[dict[str, Any]],
) -> list[float]:
    x = np.asarray([row["feature_values"] for row in rows], dtype=float)
    return [float(value) for value in model.predict_proba(scaler.transform(x))[:, 1]]


def _rank_ic(probabilities: list[float], rows: list[dict[str, Any]]) -> float:
    return float(
        _information_coefficient(
            [(value - 0.5) * 2.0 for value in probabilities],
            [float(row["residual_forward_return_pct"]) for row in rows],
        )["rank_ic"]
    )


def _walk_forward_cv(
    rows: list[dict[str, Any]],
    *,
    contract: FrozenResidualTrendModelContract,
) -> dict[str, Any]:
    splitter = TimeSeriesSplit(n_splits=contract.cv_splits, gap=contract.purge_hours)
    folds: list[dict[str, Any]] = []
    indices = np.arange(len(rows))
    for fold, (train_index, test_index) in enumerate(splitter.split(indices)):
        train = [rows[int(index)] for index in train_index]
        test = [rows[int(index)] for index in test_index]
        scaler, model = _fit_model(train, contract=contract)
        probabilities = _predict(scaler, model, test)
        targets = [int(row["target"]) for row in test]
        auc = roc_auc_score(targets, probabilities) if len(set(targets)) > 1 else 0.5
        rank_ic = _rank_ic(probabilities, test)
        folds.append(
            {
                "fold": fold,
                "train_count": len(train),
                "test_count": len(test),
                "test_start_ms": int(test[0]["decision_ts_ms"]),
                "test_end_ms": int(test[-1]["decision_ts_ms"]),
                "auc": float(auc),
                "rank_ic": rank_ic,
                "brier": float(brier_score_loss(targets, probabilities)),
            }
        )
    positive_fraction = sum(row["rank_ic"] > 0 for row in folds) / len(folds) if folds else 0.0
    return {
        "fold_count": len(folds),
        "positive_rank_ic_fold_count": sum(row["rank_ic"] > 0 for row in folds),
        "positive_rank_ic_fold_fraction": positive_fraction,
        "mean_auc": statistics.fmean(row["auc"] for row in folds) if folds else 0.0,
        "mean_rank_ic": statistics.fmean(row["rank_ic"] for row in folds) if folds else 0.0,
        "folds": folds,
    }


def _calibration(probabilities: list[float], targets: list[int]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for lower in (0.0, 0.2, 0.4, 0.6, 0.8):
        upper = lower + 0.2
        indices = [
            index
            for index, value in enumerate(probabilities)
            if lower <= value < upper or (upper == 1.0 and value == 1.0)
        ]
        result.append(
            {
                "lower": lower,
                "upper": upper,
                "count": len(indices),
                "mean_probability": statistics.fmean(probabilities[index] for index in indices) if indices else None,
                "positive_rate": statistics.fmean(targets[index] for index in indices) if indices else None,
            }
        )
    return result


def _daily_residual_dsr(periods: list[dict[str, Any]], beta: float) -> dict[str, Any]:
    buckets: dict[str, list[float]] = {}
    for row in periods:
        day = dt.datetime.fromtimestamp(int(row["ts"]) / 1000, dt.UTC).strftime("%Y-%m-%d")
        residual = float(row["strategy_return_pct"]) - beta * float(row["btc_return_pct"])
        buckets.setdefault(day, []).append(residual)
    daily = [sum(values) for _day, values in sorted(buckets.items())]
    if len(daily) < 2:
        return {"daily_count": len(daily), "sharpe": 0.0, "dsr": 0.0}
    mean = statistics.fmean(daily)
    m2 = statistics.fmean((value - mean) ** 2 for value in daily)
    skew = statistics.fmean((value - mean) ** 3 for value in daily) / (m2 ** 1.5) if m2 > 0 else 0.0
    kurt = statistics.fmean((value - mean) ** 4 for value in daily) / (m2 * m2) if m2 > 0 else 3.0
    observed = sharpe(daily)
    return {
        "daily_count": len(daily),
        "sharpe": observed,
        "skew": skew,
        "kurtosis": kurt,
        "dsr": deflated_sharpe_ratio(
            observed,
            n_obs=len(daily),
            sr_benchmark=0.0,
            skew=skew,
            kurt=kurt,
        ),
    }


def build_residual_trend_model_experiment(
    config: ResidualTrendModelConfig,
    *,
    contract: FrozenResidualTrendModelContract = FROZEN_RESIDUAL_TREND_MODEL_CONTRACT,
    bars_by_symbol: dict[str, list[Bar]] | None = None,
    funding: list[Funding] | None = None,
    rules_by_symbol: dict[str, SymbolRules] | None = None,
) -> dict[str, Any]:
    if config.holdout_role != "discovery":
        raise ValueError("v0 model runner is discovery-only")
    if "BTCUSDT" not in config.symbols or config.strategy_symbol not in config.symbols:
        raise ValueError("symbols must include BTCUSDT and strategy_symbol")
    depth, depth_hash = _load_source(config.depth_path, HISTORICAL_DEPTH_VERSION, "five_minute_features")
    premium, premium_hash = _load_source(config.premium_path, HISTORICAL_PREMIUM_VERSION, "five_minute_features")
    start = (2024, 1)
    end = (2024, 3)
    if bars_by_symbol is None:
        bars_by_symbol = {
            symbol: load_klines(
                symbol,
                "1h",
                start=start,
                end=end,
                market=config.market,
                cache_dir=config.kline_cache_dir,
                skip_missing=True,
            )
            for symbol in config.symbols
        }
    aligned = _align_bars(bars_by_symbol, config.symbols)
    if not aligned:
        raise ValueError("no common hourly price bars")
    depth_hourly = aggregate_depth_to_hourly(
        depth["five_minute_features"], symbol=config.strategy_symbol
    )
    premium_hourly = aggregate_premium_to_hourly(
        premium["five_minute_features"], symbol=config.strategy_symbol
    )
    samples = _build_model_samples(
        depth_hourly=depth_hourly,
        premium_hourly=premium_hourly,
        aligned=aligned,
        strategy_symbol=config.strategy_symbol,
        contract=contract,
    )
    train_start = _ts(contract.train_start_utc)
    train_end = _ts(contract.train_end_utc)
    test_start = _ts(contract.test_start_utc)
    test_end = _ts(contract.test_end_utc)
    train = [
        row
        for row in samples
        if train_start <= int(row["decision_ts_ms"])
        and int(row["decision_ts_ms"]) + contract.holding_hours * HOUR_MS <= train_end
    ]
    test = [
        row
        for row in samples
        if test_start <= int(row["decision_ts_ms"])
        and int(row["decision_ts_ms"]) + contract.holding_hours * HOUR_MS <= test_end
    ]
    if len(train) < 200 or len(test) < 100:
        raise ValueError("insufficient train/test model samples")
    scaler, model = _fit_model(train, contract=contract)
    probabilities = _predict(scaler, model, test)
    targets = [int(row["target"]) for row in test]
    train_positive_rate = statistics.fmean(int(row["target"]) for row in train)
    auc = float(roc_auc_score(targets, probabilities)) if len(set(targets)) > 1 else 0.5
    brier = float(brier_score_loss(targets, probabilities))
    baseline_brier = float(brier_score_loss(targets, [train_positive_rate] * len(targets)))
    predictions = []
    prediction_features = []
    for row, probability in zip(test, probabilities):
        signal = (probability - 0.5) * 2.0
        predictions.append(
            {
                "decision_ts_ms": int(row["decision_ts_ms"]),
                "probability_positive_residual": probability,
                "signed_confidence": signal,
                "target": int(row["target"]),
                "residual_forward_return_pct": float(row["residual_forward_return_pct"]),
            }
        )
        prediction_features.append(
            {
                "decision_ts_ms": int(row["decision_ts_ms"]),
                "segment_id": 0,
                "signal_zscore": signal,
                "raw_feature_value": probability,
            }
        )
    if funding is None:
        funding = (
            load_funding(
                config.strategy_symbol,
                start=start,
                end=end,
                cache_dir=config.funding_cache_dir,
                skip_missing=True,
            )
            if config.include_funding
            else []
        )
    eval_config = TradeFlowExperimentConfig(
        tradeflow_path=config.depth_path,
        symbols=config.symbols,
        strategy_symbol=config.strategy_symbol,
        start_month="2024-01",
        end_month="2024-03",
        evaluation_start_month="2024-03",
        evaluation_end_month="2024-03",
        holdout_role="discovery",
        market=config.market,
        fee_pct=config.fee_pct,
        slippage_pct=config.slippage_pct,
        account_equity_usdt=config.account_equity_usdt,
        target_notional_fraction=config.target_notional_fraction,
        leverage=config.leverage,
        include_funding=config.include_funding,
    )
    periods, execution = _build_periods(
        aligned,
        prediction_features,
        config=eval_config,
        contract=contract,
        funding=funding,
        evaluation_start_ms=test_start,
        evaluation_end_ms=test_end,
    )
    score = _score_periods(periods)
    if rules_by_symbol is None and config.exchange_rules_path:
        rules_by_symbol = load_symbol_rules(config.exchange_rules_path, market=config.market)
    filter_diagnostics = (
        evaluate_period_filter_coverage(
            periods,
            rules_by_symbol,
            symbol=config.strategy_symbol,
            account_equity_usdt=config.account_equity_usdt,
            target_notional_fraction=config.target_notional_fraction,
            leverage=config.leverage,
        )
        if rules_by_symbol is not None
        else {
            "order_count": 0,
            "filter_coverage": 0.0,
            "min_notional_coverage": 0.0,
            "failure_reasons": {"exchange_rules_missing": 1},
        }
    )
    rank_ic = _rank_ic(probabilities, test)
    cv = _walk_forward_cv(train, contract=contract)
    active_probability_count = sum(
        value >= contract.probability_long or value <= contract.probability_short
        for value in probabilities
    )
    feature_coverage = len(samples) / max(1, len(set(row["decision_ts_ms"] for row in depth_hourly)))
    blockers: list[str] = []
    if depth.get("diagnostics", {}).get("verdict") != "pass_data_smoke":
        blockers.append("source_depth_blocked")
    if premium.get("diagnostics", {}).get("verdict") != "pass_data_smoke":
        blockers.append("source_premium_blocked")
    if feature_coverage < config.min_feature_coverage:
        blockers.append("feature_coverage_below_threshold")
    if auc < contract.minimum_auc:
        blockers.append("auc_below_frozen_gate")
    if rank_ic < contract.minimum_rank_ic:
        blockers.append("rank_ic_below_frozen_gate")
    if baseline_brier - brier <= contract.minimum_brier_improvement:
        blockers.append("brier_not_better_than_constant_baseline")
    if cv["positive_rank_ic_fold_fraction"] < contract.minimum_cv_positive_ic_fraction:
        blockers.append("walk_forward_ic_stability_below_gate")
    if score["net_residual_return_pct"] <= 0:
        blockers.append("cost_adjusted_beta_residual_non_positive")
    if execution["entry_count"] < contract.minimum_entry_count:
        blockers.append("entry_count_below_minimum")
    if execution["max_rolling_24h_turnover"] > contract.maximum_rolling_24h_turnover + 1e-12:
        blockers.append("turnover_budget_exceeded")
    if filter_diagnostics["min_notional_coverage"] < 1.0:
        blockers.append("exchange_filter_coverage_incomplete")
    if not config.include_funding:
        blockers.append("funding_not_included")
    passed = not blockers
    model_card = {
        "family": contract.model_family,
        "feature_names": list(contract.feature_names),
        "scaler_mean": [float(value) for value in scaler.mean_],
        "scaler_scale": [float(value) for value in scaler.scale_],
        "coefficients": {
            name: float(value) for name, value in zip(contract.feature_names, model.coef_[0])
        },
        "intercept": float(model.intercept_[0]),
        "classes": [int(value) for value in model.classes_],
        "iterations": [int(value) for value in model.n_iter_],
    }
    source_hashes = {"depth": depth_hash, "premium": premium_hash}
    config_hash = hashlib.sha256(
        json.dumps({"config": config.to_dict(), "contract": contract.to_dict()}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    dsr = _daily_residual_dsr(periods, float(score["beta_to_btc"]))
    return {
        "schema_version": RESIDUAL_TREND_MODEL_VERSION,
        "artifact_type": "model_experiment",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "orders_allowed": False,
            "point_in_time": True,
            "as_of_join": True,
            "replayable": True,
            "trial_count": 1,
            "model_selection_performed": False,
            "sequence_model": False,
            "a10_sequence_enabled": False,
            "costs_included": True,
            "funding_included": config.include_funding,
            "source_hashes": source_hashes,
            "config_hash": config_hash,
            "contract_hash": contract.contract_hash,
            "holdout_role": config.holdout_role,
            "label_spec": contract.target,
            "cost_spec": "5bps taker + 2bps slippage per position change plus funding",
        },
        "config": config.to_dict(),
        "decision_contract": {
            **contract.to_dict(),
            "contract_hash": contract.contract_hash,
            "frozen_before_model_evaluation": True,
            "selection_trials": 1,
        },
        "model_card": model_card,
        "diagnostics": {
            "verdict": "advance_to_independent_oos" if passed else "block_discovery",
            "blockers": blockers,
            "train_sample_count": len(train),
            "test_sample_count": len(test),
            "train_positive_rate": train_positive_rate,
            "test_positive_rate": statistics.fmean(targets),
            "feature_coverage": feature_coverage,
            "active_probability_count": active_probability_count,
            "prediction": {
                "auc": auc,
                "accuracy": float(accuracy_score(targets, [int(value >= 0.5) for value in probabilities])),
                "brier": brier,
                "constant_baseline_brier": baseline_brier,
                "brier_improvement": baseline_brier - brier,
                "log_loss": float(log_loss(targets, probabilities)),
                "rank_ic": rank_ic,
                "calibration": _calibration(probabilities, targets),
            },
            "walk_forward": cv,
            "score": score,
            "execution": execution,
            "filter_diagnostics": filter_diagnostics,
            "anti_overfit": {
                "deflated_sharpe_ratio": dsr["dsr"],
                "daily_residual": dsr,
                "pbo": 1.0,
                "pbo_status": "non_identifiable_single_fixed_model_fail_closed",
                "promotion_g4_pass": False,
            },
            "reserved_oos_consumed": False,
            "promotion_note": "A fixed tabular discovery model cannot authorize A10 sequence, paper, live, or orders.",
        },
        "predictions": predictions,
        "periods": periods,
    }


def _load_json(path: str | Path) -> tuple[dict[str, Any], Path, str]:
    source = Path(path).expanduser().resolve()
    blob = source.read_bytes()
    return json.loads(blob), source, hashlib.sha256(blob).hexdigest()


def _summary(payload: dict[str, Any], path: Path, digest: str) -> dict[str, Any]:
    diagnostics = payload.get("diagnostics", {})
    prediction = diagnostics.get("prediction", {})
    return {
        "symbol": str(payload.get("config", {}).get("strategy_symbol", "")).upper(),
        "path": str(path),
        "sha256": digest,
        "contract_hash": payload.get("decision_contract", {}).get("contract_hash"),
        "verdict": diagnostics.get("verdict"),
        "auc": float(prediction.get("auc", 0.0)),
        "rank_ic": float(prediction.get("rank_ic", 0.0)),
        "brier_improvement": float(prediction.get("brier_improvement", 0.0)),
        "net_residual_return_pct": float(diagnostics.get("score", {}).get("net_residual_return_pct", 0.0)),
        "entry_count": int(diagnostics.get("execution", {}).get("entry_count", 0)),
        "max_rolling_24h_turnover": float(
            diagnostics.get("execution", {}).get("max_rolling_24h_turnover", 0.0)
        ),
        "filter_coverage": float(diagnostics.get("filter_diagnostics", {}).get("filter_coverage", 0.0)),
        "cv_positive_ic_fraction": float(
            diagnostics.get("walk_forward", {}).get("positive_rank_ic_fold_fraction", 0.0)
        ),
        "dsr": float(diagnostics.get("anti_overfit", {}).get("deflated_sharpe_ratio", 0.0)),
        "pbo": float(diagnostics.get("anti_overfit", {}).get("pbo", 1.0)),
        "blockers": list(diagnostics.get("blockers", [])),
    }


def build_residual_trend_model_report(
    *,
    preregistration_path: str | Path,
    experiment_paths: list[str | Path],
    protocol: ResidualTrendModelProtocol = FROZEN_RESIDUAL_TREND_MODEL_PROTOCOL,
) -> dict[str, Any]:
    prereg, prereg_path, prereg_hash = _load_json(preregistration_path)
    if (
        prereg.get("schema_version") != RESIDUAL_TREND_MODEL_VERSION
        or prereg.get("artifact_type") != "preregistration"
        or prereg.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash
    ):
        raise ValueError("preregistration does not match frozen model protocol")
    summaries: dict[str, dict[str, Any]] = {}
    for raw_path in experiment_paths:
        payload, path, digest = _load_json(raw_path)
        if payload.get("schema_version") != RESIDUAL_TREND_MODEL_VERSION or payload.get("artifact_type") != "model_experiment":
            raise ValueError("invalid residual-trend model experiment")
        row = _summary(payload, path, digest)
        if row["symbol"] in summaries:
            raise ValueError(f"duplicate model experiment for {row['symbol']}")
        summaries[row["symbol"]] = row
    expected = set(protocol.discovery_symbols)
    missing = sorted(expected - set(summaries))
    unexpected = sorted(set(summaries) - expected)
    ordered = [summaries[symbol] for symbol in protocol.discovery_symbols if symbol in summaries]
    contract_mismatches = sorted(row["symbol"] for row in ordered if row["contract_hash"] != protocol.contract_hash)
    passing_count = sum(row["verdict"] == "advance_to_independent_oos" for row in ordered)
    positive_residual_count = sum(row["net_residual_return_pct"] > 0 for row in ordered)
    mean_residual = statistics.fmean(row["net_residual_return_pct"] for row in ordered) if ordered else 0.0
    filter_complete = bool(ordered) and all(row["filter_coverage"] >= protocol.minimum_filter_coverage for row in ordered)
    turnover_ok = bool(ordered) and all(
        row["max_rolling_24h_turnover"] <= protocol.maximum_rolling_24h_turnover + 1e-12
        for row in ordered
    )
    blockers: list[str] = []
    if missing:
        blockers.append("registered_symbol_missing")
    if unexpected:
        blockers.append("unexpected_symbol_present")
    if contract_mismatches:
        blockers.append("frozen_contract_mismatch")
    if passing_count < protocol.minimum_passing_symbol_count:
        blockers.append("passing_symbol_count_below_protocol")
    if positive_residual_count < protocol.minimum_positive_residual_count:
        blockers.append("positive_residual_count_below_protocol")
    if mean_residual <= protocol.minimum_mean_net_residual_pct:
        blockers.append("mean_net_residual_non_positive")
    if not filter_complete:
        blockers.append("filter_coverage_incomplete")
    if not turnover_ok:
        blockers.append("turnover_budget_exceeded")
    passed = not blockers
    return {
        "schema_version": RESIDUAL_TREND_MODEL_VERSION,
        "artifact_type": "discovery_report",
        "created_at": utc_now().isoformat(),
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "preregistration": {"path": str(prereg_path), "sha256": prereg_hash},
        "experiments": {row["symbol"]: row for row in ordered},
        "diagnostics": {
            "verdict": "advance_to_reserved_oos_preregistration" if passed else "block_discovery",
            "blockers": blockers,
            "missing_symbols": missing,
            "unexpected_symbols": unexpected,
            "contract_mismatches": contract_mismatches,
            "passing_symbol_count": passing_count,
            "positive_residual_count": positive_residual_count,
            "mean_net_residual_return_pct": mean_residual,
            "filter_coverage_complete": filter_complete,
            "turnover_within_budget": turnover_ok,
            "pbo": 1.0,
            "promotion_g4_pass": False,
            "a10_sequence_enabled": False,
            "reserved_oos_consumed": False,
            "next_action": (
                "write a separate April model OOS preregistration; keep A10 sequence disabled"
                if passed
                else "stop this fixed tabular model without feature/hyperparameter rescue on Q1"
            ),
        },
        "hard_boundary": "Probabilities are research outputs, not positions or order authorization.",
    }


def write_residual_trend_model_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-residual-trend-model",
        path_key="artifact_path",
        default_filename="alpha_agent_residual_trend_model.json",
        explicit_path=explicit_path,
    )
