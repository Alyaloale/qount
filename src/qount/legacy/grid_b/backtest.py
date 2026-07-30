"""GRID-B S1 backtest: grid harvest vs buy-and-hold-above-SMA200 (the kill-test).

This is the §6 S1 生死命门. It replays an hourly bar series through the baseline grid
(``GridLadder``), gated by a daily SMA200 trend state, and pits it against the honest
baseline -- hold BTC exactly when the same filter is ACTIVE, flat otherwise. If the grid
cannot beat that under fees, the whole construction is negative value (the L6 hold-to-close
lesson, restated for grids).

Honesty choices (deliberate, see module-level discussion in the handoff):
  * Fills use **crossing** semantics, not "touched the level": a buy needs price to drop
    *through* ``P_k`` from above (``last_ref > P_k and bar.low <= P_k``); a sell fires when
    a held cell's ``P_{k+1}`` is reached (``bar.high >= P_{k+1}``). The crossing-down test
    stops buys from auto-filling above market at init / when price is under the line.
  * **No same-bar round-trips**: holding is snapshotted at bar start, so a cell that buys
    this bar cannot also sell this bar -- no fantasy intrabar harvest.
  * **Unseeded**: starts flat in cash; the grid only accumulates as price crosses down in
    an ACTIVE regime. Missing an immediate rip higher (踏空) is a *real* cost, modelled.
  * **Fills are maker** here; the taker / maker-wall stress is S2 (a later increment).
  * Range ``[L,U]`` is caller-supplied; the S1 first cut passes the *full-window* low/high
    (look-ahead, the generous upper bound -- flagged in the result).

All fills are charged the maker fee inside the ladder. The baseline pays a taker fee on
each regime switch (it reacts to MA crosses with market orders).
"""

from __future__ import annotations

import bisect
import datetime as _dt
import statistics
from dataclasses import dataclass
from dataclasses import field

import math

from qount.research_data.market_data import Bar
from qount.research_data.market_data import Funding
from qount.legacy.grid_b.engine import GridLadder
from qount.legacy.grid_b.engine import GridSpec
from qount.legacy.grid_b.engine import build_grid
from qount.legacy.grid_b.perp import PerpHedgeLeg
from qount.legacy.grid_b.trend import HybridRegime
from qount.legacy.grid_b.trend import TrendState
from qount.legacy.grid_b.trend import hybrid_regimes
from qount.legacy.grid_b.trend import sma


@dataclass
class YearAttribution:
    year: int
    grid_return: float
    hold_return: float
    grid_minus_hold: float
    crossings: int


@dataclass
class S1Result:
    spec: GridSpec
    n_hours: int
    # totals over the whole window
    grid_total_return: float
    hold_total_return: float
    grid_minus_hold: float
    # decomposition of grid PnL (v0.1 §2.4): harvested round-trips vs inventory mark
    grid_realized_harvest: float      # banked net grid profit (fees netted), in capital units
    grid_inventory_pnl: float         # final unrealized mark on held inventory
    total_crossings: int
    buy_fills: int
    sell_fills: int
    grid_max_drawdown: float
    hold_max_drawdown: float
    lookahead_range: bool
    per_year: list[YearAttribution] = field(default_factory=list)
    grid_curve: list[float] = field(default_factory=list)
    hold_curve: list[float] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        won = sum(1 for y in self.per_year if y.grid_minus_hold > 0)
        return (
            f"grid {self.grid_total_return:+.1%} vs hold {self.hold_total_return:+.1%} "
            f"(Δ {self.grid_minus_hold:+.1%}); grid beat hold in {won}/{len(self.per_year)} years; "
            f"harvest {self.grid_realized_harvest:+.1%} / inventory {self.grid_inventory_pnl:+.1%}; "
            f"crossings {self.total_crossings}"
        )


def _year_of(bar: Bar) -> int:
    return int(bar.date[:4])


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0] if equity else 0.0
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def daily_states_by_date(
    daily_bars: list[Bar],
    *,
    window: int = 200,
    confirm_bars: int = 2,
) -> dict[str, TrendState]:
    """Map each daily date -> trend state, using the same SMA/confirm machine as the gate."""

    from qount.legacy.grid_b.trend import trend_states

    closes = [b.close for b in daily_bars]
    states = trend_states(closes, window=window, confirm_bars=confirm_bars)
    return {b.date: s for b, s in zip(daily_bars, states)}


def _hold_above_ma(
    hourly_bars: list[Bar],
    states: dict[str, TrendState],
    *,
    capital: float = 1.0,
    taker_fee: float = 0.0010,
) -> list[float]:
    """The ``hold-above-200MA`` baseline equity curve: hold when ACTIVE, flat otherwise.

    Taker fee on each switch (it reacts to MA crosses with market orders). Shared by
    :func:`run_s1` and :func:`run_s1e` so both quote *the same* hold leg (v0.5 §3.2).
    """

    equity = capital
    units = 0.0
    invested = False
    curve: list[float] = []
    for bar in hourly_bars:
        active = states.get(bar.date, TrendState.PAUSED) == TrendState.ACTIVE
        if active and not invested:
            units = (equity * (1.0 - taker_fee)) / bar.close
            invested = True
        elif (not active) and invested:
            equity = units * bar.close * (1.0 - taker_fee)
            units = 0.0
            invested = False
        curve.append(units * bar.close if invested else equity)
    return curve


def active_fraction(
    hourly_bars: list[Bar],
    daily_bars: list[Bar],
    *,
    sma_window: int = 200,
    confirm_bars: int = 2,
) -> float:
    """Fraction of ``hourly_bars`` whose daily SMA200 state is ACTIVE (S1c/O-B5).

    A pair-wise structural-divergence asset (e.g. ETHBTC) can spend most of a long
    downtrend PAUSED; this is the "how much of the time can the gated grid even play"
    read, independent of the grid-vs-hold PnL comparison.
    """

    if not hourly_bars:
        return 0.0
    states = daily_states_by_date(daily_bars, window=sma_window, confirm_bars=confirm_bars)
    n_active = sum(
        1 for b in hourly_bars if states.get(b.date, TrendState.PAUSED) == TrendState.ACTIVE
    )
    return n_active / len(hourly_bars)


