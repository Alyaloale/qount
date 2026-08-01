from __future__ import annotations

import itertools
import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from .exchange_utils import build_exchange
from .exchange_utils import call_with_time_sync_retry
from .exchange_utils import resolve_market_symbols
from .settings import Settings
from .trade_policy import timeframe_to_ms


STRATEGY_SELECTION_VERSION = "strategy_selection_scan_v1"
DEFAULT_STRATEGY_SCAN_FREQUENCIES = ("5m", "1h", "4h", "1d")
DEFAULT_STRATEGY_SCAN_FAMILIES = ("xs_mom", "xs_rev", "ts_mom", "carry")
# Opt-in funding-as-feature families (kept out of the default so existing scans
# are unchanged; enabled explicitly via --families xs_funding xs_funding_rev).
STRATEGY_SCAN_FAMILY_CHOICES = DEFAULT_STRATEGY_SCAN_FAMILIES + ("xs_funding", "xs_funding_rev")
DEFAULT_CARRY_BASIS_SOURCE = "funding_history"
DEFAULT_CARRY_EXECUTION_COST_MODEL = "directional_round_trip"
DEFAULT_CARRY_CAPITAL_MODEL = "perp_notional"
DEFAULT_DISCOVERY_END_UTC = datetime(2026, 6, 1, tzinfo=timezone.utc)
DEFAULT_DIRECTIONAL_OVERLAP_MODE = "stride"
DEFAULT_DIRECTIONAL_EVALUATION_MODE = "cross_section"
DEFAULT_DIRECTIONAL_EXIT_MODE = "close"
DEFAULT_DIRECTIONAL_PURGED_CV_FOLDS = 0
DEFAULT_DIRECTIONAL_EMBARGO_BARS = 0
DEFAULT_DIRECTIONAL_BARRIER_VOL_LOOKBACK_BARS = 0


@dataclass(frozen=True)
class StrategySample:
    timestamp_ms: int
    symbol: str
    signal: float
    future_return_pct: float
    long_return_pct: float
    short_return_pct: float
    long_exit_reason: str
    short_exit_reason: str


@dataclass(frozen=True)
class BarrierVolConfig:
    """Research-only volatility-scaled triple-barrier spec.

    When active, take-profit / stop-loss barriers are derived per sample from the
    recent realized close-to-close return volatility (sigma) measured strictly with
    decision-time information, instead of fixed percentages. This adapts barriers to
    each symbol / regime, the AFML-standard remedy for fixed barriers that ignore
    per-symbol volatility.
    """

    lookback_bars: int
    take_profit_sigma: float
    stop_loss_sigma: float

    @property
    def active(self) -> bool:
        return self.lookback_bars > 0 and self.take_profit_sigma > 0.0 and self.stop_loss_sigma > 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = _mean(values)
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(max(variance, 0.0))


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        end = index + 1
        while end < len(indexed) and indexed[end][1] == indexed[index][1]:
            end += 1
        avg_rank = (index + 1 + end) / 2.0
        for original_index, _value in indexed[index:end]:
            ranks[original_index] = avg_rank
        index = end
    return ranks


