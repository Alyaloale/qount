"""Weekend convergence capacity study for Binance TradFi perpetuals."""

from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from qount.artifacts import write_research_json_artifact
from qount.grid.data import Bar, Funding
from qount.mini_trend.futures_recovery import canonical_hash
from qount.mini_trend.scorecard import max_drawdown_pct
from qount.models import utc_now
from qount.settings import Settings


TRADIFI_WEEKEND_VERSION = "binance_tradifi_weekend_convergence_v0.1"
NEW_YORK = ZoneInfo("America/New_York")
TRADIFI_LISTING_MONTHS: dict[str, tuple[int, int]] = {
    "TSLAUSDT": (2026, 1),
    "MSTRUSDT": (2026, 2),
    "AMZNUSDT": (2026, 2),
    "COINUSDT": (2026, 2),
    "METAUSDT": (2026, 3),
    "NVDAUSDT": (2026, 3),
    "GOOGLUSDT": (2026, 3),
    "QQQUSDT": (2026, 4),
    "SPYUSDT": (2026, 4),
    "AAPLUSDT": (2026, 4),
    "MSFTUSDT": (2026, 4),
}


@dataclass(frozen=True)
class TradifiWeekendConfig:
    end_month: tuple[int, int] = (2026, 6)
    round_trip_cost_bps: float = 24.0
    minimum_calendar_gap_days: int = 3
    minimum_symbol_events: int = 8
    bootstrap_samples: int = 5_000
    seed: int = 20260719

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "config": asdict(self),
                "symbols": TRADIFI_LISTING_MONTHS,
                "event": (
                    "previous US cash close -> last completed hourly bar before next cash open; "
                    "then next cash session close"
                ),
                "trade": (
                    "long only when weekend return is negative; enter pre-open proxy, "
                    "exit cash close, include round-trip cost and funding"
                ),
                "holdout_role": "short_recent_history_discovery",
                "paper_or_live_allowed": False,
            }
        )


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean, right_mean = _mean(left), _mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    )
    return numerator / denominator if denominator > 0.0 else 0.0


def _cash_session_bar_open_ms(date_value: str, *, point: str) -> int:
    date = dt.date.fromisoformat(date_value)
    if point == "close":
        local = dt.datetime.combine(date, dt.time(16, 0), tzinfo=NEW_YORK)
        bar_open = local.astimezone(dt.UTC) - dt.timedelta(hours=1)
    elif point == "preopen":
        local = dt.datetime.combine(date, dt.time(9, 30), tzinfo=NEW_YORK)
        utc = local.astimezone(dt.UTC)
        bar_open = utc.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)
    else:
        raise ValueError(f"unknown cash-session point: {point}")
    return int(bar_open.timestamp() * 1000)


def _bootstrap_mean(values: Sequence[float], *, samples: int, seed: int) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "p05": 0.0, "p95": 0.0, "probability_positive": 0.0}
    import random

    rng = random.Random(seed)
    means = [
        _mean([values[rng.randrange(len(values))] for _ in values])
        for _ in range(samples)
    ]
    means.sort()

    def percentile(probability: float) -> float:
        return means[min(int((len(means) - 1) * probability), len(means) - 1)]

    return {
        "mean": _mean(values),
        "p05": percentile(0.05),
        "p95": percentile(0.95),
        "probability_positive": _mean([float(value > 0.0) for value in means]),
    }