def run_s1(
    hourly_bars: list[Bar],
    daily_bars: list[Bar],
    *,
    step: float = 0.01,
    grid_capital: float = 1.0,
    maker_fee: float = 0.00075,
    taker_fee: float = 0.0010,
    sma_window: int = 200,
    confirm_bars: int = 2,
    lower: float | None = None,
    upper: float | None = None,
    pad: float = 0.0,
) -> S1Result:
    """Run the S1 grid-vs-hold kill-test over ``hourly_bars`` with a daily SMA200 gate.

    ``lower``/``upper`` default to the full-window low/high of ``hourly_bars`` (look-ahead;
    the generous upper bound). ``pad`` fractionally widens that range if set.
    """

    if not hourly_bars or not daily_bars:
        raise ValueError("need both hourly and daily bars")

    lookahead = lower is None or upper is None
    lo = lower if lower is not None else min(b.low for b in hourly_bars)
    hi = upper if upper is not None else max(b.high for b in hourly_bars)
    lo *= (1.0 - pad)
    hi *= (1.0 + pad)

    spec = build_grid(lower=lo, upper=hi, grid_capital=grid_capital,
                      step=step, maker_fee=maker_fee)
    ladder = GridLadder(spec=spec, maker_fee=maker_fee)
    prices = spec.prices  # ascending, length n+1

    states = daily_states_by_date(daily_bars, window=sma_window, confirm_bars=confirm_bars)
    hold_curve = _hold_above_ma(hourly_bars, states, capital=grid_capital, taker_fee=taker_fee)

    grid_curve: list[float] = []
    last_ref = hourly_bars[0].open

    # per-year accumulators
    yr_first_grid: dict[int, float] = {}
    yr_last_grid: dict[int, float] = {}
    yr_first_hold: dict[int, float] = {}
    yr_last_hold: dict[int, float] = {}
    yr_crossings: dict[int, int] = {}

    for i, bar in enumerate(hourly_bars):
        state = states.get(bar.date, TrendState.PAUSED)
        active = state == TrendState.ACTIVE

        crossings_before = ladder.buy_fills + ladder.sell_fills

        # --- sells first (snapshot of holding at bar start) ---
        # holding cells whose sell line P_{k+1} is reached this bar.
        held = [k for k in range(spec.n) if ladder.cells[k].holding]
        for k in held:
            if bar.high >= prices[k + 1]:
                ladder.apply_sell_fill(k)

        # --- buys: only in ACTIVE; price must cross DOWN through P_k ---
        if active and bar.low < last_ref:
            # cells with P_k in [bar.low, last_ref): bisect the price ladder.
            # buy line of cell k is prices[k], k in 0..n-1.
            left = bisect.bisect_left(prices, bar.low)
            right = bisect.bisect_left(prices, last_ref)
            for k in range(left, min(right, spec.n)):
                if not ladder.cells[k].holding:
                    ladder.apply_buy_fill(k)

        # --- mark to this bar's close ---
        grid_eq = grid_capital + ladder.equity(bar.close)
        hold_eq = hold_curve[i]

        grid_curve.append(grid_eq)

        crossings = (ladder.buy_fills + ladder.sell_fills) - crossings_before
        y = _year_of(bar)
        if y not in yr_first_grid:
            yr_first_grid[y] = grid_eq
            yr_first_hold[y] = hold_eq
            yr_crossings[y] = 0
        yr_last_grid[y] = grid_eq
        yr_last_hold[y] = hold_eq
        yr_crossings[y] += crossings
        last_ref = bar.close

    grid_total = grid_curve[-1] / grid_capital - 1.0
    hold_total = hold_curve[-1] / grid_capital - 1.0

    per_year: list[YearAttribution] = []
    for y in sorted(yr_first_grid):
        gr = yr_last_grid[y] / yr_first_grid[y] - 1.0 if yr_first_grid[y] else 0.0
        hr = yr_last_hold[y] / yr_first_hold[y] - 1.0 if yr_first_hold[y] else 0.0
        per_year.append(YearAttribution(
            year=y, grid_return=gr, hold_return=hr,
            grid_minus_hold=gr - hr, crossings=yr_crossings[y],
        ))

    inv_pnl = ladder.inventory_base * hourly_bars[-1].close - ladder.inventory_cost_quote
    return S1Result(
        spec=spec,
        n_hours=len(hourly_bars),
        grid_total_return=grid_total,
        hold_total_return=hold_total,
        grid_minus_hold=grid_total - hold_total,
        grid_realized_harvest=ladder.realized_quote / grid_capital,
        grid_inventory_pnl=inv_pnl / grid_capital,
        total_crossings=ladder.buy_fills + ladder.sell_fills,
        buy_fills=ladder.buy_fills,
        sell_fills=ladder.sell_fills,
        grid_max_drawdown=_max_drawdown(grid_curve),
        hold_max_drawdown=_max_drawdown(hold_curve),
        lookahead_range=lookahead,
        per_year=per_year,
        grid_curve=grid_curve,
        hold_curve=hold_curve,
    )


# ----------------------------------------------------------------------------------------
# S1d: hindsight regime-slice attribution (v0.3 §1)
#
# For every calendar month covered by the hourly window, label the month using the
# realized return ``r91`` and annualized daily-return volatility of the *91-day window
# centered on that month* -- deliberately a hindsight label (the most generous possible
# reading for a hypothetical regime-aware construction):
#
#   trend : r91 >=  +10%
#   down  : r91 <=  -10%
#   chop  : |r91| < 10% and annualized vol > 30%   (textbook grid home turf)
#   other : |r91| < 10% and annualized vol <= 30%  (quiet, neither -- not used by the gate)
#
# Within each bucket, accumulate Δ(grid - hold) for the calendar months that fall in it
# and report the compounded annualized Δ. Only the ``chop`` bucket feeds the H1 kill-test
# in v0.3 §1.
# ----------------------------------------------------------------------------------------


