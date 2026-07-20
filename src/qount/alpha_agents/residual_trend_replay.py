from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sklearn.metrics import accuracy_score
from sklearn.metrics import brier_score_loss
from sklearn.metrics import log_loss
from sklearn.metrics import roc_auc_score

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar
from qount.grid.data import Funding
from qount.grid.data import load_funding
from qount.grid.data import load_klines
from qount.models import utc_now
from qount.settings import Settings

from .exchange_rules import SymbolRules
from .exchange_rules import evaluate_period_filter_coverage
from .exchange_rules import load_symbol_rules
from .historical_depth import HISTORICAL_DEPTH_VERSION
from .historical_premium import HISTORICAL_PREMIUM_VERSION
from .premium_dislocation import aggregate_premium_to_hourly
from .residual_trend_model import FEATURE_NAMES
from .residual_trend_model import FROZEN_RESIDUAL_TREND_MODEL_CONTRACT
from .residual_trend_model import RESIDUAL_TREND_MODEL_VERSION
from .residual_trend_model import FrozenResidualTrendModelContract
from .residual_trend_model import _build_model_samples
from .residual_trend_model import _calibration
from .residual_trend_model import _daily_residual_dsr
from .residual_trend_model import _load_source
from .residual_trend_model import _rank_ic
from .residual_trend_model import aggregate_depth_to_hourly
from .tradeflow_experiment import HOUR_MS
from .tradeflow_experiment import TradeFlowExperimentConfig
from .tradeflow_experiment import _align_bars
from .tradeflow_experiment import _build_periods
from .tradeflow_experiment import _largest_contributor_removed_return
from .tradeflow_experiment import _score_periods


RESIDUAL_TREND_REPLAY_VERSION = "alpha_agent_residual_trend_replay_v0.1"
ANCHOR_MODEL_SHA256 = (
    ("ETHUSDT", "240779d0d1c131095c1c1b1de18fbc795b34f116baa4e0543f7aac04f46bfbdd"),
    ("BNBUSDT", "683b9390dc0fa9f26050b3dc524a6552552ee2adf6910f15a10dab7d55fffef8"),
    ("SOLUSDT", "d383753ad07c9aca46c22b9a3bcd07a7e2fce554c46ac1f2444912cb056beea8"),
)


@dataclass(frozen=True)
class ResidualTrendReplayProtocol:
    protocol_id: str = "frozen_residual_trend_temporal_replay_2025q1_v1"
    symbols: tuple[str, ...] = ("ETHUSDT", "BNBUSDT", "SOLUSDT")
    benchmark_symbol: str = "BTCUSDT"
    evaluation_start_utc: str = "2025-01-01T00:00:00+00:00"
    evaluation_end_utc: str = "2025-04-01T00:00:00+00:00"
    price_warmup_start_month: str = "2024-12"
    anchor_contract_hash: str = FROZEN_RESIDUAL_TREND_MODEL_CONTRACT.contract_hash
    anchor_model_sha256: tuple[tuple[str, str], ...] = ANCHOR_MODEL_SHA256
    anchor_discovery_verdict: str = "block_discovery"
    minimum_feature_coverage: float = 0.98
    minimum_filter_coverage: float = 1.0
    selection_trials: int = 1
    pbo_policy: str = "single fixed model remains non-identifiable and fail-closed at 1.0"
    promotion_policy: str = "temporal replay cannot reverse the failed 2024Q1 anchor or authorize promotion"
    a10_policy: str = "A10 sequence remains disabled regardless of temporal replay result"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["anchor_model_sha256"] = [
            {"symbol": symbol, "sha256": digest}
            for symbol, digest in self.anchor_model_sha256
        ]
        return payload

    @property
    def protocol_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()

    def anchor_hash(self, symbol: str) -> str:
        hashes = dict(self.anchor_model_sha256)
        try:
            return hashes[symbol.upper()]
        except KeyError as exc:
            raise ValueError(f"symbol is not registered for temporal replay: {symbol}") from exc


