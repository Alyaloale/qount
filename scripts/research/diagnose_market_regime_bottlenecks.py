"""Separate label coverage, strategy edge, prediction error and forecast clocks.

Fixed V2 labels, original opportunity pool, original 70% threshold and costs.
Daily refresh / end-of-holding labels are controlled offline alternatives;
no payoff model, parameter search, production state or order client.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import datetime as dt
import json
from pathlib import Path

import joblib
import numpy as np

from qount.research.market_learning import fit_candidate
from qount.research.market_regimes import REGIMES, SCHEMA, environment_rows, select_environment
from qount.research.market_stages import market_state_machine
from study_binance_market_states import load_markets
from study_market_model_profit import DAILY, RAW, daily_bars, exchange_rules, load_npz
from study_market_regimes import feature_matrix, make_books, evaluate
from study_market_strategy_router import known_time, open_time
from review_market_strategy_edge import message, independent_opportunities, selection_diagnostics, cluster_interval, portfolio_comparison


REFERENCE=Path('state/research_runs/market_regimes_v2_20261031_final')
POLICIES=('current','stale70','daily70','aligned70')
FAMILIES=('all','trend_pullback_long','trend_rally_short','confirmed_breakout_long','confirmed_breakout_short')


def latest_message(book, at):
    j=int(np.searchsorted(book['known_at'],at,side='right')-1)
    return j if j>=0 else None


def forecast_endpoint_indices(source_index, group, holding_bars=5):
    """Last held completed candle before the scheduled horizon-open exit."""
    if source_index<0 or holding_bars<1 or group not in ('crypto','etf_proxy'):
        raise ValueError('invalid_forecast_holding_clock')
    delay=2 if group=='crypto' else 1
    return source_index+delay+holding_bars-1


def shifted_training_targets(data,parent,markets,environments,group):
    y=np.full(len(data['asset']),-1,int);maturity=np.zeros(len(y),np.int64)
    for k in np.flatnonzero(data['group']==group):
        a=str(data['asset'][k]);i=int(parent['bar_index'][data['original_row'][k]])
        end=forecast_endpoint_indices(i,group);bars=markets[group][a]
        if end>=len(bars):continue
        state=environments[group][a][bars[end].t]['regime']
        if state in REGIMES:y[k]=REGIMES.index(state);maturity[k]=known_time(bars[end],group)
    return y,maturity


def dense_forecasts(data,parent,markets,environments,old_result,old_predictions):
    assets=sorted(map(str,set(parent['asset'])));indices=np.arange(len(parent['asset']))
    matrix=feature_matrix(parent,indices,markets,environments,assets)
    np.testing.assert_allclose(matrix[data['original_row']],data['X'],rtol=0,atol=1e-12)
    predictions={name:np.full((len(indices),len(REGIMES)),np.nan) for name in ('daily70','aligned70')}
    known=parent['known_at']*1000;fits=[];latest={};old_matches=0
    for group in markets:
        members=np.flatnonzero(data['group']==group)
        aligned_y,aligned_maturity=shifted_training_targets(data,parent,markets,environments,group)
        for f in (f for f in old_result['folds'] if f['group']==group):
            cutoff=f['cutoff'];d=dt.datetime.fromtimestamp(cutoff/1000,dt.timezone.utc)
            next_year=d.year+(d.month==10);next_month=1 if d.month==10 else d.month+3
            end=int(dt.datetime(next_year,next_month,1,tzinfo=dt.timezone.utc).timestamp())*1000
            test=np.flatnonzero((parent['group']==group)&(known>=cutoff)&(known<end))
            for name,y,maturity in (('daily70',data['outcome'],data['state_available']),('aligned70',aligned_y,aligned_maturity)):
                if name=='aligned70' and group=='etf_proxy':
                    predictions[name][test]=predictions['daily70'][test]
                    continue
                past=members[(maturity[members]<cutoff)&(maturity[members]>0)&(y[members]>=0)&(data['current_state'][members]>=0)]
                model,_=fit_candidate('tree',data['X'][past],y[past],seed=17)
                p=np.zeros((len(test),len(REGIMES)));p[:,model[-1].classes_.astype(int)]=model.predict_proba(matrix[test])
                predictions[name][test]=p
                fits.append(dict(group=group,variant=name,cutoff=cutoff,train=len(past),test=len(test),last_maturity=int(maturity[past].max())))
                if name=='daily70':
                    legacy_test=np.flatnonzero((data['group']==group)&(data['known_at']>=cutoff)&(data['known_at']<end)&np.isfinite(old_predictions['tree']).all(1))
                    actual=predictions[name][data['original_row'][legacy_test]]
                    np.testing.assert_allclose(actual,old_predictions['tree'][legacy_test],rtol=0,atol=1e-12);old_matches+=len(legacy_test)
                if name=='aligned70' or group=='etf_proxy':
                    latest[group]=dict(schema=SCHEMA,classifier=model,state_names=list(REGIMES),assets=assets,cutoff=cutoff,
                        horizon_observations=6 if group=='crypto' else 5,target_convention='last_held_session_for_5_bar_trade',
                        input_dimensions=data['X'].shape[1],feature_builder='study_market_regimes.feature_matrix',
                        supported_states=[REGIMES[int(c)] for c in model[-1].classes_],
                        unsupported_states=[s for j,s in enumerate(REGIMES) if j not in model[-1].classes_],
                        probabilities_conditional_on_observed_classes=True,
                        output='state_probabilities_only',research_only=True,orders_authorized=False)
        print('daily inference',group,'fit count',sum(f['group']==group for f in fits),flush=True)
    books={}
    for name,p in predictions.items():
        books[name]={}
        for a in assets:
            ix=np.flatnonzero((parent['asset']==a)&np.isfinite(p).all(1));ix=ix[np.argsort(known[ix])]
            books[name][a]=dict(known_at=known[ix],bar_index=parent['bar_index'][ix],probabilities=p[ix])
    return books,predictions,fits,latest,old_matches


def annotate(rows,books,old_books,markets,environments):
    records=copy.deepcopy(rows)
    for r in records:
        g=r['group'];a=r['asset'];bars=markets[g][a]
        entry=int(np.searchsorted([open_time(b,g) for b in bars],r['entry_at']))
        last_held=entry+r['max_bars']-1
        r['masks'].update(current=True,stale70=r['masks']['model70'])
        r['forecasts']={}
        for name in POLICIES[1:]:
            book=old_books[a] if name=='stale70' else books[name][a]
            get=(lambda t:message(book,t,bars,g)) if name=='stale70' else (lambda t:latest_message(book,t))
            signal=get(r['known_at']);j=get(r['entry_at'])
            if signal is None or j is None:r['masks'][name]=False;continue
            p0=dict(zip(REGIMES,map(float,book['probabilities'][signal])))
            p1=dict(zip(REGIMES,map(float,book['probabilities'][j])))
            source=int(book['bar_index'][j]);horizon=6 if name=='aligned70' and g=='crypto' else 5
            target=source+horizon;target_close=bars[target].t*1000+999 if target<len(bars) else None
            enabled=select_environment(p0)==r['regime']==select_environment(p1)
            # End-aligned permission must cover every planned held candle.
            if name=='aligned70':enabled=enabled and target>=last_held
            if name=='stale70':assert enabled==r['masks'][name]
            else:r['masks'][name]=bool(enabled)
            r['forecasts'][name]=dict(source_index=source,model_known_at=int(book['known_at'][j]),
                state=REGIMES[int(np.argmax(book['probabilities'][j]))],probability=float(p1[r['regime']]),
                actual=environments[g][a][bars[target].t]['regime'] if target<len(bars) else None,
                target_closed_before_entry=bool(target_close is not None and target_close<r['entry_at']),
                last_held_minus_target=last_held-target)
            assert book['known_at'][signal]<=r['known_at'] and book['known_at'][j]<=r['entry_at']
    return records


def forecast_diagnosis(rows,group,policy,strategy=None):
    v=[r for r in rows if r['group']==group and 'standalone' in r and policy in r['forecasts']
       and (strategy is None or r['strategy']==strategy)]
    selected=[r for r in v if r['masks'][policy]]
    def economic(x):
        if not x:return dict(proposals=0)
        values=[r['standalone']['net_R'] for r in x]
        return dict(proposals=len(x),filled=sum(r['standalone']['filled'] for r in x),mean_net_R=float(np.mean(values)),
            interval95=cluster_interval(values,[r['known_at'] for r in x],weights=np.ones(len(x)))['interval95'],
            reasons=dict(Counter(r['standalone']['reason'] for r in x)))
    correct=[r for r in selected if r['forecasts'][policy]['state']==r['forecasts'][policy]['actual']]
    wrong=[r for r in selected if r['forecasts'][policy]['state']!=r['forecasts'][policy]['actual']]
    all_stats=economic(v);selected_stats=economic(selected)
    selected_stats.update(precision=len(correct)/len(selected) if selected else None,
        expired_targets=sum(r['forecasts'][policy]['target_closed_before_entry'] for r in selected),
        shortfalls=dict(Counter(str(r['forecasts'][policy]['last_held_minus_target']) for r in selected)))
    return dict(group=group,policy=policy,strategy=strategy,all_opportunities=all_stats,selected=selected_stats,
        correct_endpoint=economic(correct),wrong_endpoint=economic(wrong),
        correct_but_losing=sum(r['standalone']['filled'] and r['standalone']['net_R']<0 for r in correct))


def bracket_diagnosis(rows,markets,old,prices,raw,filters):
    simple=copy.deepcopy(rows)
    for r in simple:
        bars=markets[r['group']][r['asset']];i=int(np.searchsorted([known_time(b,r['group']) for b in bars],r['known_at']))
        f=old[r['group']][r['asset']][bars[i].t]
        r.update(stop=bars[i].c-r['side']*2*f['atr14'],target=None)
        r.pop('standalone',None)
    independent_opportunities(simple,prices,raw,filters)
    out=[]
    for group in markets:
        for strategy in sorted({r['strategy'] for r in rows if r['group']==group}):
            pairs=[(a,b) for a,b in zip(rows,simple) if a['group']==group and a['strategy']==strategy
                   and a.get('standalone',{}).get('filled') and b.get('standalone',{}).get('filled')]
            if not pairs:continue
            a=np.array([x['standalone']['net_notional'] for x,_ in pairs]);b=np.array([x['standalone']['net_notional'] for _,x in pairs])
            out.append(dict(group=group,strategy=strategy,common_filled=len(pairs),original_mean_net_notional=float(a.mean()),
                plain_2atr_mean_net_notional=float(b.mean()),mean_difference=float(np.mean(b-a)),
                interval95=cluster_interval(b-a,[x['known_at'] for x,_ in pairs],weights=np.ones(len(pairs)))['interval95']))
    return out


def classification_diagnostics(data,predictions):
    results=[]
    for g in ('crypto','etf_proxy'):
        ix=np.flatnonzero((data['group']==g)&np.isfinite(predictions['tree']).all(1))
        p=predictions['tree'][ix];y=data['outcome'][ix];top=p.argmax(1)
        for j,state in enumerate(REGIMES):
            high=(top==j)&(p[:,j]>=.7)
            results.append(dict(group=g,state=state,total=len(ix),actual=int(sum(y==j)),predicted=int(sum(top==j)),
                high_predictions=int(sum(high)),high_precision=float(np.mean(y[high]==j)) if high.any() else None))
    return results


def setup_probability_diagnostics(rows):
    results=[]
    for g in ('crypto','etf_proxy'):
        for s in sorted({r['strategy'] for r in rows if r['group']==g}):
            for policy in ('daily70','aligned70'):
                p=[r['forecasts'][policy]['probability'] for r in rows if r['group']==g and r['strategy']==s and policy in r['forecasts']]
                if p:results.append(dict(group=g,strategy=s,policy=policy,proposals=len(p),median=float(np.median(p)),maximum=float(max(p)),above70=sum(v>=.7 for v in p)))
    return results


def report(r):
    lines=['# 状态、策略、模型与预测时钟：瓶颈定位','',
        '状态定义、策略参数、70%门槛及原机会池固定；每日更新及预测终点对齐是离线对照，未改变当前模型或实盘。','',
        '## 当前研究取舍', '',
        '优先研究币种上行趋势中的确认突破做多；下行趋势中的确认破位做空保留为低优先级对照。两者均未取得可靠盈利资格。回调/反弹在新鲜概率门下无合格交易，震荡/假突破受标签不足限制，暂不扩展。', '',
        '## 预测与入场形态是否冲突', '', '|市场/形态|概率目标|提议数|对应趋势概率中位数|最大值|达到70%数量|', '|---|---|---:|---:|---:|---:|']
    for x in r['setup_probability_diagnostics']:
        lines.append(f"|{x['group']}/{x['strategy']}|{x['policy']}|{x['proposals']}|{x['median']:.2%}|{x['maximum']:.2%}|{x['above70']}|")
    lines += ['',
        '## 精简策略：独立组合', '', '|市场/策略/概率来源|成本倍数|交易|净收益|平均净R及季度95%区间|','|---|---:|---:|---:|---|']
    for x in r['runs']:
        if x['family']=='all':continue
        s=x['summary'];risk=x['trade_payoffs'].get('planned_R',{})
        lines.append(f"|{x['group']}/{x['family']}/{x['policy']}|{x['cost_multiplier']}|{s['trades']}|{s['total_return']:+.3%}|{risk.get('mean')}; {risk.get('interval95')}|")
    lines += ['', '## 原完整策略库控制', '', '|市场/来源|成本倍数|交易|净收益|收盘MDD|','|---|---:|---:|---:|---:|']
    for x in r['runs']:
        if x['family']!='all':continue
        s=x['summary'];lines.append(f"|{x['group']}/{x['policy']}|{x['cost_multiplier']}|{s['trades']}|{s['total_return']:+.3%}|{s['mdd_close']:.3%}|")
    lines += ['', '## 两个币种候选的失败时期与集中度（终点对齐、基础成本）', '',
        '|候选|年度收益|剔除最大盈利交易的静态净盈亏|剔除最大盈利资产的静态净盈亏|', '|---|---|---:|---:|']
    for x in r['runs']:
        if x['group']!='crypto' or x['policy']!='aligned70' or x['cost_multiplier']!=1 or x['family'] not in ('confirmed_breakout_long','confirmed_breakout_short'):continue
        s=x['summary'];t=x['trade_payoffs'];years=', '.join(f'{y}:{v:+.3%}' for y,v in s['yearly_returns'].items())
        lines.append(f"|{x['family']}|{years}|{t['net_pnl_without_best_trade']:+.3f}|{t['net_pnl_without_best_asset']:+.3f}|")
    lines += ['', '静态剔除仅检查依赖，不是删除交易或资产后重新回放。两个候选存在亏损年份，均非已验证的稳定盈利策略。']
    lines += ['', '## 同一机会：预测正确与经济结果', '', '|市场/来源/策略|选中提议|状态精度|正确时净R|错误时净R|正确但净亏笔数|目标已收盘|','|---|---:|---:|---:|---:|---:|---:|']
    for x in r['forecast_diagnostics']:
        s=x['selected']
        if not s['proposals']:continue
        lines.append(f"|{x['group']}/{x['policy']}/{x['strategy'] or 'all'}|{s['proposals']}|{s['precision']:.2%}|{x['correct_endpoint'].get('mean_net_R')}|{x['wrong_endpoint'].get('mean_net_R')}|{x['correct_but_losing']}|{s['expired_targets']}|")
    lines += ['', '## 入场相同，仅把突破退出改为普通2ATR止损、5棒持有', '', '|市场/策略|共同成交机会|原单位名义净收益|简单退出净收益|配对增量95%区间|','|---|---:|---:|---:|---|']
    for x in r['bracket_diagnostics']:
        lines.append(f"|{x['group']}/{x['strategy']}|{x['common_filled']}|{x['original_mean_net_notional']:+.3%}|{x['plain_2atr_mean_net_notional']:+.3%}|{x['interval95']}|")
    lines += ['', '## 等数量选择对照（固定资金，允许重叠）', '', '|市场/来源/策略|选中提议|平均净R|匹配随机净R|随机分位|','|---|---:|---:|---:|---:|---:|']
    for x in r['selection_diagnostics']:
        if not x['selected_proposals']:continue
        s=x['selected'];p=x['matched_random'];lines.append(f"|{x['group']}/{x['selection']}/{x['strategy'] or 'all'}|{s['proposals']}|{s['mean_net_R']:+.4f}|{p['mean_net_R']:+.4f}|{p['percentile']:.1%}|")
    lines += ['', '## 限制', '', *['- '+x for x in r['limitations']], '']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error('preserve prior results; choose a new output')
    result0=json.loads((REFERENCE/'results.json').read_text());data=load_npz(REFERENCE/'dataset.npz');parent=load_npz(DAILY);pred0=load_npz(REFERENCE/'predictions.npz')
    markets,_,sources=load_markets();old={g:{a:market_state_machine(b) for a,b in assets.items()} for g,assets in markets.items()}
    envs={g:{a:environment_rows(b,old[g][a]) for a,b in assets.items()} for g,assets in markets.items()}
    books,dense,fits,models,matches=dense_forecasts(data,parent,markets,envs,result0,pred0)
    old_books=make_books(data,parent,pred0)['tree'];rows=annotate(json.loads((REFERENCE/'opportunities.json').read_text()),books,old_books,markets,envs)
    raw=json.loads(RAW.read_text())['data'];filters=exchange_rules();prices={g:daily_bars(assets,g) for g,assets in markets.items()}
    runs=[];curves={};trades=[];pair={};controls=0
    previous=load_npz(REFERENCE/'equity.npz')
    for group in markets:
        for family in FAMILIES:
            pool=[x for x in rows if x['group']==group and (family=='all' or x['strategy']==family)]
            if not pool:continue
            for policy in POLICIES:
                proposed={}
                for a in markets[group]:proposed[a]=[x for x in pool if x['asset']==a and x['masks'][policy]]
                for cost in (1,2):
                    run,times,nav,tt=evaluate(proposed,prices,raw,filters,group,cost);run.update(id=len(runs),policy=policy,family=family)
                    runs.append(run);curves['times_'+str(run['id'])]=times;curves['nav_'+str(run['id'])]=nav;trades.extend(dict(run_id=run['id'],**t) for t in tt)
                    if cost==1:pair[group,family,policy]=(run,times,nav)
                    if family=='all' and policy in ('current','stale70'):
                        before=next(z for z in result0['portfolio_runs'] if z['group']==group and z['policy']==('v2_current' if policy=='current' else 'v2_tree70') and z['cost_multiplier']==cost)
                        np.testing.assert_allclose(nav,previous['nav_'+str(before['id'])],rtol=0,atol=1e-8);controls+=1
            print(group,family,'done',flush=True)
    diagnostics=[forecast_diagnosis(rows,g,p,s) for g in markets for p in POLICIES[1:] for s in (None,)+FAMILIES[1:]]
    selections=[]
    for policy in POLICIES[1:]:
        ready=[dict(x,forecast_state=x['forecasts'][policy]['state'],endpoint_actual=x['forecasts'][policy]['actual']) for x in rows if policy in x['forecasts']]
        selections.extend(selection_diagnostics(ready,g,s,selection=policy) for g in markets for s in (None,)+FAMILIES[1:])
    comparison=[portfolio_comparison(pair[g,f,p],pair[g,f,'current']) for g,f,p in pair if p!='current']
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,sources=sources,
        runs=runs,forecast_diagnostics=diagnostics,selection_diagnostics=selections,
        bracket_diagnostics=bracket_diagnosis(rows,markets,old,prices,raw,filters),comparisons=comparison,
        fits=fits,old_forecast_matches=matches,original_nav_controls=controls,
        classification_diagnostics=classification_diagnostics(data,pred0),setup_probability_diagnostics=setup_probability_diagnostics(rows),
        parameters=dict(threshold=.70,state_schema=SCHEMA,fresh_target=5,aligned_target_crypto=6,aligned_target_etf=5,seed=17,parameter_search=False),
        limitations=['五类标签、原377个入场提议、策略及成本固定。新终点仅用于时间错位消融，未替换当前主模型或更改其未来5期口径。',
            'daily70复用相同5期目标和季度成熟训练池，仅每日推理；原3,138个稀疏预测逐值复现。aligned70币种改学第6期末、ETF仍第5期末，覆盖计划5棒持仓的最后一棒。',
            '未来终点状态不保证中间路径或交易盈利。预测正确/错误的分组是事后诊断，不是可交易真值筛选或因果贡献分解。',
            '币种2023至2026-10、ETF现金代理2023至2025，15个固定存续标的、历史已消费；ETF不做空，非原生Binance代理合约成交认证。',
            '每个独立策略组合初始10,000、等额袖套、最多1%计划风险/1倍入场；币种单边5+2bp加实际资金费，ETF5+15bp，双摩擦重跑。',
            '币种i+2开盘、ETF次会话开盘，固定退出与止损优先规则、当前历史套用交易档位、MDD仅收盘继续保留。',
            '简单退出对照只在两个规则都成交的相同提议上比较单位名义收益，仍允许重叠，不是独立账户回报。',
            '候选族独立回放改变占仓竞争，收益不可相加。等量随机在同资产/策略/季度匹配，但分位未经多重比较校正，不作显著性认证。',
            '新类别样本不足与未明类别占比高的问题未通过本轮换标签掩盖；未训练收益头或扩大网络。'])
    args.output.mkdir(parents=True)
    for name,value in (('results.json',result),('opportunities.json',rows),('trades.json',trades)):
        (args.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    for group,bundle in models.items():joblib.dump(bundle,args.output/(group+'_aligned_state_model.joblib'),compress=3)
    np.savez_compressed(args.output/'daily_predictions.npz',**dense)
    np.savez_compressed(args.output/'equity.npz',**curves);(args.output/'report.md').write_text(report(result))
    print('saved',args.output,'fits',len(fits),'old forecast matches',matches,'NAV controls',controls,flush=True)


if __name__=='__main__':main()
