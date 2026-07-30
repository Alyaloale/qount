from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar
from qount.research_data.market_data import Funding
from qount.research_data.market_data import day_url
from qount.research_data.market_data import download_day
from qount.research_data.market_data import load_funding
from qount.research_data.market_data import load_klines
from qount.research_data.market_data import parse_zip_bytes
from qount.models import utc_now
from qount.settings import Settings

from .exchange_rules import SymbolRules
from .exchange_rules import evaluate_period_filter_coverage
from .exchange_rules import load_symbol_rules
from .historical_dvol import HISTORICAL_DVOL_VERSION
from .historical_dvol import HOUR_MS
from .source_capacity import FROZEN_OPTIONS_DVOL_CONTRACT
from .source_capacity import FROZEN_OPTIONS_DVOL_PROTOCOL
from .source_capacity import OPTIONS_DVOL_PREREGISTRATION_VERSION
from .source_capacity import FrozenOptionsDvolContract
from .source_capacity import OptionsDvolProtocol
from .tradeflow_experiment import FrozenTradeFlowContract
from .tradeflow_experiment import _align_bars
from .tradeflow_experiment import _ic_samples
from .tradeflow_experiment import _information_coefficient
from .tradeflow_experiment import _largest_contributor_removed_return
from .tradeflow_experiment import _month_end_exclusive_ms
from .tradeflow_experiment import _month_start_ms
from .tradeflow_experiment import _parse_month
from .tradeflow_experiment import _score_periods


OPTIONS_DVOL_EXPERIMENT_VERSION = "alpha_agent_options_dvol_experiment_v0.1"


@dataclass(frozen=True)
class OptionsDvolExperimentConfig:
    dvol_path: str
    preregistration_path: str
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    strategy_symbol: str = "ETHUSDT"
    start_month: str = "2021-04"
    end_month: str = "2024-12"
    holdout_role: str = "discovery_pool"
    market: str = "um"
    kline_cache_dir: str = "state/alpha_agents/binance_klines"
    funding_cache_dir: str = "state/alpha_agents/binance_funding"
    exchange_rules_path: str | None = None
    include_funding: bool = True
    account_equity_usdt: float = 400.0
    target_notional_fraction: float = 1.0
    leverage: float = 1.0
    request_retries: int = 3
    request_timeout_seconds: float = 60.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_json(path: str | Path) -> tuple[dict[str, Any], Path, str]:
    source = Path(path).expanduser().resolve()
    blob = source.read_bytes()
    return json.loads(blob), source, hashlib.sha256(blob).hexdigest()


def _window_dates(raw: str) -> tuple[str, str]:
    parts = raw.split("..")
    if len(parts) != 2:
        raise ValueError("protocol discovery window must contain one '..' separator")
    return parts[0][:10], parts[1][:10]


def _engine_contract(contract: FrozenOptionsDvolContract) -> FrozenTradeFlowContract:
    return FrozenTradeFlowContract(
        contract_id=contract.contract_id,
        source_feature=contract.source_feature,
        decision_interval_hours=1,
        normalization_lookback_hours=contract.normalization_lookback_hours,
        entry_zscore=contract.entry_zscore,
        polarity=contract.polarity,
        holding_hours=contract.holding_hours,
        cooldown_hours=contract.cooldown_hours,
        beta_lookback_hours=contract.beta_lookback_hours,
        minimum_rank_ic=0.0,
        minimum_entry_count=contract.minimum_entry_count_per_symbol,
        maximum_rolling_24h_turnover=0.0,
    )


