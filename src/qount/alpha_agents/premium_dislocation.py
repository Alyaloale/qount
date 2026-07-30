from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar
from qount.research_data.market_data import Funding
from qount.research_data.market_data import load_funding
from qount.research_data.market_data import load_klines
from qount.models import utc_now
from qount.settings import Settings

from .exchange_rules import SymbolRules
from .exchange_rules import evaluate_period_filter_coverage
from .exchange_rules import load_symbol_rules
from .historical_premium import HISTORICAL_PREMIUM_VERSION
from .tradeflow_experiment import HOUR_MS
from .tradeflow_experiment import FrozenTradeFlowContract
from .tradeflow_experiment import TradeFlowExperimentConfig
from .tradeflow_experiment import _align_bars
from .tradeflow_experiment import _build_periods
from .tradeflow_experiment import _ic_samples
from .tradeflow_experiment import _information_coefficient
from .tradeflow_experiment import _largest_contributor_removed_return
from .tradeflow_experiment import _month_end_exclusive_ms
from .tradeflow_experiment import _month_start_ms
from .tradeflow_experiment import _parse_month
from .tradeflow_experiment import _score_periods


PREMIUM_DISLOCATION_VERSION = "alpha_agent_premium_dislocation_v0.1"


@dataclass(frozen=True)
class FrozenPremiumDislocationContract(FrozenTradeFlowContract):
    contract_id: str = "premium_mean_z168_entry2_hold6_cooldown18_reversion_v1"
    source_feature: str = "completed_hour_mean_premium_index"
    polarity: int = -1
    hypothesis: str = (
        "an extreme perpetual premium relative to its own trailing state reflects crowded leverage "
        "and predicts six-hour BTC-beta-residual mean reversion"
    )
    hourly_aggregation: str = "arithmetic mean of twelve completed 5m premium-index closes"
    execution_rule: str = "signal=-zscore(premium), enter at abs(z)>=2, hold 6h, cash 18h"


FROZEN_PREMIUM_DISLOCATION_CONTRACT = FrozenPremiumDislocationContract()