@dataclass
class MonthSlice:
    month: str          # "YYYY-MM"
    regime: str          # trend | down | chop | other
    r91: float
    annualized_vol: float
    grid_return: float
    hold_return: float
    grid_minus_hold: float


@dataclass
class RegimeSliceResult:
    months: list[MonthSlice]

    def bucket(self, regime: str) -> list[MonthSlice]:
        return [m for m in self.months if m.regime == regime]

    def annualized_delta(self, regime: str) -> float | None:
        """Compounded, annualized Δ(grid-hold) over the months in ``regime``.

        ``None`` if the bucket is empty (no months were classified into it).
        """

        ms = self.bucket(regime)
        if not ms:
            return None
        total = 1.0
        for m in ms:
            total *= 1.0 + m.grid_minus_hold
        return total ** (12.0 / len(ms)) - 1.0


def regime_slices(
    hourly_bars: list[Bar],
    daily_bars: list[Bar],
    grid_curve: list[float],
    hold_curve: list[float],
    *,
    window_days: int = 91,
    trend_threshold: float = 0.10,
    chop_vol_threshold: float = 0.30,
) -> RegimeSliceResult:
    """Hindsight regime-slice attribution (v0.3 §1, S1d).

    ``grid_curve``/``hold_curve`` must align 1:1 with ``hourly_bars`` (as returned by
    :func:`run_s1`). ``daily_bars`` must cover at least ``window_days // 2`` days on
    either side of the hourly window for edge months to be classified.
    """

    if len(hourly_bars) != len(grid_curve) or len(hourly_bars) != len(hold_curve):
        raise ValueError("grid_curve/hold_curve must align with hourly_bars")

    daily_by_date = {b.date: b.close for b in daily_bars}
    daily_dates = sorted(daily_by_date)

    # bucket hourly bar indices by calendar month: first/last index per "YYYY-MM"
    month_bounds: dict[str, tuple[int, int]] = {}
    for i, bar in enumerate(hourly_bars):
        month = bar.date[:7]
        if month not in month_bounds:
            month_bounds[month] = (i, i)
        else:
            month_bounds[month] = (month_bounds[month][0], i)

    half = window_days // 2
    months: list[MonthSlice] = []
    for month in sorted(month_bounds):
        mid = _dt.date.fromisoformat(f"{month}-15")
        win_start = (mid - _dt.timedelta(days=half)).isoformat()
        win_end = (mid + _dt.timedelta(days=half)).isoformat()
        win_dates = [d for d in daily_dates if win_start <= d <= win_end]
        if len(win_dates) < int(window_days * 0.7):
            continue  # insufficient daily coverage near the edges of the dataset

        win_closes = [daily_by_date[d] for d in win_dates]
        r91 = win_closes[-1] / win_closes[0] - 1.0
        rets = [win_closes[i] / win_closes[i - 1] - 1.0 for i in range(1, len(win_closes))]
        ann_vol = statistics.pstdev(rets) * (365.0 ** 0.5) if len(rets) > 1 else 0.0

        if r91 >= trend_threshold:
            regime = "trend"
        elif r91 <= -trend_threshold:
            regime = "down"
        elif ann_vol > chop_vol_threshold:
            regime = "chop"
        else:
            regime = "other"

        start_i, end_i = month_bounds[month]
        grid_ret = grid_curve[end_i] / grid_curve[start_i] - 1.0
        hold_ret = hold_curve[end_i] / hold_curve[start_i] - 1.0
        months.append(MonthSlice(
            month=month, regime=regime, r91=r91, annualized_vol=ann_vol,
            grid_return=grid_ret, hold_return=hold_ret,
            grid_minus_hold=grid_ret - hold_ret,
        ))

    return RegimeSliceResult(months=months)


# ----------------------------------------------------------------------------------------
# S1e: three-state hybrid construction (v0.5 §3.2)
#
# UPTREND -> hold full position (taker on entry, like the hold baseline). RANGE -> seed an
# O-A0 grid (no-look-ahead [L,U] from trailing realized vol) at ~half position and harvest
# round trips. BELOW -> flat. The structural insight (v0.5 §2): every state but RANGE is
# *identical* to hold-above-200MA, so Δ(s1e-hold) is produced entirely in RANGE, net of the
# taker "switch tax" paid on every regime transition (and every in-range rebuild when price
# exits [L,U]).
# ----------------------------------------------------------------------------------------


@dataclass
class S1eResult:
    n_hours: int
    grid_total_return: float
    hold_total_return: float
    grid_minus_hold: float
    grid_max_drawdown: float
    hold_max_drawdown: float
    switch_count: int          # total regime transitions + in-range rebuilds
    switch_tax: float          # cumulative taker cost of those switches, capital units
    range_harvest: float       # booked grid net from RANGE-state ladders only, capital units
    whipsaw_cost: float        # diagnostic: switch_tax from switches reversed within 24h
    regime_fractions: dict[str, float]   # {uptrend, range, below} time fractions
    per_year: list[YearAttribution] = field(default_factory=list)
    grid_curve: list[float] = field(default_factory=list)
    hold_curve: list[float] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        won = sum(1 for y in self.per_year if y.grid_minus_hold > 0)
        tax_ratio = (self.switch_tax / self.range_harvest) if self.range_harvest > 0 else float("inf")
        return (
            f"s1e {self.grid_total_return:+.1%} vs hold {self.hold_total_return:+.1%} "
            f"(Δ {self.grid_minus_hold:+.1%}); won {won}/{len(self.per_year)}y; "
            f"range_harvest {self.range_harvest:+.1%} / switch_tax {self.switch_tax:.2%} "
            f"(tax/harvest {tax_ratio:.1%}); switches {self.switch_count}"
        )


