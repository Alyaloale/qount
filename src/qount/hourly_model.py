from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .exchange_utils import build_exchange
from .exchange_utils import resolve_market_symbols
from .models import Candle
from .settings import Settings
from .trade_policy import timeframe_to_ms


HOURLY_MODEL_VERSION = "hourly_ridge_v1"
HOURLY_MODEL_TIMEFRAME = "1h"
HOURLY_MODEL_MIN_CANDLES = 18
HOURLY_MODEL_FEATURE_NAMES = (
    "return_1bar",
    "return_3bars",
    "return_6bars",
    "return_12bars",
    "sma_fast_ratio",
    "sma_slow_ratio",
    "fast_sma_slope",
    "slow_sma_slope",
    "rsi_centered",
    "volume_ratio_6",
    "range_ratio_6",
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float], mean_value: float) -> float:
    if not values:
        return 1.0
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(max(variance, 1e-12))


def _sma(values: list[float], period: int) -> float:
    return _mean(values[-period:])


def _rsi(closes: list[float], period: int) -> float:
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(closes[-(period + 1):-1], closes[-period:]):
        delta = current - previous
        if delta >= 0.0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-delta)
    average_gain = _mean(gains)
    average_loss = _mean(losses)
    if average_loss <= 0.0:
        return 100.0
    rs = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + rs))


def build_hourly_model_feature_map(completed_candles: list[Candle]) -> dict[str, float]:
    if len(completed_candles) < HOURLY_MODEL_MIN_CANDLES:
        raise ValueError(f"not_enough_hourly_candles:{len(completed_candles)}")
    closes = [candle.close for candle in completed_candles]
    volumes = [candle.volume for candle in completed_candles]
    range_pcts = [
        0.0 if candle.close <= 0.0 else max(candle.high - candle.low, 0.0) / candle.close
        for candle in completed_candles
    ]
    sma_fast = _sma(closes, 6)
    sma_slow = _sma(closes, 12)
    previous_sma_fast = _sma(closes[:-1], 6)
    previous_sma_slow = _sma(closes[:-1], 12)
    return {
        "return_1bar": (closes[-1] / closes[-2]) - 1.0,
        "return_3bars": (closes[-1] / closes[-4]) - 1.0,
        "return_6bars": (closes[-1] / closes[-7]) - 1.0,
        "return_12bars": (closes[-1] / closes[-13]) - 1.0,
        "sma_fast_ratio": (closes[-1] / sma_fast) - 1.0,
        "sma_slow_ratio": (closes[-1] / sma_slow) - 1.0,
        "fast_sma_slope": (sma_fast / previous_sma_fast) - 1.0,
        "slow_sma_slope": (sma_slow / previous_sma_slow) - 1.0,
        "rsi_centered": (_rsi(closes, 14) - 50.0) / 50.0,
        "volume_ratio_6": volumes[-1] / max(_mean(volumes[-7:-1]), 1e-9),
        "range_ratio_6": range_pcts[-1] / max(_mean(range_pcts[-7:-1]), 1e-9),
    }


def _feature_vector(feature_map: dict[str, float]) -> list[float]:
    return [float(feature_map[name]) for name in HOURLY_MODEL_FEATURE_NAMES]


def _fit_linear_regression(
    x_rows: list[list[float]],
    y_values: list[float],
    *,
    ridge_alpha: float,
    epochs: int = 600,
    learning_rate: float = 0.05,
) -> tuple[list[float], float]:
    weights = [0.0] * len(x_rows[0])
    bias = _mean(y_values)
    sample_count = max(len(y_values), 1)
    for _ in range(epochs):
        gradient_weights = [0.0] * len(weights)
        gradient_bias = 0.0
        for x_row, target in zip(x_rows, y_values):
            prediction = bias + sum(weight * feature for weight, feature in zip(weights, x_row))
            error = prediction - target
            gradient_bias += error
            for index, feature in enumerate(x_row):
                gradient_weights[index] += error * feature
        scale = 2.0 / sample_count
        bias -= learning_rate * scale * gradient_bias
        for index in range(len(weights)):
            weights[index] -= learning_rate * (scale * gradient_weights[index] + 2.0 * ridge_alpha * weights[index])
    return weights, bias


