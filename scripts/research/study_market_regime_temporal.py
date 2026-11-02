"""Offline semi-Markov state transition and duration study."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np

from qount.research.market_regime_temporal import (
    DURATION_BINS, feature_matrix, fit_temporal_heads, predict_temporal, spell_rows,
)
from qount.research.market_learning import fit_candidate
from qount.research.market_regimes import REGIMES, environment_rows
from qount.research.market_stages import market_state_machine
from study_binance_market_states import load_markets
from study_market_strategy_router import known_time


def metrics(actual, probabilities, kind):
    actual = np.asarray(actual, int); probabilities = np.asarray(probabilities, float)
    pred = probabilities.argmax(1)
    accuracy = float(np.mean(pred == actual)) if len(actual) else None
    present = sorted(set(actual))
    balanced = float(np.mean([np.mean(pred[actual == c] == c) for c in present])) if present else None
    brier = float(np.mean(np.sum((probabilities - np.eye(probabilities.shape[1])[actual]) ** 2, axis=1))) if len(actual) else None
    return dict(kind=kind, rows=len(actual), accuracy=accuracy, balanced_accuracy=balanced, brier=brier)


def transition_baseline(rows, indices, train_indices):
    """Historical successor mode, evaluated only at spell boundaries."""
    current = np.array([rows[i]['state_index'] for i in indices], int)
    next_actual = np.array([rows[i]['next_state_index'] for i in indices], int)
    successor_by_state = {}
    for state in range(len(REGIMES)):
        values = [rows[i]['next_state_index'] for i in train_indices
                  if rows[i]['state_index'] == state and rows[i]['next_state_index'] is not None]
        successor_by_state[state] = max(set(values), key=values.count) if values else state
    transition = np.eye(len(REGIMES))[[successor_by_state[state] for state in current]]
    return metrics(next_actual, transition, 'next_state_boundary_mode')


def duration_baseline(rows, indices, train_indices):
    """Historical duration distribution using training rows only."""
    duration_actual = np.array([min(rows[i]['remaining'], len(DURATION_BINS)) - 1 for i in indices], int)
    duration_train = np.array([min(rows[i]['remaining'], len(DURATION_BINS)) - 1 for i in train_indices], int)
    duration_counts = np.bincount(duration_train, minlength=len(DURATION_BINS)).astype(float)
    duration = np.repeat((duration_counts / duration_counts.sum())[None, :], len(indices), axis=0)
    expected = (duration * np.arange(1, len(DURATION_BINS) + 1)).sum(1)
    return dict(**metrics(duration_actual, duration, 'duration_history'),
                expected_mae=float(np.mean(np.abs(expected - (duration_actual + 1)))))


def conditional_accuracy(rows, indices, probabilities, baseline_probabilities):
    """Expose whether errors come from state imbalance or spell age mixing."""
    actual = np.array([rows[i]['next_state_index'] for i in indices], int)
    current = np.array([rows[i]['state_index'] for i in indices], int)
    ages = np.array([rows[i]['age'] for i in indices], int)
    model = probabilities.argmax(1); baseline = baseline_probabilities.argmax(1)
    by_state = {}
    for state in sorted(set(current)):
        mask = current == state
        by_state[str(REGIMES[state])] = dict(rows=int(mask.sum()), model=float(np.mean(model[mask] == actual[mask])),
                                             baseline=float(np.mean(baseline[mask] == actual[mask])))
    by_age = {}
    for label, mask in (('age_1', ages == 1), ('age_2_3', (ages >= 2) & (ages <= 3)), ('age_4_plus', ages >= 4)):
        if mask.any(): by_age[label] = dict(rows=int(mask.sum()), model=float(np.mean(model[mask] == actual[mask])),
                                             baseline=float(np.mean(baseline[mask] == actual[mask])))
    return dict(by_state=by_state, by_age=by_age)


def boundary_transition(rows, matrix, cutoff, train_indices):
    """Diagnostic: train/evaluate one successor row per completed spell."""
    train = np.asarray([i for i in train_indices if rows[i]['index'] == rows[i]['spell_end']], int)
    test = np.asarray([i for i, row in enumerate(rows)
                       if row['index'] == row['spell_end'] and row['spell_start_at'] >= cutoff
                       and row['next_state_index'] is not None], int)
    if len(train) < 100 or not len(test): return None
    model, _ = fit_candidate('tree', matrix[train], np.asarray([rows[i]['next_state_index'] for i in train]), seed=61)
    probability = np.zeros((len(test), len(REGIMES)))
    probability[:, model[-1].classes_.astype(int)] = model.predict_proba(matrix[test])
    actual = np.asarray([rows[i]['next_state_index'] for i in test])
    modes = {}
    for state in range(len(REGIMES)):
        values = [rows[i]['next_state_index'] for i in train if rows[i]['state_index'] == state]
        if values: modes[state] = max(set(values), key=values.count)
    baseline = np.eye(len(REGIMES))[[modes[rows[i]['state_index']] for i in test]]
    return dict(rows=len(test), model=metrics(actual, probability, 'boundary_next_state'),
                baseline=metrics(actual, baseline, 'boundary_next_state_mode'))


def quarter_start(timestamp):
    date = dt.datetime.fromtimestamp(timestamp / 1000, dt.timezone.utc)
    return int(dt.datetime(date.year, (date.month - 1) // 3 * 3 + 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def build_group_rows(group, assets):
    all_rows = []
    environments = {}
    for asset, bars in assets.items():
        legacy = market_state_machine(bars)
        environments.setdefault(group, {})[asset] = environment_rows(bars, legacy)
        regimes = [environments[group][asset][bar.t]['regime'] for bar in bars]
        known = [known_time(bar, group) for bar in bars]
        rows = spell_rows(regimes, known)
        for row in rows:
            row.update(group=group, asset=asset, timestamp=int(bars[row['index']].t))
        all_rows.extend(rows)
    return all_rows, environments


def run_group(group, assets, output):
    rows, environments = build_group_rows(group, assets)
    symbols = sorted(assets)
    matrix = feature_matrix(rows, environments, symbols)
    cutoffs = sorted({quarter_start(row['known_at']) for row in rows if row['known_at'] >= 1672531200000})
    fold_results = []
    latest_bundle = None
    for cutoff in cutoffs:
        train_ix = np.array([i for i, row in enumerate(rows)
                             if not row['right_censored'] and row['mature_at'] is not None
                             and row['mature_at'] < cutoff], int)
        # Do not leak a spell that started before the fold into the test side.
        test_ix = np.array([i for i, row in enumerate(rows)
                            if row['spell_start_at'] >= cutoff
                            and not row['right_censored']], int)
        if len(train_ix) < 200 or len(test_ix) == 0:
            continue
        try:
            bundle = fit_temporal_heads(rows, matrix, train_ix)
        except ValueError:
            continue
        transition_test = np.array([i for i in test_ix
                                    if rows[i]['next_state_index'] is not None
                                    and rows[i]['index'] == rows[i]['spell_end']], int)
        duration_test = np.array([i for i in test_ix if rows[i]['next_state_index'] is not None], int)
        if len(transition_test) == 0:
            continue
        transition_prediction = predict_temporal(bundle, matrix[transition_test])
        duration_prediction = predict_temporal(bundle, matrix[duration_test])
        duration_actual = np.array([min(rows[i]['remaining'], len(DURATION_BINS)) - 1 for i in duration_test])
        duration_metrics = metrics(duration_actual, duration_prediction['duration_probabilities'], 'duration_bucket')
        duration_metrics['expected_mae'] = float(np.mean(np.abs(duration_prediction['expected_remaining_bars'] - (duration_actual + 1))))
        transition_base = transition_baseline(rows, transition_test, [i for i in train_ix if rows[i]['index'] == rows[i]['spell_end']])
        duration_base = duration_baseline(rows, duration_test, train_ix)
        boundary_train = [i for i in train_ix if rows[i]['index'] == rows[i]['spell_end']]
        successor_by_state = {}
        for state in range(len(REGIMES)):
            values = [rows[i]['next_state_index'] for i in boundary_train
                      if rows[i]['state_index'] == state and rows[i]['next_state_index'] is not None]
            successor_by_state[state] = max(set(values), key=values.count) if values else state
        baseline_transition = np.eye(len(REGIMES))[[successor_by_state[rows[i]['state_index']] for i in transition_test]]
        fold_results.append(dict(group=group, cutoff=cutoff, training_rows=len(train_ix),
                                 transition_rows=len(transition_test), duration_rows=len(duration_test),
                                 transition=metrics(np.array([rows[i]['next_state_index'] for i in transition_test]), transition_prediction['next_state_probabilities'], 'next_state_boundary'),
                                 duration=duration_metrics,
                                 baseline=dict(transition=transition_base, duration=duration_base),
                                 conditional=conditional_accuracy(rows, transition_test,
                                                                  transition_prediction['next_state_probabilities'],
                                                                  baseline_transition)))
        fold_results[-1]['boundary_transition'] = boundary_transition(rows, matrix, cutoff, train_ix)
        latest_bundle = bundle
    if latest_bundle is None:
        raise RuntimeError(f'temporal_no_valid_fold:{group}')
    final_cutoff = max(row['known_at'] for row in rows)
    final_train = np.array([i for i, row in enumerate(rows)
                            if not row['right_censored'] and row['mature_at'] is not None
                            and row['mature_at'] < final_cutoff], int)
    latest_bundle = fit_temporal_heads(rows, matrix, final_train)
    latest = {}
    for asset in symbols:
        indices = [i for i, row in enumerate(rows) if row['asset'] == asset]
        index = max(indices, key=lambda i: rows[i]['known_at'])
        prediction = predict_temporal(latest_bundle, matrix[[index]])
        duration_names = [str(i) for i in DURATION_BINS[:-1]] + ['10+']
        latest[asset] = dict(
            asof=int(rows[index]['known_at']), current_state=rows[index]['state'],
            elapsed_bars=int(rows[index]['age']),
            next_state_probabilities=dict(zip(REGIMES, prediction['next_state_probabilities'][0].tolist())),
            duration_probabilities=dict(zip(duration_names, prediction['duration_probabilities'][0].tolist())),
            survival_probabilities=dict(zip(duration_names, prediction['survival_probabilities'][0].tolist())),
            expected_remaining_bars=float(prediction['expected_remaining_bars'][0]),
            research_only=True, orders_authorized=False)
    return dict(group=group, schema='market_regime_temporal_v2', spells=sum(row['index'] == row['spell_start'] for row in rows),
                rows=len(rows), folds=fold_results, latest=latest), latest_bundle


def report(result):
    lines = ['# 状态转移与剩余持续时间 V2 验证', '',
             '本实验只验证离线时序输出，不接入策略路由或实盘。转移头只在完整状态段最后一根预测后继结构；持续时间头在成熟状态段内预测从当前时点到结束的剩余根数；右删失状态段不作为已结束样本。', '',
             '|市场|状态段|观测行|折数|转移准确率|转移平衡准确率|持续时间准确率|持续时间期望MAE|基线转移准确率|基线时长MAE|',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for group, value in result['groups'].items():
        folds = value['folds']
        mean = lambda path: float(np.mean([path(f) for f in folds]))
        lines.append(f"|{group}|{value['spells']}|{value['rows']}|{len(folds)}|"
                     f"{mean(lambda f:f['transition']['accuracy']):.2%}|"
                     f"{mean(lambda f:f['transition']['balanced_accuracy']):.2%}|"
                     f"{mean(lambda f:f['duration']['accuracy']):.2%}|"
                     f"{mean(lambda f:f['duration']['expected_mae']):.2f}|"
                     f"{mean(lambda f:f['baseline']['transition']['accuracy']):.2%}|"
                     f"{mean(lambda f:f['baseline']['duration']['expected_mae']):.2f}|")
    lines += ['', '## 裁决', '',
              '- 转移和持续时间输出的结构已验证，且所有结果按成熟时间滚动拟合。',
              '- 转移标签只在状态段边界定义，避免把同一后继复制到不同剩余时长的行。',
              '- 诊断仍按当前状态和状态年龄拆分，避免把长状态重复行误读成独立证据。',
              '- 当前版本没有超过简单状态持久/历史时长基线的证据，不能用于策略准入。',
              '- 下一步应按状态段聚合、处理稀有转移和做时间外概率校准，不应直接增加模型复杂度。']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): parser.error('preserve previous artifacts; choose a new directory')
    markets, _, sources = load_markets()
    args.output.mkdir(parents=True)
    result = dict(schema='market_regime_temporal_v2', research_only=True,
                  orders_authorized=False, sources=sources, groups={})
    for group, assets in markets.items():
        group_result, bundle = run_group(group, assets, args.output)
        result['groups'][group] = {k: v for k, v in group_result.items() if k != 'latest'}
        joblib.dump(bundle, args.output / f'{group}_temporal_model.joblib', compress=3)
        (args.output / f'{group}_latest.json').write_text(json.dumps(group_result['latest'], ensure_ascii=False, indent=2) + '\n')
        print(group, 'folds', len(group_result['folds']), 'spells', group_result['spells'], flush=True)
    (args.output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (args.output / 'report.md').write_text(report(result))
    print('saved', args.output, flush=True)


if __name__ == '__main__': main()
