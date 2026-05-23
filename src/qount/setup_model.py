from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .entry_quality import FreshEntryAssessment
from .entry_quality import assess_fresh_entry
from .entry_quality import build_traditional_signal_context
from .exchange_utils import call_with_time_sync_retry
from .exchange_utils import build_exchange
from .exchange_utils import market_amount_step
from .exchange_utils import resolve_market_symbols
from .market import MIN_COMPLETED_CANDLES
from .market import build_higher_timeframe_context_from_completed_candles
from .market import build_symbol_snapshot
from .models import Candle
from .settings import Settings
from .trade_policy import estimated_action_cost_pct
from .trade_policy import timeframe_to_ms


SETUP_EDGE_MODEL_VERSION = "setup_edge_ridge_v1"
SETUP_EDGE_MODEL_TIMEFRAME = "5m"
SETUP_EDGE_MODEL_HIGHER_TIMEFRAME = "1h"
DEFAULT_SETUP_PHASES = (
    "short_breakdown_confirmed",
    "short_rebound_fail_confirmed",
    "long_pullback_reclaim_confirmed",
)
SETUP_EDGE_MODEL_FEATURE_NAMES = (
    "return_1bar",
    "return_24bars",
    "sma_fast_ratio",
    "sma_slow_ratio",
    "rsi_centered",
    "volume_ratio_20",
    "range_pct",
    "higher_trend_strength",
    "higher_fast_sma_slope",
    "higher_slow_sma_slope",
    "traditional_conviction_score",
    "traditional_terminal_risk",
    "phase_trend",
    "phase_pullback",
    "phase_reclaim",
    "phase_exhaustion",
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float], mean_value: float) -> float:
    if not values:
        return 1.0
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(max(variance, 1e-12))


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


def _feature_vector(feature_map: dict[str, float]) -> list[float]:
    return [float(feature_map[name]) for name in SETUP_EDGE_MODEL_FEATURE_NAMES]


def _summarize_edges(items: list[dict[str, object]]) -> dict[str, object]:
    targets = [float(item["target_edge_pct"]) for item in items]
    positive = [value for value in targets if value > 0.0]
    negative = [value for value in targets if value <= 0.0]
    return {
        "sample_count": len(targets),
        "positive_edge_rate": len(positive) / max(len(targets), 1),
        "avg_target_edge_pct": _mean(targets),
        "avg_positive_edge_pct": _mean(positive) if positive else None,
        "avg_negative_edge_pct": _mean(negative) if negative else None,
        "avg_conviction_score": _mean([float(item["conviction_score"]) for item in items]),
        "terminal_risk_rate": _mean([1.0 if bool(item["terminal_risk"]) else 0.0 for item in items]),
    }


def build_setup_model_feature_map(
    symbol,
    assessment: FreshEntryAssessment,
    traditional_signal_context: dict[str, object] | None,
) -> dict[str, float]:
    indicators = symbol.indicators
    higher = symbol.higher_timeframe or {}
    higher_phase = str(higher.get("trend_phase") or "range")
    return {
        "return_1bar": float(indicators.get("return_1bar") or 0.0),
        "return_24bars": float(indicators.get("return_24bars") or 0.0),
        "sma_fast_ratio": float(indicators.get("sma_fast_ratio") or 0.0),
        "sma_slow_ratio": float(indicators.get("sma_slow_ratio") or 0.0),
        "rsi_centered": (float(indicators.get("rsi_14") or 50.0) - 50.0) / 50.0,
        "volume_ratio_20": float(indicators.get("volume_ratio_20") or 0.0),
        "range_pct": float(indicators.get("range_pct") or 0.0),
        "higher_trend_strength": float(higher.get("trend_strength") or 0.0),
        "higher_fast_sma_slope": float(higher.get("fast_sma_slope") or 0.0),
        "higher_slow_sma_slope": float(higher.get("slow_sma_slope") or 0.0),
        "traditional_conviction_score": (
            0.0
            if not isinstance(traditional_signal_context, dict)
            else float(traditional_signal_context.get("conviction_score") or 0.0)
        ),
        "traditional_terminal_risk": (
            1.0
            if isinstance(traditional_signal_context, dict) and bool(traditional_signal_context.get("terminal_risk"))
            else 0.0
        ),
        "phase_trend": 1.0 if higher_phase == "trend" else 0.0,
        "phase_pullback": 1.0 if higher_phase == "pullback" else 0.0,
        "phase_reclaim": 1.0 if higher_phase == "reclaim" else 0.0,
        "phase_exhaustion": 1.0 if higher_phase == "exhaustion" else 0.0,
    }


