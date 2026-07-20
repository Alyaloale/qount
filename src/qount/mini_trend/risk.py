"""MiniTrend deterministic risk gate."""

from __future__ import annotations

from collections.abc import Mapping

from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.models import BlockedSymbol, Position, RiskResult, SignalResult, SymbolFilter


def _position(symbol: str, value: Position | float | int) -> Position:
    if isinstance(value, Position):
        return value
    return Position(symbol=symbol, base_amount=float(value))


def _floor_usdt(symbol_filter: SymbolFilter, price: float, cfg: MiniTrendConfig) -> float:
    return max(symbol_filter.min_notional, symbol_filter.min_amount * price, cfg.min_order_usdt)


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def evaluate_risk(
    signal: SignalResult,
    filters: Mapping[str, SymbolFilter],
    prices: Mapping[str, float],
    cfg: MiniTrendConfig | None = None,
    *,
    positions: Mapping[str, Position | float | int] | None = None,
    daily_pnl_pct: float = 0.0,
    weekly_pnl_pct: float = 0.0,
    latches: Mapping[str, bool] | None = None,
) -> RiskResult:
    """Apply hard risk constraints and return adjusted target weights.

    Operational unknowns halt. Ordinary risk blocks zero the affected targets while still allowing
    downstream planners to generate reducing orders.
    """

    cfg = cfg or MiniTrendConfig()
    reasons: list[str] = []
    blocked: list[BlockedSymbol] = []
    targets = {s: max(0.0, signal.targets.get(s, 0.0)) for s in cfg.universe}
    halt = False
    latches = latches or {}
    latch_reset_symbols = [s for s, latched in latches.items() if latched and signal.targets.get(s, 0.0) <= 0]

    if not signal.gate.risk_on:
        _add_reason(reasons, "risk_off_master_gate")
        targets = {s: 0.0 for s in targets}
    if daily_pnl_pct <= -cfg.max_daily_loss_pct:
        _add_reason(reasons, "daily_loss_limit")
        targets = {s: 0.0 for s in targets}
    if weekly_pnl_pct <= -cfg.max_weekly_loss_pct:
        _add_reason(reasons, "weekly_loss_limit")
        targets = {s: 0.0 for s in targets}

    for symbol, raw_position in (positions or {}).items():
        position = _position(symbol, raw_position)
        if abs(position.liability) > cfg.position_epsilon:
            _add_reason(reasons, "spot_liability")
            halt = True
        if abs(position.base_amount) <= cfg.position_epsilon:
            continue
        if symbol not in cfg.universe:
            _add_reason(reasons, "unmanaged_position")
            halt = True
        if symbol not in filters or prices.get(symbol, 0.0) <= 0:
            _add_reason(reasons, "held_position_unknown_price_or_filter")
            halt = True

    positive_before = {s: w for s, w in targets.items() if w > 0}
    covered = 0
    checked = 0
    for symbol, weight in list(positive_before.items()):
        target_usdt = weight * cfg.capital_cap_usdt
        if latches.get(symbol):
            _add_reason(reasons, "stop_latch")
            targets[symbol] = 0.0
            continue
        price = prices.get(symbol, 0.0)
        symbol_filter = filters.get(symbol)
        if symbol_filter is None or price <= 0:
            _add_reason(reasons, "target_unknown_price_or_filter")
            blocked.append(BlockedSymbol(symbol, target_usdt, 0.0, "unknown_price_or_filter"))
            targets[symbol] = 0.0
            checked += 1
            continue
        floor = _floor_usdt(symbol_filter, price, cfg)
        checked += 1
        if target_usdt < floor:
            _add_reason(reasons, "target_below_min_notional")
            blocked.append(BlockedSymbol(symbol, target_usdt, floor, "below_min_notional"))
            targets[symbol] = 0.0
        else:
            covered += 1

    coverage = (covered / checked) if checked else 1.0
    if checked and coverage < cfg.min_notional_coverage:
        _add_reason(reasons, "min_notional_coverage_below_gate")
        for symbol in targets:
            if targets[symbol] > 0:
                targets[symbol] = 0.0

    gross = sum(targets.values())
    if gross > cfg.max_gross and gross > 0:
        _add_reason(reasons, "gross_clamped")
        targets = {s: w * cfg.max_gross / gross for s, w in targets.items()}

    if halt:
        targets = {s: 0.0 for s in targets}

    return RiskResult(
        schema_version=1,
        allow=not halt,
        halt=halt,
        reasons=reasons,
        limits={
            "capital_cap_usdt": cfg.capital_cap_usdt,
            "max_gross": cfg.max_gross,
            "max_daily_loss_pct": cfg.max_daily_loss_pct,
            "max_weekly_loss_pct": cfg.max_weekly_loss_pct,
        },
        blocked_symbols=blocked,
        targets=targets,
        min_notional_coverage=coverage,
        latch_reset_symbols=latch_reset_symbols,
    )
