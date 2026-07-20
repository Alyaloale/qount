"""MiniTrend scorecard helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass

from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.models import Scorecard

REQUIRED_METRICS = (
    "max_drawdown_pct",
    "fee_to_notional_pct",
    "order_count",
    "min_notional_coverage",
    "stop_reentry_count",
    "unmanaged_position_count",
    "schema_error_count",
)


def max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return abs(worst) * 100.0


def _get(obj, key: str, default=0.0):
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _blocked_dicts(blocked_symbols: Sequence[object] | None) -> list[dict]:
    out = []
    for item in blocked_symbols or []:
        if isinstance(item, Mapping):
            out.append(dict(item))
        elif is_dataclass(item):
            out.append(asdict(item))
        else:
            out.append({"value": item})
    return out


def build_scorecard(
    metrics: Mapping[str, float | int | None],
    *,
    cfg: MiniTrendConfig | None = None,
    mode: str = "paper",
    window: Mapping[str, str] | None = None,
    blocked_symbols: Sequence[object] | None = None,
) -> Scorecard:
    cfg = cfg or MiniTrendConfig()
    clean = {k: v for k, v in metrics.items() if v is not None}
    missing = [k for k in REQUIRED_METRICS if k not in clean]
    verdict = "pass"
    if missing:
        verdict = "block"
    elif clean["schema_error_count"] > 0 or clean["unmanaged_position_count"] > 0:
        verdict = "block"
    elif clean["stop_reentry_count"] > 0:
        verdict = "block"
    elif clean["max_drawdown_pct"] > cfg.scorecard_max_drawdown_pct:
        verdict = "block"
    elif clean["min_notional_coverage"] < cfg.min_notional_coverage:
        verdict = "block"
    elif clean["fee_to_notional_pct"] > cfg.scorecard_expected_fee_to_notional_pct * 1.2:
        verdict = "block"
    elif clean["order_count"] > cfg.scorecard_max_order_count:
        verdict = "watch"

    return Scorecard(
        schema_version=1,
        strategy=cfg.strategy,
        mode=mode,
        window=dict(window or {}),
        metrics=clean,
        blocked_symbols=_blocked_dicts(blocked_symbols),
        missing_fields=missing,
        verdict=verdict,
    )


def scorecard_from_events(
    *,
    equity_curve: Sequence[float] | None = None,
    orders: Sequence[object] | None = None,
    min_notional_checks: Sequence[bool] | None = None,
    stop_reentry_count: int | None = None,
    unmanaged_position_count: int | None = None,
    schema_error_count: int | None = None,
    cfg: MiniTrendConfig | None = None,
    mode: str = "paper",
    window: Mapping[str, str] | None = None,
    blocked_symbols: Sequence[object] | None = None,
) -> Scorecard:
    metrics: dict[str, float | int | None] = {
        "stop_reentry_count": stop_reentry_count,
        "unmanaged_position_count": unmanaged_position_count,
        "schema_error_count": schema_error_count,
    }
    if equity_curve is not None:
        metrics["total_return_pct"] = (
            ((equity_curve[-1] / equity_curve[0] - 1.0) * 100.0)
            if len(equity_curve) >= 2 and equity_curve[0] != 0
            else 0.0
        )
        metrics["max_drawdown_pct"] = max_drawdown_pct(equity_curve)
    if orders is not None:
        notional = sum(float(_get(o, "notional_usdt", _get(o, "est_usdt", 0.0))) for o in orders)
        fees = sum(float(_get(o, "fee_usdt", 0.0)) for o in orders)
        metrics["order_count"] = len(orders)
        metrics["fee_to_notional_pct"] = (fees / notional * 100.0) if notional > 0 else 0.0
    if min_notional_checks is not None:
        metrics["min_notional_coverage"] = (
            sum(1 for ok in min_notional_checks if ok) / len(min_notional_checks)
            if min_notional_checks
            else 1.0
        )
    return build_scorecard(
        metrics,
        cfg=cfg,
        mode=mode,
        window=window,
        blocked_symbols=blocked_symbols,
    )
