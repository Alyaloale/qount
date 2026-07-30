from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar
from qount.research_data.market_data import Funding
from qount.research_data.market_data import load_funding
from qount.research_data.market_data import load_klines
from qount.settings import Settings

from .exchange_rules import SymbolRules
from .exchange_rules import evaluate_period_filter_coverage
from .exchange_rules import load_symbol_rules
from .historical_tradeflow import HISTORICAL_TRADEFLOW_VERSION


TRADEFLOW_EXPERIMENT_VERSION = "alpha_agent_tradeflow_experiment_v0.1"
HOUR_MS = 60 * 60_000


@dataclass(frozen=True)
class FrozenTradeFlowContract:
    contract_id: str = "agg_trade_imbalance_z168_entry2_hold6_cooldown18_momentum_v1"
    source_feature: str = "agg_trade_imbalance"
    decision_interval_hours: int = 1
    normalization_lookback_hours: int = 168
    entry_zscore: float = 2.0
    polarity: int = 1
    holding_hours: int = 6
    cooldown_hours: int = 18
    beta_lookback_hours: int = 168
    minimum_rank_ic: float = 0.02
    minimum_entry_count: int = 10
    maximum_rolling_24h_turnover: float = 2.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()


FROZEN_LOW_TURNOVER_CONTRACT = FrozenTradeFlowContract()


@dataclass(frozen=True)
class TradeFlowExperimentConfig:
    tradeflow_path: str
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


HourlySignalTransform = Callable[
    [
        list[dict[str, Any]],
        list[tuple[int, dict[str, Bar]]],
        TradeFlowExperimentConfig,
        FrozenTradeFlowContract,
    ],
    list[dict[str, Any]],
]


def _parse_month(raw: str) -> tuple[int, int]:
    parsed = dt.datetime.strptime(raw, "%Y-%m")
    return parsed.year, parsed.month


def _month_start_ms(raw: str) -> int:
    year, month = _parse_month(raw)
    return int(dt.datetime(year, month, 1, tzinfo=dt.UTC).timestamp() * 1000)


def _month_end_exclusive_ms(raw: str) -> int:
    year, month = _parse_month(raw)
    if month == 12:
        following = dt.datetime(year + 1, 1, 1, tzinfo=dt.UTC)
    else:
        following = dt.datetime(year, month + 1, 1, tzinfo=dt.UTC)
    return int(following.timestamp() * 1000)


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