def build_dvol_hourly_signals(
    rows: list[dict[str, Any]],
    *,
    contract: FrozenOptionsDvolContract = FROZEN_OPTIONS_DVOL_CONTRACT,
) -> list[dict[str, Any]]:
    ordered = sorted((row for row in rows if bool(row.get("complete"))), key=lambda row: int(row["ts_ms"]))
    window: deque[float] = deque()
    rolling_sum = 0.0
    rolling_sum_sq = 0.0
    previous_ts: int | None = None
    segment_id = 0
    result: list[dict[str, Any]] = []
    for row in ordered:
        ts_ms = int(row["ts_ms"])
        if previous_ts is not None and ts_ms - previous_ts != HOUR_MS:
            window.clear()
            rolling_sum = 0.0
            rolling_sum_sq = 0.0
            segment_id += 1
        raw_value = float(row["eth_minus_btc_dvol_close"])
        signal_zscore: float | None = None
        if len(window) >= contract.normalization_min_periods:
            mean = rolling_sum / len(window)
            variance = max(0.0, rolling_sum_sq / len(window) - mean * mean)
            std = math.sqrt(variance)
            if std > 0:
                signal_zscore = (raw_value - mean) / std * contract.polarity
        result.append(
            {
                "hour_ts_ms": ts_ms,
                "decision_ts_ms": int(row["decision_ts_ms"]),
                "segment_id": segment_id,
                "raw_feature_value": raw_value,
                "signal_zscore": signal_zscore,
            }
        )
        window.append(raw_value)
        rolling_sum += raw_value
        rolling_sum_sq += raw_value * raw_value
        if len(window) > contract.normalization_lookback_hours:
            removed = window.popleft()
            rolling_sum -= removed
            rolling_sum_sq -= removed * removed
        previous_ts = ts_ms
    return result


