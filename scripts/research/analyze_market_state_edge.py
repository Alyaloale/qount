"""Diagnose state errors versus payoff errors; fixed causal head ablations."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import datetime as dt
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from qount.research.market_learning import fit_candidate
from qount.research.market_model_profit import replay_asset,summarize_portfolio
from qount.research.market_state_scores import (
    STATE_NAMES,ACTIONS,state_code,payoff_table,action_scores,action_probability_scores,past_score_threshold,
)
from qount.research.market_state_validation import scores
from train_market_state_scores import load_npz,make_panel,all_bars
from study_market_model_profit import DAILY,RAW,exchange_rules,daily_bars
from study_binance_market_states import load_markets
from qount.research.market_stages import market_state_machine


REFERENCE=Path('state/research_runs/market_state_scores_20261031_probability_gated')
FAMILY=np.array([0,0,0,1,2,1,2,2,1,3,4,5])
INTERACTIONS=(0,3,4,5,6,9,12,16)


def quarter(stamp):
    d=dt.datetime.fromtimestamp(int(stamp)/1000,dt.timezone.utc)
    return int(dt.datetime(d.year,(d.month-1)//3*3+1,1,tzinfo=dt.timezone.utc).timestamp())*1000


def metric(y,p):return scores([dict(outcome=int(t),probabilities=v.tolist()) for t,v in zip(y,p)])


def error_diagnostics(data,archive,reference):
    out=[];lookup={(r['group'],r['model'],r['cutoff']):r for r in reference['thresholds']}
    for group in ('crypto','etf_proxy'):
        rows=[r for r in archive if r['group']==group and r['model']=='tree'];ix=np.array([r['index'] for r in rows]);p=np.array([r['probabilities'] for r in rows]);y=data['outcome'][ix]
        guess=p.argmax(1);family_p=np.stack([p[:,FAMILY==j].sum(1) for j in range(6)],axis=1)
        decomposition=[];classes=[]
        for c,name in enumerate(STATE_NAMES):
            mask=y==c
            if mask.any():classes.append(dict(state=name,support=int(mask.sum()),predicted=int(sum(guess==c)),recall=float(np.mean(guess[mask]==c))))
        for r in rows:
            k=r['index'];support=action_probability_scores(np.array([r['probabilities']]))[0]
            v=np.array([z if z is not None else -np.inf for z in r['score']]);v[support<70]=-np.inf;a=int(v.argmax())
            if r['threshold'] is None or v[a]<max(.1,r['threshold']):continue
            table=lookup[group,'tree',quarter(r['known_at'])];oracle=table['payoff_mean_R'][int(data['outcome'][k])][a]
            actual=float(data['returns'][k,a]);expected=r['expected'][a]
            decomposition.append(dict(index=k,action=a,expected=expected,oracle_state_table=oracle,actual=actual,
                probability_component=expected-oracle,payoff_component=oracle-actual))
        out.append(dict(group=group,fine=metric(y,p),coarse=metric(FAMILY[y],family_p),classes=classes,
            copy_current_accuracy=float(np.mean(data['current_state'][ix]==y)),
            fine_errors_same_family=float(np.mean(FAMILY[guess[guess!=y]]==FAMILY[y[guess!=y]])),
            high_score_decomposition=decomposition,
            decomposition_means={k:float(np.mean([r[k] for r in decomposition])) for k in
                ('expected','oracle_state_table','actual','probability_component','payoff_component')}))
    return out


def label_diagnostics(parent,markets,states,data):
    out=[]
    for group in ('crypto','etf_proxy'):
        runs=defaultdict(list);persistence=defaultdict(list)
        for asset,bars in markets[group].items():
            previous=None;length=0;left_censored=True
            for b in bars:
                if b.t<1672531200:continue
                s=state_code(states[group][asset][b.t]['action_state'])
                if previous is not None and previous!=s:
                    if not left_censored:runs[STATE_NAMES[previous]].append(length)
                    left_censored=False;length=0
                previous=s;length+=1
            # Last spell is censored, never counted as a completed duration.
        for k in np.flatnonzero(data['group']==group):
            if data['known_at'][k]<1672531200000:continue
            original=int(data['original_row'][k]);i=int(parent['bar_index'][original]);a=str(data['asset'][k]);bars=markets[group][a]
            for h in (1,3,5):
                future=state_code(states[group][a][bars[i+h].t]['action_state']);persistence[h].append(future==data['current_state'][k])
        out.append(dict(group=group,completed_spells={s:dict(count=len(v),median=float(np.median(v)),
            fraction_at_most_two=float(np.mean(np.array(v)<=2))) for s,v in runs.items()},
            persistence={str(h):float(np.mean(v)) for h,v in persistence.items()}))
    return out


def horizon_experiment(data,parent,markets,states,archive):
    results=[];fits=[]
    for group in ('crypto','etf_proxy'):
        rows=[r for r in archive if r['group']==group and r['model']=='tree'];group_ix=np.flatnonzero(data['group']==group)
        groups=defaultdict(list)
        for r in rows:groups[quarter(r['known_at'])].append(r['index'])
        for horizon in (1,3):
            y=np.full(len(data['outcome']),-1,int)
            for k in group_ix:
                original=int(data['original_row'][k]);i=int(parent['bar_index'][original]);a=str(data['asset'][k]);b=markets[group][a][i+horizon]
                y[k]=state_code(states[group][a][b.t]['action_state'])
            predictions=[];truth=[]
            for cutoff,test in sorted(groups.items()):
                train=group_ix[data['state_available'][group_ix]<cutoff];test=np.array(test)
                fitted,_=fit_candidate('tree',data['X'][train],y[train],seed=17)
                p=np.zeros((len(test),len(STATE_NAMES)));p[:,fitted[-1].classes_.astype(int)]=fitted.predict_proba(data['X'][test])
                predictions.extend(p);truth.extend(y[test]);fits.append(dict(group=group,horizon=horizon,cutoff=cutoff,
                    train=len(train),test=len(test),last_training_maturity=int(data['state_available'][train].max())))
            results.append(dict(group=group,horizon=horizon,scores=metric(truth,np.array(predictions))))
            print('horizon',group,horizon,results[-1]['scores']['accuracy'],flush=True)
    return results,fits


def transition_payoffs(data,returns,base,train,test):
    """Current x future state mean, shrunk toward the old future-only table."""
    table=np.tile(base['mean'][None,:,:],(len(STATE_NAMES),1,1))
    for current in range(len(STATE_NAMES)):
        for future in range(len(STATE_NAMES)):
            use=train[(data['current_state'][train]==current)&(data['outcome'][train]==future)]
            for action in range(len(ACTIONS)):
                values=returns[use,action];valid=np.isfinite(values);dates=defaultdict(list)
                for v,t in zip(values[valid],data['known_at'][use][valid]):dates[int(t)].append(float(v))
                means=np.array([np.mean(v) for v in dates.values()])
                table[current,future,action]=(means.sum()+50*base['mean'][future,action])/(len(means)+50)
    return table[data['current_state'][test]]


def conditioned_matrix(X,current,future):
    f=np.eye(len(STATE_NAMES))[future];c=np.eye(6)[FAMILY[current]]
    return np.c_[X,f,(c[:,:,None]*f[:,None,:]).reshape(len(X),-1),
                 (X[:,INTERACTIONS,None]*f[:,None,:]).reshape(len(X),-1)]


def regress_payoffs(data,returns,train,test,*,conditioned):
    expected=np.zeros((len(test),len(STATE_NAMES),len(ACTIONS)));fits=[]
    if conditioned:
        prediction_matrix=conditioned_matrix(np.repeat(data['X'][test],len(STATE_NAMES),axis=0),
            np.repeat(data['current_state'][test],len(STATE_NAMES)),np.tile(np.arange(len(STATE_NAMES)),len(test)))
    else:prediction_matrix=data['X'][test]
    for action in range(len(ACTIONS)):
        use=train[np.isfinite(returns[train,action])]
        if len(use)<80:continue
        values=(conditioned_matrix(data['X'][use],data['current_state'][use],data['outcome'][use])
                if conditioned else data['X'][use])
        scaler=StandardScaler();values=scaler.fit_transform(values)
        clocks,counts=np.unique(data['known_at'][use],return_counts=True)
        weight=1/counts[np.searchsorted(clocks,data['known_at'][use])];weight*=len(weight)/weight.sum()
        learner=Ridge(alpha=200.).fit(values,returns[use,action],sample_weight=weight)
        p=learner.predict(scaler.transform(prediction_matrix))
        expected[:,:,action]=p.reshape(len(test),len(STATE_NAMES)) if conditioned else p[:,None]
        fits.append(dict(action=action,rows=len(use),dates=len(clocks),features=values.shape[1],
            last_payoff_maturity=int(data['return_available'][use,action].max())))
    return expected,fits


def payoff_experiment(data,archive,source):
    heads=('future_table','transition_table','context_ridge','direct_ridge_control')
    saved=[];fits=[];classifier_fits=[]
    for group in ('crypto','etf_proxy'):
        all_ix=np.flatnonzero(data['group']==group);past={h:[] for h in heads};forecasts={}
        # Reconstruct only the eight 2022 tree folds needed for causal warmup.
        for cutoff in sorted({f['cutoff'] for f in source['fits'] if f['group']==group and f['model']=='tree' and f['cutoff']<1672531200000}):
            year=dt.datetime.fromtimestamp(cutoff/1000,dt.timezone.utc).year;month=dt.datetime.fromtimestamp(cutoff/1000,dt.timezone.utc).month
            end=int(dt.datetime(year+month//10,(month+2)%12+1,1,tzinfo=dt.timezone.utc).timestamp())*1000
            test=all_ix[(data['known_at'][all_ix]>=cutoff)&(data['known_at'][all_ix]<end)]
            train=all_ix[data['state_available'][all_ix]<cutoff]
            fitted,_=fit_candidate('tree',data['X'][train],data['outcome'][train],seed=17)
            p=np.zeros((len(test),len(STATE_NAMES)));p[:,fitted[-1].classes_.astype(int)]=fitted.predict_proba(data['X'][test])
            forecasts[cutoff]=[(int(k),v) for k,v in zip(test,p)]
            classifier_fits.append(dict(group=group,cutoff=cutoff,train=len(train),test=len(test),purpose='2022 score threshold warmup'))
        for r in archive:
            if r['group']==group and r['model']=='tree':forecasts.setdefault(quarter(r['known_at']),[]).append((r['index'],np.array(r['probabilities'])))
        for cutoff,items in sorted(forecasts.items()):
            test=np.array([k for k,p in items]);probability=np.array([p for k,p in items]);support=action_probability_scores(probability)
            returns=data['returns'].copy();ready=(data['return_available']>0)&(data['return_available']<cutoff)
            ready&=(data['state_available']<cutoff)[:,None];returns[~ready]=np.nan
            train=all_ix[data['state_available'][all_ix]<cutoff]
            base=payoff_table(data['outcome'][all_ix],returns[all_ix],data['known_at'][all_ix])
            penalty=probability@base['error'];means={}
            means['future_table']=np.tile(base['mean'][None,:,:],(len(test),1,1))
            means['transition_table']=transition_payoffs(data,returns,base,train,test)
            for head,conditioned in (('context_ridge',True),('direct_ridge_control',False)):
                means[head],records=regress_payoffs(data,returns,train,test,conditioned=conditioned)
                fits.extend(dict(group=group,head=head,cutoff=cutoff,**v) for v in records)
            for head in heads:
                expected=np.einsum('ns,nsa->na',probability,means[head]);score=expected-penalty
                expected[~data['eligible'][test]]=-np.inf;score[~data['eligible'][test]]=-np.inf
                best=score.max(1);history=past[head]
                threshold=past_score_threshold([v['score'] for v in history],[v['known_at'] for v in history],cutoff)
                candidates=score.copy();candidates[support<70]=-np.inf;actions=candidates.argmax(1);selected=candidates[np.arange(len(test)),actions]
                if cutoff>=1672531200000:
                    for j,k in enumerate(test):saved.append(dict(group=group,head=head,index=int(k),known_at=int(data['known_at'][k]),
                        action=int(actions[j]),expected=float(expected[j,actions[j]]),score=float(selected[j]),
                        threshold=threshold,approved=bool(np.isfinite(selected[j]) and selected[j]>=threshold),
                        actual=float(data['returns'][k,actions[j]]) if data['eligible'][k,actions[j]] else None))
                history.extend(dict(score=float(v),known_at=int(data['known_at'][k])) for k,v in zip(test,best))
            print('payoff heads',group,dt.datetime.fromtimestamp(cutoff/1000,dt.timezone.utc).date(),'train',len(train),flush=True)
    return saved,fits,classifier_fits


def replay_heads(data,decisions,predictions,markets,raw,filters,*,signal_sides=None):
    groups=defaultdict(list)
    for r in predictions:groups[r['group'],r['head']].append(r)
    runs=[];curves={};trades=[]
    for (group,head),rows in groups.items():
        ds=defaultdict(list);approved=[r for r in rows if r['approved']]
        chosen=approved if signal_sides is None else [r for r in approved if signal_sides[r['index']]==decisions[r['index'],r['action']]['side']]
        for r in chosen:ds[str(data['asset'][r['index']])].append(decisions[r['index'],r['action']])
        for cost in (1,2):
            sleeves={}
            for a,bars in daily_bars(markets[group],group).items():
                rules=(dict(tick=0.,step=1.,min_qty=1.,min_notional=0.) if group=='etf_proxy' else filters[a].copy())
                rules.update(fee=.0005*cost,slippage=(.0015 if group=='etf_proxy' else .0002)*cost,continuous_clock=group=='crypto')
                s=replay_asset(bars,ds.get(a,[]),[] if group=='etf_proxy' else raw[a+'_funding'],initial=10000/len(markets[group]),rules=rules)
                s['start_at']=int(bars[0,0]);sleeves[a]=s
            summary,clocks,nav,tt=summarize_portfolio(sleeves,10000,continuous=True);rid=len(runs)
            runs.append(dict(id=rid,group=group,head=head,cost_multiplier=cost,approved=len(chosen),summary=summary,
                trigger_filter=signal_sides is not None,approved_before_trigger=len(approved),
                expected_net_R=float(np.mean([r['expected'] for r in chosen])) if chosen else None,
                actual_net_R=float(np.mean([r['actual'] for r in chosen])) if chosen else None))
            curves['times_'+str(rid)]=clocks;curves['nav_'+str(rid)]=nav;trades.extend(dict(run_id=rid,**t) for t in tt)
            print('profit',group,head,cost,'approved',len(chosen),'trades',len(tt),'return',round(summary['total_return'],6),flush=True)
    return runs,curves,trades


def paired_comparisons(runs,curves):
    out=[]
    for group in ('crypto','etf_proxy'):
        baseline=next(r for r in runs if r['group']==group and r['head']=='future_table' and r['cost_multiplier']==1 and not r.get('trigger_filter'))
        for row in runs:
            if row['group']!=group or row['cost_multiplier']!=1 or row['head']=='future_table' or row.get('trigger_filter'):continue
            a,b=row['id'],baseline['id'];clocks=curves['times_'+str(a)]
            if not np.array_equal(clocks,curves['times_'+str(b)]):raise ValueError('edge_comparison_calendar')
            delta=np.diff(np.log(np.r_[10000.,curves['nav_'+str(a)]]))-np.diff(np.log(np.r_[10000.,curves['nav_'+str(b)]]))
            groups=defaultdict(float)
            for t,v in zip(clocks,delta):groups[quarter(t)]+=float(v)
            values=np.array(list(groups.values()));draws=np.random.default_rng(311026).integers(0,len(values),(3000,len(values)))
            out.append(dict(group=group,head=row['head'],quarters=len(values),mean_quarter_log_excess=float(values.mean()),
                interval95=np.quantile(values[draws].mean(1),[.025,.975]).tolist()))
    return out


def selected_path_diagnostics(data,errors,source):
    original_trades=json.loads((REFERENCE/'trades.json').read_text());out=[]
    for e in errors:
        group=e['group'];run=next(r for r in source['runs'] if r['group']==group and r['model']=='tree'
            and r['policy']=='state70_top_decile' and r['cost_multiplier']==1)
        lookup={(str(data['asset'][v['index']]),int(data['known_at'][v['index']])):v for v in e['high_score_decomposition']}
        rows=[]
        for trade in original_trades:
            if trade['run_id']!=run['id']:continue
            item=lookup[trade['asset'],trade['known_at']];k=item['index'];a=item['action']
            hit=action_probability_scores(np.eye(len(STATE_NAMES))[[int(data['outcome'][k])]])[0,a]>0
            rows.append(dict(asset=trade['asset'],action=ACTIONS[a],current_state=STATE_NAMES[int(data['current_state'][k])],
                future_state=STATE_NAMES[int(data['outcome'][k])],support_state_hit=bool(hit),
                gross_pnl=trade['gross_pnl'],net_pnl=trade['net_pnl'],reason=trade['reason'],
                exited_before_future_state_known=bool(trade['exit_at']<int(data['state_available'][k]))))
        out.append(dict(group=group,trades=rows,state_hits=sum(r['support_state_hit'] for r in rows),
            losses_with_state_hit=sum(r['support_state_hit'] and r['net_pnl']<0 for r in rows),
            gross_losses_with_state_hit=sum(r['support_state_hit'] and r['gross_pnl']<0 for r in rows)))
    return out


def report(r):
    lines=['# 状态预测与利润来源：原因分解及收益映射对照','',
        '已消费历史的离线探索，保持既有概率/阈值/成本与风险边界，未接实盘。事后真实状态只用于诊断，不当可执行信号。','',
        '## 状态误差与收益误差','',
        '|市场|细状态准确率|复制当前状态|合并经济状态准确率|高分预计R|真实状态代入旧表R|实际R|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for x in r['errors']:
        d=x['decomposition_means'];lines.append(f"|{x['group']}|{x['fine']['accuracy']:.2%}|{x['copy_current_accuracy']:.2%}|{x['coarse']['accuracy']:.2%}|{d['expected']:.4f}|{d['oracle_state_table']:.4f}|{d['actual']:.4f}|")
    lines+=['','## 相同样本的期限对照','',
        '1/3期目标仍用原5期成熟时点限制训练，与原5期模型保持相同训练行/测试起点；较短期限不是利润证明。','',
        '|市场|未来期限|准确率|平衡准确率|Brier↓|','|---|---:|---:|---:|---:|']
    for x in r['horizons']:
        s=x['scores'];lines.append(f"|{x['group']}|{x['horizon']}|{s['accuracy']:.2%}|{s['balanced_accuracy']:.2%}|{s['brier']:.5f}|")
    lines+=['','## 固定概率下的收益映射实验','',
        'future_table为原表；transition_table加入当前→未来状态、50日期收缩；context_ridge加入已知上下文/状态交互；direct_ridge_control只在收益头去掉未来状态。后两者Ridge alpha=200固定。',
        '概率全部冻结为原浅树；相同加权均值误差扣减，仅比较收益均值映射。主阈值仍为支持概率≥70及保守净R≥max(0.10,过去得分90%分位)。',
        '四头逐季只用已成熟收益，2022重建八个浅树折用于阈值预热，2023起比较；原表必须重现上轮批准及净收益。','',
        '|市场/收益头|成本倍数|批准/实际交易|净收益|CAGR|收盘MDD|预计R/实际R|','|---|---:|---|---:|---:|---:|---|']
    for x in r['runs']:
        s=x['summary'];label=x['head']+(' + route trigger' if x.get('trigger_filter') else '')
        lines.append(f"|{x['group']}/{label}|{x['cost_multiplier']}|{x['approved']}/{s['trades']}|{s['total_return']:+.3%}|{s['cagr']:+.3%}|{s['mdd_close']:.3%}|{x['expected_net_R']}/{x['actual_net_R']}|")
    if 'paired_comparisons' in r:
        lines+=['','## 配对季度增量','',
            '新收益头相对原表，平均季度对数收益增量的季度整块95%区间；未校正多重比较，跨零不确认稳定优势。','',
            '|市场/头|季度数|平均增量|95%区间|','|---|---:|---:|---|']
        for x in r['paired_comparisons']:lines.append(f"|{x['group']}/{x['head']}|{x['quarters']}|{x['mean_quarter_log_excess']}|{x['interval95']}|")
    lines+=['','## 边界','',*['- '+x for x in r['limitations']],'',
        '概率分类与行动阈值是不同问题，参见[scikit-learn成本敏感决策示例](https://scikit-learn.org/stable/auto_examples/model_selection/plot_cost_sensitive_learning.html)。',
        '多次消费历史不可据赢家认证独立优势，参见[回测过拟合研究](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)。','']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.output.exists():p.error('retain old results; choose new directory')
    parent=load_npz(DAILY);data=load_npz(REFERENCE/'dataset.npz');source=json.loads((REFERENCE/'results.json').read_text());archive=json.loads((REFERENCE/'predictions.json').read_text())
    markets,_,_=load_markets();states={g:{a:market_state_machine(b) for a,b in book.items()} for g,book in markets.items()}
    raw=json.loads(RAW.read_text())['data'];filters=exchange_rules();full={g:all_bars(book,g) for g,book in markets.items()}
    check,decisions,_=make_panel(parent,markets,states,full,filters,raw)
    if any(not np.array_equal(v,check[k],equal_nan=True) if v.dtype.kind in 'fc' else not np.array_equal(v,check[k]) for k,v in data.items()):raise ValueError('edge_panel_drift')
    errors=error_diagnostics(data,archive,source);labels=label_diagnostics(parent,markets,states,data)
    horizons,horizon_fits=horizon_experiment(data,parent,markets,states,archive)
    horizons.extend(dict(group=x['group'],horizon=5,scores=x['fine']) for x in errors)
    predictions,payoff_fits,warmup_fits=payoff_experiment(data,archive,source)
    runs,curves,trades=replay_heads(data,decisions,predictions,markets,raw,filters)
    for row in runs:
        if row['head']!='future_table':continue
        old=next(v for v in source['runs'] if v['group']==row['group'] and v['model']=='tree' and v['policy']=='state70_top_decile' and v['cost_multiplier']==row['cost_multiplier'])
        if row['approved']!=old['approved_signals'] or abs(row['summary']['total_return']-old['summary']['total_return'])>1e-12:raise ValueError('edge_baseline_reproduction')
    signal_sides=np.array([states[str(g)][str(a)][markets[str(g)][str(a)][int(parent['bar_index'][o])].t]['route_side']
        for g,a,o in zip(data['group'],data['asset'],data['original_row'])])
    extra,extra_curves,extra_trades=replay_heads(data,decisions,predictions,markets,raw,filters,signal_sides=signal_sides)
    offset=len(runs)
    for row in extra:row['id']+=offset
    runs+=extra
    for k,v in extra_curves.items():name,index=k.rsplit('_',1);curves[name+'_'+str(int(index)+offset)]=v
    trades.extend(dict(t,run_id=t['run_id']+offset) for t in extra_trades)
    result=dict(research_only=True,orders_authorized=False,independent_oos=False,reference=str(REFERENCE),errors=errors,labels=labels,
        horizons=horizons,horizon_fits=horizon_fits,payoff_fits=payoff_fits,warmup_fits=warmup_fits,runs=runs,
        paired_comparisons=paired_comparisons(runs,curves),selected_paths=selected_path_diagnostics(data,errors,source),
        limitations=['概率分类改变期限/合并类别属于不同任务，不据更高准确率称为真实预测能力提高。',
            '事后真实状态代入旧表是诊断oracle，非可执行策略；误差分解依赖当前高分切片，不外推全市场。',
            '收益头仍只比较少量固定结构；过去的状态条件收益不能保证未来稳定，Ridge均值没有独立置信认证。',
            '为隔离均值映射，四头沿用相同旧误差扣减，它不是新回归器可信下界。',
            'route trigger只采用原状态机既有同侧突破/回踩/边界拒绝触发；它是收益映射初测后的定向补充，非独立验证，不据结果挑最优触发参数。',
            '币种日线2023至2026-10、ETF代理2023至2025，初始10,000；沿用1%袖套计划风险/1倍入场/真实资金费/5+2bp币种及5+15bp代理摩擦、双摩擦重跑。',
            'ETF代理非原生合约、历史交易规则和盘口未PIT认证，MDD仅收盘，已消费历史与多重比较限制继续适用。'])
    args.output.mkdir(parents=True);(args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    clean=[dict(r,score=r['score'] if np.isfinite(r['score']) else None,expected=r['expected'] if np.isfinite(r['expected']) else None,
        threshold=r['threshold'] if np.isfinite(r['threshold']) else None) for r in predictions]
    (args.output/'predictions.json').write_text(json.dumps(clean,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    (args.output/'trades.json').write_text(json.dumps(trades,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    np.savez_compressed(args.output/'equity.npz',**curves);(args.output/'report.md').write_text(report(result))


if __name__=='__main__':main()