def fit_symbol_hourly_return_model(
    *,
    symbol: str,
    candles: list[Candle],
    horizon_bars: int,
    ridge_alpha: float,
) -> dict[str, object]:
    if len(candles) < (HOURLY_MODEL_MIN_CANDLES + horizon_bars + 1):
        raise ValueError(f"not_enough_training_candles:{symbol}:{len(candles)}")

    feature_rows: list[list[float]] = []
    targets: list[float] = []
    for index in range(HOURLY_MODEL_MIN_CANDLES - 1, len(candles) - horizon_bars):
        completed = candles[: index + 1]
        feature_map = build_hourly_model_feature_map(completed)
        current_close = completed[-1].close
        future_close = candles[index + horizon_bars].close
        feature_rows.append(_feature_vector(feature_map))
        targets.append((future_close / current_close) - 1.0)

    feature_means = [_mean([row[column] for row in feature_rows]) for column in range(len(HOURLY_MODEL_FEATURE_NAMES))]
    feature_stds = [_std([row[column] for row in feature_rows], feature_means[column]) for column in range(len(HOURLY_MODEL_FEATURE_NAMES))]
    standardized_rows = [
        [
            (value - feature_means[column]) / max(feature_stds[column], 1e-9)
            for column, value in enumerate(row)
        ]
        for row in feature_rows
    ]
    weights, bias = _fit_linear_regression(
        standardized_rows,
        targets,
        ridge_alpha=ridge_alpha,
    )
    predictions = [
        bias + sum(weight * feature for weight, feature in zip(weights, row))
        for row in standardized_rows
    ]
    mae_pct = _mean([abs(prediction - target) for prediction, target in zip(predictions, targets)])
    rmse_pct = math.sqrt(_mean([(prediction - target) ** 2 for prediction, target in zip(predictions, targets)]))
    directional_hits = sum(
        1
        for prediction, target in zip(predictions, targets)
        if (prediction > 0.0 and target > 0.0) or (prediction < 0.0 and target < 0.0)
    )
    return {
        "symbol": symbol,
        "version": HOURLY_MODEL_VERSION,
        "timeframe": HOURLY_MODEL_TIMEFRAME,
        "horizon_bars": horizon_bars,
        "feature_names": list(HOURLY_MODEL_FEATURE_NAMES),
        "feature_means": feature_means,
        "feature_stds": feature_stds,
        "weights": weights,
        "bias": bias,
        "metrics": {
            "sample_count": len(targets),
            "mae_pct": mae_pct,
            "rmse_pct": rmse_pct,
            "directional_accuracy": directional_hits / max(len(targets), 1),
        },
    }


def score_hourly_return_model_signal(
    *,
    symbol: str,
    completed_candles: list[Candle],
    model_bundle: dict[str, object] | None,
) -> dict[str, object] | None:
    if not isinstance(model_bundle, dict):
        return None
    symbol_models = model_bundle.get("symbols")
    if not isinstance(symbol_models, dict):
        return None
    symbol_model = symbol_models.get(symbol)
    if not isinstance(symbol_model, dict):
        return None

    feature_map = build_hourly_model_feature_map(completed_candles)
    raw_vector = _feature_vector(feature_map)
    standardized_vector = [
        (value - float(symbol_model["feature_means"][index])) / max(float(symbol_model["feature_stds"][index]), 1e-9)
        for index, value in enumerate(raw_vector)
    ]
    predicted_return_pct = float(symbol_model["bias"]) + sum(
        float(weight) * feature
        for weight, feature in zip(symbol_model["weights"], standardized_vector)
    )
    mae_pct = max(float(((symbol_model.get("metrics") or {}).get("mae_pct") or 0.0)), 1e-6)
    prediction_strength = abs(predicted_return_pct) / mae_pct
    flat_threshold_pct = max(mae_pct * 0.35, 0.0005)
    if predicted_return_pct >= flat_threshold_pct:
        direction = "long"
    elif predicted_return_pct <= -flat_threshold_pct:
        direction = "short"
    else:
        direction = "flat"
    return {
        "version": HOURLY_MODEL_VERSION,
        "timeframe": HOURLY_MODEL_TIMEFRAME,
        "horizon_bars": int(symbol_model.get("horizon_bars") or 0),
        "predicted_return_pct": predicted_return_pct,
        "prediction_strength": prediction_strength,
        "direction": direction,
        "mae_pct": mae_pct,
        "directional_accuracy": float(((symbol_model.get("metrics") or {}).get("directional_accuracy") or 0.0)),
    }


