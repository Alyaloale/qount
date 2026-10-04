"""P3 event-aware no-order adapter to the existing costs and hard constraints.

P2's simulator and checkpoints remain unchanged. This adapter credits ex-date
entitlements to pre-fill holders and records actual affordable fills. Daily BIL
carry and immediately available ex-date cash are declared research assumptions,
not a payment-date or broker accounting certification.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from qount.research.etf_trader import constraints as C
from qount.research.etf_trader.costs import CostParams, cost_params_for, trade_cost
from qount.research.etf_trader.env import Decision, Observation, Policy, SimResult
from qount.research.etf_trader.scorer import daily_returns, rolling_mean, rolling_std
from qount.research.etf_trader.universe import Account, US_ACCOUNT

from .data import Panel, total_return_index


@dataclass(frozen=True)
class ExecutionInputs:
    adv: np.ndarray
    sigma: np.ndarray
    spread: np.ndarray
    reduce_only: np.ndarray
    cash_returns: np.ndarray


def execution_inputs(panel: Panel, costs: CostParams) -> ExecutionInputs:
    close_tr = total_return_index(panel.close, panel.dividends, panel.splits)
    adv = rolling_mean(panel.close * panel.volume, 20)
    sigma = rolling_std(daily_returns(close_tr), 63)
    spread = np.broadcast_to(np.asarray(costs.half_spread), adv.shape).copy()
    return ExecutionInputs(adv, sigma, spread, C.reduce_only_mask(adv, spread),
                           np.r_[0.0, panel.cash_close[1:] / panel.cash_close[:-1] - 1])


def project_caps(target: np.ndarray, account: Account) -> np.ndarray:
    target = np.asarray(target, float)
    if target.shape != (account.n_assets,) or not np.isfinite(target).all() or (target < -1e-12).any() or target.sum() > 1 + 1e-9:
        raise ValueError("finite long-only target with gross<=1 required")
    w = np.minimum(np.maximum(target, 0), account.single_cap)
    for group in account.group_indices():
        idx = list(group)
        if w[idx].sum() > account.group_cap:
            w[idx] *= account.group_cap / w[idx].sum()
    return w


@dataclass
class State:
    symbols: tuple[str, ...]
    next_close: int
    shares: np.ndarray
    cash: float
    derisk: C.DeRisk
    budget: C.TurnoverBudget


@dataclass(frozen=True)
class Ledger(SimResult):
    cash: np.ndarray
    shares: np.ndarray
    executed_shares: np.ndarray
    distributions: np.ndarray
    cash_carry: np.ndarray
    open_equity: np.ndarray
    targets: np.ndarray
    state: State


def _affordable(delta: np.ndarray, prices: np.ndarray, cash: float,
                adv: np.ndarray, sigma: np.ndarray, spread: np.ndarray,
                account: Account, costs: CostParams, multiplier: float) -> tuple[np.ndarray, float]:
    """Keep sells; shrink and lot-round buys to fund their complete costs."""
    def candidate(scale):
        buy = np.maximum(delta, 0) * scale
        if not account.fractional_shares:
            buy = np.trunc(buy / account.lot_size) * account.lot_size
        filled = np.minimum(delta, 0) + buy
        notional = filled * prices
        fee = float(trade_cost(notional, prices, adv, sigma, costs, multiplier, half_spread=spread).sum())
        remaining = cash - float(notional.sum()) - fee
        return filled, fee, remaining

    full = candidate(1.0)
    if full[2] >= -1e-8:
        return full[:2]
    low, high = 0.0, 1.0
    best = candidate(0.0)
    if best[2] < -1e-8:
        raise ValueError("cash cannot cover mandatory sell costs")
    for _ in range(40):
        mid = (low + high) / 2
        trial = candidate(mid)
        if trial[2] >= 0:
            low, best = mid, trial
        else:
            high = mid
    return best[:2]


def simulate(panel: Panel, policy: Policy, *, start: int, stop: int | None = None,
             account: Account = US_ACCOUNT, costs: CostParams | None = None,
             initial_equity: float = 1_000_000.0, cost_multiplier: float = 1.0,
             inputs: ExecutionInputs | None = None, state: State | None = None,
             derisk: C.DeRisk | None = None) -> Ledger:
    """Close decisions, next-open fills; contiguous calls carry DD and budgets."""
    T, n = panel.close.shape
    stop = T - 1 if stop is None else stop
    if account.symbols != panel.symbols or not 0 <= start < stop < T:
        raise ValueError("account order and nonempty valid execution interval required")
    if initial_equity <= 0 or cost_multiplier <= 0:
        raise ValueError("positive equity and cost multiplier required")
    costs = cost_params_for(account) if costs is None else costs
    prepared = execution_inputs(panel, costs) if inputs is None else inputs
    if state is None:
        current = State(panel.symbols, start, np.zeros(n), float(initial_equity),
                        copy.deepcopy(derisk) if derisk else C.DeRisk(), C.TurnoverBudget(account.turnover_budget))
    else:
        if state.symbols != panel.symbols or state.next_close != start:
            raise ValueError("state must be carried at the exact contiguous boundary")
        current = copy.deepcopy(state)
    equity, cash, opened = [np.full(T, np.nan) for _ in range(3)]
    weights, shares, fills, targets = [np.full((T, n), np.nan) for _ in range(4)]
    returns, paid, voluntary, forced, distributions, carry = [np.zeros(T) for _ in range(6)]
    voided, breach, caps = np.zeros((T, n), bool), np.zeros(T, bool), np.full(T, np.nan)
    equity[start] = current.cash + float(current.shares @ panel.close[start])
    for t in range(start, stop):
        if not np.isfinite(panel.close[t]).all() or not np.isfinite(panel.open[t + 1]).all():
            raise ValueError("execution requires actual close and next-open marks")
        cash[t], shares[t] = current.cash, current.shares
        weights[t] = current.shares * panel.close[t] / equity[t]
        cap = current.derisk.update(float(equity[t]))
        caps[t] = cap
        obs = Observation(t, weights[t].copy(), float(equity[t]), cap, current.derisk.drawdown(),
                          cap < 1, current.budget.used_voluntary, current.budget.budget)
        decision = policy(obs)
        if not isinstance(decision, Decision):
            raise ValueError("policy must return a no-order research Decision")
        u = t + 1
        # Split and distribution entitlement belong to the previous holders.
        current.shares *= panel.splits[u]
        distributions[u] = float(current.shares @ panel.dividends[u])
        carry[u] = current.cash * float(prepared.cash_returns[u])
        current.cash += carry[u] + distributions[u]
        price = panel.open[u]
        eq_open = current.cash + float(current.shares @ price)
        if not np.isfinite(eq_open) or eq_open <= 0:
            raise ValueError("nonpositive opening equity")
        opened[u] = eq_open
        current_weights = current.shares * price / eq_open
        target = project_caps(current_weights, account) if decision.target is None else project_caps(decision.target, account)
        targets[t] = target
        if not all(np.isfinite(arr[t]).all() for arr in (prepared.adv, prepared.sigma, prepared.spread)):
            raise ValueError("complete past cost/capacity estimates required")
        shadow_budget = copy.deepcopy(current.budget)
        step = C.constrain_step(C.StepInputs(target, current_weights, current.shares, eq_open, price,
            panel.close[t] / panel.splits[u], prepared.adv[t], prepared.reduce_only[t], np.zeros(n, bool), cap,
            decision.band if decision.target is not None else 0, decision.kappa if decision.target is not None else 1),
            account, shadow_budget)
        delta, fee = _affordable(step.shares, price, current.cash, prepared.adv[t], prepared.sigma[t],
                                prepared.spread[t], account, costs, cost_multiplier)
        executed = delta * price / eq_open
        required_forced = C.scale_to_gross(current_weights, cap) - current_weights
        same_side = np.sign(executed) == np.sign(required_forced)
        forced_amount = np.where(same_side, np.minimum(np.abs(executed), np.abs(required_forced)), 0)
        forced[u] = float(forced_amount.sum()) / 2
        voluntary[u] = C.one_way_turnover(executed) - forced[u]
        breach[u] = current.budget.used_voluntary + current.budget.used_forced + forced[u] + voluntary[u] > 1.5 * current.budget.budget + 1e-9
        current.budget.record(voluntary[u], forced[u])
        current.shares += delta
        current.cash -= float(delta @ price) + fee
        if current.cash < -1e-7 or np.any(current.shares < -1e-9):
            raise ValueError("negative cash or holdings after fills")
        current.cash = max(0, current.cash)
        paid[u], fills[u], voided[u] = fee, delta, step.voided
        equity[u] = current.cash + float(current.shares @ panel.close[u])
        returns[u] = equity[u] / equity[t] - 1
        current.next_close = u
    cash[stop], shares[stop] = current.cash, current.shares
    weights[stop] = current.shares * panel.close[stop] / equity[stop]
    caps[stop] = current.derisk.cap
    return Ledger(equity, weights, returns, paid, voluntary, forced, voided, breach, caps, start,
                  cash, shares, fills, distributions, carry, opened, targets, current)
