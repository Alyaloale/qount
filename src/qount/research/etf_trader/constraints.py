"""Hard constraint layer, applied in the §5 order.

1. liquidity admission / deterioration (reduce-only) and capacity-based position caps;
2. drawdown de-risking with an explicit recovery rule;
3. soft no-trade band with partial adjustment (§3.2);
4. rolling 252-day one-way turnover budget U, forced de-risk turnover booked separately;
5. market rules: CN ±limit on the unadjusted previous close, suspension, T+1, lot rounding,
   plus the 5%·ADV daily fill cap (§6).

Weights are fractions of account equity for the risk assets only; cash is implicit
(``1 - sum(w)``). All weights are long-only. Defaults (D1/D2, U, admission ADV) are §12
owner items and remain configurable.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .universe import Account

DEFAULT_D1 = 0.10
DEFAULT_D2 = 0.15
D1_GROSS_CAP = 0.50
D2_GROSS_CAP = 0.20
RECOVERY_MIN_DAYS = 63
RECOVERY_LOOKBACK = 126
TURNOVER_WINDOW = 252
FORCED_TOTAL_MULTIPLE = 1.5
MAX_ADV_FRACTION = 0.05
CAPACITY_DAYS = 3
ADV_DETERIORATION = 0.30
SPREAD_DETERIORATION = 3.0
LIQUIDITY_WINDOW = 252
EPS = 1e-12


class ConstraintError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 1. Liquidity
# ---------------------------------------------------------------------------


def rolling_median(x: np.ndarray, window: int, min_periods: int | None = None) -> np.ndarray:
    """Trailing NaN-aware median including the current row; NaN until ``min_periods`` finite."""
    x = np.asarray(x, dtype=float)
    if x.ndim != 2:
        raise ConstraintError("expected a (T, n) panel")
    min_periods = window if min_periods is None else min_periods
    out = np.full_like(x, np.nan)
    if x.shape[0] == 0:
        return out
    padded = np.vstack([np.full((window - 1, x.shape[1]), np.nan), x])
    windows = sliding_window_view(padded, window, axis=0)  # (T, n, window)
    count = np.isfinite(windows).sum(axis=-1)
    ok = count >= max(min_periods, 1)
    with np.errstate(all="ignore"):
        med = np.nanmedian(np.where(ok[..., None], windows, 0.0), axis=-1)
    out[ok] = med[ok]
    return out


def reduce_only_mask(
    adv20: np.ndarray,
    spread: np.ndarray | None = None,
    min_adv: float = 0.0,
    window: int = LIQUIDITY_WINDOW,
    min_periods: int | None = None,
) -> np.ndarray:
    """(T, n) bool: asset may only be reduced (admission floor or liquidity deterioration).

    Missing ADV is treated as illiquid. Deterioration tests need ``min_periods`` of history;
    before that only the admission floor applies.
    """
    adv20 = np.asarray(adv20, dtype=float)
    mask = ~np.isfinite(adv20) | (adv20 < min_adv)
    med = rolling_median(adv20, window, min_periods)
    with np.errstate(invalid="ignore"):
        mask |= np.isfinite(med) & (adv20 < ADV_DETERIORATION * med)
    if spread is not None:
        spread = np.asarray(spread, dtype=float)
        if spread.shape != adv20.shape:
            raise ConstraintError("spread and adv20 shapes differ")
        smed = rolling_median(spread, window, min_periods)
        with np.errstate(invalid="ignore"):
            mask |= np.isfinite(smed) & (spread > SPREAD_DETERIORATION * smed)
    return mask


def capacity_cap(
    adv: np.ndarray,
    equity: float,
    single_cap: float,
    days: int = CAPACITY_DAYS,
    fraction: float = MAX_ADV_FRACTION,
) -> np.ndarray:
    """Position cap min(single_cap, days·fraction·ADV / equity): sellable within ``days`` sessions."""
    if equity <= 0:
        raise ConstraintError("equity must be positive")
    adv = np.nan_to_num(np.asarray(adv, dtype=float), nan=0.0)
    return np.minimum(single_cap, days * fraction * np.maximum(adv, 0.0) / equity)


def apply_liquidity(
    target: np.ndarray, current: np.ndarray, reduce_only: np.ndarray, cap: np.ndarray
) -> np.ndarray:
    """Reduce-only assets cannot exceed their current weight; every asset is capped by capacity."""
    target = np.asarray(target, dtype=float)
    current = np.asarray(current, dtype=float)
    out = np.where(np.asarray(reduce_only, dtype=bool), np.minimum(target, current), target)
    return np.minimum(out, np.asarray(cap, dtype=float))


# ---------------------------------------------------------------------------
# 2. De-risk with recovery
# ---------------------------------------------------------------------------


@dataclass
class DeRisk:
    """Drawdown state machine producing a gross-exposure cap.

    Recovery (cap back to 1.0) happens when the drawdown narrows to within D1/2, or when the
    cap has been active ≥ ``min_days`` and the trailing ``lookback``-day return is positive.
    On time-based recovery the high-water mark is reset to current equity so the same,
    unchanged drawdown does not re-trigger immediately (implementation choice, not in §5).
    """

    d1: float = DEFAULT_D1
    d2: float = DEFAULT_D2
    cap1: float = D1_GROSS_CAP
    cap2: float = D2_GROSS_CAP
    min_days: int = RECOVERY_MIN_DAYS
    lookback: int = RECOVERY_LOOKBACK
    peak: float = field(default=float("nan"), init=False)
    cap: float = field(default=1.0, init=False)
    days_capped: int = field(default=0, init=False)
    _history: deque = field(default_factory=deque, init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0 < self.d1 < self.d2 < 1:
            raise ConstraintError("need 0 < D1 < D2 < 1")
        if not 0 <= self.cap2 <= self.cap1 <= 1:
            raise ConstraintError("need 0 <= cap2 <= cap1 <= 1")
        self._history = deque(maxlen=self.lookback + 1)

    def drawdown(self) -> float:
        if not self._history or not np.isfinite(self.peak):
            return 0.0
        return 1.0 - self._history[-1] / self.peak

    def update(self, equity: float) -> float:
        """Feed today's closing equity; return the gross cap for the next decision."""
        if not equity > 0:
            raise ConstraintError("equity must be positive")
        self._history.append(float(equity))
        self.peak = equity if not np.isfinite(self.peak) else max(self.peak, equity)
        dd = self.drawdown()

        if self.cap < 1.0:
            self.days_capped += 1
            trailing = (
                len(self._history) > self.lookback and self._history[-1] / self._history[0] - 1.0 > 0
            )
            if dd <= self.d1 / 2:
                self._release()
            elif self.days_capped >= self.min_days and trailing:
                self._release()
                self.peak = float(equity)
                return self.cap

        if dd > self.d2:
            self._engage(self.cap2)
        elif dd > self.d1:
            self._engage(self.cap1)
        return self.cap

    def _engage(self, cap: float) -> None:
        if cap < self.cap:
            if self.cap == 1.0:
                self.days_capped = 0
            self.cap = cap

    def _release(self) -> None:
        self.cap = 1.0
        self.days_capped = 0