def fit_setup_edge_model(
    *,
    symbol_name: str,
    setup_phase: str,
    feature_rows: list[list[float]],
    targets: list[float],
    ridge_alpha: float,
) -> dict[str, object]:
    feature_means = [_mean([row[column] for row in feature_rows]) for column in range(len(SETUP_EDGE_MODEL_FEATURE_NAMES))]
    feature_stds = [_std([row[column] for row in feature_rows], feature_means[column]) for column in range(len(SETUP_EDGE_MODEL_FEATURE_NAMES))]
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
    positive_edge_rate = sum(1 for target in targets if target > 0.0) / max(len(targets), 1)
    directional_hits = sum(
        1
        for prediction, target in zip(predictions, targets)
        if (prediction > 0.0 and target > 0.0) or (prediction < 0.0 and target < 0.0)
    )
    return {
        "symbol": symbol_name,
        "setup_phase": setup_phase,
        "version": SETUP_EDGE_MODEL_VERSION,
        "timeframe": SETUP_EDGE_MODEL_TIMEFRAME,
        "feature_names": list(SETUP_EDGE_MODEL_FEATURE_NAMES),
        "feature_means": feature_means,
        "feature_stds": feature_stds,
        "weights": weights,
        "bias": bias,
        "metrics": {
            "sample_count": len(targets),
            "mae_pct": mae_pct,
            "rmse_pct": rmse_pct,
            "positive_edge_rate": positive_edge_rate,
            "directional_accuracy": directional_hits / max(len(targets), 1),
            "avg_target_edge_pct": _mean(targets),
        },
    }


