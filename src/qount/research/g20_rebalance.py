"""Causal close-time G20 rebalance decisions; offline research only."""
from __future__ import annotations

import math

MODES = ("risk_units", "add_band", "symmetric_band")


def selected_symbol(target):
    names = [s for s, w in target.items() if s != "BIL" and w > 0]
    if len(names) != 1:
        raise ValueError("g20_single_risk_symbol_required")
    return names[0]


def rebalance_decision(*, target, positions, prices, cash, previous_symbol, mode, band=.01):
    """Use completed close prices and spendable equity, never a future execution quote.

    Initial plans and sector changes are always passed. Quantity equality is a
    close-time estimate: next-open gaps can change affordable shares. A one-point
    absolute capital band is fixed for mechanism comparison, not optimized.
    """
    if mode not in MODES or not math.isfinite(band) or band < 0:
        raise ValueError("g20_rebalance_mode_invalid")
    symbol = selected_symbol(target)
    if (not math.isfinite(cash) or cash < 0 or any(not math.isfinite(w) or w < 0 for w in target.values())
            or sum(target.values()) > 1 + 1e-12
            or any(not math.isfinite(q) or q < 0 for q in positions.values())
            or any(not math.isfinite(prices[s]) or prices[s] <= 0 for s in {*positions, symbol})):
        raise ValueError("g20_rebalance_close_invalid")
    equity = cash + sum(q * prices[s] for s, q in positions.items())
    if equity <= 0:
        raise ValueError("g20_rebalance_equity_invalid")
    held = positions.get(symbol, 0.)
    current = held * prices[symbol] / equity
    wanted = target[symbol]
    wanted_units = math.floor(equity * wanted / prices[symbol] + 1e-12)
    if previous_symbol is None:
        execute, reason = True, "initial"
    elif previous_symbol != symbol or any(s not in ("BIL", symbol) and q > 0 for s, q in positions.items()):
        execute, reason = True, "sector_change"
    elif mode in ("risk_units", "add_band") and wanted_units == held:
        execute, reason = False, "risk_units_unchanged"
    elif mode == "risk_units":
        execute, reason = True, "risk_units_changed"
    elif mode == "add_band" and current > wanted:
        execute, reason = True, "risk_reduction"
    elif abs(current - wanted) <= band + 1e-12:
        execute, reason = False, "inside_band"
    else:
        execute, reason = True, "outside_band"
    return dict(execute=execute, reason=reason, selected=symbol, current_risk_weight=current,
        target_risk_weight=wanted, gap=current-wanted, current_units=held, close_target_units=wanted_units)
