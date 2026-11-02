"""Daily wick/volume hypotheses, not identification of hidden stock owners.

Independent event accounts use vendor adjusted-price units, with raw-share
entry lots, next-open decisions and persistent blocked exits. No live API.
"""
from collections import deque
from dataclasses import dataclass
import math


@dataclass
class Entry:
    day: int
    units: float
    cash: float
    spent: float
    fees: float
    reference: float


def fees(notional, side, date):
    commission = max(5., notional * .0003)
    transfer = notional * (.0003 if date < '20150801' else .00002 if date < '20220429' else .00001)
    stamp = notional * (.001 if date < '20230828' else .0005) if side == 'sell' else 0.
    return commission + transfer + stamp


def features(series, sessions):
    """Yield signals using five PRE-breakout candles; current bar is excluded.

    Main-board prefixes only locate the supplied archive. Past data maturity
    and turnover are used, never today's listing/ST/industry descriptors.
    """
    highs = deque(); amounts = deque(); wicks = deque()
    sum20 = sum5 = wick5 = 0.; valid_run = 0; last_signal = -1000
    for j, date in enumerate(sessions):
        good = bool(series.valid[j])
        while highs and highs[0][0] < j - 20:
            highs.popleft()
        prior_high = highs[0][1] if highs else math.nan
        prior_adv = sum20 / 20 if len(amounts) == 20 else math.nan
        if (good and valid_run >= 60 and series.history[j] >= 252 and len(wicks) == 5
                and prior_adv >= 50_000_000 and '20150101' <= date <= '20260831'
                and series.adj_close[j] > prior_high and j - last_signal >= 20):
            yield dict(signal_j=j, symbol=series.symbol, score=wick5 / sum5,
                       adv20=prior_adv, signal_date=date)
            last_signal = j
        if not good:
            highs.clear(); amounts.clear(); wicks.clear()
            sum20 = sum5 = wick5 = 0.; valid_run = 0
            continue
        amount = series.amount_cny[j]
        # Original archive adjusted prices include a per-file normalization.
        # adj_factor alone is not the raw-to-adjusted price conversion.
        scale = series.adj_open[j] / series.raw_open[j]
        high = series.raw_high[j] * scale
        raw_high, raw_low = series.raw_high[j], series.raw_low[j]
        wick = ((min(series.raw_open[j], series.raw_close[j]) - raw_low) / (raw_high - raw_low)
                if raw_high > raw_low else 0.)
        wick = min(1., max(0., wick))
        while highs and highs[-1][1] <= high:
            highs.pop()
        highs.append((j, high))
        amounts.append(amount); sum20 += amount
        if len(amounts) > 20:
            sum20 -= amounts.popleft()
        wicks.append((amount, amount * wick)); sum5 += amount; wick5 += amount * wick
        if len(wicks) > 5:
            a, w = wicks.popleft(); sum5 -= a; wick5 -= w
        valid_run += 1


def open_quote(series, j, side, slip):
    """No full-day activity/high/low/close may decide an opening execution.

    +/-4.99% is a conservative proxy guard, not historical limit certification.
    """
    values = [series.raw_open[j], series.pre_close[j], series.factor[j], series.adj_open[j]]
    if not all(math.isfinite(x) and x > 0 for x in values):
        return None, 'missing_open_or_factor'
    raw, previous, _, adjusted_open = values
    if (side == 'buy' and raw >= previous * 1.0499) or (side == 'sell' and raw <= previous * .9501):
        return None, 'conservative_open_guard'
    return (raw * (1 + slip if side == 'buy' else 1 - slip), adjusted_open / raw), None


