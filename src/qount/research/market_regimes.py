"""Causal market structures, separate from events and risk annotations.

Known observations are assigned an explicit structure, including a descriptive
transition class. Data-insufficient observations remain ``unknown`` and are
never fabricated as a supervised market state.
"""
from __future__ import annotations

import math

import numpy as np

from qount.research.market_stages import market_state_machine
from qount.research.market_strategy_router import StrategyRoute, traditional_entry


SCHEMA = 'market_regime_v3'
REGIMES = ('uptrend', 'downtrend', 'rotation', 'compression', 'low_efficiency_chop', 'transition')
DURATION_BINS = tuple(range(1, 11))
DESCRIPTIONS = {
    'uptrend': '方向持续向上，均线与正斜率一致',
    'downtrend': '方向持续向下，均线与负斜率一致',
    'rotation': '低方向效率，价格在有限历史箱体内双边触及并穿越中线；只描述轮动，不代表可交易区间',
    'compression': '方向效率低且近期振幅、相对波动共同收缩',
    'low_efficiency_chop': '方向效率低，但既未明显收缩，也未形成稳定的双边轮动箱体',
    'transition': '数据充分但方向、均线斜率或效率确认互相不一致，处于转换/待确认结构',
}
SHAPE_FEATURES = ('slope50_atr', 'width5_over20', 'anchor_drift', 'containment20',
                  'lower_visits20', 'upper_visits20', 'midpoint_crosses20')


def separated_visits(values, predicate, separation=3):
    last = -separation; count = 0
    for i, v in enumerate(values):
        if predicate(v) and i - last >= separation:
            count += 1; last = i
    return count


def structural_candidates(f):
    """Return only high-specificity structure candidates.

    Trend ER >= .30; low-directional ER <= .25. Compression and rotation use
    disjoint range-expansion bands. Rotation has relaxed but explicit two-sided
    evidence; it is not an automatic strategy permission. Thresholds are fixed
    description hypotheses, not optimized against realized returns.
    """
    trend = f['efficiency20'] >= .30 and f['direction_confirmed']
    nondirectional = f['efficiency20'] <= .25
    return dict(
        uptrend=bool(trend and f['direction'] == 1 and f['close'] > f['ema50']
                     and f['ema20'] > f['ema50'] and f['slope50_atr'] >= .15),
        downtrend=bool(trend and f['direction'] == -1 and f['close'] < f['ema50']
                       and f['ema20'] < f['ema50'] and f['slope50_atr'] <= -.15),
        rotation=bool(nondirectional and abs(f['slope50_atr']) <= .20
            and f['width5_over20'] > .55 and f['anchor_drift'] <= .70
            and f['containment20'] >= .65 and 0 <= f['anchor_position'] <= 1
            and f['lower_visits20'] >= 1 and f['upper_visits20'] >= 1
            and f['midpoint_crosses20'] >= 1 and 1.5 <= f['anchor_width_atr'] <= 12),
        compression=bool(nondirectional and f['relative_volatility'] < .75 and f['width5_over20'] <= .55),
    )


def select_structure(features):
    candidates = structural_candidates(features)
    selected = [s for s, enabled in candidates.items() if enabled]
    if len(selected) > 1: raise ValueError('regime_v3_overlapping_definitions')
    if selected: return selected[0]
    if features['efficiency20'] <= .25: return 'low_efficiency_chop'
    return 'transition'


def window_regime(regimes, *, minimum_share=.60):
    """Represent a future holding window by its majority state, not its last bar."""
    values = tuple(regimes)
    if not values or any(value not in REGIMES for value in values):
        raise ValueError('regime_v3_invalid_window')
    counts = {state: values.count(state) for state in REGIMES}
    state = max(REGIMES, key=lambda item: (counts[item], -REGIMES.index(item)))
    return state if counts[state] / len(values) >= minimum_share else 'transition'


def duration_bucket(regimes, *, cap=10):
    """Return the causal future run length from the first observed bar.

    ``cap`` is an open upper bucket (10 means 10 or more bars). Unknown
    observations are invalid targets rather than an invented duration.
    """
    values = tuple(regimes)
    if not values or any(value not in REGIMES for value in values):
        raise ValueError('regime_v3_invalid_duration_window')
    first = values[0]; length = 0
    for value in values:
        if value != first: break
        length += 1
    return min(length, cap)


def environment_rows(bars, legacy=None):
    """Every anchor and feature uses bars available through the current close.

    Box anchor: high/low of [i-40,i-20); validate on 20 recent closes and extrema.
    Future observations never move an old box or backdate a failed breakout.
    """
    legacy = market_state_machine(bars) if legacy is None else legacy
    result = {}
    for i, b in enumerate(bars):
        old = legacy[b.t]
        if i < 205 or old['action_state'] == 'unknown':
            result[b.t] = dict(schema=SCHEMA, regime='unknown', event=None,
                               risk=dict(block_new=True, shock=False, high_volatility=False), features={})
            continue
        atr = max(float(old['atr14']), 1e-12)
        anchor = bars[i-40:i-20]; recent = bars[i-19:i+1]
        low = min(x.l for x in anchor); high = max(x.h for x in anchor); width = max(high-low, 1e-12)
        width20 = max(x.h for x in recent) - min(x.l for x in recent)
        width5 = max(x.h for x in bars[i-4:i+1]) - min(x.l for x in bars[i-4:i+1])
        positions = [(x.c-low)/width for x in recent]
        signs = [1 if p > .5 else -1 for p in positions if p != .5]
        features = dict(efficiency20=float(old['er20']), direction=int(old['direction']),
            direction_confirmed=bool(old['confirmed']), close=float(b.c), ema20=float(old['ema20']), ema50=float(old['ema50']),
            slope50_atr=(old['ema50']-legacy[bars[i-5].t]['ema50'])/atr,
            relative_volatility=old['volatility20']/max(old['volatility_reference'], 1e-12),
            width5_over20=width5/max(width20, 1e-12),
            anchor_drift=max(abs(min(x.l for x in recent)-low), abs(max(x.h for x in recent)-high))/width,
            containment20=sum(0 <= p <= 1 for p in positions)/20., anchor_position=positions[-1],
            lower_visits20=separated_visits(positions, lambda p: 0 <= p <= .25),
            upper_visits20=separated_visits(positions, lambda p: .75 <= p <= 1),
            midpoint_crosses20=sum(a != z for a, z in zip(signs, signs[1:])),
            anchor_low=low, anchor_high=high, anchor_width_atr=width/atr)
        regime = select_structure(features)
        result[b.t] = dict(schema=SCHEMA, regime=regime, features=features,
            event=old['event'], risk=dict(block_new=old['action_state'] == 'shock',
            shock=old['action_state'] == 'shock', high_volatility=bool(old['high_vol'])))
    return result


