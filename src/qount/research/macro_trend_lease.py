"""Offline trend continuation experiment; no production policy or account access."""
from __future__ import annotations

from qount.strategies.macro_lease import review_lease


def review_profitable_trend(order, **known):
    """Keep original cash/risk/funding checks; trend renewals also cover known costs.

    Evaluate a hypothetical immediate close at the already available current
    open with the scenario's exit friction and accrued signed funding. Future
    prices and settlements never enter this condition. Passing is not a promise
    that eventual execution or the remaining position will be profitable.
    """
    result = review_lease(order, **known)
    if order.get("tactical_setup") not in ("breakout", "pullback"):
        return result
    side, q = order.get("side", 1), order["quantity"]
    exit_price = known["price"] * (1-side*known["slip"])
    entry_fee = order.get("entry_fee", q*order["entry_price"]*known["fee"])
    net = (side*q*(exit_price-order["entry_price"])-entry_fee-q*exit_price*known["fee"]
           +order.get("funding", 0.0))
    result.update(known_net_exit_estimate=net, profitable_trend_required=True)
    if result["allowed"] and net < 0:
        result.update(allowed=False, reason="lease_trend_profit_not_covered")
    return result
