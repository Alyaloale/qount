"""Unchanged funding-lease continuation rule shared by replay and live."""
import math

def review_lease(order, *, now, price, equity, cash, reserve, hours, eligible, fee, slip, risk_fraction, gap):
    """Renew quantity unchanged using known state, paid debits and next-period reserve.

    Favorable funding never offsets cumulative adverse spending. Marked profit
    is not withdrawable cash. A settlement can overshoot its allowance before
    an exit executes; this is a continuation rule, not a hard loss guarantee.
    """
    result = dict(time=now, forecast_hours=hours, price=price, equity=equity, cash=cash, stop=order["stop"],
                  adverse_paid=order["funding_adverse_paid"], funding_cost_cap=order["funding_cost_cap_usdt"],
                  allowed=False)
    if not eligible:
        return dict(result, reason="lease_regime_off")
    if reserve is None:
        return dict(result, reason="lease_funding_unknown")
    if any(not math.isfinite(v) for v in (price, equity, cash, reserve)) or price <= 0 or reserve < 0:
        raise ValueError("invalid_lease_inputs")
    q, side = order["quantity"], order.get("side", 1)
    future_cost = q*price*reserve
    total_cost = order["funding_adverse_paid"]+future_cost
    worst = order["stop"]*(1-side*gap)
    # Same conservative fee/slippage geometry as initial sizing; preserve the
    # entry-slippage allowance, and never spend an unrealized stop profit.
    stress = (q*max(0, side*(order["entry_price"]-worst))
              +q*order["entry_price"]*(fee+slip)+q*worst*(fee+slip)+total_cost
              +order.get("partial_risk_spent_usdt", 0))
    budget = min(order["risk_budget_usdt"], risk_fraction*equity)
    free_cash = max(0, cash-order["margin_usdt"])
    result.update(reserve=reserve, forecast_cost=future_cost, cumulative_cost_with_reserve=total_cost,
                  remaining_free_cash=free_cash, stress_risk=stress, risk_budget=budget)
    if total_cost > order["funding_cost_cap_usdt"]+1e-9:
        return dict(result, reason="lease_cost_budget")
    if future_cost > free_cash+1e-9:
        return dict(result, reason="lease_cash_budget")
    if stress > budget+1e-9:
        return dict(result, reason="lease_risk_budget")
    return dict(result, allowed=True, reason="lease_renewed")