def build_weekend_events(
    bars: Sequence[Bar],
    funding: Sequence[Funding],
    cash_trading_dates: Sequence[str],
    *,
    config: TradifiWeekendConfig,
) -> list[dict[str, Any]]:
    prices = {row.ts_ms: float(row.close) for row in bars}
    dates = sorted(set(cash_trading_dates))
    events = []
    for previous_date, next_date in zip(dates, dates[1:]):
        gap = (dt.date.fromisoformat(next_date) - dt.date.fromisoformat(previous_date)).days
        if gap < config.minimum_calendar_gap_days:
            continue
        previous_close_open = _cash_session_bar_open_ms(previous_date, point="close")
        next_preopen_open = _cash_session_bar_open_ms(next_date, point="preopen")
        next_close_open = _cash_session_bar_open_ms(next_date, point="close")
        if any(
            timestamp not in prices
            for timestamp in (previous_close_open, next_preopen_open, next_close_open)
        ):
            continue
        previous_close = prices[previous_close_open]
        preopen = prices[next_preopen_open]
        cash_close = prices[next_close_open]
        weekend_return = preopen / previous_close - 1.0
        cash_return = cash_close / preopen - 1.0
        holding_start = next_preopen_open + 3_600_000
        holding_end = next_close_open + 3_600_000
        holding_funding = sum(
            float(row.rate) for row in funding if holding_start < row.ts_ms <= holding_end
        )
        traded = weekend_return < 0.0
        net_trade_return = (
            cash_return
            - holding_funding
            - config.round_trip_cost_bps / 10_000.0
            if traded
            else 0.0
        )
        events.append(
            {
                "previous_cash_date": previous_date,
                "next_cash_date": next_date,
                "calendar_gap_days": gap,
                "previous_cash_close": previous_close,
                "next_preopen_proxy": preopen,
                "next_cash_close": cash_close,
                "weekend_return": weekend_return,
                "cash_session_return": cash_return,
                "opposite_sign_reversion": weekend_return * cash_return < 0.0,
                "long_discount_trade": traded,
                "holding_funding_return": holding_funding,
                "long_discount_net_return": net_trade_return,
            }
        )
    return events


def _event_summary(
    events: Sequence[Mapping[str, Any]],
    *,
    config: TradifiWeekendConfig,
    seed: int,
) -> dict[str, Any]:
    weekend = [float(row["weekend_return"]) for row in events]
    cash = [float(row["cash_session_return"]) for row in events]
    trades = [row for row in events if row["long_discount_trade"]]
    trade_returns = [float(row["long_discount_net_return"]) for row in trades]
    curve = [1.0]
    for value in trade_returns:
        curve.append(curve[-1] * (1.0 + value))
    return {
        "event_count": len(events),
        "first_event": events[0]["previous_cash_date"] if events else None,
        "last_event": events[-1]["next_cash_date"] if events else None,
        "mean_weekend_return_pct": round(_mean(weekend) * 100.0, 8),
        "mean_cash_session_return_pct": round(_mean(cash) * 100.0, 8),
        "weekend_cash_return_correlation": round(_correlation(weekend, cash), 8),
        "opposite_sign_reversion_rate": round(
            _mean([float(row["opposite_sign_reversion"]) for row in events]), 8
        ),
        "long_discount_trade_count": len(trades),
        "long_discount_hit_rate": round(_mean([float(value > 0.0) for value in trade_returns]), 8),
        "long_discount_compound_return_pct": round((curve[-1] - 1.0) * 100.0, 8),
        "long_discount_max_drawdown_pct": round(max_drawdown_pct(curve), 8),
        "long_discount_mean_net_return_pct": round(_mean(trade_returns) * 100.0, 8),
        "long_discount_bootstrap": _bootstrap_mean(
            trade_returns,
            samples=config.bootstrap_samples,
            seed=seed,
        ),
        "minimum_event_gate_passed": len(events) >= config.minimum_symbol_events,
    }


