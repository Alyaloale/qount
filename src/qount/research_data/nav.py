"""R0-COST/NAV Signal and Standalone Executable NAV generators.

Computes the three NAV levels defined by the research advancement roadmap:

    Signal NAV            = cumulative(position * price_return)
                           -- pure signal, no costs, no execution

    Standalone Exec NAV   = Signal NAV - cumulative(turnover * costs + funding + ...)
                           -- one strategy leg with its frozen cost model

    Portfolio Realized NAV = multi-sleeve combination (only after virtual replay)
                           -- NOT computed here; requires the allocator

All functions are pure: they take plain lists and return plain dicts.
No IO, no network, no strategy coupling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any
from typing import Sequence

from qount.research_data.cost_model import FrozenCostModel


# --- Data types -------------------------------------------------------------


@dataclass(frozen=True)
class NavResult:
    """One NAV computation result with series and summary.

    ``nav_series`` is a list of floats starting at 1.0.  ``total_return`` is
    ``nav_series[-1] - 1.0``.  ``cost_breakdown`` maps cost names to cumulative
    fractions.  ``cost_incomplete`` is True when any cost component has
    ``source == "unavailable"``.
    """

    nav_series: tuple[float, ...]
    total_return: float
    total_cost: float
    cost_breakdown: dict[str, float]
    cost_incomplete: bool
    cost_model_hash: str
    bars: int
    turnover: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "nav_series": list(self.nav_series),
            "total_return": self.total_return,
            "total_cost": self.total_cost,
            "cost_breakdown": dict(self.cost_breakdown),
            "cost_incomplete": self.cost_incomplete,
            "cost_model_hash": self.cost_model_hash,
            "bars": self.bars,
            "turnover": self.turnover,
            "final_nav": self.nav_series[-1] if self.nav_series else 0.0,
        }


# --- Helpers ----------------------------------------------------------------


def compute_max_drawdown(nav_series: Sequence[float]) -> float:
    """Compute max drawdown using a rolling peak (no look-ahead).

    At each point ``t``, the drawdown is ``(nav[t] - peak_t) / peak_t`` where
    ``peak_t = max(nav[0:t+1])``.  Returns the most negative value (<= 0.0).
    """

    if not nav_series:
        return 0.0
    peak = nav_series[0]
    max_dd = 0.0
    for v in nav_series:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < max_dd:
                max_dd = dd
    return max_dd


def _safe_float(value: Any) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _validate_inputs(
    closes: Sequence[float],
    positions: Sequence[float],
) -> None:
    if len(closes) != len(positions):
        raise ValueError(
            f"length mismatch: closes={len(closes)} positions={len(positions)}"
        )
    if len(closes) < 2:
        raise ValueError("need at least 2 bars for NAV computation")


# --- Turnover costs ---------------------------------------------------------


def _compute_turnover_costs(
    position_change: float,
    cost_model: FrozenCostModel,
) -> dict[str, float]:
    """Compute per-bar turnover costs from a position change.

    Turnover costs are proportional to the absolute change in position.
    Each turnover cost component is computed independently.
    """

    turnover_names = {
        "taker_fee", "maker_fee", "spread", "slippage",
        "legging_cost", "roll_cost", "fx_cost",
        "etf_fee", "futures_fee", "tax",
    }
    costs: dict[str, float] = {}
    abs_change = abs(position_change)
    for comp in cost_model.components:
        if comp.name in turnover_names and comp.source != "unavailable":
            costs[comp.name] = abs_change * float(comp.rate)
    return costs


def _compute_holding_costs(
    position: float,
    funding_rate: float | None,
    cost_model: FrozenCostModel,
) -> dict[str, float]:
    """Compute per-bar holding costs (funding, collateral, tail).

    Holding costs are proportional to the position size, not turnover.
    """

    costs: dict[str, float] = {}
    # Funding: signed position * funding_rate * multiplier
    # Long (position > 0) with positive funding: longs pay -> cost (positive)
    # Short (position < 0) with positive funding: shorts receive -> income (negative cost)
    funding_comp = cost_model.get("funding")
    if funding_comp and funding_comp.source != "unavailable" and funding_rate is not None:
        multiplier = float(funding_comp.rate)
        costs["funding"] = position * funding_rate * multiplier
    elif funding_comp and funding_comp.source == "unavailable":
        costs["funding"] = 0.0  # flagged as incomplete

    # Collateral: position * collateral_cost_rate
    collateral = cost_model.get("collateral_cost")
    if collateral and collateral.source != "unavailable":
        costs["collateral_cost"] = abs(position) * float(collateral.rate)

    # Tail: position * tail_cost_rate (insurance cost per bar held)
    tail = cost_model.get("tail_cost")
    if tail and tail.source != "unavailable":
        costs["tail_cost"] = abs(position) * float(tail.rate)

    return costs


# --- Signal NAV (pure, no costs) --------------------------------------------


def compute_signal_nav(
    closes: Sequence[float],
    positions: Sequence[float],
) -> NavResult:
    """Compute Signal NAV: cumulative position × price return, no costs.

    ``closes`` and ``positions`` are aligned bar-by-bar.  ``positions[t]`` is
    the target position held from bar ``t`` to ``t+1``; the return at ``t+1``
    is ``positions[t] * (close[t+1] / close[t] - 1)``.

    The first bar's position is used to set the initial exposure but produces
    no return (no prior close to compare).
    """

    _validate_inputs(closes, positions)
    nav: list[float] = [1.0]
    for t in range(1, len(closes)):
        prev_close = _safe_float(closes[t - 1])
        curr_close = _safe_float(closes[t])
        if prev_close <= 0:
            nav.append(nav[-1])
            continue
        bar_return = curr_close / prev_close - 1.0
        pos = _safe_float(positions[t - 1])
        nav.append(nav[-1] * (1.0 + pos * bar_return))

    total_return = nav[-1] - 1.0 if nav else 0.0
    turnover = sum(abs(_safe_float(positions[t]) - _safe_float(positions[t - 1]))
                   for t in range(1, len(positions)))
    return NavResult(
        nav_series=tuple(nav),
        total_return=total_return,
        total_cost=0.0,
        cost_breakdown={},
        cost_incomplete=False,
        cost_model_hash="",
        bars=len(closes),
        turnover=turnover,
    )


# --- Standalone Executable NAV (signal - costs) -----------------------------


def compute_standalone_nav(
    closes: Sequence[float],
    positions: Sequence[float],
    cost_model: FrozenCostModel,
    *,
    funding_rates: Sequence[float] | None = None,
    funding_incomplete: bool = False,
) -> NavResult:
    """Compute Standalone Executable NAV: signal return minus frozen costs.

    ``funding_rates`` is an optional aligned series of per-bar funding rates
    (only for UM perp legs).  Each element should be the **sum** of all funding
    settlements within that bar's holding interval (not a single rate).  When
    absent, funding cost is 0 and flagged ``cost_incomplete`` if the cost model
    has a funding component.

    ``funding_incomplete`` is set externally when the funding data has gaps
    (e.g., missing settlement intervals).  It is ORed into ``cost_incomplete``.

    Cost structure:
        turnover_costs  = |Δposition| × (taker_fee + slippage + spread + ...)
        holding_costs   = |position|  × (funding_rate × multiplier + collateral + tail)
        total_cost_t    = sum(turnover_costs) + sum(holding_costs)
        nav_t           = nav_{t-1} × (1 + position × return - total_cost_t)
    """

    _validate_inputs(closes, positions)
    errors = cost_model.validate()
    if errors:
        raise ValueError(f"cost_model_invalid:{','.join(errors)}")

    if funding_rates is not None and len(funding_rates) != len(closes):
        raise ValueError(
            f"funding_rates length {len(funding_rates)} != closes {len(closes)}"
        )

    nav: list[float] = [1.0]
    cumulative_costs: dict[str, float] = {}
    cumulative_total_cost = 0.0
    cost_incomplete = cost_model.has_unavailable or funding_incomplete

    for t in range(1, len(closes)):
        prev_close = _safe_float(closes[t - 1])
        curr_close = _safe_float(closes[t])
        if prev_close <= 0:
            nav.append(nav[-1])
            continue

        bar_return = curr_close / prev_close - 1.0
        prev_pos = _safe_float(positions[t - 1])
        curr_pos = _safe_float(positions[t])
        position_change = curr_pos - prev_pos

        # Turnover costs (proportional to |Δposition|)
        t_costs = _compute_turnover_costs(position_change, cost_model)

        # Holding costs (proportional to |position|)
        funding_rate = _safe_float(funding_rates[t - 1]) if funding_rates else None
        if cost_model.get("funding") and funding_rates is None:
            cost_incomplete = True
        h_costs = _compute_holding_costs(prev_pos, funding_rate, cost_model)

        # Total cost for this bar (as a fraction of NAV)
        bar_cost = sum(t_costs.values()) + sum(h_costs.values())

        # Accumulate
        for name, val in t_costs.items():
            cumulative_costs[name] = cumulative_costs.get(name, 0.0) + val
        for name, val in h_costs.items():
            cumulative_costs[name] = cumulative_costs.get(name, 0.0) + val
        cumulative_total_cost += bar_cost

        nav.append(nav[-1] * (1.0 + prev_pos * bar_return - bar_cost))

    total_return = nav[-1] - 1.0 if nav else 0.0
    turnover = sum(abs(_safe_float(positions[t]) - _safe_float(positions[t - 1]))
                   for t in range(1, len(positions)))

    return NavResult(
        nav_series=tuple(nav),
        total_return=total_return,
        total_cost=cumulative_total_cost,
        cost_breakdown=cumulative_costs,
        cost_incomplete=cost_incomplete,
        cost_model_hash=cost_model.model_hash,
        bars=len(closes),
        turnover=turnover,
    )


# --- Carry NAV (basis convergence) ------------------------------------------


def compute_carry_signal_nav(
    spot_closes: Sequence[float],
    perp_closes: Sequence[float],
    basis_at_entry: float | None = None,
) -> NavResult:
    """Compute Signal NAV for a delta-neutral basis-carry position.

    Tracks **basis convergence**: the signal return per bar is the
    period-over-period change in basis, where basis is defined as
    ``(perp - spot) / spot``.  When basis narrows (converges), the
    signal return is positive.

    ``basis_at_entry`` is the basis at the time of entry.  If ``None``,
    it is computed from the first bar as ``(perp_0 - spot_0) / spot_0``.
    It is stored for reference but does not alter the per-bar return,
    which is always ``basis_{t-1} - basis_t``.
    """

    if len(spot_closes) != len(perp_closes):
        raise ValueError("spot and perp close series must have equal length")
    if len(spot_closes) < 2:
        raise ValueError("need at least 2 bars")

    if basis_at_entry is None:
        prev_spot_0 = _safe_float(spot_closes[0])
        prev_perp_0 = _safe_float(perp_closes[0])
        if prev_spot_0 > 0:
            basis_at_entry = (prev_perp_0 - prev_spot_0) / prev_spot_0
        else:
            basis_at_entry = 0.0

    nav: list[float] = [1.0]
    for t in range(1, len(spot_closes)):
        prev_spot = _safe_float(spot_closes[t - 1])
        curr_spot = _safe_float(spot_closes[t])
        prev_perp = _safe_float(perp_closes[t - 1])
        curr_perp = _safe_float(perp_closes[t])

        if prev_spot <= 0 or prev_perp <= 0:
            nav.append(nav[-1])
            continue

        basis_prev = (prev_perp - prev_spot) / prev_spot
        basis_curr = (curr_perp - curr_spot) / curr_spot
        signal_return = basis_prev - basis_curr  # positive when basis narrows

        nav.append(nav[-1] * (1.0 + signal_return))

    total_return = nav[-1] - 1.0 if nav else 0.0
    return NavResult(
        nav_series=tuple(nav),
        total_return=total_return,
        total_cost=0.0,
        cost_breakdown={},
        cost_incomplete=False,
        cost_model_hash="",
        bars=len(spot_closes),
        turnover=0.0,
    )


def compute_carry_standalone_nav(
    spot_closes: Sequence[float],
    perp_closes: Sequence[float],
    cost_model: FrozenCostModel,
    *,
    funding_rates: Sequence[float] | None = None,
    funding_incomplete: bool = False,
    weight: float = 0.5,
) -> NavResult:
    """Compute Standalone NAV for a delta-neutral basis-carry position.

    The carry leg is long spot + short perp with equal notional per leg.
    ``weight`` is the fraction of account capital allocated to each leg
    (default 0.5, so gross exposure = 2 * weight = 1.0).

    Key differences from the old implementation:
    - **Fixed notional**: position size is set at entry and does not
      compound.  NAV is additive (``nav_t = nav_{t-1} + daily_pnl``),
      not multiplicative.  No daily rebalancing cost is needed.
    - **Gross ≤ 1**: each leg gets ``weight`` fraction of capital,
      so total gross exposure is ``2 * weight`` (default 1.0).
    - **cost_incomplete**: ``collateral_cost`` and ``tail_cost`` are
      ``"unavailable"`` in the default cost model, so ``cost_incomplete``
      is ``True`` until they are properly estimated.

    ``funding_rates`` elements should be the **sum** of all settlements in each
    bar's holding interval.  ``funding_incomplete`` is ORed into
    ``cost_incomplete`` when the funding data has gaps.
    """

    if len(spot_closes) != len(perp_closes):
        raise ValueError("spot and perp close series must have equal length")
    if len(spot_closes) < 2:
        raise ValueError("need at least 2 bars")

    errors = cost_model.validate()
    if errors:
        raise ValueError(f"cost_model_invalid:{','.join(errors)}")

    nav: list[float] = [1.0]
    cumulative_costs: dict[str, float] = {}
    cumulative_total_cost = 0.0
    cost_incomplete = cost_model.has_unavailable or funding_incomplete

    # Entry turnover: 2 legs, each with `weight` notional
    entry_costs = _compute_turnover_costs(2.0 * weight, cost_model)
    for name, val in entry_costs.items():
        cumulative_costs[name] = cumulative_costs.get(name, 0.0) + val
    cumulative_total_cost += sum(entry_costs.values())
    nav[0] = 1.0 - sum(entry_costs.values())

    for t in range(1, len(spot_closes)):
        prev_spot = _safe_float(spot_closes[t - 1])
        curr_spot = _safe_float(spot_closes[t])
        prev_perp = _safe_float(perp_closes[t - 1])
        curr_perp = _safe_float(perp_closes[t])

        if prev_spot <= 0 or prev_perp <= 0:
            nav.append(nav[-1])
            continue

        spot_return = curr_spot / prev_spot - 1.0
        perp_return = curr_perp / prev_perp - 1.0

        # Fixed-weight PnL (additive, not compounded)
        market_pnl = weight * (spot_return - perp_return)

        # Holding costs: funding (short perp) + collateral + tail
        funding_rate = _safe_float(funding_rates[t - 1]) if funding_rates else None
        if cost_model.get("funding") and funding_rates is None:
            cost_incomplete = True

        # Position is -weight (short weight units of perp)
        h_costs = _compute_holding_costs(-weight, funding_rate, cost_model)
        bar_cost = sum(h_costs.values())
        for name, val in h_costs.items():
            cumulative_costs[name] = cumulative_costs.get(name, 0.0) + val
        cumulative_total_cost += bar_cost

        # Additive NAV: no compounding = no implicit rebalancing
        nav.append(nav[-1] + market_pnl - bar_cost)

    # Exit turnover: close both legs
    exit_costs = _compute_turnover_costs(2.0 * weight, cost_model)
    for name, val in exit_costs.items():
        cumulative_costs[name] = cumulative_costs.get(name, 0.0) + val
    cumulative_total_cost += sum(exit_costs.values())
    if nav:
        nav[-1] -= sum(exit_costs.values())

    total_return = nav[-1] - 1.0 if nav else 0.0

    return NavResult(
        nav_series=tuple(nav),
        total_return=total_return,
        total_cost=cumulative_total_cost,
        cost_breakdown=cumulative_costs,
        cost_incomplete=cost_incomplete,
        cost_model_hash=cost_model.model_hash,
        bars=len(spot_closes),
        turnover=4.0 * weight,  # 2 legs entry + 2 legs exit
    )
