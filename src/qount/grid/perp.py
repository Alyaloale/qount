"""GRID-B H3 perp hedge leg + funding ledger: the delta-neutral carry primitives.

H3 (``docs/grid-binance-h3-plan.md``) strips the grid skin. A long-only grid is a
degenerate short-gamma position; once you delta-hedge its inventory with a perp short,
the harvest (θ) and the rehedge cost (½Γ(dS)²) are two sides of one coin and largely
cancel (the *offset theorem*), leaving funding carry as the only possible edge.

This module is the *pure* accounting core of that hedge, mirroring ``engine.py``'s
philosophy: deterministic, no IO, trivially offline-testable. It tracks a perp **short**
sized to offset a supplied spot base inventory (target delta = 0) and bakes in the H3
hardening holes:

* **洞3 — funding on the time-varying notional**: ``accrue_funding`` settles on the
  *current* short notional (``short_base × mark``), not a fixed one. Sign convention: a
  positive funding rate means longs pay shorts, so the short **receives** (``funding_pnl``
  increases). This is exactly where 洞1 bites -- the hedge short is largest when price has
  dumped (grid bought the dip), which is when funding most often flips negative.
* **洞4 — perp priced on its own market**: every ``rehedge`` / ``adl_cover`` takes an
  explicit ``fill_price``; the caller (``run_h3``) supplies the perp's own (possibly
  basis-dislocated, possibly bar-worst) price. Nothing here assumes perp == spot.
* **洞4 — ADL**: ``adl_cover`` force-covers a fraction of the short at a punitive price.

Average-cost short accounting: realized PnL summed back to flat equals
``Σ proceeds_open − Σ cost_cover`` regardless of the averaging, which is what makes the
offset theorem hold exactly in the frictionless limit (see ``test_grid_h3.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

_EPS = 1e-12


@dataclass
class PerpHedgeLeg:
    """A delta-neutral perp short that tracks a supplied spot inventory.

    Drive it with two events the backtest produces:

    * ``rehedge(target_short_base, fill_price)`` -- move the short to ``target_short_base``
      (= current spot base inventory for delta-neutral), filling the difference at
      ``fill_price`` (caller's worst-price / slippage policy), charging the taker fee.
    * ``accrue_funding(funding_rate, mark_price)`` -- settle one funding period.

    All cash is in quote units. ``equity(mark_price)`` is the leg's total contribution:
    realized + unrealized short PnL + funding − fees.
    """

    taker_fee: float = 0.0005        # UM perp taker; a rehedge is always a market order
    slippage: float = 0.0            # extra adverse fill fraction applied per rehedge
    short_base: float = 0.0          # current perp short size, base units (>= 0)
    short_avg_price: float = 0.0     # average price at which the current short was opened
    realized_pnl: float = 0.0        # booked price PnL from covers, quote
    funding_pnl: float = 0.0         # cumulative funding (positive = received by short)
    fees_paid: float = 0.0           # cumulative taker fees, quote
    rehedge_count: int = 0
    adl_events: int = 0

    def rehedge(self, target_short_base: float, fill_price: float) -> None:
        """Adjust the short to ``target_short_base``, filling the delta at ``fill_price``.

        ``fill_price`` is the perp's own execution price; ``slippage`` is applied
        adversely (lower when selling to open more short, higher when buying to cover).
        Charges ``taker_fee`` on the traded notional. A no-op delta returns immediately.
        """

        if target_short_base < 0:
            raise ValueError(f"target_short_base must be >= 0, got {target_short_base}")
        delta = target_short_base - self.short_base
        if abs(delta) < _EPS:
            return

        if delta > 0:
            # open more short: sell `delta` base. Adverse slippage = a *lower* sell price.
            px = fill_price * (1.0 - self.slippage)
            new_base = self.short_base + delta
            self.short_avg_price = (
                self.short_base * self.short_avg_price + delta * px
            ) / new_base
            self.short_base = new_base
            self.fees_paid += delta * px * self.taker_fee
        else:
            # cover `-delta` base: buy. Adverse slippage = a *higher* buy price.
            cover = -delta
            px = fill_price * (1.0 + self.slippage)
            self.realized_pnl += cover * (self.short_avg_price - px)
            self.fees_paid += cover * px * self.taker_fee
            self.short_base -= cover
            if self.short_base < _EPS:
                self.short_base = 0.0
                self.short_avg_price = 0.0
        self.rehedge_count += 1

    def accrue_funding(self, funding_rate: float, mark_price: float) -> float:
        """Settle one funding period on the *current* short notional (洞3).

        Returns the signed funding for this period (positive = received by the short,
        which happens when ``funding_rate > 0``: longs pay shorts).
        """

        amt = funding_rate * self.short_base * mark_price
        self.funding_pnl += amt
        return amt

    def adl_cover(self, fraction: float, fill_price: float) -> float:
        """Force-cover ``fraction`` of the short at a punitive ``fill_price`` (洞4 ADL).

        Models auto-deleveraging on a violent up-bar: the winning short is partially
        closed at a worse-than-wanted price, realizing a loss; re-establishment to
        delta-neutral happens via the next ``rehedge``. Returns realized PnL on the cover.
        A flat leg is a no-op. ``adl_events`` is incremented when a cover actually fires.
        """

        if not (0.0 < fraction <= 1.0):
            raise ValueError(f"fraction must be in (0, 1], got {fraction}")
        if self.short_base < _EPS:
            return 0.0
        cover = self.short_base * fraction
        realized = cover * (self.short_avg_price - fill_price)
        self.realized_pnl += realized
        self.fees_paid += cover * fill_price * self.taker_fee
        self.short_base -= cover
        if self.short_base < _EPS:
            self.short_base = 0.0
            self.short_avg_price = 0.0
        self.adl_events += 1
        return realized

    def equity(self, mark_price: float) -> float:
        """Total leg contribution: realized + unrealized short PnL + funding − fees."""

        unrealized = self.short_base * (self.short_avg_price - mark_price)
        return self.realized_pnl + unrealized + self.funding_pnl - self.fees_paid
