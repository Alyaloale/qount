from __future__ import annotations

import datetime as dt
import hashlib
import json
import bisect
import os
import urllib.parse
import urllib.request
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar
from qount.grid.data import Funding
from qount.grid.data import load_funding
from qount.grid.data import load_klines
from qount.settings import Settings

from .exchange_rules import SymbolRules
from .exchange_rules import evaluate_period_filter_coverage
from .exchange_rules import rules_from_exchange_info


FEATURE_EXPERIMENT_VERSION = "alpha_agent_feature_experiment_v0.2"

DERIVATIVE_FEATURE_FAMILIES = {"oi_delta", "oi_value_delta", "taker_ratio", "taker_imbalance"}
KLINE_MICROSTRUCTURE_FEATURE_FAMILIES = {
    "kline_taker_imbalance",
    "kline_taker_pressure_change",
    "kline_quote_volume_z",
    "kline_realized_vol_change",
}

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "8h": 8 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


@dataclass(frozen=True)
class FeatureExperimentConfig:
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")
    strategy_symbol: str = "ETHUSDT"
    interval: str = "1h"
    start_month: str = "2024-01"
    end_month: str = "2024-03"
    market: str = "um"
    kline_source: str = "public_dump"
    horizon_bars: int = 6
    train_fraction: float = 0.60
    lookbacks: tuple[int, ...] = (6, 12, 24, 48)
    feature_families: tuple[str, ...] = ("momentum", "reversal", "relative_momentum", "vol_adjusted_momentum")
    thresholds: tuple[float, ...] = (0.0, 0.0025, 0.005)
    modes: tuple[str, ...] = ("long_short", "long_cash", "short_cash")
    polarities: tuple[int, ...] = (1,)
    selection_metric: str = "net_residual_return"
    beta_lookback_bars: int = 24
    fee_pct: float = 0.0005
    slippage_pct: float = 0.0002
    account_equity_usdt: float = 400.0
    target_notional_fraction: float = 1.0
    leverage: float = 1.0
    include_funding: bool = True
    output_granularity: str = "month"
    cache_dir: str = "state/alpha_agents/binance_klines"
    funding_cache_dir: str = "state/alpha_agents/binance_funding"
    derivatives_state_path: str | None = None
    min_feature_coverage: float = 0.05

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateSpec:
    feature_family: str
    lookback: int
    threshold: float
    mode: str
    polarity: int = 1

    @property
    def candidate_id(self) -> str:
        suffix = "" if self.polarity == 1 else "_inv"
        return f"{self.feature_family}_lb{self.lookback}_thr{self.threshold:g}_{self.mode}{suffix}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "feature_family": self.feature_family,
            "lookback": self.lookback,
            "threshold": self.threshold,
            "mode": self.mode,
            "polarity": self.polarity,
        }


def _parse_month(raw: str) -> tuple[int, int]:
    year, month = raw.split("-", 1)
    return int(year), int(month)


def _interval_ms(interval: str) -> int:
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval for feature experiment: {interval}")
    return INTERVAL_MS[interval]


def _pct_return(prev_close: float, close: float) -> float:
    if prev_close <= 0:
        return 0.0
    return (close / prev_close - 1.0) * 100.0


def _align_bars(bars_by_symbol: dict[str, list[Bar]], symbols: tuple[str, ...]) -> list[tuple[int, dict[str, Bar]]]:
    maps = {symbol: {bar.ts_ms: bar for bar in bars_by_symbol[symbol]} for symbol in symbols}
    common = set(maps[symbols[0]])
    for symbol in symbols[1:]:
        common &= set(maps[symbol])
    return [(ts, {symbol: maps[symbol][ts] for symbol in symbols}) for ts in sorted(common)]


def _compound_pct(values: list[float]) -> float:
    total = 1.0
    for value in values:
        total *= 1.0 + value / 100.0
    return (total - 1.0) * 100.0


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


def _beta_residual(strategy: list[float], btc: list[float]) -> dict[str, float]:
    btc_var = _variance(btc)
    beta = _covariance(strategy, btc) / btc_var if btc_var > 0 else 0.0
    residual = sum(s - beta * b for s, b in zip(strategy, btc))
    return {"beta_to_btc": beta, "net_residual_return_pct": residual}


def _std(values: list[float]) -> float:
    return _variance(values) ** 0.5


def _correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    denominator = _std(left) * _std(right)
    return _covariance(left, right) / denominator if denominator > 0 else 0.0


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
            end += 1
        average_rank = (cursor + end - 1) / 2.0 + 1.0
        for ordered_index in ordered[cursor:end]:
            ranks[ordered_index] = average_rank
        cursor = end
    return ranks


def _information_coefficient(feature_values: list[float], labels: list[float]) -> dict[str, float | int]:
    if len(feature_values) != len(labels) or len(feature_values) < 2:
        return {"sample_count": len(feature_values), "pearson_ic": 0.0, "rank_ic": 0.0}
    return {
        "sample_count": len(feature_values),
        "pearson_ic": _correlation(feature_values, labels),
        "rank_ic": _correlation(_ranks(feature_values), _ranks(labels)),
    }


