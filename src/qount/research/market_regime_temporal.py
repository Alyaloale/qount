"""Causal state-spell transition and remaining-duration models.

This module deliberately starts with a small semi-Markov approximation:
transition and duration heads share causal features, while the duration head
is converted to a survival curve for the current spell.  It is research-only
and does not authorize trading.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from qount.research.market_learning import fit_candidate
from qount.research.market_regimes import DURATION_BINS, REGIMES


def spell_rows(regimes, known_at):
    """Build one causal observation per bar in each known state spell.

    Rows in a spell with no observed successor are right-censored and have no
    transition/duration target.  ``known_at`` is the information timestamp of
    the current bar, not the future maturity timestamp.
    """
    values = tuple(regimes)
    if len(values) != len(known_at):
        raise ValueError("temporal_length_mismatch")
    rows = []
    start = 0
    for end in range(len(values) + 1):
        if end < len(values) and values[end] == values[start]:
            continue
        state = values[start]
        if state not in REGIMES:
            start = end
            continue
        successor = values[end] if end < len(values) and values[end] in REGIMES else None
        for index in range(start, end):
            remaining = end - index
            rows.append(dict(index=index, spell_start=start, spell_end=end - 1,
                             state=state, state_index=REGIMES.index(state),
                             age=index - start + 1, remaining=remaining,
                             next_state=successor,
                             next_state_index=None if successor is None else REGIMES.index(successor),
                             spell_start_at=int(known_at[start]),
                             spell_end_at=int(known_at[end - 1]),
                             mature_at=None if successor is None else int(known_at[end]),
                             known_at=int(known_at[index]),
                             right_censored=successor is None))
        start = end
    return rows


def duration_target(remaining, cap=10):
    if remaining < 1 or cap != len(DURATION_BINS):
        raise ValueError("temporal_invalid_duration")
    return min(int(remaining), cap) - 1


def duration_distribution(probabilities):
    """Return duration probabilities plus survival and expected remaining bars."""
    values = np.asarray(probabilities, float)
    if values.ndim != 2 or values.shape[1] != len(DURATION_BINS):
        raise ValueError("temporal_invalid_duration_distribution")
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise ValueError("temporal_invalid_duration_distribution")
    values = values / values.sum(1, keepdims=True)
    # The final bucket is 10+, so its contribution is conservatively capped at 10.
    support = np.arange(1, len(DURATION_BINS) + 1, dtype=float)
    survival = np.flip(np.cumsum(np.flip(values, axis=1), axis=1), axis=1)
    expected = (values * support).sum(1)
    return values, survival, expected


def feature_matrix(rows, environments, assets):
    """Build features from current observations only."""
    names = ('efficiency20', 'direction', 'slope50_atr', 'relative_volatility',
             'width5_over20', 'anchor_drift', 'containment20', 'anchor_position',
             'lower_visits20', 'upper_visits20', 'midpoint_crosses20', 'anchor_width_atr')
    matrix = []
    for row in rows:
        f = environments[row['group']][row['asset']][row['timestamp']]['features']
        numeric = [float(f[name]) for name in names] + [float(row['age'])]
        state = [float(row['state_index'] == j) for j in range(len(REGIMES))]
        identity = [float(row['asset'] == asset) for asset in assets]
        matrix.append(numeric + state + identity)
    return np.asarray(matrix, float)


def padded_probabilities(model, matrix, classes):
    raw = np.asarray(model[-1].predict_proba(matrix), float)
    values = np.zeros((len(matrix), len(classes)))
    values[:, np.asarray(model[-1].classes_, int)] = raw
    return values


def fit_temporal_heads(rows, matrix, train_indices):
    """Fit boundary transition and complete-spell duration heads.

    A transition target exists only at the final observed bar of a completed
    spell. Repeating the successor over every bar would mix different
    distances to the boundary and is intentionally forbidden in v2.
    """
    train = [rows[i] for i in train_indices]
    transition_rows = [r for r in train if r['next_state_index'] is not None and r['index'] == r['spell_end']]
    if len({r['next_state_index'] for r in transition_rows}) < 2:
        raise ValueError('temporal_insufficient_transition_classes')
    transition_indices = np.asarray([train_indices[i] for i, r in enumerate(train)
                                     if r['next_state_index'] is not None and r['index'] == r['spell_end']], int)
    transition, _ = fit_candidate('tree', matrix[transition_indices],
                                   np.asarray([rows[i]['next_state_index'] for i in transition_indices]), seed=61)
    duration_indices = np.asarray([i for i in train_indices if not rows[i]['right_censored']], int)
    duration, _ = fit_candidate('tree', matrix[duration_indices],
                                np.asarray([duration_target(rows[i]['remaining']) for i in duration_indices]), seed=59)
    return dict(schema='market_regime_temporal_v2', state_names=list(REGIMES),
                transition_target='successor_only_at_completed_spell_boundary',
                duration_target='remaining_bars_for_matured_spell_rows',
                duration_bins=list(DURATION_BINS), transition_classifier=transition,
                duration_classifier=duration, research_only=True, orders_authorized=False)


def predict_temporal(bundle, matrix):
    transition = padded_probabilities(bundle['transition_classifier'], matrix, REGIMES)
    raw_duration = np.asarray(bundle['duration_classifier'][-1].predict_proba(matrix), float)
    duration = np.zeros((len(matrix), len(DURATION_BINS)))
    duration[:, np.asarray(bundle['duration_classifier'][-1].classes_, int)] = raw_duration
    duration, survival, expected = duration_distribution(duration)
    return dict(next_state_probabilities=transition, duration_probabilities=duration,
                survival_probabilities=survival, expected_remaining_bars=expected)