def environment_probabilities(bundle, matrix):
    """Output probabilities only; reject incompatible legacy model semantics."""
    if bundle.get('schema') != SCHEMA or tuple(bundle.get('state_names', ())) != REGIMES:
        raise ValueError('regime_v3_incompatible_model_schema')
    classifier = bundle['classifier']; raw = np.asarray(classifier.predict_proba(matrix), float)
    classes = np.asarray(classifier[-1].classes_, int)
    if (raw.ndim != 2 or raw.shape[1] != len(classes) or np.any(classes < 0) or np.any(classes >= len(REGIMES))
            or np.any(~np.isfinite(raw)) or np.any(raw < 0) or not np.allclose(raw.sum(1), 1)):
        raise ValueError('regime_v3_invalid_probabilities')
    prior_mix = float(bundle.get('uniform_prior_mix', .01))
    if not 0 <= prior_mix < 1: raise ValueError('regime_v3_invalid_prior_mix')
    values = np.full((len(raw), len(REGIMES)), prior_mix / len(REGIMES))
    values[:, classes] += raw * (1 - prior_mix)
    return [dict(zip(REGIMES, map(float, row))) for row in values]


def duration_probabilities(bundle, matrix, horizon):
    """Return a normalized duration distribution for a fitted horizon head."""
    classifiers = bundle.get('duration_classifiers', {})
    classifier = classifiers.get(str(horizon)) if isinstance(classifiers, dict) else None
    if classifier is None: raise ValueError('regime_v3_missing_duration_model')
    raw = np.asarray(classifier.predict_proba(matrix), float)
    classes = np.asarray(classifier[-1].classes_, int)
    if raw.ndim != 2 or raw.shape[1] != len(classes) or np.any(classes < 0) or np.any(classes >= len(DURATION_BINS)):
        raise ValueError('regime_v3_invalid_duration_probabilities')
    if np.any(~np.isfinite(raw)) or np.any(raw < 0) or not np.allclose(raw.sum(1), 1):
        raise ValueError('regime_v3_invalid_duration_probabilities')
    mix = float(bundle.get('duration_uniform_prior_mix', .01))
    values = np.full((len(raw), len(DURATION_BINS)), mix / len(DURATION_BINS))
    values[:, classes] += raw * (1 - mix)
    values /= values.sum(1, keepdims=True)
    names = [str(i) for i in DURATION_BINS[:-1]] + ['10+']
    return [dict(zip(names, map(float, row))) for row in values]


def select_environment(probabilities, threshold=.70):
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('regime_v2_invalid_threshold')
    if set(probabilities) != set(REGIMES): raise ValueError('regime_v3_incompatible_probability_keys')
    p = np.array([probabilities[s] for s in REGIMES], float)
    if np.any(~np.isfinite(p)) or np.any(p < 0) or not np.isclose(p.sum(), 1, atol=1e-6, rtol=0):
        raise ValueError('regime_v3_invalid_probabilities')
    order = np.argsort(-p)
    if p[order[0]] < threshold or np.isclose(p[order[0]], p[order[1]], atol=1e-12, rtol=0): return None
    return REGIMES[int(order[0])]


def compatible_strategy(environment):
    """Observable events are triggers within an environment, not ML classes."""
    state = environment['regime']; event = environment['event']
    if environment['risk']['block_new'] or state in ('unknown', 'compression', 'rotation', 'transition', 'low_efficiency_chop'): return None
    if event is not None and event['status'] == 'pending': return None
    if state in ('uptrend', 'downtrend'):
        side = 1 if state == 'uptrend' else -1
        if event is not None and event['status'] == 'confirmed':
            if event['side'] != side: return None
            return 'confirmed_breakout_long' if side == 1 else 'confirmed_breakout_short'
        if event is not None and event['status'] == 'failed' and event['side'] == side: return None
        return 'trend_pullback_long' if side == 1 else 'trend_rally_short'
    return None


def environment_entry(environment, bar, legacy, *, probabilities=None, allow_short=True):
    if environment.get('schema') != SCHEMA: raise ValueError('regime_v2_incompatible_environment')
    if probabilities is not None and select_environment(probabilities) != environment['regime']: return None
    strategy = compatible_strategy(environment)
    if strategy is None: return None
    # Range decisions use the same validated box that defined the environment.
    inputs = dict(legacy)
    entry = traditional_entry(StrategyRoute(environment['regime'], 1., strategy, 'v2_compatible'), bar, inputs, allow_short=allow_short)
    return entry