def _correlation(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(_variance(left) * _variance(right))
    return _covariance(left, right) / denominator if denominator > 0 else 0.0


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
            end += 1
        rank = (cursor + end - 1) / 2.0 + 1.0
        for index in ordered[cursor:end]:
            result[index] = rank
        cursor = end
    return result


def _information_coefficient(features: list[float], labels: list[float]) -> dict[str, float | int]:
    if len(features) != len(labels) or len(features) < 2:
        return {"sample_count": len(features), "pearson_ic": 0.0, "rank_ic": 0.0}
    return {
        "sample_count": len(features),
        "pearson_ic": _correlation(features, labels),
        "rank_ic": _correlation(_ranks(features), _ranks(labels)),
    }


def _compound_pct(values: list[float]) -> float:
    total = 1.0
    for value in values:
        total *= 1.0 + value / 100.0
    return (total - 1.0) * 100.0


def _load_tradeflow(path: str) -> tuple[dict[str, Any], str]:
    source = Path(path).expanduser()
    raw = source.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != HISTORICAL_TRADEFLOW_VERSION:
        raise ValueError("trade-flow path must contain a historical trade-flow artifact")
    if not isinstance(payload.get("five_minute_features"), list):
        raise ValueError("trade-flow artifact must contain five_minute_features")
    return payload, hashlib.sha256(raw).hexdigest()


def aggregate_five_minute_to_hourly(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    contract: FrozenTradeFlowContract = FROZEN_LOW_TURNOVER_CONTRACT,
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in rows
        if str(row.get("symbol", "")).upper() == symbol.upper()
        and int(row.get("agg_trade_count", 0)) > 0
    ]
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in selected:
        ts_ms = int(row["ts_ms"])
        buckets.setdefault(ts_ms // HOUR_MS * HOUR_MS, []).append(row)
    hourly: list[dict[str, Any]] = []
    prior_by_segment: dict[int, list[float]] = {}
    for hour_ts in sorted(buckets):
        bucket_rows = sorted(buckets[hour_ts], key=lambda row: int(row["ts_ms"]))
        expected = [hour_ts + offset * 5 * 60_000 for offset in range(12)]
        actual = [int(row["ts_ms"]) for row in bucket_rows]
        segment_ids = {int(row.get("segment_id", -1)) for row in bucket_rows}
        if actual != expected or len(segment_ids) != 1 or not all(bool(row.get("complete", True)) for row in bucket_rows):
            continue
        buy_quote = sum(float(row.get("aggressive_buy_quote_volume", 0.0)) for row in bucket_rows)
        sell_quote = sum(float(row.get("aggressive_sell_quote_volume", 0.0)) for row in bucket_rows)
        total_quote = buy_quote + sell_quote
        imbalance = (buy_quote - sell_quote) / total_quote if total_quote > 0 else 0.0
        segment_id = next(iter(segment_ids))
        prior = prior_by_segment.setdefault(segment_id, [])
        zscore: float | None = None
        if len(prior) >= contract.normalization_lookback_hours:
            history = prior[-contract.normalization_lookback_hours :]
            mean = _mean(history)
            std = math.sqrt(sum((value - mean) ** 2 for value in history) / len(history))
            if std > 0:
                zscore = (imbalance - mean) / std * contract.polarity
        book_event_count = sum(int(row.get("book_ticker_event_count", 0)) for row in bucket_rows)
        book_spread_numerator = sum(
            float(row.get("book_spread_bps_mean", 0.0)) * int(row.get("book_ticker_event_count", 0))
            for row in bucket_rows
            if row.get("book_spread_bps_mean") is not None
        )
        book_imbalance_numerator = sum(
            float(row.get("book_top_imbalance_mean", 0.0)) * int(row.get("book_ticker_event_count", 0))
            for row in bucket_rows
            if row.get("book_top_imbalance_mean") is not None
        )
        hourly.append(
            {
                "symbol": symbol.upper(),
                "hour_ts_ms": hour_ts,
                "decision_ts_ms": hour_ts + HOUR_MS,
                "segment_id": segment_id,
                "five_minute_bucket_count": len(bucket_rows),
                "agg_trade_count": sum(int(row["agg_trade_count"]) for row in bucket_rows),
                "agg_trade_quote_volume": total_quote,
                "aggressive_buy_quote_volume": buy_quote,
                "aggressive_sell_quote_volume": sell_quote,
                "agg_trade_imbalance": imbalance,
                "signal_zscore": zscore,
                "book_ticker_event_count": book_event_count,
                "book_spread_bps_mean": book_spread_numerator / book_event_count if book_event_count else None,
                "book_top_imbalance_mean": book_imbalance_numerator / book_event_count if book_event_count else None,
            }
        )
        prior.append(imbalance)
    return hourly


def _align_bars(bars_by_symbol: dict[str, list[Bar]], symbols: tuple[str, ...]) -> list[tuple[int, dict[str, Bar]]]:
    maps = {symbol: {bar.ts_ms: bar for bar in bars_by_symbol[symbol]} for symbol in symbols}
    common = set(maps[symbols[0]])
    for symbol in symbols[1:]:
        common &= set(maps[symbol])
    return [(ts_ms, {symbol: maps[symbol][ts_ms] for symbol in symbols}) for ts_ms in sorted(common)]


def _rolling_beta_before_decision(
    aligned: list[tuple[int, dict[str, Bar]]],
    *,
    index: int,
    strategy_symbol: str,
    lookback: int,
) -> float | None:
    start = max(1, index - lookback)
    strategy_returns: list[float] = []
    btc_returns: list[float] = []
    for return_index in range(start, index):
        current_ts, current = aligned[return_index]
        previous_ts, previous = aligned[return_index - 1]
        if current_ts - previous_ts != HOUR_MS:
            strategy_returns.clear()
            btc_returns.clear()
            continue
        strategy_returns.append(current[strategy_symbol].close / previous[strategy_symbol].close - 1.0)
        btc_returns.append(current["BTCUSDT"].close / previous["BTCUSDT"].close - 1.0)
    if len(strategy_returns) < min(20, lookback):
        return None
    btc_variance = _variance(btc_returns)
    return _covariance(strategy_returns, btc_returns) / btc_variance if btc_variance > 0 else 0.0


def _ic_samples(
    aligned: list[tuple[int, dict[str, Bar]]],
    hourly: list[dict[str, Any]],
    *,
    strategy_symbol: str,
    contract: FrozenTradeFlowContract,
    evaluation_start_ms: int,
    evaluation_end_ms: int,
) -> list[dict[str, Any]]:
    index_by_ts = {ts_ms: index for index, (ts_ms, _row) in enumerate(aligned)}
    samples: list[dict[str, Any]] = []
    for feature in hourly:
        zscore = feature.get("signal_zscore")
        decision_ts_ms = int(feature["decision_ts_ms"])
        if decision_ts_ms < evaluation_start_ms or decision_ts_ms >= evaluation_end_ms:
            continue
        index = index_by_ts.get(decision_ts_ms)
        if zscore is None or index is None or index <= 0:
            continue
        end_index = index + contract.holding_hours - 1
        if end_index >= len(aligned):
            continue
        if aligned[end_index][0] - aligned[index][0] != (contract.holding_hours - 1) * HOUR_MS:
            continue
        beta = _rolling_beta_before_decision(
            aligned,
            index=index,
            strategy_symbol=strategy_symbol,
            lookback=contract.beta_lookback_hours,
        )
        if beta is None:
            continue
        start = aligned[index - 1][1]
        end = aligned[end_index][1]
        strategy_forward = (end[strategy_symbol].close / start[strategy_symbol].close - 1.0) * 100.0
        btc_forward = (end["BTCUSDT"].close / start["BTCUSDT"].close - 1.0) * 100.0
        samples.append(
            {
                "decision_ts_ms": int(feature["decision_ts_ms"]),
                "feature_value": float(zscore),
                "residual_forward_return_pct": strategy_forward - beta * btc_forward,
                "beta_to_btc": beta,
            }
        )
    return samples


def _funding_by_hour(
    funding: list[Funding],
    *,
    period_start_ts: int,
    period_end_ts: int,
    position: float,
) -> tuple[float, int]:
    rows = [row for row in funding if period_start_ts < row.ts_ms <= period_end_ts]
    return sum(-position * row.rate * 100.0 for row in rows), len(rows)


def _build_periods(
    aligned: list[tuple[int, dict[str, Bar]]],
    hourly: list[dict[str, Any]],
    *,
    config: TradeFlowExperimentConfig,
    contract: FrozenTradeFlowContract,
    funding: list[Funding],
    evaluation_start_ms: int,
    evaluation_end_ms: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    features = {int(row["decision_ts_ms"]): row for row in hourly}
    position = 0.0
    previous_position = 0.0
    hold_remaining = 0
    cooldown_remaining = 0
    previous_feature_segment: int | None = None
    entry_count = 0
    funding_settlement_count = 0
    total_funding_return_pct = 0.0
    per_turnover_cost_pct = (config.fee_pct + config.slippage_pct) * 100.0
    periods: list[dict[str, Any]] = []
    for index in range(1, len(aligned)):
        ts_ms, row = aligned[index]
        previous_ts, previous_row = aligned[index - 1]
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
            symbol: (row[symbol].close / previous_row[symbol].close - 1.0) * 100.0
            for symbol in config.symbols
        }
        turnover = abs(position - previous_position)
        cost_pct = turnover * per_turnover_cost_pct
        funding_return_pct, funding_count = _funding_by_hour(
            funding,
            period_start_ts=ts_ms,
            period_end_ts=ts_ms + HOUR_MS,
            position=position,
        )
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
                "strategy_feature_value": feature.get("signal_zscore") if feature is not None else None,
                "strategy_raw_feature_value": (
                    feature.get("raw_feature_value", feature.get("agg_trade_imbalance"))
                    if feature is not None
                    else None
                ),
                "strategy_close": previous_row[config.strategy_symbol].close,
                "strategy_period_end_close": row[config.strategy_symbol].close,
                "btc_return_pct": symbol_returns["BTCUSDT"],
                "top3_equal_weight_return_pct": sum(symbol_returns.values()) / len(symbol_returns),
                "current_live_baseline_return_pct": 0.0,
                "cash_return_pct": 0.0,
            }
        )
        funding_settlement_count += funding_count
        total_funding_return_pct += funding_return_pct
        previous_position = position
        if position != 0.0:
            hold_remaining -= 1
        elif cooldown_remaining > 0:
            cooldown_remaining -= 1
    if periods and position != 0.0:
        closing_turnover = abs(position)
        closing_cost = closing_turnover * per_turnover_cost_pct
        periods[-1]["strategy_return_pct"] -= closing_cost
        periods[-1]["strategy_turnover"] += closing_turnover
        periods[-1]["strategy_cost_pct"] += closing_cost
        periods[-1]["strategy_position"] = 0.0
        periods[-1]["strategy_close"] = periods[-1]["strategy_period_end_close"]
        periods[-1]["forced_final_close"] = True
    turnovers = [float(row["strategy_turnover"]) for row in periods]
    max_rolling_turnover = max(
        (sum(turnovers[max(0, index - 23) : index + 1]) for index in range(len(turnovers))),
        default=0.0,
    )
    active_hours = sum(float(row["strategy_position_applied"]) != 0.0 for row in periods)
    return periods, {
        "entry_count": entry_count,
        "active_hour_count": active_hours,
        "total_turnover": sum(turnovers),
        "average_daily_turnover": sum(turnovers) / (len(periods) / 24.0) if periods else 0.0,
        "max_rolling_24h_turnover": max_rolling_turnover,
        "per_turnover_cost_pct": per_turnover_cost_pct,
        "funding_settlement_count": funding_settlement_count,
        "total_funding_return_pct": total_funding_return_pct,
    }


