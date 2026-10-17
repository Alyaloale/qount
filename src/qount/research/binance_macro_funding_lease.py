"""Budget review for a conditional funding lease; no price/funding prediction."""
from qount.strategies.macro_lease import review_lease
import math
from decimal import Decimal

from qount.research.engine.perpetual import common_step, grid




def resize_lease(order, rule, *, now, price, mark_price, cash, reserve, hours, eligible,
                 fee, slip, risk_fraction, gap, liquidity):
    """Largest grid-valid residual satisfying original budgets after paid reduction.

    All five budget constraints are affine in residual quantity. Intersect their
    feasible intervals before rounding down; do not assume a binary-search
    monotonicity. Historical adverse spending/caps are never reset or prorated.
    Reduction is modeled reduce-only (no minimum notional exemption for entry).
    """
    if not eligible or reserve is None:
        return dict(allowed=False, reason="resize_state_or_forecast_unavailable")
    if any(not math.isfinite(x) for x in (price, mark_price, cash, reserve, liquidity)) or min(price, mark_price) <= 0 or reserve < 0 or liquidity < 0:
        raise ValueError("invalid_resize_inputs")
    q0, side, entry = order["quantity"], order.get("side", 1), order["entry_price"]
    opening_liquidation = (entry-side*order["margin_usdt"]/q0)/(1-side*.01)
    if side*(mark_price-opening_liquidation) <= 0:
        return dict(allowed=False, reason="resize_already_liquidated")
    if side*(price-order["stop"]) <= 0 or order["funding_adverse_paid"] > order["funding_cost_cap_usdt"]+1e-9:
        return dict(allowed=False, reason="resize_stop_or_spent_cap")
    filters = {f["filterType"]: f for f in rule["filters"]}
    lots = [filters["LOT_SIZE"], filters.get("MARKET_LOT_SIZE", filters["LOT_SIZE"])]
    step = common_step(lots)
    minimum = max(float(f["minQty"]) for f in lots)
    lower = max(minimum, q0-min(liquidity, *(float(f["maxQty"]) for f in lots)))
    upper = q0-max(minimum, float(step))
    fill = price*(1-side*slip)
    worst = order["stop"]*(1-side*gap)

    def quantities(q):
        removed = q0-q
        exit_fee = removed*fill*fee
        realized = side*removed*(fill-entry)-exit_fee
        margin = order["margin_usdt"]*q/q0
        cash_after = cash+realized
        equity_after = cash_after+side*q*(mark_price-entry)-q*mark_price*fee
        sunk = (order.get("partial_risk_spent_usdt", 0)
                +removed*max(0, side*(entry-price))+removed*entry*(fee+slip)
                +side*removed*(price-fill)+exit_fee)
        forecast = q*price*reserve
        cumulative = order["funding_adverse_paid"]+forecast
        stress = (q*max(0, side*(entry-worst))+q*entry*(fee+slip)
                  +q*worst*(fee+slip)+cumulative+sunk)
        constraints = (cumulative-order["funding_cost_cap_usdt"],
                       stress-order["risk_budget_usdt"], stress-risk_fraction*equity_after,
                       forecast-(cash_after-margin), margin-.8*equity_after)
        return constraints, dict(quantity=q, removed_quantity=removed, exit_price=fill,
            exit_fee=exit_fee, realized_pnl=realized, margin_after=margin, cash_after=cash_after,
            equity_after=equity_after, partial_risk_spent_usdt=sunk)

    at_zero, _ = quantities(0)
    at_full, _ = quantities(q0)
    for a, b in zip(at_zero, at_full):
        slope = (b-a)/q0
        if abs(slope) < 1e-14:
            if a > 1e-9:
                return dict(allowed=False, reason="resize_no_feasible_budget")
        elif slope > 0:
            upper = min(upper, -a/slope)
        else:
            lower = max(lower, -a/slope)
    q = grid(max(0, upper), step)
    if q < lower-1e-10 or q <= 0 or q >= q0:
        return dict(allowed=False, reason="resize_grid_or_liquidity")
    constraints, plan = quantities(q)
    if max(constraints) > 1e-8 or plan["equity_after"] <= 0:
        return dict(allowed=False, reason="resize_post_cost_budget")
    # Decimal subtraction preserves the same lot grid for the reduction order.
    plan["removed_quantity"] = float(Decimal(str(q0))-Decimal(str(q)))
    remaining = {**order, "quantity": q, "margin_usdt": plan["margin_after"],
                 "partial_risk_spent_usdt": plan["partial_risk_spent_usdt"]}
    review = review_lease(remaining, now=now, price=price, equity=plan["equity_after"],
        cash=plan["cash_after"], reserve=reserve, hours=hours, eligible=eligible,
        fee=fee, slip=slip, risk_fraction=risk_fraction, gap=gap)
    if not review["allowed"]:
        return dict(allowed=False, reason="resize_review_failed", review=review)
    return dict(plan, allowed=True, reason="lease_reduced", review=review)