def scale_to_gross(weights: np.ndarray, cap: float) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    gross = weights.sum()
    return weights * (cap / gross) if gross > cap + EPS else weights.copy()


def limit_buys_to_gross(base: np.ndarray, delta: np.ndarray, cap: float) -> np.ndarray:
    """Scale the buy side of ``delta`` so that ``sum(base + delta) <= cap`` (sells untouched)."""
    delta = np.asarray(delta, dtype=float)
    buys = np.clip(delta, 0.0, None)
    excess = float(np.sum(base) + delta.sum() - cap)
    total_buy = buys.sum()
    if excess <= EPS or total_buy <= EPS:
        return delta.copy()
    keep = max(0.0, 1.0 - excess / total_buy)
    return np.where(delta > 0, delta * keep, delta)


# ---------------------------------------------------------------------------
# 3. Soft band
# ---------------------------------------------------------------------------


def soft_band(target: np.ndarray, current: np.ndarray, band: float, kappa: float) -> np.ndarray:
    """Δw = κ·sign(d)·max(0, |d| − b), d = target − current (§3.2)."""
    if not 0 <= band <= 0.10 + EPS or not 0.05 - EPS <= kappa <= 1 + EPS:
        raise ConstraintError("band must be in [0, 0.10] and kappa in [0.05, 1]")
    d = np.asarray(target, dtype=float) - np.asarray(current, dtype=float)
    return kappa * np.sign(d) * np.maximum(0.0, np.abs(d) - band)


