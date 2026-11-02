"""Relabel pure structural environments; fixed state-only retraining and replay."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import json
from pathlib import Path

import joblib
import numpy as np

from qount.research.market_learning import fit_candidate
from qount.research.market_regimes import (
    SCHEMA, REGIMES, SHAPE_FEATURES, DESCRIPTIONS, compatible_strategy, environment_entry,
    DURATION_BINS, duration_bucket, duration_probabilities, environment_probabilities, environment_rows, select_environment, structural_candidates, window_regime,
)
from qount.research.market_stages import market_state_machine
from qount.research.market_state_scores import FEATURES
from qount.research.market_model_profit import replay_asset, summarize_portfolio
from study_binance_market_states import load_markets
from study_market_model_profit import DAILY, RAW, daily_bars, exchange_rules, load_npz
from study_market_strategy_router import PANEL, REFERENCE, known_time, open_time
from review_market_strategy_edge import message, payoff_stats, portfolio_comparison, independent_opportunities, selection_diagnostics


BASE_FEATURES = tuple(n for n in FEATURES if n not in ('action_age', 'event_age'))
POLICIES = ('legacy_common', 'legacy_filtered', 'v2_current', 'v2_tree70', 'v2_transition70')
HOLDING_BARS = 5
EVALUATION_HORIZONS = (1, 3, 5, 10)


def forecast_target_index(signal_index, group, holding_bars=HOLDING_BARS):
    """Return the last planned held candle, measured from the signal candle."""
    if signal_index < 0 or holding_bars < 1 or group not in ('crypto', 'etf_proxy'):
        raise ValueError('v2_invalid_forecast_clock')
    delay = 2 if group == 'crypto' else 1
    return signal_index + delay + holding_bars - 1


def available_forecast(book, at, bars, group):
    """Latest causal forecast whose target has not matured at ``at``."""
    position = int(np.searchsorted(book['known_at'], at, side='right') - 1)
    if position < 0:
        return None
    target = forecast_target_index(int(book['bar_index'][position]), group)
    if target >= len(bars) or at >= known_time(bars[target], group):
        return None
    return position


def feature_matrix(parent, indices, markets, environments, assets):
    cols = [list(parent['feature_names']).index(n) for n in BASE_FEATURES]
    numeric = parent['X'][indices][:, cols].astype(float)
    if np.any(parent['feature_available_at'][indices][:, cols] > parent['known_at'][indices, None]):
        raise ValueError('v2_future_input')
    snapshots = [environments[str(parent['group'][k])][str(parent['asset'][k])]
                 [markets[str(parent['group'][k])][str(parent['asset'][k])][int(parent['bar_index'][k])].t] for k in indices]
    if any(r['regime'] == 'unknown' for r in snapshots): raise ValueError('v2_unknown_input')
    numeric = np.c_[numeric, [[r['features'][name] for name in SHAPE_FEATURES] for r in snapshots]]
    classes = np.array([REGIMES.index(r['regime']) for r in snapshots])
    identity = np.array([assets.index(str(parent['asset'][k])) for k in indices])
    return np.c_[np.nan_to_num(numeric, nan=0), np.isnan(numeric), np.eye(len(REGIMES))[classes], np.eye(len(assets))[identity],
                 [[r['risk']['shock'], r['risk']['high_volatility']] for r in snapshots]]


def metrics(y, p):
    pred = p.argmax(1)
    return dict(rows=len(y), accuracy=float(np.mean(pred == y)),
        balanced_accuracy=float(np.mean([np.mean(pred[y == c] == c) for c in sorted(set(y))])),
        brier=float(np.mean(np.sum((p-np.eye(len(REGIMES))[y])**2, axis=1))),
        class_results=[dict(state=s, actual=int(sum(y == i)), predicted=int(sum(pred == i)),
            high_predictions=int(sum((pred == i) & (p.max(1) >= .7))),
            recall=float(np.mean(pred[y == i] == i)) if np.any(y == i) else None) for i, s in enumerate(REGIMES)])


def train(panel, targets, target_available, duration_targets, duration_available, current, matrix, archive):
    results = []; folds = []; latest = {}
    predictions = {f'tree_h{h}':np.full((len(panel['asset']), len(REGIMES)), np.nan) for h in EVALUATION_HORIZONS}
    predictions.update(transition=np.full((len(panel['asset']),len(REGIMES)),np.nan),
                       persistence=np.full((len(panel['asset']),len(REGIMES)),np.nan))
    test_indices = archive['index']
    for group in ('crypto','etf_proxy'):
        members = np.flatnonzero(panel['group'] == group)
        quarters = defaultdict(list)
        for k in test_indices[panel['group'][test_indices] == group]:
            d = dt.datetime.fromtimestamp(int(panel['known_at'][k])/1000, dt.timezone.utc)
            quarters[d.year, (d.month-1)//3*3+1].append(int(k))
        for (year, month), test in sorted(quarters.items()):
            cutoff = int(dt.datetime(year, month, 1, tzinfo=dt.timezone.utc).timestamp())*1000
            test = np.array(test)
            latest[group] = dict(schema=SCHEMA,state_names=list(REGIMES),cutoff=cutoff,
                horizon_classifiers={},training_class_counts={},supported_states={},
                unsupported_states={},uniform_prior_mix=.01,duration_classifiers={},
                duration_class_counts={},duration_uniform_prior_mix=.01,
                research_only=True,orders_authorized=False)
            for horizon in EVALUATION_HORIZONS:
                target=targets[horizon];available=target_available[horizon]
                past = members[(available[members] < cutoff) & (target[members] >= 0) & (current[members] >= 0)]
                test_h=test[(target[test] >= 0) & (current[test] >= 0)]
                if len(past) < 200 or len(test_h) == 0: continue
                fitted, _ = fit_candidate('tree', matrix[past], target[past], seed=17)
                proba = np.zeros((len(test_h),len(REGIMES))); proba[:,fitted[-1].classes_.astype(int)] = fitted.predict_proba(matrix[test_h])
                key=f'tree_h{horizon}';predictions[key][test_h] = proba
                folds.append(dict(group=group,horizon_bars=horizon,cutoff=cutoff,training_rows=len(past),test_rows=len(test_h),last_training_maturity=int(available[past].max())))
                latest[group]['horizon_classifiers'][str(horizon)] = fitted
                latest[group]['training_class_counts'][str(horizon)]={s:int(sum(target[past]==j)) for j,s in enumerate(REGIMES)}
                latest[group]['supported_states'][str(horizon)]=[REGIMES[int(c)] for c in fitted[-1].classes_]
                latest[group]['unsupported_states'][str(horizon)]=[s for j,s in enumerate(REGIMES) if j not in fitted[-1].classes_]
                duration=duration_targets[horizon];duration_maturity=duration_available[horizon]
                duration_past=past[(duration[ past ] >= 0) & (duration_maturity[past] < cutoff)]
                if len(duration_past) >= 200:
                    duration_fitted, _ = fit_candidate('tree', matrix[duration_past], duration[duration_past], seed=29)
                    latest[group]['duration_classifiers'][str(horizon)] = duration_fitted
                    latest[group]['duration_class_counts'][str(horizon)] = {
                        str(bucket): int(sum(duration[duration_past] == bucket - 1))
                        for bucket in DURATION_BINS
                    }
                if horizon == HOLDING_BARS:
                    latest[group]['classifier']=fitted
                    global_p = (np.bincount(target[past],minlength=len(REGIMES))+1)/(len(past)+len(REGIMES))
                    transition = []
                    for k in test_h:
                        y = target[past[current[past] == current[k]]]
                        transition.append((np.bincount(y,minlength=len(REGIMES))+50*global_p)/(len(y)+50))
                    predictions['transition'][test_h] = transition
                    predictions['persistence'][test_h] = np.eye(len(REGIMES))[current[test_h]]
        for horizon in EVALUATION_HORIZONS:
            p=predictions[f'tree_h{horizon}'];target=targets[horizon]
            ix = members[np.isfinite(p[members]).all(1) & (target[members]>=0)]
            if len(ix): results.append(dict(group=group,horizon_bars=horizon,model='tree',**metrics(target[ix],p[ix])))
        target=targets[HOLDING_BARS];ix=members[np.isfinite(predictions['transition'][members]).all(1) & (target[members]>=0)]
        for name in ('transition','persistence'):
            if len(ix): results.append(dict(group=group,horizon_bars=HOLDING_BARS,model=name,**metrics(target[ix],predictions[name][ix])))
        predictions['tree']=predictions[f'tree_h{HOLDING_BARS}']
        print('trained',group,'forecasts',len(ix),flush=True)
    return predictions, results, folds, latest


def make_books(panel, parent, predictions):
    books = {}
    for name,p in predictions.items():
        books[name] = {}
        for asset in sorted(set(panel['asset'])):
            use = np.flatnonzero((panel['asset'] == asset) & np.isfinite(p).all(1)); order = np.argsort(panel['known_at'][use]); use = use[order]
            books[name][str(asset)] = dict(known_at=panel['known_at'][use],bar_index=parent['bar_index'][panel['original_row'][use]],probabilities=p[use])
    return books


def decisions(markets, old, environments, books):
    proposed = {policy:{g:defaultdict(list) for g in markets} for policy in POLICIES}; diagnostics = defaultdict(Counter)
    for group, assets in markets.items():
        for asset,bars in assets.items():
            tree = books['tree'][asset]
            for i,bar in enumerate(bars):
                known = known_time(bar,group); at = i+(2 if group == 'crypto' else 1)
                if known < 1672531200000 or at >= len(bars): continue
                entry_at = open_time(bars[at],group)
                left = available_forecast(tree,known,bars,group); right = available_forecast(tree,entry_at,bars,group)
                if left is None or right is None: continue
                env = environments[group][asset][bar.t]; legacy = old[group][asset][bar.t]
                diagnostics[group]['current:'+env['regime']] += 1
                e = environment_entry(env,bar,legacy,allow_short=group == 'crypto')
                if e is None: continue
                base = dict(e,known_at=known,entry_at=entry_at,capacity=float(bar.v*bar.c*.001),regime=env['regime'])
                proposed['v2_current'][group][asset].append(base)
                for name in ('tree','transition'):
                    book = books[name][asset]
                    a = dict(zip(REGIMES,map(float,book['probabilities'][left])))
                    b = dict(zip(REGIMES,map(float,book['probabilities'][right])))
                    # Only messages available at each clock; require current
                    # structural compatibility, not prediction alone.
                    if select_environment(a) == env['regime'] == select_environment(b):
                        proposed['v2_'+name+'70'][group][asset].append(dict(base,model_known_at=int(book['known_at'][left])))
    # Preserve identical old entries, stops, targets and quantities in this
    # control. Filtering does not rebuild old box geometry or risk fractions.
    legacy_rows = json.loads(Path('state/research_runs/market_strategy_edge_review_20261031_final/opportunities.json').read_text())
    for row in legacy_rows:
        if not row['masks']['rules_common']: continue
        group=row['group'];asset=row['asset'];bars=markets[group][asset];book=books['tree'][asset]
        if message(book,row['known_at'],bars,group) is None or message(book,row['entry_at'],bars,group) is None: continue
        proposed['legacy_common'][group][asset].append(row)
        index = int(np.searchsorted([known_time(b,group) for b in bars],row['known_at']))
        env = environments[group][asset][bars[index].t]
        if compatible_strategy(env) == row['strategy']: proposed['legacy_filtered'][group][asset].append(row)
    return proposed, {g:dict(c) for g,c in diagnostics.items()}


def selection_review(proposed, books, markets, environments, prices, raw, filters):
    rows=[]
    for group,assets in markets.items():
        chosen={(a,d['known_at']) for a,v in proposed['v2_tree70'][group].items() for d in v}
        for a,entries in proposed['v2_current'][group].items():
            book=books['tree'][a];bars=assets[a]
            for d in entries:
                j=available_forecast(book,d['known_at'],bars,group)
                if j is None: continue
                source=int(book['bar_index'][j])
                rows.append(dict(d,group=group,asset=a,coverage=True,
                    masks=dict(model70=(a,d['known_at']) in chosen,ungated_common=True),
                    forecast_state=REGIMES[int(np.argmax(book['probabilities'][j]))],
                    endpoint_actual=window_regime([environments[group][a][bars[k].t]['regime']
                        for k in range(source+(2 if group=='crypto' else 1),forecast_target_index(source,group)+1)])))
    independent_opportunities(rows,prices,raw,filters)
    return [selection_diagnostics(rows,g) for g in markets],rows


def evaluate(proposed, prices, raw, filters, group, cost, strategy=None):
    sleeves = {}; lookup = {}
    for asset,bars in prices[group].items():
        entries = [d for d in proposed.get(asset,[]) if strategy is None or d['strategy'] == strategy]
        for d in entries: lookup[asset,d['known_at']] = d
        rules = dict(tick=0.,step=1.,min_qty=1.,min_notional=0.) if group == 'etf_proxy' else filters[asset].copy()
        rules.update(fee=.0005*cost,slippage=(.0015 if group == 'etf_proxy' else .0002)*cost,continuous_clock=group == 'crypto')
        s = replay_asset(bars,entries,[] if group == 'etf_proxy' else raw[asset+'_funding'],initial=10000/len(prices[group]),rules=rules)
        s['start_at'] = int(bars[0,0]);sleeves[asset] = s
    summary,times,nav,trades = summarize_portfolio(sleeves,10000,continuous=True)
    for t in trades:
        d = lookup[t['asset'],t['known_at']];distance = abs(t['entry']-d['stop'])+t['entry']*2*cost*(.0005+(.0015 if group == 'etf_proxy' else .0002))
        t.update(strategy=d['strategy'],net_R=t['net_pnl']/(t['quantity']*distance))
    return dict(group=group,cost_multiplier=cost,strategy=strategy,summary=summary,trade_payoffs=payoff_stats(trades)),times,nav,trades


def write_report(result):
    lines=['# 市场结构V3与持仓窗口概率预测验证','',
        '模型输出六类互斥结构的概率向量，以及从当前结构起算的持续时间分布（1至9根、10+根）。unknown只表示数据不足。预测目标是计划持仓窗口内的多数结构，窗口纯度不足60%时记为transition。事件与风险分开记录，概率本身不授予策略资格。','',
        '|环境|单一结构含义|','|---|---|']
    for s in REGIMES: lines.append(f'|{s}|{DESCRIPTIONS[s]}|')
    lines += ['', '## 状态纯度与分布', '', '|市场|环境计数|旧range中成为纯区间|', '|---|---|---|']
    for g,x in result['purity'].items():lines.append(f"|{g}|{x['environment_counts']}|{x['old_range_to_rotation']} / {x['old_range_count']}|")
    lines += ['', '## 六类窗口目标的分期限模型对照', '', '|市场/模型|持仓根数|行数|准确率|平衡准确率|Brier|','|---|---:|---:|---:|---:|---:|']
    for x in result['model_metrics']:lines.append(f"|{x['group']}/{x['model']}|{x['horizon_bars']}|{x['rows']}|{x['accuracy']:.2%}|{x['balanced_accuracy']:.2%}|{x['brier']:.5f}|")
    lines += ['', '不同持仓窗口的指标分别计算；不能把不同标签/窗口的准确率直接比较为模型提升。五根窗口另与状态持久和条件转移基线比较。持续时间头使用未来十根内从当前状态开始的连续段，成熟时间按十根终点计算。','',
        '## 固定策略组合', '', '|市场/路由|摩擦倍数|交易|净收益|CAGR|收盘MDD|', '|---|---:|---:|---:|---:|---:|']
    for x in result['portfolio_runs']:
        s=x['summary'];lines.append(f"|{x['group']}/{x['policy']}|{x['cost_multiplier']}|{s['trades']}|{s['total_return']:+.3%}|{s['cagr']:+.3%}|{s['mdd_close']:.3%}|")
    lines += ['', 'legacy_filtered只过滤旧机会、沿用原止损目标；v2_current另把区间止损目标换成定义环境的验证箱体。概率门还要求当前环境相容，不能凭预测逆当前结构交易。','',
        '## V2各实际策略独立回放', '', '|市场/策略|摩擦倍数|交易|净收益|平均计划净R及95%季度簇区间|', '|---|---:|---:|---:|---|']
    for x in result['strategy_runs']:
        t=x['trade_payoffs'];risk=t.get('planned_R',{});lines.append(f"|{x['group']}/{x['strategy']}|{x['cost_multiplier']}|{t['trades']}|{x['summary']['total_return']:+.3%}|{risk.get('mean')}; {risk.get('interval95')}|")
    lines += ['', '## 新模型相对同一V2策略机会的选择增量', '',
        '|市场|选中提议/独立成交|平均净R及季度簇区间|同资产/策略/季度等量随机净R|随机分位|', '|---|---:|---|---:|---:|']
    for x in result['selection_review']:
        if not x['selected_proposals']:continue
        s=x['selected'];p=x['matched_random'];lines.append(f"|{x['group']}|{s['proposals']}/{s['filled']}|{s['mean_net_R']}; {s['interval95']}|{p['mean_net_R']}|{p['percentile']:.2%}|")
    lines += ['', '独立机会允许重叠、固定初始资金，随机分位不作为正式显著性；不能等同组合净值。', '',
        '## 模型组合相对同一V2规则库', '', '|市场|敞口匹配|累计对数增量|平均季度对数增量95%区间|', '|---|---|---:|---|']
    for x in result['comparisons']:
        if x['left']=='v2_tree70' and x['right']=='v2_current':lines.append(f"|{x['group']}|{x['exposure_matched']}|{x['total_log_excess']:+.3%}|{x['interval95']}|")
    lines += ['', '敞口匹配为事后按平均收盘敞口缩放参考对数收益，只作诊断，不是可执行新组合或风险完全匹配。']
    lines += ['', '## 限制', '', *['- '+v for v in result['limitations']], '']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists(): p.error('preserve previous artifacts; select a new path')
    parent=load_npz(DAILY);panel=load_npz(PANEL);archive=load_npz(REFERENCE/'phase_predictions.npz');assets=sorted(map(str,set(parent['asset'])))
    markets,_,sources=load_markets();old={g:{a:market_state_machine(b) for a,b in m.items()} for g,m in markets.items()}
    environments={g:{a:environment_rows(b,old[g][a]) for a,b in m.items()} for g,m in markets.items()}
    purity={}
    for g,m in markets.items():
        counts=Counter();old_range=bounded=violations=0
        for a,bars in m.items():
            for b in bars:
                if known_time(b,g)<1672531200000:continue
                r=environments[g][a][b.t];counts[r['regime']]+=1
                if r['regime'] != 'unknown':
                    candidates=structural_candidates(r['features']);violations+=int(sum(candidates.values())>1)
                    if r['regime'] in candidates: assert candidates[r['regime']]
                if old[g][a][b.t]['action_state'] in ('range','wide_range'):
                    old_range+=1;bounded+=r['regime']=='rotation'
        purity[g]=dict(environment_counts=dict(counts),old_range_count=old_range,old_range_to_rotation=int(bounded),overlap_violations=violations)
    print('purity',purity,flush=True)
    current=np.full(len(panel['asset']),-1,int)
    targets={h:np.full(len(panel['asset']),-1,int) for h in EVALUATION_HORIZONS}
    target_available={h:np.zeros(len(panel['asset']),np.int64) for h in EVALUATION_HORIZONS}
    duration_targets={h:np.full(len(panel['asset']),-1,int) for h in EVALUATION_HORIZONS}
    duration_available={h:np.zeros(len(panel['asset']),np.int64) for h in EVALUATION_HORIZONS}
    for k,original in enumerate(panel['original_row']):
        g=str(panel['group'][k]);a=str(panel['asset'][k]);i=int(parent['bar_index'][original]);bars=markets[g][a]
        c=environments[g][a][bars[i].t]['regime']
        delay=2 if g=='crypto' else 1
        if c in REGIMES:current[k]=REGIMES.index(c)
        for horizon in EVALUATION_HORIZONS:
            endpoint=i+delay+horizon-1
            if endpoint>=len(bars): continue
            held=[environments[g][a][bars[j].t]['regime'] for j in range(i+delay,endpoint+1)]
            if any(state not in REGIMES for state in held): continue
            y=window_regime(held)
            targets[horizon][k]=REGIMES.index(y)
            target_available[horizon][k]=known_time(bars[endpoint],g)
            duration_end=min(i+delay+max(DURATION_BINS)-1, len(bars)-1)
            duration_held=[environments[g][a][bars[j].t]['regime'] for j in range(i+delay,duration_end+1)]
            if any(state not in REGIMES for state in duration_held): continue
            duration_targets[horizon][k]=duration_bucket(duration_held)-1
            duration_available[horizon][k]=known_time(bars[duration_end],g)
        assert panel['known_at'][k]==known_time(bars[i],g)
    valid=np.flatnonzero(current>=0);matrix=np.zeros((len(current),2*(len(BASE_FEATURES)+len(SHAPE_FEATURES))+len(REGIMES)+len(assets)+2))
    matrix[valid]=feature_matrix(parent,panel['original_row'][valid],markets,environments,assets)
    predictions,model_metrics,folds,bundles=train(panel,targets,target_available,duration_targets,duration_available,current,matrix,archive)
    books=make_books(panel,parent,predictions);proposed,diagnostics=decisions(markets,old,environments,books)
    raw=json.loads(RAW.read_text())['data'];filters=exchange_rules();prices={g:daily_bars(m,g) for g,m in markets.items()}
    portfolio_runs=[];strategy_runs=[];curves={};trades=[];paired={}
    for policy in POLICIES:
        for group in markets:
            for cost in (1,2):
                run,times,nav,tt=evaluate(proposed[policy][group],prices,raw,filters,group,cost);run.update(id=len(portfolio_runs),policy=policy)
                portfolio_runs.append(run);curves['times_'+str(run['id'])]=times;curves['nav_'+str(run['id'])]=nav;trades.extend(dict(run_id=run['id'],**t) for t in tt)
                if cost==1:paired[group,policy]=(run,times,nav)
                print(group,policy,cost,run['summary']['trades'],round(run['summary']['total_return'],6),flush=True)
    for group in markets:
        strategies=sorted({d['strategy'] for v in proposed['v2_current'][group].values() for d in v})
        for strategy in strategies:
            for cost in (1,2):strategy_runs.append(evaluate(proposed['v2_current'][group],prices,raw,filters,group,cost,strategy)[0])
    comparisons=[portfolio_comparison(paired[g,p],paired[g,'legacy_common']) for g in markets for p in POLICIES if p!='legacy_common']
    comparisons += [portfolio_comparison(paired[g,'v2_tree70'],paired[g,'v2_current'],exposure_match=match) for g in markets for match in (False,True)]
    selection,opportunities=selection_review(proposed,books,markets,environments,prices,raw,filters)
    args.output.mkdir(parents=True);latest_probabilities={};latest_probabilities_by_horizon={};latest_states=[]
    for group,bundle in bundles.items():
        bundle.update(assets=assets,numeric_features=list(BASE_FEATURES+SHAPE_FEATURES),input_dimensions=matrix.shape[1],
                      removed_legacy_state_tokens=True,unknown_probability_estimated=False,
                      probability_floor=1e-6,uniform_prior_mix=.01)
        joblib.dump(bundle,args.output/(group+'_state_model.joblib'),compress=3)
        for a,bars in markets[group].items():
            ix=np.flatnonzero(parent['asset']==a);k=int(ix[np.argmax(parent['known_at'][ix])]);i=int(parent['bar_index'][k])
            env=environments[group][a][bars[i].t];x=feature_matrix(parent,[k],markets,environments,assets)
            latest_probabilities_by_horizon[a]={}
            for horizon in EVALUATION_HORIZONS:
                horizon_bundle=dict(bundle,classifier=bundle['horizon_classifiers'][str(horizon)])
                state_prob=environment_probabilities(horizon_bundle,x)[0]
                latest_probabilities_by_horizon[a][str(horizon)]={'state_probabilities':state_prob}
                if str(horizon) in bundle.get('duration_classifiers', {}):
                    latest_probabilities_by_horizon[a][str(horizon)]['duration_probabilities'] = duration_probabilities(bundle,x,horizon)[0]
            prob=latest_probabilities_by_horizon[a][str(HOLDING_BARS)]['state_probabilities']
            latest_probabilities[a]=prob;latest_states.append(dict(asset=a,known_at=int(parent['known_at'][k])*1000,environment=env,
                selected_environment=select_environment(prob),compatible_strategy=compatible_strategy(env),research_only=True,orders_authorized=False))
    result=dict(research_only=True,orders_authorized=False,schema=SCHEMA,independent_oos=False,sources=sources,purity=purity,
        model_metrics=model_metrics,folds=folds,portfolio_runs=portfolio_runs,strategy_runs=strategy_runs,comparisons=comparisons,diagnostics=diagnostics,
        selection_review=selection,unsupported_states={g:b['unsupported_states'] for g,b in bundles.items()},
        state_names=list(REGIMES),parameters=dict(threshold=.70,target_convention='majority_state_during_held_window',
            future_endpoint_horizon={'crypto':6,'etf_proxy':5},entry_delay={'crypto':2,'etf_proxy':1},
            holding_bars=HOLDING_BARS,evaluation_horizons=list(EVALUATION_HORIZONS),
            window_majority_minimum_share=.60,refit='quarterly',seed=17,parameter_search=False),
        limitations=['仅修正结构语义与机械适配，不保证分类对应策略盈利；状态门、入场形态和净优势需分别评价。',
            '六类模型仅输出状态概率；transition/low_efficiency_chop是可解释的等待状态，突破/假突破是当前可观察事件，冲击/高波动是独立风险标记；unknown是数据不足，不编造监督概率。',
            '旧数据、旧十一类概率及旧模型完整保留；新模型通过独立schema防止类别概率被误解释。目标仅对齐计划持仓末根K线环境，不保证持仓中间路径安全或交易盈利。',
            '币种2023至2026-10、ETF现金代理2023至2025；15个固定存续标的、历史已消费，ETF不做空，不等同于Binance原生合约。',
            '每组合初始10,000、等额袖套、1%计划风险/1倍入场、现金0利息；币种单边5+2bp与实际资金费、ETF5+15bp；双摩擦重跑，沿用当前交易档位与整数股约束。',
            '币种信号i+2开盘，ETF次会话开盘；止损优先、退出规则未优化，MDD仅收盘；高波动标记不自动改预算，以避免新增风险缩放混杂。',
            '固定结构阈值未按收益优化；每个状态只标注策略兼容性，没有自动赋予盈利资格。各策略独立组合不能相加。',
            'rotation是结构描述而不是策略授权；每个窗口目标取持仓窗口多数状态，低于60%则标为transition，避免固定终点截断状态。',
            '季度模型仅使用此前成熟标签，全部输入按信息时点核对；策略兼容检查只看当时结构/事件，未用未来收益定义状态。',
            '季度簇区间未作多重比较校正；模型指标只在相同六类标签与相同持仓窗口内比较，不能跨定义或期限宣称准确率改善。'])
    for name,value in (('results.json',result),('latest_probabilities.json',latest_probabilities),
                       ('latest_probabilities_by_horizon.json',latest_probabilities_by_horizon),
                       ('latest_states.json',latest_states),('trades.json',trades),('opportunities.json',opportunities)):
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(args.output/'dataset.npz',X=matrix,current_state=current,
        outcome=targets[HOLDING_BARS],known_at=panel['known_at'],
        state_available=target_available[HOLDING_BARS],asset=panel['asset'],group=panel['group'],
        original_row=panel['original_row'],state_names=np.array(REGIMES),
        **{f'outcome_h{h}':targets[h] for h in EVALUATION_HORIZONS},
        **{f'state_available_h{h}':target_available[h] for h in EVALUATION_HORIZONS})
    np.savez_compressed(args.output/'predictions.npz',**{name:p for name,p in predictions.items()})
    np.savez_compressed(args.output/'equity.npz',**curves);(args.output/'report.md').write_text(write_report(result))
    print('saved',args.output,'fits',len(folds),flush=True)


if __name__=='__main__':main()
