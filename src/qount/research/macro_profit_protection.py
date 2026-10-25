"""Two fixed offline profit-protection mechanisms; never a live policy import."""
from __future__ import annotations

import copy

from qount.strategies.perpetual import grid


def protect_profit(position, close, volatility, tick, *, fee, slip, early_trail=False, cost_floor=False):
    """Completed-close updates take effect after this call, never intrabar.

    Keep the original two-ATR trail distance; only its trigger may move from
    two to one initial R. A separate one-R floor covers entry fee, modeled exit
    friction and already known net funding debits, without crediting receipts.
    Future funding and adverse stop execution can still cause a loss.
    """
    if position.get("side", 1) != 1:
        raise ValueError("profit_protection_study_is_long_only")
    pos = copy.deepcopy(position)
    pos["highest_close"] = max(pos["highest_close"], close)
    gain = close-pos["entry_price"]
    if volatility is not None and gain >= (1 if early_trail else 2)*pos["structural_r"]:
        proposed = grid(pos["highest_close"]-2*volatility, tick, True)
        if proposed >= close:
            return pos, "crossed_trailing_stop"
        pos["stop"] = max(pos["stop"], proposed)
    if cost_floor:
        pos["cost_floor_armed"] = pos.get("cost_floor_armed", False) or gain >= pos["structural_r"]
        if pos["cost_floor_armed"]:
            q = pos["quantity"]
            entry_fee = pos.get("entry_fee", q*pos["entry_price"]*fee)
            paid = max(0.0, -pos.get("funding", 0.0))
            floor = grid((pos["entry_price"]+(entry_fee+paid)/q)/((1-slip)*(1-fee)), tick, True)
            if floor >= close:
                return pos, "cost_floor_crossed_at_update"
            pos["stop"] = max(pos["stop"], floor)
    return pos, None
