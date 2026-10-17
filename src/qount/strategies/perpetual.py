"""Reusable perpetual sizing and unit accounting; no venue IO or orders."""
from __future__ import annotations
import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

@dataclass
class UnitLedger:
    equity: float
    units: float
    peak_nav: float = 1.0
    deposits: float = 0.0
    withdrawals: float = 0.0

    @property
    def nav(self):
        return self.equity / self.units

    def transfer(self, amount: float):
        if not math.isfinite(amount) or self.nav <= 0 or self.equity + amount <= 0:
            raise ValueError("invalid_transfer")
        self.units += amount / self.nav
        self.equity += amount
        self.deposits += max(amount, 0)
        self.withdrawals += max(-amount, 0)


def grid(value, tick, up=False):
    d, step = Decimal(str(value)), Decimal(str(tick))
    return float((d / step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * step)


def common_step(filters):
    values = [Decimal(f["stepSize"]) for f in filters if Decimal(f["stepSize"]) > 0]
    places = max(-v.as_tuple().exponent for v in values)
    scale = 10 ** places
    return Decimal(math.lcm(*(int(v * scale) for v in values))) / scale


def size(config, rule, reference, price, volatility, equity, budget, reserve, fee, slip, liquidity,
         *, side=1, liquidation_stop_multiple=3.0):
    if side not in (-1, 1) or not math.isfinite(liquidation_stop_multiple) or liquidation_stop_multiple < 1:
        raise ValueError("invalid_side_or_liquidation_cushion")
    filters = rule["filters"]
    if isinstance(filters, list):
        filters = {f["filterType"]: f for f in filters}
    tick = filters["PRICE_FILTER"]["tickSize"]
    stop = grid(reference - side*config["signal"]["initial_stop_atr"] * volatility, tick, True)
    if stop <= 0 or side*(price-stop) <= 0:
        return None, "invalid_stop"
    distance = side*(price-stop)/price
    friction = 2*(fee+slip)+reserve
    if friction > config["cost_model"]["ordinary_friction_limit_fraction_of_stop"]*distance:
        return None, "friction_budget"
    gap = config["cost_model"]["stop_gap_reserve"]
    buffer = 0.01 + float(rule.get("liquidationFee", rule.get("liquidation_fee", 0.015)))
    leverage = config["sizing"]["exchange_leverage"]["maximum"]
    while leverage and (1/leverage-buffer)/(1-side*buffer) < liquidation_stop_multiple*(distance+gap):
        leverage -= 1
    if not leverage:
        return None, "liquidation_distance"
    worst = stop*(1-side*gap)
    # Conservative reference Pe already includes ordinary entry slippage;
    # stress allowance deliberately also reserves it per the frozen exact formula.
    loss_per_unit = side*(price-worst)+price*(fee+slip+reserve)+worst*(fee+slip)
    caps = config["sizing"]["notional_caps"]
    lots = [filters["LOT_SIZE"], filters.get("MARKET_LOT_SIZE", filters["LOT_SIZE"])]
    quantity = grid(min(budget/loss_per_unit, caps["effective_gross"]*equity/price,
        caps["maximum_isolated_margin_fraction"]*equity*leverage/price,
        equity/(price*(1/leverage+fee+reserve)), liquidity,
        *(float(f["maxQty"]) for f in lots)), common_step(lots))
    minimum = float(filters["MIN_NOTIONAL"]["notional"])
    if quantity < max(float(f["minQty"]) for f in lots) or quantity*price < minimum:
        return None, "minimum_order"
    result = dict(quantity=quantity, entry_price=price, initial_stop=stop, stop=stop,
        notional_usdt=quantity*price, margin_usdt=quantity*price/leverage,
        leverage=leverage, buffer=buffer, stress_risk_usdt=quantity*loss_per_unit,
        structural_risk_usdt=quantity*side*(price-stop), risk_budget_usdt=budget)
    assert result["stress_risk_usdt"] <= budget+1e-9
    return result, "accepted"