def load_hourly_model_bundle(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


@dataclass
class HourlySignalModelService:
    settings: Settings

    def _fetch_ohlcv_range(
        self,
        *,
        exchange,
        symbol: str,
        timeframe: str,
        start_ms: int,
        end_ms: int,
    ) -> list[list[float]]:
        rows: list[list[float]] = []
        cursor = max(start_ms, 0)
        timeframe_ms = timeframe_to_ms(timeframe)
        last_timestamp: int | None = None
        while cursor <= end_ms:
            batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
            if not batch:
                break
            added = 0
            for row in batch:
                timestamp = int(row[0])
                if timestamp < start_ms or timestamp > end_ms:
                    continue
                if last_timestamp is not None and timestamp <= last_timestamp:
                    continue
                rows.append(
                    [
                        timestamp,
                        float(row[1]),
                        float(row[2]),
                        float(row[3]),
                        float(row[4]),
                        float(row[5]),
                    ]
                )
                last_timestamp = timestamp
                added += 1
            if added == 0:
                break
            cursor = int(rows[-1][0]) + timeframe_ms
        return rows

    def train(
        self,
        *,
        symbols_filter: list[str] | None,
        lookback_days: int,
        horizon_bars: int,
        ridge_alpha: float,
        artifact_path: Path | None,
    ) -> dict[str, object]:
        exchange = build_exchange(self.settings, private=False)
        markets = exchange.load_markets()
        configured_symbols = tuple(symbols_filter) if symbols_filter else self.settings.symbols
        resolved_symbols = resolve_market_symbols(markets, configured_symbols, self.settings)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(lookback_days, 1))
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        models: dict[str, object] = {}
        training_summary: list[dict[str, object]] = []

        for symbol in resolved_symbols:
            rows = self._fetch_ohlcv_range(
                exchange=exchange,
                symbol=symbol,
                timeframe=HOURLY_MODEL_TIMEFRAME,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            candles = [
                Candle(
                    timestamp_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in rows
            ]
            model_payload = fit_symbol_hourly_return_model(
                symbol=symbol,
                candles=candles,
                horizon_bars=horizon_bars,
                ridge_alpha=ridge_alpha,
            )
            models[symbol] = model_payload
            training_summary.append(
                {
                    "symbol": symbol,
                    "samples": int(model_payload["metrics"]["sample_count"]),
                    "mae_pct": float(model_payload["metrics"]["mae_pct"]),
                    "directional_accuracy": float(model_payload["metrics"]["directional_accuracy"]),
                }
            )

        bundle = {
            "version": HOURLY_MODEL_VERSION,
            "timeframe": HOURLY_MODEL_TIMEFRAME,
            "horizon_bars": horizon_bars,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "symbols": models,
        }
        target_path = artifact_path or self.settings.hourly_model_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "model_path": str(target_path),
            "version": HOURLY_MODEL_VERSION,
            "timeframe": HOURLY_MODEL_TIMEFRAME,
            "horizon_bars": horizon_bars,
            "symbols": training_summary,
        }
