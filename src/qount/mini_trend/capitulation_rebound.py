"""Preregistered low-frequency TOP3 capitulation-rebound event research."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.research_data.market_data import Bar
from qount.mini_trend.backtest import align_bars
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.forward import TOP3
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.models import utc_now
from qount.settings import Settings


CAPITULATION_PREREG_VERSION = "mini_trend_capitulation_rebound_preregistration_v0.1"
CAPITULATION_REPORT_VERSION = "mini_trend_capitulation_rebound_price_discovery_v0.1"


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sample_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    center = _mean(values)
    return math.sqrt(sum((value - center) ** 2 for value in values) / (len(values) - 1))


def _sma(values: Sequence[float], lookback: int) -> float | None:
    if len(values) < lookback:
        return None
    return _mean(values[-lookback:])


def _atr(bars: Sequence[Bar], lookback: int) -> float | None:
    if len(bars) < lookback + 1:
        return None
    ranges: list[float] = []
    for index in range(len(bars) - lookback, len(bars)):
        bar = bars[index]
        previous_close = bars[index - 1].close
        ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )
    return _mean(ranges)


def _beta(strategy_returns: Sequence[float], benchmark_returns: Sequence[float]) -> float:
    if len(strategy_returns) != len(benchmark_returns) or len(strategy_returns) < 2:
        return 0.0
    benchmark_mean = _mean(benchmark_returns)
    strategy_mean = _mean(strategy_returns)
    variance = sum((value - benchmark_mean) ** 2 for value in benchmark_returns)
    if variance <= 0.0:
        return 0.0
    covariance = sum(
        (strategy - strategy_mean) * (benchmark - benchmark_mean)
        for strategy, benchmark in zip(strategy_returns, benchmark_returns)
    )
    return covariance / variance


def _event_curve(episodes: Sequence[Mapping[str, Any]]) -> list[float]:
    curve = [1.0]
    for episode in episodes:
        curve.append(curve[-1] * (1.0 + float(episode["net_return"])))
    return curve


@dataclass(frozen=True)
class CapitulationReboundProtocol:
    strategy: str = "MiniTrend-UM-CapitulationRebound-v0.1"
    hypothesis_family: str = "cross_market_capitulation_rebound"
    universe: tuple[str, ...] = TOP3
    market: str = "um"
    interval: str = "1d"
    signal_return_days: int = 5
    maximum_median_return: float = -0.08
    maximum_volatility_score: float = -1.50
    volatility_lookback_days: int = 20
    base_gate_lookback_days: int = 200
    require_all_symbols_negative: bool = True
    require_base_gate_off: bool = True
    entry_lag_completed_bars: int = 1
    holding_completed_bars: int = 3
    cooldown_completed_bars: int = 5
    atr_lookback_days: int = 14
    stop_atr_multiple: float = 3.0
    beta_lookback_days: int = 180
    taker_fee_bps_per_side: float = 10.0
    slippage_bps_per_side: float = 2.0
    historical_start: str = "2021-01-01"
    historical_end: str = "2026-07-17"

    @property
    def warmup_bars(self) -> int:
        return max(
            self.base_gate_lookback_days,
            self.beta_lookback_days + 1,
            self.volatility_lookback_days + self.signal_return_days,
            self.atr_lookback_days + 1,
        )

    @property
    def contract_basis(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "hypothesis_family": self.hypothesis_family,
            "economic_hypothesis": (
                "A broad volatility-normalized TOP3 selloff while the Base trend gate is off "
                "may contain a short-horizon liquidation overshoot that mean reverts."
            ),
            "data": {
                "source": "existing Binance public UM daily kline cache",
                "market": self.market,
                "interval": self.interval,
                "universe": list(self.universe),
                "completed_bars_only": True,
                "decision_uses_close_through_t": True,
                "entry_uses_next_completed_bar_open": True,
                "historical_start": self.historical_start,
                "historical_end": self.historical_end,
                "network_download_allowed": False,
            },
            "signal": {
                "return_days": self.signal_return_days,
                "maximum_median_return": self.maximum_median_return,
                "maximum_volatility_score": self.maximum_volatility_score,
                "volatility_lookback_days": self.volatility_lookback_days,
                "require_all_symbols_negative": self.require_all_symbols_negative,
                "require_base_gate_off": self.require_base_gate_off,
                "base_gate": "BTC_close_gt_SMA200 OR TOP3_above_SMA200_breadth_gte_0.5",
                "parameter_search_allowed": False,
            },
            "execution_proxy": {
                "direction": "long_cash",
                "entry_lag_completed_bars": self.entry_lag_completed_bars,
                "holding_completed_bars": self.holding_completed_bars,
                "cooldown_completed_bars": self.cooldown_completed_bars,
                "weights": "equal_weight_TOP3",
                "stop_atr_multiple": self.stop_atr_multiple,
                "atr_lookback_days": self.atr_lookback_days,
                "taker_fee_bps_per_side": self.taker_fee_bps_per_side,
                "slippage_bps_per_side": self.slippage_bps_per_side,
                "shorting_allowed": False,
                "leverage_boost_allowed": False,
                "maximum_effective_gross": 1.0,
            },
            "attribution": {
                "beta_lookback_days": self.beta_lookback_days,
                "benchmark": "BTCUSDT same event window",
                "funding_included": False,
                "standalone_executable_nav_claimed": False,
            },
        }

    @property
    def contract_hash(self) -> str:
        return canonical_hash(self.contract_basis)

    @property
    def protocol_basis(self) -> dict[str, Any]:
        return {
            "contract_hash": self.contract_hash,
            "holdout_role": "consumed_historical_discovery_pool",
            "independence_unit": "non_overlapping_signal_episode",
            "formal_trial": {
                "project_trial_number": 144,
                "number_of_prior_family_trials": 0,
                "preregistered_primary_metric": "median_net_event_return",
                "preregistered_failure_condition": (
                    "reject if fewer than 12 independent episodes, median net event return "
                    "is not positive, positive event rate is below 55%, or fewer than two "
                    "calendar segments compound positively"
                ),
                "allowed_sensitivity_range": "none in this trial",
            },
            "historical_gates": {
                "minimum_independent_episodes": 12,
                "minimum_positive_event_rate": 0.55,
                "minimum_median_net_event_return": 0.0,
                "minimum_compound_price_cost_return": 0.0,
                "minimum_positive_segments": 2,
                "minimum_median_btc_beta_residual": 0.0,
                "maximum_overlapping_episode_count": 0,
            },
            "segments": [
                {"label": "2021-2022", "start": "2021-01-01", "end": "2022-12-31"},
                {"label": "2023-2024", "start": "2023-01-01", "end": "2024-12-31"},
                {"label": "2025-2026", "start": "2025-01-01", "end": "2026-07-17"},
            ],
            "funding_complete_replay_required_before_standalone_nav": True,
            "promotion_allowed": False,
            "paper_or_live_allowed": False,
            "parameter_search_allowed": False,
        }

    @property
    def protocol_hash(self) -> str:
        return canonical_hash(self.protocol_basis)


CAPITULATION_REBOUND_PROTOCOL = CapitulationReboundProtocol()


def build_capitulation_preregistration() -> dict[str, Any]:
    protocol = CAPITULATION_REBOUND_PROTOCOL
    return {
        "schema_version": CAPITULATION_PREREG_VERSION,
        "artifact_type": "mini_trend_capitulation_rebound_preregistration",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "strategy_results_evaluated": False,
            "network_download_allowed": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "decision_contract": protocol.contract_basis | {"contract_hash": protocol.contract_hash},
        "protocol": protocol.protocol_basis | {"protocol_hash": protocol.protocol_hash},
    }


def validate_capitulation_preregistration(payload: Mapping[str, Any]) -> None:
    protocol = CAPITULATION_REBOUND_PROTOCOL
    if payload.get("schema_version") != CAPITULATION_PREREG_VERSION:
        raise ValueError("unexpected capitulation preregistration schema")
    if payload.get("decision_contract", {}).get("contract_hash") != protocol.contract_hash:
        raise ValueError("capitulation contract hash mismatch")
    if payload.get("protocol", {}).get("protocol_hash") != protocol.protocol_hash:
        raise ValueError("capitulation protocol hash mismatch")
    if payload.get("meta", {}).get("strategy_results_evaluated") is not False:
        raise ValueError("capitulation preregistration already contains results")


def _signal_state(
    aligned: Mapping[str, Sequence[Bar]], index: int, protocol: CapitulationReboundProtocol
) -> dict[str, Any]:
    returns: list[float] = []
    volatility_scores: list[float] = []
    above_sma = 0
    for symbol in protocol.universe:
        closes = [bar.close for bar in aligned[symbol][: index + 1]]
        period_return = closes[-1] / closes[-1 - protocol.signal_return_days] - 1.0
        daily_returns = [
            closes[offset] / closes[offset - 1] - 1.0
            for offset in range(
                len(closes) - protocol.volatility_lookback_days, len(closes)
            )
        ]
        volatility = _sample_std(daily_returns) * math.sqrt(protocol.signal_return_days)
        returns.append(period_return)
        volatility_scores.append(period_return / volatility if volatility > 0.0 else 0.0)
        trend = _sma(closes, protocol.base_gate_lookback_days)
        above_sma += int(trend is not None and closes[-1] > trend)

    btc_closes = [bar.close for bar in aligned["BTCUSDT"][: index + 1]]
    btc_sma = _sma(btc_closes, protocol.base_gate_lookback_days)
    breadth = above_sma / len(protocol.universe)
    base_gate_on = bool(btc_sma is not None and btc_closes[-1] > btc_sma) or breadth >= 0.5
    median_return = statistics.median(returns)
    median_score = statistics.median(volatility_scores)
    triggered = (
        median_return <= protocol.maximum_median_return
        and median_score <= protocol.maximum_volatility_score
        and (not protocol.require_all_symbols_negative or all(value < 0.0 for value in returns))
        and (not protocol.require_base_gate_off or not base_gate_on)
    )
    return {
        "triggered": triggered,
        "median_return": median_return,
        "median_volatility_score": median_score,
        "returns_by_symbol": dict(zip(protocol.universe, returns)),
        "base_gate_on": base_gate_on,
        "breadth_above_sma200": breadth,
    }


def _symbol_outcome(
    bars: Sequence[Bar], signal_index: int, protocol: CapitulationReboundProtocol
) -> dict[str, Any]:
    entry_index = signal_index + protocol.entry_lag_completed_bars
    final_index = entry_index + protocol.holding_completed_bars - 1
    entry = bars[entry_index].open
    atr = _atr(bars[: signal_index + 1], protocol.atr_lookback_days)
    if entry <= 0.0 or atr is None or atr <= 0.0:
        raise ValueError("capitulation event has invalid entry or ATR")
    stop = max(0.0, entry - protocol.stop_atr_multiple * atr)
    exit_price = bars[final_index].close
    exit_index = final_index
    stopped = False
    lows: list[float] = []
    highs: list[float] = []
    for index in range(entry_index, final_index + 1):
        bar = bars[index]
        lows.append(bar.low)
        highs.append(bar.high)
        if bar.open <= stop:
            exit_price = bar.open
            exit_index = index
            stopped = True
            break
        if bar.low <= stop:
            exit_price = stop
            exit_index = index
            stopped = True
            break

    cost = (protocol.taker_fee_bps_per_side + protocol.slippage_bps_per_side) / 10_000.0
    gross_return = exit_price / entry - 1.0
    net_return = (1.0 - cost) * (exit_price / entry) * (1.0 - cost) - 1.0
    return {
        "entry_price": entry,
        "exit_price": exit_price,
        "stop_price": stop,
        "exit_index": exit_index,
        "gross_return": gross_return,
        "net_return": net_return,
        "maximum_adverse_excursion": min(lows) / entry - 1.0,
        "maximum_favorable_excursion": max(highs) / entry - 1.0,
        "stopped": stopped,
    }


def _event_beta(
    aligned: Mapping[str, Sequence[Bar]], index: int, protocol: CapitulationReboundProtocol
) -> float:
    btc_returns: list[float] = []
    top3_returns: list[float] = []
    start = index - protocol.beta_lookback_days + 1
    for offset in range(start, index + 1):
        symbol_returns = [
            aligned[symbol][offset].close / aligned[symbol][offset - 1].close - 1.0
            for symbol in protocol.universe
        ]
        btc_returns.append(symbol_returns[0])
        top3_returns.append(_mean(symbol_returns))
    return _beta(top3_returns, btc_returns)


def _summarize(episodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(row["net_return"]) for row in episodes]
    residuals = [float(row["btc_beta_residual"]) for row in episodes]
    curve = _event_curve(episodes)
    overlapping_episode_count = sum(
        str(current["entry_date"]) <= str(previous["outcome_date"])
        for previous, current in zip(episodes, episodes[1:])
    )
    return {
        "independent_episode_count": len(episodes),
        "positive_event_rate": sum(value > 0.0 for value in returns) / len(returns) if returns else 0.0,
        "mean_net_event_return": _mean(returns),
        "median_net_event_return": statistics.median(returns) if returns else 0.0,
        "compound_price_cost_return": curve[-1] - 1.0,
        "maximum_event_nav_drawdown_pct": max_drawdown_pct(curve),
        "median_btc_beta_residual": statistics.median(residuals) if residuals else 0.0,
        "overlapping_episode_count": overlapping_episode_count,
        "stopped_symbol_count": sum(
            int(symbol_row["stopped"])
            for row in episodes
            for symbol_row in row["symbols"].values()
        ),
    }


def build_capitulation_price_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]], preregistration: Mapping[str, Any]
) -> dict[str, Any]:
    validate_capitulation_preregistration(preregistration)
    protocol = CAPITULATION_REBOUND_PROTOCOL
    aligned = align_bars(bars_by_symbol, protocol.universe)
    dates = [bar.date for bar in aligned["BTCUSDT"]]
    episodes: list[dict[str, Any]] = []
    next_eligible_index = protocol.warmup_bars
    raw_signal_count = 0
    for index in range(protocol.warmup_bars, len(dates) - protocol.holding_completed_bars):
        date = dates[index]
        if date < protocol.historical_start or date > protocol.historical_end:
            continue
        signal = _signal_state(aligned, index, protocol)
        if not signal["triggered"]:
            continue
        raw_signal_count += 1
        if index < next_eligible_index:
            continue
        symbols = {
            symbol: _symbol_outcome(aligned[symbol], index, protocol)
            for symbol in protocol.universe
        }
        net_return = _mean([row["net_return"] for row in symbols.values()])
        gross_return = _mean([row["gross_return"] for row in symbols.values()])
        entry_index = index + protocol.entry_lag_completed_bars
        final_index = entry_index + protocol.holding_completed_bars - 1
        btc_entry = aligned["BTCUSDT"][entry_index].open
        btc_exit = aligned["BTCUSDT"][final_index].close
        btc_return = btc_exit / btc_entry - 1.0
        beta = _event_beta(aligned, index, protocol)
        core = {
            "signal_date": date,
            "entry_date": dates[entry_index],
            "outcome_date": dates[final_index],
            "signal": signal,
            "symbols": symbols,
            "gross_return": gross_return,
            "net_return": net_return,
            "btc_benchmark_return": btc_return,
            "ex_ante_btc_beta": beta,
            "btc_beta_residual": net_return - beta * btc_return,
        }
        episodes.append(core | {"event_id": canonical_hash(core)})
        next_eligible_index = final_index + protocol.cooldown_completed_bars + 1

    summary = _summarize(episodes)
    segments = []
    for segment in protocol.protocol_basis["segments"]:
        rows = [
            row
            for row in episodes
            if segment["start"] <= row["signal_date"] <= segment["end"]
        ]
        segments.append(segment | _summarize(rows))

    gates = protocol.protocol_basis["historical_gates"]
    gate_results = {
        "minimum_independent_episodes": summary["independent_episode_count"]
        >= gates["minimum_independent_episodes"],
        "minimum_positive_event_rate": summary["positive_event_rate"]
        >= gates["minimum_positive_event_rate"],
        "minimum_median_net_event_return": summary["median_net_event_return"]
        > gates["minimum_median_net_event_return"],
        "minimum_compound_price_cost_return": summary["compound_price_cost_return"]
        > gates["minimum_compound_price_cost_return"],
        "minimum_positive_segments": sum(
            row["compound_price_cost_return"] > 0.0 for row in segments
        )
        >= gates["minimum_positive_segments"],
        "minimum_median_btc_beta_residual": summary["median_btc_beta_residual"]
        > gates["minimum_median_btc_beta_residual"],
        "maximum_overlapping_episode_count": summary["overlapping_episode_count"]
        <= gates["maximum_overlapping_episode_count"],
    }
    price_signal_retained = all(gate_results.values())
    data_basis = {
        symbol: [
            [bar.date, bar.open, bar.high, bar.low, bar.close]
            for bar in aligned[symbol]
            if protocol.historical_start <= bar.date <= protocol.historical_end
        ]
        for symbol in protocol.universe
    }
    return {
        "schema_version": CAPITULATION_REPORT_VERSION,
        "artifact_type": "mini_trend_capitulation_rebound_price_discovery",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "strategy_results_evaluated": True,
            "network_download_used": False,
            "funding_included": False,
            "standalone_executable_nav_evaluated": False,
            "orders_allowed": False,
            "paper_or_live_allowed": False,
        },
        "contract_hash": protocol.contract_hash,
        "protocol_hash": protocol.protocol_hash,
        "data": {
            "first_common_date": dates[0],
            "last_common_date": dates[-1],
            "common_bar_count": len(dates),
            "data_hash": canonical_hash(data_basis),
            "raw_signal_count": raw_signal_count,
        },
        "summary": summary,
        "segments": segments,
        "episodes": episodes,
        "diagnostics": {
            "gates": gate_results,
            "price_signal_retained": price_signal_retained,
            "funding_complete_replay_required": True,
            "standalone_executable_nav_blockers": [
                "funding_cost_not_loaded",
                "exchange_minimum_notional_not_audited",
                "portfolio_allocator_shadow_replay_not_run",
            ],
            "verdict": (
                "retain_price_signal_for_funding_complete_replay"
                if price_signal_retained
                else "reject_historical_capitulation_rebound"
            ),
        },
    }


def write_capitulation_preregistration_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-capitulation-rebound-preregistration",
        path_key="artifact_path",
        default_filename="mini_trend_capitulation_rebound_preregistration.json",
        explicit_path=explicit_path,
    )


def write_capitulation_report_artifact(
    settings: Settings, payload: dict[str, Any], *, explicit_path: str | None = None
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-capitulation-rebound-price-discovery",
        path_key="artifact_path",
        default_filename="mini_trend_capitulation_rebound_price_discovery.json",
        explicit_path=explicit_path,
    )