@dataclass(frozen=True)
class PremiumDislocationProtocol:
    protocol_id: str = "premium_dislocation_cross_symbol_discovery_v1"
    discovery_symbols: tuple[str, ...] = ("ETHUSDT", "BNBUSDT", "SOLUSDT")
    benchmark_symbol: str = "BTCUSDT"
    discovery_window: str = "2024-01..2024-03"
    reserved_oos_window: str = "2024-04"
    contract_hash: str = FROZEN_PREMIUM_DISLOCATION_CONTRACT.contract_hash
    minimum_passing_symbol_count: int = 2
    minimum_positive_rank_ic_count: int = 2
    minimum_positive_residual_count: int = 2
    minimum_median_rank_ic: float = 0.02
    minimum_mean_net_residual_pct: float = 0.0
    minimum_filter_coverage: float = 1.0
    maximum_rolling_24h_turnover: float = 2.0
    selection_trials: int = 1
    oos_consumption_rule: str = (
        "do not download or evaluate April premium archives unless the frozen three-symbol Q1 report passes"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def protocol_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()


FROZEN_PREMIUM_DISLOCATION_PROTOCOL = PremiumDislocationProtocol()


@dataclass(frozen=True)
class PremiumDislocationConfig:
    premium_path: str
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    strategy_symbol: str = "ETHUSDT"
    start_month: str = "2024-01"
    end_month: str = "2024-03"
    evaluation_start_month: str | None = None
    evaluation_end_month: str | None = None
    holdout_role: str = "discovery"
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def evaluation_config(self) -> TradeFlowExperimentConfig:
        return TradeFlowExperimentConfig(
            tradeflow_path=self.premium_path,
            symbols=self.symbols,
            strategy_symbol=self.strategy_symbol,
            start_month=self.start_month,
            end_month=self.end_month,
            evaluation_start_month=self.evaluation_start_month,
            evaluation_end_month=self.evaluation_end_month,
            holdout_role=self.holdout_role,
            market=self.market,
            kline_cache_dir=self.kline_cache_dir,
            funding_cache_dir=self.funding_cache_dir,
            exchange_rules_path=self.exchange_rules_path,
            include_funding=self.include_funding,
            fee_pct=self.fee_pct,
            slippage_pct=self.slippage_pct,
            account_equity_usdt=self.account_equity_usdt,
            target_notional_fraction=self.target_notional_fraction,
            leverage=self.leverage,
            min_feature_coverage=self.min_feature_coverage,
        )


def build_premium_dislocation_preregistration(
    protocol: PremiumDislocationProtocol = FROZEN_PREMIUM_DISLOCATION_PROTOCOL,
) -> dict[str, Any]:
    return {
        "schema_version": PREMIUM_DISLOCATION_VERSION,
        "artifact_type": "preregistration",
        "created_at": utc_now().isoformat(),
        "contract": {
            **FROZEN_PREMIUM_DISLOCATION_CONTRACT.to_dict(),
            "contract_hash": FROZEN_PREMIUM_DISLOCATION_CONTRACT.contract_hash,
        },
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "diagnostics": {
            "verdict": "preregistered",
            "discovery_results_evaluated": False,
            "reserved_oos_consumed": False,
            "parameter_tuning_allowed": False,
            "next_action": "run the exact frozen Q1 contract for ETHUSDT, BNBUSDT, and SOLUSDT",
        },
        "hard_boundaries": [
            "Q1 is discovery because other Strategy V0 research has already exposed that market window.",
            "The feature, reversion direction, lookback, entry, holding, cooldown, costs, and gates are frozen before evaluation.",
            "All three registered symbols remain in the denominator; failed symbols cannot be dropped.",
            "April premium archives remain unconsumed unless this discovery protocol passes.",
            "This research artifact cannot authorize A10, paper, live, VPS changes, or order placement.",
        ],
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate_premium_to_hourly(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    contract: FrozenPremiumDislocationContract = FROZEN_PREMIUM_DISLOCATION_CONTRACT,
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in rows
        if str(row.get("symbol", "")).upper() == symbol.upper() and bool(row.get("complete"))
    ]
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in selected:
        ts_ms = int(row["ts_ms"])
        buckets.setdefault(ts_ms // HOUR_MS * HOUR_MS, []).append(row)
    prior_by_segment: dict[int, list[float]] = {}
    hourly: list[dict[str, Any]] = []
    for hour_ts in sorted(buckets):
        bucket = sorted(buckets[hour_ts], key=lambda row: int(row["ts_ms"]))
        expected = [hour_ts + offset * 5 * 60_000 for offset in range(12)]
        actual = [int(row["ts_ms"]) for row in bucket]
        segments = {int(row.get("segment_id", -1)) for row in bucket}
        if actual != expected or len(segments) != 1:
            continue
        premium = _mean([float(row["premium_index_close"]) for row in bucket])
        mark_basis = _mean([float(row["mark_index_basis"]) for row in bucket])
        premium_basis_gap = _mean(
            [float(row["premium_minus_mark_index_basis"]) for row in bucket]
        )
        segment_id = next(iter(segments))
        prior = prior_by_segment.setdefault(segment_id, [])
        zscore: float | None = None
        if len(prior) >= contract.normalization_lookback_hours:
            history = prior[-contract.normalization_lookback_hours :]
            mean = _mean(history)
            std = math.sqrt(sum((value - mean) ** 2 for value in history) / len(history))
            if std > 0:
                zscore = (premium - mean) / std * contract.polarity
        hourly.append(
            {
                "symbol": symbol.upper(),
                "hour_ts_ms": hour_ts,
                "decision_ts_ms": hour_ts + HOUR_MS,
                "segment_id": segment_id,
                "five_minute_bucket_count": len(bucket),
                "premium_index_mean": premium,
                "mark_index_basis_mean": mark_basis,
                "premium_minus_mark_basis_mean": premium_basis_gap,
                "raw_feature_value": premium,
                "signal_zscore": zscore,
            }
        )
        prior.append(premium)
    return hourly


def _load_premium(path: str) -> tuple[dict[str, Any], str]:
    source = Path(path).expanduser()
    blob = source.read_bytes()
    payload = json.loads(blob)
    if payload.get("schema_version") != HISTORICAL_PREMIUM_VERSION:
        raise ValueError("premium path must contain a historical premium artifact")
    if not isinstance(payload.get("five_minute_features"), list):
        raise ValueError("premium artifact must contain five_minute_features")
    return payload, hashlib.sha256(blob).hexdigest()


def build_premium_dislocation_experiment(
    config: PremiumDislocationConfig,
    *,
    contract: FrozenPremiumDislocationContract = FROZEN_PREMIUM_DISLOCATION_CONTRACT,
    bars_by_symbol: dict[str, list[Bar]] | None = None,
    funding: list[Funding] | None = None,
    rules_by_symbol: dict[str, SymbolRules] | None = None,
) -> dict[str, Any]:
    if not config.symbols or "BTCUSDT" not in config.symbols:
        raise ValueError("symbols must include BTCUSDT")
    if config.strategy_symbol not in config.symbols:
        raise ValueError("strategy_symbol must be included in symbols")
    if config.market != "um":
        raise ValueError("premium experiment supports Binance USD-M only")
    if config.holdout_role not in {"discovery", "historical_oos"}:
        raise ValueError("holdout_role must be discovery or historical_oos")
    premium, source_hash = _load_premium(config.premium_path)
    evaluation_start_month = config.evaluation_start_month or config.start_month
    evaluation_end_month = config.evaluation_end_month or config.end_month
    evaluation_start_ms = _month_start_ms(evaluation_start_month)
    evaluation_end_ms = _month_end_exclusive_ms(evaluation_end_month)
    hourly = aggregate_premium_to_hourly(
        premium["five_minute_features"], symbol=config.strategy_symbol, contract=contract
    )
    start = _parse_month(config.start_month)
    end = _parse_month(config.end_month)
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
        raise ValueError("no common 1h kline periods")
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
    eval_config = config.evaluation_config()
    samples = _ic_samples(
        aligned,
        hourly,
        strategy_symbol=config.strategy_symbol,
        contract=contract,
        evaluation_start_ms=evaluation_start_ms,
        evaluation_end_ms=evaluation_end_ms,
    )
    ic = _information_coefficient(
        [float(row["feature_value"]) for row in samples],
        [float(row["residual_forward_return_pct"]) for row in samples],
    )
    periods, execution = _build_periods(
        aligned,
        hourly,
        config=eval_config,
        contract=contract,
        funding=funding,
        evaluation_start_ms=evaluation_start_ms,
        evaluation_end_ms=evaluation_end_ms,
    )
    if not periods:
        raise ValueError("no contiguous premium experiment periods")
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
    evaluation_hourly = [
        row
        for row in hourly
        if evaluation_start_ms <= int(row["decision_ts_ms"]) < evaluation_end_ms
    ]
    complete_hour_count = len(evaluation_hourly)
    scored_hour_count = sum(row.get("signal_zscore") is not None for row in evaluation_hourly)
    segment_count = len({int(row["segment_id"]) for row in evaluation_hourly})
    warmup_allowance = 0 if config.evaluation_start_month else segment_count * contract.normalization_lookback_hours
    eligible_hours = max(0, complete_hour_count - warmup_allowance)
    feature_coverage = min(1.0, scored_hour_count / eligible_hours) if eligible_hours else 0.0
    blockers: list[str] = []
    if premium.get("diagnostics", {}).get("verdict") != "pass_data_smoke":
        blockers.append("source_premium_blocked")
    if feature_coverage < config.min_feature_coverage:
        blockers.append("feature_coverage_below_threshold")
    if float(ic["rank_ic"]) < contract.minimum_rank_ic:
        blockers.append("rank_ic_below_frozen_gate")
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
    largest_removed = _largest_contributor_removed_return(periods)
    config_hash = hashlib.sha256(
        json.dumps({"config": config.to_dict(), "contract": contract.to_dict()}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    passed = not blockers
    verdict = (
        "pass_independent_oos" if passed else "block_independent_oos"
    ) if config.holdout_role == "historical_oos" else (
        "advance_to_independent_oos" if passed else "block_discovery"
    )
    return {
        "schema_version": PREMIUM_DISLOCATION_VERSION,
        "artifact_type": "experiment",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "point_in_time": True,
            "as_of_join": True,
            "replayable": premium.get("meta", {}).get("replayable", False),
            "trial_count": 1,
            "costs_included": True,
            "funding_included": config.include_funding,
            "min_notional_coverage": filter_diagnostics["min_notional_coverage"],
            "claims_cross_sectional_edge": True,
            "data_hash": source_hash,
            "config_hash": config_hash,
            "contract_hash": contract.contract_hash,
            "holdout_role": config.holdout_role,
            "label_spec": f"{config.strategy_symbol} forward {contract.holding_hours}h return minus as-of BTC beta",
            "data_spec": "checksum-verified Binance USD-M premiumIndex/markPrice/indexPrice 5m archives",
            "cost_spec": "taker fee + slippage per position change plus USD-M funding",
            "kill_line": "do not consume April unless at least two of three registered Q1 symbols pass",
            "largest_contributor_removed_return_pct": largest_removed,
        },
        "config": config.to_dict(),
        "decision_contract": {
            **contract.to_dict(),
            "contract_hash": contract.contract_hash,
            "frozen_before_independent_oos": True,
            "selection_trials": 1,
        },
        "diagnostics": {
            "verdict": verdict,
            "holdout_role": config.holdout_role,
            "advance_to_independent_oos": passed and config.holdout_role == "discovery",
            "survived_independent_oos": passed and config.holdout_role == "historical_oos",
            "blockers": blockers,
            "evaluation_window": {
                "start_month": evaluation_start_month,
                "end_month": evaluation_end_month,
            },
            "source_premium_path": str(Path(config.premium_path).expanduser()),
            "source_premium_verdict": premium.get("diagnostics", {}).get("verdict"),
            "source_five_minute_row_count": len(premium["five_minute_features"]),
            "complete_hour_count": complete_hour_count,
            "scored_hour_count": scored_hour_count,
            "feature_coverage": feature_coverage,
            "segment_count": segment_count,
            "aligned_kline_hour_count": len(aligned),
            "ic": ic,
            "score": score,
            "execution": execution,
            "filter_diagnostics": filter_diagnostics,
            "largest_contributor_removed_return_pct": largest_removed,
            "reserved_oos_consumed": config.holdout_role == "historical_oos",
            "promotion_note": "Discovery cannot authorize A10, paper, or live; higher-order gates remain required.",
        },
        "ic_samples": samples,
        "hourly_features": hourly,
        "periods": periods,
    }


def _load_json(path: str | Path) -> tuple[dict[str, Any], Path, str]:
    source = Path(path).expanduser().resolve()
    blob = source.read_bytes()
    return json.loads(blob), source, hashlib.sha256(blob).hexdigest()


def _experiment_summary(payload: dict[str, Any], path: Path, digest: str) -> dict[str, Any]:
    diagnostics = payload.get("diagnostics", {})
    return {
        "symbol": str(payload.get("config", {}).get("strategy_symbol", "")).upper(),
        "path": str(path),
        "sha256": digest,
        "contract_hash": payload.get("decision_contract", {}).get("contract_hash"),
        "holdout_role": diagnostics.get("holdout_role"),
        "verdict": diagnostics.get("verdict"),
        "rank_ic": float(diagnostics.get("ic", {}).get("rank_ic", 0.0)),
        "net_residual_return_pct": float(diagnostics.get("score", {}).get("net_residual_return_pct", 0.0)),
        "entry_count": int(diagnostics.get("execution", {}).get("entry_count", 0)),
        "max_rolling_24h_turnover": float(
            diagnostics.get("execution", {}).get("max_rolling_24h_turnover", 0.0)
        ),
        "filter_coverage": float(diagnostics.get("filter_diagnostics", {}).get("filter_coverage", 0.0)),
        "blockers": list(diagnostics.get("blockers", [])),
    }


def build_premium_dislocation_discovery_report(
    *,
    preregistration_path: str | Path,
    experiment_paths: list[str | Path],
    protocol: PremiumDislocationProtocol = FROZEN_PREMIUM_DISLOCATION_PROTOCOL,
) -> dict[str, Any]:
    preregistration, prereg_path, prereg_hash = _load_json(preregistration_path)
    if (
        preregistration.get("schema_version") != PREMIUM_DISLOCATION_VERSION
        or preregistration.get("artifact_type") != "preregistration"
        or preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash
    ):
        raise ValueError("preregistration does not match the frozen premium protocol")
    summaries: dict[str, dict[str, Any]] = {}
    for experiment_path in experiment_paths:
        payload, source, digest = _load_json(experiment_path)
        if payload.get("schema_version") != PREMIUM_DISLOCATION_VERSION or payload.get("artifact_type") != "experiment":
            raise ValueError("experiment path is not a premium-dislocation experiment")
        summary = _experiment_summary(payload, source, digest)
        if summary["symbol"] in summaries:
            raise ValueError(f"duplicate experiment for {summary['symbol']}")
        summaries[summary["symbol"]] = summary
    expected = set(protocol.discovery_symbols)
    missing = sorted(expected - set(summaries))
    unexpected = sorted(set(summaries) - expected)
    ordered = [summaries[symbol] for symbol in protocol.discovery_symbols if symbol in summaries]
    contract_mismatches = sorted(
        row["symbol"] for row in ordered if row["contract_hash"] != protocol.contract_hash
    )
    role_mismatches = sorted(row["symbol"] for row in ordered if row["holdout_role"] != "discovery")
    passing_count = sum(row["verdict"] == "advance_to_independent_oos" for row in ordered)
    positive_ic_count = sum(row["rank_ic"] > 0 for row in ordered)
    positive_residual_count = sum(row["net_residual_return_pct"] > 0 for row in ordered)
    median_ic = statistics.median([row["rank_ic"] for row in ordered]) if ordered else 0.0
    mean_residual = statistics.fmean([row["net_residual_return_pct"] for row in ordered]) if ordered else 0.0
    filter_complete = bool(ordered) and all(
        row["filter_coverage"] >= protocol.minimum_filter_coverage for row in ordered
    )
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
    if role_mismatches:
        blockers.append("holdout_role_mismatch")
    if passing_count < protocol.minimum_passing_symbol_count:
        blockers.append("passing_symbol_count_below_protocol")
    if positive_ic_count < protocol.minimum_positive_rank_ic_count:
        blockers.append("positive_rank_ic_count_below_protocol")
    if positive_residual_count < protocol.minimum_positive_residual_count:
        blockers.append("positive_residual_count_below_protocol")
    if median_ic < protocol.minimum_median_rank_ic:
        blockers.append("median_rank_ic_below_protocol")
    if mean_residual <= protocol.minimum_mean_net_residual_pct:
        blockers.append("mean_net_residual_non_positive")
    if not filter_complete:
        blockers.append("filter_coverage_incomplete")
    if not turnover_ok:
        blockers.append("turnover_budget_exceeded")
    passed = not blockers
    return {
        "schema_version": PREMIUM_DISLOCATION_VERSION,
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
            "holdout_role_mismatches": role_mismatches,
            "passing_symbol_count": passing_count,
            "positive_rank_ic_count": positive_ic_count,
            "positive_residual_count": positive_residual_count,
            "median_rank_ic": median_ic,
            "mean_net_residual_return_pct": mean_residual,
            "filter_coverage_complete": filter_complete,
            "turnover_within_budget": turnover_ok,
            "reserved_oos_consumed": False,
            "next_action": (
                "write a separate April OOS preregistration before downloading new premium archives"
                if passed
                else "stop this hypothesis without parameter rescue or April consumption"
            ),
        },
        "hard_boundary": "This report cannot authorize A10, paper, live, VPS changes, or order placement.",
    }


def write_premium_dislocation_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-premium-dislocation",
        path_key="artifact_path",
        default_filename="alpha_agent_premium_dislocation.json",
        explicit_path=explicit_path,
    )
