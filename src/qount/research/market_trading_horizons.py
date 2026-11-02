"""Daily inputs and holding-window-native targets; offline research only.

The target describes the future executable window itself, never the trailing
20-day state at its endpoint. Five horizon buckets share fixed definitions.
These exploratory labels are separate from market_regime_v3.
"""
from __future__ import annotations

import math
import numpy as np

STATES = ('upward', 'downward', 'two_sided', 'quiet', 'choppy', 'mixed')
HORIZONS = {'crypto': (3, 7, 14, 30), 'etf_proxy': (3, 5, 10, 21)}
SCHEMA = 'daily_native_holding_window_v2'


def path_state(bars, entry_price, exit_price, sigma):
    """Describe realized direction, efficiency, range and two-sided travel.

    sigma is known at decision. Daily OHLC cannot identify intraday ordering;
    two_sided therefore requires at least three daily closes and two observed
    crossings. It is a description, not a mean-reversion strategy permission.
    """
    if not bars or min(entry_price, exit_price, sigma) <= 0:
        raise ValueError('horizon_invalid_path')
    scale = entry_price * sigma * math.sqrt(len(bars))
    closes = np.array([entry_price] + [b.c for b in bars] + [exit_price], float)
    previous = entry_price
    variation = 0.
    for b in bars:
        variation += max(b.h-b.l, abs(b.h-previous), abs(b.l-previous))
        previous = b.c
    variation += abs(exit_price-previous)
    # Summed daily ranges grow roughly as h, while net displacement grows as
    # sqrt(h). A fixed threshold on that ratio would manufacture fewer trends
    # at longer horizons. Use the full-window envelope for the shared target.
    high = max(max(b.h for b in bars), entry_price, exit_price)
    low = min(min(b.l for b in bars), entry_price, exit_price)
    efficiency = abs(exit_price-entry_price)/max(high-low, 1e-12)
    z = math.log(exit_price/entry_price)/(sigma*math.sqrt(len(bars)))
    amplitude = (high-low)/scale
    signs = np.sign(closes[1:-1]-entry_price)
    signs = signs[signs != 0]
    crossings = int(np.sum(signs[1:] != signs[:-1]))
    if z >= .5 and efficiency >= .25:
        state = 'upward'
    elif z <= -.5 and efficiency >= .25:
        state = 'downward'
    elif amplitude <= 1.:
        state = 'quiet'
    elif len(bars) >= 3 and abs(z) < .5 and crossings >= 2 and \
            max(closes-entry_price) >= .25*scale and min(closes-entry_price) <= -.25*scale:
        state = 'two_sided'
    elif efficiency <= .25:
        state = 'choppy'
    else:
        state = 'mixed'
    return dict(state=state, z=z, efficiency=efficiency, amplitude=amplitude,
                daily_travel_efficiency=abs(exit_price-entry_price)/max(variation, 1e-12),
                crossings=crossings)


def known_at(bar, group):
    return (bar.t + (61 if group == 'crypto' else 60))*1000


def open_at(bar, group):
    import datetime as dt
    from qount.research_data.bars import NY
    if group == 'crypto':
        return (bar.t+1-86400)*1000
    day = dt.datetime.fromtimestamp(bar.t, NY).date()
    return int(dt.datetime.combine(day, dt.time(9, 30), NY).timestamp())*1000


def horizon_observation(bars, i, group, horizon):
    """Features use completed daily data; label covers entry open to expiry open.

    Crypto waits for i+2 daily open because i+1 opens before the assumed 60s
    publication buffer. Cash ETF enters i+1. Expiry is entry+h, so label,
    maturity, probability and fixed maximum holding all use the same clock.
    """
    if i < max(21, horizon):
        return None
    past = bars[i-20:i+1]
    sigma = max(float(np.std(np.diff(np.log([b.c for b in past])), ddof=1)), 1e-6)
    recent = bars[i-horizon+1:i+1]
    observed = path_state(recent, bars[i-horizon].c, bars[i].c, sigma)
    past_closes = np.array([b.c for b in bars[max(0, i-4*horizon):i+1]], float)
    last = bars[i]
    x = [observed['z'], observed['efficiency'], observed['amplitude'], observed['crossings'],
         math.log(last.c/bars[max(0, i-3*horizon)].c)/(sigma*math.sqrt(3*horizon)),
         float(np.std(np.diff(np.log(past_closes)), ddof=1))/sigma if len(past_closes)>2 else 1.,
         (last.c-last.o)/max(last.h-last.l, 1e-12),
         (last.c-min(b.l for b in recent))/max(max(b.h for b in recent)-min(b.l for b in recent), 1e-12)]
    entry = i + (2 if group == 'crypto' else 1)
    exit_ = entry+horizon
    row = dict(index=i, horizon=horizon, known_at=known_at(last, group), sigma=sigma,
               current=STATES.index(observed['state']), x=x, entry_index=entry,
               exit_index=exit_, y=-1, mature_at=0)
    if exit_ < len(bars):
        outcome = path_state(bars[entry:exit_], bars[entry].o, bars[exit_].o, sigma)
        row.update(y=STATES.index(outcome['state']),
                   mature_at=max(known_at(bars[exit_-1], group), open_at(bars[exit_], group)+60000),
                   entry_at=open_at(bars[entry], group), exit_at=open_at(bars[exit_], group))
        if row['known_at'] >= row['entry_at'] or row['mature_at'] <= row['exit_at']:
            raise ValueError('horizon_clock_error')
    return row


def quarterly_masks(rows, cutoff, end):
    train = np.array([i for i, r in enumerate(rows) if r['y'] >= 0 and r['mature_at'] < cutoff], int)
    test = np.array([i for i, r in enumerate(rows) if r['y'] >= 0 and cutoff <= r['known_at'] < end], int)
    return train, test


def trading_decision(row, bars, group, predicted):
    if predicted not in (0, 1) or row['y'] < 0 or (group == 'etf_proxy' and predicted == 1):
        return None
    side = 1 if predicted == 0 else -1
    bar = bars[row['index']]
    stop = bar.c*(1-side*2*row['sigma']*math.sqrt(row['horizon']))
    if stop <= 0:
        return None
    return dict(known_at=row['known_at'], entry_at=row['entry_at'], side=side,
        stop=stop, target=None, fraction=1., max_bars=row['horizon'],
        capacity=bar.v*bar.c*.001)
