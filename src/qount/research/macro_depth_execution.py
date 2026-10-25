"""Conditional historical depth execution stress; not a reconstruction of IOC fills."""
from __future__ import annotations

import math
from dataclasses import dataclass

from qount.strategies.perpetual import common_step, grid


def limit_depth_lower_bound(levels, limit, side=1):
    """Infer a static executable-quantity lower bound from cumulative +/-0.2%.

    Bid/ask VWAP bounds locate the midpoint. Markov's inequality then bounds
    ask quantity above the fixed limit. Zero means unknown, not an empty book.
    """
    if side not in (-1, 1) or not math.isfinite(limit) or limit <= 0:
        raise ValueError("invalid_depth_price_limit")
    required = (.2, 1., 2., 3., 4., 5.)
    if any(direction*x not in levels for direction in (-1, 1) for x in required):
        raise ValueError("missing_cumulative_depth_levels")
    if any(not math.isfinite(v) or v <= 0 for pair in levels.values() for v in pair):
        raise ValueError("invalid_cumulative_depth")
    for direction in (-1, 1):
        for a, b in zip(required, required[1:]):
            if any(levels[direction*a][i] > levels[direction*b][i]+1e-7 for i in (0, 1)):
                raise ValueError("nonmonotonic_cumulative_depth")
    bid, bn = levels[-.2]
    ask, an = levels[.2]
    bv, av = bn/bid, an/ask
    lo, hi = max(bv, av/1.002), min(av, bv/.998)
    if bv > av or lo > hi+1e-7:
        raise ValueError("inconsistent_depth_midpoint")
    if side == 1:
        if limit >= hi*1.002:
            quantity = ask
        elif limit > av and limit > lo:
            quantity = max(0, ask*(limit-av)/(limit-lo))
        else:
            quantity = 0.
    else:
        if limit <= lo*.998:
            quantity = bid
        elif limit < bv and limit < hi:
            quantity = max(0, bid*(bv-limit)/(hi-limit))
        else:
            quantity = 0.
    return dict(quantity=quantity, midpoint_lower=lo, midpoint_upper=hi,
                ask_vwap=av, bid_vwap=bv, ask_quantity_20bp=ask, bid_quantity_20bp=bid)


@dataclass(frozen=True)
class DepthExecution:
    """One bounded IOC, with no resubmission or repeated-depth accumulation.

    Quote is the first available snapshot at least five seconds after signal.
    Arrival is the first snapshot at least latency_seconds after that quote.
    Arrival information never enters submitted quantity. Fill at the unchanged
    rounded limit is a pessimistic PRICE assumption conditional on filling.
    Displayed depth survival is a scenario assumption, not an estimated rate.
    """
    contexts: dict
    use_depth_sizing: bool = False
    quote_fraction: float = .25
    fill_fraction: float = .25
    latency_seconds: int = 30

    def __post_init__(self):
        if (not 0 < self.quote_fraction <= 1 or not math.isfinite(self.quote_fraction)
                or not 0 <= self.fill_fraction <= self.quote_fraction
                or not math.isfinite(self.fill_fraction)
                or not isinstance(self.latency_seconds, int) or not 1 <= self.latency_seconds <= 90):
            raise ValueError("invalid_depth_execution_assumptions")

    def quote(self, symbol, now, price, rule):
        snapshots = self.contexts.get((symbol, now))
        if snapshots is None:
            raise ValueError("missing_depth_execution_context")
        times = [r["time"] for r in snapshots]
        if times != sorted(set(times)):
            raise ValueError("invalid_depth_snapshot_order")
        tick = next(f["tickSize"] for f in rule["filters"] if f["filterType"] == "PRICE_FILTER")
        limit = grid(price, tick)
        quote = next((r for r in snapshots if now+5 <= r["time"] <= now+90), None)
        if quote is None:
            return dict(status="quote_unavailable_before_deadline")
        bound = limit_depth_lower_bound(quote["levels"], limit)
        # Deliberately no lookup of the arrival book here.
        return dict(status="quote", symbol=symbol, decision_time=now,
                    quote_time=quote["time"], price_limit=limit,
                    quantity_cap=self.quote_fraction*bound["quantity"],
                    quote_bound=bound, quote_fraction=self.quote_fraction)

    def fill(self, order, quote, rule):
        if quote["status"] != "quote":
            raise ValueError("fill_without_quote")
        q = order["quantity"]
        if q > quote["quantity_cap"]+1e-8:
            raise ValueError("submitted_quantity_exceeds_quote")
        result = dict(quote, requested_quantity=q, filled_quantity=0.,
                      latency_seconds=self.latency_seconds, fill_fraction=self.fill_fraction)
        now = quote["decision_time"]
        arrival = next((r for r in self.contexts[quote["symbol"], now]
                        if r["time"] >= quote["quote_time"]+self.latency_seconds), None)
        if arrival is None or arrival["time"] > now+90:
            return dict(result, status="arrival_after_deadline")
        bound = limit_depth_lower_bound(arrival["levels"], quote["price_limit"])
        filters = {f["filterType"]: f for f in rule["filters"]}
        lots = [filters["LOT_SIZE"], filters.get("MARKET_LOT_SIZE", filters["LOT_SIZE"])]
        filled = grid(min(q, self.fill_fraction*bound["quantity"]), common_step(lots))
        # Minimum notional restricts submission, not an exchange partial fill.
        minimum = float(filters["MIN_NOTIONAL"]["notional"])
        if q*quote["price_limit"] < minimum:
            return dict(result, status="rounded_limit_minimum_notional")
        status = "unfilled" if filled == 0 else "full_fill" if filled == q else "partial_fill"
        return dict(result, status=status, arrival_time=arrival["time"],
                    arrival_bound=bound, filled_quantity=filled, fill_price=quote["price_limit"])


