"""Order-free single-sleeve research fills, explicit fee floors and share units."""
from __future__ import annotations

from dataclasses import dataclass
import math

from qount.dual_engine.paper import _floor_step


@dataclass(frozen=True)
class CashFriction:
    cost_bps: float=20.
    commission_bps: float=5.
    minimum_commission: float=0.
    lot: float=1.
    commission_per_share: float=0.
    commission_cap_rate: float | None=None

    def __post_init__(self):
        if (not all(math.isfinite(x) and x>=0 for x in (self.cost_bps,self.commission_bps,self.minimum_commission,self.lot,self.commission_per_share))
                or self.cost_bps>=10000 or self.commission_bps>self.cost_bps
                or (self.commission_cap_rate is not None and (not math.isfinite(self.commission_cap_rate) or not 0<=self.commission_cap_rate<1))):
            raise ValueError("cash_friction_invalid")

    def commission(self,notional,quantity=None):
        if notional<=0:return 0.
        if self.commission_per_share:
            if quantity is None or not math.isfinite(quantity) or quantity<0:
                raise ValueError("cash_commission_quantity_required")
            variable=quantity*self.commission_per_share
        else:
            variable=notional*self.commission_bps/10000
        value=max(variable,self.minimum_commission)
        return value if self.commission_cap_rate is None else min(value,notional*self.commission_cap_rate)

    def fee(self,notional,quantity=None):
        if self.commission_per_share or self.commission_cap_rate is not None:
            return notional*(self.cost_bps-self.commission_bps)/10000+self.commission(notional,quantity) if notional>0 else 0.
        # Preserve the exact floating-point path of existing cash controls.
        return (notional*self.cost_bps/10000 + max(0.,self.minimum_commission-notional*self.commission_bps/10000)
                if notional>0 else 0.)


def rebalance_cash(layer, *, sleeve_budgets, sleeve_targets, marks, fills, rules, contract, signal,
                   friction=CashFriction()):
    """Same base sizing order as G20 paper, extended to fee-floor funding.

    Commission has its own floor; the remaining friction is an extra slippage
    cash charge. This is a scenario, not a broker tariff. Receivables cannot fund buys.
    """
    if set(layer["sleeves"])!={"g20"} or sleeve_budgets!={"g20":1.} or signal:
        raise ValueError("research_single_cash_sleeve_required")
    sleeve=layer["sleeves"]["g20"];held=sleeve["positions"];cash=sleeve["cash"]
    target=sleeve_targets["g20"]
    if any(not math.isfinite(w) or w<0 for w in target.values()) or sum(target.values())>1+1e-12:
        raise ValueError("cash_target_invalid")
    equity=cash+sum(q*marks[s] for s,q in held.items())
    if not math.isfinite(equity) or equity<=0:raise ValueError("cash_equity_invalid")
    floor=lambda q:_floor_step(q,friction.lot) if friction.lot else q
    desired={s:floor(equity*w/fills[s]) for s,w in target.items()}
    fee_total=0.;events=[]

    def fill(symbol,side,quantity):
        nonlocal cash,fee_total
        if quantity<=0:return
        price=fills[symbol];notional=quantity*price;fee=friction.fee(notional,quantity)
        cash+=(-notional if side=="buy" else notional)-fee
        held[symbol]=held.get(symbol,0.)+(quantity if side=="buy" else -quantity)
        fee_total+=fee
        if cash < -1e-7 or held[symbol]<-1e-9:raise ArithmeticError("cash_fill_unfunded")
        events.append(dict(symbol=symbol,side=side,quantity=quantity,reference_price=price,
                           notional=notional,cost=fee,stress_cost=fee))

    for s in sorted(set(held)|set(desired)):
        q=held.get(s,0.)-desired.get(s,0.)
        if q>1e-12:
            if q*fills[s] < friction.fee(q*fills[s],q):raise ValueError("sale_proceeds_below_fee")
            fill(s,"sell",q)
    required=sum((q:=max(0.,wanted-held.get(s,0.)))*fills[s]+friction.fee(q*fills[s],q) for s,wanted in desired.items())
    scale=1. if required<=cash+1e-12 else cash/required
    rate=friction.cost_bps/10000
    slip=(friction.cost_bps-friction.commission_bps)/10000
    for s in sorted(desired):
        requested=desired[s]-held.get(s,0.)
        if requested<=1e-12:continue
        price=fills[s]
        # notional + slippage + max(commission, minimum) <= cash.
        affordable=max(0.,min(cash/(price*(1+rate)),(cash-friction.minimum_commission)/(price*(1+slip))))
        if friction.commission_per_share or friction.commission_cap_rate is not None:
            variable=friction.commission_per_share or price*friction.commission_bps/10000
            affordable=max(0.,min(cash/(price*(1+slip)+variable),(cash-friction.minimum_commission)/(price*(1+slip))))
            if friction.commission_cap_rate is not None:
                # Capping the commission below its floor can fund more shares.
                affordable=max(affordable,cash/(price*(1+slip+friction.commission_cap_rate)))
        q=floor(min(requested*scale,affordable))
        fill(s,"buy",q)
    sleeve["cash"]=max(0.,cash)
    sleeve["positions"]={s:q for s,q in sorted(held.items()) if abs(q)>1e-12}
    layer["cumulative_cost"]+=fee_total
    layer["cumulative_stress_cost"]+=fee_total
    return fee_total,events