def _trailing_daily_vol(daily_bars: list[Bar], window: int = 30) -> dict[str, float | None]:
    """Per-date trailing ``window``-day stdev of daily returns (the day's own close is the
    last return in the window -- it is already known by the time that day's hourly bars are
    processed, mirroring the daily-granularity convention of :func:`daily_states_by_date`).
    ``None`` where fewer than ``window`` returns are available (warm-up).
    """

    closes_list = [b.close for b in daily_bars]
    rets = [closes_list[i] / closes_list[i - 1] - 1.0 for i in range(1, len(closes_list))]
    out: dict[str, float | None] = {}
    for i, bar in enumerate(daily_bars):
        out[bar.date] = statistics.pstdev(rets[i - window:i]) if i >= window else None
    return out


def _seed_range_ladder(
    center: float,
    sigma: float | None,
    *,
    z: float,
    horizon_days: int,
    step: float,
    maker_fee: float,
    capital: float,
) -> tuple[GridLadder, float, float, dict[int, float]]:
    """Build + seed an O-A0 range grid (v0.5 §3.2).

    ``[L,U] = center * exp(∓z * sigma * sqrt(horizon_days))``, using only the trailing
    ``sigma`` already computed as of entry day (no look-ahead). Seeds to ~half position:
    every cell whose buy line ``P_k <= center`` starts already holding, via
    :meth:`GridLadder.apply_buy_fill` (so its cost basis stays ``per_grid_quote``, and a
    later :meth:`GridLadder.apply_sell_fill` of that cell accounts correctly).

    That cost basis (``P_k``) is below the price actually paid to acquire the seed
    *now* (``center``): each seeded cell carries a "seed phantom"
    ``qty_k * (center - P_k)`` of unrealized gain that exists purely from the cost-basis
    mismatch, not from any real price move. Returned per-cell so the caller can net it
    out of both equity (subtract the constant total) and ``range_harvest`` (subtract the
    portion belonging to cells that get sold), keeping seeding mark-neutral at entry.
    """

    sigma_eff = sigma if sigma and sigma > 0 else step / 2.0
    half_width = z * sigma_eff * math.sqrt(horizon_days)
    lo = center * math.exp(-half_width)
    hi = center * math.exp(half_width)
    spec = build_grid(lower=lo, upper=hi, grid_capital=capital, step=step, maker_fee=maker_fee)
    ladder = GridLadder(spec=spec, maker_fee=maker_fee)
    seed_phantom: dict[int, float] = {}
    for k in range(spec.n):
        if spec.prices[k] <= center:
            ladder.apply_buy_fill(k)
            seed_phantom[k] = ladder.cells[k].base_qty * center - spec.per_grid_quote
    return ladder, lo, hi, seed_phantom