def _load_derivatives_state(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    by_symbol: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in payload.get("open_interest_hist", []):
        if isinstance(row, dict):
            by_symbol.setdefault(str(row.get("symbol", "")).upper(), {}).setdefault("open_interest_hist", []).append(row)
    for row in payload.get("taker_long_short", []):
        if isinstance(row, dict):
            by_symbol.setdefault(str(row.get("symbol", "")).upper(), {}).setdefault("taker_long_short", []).append(row)
    for rows in by_symbol.values():
        for key in ("open_interest_hist", "taker_long_short"):
            rows.setdefault(key, []).sort(key=lambda item: int(item.get("ts_ms", 0)))
    return {
        "path": str(Path(path).expanduser()),
        "meta": payload.get("meta", {}),
        "diagnostics": payload.get("diagnostics", {}),
        "window": payload.get("window", {}),
        "by_symbol": by_symbol,
    }


def _month_window_ms(start: tuple[int, int], end: tuple[int, int]) -> tuple[int, int]:
    start_dt = dt.datetime(start[0], start[1], 1, tzinfo=dt.UTC)
    year, month = end
    if month == 12:
        next_month = dt.datetime(year + 1, 1, 1, tzinfo=dt.UTC)
    else:
        next_month = dt.datetime(year, month + 1, 1, tzinfo=dt.UTC)
    return int(start_dt.timestamp() * 1000), int(next_month.timestamp() * 1000) - 1


def _default_fetch(url: str) -> bytes:  # pragma: no cover - network
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read()


def _cached_fetch(url: str, *, cache_dir: str, fetch=None) -> bytes:
    os.makedirs(cache_dir, exist_ok=True)
    name = "rest-klines-" + hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json"
    path = Path(cache_dir) / name
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    last_error: OSError | None = None
    for _attempt in range(2):
        try:
            blob = (fetch or _default_fetch)(url)
            break
        except OSError as exc:
            last_error = exc
    else:
        host = urllib.parse.urlparse(url).netloc
        raise RuntimeError(f"failed to fetch REST klines from {host} after 2 attempts") from last_error
    path.write_bytes(blob)
    return blob


def _rest_kline_url(symbol: str, interval: str, start_ms: int, end_ms: int, *, limit: int = 1500) -> str:
    params = urllib.parse.urlencode(
        {"symbol": symbol, "interval": interval, "startTime": start_ms, "endTime": end_ms, "limit": limit}
    )
    return f"https://fapi.binance.com/fapi/v1/klines?{params}"


def _parse_rest_klines(payload: Any) -> list[Bar]:
    if not isinstance(payload, list):
        raise ValueError("REST klines response must be a list")
    bars: list[Bar] = []
    for row in payload:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            bars.append(
                Bar(
                    ts_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    quote_volume=_as_float(row[7], default=0.0) if len(row) > 7 else None,
                    trade_count=int(row[8]) if len(row) > 8 else None,
                    taker_buy_base_volume=_as_float(row[9], default=0.0) if len(row) > 9 else None,
                    taker_buy_quote_volume=_as_float(row[10], default=0.0) if len(row) > 10 else None,
                )
            )
        except (TypeError, ValueError):
            continue
    return bars


def _load_rest_klines(
    symbol: str,
    interval: str,
    *,
    start_ms: int,
    end_ms: int,
    cache_dir: str,
    fetch=None,
) -> list[Bar]:
    interval_ms = _interval_ms(interval)
    seen: dict[int, Bar] = {}
    current = start_ms
    while current <= end_ms:
        chunk_end = min(end_ms, current + interval_ms * 1499)
        url = _rest_kline_url(symbol, interval, current, chunk_end)
        rows = _parse_rest_klines(json.loads(_cached_fetch(url, cache_dir=cache_dir, fetch=fetch).decode("utf-8")))
        if not rows:
            break
        for bar in rows:
            seen[bar.ts_ms] = bar
        next_ts = rows[-1].ts_ms + interval_ms
        if next_ts <= current:
            break
        current = next_ts
    return [seen[ts] for ts in sorted(seen)]


def _derivatives_window_ms(derivatives_state: dict[str, Any] | None) -> tuple[int, int] | None:
    if derivatives_state is None:
        return None
    window = derivatives_state.get("window", {})
    try:
        start_ms = int(window.get("start_ms"))
        end_ms = int(window.get("end_ms"))
    except (TypeError, ValueError):
        return None
    if start_ms <= 0 or end_ms < start_ms:
        return None
    return start_ms, end_ms


def _load_bars_by_symbol(
    config: FeatureExperimentConfig,
    *,
    start: tuple[int, int],
    end: tuple[int, int],
    derivatives_state: dict[str, Any] | None,
    fetch=None,
) -> tuple[dict[str, list[Bar]], dict[str, Any]]:
    if config.kline_source == "public_dump":
        return (
            {
                symbol: load_klines(
                    symbol,
                    config.interval,
                    start=start,
                    end=end,
                    market=config.market,
                    cache_dir=config.cache_dir,
                    fetch=fetch,
                    skip_missing=True,
                )
                for symbol in config.symbols
            },
            {"source": "public_dump", "start_month": config.start_month, "end_month": config.end_month},
        )
    if config.kline_source == "rest":
        if config.market != "um":
            raise ValueError("REST kline source currently supports Binance USD-M futures market only")
        window = _derivatives_window_ms(derivatives_state) or _month_window_ms(start, end)
        start_ms, end_ms = window
        return (
            {
                symbol: _load_rest_klines(
                    symbol,
                    config.interval,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    cache_dir=config.cache_dir,
                    fetch=fetch,
                )
                for symbol in config.symbols
            },
            {"source": "rest", "start_ms": start_ms, "end_ms": end_ms},
        )
    raise ValueError("kline_source must be 'public_dump' or 'rest'")


def _asof_row(rows: list[dict[str, Any]], ts_ms: int) -> tuple[int, dict[str, Any] | None]:
    timestamps = [int(row.get("ts_ms", 0)) for row in rows]
    index = bisect.bisect_right(timestamps, ts_ms) - 1
    if index < 0:
        return -1, None
    return index, rows[index]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _derivative_feature_value(
    family: str,
    *,
    symbol: str,
    decision_ts_ms: int,
    lookback: int,
    derivatives_state: dict[str, Any] | None,
) -> float | None:
    if derivatives_state is None:
        return None
    rows_by_type = derivatives_state.get("by_symbol", {}).get(symbol, {})
    if family in {"oi_delta", "oi_value_delta"}:
        rows = rows_by_type.get("open_interest_hist", [])
        index, current = _asof_row(rows, decision_ts_ms)
        if current is None or index - lookback < 0:
            return None
        previous = rows[index - lookback]
        current_segment = current.get("segment_id")
        previous_segment = previous.get("segment_id")
        if current_segment is not None and previous_segment is not None and current_segment != previous_segment:
            return None
        key = "sum_open_interest" if family == "oi_delta" else "sum_open_interest_value"
        current_value = _as_float(current.get(key))
        previous_value = _as_float(previous.get(key))
        if previous_value == 0:
            return None
        return current_value / previous_value - 1.0
    if family in {"taker_ratio", "taker_imbalance"}:
        rows = rows_by_type.get("taker_long_short", [])
        _index, current = _asof_row(rows, decision_ts_ms)
        if current is None:
            return None
        if family == "taker_ratio":
            return _as_float(current.get("buy_sell_ratio")) - 1.0
        buy = _as_float(current.get("buy_vol"))
        sell = _as_float(current.get("sell_vol"))
        total = buy + sell
        if total <= 0:
            return None
        return (buy - sell) / total
    return None


def _taker_imbalance(bars: list[Bar]) -> float | None:
    if not bars or any(bar.taker_buy_base_volume is None for bar in bars):
        return None
    total_volume = sum(bar.volume for bar in bars)
    if total_volume <= 0:
        return None
    taker_buy_volume = sum(float(bar.taker_buy_base_volume) for bar in bars)
    return 2.0 * taker_buy_volume / total_volume - 1.0


def _quote_volume(bar: Bar) -> float:
    if bar.quote_volume is not None:
        return float(bar.quote_volume)
    return bar.volume * bar.close


def _kline_microstructure_feature_value(
    family: str,
    *,
    index: int,
    lookback: int,
    strategy_bars: list[Bar],
    strategy_closes: list[float],
) -> float | None:
    if lookback <= 0:
        return None
    if family == "kline_taker_imbalance":
        start = index - lookback + 1
        if start < 0:
            return None
        return _taker_imbalance(strategy_bars[start : index + 1])
    if family == "kline_taker_pressure_change":
        current_start = index - lookback + 1
        previous_start = current_start - lookback
        if previous_start < 0:
            return None
        current = _taker_imbalance(strategy_bars[current_start : index + 1])
        previous = _taker_imbalance(strategy_bars[previous_start:current_start])
        if current is None or previous is None:
            return None
        return current - previous
    if family == "kline_quote_volume_z":
        history_start = index - lookback
        if history_start < 0:
            return None
        history = [_quote_volume(bar) for bar in strategy_bars[history_start:index]]
        scale = _std(history)
        return (_quote_volume(strategy_bars[index]) - _mean(history)) / scale if scale > 0 else 0.0
    if family == "kline_realized_vol_change":
        previous_start = index - 2 * lookback
        current_start = index - lookback
        if previous_start < 0:
            return None
        previous_returns = [
            strategy_closes[i] / strategy_closes[i - 1] - 1.0
            for i in range(previous_start + 1, current_start + 1)
            if strategy_closes[i - 1] > 0
        ]
        current_returns = [
            strategy_closes[i] / strategy_closes[i - 1] - 1.0
            for i in range(current_start + 1, index + 1)
            if strategy_closes[i - 1] > 0
        ]
        if len(previous_returns) != lookback or len(current_returns) != lookback:
            return None
        return _std(current_returns) - _std(previous_returns)
    return None


def _kline_field_coverage(bars: list[Bar]) -> dict[str, float]:
    count = len(bars)
    if count == 0:
        return {
            "quote_volume": 0.0,
            "trade_count": 0.0,
            "taker_buy_base_volume": 0.0,
            "taker_buy_quote_volume": 0.0,
        }
    return {
        field: sum(getattr(bar, field) is not None for bar in bars) / count
        for field in (
            "quote_volume",
            "trade_count",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
        )
    }


def _feature_value(
    family: str,
    *,
    index: int,
    lookback: int,
    symbol: str,
    decision_ts_ms: int,
    timestamps: list[int],
    interval_ms: int,
    strategy_bars: list[Bar],
    strategy_closes: list[float],
    btc_closes: list[float],
    derivatives_state: dict[str, Any] | None,
) -> float | None:
    derivative_value = _derivative_feature_value(
        family,
        symbol=symbol,
        decision_ts_ms=decision_ts_ms,
        lookback=lookback,
        derivatives_state=derivatives_state,
    )
    if derivative_value is not None or family in DERIVATIVE_FEATURE_FAMILIES:
        return derivative_value
    history_multiplier = 2 if family in {"kline_taker_pressure_change", "kline_realized_vol_change"} else 1
    history_start = index - lookback * history_multiplier
    if history_start < 0:
        return None
    if any(
        timestamps[position] - timestamps[position - 1] != interval_ms
        for position in range(history_start + 1, index + 1)
    ):
        return None
    if family in KLINE_MICROSTRUCTURE_FEATURE_FAMILIES:
        return _kline_microstructure_feature_value(
            family,
            index=index,
            lookback=lookback,
            strategy_bars=strategy_bars,
            strategy_closes=strategy_closes,
        )
    if index - lookback < 0:
        return None
    start = strategy_closes[index - lookback]
    end = strategy_closes[index]
    btc_start = btc_closes[index - lookback]
    btc_end = btc_closes[index]
    if start <= 0 or btc_start <= 0:
        return None
    momentum = end / start - 1.0
    if family == "momentum":
        return momentum
    if family == "reversal":
        return -momentum
    if family == "relative_momentum":
        return momentum - (btc_end / btc_start - 1.0)
    if family == "vol_adjusted_momentum":
        returns = [
            strategy_closes[i] / strategy_closes[i - 1] - 1.0
            for i in range(index - lookback + 1, index + 1)
            if strategy_closes[i - 1] > 0
        ]
        vol = _std(returns)
        return momentum / vol if vol > 0 else 0.0
    raise ValueError(f"unknown feature family: {family}")


def _position_from_feature(value: float | None, spec: CandidateSpec) -> float:
    if value is None:
        return 0.0
    value *= spec.polarity
    threshold = abs(spec.threshold)
    if spec.mode == "long_short":
        if value > threshold:
            return 1.0
        if value < -threshold:
            return -1.0
        return 0.0
    if spec.mode == "long_cash":
        return 1.0 if value > threshold else 0.0
    if spec.mode == "short_cash":
        return -1.0 if value < -threshold else 0.0
    raise ValueError(f"unknown mode: {spec.mode}")


def _funding_by_bar(
    funding: list[Funding],
    *,
    previous_ts: int,
    ts: int,
    position: float,
) -> tuple[float, int]:
    total = 0.0
    count = 0
    for row in funding:
        if previous_ts < row.ts_ms <= ts:
            total += -position * row.rate * 100.0
            count += 1
    return total, count


def _candidate_periods(
    aligned: list[tuple[int, dict[str, Bar]]],
    config: FeatureExperimentConfig,
    spec: CandidateSpec,
    funding: list[Funding],
    derivatives_state: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    strategy_bars = [row[config.strategy_symbol] for _ts, row in aligned]
    timestamps = [ts for ts, _row in aligned]
    strategy_closes = [row[config.strategy_symbol].close for _ts, row in aligned]
    btc_closes = [row["BTCUSDT"].close for _ts, row in aligned]
    previous_position = 0.0
    current_position = 0.0
    total_turnover = 0.0
    total_funding_return_pct = 0.0
    funding_settlement_count = 0
    feature_decision_count = 0
    feature_available_count = 0
    per_turnover_cost_pct = (config.fee_pct + config.slippage_pct) * 100.0
    interval_ms = _interval_ms(config.interval)
    periods: list[dict[str, Any]] = []

    for index in range(1, len(aligned)):
        ts, row = aligned[index]
        prev_ts, prev_row = aligned[index - 1]
        if ts - prev_ts != interval_ms:
            current_position = 0.0
            previous_position = 0.0
            continue
        if (index - 1) % config.horizon_bars == 0:
            feature_decision_count += 1
            decision_ts = prev_ts + interval_ms
            feature = _feature_value(
                spec.feature_family,
                index=index - 1,
                lookback=spec.lookback,
                symbol=config.strategy_symbol,
                decision_ts_ms=decision_ts,
                timestamps=timestamps,
                interval_ms=interval_ms,
                strategy_bars=strategy_bars,
                strategy_closes=strategy_closes,
                btc_closes=btc_closes,
                derivatives_state=derivatives_state,
            )
            if feature is not None:
                feature_available_count += 1
            current_position = _position_from_feature(feature, spec)
        else:
            feature = None

        symbol_returns = {
            symbol: _pct_return(prev_row[symbol].close, row[symbol].close)
            for symbol in config.symbols
        }
        turnover = abs(current_position - previous_position)
        cost_pct = turnover * per_turnover_cost_pct
        funding_return_pct, funding_count = _funding_by_bar(
            funding,
            previous_ts=prev_ts,
            ts=ts,
            position=current_position,
        )
        strategy_gross = current_position * symbol_returns[config.strategy_symbol]
        strategy_net = strategy_gross - cost_pct + funding_return_pct
        total_turnover += turnover
        total_funding_return_pct += funding_return_pct
        funding_settlement_count += funding_count
        previous_position = current_position
        periods.append(
            {
                "ts": str(ts),
                "strategy_return_pct": strategy_net,
                "strategy_gross_return_pct": strategy_gross,
                "strategy_position": current_position,
                "strategy_turnover": turnover,
                "strategy_cost_pct": cost_pct,
                "strategy_funding_return_pct": funding_return_pct,
                "strategy_feature_value": feature,
                "strategy_close": row[config.strategy_symbol].close,
                "btc_return_pct": symbol_returns["BTCUSDT"],
                "top3_equal_weight_return_pct": sum(symbol_returns.values()) / len(symbol_returns),
                "current_live_baseline_return_pct": 0.0,
                "cash_return_pct": 0.0,
            }
        )

    diagnostics = {
        "total_turnover": total_turnover,
        "per_turnover_cost_pct": per_turnover_cost_pct,
        "funding_settlement_count": funding_settlement_count,
        "total_funding_return_pct": total_funding_return_pct,
        "derivatives_state_used": derivatives_state is not None,
        "feature_decision_count": feature_decision_count,
        "feature_available_count": feature_available_count,
        "feature_coverage": feature_available_count / feature_decision_count if feature_decision_count else 0.0,
    }
    return periods, diagnostics


def _rolling_betas(
    strategy_closes: list[float],
    btc_closes: list[float],
    timestamps: list[int],
    *,
    interval_ms: int,
    lookback: int,
) -> list[float | None]:
    count = len(strategy_closes)
    prefix_n = [0] * (count + 1)
    prefix_strategy = [0.0] * (count + 1)
    prefix_btc = [0.0] * (count + 1)
    prefix_cross = [0.0] * (count + 1)
    prefix_btc_sq = [0.0] * (count + 1)
    segment_return_start = [1] * count
    current_segment_return_start = 1
    for return_index in range(1, count):
        strategy_previous = strategy_closes[return_index - 1]
        btc_previous = btc_closes[return_index - 1]
        contiguous = timestamps[return_index] - timestamps[return_index - 1] == interval_ms
        if not contiguous:
            current_segment_return_start = return_index + 1
        segment_return_start[return_index] = current_segment_return_start
        valid = (
            strategy_previous > 0
            and btc_previous > 0
            and contiguous
        )
        strategy_return = strategy_closes[return_index] / strategy_previous - 1.0 if valid else 0.0
        btc_return = btc_closes[return_index] / btc_previous - 1.0 if valid else 0.0
        prefix_n[return_index + 1] = prefix_n[return_index] + int(valid)
        prefix_strategy[return_index + 1] = prefix_strategy[return_index] + strategy_return
        prefix_btc[return_index + 1] = prefix_btc[return_index] + btc_return
        prefix_cross[return_index + 1] = prefix_cross[return_index] + strategy_return * btc_return
        prefix_btc_sq[return_index + 1] = prefix_btc_sq[return_index] + btc_return * btc_return

    minimum_observations = min(lookback, 20)
    betas: list[float | None] = [None] * count
    for index in range(1, count):
        start = max(1, index - lookback + 1, segment_return_start[index])
        end = index + 1
        observations = prefix_n[end] - prefix_n[start]
        if observations < minimum_observations:
            continue
        strategy_sum = prefix_strategy[end] - prefix_strategy[start]
        btc_sum = prefix_btc[end] - prefix_btc[start]
        cross_sum = prefix_cross[end] - prefix_cross[start]
        btc_sq_sum = prefix_btc_sq[end] - prefix_btc_sq[start]
        covariance_numerator = cross_sum - strategy_sum * btc_sum / observations
        variance_numerator = btc_sq_sum - btc_sum * btc_sum / observations
        betas[index] = covariance_numerator / variance_numerator if variance_numerator > 0 else 0.0
    return betas


def _forward_residual_labels(
    aligned: list[tuple[int, dict[str, Bar]]],
    config: FeatureExperimentConfig,
) -> dict[int, dict[str, float]]:
    strategy_closes = [row[config.strategy_symbol].close for _ts, row in aligned]
    btc_closes = [row["BTCUSDT"].close for _ts, row in aligned]
    timestamps = [ts for ts, _row in aligned]
    interval_ms = _interval_ms(config.interval)
    betas = _rolling_betas(
        strategy_closes,
        btc_closes,
        timestamps,
        interval_ms=interval_ms,
        lookback=config.beta_lookback_bars,
    )
    labels: dict[int, dict[str, float]] = {}
    last_decision_index = len(aligned) - config.horizon_bars - 1
    for decision_index in range(0, last_decision_index + 1, config.horizon_bars):
        beta = betas[decision_index]
        if beta is None:
            continue
        end_index = decision_index + config.horizon_bars
        if timestamps[end_index] - timestamps[decision_index] != config.horizon_bars * interval_ms:
            continue
        strategy_start = strategy_closes[decision_index]
        btc_start = btc_closes[decision_index]
        if strategy_start <= 0 or btc_start <= 0:
            continue
        strategy_forward = (strategy_closes[end_index] / strategy_start - 1.0) * 100.0
        btc_forward = (btc_closes[end_index] / btc_start - 1.0) * 100.0
        labels[decision_index] = {
            "residual_forward_return_pct": strategy_forward - beta * btc_forward,
            "beta_to_btc": beta,
        }
    return labels


def _candidate_ic_samples(
    aligned: list[tuple[int, dict[str, Bar]]],
    config: FeatureExperimentConfig,
    spec: CandidateSpec,
    derivatives_state: dict[str, Any] | None,
    residual_labels: dict[int, dict[str, float]],
) -> list[dict[str, float | int]]:
    strategy_bars = [row[config.strategy_symbol] for _ts, row in aligned]
    strategy_closes = [bar.close for bar in strategy_bars]
    btc_closes = [row["BTCUSDT"].close for _ts, row in aligned]
    timestamps = [ts for ts, _row in aligned]
    interval_ms = _interval_ms(config.interval)
    samples: list[dict[str, float | int]] = []
    for decision_index, label in residual_labels.items():
        decision_ts = aligned[decision_index][0] + interval_ms
        feature = _feature_value(
            spec.feature_family,
            index=decision_index,
            lookback=spec.lookback,
            symbol=config.strategy_symbol,
            decision_ts_ms=decision_ts,
            timestamps=timestamps,
            interval_ms=interval_ms,
            strategy_bars=strategy_bars,
            strategy_closes=strategy_closes,
            btc_closes=btc_closes,
            derivatives_state=derivatives_state,
        )
        if feature is None:
            continue
        samples.append(
            {
                "decision_index": decision_index,
                "feature_value": feature * spec.polarity,
                "residual_forward_return_pct": label["residual_forward_return_pct"],
                "beta_to_btc": label["beta_to_btc"],
            }
        )
    return samples


def _score_ic_samples(samples: list[dict[str, float | int]]) -> dict[str, float | int]:
    return _information_coefficient(
        [float(sample["feature_value"]) for sample in samples],
        [float(sample["residual_forward_return_pct"]) for sample in samples],
    )


def _score_periods(periods: list[dict[str, Any]]) -> dict[str, float]:
    strategy = [float(row["strategy_return_pct"]) for row in periods]
    btc = [float(row["btc_return_pct"]) for row in periods]
    top3 = [float(row["top3_equal_weight_return_pct"]) for row in periods]
    residual = _beta_residual(strategy, btc)
    return {
        "strategy_total_return_pct": _compound_pct(strategy),
        "btc_total_return_pct": _compound_pct(btc),
        "top3_equal_weight_total_return_pct": _compound_pct(top3),
        "beta_to_btc": residual["beta_to_btc"],
        "net_residual_return_pct": residual["net_residual_return_pct"],
    }


def _period_key(ts_ms: str, granularity: str) -> str:
    stamp = int(ts_ms)
    fmt = "%Y-%m" if granularity == "month" else "%Y-%m-%d"
    return dt.datetime.fromtimestamp(stamp / 1000, dt.UTC).strftime(fmt)


def _aggregate_periods(periods: list[dict[str, Any]], *, granularity: str) -> list[dict[str, Any]]:
    if granularity not in {"day", "month"}:
        raise ValueError("aggregate granularity must be 'day' or 'month'")
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in periods:
        buckets.setdefault(_period_key(str(row["ts"]), granularity), []).append(row)
    result: list[dict[str, Any]] = []
    for period in sorted(buckets):
        rows = buckets[period]
        result.append(
            {
                "ts": period,
                "strategy_return_pct": _compound_pct([float(row["strategy_return_pct"]) for row in rows]),
                "strategy_gross_return_pct": _compound_pct(
                    [float(row["strategy_gross_return_pct"]) for row in rows]
                ),
                "strategy_turnover": sum(float(row["strategy_turnover"]) for row in rows),
                "strategy_cost_pct": sum(float(row["strategy_cost_pct"]) for row in rows),
                "strategy_funding_return_pct": sum(float(row["strategy_funding_return_pct"]) for row in rows),
                "btc_return_pct": _compound_pct([float(row["btc_return_pct"]) for row in rows]),
                "top3_equal_weight_return_pct": _compound_pct(
                    [float(row["top3_equal_weight_return_pct"]) for row in rows]
                ),
                "current_live_baseline_return_pct": 0.0,
                "cash_return_pct": 0.0,
                "bar_count": len(rows),
            }
        )
    return result


def _aggregate_monthly(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _aggregate_periods(periods, granularity="month")


def _aggregate_daily(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _aggregate_periods(periods, granularity="day")


def _largest_contributor_removed_return(periods: list[dict[str, Any]]) -> float:
    if len(periods) <= 1:
        return 0.0
    strategy_returns = [float(row["strategy_return_pct"]) for row in periods]
    largest_index = max(range(len(strategy_returns)), key=lambda i: strategy_returns[i])
    reduced = [value for i, value in enumerate(strategy_returns) if i != largest_index]
    return _compound_pct(reduced)


def build_feature_experiment_dataset(
    config: FeatureExperimentConfig,
    *,
    fetch=None,
    exchange_info: dict[str, Any] | None = None,
    symbol_rules: dict[str, SymbolRules] | None = None,
    include_validation_matrix: bool = False,
) -> dict[str, Any]:
    if "BTCUSDT" not in config.symbols:
        raise ValueError("symbols must include BTCUSDT for beta attribution")
    if config.strategy_symbol not in config.symbols:
        raise ValueError("strategy_symbol must be included in symbols")
    if config.horizon_bars <= 0:
        raise ValueError("horizon_bars must be positive")
    if not 0.0 < config.train_fraction < 1.0:
        raise ValueError("train_fraction must be in (0, 1)")
    if config.output_granularity not in {"bar", "month"}:
        raise ValueError("output_granularity must be 'bar' or 'month'")
    if not 0.0 <= config.min_feature_coverage <= 1.0:
        raise ValueError("min_feature_coverage must be in [0, 1]")
    if config.kline_source not in {"public_dump", "rest"}:
        raise ValueError("kline_source must be 'public_dump' or 'rest'")
    if not config.polarities or any(polarity not in {-1, 1} for polarity in config.polarities):
        raise ValueError("polarities must contain only -1 or 1")
    if config.selection_metric not in {"net_residual_return", "rank_ic"}:
        raise ValueError("selection_metric must be 'net_residual_return' or 'rank_ic'")
    if config.beta_lookback_bars <= 1:
        raise ValueError("beta_lookback_bars must be greater than 1")
    _interval_ms(config.interval)

    start = _parse_month(config.start_month)
    end = _parse_month(config.end_month)
    derivatives_state = _load_derivatives_state(config.derivatives_state_path)
    bars_by_symbol, kline_diagnostics = _load_bars_by_symbol(
        config,
        start=start,
        end=end,
        derivatives_state=derivatives_state,
        fetch=fetch,
    )
    aligned = _align_bars(bars_by_symbol, config.symbols)
    history_required = max(config.lookbacks)
    if config.selection_metric == "rank_ic":
        history_required = max(history_required, config.beta_lookback_bars)
    min_required = history_required + config.horizon_bars + 4
    if len(aligned) < min_required:
        raise ValueError("not enough aligned bars for feature experiment")

    funding: list[Funding] = []
    if config.include_funding:
        if config.market != "um":
            raise ValueError("funding is only available for Binance USD-M futures market")
        funding = load_funding(
            config.strategy_symbol,
            start=start,
            end=end,
            cache_dir=config.funding_cache_dir,
            fetch=fetch,
            skip_missing=True,
        )

    candidate_specs = [
        CandidateSpec(
            feature_family=family,
            lookback=lookback,
            threshold=threshold,
            mode=mode,
            polarity=polarity,
        )
        for family in config.feature_families
        for lookback in config.lookbacks
        for threshold in config.thresholds
        for mode in config.modes
        for polarity in config.polarities
    ]
    if not candidate_specs:
        raise ValueError("at least one candidate spec is required")

    first_periods, _first_diag = _candidate_periods(aligned, config, candidate_specs[0], funding, derivatives_state)
    train_end = int(len(first_periods) * config.train_fraction)
    if train_end <= max(config.lookbacks) or train_end >= len(first_periods) - 1:
        raise ValueError("train/test split leaves insufficient train or test data")
    residual_labels = _forward_residual_labels(aligned, config)
    validation_candidates: list[dict[str, Any]] = []
    validation_daily_timestamps: list[str] = []
    validation_btc_returns: list[float] = []
    validation_ic_indices = list(residual_labels)
    validation_ic_timestamps = [
        str(aligned[index][0] + _interval_ms(config.interval)) for index in validation_ic_indices
    ]
    validation_ic_labels = [
        float(residual_labels[index]["residual_forward_return_pct"]) for index in validation_ic_indices
    ]

    candidate_results: list[dict[str, Any]] = []
    selected_periods: list[dict[str, Any]] = []
    selected_diagnostics: dict[str, Any] = {}
    selected_train_ic: dict[str, float | int] = {}
    selected_test_ic: dict[str, float | int] = {}
    selected_spec = candidate_specs[0]
    best_score = float("-inf")
    for spec in candidate_specs:
        periods, diagnostics = _candidate_periods(aligned, config, spec, funding, derivatives_state)
        train_periods = periods[:train_end]
        test_periods = periods[train_end:]
        train_score = _score_periods(train_periods)
        test_score = _score_periods(test_periods)
        ic_samples = _candidate_ic_samples(aligned, config, spec, derivatives_state, residual_labels)
        train_ic_samples = [sample for sample in ic_samples if int(sample["decision_index"]) < train_end]
        test_ic_samples = [sample for sample in ic_samples if int(sample["decision_index"]) >= train_end]
        train_ic = _score_ic_samples(train_ic_samples)
        test_ic = _score_ic_samples(test_ic_samples)
        eligible = float(diagnostics["feature_coverage"]) >= config.min_feature_coverage
        if config.selection_metric == "rank_ic":
            score = float(train_ic["rank_ic"]) if eligible and int(train_ic["sample_count"]) >= 20 else float("-inf")
        else:
            score = train_score["net_residual_return_pct"] if eligible else float("-inf")
        row = {
            **spec.to_dict(),
            "train": train_score,
            "test": test_score,
            "train_ic": train_ic,
            "test_ic": test_ic,
            "diagnostics": diagnostics,
            "eligible": eligible,
        }
        candidate_results.append(row)
        if include_validation_matrix:
            daily_periods = _aggregate_daily(periods)
            daily_timestamps = [str(period["ts"]) for period in daily_periods]
            if not validation_daily_timestamps:
                validation_daily_timestamps = daily_timestamps
                validation_btc_returns = [float(period["btc_return_pct"]) for period in daily_periods]
            elif daily_timestamps != validation_daily_timestamps:
                raise ValueError("candidate daily return series are not aligned")
            feature_by_index = {
                int(sample["decision_index"]): float(sample["feature_value"]) for sample in ic_samples
            }
            validation_candidates.append(
                {
                    **spec.to_dict(),
                    "strategy_returns_pct": [float(period["strategy_return_pct"]) for period in daily_periods],
                    "ic_feature_values": [feature_by_index.get(index) for index in validation_ic_indices],
                }
            )
        if score > best_score:
            best_score = score
            selected_spec = spec
            selected_periods = periods
            selected_diagnostics = diagnostics
            selected_train_ic = train_ic
            selected_test_ic = test_ic
    if best_score == float("-inf"):
        raise ValueError(
            "no feature candidate met min_feature_coverage; check data overlap or lower --min-feature-coverage"
        )

    raw_oos_periods = selected_periods[train_end:]
    output_periods = _aggregate_monthly(raw_oos_periods) if config.output_granularity == "month" else raw_oos_periods
    output_score = _score_periods(output_periods)

    rules = symbol_rules
    if rules is None and exchange_info is not None:
        rules = rules_from_exchange_info(exchange_info, market=config.market)
    filter_diagnostics: dict[str, Any] | None = None
    exchange_rules_source = "unknown"
    filter_validator_reused = False
    min_notional_coverage = 0.0
    if rules is not None:
        filter_diagnostics = evaluate_period_filter_coverage(
            raw_oos_periods,
            rules,
            symbol=config.strategy_symbol,
            account_equity_usdt=config.account_equity_usdt,
            target_notional_fraction=config.target_notional_fraction,
            leverage=config.leverage,
        )
        exchange_rules_source = "runtime_exchange_info"
        filter_validator_reused = True
        min_notional_coverage = float(filter_diagnostics["min_notional_coverage"])

    basis = {
        "config": config.to_dict(),
        "selected_candidate": selected_spec.to_dict(),
        "first_ts": output_periods[0]["ts"],
        "last_ts": output_periods[-1]["ts"],
        "period_count": len(output_periods),
    }
    data_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    config_hash = hashlib.sha256(json.dumps(config.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()
    largest_removed = _largest_contributor_removed_return(output_periods)

    payload = {
        "schema_version": FEATURE_EXPERIMENT_VERSION,
        "meta": {
            "point_in_time": True,
            "as_of_join": True,
            "replayable": True,
            "trial_count": len(candidate_specs),
            "exchange_rules_source": exchange_rules_source,
            "filter_validator_reused": filter_validator_reused,
            "costs_included": True,
            "funding_included": config.include_funding,
            "min_notional_coverage": min_notional_coverage,
            "worst_case_cost_buffer_pct": 0.0,
            "effective_breadth": 1.0,
            "claims_cross_sectional_edge": False,
            "correlation_stress_pass": False,
            "capacity_checked": filter_validator_reused,
            "label_spec": (
                f"{config.strategy_symbol} forward return minus rolling as-of BTC beta times BTC forward return"
            ),
            "benchmark_spec": "cash/BTC/TOP equal-weight/current live baseline",
            "data_spec": (
                "Binance USD-M REST klines with native taker-flow fields aligned with train/test split"
                if config.kline_source == "rest"
                else "Binance public dump klines with native taker-flow fields aligned with train/test split"
            ),
            "cost_spec": "taker fee + slippage per turnover; optional USD-M funding; runtime filters if provided",
            "kill_line": "block unless OOS beta residual, costs, anti-overfit, and paper gates pass",
            "data_hash": data_hash,
            "config_hash": config_hash,
            "largest_contributor_removed_return_pct": largest_removed,
            "embargo_applied": False,
        },
        "config": config.to_dict(),
        "selected_candidate": selected_spec.to_dict(),
        "diagnostics": {
            "train_period_count": train_end,
            "raw_oos_bar_count": len(raw_oos_periods),
            "output_period_count": len(output_periods),
            "output_granularity": config.output_granularity,
            "symbols": list(config.symbols),
            "kline_source": kline_diagnostics,
            "kline_field_coverage": _kline_field_coverage(bars_by_symbol[config.strategy_symbol]),
            "derivatives_state": {
                "used": derivatives_state is not None,
                "path": derivatives_state.get("path") if derivatives_state else None,
                "history_limit": (
                    derivatives_state.get("meta", {}).get("history_limit") if derivatives_state else None
                ),
                "source": derivatives_state.get("meta", {}).get("official_source") if derivatives_state else None,
            },
            "selected_train_score": _score_periods(selected_periods[:train_end]),
            "selected_oos_score": output_score,
            "selection_metric": config.selection_metric,
            "selected_train_ic": selected_train_ic,
            "selected_oos_ic": selected_test_ic,
            "selected_diagnostics": selected_diagnostics,
            "filter_diagnostics": filter_diagnostics,
            "candidate_count": len(candidate_results),
            "top_train_candidates": sorted(
                candidate_results,
                key=(
                    (lambda item: item["train_ic"]["rank_ic"])
                    if config.selection_metric == "rank_ic"
                    else (lambda item: item["train"]["net_residual_return_pct"])
                ),
                reverse=True,
            )[:10],
            "note": "Research-only feature experiment; selected on train split and evaluated on OOS split.",
        },
        "periods": output_periods,
    }
    if include_validation_matrix:
        payload["validation_matrix"] = {
            "schema_version": "alpha_agent_feature_validation_matrix_v0.1",
            "granularity": "day",
            "selection_metric": config.selection_metric,
            "source_selected_candidate_id": selected_spec.candidate_id,
            "daily_timestamps": validation_daily_timestamps,
            "btc_returns_pct": validation_btc_returns,
            "ic_timestamps": validation_ic_timestamps,
            "ic_residual_forward_returns_pct": validation_ic_labels,
            "candidate_count": len(validation_candidates),
            "candidates": validation_candidates,
        }
    return payload


def write_feature_experiment_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="alpha-agent-feature-experiment",
        path_key="artifact_path",
        default_filename="alpha_agent_feature_experiment.json",
        explicit_path=explicit_path,
    )