def _pooled_event_summary(
    events: Sequence[Mapping[str, Any]],
    *,
    config: TradifiWeekendConfig,
) -> dict[str, Any]:
    weekend = [float(row["weekend_return"]) for row in events]
    cash = [float(row["cash_session_return"]) for row in events]
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for row in events:
        by_date.setdefault(str(row["next_cash_date"]), []).append(row)
    portfolio_returns = []
    active_dates = 0
    for date in sorted(by_date):
        traded = [row for row in by_date[date] if row["long_discount_trade"]]
        if traded:
            active_dates += 1
            portfolio_returns.append(
                _mean([float(row["long_discount_net_return"]) for row in traded])
            )
        else:
            portfolio_returns.append(0.0)
    curve = [1.0]
    for value in portfolio_returns:
        curve.append(curve[-1] * (1.0 + value))
    return {
        "symbol_event_count": len(events),
        "event_date_count": len(by_date),
        "first_event": min((row["previous_cash_date"] for row in events), default=None),
        "last_event": max((row["next_cash_date"] for row in events), default=None),
        "mean_weekend_return_pct": round(_mean(weekend) * 100.0, 8),
        "mean_cash_session_return_pct": round(_mean(cash) * 100.0, 8),
        "weekend_cash_return_correlation": round(_correlation(weekend, cash), 8),
        "opposite_sign_reversion_rate": round(
            _mean([float(row["opposite_sign_reversion"]) for row in events]), 8
        ),
        "long_discount_symbol_trade_count": sum(
            bool(row["long_discount_trade"]) for row in events
        ),
        "portfolio_active_event_date_count": active_dates,
        "portfolio_hit_rate": round(
            _mean([float(value > 0.0) for value in portfolio_returns]), 8
        ),
        "portfolio_compound_return_pct": round((curve[-1] - 1.0) * 100.0, 8),
        "portfolio_max_drawdown_pct": round(max_drawdown_pct(curve), 8),
        "portfolio_mean_event_return_pct": round(_mean(portfolio_returns) * 100.0, 8),
        "portfolio_date_clustered_bootstrap": _bootstrap_mean(
            portfolio_returns,
            samples=config.bootstrap_samples,
            seed=config.seed + 100,
        ),
        "portfolio_maximum_effective_gross": 1.0,
        "cross_sectional_events_treated_as_independent": False,
    }


def build_tradifi_weekend_report(
    bars_by_symbol: Mapping[str, Sequence[Bar]],
    funding_by_symbol: Mapping[str, Sequence[Funding]],
    cash_trading_dates: Sequence[str],
    config: TradifiWeekendConfig | None = None,
) -> dict[str, Any]:
    config = config or TradifiWeekendConfig()
    symbols = {}
    pooled_events = []
    for index, symbol in enumerate(TRADIFI_LISTING_MONTHS):
        events = build_weekend_events(
            bars_by_symbol.get(symbol, ()),
            funding_by_symbol.get(symbol, ()),
            cash_trading_dates,
            config=config,
        )
        pooled_events.extend({"symbol": symbol, **row} for row in events)
        symbols[symbol] = {
            "listing_month": list(TRADIFI_LISTING_MONTHS[symbol]),
            "bar_count": len(bars_by_symbol.get(symbol, ())),
            "funding_count": len(funding_by_symbol.get(symbol, ())),
            "summary": _event_summary(events, config=config, seed=config.seed + index),
            "events": events,
        }
    pooled = _pooled_event_summary(pooled_events, config=config)
    return {
        "schema_version": TRADIFI_WEEKEND_VERSION,
        "artifact_type": "binance_tradifi_weekend_convergence",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "short_recent_history_discovery",
            "source": "Binance Vision immutable hourly UM klines/funding",
            "transport": "direct_no_proxy_hkg_cloudfront",
            "orders_allowed": False,
            "paper_or_live_allowed": False,
            "shorting_allowed": False,
        },
        "contract": asdict(config)
        | {
            "contract_hash": config.contract_hash,
            "symbols": list(TRADIFI_LISTING_MONTHS),
            "hypothesis": (
                "weekend/off-hours discount partially converges during the next US cash session"
            ),
        },
        "data": {
            "cash_calendar_date_count": len(set(cash_trading_dates)),
            "data_hash": canonical_hash(
                {
                    "bars": {
                        symbol: [[row.ts_ms, row.close, row.volume] for row in rows]
                        for symbol, rows in bars_by_symbol.items()
                    },
                    "funding": {
                        symbol: [[row.ts_ms, row.rate] for row in rows]
                        for symbol, rows in funding_by_symbol.items()
                    },
                    "cash_dates": list(cash_trading_dates),
                }
            ),
        },
        "symbols": symbols,
        "pooled": pooled,
        "diagnostics": {
            "history_is_short": True,
            "independent_oos_available": False,
            "model_training_allowed": False,
            "next_research": (
                "append future events and add Binance/Bybit mapped-spot/perp basis only after "
                "point-in-time cross-venue timestamps are stored"
            ),
        },
    }


def write_tradifi_weekend_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="binance-tradifi-weekend",
        path_key="artifact_path",
        default_filename="binance_tradifi_weekend.json",
        explicit_path=explicit_path,
    )