FROZEN_RESIDUAL_TREND_REPLAY_PROTOCOL = ResidualTrendReplayProtocol()


@dataclass(frozen=True)
class ResidualTrendReplayConfig:
    depth_path: str
    premium_path: str
    model_path: str
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
    holdout_role: str = "temporal_replication"
    request_retries: int = 5
    request_timeout_seconds: float = 60.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ts(raw: str) -> int:
    return int(dt.datetime.fromisoformat(raw).timestamp() * 1000)


def _fetch_public_archive(
    url: str,
    *,
    retries: int,
    timeout_seconds: float,
) -> bytes:  # pragma: no cover - network
    request = urllib.request.Request(url, headers={"User-Agent": "qount-residual-trend-replay/0.1"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except (OSError, TimeoutError, urllib.error.URLError):
            if attempt >= retries:
                raise
            time.sleep(0.25 * (2**attempt))
    raise AssertionError("unreachable")


def _audit_price_bars(
    bars_by_symbol: dict[str, list[Bar]],
    symbols: tuple[str, ...],
    *,
    start_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    expected = max(0, (end_ms - start_ms) // HOUR_MS)
    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        timestamps = sorted(
            {bar.ts_ms for bar in bars_by_symbol.get(symbol, []) if start_ms <= bar.ts_ms < end_ms}
        )
        by_symbol[symbol] = {
            "expected_hour_count": expected,
            "available_hour_count": len(timestamps),
            "coverage": len(timestamps) / expected if expected else 0.0,
            "first_ts_ms": timestamps[0] if timestamps else None,
            "last_ts_ms": timestamps[-1] if timestamps else None,
        }
    minimum_coverage = min((row["coverage"] for row in by_symbol.values()), default=0.0)
    return {"minimum_coverage": minimum_coverage, "by_symbol": by_symbol}


def build_residual_trend_replay_preregistration(
    protocol: ResidualTrendReplayProtocol = FROZEN_RESIDUAL_TREND_REPLAY_PROTOCOL,
) -> dict[str, Any]:
    return {
        "schema_version": RESIDUAL_TREND_REPLAY_VERSION,
        "artifact_type": "temporal_replay_preregistration",
        "created_at": utc_now().isoformat(),
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "frozen_contract": {
            **FROZEN_RESIDUAL_TREND_MODEL_CONTRACT.to_dict(),
            "contract_hash": FROZEN_RESIDUAL_TREND_MODEL_CONTRACT.contract_hash,
        },
        "diagnostics": {
            "verdict": "preregistered",
            "temporal_results_evaluated": False,
            "refit_allowed": False,
            "recalibration_allowed": False,
            "feature_selection_allowed": False,
            "threshold_tuning_allowed": False,
            "model_family_search_allowed": False,
            "anchor_failure_reversible": False,
            "promotion_allowed": False,
            "a10_sequence_enabled": False,
            "pbo": 1.0,
            "next_action": "apply each byte-bound frozen model once to checksum-verified 2025Q1 public data",
        },
        "hard_boundaries": [
            "Reconstruct probabilities only from the saved scaler, coefficients, and intercept; do not call fit.",
            "Keep the saved feature order and 0.55/0.45 probability thresholds unchanged.",
            "Use the saved train positive rate as the constant-probability Brier baseline; do not recalibrate.",
            "Evaluate the complete registered 2025Q1 window for all three symbols without symbol selection.",
            "A positive temporal result is diagnostic only and cannot erase the failed March anchor.",
            "PBO remains fail-closed and A10, paper, live, positions, and orders remain disabled.",
        ],
    }


def _load_anchor_model(
    path: str,
    *,
    symbol: str,
    protocol: ResidualTrendReplayProtocol,
    contract: FrozenResidualTrendModelContract,
) -> tuple[dict[str, Any], str, str]:
    source = Path(path).expanduser().resolve()
    blob = source.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != protocol.anchor_hash(symbol):
        raise ValueError(f"anchor model sha256 mismatch for {symbol}")
    payload = json.loads(blob)
    if (
        payload.get("schema_version") != RESIDUAL_TREND_MODEL_VERSION
        or payload.get("artifact_type") != "model_experiment"
        or str(payload.get("config", {}).get("strategy_symbol", "")).upper() != symbol.upper()
        or payload.get("decision_contract", {}).get("contract_hash") != contract.contract_hash
        or payload.get("diagnostics", {}).get("verdict") != protocol.anchor_discovery_verdict
    ):
        raise ValueError(f"invalid frozen anchor model for {symbol}")
    model_card = payload.get("model_card", {})
    if tuple(model_card.get("feature_names", ())) != contract.feature_names:
        raise ValueError("anchor feature order does not match the frozen contract")
    means = model_card.get("scaler_mean")
    scales = model_card.get("scaler_scale")
    coefficients = model_card.get("coefficients")
    if (
        not isinstance(means, list)
        or not isinstance(scales, list)
        or not isinstance(coefficients, dict)
        or len(means) != len(contract.feature_names)
        or len(scales) != len(contract.feature_names)
        or any(float(value) <= 0 or not math.isfinite(float(value)) for value in scales)
        or any(name not in coefficients for name in contract.feature_names)
    ):
        raise ValueError("anchor model parameters are incomplete")
    parameter_basis = {
        "feature_names": list(contract.feature_names),
        "scaler_mean": means,
        "scaler_scale": scales,
        "coefficients": {name: coefficients[name] for name in contract.feature_names},
        "intercept": model_card.get("intercept"),
    }
    parameter_hash = hashlib.sha256(
        json.dumps(parameter_basis, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return payload, digest, parameter_hash


def predict_from_frozen_model(
    model_card: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> list[float]:
    means = [float(value) for value in model_card["scaler_mean"]]
    scales = [float(value) for value in model_card["scaler_scale"]]
    coefficients = [float(model_card["coefficients"][name]) for name in feature_names]
    intercept = float(model_card["intercept"])
    if not (
        len(means) == len(scales) == len(coefficients) == len(feature_names)
        and all(value > 0 and math.isfinite(value) for value in scales)
    ):
        raise ValueError("invalid frozen model dimensions")
    probabilities: list[float] = []
    for row in rows:
        values = [float(value) for value in row["feature_values"]]
        if len(values) != len(feature_names) or not all(math.isfinite(value) for value in values):
            raise ValueError("invalid replay feature vector")
        score = intercept + sum(
            coefficient * ((value - mean) / scale)
            for value, mean, scale, coefficient in zip(values, means, scales, coefficients)
        )
        if score >= 0:
            probability = 1.0 / (1.0 + math.exp(-score))
        else:
            exponent = math.exp(score)
            probability = exponent / (1.0 + exponent)
        probabilities.append(probability)
    return probabilities


def build_residual_trend_replay(
    config: ResidualTrendReplayConfig,
    *,
    protocol: ResidualTrendReplayProtocol = FROZEN_RESIDUAL_TREND_REPLAY_PROTOCOL,
    contract: FrozenResidualTrendModelContract = FROZEN_RESIDUAL_TREND_MODEL_CONTRACT,
    bars_by_symbol: dict[str, list[Bar]] | None = None,
    funding: list[Funding] | None = None,
    rules_by_symbol: dict[str, SymbolRules] | None = None,
) -> dict[str, Any]:
    symbol = config.strategy_symbol.upper()
    if config.holdout_role != "temporal_replication":
        raise ValueError("frozen replay requires holdout_role=temporal_replication")
    if config.market != "um":
        raise ValueError("frozen replay supports Binance USD-M only")
    if config.request_retries < 0 or config.request_timeout_seconds <= 0:
        raise ValueError("invalid public archive retry configuration")
    if symbol not in protocol.symbols or "BTCUSDT" not in config.symbols or symbol not in config.symbols:
        raise ValueError("symbols must include registered strategy_symbol and BTCUSDT")
    if config.min_feature_coverage != protocol.minimum_feature_coverage:
        raise ValueError("feature coverage gate must match the preregistered protocol")
    anchor, anchor_hash, parameter_hash = _load_anchor_model(
        config.model_path,
        symbol=symbol,
        protocol=protocol,
        contract=contract,
    )
    depth, depth_hash = _load_source(config.depth_path, HISTORICAL_DEPTH_VERSION, "five_minute_features")
    premium, premium_hash = _load_source(
        config.premium_path, HISTORICAL_PREMIUM_VERSION, "five_minute_features"
    )
    if depth.get("diagnostics", {}).get("verdict") != "pass_data_smoke":
        raise ValueError("temporal depth source is blocked")
    if premium.get("diagnostics", {}).get("verdict") != "pass_data_smoke":
        raise ValueError("temporal premium source is blocked")
    evaluation_start = _ts(protocol.evaluation_start_utc)
    evaluation_end = _ts(protocol.evaluation_end_utc)
    warmup_year, warmup_month = (
        int(value) for value in protocol.price_warmup_start_month.split("-", 1)
    )
    price_start = int(dt.datetime(warmup_year, warmup_month, 1, tzinfo=dt.UTC).timestamp() * 1000)
    public_fetch = lambda url: _fetch_public_archive(  # noqa: E731
        url,
        retries=config.request_retries,
        timeout_seconds=config.request_timeout_seconds,
    )
    if bars_by_symbol is None:
        bars_by_symbol = {
            selected: load_klines(
                selected,
                "1h",
                start=(warmup_year, warmup_month),
                end=(2025, 3),
                market=config.market,
                cache_dir=config.kline_cache_dir,
                fetch=public_fetch,
                skip_missing=True,
            )
            for selected in config.symbols
        }
    price_data_audit = _audit_price_bars(
        bars_by_symbol,
        config.symbols,
        start_ms=price_start,
        end_ms=evaluation_end,
    )
    if price_data_audit["minimum_coverage"] < 0.999:
        raise ValueError("hourly price coverage below strict temporal replay gate")
    aligned = _align_bars(bars_by_symbol, config.symbols)
    if not aligned:
        raise ValueError("no common hourly price bars for temporal replay")
    depth_hourly = aggregate_depth_to_hourly(depth["five_minute_features"], symbol=symbol)
    premium_hourly = aggregate_premium_to_hourly(premium["five_minute_features"], symbol=symbol)
    samples = _build_model_samples(
        depth_hourly=depth_hourly,
        premium_hourly=premium_hourly,
        aligned=aligned,
        strategy_symbol=symbol,
        contract=contract,
    )
    replay_rows = [
        row
        for row in samples
        if evaluation_start <= int(row["decision_ts_ms"])
        and int(row["decision_ts_ms"]) + contract.holding_hours * HOUR_MS <= evaluation_end
    ]
    if len(replay_rows) < 100:
        raise ValueError("insufficient temporal replay samples")
    model_card = anchor["model_card"]
    probabilities = predict_from_frozen_model(
        model_card,
        replay_rows,
        feature_names=contract.feature_names,
    )
    targets = [int(row["target"]) for row in replay_rows]
    anchor_positive_rate = float(anchor["diagnostics"]["train_positive_rate"])
    if not 0 <= anchor_positive_rate <= 1:
        raise ValueError("invalid anchor train positive rate")
    auc = float(roc_auc_score(targets, probabilities)) if len(set(targets)) > 1 else 0.5
    brier = float(brier_score_loss(targets, probabilities))
    baseline_brier = float(
        brier_score_loss(targets, [anchor_positive_rate] * len(targets))
    )
    predictions: list[dict[str, Any]] = []
    prediction_features: list[dict[str, Any]] = []
    for row, probability in zip(replay_rows, probabilities):
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
                symbol,
                start=(2025, 1),
                end=(2025, 3),
                cache_dir=config.funding_cache_dir,
                fetch=public_fetch,
                skip_missing=True,
            )
            if config.include_funding
            else []
        )
    eval_config = TradeFlowExperimentConfig(
        tradeflow_path=config.depth_path,
        symbols=config.symbols,
        strategy_symbol=symbol,
        start_month="2024-12",
        end_month="2025-03",
        evaluation_start_month="2025-01",
        evaluation_end_month="2025-03",
        holdout_role="historical_oos",
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
        evaluation_start_ms=evaluation_start,
        evaluation_end_ms=evaluation_end,
    )
    if not periods:
        raise ValueError("no contiguous temporal replay periods")
    score = _score_periods(periods)
    if rules_by_symbol is None and config.exchange_rules_path:
        rules_by_symbol = load_symbol_rules(config.exchange_rules_path, market=config.market)
    filter_diagnostics = (
        evaluate_period_filter_coverage(
            periods,
            rules_by_symbol,
            symbol=symbol,
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
    rank_ic = _rank_ic(probabilities, replay_rows)
    feature_denominator = sum(
        evaluation_start <= int(row["decision_ts_ms"]) < evaluation_end
        for row in depth_hourly
    )
    feature_coverage = len(replay_rows) / max(1, feature_denominator)
    brier_improvement = baseline_brier - brier
    diagnostic_blockers: list[str] = []
    if feature_coverage < protocol.minimum_feature_coverage:
        diagnostic_blockers.append("feature_coverage_below_registered_gate")
    if auc < contract.minimum_auc:
        diagnostic_blockers.append("auc_below_frozen_gate")
    if rank_ic < contract.minimum_rank_ic:
        diagnostic_blockers.append("rank_ic_below_frozen_gate")
    if brier_improvement <= contract.minimum_brier_improvement:
        diagnostic_blockers.append("brier_not_better_than_anchor_train_baseline")
    if score["net_residual_return_pct"] <= 0:
        diagnostic_blockers.append("cost_adjusted_beta_residual_non_positive")
    if execution["entry_count"] < contract.minimum_entry_count:
        diagnostic_blockers.append("entry_count_below_minimum")
    if execution["max_rolling_24h_turnover"] > contract.maximum_rolling_24h_turnover + 1e-12:
        diagnostic_blockers.append("turnover_budget_exceeded")
    if filter_diagnostics["min_notional_coverage"] < protocol.minimum_filter_coverage:
        diagnostic_blockers.append("exchange_filter_coverage_incomplete")
    if not config.include_funding:
        diagnostic_blockers.append("funding_not_included")
    dsr = _daily_residual_dsr(periods, float(score["beta_to_btc"]))
    original_prediction = anchor["diagnostics"]["prediction"]
    original_score = anchor["diagnostics"]["score"]
    config_hash = hashlib.sha256(
        json.dumps(
            {
                "config": config.to_dict(),
                "protocol": protocol.to_dict(),
                "contract": contract.to_dict(),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": RESIDUAL_TREND_REPLAY_VERSION,
        "artifact_type": "temporal_model_replay",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "orders_allowed": False,
            "point_in_time": True,
            "as_of_join": True,
            "refit_performed": False,
            "recalibration_performed": False,
            "model_selection_performed": False,
            "threshold_tuning_performed": False,
            "sequence_model": False,
            "a10_sequence_enabled": False,
            "selection_trials": protocol.selection_trials,
            "costs_included": True,
            "funding_included": config.include_funding,
            "source_hashes": {"depth": depth_hash, "premium": premium_hash},
            "anchor_model_sha256": anchor_hash,
            "model_parameter_hash": parameter_hash,
            "contract_hash": contract.contract_hash,
            "protocol_hash": protocol.protocol_hash,
            "config_hash": config_hash,
            "holdout_role": config.holdout_role,
            "label_spec": contract.target,
            "cost_spec": "5bps taker + 2bps slippage per position change plus funding",
        },
        "config": config.to_dict(),
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "decision_contract": {
            **contract.to_dict(),
            "contract_hash": contract.contract_hash,
            "frozen_from_failed_anchor": True,
            "selection_trials": protocol.selection_trials,
        },
        "model_anchor": {
            "path": str(Path(config.model_path).expanduser().resolve()),
            "sha256": anchor_hash,
            "parameter_hash": parameter_hash,
            "train_positive_rate": anchor_positive_rate,
            "original_verdict": anchor["diagnostics"]["verdict"],
            "original_march_auc": float(original_prediction["auc"]),
            "original_march_rank_ic": float(original_prediction["rank_ic"]),
            "original_march_brier_improvement": float(original_prediction["brier_improvement"]),
            "original_march_net_residual_return_pct": float(
                original_score["net_residual_return_pct"]
            ),
        },
        "model_card": model_card,
        "diagnostics": {
            "verdict": (
                "temporal_stress_supportive_no_promotion"
                if not diagnostic_blockers
                else "temporal_stress_failed_no_promotion"
            ),
            "diagnostic_blockers": diagnostic_blockers,
            "evaluation_window": {
                "start_ms": evaluation_start,
                "end_exclusive_ms": evaluation_end,
            },
            "sample_count": len(replay_rows),
            "feature_coverage": feature_coverage,
            "price_data_audit": price_data_audit,
            "prediction": {
                "auc": auc,
                "accuracy": float(
                    accuracy_score(targets, [int(value >= 0.5) for value in probabilities])
                ),
                "brier": brier,
                "anchor_train_constant_brier": baseline_brier,
                "brier_improvement": brier_improvement,
                "log_loss": float(log_loss(targets, probabilities)),
                "rank_ic": rank_ic,
                "calibration": _calibration(probabilities, targets),
            },
            "score": score,
            "execution": execution,
            "filter_diagnostics": filter_diagnostics,
            "largest_contributor_removed_return_pct": _largest_contributor_removed_return(periods),
            "anti_overfit": {
                "deflated_sharpe_ratio": dsr["dsr"],
                "daily_residual": dsr,
                "pbo": 1.0,
                "pbo_status": "non_identifiable_single_fixed_model_fail_closed",
                "promotion_g4_pass": False,
            },
            "anchor_failure_reversible": False,
            "promotion_allowed": False,
            "a10_sequence_enabled": False,
            "next_action": "record temporal stability evidence; do not promote or tune this failed anchor model",
        },
        "predictions": predictions,
        "periods": periods,
    }


def _load_json(path: str | Path) -> tuple[dict[str, Any], Path, str]:
    source = Path(path).expanduser().resolve()
    blob = source.read_bytes()
    return json.loads(blob), source, hashlib.sha256(blob).hexdigest()


def build_residual_trend_replay_report(
    *,
    preregistration_path: str | Path,
    replay_paths: list[str | Path],
    protocol: ResidualTrendReplayProtocol = FROZEN_RESIDUAL_TREND_REPLAY_PROTOCOL,
) -> dict[str, Any]:
    prereg, prereg_path, prereg_hash = _load_json(preregistration_path)
    if (
        prereg.get("schema_version") != RESIDUAL_TREND_REPLAY_VERSION
        or prereg.get("artifact_type") != "temporal_replay_preregistration"
        or prereg.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash
        or prereg.get("diagnostics", {}).get("temporal_results_evaluated") is not False
    ):
        raise ValueError("preregistration does not match the frozen temporal replay protocol")
    summaries: dict[str, dict[str, Any]] = {}
    for raw_path in replay_paths:
        payload, path, digest = _load_json(raw_path)
        if (
            payload.get("schema_version") != RESIDUAL_TREND_REPLAY_VERSION
            or payload.get("artifact_type") != "temporal_model_replay"
            or payload.get("meta", {}).get("protocol_hash") != protocol.protocol_hash
        ):
            raise ValueError("invalid residual-trend temporal replay artifact")
        symbol = str(payload.get("config", {}).get("strategy_symbol", "")).upper()
        if symbol in summaries:
            raise ValueError(f"duplicate temporal replay for {symbol}")
        diagnostics = payload["diagnostics"]
        prediction = diagnostics["prediction"]
        summaries[symbol] = {
            "symbol": symbol,
            "path": str(path),
            "sha256": digest,
            "anchor_model_sha256": payload["meta"]["anchor_model_sha256"],
            "verdict": diagnostics["verdict"],
            "auc": float(prediction["auc"]),
            "rank_ic": float(prediction["rank_ic"]),
            "brier_improvement": float(prediction["brier_improvement"]),
            "net_residual_return_pct": float(diagnostics["score"]["net_residual_return_pct"]),
            "entry_count": int(diagnostics["execution"]["entry_count"]),
            "max_rolling_24h_turnover": float(
                diagnostics["execution"]["max_rolling_24h_turnover"]
            ),
            "filter_coverage": float(diagnostics["filter_diagnostics"]["filter_coverage"]),
            "dsr": float(diagnostics["anti_overfit"]["deflated_sharpe_ratio"]),
            "pbo": float(diagnostics["anti_overfit"]["pbo"]),
            "diagnostic_blockers": list(diagnostics["diagnostic_blockers"]),
        }
    expected = set(protocol.symbols)
    missing = sorted(expected - set(summaries))
    unexpected = sorted(set(summaries) - expected)
    ordered = [summaries[symbol] for symbol in protocol.symbols if symbol in summaries]
    anchor_mismatches = sorted(
        row["symbol"]
        for row in ordered
        if row["anchor_model_sha256"] != protocol.anchor_hash(row["symbol"])
    )
    supportive_count = sum(
        row["verdict"] == "temporal_stress_supportive_no_promotion" for row in ordered
    )
    positive_residual_count = sum(row["net_residual_return_pct"] > 0 for row in ordered)
    positive_ic_count = sum(row["rank_ic"] > 0 for row in ordered)
    mean_residual = (
        statistics.fmean(row["net_residual_return_pct"] for row in ordered) if ordered else 0.0
    )
    complete = not missing and not unexpected and not anchor_mismatches
    return {
        "schema_version": RESIDUAL_TREND_REPLAY_VERSION,
        "artifact_type": "temporal_replay_report",
        "created_at": utc_now().isoformat(),
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "preregistration": {"path": str(prereg_path), "sha256": prereg_hash},
        "replays": {row["symbol"]: row for row in ordered},
        "diagnostics": {
            "verdict": (
                "temporal_replay_complete_no_promotion"
                if complete
                else "block_incomplete_temporal_replay"
            ),
            "blockers": [
                blocker
                for condition, blocker in (
                    (bool(missing), "registered_symbol_missing"),
                    (bool(unexpected), "unexpected_symbol_present"),
                    (bool(anchor_mismatches), "anchor_model_hash_mismatch"),
                )
                if condition
            ],
            "missing_symbols": missing,
            "unexpected_symbols": unexpected,
            "anchor_mismatches": anchor_mismatches,
            "supportive_symbol_count": supportive_count,
            "positive_residual_count": positive_residual_count,
            "positive_rank_ic_count": positive_ic_count,
            "mean_net_residual_return_pct": mean_residual,
            "pbo": 1.0,
            "promotion_g4_pass": False,
            "anchor_failure_reversible": False,
            "promotion_allowed": False,
            "a10_sequence_enabled": False,
            "next_action": "retain the frozen-model temporal evidence and seek a genuinely new information source",
        },
        "hard_boundary": "Temporal replication cannot convert a failed discovery anchor into a promotable model.",
    }


def write_residual_trend_replay_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-residual-trend-replay",
        path_key="artifact_path",
        default_filename="alpha_agent_residual_trend_replay.json",
        explicit_path=explicit_path,
    )
