"""Daily numpy simulator: decide at close t, fill at open t+1 (design §5–§6).

Accounting is in shares and *unadjusted* prices; the total return carried by the adjusted
close beyond the unadjusted move (dividends / distributions) is credited to cash, so equity
compounds at the adjusted return.  Splits are not modelled (generated worlds have none; the
P0 data contract must deliver split-consistent unadjusted prices).

The ADV fill cap is not carried as an order book: the policy re-decides every day and the
constraint layer recomputes the gap, which re-requests the deferred part (§5.1 "顺延").
The torch env used for training must reproduce :func:`simulate` day by day (§10).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import constraints as C
from .costs import CostParams, trade_cost
from .universe import Account

TRADING_DAYS = 252


class EnvError(ValueError):
    pass


@dataclass(frozen=True)
class MarketData:
    close_adj: np.ndarray  # (T, n) total-return close
    close: np.ndarray  # (T, n) unadjusted close
    open: np.ndarray  # (T, n) unadjusted open
    adv: np.ndarray  # (T, n) 20-day traded value, account currency
    sigma: np.ndarray  # (T, n) daily return vol used by the impact model
    cash_return: np.ndarray  # (T,) cash return credited over day t (row 0 unused)
    suspended: np.ndarray | None = None  # (T, n) bool
    spread: np.ndarray | None = None  # (T, n) half spread (fraction); used by costs and deterioration
    buy_blocked: np.ndarray | None = None  # (T, n) bool, e.g. QDII quota: buys void, sells allowed

    def __post_init__(self) -> None:
        shape = np.shape(self.close_adj)
        for name in ("close", "open", "adv", "sigma"):
            if np.shape(getattr(self, name)) != shape:
                raise EnvError(f"{name} must match close_adj {shape}")
        if np.shape(self.cash_return) != shape[:1]:
            raise EnvError("cash_return must be (T,)")

    @property
    def T(self) -> int:
        return self.close_adj.shape[0]

    @property
    def n(self) -> int:
        return self.close_adj.shape[1]


@dataclass(frozen=True)
class Observation:
    t: int
    weights: np.ndarray  # current risk weights at close t
    equity: float
    gross_cap: float
    drawdown: float
    derisked: bool
    used_voluntary: float
    budget: float


@dataclass(frozen=True)
class Decision:
    target: np.ndarray | None  # None: no voluntary trade today (forced de-risk still applies)
    band: float = 0.0
    kappa: float = 1.0


Policy = Callable[[Observation], Decision]


@dataclass(frozen=True)
class SimResult:
    equity: np.ndarray  # (T,) close equity; NaN before start
    weights: np.ndarray  # (T, n) close weights
    returns: np.ndarray  # (T,) daily net return
    costs: np.ndarray  # (T,) cost paid at the open of t
    voluntary_turnover: np.ndarray
    forced_turnover: np.ndarray
    voided: np.ndarray  # (T, n)
    forced_breach: np.ndarray  # (T,)
    gross_cap: np.ndarray  # (T,) cap in force for the decision at close t
    start: int


def simulate(
    data: MarketData,
    account: Account,
    policy: Policy,
    costs: CostParams,
    *,
    start: int = 0,
    initial_equity: float = 1_000_000.0,
    cost_multiplier: float = 1.0,
    min_adv: float = 0.0,
    derisk: C.DeRisk | None = None,
    budget: C.TurnoverBudget | None = None,
) -> SimResult:
    T, n = data.T, data.n
    if n != account.n_assets:
        raise EnvError("data columns must match the account's assets")
    if not 0 <= start < T - 1:
        raise EnvError("start must leave at least one fill day")
    derisk = derisk or C.DeRisk()
    budget = budget or C.TurnoverBudget(account.turnover_budget)
    suspended = np.zeros((T, n), bool) if data.suspended is None else np.asarray(data.suspended, bool)
    blocked = np.zeros((T, n), bool) if data.buy_blocked is None else np.asarray(data.buy_blocked, bool)
    reduce_only = C.reduce_only_mask(data.adv, data.spread, min_adv=min_adv)

    equity = np.full(T, np.nan)
    weights = np.zeros((T, n))
    rets = np.zeros(T)
    paid = np.zeros(T)
    vol_to = np.zeros(T)
    frc_to = np.zeros(T)
    voided = np.zeros((T, n), bool)
    breach = np.zeros(T, bool)
    caps = np.ones(T)

    shares = np.zeros(n)
    cash = float(initial_equity)
    equity[start] = cash
    for t in range(start, T - 1):
        # --- close t: mark, update de-risk state, ask the policy
        eq_t = equity[t]
        weights[t] = shares * data.close[t] / eq_t
        cap = derisk.update(eq_t)
        caps[t] = cap
        obs = Observation(
            t=t,
            weights=weights[t].copy(),
            equity=eq_t,
            gross_cap=cap,
            drawdown=derisk.drawdown(),
            derisked=cap < 1.0,
            used_voluntary=budget.used_voluntary,
            budget=budget.budget,
        )
        dec = policy(obs)

        # --- open t+1: re-mark at the open and run the constraint layer
        u = t + 1
        opn = np.asarray(data.open[u], dtype=float)
        mark = np.where(np.isfinite(opn) & (opn > 0), opn, data.close[t])
        eq_open = cash + float(shares @ mark)
        if eq_open <= 0:
            raise EnvError(f"equity exhausted at row {u}")
        current = shares * mark / eq_open
        # Fees on a fully invested book can leave cash slightly negative; "hold" then
        # means hold at gross ≤ 1, which also repays that sliver.
        hold = C.scale_to_gross(np.maximum(current, 0.0), 1.0)
        target = hold if dec.target is None else np.asarray(dec.target, dtype=float)
        step = C.constrain_step(
            C.StepInputs(
                target=target,
                current=current,
                holdings=shares,
                equity=eq_open,
                open_price=opn,
                prev_close_unadj=data.close[t],
                adv=data.adv[t],  # known at the decision close
                reduce_only=reduce_only[t],
                suspended=suspended[u],
                buy_blocked=blocked[u],
                gross_cap=cap,
                band=dec.band if dec.target is not None else 0.0,
                kappa=dec.kappa if dec.target is not None else 1.0,
            ),
            account,
            budget,
        )
        notional = step.shares * mark
        half = None if data.spread is None else data.spread[t]
        fee = float(
            trade_cost(notional, mark, data.adv[t], data.sigma[t], costs, cost_multiplier, half_spread=half).sum()
        )
        shares = shares + step.shares
        cash -= float(notional.sum()) + fee
        paid[u] = fee
        vol_to[u] = step.voluntary_turnover
        frc_to[u] = step.forced_turnover
        voided[u] = step.voided
        breach[u] = step.forced_breach

        # --- close t+1: cash carry and distributions, then mark
        cash *= 1.0 + float(data.cash_return[u])
        adj_ret = data.close_adj[u] / data.close_adj[t] - 1.0
        px_ret = data.close[u] / data.close[t] - 1.0
        dist = np.nan_to_num(shares * data.close[t] * (adj_ret - px_ret))
        cash += float(dist.sum())
        equity[u] = cash + float(np.nansum(shares * data.close[u]))
        rets[u] = equity[u] / eq_t - 1.0
    weights[T - 1] = shares * data.close[T - 1] / equity[T - 1]
    caps[T - 1] = caps[T - 2]
    return SimResult(
        equity=equity,
        weights=weights,
        returns=rets,
        costs=paid,
        voluntary_turnover=vol_to,
        forced_turnover=frc_to,
        voided=voided,
        forced_breach=breach,
        gross_cap=caps,
        start=start,
    )


# ---------------------------------------------------------------------------
# Metrics


def max_drawdown(equity: np.ndarray) -> float:
    e = np.asarray(equity, dtype=float)
    e = e[np.isfinite(e)]
    if e.size == 0:
        return 0.0
    return float(np.max(1.0 - e / np.maximum.accumulate(e)))


def summarize(res: SimResult) -> dict[str, float]:
    r = res.returns[res.start + 1 :]
    years = max(r.size / TRADING_DAYS, 1e-9)
    eq = res.equity[res.start :]
    sd = float(np.std(r, ddof=1)) if r.size > 1 else 0.0
    return {
        "cagr": float((eq[-1] / eq[0]) ** (1.0 / years) - 1.0),
        "sharpe": float(np.mean(r) / sd * np.sqrt(TRADING_DAYS)) if sd > 0 else 0.0,
        "max_drawdown": max_drawdown(eq),
        "turnover_voluntary_per_year": float(res.voluntary_turnover.sum() / years),
        "turnover_forced_per_year": float(res.forced_turnover.sum() / years),
        "cost_drag_per_year": float(np.sum(res.costs / np.where(np.isfinite(res.equity), res.equity, np.inf)) / years),
        "days_derisked": int(np.sum(res.gross_cap[res.start :] < 1.0)),
        "forced_breaches": int(res.forced_breach.sum()),
    }


def max_rolling_turnover(daily: np.ndarray, window: int = C.TURNOVER_WINDOW) -> float:
    d = np.asarray(daily, dtype=float)
    if d.size < window:
        return float(d.sum())
    cs = np.concatenate([[0.0], np.cumsum(d)])
    return float(np.max(cs[window:] - cs[:-window]))