# ---------------------------------------------------------------------------
# 4. Turnover budget
# ---------------------------------------------------------------------------


def one_way_turnover(delta: np.ndarray) -> float:
    return 0.5 * float(np.abs(np.asarray(delta, dtype=float)).sum())


@dataclass
class TurnoverBudget:
    """Rolling one-way turnover ledgers: voluntary ≤ U, voluntary + forced ≤ 1.5U.

    Forced trades are never scaled; if they alone break 1.5U the breach is reported.
    ``project`` is side-effect free; only executed trades are ``record``-ed, so trades voided
    by market rules do not consume budget.
    """

    budget: float
    window: int = TURNOVER_WINDOW
    total_multiple: float = FORCED_TOTAL_MULTIPLE
    _voluntary: deque = field(default_factory=deque, init=False, repr=False)
    _forced: deque = field(default_factory=deque, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.budget <= 0 or self.window <= 0:
            raise ConstraintError("budget and window must be positive")
        # Keep window-1 past days; today's trade completes the window.
        self._voluntary = deque(maxlen=self.window - 1)
        self._forced = deque(maxlen=self.window - 1)

    @property
    def used_voluntary(self) -> float:
        return float(sum(self._voluntary))

    @property
    def used_forced(self) -> float:
        return float(sum(self._forced))

    def project(self, voluntary: np.ndarray, forced: np.ndarray) -> tuple[np.ndarray, bool]:
        """Return (scaled voluntary delta, forced_breach)."""
        voluntary = np.asarray(voluntary, dtype=float)
        need_v = one_way_turnover(voluntary)
        need_f = one_way_turnover(forced)
        room_v = self.budget - self.used_voluntary
        room_total = self.total_multiple * self.budget - self.used_voluntary - self.used_forced - need_f
        room = max(0.0, min(room_v, room_total))
        scale = 1.0 if need_v <= room + EPS else room / need_v
        return voluntary * scale, room_total < -EPS

    def record(self, voluntary_turnover: float, forced_turnover: float) -> None:
        self._voluntary.append(float(voluntary_turnover))
        self._forced.append(float(forced_turnover))


# ---------------------------------------------------------------------------
# 5. Market rules
# ---------------------------------------------------------------------------


def tradable_sides(
    open_price: np.ndarray,
    prev_close_unadj: np.ndarray,
    suspended: np.ndarray,
    price_limit: float | None,
    tick: float,
) -> tuple[np.ndarray, np.ndarray]:
    """(can_buy, can_sell) at the open: limit-up blocks buys, limit-down blocks sells."""
    open_price = np.asarray(open_price, dtype=float)
    ok = ~np.asarray(suspended, dtype=bool) & np.isfinite(open_price) & (open_price > 0)
    can_buy, can_sell = ok.copy(), ok.copy()
    if price_limit is not None:
        prev = np.asarray(prev_close_unadj, dtype=float)
        # Exchange limits are rounded to the tick; half a tick tolerates that rounding.
        up = np.round(prev * (1 + price_limit) / tick) * tick
        down = np.round(prev * (1 - price_limit) / tick) * tick
        can_buy &= open_price < up - 0.5 * tick
        can_sell &= open_price > down + 0.5 * tick
    return can_buy, can_sell


def round_shares(
    desired_shares: np.ndarray,
    holdings: np.ndarray,
    locked: np.ndarray,
    lot_size: int,
    fractional: bool = False,
) -> np.ndarray:
    """Round signed share deltas toward zero to whole lots; sells never exceed unlocked holdings.

    Selling an entire unlocked position is allowed even if it is an odd lot (A-share rule:
    odd lots may be sold in one go). ``locked`` holds T+1 shares bought this session.
    """
    desired = np.asarray(desired_shares, dtype=float)
    holdings = np.asarray(holdings, dtype=float)
    sellable = np.maximum(holdings - np.asarray(locked, dtype=float), 0.0)
    desired = np.maximum(desired, -sellable)
    if fractional:
        return desired
    lots = np.trunc(desired / lot_size) * lot_size
    full_exit = (desired < 0) & np.isclose(-desired, sellable)
    return np.where(full_exit, -sellable, lots)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepInputs:
    target: np.ndarray  # risk-asset target weights after the scorer/policy
    current: np.ndarray  # current weights at the decision close
    holdings: np.ndarray  # shares held
    equity: float
    open_price: np.ndarray  # unadjusted fill price (t+1 open)
    prev_close_unadj: np.ndarray
    adv: np.ndarray  # 20-day traded value, account currency
    reduce_only: np.ndarray
    suspended: np.ndarray
    gross_cap: float  # from DeRisk
    band: float = 0.0
    kappa: float = 1.0
    locked: np.ndarray | None = None  # T+1 shares not yet sellable
    buy_blocked: np.ndarray | None = None  # buys void (QDII quota), sells allowed


@dataclass(frozen=True)
class StepResult:
    shares: np.ndarray  # signed executed share deltas
    delta_weight: np.ndarray  # executed Δw at the fill price
    voluntary_turnover: float
    forced_turnover: float
    budget_scale: float
    forced_breach: bool
    voided: np.ndarray  # assets whose trade was blocked by price limits / suspension
    deferred_notional: np.ndarray  # cut by the 5%·ADV daily cap


def constrain_step(inp: StepInputs, account: Account, budget: TurnoverBudget) -> StepResult:
    """Run §5 steps 1–5 for one decision and record executed turnover in ``budget``."""
    n = account.n_assets
    target = np.asarray(inp.target, dtype=float)
    current = np.asarray(inp.current, dtype=float)
    if target.shape != (n,) or current.shape != (n,):
        raise ConstraintError("weights must have one entry per risk asset")
    if np.any(target < -EPS) or target.sum() > 1 + 1e-9:
        raise ConstraintError("target must be long-only with gross <= 1")

    # 1. liquidity
    cap = capacity_cap(inp.adv, inp.equity, account.single_cap)
    target = apply_liquidity(target, current, inp.reduce_only, cap)
    # 2. de-risk: forced sells bring current gross to the cap proportionally
    target = scale_to_gross(target, inp.gross_cap)
    base = scale_to_gross(current, inp.gross_cap)
    forced = base - current
    # 3. soft band on the remaining gap, then keep gross within the cap
    voluntary = soft_band(target, base, inp.band, inp.kappa)
    voluntary = limit_buys_to_gross(base, voluntary, inp.gross_cap)
    # 4. turnover budget (voluntary only)
    need = one_way_turnover(voluntary)
    voluntary, breach = budget.project(voluntary, forced)
    scale = 1.0 if need <= EPS else one_way_turnover(voluntary) / need

    # 5. market rules
    delta = forced + voluntary
    can_buy, can_sell = tradable_sides(
        inp.open_price, inp.prev_close_unadj, inp.suspended, account.price_limit, account.tick
    )
    if inp.buy_blocked is not None:
        can_buy = can_buy & ~np.asarray(inp.buy_blocked, dtype=bool)
    blocked = ((delta > EPS) & ~can_buy) | ((delta < -EPS) & ~can_sell)
    delta = np.where(blocked, 0.0, delta)
    notional = delta * inp.equity
    limit = MAX_ADV_FRACTION * np.maximum(np.nan_to_num(np.asarray(inp.adv, dtype=float)), 0.0)
    executed_notional = np.clip(notional, -limit, limit)
    deferred = notional - executed_notional

    price = np.where(np.isfinite(inp.open_price) & (inp.open_price > 0), inp.open_price, 1.0)
    locked = np.zeros(n) if inp.locked is None else np.asarray(inp.locked, dtype=float)
    if inp.locked is None and account.t_plus_one:
        locked = np.zeros(n)
    shares = round_shares(
        executed_notional / price, inp.holdings, locked, account.lot_size, account.fractional_shares
    )
    shares = np.where(blocked, 0.0, shares)
    executed = shares * price / inp.equity

    # Attribute executed turnover: the part matching the forced direction is forced.
    same_side = np.sign(executed) == np.sign(forced)
    forced_exec = np.where(same_side, np.minimum(np.abs(executed), np.abs(forced)), 0.0)
    forced_turnover = 0.5 * float(forced_exec.sum())
    voluntary_turnover = one_way_turnover(executed) - forced_turnover
    budget.record(voluntary_turnover, forced_turnover)

    return StepResult(
        shares=shares,
        delta_weight=executed,
        voluntary_turnover=voluntary_turnover,
        forced_turnover=forced_turnover,
        budget_scale=scale,
        forced_breach=breach,
        voided=blocked,
        deferred_notional=deferred,
    )