@dataclass(frozen=True)
class DepthExitStress:
    """Conditional full-exit price floors, not a market-order reconstruction.

    At the first snapshot >= decision+delay, use the original price if its
    quantity lower bound covers the whole position after the depth haircut.
    Otherwise widen to a cumulative bid band's lower price boundary. Unknown
    or insufficient books use an explicit additional price-loss scenario.
    That fallback assumes full liquidation and never certifies its availability.
    """
    contexts: dict
    fraction: float = .05
    unknown_extra_slip: float = .02
    delay_seconds: int = 30
    use_depth: bool = True
    all_extra_slip: float = 0.

    def __post_init__(self):
        if (not math.isfinite(self.fraction) or not 0 < self.fraction <= 1
                or not math.isfinite(self.unknown_extra_slip) or not 0 <= self.unknown_extra_slip < 1
                or not math.isfinite(self.all_extra_slip) or not 0 <= self.all_extra_slip < 1
                or not isinstance(self.delay_seconds, int) or not 1 <= self.delay_seconds <= 90):
            raise ValueError("invalid_exit_depth_stress")

    def execute(self, position, now, raw_price, reason, slip):
        receipt = self._base_exit(position, now, raw_price, reason, slip)
        if self.all_extra_slip:
            # Same extra adverse price move for every exit, including terminal
            # valuation, isolates sensitivity from archive coverage differences.
            receipt["fill_price"] *= 1-self.all_extra_slip
            receipt["all_extra_slip"] = self.all_extra_slip
        return receipt

    def _base_exit(self, position, now, raw_price, reason, slip):
        if position.get("side", 1) != 1:
            raise ValueError("exit_depth_study_requires_long_position")
        base = raw_price*(1-slip)
        result = dict(decision_time=now, fill_time=now, fill_price=base,
                      quantity=position["quantity"], fraction=self.fraction)
        if reason == "end_of_sample":
            return dict(result, status="terminal_valuation_not_execution")
        scheduled = (reason in ("trend_off", "time_exit", "seven_day_exit", "funding_cost_exit")
                     or reason.startswith("lease_"))
        if not scheduled:
            # The hourly stop proxy reports a bar boundary, not its true trigger
            # second. A boundary snapshot must not be represented as its fill.
            return dict(result, status="intrabar_clock_unknown",
                        fill_price=base*(1-self.unknown_extra_slip))
        result["fill_time"] = now+self.delay_seconds
        if not self.use_depth:
            return dict(result, status="assumed_base_price_with_delay")
        snapshots = self.contexts.get((position["symbol"], now))
        if snapshots is None:
            raise ValueError("exit_context_not_loaded")
        times = [r["time"] for r in snapshots]
        if times != sorted(set(times)):
            raise ValueError("invalid_exit_snapshot_order")
        arrival = next((r for r in snapshots if now+self.delay_seconds <= r["time"] <= now+90), None)
        status = "missing_exit_snapshot"
        if arrival is not None:
            result["fill_time"] = arrival["time"]
            try:
                bound = limit_depth_lower_bound(arrival["levels"], base, side=-1)
                result["base_price_quantity_bound"] = bound["quantity"]
                if self.fraction*bound["quantity"] >= position["quantity"]:
                    return dict(result, status="conditional_base_price", band_percent=None)
                for band in (.2, 1., 2., 3., 4., 5.):
                    quantity = arrival["levels"][-band][0]
                    if self.fraction*quantity >= position["quantity"]:
                        return dict(result, status="conditional_wider_band", band_percent=band,
                            band_quantity=quantity,
                            fill_price=min(base, bound["midpoint_lower"]*(1-band/100)))
                status = "insufficient_discounted_depth"
            except ValueError as exc:
                status = str(exc)
        return dict(result, status="assumed_unknown_book_price", unknown_reason=status,
                    unknown_extra_slip=self.unknown_extra_slip,
                    fill_price=base*(1-self.unknown_extra_slip))