def pearson_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = _mean(left)
    right_mean = _mean(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    numerator = sum(a * b for a, b in zip(left_centered, right_centered))
    left_denominator = math.sqrt(sum(value * value for value in left_centered))
    right_denominator = math.sqrt(sum(value * value for value in right_centered))
    denominator = left_denominator * right_denominator
    if denominator <= 0.0:
        return None
    return numerator / denominator


def spearman_rank_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return pearson_correlation(_rank(left), _rank(right))


def _t_stat(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    std_value = _std(values)
    if std_value <= 0.0:
        return None
    return _mean(values) / (std_value / math.sqrt(len(values)))


def _effective_sample_count(values: list[float], max_lag: int) -> float:
    """Estimate independent observations after serial-correlation adjustment.

    Directional holding-period returns overlap for ``holding_bars`` observations.
    A Bartlett-weighted autocorrelation adjustment is conservative for that known
    overlap. The result is diagnostic, not a replacement for a block bootstrap.
    """

    count = len(values)
    if count < 2 or max_lag <= 0:
        return float(count)
    lag_limit = min(int(max_lag), count - 1)
    denominator = 1.0
    for lag in range(1, lag_limit + 1):
        correlation = pearson_correlation(values[lag:], values[:-lag])
        if correlation is None:
            continue
        weight = 1.0 - (lag / (lag_limit + 1.0))
        denominator += 2.0 * weight * correlation
    if denominator <= 1.0:
        return float(count)
    return max(1.0, min(float(count), count / denominator))


def _t_stat_with_effective_count(values: list[float], effective_count: float) -> float | None:
    if len(values) < 2 or effective_count < 2.0:
        return None
    std_value = _std(values)
    if std_value <= 0.0:
        return None
    return _mean(values) / (std_value / math.sqrt(effective_count))


def _annualization_periods(frequency: str) -> float:
    return (365.0 * 24.0 * 60.0 * 60.0 * 1000.0) / timeframe_to_ms(frequency)


def _sharpe(values: list[float], frequency: str) -> float | None:
    if len(values) < 2:
        return None
    std_value = _std(values)
    if std_value <= 0.0:
        return None
    return (_mean(values) / std_value) * math.sqrt(_annualization_periods(frequency))


_EULER_MASCHERONI = 0.5772156649015329


def _per_period_sharpe(cell: dict[str, object]) -> float | None:
    """Strip annualization from a cell's portfolio_sharpe to get per-observation SR."""

    sharpe = cell.get("portfolio_sharpe")
    frequency = cell.get("frequency")
    if not isinstance(sharpe, (int, float)) or not isinstance(frequency, str):
        return None
    ann = _annualization_periods(frequency)
    if ann <= 0.0:
        return None
    return float(sharpe) / math.sqrt(ann)


def compute_directional_deflated_sharpe(cells: list[dict[str, object]]) -> dict[str, object] | None:
    """Deflated Sharpe Ratio over the directional cells evaluated in one scan.

    Quantifies the multiple-testing penalty (López de Prado): given ``N`` trials with
    Sharpe dispersion ``V``, deflate the best per-period Sharpe by the expected maximum
    Sharpe under ``N`` independent trials. Uses the normal-returns simplification
    (skew=0, excess kurtosis=0). DSR is a probability; higher = more likely the best
    cell's Sharpe is real rather than a search artifact. research-only, diagnostic.
    """

    trials = [(cell, _per_period_sharpe(cell)) for cell in cells]
    trials = [(cell, sr) for cell, sr in trials if sr is not None]
    if len(trials) < 2:
        return None
    sharpes = [sr for _cell, sr in trials]
    trial_count = len(sharpes)
    variance = statistics.pvariance(sharpes)
    best_cell, best_sr = max(trials, key=lambda item: item[1])
    period_count = _safe_float(
        best_cell.get("effective_period_count", best_cell.get("portfolio_period_count")),
        0.0,
    )

    normal = statistics.NormalDist()
    if variance <= 0.0:
        expected_max = 0.0
    else:
        expected_max = math.sqrt(variance) * (
            (1.0 - _EULER_MASCHERONI) * normal.inv_cdf(1.0 - 1.0 / trial_count)
            + _EULER_MASCHERONI * normal.inv_cdf(1.0 - 1.0 / (trial_count * math.e))
        )

    deflated = None
    if period_count > 1:
        deflated = normal.cdf((best_sr - expected_max) * math.sqrt(period_count - 1))

    return {
        "trial_count": trial_count,
        "best_cell_frequency": best_cell.get("frequency"),
        "best_cell_family": best_cell.get("family"),
        "best_cell_signal_lookback_bars": best_cell.get("signal_lookback_bars"),
        "best_cell_holding_bars": best_cell.get("holding_bars"),
        "best_annualized_sharpe": best_cell.get("portfolio_sharpe"),
        "best_per_period_sharpe": best_sr,
        "best_period_count": period_count,
        "best_raw_period_count": best_cell.get("portfolio_period_count"),
        "trial_per_period_sharpe_variance": variance,
        "expected_max_per_period_sharpe": expected_max,
        "deflated_sharpe_ratio": deflated,
        "assumes_normal_returns": True,
    }


DEFAULT_DIRECTIONAL_PBO_BLOCKS = 10


def _block_sharpe(stats: list[tuple[float, float, int]], block_indices: tuple[int, ...]) -> float | None:
    total_sum = 0.0
    total_sq = 0.0
    total_n = 0
    for index in block_indices:
        block_sum, block_sq, block_n = stats[index]
        total_sum += block_sum
        total_sq += block_sq
        total_n += block_n
    if total_n < 2:
        return None
    mean = total_sum / total_n
    variance = (total_sq - total_n * mean * mean) / (total_n - 1)
    if variance <= 0.0:
        return None
    return mean / math.sqrt(variance)


def _pbo_for_group(group: list[dict[str, object]], block_count: int) -> dict[str, object] | None:
    """Single-frequency CSCV PBO over configs sharing a common time axis."""

    if len(group) < 2:
        return None
    timestamps = sorted({int(ts) for cell in group for ts in cell["period_returns_by_timestamp"]})
    if len(timestamps) < block_count:
        return None
    bounds = [int(len(timestamps) * index / block_count) for index in range(block_count + 1)]
    blocks = [set(timestamps[bounds[index] : bounds[index + 1]]) for index in range(block_count)]

    config_stats: list[list[tuple[float, float, int]]] = []
    for cell in group:
        series = {int(ts): float(value) for ts, value in cell["period_returns_by_timestamp"].items()}
        row: list[tuple[float, float, int]] = []
        for block in blocks:
            values = [series[ts] for ts in block if ts in series]
            row.append((sum(values), sum(value * value for value in values), len(values)))
        config_stats.append(row)

    half = block_count // 2
    logits: list[float] = []
    overfit = 0
    for is_blocks in itertools.combinations(range(block_count), half):
        oos_blocks = tuple(index for index in range(block_count) if index not in is_blocks)
        is_scores = [(ci, _block_sharpe(config_stats[ci], is_blocks)) for ci in range(len(group))]
        is_scores = [(ci, score) for ci, score in is_scores if score is not None]
        if not is_scores:
            continue
        best_ci = max(is_scores, key=lambda item: item[1])[0]
        oos_scores = [(ci, _block_sharpe(config_stats[ci], oos_blocks)) for ci in range(len(group))]
        oos_scores = [(ci, score) for ci, score in oos_scores if score is not None]
        best_oos = dict(oos_scores).get(best_ci)
        if best_oos is None or len(oos_scores) < 2:
            continue
        worse = sum(1 for _ci, score in oos_scores if score < best_oos)
        omega = (worse + 0.5) / len(oos_scores)
        omega = min(max(omega, 1e-9), 1.0 - 1e-9)
        logit = math.log(omega / (1.0 - omega))
        logits.append(logit)
        if logit <= 0.0:
            overfit += 1

    if not logits:
        return None
    return {
        "config_count": len(group),
        "block_count": block_count,
        "combination_count": len(logits),
        "pbo": overfit / len(logits),
        "median_logit": statistics.median(logits),
        "mean_logit": _mean(logits),
        "method": "cscv_sharpe",
    }


def compute_directional_pbo(
    cells: list[dict[str, object]],
    *,
    block_count: int = DEFAULT_DIRECTIONAL_PBO_BLOCKS,
) -> dict[str, object] | None:
    """Probability of Backtest Overfitting via CSCV (Bailey & López de Prado).

    Partition the common time axis into S contiguous blocks, then for every way to
    split them into S/2 in-sample (IS) and S/2 out-of-sample (OOS) halves: pick the
    IS-best config by Sharpe, look up its OOS relative rank ω, and record the logit
    λ=ln(ω/(1-ω)). PBO = fraction of splits where the IS-best config lands below the
    OOS median (λ ≤ 0). High PBO means the search winner is overfit. research-only.

    CSCV needs a common time axis, so PBO is computed per frequency group. The primary
    frequency reported at the top level is the one holding the highest per-period Sharpe
    config (so PBO and DSR describe the same search winner); per-frequency results are
    kept under ``by_frequency``. Each cell must carry an in-memory
    ``period_returns_by_timestamp``.
    """

    by_frequency: dict[str, list[dict[str, object]]] = {}
    best_sharpe = None
    primary_frequency: str | None = None
    for cell in cells:
        series = cell.get("period_returns_by_timestamp")
        frequency = cell.get("frequency")
        if not (isinstance(series, dict) and series and isinstance(frequency, str)):
            continue
        by_frequency.setdefault(frequency, []).append(cell)
        per_period = _per_period_sharpe(cell)
        if per_period is not None and (best_sharpe is None or per_period > best_sharpe):
            best_sharpe = per_period
            primary_frequency = frequency
    if not by_frequency:
        return None

    block_count = block_count if block_count % 2 == 0 else block_count - 1
    if block_count < 2:
        return None

    by_frequency_result: dict[str, object] = {}
    for frequency, group in by_frequency.items():
        group_result = _pbo_for_group(group, block_count)
        if group_result is not None:
            by_frequency_result[frequency] = group_result

    if not by_frequency_result:
        return None
    if primary_frequency not in by_frequency_result:
        primary_frequency = max(
            by_frequency_result, key=lambda freq: int(by_frequency_result[freq]["config_count"])
        )

    primary = by_frequency_result[primary_frequency]
    return {
        "frequency": primary_frequency,
        "config_count": primary["config_count"],
        "block_count": primary["block_count"],
        "combination_count": primary["combination_count"],
        "pbo": primary["pbo"],
        "median_logit": primary["median_logit"],
        "mean_logit": primary["mean_logit"],
        "method": "cscv_sharpe",
        "by_frequency": by_frequency_result,
    }


def _max_drawdown(values: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0.0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def build_directional_samples(
    rows_by_symbol: dict[str, list[list[float]]],
    *,
    family: str,
    signal_lookback_bars: int,
    holding_bars: int,
    start_ms: int,
    end_ms: int,
    exit_mode: str = DEFAULT_DIRECTIONAL_EXIT_MODE,
    take_profit_pct: float = 0.0,
    stop_loss_pct: float = 0.0,
    barrier_vol: BarrierVolConfig | None = None,
) -> list[StrategySample]:
    samples: list[StrategySample] = []
    for symbol, rows in rows_by_symbol.items():
        sorted_rows = sorted(rows, key=lambda row: int(row[0]))
        for index in range(max(signal_lookback_bars, 1), len(sorted_rows) - max(holding_bars, 1)):
            current = sorted_rows[index]
            timestamp_ms = int(current[0])
            if timestamp_ms < start_ms or timestamp_ms > end_ms:
                continue
            lookback_close = _safe_float(sorted_rows[index - signal_lookback_bars][4])
            current_close = _safe_float(current[4])
            future_close = _safe_float(sorted_rows[index + holding_bars][4])
            if lookback_close <= 0.0 or current_close <= 0.0 or future_close <= 0.0:
                continue
            past_return = (current_close / lookback_close) - 1.0
            future_return = (future_close / current_close) - 1.0
            long_return, short_return, long_exit_reason, short_exit_reason = _directional_exit_returns(
                sorted_rows,
                index=index,
                holding_bars=holding_bars,
                exit_mode=exit_mode,
                take_profit_pct=take_profit_pct,
                stop_loss_pct=stop_loss_pct,
                barrier_vol=barrier_vol,
            )
            if family == "xs_rev":
                signal = -past_return
            else:
                signal = past_return
            samples.append(
                StrategySample(
                    timestamp_ms=timestamp_ms,
                    symbol=symbol,
                    signal=signal,
                    future_return_pct=future_return,
                    long_return_pct=long_return,
                    short_return_pct=short_return,
                    long_exit_reason=long_exit_reason,
                    short_exit_reason=short_exit_reason,
                )
            )
    return samples


def _asof_value(sorted_funding_rows: list[dict[str, Any]], timestamp_ms: int, field: str) -> float | None:
    """As-of join: value of ``field`` from the most recent funding row settled at
    or before ``timestamp_ms``.

    ``sorted_funding_rows`` must be ascending by ``timestamp_ms``. Strictly no
    look-ahead — funding settled after the decision bar is never visible. Returns
    None when no settlement precedes the bar or the field is missing.
    """

    chosen: float | None = None
    for row in sorted_funding_rows:
        row_ts = row.get("timestamp_ms")
        if row_ts is None or int(row_ts) > timestamp_ms:
            break
        value = row.get(field)
        if value is not None:
            chosen = _safe_float(value)
    return chosen


def build_carry_tilt_samples(
    rows_by_symbol: dict[str, list[list[float]]],
    funding_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    family: str,
    holding_bars: int,
    start_ms: int,
    end_ms: int,
    signal_field: str = "funding_rate",
) -> list[StrategySample]:
    """Cross-sectional samples whose signal is the as-of funding rate (or basis).

    Tests whether funding / basis carries cross-sectional predictive content for
    forward close-to-close returns — funding used as a *feature*, not as the
    structural cash-flow harvested by ``evaluate_carry_family``. ``xs_funding``
    longs high funding; ``xs_funding_rev`` negates the signal (carry-reversal).
    Symbols without any settled funding before the decision bar are skipped.
    """

    samples: list[StrategySample] = []
    for symbol, rows in rows_by_symbol.items():
        sorted_rows = sorted(rows, key=lambda row: int(row[0]))
        funding_rows = sorted(
            funding_by_symbol.get(symbol, []), key=lambda item: int(item["timestamp_ms"])
        )
        if not funding_rows:
            continue
        for index in range(0, len(sorted_rows) - max(holding_bars, 1)):
            current = sorted_rows[index]
            timestamp_ms = int(current[0])
            if timestamp_ms < start_ms or timestamp_ms > end_ms:
                continue
            current_close = _safe_float(current[4])
            future_close = _safe_float(sorted_rows[index + holding_bars][4])
            if current_close <= 0.0 or future_close <= 0.0:
                continue
            raw_signal = _asof_value(funding_rows, timestamp_ms, signal_field)
            if raw_signal is None:
                continue
            future_return = (future_close / current_close) - 1.0
            signal = -raw_signal if family == "xs_funding_rev" else raw_signal
            samples.append(
                StrategySample(
                    timestamp_ms=timestamp_ms,
                    symbol=symbol,
                    signal=signal,
                    future_return_pct=future_return,
                    long_return_pct=future_return,
                    short_return_pct=-future_return,
                    long_exit_reason="time",
                    short_exit_reason="time",
                )
            )
    return samples


def _recent_return_std(rows: list[list[float]], index: int, lookback: int) -> float | None:
    """Sample std of close-to-close returns over the lookback bars ending at ``index``.

    Uses only bars at or before the decision bar ``index`` (no look-ahead).
    """

    if lookback < 1 or index - lookback < 0:
        return None
    returns: list[float] = []
    for position in range(index - lookback + 1, index + 1):
        previous_close = _safe_float(rows[position - 1][4])
        current_close = _safe_float(rows[position][4])
        if previous_close > 0.0 and current_close > 0.0:
            returns.append((current_close / previous_close) - 1.0)
    if len(returns) < 2:
        return None
    return _std(returns)


def _directional_exit_returns(
    rows: list[list[float]],
    *,
    index: int,
    holding_bars: int,
    exit_mode: str,
    take_profit_pct: float,
    stop_loss_pct: float,
    barrier_vol: BarrierVolConfig | None = None,
) -> tuple[float, float, str, str]:
    current_close = _safe_float(rows[index][4])
    future_close = _safe_float(rows[index + holding_bars][4])
    close_return = (future_close / current_close) - 1.0 if current_close > 0.0 and future_close > 0.0 else 0.0
    if exit_mode != "triple_barrier" or current_close <= 0.0:
        return close_return, -close_return, "time", "time"

    if barrier_vol is not None and barrier_vol.active:
        sigma = _recent_return_std(rows, index, barrier_vol.lookback_bars)
        if sigma is None or sigma <= 0.0:
            return close_return, -close_return, "time", "time"
        take_profit_pct = barrier_vol.take_profit_sigma * sigma
        stop_loss_pct = barrier_vol.stop_loss_sigma * sigma

    if take_profit_pct <= 0.0 or stop_loss_pct <= 0.0:
        return close_return, -close_return, "time", "time"

    long_result: float | None = None
    short_result: float | None = None
    long_reason = "time"
    short_reason = "time"
    for row in rows[index + 1 : index + holding_bars + 1]:
        high_return = (_safe_float(row[2]) / current_close) - 1.0
        low_return = (_safe_float(row[3]) / current_close) - 1.0
        if long_result is None:
            if low_return <= -stop_loss_pct:
                long_result = -stop_loss_pct
                long_reason = "stop_loss"
            elif high_return >= take_profit_pct:
                long_result = take_profit_pct
                long_reason = "take_profit"
        if short_result is None:
            if high_return >= stop_loss_pct:
                short_result = -stop_loss_pct
                short_reason = "stop_loss"
            elif low_return <= -take_profit_pct:
                short_result = take_profit_pct
                short_reason = "take_profit"
        if long_result is not None and short_result is not None:
            break
    return (
        close_return if long_result is None else long_result,
        -close_return if short_result is None else short_result,
        long_reason,
        short_reason,
    )


def _signal_dispersion(group: list[StrategySample]) -> float:
    """Cross-sectional dispersion (sample std) of the family signals at one timestamp.

    Signals are built from decision-time data only, so this regime gate uses no
    look-ahead. Low dispersion means no clear relative winners/losers (a correlated,
    momentum-unfriendly regime); high dispersion means a tradeable cross-section.
    """

    return _std([sample.signal for sample in group])


def _barrier_vol_fields(barrier_vol: BarrierVolConfig | None) -> dict[str, object]:
    return {
        "directional_barrier_vol_lookback_bars": 0 if barrier_vol is None else barrier_vol.lookback_bars,
        "directional_take_profit_sigma": 0.0 if barrier_vol is None else barrier_vol.take_profit_sigma,
        "directional_stop_loss_sigma": 0.0 if barrier_vol is None else barrier_vol.stop_loss_sigma,
    }


def _allowed_timestamps_for_overlap_mode(
    timestamps: list[int],
    *,
    holding_bars: int,
    overlap_mode: str,
) -> set[int]:
    ordered = sorted(set(timestamps))
    if overlap_mode != "stride":
        return set(ordered)
    stride = max(int(holding_bars), 1)
    return {timestamp for index, timestamp in enumerate(ordered) if index % stride == 0}


def _effective_breadth(rows_by_symbol: dict[str, list[list[float]]]) -> dict[str, object]:
    returns_by_symbol: dict[str, dict[int, float]] = {}
    for symbol, rows in rows_by_symbol.items():
        sorted_rows = sorted(rows, key=lambda row: int(row[0]))
        symbol_returns: dict[int, float] = {}
        for previous, current in zip(sorted_rows, sorted_rows[1:]):
            previous_close = _safe_float(previous[4])
            current_close = _safe_float(current[4])
            if previous_close > 0.0 and current_close > 0.0:
                symbol_returns[int(current[0])] = (current_close / previous_close) - 1.0
        returns_by_symbol[symbol] = symbol_returns

    symbols = sorted(returns_by_symbol)
    correlations: list[float] = []
    matrix: dict[str, dict[str, float | None]] = {symbol: {} for symbol in symbols}
    for left_index, left_symbol in enumerate(symbols):
        for right_symbol in symbols:
            if left_symbol == right_symbol:
                matrix[left_symbol][right_symbol] = 1.0
                continue
            common = sorted(set(returns_by_symbol[left_symbol]) & set(returns_by_symbol[right_symbol]))
            corr = pearson_correlation(
                [returns_by_symbol[left_symbol][timestamp] for timestamp in common],
                [returns_by_symbol[right_symbol][timestamp] for timestamp in common],
            )
            matrix[left_symbol][right_symbol] = corr
            if symbols.index(right_symbol) > left_index and corr is not None:
                correlations.append(corr)

    avg_abs_corr = _mean([abs(value) for value in correlations]) if correlations else 0.0
    raw_breadth = len(symbols)
    effective = raw_breadth / (1.0 + max(raw_breadth - 1, 0) * avg_abs_corr) if raw_breadth else 0.0
    return {
        "raw_symbol_count": raw_breadth,
        "avg_abs_pairwise_return_corr": avg_abs_corr,
        "effective_breadth": effective,
        "correlation_matrix": matrix,
    }


def _increment_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _time_folds(start_ms: int, end_ms: int, fold_count: int) -> list[tuple[int, int]]:
    if fold_count <= 1 or end_ms <= start_ms:
        return []
    span = end_ms - start_ms + 1
    folds: list[tuple[int, int]] = []
    for index in range(fold_count):
        fold_start = start_ms + int((span * index) / fold_count)
        fold_end = start_ms + int((span * (index + 1)) / fold_count) - 1
        if index == fold_count - 1:
            fold_end = end_ms
        if fold_end >= fold_start:
            folds.append((fold_start, fold_end))
    return folds


def _utc_iso_from_ms(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _attach_directional_purged_cv(
    result: dict[str, object],
    rows_by_symbol: dict[str, list[list[float]]],
    *,
    family: str,
    frequency: str,
    signal_lookback_bars: int,
    holding_bars: int,
    start_ms: int,
    end_ms: int,
    min_cross_section_symbols: int,
    top_fraction: float,
    cost_per_directional_bet_pct: float,
    overlap_mode: str,
    evaluation_mode: str,
    max_open_positions: int,
    exit_mode: str,
    take_profit_pct: float,
    stop_loss_pct: float,
    barrier_vol: BarrierVolConfig | None,
    regime_min_dispersion_pct: float,
    fold_count: int,
    embargo_bars: int,
) -> None:
    folds = _time_folds(start_ms, end_ms, fold_count)
    if not folds:
        return

    timeframe_ms = timeframe_to_ms(frequency)
    embargo_ms = max(int(embargo_bars), 0) * timeframe_ms
    holding_ms = max(int(holding_bars), 1) * timeframe_ms
    fold_results: list[dict[str, object]] = []
    for index, (fold_start_ms, fold_end_ms) in enumerate(folds, start=1):
        # There is no fitted model in these rule-based families. This is therefore
        # a purged fold-stability diagnostic: labels must finish before the fold
        # boundary, with an embargo gap on both sides of the evaluated fold.
        eval_start_ms = fold_start_ms + embargo_ms
        eval_end_ms = fold_end_ms - holding_ms - embargo_ms
        if family in {"xs_mom", "xs_rev"}:
            evaluator = (
                evaluate_cross_sectional_portfolio_replay
                if evaluation_mode == "portfolio_replay"
                else evaluate_cross_sectional_family
            )
            kwargs: dict[str, object] = {}
            if evaluation_mode == "portfolio_replay":
                kwargs["max_open_positions"] = max_open_positions
            fold_result = evaluator(
                rows_by_symbol,
                family=family,
                frequency=frequency,
                signal_lookback_bars=signal_lookback_bars,
                holding_bars=holding_bars,
                start_ms=eval_start_ms,
                end_ms=eval_end_ms,
                min_cross_section_symbols=min_cross_section_symbols,
                top_fraction=top_fraction,
                cost_per_directional_bet_pct=cost_per_directional_bet_pct,
                overlap_mode=overlap_mode,
                exit_mode=exit_mode,
                take_profit_pct=take_profit_pct,
                stop_loss_pct=stop_loss_pct,
                barrier_vol=barrier_vol,
                regime_min_dispersion_pct=regime_min_dispersion_pct,
                **kwargs,
            )
        else:
            fold_result = evaluate_time_series_momentum(
                rows_by_symbol,
                frequency=frequency,
                signal_lookback_bars=signal_lookback_bars,
                holding_bars=holding_bars,
                start_ms=eval_start_ms,
                end_ms=eval_end_ms,
                cost_per_directional_bet_pct=cost_per_directional_bet_pct,
                overlap_mode=overlap_mode,
                exit_mode=exit_mode,
                take_profit_pct=take_profit_pct,
                stop_loss_pct=stop_loss_pct,
                barrier_vol=barrier_vol,
            )
        fold_results.append(
            {
                "fold": index,
                "raw_fold_start_utc": _utc_iso_from_ms(fold_start_ms),
                "raw_fold_end_utc": _utc_iso_from_ms(fold_end_ms),
                "eval_start_utc": _utc_iso_from_ms(eval_start_ms),
                "eval_end_utc": _utc_iso_from_ms(eval_end_ms),
                "embargo_bars": max(int(embargo_bars), 0),
                "embargo_ms": embargo_ms,
                "label_horizon_bars": max(int(holding_bars), 1),
                "label_end_must_be_before_utc": _utc_iso_from_ms(fold_end_ms - embargo_ms),
                "method": "purged_label_fold_stability_no_training",
                "sample_count": fold_result.get("sample_count"),
                "cross_section_count": fold_result.get("cross_section_count"),
                "turnover_events": fold_result.get("turnover_events"),
                "rank_ic_mean": fold_result.get("rank_ic_mean"),
                "portfolio_sum_return_pct": fold_result.get("portfolio_sum_return_pct"),
                "portfolio_mean_return_pct": fold_result.get("portfolio_mean_return_pct"),
                "portfolio_sharpe": fold_result.get("portfolio_sharpe"),
                "portfolio_max_drawdown_pct": fold_result.get("portfolio_max_drawdown_pct"),
                "directional_exit_reason_counts": fold_result.get("directional_exit_reason_counts"),
            }
        )

    fold_sums = [
        float(fold["portfolio_sum_return_pct"])
        for fold in fold_results
        if fold.get("portfolio_sum_return_pct") is not None
    ]
    result["directional_purged_cv"] = {
        "method": "purged_label_fold_stability_no_training",
        "fold_count": len(fold_results),
        "requested_fold_count": fold_count,
        "embargo_bars": max(int(embargo_bars), 0),
        "embargo_ms": embargo_ms,
        "positive_fold_count": sum(1 for value in fold_sums if value > 0.0),
        "min_fold_sum_return_pct": None if not fold_sums else min(fold_sums),
        "mean_fold_sum_return_pct": None if not fold_sums else _mean(fold_sums),
        "folds": fold_results,
    }


def _aggregate_directional_cross_sections(
    samples: list[StrategySample],
    *,
    frequency: str,
    holding_bars: int,
    min_cross_section_symbols: int,
    top_fraction: float,
    cost_per_directional_bet_pct: float,
    overlap_mode: str,
    regime_min_dispersion_pct: float,
) -> dict[str, object]:
    """Shared per-timestamp cross-sectional aggregation: rank-IC, long/short net
    returns, period-return series and turnover. Used by both the price-signal
    families and the funding-signal carry-tilt family so the IC / DSR / PBO read
    is computed identically regardless of where the signal came from.
    """

    by_timestamp: dict[int, list[StrategySample]] = {}
    for sample in samples:
        by_timestamp.setdefault(sample.timestamp_ms, []).append(sample)

    ic_values: list[float] = []
    portfolio_returns: list[float] = []
    period_returns_by_timestamp: dict[int, float] = {}
    turnover_events = 0
    regime_gated_cross_sections = 0
    exit_reason_counts: dict[str, int] = {}
    allowed_timestamps = _allowed_timestamps_for_overlap_mode(
        list(by_timestamp),
        holding_bars=holding_bars,
        overlap_mode=overlap_mode,
    )
    for timestamp in sorted(by_timestamp):
        if timestamp not in allowed_timestamps:
            continue
        group = by_timestamp[timestamp]
        if len(group) < min_cross_section_symbols:
            continue
        if regime_min_dispersion_pct > 0.0 and _signal_dispersion(group) < regime_min_dispersion_pct:
            regime_gated_cross_sections += 1
            continue
        signal_values = [sample.signal for sample in group]
        target_values = [sample.future_return_pct for sample in group]
        ic = spearman_rank_correlation(signal_values, target_values)
        if ic is not None:
            ic_values.append(ic)
        sorted_group = sorted(group, key=lambda sample: sample.signal, reverse=True)
        side_count = max(1, int(len(sorted_group) * max(min(top_fraction, 0.5), 0.01)))
        longs = sorted_group[:side_count]
        shorts = sorted_group[-side_count:]
        gross_return = _mean([sample.long_return_pct for sample in longs]) + _mean(
            [sample.short_return_pct for sample in shorts]
        )
        for sample in longs:
            _increment_count(exit_reason_counts, f"long_{sample.long_exit_reason}")
        for sample in shorts:
            _increment_count(exit_reason_counts, f"short_{sample.short_exit_reason}")
        net_return = gross_return - (2.0 * cost_per_directional_bet_pct)
        portfolio_returns.append(net_return)
        period_returns_by_timestamp[timestamp] = net_return
        turnover_events += 2 * side_count

    return {
        "directional_regime_gated_cross_sections": regime_gated_cross_sections,
        "period_returns_by_timestamp": period_returns_by_timestamp,
        "cross_section_count": len(portfolio_returns),
        "rank_ic_mean": None if not ic_values else _mean(ic_values),
        "rank_ic_t_stat": _t_stat(ic_values),
        "portfolio_mean_return_pct": None if not portfolio_returns else _mean(portfolio_returns),
        "portfolio_sum_return_pct": sum(portfolio_returns),
        "portfolio_sharpe": _sharpe(portfolio_returns, frequency),
        "portfolio_max_drawdown_pct": _max_drawdown(portfolio_returns),
        "portfolio_period_count": len(portfolio_returns),
        "effective_period_count": _effective_sample_count(portfolio_returns, max(holding_bars - 1, 0)),
        "period_count_adjustment_ratio": (
            _effective_sample_count(portfolio_returns, max(holding_bars - 1, 0)) / len(portfolio_returns)
            if portfolio_returns else 0.0
        ),
        "effective_rank_ic_count": _effective_sample_count(ic_values, max(holding_bars - 1, 0)),
        "rank_ic_t_stat_effective": _t_stat_with_effective_count(
            ic_values, _effective_sample_count(ic_values, max(holding_bars - 1, 0))
        ),
        "turnover_events": turnover_events,
        "directional_exit_reason_counts": exit_reason_counts,
    }


def evaluate_cross_sectional_family(
    rows_by_symbol: dict[str, list[list[float]]],
    *,
    family: str,
    frequency: str,
    signal_lookback_bars: int,
    holding_bars: int,
    start_ms: int,
    end_ms: int,
    min_cross_section_symbols: int,
    top_fraction: float,
    cost_per_directional_bet_pct: float,
    overlap_mode: str = DEFAULT_DIRECTIONAL_OVERLAP_MODE,
    exit_mode: str = DEFAULT_DIRECTIONAL_EXIT_MODE,
    take_profit_pct: float = 0.0,
    stop_loss_pct: float = 0.0,
    barrier_vol: BarrierVolConfig | None = None,
    regime_min_dispersion_pct: float = 0.0,
) -> dict[str, object]:
    samples = build_directional_samples(
        rows_by_symbol,
        family=family,
        signal_lookback_bars=signal_lookback_bars,
        holding_bars=holding_bars,
        start_ms=start_ms,
        end_ms=end_ms,
        exit_mode=exit_mode,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        barrier_vol=barrier_vol,
    )
    aggregate = _aggregate_directional_cross_sections(
        samples,
        frequency=frequency,
        holding_bars=holding_bars,
        min_cross_section_symbols=min_cross_section_symbols,
        top_fraction=top_fraction,
        cost_per_directional_bet_pct=cost_per_directional_bet_pct,
        overlap_mode=overlap_mode,
        regime_min_dispersion_pct=regime_min_dispersion_pct,
    )
    return {
        "frequency": frequency,
        "family": family,
        "signal_lookback_bars": signal_lookback_bars,
        "holding_bars": holding_bars,
        "directional_overlap_mode": overlap_mode,
        "directional_exit_mode": exit_mode,
        "directional_take_profit_pct": take_profit_pct,
        "directional_stop_loss_pct": stop_loss_pct,
        **_barrier_vol_fields(barrier_vol),
        "directional_regime_min_dispersion_pct": regime_min_dispersion_pct,
        **aggregate,
        "sample_count": len(samples),
        "cost_per_directional_bet_pct": cost_per_directional_bet_pct,
        "effective_breadth": _effective_breadth(rows_by_symbol),
    }


def evaluate_cross_sectional_carry_tilt(
    rows_by_symbol: dict[str, list[list[float]]],
    funding_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    family: str,
    frequency: str,
    holding_bars: int,
    start_ms: int,
    end_ms: int,
    min_cross_section_symbols: int,
    top_fraction: float,
    cost_per_directional_bet_pct: float,
    overlap_mode: str = DEFAULT_DIRECTIONAL_OVERLAP_MODE,
    regime_min_dispersion_pct: float = 0.0,
    signal_field: str = "funding_rate",
) -> dict[str, object]:
    """S1' new-source kill-test: rank funding (or basis) cross-sectionally against
    forward close-to-close returns. Reuses the shared IC / portfolio aggregation so
    DSR / PBO downstream treat funding exactly like a price signal.
    """

    samples = build_carry_tilt_samples(
        rows_by_symbol,
        funding_by_symbol,
        family=family,
        holding_bars=holding_bars,
        start_ms=start_ms,
        end_ms=end_ms,
        signal_field=signal_field,
    )
    aggregate = _aggregate_directional_cross_sections(
        samples,
        frequency=frequency,
        holding_bars=holding_bars,
        min_cross_section_symbols=min_cross_section_symbols,
        top_fraction=top_fraction,
        cost_per_directional_bet_pct=cost_per_directional_bet_pct,
        overlap_mode=overlap_mode,
        regime_min_dispersion_pct=regime_min_dispersion_pct,
    )
    return {
        "frequency": frequency,
        "family": family,
        "carry_tilt_signal_field": signal_field,
        "signal_lookback_bars": 0,
        "holding_bars": holding_bars,
        "directional_overlap_mode": overlap_mode,
        "directional_exit_mode": "time",
        "directional_regime_min_dispersion_pct": regime_min_dispersion_pct,
        **aggregate,
        "sample_count": len(samples),
        "cost_per_directional_bet_pct": cost_per_directional_bet_pct,
        "effective_breadth": _effective_breadth(rows_by_symbol),
    }


def evaluate_cross_sectional_portfolio_replay(
    rows_by_symbol: dict[str, list[list[float]]],
    *,
    family: str,
    frequency: str,
    signal_lookback_bars: int,
    holding_bars: int,
    start_ms: int,
    end_ms: int,
    min_cross_section_symbols: int,
    top_fraction: float,
    cost_per_directional_bet_pct: float,
    max_open_positions: int = 0,
    overlap_mode: str = DEFAULT_DIRECTIONAL_OVERLAP_MODE,
    exit_mode: str = DEFAULT_DIRECTIONAL_EXIT_MODE,
    take_profit_pct: float = 0.0,
    stop_loss_pct: float = 0.0,
    barrier_vol: BarrierVolConfig | None = None,
    regime_min_dispersion_pct: float = 0.0,
) -> dict[str, object]:
    samples = build_directional_samples(
        rows_by_symbol,
        family=family,
        signal_lookback_bars=signal_lookback_bars,
        holding_bars=holding_bars,
        start_ms=start_ms,
        end_ms=end_ms,
        exit_mode=exit_mode,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        barrier_vol=barrier_vol,
    )
    by_timestamp: dict[int, list[StrategySample]] = {}
    for sample in samples:
        by_timestamp.setdefault(sample.timestamp_ms, []).append(sample)

    timeframe_ms = timeframe_to_ms(frequency)
    holding_ms = max(int(holding_bars), 1) * timeframe_ms
    regime_gated_cross_sections = 0
    allowed_timestamps = _allowed_timestamps_for_overlap_mode(
        list(by_timestamp),
        holding_bars=holding_bars,
        overlap_mode=overlap_mode,
    )
    open_positions: list[dict[str, object]] = []
    closed_by_timestamp: dict[int, list[float]] = {}
    exit_reason_counts: dict[str, int] = {}
    ic_values: list[float] = []
    opened_count = 0
    skipped_count = 0
    cross_section_count = 0
    max_concurrent = 0

    def close_due(timestamp_ms: int) -> None:
        nonlocal open_positions
        still_open: list[dict[str, object]] = []
        for position in open_positions:
            exit_timestamp_ms = int(position["exit_timestamp_ms"])
            if exit_timestamp_ms <= timestamp_ms:
                closed_by_timestamp.setdefault(exit_timestamp_ms, []).append(float(position["net_return_pct"]))
            else:
                still_open.append(position)
        open_positions = still_open

    for timestamp in sorted(by_timestamp):
        close_due(timestamp)
        if timestamp not in allowed_timestamps:
            continue
        group = by_timestamp[timestamp]
        if len(group) < min_cross_section_symbols:
            continue
        if regime_min_dispersion_pct > 0.0 and _signal_dispersion(group) < regime_min_dispersion_pct:
            regime_gated_cross_sections += 1
            continue
        cross_section_count += 1
        signal_values = [sample.signal for sample in group]
        target_values = [sample.future_return_pct for sample in group]
        ic = spearman_rank_correlation(signal_values, target_values)
        if ic is not None:
            ic_values.append(ic)
        sorted_group = sorted(group, key=lambda sample: sample.signal, reverse=True)
        side_count = max(1, int(len(sorted_group) * max(min(top_fraction, 0.5), 0.01)))
        candidate_positions: list[dict[str, object]] = []
        for sample in sorted_group[:side_count]:
            candidate_positions.append(
                {
                    "entry_timestamp_ms": timestamp,
                    "exit_timestamp_ms": timestamp + holding_ms,
                    "symbol": sample.symbol,
                    "side": "long",
                    "signal": sample.signal,
                    "net_return_pct": sample.long_return_pct - cost_per_directional_bet_pct,
                    "exit_reason": f"long_{sample.long_exit_reason}",
                }
            )
        for sample in sorted_group[-side_count:]:
            candidate_positions.append(
                {
                    "entry_timestamp_ms": timestamp,
                    "exit_timestamp_ms": timestamp + holding_ms,
                    "symbol": sample.symbol,
                    "side": "short",
                    "signal": sample.signal,
                    "net_return_pct": sample.short_return_pct - cost_per_directional_bet_pct,
                    "exit_reason": f"short_{sample.short_exit_reason}",
                }
            )
        candidate_positions = sorted(candidate_positions, key=lambda item: abs(float(item["signal"])), reverse=True)
        if max_open_positions > 0:
            available_slots = max(max_open_positions - len(open_positions), 0)
            selected_positions = candidate_positions[:available_slots]
            skipped_count += max(len(candidate_positions) - len(selected_positions), 0)
        else:
            selected_positions = candidate_positions
        open_positions.extend(selected_positions)
        for position in selected_positions:
            _increment_count(exit_reason_counts, str(position["exit_reason"]))
        opened_count += len(selected_positions)
        max_concurrent = max(max_concurrent, len(open_positions))

    for position in open_positions:
        exit_timestamp_ms = int(position["exit_timestamp_ms"])
        closed_by_timestamp.setdefault(exit_timestamp_ms, []).append(float(position["net_return_pct"]))

    capital_slots = max_open_positions if max_open_positions > 0 else max(max_concurrent, 1)
    period_returns_by_timestamp = {
        int(timestamp): sum(values) / capital_slots for timestamp, values in sorted(closed_by_timestamp.items())
    }
    period_returns = list(period_returns_by_timestamp.values())
    closed_trade_returns = [value for values in closed_by_timestamp.values() for value in values]
    win_count = sum(1 for value in closed_trade_returns if value > 0.0)
    return {
        "frequency": frequency,
        "family": family,
        "signal_lookback_bars": signal_lookback_bars,
        "holding_bars": holding_bars,
        "directional_overlap_mode": overlap_mode,
        "directional_exit_mode": exit_mode,
        "directional_take_profit_pct": take_profit_pct,
        "directional_stop_loss_pct": stop_loss_pct,
        **_barrier_vol_fields(barrier_vol),
        "directional_regime_min_dispersion_pct": regime_min_dispersion_pct,
        "directional_regime_gated_cross_sections": regime_gated_cross_sections,
        "period_returns_by_timestamp": period_returns_by_timestamp,
        "directional_evaluation_mode": "portfolio_replay",
        "directional_max_open_positions": max_open_positions,
        "sample_count": len(samples),
        "cross_section_count": cross_section_count,
        "rank_ic_mean": None if not ic_values else _mean(ic_values),
        "rank_ic_t_stat": _t_stat(ic_values),
        "portfolio_mean_return_pct": None if not period_returns else _mean(period_returns),
        "portfolio_sum_return_pct": sum(period_returns),
        "portfolio_sharpe": _sharpe(period_returns, frequency),
        "portfolio_max_drawdown_pct": _max_drawdown(period_returns),
        "portfolio_period_count": len(period_returns),
        "turnover_events": opened_count,
        "directional_exit_reason_counts": exit_reason_counts,
        "cost_per_directional_bet_pct": cost_per_directional_bet_pct,
        "portfolio_replay_closed_trade_count": len(closed_trade_returns),
        "portfolio_replay_skipped_trade_count": skipped_count,
        "portfolio_replay_max_concurrent_positions": max_concurrent,
        "portfolio_replay_capital_slots": capital_slots,
        "portfolio_replay_win_rate": None if not closed_trade_returns else win_count / len(closed_trade_returns),
        "effective_breadth": _effective_breadth(rows_by_symbol),
    }


def evaluate_time_series_momentum(
    rows_by_symbol: dict[str, list[list[float]]],
    *,
    frequency: str,
    signal_lookback_bars: int,
    holding_bars: int,
    start_ms: int,
    end_ms: int,
    cost_per_directional_bet_pct: float,
    overlap_mode: str = DEFAULT_DIRECTIONAL_OVERLAP_MODE,
    exit_mode: str = DEFAULT_DIRECTIONAL_EXIT_MODE,
    take_profit_pct: float = 0.0,
    stop_loss_pct: float = 0.0,
    barrier_vol: BarrierVolConfig | None = None,
) -> dict[str, object]:
    samples = build_directional_samples(
        rows_by_symbol,
        family="ts_mom",
        signal_lookback_bars=signal_lookback_bars,
        holding_bars=holding_bars,
        start_ms=start_ms,
        end_ms=end_ms,
        exit_mode=exit_mode,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        barrier_vol=barrier_vol,
    )
    allowed_timestamps = _allowed_timestamps_for_overlap_mode(
        [sample.timestamp_ms for sample in samples],
        holding_bars=holding_bars,
        overlap_mode=overlap_mode,
    )
    filtered_samples = [sample for sample in samples if sample.timestamp_ms in allowed_timestamps]
    ic = spearman_rank_correlation(
        [sample.signal for sample in filtered_samples],
        [sample.future_return_pct for sample in filtered_samples],
    )
    returns: list[float] = []
    returns_by_timestamp: dict[int, list[float]] = {}
    exit_reason_counts: dict[str, int] = {}
    for sample in filtered_samples:
        if sample.signal == 0.0:
            continue
        direction = 1.0 if sample.signal > 0.0 else -1.0
        directional_return = sample.long_return_pct if direction > 0.0 else sample.short_return_pct
        exit_reason = sample.long_exit_reason if direction > 0.0 else sample.short_exit_reason
        side = "long" if direction > 0.0 else "short"
        _increment_count(exit_reason_counts, f"{side}_{exit_reason}")
        net_return = directional_return - cost_per_directional_bet_pct
        returns.append(net_return)
        returns_by_timestamp.setdefault(int(sample.timestamp_ms), []).append(net_return)
    # Aggregate same-timestamp bets to a portfolio return so PBO can align on the time axis.
    period_returns_by_timestamp = {ts: _mean(values) for ts, values in returns_by_timestamp.items()}
    portfolio_period_returns = list(period_returns_by_timestamp.values())
    effective_period_count = _effective_sample_count(
        portfolio_period_returns, max(holding_bars - 1, 0)
    )
    return {
        "frequency": frequency,
        "family": "ts_mom",
        "signal_lookback_bars": signal_lookback_bars,
        "holding_bars": holding_bars,
        "directional_overlap_mode": overlap_mode,
        "directional_exit_mode": exit_mode,
        "directional_take_profit_pct": take_profit_pct,
        "directional_stop_loss_pct": stop_loss_pct,
        **_barrier_vol_fields(barrier_vol),
        "period_returns_by_timestamp": period_returns_by_timestamp,
        "sample_count": len(samples),
        "evaluated_sample_count": len(filtered_samples),
        "rank_ic_mean": ic,
        "rank_ic_t_stat": None,
        "portfolio_mean_return_pct": None if not portfolio_period_returns else _mean(portfolio_period_returns),
        "portfolio_sum_return_pct": sum(portfolio_period_returns),
        "portfolio_sharpe": _sharpe(portfolio_period_returns, frequency),
        "portfolio_max_drawdown_pct": _max_drawdown(portfolio_period_returns),
        "portfolio_period_count": len(portfolio_period_returns),
        "effective_period_count": effective_period_count,
        "period_count_adjustment_ratio": (
            effective_period_count / len(portfolio_period_returns) if portfolio_period_returns else 0.0
        ),
        "turnover_events": len(returns),
        "directional_exit_reason_counts": exit_reason_counts,
        "cost_per_directional_bet_pct": cost_per_directional_bet_pct,
        "effective_breadth": _effective_breadth(rows_by_symbol),
    }


def normalize_funding_history(raw_rows: list[dict[str, Any]], *, symbol: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in raw_rows:
        timestamp = row.get("timestamp")
        if timestamp is None:
            info = row.get("info") if isinstance(row.get("info"), dict) else {}
            timestamp = info.get("fundingTime") or info.get("time")
        timestamp_ms = int(timestamp) if timestamp is not None else None
        if timestamp_ms is None or timestamp_ms < start_ms or timestamp_ms > end_ms:
            continue
        rate = row.get("fundingRate")
        if rate is None:
            info = row.get("info") if isinstance(row.get("info"), dict) else {}
            rate = info.get("fundingRate")
        info = row.get("info") if isinstance(row.get("info"), dict) else {}
        mark_price = row.get("markPrice") or row.get("mark_price") or info.get("markPrice")
        index_price = row.get("indexPrice") or row.get("index_price") or info.get("indexPrice")
        mark_price_float = _safe_float(mark_price)
        index_price_float = _safe_float(index_price)
        basis_pct = (
            (mark_price_float / index_price_float) - 1.0
            if mark_price_float > 0.0 and index_price_float > 0.0
            else None
        )
        normalized.append(
            {
                "symbol": str(row.get("symbol") or symbol),
                "timestamp_ms": timestamp_ms,
                "funding_rate": _safe_float(rate),
                "mark_price": mark_price_float if mark_price_float > 0.0 else None,
                "index_price": index_price_float if index_price_float > 0.0 else None,
                "basis_pct": basis_pct,
            }
        )
    return sorted(normalized, key=lambda item: int(item["timestamp_ms"]))


def evaluate_carry_family(
    funding_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    cost_per_directional_bet_pct: float,
    model: str = "naive",
    entry_threshold_pct: float = 0.0,
    exit_threshold_pct: float | None = None,
    min_hold_periods: int = 1,
    execution_cost_model: str = DEFAULT_CARRY_EXECUTION_COST_MODEL,
    capital_model: str = DEFAULT_CARRY_CAPITAL_MODEL,
    perp_margin_fraction: float = 1.0,
    basis_tail_stop_pct: float | None = None,
    basis_entry_max_abs_pct: float | None = None,
    maker_order_cost_pct: float | None = None,
    taker_order_cost_pct: float | None = None,
) -> dict[str, object]:
    if model == "threshold_dual_leg":
        return _evaluate_threshold_dual_leg_carry_family(
            funding_by_symbol,
            cost_per_directional_bet_pct=cost_per_directional_bet_pct,
            entry_threshold_pct=entry_threshold_pct,
            exit_threshold_pct=exit_threshold_pct,
            min_hold_periods=min_hold_periods,
            execution_cost_model=execution_cost_model,
            capital_model=capital_model,
            perp_margin_fraction=perp_margin_fraction,
            basis_tail_stop_pct=basis_tail_stop_pct,
            basis_entry_max_abs_pct=basis_entry_max_abs_pct,
            maker_order_cost_pct=maker_order_cost_pct,
            taker_order_cost_pct=taker_order_cost_pct,
        )

    period_returns: list[float] = []
    symbol_summaries: dict[str, dict[str, object]] = {}
    sign_changes = 0
    for symbol, rows in sorted(funding_by_symbol.items()):
        normalized = [row for row in rows if row.get("funding_rate") is not None]
        previous_direction: int | None = None
        symbol_returns: list[float] = []
        for row in normalized:
            rate = _safe_float(row.get("funding_rate"))
            if rate == 0.0:
                continue
            direction = -1 if rate > 0.0 else 1
            funding_capture = abs(rate)
            cost = 0.0
            if previous_direction is None or previous_direction != direction:
                cost = cost_per_directional_bet_pct
                if previous_direction is not None:
                    sign_changes += 1
            previous_direction = direction
            net_return = funding_capture - cost
            period_returns.append(net_return)
            symbol_returns.append(net_return)
        symbol_summaries[symbol] = {
            "sample_count": len(symbol_returns),
            "mean_net_funding_pct": None if not symbol_returns else _mean(symbol_returns),
            "sum_net_funding_pct": sum(symbol_returns),
            "positive_periods": sum(1 for value in symbol_returns if value > 0.0),
        }
    return {
        "frequency": "8h",
        "family": "carry",
        "carry_model": "naive",
        "sample_count": len(period_returns),
        "rank_ic_mean": None,
        "rank_ic_t_stat": None,
        "portfolio_mean_return_pct": None if not period_returns else _mean(period_returns),
        "portfolio_sum_return_pct": sum(period_returns),
        "portfolio_sharpe": _sharpe(period_returns, "8h"),
        "portfolio_max_drawdown_pct": _max_drawdown(period_returns),
        "turnover_events": sign_changes,
        "cost_per_directional_bet_pct": cost_per_directional_bet_pct,
        "carry_execution_cost_model": execution_cost_model,
        "carry_capital_model": capital_model,
        "carry_perp_margin_fraction": perp_margin_fraction,
        "carry_capital_per_perp_notional": _carry_capital_per_perp_notional(capital_model, perp_margin_fraction),
        "by_symbol": symbol_summaries,
        "effective_breadth": {
            "raw_symbol_count": len(funding_by_symbol),
            "effective_breadth": float(len(funding_by_symbol)),
            "avg_abs_pairwise_return_corr": None,
        },
    }


def _evaluate_threshold_dual_leg_carry_family(
    funding_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    cost_per_directional_bet_pct: float,
    entry_threshold_pct: float,
    exit_threshold_pct: float | None,
    min_hold_periods: int,
    execution_cost_model: str,
    capital_model: str,
    perp_margin_fraction: float,
    basis_tail_stop_pct: float | None,
    basis_entry_max_abs_pct: float | None,
    maker_order_cost_pct: float | None,
    taker_order_cost_pct: float | None,
) -> dict[str, object]:
    period_returns: list[float] = []
    symbol_summaries: dict[str, dict[str, object]] = {}
    entry_threshold = max(float(entry_threshold_pct), 0.0)
    exit_threshold = entry_threshold if exit_threshold_pct is None else max(float(exit_threshold_pct), 0.0)
    min_hold = max(int(min_hold_periods), 1)
    order_cost = _carry_order_cost_pct(
        cost_per_directional_bet_pct=cost_per_directional_bet_pct,
        execution_cost_model=execution_cost_model,
    )
    capital_per_perp_notional = _carry_capital_per_perp_notional(capital_model, perp_margin_fraction)
    entry_events = 0
    exit_events = 0
    switch_events = 0
    idle_periods = 0
    invested_periods = 0
    basis_values: list[float] = []
    gross_funding_sum = 0.0
    execution_cost_sum = 0.0
    basis_tail_stop_threshold = None if basis_tail_stop_pct is None else max(float(basis_tail_stop_pct), 0.0)
    basis_entry_max_abs = None if basis_entry_max_abs_pct is None else max(float(basis_entry_max_abs_pct), 0.0)
    basis_tail_stop_events = 0
    basis_entry_blocked_events = 0

    for symbol, rows in sorted(funding_by_symbol.items()):
        normalized = [row for row in rows if row.get("funding_rate") is not None]
        position_direction: int | None = None
        held_periods = 0
        symbol_returns: list[float] = []
        symbol_invested_periods = 0
        symbol_basis_values: list[float] = []
        symbol_gross_funding_sum = 0.0
        symbol_execution_cost_sum = 0.0
        symbol_basis_tail_stop_events = 0
        symbol_basis_entry_blocked_events = 0
        for row in normalized:
            rate = _safe_float(row.get("funding_rate"))
            abs_rate = abs(rate)
            period_gross_funding = 0.0
            period_execution_cost = 0.0
            desired_direction = -1 if rate > 0.0 else 1 if rate < 0.0 else None
            strong_enough = desired_direction is not None and abs_rate >= entry_threshold
            weak_enough = abs_rate < exit_threshold
            basis_pct = row.get("basis_pct")
            basis_value = None if basis_pct is None else _safe_float(basis_pct)
            basis_entry_allowed = (
                basis_entry_max_abs is None
                or basis_value is None
                or abs(basis_value) <= basis_entry_max_abs
            )

            if position_direction is None:
                if strong_enough:
                    if basis_entry_allowed:
                        position_direction = desired_direction
                        held_periods = 0
                        entry_events += 1
                        period_execution_cost += 2.0 * order_cost
                    else:
                        basis_entry_blocked_events += 1
                        symbol_basis_entry_blocked_events += 1
            elif held_periods >= min_hold:
                if strong_enough and desired_direction is not None and desired_direction != position_direction:
                    position_direction = desired_direction
                    held_periods = 0
                    switch_events += 1
                    period_execution_cost += 4.0 * order_cost
                elif weak_enough:
                    position_direction = None
                    held_periods = 0
                    exit_events += 1
                    period_execution_cost += 2.0 * order_cost

            if (
                position_direction is not None
                and basis_tail_stop_threshold is not None
                and basis_value is not None
                and abs(basis_value) >= basis_tail_stop_threshold
            ):
                position_direction = None
                held_periods = 0
                exit_events += 1
                basis_tail_stop_events += 1
                symbol_basis_tail_stop_events += 1
                period_execution_cost += 2.0 * order_cost

            if position_direction is None:
                idle_periods += 1
            elif desired_direction is not None:
                period_gross_funding += abs_rate if position_direction == desired_direction else -abs_rate
                held_periods += 1
                invested_periods += 1
                symbol_invested_periods += 1
                if basis_value is not None:
                    basis_values.append(basis_value)
                    symbol_basis_values.append(basis_value)

            gross_funding_sum += period_gross_funding
            execution_cost_sum += period_execution_cost
            symbol_gross_funding_sum += period_gross_funding
            symbol_execution_cost_sum += period_execution_cost
            period_return = (period_gross_funding - period_execution_cost) / capital_per_perp_notional
            period_returns.append(period_return)
            symbol_returns.append(period_return)

        symbol_basis_tail_loss = _basis_tail_loss_on_capital(symbol_basis_values, capital_per_perp_notional)
        symbol_net_return_sum = sum(symbol_returns)
        symbol_summaries[symbol] = {
            "sample_count": len(symbol_returns),
            "mean_net_funding_pct": None if not symbol_returns else _mean(symbol_returns),
            "sum_net_funding_pct": symbol_net_return_sum,
            "positive_periods": sum(1 for value in symbol_returns if value > 0.0),
            "invested_periods": symbol_invested_periods,
            "utilization_ratio": 0.0 if not symbol_returns else symbol_invested_periods / len(symbol_returns),
            "dual_leg_gross_exposure_periods": 2 * symbol_invested_periods,
            "avg_dual_leg_gross_exposure_pct": 0.0 if not symbol_returns else (2.0 * symbol_invested_periods) / len(symbol_returns),
            "avg_dual_leg_gross_exposure_on_capital_pct": (
                0.0 if not symbol_returns else ((2.0 * symbol_invested_periods) / len(symbol_returns)) / capital_per_perp_notional
            ),
            "gross_funding_return_pct": symbol_gross_funding_sum / capital_per_perp_notional,
            "execution_cost_sum_pct": symbol_execution_cost_sum / capital_per_perp_notional,
            "basis_sample_count": len(symbol_basis_values),
            "basis_avg_abs_pct": None if not symbol_basis_values else _mean([abs(value) for value in symbol_basis_values]),
            "basis_max_abs_pct": None if not symbol_basis_values else max(abs(value) for value in symbol_basis_values),
            "basis_single_tail_loss_on_capital_pct": symbol_basis_tail_loss,
            "basis_single_tail_to_net_ratio": _ratio_or_none(symbol_basis_tail_loss, abs(symbol_net_return_sum)),
            "sum_after_single_basis_tail_pct": (
                None if symbol_basis_tail_loss is None else symbol_net_return_sum - symbol_basis_tail_loss
            ),
            "basis_tail_stop_threshold_pct": basis_tail_stop_threshold,
            "basis_tail_stop_events": symbol_basis_tail_stop_events,
            "basis_entry_max_abs_pct": basis_entry_max_abs,
            "basis_entry_blocked_events": symbol_basis_entry_blocked_events,
        }

    utilization_ratio = 0.0 if not period_returns else invested_periods / len(period_returns)
    turnover_events = entry_events + exit_events + (2 * switch_events)
    break_even_order_cost_pct = None if turnover_events <= 0 else gross_funding_sum / (2.0 * turnover_events)
    normalized_gross_funding_sum = gross_funding_sum / capital_per_perp_notional
    normalized_execution_cost_sum = execution_cost_sum / capital_per_perp_notional
    avg_dual_leg_gross_exposure = 2.0 * utilization_ratio
    net_return_sum = sum(period_returns)
    basis_tail_loss = _basis_tail_loss_on_capital(basis_values, capital_per_perp_notional)
    post_only_economics = _post_only_economics(
        break_even_order_cost_pct=break_even_order_cost_pct,
        gross_funding_sum=gross_funding_sum,
        turnover_events=turnover_events,
        capital_per_perp_notional=capital_per_perp_notional,
        basis_tail_loss_on_capital=basis_tail_loss,
        maker_order_cost_pct=maker_order_cost_pct,
        taker_order_cost_pct=taker_order_cost_pct,
    )
    return {
        "frequency": "8h",
        "family": "carry",
        "carry_model": "threshold_dual_leg",
        "sample_count": len(period_returns),
        "rank_ic_mean": None,
        "rank_ic_t_stat": None,
        "portfolio_mean_return_pct": None if not period_returns else _mean(period_returns),
        "portfolio_sum_return_pct": net_return_sum,
        "portfolio_sharpe": _sharpe(period_returns, "8h"),
        "portfolio_max_drawdown_pct": _max_drawdown(period_returns),
        "turnover_events": turnover_events,
        "cost_per_directional_bet_pct": cost_per_directional_bet_pct,
        "carry_execution_cost_model": execution_cost_model,
        "carry_order_cost_pct": order_cost,
        "carry_capital_model": capital_model,
        "carry_perp_margin_fraction": max(float(perp_margin_fraction), 0.0),
        "carry_capital_per_perp_notional": capital_per_perp_notional,
        "carry_entry_threshold_pct": entry_threshold,
        "carry_exit_threshold_pct": exit_threshold,
        "carry_min_hold_periods": min_hold,
        "carry_entry_events": entry_events,
        "carry_exit_events": exit_events,
        "carry_switch_events": switch_events,
        "carry_idle_periods": idle_periods,
        "carry_invested_periods": invested_periods,
        "carry_utilization_ratio": utilization_ratio,
        "carry_dual_leg_gross_exposure_periods": 2 * invested_periods,
        "carry_avg_dual_leg_gross_exposure_pct": avg_dual_leg_gross_exposure,
        "carry_avg_dual_leg_gross_exposure_on_capital_pct": avg_dual_leg_gross_exposure / capital_per_perp_notional,
        "carry_gross_funding_return_pct": normalized_gross_funding_sum,
        "carry_execution_cost_sum_pct": normalized_execution_cost_sum,
        "carry_cost_to_gross_ratio": (
            None if normalized_gross_funding_sum == 0.0 else normalized_execution_cost_sum / abs(normalized_gross_funding_sum)
        ),
        "carry_break_even_order_cost_pct": break_even_order_cost_pct,
        "basis_sample_count": len(basis_values),
        "basis_avg_abs_pct": None if not basis_values else _mean([abs(value) for value in basis_values]),
        "basis_max_abs_pct": None if not basis_values else max(abs(value) for value in basis_values),
        "basis_single_tail_loss_on_capital_pct": basis_tail_loss,
        "basis_single_tail_to_net_ratio": _ratio_or_none(basis_tail_loss, abs(net_return_sum)),
        "portfolio_sum_after_single_basis_tail_pct": None if basis_tail_loss is None else net_return_sum - basis_tail_loss,
        "basis_tail_stop_threshold_pct": basis_tail_stop_threshold,
        "basis_tail_stop_events": basis_tail_stop_events,
        "basis_entry_max_abs_pct": basis_entry_max_abs,
        "basis_entry_blocked_events": basis_entry_blocked_events,
        **post_only_economics,
        "by_symbol": symbol_summaries,
        "effective_breadth": {
            "raw_symbol_count": len(funding_by_symbol),
            "effective_breadth": float(len(funding_by_symbol)),
            "avg_abs_pairwise_return_corr": None,
        },
    }


def _grid_values(primary: float | int | None, grid: list[float] | list[int] | None, *, default: float | int) -> list[float | int]:
    if grid:
        return list(grid)
    if primary is not None:
        return [primary]
    return [default]


def _carry_order_cost_pct(*, cost_per_directional_bet_pct: float, execution_cost_model: str) -> float:
    cost = max(float(cost_per_directional_bet_pct), 0.0)
    if execution_cost_model == "per_order":
        return cost / 2.0
    return cost


def _carry_capital_per_perp_notional(capital_model: str, perp_margin_fraction: float) -> float:
    if capital_model == "spot_perp_gross":
        return 1.0 + max(float(perp_margin_fraction), 0.0)
    return 1.0


def _basis_tail_loss_on_capital(basis_values: list[float], capital_per_perp_notional: float) -> float | None:
    if not basis_values:
        return None
    return max(abs(value) for value in basis_values) / max(capital_per_perp_notional, 1e-12)


def _post_only_economics(
    *,
    break_even_order_cost_pct: float | None,
    gross_funding_sum: float,
    turnover_events: int,
    capital_per_perp_notional: float,
    basis_tail_loss_on_capital: float | None,
    maker_order_cost_pct: float | None,
    taker_order_cost_pct: float | None,
) -> dict[str, float | bool | None]:
    maker_cost = None if maker_order_cost_pct is None else max(float(maker_order_cost_pct), 0.0)
    taker_cost = None if taker_order_cost_pct is None else max(float(taker_order_cost_pct), 0.0)
    target_after_tail = None
    if basis_tail_loss_on_capital is not None and turnover_events > 0:
        target_after_tail = (
            gross_funding_sum - (basis_tail_loss_on_capital * max(capital_per_perp_notional, 1e-12))
        ) / (2.0 * turnover_events)
    required_for_break_even = _required_maker_fill_rate(
        target_order_cost=break_even_order_cost_pct,
        maker_order_cost=maker_cost,
        taker_order_cost=taker_cost,
    )
    required_for_after_tail = _required_maker_fill_rate(
        target_order_cost=target_after_tail,
        maker_order_cost=maker_cost,
        taker_order_cost=taker_cost,
    )
    return {
        "carry_post_only_maker_order_cost_pct": maker_cost,
        "carry_post_only_taker_order_cost_pct": taker_cost,
        "carry_post_only_target_order_cost_for_break_even_pct": break_even_order_cost_pct,
        "carry_post_only_target_order_cost_after_single_basis_tail_pct": target_after_tail,
        "carry_required_maker_fill_rate_for_break_even": required_for_break_even,
        "carry_required_maker_fill_rate_after_single_basis_tail": required_for_after_tail,
        "carry_post_only_break_even_feasible": (
            None if required_for_break_even is None else required_for_break_even <= 1.0
        ),
        "carry_post_only_after_tail_feasible": (
            None if required_for_after_tail is None else required_for_after_tail <= 1.0
        ),
    }


def _required_maker_fill_rate(
    *,
    target_order_cost: float | None,
    maker_order_cost: float | None,
    taker_order_cost: float | None,
) -> float | None:
    if target_order_cost is None or maker_order_cost is None or taker_order_cost is None:
        return None
    if taker_order_cost <= maker_order_cost:
        return 0.0 if taker_order_cost <= target_order_cost else None
    if target_order_cost >= taker_order_cost:
        return 0.0
    if target_order_cost < maker_order_cost:
        return 1.0 + ((maker_order_cost - target_order_cost) / (taker_order_cost - maker_order_cost))
    return (taker_order_cost - target_order_cost) / (taker_order_cost - maker_order_cost)


def _ratio_or_none(numerator: float | None, denominator: float) -> float | None:
    if numerator is None or denominator <= 0.0:
        return None
    return numerator / denominator


def enrich_funding_with_premium_index_basis(
    funding_rows: list[dict[str, Any]],
    premium_rows: list[list[float]],
    *,
    timeframe_ms: int,
) -> list[dict[str, Any]]:
    if not premium_rows:
        return funding_rows
    premium_by_bucket: dict[int, float] = {}
    for row in premium_rows:
        if len(row) < 5:
            continue
        timestamp = int(row[0])
        close = _safe_float(row[4])
        premium_by_bucket[timestamp // timeframe_ms] = close
    enriched: list[dict[str, Any]] = []
    for row in funding_rows:
        copied = dict(row)
        timestamp = int(copied.get("timestamp_ms") or 0)
        premium_close = premium_by_bucket.get(timestamp // timeframe_ms)
        if premium_close is not None:
            copied["basis_pct"] = premium_close
            copied["basis_source"] = "premium_index"
        enriched.append(copied)
    return enriched


@dataclass
class StrategySelectionScanService:
    settings: Settings
    public_exchange: Any | None = None

    def _fetch_ohlcv_range(
        self,
        *,
        exchange: Any,
        symbol: str,
        frequency: str,
        start_ms: int,
        end_ms: int,
    ) -> list[list[float]]:
        rows: list[list[float]] = []
        cursor = max(start_ms, 0)
        timeframe_ms = timeframe_to_ms(frequency)
        last_timestamp: int | None = None
        while cursor <= end_ms:
            batch = call_with_time_sync_retry(
                exchange,
                exchange.fetch_ohlcv,
                symbol,
                timeframe=frequency,
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
                        _safe_float(row[1]),
                        _safe_float(row[2]),
                        _safe_float(row[3]),
                        _safe_float(row[4]),
                        _safe_float(row[5]),
                    ]
                )
                last_timestamp = timestamp
                added += 1
            if added == 0:
                break
            cursor = int(rows[-1][0]) + timeframe_ms
        return rows

    def _fetch_funding_history(
        self,
        *,
        exchange: Any,
        symbol: str,
        start_ms: int,
        end_ms: int,
    ) -> list[dict[str, Any]]:
        fetch_history = getattr(exchange, "fetch_funding_rate_history", None)
        if not callable(fetch_history):
            return []
        rows: list[dict[str, Any]] = []
        cursor = start_ms
        last_timestamp: int | None = None
        while cursor <= end_ms:
            batch = call_with_time_sync_retry(
                exchange,
                fetch_history,
                symbol,
                since=cursor,
                limit=1000,
            )
            if not batch:
                break
            normalized = normalize_funding_history(batch, symbol=symbol, start_ms=start_ms, end_ms=end_ms)
            added = 0
            for row in normalized:
                timestamp = int(row["timestamp_ms"])
                if last_timestamp is not None and timestamp <= last_timestamp:
                    continue
                rows.append(row)
                last_timestamp = timestamp
                added += 1
            if added == 0:
                break
            cursor = int(rows[-1]["timestamp_ms"]) + 1
        return rows

    def _fetch_premium_index_range(
        self,
        *,
        exchange: Any,
        symbol: str,
        frequency: str,
        start_ms: int,
        end_ms: int,
    ) -> list[list[float]]:
        fetch_premium = getattr(exchange, "fetch_premium_index_ohlcv", None)
        if not callable(fetch_premium):
            return []
        rows: list[list[float]] = []
        cursor = max(start_ms, 0)
        timeframe_ms = timeframe_to_ms(frequency)
        last_timestamp: int | None = None
        while cursor <= end_ms:
            batch = call_with_time_sync_retry(
                exchange,
                fetch_premium,
                symbol,
                timeframe=frequency,
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
                        _safe_float(row[1]),
                        _safe_float(row[2]),
                        _safe_float(row[3]),
                        _safe_float(row[4]),
                        _safe_float(row[5]) if len(row) > 5 else 0.0,
                    ]
                )
                last_timestamp = timestamp
                added += 1
            if added == 0:
                break
            cursor = int(rows[-1][0]) + timeframe_ms
        return rows

    def run(
        self,
        *,
        symbols_filter: list[str] | None,
        frequencies: list[str],
        families: list[str],
        start: datetime | None,
        end: datetime | None,
        lookback_days: int,
        signal_lookback_bars: int,
        holding_bars: int,
        min_cross_section_symbols: int,
        top_fraction: float,
        signal_lookback_grid_bars: list[int] | None = None,
        holding_grid_bars: list[int] | None = None,
        directional_overlap_mode: str = DEFAULT_DIRECTIONAL_OVERLAP_MODE,
        directional_evaluation_mode: str = DEFAULT_DIRECTIONAL_EVALUATION_MODE,
        directional_max_open_positions: int = 0,
        directional_exit_mode: str = DEFAULT_DIRECTIONAL_EXIT_MODE,
        directional_take_profit_pct: float = 0.0,
        directional_stop_loss_pct: float = 0.0,
        directional_barrier_vol_lookback_bars: int = DEFAULT_DIRECTIONAL_BARRIER_VOL_LOOKBACK_BARS,
        directional_take_profit_sigma: float = 0.0,
        directional_stop_loss_sigma: float = 0.0,
        directional_regime_min_dispersion_pct: float = 0.0,
        directional_purged_cv_folds: int = DEFAULT_DIRECTIONAL_PURGED_CV_FOLDS,
        directional_embargo_bars: int = DEFAULT_DIRECTIONAL_EMBARGO_BARS,
        carry_model: str = "naive",
        carry_entry_threshold_pct: float = 0.0,
        carry_exit_threshold_pct: float | None = None,
        carry_min_hold_periods: int = 1,
        carry_entry_threshold_grid_pct: list[float] | None = None,
        carry_exit_threshold_grid_pct: list[float] | None = None,
        carry_min_hold_grid: list[int] | None = None,
        carry_basis_source: str = DEFAULT_CARRY_BASIS_SOURCE,
        carry_execution_cost_model: str = DEFAULT_CARRY_EXECUTION_COST_MODEL,
        carry_capital_model: str = DEFAULT_CARRY_CAPITAL_MODEL,
        carry_perp_margin_fraction: float = 1.0,
        carry_basis_tail_stop_pct: float | None = None,
        carry_basis_entry_max_abs_pct: float | None = None,
        carry_maker_order_cost_pct: float | None = None,
        carry_taker_order_cost_pct: float | None = None,
        carry_tilt_signal_field: str = "funding_rate",
        holdout_role: str = "discovery",
    ) -> dict[str, object]:
        exchange = self.public_exchange or build_exchange(self.settings, private=False)
        markets = call_with_time_sync_retry(exchange, exchange.load_markets)
        configured_symbols = tuple(symbols_filter) if symbols_filter else self.settings.symbols
        resolved_symbols = resolve_market_symbols(markets, configured_symbols, self.settings)
        scan_end = (end or DEFAULT_DISCOVERY_END_UTC).astimezone(timezone.utc)
        scan_start = (start or (scan_end - timedelta(days=max(lookback_days, 1)))).astimezone(timezone.utc)
        start_ms = int(scan_start.timestamp() * 1000)
        end_ms = int(scan_end.timestamp() * 1000)
        cost_per_directional_bet_pct = 2.0 * (
            max(float(self.settings.estimated_fee_pct), 0.0) + max(float(self.settings.estimated_slippage_pct), 0.0)
        )
        directional_barrier_vol = BarrierVolConfig(
            lookback_bars=max(int(directional_barrier_vol_lookback_bars), 0),
            take_profit_sigma=max(float(directional_take_profit_sigma), 0.0),
            stop_loss_sigma=max(float(directional_stop_loss_sigma), 0.0),
        )
        directional_regime_dispersion = max(float(directional_regime_min_dispersion_pct), 0.0)
        cells: list[dict[str, object]] = []
        fetch_summary: dict[str, dict[str, int]] = {}
        signal_lookback_values = [int(value) for value in _grid_values(signal_lookback_bars, signal_lookback_grid_bars, default=12)]
        holding_values = [int(value) for value in _grid_values(holding_bars, holding_grid_bars, default=1)]

        directional_families = [family for family in families if family in {"xs_mom", "xs_rev", "ts_mom"}]
        carry_tilt_families = [family for family in families if family in {"xs_funding", "xs_funding_rev"}]
        carry_tilt_funding_by_symbol: dict[str, list[dict[str, Any]]] = {}
        if carry_tilt_families:
            # As-of join needs a settlement before the first bar; fetch a small
            # funding buffer ahead of the holdout window so leading bars are usable.
            funding_lookback_ms = timeframe_to_ms("8h") * 3
            carry_tilt_funding_by_symbol = {
                symbol: self._fetch_funding_history(
                    exchange=exchange,
                    symbol=symbol,
                    start_ms=start_ms - funding_lookback_ms,
                    end_ms=end_ms,
                )
                for symbol in resolved_symbols
            }
            fetch_summary["carry_tilt_funding"] = {
                symbol: len(rows) for symbol, rows in carry_tilt_funding_by_symbol.items()
            }
        for frequency in frequencies:
            if not directional_families and not carry_tilt_families:
                continue
            timeframe_ms = timeframe_to_ms(frequency)
            fetch_start_ms = start_ms - (max(max(signal_lookback_values), 1) * timeframe_ms)
            fetch_end_ms = end_ms + (max(max(holding_values), 1) * timeframe_ms)
            rows_by_symbol: dict[str, list[list[float]]] = {}
            for symbol in resolved_symbols:
                rows_by_symbol[symbol] = self._fetch_ohlcv_range(
                    exchange=exchange,
                    symbol=symbol,
                    frequency=frequency,
                    start_ms=fetch_start_ms,
                    end_ms=fetch_end_ms,
                )
            fetch_summary[frequency] = {symbol: len(rows) for symbol, rows in rows_by_symbol.items()}
            for directional_signal_lookback in signal_lookback_values:
                for directional_holding in holding_values:
                    for family in directional_families:
                        if family in {"xs_mom", "xs_rev"}:
                            evaluator = (
                                evaluate_cross_sectional_portfolio_replay
                                if directional_evaluation_mode == "portfolio_replay"
                                else evaluate_cross_sectional_family
                            )
                            kwargs: dict[str, object] = {}
                            if directional_evaluation_mode == "portfolio_replay":
                                kwargs["max_open_positions"] = directional_max_open_positions
                            cell = evaluator(
                                rows_by_symbol,
                                family=family,
                                frequency=frequency,
                                signal_lookback_bars=directional_signal_lookback,
                                holding_bars=directional_holding,
                                start_ms=start_ms,
                                end_ms=end_ms,
                                min_cross_section_symbols=min_cross_section_symbols,
                                top_fraction=top_fraction,
                                cost_per_directional_bet_pct=cost_per_directional_bet_pct,
                                overlap_mode=directional_overlap_mode,
                                exit_mode=directional_exit_mode,
                                take_profit_pct=directional_take_profit_pct,
                                stop_loss_pct=directional_stop_loss_pct,
                                barrier_vol=directional_barrier_vol,
                                regime_min_dispersion_pct=directional_regime_dispersion,
                                **kwargs,
                            )
                            _attach_directional_purged_cv(
                                cell,
                                rows_by_symbol,
                                family=family,
                                frequency=frequency,
                                signal_lookback_bars=directional_signal_lookback,
                                holding_bars=directional_holding,
                                start_ms=start_ms,
                                end_ms=end_ms,
                                min_cross_section_symbols=min_cross_section_symbols,
                                top_fraction=top_fraction,
                                cost_per_directional_bet_pct=cost_per_directional_bet_pct,
                                overlap_mode=directional_overlap_mode,
                                evaluation_mode=directional_evaluation_mode,
                                max_open_positions=directional_max_open_positions,
                                exit_mode=directional_exit_mode,
                                take_profit_pct=directional_take_profit_pct,
                                stop_loss_pct=directional_stop_loss_pct,
                                barrier_vol=directional_barrier_vol,
                                regime_min_dispersion_pct=directional_regime_dispersion,
                                fold_count=directional_purged_cv_folds,
                                embargo_bars=directional_embargo_bars,
                            )
                            cells.append(cell)
                        elif family == "ts_mom":
                            cell = evaluate_time_series_momentum(
                                rows_by_symbol,
                                frequency=frequency,
                                signal_lookback_bars=directional_signal_lookback,
                                holding_bars=directional_holding,
                                start_ms=start_ms,
                                end_ms=end_ms,
                                cost_per_directional_bet_pct=cost_per_directional_bet_pct,
                                overlap_mode=directional_overlap_mode,
                                exit_mode=directional_exit_mode,
                                take_profit_pct=directional_take_profit_pct,
                                stop_loss_pct=directional_stop_loss_pct,
                                barrier_vol=directional_barrier_vol,
                            )
                            _attach_directional_purged_cv(
                                cell,
                                rows_by_symbol,
                                family=family,
                                frequency=frequency,
                                signal_lookback_bars=directional_signal_lookback,
                                holding_bars=directional_holding,
                                start_ms=start_ms,
                                end_ms=end_ms,
                                min_cross_section_symbols=min_cross_section_symbols,
                                top_fraction=top_fraction,
                                cost_per_directional_bet_pct=cost_per_directional_bet_pct,
                                overlap_mode=directional_overlap_mode,
                                evaluation_mode=directional_evaluation_mode,
                                max_open_positions=directional_max_open_positions,
                                exit_mode=directional_exit_mode,
                                take_profit_pct=directional_take_profit_pct,
                                stop_loss_pct=directional_stop_loss_pct,
                                barrier_vol=directional_barrier_vol,
                                regime_min_dispersion_pct=directional_regime_dispersion,
                                fold_count=directional_purged_cv_folds,
                                embargo_bars=directional_embargo_bars,
                            )
                            cells.append(cell)
            for directional_holding in holding_values:
                for family in carry_tilt_families:
                    cells.append(
                        evaluate_cross_sectional_carry_tilt(
                            rows_by_symbol,
                            carry_tilt_funding_by_symbol,
                            family=family,
                            frequency=frequency,
                            holding_bars=directional_holding,
                            start_ms=start_ms,
                            end_ms=end_ms,
                            min_cross_section_symbols=min_cross_section_symbols,
                            top_fraction=top_fraction,
                            cost_per_directional_bet_pct=cost_per_directional_bet_pct,
                            overlap_mode=directional_overlap_mode,
                            regime_min_dispersion_pct=directional_regime_dispersion,
                            signal_field=carry_tilt_signal_field,
                        )
                    )

        if "carry" in families:
            funding_by_symbol = {
                symbol: self._fetch_funding_history(
                    exchange=exchange,
                    symbol=symbol,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
                for symbol in resolved_symbols
            }
            premium_fetch_summary: dict[str, int] = {}
            if carry_basis_source == "premium_index":
                premium_timeframe_ms = timeframe_to_ms("8h")
                for symbol in resolved_symbols:
                    premium_rows = self._fetch_premium_index_range(
                        exchange=exchange,
                        symbol=symbol,
                        frequency="8h",
                        start_ms=start_ms,
                        end_ms=end_ms,
                    )
                    premium_fetch_summary[symbol] = len(premium_rows)
                    funding_by_symbol[symbol] = enrich_funding_with_premium_index_basis(
                        funding_by_symbol[symbol],
                        premium_rows,
                        timeframe_ms=premium_timeframe_ms,
                    )
                fetch_summary["premium_index_8h"] = premium_fetch_summary
            if carry_model == "threshold_dual_leg" and (
                carry_entry_threshold_grid_pct or carry_exit_threshold_grid_pct or carry_min_hold_grid
            ):
                for entry_threshold in _grid_values(carry_entry_threshold_pct, carry_entry_threshold_grid_pct, default=0.0):
                    for exit_threshold in _grid_values(carry_exit_threshold_pct, carry_exit_threshold_grid_pct, default=entry_threshold):
                        for min_hold in _grid_values(carry_min_hold_periods, carry_min_hold_grid, default=1):
                            cells.append(
                                evaluate_carry_family(
                                    funding_by_symbol,
                                    cost_per_directional_bet_pct=cost_per_directional_bet_pct,
                                    model=carry_model,
                                    entry_threshold_pct=float(entry_threshold),
                                    exit_threshold_pct=float(exit_threshold),
                                    min_hold_periods=int(min_hold),
                                    execution_cost_model=carry_execution_cost_model,
                                    capital_model=carry_capital_model,
                                    perp_margin_fraction=carry_perp_margin_fraction,
                                    basis_tail_stop_pct=carry_basis_tail_stop_pct,
                                    basis_entry_max_abs_pct=carry_basis_entry_max_abs_pct,
                                    maker_order_cost_pct=carry_maker_order_cost_pct,
                                    taker_order_cost_pct=carry_taker_order_cost_pct,
                                )
                            )
            else:
                cells.append(
                    evaluate_carry_family(
                        funding_by_symbol,
                        cost_per_directional_bet_pct=cost_per_directional_bet_pct,
                        model=carry_model,
                        entry_threshold_pct=carry_entry_threshold_pct,
                        exit_threshold_pct=carry_exit_threshold_pct,
                        min_hold_periods=carry_min_hold_periods,
                        execution_cost_model=carry_execution_cost_model,
                        capital_model=carry_capital_model,
                        perp_margin_fraction=carry_perp_margin_fraction,
                        basis_tail_stop_pct=carry_basis_tail_stop_pct,
                        basis_entry_max_abs_pct=carry_basis_entry_max_abs_pct,
                        maker_order_cost_pct=carry_maker_order_cost_pct,
                        taker_order_cost_pct=carry_taker_order_cost_pct,
                    )
                )

        directional_cells = [cell for cell in cells if cell.get("family") in {"xs_mom", "xs_rev", "ts_mom"}]
        directional_deflated_sharpe = compute_directional_deflated_sharpe(directional_cells)
        directional_pbo = compute_directional_pbo(directional_cells)
        # Carry-tilt (funding-as-feature) is a separate experiment; deflate it over
        # its own trial set so the multiple-testing penalty is not diluted by the
        # price-signal grid.
        carry_tilt_cells = [cell for cell in cells if cell.get("family") in {"xs_funding", "xs_funding_rev"}]
        carry_tilt_deflated_sharpe = compute_directional_deflated_sharpe(carry_tilt_cells)
        carry_tilt_pbo = compute_directional_pbo(carry_tilt_cells)
        # period_returns_by_timestamp is an in-memory series for DSR/PBO only; drop it
        # before serialization to keep artifacts compact.
        for cell in cells:
            cell.pop("period_returns_by_timestamp", None)

        ranked_cells = sorted(
            cells,
            key=lambda cell: (
                -1e18 if cell.get("portfolio_sharpe") is None else float(cell["portfolio_sharpe"]),
                -1e18 if cell.get("portfolio_sum_return_pct") is None else float(cell["portfolio_sum_return_pct"]),
            ),
            reverse=True,
        )
        best_cell = ranked_cells[0] if ranked_cells else None
        return {
            "version": STRATEGY_SELECTION_VERSION,
            "holdout_role": holdout_role,
            "sample_window_start_utc": scan_start.isoformat(),
            "sample_window_end_utc": scan_end.isoformat(),
            "symbols": list(resolved_symbols),
            "frequencies": list(frequencies),
            "families": list(families),
            "signal_lookback_bars": signal_lookback_bars,
            "holding_bars": holding_bars,
            "signal_lookback_grid_bars": signal_lookback_grid_bars,
            "holding_grid_bars": holding_grid_bars,
            "directional_overlap_mode": directional_overlap_mode,
            "directional_evaluation_mode": directional_evaluation_mode,
            "directional_max_open_positions": directional_max_open_positions,
            "directional_exit_mode": directional_exit_mode,
            "directional_take_profit_pct": directional_take_profit_pct,
            "directional_stop_loss_pct": directional_stop_loss_pct,
            "directional_barrier_vol_lookback_bars": directional_barrier_vol.lookback_bars,
            "directional_take_profit_sigma": directional_barrier_vol.take_profit_sigma,
            "directional_stop_loss_sigma": directional_barrier_vol.stop_loss_sigma,
            "directional_regime_min_dispersion_pct": directional_regime_dispersion,
            "directional_purged_cv_folds": directional_purged_cv_folds,
            "directional_embargo_bars": directional_embargo_bars,
            "min_cross_section_symbols": min_cross_section_symbols,
            "top_fraction": top_fraction,
            "carry_model": carry_model,
            "carry_entry_threshold_pct": carry_entry_threshold_pct,
            "carry_exit_threshold_pct": carry_exit_threshold_pct,
            "carry_min_hold_periods": carry_min_hold_periods,
            "carry_entry_threshold_grid_pct": carry_entry_threshold_grid_pct,
            "carry_exit_threshold_grid_pct": carry_exit_threshold_grid_pct,
            "carry_min_hold_grid": carry_min_hold_grid,
            "carry_basis_source": carry_basis_source,
            "carry_execution_cost_model": carry_execution_cost_model,
            "carry_capital_model": carry_capital_model,
            "carry_perp_margin_fraction": carry_perp_margin_fraction,
            "carry_basis_tail_stop_pct": carry_basis_tail_stop_pct,
            "carry_basis_entry_max_abs_pct": carry_basis_entry_max_abs_pct,
            "carry_maker_order_cost_pct": carry_maker_order_cost_pct,
            "carry_taker_order_cost_pct": carry_taker_order_cost_pct,
            "cost_per_directional_bet_pct": cost_per_directional_bet_pct,
            "fetch_summary": fetch_summary,
            "cells": ranked_cells,
            "best_cell": best_cell,
            "decision": _decision_from_best_cell(best_cell),
            "directional_deflated_sharpe": directional_deflated_sharpe,
            "directional_pbo": directional_pbo,
            "carry_tilt_signal_field": carry_tilt_signal_field,
            "carry_tilt_deflated_sharpe": carry_tilt_deflated_sharpe,
            "carry_tilt_pbo": carry_tilt_pbo,
        }


def _decision_from_best_cell(best_cell: dict[str, object] | None) -> dict[str, object]:
    if best_cell is None:
        return {"status": "no_data", "next_step": "fix_data_or_fetch_layer"}
    family = str(best_cell.get("family") or "")
    sum_return = best_cell.get("portfolio_sum_return_pct")
    mean_return = best_cell.get("portfolio_mean_return_pct")
    if sum_return is None or float(sum_return) <= 0.0 or mean_return is None or float(mean_return) <= 0.0:
        return {
            "status": "no_positive_cell",
            "next_step": "do_not_enter_s2_or_live; expand data/frequency/features before promotion",
        }
    if family == "carry":
        return {
            "status": "carry_candidate",
            "next_step": "run S-CARRY funding history replay with explicit hedge and basis risk model",
        }
    return {
        "status": "prediction_family_candidate",
        "next_step": "run S1.1/S1.2 and model work only on the winning frequency/family",
    }
