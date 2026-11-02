"""Offline single-coin momentum rotation with full-account leverage.

No execution imports or order interface. Daily OHLC cannot establish the order
of a stop and a mark-price liquidation; both path assumptions are supported.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

import numpy as np


@dataclass(frozen=True)
class Rule:
    cadence: str = "weekly"
    lookback: int = 63
    trend: bool = True
    gross: float = 3.0
    volatility_target: float | None = None
    stop_atr: float | None = None
    delay: int = 2
    direction: str = "long"
    risk_adjusted_rank: bool = False
    max_hold_bars: int | None = None
    entry_filter: str = "none"
    trend_exit: bool = True
    market_trend: bool = False
    risk_on_breadth: float | None = None
    risk_on_gross: float | None = None
    risk_on_volatility_target: float | None = None
    risk_off_breadth: float | None = None

    def __post_init__(self):
        if self.cadence not in ("weekly", "monthly", "daily", "6h") or self.lookback < 2:
            raise ValueError("invalid_rotation_clock")
        if self.gross <= 0 or self.delay < 2:
            raise ValueError("invalid_gross_or_signal_delay")
        if self.stop_atr is not None and self.stop_atr <= 0:
            raise ValueError("invalid_stop")
        if self.direction not in ("long", "both"):
            raise ValueError("invalid_direction")
        if self.entry_filter not in ("none", "pullback", "funding_cool", "both"):
            raise ValueError("invalid_entry_filter")
        if self.entry_filter != "none" and self.direction != "long":
            raise ValueError("entry_filters_require_long_only")
        risk_on = (self.risk_on_breadth, self.risk_on_gross, self.risk_on_volatility_target)
        if any(value is not None for value in risk_on):
            if (any(value is None for value in risk_on) or
                    not 0 < self.risk_on_breadth <= 1 or
                    self.risk_on_gross <= 0 or self.risk_on_volatility_target <= 0):
                raise ValueError("invalid_risk_on_breadth_overlay")
        if self.risk_off_breadth is not None and not 0 < self.risk_off_breadth <= 1:
            raise ValueError("invalid_risk_off_breadth")


def features(panel):
    close = panel["close"]
    high, low = panel["high"], panel["low"]
    previous = np.vstack([close[:1], close[:-1]])
    tr = np.maximum(high - low, np.maximum(abs(high - previous), abs(low - previous)))
    logret = np.vstack([np.zeros((1, close.shape[1])), np.diff(np.log(close), axis=0)])
    ma, sigma, atr = (np.full_like(close, np.nan) for _ in range(3))
    for t in range(len(close)):
        if t >= 119:
            ma[t] = close[t - 119:t + 1].mean(axis=0)
        if t >= 30:
            sigma[t] = logret[t - 29:t + 1].std(axis=0, ddof=1) * np.sqrt(panel.get("periods_per_year", 365.25))
        if t >= 14:
            atr[t] = tr[t - 13:t + 1].mean(axis=0)
    out = dict(ma=ma, sigma=sigma, atr=atr)
    pullback = np.zeros_like(close, dtype=bool)
    pullback[3:] = close[3:] <= close[:-3]
    out["pullback"] = pullback
    if "daily_rate" in panel:
        # Settlements in day d are known after its close. The reference uses
        # only prior seven-day averages, excluding the current observation.
        rate7 = np.full_like(close, np.nan)
        cool = np.zeros_like(close, dtype=bool)
        for t in range(6, len(close)):
            rate7[t] = panel["daily_rate"][t - 6:t + 1].mean(axis=0)
            if t >= 96:
                cool[t] = rate7[t] <= np.median(rate7[t - 90:t], axis=0)
        out["funding_cool"] = cool
    return out


def market_is_on(panel, f, signal, rule):
    if not rule.market_trend:
        return True
    j = panel["symbols"].index("BTCUSDT")
    return bool(signal >= max(119, rule.lookback) and
                panel["close"][signal, j] > f["ma"][signal, j] and
                panel["close"][signal, j] > panel["close"][signal - rule.lookback, j])


def qualifying_trend_breadth(panel, f, signal, lookback):
    """Fraction of the fixed universe with positive momentum above its MA."""
    if signal < max(119, lookback):
        return 0.0
    momentum = panel["close"][signal] / panel["close"][signal - lookback] - 1
    qualified = (panel["close"][signal] > f["ma"][signal]) & (momentum > 0)
    return float(np.mean(qualified))


def decision(panel, f, signal, rule):
    """Only the chosen winner is checked; no fallback to a cheaper coin."""
    if signal < max(119, rule.lookback):
        return None, 0.0
    if not market_is_on(panel, f, signal, rule):
        return None, 0.0
    breadth = qualifying_trend_breadth(panel, f, signal, rule.lookback)
    if rule.risk_off_breadth is not None and breadth < rule.risk_off_breadth:
        return None, 0.0
    momentum = panel["close"][signal] / panel["close"][signal - rule.lookback] - 1
    rank = momentum.copy()
    if rule.direction == "both":
        rank = abs(rank)
    if rule.risk_adjusted_rank:
        rank /= np.maximum(f["sigma"][signal], 1e-8)
    winner = int(np.argmax(rank))
    side = 1 if rule.direction == "long" or momentum[winner] >= 0 else -1
    if rule.trend and (side * momentum[winner] <= 0 or
                      side * (panel["close"][signal, winner] - f["ma"][signal, winner]) <= 0):
        return None, 0.0
    gates = ("pullback", "funding_cool") if rule.entry_filter == "both" else (rule.entry_filter,)
    if rule.entry_filter != "none" and any(not f[g][signal, winner] for g in gates):
        return None, 0.0
    gross = rule.gross
    if rule.volatility_target is not None:
        gross = min(gross, rule.volatility_target / max(f["sigma"][signal, winner], 1e-8))
    if (rule.risk_on_breadth is not None and
            breadth >= rule.risk_on_breadth):
        gross = min(rule.risk_on_gross,
                    rule.risk_on_volatility_target / max(f["sigma"][signal, winner], 1e-8))
    return winner, float(gross)


def rounded_quantity(notional, price, symbol, filters):
    if filters is None:
        return notional / price
    rows = {f["filterType"]: f for f in filters[symbol]["filters"]}
    lot = rows["MARKET_LOT_SIZE"]
    step = Decimal(lot["stepSize"])
    q = (Decimal(str(notional / price)) / step).to_integral_value(rounding=ROUND_DOWN) * step
    if q < Decimal(lot["minQty"]) or q * Decimal(str(price)) < Decimal(rows["MIN_NOTIONAL"]["notional"]):
        return 0.0
    return float(min(q, Decimal(lot["maxQty"])))


def replay(panel, f, rule, *, start, end="9999", capital=1000.0, cost_bp=10.0,
           filters=None, maintenance=0.005, liquidation_fee=0.01,
           ambiguous_path="liquidation_first", reverse_execution=False):
    """UTC open-to-open book, fixed quantities between weekly/monthly trades.

    A signal at bar d's close trades at bar d+2's open. Weekly decisions use
    Sunday close; monthly decisions use month-end close. Intraday cadence uses
    the preceding six-hour boundary. Trend exits/trailing stops also use bar
    d-2. No protected cash sleeve. A stop pays all debit funding in the bar's
    interval and receives no credits (conservative unknown intrabar time).
    Liquidation uses actual mark extremes, a constant MMR proxy and fee.
    reverse_execution flips the traded side while preserving the original
    model's selection, trend exits and stop triggers. The original stop becomes
    a profit-taking exit for the inverse book; it is not an inverse stop-loss.
    """
    if capital <= 0 or cost_bp < 0 or not 0 <= maintenance < 1 or liquidation_fee < 0:
        raise ValueError("invalid_account_assumptions")
    if ambiguous_path not in ("liquidation_first", "stop_first"):
        raise ValueError("invalid_path")
    dates, opening = panel["dates"], panel["open"]
    indices = np.flatnonzero((dates >= start) & (dates < end))
    if not len(indices) or indices[0] < 121:
        raise ValueError("insufficient_signal_history")
    left, right = int(indices[0]), min(int(indices[-1]) + 1, len(dates) - 1)
    fee = cost_bp / 10000
    equity, q, held, stop, blocked = float(capital), 0.0, None, None, False
    side, entry_bar = 1, None
    holding_bars = []
    counts, curve, trades = Counter(), [], []
    highwater = float(capital)
    worst_intraday = 0.0
    for t in range(left, right):
        before = equity
        costs = funding = price_pnl = turnover = 0.0
        gross = 0.0
        signal = t - rule.delay
        signal_date = np.datetime64(dates[signal], "D")
        if rule.cadence == "weekly":
            scheduled = (int(signal_date.astype(int)) + 3) % 7 == 6
        elif rule.cadence == "monthly":
            scheduled = dates[signal][:7] != dates[signal + 1][:7]
        elif rule.cadence == "daily":
            scheduled = dates[signal][:10] != dates[signal + 1][:10]
        else:
            hour = int(np.datetime64(dates[signal], "h").astype(int))
            scheduled = hour % 6 == 5
        scheduled = scheduled or t == left
        target, desired_gross = decision(panel, f, signal, rule)
        target_side = 1
        if target is not None and rule.direction == "both":
            target_side = 1 if panel["close"][signal, target] >= panel["close"][signal - rule.lookback, target] else -1

        def close_position(price, reason):
            nonlocal equity, q, held, stop, costs, turnover, price_pnl
            traded_side = -side if reverse_execution else side
            mark_pnl = traded_side * q * (price - opening[t, held])
            trade_value = q * price
            charge = trade_value * fee
            equity += mark_pnl - charge
            price_pnl += mark_pnl
            costs += charge
            turnover += trade_value
            trades.append(dict(date=str(dates[t]), symbol=panel["symbols"][held],
                               side="SELL" if traded_side == 1 else "BUY", quantity=q, price=float(price), reason=reason,
                               signal_date=str(dates[signal]), holding_bars=t - entry_bar))
            holding_bars.append(t - entry_bar)
            counts[reason] += 1
            q, held, stop = 0.0, None, None

        if equity > 0:
            # A trend failure may exit every day; selecting a new coin waits
            # until the next scheduled rotation. Stop exits also wait.
            if held is not None and not market_is_on(panel, f, signal, rule):
                close_position(opening[t, held], "market_exit")
                blocked = True
            if held is not None and rule.trend and rule.trend_exit:
                own_momentum = panel["close"][signal, held] / panel["close"][signal - rule.lookback, held] - 1
                if side * own_momentum <= 0 or side * (panel["close"][signal, held] - f["ma"][signal, held]) <= 0:
                    close_position(opening[t, held], "trend_exit")
                    blocked = True
            if held is not None and rule.max_hold_bars and t - entry_bar >= rule.max_hold_bars:
                close_position(opening[t, held], "time_exit")
                blocked = True
            if scheduled:
                blocked = False
                if held is not None and (held != target or side != target_side):
                    close_position(opening[t, held], "rotation_exit")
                if target is not None:
                    price = opening[t, target]
                    # Reserve the possible cost rather than borrow to pay it.
                    # This bound never uses more than the stated gross target.
                    wanted = rounded_quantity(equity * desired_gross / (1 + desired_gross * fee),
                                              price, panel["symbols"][target], filters)
                    if wanted == 0:
                        counts["minimum_order_skip"] += 1
                    if wanted == 0 and held is not None:
                        close_position(price, "untradeable_resize_exit")
                    elif wanted > 0:
                        old = q
                        delta = wanted - old
                        if filters is not None and abs(delta) > 1e-12:
                            # New/increased risk must pass the minimum for the
                            # delta order, not only the final position. Small
                            # partial reductions are skipped conservatively.
                            valid_delta = rounded_quantity(abs(delta) * price, price,
                                                           panel["symbols"][target], filters)
                            if valid_delta == 0:
                                counts["minimum_resize_skip"] += 1
                                wanted, delta = old, 0.0
                        charge = abs(delta) * price * fee
                        equity -= charge
                        costs += charge
                        turnover += abs(delta) * price
                        if abs(delta) > 1e-12:
                            trades.append(dict(date=str(dates[t]), symbol=panel["symbols"][target],
                                side="BUY" if delta * target_side * (-1 if reverse_execution else 1) > 0 else "SELL", quantity=abs(float(delta)),
                                price=float(price), reason="scheduled", signal_date=str(dates[signal])))
                            counts["rebalance_fills"] += 1
                        q, held, side = wanted, target, target_side
                        if old == 0:
                            entry_bar = t
                            counts["entries"] += 1
                            if rule.stop_atr:
                                stop = price - side * rule.stop_atr * f["atr"][signal, held]
            if held is not None and not blocked:
                price = opening[t, held]
                traded_side = -side if reverse_execution else side
                gross = q * price / max(equity, 1e-30)
                if rule.stop_atr:
                    updated = panel["close"][signal, held] - side * rule.stop_atr * f["atr"][signal, held]
                    stop = max(stop, updated) if side == 1 else min(stop, updated)
                debit = q * panel["funding_debit" if traded_side == 1 else "funding_credit"][t, held]
                mark_extreme = panel["mark_low" if traded_side == 1 else "mark_high"][t, held]
                worst_equity = equity + traded_side * q * (mark_extreme - price) - debit
                maintenance_margin = q * mark_extreme * maintenance
                liquidated = worst_equity <= maintenance_margin
                stopped = stop is not None and (panel["low"][t, held] <= stop if side == 1
                                                else panel["high"][t, held] >= stop)
                if liquidated and stopped:
                    counts["ambiguous_stop_liquidation_days"] += 1
                if liquidated and not (stopped and ambiguous_path == "stop_first"):
                    # Constant maintenance/fee, full-wallet collateral proxy.
                    # Liquidation may leave zero equity; actual tiered rules
                    # and insurance treatment are not reconstructed.
                    liquidation_price = max(0., (q * price - traded_side * equity + traded_side * debit) /
                                            (q * (1 - traded_side * maintenance)))
                    remaining = max(0., q * liquidation_price * (maintenance - liquidation_fee))
                    price_pnl += remaining - equity + debit
                    funding -= debit
                    equity = remaining
                    counts["liquidations"] += 1
                    counts["ruin"] = int(equity == 0)
                    q, held, stop = 0.0, None, None
                    blocked = True
                    worst_intraday = 1.0
                elif stopped:
                    funding -= debit
                    equity -= debit
                    fill = min(price, stop) if side == 1 else max(price, stop)
                    worst_intraday = max(worst_intraday, 1 - max(0., equity + traded_side * q * (fill - price)) / highwater)
                    close_position(fill, "stop_exit")
                    blocked = True
                else:
                    funding -= traded_side * q * panel["funding_value"][t, held]
                    pnl = traded_side * q * (opening[t + 1, held] - price)
                    price_pnl += pnl
                    equity += pnl + funding
                    worst_intraday = max(worst_intraday, 1 - max(0., worst_equity) / highwater)
            if t == right - 1 and held is not None:
                # Mark-to-next-open PnL already recognized above.
                final_price = opening[t + 1, held]
                final_cost = q * final_price * fee
                equity -= final_cost
                costs += final_cost
                turnover += q * final_price
                counts["terminal_exit"] += 1
                q, held = 0.0, None
            if equity < 0:
                # A close/open gap or conservative funding timing can still
                # exhaust the wallet outside the simplified mark-low test.
                counts["ruin"] = 1
                counts["gap_or_funding_insolvency"] += 1
                price_pnl -= equity
                equity, q, held, stop = 0.0, 0.0, None, None
                worst_intraday = 1.0
        highwater = max(highwater, equity)
        assert np.isfinite(equity) and equity >= 0
        assert abs((equity - before) - (price_pnl + funding - costs)) < 1e-7 * max(1, before)
        curve.append(dict(date=str(dates[t]), equity=equity, returns=equity / before - 1 if before else 0.,
                          price_pnl=price_pnl, funding_pnl=funding, costs=costs,
                          gross=gross, turnover=turnover / before if before else 0.))
    nav = np.array([capital, *[r["equity"] for r in curve]]) / capital
    mdd = float(np.max(1 - nav / np.maximum.accumulate(nav)))
    periods_per_year = panel.get("periods_per_year", 365.25)
    cagr = float(nav[-1] ** (periods_per_year / len(curve)) - 1)
    summary = dict(start=str(dates[left]), end_open=str(dates[right]), days=len(curve),
        initial_usdt=capital, final_usdt=equity, return_pct=float((nav[-1] - 1) * 100),
        bar_hours=8766 / periods_per_year,
        mean_completed_holding_bars=float(np.mean(holding_bars)) if holding_bars else None,
        cagr_pct=cagr * 100, mdd_pct=mdd * 100, calmar=cagr / mdd if mdd else None,
        intraday_drawdown_bound_pct=worst_intraday * 100, counts=dict(counts),
        funding_pnl=sum(r["funding_pnl"] for r in curve), costs=sum(r["costs"] for r in curve),
        mean_gross=float(np.mean([r["gross"] for r in curve])),
        active_days=int(sum(r["gross"] > 0 for r in curve)),
        annual_one_way_turnover=float(np.mean([r["turnover"] for r in curve]) * periods_per_year))
    return dict(summary=summary, curve=curve, trades=trades)