def _score_periods(periods: list[dict[str, Any]]) -> dict[str, float]:
    strategy = [float(row["strategy_return_pct"]) for row in periods]
    btc = [float(row["btc_return_pct"]) for row in periods]
    top3 = [float(row["top3_equal_weight_return_pct"]) for row in periods]
    btc_variance = _variance(btc)
    beta = _covariance(strategy, btc) / btc_variance if btc_variance > 0 else 0.0
    residual = [strategy_return - beta * btc_return for strategy_return, btc_return in zip(strategy, btc)]
    return {
        "strategy_total_return_pct": _compound_pct(strategy),
        "btc_total_return_pct": _compound_pct(btc),
        "top3_equal_weight_total_return_pct": _compound_pct(top3),
        "beta_to_btc": beta,
        "net_residual_return_pct": sum(residual),
    }


def _largest_contributor_removed_return(periods: list[dict[str, Any]]) -> float:
    returns = [float(row["strategy_return_pct"]) for row in periods]
    if len(returns) <= 1:
        return 0.0
    largest = max(range(len(returns)), key=lambda index: returns[index])
    return _compound_pct([value for index, value in enumerate(returns) if index != largest])


def build_tradeflow_experiment(
    config: TradeFlowExperimentConfig,
    *,
    contract: FrozenTradeFlowContract = FROZEN_LOW_TURNOVER_CONTRACT,
    bars_by_symbol: dict[str, list[Bar]] | None = None,
    funding: list[Funding] | None = None,
    rules_by_symbol: dict[str, SymbolRules] | None = None,
    hourly_signal_transform: HourlySignalTransform | None = None,
    strategy_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not config.symbols or "BTCUSDT" not in config.symbols:
        raise ValueError("symbols must include BTCUSDT")
    if config.strategy_symbol not in config.symbols:
        raise ValueError("strategy_symbol must be included in symbols")
    if config.market != "um":
        raise ValueError("trade-flow experiment currently supports Binance USD-M only")
    if config.holdout_role not in {"discovery", "historical_oos"}:
        raise ValueError("holdout_role must be 'discovery' or 'historical_oos'")
    if not 0 < config.min_feature_coverage <= 1:
        raise ValueError("min_feature_coverage must be in (0,1]")
    if contract.decision_interval_hours != 1:
        raise ValueError("frozen trade-flow contract requires 1h decisions")
    tradeflow, source_hash = _load_tradeflow(config.tradeflow_path)
    evaluation_start_month = config.evaluation_start_month or config.start_month
    evaluation_end_month = config.evaluation_end_month or config.end_month
    evaluation_start_ms = _month_start_ms(evaluation_start_month)
    evaluation_end_ms = _month_end_exclusive_ms(evaluation_end_month)
    if evaluation_end_ms <= evaluation_start_ms:
        raise ValueError("evaluation_end_month must not precede evaluation_start_month")
    hourly = aggregate_five_minute_to_hourly(
        tradeflow["five_minute_features"],
        symbol=config.strategy_symbol,
        contract=contract,
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
    if hourly_signal_transform is not None:
        hourly = hourly_signal_transform(hourly, aligned, config, contract)
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
    samples = _ic_samples(
        aligned,
        hourly,
        strategy_symbol=config.strategy_symbol,
        contract=contract,
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
        raise ValueError("no contiguous experiment periods")
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
    if config.evaluation_start_month:
        eligible_hours = complete_hour_count
    else:
        warmup_allowance = segment_count * contract.normalization_lookback_hours
        eligible_hours = max(0, complete_hour_count - warmup_allowance)
    feature_coverage = min(1.0, scored_hour_count / eligible_hours) if eligible_hours else 0.0
    blockers: list[str] = []
    if tradeflow.get("diagnostics", {}).get("verdict") != "pass_data_smoke":
        blockers.append("source_tradeflow_blocked")
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
    metadata = strategy_metadata or {}
    meta = {
        "point_in_time": True,
        "as_of_join": True,
        "replayable": tradeflow.get("meta", {}).get("replayable", False),
        "trial_count": 1,
        "exchange_rules_source": "runtime_exchange_info" if rules_by_symbol is not None else "missing",
        "filter_validator_reused": rules_by_symbol is not None,
        "costs_included": True,
        "funding_included": config.include_funding,
        "min_notional_coverage": filter_diagnostics["min_notional_coverage"],
        "worst_case_cost_buffer_pct": 0.0,
        "effective_breadth": 1.0,
        "claims_cross_sectional_edge": bool(metadata.get("claims_cross_sectional_edge", False)),
        "correlation_stress_pass": False,
        "capacity_checked": rules_by_symbol is not None,
        "label_spec": f"{config.strategy_symbol} forward {contract.holding_hours}h return minus as-of BTC beta",
        "benchmark_spec": "cash/BTC/TOP equal-weight/current live baseline",
        "data_spec": metadata.get(
            "data_spec",
            "checksum-verified Binance USD-M aggTrades aggregated 5m then 1h",
        ),
        "cost_spec": "taker fee + slippage per position change plus USD-M funding",
        "kill_line": metadata.get(
            "kill_line",
            "do not read independent OOS unless Q1 rank IC, net beta residual, coverage and turnover gates pass",
        ),
        "largest_contributor_removed_return_pct": largest_removed,
        "embargo_applied": False,
        "data_hash": source_hash,
        "contract_hash": contract.contract_hash,
        "holdout_role": config.holdout_role,
    }
    config_hash = hashlib.sha256(
        json.dumps({"config": config.to_dict(), "contract": contract.to_dict()}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    meta["config_hash"] = config_hash
    passed = not blockers
    if config.holdout_role == "historical_oos":
        verdict = "pass_independent_oos" if passed else "block_independent_oos"
    else:
        verdict = "advance_to_independent_oos" if passed else "block_discovery"
    return {
        "schema_version": TRADEFLOW_EXPERIMENT_VERSION,
        "meta": meta,
        "config": config.to_dict(),
        "decision_contract": {
            **contract.to_dict(),
            "contract_hash": contract.contract_hash,
            "frozen_before_independent_oos": contract == FROZEN_LOW_TURNOVER_CONTRACT,
            "selection_trials": 1,
            "position_rule": metadata.get(
                "position_rule",
                "enter on completed-hour z-score, hold fixed horizon, then cash cooldown; no direct flips",
            ),
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
                "start_ms": evaluation_start_ms,
                "end_exclusive_ms": evaluation_end_ms,
            },
            "source_tradeflow_path": str(Path(config.tradeflow_path).expanduser()),
            "source_tradeflow_verdict": tradeflow.get("diagnostics", {}).get("verdict"),
            "source_five_minute_row_count": len(tradeflow["five_minute_features"]),
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
            "independent_oos_status": (
                "consumed_once_pass" if passed else "consumed_once_fail"
            )
            if config.holdout_role == "historical_oos"
            else ("eligible_but_not_consumed" if passed else "not_consumed_candidate_failed"),
            "promotion_note": "This discovery kill-test cannot authorize paper/live; higher-order gates remain required.",
        },
        "ic_samples": samples,
        "hourly_features": hourly,
        "periods": periods,
    }


def write_tradeflow_experiment_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-tradeflow-experiment",
        path_key="artifact_path",
        default_filename="alpha_agent_tradeflow_experiment.json",
        explicit_path=explicit_path,
    )
