"""Small offline long-perpetual account; funding and fees remain separate."""
from __future__ import annotations

import math


class LinearAccount:
    def __init__(self, capital, fee, slip):
        if not math.isfinite(capital) or capital <= 0 or not 0 <= fee < .1 or not 0 <= slip < .1:
            raise ValueError("invalid_account_assumptions")
        self.initial = self.cash = float(capital)
        self.fee, self.slip = fee, slip
        self.position = None
        self.trades = []

    def open(self, symbol, quantity, price, stop, time, signal_time):
        if self.position or quantity <= 0 or stop <= 0:
            raise ValueError("invalid_entry")
        price *= 1+self.slip
        if stop >= price:
            raise ValueError("entry_below_protective_stop")
        fee = quantity*price*self.fee
        self.cash -= fee
        self.position = dict(symbol=symbol, quantity=quantity, entry_price=price, stop=stop,
                             entry_time=time, signal_time=signal_time, entry_fee=fee, funding=0.0)

    def funding(self, rate, mark):
        if self.position:
            amount = -self.position["quantity"]*mark*rate
            self.cash += amount
            self.position["funding"] += amount

    def equity(self, mark):
        return self.cash + (self.position["quantity"]*(mark-self.position["entry_price"]) if self.position else 0)

    def close(self, price, time, reason):
        p = self.position
        if p is None:
            raise ValueError("no_position")
        price *= 1-self.slip
        gross = p["quantity"]*(price-p["entry_price"])
        fee = p["quantity"]*price*self.fee
        self.cash += gross-fee
        self.trades.append(dict(p, exit_price=price, exit_time=time, exit_reason=reason,
                                gross_pnl=gross, exit_fee=fee, net_pnl=gross-fee-p["entry_fee"]+p["funding"]))
        self.position = None
