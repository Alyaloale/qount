"""Research-only active positive-basis capture state machine.

The first trial deliberately supports one executable direction: long spot and
short perpetual when a positive basis is unusually wide.  It uses only data
available at the close of the decision bar and keeps the two-leg PnL separate
from execution costs and funding cash flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Iterable, Sequence

from qount.contracts import canonical_hash
from qount.grid.data import Bar, Funding


ACTIVE_BASIS_SCHEMA_VERSION = "active_basis_capture_trial_v0.1"


def _cost_model_payload(config: ActiveBasisConfig) -> dict[str, Any]:
    return {
        "status": "incomplete",
        "modeled_components": {
            "spot_fee_pct": config.spot_fee_pct,
            "perp_fee_pct": config.perp_fee_pct,
            "spot_slippage_pct": config.spot_slippage_pct,
            "perp_slippage_pct": config.perp_slippage_pct,
            "legging_cost_pct": config.legging_cost_pct,
        },
        "unmodeled_components": [
            "collateral_opportunity_cost",
            "basis_tail_insurance",
            "authenticated_real_fill_and_legging_samples",
        ],
        "complete_executable_cost_model": False,
    }


@dataclass(frozen=True)
class ActiveBasisConfig:
    basis_lookback_days: int = 30
    funding_lookback_days: int = 7
    entry_basis_z: float = 1.0
    exit_basis_z: float = 0.25
    funding_threshold_annualized: float = 0.20
    max_holding_days: int = 10
    adverse_basis_z: float = 2.5
    min_funding_settlements_per_day: int = 3
    spot_fee_pct: float = 0.0010
    perp_fee_pct: float = 0.0004
    spot_slippage_pct: float = 0.0002
    perp_slippage_pct: float = 0.0002
    legging_cost_pct: float = 0.0005
    gross_capital_fraction: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "basis_lookback_days": self.basis_lookback_days,
            "funding_lookback_days": self.funding_lookback_days,
            "entry_basis_z": self.entry_basis_z,
            "exit_basis_z": self.exit_basis_z,
            "funding_threshold_annualized": self.funding_threshold_annualized,
            "max_holding_days": self.max_holding_days,
            "adverse_basis_z": self.adverse_basis_z,
            "min_funding_settlements_per_day": self.min_funding_settlements_per_day,
            "spot_fee_pct": self.spot_fee_pct,
            "perp_fee_pct": self.perp_fee_pct,
            "spot_slippage_pct": self.spot_slippage_pct,
            "perp_slippage_pct": self.perp_slippage_pct,
            "legging_cost_pct": self.legging_cost_pct,
            "gross_capital_fraction": self.gross_capital_fraction,
        }

    def validate(self) -> None:
        if self.basis_lookback_days < 2 or self.funding_lookback_days < 1:
            raise ValueError("active_basis_lookback_invalid")
        if not 0.0 < self.exit_basis_z < self.entry_basis_z:
            raise ValueError("active_basis_z_thresholds_invalid")
        if self.funding_threshold_annualized <= 0.0:
            raise ValueError("active_basis_funding_threshold_invalid")
        if self.max_holding_days < 1 or self.adverse_basis_z <= self.entry_basis_z:
            raise ValueError("active_basis_exit_config_invalid")
        if self.min_funding_settlements_per_day < 1:
            raise ValueError("active_basis_funding_coverage_invalid")
        if self.gross_capital_fraction <= 0.0 or self.gross_capital_fraction > 1.0:
            raise ValueError("active_basis_gross_capital_invalid")


@dataclass(frozen=True)
class DailyBasisBar:
    ts_ms: int
    spot_close: float
    perp_close: float
    basis_pct: float
    funding_rate_sum: float
    funding_settlement_count: int

    @property
    def date(self) -> date:
        return datetime.fromtimestamp(self.ts_ms / 1000.0, UTC).date()


@dataclass(frozen=True)
class BasisFeatures:
    index: int
    basis_z: float | None
    funding_ma_annualized: float | None
    funding_complete: bool


def build_daily_basis_series(
    spot_bars: Sequence[Bar],
    perp_bars: Sequence[Bar],
    funding_rows: Sequence[Funding],
) -> list[DailyBasisBar]:
    """Align spot/perp daily closes and aggregate funding by UTC date."""

    spot_by_date = {
        datetime.fromtimestamp(bar.ts_ms / 1000.0, UTC).date(): bar
        for bar in spot_bars
        if bar.close > 0.0
    }
    perp_by_date = {
        datetime.fromtimestamp(bar.ts_ms / 1000.0, UTC).date(): bar
        for bar in perp_bars
        if bar.close > 0.0
    }
    funding_by_date: dict[date, list[float]] = {}
    for row in funding_rows:
        funding_date = datetime.fromtimestamp(row.ts_ms / 1000.0, UTC).date()
        funding_by_date.setdefault(funding_date, []).append(float(row.rate))

    rows: list[DailyBasisBar] = []
    for current_date in sorted(set(spot_by_date) & set(perp_by_date)):
        spot = spot_by_date[current_date]
        perp = perp_by_date[current_date]
        funding = funding_by_date.get(current_date, [])
        rows.append(
            DailyBasisBar(
                ts_ms=spot.ts_ms,
                spot_close=float(spot.close),
                perp_close=float(perp.close),
                basis_pct=(float(perp.close) - float(spot.close)) / float(spot.close),
                funding_rate_sum=sum(funding),
                funding_settlement_count=len(funding),
            )
        )
    return rows


def build_features(
    series: Sequence[DailyBasisBar],
    config: ActiveBasisConfig,
) -> list[BasisFeatures]:
    config.validate()
    features: list[BasisFeatures] = []
    for index, row in enumerate(series):
        basis_z: float | None = None
        start = index - config.basis_lookback_days
        if start >= 0:
            history = [item.basis_pct for item in series[start:index]]
            mean = sum(history) / len(history)
            variance = sum((value - mean) ** 2 for value in history) / max(len(history) - 1, 1)
            std = math.sqrt(max(variance, 0.0))
            if std > 0.0:
                basis_z = (row.basis_pct - mean) / std

        funding_start = index - config.funding_lookback_days + 1
        if funding_start >= 0:
            funding_window = series[funding_start : index + 1]
            funding_ma = sum(item.funding_rate_sum for item in funding_window) / len(funding_window)
            funding_ma_annualized = funding_ma * 365.0
            funding_complete = all(
                item.funding_settlement_count >= config.min_funding_settlements_per_day
                for item in funding_window
            )
        else:
            funding_ma_annualized = None
            funding_complete = False

        features.append(
            BasisFeatures(
                index=index,
                basis_z=basis_z,
                funding_ma_annualized=(
                    funding_ma_annualized if funding_ma_annualized is not None else None
                ),
                funding_complete=funding_complete,
            )
        )
    return features


def _transition_cost(config: ActiveBasisConfig) -> float:
    """Cost of opening or closing both 0.5-notional legs."""

    leg_cost = 0.5 * (
        config.spot_fee_pct
        + config.perp_fee_pct
        + config.spot_slippage_pct
        + config.perp_slippage_pct
    )
    return leg_cost + config.legging_cost_pct


def _max_drawdown(nav: Sequence[float]) -> float:
    peak = 1.0
    worst = 0.0
    for value in nav:
        peak = max(peak, value)
        if peak > 0.0:
            worst = min(worst, value / peak - 1.0)
    return worst


def _annualized_sharpe(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance <= 0.0:
        return None
    return mean / math.sqrt(variance) * math.sqrt(365.0)


def _summary(
    nav: Sequence[float],
    daily_returns: Sequence[float],
    *,
    market_pnl: float,
    funding_pnl: float,
    execution_cost: float,
    trades: Sequence[dict[str, Any]],
    funding_complete_days: int,
    total_days: int,
) -> dict[str, Any]:
    return {
        "start_nav": nav[0] if nav else 1.0,
        "end_nav": nav[-1] if nav else 1.0,
        "total_return": (nav[-1] - 1.0) if nav else 0.0,
        "max_drawdown": _max_drawdown(nav),
        "annualized_sharpe": _annualized_sharpe(daily_returns),
        "market_pnl": market_pnl,
        "funding_pnl": funding_pnl,
        "execution_cost": execution_cost,
        "trade_count": len(trades),
        "positive_trade_count": sum(1 for trade in trades if trade["net_return"] > 0.0),
        "funding_coverage": funding_complete_days / total_days if total_days else 0.0,
        "active_days": sum(1 for value in daily_returns if value != 0.0),
        "trades": list(trades),
    }


def _simulate(
    series: Sequence[DailyBasisBar],
    features: Sequence[BasisFeatures],
    config: ActiveBasisConfig,
    *,
    start_index: int,
    require_basis_entry: bool,
    use_basis_exit: bool,
) -> dict[str, Any]:
    nav = [1.0]
    daily_returns: list[float] = []
    trades: list[dict[str, Any]] = []
    position_open = False
    entry_index: int | None = None
    trade_return = 0.0
    market_pnl = 0.0
    funding_pnl = 0.0
    execution_cost = 0.0
    transition_cost = _transition_cost(config) * config.gross_capital_fraction
    complete_days = 0

    for index in range(start_index, len(series)):
        row = series[index]
        feature = features[index]
        previous_nav = nav[-1]
        period_pnl = 0.0
        if feature.funding_complete:
            complete_days += 1

        if position_open and index > start_index:
            previous = series[index - 1]
            spot_return = row.spot_close / previous.spot_close - 1.0
            perp_return = row.perp_close / previous.perp_close - 1.0
            period_market_pnl = 0.5 * config.gross_capital_fraction * (spot_return - perp_return)
            period_funding_pnl = 0.5 * config.gross_capital_fraction * row.funding_rate_sum
            period_pnl += period_market_pnl + period_funding_pnl
            market_pnl += period_market_pnl
            funding_pnl += period_funding_pnl
            trade_return += period_market_pnl + period_funding_pnl

        nav.append(previous_nav + period_pnl)
        daily_returns.append(nav[-1] - previous_nav)

        exit_reason: str | None = None
        if position_open and entry_index is not None:
            held_days = index - entry_index
            if use_basis_exit and feature.basis_z is not None and feature.basis_z <= config.exit_basis_z:
                exit_reason = "basis_reverted"
            elif feature.funding_ma_annualized is not None and feature.funding_ma_annualized <= 0.0:
                exit_reason = "funding_sign_flip"
            elif use_basis_exit and feature.basis_z is not None and feature.basis_z >= config.adverse_basis_z:
                exit_reason = "adverse_basis_expansion"
            elif held_days >= config.max_holding_days:
                exit_reason = "max_holding_days"
            if exit_reason is not None:
                nav[-1] -= transition_cost
                daily_returns[-1] -= transition_cost
                execution_cost += transition_cost
                trade_return -= transition_cost
                trades.append(
                    {
                        "entry_date": series[entry_index].date.isoformat(),
                        "exit_date": row.date.isoformat(),
                        "holding_days": held_days,
                        "entry_basis_pct": series[entry_index].basis_pct,
                        "exit_basis_pct": row.basis_pct,
                        "net_return": trade_return,
                        "exit_reason": exit_reason,
                    }
                )
                position_open = False
                entry_index = None
                trade_return = 0.0

        if not position_open and index >= start_index:
            basis_ok = (
                feature.basis_z is not None
                and series[index].basis_pct > 0.0
                and feature.basis_z >= config.entry_basis_z
            )
            funding_ok = (
                feature.funding_complete
                and feature.funding_ma_annualized is not None
                and feature.funding_ma_annualized >= config.funding_threshold_annualized
            )
            if funding_ok and (basis_ok if require_basis_entry else True):
                nav[-1] -= transition_cost
                daily_returns[-1] -= transition_cost
                execution_cost += transition_cost
                position_open = True
                entry_index = index
                trade_return = -transition_cost

    if position_open and entry_index is not None:
        row = series[-1]
        nav[-1] -= transition_cost
        daily_returns[-1] -= transition_cost
        execution_cost += transition_cost
        trade_return -= transition_cost
        trades.append(
            {
                "entry_date": series[entry_index].date.isoformat(),
                "exit_date": row.date.isoformat(),
                "holding_days": len(series) - 1 - entry_index,
                "entry_basis_pct": series[entry_index].basis_pct,
                "exit_basis_pct": row.basis_pct,
                "net_return": trade_return,
                "exit_reason": "sample_end",
            }
        )

    return _summary(
        nav,
        daily_returns,
        market_pnl=market_pnl,
        funding_pnl=funding_pnl,
        execution_cost=execution_cost,
        trades=trades,
        funding_complete_days=complete_days,
        total_days=max(len(series) - start_index, 0),
    )


def evaluate_active_basis(
    series: Sequence[DailyBasisBar],
    *,
    config: ActiveBasisConfig | None = None,
    symbol: str = "BTCUSDT",
) -> dict[str, Any]:
    config = config or ActiveBasisConfig()
    config.validate()
    if len(series) <= config.basis_lookback_days + 2:
        raise ValueError("active_basis_series_too_short")
    features = build_features(series, config)
    start_index = max(config.basis_lookback_days, config.funding_lookback_days - 1)
    active = _simulate(
        series,
        features,
        config,
        start_index=start_index,
        require_basis_entry=True,
        use_basis_exit=True,
    )
    funding_only = _simulate(
        series,
        features,
        config,
        start_index=start_index,
        require_basis_entry=False,
        use_basis_exit=False,
    )
    static = _simulate_static(series, config, start_index=start_index)
    segment_results = _segment_summaries(series, features, config, start_index)
    positive_segments = sum(
        1 for value in segment_results.values() if value["active"]["total_return"] > 0.0
    )
    cost_model = _cost_model_payload(config)
    gates = {
        "positive_net_after_cost": active["total_return"] > 0.0,
        "beats_funding_only_baseline": active["total_return"] >= funding_only["total_return"],
        "beats_static_positive_carry": active["total_return"] >= static["total_return"],
        "minimum_trade_count_24": active["trade_count"] >= 24,
        "at_least_two_positive_segments": positive_segments >= 2,
        "complete_funding_coverage": active["funding_coverage"] >= 1.0,
        "complete_executable_cost_model": cost_model["complete_executable_cost_model"],
    }
    return {
        "schema_version": ACTIVE_BASIS_SCHEMA_VERSION,
        "symbol": symbol,
        "strategy": "long_spot_short_perp_positive_basis_active_capture",
        "data_role": "consumed_historical_discovery_pool",
        "orders_authorized": False,
        "paper_or_live_allowed": False,
        "config": config.as_dict(),
        "cost_model": cost_model,
        "contract_hash": canonical_hash(
            {
                "schema_version": ACTIVE_BASIS_SCHEMA_VERSION,
                "config": config.as_dict(),
                "cost_model": cost_model,
            }
        ),
        "series": {
            "bar_count": len(series),
            "start_date": series[0].date.isoformat(),
            "end_date": series[-1].date.isoformat(),
            "funding_settlement_count": sum(item.funding_settlement_count for item in series),
        },
        "active": active,
        "funding_only_baseline": funding_only,
        "static_positive_carry_baseline": static,
        "segments": segment_results,
        "kill_gates": gates,
        "verdict": "retain_for_next_evidence" if all(gates.values()) else "reject_mechanism",
    }


def _simulate_static(
    series: Sequence[DailyBasisBar],
    config: ActiveBasisConfig,
    *,
    start_index: int,
) -> dict[str, Any]:
    transition_cost = _transition_cost(config) * config.gross_capital_fraction
    nav = [1.0]
    daily_returns: list[float] = []
    market_pnl = 0.0
    funding_pnl = 0.0
    execution_cost = 2.0 * transition_cost
    nav[0] -= transition_cost
    daily_returns.append(-transition_cost)
    for index in range(start_index + 1, len(series)):
        previous = series[index - 1]
        row = series[index]
        period_market_pnl = 0.5 * config.gross_capital_fraction * (
            row.spot_close / previous.spot_close
            - row.perp_close / previous.perp_close
        )
        period_funding_pnl = 0.5 * config.gross_capital_fraction * row.funding_rate_sum
        period_pnl = period_market_pnl + period_funding_pnl
        market_pnl += period_market_pnl
        funding_pnl += period_funding_pnl
        nav.append(nav[-1] + period_pnl)
        daily_returns.append(period_pnl)
    if len(nav) > 1:
        nav[-1] -= transition_cost
        daily_returns[-1] -= transition_cost
    else:
        nav[-1] -= transition_cost
        daily_returns[-1] -= transition_cost
    return _summary(
        nav,
        daily_returns,
        market_pnl=market_pnl,
        funding_pnl=funding_pnl,
        execution_cost=execution_cost,
        trades=[
            {
                "entry_date": series[start_index].date.isoformat(),
                "exit_date": series[-1].date.isoformat(),
                "holding_days": max(len(series) - 1 - start_index, 0),
                "entry_basis_pct": series[start_index].basis_pct,
                "exit_basis_pct": series[-1].basis_pct,
                "net_return": nav[-1] - 1.0,
                "exit_reason": "sample_end",
            }
        ],
        funding_complete_days=sum(
            1 for row in series[start_index:] if row.funding_settlement_count >= config.min_funding_settlements_per_day
        ),
        total_days=max(len(series) - start_index, 0),
    )


def _segment_summaries(
    series: Sequence[DailyBasisBar],
    features: Sequence[BasisFeatures],
    config: ActiveBasisConfig,
    start_index: int,
) -> dict[str, dict[str, Any]]:
    segments = {
        "2020_2022": (date(2020, 1, 1), date(2022, 12, 31)),
        "2023_2024": (date(2023, 1, 1), date(2024, 12, 31)),
        "2025_2026": (date(2025, 1, 1), date(2026, 12, 31)),
    }
    output: dict[str, dict[str, Any]] = {}
    for name, (start_date, end_date) in segments.items():
        indices = [
            i for i, row in enumerate(series)
            if start_date <= row.date <= end_date
        ]
        if not indices:
            continue
        first = indices[0]
        subseries = series[first : indices[-1] + 1]
        subfeatures = features[first : indices[-1] + 1]
        local_start = max(start_index - first, 0)
        output[name] = {
            "start_date": subseries[0].date.isoformat(),
            "end_date": subseries[-1].date.isoformat(),
            "active": _simulate(
                subseries,
                subfeatures,
                config,
                start_index=local_start,
                require_basis_entry=True,
                use_basis_exit=True,
            ),
        }
    return output


def protocol() -> dict[str, Any]:
    config = ActiveBasisConfig()
    return {
        "schema_version": ACTIVE_BASIS_SCHEMA_VERSION,
        "hypothesis_family": "carry_active_basis_v1",
        "research_question": "Does persistent positive funding plus an unusually wide positive perp basis predict cost-adjusted basis convergence?",
        "mechanism": "long spot and short perpetual; profit from basis narrowing and positive short-perp funding",
        "bar_frequency": "1d",
        "decision_timing": "daily close; position return starts on the next bar",
        "direction": "positive_basis_only",
        "config": config.as_dict(),
        "baseline_ids": ["static_positive_carry", "funding_only_active_capture"],
        "primary_metric": "active.total_return after two-leg costs and funding",
        "cost_model": _cost_model_payload(config),
        "kill_tests": [
            "positive_net_after_cost",
            "beats_funding_only_baseline",
            "beats_static_positive_carry",
            "minimum_trade_count_24",
            "at_least_two_positive_segments",
            "complete_funding_coverage",
            "complete_executable_cost_model",
        ],
        "orders_authorized": False,
        "paper_or_live_allowed": False,
    }


__all__ = [
    "ACTIVE_BASIS_SCHEMA_VERSION",
    "ActiveBasisConfig",
    "DailyBasisBar",
    "BasisFeatures",
    "build_daily_basis_series",
    "build_features",
    "evaluate_active_basis",
    "protocol",
]
