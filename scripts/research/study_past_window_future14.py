"""Historical univariate association of trailing observations with C[t+14]>C[t].

Run with PYTHONPATH=src .venv/bin/python scripts/research/study_past_window_future14.py
--output state/research_runs/NAME. No state labels or trading code are used.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.stats import rankdata
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, roc_auc_score
from threadpoolctl import threadpool_limits

SOURCE = Path('state/research_cache/independent_crypto_factors_20261027/panel_seven.json')
DAY = 86400000


def features(raw, anchors):
    """Every feature reads only indices <= its anchor; momentum uses w returns."""
    close = raw[:, 4]
    ret = np.r_[np.nan, np.diff(np.log(close))]
    pressure = 2 * raw[:, 10] / raw[:, 7] - 1
    out = {}
    for w in (60, 90):
        ix = anchors[:, None] + np.arange(-w+1, 1)[None, :]
        bars = raw[ix]
        c = bars[:, :, 4]
        r = ret[ix]
        last = close[anchors]
        change = np.log(last / close[anchors-w])
        vol = r.std(1)
        logc = np.log(c)
        x = np.arange(w) - (w-1)/2
        slope = ((logc-logc.mean(1, keepdims=True))*x).sum(1)/(x*x).sum()
        hi = bars[:, :, 2].max(1)
        lo = bars[:, :, 3].min(1)
        recent = bars[:, -5:]
        prior = bars[:, :-5]
        f = dict(
            momentum=change,
            close_over_mean=last/c.mean(1)-1,
            price_zscore=(logc[:, -1]-logc.mean(1))/logc.std(1),
            log_price_slope=slope,
            slope_over_vol=slope/vol,
            range_location=(last-lo)/(hi-lo),
            drawdown_from_high=last/hi-1,
            rise_from_low=last/lo-1,
            signed_path_efficiency=change/np.abs(r).sum(1),
            positive_day_fraction=(r>0).mean(1),
            realized_volatility=vol,
            downside_volatility=np.sqrt(np.minimum(r, 0).__pow__(2).mean(1)),
            mean_daily_range=((bars[:, :, 2]-bars[:, :, 3])/c).mean(1),
            recent5_vol_over_window=r[:, -5:].std(1)/vol,
            quote_taker_imbalance=2*bars[:, :, 10].sum(1)/bars[:, :, 7].sum(1)-1,
            base_taker_imbalance=2*bars[:, :, 9].sum(1)/bars[:, :, 5].sum(1)-1,
            recent5_pressure_change=(2*recent[:, :, 10].sum(1)/recent[:, :, 7].sum(1)
                                     -2*prior[:, :, 10].sum(1)/prior[:, :, 7].sum(1)),
            recent5_quote_activity=np.log(recent[:, :, 7].mean(1)/prior[:, :, 7].mean(1)),
            recent5_trade_activity=np.log(recent[:, :, 8].mean(1)/prior[:, :, 8].mean(1)),
            recent5_average_trade_change=np.log((recent[:, :, 7].sum(1)/recent[:, :, 8].sum(1))
                                                /(prior[:, :, 7].sum(1)/prior[:, :, 8].sum(1))),
            close_over_window_vwap=last/(bars[:, :, 7].sum(1)/bars[:, :, 5].sum(1))-1,
            log_average_trade_quote=np.log(bars[:, :, 7].sum(1)/bars[:, :, 8].sum(1)),
        )
        # Raw levels are included for completeness and explicitly flagged as drifting.
        for col, name in [(1, 'open'), (2, 'high'), (3, 'low'), (4, 'close'),
                          (5, 'base_volume'), (7, 'quote_volume'), (8, 'trade_count'),
                          (9, 'taker_buy_base_volume'), (10, 'taker_buy_quote_volume')]:
            f['raw_log_mean_'+name] = np.log(bars[:, :, col].mean(1))
        out.update({f'{name}_{w}d': value for name, value in f.items()})
    # Direct observations at all historical offsets, normalized without future data.
    for lag in range(90):
        j = anchors-lag
        past = j[:, None]+np.arange(-29, 1)[None, :]
        out[f'daily_return_lag{lag}'] = ret[j]
        out[f'daily_pressure_lag{lag}'] = pressure[j]
        out[f'daily_quote_activity_lag{lag}'] = np.log(raw[j, 7]/np.median(raw[past, 7], axis=1))
        out[f'daily_trade_activity_lag{lag}'] = np.log(raw[j, 8]/np.median(raw[past, 8], axis=1))
    names = list(out)
    matrix = np.column_stack(list(out.values()))
    if not np.isfinite(matrix).all():
        raise ValueError('nonfinite_feature')
    return names, matrix


def standardized_rank(x):
    r = rankdata(x, axis=0)
    return (r-r.mean(0))/r.std(0)


def correlations(x, y):
    # For a binary target, its standardized rank equals standardized 0/1.
    return (standardized_rank(x)*(y-y.mean())[:, None]/y.std()).mean(0)


def metric(y, p, base):
    return dict(rows=len(y), up_fraction=float(y.mean()), auc=float(roc_auc_score(y, p)),
                accuracy=float(np.mean((p>=.5)==y)),
                balanced_accuracy=float(balanced_accuracy_score(y, p>=.5)),
                brier=float(np.mean((p-y)**2)), baseline_brier=float(np.mean((base-y)**2)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('preserve old results: choose a new output path')
    cache = json.loads(args.source.read_text())
    arrays = {key.removesuffix('_klines'): np.asarray(value, float)
              for key, value in cache['data'].items() if key.endswith('_klines')}
    assets = sorted(arrays)
    n = len(arrays[assets[0]])
    # Same dates for both windows. Extra 29 days support normalized lag activity.
    anchors = np.arange(118, n-14)
    ties = np.array([arrays[a][anchors+14,4] == arrays[a][anchors,4] for a in assets])
    excluded_tie_rows = int(ties.sum())
    excluded_common_dates = int(ties.any(0).sum())
    anchors = anchors[~ties.any(0)]
    xs, ys, returns = [], [], []
    complete = Path('state/research_runs/market_state_complete_20261101/dataset.npz')
    with np.load(complete, allow_pickle=False) as z:
        native_asset, native_clock, native_market = z['asset'], z['bar_open_at'], z['market']
    matched = 0
    for asset in assets:
        raw = arrays[asset]
        if raw.shape != (n, 12) or not np.all(np.diff(raw[:, 0]) == DAY):
            raise ValueError('non_daily_or_inconsistent_source')
        if not np.array_equal(raw[:, 0], arrays[assets[0]][:, 0]):
            raise ValueError('different_asset_calendar')
        if not np.isfinite(raw).all() or np.any(raw[:, 1:6] <= 0) or np.any(raw[:, 7:11] <= 0):
            raise ValueError('bad_source_values')
        if np.any(raw[:, 10] > raw[:, 7]) or np.any(raw[:, 9] > raw[:, 5]):
            raise ValueError('invalid_aggressive_volume')
        selected = native_asset == asset
        source_rows = np.searchsorted(raw[:, 0], native_clock[selected])
        if not np.array_equal(raw[source_rows][:, [1,2,3,4,5,7,8,9,10]], native_market[selected]):
            raise ValueError('source_differs_from_current_native_dataset')
        matched += int(selected.sum())
        names, x = features(raw, anchors)
        fr = raw[anchors+14, 4]/raw[anchors, 4]-1
        if np.any(fr == 0):
            raise ValueError('ties_need_explicit_mask')
        xs.append(x)
        ys.append(fr > 0)
        returns.append(fr)
    X = np.array(xs)
    Y = np.array(ys)
    R = np.array(returns)
    times = arrays[assets[0]][anchors, 0].astype(np.int64)
    decisions = times+DAY+60000
    mature = decisions+14*DAY
    dates = np.array([dt.datetime.fromtimestamp(int(t)/1000, dt.timezone.utc).strftime('%Y-%m-%d') for t in times])
    years = np.array([int(d[:4]) for d in dates])
    quarter = np.array([d[:4]+'Q'+str((int(d[5:7])-1)//3+1) for d in dates])
    # Check causal formulas with genuine truncated inputs and a changed future tail.
    for ai in (0, 3, 6):
        raw = arrays[assets[ai]]
        for t in (250, 850, 1500):
            _, full = features(raw, np.array([t]))
            _, prefix = features(raw[:t+1], np.array([t]))
            np.testing.assert_array_equal(full, prefix)
    rho = np.array([correlations(x, y) for x, y in zip(X, Y)])
    mean_rho = rho.mean(0)
    rankX = np.array([standardized_rank(x) for x in X])
    rankY = np.array([(y-y.mean())/y.std() for y in Y])
    # One common circular shift preserves the contemporaneous cross-asset structure.
    # Search-wide null is an exploratory stationarity diagnostic, not a causal test.
    rng = np.random.default_rng(20261101)
    shifts = rng.integers(90, len(anchors)-90, size=499)
    null = np.array([np.einsum('atf,at->f', rankX, np.roll(rankY, int(s), axis=1))/Y.size for s in shifts])
    max_null = np.max(np.abs(null), axis=1)
    groups = sorted(set(quarter))
    # Quarter cluster bootstrap of fixed full-sample rank products; assets move together.
    qsum = np.array([(rankX[:, quarter == q]*rankY[:, quarter == q, None]).sum((0,1)) for q in groups])
    qcount = np.array([int((quarter == q).sum())*len(assets) for q in groups])
    draws = rng.integers(len(groups), size=(2000, len(groups)))
    boot = qsum[draws].sum(1)/qcount[draws].sum(1)[:, None]
    intervals = np.quantile(boot, [.025, .975], axis=0)
    by_year = {str(y): np.array([correlations(x[years == y], z[years == y]) for x,z in zip(X,Y)]).mean(0)
               for y in sorted(set(years))}
    rows = []
    for j, name in enumerate(names):
        raw_level = 'raw_log_' in name or 'log_average_trade_quote' in name
        rows.append(dict(feature=name, raw_level=raw_level, mean_spearman=float(mean_rho[j]),
                         abs_mean_spearman=float(abs(mean_rho[j])),
                         mean_abs_asset_spearman=float(abs(rho[:, j]).mean()),
                         asset_correlations={a:float(rho[i,j]) for i,a in enumerate(assets)},
                         yearly_correlations={y:float(v[j]) for y,v in by_year.items()},
                         same_sign_assets=int((np.sign(rho[:, j])==np.sign(mean_rho[j])).sum()),
                         quarter_cluster_fixed_rank_ci95=intervals[:,j].tolist(),
                         circular_shift_p=float((1+(abs(null[:,j])>=abs(mean_rho[j])).sum())/500),
                         search_wide_shift_p=float((1+(max_null>=abs(mean_rho[j])).sum())/500)))
    rows.sort(key=lambda r:r['abs_mean_spearman'], reverse=True)
    print('top associations', [(r['feature'], round(r['mean_spearman'],4)) for r in rows[:12]], flush=True)
    # Each quarter chooses its feature and orientation from matured prior labels only.
    # Rank normalization is fitted on each asset's own training history.
    fixed = {'fixed_rise60':'rise_from_low_60d', 'fixed_pressure60':'quote_taker_imbalance_60d',
             'fixed_rise90':'rise_from_low_90d', 'fixed_pressure90':'quote_taker_imbalance_90d'}
    models = ('frequency', 'select_60', 'select_90', 'select_both', 'select_lags',
              'select_normalized60', 'select_normalized90', *fixed)
    preds = {name:np.full(Y.shape, np.nan) for name in models}
    folds = []
    for year in range(2023, 2027):
        for month in (1,4,7,10):
            start = int(dt.datetime(year,month,1,tzinfo=dt.timezone.utc).timestamp()*1000)
            end = int(dt.datetime(year+int(month==10),1 if month==10 else month+3,1,tzinfo=dt.timezone.utc).timestamp()*1000)
            tr = mature < start
            te = (decisions>=start)&(decisions<end)
            if not te.any():
                continue
            train_rho = np.array([correlations(x[tr],y[tr]) for x,y in zip(X,Y)]).mean(0)
            fold = dict(year=year, month=month, training_dates=int(tr.sum()), test_dates=int(te.sum()), selections={})
            for ai in range(len(assets)):
                preds['frequency'][ai,te] = (Y[ai,tr].sum()+1)/(tr.sum()+2)
            for model in models[1:]:
                candidates = [j for j,name in enumerate(names) if
                              (model=='select_60' and name.endswith('_60d')) or
                              (model=='select_90' and name.endswith('_90d')) or
                              (model=='select_both' and name.endswith(('60d','90d'))) or
                              (model=='select_lags' and '_lag' in name) or
                              (model=='select_normalized60' and name.endswith('_60d') and 'raw_log_' not in name and 'log_average_trade_quote' not in name) or
                              (model=='select_normalized90' and name.endswith('_90d') and 'raw_log_' not in name and 'log_average_trade_quote' not in name) or
                              (model in fixed and name == fixed[model])]
                best = candidates[int(np.argmax(abs(train_rho[candidates])))]
                fold['selections'][model] = names[best]
                trainx, testx = [], []
                for ai in range(len(assets)):
                    fitted = np.sort(X[ai,tr,best])
                    trainx.append(np.searchsorted(fitted,X[ai,tr,best],side='right')/len(fitted))
                    testx.append(np.searchsorted(fitted,X[ai,te,best],side='right')/len(fitted))
                trainx = np.array(trainx).reshape(-1,1)
                testx = np.array(testx).reshape(-1,1)
                # Fixed regularization; no test-based tuning or orientation selection.
                est = LogisticRegression(C=1., max_iter=200).fit(trainx,Y[:,tr].ravel())
                preds[model][:,te] = est.predict_proba(testx)[:,1].reshape(len(assets),-1)
            folds.append(fold)
    valid = np.isfinite(preds['frequency'][0])
    metrics = {}
    testq = quarter[valid]
    uq = sorted(set(testq))
    draw = rng.integers(len(uq),size=(4000,len(uq)))
    for model, p in preds.items():
        metrics[model] = metric(Y[:,valid].ravel(),p[:,valid].ravel(),preds['frequency'][:,valid].ravel())
        delta = (p[:,valid]-Y[:,valid])**2-(preds['frequency'][:,valid]-Y[:,valid])**2
        sums = np.array([delta[:,testq==q].sum() for q in uq])
        counts = np.array([int((testq==q).sum())*len(assets) for q in uq])
        interval = sums[draw].sum(1)/counts[draw].sum(1)
        metrics[model]['brier_delta_quarter_ci95'] = np.quantile(interval,[.025,.975]).tolist()
        metrics[model]['by_year'] = {str(y):metric(Y[:,valid&(years==y)].ravel(),p[:,valid&(years==y)].ravel(),preds['frequency'][:,valid&(years==y)].ravel()) for y in range(2023,2027)}
    # Same-date quintiles within each asset (descriptive, not executable thresholds).
    for row in rows[:20]:
        j = names.index(row['feature'])
        quantile = np.array([np.minimum((rankdata(x[:,j])-1)*5//len(anchors),4).astype(int) for x in X])
        row['quintiles'] = [dict(bin=k+1,rows=int((quantile==k).sum()),up_fraction=float(Y[quantile==k].mean()),mean_future_return=float(R[quantile==k].mean())) for k in range(5)]
    result = dict(research_only=True, orders_authorized=False, independent_oos=False,
                  history_previously_consumed=True, source=str(args.source),
                  source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                  assets=assets, first_date=dates[0], last_date=dates[-1],
                  dates=len(anchors), rows=Y.size, up_fraction=float(Y.mean()),
                  target='C[t+14] > C[t]; exact 14 calendar days; no state label',
                  features=len(names), source_matches_current_dataset_rows=matched,
                  prefix_invariance_checks=9, tie_rows=int((R==0).sum()),
                  excluded_exact_tie_rows=excluded_tie_rows,
                  excluded_common_dates_for_ties=excluded_common_dates,
                  window_definition='w complete daily bars ending t; momentum C[t]/C[t-w]-1 uses w returns; 118 warmup bars allow lag89 activity trailing30',
                  ci_note='Quarter resampling of fixed-rank covariance contributions; exploratory, unadjusted intervals. Common circular shifts preserve asset co-movement; stationarity is unverified.',
                  costs='Not a trading backtest; gross endpoint direction, no fees/slippage/funding or account size applicable.',
                  limitations=['Current seven survivors only; no all-coin generalisation.',
                               'Overlapping labels, correlated assets, repeated historical exploration.',
                               'Raw level correlations can reflect lifecycle/time trends.',
                               'No causal attribution; screening evaluates monotone single-feature relationships only.'],
                  fixed_candidate_note='The four fixed features were chosen after inspecting whole-history associations; their forward replay is post-selection and is not independent confirmation.',
                  ranking=rows, forward_screen_metrics=metrics, folds=folds,
                  first_forward_date=dates[valid][0],last_forward_date=dates[valid][-1])
    args.output.mkdir(parents=True)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with (args.output/'ranking.csv').open('w') as f:
        cols=['feature','raw_level','mean_spearman','mean_abs_asset_spearman','same_sign_assets','circular_shift_p','search_wide_shift_p']
        writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader()
        writer.writerows({k:row[k] for k in cols} for row in rows)
    np.savez_compressed(args.output/'observations.npz',asset=assets,bar_open_at=times,
                        feature_names=names,features=X,up=Y,future_return=R,
                        **{f'prediction_{k}':p for k,p in preds.items()})
    lines=['# 过去60/90天与未来14天涨跌的单变量关系','',
           f'样本：{dates[0]}—{dates[-1]}（UTC日K开盘日），{len(anchors):,}个共同日期 × 7币种 = {Y.size:,}条；上涨比例{Y.mean():.2%}。',
           f'目标严格为 C[t+14] > C[t]；{len(names)}个候选，逐币种计算Spearman后取等权均值。',
           f'原候选有{excluded_tie_rows}条价格完全相同，剔除其涉及的{excluded_common_dates}个共同日期，避免将平价归为下跌；其余资产同日一并剔除以保持配对比较。',
           '以当天完整收盘作为“现在”，不是实时盘口价格。所有特征只使用当天及之前数据；9项截断历史不变性检查通过，原生14,588条记录逐值匹配当前数据集。',
           '这是端点方向统计，不是收益回测，无手续费、滑点、资金费或资金规模结论。当前7币种名单有幸存者选择；既有历史已用于研究，前推结果不能宣称新独立样本外。','',
           '## 全历史排名','',
           '|特征|平均Spearman|同号币种|季度簇95%区间（未校正）|搜索范围校正移位p|',
           '|---|---:|---:|---|---:|']
    for r in rows[:15]:
        ci=r['quarter_cluster_fixed_rank_ci95']
        lines.append(f"|{r['feature']}|{r['mean_spearman']:+.4f}|{r['same_sign_assets']}/7|[{ci[0]:+.4f}, {ci[1]:+.4f}]|{r['search_wide_shift_p']:.3f}|")
    lines += ['','原始水平字段（raw_log_*及平均每笔成交额）随时间漂移，其历史排名不能直接当成预测优势。移位检验依赖平稳近似，仅作探索性筛查；不能将普通逐日p值作为独立证据。','',
              '## 按季度前推：只用成熟历史选一个特征','',
              'select方法每季度从相应候选中选历史平均相关绝对值最大的一个；仅训练样本拟合逐币种秩缩放和单变量逻辑回归。训练标签成熟时间必须严格早于季度开始。无测试集调参。',
              'fixed方法的4个特征是在看过全历史排名后指定，虽按成熟时点训练，仍属事后选择的复核，不是独立确认；normalized筛选排除原始价格/活动水平。',
              f'前推日期：{dates[valid][0]}—{dates[valid][-1]}；此历史已消费，仅作时间顺序稳健性检查。','',
              '|方法|AUC|准确率|平衡准确率|Brier↓|相对频率Brier差的季度簇95%区间|',
              '|---|---:|---:|---:|---:|---|']
    for name,m in metrics.items():
        ci=m['brier_delta_quarter_ci95']
        lines.append(f"|{name}|{m['auc']:.4f}|{m['accuracy']:.2%}|{m['balanced_accuracy']:.2%}|{m['brier']:.5f}|[{ci[0]:+.5f}, {ci[1]:+.5f}]|")
    lines += ['','## 每年相关方向','', '|特征|'+'|'.join(by_year)+'|','|---|'+'---:|'*len(by_year)]
    for r in rows[:10]:
        lines.append('|'+r['feature']+'|'+'|'.join(f'{v:+.4f}' for v in r['yearly_correlations'].values())+'|')
    lines += ['', '## 前推选中特征次数','']
    for model in models[1:]:
        lines.append(f"- {model}: {dict(Counter(f['selections'][model] for f in folds))}")
    lines += ['','完整逐币、逐年、分位数组及检验见 results.json；全部排名见 ranking.csv；特征/目标/前推概率见 observations.npz。',
              '主动买卖差由2×主动买入USDT额/总USDT成交额−1计算，代表成交主动性，不代表外部现金净流入。原生字段定义参照 https://github.com/binance/binance-public-data 。']
    (args.output/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(output=str(args.output),rows=Y.size,features=len(names),metrics=metrics),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    with threadpool_limits(limits=2):
        main()
