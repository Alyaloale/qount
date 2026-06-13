"""GRID-B grid engine: geometric ladder math + buy/sell pairing + per-grid net check.

This is step 1 of the v0.1 route (``docs/grid-binance-plan.md`` §7): the *pure* core
of a long-only geometric grid. No data, no network, no broker -- every function here is
deterministic and unit-testable offline, which is exactly why it goes first.

Two responsibilities live here, both from v0.1:

1. **Geometry / sizing** (§2.1-§2.3): given a price range ``[lower, upper]`` and either a
   grid count ``n`` or a per-grid step, build the geometric price ladder ``P_k = L·q^k``
   and the equal-quote capital allocation. Plus the hard per-grid net-profit gate (§2.2):
   ``net_per_grid = step - fee_buy - fee_sell - slippage`` must clear ``MIN_NET_PER_GRID``.

2. **Buy/sell pairing state** (§4 单格闭环): each of the ``n`` intervals ``[P_k, P_{k+1}]``
   is an independent cell that cycles *buy@bottom / sell@top*. ``GridLadder`` tracks each
   cell's state and realizes net quote profit on each completed buy->sell round, while
   accumulating base inventory (and its average cost) as price falls.

The v0.2 shape generator (gaussian alloc / ATR spacing / trailing) is deliberately NOT
here yet -- baseline must pass the S1 hold-baseline kill-test before any of that. Keep
this module the clean, equal-quote, fixed-geometric baseline that v0.2 can later degrade
back to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field

# v0.1 §2.2: per-grid net floor (after maker round-trip + slippage buffer). A grid whose
# step cannot clear this is rejected -- a single taker fill or a bit of slippage flips it
# negative.
MIN_NET_PER_GRID = 0.0030  # 0.30%


class GridConfigError(ValueError):
    """Raised when a grid configuration is internally inconsistent or fails the net gate."""


# --------------------------------------------------------------------------------------
# Geometry (v0.1 §2.1)
# --------------------------------------------------------------------------------------


def geometric_ratio(lower: float, upper: float, n: int) -> float:
    """Common ratio ``q = (U/L)^(1/n)`` for an ``n``-interval geometric grid."""

    _check_bounds(lower, upper)
    if n < 1:
        raise GridConfigError(f"n must be >= 1, got {n}")
    return (upper / lower) ** (1.0 / n)


def count_for_step(lower: float, upper: float, step: float) -> int:
    """Smallest ``n`` whose per-grid step is <= ``step`` (so spacing never exceeds target).

    Inverts ``n = ln(U/L) / ln(1+step)`` and rounds *up*: using ``ceil`` guarantees the
    realized step ``(U/L)^(1/n)-1 <= step`` rather than overshooting it.
    """

    _check_bounds(lower, upper)
    if step <= 0:
        raise GridConfigError(f"step must be > 0, got {step}")
    raw = math.log(upper / lower) / math.log(1.0 + step)
    return max(1, math.ceil(raw - 1e-12))


def grid_prices(lower: float, upper: float, n: int) -> list[float]:
    """The ``n+1`` price lines ``P_k = L·q^k`` for ``k = 0..n`` (``P_0=L``, ``P_n=U``)."""

    q = geometric_ratio(lower, upper, n)
    return [lower * (q ** k) for k in range(n + 1)]


# --------------------------------------------------------------------------------------
# Per-grid net gate (v0.1 §2.2)
# --------------------------------------------------------------------------------------


def net_per_grid(step: float, *, maker_fee: float, slippage: float = 0.0) -> float:
    """Net fractional profit per completed grid round, after maker fees both sides.

    ``step`` is the gross per-grid move (``q-1``). Fees are charged on both the buy and
    the sell leg; ``slippage`` is an extra one-shot buffer. To first order this is
    ``step - 2*maker_fee - slippage`` (the exact buy-leg/sell-leg notionals differ by a
    factor ``q``, a second-order effect well under the safety buffer).
    """

    return step - 2.0 * maker_fee - slippage


def validate_step(step: float, *, maker_fee: float, slippage: float = 0.0,
                  min_net: float = MIN_NET_PER_GRID) -> float:
    """Return ``net_per_grid`` if it clears ``min_net``; else raise ``GridConfigError``."""

    net = net_per_grid(step, maker_fee=maker_fee, slippage=slippage)
    if net < min_net:
        raise GridConfigError(
            f"per-grid net {net:.4%} below floor {min_net:.4%} "
            f"(step={step:.4%}, maker_fee={maker_fee:.4%}, slippage={slippage:.4%})"
        )
    return net


# --------------------------------------------------------------------------------------
# Grid spec: geometry + equal-quote allocation, with the net gate enforced (v0.1 §2.3)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GridSpec:
    """A fully-resolved long-only geometric grid (baseline, equal-quote allocation)."""

    lower: float
    upper: float
    n: int
    q: float
    step: float
    prices: tuple[float, ...]          # n+1 price lines, ascending
    per_grid_quote: float              # equal USDT notional per buy line
    net_per_grid: float                # net fractional profit per completed round

    def base_qty(self, level: int) -> float:
        """Base amount a buy at line ``level`` acquires (``per_grid_quote / P_level``)."""

        return self.per_grid_quote / self.prices[level]


def build_grid(
    *,
    lower: float,
    upper: float,
    grid_capital: float,
    n: int | None = None,
    step: float | None = None,
    maker_fee: float = 0.00075,   # v0.1 §5: maker 0.075% with BNB discount
    slippage: float = 0.0,
    min_net: float = MIN_NET_PER_GRID,
) -> GridSpec:
    """Build a baseline equal-quote geometric grid and enforce the per-grid net gate.

    Provide exactly one of ``n`` (grid count) or ``step`` (target per-grid move); the
    other is derived (§2.1). Capital is split equally across the ``n`` buy lines
    ``P_0..P_{n-1}`` -- equal USDT per line means *more base bought the lower it fills*,
    which is the "average down as it drops" behaviour (§2.3).
    """

    _check_bounds(lower, upper)
    if grid_capital <= 0:
        raise GridConfigError(f"grid_capital must be > 0, got {grid_capital}")
    if (n is None) == (step is None):
        raise GridConfigError("provide exactly one of n or step")

    if n is None:
        n = count_for_step(lower, upper, float(step))
    q = geometric_ratio(lower, upper, n)
    realized_step = q - 1.0
    net = validate_step(realized_step, maker_fee=maker_fee, slippage=slippage, min_net=min_net)

    prices = tuple(lower * (q ** k) for k in range(n + 1))
    per_grid_quote = grid_capital / n
    return GridSpec(
        lower=lower,
        upper=upper,
        n=n,
        q=q,
        step=realized_step,
        prices=prices,
        per_grid_quote=per_grid_quote,
        net_per_grid=net,
    )


# --------------------------------------------------------------------------------------
# Buy/sell pairing state machine (v0.1 §4 单格闭环)
# --------------------------------------------------------------------------------------


@dataclass
class _Cell:
    """One grid interval ``[P_k, P_{k+1}]``: holds either a resting buy or inventory."""

    holding: bool = False     # True once the buy@P_k has filled and a sell@P_{k+1} rests
    base_qty: float = 0.0     # base acquired by the buy leg (0 when not holding)


@dataclass
class GridLadder:
    """Stateful buy/sell pairing over a fixed grid, charging maker fees on every fill.

    Cell ``k`` covers the interval ``[prices[k], prices[k+1]]`` (``k = 0..n-1``). Drive it
    with the two fill events a backtest / live loop produces:

    * ``apply_buy_fill(k)``  -- price reached ``P_k``; buy the cell's base, start holding.
    * ``apply_sell_fill(k)`` -- price reached ``P_{k+1}``; sell the held base, realize net.

    The ladder tracks realized quote profit (net of fees), live base inventory, and the
    cumulative quote actually spent on that inventory (for average-cost / mark-to-market).
    Fill *detection* (did this bar cross the line? maker vs taker?) is the backtest's job,
    not the ladder's -- keeping this piece pure and trivially testable.
    """

    spec: GridSpec
    maker_fee: float = 0.00075
    realized_quote: float = 0.0           # cumulative net grid profit booked in USDT
    fees_paid: float = 0.0                # cumulative fees, for honest accounting
    inventory_base: float = 0.0           # base currently held across all holding cells
    inventory_cost_quote: float = 0.0     # quote spent acquiring current inventory
    buy_fills: int = 0
    sell_fills: int = 0
    cells: list[_Cell] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.cells:
            self.cells = [_Cell() for _ in range(self.spec.n)]

    def apply_buy_fill(self, k: int) -> float:
        """Fill the buy at line ``P_k`` (cell ``k``). Returns the fee paid. Idempotent-safe:
        a cell already holding is ignored (returns 0)."""

        self._check_cell(k)
        cell = self.cells[k]
        if cell.holding:
            return 0.0
        price = self.spec.prices[k]
        qty = self.spec.per_grid_quote / price
        fee = self.spec.per_grid_quote * self.maker_fee
        cell.holding = True
        cell.base_qty = qty
        self.inventory_base += qty
        self.inventory_cost_quote += self.spec.per_grid_quote
        self.fees_paid += fee
        self.realized_quote -= fee  # fee booked immediately; profit realized on the sell
        self.buy_fills += 1
        return fee

    def apply_sell_fill(self, k: int) -> float:
        """Fill the sell at line ``P_{k+1}`` for cell ``k``. Returns net quote realized on
        this round (gross spread minus this leg's fee; the buy-leg fee was already booked).
        A cell not holding is ignored (returns 0)."""

        self._check_cell(k)
        cell = self.cells[k]
        if not cell.holding:
            return 0.0
        sell_price = self.spec.prices[k + 1]
        qty = cell.base_qty
        proceeds = qty * sell_price
        fee = proceeds * self.maker_fee
        cost = self.spec.per_grid_quote  # what the buy leg spent on this cell
        net = proceeds - cost - fee      # buy-leg fee already deducted at buy time
        self.inventory_base -= qty
        self.inventory_cost_quote -= cost
        self.fees_paid += fee
        self.realized_quote += net
        cell.holding = False
        cell.base_qty = 0.0
        self.sell_fills += 1
        return net

    def equity(self, mark_price: float) -> float:
        """Total grid PnL marked at ``mark_price``: realized + unrealized on inventory.

        Realized is already net of all fees booked so far. Unrealized marks the held base
        against ``mark_price`` relative to what was paid for it.
        """

        unrealized = self.inventory_base * mark_price - self.inventory_cost_quote
        return self.realized_quote + unrealized

    def _check_cell(self, k: int) -> None:
        if not (0 <= k < self.spec.n):
            raise GridConfigError(f"cell index {k} out of range [0, {self.spec.n})")


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def _check_bounds(lower: float, upper: float) -> None:
    if not (lower > 0 and upper > 0):
        raise GridConfigError(f"prices must be > 0, got lower={lower}, upper={upper}")
    if not (upper > lower):
        raise GridConfigError(f"upper ({upper}) must exceed lower ({lower})")