def run_s1e(
    hourly_bars: list[Bar],
    daily_bars: list[Bar],
    *,
    step: float = 0.01,
    grid_capital: float = 1.0,
    maker_fee: float = 0.00075,
    taker_fee: float = 0.0010,
    sma_window: int = 200,
    confirm_bars: int = 2,
    r90_window: int = 90,
    r90_threshold: float = 0.15,
    z: float = 2.0,
    range_horizon_days: int = 90,
    sigma_window: int = 30,
) -> S1eResult:
    """Run the S1e three-state hybrid construction (v0.5 §3.2-§4).

    UPTREND holds (taker on entry, identical to the hold baseline's leg);
    RANGE seeds an O-A0 grid (:func:`_seed_range_ladder`) and harvests crossings with the
    same crossing/no-same-bar-roundtrip semantics as :func:`run_s1`; BELOW is flat. Every
    regime transition -- and every in-range rebuild when price exits ``[L,U]`` -- pays a
    taker "switch tax" on the full mark-to-market equity. Quoted against the same
    hold-above-200MA baseline as ``run_s1`` (via :func:`_hold_above_ma`).
    """

    if not hourly_bars or not daily_bars:
        raise ValueError("need both hourly and daily bars")

    daily_closes = [b.close for b in daily_bars]
    regimes = hybrid_regimes(daily_closes, window=sma_window, confirm_bars=confirm_bars,
                              r90_window=r90_window, r90_threshold=r90_threshold)
    regime_by_date = {b.date: r for b, r in zip(daily_bars, regimes)}
    sigma_by_date = _trailing_daily_vol(daily_bars, window=sigma_window)
    close_by_date = {b.date: b.close for b in daily_bars}

    states = daily_states_by_date(daily_bars, window=sma_window, confirm_bars=confirm_bars)
    hold_curve = _hold_above_ma(hourly_bars, states, capital=grid_capital, taker_fee=taker_fee)

    whipsaw_window_bars = 24  # diagnostic: a switch reversed within 24h is a "whipsaw"

    mode = HybridRegime.BELOW
    equity = grid_capital
    units = 0.0
    ladder: GridLadder | None = None
    range_baseline = 0.0
    range_lo = range_hi = 0.0
    seed_phantom_total = 0.0
    seed_phantom_per_cell: dict[int, float] = {}
    seed_phantom_remaining: dict[int, float] = {}
    realized_phantom = 0.0
    last_ref = hourly_bars[0].open
    last_switch_bar: int | None = None

    switch_count = 0
    switch_tax = 0.0
    range_harvest = 0.0
    whipsaw_cost = 0.0
    regime_bar_counts = {HybridRegime.UPTREND: 0, HybridRegime.RANGE: 0, HybridRegime.BELOW: 0}

    grid_curve: list[float] = []
    yr_first_grid: dict[int, float] = {}
    yr_last_grid: dict[int, float] = {}
    yr_first_hold: dict[int, float] = {}
    yr_last_hold: dict[int, float] = {}
    yr_crossings: dict[int, int] = {}

    for i, bar in enumerate(hourly_bars):
        regime = regime_by_date.get(bar.date, HybridRegime.BELOW)

        # mark the carried-forward position to this bar's close
        if mode == HybridRegime.UPTREND:
            equity = units * bar.close
        elif mode == HybridRegime.RANGE:
            equity = range_baseline + ladder.equity(bar.close) - seed_phantom_total

        rebuild = (
            mode == HybridRegime.RANGE and regime == HybridRegime.RANGE
            and (bar.close < range_lo or bar.close > range_hi)
        )

        crossings_before = (ladder.buy_fills + ladder.sell_fills) if ladder else 0

        if regime != mode or rebuild:
            tax = equity * taker_fee
            equity -= tax
            switch_tax += tax
            switch_count += 1
            if last_switch_bar is not None and (i - last_switch_bar) <= whipsaw_window_bars:
                whipsaw_cost += tax
            last_switch_bar = i

            if mode == HybridRegime.RANGE and ladder is not None:
                range_harvest += ladder.realized_quote - realized_phantom

            ladder = None
            units = 0.0
            seed_phantom_total = 0.0
            seed_phantom_per_cell = {}
            seed_phantom_remaining = {}
            realized_phantom = 0.0
            if regime == HybridRegime.UPTREND:
                units = equity / bar.close
            elif regime == HybridRegime.RANGE:
                range_baseline = equity
                center = close_by_date.get(bar.date, bar.close)
                sigma = sigma_by_date.get(bar.date)
                ladder, range_lo, range_hi, seed_phantom_per_cell = _seed_range_ladder(
                    center, sigma, z=z, horizon_days=range_horizon_days,
                    step=step, maker_fee=maker_fee, capital=range_baseline,
                )
                seed_phantom_total = sum(seed_phantom_per_cell.values())
                seed_phantom_remaining = dict(seed_phantom_per_cell)
                last_ref = bar.close
                crossings_before = ladder.buy_fills + ladder.sell_fills
            mode = regime
            if mode == HybridRegime.UPTREND:
                equity = units * bar.close
            elif mode == HybridRegime.RANGE:
                equity = range_baseline + ladder.equity(bar.close) - seed_phantom_total

        # --- intra-bar grid mechanics for RANGE (mirrors run_s1's crossing semantics) ---
        if mode == HybridRegime.RANGE:
            spec = ladder.spec
            prices = spec.prices
            held = [k for k in range(spec.n) if ladder.cells[k].holding]
            for k in held:
                if bar.high >= prices[k + 1]:
                    ladder.apply_sell_fill(k)
            # a seeded cell's phantom transfers from unrealized into realized_quote on
            # its first sale; consume it once here, before any same-bar rebuy masks it
            for k in list(seed_phantom_remaining):
                if not ladder.cells[k].holding:
                    realized_phantom += seed_phantom_remaining.pop(k)
            if bar.low < last_ref:
                left = bisect.bisect_left(prices, bar.low)
                right = bisect.bisect_left(prices, last_ref)
                for k in range(left, min(right, spec.n)):
                    if not ladder.cells[k].holding:
                        ladder.apply_buy_fill(k)
            equity = range_baseline + ladder.equity(bar.close) - seed_phantom_total

        grid_curve.append(equity)
        hold_eq = hold_curve[i]

        crossings = ((ladder.buy_fills + ladder.sell_fills) - crossings_before) if ladder else 0
        regime_bar_counts[mode] += 1
        y = _year_of(bar)
        if y not in yr_first_grid:
            yr_first_grid[y] = equity
            yr_first_hold[y] = hold_eq
            yr_crossings[y] = 0
        yr_last_grid[y] = equity
        yr_last_hold[y] = hold_eq
        yr_crossings[y] += crossings
        last_ref = bar.close

    if mode == HybridRegime.RANGE and ladder is not None:
        range_harvest += ladder.realized_quote - realized_phantom

    grid_total = grid_curve[-1] / grid_capital - 1.0
    hold_total = hold_curve[-1] / grid_capital - 1.0

    per_year: list[YearAttribution] = []
    for y in sorted(yr_first_grid):
        gr = yr_last_grid[y] / yr_first_grid[y] - 1.0 if yr_first_grid[y] else 0.0
        hr = yr_last_hold[y] / yr_first_hold[y] - 1.0 if yr_first_hold[y] else 0.0
        per_year.append(YearAttribution(
            year=y, grid_return=gr, hold_return=hr,
            grid_minus_hold=gr - hr, crossings=yr_crossings[y],
        ))

    n_bars = len(hourly_bars)
    regime_fractions = {
        "uptrend": regime_bar_counts[HybridRegime.UPTREND] / n_bars,
        "range": regime_bar_counts[HybridRegime.RANGE] / n_bars,
        "below": regime_bar_counts[HybridRegime.BELOW] / n_bars,
    }

    return S1eResult(
        n_hours=n_bars,
        grid_total_return=grid_total,
        hold_total_return=hold_total,
        grid_minus_hold=grid_total - hold_total,
        grid_max_drawdown=_max_drawdown(grid_curve),
        hold_max_drawdown=_max_drawdown(hold_curve),
        switch_count=switch_count,
        switch_tax=switch_tax / grid_capital,
        range_harvest=range_harvest / grid_capital,
        whipsaw_cost=whipsaw_cost / grid_capital,
        regime_fractions=regime_fractions,
        per_year=per_year,
        grid_curve=grid_curve,
        hold_curve=hold_curve,
    )


