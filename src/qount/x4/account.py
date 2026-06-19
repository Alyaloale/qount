"""X4 unified independent account: the signed-position ledger every strategy shares (线 D).

The bake-off is only fair if all four strategies book PnL the same way. ``X4Account`` is the
**signed** generalization of ``grid.perp.PerpHedgeLeg`` (which tracks a short-only hedge): it
holds one signed position (``+`` long / ``−`` short) in a single instrument and books realized
PnL, funding, and fees against an equity-normalized capital base. It is a *pure* ledger — no IO,
no fill detection — mirroring the line B/C philosophy so it is trivially offline-testable.

Accounting model (perp-style, margin implied; no spot cash constraint, matching the
equity-normalized 1x convention used across rv/grid):

* ``equity(mark) = initial_capital + realized + unrealized(mark) + funding − fees``
* ``unrealized = position_base × (mark − avg_price)`` (signed: a short has ``position_base<0``).
* ``trade(target_base, fill_price)`` moves the signed position, charging ``taker_fee`` on the
  traded notional and applying ``slippage`` adversely (buys fill higher, sells fill lower).
  Reductions/flips realize average-cost PnL on the closed portion; the reopened remainder of a
  flip takes the fill price as its new average.
* ``accrue_funding(rate, mark)`` settles on the current signed notional; a positive rate means
  longs pay shorts (a long's funding is negative, a short's positive) — same sign convention as
  ``grid.perp``, generalized to signed positions.

Each strategy owns its own instance: separate instances never share margin (no cross-strategy
netting), which is exactly the independence the bake-off requires.
"""

from __future__ import annotations

from dataclasses import dataclass

_EPS = 1e-12


@dataclass
class X4Account:
    initial_capital: float
    taker_fee: float = 0.0005
    slippage: float = 0.0
    position_base: float = 0.0     # signed: + long, - short
    avg_price: float = 0.0         # average entry of the current open position (>= 0)
    realized_pnl: float = 0.0      # booked price PnL from reductions/flips, quote
    funding_pnl: float = 0.0       # cumulative funding (signed; long pays on positive rate)
    fees_paid: float = 0.0         # cumulative taker fees, quote
    trade_count: int = 0

    def trade(self, target_base: float, fill_price: float) -> None:
        """Move the signed position to ``target_base``, filling the delta at ``fill_price``.

        ``slippage`` is applied adversely (a buy fills higher, a sell lower); ``taker_fee`` is
        charged on the traded notional. A no-op delta returns immediately. Reductions realize
        average-cost PnL on the closed portion; a flip realizes the whole old leg and reopens
        the remainder at the (slipped) fill price.
        """

        if fill_price <= 0:
            raise ValueError(f"fill_price must be > 0, got {fill_price}")
        old = self.position_base
        delta = target_base - old
        if abs(delta) < _EPS:
            return

        buying = delta > 0
        px = fill_price * (1.0 + self.slippage) if buying else fill_price * (1.0 - self.slippage)
        self.fees_paid += abs(delta) * px * self.taker_fee

        if abs(old) < _EPS or (old > 0) == buying:
            # opening from flat, or increasing magnitude in the same direction: new average
            new_base = old + delta
            self.avg_price = (abs(old) * self.avg_price + abs(delta) * px) / abs(new_base)
            self.position_base = new_base
        else:
            # delta opposes the existing position: close (and maybe flip)
            closing = min(abs(delta), abs(old))
            sign = 1.0 if old > 0 else -1.0
            self.realized_pnl += sign * (px - self.avg_price) * closing
            self.position_base = target_base
            if abs(target_base) < _EPS:
                self.position_base = 0.0
                self.avg_price = 0.0
            elif abs(delta) > abs(old) + _EPS:
                # flipped past flat: the reopened remainder is priced at the fill
                self.avg_price = px
            # else: partial close, same-sign smaller position keeps its average
        self.trade_count += 1

    def accrue_funding(self, funding_rate: float, mark_price: float) -> float:
        """Settle one funding period on the current signed notional (returns signed amount).

        Positive ``funding_rate`` => longs pay shorts: a long (``position_base>0``) pays
        (negative), a short receives (positive). Flat is a no-op.
        """

        amt = -funding_rate * self.position_base * mark_price
        self.funding_pnl += amt
        return amt

    def equity(self, mark_price: float) -> float:
        """Total account equity marked at ``mark_price`` (the **marginBalance** analog: includes
        open-position unrealized MTM)."""

        unrealized = self.position_base * (mark_price - self.avg_price)
        return self.initial_capital + self.realized_pnl + unrealized + self.funding_pnl - self.fees_paid

    def wallet_balance(self) -> float:
        """Realized-only equity (the **walletBalance** analog: ``equity`` MINUS open-position MTM).

        Independent of the mark — it only moves when PnL is *booked* (a reduction/flip realizes
        average-cost PnL), funding settles, or fees are charged. Used as an alternative sizing base
        so that an open winner/loser's unrealized MTM does NOT feed back into the position size."""

        return self.initial_capital + self.realized_pnl + self.funding_pnl - self.fees_paid

    def weight(self, mark_price: float) -> float:
        """Current signed exposure as a fraction of equity (``position notional / equity``)."""

        eq = self.equity(mark_price)
        if eq <= 0:
            return 0.0
        return self.position_base * mark_price / eq
