"""Offline, unlevered ETF risk budgets with next-open cash/share accounting."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from statistics import stdev

from qount.research.personal_trading_assistant import (
    AssistantBar, ETFAssetMeta, PersonalTradingAssistantKernel,
    StateMachineState, TrendTimingStateMachine, compute_adjusted_closes, validate_bars,
)


@dataclass(frozen=True)
class Costs:
    commission_bps: float = 6.0
    slippage_bps: float = 5.0
    minimum_commission: float = 5.0
    lot_size: int = 100
    cash_apr: float = 0.0

    def __post_init__(self):
        values = (self.commission_bps, self.slippage_bps, self.minimum_commission, self.cash_apr)
        if not all(math.isfinite(x) and x >= 0 for x in values):
            raise ValueError("invalid_costs")
        if self.slippage_bps >= 10000 or self.commission_bps >= 10000:
            raise ValueError("invalid_cost_rate")
        if not isinstance(self.lot_size, int) or self.lot_size < 0:
            raise ValueError("invalid_lot_size")


def target_schedule(bars: list[AssistantBar], meta: ETFAssetMeta, policy: str, *,
                    constant_weight: float = 0.75) -> list[float | None]:
    """Close decisions; None means no rebalance. Weekly decisions use past dates only.

    A new ISO week is recognized at its first completed session; execution is
    the following session. This avoids inferring Fridays/holidays from future bars.
    """
    if policy not in {"buy_hold", "constant", "ma120", "vol15"}:
        raise ValueError("unknown_policy")
    if not math.isfinite(constant_weight) or not 0 <= constant_weight <= 1:
        raise ValueError("invalid_constant_weight")
    closes = compute_adjusted_closes(bars, meta)
    averages = PersonalTradingAssistantKernel.compute_sma(closes, 120)
    machine, state = TrendTimingStateMachine(), StateMachineState()
    schedule = []
    previous_week = None
    for i, bar in enumerate(bars):
        week = datetime.strptime(bar.trade_date, "%Y%m%d").isocalendar()[:2]
        new_week = week != previous_week
        previous_week = week
        if policy == "ma120":
            previous = state.current_target
            state = machine.update_at_close(state, closes[i], averages[i])
            schedule.append(state.current_target if previous != state.current_target else None)
        elif policy == "buy_hold":
            schedule.append(1.0 if i == 0 else None)
        elif policy == "constant":
            schedule.append(constant_weight if new_week else None)
        elif i >= 20 and new_week:
            returns = [closes[j] / closes[j - 1] - 1 for j in range(i - 19, i + 1)]
            volatility = stdev(returns) * math.sqrt(252)
            schedule.append(min(1.0, 0.15 / volatility) if volatility > 0 else 1.0)
        else:
            schedule.append(None)
    return schedule


def summarize(rows: list[dict], initial_equity: float) -> dict:
    if not rows or initial_equity <= 0:
        raise ValueError("invalid_summary_input")
    peak, max_dd = initial_equity, 0.0
    returns, previous = [], initial_equity
    for row in rows:
        nav = row["equity"]
        returns.append(nav / previous - 1)
        previous = nav
        peak = max(peak, nav)
        max_dd = max(max_dd, 1 - nav / peak)
    years = max(1, (datetime.strptime(rows[-1]["date"], "%Y%m%d") -
                    datetime.strptime(rows[0]["date"], "%Y%m%d")).days) / 365.25
    cagr = (rows[-1]["equity"] / initial_equity) ** (1 / years) - 1
    volatility = stdev(returns) * math.sqrt(252) if len(returns) > 1 else 0.0
    return dict(start=rows[0]["date"], end=rows[-1]["date"], sessions=len(rows),
                total_return_pct=100 * (rows[-1]["equity"] / initial_equity - 1),
                cagr_calendar_pct=100 * cagr, max_drawdown_pct=100 * max_dd,
                calmar=cagr / max_dd if max_dd else None,
                volatility_pct=100 * volatility,
                sharpe=sum(returns) / len(returns) * 252 / volatility if volatility else None,
                average_weight=sum(r["weight"] for r in rows) / len(rows),
                terminal_equity=rows[-1]["equity"])


def simulate(bars: list[AssistantBar], meta: ETFAssetMeta, policy: str, *,
             start: str = "20140102", initial_capital: float = 100_000,
             costs: Costs = Costs(), delay: int = 1, constant_weight: float = 0.75) -> dict:
    """No orders/network; actual raw-price shares, splits and explicit friction.

    Weights are chosen at close, submitted after ``delay`` sessions, then sized
    against the observed opening price. Single-price sessions conservatively
    defer execution. Final equity is marked, not fictitiously liquidated.
    """
    validate_bars(bars, meta)
    if meta.is_index_proxy:
        raise ValueError("index_proxy_is_not_a_tradable_etf")
    if any(not b.is_complete for b in bars):
        raise ValueError("incomplete_bar")
    if not math.isfinite(initial_capital) or initial_capital <= 0 or delay < 1 or not isinstance(delay, int):
        raise ValueError("invalid_simulation_parameters")
    eligible = [i for i, b in enumerate(bars) if b.trade_date >= max(start, meta.listing_date)]
    if not eligible or eligible[0] < 120:
        raise ValueError("need_120_prior_sessions")
    first = eligible[0]
    schedule = target_schedule(bars, meta, policy, constant_weight=constant_weight)
    # Initialize from information available strictly before the first fill.
    known = [i for i in range(first - delay + 1) if schedule[i] is not None]
    if not known:
        initial_target, initial_decision = 0.0, None
    else:
        initial_decision = known[-1]
        initial_target = schedule[initial_decision]
    cash, shares = float(initial_capital), 0.0
    trades, rows = [], []
    pending = (initial_target, initial_decision)
    total_fee, total_slip, turnover, blocked = 0.0, 0.0, 0.0, 0
    for i in range(first, len(bars)):
        bar = bars[i]
        if i > first:
            cash *= (1 + costs.cash_apr) ** (1 / 252)
            for action in meta.corporate_actions:
                if bars[i - 1].trade_date < action.ex_date <= bar.trade_date:
                    cash += shares * action.cash_dividend
                    shares *= action.split_ratio
            decision = i - delay
            if decision >= 0 and schedule[decision] is not None:
                pending = (schedule[decision], decision)
        if pending is not None:
            weight, decision = pending
            if bar.low == bar.high:
                blocked += 1
            else:
                equity = cash + shares * bar.open
                desired = weight * equity / bar.open
                delta = desired - shares
                side = 1 if delta > 0 else -1
                price = bar.open * (1 + side * costs.slippage_bps / 10000)
                quantity = abs(delta)
                if side > 0:
                    # Target budget includes fees and slippage; never borrow cash.
                    budget = min(cash, max(0.0, weight * equity - shares * bar.open))
                    quantity = min(quantity, max(0.0, (budget - costs.minimum_commission) / price),
                                   budget / (price * (1 + costs.commission_bps / 10000)))
                else:
                    quantity = min(quantity, shares)
                if costs.lot_size:
                    quantity = math.floor((quantity + 1e-9) / costs.lot_size) * costs.lot_size
                fee = max(costs.minimum_commission, quantity * price * costs.commission_bps / 10000)
                if quantity > 1e-10 and (side > 0 or quantity * price > fee):
                    cash -= side * quantity * price + fee
                    shares += side * quantity
                    total_fee += fee
                    total_slip += quantity * abs(price - bar.open)
                    turnover += quantity * bar.open / equity
                    trades.append(dict(date=bar.trade_date, decision_date=bars[decision].trade_date if decision is not None else None,
                                       side="BUY" if side > 0 else "SELL", quantity=quantity, price=price,
                                       commission=fee, target_weight=weight, cash=cash, shares=shares))
                pending = None
        equity = cash + shares * bar.close
        if cash < -1e-7 or shares < -1e-7 or not math.isfinite(equity) or equity <= 0:
            raise ArithmeticError("invalid_cash_share_account")
        rows.append(dict(date=bar.trade_date, equity=equity, cash=cash, shares=shares,
                         weight=shares * bar.close / equity))
    metrics = summarize(rows, initial_capital)
    years = max(1, (datetime.strptime(rows[-1]["date"], "%Y%m%d") -
                    datetime.strptime(rows[0]["date"], "%Y%m%d")).days) / 365.25
    metrics.update(trade_count=len(trades), commission=total_fee, slippage=total_slip,
                   annual_turnover_two_sided=turnover / years, blocked_single_price_sessions=blocked)
    return dict(policy=policy, symbol=meta.symbol, metrics=metrics, nav=rows, trades=trades,
                research_only=True, orders_authorized=False)