# ----------------------------------------------------------------------------------------
# H3: delta-neutral funding carry (docs/archive/legacy/grid-b/grid-binance-h3-plan.md)
#
# Strips the grid skin. A long-only grid is a degenerate short-gamma position; once you
# delta-hedge its inventory with a perp short (``PerpHedgeLeg``), the harvest (θ) and the
# rehedge cost (½Γ(dS)²) cancel, leaving funding carry as the only possible edge. Two
# configs share one loop:
#
#   mode="static" (H3-A, the *true* baseline): a constant spot long + constant perp short.
#       No grid harvest; net = funding − fees − tail. This is the pure carry.
#   mode="grid"   (H3-B): spot runs the (ungated) grid, perp rehedges inventory to Δ=0 each
#       bar at the bar's *worst* price. Predicted < H3-A (洞1: the grid's inventory is
#       anti-correlated with price, hence anti-phase with funding).
#
# Orthogonal PnL decomposition that sums *exactly* to ``net_return`` (over capital):
#   harvest + spot_inventory + perp_directional + funding − fee_cost == net
# where ``offset_residual = spot_inventory + perp_directional`` is the delta-neutral
# residual (≈ 0 when hedging works, = basis when it dislocates). Grid maker fees are netted
# inside ``harvest``; ``fee_cost`` carries the explicit taker costs (perp rehedge + the
# static spot buy). Funding accrues on the *time-varying* short notional (洞3); a violent
# up-bar force-covers part of the short via ADL (洞4).
# ----------------------------------------------------------------------------------------


@dataclass
class H3YearAttribution:
    year: int
    net_return: float


@dataclass
class H3Result:
    mode: str
    n_hours: int
    net_return: float
    # orthogonal decomposition (each over capital), sums to net_return:
    harvest_pnl: float            # grid round-trips, fee-netted (0 in static)
    spot_inventory_pnl: float     # spot leg directional mark
    perp_directional_pnl: float   # perp realized + unrealized short PnL
    funding_pnl: float            # carry on the time-varying short notional
    fee_cost: float               # explicit taker: perp rehedge + static spot buy (>= 0)
    liq_cost: float               # physical liquidation tail: penalty + intrabar gap (>= 0)
    offset_residual: float        # spot_inventory + perp_directional (≈0 = hedge works)
    adl_events: int
    liq_events: int
    rehedge_count: int
    worst_basis: float            # max |spot-perp|/spot seen
    max_drawdown: float
    final_notional: float = 0.0   # equity-normalized carry: ending leg notional
    final_equity: float = 0.0     # equity-normalized carry: ending equity
    per_year: list[H3YearAttribution] = field(default_factory=list)
    curve: list[float] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        won = sum(1 for y in self.per_year if y.net_return > 0)
        return (
            f"h3-{self.mode} net {self.net_return:+.2%}; won {won}/{len(self.per_year)}y; "
            f"funding {self.funding_pnl:+.2%} / fees {self.fee_cost:.2%} / "
            f"liq {self.liq_cost:.2%} ({self.liq_events}x); "
            f"offset_resid {self.offset_residual:+.2%}; "
            f"rehedges {self.rehedge_count}, worst_basis {self.worst_basis:.1%}"
        )