def _archive_fetch(url: str, *, timeout_seconds: float, retries: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qount-options-dvol/0.1"})
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


def _parse_checksum(raw: bytes, filename: str) -> str:
    parts = raw.decode("utf-8").strip().split()
    digest = parts[0].lower() if parts else ""
    declared = parts[-1].lstrip("*") if len(parts) >= 2 else ""
    if (
        len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        or declared != filename
    ):
        raise ValueError(f"invalid Binance checksum sidecar for {filename}")
    return digest


def _fill_daily_kline_gaps(
    *,
    symbol: str,
    bars: list[Bar],
    evaluation_start_ms: int,
    evaluation_end_ms: int,
    config: OptionsDvolExperimentConfig,
    fetch: Any,
) -> tuple[list[Bar], list[dict[str, Any]]]:
    indexed = {bar.ts_ms: bar for bar in bars}
    missing = [
        ts_ms
        for ts_ms in range(evaluation_start_ms, evaluation_end_ms, HOUR_MS)
        if ts_ms not in indexed
    ]
    missing_dates = sorted(
        {
            dt.datetime.fromtimestamp(ts_ms / 1000, dt.UTC).date()
            for ts_ms in missing
        }
    )
    provenance: list[dict[str, Any]] = []
    for day in missing_dates:
        url = day_url(
            symbol,
            "1h",
            day.year,
            day.month,
            day.day,
            market=config.market,
        )
        filename = url.rsplit("/", 1)[-1]
        source: dict[str, Any] = {
            "symbol": symbol,
            "date": day.isoformat(),
            "archive_url": url,
            "checksum_url": f"{url}.CHECKSUM",
            "status": "error",
        }
        try:
            expected_digest = _parse_checksum(fetch(f"{url}.CHECKSUM"), filename)
            blob = download_day(
                symbol,
                "1h",
                day.year,
                day.month,
                day.day,
                market=config.market,
                cache_dir=config.kline_cache_dir,
                fetch=fetch,
            )
            actual_digest = hashlib.sha256(blob).hexdigest()
            if actual_digest != expected_digest:
                raise ValueError(f"checksum mismatch for {filename}")
            parsed = parse_zip_bytes(blob)
            for bar in parsed:
                if evaluation_start_ms <= bar.ts_ms < evaluation_end_ms:
                    indexed[bar.ts_ms] = bar
            source.update(
                {
                    "status": "filled",
                    "checksum_sha256": actual_digest,
                    "checksum_verified": True,
                    "row_count": len(parsed),
                }
            )
        except Exception as exc:  # fail closed via the final frozen coverage gate
            source["error"] = f"{type(exc).__name__}: {exc}"
        provenance.append(source)
    return [indexed[ts_ms] for ts_ms in sorted(indexed)], provenance


def _build_periods(
    aligned: list[tuple[int, dict[str, Bar]]],
    hourly: list[dict[str, Any]],
    *,
    config: OptionsDvolExperimentConfig,
    contract: FrozenOptionsDvolContract,
    funding: list[Funding],
    evaluation_start_ms: int,
    evaluation_end_ms: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    features = {int(row["decision_ts_ms"]): row for row in hourly}
    funding_by_ts = {row.ts_ms: row.rate for row in funding}
    position = 0.0
    previous_position = 0.0
    hold_remaining = 0
    cooldown_remaining = 0
    previous_feature_segment: int | None = None
    entry_count = 0
    funding_settlement_count = 0
    total_funding_return_pct = 0.0
    per_turnover_cost_pct = (
        contract.fee_pct_per_position_change + contract.slippage_pct_per_position_change
    ) * 100.0
    periods: list[dict[str, Any]] = []
    for index in range(1, len(aligned)):
        ts_ms, bars = aligned[index]
        previous_ts, previous_bars = aligned[index - 1]
        if ts_ms < evaluation_start_ms:
            continue
        if ts_ms >= evaluation_end_ms:
            break
        if ts_ms - previous_ts != HOUR_MS:
            position = 0.0
            previous_position = 0.0
            hold_remaining = 0
            cooldown_remaining = contract.cooldown_hours
            previous_feature_segment = None
            continue
        feature = features.get(ts_ms)
        feature_segment = int(feature["segment_id"]) if feature is not None else None
        if feature is None:
            position = 0.0
            hold_remaining = 0
            cooldown_remaining = contract.cooldown_hours
            previous_feature_segment = None
        if (
            feature_segment is not None
            and previous_feature_segment is not None
            and feature_segment != previous_feature_segment
        ):
            position = 0.0
            hold_remaining = 0
            cooldown_remaining = contract.cooldown_hours
        if feature_segment is not None:
            previous_feature_segment = feature_segment
        if position != 0.0 and hold_remaining == 0:
            position = 0.0
            cooldown_remaining = contract.cooldown_hours
        if position == 0.0 and cooldown_remaining == 0 and feature is not None:
            zscore = feature.get("signal_zscore")
            if zscore is not None and abs(float(zscore)) >= contract.entry_zscore:
                position = 1.0 if float(zscore) > 0 else -1.0
                hold_remaining = contract.holding_hours
                entry_count += 1
        symbol_returns = {
            symbol: (bars[symbol].close / previous_bars[symbol].close - 1.0) * 100.0
            for symbol in config.symbols
        }
        turnover = abs(position - previous_position)
        cost_pct = turnover * per_turnover_cost_pct
        funding_rate = funding_by_ts.get(ts_ms + HOUR_MS)
        funding_return_pct = -position * funding_rate * 100.0 if funding_rate is not None else 0.0
        if funding_rate is not None:
            funding_settlement_count += 1
            total_funding_return_pct += funding_return_pct
        gross = position * symbol_returns[config.strategy_symbol]
        periods.append(
            {
                "ts": str(ts_ms),
                "strategy_return_pct": gross - cost_pct + funding_return_pct,
                "strategy_gross_return_pct": gross,
                "strategy_position": position,
                "strategy_position_applied": position,
                "strategy_turnover": turnover,
                "strategy_cost_pct": cost_pct,
                "strategy_funding_return_pct": funding_return_pct,
                "strategy_feature_value": feature.get("signal_zscore") if feature else None,
                "strategy_raw_feature_value": feature.get("raw_feature_value") if feature else None,
                "strategy_close": previous_bars[config.strategy_symbol].close,
                "strategy_period_end_close": bars[config.strategy_symbol].close,
                "btc_return_pct": symbol_returns["BTCUSDT"],
                "top3_equal_weight_return_pct": sum(symbol_returns.values()) / len(symbol_returns),
                "current_live_baseline_return_pct": 0.0,
                "cash_return_pct": 0.0,
            }
        )
        previous_position = position
        if position != 0.0:
            hold_remaining -= 1
        elif cooldown_remaining > 0:
            cooldown_remaining -= 1
    if periods and position != 0.0:
        closing_cost = abs(position) * per_turnover_cost_pct
        periods[-1]["strategy_return_pct"] -= closing_cost
        periods[-1]["strategy_turnover"] += abs(position)
        periods[-1]["strategy_cost_pct"] += closing_cost
        periods[-1]["strategy_position"] = 0.0
        periods[-1]["strategy_close"] = periods[-1]["strategy_period_end_close"]
        periods[-1]["forced_final_close"] = True
    turnovers = [float(row["strategy_turnover"]) for row in periods]
    max_rolling_turnover = max(
        (sum(turnovers[max(0, index - 23) : index + 1]) for index in range(len(turnovers))),
        default=0.0,
    )
    return periods, {
        "entry_count": entry_count,
        "active_hour_count": sum(float(row["strategy_position_applied"]) != 0.0 for row in periods),
        "total_turnover": sum(turnovers),
        "average_daily_turnover": sum(turnovers) / (len(periods) / 24.0) if periods else 0.0,
        "max_rolling_24h_turnover": max_rolling_turnover,
        "per_turnover_cost_pct": per_turnover_cost_pct,
        "funding_settlement_count": funding_settlement_count,
        "total_funding_return_pct": total_funding_return_pct,
    }


def build_options_dvol_experiment(
    config: OptionsDvolExperimentConfig,
    *,
    contract: FrozenOptionsDvolContract = FROZEN_OPTIONS_DVOL_CONTRACT,
    protocol: OptionsDvolProtocol = FROZEN_OPTIONS_DVOL_PROTOCOL,
    bars_by_symbol: dict[str, list[Bar]] | None = None,
    funding: list[Funding] | None = None,
    rules_by_symbol: dict[str, SymbolRules] | None = None,
) -> dict[str, Any]:
    if tuple(config.symbols) != ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"):
        raise ValueError("options-DVOL discovery requires the frozen four-symbol price denominator")
    if config.strategy_symbol not in protocol.discovery_symbols:
        raise ValueError("strategy_symbol must be one of the frozen discovery symbols")
    if config.market != "um" or protocol.price_interval != "1h":
        raise ValueError("options-DVOL v0 requires Binance USD-M 1h prices")
    if config.holdout_role != protocol.discovery_holdout_role:
        raise ValueError("holdout role does not match the frozen discovery protocol")
    if not config.include_funding or not contract.funding_included:
        raise ValueError("the frozen options-DVOL discovery requires funding")
    if protocol.contract_hash != contract.contract_hash:
        raise ValueError("protocol does not match the frozen options-DVOL contract")
    discovery_start, discovery_end = _window_dates(protocol.discovery_window)
    if config.start_month != discovery_start[:7] or config.end_month != discovery_end[:7]:
        raise ValueError("experiment months do not match the frozen discovery window")

    preregistration, prereg_path, prereg_sha = _load_json(config.preregistration_path)
    if (
        preregistration.get("schema_version") != OPTIONS_DVOL_PREREGISTRATION_VERSION
        or preregistration.get("artifact_type") != "preregistration"
        or preregistration.get("contract", {}).get("contract_hash") != contract.contract_hash
        or preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash
        or preregistration.get("diagnostics", {}).get("strategy_results_evaluated") is not False
    ):
        raise ValueError("preregistration does not match the frozen options-DVOL v0.3 protocol")
    dvol, dvol_path, dvol_sha = _load_json(config.dvol_path)
    if (
        dvol.get("schema_version") != HISTORICAL_DVOL_VERSION
        or dvol.get("artifact_type") != "historical_dvol_dataset"
        or dvol.get("diagnostics", {}).get("verdict") != "pass_dataset"
        or dvol.get("meta", {}).get("strategy_results_evaluated") is not False
        or dvol.get("config", {}).get("start_date") != discovery_start
        or dvol.get("config", {}).get("end_date") != discovery_end
    ):
        raise ValueError("DVOL artifact does not match the frozen discovery data contract")
    hourly = build_dvol_hourly_signals(dvol["hourly_features"], contract=contract)
    start = _parse_month(config.start_month)
    end = _parse_month(config.end_month)
    fetch = lambda url: _archive_fetch(
        url,
        timeout_seconds=config.request_timeout_seconds,
        retries=config.request_retries,
    )
    daily_gap_fills: list[dict[str, Any]] = []
    if bars_by_symbol is None:
        bars_by_symbol = {
            symbol: load_klines(
                symbol,
                protocol.price_interval,
                start=start,
                end=end,
                market=config.market,
                cache_dir=config.kline_cache_dir,
                fetch=fetch,
                skip_missing=True,
            )
            for symbol in config.symbols
        }
        for symbol in config.symbols:
            bars_by_symbol[symbol], repairs = _fill_daily_kline_gaps(
                symbol=symbol,
                bars=bars_by_symbol[symbol],
                evaluation_start_ms=_month_start_ms(config.start_month),
                evaluation_end_ms=_month_end_exclusive_ms(config.end_month),
                config=config,
                fetch=fetch,
            )
            daily_gap_fills.extend(repairs)
    if funding is None:
        funding = load_funding(
            config.strategy_symbol,
            start=start,
            end=end,
            cache_dir=config.funding_cache_dir,
            fetch=fetch,
            skip_missing=True,
        )
    aligned = _align_bars(bars_by_symbol, config.symbols)
    if not aligned:
        raise ValueError("no common 1h kline periods")
    evaluation_start_ms = _month_start_ms(config.start_month)
    evaluation_end_ms = _month_end_exclusive_ms(config.end_month)
    expected_price_hours = len(range(evaluation_start_ms, evaluation_end_ms, HOUR_MS))
    by_symbol_price_coverage = {
        symbol: min(
            1.0,
            len({bar.ts_ms for bar in bars_by_symbol[symbol] if evaluation_start_ms <= bar.ts_ms < evaluation_end_ms})
            / expected_price_hours,
        )
        for symbol in config.symbols
    }
    aligned_price_coverage = min(1.0, len(aligned) / expected_price_hours)
    engine_contract = _engine_contract(contract)
    samples = _ic_samples(
        aligned,
        hourly,
        strategy_symbol=config.strategy_symbol,
        contract=engine_contract,
        evaluation_start_ms=evaluation_start_ms,
        evaluation_end_ms=evaluation_end_ms,
    )
    ic = _information_coefficient(
        [float(sample["feature_value"]) for sample in samples],
        [float(sample["residual_forward_return_pct"]) for sample in samples],
    )
    periods, execution = _build_periods(
        aligned,
        hourly,
        config=config,
        contract=contract,
        funding=funding,
        evaluation_start_ms=evaluation_start_ms,
        evaluation_end_ms=evaluation_end_ms,
    )
    if not periods:
        raise ValueError("no contiguous options-DVOL experiment periods")
    score = _score_periods(periods)
    if rules_by_symbol is None:
        if not config.exchange_rules_path:
            raise ValueError("--exchange-rules-path is required by the frozen protocol")
        rules_by_symbol = load_symbol_rules(config.exchange_rules_path, market=config.market)
    filter_diagnostics = evaluate_period_filter_coverage(
        periods,
        rules_by_symbol,
        symbol=config.strategy_symbol,
        account_equity_usdt=config.account_equity_usdt,
        target_notional_fraction=config.target_notional_fraction,
        leverage=config.leverage,
    )
    evaluation_hourly = [
        row for row in hourly if evaluation_start_ms <= int(row["decision_ts_ms"]) < evaluation_end_ms
    ]
    warmup_allowance = len({int(row["segment_id"]) for row in evaluation_hourly}) * contract.normalization_lookback_hours
    eligible_feature_hours = max(0, len(evaluation_hourly) - warmup_allowance)
    scored_feature_hours = sum(row.get("signal_zscore") is not None for row in evaluation_hourly)
    feature_coverage = (
        min(1.0, scored_feature_hours / eligible_feature_hours) if eligible_feature_hours else 0.0
    )
    blockers: list[str] = []
    if feature_coverage < protocol.minimum_feature_coverage:
        blockers.append("feature_coverage_below_protocol")
    if aligned_price_coverage < protocol.minimum_price_coverage or any(
        value < protocol.minimum_price_coverage for value in by_symbol_price_coverage.values()
    ):
        blockers.append("price_coverage_below_protocol")
    if float(ic["rank_ic"]) < protocol.minimum_symbol_rank_ic:
        blockers.append("rank_ic_below_protocol")
    if score["net_residual_return_pct"] <= protocol.minimum_symbol_net_residual_pct:
        blockers.append("cost_adjusted_beta_residual_non_positive")
    if execution["entry_count"] < contract.minimum_entry_count_per_symbol:
        blockers.append("entry_count_below_protocol")
    if execution["max_rolling_24h_turnover"] > protocol.maximum_rolling_24h_turnover + 1e-12:
        blockers.append("turnover_budget_exceeded")
    if filter_diagnostics["filter_coverage"] < protocol.minimum_filter_coverage:
        blockers.append("exchange_filter_coverage_incomplete")
    passed = not blockers
    price_data_hash = hashlib.sha256(
        json.dumps(
            {
                symbol: [(bar.ts_ms, bar.close) for bar in bars_by_symbol[symbol]]
                for symbol in config.symbols
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    funding_data_hash = hashlib.sha256(
        json.dumps([(row.ts_ms, row.rate) for row in funding]).encode("utf-8")
    ).hexdigest()
    exchange_rules_hash = hashlib.sha256(
        json.dumps(
            {symbol: rules_by_symbol[symbol].to_dict() for symbol in sorted(rules_by_symbol)},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    config_hash = hashlib.sha256(
        json.dumps(
            {"config": config.to_dict(), "contract": contract.to_dict(), "protocol": protocol.to_dict()},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": OPTIONS_DVOL_EXPERIMENT_VERSION,
        "artifact_type": "experiment",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "public_data_only": True,
            "orders_allowed": False,
            "point_in_time": True,
            "trial_count": protocol.selection_trials,
            "holdout_role": config.holdout_role,
            "costs_included": True,
            "funding_included": True,
            "filter_validator_reused": True,
            "data_hash": dvol.get("meta", {}).get("data_hash"),
            "price_data_hash": price_data_hash,
            "funding_data_hash": funding_data_hash,
            "exchange_rules_hash": exchange_rules_hash,
            "config_hash": config_hash,
            "contract_hash": contract.contract_hash,
            "protocol_hash": protocol.protocol_hash,
            "label_spec": f"{config.strategy_symbol} forward 24h return minus 720h as-of BTC beta",
            "cost_spec": "5bps taker fee + 2bps slippage per position change plus USD-M funding",
        },
        "config": config.to_dict(),
        "source_bindings": {
            "preregistration_path": str(prereg_path),
            "preregistration_sha256": prereg_sha,
            "dvol_path": str(dvol_path),
            "dvol_sha256": dvol_sha,
        },
        "decision_contract": {**contract.to_dict(), "contract_hash": contract.contract_hash},
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "diagnostics": {
            "verdict": "pass_discovery_symbol" if passed else "block_discovery_symbol",
            "holdout_role": config.holdout_role,
            "blockers": blockers,
            "feature_coverage": feature_coverage,
            "price_coverage": {
                "expected_hour_count": expected_price_hours,
                "aligned_hour_count": len(aligned),
                "aligned_coverage_ratio": aligned_price_coverage,
                "by_symbol": by_symbol_price_coverage,
                "daily_gap_fills": daily_gap_fills,
            },
            "ic": ic,
            "score": score,
            "execution": execution,
            "filter_diagnostics": filter_diagnostics,
            "largest_contributor_removed_return_pct": _largest_contributor_removed_return(periods),
            "historical_replication_consumed": False,
            "reserved_forward_oos_consumed": False,
            "promotion_allowed": False,
        },
        "ic_samples": samples,
        "hourly_features": hourly,
        "periods": periods,
    }


def _experiment_summary(payload: dict[str, Any], path: Path, digest: str) -> dict[str, Any]:
    diagnostics = payload.get("diagnostics", {})
    return {
        "symbol": str(payload.get("config", {}).get("strategy_symbol", "")).upper(),
        "path": str(path),
        "sha256": digest,
        "contract_hash": payload.get("decision_contract", {}).get("contract_hash"),
        "protocol_hash": payload.get("protocol", {}).get("protocol_hash"),
        "holdout_role": diagnostics.get("holdout_role"),
        "verdict": diagnostics.get("verdict"),
        "rank_ic": float(diagnostics.get("ic", {}).get("rank_ic", 0.0)),
        "net_residual_return_pct": float(diagnostics.get("score", {}).get("net_residual_return_pct", 0.0)),
        "entry_count": int(diagnostics.get("execution", {}).get("entry_count", 0)),
        "max_rolling_24h_turnover": float(
            diagnostics.get("execution", {}).get("max_rolling_24h_turnover", 0.0)
        ),
        "filter_coverage": float(diagnostics.get("filter_diagnostics", {}).get("filter_coverage", 0.0)),
        "feature_coverage": float(diagnostics.get("feature_coverage", 0.0)),
        "price_coverage": float(
            diagnostics.get("price_coverage", {}).get("aligned_coverage_ratio", 0.0)
        ),
        "blockers": list(diagnostics.get("blockers", [])),
    }


def build_options_dvol_discovery_report(
    *,
    preregistration_path: str | Path,
    experiment_paths: list[str | Path],
    protocol: OptionsDvolProtocol = FROZEN_OPTIONS_DVOL_PROTOCOL,
) -> dict[str, Any]:
    preregistration, prereg_path, prereg_sha = _load_json(preregistration_path)
    if (
        preregistration.get("schema_version") != OPTIONS_DVOL_PREREGISTRATION_VERSION
        or preregistration.get("artifact_type") != "preregistration"
        or preregistration.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash
    ):
        raise ValueError("preregistration does not match the frozen options-DVOL protocol")
    summaries: dict[str, dict[str, Any]] = {}
    for experiment_path in experiment_paths:
        payload, source, digest = _load_json(experiment_path)
        if (
            payload.get("schema_version") != OPTIONS_DVOL_EXPERIMENT_VERSION
            or payload.get("artifact_type") != "experiment"
        ):
            raise ValueError("experiment path is not an options-DVOL experiment")
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
    protocol_mismatches = sorted(
        row["symbol"] for row in ordered if row["protocol_hash"] != protocol.protocol_hash
    )
    role_mismatches = sorted(
        row["symbol"] for row in ordered if row["holdout_role"] != protocol.discovery_holdout_role
    )
    passing_count = sum(row["verdict"] == "pass_discovery_symbol" for row in ordered)
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
    feature_complete = bool(ordered) and all(
        row["feature_coverage"] >= protocol.minimum_feature_coverage for row in ordered
    )
    price_complete = bool(ordered) and all(
        row["price_coverage"] >= protocol.minimum_price_coverage for row in ordered
    )
    blockers: list[str] = []
    if missing:
        blockers.append("registered_symbol_missing")
    if unexpected:
        blockers.append("unexpected_symbol_present")
    if contract_mismatches:
        blockers.append("frozen_contract_mismatch")
    if protocol_mismatches:
        blockers.append("frozen_protocol_mismatch")
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
    if not feature_complete:
        blockers.append("feature_coverage_incomplete")
    if not price_complete:
        blockers.append("price_coverage_incomplete")
    passed = not blockers
    return {
        "schema_version": OPTIONS_DVOL_EXPERIMENT_VERSION,
        "artifact_type": "discovery_report",
        "created_at": utc_now().isoformat(),
        "protocol": {**protocol.to_dict(), "protocol_hash": protocol.protocol_hash},
        "preregistration": {"path": str(prereg_path), "sha256": prereg_sha},
        "experiments": {row["symbol"]: row for row in ordered},
        "diagnostics": {
            "verdict": "advance_to_replication_authorization" if passed else "block_discovery",
            "blockers": blockers,
            "missing_symbols": missing,
            "unexpected_symbols": unexpected,
            "contract_mismatches": contract_mismatches,
            "protocol_mismatches": protocol_mismatches,
            "holdout_role_mismatches": role_mismatches,
            "passing_symbol_count": passing_count,
            "positive_rank_ic_count": positive_ic_count,
            "positive_residual_count": positive_residual_count,
            "median_rank_ic": median_ic,
            "mean_net_residual_return_pct": mean_residual,
            "filter_coverage_complete": filter_complete,
            "turnover_within_budget": turnover_ok,
            "feature_coverage_complete": feature_complete,
            "price_coverage_complete": price_complete,
            "historical_replication_consumed": False,
            "reserved_forward_oos_consumed": False,
            "a10_enabled": False,
            "promotion_allowed": False,
            "next_action": (
                "write a replication authorization binding this report before loading 2025 returns"
                if passed
                else "stop the options-DVOL hypothesis without parameter rescue or 2025 return evaluation"
            ),
        },
        "hard_boundary": "This report cannot authorize A10, paper, live, VPS changes, private API access, or orders.",
    }


def write_options_dvol_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-options-dvol",
        path_key="artifact_path",
        default_filename="alpha_agent_options_dvol.json",
        explicit_path=explicit_path,
    )