def make_entry(series, sessions, event, *, slip=.001, delay=0, capital=10000.):
    j = event['signal_j'] + 1 + delay
    quote, reason = open_quote(series, j, 'buy', slip)
    if quote is None:
        return None, reason
    price, price_scale = quote
    budget = min(capital, event['adv20'] * .01)
    shares = math.floor(budget / price / 100) * 100
    while shares >= 100 and shares * price + fees(shares * price, 'buy', sessions[j]) > budget:
        shares -= 100
    if shares < 100:
        return None, 'minimum_lot_or_cash'
    notional = shares * price; paid = fees(notional, 'buy', sessions[j])
    return Entry(j, shares / price_scale, capital - notional - paid, notional + paid,
                 paid, series.adj_open[j]), None


def exit_flags(series, j, reference, peak_close):
    """All inputs are known after close j; exits can start at open j+1."""
    if not series.valid[j]:
        return False, False
    close = series.adj_close[j]
    past = [series.adj_close[k] for k in range(max(0, j - 3), j)]
    good_past = (len(past) == 3 and all(math.isfinite(x) and x > 0 for x in past)
                 and all(series.valid[k] for k in range(j-3, j)))
    price_failure = close <= .95 * reference or (good_past and close < min(past))
    prior = [series.amount_cny[k] for k in range(max(0, j - 20), j)]
    volume_known = len(prior) == 20 and all(math.isfinite(x) and x > 0 for x in prior)
    high, low = series.raw_high[j], series.raw_low[j]
    clv = (2 * series.raw_close[j] - high - low) / (high - low) if high > low else 0.
    stall = (volume_known and peak_close >= reference * 1.05 and clv <= -.5
             and series.amount_cny[j] >= 1.5 * sum(prior) / 20)
    return price_failure, stall


def simulate(series, sessions, entry, policy, *, slip=.001, capital=10000.):
    """Identical entry/quantity across policies, T+1, blocked exits never vanish.

    Missing close marks carry provisionally. An unresolved liquidation after
    60 sessions/data end retains both zero-recovery and last-mark bounds.
    """
    assert policy in ('fixed10', 'price', 'price_plus_stall')
    due = None; reason = None; blocked = 0; mark = entry.reference
    peak = capital; mdd = 0.; peak_close = entry.reference
    last = min(len(sessions) - 1, entry.day + 60)
    missing_marks = 0
    for j in range(entry.day, last + 1):
        if due is not None and j >= due:
            quote, failure = open_quote(series, j, 'sell', slip)
            if quote is not None:
                price, price_scale = quote
                notional = entry.units * price_scale * price
                paid = fees(notional, 'sell', sessions[j])
                equity = entry.cash + notional - paid
                mdd = max(mdd, 1 - equity / peak)
                return dict(status='closed', entry_j=entry.day, exit_j=j, reason=reason,
                            return_pct=(equity / capital - 1) * 100,
                            lower_return_pct=(equity / capital - 1) * 100,
                            mdd_pct=mdd * 100, fees=entry.fees + paid,
                            blocked_exit_opens=blocked, held_sessions=j-entry.day,
                            profit_giveback_pct=min(max(0., peak-capital), max(0., peak-equity))/capital*100,
                            missing_marks=missing_marks)
            blocked += 1
        if series.valid[j]:
            mark = series.adj_close[j]
            peak_close = max(peak_close, mark)
        else:
            missing_marks += 1
        equity = entry.cash + entry.units * mark
        peak = max(peak, equity); mdd = max(mdd, 1 - equity / peak)
        if due is None:
            price, stall = exit_flags(series, j, entry.reference, peak_close)
            if policy != 'fixed10' and price:
                reason = 'price_failure'
            elif policy == 'price_plus_stall' and stall:
                reason = 'high_volume_low_close_after_profit'
            elif j >= entry.day + 9:
                reason = 'fixed10'
            if reason:
                due = j + 1
    return dict(status='unresolved', entry_j=entry.day, exit_j=None, reason=reason,
                return_pct=(equity / capital - 1) * 100,
                lower_return_pct=(entry.cash / capital - 1) * 100,
                mdd_pct=mdd * 100, fees=entry.fees, blocked_exit_opens=blocked,
                held_sessions=last-entry.day, profit_giveback_pct=None, missing_marks=missing_marks)