def run_h3(
    spot_bars: list[Bar],
    perp_bars: list[Bar],
    funding: list[Funding],
    *,
    mode: str = "static",
    capital: float = 1.0,
    spot_taker: float = 0.0010,
    perp_taker: float = 0.0005,
    step: float = 0.01,
    maker_fee: float = 0.00075,
    lower: float | None = None,
    upper: float | None = None,
    enable_adl: bool = False,
    adl_up_threshold: float = 0.20,
    adl_fraction: float = 0.5,
    liq_leverage: float | None = None,
    mm_rate: float = 0.005,
    liq_penalty: float = 0.015,
) -> H3Result:
    """Run the H3 delta-neutral carry kill-test over aligned spot/perp hourly bars.

    ``spot_bars`` and ``perp_bars`` must be 1:1 aligned (same length, same timeline).
    ``funding`` is the UM settlement series; each settlement is accrued once, on the short
    notional *after* that bar's rehedge, marked at the spot close. ``mode`` selects H3-A
    (``"static"``) or H3-B (``"grid"``).

    ``enable_adl`` is OFF by default: the first cut is the *generous upper bound* -- a
    delta-neutral carry with **no liquidation / infinite margin** (the growing short on a
    pumping coin is never margin-squeezed). This mirrors S1's look-ahead range: if even the
    upper bound fails, dead; the margin/ADL tail is a deferred, separate stress (the crude
    per-bar ADL model is reusable via ``PerpHedgeLeg.adl_cover`` but is not a clean test).

    ``liq_leverage`` (None = upper bound) turns on the **physical liquidation tail gate**:
    the short is margined at ``liq_leverage``× and margin is rebalanced each bar close. The
    key insight -- a liquidation is NOT a full-margin loss, because the spot long gained
    exactly what the short lost; the *net* tail cost per liquidation is only the forced-close
    penalty + the intrabar gap *beyond* the liquidation price (you can't react inside a bar)
    + re-entry. So liquidation triggers when ``bar_high / prev_close - 1 > 1/L - mm_rate``
    and costs ``notional × (liq_penalty + gap_beyond_liq_price)`` -- small per event, but it
    lands in exactly the violent pumps where the gap is largest. The short is kept (delta
    maintained); only the penalty+gap is charged.
    """

    if not spot_bars or not perp_bars:
        raise ValueError("need both spot and perp bars")
    if len(spot_bars) != len(perp_bars):
        raise ValueError("spot and perp bars must be 1:1 aligned")
    if mode not in ("static", "grid"):
        raise ValueError(f"mode must be 'static' or 'grid', got {mode!r}")

    fund = sorted(funding, key=lambda f: f.ts_ms)
    fi = 0
    leg = PerpHedgeLeg(taker_fee=perp_taker, slippage=0.0)

    spot0 = spot_bars[0].open
    perp0 = perp_bars[0].open

    ladder: GridLadder | None = None
    spec: GridSpec | None = None
    prices: tuple[float, ...] = ()
    last_ref = spot0
    spot_base_static = 0.0
    spot_buy_fee = 0.0

    if mode == "grid":
        lo = lower if lower is not None else min(b.low for b in spot_bars)
        hi = upper if upper is not None else max(b.high for b in spot_bars)
        spec = build_grid(lower=lo, upper=hi, grid_capital=capital,
                          step=step, maker_fee=maker_fee)
        ladder = GridLadder(spec=spec, maker_fee=maker_fee)
        prices = spec.prices
    else:  # static: constant spot long + constant perp short, opened once
        spot_base_static = capital / spot0
        spot_buy_fee = capital * spot_taker
        leg.rehedge(target_short_base=spot_base_static, fill_price=perp0)

    curve: list[float] = []
    yr_first: dict[int, float] = {}
    yr_last: dict[int, float] = {}
    prev_perp_close = perp0
    worst_basis = 0.0
    liq_cost = 0.0
    liq_events = 0
    liq_buffer = (1.0 / liq_leverage - mm_rate) if liq_leverage else None

    for sb, pb in zip(spot_bars, perp_bars):
        # --- spot grid fills (grid mode only); determine the delta-neutral target short ---
        if ladder is not None:
            held = [k for k in range(spec.n) if ladder.cells[k].holding]
            for k in held:
                if pb is not None and sb.high >= prices[k + 1]:
                    ladder.apply_sell_fill(k)
            if sb.low < last_ref:
                left = bisect.bisect_left(prices, sb.low)
                right = bisect.bisect_left(prices, last_ref)
                for k in range(left, min(right, spec.n)):
                    if not ladder.cells[k].holding:
                        ladder.apply_buy_fill(k)
            last_ref = sb.close
            target_short = max(0.0, ladder.inventory_base)  # guard float dust < 0
        else:
            target_short = spot_base_static

        # --- ADL on a violent up-bar (perp), force-covering part of the winning short ---
        # OFF by default: the upper-bound cut assumes no liquidation (see docstring). The
        # per-bar trigger is a crude proxy, deferred to a dedicated tail stress.
        if enable_adl:
            up = pb.high / prev_perp_close - 1.0 if prev_perp_close else 0.0
            if up > adl_up_threshold and leg.short_base > 0.0:
                leg.adl_cover(fraction=adl_fraction, fill_price=pb.high)

        # --- rehedge to delta-neutral at the bar's worst perp price (sell@low, buy@high) ---
        delta = target_short - leg.short_base
        if abs(delta) > 1e-12:
            fill = pb.low if delta > 0 else pb.high
            leg.rehedge(target_short_base=target_short, fill_price=fill)

        # --- physical liquidation tail: short blown out by an intrabar pump past the
        #     liq price; net cost = forced-close penalty + the gap *beyond* liq (spot offset
        #     covers the rest). Margin is assumed rebalanced at the prior close. ---
        if liq_buffer is not None and liq_buffer > 0.0 and leg.short_base > 0.0:
            if pb.high / prev_perp_close - 1.0 > liq_buffer:
                liq_price = prev_perp_close * (1.0 + liq_buffer)
                gap = max(0.0, pb.high / liq_price - 1.0)
                notional = leg.short_base * liq_price
                liq_cost += notional * (liq_penalty + gap)
                liq_events += 1

        # --- funding settlements up to this bar, on the post-rehedge notional (洞3) ---
        while fi < len(fund) and fund[fi].ts_ms <= sb.ts_ms:
            leg.accrue_funding(fund[fi].rate, sb.close)
            fi += 1

        # --- mark portfolio ---
        if ladder is not None:
            spot_eq = ladder.equity(sb.close)             # realized harvest + inventory
        else:
            spot_eq = spot_base_static * (sb.close - spot0)
        total = capital + spot_eq + leg.equity(pb.close) - spot_buy_fee - liq_cost
        curve.append(total)

        worst_basis = max(worst_basis, abs(sb.close - pb.close) / sb.close)
        prev_perp_close = pb.close
        y = _year_of(sb)
        if y not in yr_first:
            yr_first[y] = total
        yr_last[y] = total

    spot_end = spot_bars[-1].close
    perp_end = perp_bars[-1].close

    if ladder is not None:
        harvest = ladder.realized_quote / capital
        spot_inventory = (ladder.inventory_base * spot_end - ladder.inventory_cost_quote) / capital
        grid_maker_fees_inside_harvest = ladder.fees_paid  # documented: netted in harvest
    else:
        harvest = 0.0
        spot_inventory = spot_base_static * (spot_end - spot0) / capital

    perp_directional = (leg.realized_pnl + leg.short_base * (leg.short_avg_price - perp_end)) / capital
    funding_pnl = leg.funding_pnl / capital
    fee_cost = (leg.fees_paid + spot_buy_fee) / capital
    liq_cost_frac = liq_cost / capital
    net_return = curve[-1] / capital - 1.0

    per_year = [
        H3YearAttribution(year=y, net_return=yr_last[y] / yr_first[y] - 1.0 if yr_first[y] else 0.0)
        for y in sorted(yr_first)
    ]

    return H3Result(
        mode=mode,
        n_hours=len(spot_bars),
        net_return=net_return,
        harvest_pnl=harvest,
        spot_inventory_pnl=spot_inventory,
        perp_directional_pnl=perp_directional,
        funding_pnl=funding_pnl,
        fee_cost=fee_cost,
        liq_cost=liq_cost_frac,
        offset_residual=spot_inventory + perp_directional,
        adl_events=leg.adl_events,
        liq_events=liq_events,
        rehedge_count=leg.rehedge_count,
        worst_basis=worst_basis,
        max_drawdown=_max_drawdown(curve),
        per_year=per_year,
        curve=curve,
    )


# ----------------------------------------------------------------------------------------
# H3 equity-normalized carry (§8.5 fix): the *correct* sizing for the final verdict.
#
# The §8.3/§8.5 disease: a constant-coin-base delta-neutral position lets the dollar
# notional balloon with price (DOGE pumps 80x -> notional 80x cap), so everything measured
# against *initial* capital is scale-distorted, monthly returns breach -100%, and the
# portfolio chain (∏(1+r)) flips to garbage. The fix, as any real carry book runs: size the
# position to a *target notional = k_gross × current equity* and rebalance periodically. Then
# returns are always vs current equity, the notional never balloons, funding accrues on a
# bounded notional, liquidation cost is bounded, and equity stays positive (no sub--100%
# month). Directional PnL cancels (delta-neutral) up to basis; net is driven by
# funding − rebalance fees − liquidation. This is what gives H3-A its honest final verdict.
# ----------------------------------------------------------------------------------------