def score_setup_edge_model_signal(
    *,
    symbol,
    assessment: FreshEntryAssessment | None,
    traditional_signal_context: dict[str, object] | None,
    model_bundle: dict[str, object] | None,
) -> dict[str, object] | None:
    if assessment is None or assessment.action not in {"buy", "sell"}:
        return None
    if not isinstance(model_bundle, dict):
        return None
    symbol_models = model_bundle.get("symbols")
    if not isinstance(symbol_models, dict):
        return None
    symbol_entry = symbol_models.get(symbol.symbol)
    if not isinstance(symbol_entry, dict):
        return None
    model_payload = symbol_entry.get(assessment.setup_phase)
    if not isinstance(model_payload, dict):
        return None
    higher_phase = str((symbol.higher_timeframe or {}).get("trend_phase") or "unknown")
    if "by_higher_timeframe_phase" in model_payload:
        phase_models = model_payload.get("by_higher_timeframe_phase")
        if isinstance(phase_models, dict):
            phase_payload = phase_models.get(higher_phase)
            if isinstance(phase_payload, dict):
                model_payload = phase_payload
            else:
                aggregate_payload = model_payload.get("aggregate")
                if isinstance(aggregate_payload, dict):
                    model_payload = aggregate_payload

    feature_map = build_setup_model_feature_map(symbol, assessment, traditional_signal_context)
    raw_vector = _feature_vector(feature_map)
    standardized_vector = [
        (value - float(model_payload["feature_means"][index])) / max(float(model_payload["feature_stds"][index]), 1e-9)
        for index, value in enumerate(raw_vector)
    ]
    predicted_edge_pct = float(model_payload["bias"]) + sum(
        float(weight) * feature
        for weight, feature in zip(model_payload["weights"], standardized_vector)
    )
    mae_pct = max(float(((model_payload.get("metrics") or {}).get("mae_pct") or 0.0)), 1e-6)
    confidence_ratio = abs(predicted_edge_pct) / mae_pct
    threshold_pct = max(mae_pct * 0.10, 0.0002)
    if predicted_edge_pct >= threshold_pct:
        label = "favorable"
    elif predicted_edge_pct <= -threshold_pct:
        label = "unfavorable"
    else:
        label = "neutral"
    positive_edge_rate = float(((model_payload.get("metrics") or {}).get("positive_edge_rate") or 0.0))
    avg_target_edge_pct = float(((model_payload.get("metrics") or {}).get("avg_target_edge_pct") or 0.0))
    quality = "neutral"
    if label == "favorable":
        quality = (
            "strong_favorable"
            if (
                predicted_edge_pct >= 0.0025
                and confidence_ratio >= 1.5
                and positive_edge_rate >= 0.40
                and avg_target_edge_pct > 0.0
            )
            else "weak_favorable"
        )
    elif label == "unfavorable":
        quality = "unfavorable"
    return {
        "version": SETUP_EDGE_MODEL_VERSION,
        "setup_phase": assessment.setup_phase,
        "predicted_edge_pct": predicted_edge_pct,
        "confidence_ratio": confidence_ratio,
        "label": label,
        "quality": quality,
        "sample_count": int(((model_payload.get("metrics") or {}).get("sample_count") or 0)),
        "positive_edge_rate": positive_edge_rate,
        "avg_target_edge_pct": avg_target_edge_pct,
        "higher_timeframe_phase": higher_phase,
    }


