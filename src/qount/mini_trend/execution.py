"""MiniTrend target-to-order planning."""

from __future__ import annotations

import math
from collections.abc import Mapping

from qount.mini_trend.config import MiniTrendConfig
from qount.mini_trend.models import ExecutionPlan, Order, RiskResult, SymbolFilter


def _round_down_step(amount: float, step: float) -> float:
    if step <= 0:
        return amount
    return math.floor(amount / step + 1e-12) * step


def _floor_usdt(symbol_filter: SymbolFilter, price: float, cfg: MiniTrendConfig) -> float:
    return max(symbol_filter.min_notional, symbol_filter.min_amount * price, cfg.min_order_usdt)


def _ordered_symbols(cfg: MiniTrendConfig, balances_base: Mapping[str, float]) -> list[str]:
    out = list(cfg.universe)
    out.extend(sorted(s for s in balances_base if s not in set(cfg.universe)))
    return out


def compute_orders(
    risk: RiskResult,
    balances_base: Mapping[str, float],
    prices: Mapping[str, float],
    filters: Mapping[str, SymbolFilter],
    cfg: MiniTrendConfig | None = None,
    *,
    mode: str = "dry",
    armed: bool = False,
) -> ExecutionPlan:
    """Plan spot market orders from risk-approved target weights.

    In ``paper``/``dry`` the plan is a would-place plan even when ``armed`` is false. In ``live``,
    ``armed`` must be true before any order is emitted.
    """

    cfg = cfg or MiniTrendConfig()
    no_order_reasons: list[str] = []
    target_usdt: dict[str, float] = {}
    current_usdt: dict[str, float] = {}
    orders: list[Order] = []

    if risk.halt or not risk.allow:
        reason = "risk_halted" if risk.halt else "risk_blocked"
        return ExecutionPlan(1, mode, armed, [], [reason], target_usdt, current_usdt)
    if mode == "live" and not armed:
        return ExecutionPlan(1, mode, armed, [], ["not_armed"], target_usdt, current_usdt)

    for symbol in _ordered_symbols(cfg, balances_base):
        price = prices.get(symbol, 0.0)
        current_base = max(0.0, float(balances_base.get(symbol, 0.0)))
        current_value = current_base * price if price > 0 else 0.0
        target_value = max(0.0, risk.targets.get(symbol, 0.0)) * cfg.capital_cap_usdt
        current_usdt[symbol] = current_value
        target_usdt[symbol] = target_value

        diff = target_value - current_value
        if abs(diff) <= 1e-9:
            continue
        symbol_filter = filters.get(symbol)
        if symbol_filter is None or price <= 0:
            no_order_reasons.append(f"{symbol}: no price/filter")
            continue

        denom = max(abs(target_value), abs(current_value), 1e-9)
        if target_value > 0 and abs(diff) < cfg.rebalance_band * denom:
            no_order_reasons.append(f"{symbol}: within rebalance_band")
            continue

        floor = _floor_usdt(symbol_filter, price, cfg)
        if diff > 0:
            spend = min(diff, cfg.max_order_usdt)
            if spend < floor:
                no_order_reasons.append(f"{symbol}: buy below notional floor")
                continue
            base_qty = _round_down_step(spend / price, symbol_filter.amount_step)
            est = base_qty * price
            if base_qty < symbol_filter.min_amount or est < floor:
                no_order_reasons.append(f"{symbol}: buy quantity below filter")
                continue
            orders.append(
                Order(
                    symbol=symbol,
                    side="buy",
                    type="market",
                    base_qty=base_qty,
                    quote_qty=round(spend, 2),
                    est_usdt=round(spend, 2),
                    reason="target_rebalance",
                )
            )
            continue

        sell_base = _round_down_step(min(current_base, -diff / price), symbol_filter.amount_step)
        est = sell_base * price
        if sell_base <= 0:
            no_order_reasons.append(f"{symbol}: no sellable balance")
            continue
        if sell_base < symbol_filter.min_amount or est < floor:
            no_order_reasons.append(f"{symbol}: sell below notional/min floor")
            continue
        reason = "target_exit" if target_value == 0 else "target_rebalance"
        orders.append(
            Order(
                symbol=symbol,
                side="sell",
                type="market",
                base_qty=sell_base,
                quote_qty=0.0,
                est_usdt=round(est, 2),
                reason=reason,
            )
        )

    if not orders and not no_order_reasons:
        no_order_reasons.append("on_target")
    return ExecutionPlan(1, mode, armed, orders, no_order_reasons, target_usdt, current_usdt)