def run_h3_carry(
    spot_bars: list[Bar],
    perp_bars: list[Bar],
    funding: list[Funding],
    *,
    capital: float = 1.0,
    k_gross: float = 1.0,
    liq_leverage: float | None = 3.0,
    mm_rate: float = 0.005,
    liq_penalty: float = 0.015,
    rebalance_hours: int = 24,
    spot_taker: float = 0.0010,
    perp_taker: float = 0.0005,
) -> H3Result:
    """Equity-normalized delta-neutral carry: notional rebalanced to ``k_gross × equity``.

    Long spot + short perp, both sized so the leg notional tracks ``k_gross × equity``,
    rebalanced every ``rebalance_hours`` (which is also the margin top-up cadence for the
    liquidation check). Funding accrues on the *current* short notional; liquidation fires
    when an intrabar pump exceeds ``1/liq_leverage − mm_rate`` above the last rebalance
    price, costing ``notional × (liq_penalty + gap)`` -- all bounded by ``k_gross × equity``.
    Returns an :class:`H3Result` (mode ``"carry"``); the decomposition still sums to net.
    """

    if not spot_bars or not perp_bars:
        raise ValueError("need both spot and perp bars")
    if len(spot_bars) != len(perp_bars):
        raise ValueError("spot and perp bars must be 1:1 aligned")

    fund = sorted(funding, key=lambda f: f.ts_ms)
    fi = 0
    buffer = (1.0 / liq_leverage - mm_rate) if liq_leverage else None

    spot0, perp0 = spot_bars[0].open, perp_bars[0].open
    equity = capital
    notional = k_gross * equity
    spot_base = notional / spot0
    short_base = notional / perp0
    fees = notional * (spot_taker + perp_taker)   # open spot long + perp short
    equity -= fees
    prev_spot, prev_perp = spot0, perp0
    ref_perp = perp0                              # liquidation reference (margin set here)

    dir_total = 0.0
    funding_total = 0.0
    liq_total = 0.0
    liq_events = 0
    rebalances = 0
    worst_basis = 0.0
    curve: list[float] = []
    yr_first: dict[int, float] = {}
    yr_last: dict[int, float] = {}

    for i, (sb, pb) in enumerate(zip(spot_bars, perp_bars)):
        # directional PnL this bar (delta-neutral residual = basis move) on held coin bases
        dpnl = spot_base * (sb.close - prev_spot) - short_base * (pb.close - prev_perp)
        equity += dpnl
        dir_total += dpnl

        # liquidation: intrabar pump past the liq price set at the last rebalance. The short
        # is force-closed (margin lost = penalty + gap, bounded by notional), then the carry
        # is RE-ESTABLISHED on remaining equity at the current price -- exactly as a real
        # account would re-open after a liquidation. This stops the stale-ref repeat-charge.
        if buffer is not None and buffer > 0.0 and short_base > 0.0:
            if pb.high / ref_perp - 1.0 > buffer:
                liq_price = ref_perp * (1.0 + buffer)
                gap = max(0.0, pb.high / liq_price - 1.0)
                cost = short_base * liq_price * (liq_penalty + gap)
                equity -= cost
                liq_total += cost
                liq_events += 1
                if equity > 0.0:
                    notional = k_gross * equity
                    reopen_fee = notional * (spot_taker + perp_taker)
                    equity -= reopen_fee
                    fees += reopen_fee
                    spot_base = notional / sb.close
                    short_base = notional / pb.close
                    ref_perp = pb.close
                else:
                    spot_base = short_base = 0.0

        # funding settlements up to this bar, on the current short notional
        while fi < len(fund) and fund[fi].ts_ms <= sb.ts_ms:
            f = fund[fi].rate * short_base * pb.close
            equity += f
            funding_total += f
            fi += 1

        prev_spot, prev_perp = sb.close, pb.close

        # periodic rebalance to k_gross × equity (also the margin top-up)
        if (i + 1) % rebalance_hours == 0 and equity > 0.0:
            notional = k_gross * equity
            new_spot_base = notional / sb.close
            new_short_base = notional / pb.close
            fee = (abs(new_spot_base - spot_base) * sb.close * spot_taker
                   + abs(new_short_base - short_base) * pb.close * perp_taker)
            equity -= fee
            fees += fee
            spot_base, short_base = new_spot_base, new_short_base
            ref_perp = pb.close
            rebalances += 1

        worst_basis = max(worst_basis, abs(sb.close - pb.close) / sb.close)
        curve.append(equity)
        y = _year_of(sb)
        if y not in yr_first:
            yr_first[y] = equity
        yr_last[y] = equity

    per_year = [
        H3YearAttribution(year=y, net_return=yr_last[y] / yr_first[y] - 1.0 if yr_first[y] else 0.0)
        for y in sorted(yr_first)
    ]
    final_notional = short_base * perp_bars[-1].close
    return H3Result(
        mode="carry",
        n_hours=len(spot_bars),
        net_return=equity / capital - 1.0,
        harvest_pnl=0.0,
        spot_inventory_pnl=dir_total / capital,
        perp_directional_pnl=0.0,
        funding_pnl=funding_total / capital,
        fee_cost=fees / capital,
        liq_cost=liq_total / capital,
        offset_residual=dir_total / capital,
        adl_events=0,
        liq_events=liq_events,
        rehedge_count=rebalances,
        worst_basis=worst_basis,
        max_drawdown=_max_drawdown(curve),
        final_notional=final_notional,
        final_equity=equity,
        per_year=per_year,
        curve=curve,
    )