def load_setup_model_bundle(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


@dataclass
class SetupEdgeModelService:
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
            batch = call_with_time_sync_retry(
                exchange,
                exchange.fetch_ohlcv,
                symbol,
                timeframe=timeframe,
                since=cursor,
                limit=1000,
            )
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

    def _collect_examples(
        self,
        *,
        symbols_filter: list[str] | None,
        setup_phases: tuple[str, ...],
        lookback_days: int,
        horizon_bars: int,
    ) -> list[dict[str, object]]:
        exchange = build_exchange(self.settings, private=False)
        markets = call_with_time_sync_retry(
            exchange,
            exchange.load_markets,
        )
        configured_symbols = tuple(symbols_filter) if symbols_filter else self.settings.symbols
        resolved_symbols = resolve_market_symbols(markets, configured_symbols, self.settings)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(lookback_days, 1))
        base_timeframe_ms = timeframe_to_ms(SETUP_EDGE_MODEL_TIMEFRAME)
        higher_timeframe_ms = timeframe_to_ms(SETUP_EDGE_MODEL_HIGHER_TIMEFRAME)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        base_fetch_start_ms = start_ms - (MIN_COMPLETED_CANDLES * base_timeframe_ms)
        higher_fetch_start_ms = start_ms - (MIN_COMPLETED_CANDLES * higher_timeframe_ms)
        rows_by_symbol: dict[str, list[list[float]]] = {}
        higher_rows_by_symbol: dict[str, list[list[float]]] = {}

        for symbol in resolved_symbols:
            rows_by_symbol[symbol] = self._fetch_ohlcv_range(
                exchange=exchange,
                symbol=symbol,
                timeframe=SETUP_EDGE_MODEL_TIMEFRAME,
                start_ms=base_fetch_start_ms,
                end_ms=end_ms + (horizon_bars * base_timeframe_ms),
            )
            higher_rows_by_symbol[symbol] = self._fetch_ohlcv_range(
                exchange=exchange,
                symbol=symbol,
                timeframe=SETUP_EDGE_MODEL_HIGHER_TIMEFRAME,
                start_ms=higher_fetch_start_ms,
                end_ms=end_ms + higher_timeframe_ms,
            )

        examples: list[dict[str, object]] = []
        for symbol in resolved_symbols:
            rows = rows_by_symbol[symbol]
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
            higher_candles = [
                Candle(
                    timestamp_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
                for row in higher_rows_by_symbol[symbol]
            ]
            market = markets[symbol]
            for index in range(MIN_COMPLETED_CANDLES - 1, len(candles) - horizon_bars):
                current = candles[index]
                if current.timestamp_ms < start_ms or current.timestamp_ms > end_ms:
                    continue
                completed = candles[: index + 1]
                higher_completed = [
                    candle
                    for candle in higher_candles
                    if candle.timestamp_ms + higher_timeframe_ms <= current.timestamp_ms + base_timeframe_ms + 1
                ]
                higher_context = (
                    None
                    if len(higher_completed) < MIN_COMPLETED_CANDLES
                    else build_higher_timeframe_context_from_completed_candles(
                        timeframe=SETUP_EDGE_MODEL_HIGHER_TIMEFRAME,
                        completed_candles=higher_completed,
                    )
                )
                snapshot = build_symbol_snapshot(
                    symbol=symbol,
                    timeframe=SETUP_EDGE_MODEL_TIMEFRAME,
                    completed_candles=completed,
                    exchange_min_cost_quote=float((((market.get("limits") or {}).get("cost") or {}).get("min")) or 0.0) or None,
                    exchange_min_amount=float((((market.get("limits") or {}).get("amount") or {}).get("min")) or 0.0) or None,
                    exchange_amount_step=market_amount_step(market),
                    higher_timeframe=higher_context,
                )
                assessment = assess_fresh_entry(snapshot)
                if assessment.setup_phase not in setup_phases or assessment.action not in {"buy", "sell"}:
                    continue
                traditional_signal_context = build_traditional_signal_context(snapshot, assessment)
                feature_map = build_setup_model_feature_map(snapshot, assessment, traditional_signal_context)
                future_close = candles[index + horizon_bars].close
                current_close = current.close
                aligned_return_pct = (
                    (future_close / current_close) - 1.0
                    if assessment.action == "buy"
                    else (current_close / future_close) - 1.0
                )
                post_cost_edge_pct = aligned_return_pct - estimated_action_cost_pct(
                    assessment.action,
                    contract_market=self.settings.contract_market,
                    fee_pct=self.settings.estimated_fee_pct,
                    slippage_pct=self.settings.estimated_slippage_pct,
                )
                examples.append(
                    {
                        "symbol": symbol,
                        "timestamp_ms": current.timestamp_ms,
                        "setup_phase": assessment.setup_phase,
                        "higher_timeframe_phase": None if higher_context is None else str(higher_context.get("trend_phase") or "unknown"),
                        "traditional_pattern_label": (
                            "unknown"
                            if not isinstance(traditional_signal_context, dict)
                            else str(traditional_signal_context.get("pattern_label") or "unknown")
                        ),
                        "target_edge_pct": post_cost_edge_pct,
                        "conviction_score": (
                            0.0
                            if not isinstance(traditional_signal_context, dict)
                            else float(traditional_signal_context.get("conviction_score") or 0.0)
                        ),
                        "terminal_risk": (
                            False
                            if not isinstance(traditional_signal_context, dict)
                            else bool(traditional_signal_context.get("terminal_risk"))
                        ),
                        "feature_vector": _feature_vector(feature_map),
                    }
                )
        return examples

    def train(
        self,
        *,
        symbols_filter: list[str] | None,
        setup_phases: list[str] | None,
        lookback_days: int,
        horizon_bars: int,
        min_samples: int,
        ridge_alpha: float,
        artifact_path: Path | None,
        split_higher_phase: bool = False,
    ) -> dict[str, object]:
        active_setup_phases = tuple(setup_phases) if setup_phases else DEFAULT_SETUP_PHASES
        examples = self._collect_examples(
            symbols_filter=symbols_filter,
            setup_phases=active_setup_phases,
            lookback_days=lookback_days,
            horizon_bars=horizon_bars,
        )
        by_symbol_setup: dict[tuple[str, str], dict[str, list]] = {}
        by_symbol_setup_phase: dict[tuple[str, str, str], dict[str, list]] = {}
        for item in examples:
            bucket = by_symbol_setup.setdefault(
                (str(item["symbol"]), str(item["setup_phase"])),
                {"features": [], "targets": []},
            )
            bucket["features"].append(list(item["feature_vector"]))
            bucket["targets"].append(float(item["target_edge_pct"]))
            phase_bucket = by_symbol_setup_phase.setdefault(
                (
                    str(item["symbol"]),
                    str(item["setup_phase"]),
                    str(item["higher_timeframe_phase"]),
                ),
                {"features": [], "targets": []},
            )
            phase_bucket["features"].append(list(item["feature_vector"]))
            phase_bucket["targets"].append(float(item["target_edge_pct"]))

        symbol_models: dict[str, dict[str, object]] = {}
        training_summary: list[dict[str, object]] = []
        aggregate_models: dict[tuple[str, str], dict[str, object]] = {}
        for (symbol, setup_phase), payload in sorted(by_symbol_setup.items()):
            feature_rows = payload["features"]
            targets = payload["targets"]
            if len(targets) < max(min_samples, 8):
                continue
            model_payload = fit_setup_edge_model(
                symbol_name=symbol,
                setup_phase=setup_phase,
                feature_rows=feature_rows,
                targets=targets,
                ridge_alpha=ridge_alpha,
            )
            aggregate_models[(symbol, setup_phase)] = model_payload
            symbol_models.setdefault(symbol, {})[setup_phase] = model_payload
            metrics = model_payload["metrics"]
            training_summary.append(
                {
                    "symbol": symbol,
                    "setup_phase": setup_phase,
                    "samples": int(metrics["sample_count"]),
                    "mae_pct": float(metrics["mae_pct"]),
                    "positive_edge_rate": float(metrics["positive_edge_rate"]),
                    "directional_accuracy": float(metrics["directional_accuracy"]),
                    "avg_target_edge_pct": float(metrics["avg_target_edge_pct"]),
                }
            )

        if split_higher_phase:
            phase_models_by_setup: dict[tuple[str, str], dict[str, dict[str, object]]] = {}
            phase_training_rows: list[dict[str, object]] = []
            for (symbol, setup_phase, higher_phase), payload in sorted(by_symbol_setup_phase.items()):
                feature_rows = payload["features"]
                targets = payload["targets"]
                if len(targets) < max(min_samples, 8):
                    continue
                model_payload = fit_setup_edge_model(
                    symbol_name=symbol,
                    setup_phase=setup_phase,
                    feature_rows=feature_rows,
                    targets=targets,
                    ridge_alpha=ridge_alpha,
                )
                phase_models_by_setup.setdefault((symbol, setup_phase), {})[higher_phase] = model_payload
                metrics = model_payload["metrics"]
                phase_training_rows.append(
                    {
                        "symbol": symbol,
                        "setup_phase": setup_phase,
                        "higher_timeframe_phase": higher_phase,
                        "samples": int(metrics["sample_count"]),
                        "mae_pct": float(metrics["mae_pct"]),
                        "positive_edge_rate": float(metrics["positive_edge_rate"]),
                        "directional_accuracy": float(metrics["directional_accuracy"]),
                        "avg_target_edge_pct": float(metrics["avg_target_edge_pct"]),
                    }
                )
            for (symbol, setup_phase), phase_models in phase_models_by_setup.items():
                aggregate_payload = aggregate_models.get((symbol, setup_phase))
                if aggregate_payload is None:
                    continue
                symbol_models.setdefault(symbol, {})[setup_phase] = {
                    "mode": "by_higher_timeframe_phase",
                    "aggregate": aggregate_payload,
                    "by_higher_timeframe_phase": phase_models,
                }
            training_summary.extend(phase_training_rows)

        bundle = {
            "version": SETUP_EDGE_MODEL_VERSION,
            "timeframe": SETUP_EDGE_MODEL_TIMEFRAME,
            "higher_timeframe": SETUP_EDGE_MODEL_HIGHER_TIMEFRAME,
            "horizon_bars": horizon_bars,
            "split_higher_phase": split_higher_phase,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "symbols": symbol_models,
        }
        target_path = artifact_path or self.settings.setup_model_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "model_path": str(target_path),
            "version": SETUP_EDGE_MODEL_VERSION,
            "timeframe": SETUP_EDGE_MODEL_TIMEFRAME,
            "higher_timeframe": SETUP_EDGE_MODEL_HIGHER_TIMEFRAME,
            "horizon_bars": horizon_bars,
            "symbols": training_summary,
        }

    def study(
        self,
        *,
        symbols_filter: list[str] | None,
        setup_phases: list[str] | None,
        lookback_days: int,
        horizon_bars: int,
        min_samples: int,
        top_k: int,
    ) -> dict[str, object]:
        active_setup_phases = tuple(setup_phases) if setup_phases else DEFAULT_SETUP_PHASES
        examples = self._collect_examples(
            symbols_filter=symbols_filter,
            setup_phases=active_setup_phases,
            lookback_days=lookback_days,
            horizon_bars=horizon_bars,
        )
        by_symbol_setup: dict[tuple[str, str], list[dict[str, object]]] = {}
        by_pattern: dict[tuple[str, str, str], list[dict[str, object]]] = {}
        by_higher_phase: dict[tuple[str, str, str], list[dict[str, object]]] = {}
        for item in examples:
            symbol = str(item["symbol"])
            setup_phase = str(item["setup_phase"])
            pattern_label = str(item["traditional_pattern_label"])
            higher_phase = str(item["higher_timeframe_phase"])
            by_symbol_setup.setdefault((symbol, setup_phase), []).append(item)
            by_pattern.setdefault((symbol, setup_phase, pattern_label), []).append(item)
            by_higher_phase.setdefault((symbol, setup_phase, higher_phase), []).append(item)

        def summarize(grouped: dict[tuple[str, ...], list[dict[str, object]]], keys: tuple[str, ...]) -> list[dict[str, object]]:
            rows: list[dict[str, object]] = []
            for key, items in grouped.items():
                if len(items) < max(min_samples, 1):
                    continue
                summary = _summarize_edges(items)
                row = {name: value for name, value in zip(keys, key)}
                row.update(summary)
                rows.append(row)
            rows.sort(key=lambda row: (float(row["avg_target_edge_pct"]), float(row["positive_edge_rate"])), reverse=True)
            return rows

        symbol_setup_rows = summarize(by_symbol_setup, ("symbol", "setup_phase"))
        pattern_rows = summarize(by_pattern, ("symbol", "setup_phase", "traditional_pattern_label"))
        higher_phase_rows = summarize(by_higher_phase, ("symbol", "setup_phase", "higher_timeframe_phase"))

        return {
            "version": SETUP_EDGE_MODEL_VERSION,
            "timeframe": SETUP_EDGE_MODEL_TIMEFRAME,
            "higher_timeframe": SETUP_EDGE_MODEL_HIGHER_TIMEFRAME,
            "horizon_bars": horizon_bars,
            "lookback_days": lookback_days,
            "min_samples": min_samples,
            "example_count": len(examples),
            "by_symbol_setup": symbol_setup_rows,
            "by_pattern": pattern_rows[:top_k],
            "by_higher_timeframe_phase": higher_phase_rows[:top_k],
            "top_positive_patterns": [row for row in pattern_rows if float(row["avg_target_edge_pct"]) > 0.0][:top_k],
            "top_negative_patterns": sorted(
                pattern_rows,
                key=lambda row: float(row["avg_target_edge_pct"])
            )[:top_k],
        }
